"""EL400 ABS Axis Set recipes; approach side is not jog polarity."""

from __future__ import annotations

import math
import re
from itertools import pairwise, product

from ..findings import Finding
from ..measurements import length_debt, length_keys, measurement_checklist
from ..model import UNIT_TOLERANCE, setup_lineage
from ._bench import manual_bench, not_applicable
from .geometry_common import TURNING_BLADE_KINDS, approach, cutting_action, op_claims
from .resolution import (
    HAND_FINISH,
    LENGTH_TOLERANCE_MM,
    MANUAL,
    SAW_OPS,
    UNKNOWN,
    identity,
    known_refs,
    length_mm,
    number,
    plan_frame_cite,
    resolve,
    saw_setup,
    setup_frame,
    uncertain,
)
from .speeds_feeds import spindle_ranges
from .tip_endpoints import (
    FACING,
    POCKETING,
    _kernel_face_boxes,
    _producer,
    _setup_footprint,
    _turning_window,
    cut_coverage,
    cut_region,
    forms_face,
    mapping,
    records,
    stock_states,
)

# Set from a bench reading, not a plan number: a trial-cut diameter or a measured edge.
MEASURED = {"trial_cut_measure", "measure_then_set"}
# Lathe ops that leave a measurable diameter a later tool can be touched off on.
TURNED = {"turn", "rough_turn", "finish_turn"}
# AUTHOR'S CHOICE: the side of the smallest square of a partly cut surface credited as
# left to touch off on. A paper touch needs a patch the operator can see, set the tool end
# over and slide paper under; a narrower sliver may hold no flat surface once the burrs of
# the cuts beside it are counted, and whether it is there at all can rest on geometry no
# operator can check. Illustrative, not measured: larger only leaves more Z unknown.
TOUCH_LAND_MM = 0.5
# How far inside its recorded box a face that fills it (``fills_bbox``) is known to hold
# surface: the kernel's 1e-6 mm side tolerance, within which a notch may run, plus the
# 5e-7 mm by which the record's 6-decimal rounding may move each side of the box.
FILL_MARGIN_MM = 1.5e-6
# Native rigid-transform eligibility, not authored included-angle equality.
_NATIVE_DIRECTION_TOLERANCE_DEG = 1e-6

DIRECTIONS = {
    "x": ({"right", "away_from_spindle_axis"}, {"left", "toward_spindle_axis"}),
    "y": ({"away"}, {"toward"}),
    "z": ({"up", "toward_exposed_end"}, {"down", "toward_chuck"}),
}


def _touch_diameter(tool):
    """Use the contact tip when authored; only an absent tip can use the tool diameter."""
    field = "tip" if length_keys(tool, "tip", tool.get("units"), bare=True) else "dia"
    return length_mm(tool, field), field


def finder_procedure(bundle, setup, tool):
    """The EDGE FINDER box's facts for an X/Y pick-up with ``tool``: its type, tip Ø and
    radius, and the rpm bands it runs at on this setup's mill (its own band intersected
    with each spindle band; the gaps between spindle bands are never filled).

    ``status`` is unknown while a fact is missing or any band endpoint is unknown, and an
    error where no spindle band turns any of the finder's band. An electronic finder
    signals contact with the spindle stopped, so it needs no speed."""
    kind = tool.get("finder_type", UNKNOWN)
    tip, _ = _touch_diameter(tool)
    band = tool.get("rpm_range", UNKNOWN)
    missing = [
        name
        for name, value in (
            ("finder_type", kind),
            ("tip_in / tip_mm", tip),
            ("rpm_range", band if kind != "electronic" else "not_applicable"),
        )
        if value == UNKNOWN
    ]
    rpm, machine_rpm, status = "not_applicable", "not_applicable", "pass"
    if kind != "electronic":
        machine = resolve(bundle, "machines", setup.get("machine")) or {}
        machine_rpm = spindle_ranges(machine)
        known = (
            isinstance(band, list)
            and len(band) == 2
            and all(number(v) for v in band)
            and machine_rpm != UNKNOWN
        )
        rpm = UNKNOWN
        if known:
            rpm = [
                [max(band[0], lo), min(band[1], hi)]
                for lo, hi in machine_rpm
                if max(band[0], lo) <= min(band[1], hi)
            ]
            status = "pass" if rpm else "error"
    if status == "pass" and (missing or rpm == UNKNOWN):
        status = UNKNOWN
    return {
        "finder_type": kind,
        "tip_dia_mm": tip,
        "radius_mm": tip / 2 if number(tip) else UNKNOWN,
        "finder_rpm_range": band,
        "machine_rpm": machine_rpm,
        "rpm": rpm,
        "missing": missing,
        "status": status,
        "cite": tool.get("cite", UNKNOWN),
    }


def axis_recipe(edge_mm, radius_mm, approach, axis, jog_mm, sign=1, scale=1, paper_mm=None):
    """Return nominal Axis Set/check/mirror; jog is physically along frame +axis.

    A finder approaching from -axis subtracts its radius regardless of DRO
    direction. ``paper_mm`` is a Z touch's signed paper stand-off
    (:func:`paper_offset`: negative for a face met from -Z). ``scale`` is the display
    scale: a lathe diameter display shows twice the physical X position, so the
    contact and the jog both double.
    """
    if paper_mm is not None:
        contact = edge_mm + paper_mm if number(edge_mm) and number(paper_mm) else UNKNOWN
    elif (
        number(edge_mm) and number(radius_mm) and approach in {f"-{axis}", f"+{axis}", "indicated"}
    ):
        contact = edge_mm + (-1 if approach == f"-{axis}" else 1) * radius_mm
    else:
        contact = UNKNOWN
    shown = contact * scale if number(contact) and number(scale) else UNKNOWN
    increment = (
        sign * scale * jog_mm if sign in {-1, 1} and number(scale) and number(jog_mm) else UNKNOWN
    )
    return {
        "axis_set": shown,
        "check_reading": shown + increment if number(shown) and number(increment) else UNKNOWN,
        "mirrored_reading": shown - increment if number(shown) and number(increment) else UNKNOWN,
        "sign": sign,
    }


def measured(scale):
    """The bench expression a measured trial-cut diameter is set as on this display."""
    return {2: "D", 1: "D/2"}.get(scale, UNKNOWN)


def x_touch_set(scale, paper_mm, trial_cut):
    """The Axis Set of an authored lathe X touch: the measured diameter on this display,
    plus the paper it touched through, once on the radius (twice on a diameter display);
    a trial cut is its own surface and takes no paper. Unknown paper is unknown."""
    shown = measured(scale)
    if shown == UNKNOWN or trial_cut:
        return UNKNOWN if shown == UNKNOWN else f"measured {shown}"
    if not number(paper_mm) or paper_mm < 0:
        return UNKNOWN
    term = round(paper_mm * scale, 6) + 0.0
    return f"measured {shown}" + (f" + {term:g}" if term else "")


def gauge_ready(bundle, reference):
    """A trial-cut diameter is a bench reading: it needs a resolved, unflagged gauge."""
    gauge = resolve(bundle, "gauges", reference)
    return bool(gauge) and not uncertain(gauge)


def measured_edge(base):
    """The bench expression a measured edge is set as: the reading M plus ``base``."""
    if not number(base):
        return UNKNOWN
    return "M " + f"{round(base, 6) + 0.0:+.6f}".rstrip("0").rstrip(".")


def measured_z(bundle, gauge, measure, offset_mm, paper_mm):
    """A ``measure_then_set`` Z: Axis Set M + offset + paper, where M is read at the
    machine with a ready gauge and ``paper_mm`` is the paper's signed stand-off
    (:func:`paper_offset`); the returned offset + paper is unknown until the gauge
    resolves unflagged and the measurement is named (``"unknown"`` names none)."""
    named = isinstance(measure, str) and measure.strip() not in {"", UNKNOWN}
    if not (named and gauge_ready(bundle, gauge) and number(offset_mm) and number(paper_mm)):
        return UNKNOWN
    return offset_mm + paper_mm


# The corner a grooving/parting blade's Z touch sets, by the touched face's outward normal
# along setup Z: a face toward the free end (+1) is met from +Z by the blade's chuck-side
# corner, a face toward the chuck (-1) by its tailstock-side corner.
CORNERS = {1: "chuck_side", -1: "tailstock_side"}
# The side of its face (along setup Z) a blade corner meets it from: the inverse of CORNERS.
SIDES = {corner: normal for normal, corner in CORNERS.items()}
_NAMED_CORNER = re.compile(r"\b(chuck|tailstock)-side\s+corner\b", re.IGNORECASE)
# Millimetres within which a kernel end face stands at a touch's plan Z.
FACE_Z_TOL_MM = 1e-3


def blade(bundle, reference):
    """Whether tool ``reference`` is a two-cornered grooving/parting blade."""
    return (resolve(bundle, "tools", reference) or {}).get("kind") in TURNING_BLADE_KINDS


def face_normal_z(bundle, setup, face, edge):
    """The outward normal sign along setup Z (+1/-1) of ``face`` where a Z touch at plan
    ``edge`` meets it: the kernel's measured ``end_faces`` of an already-present run (this
    never starts the kernel). With no end face at ``edge`` (stock still stands on it), the
    feature's end faces decide only when they all agree; otherwise unknown."""
    kernel = mapping(getattr(bundle, "kernel", None))
    if kernel.get("status") != "ok" or not isinstance(face, str):
        return UNKNOWN
    if setup_frame(bundle, setup).get("binding", UNKNOWN) == UNKNOWN:
        return UNKNOWN
    revolved = mapping(mapping(mapping(kernel.get("setups")).get(setup["id"])).get("revolved"))
    ends = [
        end
        for end in records(mapping(revolved.get(face)).get("end_faces"))
        if isinstance(end, dict) and end.get("normal_z") in CORNERS and number(end.get("z_mm"))
    ]
    scale = {"mm": 1.0, "in": 25.4}.get(bundle.features.get("units"))
    if number(edge) and scale:
        at = [end for end in ends if abs(end["z_mm"] - edge * scale) <= FACE_Z_TOL_MM]
        ends = at or ends
    signs = {end["normal_z"] for end in ends}
    return signs.pop() if len(signs) == 1 else UNKNOWN


def touch_corner(bundle, setup, touch, face, edge):
    """Which corner of a grooving/parting blade a Z touch on ``face`` at plan ``edge`` sets
    (None for any other tool): ``reference_corner`` is the corner the DRO Z then reads,
    from the face's outward normal (``corner_from`` "face normal"), else the touch's
    authored ``corner`` ("authored"), else unknown. An authored corner, or one its
    ``method`` names, that the face cannot give is ``corner_error`` and leaves the corner
    unknown: the plan is never re-read to fit."""
    if not blade(bundle, touch.get("tool")):
        return None
    normal = face_normal_z(bundle, setup, face, edge)
    derived = CORNERS.get(normal, UNKNOWN)
    authored = touch.get("corner") if touch.get("corner") in CORNERS.values() else None
    named = {match.lower() + "_side" for match in _NAMED_CORNER.findall(str(touch.get("method")))}
    claimed = named | ({authored} if authored else set())
    error = None
    if len(claimed) > 1:
        error = "names both the chuck-side and the tailstock-side corner"
    elif derived != UNKNOWN and claimed and claimed != {derived}:
        error = (
            f"names the {next(iter(claimed)).replace('_', '-')} corner, but its "
            f"{face} faces {'+Z (the free end)' if normal == 1 else '-Z (the chuck)'}: a "
            f"blade touches it with its {derived.replace('_', '-')} corner"
        )
    if error is not None:
        return {"reference_corner": UNKNOWN, "corner_from": UNKNOWN, "corner_error": error}
    if derived != UNKNOWN:
        return {"reference_corner": derived, "corner_from": "face normal"}
    if authored:
        return {"reference_corner": authored, "corner_from": "authored"}
    return {"reference_corner": UNKNOWN, "corner_from": UNKNOWN}


def touch_side(bundle, setup, touch, face, edge, lathe):
    """The side of ``face`` along setup Z (+1 toward the free end or up, -1 toward the
    chuck) a Z touch at plan ``edge`` meets it from, where its paper lies. Off a lathe a Z
    touch comes down on its face: +1. On a lathe it is the face's measured outward normal
    (:func:`face_normal_z`); without one a grooving/parting blade meets it on the side of
    the corner it sets (:func:`touch_corner`: its authored corner), unknown when that is,
    and any other tool from +Z."""
    if not lathe:
        return 1
    normal = face_normal_z(bundle, setup, face, edge)
    if normal != UNKNOWN:
        return normal
    corner = touch_corner(bundle, setup, touch, face, edge)
    return 1 if corner is None else SIDES.get(corner["reference_corner"], UNKNOWN)


def _kernel_face(bundle, face):
    """Whether ``face`` needs a native-plane producer, rather than authored bounds."""
    target = mapping(mapping(bundle.feature_definitions).get(face))
    return target.get("kind") == "face" and "bounds" not in target


def _stock_route(bundle, setup):
    """Explicit upstream stock DAG, in processing order; None for any broken route."""
    setups = records(bundle.plan.get("setups"))
    by_id = {s.get("id"): s for s in setups}
    order = {s.get("id"): i for i, s in enumerate(setups)}
    stock = mapping(bundle.plan.get("stock"))
    components = records(stock.get("components"))
    component_ids = [mapping(component).get("id") for component in components]
    if not all(isinstance(cid, str) and cid.strip() and cid != UNKNOWN for cid in component_ids):
        return None
    if len(set(component_ids)) != len(component_ids):
        return None
    supplies = {f"stock.{cid}" for cid in component_ids} if components else {"stock"}
    routed, visiting = set(), set()

    def visit(current):
        sid = current.get("id")
        if sid in routed:
            return True
        if sid in visiting:
            return False
        visiting.add(sid)
        refs = current.get("stock_in")
        refs = refs if isinstance(refs, list) else [refs]
        if not refs:
            return False
        for ref in refs:
            if not isinstance(ref, str):
                return False
            if ref in supplies:
                continue
            previous = by_id.get(ref)
            if previous is None or order[ref] >= order[sid] or not visit(previous):
                return False
        visiting.remove(sid)
        routed.add(sid)
        return True

    return [s for s in setups if s.get("id") in routed] if visit(setup) else None


def _native_unit(vector):
    return (
        isinstance(vector, (list, tuple))
        and len(vector) == 3
        and all(number(v) and math.isfinite(v) for v in vector)
        and abs(math.hypot(*vector) - 1.0) <= UNIT_TOLERANCE
    )


def _native_basis(axes):
    return all(_native_unit(axis) for axis in axes) and all(
        abs(sum(a * b for a, b in zip(axes[i], axes[j], strict=True))) <= UNIT_TOLERANCE
        for i, j in ((0, 1), (0, 2), (1, 2))
    )


def _native_normal_up(normal, axes):
    """A proven model-space outward normal must face receiving setup +Z."""
    if not _native_unit(normal) or not _native_basis(axes):
        return False
    turned = [sum(a * b for a, b in zip(normal, axis, strict=True)) for axis in axes]
    return (
        math.degrees(math.atan2(math.hypot(*turned[:2]), turned[2]))
        <= _NATIVE_DIRECTION_TOLERANCE_DEG
    )


