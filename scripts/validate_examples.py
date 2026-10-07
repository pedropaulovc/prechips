"""Validate exported/reference bundles; this is not a machining checker.

Run: uv run python scripts/validate_examples.py
Shared input definitions determine operation applicability and required joint debt;
finished-face coverage still uses only the original exported manifest.

Z pickups use stock_state.top_z for face = "top"; other named touch surfaces
must supply edge_mm in the zero recipe. Report values never define the edge.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
import sys
import tomllib
from fractions import Fraction
from html.parser import HTMLParser
from pathlib import Path
from types import SimpleNamespace

from prechips.findings import ALWAYS_REQUIRED
from prechips.joint_features import LABEL_PREFIX, feature_definitions, fit, label
from prechips.model import Plan, tolerance_requirements
from prechips.rules._bench import manual_bench
from prechips.rules.resolution import MANUAL, SAW_OPS, op_features, saw_setup

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

    return set(walk(plan))


def tool_diameter(ref: str, entries: dict):
    root, _, member = ref.partition("/")
    entry = entries.get(root, {})
    if entry.get("kind") == "endmill_set":
        match = re.fullmatch(r"(.+in)-(2|4)fl", member)
        size = fraction(match[1]) if match else None
        return float(size) * 25.4 if size is not None else "unknown"
    if entry.get("kind") == "drill_index":
        size = fraction(member)
        return (
            float(size) * 25.4
            if size is not None
            else entry.get("nominal_dia_mm", {}).get(member, "unknown")
        )
    return tool_field(ref, "dia", entries)


def tool_field(ref: str, key: str, entries: dict):
    root, _, member = ref.partition("/")
    entry = entries.get(root, {})
    if key == "flutes" and entry.get("kind") == "endmill_set":
        match = re.fullmatch(r"(.+in)-(2|4)fl", member)
        return int(match[2]) if match else "unknown"
    members = entry.get("members", {})
    selected = members.get(member, {}) if isinstance(members, dict) else {}
    if not isinstance(selected, dict):
        return "unknown"
    value = selected.get(key, entry.get(key, "unknown"))
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
    """Match checker readiness, including non-waivable joint and centre-support rules."""
    if finding["rule"] in ALWAYS_REQUIRED:
        return True
    required = policy.get("required", "unknown")
    if required == "unknown":
        return True
    selector = required.get(finding["rule"])
    subject = finding["subject"]
    if selector is None:
        return False
    if subject == "*" and finding["numbers"].get("required") == selector:
        return True
    if selector == "*":
        return True
    if isinstance(selector, list):
        return subject in selector
    if selector == "setups":
        return subject in {setup["id"] for setup in plan["setups"]}
    if selector in {"holes", "toleranced_features"}:
        feature = feature_definitions(plan, features).get(subject.split(":", 1)[0], {})
        if selector == "holes":
            return feature.get("kind") in {"hole", "counterbore", "thread"}
        return bool(tolerance_requirements(feature))
    return subject == selector or subject.startswith(selector + ":")


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
    definitions = feature_definitions(plan, features)

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
            or all(not str(face).startswith(LABEL_PREFIX) for face in feature["faces"]),
            f"{name}: transient joint labels cannot name finished STEP faces",
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
    definitions = feature_definitions(plan, features)
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


def check_joint_declarations(plan: dict, features: dict, findings: dict) -> None:
    """Keep assembly identities and unresolved joint geometry explicit in the report."""
    bundle = SimpleNamespace(plan=plan, features=features)
    for setup in plan["setups"]:
        if not isinstance(setup.get("stock_in"), list):
            continue
        sid = setup["id"]
        joint = setup["joint"]
        assembly = findings["joint_assembly", sid]
        if "kernel_status" in assembly["numbers"]:
            expected_status = (
                "error" if assembly["numbers"]["kernel_status"] == "error" else "unknown"
            )
            require(
                assembly["status"] == expected_status,
                f"{sid}: unavailable kernel cannot approve the assembly",
            )
        else:
            require(
                assembly["numbers"].get("joint") == joint["kind"]
                and assembly["numbers"].get("stock_in") == setup["stock_in"],
                f"{sid}: joint assembly identities differ from the plan",
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


def check_zero(setup: dict, finding: dict, entries: dict, dro: dict) -> None:
    numbers = finding["numbers"]
    mode = numbers.get("dro", numbers).get("radius_mode")
    require(mode == dro["radius_mode"], f"{setup['id']}: DRO radius/diameter mode mismatch")
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


def check_endpoints(plan: dict, features: dict, findings: dict, entries: dict) -> None:
    setups = {setup["id"]: setup for setup in plan["setups"]}
    definitions = feature_definitions(plan, features)
    for (rule, _), finding in findings.items():
        if rule != "blind_depth":
            continue
        for row in finding["numbers"].get("endpoints", []):
            setup = setups[row["setup"]]
            op = next(op for op in setup["ops"] if op["op"] == row["op"])
            require(op["feature"] == row["feature"], "endpoint mismatched feature")
            feature = definitions[op["feature"]]
            action = op["do"]
            entry = row.get("entry_z", "unknown")
            tool = op.get("tool", "unknown")
            if action in {"spot", "tap"}:
                fallback = feature.get("thread_depth", feature.get("depth", "unknown"))
                depth = op.get("depth_mm", fallback if action == "tap" else "unknown")
                depth = depth[1] if isinstance(depth, list) else depth
                near(row.get("depth_mm", "unknown"), depth, f"{action} cutting depth")
                require(row["exit_face"] == "not_applicable", f"{action} has no exit face")
                tip = entry - depth if numeric(entry) and numeric(depth) else "unknown"
                near(row["tip_z"], tip, f"{action} endpoint")
                if action == "tap":
                    near(
                        row.get("flute_len_mm", "unknown"),
                        tool_length_mm(tool, "flute_len", entries),
                        "tap flute length",
                    )
                continue
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
                    setup["stock_state"].get("local_thickness", {}).get(op["feature"], "unknown")
                )
                near(row.get("local_thickness", "unknown"), thickness, "endpoint local thickness")
                exit_face = (
                    entry - thickness if numeric(entry) and numeric(thickness) else "unknown"
                )
                near(row["exit_face"], exit_face, "local exit face")
                tip = (
                    exit_face - lead - allowance
                    if all(numeric(v) for v in (exit_face, lead, allowance)) and allowance >= 0
                    else "unknown"
                )
                near(row["tip_z"], tip, "through tip endpoint")
            else:
                depth = op.get("depth_mm", "unknown")
                limit = feature.get("depth", "unknown")
                limit = limit[1] if isinstance(limit, list) else limit
                near(row.get("depth_mm", "unknown"), depth, "blind cutting depth")
                near(row.get("depth_limit_mm", "unknown"), limit, "blind depth guard")
                total = depth + lead if numeric(depth) and numeric(lead) else "unknown"
                near(row.get("total_depth_mm", "unknown"), total, "blind total tip depth")
                require(row["exit_face"] == "not_applicable", "blind hole has no exit face")
                tip = entry - total if numeric(entry) and numeric(total) else "unknown"
                near(row["tip_z"], tip, "blind tip endpoint")


def check_saw_speed(setup: dict, op: dict, row: dict, entries: dict, cutting: dict) -> None:
    """A saw row is blade linear speed and descent feed from one cited row; no spindle maths."""
    tool_material = tool_field(op.get("tool", "unknown"), "material", entries)
    require(row.get("tool_material") == tool_material, f"{setup['id']}: saw blade material")
    rows = [
        c
        for c in cutting["cut"]
        if (c.get("material_class"), c.get("tool_material"), c.get("operation"))
        == (row.get("material_class"), tool_material, "saw_cut")
    ]
    require(row.get("matching_rows") == len(rows), f"{setup['id']}: saw row count")
    cited = len(rows) == 1 and rows[0].get("cite") not in (None, "", "unknown")
    sfm = rows[0].get("sfm", "unknown") if cited else "unknown"
    descent = rows[0].get("feed_mm_min", "unknown") if cited else "unknown"
    near(row.get("sfm", "unknown"), sfm, f"{setup['id']}:{op['op']}: saw row speed")
    band = entries.get(setup["machine"], {}).get("blade_speed_sfm", "unknown")
    bounded = isinstance(band, list) and len(band) == 2 and all(map(numeric, band))
    low, high = band if bounded and 0 < band[0] <= band[1] else ("unknown", "unknown")
    near(row.get("blade_speed_min_sfm", "unknown"), low, "saw blade speed minimum")
    near(row.get("blade_speed_max_sfm", "unknown"), high, "saw blade speed maximum")
    speed = max(low, min(high, sfm)) if numeric(sfm) and sfm > 0 and numeric(low) else "unknown"
    near(row.get("blade_speed_sfm", "unknown"), speed, f"{setup['id']}:{op['op']}: blade speed")
    feed = descent if numeric(descent) and descent > 0 else "unknown"
    near(row.get("feed_mm_min", "unknown"), feed, f"{setup['id']}:{op['op']}: descent feed")
    require("rpm" not in row, f"{setup['id']}:{op['op']}: a saw blade has no spindle RPM")


def check_speeds(
    setup: dict, op: dict, finding: dict, entries: dict, cutting: dict, definitions: dict
) -> None:
    row = finding["numbers"]
    if finding["status"] == "not_applicable":
        return
    if op["do"] in SAW_OPS:
        check_saw_speed(setup, op, row, entries, cutting)
        return
    if setup["machine"] == "PM-1127VF-LB":
        feature = definitions[op["feature"]]
        diameter = feature.get("dia_nominal", "unknown")
        if not numeric(diameter) and numeric(feature.get("base_radius")):
            diameter = 2 * feature["base_radius"]
        if op["do"] == "rough_turn":
            allowance = op["rough_allowance_mm"]  # lathe allowance is on diameter
            diameter = (
                diameter + allowance if numeric(diameter) and numeric(allowance) else "unknown"
            )
        # A turned face/end can cut several diameters. Its workpiece envelope
        # is cited in the report, not inferred from a single-point tool's size.
    else:
        # A member's own (measured) diameter outranks the size its name implies.
        tool = op.get("tool", "unknown")
        diameter = tool_length_mm(tool, "dia", entries)
        if not numeric(diameter):
            diameter = tool_diameter(tool, entries)
    if numeric(row.get("diameter_in")) and numeric(diameter):
        near(row["diameter_in"], diameter / 25.4, "cutting diameter")
    sfm = row.get("sfm", "unknown")
    if numeric(sfm):
        require(
            any(c["sfm"] == sfm and c["cite"] != "unknown" for c in cutting["cut"])
            or tool_field(op["tool"], "chart", entries) != "unknown",
            "numeric speed lacks source table/chart",
        )
        raw = 12 * sfm / (math.pi * row["diameter_in"])
        rpm = round(max(row["rpm_min"], min(row["rpm_max"], raw)) / 50) * 50
        near(row["rpm"], rpm, f"{setup['id']}:{op['op']}: RPM")
    else:
        require(row.get("rpm") == "unknown", "uncited cutting speed became RPM")
    if numeric(row.get("feed_mm_rev")):  # lathe rows feed per spindle revolution
        values = row.get("rpm"), row.get("feed_mm_rev")
        label = "feed per revolution"
    else:
        values = row.get("rpm"), row.get("flutes"), row.get("chip_load_mm_per_tooth")
        label = "feed per tooth"
    feed = math.prod(values) if all(numeric(v) for v in values) else "unknown"
    near(row.get("feed_mm_min", "unknown"), feed, label)


def check_coordinates(setup: dict, features: dict, finding: dict, plan: dict) -> None:
    frame = setup_frame(setup, plan, features)
    if setup["frame"] in plan.get("frames", {}):
        require(
            f"plan.frames.{setup['frame']}: author-declared setup frame" in finding["cite"],
            f"{setup['id']}: plan-owned frame provenance missing from coordinates",
        )
    definitions = feature_definitions(plan, features)
    for row in finding["numbers"].get("rows", []):
        require(row["feature"] in definitions, "unknown coordinate feature")
        feature = definitions[row["feature"]]
        parent = feature.get("hole", feature.get("parent"))
        if "at" not in feature and isinstance(parent, str):
            # A child (counterbore, chamfer) sits on its parent hole's centre.
            require(row.get("located_by") == parent, f"{row['feature']}: locator differs")
            feature = definitions.get(parent, {})
        else:
            require("located_by" not in row, f"{row['feature']}: undeclared locator")
        # A named station/apex on a turned part is not a feature centre.
        if "point" not in row:
            at = feature.get("at", ["unknown"] * 3)
            require(isinstance(at, list) and len(at) == 3, "coordinate has no feature centre")
            source = features["frames"][feature.get("frame", "model")]
            model = model_point(at, source)
            for actual, expected in zip(row["model"], model, strict=True):
                near(actual, expected, "model coordinate")
        transformed = frame_point(row["model"], frame)
        if "local_from" in row:
            source = row["local_from"]
            require(
                source["axis"] == "z" and source["field"] in {"to_z", "z_from", "z_to"},
                "local coordinate must name an authored Z endpoint",
            )
            require(
                (frame == "unknown" or frame.get("binding") == "unknown")
                and transformed[2] == "unknown",
                "local target cannot replace a known model transform",
            )
            op = next(op for op in setup["ops"] if op["op"] == source["op"])
            transformed[2] = op[source["field"]]
            require(numeric(transformed[2]), "local endpoint is not an authored number")
        for actual, expected in zip(row["setup"], transformed, strict=True):
            near(actual, expected, "setup coordinate")


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
    if tolerance == "unknown" or uncertain(declaration["fixture"], entries):
        require(finding["status"] == "unknown", "unverified angular setting must remain tentative")


def finished_exposed_diameter(setup: dict, features: dict, plan: dict | None = None):
    """Independent midpoint oracle for the fixtures' declared finished profile."""
    units = features.get("units")
    scale = 1 if units == "mm" else 25.4 if units == "in" else None
    state = setup.get("stock_state", {})
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


