"""Validate exported/reference bundles; this is not a machining checker.

Run: uv run python scripts/validate_examples.py
Shared input definitions determine operation applicability and required joint debt;
finished-face coverage still uses only the original exported manifest.

Z pickups use stock_state.top_z for face = "top"; other named touch surfaces
must supply edge_mm in the zero recipe. Report values never define the edge.
"""

from __future__ import annotations

import functools
import hashlib
import json
import math
import re
import sys
import tomllib
from datetime import date
from fractions import Fraction
from html.parser import HTMLParser
from pathlib import Path
from types import SimpleNamespace

from prechips.findings import ALWAYS_REQUIRED
from prechips.inputs import load_bundle, operative_definitions
from prechips.joint_features import LABEL_PREFIX, fit, label, present, setup_span_mm
from prechips.kernel import run_geometry
from prechips.measurements import length_fact, nominal_length_mm
from prechips.model import UNIT_TOLERANCE, Plan, tolerance_requirements
from prechips.process_features import ACTIONS as PROCESS_ACTIONS
from prechips.process_features import ANGLE_TOLERANCE_DEG
from prechips.process_features import LABEL_PREFIX as PROCESS_PREFIX
from prechips.rules._bench import manual_bench
from prechips.rules.coordinates import (
    CENTRE_OPS,
    DRO_DEFAULT_STEP,
    HEIGHT_BANDS,
    LOCATED_KINDS,
    UNIT_MM,
)
from prechips.rules.geometry_common import _AXIAL_LATHE_ACTIONS as AXIAL_LATHE_ACTIONS
from prechips.rules.geometry_common import _TURNING_ACTIONS as TURNING_ACTIONS
from prechips.rules.geometry_common import TURNING_BLADE_KINDS
from prechips.rules.resolution import (
    LENGTH_TOLERANCE_MM,
    MANUAL,
    SAW_OPS,
    op_features,
    rough_leave,
    same_length,
    saw_setup,
)
from prechips.rules.resolution import resolve as resolve_item
from prechips.rules.resolution import uncertain as record_uncertain
from prechips.rules.speeds_feeds import AXIAL_FACING
from prechips.rules.stickout import support_state
from prechips.rules.tip_endpoints import (
    FACING,
    POCKETING,
    SAME_Z,
    cut_coverage,
    lineage,
    stock_states,
)
from prechips.rules.tip_endpoints import _covers_xy as covers_xy
from prechips.rules.turned_profile import AXIAL_KINDS, PROFILE_OPS, RADIUS_TOL_MM

ROOT = Path(__file__).resolve().parents[1]
EXAMPLES = ROOT / "examples"
PARTS = ("pivot-shaft", "rocker-arm", "pivot-bracket")
EXPECTED_EXIT = {
    "pivot-shaft": 0,
    "rocker-arm": 0,
    "pivot-bracket": 0,
    "cone-pivot-post/built-up.toml": 0,
}
# (bundle, plan, expected dir, exit, discriminating rule, modeled setups, setups the rule
# errors on). Setups outside the modeled set must render as partial pictures with debts.
GEOMETRY_CASES = (
    ("rocker-jaw-occluded", "plan.toml", "expected", 2, "accessibility", ("S3",), ("S3",)),
    ("pocket-reach", "plan.toml", "expected", 2, "reach", ("S2",), ("S2",)),
    ("pocket-reach", "long-reach.toml", "expected/long-reach", 0, None, ("S2",), ()),
    ("sharp-corner", "plan.toml", "expected", 2, "internal_corner_radius", ("S2",), ("S2",)),
    ("unclaimed-face", "plan.toml", "expected", 2, "coverage", ("S2",), ("S2",)),
    (
        "fixture-holds",
        "plan.toml",
        "expected",
        2,
        "accessibility",
        ("S1", "S2", "S3", "S4", "S5", "S6"),
        ("S2", "S3", "S4"),
    ),
    (
        "fixture-holds",
        "clash.toml",
        "expected/clash",
        2,
        "fixture_interference",
        ("S1", "S3"),
        ("S1", "S2"),
    ),
)
# Discriminating rules whose subject is the setup id rather than its op.
SETUP_GEOMETRY_RULES = {"vise", "thin_wall_under_clamp", "fixture_interference"}
STATUSES = {"pass", "error", "warn", "info", "unknown", "unsupported", "not_applicable"}
FEATURE_RULES = {"sizing", "op_chain", "blind_depth", "datum_consistency"}
SETUP_RULES = {
    "order",
    "hold_fields",
    "headroom",
    "envelope",
    "travel",
    "zero_check",
    "coordinates",
    "turned_profile",
    "stickout",
    "stock_diameter",
    "indexing",
}
SET_KINDS = {
    "endmill_set",
    "collet_set",
    "parallels_set",
    "center_drill_set",
    "drill_index",
    "drill_set",
    "tap_die_set",
    "tap_set",
    "reamers",
    "countersink_set",
    "qctp_set",
    "insert_holders",
    "micrometer_set",
    "lathe_tool_bits",
}
REFERENCE_KEYS = {
    "machine",
    "tool",
    "holder",
    "gauge",
    "fixture",
    "parallels",
    "support",
    "clamps",
    "riser",
    "support_blocks",
    "ref",
}
# These are plan-author decisions, not measurements awaiting an external source.
# RPM is deliberately absent: it still depends on sourced cutting data.
AUTHOR_CHOICE_FIELDS = {
    "form",
    "section_mm",
    "length_mm",
    "north_allowance_mm",
    "south_grip_mm",
    "top_z",
    "bottom_z",
    "edge_mm",
    "grip_mm",
    "jaw_above_parallels_mm",
    "stop",
    "clamp",
    "fixed_jaw",
    "check_jog_mm",
    "paper_mm",
    "direction",
    "to_z",
    "stock_to_leave_mm",
    "rough_allowance_mm",
    "depth_mm",
    "exit_mm",
    "coolant",
    "contour",
    "method",
    "step_deg",
    "step_mm",
}
# The selected combined drill and countersink's own fact behind each drilled-centre size
# (Machinery's Handbook Table 6 drill D, drill length C, countersink angle, body A) and
# the pilot point that closes the centre.
CENTRE_TOOL_FACTS = {
    "drill_dia_mm": "dia",
    "drill_length_mm": "pilot_len",
    "countersink_angle_deg": "angle_deg",
    "body_dia_mm": "shank",
    "point_angle_deg": "point_angle",
}
# The cutting-data operation an action's speed (and deep-hole derate) row is keyed by.
CUT_OPERATIONS = {
    "rough_face": "face",
    "finish_face": "face",
    **dict.fromkeys(
        ("rough_profile", "finish_profile", "rough_pocket", "finish_pocket", "pocket"), "profile"
    ),
}
# The hole actions whose tip a hole feature's blind_depth row places, and the feature
# kinds they place it for (a centre hole's row is its center_drill's alone).
ENDPOINT_OPS = frozenset({"spot", "drill", "ream", "tap", "counterbore", "bore"})
ENDPOINT_KINDS = frozenset({"hole", "counterbore", "thread", "threaded_hole"})


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def numeric(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def near(actual, expected, where: str) -> None:
    if numeric(expected):
        require(numeric(actual), f"{where}: numeric result lost to {actual!r}")
        require(
            math.isclose(actual, expected, rel_tol=1e-10, abs_tol=1e-8),
            f"{where}: {actual!r} != {expected!r}",
        )
    else:
        require(actual == "unknown", f"{where}: unresolved input must yield unknown")


def check_author_choices(plan: dict) -> None:
    def walk(value, path: str, authored: bool = False) -> None:
        if isinstance(value, dict):
            for key, child in value.items():
                walk(child, f"{path}.{key}", authored or key in AUTHOR_CHOICE_FIELDS)
        elif isinstance(value, list):
            for index, child in enumerate(value):
                label = (
                    child.get("id", child.get("op", index)) if isinstance(child, dict) else index
                )
                walk(child, f"{path}[{label}]", authored)
        else:
            require(
                not (authored and value == "unknown"),
                f"{path}: author's choice must be stated, not unknown",
            )

    walk(plan, "plan")


def canonical(value: dict | list) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n"
    ).encode("utf-8")


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def fraction(value: str) -> Fraction | None:
    try:
        return Fraction(value.removesuffix("in").replace("-", "/"))
    except (ValueError, ZeroDivisionError):
        return None


def entries_for(inventory: dict) -> dict:
    entries = {}
    for category in ("machines", "fixtures", "holders", "tools", "gauges"):
        for name, item in inventory.get(category, {}).items():
            require(name not in entries, f"duplicate inventory identity {name}")
            entries[name] = item
    for name, machine in inventory.get("machines", {}).items():
        for accessory in machine.get("standard_accessories", []) + machine.get("included", []):
            entries.setdefault(accessory, {"ref": name})
    return entries


def resolves(ref: str, entries: dict) -> bool:
    if ref in entries:
        item = entries[ref]
        return item.get("present") is not False and item.get("kind") not in SET_KINDS
    if "/" not in ref:
        return False
    root, selected = ref.split("/", 1)
    entry = entries.get(root, {})
    if not entry or entry.get("present") is False:
        return False
    members = entry.get("members", {})
    if isinstance(members, dict) and selected in members:
        # An explicitly declared member resolves by identity; an "unknown" member
        # resolves to an unverified identity rather than a missing one.
        member = members[selected]
        return member == "unknown" or (
            isinstance(member, dict) and member.get("present") is not False
        )
    if selected in entry.get("included", []) + entry.get("standard_accessories", []):
        return True
    kind = entry.get("kind")
    if kind in {"collet_set", "parallels_set", "countersink_set"}:
        size = fraction(selected)
        choices = entry.get("sizes_in", entry.get("heights_in", []))
        return size is not None and size in {fraction(str(v)) for v in choices}
    if kind == "endmill_set":
        match = re.fullmatch(r"(.+in)-(2|4)fl", selected)
        if not match:
            return False
        size = fraction(match[1])
        return size is not None and size in {
            fraction(str(v)) for v in entry.get("sizes_in", {}).get("2_and_4_flute", [])
        }
    if kind == "center_drill_set":
        return selected.removeprefix("#").isdigit() and int(selected.removeprefix("#")) in (
            entry.get("sizes", [])
        )
    if kind == "drill_index":
        numbered = re.fullmatch(r"#(\d{1,2})", selected)
        if numbered:
            return 1 <= int(numbered[1]) <= 60
        if re.fullmatch("[A-Z]", selected):
            return True
        size = fraction(selected)
        return (
            size is not None
            and Fraction(1, 16) <= size <= Fraction(1, 2)
            and (size * 64).denominator == 1
        )
    if kind == "qctp_set":
        choices = {
            "1-turning-facing": "#1 turning/facing",
            "2-boring-turning-facing": "#2 boring/turning/facing",
            "4-heavy-boring": "#4 heavy boring",
            "7-parting": "#7 parting (1/2 blade)",
        }
        return choices.get(selected, selected) in entry.get("holders", {})
    if kind == "insert_holders":
        return selected in entry.get("styles", [])
    if kind == "micrometer_set":
        return selected.removesuffix("in") in entry.get("ranges_in", [])
    return False


def uncertain(ref: str, entries: dict, seen: tuple = ()) -> bool:
    root = ref if ref in entries else ref.split("/", 1)[0]
    if root not in entries or root in seen:
        return True
    members = entries[root].get("members", {})
    member = ref.split("/", 1)[1] if ref != root else None
    if isinstance(members, dict) and member is not None and members.get(member) == "unknown":
        return True

    def walk(value) -> bool:
        if isinstance(value, dict):
            if (
                value.get("verify") is True
                or value.get("present") == "unknown"
                or "verify" in str(value.get("coverage", "")).lower()
            ):
                return True
            if "ref" in value and uncertain(value["ref"], entries, (*seen, root)):
                return True
            return any(walk(v) for v in value.values())
        return isinstance(value, list) and any(walk(v) for v in value)

    return walk(entries[root])


def selected_refs(plan: dict):
    """Every inventory identity the plan selects that its ``tool_resolves`` findings
    resolve: all of the plan but the prepared blank's gauges, which its
    ``prepared_blank`` finding reads instead (:func:`check_prepared_blank`)."""

    def walk(value):
        if isinstance(value, dict):
            if "ref" in value:
                ref = value["ref"]
                if "item" in value:
                    ref += "/" + str(value["item"])
                if ref != "unknown":
                    yield ref
            for key, child in value.items():
                if key in REFERENCE_KEYS - {"ref"} and isinstance(child, str):
                    if child not in {"unknown", "not_applicable", "none"}:
                        yield child
                elif key in {"checks", "missing_requirements"} and isinstance(child, dict):
                    yield from (v for v in child.values() if v != "unknown")
                elif key not in {"ref", "item"}:
                    yield from walk(child)
        elif isinstance(value, list):
            for child in value:
                yield from walk(child)

    stock = plan.get("stock")
    if isinstance(stock, dict):
        plan = {**plan, "stock": {k: v for k, v in stock.items() if k != "prepared"}}
    return set(walk(plan))


def tool_diameter(ref: str, entries: dict):
    root, _, member = ref.partition("/")
    entry = entries.get(root, {})
    if entry.get("kind") == "endmill_set":
        match = re.fullmatch(r"(.+in)-(2|4)fl", member)
        size = fraction(match[1]) if match else None
        return float(size) * 25.4 if size is not None else "unknown"
    if entry.get("kind") == "drill_index":
        # A declared nominal (letter, number or fractional) outranks the fraction's size.
        size = fraction(member)
        fallback = float(size) * 25.4 if size is not None else "unknown"
        return entry.get("nominal_dia_mm", {}).get(member, fallback)
    return tool_field(ref, "dia", entries)


def tool_record(ref: str, key: str, entries: dict):
    """The selected tool's own authored ``key`` (a member's over its set's), unwrapped
    from neither ``{value, ...}`` nor its units."""
    root, _, member = ref.partition("/")
    entry = entries.get(root, {})
    members = entry.get("members", {})
    selected = members.get(member, {}) if isinstance(members, dict) else {}
    if not isinstance(selected, dict):
        return "unknown"
    return selected.get(key, entry.get(key, "unknown"))


def tool_field(ref: str, key: str, entries: dict):
    root, _, member = ref.partition("/")
    if key == "flutes" and entries.get(root, {}).get("kind") == "endmill_set":
        match = re.fullmatch(r"(.+in)-(2|4)fl", member)
        return int(match[2]) if match else "unknown"
    value = tool_record(ref, key, entries)
    return value.get("value", "unknown") if isinstance(value, dict) else value


def tool_length_mm(ref: str, field: str, entries: dict):
    value = tool_field(ref, f"{field}_mm", entries)
    if numeric(value):
        return value
    inches = fraction(str(tool_field(ref, f"{field}_in", entries)))
    if inches is not None:
        return float(inches) * 25.4
    value = tool_field(ref, field, entries)
    units = tool_field(ref, "units", entries)
    if numeric(value) and units in {"mm", "in", "inch"}:
        return value if units == "mm" else value * 25.4
    return "unknown"


def accepted(fact) -> bool:
    """A fact is accepted unless its own record declares verification debt: ``verify``
    true or unknown, or a ``measured`` record short of its by, date and instrument."""
    if not isinstance(fact, dict):
        return True
    if fact.get("verify") is True or fact.get("verify") == "unknown":
        return False
    measured = fact.get("measured", "unknown")
    if measured == "unknown":
        return True
    if not isinstance(measured, dict) or set(measured) != {"by", "date", "instrument"}:
        return False
    try:
        return date.fromisoformat(measured["date"]).isoformat() == measured["date"]
    except (TypeError, ValueError):
        return False


def centre_tool_facts(ref: str, entries: dict) -> dict:
    """The selected centre drill's own accepted D, C, countersink angle, body and point
    (``CENTRE_TOOL_FACTS``) in mm and degrees; any other fact is unknown."""
    facts = {}
    for key, field in CENTRE_TOOL_FACTS.items():
        if key.endswith("_deg"):
            value, names = tool_field(ref, field, entries), (field,)
        else:
            value = tool_length_mm(ref, field, entries)
            names = (field + "_mm", field + "_in", field)
        trusted = all(accepted(tool_record(ref, name, entries)) for name in names)
        facts[key] = value if numeric(value) and trusted else "unknown"
    return facts


def frame_point(point: list, frame: dict) -> list:
    if frame == "unknown":
        return ["unknown"] * 3
    result = []
    for axis in ("x", "y", "z"):
        terms = [
            (point[i], frame["origin"][i], frame[axis][i]) for i in range(3) if frame[axis][i] != 0
        ]
        result.append(
            sum((p - origin) * scale for p, origin, scale in terms)
            if all(numeric(p) for p, _, _ in terms)
            else "unknown"
        )
    return result


def model_point(point: list, frame: dict) -> list:
    if frame == "unknown":
        return ["unknown"] * 3
    result = []
    for i in range(3):
        terms = [
            (point[j], frame[axis][i])
            for j, axis in enumerate(("x", "y", "z"))
            if frame[axis][i] != 0
        ]
        result.append(
            frame["origin"][i] + sum(value * scale for value, scale in terms)
            if numeric(frame["origin"][i]) and all(numeric(value) for value, _ in terms)
            else "unknown"
        )
    return result


def plan_frames(plan: dict, features: dict) -> dict:
    """Plan-owned setup frames; an exported name may never be shadowed."""
    planned = plan.get("frames", {})
    require(isinstance(planned, dict), "plan.frames must be a table of frames")
    exported = features["frames"] if isinstance(features["frames"], dict) else {}
    shadowed = sorted(set(planned) & set(exported))
    require(not shadowed, f"plan frames shadow exported frames {shadowed}")
    return planned


def setup_frame(setup: dict, plan: dict, features: dict):
    """Independent lookup: the exported manifest frame, else the plan-owned frame."""
    exported = features["frames"] if isinstance(features["frames"], dict) else {}
    name = setup.get("frame", "unknown")
    if name in exported:
        return exported[name]
    return plan_frames(plan, features).get(name, "unknown")


def check_frames(features: dict, plan: dict) -> None:
    planned = plan_frames(plan, features)
    for name, frame in planned.items():
        require(frame.get("binding") is not None, f"plan frame {name}: binding must be stated")
        require(
            "AUTHOR'S CHOICE" in frame.get("cite", [])
            and "AUTHOR'S CHOICE" in frame.get("note", ""),
            f"plan frame {name}: author's choice must be distinguished from source geometry",
        )
    exported = features["frames"] if isinstance(features["frames"], dict) else {}
    for name, frame in [*exported.items(), *planned.items()]:
        if frame == "unknown":
            continue
        for key in ("origin", "x", "y", "z"):
            require(
                isinstance(frame.get(key), list)
                and len(frame[key]) == 3
                and all(numeric(v) for v in frame[key]),
                f"frame {name}.{key}: numeric triple",
            )
        axes = [frame[k] for k in ("x", "y", "z")]
        for i in range(3):
            for j in range(3):
                near(
                    sum(a * b for a, b in zip(axes[i], axes[j], strict=True)),
                    1 if i == j else 0,
                    f"frame {name}: orthonormal basis",
                )
        x, y, z = axes
        cross = [x[1] * y[2] - x[2] * y[1], x[2] * y[0] - x[0] * y[2], x[0] * y[1] - x[1] * y[0]]
        for actual, expected in zip(cross, z, strict=True):
            near(actual, expected, f"frame {name}: right-handed basis")


