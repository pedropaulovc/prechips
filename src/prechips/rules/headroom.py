"""Mill stack and nominal jaw/travel checks; lathe swing and length; unmeasured never passes.

The 25 mm insertion allowance is PLAN §4.1's tool-change allowance, not
holder grip. Jaw height is an obstruction, never a spindle-stack layer.
Machine limits are the measured ``envelope`` facts the M5 envelope and
travel screens read; a vendor number without a complete local measurement
keeps its nominal value in the numbers but can neither pass nor fail.
An authored tool/holder projection stays unknown when explicitly declared
unknown; OAL minus grip applies only when the selected pair has no entry.
A dividing head carries the work on its axis: the stock top above the table
is any declared parallels/supports plus the head's ``centre_height`` plus stock
``top_z`` minus the posed axis origin height (``hold.pose.origin_mm`` z); the
head's bed and jaw heights and the supported stock height do not enter it.
Saw-only setups have no spindle stack and are not applicable.

A lathe setup's envelope is its swing and length: the stock and chuck body
diameters against swing over the bed, the stock against swing over the cross
slide (the carriage passes under the whole turned length), and the stick-out
plus chuck body length against the distance between centres.  It is a
necessary-condition screen: it proves no tool path, carriage stroke or
tailstock quill extension.
"""

from fractions import Fraction

from prechips.findings import Finding
from prechips.measurements import length_fact, measurement_entry
from prechips.rules.resolution import (
    MANUAL,
    SAW_OPS,
    length_mm,
    resolve,
    saw_setup,
    setup_frame,
    uncertain,
    workholding_category,
)

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


def _head_axis_z(pose):
    """Setup-frame height of the posed dividing-head axis origin, else unknown."""
    origin = pose.get("origin_mm")
    if isinstance(origin, list) and len(origin) == 3 and all(_numeric(v) for v in origin):
        return origin[2]
    return _UNKNOWN


def _limit(machine, identity, field, debts, cite):
    """One measured machine envelope fact, with the same checklist id as envelope/travel."""
    result = length_fact(machine, field)
    cite.extend(result["cite"])
    cite.append(f"inventory.machines.{identity}.{field}")
    if not result["verified"]:
        entry = measurement_entry("machines", identity, field)
        debts[entry["id"]] = entry
    return result


