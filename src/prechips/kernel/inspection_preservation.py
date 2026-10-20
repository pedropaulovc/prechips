"""Requirement-specific early inspection proofs from the actual native material route.

``preserve_inspections`` runs after the setup runners finish.  Its only inputs are
native runners and their actual ancestor map; request identities are never material
ownership.  A nominal dimension selects opposite planar supports, not a guessed
width/height axis.  Every point of those original supports must remain a boundary.
The only permitted aperture is a resolved, interior thread-envelope opening.

Runner seam: setup/owner/state, matrix/faces, cuts/built/stopped_cut,
lower_part/lower_out/lower_cuts, thread_regions, _placed/_registered_target and
_partition_path.  Shapes and cut snapshots are in setup coordinates; published
support axes/planes use the original registered model coordinates.  No host-side
material graph, inspection result or machining-credit facts participate.
"""

import math
from copy import deepcopy

import FreeCAD
import Part

_LENGTH = 1e-6
_AREA = 1e-6
_VOLUME = 1e-6
_PARALLEL = 1 - 1e-9
_METADATA = {"inspect", "release", "scribe"}
_HOLES = {"drill", "spot_drill", "center_drill", "bore", "ream", "tap", "hand_tap"}


def _moved(shape, *matrices):
    moved = shape.copy()
    for matrix in matrices:
        if matrix is not None and not moved.isNull():
            moved.transformShape(matrix)
    return moved


def _normal(face):
    u0, u1, v0, v1 = face.ParameterRange
    normal = face.normalAt((u0 + u1) / 2, (v0 + v1) / 2)
    normal.normalize()
    return normal


def _axis(normal):
    result = FreeCAD.Vector(normal)
    for value in result:
        if abs(value) > _LENGTH:
            if value < 0:
                result = -result
            break
    return result


def _limit(face):
    return max(_AREA, face.Area * _AREA)


def _valid(solid):
    return solid is not None and not solid.isNull() and solid.isValid() and solid.Volume > _VOLUME


def _model_face(runner, member, index):
    transform = runner.state.get("member_transforms", {}).get(member)
    return _moved(
        runner.faces[index],
        runner.matrix.inverse(),
        transform.inverse() if transform is not None else None,
    )


def _setup_face(runner, member, face):
    return _moved(face, runner.state.get("member_transforms", {}).get(member), runner.matrix)


def _supports(runner, request):
    member, feature = request["workpiece_id"], request["feature"]
    nominal = request.get("nominal_mm")
    if (
        isinstance(nominal, bool)
        or not isinstance(nominal, (int, float))
        or not math.isfinite(nominal)
        or nominal <= 0
    ):
        raise ValueError("requested nominal separation is unresolved")
    selected = runner.owner.workpiece_features.get(member, {}).get(feature)
    mapping = getattr(runner.owner, "workpiece_mapping", {}).get(member, {})
    if not isinstance(selected, list) or not selected or not mapping or runner.matrix is None:
        raise ValueError("registered feature face binding is unresolved")
    indices = sorted(set(mapping.values()))
    if not set(selected) <= set(indices):
        raise ValueError("feature faces do not belong to the requested registered member")
    planes = {
        index: _model_face(runner, member, index)
        for index in indices
        if isinstance(runner.faces[index].Surface, Part.Plane)
    }
    candidates = []
    for first in selected:
        if first not in planes:
            continue
        a = planes[first]
        normal = _normal(a)
        axis = _axis(normal)
        for second, b in planes.items():
            if normal.dot(_normal(b)) > -_PARALLEL:
                continue
            # The lower plane must face outward in -axis and the upper in +axis.
            pa, pb = a.CenterOfMass.dot(axis), b.CenterOfMass.dot(axis)
            low, high = sorted((pa, pb))
            if abs(high - low - nominal) > _LENGTH or (pa - pb) * normal.dot(axis) <= 0:
                continue
            shifted = b.copy()
            shifted.translate(axis * (pa - pb))
            footprint = a.common(shifted)
            if footprint.Area <= _AREA:
                continue
            if second not in selected:
                # A complementary face outside the feature is admissible only
                # directly across a whole material column under its footprint.
                # Equal plane spacing somewhere else in the member is not support.
                column = footprint.extrude(axis * (pb - pa))
                target = runner.owner.finished_solids.get(member)
                if not _valid(column) or not _valid(target) or column.cut(target).Volume > _VOLUME:
                    continue
            candidate = (axis, low, high)
            if not any(
                axis.dot(other[0]) >= _PARALLEL
                and abs(low - other[1]) <= _LENGTH
                and abs(high - other[2]) <= _LENGTH
                for other in candidates
            ):
                candidates.append(candidate)
    if len(candidates) != 1:
        raise ValueError("feature faces lack a unique supported nominal plane pair/direction")
    axis, low, high = candidates[0]
    supports = []
    for index, face in planes.items():
        position, direction = face.CenterOfMass.dot(axis), _normal(face).dot(axis)
        if (
            abs(position - low) <= _LENGTH
            and direction <= -_PARALLEL
            or abs(position - high) <= _LENGTH
            and direction >= _PARALLEL
        ):
            supports.append((index, face))
    return supports, {
        "model": "planar_support_v1",
        "indices": [index for index, _ in supports],
        "axis": [0.0 if abs(value) < _LENGTH else float(value) for value in axis],
        "planes_mm": [float(low), float(high)],
        "nominal_mm": nominal,
    }