def read_report(path: Path) -> dict:
    def invalid_constant(value):
        raise ValueError(f"non-finite JSON value {value}")

    report = json.loads(path.read_bytes(), parse_constant=invalid_constant)
    require(path.read_bytes() == canonical(report), f"{path}: noncanonical JSON")
    payload = {k: v for k, v in report.items() if k != "hash"}
    require(
        report.get("hash") == hashlib.sha256(canonical(payload)).hexdigest(),
        f"{path}: report hash mismatch",
    )
    require(
        report.get("verification")
        == ("checked" if report.get("expected_exit") == 0 else "planned"),
        f"{path}: unearned readiness",
    )
    require(report.get("rules_version") == "m5-rev9", f"{path}: stale rule catalogue")
    previous = None
    for finding in report["findings"]:
        key = finding["rule"], finding["subject"]
        require(previous is None or previous < key, f"{path}: duplicate/unsorted finding {key}")
        previous = key
        require(finding["status"] in STATUSES, f"{key}: invalid status")
        require(isinstance(finding.get("numbers"), dict), f"{key}: missing numbers")
        require(isinstance(finding.get("cite"), list) and finding["cite"], f"{key}: missing cite")
        require(
            isinstance(finding.get("message"), str) and finding["message"],
            f"{key}: missing finding sentence",
        )
        require("severity" not in finding, f"{key}: obsolete severity vocabulary")
    return report


def input_paths(folder: Path, plan: dict, plan_filename: str = "plan.toml") -> dict:
    paths = {"plan": folder / plan_filename, "features": folder / plan["features"]}
    for key, field in (
        ("inventory", "inventory"),
        ("shop_policy", "policy"),
        ("cutting_data", "cutting_data"),
    ):
        paths[key] = (folder / plan["paths"][field]).resolve()
    features = tomllib.loads(paths["features"].read_text(encoding="utf-8"))
    step = features.get("step", plan.get("step", plan.get("paths", {}).get("step")))
    if step and step != "unknown":
        base = paths["features"].parent if "step" in features else folder
        paths["step"] = (base / step).resolve()
    for path in paths.values():
        require(path.is_relative_to(EXAMPLES), f"input escapes examples: {path}")
    return paths


def required_finding(finding: dict, policy: dict, plan: dict, features: dict) -> bool:
    """Match checker readiness, including non-waivable joint and centre-support rules.
    Every input is the validator's own: a ``"*"`` subject is only ever the coverage row
    of a rule the policy selects (:func:`required_subjects`), so it is required by that
    selection, never by the ``numbers.required`` the report prints on it."""
    if finding["rule"] in ALWAYS_REQUIRED:
        return True
    required = policy.get("required", "unknown")
    if required == "unknown":
        return True
    selector = required.get(finding["rule"])
    subject = finding["subject"]
    if selector is None:
        return False
    if subject == "*" or selector == "*":
        return True
    if isinstance(selector, list):
        return subject in selector
    if selector == "setups":
        return subject in {setup["id"] for setup in plan["setups"]}
    if selector in {"holes", "toleranced_features"}:
        feature = operative_definitions(plan, features).get(subject.split(":", 1)[0], {})
        if selector == "holes":
            return feature.get("kind") in {"hole", "counterbore", "thread"}
        return bool(tolerance_requirements(feature))
    return subject == selector or subject.startswith(selector + ":")


def required_subjects(policy: dict, plan: dict, features: dict, rules: dict) -> dict:
    """``{rule: subjects}`` the policy's ``required`` selection must cover, as the checker
    derives them (``rules.required_coverage``) from the plan, the manifest and the rules'
    own subjects (``rules``: rule to the set of reported subjects): a list names its
    subjects, ``setups`` every setup, ``holes``/``toleranced_features`` the operative
    features of that kind, ``"*"`` (or a selection matching nothing) at least one subject,
    else the selector itself. An unknown policy requires its ``required_policy`` row."""
    required = policy.get("required", "unknown")
    if required == "unknown":
        required = {"required_policy": "*"}
    definitions = operative_definitions(plan, features)
    result = {}
    for name, selector in required.items():
        actual = rules.get(name, set())
        if isinstance(selector, list):
            subjects = list(selector)
        elif selector == "setups":
            subjects = [setup["id"] for setup in plan["setups"]]
        elif selector in {"holes", "toleranced_features"}:
            subjects = [
                feature
                for feature, item in definitions.items()
                if (
                    item.get("kind") in {"hole", "counterbore", "thread"}
                    if selector == "holes"
                    else bool(tolerance_requirements(item))
                )
            ]
        elif selector == "*":
            subjects = [] if actual else ["*"]
        else:
            subjects = [selector]
        if not subjects and not actual:
            subjects = ["*"]
        result[name] = subjects
    return result


def check_required_coverage(policy: dict, plan: dict, features: dict, keys) -> None:
    """Every subject the policy requires has a finding (itself, one of its requirements,
    or the checker's unknown coverage row): a report cannot reach readiness by leaving a
    required subject out."""
    rules = {}
    for rule, subject in keys:
        rules.setdefault(rule, set()).add(subject)
    for rule, subjects in required_subjects(policy, plan, features, rules).items():
        for subject in subjects:
            require(
                any(
                    value == subject or value.startswith(subject + ":")
                    for value in rules.get(rule, ())
                ),
                f"{rule}:{subject}: the policy requires it and no finding covers it",
            )


def report_exit(report: dict, policy: dict, plan: dict, features: dict) -> int:
    if any(f["status"] == "error" for f in report["findings"]):
        return 2
    if any(f["numbers"].get("kernel_unavailable") is True for f in report["findings"]):
        return 4
    required = policy.get("required", "unknown")
    if required == "unknown":
        return 4
    if any(
        required_finding(f, policy, plan, features)
        and f["status"] in {"unknown", "unsupported", "warn"}
        for f in report["findings"]
    ):
        return 4
    if set(required) - {finding["rule"] for finding in report["findings"]}:
        return 4
    return 0


def check_subjects(plan: dict, features: dict, findings: dict, inventory: dict) -> None:
    Plan.model_validate(plan)
    definitions = operative_definitions(plan, features)

    def has(rule: str, subject: str) -> None:
        require((rule, subject) in findings, f"missing finding {rule}:{subject}")

    for name, feature in features["features"].items():
        requirements = feature.get("requirements")
        require(
            isinstance(requirements, list) and len(requirements) == len(set(requirements)),
            f"{name}: invalid requirements",
        )
        for requirement in requirements:
            if requirement != "unknown":
                require(requirement in feature, f"{name}: omitted required field {requirement}")
        require(
            feature.get("faces") == "unknown" or isinstance(feature.get("faces"), list),
            f"{name}: faces must be set or unknown",
        )
        require(
            not isinstance(feature.get("faces"), list)
            or all(
                not str(face).startswith((LABEL_PREFIX, PROCESS_PREFIX))
                for face in feature["faces"]
            ),
            f"{name}: transient joint or preparation labels cannot name finished STEP faces",
        )
        if requirements:
            require(isinstance(feature.get("precision"), dict), f"{name}: per-dimension precision")
        has("datum_consistency", name)
    for name, feature in definitions.items():
        for rule in FEATURE_RULES - {"datum_consistency"}:
            has(rule, name)
        requirements = feature.get("requirements", "unknown")
        tolerances = set(tolerance_requirements(feature)) - {"unknown"}
        if requirements == "unknown" or "unknown" in requirements:
            subject = f"{name}:unknown"
            has("inspection", subject)
            require(
                findings["inspection", subject]["status"] == "unknown",
                f"{subject}: unresolved requirement must remain unknown",
            )
        if not tolerances and requirements != "unknown" and "unknown" not in requirements:
            has("inspection", name)
        for requirement in tolerances:
            subject = f"{name}:{requirement}"
            has("inspection", subject)
            finishing = [
                op
                for setup in plan["setups"]
                for op in setup["ops"]
                if name in op_features(op) and requirement in op.get("checks", {})
            ]
            require(
                finishing or findings["inspection", subject]["status"] == "error",
                f"{subject}: no check entry or report error",
            )
    setups = plan.get("setups")
    require(isinstance(setups, list) and setups, "empty plan setups")
    ids = [setup["id"] for setup in setups]
    require(len(ids) == len(set(ids)), "duplicate setup id")
    for setup in setups:
        sid = setup["id"]
        require(
            setup["frame"] in features["frames"] or setup["frame"] in plan_frames(plan, features),
            f"{sid}: missing frame",
        )
        require(setup.get("ops"), f"{sid}: empty operations")
        require(isinstance(setup.get("stock_state"), dict), f"{sid}: missing stock state")
        require(isinstance(setup.get("hold"), dict), f"{sid}: missing hold")
        bench = manual_bench(inventory, setup)
        if saw_setup(setup):
            # A dedicated saw setup locates its cut by cut_plane; no spindle zero is set.
            has("zero_check", sid)
            require(
                findings["zero_check", sid]["status"] == "not_applicable"
                and findings["zero_check", sid]["numbers"] == {"frame": setup["frame"]},
                f"{sid}: saw setup zero waiver must name its frame",
            )
        elif bench is None:
            require(isinstance(setup.get("zero"), dict), f"{sid}: missing zero")
            axes = ("x", "z") if setup["machine"] == "PM-1127VF-LB" else ("x", "y", "z")
            for axis in axes:
                recipe = setup["zero"].get(axis)
                require(
                    isinstance(recipe, dict) and "check_jog_mm" in recipe,
                    f"{sid}: missing {axis} check jog",
                )
            require("retouch_after" in setup["zero"]["z"], f"{sid}: missing retouch contract")
        else:
            # Manual bench fit/inspect work sets no DRO zero; the screens say so by name.
            for rule in ("zero_check", "coordinates", "headroom"):
                has(rule, sid)
                require(
                    findings[rule, sid]["status"] == "not_applicable"
                    and findings[rule, sid]["numbers"] == bench,
                    f"{sid}: {rule} must name the manual bench facts that waive it",
                )
        for rule in SETUP_RULES:
            has(rule, sid)
        ops = [op["op"] for op in setup["ops"]]
        require(len(ops) == len(set(ops)), f"{sid}: duplicate operation number")
        for op in setup["ops"]:
            if op["do"] not in SAW_OPS or "feature" in op:
                names = op_features(op)
                require(names and set(names) <= definitions.keys(), f"{sid}: undeclared feature")
            has("speeds_feeds", f"{sid}:{op['op']}")
            has("turning_deflection", f"{sid}:{op['op']}")
            has("engagement", f"{sid}:{op['op']}")
            if op["do"] not in MANUAL:
                if "tool" in op and op["do"] not in SAW_OPS:
                    require("holder" in op, f"{sid}:{op['op']}: omitted holder")
                has("tool_resolves", f"{sid}:{op['op']}")
        if isinstance(setup.get("stock_in"), list):
            has("joint_assembly", sid)
            if setup["joint"]["kind"] == "cylindrical":
                has("joint_fit", sid)


def check_inspection_declarations(plan: dict, features: dict, findings: dict) -> None:
    definitions = operative_definitions(plan, features)
    for setup in plan["setups"]:
        for op in setup["ops"]:
            if op.get("do") in SAW_OPS and "feature" not in op:
                continue  # a stock cut-off names no feature and exports no requirement
            # A multi-feature inspect op checks a requirement any named feature exports.
            names = op_features(op)
            exported = set()
            for name in names:
                requirements = definitions[name].get("requirements", "unknown")
                exported |= set(requirements) if isinstance(requirements, list) else set()
            label = "/".join(names)
            for requirement in op.get("checks", {}):
                require(
                    requirement in exported,
                    f"{setup['id']}:{op['op']}: {label} has no requirement {requirement}",
                )
            for requirement in op.get("missing_requirements", {}):
                require(
                    requirement not in exported,
                    f"{setup['id']}:{op['op']}: {label}.{requirement} is an exported requirement",
                )
                for name in names:
                    subject = f"{name}:{requirement}"
                    row = findings.get(("inspection", subject), {})
                    require(
                        row.get("status") == "unknown"
                        and row.get("numbers", {}).get("missing_requirement") is True,
                        f"{subject}: missing requirement inspection must remain explicitly unknown",
                    )


def independent_kernel(plan_path: Path):
    """The geometry kernel's facts for the plan at ``plan_path``, as a zero-argument call:
    this validator's own bundle load and kernel run (``prechips.kernel.run_geometry``),
    measured from that plan and its manifest-bound STEP bytes and keyed by them, made on
    the first call and kept. No report value enters it; a run that is not ``ok`` measures
    nothing (:func:`measured_setup`)."""
    return functools.cache(lambda: run_geometry(load_bundle(plan_path)))


def measured_setup(kernel, sid: str) -> dict:
    """Setup ``sid``'s facts from an ``ok`` independent kernel run ``kernel``
    (:func:`independent_kernel`), else empty."""
    facts = kernel()
    if not isinstance(facts, dict) or facts.get("status") != "ok":
        return {}
    setups = facts.get("setups")
    measured = setups.get(sid) if isinstance(setups, dict) else None
    return measured if isinstance(measured, dict) else {}


def kernel_join(kernel, setup: dict) -> tuple:
    """``(status, numbers)``: the ``joint_assembly`` finding the validator's own kernel run
    (``kernel``, :func:`independent_kernel`) derives for the assembly ``setup``. A run that
    is not ``ok`` names its status (``kernel_status``, plus ``kernel_unavailable`` when
    the kernel is missing) and is an error only when it errored, else unknown; an ``ok``
    run refusing the join is an error, one leaving its joined stock unknown or deriving
    none for the setup (no setup facts at all included) unknown, else pass, with that
    setup's completed joint features."""
    facts = kernel()
    facts = facts if isinstance(facts, dict) else {}
    run = facts.get("status")
    if run != "ok":
        numbers = {"kernel_status": run or "unknown"}
        if facts.get("kernel_unavailable") is True:
            numbers["kernel_unavailable"] = True
        return ("error" if run == "error" else "unknown"), numbers
    setups = facts.get("setups")
    detail = setups.get(setup["id"]) if isinstance(setups, dict) else None
    detail = detail if isinstance(detail, dict) else {}
    status = (
        "error"
        if detail.get("assembly_error")
        else "unknown"
        if detail.get("stock_reason") or "stock_bbox_mm" not in detail
        else "pass"
    )
    numbers = {
        "joint": setup["joint"]["kind"],
        "stock_in": list(setup["stock_in"]),
        "completed_joint_features": detail.get("completed_joint_features", "unknown"),
    }
    return status, numbers


def check_joint_declarations(plan: dict, features: dict, findings: dict, kernel) -> None:
    """Keep assembly identities and unresolved joint geometry explicit in the report. Every
    assembly's join verdict and its evidence, kernel availability included, are exactly
    those the validator's own kernel run derives (:func:`kernel_join`); nothing in the
    report decides which applies."""
    bundle = SimpleNamespace(plan=plan, features=features)
    for setup in plan["setups"]:
        if not isinstance(setup.get("stock_in"), list):
            continue
        sid = setup["id"]
        joint = setup["joint"]
        assembly = findings["joint_assembly", sid]
        status, numbers = kernel_join(kernel, setup)
        require(
            assembly["status"] == status,
            f"{sid}: joint assembly verdict differs from the validator's own kernel join",
        )
        require(
            assembly["numbers"] == numbers,
            f"{sid}: joint assembly evidence differs from the validator's own kernel join",
        )
        if joint["kind"] != "cylindrical":
            continue
        result = fit(bundle, setup)
        engagement = result["engagement"]
        expected = {
            "socket": label(joint["socket"]),
            "spigot": label(joint["spigot"]),
            "fit": joint["fit"],
            "method": joint["method"],
            "band_mm": result["band_mm"],
            "guaranteed_mm": result["guaranteed_mm"],
            "engagement_mm": engagement["depth_mm"] if engagement else "unknown",
            "engagement_dia_mm": engagement["diameter_mm"] if engagement else "unknown",
            "violations": result["violations"],
            "missing": result["missing"],
        }
        if joint["method"] == "retaining_compound":
            expected.update(
                cure_time_min=joint["cure_time_min"], surface_prep=joint["surface_prep"]
            )
        row = findings["joint_fit", sid]
        require(row["numbers"] == expected, f"{sid}: joint fit evidence differs from the plan")
        status = "unknown" if result["missing"] else "error" if result["violations"] else "pass"
        require(row["status"] == status, f"{sid}: joint fit status hides declared geometry debt")
        if result["missing"]:
            require(
                assembly["status"] in {"unknown", "unsupported", "error"},
                f"{sid}: unresolved joint geometry cannot approve the assembly",
            )


def check_references(plan: dict, entries: dict, findings: dict) -> list:
    missing = []
    for ref in sorted(selected_refs(plan)):
        key = "tool_resolves", ref
        require(key in findings, f"missing reference finding for {ref}")
        finding = findings[key]
        if not resolves(ref, entries):
            require(
                finding["status"] == "error" and finding["numbers"].get("reference") == ref,
                f"{ref}: missing item must have exact named error",
            )
            missing.append(ref)
        elif uncertain(ref, entries):
            require(finding["status"] == "unknown", f"{ref}: inherited verify must be unknown")
        else:
            require(finding["status"] == "pass", f"{ref}: available identity must resolve")
    return missing


PREPARED_SIZE_CHECKS = ("length", "section_0", "section_1")
PREPARED_FORM_CHECKS = ("flat", "square", "parallel")
PREPARED_DECLARED = ("origin_mm", "section_mm", "length_mm", "tolerance_mm")
STATUS_RANK = {"pass": 0, "unknown": 1, "error": 2}
# The gauges that read a size across two faces (inspection's sizing kinds), and those
# that read a face's form against a limit.
PREPARED_SIZE_GAUGES = frozenset(
    {
        "caliper",
        "micrometer",
        "micrometer_set",
        "pin_gauge",
        "pin_gauge_set",
        "bore_gauge",
        "height_gauge",
        "depth_gauge",
        "cmm",
    }
)
PREPARED_FORM_GAUGES = frozenset({"dial_indicator", "dial_test_indicator", "height_gauge", "cmm"})
# A made face this close to a blank axis is square to it; the kernel's stock may leave
# this fraction of its box unfilled (boolean round-off), and no more.
PREPARED_SQUARE = 1e-6
PREPARED_FULL = 1e-6


def vector_of(value, size: int = 3) -> list | None:
    """``size`` numbers as floats, else None."""
    if isinstance(value, list) and len(value) == size and all(map(numeric, value)):
        return [float(v) for v in value]
    return None


def stock_lineage(plan: dict, sid) -> set:
    """Setup ``sid`` and every earlier setup whose output material flows into it."""
    setups = {setup["id"]: setup for setup in plan.get("setups", [])}
    seen, pending = set(), [sid]
    while pending:
        current = pending.pop()
        if not isinstance(current, str) or current in seen or current not in setups:
            continue
        seen.add(current)
        refs = setups[current].get("stock_in")
        pending.extend(refs if isinstance(refs, list) else [refs])
    return seen


def blank_axes(stock: dict) -> list | None:
    """The root stock's unit length, section and third axes, or None when unknown."""
    axis, across = vector_of(stock.get("axis")), vector_of(stock.get("section_axis"))
    if axis is None or across is None:
        return None
    third = [
        axis[1] * across[2] - axis[2] * across[1],
        axis[2] * across[0] - axis[0] * across[2],
        axis[0] * across[1] - axis[1] * across[0],
    ]
    units = [axis, across, third]
    if (
        any(abs(dot(u, u) - 1.0) > PREPARED_SQUARE for u in units)
        or abs(dot(axis, across)) > PREPARED_SQUARE
    ):
        return None
    return units


def blank_box(origin: list, sizes: list, axes: list) -> list:
    """``[low, high]`` along each blank axis (length, section[0], section[1]), model mm."""
    return [[dot(origin, u), dot(origin, u) + size] for u, size in zip(axes, sizes, strict=True)]


def blank_misfit(box: list, declared: list, allowed: list) -> bool:
    """Whether any blank axis of ``box`` lies off the ``declared`` one (either end or its
    size) by more than that axis's tolerance."""
    return any(
        max(abs(low - want_low), abs(high - want_high), abs((high - low) - (want_high - want_low)))
        > tol + 1e-9
        for (low, high), (want_low, want_high), tol in zip(box, declared, allowed, strict=True)
    )


