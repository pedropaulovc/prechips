"""Hole tip endpoints and operation-local entry surfaces (PLAN §4.1)."""

from __future__ import annotations

import functools
import itertools
import math
import re

from prechips.material_routes import (
    producer_setup,
    reference_frame,
    route_identities_known,
    setup_lineage,
)
from prechips.measurements import angle_fact, length_debt

from ..findings import Finding
from ..model import UNIT_TOLERANCE
from .resolution import (
    HAND_THREAD,
    LENGTH_TOLERANCE_MM,
    MANUAL,
    SAW_OPS,
    TAP_OPS,
    UNKNOWN,
    canonical_face_mapping,
    identity,
    length_mm,
    member_protection_status,
    number,
    op_feature,
    operation_material_status,
    operation_members,
    record,
    registered_workpieces,
    resolve,
    same_length,
    setup_frame,
    uncertain,
)

FACING = {"face", "rough_face", "finish_face"}
POCKETING = {"pocket", "rough_pocket", "finish_pocket"}
AXES = ("x", "y", "z")
HOLE_OPS = {"spot", "drill", "ream", "counterbore", "bore"} | TAP_OPS
_HOLE_KINDS = {"hole", "counterbore", "thread", "threaded_hole"}
# Lathe actions that, as a facing op does, leave their feature's face at their to_z.
_PARTING = {"part_off", "cut_to_fit"}
# Plan units of float residue within which two authored Zs are one surface.
SAME_Z = 1e-9


def mapping(value):
    return value if isinstance(value, dict) else {}


def records(value):
    return value if isinstance(value, list) else []


def drill_point_mm(diameter_mm, point_angle_deg):
    """Axial cone length: D / (2 tan(included angle / 2)); unrepresentable cones stay unknown."""
    if not (
        number(diameter_mm)
        and diameter_mm > 0
        and number(point_angle_deg)
        and 0 < point_angle_deg < 180
    ):
        return UNKNOWN
    tangent = math.tan(math.radians(point_angle_deg / 2))
    if tangent <= 0:
        return UNKNOWN
    point = diameter_mm / (2 * tangent)
    return point if math.isfinite(point) else UNKNOWN


def _subtract(*values):
    return values[0] - sum(values[1:]) if all(number(v) for v in values) else UNKNOWN


def _operative(row, bundle, setup, face, op):
    """Add the actual DRO endpoint, preserving physical carry evidence separately.

    A carried touch supplies its typed setting, not another rounding of the raw
    native plane. An imported entry must name that native nominal; return a
    named input error otherwise, without offering an operative stop. Cuts still
    round upward. A through exit is a dimension-derived bound, not another
    face's native or as-cut plane identity. An unverified DRO grid is recorded as
    ``dro_grid_debt``.
    """
    from .coordinates import UNIT_MM, dro_grid, dro_grid_debt, dro_z
    from .zero_recipe.tool_setting import carried_z_reading
    from .zero_recipe.touch import _framed

    grid = dro_grid(bundle, setup)
    grid_debt = dro_grid_debt(bundle, setup)
    if grid_debt:
        row["dro_grid_debt"] = grid_debt
    through = row["exit_face"] != "not_applicable"
    reading = carried_z_reading(bundle, setup, op)
    bad_input = None
    if reading is not None:
        reference = reading["native_edge_mm"]
        anchor = _subtract(reading["z_axis_set"], reading["paper_offset_mm"])
        shift = _subtract(anchor, reference)
        physical_shift = _subtract(reading["edge_mm"], reference)
        producer = _producer(bundle, setup, row["entry_z"], face, 0, row["entry_from"], op=op)
        if (
            number(shift)
            and number(physical_shift)
            and producer not in (None, UNKNOWN)
            and producer[0] is setup
            and _framed(*producer)
        ):
            # A surviving numeric touch proves this DRO. A local cut already
            # ran on it, so do not shift its printed face as an imported native
            # coordinate again; an original producer cannot repair a lost touch.
            formed = operative_z(
                bundle, setup, row["entry_z"], face, source=row["entry_from"], op=op
            )
            shift = _subtract(formed, row["entry_z"])
            residual = reading.get("setting_residual_mm", UNKNOWN)
            scale = UNIT_MM.get(bundle.features.get("units"))
            physical_shift = (
                shift + residual / scale
                if number(shift) and number(residual) and scale is not None
                else UNKNOWN
            )
        else:
            scale = UNIT_MM.get(bundle.features.get("units"))
            if (
                number(row["entry_z"])
                and number(reference)
                and "credited_faces" in reading
                and scale is not None
                and abs(row["entry_z"] - reference) * scale > LENGTH_TOLERANCE_MM
            ):
                bad_input = (
                    f"{row['entry_from']} must equal the carried native entry Z {reference:g} "
                    f"within {LENGTH_TOLERANCE_MM:g} mm; got {row['entry_z']:g}"
                )
                shift = physical_shift = UNKNOWN
        entry = row["entry_z"] + shift if number(row["entry_z"]) and number(shift) else UNKNOWN
        row["dro_entry_z"] = dro_z(entry, grid)
        row["physical_entry_z"] = (
            row["entry_z"] + physical_shift
            if number(row["entry_z"]) and number(physical_shift)
            else UNKNOWN
        )
        row["setting_residual_mm"] = reading.get("setting_residual_mm", UNKNOWN)
        if through:
            # The stock's local thickness can be its allowed maximum. It bounds
            # break-through from this physical entry, but identifies no opposite
            # plane whose own producer offset could be inherited from the entry.
            exit_face = _subtract(entry, row["local_thickness"])
            row["physical_exit_bound_z"] = _subtract(
                row["physical_entry_z"], row["local_thickness"]
            )
            row["dro_exit_face"] = dro_z(exit_face, grid)
            shift = _subtract(row["dro_exit_face"], row["exit_face"])
    else:
        row["dro_entry_z"] = operative_z(
            bundle, setup, row["entry_z"], face, source=row["entry_from"], op=op
        )
        if through:
            exit_face = row["exit_face"]
            row["dro_exit_face"] = dro_z(exit_face, grid)
        surface, worked = ("dro_exit_face", "exit_face") if through else ("dro_entry_z", "entry_z")
        shift = _subtract(row[surface], row[worked])
    tip = row["tip_z"] + shift if number(row["tip_z"]) and number(shift) else UNKNOWN
    row["dro_tip_z"] = dro_z(tip, grid)
    if through:
        lead = row.get("lead_mm", row.get("point_mm", UNKNOWN))
        row["dro_exit_mm"] = _subtract(exit_face, lead, row["dro_tip_z"])
    elif "depth_mm" in row:
        row["dro_depth_mm"] = _subtract(row["depth_mm"], _subtract(row["dro_tip_z"], tip))
        row.setdefault("depth_floor_mm", UNKNOWN)
    return bad_input


def _feature_depth_mm(feature, field, units, end=1):
    """A feature-depth band end (upper by default) uses the model's units, unlike
    depth_mm; a bare number is an upper limit only, so its lower end is unknown."""
    value = feature.get(field, UNKNOWN)
    if isinstance(value, list):
        value = value[end] if len(value) == 2 else UNKNOWN
    elif end == 0:
        value = UNKNOWN
    scale = {"mm": 1.0, "in": 25.4}.get(units)
    return value * scale if number(value) and scale is not None else UNKNOWN


def hole_depth_mm(op, feature, units):
    """Operation depth in machine mm; taps may use their feature's upper depth."""
    if "depth_mm" in op:
        value = op["depth_mm"]
        return value if number(value) else UNKNOWN
    if op.get("do") in TAP_OPS:
        field = "thread_depth" if "thread_depth" in feature else "depth"
        return _feature_depth_mm(feature, field, units)
    return UNKNOWN