def _boundary(face, solid):
    """All actual same-plane, same-outward-normal boundary, never solid containment."""
    normal, position = _normal(face), face.CenterOfMass
    faces = [
        candidate
        for candidate in solid.Faces
        if isinstance(candidate.Surface, Part.Plane)
        and normal.dot(_normal(candidate)) >= _PARALLEL
        and abs((candidate.CenterOfMass - position).dot(normal)) <= _LENGTH
    ]
    return Part.makeCompound(faces) if faces else Part.Shape()


def _outside(face, solid, exclusions):
    expected = face
    for envelope in exclusions:
        expected = expected.cut(envelope)
    if expected.Area <= _limit(face):
        raise ValueError("thread exclusion removes an entire dimensional support")
    boundary = _boundary(face, solid)
    if not boundary.Faces:
        return True
    return expected.cut(boundary).Area > _limit(face)


def _hole_for_member(stage, op, member, feature):
    if op.get("do") not in _HOLES or op.get("feature") != feature:
        return False
    claims = op.get("workpiece_faces")
    if isinstance(claims, dict):
        return member in claims
    manual = op.get("manual_thread")
    if isinstance(manual, dict):
        return manual.get("workpiece_id") == member
    return stage.state.get("finished_names") == {member}


def _thread_regions(runner, member, supports, subjects, lineage, route, positions):
    """Validate transported native envelopes, including a preceding matched drill."""
    accepted, seen = [], set()
    target = runner._placed(runner._registered_target(member))
    available = [
        (sid, holder, record)
        for sid, holder in route
        for record in getattr(holder, "thread_regions", [])
    ]
    route_ids = {sid for sid, _ in route}
    for holder_sid, holder, record in available:
        public = record.get("public", {})
        producer = public.get("producer")
        source = subjects.get(producer)
        if public.get("workpiece_id") != member or source is None or producer in seen:
            continue
        source_sid, source_runner, source_index, source_op = source
        if source_sid not in route_ids or (
            source_sid != holder_sid and source_sid not in lineage.get(holder_sid, set())
        ):
            continue
        if (
            source_op.get("do") != "hand_tap"
            or not _hole_for_member(source_runner, source_op, member, public.get("feature"))
            or public.get("registration") != runner.owner.workpieces.get(member)
            or public.get("partition_path") != source_runner._partition_path()
        ):
            continue
        region, diameter = public.get("region"), public.get("diameter_mm")
        manual = source_op.get("manual_thread")
        if (
            not isinstance(manual, dict)
            or manual.get("model") != "bounded_thread_envelope_v1"
            or manual.get("status") != "ready"
            or manual.get("feature") != public.get("feature")
            or manual.get("region") != region
            or manual.get("diameter_mm") != diameter
        ):
            continue
        if (
            not isinstance(region, dict)
            or isinstance(diameter, bool)
            or not isinstance(diameter, (int, float))
            or not math.isfinite(diameter)
            or diameter <= 0
        ):
            continue
        try:
            _op_state(source_runner, source_op)
            at = FreeCAD.Vector(*region["at_mm"])
            axis = FreeCAD.Vector(*region["axis"])
            depth = region["depth_mm"]
            if (
                not all(math.isfinite(value) for value in (*at, *axis, depth))
                or abs(axis.Length - 1) > _LENGTH
                or depth <= 0
            ):
                continue
            source_transform = source_runner.state.get("member_transforms", {}).get(member)
            model = _moved(
                Part.makeCylinder(diameter / 2, depth, at, axis),
                source_runner.matrix.inverse(),
                source_transform.inverse() if source_transform is not None else None,
            )
            expected = _setup_face(holder, member, model)
            actual = record["shape"]
            if (
                not _valid(actual)
                or actual.cut(expected).Volume > _VOLUME
                or expected.cut(actual).Volume > _VOLUME
            ):
                continue
            envelope = _setup_face(runner, member, model)
            cylinders = [
                face.Surface for face in envelope.Faces if isinstance(face.Surface, Part.Cylinder)
            ]
            if len(cylinders) != 1:
                continue
            valid = True
            for face in target.Faces:
                if not isinstance(face.Surface, Part.Plane):
                    continue
                aperture = face.common(envelope)
                if aperture.Area <= _limit(face):
                    continue
                if (
                    abs(_normal(face).dot(cylinders[0].Axis)) < _PARALLEL
                    or aperture.distToShape(face.OuterWire)[0] <= _LENGTH
                ):
                    valid = False
                    break
            if not valid or any(
                face.common(envelope).Area > _limit(face)
                and face.common(envelope).distToShape(face.OuterWire)[0] <= _LENGTH
                for face in supports
            ):
                continue
            start = min(
                [(positions[source_sid], source_index)]
                + [
                    (positions[sid], index)
                    for sid, stage in route
                    for index, op in enumerate(stage.setup.get("ops", []))
                    if _hole_for_member(stage, op, member, public.get("feature"))
                    and (positions[sid], index) <= (positions[source_sid], source_index)
                ]
            )
            accepted.append((start, public, envelope))
            seen.add(producer)
        except Exception:
            # Missing/unsupported material or untransportable provenance grants
            # no aperture, even if another operation happens to name a thread.
            continue
    return accepted


