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
Hand-saw-only setups have no spindle stack. Mounted disks require complete native
assembly and spindle-nose bounds, translated from setup Z using the same supported
stock/fixture stack as envelope; no axial insertion allowance is invented for them.

Explicitly posed auxiliary supports are native obstacles, not underpart stack
layers. Legacy support references still contribute their declared heights;
malformed placements and unresolved legacy heights never become zero.

A lathe setup's envelope is its swing and length: the stock and chuck body
diameters against swing over the bed, the stock against swing over the cross
slide (the carriage passes under the whole turned length), and the stick-out
plus chuck body length against the distance between centres.  It is a
necessary-condition screen: it proves no tool path, carriage stroke or
tailstock quill extension.

Mill travel compares the stock each setup receives: a raw single supply (``stock_in``
absent or ``"stock"``) keeps its blank, while a derived, component or joined route uses
the kernel's setup-entry ``stock_bbox_mm`` (never the finished part or raw blank) and
otherwise stays unknown.  Manual bench fit/inspection setups (``rules._bench``) have no
spindle stack or travel.
"""

from fractions import Fraction

from pydantic import ValidationError

from prechips.findings import Finding
from prechips.measurements import length_debt, length_fact, measurement_entry
from prechips.model import PlacedSupport, Reference
from prechips.rules._bench import manual_bench, not_applicable
from prechips.rules._envelope import _band, entry_stock, fixture_height, stock_extents
from prechips.rules.coordinates import printed_xy
from prechips.rules.envelope import _mounted_saw_bounds, _ordered_bounds
from prechips.rules.geometry_common import rule_rows
from prechips.rules.resolution import (
    MANUAL,
    SAW_OPS,
    SLITTING_SAW_MODEL_REASON,
    UNRESOLVED_SAW_MODEL_REASON,
    identity,
    length_mm,
    projection_holder,
    resolve,
    saw_setup,
    select,
    setup_frame,
    slitting_saw,
    spindle_saw,
    uncertain,
)
from prechips.rules.swivel import swivel_angle, to_jaw_frame

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


def _support_stack(bundle, hold, consumed):
    """Legacy bearing heights only; posed auxiliary clearance belongs to native."""
    declared = hold.get("supports", hold.get("riser"))
    values = declared if isinstance(declared, list) else [declared]
    heights, unverified, legacy = [], False, 0
    seen = set()
    for value in values:
        if isinstance(value, dict) and "placement" in value:
            try:
                placed = PlacedSupport.model_validate(value)
            except ValidationError:
                heights.append(_UNKNOWN)
                continue
            if placed.id in seen:
                heights.append(_UNKNOWN)
                continue
            seen.add(placed.id)
            # Source geometry and placement remain in the native obstacle proof.
            # An unresolved inventory source is not a known auxiliary.
            if placed.ref is not None:
                item = resolve(bundle, "fixtures", placed.ref)
                if not item or item.get("kind") == _UNKNOWN:
                    heights.append(_UNKNOWN)
                unverified |= uncertain(item)
            continue
        legacy += 1
        if isinstance(value, dict):
            try:
                Reference.model_validate(value)
            except ValidationError:
                heights.append(_UNKNOWN)
                continue
        elif isinstance(declared, list) and not isinstance(value, str):
            heights.append(_UNKNOWN)
            continue
        reference = value.get("ref", _UNKNOWN) if isinstance(value, dict) else value
        if isinstance(value, dict) and (
            not isinstance(reference, str)
            or reference in ("", "none", "not_applicable")
            or any(key in value for key in ("jaw_side", "jaw_lead_mm", "at_z_mm", "engage_at_z_mm"))
        ):
            # A rest/jaw role is not a declared bearing layer, nor an absent item.
            heights.append(_UNKNOWN)
            continue
        if reference in (None, "none", "not_applicable"):
            legacy -= 1
            continue
        item = resolve(bundle, "fixtures", reference) or {}
        orientation = (
            value.get("orientation", hold.get("support_orientation"))
            if isinstance(value, dict)
            else hold.get("support_orientation")
        )
        height = _height(item, orientation)
        heights.append(height)
        unverified |= uncertain(item)
        if item and not _numeric(height):
            _length(bundle, item, "height", "fixtures", reference, consumed)
    # Multiple listed supports do not declare serial bearing layers: they may
    # stand side by side. Only an explicit riser selects a primary bearing item.
    riser_ref = hold.get("riser")
    if riser_ref not in (None, "none", "not_applicable"):
        height, debt = _support_stack(
            bundle,
            {"supports": riser_ref, "support_orientation": hold.get("support_orientation")},
            consumed,
        )
        # Valid posed auxiliaries add no layer. Other listed legacy declarations
        # retain their debt rather than silently overriding the selected riser.
        riser_identity = identity(bundle, riser_ref, "fixtures")
        other = [
            value
            for value in values
            if not (isinstance(value, dict) and value.get("placement") == "posed")
            and (value.get("ref") if isinstance(value, dict) else value)
            not in (None, "none", "not_applicable")
            and identity(bundle, value.get("ref") if isinstance(value, dict) else value, "fixtures")
            != riser_identity
        ]
        if other or any(not _numeric(value) for value in heights):
            return _UNKNOWN, unverified or debt
        return height, unverified or debt
    if legacy > 1:
        return _UNKNOWN, unverified
    return _sum(*heights), unverified


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
        entry = measurement_entry(
            "machines", identity, field, status=result["measurement_status"], item=machine
        )
        debts[entry["id"]] = entry
    return result


def _length(bundle, item, field, slot, reference, debts):
    """Read the existing nominal policy and name only this consumed refused fact."""
    if isinstance(item, dict) and item:
        category, identity, selected = select(bundle, reference, slot)
        if (
            isinstance(selected, dict)
            and isinstance(identity, str)
            and identity not in (_UNKNOWN, "none", "not_applicable")
        ):
            entry = length_debt(item, field, category, identity)
            if entry is not None:
                debts[entry["id"]] = entry
    return length_mm(item, field)


# The tip-near-jaw-top crash zone the traveler boxes (sheet ``_CRASH_ZONE_MM``).
CRASH_ZONE_MM = 3.0


def _jaw_faces(bundle, setup):
    """(clamp axis index, [low, high] jaw-frame coordinates of the vise jaw faces, swivel
    in degrees), or None.

    The jaws grip the setup-entry stock across the axis they do not run along, so their
    faces stand at the kernel's setup-entry stock box along that axis. A swivelled vise's
    faces are read from the stock box in its jaw frame (the setup frame turned by the
    swivel); an unknown swivel places no faces."""
    hold = _mapping(setup.get("hold"))
    axis = {"x": 1, "y": 0}.get(hold.get("jaws_along"))
    angle = swivel_angle(hold)
    kernel = getattr(bundle, "kernel", None)
    if axis is None or angle == _UNKNOWN:
        return None
    if not isinstance(kernel, dict) or kernel.get("status") != "ok":
        return None
    detail = _mapping(_mapping(kernel.get("setups")).get(setup["id"]))
    bbox = detail.get("jaw_frame_stock_bbox_mm" if angle else "stock_bbox_mm")
    if not (isinstance(bbox, list) and len(bbox) == 6 and all(_numeric(v) for v in bbox)):
        return None
    return axis, [bbox[axis], bbox[axis + 3]], angle


def _setup_coordinates(bundle, setup, memo):
    """The coordinates numbers (printed cutter-centre tables) of ``setup``; ``memo`` keeps
    one coordinates pass per headroom evaluation."""
    from .coordinates import evaluate as coordinates

    if not memo:
        memo.update(
            {row.subject: row.numbers for row in rule_rows(bundle, "coordinates", coordinates)}
        )
    return _mapping(memo.get(setup["id"]))


def _span(op, coordinates, axis, angle=0.0):
    """[low, high] of ``op``'s cutter-centre sweep along ``axis`` (0 = X, 1 = Y) of the
    jaw frame (the setup frame turned by the swivel ``angle``): its printed cutter-centre
    path (:func:`coordinates.printed_xy`), else its stock_removal_bounds (under a swivel, the turned
    corners of that box, which bound the sweep)."""
    printed = printed_xy(coordinates, op["op"])
    bounds = _mapping(op.get("stock_removal_bounds"))
    if not printed and angle:
        x, y = bounds.get("x"), bounds.get("y")
        known = all(isinstance(v, list) and len(v) == 2 and all(map(_numeric, v)) for v in (x, y))
        printed = [[a, b] for a in x for b in y] if known else None
    if printed and angle:
        printed = [to_jaw_frame(p, angle) for p in printed]
    span = (
        [min(p[axis] for p in printed), max(p[axis] for p in printed)]
        if printed
        else bounds.get("xy"[axis])
    )
    if isinstance(span, list) and len(span) == 2 and all(_numeric(v) for v in span):
        return span
    return None


def _clear_of_jaws(bundle, setup, op, faces, coordinates, debts):
    """Whether ``op``'s cutter stays more than :data:`CRASH_ZONE_MM` clear of the vise jaws:
    inside both jaw faces along the clamp axis, or wholly beyond the jaws' ends along the
    axis they run (a blank end overhanging the vise). The jaw ends stand at the declared
    ``jaw_center_along_mm`` ± half the vise's jaw width. An underivable sweep or jaw never
    is clear."""
    if faces is None:
        return False
    tool_ref = op.get("tool")
    tool = resolve(bundle, "tools", tool_ref) or {}
    dia = _length(bundle, tool, "dia", "tools", tool_ref, debts)
    if not _numeric(dia):
        return False
    axis, (low, high), angle = faces
    span = _span(op, coordinates, axis, angle)
    if (
        span
        and span[0] - dia / 2 > low + CRASH_ZONE_MM
        and span[1] + dia / 2 < high - CRASH_ZONE_MM
    ):
        return True
    hold = _mapping(setup.get("hold"))
    fixture_ref = hold.get("fixture")
    fixture = resolve(bundle, "workholding", fixture_ref) or {}
    centre = hold.get("jaw_center_along_mm")
    along = _span(op, coordinates, 1 - axis, angle)
    width = (
        _length(bundle, fixture, "jaw_width", "workholding", fixture_ref, debts)
        if along and _numeric(centre)
        else length_mm(fixture, "jaw_width")
    )
    if not (along and _numeric(centre) and _numeric(width)) or uncertain(fixture):
        return False
    ends = (centre - width / 2, centre + width / 2)
    return (
        along[1] + dia / 2 < ends[0] - CRASH_ZONE_MM or along[0] - dia / 2 > ends[1] + CRASH_ZONE_MM
    )


def evaluate(bundle):
    from . import travel

    findings, coordinates = [], {}
    travel_rows = {row.subject: row.numbers for row in rule_rows(bundle, "travel", travel.evaluate)}
    for setup in bundle.plan["setups"]:
        bench = manual_bench(bundle, setup)
        if bench is not None:
            findings.append(
                not_applicable(
                    "headroom", setup, bench, "headroom", "spindle stack or machine travel"
                )
            )
            continue
        machine = resolve(bundle, "machines", setup["machine"]) or {}
        machine_ref = select(bundle, setup["machine"], "machines")[1]
        if machine.get("kind") == "lathe":
            findings.append(_lathe(bundle, setup, machine, machine_ref))
            continue
        if saw_setup(bundle, setup):
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
        debts, consumed = {}, {}
        cite = [
            "PLAN.md §4.1 headroom",
            "inventory: machine, fixture, support, tool and holder dimensions",
            "plan: stock state and setup frame",
        ]
        hold = _mapping(setup.get("hold"))
        state = _mapping(setup.get("stock_state"))
        fixture_ref = hold.get("fixture")
        fixture = resolve(bundle, "workholding", fixture_ref) or {}
        parallels_ref = hold.get("parallels")
        parallels = resolve(bundle, "fixtures", parallels_ref) or {}
        parallel_height = (
            0 if parallels_ref in (None, "none", "not_applicable") else _height(parallels)
        )
        support_height, support_unverified = _support_stack(bundle, hold, consumed)
        if parallels and not _numeric(parallel_height):
            _length(bundle, parallels, "height", "fixtures", parallels_ref, consumed)
        # The legacy riser declaration selects a 1-in block; without an explicit
        # orientation preserve the unknown rather than inventing a stack height.
        bottom = state.get("retained_rail_bottom_z", state.get("bottom_z", _UNKNOWN))
        top = state.get("top_z", _UNKNOWN)
        stock_height = top - bottom if _numeric(top) and _numeric(bottom) else _UNKNOWN
        head = fixture.get("kind") == "dividing_head"
        jaw_fixture = fixture.get("kind") in {"vise", "chuck_3jaw", "chuck_4jaw"}
        bed = (
            _UNKNOWN
            if head
            else _length(bundle, fixture, "bed_height", "workholding", fixture_ref, consumed)
        )
        jaw = (
            _length(bundle, fixture, "jaw_height", "workholding", fixture_ref, consumed)
            if jaw_fixture
            else length_mm(fixture, "jaw_height")
            if head
            else "not_applicable"
        )
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
            centre = _length(bundle, fixture, "centre_height", "workholding", fixture_ref, consumed)
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
            or any(uncertain(item) for item in (fixture, parallels) if item)
            or support_unverified
        )
        unknown |= not _numeric(work_top if head else stock_height) or (
            fixture.get("kind") == "vise" and not _numeric(jaw)
        )
        errors = []
        if _numeric(stock_height) and stock_height <= 0:
            errors.append("supported stock height is not positive")
        nominal_stacks, oals, gauges, conflicts = [], [], [], []
        saw_debts = []
        spindle_saws = [op for op in setup["ops"] if spindle_saw(bundle, setup, op)]
        if spindle_saws:
            fixture_z, fixture_verified = fixture_height(bundle, setup, debts, cite)
            extents, extent_cite = stock_extents(bundle, setup)
            cite.extend(extent_cite)
            height = extents.get("z", _UNKNOWN)
            for op in spindle_saws:
                status, reasons, evidence, inputs = _mounted_saw_bounds(
                    bundle, setup, op, "headroom"
                )
                if status != "pass":
                    saw_debts.extend(
                        reasons
                        or [
                            SLITTING_SAW_MODEL_REASON
                            if slitting_saw(bundle, op)
                            else UNRESOLVED_SAW_MODEL_REASON
                        ]
                    )
                if status == "error":
                    errors.extend(f"op {op['op']}: {reason}" for reason in reasons)
                nose = evidence.get("spindle_nose_bounds_mm")
                table_band = (
                    [fixture_z + height - top + value for value in (nose[2], nose[5])]
                    if _ordered_bounds(nose)
                    and all(_numeric(value) for value in (fixture_z, height, top))
                    else _UNKNOWN
                )
                verified = fixture_verified and _band(table_band)
                stack = table_band[1] if _band(table_band) else _UNKNOWN
                margin = (
                    spindle["value"] - stack
                    if _numeric(spindle["value"]) and _numeric(stack)
                    else _UNKNOWN
                )
                unknown |= status != "pass" or not verified or not spindle["verified"]
                numbers["stacks"].append(
                    {
                        "op": op["op"],
                        "mounted_saw": inputs,
                        "assembly_swept_bounds_mm": evidence.get(
                            "assembly_swept_bounds_mm", _UNKNOWN
                        ),
                        "spindle_nose_table_band_mm": table_band,
                        "sum_mm": stack,
                        "margin_mm": margin,
                        "verify": not (verified and spindle["verified"] and status == "pass"),
                    }
                )
                if verified and spindle["verified"] and _numeric(margin) and margin < 0:
                    errors.append(f"op {op['op']} exceeds spindle clearance by {-margin:g} mm")
                if _numeric(stack):
                    nominal_stacks.append(stack)
        for op in setup["ops"]:
            if op["do"] in MANUAL or op["do"] in SAW_OPS:
                continue
            holder_ref = op.get("holder")
            tool_ref = op.get("tool")
            tool = resolve(bundle, "tools", tool_ref) or {}
            holder = resolve(bundle, "holders", holder_ref) or {}
            oal = _length(bundle, tool, "oal", "tools", tool_ref, consumed)
            gauge = _length(bundle, holder, "gauge_len", "holders", holder_ref, consumed)
            pair, conflict = projection_holder(bundle, tool, holder_ref)
            # Two spellings of the holder in the map state it twice: unknown, never OAL - grip.
            declared = pair is not None or conflict is not None
            projection = (
                _length(bundle, tool, ("projection", pair), "tools", tool_ref, consumed)
                if holder and pair is not None
                else _UNKNOWN
            )
            if holder and not declared:
                grip = _length(bundle, holder, "grip", "holders", holder_ref, consumed)
                projection = oal - grip if _numeric(oal) and _numeric(grip) else _UNKNOWN
            if conflict:
                conflicts.append(f"op {op['op']}: {conflict}")
            stack = _sum(work_top, projection, gauge, 25)
            margin = (
                spindle["value"] - stack
                if _numeric(spindle["value"]) and _numeric(stack)
                else _UNKNOWN
            )
            verified = (
                not support_unverified
                and not any(uncertain(item) for item in (fixture, parallels, tool, holder) if item)
                and bool(tool and holder and fixture)
            )
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
                    **({"projection_conflict": conflict} if conflict else {}),
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
            if head or not jaw_fixture
            else bottom + jaw - support_stack
            if all(_numeric(v) for v in (bottom, jaw, support_stack))
            else _UNKNOWN
        )
        top_clearance = (
            top - jaw_top_z
            if _numeric(top) and _numeric(jaw_top_z)
            else "not_applicable"
            if head or not jaw_fixture
            else _UNKNOWN
        )
        faces = None if head else _jaw_faces(bundle, setup)
        printed = _setup_coordinates(bundle, setup, coordinates) if faces else {}
        cuts = {
            str(op["op"]): op["to_z"] - jaw_top_z
            for op in setup["ops"]
            if op["do"] not in SAW_OPS
            and _numeric(op.get("to_z"))
            and _numeric(jaw_top_z)
            and not _clear_of_jaws(bundle, setup, op, faces, printed, consumed)
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
        frame = setup_frame(bundle, setup)
        entry = entry_stock(bundle, setup, frame)
        stock_x, stock_y = entry.pop("x"), entry.pop("y")
        cite.extend(entry.pop("cite"))
        numbers.update(entry)
        numbers.update({"stock_extent_x_mm": stock_x, "stock_extent_y_mm": stock_y})
        # Travel is what the table must reach: the cutter-centre span the travel rule
        # judges (printed paths included), never the fixture's footprint (#297). The
        # setup-entry stock is evidence only (``part_mm``).
        span = _mapping(_mapping(travel_rows.get(setup["id"])).get("travel_checks"))
        travels = {}
        for axis, extent in (("x", stock_x), ("y", stock_y)) if span else ():
            travel = _limit(machine, machine_ref, f"envelope.travel.{axis}", debts, cite)
            check = _mapping(span.get(axis))
            required = check.get("required_mm", _UNKNOWN)
            travels[axis] = {
                "travel_mm": travel["value"],
                "part_mm": extent,
                "required_mm": required,
                "minimum_required_mm": check.get("minimum_required_mm", _UNKNOWN),
                "basis": check.get("basis", _UNKNOWN),
            }
            unknown |= not _numeric(required) or not travel["verified"]
            lower = check.get("lower_bound_margin_mm")
            if travel["verified"] and _numeric(lower) and lower < 0:
                errors.append(f"cutter-centre span exceeds {axis.upper()} travel")
        numbers["travel_checks"] = travels
        # A guided sweep moves its fixture under the spindle: the stack and clearance
        # judged at the setup pose do not cover every pose, so it is never a pass (#255).
        from .guided_sweep import unmodelled

        swept = unmodelled(bundle, setup, "headroom")
        saw_debt = "; ".join(dict.fromkeys(saw_debts))
        if spindle_saws:
            numbers["spindle_saw_ops"] = [op["op"] for op in spindle_saws]
            numbers["spindle_saw_debt"] = saw_debt
        if swept:
            numbers["guided_sweep_debts"] = swept
        status = "error" if errors else "unknown" if unknown or swept else "pass"
        if unknown and not errors:
            debts.update(consumed)
        numbers["measurements"] = [debts[key] for key in sorted(debts)]
        sentence = (
            f"{setup['id']}: "
            + (
                "; ".join(errors)
                if errors
                else "; ".join(
                    (
                        ["headroom, travel or jaw-path geometry remains unmeasured or unresolved"]
                        if unknown
                        else []
                    )
                    + conflicts
                    + swept
                    + ([saw_debt] if saw_debt else [])
                )
                if unknown or swept
                else "measured spindle stack and setup-entry stock travels fit"
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
    debts, consumed = {}, {}
    cite = [
        "PLAN.md §4.1 headroom",
        "inventory: lathe swing/between-centres facts and chuck body dimensions",
        "plan: stock_state od_mm/north_end_z/south_end_z and hold stickout_mm",
    ]
    hold = _mapping(setup.get("hold"))
    state = _mapping(setup.get("stock_state"))
    fixture_ref = hold.get("fixture")
    fixture = resolve(bundle, "workholding", fixture_ref) or {}
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
    body_dia = _length(bundle, fixture, "body_dia", "workholding", fixture_ref, consumed)
    body_length = _length(bundle, fixture, "body_length", "workholding", fixture_ref, consumed)
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
    status = "error" if errors else "unknown" if unknown else "pass"
    if status == "unknown":
        debts.update(consumed)
    numbers["measurements"] = [debts[key] for key in sorted(debts)]
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
