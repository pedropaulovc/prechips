"""Declared holding completeness, not certification of fixture geometry (PLAN §4.1)."""

from prechips.findings import Finding
from prechips.rules.resolution import MANUAL, UNKNOWN, resolve
from prechips.rules.tip_endpoints import HOLE_OPS

# Point/hole actions plunge on the spindle axis; every other machine cut needs a direction.
_POINT = HOLE_OPS | {"center"}


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
        fixture = resolve(bundle, "fixtures", hold.get("fixture")) or {}
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
        for key in ("supports", "support_orientation", "parallels", "jaws_along", "locate"):
            if key in hold:
                required[f"hold.{key}"] = hold[key]
        directions = {}
        for op in setup["ops"]:
            if op["do"] in MANUAL:
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
        findings.append(
            Finding(
                "hold_fields", setup["id"], status, numbers, ["PLAN.md §4.1 hold fields"], message
            )
        )
    return findings
