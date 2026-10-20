"""Validate exported/reference bundles; this is not a machining checker.

Run: uv run python scripts/validate_examples.py
Shared input definitions determine operation applicability and required joint debt;
finished-face coverage uses authored inputs and the validator's own kernel facts.

Z pickups use stock_state.top_z for face = "top"; other named touch surfaces
must supply edge_mm in the zero recipe. Mounted saws additionally require a current,
stopped tool-holder body-side contact and independent native approach evidence.
Visible status disclosures may be compact decisions or legacy status boxes, never
hidden metadata alone. Report values never define the edge or the setting.
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
from itertools import product
from pathlib import Path
from types import SimpleNamespace

from prechips.findings import ALWAYS_REQUIRED
from prechips.inputs import BadInput, blank_supplies, load_bundle, operative_definitions
from prechips.joint_features import LABEL_PREFIX, fit, label, present, setup_span_mm
from prechips.kernel import run_geometry
from prechips.material_routes import (
    OUTPUT_PREFIX,
    MaterialGraph,
    feature_material_status,
    input_refs,
    producer_setup,
    setup_lineage,
)
from prechips.measurements import length_debt, length_fact, record_debt
from prechips.model import (
    TOLERANCE_REQUIREMENTS,
    UNIT_TOLERANCE,
    Inventory,
    Plan,
    tolerance_requirements,
)
from prechips.process_features import ACTIONS as PROCESS_ACTIONS
from prechips.process_features import ANGLE_TOLERANCE_DEG
from prechips.process_features import LABEL_PREFIX as PROCESS_PREFIX
from prechips.rules import RULES as CHECKER_RULES
from prechips.rules import tool_resolves as identity_rule
from prechips.rules._bench import BENCH_KINDS, hand_saw, manual_bench
from prechips.rules.coordinates import (
    CENTRE_OPS,
    DRO_DEFAULT_STEP,
    HEIGHT_BANDS,
    LOCATED_KINDS,
    UNIT_MM,
)
from prechips.rules.geometry_common import _AXIAL_LATHE_ACTIONS as AXIAL_LATHE_ACTIONS
from prechips.rules.geometry_common import _TURNING_ACTIONS as TURNING_ACTIONS
from prechips.rules.geometry_common import (
    TURNING_BLADE_KINDS,
    cutting_action,
    finite_saw_evidence,
    op_claims,
)
from prechips.rules.resolution import (
    HAND_FINISH,
    HAND_THREAD,
    LENGTH_TOLERANCE_MM,
    MANUAL,
    SAW_OPS,
    SLOT_CATEGORIES,
    TAP_OPS,
    UNRESOLVED_SAW_MODEL_REASON,
    make_op_unknowns,
    make_ops,
    make_tool,
    named_item,
    op_check_targets,
    op_entries,
    op_entry,
    op_features,
    operation_members,
    rough_leave,
    same_length,
    saw_setup,
    saw_station,
    shop_made_item,
    slitting_saw,
    spindle_saw,
)
from prechips.rules.resolution import resolve as resolve_item
from prechips.rules.resolution import select as select_item
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
from prechips.rules.zero_recipe import faces as zero_rules_faces
from prechips.rules.zero_recipe import rule as zero_rules_rule
from prechips.rules.zero_recipe import tool_setting as zero_rules_tool_setting
from prechips.rules.zero_recipe import touch as zero_rules_touch
from prechips.sheet import _REQUIREMENT_NAMES as SHEET_REQUIREMENTS
from prechips.sheet import _TOPICS as SHEET_TOPICS

# Each zero axis's DRO count direction, in the plan's words: counting up along setup +axis
# (jog polarity +1) or down (-1, a reversed DRO to stop on).
DRO_COUNTS = {
    "x": ({"right", "away_from_spindle_axis"}, {"left", "toward_spindle_axis"}),
    "y": ({"away"}, {"toward"}),
    "z": ({"up", "toward_exposed_end"}, {"down", "toward_chuck"}),
}
# Zero methods whose Axis Set is a bench reading: a trial-cut diameter or a measured edge.
MEASURED_ZERO = frozenset({"trial_cut_measure", "measure_then_set"})
ZERO_READINGS = ("axis_set", "check_reading", "mirrored_reading")
# The derived fields of a zero axis row, in the order they are checked, and their names.
ZERO_FIELDS = (
    ("sign", "jog polarity"),
    ("dro_direction", "DRO direction"),
    ("edge_mm", "touched edge"),
    ("radius_mm", "finder radius"),
    ("axis_set", "Axis Set"),
    ("check_reading", "check reading"),
    ("mirrored_reading", "mirrored reading"),
)

ROOT = Path(__file__).resolve().parents[1]
EXAMPLES = ROOT / "examples"
PARTS = ("pivot-shaft", "rocker-arm", "pivot-bracket")
EXPECTED_EXIT = {
    "pivot-shaft": 0,
    "rocker-arm": 0,
    "pivot-bracket": 0,
    "cone-pivot-post/built-up.toml": 4,
}
STANDALONE_CASES = (
    ("blondihacks-t-nuts", "plan.toml", "expected", 0),
    ("blondihacks-brass-ring", "plan.toml", "expected", 4),
    ("blondihacks-magic-tube", "plan.toml", "expected", 4),
)
# Worked fixtures exercise the measured branch without claiming shop observations.
EXAMPLE_MEASUREMENT = {
    "by": "example value (realistic, not a shop measurement)",
    "date": "2026-10-11",
    "instrument": "example fixture (no physical measurement)",
}
EXAMPLE_DEMO_FACT_COUNT = 818
REAL_PEDRO_FACTS = {
    ("fixtures", "vise-pm-6", "jaw_width_in"): (
        6.247,
        "large calipers or steel rule (as reported; exceeds 6 in caliper range)",
    ),
    ("fixtures", "vise-pm-6", "opening_in"): (6.135, "calipers"),
    ("fixtures", "vise-pm-6", "jaw_height_in"): (1.7695, "calipers"),
    ("fixtures", "vise-pm-6", "jaw_depth_in"): (0.7010, "calipers"),
    ("fixtures", "vise-pm-6", "bed_height_in"): (2.886, "calipers"),
    ("fixtures", "vise-pm-6-tall-soft-jaws", "bed_height_in"): (
        2.886,
        "calipers (vise-pm-6 reading, unchanged by the jaw plates)",
    ),
}
EXAMPLE_ASSUMED_LEADS = {
    ("tools", "reamers-decimal", "members", "0.4500in", "lead_mm"): (
        "cone-pivot-post/built-up.toml",
        "S8",
        30,
        "reamers-decimal/0.4500in",
        "crank_bore",
    ),
    ("tools", "reamers-decimal", "members", "0.4835in", "lead_mm"): (
        "cone-pivot-post/built-up.toml",
        "S9",
        30,
        "reamers-decimal/0.4835in",
        "journal_bore",
    ),
}
# (bundle, plan, expected dir, exit, discriminating rule, modeled setups, setups the rule
# errors on). Setups outside the modeled set must render as partial pictures with debts.
GEOMETRY_CASES = (
    ("rocker-jaw-occluded", "plan.toml", "expected", 2, "accessibility", ("S3",), ("S3",)),
    ("pocket-reach", "plan.toml", "expected", 2, "reach", ("S2",), ("S2",)),
    ("pocket-reach", "long-reach.toml", "expected/long-reach", 0, None, ("S2",), ()),
    ("sharp-corner", "plan.toml", "expected", 2, "internal_corner_radius", ("S2",), ("S2",)),
    ("unclaimed-face", "plan.toml", "expected", 2, "coverage", ("S2",), ("S2",)),
    ("profiled-blank", "plan.toml", "expected", 2, "coverage", (), ()),
    ("profiled-blank", "machined-ends.toml", "expected/machined-ends", 0, None, (), ()),
    # The hand-fed saw setup's required rows pass; the arm it does not make keeps errors.
    ("hand-fed-saw", "plan.toml", "expected", 2, None, (), ()),
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
# Rules evaluating every op of every setup.
OP_RULES = {
    "speeds_feeds",
    "turning_deflection",
    "engagement",
    "accessibility",
    "reach",
    "internal_corner_radius",
}
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
REFERENCE_KEYS = {
    "machine",
    "tool",
    "holder",
    "gauge",
    "fixture",
    "parallels",
    "support",
    "supports",
    "clamps",
    "riser",
    "support_blocks",
    "chuck",
    "ref",
}
# A hold's ``clamp`` names an inventory identity when it is one hyphenated word.
CLAMP_IDENTITY = re.compile(r"\w+(?:-\w+)+")
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
# kinds they place it for (a centre hole uses its real spot/centre-drilling action).
ENDPOINT_OPS = frozenset({"spot", "drill", "ream", "counterbore", "bore"}) | TAP_OPS
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


class Entries:
    """The inventory as the checker reads it: the validator's one reader of an item by its
    key. The item a reference names in a ``slot`` (a category, or a slot kind such as
    ``workholding`` or ``spindle``) is the one resolution.select reads there, as the rules
    use it (resolution.resolve); it is unverified as resolution.uncertain reads it."""

    def __init__(self, inventory: dict):
        self.inventory = inventory

    def item(self, ref, slot):
        """The record ``slot`` selects for ``ref`` (a member's merged over its set's; an
        item stated unknown ``{"kind": "unknown", "verify": True}``), None when it selects
        none."""
        return resolve_item(self.inventory, slot, ref) if isinstance(ref, str) else None

    def record(self, ref, slot) -> dict:
        """:meth:`item`, or {} when ``slot`` selects none."""
        return self.item(ref, slot) or {}

    def resolves(self, ref, slot) -> bool:
        return self.item(ref, slot) is not None

    def uncertain(self, ref, slot) -> bool:
        return record_uncertain(self.item(ref, slot))

    def verified(self, ref, slot) -> bool:
        """Whether ``ref`` resolves in ``slot`` to an item the checker does not read as
        unverified: a flagged, unverified or explicitly unknown one is not ready."""
        return self.resolves(ref, slot) and not self.uncertain(ref, slot)

    def identities(self, ref) -> set:
        """The ``(category, key)`` items ``ref`` names, as resolution.select selects it in
        each slot kind and category: a reference naming its category (``tools.drill``) is
        that one item; a bare key is the item each slot reads, so one key two categories
        list is two."""
        slots = [*SLOT_CATEGORIES, *(c for order in SLOT_CATEGORIES.values() for c in order)]
        return {select_item(self.inventory, ref, slot)[:2] for slot in slots}


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
                if key in REFERENCE_KEYS - {"ref"} and isinstance(child, (str, list)):
                    for name in [child] if isinstance(child, str) else child:
                        if isinstance(name, str) and name not in {
                            "unknown",
                            "not_applicable",
                            "none",
                        }:
                            yield name
                    yield from walk(child)
                elif key == "clamp" and isinstance(child, str) and CLAMP_IDENTITY.fullmatch(child):
                    yield child
                elif key in {"checks", "missing_requirements"} and isinstance(child, dict):
                    # A multi-feature op's checks may scope a gauge table to one feature.
                    gauges = (v.values() if isinstance(v, dict) else [v] for v in child.values())
                    yield from (g for scope in gauges for g in scope if g != "unknown")
                elif key not in {"ref", "item"}:
                    yield from walk(child)
        elif isinstance(value, list):
            for child in value:
                yield from walk(child)

    stock = plan.get("stock")
    if isinstance(stock, dict):
        plan = {**plan, "stock": {k: v for k, v in stock.items() if k != "prepared"}}
    return set(walk(plan))


def tool_record(ref, key: str, entries: Entries, slot: str = "tools"):
    """The authored ``key`` of the item ``slot`` selects for ``ref`` (:class:`Entries`: a
    member's over its set's, a set member's generated size), unwrapped from neither
    ``{value, ...}`` nor its units."""
    return entries.record(ref, slot).get(key, "unknown")


def tool_field(ref, key: str, entries: Entries, slot: str = "tools"):
    fact = tool_record(ref, key, entries, slot)
    if not accepted(fact):
        return "unknown"
    return fact.get("value", "unknown") if isinstance(fact, dict) else fact


def tool_length_mm(ref, field: str, entries: Entries, slot: str = "tools"):
    record = entries.record(ref, slot)
    units = tool_field(ref, "units", entries, slot)
    names = [key for key in (f"{field}_mm", f"{field}_in") if key in record]
    if field in record and units in {"mm", "in", "inch"}:
        names.append(field)
    if len(names) != 1:
        return "unknown"
    key = names[0]
    value = tool_field(ref, key, entries, slot)
    if key.endswith("_mm") or key == field and units == "mm":
        return value if numeric(value) else "unknown"
    inches = fraction(str(value))
    return float(inches) * 25.4 if inches is not None else "unknown"


def accepted(fact) -> bool:
    """Bare nominal facts retain their contract; a declared measurement is trusted only
    with explicit measured status and complete fact-local metadata, never by its prose."""
    if not isinstance(fact, dict):
        return True
    if fact.get("verify") is True or fact.get("verify") == "unknown":
        return False
    measured = fact.get("measured", "unknown")
    if measured == "unknown":
        return True
    if not isinstance(measured, dict) or set(measured) != {"status", "by", "date", "instrument"}:
        return False
    if measured["status"] != "measured" or not all(
        isinstance(measured[key], str)
        and measured[key].strip()
        and measured[key].strip() != "unknown"
        for key in ("by", "date", "instrument")
    ):
        return False
    try:
        return date.fromisoformat(measured["date"]).isoformat() == measured["date"]
    except ValueError:
        return False


def inventory_provenance_fields(source: str):
    """Comment/note-labelled facts, classified by schema-specific qualification.

    Yield ``(path, line, item, value, kind)``: ``measured`` requires a fact-local
    measured record, ``cited`` permits a fact-local citation or measured record, and
    ``plain`` requires exact source disclosure on a bare capability.
    TOML supplies the values and quoted identities; source lines supply only adjacent
    comments. Plain capability collections retain bare-nominal handling and exact source
    disclosure, not fictitious length records or automatic item-verification demotions.
    A catalogue nominal without a local provenance marker stays nominal.
    """
    document = tomllib.loads(source)
    schema = Inventory.model_json_schema()
    definitions = schema["$defs"]
    marker = re.compile(r"\b(?:example|illustrative)\b|\bmeasured\s*=", re.IGNORECASE)
    tokens = re.compile(r"""("(?:\\.|[^"\\])*"|'[^']*')|(?P<comment>\#.*)""")
    plain_capabilities = {"range_mm", "range_in", "ra_range", "sizes_mm", "blade_speed_sfm"}

    def branches(node):
        if "$ref" in node:
            yield from branches(definitions[node["$ref"].rsplit("/", 1)[1]])
        elif "anyOf" in node:
            for child in node["anyOf"]:
                yield from branches(child)
        else:
            yield node

    def field_schema(path):
        nodes = [schema]
        for key in path:
            children = []
            for node in nodes:
                for branch in branches(node):
                    child = branch.get("properties", {}).get(key)
                    if child is None:
                        child = branch.get("additionalProperties")
                    if isinstance(child, dict):
                        children.append(child)
            nodes = children
        return nodes

    def keys(authored):
        value = tomllib.loads(f"{authored} = 0")
        path = []
        while isinstance(value, dict):
            ((key, value),) = value.items()
            path.append(key)
        return tuple(path)

    table_path, comments = (), []
    for line_number, line in enumerate(source.splitlines(), 1):
        comment = next((match for match in tokens.finditer(line) if match["comment"]), None)
        code = line[: comment.start()] if comment else line
        if not code.strip():
            if comment:
                comments.append(comment["comment"])
            else:
                comments.clear()
            continue
        code = code.strip()
        if code.startswith("["):
            # Array tables (shop stock) use plain Stock fields, not InventoryItem facts.
            table_path = () if code.startswith("[[") else keys(code[1:-1])
            comments.clear()
            continue
        if not table_path or "=" not in code or code.startswith("{"):
            comments.clear()
            continue
        authored_key = code.partition("=")[0].strip()
        key_token = r"""(?:[\w-]+|"(?:\\.|[^"\\])*"|'[^']*')"""
        if re.fullmatch(rf"{key_token}(?:\s*\.\s*{key_token})*", authored_key) is None:
            comments.clear()
            continue
        path = table_path + keys(authored_key)
        item = document
        notes = []
        for key in table_path:
            item = item[key]
            if isinstance(item, dict):
                notes.append(item.get("note", ""))
        value = item
        for key in path[len(table_path) :]:
            value = value[key]
        prose = [*comments, comment["comment"] if comment else "", *notes]
        comments.clear()
        if not any(isinstance(text, str) and marker.search(text) for text in prose):
            continue
        nodes = field_schema(path)
        record_properties = [
            branch["properties"]
            for node in nodes
            for branch in branches(node)
            if {"value", "measured"} <= branch.get("properties", {}).keys()
        ]
        fact_value = value.get("value", "unknown") if isinstance(value, dict) else value
        physical = (
            numeric(fact_value)
            or (isinstance(fact_value, str) and fraction(fact_value) is not None)
            or (isinstance(fact_value, list) and bool(fact_value) and all(map(numeric, fact_value)))
        )
        if physical and (record_properties or path[-1] in plain_capabilities and nodes):
            kind = "measured" if record_properties else "plain"
            if any("cite" in properties for properties in record_properties):
                kind = "cited"
            yield path, line_number, item, value, kind


def check_inventory_provenance(source: str, where: str = "inventory") -> dict:
    """Require each marked fact's schema-supported, fact-local qualification.

    Measurement-only records require ``measured``; citation-capable records allow their
    own usable ``cite`` only when ``measured`` is absent. Plain capabilities retain
    exact adjacent disclosure.
    """
    found = {"record_fields": set(), "plain_fields": set()}
    lines = source.splitlines()
    for path, line, _item, value, kind in inventory_provenance_fields(source):
        label = ".".join(path)
        location = f"{where}:{line}: {label}"
        if kind == "measured":
            require(
                isinstance(value, dict) and isinstance(value.get("measured"), dict),
                f"{location}: provenance comment/note requires a fact-local measured record",
            )
            found["record_fields"].add(path)
        elif kind == "cited":
            require(
                isinstance(value, dict)
                and (
                    isinstance(value.get("measured"), dict)
                    or ("measured" not in value and bool(citations(value.get("cite"))))
                ),
                f"{location}: provenance comment/note requires a fact-local citation "
                "or measured record",
            )
            found["record_fields"].add(path)
        else:
            comments = [lines[line - 1].partition("#")[2]]
            previous = line - 2
            while previous >= 0 and lines[previous].lstrip().startswith("#"):
                comments.append(lines[previous])
                previous -= 1
            require(
                not isinstance(value, dict)
                and any(EXAMPLE_MEASUREMENT["by"] in comment for comment in comments),
                f"{location}: example bare nominal requires the exact source disclosure marker",
            )
            found["plain_fields"].add(path)
    return found


def example_measurement_records(node, path=()):
    """Every authored measured record, including fixture solids and member facts."""
    if isinstance(node, dict):
        for key, value in node.items():
            if key == "measured" and isinstance(value, dict):
                yield path, node
            else:
                yield from example_measurement_records(value, path + (key,))
    elif isinstance(node, list):
        for index, value in enumerate(node):
            yield from example_measurement_records(value, path + (str(index),))


def check_example_measurements(inventory: dict, plans: dict) -> dict:
    """Strict demo markers, unchanged real observations and two actually selected leads.

    This is authoring policy for the shared worked inventory, not a production trust
    exception: ASSUMED still fails ``accepted`` and no plain field gains a wrapper."""
    real, demo, assumed = set(), set(), set()
    for path, fact in example_measurement_records(inventory):
        label = ".".join(path)
        measurement = fact["measured"]
        if path in REAL_PEDRO_FACTS:
            value, instrument = REAL_PEDRO_FACTS[path]
            require(
                fact.get("value") == value
                and measurement
                == {
                    "status": "measured",
                    "by": "Pedro Paulo Vezza Campos",
                    "date": "2026-10-05",
                    "instrument": instrument,
                },
                f"{label}: actual Pedro measurement changed",
            )
            real.add(path)
            continue
        status = "assumed" if path in EXAMPLE_ASSUMED_LEADS else "measured"
        require(
            measurement == {"status": status, **EXAMPLE_MEASUREMENT},
            f"{label}: demonstration fixture requires exact {status} marker metadata",
        )
        demo.add(path)
        if path in EXAMPLE_ASSUMED_LEADS:
            require(fact.get("value") == 1.0, f"{label}: deliberately assumed lead value changed")
            assumed.add(path)
    require(real == REAL_PEDRO_FACTS.keys(), "shared inventory lost an actual Pedro record")
    require(assumed == EXAMPLE_ASSUMED_LEADS.keys(), "shared inventory lost an assumed lead")
    anchors = {
        ("machines", "PM-30MV", "resolution_mm"),
        ("machines", "PM-1127VF-LB", "resolution_mm"),
        ("tools", "endmills-lms-6784", "members", "3-8in-4fl", "dia_mm"),
        ("gauges", "radius-gauge", "resolution_mm"),
    }
    require(anchors <= demo, "shared inventory demonstration scan lost its fact anchors")
    require(
        len(demo) == EXAMPLE_DEMO_FACT_COUNT,
        "shared inventory demonstration measurement count changed",
    )
    consumers = {}
    for path, (filename, sid, number, reference, feature) in EXAMPLE_ASSUMED_LEADS.items():
        require(filename in plans, f"{filename}: assumed lead's consuming plan missing")
        selected = {
            (plan_name, setup["id"], op["op"], op.get("do"), op.get("feature"))
            for plan_name, plan in plans.items()
            for setup in plan["setups"]
            for op in setup["ops"]
            if op.get("tool") == reference
        }
        require(
            selected == {(filename, sid, number, "ream", feature)},
            f"{'.'.join(path)}: assumed lead must be selected only by {sid}:{number} {feature}",
        )
        consumers[path] = (filename, sid, number, "blind_depth", feature)
    return {"real": real, "demo": demo, "assumed": assumed, "consumers": consumers}


def centre_tool_facts(ref: str, entries: Entries) -> dict:
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
    exported = table_of(features.get("frames"))
    shadowed = sorted(set(planned) & set(exported))
    require(not shadowed, f"plan frames shadow exported frames {shadowed}")
    return planned


def setup_frame(setup: dict, plan: dict, features: dict):
    """Independent lookup: the exported manifest frame, else the plan-owned frame."""
    exported = table_of(features.get("frames"))
    name = setup.get("frame", "unknown")
    if name in exported:
        return exported[name]
    return plan_frames(plan, features).get(name, "unknown")