def evaluate(bundle):
    findings = []
    for setup in bundle.plan["setups"]:
        machine_ref = setup["machine"]
        machine = resolve(bundle, "machines", machine_ref) or {}
        if machine.get("kind") == "lathe":
            findings.append(_lathe(bundle, setup, machine, machine_ref))
            continue
        if saw_setup(setup):
            findings.append(
                Finding(
                    "headroom",
                    setup["id"],
                    "not_applicable",
                    {},
                    ["PLAN.md §4.1 headroom", f"plan.setups.{setup['id']}.ops"],
                    f"{setup['id']}: saw cuts use no spindle tool stack or table travel.",
                )
            )
            continue
        debts = {}
        cite = [
            "PLAN.md §4.1 headroom",
            "inventory: machine, fixture, support, tool and holder dimensions",
            "plan: stock state and setup frame",
        ]
        hold = _mapping(setup.get("hold"))
        state = _mapping(setup.get("stock_state"))
        fixture_ref = hold.get("fixture")
        fixture = resolve(bundle, workholding_category(bundle, fixture_ref), fixture_ref) or {}
        parallels_ref = hold.get("parallels")
        parallels = resolve(bundle, "fixtures", parallels_ref) or {}
        parallel_height = (
            0 if parallels_ref in (None, "none", "not_applicable") else _height(parallels)
        )
        support_ref = hold.get("supports", hold.get("riser"))
        support = resolve(bundle, "fixtures", support_ref) or {}
        support_height = (
            0
            if support_ref in (None, "none", "not_applicable")
            else _height(support, hold.get("support_orientation"))
        )
        # The legacy riser declaration selects a 1-in block; without an explicit
        # orientation preserve the unknown rather than inventing a stack height.
        bottom = state.get("retained_rail_bottom_z", state.get("bottom_z", _UNKNOWN))
        top = state.get("top_z", _UNKNOWN)
        stock_height = top - bottom if _numeric(top) and _numeric(bottom) else _UNKNOWN
        head = fixture.get("kind") == "dividing_head"
        bed = _UNKNOWN if head else length_mm(fixture, "bed_height")
        jaw = length_mm(fixture, "jaw_height")
        spindle = _limit(machine, machine_ref, "envelope.spindle_to_table_max", debts, cite)
        numbers = {
            "bed_height_mm": "not_applicable" if head else bed,
            "fixture_height_mm": jaw,
            "fixture_verify": uncertain(fixture) if fixture else "missing",
            "parallels_mm": parallel_height
            if parallels_ref not in (None, "none", "not_applicable")
            else "not_applicable",
            "support_blocks_mm": support_height,
            "stock_top_z": top,
            "stock_bottom_z": state.get("bottom_z", _UNKNOWN),
            "retained_rail_bottom_z": bottom,
            "stock_height_mm": stock_height,
            "insertion_mm": 25,
            "spindle_to_table_max_mm": spindle["value"],
            "tool_oal_mm": _UNKNOWN,
            "holder_gauge_len_mm": _UNKNOWN,
            "sum_mm": _UNKNOWN,
            "stacks": [],
            "clearance_basis": (
                "measured spindle-to-table maximum and XY travel; nominal fixture, support, "
                "tool and holder geometry with verification flags as measurement debt"
            ),
        }
        if head:
            # The chucked work hangs on the head axis: its top sits at the head's centre
            # height plus the stock top's offset above the posed axis origin, raised by
            # any declared parallels/blocks under the head (the established support stack).
            centre = length_mm(fixture, "centre_height")
            axis_z = _head_axis_z(_mapping(hold.get("pose")))
            offset = top - axis_z if _numeric(top) and _numeric(axis_z) else _UNKNOWN
            work_top = _sum(parallel_height, support_height, centre, offset)
            numbers.update(
                {
                    "head_centre_height_mm": centre,
                    "head_axis_z": axis_z,
                    "work_top_above_table_mm": work_top,
                }
            )
        else:
            work_top = _sum(bed, parallel_height, support_height, stock_height)
        unknown = (
            not fixture
            or not machine
            or any(uncertain(item) for item in (fixture, parallels, support) if item)
        )
        unknown |= not _numeric(work_top if head else stock_height) or (
            fixture.get("kind") == "vise" and not _numeric(jaw)
        )
        errors = []
        if _numeric(stock_height) and stock_height <= 0:
            errors.append("supported stock height is not positive")
        nominal_stacks, oals, gauges = [], [], []
        for op in setup["ops"]:
            if op["do"] in MANUAL or op["do"] in SAW_OPS:
                continue
            holder_ref = op.get("holder")
            tool = resolve(bundle, "tools", op.get("tool")) or {}
            holder = resolve(bundle, "holders", holder_ref) or {}
            oal, gauge = length_mm(tool, "oal"), length_mm(holder, "gauge_len")
            declared = any(
                holder_ref in _mapping(tool.get(field))
                for field in ("projection_mm", "projection_in")
            )
            projection = length_mm(tool, ("projection", holder_ref)) if holder else _UNKNOWN
            if holder and not declared:
                grip = length_mm(holder, "grip")
                projection = oal - grip if _numeric(oal) and _numeric(grip) else _UNKNOWN
            stack = _sum(work_top, projection, gauge, 25)
            margin = (
                spindle["value"] - stack
                if _numeric(spindle["value"]) and _numeric(stack)
                else _UNKNOWN
            )
            verified = not any(
                uncertain(item) for item in (fixture, parallels, support, tool, holder) if item
            ) and bool(tool and holder and fixture)
            numbers["stacks"].append(
                {
                    "op": op["op"],
                    "tool": op.get("tool", _UNKNOWN),
                    "holder": op.get("holder", _UNKNOWN),
                    "tool_oal_mm": oal,
                    "tool_projection_mm": projection,
                    "holder_gauge_len_mm": gauge,
                    "sum_mm": stack,
                    "margin_mm": margin,
                    "verify": not (verified and spindle["verified"]),
                }
            )
            unknown |= not verified or not spindle["verified"] or not _numeric(margin)
            if verified and spindle["verified"] and _numeric(margin) and margin < 0:
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
        # The vise jaw rises from the supported stock bottom; a head's chuck jaws do not.
        jaw_top_z = (
            "not_applicable"
            if head
            else bottom + jaw - support_stack
            if all(_numeric(v) for v in (bottom, jaw, support_stack))
            else _UNKNOWN
        )
        top_clearance = (
            top - jaw_top_z
            if _numeric(top) and _numeric(jaw_top_z)
            else "not_applicable"
            if head
            else _UNKNOWN
        )
        cuts = {
            str(op["op"]): op["to_z"] - jaw_top_z
            for op in setup["ops"]
            if op["do"] not in SAW_OPS and _numeric(op.get("to_z")) and _numeric(jaw_top_z)
        }
        numbers.update(
            {
                "stock_top_above_jaws_mm": top_clearance,
                "cut_tip_above_jaws_mm": cuts,
                "jaw_obstruction": {
                    "jaw_top_z": jaw_top_z,
                    "requires_path_check": any(value < 0 for value in cuts.values()),
                },
            }
        )
        # A below-jaw endpoint is not proof of a collision: lateral keep-outs
        # require geometry. Report separately without pretending the stack fails.
        unknown |= any(value < 0 for value in cuts.values())
        stock = _mapping(bundle.plan.get("stock"))
        section = stock.get("section_mm", [])
        stock_x, stock_y = (
            stock.get("length_mm", _UNKNOWN),
            section[0] if isinstance(section, list) and section else _UNKNOWN,
        )
        frame = setup_frame(bundle, setup)
        axes = [frame.get("x"), frame.get("y")]
        extents = [
            stock_x,
            stock_y,
            section[1] if isinstance(section, list) and len(section) > 1 else _UNKNOWN,
        ]
        # Transform the stock box dimensions into the actual setup frame.
        if all(_numeric(value) for value in extents) and all(
            isinstance(axis, list) and len(axis) == 3 and all(_numeric(value) for value in axis)
            for axis in axes
        ):
            stock_x, stock_y = [sum(abs(axis[i]) * extents[i] for i in range(3)) for axis in axes]
        numbers.update({"stock_extent_x_mm": stock_x, "stock_extent_y_mm": stock_y})
        travels = {}
        for axis, extent in (("x", stock_x), ("y", stock_y)):
            travel = _limit(machine, machine_ref, f"envelope.travel.{axis}", debts, cite)
            fixture_extent = length_mm(fixture, "length" if axis == "x" else "width")
            required = (
                max(extent, fixture_extent)
                if _numeric(extent) and _numeric(fixture_extent)
                else _UNKNOWN
            )
            travels[axis] = {
                "travel_mm": travel["value"],
                "part_mm": extent,
                "fixture_mm": fixture_extent,
                "required_mm": required,
            }
            unknown |= not _numeric(required) or not travel["verified"]
            if (
                travel["verified"]
                and not uncertain(fixture)
                and _numeric(required)
                and required > travel["value"]
            ):
                errors.append(f"part/fixture envelope exceeds {axis.upper()} travel")
        numbers["travel_checks"] = travels
        numbers["measurements"] = [debts[key] for key in sorted(debts)]
        status = "error" if errors else "unknown" if unknown else "pass"
        sentence = (
            f"{setup['id']}: "
            + (
                "; ".join(errors)
                if errors
                else "headroom, travel or jaw-path geometry remains unmeasured or unresolved"
                if unknown
                else "measured spindle stack and part/fixture travels fit"
            )
            + "."
        )
        findings.append(
            Finding(
                "headroom",
                setup["id"],
                status,
                numbers,
                list(dict.fromkeys(cite)),
                sentence,
            )
        )
    return findings


