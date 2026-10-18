"""Split from zero_recipe.py by scripts/split_modules.py."""

from __future__ import annotations

import math

from prechips.rules.zero_recipe.faces import _rectangle, _uncut
from prechips.rules.zero_recipe.touch import (
    MEASURED,
    SIDES,
    TOUCH_LAND_MM,
    TURNED,
    _framed,
    _stock_route,
    face_normal_z,
    lathe_setup,
    touch_corner,
    touch_side,
)

from ...model import UNIT_TOLERANCE
from ..geometry_common import TURNING_BLADE_KINDS, approach, cutting_action, op_claims
from ..resolution import (
    HAND_FINISH,
    LENGTH_TOLERANCE_MM,
    UNKNOWN,
    known_refs,
    length_mm,
    number,
    op_feature,
    resolve,
    setup_frame,
    uncertain,
)
from ..tip_endpoints import (
    FACING,
    POCKETING,
    _kernel_face_boxes,
    _turning_window,
    cut_coverage,
    forms_face,
    mapping,
    records,
)

# Native rigid-transform eligibility, not authored included-angle equality.
_NATIVE_DIRECTION_TOLERANCE_DEG = 1e-6


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
    from ..coordinates import UNIT_MM

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
    from ..coordinates import UNIT_MM, frame_axes, frame_point, model_point

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
    from ...measurements import angle_fact, length_fact
    from .._envelope import measurement_item
    from ..coordinates import dro_grid, dro_point, frame_axes, frame_point, planned_point
    from ..tip_endpoints import hole_depth_mm

    action = op.get("do")
    if action not in {"spot", "drill", "ream", "counterbore"}:
        return None
    feature = mapping(bundle.feature_definitions.get(op_feature(op)))
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
    from ...joint_features import joint_operation
    from ..coordinates import (
        UNIT_MM,
        dro_grid,
        dro_z,
        formed_z,
        frame_axes,
        frame_point,
        model_point,
    )
    from ..geometry_common import finishing_subjects

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
        name = op_feature(op)
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
    from ..coordinates import UNIT_MM, frame_axes, frame_point, model_point

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
    from ..coordinates import UNIT_MM, frame_axes, model_point

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
    from ..coordinates import UNIT_MM, frame_axes

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
    from ..coordinates import UNIT_MM

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
    from ..coordinates import UNIT_MM

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
    from ..coordinates import UNIT_MM

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
    from ..coordinates import UNIT_MM

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
    from ..coordinates import UNIT_MM, formed_z, frame_axes

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