def _covers(cut, target, whole=False):
    """Only explicit same-frame footprints can advance another entry surface; ``whole``
    asks that ``target``'s whole footprint (:func:`_footprint`) lie inside them, not
    merely overlap them or hold its ``at`` point."""
    bounds = mapping(cut.get("bounds"))
    if not bounds or cut.get("frame", "model") != target.get("frame", "model"):
        return False
    if target.get("kind") == "face" and not mapping(target.get("bounds")):
        return False
    at = target.get("at")
    other = _footprint(target) if whole else mapping(target.get("bounds"))
    for i, axis in enumerate(("x", "y", "z")):
        if axis not in bounds:
            continue
        band = bounds[axis]
        if not isinstance(band, list) or len(band) != 2 or not all(number(v) for v in band):
            return False
        if isinstance(at, list) and len(at) == 3 and not whole:
            if not number(at[i]) or not band[0] <= at[i] <= band[1]:
                return False
        elif axis in other:
            interval = other[axis]
            if not _span(interval):
                return False
            if whole and not band[0] <= interval[0] <= interval[1] <= band[1]:
                return False
            if max(band[0], interval[0]) >= min(band[1], interval[1]):
                return False
        elif mapping(target.get("plane")).get("axis") == axis:
            value = mapping(target.get("plane")).get("value", UNKNOWN)
            if not number(value) or not band[0] <= value <= band[1]:
                return False
        else:
            return False
    return True


def _axis(feature):
    """``feature``'s ``axis`` (model Z when omitted) when it is a unit vector, to the
    ``UNIT_TOLERANCE`` loading holds a joint axis to, else None: a scaled or zero vector's
    components are no direction cosines, so no fixed residue tells what it runs along."""
    axis = feature.get("axis", [0.0, 0.0, 1.0])
    if not (isinstance(axis, list) and len(axis) == 3 and all(number(v) for v in axis)):
        return None
    return axis if abs(math.hypot(*axis) - 1.0) <= UNIT_TOLERANCE else None


def _footprint(target):
    """``target``'s explicit ``bounds``, else a non-face round feature's X/Y square
    about a unit Z :func:`_axis` (``at`` plus or minus half its largest ``dia``).
    A face's incidental point/diameter metadata never declares its footprint."""
    bounds = mapping(target.get("bounds"))
    if bounds:
        return bounds
    if target.get("kind") == "face":
        return {}
    at, dia, axis = target.get("at"), target.get("dia"), _axis(target)
    sizes = dia if isinstance(dia, list) else [dia]
    if not (isinstance(at, list) and len(at) == 3 and all(number(v) for v in at[:2])):
        return {}
    if not sizes or not all(number(v) for v in sizes):
        return {}
    if axis is None or abs(axis[0]) > 1e-9 or abs(axis[1]) > 1e-9:
        return {}
    half = max(sizes) / 2
    return {name: [at[i] - half, at[i] + half] for i, name in enumerate(("x", "y"))}


def _span(values):
    """Whether ``values`` is a well-formed span: one or more numbers, ascending."""
    return (
        isinstance(values, list)
        and bool(values)
        and all(number(v) for v in values)
        and values == sorted(values)
    )


def _disc(target):
    """A round feature's box: ``at`` along its principal unit :func:`_axis`, ``at`` plus or
    minus its largest radius (half its ``dia``, else its ``radius``) across it; None spans
    unless all are numeric."""
    at, axis = target.get("at"), _axis(target)
    size = target.get("dia") if "dia" in target else target.get("radius")
    sizes, per = size if isinstance(size, list) else [size], 2 if "dia" in target else 1
    if not (
        isinstance(at, list)
        and len(at) == 3
        and axis is not None
        and sizes
        and all(number(v) for v in [*at, *sizes])
        and sum(abs(v) > 1e-9 for v in axis) == 1
    ):
        return dict.fromkeys(AXES)
    half = max(sizes) / per
    return {
        name: [at[i]] if abs(axis[i]) > 1e-9 else [at[i] - half, at[i] + half]
        for i, name in enumerate(AXES)
    }


def _corners(bundle, target, frame):
    """The corners of ``target``'s footprint box in ``frame``, else None: its own
    ``bounds`` (Z from ``at`` when they omit it), else a non-face round feature's box
    (:func:`_disc`), with an omitted axis taken only from its ``plane`` value. A face
    without nonempty authored bounds has no declared corners. Unknown, omitted,
    empty or malformed spans, or a non-numeric frame, give None."""
    from .coordinates import frame_point, model_point

    at, bounds, plane = (
        target.get("at"),
        mapping(target.get("bounds")),
        mapping(target.get("plane")),
    )
    if target.get("kind") == "face" and not bounds:
        return None
    spans = {axis: bounds.get(axis) for axis in AXES} if bounds else _disc(target)
    if bounds and "z" not in bounds and isinstance(at, list) and len(at) == 3:
        spans["z"] = [at[2]]
    for axis in AXES:
        if spans[axis] is None and axis not in bounds and plane.get("axis") == axis:
            spans[axis] = [plane.get("value")]
    if not all(_span(span) for span in spans.values()):
        return None
    source = _frame(bundle, target)
    points = [
        frame_point(model_point(list(p), source), frame)
        for p in itertools.product(spans["x"], spans["y"], spans["z"])
    ]
    return points if all(number(v) for p in points for v in p) else None


def _frame(bundle, feature):
    return mapping(mapping(bundle.features.get("frames")).get(feature.get("frame", "model")))


def _kernel_face_boxes(bundle, target, frame, *, setup=None, workpiece_id=None):
    """Every geometry-matched face's enclosing setup-frame X/Y/Z box and raw ref.

    Resolve the complete list before selecting a producer plane: a missing face must
    not silently shrink the surface to its known patches. Kernel lengths are mm,
    unlike the plan's frame coordinates. Rebounded boxes need not be exact extents.
    """
    from .coordinates import UNIT_MM, frame_point

    refs = target.get("faces")
    if not (
        isinstance(refs, list)
        and refs
        and all(isinstance(ref, str) and ref != UNKNOWN for ref in refs)
    ):
        return None, "no footprint: provide feature bounds or a complete feature faces list"
    kernel = mapping(getattr(bundle, "kernel", None))
    if kernel.get("status") != "ok":
        return None, (
            "no footprint: feature bounds are absent and a successful kernel face "
            "mapping/bbox_mm is missing"
        )
    scale = UNIT_MM.get(bundle.features.get("units"))
    if scale is None:
        return None, "no footprint: feature units are unknown"
    if registered_workpieces(bundle):
        members = (workpiece_id,) if workpiece_id is not None else operation_members(bundle, setup)
        if members is None or len(members) != 1:
            return None, "no footprint: a unique receiving workpiece is unresolved"
        if member_protection_status(bundle, setup, members[0]) is not True:
            return None, "no footprint: receiving workpiece protection is unproved"
    matched = canonical_face_mapping(bundle, kernel, setup, workpiece_id=workpiece_id)
    errors = kernel.get("mapping_errors", {})
    if not isinstance(errors, dict):
        return None, "no footprint: kernel.mapping_errors is malformed"
    faces = {face.get("index"): face for face in map(mapping, records(kernel.get("faces")))}
    boxes = []
    for ref in refs:
        index = matched.get(ref)
        if ref in errors or not isinstance(index, int) or isinstance(index, bool):
            return None, f"no footprint: kernel.mapping has no matched face for {ref}"
        box = mapping(faces.get(index)).get("bbox_mm")
        if not (
            isinstance(box, list)
            and len(box) == 6
            and all(number(v) and math.isfinite(v) for v in box)
            and all(box[i] <= box[i + 3] for i in range(3))
        ):
            return None, (
                f"no footprint: kernel.faces[{index}].bbox_mm is missing or malformed for {ref}"
            )
        spans = [[box[i] / scale, box[i + 3] / scale] for i in range(3)]
        points = [frame_point(list(p), frame) for p in itertools.product(*spans)]
        if not all(number(v) and math.isfinite(v) for p in points for v in p):
            return None, "no footprint: setup frame origin/x/y/z is unknown or malformed"
        boxes.append(
            (
                ref,
                [[min(p[i] for p in points), max(p[i] for p in points)] for i in range(3)],
            )
        )
    return boxes, None