def _metadata(op):
    # An inspect label cannot conceal operative cutting geometry.
    return op.get("do") in _METADATA and not any(
        key in op
        for key in ("manual_thread", "cut_plane", "sweep", "removal", "outputs", "mounted_saw")
    )


def _op_state(runner, op):
    state = runner.cuts.get(id(op))
    if state is None or len(state) != 3:
        raise ValueError(f"{op.get('subject')}: native operation material proof is missing")
    before, after, reason = state
    if (
        reason is not None
        or getattr(runner, "stopped_cut", None) == id(op)
        or not _valid(before)
        or not _valid(after)
    ):
        raise ValueError(
            f"{op.get('subject')}: native operation material proof is unknown "
            f"({reason or 'cut stopped'})"
        )
    lower = getattr(runner, "lower_cuts", {}).get(id(op))
    if (
        lower is None
        or len(lower) != 3
        or lower[2] is not None
        or not _valid(lower[0])
        or not _valid(lower[1])
    ):
        raise ValueError(f"{op.get('subject')}: lower material proof is missing or unknown")
    return before, after, lower[0], lower[1]


def _verify(face, upper, lower, envelopes):
    if _outside(face, upper, envelopes):
        return "error", "original dimensional support geometry is absent or altered"
    if _outside(face, lower, envelopes):
        return "unknown", "material bounds do not prove the complete dimensional support"
    return "pass", None


