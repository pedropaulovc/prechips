"""Declared holding completeness, not certification of fixture geometry (PLAN §4.1).

A declared ``hold.stop_face`` must exist on the stock as it arrives: ``"stock_end"``, a
face the raw stock supplies as-is, or a feature an earlier setup in this setup's stock
lineage has cut. A stop against a face cut only later is an error.
"""

from prechips.findings import Finding
from prechips.joint_features import _lineage
from prechips.rules.resolution import (
    MANUAL,
    SAW_OPS,
    UNKNOWN,
    known_refs,
    op_feature,
    owns_feature,
    record,
    resolve,
    workholding_category,
)
from prechips.rules.tip_endpoints import HOLE_OPS

# Point/hole actions plunge on the spindle axis; every other machine cut needs a direction.
_POINT = HOLE_OPS | {"center"}
STOCK_END = "stock_end"


def stop_face(bundle, setup, name):
    """``(status, facts)`` for a stop face on this setup's arriving stock.

    A lineage cut of explicitly unknown action, or undeclared as-is stock faces, may have
    made the face: unknown.
    """
    if name == STOCK_END:
        return "pass", {"face": name, "on_arriving_stock": True}
    earlier = _lineage(bundle.plan, setup["id"]) - {setup["id"]}
    before, pending, later = [], [], []
    for other in bundle.plan["setups"]:
        for op in other["ops"]:
            action = op.get("do", UNKNOWN)
            if action in MANUAL or action == "transfer":
                continue
            if op_feature(op) != name and not owns_feature(bundle, op, name):
                continue
            cut = f"{other['id']} op {op['op']}"
            if other["id"] not in earlier:
                later.append(cut)
            else:
                (pending if action == UNKNOWN else before).append(cut)
    faces = record(bundle.feature_definitions.get(name)).get("faces", UNKNOWN)
    as_is = record(bundle.plan.get("stock")).get("as_is_faces", UNKNOWN)
    settled = known_refs(faces) and isinstance(as_is, list)
    supplied = settled and set(faces) <= set(as_is)
    facts = {"face": name, "cut_before": before, "cut_later": later, "as_is": supplied}
    if before or supplied:
        return "pass", {**facts, "on_arriving_stock": True}
    if pending or not settled:
        return "unknown", {**facts, "on_arriving_stock": UNKNOWN}
    return "error", {**facts, "on_arriving_stock": False}


def evaluate(bundle):
    findings = []
    for setup in bundle.plan["setups"]:
        hold = setup.get("hold", {})
        state = setup.get("stock_state", {})
        unknown_hold = hold == "unknown"
        unknown_state = state == "unknown"
        hold = hold if isinstance(hold, dict) else {}
        state = state if isinstance(state, dict) else {}
        machines = bundle.inventory.get("machines", {})
        machine = machines.get(setup["machine"], {}) if isinstance(machines, dict) else {}
        machine = machine if isinstance(machine, dict) else {}
        lathe = machine.get("kind") == "lathe"
        required = {
            "hold.fixture": hold.get("fixture"),
            "hold.stop": hold.get("stop"),
            "hold.grip_mm": hold.get("grip_mm"),
            "hold.clamp": hold.get("clamp"),
            "coolant": setup.get("coolant"),
            "deburr_mm": setup.get("deburr_mm"),
        }
        fixture_ref = hold.get("fixture")
        fixture = resolve(bundle, workholding_category(bundle, fixture_ref), fixture_ref) or {}
        if fixture.get("kind") == "vise" or (
            not lathe and hold.get("fixed_jaw") != "not_applicable"
        ):
            required["hold.fixed_jaw"] = hold.get("fixed_jaw")
        if lathe:
            required.update(
                {
                    "stock_state.od_mm": state.get("od_mm"),
                    "hold.support": hold.get("support"),
                    "hold.grip_on": hold.get("grip_on"),
                }
            )
            for key in ("plain_end_z", "north_end_z", "south_end_z"):
                if key in state:
                    required[f"stock_state.{key}"] = state[key]
            if not any(key in state for key in ("plain_end_z", "north_end_z", "south_end_z")):
                required["stock_state.end_station"] = None
        else:
            required.update(
                {
                    "stock_state.top_z": state.get("top_z"),
                    "stock_state.bottom_z": state.get("bottom_z"),
                }
            )
        # Fixture-specific declarations already present in the schema remain operative.
        for key in (
            "supports",
            "support_orientation",
            "parallels",
            "jaws_along",
            "locate",
            "stop_face",
        ):
            if key in hold:
                required[f"hold.{key}"] = hold[key]
        directions = {}
        for op in setup["ops"]:
            # A saw blade needs no holder and is located by its cut_plane, not a direction;
            # the setup's holding and stock facts above still apply.
            if op["do"] in MANUAL or op["do"] in SAW_OPS:
                continue
            required[f"ops.{op['op']}.holder"] = op.get("holder")
            if op["do"] not in _POINT or "direction" in op:
                # An explicitly unknown action cannot establish whether it needs a direction.
                fallback = UNKNOWN if op["do"] == UNKNOWN else None
                directions[str(op["op"])] = op.get("direction", "unknown")
                required[f"ops.{op['op']}.direction"] = op.get("direction", fallback)
        for key, value in required.items():
            if value is None and (
                (unknown_hold and key.startswith("hold."))
                or (unknown_state and key.startswith("stock_state."))
                or (machine.get("kind", "unknown") == "unknown" and key.startswith("stock_state."))
            ):
                required[key] = "unknown"
        absent = [key for key, value in required.items() if value is None or value == ""]
        unresolved = [key for key, value in required.items() if value == "unknown"]
        numbers = {
            "fixture": hold.get("fixture", "unknown"),
            "hold": dict(hold),
            "coolant": setup.get("coolant", "unknown"),
            "deburr_mm": setup.get("deburr_mm", "unknown"),
            "cut_directions": directions,
            "missing": absent + unresolved,
        }
        numbers.update(
            {
                f"stock_{key}": value
                for key, value in state.items()
                if key
                in ("top_z", "bottom_z", "od_mm", "north_end_z", "south_end_z", "plain_end_z")
            }
        )
        status = "error" if absent else "unknown" if unresolved else "pass"
        message = (
            (f"{setup['id']}: holding declarations need " + ", ".join(absent + unresolved) + ".")
            if absent or unresolved
            else (
                f"{setup['id']}: holding and cutting decisions are declared; "
                "this does not approve measured fixture clearance."
            )
        )
        face = hold.get("stop_face", UNKNOWN)
        if face != UNKNOWN:
            face_status, numbers["stop_face"] = stop_face(bundle, setup, face)
            if face_status == "error":
                later = numbers["stop_face"]["cut_later"]
                made = f"it is first cut in {later[0]}" if later else "no operation cuts it"
                status = "error"
                message = (
                    f"{setup['id']}: the hold stops on {face}, which the arriving stock does "
                    f"not have yet; {made}." + ("" if not (absent or unresolved) else " " + message)
                )
            elif face_status == "unknown" and status == "pass":
                status = "unknown"
                message = (
                    f"{setup['id']}: whether the arriving stock already has the stop face "
                    f"{face} is unresolved."
                )
        findings.append(
            Finding(
                "hold_fields", setup["id"], status, numbers, ["PLAN.md §4.1 hold fields"], message
            )
        )
    return findings