def _setup_footprint(bundle, setup, target, debts=None):
    """The setup-frame X/Y box enclosing ``target``'s footprint, else None.

    Authored bounds and non-face discs take precedence. A bounds-free face uses only
    the existing kernel's geometry-matched boxes, never incidental point/diameter
    metadata. Either enclosing box proves containment, never a cut. A process end
    face uses its section of the arriving stock.
    """
    from prechips.process_features import arriving_bounds, process_of

    if process_of(target) and target.get("bounds"):
        target = {**target, "bounds": arriving_bounds(bundle, setup, target)}
    frame = setup_frame(bundle, setup)
    if (
        registered_workpieces(bundle)
        and target.get("kind") == "face"
        and process_of(target) is None
    ):
        boxes, reason = _kernel_face_boxes(bundle, target, frame, setup=setup)
        if boxes is None:
            if debts is not None:
                debts.append(reason)
            return None
        return [
            [min(box[i][0] for _, box in boxes), max(box[i][1] for _, box in boxes)]
            for i in range(2)
        ]
    points = _corners(bundle, target, frame)
    if points is None:
        reason = "no footprint: feature bounds/plane/at or setup frame origin/x/y/z is unknown"
        if target.get("kind") == "face" and "bounds" not in target:
            boxes, reason = _kernel_face_boxes(bundle, target, frame, setup=setup)
            if boxes is not None:
                return [
                    [min(box[i][0] for _, box in boxes), max(box[i][1] for _, box in boxes)]
                    for i in range(2)
                ]
        if points is None:
            if debts is not None:
                debts.append(reason)
            return None
    return [[min(p[i] for p in points), max(p[i] for p in points)] for i in range(2)]


def _feature_holds(bundle, setup, own, target):
    """Whether cutting all of feature ``own`` down the setup's Z cut all of ``target``:
    ``"whole"``, ``"partial"`` or ``UNKNOWN``. Proven in ``own``'s frame, where its box
    is exact: the setup Z must run along one of that frame's axes, and the box enclosing
    ``target`` there must lie within ``own``'s spans on the other two. A setup Z oblique
    to that frame or not a known unit vector (:func:`frame_axes`), or a footprint that
    cannot be built, is unknown."""
    from .coordinates import frame_axes

    frame = _frame(bundle, own)
    tool = frame_axes(setup_frame(bundle, setup))[2]
    axes = frame_axes(frame)
    box, held = _corners(bundle, own, frame), _corners(bundle, target, frame)
    if box is None or held is None or not all(number(v) for v in [*tool, *sum(axes, [])]):
        return UNKNOWN
    dots = [sum(tool[i] * axis[i] for i in range(3)) for axis in axes]
    across = [i for i, dot in enumerate(dots) if abs(dot) <= 1e-9]
    if len(across) != 2:
        return UNKNOWN
    if all(
        min(p[i] for p in box) - SAME_Z <= min(p[i] for p in held)
        and max(p[i] for p in held) <= max(p[i] for p in box) + SAME_Z
        for i in across
    ):
        return "whole"
    return "partial"


def cut_region(op):
    """``op``'s setup-frame X/Y ``stock_removal_bounds`` as ``[[x0, x1], [y0, y1]]``, else
    None when an axis is unknown, omitted or malformed."""
    box = mapping(op.get("stock_removal_bounds"))
    region = [box.get("x"), box.get("y")]
    return (
        region
        if all(_span(s) and len(s) == 2 and all(math.isfinite(v) for v in s) for s in region)
        else None
    )


def _keep_out_circles(bundle, setup, op, own):
    """Raster keep-out centres in setup XY, with island plus cutter radius in plan units."""
    from .coordinates import UNIT_MM, frame_point, model_point

    contour = mapping(op.get("contour"))
    circles = contour.get("keep_out", [])
    if not isinstance(circles, list):
        return None, "contour.keep_out must be a list of circles"
    if not circles:
        return [], None
    scale = UNIT_MM.get(bundle.features.get("units"))
    if scale is None:
        return None, "contour.keep_out cannot map radii: feature units are unknown"
    tool = record(resolve(bundle, "tools", op.get("tool")))
    diameter = length_mm(tool, "dia")
    if not number(diameter) or not math.isfinite(diameter) or diameter <= 0:
        return None, "contour.keep_out cutter radius is unknown: provide the selected tool.dia"
    frame = setup_frame(bundle, setup)
    frames = mapping(bundle.features.get("frames"))
    sweep_frame = frames.get(contour.get("sweep_frame", own.get("frame", "model")))
    mapped = []
    for circle in circles:
        circle = mapping(circle)
        at, dia = circle.get("at"), circle.get("dia_mm")
        if not (
            isinstance(at, list)
            and len(at) == 2
            and all(number(v) and math.isfinite(v) for v in at)
            and number(dia)
            and math.isfinite(dia)
            and dia > 0
        ):
            return None, "contour.keep_out needs numeric XY at and positive dia_mm"
        centre = frame_point(model_point([*at, 0.0], sweep_frame), frame)[:2]
        if not all(number(v) and math.isfinite(v) for v in centre):
            return None, "contour.keep_out centre has no numeric sweep/setup frame mapping"
        mapped.append((centre, (dia + diameter) / 2 / scale))
    return mapped, None


def _keep_out_hits(circles, boxes):
    return any(
        math.hypot(
            max(box[0][0] - centre[0], 0.0, centre[0] - box[0][1]),
            max(box[1][0] - centre[1], 0.0, centre[1] - box[1][1]),
        )
        <= radius
        for centre, radius in circles
        for box in boxes
    )


