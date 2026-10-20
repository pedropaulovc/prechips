"""Causal target-face creation proof for accepted registered finite slitting saws.

Called only after the stock builder accepts both named physical children. Ordinary
saw claims remain empty. A complete trimmed planar target footprint must lie on
its own actual child's new boundary, with a full kerf-width outward material
column removed by this cut and an inward column retained in that child. Neither
kerf dimensions nor coincident planes alone establish this proof. These are
geometric creation facts, never finish, tolerance or physical-execution approval.

Runner seam: owner.workpieces/workpiece_mapping, faces, state, matrix,
_partition_path/_qualified_claims/_subject, and saws. All shapes are setup-frame
native B-reps; output registrations are identities, not substitute geometry.
"""

import math
from copy import deepcopy

import FreeCAD
import Part

_LENGTH = 1e-6
_AREA = 1e-6
_VOLUME = 1e-6
_PARALLEL = 1 - 1e-9
_REQUEST_KEYS = (
    "subject",
    "do",
    "saw_tool",
    "kerf_mm",
    "cut_plane",
    "mounted_saw",
    "workpiece_faces",
    "outputs",
)


def _number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _normal(face):
    u0, u1, v0, v1 = face.ParameterRange
    normal = face.normalAt((u0 + u1) / 2, (v0 + v1) / 2)
    normal.normalize()
    return normal


def _shape(shape, dimension):
    if shape is None or not shape.isValid() or getattr(shape, dimension) <= 0:
        raise ValueError("the native face or material column is invalid or empty")
    return shape


def _difference(shape, within, dimension):
    remainder = shape.cut(within)
    common = shape.common(within)
    if any(not result.isNull() and not result.isValid() for result in (remainder, common)):
        raise ValueError("native footprint/material boolean is invalid")
    original, value, covered = (getattr(result, dimension) for result in (shape, remainder, common))
    if any(not _number(measure) or measure < 0 for measure in (original, value, covered)):
        raise ValueError("native footprint/material boolean is not measurable")
    # An empty difference proves containment only when an independent common
    # accounts for the original area/volume. Never substitute either result.
    tolerance = max(_AREA if dimension == "Area" else _VOLUME, original * 1e-6)
    if abs(original - value - covered) > tolerance:
        raise ValueError("native footprint/material difference and common do not conserve measure")
    return remainder, value


def _boundary_remainder(face, solid, plane, sign):
    """Subtract full coplanar, outward-facing boundary patches, preserving trim loops."""
    remainder = face
    for patch in solid.Faces:
        if not isinstance(patch.Surface, Part.Plane):
            continue
        bounds = patch.BoundBox
        if (
            abs(bounds.ZMin - plane) > _LENGTH
            or abs(bounds.ZMax - plane) > _LENGTH
            or _normal(patch).z * sign < _PARALLEL
        ):
            continue
        remainder, area = _difference(remainder, patch, "Area")
        if area == 0:
            break
    return remainder.Area


def _certify_face(runner, before, removed, child, face, row, band):
    _shape(face, "Area")
    if not isinstance(face.Surface, Part.Plane):
        raise ValueError("the explicitly claimed target face is not planar")
    sign = -1 if row["side"] == "above" else 1
    edge = band[1] if row["side"] == "above" else band[0]
    normal = _normal(face)
    plane = face.CenterOfMass.z
    bounds = face.BoundBox
    plane_error = max(abs(bounds.ZMin - edge), abs(bounds.ZMax - edge))
    if normal.z * sign < _PARALLEL or plane_error > _LENGTH:
        raise ValueError("the whole target face does not coincide with its child's kerf edge")
    width = band[1] - band[0]
    area = face.Area
    area_limit = max(_AREA, area * _AREA)
    volume_limit = max(_VOLUME, area * width * _VOLUME)
    boundary_missing = _boundary_remainder(face, child, plane, sign)
    preexisting = max(0.0, area - _boundary_remainder(face, before, plane, sign))
    # The complete outward prism reaches the opposite kerf edge. Preexisting air,
    # a tangency, a partial cut or an old face cannot supply its missing material.
    outward = _shape(face.extrude(FreeCAD.Vector(0, 0, sign * width)), "Volume")
    inward = _shape(face.extrude(FreeCAD.Vector(0, 0, -sign * min(width, 1e-3))), "Volume")
    _, missing_before = _difference(outward, before, "Volume")
    _, missing_removed = _difference(outward, removed, "Volume")
    _, missing_child = _difference(inward, child, "Volume")
    row.update(
        surface="plane",
        normal=[0.0, 0.0, float(sign)],
        plane_z_mm=plane,
        cutting_band_mm=list(band),
        plane_error_mm=plane_error,
        area_mm2=area,
        area_tolerance_mm2=area_limit,
        volume_tolerance_mm3=volume_limit,
        boundary_uncovered_area_mm2=boundary_missing,
        preexisting_boundary_area_mm2=preexisting,
        outward_column_volume_mm3=outward.Volume,
        outward_missing_before_mm3=missing_before,
        outward_missing_removed_mm3=missing_removed,
        inward_column_volume_mm3=inward.Volume,
        inward_missing_child_mm3=missing_child,
    )
    if (
        boundary_missing > area_limit
        or preexisting > area_limit
        or missing_before > volume_limit
        or missing_removed > volume_limit
        or missing_child > volume_limit
    ):
        raise ValueError("the whole target footprint is not a new boundary of this cut's child")
    row.update(status="pass", reasons=[])


