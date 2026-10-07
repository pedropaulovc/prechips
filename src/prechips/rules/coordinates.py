"""Nominal feature targets and finite cutter-centre tables.

A model point is transformed by the dot product with each setup basis. Unknown
components propagate only through nonzero basis coefficients. Local authored Z
can substitute only an unknown model transform in an unbound frame, retaining
local_from operation provenance. No tolerance-band midpoint defines geometry: a plan
``aims`` entry moves only a located feature's DRO target along its height-like band to a
stated value, and the geometry stays nominal; one naming a ``face`` instead moves that
faced plane of the part the kernel cuts (:func:`faced_aims`), never the STEP.
A basis axis is known only when orthonormal with its frame's other numeric axes
(:func:`frame_axes`): loading checks only a complete frame.

A located feature is placed by its own ``at``, else by its parent hole's ``at``
(:func:`located_by`), else by the kernel's measured faces of revolution about setup Z
through X0 Y0 (:func:`revolved_located`); otherwise its row stays unknown. A mill row
prints on the DRO grid (``dro``), and a row whose feature holds a height-like band from a
``height_from`` reference must stand inside that band as printed (:func:`band_reference`).
"""

from __future__ import annotations

import functools
import itertools
import math

from ..findings import Finding
from ..measurements import angle_fact, length_fact
from ..model import tolerance_requirements
from ._bench import manual_bench, not_applicable
from .datum_consistency import _cuts
from .resolution import (
    HAND_FINISH,
    UNKNOWN,
    _citations,
    length_mm,
    number,
    op_features,
    plan_frame_cite,
    resolve,
    rough_leave,
    setup_frame,
    uncertain,
)
from .tip_endpoints import (
    FACING,
    HOLE_OPS,
    POCKETING,
    _covers_xy,
    forms_face,
    operative_z,
    stock_states,
)

AXES = ("x", "y", "z")
CENTRE_OPS = HOLE_OPS | {"center"}
LOCATED_KINDS = {"hole", "counterbore", "thread", "threaded_hole", "boss"}
# Side-milling traverse sense. With n the cutter-side surface normal (from the cut wall
# toward the cutter centre) and t the travel, a clockwise spindle (viewed from above,
# looking down setup -Z) cuts conventionally when (n x t)·Z > 0 and climbs when it is < 0;
# a counterclockwise spindle inverts both.
_CUT_SENSE = {"conventional": 1, "climb": -1}
_SPINDLE_SENSE = {"cw": 1, "ccw": -1}


def mapping(value):
    return value if isinstance(value, dict) else {}


def located_by(features, name, feature):
    """The feature whose ``at`` locates ``name``, that feature's frame name and its name.

    An explicit ``at`` (even ``unknown``) wins; otherwise a child names its
    parent hole (``hole``/``parent``) and is located at that parent's ``at`` in the
    parent's frame. A missing parent locates nothing, so the child stays unknown.
    """
    parent = feature.get("hole", feature.get("parent"))
    if "at" in feature or not isinstance(parent, str):
        return feature, feature.get("frame", "model"), name
    owner = mapping(features.get(parent))
    return owner, owner.get("frame", "model"), parent


def _op_names(setup):
    """Every feature the setup's ops name, in op order; an absent feature stays ``None``."""
    return dict.fromkeys(name for op in setup["ops"] for name in op_features(op) or [None])


def _centred(setup):
    """The features this setup's centre ops (hole ops and ``center``) dial to their DRO
    target."""
    return {op.get("feature") for op in setup["ops"] if op.get("do") in CENTRE_OPS}


def _located_names(setup, features):
    """This setup's located features (a located kind or a centre-op target), in op order."""
    centre = _centred(setup)
    return [
        name
        for name in _op_names(setup)
        if mapping(features.get(name)).get("kind") in LOCATED_KINDS or name in centre
    ]


def revolved_located(setup, features):
    """Located features of ``setup`` with neither ``at`` nor a parent locator.

    Only the kernel's faces of revolution about setup Z through X0 Y0 can locate them; the
    kernel request asks it to measure them in every setup (turning setups measure every
    feature anyway).
    """
    return [
        name
        for name in _located_names(setup, features)
        if isinstance(name, str)
        and "at" not in mapping(features.get(name))
        and located_by(features, name, mapping(features.get(name)))[2] == name
    ]


def _sum(terms):
    return sum(terms) if all(number(v) for v in terms) else UNKNOWN


def model_point(point, frame):
    frame = mapping(frame)
    if not isinstance(point, list) or len(point) != 3:
        return [UNKNOWN] * 3
    origin = mapping_vector(frame.get("origin"))
    axes = frame_axes(frame)
    return [
        _sum(
            [origin[i]]
            + [
                point[j] * basis[i] if number(point[j]) and number(basis[i]) else UNKNOWN
                for j, basis in enumerate(axes)
                if basis[i] != 0
            ]
        )
        for i in range(3)
    ]


def mapping_vector(value):
    return value if isinstance(value, list) and len(value) == 3 else [UNKNOWN] * 3


def frame_axes(frame):
    """``frame``'s X, Y and Z vectors; each is ``[UNKNOWN] * 3`` unless finite and, to
    loading's 1e-9, orthonormal with the frame's other numeric axes. Loading checks a
    complete frame only: one with an unknown axis may carry scaled or skewed vectors, along
    which no coordinate, and against which no direction, is known."""
    vectors = [mapping_vector(mapping(frame).get(axis)) for axis in AXES]
    known = [i for i, v in enumerate(vectors) if all(number(t) and math.isfinite(t) for t in v)]
    bad = {
        k
        for i, j in itertools.combinations_with_replacement(known, 2)
        if abs(sum(a * b for a, b in zip(vectors[i], vectors[j], strict=True)) - (i == j)) > 1e-9
        for k in (i, j)
    }
    return [vectors[i] if i in known and i not in bad else [UNKNOWN] * 3 for i in range(3)]


def frame_point(point, frame):
    frame = mapping(frame)
    if not isinstance(point, list) or len(point) != 3:
        return [UNKNOWN] * 3
    origin = mapping_vector(frame.get("origin"))
    result = []
    for basis in frame_axes(frame):
        terms = [
            (point[i] - origin[i]) * basis[i]
            if all(number(v) for v in (point[i], origin[i], basis[i]))
            else UNKNOWN
            for i in range(3)
            if basis[i] != 0
        ]
        result.append(_sum(terms))
    return result


# The height-like drawing band a located feature holds from its ``height_from`` feature or
# plane: the first one it declares (datum_consistency reads the same one).
HEIGHT_BANDS = ("height_above_pivot", "height", "separation")
# Millimetres per manifest unit; any other ``units`` leaves a length conversion unknown.
UNIT_MM = {"mm": 1.0, "in": 25.4}


def printed_band(manifest, feature, requirement):
    """``feature``'s ``requirement`` band as the sheet prints it: rounded inward at its
    drawing precision (low limit up, high limit down), as declared when no precision applies
    or the band is too narrow for it; unknown unless both limits are numbers. ``manifest``
    is the feature manifest (its general ``precision``)."""
    band = feature.get(requirement)
    if not (isinstance(band, list) and len(band) == 2 and all(number(v) for v in band)):
        return UNKNOWN
    overrides = feature.get("precision", {})
    general = manifest.get("precision")
    places = overrides.get(requirement, general) if isinstance(overrides, dict) else overrides
    if not isinstance(places, int) or isinstance(places, bool):
        return list(band)
    scale = 10**places
    low = math.ceil(round(band[0] * scale, 6)) / scale
    high = math.floor(round(band[1] * scale, 6)) / scale
    return [low, high] if low <= high else list(band)


def aim_band_error(manifest, name, feature, aim):
    """Why plan ``aims.<name>`` asks its requirement for a value outside the band the sheet
    prints (:func:`printed_band`): ``value_mm`` itself, in manifest units, before any DRO
    rounding. None when it lies inside, or when the units or the band are unknown (the
    coordinates rule leaves those unknown)."""
    units = manifest.get("units")
    requirement = aim["requirement"]
    band = printed_band(manifest, feature, requirement)
    if units not in UNIT_MM or band == UNKNOWN:
        return None
    value = aim["value_mm"] / UNIT_MM[units]
    if band[0] - _JOIN_TOL <= value <= band[1] + _JOIN_TOL:
        return None
    asked = f"{aim['value_mm']:g} mm" + ("" if units == "mm" else f" ({value:g} {units})")
    return (
        f"aims.{name} sets its {requirement} to {asked}, outside its printed band "
        f"{band[0]:g}-{band[1]:g} {units}"
    )


def faced_aim_error(plan, manifest, name, aim):
    """Why plan ``aims.<name>`` naming a ``face`` names no faced length (bad input), else
    None: the face must be one of the exported feature's own ``faces``, the feature must
    declare the ``lower_z`` and ``upper_z`` planes its length runs between, and a facing op
    (:data:`FACING`) on the feature must claim the face (it names no ``faces``, or names
    that one): an aim moves only a plane the plan cuts."""
    face = aim.get("face")
    if face is None:
        return None
    feature = mapping(mapping(manifest.get("features")).get(name))
    faces = feature.get("faces")
    if not isinstance(faces, list) or face not in faces:
        return f"aims.{name}.face {face} is not one of features.{name}.faces"
    missing = [key for key in ("lower_z", "upper_z") if key not in feature]
    if missing:
        return (
            f"aims.{name}.face moves a plane of the length between features.{name}.lower_z "
            f"and upper_z; the feature declares no {' or '.join(missing)}"
        )
    if not faced_aim_claims(plan, name, face):
        return f"no facing op claims aims.{name}.face {face}, so the aim moves no cut"
    return None


def faced_aim_claims(plan, name, face):
    """The facing ops (:data:`FACING`) on feature ``name`` that claim ``face`` (they name no
    ``faces``, or name that one), in plan order."""
    return [
        op
        for setup in plan.get("setups", [])
        for op in setup.get("ops", [])
        if op.get("do") in FACING
        and name in op_features(op)
        and (not isinstance(op.get("faces"), list) or face in op["faces"])
    ]


def faced_aims(bundle):
    """The kernel's faced-aim inputs: for each plan aim naming a ``face``
    (:func:`faced_aim_error` holds at load), that face, the model unit ``axis`` of its
    feature's frame Z, the feature's ``lower_z``/``upper_z`` planes as mm offsets along it,
    the aimed ``value_mm``, the requirement's printed band in mm (``band_mm``,
    :func:`printed_band`) and ``delta_mm``: the aimed ``value_mm`` less their separation,
    the distance the face moves outward so the faced length reads the aim. The kernel cuts
    that part, so every setup's stock, frame heights and checks stand on one face position,
    and measures every aimed length on it. A record carries a ``reason`` instead when units,
    the printed band, the planes or the frame are unknown, or the requirement's declared
    nominal is not the planes' separation (the length they bound is not the one the band
    holds): no known band authorizes a move."""
    manifest = bundle.features
    scale = UNIT_MM.get(manifest.get("units"))
    frames = mapping(manifest.get("frames"))
    result = []
    for name, aim in mapping(bundle.plan.get("aims")).items():
        if aim.get("face") is None:
            continue
        requirement = aim["requirement"]
        record = {"feature": name, "face": aim["face"], "requirement": requirement}
        feature = mapping(mapping(manifest.get("features")).get(name))
        lower, upper = feature.get("lower_z"), feature.get("upper_z")
        frame = mapping(frames.get(feature.get("frame", "model")))
        axis = frame_axes(frame)[2]
        origin = mapping_vector(frame.get("origin"))
        nominal = feature.get(f"{requirement}_nominal", UNKNOWN)
        band = printed_band(manifest, feature, requirement)
        if scale is None:
            record["reason"] = "feature units are not mm or in, so the aim moves no face"
        elif band == UNKNOWN:
            record["reason"] = (
                f"features.{name}.{requirement} has no known printed band, so the aim moves no face"
            )
        elif not (number(lower) and number(upper) and lower < upper):
            record["reason"] = f"features.{name}.lower_z/upper_z are not two ordered planes"
        elif not all(number(v) for v in (*axis, *origin)):
            record["reason"] = f"features.{name}'s frame is not fully declared"
        elif f"{requirement}_nominal" in feature and not (
            number(nominal) and abs(nominal - (upper - lower)) <= _JOIN_TOL
        ):
            record["reason"] = (
                f"features.{name}.{requirement}_nominal is not the lower_z-upper_z "
                "separation, so moving one of those planes does not set it"
            )
        else:
            base = _dot(origin, axis)
            record.update(
                axis=axis,
                lower_mm=round((base + lower) * scale, 9),
                upper_mm=round((base + upper) * scale, 9),
                value_mm=aim["value_mm"],
                band_mm=[round(limit * scale, 9) for limit in band],
                delta_mm=round(aim["value_mm"] - (upper - lower) * scale, 9),
            )
        result.append(record)
    return result


def _dot(a, b):
    return sum(x * y for x, y in zip(a, b, strict=True))


def _unit(vector):
    """``vector`` scaled to length 1; None unless it is three numbers of nonzero length."""
    if not (isinstance(vector, list) and len(vector) == 3 and all(number(v) for v in vector)):
        return None
    length = math.sqrt(_dot(vector, vector))
    return [v / length for v in vector] if length > 1e-6 else None


def _model_axis(features, name, frames, seen=()):
    """``(vector, why)``: ``name``'s measuring axis as a model unit vector: its own declared
    ``axis`` in its own frame. Without one, a feature on another's axis takes that
    feature's, in that feature's frame (its own, or in turn the one it takes), with or
    without an ``at`` of its own: a child's parent hole (``hole``, else ``parent``), else
    the feature it is drawn ``coaxial_to``. (None, None) when no axis is declared along
    that line, so the dimension is point to point; (None, why) when the applicable axis,
    its frame or the feature it comes from is not known, so no measuring direction follows.
    """
    feature = mapping(features.get(name))
    if "axis" not in feature:
        owner = feature.get("hole", feature.get("parent", feature.get("coaxial_to")))
        if not isinstance(owner, str):
            return None, None
        if owner in (*seen, name):
            return None, f"{name} takes its axis from {owner}, which takes it back"
        if owner not in features:
            return None, f"{name} takes its axis from {owner}, which is not declared"
        return _model_axis(features, owner, frames, (*seen, name))
    axis = feature["axis"]
    frame = mapping(frames.get(feature.get("frame", "model")))
    basis = [mapping_vector(frame.get(axis_name)) for axis_name in AXES]
    if not (isinstance(axis, list) and len(axis) == 3 and all(number(v) for v in axis)):
        return None, f"{name}'s axis is unknown"
    if not all(number(v) for vector in basis for v in vector):
        return None, f"{name}'s axis frame is not fully declared"
    vector = _unit([sum(axis[j] * basis[j][i] for j in range(3)) for i in range(3)])
    return (vector, None) if vector else (None, f"{name}'s axis has no direction")


def band_reference(bundle, name, point, seen=(), targets=None):
    """Where model ``point`` stands on ``name``'s height-like band (:data:`HEIGHT_BANDS`)
    from its ``height_from`` reference; None when the feature declares no such band.

    A plane reference (``plane``: frame, axis, value) measures along the plane normal. A
    located reference measures from its model point in ``targets`` (its printed DRO target
    when the setup checking ``point`` machines it there), else its planned point
    (:func:`planned_point`), along the common normal of both measuring axes
    (:func:`_model_axis`: declared, else the axis it stands on), else square to the one axis,
    else point to point when neither has one; an axis that is not known leaves the
    distance unmeasured. The result names the requirement, the reference, the printed band
    (:func:`printed_band`), the unit ``direction`` from the reference toward ``point`` and
    the distance ``value`` in manifest units, or a ``why`` when it cannot be measured.
    """
    features = bundle.feature_definitions
    feature = mapping(features.get(name))
    source = feature.get("height_from")
    requirement = next((key for key in HEIGHT_BANDS if key in feature), None)
    if not isinstance(source, str) or requirement is None:
        return None
    result = {
        "requirement": requirement,
        "from": source,
        "printed_band": printed_band(bundle.features, feature, requirement),
    }
    frames = mapping(bundle.features.get("frames"))
    reference = mapping(features.get(source))
    plane = mapping(reference.get("plane"))
    if not all(number(v) for v in point):
        return {**result, "why": f"{name} has no known planned point"}
    if plane:
        frame = mapping(frames.get(plane.get("frame", "model")))
        axis, value = plane.get("axis"), plane.get("value")
        normal = _unit(mapping_vector(frame.get(axis))) if axis in AXES else None
        base = model_point([value if a == axis else 0.0 for a in AXES], frame)
        if normal is None or not all(number(v) for v in base):
            return {**result, "why": f"the {source} plane is not fully declared"}
    else:
        if targets is not None and source in targets:
            base, why = targets[source], None
        else:
            base, _, why = planned_point(bundle, source, (*seen, name))
        if why is not None:
            return {**result, "why": why}
        delta = [p - q for p, q in zip(point, base, strict=True)]
        first, why = _model_axis(features, name, frames)
        second, other = _model_axis(features, source, frames)
        if why or other:
            return {**result, "why": why or other}
        normal = None
        if first and second:
            normal = _unit(
                [
                    first[(i + 1) % 3] * second[(i + 2) % 3]
                    - first[(i + 2) % 3] * second[(i + 1) % 3]
                    for i in range(3)
                ]
            )
        shared = first or second
        if normal is None and shared:
            along = _dot(delta, shared)
            normal = _unit([d - along * s for d, s in zip(delta, shared, strict=True)])
        if normal is None and not shared:
            normal = _unit(delta)
        if normal is None:
            return {**result, "why": f"{name} stands on the {source} axis"}
    signed = _dot([p - q for p, q in zip(point, base, strict=True)], normal)
    direction = normal if signed >= 0 else [-v for v in normal]
    return {**result, "direction": direction, "value": abs(signed)}


def _measure(bundle, name, points, seen=(), targets=None):
    """:func:`band_reference` for every model point locating ``name`` (a kernel span's
    two ends, else one point): they must stand at one distance in one direction, else the
    band names no one of them and the result carries that ``why``."""
    checks = [band_reference(bundle, name, point, seen, targets) for point in points]
    if not checks or checks[0] is None:
        return None
    first = checks[0]
    unmeasured = next((check for check in checks if "why" in check), None)
    if unmeasured is not None:
        return unmeasured
    for check in checks[1:]:
        if abs(check["value"] - first["value"]) > _JOIN_TOL or (
            math.dist(check["direction"], first["direction"]) > 1e-9
        ):
            return {
                **{key: first[key] for key in ("requirement", "from", "printed_band")},
                "why": f"{name}'s located points stand at different distances from "
                f"{first['from']}, so its band names no one of them",
            }
    return first


def _plan_aim(bundle, name):
    """``name``'s own plan ``aims`` record (owner, requirement, value, reason), else None;
    a faced aim (one naming a ``face``, :func:`faced_aims`) moves the part, no DRO target."""
    aim = mapping(mapping(bundle.plan.get("aims")).get(name))
    if not aim or aim.get("face") is not None:
        return None
    return {
        "feature": name,
        "requirement": aim["requirement"],
        "value_mm": aim["value_mm"],
        "reason": aim["reason"],
    }


def _dialled(bundle, name):
    """Whether a mill setup's centre op (:func:`_centred`) names ``name`` itself, so the
    plan cuts it at its DRO target; inspecting it, cutting a child of it or drilling it on
    a lathe's spindle axis does not."""
    for setup in bundle.plan["setups"]:
        machine = resolve(bundle, "machines", setup.get("machine")) or {}
        if machine.get("kind") == "lathe" or manual_bench(bundle, setup) is not None:
            continue
        if name in _centred(setup):
            return True
    return False


def _aimed(bundle, name, points, seen=()):
    """``(points, aim, why)``: the model ``points`` locating ``name`` moved by its own plan
    ``aims.<name>`` along its height-like band (:func:`_measure`) so that band reads
    ``value_mm``, converted to manifest units: a process choice on the DRO target, never a
    change to the geometry. ``aim`` is None without one. An aim that cannot be applied
    leaves the points where they are and says ``why``: a value outside the printed band
    (:func:`aim_band_error`) also carries it as ``error``; a feature no mill setup cuts at
    its target (:func:`_dialled`), unknown units, a band the feature does not hold, an
    unknown band or an unmeasurable distance leave it unknown.
    """
    aim = _plan_aim(bundle, name)
    if aim is None:
        return points, None, None

    def refuse(why):
        aim["why"] = why
        return points, aim, why

    requirement = aim["requirement"]
    if name in seen:
        return refuse(f"the aims of {', '.join((*seen, name))} depend on each other")
    error = aim_band_error(bundle.features, name, bundle.feature_definitions.get(name, {}), aim)
    if error is not None:
        aim["error"] = error
        return refuse(error)
    if not _dialled(bundle, name):
        return refuse(f"no mill setup centres {name}, so aims.{name} moves no cut")
    scale = UNIT_MM.get(bundle.features.get("units"))
    if scale is None:
        return refuse(f"feature units are not mm or in, so aims.{name}.value_mm places nothing")
    reference = _measure(bundle, name, points, seen)
    if reference is None or reference["requirement"] != requirement:
        return refuse(f"{name} holds no {requirement} band from height_from")
    aim.update(source=reference["from"], printed_band=reference["printed_band"])
    if reference["printed_band"] == UNKNOWN:
        return refuse(f"{name}'s printed {requirement} band is unknown")
    if "why" in reference:
        return refuse(reference["why"])
    value = aim["value_mm"] / scale
    shift = value - reference["value"]
    aim.update(
        value=value,
        nominal_mm=round(reference["value"] * scale, 6),
        shift_mm=round(shift * scale, 6),
    )
    moved = [
        [p + shift * d for p, d in zip(point, reference["direction"], strict=True)]
        for point in points
    ]
    return moved, aim, None