def cut_coverage(bundle, setup, op, target, debts=None, credited=None, *, workpiece_id=None):
    """``"whole"``, ``"partial"`` or ``UNKNOWN`` coverage of the producer's surface.

    Unbounded own-feature cuts retain declared whole coverage; cross-feature native
    containment needs an explicit footprint. Bounded cuts use matched kernel boxes
    for every ``kind="face"`` target without ``bounds``: incidental ``at``/``dia`` or
    axis/plane metadata does not declare its extent. Authored bounds and non-face round
    features retain declared containment. Resolve every ref, then select only boxes
    whose whole setup-Z span is at to_z. Existing boxes carry no oriented
    normal: a downward-facing plane at that same Z is an accepted limitation of this
    above-cut model, not an inferred +Z normal. Keep-out islands prevent whole credit.
    Only a whole eligible kernel-box producer appends raw refs to ``credited``.
    """
    from prechips.process_features import process_of

    from .coordinates import UNIT_MM, frame_axes

    name = op_feature(op)  # None for an inspect op's feature list: it cuts no feature
    own = mapping(mapping(bundle.feature_definitions).get(name))
    circles, reason = _keep_out_circles(bundle, setup, op, own)
    if circles is None:
        if debts is not None:
            debts.append(reason)
        return UNKNOWN
    if target.get("kind") == "face" and "bounds" in target and not mapping(target.get("bounds")):
        if debts is not None:
            debts.append("no footprint: explicit face bounds are unknown, empty or malformed")
        return UNKNOWN
    if "stock_removal_bounds" not in op:
        coverage = (
            "whole"
            if name is not None and target == own
            else _feature_holds(bundle, setup, own, target)
        )
        if coverage == UNKNOWN and debts is not None:
            debts.append(
                "no footprint: declared feature bounds/plane/at and setup frame origin/x/y/z "
                "cannot establish unbounded containment"
            )
        if circles and coverage == "whole":
            held = _setup_footprint(bundle, setup, target, debts)
            if held is None:
                return UNKNOWN
            if not all(number(v) and math.isfinite(v) for span in held for v in span):
                if debts is not None:
                    debts.append("contour.keep_out footprint or setup frame is non-finite")
                return UNKNOWN
            if _keep_out_hits(circles, [held]):
                return "partial"
        return coverage

    region = cut_region(op)
    if region is None:
        if debts is not None:
            debts.append("stock_removal_bounds.x/y is missing or malformed")
        return UNKNOWN
    frame = setup_frame(bundle, setup)
    native = target.get("kind") == "face" and (
        "bounds" not in target or (registered_workpieces(bundle) and process_of(target) is None)
    )
    refs = []
    if native:
        faces, reason = _kernel_face_boxes(
            bundle, target, frame, setup=setup, workpiece_id=workpiece_id
        )
        if faces is None:
            if debts is not None:
                debts.append(reason)
            return UNKNOWN
        tolerance = LENGTH_TOLERANCE_MM / UNIT_MM[bundle.features["units"]]
        # Complete native boxes disjoint in XY cannot be touched, regardless of floor.
        # Check this before plane selection so a later unrelated cut cannot hide a
        # known earlier producer. A missing ref above still leaves the whole result debt.
        if all(
            any(
                span[0] > region[i][1] + tolerance or span[1] < region[i][0] - tolerance
                for i, span in enumerate(box[:2])
            )
            for _, box in faces
        ):
            return "partial"
        to_z = op.get("to_z")
        if not number(to_z) or not math.isfinite(to_z):
            if debts is not None:
                debts.append("eligible kernel face plane needs numeric op.to_z")
            return UNKNOWN
        kernel = mapping(getattr(bundle, "kernel", None))
        kinds = {
            item.get("index"): item.get("kind")
            for item in map(mapping, records(kernel.get("faces")))
        }
        matched = mapping(kernel.get("mapping"))
        flat = [(ref, box) for ref, box in faces if all(abs(z - to_z) <= tolerance for z in box[2])]
        # A thin cylinder is not an axial plane merely because its box fits the length
        # tolerance: bbox-only plane proof stands only where no contrary kind is known.
        eligible = [
            (ref, box)
            for ref, box in flat
            if kinds.get(matched.get(ref)) in (None, UNKNOWN, "Plane")
        ]
        if not eligible:
            if debts is not None:
                surface = next(
                    (
                        key
                        for key, feature in bundle.feature_definitions.items()
                        if feature == target
                    ),
                    "feature",
                )
                debts.append(
                    f"no eligible face for {surface} at to_z {to_z:g}: "
                    + (
                        "matched faces at that Z are known non-Plane kinds"
                        if flat
                        else "matched bbox_mm Z spans differ"
                    )
                )
            return UNKNOWN
        refs = [ref for ref, _ in eligible]
        boxes = [box[:2] for _, box in eligible]
        axes = frame_axes(frame)
        # Only a signed permutation preserves the actual model-box extrema. Even a
        # small nonzero oblique component may enlarge the rebounded footprint.
        exact = all(sorted(abs(value) for value in axis) == [0.0, 0.0, 1.0] for axis in axes)
        margins = [
            margin
            for box in boxes
            for i, span in enumerate(box)
            for margin in (span[0] - region[i][0], region[i][1] - span[1])
        ]
        # Rounded kernel edges cannot prove containment or leftover land within the
        # tolerance band, including an edge authored exactly on its rounded value.
        whole = all(margin > tolerance for margin in margins)
        disjoint = any(
            span[0] > region[i][1] + tolerance or span[1] < region[i][0] - tolerance
            for box in boxes
            for i, span in enumerate(box)
        )
        if disjoint or (exact and any(margin < -tolerance for margin in margins)):
            return "partial"
        if not whole:
            if debts is not None:
                debts.append(
                    "kernel bbox boundary uncertainty within LENGTH_TOLERANCE_MM of "
                    "stock_removal_bounds"
                    if all(margin >= -tolerance for margin in margins)
                    else "setup frame rotation gives a rebound over-approximation; overlapping "
                    "kernel bbox_mm does not prove partial coverage"
                )
            return UNKNOWN
        if _keep_out_hits(circles, boxes):
            if exact:
                return "partial"
            if debts is not None:
                debts.append(
                    "contour.keep_out intersects a rebound over-approximation of kernel bbox_mm; "
                    "setup frame rotation leaves coverage unknown"
                )
            return UNKNOWN
        # X/Y containment proves no plane the permitted removal volume never reaches.
        span = mapping(op.get("stock_removal_bounds")).get("z")
        if not (
            _span(span)
            and len(span) == 2
            and all(math.isfinite(v) for v in span)
            and span[0] - SAME_Z <= to_z <= span[1] + SAME_Z
        ):
            if debts is not None:
                debts.append("stock_removal_bounds.z must be a finite span containing op.to_z")
            return UNKNOWN
    else:
        held = _setup_footprint(bundle, setup, target, debts)
        if held is None:
            return UNKNOWN
        if not all(number(v) and math.isfinite(v) for span in held for v in span):
            if debts is not None:
                debts.append("no footprint: feature bounds/plane/at or setup frame is non-finite")
            return UNKNOWN
        if not all(
            region[i][0] - SAME_Z <= held[i][0] and held[i][1] <= region[i][1] + SAME_Z
            for i in range(2)
        ) or _keep_out_hits(circles, [held]):
            return "partial"
    if credited is not None and refs and forms_face(bundle, setup, op) is True:
        credited.extend(refs)
    return "whole"


def stock_states(bundle, setup):
    """Yield (op, before, after); profiles never move the touched top surface.

    Entry values are separate from the setup's touched top: a seeded hole entry may
    name its eventual face, not the incoming material boundary. Explicit pocket/face
    footprints (including an op's own clearing box) may advance entry planes inside the
    cut, not adjoining strips. A clearing box must contain both the current entry and
    its new floor in Z, and cannot raise that entry. A boxed cut within :data:`SAME_Z`
    of the entry may still establish its producer, keeping the lower numeric Z.
    An op that cut only part of a surface (:func:`cut_coverage`)
    advances neither it nor the top; unknown coverage or removal Z leaves the entry
    and its source unknown. Local thickness is authored at the eventual hole entry,
    not raw stock height.
    """
    features = mapping(bundle.feature_definitions)
    stock = mapping(setup.get("stock_state"))
    top = stock.get("top_z", UNKNOWN)
    entries = dict(mapping(stock.get("entry_z")))
    origins = {name: f"{setup['id']} stock_state.entry_z.{name}" for name in entries}
    top_from = f"{setup['id']} stock_state.top_z"
    for op in setup.get("ops", []):
        before = {
            "top_z": top,
            "entry_z": dict(entries),
            "entry_from": dict(origins),
            "top_from": top_from,
        }
        if "to_z" in op and op.get("do") in FACING | POCKETING:
            name = op.get("feature")
            cut = mapping(features.get(name))
            made = f"{setup['id']} op {op['op']} to_z"
            boxed = "stock_removal_bounds" in op
            span = mapping(op.get("stock_removal_bounds")).get("z")
            known_span = _span(span) and len(span) == 2 and span[0] < span[1]
            for target in entries:
                if not boxed and target != name and not _covers(cut, mapping(features.get(target))):
                    continue
                coverage = cut_coverage(bundle, setup, op, mapping(features.get(target)))
                if boxed:
                    entry, floor = entries[target], op["to_z"]
                    # Neither the touched top nor an XY box proves material above a
                    # seeded local entry. A higher floor outside SAME_Z cannot
                    # produce that entry; float-equivalent planes may share a source.
                    if number(entry) and number(floor) and floor > entry + SAME_Z:
                        continue
                    if (
                        known_span
                        and number(entry)
                        and not (span[0] - SAME_Z <= entry <= span[1] + SAME_Z)
                    ):
                        continue
                    if coverage == "whole" and not (
                        known_span
                        and number(entry)
                        and number(floor)
                        and span[0] - SAME_Z <= floor <= span[1] + SAME_Z
                    ):
                        coverage = UNKNOWN
                if coverage == "whole":
                    entries[target] = min(entries[target], op["to_z"]) if boxed else op["to_z"]
                    origins[target] = made
                elif coverage != "partial":
                    entries[target], origins[target] = UNKNOWN, UNKNOWN
            faced = mapping(features.get(stock.get("top_feature") or name))
            if op.get("do") in FACING and (
                stock.get("top_feature") is None or name == stock["top_feature"]
            ):
                coverage = cut_coverage(bundle, setup, op, faced)
                if coverage != "partial":
                    top, top_from = (
                        (op["to_z"], made) if coverage == "whole" else (UNKNOWN, UNKNOWN)
                    )
        after = {
            "top_z": top,
            "entry_z": dict(entries),
            "entry_from": dict(origins),
            "top_from": top_from,
        }
        yield op, before, after


def lineage(bundle, setup):
    """Producer history, oldest first; feature survival requires separate material proof."""
    if not route_identities_known(bundle.plan, setup.get("id")):
        return []
    earlier = setup_lineage(bundle.plan, setup.get("id")) - {setup.get("id")}
    return [other for other in bundle.plan.get("setups", []) if other.get("id") in earlier]