def _native_plane_geometry(bundle, source, face, refs):
    """An exact selected native end plane and radius, never another plane's radius."""
    from .coordinates import UNIT_MM

    kernel = mapping(getattr(bundle, "kernel", None))
    target = mapping(bundle.feature_definitions.get(face))
    declared = records(target.get("faces"))
    indices = mapping(kernel.get("features")).get(face)
    mapped = [mapping(kernel.get("mapping")).get(ref) for ref in declared]
    if not (
        declared
        and set(refs) <= set(declared)
        and isinstance(indices, list)
        and all(isinstance(i, int) and not isinstance(i, bool) for i in indices)
        and len(indices) == len(set(indices))
        and all(isinstance(i, int) and not isinstance(i, bool) for i in mapped)
        and set(indices) == set(mapped)
    ):
        return None
    fact = mapping(
        mapping(mapping(kernel.get("setups")).get(source.get("id"))).get("revolved")
    ).get(face)
    fact = mapping(fact)
    zs, radii, ends = fact.get("z_mm"), fact.get("end_radii_mm"), fact.get("end_faces")
    if not (
        fact.get("kinds") == ["Plane"]
        and isinstance(zs, list)
        and len(zs) == 2
        and all(number(z) and math.isfinite(z) for z in zs)
        and zs[0] <= zs[1]
        and isinstance(radii, list)
        and len(radii) == 2
        and all(number(r) and math.isfinite(r) and r > 0 for r in radii)
        and isinstance(ends, list)
        and len(ends) == len(declared)
        and all(
            isinstance(end, dict)
            and number(end.get("z_mm"))
            and math.isfinite(end["z_mm"])
            and number(end.get("normal_z"))
            and end.get("normal_z") in (1, -1)
            for end in ends
        )
    ):
        return None
    scale = UNIT_MM[bundle.features["units"]]
    boxes, _ = _kernel_face_boxes(bundle, target, setup_frame(bundle, source))
    tolerance = LENGTH_TOLERANCE_MM
    if set(refs) == set(declared) and zs[1] - zs[0] <= tolerance:
        # Exact native source geometry wins over the exported world AABB.
        height = max(end["z_mm"] for end in ends)
    elif boxes is not None and all(
        (box[2][1] - box[2][0]) * scale <= tolerance for _, box in boxes
    ):
        selected = [box for ref, box in boxes if ref in refs]
        height = max(box[2][1] * scale for box in selected)
        if any(abs(z * scale - height) > tolerance for box in selected for z in box[2]):
            return None
        plane_refs = {ref for ref, box in boxes if abs(box[2][1] * scale - height) <= tolerance}
        if plane_refs != set(refs):
            return None
    else:
        return None
    matched = [end for end in ends if abs(end["z_mm"] - height) <= tolerance]
    if len(matched) != len(refs) or len({end["normal_z"] for end in matched}) != 1:
        return None
    at = [i for i, z in enumerate(zs) if abs(z - height) <= tolerance]
    if not at or max(radii[i] for i in at) - min(radii[i] for i in at) > tolerance:
        return None
    return {
        "source": source["id"],
        "frame": setup_frame(bundle, source),
        "z_mm": height,
        "normal_z": matched[0]["normal_z"],
        "outer_radius_mm": radii[at[0]],
        "radius_is_upper": True,
    }


def _plane_in_frame(bundle, plane, setup, *, physical=True):
    """Rigidly carry the source's as-cut point, or its native nominal for identity."""
    from .coordinates import UNIT_MM, frame_axes, frame_point, model_point

    scale = UNIT_MM[bundle.features["units"]]
    source_axes = frame_axes(plane["frame"])
    axes = frame_axes(setup_frame(bundle, setup))
    if not _native_basis(source_axes) or not _native_basis(axes):
        return None
    source_z = plane.get("formed_z_mm", plane["z_mm"]) if physical else plane["z_mm"]
    point = model_point([0.0, 0.0, source_z / scale], plane["frame"])
    height = frame_point(point, setup_frame(bundle, setup))[2]
    normal = [plane["normal_z"] * v for v in source_axes[2]]
    if not number(height) or not math.isfinite(height):
        return None
    return height if _native_normal_up(normal, axes) else None


def _axial_cut_footprint(bundle, setup, op):
    """One fixed-axis plunge's located centre and finite worst cutting radius."""
    from ..measurements import angle_fact, length_fact
    from ._envelope import measurement_item
    from .coordinates import dro_grid, dro_point, frame_axes, frame_point, planned_point
    from .tip_endpoints import hole_depth_mm

    action = op.get("do")
    if action not in {"spot", "drill", "ream", "counterbore"}:
        return None
    feature = mapping(bundle.feature_definitions.get(op.get("feature")))
    axis = feature.get("axis")
    if feature.get("kind") not in {"hole", "counterbore", "threaded_hole", "thread"}:
        return None
    if not (
        _native_unit(axis) and not any(key in feature for key in ("pattern", "positions", "holes"))
    ):
        return None
    frame = setup_frame(bundle, setup)
    own_frame = mapping(bundle.features.get("frames")).get(feature.get("frame", "model"))
    axes, own_axes = frame_axes(frame), frame_axes(own_frame)
    if not _native_basis(axes) or not _native_basis(own_axes):
        return None
    normal = [sum(axis[i] * own_axes[i][j] for i in range(3)) for j in range(3)]
    direction = [sum(a * b for a, b in zip(normal, basis, strict=True)) for basis in axes]
    if (
        math.degrees(math.atan2(math.hypot(*direction[:2]), abs(direction[2])))
        > _NATIVE_DIRECTION_TOLERANCE_DEG
    ):
        return None
    point, _, reason = planned_point(bundle, op["feature"])
    if reason is not None or not all(number(v) and math.isfinite(v) for v in point):
        return None
    point = dro_point(frame_point(point, frame), dro_grid(bundle, setup))
    if not all(number(v) and math.isfinite(v) for v in point):
        return None
    tool = measurement_item(bundle, "tools", op.get("tool"))
    diameter = length_fact(tool, "dia", require_measured=False)
    if not diameter["verified"] or not number(diameter["value"]) or diameter["value"] <= 0:
        return None
    radius = diameter["value"] / 2
    if tool.get("kind") == "center_drill_set":
        pilot = length_fact(tool, "pilot_len", require_measured=False)
        body = length_fact(tool, "shank", require_measured=False)
        countersink = angle_fact(tool, "angle_deg", require_measured=False)
        depth = hole_depth_mm(op, feature, bundle.features.get("units"))
        if not (
            all(
                fact["verified"] and number(fact["value"]) and math.isfinite(fact["value"])
                for fact in (pilot, body, countersink)
            )
            and pilot["value"] > 0
            and body["value"] >= diameter["value"]
            and 0 < countersink["value"] < 180
            and number(depth)
            and math.isfinite(depth)
            and depth > 0
        ):
            return None
        # The endpoint rounds up, so resolved tip depth is a conservative upper
        # bound. A combined drill's wider cone starts only after its pilot length.
        radius = min(
            body["value"] / 2,
            radius
            + max(0.0, depth - pilot["value"]) * math.tan(math.radians(countersink["value"] / 2)),
        )
    if action in {"spot", "drill"}:
        angle = angle_fact(tool, "point_angle", require_measured=False)
        if not angle["verified"] or not number(angle["value"]) or not 0 < angle["value"] < 180:
            return None
    return (point, radius) if math.isfinite(radius) else None


def _primitive_spares_plane(bundle, setup, op, plane):
    """Exact radial/axial primitive bounds; claims alone prove no preservation."""
    from ..joint_features import joint_operation
    from .coordinates import (
        UNIT_MM,
        dro_grid,
        dro_z,
        formed_z,
        frame_axes,
        frame_point,
        model_point,
    )
    from .geometry_common import finishing_subjects

    if plane is None or not number(plane.get("outer_radius_mm")):
        return False
    scale = UNIT_MM[bundle.features["units"]]
    frame = setup_frame(bundle, setup)
    source_axes = frame_axes(plane["frame"])
    axes = frame_axes(frame)
    if not _native_basis(source_axes) or not _native_basis(axes):
        return False
    centre = frame_point(
        model_point([0.0, 0.0, plane.get("formed_z_mm", plane["z_mm"]) / scale], plane["frame"]),
        frame,
    )
    if not all(number(v) and math.isfinite(v) for v in centre):
        return False
    action = op.get("do")
    # The kernel limits a lathe turning-approach cut's removal to its z_from..z_to
    # window, so a window wholly on the plane's open (outward-normal) side leaves its
    # land whatever its radius: only in a frame coaxial with the plane's normal, with the
    # window's dialled (rounded-up) ends, and a blade's groove its full width from the
    # chuck-side wall (an unknown width proves nothing).
    window = [op.get(key) for key in ("z_from", "z_to")]
    normal = [sum(a * b for a, b in zip(source_axes[2], basis, strict=True)) for basis in axes]
    coaxial = (
        math.degrees(math.atan2(math.hypot(*normal[:2]), abs(normal[2])))
        <= _NATIVE_DIRECTION_TOLERANCE_DEG
    )
    outward = plane.get("normal_z") * normal[2] if plane.get("normal_z") in (1, -1) else 0
    if (
        coaxial
        and _turning_window(bundle, setup, op)
        and all(number(z) and math.isfinite(z) for z in window)
    ):
        grid = dro_grid(bundle, setup)
        dialled = [dro_z(z, grid) for z in window]
        tool = resolve(bundle, "tools", op.get("tool")) or {}
        kind = tool.get("kind")
        # An unresolved tool kind may be a blade: it then needs a known width too.
        possible = not isinstance(kind, str) or kind == UNKNOWN or kind in TURNING_BLADE_KINDS
        blade = (
            (UNKNOWN if uncertain(tool) else length_mm(tool, "blade_width")) if possible else 0.0
        )
        if all(number(z) for z in dialled) and number(blade) and (blade > 0 or not possible):
            # Both ends conservatively: the lower of raw and dialled for the open +Z
            # side; the groove grown from the deeper-dialled chuck-side wall for -Z.
            low = min(*window, *dialled)
            high = max(*window, *dialled, max(min(window), min(dialled)) + blade / scale)
            tolerance = LENGTH_TOLERANCE_MM / scale
            if (outward > 0 and low >= centre[2] - tolerance) or (
                outward < 0 and high <= centre[2] + tolerance
            ):
                return True
    if action in TURNED:
        if plane.get("radius_is_upper") is not True:
            return False
        name = op.get("feature")
        joint = joint_operation(
            bundle, op, f"{setup['id']}:{op['op']}" in finishing_subjects(bundle)
        )
        if joint is not None:
            at, axis = joint.get("at_mm"), joint.get("axis")
            if joint.get("kind") != "cylinder_spigot" or joint.get("reason"):
                return False
            if not (
                isinstance(at, list)
                and isinstance(axis, list)
                and len(at) == len(axis) == 3
                and all(number(v) and math.isfinite(v) for v in [*at, *axis])
                and _native_unit(axis)
            ):
                return False
            own = frame_point([v / scale for v in at], frame)
            direction = [sum(a * b for a, b in zip(axis, basis, strict=True)) for basis in axes]
            if math.hypot(*own[:2]) * scale > LENGTH_TOLERANCE_MM:
                return False
            if (
                math.degrees(math.atan2(math.hypot(*direction[:2]), abs(direction[2])))
                > _NATIVE_DIRECTION_TOLERANCE_DEG
            ):
                return False
            radius = joint.get("diameter_mm")
            radius = radius / 2 if number(radius) else None
        else:
            kernel = mapping(getattr(bundle, "kernel", None))
            definition = mapping(bundle.feature_definitions.get(name))
            expected = {
                mapping(kernel.get("mapping")).get(ref) for ref in records(definition.get("faces"))
            }
            indices = mapping(kernel.get("features")).get(name)
            claims, away, invalid = op_claims(bundle, kernel, setup, op)
            native = mapping(
                mapping(mapping(kernel.get("setups")).get(setup["id"])).get("revolved")
            ).get(name)
            native = mapping(native)
            radii = native.get("radii_mm")
            if not (
                isinstance(indices, list)
                and expected
                and None not in expected
                and set(indices) == expected
                and claims
                and claims <= expected
                and not away
                and not invalid
                and native.get("kinds") == ["Cylinder"]
                and isinstance(radii, list)
                and len(radii) == 2
                and all(number(r) and math.isfinite(r) and r > 0 for r in radii)
                and abs(radii[1] - radii[0]) <= LENGTH_TOLERANCE_MM
            ):
                return False
            radius = radii[0]
        window = [op.get(key) for key in ("z_from", "z_to")]
        if not (
            all(number(z) and math.isfinite(z) for z in window)
            and abs(window[1] - window[0]) > LENGTH_TOLERANCE_MM / scale
            and number(radius)
            and math.isfinite(radius)
        ):
            return False
        # A known external-cylinder turn removes only material outside that radius.
        return radius >= plane["outer_radius_mm"] + math.hypot(*centre[:2]) * scale
    if action in FACING | {"part_off", "cut_to_fit"}:
        kernel = mapping(getattr(bundle, "kernel", None))
        side = mapping(mapping(kernel.get("ops")).get(f"{setup['id']}:{op['op']}")).get(
            "faced_side"
        )
        if plane.get("radius_is_upper") is not True:
            return False
        extent = (
            plane["outer_radius_mm"]
            / scale
            * math.hypot(
                sum(a * b for a, b in zip(source_axes[0], axes[2], strict=True)),
                sum(a * b for a, b in zip(source_axes[1], axes[2], strict=True)),
            )
        )
        low, high = centre[2] - extent, centre[2] + extent
        cut = [op.get("to_z"), formed_z(bundle, setup, op)]
        if (
            not number(side)
            or side not in (1, -1)
            or not all(number(z) and math.isfinite(z) for z in cut)
        ):
            return False
        return (
            high < min(cut) - LENGTH_TOLERANCE_MM / scale
            if side == 1
            else low > max(cut) + LENGTH_TOLERANCE_MM / scale
        )
    return False


def _rectangular_spares_plunge(bundle, setup, target, plane, footprint, previous, excluded):
    """A native filled rectangle retains the existing square touch-land witness."""
    from .coordinates import UNIT_MM, frame_axes, frame_point, model_point

    if plane is None or footprint is None:
        return False
    held = _rectangle(bundle, setup, target)
    if held is None:
        return False
    source_axes = frame_axes(plane["frame"])
    axes = frame_axes(setup_frame(bundle, setup))
    if not _native_basis(source_axes) or not _native_basis(axes):
        return False
    turned = [sum(a * b for a, b in zip(source_axes[2], axis, strict=True)) for axis in axes]
    if (
        math.degrees(math.atan2(math.hypot(*turned[:2]), abs(turned[2])))
        > _NATIVE_DIRECTION_TOLERANCE_DEG
    ):
        return False
    scale = UNIT_MM[bundle.features["units"]]
    centre = frame_point(
        model_point([0.0, 0.0, plane.get("formed_z_mm", plane["z_mm"]) / scale], plane["frame"]),
        setup_frame(bundle, setup),
    )
    if not all(number(v) and math.isfinite(v) for v in centre):
        return False
    point, radius = footprint
    reach = max(previous, radius + math.hypot(point[0] - centre[0], point[1] - centre[1]) * scale)
    if not math.isfinite(reach):
        return False
    region = [[centre[i] - reach / scale, centre[i] + reach / scale] for i in (0, 1)]
    if not _uncut(*held, [region]):
        return False
    excluded.append(reach)
    return True