def kernel_filled_exposed_diameter(
    setup: dict, plan: dict, features: dict, row: dict, held, citations: list[str]
):
    """Cross-check an exposed profile whose features declare no z_mm stations.

    The kernel spans are not recomputed here. Everything the declared inputs fix is: the
    exposed span, gap-free coverage, declared feature diameters, stock width, and the minimum.
    A nominal-less dome must match the base derived independently from its declared radius
    and height; its kernel span must be cited. Other missing or contradictory nominals stay
    unresolved rather than trusting a diameter repeated by the report.
    """
    definitions = feature_definitions(plan, features)
    units = features.get("units")
    scale = 1 if units == "mm" else 25.4 if units == "in" else None
    state = setup.get("stock_state", {})
    length = setup.get("hold", {}).get("stickout_mm")
    ends = [state.get("north_end_z"), state.get("south_end_z")]
    segments = row.get("segments")
    if (
        any("z_mm" in feature for feature in definitions.values())
        or scale is None
        or not numeric(held)
        or not numeric(length)
        or length <= 0
        or not all(map(numeric, ends))
        or not isinstance(segments, list)
        or not segments
        or row.get("unresolved") != []
        or row.get("uncovered_z_mm") != []
    ):
        return "unknown"
    exposure = [max(ends) - length, max(ends)]
    claimed = row.get("exposed_z_mm")
    if not (
        isinstance(claimed, list)
        and len(claimed) == 2
        and all(math.isclose(a, b, abs_tol=1e-6) for a, b in zip(claimed, exposure, strict=True))
    ):
        return "unknown"
    reach, diameters = exposure[0], []
    for segment in sorted(segments, key=lambda item: item["z_mm"][0]):
        low, high = segment["z_mm"]
        diameter = segment["diameter_mm"]
        if not math.isclose(low, reach, abs_tol=1e-6) or high <= low or not numeric(diameter):
            return "unknown"
        reach = high
        names = segment["features"]
        if names:
            for name in names:
                definition = definitions.get(name)
                if not isinstance(definition, dict):
                    return "unknown"
                if definition.get("kind") not in {"cylinder", "boss", "shaft", "groove", "dome"}:
                    return "unknown"
                key = next(
                    (key for key in ("dia_nominal", "nominal_dia", "dia") if key in definition),
                    None,
                )
                if key is not None:
                    nominal = definition[key]
                    if not numeric(nominal) or not math.isclose(
                        nominal * scale, diameter, rel_tol=1e-10, abs_tol=1e-8
                    ):
                        return "unknown"
                    if definition.get("kind") != "dome":
                        continue
                if definition.get("kind") != "dome":
                    return "unknown"
                radius = definition.get("base_radius")
                if numeric(radius) and radius > 0:
                    expected_base = 2 * radius * scale
                else:
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
                    expected_base = 2 * math.sqrt(cap * (2 * radius - cap)) * scale
                base = segment.get("base_diameter_mm")
                reference = f"kernel: setups.{setup['id']}.revolved.{name} ("
                cited = any(
                    isinstance(citation, str) and citation.startswith(reference)
                    for citation in citations
                )
                if not (
                    numeric(base)
                    and math.isclose(base, diameter, rel_tol=1e-10, abs_tol=1e-8)
                    and math.isclose(expected_base, diameter, rel_tol=1e-10, abs_tol=1e-8)
                    and 0 < diameter <= held + 1e-6
                    and cited
                ):
                    return "unknown"
        elif segment.get("source") != "kernel_stock" or not 0 < diameter <= held + 1e-6:
            return "unknown"
        diameters.append(diameter)
    if not math.isclose(reach, exposure[1], abs_tol=1e-6):
        return "unknown"
    return min(diameters)


