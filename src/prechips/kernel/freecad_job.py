"""Headless FreeCAD geometry engine for prechips M4 (stdlib + FreeCAD/Part only).

Run as ``freecadcmd.exe freecad_job.py -- INPUT_JSON OUTPUT_JSON``.  The input is
one version-1 job, or ``{"jobs": [job, ...]}`` answered by ``{"results": [...]}``
in the same order; both go through :func:`run_job`.  Output is canonical JSON
(sorted keys, floats rounded to 1e-6 mm) and nothing is printed.  Every number is
measured on the imported B-rep in this run; a fact that cannot be measured is
``"unknown"`` with its reason under ``reasons``, never a default.

Measurement conventions (setup frame, tool axis +Z):

* Face refs ``#<entity>/ADVANCED_FACE[<ordinal>]/<label>`` map to 0-based indices
  of the import's single solid by matching each individually reconstructed
  ADVANCED_FACE's (surface kind, area, optimal bbox) — never by import order.
* Samples: a cell-centred 5x5 UV grid inside each claimed face plus points along
  every boundary edge (spacing max(r, 1 mm), 2..12 per edge).  The tool axis is
  offset by r along the horizontal part of the outward normal (tangent to walls,
  through the sample on floors); the tool tip sits at the sample height.  This is
  the r-along-the-normal offset for a flat-ended cylinder: it touches the face at
  the sample for every upward normal, whereas offsetting the tip by r*n itself
  would float it r*n_z above floors and clear walls shorter than that.  Tool
  cylinder r x flute_len from the tip, holder cylinder holder_radius x
  holder_gauge_len from tip + projection; both shrink/lift by ``LIFT``.
  Downward-facing samples are occluded by the part.
* Obstacles: (part - own region) and the placed jaw boxes.  The own region is the
  material within r of the op's claimed faces: per-face thick offsets by r into
  material plus, around every sharp concave line edge shared by two claimed
  faces, the r-cylinder minus the open-corner wedge in front of both faces.
* Modelled placement only: each sample gets one prescribed tool pose, so a hit
  means that pose collides, not that no other pose reaches the face.
* Vise: part seated at its lowest z; jaw zone z in [seat, seat +
  jaw_above_parallels], limited along ``jaws_along`` to the jaw span when
  ``jaw_center_along_mm`` declares it; inner jaw planes at the zone material's
  extremes along the clamp axis; jaw boxes jaw_width along ``jaws_along``
  (centred on the declared centre, else certainly over the zone material's
  extent and possibly up to jaw_width beyond it), jaw_depth outward, jaw_height
  down from the jaw top; rear/back = +Y, front = -Y, left = -X, right = +X.
  Parallels are drawn only from declared length/width/height and two XY
  centres, top at the seat; they lie below every tool and holder cylinder, so
  they never enter hit counts.
"""

from __future__ import annotations

import base64
import hashlib
import json
import math
import os
import struct
import sys
import tempfile
import zlib

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import FreeCAD  # noqa: E402
import Part  # noqa: E402
from step_faces import FaceRefError, StepError, StepFile  # noqa: E402

UNKNOWN = "unknown"
LIFT = 1e-3  # mm: cylinders shrink radially and lift off the sample by this clearance
GRID = 5  # cell-centred UV samples per face direction
EDGE_SAMPLES = (2, 12)  # per boundary edge
HIT_MM3 = 1e-6  # common volume that counts as an intersection
CONTACT_MM2 = 1e-6  # face/jaw common area that counts as a face inside a jaw
REACH_BAND = 0.05  # mm beyond the cutter radius in which walls set reach depth
AREA_REL = AREA_ABS = 1e-6  # face-signature area tolerance (relative, absolute mm^2)
BBOX_TOL = 1e-4  # mm, face-signature bbox tolerance
PLANE_TOL = 1e-6  # mm, coplanarity of contact faces / interval ends
PARALLEL = 1 - 1e-9  # |cos| beyond which directions are parallel
CONCAVE_PROBE = 1e-2  # mm step used to classify an edge as concave
WALL_LEVELS = 6  # z levels of the thin-wall map
WALL_COLUMNS = (8, 64)  # along-jaw columns of the thin-wall map (1 mm pitch, clamped)
WIDTH, HEIGHT = 640, 480
V = FreeCAD.Vector
Z = V(0, 0, 1)


class _Unknown(Exception):
    """The whole job's facts are unknown for the stated reason."""


def _r(value, digits=6):
    value = float(value)
    if not math.isfinite(value):
        raise ValueError("non-finite measurement")
    value = round(value, digits)
    return 0.0 if value == 0 else value


def _number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _positive(record, key):
    value = record.get(key)
    return float(value) if _number(value) and value > 0 else None


def _bbox(shape):
    box = shape.optimalBoundingBox(True, False)
    return (box.XMin, box.YMin, box.ZMin, box.XMax, box.YMax, box.ZMax)


def _box_shape(box):
    x0, y0, z0, x1, y1, z1 = box
    return Part.makeBox(x1 - x0, y1 - y0, z1 - z0, V(x0, y0, z0))


def _boxes_overlap(a, b):
    return all(a[i] < b[i + 3] - PLANE_TOL and b[i] < a[i + 3] - PLANE_TOL for i in range(3))


def _merged_length(intervals):
    total, end = 0.0, -math.inf
    for lo, hi in sorted(intervals):
        if hi <= end:
            continue
        total += hi - max(lo, end)
        end = hi
    return total


# --------------------------------------------------------------------------- mapping


def _signature(face):
    return type(face.Surface).__name__, face.Area, _bbox(face)


def _matches(a, b):
    return (
        a[0] == b[0]
        and abs(a[1] - b[1]) <= AREA_REL * max(1.0, abs(a[1])) + AREA_ABS
        and all(abs(x - y) <= BBOX_TOL for x, y in zip(a[2], b[2], strict=True))
    )


def _map_faces(step, signatures):
    """Canonical ref -> index for every uniquely matched ADVANCED_FACE, plus errors."""
    owners, errors = {}, {}
    with tempfile.TemporaryDirectory(prefix="prechips-faces-") as directory:
        scratch = os.path.join(directory, "face.step")
        for face in step.faces:
            ref = face.ref
            try:
                text = step.isolate_face(face.entity)
                with open(scratch, "w", encoding="latin-1", newline="") as handle:
                    handle.write(text)
                single = Part.Shape()
                single.read(scratch)
            except Exception as exc:
                errors[ref] = f"{ref}: face reconstruction failed: {exc}"
                continue
            if len(single.Faces) != 1:
                errors[ref] = f"{ref}: reconstructs to {len(single.Faces)} faces, not one"
                continue
            signature = _signature(single.Faces[0])
            candidates = [
                index for index, other in enumerate(signatures) if _matches(signature, other)
            ]
            if not candidates:
                errors[ref] = (
                    f"{ref}: no imported face matches its {signature[0]} surface, "
                    f"area {_r(signature[1])} mm^2 and bounding box"
                )
            elif len(candidates) > 1:
                errors[ref] = (
                    f"{ref}: ambiguous; imported faces {', '.join(map(str, candidates))} "
                    "share its surface kind, area and bounding box"
                )
            else:
                owners.setdefault(candidates[0], []).append(ref)
    mapping = {}
    for index, refs in owners.items():
        if len(refs) == 1:
            mapping[refs[0]] = index
        else:
            for ref in refs:
                errors[ref] = (
                    f"{ref}: ambiguous; ADVANCED_FACEs "
                    f"{', '.join(refs)} all match imported face {index}"
                )
    return mapping, errors