def _check_setup(check_id, runners, subjects):
    if not isinstance(check_id, str):
        return None
    if check_id in subjects:
        check = subjects[check_id]
        return check[0] if check is not None and check[3].get("do") == "inspect" else None
    # Inspections are deliberately omitted from native cutting operations.
    # The operative normalized request supplies their exact subject identity;
    # do not make a geometry proof depend on optional render-only annotations.
    matches = [
        sid for sid, _ in runners if check_id.startswith(f"{sid}:") and check_id != f"{sid}:"
    ]
    return matches[0] if len(matches) == 1 else None


def _prove(request, source_sid, receiver_sid, runner, runners, lineage, subjects):
    row = {
        "model": "requirement_preservation_v1",
        **{
            key: deepcopy(request.get(key))
            for key in ("check_id", "feature", "requirement", "workpiece_id", "after", "before")
        },
        "producer": request.get("after"),
        "receiver": receiver_sid,
        "registration": deepcopy(runner.owner.workpieces.get(request.get("workpiece_id"))),
        "partition_path": runner._partition_path(),
        "status": "unknown",
        "reasons": [],
        "region": None,
        "operations": [],
    }
    try:
        member = request.get("workpiece_id")
        if not isinstance(row["registration"], dict) or row["partition_path"] is None:
            raise ValueError("current member registration or partition path is unresolved")
        after, check, before = (
            subjects.get(request.get(key)) for key in ("after", "check_id", "before")
        )
        if (
            after is None
            or before is None
            or _check_setup(request.get("check_id"), runners, subjects) != source_sid
        ):
            raise ValueError("inspection producer/check/before identity is unresolved or repeated")
        positions = {sid: index for index, (sid, _) in enumerate(runners)}

        def order(item):
            return positions[item[0]], item[2]

        if not order(after) < order(before) or (
            check is not None and not order(after) < order(check) < order(before)
        ):
            raise ValueError("inspection scope operation order is unproven")
        if after[0] != source_sid and after[0] not in lineage.get(source_sid, set()):
            raise ValueError("inspection producer is not in the actual incoming material lineage")
        if before[0] != source_sid and source_sid not in lineage.get(before[0], set()):
            raise ValueError("inspection scope boundary is not in the actual descendant lineage")
        if (
            positions[receiver_sid] >= positions[before[0]]
            and before[0] != receiver_sid
            and before[0] not in lineage.get(receiver_sid, set())
        ):
            raise ValueError("scope boundary is not on this receiver's actual member lineage")
        if member not in (before[1].state.get("finished_names") or set()):
            raise ValueError("scope boundary does not carry the checked registered member")
        if member not in (after[1].state.get("finished_names") or set()):
            raise ValueError("producer does not carry the checked registered member")
        supports, region = _supports(after[1], request)
        row["region"] = region
        route = [
            (sid, stage)
            for sid, stage in runners
            if (sid == receiver_sid or sid in lineage.get(receiver_sid, set()))
            and (sid == after[0] or after[0] in lineage.get(sid, set()))
        ]
        if not route or route[0][0] != after[0] or route[-1][0] != receiver_sid:
            raise ValueError("complete actual producer-to-receiver lineage is unproven")
        row["operations"] = [
            op.get("subject")
            for sid, stage in route
            for index, op in enumerate(stage.setup.get("ops", []))
            if (sid != after[0] or index >= after[2])
            and (op.get("subject") == request["after"] or not _metadata(op))
        ]
        for sid, stage in route:
            if member not in (stage.state.get("finished_names") or set()) or stage.matrix is None:
                raise ValueError(f"{sid}: checked member material registration is unresolved")
            if (
                stage.owner.workpieces.get(member) != row["registration"]
                or stage._partition_path() is None
            ):
                raise ValueError(f"{sid}: member registration or partition proof is unresolved")
            placed = [_setup_face(stage, member, face) for _, face in supports]
            regions = _thread_regions(stage, member, placed, subjects, lineage, route, positions)
            if sid != after[0]:
                operations = stage.setup.get("ops", [])
                entering = (
                    stage.cuts.get(id(operations[0]), (None, None, None))[0]
                    if operations
                    else getattr(stage, "built", (None, None))[0]
                )
                entering_lower = getattr(stage, "lower_part", None)
                if not _valid(entering) or not _valid(entering_lower):
                    raise ValueError(f"{sid}: arriving material bounds are unresolved")
                apertures = [
                    envelope for start, _, envelope in regions if start < (positions[sid], 0)
                ]
                for face in placed:
                    status, reason = _verify(face, entering, entering_lower, apertures)
                    if status != "pass":
                        row.update(status=status, reasons=[f"{sid}: arriving {reason}"])
                        return row
            first = after[2] if sid == after[0] else 0
            for index, op in enumerate(stage.setup.get("ops", [])):
                if index < first:
                    continue
                subject = op.get("subject")
                is_producer = subject == request["after"]
                if not is_producer and _metadata(op):
                    continue
                upper_before, upper, _, lower = _op_state(stage, op)
                current = (positions[sid], index)
                active = [
                    (public, envelope) for start, public, envelope in regions if start <= current
                ]
                envelopes = [envelope for _, envelope in active]
                for face in placed:
                    # Existing holes may persist. A new profile/face cut cannot use
                    # an earlier thread's uncertainty to hide newly lost support.
                    removed = Part.Shape()
                    if not is_producer:
                        previous_boundary = _boundary(face, upper_before)
                        if previous_boundary.Faces:
                            removed = face.common(previous_boundary)
                            current_boundary = _boundary(face, upper)
                            if current_boundary.Faces:
                                removed = removed.cut(current_boundary)
                    if not is_producer and removed.Area > _limit(face):
                        eligible = [
                            envelope
                            for public, envelope in active
                            if _hole_for_member(stage, op, member, public.get("feature"))
                        ]
                        for envelope in eligible:
                            removed = removed.cut(envelope)
                        if removed.Area > _limit(face):
                            row.update(
                                status="error",
                                reasons=[
                                    f"{subject}: later cut alters original dimensional support"
                                ],
                            )
                            return row
                    status, reason = _verify(face, upper, lower, envelopes)
                    if status != "pass":
                        row.update(status=status, reasons=[f"{subject}: {reason}"])
                        return row
            built = getattr(stage, "built", None)
            lower = getattr(stage, "lower_out", None)
            if built is None or built[1] is not None or not _valid(built[0]) or not _valid(lower):
                raise ValueError(f"{sid}: terminal material bounds are unresolved")
            active = [
                envelope
                for start, _, envelope in regions
                if start <= (positions[sid], len(stage.setup.get("ops", [])))
            ]
            for face in placed:
                status, reason = _verify(face, built[0], lower, active)
                if status != "pass":
                    row.update(status=status, reasons=[f"{sid}: {reason}"])
                    return row
        row["status"] = "pass"
    except Exception as exc:
        row["reasons"] = [str(exc)]
    return row