def blank_cut(plan: dict, kernel, receiver: str, axes, declared, allowed, numbers) -> str:
    """What the validator's own kernel run (``kernel``, :func:`independent_kernel`) says
    the receiver's ``stock_in`` setup hands on: the declared box within each tolerance and
    filling it is a pass, a different or gouged box an error. A blank taken as supplied
    (``stock_in = "stock"``) is the analytic box itself; no ok run, no handed-on stock or
    a blank off the model axes leaves the cut unknown."""
    source = next(
        (s.get("stock_in", "unknown") for s in plan["setups"] if s["id"] == receiver), "unknown"
    )
    if source == "stock":
        return "pass"
    facts = kernel() if isinstance(source, str) and source != "unknown" else None
    if not isinstance(facts, dict) or facts.get("status") != "ok":
        return "unknown"
    setups = facts.get("setups")
    handed = setups.get(source) if isinstance(setups, dict) else None
    handed = handed if isinstance(handed, dict) else {}
    if handed.get("stock_out_reason"):
        return "unknown"
    bbox, volume = vector_of(handed.get("stock_out_bbox_mm"), 6), handed.get("stock_out_volume_mm3")
    if bbox is None or not numeric(volume):
        return "unknown"
    spans = []
    for unit in axes:
        index = next((k for k in range(3) if abs(abs(unit[k]) - 1.0) <= PREPARED_SQUARE), None)
        if index is None:
            return "unknown"
        low, high = bbox[index], bbox[index + 3]
        spans.append([low, high] if unit[index] > 0 else [-high, -low])
    numbers["cut_box_mm"] = [[round(v, 6) for v in span] for span in spans]
    numbers["cut_volume_mm3"] = volume
    short = volume < math.prod(high - low for low, high in spans) * (1 - PREPARED_FULL)
    return "error" if short or blank_misfit(spans, declared, allowed) else "pass"


def written_procedure(method) -> bool:
    """A written method: a non-empty string other than ``unknown``, or a list of them."""
    steps = method if isinstance(method, list) else [method]
    return bool(steps) and all(
        isinstance(step, str) and bool(step.strip()) and step.strip() != "unknown" for step in steps
    )


def gauge_resolution(gauge: dict):
    """The gauge's resolution when its own fact trusts it, else unknown."""
    fact = length_fact(gauge, "resolution", require_measured=False)
    return fact["value"] if fact["verified"] else "unknown"


def blank_size_check(gauge, band: list, features: dict, row: dict) -> str:
    """A size check: a sizing gauge whose range spans ``band`` (size ± tolerance) at a
    resolution within it, on a millimetre manifest. A gauge that cannot size is an error,
    so is one too short or too coarse; an unread kind, range, resolution or unit stays
    unknown, and an unverified gauge establishes nothing either way unless it cannot size
    at all."""
    if not gauge:
        return "unknown"
    kind = gauge.get("kind", "unknown")
    span = gauge.get("range_mm")
    if not isinstance(span, list):
        maximum = nominal_length_mm(gauge, "range")
        span = [0, maximum] if numeric(maximum) else "unknown"
    resolution = gauge_resolution(gauge)
    row.update(gauge_kind=kind, range_mm=span, resolution_mm=resolution)
    capable = kind in PREPARED_SIZE_GAUGES
    if kind == "unknown" or (capable and features.get("units") != "mm"):
        status = "unknown"
    elif not capable:
        status = "error"
    elif isinstance(span, list) and all(map(numeric, span)) and numeric(resolution):
        row["band_mm"] = band[1] - band[0]
        spans = span[0] <= band[0] and band[1] <= span[1]
        status = "pass" if spans and resolution <= band[1] - band[0] else "error"
    else:
        status = "unknown"
    if record_uncertain(gauge) and (status != "error" or capable):
        status = "unknown"
    return status


def blank_form_check(gauge, method, limit, row: dict) -> str:
    """A flatness, squareness or parallelism check: a form gauge whose trusted resolution
    reads the declared ``form_mm`` limit, with a written method. A gauge that cannot read
    form or one too coarse is an error; an undeclared gauge, method or limit, an unread
    resolution or an unverified gauge stays unknown."""
    row["method"] = method if method is not None else "unknown"
    row["limit_mm"] = limit if numeric(limit) else "unknown"
    if gauge is None:
        return "unknown"
    if gauge.get("kind", "unknown") not in PREPARED_FORM_GAUGES:
        return "error"
    resolution = row["resolution_mm"] = gauge_resolution(gauge)
    if (
        not written_procedure(method)
        or not (numeric(limit) and limit > 0)
        or not numeric(resolution)
        or record_uncertain(gauge)
    ):
        return "unknown"
    return "error" if resolution > limit + 1e-9 else "pass"


def blank_gauge_checks(prepared: dict, bands: dict, features: dict, inventory: dict, numbers):
    """``(worst, missing)``: each declared blank check read through the inventory's gauges
    (the gauges table, then a machine's own accessories): a gauge the inventory lacks is an
    error and missing, else :func:`blank_size_check` or :func:`blank_form_check` decides
    the row. The rows go to ``numbers["checks"]``."""

    def plan_record(name):
        value = prepared.get(name)
        return value if isinstance(value, dict) else {}

    checks, methods, limits = plan_record("checks"), plan_record("methods"), plan_record("form_mm")
    rows, worst, missing = {}, "pass", []
    for key in (*PREPARED_SIZE_CHECKS, *PREPARED_FORM_CHECKS):
        ref = checks.get(key, "unknown")
        row = {"gauge": ref}
        gauge = resolve_item(inventory, "gauges", ref) if ref != "unknown" else None
        if ref != "unknown" and gauge is None:
            status = "error"
            missing.append(ref)
        elif key in bands:
            row["limits_mm"] = [round(v, 6) for v in bands[key]]
            status = blank_size_check(gauge, bands[key], features, row)
        else:
            status = blank_form_check(gauge, methods.get(key), limits.get(key), row)
        row["status"] = status
        rows[key] = row
        worst = max(worst, status, key=STATUS_RANK.get)
    numbers["checks"] = rows
    return worst, missing


def derive_prepared_blank(plan: dict, features: dict, inventory: dict, prepared: dict, kernel):
    """``(status, numbers, missing gauges)``: the ``prepared_blank`` finding a declared blank
    derives from the plan, the manifest's units, the inventory and the validator's own
    kernel run, never from a report. The root stock trimmed by the process end faces that
    earlier setups of the receiver's lineage make must be the declared box within its
    tolerances (``[section[0], section[1], length]``), with every made face square to the
    blank, else an error; then the kernel's handed-on stock (:func:`blank_cut`) and each
    gauge check (:func:`blank_gauge_checks`) are read and the worse verdict stands. Any
    unknown receiver, routing, size, placement, tolerance or unit stays unknown."""
    stock = plan["stock"]
    receiver = prepared.get("setup", "unknown")
    numbers = {
        "setup": receiver,
        **{key: prepared.get(key, "unknown") for key in PREPARED_DECLARED},
    }
    if receiver == "unknown":
        return "unknown", numbers, []
    lineage = stock_lineage(plan, receiver)
    definitions = operative_definitions(plan, features)
    made, later = [], []
    for setup in plan["setups"]:
        for op in setup["ops"]:
            name = op.get("feature")
            face = definitions.get(name) if isinstance(name, str) else None
            face = face.get("preparation") if isinstance(face, dict) else None
            if not isinstance(face, dict) or face.get("kind") != "end_face":
                continue
            if op.get("do") not in PROCESS_ACTIONS["end_face"]:
                continue
            earlier = setup["id"] in lineage and setup["id"] != receiver
            (made if earlier else later).append((name, f"{setup['id']} op {op['op']}"))
    numbers["made_by"] = [f"{PROCESS_PREFIX}{name} in {where}" for name, where in made]
    numbers["made_outside_lineage"] = [
        f"{PROCESS_PREFIX}{name} in {where}" for name, where in later
    ]
    axes = blank_axes(stock)
    raw_section, raw_length = vector_of(stock.get("section_mm"), 2), stock.get("length_mm")
    raw_origin = vector_of(stock.get("origin_mm"))
    if axes is None or raw_origin is None or raw_section is None or not numeric(raw_length):
        return "unknown", numbers, []
    if not all("stock_in" in s for s in plan["setups"] if s["id"] in lineage):
        return "unknown", numbers, []
    section, length = vector_of(prepared.get("section_mm"), 2), prepared.get("length_mm")
    origin, tolerance = (
        vector_of(prepared.get("origin_mm")),
        vector_of(prepared.get("tolerance_mm")),
    )
    if section is None or not numeric(length) or origin is None:
        return "unknown", numbers, []
    if tolerance is None or any(t < 0 for t in tolerance):
        return "unknown", numbers, []
    box = blank_box(raw_origin, [float(raw_length), *raw_section], axes)
    scale = UNIT_MM.get(features.get("units"))
    tilted = False
    for name, _ in made:
        face = plan["process_features"][name]
        at, normal = vector_of(face.get("at")), vector_of(face.get("axis"))
        if at is None or normal is None or scale is None:
            return "unknown", numbers, []
        at = [v * scale for v in at]
        size = dot(normal, normal) ** 0.5
        if size == 0:
            return "unknown", numbers, []
        normal = [v / size for v in normal]
        square = [
            i for i, u in enumerate(axes) if abs(abs(dot(normal, u)) - 1.0) <= PREPARED_SQUARE
        ]
        if not square:
            tilted = True
            continue
        i = square[0]
        plane = dot(at, axes[i])
        if dot(normal, axes[i]) > 0:  # kept material lies on +axis: the face trims the low end
            box[i][0] = max(box[i][0], plane)
        else:
            box[i][1] = min(box[i][1], plane)
    declared = blank_box(origin, [length, *section], axes)
    numbers["received_box_mm"] = [[round(v, 6) for v in span] for span in box]
    numbers["declared_box_mm"] = [[round(v, 6) for v in span] for span in declared]
    numbers["received_size_mm"] = [round(high - low, 6) for low, high in box]
    allowed = [tolerance[2], tolerance[0], tolerance[1]]
    if tilted or blank_misfit(box, declared, allowed):
        return "error", numbers, []
    bands = {
        key: [size - tol, size + tol]
        for key, size, tol in zip(PREPARED_SIZE_CHECKS, [length, *section], allowed, strict=True)
    }
    cut = blank_cut(plan, kernel, receiver, axes, declared, allowed, numbers)
    checked, missing = blank_gauge_checks(prepared, bands, features, inventory, numbers)
    return max(cut, checked, key=STATUS_RANK.get), numbers, missing


def same_evidence(reported, derived) -> bool:
    """Whether ``reported`` is the ``derived`` evidence: the same keys, items and strings,
    and numbers equal to float round-off."""
    if numeric(derived):
        return numeric(reported) and math.isclose(reported, derived, rel_tol=1e-9, abs_tol=1e-9)
    if isinstance(derived, dict):
        return (
            isinstance(reported, dict)
            and set(reported) == set(derived)
            and all(same_evidence(reported[key], value) for key, value in derived.items())
        )
    if isinstance(derived, list):
        return (
            isinstance(reported, list)
            and len(reported) == len(derived)
            and all(map(same_evidence, reported, derived))
        )
    return type(reported) is type(derived) and reported == derived


def check_prepared_blank(
    plan: dict, features: dict, inventory: dict, findings: dict, kernel
) -> list:
    """The one ``prepared_blank`` finding (never ``tool_resolves``: no setup names the
    blank's gauges) carries the verdict and evidence the validator derives for itself
    (:func:`derive_prepared_blank`) from the plan, the inventory and its own kernel run
    (``kernel``, :func:`independent_kernel`); no reported status, row or field selects
    them. A plan with no blank has nothing to approve; a blank declared unknown stays
    unknown. Returns the missing gauges the blank's checks name."""
    stock = plan.get("stock")
    declared = "prepared" in stock if isinstance(stock, dict) else False
    finding = findings.get(("prepared_blank", "stock.prepared"))
    if not declared:
        require(
            finding is None or finding["status"] == "not_applicable",
            "stock.prepared: a plan with no prepared blank has nothing to approve",
        )
        return []
    require(finding is not None, "missing finding prepared_blank:stock.prepared")
    prepared = stock["prepared"]
    if not isinstance(prepared, dict):
        require(
            finding["status"] == "unknown" and finding["numbers"] == {"prepared": prepared},
            "stock.prepared: an unknown blank stays unknown",
        )
        return []
    status, numbers, missing = derive_prepared_blank(plan, features, inventory, prepared, kernel)
    require(
        finding["status"] == status,
        f"stock.prepared: verdict {finding['status']} is not the {status} the plan, inventory "
        "and the validator's own kernel run decide",
    )
    reported = dict(finding["numbers"])
    if isinstance(reported.get("checks"), dict):
        # A row's sentence is wording; its gauge, band, capability and verdict are evidence.
        reported["checks"] = {
            key: {k: v for k, v in row.items() if k != "message"} if isinstance(row, dict) else row
            for key, row in reported["checks"].items()
        }
    require(
        same_evidence(reported, numbers),
        "stock.prepared: evidence differs from the plan, inventory and the validator's own "
        "kernel run",
    )
    return sorted(set(missing))


def check_zero(setup: dict, finding: dict, entries: dict, dro: dict) -> None:
    numbers = finding["numbers"]
    mode = numbers.get("dro", numbers).get("radius_mode")
    require(mode == dro["radius_mode"], f"{setup['id']}: DRO radius/diameter mode mismatch")
    # The rows are the plan's: an axis row per authored recipe, a retouch row per listed
    # retouch in op order; a report cannot drop one to leave it unchecked.
    zero = setup["zero"]
    require(
        set(numbers.get("axes", {}))
        == {a for a in ("x", "y", "z") if isinstance(zero.get(a), dict)},
        f"{setup['id']}: zero rows are not the plan's axis recipes",
    )
    listed = zero["z"].get("retouch_after")
    require(
        [row.get("op") for row in numbers.get("retouch", [])]
        == [op["op"] for op in setup["ops"] if isinstance(listed, list) and op["op"] in listed],
        f"{setup['id']}: retouch rows are not the plan's listed retouches",
    )
    # Any reading the plan leaves unknown (or an unknown DRO mode or retouch list) is a
    # zero the checker cannot certify.
    unsettled = not isinstance(listed, list) or any(
        dro.get(key, "unknown") == "unknown" for key in ("controller", "mode", "radius_mode")
    )
    for axis, row in numbers.get("axes", {}).items():
        recipe = setup["zero"][axis]
        edge = recipe.get("edge_mm", "unknown")
        jog = recipe["check_jog_mm"]
        sign = row.get("sign", "unknown")
        require(sign in (-1, 1), f"{setup['id']}.{axis}: jog polarity must be ±1")
        scale = 2 if axis == "x" and setup["machine"] == "PM-1127VF-LB" and mode is False else 1
        if recipe.get("method") == "measure_then_set":
            # A measured edge is a bench reading M: with a ready gauge, a stated
            # measurement and numeric offset/paper/jog, Axis Set M + offset + paper.
            gauge, base = recipe.get("gauge", "unknown"), recipe.get("offset_mm", "unknown")
            paper = recipe.get("paper_mm", "unknown")
            ready = (
                axis == "z"
                and isinstance(gauge, str)
                and resolves(gauge, entries)
                and not uncertain(gauge, entries)
                and str(recipe.get("measure", "")).strip() not in {"", "unknown"}
                and all(numeric(v) for v in (base, paper, jog))
            )
            unsettled |= not ready
            for field, step in (("axis_set", 0), ("check_reading", 1), ("mirrored_reading", -1)):
                text = "unknown"
                if ready:
                    value = round(base + paper + step * sign * jog, 6) + 0.0
                    text = "M " + f"{value:+.6f}".rstrip("0").rstrip(".")
                require(row.get(field) == text, f"{setup['id']}.{axis}: measured-edge {field}")
            continue
        if axis == "z":
            if recipe.get("face") == "top":
                edge = setup["stock_state"].get("top_z", "unknown")
            near(row.get("edge_mm", "unknown"), edge, f"{setup['id']}.{axis}: touched edge")
            paper = recipe.get("paper_mm", "unknown")
            expected = edge + paper if numeric(edge) and numeric(paper) else "unknown"
        elif recipe.get("method") == "trial_cut_measure":
            # The measured diameter is a bench reading: a ready gauge and jog complete it.
            gauge = recipe.get("gauge", "unknown")
            ready = (
                isinstance(gauge, str)
                and resolves(gauge, entries)
                and not uncertain(gauge, entries)
                and numeric(jog)
            )
            unsettled |= not ready
            display = "D" if scale == 2 else "D/2"
            step = sign * scale * jog if ready else 0
            for field, text in (
                ("axis_set", f"measured {display}"),
                ("check_reading", f"{display} {step:+g}"),
                ("mirrored_reading", f"{display} {-step:+g}"),
            ):
                require(
                    row.get(field) == (text if ready else "unknown"),
                    f"{setup['id']}.{axis}: trial-cut {field}",
                )
            continue
        elif recipe.get("from") == "indicated":
            near(row["radius_mm"], 0, "indicated axis has no finder correction")
            expected = edge
        else:
            tip = entries.get(recipe.get("tool", ""), {}).get("tip_in", "unknown")
            radius = tip * 25.4 / 2 if numeric(tip) else "unknown"
            near(row.get("radius_mm", "unknown"), radius, f"{setup['id']}.{axis}: finder radius")
            side = -1 if recipe.get("from") == f"-{axis}" else 1
            expected = edge + side * radius if numeric(edge) and numeric(radius) else "unknown"
        # The display shows scale × the physical contact (diameter mode doubles it).
        expected = expected * scale if numeric(expected) else "unknown"
        unsettled |= not (numeric(expected) and numeric(jog))
        near(row.get("axis_set", "unknown"), expected, f"{setup['id']}.{axis}: Axis Set")
        for field, factor in (("check_reading", 1), ("mirrored_reading", -1)):
            result = (
                expected + factor * sign * scale * jog
                if all(numeric(v) for v in (expected, jog))
                else "unknown"
            )
            near(row.get(field, "unknown"), result, f"{setup['id']}.{axis}: {field}")
    top = setup["stock_state"].get("top_z", "unknown")
    after = {}
    for op in setup["ops"]:
        top_feature = setup["stock_state"].get("top_feature")
        if (
            op["do"] in {"face", "finish_face", "rough_face"}
            and "to_z" in op
            and (top_feature is None or op["feature"] == top_feature)
        ):
            top = op["to_z"]
        after[op["op"]] = top
    for row in numbers.get("retouch", []):
        top = after[row["op"]]
        paper = setup["zero"]["z"].get("paper_mm", "unknown")
        near(row["top_z"], top, f"{setup['id']}: advanced top")
        expected = top + paper if numeric(top) and numeric(paper) else "unknown"
        near(row["axis_set"], expected, f"{setup['id']}: retouch Axis Set")
        unsettled |= not numeric(expected)
    # Only a saw or manual bench setup waives its zero (check_subjects): any other zero is
    # a verdict, and one its plan leaves unresolved is never approved.
    require(
        finding["status"] in ({"unknown", "error"} if unsettled else {"pass", "unknown", "error"}),
        f"{setup['id']}: a zero its plan leaves unresolved cannot pass or be waived",
    )


