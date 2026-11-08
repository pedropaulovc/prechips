"""Resolve one shared axis translation from immutable source geometry, never native guesses.

The host establishes the declarative contract; the native kernel must independently prove
that the selected source faces have these primitives and can be reconstructed safely.
"""

from __future__ import annotations

import math
from types import SimpleNamespace

from prechips.inputs import BadInput

_CYLINDERS = {"boss", "cylinder", "shaft"}
_MEMBERS = ("boss", "bore", "caps")


def _number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _vector(value, where):
    if not isinstance(value, list) or len(value) != 3 or not all(_number(v) for v in value):
        raise BadInput(f"{where} must be a known finite three-vector.")
    return list(value)


def _dot(left, right):
    return sum(a * b for a, b in zip(left, right, strict=True))


def _unit(value, where):
    vector = _vector(value, where)
    length = math.hypot(*vector)
    if not math.isfinite(length) or length <= 0:
        raise BadInput(f"{where} must have a finite nonzero direction.")
    return [v / length for v in vector]


def _frame(manifest, feature, where):
    from prechips.rules.coordinates import frame_axes

    frames = manifest.get("frames")
    frame = frames.get(feature.get("frame", "model")) if isinstance(frames, dict) else None
    if not isinstance(frame, dict) or frame.get("binding") == "unknown":
        raise BadInput(f"{where} needs a known source frame.")
    origin = _vector(frame.get("origin"), f"{where} frame origin")
    axes = [_vector(axis, f"{where} frame axis") for axis in frame_axes(frame)]
    x, y, z = axes
    cross = [x[1] * y[2] - x[2] * y[1], x[2] * y[0] - x[0] * y[2], x[0] * y[1] - x[1] * y[0]]
    if math.dist(cross, z) > 1e-9:
        raise BadInput(f"{where} needs a right-handed source frame.")
    return origin, axes


def _direction(local, axes, where):
    vector = _unit(local, where)
    return _unit([sum(vector[j] * axes[j][i] for j in range(3)) for i in range(3)], where)


def _located(manifest, feature, scale, where):
    origin, axes = _frame(manifest, feature, where)
    at = _vector(feature.get("at"), f"{where}.at")
    point = _vector(
        [(origin[i] + sum(at[j] * axes[j][i] for j in range(3))) * scale for i in range(3)],
        f"{where} model origin",
    )
    return point, _direction(feature.get("axis"), axes, f"{where}.axis")


def _radius(bundle, feature, where):
    from prechips.rules.turned_profile import nominal_diameter

    diameter = nominal_diameter(bundle, feature)
    if not _number(diameter) or diameter <= 0:
        raise BadInput(f"{where} needs a known positive nominal cylinder diameter.")
    return diameter / 2


def _cylinder(bundle, feature, scale, where):
    origin, axes = _frame(bundle.features, feature, where)
    # z_mm uses manifest length units, as in turned_profile._axial_span. Only the
    # normalized job's z_mm is unconditionally millimetres.
    span = feature.get("z_mm")
    if not (
        isinstance(span, list)
        and len(span) == 2
        and all(_number(v) for v in span)
        and span[0] < span[1]
    ):
        raise BadInput(f"{where}.z_mm needs a known increasing cylinder span.")
    if "at" in feature and _vector(feature["at"], f"{where}.at") != [0.0, 0.0, 0.0]:
        raise BadInput(f"{where} cylinder stations must be based at its source frame origin.")
    axis = _unit(feature.get("axis", [0.0, 0.0, 1.0]), f"{where}.axis")
    if abs(axis[0]) > 1e-9 or abs(axis[1]) > 1e-9:
        raise BadInput(f"{where} cylinder stations must run along its source frame Z.")
    stations = [value * scale for value in span]
    point = _vector([value * scale for value in origin], f"{where} model origin")
    if not all(_number(value) for value in stations):
        raise BadInput(f"{where} cylinder span is not finite in millimetres.")
    # Stations refer to frame Z even when the cylinder's authored axis points backward.
    return point, axes[2], _radius(bundle, feature, where), stations


def _faces(feature, where):
    from prechips.kernel.step_faces import FaceRefError, parse_ref

    faces = feature.get("faces")
    if not isinstance(faces, list) or not faces:
        raise BadInput(f"{where} must name known source faces.")
    try:
        for face in faces:
            parse_ref(face)
    except FaceRefError as exc:
        raise BadInput(f"{where}: {exc}") from exc
    if len(set(faces)) != len(faces):
        raise BadInput(f"{where} source faces must be distinct.")
    return set(faces)