def operative_z(bundle, setup, value, face=None, done=0, source=None, path=False, *, op=None):
    """One printed Z for the surface at nominal ``value`` in ``setup``: the ``dro_to_z``
    of the op that produced it, on that op's own setup grid (:func:`formed_z`: for a
    grooving/parting blade, the face its rounded corner reading leaves, unknown when that
    blade's corner, side or width is), then as this setup's DRO shows it (``dro_z``:
    rounded up on its grid; a value on both grids stays); with no producer, for the
    surface a ``stock_state`` Z names that the setup receives from the setup before it
    (``face`` ``"top"`` or the ``top_feature`` at ``top_z``, the ``bottom_feature`` at
    ``bottom_z``), the Z that setup printed for it carried over (:func:`transfer`), else
    ``dro_z`` of ``value``. An unknown stays unknown.

    The producer is the op ``source`` names in this setup (``"S2 op 20 to_z"``,
    :func:`stock_states`). Else, for the stock ``"top"``, the op that last faced it in
    this setup's first ``done`` ops (:func:`stock_states`). Else the last op proven to cut
    feature ``face`` in the same-frame setups of this setup's :func:`lineage` (and, for a
    feature, this setup's first ``done`` ops), when it cut it to ``value``: for ``"top"``
    a facing op on ``top_feature`` (any, if none is named); for a feature an op on it that
    leaves its face at its ``to_z`` (:func:`forms_face`: a facing or pocketing op, a
    part-off, cut-to-fit, groove or turned shoulder the kernel poses on that plane), or a
    facing or pocketing op whose feature's XY footprint covers it (:func:`_covers_xy`).
    An op on it that may have left its face at an unknown Z (:func:`forms_face` unknown:
    an unknown or missing ``to_z``, an unsampled or unproven kernel pose, a turning window
    claiming a face that is not a cylinder) is its producer, so the surface is unknown,
    never its nominal; an op proven to leave no face there is passed over. An equal Z
    alone is never proof; no ``face`` names no producer. A partial cut
    (:func:`cut_coverage`) never produces the surface; one of unknown coverage leaves its
    producer, and so the Z, unknown.

    ``path`` reads an op's own path end (its ``z_from``/``z_to``, a feature map's cut
    from/to), not a face a touch or a hole entry meets: a turning window op on ``face``
    (:func:`_turning_window`) is passed over there. It places no face on a ``to_z`` a
    path end could print, so as its producer it could only blank it; a touch read keeps
    it as its producer."""
    return _operative_z(bundle, setup, value, face, done, source, path, None, op=op)


def top_reader(bundle, setup):
    """``top(value, done=0)``: :func:`operative_z` of ``setup``'s stock ``"top"``, the Zs
    it carries over (:func:`transfer`) found at most once, and each read once, for the
    setup."""
    carried, reads = functools.cache(lambda: _carried(bundle, setup)), {}

    def top(value, done=0):
        if not number(value):
            return value
        if (value, done) not in reads:
            reads[value, done] = _operative_z(
                bundle, setup, value, "top", done, None, False, carried
            )
        return reads[value, done]

    return top


def _operative_z(bundle, setup, value, face, done, source, path, carried, *, op=None):
    """:func:`operative_z`; ``carried()``, when given, returns ``setup``'s carried Zs
    (:func:`_carried`)."""
    from .coordinates import dro_grid, dro_z, formed_z

    if not number(value):
        return value
    producer = _producer(bundle, setup, value, face, done, source, path, op=op)
    if producer == UNKNOWN:
        return UNKNOWN
    if producer:
        value = formed_z(bundle, *producer)
    else:
        state = mapping(setup.get("stock_state"))
        for key in ("top_z", "bottom_z"):
            named = state.get(ARRIVAL_ZS[key])
            names = {"top"} if key == "top_z" else set()
            if isinstance(named, str) and named != UNKNOWN:
                names.add(named)
            # The received surface itself, never another at an equal Z.
            if face not in names or not number(state.get(key)):
                continue
            if abs(state[key] - value) > SAME_Z:
                continue
            found = carried() if carried else _carried(bundle, setup)
            if key in found:
                return found[key][1]
        surface = state.get("top_feature") if face == "top" else face
        if not path and operation_material_status(bundle, setup, "stock", surface, op=op) is None:
            return UNKNOWN
    return dro_z(value, dro_grid(bundle, setup))


# The stock_state Zs of the surfaces a setup receives, and the feature naming each, if any.
ARRIVAL_ZS = {
    "top_z": "top_feature",
    "bottom_z": "bottom_feature",
    "north_end_z": None,
    "south_end_z": None,
    "plain_end_z": None,
    "retained_rail_bottom_z": None,
}


def transfer(bundle, setup):
    """``{"before", "sign", "offset", "shift", "carried"}`` when ``setup`` receives the
    part from one earlier setup ``before`` whose Z is this one's (``sign`` 1) or its reverse
    (``sign`` -1, the part turned over), else None: from a supply or a joint, from a setup
    whose Z lies along another of this one's axes, or with either frame's Z or origin
    unknown.

    The frames place every surface at ``Z = sign * Z_before + offset``. The setup prints
    each ``stock_state`` Z it receives (:data:`ARRIVAL_ZS`) at ``sign *`` the Z the setup
    before printed for that surface (:func:`_left_z`) plus one ``shift``: so the printed
    numbers linking the two agree on the printed grid, two surfaces apart on one sheet
    stay as far apart on the next, and the transfer rounds once. ``carried`` maps each
    such key to ``(stated Z, printed Z)``. ``shift`` is the least value at or above the
    offset that lands those Zs on this setup's DRO grid (the offset rounded up, ``dro_z``,
    when they are on it already). Where that would print the stock top below its stated Z
    and the setup's Z zero does not touch that top (whose touch sets it where it prints),
    the shift is the least that lands the top on the grid at or above it: a tool clear of
    the printed top is clear of the stock.

    Zs the setup before printed that do not lie whole steps of this grid apart (from a
    finer DRO) no one shift lands on it, and rounding each alone would move them apart:
    such a transfer carries none, and its ``shift`` is None."""
    from .coordinates import dro_grid, dro_z, frame_axes, mapping_vector

    if not route_identities_known(bundle.plan, setup.get("id")):
        return None
    source, before = setup.get("stock_in"), None
    producer = producer_setup(bundle.plan, source) if isinstance(source, str) else None
    for other in bundle.plan.get("setups", []):
        if other is setup:
            break
        if other.get("id") == producer:
            before = other
    if before is None:
        return None
    here = setup_frame(bundle, setup)
    there = reference_frame(bundle.plan, source, setup_frame(bundle, before))
    z_here, z_there = frame_axes(here)[2], frame_axes(there)[2]
    o_here, o_there = (mapping_vector(mapping(f).get("origin")) for f in (here, there))
    if not all(number(v) for v in (*z_here, *z_there, *o_here, *o_there)):
        return None
    turn = sum(a * b for a, b in zip(z_here, z_there, strict=True))
    if abs(abs(turn) - 1) > 1e-9:
        return None
    sign = 1 if turn > 0 else -1
    offset = sum((a - b) * c for a, b, c in zip(o_there, o_here, z_here, strict=True))
    grid = dro_grid(bundle, setup)
    step = grid[0]
    received = arrival_zs(bundle, before)
    state, left = mapping(setup.get("stock_state")), {}
    unresolved = {}
    for key, named in ARRIVAL_ZS.items():
        if number(state.get(key)):
            feature = state.get(named) if named else None
            material = operation_material_status(bundle, setup, before, feature)
            if material is None:
                unresolved[key] = (state[key], UNKNOWN)
            if material is not True:
                continue
            z = _left_z(bundle, before, sign * (state[key] - offset), feature, received)
            if number(z):
                left[key] = sign * z
    move = {"before": before, "sign": sign, "offset": offset, "shift": dro_z(offset, grid)}
    if not left:
        return {**move, "carried": unresolved}
    anchor = next(iter(left.values()))
    if any(abs((z - anchor) / step - round((z - anchor) / step)) > 1e-6 for z in left.values()):
        return {**move, "shift": None, "carried": unresolved}
    shift = dro_z(anchor + offset, grid) - anchor
    zero = mapping(mapping(setup.get("zero")).get("z"))
    touched = zero.get("face") == "top" and zero.get("after_op") is None
    if "top_z" in left and not touched and left["top_z"] + shift < state["top_z"] - SAME_Z:
        shift = dro_z(state["top_z"], grid) - left["top_z"]
    shift = round(shift, 9)
    carried = {key: (state[key], dro_z(z + shift, grid)) for key, z in left.items()}
    carried.update(unresolved)
    return {**move, "shift": shift, "carried": carried}