def check_centre_endpoint(
    plan: dict,
    features: dict,
    setup: dict,
    op: dict,
    row: dict,
    entries: dict,
    entry,
) -> tuple:
    """A quill-fed drilled centre: its depth past touching the end is the Table 6 drill
    length C (point included) plus the countersink to the mouth, read on the tailstock
    quill, and only for the centre the selected tool's own accepted facts cut, with its
    mouth on the touched entry surface ``entry`` (the plan's, :func:`entry_surface`)
    along the setup -Z feed (on a lathe, on the spindle axis). Returns ``(depth, verdict)``:
    the depth the plan derives, else unknown, and the row's verdict from the same inputs:
    a contradiction is an error, anything unresolved unknown (the row stating why)."""
    where = f"{setup['id']}:{op['op']}: centre"
    declared = plan["process_features"][op["feature"]]
    drill, length, mouth, angle = (
        declared.get(key, "unknown")
        for key in ("drill_dia_mm", "drill_length_mm", "mouth_dia_mm", "countersink_angle_deg")
    )
    sized = all(numeric(value) for value in (drill, length, mouth, angle))
    countersink = (mouth - drill) / 2 / math.tan(math.radians(angle / 2)) if sized else "unknown"
    near(row.get("countersink_depth_mm", "unknown"), countersink, f"{where} countersink depth")
    near(
        row.get("drill_length_mm", "unknown"),
        length if numeric(length) else "unknown",
        f"{where} Table 6 drill length",
    )
    require(row.get("depth_scale") == "quill", f"{where} depth is read on the tailstock quill")
    require(row.get("exit_face") == "not_applicable", f"{where} has no exit face")
    require(not {"point_mm", "lead_mm"} & row.keys(), f"{where}: Table 6 C already holds the point")
    reference = op.get("tool", "unknown")
    tool = centre_tool_facts(reference, entries)
    reported = row.get("tool_centre")
    require(isinstance(reported, dict) and reported.keys() == tool.keys(), f"{where} tool facts")
    for key, value in tool.items():
        near(reported[key], value, f"{where} tool {key}")
    errors, unresolved = [], []
    if not resolves(reference, entries) or uncertain(reference, entries):
        unresolved.append("tool record")
    unresolved += [key for key, value in tool.items() if not numeric(value)]
    for key, size in (("drill_dia_mm", drill), ("drill_length_mm", length)):
        if not numeric(size):
            unresolved.append(f"declared {key}")
        elif numeric(tool[key]) and abs(size - tool[key]) > LENGTH_TOLERANCE_MM:
            errors.append(key)
    if not numeric(angle):
        unresolved.append("declared countersink_angle_deg")
    elif numeric(tool["countersink_angle_deg"]):
        if abs(angle - tool["countersink_angle_deg"]) > ANGLE_TOLERANCE_DEG:
            errors.append("countersink_angle_deg")
    body = tool["body_dia_mm"]
    if not numeric(mouth):
        unresolved.append("declared mouth_dia_mm")
    elif numeric(body) and mouth > body + LENGTH_TOLERANCE_MM:
        errors.append("mouth wider than body")
    point, pilot, dia = (tool[k] for k in ("point_angle_deg", "drill_length_mm", "drill_dia_mm"))
    if numeric(point) and not 0 < point < 180:
        errors.append("point angle")
    elif all(numeric(value) for value in (point, pilot, dia)):
        if pilot - dia / 2 / math.tan(math.radians(point / 2)) <= LENGTH_TOLERANCE_MM:
            errors.append("point no shorter than pilot")
    # The mouth in the setup frame: on the plan's touched entry surface, fed along -Z.
    frame = setup_frame(setup, plan, features)
    scale = {"mm": 1.0, "in": 25.4}.get(features.get("units"))
    at, axis = declared.get("at"), declared.get("axis")
    mouth_z = "unknown"
    if scale and all(
        isinstance(v, list) and len(v) == 3 and all(map(numeric, v)) for v in (at, axis)
    ):
        seat = frame_point(at, frame)
        ahead = frame_point([a + d for a, d in zip(at, axis, strict=True)], frame)
        if all(map(numeric, seat + ahead)):
            mouth_z = seat[2]
            feed = [b - a for a, b in zip(seat, ahead, strict=True)]
            norm = math.sqrt(sum(v * v for v in feed))
            if norm == 0 or feed[2] / norm > -1 + UNIT_TOLERANCE:
                errors.append("axis is not the setup -Z feed")
            if math.hypot(seat[0], seat[1]) * scale > LENGTH_TOLERANCE_MM:
                kind = entries.get(setup.get("machine", "unknown"), {}).get("kind", "unknown")
                if kind == "lathe":
                    errors.append("mouth off the spindle axis")
                elif not isinstance(kind, str) or kind == "unknown":
                    unresolved.append("machine kind")
            if not numeric(entry):
                unresolved.append("entry surface")
            elif abs(seat[2] - entry) * scale > LENGTH_TOLERANCE_MM:
                errors.append("mouth off the touched entry surface")
    if mouth_z == "unknown":
        unresolved.append("mouth position")
    near(row.get("mouth_z", "unknown"), mouth_z, f"{where} mouth Z")
    depth = countersink + length if sized else "unknown"
    prepared = not errors and not unresolved and numeric(depth)
    expected = depth if prepared else "unknown"
    near(row.get("depth_mm", "unknown"), expected, f"{where} quill depth")
    tip = entry - expected if numeric(entry) and numeric(expected) else "unknown"
    near(row.get("tip_z", "unknown"), tip, f"{where} tip endpoint")
    if errors:
        return expected, "error"
    if not prepared:
        require(bool(row.get("unknown")), f"{where}: unresolved ({unresolved}) yet not unknown")
        return expected, "unknown"
    require("unknown" not in row, f"{where}: a prepared centre has no unresolved reason")
    return expected, "pass"


def entry_surface(stock: SimpleNamespace, setup: dict, op: dict) -> tuple:
    """``(Z, source, face)`` of the surface ``op``'s feature is entered from, advanced from
    the setup's authored ``stock_state`` through its preceding ops by the plan alone: the
    plan-only stock advance (``stock_states``) the engine shares, as it shares
    ``operative_definitions``; ``face`` is the feature when it has its own ``entry_z``
    surface, else ``"top"``. ``stock`` carries the authored plan, manifest and operative
    definitions only; no report value enters it."""
    name = op["feature"]
    before = next(state for current, state, _ in stock_states(stock, setup) if current is op)
    face = name if name in before["entry_z"] else "top"
    entry = before["entry_z"].get(name, before["top_z"])
    return entry, before["entry_from"].get(name, before["top_from"]), face


def feature_depth_mm(feature: dict, field: str, units, end: int = 1):
    """A feature-depth band end (upper by default) in mm: a bare number is an upper limit
    only; any other shape, or units other than mm/in, is unknown."""
    value = feature.get(field, "unknown")
    if isinstance(value, list):
        value = value[end] if len(value) == 2 else "unknown"
    elif end == 0:
        value = "unknown"
    scale = UNIT_MM.get(units)
    return value * scale if numeric(value) and scale is not None else "unknown"


def planned_depth_mm(op: dict, feature: dict, units):
    """An op's cutting depth in mm from the plan: its own ``depth_mm``; a tap's, without
    one, its feature's upper thread (else hole) depth."""
    if "depth_mm" in op:
        return op["depth_mm"] if numeric(op["depth_mm"]) else "unknown"
    if op.get("do") == "tap":
        field = "thread_depth" if "thread_depth" in feature else "depth"
        return feature_depth_mm(feature, field, units)
    return "unknown"


def positive(value) -> bool:
    return numeric(value) and math.isfinite(value) and value > 0


def dro_up(value, grid: tuple):
    """A tip or face Z as the DRO shows it on ``grid``: rounded up, so never deeper than
    worked; an unknown stays unknown."""
    step, decimals = grid
    if not numeric(value):
        return "unknown"
    return round(math.ceil(value / step - 1e-6) * step, decimals) + 0.0


def difference(*values):
    """The first value less the rest; unknown unless every value is a number."""
    return values[0] - sum(values[1:]) if all(map(numeric, values)) else "unknown"


def machine_kind(setup: dict, entries: dict):
    machine = setup.get("machine")
    return entries.get(machine, {}).get("kind") if isinstance(machine, str) else None


def leaves_face(setup: dict, op: dict, entries: dict):
    """Whether ``op``, cut on ``setup``, leaves its own feature's face at its ``to_z``,
    from the plan and the inventory alone: True for a facing or pocketing op with a
    ``to_z`` (unknown without one); False for a manual, saw or transfer step and for an
    axial or dividing-head cut (a mill cut, a lathe's spindle-axis tool), which leaves no
    face across its feature; unknown for an unknown action or a turning action off a
    lathe. A lathe turning cut leaves a face only where kernel facts pose one: no
    plan-only derivation, rejected."""
    action = op.get("do")
    if action in MANUAL | SAW_OPS | {"transfer"}:
        return False
    if not isinstance(action, str) or action == "unknown":
        return "unknown"
    if action in FACING | POCKETING:
        return True if "to_z" in op else "unknown"
    kind = machine_kind(setup, entries)
    if kind == "lathe":
        require(
            action in AXIAL_LATHE_ACTIONS,
            f"{setup['id']}:{op.get('op')}: a turned face stands where kernel facts pose it; "
            "no plan-only entry surface",
        )
        return False
    if op.get("approach") == "rotary" and action not in TURNING_ACTIONS:
        return False
    turning = action in TURNING_ACTIONS or (kind != "mill" and action in PROFILE_OPS)
    return "unknown" if turning else False


def entry_producer(stock: SimpleNamespace, setup: dict, entry, face: str, source, entries: dict):
    """The plan op whose cut left the surface a hole op of ``setup`` enters at nominal
    ``entry`` (:func:`entry_surface`), as ``(setup, op)``; None when no op cut it, so the
    authored surface stands; unknown when one may have cut it to an unknown Z or over an
    unknown part of it. From the plan alone: the op of ``setup`` that ``source`` names;
    else the last op, in the setups ``setup`` receives stock from (``lineage``) and shares
    a known frame with, that cut the whole surface (``cut_coverage``): for ``"top"`` a
    facing op on the setup's ``top_feature`` (any, when it names none), for a feature one
    that leaves its face (:func:`leaves_face`) or a facing or pocketing op whose
    footprint covers it. One that left the surface at another Z did not produce it."""
    if source == "unknown":
        return "unknown"
    made = re.fullmatch(r"(\S+) op (\S+) to_z", source) if isinstance(source, str) else None
    if made and made[1] == setup["id"]:
        return next(((setup, op) for op in setup["ops"] if str(op.get("op")) == made[2]), None)
    frame = setup.get("frame")
    definitions = stock.feature_definitions
    top = setup.get("stock_state", {}).get("top_feature")
    cuts = [
        (earlier, op)
        for earlier in lineage(stock, setup)
        if frame not in (None, "unknown") and earlier.get("frame") == frame
        for op in earlier.get("ops", [])
    ]
    for earlier, op in reversed(cuts):
        name, action = op.get("feature"), op.get("do")
        if face == "top":
            forms = action in FACING and "to_z" in op and top in (None, name)
        elif name == face:
            forms = leaves_face(earlier, op, entries)
        else:
            cut, target = definitions.get(name), definitions.get(face)
            forms = (
                action in FACING | POCKETING
                and "to_z" in op
                and isinstance(cut, dict)
                and isinstance(target, dict)
                and covers_xy(cut, target)
            )
        if not forms:
            continue
        surface = definitions.get((top or name) if face == "top" else face)
        coverage = cut_coverage(stock, earlier, op, surface if isinstance(surface, dict) else {})
        if coverage == "unknown":
            return "unknown"
        if coverage != "whole":
            continue
        if forms is True and numeric(op.get("to_z")) and abs(op["to_z"] - entry) > SAME_Z:
            return None
        return (earlier, op) if forms is True else "unknown"
    return None


def printed_entry(stock: SimpleNamespace, setup: dict, entry, face: str, source, entries: dict):
    """The entry surface Z the traveler prints for a hole op of ``setup`` entering nominal
    ``entry``: the ``to_z`` its producer (:func:`entry_producer`) cut, where that op's DRO
    stopped (rounded up on its own setup's grid), then as this setup's DRO shows it
    (rounded up on this grid); with no producer, the nominal rounded up on this grid; with
    a producer that may have cut it anywhere, unknown. A lathe producer's face stands
    where a blade's corner reading leaves it unless its cutter is known to be no blade:
    that face has no plan-only derivation, rejected. Every setup's DRO zero is held to
    its recipe by :func:`check_zero`."""
    features = stock.features
    grid = dro_grid(setup, features, entries)
    if not numeric(entry):
        return "unknown"
    producer = entry_producer(stock, setup, entry, face, source, entries)
    if producer is None:
        return dro_up(entry, grid)
    if producer == "unknown":
        return "unknown"
    cut_setup, op = producer
    if machine_kind(cut_setup, entries) == "lathe":
        tool = op.get("tool")
        kind = tool_field(tool, "kind", entries) if isinstance(tool, str) else "unknown"
        require(
            isinstance(kind, str) and kind != "unknown" and kind not in TURNING_BLADE_KINDS,
            f"{cut_setup['id']}:{op.get('op')}: a lathe face cut by what may be a blade stands "
            "where its corner reading leaves it; no plan-only entry surface",
        )
    cut = dro_up(op.get("to_z", "unknown"), dro_grid(cut_setup, features, entries))
    return dro_up(cut, grid)


def check_printed_endpoint(row: dict, where: str, grid: tuple, planned: dict) -> None:
    """Hold the endpoint the traveler prints (``dro_*``) to the plan-derived one on the
    setup's DRO grid: the entry surface as its producer cut it (``planned["surface"]``,
    :func:`printed_entry`); a through hole's exit face rounded up; the tip keeping its
    planned distance below the surface it is worked from (the exit face of a through hole,
    else that printed entry), then rounded up; and the depth or break-through that printed
    tip leaves. ``planned`` carries only plan-derived values."""
    entry, tip, exit_face = planned["entry"], planned["tip"], planned["exit_face"]
    surface = planned["surface"]
    same(row.get("dro_entry_z", "unknown"), surface, f"{where}: printed entry Z")
    through = exit_face != "not_applicable"
    if through:
        printed_exit = dro_up(exit_face, grid)
        same(row.get("dro_exit_face", "unknown"), printed_exit, f"{where}: printed exit face")
        shift = difference(printed_exit, exit_face)
    else:
        require("dro_exit_face" not in row, f"{where}: a blind endpoint prints no exit face")
        shift = difference(surface, entry)
    worked = tip + shift if numeric(tip) and numeric(shift) else "unknown"
    printed_tip = dro_up(worked, grid)
    same(row.get("dro_tip_z", "unknown"), printed_tip, f"{where}: printed tip Z")
    if through:
        left = difference(exit_face, planned["lead"], printed_tip)
        same(row.get("dro_exit_mm", "unknown"), left, f"{where}: printed break-through")
        require("dro_depth_mm" not in row, f"{where}: a through endpoint prints no depth")
        return
    require("dro_exit_mm" not in row, f"{where}: a blind endpoint has no break-through")
    depth = difference(planned["depth"], difference(printed_tip, worked))
    same(row.get("dro_depth_mm", "unknown"), depth, f"{where}: printed depth")
    floor = planned.get("floor", "unknown")
    same(row.get("depth_floor_mm", "unknown"), floor, f"{where}: depth band floor")


def check_endpoints(plan: dict, features: dict, findings: dict, entries: dict) -> dict:
    """Hold every ``blind_depth`` endpoint row to the plan, from its entry surface on,
    and the endpoint it prints to the setup's DRO grid (:func:`check_printed_endpoint`).
    The rows are exactly the plan's hole ops on the feature (a centre's, its
    center_drill ops) and the finding's verdict is the one those ops, their tools and
    the feature's depth guard decide: a contradiction (a tip past the depth guard, a tap
    flute shorter than its depth, a negative through allowance, a centre its tool does
    not cut) is an error, anything unresolved (no op, an unknown tip or guard, a missing
    or unverified tool) unknown, else pass; a non-hole feature's is not applicable.
    Returns the material depth each hole op's full diameter cuts, keyed ``(setup, op)``,
    as the plan derives it (a through hole's local thickness, a blind or tapped hole's
    planned depth, a drilled centre's prepared depth), never the point or exit lead and
    never the report's own depth."""
    setups = {setup["id"]: setup for setup in plan["setups"]}
    definitions = operative_definitions(plan, features)
    stock = SimpleNamespace(plan=plan, features=features, feature_definitions=definitions)
    units = features.get("units")
    depths = {}
    for (rule, name), finding in findings.items():
        if rule != "blind_depth":
            continue
        rows = finding["numbers"].get("endpoints", [])
        kind = definitions.get(name, {}).get("kind")
        centre = kind == "centre_hole"
        if not centre and kind not in ENDPOINT_KINDS:
            require(
                finding["status"] == "not_applicable" and not rows,
                f"{name}: a feature that is not a hole has no tip endpoint",
            )
            continue
        placed = [
            (setup["id"], op["op"])
            for setup in plan["setups"]
            for op in setup["ops"]
            if op.get("feature") == name
            and (op.get("do") == "center_drill" if centre else op.get("do") in ENDPOINT_OPS)
        ]
        require(
            [(row.get("setup"), row.get("op")) for row in rows] == placed,
            f"{name}: endpoint rows are not the plan's hole ops on it",
        )
        verdicts = []
        for row in rows:
            setup = setups[row["setup"]]
            op = next(op for op in setup["ops"] if op["op"] == row["op"])
            require(op["feature"] == row["feature"], "endpoint mismatched feature")
            where = f"{row['setup']}:{row['op']}"
            feature = definitions[op["feature"]]
            action = op["do"]
            entry, source, face = entry_surface(stock, setup, op)
            near(row.get("entry_z", "unknown"), entry, f"{where}: touched entry surface")
            require(row.get("entry_from") == source, f"{where}: entry surface source")
            surface = printed_entry(stock, setup, entry, face, source, entries)
            planned = {"entry": entry, "surface": surface, "exit_face": "not_applicable"}
            tool = op.get("tool", "unknown")
            # A missing tool resolves nothing; an unverified one proves no contradiction.
            missing = not (isinstance(tool, str) and resolves(tool, entries))
            unverified = tool_unverified(tool, entries)
            verdict = "pass"
            if action == "center_drill":
                require(
                    feature.get("kind") == "centre_hole",
                    f"{where}: only a plan centre hole has a centre endpoint",
                )
                cut, verdict = check_centre_endpoint(plan, features, setup, op, row, entries, entry)
                verdicts.append(verdict)
                depths[row["setup"], row["op"]] = cut if positive(cut) else "unknown"
                planned.update(depth=cut, tip=difference(entry, cut))
                check_printed_endpoint(row, where, dro_grid(setup, features, entries), planned)
                continue
            elif action in {"spot", "tap"}:
                depth = planned_depth_mm(op, feature, units)
                depths[row["setup"], row["op"]] = depth if positive(depth) else "unknown"
                near(row.get("depth_mm", "unknown"), depth, f"{action} cutting depth")
                require(row["exit_face"] == "not_applicable", f"{action} has no exit face")
                tip = difference(entry, depth)
                near(row["tip_z"], tip, f"{action} endpoint")
                planned.update(depth=depth, tip=tip)
                if action == "tap":
                    flute = tool_length_mm(tool, "flute_len", entries)
                    near(row.get("flute_len_mm", "unknown"), flute, "tap flute length")
                    band = "thread_depth" if "thread_depth" in feature else "depth"
                    planned["floor"] = feature_depth_mm(feature, band, units, 0)
                    if not (numeric(flute) and numeric(depth)):
                        verdict = "unknown"
                    elif flute < depth and not unverified:
                        verdict = "error"
            else:
                if action == "ream":
                    lead = tool_length_mm(tool, "lead", entries)
                    lead_field = "lead_mm"
                elif action == "drill":
                    diameter = tool_length_mm(tool, "dia", entries)
                    if not numeric(diameter):
                        diameter = tool_diameter(tool, entries)
                    angle = tool_field(tool, "point_angle", entries)
                    lead = (
                        diameter / (2 * math.tan(math.radians(angle / 2)))
                        if numeric(diameter) and diameter > 0 and numeric(angle) and 0 < angle < 180
                        else "unknown"
                    )
                    lead_field = "point_mm"
                else:
                    # Boring/counterboring has no twist-drill cone, even when the
                    # selected cutter identity and measured dimensions are unknown.
                    lead = 0.0
                    lead_field = "point_mm"
                near(row.get(lead_field, "unknown"), lead, f"{action} endpoint lead")
                if feature.get("thru") is True:
                    allowance = op.get("exit_mm", "unknown")
                    near(row.get("exit_mm", "unknown"), allowance, "endpoint exit allowance")
                    thickness = (
                        setup["stock_state"]
                        .get("local_thickness", {})
                        .get(op["feature"], "unknown")
                    )
                    near(
                        row.get("local_thickness", "unknown"), thickness, "endpoint local thickness"
                    )
                    depths[row["setup"], row["op"]] = (
                        thickness if positive(thickness) else "unknown"
                    )
                    exit_face = difference(entry, thickness)
                    near(row["exit_face"], exit_face, "local exit face")
                    tip = (
                        exit_face - lead - allowance
                        if all(numeric(v) for v in (exit_face, lead, allowance)) and allowance >= 0
                        else "unknown"
                    )
                    near(row["tip_z"], tip, "through tip endpoint")
                    planned.update(exit_face=exit_face, lead=lead, tip=tip)
                    if numeric(allowance) and allowance < 0:
                        verdict = "error"  # it stops short of breaking through
                else:
                    depth = planned_depth_mm(op, feature, units)
                    limit = feature_depth_mm(feature, "depth", units)
                    depths[row["setup"], row["op"]] = depth if positive(depth) else "unknown"
                    near(row.get("depth_mm", "unknown"), depth, "blind cutting depth")
                    near(row.get("depth_limit_mm", "unknown"), limit, "blind depth guard")
                    total = depth + lead if numeric(depth) and numeric(lead) else "unknown"
                    near(row.get("total_depth_mm", "unknown"), total, "blind total tip depth")
                    require(row["exit_face"] == "not_applicable", "blind hole has no exit face")
                    tip = difference(entry, total)
                    near(row["tip_z"], tip, "blind tip endpoint")
                    floor = feature_depth_mm(feature, "depth", units, 0)
                    planned.update(depth=depth, tip=tip, floor=floor)
                    if feature.get("thru") == "unknown" or not (numeric(total) and numeric(limit)):
                        verdict = "unknown"
                    elif total > limit and not unverified:
                        verdict = "error"
            if verdict != "error" and (not numeric(tip) or missing or unverified):
                verdict = "unknown"
            verdicts.append(verdict)
            check_printed_endpoint(row, where, dro_grid(setup, features, entries), planned)
        verdict = max(verdicts, key=STATUS_RANK.get, default="unknown")
        require(
            finding["status"] == verdict,
            f"{name}: endpoint verdict {finding['status']} is not the {verdict} its plan "
            "ops, tools and depth guard decide",
        )
    return depths