# --------------------------------------------------------------------------- frame


def _frame_matrix(frame):
    if not isinstance(frame, dict):
        return None, "numeric setup frame is unknown"
    vectors = []
    for key in ("origin", "x", "y", "z"):
        value = frame.get(key)
        if not (isinstance(value, list) and len(value) == 3 and all(_number(v) for v in value)):
            return None, f"setup frame {key} is not a numeric 3-vector"
        vectors.append(V(*map(float, value)))
    origin, x, y, z = vectors
    for name, axis in (("x", x), ("y", y), ("z", z)):
        if abs(axis.Length - 1) > 1e-6:
            return None, f"setup frame axis {name} is not a unit vector"
    if max(abs(x.dot(y)), abs(y.dot(z)), abs(z.dot(x))) > 1e-6:
        return None, "setup frame axes are not orthogonal"
    if x.cross(y).dot(z) < 0:
        return None, "setup frame axes are left-handed"
    matrix = FreeCAD.Matrix(
        x.x,
        x.y,
        x.z,
        -x.dot(origin),
        y.x,
        y.y,
        y.z,
        -y.dot(origin),
        z.x,
        z.y,
        z.z,
        -z.dot(origin),
        0,
        0,
        0,
        1,
    )
    return matrix, None


# --------------------------------------------------------------------------- local geometry


def _normal_at(face, point):
    u, v = face.Surface.parameter(point)
    return face.normalAt(u, v)


def _face_samples(face, spacing):
    """(point, outward normal) pairs inside and along the boundary of ``face``."""
    samples, skipped = [], 0
    u0, u1, v0, v1 = face.ParameterRange
    for i in range(GRID):
        u = u0 + (i + 0.5) * (u1 - u0) / GRID
        for j in range(GRID):
            v = v0 + (j + 0.5) * (v1 - v0) / GRID
            if not face.isPartOfDomain(u, v):
                continue
            try:
                samples.append((face.valueAt(u, v), face.normalAt(u, v)))
            except Exception:
                skipped += 1
    for edge in face.Edges:
        if edge.Degenerated or edge.Length < 1e-7:
            continue
        count = min(EDGE_SAMPLES[1], max(EDGE_SAMPLES[0], math.ceil(edge.Length / spacing)))
        first, last = edge.FirstParameter, edge.LastParameter
        for k in range(count):
            point = edge.valueAt(first + (k + 0.5) * (last - first) / count)
            try:
                samples.append((point, _normal_at(face, point)))
            except Exception:
                skipped += 1
    return samples, skipped


def _concave_edge(part, edge, face_a, face_b):
    """True/False for a sharp concave/convex shared edge, None when tangent."""
    middle = edge.valueAt((edge.FirstParameter + edge.LastParameter) / 2)
    na, nb = _normal_at(face_a, middle), _normal_at(face_b, middle)
    split = na - nb
    if split.Length < 1e-6:
        return None
    probe = middle + split.normalize() * CONCAVE_PROBE
    # Air is the intersection of the two half-spaces at a concave edge, their union
    # at a convex one; the probe lies in exactly one half-space.
    return part.isInside(probe, 1e-9, False)


def _half_space(point, normal, size):
    """A cube of edge ``size`` standing on the plane through ``point`` on the side of ``normal``."""
    cube = Part.makeBox(size, size, size, V(-size / 2, -size / 2, 0))
    cube.Placement = FreeCAD.Placement(point, FreeCAD.Rotation(Z, normal))
    return cube


def _edge_material(edge, face_a, face_b, radius):
    """The r-cylinder around a sharp concave line edge minus the air wedge in front of both faces.

    The wedge in front of both faces (n_a.d > 0 and n_b.d > 0) is the open corner, where
    unrelated material such as a pin may stand; only the rest is the faces' own material.
    """
    start, end = edge.Vertexes[0].Point, edge.Vertexes[-1].Point
    middle = edge.valueAt((edge.FirstParameter + edge.LastParameter) / 2)
    cylinder = Part.makeCylinder(radius, (end - start).Length, start, end - start)
    size = 4 * ((end - start).Length + 2 * radius)
    air = _half_space(middle, _normal_at(face_a, middle), size).common(
        _half_space(middle, _normal_at(face_b, middle), size)
    )
    return cylinder.cut(air)


def _edge_direction(edge):
    """'vertical', 'horizontal' or 'skew' with respect to the tool axis."""
    if isinstance(edge.Curve, Part.Line):
        cos = abs(edge.tangentAt(edge.FirstParameter).dot(Z))
        return "vertical" if cos >= PARALLEL else "horizontal" if cos <= 1 - PARALLEL else "skew"
    first, last = edge.FirstParameter, edge.LastParameter
    for k in range(9):
        if abs(edge.tangentAt(first + k * (last - first) / 8).dot(Z)) > 1e-9:
            return "skew"
    return "horizontal"


def _shared_edges(faces, indices):
    """(edge, index_a, index_b) for every edge shared by two of ``indices``."""
    seen = {}
    pairs = []
    for index in indices:
        for edge in faces[index].Edges:
            bucket = seen.setdefault(edge.hashCode(), [])
            for other_index, other in bucket:
                if other_index != index and other.isSame(edge):
                    pairs.append((other, other_index, index))
            bucket.append((index, edge))
    return pairs


def _curved_concave(part, face):
    """Whether any chord between neighbouring UV samples of ``face`` runs through air."""
    u0, u1, v0, v1 = face.ParameterRange
    grid = {}
    for i in range(GRID):
        for j in range(GRID):
            u = u0 + (i + 0.5) * (u1 - u0) / GRID
            v = v0 + (j + 0.5) * (v1 - v0) / GRID
            if face.isPartOfDomain(u, v):
                grid[i, j] = face.valueAt(u, v)
    for (i, j), point in sorted(grid.items()):
        for neighbour in ((i + 1, j), (i, j + 1)):
            other = grid.get(neighbour)
            if other is None:
                continue
            middle = (point + other) * 0.5
            if face.distToShape(Part.Vertex(middle))[0] < 1e-6:
                continue
            if not part.isInside(middle, 1e-9, False):
                return True
    return False