def _same_plane_axis(bundle, old, new):
    """Whether two native planes share one centre axis (parallel normals, frame origins
    within LENGTH tolerance across it), so a keep-off radius about one is about the other."""
    from .coordinates import UNIT_MM, frame_axes, model_point

    if old is None or new is None:
        return False
    old_axes, new_axes = frame_axes(old["frame"]), frame_axes(new["frame"])
    if not _native_basis(old_axes) or not _native_basis(new_axes):
        return False
    along = abs(sum(a * b for a, b in zip(old_axes[2], new_axes[2], strict=True)))
    if math.degrees(math.acos(min(1.0, along))) > _NATIVE_DIRECTION_TOLERANCE_DEG:
        return False
    offset = [
        a - b
        for a, b in zip(
            model_point([0.0, 0.0, 0.0], old["frame"]),
            model_point([0.0, 0.0, 0.0], new["frame"]),
            strict=True,
        )
    ]
    axial = sum(a * b for a, b in zip(offset, new_axes[2], strict=True))
    lateral = math.sqrt(max(0.0, sum(v * v for v in offset) - axial * axial))
    return (
        math.isfinite(lateral)
        and lateral * UNIT_MM[bundle.features["units"]] <= LENGTH_TOLERANCE_MM
    )


def _carry_boxes(bundle, setup, target, plane):
    """Existing selected boxes translated only by a proved source cut's offset."""
    from .coordinates import UNIT_MM, frame_axes

    boxes, _ = _kernel_face_boxes(bundle, target, setup_frame(bundle, setup))
    if boxes is None or plane is None or "formed_z_mm" not in plane:
        return boxes
    delta = (plane["formed_z_mm"] - plane["z_mm"]) / UNIT_MM[bundle.features["units"]]
    if delta == 0.0:
        return boxes
    source_axes = frame_axes(plane["frame"])
    axes = frame_axes(setup_frame(bundle, setup))
    if not math.isfinite(delta) or not _native_basis(source_axes) or not _native_basis(axes):
        return None
    shift = [delta * sum(a * b for a, b in zip(source_axes[2], axis, strict=True)) for axis in axes]
    return [
        (ref, [[end + shift[i] for end in span] for i, span in enumerate(box)])
        for ref, box in boxes
    ]


def _carry_cut(bundle, setup, op, target, plane=None, excluded=None, previous=0.0, debts=None):
    """Whether a cut invalidates the plane; preserve only proven bounded primitives."""
    from .coordinates import UNIT_MM

    kernel = mapping(getattr(bundle, "kernel", None))
    claims, away, invalid = op_claims(bundle, kernel, setup, op)
    if claims is None or away or invalid:
        return True
    if "stock_removal_bounds" in op:
        bounds = mapping(op.get("stock_removal_bounds"))
        spans = [bounds.get(axis) for axis in ("x", "y", "z")]
        if not all(
            isinstance(span, list)
            and len(span) == 2
            and all(number(v) and math.isfinite(v) for v in span)
            and span[0] <= span[1]
            for span in spans
        ):
            return True
        boxes = _carry_boxes(bundle, setup, target, plane)
        if boxes is None:
            return True
        tolerance = LENGTH_TOLERANCE_MM / UNIT_MM[bundle.features["units"]]
        if not any(
            all(
                max(cut[0], face[0]) <= min(cut[1], face[1]) + tolerance
                for cut, face in zip(spans, box, strict=True)
            )
            for _, box in boxes
        ):
            return False
    footprint = _axial_cut_footprint(bundle, setup, op)
    if footprint is not None:
        point, radius = footprint
        boxes = _carry_boxes(bundle, setup, target, plane)
        scale = UNIT_MM[bundle.features["units"]]
        if boxes is not None and all(
            any(
                point[axis] + radius / scale < box[axis][0] - LENGTH_TOLERANCE_MM / scale
                or point[axis] - radius / scale > box[axis][1] + LENGTH_TOLERANCE_MM / scale
                for axis in range(2)
            )
            for _, box in boxes
        ):
            # An unrelated bounded axial column cannot touch even an oblique face.
            return False
    if footprint is not None:
        if _rectangular_spares_plunge(
            bundle,
            setup,
            target,
            plane,
            footprint,
            previous,
            excluded if excluded is not None else [],
        ):
            return False
        if debts is not None:
            debts.append(
                f"{setup['id']} op {op['op']} has no proven usable touch land: "
                "an overlapping plunge needs a native fills_bbox rectangle retaining "
                f"a {TOUCH_LAND_MM:g} mm square; circular/holed shape topology is unproven "
                "(native evidence gap: https://github.com/pedropaulovc/prechips/issues/208)"
            )
        return True
    return not _primitive_spares_plane(bundle, setup, op, plane)


def _native_scene_plane(bundle, setup, face, geometry=None, *, normal_z=1):
    """Raw setup-Z of this exact datum's stock-proven native outline, or None."""
    from .coordinates import UNIT_MM

    kernel = mapping(getattr(bundle, "kernel", None))
    target = mapping(bundle.feature_definitions.get(face))
    refs = target.get("faces")
    indices = mapping(kernel.get("features")).get(face)
    matched = mapping(kernel.get("mapping"))
    if (
        not known_refs(refs)
        or not isinstance(indices, list)
        or not indices
        or not all(isinstance(i, int) and not isinstance(i, bool) and i >= 0 for i in indices)
        or len(indices) != len(set(indices))
        or set(indices) != {matched.get(ref) for ref in refs}
    ):
        return None
    labels = {
        f"DATUM {name}: {datum.get('surface', datum.get('feature', ''))}"
        for name, datum in mapping(bundle.features.get("datums")).items()
        if isinstance(datum, dict) and datum.get("feature") == face
    }
    scene = mapping(mapping(mapping(kernel.get("setups")).get(setup.get("id"))).get("render_scene"))
    datums = [d for d in records(scene.get("datums")) if mapping(d).get("label") in labels]
    if len(datums) != 1:
        return None
    datum = datums[0]
    normal, outline = datum.get("normal"), datum.get("outline_mm")
    if not (
        normal_z in (1, -1)
        and _native_unit(normal)
        and math.degrees(math.atan2(math.hypot(*normal[:2]), normal_z * normal[2]))
        <= _NATIVE_DIRECTION_TOLERANCE_DEG
        and isinstance(outline, list)
        and outline
        and all(isinstance(edge, list) and len(edge) >= 2 for edge in outline)
    ):
        return None
    points = [point for edge in outline for point in edge]
    if not all(
        isinstance(point, list)
        and len(point) == 3
        and all(number(v) and math.isfinite(v) for v in point)
        for point in points
    ):
        return None
    heights = [point[2] for point in points]
    scale = UNIT_MM.get(bundle.features.get("units"))
    if scale is None or max(heights) - min(heights) > LENGTH_TOLERANCE_MM:
        return None
    if geometry is not None:
        # Stock-proven boundary points give a lower bound on remaining planar
        # extent, not a box-derived circle topology or an external-turn bound.
        radius = max(math.hypot(*point[:2]) for point in points)
        if radius > 0 and math.isfinite(radius):
            geometry.update(
                source=setup["id"],
                frame=setup_frame(bundle, setup),
                z_mm=max(heights),
                normal_z=normal_z,
                outer_radius_mm=radius,
                radius_is_upper=False,
            )
    return max(heights) / scale


def _component_supply_plane(bundle, setup, source, face, ref):
    """Tie an as-is plane to this component's entering stock, not the joined union."""
    kernel = mapping(getattr(bundle, "kernel", None))
    facts = mapping(mapping(kernel.get("setups")).get(setup.get("id")))

    def missing(detail):
        return None, f"{source} as-is face {face} ({ref}): {detail}"

    if facts.get("stock_reason") or facts.get("stock_out_reason"):
        return missing("component root has unresolved stock")
    state = mapping(setup.get("stock_state"))
    sides = [
        side
        for field, side in (("top_feature", "up"), ("bottom_feature", "down"))
        if state.get(field) == face
    ]
    if not sides:
        return missing("component root needs its named pre-cut stock face")
    measured = mapping(mapping(facts.get("stock_faces_mm")).get(face))
    if measured.get("reason"):
        return missing(f"pre-cut stock face is unresolved ({measured['reason']})")
    plane = _native_plane_geometry(bundle, setup, face, [ref])
    if plane is None:
        return missing("exact mapped source native plane is missing")
    side = "up" if plane["normal_z"] == 1 else "down"
    if side not in sides:
        return missing(f"component root does not name this {side} stock face")
    height = mapping(measured.get(side))
    face_z, stock_z = height.get("face_z"), height.get("stock_z")
    if height.get("reason") or not all(number(z) and math.isfinite(z) for z in (face_z, stock_z)):
        return missing("pre-cut stock face needs finite face_z and stock_z")
    if (
        abs(face_z - stock_z) > LENGTH_TOLERANCE_MM
        or abs(face_z - plane["z_mm"]) > LENGTH_TOLERANCE_MM
    ):
        return missing("pre-cut stock height does not match the exact source face plane")
    geometry = {}
    _native_scene_plane(bundle, setup, face, geometry, normal_z=plane["normal_z"])
    if not geometry or abs(geometry["z_mm"] - face_z) > LENGTH_TOLERANCE_MM:
        # stock_faces_mm permits partial carry. Only this component's own
        # on-surface datum additionally proves the named surface still exists.
        return missing("component-local whole on-surface datum is missing or mismatched")
    return plane, None


def _native_surface_planes(bundle, setup, face, to_z):
    """Eligible raw planes at a cut's height; None for authored/legacy surfaces.

    Owning a feature proves no planar datum: an unbounded facing cut can wholly
    own a hole's cylindrical refs without leaving any of those refs at ``to_z``.
    A new native touch surface needs its flat matched boxes or exact bound plane,
    including the source-plane/datum alternatives for an oblique world bbox.
    """
    from .coordinates import UNIT_MM

    target = mapping(bundle.feature_definitions.get(face))
    refs = target.get("faces")
    if "bounds" in target or not known_refs(refs):
        return None
    if not number(to_z) or not math.isfinite(to_z):
        return []
    scale = UNIT_MM.get(bundle.features.get("units"))
    if scale is None:
        return []
    tolerance = LENGTH_TOLERANCE_MM / scale
    boxes, _ = _kernel_face_boxes(bundle, target, setup_frame(bundle, setup))
    kernel = mapping(getattr(bundle, "kernel", None))
    kinds = {
        item.get("index"): item.get("kind") for item in map(mapping, records(kernel.get("faces")))
    }
    matched = mapping(kernel.get("mapping"))
    # A thin cylinder is not an axial plane merely because its box fits the
    # length tolerance. Keep bbox-only proof only where no contrary type is known.
    possible = [ref for ref in refs if kinds.get(matched.get(ref)) in (None, UNKNOWN, "Plane")]
    eligible = (
        [
            ref
            for ref, box in boxes
            if ref in possible and all(abs(z - to_z) <= tolerance for z in box[2])
        ]
        if boxes is not None
        else []
    )
    if eligible:
        return eligible
    for ref in possible:
        plane = _native_plane_geometry(bundle, setup, face, [ref])
        if plane is not None and abs(plane["z_mm"] / scale - to_z) <= tolerance:
            eligible.append(ref)
    if eligible:
        return eligible
    if len(possible) != len(refs):
        return []
    height = _native_scene_plane(bundle, setup, face)
    return list(refs) if number(height) and abs(height - to_z) <= tolerance else []


def _carried_native_plane_groups(bundle, route, setup, face, boxes, *, current=False):
    """Raw receiving planes, before any stock or as-cut credit; None for proof gaps."""
    from .coordinates import UNIT_MM

    scale = UNIT_MM[bundle.features["units"]]
    tolerance = LENGTH_TOLERANCE_MM / scale
    kernel = mapping(getattr(bundle, "kernel", None))
    kinds = {
        item.get("index"): item.get("kind") for item in map(mapping, records(kernel.get("faces")))
    }
    matched = mapping(kernel.get("mapping"))
    target = mapping(bundle.feature_definitions.get(face))
    heights = []
    for ref, box in boxes:
        if not all(number(z) and math.isfinite(z) for z in box[2]):
            return None
        if kinds.get(matched.get(ref)) not in (None, UNKNOWN, "Plane"):
            return None
        if box[2][1] - box[2][0] <= tolerance:
            height = box[2][1]
        else:
            # A rotated world AABB is not a plane. Only exact source-native
            # geometry or this same named source datum can supply its raw Z.
            source_heights = []
            for source in route:
                if not current and source.get("id") == setup.get("id"):
                    continue
                plane = _native_plane_geometry(bundle, source, face, [ref])
                if plane is None and target.get("faces") == [ref]:
                    geometry = {}
                    _native_scene_plane(bundle, source, face, geometry)
                    plane = geometry or None
                if plane is not None:
                    native = _plane_in_frame(bundle, plane, setup, physical=False)
                    if number(native) and math.isfinite(native):
                        source_heights.append(native)
            if not source_heights or max(source_heights) - min(source_heights) > tolerance:
                return None
            height = max(source_heights)
        heights.append((height, ref))
    groups = []
    for height, ref in sorted(heights):
        # Matching uses LENGTH, but it cannot merge distinct native planes.
        # Only the same numerical plane groups its exactly coplanar refs.
        if not groups or height != groups[-1]["z"]:
            groups.append({"z": height, "refs": [ref]})
        else:
            groups[-1]["refs"].append(ref)
    return groups