def cutting_material(plan: dict, features: dict, cutting: dict) -> tuple:
    """``(material, material class)``: the plan stock's material (else the manifest's
    spec) and the class the cutting data's aliases give it, else unknown."""
    stock = plan.get("stock") if isinstance(plan.get("stock"), dict) else {}
    manifest = features.get("material") if isinstance(features.get("material"), dict) else {}
    material = stock.get("material", manifest.get("spec", "unknown"))
    aliases = cutting.get("aliases") if isinstance(cutting.get("aliases"), dict) else {}
    found = aliases.get(material, "unknown") if isinstance(material, str) else "unknown"
    if isinstance(found, dict):
        found = found.get("material_class", "unknown")
    return material, found


def same(actual, expected, where: str) -> None:
    """``actual`` is ``expected``: numerically, else exactly (an unknown stays unknown)."""
    if numeric(expected):
        near(actual, expected, where)
    else:
        require(actual == expected, f"{where}: {actual!r} != {expected!r}")


def selected_tool(ref, entries: dict, key: str):
    """The selected tool's own authored ``key`` as the engine reads it (no fact record
    unwrapped); unknown for a reference that does not resolve to one tool."""
    if not isinstance(ref, str) or not resolves(ref, entries):
        return "unknown"
    return tool_record(ref, key, entries)


def tool_unverified(ref, entries: dict) -> bool:
    """Whether the selected tool carries verification debt (any fact marked for
    verification, unknown presence or verify coverage, through the references it names):
    its cutting data then proves nothing, so the row cannot pass."""
    return isinstance(ref, str) and resolves(ref, entries) and uncertain(ref, entries)


def check_saw_speed(
    plan: dict, setup: dict, op: dict, finding: dict, entries: dict, cutting: dict, material
) -> None:
    """A saw row is blade linear speed and descent feed from the one cited ``saw_cut`` row
    the plan's material class and the blade's material select; no spindle maths."""
    where = f"{setup['id']}:{op['op']}"
    row = finding["numbers"]
    machine = entries.get(setup.get("machine", "unknown"), {})
    tool_material = selected_tool(op.get("tool", "unknown"), entries, "material")
    identities = (*material, tool_material)
    require(row.get("tool_material") == tool_material, f"{where}: saw blade material")
    require((row.get("material"), row.get("material_class")) == material, f"{where}: saw material")
    known = all(isinstance(v, str) and v.strip() and v != "unknown" for v in identities)
    rows = [
        c
        for c in cutting.get("cut", [])
        if known
        and (c.get("material_class"), c.get("tool_material"), c.get("operation"))
        == (material[1], tool_material, "saw_cut")
    ]
    require(row.get("matching_rows") == len(rows), f"{where}: saw row count")
    texts = citations(rows[0].get("cite")) if len(rows) == 1 else []
    sfm = rows[0].get("sfm", "unknown") if texts else "unknown"
    descent = rows[0].get("feed_mm_min", "unknown") if texts else "unknown"
    source = "unknown"
    if texts:
        source = texts[0] if isinstance(rows[0]["cite"], str) else texts
    require(row.get("cutting_data_row", "unknown") == source, f"{where}: saw row source")
    same(row.get("sfm", "unknown"), sfm, f"{where}: saw row speed")
    band = machine.get("blade_speed_sfm", "unknown")
    bounded = isinstance(band, list) and len(band) == 2 and all(map(positive, band))
    low, high = band if bounded and band[0] <= band[1] else ("unknown", "unknown")
    near(row.get("blade_speed_min_sfm", "unknown"), low, "saw blade speed minimum")
    near(row.get("blade_speed_max_sfm", "unknown"), high, "saw blade speed maximum")
    speed = max(low, min(high, sfm)) if positive(sfm) and numeric(low) else "unknown"
    near(row.get("blade_speed_sfm", "unknown"), speed, f"{where}: blade speed")
    feed = descent if positive(descent) else "unknown"
    near(row.get("feed_mm_min", "unknown"), feed, f"{where}: descent feed")
    require("rpm" not in row, f"{where}: a saw blade has no spindle RPM")
    material_verify = plan.get("stock", {}).get("material_verify", False)
    require(row.get("material_verify") == material_verify, f"{where}: material verification")
    range_verify = record_uncertain(machine)
    require(row.get("blade_speed_range_verify") == range_verify, f"{where}: blade range check")
    unsettled = (
        not numeric(speed)
        or not numeric(feed)
        or not texts
        or record_uncertain(rows[0])
        or range_verify
        or material_verify
        or tool_unverified(op.get("tool", "unknown"), entries)
    )
    # The checker certifies a sourced blade speed and feed, else leaves it unknown.
    require(
        finding["status"] == ("unknown" if unsettled else "pass"),
        f"{where}: the blade speed and feed verdict is not the one its inputs settle",
    )


def citations(value) -> list:
    """The usable cited strings of ``value`` (a string, list or citation map), in order."""
    if isinstance(value, dict):
        return [text for key in sorted(value) for text in citations(value[key])]
    if isinstance(value, list):
        return [text for item in value for text in citations(item)]
    return [value] if isinstance(value, str) and value.strip() not in {"", "unknown"} else []


def cited(value) -> bool:
    if isinstance(value, list):
        return bool(value) and all(map(cited, value))
    return isinstance(value, str) and value not in {"", "unknown"}


def deep_hole_derate(cutting: dict, operation: str, depth, diameter) -> tuple:
    """``(sfm factor, report fields, unresolved)`` of the cutting data's cited
    ``[[deep_hole]]`` row governing a hole ``depth`` deep at ``diameter`` (both mm): the
    deepest ``depth_over_dia`` its depth/diameter exceeds. An operation no row names keeps
    its sfm and reports nothing; an unknown ratio or a malformed, uncited or tied row leaves
    the factor unknown, and they or an unconfirmed governing row leave it ``unresolved``."""
    rows = [row for row in cutting.get("deep_hole", []) if row.get("operation") == operation]
    if not rows:
        return 1.0, {}, False
    known = numeric(depth) and numeric(diameter) and diameter > 0
    ratio = depth / diameter if known else "unknown"
    fields = {
        "depth_over_dia": ratio,
        "deep_hole_row": "unknown",
        "deep_hole_sfm_factor": "unknown",
    }
    valid = all(
        positive(row.get("depth_over_dia"))
        and positive(row.get("sfm_factor"))
        and row["sfm_factor"] <= 1
        and cited(row.get("cite"))
        for row in rows
    )
    if not valid or not numeric(ratio):
        return "unknown", fields, True
    deeper = [row for row in rows if ratio > row["depth_over_dia"]]
    if not deeper:
        fields.update(deep_hole_row="not_applicable", deep_hole_sfm_factor=1.0)
        return 1.0, fields, False
    limit = max(row["depth_over_dia"] for row in deeper)
    governing = [row for row in deeper if row["depth_over_dia"] == limit]
    if len(governing) != 1:
        return "unknown", fields, True
    (row,) = governing
    fields.update(deep_hole_row=row["cite"], deep_hole_sfm_factor=row["sfm_factor"])
    # A governing row marked for verification derates, but cannot establish a pass.
    return row["sfm_factor"], fields, record_uncertain(row)


def spindle_range(machine: dict) -> tuple:
    """The machine's ``(rpm_min, rpm_max)``: its spindle's own limits, else the ends of its
    declared speed ranges; unknown otherwise."""
    spindle = machine.get("spindle") if isinstance(machine.get("spindle"), dict) else {}
    low, high = spindle.get("rpm_min", "unknown"), spindle.get("rpm_max", "unknown")
    declared = spindle.get("ranges_rpm")
    ranges = [
        band
        for band in (declared if isinstance(declared, list) else [])
        if isinstance(band, list) and len(band) == 2 and all(map(numeric, band))
    ]
    if not numeric(low) and ranges:
        low = min(band[0] for band in ranges)
    if not numeric(high) and ranges:
        high = max(band[1] for band in ranges)
    return low, high


def nearest50(rpm, low, high):
    """Raw RPM rounded to the nearest 50 (ties to even), then clamped to the machine range."""
    finite = all(numeric(v) and math.isfinite(v) for v in (rpm, low, high))
    if not finite or low < 0 or high < low:
        return "unknown"
    return max(low, min(high, round(rpm / 50) * 50))


def dome_base_mm(definition: dict, scale):
    """A dome's widest (base) diameter in mm from its declared base radius, else its
    declared sphere radius and height; unknown when neither fixes it."""
    if scale is None:
        return "unknown"
    radius = definition.get("base_radius")
    if numeric(radius) and radius > 0:
        return 2 * radius * scale
    radius = definition.get("sphere_radius")
    height = next(
        (
            definition[key]
            for key in ("height_nominal", "nominal_height", "height")
            if key in definition
        ),
        "unknown",
    )
    if not (numeric(radius) and numeric(height) and 0 < height <= 2 * radius):
        return "unknown"
    cap = min(height, radius)
    return 2 * math.sqrt(cap * (2 * radius - cap)) * scale


def cutting_diameter_mm(setup: dict, op: dict, entries: dict, definitions: dict, units, lathe):
    """The diameter an op's speed is figured at, in mm, from the inventory and manifest: a
    rotating tool's own (any mill op, a lathe spindle-axis op); a turned feature's nominal,
    else twice its base radius (a dome's declared base), else for a facing cut the held
    stock O.D.; a rough turn adds its leave."""
    if not lathe or op.get("do") in AXIAL_LATHE_ACTIONS:
        # A member's own (measured) diameter outranks the size its name implies.
        tool = op.get("tool", "unknown")
        if not isinstance(tool, str) or not resolves(tool, entries):
            return "unknown"
        diameter = tool_length_mm(tool, "dia", entries)
        return diameter if numeric(diameter) else tool_diameter(tool, entries)
    feature = definitions.get(op.get("feature"), {})
    scale = UNIT_MM.get(units)
    nominal = feature.get("dia_nominal", "unknown")
    diameter = nominal * scale if numeric(nominal) and scale is not None else "unknown"
    if not numeric(diameter) and feature.get("kind") == "dome":
        # Declared only: a base the kernel alone measures is no input this oracle holds.
        diameter = dome_base_mm(feature, scale)
    elif not numeric(diameter):
        radius = feature.get("base_radius", "unknown")
        diameter = 2 * radius * scale if numeric(radius) and scale is not None else "unknown"
    if not numeric(diameter) and op.get("do") in AXIAL_FACING:
        diameter = setup.get("stock_state", {}).get("od_mm", "unknown")
    if op.get("do") == "rough_turn":
        leave = rough_leave(op)[0]
        diameter = diameter + leave if numeric(diameter) and numeric(leave) else "unknown"
    return diameter


def check_speeds(
    plan: dict,
    features: dict,
    setup: dict,
    op: dict,
    finding: dict,
    entries: dict,
    cutting: dict,
    definitions: dict,
    depths: dict,
) -> None:
    """Hold a speeds_feeds row to the RPM and feed the authored inputs give: the plan's
    material and the cutting data's alias, the selected tool's chart (else the one cited
    cut row its material, the op and its diameter select), the machine's spindle range,
    the plan-derived hole depth (:func:`check_endpoints`) and its deep-hole derate. No
    reported operand enters the arithmetic; each is compared with its source."""
    where = f"{setup['id']}:{op['op']}"
    row = finding["numbers"]
    if op["do"] in MANUAL:
        require(finding["status"] == "not_applicable", f"{where}: a manual op has no speed")
        return
    material = cutting_material(plan, features, cutting)
    if op["do"] in SAW_OPS:
        check_saw_speed(plan, setup, op, finding, entries, cutting, material)
        return
    machine = entries.get(setup.get("machine", "unknown"), {})
    lathe = machine.get("kind") == "lathe"
    tool = op.get("tool", "unknown")
    diameter = cutting_diameter_mm(setup, op, entries, definitions, features.get("units"), lathe)
    operation = CUT_OPERATIONS.get(op["do"], op["do"])
    tool_material = selected_tool(tool, entries, "material")
    require(row.get("operation") == operation, f"{where}: cutting-data operation")
    require((row.get("material"), row.get("material_class")) == material, f"{where}: material")
    require(row.get("tool_material") == tool_material, f"{where}: tool material")
    sfm = chip = per_rev = "unknown"
    source, range_unknown = "unknown", False
    if cited(selected_tool(tool, entries, "chart")):
        source = selected_tool(tool, entries, "chart")
        sfm = selected_tool(tool, entries, "sfm")
        chip = selected_tool(tool, entries, "chip_load_mm_per_tooth")
        per_rev = selected_tool(tool, entries, "feed_mm_rev")
    else:
        matching = []
        for candidate in cutting.get("cut", []):
            key = tuple(candidate.get(k) for k in ("material_class", "tool_material", "operation"))
            if key != (material[1], tool_material, operation):
                continue
            band = candidate.get("diameter_range", "unknown")
            if not (isinstance(band, list) and len(band) == 2 and all(map(numeric, band))):
                range_unknown = True
            elif numeric(diameter) and band[0] <= diameter <= band[1]:
                matching.append(candidate)
        if len(matching) == 1 and cited(matching[0].get("cite")):
            (selected,) = matching
            source = selected["cite"]
            sfm = selected.get("sfm", "unknown")
            chip = selected.get("chip_load_mm_per_tooth", "unknown")
            per_rev = selected.get("feed_mm_rev", "unknown")
            range_unknown |= record_uncertain(selected)
    if lathe and "feed_mm_rev" in op:
        per_rev = op["feed_mm_rev"]  # the op's planned feed overrides the row's
    diameter_in = diameter / 25.4 if numeric(diameter) and diameter > 0 else "unknown"
    low, high = spindle_range(machine)
    flutes = tool_field(tool, "flutes", entries) if resolves(tool, entries) else "unknown"
    for field, expected in (
        ("cutting_data_row", source),
        ("sfm", sfm),
        ("chip_load_mm_per_tooth", chip),
        ("diameter_in", diameter_in),
        ("flutes", flutes),
        ("rpm_min", low),
        ("rpm_max", high),
    ):
        same(row.get(field, "unknown"), expected, f"{where}: {field}")
    if lathe:
        same(row.get("feed_mm_rev", "unknown"), per_rev, f"{where}: feed per revolution")
    else:
        require("feed_mm_rev" not in row, f"{where}: a mill op feeds per tooth")
    depth = depths.get((setup["id"], op["op"]), "unknown")
    factor, derate, unresolved = deep_hole_derate(cutting, operation, depth, diameter)
    deep_fields = {"depth_over_dia", "deep_hole_row", "deep_hole_sfm_factor"}
    require(deep_fields & row.keys() == derate.keys(), f"{where}: deep-hole derate fields")
    for key, value in derate.items():
        same(row[key], value, f"{where}: deep-hole {key}")
    # The governing deep-hole row derates the sourced sfm before the RPM is derived.
    speed = sfm * factor if numeric(sfm) and numeric(factor) else "unknown"
    raw = (
        12 * speed / (math.pi * diameter_in)
        if numeric(speed) and speed > 0 and numeric(diameter_in)
        else "unknown"
    )
    rpm = nearest50(raw, low, high)
    near(row.get("rpm", "unknown"), rpm, f"{where}: RPM")
    operands = (rpm, per_rev) if lathe else (rpm, flutes, chip)
    feed = math.prod(operands) if all(map(positive, operands)) else "unknown"
    near(row.get("feed_mm_min", "unknown"), feed, f"{where}: feed")
    material_verify = plan.get("stock", {}).get("material_verify", False)
    require(row.get("material_verify") == material_verify, f"{where}: material verification")
    range_verify = record_uncertain(machine)
    require(row.get("rpm_range_verify") == range_verify, f"{where}: spindle range verification")
    unsettled = (
        not numeric(rpm)
        or not numeric(feed)
        or range_unknown
        or unresolved
        or material_verify
        or range_verify
        or tool_unverified(tool, entries)
    )
    # The checker certifies a sourced RPM and feed, else leaves it unknown.
    require(
        finding["status"] == ("unknown" if unsettled else "pass"),
        f"{where}: the RPM and feed verdict is not the one its inputs settle",
    )


def located_point(definitions: dict, frames: dict, name: str) -> tuple[str, list]:
    """``(locator, model point)``: the feature whose ``at`` places ``name`` (its own, even
    unknown; else its parent hole's) and that ``at`` in model coordinates."""
    feature = definitions.get(name, {})
    parent = feature.get("hole", feature.get("parent"))
    locator = name if "at" in feature or not isinstance(parent, str) else parent
    owner = definitions.get(locator, {})
    at, frame = owner.get("at"), frames.get(owner.get("frame", "model"), "unknown")
    if not (isinstance(at, list) and len(at) == 3 and isinstance(frame, dict)):
        return locator, ["unknown"] * 3
    return locator, model_point(at, frame)


def unit(vector) -> list | None:
    if not (isinstance(vector, list) and len(vector) == 3 and all(map(numeric, vector))):
        return None
    length = math.sqrt(sum(v * v for v in vector))
    return [v / length for v in vector] if length > 1e-6 else None


def dot(a: list, b: list) -> float:
    return sum(x * y for x, y in zip(a, b, strict=True))