def preserve_inspections(result, runners, lineage):
    """Append one exact-identity proof per applicable request/member/receiver setup.

    Unsupported operations, missing lower bounds, ambiguous supports and incomplete
    scopes remain unknown.  Observed destruction is an error, even when a later
    operation could recreate a nominally similar surface.
    """
    subjects, repeated = {}, set()
    for sid, runner in runners:
        for index, op in enumerate(runner.setup.get("ops", [])):
            subject = op.get("subject")
            if not isinstance(subject, str) or subject in subjects:
                repeated.add(subject)
            else:
                subjects[subject] = (sid, runner, index, op)
    for subject in repeated:
        subjects[subject] = None
    requests = []
    for declared_sid, source in runners:
        for request in source.setup.get("inspection_preservation", []):
            if not isinstance(request, dict) or any(request == prior for _, prior in requests):
                continue
            source_sid = _check_setup(request.get("check_id"), runners, subjects)
            requests.append((source_sid if source_sid is not None else declared_sid, request))
    for source_sid, request in requests:
        member = request.get("workpiece_id")
        for receiver_sid, receiver in runners:
            if source_sid != receiver_sid and source_sid not in lineage.get(receiver_sid, set()):
                continue
            names = receiver.state.get("finished_names")
            if names is not None and member not in names:
                continue
            facts = result.setdefault("setups", {}).setdefault(receiver_sid, {})
            facts.setdefault("inspection_preservation", []).append(
                _prove(request, source_sid, receiver_sid, receiver, runners, lineage, subjects)
            )