def _carried_face_z(
    bundle,
    setup,
    face,
    edge,
    done,
    debts,
    credited,
    constraint=None,
    errors=None,
    *,
    current_refs=None,
):
    """A surviving selected plane, including a current producer's own native refs
    (``current_refs``), with bounded touch keep-off."""
    from .coordinates import UNIT_MM, formed_z, frame_axes

    def unknown(reason):
        if debts is not None:
            debts.append(reason)
        return UNKNOWN

    target = mapping(bundle.feature_definitions.get(face))
    route = _stock_route(bundle, setup)
    if route is None and current_refs is not None and "stock_in" not in setup:
        # Legacy local recipes name no incoming route. A whole local producer
        # still establishes this surface; no upstream supply is borrowed.
        route = [setup]
    if route is None:
        roots = [current.get("stock_in") for current in records(bundle.plan.get("setups"))]
        return unknown(f"untraceable stock_in lineage for {face}: {roots!r}")
    stock = mapping(bundle.plan.get("stock"))
    supplied = records(stock.get("as_is_faces"))
    components = {f"stock.{component['id']}" for component in records(stock.get("components"))}
    if not _native_basis(frame_axes(setup_frame(bundle, setup))):
        return unknown(f"{face} has no finite unit-axis receiving setup frame")
    boxes, reason = _kernel_face_boxes(bundle, target, setup_frame(bundle, setup))
    if boxes is None:
        roots = [
            source
            for current in route
            for source in (
                current["stock_in"]
                if isinstance(current["stock_in"], list)
                else [current["stock_in"]]
            )
            if source in components
        ]
        detail = f"{face} on {', '.join(dict.fromkeys(roots))}: " if roots else ""
        return unknown(f"{detail}{reason}")
    if current_refs is not None:
        boxes = [(ref, box) for ref, box in boxes if ref in current_refs]
    scale = UNIT_MM[bundle.features["units"]]
    tolerance = LENGTH_TOLERANCE_MM / scale
    groups = _carried_native_plane_groups(
        bundle, route, setup, face, boxes, current=current_refs is not None
    )
    if not groups:
        return unknown(
            f"{face} needs exact native plane heights in the receiving frame "
            "(native evidence gap: https://github.com/pedropaulovc/prechips/issues/203)"
        )
    refs = [ref for ref, _ in boxes]
    kernel = mapping(getattr(bundle, "kernel", None))
    mapping_refs = mapping(kernel.get("mapping"))
    supply_gaps = []
    outputs = {}

    def seed(current, incoming, source, ref):
        present, plane = source == "stock" and ref in supplied, None
        if source in components and ref not in supplied:
            supply_gaps.append(f"{source} face {face} ({ref}) is not declared stock as-is")
        if source in components and ref in supplied:
            if incoming != [source]:
                present = UNKNOWN
                supply_gaps.append(
                    f"{source} as-is face {face} ({ref}) needs a single-component stock root"
                )
            else:
                plane, reason = _component_supply_plane(bundle, current, source, face, ref)
                named = mapping(current.get("stock_state"))
                present = plane is not None
                if reason and face in (named.get("top_feature"), named.get("bottom_feature")):
                    present = UNKNOWN
                # An unrelated component does not supply this named face. Its
                # missing proof is reported if no component actually supplies it.
                if reason:
                    supply_gaps.append(reason)
        return {
            "present": present,
            "plane": plane,
            "normal": None,
            "area_unknown": False,
            "excluded_mm": 0.0,
        }

    for current in route:
        receiving = current.get("id") == setup.get("id")
        incoming = current.get("stock_in")
        incoming = incoming if isinstance(incoming, list) else [incoming]
        state = {}
        for ref in refs:
            inputs = [
                outputs[source][ref] if source in outputs else seed(current, incoming, source, ref)
                for source in incoming
            ]
            present = (
                UNKNOWN
                if any(row["present"] == UNKNOWN for row in inputs)
                else any(row["present"] is True for row in inputs)
            )
            carrying = [row for row in inputs if row["present"] is True]
            origins = {
                row["plane"]["source"]
                if row["plane"] is not None
                else tuple(row["normal"])
                if row["normal"] is not None
                else None
                for row in carrying
            }
            if len(origins) > 1:
                present = UNKNOWN
            plane = carrying[0]["plane"] if carrying else None
            normal = carrying[0]["normal"] if carrying else None
            if plane is None and present is True and "stock" in incoming:
                plane = _native_plane_geometry(bundle, current, face, [ref])
                if plane is None and {**target, "faces": [ref]} == target:
                    supplied_geometry = {}
                    _native_scene_plane(bundle, current, face, supplied_geometry)
                    plane = supplied_geometry or None
            state[ref] = {
                "present": present,
                "plane": plane,
                "normal": normal,
                "area_unknown": any(row["area_unknown"] for row in inputs),
                "excluded_mm": max((row["excluded_mm"] for row in carrying), default=0.0),
            }
        stock_facts = mapping(mapping(kernel.get("setups")).get(current.get("id")))
        stock_debt = bool(stock_facts.get("stock_reason")) or (
            not receiving and bool(stock_facts.get("stock_out_reason"))
        )
        if stock_debt:
            for row in state.values():
                if row["present"] is not False:
                    row["present"] = UNKNOWN
                    row["area_unknown"] = True
        ops = records(current.get("ops"))
        if receiving:
            ops = ops[:done]
        for op in ops:
            cuts = True if op.get("do") in HAND_FINISH else cutting_action(op)
            if cuts is False:
                continue
            claims, away, invalid = op_claims(bundle, kernel, current, op)
            forms = forms_face(bundle, current, op)
            framed = _framed(current, op)
            for ref in refs:
                surface = {**target, "faces": [ref]}
                row = state[ref]
                produced, plane, normal = False, None, None
                # The touch's own setup producer goes through this same survival
                # ledger; its admissibility is _producer's, not op claims.
                local = receiving and current_refs is not None
                potential = (
                    (not receiving or local)
                    and cuts is not False
                    and (
                        local
                        and (op.get("feature") == face or op.get("do") in FACING | POCKETING)
                        or not local
                        and (
                            claims is None
                            and op.get("feature") == face
                            or claims is not None
                            and mapping_refs[ref] in claims
                        )
                    )
                    and forms is not False
                    and framed
                )
                if potential and (
                    stock_debt
                    or cuts is not True
                    or forms is not True
                    or not local
                    and claims is None
                    or away
                    or invalid
                    or not _native_basis(frame_axes(setup_frame(bundle, current)))
                ):
                    row["present"] = UNKNOWN
                    row["plane"] = row["normal"] = None
                    row["area_unknown"] = True
                    continue
                coverage = cut_coverage(bundle, current, op, target) if potential else None
                if coverage == UNKNOWN:
                    row["present"] = UNKNOWN
                    row["plane"] = row["normal"] = None
                    row["area_unknown"] = True
                    continue
                if (
                    potential
                    and coverage == "whole"
                    and ref in (_native_surface_planes(bundle, current, face, op.get("to_z")) or ())
                ):
                    formed = formed_z(bundle, current, op)
                    if not number(formed) or not math.isfinite(formed):
                        # An eligible native producer with unresolved physical
                        # height is potential supply, not proven absence.
                        row["present"] = UNKNOWN
                        row["plane"] = row["normal"] = None
                        continue
                    plane = _native_plane_geometry(bundle, current, face, [ref])
                    native, _ = _kernel_face_boxes(bundle, surface, setup_frame(bundle, current))
                    to_z = op.get("to_z")
                    if native is not None and number(to_z):
                        produced = all(
                            abs(z - to_z) <= tolerance for _, box in native for z in box[2]
                        )
                    if not produced and number(to_z):
                        if plane is not None:
                            produced = abs(plane["z_mm"] / scale - to_z) <= tolerance
                        elif surface == target:
                            scene_geometry = {}
                            height = _native_scene_plane(bundle, current, face, scene_geometry)
                            produced = number(height) and abs(height - to_z) <= tolerance
                            plane = scene_geometry or None
                    if produced and plane is not None:
                        plane["formed_z_mm"] = formed * scale
                        produced = number(_plane_in_frame(bundle, plane, setup))
                    elif produced:
                        side = face_normal_z(bundle, current, face, to_z)
                        if side not in (1, -1):
                            detail = mapping(
                                mapping(kernel.get("ops")).get(f"{current['id']}:{op['op']}")
                            )
                            side = detail.get("faced_side")
                        if (
                            side not in (1, -1)
                            and op.get("do") in FACING | POCKETING
                            and mapping(resolve(bundle, "machines", current.get("machine"))).get(
                                "kind"
                            )
                            == "mill"
                            and approach(bundle, current, op) == "axial"
                        ):
                            # The native axial mill model cuts down setup -Z, leaving
                            # its floor facing source +Z. Rotary/unknown approaches
                            # and a box alone establish no outward direction.
                            side = 1
                        if number(side) and side in (1, -1):
                            source_frame = setup_frame(bundle, current)
                            normal = [side * v for v in frame_axes(source_frame)[2]]
                            plane = {
                                "source": current["id"],
                                "frame": source_frame,
                                "z_mm": to_z * scale,
                                "formed_z_mm": formed * scale,
                                "normal_z": side,
                            }
                            produced = _native_normal_up(
                                normal, frame_axes(setup_frame(bundle, setup))
                            )
                        else:
                            row["present"] = UNKNOWN
                            row["plane"] = row["normal"] = None
                            continue
                if produced:
                    # Re-facing does not fill either a bounded or an unknown hole.
                    # The latter debt survives every cut on this same stock route. A
                    # kept-off radius is about the plane's own centre: a re-face about
                    # another centre leaves the old exclusion's extent unproven.
                    if row["excluded_mm"] > 0 and not _same_plane_axis(bundle, row["plane"], plane):
                        row["area_unknown"] = True
                    row["plane"] = plane
                    row["normal"] = normal
                    row["present"] = UNKNOWN if row["area_unknown"] else True
                elif row["present"] is not False:
                    excluded = []
                    if cuts is None or _carry_cut(
                        bundle,
                        current,
                        op,
                        surface,
                        row["plane"],
                        excluded,
                        row["excluded_mm"],
                        supply_gaps,
                    ):
                        row["present"] = UNKNOWN
                        row["area_unknown"] = True
                    elif excluded:
                        row["excluded_mm"] = max(row["excluded_mm"], *excluded)
        outputs[current["id"]] = state
    state = outputs[setup["id"]]

    def standing(group):
        rows = [state[ref] for ref in group["refs"]]
        if not all(row["present"] is True and row["plane"] is not None for row in rows):
            return None
        heights = [_plane_in_frame(bundle, row["plane"], setup) for row in rows]
        if not all(number(z) and math.isfinite(z) for z in heights):
            return None
        return max(heights) if max(heights) - min(heights) <= tolerance else None

    def could_face_up(group):
        """A proven wrong-way native member cannot be an eligible physical candidate."""
        receiving_axes = frame_axes(setup_frame(bundle, setup))
        for ref in group["refs"]:
            plane = state[ref]["plane"]
            planes = (
                [plane]
                if plane is not None
                else [
                    _native_plane_geometry(bundle, source, face, [ref])
                    for source in route
                    if source.get("id") != setup.get("id")
                ]
            )
            for native in planes:
                if native is None:
                    continue
                axes = frame_axes(native["frame"])
                if not _native_basis(axes) or native.get("normal_z") not in (1, -1):
                    continue
                normal = [native["normal_z"] * v for v in axes[2]]
                if not _native_normal_up(normal, receiving_axes):
                    return False
        return True

    if len(groups) == 1:
        # Keep the established single-plane contradiction check: credit its
        # physical standing plane, then compare the authored edge separately.
        selected = groups[0]
    else:
        physical = [standing(group) for group in groups]
        matches = [
            group
            for group, height in zip(groups, physical, strict=True)
            if abs(group["z"] - edge) <= tolerance
            or number(height)
            and abs(height - edge) <= tolerance
        ]
        if len(matches) > 1:
            return unknown(f"{face} edge {edge:g} matches multiple distinct native plane groups")
        if any(
            (
                any(state[ref]["present"] == UNKNOWN for ref in group["refs"])
                or any(state[ref]["present"] is True for ref in group["refs"])
                and height is None
            )
            and could_face_up(group)
            for group, height in zip(groups, physical, strict=True)
        ):
            detail = f" ({'; '.join(dict.fromkeys(supply_gaps))})" if supply_gaps else ""
            return unknown(f"{face} has incomplete eligible carried-plane height proof{detail}")
        if not matches:
            known = ", ".join(f"{group['z']:g}" for group in groups)
            carried = ", ".join(f"{z:g}" for z in physical if number(z))
            detail = (
                f"edge {edge:g} matches no native plane of {face}; "
                f"known native heights are {known}"
                f"; eligible as-cut heights are {carried or 'none'}"
            )
            if errors is not None:
                errors.append(detail)
            return unknown(detail)
        selected = matches[0]
    selected_refs = set(selected["refs"])
    raw = selected["z"]
    refs = [ref for ref, _ in boxes if ref in selected_refs]
    if not all(state[ref]["present"] is True for ref in refs):
        detail = f" ({'; '.join(dict.fromkeys(supply_gaps))})" if supply_gaps else ""
        return unknown(
            f"no surviving credited stock plane with a bounded touch area for {face}{detail}"
        )
    if any(
        state[ref]["plane"] is None
        and not _native_normal_up(state[ref]["normal"], frame_axes(setup_frame(bundle, setup)))
        for ref in refs
    ):
        return unknown(f"carried {face} has no proven +Z outward normal in the receiving frame")
    heights = [
        _plane_in_frame(bundle, state[ref]["plane"], setup)
        if state[ref]["plane"] is not None
        else None
        for ref in refs
    ]
    if any(
        state[ref]["plane"] is not None and not number(z)
        for ref, z in zip(refs, heights, strict=True)
    ):
        return unknown(f"carried {face} has no finite +Z native plane in the receiving rigid frame")
    if all(number(z) for z in heights):
        if max(heights) - min(heights) > tolerance:
            return unknown(f"carried {face} has no single consistent as-cut physical plane")
        raw = max(heights)
    elif any(number(z) for z in heights):
        return unknown(
            f"carried {face} needs its exact source native plane or stock-proven datum "
            "(native evidence gap: https://github.com/pedropaulovc/prechips/issues/203)"
        )
    if credited is not None:
        credited.extend(refs)
    if constraint is not None:
        if current_refs is None:
            # Only a carried plane has an imported native nominal; a current
            # producer keeps its exact local DRO comparison.
            native_heights = [
                _plane_in_frame(bundle, state[ref]["plane"], setup, physical=False)
                if state[ref]["plane"] is not None
                else None
                for ref in refs
            ]
            if all(number(z) for z in native_heights):
                constraint["native_edge_mm"] = max(native_heights)
        constraint["touch_exclusion_dia_mm"] = round(
            2 * max(state[ref]["excluded_mm"] for ref in refs), 9
        )
    return raw


def _retouch_recipe(recipe):
    """A listed contact retouch is not the primary zero's measured setting."""
    touch = {**recipe, "from": recipe.get("from", UNKNOWN)}
    if touch.get("method") in MEASURED:
        del touch["method"]
    return touch


def _credited_side(bundle, setup, touch, face, edge):
    """A native-plane credit is usable only from a determinable +Z side.

    Axis recipes name their approach in ``from``; a tool touch on a resolved mill
    comes down from above. A lathe tool touch needs its known face normal or
    blade corner, never the ordinary touch's fallback to +Z.
    """
    machine = resolve(bundle, "machines", setup.get("machine")) or {}
    lathe = lathe_setup(bundle, setup)
    if "from" in touch:
        side = {"+z": 1, "-z": -1}.get(touch["from"], UNKNOWN)
        if side != 1:
            return side
        if lathe:
            return touch_side(bundle, setup, touch, face, edge, lathe)
        return 1 if machine.get("kind") == "mill" else UNKNOWN
    if machine.get("kind") == "mill":
        return 1
    if lathe_setup(bundle, setup):
        normal = face_normal_z(bundle, setup, face, edge)
        if normal != UNKNOWN:
            return normal
        corner = touch_corner(bundle, setup, touch, face, edge)
        if corner is not None:
            return SIDES.get(corner["reference_corner"], UNKNOWN)
    return UNKNOWN