def _cylinder_concave(face):
    surface = face.Surface
    u0, u1, v0, v1 = face.ParameterRange
    u, v = (u0 + u1) / 2, (v0 + v1) / 2
    point, normal = face.valueAt(u, v), face.normalAt(u, v)
    axis = surface.Axis
    foot = surface.Center + axis * (point - surface.Center).dot(axis)
    return normal.dot(foot - point) > 0


def _cylinder_hits_box(cx, cy, radius, z0, z1, box, touching=False):
    """Whether the vertical cylinder meets the axis-aligned box (touching counts if asked)."""
    if (z1 < box[2] or z0 > box[5]) if touching else (z1 <= box[2] or z0 >= box[5]):
        return False
    dx = max(box[0] - cx, 0.0, cx - box[3])
    dy = max(box[1] - cy, 0.0, cy - box[4])
    return dx * dx + dy * dy <= radius * radius if touching else dx * dx + dy * dy < radius * radius


class _Culled:
    """A solid whose vertical-cylinder intersections skip the boolean when no face is near."""

    def __init__(self, shape):
        self.shape = shape
        self.boxes = []
        for face in shape.Faces:
            box = face.optimalBoundingBox(False, True)  # exact, grown by the shape tolerance
            self.boxes.append((box.XMin, box.YMin, box.ZMin, box.XMax, box.YMax, box.ZMax))

    def common(self, cx, cy, radius, z0, z1):
        """The solid's material inside the cylinder, or None when there is none."""
        if not any(_cylinder_hits_box(cx, cy, radius, z0, z1, box, True) for box in self.boxes):
            # No face reaches the cylinder, so it lies wholly inside or wholly outside.
            if not self.shape.isInside(V(cx, cy, (z0 + z1) / 2), 1e-9, False):
                return None
            return Part.makeCylinder(radius, z1 - z0, V(cx, cy, z0))
        common = self.shape.common(Part.makeCylinder(radius, z1 - z0, V(cx, cy, z0)))
        return common if common.Volume > HIT_MM3 else None


# --------------------------------------------------------------------------- PNG


_TOWARD = V(1, -1, 1).normalize()  # camera at front (-Y), right (+X), above (+Z)
_RIGHT = V(1, 1, 0).normalize()
_UP = _RIGHT.cross(-_TOWARD).normalize()
_LIGHT = V(0.4, -0.6, 1.0).normalize()
_COLOURS = {
    "part": (186, 186, 186),
    "claimed": (92, 142, 212),
    "fixed_jaw": (112, 92, 72),
    "moving_jaw": (150, 122, 92),
    "fixed_jaw_possible": (214, 204, 194),  # where the undeclared rest of the jaw may lie
    "moving_jaw_possible": (230, 220, 208),
    "parallel": (96, 120, 104),
}


def _png(width, height, rgb):
    stride = width * 3
    raw = b"".join(b"\x00" + bytes(rgb[row * stride : (row + 1) * stride]) for row in range(height))

    def chunk(tag, data):
        return (
            struct.pack(">I", len(data))
            + tag
            + data
            + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
        )

    header = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", header)
        + chunk(b"IDAT", zlib.compress(raw, 9))
        + chunk(b"IEND", b"")
    )


def _render(meshes):
    """Orthographic z-buffered flat-shaded PNG of (points, triangles, colour) meshes."""
    projected = []
    for points, triangles, colour in meshes:
        screen = [(p.dot(_RIGHT), p.dot(_UP), p.dot(_TOWARD)) for p in points]
        projected.append((points, screen, triangles, colour))
    xs = [s[0] for _, screen, _, _ in projected for s in screen]
    ys = [s[1] for _, screen, _, _ in projected for s in screen]
    rgb = bytearray(b"\xff" * (WIDTH * HEIGHT * 3))
    if not xs:
        return _png(WIDTH, HEIGHT, rgb)
    span = max(max(xs) - min(xs), 1e-9), max(max(ys) - min(ys), 1e-9)
    scale = min(0.92 * WIDTH / span[0], 0.92 * HEIGHT / span[1])
    cx, cy = (max(xs) + min(xs)) / 2, (max(ys) + min(ys)) / 2
    depth = [-math.inf] * (WIDTH * HEIGHT)
    for points, screen, triangles, colour in projected:
        pix = [
            (WIDTH / 2 + (x - cx) * scale, HEIGHT / 2 - (y - cy) * scale, d) for x, y, d in screen
        ]
        for a, b, c in triangles:
            normal = (points[b] - points[a]).cross(points[c] - points[a])
            if normal.Length < 1e-15:
                continue
            shade = 0.3 + 0.7 * abs(normal.normalize().dot(_LIGHT))
            pixel = bytes(min(255, int(channel * shade + 0.5)) for channel in colour)
            _raster(pix[a], pix[b], pix[c], pixel, rgb, depth)
    return _png(WIDTH, HEIGHT, rgb)


def _raster(p0, p1, p2, pixel, rgb, depth):
    (x0, y0, d0), (x1, y1, d1), (x2, y2, d2) = p0, p1, p2
    area = (x1 - x0) * (y2 - y0) - (x2 - x0) * (y1 - y0)
    if abs(area) < 1e-12:
        return
    if area < 0:
        x1, y1, d1, x2, y2, d2 = x2, y2, d2, x1, y1, d1
        area = -area
    # depth plane d = gx*x + gy*y + g0
    gx = ((d1 - d0) * (y2 - y0) - (d2 - d0) * (y1 - y0)) / area
    gy = ((d2 - d0) * (x1 - x0) - (d1 - d0) * (x2 - x0)) / area
    g0 = d0 - gx * x0 - gy * y0
    edges = ((x0, y0, x1, y1), (x1, y1, x2, y2), (x2, y2, x0, y0))
    row_lo = max(0, math.ceil(min(y0, y1, y2) - 0.5))
    row_hi = min(HEIGHT - 1, math.floor(max(y0, y1, y2) - 0.5))
    left_bound, right_bound = min(x0, x1, x2), max(x0, x1, x2)
    for row in range(row_lo, row_hi + 1):
        yc = row + 0.5
        lo, hi = left_bound, right_bound
        for ax, ay, bx, by in edges:
            # inside when (bx-ax)*(yc-ay) - (by-ay)*(x-ax) >= 0
            slope = -(by - ay)
            offset = (bx - ax) * (yc - ay) + (by - ay) * ax
            if slope > 0:
                lo = max(lo, -offset / slope)
            elif slope < 0:
                hi = min(hi, -offset / slope)
            elif offset < 0:
                lo, hi = 1.0, 0.0
        first = max(0, math.ceil(lo - 0.5))
        last = min(WIDTH - 1, math.floor(hi - 0.5))
        base = row * WIDTH
        for column in range(first, last + 1):
            value = gx * (column + 0.5) + gy * yc + g0
            slot = base + column
            if value > depth[slot]:
                depth[slot] = value
                rgb[slot * 3 : slot * 3 + 3] = pixel