def _carried(bundle, setup):
    """:func:`transfer`'s carried Zs; unknown, not nominal, across an unplaced output."""
    if not route_identities_known(bundle.plan, setup.get("id")):
        state = mapping(setup.get("stock_state"))
        return {key: (state[key], UNKNOWN) for key in ARRIVAL_ZS if number(state.get(key))}
    move = transfer(bundle, setup)
    if move:
        return move["carried"]
    source = setup.get("stock_in")
    if not isinstance(source, str) or not source.startswith("stock_out."):
        return {}
    producer = producer_setup(bundle.plan, source)
    before = next(
        (row for row in bundle.plan.get("setups", []) if row.get("id") == producer),
        None,
    )
    if (
        before is None
        or reference_frame(bundle.plan, source, setup_frame(bundle, before)) is not None
    ):
        return {}
    state = mapping(setup.get("stock_state"))
    return {key: (state[key], UNKNOWN) for key in ARRIVAL_ZS if number(state.get(key))}


def arrival_zs(bundle, setup):
    """``{key: (stated Z, printed Z)}`` for each ``stock_state`` Z of ``setup``
    (:data:`ARRIVAL_ZS`) as its sheet prints the surface it receives: the top as
    :func:`operative_z` reads it before any op, any other carried over (:func:`transfer`),
    else on its grid (``dro_z``)."""
    from .coordinates import dro_grid, dro_z

    if not route_identities_known(bundle.plan, setup.get("id")):
        state = mapping(setup.get("stock_state"))
        return {key: (state[key], UNKNOWN) for key in ARRIVAL_ZS if number(state.get(key))}
    carried = _carried(bundle, setup)
    state, received = mapping(setup.get("stock_state")), {}
    for key in ARRIVAL_ZS:
        value = state.get(key)
        if not number(value):
            continue
        if key == "top_z":
            printed = _operative_z(bundle, setup, value, "top", 0, None, False, lambda: carried)
        else:
            printed = carried.get(key, (value, dro_z(value, dro_grid(bundle, setup))))[1]
        received[key] = (value, printed)
    return received


def _left_z(bundle, setup, value, feature, received):
    """The Z ``setup``'s sheet printed for the surface it leaves at ``value``: where the op
    that last cut it there left it (:func:`formed_z`), the op found as
    :func:`operative_z` finds it for ``feature`` (when named) or for the stock top (when
    the setup leaves its top there); else the Z it printed for the surface it received
    there (``received``, :func:`arrival_zs`); else None. A producer whose cut is unknown
    carries nothing over."""
    from .coordinates import formed_z

    done = len(setup.get("ops", []))
    faces = [feature] if isinstance(feature, str) and feature != UNKNOWN else []
    states = list(stock_states(bundle, setup))
    top = states[-1][2]["top_z"] if states else None
    if number(top) and abs(top - value) <= SAME_Z:
        faces.append("top")
    for face in faces:
        producer = _producer(bundle, setup, value, face, done, None)
        if producer == UNKNOWN:
            return None
        if producer:
            return formed_z(bundle, *producer)
    printed = {z for exact, z in received.values() if abs(exact - value) <= SAME_Z}
    return printed.pop() if len(printed) == 1 else None


def _covers_xy(cut, target):
    """``cut``'s explicit footprint, its X/Y bounds, holds all of ``target``
    (:func:`_covers`, ``whole``): a surface it leaves at Z is only the surface that
    starts there where it spans that surface's whole footprint."""
    bounds = {k: v for k, v in mapping(cut.get("bounds")).items() if k in ("x", "y")}
    return _covers({**cut, "bounds": bounds}, target, whole=True)


def _turning_window(bundle, setup, op):
    """Whether ``op`` is a lathe turning-approach cut over its ``z_from``..``z_to``
    window: no ``to_z``, and not a manual, transfer, saw, facing, pocketing, part-off or
    cut-to-fit step."""
    from .geometry_common import TURNING, approach

    action = op.get("do")
    return (
        "to_z" not in op
        and isinstance(action, str)
        and action != UNKNOWN
        and action not in MANUAL | SAW_OPS | FACING | POCKETING | _PARTING | {"transfer"}
        and approach(bundle, setup, op) == TURNING
    )


def forms_face(bundle, setup, op):
    """Whether ``op``'s cut leaves its feature's face at its ``to_z``, from known facts
    only. True for a facing or pocketing op with a ``to_z``, and for a lathe
    turning-approach op the geometry kernel poses on its numeric ``to_z`` plane
    (``faced_side``: its claimed faces all face one way along Z, as a face, part-off,
    cut-to-fit, groove wall or turned shoulder does).

    False only where it is known to leave none: a manual or transfer step cuts nothing; a
    saw face is located by its ``cut_plane`` and kerf, never a DRO Z; off the turning
    approach only a facing or pocketing op leaves a Z face (:func:`stock_states`: a hole
    op's ``to_z`` is its tip, a milled wall's its foot); and a turning op the kernel
    sampled, at its numeric ``to_z`` or over its ``z_from``..``z_to`` window, whose
    claimed faces are all cylinders leaves diameters alone.

    Unknown otherwise, so a face it may have left is never taken for stock: an op whose
    action is unknown; a facing, pocketing, part-off or cut-to-fit op without ``to_z``;
    a turning op with an unknown ``to_z`` (the kernel poses no plane without a number,
    so its samples prove no face absent), with no kernel run or sample, or whose sampled
    claims it posed on no one side yet are not all cylinders (they face both ways, or
    their kind is unknown); a turning window op (no ``to_z``) whose claims are not all
    cylinders: the kernel cuts a claimed axial face (a shoulder or groove wall) out to
    its window end yet poses it on no Z plane, so that face stands at an unknown Z; and a
    lathe action off a lathe (no approach model)."""
    from .geometry_common import TURNING, approach

    action = op.get("do")
    if action in MANUAL | SAW_OPS | {"transfer"}:
        return False
    if not isinstance(action, str) or action == UNKNOWN:
        return UNKNOWN
    if action in FACING | POCKETING:
        return True if "to_z" in op else UNKNOWN
    model = approach(bundle, setup, op)
    if model != TURNING:
        return UNKNOWN if model is None else False
    window = "to_z" not in op
    if (window and action in _PARTING) or not (window or number(op["to_z"])):
        return UNKNOWN
    kernel = mapping(getattr(bundle, "kernel", None))
    if kernel.get("status") != "ok":
        return UNKNOWN
    fact = mapping(mapping(kernel.get("ops")).get(f"{setup.get('id')}:{op.get('op')}"))
    if not window and fact.get("faced_side") in (1, -1):
        return True
    # Only a cylinder about setup Z (every claim the kernel samples is turned about it)
    # has no axial normal: any other claim may be a face it left on both sides.
    faces = map(mapping, records(kernel.get("faces")))
    kinds = {face.get("index"): face.get("kind") for face in faces}
    count, claims = fact.get("sample_count"), records(fact.get("claimed_indices"))
    if number(count) and count > 0 and claims and all(kinds.get(i) == "Cylinder" for i in claims):
        return False
    return UNKNOWN