def check_stickout(setup: dict, plan: dict, features: dict, policy: dict, finding: dict) -> None:
    row = finding["numbers"]
    held = setup["stock_state"].get("od_mm", plan["stock"].get("dia_mm", "unknown"))
    if not numeric(held) or held <= 0:
        held = "unknown"
    diameter = finished_exposed_diameter(setup, features, plan)
    if diameter == "unknown":
        diameter = kernel_filled_exposed_diameter(setup, plan, features, row, held, finding["cite"])
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
    limit = (
        diameter * limit_ratio
        if numeric(diameter) and numeric(limit_ratio) and limit_ratio > 0 and cited and verified
        else "unknown"
    )
    near(row["unsupported_limit_mm"], limit, "stick-out unsupported limit")
    if (
        setup["machine"] == "PM-1127VF-LB"
        and limit == "unknown"
        and row["support_status"] != "pass"
    ):
        require(
            finding["status"] == "unknown",
            "unresolved exposed profile or shop ratio cannot approve stick-out",
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
    check_inspection_declarations(plan, features, findings)
    check_joint_declarations(plan, features, findings)
    missing = check_references(plan, entries, findings)
    check_endpoints(plan, features, findings, entries)
    definitions = feature_definitions(plan, features)
    for setup in plan["setups"]:
        # check_subjects already holds bench and saw zero waivers to their facts.
        if manual_bench(inventory, setup) is None:
            if not saw_setup(setup):
                check_zero(setup, findings["zero_check", setup["id"]], entries, plan["dro"])
            check_coordinates(setup, features, findings["coordinates", setup["id"]], plan)
        check_indexing(setup, features, entries, findings["indexing", setup["id"]])
        check_stickout(setup, plan, features, policy, findings["stickout", setup["id"]])
        for op in setup["ops"]:
            check_speeds(
                setup,
                op,
                findings["speeds_feeds", f"{setup['id']}:{op['op']}"],
                entries,
                cutting,
                definitions,
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