def paper_offset(paper_mm, side):
    """Where a Z touch through ``paper_mm`` of paper stands off its face along setup Z: the
    paper lies on the ``side`` (:func:`touch_side`) the tool meets the face from, so the
    contact is ``edge + side * paper``. No paper needs no side; an unknown side or paper
    otherwise leaves it unknown. The paper itself is never negative."""
    if not number(paper_mm):
        return UNKNOWN
    if paper_mm == 0:
        return paper_mm
    return side * paper_mm if side in (1, -1) else UNKNOWN


def _position(ops, record):
    """The index of the op a touch is made before: the first of its ``before_ops``, else
    the op after its ``after_op``; None when neither names one of ``ops``."""
    names = [str(op.get("op")) for op in ops]
    before = record.get("before_ops")
    named = [
        names.index(str(n))
        for n in (before if isinstance(before, list) else [before])
        if str(n) in names
    ]
    if named:
        return min(named)
    after = str(record.get("after_op"))
    return names.index(after) + 1 if after in names else None


def _boundary(ops, record):
    """The index of the op a Z touch is made before, as :func:`_position`, but with every
    declared name required to resolve: an empty or partly unresolved ``before_ops``, or an
    unresolved ``after_op``, is UNKNOWN, never the initial boundary. A touch declaring
    neither is made before the first op."""
    names = [str(op.get("op")) for op in ops]
    if "before_ops" in record:
        before = record["before_ops"]
        before = before if isinstance(before, list) else [before]
        if not before or any(str(n) not in names for n in before):
            return UNKNOWN
        return min(names.index(str(n)) for n in before)
    after = record.get("after_op")
    if after is None:
        return 0
    return names.index(str(after)) + 1 if str(after) in names else UNKNOWN


def _features(op):
    """The features an op cuts; None when the plan does not name them."""
    feature = op.get("feature")
    names = feature if isinstance(feature, list) else [feature]
    if not names or any(not isinstance(n, str) or n in {"", UNKNOWN} for n in names):
        return None
    return set(names)


def _top_cut(op, names, top_feature):
    """The feature through which face op ``op`` cuts the stock top: the stock's
    ``top_feature`` when the op names it, else (no top feature: every face op is the
    top's) the op's single feature, else None; False when it does not face the top and
    UNKNOWN when the top's feature is unresolved."""
    if op.get("do") not in FACING:
        return False
    if top_feature in {"", UNKNOWN}:
        return UNKNOWN
    if top_feature is not None:
        return top_feature if top_feature in names else False
    return min(names) if len(names) == 1 else None


def _rectangle(bundle, setup, target):
    """(rectangle, land) when ``target``'s surface is known to fill its setup-frame X/Y
    footprint (:func:`_setup_footprint`), else None: the X/Y rectangle it is known to hold
    surface over and :data:`TOUCH_LAND_MM`, both in plan units. The evidence is the
    kernel's one STEP face for it (``faces``): a plane that fills its own box
    (``fills_bbox``: one wire, every edge a straight segment within the kernel's side
    tolerance of a side of the box, and more area than that band along its sides), flat in
    setup Z, with each corner of the box on a corner of its setup X/Y box, which is the
    footprint. The rectangle is that box less :data:`FILL_MARGIN_MM` and the corner
    tolerance on every side, where a notch may still run. Without a kernel result, or for
    a face set of other than one face, a round, holed, notched or L-shaped face, or one
    turned against the setup axes, the box's corners may hold no surface at all, however
    little area the face lacks."""
    from .coordinates import frame_point

    footprint = _setup_footprint(bundle, setup, target)
    kernel, refs = mapping(getattr(bundle, "kernel", None)), records(target.get("faces"))
    scale = {"mm": 1.0, "in": 25.4}.get(bundle.features.get("units"))
    if footprint is None or kernel.get("status") != "ok" or len(refs) != 1 or scale is None:
        return None
    index = mapping(kernel.get("mapping")).get(refs[0])
    faces = [mapping(f) for f in records(kernel.get("faces"))]
    face = next((f for f in faces if index is not None and f.get("index") == index), {})
    box = face.get("bbox_mm")
    if not (
        face.get("kind") == "Plane"
        and face.get("fills_bbox") is True
        and isinstance(box, list)
        and len(box) == 6
        and all(number(v) for v in box)
    ):
        return None
    frame = setup_frame(bundle, setup)
    ends = [[box[i] / scale, box[i + 3] / scale] for i in range(3)]
    corners = [frame_point(list(p), frame) for p in product(*ends)]
    if not all(number(v) for p in corners for v in p):
        return None
    spans = [[min(p[i] for p in corners), max(p[i] for p in corners)] for i in range(3)]
    tolerance = LENGTH_TOLERANCE_MM
    square = all(min(abs(p[i] - v) for v in spans[i]) <= tolerance for p in corners for i in (0, 1))
    same = all(
        abs(a - b) <= tolerance
        for span, side in zip(spans[:2], footprint, strict=True)
        for a, b in zip(span, side, strict=True)
    )
    if spans[2][1] - spans[2][0] > tolerance or not square or not same:
        return None
    margin = FILL_MARGIN_MM / scale + tolerance
    return [[low + margin, high - margin] for low, high in spans[:2]], TOUCH_LAND_MM / scale


def _uncut(rectangle, land, regions):
    """Whether a ``land`` by ``land`` square of X/Y ``rectangle`` lies outside every X/Y
    region (it may touch one). Such a square's low corner lies in the rectangle less
    ``land`` at its high ends, and overlaps a region when strictly inside it grown by
    ``land`` at its low ends. The free corners, if any, include a crossing or midpoint of
    the lines through all these ends."""
    lows = [(low, high - land) for low, high in rectangle]
    grown = [[(r[axis][0] - land, r[axis][1]) for axis in (0, 1)] for r in regions]
    lines = []
    for axis, (low, high) in enumerate(lows):
        if high < low:
            return False
        ends = sorted({low, high, *(v for g in grown for v in g[axis] if low < v < high)})
        lines.append({*ends, *((a + b) / 2 for a, b in pairwise(ends))})
    return any(
        not any(g[0][0] < x < g[0][1] and g[1][0] < y < g[1][1] for g in grown)
        for x in lines[0]
        for y in lines[1]
    )


def _cuts(bundle, setup, event, states, start, end):
    """(state, scars) of a touched or faced Z surface over ops ``start`` to ``end``.

    State is False once one of these ops cut it whole (:func:`cut_coverage`; the stock
    top: faced the top feature) to another or no stated Z, or cut it other than by
    facing/pocketing; None (unknown) when the surface is unnamed, an op cut a feature
    the plan (or the stock's top feature) does not name, or a coverage is unknown; else
    True. Scars are the (feature, X/Y region) of each op that cut only part of it."""
    features = mapping(bundle.feature_definitions)
    top_feature = mapping(setup.get("stock_state")).get("top_feature")
    gone, unproven, scars = False, event["face"] in {None, "", UNKNOWN}, []
    for op, _, _ in states[start:end]:
        action = op.get("do")
        if action in MANUAL:
            continue
        names = _features(op)
        if names is None:
            unproven = True
            continue
        cut = event["face"] if event["face"] in names else False
        if cut is False and event["top"]:
            cut = _top_cut(op, names, top_feature)
        if cut is False:
            continue
        if cut == UNKNOWN:
            unproven = True
            continue
        to_z = op.get("to_z")
        if action in FACING | POCKETING and number(to_z) and number(event["z"]):
            if abs(to_z - event["z"]) <= LENGTH_TOLERANCE_MM:
                continue
        coverage = cut_coverage(bundle, setup, op, mapping(features.get(cut)))
        if coverage == "partial":
            scars.append((cut, cut_region(op)))
        gone |= coverage == "whole"
        unproven |= coverage not in {"whole", "partial"}
    return (False if gone else None if unproven else True), scars


def _standing(bundle, setup, event, states, index):
    """Whether a touched or faced Z surface still stands at op ``index``.

    The surface is tracked across the ops since the event (:func:`_cuts`). A touch
    carries what the ops since its surface was made left of it: not ``proven`` when
    those ops may have cut it away, and their partial cuts as ``scars``. Ops that each
    cut only part of it, before or since the event, leave it at its uncut Z only while
    a square land of the rectangle it is known to hold (:func:`_rectangle`) lies outside
    all of their regions (:func:`_uncut`); else, or with more than one feature named for
    it, None (unknown)."""
    state, scars = _cuts(bundle, setup, event, states, event["index"], index)
    # A touch does not prove what cuts before it left of its surface.
    state = state if event["proven"] or state is False else None
    scars = event["scars"] + scars
    if scars and state:
        names = {name for name, _ in scars}
        target = mapping(mapping(bundle.feature_definitions).get(min(names)))
        held = _rectangle(bundle, setup, target)
        if len(names) > 1 or held is None or not _uncut(*held, [r for _, r in scars]):
            return None
    return state


def _tops(bundle, setup, states):
    """(Z, made) of the stock top before each op and after the last: the incoming top
    (made before op 0), then each face op that wholly cuts the top feature makes a new
    top at its ``to_z``; Z unknown when that top states no Z or is not proven still to
    stand (:func:`_standing`)."""
    stock = mapping(setup.get("stock_state"))
    features = mapping(bundle.feature_definitions)
    z = stock.get("top_z", UNKNOWN)
    track = {"index": 0, "face": "top", "z": z, "top": True, "scars": [], "proven": True}
    tops = []
    for index in range(len(states) + 1):
        standing = _standing(bundle, setup, track, states, index) is True
        tops.append((track["z"] if number(track["z"]) and standing else UNKNOWN, track["index"]))
        op = states[index][0] if index < len(states) else {}
        names = _features(op)
        cut = _top_cut(op, names, stock.get("top_feature")) if names else False
        if cut not in {False, UNKNOWN}:
            if cut_coverage(bundle, setup, op, mapping(features.get(cut))) == "whole":
                z = op.get("to_z") if number(op.get("to_z")) else UNKNOWN
                track = {**track, "index": index + 1, "z": z}
    return tops


def _turned_standing(event, states, index):
    """A diameter turned before op ``event["index"]`` stands at op ``index`` unless an op
    since cut that feature other than by turning it, or cut a feature the plan does not
    name."""
    for op, _, _ in states[event["index"] : index]:
        if op.get("do") in MANUAL:
            continue
        names = _features(op)
        if names is None or (event["x_face"] in names and op.get("do") not in TURNED):
            return False
    return True


def _named(value):
    return isinstance(value, str) and value.strip() not in {"", UNKNOWN}


def x_face_state(bundle, setup, touch, x_recipe, states, index):
    """(status, reason) of the diameter an authored lathe X touch measures, at op
    ``index`` (D2: the zero is set on the surface actually touched; unknown is not pass).

    A touch that trial-cuts (``x_method = "trial_cut_measure"``) makes its own diameter.
    ``x_face = "x_zero"`` is this setup's X-zero trial-cut land: it needs a trial-cut X
    zero made before the touch and stands until a cutting op runs after the zero, when
    whether that cut took it is unknown (the land is no plan feature to follow). Any other
    ``x_face`` is a plan feature: the latest op naming it before the touch (this setup,
    then the earlier setups of its stock lineage) must turn it, or it must be supplied
    as-is and never cut; an op naming no feature since leaves it unknown, and so does a
    feature turned only upstream of an undeclared stock route. Without ``x_face`` the
    words name no surface the rule can follow: unknown."""
    if touch.get("x_method") == "trial_cut_measure":
        return "pass", None
    face = touch.get("x_face")
    if not _named(face):
        return UNKNOWN, "names no x_face"
    if face == "x_zero":
        ops = [op for op, _, _ in states]
        made = _position(ops, {"after_op": x_recipe.get("after_op")}) or 0
        if x_recipe.get("method") != "trial_cut_measure":
            return "error", "touches the X zero's trial-cut land, but the X zero cuts none"
        if index < made:
            return "error", "touches the X zero's trial-cut land before the zero cuts it"
        cut = next((op for op in ops[made:index] if op.get("do") not in MANUAL), None)
        if cut is not None:
            return UNKNOWN, f"touches the X zero's trial-cut land after op {cut['op']} cut"
        return "pass", None
    if face not in mapping(bundle.feature_definitions):
        return "error", f"names x_face {face}, no plan feature"
    lineage = setup_lineage(bundle.plan, setup["id"])
    earlier = [
        (other["id"], op)
        for other in bundle.plan["setups"]
        if other["id"] in lineage - {setup["id"]}
        for op in records(other.get("ops"))
    ]
    history = earlier + [(setup["id"], op) for op, _, _ in states[:index]]
    for owner, op in reversed(history):
        if op.get("do") in MANUAL:
            continue
        names = _features(op)
        where = f"{owner} op {op.get('op')}"
        if names is None:
            return UNKNOWN, f"touches {face} after {where}, which names no feature"
        if face in names:
            if op.get("do") in TURNED:
                return "pass", None
            return "error", f"touches {face} after {where} cut it other than by turning"
    faces = mapping(bundle.feature_definitions.get(face)).get("faces", UNKNOWN)
    as_is = mapping(bundle.plan.get("stock")).get("as_is_faces", UNKNOWN)
    if known_refs(faces) and isinstance(as_is, list) and set(faces) <= set(as_is):
        return "pass", None
    if not all("stock_in" in other for other in bundle.plan["setups"] if other["id"] in lineage):
        return UNKNOWN, f"touches {face}, whose turning upstream is not routed to this setup"
    return "error", f"touches {face} before any op turns it"


def same_tool(bundle, first, second):
    """Whether two tool references name one spindle tool (:func:`identity`): ``turner`` on a
    touch and ``tools.turner`` on an op are one tool. None (no tool) is never a tool."""
    return (
        first is not None
        and second is not None
        and identity(bundle, first, "spindle") == identity(bundle, second, "spindle")
    )