def check_frames(features: dict, plan: dict) -> None:
    planned = plan_frames(plan, features)
    for name, frame in planned.items():
        require(frame.get("binding") is not None, f"plan frame {name}: binding must be stated")
        citations = frame.get("cite", [])
        if isinstance(citations, str):
            citations = [citations]
        require(
            any(
                isinstance(citation, str)
                and re.search(r"\bAUTHOR'S CHOICE\b", citation) is not None
                for citation in citations
            ),
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
    require(report.get("rules_version") == "m5-rev12", f"{path}: stale rule catalogue")
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
    for kind, blank in blank_supplies(plan).items():
        if blank.get("step", "unknown") != "unknown":
            paths[kind] = (folder / blank["step"]).resolve()
            digest = blank.get("step_sha256", "unknown")
            require(
                digest in {"unknown", sha256(paths[kind])},
                f"{folder.name}: {kind} STEP bytes differ from their step_sha256",
            )
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


def arc_feature(feature: dict) -> bool:
    """Whether ``feature`` is an arc a manual layout scribes and files to (a boss or
    cylinder, a bottom radius, or a radius with an end or an upper semicircle)."""
    return (
        feature.get("kind") in {"boss", "cylinder"}
        or "bottom_radius" in feature
        or ("radius" in feature and ("end" in feature or feature.get("arc") == "upper_semicircle"))
    )


def inspection_domains(plan: dict, definitions: dict, features: dict | None = None) -> dict:
    """Authored inspection identities and routes, including physical and shared owners.

    Presentation families never select a member. Explicit shared checks suppress only
    the member/feature/requirement tuples they cover; manual part relationships remain
    separate for every registered member, including a missing final inspection.
    """
    own = SimpleNamespace(
        plan=plan,
        features=features or {"features": definitions},
        feature_definitions=definitions,
    )
    ops = [(setup, op) for setup in plan["setups"] for op in setup["ops"]]
    selected = [
        (setup, op, target) for setup, op in ops for target in op_check_targets(own, setup, op)
    ]
    domains = {
        f"{setup['id']}:{op['op']}": (None, None, [(setup, op)])
        for setup, op in ops
        if "process_holds" in op
    }
    shared = set()
    for setup, op, target in selected:
        if target["kind"] == "dimensional" and target["shared_check_id"] is not None:
            name, requirement = (
                target["identity"]["feature_owner"],
                target["identity"]["requirement"],
            )
            domains[target["subject"]] = (name, requirement, [(setup, op)])
            shared.update((member, name, requirement) for member in target["covered_workpieces"])
    registered = plan.get("workpieces")
    members = tuple(registered) if isinstance(registered, dict) and registered else (None,)
    graph = MaterialGraph(plan) if "workpieces" in plan else None
    for member in members:
        prefix = f"{member}/" if member is not None else ""
        for name, feature in definitions.items():
            route = [
                (setup, op)
                for setup, op in ops
                if name in op_features(op)
                and (
                    member is None
                    or member in (operation_members(own, setup, op) or ())
                    or any(
                        target["identity"]["workpiece"] == member
                        or target["selection_status"] == "unknown"
                        and member in ((graph.members(setup["id"]) if graph else ()) or ())
                        for candidate_setup, candidate_op, target in selected
                        if candidate_setup is setup and candidate_op is op
                    )
                )
            ]
            missing = {
                requirement
                for _, op in route
                for requirement in table_of(op.get("missing_requirements"))
            }
            for requirement in missing:
                domains[f"{prefix}{name}:{requirement}"] = (name, requirement, route)
            requirements = tolerance_requirements(feature)
            for requirement in requirements:
                if (member, name, requirement) not in shared:
                    domains[f"{prefix}{name}:{requirement}"] = (name, requirement, route)
            unknown = feature.get("kind") == "unknown" or any(
                op.get("do") == "unknown" for _, op in route
            )
            if not requirements and (unknown or not missing):
                domains[prefix + name] = (name, None, route)
        for requirement in table_of(own.features.get("acceptance")):
            domains[f"{prefix}part:{requirement}"] = (None, requirement, ops)
    return domains


def inspection_subjects(plan: dict, definitions: dict, features: dict | None = None) -> set:
    return set(inspection_domains(plan, definitions, features))


def rule_subjects(plan: dict, features: dict, entries: Entries, checked) -> dict:
    """``{rule: subjects}`` each supported rule evaluates for this plan, from the plan and
    the manifest alone: the setup, op, feature and part subjects of the checker's rule
    catalogue, the bundle binding's ``inputs``, the prepared blank's ``stock.prepared``,
    each joined setup (a cylindrical one's fit too), each saw cut, each scribed or filed
    arc, every inventory item the plan selects or names (:func:`identity_rows`), each make
    operation of a shop-made item a setup holds with (:func:`make_op_rows`) and each
    non-manual op, and the inspection subjects (:func:`inspection_subjects`). Any other
    rule of the checker's catalogue (``prechips.rules.RULES``) is its own rows on the
    validator's own bundle load and kernel run (``checked``, :func:`checker_findings`):
    ``{subject: row}``, so a rule the checker adds needs no validator edit; a rule outside
    the catalogue evaluates nothing."""
    definitions = operative_definitions(plan, features)
    ops = [(setup, op) for setup in plan["setups"] for op in setup["ops"]]
    setups = {setup["id"] for setup in plan["setups"]}

    def op_ids(keep):
        return {f"{setup['id']}:{op['op']}" for setup, op in ops if keep(op)}

    joined = [setup for setup in plan["setups"] if isinstance(setup.get("stock_in"), list)]
    subjects = {rule: setups for rule in SETUP_RULES | SETUP_GEOMETRY_RULES | {"centre_support"}}
    subjects.update(dict.fromkeys(OP_RULES, op_ids(lambda op: True)))
    subjects.update(dict.fromkeys(FEATURE_RULES - {"datum_consistency"}, set(definitions)))
    manifest = set(features["features"])
    subjects.update(dict.fromkeys(("datum_consistency", "finish_coverage"), manifest))
    subjects.update(dict.fromkeys(("construction", "coverage", "finish_route"), {plan["part"]}))
    subjects.update(
        bundle_binding={"inputs"},
        prepared_blank={"stock.prepared"},
        joint_assembly={setup["id"] for setup in joined},
        joint_fit={setup["id"] for setup in joined if setup["joint"]["kind"] == "cylindrical"},
        joint_thread={setup["id"] for setup in joined if setup["joint"]["kind"] == "threaded"},
        saw_cut=op_ids(lambda op: op.get("do") in SAW_OPS),
        manual_arc=op_ids(
            lambda op: (
                op.get("do") in {"scribe", "file_to_line"}
                and isinstance(op.get("feature"), str)
                and arc_feature(definitions.get(op["feature"], {}))
            )
        ),
        # Coating resolves its process; stopped-spindle threads select real hand tools.
        tool_resolves=set(identity_rows(plan, features, entries))
        | set(make_op_rows(plan, features, entries))
        | op_ids(
            lambda op: (
                op.get("do") == "coating"
                or op.get("do") in HAND_THREAD
                or op.get("do") not in MANUAL
            )
        ),
        inspection=inspection_subjects(plan, definitions, features),
    )
    for rule in CHECKER_RULES:
        if rule.name not in subjects:
            subjects[rule.name] = checked(rule)
    return subjects


def checker_findings(plan_path: Path):
    """``checked(rule)``: ``{subject: row}``, the findings the checker's own ``rule``
    (``prechips.rules.RULES``) gives on this validator's own bundle load and kernel run of
    the plan at ``plan_path`` (geometry first, as the CLI runs it), made once per rule. No
    report value enters it."""

    @functools.cache
    def bundle():
        loaded = load_bundle(plan_path)
        run_geometry(loaded)
        return loaded

    def rows(rule) -> dict:
        return {f.subject: json.loads(json.dumps(f.to_dict())) for f in rule.evaluate(bundle())}

    return functools.cache(rows)


def required_subjects(policy: dict, plan: dict, features: dict, rules: dict) -> dict:
    """``{rule: (selector, subjects)}``: what the policy's ``required`` selection must
    cover, as the checker derives it (``rules.required_coverage``) from the plan, the
    manifest and the rules' own subjects (``rules``: rule to the set of subjects it
    evaluates): a list names its subjects, ``setups`` every setup,
    ``holes``/``toleranced_features`` the operative features of that kind, ``"*"`` (or a
    selection matching nothing) at least one subject, else the selector itself. An unknown
    policy requires its ``required_policy`` row."""
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
        result[name] = selector, subjects
    return result


def check_required_coverage(
    policy: dict, plan: dict, features: dict, findings: dict, entries: Entries, checked
) -> None:
    """The report's subjects are exactly those its supported rules evaluate
    (:func:`rule_subjects`, from the validator's own inputs) plus the checker's coverage
    row for each required subject none of them covers (:func:`required_subjects`). Each
    coverage row stays unknown with the policy's selector: no supported check exists to
    approve or waive it, and no report row can stand in for one. A rule only the checker's
    catalogue lists is its own rows on the validator's inputs (:func:`checker_findings`):
    each report row is that row, verdict and evidence, never approved, waived or moved. A
    make operation's row is admitted only with its own evidence and verdict
    (:func:`check_make_ops`), on every bundle this boundary checks."""
    domains = rule_subjects(plan, features, entries, checked)
    coverage = {
        (rule, subject): selector
        for rule, (selector, subjects) in required_subjects(policy, plan, features, domains).items()
        for subject in subjects
        if not any(
            value == subject or value.startswith(subject + ":") for value in domains.get(rule, ())
        )
    }
    evaluated = {(rule, subject) for rule, subjects in domains.items() for subject in subjects}
    absent = sorted((evaluated | coverage.keys()) - findings.keys())
    require(not absent, f"missing findings {absent}: evaluated or required subjects")
    check_make_ops(plan, features, entries, findings)
    # Thread subjects are independently authored above, while their full normalized
    # evidence still comes from this validator's own source-bound checker bundle.
    threaded = domains.get("joint_thread", set())
    if threaded:
        rule = next(rule for rule in CHECKER_RULES if rule.name == "joint_thread")
        own = checked(rule)
        for subject in threaded:
            require(
                subject in own and findings["joint_thread", subject] == own[subject],
                f"joint_thread:{subject}: not the checker's own row on the validator's inputs",
            )
    for rule, own in domains.items():
        for subject, row in own.items() if isinstance(own, dict) else ():
            if rule == "consistency":
                setup = next((s for s in plan["setups"] if s["id"] == subject), None)
                if (
                    setup is not None
                    and "kernel setup picture: closest_cut and per-op cut_clearances" in row["cite"]
                    and not dro_grid_trusted(setup, features, entries, plan)
                ):
                    require(
                        findings[rule, subject]["status"] in {"unknown", "error"},
                        f"consistency:{subject}: an unverified picture grid cannot pass",
                    )
            require(
                findings[rule, subject] == row,
                f"{rule}:{subject}: not the checker's own row on the validator's inputs",
            )
    for key, finding in findings.items():
        if key in evaluated:
            continue
        require(
            key in coverage,
            f"{key[0]}:{key[1]}: no supported check evaluates it and no required subject "
            "calls for its coverage row",
        )
        require(
            finding["status"] == "unknown" and finding["numbers"] == {"required": coverage[key]},
            f"{key[0]}:{key[1]}: a required subject no supported check covers stays unknown",
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

    # Missing-requirement declarations replace a known empty feature's bare N/A row,
    # but unknown requirement identities/applicability still need their own subjects.
    inspection = inspection_domains(plan, definitions, features)
    for subject in inspection:
        has("inspection", subject)

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
        numeric_requirements = [
            field
            for field in requirements
            if numeric(feature.get(field))
            or (
                isinstance(feature.get(field), list)
                and bool(feature[field])
                and all(map(numeric, feature[field]))
            )
        ]
        if numeric_requirements:
            require(isinstance(feature.get("precision"), dict), f"{name}: per-dimension precision")
        has("datum_consistency", name)
    for name in definitions:
        for rule in FEATURE_RULES - {"datum_consistency"}:
            has(rule, name)
    for subject, (name, requirement, route) in inspection.items():
        if name is None or requirement is None:
            continue
        if requirement == "unknown":
            require(
                findings["inspection", subject]["status"] == "unknown",
                f"{subject}: unresolved requirement must remain unknown",
            )
        elif requirement in tolerance_requirements(definitions[name]):
            finishing = [
                op for _, op in route if op_entry(op, "checks", name, requirement) is not None
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
        bench = manual_bench(inventory, setup)
        threaded_manual = manual_thread_facts(inventory, setup) if bench is None else None
        if bench is None:
            frame = setup.get("frame", "unknown")
            require(
                frame == "unknown"
                or frame in features["frames"]
                or frame in plan_frames(plan, features),
                f"{sid}: missing frame",
            )
            state = setup.get("stock_state", "unknown")
            require(
                state == "unknown" or isinstance(state, dict),
                f"{sid}: stock state must be declared or remain unknown",
            )
        require(setup.get("ops"), f"{sid}: empty operations")
        require(isinstance(setup.get("hold"), dict), f"{sid}: missing hold")
        if saw_setup(inventory, setup):
            # A dedicated saw setup locates its cut by cut_plane; no spindle zero is set.
            has("zero_check", sid)
            require(
                findings["zero_check", sid]["status"] == "not_applicable"
                and findings["zero_check", sid]["numbers"]
                == {"frame": setup.get("frame", "unknown")},
                f"{sid}: saw setup zero waiver must name its frame",
            )
        elif threaded_manual is not None:
            # Stopped-spindle thread work waives only these two electronic screens.
            for rule in ("zero_check", "coordinates"):
                has(rule, sid)
                require(
                    findings[rule, sid]["status"] == "not_applicable"
                    and findings[rule, sid]["numbers"] == threaded_manual,
                    f"{sid}: {rule} must name the all-manual thread facts that waive it",
                )
        elif bench is None:
            if any(spindle_saw(inventory, setup, op) for op in setup["ops"]):
                check_spindle_zero(setup, findings["zero_check", sid], inventory)
            for rule in ("zero_check", "coordinates"):
                has(rule, sid)
                require(
                    findings[rule, sid]["status"] != "not_applicable",
                    f"{sid}: {rule} cannot waive unknown or mixed machine work",
                )
            if table_of(plan.get("dro")).get("kind", "digital") == "digital":
                require(isinstance(setup.get("zero"), dict), f"{sid}: missing zero")
                lathe = machine_kind(setup, Entries(inventory)) == "lathe"
                axes = ("x", "z") if lathe else ("x", "y", "z")
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
            action = op["do"]
            if action in HAND_THREAD:
                require("tool" in op, f"{sid}:{op['op']}: omitted manual thread tool")
                require("holder" in op, f"{sid}:{op['op']}: omitted manual thread holder")
            elif action not in MANUAL:
                if "tool" in op and (action not in SAW_OPS or spindle_saw(inventory, setup, op)):
                    require("holder" in op, f"{sid}:{op['op']}: omitted holder")
            if action in HAND_THREAD or action == "coating" or action not in MANUAL:
                has("tool_resolves", f"{sid}:{op['op']}")
        if isinstance(setup.get("stock_in"), list):
            has("joint_assembly", sid)
            if setup["joint"]["kind"] == "cylindrical":
                has("joint_fit", sid)
            elif setup["joint"]["kind"] == "threaded":
                has("joint_thread", sid)


def check_inspection_declarations(plan: dict, features: dict, findings: dict) -> None:
    definitions = operative_definitions(plan, features)
    for setup in plan["setups"]:
        for op in setup["ops"]:
            if op.get("do") in SAW_OPS and "feature" not in op:
                continue  # a stock cut-off names no feature and exports no requirement
            # A multi-feature inspect op checks a requirement any named feature exports.
            names = op_features(op)
            owned = {}
            for name in names:
                requirements = definitions[name].get("requirements", "unknown")
                owned[name] = set(requirements) if isinstance(requirements, list) else set()
            exported = set().union(*owned.values())
            label = "/".join(names)
            # A feature-scoped check is one its own feature exports.
            for scope, requirement, _ in op_entries(op, "checks"):
                require(
                    requirement
                    in (
                        exported | set(table_of(features.get("acceptance")))
                        if scope is None
                        else owned[scope]
                    ),
                    f"{setup['id']}:{op['op']}: {scope or label} has no requirement {requirement}",
                )
            for requirement in op.get("missing_requirements", {}):
                require(
                    requirement not in exported,
                    f"{setup['id']}:{op['op']}: {label}.{requirement} is an exported requirement",
                )
                for subject, (name, owned_requirement, route) in inspection_domains(
                    plan, definitions, features
                ).items():
                    if (
                        name not in names
                        or owned_requirement != requirement
                        or not any(
                            candidate_setup is setup and candidate_op is op
                            for candidate_setup, candidate_op in route
                        )
                    ):
                        continue
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


def measured_output(plan: dict, facts: dict, ref: str) -> dict:
    """Only a native-proven retained partition, never its host identity descriptor."""
    if facts.get("status") != "ok":
        return {}
    producer = producer_setup(plan, ref)
    detail = table_of(table_of(facts.get("setups")).get(producer))
    output = table_of(table_of(detail.get("outputs")).get(ref.removeprefix(OUTPUT_PREFIX)))
    box, volume = output.get("bbox_mm"), output.get("volume_mm3")
    if (
        output.get("reason")
        or not isinstance(box, list)
        or len(box) != 6
        or not all(map(finite, box))
        or any(box[i] > box[i + 3] for i in range(3))
        or not finite(volume)
        or volume <= 0
    ):
        return {}
    return output


def kernel_join(kernel, setup: dict, plan: dict) -> tuple:
    """``(status, numbers)``: the ``joint_assembly`` finding the validator's own kernel run
    (``kernel``, :func:`independent_kernel`) derives for the assembly ``setup``. A run that
    is not ``ok`` names its status (``kernel_status``, plus ``kernel_unavailable`` when
    the kernel is missing) and is an error only when it errored, else unknown; an ``ok``
    run refusing the join is an error; unknown joined stock, missing setup facts or any
    retained input without its own native partition proof is unknown. Only a proven
    route passes, with that setup's completed joint features."""
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
    history = setup_lineage(plan, setup["id"])
    unproven_partition = any(
        not measured_output(plan, facts, ref)
        for earlier in plan.get("setups", [])
        if earlier["id"] in history
        for ref in input_refs(earlier)
        if ref.startswith(OUTPUT_PREFIX)
    )
    status = (
        "error"
        if detail.get("assembly_error")
        else "unknown"
        if (
            setup["joint"]["kind"] == "threaded"
            or detail.get("stock_reason")
            or "stock_bbox_mm" not in detail
            or unproven_partition
        )
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
        status, numbers = kernel_join(kernel, setup, plan)
        require(
            assembly["status"] == status,
            f"{sid}: joint assembly verdict differs from the validator's own kernel join",
        )
        require(
            assembly["numbers"] == numbers,
            f"{sid}: joint assembly evidence differs from the validator's own kernel join",
        )
        if joint["kind"] == "threaded":
            thread = findings["joint_thread", sid]
            require(
                thread["status"] == ("error" if thread["numbers"].get("violations") else "unknown"),
                f"{sid}: unmodeled threaded geometry cannot approve the assembly",
            )
            require(
                thread["numbers"].get("socket") == joint["socket"]
                and thread["numbers"].get("spigot") == joint["spigot"]
                and thread["numbers"].get("unmodeled_geometry")
                == ["helical flanks", "lead/runout", "prepared shoulder seating"],
                f"{sid}: threaded joint must retain exported identities "
                "and unmodeled geometry debt",
            )
            continue
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
        compound = joint.get("compound")
        if compound is not None:
            expected.update(
                product=compound["product"],
                cure_time_min=compound["cure_time_min"],
                surface_prep=compound["surface_prep"],
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


def identity_rows(plan: dict, features: dict, entries: Entries) -> dict:
    """``{subject: (category, reference, named)}``: every inventory item the checker's
    ``tool_resolves`` rule resolves on the validator's own plan and inventory, under the
    subject that rule gives it: each item a slot selects (resolution.setup_items) under
    its bare key, or as ``<category>.<key>`` where a bare key reads another category, and
    each item the prose ``named`` (resolution.named_references)."""
    data = SimpleNamespace(
        plan=plan,
        features=features,
        feature_definitions=operative_definitions(plan, features),
        inventory=entries.inventory,
    )
    return {
        row.subject: (row.numbers["category"], row.numbers["reference"], "named_in" in row.numbers)
        for row in identity_rule.evaluate(data)
        if "category" in row.numbers
    }


def make_op_rows(plan: dict, features: dict, entries: Entries) -> dict:
    """``{subject: numbers}``: the checker's ``tool_resolves`` evidence on each make
    operation of each shop-made item a setup holds with (resolution.make_ops), on the
    validator's own plan and inventory, under the subject that rule gives it
    (``<category>.<key> make op <n>``)."""
    data = SimpleNamespace(
        plan=plan,
        features=features,
        feature_definitions=operative_definitions(plan, features),
        inventory=entries.inventory,
    )
    return {
        row.subject: json.loads(json.dumps(row.numbers))
        for row in identity_rule.evaluate(data)
        if "make_op" in row.numbers
    }


def check_make_ops(plan: dict, features: dict, entries: Entries, findings: dict) -> None:
    """Every make operation (:func:`make_op_rows`) has its finding, with the evidence the
    validator's own run gives it and the verdict its line earns on the validator's own
    inventory: its tool read in ``tools`` only (resolution.make_tool: never another
    category's item or a machine's accessory), an error when not listed there, unknown
    when unverified or when any fact the line prints is not known
    (resolution.make_op_unknowns), else pass. No report value decides it."""
    data = SimpleNamespace(
        plan=plan,
        features=features,
        feature_definitions=operative_definitions(plan, features),
        inventory=entries.inventory,
    )
    for subject, numbers in sorted(make_op_rows(plan, features, entries).items()):
        key = "tool_resolves", subject
        require(key in findings, f"missing make operation finding for {subject}")
        finding = findings[key]
        require(finding["numbers"] == numbers, f"{subject}: make operation evidence differs")
        category, _, ref = numbers["item"].partition(".")
        _, op = make_ops(shop_made_item(data, ref, category))[numbers["make_op"] - 1]
        unknown = make_op_unknowns(op)
        tool = None if "tool" in unknown else make_tool(data, numbers["tool"])
        status = (
            "error"
            if tool is None and "tool" not in unknown
            else "unknown"
            if unknown or record_uncertain(tool)
            else "pass"
        )
        require(
            finding["status"] == status,
            f"{subject}: a make operation passes only on a listed, verified tool and known facts",
        )


def check_references(plan: dict, features: dict, entries: Entries, findings: dict) -> list:
    """Every selected or named item has its category/reference finding. Missing selected
    items are errors (named items unknown); inherited identity verification stays unknown.
    A selected diameter's declared measurement must independently qualify its numeric
    claim, else the finding is unknown, unverified and carries no diameter. Bare nominal
    diameters retain their contract; prose-only names remain identity-only. Every plan
    slot is covered by its selected identity. Returns the subjects not listed."""
    rows = identity_rows(plan, features, entries)
    items = {(category, reference) for category, reference, _ in rows.values()}
    for ref in sorted(selected_refs(plan)):
        require(
            entries.identities(ref) & items,
            f"{ref}: no reference finding resolves the identity it names",
        )
    missing = []
    for subject, (category, ref, named) in sorted(rows.items()):
        key = "tool_resolves", subject
        require(key in findings, f"missing reference finding for {subject}")
        finding = findings[key]
        require(
            (finding["numbers"].get("category"), finding["numbers"].get("reference"))
            == (category, ref),
            f"{subject}: reference finding names another item than {category}.{ref}",
        )
        if named:
            item = named_item(entries.inventory, subject)
            verified = item is not None and not record_uncertain(item)
            require(
                finding["status"] == ("pass" if verified else "unknown"),
                f"{subject}: a named item resolves only listed and verified",
            )
        elif not entries.resolves(ref, category):
            require(finding["status"] == "error", f"{subject}: missing item must be an error")
            missing.append(subject)
        else:
            item = entries.record(ref, category)
            diameter_keys = [name for name in ("dia_mm", "dia_in") if name in item]
            if "dia" in item and item.get("units") in {"mm", "in", "inch"}:
                diameter_keys.append("dia")
            measurements = [
                item[name]
                for name in diameter_keys
                if isinstance(item[name], dict)
                and "value" in item[name]
                and isinstance(item[name].get("measured"), dict)
            ]
            diameter = tool_length_mm(ref, "dia", entries, category)
            diameter_debt = bool(measurements) and (
                not numeric(diameter) or any(not accepted(fact) for fact in measurements)
            )
            unverified = entries.uncertain(ref, category)
            if unverified:
                require(
                    finding["status"] == "unknown",
                    f"{subject}: inherited verify must be unknown",
                )
            elif diameter_debt:
                require(
                    finding["status"] == "unknown",
                    f"{subject}: untrusted measured diameter must be unknown",
                )
            else:
                require(finding["status"] == "pass", f"{subject}: available identity must resolve")
            if diameter_debt:
                require(
                    finding["numbers"].get("verified") is False,
                    f"{subject}: untrusted measured diameter must be unverified",
                )
                require(
                    "dia_mm" not in finding["numbers"],
                    f"{subject}: untrusted measured diameter must not be reported",
                )
            elif numeric(diameter):
                require(
                    finding["numbers"].get("verified") is (not unverified),
                    f"{subject}: diameter evidence must keep its identity verification",
                )
                near(finding["numbers"].get("dia_mm"), diameter, f"{subject}: selected diameter")
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
    if source.startswith(OUTPUT_PREFIX):
        handed = measured_output(plan, facts, source)
        bbox, volume = handed.get("bbox_mm"), handed.get("volume_mm3")
    else:
        setups = facts.get("setups")
        handed = setups.get(source) if isinstance(setups, dict) else None
        handed = handed if isinstance(handed, dict) else {}
        if handed.get("stock_out_reason"):
            return "unknown"
        bbox, volume = (
            vector_of(handed.get("stock_out_bbox_mm"), 6),
            handed.get("stock_out_volume_mm3"),
        )
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
    """Independent fact-local acceptance and unit conversion; debt is never a number.

    ``gauge`` is already resolved, possibly a micrometer-set member. Retain an explicit
    member identity so Entries does not reject that record as an unselected whole set.
    """
    entries = Entries({"gauges": {"selected": {"members": {"resolved": gauge}}}})
    resolution = tool_length_mm("selected/resolved", "resolution", entries, "gauges")
    # A step that is not positive reads nothing: never a sufficient resolution (#315).
    return resolution if numeric(resolution) and resolution > 0 else "unknown"


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
        entries = Entries({"gauges": {"selected": {"members": {"resolved": gauge}}}})
        maximum = tool_length_mm("selected/resolved", "range", entries, "gauges")
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


def blank_gauge_debts(gauge: dict, ref: str, inventory: dict, fields: tuple) -> list:
    """Name only the refused facts an independently decided gauge check consumes.

    Shared checklist constructors supply canonical debt descriptions, never the verdict
    or numeric capability; those still come from Entries and the blank check itself.
    """
    category, name, _ = select_item(inventory, ref, "gauges")
    debts = []
    for field in fields:
        raw_range = field == "range" and isinstance(gauge.get("range_mm"), list)
        debt = None if raw_range else length_debt(gauge, field, category, name)
        if debt is None and gauge.get("verify") in (True, "unknown"):
            debt = record_debt(gauge, category, name, field)
        if debt:
            debts.append(debt)
    return debts


def blank_gauge_checks(prepared: dict, bands: dict, features: dict, inventory: dict, numbers):
    """``(worst, missing)``: each declared blank check read through the inventory's gauges
    (the gauges table, then a machine's own accessories): a gauge the inventory lacks is an
    error and missing, else :func:`blank_size_check` or :func:`blank_form_check` decides
    the row. The rows go to ``numbers["checks"]``; unknown checks retain their exact
    consumed-fact checklist debt, deduplicated on an unknown aggregate."""

    def plan_record(name):
        value = prepared.get(name)
        return value if isinstance(value, dict) else {}

    checks, methods, limits = plan_record("checks"), plan_record("methods"), plan_record("form_mm")
    rows, worst, missing = {}, "pass", []
    for key in (*PREPARED_SIZE_CHECKS, *PREPARED_FORM_CHECKS):
        ref = checks.get(key, "unknown")
        row = {"gauge": ref}
        gauge = resolve_item(inventory, "gauges", ref) if ref != "unknown" else None
        consumed = ()
        if ref != "unknown" and gauge is None:
            status = "error"
            missing.append(ref)
        elif key in bands:
            row["limits_mm"] = [round(v, 6) for v in bands[key]]
            status = blank_size_check(gauge, bands[key], features, row)
            if (
                gauge
                and gauge.get("kind") in PREPARED_SIZE_GAUGES
                and features.get("units") == "mm"
            ):
                consumed = ("range", "resolution")
        else:
            status = blank_form_check(gauge, methods.get(key), limits.get(key), row)
            if (
                gauge
                and gauge.get("kind") in PREPARED_FORM_GAUGES
                and written_procedure(methods.get(key))
                and numeric(limits.get(key))
                and limits[key] > 0
            ):
                consumed = ("resolution",)
        if status == "unknown" and consumed:
            debts = blank_gauge_debts(gauge, ref, inventory, consumed)
            if debts:
                row["measurements"] = debts
        row["status"] = status
        rows[key] = row
        worst = max(worst, status, key=STATUS_RANK.get)
    numbers["checks"] = rows
    if worst == "unknown":
        debts = {debt["id"]: debt for row in rows.values() for debt in row.get("measurements", [])}
        if debts:
            numbers["measurements"] = [debts[key] for key in sorted(debts)]
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
    lineage = setup_lineage(plan, receiver)
    definitions = operative_definitions(plan, features)
    made, later, unproven = [], [], []
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
            status = (
                feature_material_status(plan, receiver, setup["id"], name, features)
                if earlier
                else False
            )
            destination = unproven if status is None else made if status else later
            destination.append((name, f"{setup['id']} op {op['op']}"))
    numbers["made_by"] = [f"{PROCESS_PREFIX}{name} in {where}" for name, where in made]
    numbers["made_outside_lineage"] = [
        f"{PROCESS_PREFIX}{name} in {where}" for name, where in later
    ]
    if unproven:
        numbers["made_material_unknown"] = [
            f"{PROCESS_PREFIX}{name} in {where}" for name, where in unproven
        ]
        return "unknown", numbers, []
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
    partitioned = any(atom.path for atom in MaterialGraph(plan).nodes.get(receiver, ()))
    if partitioned:
        # The original bar's analytic box is not the receiving child's geometry.
        # Require every selected split's own native proof, then measure that child.
        facts = kernel()
        facts = facts if isinstance(facts, dict) else {}
        if any(
            not measured_output(plan, facts, ref)
            for earlier in plan["setups"]
            if earlier["id"] in lineage
            for ref in input_refs(earlier)
            if ref.startswith(OUTPUT_PREFIX)
        ):
            return "unknown", numbers, []
        declared = blank_box(origin, [length, *section], axes)
        numbers["declared_box_mm"] = [[round(v, 6) for v in span] for span in declared]
        allowed = [tolerance[2], tolerance[0], tolerance[1]]
        cut = blank_cut(plan, lambda: facts, receiver, axes, declared, allowed, numbers)
        bands = {
            key: [size - tol, size + tol]
            for key, size, tol in zip(
                PREPARED_SIZE_CHECKS, [length, *section], allowed, strict=True
            )
        }
        checked, missing = blank_gauge_checks(prepared, bands, features, inventory, numbers)
        return max(cut, checked, key=STATUS_RANK.get), numbers, missing
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


def zero_inputs(plan: dict, features: dict, inventory: dict, policy: dict, kernel):
    """The validator's own inputs a zero's surfaces are read from: the plan, manifest,
    inventory and policy, with its own kernel run's facts (``kernel``,
    :func:`independent_kernel`). No report value enters them."""
    return SimpleNamespace(
        plan=plan,
        features=features,
        inventory=inventory,
        policy=policy,
        feature_definitions=operative_definitions(plan, features),
        kernel=kernel(),
    )


def checker_row(own, evaluate, subject: str, status: str, numbers: dict) -> tuple:
    """``(status, numbers)`` of a finding the validator derives (``status``, ``numbers``)
    with what only the checker's own rule derives (``evaluate`` run on the validator's
    inputs ``own``, :func:`zero_inputs`): every value the validator derives stands (a
    mapping key by key, a list of as many rows row by row), and a value it does not is the
    checker's on those inputs, so a row the checker adds needs no validator edit and no
    report value is ever an operand. The status is the worse of the two: an unknown or
    error either derives is never a pass."""
    row = next((f.to_dict() for f in evaluate(own) if f.subject == subject), None)
    if row is None:
        return status, numbers

    def merge(theirs, ours):
        if isinstance(theirs, dict) and isinstance(ours, dict):
            return {**theirs, **{key: merge(theirs.get(key), v) for key, v in ours.items()}}
        if isinstance(theirs, list) and isinstance(ours, list) and len(theirs) == len(ours):
            return [merge(t, o) for t, o in zip(theirs, ours, strict=True)]
        return ours

    if row["status"] in STATUS_RANK and STATUS_RANK[row["status"]] > STATUS_RANK[status]:
        status = row["status"]
    return status, merge(row["numbers"], numbers)


def paper_stand_off(paper, side):
    """Where paper of ``paper`` mm stands a Z touch off its face along setup Z, met from
    ``side`` (+1/-1): no paper needs no side; an unknown side or paper leaves it unknown."""
    if not numeric(paper):
        return "unknown"
    if paper == 0:
        return paper
    return side * paper if side in (1, -1) else "unknown"


def bench_edge(value) -> str:
    """A measured edge's bench expression: the reading M plus ``value`` mm."""
    if not numeric(value):
        return "unknown"
    return "M " + f"{round(value, 6) + 0.0:+.6f}".rstrip("0").rstrip(".")


def zero_readings(axis: str, recipe: dict, sign, scale, contact, stand_off, lathe, gauge_ok):
    """The Axis Set, check and mirrored readings of one zero axis: a bench expression for a
    trial-cut diameter (``D``/``D/2`` by the display ``scale``, with a ready gauge) or a
    measured Z edge (M + offset + paper, a named measurement and a ready gauge), else the
    display ``scale`` times the physical ``contact``; the check jogs ``sign`` × scale ×
    jog from it (a measured edge's jog is physical) and the mirror the other way."""
    jog = recipe.get("check_jog_mm", "unknown")
    method = recipe.get("method")
    polarised = sign in (-1, 1) and numeric(jog)
    step = sign * scale * jog if polarised and numeric(scale) else "unknown"
    if method == "trial_cut_measure":
        display = {2: "D", 1: "D/2"}.get(scale, "unknown") if axis == "x" and lathe else "unknown"
        if display == "unknown" or not numeric(step) or not gauge_ok:
            return dict.fromkeys(ZERO_READINGS, "unknown")
        return {
            "axis_set": f"measured {display}",
            "check_reading": f"{display} {step:+g}",
            "mirrored_reading": f"{display} {-step:+g}",
        }
    if method == "measure_then_set":
        measure, offset = recipe.get("measure"), recipe.get("offset_mm", "unknown")
        named = isinstance(measure, str) and measure.strip() not in {"", "unknown"}
        if not (axis == "z" and named and gauge_ok and numeric(offset) and numeric(stand_off)):
            return dict.fromkeys(ZERO_READINGS, "unknown")
        if not polarised:
            return dict.fromkeys(ZERO_READINGS, "unknown")
        base = offset + stand_off
        return {
            "axis_set": bench_edge(base),
            "check_reading": bench_edge(base + sign * jog),
            "mirrored_reading": bench_edge(base - sign * jog),
        }
    shown = contact * scale if numeric(contact) and numeric(scale) else "unknown"
    if not (numeric(shown) and numeric(step)):
        return {**dict.fromkeys(ZERO_READINGS, "unknown"), "axis_set": shown}
    return {"axis_set": shown, "check_reading": shown + step, "mirrored_reading": shown - step}


# A carried plane's normal, and the axis of a plunge or turn bounding what a cut takes of
# it, must lie along setup Z to within this angle: the exactness of a rigid transform, not
# an authored included angle.
CARRY_DIRECTION_TOLERANCE_DEG = 1e-6
# Fixed-axis plunges whose footprint bounds what they take of a carried plane, and the
# hole kinds they plunge.
CARRY_PLUNGES = frozenset({"spot", "drill", "ream", "counterbore"})
CARRY_PLUNGE_KINDS = frozenset({"hole", "counterbore", "threaded_hole", "thread"})
CARRY_TURNS = frozenset({"turn", "rough_turn", "finish_turn"})
CARRY_FACINGS = FACING | {"part_off", "cut_to_fit"}
# The existing rectangular-touch contract: a visible 0.5 mm square remains,
# inset by native box-side/rounding uncertainty before testing cut exclusions.
CARRY_TOUCH_LAND_MM = 0.5
CARRY_FILL_MARGIN_MM = 1.5e-6


def table_of(value) -> dict:
    """``value`` when it is a table, else an empty one."""
    return value if isinstance(value, dict) else {}


def as_list(value) -> list:
    """``value`` when it is a list, else the one value as a list."""
    return value if isinstance(value, list) else [value]


def finite(value) -> bool:
    return numeric(value) and math.isfinite(value)


def frame_basis(frame) -> list | None:
    """``frame``'s x, y and z axes as unit, mutually square model vectors over a numeric
    origin, else None."""
    if not isinstance(frame, dict) or vector_of(frame.get("origin")) is None:
        return None
    axes = [vector_of(frame.get(name)) for name in ("x", "y", "z")]
    if None in axes or not all(finite(v) for axis in axes for v in axis):
        return None
    square = all(
        abs(dot(axes[i], axes[j]) - (i == j)) <= UNIT_TOLERANCE for i in range(3) for j in range(3)
    )
    return axes if square else None


def off_z_deg(vector: list) -> float:
    """The angle between ``vector`` (setup coordinates) and the setup's Z line."""
    return math.degrees(math.atan2(math.hypot(vector[0], vector[1]), abs(vector[2])))


def kernel_face(definitions: dict, name) -> bool:
    """Whether ``name`` is a face only its native kernel plane places (no authored bounds)."""
    target = table_of(definitions.get(name)) if isinstance(name, str) else {}
    return target.get("kind") == "face" and "bounds" not in target


def surface_cut_coverage(own, entries: Entries, setup: dict, op: dict, target: dict) -> str:
    """Independent face-extent guards and bounded native coverage from our own inputs.

    Incidental ``at``/``dia`` metadata never declares a face's extent, including with
    empty/unknown explicit bounds. A valid own-feature unbounded cut retains declared
    whole semantics without islands; cross-feature native unbounded containment and
    unbounded native keep-outs are unsupported here and independently unknown.
    Bounded native cuts resolve every authored ref through our kernel mapping and pose
    its finite model-mm box in setup units before selecting boxes wholly at ``to_z``.
    Boxes prove enclosure, not normals or filled topology; carried planes have their
    separate exact-plane/above-touch gates. Only signed permutations preserve extrema
    for partial-overlap/keep-out decisions. Valid authored bounds and non-face coverage
    still use the checker under #214, never these face-extent classifications.
    """
    if target.get("kind") != "face":
        return cut_coverage(own, setup, op, target)
    if "bounds" in target:
        if not isinstance(target["bounds"], dict) or not target["bounds"]:
            return "unknown"
        return cut_coverage(own, setup, op, target)
    if "stock_removal_bounds" not in op:
        name = op.get("feature")
        cut = table_of(own.feature_definitions.get(name)) if isinstance(name, str) else {}
        islands = table_of(op.get("contour")).get("keep_out", [])
        return "whole" if target == cut and isinstance(islands, list) and not islands else "unknown"
    region = [table_of(op.get("stock_removal_bounds")).get(axis) for axis in ("x", "y")]
    if not all(
        isinstance(span, list) and len(span) == 2 and all(map(finite, span)) and span[0] <= span[1]
        for span in region
    ):
        return "unknown"
    scale = UNIT_MM.get(own.features.get("units"))
    frame = setup_frame(setup, own.plan, own.features)
    axes = frame_basis(frame)
    if scale is None or axes is None or not all(map(finite, frame["origin"])):
        return "unknown"
    contour = table_of(op.get("contour"))
    islands = contour.get("keep_out", [])
    if not isinstance(islands, list):
        return "unknown"
    circles = []
    if islands:
        diameter = tool_length_mm(op.get("tool"), "dia", entries)
        name = op.get("feature")
        cut = table_of(own.feature_definitions.get(name)) if isinstance(name, str) else {}
        sweep = table_of(own.features.get("frames")).get(
            contour.get("sweep_frame", cut.get("frame", "model"))
        )
        if (
            not finite(diameter)
            or diameter <= 0
            or frame_basis(sweep) is None
            or not all(map(finite, sweep["origin"]))
        ):
            return "unknown"
        for island in islands:
            island = table_of(island)
            at, dia = vector_of(island.get("at"), 2), island.get("dia_mm")
            if at is None or not all(map(finite, at)) or not finite(dia) or dia <= 0:
                return "unknown"
            centre = frame_point(model_point([*at, 0.0], sweep), frame)[:2]
            radius = (dia + diameter) / (2 * scale)
            if not all(map(finite, centre)) or not finite(radius):
                return "unknown"
            circles.append((centre, radius))
    refs = target.get("faces")
    kernel = table_of(own.kernel)
    mapping, errors, native = (
        kernel.get("mapping"),
        kernel.get("mapping_errors", {}),
        kernel.get("faces"),
    )
    if not (
        isinstance(refs, list)
        and refs
        and all(isinstance(ref, str) and ref and ref != "unknown" for ref in refs)
        and kernel.get("status") == "ok"
        and isinstance(mapping, dict)
        and isinstance(errors, dict)
        and isinstance(native, list)
    ):
        return "unknown"
    boxes, kinds = [], []
    for ref in refs:
        index = mapping.get(ref)
        if ref in errors or not isinstance(index, int) or isinstance(index, bool):
            return "unknown"
        matched = [
            face
            for face in native
            if isinstance(face, dict)
            and isinstance(face.get("index"), int)
            and not isinstance(face["index"], bool)
            and face["index"] == index
        ]
        if len(matched) != 1:
            return "unknown"
        box = matched[0].get("bbox_mm")
        if not (
            isinstance(box, list)
            and len(box) == 6
            and all(map(finite, box))
            and all(box[i] <= box[i + 3] for i in range(3))
        ):
            return "unknown"
        spans = [[box[i] / scale, box[i + 3] / scale] for i in range(3)]
        points = [frame_point(list(point), frame) for point in product(*spans)]
        if not all(finite(value) for point in points for value in point):
            return "unknown"
        boxes.append([[min(p[i] for p in points), max(p[i] for p in points)] for i in range(3)])
        kinds.append(matched[0].get("kind"))
    tolerance = LENGTH_TOLERANCE_MM / scale
    if all(
        any(
            box[i][0] > region[i][1] + tolerance or box[i][1] < region[i][0] - tolerance
            for i in range(2)
        )
        for box in boxes
    ):
        return "partial"
    if not finite(op.get("to_z")):
        return "unknown"
    # Only a face of no known contrary kind can be a plane: a thin cylinder's box fitting
    # the length tolerance is no planar producer.
    boxes = [
        box[:2]
        for box, kind in zip(boxes, kinds, strict=True)
        if kind in (None, "unknown", "Plane")
        and all(abs(z - op["to_z"]) <= tolerance for z in box[2])
    ]
    if not boxes:
        return "unknown"
    exact = all(sorted(abs(value) for value in axis) == [0.0, 0.0, 1.0] for axis in axes)
    margins = [
        margin
        for box in boxes
        for i, span in enumerate(box)
        for margin in (span[0] - region[i][0], region[i][1] - span[1])
    ]
    disjoint = any(
        span[0] > region[i][1] + tolerance or span[1] < region[i][0] - tolerance
        for box in boxes
        for i, span in enumerate(box)
    )
    if disjoint or (exact and any(margin < -tolerance for margin in margins)):
        return "partial"
    if not all(margin > tolerance for margin in margins):
        return "unknown"
    excluded = any(
        math.hypot(
            max(box[0][0] - centre[0], 0.0, centre[0] - box[0][1]),
            max(box[1][0] - centre[1], 0.0, centre[1] - box[1][1]),
        )
        <= radius
        for centre, radius in circles
        for box in boxes
    )
    if excluded:
        return "partial" if exact else "unknown"
    # X/Y containment proves no plane the permitted removal volume never reaches.
    span = table_of(op.get("stock_removal_bounds")).get("z")
    reaches = (
        isinstance(span, list)
        and len(span) == 2
        and all(map(finite, span))
        and span[0] <= span[1]
        and span[0] - SAME_Z <= op["to_z"] <= span[1] + SAME_Z
    )
    return "whole" if reaches else "unknown"


def carry_route(plan: dict, setup: dict) -> list | None:
    """Validated producer history in plan order, including named retained outputs.

    Canonical partition identities allow sibling pieces from one bar to meet again,
    but still reject overlapping/reused material. This establishes no native geometry.
    """
    try:
        MaterialGraph(plan, validate=True)
    except (KeyError, TypeError, ValueError):
        return None
    routed = setup_lineage(plan, setup.get("id"))
    setups = [other for other in plan.get("setups", []) if other.get("id") in routed]
    if not setups or any(not input_refs(other) for other in setups):
        return None
    return setups


def exact_end_plane(kernel: dict, sid, face: str) -> dict | None:
    """Setup ``sid``'s own kernel fact for ``face`` as one exact flat end plane: its height
    along that setup's Z and its outer radius (mm), and which way along Z it faces."""
    setups = table_of(kernel.get("setups"))
    fact = table_of(table_of(table_of(setups.get(sid)).get("revolved")).get(face))
    zs, radii, ends = fact.get("z_mm"), fact.get("end_radii_mm"), fact.get("end_faces")
    if not (
        fact.get("kinds") == ["Plane"]
        and isinstance(zs, list)
        and len(zs) == 2
        and all(map(finite, zs))
        and 0 <= zs[1] - zs[0] <= LENGTH_TOLERANCE_MM
        and isinstance(radii, list)
        and len(radii) == 2
        and all(finite(r) and r > 0 for r in radii)
        and isinstance(ends, list)
        and len(ends) == 1
        and isinstance(ends[0], dict)
        and finite(ends[0].get("z_mm"))
        and numeric(ends[0].get("normal_z"))
        and ends[0]["normal_z"] in (1, -1)
    ):
        return None
    height = ends[0]["z_mm"]
    at = [i for i, z in enumerate(zs) if abs(z - height) <= LENGTH_TOLERANCE_MM]
    if not at or max(radii[i] for i in at) - min(radii[i] for i in at) > LENGTH_TOLERANCE_MM:
        return None
    return {"z_mm": height, "normal_z": ends[0]["normal_z"], "outer_radius_mm": radii[at[0]]}


def carried_plane_cut(
    own, entries: Entries, setup: dict, op: dict, face: str, index: int, current: bool = False
):
    """The exact plane ``op`` of ``setup`` cuts ``face`` (kernel index ``index``) to whole,
    as that setup's own kernel fact states it at the op's ``to_z``, with the height the
    cut leaves it at (``formed``: where the op's DRO stopped, ``to_z`` rounded up on its
    grid); None when ``op`` makes no such plane; "unknown" when its native
    footprint cannot cover that plane whole; "blade" when a blade corner's reading
    leaves it, which no plan-only derivation places. A ``current`` (touch-setup)
    producer's admissibility is its whole coverage and exact plane, not op claims."""
    kernel = table_of(own.kernel)
    action, to_z = op.get("do"), op.get("to_z")
    detail = table_of(table_of(kernel.get("ops")).get(f"{setup.get('id')}:{op.get('op')}"))
    lathe = machine_kind(setup, entries) == "lathe"
    turned_face = (
        lathe
        and action in TURNING_ACTIONS
        and kernel.get("status") == "ok"
        and detail.get("approach") == "turning"
        and numeric(detail.get("faced_side"))
        and detail["faced_side"] in (1, -1)
    )
    if not (
        finite(to_z)
        and (action in FACING | POCKETING or turned_face)
        and cutting_action(op) is True
    ):
        return None
    claims, away, invalid = op_claims(own, kernel, setup, op)
    if away or invalid:
        return None
    lenient = (
        current and claims is None and (op.get("feature") == face or action in FACING | POCKETING)
    )
    if (claims is None or index not in claims) and not lenient:
        return None
    target = table_of(own.feature_definitions.get(face))
    if surface_cut_coverage(own, entries, setup, op, target) != "whole":
        if kernel_face(own.feature_definitions, face):
            return "unknown"
        return None
    if frame_basis(setup_frame(setup, own.plan, own.features)) is None:
        return None
    plane = exact_end_plane(kernel, setup.get("id"), face)
    scale = UNIT_MM[own.features["units"]]
    if plane is None or abs(plane["z_mm"] - to_z * scale) > LENGTH_TOLERANCE_MM:
        return None
    tool = op.get("tool")
    kind = tool_field(tool, "kind", entries) if isinstance(tool, str) else "unknown"
    if lathe and (not isinstance(kind, str) or kind == "unknown" or kind in TURNING_BLADE_KINDS):
        return "blade"
    selected = next(
        (
            record
            for record in as_list(kernel.get("faces"))
            if table_of(record).get("index") == index
        ),
        {},
    )
    return {
        **plane,
        "formed": dro_up(to_z, dro_grid(setup, own.features, entries, own.plan)),
        "touch_face": selected,
    }


def plunge_footprint(own, entries: Entries, setup: dict, op: dict) -> tuple | None:
    """``(point, radius)``: where a fixed-axis plunge ``op`` of ``setup`` cuts, its planned
    point as this setup's DRO dials it (setup coordinates), and the widest radius (mm) its
    selected cutter cuts to the op's depth; None when it is no such plunge or any fact is
    unknown. A center_drill_set member cuts its pilot radius to its pilot length, then its
    countersink cone widens it by tan(half its angle) per mm deeper, never past its body."""
    action, name = op.get("do"), op.get("feature")
    feature = table_of(own.feature_definitions.get(name))
    if action not in CARRY_PLUNGES or feature.get("kind") not in CARRY_PLUNGE_KINDS:
        return None
    if any(key in feature for key in ("pattern", "positions", "holes")):
        return None
    frames = table_of(own.features.get("frames"))
    frame = setup_frame(setup, own.plan, own.features)
    axes = frame_basis(frame)
    own_axes = frame_basis(frames.get(feature.get("frame", "model")))
    axis = vector_of(feature.get("axis"))
    if axes is None or own_axes is None or axis is None:
        return None
    if abs(math.hypot(*axis) - 1) > UNIT_TOLERANCE:
        return None
    model_axis = [sum(axis[i] * own_axes[i][j] for i in range(3)) for j in range(3)]
    if off_z_deg([dot(model_axis, basis) for basis in axes]) > CARRY_DIRECTION_TOLERANCE_DEG:
        return None
    # The planned point reads plan aims, which ask whether a mill setup dials the hole
    # (:func:`dialled`): the same plan, features, frames, inventory and entries.
    context = SimpleNamespace(
        plan=own.plan,
        features=own.features,
        definitions=own.feature_definitions,
        frames=frames,
        entries=entries,
        inventory=entries.inventory,
    )
    point = planned_model_point(context, name)
    if point is None:
        return None
    grid = dro_grid(setup, own.features, entries, own.plan)
    point = [dro_target(v, grid) for v in frame_point(point, frame)]
    if not all(map(finite, point)):
        return None
    tool = op.get("tool")
    if tool_field(tool, "kind", entries) == "center_drill_set":
        facts = centre_tool_facts(tool, entries)
        pilot, length = facts["drill_dia_mm"], facts["drill_length_mm"]
        body, angle = facts["body_dia_mm"], facts["countersink_angle_deg"]
        depth = planned_depth_mm(op, feature, own.features.get("units"))
        if not (
            positive(pilot)
            and positive(length)
            and finite(body)
            and body >= pilot
            and finite(angle)
            and 0 < angle < 180
            and positive(depth)
        ):
            return None
        deeper = max(0.0, depth - length)
        radius = min(body / 2, pilot / 2 + deeper * math.tan(math.radians(angle / 2)))
    else:
        diameter = tool_length_mm(tool, "dia", entries)
        names = ("dia_mm", "dia_in", "dia")
        if not (positive(diameter) and all(accepted(tool_record(tool, n, entries)) for n in names)):
            return None
        radius = diameter / 2
    if action in {"spot", "drill"}:
        point_angle = tool_field(tool, "point_angle", entries)
        if not (
            finite(point_angle)
            and 0 < point_angle < 180
            and accepted(tool_record(tool, "point_angle", entries))
        ):
            return None
    return (point, radius) if math.isfinite(radius) else None


def turn_spares(own, setup: dict, op: dict, plane: dict, centre: list) -> bool:
    """Whether turn ``op`` of ``setup`` keeps clear of the carried ``plane`` (centred at
    setup ``centre``): a known external cylinder coaxial with setup Z, over a real Z window,
    whose radius reaches past the plane's whole disc. A spigot joint feature's cut is
    never inside its finished nominal; any other turn's is its own kernel cylinder."""
    scale = UNIT_MM[own.features["units"]]
    window = [op.get("z_from"), op.get("z_to")]
    if not (all(map(finite, window)) and abs(window[1] - window[0]) > LENGTH_TOLERANCE_MM / scale):
        return False
    name = op.get("feature")
    definition = table_of(own.feature_definitions.get(name))
    kernel = table_of(own.kernel)
    joint = table_of(definition.get("joint"))
    if joint:
        record = table_of(table_of(own.plan.get("joint_features")).get(joint.get("id")))
        at, axis = vector_of(record.get("at")), vector_of(record.get("axis"))
        nominal = record.get("nominal_dia")
        frame = setup_frame(setup, own.plan, own.features)
        axes = frame_basis(frame)
        if not (
            record.get("kind") == "cylinder_spigot"
            and at is not None
            and axis is not None
            and abs(math.hypot(*axis) - 1) <= UNIT_TOLERANCE
            and positive(nominal)
            and axes is not None
        ):
            return False
        on_axis = frame_point(at, frame)
        if math.hypot(on_axis[0], on_axis[1]) * scale > LENGTH_TOLERANCE_MM:
            return False
        if off_z_deg([dot(axis, basis) for basis in axes]) > CARRY_DIRECTION_TOLERANCE_DEG:
            return False
        radius = nominal * scale / 2
    else:
        refs = as_list(definition.get("faces"))
        mapped = table_of(kernel.get("mapping"))
        expected = {mapped.get(ref) if isinstance(ref, str) else None for ref in refs}
        indices = table_of(kernel.get("features")).get(name)
        claims, away, invalid = op_claims(own, kernel, setup, op)
        facts = table_of(table_of(kernel.get("setups")).get(setup.get("id")))
        fact = table_of(table_of(facts.get("revolved")).get(name))
        radii = fact.get("radii_mm")
        if not (
            isinstance(indices, list)
            and all(isinstance(i, int) and not isinstance(i, bool) for i in indices)
            and None not in expected
            and set(indices) == expected
            and claims
            and claims <= expected
            and not away
            and not invalid
            and fact.get("kinds") == ["Cylinder"]
            and isinstance(radii, list)
            and len(radii) == 2
            and all(finite(r) and r > 0 for r in radii)
            and abs(radii[1] - radii[0]) <= LENGTH_TOLERANCE_MM
        ):
            return False
        radius = radii[0]
    return radius >= plane["outer_radius_mm"] + math.hypot(centre[0], centre[1]) * scale


def facing_spares(own, entries: Entries, setup: dict, op: dict, plane: dict, centre: list):
    """Whether facing or parting ``op`` of ``setup`` keeps clear of the carried ``plane``
    (centred at setup ``centre``): the kernel's side the cut removes, and the plane's whole
    Z extent beyond every height the cut may leave (its ``to_z``, that DRO stop rounded
    up, and for a blade either side of it by its width)."""
    scale = UNIT_MM[own.features["units"]]
    tolerance = LENGTH_TOLERANCE_MM / scale
    kernel = table_of(own.kernel)
    detail = table_of(table_of(kernel.get("ops")).get(f"{setup.get('id')}:{op.get('op')}"))
    side, to_z = detail.get("faced_side"), op.get("to_z")
    axes = frame_basis(setup_frame(setup, own.plan, own.features))
    source_axes = frame_basis(plane["frame"])
    if not (numeric(side) and side in (1, -1) and finite(to_z) and axes and source_axes):
        return False
    cut = [to_z, dro_up(to_z, dro_grid(setup, own.features, entries, own.plan))]
    if machine_kind(setup, entries) == "lathe":
        tool = op.get("tool")
        kind = tool_field(tool, "kind", entries) if isinstance(tool, str) else "unknown"
        if not isinstance(kind, str) or kind == "unknown" or kind in TURNING_BLADE_KINDS:
            width = tool_length_mm(tool, "blade_width", entries)
            if not positive(width):
                return False
            cut += [to_z - width / scale, to_z + width / scale]
    extent = (
        plane["outer_radius_mm"]
        / scale
        * math.hypot(dot(source_axes[0], axes[2]), dot(source_axes[1], axes[2]))
    )
    if side == 1:
        return centre[2] + extent < min(cut) - tolerance
    return centre[2] - extent > max(cut) + tolerance


def rectangular_touch_land(own, setup: dict, plane: dict, centre: list, excluded_mm) -> bool:
    """Independently prove the existing rectangular 0.5 mm square touch witness.

    Native extrema and a plane normal do not prove circular topology. Only the
    selected single native Plane whose real ``fills_bbox`` fact certifies its
    rectangular interior supplies surface; a round or holed face supplies none.
    The cumulative axial footprint is enclosed by one square about the carried
    centre. With one axis-aligned exclusion, a free land can be slid to a corner
    of the rectangle, so its four corner placements exhaust the square witness.
    """
    face = table_of(plane.get("touch_face"))
    box = face.get("bbox_mm")
    scale = UNIT_MM.get(own.features.get("units"))
    if not (
        scale is not None
        and face.get("kind") == "Plane"
        and face.get("fills_bbox") is True
        and isinstance(box, list)
        and len(box) == 6
        and all(map(finite, box))
        and finite(excluded_mm)
        and excluded_mm >= 0
    ):
        return False
    sides = [[box[i] / scale, box[i + 3] / scale] for i in range(3)]
    if any(low > high for low, high in sides):
        return False
    frame = setup_frame(setup, own.plan, own.features)
    corners = [frame_point(list(point), frame) for point in product(*sides)]
    if not all(map(finite, (value for point in corners for value in point))):
        return False
    spans = [
        [min(point[i] for point in corners), max(point[i] for point in corners)] for i in range(3)
    ]
    tolerance = LENGTH_TOLERANCE_MM
    if spans[2][1] - spans[2][0] > tolerance or any(
        min(abs(point[i] - end) for end in spans[i]) > tolerance
        for point in corners
        for i in (0, 1)
    ):
        return False
    margin = CARRY_FILL_MARGIN_MM / scale + tolerance
    land = CARRY_TOUCH_LAND_MM / scale
    rectangle = [[low + margin, high - margin] for low, high in spans[:2]]
    if any(high - low < land for low, high in rectangle):
        return False
    reach = excluded_mm / scale
    cut = [[centre[i] - reach, centre[i] + reach] for i in (0, 1)]
    return any(
        any(position[i] + land <= cut[i][0] or position[i] >= cut[i][1] for i in (0, 1))
        for position in product(*[[low, high - land] for low, high in rectangle])
    )


def plane_cut_reach(own, entries: Entries, setup: dict, op: dict, plane: dict, excluded_mm):
    """What cut ``op`` of ``setup`` leaves of the carried ``plane``: None when it may take
    any of its touch area; else the radius (mm) about the plane's centre a touch must keep
    off, 0.0 when the cut keeps clear of the whole plane. Kernel claims must be known;
    a cut is clear of it when its authored removal bounds or its plunge footprint miss the
    plane's enclosing disc, or a turn or facing cut provably spares it. An overlapping
    axial plunge preserves only a proven rectangular 0.5 mm square touch land outside
    the cumulative exclusion; radial extrema alone never prove an annulus usable."""
    kernel = table_of(own.kernel)
    claims, away, invalid = op_claims(own, kernel, setup, op)
    if claims is None or away or invalid:
        return None
    scale = UNIT_MM[own.features["units"]]
    tolerance = LENGTH_TOLERANCE_MM / scale
    frame = setup_frame(setup, own.plan, own.features)
    axes, source_axes = frame_basis(frame), frame_basis(plane["frame"])
    if axes is None or source_axes is None:
        return None
    normal = [dot(source_axes[2], basis) for basis in axes]
    radius = plane["outer_radius_mm"]
    # The disc as cut (its physical centre) and its box in this setup.
    centre = frame_point(model_point([0.0, 0.0, plane["formed"]], plane["frame"]), frame)
    if not all(map(finite, centre)):
        return None
    half = [radius / scale * math.sqrt(max(0.0, 1 - n * n)) for n in normal]
    box = [[c - h, c + h] for c, h in zip(centre, half, strict=True)]
    if "stock_removal_bounds" in op:
        bounds = table_of(op.get("stock_removal_bounds"))
        spans = [bounds.get(axis) for axis in ("x", "y", "z")]
        if not all(
            isinstance(span, list)
            and len(span) == 2
            and all(map(finite, span))
            and span[0] <= span[1]
            for span in spans
        ):
            return None
        if any(
            cut[0] > face[1] + tolerance or cut[1] < face[0] - tolerance
            for cut, face in zip(spans, box, strict=True)
        ):
            return 0.0
    footprint = plunge_footprint(own, entries, setup, op)
    if footprint is not None:
        point, cutter = footprint
        if any(
            point[i] + cutter / scale < box[i][0] - tolerance
            or point[i] - cutter / scale > box[i][1] + tolerance
            for i in range(2)
        ):
            return 0.0
    action = op.get("do")
    # The kernel limits a lathe turning-approach cut (a lathe's non-axial action; no
    # to_z; not manual, saw, facing, pocketing, parting or transfer) to its
    # z_from..z_to window: a window wholly on the plane's outward side, in a frame
    # coaxial with the plane, leaves the plane whole. Its ends are the dialled
    # (rounded-up) ones, taken with the raw ones whichever is worse, and a blade (or an
    # unknown kind) cuts its whole known width up from the dialled chuck-side end.
    window = [op.get("z_from"), op.get("z_to")]
    outward = plane["normal_z"] * normal[2] if plane.get("normal_z") in (1, -1) else 0
    if (
        machine_kind(setup, entries) == "lathe"
        and "to_z" not in op
        and isinstance(action, str)
        and action not in AXIAL_LATHE_ACTIONS | MANUAL | SAW_OPS | FACING | POCKETING
        and action not in {"part_off", "cut_to_fit", "transfer", "unknown"}
        and all(map(finite, window))
        and off_z_deg(normal) <= CARRY_DIRECTION_TOLERANCE_DEG
    ):
        tool = op.get("tool")
        kind = tool_field(tool, "kind", entries) if isinstance(tool, str) else "unknown"
        width = 0.0
        if not isinstance(kind, str) or kind == "unknown" or kind in TURNING_BLADE_KINDS:
            width = tool_length_mm(tool, "blade_width", entries)
            known = isinstance(tool, str) and not entries.uncertain(tool, "tools")
            if not (known and positive(width)):
                width = None
        dialled = [dro_up(z, dro_grid(setup, own.features, entries, own.plan)) for z in window]
        if width is not None and all(map(finite, dialled)):
            low = min(*window, *dialled)
            high = max(*window, *dialled, max(min(window), min(dialled)) + width / scale)
            if (outward > 0 and low >= centre[2] - tolerance) or (
                outward < 0 and high <= centre[2] + tolerance
            ):
                return 0.0
    if action in CARRY_TURNS:
        return 0.0 if turn_spares(own, setup, op, plane, centre) else None
    if action in CARRY_FACINGS:
        return 0.0 if facing_spares(own, entries, setup, op, plane, centre) else None
    if footprint is None or off_z_deg(normal) > CARRY_DIRECTION_TOLERANCE_DEG:
        return None
    point, cutter = footprint
    reach = cutter + math.hypot(point[0] - centre[0], point[1] - centre[1]) * scale
    cumulative = max(excluded_mm, reach)
    return (
        reach
        if math.isfinite(reach) and rectangular_touch_land(own, setup, plane, centre, cumulative)
        else None
    )


def touch_position(ops: list, record: dict):
    """Own operation boundary: earliest named before-op, else after-op, else zero.
    A declared name that does not resolve is unknown, never an implicit initial zero."""
    names = [str(op.get("op")) for op in ops]
    if "before_ops" in record:
        before = as_list(record["before_ops"])
        if not before or any(str(name) not in names for name in before):
            return "unknown"
        return min(names.index(str(name)) for name in before)
    after = record.get("after_op")
    if after is not None:
        return names.index(str(after)) + 1 if str(after) in names else "unknown"
    return 0


def under_zero(setup: dict, op: dict) -> bool:
    """Whether ``setup``'s ``op`` cuts under its Z zero: ops before the zero's ``after_op``
    run before any tool set the Z DRO, so the zero, not they, places their faces."""
    ops = setup.get("ops", [])
    recipe = table_of(table_of(setup.get("zero")).get("z"))
    start = touch_position(ops, {"after_op": recipe.get("after_op")})
    return isinstance(start, int) and any(cut is op for cut in ops[start:])


def shares_plane_axis(own, old: dict | None, frame: dict) -> bool:
    """Own check that ``frame``'s centre axis is ``old`` plane's: parallel Z axes and
    origins within LENGTH tolerance across them."""
    if old is None:
        return False
    old_axes, new_axes = frame_basis(old["frame"]), frame_basis(frame)
    if old_axes is None or new_axes is None:
        return False
    if off_z_deg([dot(old_axes[2], basis) for basis in new_axes]) > CARRY_DIRECTION_TOLERANCE_DEG:
        return False
    a = model_point([0.0, 0.0, 0.0], old["frame"])
    b = model_point([0.0, 0.0, 0.0], frame)
    offset = [p - q for p, q in zip(a, b, strict=True)]
    axial = dot(offset, new_axes[2])
    lateral = math.sqrt(max(0.0, dot(offset, offset) - axial * axial))
    return finite(lateral) and lateral * UNIT_MM[own.features["units"]] <= LENGTH_TOLERANCE_MM


def carried_source_plane(own, entries: Entries, setup: dict, face, done: int) -> dict | None:
    """Where ``face`` stands when a setup cut it as one exact native plane and it
    survived into ``setup``'s first ``done`` ops, from the validator's own plan,
    inventory and kernel run alone: None when that is not how ``face`` reaches the
    touch (it has bounds or several refs, is supplied as-is, no op under a Z zero cut
    it, a blade's corner did, or this setup cuts it without such a framed producer);
    else ``{"unknown": reason}`` or the plane.

    Along the stock route (:func:`carry_route`, or this setup alone for a legacy local
    recipe), the last op that cuts it whole to its own kernel plane
    (:func:`carried_plane_cut`), including a producer in this setup before the touch,
    makes it at that op's as-cut height; every later cut must leave it
    (:func:`plane_cut_reach`), else its area is lost for good, as stock debt loses it.
    The as-cut source point and the nominal one carry rigidly into this setup's frame,
    where the plane must face +Z: ``physical`` and ``native`` heights, its one credited
    ref, the widest keep-off (``excluded_mm``) and whether this setup cut it
    (``current``). Empty/non-table explicit face bounds are independently unknown,
    never a checker-disc fallback."""
    target = table_of(own.feature_definitions.get(face)) if isinstance(face, str) else {}
    if target.get("kind") == "face" and "bounds" in target and not table_of(target["bounds"]):
        return {"unknown": f"{face} has no valid explicitly authored face bounds"}
    refs = target.get("faces")
    kernel = table_of(own.kernel)
    scale = UNIT_MM.get(own.features.get("units"))
    if not (
        scale is not None
        and kernel_face(own.feature_definitions, face)
        and isinstance(refs, list)
        and len(refs) == 1
        and isinstance(refs[0], str)
    ):
        return None
    (ref,) = refs
    index = table_of(kernel.get("mapping")).get(ref)
    if not (
        isinstance(index, int)
        and not isinstance(index, bool)
        and table_of(kernel.get("features")).get(face) == [index]
    ):
        return None
    supplied = as_list(table_of(own.plan.get("stock")).get("as_is_faces"))
    if any(item == ref for item in supplied):
        return None
    named = [op for op in setup.get("ops", [])[:done] if face in (op_features(op) or ())]
    local = bool(named)
    # A framed local producer is placed only by its own surviving native plane: with no
    # traceable route or receiving frame its area is unknown, never the checker's.
    framed = any(under_zero(setup, op) for op in named)
    route = carry_route(own.plan, setup)
    if route is None and local and "stock_in" not in setup:
        route = [setup]  # a legacy local recipe names no incoming route
    if route is None:
        return {"unknown": f"{face} has no valid native stock route"} if framed else None
    frame = setup_frame(setup, own.plan, own.features)
    axes = frame_basis(frame)
    if axes is None:
        return {"unknown": f"{face} has no known receiving rigid frame"} if framed else None
    outputs, made, unproven = {}, False, False
    for current in route:
        sid, receiving = current.get("id"), current is setup
        rows = []
        for source in input_refs(current):
            row = outputs.get(
                producer_setup(own.plan, source),
                {"present": False, "plane": None, "lost": False, "excluded": 0.0},
            )
            if source.startswith(OUTPUT_PREFIX) and row["present"] is not False:
                row = dict(row)
                producer = row["plane"]["source"] if row["plane"] is not None else None
                status = (
                    feature_material_status(own.plan, source, producer, face, own)
                    if producer is not None
                    else None
                )
                if status is False:
                    row.update(present=False, plane=None, lost=False, excluded=0.0)
                elif status is None or not measured_output(own.plan, kernel, source):
                    row.update(present="unknown", lost=True)
            rows.append(row)
        carrying = [row for row in rows if row["present"] is True]
        present = "unknown" if any(row["present"] == "unknown" for row in rows) else bool(carrying)
        if len({row["plane"]["source"] for row in carrying}) > 1:
            present = "unknown"
        state = {
            "present": present,
            "plane": carrying[0]["plane"] if carrying else None,
            "lost": any(row["lost"] for row in rows),
            "excluded": max((row["excluded"] for row in carrying), default=0.0),
        }
        facts = table_of(table_of(kernel.get("setups")).get(sid))
        debt = bool(facts.get("stock_reason")) or (
            not receiving and bool(facts.get("stock_out_reason"))
        )
        if debt and state["present"] is not False:
            state.update(present="unknown", lost=True)
        ops = current.get("ops", [])
        for op in ops[:done] if receiving else ops:
            cuts = True if op.get("do") in HAND_FINISH else cutting_action(op)
            if cuts is False:
                continue
            plane = None
            if (not receiving or local) and cuts is True and not debt and under_zero(current, op):
                plane = carried_plane_cut(
                    own, entries, current, op, face, index, receiving and local
                )
            if plane == "blade":
                return None
            if plane == "unknown":
                # Do not replace a surviving earlier plane with partial/ambiguous
                # production. Its ordinary cut-reach guard still decides survival.
                unproven, plane = True, None
            if plane is not None:
                made = True
                frame_of = setup_frame(current, own.plan, own.features)
                # A keep-off radius is about its plane's own centre: a re-face about
                # another centre leaves the old exclusion's extent unproven.
                if state["excluded"] > 0 and not shares_plane_axis(own, state["plane"], frame_of):
                    state["lost"] = True
                state["plane"] = {**plane, "source": sid, "frame": frame_of}
                state["present"] = "unknown" if state["lost"] else True
                continue
            if state["present"] is False:
                continue
            carried = state["plane"]
            known = cuts is True and carried is not None
            reach = (
                plane_cut_reach(own, entries, current, op, carried, state["excluded"])
                if known
                else None
            )
            if reach is None:
                state.update(present="unknown", lost=True)
            else:
                state["excluded"] = max(state["excluded"], reach)
        outputs[sid] = state
    final = outputs[setup.get("id")]
    if local and (final["plane"] is None or final["plane"]["source"] != setup.get("id")):
        return None  # cut here without an exact framed producer: its own reading places it
    if not made:
        if unproven:
            return {"unknown": f"native cut does not establish the whole {face} plane"}
        return None
    current = final["plane"] is not None and final["plane"]["source"] == setup.get("id")
    if final["present"] is not True:
        reason = f"no surviving credited stock plane with a bounded touch area for {face}"
        # An unproven survival leaves the reading unknown even against this setup's own
        # producer height: no contradiction is decided from a plane that may be gone.
        return {"unknown": reason, "current": current}
    plane = final["plane"]
    source_axes = frame_basis(plane["frame"])
    turned = [dot([plane["normal_z"] * v for v in source_axes[2]], basis) for basis in axes]
    if turned[2] <= 0 or off_z_deg(turned) > CARRY_DIRECTION_TOLERANCE_DEG:
        return {"unknown": f"carried {face} has no proven +Z outward normal in the receiving frame"}
    physical = frame_point(model_point([0.0, 0.0, plane["formed"]], plane["frame"]), frame)[2]
    native = frame_point(model_point([0.0, 0.0, plane["z_mm"] / scale], plane["frame"]), frame)[2]
    if not (finite(physical) and finite(native)):
        return {"unknown": f"carried {face} has no finite plane in the receiving rigid frame"}
    return {
        "physical": physical,
        "native": native,
        "ref": ref,
        "excluded_mm": final["excluded"],
        "current": current,
    }


def credited_from_above(own, entries: Entries, setup: dict, touch: dict, face, edge, lathe):
    """Whether a touch crediting a native plane meets it from a known +Z side: its authored
    ``from`` is +Z (on a mill from above; on a lathe, its face's own side agreeing), or
    with none, a mill's tool coming down or a lathe's face met from +Z."""
    mill = machine_kind(setup, entries) == "mill"
    if "from" in touch:
        if touch["from"] != "+z":
            return False
        return (
            zero_rules_touch.touch_side(own, setup, touch, face, edge, lathe) == 1
            if lathe
            else mill
        )
    if mill:
        return True
    return lathe and zero_rules_touch.touch_side(own, setup, touch, face, edge, lathe) == 1


def safe_down_setting(row: dict, field: str, constraint: dict, grid: tuple, scale) -> None:
    """Type a carried +Z contact (``row[field]``: its physical height plus paper) on the DRO
    ``grid`` safely down, never above the contact, so no later tip read off it cuts deeper,
    and keep the nonnegative physical residual (mm) the typed setting leaves; the check
    and mirrored readings move with it. ``constraint`` adds the plane's own evidence."""
    row.update(constraint)
    desired = row[field]
    step, decimals = grid
    typed = "unknown"
    if finite(desired):
        # Only float roundoff may meet a grid line from below; anything else floors.
        line = round(round(desired / step) * step, decimals)
        tight = 4 * max(math.ulp(line), math.ulp(desired))
        typed = line if abs(line - desired) <= tight else math.floor(desired / step) * step
        typed = round(typed, decimals) + 0.0
    row[field] = typed
    row["setting_residual_mm"] = (
        round((desired - typed) * scale, 9) + 0.0
        if numeric(typed) and scale is not None
        else "unknown"
    )
    if field == "axis_set":
        for key in ("check_reading", "mirrored_reading"):
            if key in row:
                row[key] = (
                    typed + (row[key] - desired)
                    if numeric(typed) and numeric(row[key])
                    else "unknown"
                )


def contact_retouch(recipe: dict) -> dict:
    """A listed retouch is a contact on the top, read from the zero recipe's side: never
    the primary zero's measured setting."""
    touch = {**recipe, "from": recipe.get("from", "unknown")}
    if touch.get("method") in MEASURED_ZERO:
        del touch["method"]
    return touch


def manual_thread_facts(inventory: dict, setup: dict):
    """Independent proof of wholly manual thread work, never a holding waiver."""
    reference = setup.get("machine", "unknown")
    kind = Entries(inventory).record(reference, "machines").get("kind")
    ops = setup.get("ops")
    if (
        kind not in BENCH_KINDS | {"lathe", "mill", "drill_press"}
        or not isinstance(ops, list)
        or not ops
        or not any(op.get("do") in HAND_THREAD for op in ops)
        or not all(op.get("do") in MANUAL for op in ops)
    ):
        return None
    return {
        "machine": reference,
        "machine_kind": kind,
        "manual_thread": True,
        "operations": [{"op": op.get("op", "unknown"), "do": op["do"]} for op in ops],
    }


def readout_fields(plan: dict, features: dict) -> dict:
    """Independent source-scale facts; CAD and readout units are distinct.

    A diameter-scale increment is diameter change, not radial travel. A source
    procedure or positive graduation does not prove physical calibration or zero.
    The explanatory debt sentence is wording, checked separately by check_readout.
    """
    dro = table_of(plan.get("dro"))
    units = dro.get("units", features.get("units", "unknown"))
    graduation = dro.get("graduation", "unknown")
    graduation = graduation if positive(graduation) else "unknown"
    unit_mm = UNIT_MM.get(units)
    graduation_mm = graduation * unit_mm if numeric(graduation) and unit_mm else "unknown"
    radius = dro.get("radius_mode")
    radial = (
        graduation_mm / (1 if radius is True else 2)
        if numeric(graduation_mm) and isinstance(radius, bool)
        else "unknown"
    )
    return {
        "kind": dro.get("kind", "digital"),
        "units": units,
        "graduation": graduation,
        "graduation_mm": graduation_mm,
        "x_radial_graduation_mm": radial,
        "x_scale": "radius" if radius is True else "diameter" if radius is False else "unknown",
        "procedure": dro.get("procedure", "unknown"),
        "backlash": dro.get("backlash", "unknown"),
        "calibration": dro.get("calibration", "unknown"),
    }


def check_readout(reported, plan: dict, features: dict, where: str) -> None:
    """Hold reported mechanical/unknown scale facts to authored inputs, not a rule helper."""
    fields = readout_fields(plan, features)
    require(
        isinstance(reported, dict) and set(reported) == set(fields) | {"debt"},
        f"{where}: readout fields are not the declared scale's",
    )
    for key, value in fields.items():
        require(
            same_evidence(reported[key], value),
            f"{where}: readout {key} is not the plan's {value!r}",
        )
    # Wording is not evidence, but an unproved physical instrument cannot lose its debt.
    debt = reported["debt"]
    require(
        isinstance(debt, str) and debt.strip() not in {"", "unknown"},
        f"{where}: readout physical-setting debt is missing",
    )


def mechanical_zero_rows(setup: dict, own, entries: Entries) -> tuple:
    """Independent source pickup rows, held without any electronic preset or carry proof.

    The returned readout has the source/numeric fields only; check_readout validates
    their report plus its nonempty explanatory debt. Nominal edge_mm and source
    calibration prose cannot register a physical dial or create carried Z readings.
    """
    zero = table_of(setup.get("zero"))
    fields = readout_fields(own.plan, own.features)
    axes = {
        axis: {
            key: recipe.get(key, "unknown")
            for key in ("procedure", "method", "dial_setting", "face", "feature", "tool", "gauge")
        }
        for axis in ("x", "y", "z")
        if isinstance(recipe := zero.get(axis), dict)
    }
    machine = machine_record(setup, entries)
    lathe = machine.get("kind") == "lathe" or "lathe" in str(machine.get("type", "")).lower()
    needed = ("x", "z") if lathe else ("x", "y", "z")
    missing = [
        f"{axis.upper()} physical dial setting"
        for axis in needed
        if not numeric(table_of(axes.get(axis)).get("dial_setting"))
    ]
    if not axes:
        missing.append("physical zero/pickup procedure")
    missing.extend(
        key for key in ("graduation", "calibration", "backlash") if fields[key] == "unknown"
    )
    directions = table_of(table_of(own.plan.get("dro")).get("direction"))
    missing.extend(
        f"{axis.upper()} direction"
        for axis in needed
        if directions.get(axis, "unknown") == "unknown"
    )
    if fields["units"] not in UNIT_MM:
        missing.append("readout units")
    if lathe and fields["x_scale"] == "unknown":
        missing.append("X diameter/radius scale")
    touches = zero.get("tool_touches")
    return (
        "unknown",
        {
            "frame": setup.get("frame", "unknown"),
            "readout": fields,
            "axes": axes,
            "physical_setting_debt": missing,
            "tool_touches": [row for row in touches if isinstance(row, dict)]
            if isinstance(touches, list)
            else [],
        },
        {},
    )


def mounted_zero_settings(setup: dict, own, entries: Entries) -> dict:
    """Checker/native contact proof, bound to independently selected authored pair facts.

    The checker supplies native contact/clearance interpretation and unresolved reasons.
    Selection, units, body-side arithmetic and tool/holder identity are independently
    checked here; neither its computed operands nor any report row defines them.
    """
    mounted = zero_rules_tool_setting.mounted_saw_settings(own, setup)
    ops, zero = setup["ops"], table_of(setup.get("zero"))
    scale = UNIT_MM.get(own.features.get("units"))

    def identity(reference, slot):
        category, key, _ = select_item(entries.inventory, reference, slot)
        return f"{category}.{key}" if category and key not in (None, "unknown") else "unknown"

    def pair(record):
        return identity(record.get("tool"), "spindle"), identity(record.get("holder"), "holders")

    def length(source, key):
        value = source.get(key, "unknown")
        return value * scale if numeric(value) and scale else "unknown"

    def position(kind, source):
        return 0 if kind == "axis" and "after_op" not in source else touch_position(ops, source)

    sources = [
        (kind, source)
        for kind, source in [
            ("axis", table_of(zero.get("z"))),
            *(("tool", row) for row in as_list(zero.get("tool_touches")) if isinstance(row, dict)),
        ]
        if source.get("method") == "mounted_saw_side"
    ]
    expected_ops = [op for op in ops if spindle_saw(entries.inventory, setup, op)]
    require(set(mounted) == {str(op["op"]) for op in expected_ops}, "mounted zero op identities")
    for op in expected_ops:
        where = f"{setup['id']}:{op['op']}: mounted zero"
        row = mounted[str(op["op"])]
        op_position = ops.index(op)
        selected, source, kind = "unknown", {}, None
        for index, (candidate_kind, candidate) in enumerate(sources):
            at = position(candidate_kind, candidate)
            if (
                pair(candidate) != pair(op)
                or not isinstance(at, int)
                or at > op_position
                or (
                    candidate_kind == "tool"
                    and isinstance(candidate.get("before_ops"), list)
                    and op["op"] not in candidate["before_ops"]
                )
                or any(
                    prior.get("do") not in MANUAL and pair(prior) != pair(op)
                    for prior in ops[at:op_position]
                )
            ):
                continue
            if source and position(kind, source) > at:
                continue
            selected, source, kind = index, candidate, candidate_kind
        require(row.get("selected") == selected, f"{where}: installed tool-holder touch selection")
        contact = table_of(source.get("mounted_saw"))
        body_facts = {
            key: length_fact(entries.record(op.get("tool"), "spindle"), stem, require_measured=True)
            for key, stem in (("body_thickness_mm", "thickness"), ("kerf_offset_mm", "kerf_offset"))
        }
        body, offset = (
            body_facts[key]["value"] if body_facts[key]["verified"] else "unknown"
            for key in ("body_thickness_mm", "kerf_offset_mm")
        )
        edge, paper = length(source, "edge_mm"), length(source, "paper_mm")
        side = contact.get("blade_side", "unknown")
        sense = {"minus_z": 1, "plus_z": -1}.get(side)
        axis_set = (
            edge + sense * (paper + body / 2) + offset
            if sense and all(map(numeric, (edge, paper, body, offset))) and paper >= 0 and body > 0
            else "unknown"
        )
        require(same_evidence(row.get("axis_set_mm"), axis_set), f"{where}: body-side arithmetic")
        setting = {
            "edge_mm": edge,
            "paper_mm": paper,
            "blade_side": side,
            "body_thickness_mm": body,
            "kerf_offset_mm": offset,
            "axis_set_mm": axis_set if row["status"] == "pass" else "unknown",
        }
        require(
            same_evidence(row.get("mounted_saw_setting"), setting),
            f"{where}: body thickness, contact side or paper compensation",
        )
        if source:
            authored = {
                "kind": kind,
                "axis": "z",
                "method": source["method"],
                "tool": pair(source)[0],
                "holder": pair(source)[1],
                "tool_reference": source.get("tool", "unknown"),
                "holder_reference": source.get("holder", "unknown"),
                "face": source.get("face", source.get("z_face", source.get("feature", "unknown"))),
                "edge_mm": edge,
                "paper_mm": paper,
                "check_jog_mm": length(source, "check_jog_mm"),
                "mounted_saw": contact,
                "position": position(kind, source),
                **{key: source[key] for key in ("before_ops", "after_op") if key in source},
            }
            require(
                all(same_evidence(row.get(key), value) for key, value in authored.items()),
                f"{where}: selected setting differs from authored contact or tool-holder identity",
            )
        expected_z = (
            axis_set / scale
            if row["status"] == "pass" and numeric(axis_set) and scale
            else "unknown"
        )
        require(same_evidence(row.get("z_axis_set"), expected_z), f"{where}: setup-unit Axis Set")
        native = table_of(table_of(own.kernel).get("ops")).get(f"{setup['id']}:{op['op']}", {})
        proof = (
            table_of(native).get("saw", {}) if table_of(own.kernel).get("status") == "ok" else {}
        )
        native_status, _, _ = finite_saw_evidence(native, "zero")
        require(
            STATUS_RANK.get(row["status"], -1) >= STATUS_RANK[native_status],
            f"{where}: native contact/clearance debt was promoted",
        )
        require(same_evidence(row.get("proof"), proof), f"{where}: independent native proof")
        if row["status"] == "pass":
            native_zero = table_of(proof.get("zero"))
            native_touch = next(
                (
                    item
                    for item in as_list(native_zero.get("touches"))
                    if isinstance(item, dict) and item.get("index") == selected
                ),
                {},
            )
            require(
                source
                and pair(op) != ("unknown", "unknown")
                and entries.verified(op.get("tool"), "spindle")
                and entries.verified(op.get("holder"), "holders")
                and slitting_saw(entries.inventory, op)
                and contact.get("spindle_state") == "stopped"
                and numeric(axis_set)
                and native_zero.get("selected") == selected
                and native_zero.get("status") == native_touch.get("status") == "pass"
                and native_touch.get("collisions") == []
                and all(
                    same_evidence(native_touch.get(key), value)
                    for key, value in {
                        **contact,
                        "plane_z_mm": edge,
                        "paper_mm": paper,
                        "body_thickness_mm": body,
                        "kerf_offset_mm": offset,
                        "cutting_midplane_z_mm": axis_set,
                        "surface_side": "+z" if sense == 1 else "-z",
                        "plane_normal_z": sense,
                    }.items()
                ),
                f"{where}: pass lacks current stopped body-side/native contact evidence",
            )
    return mounted


def derive_zero(setup: dict, own, entries: Entries) -> tuple:
    """The independently derived zero evidence; electronic-only extras stay electronic.

    A digital zero carries lathe tool-setting rows and checker-only evidence
    (:func:`checker_row`); a mechanical zero never merges that electronic recipe.
    """
    status, numbers, _ = zero_rows(setup, own, entries)
    if table_of(own.plan.get("dro")).get("kind", "digital") != "digital":
        return status, numbers
    if zero_rules_touch.lathe_setup(own, setup):
        numbers["tool_setting"] = zero_rules_tool_setting.tool_setting(
            own, setup, setup["zero"], numbers["tool_touches"], numbers["derived_touches"]
        )
    return checker_row(own, zero_rules_rule.evaluate, setup["id"], status, numbers)


def zero_rows(setup: dict, own, entries: Entries) -> tuple:
    """``(status, numbers, readings)``: independent ``zero_check`` rows and per-op carried
    electronic Z readings, from the validator's own inputs ``own`` (:func:`zero_inputs`).
    Mechanical pickups stay held with no carried readings, never nominal-edge presets.
    Electronic readings carry physical and native heights, typed setting, stand-off and
    residual; "unknown" for a native face its touch cannot place; absent otherwise.

    The DRO's jog polarity per axis is the plan's ``dro.direction`` (:data:`DRO_COUNTS`):
    a reversed axis (-1), or a mode other than ABS, is the error to stop on. The display
    scale is the plan's radius/diameter mode on a lathe's X, else 1; a lathe is the
    setup's machine as the inventory resolves it. Each axis row's contact is its edge,
    less or plus its finder radius (half its resolved tip, else body, diameter) by the side
    it comes from, or for Z its edge plus its paper on the side the face is met from; the
    readings follow (:func:`zero_readings`). Readings, a tool or gauge that is not ready
    (:meth:`Entries.verified` in the slot the checker reads it in: flagged, unverified or
    explicitly unknown), an unknown frame, binding, controller, mode or radius mode,
    retouch list or touch list leave the zero unknown. Where its surfaces stand (the top as
    each op leaves it, the side a face is met from, which touched or faced surface a tool
    change is touched off on, a blade's corner, where a touched face stands on the DRO
    grid) is plan and kernel geometry, read with the checker's surface functions on these
    inputs; a missing touch, a blade corner its face cannot give or a face set off the
    grid is an error. A face an upstream setup cut as one exact native plane and the
    stock carried here is the validator's own derivation (:func:`carried_source_plane`):
    it stands where its producer cut it, carried rigidly; its authored edge must be that
    or its native nominal; and its contact is typed safely down on this grid
    (:func:`safe_down_setting`), every carried contact so, its listed retouches contacts
    whatever the zero's own method (:func:`contact_retouch`). A lathe X touch's Axis Set
    is the checker's own expression of it (``x_touch_set``)."""
    if table_of(own.plan.get("dro")).get("kind", "digital") != "digital":
        return mechanical_zero_rows(setup, own, entries)
    plan = own.plan
    dro = plan.get("dro") if isinstance(plan.get("dro"), dict) else {}
    counts = dro.get("direction") if isinstance(dro.get("direction"), dict) else {}
    radius_mode, mode = dro.get("radius_mode"), dro.get("mode", "unknown")
    frame = setup_frame(setup, plan, own.features)
    frame = frame if isinstance(frame, dict) else {}
    # A lathe as the checker resolves the setup's machine: present, lathe kind or type.
    lathe = zero_rules_touch.lathe_setup(own, setup)

    def ready(ref, slot) -> bool:
        return entries.verified(ref, slot)

    zero, ops = table_of(setup.get("zero")), setup["ops"]
    spindle_ops = [op for op in ops if spindle_saw(entries.inventory, setup, op)]
    mounted = mounted_zero_settings(setup, own, entries) if spindle_ops else {}
    spindle_tools = {
        select_item(entries.inventory, op.get("tool"), "spindle")[:2] for op in spindle_ops
    }

    def unsupported_touch(reference):
        return (
            reference not in (None, "unknown")
            and select_item(entries.inventory, reference, "spindle")[:2] in spindle_tools
        )

    states = list(stock_states(own, setup))
    tops = [z for z, _ in zero_rules_faces._tops(own, setup, states)]
    corner_errors, face_errors, face_unknowns = [], [], []
    blade_corner = zero_rules_tool_setting._corner_recorder(own, setup, lathe, corner_errors)
    face_check = zero_rules_tool_setting._face_checker(own, setup, face_errors, face_unknowns)
    units_mm = UNIT_MM.get(own.features.get("units"))
    grid = dro_grid(setup, own.features, entries, plan)
    grid_trusted = dro_grid_trusted(setup, own.features, entries, plan)
    top_feature = table_of(setup.get("stock_state")).get("top_feature")
    carry = {}
    independent_contacts = set()

    def contact_side(touch, face, edge, done):
        if (face, done) in independent_contacts:
            # The own current-producer proof already requires the selected outward
            # normal to face receiving +Z; unknown survival cannot recover raw credit.
            return 1
        return zero_rules_touch.touch_side(own, setup, touch, face, edge, lathe)

    def touch_face(touch, face, edge, done, who, *source):
        """``(stands, credited refs, constraint or None)`` of a Z touch on ``face``: a
        native plane cut whole and surviving to the touch (:func:`carried_source_plane`),
        here or upstream, is the validator's own; any other face the checker's surface
        reading of it. The touch's operation boundary is its own raw op names."""
        native = top_feature if face == "top" else face
        if not isinstance(done, int):
            independent_contacts.add((face, done))
            face_unknowns.append(f"{who} on {face} (unknown operation boundary)")
            return "unknown", [], None
        carried = None
        if face and touch.get("method") not in MEASURED_ZERO:
            carried = carried_source_plane(own, entries, setup, native, done)
        if carried is None:
            stands, credited, constraint = face_check(touch, face, edge, done, who, *source)
            return stands, credited, constraint or None
        if "unknown" in carried:
            if carried.get("current"):
                independent_contacts.add((face, done))
            face_unknowns.append(f"{who} on {face} ({carried['unknown']})")
            return "unknown", [], None
        stands = carried["physical"]
        if not credited_from_above(own, entries, setup, touch, face, stands, lathe):
            reason = "native-plane credit requires a known +Z/above touch"
            face_unknowns.append(f"{who} on {face} ({reason})")
            return "unknown", [], None
        if not grid_trusted:
            # Readings stay on the nominal grid; an unverified grid certifies nothing.
            face_unknowns.append(f"{who} on {face} (unverified DRO grid)")
        if carried["current"]:
            # This setup's own framed producer: the exact DRO grid, as any local face,
            # with only the surviving-area exclusion carried onto the row.
            independent_contacts.add((face, done))
            shown = dro_up(edge, grid)
            if grid_trusted and numeric(edge) and shown != stands:
                face_errors.append(
                    f"{who} on {face} uses edge {edge:g} (DRO Z {shown:g}); "
                    f"the face stands at {stands:g}"
                )
            shown = dro_up(stands, grid)
            if grid_trusted and round(shown - stands, 9):
                face_errors.append(f"{who} sets {face} as Z {shown:g}, which stands at {stands:g}")
            exclusion = round(2 * carried["excluded_mm"], 9)
            # As the checker, a whole surviving face records no exclusion at all.
            constraint = {"touch_exclusion_dia_mm": exclusion} if exclusion else None
            return stands, [carried["ref"]], constraint
        tolerance = LENGTH_TOLERANCE_MM / units_mm
        if numeric(edge) and all(abs(edge - z) > tolerance for z in (stands, carried["native"])):
            face_errors.append(
                f"{who} on {face} uses edge {edge:g}; the carried face physically stands at "
                f"{stands:g}"
            )
        constraint = {
            "native_edge_mm": carried["native"],
            "touch_exclusion_dia_mm": round(2 * carried["excluded_mm"], 9),
        }
        return stands, [carried["ref"]], constraint

    def settle(key, touch, face, row, field, stands, constraint, stand_off, authored):
        """Type a carried contact safely down (:func:`safe_down_setting`) and record what an
        op reading it anchors on; a native face its touch cannot place reads unknown. A
        current producer's exact setting is not carried: only its exclusion is recorded."""
        if constraint and "native_edge_mm" not in constraint:
            row.update(constraint)
        elif constraint:
            safe_down_setting(row, field, constraint, grid, units_mm)
            carry[key] = {
                "typed": row[field],
                "stand_off": stand_off,
                "native": constraint.get("native_edge_mm", authored),
                "physical": stands,
                "residual": row["setting_residual_mm"],
            }
        elif (
            touch.get("method") not in MEASURED_ZERO
            and kernel_face(own.feature_definitions, top_feature if face == "top" else face)
            and not numeric(stands)
        ):
            carry[key] = "unknown"

    unknown = (
        not frame
        or frame.get("binding") == "unknown"
        or "unknown" in (dro.get("controller", "unknown"), radius_mode, mode)
    )
    unknown |= any(row["status"] != "pass" for row in mounted.values())
    bad = mode not in {"abs", "unknown"} or any(
        row["status"] == "error" for row in mounted.values()
    )
    axes = {}
    for axis in ("x", "y", "z"):
        recipe = zero.get(axis)
        if not isinstance(recipe, dict):
            unknown |= axis != "y" or not lathe
            continue
        direction = counts.get(axis, "unknown")
        up, down = DRO_COUNTS[axis]
        sign = 1 if direction in up else -1 if direction in down else "unknown"
        bad |= sign == -1
        if axis == "z" and recipe.get("method") == "mounted_saw_side":
            setting = next((row for row in mounted.values() if row.get("kind") == "axis"), {})
            shown, jog = setting.get("z_axis_set", "unknown"), recipe.get("check_jog_mm", "unknown")
            increment = sign * jog if sign in (-1, 1) and numeric(jog) else "unknown"
            axes[axis] = {
                **recipe,
                "axis_set": shown,
                "check_reading": (
                    shown + increment if numeric(shown) and numeric(increment) else "unknown"
                ),
                "mirrored_reading": (
                    shown - increment if numeric(shown) and numeric(increment) else "unknown"
                ),
                "axis_set_status": "computed" if numeric(shown) else "unknown",
                "tool_setting_state": "mounted_saw_side",
                "mounted_saw_proof": setting.get("proof", {}),
                "mounted_saw_setting": setting.get("mounted_saw_setting", {}),
            }
            unknown |= not numeric(shown) or not numeric(increment)
            continue
        if (
            unsupported_touch(recipe.get("tool"))
            and recipe.get("method") != "opposed_edge_midpoint"
        ):
            axes[axis] = {
                **recipe,
                **dict.fromkeys(ZERO_READINGS, "unknown"),
                "axis_set_status": "unknown",
                "tool_setting_state": "unsupported_spindle_saw",
            }
            unknown = True
            continue
        method, approach = recipe.get("method"), recipe.get("from")
        tool_ok = ready(recipe.get("tool"), "spindle")
        gauge_ok = ready(recipe.get("gauge"), "gauges")
        edge = recipe.get("edge_mm", "unknown")
        face = recipe.get("face", recipe.get("feature"))
        done = touch_position(ops, {"after_op": recipe.get("after_op")})
        paper, stand_off, contact = "not_applicable", None, "unknown"
        credited, carried = [], False
        if axis == "z" or method == "trial_cut_measure":
            radius = "not_applicable"
        elif approach == "indicated":
            radius = 0
        else:
            # A finder's tip, else its body, diameter halved, as the spindle slot selects it
            # (a set member's own or its set's, in mm or inches, as a fact or a bare length).
            reference = recipe.get("tool")
            tip = tool_length_mm(reference, "tip", entries, "spindle")
            diameter = tip if numeric(tip) else tool_length_mm(reference, "dia", entries, "spindle")
            radius = diameter / 2 if numeric(diameter) else "unknown"
        if axis == "z":
            if recipe.get("face") == "top":
                # The top as the ops through after_op left it, not the incoming top.
                edge = tops[done] if isinstance(done, int) else "unknown"
            z_touch = {**recipe, "from": recipe.get("from", "unknown")}
            authored = edge
            edge, credited, carried = touch_face(z_touch, face, edge, done, "the Z zero touch")
            paper = recipe.get("paper_mm", "unknown")
            side = contact_side(recipe, face, edge, done)
            stand_off = paper_stand_off(paper, side)
            contact = edge + stand_off if numeric(edge) and numeric(stand_off) else "unknown"
        elif (
            numeric(edge) and numeric(radius) and approach in {f"-{axis}", f"+{axis}", "indicated"}
        ):
            contact = edge + (-1 if approach == f"-{axis}" else 1) * radius
        scale = {True: 1, False: 2}.get(radius_mode, "unknown") if axis == "x" and lathe else 1
        values = zero_readings(axis, recipe, sign, scale, contact, stand_off, lathe, gauge_ok)
        if axis == "z":
            settle("zero", z_touch, face, values, "axis_set", edge, carried, stand_off, authored)
        row = {key: value for key, value in recipe.items() if key != "retouch_after"}
        row.update(
            values,
            sign=sign,
            edge_mm=edge,
            radius_mm=radius,
            paper_mm=paper,
            jog_mm=recipe.get("check_jog_mm", "unknown"),
            dro_direction=direction,
            axis_set_status=(
                "measured"
                if method in MEASURED_ZERO and values["axis_set"] != "unknown"
                else "computed"
                if numeric(values["axis_set"])
                else "unknown"
            ),
        )
        if credited:
            row["credited_faces"] = credited
        if method in MEASURED_ZERO:
            row["check_expression"] = values["check_reading"]
            row["mirrored_expression"] = values["mirrored_reading"]
            row["gauge_verify"] = not gauge_ok
        elif axis != "z":
            row["indicator_verify" if approach == "indicated" else "finder_verify"] = not tool_ok
        if axis == "z":
            blade_corner(row, recipe, face, edge, "the Z zero touch")
        axes[axis] = row
        unknown |= "unknown" in values.values() or not tool_ok
    z = zero["z"] if isinstance(zero.get("z"), dict) else {}
    paper, listed = z.get("paper_mm", "unknown"), z.get("retouch_after", "unknown")
    unknown |= listed == "unknown" or zero.get("tool_touches") == "unknown"
    retouch = []
    for index, (op, _, after) in enumerate(states):
        if isinstance(listed, list) and op.get("op") in listed:
            if unsupported_touch(z.get("tool")):
                retouch.append(
                    {
                        "op": op["op"],
                        "top_z": "unknown",
                        "paper_mm": paper,
                        "axis_set": "unknown",
                        "tool_setting_state": "unsupported_spindle_saw",
                    }
                )
                unknown = True
                continue
            who = f"the retouch after op {op['op']}"
            contact = contact_retouch(z)
            top, credited, carried = touch_face(
                contact, "top", tops[index + 1], index + 1, who, after["top_from"]
            )
            axis_set = top + paper if numeric(top) and numeric(paper) else "unknown"
            row = {"op": op["op"], "top_z": top, "paper_mm": paper, "axis_set": axis_set}
            side = contact_side(contact, "top", top, index + 1)
            stand_off = paper_stand_off(paper, side)
            key = ("retouch", op["op"])
            settle(key, contact, "top", row, "axis_set", top, carried, stand_off, tops[index + 1])
            if credited:
                row["credited_faces"] = credited
            retouch.append(row)
            unknown |= row["axis_set"] == "unknown"
    x_scale = {True: 1, False: 2}.get(radius_mode, "unknown") if lathe else "unknown"
    touches = []
    for record in zero.get("tool_touches") if isinstance(zero.get("tool_touches"), list) else []:
        if record.get("method") == "mounted_saw_side":
            setting = next(
                (
                    row
                    for row in mounted.values()
                    if row.get("kind") == "tool"
                    and row.get("tool_reference") == record.get("tool")
                    and row.get("holder_reference") == record.get("holder")
                    and row.get("before_ops") == record.get("before_ops")
                    and row.get("after_op") == record.get("after_op")
                ),
                {},
            )
            touches.append(
                {
                    **record,
                    "x_axis_set": "not_applicable",
                    "z_axis_set": setting.get("z_axis_set", "unknown"),
                    "tool_setting_state": "mounted_saw_side",
                    "mounted_saw_proof": setting.get("proof", {}),
                    "mounted_saw_setting": setting.get("mounted_saw_setting", {}),
                }
            )
            unknown |= setting.get("status") != "pass"
            continue
        if unsupported_touch(record.get("tool")):
            touches.append(
                {
                    **record,
                    "edge_mm": "unknown",
                    "x_axis_set": "unknown",
                    "z_axis_set": "unknown",
                    "tool_setting_state": "unsupported_spindle_saw",
                }
            )
            unknown = True
            continue
        edge, paper = record.get("edge_mm", "unknown"), record.get("paper_mm", "unknown")
        authored, z_face = edge, record.get("z_face")
        who = f"the {record.get('tool', 'unknown')} touch"
        done = touch_position(ops, record)
        edge, credited, carried = touch_face(record, z_face, edge, done, who)
        side = contact_side(record, z_face, edge, done)
        stand_off = paper_stand_off(paper, side)
        trial_cut = record.get("x_method") == "trial_cut_measure"
        x_set = (
            "not_applicable"
            if not lathe
            else zero_rules_touch.x_touch_set(
                x_scale, record.get("x_paper_mm", "unknown"), trial_cut
            )
            if ready(record.get("gauge"), "gauges")
            else "unknown"
        )
        if record.get("method") == "measure_then_set":
            measure, offset = record.get("z_measure"), record.get("z_offset_mm", "unknown")
            named = isinstance(measure, str) and measure.strip() not in {"", "unknown"}
            ready_z = named and ready(record.get("z_gauge"), "gauges")
            known = ready_z and numeric(offset) and numeric(stand_off)
            z_set = bench_edge(offset + stand_off) if known else "unknown"
        else:
            z_set = edge + stand_off if numeric(edge) and numeric(stand_off) else "unknown"
        row = {**record, "edge_mm": edge, "x_axis_set": x_set, "z_axis_set": z_set}
        settle(id(row), record, z_face, row, "z_axis_set", edge, carried, stand_off, authored)
        if credited:
            row["credited_faces"] = credited
        blade_corner(row, record, record.get("z_face"), edge, who)
        touches.append(row)
        unknown |= "unknown" in (x_set, row["z_axis_set"]) or not ready(
            record.get("tool"), "spindle"
        )
    derived, missing, changes_unknown, readings, served = zero_rules_tool_setting.tool_changes(
        own, setup, zero, lathe, x_scale, touches, mounted=mounted
    )
    unknown |= changes_unknown
    # A listed retouch names the op that reads it and the tool that goes in first; one no
    # later cutting op reads serves no tool.
    idle = {"next_op": "not_applicable", "next_tool": "not_applicable", "tool_change": False}
    for row in retouch:
        row.update(served.get(str(row["op"]), idle))
    for row in derived:
        who = f"the {row.get('tool', 'unknown')} re-touch"
        done = touch_position(ops, row)
        previous = row.get("edge_mm")
        offset = (
            row["z_axis_set"] - previous
            if numeric(previous) and numeric(row.get("z_axis_set"))
            else "unknown"
        )
        edge, credited, carried = touch_face(row, row.get("z_face"), previous, done, who)
        if carried and "native_edge_mm" in carried:
            offset = paper_stand_off(
                row.get("paper_mm", "unknown"),
                contact_side(row, row.get("z_face"), edge, done),
            )
        if row.get("z_face"):
            row["edge_mm"] = edge
            row["z_axis_set"] = edge + offset if numeric(edge) and numeric(offset) else "unknown"
            z_face = row["z_face"]
            settle(id(row), row, z_face, row, "z_axis_set", edge, carried, offset, previous)
            unknown |= row["z_axis_set"] == "unknown"
        if credited:
            row["credited_faces"] = credited
        blade_corner(row, row, row.get("z_face"), row.get("edge_mm"), who)
    unknown |= bool(face_unknowns)
    numbers = {
        "frame": setup.get("frame", "unknown"),
        "binding": frame.get("binding", "nominal"),
        "dro": {"mode": mode, "radius_mode": dro.get("radius_mode", "unknown")},
        "axes": axes,
        "retouch": retouch,
        "tool_touches": touches,
        "derived_touches": derived,
        "missing_touches": missing,
    }
    if spindle_ops:
        numbers.update(
            spindle_saw_ops=[op["op"] for op in spindle_ops],
            spindle_saw_debt="; ".join(
                dict.fromkeys(reason for row in mounted.values() for reason in row["reasons"])
            ),
            mounted_saw_settings=mounted,
        )
    if "transfer" in zero:
        numbers["transfer"] = zero["transfer"]
    status = "error" if bad or missing or corner_errors or face_errors else "pass"
    status = "unknown" if status == "pass" and unknown else status

    def reading(record):
        """What the Z touch ``record`` an op reads anchors it on: a tool touch or re-touch
        row itself, a listed retouch (its ``after_op`` and Axis Set), else the zero."""
        if record is None or record.get("method") in MEASURED_ZERO:
            return None
        if any(record is row for row in (*touches, *derived)):
            return carry.get(id(record))
        if "z_axis_set" in record and "after_op" in record:
            return carry.get(("retouch", record["after_op"]))
        return carry.get("zero")

    return status, numbers, {op: reading(record) for op, record in readings.items()}


def check_spindle_zero(setup: dict, finding: dict, inventory: dict) -> None:
    """A confirmed or possible disk cannot gain a no-spindle zero waiver."""
    ops = [op for op in setup["ops"] if spindle_saw(inventory, setup, op)]
    rows = finding["numbers"].get("mounted_saw_settings", {})
    require(
        finding["status"] in {"pass", "unknown", "error"}
        and finding["numbers"].get("spindle_saw_ops") == [op["op"] for op in ops]
        and set(rows) == {str(op["op"]) for op in ops}
        and finding["numbers"].get("spindle_saw_debt")
        == "; ".join(dict.fromkeys(reason for row in rows.values() for reason in row["reasons"]))
        and (
            finding["status"] in {"unknown", "error"}
            or all(row["status"] == "pass" for row in rows.values())
        ),
        f"{setup['id']}: mounted saw zero evidence is missing or waived",
    )


def check_zero(setup: dict, finding: dict, entries: Entries, own) -> None:
    """Hold the zero's verdict and rows to independent authored-input derivations.

    Electronic jogs, modes, presets and tool touches follow :func:`derive_zero`.
    Mechanical source pickups have no electronic settings and cannot waive their
    unverified physical registration. No report field or verdict is an operand.
    """
    if table_of(own.plan.get("dro")).get("kind", "digital") != "digital":
        status, numbers = derive_zero(setup, own, entries)
        sid, reported = setup["id"], finding["numbers"]
        check_readout(reported.get("readout"), own.plan, own.features, sid)
        require(
            set(reported) == set(numbers),
            f"{sid}: mechanical zero cannot invent digital modes, presets or retouches",
        )
        for key in numbers.keys() - {"readout"}:
            require(
                same_evidence(reported.get(key), numbers[key]),
                f"{sid}: mechanical zero {key} is not its authored pickup evidence",
            )
        require(
            finding["status"] == status,
            f"{sid}: unverified physical readout cannot pass or waive its zero",
        )
        return
    spindle = [op for op in setup["ops"] if spindle_saw(entries.inventory, setup, op)]
    if spindle:
        check_spindle_zero(setup, finding, entries.inventory)
    status, numbers = derive_zero(setup, own, entries)
    sid, reported = setup["id"], finding["numbers"]
    require(
        reported.get("dro") == numbers["dro"],
        f"{sid}: DRO mode or radius/diameter mode is not the plan's",
    )
    # The rows are the plan's: an axis row per authored recipe, a retouch row per listed
    # retouch in op order; a report cannot drop one to leave it unchecked.
    require(
        set(reported.get("axes", {})) == set(numbers["axes"]),
        f"{sid}: zero rows are not the plan's axis recipes",
    )
    require(
        [row.get("op") for row in reported.get("retouch", [])]
        == [row["op"] for row in numbers["retouch"]],
        f"{sid}: retouch rows are not the plan's listed retouches",
    )
    for axis, row in numbers["axes"].items():
        got = reported["axes"][axis]
        kind = {"measure_then_set": "measured-edge ", "trial_cut_measure": "trial-cut "}
        what = kind.get(row.get("method"), "")
        for field, name in ZERO_FIELDS:
            if (
                row.get("tool_setting_state") in {"mounted_saw_side", "unsupported_spindle_saw"}
                and field not in row
            ):
                continue
            require(
                same_evidence(got.get(field), row[field]),
                f"{sid}.{axis}: {what}{name} {got.get(field)!r} is not the {row[field]!r} "
                "its plan derives",
            )
        require(same_evidence(got, row), f"{sid}.{axis}: zero row is not the one its plan derives")
    for got, row in zip(reported["retouch"], numbers["retouch"], strict=True):
        require(same_evidence(got.get("top_z"), row["top_z"]), f"{sid}: advanced top")
        require(same_evidence(got, row), f"{sid}: retouch Axis Set")
    for key in ("tool_touches", "derived_touches", "missing_touches", "tool_setting"):
        require(
            same_evidence(reported.get(key), numbers.get(key)),
            f"{sid}: {key} are not the ones its plan derives",
        )
    require(same_evidence(reported, numbers), f"{sid}: zero evidence differs from its plan")
    # Only a saw or manual bench setup waives its zero (check_subjects): any other zero is
    # the verdict its plan decides.
    require(
        finding["status"] == status,
        f"{sid}: zero verdict {finding['status']} is not the {status} its plan decides",
    )


def check_centre_endpoint(
    plan: dict,
    features: dict,
    setup: dict,
    op: dict,
    row: dict,
    entries: Entries,
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
    if not entries.verified(reference, "tools"):
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
                kind = machine_record(setup, entries).get("kind", "unknown")
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
    the setup's authored ``stock_state`` through its preceding ops by ``stock_states``,
    which the engine shares, as it shares ``operative_definitions``. ``face`` is the feature
    when it has its own ``entry_z`` surface, else ``"top"``. ``stock`` carries the authored
    plan, manifest, inventory and operative definitions plus independently obtained kernel
    facts; no report value enters it."""
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
    if op.get("do") in TAP_OPS:
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


def machine_record(setup: dict, entries: Entries) -> dict:
    """The setup's machine as its machine slot selects it (:class:`Entries`), else {}."""
    return entries.record(setup.get("machine"), "machines")


def machine_kind(setup: dict, entries: Entries):
    return machine_record(setup, entries).get("kind")


def leaves_face(setup: dict, op: dict, entries: Entries):
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


def entry_producer(stock: SimpleNamespace, setup: dict, entry, face: str, source, entries: Entries):
    """The plan op whose cut left the surface a hole op of ``setup`` enters at nominal
    ``entry`` (:func:`entry_surface`), as ``(setup, op)``; None when no op cut it, so the
    authored surface stands; unknown when one may have cut it to an unknown Z or over an
    unknown part of it. From authored inputs and independent kernel facts: the op of
    ``setup`` that ``source`` names, with native coverage independently checked; else
    the last op in the same-frame stock lineage that cut the whole surface. For
    ``"top"`` this is a facing op on ``top_feature`` (any when none is named); for a
    feature it leaves its face or is a facing/pocketing candidate. Bounds-free faces
    use our matched boxes for bounded candidates, never authored discs/containment;
    unsupported unbounded cross-feature containment and invalid face bounds are
    unknown. An XY-disjoint cut is skipped before plane eligibility, preserving an
    earlier producer; a whole producer at another Z did not produce this entry."""
    if source == "unknown":
        return "unknown"
    made = re.fullmatch(r"(\S+) op (\S+) to_z", source) if isinstance(source, str) else None
    if made and made[1] == setup["id"]:
        producer = next(((setup, op) for op in setup["ops"] if str(op.get("op")) == made[2]), None)
        if producer is not None:
            op = producer[1]
            top = table_of(setup.get("stock_state")).get("top_feature")
            surface_name = (top or op.get("feature")) if face == "top" else face
            surface = (
                table_of(stock.feature_definitions.get(surface_name))
                if isinstance(surface_name, str)
                else {}
            )
            if surface.get("kind") == "face" and not table_of(surface.get("bounds")):
                coverage = surface_cut_coverage(stock, entries, setup, op, surface)
                if coverage != "whole":
                    # This local source is a checker stock_states whole claim.
                    # Falling back to its numeric entry would accept that same claim.
                    return "unknown"
        return producer
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
        surface_name = (top or name) if face == "top" else face
        surface = table_of(definitions.get(surface_name)) if isinstance(surface_name, str) else {}
        guarded_face = surface.get("kind") == "face" and not table_of(surface.get("bounds"))
        if face == "top":
            forms = action in FACING and "to_z" in op and top in (None, name)
        elif name == face:
            forms = leaves_face(earlier, op, entries)
        else:
            cut = definitions.get(name) if isinstance(name, str) else None
            target = definitions.get(face)
            forms = (
                action in FACING | POCKETING
                and "to_z" in op
                and isinstance(cut, dict)
                and isinstance(target, dict)
                and (guarded_face or covers_xy(cut, target))
            )
        if not forms:
            continue
        coverage = surface_cut_coverage(stock, entries, earlier, op, surface)
        if coverage == "unknown":
            return "unknown"
        if coverage != "whole":
            continue
        if forms is True and numeric(op.get("to_z")) and abs(op["to_z"] - entry) > SAME_Z:
            return None
        return (earlier, op) if forms is True else "unknown"
    return None


def printed_entry(stock: SimpleNamespace, setup: dict, entry, face: str, source, entries: Entries):
    """The entry surface Z the traveler prints for a hole op of ``setup`` entering nominal
    ``entry``: the ``to_z`` its producer (:func:`entry_producer`) cut, where that op's DRO
    stopped (rounded up on its own setup's grid), then as this setup's DRO shows it
    (rounded up on this grid); with no producer, the nominal rounded up on this grid; with
    a producer that may have cut it anywhere, unknown. A lathe producer's face stands
    where a blade's corner reading leaves it unless its cutter is known to be no blade:
    that face has no plan-only derivation, rejected. Every setup's DRO zero is held to
    its recipe by :func:`check_zero`."""
    features = stock.features
    grid = dro_grid(setup, features, entries, stock.plan)
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
    cut = dro_up(op.get("to_z", "unknown"), dro_grid(cut_setup, features, entries, stock.plan))
    return dro_up(cut, grid)


# What an endpoint read off a carried Z touch adds: where its entry physically stands,
# the bound a through hole's exit stands at under it (the as-cut entry less the local
# thickness, never an identified exit plane) and the residual its typed setting left.
CARRIED_ENDPOINT = ("physical_entry_z", "physical_exit_bound_z", "setting_residual_mm")
# Fields no endpoint carries: an as-cut exit plane (the local thickness bounds the exit,
# never names it) or a schema for that bound's source beyond its own name.
UNCLAIMED_EXIT = ("physical_exit_face", "exit_bound_from")


def plus(*values):
    """The sum of ``values``; unknown unless every one is a number."""
    return sum(values) if all(map(numeric, values)) else "unknown"


def check_printed_endpoint(row: dict, where: str, grid: tuple, planned: dict):
    """Hold the endpoint the traveler prints (``dro_*``) to the plan-derived one on the
    setup's DRO grid: the entry surface as its producer cut it (``planned["surface"]``,
    :func:`printed_entry`); a through hole's exit face rounded up; the tip keeping its
    planned distance below the surface it is worked from (the exit face of a through hole,
    else that printed entry), then rounded up; and the depth or break-through that printed
    tip leaves. ``planned`` carries only plan-derived values.

    An op whose DRO Z a carried touch set (``planned["carried"]``, :func:`zero_rows`)
    reads every plan Z off that touch's typed setting instead: moved by the setting less
    its stand-off less the plane's native height, its entry and a through exit rounded
    up, a blind tip rounded up from its own moved Z; its physical entry stands off native
    by the as-cut offset, a through exit's bound by the same (the as-cut entry less the
    planned thickness), and it repeats the setting's residual. An imported entry
    must match the carried native nominal within physical length tolerance; an
    authored AS-CUT entry is a named input error, not another Z to shift. An entry an
    op of this setup cut under its zero (``planned["local"]``, that cut's printed face)
    already stands on this DRO: it moves by that face less the nominal, and stands
    physically higher by the residual. A carried touch that cannot be placed leaves them
    all unknown, never the nominal's. Returns the independently computed printed tip Z,
    numeric only when the planned endpoint and its DRO datum are known."""
    entry, tip, exit_face = planned["entry"], planned["tip"], planned["exit_face"]
    through = exit_face != "not_applicable"
    carried = planned.get("carried")
    if carried is None:
        for key in CARRIED_ENDPOINT:
            require(key not in row, f"{where}: an endpoint off no carried touch has no {key}")
        surface, read_exit = planned["surface"], exit_face
        blind_shift = difference(surface, entry)
    else:
        known = isinstance(carried, dict)
        anchor = carried if known else dict.fromkeys(("typed", "stand_off", "physical"), "unknown")
        native = carried["native"] if known else "unknown"
        residual = carried["residual"] if known else "unknown"
        shift = difference(anchor["typed"], anchor["stand_off"], native)
        physical = difference(anchor["physical"], native)
        if planned.get("local") is not None:
            shift = difference(planned["local"], entry)
            scale = planned.get("units_mm")
            known = numeric(residual) and scale is not None
            physical = plus(shift, residual / scale) if known else "unknown"
        else:
            scale = planned.get("units_mm")
            if numeric(entry) and numeric(native) and scale is not None:
                require(
                    abs(entry - native) * scale <= LENGTH_TOLERANCE_MM,
                    f"{where}: Bad input: {planned['source']} must equal the carried native "
                    f"entry Z {native:g} within {LENGTH_TOLERANCE_MM:g} mm; got {entry:g}",
                )
        surface = dro_up(plus(entry, shift), grid)
        read_exit = plus(exit_face, shift) if through else exit_face
        blind_shift = shift
    same(row.get("dro_entry_z", "unknown"), surface, f"{where}: printed entry Z")
    if carried is not None:
        same(row.get("setting_residual_mm", "unknown"), residual, f"{where}: setting residual")
        physical_entry = plus(entry, physical)
        same(row.get("physical_entry_z", "unknown"), physical_entry, f"{where}: physical entry")
        if through:
            bound, field = plus(exit_face, physical), "physical_exit_bound_z"
            same(row.get(field, "unknown"), bound, f"{where}: physical exit bound")
        else:
            require("physical_exit_bound_z" not in row, f"{where}: a blind endpoint has no exit")
    for key in UNCLAIMED_EXIT:
        require(key not in row, f"{where}: no endpoint claims an as-cut exit plane ({key})")
    if through:
        printed_exit = dro_up(read_exit, grid)
        same(row.get("dro_exit_face", "unknown"), printed_exit, f"{where}: printed exit face")
        shift = difference(printed_exit, exit_face)
    else:
        require("dro_exit_face" not in row, f"{where}: a blind endpoint prints no exit face")
        shift = blind_shift
    worked = plus(tip, shift)
    printed_tip = dro_up(worked, grid)
    same(row.get("dro_tip_z", "unknown"), printed_tip, f"{where}: printed tip Z")
    if through:
        left = difference(read_exit, planned["lead"], printed_tip)
        same(row.get("dro_exit_mm", "unknown"), left, f"{where}: printed break-through")
        require("dro_depth_mm" not in row, f"{where}: a through endpoint prints no depth")
        return printed_tip
    require("dro_exit_mm" not in row, f"{where}: a blind endpoint has no break-through")
    depth = difference(planned["depth"], difference(printed_tip, worked))
    same(row.get("dro_depth_mm", "unknown"), depth, f"{where}: printed depth")
    floor = planned.get("floor", "unknown")
    same(row.get("depth_floor_mm", "unknown"), floor, f"{where}: depth band floor")
    return printed_tip


def check_endpoints(
    plan: dict, features: dict, findings: dict, entries: Entries, kernel=None
) -> dict:
    """Hold every ``blind_depth`` endpoint row to the plan, from its entry surface on,
    and the endpoint it prints to the setup's DRO grid (:func:`check_printed_endpoint`).
    The rows are exactly the plan's hole ops on the feature (a centre's, its
    center_drill ops) and the finding's verdict is the one those ops, their tools and
    the feature's depth guard and DRO datum decide: a contradiction (a tip past the depth
    guard, a tap flute shorter than its depth, a negative through allowance, a centre its
    tool does not cut) is an error, anything unresolved (no op, an unknown tip, guard or
    printed datum, a missing or unverified tool) unknown, else pass; a non-hole feature's
    is not applicable.
    Returns the material depth each hole op's full diameter cuts, keyed ``(setup, op)``,
    as the plan derives it (a through hole's local thickness, a blind or tapped hole's
    planned depth, a drilled centre's prepared depth), never the point or exit lead.
    Chain drills add their before-state entry-to-to_z penetration. No reported
    operand enters either depth. Surface coverage uses ``entries.inventory`` and the
    validator's own kernel getter (``kernel``, :func:`independent_kernel`), as
    :func:`zero_inputs` does. With no getter, native evidence is absent: a face needing
    it stays unknown; authored bounds need none. No report value supplies either input.
    An op whose DRO Z a carried touch set reads its endpoint off that touch's typed
    setting, from this validator's own zero rows (:func:`zero_rows`)."""
    setups = {setup["id"]: setup for setup in plan["setups"]}
    definitions = operative_definitions(plan, features)
    stock = SimpleNamespace(
        plan=plan,
        features=features,
        inventory=entries.inventory,
        feature_definitions=definitions,
        kernel=kernel() if kernel is not None else None,
    )
    units = features.get("units")
    depths, readings = {}, {}

    def carried_reading(setup: dict, op: dict):
        """The carried Z touch ``op``'s DRO reads, from this setup's own zero rows
        (:func:`zero_rows`); None when it reads none."""
        if saw_setup(entries.inventory, setup) or not isinstance(setup.get("zero"), dict):
            return None
        if setup["id"] not in readings:
            readings[setup["id"]] = zero_rows(setup, stock, entries)[2]
        return readings[setup["id"]].get(str(op["op"]))

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
            and (
                op.get("do") in PROCESS_ACTIONS["centre_hole"]
                if centre
                else op.get("do") in ENDPOINT_OPS
            )
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
            if action in TAP_OPS & HAND_THREAD:
                # A stopped-spindle hand tap uses a relative depth, not carriage/table
                # DRO coordinates. The independent oracle still checks actual tap length.
                require(row.get("depth_scale") == "manual", f"{where}: hand tap depth scale")
                require(
                    not any(key.startswith("dro_") for key in row)
                    and not any(key in row for key in CARRIED_ENDPOINT),
                    f"{where}: hand tap must not claim a DRO or carried tool setting",
                )
                entry, source, _ = entry_surface(stock, setup, op)
                near(row.get("entry_z", "unknown"), entry, f"{where}: nominal entry")
                require(row.get("entry_from") == source, f"{where}: nominal entry source")
                depth = planned_depth_mm(op, feature, units)
                tool = op.get("tool", "unknown")
                flute = tool_length_mm(tool, "flute_len", entries)
                near(row.get("depth_mm", "unknown"), depth, f"{where}: manual tapping depth")
                near(row.get("flute_len_mm", "unknown"), flute, f"{where}: actual tap flute length")
                band = "thread_depth" if "thread_depth" in feature else "depth"
                near(
                    row.get("depth_floor_mm", "unknown"),
                    feature_depth_mm(feature, band, units, 0),
                    f"{where}: thread depth floor",
                )
                require(row.get("exit_face") == "not_applicable", f"{where}: hand tap exit")
                near(row.get("tip_z", "unknown"), difference(entry, depth), f"{where}: nominal tip")
                depths[row["setup"], row["op"]] = depth if positive(depth) else "unknown"
                missing = not entries.resolves(tool, "tools")
                unverified = tool_unverified(tool, entries)
                if numeric(depth) and depth <= 0:
                    verdict = "error"
                elif numeric(flute) and numeric(depth) and flute < depth and not unverified:
                    verdict = "error"
                elif missing or unverified or not (positive(depth) and positive(flute)):
                    verdict = "unknown"
                else:
                    verdict = "pass"
                verdicts.append(verdict)
                continue
            grid_trusted = dro_grid_trusted(setup, features, entries, plan)
            require(
                bool(row.get("dro_grid_debt")) is not grid_trusted,
                f"{where}: endpoint grid debt is not its source measurement's trust",
            )
            feature = definitions[op["feature"]]
            action = op["do"]
            entry, source, face = entry_surface(stock, setup, op)
            near(row.get("entry_z", "unknown"), entry, f"{where}: touched entry surface")
            require(row.get("entry_from") == source, f"{where}: entry surface source")
            carried = carried_reading(setup, op)
            surface = "not_applicable"
            if carried is None:
                surface = printed_entry(stock, setup, entry, face, source, entries)
            planned = {
                "entry": entry,
                "source": source,
                "surface": surface,
                "exit_face": "not_applicable",
            }
            if carried is not None:
                producer = entry_producer(stock, setup, entry, face, source, entries)
                local = isinstance(producer, tuple) and producer[0] is setup
                planned.update(carried=carried, units_mm=UNIT_MM.get(units))
                known_touch = isinstance(carried, dict) and all(
                    numeric(carried.get(key))
                    for key in ("typed", "stand_off", "native", "physical", "residual")
                )
                if known_touch and local and under_zero(setup, producer[1]):
                    # A face this setup cut under its zero already stands on this DRO;
                    # an unknown touch never recovers it from that local producer.
                    planned["local"] = printed_entry(stock, setup, entry, face, source, entries)
            tool = op.get("tool", "unknown")
            # A missing tool resolves nothing; an unverified one proves no contradiction.
            missing = not entries.resolves(tool, "tools")
            unverified = tool_unverified(tool, entries)
            verdict = "pass"
            if centre and action in PROCESS_ACTIONS["centre_hole"]:
                require(
                    feature.get("kind") == "centre_hole",
                    f"{where}: only a plan centre hole has a centre endpoint",
                )
                cut, verdict = check_centre_endpoint(plan, features, setup, op, row, entries, entry)
                depths[row["setup"], row["op"]] = cut if positive(cut) else "unknown"
                planned.update(depth=cut, tip=difference(entry, cut))
                printed_tip = check_printed_endpoint(
                    row, where, dro_grid(setup, features, entries, plan), planned
                )
                if verdict != "error" and (not numeric(printed_tip) or not grid_trusted):
                    verdict = "unknown"
                verdicts.append(verdict)
                continue
            elif action in {"spot"} | TAP_OPS:
                depth = planned_depth_mm(op, feature, units)
                depths[row["setup"], row["op"]] = depth if positive(depth) else "unknown"
                near(row.get("depth_mm", "unknown"), depth, f"{action} cutting depth")
                require(row["exit_face"] == "not_applicable", f"{action} has no exit face")
                tip = difference(entry, depth)
                near(row["tip_z"], tip, f"{action} endpoint")
                planned.update(depth=depth, tip=tip)
                if action in TAP_OPS:
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
            printed_tip = check_printed_endpoint(
                row, where, dro_grid(setup, features, entries, plan), planned
            )
            if verdict != "error" and (
                not numeric(tip)
                or not numeric(printed_tip)
                or missing
                or unverified
                or not grid_trusted
            ):
                verdict = "unknown"
            verdicts.append(verdict)
        verdict = max(verdicts, key=STATUS_RANK.get, default="unknown")
        require(
            finding["status"] == verdict,
            f"{name}: endpoint verdict {finding['status']} is not the {verdict} its plan "
            "ops, tools, depth guard and DRO datum decide",
        )
    for setup in plan["setups"]:
        for op in setup["ops"]:
            if (
                op.get("do") != "rough_profile"
                or not isinstance(op.get("contour"), dict)
                or op["contour"].get("method") != "chain_drill"
                or selected_tool(op.get("tool"), entries, "kind")
                not in {"drill", "drill_index", "drill_set"}
            ):
                continue
            start, _, _ = entry_surface(stock, setup, op)
            end, scale = op.get("to_z", "unknown"), UNIT_MM.get(units)
            depth = (
                (start - end) * scale if numeric(start) and numeric(end) and scale else "unknown"
            )
            depths[(setup["id"], op["op"])] = depth if positive(depth) else "unknown"
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


def near_values(actual, expected, where: str) -> None:
    """Compare an entire numeric/unknown sequence, including its independent row count."""
    require(isinstance(actual, list) and len(actual) == len(expected), f"{where}: count")
    for observed, wanted in zip(actual, expected, strict=True):
        near(observed, wanted, where)


def selected_tool(ref, entries: Entries, key: str):
    """The selected tool's own authored ``key`` as the engine reads it (no fact record
    unwrapped); unknown for a reference that does not resolve to one tool."""
    if not entries.resolves(ref, "tools"):
        return "unknown"
    return tool_record(ref, key, entries)


def tool_unverified(ref, entries: Entries) -> bool:
    """Whether the selected tool carries verification debt (any fact marked for
    verification, unknown presence or verify coverage, through the references it names):
    its cutting data then proves nothing, so the row cannot pass."""
    return entries.resolves(ref, "tools") and entries.uncertain(ref, "tools")


def check_saw_speed(
    plan: dict, setup: dict, op: dict, finding: dict, entries: Entries, cutting: dict, material
) -> None:
    """A saw row is blade linear speed and descent feed from the one cited ``saw_cut`` row
    the plan's material class and the blade's material select; no spindle maths."""
    where = f"{setup['id']}:{op['op']}"
    row = finding["numbers"]
    machine = machine_record(setup, entries)
    tool_material = selected_tool(op.get("tool", "unknown"), entries, "material")
    identities = (*material, tool_material)
    require(row.get("tool_material") == tool_material, f"{where}: saw blade material")
    require((row.get("material"), row.get("material_class")) == material, f"{where}: saw material")
    known = all(isinstance(v, str) and v.strip() and v != "unknown" for v in identities)
    rows = [
        c
        for c in (cutting["cut"] if isinstance(cutting.get("cut"), list) else [])
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
    feed = "not_applicable" if "follows" in op else descent if positive(descent) else "unknown"
    same(row.get("feed_mm_min", "unknown"), feed, f"{where}: descent feed")
    require("rpm" not in row, f"{where}: a saw blade has no spindle RPM")
    material_verify = plan.get("stock", {}).get("material_verify", False)
    require(row.get("material_verify") == material_verify, f"{where}: material verification")
    range_verify = record_uncertain(machine)
    require(row.get("blade_speed_range_verify") == range_verify, f"{where}: blade range check")
    unsettled = (
        not numeric(speed)
        or feed == "unknown"
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
    authored = cutting.get("deep_hole")
    rows = [
        row
        for row in (authored if isinstance(authored, list) else [])
        if row.get("operation") == operation
    ]
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


def spindle_bands(machine: dict):
    """Available spindle intervals, clipped to authored bounds; malformed bands stay unknown."""
    spindle = machine.get("spindle") if isinstance(machine.get("spindle"), dict) else {}
    low, high = spindle.get("rpm_min", "unknown"), spindle.get("rpm_max", "unknown")
    declared = spindle.get("ranges_rpm", [[low, high]])
    if not isinstance(declared, list) or not declared:
        return "unknown"
    bands = []
    for band in declared:
        if not (isinstance(band, list) and len(band) == 2 and all(map(numeric, band))):
            return "unknown"
        start = max(band[0], low) if numeric(low) else band[0]
        end = min(band[1], high) if numeric(high) else band[1]
        if start <= end:
            bands.append((start, end))
    return sorted(bands) or "unknown"


def spindle_range(machine: dict) -> tuple:
    """The extreme available RPMs, not a claim that speeds between bands are available."""
    bands = spindle_bands(machine)
    if bands == "unknown":
        return "unknown", "unknown"
    return min(start for start, _ in bands), max(end for _, end in bands)


def available_rpm(rpm, machine: dict):
    """The fastest available speed no higher than the rounded/clamped request."""
    bands = spindle_bands(machine)
    if not numeric(rpm) or bands == "unknown":
        return "unknown"
    candidates = [min(end, rpm) for start, end in bands if start <= rpm]
    return max(candidates) if candidates else "unknown"


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


def cutting_diameter_mm(setup: dict, op: dict, entries: Entries, definitions: dict, units, lathe):
    """The diameter an op's speed is figured at, in mm, from the inventory and manifest: a
    rotating tool's own (any mill op, a lathe spindle-axis op); a turned feature's nominal,
    else twice its base radius (a dome's declared base), else for a facing cut the held
    stock O.D.; a rough turn adds its leave."""
    if not lathe or op.get("do") in AXIAL_LATHE_ACTIONS:
        # A member's own (measured) diameter outranks the size its name implies.
        tool = op.get("tool", "unknown")
        if not entries.resolves(tool, "tools"):
            return "unknown"
        return tool_length_mm(tool, "dia", entries)
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
    entries: Entries,
    cutting: dict,
    definitions: dict,
    depths: dict,
) -> None:
    """Hold a speeds_feeds row to the RPM and feed the authored inputs give: the plan's
    material and the cutting data's alias, the selected tool's chart (else the one cited
    cut row its material, the op and its diameter select), the machine's spindle range,
    the plan-derived hole depth (:func:`check_endpoints`) and its deep-hole derate. An
    authored RPM overrides the computed recommendation, not its unresolved-input debt;
    known request/limit contradictions remain errors. No reported operand enters the
    arithmetic; each is compared with its source."""
    where = f"{setup['id']}:{op['op']}"
    row = finding["numbers"]
    if op["do"] in MANUAL:
        require(finding["status"] == "not_applicable", f"{where}: a manual op has no speed")
        return
    material = cutting_material(plan, features, cutting)
    if hand_saw(entries.inventory, op):
        require(
            finding["status"] == "not_applicable"
            and row == {"operation": op["do"], "tool": op["tool"]},
            f"{where}: a hand saw has no blade speed or machine feed",
        )
        return
    disk = slitting_saw(entries.inventory, op)
    if spindle_saw(entries.inventory, setup, op) and not disk:
        require(
            finding["status"] == "unknown"
            and row
            == {
                "operation": op["do"],
                "tool": op.get("tool", "unknown"),
                "rpm": "unknown",
                "feed_mm_min": "unknown",
                "model_reason": UNRESOLVED_SAW_MODEL_REASON,
            },
            f"{where}: unresolved saw kind cannot establish blade-only speed or spindle RPM",
        )
        return
    if op["do"] in SAW_OPS and not disk:
        check_saw_speed(plan, setup, op, finding, entries, cutting, material)
        return
    machine = machine_record(setup, entries)
    lathe = machine.get("kind") == "lathe" and not disk
    tool = op.get("tool", "unknown")
    diameter = cutting_diameter_mm(setup, op, entries, definitions, features.get("units"), lathe)
    operation = "slitting_saw" if disk else CUT_OPERATIONS.get(op["do"], op["do"])
    if disk:
        require(
            row.get("action") == op["do"] and row.get("tool_kind") == "slitting_saw",
            f"{where}: missing spindle-mounted saw identity",
        )
        require("blade_speed_sfm" not in row, f"{where}: a disk requires spindle RPM")
        require("rpm" in row and "feed_mm_min" in row, f"{where}: missing disk RPM/feed")
    if (
        op["do"] == "rough_profile"
        and isinstance(op.get("contour"), dict)
        and op.get("contour", {}).get("method") == "chain_drill"
        and selected_tool(tool, entries, "kind") in {"drill", "drill_index", "drill_set"}
    ):
        operation = "drill"
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
        authored = cutting.get("cut")
        for candidate in authored if isinstance(authored, list) else []:
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
    flutes = tool_field(tool, "flutes", entries) if entries.resolves(tool, "tools") else "unknown"
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
    drilling = operation == "drill" and selected_tool(tool, entries, "kind") in {
        "drill",
        "drill_index",
        "drill_set",
    }
    if drilling:
        require(row.get("feed_direction") == "axial", f"{where}: drilling feed is axial")
        require("axial_feed_mm_rev" in row, f"{where}: drilling feed per revolution is reported")
        axial = (
            per_rev
            if lathe
            else flutes * chip
            if positive(flutes) and positive(chip)
            else "unknown"
        )
        near(row["axial_feed_mm_rev"], axial, f"{where}: axial feed per revolution")
    else:
        require(
            "feed_direction" not in row and "axial_feed_mm_rev" not in row,
            f"{where}: non-drilling feed has no drilling direction or per-revolution operand",
        )
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
    computed_rpm = available_rpm(nearest50(raw, low, high), machine)
    rpm = computed_rpm
    authored = "rpm" in op
    rpm_error = False
    authored_fields = {"requested_rpm", "computed_rpm", "rpm_basis", "rpm_status", "rpm_reason"}
    if authored:
        require(authored_fields <= row.keys(), f"{where}: missing authored RPM evidence")
        requested = op["rpm"]
        rpm = requested if positive(requested) else "unknown"
        bands = spindle_bands(machine)
        spindle = machine.get("spindle") if isinstance(machine.get("spindle"), dict) else {}
        minimum, maximum = spindle.get("rpm_min", "unknown"), spindle.get("rpm_max", "unknown")
        rpm_error = requested != "unknown" and not positive(requested)
        if positive(requested):
            rpm_error |= (
                (numeric(minimum) and requested < minimum)
                or (numeric(maximum) and requested > maximum)
                or (
                    bands != "unknown"
                    and not any(start <= requested <= end for start, end in bands)
                )
            )
        same(row["requested_rpm"], requested, f"{where}: requested RPM")
        near(row["computed_rpm"], computed_rpm, f"{where}: computed RPM")
        require(row["rpm_basis"] == "authored", f"{where}: authored RPM basis")
        require(
            isinstance(row["rpm_reason"], str) and row["rpm_reason"].strip() not in {"", "unknown"},
            f"{where}: missing authored RPM reason",
        )
    else:
        require(not authored_fields & row.keys(), f"{where}: unauthored RPM evidence")
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
        or (disk and saw_station(entries.inventory, setup, op) != "fits")
        or (
            authored
            and (
                bands == "unknown"
                or not numeric(raw)
                or not entries.record(tool, "tools")
                or not machine
            )
        )
    )
    # A request stays visible through debt; a known contradiction cannot become unknown.
    status = "error" if rpm_error else "unknown" if unsettled else "pass"
    if authored:
        require(row["rpm_status"] == status, f"{where}: authored RPM verdict")
    require(
        finding["status"] == status,
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
        kind = machine_record(setup, context.entries).get("kind")
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
    lathe = machine_kind(setup, context.entries) == "lathe"
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


def declared_dro_resolution(record: dict) -> tuple:
    """The independently read nominal resolution in mm and its authored fact."""
    authored = [key for key in ("resolution_mm", "resolution_in") if key in record]
    authored += ["resolution"] if "resolution" in record and "units" in record else []
    if len(authored) != 1:
        return "unknown", None
    key = authored[0]
    fact = record[key]
    value = fact.get("value", "unknown") if isinstance(fact, dict) else fact
    unit = "in" if key.endswith("_in") else "mm" if key.endswith("_mm") else record["units"]
    if unit == "mm":
        return (value if numeric(value) else "unknown"), fact
    if unit in {"in", "inch"}:
        inches = fraction(str(value))
        return (float(inches) * 25.4 if inches is not None else "unknown"), fact
    return "unknown", fact


def dro_grid_source(setup: dict, entries: Entries, plan: dict | None = None) -> dict:
    """A bench without its own positive declaration inherits its supplying machine."""
    machine = machine_record(setup, entries)
    resolution, _ = declared_dro_resolution(machine)
    if positive(resolution) or machine.get("kind") not in BENCH_KINDS or plan is None:
        return setup
    return next(
        (
            source
            for source in reversed(lineage(SimpleNamespace(plan=plan), setup))
            if machine_record(source, entries).get("kind") not in BENCH_KINDS
        ),
        setup,
    )


def dro_grid_trusted(
    setup: dict, features: dict, entries: Entries, plan: dict | None = None
) -> bool:
    """Judging requires the effective grid's own positive, complete measured fact."""
    dro = table_of(table_of(plan).get("dro"))
    if (
        dro.get("kind", "digital") != "digital"
        or dro.get("units", features.get("units")) not in UNIT_MM
    ):
        return False
    source = dro_grid_source(setup, entries, plan)
    resolution, fact = declared_dro_resolution(machine_record(source, entries))
    return (
        features.get("units") in UNIT_MM
        and positive(resolution)
        and isinstance(fact, dict)
        and isinstance(fact.get("measured"), dict)
        and accepted(fact)
    )


def dro_grid(setup: dict, features: dict, entries: Entries, plan: dict | None = None) -> tuple:
    """The nominal grid: keep declared precision regardless of judging trust.

    Only an absent/unread positive step uses ``DRO_DEFAULT_STEP``. A bench inherits
    its source machine's declaration and trust when its plan is available."""
    if table_of(table_of(plan).get("dro")).get("kind", "digital") != "digital":
        # Only an internal nominal grid; neither physical graduation nor machine DRO.
        return DRO_DEFAULT_STEP, 3
    scale = UNIT_MM.get(features.get("units"))
    source = dro_grid_source(setup, entries, plan)
    resolution, _ = declared_dro_resolution(machine_record(source, entries))
    step = resolution / scale if scale is not None and positive(resolution) else DRO_DEFAULT_STEP
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
    lathe = machine_kind(setup, context.entries) == "lathe"
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
        radius = context.plan.get("dro", {}).get("radius_mode")
        target = (
            (diameter / 2 if radius is True else diameter)
            if isinstance(radius, bool) and numeric(diameter)
            else "unknown"
        )
        same(row.get("dia_nominal", "unknown"), diameter, f"{where}: {label} nominal diameter")
        same(row.get("x_target_mm", "unknown"), target, f"{where}: {label} X target")
    else:
        require(not {"dia_nominal", "x_target_mm"} & row.keys(), f"{where}: no turned X target")
    return model, local


def coordinates_use_grid(setup, definitions, frames, numbers, lathe):
    """Independently identify authored or emitted targets that require a DRO grid."""
    for op in setup["ops"]:
        if (
            any(key in op for key in ("to_z", "z_from", "z_to"))
            or op.get("contour") == "unknown"
            or (isinstance(op.get("contour"), dict) and op["contour"])
        ):
            return True
        for name in op_features(op) or []:
            feature = definitions.get(name, {})
            if feature.get("kind") in LOCATED_KINDS or op.get("do") in CENTRE_OPS:
                return True
            locator, _ = located_point(definitions, frames, name)
            at = definitions.get(locator, {}).get("at")
            if isinstance(at, list) and len(at) == 3:
                return True
            if lathe and isinstance(feature.get("z_mm"), list) and feature["z_mm"]:
                return True
    if any(
        numbers.get(key)
        for key in ("rows", "profiles", "arc_table", "line_table", "contours", "level_paths")
    ):
        return True
    return any(
        any(key in operation for key in ("dro_to_z", "blade", "z_levels"))
        for operation in numbers.get("operations", [])
    )


def check_coordinates(
    setup: dict,
    features: dict,
    finding: dict,
    plan: dict,
    entries: Entries,
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
    if setup.get("frame", "unknown") in plan.get("frames", {}):
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
    lathe = machine_kind(setup, entries) == "lathe"
    grid = dro_grid(setup, features, entries, plan)
    grid_trusted = dro_grid_trusted(setup, features, entries, plan)
    uses_grid = coordinates_use_grid(setup, definitions, context.frames, numbers, lathe)
    if table_of(plan.get("dro")).get("kind", "digital") != "digital":
        if uses_grid:
            check_readout(numbers.get("readout"), plan, features, sid)
        else:
            require("readout" not in numbers, f"{sid}: unused nominal grid has no readout row")
        if lathe:
            require(
                numbers.get("x_display") == readout_fields(plan, features)["x_scale"],
                f"{sid}: mechanical X scale is not the plan's radius/diameter mode",
            )
        require(
            not any(
                entry.get("id", "").startswith("machines.")
                and entry.get("id", "").endswith(".resolution")
                for entry in numbers.get("measurements", [])
            ),
            f"{sid}: a mechanical or unknown readout cannot request a digital DRO resolution",
        )
    shown = numbers.get("dro_grid")
    require(isinstance(shown, dict) and set(shown) == {"step", "decimals"}, f"{sid}: DRO grid")
    if uses_grid:
        require(
            bool(numbers.get("dro_grid_debt")) is not grid_trusted,
            f"{sid}: coordinate grid debt is not its source measurement's trust",
        )
        require(
            grid_trusted or finding["status"] != "pass", f"{sid}: an unverified grid cannot pass"
        )
        near(shown["step"], grid[0], f"{sid}: DRO grid step")
        require(shown["decimals"] == grid[1], f"{sid}: DRO grid decimals")
    else:
        require(shown == {"step": "not used", "decimals": "not used"}, f"{sid}: unused DRO grid")
        require(not numbers.get("dro_grid_debt"), f"{sid}: unused grid carries decision debt")
        require(
            not any(
                entry.get("id", "").startswith("machines.")
                and entry.get("id", "").endswith(".resolution")
                for entry in numbers.get("measurements", [])
            ),
            f"{sid}: unused grid carries a measurement instruction",
        )
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
        near_values(row["model"], places[id(row)][0], f"{sid}: {row['feature']}: model coordinate")
    stations = [(row["feature"], row["point"]) for row in rows if "point" in row]
    require(len(set(stations)) == len(stations), f"{sid}: a station row repeats")
    if lathe:
        expected_stations = {
            (name, f"drawing station {index + 1}")
            for name in named
            if name in definitions and isinstance(definitions[name].get("z_mm"), list)
            for index in range(len(definitions[name]["z_mm"]))
        }
        expected_stations |= {
            (op["feature"], f"op {op['op']} {field}")
            for op in setup["ops"]
            if isinstance(op.get("feature"), str) and op["feature"] in definitions
            for field in ("to_z", "z_from", "z_to")
            if numeric(op.get(field))
        }
        require(expected_stations <= set(stations), f"{sid}: an authored lathe station is missing")
    for name in {name for name, point in stations if "kernel span" in point}:
        ends = {point.rsplit(" ", 1)[1] for owner, point in stations if owner == name}
        require(ends >= {"start", "end"}, f"{sid}: {name}: a kernel span lacks an end")
    standing = check_aims(context, setup, finding, frame, places)
    unresolved_targets = False
    for row in rows:
        where = f"{sid}: {row['feature']}"
        # A row a plan aim moves stands at the moved point; its nominal target is checked
        # as nominal_setup (check_aims).
        moved = id(row) in standing
        target = frame_point(standing[id(row)], frame) if moved else places[id(row)][1]
        near_values(row["setup"], target, f"{where}: setup coordinate")
        if "point" not in row:
            unresolved_targets |= not all(map(numeric, target))
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
            near_values(row["dro"], dro, f"{where}: printed DRO target")
            dialled_xy = dro[:2]
        else:
            require("dro" not in row, f"{where}: an unplaced target prints no DRO stop")
            require("point" not in row, f"{where}: an unplaced station row")
            dialled_xy = [dro_target(value, grid) for value in target[:2]]
        require(isinstance(row.get("dro_xy"), list), f"{where}: tool-axis DRO X/Y")
        near_values(row["dro_xy"], dialled_xy, f"{where}: tool-axis DRO X/Y")
    # A target-only mill setup has no contour, axial or height-band verdict to merge.
    # Derive its whole verdict from the source frame and every source target, not from
    # a self-consistent report's choice of pass/unknown/error.
    target_only = not lathe and all(
        op.get("do") in CENTRE_OPS | {"inspect"}
        and not any(
            key in op
            for key in (
                "contour",
                "to_z",
                "z_from",
                "z_to",
                "doc_mm",
                "rough_allowance_mm",
                "stock_to_leave_mm",
                "to_z_band",
                "stock_removal_bounds",
            )
        )
        for op in setup["ops"]
    )
    target_only &= all(
        name in definitions
        and not any(key in definitions[name] for key in HEIGHT_BANDS)
        and name not in plan.get("aims", {})
        and located_point(definitions, context.frames, name)[0] not in plan.get("aims", {})
        for name in named
        if isinstance(name, str)
    )
    if target_only:
        unresolved = frame == "unknown" or frame.get("binding") == "unknown"
        unresolved |= unresolved_targets or not grid_trusted
        status = "unknown" if unresolved else "pass"
        require(finding["status"] == status, f"{sid}: ordinary target verdict is not {status}")


class SheetText(HTMLParser):
    """Visible text and its disclosure/owner ancestry; scripts never supply print debt."""

    VOID = {
        "area",
        "base",
        "br",
        "col",
        "embed",
        "hr",
        "img",
        "input",
        "link",
        "meta",
        "source",
        "wbr",
    }
    INVISIBLE = {"head", "script", "style", "template", "noscript"}
    HIDDEN_STYLE = re.compile(
        r"(?:display\s*:\s*none|visibility\s*:\s*(?:hidden|collapse))\b", re.I
    )

    def __init__(self, html=""):
        super().__init__()
        self.text, self.nodes, self.stack = [], [], []
        self.hidden_selectors = []
        for sheet in re.findall(r"<style\b[^>]*>(.*?)</style>", html, re.I | re.S):
            for selectors, declarations in re.findall(r"([^{}]+)\{([^{}]*)\}", sheet):
                if self.HIDDEN_STYLE.search(declarations):
                    self.hidden_selectors.extend(
                        selector.strip() for selector in selectors.split(",")
                    )

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)

        def matches(selector):
            if selector == "*":
                return True
            if not re.fullmatch(r"(?:[a-z][\w-]*)?(?:[.#][\w-]+)*", selector, re.I):
                return False
            return all(
                token[1:] in classes
                if token.startswith(".")
                else token[1:] == attrs.get("id")
                if token.startswith("#")
                else token == tag
                for token in re.findall(r"^[a-z][\w-]*|[.#][\w-]+", selector, re.I)
            )

        classes = set(attrs.get("class", "").split())
        css_hidden = any(matches(selector) for selector in self.hidden_selectors)
        hidden = (
            bool(self.stack and self.stack[-1].hidden)
            or tag in self.INVISIBLE
            or "hidden" in attrs
            or attrs.get("aria-hidden") == "true"
            or self.HIDDEN_STYLE.search(attrs.get("style", "")) is not None
            or css_hidden
        )
        node = SimpleNamespace(
            tag=tag,
            attrs=attrs,
            classes=classes,
            hidden=hidden,
            text=[],
            ancestors=tuple(self.stack),
        )
        self.nodes.append(node)
        if tag not in self.VOID:
            self.stack.append(node)

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag not in self.VOID:
            self.handle_endtag(tag)

    def handle_endtag(self, tag):
        for index in range(len(self.stack) - 1, -1, -1):
            if self.stack[index].tag == tag:
                del self.stack[index:]
                break

    def handle_data(self, data):
        if self.stack and not self.stack[-1].hidden:
            self.text.append(data)
            for node in self.stack:
                node.text.append(data)


def check_sheet_disclosures(parser: SheetText, report: dict) -> None:
    """Every unknown/error has visible debt in its own physical or legacy print scope.

    Decision metadata binds visible prose to findings; it cannot replace that prose.
    A grouped decision must retain both its original evidence identities and each
    setup/op owner. Legacy boxes use their visible topic and local setup/op labels.
    """
    unknown_words = re.compile(
        r"\?|\b(?:unknown|unmapped|unverified|unresolved|unsupported|missing|uncertain|"
        r"undeclared|confirm|cannot|not\b|no\b)",
        re.I,
    )
    error_words = re.compile(
        r"✗|\b(?:stop|error|fail\w*|cannot|not\b|no\b|outside|exceed\w*|"
        r"mismatch\w*|must|required|needs?|invalid|unsafe|collid\w*|intersect\w*|"
        r"missing|disagree\w*|clash\w*|hits|insufficient|away)\b",
        re.I,
    )
    cleared_words = re.compile(
        r"^\s*(?:all\s+clear\b.*|no\s+(?:unknowns?|errors?|issues?|collisions?)\s+"
        r"(?:or\s+\w+\s+)*(?:remain|present|found)\b.*)\s*$",
        re.I,
    )

    def normalized(value):
        return re.sub(r"[^a-z0-9]+", " ", value.lower()).strip()

    def decoded(attrs, key):
        try:
            return json.loads(attrs.get(key, "[]"))
        except (ValueError, TypeError):
            return []

    def owners(node, subject):
        sid, separator, op = subject.partition(":")
        for ancestor in (node, *reversed(node.ancestors)):
            if "data-physical-ops" in ancestor.attrs:
                rows = decoded(ancestor.attrs, "data-physical-ops")
                return isinstance(rows, list) and any(
                    isinstance(row, dict)
                    and row.get("setup_id") == sid
                    and (not separator or str(row.get("op_id")) == op)
                    for row in rows
                )
        return node.attrs.get("data-scope") == subject

    def modern(node, finding):
        kinds = {"block"} if finding["status"] == "error" else {"block", "caution"}
        decision = node.attrs.get("data-decision")
        if (
            "decision" not in node.classes
            or decision not in kinds
            or ("stop" if decision == "block" else "caution") not in node.classes
            or node.attrs.get("data-status")
            not in (
                {"error"} if finding["status"] == "error" else {"unknown", "unsupported", "error"}
            )
        ):
            return False
        evidence = decoded(node.attrs, "data-decision-evidence")
        if "data-decision-evidence" not in node.attrs:
            evidence = [
                {
                    "source": node.attrs.get("data-source"),
                    "status": node.attrs.get("data-status"),
                    "scope": node.attrs.get("data-scope"),
                    "kind": node.attrs.get("data-decision"),
                }
            ]
        return isinstance(evidence, list) and any(
            isinstance(row, dict)
            and row.get("source") == finding["rule"]
            and row.get("status") == finding["status"]
            and row.get("scope") == finding["subject"]
            and row.get("kind") in kinds
            and owners(node, finding["subject"])
            for row in evidence
        )

    criterion_ancestors = {
        id(parent)
        for node in parser.nodes
        if "inspection-criterion" in node.classes
        for parent in node.ancestors
    }

    requirement_names = set(TOLERANCE_REQUIREMENTS) | set(SHEET_REQUIREMENTS)
    requirement_names.update(
        finding["subject"].rsplit(":", 1)[-1]
        for finding in report["findings"]
        if finding["rule"] == "inspection"
    )
    requirement_labels = {
        SHEET_REQUIREMENTS.get(name, name.replace("_", " ")) for name in requirement_names
    }
    requirement_labels |= {label + " ref" for label in requirement_labels}

    def inspection_identity(finding):
        """Distinguish dimension/acceptance identities from setup:op process holds."""
        numbers = finding.get("numbers", {})
        identity = numbers.get("identity")
        if isinstance(identity, dict):
            return identity
        subject = finding["subject"]
        if ":" not in subject:
            return None
        feature, requirement = subject.rsplit(":", 1)
        if requirement.isdigit():
            return None
        return {"feature_owner": feature, "requirement": requirement, "workpiece": None}

    def shop_name(feature):
        feature = re.sub(r"_pos_([xyz])$", lambda m: f" (+{m[1].upper()} side)", feature)
        feature = re.sub(r"_neg_([xyz])$", lambda m: f" (−{m[1].upper()} side)", feature)
        feature = re.sub(r"_datum_([a-z])$", lambda m: f" (datum {m[1].upper()})", feature)
        return feature.replace("_", " ")

    def inspection_criterion(node, finding, identity):
        """Parse a full criterion heading; never search for an owner's word suffix."""
        ancestry = (node, *reversed(node.ancestors))
        semantic = "inspection-criterion" in node.classes
        if semantic and "data-inspection-ids" not in node.attrs:
            return False
        if not semantic and not (
            node.tag == "tr"
            or node.tag == "p"
            and any(
                parent.classes & {"route-inspection", "setup-variant"} for parent in node.ancestors
            )
        ):
            return False
        # Once explicit criterion boundaries exist, an ancestor must not combine
        # their text or identities back into one permissive disclosure candidate.
        if not semantic and id(node) in criterion_ancestors:
            return False
        records = [parent for parent in ancestry if "data-inspection-ids" in parent.attrs]
        subject = finding["subject"]
        if records and subject not in decoded(records[0].attrs, "data-inspection-ids"):
            return False
        workpiece = identity.get("workpiece")
        physical = next(
            (parent for parent in ancestry if "data-physical-ops" in parent.attrs), None
        )
        physical_rows = decoded(physical.attrs, "data-physical-ops") if physical else []
        physical_member = isinstance(physical_rows, list) and any(
            isinstance(row, dict) and row.get("workpiece") == workpiece for row in physical_rows
        )
        if workpiece and (
            not records
            or physical is not None
            and not physical_member
            or not (
                physical_member
                or any(parent.attrs.get("data-workpiece") == workpiece for parent in ancestry)
            )
        ):
            return False
        if any(
            parent.attrs.get("data-workpiece")
            and parent.attrs["data-workpiece"] != (workpiece or "")
            for parent in ancestry
        ):
            return False
        feature = identity.get("feature_owner")
        requirement = identity.get("requirement")
        if not isinstance(requirement, str):
            return False
        label = SHEET_REQUIREMENTS.get(requirement, requirement.replace("_", " "))

        def owns(heading):
            if feature is None:
                return bool(records) and not heading
            owners = [" ".join(owner.split()).casefold() for owner in heading.split(",")]
            return shop_name(feature).casefold() in owners

        text = " ".join(" ".join(node.text).split())
        if re.match(r"PROCESS\s+HOLD\b", text, re.I):
            return False
        marker = r"(?:\?|unknown\b|unverified\b|not\s+set\b)"
        # Pedantic: the entire owner list precedes the dash and the marker.
        pedantic = re.fullmatch(rf"(.+?)\s+[—–]\s+{marker}\s+(.+)", text, re.I)
        if pedantic:
            owners_text, criterion = pedantic.groups()
            if not re.match(rf"{re.escape(label)}(?:\s+|:\s*)\S", criterion, re.I):
                return False
            # String-valued bands and '(no drawing limit)' are real criteria.
            # Reject a longer registered requirement, not every nonnumeric value.
            if any(
                other.casefold().startswith(label.casefold() + " ")
                and re.match(rf"{re.escape(other)}(?:\s|:|$)", criterion, re.I)
                for other in requirement_labels
            ):
                return False
        else:
            # Compact: an optional gauge prefix, then marker + complete heading.
            compact = re.fullmatch(rf"(?:[^:]+:\s*)?{marker}\s+(.+)", text, re.I)
            if compact:
                criterion = compact[1]
                header = re.split(r"\s+(?=[+-]?\d|\?)|:", criterion, maxsplit=1)[0]
                if header == criterion:
                    return False
                suffix = " " + label
                if header.casefold().endswith(suffix.casefold()):
                    owners_text = header[: -len(suffix)]
                elif (
                    feature
                    and re.split(r"[-_\s]+", shop_name(feature))[-1].casefold() == label.casefold()
                ):
                    # The renderer elides a redundant 'length' in 'end-length'.
                    owners_text = header
                elif feature is None and header.casefold() == label.casefold():
                    owners_text = ""
                else:
                    return False
            else:
                # Historical table cells: owner, requirement, trailing marker.
                # Require an actual end/separator after it, not the next
                # criterion's leading '? owner ...'.
                historical = re.fullmatch(
                    rf"(.+?)\s+{re.escape(label)}\s*{marker}(?:\s*;.*)?",
                    text,
                    re.I,
                )
                if not historical or node.tag != "tr":
                    return False
                owners_text = historical[1]
        return owns(owners_text)

    def legacy(node, finding):
        if finding["status"] == "unknown" and finding["rule"] == "inspection":
            identity = inspection_identity(finding)
            if identity is not None:
                return inspection_criterion(node, finding, identity)
        wanted = "stop" if finding["status"] == "error" else "unverified"
        if wanted not in node.classes or "decision" in node.classes:
            return False
        text = " ".join(node.text)
        topic = SHEET_TOPICS.get(finding["rule"], finding["rule"].replace("_", " "))
        if finding["status"] == "unknown" and normalized(topic) not in normalized(text):
            if finding["rule"] != "zero_check" or not re.search(
                r"(?:handwheel|readout).*zero", text, re.I
            ):
                return False
        sid, separator, op = finding["subject"].partition(":")
        sections = [parent for parent in reversed(node.ancestors) if parent.tag == "section"]
        context = (
            sections[0]
            if sections
            else next((parent for parent in node.ancestors if parent.tag == "body"), node)
        )
        context_text = " ".join(context.text)
        setup_scope = (
            context.attrs.get("data-setup-id") == sid
            or re.search(rf"\bSETUPS?\s+{re.escape(sid)}\b", context_text, re.I) is not None
        )
        if setup_scope:
            return (
                not separator
                or re.search(
                    rf"\b(?:all\s+(?:cutting\s+)?ops|ops?\s+(?:\d+\s*[,/–-]\s*)*{re.escape(op)}\b)",
                    text,
                    re.I,
                )
                is not None
            )
        if separator and op.isdigit():
            return False  # An unrelated setup's box cannot disclose this physical op.
        # Legacy feature maps may be on a continuation of the same printed setup.
        title = re.search(r"\bSETUP\s+([A-Za-z0-9_-]+)\b", context_text, re.I)
        if title:
            heading = rf"\bSETUP\s+{re.escape(title[1])}\b"
            context_text += " " + " ".join(
                " ".join(section.text)
                for section in parser.nodes
                if section.tag == "section"
                and not section.hidden
                and re.search(heading, section.attrs.get("data-title", ""), re.I)
                and re.search(heading, " ".join(section.text), re.I)
            )
        # Job/setup boxes cover explicitly named features and requirements, not any '?'.
        return re.search(
            rf"\b{re.escape(normalized(sid))}\b", normalized(context_text)
        ) is not None and (not separator or normalized(op) in normalized(context_text))

    for finding in report["findings"]:
        if finding["status"] not in {"unknown", "error"}:
            continue
        words = error_words if finding["status"] == "error" else unknown_words
        require(
            any(
                not node.hidden
                and words.search(" ".join(node.text))
                and not cleared_words.search(" ".join(node.text))
                and (modern(node, finding) or legacy(node, finding))
                for node in parser.nodes
            ),
            f"sheet hides {finding['status']} disclosure for "
            f"{finding['rule']}:{finding['subject']}",
        )


def check_sheet(folder: Path, report: dict, expected_subdir: str = "expected") -> None:
    html = (folder / expected_subdir / "traveler.html").read_text(encoding="utf-8")
    parser = SheetText(html)
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
    check_sheet_disclosures(parser, report)


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


def check_indexing(setup: dict, features: dict, entries: Entries, finding: dict) -> None:
    hold = setup.get("hold")
    declaration = hold.get("index") if isinstance(hold, dict) else "unknown"
    if declaration is None:
        require(finding["status"] == "not_applicable", "undeclared indexing must be inapplicable")
        return
    declaration = declaration if isinstance(declaration, dict) else {}
    row = finding["numbers"]
    reference = declaration.get("fixture", "unknown")
    item = entries.item(reference, "workholding")
    kind = item.get("kind", "unknown") if item is not None else "unknown"
    invalid = (item is None and reference != "unknown") or kind not in {"dividing_head", "unknown"}
    unresolved = item is None or kind == "unknown" or entries.uncertain(reference, "workholding")
    same(row.get("fixture"), reference, "indexing fixture")
    require(
        row.get("verified")
        == (item is not None and not entries.uncertain(reference, "workholding")),
        "indexing fixture verification",
    )
    if "rotation" in declaration:
        rotation = declaration["rotation"]
        same(row.get("rotation"), rotation, "indexing rotation")
        invalid |= rotation not in {"continuous", "unknown"} or any(
            key in declaration for key in ("positions", "angle_deg")
        )
        unresolved |= rotation == "unknown"
        require(
            not {"actual_angle_deg", "position_errors_deg", "closure"} & row.keys(),
            "continuous indexing has no angular landings",
        )
        status = "error" if invalid else "unknown" if unresolved else "pass"
        require(finding["status"] == status, "continuous indexing verdict differs from its inputs")
        return
    item = item or {}
    positions = declaration.get("positions", "unknown")
    count_known = isinstance(positions, int) and not isinstance(positions, bool) and positions >= 1
    invalid |= positions != "unknown" and not count_known
    unresolved |= positions == "unknown"
    full_pattern = count_known and positions >= 2 and "angle_deg" not in declaration
    angle = declaration.get("angle_deg")
    requested = (
        Fraction(360, positions)
        if full_pattern
        else Fraction(str(angle))
        if numeric(angle)
        else None
    )
    unresolved |= requested is None
    name = declaration.get("feature", "unknown")
    definitions = features.get("features", {})
    feature = definitions.get(name, {}) if "feature" in declaration else {}
    invalid |= name != "unknown" and name not in definitions
    tolerance = (
        "unknown"
        if declaration.get("feature") == "unknown"
        else feature.get(
            "angle_tol_deg",
            "unknown"
            if feature.get("dimension_type") == "basic"
            else features.get("general_tolerances", {}).get("angular_deg", "unknown"),
        )
    )
    limit = Fraction(str(tolerance)) if numeric(tolerance) else None
    invalid |= limit is not None and limit < 0
    unresolved |= limit is None
    for key, expected in {
        "feature": name,
        "positions": positions,
        "requested_angle_fraction": str(requested) if requested is not None else "unknown",
        "requested_angle_deg": float(requested) if requested is not None else "unknown",
        "tolerance_deg": float(limit) if limit is not None and limit >= 0 else "unknown",
    }.items():
        same(row.get(key), expected, f"indexing {key}")
    options, circles = [], []
    missing, broken = False, False
    direct = item.get("direct_index", {})
    if direct == "unknown":
        missing = True
    elif isinstance(direct, dict) and direct:
        count, step = direct.get("positions"), direct.get("step_deg")
        missing |= count == "unknown" or step == "unknown"
        count = Fraction(str(count)) if numeric(count) else None
        step = Fraction(str(step)) if numeric(step) else None
        if count is None and step is None:
            missing = True
        elif (count is not None and (count <= 0 or count.denominator != 1)) or (
            step is not None and step <= 0
        ):
            broken = True
        else:
            count = count if count is not None else 360 / step
            step = step if step is not None else 360 / count
            if count.denominator != 1 or count * step != 360:
                broken = True
            else:
                circles.append(("direct", "direct", int(count), Fraction(1)))
    plates = item.get("plate_holes", "unknown")
    ratio = item.get("worm_ratio")
    ratio = Fraction(str(ratio)) if numeric(ratio) else None
    if not isinstance(plates, dict):
        missing = True
    elif plates:
        missing |= ratio is None
        broken |= ratio is not None and ratio <= 0
        for plate, holes in plates.items():
            if not isinstance(holes, list):
                missing = True
                continue
            for hole in holes:
                if not numeric(hole):
                    missing = True
                elif hole <= 0 or Fraction(str(hole)).denominator != 1:
                    broken = True
                elif ratio is not None and ratio > 0:
                    circles.append(("worm", plate, int(hole), ratio))
    # Exhaust every space around the requested revolution, rather than sharing the rule's
    # nearest-count helper. Equal signed half-steps choose the lower signed count.
    if requested is not None:
        for method, plate, circle, multiplier in circles:
            central = int(abs(requested) * multiplier / 360)
            for turns in range(max(0, central - 1), central + 2):
                for spaces in range(circle):
                    for sign in (-1, 1):
                        count = sign * (turns * circle + spaces)
                        actual = Fraction(360 * count, circle) / multiplier
                        options.append(
                            (
                                abs(actual - requested),
                                method != "direct",
                                plate,
                                circle,
                                count,
                                actual,
                                method,
                                turns,
                                spaces,
                            )
                        )
        require(
            row.get("selection_complete") == (not missing and not broken),
            "indexing selection completeness",
        )
        invalid |= broken
        unresolved |= missing or not options
    else:
        require(row.get("selection_complete") is False, "unknown request has no selection")
    failed = False
    if options:
        _, _, plate, circle, count, actual, method, turns, spaces = min(options)
        for key, expected in {
            "method": method,
            "plate": plate,
            "circle": circle,
            "turns": turns,
            "spaces": spaces,
            "direction": "reverse" if count < 0 else "forward",
            "exact": actual == requested,
            "actual_angle_deg": float(actual),
            "step_error_deg": float(actual - requested),
        }.items():
            same(row.get(key), expected, f"indexing {key}")
        errors = (
            [(actual - requested) * position for position in range(1, positions + 1)]
            if count_known
            else []
        )
        near_values(
            row.get("position_errors_deg"),
            list(map(float, errors)),
            "indexing signed landing errors",
        )
        same(
            row.get("max_position_error_deg"),
            float(max(map(abs, errors))) if errors else "unknown",
            "indexing maximum landing error",
        )
        failed = limit is not None and limit >= 0 and any(abs(error) > limit for error in errors)
        if full_pattern:
            total = positions * actual
            lower = total // 360
            revolutions = min((lower, lower + 1), key=lambda k: (abs(total - 360 * k), k))
            closure_error = total - 360 * revolutions
            within = abs(closure_error) <= limit if limit is not None and limit >= 0 else "unknown"
            closure = row.get("closure")
            require(isinstance(closure, dict), "indexing full-pattern closure missing")
            for key, expected in {
                "revolutions": revolutions,
                "target_angle_deg": 360 * revolutions,
                "actual_angle_deg": float(total),
                "error_deg": float(closure_error),
                "within_tolerance": within,
            }.items():
                same(closure.get(key), expected, f"indexing closure {key}")
            failed |= within is False
    else:
        for key in (
            "actual_angle_deg",
            "method",
            "plate",
            "circle",
            "turns",
            "spaces",
            "direction",
            "exact",
        ):
            same(row.get(key), "unknown", f"unresolved indexing {key}")
        near_values(row.get("position_errors_deg"), [], "unresolved indexing landings")
        same(row.get("max_position_error_deg"), "unknown", "unresolved indexing maximum error")
        if full_pattern:
            same(row.get("closure"), "unknown", "unresolved indexing cycle closure")
    if not full_pattern:
        same(
            row.get("closure"),
            "not_applicable" if "angle_deg" in declaration or positions == 1 else "unknown",
            "indexing open-pattern closure",
        )
    status = "error" if invalid else "unknown" if unresolved else "error" if failed else "pass"
    require(
        finding["status"] == status,
        f"{setup['id']}: indexing verdict is not the {status} its inputs decide",
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
    """The declared held-stock OD: the setup's ``od_mm``, else the plan stock's
    ``dia_mm`` unless its form is marked for verification. An omitted stock state uses
    that fallback; an explicitly unknown state or OD does not. Only positive numbers
    count, and a nominal declaration is not evidence of a measured physical diameter."""
    state = setup.get("stock_state")
    if state == "unknown":
        return "unknown"
    state = state if isinstance(state, dict) else {}
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
    kind = machine_record(setup, Entries(inventory)).get("kind", "unknown")
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
    fit = setup["hold"].get("stickout_fit")
    if isinstance(fit, dict) and fit and status != "not_applicable":
        expected = {
            "measure": fit.get("measure", "unknown"),
            "nominal_mm": fit.get("nominal_mm", "unknown"),
            "add_mm": fit.get("add_mm", "unknown"),
            "stickout_mm": length,
        }
        require(isinstance(row.get("stickout_fit"), dict), "stick-out fit evidence missing")
        for key, value in expected.items():
            same(row["stickout_fit"].get(key), value, f"stick-out fit {key}")
        settled = all(map(numeric, (expected["nominal_mm"], expected["add_mm"], length)))
        stated = isinstance(expected["measure"], str) and expected["measure"].strip()
        stated = stated and expected["measure"] != "unknown"
        fit_status = (
            "error"
            if settled and not same_length(expected["nominal_mm"] + expected["add_mm"], length)
            else "unknown"
            if not (settled and stated)
            else "pass"
        )
        status = max((status, fit_status), key=STATUS_RANK.get)
    else:
        require(
            "stickout_fit" not in row, "stick-out fit evidence without an applicable declaration"
        )
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


def check_fixture_semantics(
    plan_path: Path,
    plan: dict,
    features: dict,
    inventory: dict,
    policy: dict,
    cutting: dict,
    findings: dict,
) -> list:
    """Independent authored-input arithmetic shared by consumer and standalone examples."""
    entries = Entries(inventory)
    check_construction(plan, features, findings["construction", plan["part"]])
    check_frames(features, plan)
    check_subjects(plan, features, findings, inventory)
    checked = checker_findings(plan_path)
    check_required_coverage(policy, plan, features, findings, entries, checked)
    check_inspection_declarations(plan, features, findings)
    kernel = independent_kernel(plan_path)
    check_joint_declarations(plan, features, findings, kernel)
    missing = check_references(plan, features, entries, findings)
    missing += check_prepared_blank(plan, features, inventory, findings, kernel)
    depths = check_endpoints(plan, features, findings, entries, kernel)
    definitions = operative_definitions(plan, features)
    own = functools.cache(lambda: zero_inputs(plan, features, inventory, policy, kernel))
    for setup in plan["setups"]:
        if manual_bench(inventory, setup) is None and manual_thread_facts(inventory, setup) is None:
            if not saw_setup(inventory, setup):
                check_zero(setup, findings["zero_check", setup["id"]], entries, own())
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
    return missing


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
    report = read_report(folder / expected_subdir / "report.json")
    renders = report.get("renders", {})
    # Every image the report binds: each setup's render and each inspection sketch it
    # carries, a PNG in the expected folder under its own input key.
    images = {f"render:{sid}": asset for sid, asset in renders.items()}
    images |= {
        f"render:{sid}:{key}": sketch
        for sid, asset in renders.items()
        for key, sketch in asset.get("inspections", {}).items()
    }
    require(set(report["inputs"]) == set(paths) | set(images), "report input bundle incomplete")
    for key, asset in images.items():
        image = folder / expected_subdir / asset["path"]
        require(image.read_bytes().startswith(b"\x89PNG\r\n\x1a\n"), "invalid fixture PNG")
        require(asset["sha256"] == sha256(image), "fixture render hash mismatch")
        require(
            report["inputs"][key] == {"path": asset["path"], "sha256": asset["sha256"]},
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
    if part == "cone-pivot-post":
        check_cone_facts(plan, features)
    missing = check_fixture_semantics(
        folder / plan_filename, plan, features, inventory, policy, cutting, findings
    )
    exit_code = report_exit(report, policy, plan, features)
    candidate = part if plan_filename == "plan.toml" else f"{part}/{plan_filename}"
    require(
        exit_code == report["expected_exit"] == EXPECTED_EXIT[candidate],
        f"{candidate}: expected exit mismatch ({exit_code})",
    )
    check_sheet(folder, report, expected_subdir)
    return exit_code, missing


def check_step_face_references(step: Path, plan: dict, features: dict) -> None:
    """Resolve authored finished-face identities against the adjacent STEP bytes."""
    records = re.findall(
        r"#(\d+)\s*=\s*ADVANCED_FACE\s*\(\s*'((?:[^']|'')*)'",
        step.read_text(encoding="utf-8"),
        re.DOTALL,
    )
    require(records, f"{step.name}: no ADVANCED_FACE records")
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
        require(match is not None, f"{step.name}: malformed face reference {ref}")
        entity, ordinal, label = match.groups()
        require(0 < int(ordinal) <= len(records), f"{step.name}: invalid face ordinal {ref}")
        actual_entity, actual_label = records[int(ordinal) - 1]
        require(
            (entity, label) == (actual_entity, actual_label.replace("''", "'")),
            f"{step.name}: face reference differs from bound STEP {ref}",
        )


def validate_standalone_fixture(case: tuple) -> None:
    """Validate local authored inputs, including disclosed demonstration measurements."""
    part, plan_filename, expected_subdir, expected_exit = case
    folder = (EXAMPLES / part).resolve()
    bundle = load_bundle(folder / plan_filename)
    plan, features = bundle.plan, bundle.features
    require(plan["part"] == features["part"] == part, "part identity mismatch")
    paths = {key: path.resolve() for key, path in input_paths(folder, plan, plan_filename).items()}
    require(
        all(path.is_relative_to(folder) for path in paths.values()), "nonlocal standalone input"
    )
    require(paths["step"].parent == paths["features"].parent, "STEP is not adjacent to manifest")
    require(
        features["step_sha256"] == sha256(paths["step"]),
        f"{part}: STEP digest mismatch",
    )
    check_step_face_references(paths["step"], plan, features)
    report = read_report(folder / expected_subdir / "report.json")
    require(report["step_sha256"] == features["step_sha256"], "STEP report binding mismatch")
    images = {f"render:{sid}": asset for sid, asset in report.get("renders", {}).items()}
    images |= {
        f"render:{sid}:{key}": sketch
        for sid, asset in report.get("renders", {}).items()
        for key, sketch in asset.get("inspections", {}).items()
    }
    require(set(report["inputs"]) == set(paths) | set(images), "report input bundle incomplete")
    for key, path in paths.items():
        require(
            report["inputs"][key]
            == {"path": path.relative_to(ROOT).as_posix(), "sha256": sha256(path)},
            f"{part}: stale {key} input binding",
        )
    expected = (folder / expected_subdir).resolve()
    for key, asset in images.items():
        image = (expected / asset["path"]).resolve()
        require(image.is_relative_to(expected), "render path escapes")
        require(image.read_bytes().startswith(b"\x89PNG\r\n\x1a\n"), "invalid fixture PNG")
        require(
            asset["sha256"] == sha256(image)
            and report["inputs"][key] == {"path": asset["path"], "sha256": asset["sha256"]},
            "fixture render not bound to report",
        )
    findings = {(row["rule"], row["subject"]): row for row in report["findings"]}
    check_fixture_semantics(
        folder / plan_filename,
        plan,
        features,
        bundle.inventory,
        bundle.policy,
        bundle.cutting_data,
        findings,
    )
    checked = checker_findings(folder / plan_filename)
    for rule in CHECKER_RULES:
        for subject, row in checked(rule).items():
            require(
                findings.get((rule.name, subject)) == row,
                f"{part}: stale {rule.name}:{subject} finding",
            )
    require(
        report_exit(report, bundle.policy, plan, features)
        == report["expected_exit"]
        == expected_exit,
        f"{part}: expected exit mismatch",
    )
    check_sheet(folder, report, expected_subdir)


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
    check_step_face_references(paths["step"], plan, features)
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
            kinds = [Entries(inventory).record(fixture, "workholding").get("kind")]
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
    findings = {(row["rule"], row["subject"]): row for row in report["findings"]}
    checked = checker_findings(folder / plan_filename)
    check_required_coverage(policy, plan, features, findings, Entries(inventory), checked)
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
        for path, document in documents.items():
            if any(
                key in document for key in ("machines", "tools", "holders", "fixtures", "gauges")
            ):
                check_inventory_provenance(path.read_text(encoding="utf-8"), str(path))
        check_example_measurements(
            documents[(EXAMPLES / "inventory" / "pedro-shop.toml").resolve()],
            {
                path.relative_to(EXAMPLES).as_posix(): document
                for path, document in documents.items()
                if "setups" in document
            },
        )
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
        for case in STANDALONE_CASES:
            validate_standalone_fixture(case)
            print(f"{case[0]}/{case[1]}: expected exit {case[3]}")
        print("All rev-6 reference bundles validate.")
        return 0
    except (BadInput, OSError, ValueError, KeyError, TypeError, StopIteration) as exc:
        print(f"Example validation failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