def _producer(
    bundle, setup, value, face, done, source, path=False, debts=None, credited=None, *, op=None
):
    """Resolve the existing producer; optionally collect its whole eligible face refs."""
    if not route_identities_known(bundle.plan, setup.get("id")):
        return UNKNOWN
    receiver_op = op
    ops = setup.get("ops", [])
    features = bundle.feature_definitions
    if source is None and face == "top" and done:
        states = list(stock_states(bundle, setup))[:done]
        source = states[-1][2]["top_from"] if states else None
    unknown_source = source == UNKNOWN
    # Preserve the unknown stock source, but trace its cut when a touch asks why.
    if unknown_source and debts is None:
        return UNKNOWN
    match = re.fullmatch(r"(\S+) op (\S+) to_z", source) if isinstance(source, str) else None
    if match and match[1] == setup.get("id"):
        producer = next(((setup, op) for op in ops if str(op.get("op")) == match[2]), None)
        if producer is not None:
            op = producer[1]
            top = mapping(setup.get("stock_state")).get("top_feature")
            surface_name = top or op_feature(op) if face == "top" else face
            material = operation_material_status(
                bundle, setup, setup, surface_name, op=receiver_op, producer_op=op
            )
            if material is not True:
                return UNKNOWN if material is None else None
            surface = mapping(features.get(surface_name)) if isinstance(surface_name, str) else {}
            matched = [] if credited is not None else None
            if surface.get("kind") == "face" and not mapping(surface.get("bounds")):
                coverage = cut_coverage(bundle, setup, op, surface, debts, matched)
                if coverage != "whole":
                    return UNKNOWN if coverage == UNKNOWN else None
            elif matched is not None:
                cut_coverage(bundle, setup, op, surface, credited=matched)
            if credited is not None:
                credited.extend(matched)
        return producer
    if not isinstance(face, str):
        return UNKNOWN if unknown_source else None
    frame = setup.get("frame")
    cuts = [
        (earlier, op)
        for earlier in lineage(bundle, setup)
        if frame not in (None, UNKNOWN) and earlier.get("frame") == frame
        for op in earlier.get("ops", [])
    ]
    if face != "top" or unknown_source:
        cuts += [(setup, op) for op in ops[:done]]
    top = mapping(setup.get("stock_state")).get("top_feature")
    for cut_setup, op in reversed(cuts):
        name, to_z = op.get("feature"), op.get("to_z")
        if face == "top":
            # The stock top only a facing op moves (:func:`stock_states`).
            forms = op.get("do") in FACING and "to_z" in op and top in (None, name)
        elif name == face:
            # A path end passes over a turning window (:func:`operative_z`).
            forms = not (path and _turning_window(bundle, cut_setup, op)) and forms_face(
                bundle, cut_setup, op
            )
        else:
            # Faces without a nonempty declared footprint need coverage proof,
            # including authored unknown/empty bounds that must remain debt.
            surface = mapping(features.get(face))
            guarded = surface.get("kind") == "face" and not mapping(surface.get("bounds"))
            forms = (
                op.get("do") in FACING | POCKETING
                and "to_z" in op
                and (guarded or _covers_xy(mapping(features.get(name)), surface))
            )
        if not forms:
            continue
        surface_name = top or name if face == "top" else face
        material = operation_material_status(
            bundle, setup, cut_setup, surface_name, op=receiver_op, producer_op=op
        )
        if material is False:
            continue
        if material is None:
            if debts is not None:
                debts.append(f"survival after partition is unknown for {surface_name}")
            return UNKNOWN
        surface = mapping(features.get(top or name if face == "top" else face))
        # An op that cut only part of the surface did not produce it: the uncut part
        # still stands where its last whole producer left it. Unknown coverage proves
        # neither.
        missing = [] if debts is not None else None
        matched = [] if credited is not None else None
        coverage = cut_coverage(bundle, cut_setup, op, surface, missing, matched)
        if coverage == UNKNOWN:
            if debts is not None:
                surface_name = top or name if face == "top" else face
                debts.extend(f"coverage unknown for {surface_name}: {reason}" for reason in missing)
            return UNKNOWN
        if coverage != "whole":
            continue
        if forms is True and number(to_z) and number(value) and abs(to_z - value) > SAME_Z:
            from .coordinates import dro_grid, dro_z
            from .zero_recipe.touch import blade

            # A non-blade face also matches where the DRO actually left it. Do not
            # call formed_z here: its touch-readings lookup may itself be resolving
            # producer metadata. The caller still uses formed_z to reject unknown
            # readings. A blade's touched corner is not its raw to_z on the grid.
            standing = (
                UNKNOWN
                if blade(bundle, op.get("tool"))
                else dro_z(to_z, dro_grid(bundle, cut_setup))
            )
            if not number(standing) or abs(standing - value) > SAME_Z:
                return UNKNOWN if unknown_source else None
        # Where it left the face; unknown when that is (:func:`formed_z`).
        if unknown_source:
            return UNKNOWN
        if credited is not None:
            credited.extend(matched)
        return cut_setup, op
    return UNKNOWN if unknown_source else None


def _centre_mouth(bundle, setup, feature, entry):
    """``(errors, unknown, mouth setup Z)``: a centre's mouth ``at`` must lie on the entry
    surface ``entry`` the quill is touched on, its ``axis`` along the setup -Z feed and, on
    a lathe, its mouth on the spindle axis the tailstock quill feeds along."""
    from prechips.model import UNIT_TOLERANCE

    from .coordinates import frame_point

    frame = setup_frame(bundle, setup)
    at, axis = feature.get("at"), feature.get("axis")
    scale = {"mm": 1.0, "in": 25.4}.get(bundle.features.get("units"))
    if not all(isinstance(v, list) and len(v) == 3 and all(map(number, v)) for v in (at, axis)):
        return [], ["its mouth position or axis is unknown"], UNKNOWN
    mouth = frame_point(at, frame)
    ahead = frame_point([a + d for a, d in zip(at, axis, strict=True)], frame)
    if not all(map(number, mouth + ahead)) or scale is None:
        return [], ["its mouth in the setup frame is unknown"], UNKNOWN
    feed = [b - a for a, b in zip(mouth, ahead, strict=True)]
    norm = math.sqrt(sum(v * v for v in feed))
    errors, unknown = [], []
    if norm == 0 or feed[2] / norm > -1 + UNIT_TOLERANCE:
        errors.append("its axis is not the setup -Z the quill feeds along")
    off = math.hypot(mouth[0], mouth[1]) * scale
    if off > LENGTH_TOLERANCE_MM:
        kind = record(resolve(bundle, "machines", setup.get("machine"))).get("kind")
        if kind == "lathe":
            errors.append(f"its mouth is {off:g} mm off the spindle axis the quill feeds along")
        elif not isinstance(kind, str) or kind == UNKNOWN:
            unknown.append("whether its off-axis mouth is on a lathe spindle axis is unknown")
    if not number(entry):
        unknown.append("the entry surface the quill is touched on is unknown")
    elif not same_length(mouth[2] * scale, entry * scale):
        errors.append(
            f"its mouth lies at setup Z {mouth[2]:g}, not on the Z {entry:g} entry surface "
            "the quill is touched on"
        )
    return errors, unknown, mouth[2]


def centre_endpoint(bundle, setup, op, feature, entry):
    """``(fields, status, reasons, measurement debt)`` of a quill-fed centre drilled from
    ``entry``: ``blind_depth``'s whole verdict on that centre's row.

    Its depth past touching the end is the Table 6 drill length C plus the countersink
    (``centre_depth_mm``), but only for the centre the selected tool's own facts cut
    (``centre_tool``: every fact the kernel builds it from, under the endpoint's verify and
    unknown handling) with its mouth on the touched entry surface along the setup -Z
    feed. A contradiction is ``error``, anything unresolved ``unknown``; either leaves the
    depth unknown, so the traveler prints no quill depth.
    """
    from prechips.process_features import centre_depth_mm, centre_tool

    depth = centre_depth_mm(feature)
    binding = centre_tool(bundle, op)
    errors, unknown, mouth_z = _centre_mouth(bundle, setup, feature, entry)
    (errors if binding["status"] == "error" else unknown).extend(binding["reasons"])
    if not number(depth["depth_mm"]):
        unknown.append("a centre size is unknown")
    status = "error" if errors else "unknown" if unknown else "pass"
    known = depth["depth_mm"] if status == "pass" else UNKNOWN
    fields = {
        "depth_mm": known,
        "countersink_depth_mm": depth["countersink_depth_mm"],
        "drill_length_mm": depth["drill_length_mm"],
        "depth_scale": "quill",
        "exit_face": "not_applicable",
        "tip_z": _subtract(entry, known),
        "mouth_z": mouth_z,
        "tool_centre": binding["tool"],
    }
    return fields, status, errors or unknown, binding["measurements"]


def _entry(before, name):
    """The entry surface Z an op on ``name`` is touched on, from its stock state."""
    return before["entry_z"].get(name, before["top_z"])


def centre_check(bundle, setup, op):
    """``(status, reasons)``: ``blind_depth``'s verdict on centre op ``op`` of ``setup``."""
    features = bundle.feature_definitions
    name = op.get("feature")
    before = next(state for current, state, _ in stock_states(bundle, setup) if current is op)
    _, status, reasons, _ = centre_endpoint(
        bundle, setup, op, features.get(name, {}), _entry(before, name)
    )
    return status, reasons