def tool_changes(bundle, setup, zero, lathe, x_scale, touches):
    """One DRO per setup: each cutting op runs on Axis Sets its own tool made.

    The DRO reads the tool that last set it: the zero, a tool touch or a listed retouch
    (which serves the next tool only); an axis with no zero recipe has no setter until a
    touch. A cutting op with another tool is touched off
    first, derived here: Z on the latest touched or wholly faced surface proven to stand
    (:func:`_standing`) at a known plan Z (its paper, on the side the surface was met
    from: :func:`touch_side`; a faced surface takes the zero's paper), never a measured
    one, else on the latest surface not proven gone, with Z and Axis Set unknown
    (unknown); a touched top is the top as the ops before it left it (:func:`_tops`). On a
    lathe, X on
    the latest diameter turned in the setup that still stands, set as the measured
    diameter. A touch's X surface is prose the rule cannot follow past a cut, so it is
    never repeated. Tailstock tools on a lathe never read the carriage DRO; a cut by an
    unknown tool leaves the DRO's setter unknown; an incoming tool that does not
    resolve unflagged keeps its touch unknown, as an authored touch is. A touch naming
    none of the setup's ops serves none. Returns (derived touches, missing touches,
    unknown, readings, served): ``readings`` maps each cutting op to the Z touch record its
    DRO Z reads (the zero's recipe, a tool touch, a derived re-touch or a listed retouch of
    the top), None when no touch of its tool set Z; ``served`` maps each listed retouch's
    op to the cutting op that reads it (``next_op``), that op's tool (``next_tool``) and
    whether it is another tool than the last one that cut (``tool_change``: it goes in
    before the touch); a cut by an unknown tool leaves both unknown."""
    from .coordinates import dro_grid, dro_z

    ops = records(setup.get("ops"))
    states = list(stock_states(bundle, setup))
    features = mapping(bundle.feature_definitions)
    recipe, x_recipe = mapping(zero.get("z")), mapping(zero.get("x"))
    paper = recipe.get("paper_mm", UNKNOWN)
    face = recipe.get("face", recipe.get("feature"))
    start = _position(ops, {"after_op": recipe.get("after_op")}) or 0
    tops = _tops(bundle, setup, states)
    grid = dro_grid(bundle, setup)
    # A top pickup touches the top as the ops through its after_op left it.
    zero_z = tops[start][0] if face == "top" else recipe.get("edge_mm", UNKNOWN)
    placed, unknown = {}, False
    for touch in touches:
        placed.setdefault(_position(ops, touch), []).append(touch)
    listed = {str(n) for n in records(recipe.get("retouch_after"))}
    z_events, x_events, derived, missing = [], [], [], []
    # The Z touch the DRO reads (its tool, face and edge), per cutting op.
    z_by, readings = None, {}
    # Ops before the zero's after_op run before any tool set the Z DRO; with no zero
    # recipe no tool set it at all (the missing zero is reported, not a tool change).
    set_z = None
    set_x, x_gauge = (None, None)
    if lathe and x_recipe:
        set_x, x_gauge = x_recipe.get("tool", UNKNOWN), x_recipe.get("gauge")
    # The top a listed retouch touches, for the next cutting tool; the tool that last cut.
    pending, spindle, served = None, None, {}

    def z_event(index, surface, z, touch_paper, source, touch=None, made=False):
        event = {
            "index": index,
            "face": surface,
            "z": z if number(z) else UNKNOWN,
            "paper": touch_paper,
            "side": touch_side(bundle, setup, touch or {}, surface, z, lathe),
            "top": surface == "top",
            "source": source,
            "made": made,
        }
        # A touch on a surface made earlier carries what the ops since left of it, and
        # repeats it only at the Z that op made; on the top, at the tracked top's Z.
        maker = [e for e in z_events if e["made"] and e["face"] == surface]
        if event["top"]:
            since, at = tops[index][1], tops[index][0]
        elif maker and not made:
            since, at = maker[-1]["index"], maker[-1]["z"]
        else:
            since, at = (index if made else 0), z
        agrees = (
            number(at)
            and number(z)
            and (abs(at - z) <= LENGTH_TOLERANCE_MM or dro_z(at, grid) == z)
        )
        state, event["scars"] = _cuts(bundle, setup, event, states, since, index)
        event["proven"] = state is True and agrees
        z_events.append(event)

    for index, (op, _, _) in enumerate(states):
        if index == start and recipe:
            set_z = recipe.get("tool", UNKNOWN)
            z_by = {
                **recipe,
                "tool": set_z,
                "z_face": face,
                "edge_mm": zero_z,
                "from": recipe.get("from", UNKNOWN),
            }
            if recipe.get("method") not in MEASURED:
                z_event(index, face or UNKNOWN, zero_z, paper, "zero", z_by)
        for touch in placed.get(index, []):
            if touch.get("z_face"):
                set_z, z_by = touch.get("tool", UNKNOWN), touch
                if touch.get("method") != "measure_then_set":
                    z_event(
                        index,
                        touch["z_face"],
                        touch.get("edge_mm"),
                        touch.get("paper_mm", UNKNOWN),
                        f"tool touch before op {op['op']}",
                        touch,
                    )
            if lathe:
                set_x, x_gauge = touch.get("tool", UNKNOWN), touch.get("gauge", x_gauge)
        tool = op.get("tool", UNKNOWN)
        cuts = op.get("do") not in MANUAL | SAW_OPS and not (
            lathe and approach(bundle, setup, op) == "axial"
        )
        if cuts and tool in (None, UNKNOWN):
            # Whether an unknown tool takes the DRO over from its setter is unknown.
            if pending:
                served[str(pending["after_op"])] = {
                    "next_op": op["op"],
                    "next_tool": UNKNOWN,
                    "tool_change": UNKNOWN,
                }
            unknown, pending, spindle = True, None, UNKNOWN
            set_z = None if set_z is None else UNKNOWN
            set_x = None if set_x is None else UNKNOWN
        cutting = cuts and tool not in (None, UNKNOWN)
        if cutting and pending:
            served[str(pending["after_op"])] = {
                "next_op": op["op"],
                "next_tool": tool,
                "tool_change": UNKNOWN
                if spindle == UNKNOWN
                else not same_tool(bundle, spindle, tool),
            }
            set_z, z_by, pending = tool, {"tool": tool, **pending}, None
        changed = [
            axis
            for axis, current in (("x", set_x), ("z", set_z))
            if current is not None and not same_tool(bundle, current, tool)
        ]
        if cutting and changed:
            resolved = resolve(bundle, "tools", tool)
            unknown |= UNKNOWN in (set_x, set_z) or not resolved or uncertain(resolved)
            record, lost = {"before_ops": [op["op"]], "tool": tool}, []
            if "z" in changed:
                standing = [
                    (e, s)
                    for e in z_events
                    if (s := _standing(bundle, setup, e, states, index)) is not False
                ]
                proven = [e for e, s in standing if s and number(e["z"])]
                source = (proven or [e for e, _ in standing] or [None])[-1]
                if source is None:
                    lost.append("z")
                else:
                    # A surface not proven to stand at a known Z repeats no number.
                    edge = source["z"] if source in proven else UNKNOWN
                    offset = paper_offset(source["paper"], source["side"])
                    # The source's own recipe names its tool's edge (a blade corner);
                    # the incoming tool repeats the surface in tool-neutral words, from
                    # the same side through the same paper.
                    record.update(
                        z_face=source["face"],
                        edge_mm=edge,
                        paper_mm=source["paper"],
                        z_axis_set=edge + offset if number(edge) and number(offset) else UNKNOWN,
                        method="edge_then_set" if lathe else "touch_then_set",
                        repeats=source["source"],
                    )
            if "x" in changed:
                source = next(
                    (e for e in reversed(x_events) if _turned_standing(e, states, index)), None
                )
                if source is None:
                    lost.append("x")
                else:
                    shown = measured(x_scale)
                    ready = shown != UNKNOWN and gauge_ready(bundle, source["gauge"])
                    # A direct touch on the measured diameter: its Axis Set counts no paper.
                    record.update(
                        x_face=source["x_face"],
                        x_paper_mm=0.0,
                        gauge=source["gauge"],
                        x_axis_set=f"measured {shown}" if ready else UNKNOWN,
                    )
            if lost:
                z_by = None if "z" in lost else z_by
                by = set_z if "z" in lost else set_x
                missing.append(
                    {"before_op": op["op"], "tool": tool, "axes": lost, "dro_set_by": by}
                )
            if len(lost) < len(changed):
                derived.append(record)
                z_by = record if "z" in changed and "z" not in lost else z_by
                unknown |= UNKNOWN in (record.get("z_axis_set"), record.get("x_axis_set"))
            set_z = tool if "z" in changed else set_z
            set_x = tool if "x" in changed else set_x
        if cutting:
            readings[str(op["op"])] = z_by if same_tool(bundle, set_z, tool) else None
            spindle = tool
        if str(op.get("op")) in listed:
            top = tops[index + 1][0]
            pending = {
                "z_face": "top",
                "edge_mm": top,
                "paper_mm": paper,
                "from": recipe.get("from", UNKNOWN),
                # Its Axis Set, as the zero lists it: the top plus its paper.
                "z_axis_set": top + paper if number(top) and number(paper) else UNKNOWN,
                "after_op": op["op"],
            }
            z_event(index + 1, "top", top, paper, f"retouch after op {op['op']}", pending)
        if op.get("do") in FACING | POCKETING:
            # Only a whole cut makes a surface: a partial one leaves it at its uncut Z.
            for name in sorted(_features(op) or ()):
                if (
                    cut_coverage(bundle, setup, op, mapping(features.get(name))) == "whole"
                    and _native_surface_planes(bundle, setup, name, op.get("to_z")) != []
                ):
                    source = f"op {op['op']} {op['do']}"
                    z_event(index + 1, name, op.get("to_z"), paper, source, made=True)
        if lathe and op.get("do") in TURNED:
            for name in sorted(_features(op) or ()):
                x_events.append({"x_face": name, "gauge": x_gauge, "index": index + 1})
    return derived, missing, unknown, readings, served


def lathe_setup(bundle, setup):
    """Whether ``setup`` runs on a lathe: a lathe-kind (or lathe-type) machine."""
    machine = resolve(bundle, "machines", setup.get("machine")) or {}
    return machine.get("kind") == "lathe" or "lathe" in str(machine.get("type", "")).lower()


def z_readings(bundle, setup):
    """{op: Z touch record} for each cutting op of ``setup``: the touch whose Axis Set its
    DRO Z reads (:func:`tool_changes` ``readings``), None when no touch of its tool set Z.
    Empty for a saw setup."""
    if saw_setup(setup):
        return {}
    zero = mapping(setup.get("zero"))
    touches = [touch for touch in records(zero.get("tool_touches")) if isinstance(touch, dict)]
    lathe = lathe_setup(bundle, setup)
    _, _, _, readings, _ = tool_changes(bundle, setup, zero, lathe, UNKNOWN, touches)
    return readings


def carried_z_reading(bundle, setup, op, readings=None):
    """The effective carried touch's physical edge and actual typed Z setting.

    Resolve the touch at its own position, not after the op it serves. This reads
    the same contact recipe as zero_check without evaluating endpoint rules or
    replacing the separate physical/native evidence with a display coordinate.
    None means this op does not read a carried native plane.
    """
    readings = z_readings(bundle, setup) if readings is None else readings
    touch = readings.get(str(op.get("op")))
    if touch is None or touch.get("method") in MEASURED:
        return None
    face, authored = touch.get("z_face"), touch.get("edge_mm")
    native = mapping(setup.get("stock_state")).get("top_feature") if face == "top" else face
    if not _kernel_face(bundle, native):
        return None
    done = _boundary(records(setup.get("ops")), touch)
    edge, credited, carried = _face_checker(bundle, setup, [], [])(
        touch, face, authored, done, "the effective Z touch"
    )
    if number(edge) and (not carried or "native_edge_mm" not in carried):
        return None
    stand_off = paper_offset(
        touch.get("paper_mm", UNKNOWN),
        touch_side(bundle, setup, touch, face, edge, lathe_setup(bundle, setup)),
    )
    row = {
        "edge_mm": edge,
        "paper_offset_mm": stand_off,
        "z_axis_set": edge + stand_off if number(edge) and number(stand_off) else UNKNOWN,
        "native_edge_mm": authored,
    }
    if carried:
        _carried_setting(bundle, setup, row, "z_axis_set", carried)
        row["credited_faces"] = credited
    return row


def reads_unknown(bundle, setup, op, readings=None):
    """Whether ``op`` cuts on a DRO Z set at an unknown place: the Z touch it reads
    (:func:`z_readings`, unless given) has an unknown plan edge or paper stand-off
    (:func:`paper_offset`), or meets a face standing at an unknown Z (:func:`face_stands`).
    A measured touch reads its face."""
    readings = z_readings(bundle, setup) if readings is None else readings
    touch = readings.get(str(op.get("op")))
    if touch is None or touch.get("method") in MEASURED:
        return False
    face, edge = touch.get("z_face"), touch.get("edge_mm")
    if not number(edge):
        return True
    if "z_axis_set" in touch:
        # A derived re-touch or a listed retouch of the top carries its own Axis Set.
        known = number(touch["z_axis_set"])
    else:
        side = touch_side(bundle, setup, touch, face, edge, lathe_setup(bundle, setup))
        known = number(paper_offset(touch.get("paper_mm", UNKNOWN), side))
    if not known:
        return True
    done = _boundary(records(setup.get("ops")), touch)
    if done == UNKNOWN:
        return True
    credited = []
    stands = face_stands(bundle, setup, face, edge, done, credited=credited)
    return (stands is not None and not number(stands)) or (
        bool(credited) and _credited_side(bundle, setup, touch, face, edge) != 1
    )


def blade_readings(bundle, setup, readings=None):
    """{op: corner record} for each grooving/parting-blade op of a lathe setup: the corner
    the DRO Z reads while it cuts (:func:`touch_corner` of the Z touch in effect,
    :func:`z_readings` unless given), with ``reason`` when no touch of that blade set Z.
    Empty off a lathe."""
    if saw_setup(setup) or not lathe_setup(bundle, setup):
        return {}
    readings = z_readings(bundle, setup) if readings is None else readings
    result = {}
    for op in records(setup.get("ops")):
        if not isinstance(op, dict) or not blade(bundle, op.get("tool")):
            continue
        touch = readings.get(str(op.get("op")))
        corner = None
        if touch is not None:
            corner = touch_corner(bundle, setup, touch, touch.get("z_face"), touch.get("edge_mm"))
        result[str(op.get("op"))] = corner or {
            "reference_corner": UNKNOWN,
            "corner_from": UNKNOWN,
            "reason": "no Z touch of this blade sets the DRO before it cuts",
        }
    return result


# How a lathe tool is set before its first touch-off (Moltrecht, below); a toolpost's own
# ``centre_height`` / ``square_blade`` words, when the inventory gives them, say how.
TOOL_SETTING_CITES = [
    "Moltrecht, Machining for Hobbyists: Getting Started (Industrial Press 2015) ch. 6 "
    "p136 Fig. 6-7: the nose of the cutting tool on centre, at the height of the lathe centers",
    "Moltrecht, Machining for Hobbyists: Getting Started (Industrial Press 2015) ch. 6 "
    "p147 Fig. 6-20: a cut-off blade perpendicular to the workpiece axis, its end cutting "
    "edge on center",
]
CENTRE_HEIGHT = "set its cutting edge on spindle centre height"
SQUARE_BLADE = "square the blade to the spindle axis"


def toolpost(bundle, setup):
    """The setup machine's ``toolpost`` record (empty without one)."""
    machine = resolve(bundle, "machines", setup.get("machine")) or {}
    return mapping(mapping(machine).get("toolpost"))