def measuring_axis(definitions: dict, frames: dict, name: str, seen: tuple = ()):
    """``name``'s declared axis as a model unit vector, else the axis of the feature it
    stands on (``hole``, ``parent``, ``coaxial_to``); None when none is declared along that
    line, "unknown" when the axis, its frame or its owner is not resolved."""
    feature = definitions.get(name, {})
    if "axis" not in feature:
        owner = feature.get("hole", feature.get("parent", feature.get("coaxial_to")))
        if not isinstance(owner, str):
            return None
        if owner in (*seen, name) or owner not in definitions:
            return "unknown"
        return measuring_axis(definitions, frames, owner, (*seen, name))
    axis, frame = feature["axis"], frames.get(feature.get("frame", "model"))
    basis = [frame.get(key) for key in ("x", "y", "z")] if isinstance(frame, dict) else []
    if not (
        isinstance(axis, list)
        and len(axis) == 3
        and all(map(numeric, axis))
        and len(basis) == 3
        and all(unit(vector) for vector in basis)
    ):
        return "unknown"
    return unit([dot(axis, [basis[j][i] for j in range(3)]) for i in range(3)]) or "unknown"


def sheet_band(features: dict, feature: dict, requirement: str):
    """``requirement``'s band as the sheet prints it: each limit rounded inward at its
    drawing precision; "unknown" unless both limits are numbers."""
    band = feature.get(requirement)
    if not (isinstance(band, list) and len(band) == 2 and all(map(numeric, band))):
        return "unknown"
    precision = feature.get("precision", {})
    places = (
        precision.get(requirement, features.get("precision"))
        if isinstance(precision, dict)
        else precision
    )
    if not isinstance(places, int) or isinstance(places, bool):
        return list(band)
    scale = 10**places
    low = math.ceil(round(band[0] * scale, 6)) / scale
    high = math.floor(round(band[1] * scale, 6)) / scale
    return [low, high] if low <= high else list(band)


def dialled(context: SimpleNamespace, name: str) -> bool:
    """Whether a mill setup's hole or centre op cuts ``name`` at its DRO target."""
    for setup in context.plan["setups"]:
        kind = context.entries.get(setup.get("machine", "unknown"), {}).get("kind")
        if kind == "lathe" or manual_bench(context.inventory, setup) is not None:
            continue
        if any(op.get("do") in CENTRE_OPS and op.get("feature") == name for op in setup["ops"]):
            return True
    return False


def band_distance(context: SimpleNamespace, name: str, source: str, point: list, seen: tuple):
    """``(distance, unit direction)`` from ``name``'s ``height_from`` reference ``source`` to
    model ``point``: along a reference plane's normal; else from the reference's planned
    point along the common normal of both measuring axes, square to the one axis, or point
    to point with neither. None when it cannot be measured."""
    if not all(map(numeric, point)):
        return None
    reference = context.definitions.get(source, {})
    plane = reference.get("plane")
    if isinstance(plane, dict) and plane:
        frame = context.frames.get(plane.get("frame", "model"))
        axis = plane.get("axis")
        if axis not in ("x", "y", "z") or not isinstance(frame, dict):
            return None
        normal = unit(frame.get(axis))
        coordinates = [plane.get("value") if key == axis else 0.0 for key in ("x", "y", "z")]
        base = model_point(coordinates, frame)
        if normal is None or not all(map(numeric, base)):
            return None
    else:
        base = planned_model_point(context, source, (*seen, name))
        first = measuring_axis(context.definitions, context.frames, name)
        second = measuring_axis(context.definitions, context.frames, source)
        if base is None or "unknown" in (first, second):
            return None
        delta = [p - q for p, q in zip(point, base, strict=True)]
        normal = None
        if first and second:
            normal = unit(
                [
                    first[(i + 1) % 3] * second[(i + 2) % 3]
                    - first[(i + 2) % 3] * second[(i + 1) % 3]
                    for i in range(3)
                ]
            )
        shared = first or second
        if normal is None and shared:
            along = dot(delta, shared)
            normal = unit([d - along * s for d, s in zip(delta, shared, strict=True)])
        if normal is None and not shared:
            normal = unit(delta)
        if normal is None:
            return None
    signed = dot([p - q for p, q in zip(point, base, strict=True)], normal)
    return abs(signed), normal if signed >= 0 else [-v for v in normal]


# A requested value on a printed band limit is inside it (the engine's join tolerance).
BAND_TOLERANCE = 1e-6


def aim_outcome(context: SimpleNamespace, name: str, points: list, seen: tuple = ()):
    """How plan ``aims.<name>`` places ``name``'s model ``points``, recomputed from the plan
    and the drawing band: None without an aim; ``{"refused": True, "error": bool}`` when it
    cannot apply (``error``: the asked value lies outside the printed band); else the
    moved points with the nominal and asked distances."""
    aim = context.plan.get("aims", {}).get(name)
    if aim is None:
        return None
    refused = {"refused": True, "error": False}
    feature = context.definitions.get(name, {})
    scale = UNIT_MM.get(context.features.get("units"))
    band = sheet_band(context.features, feature, aim["requirement"])
    if name in seen:
        return refused
    if scale is not None and band != "unknown":
        asked = aim["value_mm"] / scale
        if not band[0] - BAND_TOLERANCE <= asked <= band[1] + BAND_TOLERANCE:
            return {"refused": True, "error": True}
    source = feature.get("height_from")
    requirement = next((key for key in HEIGHT_BANDS if key in feature), None)
    if (
        not dialled(context, name)
        or scale is None
        or not isinstance(source, str)
        or requirement != aim["requirement"]
        or band == "unknown"
    ):
        return refused
    measured = [band_distance(context, name, source, point, seen) for point in points]
    if not measured or None in measured:
        return refused
    nominal, direction = measured[0]
    if any(
        abs(value - nominal) > BAND_TOLERANCE or math.dist(other, direction) > 1e-9
        for value, other in measured[1:]
    ):
        return refused
    asked = aim["value_mm"] / scale
    shift = asked - nominal
    return {
        "moved": [
            [p + shift * d for p, d in zip(point, direction, strict=True)] for point in points
        ],
        "source": source,
        "printed_band": band,
        "value": asked,
        "nominal_mm": nominal * scale,
        "shift_mm": shift * scale,
    }


def planned_model_point(context: SimpleNamespace, name: str, seen: tuple = ()):
    """``name``'s planned model point: its locator's ``at`` moved by that locator's own
    plan aim; None when unknown, or when an aim bearing on it cannot be applied."""
    locator, point = located_point(context.definitions, context.frames, name)
    outcome = aim_outcome(context, locator, [point], seen)
    if outcome is not None:
        if "refused" in outcome:
            return None
        (point,) = outcome["moved"]
    if locator != name and name in context.plan.get("aims", {}):
        return None  # a child's own aim would take it off its parent's axis
    return point if all(map(numeric, point)) else None


def check_aims(context: SimpleNamespace, setup: dict, finding: dict, frame, places: dict) -> dict:
    """Hold every coordinate row to the plan ``aims`` bearing on it, recomputed from the
    plan, the drawing band and the frames: a mill row of an aimed feature (or of a child
    located on one) carries that aim, stands where the aim moves it with its unmoved
    target as ``nominal_setup``, or names why the aim moves nothing. ``places`` maps each
    row to its derived ``(model point, unmoved setup point)`` (:func:`coordinate_place`);
    no reported coordinate is moved. Returns ``{id(row): model point the row stands at}``
    for the rows an aim moves."""
    aims = context.plan.get("aims", {})
    lathe = context.entries.get(setup.get("machine", "unknown"), {}).get("kind") == "lathe"
    groups = {}
    for row in finding["numbers"].get("rows", []):
        known = all(map(numeric, places[id(row)][1]))
        if not lathe and ("point" in row or known):
            groups.setdefault(row["feature"], []).append(row)
        else:
            require(not {"aim", "refused_aim", "nominal_setup"} & row.keys(), "unplaced aim")
    standing, errors, unresolved = {}, False, False
    for name, rows in groups.items():
        locator, _ = located_point(context.definitions, context.frames, name)
        outcome = aim_outcome(context, locator, [places[id(row)][0] for row in rows])
        own = locator != name and name in aims
        expected = {"aim"} if outcome is not None else set()
        expected |= {"refused_aim"} if own else set()
        moved = outcome is not None and "moved" in outcome
        errors |= outcome is not None and outcome.get("error", False)
        unresolved |= own or (outcome is not None and "refused" in outcome)
        for index, row in enumerate(rows):
            require(
                {"aim", "refused_aim"} & row.keys() == expected,
                f"{setup['id']}: {name}: plan aims bearing on the row",
            )
            for key in expected:
                owner = locator if key == "aim" else name
                record, authored = row[key], aims[owner]
                require(
                    record.get("feature") == owner
                    and all(
                        record.get(k) == authored[k] for k in ("requirement", "value_mm", "reason")
                    )
                    and f"plan.aims.{owner}" in finding["cite"],
                    f"{setup['id']}: {name}: aim differs from plan.aims.{owner}",
                )
            if own:
                require("why" in row["refused_aim"], f"{name}: a child's own aim must be refused")
            if outcome is None:
                require("nominal_setup" not in row, f"{name}: unaimed row moved")
                continue
            record = row["aim"]
            if not moved:
                require(
                    "why" in record
                    and ("error" in record) is outcome["error"]
                    and "nominal_setup" not in row,
                    f"{setup['id']}: {name}: aims.{locator} cannot move it",
                )
                continue
            require(
                not {"why", "error"} & record.keys() and record.get("source") == outcome["source"],
                f"{setup['id']}: {name}: aims.{locator} applies",
            )
            for actual, expected_limit in zip(
                record["printed_band"], outcome["printed_band"], strict=True
            ):
                near(actual, expected_limit, f"{name}: aimed printed band")
            near(record.get("value"), outcome["value"], f"{name}: aimed value")
            for key in ("nominal_mm", "shift_mm"):
                require(
                    numeric(record.get(key))
                    and math.isclose(record[key], outcome[key], abs_tol=BAND_TOLERANCE),
                    f"{name}: aim {key}",
                )
            for actual, expected_value in zip(
                row["nominal_setup"], places[id(row)][1], strict=True
            ):
                near(actual, expected_value, f"{name}: unaimed setup coordinate")
            standing[id(row)] = outcome["moved"][index]
    if errors:
        require(finding["status"] == "error", f"{setup['id']}: an out-of-band aim must error")
    elif unresolved:
        require(finding["status"] != "pass", f"{setup['id']}: an unapplied aim cannot pass")
    return standing


def dro_grid(setup: dict, features: dict, entries: dict) -> tuple:
    """``(step, decimals)``: the setup machine's DRO grid in manifest units, from the
    inventory alone: its one authored positive ``resolution`` length, else
    ``DRO_DEFAULT_STEP`` (so too for units other than mm or in); the decimals print one
    step exactly."""
    scale = UNIT_MM.get(features.get("units"))
    machine = setup.get("machine", "unknown")
    record = entries.get(machine, {}) if isinstance(machine, str) else {}
    authored = [key for key in ("resolution_mm", "resolution_in") if key in record]
    authored += ["resolution"] if "resolution" in record and "units" in record else []
    resolution = "unknown"
    if scale is not None and len(authored) == 1:
        resolution = tool_length_mm(machine, "resolution", entries)
    step = resolution / scale if positive(resolution) else DRO_DEFAULT_STEP
    decimals = next((d for d in range(9) if abs(round(step, d) - step) <= 1e-12), 9)
    return step, decimals


def dro_target(value, grid: tuple):
    """A position as the DRO dials it on ``grid``: the nearest grid point (a located axis
    has no safe side); an unknown stays unknown."""
    step, decimals = grid
    return round(round(value / step) * step, decimals) + 0.0 if numeric(value) else "unknown"


def coordinate_place(context: SimpleNamespace, setup: dict, frame, row: dict, located) -> tuple:
    """``(model point, setup point)`` a coordinate ``row`` of ``setup`` stands for before
    any aim moves it, from the plan and the manifest: a located row its locator's ``at``; a
    lathe ``drawing station`` its feature's ``z_mm`` station and an ``op`` row that op's
    authored Z, on the turned axis (in an unbound frame, the authored Z itself as
    ``local_from``); a ``kernel span`` row a point on setup Z through X0 Y0, legitimate only
    in a bound frame, for a located feature no known ``at`` places (on a mill, one with no
    ``at`` or parent at all) and whose kernel faces of revolution the finding cites: its Z
    the low (start) or high (end) end of those faces as the validator's own kernel run
    measures them (``context.kernel``, :func:`independent_kernel`), never the row's; no
    such measurement, no span. A lathe station also carries its feature's nominal
    diameter as the X target."""
    name, label = row["feature"], row.get("point")
    where = f"{setup['id']}: {name}"
    lathe = context.entries.get(setup.get("machine", "unknown"), {}).get("kind") == "lathe"
    feature = context.definitions[name]
    locator, model = located_point(context.definitions, context.frames, name)
    at = context.definitions.get(locator, {}).get("at")
    vector = isinstance(at, list) and len(at) == 3
    unbound = frame == "unknown" or frame.get("binding") == "unknown"
    local_from = None
    if label is None:
        # A child (counterbore, chamfer) sits on its parent hole's centre.
        require(row.get("located_by", name) == locator, f"{where}: locator differs")
        require(name in located or vector, f"{where}: no located feature or at places it")
        local = frame_point(model, frame)
    else:
        require(isinstance(label, str) and "located_by" not in row, f"{where}: station row")
        station = re.fullmatch(r"drawing station ([1-9][0-9]*)", label)
        end = re.fullmatch(r"op (.+) (to_z|z_from|z_to)", label)
        span = re.fullmatch(r"(spindle|setup Z) axis, kernel span (start|end)", label)
        if lathe and station:
            stations, index = feature.get("z_mm"), int(station[1]) - 1
            require(isinstance(stations, list) and index < len(stations), f"{where}: {label}")
            source = context.frames.get(feature.get("frame", "model"), "unknown")
            source = source if isinstance(source, dict) else "unknown"
            model = model_point([0.0, 0.0, stations[index]], source)
            local = frame_point(model, frame)
        elif lathe and end:
            op = next(
                (op for op in setup["ops"] if str(op.get("op")) == end[1]),
                {},
            )
            z = op.get(end[2]) if op.get("feature") == name else "unknown"
            require(numeric(z), f"{where}: {label} names no authored Z of its op")
            model = model_point([0.0, 0.0, "unknown" if unbound else z], frame)
            local = frame_point(model, frame)
            if unbound and local[2] == "unknown":
                local[2] = z
                local_from = {"op": op["op"], "field": end[2], "axis": "z"}
        elif span and span[1] == ("spindle" if lathe else "setup Z"):
            placed = vector and all(map(numeric, at))
            revolved = lathe or (locator == name and "at" not in feature)
            require(name in located and not placed and revolved, f"{where}: {label}")
            reference = f"kernel: setups.{setup['id']}.revolved.{name} ("
            require(
                any(
                    isinstance(citation, str) and citation.startswith(reference)
                    for citation in context.citations
                ),
                f"{where}: a kernel span end its kernel faces do not cite",
            )
            facts = measured_setup(context.kernel, setup["id"]).get("revolved")
            fact = facts.get(name) if isinstance(facts, dict) else None
            measured = fact.get("z_mm") if isinstance(fact, dict) else None
            scale = UNIT_MM.get(context.features.get("units"))
            require(
                not unbound
                and scale is not None
                and isinstance(measured, list)
                and len(measured) == 2
                and all(map(numeric, measured))
                and measured[0] <= measured[1],
                f"{where}: no independent kernel run measures its span",
            )
            local = [0.0, 0.0, measured[0 if span[2] == "start" else 1] / scale]
            model = model_point(local, frame)
        else:
            raise ValueError(f"{where}: {label!r} is no point the plan or the kernel places")
    require(row.get("local_from") == local_from, f"{where}: local endpoint provenance")
    if lathe and label is not None:
        diameter = feature.get("dia_nominal", "unknown")
        if not numeric(diameter):
            diameter = feature.get("dia", "unknown") if numeric(feature.get("dia")) else "unknown"
        if not numeric(diameter) and not span and numeric(feature.get("base_radius")):
            diameter = 2 * feature["base_radius"]
        radius = context.plan.get("dro", {}).get("radius_mode") is True
        target = diameter / 2 if radius and numeric(diameter) else diameter
        same(row.get("dia_nominal", "unknown"), diameter, f"{where}: {label} nominal diameter")
        same(row.get("x_target_mm", "unknown"), target, f"{where}: {label} X target")
    else:
        require(not {"dia_nominal", "x_target_mm"} & row.keys(), f"{where}: no turned X target")
    return model, local


def check_coordinates(
    setup: dict,
    features: dict,
    finding: dict,
    plan: dict,
    entries: dict,
    inventory: dict,
    kernel,
) -> None:
    """Hold every coordinate row to the point the plan and the manifest place it at
    (:func:`coordinate_place`; a kernel span end where the validator's own ``kernel`` run
    measures it), moved by the plan aims bearing on it (:func:`check_aims`), and a mill
    row's printed DRO target and tool-axis X/Y to that standing point on the machine's DRO
    grid (:func:`dro_grid`). No reported coordinate is an operand."""
    frame = setup_frame(setup, plan, features)
    sid = setup["id"]
    if setup["frame"] in plan.get("frames", {}):
        require(
            f"plan.frames.{setup['frame']}: author-declared setup frame" in finding["cite"],
            f"{sid}: plan-owned frame provenance missing from coordinates",
        )
    definitions = operative_definitions(plan, features)
    context = SimpleNamespace(
        plan=plan,
        features=features,
        definitions=definitions,
        frames=features["frames"] if isinstance(features["frames"], dict) else {},
        entries=entries,
        inventory=inventory,
        citations=finding["cite"],
        kernel=kernel,
    )
    numbers = finding["numbers"]
    # Only a manual bench setup waives its coordinates (check_subjects): a cutting setup's
    # are a verdict, never not_applicable or informational.
    require(
        finding["status"] in {"pass", "unknown", "error"}, f"{sid}: coordinates cannot be waived"
    )
    rows = numbers.get("rows", [])
    lathe = entries.get(setup.get("machine", "unknown"), {}).get("kind") == "lathe"
    grid = dro_grid(setup, features, entries)
    shown = numbers.get("dro_grid")
    require(isinstance(shown, dict) and set(shown) == {"step", "decimals"}, f"{sid}: DRO grid")
    near(shown["step"], grid[0], f"{sid}: DRO grid step")
    require(shown["decimals"] == grid[1], f"{sid}: DRO grid decimals")
    centred = {op.get("feature") for op in setup["ops"] if op.get("do") in CENTRE_OPS}
    named = dict.fromkeys(name for op in setup["ops"] for name in op_features(op) or [None])
    located = [
        name
        for name in named
        if isinstance(name, str)
        and (definitions.get(name, {}).get("kind") in LOCATED_KINDS or name in centred)
    ]
    for name in located:
        require(any(row.get("feature") == name for row in rows), f"{sid}: {name} is not located")
    places = {}
    for row in rows:
        require(row.get("feature") in definitions, "unknown coordinate feature")
        places[id(row)] = coordinate_place(context, setup, frame, row, located)
        for actual, expected in zip(row["model"], places[id(row)][0], strict=True):
            near(actual, expected, f"{sid}: {row['feature']}: model coordinate")
    stations = [(row["feature"], row["point"]) for row in rows if "point" in row]
    require(len(set(stations)) == len(stations), f"{sid}: a station row repeats")
    for name in {name for name, point in stations if "kernel span" in point}:
        ends = {point.rsplit(" ", 1)[1] for owner, point in stations if owner == name}
        require(ends >= {"start", "end"}, f"{sid}: {name}: a kernel span lacks an end")
    standing = check_aims(context, setup, finding, frame, places)
    for row in rows:
        where = f"{sid}: {row['feature']}"
        # A row a plan aim moves stands at the moved point; its nominal target is checked
        # as nominal_setup (check_aims).
        moved = id(row) in standing
        target = frame_point(standing[id(row)], frame) if moved else places[id(row)][1]
        for actual, expected in zip(row["setup"], target, strict=True):
            near(actual, expected, f"{where}: setup coordinate")
        if "point" not in row:
            require(
                all(map(numeric, target)) or finding["status"] != "pass",
                f"{where}: an unplaced located target cannot pass",
            )
        if lathe:
            require(not {"dro", "dro_xy"} & row.keys(), f"{where}: a lathe row has no mill DRO")
            continue
        # What the feature map prints and a hole op dials: the standing point on the grid.
        if all(map(numeric, target)):
            dro = [dro_target(value, grid) for value in target]
            require(isinstance(row.get("dro"), list), f"{where}: printed DRO target")
            for actual, expected in zip(row["dro"], dro, strict=True):
                near(actual, expected, f"{where}: printed DRO target")
            dialled_xy = dro[:2]
        else:
            require("dro" not in row, f"{where}: an unplaced target prints no DRO stop")
            require("point" not in row, f"{where}: an unplaced station row")
            dialled_xy = [dro_target(value, grid) for value in target[:2]]
        require(isinstance(row.get("dro_xy"), list), f"{where}: tool-axis DRO X/Y")
        for actual, expected in zip(row["dro_xy"], dialled_xy, strict=True):
            near(actual, expected, f"{where}: tool-axis DRO X/Y")