def evaluate(bundle):
    from prechips.process_features import source_cite

    from .coordinates import dro_grid_measurements

    features = bundle.feature_definitions
    endpoints = {name: [] for name in features}
    unresolved = set()
    errors = set()
    negative_exit = set()
    manual_depth_errors = set()
    # Per centre: why it is not the centre its selected tool cuts from the touched surface.
    centre_errors = {}
    input_errors = {}
    debts = {}
    for setup in bundle.plan["setups"]:
        for op, before, _ in stock_states(bundle, setup):
            name = op.get("feature")
            if not isinstance(name, str) or name not in features:
                continue
            feature = features[name]
            # A plan centre hole is drilled by a combined drill and countersink fed from
            # the tailstock quill: its depth is its own Table 6 geometry, read on the quill.
            centre = (
                op.get("do") in {"spot", "center_drill"} and feature.get("kind") == "centre_hole"
            )
            if not centre and (
                op.get("do") not in HOLE_OPS or feature.get("kind") not in _HOLE_KINDS
            ):
                continue
            entry = _entry(before, name)
            row = {
                "setup": setup["id"],
                "op": op["op"],
                "feature": name,
                "entry_z": entry,
                "entry_from": before["entry_from"].get(name, before["top_from"]),
            }
            tool = resolve(bundle, "tools", op.get("tool")) or {}
            action = op["do"]
            manual_tap = action in TAP_OPS and action in HAND_THREAD
            angle = angle_fact(tool, "point_angle", require_measured=False)
            point = drill_point_mm(
                length_mm(tool, "dia"),
                angle["value"] if angle["verified"] else UNKNOWN,
            )
            if centre:
                fields, status, reasons, debt = centre_endpoint(bundle, setup, op, feature, entry)
                row.update(fields)
                debts.setdefault(name, {}).update((item["id"], item) for item in debt)
                if status == "error":
                    centre_errors.setdefault(name, []).extend(reasons)
                elif status == "unknown":
                    row["unknown"] = reasons
                    unresolved.add(name)
            elif action == "spot":
                depth = hole_depth_mm(op, feature, bundle.features.get("units"))
                row.update(
                    depth_mm=depth,
                    point_mm=point,
                    exit_face="not_applicable",
                    tip_z=_subtract(entry, depth),
                )
            elif action in TAP_OPS:
                depth = hole_depth_mm(op, feature, bundle.features.get("units"))
                flute = length_mm(tool, "flute_len")
                # The thread depth band a tap's depth answers to (hole_depth_mm's field).
                band = "thread_depth" if "thread_depth" in feature else "depth"
                row.update(
                    depth_mm=depth,
                    depth_floor_mm=_feature_depth_mm(
                        feature, band, bundle.features.get("units"), 0
                    ),
                    flute_len_mm=flute,
                    tip_z=_subtract(entry, depth),
                    exit_face="not_applicable",
                )
                if manual_tap:
                    row["depth_scale"] = "manual"
                    if number(depth) and depth <= 0:
                        manual_depth_errors.add(name)
                if number(flute) and number(depth) and not uncertain(tool) and flute < depth:
                    errors.add(name)
                elif not (number(flute) and number(depth)):
                    unresolved.add(name)
            elif feature.get("thru") is True:
                thickness = mapping(mapping(setup.get("stock_state")).get("local_thickness")).get(
                    name, UNKNOWN
                )
                lead = (
                    length_mm(tool, "lead")
                    if action == "ream"
                    else point
                    if action == "drill"
                    else 0
                )
                exit_face = _subtract(entry, thickness)
                allowance = op.get("exit_mm", UNKNOWN)
                negative = number(allowance) and allowance < 0
                if negative:
                    # A negative allowance stops short of breaking through; no stop is offered.
                    negative_exit.add(name)
                row.update(
                    local_thickness=thickness,
                    exit_face=exit_face,
                    exit_mm=allowance,
                    tip_z=UNKNOWN if negative else _subtract(exit_face, lead, allowance),
                )
                row["lead_mm" if action == "ream" else "point_mm"] = lead
            else:
                depth = hole_depth_mm(op, feature, bundle.features.get("units"))
                lead = (
                    length_mm(tool, "lead")
                    if action == "ream"
                    else point
                    if action == "drill"
                    else 0
                )
                units = bundle.features.get("units")
                limit = _feature_depth_mm(feature, "depth", units)
                total = depth + lead if number(depth) and number(lead) else UNKNOWN
                row.update(
                    depth_mm=depth,
                    depth_limit_mm=limit,
                    depth_floor_mm=_feature_depth_mm(feature, "depth", units, 0),
                    total_depth_mm=total,
                    exit_face="not_applicable",
                    tip_z=_subtract(entry, total),
                )
                row["lead_mm" if action == "ream" else "point_mm"] = lead
                if feature.get("thru") == UNKNOWN or not (number(total) and number(limit)):
                    unresolved.add(name)
                elif total > limit and not uncertain(tool):
                    errors.add(name)
            # A centre row's verdict is centre_endpoint's alone (it already holds the tool's
            # presence and verify debt), which centre_support reads through centre_check.
            if not centre and (
                (not manual_tap and row.get("tip_z") == UNKNOWN) or not tool or uncertain(tool)
            ):
                unresolved.add(name)
            if not centre and action == "ream":
                category, tool_ref = identity(bundle, op.get("tool"), "tools")
                debt = length_debt(tool, "lead", category, tool_ref) if tool else None
                if debt:
                    debts.setdefault(name, {})[debt["id"]] = debt
            if not centre and action == "drill":
                machine = resolve(bundle, "machines", setup.get("machine")) or {}
                if machine.get("kind") == "lathe":
                    category, tool_ref = identity(bundle, op.get("tool"), "tools")
                    debt = length_debt(tool, "dia", category, tool_ref) if tool else None
                    if debt:
                        debts.setdefault(name, {})[debt["id"]] = debt
            if not manual_tap:
                face = name if name in before["entry_z"] else "top"
                bad_input = _operative(row, bundle, setup, face, op)
                if bad_input is not None:
                    input_errors.setdefault(name, []).append(bad_input)
                if row.get("dro_tip_z") == UNKNOWN:
                    unresolved.add(name)
                if row.get("dro_grid_debt"):
                    unresolved.add(name)
                    debts.setdefault(name, {}).update(
                        (item["id"], item) for item in dro_grid_measurements(bundle, setup)
                    )
            endpoints[name].append(row)
    result = []
    for name, feature in features.items():
        rows = endpoints[name]
        grid_debts = sorted({row["dro_grid_debt"] for row in rows if "dro_grid_debt" in row})
        if feature.get("kind") not in _HOLE_KINDS | {"centre_hole"}:
            status, sentence = "not_applicable", "Not a hole; no tip endpoint applies."
        elif (
            name in errors
            or name in negative_exit
            or name in manual_depth_errors
            or name in centre_errors
            or name in input_errors
        ):
            sentence = " ".join(
                text
                for flagged, text in (
                    (negative_exit, "A through exit allowance is negative; exit_mm must be >= 0."),
                    (manual_depth_errors, "Manual tapping requires a positive relative depth."),
                    (errors, "The blind tip or tap flute length exceeds the declared depth guard."),
                    (
                        centre_errors,
                        "The centre is not the one its selected tool cuts from the touched "
                        f"entry surface: {'; '.join(centre_errors.get(name, []))}.",
                    ),
                    (input_errors, f"Bad input: {'; '.join(input_errors.get(name, []))}."),
                )
                if name in flagged
            )
            status = "error"
        elif not rows or name in unresolved:
            status, sentence = (
                "unknown",
                "Hole endpoints need the missing or unverified entry, "
                "tool geometry or depth inputs.",
            )
        else:
            status, sentence = (
                "pass",
                "Hole tip endpoints and blind-depth guards are computed from the advanced "
                "local entry surfaces.",
            )
        if grid_debts:
            sentence += " DRO grid debt: " + "; ".join(grid_debts)
        result.append(
            Finding(
                "blind_depth",
                name,
                status,
                {
                    "kind": feature.get("kind", UNKNOWN),
                    "endpoints": rows,
                    **({"dro_grid_debt": "; ".join(grid_debts)} if grid_debts else {}),
                    **(
                        {"measurements": [debts[name][key] for key in sorted(debts[name])]}
                        if debts.get(name)
                        else {}
                    ),
                },
                [
                    "PLAN.md §4.1 tip endpoints",
                    *(
                        [*source_cite(feature), *records(feature.get("cite"))]
                        if feature.get("kind") == "centre_hole"
                        else ["features manifest hole geometry"]
                    ),
                    "plan stock_state and operation depth/exit",
                    "inventory selected tool geometry",
                ],
                sentence,
            )
        )
    return result