def certify_saw_faces(runner, op, before, after, records):
    """Separate certificate; any uncertainty withholds credit, never the accepted cut."""
    mounted = op.get("mounted_saw")
    detail = runner.saws.get(id(op), {})
    saw = detail.get("saw", {})
    if (
        op.get("do") != "cut_off"
        or op.get("saw_tool") != "slitting_saw"
        or not isinstance(mounted, dict)
        or mounted.get("model") != "finite_disk_v1"
        or saw.get("model") != "finite_disk_v1"
        or saw.get("status") != "pass"
        or "workpiece_faces" not in op
        or not getattr(runner.owner, "workpieces", {})
    ):
        return {}
    proof = {
        "model": "finite_saw_face_credit_v1",
        "producer": runner._subject(op),
        "request": deepcopy({key: op[key] for key in _REQUEST_KEYS if key in op}),
        "faces": [],
    }
    try:
        claims = runner._qualified_claims(op)
        path = runner._partition_path()
        band = saw.get("cutting_band_mm")
        if (
            not claims
            or path is None
            or not isinstance(band, list)
            or len(band) != 2
            or not all(_number(value) for value in band)
            or band[0] >= band[1]
            or not isinstance(records, dict)
            or len(records) != 2
            or {record.get("side") for record in records.values()} != {"below", "above"}
            or any(record.get("status") != "pass" for record in records.values())
        ):
            raise ValueError("accepted registered finite-saw partition evidence is incomplete")
        pieces = sorted(after.Solids, key=lambda piece: piece.BoundBox.ZMin)
        if len(pieces) != 2:
            raise ValueError("the accepted cut has no unique two-child stock")
        removed = _shape(before.cut(after), "Volume")
        for member, refs in claims.items():
            outputs = [
                (name, record)
                for name, record in records.items()
                if member in record.get("carries_workpieces", ())
            ]
            for ref in refs:
                row = {
                    "status": "unknown",
                    "reasons": [],
                    "workpiece_id": member,
                    "canonical_ref": ref,
                    "index": runner.owner.workpiece_mapping[member][ref],
                    "registration": deepcopy(runner.owner.workpieces[member]),
                    "input_partition_path": deepcopy(path),
                }
                proof["faces"].append(row)
                try:
                    if len(outputs) != 1:
                        raise ValueError("the selected member has no unique accepted named child")
                    name, record = outputs[0]
                    if record.get("partition_path") != path + [
                        {"split": runner.setup["id"], "output": name}
                    ]:
                        raise ValueError("the accepted child's partition path is not this cut")
                    side = record["side"]
                    row.update(
                        output=name,
                        side=side,
                        output_registration=deepcopy(op["outputs"][name]["pose"]),
                        partition_path=deepcopy(record["partition_path"]),
                        output_proof=deepcopy(record),
                    )
                    child = pieces[0 if side == "below" else 1]
                    _certify_face(
                        runner, before, removed, child, runner.faces[row["index"]], row, band
                    )
                except Exception as exc:
                    row.update(status="unknown", reasons=[str(exc)])
    except Exception as exc:
        proof["reasons"] = [str(exc)]
    return proof