class SheetText(HTMLParser):
    def __init__(self):
        super().__init__()
        self.text = []
        self.hidden = 0

    def handle_starttag(self, tag, attrs):
        if tag in {"style", "script"}:
            self.hidden += 1

    def handle_endtag(self, tag):
        if tag in {"style", "script"}:
            self.hidden -= 1

    def handle_data(self, data):
        if not self.hidden:
            self.text.append(data)


def check_sheet(folder: Path, report: dict, expected_subdir: str = "expected") -> None:
    html = (folder / expected_subdir / "traveler.html").read_text(encoding="utf-8")
    parser = SheetText()
    parser.feed(html)
    text = " ".join(parser.text)
    require(
        "PLANNED" in text and not re.search(r"(?<!NOT )\bCHECKED\b", text),
        "sheet claims unchecked approval",
    )
    # 79f61ad keeps the hash off the printed page; the sheet binds it in its head.
    require(
        f'<meta name="prechips-report" content="{report["hash"]}">' in html,
        "sheet/report binding mismatch",
    )
    require(
        "@page" in html and re.search(r"size\s*:\s*(?:letter|8.5in)", html, re.I),
        "missing Letter print CSS",
    )
    require(
        not re.search(r"\.(?:toml|yaml|json|py|csv)\b|cad/|examples/", text),
        "bench sheet contains file paths",
    )
    rules = (
        FEATURE_RULES
        | SETUP_RULES
        | {
            "tool_resolves",
            "speeds_feeds",
            "inspection",
            "turned_profile",
            "stickout",
            "stock_diameter",
            "indexing",
            "turning_deflection",
            "engagement",
            "construction",
        }
    )
    machine_ids = "|".join(sorted(rule for rule in rules if "_" in rule))
    labelled_ids = "|".join(sorted(rules))
    require(
        not re.search(rf"\b(?:{machine_ids})\b|\brule[\s:]+(?:{labelled_ids})\b", text, re.I),
        "bench sheet contains rule ids",
    )
    if any(f["status"] == "unknown" for f in report["findings"]):
        require("?" in text, "sheet hides required unknowns")
    if any(f["status"] == "error" for f in report["findings"]):
        require("✗" in text, "sheet hides errors")


def check_construction(plan: dict, features: dict, finding: dict) -> None:
    candidate = plan.get("construction", "unknown")
    permission = features.get("construction", "unknown")
    require(
        finding["numbers"]
        == {
            "plan_construction": candidate,
            "drawing_construction": permission,
        },
        "construction evidence does not identify the candidate and drawing",
    )
    if candidate == "built_up":
        expected = "pass" if permission == "built_up_permitted" else "error"
    else:
        expected = "pass" if candidate == "one_piece" else "unknown"
    require(finding["status"] == expected, "construction gate disagrees with drawing permission")


def check_indexing(setup: dict, features: dict, entries: dict, finding: dict) -> None:
    declaration = setup["hold"].get("index")
    if declaration is None:
        require(finding["status"] == "not_applicable", "undeclared indexing must be inapplicable")
        return
    requested = (
        Fraction(360, declaration["positions"])
        if "angle_deg" not in declaration
        else Fraction(str(declaration["angle_deg"]))
    )
    item = entries[declaration["fixture"]]
    ratio = Fraction(str(item["worm_ratio"]))
    # Independent exhaustive oracle: search complete turns and every space on
    # EVERY inventory circle, plus every direct slot near the desired setting.
    # It does not use the rule's rounding or candidate-generation helpers.
    options = []
    for method, plate, circle, multiplier in [
        ("worm", plate, int(circle), ratio)
        for plate, circles in item["plate_holes"].items()
        for circle in circles
    ] + [("direct", "direct", int(item["direct_index"]["positions"]), Fraction(1))]:
        central_turn = int(abs(requested) * multiplier / 360)
        for turns in range(max(0, central_turn - 1), central_turn + 2):
            for spaces in range(circle):
                for sign in (-1, 1):
                    actual = sign * Fraction(360 * (turns * circle + spaces), circle) / multiplier
                    options.append(
                        (
                            abs(actual - requested),
                            method != "direct",
                            plate,
                            circle,
                            sign * (turns * circle + spaces),
                            actual,
                            method,
                            turns,
                            spaces,
                        )
                    )
    chosen = min(options)
    _, _, plate, circle, signed_count, actual, method, turns, spaces = chosen
    row = finding["numbers"]
    for key, expected in {
        "fixture": declaration["fixture"],
        "feature": declaration["feature"],
        "positions": declaration["positions"],
        "requested_angle_fraction": str(requested),
        "method": method,
        "plate": plate,
        "circle": circle,
        "turns": turns,
        "spaces": spaces,
        "direction": "reverse" if signed_count < 0 else "forward",
        "exact": actual == requested,
        "selection_complete": True,
        "verified": not uncertain(declaration["fixture"], entries),
    }.items():
        require(row[key] == expected, f"{setup['id']}: indexing {key} disagrees with inventory")
    near(row["requested_angle_deg"], float(requested), "indexing requested angle")
    near(row["actual_angle_deg"], float(actual), "indexing nearest setting")
    feature = features["features"][declaration["feature"]]
    tolerance = feature.get(
        "angle_tol_deg",
        "unknown"
        if feature.get("dimension_type") == "basic"
        else features["general_tolerances"]["angular_deg"],
    )
    near(row["tolerance_deg"], tolerance, "indexing explicit feature tolerance")
    errors = [
        float(position * (actual - requested))
        for position in range(1, declaration["positions"] + 1)
    ]
    require(len(row["position_errors_deg"]) == len(errors), "indexing landing count mismatch")
    for observed, expected in zip(row["position_errors_deg"], errors, strict=True):
        near(observed, expected, "indexing signed landing error")
    near(row["max_position_error_deg"], max(map(abs, errors)), "indexing maximum landing error")
    full_pattern = declaration["positions"] >= 2 and "angle_deg" not in declaration
    if not full_pattern:
        require(row["closure"] == "not_applicable", "open or single indexing has no closure")
    else:
        total = declaration["positions"] * actual
        lower = total // 360
        revolutions = min((lower, lower + 1), key=lambda k: (abs(total - 360 * k), k))
        closure = row["closure"]
        near(closure["target_angle_deg"], 360 * revolutions, "indexing full-pattern target")
        near(closure["actual_angle_deg"], float(total), "indexing full-pattern total")
        near(closure["error_deg"], float(total - 360 * revolutions), "indexing closure error")
        expected = (
            abs(total - 360 * revolutions) <= Fraction(str(tolerance))
            if numeric(tolerance)
            else "unknown"
        )
        require(closure["within_tolerance"] == expected, "indexing closure allowance mismatch")
    # The verdict is the inventory's and the drawing's: a fixture that is not a dividing
    # head or a negative tolerance contradicts the plan; an unknown kind or tolerance, or
    # an unverified head, leaves it tentative; else every landing (and a full pattern's
    # closure) inside the tolerance passes and any outside it errors.
    kind = item.get("kind", "unknown")
    limit = Fraction(str(tolerance)) if numeric(tolerance) else None
    if kind not in {"dividing_head", "unknown"} or (limit is not None and limit < 0):
        status = "error"
    elif limit is None or kind == "unknown" or uncertain(declaration["fixture"], entries):
        status = "unknown"
    else:
        steps = [abs(position * (actual - requested)) for position in range(1, len(errors) + 1)]
        closes = not full_pattern or abs(total - 360 * revolutions) <= limit
        status = "pass" if closes and all(step <= limit for step in steps) else "error"
    require(
        finding["status"] == status,
        f"{setup['id']}: indexing verdict {finding['status']} is not the {status} its "
        "dividing head and tolerance decide",
    )


def finished_exposed_diameter(setup: dict, features: dict, plan: dict | None = None):
    """Independent midpoint oracle for the fixtures' declared finished profile."""
    units = features.get("units")
    scale = 1 if units == "mm" else 25.4 if units == "in" else None
    state = setup.get("stock_state")
    state = state if isinstance(state, dict) else {}
    length = setup.get("hold", {}).get("stickout_mm")
    ends = [state.get("north_end_z"), state.get("south_end_z")]
    if scale is None or not numeric(length) or length <= 0 or not all(map(numeric, ends)):
        return "unknown"
    upper = max(ends)
    lower = upper - length
    frames = features.get("frames", {})
    target = setup_frame(setup, plan or {}, features)
    if (
        not isinstance(target, dict)
        or target.get("binding") == "unknown"
        or not isinstance(target.get("z"), list)
    ):
        return "unknown"
    target = dict(target, origin=[v * scale for v in target["origin"]])
    claimed = {
        op.get("feature")
        for op in setup["ops"]
        if op["do"]
        in {
            "turn",
            "rough_turn",
            "finish_turn",
            "profile_turn",
            "profile",
            "form",
            "form_dome",
            "form_relief",
            "groove",
            "rough_groove",
            "finish_groove",
        }
    }
    intervals = []
    for name, feature in features["features"].items():
        kind = feature.get("kind")
        if kind not in {"cylinder", "boss", "groove"} and name not in claimed:
            continue
        stations = feature.get("z_mm")
        source = frames.get(feature.get("frame", "model"), {})
        axis = source.get("z")
        if (
            not isinstance(stations, list)
            or len(stations) != 2
            or not all(map(numeric, stations))
            or source.get("binding") == "unknown"
            or axis not in (target["z"], [-v for v in target["z"]])
            or feature.get("axis", [0, 0, 1]) not in ([0, 0, 1], [0, 0, -1])
        ):
            return "unknown"
        source = dict(source, origin=[v * scale for v in source["origin"]])
        span = sorted(
            frame_point(model_point([0, 0, station * scale], source), target)[2]
            for station in stations
        )
        if span[0] == span[1]:
            return "unknown"
        start, stop = max(lower, span[0]), min(upper, span[1])
        if start >= stop:
            continue
        value = next(
            (feature[key] for key in ("dia_nominal", "nominal_dia", "dia") if key in feature),
            "unknown",
        )
        if kind not in {"cylinder", "boss", "groove"} or not numeric(value) or value <= 0:
            return "unknown"
        intervals.append((start, stop, kind, value * scale))
    boundaries = sorted({lower, upper} | {z for a, b, _, _ in intervals for z in (a, b)})
    diameters = []
    for start, stop in zip(boundaries, boundaries[1:], strict=False):
        middle = (start + stop) / 2
        active = [(kind, diameter) for a, b, kind, diameter in intervals if a < middle < b]
        base = {d for kind, d in active if kind != "groove"}
        grooves = {d for kind, d in active if kind == "groove"}
        chosen = grooves or base
        if len(chosen) != 1 or len(base) > 1 or (grooves and base and min(grooves) > min(base)):
            return "unknown"
        diameters.append(min(chosen))
    return min(diameters) if diameters else "unknown"


def kernel_exposed_profile(setup: dict, plan: dict, features: dict, held, kernel):
    """The exposed profile of a setup whose features declare no ``z_mm`` stations, as the
    traveler's stick-out row reports it (``segments``, their least ``diameter_mm``, and
    the kernel facts it must cite as ``cites`` prefixes), recomputed from the plan, the
    manifest and the validator's own kernel run (``kernel``, :func:`independent_kernel`),
    never the report; None when they do not derive it. The span runs from the stock ends
    over the declared stick-out; each present turned feature (and each one a profiling op
    claims) stands where that run measures its faces of revolution about setup Z (a
    transient joint cylinder where its declared ends lie on the spindle), clipped to the
    span, at its declared nominal diameter (a dome, narrowing away from the chuck, at the
    base its declared radius and height give); a groove stands for the cylinder it cuts
    into; exposed stock beyond every such feature counts at the least radius that run's
    stock profile measures there. A feature with no such span (unless measured revolved
    contradicts, a gap between features, disagreeing overlaps, a dome base or stock wider
    than a known ``held`` diameter or a span the stock profile does not cover derive none;
    an unknown ``held`` bounds nothing (the verdict stays unknown without it)."""
    definitions = operative_definitions(plan, features)
    scale = UNIT_MM.get(features.get("units"))
    state = setup.get("stock_state")
    state = state if isinstance(state, dict) else {}
    length = setup.get("hold", {}).get("stickout_mm")
    ends = [state.get("north_end_z"), state.get("south_end_z")]
    frame = setup_frame(setup, plan, features)
    measured = measured_setup(kernel, setup["id"])
    revolved = measured.get("revolved")
    if (
        any("z_mm" in feature for feature in definitions.values())
        or scale is None
        or not numeric(length)
        or length <= 0
        or not all(map(numeric, ends))
        or not isinstance(frame, dict)
        or frame.get("binding") == "unknown"
        or not isinstance(revolved, dict)
    ):
        return None
    exposure = [max(ends) - length, max(ends)]
    origin = [value * scale if numeric(value) else "unknown" for value in frame.get("origin", [])]
    spindle = dict(frame, origin=origin)
    off_axis = measured.get("revolved_off_axis")
    off_axis = off_axis if isinstance(off_axis, dict) else {}
    claimed = {op.get("feature", "unknown") for op in setup["ops"] if op.get("do") in PROFILE_OPS}
    bundle = SimpleNamespace(plan=plan, features=features, feature_definitions=definitions)
    names = {
        name
        for name, definition in definitions.items()
        if definition.get("kind") in AXIAL_KINDS and present(bundle, setup, name)
    } | claimed

    def pair(value) -> bool:
        return (
            isinstance(value, list)
            and len(value) == 2
            and all(numeric(item) and math.isfinite(item) for item in value)
        )

    intervals, cites = [], set()
    for name in sorted(names):
        definition = definitions.get(name)
        if not isinstance(definition, dict):
            return None
        joint = definition.get("joint") is not None
        fact = None if joint else revolved.get(name)
        span = fact.get("z_mm") if isinstance(fact, dict) else None
        if joint:
            declared = setup_span_mm(bundle, name, spindle)
            span = list(declared) if declared is not None else None
        if not pair(span):
            axis = off_axis.get(name, {})
            axis = axis.get("axis") if isinstance(axis, dict) else None
            if not joint and name not in claimed and isinstance(axis, list) and len(axis) == 3:
                continue
            return None
        if span[0] >= span[1]:
            return None
        low, high = max(span[0], exposure[0]), min(span[1], exposure[1])
        if low >= high:
            continue
        kind = definition.get("kind")
        keys = ("dia_nominal", "nominal_dia", "dia")
        key = next((key for key in keys if key in definition), None)
        nominal = definition[key] if key is not None else "unknown"
        nominal = nominal * scale if numeric(nominal) and nominal > 0 else "unknown"
        if kind == "dome":
            radii = fact.get("end_radii_mm") if isinstance(fact, dict) else None
            if not (pair(radii) and radii[0] - radii[1] > RADIUS_TOL_MM):
                return None
            diameter = dome_base_mm(definition, scale)
            # A declared diameter the base contradicts leaves the dome unresolved.
            if key is not None and not (
                numeric(nominal)
                and numeric(diameter)
                and math.isclose(nominal, diameter, rel_tol=1e-10, abs_tol=1e-8)
            ):
                return None
        elif kind in AXIAL_KINDS:
            diameter = nominal
        else:
            return None
        too_wide = kind == "dome" and numeric(held) and diameter > held + 1e-6
        if not numeric(diameter) or diameter <= 0 or too_wide:
            return None
        intervals.append((low, high, kind, diameter, name))
        if not joint:
            cites.add(f"kernel: setups.{setup['id']}.revolved.{name} (")
    segments, previous = [], None
    boundaries = sorted({z for low, high, *_ in intervals for z in (low, high)})
    for low, high in zip(boundaries, boundaries[1:], strict=False):
        active = [item for item in intervals if item[0] <= low and high <= item[1]]
        cylinders = [item for item in active if item[2] != "groove"]
        grooves = [item for item in active if item[2] == "groove"]
        chosen = grooves or cylinders
        if (
            not chosen
            or any(not same_length(item[3], chosen[0][3]) for item in chosen)
            or any(not same_length(item[3], cylinders[0][3]) for item in cylinders)
            or (
                grooves
                and cylinders
                and not same_length(grooves[0][3], cylinders[0][3])
                and grooves[0][3] > cylinders[0][3]
            )
        ):
            return None
        base = (
            cylinders[0][3]
            if cylinders
            else previous["base_diameter_mm"]
            if previous is not None
            else "unknown"
        )
        previous = {
            "z_mm": [low, high],
            "diameter_mm": chosen[0][3],
            "base_diameter_mm": base,
            "features": sorted(item[4] for item in chosen),
        }
        segments.append(previous)
    uncovered = [list(exposure)] if not segments else []
    if segments:
        first, last = segments[0]["z_mm"][0], segments[-1]["z_mm"][1]
        if first > exposure[0] and not same_length(first, exposure[0]):
            uncovered.append([exposure[0], first])
        if last < exposure[1] and not same_length(last, exposure[1]):
            uncovered.append([last, exposure[1]])
    rows = measured.get("stock_profile") if uncovered else []
    well_formed = isinstance(rows, list) and all(
        isinstance(row, list)
        and len(row) == 4
        and pair(row[:2])
        and pair(row[2:])
        and row[0] < row[1]
        and 0 <= row[2] <= row[3]
        for row in rows
    )
    if not well_formed:
        return None
    for low, high in uncovered:
        reach = low
        cites.add(f"kernel: setups.{setup['id']}.stock_profile (")
        for z0, z1, least, _ in sorted(rows):
            if z1 <= reach or same_length(z1, reach) or z0 >= high:
                continue
            if z0 > reach and not same_length(z0, reach):
                break
            if not 0 < 2 * least or (numeric(held) and 2 * least > held + 1e-6):
                return None
            top = min(z1, high)
            segments.append(
                {
                    "z_mm": [reach, top],
                    "diameter_mm": 2 * least,
                    "features": [],
                    "source": "kernel_stock",
                }
            )
            reach = top
        if reach < high and not same_length(reach, high):
            return None
    if not segments:
        return None
    diameter = min(segment["diameter_mm"] for segment in segments)
    return {
        "diameter_mm": diameter,
        "exposed_z_mm": exposure,
        "segments": segments,
        "cites": cites,
    }


def same_segments(reported, expected: list) -> bool:
    """Whether the report's stick-out ``segments`` are ``expected`` ones: the same spans,
    diameters, base diameters, features and sources, in order."""

    def close(a, b) -> bool:
        if numeric(b):
            return numeric(a) and math.isclose(a, b, rel_tol=1e-10, abs_tol=1e-8)
        return a == b

    return (
        isinstance(reported, list)
        and len(reported) == len(expected)
        and all(
            isinstance(got, dict)
            and set(got) == set(want)
            and isinstance(got["z_mm"], list)
            and len(got["z_mm"]) == 2
            and all(map(close, got["z_mm"], want["z_mm"]))
            and close(got["diameter_mm"], want["diameter_mm"])
            and close(got.get("base_diameter_mm"), want.get("base_diameter_mm"))
            and got["features"] == want["features"]
            and got.get("source") == want.get("source")
            for got, want in zip(reported, expected, strict=False)
        )
    )