def resolve_placements(bundle) -> list[dict]:
    """Return source-based native records, or raise BadInput; never use a nominal fallback.

    Every position/radius/span in a record is in millimetres. ``origin_mm`` and
    ``support_origin_mm`` are the original cylinder frame origins; their ``z_mm`` spans
    are axial offsets from those origins. ``delta_mm`` moves boss, bore and caps only.
    The reference and supporting cylinder remain fixed. No source dictionaries mutate.
    """
    from prechips.rules.coordinates import UNIT_MM, band_reference

    declarations = bundle.plan.get("axis_placements", {})
    if not isinstance(declarations, dict):
        raise BadInput("axis_placements must be a table of known placements.")
    if not declarations:
        return []
    if len(declarations) != 1:
        raise BadInput("axis_placements supports exactly one shared-axis placement.")
    if "workpieces" in bundle.plan or len(bundle.features.get("solids", {})) > 1:
        raise BadInput("axis_placements does not support registered workpieces or multiple solids.")
    aims = bundle.plan.get("aims", {})
    if any(aim.get("face") is not None for aim in aims.values()):
        raise BadInput("axis_placements cannot be combined with faced aims.")
    scale = UNIT_MM.get(bundle.features.get("units"))
    if scale is None:
        raise BadInput("axis_placements requires known mm or in source units.")
    definitions = bundle.features["features"]
    name, declaration = next(iter(declarations.items()))
    where = f"axis_placements.{name}"
    if not isinstance(name, str) or not name.strip() or name.strip() == "unknown":
        raise BadInput("Axis placement names must be known and non-empty.")
    if not isinstance(declaration, dict) or set(declaration) != {
        *_MEMBERS,
        "support",
        "separation_mm",
    }:
        raise BadInput(f"{where} requires boss, bore, caps, support and separation_mm only.")
    names = [declaration[role] for role in (*_MEMBERS, "support")]
    if any(
        not isinstance(value, str)
        or not value.strip()
        or value.strip() == "unknown"
        or value not in definitions
        for value in names
    ):
        raise BadInput(f"{where} members must name known exported source features.")
    if len(set(names)) != len(names):
        raise BadInput(f"{where} members and support must be distinct features.")
    boss, bore, caps, support = [definitions[value] for value in names]
    if boss.get("kind") not in _CYLINDERS or support.get("kind") not in _CYLINDERS:
        raise BadInput(f"{where} boss and support must be nominal cylinder features.")
    if bore.get("kind") != "hole" or bore.get("thru") is not True or caps.get("kind") != "face":
        raise BadInput(f"{where} requires a through hole bore and a face caps feature.")
    reference_name = bore.get("height_from")
    if (
        not isinstance(reference_name, str)
        or not reference_name.strip()
        or reference_name.strip() == "unknown"
        or reference_name not in definitions
        or reference_name in names
    ):
        raise BadInput(f"{where} bore.height_from must name a distinct fixed source axis.")
    reference = definitions[reference_name]
    if reference.get("kind") != "hole":
        raise BadInput(f"{where} height_from must be a located source hole axis.")
    if any(member in aims for member in (*names, reference_name)):
        raise BadInput(f"{where} members, support and reference cannot also have aims.")
    face_sets = [
        _faces(feature, f"{where} {member}")
        for member, feature in zip(names, (boss, bore, caps, support), strict=True)
    ]
    reference_faces = _faces(reference, f"{where} {reference_name}")
    seen_faces = set(reference_faces)
    for faces in face_sets:
        if seen_faces & faces:
            raise BadInput(f"{where} member, support and reference source faces must not overlap.")
        seen_faces.update(faces)
    for aimed_name in aims:
        visited = set()
        related = aimed_name
        while isinstance(related, str) and related in definitions and related not in visited:
            visited.add(related)
            feature = definitions[related]
            faces = feature.get("faces")
            if related in (*names, reference_name) or (
                isinstance(faces, list) and seen_faces.intersection(faces)
            ):
                raise BadInput(f"{where} conflicts with the source geometry of aims.{aimed_name}.")
            related = feature.get("hole", feature.get("parent", feature.get("coaxial_to")))
    origin, axis, boss_radius, span = _cylinder(bundle, boss, scale, f"{where} boss")
    support_origin, support_axis, support_radius, support_span = _cylinder(
        bundle, support, scale, f"{where} support"
    )
    bore_origin, bore_axis = _located(bundle.features, bore, scale, f"{where} bore")
    reference_origin, reference_axis = _located(
        bundle.features, reference, scale, f"{where} reference"
    )
    _frame(bundle.features, caps, f"{where} caps")
    bore_radius = _radius(bundle, bore, f"{where} bore")
    if bore_radius >= boss_radius:
        raise BadInput(f"{where} bore radius must be smaller than its boss radius.")
    offset = [a - b for a, b in zip(bore_origin, origin, strict=True)]
    axial_offset = _dot(offset, axis)
    radial = [
        value - axial_offset * direction for value, direction in zip(offset, axis, strict=True)
    ]
    if abs(abs(_dot(axis, bore_axis)) - 1.0) > 1e-9 or math.hypot(*radial) > 1e-6:
        raise BadInput(f"{where} bore and boss source axes must be concentric.")
    requirements = bore.get("requirements")
    if not isinstance(requirements, list) or "separation" not in requirements:
        raise BadInput(f"{where} bore must hold an exported separation band from height_from.")
    # A deliberately source-only facade prevents band_reference -> planned_point from
    # re-entering placement resolution or consuming a process aim. The explicit target
    # additionally keeps its reference independent of all plan coordinate operations.
    source = SimpleNamespace(
        plan={"aims": {}, "axis_placements": {}, "setups": []},
        features=bundle.features,
        feature_definitions=definitions,
    )
    check = band_reference(
        source,
        names[1],
        [v / scale for v in bore_origin],
        targets={reference_name: [v / scale for v in reference_origin]},
    )
    if check is None or check.get("requirement") != "separation" or check.get("why"):
        raise BadInput(
            f"{where} cannot resolve the source separation: "
            f"{(check or {}).get('why', 'no separation band')}."
        )
    band = check["printed_band"]
    if (
        not isinstance(band, list)
        or len(band) != 2
        or not all(_number(v) for v in band)
        or band[0] > band[1]
    ):
        raise BadInput(f"{where} requires a known finite printed separation band.")
    band_mm = [value * scale for value in band]
    target = declaration["separation_mm"]
    if not _number(target) or target <= 0 or not band_mm[0] <= target <= band_mm[1]:
        raise BadInput(f"{where}.separation_mm must be positive and inside the printed band.")
    direction = _unit(check["direction"], f"{where} separation direction")
    shift = target - check["value"] * scale
    delta = _vector([shift * value for value in direction], f"{where} delta_mm")
    if not all(_number(value) for value in band_mm):
        raise BadInput(f"{where} printed separation band is not finite in millimetres.")
    # Refuse unsupported geometry already knowable from declarations at load time.
    # Surface types, trim topology and retained counterbores still require native proof.
    if abs(_dot(axis, support_axis)) > 1e-9:
        raise BadInput(f"{where} boss and support axes must be perpendicular.")
    offset = [a - b for a, b in zip(origin, support_origin, strict=True)]
    along_boss, along_support = _dot(offset, axis), _dot(offset, support_axis)
    residual = [
        value - along_boss * a - along_support * b
        for value, a, b in zip(offset, axis, support_axis, strict=True)
    ]
    travel = _dot(delta, support_axis)
    sideways = [
        value - travel * component for value, component in zip(delta, support_axis, strict=True)
    ]
    if math.hypot(*residual) > 1e-6 or math.hypot(*sideways) > 1e-6:
        raise BadInput(f"{where} boss axis must intersect the support axis and move along it.")
    for centre in (along_support, along_support + travel):
        if not support_span[0] < centre - boss_radius < centre + boss_radius < support_span[1]:
            raise BadInput(f"{where} boss envelope must remain strictly inside support end planes.")
    if not along_boss + span[0] < -support_radius < support_radius < along_boss + span[1]:
        raise BadInput(f"{where} boss ends must extend beyond both sides of its support cylinder.")
    return [
        {
            "name": name,
            **{role: declaration[role] for role in (*_MEMBERS, "support")},
            "reference": reference_name,
            "separation_mm": target,
            "band_mm": band_mm,
            "delta_mm": delta,
            "origin_mm": origin,
            "axis": axis,
            "boss_radius_mm": boss_radius,
            "bore_radius_mm": bore_radius,
            "z_mm": span,
            "support_origin_mm": support_origin,
            "support_axis": support_axis,
            "support_radius_mm": support_radius,
            "support_z_mm": support_span,
            "reference_origin_mm": reference_origin,
            "reference_axis": reference_axis,
        }
    ]


def member_placement(bundle, name) -> dict | None:
    """The shared translation for a boss/bore/caps feature, never its fixed support.

    Invalid declarations raise BadInput even when the requested member is unrelated;
    callers must not replace a refused placement with source/nominal coordinates.
    """
    return next(
        (
            placement
            for placement in resolve_placements(bundle)
            if name in (placement[role] for role in _MEMBERS)
        ),
        None,
    )