# --------------------------------------------------------------------------- job


def run_job(job):
    """Result dict for one job; failures become status error/unknown with a reason."""
    try:
        return _Job(job).run()
    except _Unknown as exc:
        return {"status": UNKNOWN, "reason": str(exc)}
    except Exception as exc:
        return {"status": "error", "reason": f"{type(exc).__name__}: {exc}"}


def run(payload):
    if isinstance(payload, dict) and "jobs" in payload:
        jobs = payload["jobs"]
        if not isinstance(jobs, list):
            return {"status": "error", "reason": "batch 'jobs' is not a list"}
        return {"results": [run_job(job) for job in jobs]}
    return run_job(payload)


class _Job:
    def __init__(self, job):
        if not isinstance(job, dict) or job.get("version") != 1:
            raise ValueError("input is not a version-1 prechips geometry job")
        self.job = job

    def run(self):
        job = self.job
        path, digest = job.get("step_path"), job.get("step_sha256")
        if not isinstance(path, str) or path == UNKNOWN:
            raise _Unknown("STEP path is unknown.")
        if not isinstance(digest, str) or digest == UNKNOWN:
            raise _Unknown("STEP SHA-256 is unknown; face references cannot be bound to the file.")
        with open(path, "rb") as handle:
            data = handle.read()
        actual = hashlib.sha256(data).hexdigest()
        if actual != digest.lower():
            raise ValueError(f"STEP SHA-256 mismatch: job declares {digest}, file has {actual}")
        try:
            step = StepFile(data.decode("latin-1"))
        except StepError as exc:
            raise ValueError(f"STEP is not parseable: {exc}") from None
        shape = Part.Shape()
        shape.read(path)
        solids = shape.Solids
        if len(solids) != 1:
            raise _Unknown(
                f"STEP import yields {len(solids)} solids; "
                "the kernel measures exactly one part solid."
            )
        solid = solids[0]
        if len(shape.Faces) != len(solid.Faces):
            raise _Unknown("STEP import holds faces outside its single solid.")
        if not solid.isValid():
            raise _Unknown(
                "imported solid is not a valid B-rep; booleans on it would be unreliable."
            )
        self.solid = solid
        signatures = [_signature(face) for face in solid.Faces]
        mapping, errors = _map_faces(step, signatures)
        refs_by_index = {index: ref for ref, index in mapping.items()}
        self.labels = [
            refs_by_index.get(index, f"imported face index {index}")
            for index in range(len(signatures))
        ]
        mapping, errors = self._job_refs(step, mapping, errors)
        self.mapping, self.errors = mapping, errors
        self.features = {name: self._feature(value) for name, value in self._declared().items()}
        result = {
            "status": "ok",
            "bbox_mm": [_r(v) for v in _bbox(solid)],
            "faces": [
                {
                    "ref": refs_by_index.get(index),
                    "index": index,
                    "kind": kind,
                    "bbox_mm": [_r(v) for v in box],
                    "area_mm2": _r(area),
                }
                for index, (kind, area, box) in enumerate(signatures)
            ],
            "mapping": dict(sorted(mapping.items())),
            "mapping_errors": dict(sorted(errors.items())),
            "features": self.features,
            "ops": {},
            "setups": {},
        }
        setups = job.get("setups", [])
        if not isinstance(setups, list):
            raise ValueError("job setups is not a list")
        for setup in setups:
            facts, ops = _Setup(self, setup).run()
            result["setups"][str(setup.get("id"))] = facts
            result["ops"].update(ops)
        return result

    def _declared(self):
        features = self.job.get("features", {})
        return features if isinstance(features, dict) else {}

    def _job_refs(self, step, mapping, errors):
        refs = []
        for value in list(self._declared().values()) + [self.job.get("as_is_faces")]:
            if isinstance(value, list):
                refs.extend(ref for ref in value if isinstance(ref, str) and ref != UNKNOWN)
        mapping, errors = dict(mapping), dict(errors)
        for ref in refs:
            if ref in mapping or ref in errors:
                continue
            try:
                canonical = step.resolve(ref).ref
            except FaceRefError as exc:
                errors[ref] = str(exc)
                continue
            if canonical in mapping:
                mapping[ref] = mapping[canonical]
            else:
                errors[ref] = errors.get(canonical, f"{ref}: not mapped")
        return mapping, errors

    def _feature(self, refs):
        if not isinstance(refs, list) or not all(isinstance(ref, str) for ref in refs):
            return UNKNOWN
        if any(ref == UNKNOWN or ref not in self.mapping for ref in refs):
            return UNKNOWN
        return sorted({self.mapping[ref] for ref in refs})


