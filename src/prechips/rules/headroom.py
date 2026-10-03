"""Mill stack and nominal jaw/travel checks; unmeasured geometry never passes.

The 25 mm insertion allowance is PLAN §4.1's tool-change allowance, not
holder grip. Jaw height is an obstruction, never a spindle-stack layer.
"""

from fractions import Fraction

from prechips.findings import Finding
from prechips.rules.resolution import MANUAL, length_mm, resolve, uncertain


_UNKNOWN = "unknown"


def _numeric(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _sum(*values):
    return sum(values) if all(_numeric(value) for value in values) else _UNKNOWN


def _height(item, orientation=None):
    if not item:
        return _UNKNOWN
    height = length_mm(item, "height")
    if _numeric(height):
        return height
    # Blocks have three different dimensions: use only the authored orientation.
    if isinstance(orientation, str) and orientation.endswith(" in height"):
        try:
            selected = float(Fraction(orientation.removesuffix(" in height")))
        except (ValueError, ZeroDivisionError):
            return _UNKNOWN
        if selected in item.get("size_in", []):
            return selected * 25.4
    return _UNKNOWN


def _mapping(value):
    return value if isinstance(value, dict) else {}


def evaluate(bundle):
    findings = []
    for setup in bundle.plan["setups"]:
        machine = resolve(bundle, "machines", setup["machine"]) or {}
        if machine.get("kind") == "lathe":
            findings.append(Finding("headroom", setup["id"], "unsupported", {}, ["PLAN.md §4.1 headroom"], "Lathe headroom is outside the mill-only M1 envelope rule."))
            continue
        hold = _mapping(setup.get("hold"))
        state = _mapping(setup.get("stock_state"))
        fixture = resolve(bundle, "fixtures", hold.get("fixture")) or {}
        parallels_ref = hold.get("parallels")
        parallels = resolve(bundle, "fixtures", parallels_ref) or {}
        parallel_height = 0 if parallels_ref in (None, "none", "not_applicable") else _height(parallels)
        support_ref = hold.get("supports", hold.get("riser"))
        support = resolve(bundle, "fixtures", support_ref) or {}
        support_height = 0 if support_ref in (None, "none", "not_applicable") else _height(support, hold.get("support_orientation"))
        # The legacy riser declaration selects a 1-in block; without an explicit
        # orientation preserve the unknown rather than inventing a stack height.
        bottom = state.get("retained_rail_bottom_z", state.get("bottom_z", _UNKNOWN))
        top = state.get("top_z", _UNKNOWN)
        stock_height = top - bottom if _numeric(top) and _numeric(bottom) else _UNKNOWN
        bed = length_mm(fixture, "bed_height")
        jaw = length_mm(fixture, "jaw_height")
        spindle = length_mm(machine, "spindle_to_table_max")
        numbers = {"bed_height_mm": bed, "fixture_height_mm": jaw,
                   "fixture_verify": uncertain(fixture) if fixture else "missing",
                   "parallels_mm": parallel_height if parallels_ref not in (None, "none", "not_applicable") else "not_applicable",
                   "support_blocks_mm": support_height, "stock_top_z": top,
                   "stock_bottom_z": state.get("bottom_z", _UNKNOWN),
                   "retained_rail_bottom_z": bottom, "stock_height_mm": stock_height,
                   "raw_rail_thickness_mm": stock_height, "insertion_mm": 25,
                   "spindle_to_table_max_mm": spindle, "spindle_verify": uncertain(machine),
                   "tool_oal_mm": _UNKNOWN, "holder_gauge_len_mm": _UNKNOWN, "sum_mm": _UNKNOWN,
                   "travel_in": machine.get("travel_in", {}), "stacks": [],
                   "clearance_basis": "nominal input geometry; verification flags are measurement debt"}
        unknown = not fixture or not machine or any(uncertain(item) for item in (machine, fixture, parallels, support) if item)
        unknown |= not _numeric(stock_height) or (fixture.get("kind") == "vise" and not _numeric(jaw))
        errors = []
        if _numeric(stock_height) and stock_height <= 0:
            errors.append("supported stock height is not positive")
        nominal_stacks, oals, gauges = [], [], []
        for op in setup["ops"]:
            if op["do"] in MANUAL:
                continue
            tool = resolve(bundle, "tools", op.get("tool")) or {}
            holder = resolve(bundle, "holders", op.get("holder")) or {}
            oal, gauge = length_mm(tool, "oal"), length_mm(holder, "gauge_len")
            projection = length_mm(tool, "projection")
            if not _numeric(projection):
                grip = length_mm(holder, "grip")
                projection = oal - grip if _numeric(oal) and _numeric(grip) else _UNKNOWN
            stack = _sum(bed, parallel_height, support_height, stock_height, projection, gauge, 25)
            margin = spindle - stack if _numeric(spindle) and _numeric(stack) else _UNKNOWN
            verified = not any(uncertain(item) for item in (machine, fixture, parallels, support, tool, holder) if item) and bool(tool and holder and fixture)
            numbers["stacks"].append({"op": op["op"], "tool": op.get("tool", _UNKNOWN), "holder": op.get("holder", _UNKNOWN),
                                      "tool_oal_mm": oal, "tool_projection_mm": projection, "holder_gauge_len_mm": gauge,
                                      "sum_mm": stack, "margin_mm": margin, "verify": not verified})
            unknown |= not verified or not _numeric(margin)
            if verified and _numeric(margin) and margin < 0:
                errors.append(f"op {op['op']} exceeds spindle clearance by {-margin:g} mm")
            if _numeric(stack):
                nominal_stacks.append(stack)
            if _numeric(oal):
                oals.append(oal)
            if _numeric(gauge):
                gauges.append(gauge)
        if numbers["stacks"] and len(nominal_stacks) == len(numbers["stacks"]):
            numbers["sum_mm"] = max(nominal_stacks)
        if oals and len(oals) == len(numbers["stacks"]):
            numbers["tool_oal_mm"] = max(oals)
        if gauges and len(gauges) == len(numbers["stacks"]):
            numbers["holder_gauge_len_mm"] = max(gauges)
        support_stack = _sum(parallel_height, support_height)
        jaw_top_z = bottom + jaw - support_stack if all(_numeric(v) for v in (bottom, jaw, support_stack)) else _UNKNOWN
        top_clearance = top - jaw_top_z if _numeric(top) and _numeric(jaw_top_z) else _UNKNOWN
        cuts = {str(op["op"]): op["to_z"] - jaw_top_z for op in setup["ops"] if _numeric(op.get("to_z")) and _numeric(jaw_top_z)}
        numbers.update({"stock_top_above_jaws_mm": top_clearance, "cut_tip_above_jaws_mm": cuts,
                        "jaw_obstruction": {"jaw_top_z": jaw_top_z, "requires_path_check": any(value < 0 for value in cuts.values())}})
        # A below-jaw endpoint is not proof of a collision: lateral keep-outs
        # require geometry. Report separately without pretending the stack fails.
        unknown |= any(value < 0 for value in cuts.values())
        stock = _mapping(bundle.plan.get("stock"))
        section = stock.get("section_mm", [])
        stock_x, stock_y = stock.get("length_mm", _UNKNOWN), section[0] if isinstance(section, list) and section else _UNKNOWN
        frame = _mapping(_mapping(bundle.features.get("frames")).get(setup.get("frame")))
        axes = [frame.get("x"), frame.get("y")]
        extents = [stock_x, stock_y, section[1] if isinstance(section, list) and len(section) > 1 else _UNKNOWN]
        # Transform the stock box dimensions into the actual setup frame.
        if all(_numeric(value) for value in extents) and all(isinstance(axis, list) and len(axis) == 3 and all(_numeric(value) for value in axis) for axis in axes):
            stock_x, stock_y = [sum(abs(axis[i]) * extents[i] for i in range(3)) for axis in axes]
        numbers.update({"stock_extent_x_mm": stock_x, "stock_extent_y_mm": stock_y})
        travels = {}
        for axis, extent in (("x", stock_x), ("y", stock_y)):
            travel = _mapping(machine.get("travel_mm")).get(axis, _UNKNOWN)
            if not _numeric(travel):
                inches = _mapping(machine.get("travel_in")).get(axis, _UNKNOWN)
                travel = inches * 25.4 if _numeric(inches) else _UNKNOWN
            fixture_extent = length_mm(fixture, "length" if axis == "x" else "width")
            required = max(extent, fixture_extent) if _numeric(extent) and _numeric(fixture_extent) else _UNKNOWN
            travels[axis] = {"travel_mm": travel, "part_mm": extent, "fixture_mm": fixture_extent, "required_mm": required}
            unknown |= not _numeric(required) or not _numeric(travel)
            if not uncertain(machine) and not uncertain(fixture) and _numeric(required) and _numeric(travel) and required > travel:
                errors.append(f"part/fixture envelope exceeds {axis.upper()} travel")
        numbers["travel_checks"] = travels
        profile_extents = [
            2 * abs(feature["radial_tip_end"][0])
            for feature in bundle.features.get("features", {}).values()
            if feature.get("mirror_symmetric") is True
            and isinstance(feature.get("radial_tip_end"), list)
            and feature["radial_tip_end"]
            and _numeric(feature["radial_tip_end"][0])
        ]
        if profile_extents:
            numbers["part_extent_x_mm"] = max(profile_extents)
        status = "error" if errors else "unknown" if unknown else "pass"
        sentence = f"{setup['id']}: " + ("; ".join(errors) if errors else "headroom, travel or jaw-path geometry remains unmeasured or unresolved" if unknown else "measured spindle stack and part/fixture travels fit") + "."
        findings.append(Finding("headroom", setup["id"], status, numbers, ["PLAN.md §4.1 headroom", "inventory: machine, fixture, support, tool and holder dimensions", "plan: stock state and setup frame"], sentence))
    return findings