def held_stock(setup: dict, plan: dict):
    """The chucked stock's diameter as ``stickout.held_diameter`` counts it: the stock
    state's ``od_mm``, else the bar's ``dia_mm`` only while the plan does not flag the
    bar's form for verification (``stock.form_verify`` true or unknown); a stock state
    declared unknown has none. Unknown unless a positive number: an unverified fallback
    is never a held diameter."""
    state = setup.get("stock_state")
    if not isinstance(state, dict):
        return "unknown"
    if "od_mm" in state:
        value = state["od_mm"]
    else:
        stock = plan.get("stock") if isinstance(plan.get("stock"), dict) else {}
        if stock.get("form_verify") in (True, "unknown"):
            return "unknown"
        value = stock.get("dia_mm", "unknown")
    return value if numeric(value) and value > 0 else "unknown"


def check_stickout(
    setup: dict,
    plan: dict,
    features: dict,
    inventory: dict,
    policy: dict,
    finding: dict,
    kernel,
) -> None:
    """Hold the stick-out row to the plan: the finished exposed diameter from declared
    stations (:func:`finished_exposed_diameter`), else the profile the validator's own
    kernel run derives (:func:`kernel_exposed_profile`), whose segments the row reports
    and whose kernel facts it cites; neither derived, it stays unknown. The held diameter
    is the plan's trusted one (:func:`held_stock`), the selected support the plan's hold
    read through the inventory (``stickout.support_state``), and the verdict the one
    those inputs decide, never a report field."""
    row = finding["numbers"]
    held = held_stock(setup, plan)
    diameter = finished_exposed_diameter(setup, features, plan)
    profile = None
    if diameter == "unknown":
        profile = kernel_exposed_profile(setup, plan, features, held, kernel)
    if profile is not None:
        diameter = profile["diameter_mm"]
        cites = [cite for cite in finding["cite"] if isinstance(cite, str)]
        require(
            all(any(cite.startswith(ref) for cite in cites) for ref in profile["cites"]),
            "stick-out finished exposed diameter: an uncited kernel span or stock profile",
        )
        exposed = row.get("exposed_z_mm")
        require(
            isinstance(exposed, list)
            and len(exposed) == 2
            and all(map(numeric, exposed))
            and all(map(same_length, exposed, profile["exposed_z_mm"]))
            and same_segments(row.get("segments"), profile["segments"]),
            "stick-out finished exposed diameter: span or segments differ from the derived profile",
        )
    length = setup["hold"].get("stickout_mm", "unknown")
    near(row["held_diameter_mm"], held, "stick-out held diameter evidence")
    near(row["diameter_mm"], diameter, "stick-out finished exposed diameter")
    near(row["stickout_mm"], length, "stick-out declared length")
    limit_ratio = policy["numbers"]["stickout_ld_max"]
    near(row["stickout_ld_max"], limit_ratio, "stick-out shop ratio")
    citation = policy["numbers_cite"]["stickout_ld_max"]
    citations = citation if isinstance(citation, list) else [citation]
    cited = any(isinstance(c, str) and c.strip() and c != "unknown" for c in citations)
    verified = policy["numbers_verify"]["stickout_ld_max"] is False
    known_limit = numeric(limit_ratio) and limit_ratio > 0 and cited and verified
    limit = diameter * limit_ratio if known_limit and numeric(diameter) else "unknown"
    near(row["unsupported_limit_mm"], limit, "stick-out unsupported limit")
    support, supports = support_state(SimpleNamespace(plan=plan, inventory=inventory), setup)
    require(
        row["support_status"] == support and row["supports"] == supports,
        "stick-out selected support differs from the plan's hold in the inventory",
    )
    machines = inventory.get("machines", {})
    machine = machines.get(setup.get("machine")) if isinstance(machines, dict) else None
    kind = machine.get("kind", "unknown") if isinstance(machine, dict) else "unknown"
    if kind != "lathe":
        status = "unknown" if kind == "unknown" else "not_applicable"
    elif not numeric(length) or length < 0 or not numeric(held):
        status = "unknown"
    elif length == 0 and (known_limit or support == "pass"):
        status = "pass"
    elif not numeric(diameter):
        status = "unknown"
    elif support == "pass":
        status = "pass"
    elif not known_limit:
        status = "unknown"
    elif length <= limit:
        status = "pass"
    else:
        status = "unknown" if support == "unknown" else "error"
    require(
        finding["status"] == status,
        f"stick-out verdict {finding['status']} is not the {status} its inputs decide",
    )


def check_cone_facts(plan: dict, features: dict) -> None:
    # User-approved example divergence (examples/README.md): the export says one_piece;
    # the example treats the drawing as permitting the built-up candidate.
    require(
        features["construction"] == "built_up_permitted",
        "cone drawing lost its approved built-up permission",
    )
    # Example divergence (examples/README.md, HA #1215 comment): the built-up variant's
    # paint/mask split replaces only MASK MACHINED FACES; the coating spec stays exported.
    require(
        features["material"]["finish"]
        == "RAL 6005 ALKYD; SSPC-SP 3; 50-75 um DFT; built-up variant: paint RAL 6005 on "
        "non-functional turned ODs; mask bores, faces and joint surfaces; OIL BARE FACES ISO VG 32",
        "cone finish divergence drifted from the approved built-up paint/mask text",
    )
    for field, expected in (
        ("linear_1pl", 0.8),
        ("linear_2pl", 0.51),
        ("linear_3pl", 0.13),
    ):
        near(features["general_tolerances"][field], expected, "cone rendered general tolerance")
    geometry = features["features"]
    for name, fields in {
        "body": {"dia_nominal": 42.011, "height_nominal": 86.0},
        "head": {"dia_nominal": 42.7506, "height_nominal": 26.6},
        "crank_boss": {"dia_nominal": 21.93},
        "crank_boss_faces": {"length_nominal": 72.0344, "station_nominal": 21.3753},
        "crank_bore": {"nominal_dia": 11.438, "land_angle_nominal_deg": 12.5182},
        "cone_boss": {"dia_nominal": 17.2},
        "cone_boss_north_face": {"length_nominal": 42.011},
        "journal_bore": {"nominal_dia": 12.2808},
        "mount_west": {"nominal_dia": 7.14248},
        "mount_east": {"nominal_dia": 7.14248},
    }.items():
        for field, expected in fields.items():
            near(geometry[name][field], expected, f"cone source {name}.{field}")
    require(
        geometry["crank_bore"]["precision"]["land_angle_nominal_deg"] == 4,
        "BASIC angle lost four places",
    )
    require(geometry["crank_bore"]["dimension_type"] == "basic", "cone angle lost BASIC identity")
    # Example divergences (examples/README.md, HA #1215): the R0.25 title-block break on the
    # CAD-sharp body/head step corner, and the cap-to-cap / foot-to-top bands copied onto the
    # second face that terminates each dimension. Each copy must equal its exported source band
    # and must not turn into a new drawing requirement on that face.
    near(geometry["body"]["corner_radius_max_design"], 0.25, "cone body step-corner divergence")
    for copy, field, source, band in (
        ("cone_boss_south_face", "length", "cone_boss_north_face", [41.5, 42.52]),
        ("foot_seat", "height", "body", [85.2, 86.8]),
    ):
        require(
            geometry[copy][field] == geometry[source][field] == band
            and geometry[copy][f"{field}_nominal"] == geometry[source][f"{field}_nominal"],
            f"cone {copy}.{field} divergence no longer equals the exported {source} band",
        )
        require(
            field not in geometry[copy]["requirements"],
            f"cone {copy}.{field} divergence became a drawing requirement",
        )
    # Example divergence (examples/README.md): the BASIC angle may carry only the angular
    # limit HA derives from the 0.10 diametral FCF over the 72.0344 crank bore
    # (cone_pivot_post_spec.py:373-375), never an independent +/- band.
    angle_tol = geometry["crank_bore"].get("angle_tol_deg", "unknown")
    require(
        angle_tol == "unknown"
        or abs(
            angle_tol
            - math.degrees(
                math.atan(
                    geometry["crank_bore"]["angularity_dia"]
                    / geometry["crank_boss_faces"]["length_nominal"]
                )
            )
        )
        < 5e-5,
        "BASIC angle acquired a +/- band beyond its FCF-derived limit",
    )
    near(geometry["crank_bore"]["angularity_dia"], 0.10, "cone diametral FCF")
    require(
        geometry["crank_bore"]["angularity_datums"] == ["A", "B"], "cone lost ordered A/B datums"
    )
    require("angularity_dia" in geometry["crank_bore"]["requirements"], "FCF inspection omitted")
    require(features["datums"]["A"]["feature"] == "journal_bore", "datum A is not the cone bore")
    require(features["datums"]["B"]["feature"] == "foot_seat", "datum B is not the foot")
    require(
        all(isinstance(f["faces"], list) and f["faces"] for f in geometry.values()),
        "exported cone features lost STEP face bindings",
    )
    require(features["frames"]["setup"] == "unknown", "unverified setup binding")
    # "nominal" places model geometry in setup coordinates; a plan frame never claims a
    # measured physical binding.
    require(
        all(
            frame["binding"] in {"unknown", "nominal"} for frame in plan.get("frames", {}).values()
        ),
        "cone plan frames claim a physical binding",
    )
    require(plan["stock"]["on_hand"] is False, "authored cone blanks are not on-hand inventory")
    pieces = plan["stock"].get("components", [plan["stock"]])
    require(
        all("AUTHOR'S CHOICE" in p["cite"] for p in pieces),
        "blank dimensions lack author provenance",
    )
    require(
        [p.get("id") for p in pieces] == ["body", "cone", "crank"],
        "built-up candidate must declare its three real leaf blanks: body, cone and crank sleeves",
    )
    require(plan["stock"]["form"] == "built_up", "built-up blank form lost candidate identity")


def validate_fixture(
    part: str,
    documents: dict,
    plan_filename: str = "plan.toml",
    expected_subdir: str = "expected",
) -> tuple[int, list]:
    folder = EXAMPLES / part
    plan = documents[folder / plan_filename]
    features = documents[folder / "features.toml"]
    require(plan["part"] == features["part"] == part, "part identity mismatch")
    require(features.get("features"), "empty manifest")
    digest = features["step_sha256"]
    if digest != "unknown":
        require(
            re.fullmatch(r"[0-9a-f]{64}", digest) is not None,
            "invalid STEP digest asserted",
        )
    check_author_choices(plan)
    paths = input_paths(folder, plan, plan_filename)
    inventory = documents[paths["inventory"]]
    policy = documents[paths["shop_policy"]]
    cutting = documents[paths["cutting_data"]]
    entries = entries_for(inventory)
    report = read_report(folder / expected_subdir / "report.json")
    renders = report.get("renders", {})
    render_inputs = {f"render:{sid}" for sid in renders}
    require(set(report["inputs"]) == set(paths) | render_inputs, "report input bundle incomplete")
    for sid, asset in renders.items():
        image = folder / expected_subdir / asset["path"]
        require(image.read_bytes().startswith(b"\x89PNG\r\n\x1a\n"), "invalid fixture PNG")
        require(asset["sha256"] == sha256(image), "fixture render hash mismatch")
        require(
            report["inputs"][f"render:{sid}"] == {"path": asset["path"], "sha256": asset["sha256"]},
            "fixture render not bound to the report",
        )
    for key, path in paths.items():
        expected = {"path": path.relative_to(ROOT).as_posix(), "sha256": sha256(path)}
        require(report["inputs"][key] == expected, f"{part}: stale {key} input binding")
    require(report["step_sha256"] == features["step_sha256"], "STEP binding mismatch")
    if digest != "unknown":
        require(
            "step" in paths and sha256(paths["step"]) == digest, "STEP bytes differ from digest"
        )
    findings = {(f["rule"], f["subject"]): f for f in report["findings"]}
    check_construction(plan, features, findings["construction", part])
    if part == "cone-pivot-post":
        check_cone_facts(plan, features)
    check_frames(features, plan)
    check_subjects(plan, features, findings, inventory)
    check_required_coverage(policy, plan, features, findings)
    check_inspection_declarations(plan, features, findings)
    kernel = independent_kernel(folder / plan_filename)
    check_joint_declarations(plan, features, findings, kernel)
    missing = check_references(plan, entries, findings)
    missing += check_prepared_blank(plan, features, inventory, findings, kernel)
    depths = check_endpoints(plan, features, findings, entries)
    definitions = operative_definitions(plan, features)
    for setup in plan["setups"]:
        # check_subjects already holds bench and saw zero waivers to their facts.
        if manual_bench(inventory, setup) is None:
            if not saw_setup(setup):
                check_zero(setup, findings["zero_check", setup["id"]], entries, plan["dro"])
            check_coordinates(
                setup,
                features,
                findings["coordinates", setup["id"]],
                plan,
                entries,
                inventory,
                kernel,
            )
        check_indexing(setup, features, entries, findings["indexing", setup["id"]])
        check_stickout(
            setup, plan, features, inventory, policy, findings["stickout", setup["id"]], kernel
        )
        for op in setup["ops"]:
            check_speeds(
                plan,
                features,
                setup,
                op,
                findings["speeds_feeds", f"{setup['id']}:{op['op']}"],
                entries,
                cutting,
                definitions,
                depths,
            )
    exit_code = report_exit(report, policy, plan, features)
    candidate = part if plan_filename == "plan.toml" else f"{part}/{plan_filename}"
    require(
        exit_code == report["expected_exit"] == EXPECTED_EXIT[candidate],
        f"{candidate}: expected exit mismatch ({exit_code})",
    )
    check_sheet(folder, report, expected_subdir)
    return exit_code, missing


def validate_geometry_fixture(case: tuple, documents: dict) -> None:
    name, plan_filename, expected_subdir, expected_exit, failing_rule, modeled, failing = case
    folder = EXAMPLES / "geometry" / name
    plan = documents[(folder / plan_filename).resolve()]
    features = documents[(folder / plan["features"]).resolve()]
    Plan.model_validate(plan)
    paths = input_paths(folder, plan, plan_filename)
    report = read_report(folder / expected_subdir / "report.json")
    require(plan["part"] == features["part"], f"{name}: part identity mismatch")
    require(
        features["step_sha256"] == sha256(paths["step"]) == report["step_sha256"],
        f"{name}: STEP digest mismatch",
    )
    face_records = re.findall(
        r"#(\d+)\s*=\s*ADVANCED_FACE\s*\(\s*'((?:[^']|'')*)'",
        paths["step"].read_text(encoding="utf-8"),
        re.DOTALL,
    )
    require(face_records, f"{name}: no ADVANCED_FACE records")
    refs = set(plan["stock"].get("as_is_faces", []))
    for feature in features["features"].values():
        if isinstance(feature.get("faces"), list):
            refs.update(feature["faces"])
    for setup in plan["setups"]:
        for op in setup["ops"]:
            if isinstance(op.get("faces"), list):
                refs.update(op["faces"])
    for ref in refs:
        match = re.fullmatch(r"#(\d+)/ADVANCED_FACE\[(\d+)\]/(.*)", ref)
        require(match is not None, f"{name}: malformed face reference {ref}")
        entity, ordinal, label = match.groups()
        require(0 < int(ordinal) <= len(face_records), f"{name}: invalid face ordinal {ref}")
        actual_entity, actual_label = face_records[int(ordinal) - 1]
        require(
            (entity, label) == (actual_entity, actual_label.replace("''", "'")),
            f"{name}: face reference differs from bound STEP {ref}",
        )
    for kind, path in paths.items():
        require(
            report["inputs"][kind]
            == {"path": path.relative_to(ROOT).as_posix(), "sha256": sha256(path)},
            f"{name}: stale input binding {kind}",
        )
    require(
        set(report.get("renders", {})) == {setup["id"] for setup in plan["setups"]},
        f"{name}: numeric in-process stock render missing",
    )
    holds = {setup["id"]: setup.get("hold", {}) for setup in plan["setups"]}
    inventory = documents[paths["inventory"]]
    for sid, asset in report["renders"].items():
        scene = asset.get("scene", {})
        if sid in modeled:
            # Every drawn component exact, no debt, and the scene names the held kind.
            fixture = holds[sid].get("fixture")
            kinds = [
                inventory.get(category, {}).get(fixture, {}).get("kind")
                for category in ("fixtures", "machines")
            ]
            components = scene.get("components", [])
            require(
                asset.get("fixture") == "modeled"
                and scene.get("debts") == []
                and scene.get("fixture_kind") in kinds
                and components
                and all(component.get("exact") is True for component in components)
                and (
                    scene.get("fixture_kind") != "vise"
                    or (scene.get("jaws"), scene.get("parallels")) == ("exact", "exact")
                ),
                f"{name}: authored {sid} fixture scene is unresolved",
            )
        else:
            require(
                asset.get("fixture") != "modeled" and scene.get("debts"),
                f"{name}: unknown preparation holding is falsely modeled as clear",
            )
        image = (folder / expected_subdir / asset["path"]).resolve()
        require(image.is_relative_to((folder / expected_subdir).resolve()), "render path escapes")
        require(image.read_bytes().startswith(b"\x89PNG\r\n\x1a\n"), "invalid fixture PNG")
        binding = {"path": asset["path"], "sha256": sha256(image)}
        require(
            report["inputs"][f"render:{sid}"] == binding and asset["sha256"] == binding["sha256"],
            f"{name}: render is not bound to the report",
        )
    policy = documents[paths["shop_policy"]]
    check_required_coverage(
        policy, plan, features, [(row["rule"], row["subject"]) for row in report["findings"]]
    )
    require(
        report_exit(report, policy, plan, features) == report["expected_exit"] == expected_exit,
        "geometry exit",
    )
    if failing_rule:
        errors = {
            row["subject"]
            for row in report["findings"]
            if row["rule"] == failing_rule and row["status"] == "error"
        }
        expected = (
            {plan["part"]}
            if failing_rule == "coverage"
            else {sid if failing_rule in SETUP_GEOMETRY_RULES else f"{sid}:10" for sid in failing}
        )
        # Preparation setups may show their own errors; a modeled setup errors only if named.
        extra = {subject.split(":")[0] for subject in errors - expected - {plan["part"]}}
        require(
            expected <= errors and (failing_rule == "coverage" or not extra & set(modeled)),
            f"{name}: discriminating {failing_rule} errors differ: {sorted(errors)}",
        )
    else:
        require(
            all(
                row["status"] in {"pass", "not_applicable"}
                for row in report["findings"]
                if required_finding(row, policy, plan, features)
            ),
            f"{name}: successful geometry counterpart retains a required debt",
        )
    check_sheet(folder, report, expected_subdir)


def main() -> int:
    try:
        paths = sorted(EXAMPLES.rglob("*.toml"))
        require(paths, "no TOML fixtures found")
        documents = {
            path.resolve(): tomllib.loads(path.read_text(encoding="utf-8")) for path in paths
        }
        require(not list(EXAMPLES.rglob("*.yaml")), "obsolete YAML examples remain")
        require(not list(EXAMPLES.rglob("*.csv")), "obsolete external coordinate files remain")
        print(f"Parsed {len(documents)} TOML files.")
        for part in PARTS:
            code, missing = validate_fixture(part, documents)
            print(f"{part}: expected exit {code}; named missing: {', '.join(missing) or 'none'}")
        code, missing = validate_fixture(
            "cone-pivot-post",
            documents,
            "built-up.toml",
            "expected/built-up",
        )
        print(
            f"cone-pivot-post/built-up.toml: expected exit {code}; named missing: "
            f"{', '.join(missing) or 'none'}"
        )
        for case in GEOMETRY_CASES:
            validate_geometry_fixture(case, documents)
            print(f"geometry/{case[0]}/{case[1]}: expected exit {case[3]}")
        print("All rev-6 reference bundles validate.")
        return 0
    except (OSError, ValueError, KeyError, TypeError, StopIteration) as exc:
        print(f"Example validation failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