def planned_point(bundle, name, seen=()):
    """``(point, aims, why)``: ``name``'s planned model point, the plan aims that bear on it
    (row fields, below; empty without any) and why the point is unknown or one of those
    aims unusable (or None).

    The point is where its locator places it (:func:`located_by`), moved by that locator's
    own aim (:func:`_aimed`), which ``aims`` holds as ``aim``. A child located by its
    parent's ``at`` therefore stands on its parent's target, aimed or not, and carries the
    parent's aim. An aim of the child's own would take it off that axis: ``aims`` holds it
    as ``refused_aim`` with that reason and it moves nothing, so the child still stands on
    its parent's target.
    """
    features = bundle.feature_definitions
    frames = mapping(bundle.features.get("frames"))
    locator, locator_frame, locator_name = located_by(features, name, mapping(features.get(name)))
    point = model_point(locator.get("at"), frames.get(locator_frame))
    (point,), aim, why = _aimed(bundle, locator_name, [point], seen)
    aims = {} if aim is None else {"aim": aim}
    own = _plan_aim(bundle, name) if locator_name != name else None
    if own is not None:
        own["why"] = (
            f"{name} is located on its parent {locator_name}'s at, so an aim of its own "
            f"would take it off that axis; aim {locator_name} instead"
        )
        aims["refused_aim"] = own
        why = why or own["why"]
    if why is None and not all(number(v) for v in point):
        why = f"{name} has no known point"
    return point, aims, why


def dro_point(point, grid):
    """A located target as the DRO prints it on ``grid`` (:func:`dro_grid`): each axis at
    its nearest grid step, so it moves at most half a step; unknown unless all known."""
    if not all(number(v) for v in point):
        return [UNKNOWN] * 3
    step, decimals = grid
    return [round(round(v / step) * step, decimals) + 0.0 for v in point]


def _planned_rows(rows, planned, aims, frame, grid):
    """Stamp one feature's mill located ``rows`` with the plan ``aims`` that bear on them
    (:func:`planned_point`: ``aim``, the locator's, and a child's ``refused_aim``; or
    :func:`_aimed`), stand them at model ``planned`` when that ``aim`` moved them there, and
    stamp the DRO target the feature map prints and its hole ops dial (``dro``,
    ``dro_xy``); returns ``(errors, unknown)``: an aim outside its printed band is an
    error, any other unusable aim unknown."""
    errors, unknown = [], False
    for record in aims.values():
        if "error" in record:
            errors.append(record["error"])
        elif "why" in record:
            unknown = True
    placed = "aim" in aims and "why" not in aims["aim"]
    for row, point in zip(rows, planned, strict=True):
        row.update({key: dict(record) for key, record in aims.items()})
        if placed:
            row["nominal_setup"] = row["setup"]
            row["setup"] = frame_point(point, frame)
    for row in rows:
        if all(number(v) for v in row["setup"]):
            row["dro"] = dro_point(row["setup"], grid)
            row["dro_xy"] = row["dro"][:2]
    return errors, unknown


def _band_rows(bundle, name, rows, frame, targets, debt, machined):
    """Stamp one feature's DRO-targeted ``rows`` with the check of its height-like band
    where the feature stands: at those DRO targets when this setup machines it there
    (``machined``), else at their planned points (the targets only display it), measured
    from the reference's DRO target when ``targets`` holds it (:func:`band_reference`);
    returns ``(errors, unknown)``. A provisional DRO grid (``debt``,
    :func:`dro_grid_debt`) or unknown units never establish a pass."""
    if not rows or not all(number(v) for row in rows for v in row.get("dro", [UNKNOWN])):
        return [], False
    points = [model_point(row["dro" if machined else "setup"], frame) for row in rows]
    check = _measure(bundle, name, points, targets=targets)
    if check is None:
        return [], False
    band = check["printed_band"]
    record = {key: check[key] for key in ("requirement", "from", "printed_band")}
    scale = UNIT_MM.get(bundle.features.get("units"))
    why = check.get("why") or (None if scale else "feature units are not mm or in") or debt
    if why is not None or band == UNKNOWN:
        record.update({"why": why} if why else {}, status=UNKNOWN)
        for row in rows:
            row["band_check"] = dict(record)
        return [], True
    value = check["value"]
    inside = band[0] - _JOIN_TOL <= value <= band[1] + _JOIN_TOL
    record.update(value_mm=round(value * scale, 6), status="pass" if inside else "error")
    for row in rows:
        row["band_check"] = dict(record)
    if inside:
        return [], False
    return [
        f"{name} at its {'DRO target' if machined else 'planned point'} stands {value:.3f} "
        f"from {check['from']}, outside its printed {check['requirement']} band "
        f"{band[0]:g}-{band[1]:g}"
    ], False


def _nominal(feature, key):
    explicit = feature.get(key + "_nominal", UNKNOWN)
    if number(explicit):
        return explicit
    return feature.get(key, UNKNOWN) if number(feature.get(key)) else UNKNOWN


def _samples(start, end, step):
    """Both exact endpoints plus grid checkpoints; no extrapolated full circle."""
    if not all(number(v) for v in (start, end, step)) or step <= 0:
        return []
    reverse = end < start
    low, high = sorted((start, end))
    values = (
        [low]
        + [i * step for i in range(math.floor(low / step) + 1, math.ceil(high / step))]
        + ([high] if high != low else [])
    )
    return list(reversed(values)) if reverse else values


def _cross(a, b):
    return a[0] * b[1] - a[1] * b[0]


def cut_order(machine, op):
    """(required sign of (n x t)·Z or None, order record) from op direction and spindle.

    Only an authored ``conventional``/``climb`` op on a machine whose spindle ``rotation``
    is declared (bare, or a ``{value, measured}`` fact not flagged ``verify``) has a
    cutting order; anything else keeps the order unknown.
    """
    direction = op.get("direction", UNKNOWN)
    rotation = mapping(mapping(machine).get("spindle")).get("rotation", UNKNOWN)
    flagged = isinstance(rotation, dict) and rotation.get("verify") is True
    if isinstance(rotation, dict):
        rotation = rotation.get("value", UNKNOWN)
    if direction not in _CUT_SENSE:
        reason = f"op direction {direction!r} is neither conventional nor climb"
    elif flagged:
        reason = "the machine spindle rotation is flagged verify"
    elif rotation not in _SPINDLE_SENSE:
        reason = "the machine spindle rotation is not declared"
    else:
        sense = _CUT_SENSE[direction] * _SPINDLE_SENSE[rotation]
        return sense, {"cut_order": direction, "spindle_rotation": rotation}
    return None, {"cut_order": UNKNOWN, "cut_order_reason": reason}


def _reversal(a, b, normal, sense):
    """Whether travel a->b (setup XY) must reverse to cut with ``sense``, or None.

    ``normal`` is the cutter-side wall normal there; an unknown sense, unknown values or a
    travel parallel to the normal cannot establish an order.
    """
    values = (*a, *b, *normal)
    if sense is None or not all(number(v) for v in values):
        return None
    turn = _cross(normal, [b[0] - a[0], b[1] - a[1]])
    if abs(turn) < 1e-12:
        return None
    return (turn > 0) != (sense > 0)


def _side(a, b, normal, reverse):
    """``left`` or ``right``: the side of the travel the cutter-side wall ``normal`` points
    to, for travel a->b (setup XY), reversed when ``reverse``; unknown when not determined.
    The kernel rounds a clipped point no nearer the walls: toward this side."""
    values = (*a, *b, *normal)
    if not all(number(v) for v in values):
        return UNKNOWN
    turn = _cross(normal, [b[0] - a[0], b[1] - a[1]])
    if abs(turn) < 1e-12:
        return UNKNOWN
    return "left" if (turn < 0) != (reverse is True) else "right"


def _ordered(record, reverse, order, keys):
    """Reverse ``keys`` lists for the traverse and stamp the order (unknown if unproven)."""
    if reverse is None:
        order = {"cut_order": UNKNOWN, **{k: v for k, v in order.items() if k != "cut_order"}}
        order.setdefault("cut_order_reason", "the traverse direction is not determined")
    elif reverse:
        for key in keys:
            record[key] = list(reversed(record[key]))
    record.update(order)
    return record


def _offset_line(a, b, offset):
    delta = [b[i] - a[i] for i in range(2)]
    norm = math.hypot(*delta)
    if norm == 0:
        return None
    direction = [v / norm for v in delta]
    return [a[0] - direction[1] * offset, a[1] + direction[0] * offset], direction


def _line_join(a, u, b, v):
    divisor = _cross(u, v)
    if abs(divisor) < 1e-12:
        return None
    t = _cross([b[i] - a[i] for i in range(2)], v) / divisor
    return [a[i] + t * u[i] for i in range(2)]


def _circle_join(point, direction, centre, radius, target):
    q = [point[i] - centre[i] for i in range(2)]
    dot = sum(q[i] * direction[i] for i in range(2))
    disc = dot * dot - sum(v * v for v in q) + radius * radius
    if disc < 0:
        return None
    roots = (-dot - math.sqrt(disc), -dot + math.sqrt(disc))
    candidates = [[point[i] + root * direction[i] for i in range(2)] for root in roots]
    return min(candidates, key=lambda p: math.dist(p, target))


def _top_join(top, linked, offset):
    """The upper arc's join needs each linked land, not its lower outline arc."""
    centre = top.get("arc_centre", top.get("at"))
    a, b = top.get("end"), linked.get("radial_tip_end")
    radius = _nominal(top, "radius")
    if not (
        all(isinstance(point, list) and len(point) >= 2 for point in (centre, a, b))
        and all(number(value) for point in (centre, a, b) for value in point)
        and all(number(value) for value in (radius, offset))
        and radius > offset
        and linked.get("frame", "model") == top.get("frame", "model")
    ):
        return None
    # The table spans the mirrored top arc. The -X land describes the same
    # join with reversed handedness, so evaluate it in the +X half-plane.
    a = [centre[0] + abs(a[0] - centre[0]), a[1]]
    b = [centre[0] + abs(b[0] - centre[0]), b[1]]
    land = _offset_line(a, b, offset)
    return _circle_join(*land, centre[:2], radius - offset, a) if land else None


def _joins(top, outer, offset):
    centre = outer.get("arc_centre")
    a, b, c = top.get("end"), outer.get("radial_tip_end"), outer.get("bottom_end")
    top_r, bottom_r = _nominal(top, "radius"), _nominal(outer, "bottom_radius")
    if not (
        isinstance(centre, list)
        and all(isinstance(v, list) and len(v) >= 2 for v in (a, b, c))
        and all(number(v) for point in (centre, a, b, c) for v in point)
        and all(number(v) for v in (top_r, bottom_r, offset))
    ):
        return None
    if top_r <= offset:
        return None
    land = _offset_line(a, b, offset)
    taper = _offset_line(b, c, offset)
    if land is None or taper is None:
        return None
    miter = _line_join(*land, *taper)
    upper = _circle_join(*land, centre[:2], top_r - offset, a)
    lower = _circle_join(*taper, centre[:2], bottom_r + offset, c)
    return [upper, miter, lower] if all(p is not None for p in (upper, miter, lower)) else None


def _xy_model(point, feature, frames):
    return model_point([point[0], point[1], 0.0], frames.get(feature.get("frame", "model")))


# Plan units within which a printed point still counts as no nearer a wall than its target.
_WALL_TOL = 1e-9
# Plan units within which two table ends are one join of the same cutter path.
_JOIN_TOL = 1e-6
# The DRO grid (plan units) of a machine whose inventory declares no ``resolution``: three
# decimals. The sheet prints, and the kernel checks, it.
DRO_DEFAULT_STEP = 0.001
# The operator note on a printed corner miter the kernel proves clear (rule A′).
OVERSHOOT_NOTE = "corner overshoot into scrap — OK"


def dro_grid(bundle, setup):
    """(step, decimals): the setup machine's DRO grid in plan units.

    The step is the inventory machine's declared ``resolution`` when it is a positive
    length, else :data:`DRO_DEFAULT_STEP`; the decimals print one step exactly. A bench
    (``kind`` bench or manual) declaring none has no DRO of its own: its surfaces are the
    ones the nearest machine setup in its stock lineage left, so they print on that
    machine's grid, one surface one value.
    """
    from ._bench import BENCH_KINDS
    from .tip_endpoints import lineage

    units = bundle.features.get("units")
    scale = {"mm": 1.0, "in": 25.4}.get(units)
    machine = resolve(bundle, "machines", setup.get("machine")) or {}
    declared = length_mm(machine, "resolution") if scale else UNKNOWN
    if not (number(declared) and declared > 0) and machine.get("kind") in BENCH_KINDS:
        source = next(
            (
                s
                for s in reversed(lineage(bundle, setup))
                if (resolve(bundle, "machines", s.get("machine")) or {}).get("kind")
                not in BENCH_KINDS
            ),
            None,
        )
        if source is not None:
            return dro_grid(bundle, source)
    step = declared / scale if number(declared) and declared > 0 else DRO_DEFAULT_STEP
    decimals = next((d for d in range(9) if abs(round(step, d) - step) <= 1e-12), 9)
    return step, decimals


def dro_grid_debt(bundle, setup):
    """Why the setup machine's DRO grid (:func:`dro_grid`) is provisional, else None.

    The grid is a shop fact only when the manifest units are mm or in and the inventory
    machine's ``resolution`` is a positive length qualified by its own complete
    measurement. A provisional grid still places and prints the targets, but no band check
    passes on it.
    """
    if bundle.features.get("units") not in UNIT_MM:
        return "feature units are not mm or in, so the DRO grid is provisional"
    name = setup.get("machine")
    fact = length_fact(resolve(bundle, "machines", name) or {}, "resolution")
    if not number(fact["value"]) or fact["value"] <= 0:
        return f"machine {name} declares no DRO resolution, so its grid is provisional"
    if not fact["verified"]:
        return f"machine {name}'s DRO resolution is unverified: {fact['reason']}"
    return None


def _grid(value, step, decimals, up):
    """``value`` on the DRO grid of ``step`` (printed at ``decimals``), rounded up (True)
    or down (False)."""
    steps = math.ceil(value / step - 1e-6) if up else math.floor(value / step + 1e-6)
    return round(steps * step, decimals)


def dro_z(value, grid):
    """A tip or floor Z as the DRO shows it on ``grid`` (:func:`dro_grid`): rounded up, so
    never deeper than authored; an unknown stays unknown."""
    return _grid(value, *grid, True) if number(value) else UNKNOWN


def dro_nearest(value, grid):
    """A position as the DRO dials it on ``grid``: the nearest grid point (a hole axis has
    no safe side); an unknown stays unknown."""
    step, decimals = grid
    return round(round(value / step) * step, decimals) if number(value) else UNKNOWN


def _to_segment(point, a, b):
    delta = [b[i] - a[i] for i in range(2)]
    span = delta[0] ** 2 + delta[1] ** 2
    t = sum((point[i] - a[i]) * delta[i] for i in range(2)) / span if span else 0.0
    t = max(0.0, min(1.0, t))
    return math.dist(point, [a[i] + t * delta[i] for i in range(2)])


def _to_arc(point, centre, radius, a, b, middle):
    """Distance from ``point`` to the arc of ``radius`` about ``centre`` running from ``a``
    through ``middle`` to ``b``: radial inside its sector, else to the nearer end."""

    def angle(q):
        return math.atan2(q[1] - centre[1], q[0] - centre[0])

    sweep = (angle(b) - angle(a)) % math.tau
    if (angle(middle) - angle(a)) % math.tau > sweep:  # the arc runs the other way round
        a, b, sweep = b, a, math.tau - sweep
    if (angle(point) - angle(a)) % math.tau <= sweep:
        return abs(math.dist(point, centre) - radius)
    return min(math.dist(point, a), math.dist(point, b))


def _ray_capsule(origin, direction, a, b, radius):
    """How far along the unit ``direction`` from ``origin`` the ray first meets the sweep
    of a cutter of ``radius`` moved from ``a`` to ``b`` (the capsule about that segment):
    0 when ``origin`` lies inside it, None when the ray misses it."""
    (ox, oy), (dx, dy), (ax, ay) = origin, direction, a
    best = None
    for ex, ey in (a, b):
        qx, qy = ox - ex, oy - ey
        dot = qx * dx + qy * dy
        disc = dot * dot - (qx * qx + qy * qy) + radius * radius
        if disc >= 0 and math.sqrt(disc) - dot >= 0:
            hit = max(0.0, -dot - math.sqrt(disc))
            best = hit if best is None else min(best, hit)
    span = math.dist(a, b)
    if span > 0:
        ux, uy = (b[0] - ax) / span, (b[1] - ay) / span
        low, high = 0.0, math.inf
        for vx, vy, lo, hi in ((ux, uy, 0.0, span), (-uy, ux, -radius, radius)):
            start = (ox - ax) * vx + (oy - ay) * vy  # the band beside the segment: two slabs
            speed = dx * vx + dy * vy
            if abs(speed) < 1e-15:
                if not lo <= start <= hi:
                    low = math.inf
                continue
            t0, t1 = (lo - start) / speed, (hi - start) / speed
            t0, t1 = (t0, t1) if t0 <= t1 else (t1, t0)
            low, high = max(low, t0), min(high, t1)
        if low <= high:
            best = low if best is None else min(best, low)
    return best


def _segment_cross(a, b):
    """Where segments ``a`` and ``b`` (point pairs) cross, as a list of at most one point."""
    d, e = [a[1][i] - a[0][i] for i in range(2)], [b[1][i] - b[0][i] for i in range(2)]
    divisor = _cross(d, e)
    if abs(divisor) < 1e-15:
        return []
    w = [b[0][i] - a[0][i] for i in range(2)]
    s, t = _cross(w, e) / divisor, _cross(w, d) / divisor
    if -1e-12 <= s <= 1 + 1e-12 and -1e-12 <= t <= 1 + 1e-12:
        return [[a[0][i] + s * d[i] for i in range(2)]]
    return []


def _segment_circle(segment, centre, radius):
    """Where ``segment`` (a point pair) crosses the circle of ``radius`` about ``centre``."""
    p, d = segment[0], [segment[1][i] - segment[0][i] for i in range(2)]
    f = [p[i] - centre[i] for i in range(2)]
    a = d[0] ** 2 + d[1] ** 2
    b = 2 * (f[0] * d[0] + f[1] * d[1])
    disc = b * b - 4 * a * (f[0] ** 2 + f[1] ** 2 - radius * radius)
    if a == 0 or disc < 0:
        return []
    roots = ((-b - math.sqrt(disc)) / (2 * a), (-b + math.sqrt(disc)) / (2 * a))
    return [[p[i] + t * d[i] for i in range(2)] for t in roots if -1e-12 <= t <= 1 + 1e-12]


def _circle_cross(a, b, radius):
    """Where two circles of one ``radius`` about ``a`` and ``b`` cross."""
    span = math.dist(a, b)
    if span == 0 or span > 2 * radius:
        return []
    rise = math.sqrt(max(0.0, radius * radius - span * span / 4)) / span
    middle = [(a[i] + b[i]) / 2 for i in range(2)]
    across = [a[1] - b[1], b[0] - a[0]]
    return [[middle[i] + side * rise * across[i] for i in range(2)] for side in (-1, 1)]


def _sweep_vertices(legs, radius, focus=None):
    """Where the material a stair leaves on a target surface can peak, against the
    capsules a cutter of ``radius`` sweeps along ``legs``: every point where two capsule
    outlines cross, each outline's straight-to-round junctions and, when the surface's
    normals all meet at ``focus`` (an arc's centre), the foot of the perpendicular from
    ``focus`` to each straight side (where a concave surface sits farthest from it).
    Between these points, measured along the surface normal, the material is monotone."""
    outlines, points = [], []
    for p, q in legs:
        span = math.dist(p, q)
        sides = []
        if span > 0:
            n = [(p[1] - q[1]) / span * radius, (q[0] - p[0]) / span * radius]
            sides = [
                [[p[i] + s * n[i] for i in range(2)], [q[i] + s * n[i] for i in range(2)]]
                for s in (-1, 1)
            ]
            points.extend(end for side in sides for end in side)
            if focus is not None:
                for a, b in sides:
                    t = sum((focus[i] - a[i]) * (b[i] - a[i]) for i in range(2)) / span**2
                    if 0 < t < 1:
                        points.append([a[i] + t * (b[i] - a[i]) for i in range(2)])
        outlines.append((sides, [p] if span == 0 else [p, q]))
    for (sides, ends), (others, centres) in itertools.combinations(outlines, 2):
        for side in sides:
            for other in others:
                points.extend(_segment_cross(side, other))
            for centre in centres:
                points.extend(_segment_circle(side, centre, radius))
        for end in ends:
            for other in others:
                points.extend(_segment_circle(other, end, radius))
            for centre in centres:
                points.extend(_circle_cross(end, centre, radius))
    return points


def _material(face, normal, legs, radius):
    """How far the material on a target surface at ``face`` runs along its unit
    ``normal`` (toward the cutter) before the cut: the ray's first entry into any capsule a
    cutter of ``radius`` sweeps along ``legs``; None when it meets none."""
    hits = [_ray_capsule(face, normal, p, q, radius) for p, q in legs]
    hits = [hit for hit in hits if hit is not None]
    return min(hits) if hits else None


def _dro_xy(xy, grid, walls, offset):
    """``xy`` as the DRO prints it on ``grid`` (:func:`dro_grid`), on the safe side: the
    nearest grid point no nearer any wall (``walls``: point -> distance) than ``xy`` or
    than the authored cutter-centre ``offset``, whichever is less; a corner of its grid
    cell, else up to two steps out, else unknown."""
    if not walls or not all(number(v) for v in xy):
        return [UNKNOWN, UNKNOWN]
    step, decimals = grid
    base = [_grid(v, step, decimals, False) for v in xy]
    floors = [min(wall(xy), offset) - _WALL_TOL for wall in walls]
    for reach in (1, 3):
        span = range(1 - reach, reach + 1)
        options = [
            [round(base[0] + i * step, decimals), round(base[1] + j * step, decimals)]
            for i in span
            for j in span
        ]
        for point in sorted(options, key=lambda p: math.dist(p, xy)):
            if all(wall(point) >= low for wall, low in zip(walls, floors, strict=True)):
                return point
    return [UNKNOWN, UNKNOWN]