class _Setup:
    def __init__(self, owner, setup):
        self.owner = owner
        self.setup = setup if isinstance(setup, dict) else {}
        self.ops = [op for op in self.setup.get("ops", []) if isinstance(op, dict)]
        self.reasons = {}
        self.part = None
        # certain jaw boxes {"fixed", "moving"} plus "possible": [(fixed side?, box)] once placed
        self.jaws = None
        self.hold = None  # the vise hold, once it is declared without a reason
        self.fixture_reason = None
        self.regions = {}
        self.culled_part = None

    # ------------------------------------------------------------------ setup facts

    def run(self):
        matrix, frame_reason = _frame_matrix(self.setup.get("frame"))
        facts = {
            "fixture_rendered": False,
            "parallel_pair": UNKNOWN,
            "width_mm": UNKNOWN,
            "contact_grip_mm": UNKNOWN,
            "claimed_in_jaws": UNKNOWN,
            "min_wall_mm": UNKNOWN,
            "reasons": {},
        }
        if matrix is not None:
            part = self.owner.solid.copy()
            try:
                part.transformShape(matrix)
            except Exception as exc:
                matrix, frame_reason = None, f"setup frame transform failed: {exc}"
            else:
                self.part = part
                self.faces = part.Faces
                self.box = _bbox(part)
                self.face_boxes = self._culled_part().boxes
        if matrix is None:
            facts["reason"] = frame_reason
            facts["fixture_reason"] = frame_reason
            for key in (
                "parallel_pair",
                "width_mm",
                "contact_grip_mm",
                "claimed_in_jaws",
                "min_wall_mm",
            ):
                facts["reasons"][key] = frame_reason
            ops = {self._subject(op): self._op_unknown(op, frame_reason) for op in self.ops}
            return facts, ops
        self._vise(facts)
        ops = {self._subject(op): self._op(op) for op in self.ops}
        png, scene = self._render()
        facts["render_png_base64"] = base64.b64encode(png).decode("ascii")
        facts["render_scene"] = scene
        facts["fixture_rendered"] = scene["jaws"] != "absent" and not scene["debts"]
        if self.fixture_reason is not None:
            facts["fixture_reason"] = self.fixture_reason
        unknown = [facts["reasons"][key] for key in sorted(facts["reasons"])]
        if self.fixture_reason is not None:
            facts["reason"] = self.fixture_reason
        elif unknown:
            facts["reason"] = unknown[0]
        return facts, ops

    @staticmethod
    def _subject(op):
        return str(op.get("subject"))

    def _claimed(self):
        """Indices claimed by this setup's ops, or the reason they are not all known."""
        indices, missing = set(), []
        for op in self.ops:
            value = self.owner.features.get(op.get("feature"), UNKNOWN)
            if value == UNKNOWN:
                missing.append(self._subject(op))
            else:
                indices.update(value)
        if missing:
            return None, "claimed faces unknown or unmapped for " + ", ".join(missing)
        return sorted(indices), None

    def _vise(self, facts):
        hold = self.setup.get("hold")
        reasons = facts["reasons"]
        reason = None
        if not isinstance(hold, dict):
            reason = "holding inputs are unknown"
        elif hold.get("reason"):
            reason = str(hold["reason"])
        elif hold.get("kind") != "vise":
            reason = "Fixture solids are not declared for this holding kind."
        else:
            self.hold = hold
            reason = self._place(hold, facts)
        if reason is not None:
            self.fixture_reason = reason
            for key in (
                "parallel_pair",
                "width_mm",
                "contact_grip_mm",
                "claimed_in_jaws",
                "min_wall_mm",
            ):
                if facts[key] == UNKNOWN:
                    reasons.setdefault(key, reason)

    def _place(self, hold, facts):
        along = hold.get("jaws_along")
        if along not in ("x", "y"):
            return f"jaws_along {along!r} is not x or y"
        sides = {"x": {"rear": 1, "back": 1, "front": -1}, "y": {"right": 1, "left": -1}}[along]
        fixed = hold.get("fixed_jaw")
        if fixed not in sides:
            return (
                f"fixed_jaw {fixed!r} is not a side of the "
                f"{'y' if along == 'x' else 'x'} clamp axis"
            )
        above = hold.get("jaw_above_parallels_mm")
        if not (_number(above) and above >= 0):
            return "jaw_above_parallels_mm is unknown"
        dims = {
            key: _positive(hold, key) for key in ("jaw_height_mm", "jaw_width_mm", "jaw_depth_mm")
        }
        missing = sorted(key for key, value in dims.items() if value is None)
        if missing:
            return "Fixture pose/dimensions unmeasured or unavailable: " + ", ".join(missing)
        a_axis, c_axis = (0, 1) if along == "x" else (1, 0)
        sign = sides[fixed]
        width, depth, height = dims["jaw_width_mm"], dims["jaw_depth_mm"], dims["jaw_height_mm"]
        centre = hold.get("jaw_center_along_mm")
        if centre is not None and centre != UNKNOWN and not _number(centre):
            return f"jaw_center_along_mm {centre!r} is not a number"
        exact = _number(centre)
        xmin, ymin, seat, xmax, ymax, ztop = self.box
        top = seat + above
        facts["jaw_zone_z_mm"] = [_r(seat), _r(top)]
        zone = None
        if above > 0:
            corner, size = [xmin - 1, ymin - 1, seat], [xmax - xmin + 2, ymax - ymin + 2, above]
            if exact:
                corner[a_axis], size[a_axis] = centre - width / 2, width
            zone = self.part.common(Part.makeBox(*size, V(*corner)))
        if zone is None or zone.Volume <= HIT_MM3:
            facts["contact_grip_mm"] = [0.0, 0.0]
            if above > 0:
                return (
                    f"no part material lies between the jaws (jaw_center_along_mm {_r(centre)}, "
                    f"jaw_width_mm {_r(width)}), so jaw positions are undefined"
                )
            return (
                "jaws stand 0 mm above the part seat; no part material lies between the "
                "jaws, so jaw positions are undefined"
            )
        zb = _bbox(zone)
        lo, hi = zb[c_axis], zb[c_axis + 3]
        a_lo, a_hi = zb[a_axis], zb[a_axis + 3]
        if not exact and a_hi - a_lo > width + PLANE_TOL:
            return (
                f"part spans {_r(a_hi - a_lo)} mm along {along} inside the jaw zone, "
                f"more than jaw_width_mm {_r(width)}; the jaw position along {along} is "
                "undeclared, so jaws are not placed"
            )

        def box(a0, a1, c0, c1):
            lo_corner, hi_corner = [0.0, 0.0], [0.0, 0.0]
            lo_corner[a_axis], hi_corner[a_axis] = a0, a1
            lo_corner[c_axis], hi_corner[c_axis] = c0, c1
            return (lo_corner[0], lo_corner[1], top - height, hi_corner[0], hi_corner[1], top)

        high, low = (hi, hi + depth), (lo - depth, lo)
        fixed_c, moving_c = (high, low) if sign > 0 else (low, high)
        jaw_a = (centre - width / 2, centre + width / 2) if exact else (a_lo, a_hi)
        self.jaws = {
            "fixed": box(*jaw_a, *fixed_c),
            "moving": box(*jaw_a, *moving_c),
            "possible": [],
        }
        spare = width - (a_hi - a_lo)
        if not exact and spare > PLANE_TOL:
            for c_range in (fixed_c, moving_c):
                self.jaws["possible"].append(
                    (c_range is fixed_c, box(a_lo - spare, a_lo, *c_range))
                )
                self.jaws["possible"].append(
                    (c_range is fixed_c, box(a_hi, a_hi + spare, *c_range))
                )
        self.clamp = {
            "along": along,
            "a_axis": a_axis,
            "c_axis": c_axis,
            "lo": lo,
            "hi": hi,
            "a_lo": a_lo,
            "a_hi": a_hi,
            "seat": seat,
            "top": top,
            "jaw_a": jaw_a,
            "exact": exact,
        }
        facts["width_mm"] = _r(hi - lo)
        planes = {"fixed": hi if sign > 0 else lo, "moving": lo if sign > 0 else hi}
        outward = {"fixed": sign, "moving": -sign}
        grips, planar, contact_faces = [], [], {}
        for side in ("fixed", "moving"):
            intervals, labels = self._contact(zone, c_axis, planes[side], outward[side], seat, top)
            planar.append(bool(intervals))
            contact_faces[side] = labels
            if not intervals:
                intervals = self._line_contact(zone, c_axis, planes[side])
            grips.append(_r(_merged_length(intervals)))
        facts["parallel_pair"] = all(planar)
        facts["contact_grip_mm"] = grips
        facts["contact_faces"] = contact_faces
        claimed, reason = self._claimed()
        if claimed is None:
            facts["reasons"]["claimed_in_jaws"] = reason
        else:
            facts["claimed_in_jaws"] = self._in_jaws(claimed)
        self._walls(facts)
        return None

    def _contact(self, zone, c_axis, plane, outward, seat, top):
        """z-intervals of planar zone faces on the jaw plane, and the part faces they come from."""
        intervals = []
        for face in zone.Faces:
            if not isinstance(face.Surface, Part.Plane):
                continue
            box = _bbox(face)
            if box[c_axis + 3] - box[c_axis] > PLANE_TOL or abs(box[c_axis] - plane) > PLANE_TOL:
                continue
            u0, u1, v0, v1 = face.ParameterRange
            normal = face.normalAt((u0 + u1) / 2, (v0 + v1) / 2)
            if normal[c_axis] * outward < PARALLEL or face.Area <= CONTACT_MM2:
                continue
            intervals.append((box[2], box[5]))
        labels = []
        a_axis, (a0, a1) = self.clamp["a_axis"], self.clamp["jaw_a"]
        for index, face in enumerate(self.faces):
            if not isinstance(face.Surface, Part.Plane):
                continue
            box = _bbox(face)
            if box[c_axis + 3] - box[c_axis] > PLANE_TOL or abs(box[c_axis] - plane) > PLANE_TOL:
                continue
            if box[5] <= seat or box[2] >= top or box[a_axis + 3] <= a0 or box[a_axis] >= a1:
                continue
            labels.append(self.owner.labels[index])
        return intervals, sorted(labels) if intervals else []

    def _line_contact(self, zone, c_axis, plane):
        size = (
            4 * max(self.box[3] - self.box[0], self.box[4] - self.box[1], self.box[5] - self.box[2])
            + 10
        )
        corner = [self.box[0] - size / 4, self.box[1] - size / 4, self.box[2] - size / 4]
        corner[c_axis] = plane
        # Explicit in-plane x so both plane directions run positive from ``corner``.
        normal, xdir = (V(1, 0, 0), V(0, 1, 0)) if c_axis == 0 else (V(0, 1, 0), V(0, 0, 1))
        section = zone.section(Part.makePlane(size, size, V(*corner), normal, xdir))
        return [(_bbox(edge)[2], _bbox(edge)[5]) for edge in section.Edges]

    def _jaw_shapes(self):
        return [(side + "_jaw", _box_shape(self.jaws[side])) for side in ("fixed", "moving")]

    def _in_jaws(self, claimed):
        inside = []
        jaws = self._jaw_shapes()
        for index in claimed:
            face = self.faces[index]
            for _, jaw in jaws:
                if face.BoundBox.intersect(jaw.BoundBox) and face.common(jaw).Area > CONTACT_MM2:
                    inside.append(self.owner.labels[index])
                    break
        return sorted(inside)

    def _walls(self, facts):
        clamp = self.clamp
        a_axis, c_axis = clamp["a_axis"], clamp["c_axis"]
        length = clamp["a_hi"] - clamp["a_lo"]
        columns = min(WALL_COLUMNS[1], max(WALL_COLUMNS[0], math.ceil(length)))
        rows = []
        thinnest = None
        for i in range(columns):
            a = clamp["a_lo"] + (i + 0.5) * length / columns
            for j in range(WALL_LEVELS):
                z = clamp["seat"] + (j + 0.5) * (clamp["top"] - clamp["seat"]) / WALL_LEVELS
                start, end = [0.0, 0.0, z], [0.0, 0.0, z]
                start[a_axis] = end[a_axis] = a
                start[c_axis], end[c_axis] = clamp["lo"] - 1, clamp["hi"] + 1
                line = Part.LineSegment(V(*start), V(*end)).toShape()
                intervals = []
                for edge in line.common(self.part).Edges:
                    ends = sorted(vertex.Point[c_axis] for vertex in edge.Vertexes)
                    if ends[-1] - ends[0] > PLANE_TOL:
                        intervals.append([ends[0], ends[-1]])
                intervals.sort()
                loaded = (
                    bool(intervals)
                    and abs(intervals[0][0] - clamp["lo"]) <= 1e-3
                    and abs(intervals[-1][1] - clamp["hi"]) <= 1e-3
                )
                if loaded:
                    for lo, hi in intervals:
                        thinnest = hi - lo if thinnest is None else min(thinnest, hi - lo)
                rows.append(
                    {
                        "along_mm": _r(a),
                        "z_mm": _r(z),
                        "loaded": loaded,
                        "intervals_mm": [[_r(lo), _r(hi)] for lo, hi in intervals],
                    }
                )
        facts["wall_map"] = {"axis": "y" if c_axis == 1 else "x", "lines": rows}
        if thinnest is None:
            facts["reasons"]["min_wall_mm"] = (
                "no sampled clamp line meets material at both jaw contact planes"
            )
        else:
            facts["min_wall_mm"] = _r(thinnest)

    def _render(self):
        """PNG of the part (claimed faces tinted) and the declared fixture, and its debts."""
        claimed = set()
        for op in self.ops:
            value = self.owner.features.get(op.get("feature"), UNKNOWN)
            if value != UNKNOWN:
                claimed.update(value)
        size = max(self.box[3] - self.box[0], self.box[4] - self.box[1], self.box[5] - self.box[2])
        tolerance = max(0.01, size / 400)
        meshes = []
        for index, face in enumerate(self.faces):
            points, triangles = face.tessellate(tolerance)
            meshes.append((points, triangles, _COLOURS["claimed" if index in claimed else "part"]))
        debts, solids = [], []
        if self.jaws is None:
            jaws = "absent"
            debts.append(f"jaws not drawn: {self.fixture_reason}")
        else:
            solids += self._jaw_shapes()
            jaws = "exact" if self.clamp["exact"] else "lateral_undeclared"
            if jaws != "exact":
                clamp = self.clamp
                extent = clamp["a_hi"] - clamp["a_lo"]
                width = self.hold["jaw_width_mm"]
                debts.append(
                    f"jaw position along {clamp['along']} is undeclared "
                    "(no jaw_center_along_mm): dark jaws span only the part's "
                    f"{_r(extent)} mm grip-zone extent; light strips show where the "
                    f"other {_r(width - extent)} mm of each {_r(width)} mm jaw may lie"
                )
                solids += [
                    (("fixed" if fixed else "moving") + "_jaw_possible", _box_shape(box))
                    for fixed, box in self.jaws["possible"]
                ]
        parallels, debt = self._parallels()
        if debt is not None:
            debts.append(debt)
        for box in parallels or ():
            solids.append(("parallel", _box_shape(box)))
            for side in ("fixed", "moving") if self.jaws is not None else ():
                if _boxes_overlap(box, self.jaws[side]):
                    centre = [_r((box[0] + box[3]) / 2), _r((box[1] + box[4]) / 2)]
                    debts.append(f"declared parallel centred at {centre} intersects the {side} jaw")
        for label, shape in solids:
            points, triangles = shape.tessellate(tolerance)
            meshes.append((points, triangles, _COLOURS[label]))
        scene = {
            "jaws": jaws,
            "parallels": "absent"
            if self.hold is None
            else "exact"
            if parallels
            else "not_modelled",
            "debts": debts,
        }
        return _render(meshes), scene

    def _parallels(self):
        """Parallel boxes from declared dimensions and centres, or the debt that prevents them."""
        hold = self.hold
        if hold is None:
            return None, None
        dims = {
            key: _positive(hold, key)
            for key in ("parallels_height_mm", "parallels_length_mm", "parallels_width_mm")
        }
        missing = sorted(key for key, value in dims.items() if value is None)
        centres = hold.get("parallels_centres_mm")
        if not (
            isinstance(centres, list)
            and len(centres) == 2
            and all(
                isinstance(xy, list) and len(xy) == 2 and all(_number(v) for v in xy)
                for xy in centres
            )
        ):
            missing.append("parallels_centres_mm")
        along = hold.get("jaws_along")
        if along not in ("x", "y"):
            missing.append("jaws_along")
        if missing:
            return None, "parallels not drawn: " + ", ".join(missing) + " undeclared"
        seat = self.box[2]
        half = [dims["parallels_length_mm"] / 2, dims["parallels_width_mm"] / 2]
        if along == "y":
            half.reverse()
        boxes = [
            (
                x - half[0],
                y - half[1],
                seat - dims["parallels_height_mm"],
                x + half[0],
                y + half[1],
                seat,
            )
            for x, y in centres
        ]
        return boxes, None

    # ------------------------------------------------------------------ op facts

    def _op_unknown(self, op, reason):
        facts = {"reason": reason, "reasons": {}}
        for key in (
            "sample_count",
            "tool_hits",
            "holder_hits",
            "reach_depth_mm",
            "holder_wall_hits",
            "corner_radii_mm",
        ):
            facts[key] = UNKNOWN
            facts["reasons"][key] = reason
        return facts

    def _op(self, op):
        owner = self.owner
        name = op.get("feature")
        declared = owner._declared()
        refs = declared.get(name, UNKNOWN) if isinstance(name, str) else UNKNOWN
        if not isinstance(name, str) or name not in declared:
            return self._op_unknown(op, f"feature {name!r} is not declared")
        if not isinstance(refs, list):
            return self._op_unknown(op, f"feature {name!r} face references are unknown")
        invalid = sorted({ref for ref in refs if ref in owner.errors})
        if invalid:
            facts = self._op_unknown(
                op,
                f"feature {name!r} has invalid or unmapped face reference(s): "
                + ", ".join(invalid),
            )
            facts["mapping_errors"] = invalid
            return facts
        indices = owner.features.get(name, UNKNOWN)
        if indices == UNKNOWN or not indices:
            return self._op_unknown(op, f"feature {name!r} face references are unknown")
        facts = {"reasons": {}}
        reasons = facts["reasons"]
        corner = self._corners(indices)
        facts["corner_radii_mm"] = corner if isinstance(corner, list) else UNKNOWN
        if not isinstance(corner, list):
            reasons["corner_radii_mm"] = corner
        radius = _positive(op, "radius_mm")
        if radius is None:
            for key in (
                "sample_count",
                "tool_hits",
                "holder_hits",
                "reach_depth_mm",
                "holder_wall_hits",
            ):
                facts[key] = UNKNOWN
                reasons[key] = "op lacks a measured cutter radius_mm"
        else:
            self._sample_facts(op, indices, radius, facts)
        unknown = [
            reasons[key]
            for key in (
                "sample_count",
                "tool_hits",
                "holder_hits",
                "reach_depth_mm",
                "holder_wall_hits",
                "corner_radii_mm",
            )
            if key in reasons
        ]
        if unknown:
            facts["reason"] = unknown[0]
        return facts

    def _corners(self, indices):
        """Sorted concave corner radii around the tool axis, or the reason they are unknown."""
        part, faces, labels = self.part, self.faces, self.owner.labels
        radii, problems = set(), []
        for index in indices:
            face = faces[index]
            surface = face.Surface
            if isinstance(surface, Part.Plane):
                continue
            if isinstance(surface, Part.Cylinder):
                if not _cylinder_concave(face):
                    continue
                if abs(surface.Axis.dot(Z)) >= PARALLEL:
                    radii.add(_r(surface.Radius))
                else:
                    problems.append(
                        f"{labels[index]} is a concave cylinder whose axis is not the tool axis"
                    )
                continue
            if _curved_concave(part, face):
                problems.append(f"{labels[index]} is a concave {type(surface).__name__} surface")
        for edge, a, b in _shared_edges(faces, indices):
            direction = _edge_direction(edge)
            if direction == "horizontal":
                continue
            concave = _concave_edge(part, edge, faces[a], faces[b])
            if not concave:
                continue
            if direction == "vertical":
                radii.add(0.0)
            else:
                problems.append(
                    f"concave edge between {labels[a]} and {labels[b]} is oblique to the tool axis"
                )
        if problems:
            extra = f" (+{len(problems) - 3} more)" if len(problems) > 3 else ""
            return "; ".join(problems[:3]) + extra
        return sorted(radii)

    def _region(self, indices, radius):
        """Part material within ``radius`` of the claimed faces (own-feature exclusion)."""
        key = (tuple(indices), radius)
        if key in self.regions:
            return self.regions[key]
        faces, labels = self.faces, self.owner.labels
        pieces = []
        for index in indices:
            try:
                slab = Part.Shell([faces[index]]).makeOffsetShape(
                    -radius, 1e-6, False, False, 0, 0, True
                )
                if slab.Volume <= HIT_MM3 or not slab.isValid():
                    raise ValueError("empty or invalid offset solid")
            except Exception as exc:
                self.regions[key] = (
                    None,
                    f"own-feature region: offsetting {labels[index]} by {_r(radius)} mm "
                    f"into material failed ({exc})",
                )
                return self.regions[key]
            pieces.append(slab)
        for edge, a, b in _shared_edges(faces, indices):
            if not isinstance(edge.Curve, Part.Line) or not _concave_edge(
                self.part, edge, faces[a], faces[b]
            ):
                continue
            pieces.append(_edge_material(edge, faces[a], faces[b], radius))
        try:
            region = pieces[0].fuse(pieces[1:]) if len(pieces) > 1 else pieces[0]
            obstacle = self.part.cut(region)
        except Exception as exc:
            self.regions[key] = (None, f"own-feature region boolean failed ({exc})")
            return self.regions[key]
        self.regions[key] = (_Culled(obstacle), None)
        return self.regions[key]

    def _sample_facts(self, op, indices, radius, facts):
        reasons = facts["reasons"]
        samples, skipped = [], 0
        for index in indices:
            found, missed = _face_samples(self.faces[index], max(radius, 1.0))
            samples.extend((index, point, normal) for point, normal in found)
            skipped += missed
        facts["sample_count"] = len(samples)
        if skipped:
            reasons["sample_count"] = f"{skipped} sample point(s) had no defined surface normal"
        flute = _positive(op, "flute_len_mm")
        keys = ("holder_radius_mm", "holder_gauge_len_mm", "projection_mm")
        holder = {key: _positive(op, key) for key in keys}
        holder_missing = sorted(key for key, value in holder.items() if value is None)
        placed = []  # (index, point, axis x, axis y, tip z, downward)
        for index, point, normal in samples:
            horizontal = math.hypot(normal.x, normal.y)
            ax, ay = point.x, point.y
            if horizontal > 1e-9:
                ax += radius * normal.x / horizontal
                ay += radius * normal.y / horizontal
            placed.append((index, point, ax, ay, point.z + LIFT, normal.z < -1e-3))
        top = self.box[5]
        part = self._culled_part()
        # Reach: highest material within r + band of the tool axis above each sample.
        reach = 0.0
        for _, point, ax, ay, tip, downward in sorted(
            placed, key=lambda item: (item[1].z, item[0], item[2], item[3])
        ):
            if downward:
                continue
            if top - point.z <= reach:
                break
            common = part.common(ax, ay, radius + REACH_BAND, tip, top + 1.0)
            if common is not None:
                reach = max(reach, _bbox(common)[5] - point.z)
        facts["reach_depth_mm"] = _r(reach)
        if holder_missing:
            facts["holder_wall_hits"] = UNKNOWN
            reasons["holder_wall_hits"] = "op lacks " + ", ".join(holder_missing)
        else:
            facts["holder_wall_hits"] = sum(
                1
                for _, _, ax, ay, tip, downward in placed
                if not downward and part.common(*self._holder(ax, ay, tip, holder)) is not None
            )
        obstacle, region_reason = self._region(indices, radius)
        tool_ready = flute is not None and obstacle is not None
        holder_ready = not holder_missing and obstacle is not None
        # per kind: certain hits, hits only in the undeclared jaw extension, labels, refs
        counters = {"tool": [0, 0, set(), set()], "holder": [0, 0, set(), set()]}
        own = set(indices)
        for _, _, ax, ay, tip, downward in placed if obstacle is not None else ():
            checks = []
            if tool_ready:
                checks.append(("tool", (ax, ay, radius - LIFT, tip, tip + flute)))
            if holder_ready:
                checks.append(("holder", self._holder(ax, ay, tip, holder)))
            for kind, cylinder in checks:
                counter = counters[kind]
                if downward:
                    if kind == "tool":
                        counter[0] += 1
                        counter[2].add("part")
                    continue
                labels = set()
                common = obstacle.common(*cylinder)
                if common is not None:
                    labels.add("part")
                    counter[3].update(self._hit_refs(common, cylinder, own))
                if self.jaws is not None:
                    for side in ("fixed", "moving"):
                        if _cylinder_hits_box(*cylinder, self.jaws[side]):
                            labels.add(side + "_jaw")
                if labels:
                    counter[0] += 1
                    counter[2].update(labels)
                elif self.jaws is None or any(
                    _cylinder_hits_box(*cylinder, box) for _, box in self.jaws["possible"]
                ):
                    counter[1] += 1
        facts["obstacles"] = {kind: sorted(counters[kind][2]) for kind in counters}
        facts["hit_refs"] = {kind: sorted(counters[kind][3]) for kind in counters}
        facts["min_hits"] = {}
        holder_reason = (
            ("op lacks " + ", ".join(holder_missing)) if holder_missing else region_reason
        )
        for kind, ready, missing in (
            ("tool", tool_ready, "op lacks flute_len_mm" if flute is None else region_reason),
            ("holder", holder_ready, holder_reason),
        ):
            key = kind + "_hits"
            certain, uncertain = counters[kind][0], counters[kind][1]
            if not ready:
                facts[key] = UNKNOWN
                reasons[key] = missing
                continue
            facts["min_hits"][kind] = certain
            if self.jaws is None:
                facts[key] = UNKNOWN
                reasons[key] = (
                    f"fixture solids unresolved ({self.fixture_reason}); "
                    f"{certain} sample(s) hit part material"
                )
            elif uncertain:
                facts[key] = UNKNOWN
                reasons[key] = (
                    f"{uncertain} sample(s) clear of the part and placed jaws reach the undeclared "
                    f"jaw extension along {self.clamp['along']}; {certain} sample(s) certainly hit"
                )
            else:
                facts[key] = certain

    @staticmethod
    def _holder(ax, ay, tip, holder):
        bottom = tip + holder["projection_mm"]
        return (
            ax,
            ay,
            holder["holder_radius_mm"] - LIFT,
            bottom,
            bottom + holder["holder_gauge_len_mm"],
        )

    def _culled_part(self):
        if self.culled_part is None:
            self.culled_part = _Culled(self.part)
        return self.culled_part

    def _hit_refs(self, common, cylinder, own):
        """Labels of non-claimed faces that bound the hit material inside the cylinder."""
        refs = set()
        solid = None
        for index, face in enumerate(self.faces):
            if index in own or not _cylinder_hits_box(*cylinder, self.face_boxes[index], True):
                continue
            if solid is None:
                ax, ay, radius, z0, z1 = cylinder
                solid = Part.makeCylinder(radius, z1 - z0, V(ax, ay, z0))
            if common.distToShape(face)[0] < 1e-6 and face.common(solid).Area > CONTACT_MM2:
                refs.add(self.owner.labels[index])
        return refs


def main(argv):
    args = argv[argv.index("--") + 1 :] if "--" in argv else []
    if len(args) != 2:
        raise SystemExit("usage: freecadcmd freecad_job.py -- INPUT_JSON OUTPUT_JSON")
    source, target = args
    try:
        with open(source, encoding="utf-8") as handle:
            payload = json.load(handle)
    except (OSError, ValueError) as exc:
        result = {"status": "error", "reason": f"kernel job input unreadable: {exc}"}
    else:
        result = run(payload)
    text = json.dumps(result, sort_keys=True, separators=(",", ":"), allow_nan=False)
    with open(target, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(text)


if __name__ in {"__main__", "freecad_job"}:
    main(sys.argv)