def _lathe(bundle, setup, machine, machine_ref):
    """Swing over bed/cross slide and length between centres for a lathe setup."""
    debts = {}
    cite = [
        "PLAN.md §4.1 headroom",
        "inventory: lathe swing/between-centres facts and chuck body dimensions",
        "plan: stock_state od_mm/north_end_z/south_end_z and hold stickout_mm",
    ]
    hold = _mapping(setup.get("hold"))
    state = _mapping(setup.get("stock_state"))
    fixture_ref = hold.get("fixture")
    fixture = resolve(bundle, workholding_category(bundle, fixture_ref), fixture_ref) or {}
    scale = {"mm": 1.0, "in": 25.4}.get(bundle.features.get("units"))
    od = state.get("od_mm", _UNKNOWN)
    north, south = state.get("north_end_z"), state.get("south_end_z")
    length = (
        (north - south) * scale
        if _numeric(north) and _numeric(south) and scale is not None
        else _UNKNOWN
    )
    stickout = hold.get("stickout_mm", _UNKNOWN)
    exposed = stickout if _numeric(stickout) else length
    body_dia = length_mm(fixture, "body_dia")
    body_length = length_mm(fixture, "body_length")
    bed = _limit(machine, machine_ref, "envelope.swing_over_bed", debts, cite)
    slide = _limit(machine, machine_ref, "envelope.swing_over_cross_slide", debts, cite)
    centres = _limit(machine, machine_ref, "envelope.between_centres", debts, cite)
    required = _sum(exposed, body_length)
    numbers = {
        "stock_od_mm": od,
        "stock_length_mm": length,
        "stickout_mm": stickout,
        "chuck_body_dia_mm": body_dia,
        "chuck_body_length_mm": body_length,
        "fixture_verify": uncertain(fixture) if fixture else "missing",
        "swing_over_bed_mm": bed["value"],
        "swing_over_cross_slide_mm": slide["value"],
        "between_centres_mm": centres["value"],
        "required_length_mm": required,
        "clearance_basis": (
            "measured swing over bed/cross slide and distance between centres against the "
            "declared stock OD, stick-out (else stock length) and nominal chuck body; no "
            "tool path, carriage stroke or tailstock extension is checked"
        ),
    }
    checks = (
        (od, bed, "stock OD exceeds the swing over the bed"),
        (body_dia, bed, "chuck body diameter exceeds the swing over the bed"),
        (od, slide, "stock OD exceeds the swing over the cross slide"),
        (required, centres, "stick-out plus chuck body exceeds the distance between centres"),
    )
    errors, unknown = [], not machine or not fixture or bool(uncertain(fixture))
    for value, limit, message in checks:
        if not (_numeric(value) and value > 0) or not limit["verified"]:
            unknown = True
        elif value > limit["value"]:
            errors.append(message)
    numbers["measurements"] = [debts[key] for key in sorted(debts)]
    status = "error" if errors else "unknown" if unknown else "pass"
    message = (
        "; ".join(errors)
        if errors
        else "lathe swing, chuck body or between-centres length remains unmeasured or unresolved"
        if unknown
        else "stock and chuck fit the measured swing and between-centres length"
    )
    return Finding(
        "headroom",
        setup["id"],
        status,
        numbers,
        list(dict.fromkeys(cite)),
        f"{setup['id']}: {message}.",
    )