def _printed(arcs, lines, grid, walls, offset):
    """Stamp every row and join point with the value the DRO prints: ``dro_xy``
    (:func:`_dro_xy`) and ``dro_tip_z`` (:func:`dro_z`). The sheet prints these; the kernel
    clips, checks and credits them. Points within _JOIN_TOL of each other (a table end and
    the join it meets) print one value."""
    done = []

    def dro(xy):
        if all(number(v) for v in xy):
            for point, value in done:
                if math.dist(point, xy) <= _JOIN_TOL:
                    return value
        value = _dro_xy(xy, grid, walls, offset)
        done.append((xy, value))
        return value

    for arc in arcs:
        arc["dro_tip_z"] = dro_z(arc.get("tip_z"), grid)
        for row in arc["rows"]:
            row["dro_xy"] = dro(row["setup_xy"])
            row["dro_tip_z"] = dro_z(row.get("tip_z"), grid)
    for line in lines:
        line["dro_tip_z"] = dro_z(line.get("tip_z"), grid)
        line["dro_xy"] = [dro(xy) for xy in line["setup_xy"]]


# Points per leg where a single-axis step is checked clear of the part and its cusp measured.
_STAIR_SAMPLES = 16


def _axis_tangents(angles, start, hand):
    """``angles`` (feature degrees) plus, between neighbours, each angle at which the arc
    is tangent to a setup axis (its setup X or Y extreme), where no single-axis step can
    stay on the scrap side. ``start`` is the setup angle of ``angles[0]`` about the arc
    centre and ``hand`` (+1 or -1) the handedness of the feature-to-setup map."""
    result = list(angles[:1])
    for a, b in itertools.pairwise(angles):
        ends = sorted(start + hand * (value - angles[0]) for value in (a, b))
        quarters = range(math.floor((ends[0] + 1e-7) / 90) + 1, math.ceil((ends[1] - 1e-7) / 90))
        between = [angles[0] + hand * (90 * quarter - start) for quarter in quarters]
        result.extend(sorted(between, reverse=b < a))
        result.append(b)
    return result


def _route_points(route):
    for a, b in itertools.pairwise(route):
        for k in range(_STAIR_SAMPLES + 1):
            yield [a[i] + k / _STAIR_SAMPLES * (b[i] - a[i]) for i in range(2)]


def _stair(printed, path, normal, locate, walls, cutter, offset, focus=None):
    """(steps, cusp, nearest, None) or (None, None, None, why not): single-axis handwheel
    moves through the ``printed`` points (setup XY).

    Each route runs from one printed point to the next. Where they differ on both axes it
    turns one corner, (b.x, a.y) or (a.x, b.y): one whose legs come no nearer any wall
    (``walls``: point -> distance) than the cutter-centre ``offset`` (or than either end,
    if that is nearer: :func:`_dro_xy`), the farther from the walls (the scrap side).
    Consecutive legs on one handwheel merge into one move, dropping the point between
    them: an axis never reverses for a step inside one move (a concave arc's tangent row
    is such a dip), which backlash makes unreliable, and the merged move lies on the legs
    it replaces, so it comes no nearer a wall. ``steps`` are (point, axis moved, printed
    row index or None for a corner) after the first printed point, in handwheel order.
    The cusp is the most material a target-surface point (``offset - cutter`` from a
    wall, so none past a wall's end) keeps from the stepped cutter of radius ``cutter``,
    measured along the wall normal (the radius of an arc), never the shorter distance to
    the nearest cutter edge: :func:`_material` from 15 points along each route and from
    every point where it can peak (:func:`_sweep_vertices`; ``focus`` is an arc's
    centre). ``path(k, t)`` is the exact cutter centre a fraction t from point k to
    k + 1, ``normal(k, xy)`` its unit normal from the wall toward the cutter and
    ``locate(k, point)`` the fraction t whose normal runs through ``point``, None when
    none on route k does. ``nearest`` is the least wall distance of any cutter centre on
    the moves.
    """
    if not walls or not number(cutter) or not all(_pair(p) for p in printed):
        return None, None, None, "its printed points or walls are unknown"
    routes = []
    for a, b in itertools.pairwise(printed):
        floors = [min(offset, wall(a), wall(b)) - _WALL_TOL for wall in walls]
        options = (
            [[a, b]]
            if a[0] == b[0] or a[1] == b[1]
            else [[a, [b[0], a[1]], b], [a, [a[0], b[1]], b]]
        )
        clear = [
            route
            for route in options
            if all(
                wall(p) >= floor
                for p in _route_points(route)
                for wall, floor in zip(walls, floors, strict=True)
            )
        ]
        if not clear:
            return None, None, None, STAIR_BLOCKED.format(a=a, b=b)
        routes.append(max(clear, key=lambda route: min(wall(route[1]) for wall in walls)))
    steps, spans = [], []  # spans: the first and last route each move steps
    for k, route in enumerate(routes):
        for p, q in itertools.pairwise(route):
            if p == q:
                continue
            axis, index, first = "Y" if p[0] == q[0] else "X", None, k
            if q is route[-1]:
                index = k + 1
            if steps and steps[-1][1] == axis:
                first = spans.pop()[0]
                steps.pop()
                if q == (steps[-1][0] if steps else printed[0]):
                    continue  # out and back to the same reading: no move at all
            steps.append((q, axis, index))
            spans.append((first, k))
    points = [printed[0], *(step[0] for step in steps)]
    moves = list(zip(itertools.pairwise(points), spans, strict=True))
    nearest = min(
        (wall(p) for move, _ in moves for p in _route_points(move) for wall in walls),
        default=min(wall(printed[0]) for wall in walls),
    )
    cusp = 0.0
    every = [move for move, _ in moves]
    for k in range(len(routes)):
        legs = [move for move, (first, last) in moves if first <= k + 1 and last >= k - 1]
        legs = legs or every
        if not legs:
            continue
        spots = [i / _STAIR_SAMPLES for i in range(_STAIR_SAMPLES + 1)]
        for point in _sweep_vertices(legs, cutter, focus):
            t = locate(k, point)
            if t is not None:
                spots.append(t)
        for t in set(spots):
            xy = path(k, t)
            n = normal(k, xy)
            face = [xy[j] - cutter * n[j] for j in range(2)]
            left = _material(face, n, legs, cutter)
            if left is not None and left <= cusp:
                continue  # raises no cusp, on the surface or not
            if abs(min(wall(face) for wall in walls) - (offset - cutter)) > _JOIN_TOL:
                continue  # past a wall's end (a join's miter run-out): no surface there
            left = left if left is not None else _material(face, n, every, cutter)
            if left is None:
                return None, None, None, STAIR_UNMEASURED
            cusp = max(cusp, left)
    return steps, cusp, nearest, None


# Why a stair cannot be stepped: every single-axis corner between two rows would bring the
# cutter nearer the finished line than its rough offset (an error, never a debt).
STAIR_BLOCKED = "no single-axis step from {a} to {b} stays outside the line"
# Why a stair's cusp is unknown: a wall normal meets no cutter sweep (a debt).
STAIR_UNMEASURED = "a wall normal meets none of its stair's cutter sweeps"


def _jog(arc, lines, centre, outward, walls, cutter, offset, scale):
    """Step ``arc`` and its join ``lines`` in single-axis moves (:func:`_stair`, walls kept
    ``offset`` away; the geometry, ``cutter`` and ``offset`` in plan units, ``scale`` mm
    per unit): each row names the axis (``jog``) moved to reach it and each corner is a
    row of its own (``corner``); each table records, in mm, its ``stair_cusp_mm`` and
    ``line_clear_mm`` (the least gap from the stepped cutter's edge to the finished line),
    else its ``stair_reason``."""
    rows = arc["rows"]
    exact = [row["setup_xy"] for row in rows]
    if not (_pair(centre) and all(_pair(p) for p in exact)):
        arc["stair_reason"] = "its cutter-centre path is unknown"
        return
    turns = [math.atan2(p[1] - centre[1], p[0] - centre[0]) for p in exact]
    radius = arc["cutter_centre_radius_mm"]

    def sweep(k):
        return (turns[k + 1] - turns[k] + math.pi) % math.tau - math.pi

    def along(k, t):
        angle = turns[k] + t * sweep(k)
        return [centre[0] + radius * math.cos(angle), centre[1] + radius * math.sin(angle)]

    def radial(k, xy):
        span = math.dist(xy, centre)
        return [outward * (xy[i] - centre[i]) / span for i in range(2)]

    def round_about(k, point):
        """The fraction of route k whose radius runs through ``point``."""
        if sweep(k) == 0 or math.dist(point, centre) == 0:
            return None
        turn = math.atan2(point[1] - centre[1], point[0] - centre[0]) - turns[k]
        return _fraction(((turn + math.pi) % math.tau - math.pi) / sweep(k))

    steps, cusp, nearest, why = _stair(
        [row["dro_xy"] for row in rows],
        along,
        radial,
        round_about,
        walls,
        cutter,
        offset,
        centre,
    )
    if why:
        arc["stair_reason"] = why
        return
    stepped = [rows[0]]
    for point, axis, index in steps:
        row = rows[index] if index is not None else None
        if row is None:
            row = {
                "angle_deg": UNKNOWN,
                "model_xy": [UNKNOWN, UNKNOWN],
                "setup_xy": list(point),
                "x": point[0],
                "y": point[1],
                "tip_z": stepped[-1].get("tip_z"),
                "dro_xy": list(point),
                "dro_tip_z": stepped[-1].get("dro_tip_z"),
                "corner": True,
            }
        row["jog"] = axis
        stepped.append(row)
    arc.update(rows=stepped, stair_cusp_mm=cusp * scale, line_clear_mm=(nearest - cutter) * scale)
    for line in lines:
        exact = line["setup_xy"]
        if not all(_pair(p) for p in exact):
            line["stair_reason"] = "its cutter-centre path is unknown"
            continue

        def straight(k, t, exact=exact):
            return [exact[k][i] + t * (exact[k + 1][i] - exact[k][i]) for i in range(2)]

        def away(k, xy, exact=exact):
            """The leg's unit normal toward the side farther from the walls."""
            delta = [exact[k + 1][i] - exact[k][i] for i in range(2)]
            span = math.hypot(*delta) or 1.0
            n = [-delta[1] / span, delta[0] / span]
            ahead = min(wall([xy[i] + 1e-3 * n[i] for i in range(2)]) for wall in walls)
            behind = min(wall([xy[i] - 1e-3 * n[i] for i in range(2)]) for wall in walls)
            return n if ahead >= behind else [-n[0], -n[1]]

        def across(k, point, exact=exact):
            """The fraction of leg k whose normal runs through ``point``."""
            delta = [exact[k + 1][i] - exact[k][i] for i in range(2)]
            span = delta[0] ** 2 + delta[1] ** 2
            if span == 0:
                return None
            return _fraction(sum((point[i] - exact[k][i]) * delta[i] for i in range(2)) / span)

        steps, cusp, nearest, why = _stair(
            line["dro_xy"], straight, away, across, walls, cutter, offset
        )
        if why:
            line["stair_reason"] = why
            continue
        columns = {key: [line[key][0]] for key in _LINE_COLUMNS}
        columns["jog"] = [None]
        for point, axis, index in steps:
            corner = {
                "model_xy": [UNKNOWN, UNKNOWN],
                "setup_xy": list(point),
                "dro_xy": list(point),
                "overshoot": False,
            }
            for key in _LINE_COLUMNS:
                columns[key].append(corner[key] if index is None else line[key][index])
            columns["jog"].append(axis)
        line.update(columns, stair_cusp_mm=cusp * scale, line_clear_mm=(nearest - cutter) * scale)


def _fraction(t):
    """``t`` when it lies on a route (0 to 1, to rounding), else None."""
    return min(1.0, max(0.0, t)) if -1e-9 <= t <= 1 + 1e-9 else None