def tool_setting(bundle, setup, zero, touches, derived):
    """Each toolpost tool's setting before its first touch-off in a lathe setup: on centre
    height, and a blade squared to the spindle axis. One record per tool a turning op of
    the setup cuts with (tailstock tools never touch the carriage DRO), at the first of
    the zero (``touch`` "zero", its ``axis``), its ``tool_touches`` or its
    ``derived_touches`` (``index``) that touches it off, in op order. Words come from the
    setup machine's toolpost ``centre_height`` / ``square_blade``, else the requirement
    alone."""
    ops = records(setup.get("ops"))
    # A tool is the item it selects (:func:`identity`), however the op or touch spells it.
    carriage = {
        identity(bundle, op.get("tool"), "spindle")
        for op in ops
        if approach(bundle, setup, op) != "axial"
    }
    words = toolpost(bundle, setup)
    events = [
        (-1, 0, {"touch": "zero", "axis": axis}, mapping(zero.get(axis)).get("tool"))
        for axis in ("x", "z")
    ]
    for kind, rank, rows in (("tool_touches", 1, touches), ("derived_touches", 2, derived)):
        for index, row in enumerate(rows):
            position = _position(ops, row)
            at = len(ops) if position is None else position
            events.append((at, rank, {"touch": kind, "index": index}, row.get("tool")))
    result, seen = [], set()
    for *_, where, tool in sorted(events, key=lambda event: event[:2]):
        key = identity(bundle, tool, "spindle")
        if key in seen or tool in (None, UNKNOWN) or key not in carriage:
            continue
        seen.add(key)
        result.append(
            {
                **where,
                "tool": tool,
                "centre_height": words.get("centre_height", CENTRE_HEIGHT),
                "square_blade": (
                    words.get("square_blade", SQUARE_BLADE)
                    if blade(bundle, tool)
                    else "not_applicable"
                ),
            }
        )
    return result


def _corner_recorder(bundle, setup, lathe, errors):
    """A function adding a blade Z touch's corner record (:func:`touch_corner`) to its
    row, collecting each contradiction into ``errors``; off a lathe it records nothing."""

    def record(row, touch, face, edge, who):
        corner = touch_corner(bundle, setup, touch, face, edge) if lathe and face else None
        if corner is None:
            return
        row.update(corner)
        if "corner_error" in corner:
            errors.append(f"{who} {corner['corner_error']}")

    return record


def face_stands(
    bundle,
    setup,
    face,
    edge,
    done=0,
    source=None,
    debts=None,
    credited=None,
    carried=None,
    errors=None,
):
    """Where ``face`` physically stands once ``setup``'s first ``done`` ops have run.

    A whole producer in this setup under a set Z DRO leaves its :func:`formed_z`,
    not the touch's authored edge; a native one must also have run before the
    touch and survive every later cut through the same ledger as a carried face
    (:func:`_carried_face_z`). An unknown producer or a named native plane without
    a whole eligible producer is unknown unless its exact native face was supplied
    as-is or whole-produced upstream and survives its traced stock route. Carried
    faces rigidly transform the producer's as-cut offset from their exact native
    geometry, never substituting the nominal CAD height for a known cut.
    Other stock faces and faces cut before the producer's Z zero stand where the
    touch sets them (None).
    Optional collectors receive coverage debts, exact raw STEP refs, carried
    touch-footprint constraints and complete multi-plane edge contradictions,
    never metadata on the input dicts.
    """
    from .coordinates import formed_z

    if not number(edge):
        # An unknown top can itself be missing its footprint; retain that input debt.
        if debts is not None:
            _producer(bundle, setup, edge, face, done, source, debts=debts)
        return None
    matched = [] if credited is not None else None
    producer = _producer(bundle, setup, edge, face, done, source, debts=debts, credited=matched)
    native = mapping(setup.get("stock_state")).get("top_feature") if face == "top" else face
    current = producer not in (None, UNKNOWN) and producer[0].get("id") == setup.get("id")
    if current:
        if not any(cut is producer[1] for cut in records(setup.get("ops"))[:done]):
            # The touch's own raw operation cutoff precedes this producer.
            if debts is not None:
                debts.append(
                    f"{setup['id']} op {producer[1].get('op')} has not run before the touch "
                    f"on {native}"
                )
            return UNKNOWN
        planes = _native_surface_planes(bundle, setup, native, producer[1].get("to_z"))
        if planes == []:
            if debts is not None:
                debts.append(f"{native} has no eligible native plane at raw to_z")
            return UNKNOWN
        if planes is not None and matched is not None and not matched:
            matched.extend(planes)
    if _kernel_face(bundle, native) and not current:
        fallback = _producer(bundle, setup, UNKNOWN, face, done, source)
        if fallback not in (None, UNKNOWN) and fallback[0].get("id") == setup.get("id"):
            # Only a producer inside THIS setup keeps its formed-Z/grid check.
            return UNKNOWN
        constraint = {}
        stands = _carried_face_z(
            bundle, setup, native, edge, done, debts, credited, constraint, errors
        )
        if number(stands) and carried is not None:
            carried.append(constraint)
        return stands
    if producer == UNKNOWN:
        return UNKNOWN
    if producer is None:
        return None
    if not _framed(*producer):
        return None
    if current and planes is not None:
        # A same-setup native producer is not an escape hatch: every cut between
        # it and the touch must leave proven land, through the shared ledger.
        constraint = {}
        stands = _carried_face_z(
            bundle,
            setup,
            native,
            edge,
            done,
            debts,
            credited,
            constraint,
            errors,
            current_refs=planes,
        )
        if number(stands) and carried is not None and constraint["touch_exclusion_dia_mm"]:
            # Local keep-off metadata, not a carried coordinate transform.
            carried.append(constraint)
        return stands
    if credited is not None:
        credited.extend(matched)
    return formed_z(bundle, *producer)


def _framed(setup, op):
    """Whether ``setup``'s ``op`` cut under its Z zero: ops before the zero's ``after_op``
    run before any tool set the Z DRO, so the zero, not they, places their faces."""
    ops = records(setup.get("ops"))
    recipe = mapping(mapping(setup.get("zero")).get("z"))
    start = _position(ops, {"after_op": recipe.get("after_op")}) or 0
    return any(cut is op for cut in ops[start:])


def _face_checker(bundle, setup, errors, unknowns):
    """Return the standing physical edge, credited refs and whether it was carried.

    A same-setup producer keeps its exact DRO-step comparison. A carried face's
    authored edge must agree with its transformed native nominal or as-cut height
    within LENGTH tolerance; the +Z Axis Set separately rounds height plus paper
    down to the current display step. Measured touches remain independent. On an
    unverified DRO grid a face's known standing Z still reads unknown.
    """
    from .coordinates import dro_grid, dro_grid_debt, dro_z, formed_z

    grid = dro_grid(bundle, setup)
    grid_debt = dro_grid_debt(bundle, setup)

    def check(touch, face, edge, done, who, source=None):
        if done == UNKNOWN:
            # A touch whose own operation boundary does not resolve stands nowhere
            # known: no surface reading, measured or surveyed, places it.
            unknowns.append(f"{who} on {face} (unknown operation boundary)")
            return UNKNOWN, [], False
        if touch.get("method") in MEASURED or not face:
            return edge, [], False
        debts, credited, carried, contradictions = [], [], [], []
        stands = face_stands(
            bundle, setup, face, edge, done, source, debts, credited, carried, contradictions
        )
        if contradictions:
            errors.extend(f"{who} on {face}: {reason}" for reason in contradictions)
            return UNKNOWN, [], False
        if number(edge) and not number(stands) and not debts:
            # Strict edge matching can reject a real producer. Recover its
            # physical face for the contradiction check below only through the
            # same survival proof, never by copying its refs over a lost area.
            producer = _producer(bundle, setup, UNKNOWN, face, done, source)
            native = mapping(setup.get("stock_state")).get("top_feature") if face == "top" else face
            if (
                producer not in (None, UNKNOWN)
                and _framed(*producer)
                and (not _kernel_face(bundle, native) or producer[0].get("id") == setup.get("id"))
            ):
                candidate = formed_z(bundle, *producer)
                if number(candidate):
                    stands = face_stands(
                        bundle,
                        setup,
                        face,
                        candidate,
                        done,
                        source,
                        debts,
                        credited,
                        carried,
                        contradictions,
                    )
                    if contradictions:
                        errors.extend(f"{who} on {face}: {reason}" for reason in contradictions)
                        return UNKNOWN, [], False
        if stands is None and not debts:
            return edge, [], False
        if not number(stands):
            detail = f" ({'; '.join(debts)})" if debts else ""
            unknowns.append(f"{who} on {face}{detail}")
            return UNKNOWN, [], False
        if credited and _credited_side(bundle, setup, touch, face, stands) != 1:
            unknowns.append(
                f"{who} on {face} (native-plane credit requires a known +Z/above touch)"
            )
            return UNKNOWN, [], False
        if grid_debt:
            # An unverified grid certifies nothing, but the readings stay printed on
            # its nominal step; grid-exactness errors are not judged on it.
            unknowns.append(f"{who} on {face}: {grid_debt}")
        if carried and "native_edge_mm" in carried[0]:
            from .coordinates import UNIT_MM

            tolerance = LENGTH_TOLERANCE_MM / UNIT_MM[bundle.features["units"]]
            nominal = carried[0].get("native_edge_mm")
            if number(edge) and not any(
                number(z) and abs(edge - z) <= tolerance for z in (stands, nominal)
            ):
                errors.append(
                    f"{who} on {face} uses edge {edge:g}; "
                    f"the carried face physically stands at {stands:g}"
                )
            return stands, credited, carried[0]
        if grid_debt:
            return stands, credited, carried[0] if carried else False
        shown_edge = dro_z(edge, grid)
        if number(edge) and shown_edge != stands:
            errors.append(
                f"{who} on {face} uses edge {edge:g} (DRO Z {shown_edge:g}); "
                f"the face stands at {stands:g}"
            )
        shown = dro_z(stands, grid)
        if round(shown - stands, 9):
            errors.append(f"{who} sets {face} as Z {shown:g}, which stands at {stands:g}")
        return stands, credited, carried[0] if carried else False

    return check


def _carried_setting(bundle, setup, row, field, constraint=None):
    """Type a +Z contact height safely down, retaining its nonnegative residual."""
    from .coordinates import UNIT_MM, _grid, dro_grid

    if constraint is not None:
        row.update(constraint)
        if "native_edge_mm" not in constraint:
            # A same-setup plane retains its exact current DRO comparison and
            # Axis Set; only its surviving-land keep-off note is carried here.
            return
    desired = row[field]
    grid = dro_grid(bundle, setup)
    shown = _grid(desired, *grid, True) if number(desired) else UNKNOWN
    if (
        number(shown)
        and shown > desired
        and not math.isclose(
            shown, desired, rel_tol=0.0, abs_tol=4 * max(math.ulp(shown), math.ulp(desired))
        )
    ):
        # Start from the upper printed line: a converted inch step recurs, so
        # its printed line can lie just below the ideal step quotient. Keep
        # that line only for binary roundoff, never a genuinely higher setting.
        shown = round(shown - grid[0], grid[1])
    row[field] = shown
    scale = UNIT_MM.get(bundle.features.get("units"))
    row["setting_residual_mm"] = (
        round((desired - shown) * scale, 9)
        if number(desired) and number(shown) and scale is not None
        else UNKNOWN
    )
    if field == "axis_set":
        for key in ("check_reading", "mirrored_reading"):
            if key in row:
                row[key] = (
                    shown + (row[key] - desired)
                    if number(shown) and number(row[key]) and number(desired)
                    else UNKNOWN
                )