def _stair_angles(start, end, forced, at, centre, outward, cusp, cutter):
    """Feature angles from ``start`` to ``end`` (through every ``forced`` angle, the
    setup-axis tangents of :func:`_axis_tangents`) spaced as far apart as a single-axis
    stair between neighbours keeps the material it leaves on the wall within ``cusp``:
    ``at(angle)`` is the setup XY of the cutter centre there, the stair's corner is the
    one on the scrap side (``outward``: away from ``centre`` when the cutter runs outside
    the wall) and the wall sits ``cutter`` (the cutter radius; 0 when unknown) inside the
    cutter-centre arc. A concave arc's tangent stop (not an end) is a dip the handwheel
    would run down to and straight back up from: :func:`_stair` merges that into one move
    that stops short of it, so the leg into or out of a dip is not counted and the dip's
    own face is measured. :func:`_stair` measures the printed stair's actual cusp."""
    span = abs(end - start)
    radius = math.dist(at(start), centre)
    reach = cutter if number(cutter) else 0.0
    count = min(_STAIR_CANDIDATES, max(8, math.ceil(math.radians(span) * radius / (cusp / 4))))
    stops = sorted({start, end, *forced}, reverse=end < start)
    dips = set(forced) - {start, end} if outward < 0 else set()
    angles = [stops[0]]
    for a, b in itertools.pairwise(stops):
        pieces = max(1, math.ceil(count * abs(b - a) / span))
        candidates = [a + (b - a) * i / pieces for i in range(pieces + 1)]
        points = [at(angle) for angle in candidates]
        faces = []
        for p in points:
            gap = math.dist(p, centre) or 1.0
            n = [outward * (p[k] - centre[k]) / gap for k in range(2)]
            faces.append(([p[k] - reach * n[k] for k in range(2)], n))

        def fits(i, j, points=points, faces=faces, pieces=pieces, a=a, b=b):
            p, q = points[i], points[j]
            corners = ([q[0], p[1]], [p[0], q[1]])
            corner = (max if outward > 0 else min)(corners, key=lambda c: math.dist(c, centre))
            samples = list(range(i + 1, j, max(1, (j - i) // _STAIR_SAMPLES)))
            legs = [(p, corner), (corner, q)]
            if a in dips and i == 0:
                legs, samples = legs[1:], [i, *samples]
            if b in dips and j == pieces:
                legs, samples = legs[:-1], [*samples, j]
            if not legs:
                return False
            left = (_material(*faces[m], legs, reach) for m in samples)
            return all(gap is not None and gap <= cusp for gap in left)

        i = 0
        while i < pieces:
            low, high = i + 1, pieces
            while low < high:  # the farthest candidate whose stair still fits
                middle = (low + high + 1) // 2
                low, high = (middle, high) if fits(i, middle) else (low, middle - 1)
            angles.append(candidates[low])
            i = low
    return angles


# The most candidate angles one stair table is spaced from.
_STAIR_CANDIDATES = 20000


def _arc(
    feature_name,
    feature,
    op,
    offset,
    frame,
    frames,
    features,
    sense,
    order,
    grid,
    method,
    cutter=UNKNOWN,
    scale=1.0,
):
    """([the arc table], join lines, walls) in cutting order for ``sense`` (cut_order).

    The cutter-side wall normal is radial: outward when the cutter centre runs outside the
    wall radius, inward on a concave wall. A join's normal is its offset land's normal.
    Every row and join point carries the value the DRO prints on ``grid``
    (:func:`dro_grid`), never nearer the feature's walls (:func:`_printed`); each join's
    corner miter, the run-out past its land and taper walls, is flagged ``overshoot``. A
    bounded op's tables are whole here: the kernel clips them (:func:`_kernel_clip`).
    ``walls`` (point -> distance to each feature wall, setup XY) is empty when unknown.

    The geometry, the cutter-centre ``offset`` and the ``cutter`` radius are plan units;
    ``scale`` is mm per unit, for the contour's mm inputs (``cusp_mm``, ``pitch_mm``) and
    the table's ``cutter_radius_mm`` and stair measures. The ``method`` spaces the rows:
    ``stairs`` rows are spaced through each setup-axis tangent so each printed stair stays
    within the contour's ``cusp_mm`` (:func:`_stair_angles`, :func:`_respaced`; joins are
    split likewise) and step in single-axis moves of a cutter of radius ``cutter``
    (:func:`_jog`, which drops a tangent row a move runs through); ``chain_drill`` rows
    are hole centres no more than ``pitch_mm`` apart along the path; ``rotary_table`` rows
    sample the cutter-centre arc every ``step_deg``; ``chords`` rows are the ``count + 1``
    chord vertices :func:`_chords` replaces.
    """
    radius = _nominal(feature, "radius")
    centre = feature.get("arc_centre", feature.get("at"))
    full = feature.get("kind") in {"boss", "cylinder"}
    if full:
        diameter = _nominal(feature, "dia")
        radius = diameter / 2 if number(diameter) else UNKNOWN
    bottom = "bottom_radius" in feature
    if bottom:
        radius = _nominal(feature, "bottom_radius")
    if not (
        number(radius)
        and number(offset)
        and isinstance(centre, list)
        and len(centre) == 3
        and all(number(v) for v in centre)
    ):
        return [], [], []
    cutter_radius = radius + offset
    start, end = 0.0, 360.0 if full else 180.0
    vertical_angle = False
    joins = None
    lands = []  # a top arc's linked land segments (model xy): walls its end rows meet
    if "end" in feature or bottom:
        vertical_angle = True
        if bottom:
            top = mapping(features.get(feature.get("top_edge_feature")))
            joins = _joins(top, feature, offset)
            if joins is None:
                return [], [], []
            endpoint = joins[2] if joins else feature.get("bottom_end")
        else:
            cutter_radius = radius - offset
            linked = [f for f in features.values() if f.get("top_edge_feature") == feature_name]
            endpoints = [_top_join(feature, linked_feature, offset) for linked_feature in linked]
            if linked:
                if any(point is None for point in endpoints):
                    return [], [], []
                endpoint = endpoints[0]
                if any(math.dist(endpoint, point) > 1e-9 for point in endpoints[1:]):
                    return [], [], []
                # Each land as _top_join takes it, on both halves of the mirrored top arc.
                lands = [
                    [
                        [centre[0] + side * abs(p[0] - centre[0]), p[1]]
                        for p in (feature["end"], linked_feature["radial_tip_end"])
                    ]
                    for linked_feature in linked
                    for side in (-1, 1)
                ]
            else:
                endpoint = feature.get("end")
        if not isinstance(endpoint, list) or not all(number(v) for v in endpoint):
            return [], [], []
        half = math.degrees(math.atan2(endpoint[0] - centre[0], centre[1] - endpoint[1]))
        start, end = -half, half
    elif not full and feature.get("arc") != "upper_semicircle":
        return [], [], []
    if cutter_radius <= 0:
        return [], [], []
    contour = mapping(op.get("contour"))
    model_centre = model_point(centre, frames.get(feature.get("frame", "model")))
    centre_xy = frame_point(model_centre, frame)[:2]

    def setup_xy(point):
        return frame_point(_xy_model(point, feature, frames), frame)[:2]

    def unit(angle):
        theta = math.radians(angle)
        if vertical_angle:
            return [math.sin(theta), -math.cos(theta)]
        return [math.cos(theta), math.sin(theta)]

    def row_at(angle):
        xy = [centre[i] + cutter_radius * unit(angle)[i] for i in range(2)]
        local = frame_point(_xy_model(xy, feature, frames), frame)
        return {
            "angle_deg": angle,
            "model_xy": xy,
            "setup_xy": local[:2],
            "x": local[0],
            "y": local[1],
            "tip_z": op.get("to_z", UNKNOWN),
        }

    outward = 1 if cutter_radius > radius else -1
    span = math.radians(abs(end - start)) * cutter_radius
    step = UNKNOWN
    angles, space = [], None
    if method == "rotary_table":
        step = contour.get("step_deg", UNKNOWN)
        angles = _samples(start, end, step)
    elif method == "chords" and isinstance(contour.get("count"), int) and contour["count"] > 0:
        angles = [start + (end - start) * i / contour["count"] for i in range(contour["count"] + 1)]
    elif method == "chain_drill" and number(contour.get("pitch_mm")) and contour["pitch_mm"] > 0:
        pieces = max(1, math.ceil(span / (contour["pitch_mm"] / scale)))
        angles = [start + (end - start) * i / pieces for i in range(pieces + 1)]
    elif method == "stairs" and number(contour.get("cusp_mm")) and contour["cusp_mm"] > 0:
        base = setup_xy(centre[:2])
        axes = [setup_xy([centre[0] + (i == 0), centre[1] + (i == 1)]) for i in range(2)]
        if _pair(base) and all(_pair(p) for p in axes):
            basis = [[p[j] - base[j] for j in range(2)] for p in axes]

            def at(angle):
                u = unit(angle)
                return [
                    base[j] + cutter_radius * (u[0] * basis[0][j] + u[1] * basis[1][j])
                    for j in range(2)
                ]

            first, second = (
                math.degrees(math.atan2(p[1] - base[1], p[0] - base[0]))
                for p in (at(start), at(start + 1.0))
            )
            hand = 1 if (second - first + 180) % 360 - 180 > 0 else -1
            forced = _axis_tangents([start, end], first, hand)

            def space(target):  # target: the cusp in mm
                return _stair_angles(start, end, forced, at, base, outward, target / scale, cutter)

            angles = space(contour["cusp_mm"])

    def table(angles):
        rows = [row_at(angle) for angle in angles]
        reverse, arc_side = None, UNKNOWN
        if len(rows) >= 2 and cutter_radius != radius and all(number(v) for v in centre_xy):
            a, b = rows[len(rows) // 2 - 1]["setup_xy"], rows[len(rows) // 2]["setup_xy"]
            if all(number(v) for v in (*a, *b)):
                normal = [outward * ((a[i] + b[i]) / 2 - centre_xy[i]) for i in range(2)]
                reverse = _reversal(a, b, normal, sense)
                arc_side = _side(a, b, normal, reverse)
        arc = {
            "feature": feature_name,
            "op": op["op"],
            "method": method,
            **({"step_deg": step} if method == "rotary_table" else {}),
            **({"cusp_mm": contour["cusp_mm"]} if method == "stairs" and angles else {}),
            "centre_model_xy": model_centre[:2],
            "centre_setup_xy": centre_xy,
            "wall_radius_mm": radius,
            "cutter_radius_mm": cutter * scale if number(cutter) else UNKNOWN,
            "cutter_centre_radius_mm": cutter_radius,
            "radius_mm": cutter_radius,
            "full_circle": full,
            "tip_z": op.get("to_z", UNKNOWN),
            "rows": rows,
            "basis": (
                "nominal selected cutter size; measured geometry and frame binding "
                + "govern readiness"
            ),
        }
        _ordered(arc, reverse, order, ("rows",))
        arc["cutter_side"] = arc_side
        return arc

    arc = table(angles)
    walls, miters = [], []  # point -> distance to each feature wall; join miter points
    known = all(number(v) for v in centre_xy)  # else no wall is placed and no DRO value

    def rim(wall_radius, end_xy):
        """point -> distance to the wall arc of ``wall_radius`` about the centre: mirrored
        from ``end_xy`` through its lowest point (an upper semicircle's highest), a full
        circle when ``end_xy`` is None. Never its circle past its ends."""
        if end_xy is None:
            return lambda p: abs(math.dist(p, centre_xy) - wall_radius)
        dip = -wall_radius if vertical_angle else wall_radius
        mirror = [2 * centre[0] - end_xy[0], end_xy[1]]
        a, b, m = (setup_xy(q) for q in (end_xy, mirror, [centre[0], centre[1] + dip]))
        return lambda p: _to_arc(p, centre_xy, wall_radius, a, b, m)

    if known:
        if full:
            walls.append(rim(radius, None))
        elif vertical_angle:  # _joins, _top_join or the endpoint check validated the end
            walls.append(rim(radius, feature["bottom_end"] if bottom else feature["end"]))
        else:
            walls.append(rim(radius, [centre[0] + radius, centre[1]]))
    for a, b in ([setup_xy(a), setup_xy(b)] for a, b in lands):
        known = known and all(number(v) for v in (*a, *b))
        walls.append(lambda p, a=a, b=b: _to_segment(p, a, b))
    lines = []
    if bottom and joins:
        sides = (-1, 1) if feature.get("mirror_symmetric") is True else (1,)
        # _joins validated both land ends; the land's unit left normal is its cutter side.
        top_end = mapping(features.get(feature.get("top_edge_feature")))["end"]
        shifted, _ = _offset_line(top_end, feature["radial_tip_end"], 1.0)
        left = [shifted[i] - top_end[i] for i in range(2)]
        top_r = _nominal(top, "radius")
        if known:
            walls.append(rim(top_r, top_end))
        for side in sides:
            xy = [[centre[0] + side * (p[0] - centre[0]), p[1]] for p in joins]
            local = [setup_xy(p) for p in xy]
            wall = setup_xy([xy[0][0] - side * left[0] * offset, xy[0][1] - left[1] * offset])
            ends = [
                setup_xy([centre[0] + side * (p[0] - centre[0]), p[1]])
                for p in (top_end, feature["radial_tip_end"], feature["bottom_end"])
            ]
            known = known and all(number(v) for point in ends for v in point)
            for a, b in itertools.pairwise(ends):
                walls.append(lambda p, a=a, b=b: _to_segment(p, a, b))
            miters.append(xy[1])
            normal = [
                local[0][i] - wall[i] if number(local[0][i]) and number(wall[i]) else UNKNOWN
                for i in range(2)
            ]
            line = {
                "op": op["op"],
                "feature": feature_name,
                "side": "+X" if side == 1 else "-X",
                "model_xy": xy,
                "setup_xy": local,
                "offset_mm": offset,
                "tip_z": op.get("to_z", UNKNOWN),
                "join_method": "line-line miter and exact line-circle intersections",
            }
            reverse = _reversal(local[0], local[1], normal, sense)
            lines.append(_ordered(line, reverse, order, ("model_xy", "setup_xy")))
            line["cutter_side"] = _side(local[0], local[1], normal, reverse)
    if not angles:
        return [], [], []
    if method == "stairs":
        for line in lines:
            _split(line, contour["cusp_mm"] / scale)
    walls = walls if known else []
    if space is not None and walls:

        def measure(angles):
            trial = table(angles)
            _printed([trial], [], grid, walls, offset)
            _jog(trial, [], centre_xy, outward, walls, cutter, offset, scale)
            return trial.get("stair_cusp_mm")

        arc = table(_respaced(angles, space, contour["cusp_mm"], measure))
    _printed([arc], lines, grid, walls, offset)
    for line in lines:
        line["overshoot"] = [any(p is m for m in miters) for p in line["model_xy"]]
        if any(line["overshoot"]):
            line["overshoot_note"] = OVERSHOOT_NOTE
    if method == "stairs":
        _jog(arc, lines, centre_xy, outward, walls, cutter, offset, scale)
        if arc.get("stair_cusp_mm", 0.0) > contour["cusp_mm"] + _JOIN_TOL:
            arc["stair_reason"] = STAIR_SPACING.format(
                cusp=round(arc["stair_cusp_mm"], 4), target=contour["cusp_mm"]
            )
    return [arc], lines, walls


def _respaced(angles, space, cusp, measure):
    """Stair ``angles`` respaced (``space(target)``: :func:`_stair_angles`) until the
    printed stair through them keeps within ``cusp`` (``measure(angles)``: the printed
    stair's cusp, None when it cannot be stepped). The DRO grid moves each printed row a
    little outside the exact point the spacing fits, so the target shrinks by each excess,
    at most :data:`_STAIR_RESPACINGS` times; :func:`_arc` measures the result again. A
    shrink that moves no row is doubled until one moves: an excess finer than the
    spacing's step would otherwise respace the same rows every time."""
    target = cusp
    for _ in range(_STAIR_RESPACINGS):
        measured = measure(angles)
        if measured is None or measured <= cusp:
            return angles
        shrink = measured - cusp
        while True:
            target -= shrink
            if target <= 0:
                return angles
            spaced = space(target)
            if spaced != angles:
                break
            shrink *= 2
        angles = spaced
    return angles


# The most times a stair table is respaced to keep its printed cusp within ``cusp_mm``.
_STAIR_RESPACINGS = 6
# Why a stair table is unproven: no spacing kept its printed stair within ``cusp_mm``.
STAIR_SPACING = "its printed stairs leave {cusp} mm on the wall, more than cusp_mm {target}"


def _split(line, cusp):
    """Split each leg of a join ``line`` into equal pieces whose single-axis stair keeps
    within ``cusp`` of it (a stair across a leg of run dx, rise dy over n pieces leaves
    |dx·dy| / (n·length))."""
    model, setup = [line["model_xy"][0]], [line["setup_xy"][0]]
    for k in range(1, len(line["setup_xy"])):
        a, b = line["setup_xy"][k - 1], line["setup_xy"][k]
        pieces = 1
        if _pair(a) and _pair(b) and math.dist(a, b) > 0:
            corner = abs((b[0] - a[0]) * (b[1] - a[1])) / math.dist(a, b)
            pieces = max(1, math.ceil(corner / cusp))
        for i in range(1, pieces):
            model.append(_between(line["model_xy"][k - 1], line["model_xy"][k], i / pieces))
            setup.append(_between(a, b, i / pieces))
        model.append(line["model_xy"][k])
        setup.append(b)
    line.update(model_xy=model, setup_xy=setup)


def _boundary(feature, frame, frames):
    bounds = mapping(feature.get("bounds"))
    if not all(
        axis in bounds
        and isinstance(bounds[axis], list)
        and len(bounds[axis]) == 2
        and all(number(v) for v in bounds[axis])
        for axis in AXES
    ):
        return None
    points = [
        frame_point(model_point(list(p), frames.get(feature.get("frame", "model"))), frame)
        for p in itertools.product(*(bounds[axis] for axis in AXES))
    ]
    if not all(number(v) for p in points for v in p[:2]):
        return None
    points = sorted(set(tuple(p[:2]) for p in points))
    if len(points) < 3:
        return None

    def half(sequence):
        hull = []
        for p in sequence:
            while (
                len(hull) >= 2
                and _cross(
                    [hull[-1][i] - hull[-2][i] for i in range(2)],
                    [p[i] - hull[-1][i] for i in range(2)],
                )
                <= 0
            ):
                hull.pop()
            hull.append(p)
        return hull

    return half(points)[:-1] + half(reversed(points))[:-1]


def _sweep_area(feature, op, frame, frames):
    """Setup-XY corners of the area a ``linear_table`` sweeps, or None: ``contour.
    sweep_bounds`` in ``sweep_frame``, else a face op's or side-milling profile's
    (:func:`_rastered`) setup-frame ``stock_removal_bounds``, else the feature's own
    bounds."""
    contour = mapping(op.get("contour"))
    if isinstance(contour.get("sweep_bounds"), dict):
        envelope = {
            **feature,
            "bounds": contour["sweep_bounds"],
            "frame": contour.get("sweep_frame", feature.get("frame", "model")),
        }
        return _boundary(envelope, frame, frames)
    box = op.get("stock_removal_bounds")
    side_mill = op.get("do") in _PROFILE_OPS and "open_side" in contour
    if (op.get("do") in FACING or side_mill) and isinstance(box, dict):
        spans = [box.get(axis) for axis in ("x", "y")]
        if not all(
            isinstance(span, list) and len(span) == 2 and all(number(v) for v in span)
            for span in spans
        ):
            return None
        (x0, x1), (y0, y1) = spans
        return [[x0, y0], [x1, y0], [x1, y1], [x0, y1]]
    return _boundary(feature, frame, frames)


def _linear(feature, op, offset, radius, frame, frames, grid):
    """(Closed cutter-centre outline on the DRO grid, residual) or (None, None).

    The swept area is convex (:func:`_boundary`), so a vertex no nearer either wall line it
    joins than ``offset`` keeps both edges through it off those walls. Each vertex is the
    nearest grid point outside both lines by at least ``offset`` (the safe side: material
    is left, never cut), a corner of its grid cell, else up to two steps out. The residual
    is the most any vertex stands further off a wall line than ``offset``: material left
    on that wall; ``inf`` when a vertex has no such grid point."""
    boundary = _sweep_area(feature, op, frame, frames)
    if not boundary or not all(number(v) for v in (offset, radius)):
        return None, None
    lines = [
        _offset_line(boundary[i], boundary[(i + 1) % len(boundary)], -offset)
        for i in range(len(boundary))
    ]
    if any(line is None for line in lines):
        return None, None
    vertices = [_line_join(*lines[i - 1], *lines[i]) for i in range(len(lines))]
    if any(v is None for v in vertices):
        return None, None

    def outside(index, point):
        """Signed distance of ``point`` outside wall ``index``'s line (outward normal)."""
        a, direction = boundary[index], lines[index][1]
        return (point[0] - a[0]) * direction[1] - (point[1] - a[1]) * direction[0]

    step, decimals = grid
    snapped, residual = [], 0.0
    for index, vertex in enumerate(vertices):
        walls = (index - 1, index)
        base = [_grid(v, step, decimals, False) for v in vertex]
        point = None
        for reach in (1, 3):
            span = range(1 - reach, reach + 1)
            options = sorted(
                (
                    [round(base[0] + i * step, decimals), round(base[1] + j * step, decimals)]
                    for i in span
                    for j in span
                ),
                key=lambda p: math.dist(p, vertex),
            )
            point = next(
                (p for p in options if all(outside(w, p) >= offset - _WALL_TOL for w in walls)),
                None,
            )
            if point is not None:
                break
        if point is None:
            return None, math.inf
        residual = max(residual, *(outside(w, point) - offset for w in walls))
        snapped.append(point)
    return snapped + [snapped[0]], residual


# Raster ops: each pass is one straight single-axis cut fed one way at the op's Z, then the
# cutter lifts to its retract height and rapids back to the next pass's start.
RASTER_OPS = POCKETING | FACING
# An open side's unit vector: every pass's cutter-side wall normal, from the uncut stock
# ahead of the stepping cutter back toward the cleared side it steps away from.
_OPEN_SIDES = {"-x": (-1.0, 0.0), "+x": (1.0, 0.0), "-y": (0.0, -1.0), "+y": (0.0, 1.0)}
# Milling ops whose authored ``doc_mm`` steps them down in axial levels.
_PROFILE_OPS = {"profile", "rough_profile", "finish_profile"}
_LEVEL_OPS = RASTER_OPS | _PROFILE_OPS
# Wall-finishing ops: the cutter's flank engages the whole wall above its tip.
_WALL_OPS = {"pocket", "finish_pocket", "profile", "finish_profile"}


def _rastered(op, contour):
    """Whether a ``linear_table`` op cuts in raster passes: a pocket or face, or a profile
    with a declared ``open_side``: a one-sided side-mill (a blank end overhanging the vise)
    whose passes step from clear air on the open side to the retained wall, as a pocket's."""
    return op.get("do") in RASTER_OPS or (op.get("do") in _PROFILE_OPS and "open_side" in contour)


def _outside_circle(segment, circle, radius, grid, scale):
    """(The positive-length pieces of an axis-parallel pass, in feed order, and the part of
    it the island removed, or None). Each cut point lies on the DRO ``grid``
    (:func:`dro_grid`), rounded away from the island, so the printed piece never reaches
    nearer than the island radius plus ``radius``; the removed part runs from the entry to
    the exit cut point, or to the pass's own end where no piece is left there. The island's
    ``dia_mm`` is millimetres; ``segment``, ``radius`` and ``grid`` are plan units
    (``scale`` mm per plan unit)."""
    a, b = segment
    axis = 0 if a[0] != b[0] else 1
    across = 1 - axis
    centre = circle["at"]
    island = circle["dia_mm"] / 2 / scale
    whole = [segment] if math.dist(a, b) > 1e-9 else []
    reach_squared = (island + radius) ** 2 - (a[across] - centre[across]) ** 2
    if reach_squared <= 0:  # tangent or outside: no interior crossing
        return whole, None
    reach = math.sqrt(reach_squared)
    low, high = centre[axis] - reach, centre[axis] + reach
    if max(a[axis], b[axis]) <= low or min(a[axis], b[axis]) >= high:
        return whole, None
    low, high = _grid(low, *grid, False), _grid(high, *grid, True)
    forward = b[axis] > a[axis]
    entry, exit = (low, high) if forward else (high, low)
    pieces, removed = [], [list(a), list(b)]
    if (entry - a[axis]) * (1 if forward else -1) > 1e-9:
        point = list(a)
        point[axis] = entry
        pieces.append([a, point])
        removed[0] = point
    if (b[axis] - exit) * (1 if forward else -1) > 1e-9:
        point = list(b)
        point[axis] = exit
        pieces.append([point, b])
        removed[1] = point
    return pieces, removed


def _raster(feature, op, offset, radius, frame, frames, sense, order, lift_z, grid, scale):
    """(One stage's raster record in cutting order, None) or (None, why it is unknown).

    Passes stand at positions across the area, stepping from its open side
    (``contour.open_side``) toward the far side, and each runs one cutter radius past both
    ends of the area. A pocket's first pass enters wholly outside the open side, the next
    are ``step_mm`` apart and the last stops ``offset`` short of the retained far wall. A
    face's passes are evenly spaced no more than ``step_mm`` apart from centre-on-edge to
    centre-on-edge, clearing the whole area; without an open side it steps from the low
    side of the area's shorter span, so its passes run along the longer one.

    Every value sits on the DRO ``grid`` on the safe side: pass ends and a face's edge
    passes round outward, a pocket's first pass further outside its open side and its last
    away from the retained far wall (the material it leaves there is ``grid_residual_mm``);
    passes between step a whole number of grid steps no larger than ``step_mm``.

    The uncut stock lies ahead of the stepping cutter, so every pass's cutter-side wall
    normal is the open side's unit vector: each pass runs the way that cuts the op's
    ``direction`` with the spindle (:func:`_reversal`), else the order is unknown. The
    cycle is one way: feed a pass, lift to ``lift_z``, rapid back to the next pass's start.
    ``step_mm``, ``offset`` and ``radius`` are millimetres; the passes stand in plan units
    (``scale`` mm per plan unit).
    """
    face = op.get("do") in FACING
    contour = mapping(op.get("contour"))
    step = contour.get("step_mm", UNKNOWN)
    if not number(step) or step <= 0:
        return None, "a raster needs a positive contour.step_mm"
    if not number(radius) or radius <= 0:
        return None, "its cutter radius is unknown"
    keep_out = []
    if "keep_out" in contour:
        circles = contour["keep_out"]
        if not isinstance(circles, list):
            return None, "its contour.keep_out must be a list of circles"
        sweep_frame = frames.get(contour.get("sweep_frame", feature.get("frame", "model")))
        for circle in circles:
            circle = mapping(circle)
            at, diameter = circle.get("at"), circle.get("dia_mm")
            if not (
                isinstance(at, list)
                and len(at) == 2
                and all(number(v) and math.isfinite(v) for v in at)
                and number(diameter)
                and math.isfinite(diameter)
                and diameter > 0
            ):
                return None, "its contour.keep_out needs numeric XY at and positive dia_mm"
            centre = frame_point(model_point([*at, 0.0], sweep_frame), frame)[:2]
            if not all(number(v) and math.isfinite(v) for v in centre):
                return None, "its contour.keep_out centre has no numeric setup-frame mapping"
            keep_out.append({"at": centre, "dia_mm": diameter})
    if not face and not number(offset):
        return None, "its cutter-centre offset from the far wall is unknown"
    if step > 2 * radius:
        return None, f"its step_mm {step:g} exceeds the cutter diameter {2 * radius:g}"
    if not number(scale):
        return None, "its plan units are neither mm nor in"
    authored, step, radius = step, step / scale, radius / scale
    offset = offset / scale if number(offset) else offset
    unit, decimals = grid
    lattice = round(math.floor(step / unit + 1e-6) * unit, decimals)
    if lattice <= 0:
        return None, f"its step_mm {authored:g} is finer than the DRO grid {unit:g}"
    boundary = _sweep_area(feature, op, frame, frames)
    if not boundary:
        return None, "its swept area has no numeric bounds"
    left, right = min(p[0] for p in boundary), max(p[0] for p in boundary)
    front, back = min(p[1] for p in boundary), max(p[1] for p in boundary)
    side = contour.get("open_side")
    if face and side is None:
        side = "-y" if right - left >= back - front else "-x"
    if side not in _OPEN_SIDES:
        return None, f"its contour.open_side {side!r} is not one of -x, +x, -y, +y"
    along_x = side.endswith("x")  # passes stand at X positions and run along Y
    low, high = (left, right) if along_x else (front, back)
    residual = 0.0
    if face:
        lo, hi = _grid(low, unit, decimals, False), _grid(high, unit, decimals, True)
        count = math.ceil((hi - lo) / lattice - 1e-9)
        if count > 1:
            spacing = _grid((hi - lo) / count, unit, decimals, True)
            inner = (round(lo + i * spacing, decimals) for i in range(count))
            positions = [v for v in inner if v < hi - _WALL_TOL] + [hi]
        else:
            positions = [dro_nearest((low + high) / 2, grid)]
        if side.startswith("+"):
            positions.reverse()
    else:
        outward = side.startswith("-")
        start = _grid(low - radius if outward else high + radius, unit, decimals, not outward)
        exact = high - offset if outward else low + offset
        end = _grid(exact, unit, decimals, not outward)
        residual = abs(exact - end)
        direction = 1 if end >= start else -1
        count = math.ceil(abs(end - start) / lattice - 1e-9)
        positions = [round(start + direction * i * lattice, decimals) for i in range(count)]
        positions.append(end)
    first, last = (front, back) if along_x else (left, right)
    near, far = (
        _grid(first - radius, unit, decimals, False),
        _grid(last + radius, unit, decimals, True),
    )
    passes = [[[v, near], [v, far]] if along_x else [[near, v], [far, v]] for v in positions]
    reverse = _reversal(*passes[0], _OPEN_SIDES[side], sense)
    if reverse:
        passes = [list(reversed(segment)) for segment in passes]
    skipped = []
    for circle in keep_out:
        split = []
        for segment in passes:
            pieces, removed = _outside_circle(segment, circle, radius, grid, scale)
            split.extend(pieces)
            if removed is not None:
                skipped.append(removed)
        passes = split
    record = {
        "cutter_centre": passes,
        "grid_residual_mm": residual,
        "raster": {
            "open_side": side,
            "open_side_basis": "contour.open_side" if "open_side" in contour else "derived",
            "step_mm": authored,
            "passes": len(passes),
            "cycle": "one_way",
            "lift_z": lift_z,
            # Cutter clearance past the swept area: the passes run from ``ends[0]`` to
            # ``ends[1]`` along ``run_axis``, one cutter radius beyond the area's edges
            # ``area_ends`` (clear of the area, not proven clear of the stock); a keep_out
            # splits them into pieces that also start and stop between. A pocket's first
            # pass stands one radius outside its open side (``entry_pass``).
            "run_axis": "y" if along_x else "x",
            "area_ends": [first, last],
            "ends": [near, far],
            "clearance_mm": radius,
            "entry_pass": "not_applicable" if face else start,
        },
    }
    if "keep_out" in contour:
        record["raster"]["keep_out"] = keep_out
        # The parts of the island-free passes the circles removed: with the printed pieces
        # they make up every whole pass, so the kernel knows what no printed piece sweeps.
        record["raster"]["keep_out_skipped"] = skipped
    return _ordered(record, None if reverse is None else False, order, ()), None


def _xy_box(op):
    """An op's setup-frame stock_removal_bounds X and Y spans, or None."""
    box = mapping(op.get("stock_removal_bounds"))
    spans = [box.get(axis) for axis in ("x", "y")]
    if all(isinstance(s, list) and len(s) == 2 and all(number(v) for v in s) for s in spans):
        return spans
    return None


def _cleared_floor(op, cleared, features):
    """The lowest floor an earlier face or pocket op of the setup provably cleared under
    all of ``op``'s region, or None. ``cleared`` holds each such op's feature, setup-frame
    XY stock_removal_bounds and ``to_z``. It counts only if its box holds ``op``'s whole
    box and it produced ``op``'s surface under the operative-producer contract: the same
    feature, or one whose X/Y ``bounds`` hold ``op``'s feature's whole footprint
    (:func:`_covers_xy`). Overlap, a partial region or an unboxed op proves nothing."""
    name, region = op.get("feature"), _xy_box(op)
    target = mapping(features.get(name))
    floors = [
        to_z
        for cut, box, to_z in cleared
        if region
        and all(box[i][0] <= region[i][0] and region[i][1] <= box[i][1] for i in range(2))
        and (cut == name or (target and _covers_xy(mapping(features.get(cut)), target)))
    ]
    return min(floors) if floors else None


def _z_levels(op, before, declared, cleared, features, grid, units, printed_top):
    """The axial Z levels of a milling op that authors ``doc_mm``, else None.

    Levels step from the op's start surface down to its DRO depth, each on the DRO grid and
    no more than ``doc_mm`` below the one before; the last is the DRO depth itself. Each
    starts at its feature's declared setup ``entry_z``, else the current top. A
    wall-finishing op keeps that start, as its flank engages the whole wall; any other op
    starts lower only on an earlier face or pocket op's floor that provably cleared all of
    its region (:func:`_cleared_floor`). A start on the top prints as the setup prints the
    top before the op (``printed_top``, :func:`~.tip_endpoints.operative_z`), any other on
    the grid (``dro_z``), and the levels step down from it.
    """
    if op.get("do") not in _LEVEL_OPS or "doc_mm" not in op or "to_z" not in op:
        return None
    name, top = op.get("feature"), before["top_z"]
    start = declared.get(name, top)
    basis = "declared entry_z" if name in declared else "setup top_z"
    floor = None if op["do"] in _WALL_OPS else _cleared_floor(op, cleared, features)
    if floor is not None and number(start) and floor < start:
        start, basis = floor, "floor of an earlier op that cleared this op's whole region"
    end, doc = dro_z(op["to_z"], grid), op["doc_mm"]
    if basis == "setup top_z":
        printed = printed_top if number(start) else UNKNOWN
    else:
        printed = dro_z(start, grid) if number(start) else UNKNOWN
    record = {"start_z": start, "start_basis": basis, "dro_start_z": printed}
    record.update(dro_to_z=end, doc_mm=doc)
    scale = {"mm": 1.0, "in": 25.4}.get(units)
    step, decimals = grid
    depth = doc / scale if scale and number(doc) and doc > 0 else UNKNOWN
    lattice = math.floor(depth / step + 1e-6) * step if number(depth) else 0
    if not (number(printed) and number(end)) or lattice <= 0:
        record.update(levels=UNKNOWN, count=UNKNOWN)
        record["reason"] = "its start Z, DRO depth, plan units or doc_mm is unknown"
        return record
    levels, z = [], _grid(printed - depth, step, decimals, True)
    while z > end + _WALL_TOL:
        levels.append(z)
        z = round(z - lattice, decimals)
    record.update(levels=[*levels, end], count=len(levels) + 1)
    return record


def _x_reading(radius, radius_mode):
    """``radius`` as the lathe DRO's X display reads it: itself on a radius display
    (``dro.radius_mode = true``), twice it on a diameter one (``false``); unknown when the
    plan omits the display or states it unknown, never a default display."""
    scale = {True: 1, False: 2}.get(radius_mode) if isinstance(radius_mode, bool) else None
    return scale * radius if scale and number(radius) else UNKNOWN


def _lathe_rows(name, feature, setup, frame, frames, radius_mode):
    rows = []
    diameter = _nominal(feature, "dia")
    if not number(diameter) and number(feature.get("base_radius")):
        diameter = 2 * feature["base_radius"]
    stations = feature.get("z_mm", [])
    if isinstance(stations, list):
        for index, z in enumerate(stations):
            model = model_point([0.0, 0.0, z], frames.get(feature.get("frame", "model")))
            rows.append(
                {
                    "feature": name,
                    "point": f"drawing station {index + 1}",
                    "model": model,
                    "setup": frame_point(model, frame),
                    "dia_nominal": diameter,
                    "x_target_mm": _x_reading(diameter / 2, radius_mode)
                    if number(diameter)
                    else UNKNOWN,
                }
            )
    for op in setup["ops"]:
        if op.get("feature") != name:
            continue
        for field in ("to_z", "z_from", "z_to"):
            z = op.get(field)
            if not number(z):
                continue
            unbound = not frame or frame.get("binding") == UNKNOWN
            model = model_point([0.0, 0.0, UNKNOWN if unbound else z], frame)
            local = frame_point(model, frame)
            row = {
                "feature": name,
                "point": f"op {op['op']} {field}",
                "model": model,
                "setup": local,
                "dia_nominal": diameter,
                "x_target_mm": _x_reading(diameter / 2, radius_mode)
                if number(diameter)
                else UNKNOWN,
            }
            if unbound and local[2] == UNKNOWN:
                row["setup"][2] = z
                row["local_from"] = {"op": op["op"], "field": field, "axis": "z"}
            rows.append(row)
    return rows


def _axis_rows(bundle, setup, name, feature, frame, dro, lathe):
    """(rows, citation, None) locating a feature on setup Z through X0 Y0 at both ends of
    its kernel-measured axial span, or ([], None, why not) when the kernel did not measure
    every face revolved about setup Z through the origin (``turned_profile.spindle_span``).

    On a lathe that axis is the spindle and the rows carry the DRO X target; on any other
    machine they are setup X0 Y0 points, transformed to the model through the setup frame.
    """
    from .turned_profile import spindle_span

    scale = {"mm": 1.0, "in": 25.4}.get(bundle.features.get("units"))
    if scale is None:
        return [], None, "feature units are not mm or in"
    span, cite = spindle_span(bundle, setup, name)
    if span is None:
        return [], None, f"kernel: {cite}"
    diameter = _nominal(feature, "dia")
    radius_mode = dro.get("radius_mode")
    rows = []
    for end, z in zip(("start", "end"), span, strict=True):
        local = [0.0, 0.0, z / scale]
        row = {
            "feature": name,
            "point": f"{'spindle' if lathe else 'setup Z'} axis, kernel span {end}",
            "model": model_point(local, frame),
            "setup": local,
        }
        if lathe:
            row["dia_nominal"] = diameter
            row["x_target_mm"] = (
                _x_reading(diameter / 2, radius_mode) if number(diameter) else UNKNOWN
            )
        rows.append(row)
    return rows, cite, None


def _nose_arc(edges):
    """(lowest, highest) contact-normal angle in degrees, measured from +X (radially out)
    toward +Z, that a right-hand insert's nose arc spans: its major edge (entering angle
    ``kappa`` from the -Z feed) bounds it at ``kappa``, its trailing edge at
    ``kappa + insert - 180``. (None, reason) when the edge facts do not establish it."""
    edges = mapping(edges)
    kappa, insert = edges.get("entering_angle_deg"), edges.get("insert_angle_deg")
    if edges.get("hand") != "right":
        return None, "the nose arc is modelled for a right-hand tool feeding toward the chuck"
    if not (number(kappa) and number(insert)) or kappa <= 0 or insert <= 0:
        return None, "the selected tool's entering or insert angle is unknown"
    if kappa + insert >= 180:
        return None, "the selected tool's entering and insert angles do not form an insert"
    return (kappa + insert - 180, kappa), None


def _dome(name, feature, op, radius_mode, nose=UNKNOWN, edges=None):
    """Axial table of the dome's finished surface and, when the selected insert's nose arc
    spans every row's contact normal, the imaginary-tip readings of a tool touched off on
    an outside diameter (X) and a +Z end face (Z), the lathe tool-touch convention: the
    nose centre sits ``nose`` along the surface normal, so the tip reads ``nose * (n - 1)``
    from the surface point per axis. A normal outside the arc is cut by an edge or flank,
    not the nose, so no nose offset holds there."""
    sphere = feature.get("sphere_radius", UNKNOWN)
    apex, base = op.get("z_from", UNKNOWN), op.get("z_to", UNKNOWN)
    step = mapping(op.get("contour")).get("step_mm", UNKNOWN)
    if not all(number(v) for v in (sphere, apex, base, step)) or sphere <= 0 or step <= 0:
        return None
    sign = 1 if apex > base else -1
    centre = apex - sign * sphere
    arc, arc_reason = _nose_arc(edges)
    if not number(nose) or nose < 0:
        compensation, why = UNKNOWN, "the selected tool's nose radius is unknown"
    elif sign < 0:
        compensation, why = UNKNOWN, "the dome apex faces the chuck, not the +Z touch-off face"
    elif arc is None:
        compensation, why = UNKNOWN, arc_reason
    else:
        compensation, why = nose, None
    reading = functools.partial(_x_reading, radius_mode=radius_mode)
    rows = []
    count = math.ceil(abs(apex - base) / step)
    for i in range(count + 1):
        z = base if i == count else apex - sign * i * step
        squared = sphere * sphere - (z - centre) ** 2
        if squared < -1e-10:
            return None
        radius = math.sqrt(max(0, squared))
        normal_r, normal_z = radius / sphere, (z - centre) / sphere
        rows.append(
            {
                "z_mm": z,
                "radius_mm": radius,
                "diameter_mm": 2 * radius,
                "x_target_mm": reading(radius),
                "setup_xz": [reading(radius), z],
                "normal_deg": math.degrees(math.atan2(normal_z, normal_r)),
            }
        )
    if why is None:
        outside = [r["z_mm"] for r in rows if not arc[0] - 1e-9 <= r["normal_deg"] <= arc[1] + 1e-9]
        if outside:
            compensation = UNKNOWN
            why = (
                f"contact normals at Z {', '.join(f'{z:g}' for z in outside)} lie outside the "
                f"nose arc {arc[0]:g}°..{arc[1]:g}°, so an edge, not the nose, meets them"
            )
    if why is None:
        for row in rows:
            normal = math.radians(row["normal_deg"])
            row["x_tool_mm"] = reading(row["radius_mm"] + nose * (math.cos(normal) - 1))
            row["z_tool_mm"] = row["z_mm"] + nose * (math.sin(normal) - 1)
    contour = {
        "feature": name,
        "op": op["op"],
        "method": "axial_table",
        "rows": rows,
        "sphere_radius_mm": sphere,
        "sphere_centre_z_mm": centre,
        "apex_z_mm": apex,
        "base_z_mm": base,
        "step_mm": step,
        "tool_nose_compensation_mm": compensation,
        "tool_reference": "imaginary tip: X touched on an outside diameter, Z on a +Z end face",
    }
    if why is not None:
        contour["tool_nose_compensation_reason"] = why
    return contour


def _dome_stair(name, feature, op, radius_mode, allowance, scale):
    """The rough stair under a convex dome's finish table, apex toward +Z.

    One facing row per finish-table Z below the apex: from outside the work at that Z, face
    in to the X where the sphere grown by half the diametral ``allowance`` crosses it. The
    imaginary tip of a tool touched off on an outside diameter and a +Z end face reads the
    stair corner exactly, and every corner lies on the grown sphere, so the whole stair
    stays at least ``allowance / 2`` off the finished dome. Rows at or past the base
    radius (the diameter the dome caps) cut nothing and are dropped. Rows are in plan
    units, as the finish table's; the allowance is millimetres (``scale`` mm per unit).
    None when the stair is not established."""
    sphere = feature.get("sphere_radius", UNKNOWN)
    apex, base = op.get("z_from", UNKNOWN), op.get("z_to", UNKNOWN)
    step = mapping(op.get("contour")).get("step_mm", UNKNOWN)
    values = (sphere, apex, base, step, allowance, scale)
    if not all(number(v) for v in values) or min(sphere, step) <= 0 or allowance <= 0:
        return None
    if apex <= base:
        return None  # facing rows come in from +Z: an apex toward the chuck has no stair
    centre = apex - sphere
    grown = sphere + allowance / 2 / scale
    squared = sphere * sphere - (base - centre) ** 2
    if squared < -1e-10:
        return None  # the window runs past the sphere: no dome caps that base
    work = math.sqrt(max(0.0, squared))
    reading = functools.partial(_x_reading, radius_mode=radius_mode)
    rows = []
    count = math.ceil((apex - base) / step)
    for i in range(1, count + 1):
        z = base if i == count else apex - i * step
        radius = math.sqrt(max(0.0, grown * grown - (z - centre) ** 2))
        if radius >= work - 1e-9:
            break
        rows.append(
            {
                "z_mm": z,
                "radius_mm": radius,
                "x_target_mm": reading(radius),
                "setup_xz": [reading(radius), z],
            }
        )
    return {
        "feature": name,
        "op": op["op"],
        "stage": "rough",
        "method": "stair_table",
        "rows": rows,
        "allowance_mm": allowance,
        "sphere_radius_mm": sphere,
        "apex_z_mm": apex,
        "base_z_mm": base,
        "work_radius_mm": work,
        "step_mm": step,
        "tool_reference": "imaginary tip: X touched on an outside diameter, Z on a +Z end face",
    }


def _edge_facts(bundle, op):
    """The selected turning insert's hand and accepted entering/insert angles (degrees)."""
    from ._envelope import measurement_item

    item = measurement_item(bundle, "tools", op.get("tool"))
    angles = {}
    for field in ("entering_angle_deg", "insert_angle_deg"):
        fact = angle_fact(item, field, require_measured=False)
        angles[field] = fact["value"] if fact["verified"] else UNKNOWN
    return {"hand": mapping(item).get("hand", UNKNOWN), **angles}


def _plunges(bundle, op, feature, reading=None):
    """The plunges of a grooving/parting blade over its op's ``z_from``..``z_to`` groove,
    or None when the op is not a blade groove op.

    The DRO reads the blade corner its Z touch-off set (``reading``, from
    :func:`prechips.rules.zero_recipe.blade_readings`): the chuck-side corner after a touch
    on a face toward the free end, the tailstock-side corner after one on a face toward
    the chuck; unknown without one. Plunges start flush with the chuck-side groove wall and
    step evenly, never more than a blade width, until the last plunge is flush with the
    far wall; a blade at least as wide as the groove plunges once. The groove they leave
    (first plunge's chuck-side face to the last one's far face) is checked against the
    feature's declared ``width`` band."""
    from .geometry_common import TURNING_BLADE_KINDS
    from .turned_profile import GROOVE_OPS, nominal_diameter

    tool = resolve(bundle, "tools", op.get("tool")) or {}
    ends = (op.get("z_from"), op.get("z_to"))
    if op.get("do") not in GROOVE_OPS or tool.get("kind") not in TURNING_BLADE_KINDS:
        return None
    if not all(number(z) for z in ends):
        return None
    blade = UNKNOWN if uncertain(tool) else length_mm(tool, "blade_width")
    scale = {"mm": 1.0, "in": 25.4}.get(bundle.features.get("units"))
    # Every *_mm fact here is millimetres: the op's plan-unit ends are scaled.
    low, high = sorted(z * scale for z in ends) if scale else (UNKNOWN, UNKNOWN)
    band = feature.get("width")
    dia = feature.get("dia")
    result = {
        "op": op["op"],
        "feature": op.get("feature", UNKNOWN),
        "blade_width_mm": blade,
        "reading_corner": (reading or {}).get("reference_corner", UNKNOWN),
        "diameter_mm": nominal_diameter(bundle, feature),
        "dia_band_mm": [v * scale for v in dia] if scale and _band(dia) else "not_applicable",
        "width_band_mm": [v * scale for v in band] if scale and _band(band) else "not_applicable",
    }
    if not number(blade) or blade <= 0 or result["reading_corner"] == UNKNOWN or not scale:
        result.update(corner_z_mm=UNKNOWN, groove_z_mm=UNKNOWN, width_mm=UNKNOWN)
        return result
    span = high - low
    count = 1 if span <= blade + 1e-9 else math.ceil((span - blade) / blade - 1e-9) + 1
    step = (span - blade) / (count - 1) if count > 1 else 0.0
    faces = [low + k * step for k in range(count)]
    lift = blade if result["reading_corner"] == "tailstock_side" else 0.0
    width = max(span, blade)
    result.update(
        corner_z_mm=[face + lift for face in faces],
        groove_z_mm=[low, low + width],
        width_mm=width,
    )
    return result


def _blade_target(bundle, setup, op, reading, grid):
    """A grooving/parting blade op's ``to_z`` as the DRO reading of its reference corner,
    or None for any other op (a groove op prints its plunges instead).

    ``to_z`` is the face the op leaves. The blade stands on that face's outward side
    (kernel ``faced_side`` of an already-present run; this never starts the kernel): a
    face toward the free end is formed by its chuck-side corner, one toward the chuck by
    its tailstock-side corner (``forming_corner``). The DRO reads the corner its Z touch
    set (``reading_corner``); when that is the other corner, its reading lies a blade
    width beyond ``to_z``. ``corner_dro_z`` is that reading on the DRO grid, rounded up
    like ``dro_z``; ``formed_z`` is the face that rounded reading leaves, a blade width
    back from it (off the grid when the width is), never below ``to_z``. A ``to_z_band``
    is in face coordinates too: ``corner_dro_band`` is the same band as readings of the
    reading corner, rounded inward onto the grid so every reading in it leaves the face
    inside the band (an unknown end stays unknown). Unknown, with its ``reason``, when the
    corner, the side or the blade width is."""
    from .geometry_common import TURNING_BLADE_KINDS
    from .turned_profile import GROOVE_OPS

    tool = resolve(bundle, "tools", op.get("tool")) or {}
    if tool.get("kind") not in TURNING_BLADE_KINDS or op.get("do") in GROOVE_OPS:
        return None
    if "to_z" not in op:
        return None
    width = UNKNOWN if uncertain(tool) else length_mm(tool, "blade_width")
    kernel = mapping(getattr(bundle, "kernel", None))
    fact = mapping(mapping(kernel.get("ops")).get(f"{setup['id']}:{op['op']}"))
    side = fact.get("faced_side") if kernel.get("status") == "ok" else None
    reading = mapping(reading)
    result = {
        "reading_corner": reading.get("reference_corner", UNKNOWN),
        "forming_corner": {1: "chuck_side", -1: "tailstock_side"}.get(side, UNKNOWN),
        "blade_width_mm": width,
    }
    scale = {"mm": 1.0, "in": 25.4}.get(bundle.features.get("units"))
    reasons = []
    if result["reading_corner"] == UNKNOWN:
        reasons.append(reading.get("reason", "the corner its Z touch set is unknown"))
    if result["forming_corner"] == UNKNOWN:
        reasons.append("no kernel pose puts the blade on one side of the face it leaves")
    if not number(width) or width <= 0:
        reasons.append("the blade width is not a measured length")
    if not number(op["to_z"]) or not scale:
        reasons.append("to_z or the feature units are unknown")
    if reasons:
        result.update(corner_dro_z=UNKNOWN, reason="; ".join(reasons))
        return result
    offset = 0.0
    if result["reading_corner"] != result["forming_corner"]:
        # Formed by the chuck-side corner, the blade spans to_z..to_z + width.
        offset = (width if result["forming_corner"] == "chuck_side" else -width) / scale
    corner = dro_z(op["to_z"] + offset, grid)
    # Rounded to float residue: an on-grid width forms dro_z(to_z) exactly.
    result.update(corner_dro_z=corner, formed_z=round(corner - offset, 9))
    ends = _band_ends(op)
    if ends is not None:
        low, high = ends
        result["corner_dro_band"] = [
            _grid(low + offset, *grid, True) if number(low) else UNKNOWN,
            _grid(high + offset, *grid, False) if number(high) else UNKNOWN,
        ]
    return result


def _band_ends(op):
    """``op``'s ``to_z_band`` as (low, high), an unknown end kept in place; None without
    a two-ended band."""
    band = op.get("to_z_band")
    if not (isinstance(band, list) and len(band) == 2):
        return None
    return tuple(sorted(band)) if all(number(v) for v in band) else tuple(band)


def _allowed_error(op, target):
    """Why ``op``'s blade target forms its face outside the op's own ``to_z_band``, else
    None: rounding a reading through an off-grid blade width can carry the face past a
    band end, so the printed target falls outside the readings printed as allowed."""
    ends, formed = _band_ends(op), target.get("formed_z")
    if ends is None or not number(formed):
        return None
    low, high = ends
    if (number(low) and formed < low - 1e-9) or (number(high) and formed > high + 1e-9):
        return (
            f"op {op['op']} prints Z {target['corner_dro_z']:g} for its "
            f"{target['reading_corner'].replace('_', '-')} corner, which forms its face at "
            f"{formed:g}, outside its allowed {_text_z(low)} to {_text_z(high)}"
        )
    return None


def _text_z(value):
    return f"{value:g}" if number(value) else UNKNOWN


def formed_z(bundle, setup, op):
    """The Z the face ``op`` leaves stands at once the DRO reads its printed target: a
    lathe grooving/parting blade op's ``formed_z`` from the rounded reading of the corner
    its Z touch set (:func:`_blade_target`); else ``dro_z(to_z)`` on ``setup``'s grid.
    Unknown, never its nominal ``to_z``, when the blade's corner, side or width is, when
    whether it leaves a face at ``to_z`` is (:func:`~.tip_endpoints.forms_face`), or when
    the DRO Z it cuts on was set at an unknown place (:func:`reads_unknown`).
    Coordinates records it as the op's ``dro_to_z``."""
    from .zero_recipe import blade, blade_readings, reads_unknown, z_readings

    grid = dro_grid(bundle, setup)
    readings = z_readings(bundle, setup)
    if forms_face(bundle, setup, op) == UNKNOWN or reads_unknown(bundle, setup, op, readings):
        return UNKNOWN
    if blade(bundle, op.get("tool")):
        # Empty off a lathe, where no blade corner reads the DRO.
        reading = blade_readings(bundle, setup, readings).get(str(op.get("op")))
        target = reading and _blade_target(bundle, setup, op, reading, grid)
        if target:
            return target.get("formed_z", UNKNOWN)
    return dro_z(op.get("to_z", UNKNOWN), grid)


def _band(value):
    return isinstance(value, list) and len(value) == 2 and all(number(v) for v in value)


# A printed row's id (:func:`row_id`) is its table's name, ``FRAGMENT_FORMAT`` for a piece
# of a clipped table, then ``ROW_FORMAT``: the kernel names the rows of each piece it clips
# (:func:`checkpoints`) with these same formats.
ROW_FORMAT = {"arc_table": " row {}", "line_table": "[{}]"}
FRAGMENT_FORMAT = " fragment {}"


def _table_name(subject, kind, table):
    name = f"{subject} {table.get('stage')} " + (
        "arc" if kind == "arc_table" else f"line {table.get('side')}"
    )
    if "fragment" in table:
        name += FRAGMENT_FORMAT.format(table["fragment"][0])
    return name


def row_id(subject, kind, table, index):
    """A printed row's id: ``S1:40 rough arc row 3`` (``arc_table``) or ``S1:40 rough line
    +X[0]`` (``line_table``); a piece of a clipped table adds ``fragment k``."""
    return _table_name(subject, kind, table) + ROW_FORMAT[kind].format(index)


def checkpoints(subject, numbers, op):
    """Each printed cutter-centre table of op ``op``'s arc_table output, in cutting order.

    A table is its ``name`` and ``kind`` (:func:`row_id`), its ``rows`` of (row id,
    printed setup XY ``dro_xy``, printed tip Z ``dro_tip_z``, corner overshoot?) in plan
    units, whether the kernel must clip it at its op's stock_removal_bounds (``bounded``),
    the side of its travel its cutter clears from (``cutter_side``) and whether its rows
    are single-axis stair steps (``stepped``: keyed at its ends and miters, not every
    step). What the DRO shows is what the kernel clips and checks.
    """
    result = []
    for kind in ("arc_table", "line_table"):
        for table in numbers.get(kind, []):
            if table.get("op") != op:
                continue
            tip = table.get("dro_tip_z", UNKNOWN)
            if kind == "arc_table":
                rows = table.get("rows", [])
                printed = [row.get("dro_xy", UNKNOWN) for row in rows]
                tips, flags = [row.get("dro_tip_z", tip) for row in rows], []
            else:
                printed, flags = table.get("dro_xy") or [], table.get("overshoot") or []
                tips = [tip] * len(table.get("setup_xy", []))
            rows = [
                (
                    row_id(subject, kind, table, i),
                    printed[i] if i < len(printed) else UNKNOWN,
                    z,
                    i < len(flags) and flags[i] is True,
                )
                for i, z in enumerate(tips)
            ]
            result.append(
                {
                    "name": _table_name(subject, kind, table),
                    "kind": kind,
                    "rows": rows,
                    "bounded": table.get("kernel_clip") is True,
                    "cutter_side": table.get("cutter_side", UNKNOWN),
                    "directed": table.get("cut_order") in _CUT_SENSE,
                    "stepped": "stair_cusp_mm" in table,
                }
            )
    return result


def _clip_facts(bundle, subject):
    """(op ``subject``'s kernel ``checkpoint_clips``, or None, and why its clip is unknown).

    Only the kernel finds where a bounded op's cutter first meets stock outside its
    stock_removal_bounds; without its result the printed path is never cuttable."""
    kernel = getattr(bundle, "kernel", None)
    if not isinstance(kernel, dict):
        return None, "no kernel result has clipped it"
    if kernel.get("status") != "ok":
        return None, f"the kernel is unavailable ({kernel.get('reason', UNKNOWN)})"
    clips = mapping(mapping(mapping(kernel.get("ops")).get(subject)).get("checkpoint_clips"))
    if not clips:
        return None, "the kernel reports no clip of it"
    if clips.get("reason"):
        return None, f"its kernel clip is unknown ({clips['reason']})"
    return clips, None


_LINE_COLUMNS = ("model_xy", "setup_xy", "dro_xy", "overshoot")
# A stepped join's columns: the point ones plus the axis each point is jogged on.
_STEPPED_COLUMNS = (*_LINE_COLUMNS, "jog")


def _line_rows(line):
    """A join line's point columns as one row per point."""
    return [
        {key: line[key][i] for key in _STEPPED_COLUMNS if i < len(line.get(key) or [])}
        for i in range(len(line["setup_xy"]))
    ]


def _between(a, b, t):
    if isinstance(a, list):
        return [_between(u, v, t) for u, v in zip(a, b, strict=True)]
    return a + t * (b - a) if number(a) and number(b) else UNKNOWN


def _clip_row(rows, point, marker):
    """A kernel piece point as a printed row, or None when it names no printed row: row
    ``row`` itself, or the clip point a fraction ``t`` along the printed chord after row
    ``after`` at its exact setup XY ``exact_xy``, printed at its safe-side ``dro_xy``."""
    point = mapping(point)
    clipped = "after" in point
    index = point.get("after" if clipped else "row")
    if not isinstance(index, int) or not 0 <= index < len(rows) - clipped:
        return None
    if not clipped:
        return rows[index]
    a, b, t = rows[index], rows[index + 1], point.get("t")
    exact, printed = point.get("exact_xy"), point.get("dro_xy")
    if not (number(t) and _pair(exact) and _pair(printed)):
        return None
    row = dict(a)
    row.pop("corner", None)
    for key in ("angle_deg", "model_xy"):
        if key in a:
            row[key] = _between(a[key], b[key], t)
    row.update(setup_xy=exact, dro_xy=printed, clipped_at=marker)
    if "jog" in b:  # the clip point lies on the leg that reaches b
        row["jog"] = b["jog"]
    if "overshoot" in a:
        row["overshoot"] = False
    if "x" in a:
        row.update(x=exact[0], y=exact[1])
    return row


def _pair(value):
    return isinstance(value, list) and len(value) == 2 and all(number(v) for v in value)


def _kernel_clip(subject, arcs, lines, clips):
    """(arc pieces, line pieces, debt or None): one stage's printed tables as the kernel
    clipped them (``clips``: the op's ``checkpoint_clips``) at the cutter's first contact
    with stock outside the op's stock_removal_bounds.

    Each piece keeps the printed rows the kernel names and adds its clip points, marked
    ``clipped_at``. A table cut into pieces lists each as ``fragment`` [k, n]; tables
    sharing a kept end are one path. A path left in more than one piece is debt: no
    credited cut links the pieces and none is reconnected. Facts that do not match the
    printed tables, or no piece at all, leave the stage unprinted with a reason.
    """
    paths = {
        entry.get("table"): entry for entry in clips.get("paths", []) if isinstance(entry, dict)
    }
    marker = clips.get("clipped_at", UNKNOWN)
    result = {"arc_table": [], "line_table": []}
    count, ends = 0, []
    tables = [("arc_table", arc) for arc in arcs] + [("line_table", line) for line in lines]
    for kind, table in tables:
        arc = kind == "arc_table"
        rows = table["rows"] if arc else _line_rows(table)
        entry = mapping(paths.get(row_id(subject, kind, table, 0)))
        pieces = entry.get("pieces")
        if entry.get("rows") != len(rows) or not isinstance(pieces, list):
            return [], [], "the kernel's clip does not match its printed table"
        built = [[_clip_row(rows, point, marker) for point in piece] for piece in pieces]
        if any(row is None for piece in built for row in piece):
            return [], [], "the kernel's clip does not match its printed table"
        kept = [mapping(point).get("row") for piece in pieces for point in piece]
        if len(built) == 1 and kept == list(range(len(rows))):
            built = None
        count += 1 if built is None else len(built)
        end = len(rows) - 1
        first = built is None or bool(pieces) and mapping(pieces[0][0]).get("row") == 0
        last = built is None or bool(pieces) and mapping(pieces[-1][-1]).get("row") == end
        ends.append((first, rows[0]["setup_xy"], last, rows[-1]["setup_xy"]))
        if built is None:
            result[kind].append(table)
            continue
        dropped = len(rows) - len({row for row in kept if row is not None})
        for k, piece in enumerate(built, start=1):
            if arc:
                clipped = {**table, "rows": piece, "dropped_rows": dropped}
            else:
                columns = {
                    key: [row.get(key) for row in piece] for key in _STEPPED_COLUMNS if key in table
                }
                clipped = {**table, **columns}
                clipped["overshoot"] = [flag is True for flag in clipped["overshoot"]]
                clipped["clipped_at"] = [row.get("clipped_at") for row in piece]
                clipped["dropped_points"] = dropped
                if not any(clipped["overshoot"]):
                    clipped.pop("overshoot_note", None)
            if len(built) > 1:
                clipped["fragment"] = [k, len(built)]
            result[kind].append(clipped)
    for a, b in itertools.combinations(ends, 2):
        for x, y in ((0, 0), (0, 2), (2, 0), (2, 2)):
            if a[x] and b[y] and _joined(a[x + 1], b[y + 1]):
                count -= 1
    if not result["arc_table"] and not result["line_table"]:
        return (
            [],
            [],
            (
                "no part of its cutter-centre path is clear of stock outside its "
                "stock_removal_bounds"
            ),
        )
    debt = None
    if count > 1:
        debt = (
            f"its first contact with stock outside its stock_removal_bounds splits its "
            f"cutter-centre path into {count} pieces; no credited cut links them"
        )
    return result["arc_table"], result["line_table"], debt


def _joined(a, b):
    return _pair(a) and _pair(b) and math.dist(a, b) <= _JOIN_TOL


def _sequence(tables):
    """Number one op stage's ``tables`` (each in its cutting order) ``sequence`` 0, 1, ...
    as the cutter runs them: a table follows the one whose last point is its first; chains
    keep their listed order. None is numbered while any cutting order is unestablished."""
    if any(table.get("cut_order") not in _CUT_SENSE for table in tables):
        return
    ends = [
        [row["setup_xy"] for row in table["rows"]] if "rows" in table else table["setup_xy"]
        for table in tables
    ]
    after = {}
    for i, a in enumerate(ends):
        for j, b in enumerate(ends):
            if i != j and j not in after.values() and _joined(a[-1], b[0]):
                after[i] = j
                break
    order = []
    for start in [i for i in range(len(tables)) if i not in after.values()] + list(
        range(len(tables))
    ):
        while start is not None and start not in order:
            order.append(start)
            start = after.get(start)
    for position, index in enumerate(order):
        tables[index]["sequence"] = position


def _z_residuals(bundle, setup, grid, features, entries):
    """Each finish op whose DRO depth misses its finished face by more than its feature's
    narrowest numeric tolerance band: a final forming cut (``_cuts``) whose ``to_z`` ends
    on that face (no ``exit_mm`` run-out past it) leaves it at its operation entry's
    ``dro_to_z`` (``entries`` by op): :func:`dro_z` above it, or for a blade the face its
    rounded corner reading forms (``blade`` ``formed_z``)."""
    errors = []
    for op in setup["ops"]:
        to_z = op.get("to_z")
        if "exit_mm" in op or not number(to_z):
            continue
        if not any(cut[2] is op for cut in _cuts(bundle, op.get("feature"))):
            continue
        feature = mapping(features.get(op.get("feature")))
        band = _narrowest_band(feature)
        entry = mapping(entries.get(str(op["op"])))
        face = entry.get("dro_to_z", dro_z(to_z, grid))
        blade = mapping(entry.get("blade"))
        printed = f"Z {face:.{grid[1]}f}"
        if number(blade.get("formed_z")):
            corner = blade["reading_corner"].replace("_", "-")
            printed = (
                f"Z {blade['corner_dro_z']:.{grid[1]}f} for its {corner} corner, forming "
                f"its face at {face:g},"
            )
        residual = face - to_z
        if band is not None and residual > band + _WALL_TOL:
            errors.append(
                f"op {op['op']} prints {printed} for to_z {to_z:g}: "
                f"{residual:.{grid[1] + 1}g} above its finished face, more than the "
                f"{band:g} tolerance band of {op.get('feature')}"
            )
    return errors


def _narrowest_band(feature):
    """The width of ``feature``'s narrowest numeric tolerance band, else None."""
    bands = [
        feature[name][1] - feature[name][0]
        for name in tolerance_requirements(feature)
        if isinstance(feature.get(name), list)
        and len(feature[name]) == 2
        and all(number(v) for v in feature[name])
    ]
    return min(bands) if bands else None


def _grid_residual(op, feature, residual, grid):
    """A finish pass's cutter-centre rows on the DRO grid stand ``residual`` further off its
    wall than authored (rounded on the safe side): an error when that is more than its
    feature's narrowest tolerance band, or when no grid point stands on the safe side."""
    if math.isinf(residual):
        return [f"op {op['op']} finish has a row with no DRO grid point on the safe side"]
    band = _narrowest_band(feature)
    if band is None or residual <= band + _WALL_TOL:
        return []
    return [
        f"op {op['op']} finish rows on the {grid[0]:g} DRO grid leave "
        f"{residual:.{grid[1] + 1}g} on the wall, more than the {band:g} tolerance band of "
        f"{op.get('feature')}"
    ]


def _diagonal(points):
    """Whether any consecutive setup points differ on both axes: a move no single axis cuts."""
    return any(
        _pair(a) and _pair(b) and abs(a[0] - b[0]) > _JOIN_TOL and abs(a[1] - b[1]) > _JOIN_TOL
        for a, b in itertools.pairwise(points)
    )


# The manual-mill arc methods (docs/plan.md "Manual arcs"): rough outside the scribed line
# in single-axis stairs or a chain of drilled holes and file to it (rules/manual_arc.py),
# or finish it as straight chords or on a rotary table. No method moves two axes at once.
ROUGH_METHODS = frozenset({"stairs", "chain_drill"})
FINISH_METHODS = frozenset({"chords", "rotary_table"})
ARC_METHODS = ROUGH_METHODS | FINISH_METHODS
REMOVED_ARC_TABLE = (
    "contour method arc_table moves two handwheels at once, which a manual mill cannot: "
    "rough the arc in stairs or chain_drill and file it to the line, or cut it as chords "
    "or on a rotary_table"
)
DIAGONAL_OUTLINE = (
    "needs diagonal moves: a manual mill moves one handwheel at a time and single-axis "
    "stairs along an outline are not computed"
)
# Plan units a cutter edge or drilled hole may reach past the finished line before it
# counts as cutting into the part.
_INSIDE_TOL = 1e-6
# What makes a centre feature a hole to pin or indicate the rotary table on.
_CENTRE_FORMS = frozenset({"drill", "ream", "bore"})
# How a chain-drilled line opens: the webs break along the straight runs between hole
# centres, so the file meets whatever lies between the line and those runs (_holes).
CHAIN_BREAK_OUT = "chisel the webs out along the hole centres"


def filing_cap(bundle):
    """The shop policy ``numbers.max_filing_stock_mm``: the most stock a rough stair or a
    drilled chain may leave the file; unknown when absent, negative, uncited or not
    explicitly verified (``numbers_verify`` false for it)."""
    cap = mapping(bundle.policy.get("numbers")).get("max_filing_stock_mm", UNKNOWN)
    verify = bundle.policy.get("numbers_verify", False)
    if isinstance(verify, dict):
        verify = verify.get("max_filing_stock_mm", False)
    cited = _citations(mapping(bundle.policy.get("numbers_cite")).get("max_filing_stock_mm"))
    known = number(cap) and cap >= 0 and verify is False and bool(cited)
    return cap if known else UNKNOWN


def _filed(stock, cap, label):
    """(errors, debts) for a rough method leaving up to ``stock`` for the file."""
    if not number(cap):
        return [], [
            f"{label} leaves up to {stock:.3f} for the file and the shop policy sets no "
            "max_filing_stock_mm"
        ]
    if stock > cap + _WALL_TOL:
        return [
            f"{label} leaves up to {stock:.3f} for the file, more than the shop's {cap:g} cap"
        ], []
    return [], []


def _stairs(tables, allowance, cap, label, recut=None):
    """(errors, debts): rough stairs stay outside the finished line and leave at most the
    filing ``cap``: the allowance plus the stairs' measured cusp; a rough a later rough
    ``recut`` cuts again (:func:`_recut_by`) leaves its stock to that op, not the file. A
    stair no single-axis corner can step outside the line is an error; unknown inputs are
    debt."""
    errors, debts = [], []
    for table in tables:
        reason = table.get("stair_reason")
        if reason is not None:
            blocked = reason.startswith(STAIR_BLOCKED.split("{")[0])
            (errors if blocked else debts).append(f"{label}: {reason}")
    if errors or debts:
        return errors, debts
    inside = min(table["line_clear_mm"] for table in tables)
    if inside < -_INSIDE_TOL:
        errors.append(f"{label}: a stair's cutter edge reaches {-inside:.3f} past the line")
    stock = allowance + max(table["stair_cusp_mm"] for table in tables)
    for table in tables:
        table.update(stock_left_mm=stock, **_leaves(cap, recut))
    if recut:
        return errors, debts
    more, debts = _filed(stock, cap, f"{label} stairs")
    return errors + more, debts


def _leaves(cap, recut):
    """Who takes a rough's leftover stock: a later rough (``recut_by``) or the file (cap)."""
    return {"recut_by": recut} if recut else {"stock_cap_mm": cap}


def _holes(arc, walls, drill, allowance, cap, label, scale, recut=None):
    """(errors, debts): a drilled chain keeps every hole's full diameter outside the line,
    a web between neighbours and, once the webs are broken out along the straight runs
    between hole centres, every run outside the line (a convex arc's run dips toward its
    centre) and at most ``cap`` for the file: the most material between the line and a
    run along the arc's radius (a concave arc's run bulges away from the line), never
    less than the allowance plus a drill radius. Geometry and the ``drill`` radius are
    plan units, the allowance and recorded measures mm (``scale`` mm per unit)."""
    holes = [row["dro_xy"] for row in arc["rows"]]
    centre, radius = arc["centre_setup_xy"], arc["wall_radius_mm"]
    known = _pair(centre) and number(radius) and all(_pair(p) for p in holes)
    if not walls or not number(drill) or not known:
        return [], [f"{label}: its hole centres or the finished line are unknown"]
    convex = arc["cutter_centre_radius_mm"] > radius
    errors = []
    clear = [min(wall(p) for wall in walls) - drill for p in holes]
    for k, gap in enumerate(clear, start=1):
        if gap < -_INSIDE_TOL:
            errors.append(f"{label}: hole {k} reaches {-gap * scale:.3f} past the line")
    deepest = 0.0
    for k, (a, b) in enumerate(itertools.pairwise(holes), start=1):
        if math.dist(a, b) <= 2 * drill + _WALL_TOL:
            errors.append(
                f"{label}: holes {k} and {k + 1} are {math.dist(a, b) * scale:.3f} mm apart, "
                f"no web for a {2 * drill * scale:g} mm drill to run against"
            )
        near, far = _to_segment(centre, a, b), max(math.dist(a, centre), math.dist(b, centre))
        least, most = (near - radius, far - radius) if convex else (radius - far, radius - near)
        if least < -_INSIDE_TOL:
            errors.append(
                f"{label}: the break-out between holes {k} and {k + 1} runs "
                f"{-least * scale:.3f} past the line"
            )
        deepest = max(deepest, most)
    stock = max(allowance + drill * scale, deepest * scale)
    arc.update(
        drill_dia_mm=2 * drill * scale,
        pitch_mm=max(math.dist(a, b) for a, b in itertools.pairwise(holes)) * scale,
        hole_clear_mm=min(clear) * scale,
        stock_left_mm=stock,
        break_out=CHAIN_BREAK_OUT,
        **_leaves(cap, recut),
    )
    if recut:
        return errors, []
    more, debts = _filed(stock, cap, f"{label} chain drill")
    return errors + more, debts


def _rotate(point, degrees):
    """``point`` turned ``degrees`` counterclockwise (viewed from above) about X0 Y0."""
    c, s = math.cos(math.radians(degrees)), math.sin(math.radians(degrees))
    return [c * point[0] - s * point[1], s * point[0] + c * point[1]]


def _turn(reading, increases):
    """The counterclockwise work turn (degrees) of a table dial ``reading`` from zero on
    a dial whose readings rise turning ``increases``."""
    return -reading if increases == "clockwise" else reading


def _reading(turn, increases):
    """The dial reading (0 to 360) that turns the work ``turn`` degrees counterclockwise."""
    return _turn(turn, increases) % 360.0


def _band_radius(feature, key):
    """A feature's radial band for ``key`` (a diameter band halved), or None."""
    band = feature.get(key)
    if not _band(band):
        return None
    return sorted(v / 2 for v in band) if key == "dia" else sorted(band)


def _towards(a, b):
    """The XY unit direction from ``a`` to ``b`` (``_unit`` scales one 3D vector)."""
    span = math.dist(a, b)
    return [(b[i] - a[i]) / span for i in range(2)]


def _chords(arc, band, offset, grid, table, label, scale):
    """(errors, debts): cut ``arc`` (rows: its chord vertices) as straight chords.

    The chord ends sit on the edge radius that centres each chord's sagitta in the
    feature's radial ``band``; a sagitta wider than the band is an error, as is a full
    circle in fewer than three chords. Each chord is cut along one table axis: as it
    lies, else with the work indexed square to X on the setup's rotary ``table`` (the
    dial rounded to its resolution; a table flagged to verify is a debt); with no table a
    slanted chord is an error. The fixed axis is printed on the DRO grid on the scrap
    side; the fed axis runs to the cutter-centre corner, past it on a convex arc (the
    run-out is scrap) and short of it on a concave one. The proof rebuilds every chord
    face from the printed cuts and holds its nearest and farthest points inside the band.
    Rows become the printed cutter-centre corners in the unindexed setup frame. The band,
    cutter-centre ``offset`` and rows are plan units; the recorded lengths are mm
    (``scale`` mm per unit)."""
    centre, rows = arc["centre_setup_xy"], arc["rows"]
    if band is None or not _pair(centre) or not all(_pair(row["setup_xy"]) for row in rows):
        return [], [f"{label}: its arc centre, chord ends or radial band are unknown"]
    lo, hi = band
    step, decimals = grid
    convex = arc["cutter_centre_radius_mm"] > arc["wall_radius_mm"]
    count = len(rows) - 1
    closed = arc["full_circle"]
    if closed and count < 3:
        return [f"{label}: {count} chords cannot cut a full circle; it takes at least 3"], []
    thetas = [math.atan2(r["setup_xy"][1] - centre[1], r["setup_xy"][0] - centre[0]) for r in rows]
    delta = (thetas[1] - thetas[0] + math.pi) % math.tau - math.pi
    half = math.cos(abs(delta) / 2)
    edge = (lo + hi) / (1 + half)
    sagitta = edge * (1 - half)
    arc.update(
        edge_radius_mm=edge * scale,
        band_mm=[lo * scale, hi * scale],
        sagitta_mm=sagitta * scale,
        indexed=bool(table),
    )
    if sagitta > hi - lo + _WALL_TOL:
        return [
            f"{label}: {count} chords leave a {sagitta * scale:.3f} mm sagitta, more than the "
            f"{(hi - lo) * scale:g} mm radial band"
        ], []
    vertices = [
        [centre[i] + edge * (math.cos, math.sin)[i](thetas[0] + k * delta) for i in range(2)]
        for k in range(count + 1)
    ]
    normals = []
    for a, b in itertools.pairwise(vertices):
        mid = [(a[i] + b[i]) / 2 for i in range(2)]
        normals.append(_towards(centre, mid) if convex else _towards(mid, centre))
    cuts = [
        [[v[i] + offset * n[i] for i in range(2)] for v in (a, b)]
        for a, b, n in zip(vertices, vertices[1:], normals, strict=False)
    ]

    def corners(lines, ends):
        """Where neighbouring ``lines`` meet; an open arc's ends at ``ends`` (k -> point)."""
        points = []
        for k in range(count + 1):
            if 0 < k < count or closed:
                before, after = lines[(k - 1) % count], lines[k % count]
                points.append(_line_join(before[0], _towards(*before), after[0], _towards(*after)))
            else:
                points.append(ends(k))
        return points

    designed = corners(cuts, lambda k: cuts[0][0] if k == 0 else cuts[-1][1])
    if any(point is None for point in designed):
        return [f"{label}: two neighbouring chords run parallel"], []
    errors, debts, chords, actual = [], [], [], []
    for k in range(count):
        p, q = designed[k], designed[k + 1]
        angle = math.degrees(math.atan2(q[1] - p[1], q[0] - p[0]))
        square = (angle + 90.0) % 180.0 - 90.0  # the chord's slant from X, -90 to 90
        along = "X" if abs(square) < 1e-9 else "Y" if abs(abs(square) - 90.0) < 1e-9 else None
        index, turn = None, 0.0
        if along is None and table is None:
            errors.append(
                f"{label}: chord {k + 1} runs {square:.1f}° from X: a manual mill feeds one "
                "handwheel at a time, so index each chord square to X on a rotary table"
            )
            continue
        if along is None:
            resolution, increases = table["resolution_deg"], table["dial_increases"]
            if table["uncertain"]:
                return [], [f"{label}: the rotary table {table['id']} is flagged to verify"]
            if not number(resolution) or increases not in ("clockwise", "counterclockwise"):
                return [], [f"{label}: the rotary table's dial resolution or direction is unknown"]
            index = round(_reading(-square, increases) / resolution) * resolution % 360.0
            turn, along = _turn(index, increases), "X"
        fixed = 1 if along == "X" else 0  # the locked axis; the other is fed
        p, q, n = _rotate(p, turn), _rotate(q, turn), _rotate(normals[k], turn)
        scrap = 1 if n[fixed] > 0 else -1
        level = _grid((max if scrap > 0 else min)(p[fixed], q[fixed]), step, decimals, scrap > 0)
        ends = [
            _grid(a[1 - fixed], step, decimals, (a[1 - fixed] > b[1 - fixed]) == convex)
            for a, b in ((p, q), (q, p))
        ]
        chords.append(
            {
                "from": k,
                "to": k + 1,
                "angle_deg": angle,
                "length_mm": math.dist(vertices[k], vertices[k + 1]) * scale,
                "sagitta_mm": sagitta * scale,
                "cut": {
                    "index_deg": index,
                    "along": along,
                    "at": level,
                    "from": ends[0],
                    "to": ends[1],
                },
            }
        )
        line, face = [], []
        for value in ends:
            point = [0.0, 0.0]
            point[fixed], point[1 - fixed] = level, value
            line.append(_rotate(point, -turn))
            point = list(point)
            point[fixed] = level - scrap * offset
            face.append(_rotate(point, -turn))
        actual.append((line, face))
    if errors:
        return errors, debts

    def radial(lines, k):
        theta = thetas[k]
        line = lines[0 if k == 0 else -1]
        return _line_join(line[0], _towards(*line), centre, [math.cos(theta), math.sin(theta)])

    paths = corners(
        [a for a, _ in actual], lambda k: actual[0 if k == 0 else -1][0][0 if k == 0 else 1]
    )
    faces = corners([f for _, f in actual], lambda k: radial([f for _, f in actual], k))
    if any(point is None for point in (*paths, *faces)):
        return [f"{label}: two neighbouring chords run parallel"], []
    for k, chord in enumerate(chords):
        a, b = faces[k], faces[k + 1]
        reach = [_to_segment(centre, a, b), max(math.dist(a, centre), math.dist(b, centre))]
        chord["face_radius_mm"] = [v * scale for v in reach]
        if reach[0] < lo - _WALL_TOL or reach[1] > hi + _WALL_TOL:
            errors.append(
                f"{label}: chord {k + 1}'s face runs R{reach[0] * scale:.3f} to "
                f"R{reach[1] * scale:.3f} mm, outside its R{lo * scale:g} to R{hi * scale:g} mm "
                "band"
            )
    for row, point in zip(rows, paths, strict=True):
        printed = [round(v, decimals) for v in point]
        row.update(setup_xy=point, x=point[0], y=point[1], dro_xy=printed, model_xy=[UNKNOWN] * 2)
    arc["chords"] = chords
    return errors, debts


def rotary_table(bundle, setup):
    """The setup's rotary table (inventory fixture ``kind = "rotary_table"`` named by
    ``hold.fixture``): ``id``, ``name``, ``resolution_deg`` (vernier, else graduation),
    ``dial_increases``, ``max_work_mm``, its centre ``bore_dia_mm`` and whether it is
    flagged to verify (``uncertain``); None when it holds none."""
    reference = mapping(setup.get("hold")).get("fixture")
    fixture = resolve(bundle, "fixtures", reference) if isinstance(reference, str) else None
    if not isinstance(fixture, dict) or fixture.get("kind") != "rotary_table":
        return None
    resolution = fixture.get("vernier_deg", fixture.get("graduation_deg", UNKNOWN))
    return {
        "id": reference,
        "name": fixture.get("name", reference),
        "resolution_deg": resolution if number(resolution) and resolution > 0 else UNKNOWN,
        "dial_increases": fixture.get("dial_increases", UNKNOWN),
        "max_work_mm": length_mm(fixture, "max_work"),
        "bore_dia_mm": length_mm(fixture, "bore_dia"),
        "uncertain": uncertain(fixture),
    }


def _made_before(bundle, op, name):
    """Whether a drill, ream or bore op forms feature ``name`` before ``op`` in plan order."""
    for setup in bundle.plan["setups"]:
        for other in setup["ops"]:
            if other is op:
                return False
            if other.get("feature") == name and other.get("do") in _CENTRE_FORMS:
                return True
    return False


def arc_layout(bundle, setup, name):
    """The line a layout scribes for arc feature ``name``, in ``setup``'s frame, or None
    when it is no arc or its geometry is unknown: ``centre_setup_xy``, ``radius_mm``
    (nominal), ``convex`` (the part inside the circle), ``full_circle``, ``ends_setup_xy``
    (None for a full circle) and ``centre_on``, the hole whose axis is the arc centre."""
    features = bundle.feature_definitions
    feature = mapping(features.get(name))
    frames = mapping(bundle.features.get("frames"))
    frame = setup_frame(bundle, setup)
    grid = dro_grid(bundle, setup)
    probe = {"op": UNKNOWN, "contour": {"step_deg": 360.0}}
    found = []
    for offset in (0.0, 1.0):  # the line itself, then which side a cutter clears it
        arcs, _, _ = _arc(
            name, feature, probe, offset, frame, frames, features, None, {}, grid, "rotary_table"
        )
        if not arcs or not all(number(v) for v in arcs[0]["centre_setup_xy"]):
            return None
        found.append(arcs[0])
    line, side = found
    centre = line["centre_setup_xy"]
    centre_on = None
    for other, item in features.items():
        locator, locator_frame, _ = located_by(features, other, mapping(item))
        at = locator.get("at")
        placed = isinstance(at, list) and len(at) == 3 and all(number(v) for v in at)
        if mapping(item).get("kind") != "hole" or not placed:
            continue
        axis = frame_point(model_point(at, frames.get(locator_frame)), frame)[:2]
        if _pair(axis) and math.dist(axis, centre) <= _JOIN_TOL:
            centre_on = other
            break
    full = line["full_circle"]
    return {
        "centre_setup_xy": centre,
        "radius_mm": line["wall_radius_mm"],
        "convex": side["cutter_centre_radius_mm"] > side["wall_radius_mm"],
        "full_circle": full,
        "ends_setup_xy": None
        if full
        else [line["rows"][0]["setup_xy"], line["rows"][-1]["setup_xy"]],
        "centre_on": centre_on,
    }


def _swing(bundle, setup):
    """The farthest setup-entry stock corner (mm) from the setup's X0 Y0, from the
    kernel's ``stock_bbox_mm``; None without one."""
    kernel = getattr(bundle, "kernel", None)
    if not isinstance(kernel, dict) or kernel.get("status") != "ok":
        return None
    box = mapping(mapping(kernel.get("setups")).get(setup["id"])).get("stock_bbox_mm")
    if not (isinstance(box, list) and len(box) == 6 and all(number(v) for v in box)):
        return None
    return max(math.hypot(x, y) for x in (box[0], box[3]) for y in (box[1], box[4]))


def _rotary(bundle, setup, op, arc, table, band, features, frame, frames, label, scale):
    """(errors, debts): the rotary-table recipe for ``arc`` (its rows the cutter-centre
    arc in cutting order), stamped as ``rotary``.

    The arc centre is the table axis at setup X0 Y0, located by a pin through, or by
    indicating, ``contour.centre_feature``: a hole on that axis an earlier drill, ream or
    bore made. A pin sized to the hole's smallest diameter must enter the table's known
    centre bore. The spindle is locked at X = the cutter-centre radius on the DRO grid
    (off the line), Y0, and that printed offset's cut radius, widened by a pin's centre
    play (half each bore's clearance over the pin), must lie inside the feature's radial
    ``band`` (plan units; a rough stage's moved off the line by its allowance) however the
    centre is found. The table turns the work against the cutter's path from the start
    reading to the stop reading, both rounded inward to the dial's resolution: an arc
    shorter than that leaves no reading inside it, an error. A table flagged to verify is
    a debt, and the setup-entry stock must swing inside the table's ``max_work``.
    Geometry is plan units, ``scale`` mm per unit."""
    if table is None:
        return [f"{label}: rotary_table needs the work held on a rotary table (hold.fixture)"], []
    contour = mapping(op.get("contour"))
    errors, debts = [], []
    if table["uncertain"]:
        debts.append(f"{label}: the rotary table {table['id']} is flagged to verify")
    centre = arc["centre_setup_xy"]
    if not _pair(centre):
        return [], [f"{label}: its arc centre is unknown"]
    if math.hypot(*centre) > _JOIN_TOL:
        errors.append(
            f"{label}: the arc centre sits at X{centre[0]:g} Y{centre[1]:g}, off the table "
            "axis at setup X0 Y0"
        )
    by, name = contour.get("centre_by", UNKNOWN), contour.get("centre_feature", UNKNOWN)
    if by not in ("pin", "indicate"):
        debts.append(f"{label}: contour.centre_by is neither pin nor indicate")
    hub = mapping(features.get(name)) if isinstance(name, str) else {}
    pin, seat, play = UNKNOWN, table["bore_dia_mm"], UNKNOWN
    convex = arc["cutter_centre_radius_mm"] > arc["wall_radius_mm"]
    if not hub:
        debts.append(f"{label}: contour.centre_feature names no feature")
    else:
        locator, locator_frame, _ = located_by(features, name, hub)
        at = locator.get("at")
        placed = isinstance(at, list) and len(at) == 3 and all(number(v) for v in at)
        axis = (
            frame_point(model_point(at, frames.get(locator_frame)), frame)[:2] if placed else None
        )
        if not _pair(axis):
            debts.append(f"{label}: {name}'s axis is unknown")
        elif math.dist(axis, centre) > _JOIN_TOL:
            errors.append(f"{label}: {name}'s axis is not the arc centre")
        if not _made_before(bundle, op, name):
            errors.append(f"{label}: no earlier drill, ream or bore makes {name} to centre on")
        size = hub.get("dia")
        hole = sorted(size) if _band(size) else [size, size] if number(size) else None
        hole = [v * scale for v in hole] if hole else None
        pin = hole[0] if hole else UNKNOWN
        if by == "pin" and hole is None:
            debts.append(f"{label}: {name}'s diameter is unknown, so no centre pin is sized")
        elif by == "pin" and not number(seat):
            debts.append(f"{label}: the rotary table's centre bore is unknown, so no pin fits it")
        elif by == "pin" and pin > seat + _WALL_TOL:
            errors.append(
                f"{label}: the Ø{pin:g} mm centre pin does not enter the table's Ø{seat:g} mm "
                "centre bore"
            )
        elif by == "pin":
            play = (hole[1] - pin) / 2 + (seat - pin) / 2  # the arc centre's worst shift
    resolution, increases = table["resolution_deg"], table["dial_increases"]
    if not number(resolution) or increases not in ("clockwise", "counterclockwise"):
        debts.append(f"{label}: the rotary table's dial resolution or direction is unknown")
    points = [row["setup_xy"] for row in arc["rows"]]
    if arc["cut_order"] == UNKNOWN or len(points) < 2 or not all(_pair(p) for p in points):
        debts.append(f"{label}: its cutting order or cutter path is unknown")
    reach, capacity = _swing(bundle, setup), table["max_work_mm"]
    if reach is None or not number(capacity):
        debts.append(f"{label}: the stock's swing or the table's max_work is unknown")
    elif 2 * reach > capacity + _WALL_TOL:
        errors.append(
            f"{label}: the stock swings {2 * reach:.1f} mm across, more than the table's "
            f"{capacity:g} mm"
        )
    step, decimals = dro_grid(bundle, setup)
    offset = _grid(arc["cutter_centre_radius_mm"], step, decimals, convex)  # off the line
    cutter = arc["cutter_radius_mm"] / scale if number(arc["cutter_radius_mm"]) else UNKNOWN
    cut = (offset - cutter if convex else offset + cutter) if number(cutter) else UNKNOWN
    # The printed offset, not the exact one, sets the cut, however the centre is found: a
    # rough stage's band is the drawing band moved off the line by its allowance, and only
    # a pin's play (an unknown one leaves its own debt) widens the cut about the centre.
    allowance = arc.get("allowance_mm", 0.0)
    shift = (allowance if convex else -allowance) / scale if number(allowance) else UNKNOWN
    widen = play / scale if number(play) else 0.0
    if not number(cut) or not number(shift):
        debts.append(f"{label}: its cutter radius or allowance is unknown, so no cut is proven")
    elif band is None:
        debts.append(f"{label}: its radial band is unknown, so the cut radius is unproven")
    else:
        low, high = cut - widen, cut + widen
        lo, hi = band[0] + shift, band[1] + shift
        if low < lo - _WALL_TOL or high > hi + _WALL_TOL:
            reach = f"R{low * scale:.3f}" + (f" to R{high * scale:.3f}" if widen else "")
            why = (
                f"a Ø{pin:g} mm pin in {name} and the table's Ø{seat:g} mm bore lets the centre "
                f"shift {play:.3f} mm, so "
                if widen
                else ""
            )
            errors.append(
                f"{label}: {why}the table offset X{offset:.{decimals}f} cuts {reach} mm, "
                f"outside the R{lo * scale:g} to R{hi * scale:g} mm band"
            )
    record = {
        "table": table["id"],
        "table_name": table["name"],
        "centre_by": by,
        "centre_feature": name,
        "pin_dia_mm": pin if by == "pin" else None,
        "table_bore_dia_mm": seat if by == "pin" else None,
        "centre_play_mm": play if by == "pin" else None,
        "convex": convex,
        "radius_mm": arc["wall_radius_mm"] * scale,
        "cut_radius_mm": cut * scale if number(cut) else UNKNOWN,
        "cutter_radius_mm": arc["cutter_radius_mm"],
        "offset_axis": "X",
        "offset_x": offset,
        "offset_mm": offset * scale,
        "resolution_deg": resolution,
        "dial_increases": increases,
        "work_radius_mm": reach if reach is not None else UNKNOWN,
        "max_work_radius_mm": capacity / 2 if number(capacity) else UNKNOWN,
        "start_deg": UNKNOWN,
        "stop_deg": UNKNOWN,
        "sweep_deg": UNKNOWN,
        "rotation": UNKNOWN,
    }
    arc["rotary"] = record
    if debts:
        return errors, debts
    thetas = [math.degrees(math.atan2(p[1], p[0])) for p in points]
    travel = sum((b - a + 180.0) % 360.0 - 180.0 for a, b in itertools.pairwise(thetas))
    rotation = "clockwise" if travel > 0 else "counterclockwise"  # the work turns back
    start = _reading(-thetas[0], increases) / resolution
    if arc["full_circle"]:
        start = stop = round(start) * resolution % 360.0
        sweep = 360.0
    else:
        # The reading runs on from the start by the work's turn (-travel), unwrapped: only
        # rounding both ends inward (start forward, stop back) on that interval keeps the
        # cut inside the arc; ends that cross leave no reading inside it.
        stop = start + _turn(-travel, increases) / resolution
        sign = 1 if stop > start else -1
        start = sign * math.ceil(sign * start - 1e-9)
        stop = sign * math.floor(sign * stop + 1e-9)
        if sign * (stop - start) <= 0:
            errors.append(
                f"{label}: the arc turns {abs(travel):.3f}°, too short for the dial's "
                f"{resolution:g}° readings to start and stop inside it"
            )
            return errors, []
        sweep = sign * (stop - start) * resolution
        start, stop = start * resolution % 360.0, stop * resolution % 360.0
    record.update(start_deg=start, stop_deg=stop, sweep_deg=sweep, rotation=rotation)
    return errors, []


# The contour input each manual-arc method spaces its rows by.
_NEEDS = {
    "stairs": "cusp_mm",
    "chain_drill": "pitch_mm",
    "chords": "count",
    "rotary_table": "step_deg",
}


def _recut_by(bundle, op):
    """The last later manual-arc op ("S4 op 27") that cuts all of ``op``'s claimed faces
    again before any file reaches them, else None: then ``op``'s leftover stock is not the
    file's. The last such op hands the faces to the file, so it names the leftover's taker:
    an op between them may claim the faces from the other side (a half-depth rough from
    the opposite face), and the face claim does not compare depth. A claim without
    ``faces`` is the whole feature."""
    name, faces = op.get("feature"), op.get("faces")
    passed, last = False, None
    for setup in bundle.plan["setups"]:
        for other in setup["ops"]:
            if other is op:
                passed = True
                continue
            if not passed or other.get("feature") != name:
                continue
            if other.get("do") in HAND_FINISH:
                return last
            later = other.get("faces")
            covers = later is None or (faces is not None and set(faces) <= set(later))
            if mapping(other.get("contour")).get("method") in ARC_METHODS and covers:
                last = f"{setup['id']} op {other.get('op', UNKNOWN)}"
    return last


def _manual(bundle, setup, op, stage, allowance, arcs, lines, walls, label, scale):
    """(errors, debts) of one arc stage cut by its manual method (:data:`ARC_METHODS`); the
    tables' geometry is plan units, ``scale`` mm per unit."""
    arc = arcs[0]
    method = arc["method"]
    if method in ROUGH_METHODS and stage != "rough":
        return [f"{label}: {method} only roughs outside the line; file_to_line finishes it"], []
    if method != "stairs" and lines:
        return [], [f"{label}: {method} along the arc's straight joins is not computed"]
    if method in FINISH_METHODS and "stock_removal_bounds" in op:
        return [], [f"{label}: {method} cuts its whole arc; stock_removal_bounds cannot clip it"]
    cap = filing_cap(bundle)
    recut = _recut_by(bundle, op)
    if method == "stairs":
        return _stairs([*arcs, *lines], allowance, cap, label, recut)
    if method == "chain_drill":
        drill = arc["cutter_radius_mm"]
        drill = drill / scale if number(drill) else UNKNOWN
        return _holes(arc, walls, drill, allowance, cap, label, scale, recut)
    features, frames = bundle.feature_definitions, mapping(bundle.features.get("frames"))
    feature = mapping(features.get(arc["feature"]))
    table = rotary_table(bundle, setup)
    key = "radius" if "bottom_radius" not in feature else "bottom_radius"
    key = "dia" if arc["full_circle"] else key
    band = _band_radius(feature, key)
    if method == "chords":
        offset = arc["offset_mm"] / scale if number(arc["offset_mm"]) else UNKNOWN
        return _chords(arc, band, offset, dro_grid(bundle, setup), table, label, scale)
    frame = setup_frame(bundle, setup)
    return _rotary(bundle, setup, op, arc, table, band, features, frame, frames, label, scale)


def evaluate(bundle, *, pre_kernel=False):
    """Coordinates findings, one per setup.

    A bounded op's (``stock_removal_bounds``) printed path is clipped only by the kernel,
    at the cutter's first contact with stock outside that box (:func:`_kernel_clip`). The
    kernel request (``pre_kernel``, :func:`prechips.kernel.build_job`) carries its whole
    printed tables marked ``kernel_clip``; the rule pass prints the kernel's clip of them,
    and without one leaves them unprinted and unknown, never cuttable unclipped.
    """
    result = []
    features = bundle.feature_definitions
    # Feature source frames are manifest-only; setups resolve exported or plan-owned frames.
    frames = mapping(bundle.features.get("frames"))
    dro = mapping(bundle.plan.get("dro"))
    units = bundle.features.get("units")
    for setup in bundle.plan["setups"]:
        bench = manual_bench(bundle, setup)
        if bench is not None:
            result.append(
                not_applicable(
                    "coordinates", setup, bench, "coordinates", "DRO target or cutter-centre table"
                )
            )
            continue
        frame = setup_frame(bundle, setup)
        machine = resolve(bundle, "machines", setup.get("machine")) or {}
        lathe = machine.get("kind") == "lathe"
        unordered = set()  # why a contour table's cutting order is unknown
        clip_debts = []  # why a clipped contour path is split, empty or unclipped
        unproven = []  # why a contour's diagonal moves are not proven cuttable
        arc_errors = []  # manual-arc plans that cut into the part or cannot be cut
        leave_errors = []  # rough stages whose leave would cut into the finished part
        arc_debts = []  # manual-arc plans whose inputs are unknown
        numbers = {
            "frame": setup.get("frame", UNKNOWN),
            "binding": frame.get("binding", "nominal"),
            "rows": [],
            "profiles": [],
            "arc_table": [],
            "line_table": [],
            "contours": [],
            "entry_surfaces": [],
        }
        numbers["operations"] = [
            {
                key: value
                for key, value in op.items()
                if key
                in {
                    "op",
                    "do",
                    "feature",
                    "tool",
                    "direction",
                    "to_z",
                    "z_from",
                    "z_to",
                    "rough_allowance_mm",
                    "stock_to_leave_mm",
                }
            }
            for op in setup["ops"]
        ]
        grid = dro_grid(bundle, setup)
        numbers["dro_grid"] = {"step": grid[0], "decimals": grid[1]}
        declared = mapping(mapping(setup.get("stock_state")).get("entry_z"))
        # The stock top before op ``done`` as the setup prints it: a path starts or lifts
        # from that surface.
        top = functools.partial(operative_z, bundle, setup, face="top")
        states, cleared, plan_debts = stock_states(bundle, setup), [], []
        # The corner each blade op's DRO Z reads (the Z touch in effect when it cuts).
        readings = {}
        if lathe:
            from .zero_recipe import blade_readings

            readings = blade_readings(bundle, setup)
        blade_unknown = False
        allowed_errors = []  # blade targets forming their face outside the op's to_z_band
        for done, (entry, (op, before, _)) in enumerate(
            zip(numbers["operations"], states, strict=True)
        ):
            if "to_z" in entry:
                # The depth the DRO shows: rounded up, never deeper than authored.
                entry["dro_to_z"] = dro_z(entry["to_z"], grid)
            target = _blade_target(bundle, setup, op, readings.get(str(op.get("op"))), grid)
            if lathe and target is not None:
                entry["blade"] = target
                blade_unknown |= target["corner_dro_z"] == UNKNOWN
                if "formed_z" in target:
                    # The face the printed corner reading leaves (:func:`formed_z`).
                    entry["dro_to_z"] = target["formed_z"]
                    error = _allowed_error(op, target)
                    if error:
                        allowed_errors.append(error)
            levels = None
            if not lathe:
                printed = top(before["top_z"], done=done)
                levels = _z_levels(op, before, declared, cleared, features, grid, units, printed)
            if levels is not None:
                entry["z_levels"] = levels
                if levels["levels"] == UNKNOWN:
                    plan_debts.append(f"op {op['op']} axial levels: {levels['reason']}")
            if op.get("do") in RASTER_OPS and number(op.get("to_z")) and _xy_box(op):
                cleared.append((op.get("feature"), _xy_box(op), op["to_z"]))
        entries = {str(entry.get("op")): entry for entry in numbers["operations"]}
        residuals = _z_residuals(bundle, setup, grid, features, entries)
        unknown = not frame or frame.get("binding") == UNKNOWN or blade_unknown
        if lathe:
            from .geometry_common import _AXIAL_LATHE_ACTIONS

            numbers["x_display"] = (
                "radius"
                if dro.get("radius_mode") is True
                else "diameter"
                if dro.get("radius_mode") is False
                else UNKNOWN
            )
            # A turning tool's printed X/Z targets need its nose radius; a tailstock tool on
            # the spindle axis (centre drill, drill, reamer, tap) has none to compensate.
            unknown |= dro.get("controller", UNKNOWN) == UNKNOWN or any(
                not number(length_mm(resolve(bundle, "tools", op.get("tool")) or {}, "nose_radius"))
                for op in setup["ops"]
                if "tool" in op and op.get("do") not in _AXIAL_LATHE_ACTIONS
            )
            if numbers["x_display"] == UNKNOWN:
                # Every X the setup prints reads radius or diameter; a default is half or
                # twice the cut on the other display.
                plan_debts.append("dro.radius_mode not stated: X reads radius or diameter")
        plunge_errors = []  # blade plunges leaving a groove outside its drawing width
        grid_errors = []  # finish rows whose safe-side DRO grid point leaves more than the band
        for op in setup["ops"]:
            # An inspect op may name a list of features; a groove op names one.
            name = op.get("feature")
            plunges = _plunges(
                bundle,
                op,
                mapping(features.get(name) if isinstance(name, str) else None),
                readings.get(str(op.get("op"))),
            )
            if plunges is None:
                continue
            numbers.setdefault("plunges", []).append(plunges)
            width, band = plunges["width_mm"], plunges["width_band_mm"]
            if not number(width):
                unknown = True
            elif _band(band) and not min(band) - 1e-9 <= width <= max(band) + 1e-9:
                plunge_errors.append(
                    f"op {op['op']} plunges leave a groove {width:g} wide, outside the "
                    f"drawing width {min(band):g} to {max(band):g}"
                )
        names = list(_op_names(setup))
        located_names = set(_located_names(setup, features))
        revolved_names = set(revolved_located(setup, features))
        axis_cites, locator_cites, aim_cites = [], [], []
        band_errors = []  # aims and located DRO targets outside their printed band
        planned = []  # (feature, its mill rows, whether they stand at its locator's ``at``)
        for name in names:
            feature = mapping(features.get(name))
            locator, locator_frame, locator_name = located_by(features, name, feature)
            at = locator.get("at")
            located = name in located_names
            vector = isinstance(at, list) and len(at) == 3
            placed = vector and all(number(value) for value in at)
            why = None
            if located and not placed and (lathe or name in revolved_names):
                # A feature the kernel measured revolved about setup Z through X0 Y0 is
                # located on that axis (a lathe's spindle); off-axis or unmeasured ones still
                # need ``at``. Off a lathe an explicit ``at`` (even unknown) or a parent wins.
                rows, cite, why = _axis_rows(bundle, setup, name, feature, frame, dro, lathe)
                if rows:
                    numbers["rows"].extend(rows)
                    axis_cites.append(cite)
                    located = vector = False
                    if not lathe:
                        # The kernel's span ends take the same aim, grid and band check.
                        points, aim, _ = _aimed(bundle, name, [r["model"] for r in rows])
                        aims = {} if aim is None else {"aim": aim}
                        errors, debt = _planned_rows(rows, points, aims, frame, grid)
                        band_errors.extend(errors)
                        unknown |= debt
                        planned.append((name, rows, False))
            unknown |= located and not placed
            if located or vector:
                model = model_point(at, frames.get(locator_frame))
                local = frame_point(model, frame)
                row = {"feature": name, "model": model, "setup": local}
                if not lathe and isinstance(local, list):
                    # The tool-axis X/Y a hole op dials: the nearest DRO grid point.
                    row["dro_xy"] = [dro_nearest(v, grid) for v in local[:2]]
                if locator_name != name:
                    row["located_by"] = locator_name
                    locator_cites.extend(
                        [
                            f"features.features.{locator_name}.at",
                            *_citations(locator.get("cite"), "at"),
                        ]
                    )
                if why is not None and not lathe:
                    # Lathe rows keep their established shape; elsewhere name the debt.
                    row["reason"] = why
                if not lathe and UNKNOWN not in local:
                    point, aims, _ = planned_point(bundle, name)
                    errors, debt = _planned_rows([row], [point], aims, frame, grid)
                    band_errors.extend(errors)
                    unknown |= debt
                    planned.append((name, [row], True))
                numbers["rows"].append(row)
                unknown |= UNKNOWN in local
            if lathe:
                numbers["rows"].extend(
                    _lathe_rows(name, feature, setup, frame, frames, dro.get("radius_mode"))
                )
        # Each band is measured where its features stand: one this setup machines (a centre
        # op dials its printed DRO target) at that target; one it only inspects, or works
        # through a child, or machines in another setup, at its planned model point.
        machined = _centred(setup)
        targets = {
            name: model_point(rows[0]["dro"], frame)
            for name, rows, at in planned
            if at and name in machined and "dro" in rows[0]
        }
        grid_debt = dro_grid_debt(bundle, setup)
        for name, rows, _ in planned:
            errors, debt = _band_rows(
                bundle, name, rows, frame, targets, grid_debt, name in machined
            )
            band_errors.extend(errors)
            unknown |= debt
            for key in ("aim", "refused_aim"):
                if key in rows[0]:
                    aim_cites.append(f"plan.aims.{rows[0][key]['feature']}")
        for done, (op, before, after) in enumerate(stock_states(bundle, setup)):
            numbers["entry_surfaces"].append({"op": op["op"], **after["entry_z"]})
            contour = mapping(op.get("contour"))
            unknown |= op.get("contour") == UNKNOWN
            leave, refusal = rough_leave(op)
            if refusal:
                # However the op is cut (contour, pocket, turn, joint), a rough leave
                # inside the finished part spoils it, and no stage of it is proven.
                leave_errors.append(f"op {op['op']}: {refusal}")
            if not contour:
                continue
            name = op.get("feature")
            feature = mapping(features.get(name))
            tool = resolve(bundle, "tools", op.get("tool")) or {}
            diameter = length_mm(tool, "dia")
            radius = diameter / 2 if number(diameter) else UNKNOWN
            stages = (
                [("finish", 0)]
                if leave is None
                else [("rough", leave)]
                if op.get("do", "").startswith("rough_")
                else [("rough", leave), ("finish", 0)]
            )
            sense, order = cut_order(machine, op)
            bounded = "stock_removal_bounds" in op
            subject = f"{setup['id']}:{op['op']}"
            for stage, allowance in stages:
                offset = radius + allowance if number(radius) and number(allowance) else UNKNOWN
                profile = {
                    "feature": name,
                    "op": op["op"],
                    "stage": stage,
                    "tool": op.get("tool", UNKNOWN),
                    "tool_dia": diameter,
                    "tool_nominal_dia_mm": diameter,
                    "cutter_radius_mm": radius,
                    "offset_mm": offset,
                    "rough_allowance_mm": allowance if stage == "rough" else "not_applicable",
                    "entry_z": before["entry_z"].get(name, before["top_z"]),
                    "to_z": op.get("to_z", UNKNOWN),
                    "dro_to_z": dro_z(op.get("to_z", UNKNOWN), grid),
                    "contour": contour,
                    "tool_dia_basis": "selected member nominal, not measured",
                }
                generated = refused = False
                method = contour.get("method")
                label = f"op {op['op']} {stage}"
                if refusal:
                    # No stage is printed: the rough spoils the part, and its paired
                    # finish alone is not the planned cut.
                    profile.update(cutter_centre=UNKNOWN, allowance_reason=refusal)
                    numbers["profiles"].append(profile)
                    continue
                if method == "arc_table":
                    arc_errors.append(f"{label}: {REMOVED_ARC_TABLE}")
                    refused = True
                elif method in ARC_METHODS:
                    # The arc's geometry is plan units; the cutter and allowance are mm.
                    scale = {"mm": 1.0, "in": 25.4}.get(units)
                    arcs, lines, walls = [], [], []
                    if scale is not None:
                        arcs, lines, walls = _arc(
                            name,
                            feature,
                            op,
                            offset / scale if number(offset) else UNKNOWN,
                            frame,
                            frames,
                            features,
                            sense,
                            order,
                            grid,
                            method,
                            radius / scale if number(radius) else UNKNOWN,
                            scale,
                        )
                    for table in (*arcs, *lines):
                        table.update(stage=stage, allowance_mm=allowance, offset_mm=offset)
                    errors, debts = [], []
                    if scale is None:
                        debts = [f"{label}: the feature units are not mm or in"]
                    elif arcs:
                        errors, debts = _manual(
                            bundle, setup, op, stage, allowance, arcs, lines, walls, label, scale
                        )
                    elif number(offset):
                        debts = [f"{label}: no {method} rows: contour.{_NEEDS[method]} is unknown"]
                    arc_errors.extend(errors)
                    arc_debts.extend(debts)
                    if errors or any("stair_reason" in t for t in (*arcs, *lines)):
                        profile["arc_reason"] = (errors + debts)[0]
                        refused, arcs, lines = True, [], []
                    debt = None
                    if bounded and (arcs or lines) and pre_kernel:
                        for table in (*arcs, *lines):
                            table["kernel_clip"] = True
                    elif bounded and (arcs or lines):
                        clips, why = _clip_facts(bundle, subject)
                        if clips is None:
                            arcs, lines = [], []
                            debt = f"its bounds clip is unknown: {why}"
                        else:
                            arcs, lines, debt = _kernel_clip(subject, arcs, lines, clips)
                    if debt:
                        profile["clip_reason"] = debt
                        clip_debts.append(f"op {op['op']} {stage}: {debt}")
                    if arcs or lines:
                        _sequence([*arcs, *lines])
                        numbers["arc_table"].extend(arcs)
                        numbers["line_table"].extend(lines)
                        # Clip pieces stay separate lists: nothing reconnects them.
                        profile["cutter_centre"] = (
                            arcs[0]["rows"] if len(arcs) == 1 else [arc["rows"] for arc in arcs]
                        )
                        unordered.update(
                            item["cut_order_reason"]
                            for item in (*arcs, *lines)
                            if item["cut_order"] == UNKNOWN and item.get("method") != "chain_drill"
                        )
                        generated = True
                elif contour.get("method") == "linear_table" and _rastered(op, contour):
                    approach = op.get("approach_mm", UNKNOWN)
                    scale = {"mm": 1.0, "in": 25.4}.get(units)
                    printed_top = top(before["top_z"], done=done)
                    lift = (
                        dro_z(printed_top + approach / scale, grid)
                        if scale and number(approach) and number(printed_top)
                        else UNKNOWN
                    )
                    raster, why = _raster(
                        feature, op, offset, radius, frame, frames, sense, order, lift, grid, scale
                    )
                    if raster is None:
                        profile["raster_reason"] = why
                    else:
                        profile.update(raster)
                        if profile["cut_order"] == UNKNOWN:
                            unordered.add(profile["cut_order_reason"])
                        if stage == "finish":
                            grid_errors.extend(
                                _grid_residual(op, feature, raster["grid_residual_mm"], grid)
                            )
                        if lift == UNKNOWN:
                            # Each pass lifts before its rapid return: no lift Z, no cycle.
                            profile["lift_reason"] = (
                                "its lift Z is unknown: it needs approach_mm above a known top"
                            )
                            plan_debts.append(f"op {op['op']} {stage}: {profile['lift_reason']}")
                        generated = True
                elif contour.get("method") == "linear_table":
                    path, residual = _linear(feature, op, offset, radius, frame, frames, grid)
                    if residual is not None and stage == "finish":
                        grid_errors.extend(_grid_residual(op, feature, residual, grid))
                    if path:
                        profile["grid_residual_mm"] = residual
                        profile["cutter_centre"] = path
                        if not isinstance(path[0][0], list):
                            # A closed outline runs counterclockwise with the cutter outside
                            # its walls, so (n x t)·Z > 0; rasters are independent passes.
                            reverse = None if sense is None else sense < 0
                            _ordered(profile, reverse, order, ("cutter_centre",))
                            if profile["cut_order"] == UNKNOWN:
                                unordered.add(profile["cut_order_reason"])
                            if _diagonal(path):
                                unproven.append(f"op {op['op']} {stage} {DIAGONAL_OUTLINE}")
                        generated = True
                elif contour.get("method") == "axial_table" and stage == "rough":
                    stair = _dome_stair(
                        name,
                        feature,
                        op,
                        dro.get("radius_mode"),
                        allowance,
                        {"mm": 1.0, "in": 25.4}.get(bundle.features.get("units"), UNKNOWN),
                    )
                    if stair:
                        numbers.setdefault("stair_tables", []).append(stair)
                        generated = True
                elif contour.get("method") == "axial_table":
                    nose = length_mm(tool, "nose_radius") if tool and not uncertain(tool) else None
                    dome = _dome(
                        name,
                        feature,
                        op,
                        dro.get("radius_mode"),
                        nose if number(nose) else UNKNOWN,
                        _edge_facts(bundle, op) if tool and not uncertain(tool) else None,
                    )
                    if dome:
                        numbers["contours"].append(dome)
                        generated = True
                        unknown |= not number(dome["tool_nose_compensation_mm"])
                if not generated:
                    profile["cutter_centre"] = UNKNOWN
                numbers["profiles"].append(profile)
                unknown |= (not generated and not refused) or not tool or uncertain(tool)
            if lathe:
                unknown |= not number(length_mm(tool, "nose_radius"))
        if not lathe:
            from .level_entry import level_paths

            paths, path_debts = level_paths(
                bundle, setup, numbers, stock_states(bundle, setup), grid, units, dro_z, top
            )
            if paths:
                numbers["level_paths"] = paths
            plan_debts.extend(path_debts)
        status = (
            "error"
            if residuals
            or arc_errors
            or plunge_errors
            or grid_errors
            or band_errors
            or allowed_errors
            or leave_errors
            else "unknown"
            if unknown or unordered or clip_debts or unproven or arc_debts or plan_debts
            else "pass"
        )
        sentence = (
            "Feature targets use the declared model-to-setup basis; cutter tables use explicit "
            "nominal geometry and authored allowance."
        )
        if unknown:
            sentence += (
                " Missing geometry or unverified tool/frame binding prevents a cleared toolpath."
            )
        if unordered:
            sentence += " Cutting order is unknown: " + "; ".join(sorted(unordered)) + "."
        if clip_debts:
            sentence += " Stock-removal clip debt: " + "; ".join(clip_debts) + "."
        if plan_debts:
            sentence += " Pass plan unknown: " + "; ".join(plan_debts) + "."
        if residuals:
            numbers["dro_z_residual_errors"] = residuals
            sentence += " DRO depth rounding error: " + "; ".join(residuals) + "."
        if leave_errors:
            numbers["allowance_errors"] = leave_errors
            sentence += " Rough allowance error: " + "; ".join(leave_errors) + "."
        if plunge_errors:
            sentence += " Relief plunge error: " + "; ".join(plunge_errors) + "."
        if grid_errors:
            numbers["dro_xy_residual_errors"] = grid_errors
            sentence += " DRO cutter-centre rounding error: " + "; ".join(grid_errors) + "."
        if band_errors:
            numbers["band_errors"] = band_errors
            sentence += " Located target band error: " + "; ".join(band_errors) + "."
        if allowed_errors:
            numbers["blade_band_errors"] = allowed_errors
            sentence += " Blade target band error: " + "; ".join(allowed_errors) + "."
        if unproven:
            sentence += " Moves between rows are unproven: " + "; ".join(unproven) + "."
        if arc_errors:
            numbers["arc_errors"] = arc_errors
            sentence += " Manual arc error: " + "; ".join(arc_errors) + "."
        if arc_debts:
            numbers["arc_debts"] = arc_debts
            sentence += " Manual arc debt: " + "; ".join(arc_debts) + "."
        methods = {table.get("method") for table in numbers["arc_table"]}
        tables = [table.get("rotary", {}).get("table") for table in numbers["arc_table"]]
        result.append(
            Finding(
                "coordinates",
                setup["id"],
                status,
                numbers,
                [
                    "PLAN.md §4.1 coordinates",
                    "features declared frames and nominal geometry",
                    "plan contour steps, operation targets and stock allowances",
                    "inventory selected cutter nominal diameter",
                    *plan_frame_cite(bundle, setup),
                    *dict.fromkeys(locator_cites),
                    *dict.fromkeys(aim_cites),
                    *axis_cites,
                    *(
                        ["docs/plan.md Manual arcs: stairs, chain drill, chords, rotary table"]
                        if methods or arc_errors or arc_debts
                        else []
                    ),
                    *(
                        ["policy numbers.max_filing_stock_mm: most stock left for the file"]
                        if methods & ROUGH_METHODS
                        else []
                    ),
                    *(
                        f"inventory fixtures.{t}: rotary table dial"
                        for t in dict.fromkeys(tables)
                        if t
                    ),
                ],
                sentence,
            )
        )
    return result