def evaluate(bundle):
    from .coordinates import dro_grid_debt, dro_grid_measurements

    result = []
    dro = mapping(bundle.plan.get("dro"))
    for setup in bundle.plan["setups"]:
        bench = manual_bench(bundle, setup)
        if bench is not None:
            result.append(
                not_applicable("zero_check", setup, bench, "zero recipe", "DRO zero to set")
            )
            continue
        if saw_setup(setup):
            result.append(
                Finding(
                    "zero_check",
                    setup["id"],
                    "not_applicable",
                    {"frame": setup.get("frame", UNKNOWN)},
                    ["PLAN.md §4.1 zero recipe", *plan_frame_cite(bundle, setup)],
                    "A dedicated saw setup locates its cut by cut_plane; no spindle XYZ "
                    "zero is set.",
                )
            )
            continue
        frame = setup_frame(bundle, setup)
        lathe = lathe_setup(bundle, setup)
        zero = mapping(setup.get("zero"))
        ops = records(setup.get("ops"))
        states = list(stock_states(bundle, setup))
        # The top as each op left it, unknown where no stated depth proves it.
        tops = [z for z, _ in _tops(bundle, setup, states)]
        axes = {}
        # Blade Z touches whose authored corner the touched face cannot give. An unknown
        # corner leaves the Axis Set known: the blade ops whose Zs it reads stay unknown
        # under coordinates instead.
        corner_errors = []
        blade_corner = _corner_recorder(bundle, setup, lathe, corner_errors)
        # Z touches that set their DRO off where their face stands, or on a face standing
        # at an unknown Z (:func:`_face_checker`).
        face_errors, face_unknowns = [], []
        face_check = _face_checker(bundle, setup, face_errors, face_unknowns)
        # The edge finder's procedure facts (:func:`finder_procedure`) of each pick-up.
        finder_status = set()
        tip_measurements = []

        unknown = (
            not frame
            or frame.get("binding") == UNKNOWN
            or dro.get("controller", UNKNOWN) == UNKNOWN
            or dro.get("radius_mode") == UNKNOWN
            or dro.get("mode", UNKNOWN) == UNKNOWN
        )
        bad = dro.get("mode", UNKNOWN) not in {"abs", UNKNOWN}
        # A setup whose every spindle op is a guided sweep sets X and Y by touching the
        # cutter to its master and locks them: it picks up no X/Y zero (#255).
        from .guided_sweep import touch_set, trammel_set

        swept = [] if lathe else touch_set(setup)
        # A trammel's rails fix the cut: no X/Y handwheel move, so no X/Y DRO sign (#269).
        railed = bool(swept) and trammel_set(setup)
        # An X/Y pickup moves the table off the rails' crossing the trammel cuts on.
        railed_errors = [
            f"zero.{axis} picks up an edge, but the trammel ({', '.join(map(str, swept))}) "
            "cuts where its rails cross the spindle axis with X and Y locked: remove it"
            for axis in ("x", "y")
            if railed and isinstance(zero.get(axis), dict)
        ]
        for axis in ("x", "y", "z"):
            recipe = zero.get(axis)
            if not isinstance(recipe, dict):
                if axis in ("x", "y") and railed:
                    continue
                if axis in ("x", "y") and swept:
                    # No edge pickup, but the sweep's touch feed and rough back-off still
                    # move this axis by its DRO sign: a reversed or undeclared direction
                    # is the same error or debt it is under a pickup.
                    direction = mapping(dro.get("direction")).get(axis, UNKNOWN)
                    positive, negative = DIRECTIONS[axis]
                    bad |= direction in negative
                    unknown |= direction not in positive and direction not in negative
                    continue
                if axis != "y" or not lathe:
                    unknown = True
                continue
            direction = mapping(dro.get("direction")).get(axis, UNKNOWN)
            positive, negative = DIRECTIONS[axis]
            sign = 1 if direction in positive else -1 if direction in negative else UNKNOWN
            # Frames are installed machine-aligned: a flipped model frame changes
            # the model basis, not the machine's authored right/away/up convention.
            bad |= sign == -1
            edge = recipe.get("edge_mm", UNKNOWN)
            paper = recipe.get("paper_mm", UNKNOWN) if axis == "z" else None
            tool = resolve(bundle, "spindle", recipe.get("tool")) or {}
            method = recipe.get("method")
            indicated = recipe.get("from") == "indicated"
            radius = (
                "not_applicable"
                if axis == "z" or method == "trial_cut_measure"
                else 0
                if indicated
                else _touch_diameter(tool)[0]
            )
            if not indicated and number(radius):
                radius /= 2
            if axis != "z" and not indicated and method not in MEASURED and tool:
                _, field = _touch_diameter(tool)
                category, tool_ref = identity(bundle, recipe.get("tool"), "spindle")
                if tool.get("kind") != UNKNOWN:
                    debt = length_debt(tool, field, category, tool_ref)
                    if debt:
                        tip_measurements.append(debt)
            # A named after_op that does not resolve places the touch nowhere known,
            # never at the initial boundary.
            done = _boundary(ops, {"after_op": recipe.get("after_op")})
            if axis == "z" and recipe.get("face") == "top":
                # The top as the ops up to and including after_op left it, not the
                # incoming stock top.
                edge = tops[done] if done != UNKNOWN else UNKNOWN
            # Paper stands the tool off its face on the side it meets the face from.
            face = recipe.get("face", recipe.get("feature"))
            stand_off = None
            credited, carried = [], False
            if axis == "z":
                edge, credited, carried = face_check(
                    {**recipe, "from": recipe.get("from", UNKNOWN)},
                    face,
                    edge,
                    done,
                    "the Z zero touch",
                )
                side = touch_side(bundle, setup, recipe, face, edge, lathe)
                stand_off = paper_offset(paper, side)
            # Only an authored radius/diameter display fixes the lathe X jog scale.
            scale = (
                {True: 1, False: 2}.get(dro.get("radius_mode"), UNKNOWN)
                if axis == "x" and lathe
                else 1
            )
            values = axis_recipe(
                edge,
                radius,
                recipe.get("from"),
                axis,
                recipe.get("check_jog_mm", UNKNOWN),
                sign,
                scale,
                stand_off,
            )
            if carried:
                _carried_setting(bundle, setup, values, "axis_set", carried)
            gauge = gauge_ready(bundle, recipe.get("gauge"))
            if method == "trial_cut_measure":
                # The diameter is measured at the machine after the cut, like paper
                # thickness: the recipe is complete once the gauge and jog are known.
                display = measured(scale) if axis == "x" and lathe else UNKNOWN
                jog = recipe.get("check_jog_mm", UNKNOWN)
                increment = (
                    sign * scale * jog
                    if sign in {-1, 1} and number(scale) and number(jog)
                    else UNKNOWN
                )
                known = display != UNKNOWN and number(increment) and gauge
                values = {
                    "axis_set": f"measured {display}" if known else UNKNOWN,
                    "check_reading": f"{display} {increment:+g}" if known else UNKNOWN,
                    "mirrored_reading": f"{display} {-increment:+g}" if known else UNKNOWN,
                    "sign": sign,
                }
            elif method == "measure_then_set":
                # The edge is read at the machine (M), like a trial-cut diameter: Axis
                # Set M + offset + paper, then jog from it.
                base = (
                    measured_z(
                        bundle,
                        recipe.get("gauge"),
                        recipe.get("measure"),
                        recipe.get("offset_mm", UNKNOWN),
                        stand_off,
                    )
                    if axis == "z"
                    else UNKNOWN
                )
                jog = recipe.get("check_jog_mm", UNKNOWN)
                step = sign * jog if sign in {-1, 1} and number(jog) else UNKNOWN
                known = number(base) and number(step)
                values = {
                    "axis_set": measured_edge(base) if known else UNKNOWN,
                    "check_reading": measured_edge(base + step) if known else UNKNOWN,
                    "mirrored_reading": measured_edge(base - step) if known else UNKNOWN,
                    "sign": sign,
                }
            row = dict(recipe)
            row.pop("retouch_after", None)
            row.update(
                values,
                edge_mm=edge,
                radius_mm=radius,
                paper_mm=paper if paper is not None else "not_applicable",
                jog_mm=recipe.get("check_jog_mm", UNKNOWN),
                dro_direction=direction,
                axis_set_status=(
                    "measured"
                    if method in MEASURED and values["axis_set"] != UNKNOWN
                    else "computed"
                    if number(values["axis_set"])
                    else UNKNOWN
                ),
            )
            if credited:
                row["credited_faces"] = credited
            if method in MEASURED:
                row["check_expression"] = values["check_reading"]
                row["mirrored_expression"] = values["mirrored_reading"]
                row["gauge_verify"] = not gauge
            elif axis != "z":
                row["indicator_verify" if indicated else "finder_verify"] = uncertain(
                    tool
                ) or not bool(tool)
                if not indicated and tool.get("kind") == "edge_finder":
                    # The one EDGE FINDER box on the traveler prints these facts.
                    finder = row["finder"] = finder_procedure(bundle, setup, tool)
                    finder_status.add(finder["status"])
            axes[axis] = row
            if axis == "z":
                blade_corner(row, recipe, face, edge, "the Z zero touch")
            unknown |= (
                any(values[k] == UNKNOWN for k in ("axis_set", "check_reading", "mirrored_reading"))
                or not tool
                or uncertain(tool)
            )
        retouch = []
        recipe = mapping(zero.get("z"))
        paper = recipe.get("paper_mm", UNKNOWN)
        unknown |= (
            recipe.get("retouch_after", UNKNOWN) == UNKNOWN or zero.get("tool_touches") == UNKNOWN
        )
        for index, (op, _, after) in enumerate(states):
            if op.get("op") in records(recipe.get("retouch_after")):
                who = f"the retouch after op {op['op']}"
                top, credited, carried = face_check(
                    _retouch_recipe(recipe),
                    "top",
                    tops[index + 1],
                    index + 1,
                    who,
                    after["top_from"],
                )
                touch = top + paper if number(top) and number(paper) else UNKNOWN
                row = {"op": op["op"], "top_z": top, "paper_mm": paper, "axis_set": touch}
                if carried:
                    _carried_setting(bundle, setup, row, "axis_set", carried)
                if credited:
                    row["credited_faces"] = credited
                retouch.append(row)
                unknown |= row["axis_set"] == UNKNOWN
        touches = []
        x_scale = {True: 1, False: 2}.get(dro.get("radius_mode"), UNKNOWN) if lathe else UNKNOWN
        # Authored X touches on a diameter that is gone (errors) or not shown standing.
        x_errors, x_unknowns = [], []
        for record in records(zero.get("tool_touches")):
            edge, paper = record.get("edge_mm", UNKNOWN), record.get("paper_mm", UNKNOWN)
            who = f"the {record.get('tool', UNKNOWN)} touch"
            edge, credited, carried = face_check(
                record, record.get("z_face"), edge, _boundary(ops, record), who
            )
            side = touch_side(bundle, setup, record, record.get("z_face"), edge, lathe)
            stand_off = paper_offset(paper, side)
            tool = resolve(bundle, "spindle", record.get("tool")) or {}
            # A mill's X/Y read the spindle axis whatever the tool: its touches set Z only.
            x_set = (
                "not_applicable"
                if not lathe
                else x_touch_set(
                    x_scale,
                    record.get("x_paper_mm", UNKNOWN),
                    record.get("x_method") == "trial_cut_measure",
                )
                if gauge_ready(bundle, record.get("gauge"))
                else UNKNOWN
            )
            if record.get("method") == "measure_then_set":
                z_set = measured_edge(
                    measured_z(
                        bundle,
                        record.get("z_gauge"),
                        record.get("z_measure"),
                        record.get("z_offset_mm", UNKNOWN),
                        stand_off,
                    )
                )
            else:
                z_set = edge + stand_off if number(edge) and number(stand_off) else UNKNOWN
            row = {**record, "edge_mm": edge, "x_axis_set": x_set, "z_axis_set": z_set}
            if carried:
                _carried_setting(bundle, setup, row, "z_axis_set", carried)
            if credited:
                row["credited_faces"] = credited
            if lathe:
                at = _position(ops, record) or 0
                state, reason = x_face_state(
                    bundle, setup, record, mapping(zero.get("x")), states, at
                )
                row["x_face_status"] = state
                if state != "pass":
                    (x_errors if state == "error" else x_unknowns).append(f"{who} {reason}")
            blade_corner(row, record, record.get("z_face"), edge, who)
            touches.append(row)
            unknown |= (
                x_set == UNKNOWN or row["z_axis_set"] == UNKNOWN or not tool or uncertain(tool)
            )
        unknown |= bool(x_unknowns)
        derived, missing, changes_unknown, _, served = tool_changes(
            bundle, setup, zero, lathe, x_scale, touches
        )
        unknown |= changes_unknown
        # A listed retouch names the op that reads it and the tool that goes in first;
        # one no later cutting op reads serves no tool.
        idle = {"next_op": "not_applicable", "next_tool": "not_applicable", "tool_change": False}
        for row in retouch:
            row.update(served.get(str(row["op"]), idle))
        for row in derived:
            who = f"the {row.get('tool', UNKNOWN)} re-touch"
            done = _boundary(ops, row)
            previous = row.get("edge_mm")
            offset = (
                row["z_axis_set"] - previous
                if number(previous) and number(row.get("z_axis_set"))
                else UNKNOWN
            )
            edge, credited, carried = face_check(row, row.get("z_face"), previous, done, who)
            if carried and "native_edge_mm" in carried:
                offset = paper_offset(
                    row.get("paper_mm", UNKNOWN),
                    touch_side(bundle, setup, row, row.get("z_face"), edge, lathe),
                )
            if row.get("z_face"):
                row["edge_mm"] = edge
                row["z_axis_set"] = edge + offset if number(edge) and number(offset) else UNKNOWN
                if carried:
                    _carried_setting(bundle, setup, row, "z_axis_set", carried)
                unknown |= row["z_axis_set"] == UNKNOWN
            if credited:
                row["credited_faces"] = credited
            blade_corner(row, row, row.get("z_face"), row.get("edge_mm"), who)
        unknown |= bool(face_unknowns)
        numbers = {
            "frame": setup.get("frame", UNKNOWN),
            "binding": frame.get("binding", "nominal"),
            "dro": {
                "mode": dro.get("mode", UNKNOWN),
                "radius_mode": dro.get("radius_mode", UNKNOWN),
            },
            "axes": axes,
            "retouch": retouch,
            "tool_touches": touches,
            "derived_touches": derived,
            "missing_touches": missing,
        }
        touched = [axis for axis in ("x", "y") if swept and not isinstance(zero.get(axis), dict)]
        if touched:
            numbers["touch_set"] = {
                "axes": touched,
                "ops": swept,
                "by": "trammel" if railed else "touch",
            }
        grid_debt = dro_grid_debt(bundle, setup) if face_unknowns else None
        if grid_debt:
            numbers["dro_grid_debt"] = grid_debt
            numbers["measurements"] = dro_grid_measurements(bundle, setup)
        if tip_measurements:
            numbers["measurements"] = measurement_checklist(
                [], debts=[*numbers.get("measurements", []), *tip_measurements]
            )
        if lathe:
            numbers["tool_setting"] = tool_setting(bundle, setup, zero, touches, derived)
        if "transfer" in zero:
            numbers["transfer"] = zero["transfer"]
        # A hold that must stay clamped cannot be tapped true: a sweep over its limit needs
        # the plan's recovery, else what to do then is unknown.
        transfer = mapping(zero.get("transfer"))
        recovery = transfer.get("recovery")
        unrecovered = transfer.get("keep_clamped") is True and not (
            isinstance(recovery, str) and recovery.strip() and recovery != UNKNOWN
        )
        unknown |= unrecovered or UNKNOWN in finder_status
        finder_error = "error" in finder_status
        errors = (
            bad
            or missing
            or corner_errors
            or face_errors
            or x_errors
            or finder_error
            or railed_errors
        )
        status = "error" if errors else "unknown" if unknown else "pass"
        sentence = (
            "DRO direction or mode disagrees with the setup convention; stop and correct it "
            "before the check jog."
            if bad
            else (
                "Touch, Axis Set the compensated value, then jog without retouching "
                "and compare expected versus mirrored readings."
                + (
                    " Each tool change is touched off on the last touched or faced surface "
                    "still standing."
                    if derived
                    else ""
                )
                + (
                    " A tool cuts on a DRO another tool set and no standing plan surface "
                    "is known to touch it off on: plan a tool touch before "
                    + ", ".join(f"op {row['before_op']}" for row in missing)
                    + "."
                    if missing
                    else ""
                )
                + (
                    " Measured setup/tool or trial-cut verification remains unknown."
                    if unknown
                    else ""
                )
            )
        )
        if finder_error:
            sentence += (
                " The edge finder's rpm range lies outside the spindle's: the mill cannot "
                "run it at a speed its maker allows. Use a finder whose band the spindle turns."
            )
        elif UNKNOWN in finder_status:
            sentence += (
                " The edge finder's type, tip Ø, rpm range or the spindle's rpm range is not "
                "stated: its procedure (speed, kick-out, tip-radius offset) cannot be printed."
            )
        if unrecovered:
            sentence += (
                " The datum transfer keeps the work clamped but plans no recovery for a sweep "
                "over its limit: state transfer.recovery."
            )
        if corner_errors:
            sentence += (
                " A blade's Z touch names a corner its face cannot give ("
                + "; ".join(corner_errors)
                + "): plan its Zs from the corner the face gives."
            )
        if face_errors:
            sentence += (
                " A Z touch sets its DRO off where its face stands ("
                + "; ".join(face_errors)
                + "): every Z the tool then cuts to lands off by the difference. Plan the "
                "face onto this DRO's grid, or set Z from a measured reading of it."
            )
        if face_unknowns:
            sentence += (
                (
                    " A Z touch cannot be certified on an unverified DRO grid ("
                    if grid_debt
                    else " A Z touch meets a face its op left at an unknown Z ("
                )
                + "; ".join(face_unknowns)
                + "): its Axis Set is not known."
            )
        if railed_errors:
            sentence += " " + "; ".join(railed_errors) + "."
        if x_errors:
            sentence += (
                " An X touch measures a diameter that does not stand where it touches ("
                + "; ".join(x_errors)
                + "): touch X on a diameter standing then (D2), or trial-cut one."
            )
        if x_unknowns:
            sentence += (
                " An X touch's diameter is not shown standing where it touches ("
                + "; ".join(x_unknowns)
                + "): name it in x_face, on a diameter the rule can follow."
            )
        result.append(
            Finding(
                "zero_check",
                setup["id"],
                status,
                numbers,
                [
                    "PLAN.md §4.1 zero recipe",
                    "Electronica EL400 Operation Manual §6.2 p20, §7.4 p31, §8.1 p37, §9.2.1 p62",
                    "plan zero and stock_state; inventory finder nominal size",
                    *plan_frame_cite(bundle, setup),
                    *(TOOL_SETTING_CITES if lathe else []),
                    *(records(toolpost(bundle, setup).get("cite")) if lathe else []),
                ],
                sentence,
            )
        )
    return result
