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
  offset by r along the horizontal outward normal on walls. By user decision
  2026-10-05, concave floor-edge samples instead shift r into the floor; two-wall
  floor corners use the axis tangent to both. Convex edges and interior samples
  are unchanged. Rough tips stand at their authored to_z when above the finished
  face, and hole tools follow their geometry-matched axis to their declared depth
  or through extent. Spot/drill flutes use their point cone plus full-radius body;
  flat tools use an r x flute_len cylinder. The holder starts at tip + projection.
  Both shrink/lift by ``LIFT``.
  Far-side faces cannot be claimed from that setup; undefined normals remain debt.
* Obstacles: setup-entry stock minus the sampled face's ``LIFT``-thick inward
  shell, plus placed fixture solids. A hole's known matched cap keeps unmodified stock instead
  of an unrepresentable apex shell. The flute alone excludes its own actual cut.
  Unrelated finished features remain obstacles, and holders retain all entry-stock
  obstacles. A hole's own bore radius is sizing, not a corner.
  Supply and earlier setups' removals determine the held stock and holder/reach
  obstacles. A rough mill op's ``rough_allowance_mm`` leave moves its poses along the unit
  normal (floor-edge limits r + a) and stays in derived stock; authored clearing boxes
  are multipass volumes, clipped to the stock, not limited to the claims' footprint.
* Modelled placement only: each sample gets one prescribed tool pose, so a hit
  means that pose collides, not that no other pose reaches the face.
* Vise: stock seated at its lowest z; jaw zone z in [seat, seat +
  jaw_above_parallels], limited along ``jaws_along`` to the jaw span when
  ``jaw_center_along_mm`` declares it; inner jaw planes at the zone material's
  extremes along the clamp axis; jaw boxes jaw_width along ``jaws_along``
  (centred on the declared centre, else certainly over the zone material's
  extent and possibly up to jaw_width beyond it), jaw_depth outward, jaw_height
  down from the jaw top; rear/back = +Y, front = -Y, left = -X, right = +X.
  Parallels are drawn only from declared length/width/height and two XY
  centres, top at the seat; they lie below every tool and holder cylinder, so
  they never enter hit counts.
* Turning (ops with ``approach = "turning"``; lathe setups): the spindle axis is
  setup Z through x = y = 0, +Z from the chuck toward the free end.  Claimable
  faces are surfaces of revolution about it (every sampled normal lies in its
  meridian plane, within ``REVOLVED_TOL``); a face whose normals point toward
  the axis is internal turning (boring bar), which is not modelled.  Samples
  collapse to distinct (r, z) meridian points (plus a dome's pole on the axis);
  a ``to_z`` op is posed across its claims' radii on the to_z plane it leaves.
  The tool is its centre-height (y = 0) section in the XZ half-plane, revolved
  360 degrees about Z because the work turns: an insert (nose circle radius r_e
  lifted ``LIFT`` off its pose, major edge at the entering angle to the feed,
  minor edge closing the insert angle, both edge_len long), a head (convex hull
  of insert and shank start head_len out from the nose centre), a radial shank
  shank_width wide whose back face lies functional_width from the nose centre
  against the feed, out to projection, and the toolpost body behind it
  (body_depth radially, body_width from the shank's leading face against the
  feed).  A grooving/parting blade (``corners = 2``, entering angle 90) has
  two r_e corners on a square front edge ``blade_width_mm`` wide, its sides
  running straight back to head_len.  Insert/blade/holder thickness above and
  below centre height and blade side clearance are not modelled.  Obstacles
  are the profile after the op, the held stock minus the revolved removals of
  the setup's turning ops up to and including this one (final-pass states;
  roughing passes are not simulated), plus placed fixture solids.  Poses are
  chosen on that profile's meridian section (``MERIDIAN_AZIMUTH``): an
  insert's nose tangent at the sample; a blade's front edge on a radial-normal
  sample anywhere that keeps the sample under the edge and the blade clear
  (inside its groove: floor spans narrower than the blade are swept by that
  plunge), any other sample cut by the nearest corner.  A nose/blade meeting
  the profile at an exposed sample moves to the nearest clear pose within 2 r_e
  (``POSE_SEARCH``): tangent to both segments of a concave corner, offset by
  r_e, so a corner sharper than the nose is a ``corner_radii_mm`` fact, not a
  collision.  Flank, head and holder hits stay hits.  Turned removal sweeps
  each claimed meridian radially outward (facing actions: along +Z, bounded by
  to_z; a facing op, part-off or cut-to-fit given to_dia, from to_dia/2 to the stock
  end, a part-off's default the axis, never a bore inferred from the finished
  part), extended at the profile's end radius over the declared z_from..z_to
  span and limited to it, minus the finished part.
  Reach depth is the material radius beside the nose/blade (z within its axial
  extent, r beyond the sample).  Concave profile corners are sharp concave
  edges between claimed faces (0) and concave tori/spheres (their profile
  radius).  Chuck grip-zone walls are radial lines through each jaw: the
  material run starting at the jaw contact.  The result is a deterministic
  sampled screen: it proves no tool path, chip flow, cutting load or chatter.
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
import time
from contextlib import contextmanager
import zlib

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import FreeCAD  # noqa: E402
import Part  # noqa: E402
from step_faces import FaceRefError, StepError, StepFile  # noqa: E402

UNKNOWN = "unknown"
LIFT = 1e-3  # mm: cylinders shrink radially and lift off the sample by this clearance
GRID = 5  # cell-centred UV samples per face direction
EDGE_SAMPLES = (2, 12)  # per boundary edge
AWAY = -1e-3  # outward normal z below which a face points away from the tool approach
HIT_MM3 = 1e-6  # common volume that counts as an intersection
STOCK_TOL = 1e-3  # mm: as-is face distance to the envelope, claimed-face contact
COVER_MM = 0.01  # mm outside a claimed face where remaining stock means it is not cleared
STOCK_MM3 = 1e-3  # mm^3: finished material outside the envelope, or a detached stock piece
CONTACT_MM2 = 1e-6  # face/jaw common area that counts as a face inside a jaw
REACH_BAND = 0.05  # mm beyond the cutter radius in which walls set reach depth
FACING_ACTIONS = {"face", "rough_face", "finish_face"}  # sweeps that span planar inner loops
AREA_REL = AREA_ABS = 1e-6  # face-signature area tolerance (relative, absolute mm^2)
BBOX_TOL = 1e-4  # mm, face-signature bbox tolerance
PLANE_TOL = 1e-6  # mm, coplanarity of contact faces / interval ends
PARALLEL = 1 - 1e-9  # |cos| beyond which directions are parallel
CONCAVE_PROBE = 1e-2  # mm step used to classify an edge as concave
WALL_LEVELS = 6  # z levels of the thin-wall map
WALL_COLUMNS = (8, 64)  # along-jaw columns of the thin-wall map (1 mm pitch, clamped)
STRAP_GRID = (4, 16)  # samples per side of a strap's bearing footprint (1 mm pitch, clamped)
REVOLVED_TOL = 1e-5  # tangential normal component above which a face is not revolved about Z
AXIS_TOL = 1e-6  # mm: sample radius treated as on the spindle axis
NOSE_ARC = 12  # chords approximating the insert nose arc (inscribed: never enlarges it)
MERIDIAN_AZIMUTH = 0.5  # rad: the pose-selection meridian plane through Z (off revolved seams)
MERIDIAN_DEFLECTION = 1e-4  # mm: chord deflection of that section (well below LIFT)
POSE_SEARCH = (24, 16, 10)  # corner-offset search: directions, radial steps, bisections
TURNING = "turning"
SAW_ACTIONS = {"saw_cut", "cut_off"}
# Facing-type turning actions sweep their claims along +Z (toward the free end).
AXIAL_TURNING = {"face", "cut_to_fit", "part_off"}
WIDTH, HEIGHT = 640, 480
V = FreeCAD.Vector
Z = V(0, 0, 1)


@contextmanager
def _timed(records, key):
    """Nonoperative elapsed/process-CPU facts, only when the caller requests them."""
    if records is None:
        yield
        return
    wall, cpu = time.perf_counter(), time.process_time()
    record = {}
    records[key] = record
    try:
        yield record
    finally:
        record["wall_ms"] = _r((time.perf_counter() - wall) * 1000)
        record["cpu_ms"] = _r((time.process_time() - cpu) * 1000)


class _Unknown(Exception):
    """The whole job's facts are unknown for the stated reason."""


def _turned(op):
    return op.get("approach") == TURNING


def _sawn(op):
    return op.get("do") in SAW_ACTIONS


def _internal_reason(labels, internal):
    return "internal turning (boring bar inside a bore) is not modelled: " + ", ".join(
        sorted(labels[index] for index in internal)
    )


def _hull(points):
    """Convex hull (counter-clockwise, Andrew's monotone chain) of 2-D points."""
    points = sorted(set(points))
    if len(points) < 3:
        return points

    def cross(o, a, b):
        return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])

    lower, upper = [], []
    for point in points:
        while len(lower) >= 2 and cross(lower[-2], lower[-1], point) <= 0:
            lower.pop()
        lower.append(point)
    for point in reversed(points):
        while len(upper) >= 2 and cross(upper[-2], upper[-1], point) <= 0:
            upper.pop()
        upper.append(point)
    return lower[:-1] + upper[:-1]


def _clip_axis(polygon):
    """The part of an (r, z) polygon with r >= 0 (Sutherland-Hodgman against the axis)."""
    result = []
    for k, current in enumerate(polygon):
        previous = polygon[k - 1]
        inside, was_inside = current[0] >= 0, previous[0] >= 0
        if inside != was_inside:
            t = previous[0] / (previous[0] - current[0])
            result.append((0.0, previous[1] + t * (current[1] - previous[1])))
        if inside:
            result.append(current)
    return result


def _revolved_side(polygon):
    """Solid swept by the r >= 0 part of an (r, z) polygon turning once about Z, or None."""
    polygon = _clip_axis(polygon)
    if len(polygon) < 3:
        return None
    area = sum(
        polygon[k - 1][0] * polygon[k][1] - polygon[k][0] * polygon[k - 1][1]
        for k in range(len(polygon))
    )
    if abs(area) < 1e-9:
        return None
    points = [V(r, 0, z) for r, z in polygon]
    face = Part.Face(Part.makePolygon(points + points[:1]))
    return face.revolve(V(0, 0, 0), Z, 360)


def _revolved(polygon):
    """Solid a turning section sweeps about Z, or None: a part beyond the axis (r < 0) is
    mirrored, because the work turns past both sides of a section that crosses it."""
    pieces = [
        piece
        for piece in (
            _revolved_side(polygon),
            _revolved_side([(-r, z) for r, z in reversed(polygon)]),
        )
        if piece is not None
    ]
    if not pieces:
        return None
    return pieces[0].fuse(pieces[1]) if len(pieces) == 2 else pieces[0]


def _meridian_segments(shape):
    """Chords (s0, z0, s1, z1) of ``shape``'s section by the plane through Z at azimuth
    ``MERIDIAN_AZIMUTH``; s is the signed distance from Z in that plane, so the section of a
    solid of revolution carries both of its meridians (the work turns past both sides)."""
    c, s = math.cos(MERIDIAN_AZIMUTH), math.sin(MERIDIAN_AZIMUTH)
    segments = []
    for wire in shape.slice(V(-s, c, 0), 0.0):
        for edge in wire.Edges:
            if edge.Degenerated or edge.Length < 1e-7:
                continue
            points = [
                (p.x * c + p.y * s, p.z) for p in edge.discretize(Deflection=MERIDIAN_DEFLECTION)
            ]
            segments.extend((*a, *b) for a, b in zip(points, points[1:], strict=False))
    return segments


def _in_material(point, segments):
    """Whether an (s, z) point lies inside the closed section ``segments`` bound (even-odd)."""
    x, z = point
    inside = False
    for s0, z0, s1, z1 in segments:
        if (z0 > z) != (z1 > z) and s0 + (z - z0) * (s1 - s0) / (z1 - z0) > x:
            inside = not inside
    return inside


def _segment_distance(point, segment):
    x, z = point
    s0, z0, s1, z1 = segment
    ds, dz = s1 - s0, z1 - z0
    length = ds * ds + dz * dz
    t = 0.0 if length <= 0 else max(0.0, min(1.0, ((x - s0) * ds + (z - z0) * dz) / length))
    return math.hypot(x - s0 - t * ds, z - z0 - t * dz)


def _near(segments, box):
    """Segments whose bounding box meets ``box`` (s0, z0, s1, z1)."""
    return [
        seg
        for seg in segments
        if min(seg[0], seg[2]) <= box[2]
        and max(seg[0], seg[2]) >= box[0]
        and min(seg[1], seg[3]) <= box[3]
        and max(seg[1], seg[3]) >= box[1]
    ]


def _disk_clear(centre, radius, segments):
    """Whether a disk lies outside the section's material (touching allowed)."""
    x, z = centre
    near = _near(segments, (x - radius, z - radius, x + radius, z + radius))
    return not _in_material(centre, segments) and all(
        _segment_distance(centre, seg) >= radius for seg in near
    )


def _cross(o, a, b):
    return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])


def _polygon_clear(polygon, segments):
    """Whether a convex (s, z) polygon lies outside the section's material (touching allowed)."""
    edges = list(zip(polygon, polygon[1:] + polygon[:1], strict=True))
    sign = 1.0 if sum(_cross((0.0, 0.0), a, b) for a, b in edges) > 0 else -1.0

    def inside(point):
        return all(sign * _cross(a, b, point) > 1e-12 for a, b in edges)

    xs, zs = [p[0] for p in polygon], [p[1] for p in polygon]
    for s0, z0, s1, z1 in _near(segments, (min(xs), min(zs), max(xs), max(zs))):
        a, b = (s0, z0), (s1, z1)
        if inside(a) or inside(b) or inside(((s0 + s1) / 2, (z0 + z1) / 2)):
            return False
        for p, q in edges:
            if _cross(p, q, a) * _cross(p, q, b) < 0 and _cross(a, b, p) * _cross(a, b, q) < 0:
                return False
    return not _in_material(polygon[0], segments)


def _nearest_free(free, start, bound):
    """The (s, z) point nearest ``start`` within ``bound`` that ``free`` accepts, or None:
    ``POSE_SEARCH`` directions at growing radial steps, the first ring with a free point
    bisected back along each of its free directions."""
    directions, steps, halvings = POSE_SEARCH
    units = [
        (math.cos(2 * math.pi * k / directions), math.sin(2 * math.pi * k / directions))
        for k in range(directions)
    ]

    def at(unit, distance):
        return (start[0] + unit[0] * distance, start[1] + unit[1] * distance)

    for step in range(1, steps + 1):
        found = [unit for unit in units if free(at(unit, bound * step / steps))]
        best = None
        for unit in found:
            low, high = bound * (step - 1) / steps, bound * step / steps
            for _ in range(halvings):
                middle = (low + high) / 2
                low, high = (low, middle) if free(at(unit, middle)) else (middle, high)
            if best is None or high < best[0]:
                best = (high, at(unit, high))
        if best is not None:
            return best[1]
    return None


def _band(r0, r1, z0, z1):
    """Revolved annulus r0..r1 x z0..z1 (r0 may be 0), or None when it is empty."""
    if r1 - r0 <= PLANE_TOL or z1 - z0 <= PLANE_TOL:
        return None
    band = Part.makeCylinder(r1, z1 - z0, V(0, 0, z0))
    return band if r0 <= PLANE_TOL else band.cut(Part.makeCylinder(r0, z1 - z0, V(0, 0, z0)))


def _max_radius(shape):
    """Largest distance from Z over a shape's sampled edges (16 points per edge)."""
    return max(
        (math.hypot(p.x, p.y) for edge in shape.Edges for p in edge.discretize(16)),
        default=0.0,
    )


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


def _distant_box(box, other):
    """Tolerance-grown bounds prove distance > 1e-6; overlap never proves contact."""
    return (
        box[3] < other[0] - 1e-6
        or box[4] < other[1] - 1e-6
        or box[5] < other[2] - 1e-6
        or box[0] > other[3] + 1e-6
        or box[1] > other[4] + 1e-6
        or box[2] > other[5] + 1e-6
    )


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


def _distance(a, b):
    """``a.distToShape(b)``, measured from ``b`` when OCC cannot finish it from ``a``.

    BRepExtrema evaluates each sub-shape pair in argument order and is not symmetric. A
    guard's arc-join torus or sphere is an exact ``leave`` offset of the finished edge it
    rounds, and that coaxial circle/surface extremum can raise ``StdFail_NotDone`` one way
    while the other way measures it. Both orders measure the same distance; a failure in
    both still raises.
    """
    try:
        return a.distToShape(b)
    except RuntimeError as exc:
        if "StdFail_NotDone" not in str(exc):
            raise
    distance, pairs, infos = b.distToShape(a)
    return distance, [(p, q) for q, p in pairs], [info[3:] + info[:3] for info in infos]


def _face_samples(face, spacing, interior_only=False):
    """(point, outward normal) pairs inside and, unless excluded, on the boundary."""
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
    if interior_only:
        return samples, skipped
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
    """Cull and memoize cylinder intersections against one immutable stock solid.

    Cached shapes are read-only and expire with their stock/own-face region.
    Cap retained material shapes; cheap empty answers do not retain any B-rep.
    """

    KEEP = 256

    def __init__(self, shape):
        self.shape = shape
        self.boxes = [_tolerant_box(face) for face in shape.Faces]
        self.box = None
        if self.boxes:
            self.box = tuple(
                (min if index < 3 else max)(box[index] for box in self.boxes)
                for index in range(6)
            )
        self.answers = {}
        self.hit_refs = {}  # exact (cylinder, own face) -> read-only label set
        self.kept = 0

    def common(self, cx, cy, radius, z0, z1, solid=None):
        """The solid's material inside the cylinder, or None when there is none.

        A cutter ``solid`` lying inside that cylinder (a spot's point cone and body)
        replaces it in the boolean; the cylinder still bounds the face culling.
        Actual solids bypass the cylinder-answer cache.
        """
        key = (cx, cy, radius, z0, z1)
        cacheable = solid is None
        if cacheable and key in self.answers:
            return self.answers[key]
        if not any(_cylinder_hits_box(cx, cy, radius, z0, z1, box, True) for box in self.boxes):
            # No face reaches the cylinder, so it lies wholly inside or wholly outside.
            middle = (z0 + z1) / 2
            outside = self.box is not None and (
                cx < self.box[0] - 1e-6
                or cy < self.box[1] - 1e-6
                or middle < self.box[2] - 1e-6
                or cx > self.box[3] + 1e-6
                or cy > self.box[4] + 1e-6
                or middle > self.box[5] + 1e-6
            )
            if outside or not self.shape.isInside(V(cx, cy, middle), 1e-9, False):
                answer = None
            else:
                answer = (
                    solid if solid is not None else Part.makeCylinder(radius, z1 - z0, V(cx, cy, z0))
                )
        else:
            if solid is None:
                solid = Part.makeCylinder(radius, z1 - z0, V(cx, cy, z0))
            common = self.shape.common(solid)
            answer = common if common.Volume > HIT_MM3 else None
        if cacheable:
            if answer is None:
                self.answers[key] = None
            elif self.kept < _Culled.KEEP:
                self.answers[key] = answer
                self.kept += 1
        return answer


def _pointed_cutter(x, y, tip, radius, slope, length):
    """Solid a pointed tool on vertical axis (x, y) fills from ``tip`` up ``length`` mm.

    Its point is a cone with its apex at the tip, widening by ``slope`` (tangent of
    half the included point angle) per mm of rise until ``radius``, then a
    full-radius body; a length shorter than that rise truncates the cone.
    """
    rise = radius / slope
    profile = [V(x, y, tip)]
    if length <= rise:
        profile.append(V(x + length * slope, y, tip + length))
    else:
        profile += [V(x + radius, y, tip + rise), V(x + radius, y, tip + length)]
    profile.append(V(x, y, tip + length))
    return Part.Face(Part.makePolygon(profile + profile[:1])).revolve(V(x, y, tip), Z, 360)


def _tool_hits_box(cylinder, box, solid=None):
    """Whether a tool meets an axis-aligned box: its gross ``cylinder`` culls, and a
    cutter ``solid`` inside that cylinder (a pointed tool) must share volume with it."""
    if not _cylinder_hits_box(*cylinder, box):
        return False
    return solid is None or _box_shape(box).common(solid).Volume > HIT_MM3


def _tolerant_box(face):
    box = face.optimalBoundingBox(False, True)  # exact, grown by the shape tolerance
    return (box.XMin, box.YMin, box.ZMin, box.XMax, box.YMax, box.ZMax)


# --------------------------------------------------------------------------- stock


def _stock_vector(stock, key, unit):
    value = stock.get(key)
    if not (isinstance(value, list) and len(value) == 3 and all(_number(v) for v in value)):
        raise ValueError(f"stock {key} is not a numeric 3-vector")
    vector = V(*map(float, value))
    if unit and abs(vector.Length - 1) > 1e-6:
        raise ValueError(f"stock {key} is not a unit vector")
    return vector


def _envelope(stock):
    """The authored supplied-stock solid in model mm: a placed box or round bar."""
    shape = stock.get("shape")
    length = _positive(stock, "length_mm")
    if length is None:
        raise ValueError("stock length_mm is not a positive number")
    origin = _stock_vector(stock, "origin_mm", False)
    axis = _stock_vector(stock, "axis", True)
    if shape == "round":
        dia = _positive(stock, "dia_mm")
        if dia is None:
            raise ValueError("stock dia_mm is not a positive number")
        return Part.makeCylinder(dia / 2, length, origin, axis)
    if shape != "box":
        raise ValueError(f"stock shape {shape!r} is neither box nor round")
    section = stock.get("section_mm")
    if not (
        isinstance(section, list)
        and len(section) == 2
        and all(_number(v) and v > 0 for v in section)
    ):
        raise ValueError("stock section_mm is not two positive numbers")
    across = _stock_vector(stock, "section_axis", True)
    if abs(axis.dot(across)) > 1e-6:
        raise ValueError("stock axis and section_axis are not orthogonal")
    third = axis.cross(across)
    solid = Part.makeBox(length, float(section[0]), float(section[1]))
    solid.transformShape(
        FreeCAD.Matrix(
            axis.x,
            across.x,
            third.x,
            origin.x,
            axis.y,
            across.y,
            third.y,
            origin.y,
            axis.z,
            across.z,
            third.z,
            origin.z,
            0,
            0,
            0,
            1,
        )
    )
    return solid


def _clearing_box(bounds, within=None):
    """(setup-frame solid of an op's ``stock_removal_bounds`` in mm, or None, and why not).

    Given the stock bbox ``within``, the box is clipped to it grown by 1 mm before it is
    built, so huge finite bounds never become huge boolean operands; its intersection with
    that stock and face contact within ``STOCK_TOL`` are unchanged.
    """
    if isinstance(bounds, dict) and bounds.get("reason"):
        return None, str(bounds["reason"])
    if not isinstance(bounds, dict):
        return None, "stock_removal_bounds is unknown"
    spans, bad = [], []
    for axis in ("x", "y", "z"):
        span = bounds.get(axis)
        if (
            isinstance(span, list)
            and len(span) == 2
            and all(_number(v) for v in span)
            and span[0] < span[1]
        ):
            spans.append((float(span[0]), float(span[1])))
        else:
            bad.append(axis)
    if bad:
        return None, (
            "stock_removal_bounds " + ", ".join(bad) + " not a numeric [lo, hi] span with lo < hi"
        )
    lo, hi = [lo for lo, _ in spans], [hi for _, hi in spans]
    if within is not None:
        lo = [max(v, within[axis] - 1.0) for axis, v in enumerate(lo)]
        hi = [min(v, within[axis + 3] + 1.0) for axis, v in enumerate(hi)]
        if any(a >= b for a, b in zip(lo, hi, strict=True)):
            return None, "stock_removal_bounds lie wholly outside the stock"
    return _box_shape((*lo, *hi)), None


_UNRADIUSED = "stock_removal_bounds is unresolved: missing measured cutter radius_mm"


def _leave(op):
    """(mm a milling op leaves normal to the finished surface, or None, and why not).

    Only a ``rough_`` action leaves stock: a finishing op's paired allowance is the leave it
    removes. A primitive job without the key leaves none; the host always sends it.
    """
    if (
        _turned(op)
        or not str(op.get("do", "")).startswith("rough_")
        or "rough_allowance_mm" not in op
    ):
        return 0.0, None
    value = op["rough_allowance_mm"]
    if _number(value) and value >= 0:
        return float(value), None
    return None, f"rough_allowance_mm {value!r} is not a known nonnegative leave"


def _inner_point(face):
    """A point exactly on ``face`` (not on its boundary when avoidable), or None."""
    u0, u1, v0, v1 = face.ParameterRange
    for i, j in ((1, 1), (0, 0), (2, 2), (0, 2), (2, 0), (1, 0), (0, 1), (2, 1), (1, 2)):
        u, v = u0 + (2 * i + 1) * (u1 - u0) / 6, v0 + (2 * j + 1) * (v1 - v0) / 6
        if face.isPartOfDomain(u, v):
            return face.valueAt(u, v)
    return None


def _vertical(face, axis):
    """Whether every sampled normal of ``face`` is perpendicular to ``axis`` (no sweep volume)."""
    samples, skipped = _face_samples(face, 1.0)
    return not skipped and all(abs(normal.dot(axis)) < 1e-9 for _, normal in samples)


# --------------------------------------------------------------------------- fixtures


# Engine hold kind -> the _Setup method that places it (None = placed, else why not).
_PLACERS = {"vise": "_place", "chuck": "_place_chuck", "solids": "_place_solids"}
# Vise grip-zone facts; other holdings leave them unknown with the placement reason.
_VISE_FACTS = ("parallel_pair", "width_mm", "contact_grip_mm", "claimed_in_jaws", "min_wall_mm")
# Components whose interpenetration with the entering stock is a declaration error.
_SOLID_ROLES = frozenset(("chuck_jaw", "chuck_body", "head", "centre", "fixture", "clamp", "riser"))
# Vise accessories that stand between the jaws, below the seat.
_VISE_ACCESSORIES = frozenset(("parallel", "riser"))


def _pose_matrix(pose):
    """Fixture-local -> setup-frame matrix of a host-validated orthonormal pose."""
    x, z = V(*pose["x"]), V(*pose["z"])
    y = z.cross(x)
    origin = pose["origin_mm"]
    return FreeCAD.Matrix(
        x.x, y.x, z.x, origin[0], x.y, y.y, z.y, origin[1], x.z, y.z, z.z, origin[2], 0, 0, 0, 1
    )


def _fixture_kind(hold):
    """The inventory holding kind a hold declares (engine kinds are coarser), or None."""
    if not isinstance(hold, dict):
        return None
    kind = hold.get("fixture_kind", hold.get("kind"))
    return kind if isinstance(kind, str) and kind != UNKNOWN else None


def _primitive(spec):
    """A fixture-local box (min corner, size) or cylinder (base centre, axis, dia, length)."""
    at = V(*spec["at_mm"])
    if spec["shape"] == "box":
        return Part.makeBox(*spec["size_mm"], at)
    return Part.makeCylinder(spec["dia_mm"] / 2, spec["length_mm"], at, V(*spec["axis"]))


def _owner_primitives(specs):
    """(spec, local shape) per drawn primitive of one owner, its ``void``s cut away.

    A void (bore, tapped hole, slot) cuts the owner's primitives it names in ``cuts``, else
    all of them; it never cuts another owner's solid.
    """
    voids = [(spec.get("cuts"), _primitive(spec)) for spec in specs if spec.get("void")]
    result = []
    for spec in specs:
        if spec.get("void"):
            continue
        shape = _primitive(spec)
        for cuts, void in voids:
            if cuts is not None and spec.get("local") not in cuts:
                continue
            if shape.BoundBox.intersect(void.BoundBox):
                shape = shape.cut(void)
        result.append((spec, shape))
    return result


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
    "riser": (84, 108, 128),
    "chuck_jaw": (112, 92, 72),
    "chuck_body": (132, 128, 120),
    "head": (104, 112, 124),
    "centre": (150, 122, 92),
    "fixture": (120, 104, 136),
    "clamp": (164, 132, 64),
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


def run_job(job, timing=False):
    """Result dict for one job; failures become status error/unknown with a reason."""
    measured = {} if timing else None
    with _timed(measured, "job") as clocks:
        try:
            result = _Job(job, clocks).run()
        except _Unknown as exc:
            result = {"status": UNKNOWN, "reason": str(exc)}
        except Exception as exc:
            result = {"status": "error", "reason": f"{type(exc).__name__}: {exc}"}
    if timing:
        result["timing"] = measured["job"]
    return result


def run(payload):
    if isinstance(payload, dict) and "jobs" in payload:
        jobs = payload["jobs"]
        if not isinstance(jobs, list):
            return {"status": "error", "reason": "batch 'jobs' is not a list"}
        timing = payload.get("timing") is True
        measured = {} if timing else None
        with _timed(measured, "batch"):
            result = {"results": [run_job(job, timing) for job in jobs]}
        if timing:
            result["timing"] = measured["batch"]
        return result
    return run_job(payload)


class _Job:
    def __init__(self, job, timing=None):
        if not isinstance(job, dict) or job.get("version") != 1:
            raise ValueError("input is not a version-1 prechips geometry job")
        self.job = job
        self.timing = timing
        if timing is not None:
            timing["setups"] = {}

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
        supplies, (stock, reason) = self._supplies()
        result["stock"] = (
            {"bbox_mm": [_r(v) for v in _bbox(stock)], "volume_mm3": _r(stock.Volume)}
            if reason is None
            else {"reason": reason}
        )
        outputs = dict(supplies)
        leaves = dict.fromkeys(outputs, 0.0)  # largest known rough leave each lineage carries
        for setup in setups:
            held, held_reason = self._held(setup, outputs)
            if held_reason is None:
                box = _bbox(held)
                self.sweep_mm = 2 * math.dist(box[:3], box[3:]) + 10
            stock_in = setup.get("stock_in") if isinstance(setup, dict) else None
            refs = stock_in if isinstance(stock_in, list) else [stock_in]
            leave = max([0.0] + [leaves.get(ref, 0.0) for ref in refs if isinstance(ref, str)])
            runner = _Setup(self, setup, held, held_reason, leave)
            clocks = self.timing["setups"] if self.timing is not None else None
            with _timed(clocks, str(setup.get("id"))) as setup_clocks:
                runner.timing = setup_clocks
                facts, ops = runner.run()
            sid = str(setup.get("id"))
            result["setups"][sid] = facts
            result["ops"].update(ops)
            outputs[sid] = runner.stock_out, runner.stock_out_reason
            leaves[sid] = runner.leave_out
        return result

    def _supplies(self):
        """Each separately authored supply is independent of other branches' geometry debt."""
        stock = self.job.get("stock")
        components = stock.get("components") if isinstance(stock, dict) else None
        if isinstance(components, dict) and components:
            supplies = {}
            for name, component in components.items():
                solid, reason = self._supply(component, complete=False)
                supplies["stock." + name] = (
                    solid,
                    f"stock.{name}: {reason}" if reason is not None else None,
                )
            joined, reason = self._joined(list(supplies), supplies)
            if reason is None:
                outside = self.solid.cut(joined).Volume
                if outside > STOCK_MM3:
                    reason = (
                        f"the finished part extends {_r(outside)} mm^3 outside the joined "
                        "built-up supplies; in-process stock cannot be derived"
                    )
                    return {name: (None, reason) for name in supplies}, (None, reason)
            refs = self.job.get("as_is_faces")
            if isinstance(refs, list) and refs:
                if reason is None:
                    joined, reason = self._as_is(joined)
                if reason is not None:
                    return {name: (None, reason) for name in supplies}, (None, reason)
            return supplies, (joined, reason)
        supplied = self._supply(stock)
        return {"stock": supplied}, supplied

    def _supply(self, stock, complete=True):
        """A model-frame supply; a component need not contain the entire finished assembly."""
        if not isinstance(stock, dict):
            return None, "plan stock envelope is unknown; in-process stock cannot be derived"
        if stock.get("reason"):
            return None, str(stock["reason"])
        if stock.get("shape") == "part":
            # Explicit declaration that the supply is the imported solid itself (an already
            # finished blank); never inferred, and never emitted for a production plan.
            solid = self.solid.copy()
        else:
            try:
                solid = _envelope(stock)
            except ValueError as exc:
                return None, f"{exc}; in-process stock cannot be derived"
            if complete:
                outside = self.solid.cut(solid).Volume
                if outside > STOCK_MM3:
                    return None, (
                        f"the finished part extends {_r(outside)} mm^3 outside the authored stock "
                        "envelope; in-process stock cannot be derived"
                    )
        return self._as_is(solid) if complete else (solid, None)

    def _as_is(self, solid):
        """As-stock surfaces belong to the full supply envelope, including joined components."""
        refs = self.job.get("as_is_faces")
        if isinstance(refs, list):
            unmapped = sorted(
                str(ref) for ref in refs if not isinstance(ref, str) or ref not in self.mapping
            )
            if unmapped:
                return None, (
                    "as-is face reference(s) unmapped, so their supplied-stock surfaces cannot "
                    "be checked: " + ", ".join(unmapped)
                )
            shell = Part.makeCompound(solid.Shells)
            off = []
            for ref in refs:
                samples, _ = _face_samples(self.solid.Faces[self.mapping[ref]], 1.0)
                if not samples or any(
                    shell.distToShape(Part.Vertex(point))[0] > STOCK_TOL for point, _ in samples
                ):
                    off.append(ref)
            if off:
                return None, (
                    "as-is face(s) do not lie on the authored stock envelope, so the supplied "
                    "stock is not that envelope: " + ", ".join(sorted(set(off)))
                )
        return solid, None

    @staticmethod
    def _joined(refs, sources):
        """Union supplies/earlier outputs in model coordinates, never in their setup frames."""
        solids = []
        for ref in refs:
            if not isinstance(ref, str) or ref not in sources:
                return None, f"stock_in reference {ref!r} is not a supply or earlier setup output"
            solid, reason = sources[ref]
            if reason is not None:
                return None, reason
            solids.append(solid)
        if not solids:
            return None, "stock_in requires at least one supply or earlier setup output"
        if len(solids) == 1:
            return solids[0], None
        return solids[0].multiFuse(solids[1:]).removeSplitter(), None

    def _held(self, setup, sources):
        """Stock received from an explicit single reference or an assembly of references."""
        stock_in = setup.get("stock_in", UNKNOWN) if isinstance(setup, dict) else UNKNOWN
        refs = stock_in if isinstance(stock_in, list) else [stock_in]
        return self._joined(refs, sources)

    def _declared(self):
        features = self.job.get("features", {})
        return features if isinstance(features, dict) else {}

    def _claims(self):
        """Explicit ``faces`` lists of every op in the job."""
        setups = self.job.get("setups")
        return [
            op["faces"]
            for setup in (setups if isinstance(setups, list) else ())
            if isinstance(setup, dict) and isinstance(setup.get("ops"), list)
            for op in setup["ops"]
            if isinstance(op, dict) and isinstance(op.get("faces"), list)
        ]

    def _job_refs(self, step, mapping, errors):
        refs = []
        declared = list(self._declared().values()) + self._claims()
        for value in declared + [self.job.get("as_is_faces")]:
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
    def __init__(
        self, owner, setup, held=None, stock_reason="in-process stock was not derived", leave=0.0
    ):
        self.owner = owner
        self.setup = setup if isinstance(setup, dict) else {}
        self.ops = [op for op in self.setup.get("ops", []) if isinstance(op, dict)]
        # Largest known rough leave the entry stock's lineage may carry, and the output's.
        self.leave_in = leave
        self.leave_out = max([leave] + [a for a, _ in map(_leave, self.ops) if a is not None])
        self.reasons = {}
        # Model-frame stock this setup receives, or why it is unknown.
        self.held, self.stock_reason = (None, stock_reason) if held is None else (held, None)
        # Model-frame stock this setup leaves for the next one, or why it is unknown.
        self.stock_out, self.stock_out_reason = None, self.stock_reason
        self.matrix = None
        self.finished = None  # the finished solid in the setup frame
        self.faces = []  # its faces: every face index/label refers to these
        self.face_boxes = []
        self.part = None  # material present for the current fact: in-process stock
        self.box = None  # bounding box of the stock as held (seat, top)
        # certain jaw boxes {"fixed", "moving"} plus "possible": [(fixed side?, box)] once placed
        self.jaws = None
        self.hold = None  # the declared hold, once it is declared without a reason
        self.fixture_reason = None
        # Placed fixture components: {name, role, solid, bbox, box, rotating}; their union is
        # the fixture obstacle. ``possible`` are (name, box) regions a jaw may also occupy.
        self.fixture = []
        self.fixture_possible = []
        self.fixture_ready = False  # the holding itself is placed, so hit counts can be made
        self.fixture_debts = []  # scene-only debts (supports below the seat, poses to check)
        self.fixture_gaps = []  # undrawn components that could be obstacles
        self.undrawn = []  # declared components that are not drawn (interference debts)
        self.chuck = None  # placed chuck geometry for the turning model, else None
        self.regions = {}
        self.culled_part = None
        self.directions = {}  # finished face index -> direction verdict cache
        self.revolutions = {}  # finished face index -> turning verdict cache
        # Turning op subject -> (profile after it, or None, and (failing op, why) or None).
        self.turn_obstacles = {}
        self.floor_adjacency = None
        self.hole_cuts = {}  # (id(op), indices, radius) -> _hole_cut record
        self.hole_columns = None  # finished hole-face index -> entry-stock-long bore column
        self.guards = {}  # rough leave -> (finished solid offset outward by it, or None, why)
        self.slabs = {}  # (face index, thickness) -> (face thickened outward, or None, why)
        self.neighbours = None  # finished face index -> indices sharing an edge with it
        self.timing = None

    # ------------------------------------------------------------------ setup facts

    def run(self):
        clocks = self.timing
        phases = None if clocks is None else clocks.setdefault("phases", {})
        op_clocks = None if clocks is None else clocks.setdefault("ops", {})
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
            finished = self.owner.solid.copy()
            try:
                finished.transformShape(matrix)
            except Exception as exc:
                matrix, frame_reason = None, f"setup frame transform failed: {exc}"
            else:
                self.matrix = matrix
                self.finished = finished
                self.faces = finished.Faces
                self.face_boxes = [_tolerant_box(face) for face in self.faces]
        if matrix is None:
            self.stock_out_reason = (
                f"setup {self.setup.get('id')} frame is unusable ({frame_reason}); "
                "in-process stock after it cannot be derived"
            )
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
            ops = {}
            for op in self.ops:
                with _timed(op_clocks, self._subject(op)):
                    ops[self._subject(op)] = self._op_unknown(op, frame_reason)
            return facts, ops
        if self.stock_reason is None:
            self._use(self._placed(self.held))
            self.box = _bbox(self.part)
            facts["stock_bbox_mm"] = [_r(v) for v in self.box]
            facts["stock_volume_mm3"] = _r(self.part.Volume)
            with _timed(phases, "fixture"):
                self._fixture(facts)
        else:
            # Finished material is a subset of any real stock: hits on it stay sound, but
            # nothing measured on it may pass or be drawn as the held part.
            self._use(self.finished)
            self.box = _bbox(self.finished)
            facts["stock_reason"] = self.fixture_reason = self.stock_reason
            for key in (
                "parallel_pair",
                "width_mm",
                "contact_grip_mm",
                "claimed_in_jaws",
                "min_wall_mm",
            ):
                facts["reasons"][key] = self.stock_reason
        # Lathe chucks grip radially: their thin-wall fact is the run of material under each
        # jaw. ``chuck`` is set only once the fixture-solid model has placed a chuck.
        if self.stock_reason is None and self.chuck is not None:
            with _timed(phases, "chuck_walls"):
                self._chuck_walls(facts)
        # Turned setups: each declared feature's faces of revolution about setup Z (finished
        # geometry, independent of the entering stock).
        if any(_turned(op) for op in self.ops):
            self._revolution_facts(facts)
        # Every op and the render see the stock as it enters the setup; this setup's own
        # removals only shape the stock handed to the next one.
        ops = {}
        for op in self.ops:
            with _timed(op_clocks, self._subject(op)):
                result = self._op(op)
                if self.stock_reason is not None and not _sawn(op):
                    self._unproven(result, self.stock_reason)
                ops[self._subject(op)] = result
        if self.stock_reason is None:
            with _timed(phases, "render"):
                png, scene = self._render()
            facts["render_png_base64"] = base64.b64encode(png).decode("ascii")
            facts["render_scene"] = scene
            facts["fixture_rendered"] = (
                self.fixture_ready and bool(scene["components"]) and not scene["debts"]
            )
            with _timed(phases, "stock_output"):
                self.stock_out, self.stock_out_reason = self._output(ops)
            saws = [
                {"subject": self._subject(op), **ops[self._subject(op)]}
                for op in self.ops
                if _sawn(op)
            ]
            if saws:
                scene["saw_cuts"] = saws
        if self.fixture_reason is not None:
            facts["fixture_reason"] = self.fixture_reason
        unknown = [facts["reasons"][key] for key in sorted(facts["reasons"])]
        if self.fixture_reason is not None:
            facts["reason"] = self.fixture_reason
        elif unknown:
            facts["reason"] = unknown[0]
        return facts, ops

    # ------------------------------------------------------------------ in-process stock

    def _placed(self, shape):
        """A setup-frame copy of a model-frame shape."""
        placed = shape.copy()
        placed.transformShape(self.matrix)
        return placed

    def _use(self, solid):
        """Make ``solid`` the material present for the following facts."""
        self.part = solid
        self.culled_part = None
        self.regions = {}

    def _output(self, facts):
        """(model-frame stock this setup leaves, or None, and why it cannot be derived).

        A hole op (``hole`` metadata) removes its geometry-located bore cylinder (see
        :meth:`_hole_cut`). Other ops remove only stock outside their guard: the finished
        solid offset by their own rough leave (:meth:`_guard`). An authored clearing box
        removes that within the box above ``to_z``, leaving unclaimed hole columns to
        their own ops; its pieces must border a claim on the stock entering the setup, as
        its flute mask does, so an earlier op clearing the bridge between a claim and the
        rest of its box never strands that box. Other ops sweep direction-valid claims
        along +Z, keeping unclaimed rails, ears, webs and overstock. A lower-leave op also
        cuts the lineage leave off its claimed lateral faces (:meth:`_band`). Every
        profile-claimed face with a horizontal normal component must be clear of overstock
        beyond its op's guard at its interior after the setup's removals; merely sweeping a
        sliver from a drafted wall does not prove it cleared.
        """
        where = f"the in-process stock setup {self.setup.get('id')} leaves cannot be derived"
        stock, walls = self.part, []
        try:
            for op in self.ops:
                subject = self._subject(op)
                if _sawn(op):
                    stock, detail = self._saw_stock(op, stock)
                    facts[subject] = detail
                    why = detail.get("saw_error") or detail.get("saw_reason")
                    if why is not None:
                        return None, f"{subject}: {why}; {where}"
                    continue
                valid, away, why = self._claims(op)
                if not isinstance(valid, list):
                    return None, f"{subject} claimed faces are unresolved ({why}); {where}"
                to_z = op.get("to_z")
                if to_z is not None and not _number(to_z):
                    return None, f"{subject} to_z is unknown; {where}"
                if _turned(op):
                    removal, why = self._turn_removal(op, valid)
                    if why is not None:
                        return None, f"{subject} {why}; {where}"
                elif isinstance(op.get("hole"), dict):
                    # A hole cut derives later stock but never joins the profile-wall check.
                    cut = self._hole_cut(op, valid, _positive(op, "radius_mm"))
                    if cut["reason"] is not None:
                        return None, f"{subject} {cut['reason']}; {where}"
                    removal = cut["removal"]
                else:
                    leave, why = self._guarded(op)
                    if why is not None:
                        return None, f"{subject} {why}; {where}"
                    carried = self._carried(op)
                    if "stock_removal_bounds" in op:
                        # Removing the entry-stock pieces from the current stock only cuts.
                        removal, why = self._bounded(
                            op["stock_removal_bounds"],
                            self.part,
                            valid,
                            away,
                            to_z,
                            _positive(op, "radius_mm"),
                            leave,
                        )
                        if why is not None:
                            return None, f"{subject} {why}; {where}"
                    else:
                        removal = self._removal(valid, to_z, op.get("do"), leave)
                        walls.append((subject, self._indices(op), to_z, leave, carried))
                    band, why = self._band(stock, valid, to_z, leave, carried)
                    if why is not None:
                        return None, f"{subject} {why}; {where}"
                    if band is not None:
                        removal = band if removal is None else removal.fuse(band)
                if removal is None:
                    continue
                pieces = []
                for original in stock.Solids:
                    kept = [p for p in original.cut(removal).Solids if p.Volume > STOCK_MM3]
                    if len(kept) > 1 or not all(piece.isValid() for piece in kept):
                        return None, (
                            f"{subject}: removing its claimed clearance splits an input "
                            f"stock piece into {len(kept)} piece(s); {where}"
                        )
                    pieces.extend(kept)
                if not pieces:
                    return None, f"{subject}: claimed clearance leaves no stock; {where}"
                stock = pieces[0] if len(pieces) == 1 else Part.makeCompound(pieces)
            for subject, claimed, to_z, leave, carried in walls:
                # Raw stock beyond the larger of its own and the lineage leave is uncleared.
                overstock = stock.cut(self._guard(leave)[0])
                covered = self._covered(overstock, claimed, to_z, max(leave, carried) + COVER_MM)
                if covered:
                    return None, (
                        f"{subject}: overstock still touches claimed wall(s) "
                        f"{', '.join(covered)} above its to_z; the setup approach does not "
                        "fully clear this profile wall and the op declares no "
                        "stock_removal_bounds (cleared XY footprint, retained rail/ear volume "
                        f"of an interrupted profile) for it; {where}"
                    )
            model = stock.copy()
            model.transformShape(self.matrix.inverse())
        except Exception as exc:
            return None, f"in-process stock boolean failed ({exc}); {where}"
        return model, None

    # ------------------------------------------------------------------ planar sawing

    _SAW_VOLUMES = (
        "kerf_volume_mm3",
        "offcut_volume_mm3",
        "removed_volume_mm3",
        "stock_volume_before_mm3",
        "stock_volume_after_mm3",
    )

    def _saw_facts(self, op, stock_reason=None):
        """Saw inputs and debts, without a spindle/holder model or finished-face claims."""
        facts = {
            "claimed_indices": [],
            "kerf_mm": UNKNOWN,
            "cut_plane": UNKNOWN,
            "retained_boundary_mm": UNKNOWN,
            **{key: UNKNOWN for key in self._SAW_VOLUMES},
            "reasons": {},
        }
        missing = []
        kerf = op.get("kerf_mm")
        if not _number(kerf):
            missing.append("kerf_mm is missing or unverified")
        else:
            facts["kerf_mm"] = float(kerf)
            if kerf <= 0:
                facts["saw_error"] = "saw kerf_mm must be positive"
        plane = op.get("cut_plane")
        if (
            not isinstance(plane, dict)
            or plane.get("axis") not in ("x", "y", "z")
            or plane.get("keep") not in ("below", "above")
            or not _number(plane.get("value"))
        ):
            missing.append(
                str(plane["reason"])
                if isinstance(plane, dict) and plane.get("reason")
                else "cut_plane needs axis x/y/z, numeric value and keep below/above"
            )
        else:
            facts["cut_plane"] = {
                "axis": plane["axis"],
                "value": float(plane["value"]),
                "keep": plane["keep"],
            }
            if _number(kerf) and kerf > 0:
                sign = -1 if plane["keep"] == "below" else 1
                facts["retained_boundary_mm"] = _r(plane["value"] + sign * kerf / 2)
        machine = self.setup.get("machine_kind")
        if machine in (None, UNKNOWN):
            missing.append("saw machine kind is unknown")
        elif machine not in ("mill", "bench", "bandsaw"):
            facts["saw_error"] = f"saw action is unsupported on machine kind {machine!r}"
        if stock_reason is not None:
            missing.append(str(stock_reason))
        if missing:
            facts["saw_reason"] = "; ".join(missing)
            facts["reason"] = facts["saw_reason"]
            for key, value in facts.items():
                if value == UNKNOWN:
                    facts["reasons"][key] = facts["saw_reason"]
        return facts

    def _saw_stock(self, op, stock):
        """Keep one side of the blade slab; the kerf and offcut never enter later setups."""
        facts = self._saw_facts(op)
        facts["stock_volume_before_mm3"] = _r(stock.Volume)
        facts["reasons"].pop("stock_volume_before_mm3", None)
        if facts.get("saw_error") or facts.get("saw_reason"):
            return None, facts
        try:
            plane, kerf = facts["cut_plane"], facts["kerf_mm"]
            axis = "xyz".index(plane["axis"])
            low, high = plane["value"] - kerf / 2, plane["value"] + kerf / 2
            box = _bbox(stock)
            # Every halfspace/slab encloses the native stock on its other two axes.
            bounds = [value - 1.0 for value in box[:3]] + [
                value + 1.0 for value in box[3:]
            ]
            slab = list(bounds)
            slab[axis], slab[axis + 3] = low, high
            kerf_volume = stock.common(_box_shape(slab)).Volume
            facts["kerf_volume_mm3"] = _r(kerf_volume)
            if kerf_volume <= HIT_MM3:
                facts["saw_error"] = "off-stock blade slab removes no stock (saw no-op)"
                return None, facts
            boundary = low if plane["keep"] == "below" else high
            empty = boundary <= box[axis] if plane["keep"] == "below" else boundary >= box[axis + 3]
            if empty:
                facts["stock_volume_after_mm3"] = 0.0
                facts["removed_volume_mm3"] = _r(stock.Volume)
                facts["offcut_volume_mm3"] = _r(max(0.0, stock.Volume - kerf_volume))
                facts["saw_error"] = "saw leaves no retained stock"
                return None, facts
            bounds[axis + (3 if plane["keep"] == "below" else 0)] = boundary
            keep = _box_shape(bounds)
            retained = stock.common(keep)
            after = retained.Volume
            removed_volume = stock.Volume - after
            facts.update(
                stock_volume_after_mm3=_r(after),
                removed_volume_mm3=_r(removed_volume),
                offcut_volume_mm3=_r(max(0.0, removed_volume - kerf_volume)),
            )
            if not retained.Solids or after <= HIT_MM3:
                facts["saw_error"] = "saw leaves no retained stock"
            elif not retained.isValid():
                facts["saw_reason"] = "saw retained-stock boolean is invalid"
            else:
                removed = stock.cut(keep)
                target_loss = self.finished.common(removed).Volume
                if target_loss > HIT_MM3:
                    facts["saw_error"] = (
                        f"saw removes {_r(target_loss)} mm^3 of finished target material"
                    )
                elif len(retained.Solids) > 1:
                    # Existing separate supplies may remain separate. A cut must not
                    # create loose pieces from one connected input solid, even slivers;
                    # do not filter away native material or change the volume facts.
                    for original in stock.Solids:
                        count = len(original.common(keep).Solids)
                        if count > 1:
                            facts["saw_error"] = (
                                f"saw splits an input stock piece into {count} retained pieces"
                            )
                            break
            if facts.get("saw_error") or facts.get("saw_reason"):
                return None, facts
            return retained, facts
        except Exception as exc:
            reason = f"saw stock boolean failed ({exc})"
            facts["saw_reason"] = facts["reason"] = reason
            return None, facts

    def _bounded(self, bounds, stock, valid, away, to_z, radius, leave):
        """(stock outside the op's guard inside the declared box or None, or why not).

        The box is the author's multipass clearing volume, clipped to ``stock``: neither
        limited to the claims' footprint nor proof of a toolpath, but unresolved without a
        measured cutter radius. Every claim must face the approach and touch the box; every
        removed piece must border a claim across the op's ``leave``. Bores of hole-op
        claims this op does not claim keep their stock (:meth:`_hole_columns`).
        """
        box, why = _clearing_box(bounds, _bbox(stock))
        if box is None:
            return None, why
        labels = self.owner.labels
        if away:
            return None, (
                "stock_removal_bounds cannot clear claimed face(s) facing away from the setup "
                "approach: " + ", ".join(away)
            )
        if not valid:
            return None, "stock_removal_bounds has no claimed face to clear"
        outside = [
            labels[index] for index in valid if self.faces[index].distToShape(box)[0] >= STOCK_TOL
        ]
        if outside:
            return None, (
                "claimed face(s) lie outside its stock_removal_bounds: "
                + ", ".join(sorted(outside))
            )
        if radius is None:
            return None, _UNRADIUSED
        removed = stock.common(box).cut(self._guard(leave)[0])
        columns = self._hole_columns(valid)
        if columns is not None:
            # Not-yet-drilled hole interiors stay stock for their own hole op.
            removed = removed.cut(columns)
        if to_z is not None:
            removed = removed.common(self._above(to_z))
        pieces = [piece for piece in removed.Solids if piece.Volume > HIT_MM3]
        claimed = [self.faces[index] for index in valid]
        stray = [
            piece
            for piece in pieces
            if not any(_distance(piece, face)[0] < leave + STOCK_TOL for face in claimed)
        ]
        if stray:
            return None, (
                f"stock_removal_bounds removes {_r(sum(p.Volume for p in stray))} mm^3 in "
                f"{len(stray)} piece(s) bordering none of its claimed faces"
            )
        if not pieces:
            return None, None
        return (pieces[0].fuse(pieces[1:]) if len(pieces) > 1 else pieces[0]), None

    def _removal(self, valid, to_z, action, leave):
        """Stock outside the op's guard swept by direction-valid claims along +Z.

        A facing ``action`` sweeps each planar claim's outer loop, so raw pins over hole
        mouths go too; subtracting the guard still keeps islands, bosses and the leave.
        """
        up = V(0, 0, 1)
        faces, prisms = [], []
        for index in valid:
            face = self.faces[index]
            if _vertical(face, up):
                continue
            if (
                action in FACING_ACTIONS
                and isinstance(face.Surface, Part.Plane)
                and len(face.Wires) > 1
            ):
                face = Part.Face(face.OuterWire)
            prism = face.extrude(up * self.owner.sweep_mm)
            if prism.Volume > HIT_MM3:
                faces.append(face)
                prisms.append(prism)
        if not prisms:
            return None
        sweep = prisms[0].fuse(prisms[1:]) if len(prisms) > 1 else prisms[0]
        kept = [
            piece
            for piece in sweep.cut(self._guard(leave)[0]).Solids
            if piece.Volume > HIT_MM3
            and any(_distance(piece, f)[0] < leave + STOCK_TOL for f in faces)
        ]
        if not kept:
            return None
        removal = kept[0].fuse(kept[1:]) if len(kept) > 1 else kept[0]
        if to_z is not None:
            removal = removal.common(self._above(to_z))
            if removal.Volume <= HIT_MM3:
                return None
        return removal

    def _above(self, z):
        """A box holding everything in this setup at or above height ``z``."""
        size = 4 * self.owner.sweep_mm
        x, y = ((self.box[i] + self.box[i + 3]) / 2 - size / 2 for i in range(2))
        return Part.makeBox(size, size, size, V(x, y, z))

    def _covered(self, overstock, claimed, to_z, reach=COVER_MM):
        """Labels whose lateral face interior still borders overstock, not just neighbours."""
        if not claimed:
            return []
        if to_z is not None:
            overstock = overstock.common(self._above(to_z + COVER_MM))
        if overstock.Volume <= HIT_MM3:
            return []
        return sorted(
            self.owner.labels[index]
            for index in claimed
            if self._lateral(index) and self._interior_contact(self.faces[index], overstock, reach)
        )

    def _lateral(self, index):
        """Whether a finished face has a horizontal normal component inside it."""
        samples, _ = _face_samples(self.faces[index], 1.0, interior_only=True)
        return any(math.hypot(normal.x, normal.y) > 1e-9 for _, normal in samples)

    @staticmethod
    def _interior_contact(face, overstock, reach):
        """Exact contact catches small ears; inset near-edge probes ignore boundary-only contact.

        ``reach`` is ``COVER_MM`` past any leave the face may legitimately keep.
        """
        distance, pairs, _ = _distance(face, overstock)
        if distance >= reach:
            return False
        if face.common(overstock).Area > CONTACT_MM2:
            return True
        inner = _inner_point(face)
        if inner is None:
            # Without an interior point the face cannot establish that close stock is a neighbour.
            return True
        boundary = Part.makeCompound(face.Wires)
        inner_u, inner_v = face.Surface.parameter(inner)
        for point, _ in pairs:
            if boundary.distToShape(Part.Vertex(point))[0] > reach:
                return True
            length = (inner - point).Length
            fraction = min(1.0, 2 * reach / length) if length else 1.0
            contact_u, contact_v = face.Surface.parameter(point)
            while True:
                u = contact_u + fraction * (inner_u - contact_u)
                v = contact_v + fraction * (inner_v - contact_v)
                if face.isPartOfDomain(u, v):
                    inset = Part.Vertex(face.valueAt(u, v))
                    if boundary.distToShape(inset)[0] > 2 * reach:
                        if inset.distToShape(overstock)[0] < reach:
                            return True
                        break
                if fraction == 1.0:
                    break
                # A corner on a wide/short face needs more travel than an edge midpoint.
                fraction = min(1.0, 2 * fraction)
        return False

    def _carried(self, op):
        """Largest known rough leave the stock may carry where ``op`` cuts: its lineage's
        and every earlier op's of this setup."""
        leaves = [self.leave_in]
        for other in self.ops:
            if other is op:
                break
            leave, _ = _leave(other)
            if leave is not None:
                leaves.append(leave)
        return max(leaves)

    def _guarded(self, op):
        """(op's known rough leave whose guard is derivable, or None, and why not)."""
        leave, why = _leave(op)
        if why is None:
            why = self._guard(leave)[1]
        return (leave, None) if why is None else (None, why)

    def _guard(self, leave):
        """(finished solid offset outward by ``leave``, or None, and why not).

        Arc joins give the exact offset; where OCC cannot build them (a drill-point apex)
        sharp intersection joins give a superset that keeps more stock. The leave stays
        stock: a valid finite solid containing the finished part, or named debt, never the
        nominal solid in its place.
        """
        if leave == 0:
            return self.finished, None
        if leave not in self.guards:
            errors = []
            for join in (0, 2):
                try:
                    guard = self.finished.makeOffsetShape(leave, 1e-6, False, False, 0, join, False)
                    if (
                        not guard.isValid()
                        or len(guard.Solids) != len(self.finished.Solids)
                        or not all(math.isfinite(v) for v in _bbox(guard))
                        or guard.Volume <= self.finished.Volume
                    ):
                        raise ValueError("not a valid finite enclosing solid")
                    if self.finished.cut(guard).Volume > STOCK_MM3:
                        raise ValueError("it does not contain the finished part")
                    self.guards[leave] = (guard, None)
                    break
                except Exception as exc:
                    errors.append(f"{('arc', '', 'intersection')[join]} joins: {exc}")
            else:
                self.guards[leave] = (
                    None,
                    f"finished part offset by its {_r(leave)} mm rough_allowance_mm leave "
                    f"failed ({'; '.join(errors)})",
                )
        return self.guards[leave]

    def _slabs(self, valid, leave, carried):
        """(unclaimed neighbours of claimed lateral faces thickened past ``carried``, the
        lateral faces, and why not) when ``carried`` exceeds this op's ``leave``."""
        lateral = [index for index in valid if self._lateral(index)]
        if carried <= leave or not lateral:
            return [], [], None
        if self.neighbours is None:
            self.neighbours = {}
            for _, a, b in _shared_edges(self.faces, range(len(self.faces))):
                self.neighbours.setdefault(a, set()).add(b)
                self.neighbours.setdefault(b, set()).add(a)
        slabs = []
        thickness = carried + 10 * COVER_MM
        for index in sorted(
            {other for face in lateral for other in self.neighbours.get(face, ())} - set(valid)
        ):
            key = (index, thickness)
            if key not in self.slabs:
                try:
                    face = self.faces[index]
                    slab = face.makeOffsetShape(thickness, 1e-6, False, False, 0, 0, True)
                    if slab.Volume <= HIT_MM3 or not slab.isValid():
                        raise ValueError("empty or invalid thickened face")
                    self.slabs[key] = (slab, None)
                except Exception as exc:
                    self.slabs[key] = (
                        None,
                        f"unclaimed {self.owner.labels[index]} thickened by the "
                        f"{_r(carried)} mm lineage rough leave failed ({exc})",
                    )
            slab, why = self.slabs[key]
            if why is not None:
                return [], lateral, why
            slabs.append(slab)
        return slabs, lateral, None

    def _band(self, stock, valid, to_z, leave, carried):
        """(lineage leave a lower-leave op cuts off its claimed lateral faces, or None, and
        why not).

        Stock within the ``carried`` leave of the finished part but outside this op's own
        guard, less its unclaimed neighbours thickened past that leave, in pieces bordering
        a claimed lateral face: convex wedges between claimed faces go, unclaimed faces keep
        their skin, and raw stock beyond the leave stays for :meth:`_covered`.
        """
        slabs, lateral, why = self._slabs(valid, leave, carried)
        if why is not None or not lateral or carried <= leave:
            return None, why
        outer, why = self._guard(carried)
        if why is not None:
            return None, why
        band = stock.common(outer).cut(self._guard(leave)[0])
        if slabs:
            band = band.cut(slabs[0].fuse(slabs[1:]) if len(slabs) > 1 else slabs[0])
        if to_z is not None:
            band = band.common(self._above(to_z))
        pieces = [
            piece
            for piece in band.Solids
            if piece.Volume > HIT_MM3
            and any(_distance(piece, self.faces[i])[0] < leave + STOCK_TOL for i in lateral)
        ]
        if not pieces:
            return None, None
        return (pieces[0].fuse(pieces[1:]) if len(pieces) > 1 else pieces[0]), None

    @staticmethod
    def _unproven(facts, reason):
        """Unknown stock blocks clearance; finished-solid hits and corner radii survive."""
        why = f"in-process stock unknown: {reason}"
        facts["stock_reason"] = reason
        facts["reason"] = why
        reasons = facts.setdefault("reasons", {})
        for kind in ("tool", "holder"):
            value = facts.get(kind + "_hits")
            if _number(value):
                facts.setdefault("min_hits", {}).setdefault(kind, value)
        for key in (
            "tool_hits",
            "holder_hits",
            "reach_depth_mm",
            "holder_wall_hits",
        ):
            facts[key] = UNKNOWN
            reasons[key] = why

    @staticmethod
    def _subject(op):
        return str(op.get("subject"))

    # ------------------------------------------------------------------ claims

    def _claim_refs(self, op):
        """(refs, what) an op claims: its explicit ``faces``, else its feature's faces."""
        if "faces" in op:
            return op["faces"], f"op {self._subject(op)} faces"
        name = op.get("feature")
        declared = self.owner._declared()
        if not isinstance(name, str) or name not in declared:
            return None, f"feature {name!r} is not declared"
        return declared[name], f"feature {name!r}"

    def _indices(self, op):
        """Sorted finished-face indices an op claims, or unknown while any ref is unresolved."""
        refs, _ = self._claim_refs(op)
        indices = self.owner._feature(refs)
        return indices if indices != UNKNOWN and indices else UNKNOWN

    def _direction(self, index):
        """(faces away, undefined normal count) for a finished face in the setup frame.

        A face points away as soon as one evaluable normal has z below ``AWAY``: the
        tool approaches along -Z and no cutter dimension changes that.
        """
        if index not in self.directions:
            samples, skipped = _face_samples(self.faces[index], 1.0)
            away = any(normal.z < AWAY for _, normal in samples)
            self.directions[index] = (away, skipped if samples else max(skipped, 1))
        return self.directions[index]

    def _split(self, indices):
        """Claimed indices by verdict: cuttable, facing away, (index, undefined normals)."""
        valid, away, undefined = [], [], []
        for index in indices:
            facing_away, skipped = self._direction(index)
            if facing_away:
                away.append(index)
            elif skipped:
                undefined.append((index, skipped))
            else:
                valid.append(index)
        return valid, away, undefined

    def _undefined(self, undefined):
        labels = self.owner.labels
        return "face normal undefined at " + ", ".join(
            f"{skipped} sample(s) of {labels[index]}" for index, skipped in undefined
        )

    def _claims(self, op):
        """(direction-valid indices or unknown, labels facing away, reason) for an op."""
        if _sawn(op):
            return [], [], None
        indices = self._indices(op)
        if indices == UNKNOWN:
            return UNKNOWN, [], "claimed face references are unknown or unmapped"
        labels = self.owner.labels
        internal = []
        if _turned(op):
            valid, away, undefined, internal = self._turn_split(indices)
        else:
            valid, away, undefined = self._split(indices)
        if undefined:
            return UNKNOWN, sorted(labels[i] for i in away), self._undefined(undefined)
        if internal:
            return UNKNOWN, sorted(labels[i] for i in away), _internal_reason(labels, internal)
        return sorted(valid), sorted(labels[i] for i in away), None

    def _claimed(self):
        """Direction-valid indices claimed by this setup's ops, or why they are not all known."""
        indices, missing = set(), []
        for op in self.ops:
            valid, _, reason = self._claims(op)
            if valid == UNKNOWN:
                missing.append(f"{self._subject(op)} ({reason})")
            else:
                indices.update(valid)
        if missing:
            return None, "claimed faces unresolved for " + "; ".join(missing)
        return sorted(indices), None

    def _fixture(self, facts):
        """Place the declared holding, then its accessories; record what stays undrawn."""
        hold = self.setup.get("hold")
        reasons = facts["reasons"]
        reason = None
        if not isinstance(hold, dict):
            reason = "holding inputs are unknown"
        elif hold.get("reason"):
            reason = str(hold["reason"])
        elif hold.get("kind") not in _PLACERS:
            reason = "Fixture solids are not declared for this holding kind."
        else:
            self.hold = hold
            reason = getattr(self, _PLACERS[hold["kind"]])(hold, facts)
        if reason is None:
            self.fixture_ready = True
            if hold["kind"] == "vise":
                for side in ("fixed", "moving"):
                    self._add(side + "_jaw", "jaw", _box_shape(self.jaws[side]), self.jaws[side])
                self.fixture_possible = [
                    (("fixed" if fixed else "moving") + "_jaw_possible", box)
                    for fixed, box in self.jaws["possible"]
                ]
            else:
                reason = f"vise grip-zone facts do not apply to {hold.get('fixture_kind')} holding"
        else:
            self.fixture_reason = reason
        if self.hold is not None:
            self._accessories()
            self._interference(facts)
        else:
            reasons["fixture_clashes"] = reason
        if (
            self.fixture_ready
            and hold["kind"] == "solids"
            and (hold.get("clamps") or hold.get("clamp_debts"))
        ):
            # Posed straps load the stock: their footprint runs are the wall facts here.
            self._strap_walls(facts)
        if reason is not None:
            for key in _VISE_FACTS:
                if facts[key] == UNKNOWN:
                    reasons.setdefault(key, reason)

    def _add(self, name, role, solid, box=None, swept=None, owner=None):
        """Record one placed setup-frame fixture component (``box`` when it is that AABB).

        ``owner`` groups the primitives of one authored body (a fixture's or a clamp's
        ``solids``); they are one assembly, never checked against each other.
        """
        component = {
            "name": name,
            "role": role,
            "owner": owner or name,
            "solid": solid,
            "box": box,
            "bbox": box if box is not None else _bbox(solid),
            "envelope": swept if swept is not None else solid,
        }
        component["envelope_bbox"] = (
            component["bbox"] if swept is None else _bbox(component["envelope"])
        )
        self.fixture.append(component)
        return component

    def _add_local(self, name, role, shape, matrix, swept=None, owner=None):
        """Place a fixture-local shape (and its revolved envelope) into the setup frame."""
        placed = shape.copy()
        placed.transformShape(matrix)
        envelope = None
        if swept is not None:
            envelope = swept.copy()
            envelope.transformShape(matrix)
        return self._add(name, role, placed, swept=envelope, owner=owner)

    def _add_owned(self, specs, role, matrix, owner):
        """Place one owner's authored primitives (voids cut) and return their solids."""
        return [
            self._add_local(spec["name"], role, shape, matrix, owner=owner)["solid"]
            for spec, shape in _owner_primitives(specs)
        ]

    def _place_chuck(self, hold, facts):
        """Jaws close on the stock's extremes along each jaw inside the grip zone.

        Chuck frame: origin at the jaw-face centre, +z out of the jaws toward the work,
        jaw 1 along +x rotated by ``jaw_clock_deg``. Jaws are boxes ``jaw_height``
        radially outward from their contact, ``jaw_width`` wide and ``jaw_depth`` long
        behind the face; the body is a bored cylinder behind them. A dividing head's
        declared body solids hang from its spindle nose, the body's back face.
        """
        matrix = _pose_matrix(hold["pose"])
        local = self.part.copy()
        local.transformShape(matrix.inverse())
        depth, height, width = (hold[k] for k in ("jaw_depth_mm", "jaw_height_mm", "jaw_width_mm"))
        grip = min(hold["grip_mm"], depth)
        lb = _bbox(local)
        zone = local.common(
            Part.makeBox(lb[3] - lb[0] + 2, lb[4] - lb[1] + 2, grip, V(lb[0] - 1, lb[1] - 1, -grip))
        )
        if zone.Volume <= HIT_MM3:
            return (
                f"no stock lies within the chuck jaws ({_r(grip)} mm behind the jaw face at the "
                "pose origin), so jaw positions are undefined"
            )
        count = hold["jaws"]
        angles = [(hold["jaw_clock_deg"] + 360.0 * i / count) % 360.0 for i in range(count)]
        radii = []
        for angle in angles:
            turned = zone.copy()
            turned.rotate(V(0, 0, 0), Z, -angle)
            radii.append(_bbox(turned)[3])
        if min(radii) <= PLANE_TOL:
            return "the chuck axis does not pass through the gripped stock; jaws cannot close on it"
        lathe = self.setup.get("machine_kind") == "lathe" and hold.get("fixture_kind") != (
            "dividing_head"
        )
        for index, (angle, radius) in enumerate(zip(angles, radii, strict=True), start=1):
            jaw = Part.makeBox(height, width, depth, V(radius, -width / 2, -depth))
            jaw.rotate(V(0, 0, 0), Z, angle)
            swept = None
            if lathe:
                outer = math.hypot(radius + height, width / 2)
                swept = Part.makeCylinder(outer, depth, V(0, 0, -depth)).cut(
                    Part.makeCylinder(radius, depth, V(0, 0, -depth))
                )
            self._add_local(f"chuck jaw {index}", "chuck_jaw", jaw, matrix, swept, owner="chuck")
        length = hold["body_length_mm"]
        back = V(0, 0, -depth - length)
        body = Part.makeCylinder(hold["body_dia_mm"] / 2, length, back).cut(
            Part.makeCylinder(hold["bore_dia_mm"] / 2, length, back)
        )
        self._add_local(
            "chuck body", "chuck_body", body, matrix, body if lathe else None, owner="chuck"
        )
        if hold.get("head_solids"):
            nose = FreeCAD.Matrix()
            nose.move(back)
            nose = matrix.multiply(nose)
            self._add_owned(hold["head_solids"], "head", nose, "head")
        if hold.get("centre"):
            self._place_centre(hold["centre"], hold["pose"], lathe)
        if hold.get("fixture_kind") == "chuck_3jaw" and max(radii) - min(radii) > COVER_MM:
            self.fixture_debts.append(
                "scroll-chuck jaws close at unequal radii "
                f"{[_r(r) for r in radii]} mm: the stock is not centred on the declared chuck axis"
            )
        origin, axis = V(*hold["pose"]["origin_mm"]), V(*hold["pose"]["z"])
        x_axis = V(*hold["pose"]["x"])
        y_axis = axis.cross(x_axis)
        directions = [
            x_axis * math.cos(math.radians(a)) + y_axis * math.sin(math.radians(a)) for a in angles
        ]
        entry = origin - axis * grip
        self.chuck = {
            "grip_z": tuple(sorted((entry.z, origin.z))),
            "jaw_angles_deg": [math.degrees(math.atan2(d.y, d.x)) % 360.0 for d in directions],
            "matrix": matrix,
            "local_angles_deg": angles,
            "grip": grip,
        }
        facts["chuck"] = {
            "jaw_angles_deg": [_r(a) for a in self.chuck["jaw_angles_deg"]],
            "contact_radii_mm": [_r(r) for r in radii],
            "grip_in_jaws_mm": _r(grip),
        }
        facts["grip_zone_z_mm"] = [_r(v) for v in self.chuck["grip_z"]]
        claimed, reason = self._claimed()
        if claimed is None:
            facts["reasons"]["claimed_in_jaws"] = reason
        else:
            jaws = [c["solid"] for c in self.fixture if c["role"] == "chuck_jaw"]
            facts["claimed_in_jaws"] = sorted(
                self.owner.labels[index]
                for index in claimed
                if any(self.faces[index].distToShape(jaw)[0] < STOCK_TOL for jaw in jaws)
            )
        return None

    def _place_centre(self, centre, pose, lathe):
        """A tailstock dead centre pointing back along -pose.z, plus its exposed quill."""
        tip, axis = V(*centre["tip_mm"]), V(*pose["z"])
        radius, length = centre["dia_mm"] / 2, centre["length_mm"]
        half = math.radians(centre["point_angle_deg"] / 2)
        cone = min(length, radius / math.tan(half))
        point = Part.makeCone(0, cone * math.tan(half), cone, tip, axis)
        if length - cone > PLANE_TOL:
            point = point.fuse(Part.makeCylinder(radius, length - cone, tip + axis * cone, axis))
        name = f"dead centre {centre['name']}"
        self._add(name, "centre", point, swept=point if lathe else None, owner="tailstock")
        if centre["quill_extension_mm"] > 0:
            quill = Part.makeCylinder(
                centre["quill_dia_mm"] / 2,
                centre["quill_extension_mm"],
                tip + axis * length,
                axis,
            )
            self._add(
                "tailstock quill",
                "centre",
                quill,
                swept=quill if lathe else None,
                owner="tailstock",
            )
        if point.distToShape(self.part)[0] > STOCK_TOL:
            self.fixture_debts.append(f"{name} tip does not reach the stock")

    def _place_solids(self, hold, facts):
        """An authored fixture body (angle plate, custom nest) at its declared pose."""
        matrix = _pose_matrix(hold["pose"])
        self._add_owned(hold.get("solids", []), "fixture", matrix, "fixture")
        if not self.fixture:
            return "no fixture solid is declared free of measurement debt"
        if all(c["solid"].distToShape(self.part)[0] > STOCK_TOL for c in self.fixture):
            self.fixture_debts.append(
                f"{hold.get('fixture_kind')} fixture solids do not touch the stock at the "
                "declared pose"
            )
        return None

    def _place_clamps(self, hold):
        """Each posed clamp member's solids (strap, stud, heel; voids cut) as one owner."""
        clamps = []
        for clamp in hold.get("clamps", []):
            matrix = _pose_matrix(clamp["pose"])
            clamps.append(
                (clamp["name"], self._add_owned(clamp["solids"], "clamp", matrix, clamp["name"]))
            )
        return clamps

    def _accessories(self):
        """Parallels, riser blocks and clamps of a declared hold, plus host-side debts."""
        hold = self.hold
        parallels, debt = self._parallels()
        if debt is not None:
            self.fixture_debts.append(debt)
        # Components that exist but are not drawn: any of them may interpenetrate.
        self.undrawn = [debt] if debt is not None else []
        self.undrawn.extend(str(item) for item in (*hold.get("debts", []), *hold.get("gaps", [])))
        for index, box in enumerate(parallels or (), start=1):
            self._add(f"parallel {index}", "parallel", _box_shape(box), box)
            for side in ("fixed", "moving") if self.jaws is not None else ():
                if _boxes_overlap(box, self.jaws[side]):
                    centre = [_r((box[0] + box[3]) / 2), _r((box[1] + box[4]) / 2)]
                    self.fixture_debts.append(
                        f"declared parallel centred at {centre} intersects the {side} jaw"
                    )
        riser = hold.get("riser")
        if riser:
            top = self.box[2] - (hold.get("parallels_height_mm") or 0.0)
            along, across, up = riser["size_mm"]
            dx, dy = (along, across) if hold.get("jaws_along") == "x" else (across, along)
            for index, (x, y) in enumerate(riser["centres_mm"], start=1):
                box = (x - dx / 2, y - dy / 2, top - up, x + dx / 2, y + dy / 2, top)
                self._add(f"riser {index} {riser['name']}", "riser", _box_shape(box), box)
        clamps = self._place_clamps(hold)
        self.clamp_parts = [
            (name, V(*clamp["pose"]["z"]) * -1, parts)
            for (name, parts), clamp in zip(clamps, hold.get("clamps", []), strict=True)
        ]
        self.fixture_debts.extend(str(debt) for debt in hold.get("debts", []))
        self.fixture_gaps.extend(str(gap) for gap in hold.get("gaps", []))
        if hold.get("kind") == "vise":
            return
        for component in self.fixture:
            if component["role"] not in _SOLID_ROLES:
                continue
            common = component["solid"].common(self.part)
            if common.Volume > STOCK_MM3:
                self.fixture_debts.append(
                    f"{component['name']} intersects the setup-entry stock "
                    f"({_r(common.Volume)} mm^3) at the declared pose"
                )
        for name, parts in clamps:
            if all(part.distToShape(self.part)[0] > STOCK_TOL for part in parts):
                self.fixture_debts.append(f"{name} does not bear on the stock at its pose")

    def _interference(self, facts):
        """Drawn fixture components that interpenetrate the entry stock or each other, and
        vise accessories outside the closed jaw opening; undrawn components stay debts.

        Contact is allowed: a clash is common volume above STOCK_MM3. Primitives of one
        owner (an authored body, a clamp assembly, the chuck) are one part and not paired.
        """
        clashes, debts = [], list(self.undrawn)
        components = self.fixture
        for component in components:
            if not _boxes_overlap(component["bbox"], self.box):
                continue
            volume = component["solid"].common(self.part).Volume
            if volume > STOCK_MM3:
                clashes.append(
                    f"{component['name']} interpenetrates the setup-entry stock ({_r(volume)} mm^3)"
                )
        for index, first in enumerate(components):
            for second in components[index + 1 :]:
                roles = {first["role"], second["role"]}
                if first["owner"] == second["owner"] or (
                    "jaw" in roles and roles & _VISE_ACCESSORIES
                ):
                    continue  # one part, or the jaw-opening check below
                if not _boxes_overlap(first["bbox"], second["bbox"]):
                    continue
                volume = first["solid"].common(second["solid"]).Volume
                if volume > STOCK_MM3:
                    clashes.append(
                        f"{first['name']} interpenetrates {second['name']} ({_r(volume)} mm^3)"
                    )
        if self.hold.get("kind") == "vise":
            self._jaw_opening(components, clashes, debts)
        elif not self.fixture_ready:
            debts.append(f"holding not placed: {self.fixture_reason}")
        for component in components:
            for name, box in self.fixture_possible:
                if component["role"] != "jaw" and _boxes_overlap(component["bbox"], box):
                    debts.append(f"{component['name']} may meet the {name.replace('_', ' ')}")
        facts["fixture_clashes"] = clashes
        facts["fixture_clash_debts"] = list(dict.fromkeys(debts))

    def _jaw_opening(self, components, clashes, debts):
        """Parallels and risers stand between the jaws: inside the opening closed on the stock."""
        accessories = [c for c in components if c["role"] in _VISE_ACCESSORIES]
        if self.jaws is None:
            debts.append(f"vise jaws not placed: {self.fixture_reason}")
            return
        axis, lo, hi = self.clamp["c_axis"], self.clamp["lo"], self.clamp["hi"]
        name = "xy"[axis]
        for component in accessories:
            box = component["bbox"]
            if box[axis] < lo - STOCK_TOL or box[axis + 3] > hi + STOCK_TOL:
                clashes.append(
                    f"{component['name']} spans {name} {_r(box[axis])}..{_r(box[axis + 3])} mm, "
                    f"outside the jaw opening {name} {_r(lo)}..{_r(hi)} mm closed on the stock"
                )

    def _fixture_hits(self, solid):
        """Names of placed fixture components (revolved on a lathe) that ``solid`` meets."""
        box = _bbox(solid)
        names = set()
        for component in self.fixture:
            if not _boxes_overlap(box, component["envelope_bbox"]):
                continue
            if solid.common(component["envelope"]).Volume > HIT_MM3:
                names.add(component["name"])
        return sorted(names)

    def _fixture_cylinder_hits(self, cylinder, solid=None):
        """Names of placed fixture components a vertical (x, y, r, z0, z1) tool meets.

        ``solid`` is the cutter inside ``cylinder`` (a pointed tool's cone and body) when it
        is not the cylinder itself: the cylinder only culls, and every component, a box
        jaw too, must share volume with that cutter.
        """
        ax, ay, radius, z0, z1 = cylinder
        names, tool = set(), solid
        for component in self.fixture:
            if not _cylinder_hits_box(*cylinder, component["envelope_bbox"]):
                continue
            if component["box"] is None or solid is not None:
                if tool is None:
                    tool = Part.makeCylinder(radius, z1 - z0, V(ax, ay, z0))
                if tool.common(component["envelope"]).Volume <= HIT_MM3:
                    continue
            names.add(component["name"])
        return names

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
        intervals, stock = [], False
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
            if not stock and self._source(face) is None:
                stock = True
        labels = ["in-process stock"] if stock else []
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

    def _source(self, face):
        """Index of the finished face that a stock face lies on, or None for stock surface."""
        point = _inner_point(face)
        if point is None:
            return None
        vertex = Part.Vertex(point)
        for index, box in enumerate(self.face_boxes):
            if all(box[i] - STOCK_TOL <= point[i] <= box[i + 3] + STOCK_TOL for i in range(3)):
                if self.faces[index].distToShape(vertex)[0] < STOCK_TOL:
                    return index
        return None

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

    def _in_jaws(self, claimed):
        inside = []
        jaws = [_box_shape(self.jaws[side]) for side in ("fixed", "moving")]
        for index in claimed:
            face = self.faces[index]
            for jaw in jaws:
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

    def _strap_walls(self, facts):
        """Thinnest material run under each strap's bearing footprint along its clamp force.

        The force is the strap pose's -z. Footprint samples are a cell-centred grid on every
        flat strap face that faces the force and touches the entry stock; from each sample a
        line runs along the force and the first material interval it meets at the contact is
        the run. A sample over air is not loaded. Undrawn or non-bearing clamps keep the wall
        unknown unless a drawn strap already proves it thin.
        """
        debts = [str(debt) for debt in self.hold.get("clamp_debts", [])]
        span = self.part.BoundBox.DiagonalLength + 1.0
        rows, thinnest = [], None
        for name, force, parts in self.clamp_parts:
            loaded = 0
            for part in parts:
                for face in part.Faces:
                    if not isinstance(face.Surface, Part.Plane):
                        continue
                    u0, u1, v0, v1 = face.ParameterRange
                    if face.normalAt((u0 + u1) / 2, (v0 + v1) / 2).dot(force) < 1 - 1e-6:
                        continue
                    if face.distToShape(self.part)[0] > STOCK_TOL:
                        continue
                    nu, nv = (
                        min(STRAP_GRID[1], max(STRAP_GRID[0], math.ceil(hi - lo)))
                        for lo, hi in ((u0, u1), (v0, v1))
                    )
                    for i in range(nu):
                        for j in range(nv):
                            point = face.valueAt(
                                u0 + (i + 0.5) * (u1 - u0) / nu, v0 + (j + 0.5) * (v1 - v0) / nv
                            )
                            if not face.isInside(point, PLANE_TOL, True):
                                continue
                            run = self._strap_run(point, force, span)
                            rows.append(
                                {
                                    "clamp": name,
                                    "point_mm": [_r(c) for c in point],
                                    "loaded": run is not None,
                                    "run_mm": UNKNOWN if run is None else _r(run),
                                }
                            )
                            if run is not None:
                                loaded += 1
                                thinnest = run if thinnest is None else min(thinnest, run)
            if not loaded:
                debts.append(f"{name} has no sampled footprint point bearing on the stock")
        facts["strap_wall_map"] = rows
        facts["strap_wall_debts"] = debts
        if thinnest is not None:
            facts["min_wall_mm"] = _r(thinnest)
        else:
            facts["reasons"]["min_wall_mm"] = "strap walls unresolved: " + "; ".join(debts)

    def _strap_run(self, point, force, span):
        """Material length from ``point`` along ``force`` until the first air, or None."""
        start = point - force * 0.01
        line = Part.LineSegment(start, point + force * span).toShape()
        intervals = sorted(
            sorted((vertex.Point - point).dot(force) for vertex in edge.Vertexes)
            for edge in line.common(self.part).Edges
        )
        merged = []
        for lo, hi in intervals:
            if merged and lo - merged[-1][1] <= PLANE_TOL:
                merged[-1][1] = max(merged[-1][1], hi)
            else:
                merged.append([lo, hi])
        if not merged or merged[0][0] > STOCK_TOL:
            return None
        return merged[0][1] - max(merged[0][0], 0.0)

    def _render(self):
        """PNG of the stock entering the setup (claimed surfaces tinted) and the fixture."""
        claimed = set()
        for op in self.ops:
            valid = self._claims(op)[0]
            if isinstance(valid, list):
                claimed.update(valid)
        size = max(self.box[3] - self.box[0], self.box[4] - self.box[1], self.box[5] - self.box[2])
        tolerance = max(0.01, size / 400)
        meshes = []
        for face in self.part.Faces:
            points, triangles = face.tessellate(tolerance)
            colour = "claimed" if self._source(face) in claimed else "part"
            meshes.append((points, triangles, _COLOURS[colour]))
        debts, solids, possible = [], [], []
        vise = self.hold is not None and self.hold.get("kind") == "vise"
        if not self.fixture_ready:
            jaws = "absent"
            debts.append(f"{'jaws' if vise else 'fixture'} not drawn: {self.fixture_reason}")
        elif not vise:
            jaws = "exact" if self.hold.get("kind") == "chuck" else "not_applicable"
        else:
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
                possible = [
                    (name, _box_shape(box), _COLOURS[name]) for name, box in self.fixture_possible
                ]
        debts += self.fixture_debts
        debts += [f"not drawn: {gap}" for gap in self.fixture_gaps]
        # Jaws, then the possible-jaw strips, then the rest: the z-buffer keeps first-drawn ties.
        for component in sorted(self.fixture, key=lambda c: c["role"] != "jaw"):
            colour = _COLOURS.get(component["name"]) or _COLOURS[component["role"]]
            solids.append((component["name"], component["solid"], colour))
            if component["name"] == "moving_jaw":
                solids += possible
                possible = []
        for _, shape, colour in solids + possible:
            points, triangles = shape.tessellate(tolerance)
            meshes.append((points, triangles, colour))
        parallels = any(c["role"] == "parallel" for c in self.fixture)
        scene = {
            "fixture_kind": _fixture_kind(self.setup.get("hold")),
            "jaws": jaws,
            "parallels": "absent"
            if self.hold is None or (not vise and "parallels_ref" not in self.hold)
            else "exact"
            if parallels
            else "not_modelled",
            "components": [
                {
                    "name": c["name"],
                    "role": c["role"],
                    "exact": jaws == "exact" or c["role"] != "jaw",
                }
                for c in self.fixture
            ],
            "debts": debts,
        }
        return _render(meshes), scene

    def _parallels(self):
        """Parallel boxes from declared dimensions and centres, or the debt that prevents them."""
        hold = self.hold
        vise = hold is not None and hold.get("kind") == "vise"
        if hold is None or not (vise or "parallels_ref" in hold):
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
        along = hold.get("jaws_along") if vise else hold.get("parallels_along")
        if along not in ("x", "y"):
            missing.append("jaws_along" if vise else "parallels_along")
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

    _MEASURED = (
        "sample_count",
        "tool_hits",
        "holder_hits",
        "reach_depth_mm",
        "holder_wall_hits",
    )

    def _op_unknown(self, op, reason):
        if _sawn(op):
            return self._saw_facts(op, reason)
        facts = {"reason": reason, "reasons": {}}
        if _turned(op):
            facts["approach"] = TURNING
        for key in ("claimed_indices", *self._MEASURED, "corner_radii_mm"):
            facts[key] = UNKNOWN
            facts["reasons"][key] = reason
        return facts

    def _op(self, op):
        if _sawn(op):
            return self._saw_facts(
                op, self.stock_reason or "in-process stock before this saw operation cannot be derived"
            )
        owner = self.owner
        refs, what = self._claim_refs(op)
        if refs is None:
            return self._op_unknown(op, what)
        if (
            not isinstance(refs, list)
            or not refs
            or any(not isinstance(ref, str) or ref == UNKNOWN for ref in refs)
        ):
            return self._op_unknown(op, f"{what}: face references are unknown")
        invalid = sorted({ref for ref in refs if ref in owner.errors})
        if invalid:
            facts = self._op_unknown(
                op, f"{what}: invalid or unmapped face reference(s): " + ", ".join(invalid)
            )
            facts["mapping_errors"] = invalid
            return facts
        indices = self._indices(op)
        if indices == UNKNOWN:
            return self._op_unknown(op, f"{what}: face references are unknown")
        if _turned(op):
            return self._turn_op(op, indices)
        valid, away, undefined = self._split(indices)
        facts = {"reasons": {}}
        reasons = facts["reasons"]
        facts["claim_errors"] = sorted(owner.labels[index] for index in away)
        if (
            "stock_removal_bounds" in op
            and valid
            and not away
            and not undefined
            and _positive(op, "radius_mm") is None
            and _clearing_box(op["stock_removal_bounds"])[0] is not None
        ):
            reasons["stock_removal_bounds"] = _UNRADIUSED
        if undefined:
            facts["claimed_indices"] = UNKNOWN
            reasons["claimed_indices"] = self._undefined(undefined)
        else:
            facts["claimed_indices"] = sorted(valid)
        # Faces whose normals are only partly evaluable are still sampled: a hit on them
        # is a definite hit (``min_hits``), but no measured fact may pass on them while
        # the claim verdict itself stays unknown.
        sampled = sorted(valid + [index for index, _ in undefined])
        if not sampled:
            reason = "every claimed face points away from the setup approach: " + ", ".join(
                facts["claim_errors"]
            )
            for key in (*self._MEASURED, "corner_radii_mm"):
                facts[key] = UNKNOWN
                reasons[key] = reason
        else:
            hole = isinstance(op.get("hole"), dict)
            corner = self._corners(sampled, hole) if not undefined else reasons["claimed_indices"]
            facts["corner_radii_mm"] = corner if isinstance(corner, list) else UNKNOWN
            if not isinstance(corner, list):
                reasons["corner_radii_mm"] = corner
            radius = _positive(op, "radius_mm")
            if radius is None:
                for key in self._MEASURED:
                    facts[key] = UNKNOWN
                    reasons[key] = "op lacks a measured cutter radius_mm"
            else:
                self._sample_facts(op, sampled, radius, facts)
                if undefined:
                    for key in self._MEASURED:
                        if facts.get(key) != UNKNOWN:
                            facts[key] = UNKNOWN
                            reasons[key] = reasons["claimed_indices"]
        unknown = [
            reasons[key]
            for key in (
                "stock_removal_bounds",
                "claimed_indices",
                *self._MEASURED,
                "corner_radii_mm",
            )
            if key in reasons
        ]
        if unknown:
            facts["reason"] = unknown[0]
        return facts

    def _corners(self, indices, hole=False):
        """Sorted concave corner radii around the tool axis, or the reason they are unknown.

        A hole op's own tool-axis bores are not internal corners: sizing owns their diameter.
        Nor are those bores' own matched caps (:meth:`_own_caps`), which its tool cuts.
        """
        part, faces, labels = self.finished, self.faces, self.owner.labels
        radii, problems = set(), []
        caps = self._own_caps(indices) if hole else set()
        for index in indices:
            if index in caps:
                continue
            face = faces[index]
            surface = face.Surface
            if isinstance(surface, Part.Plane):
                continue
            if isinstance(surface, Part.Cylinder):
                if not _cylinder_concave(face):
                    continue
                if abs(surface.Axis.dot(Z)) >= PARALLEL:
                    if not hole:
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

    def _own_caps(self, indices):
        """Claimed cone or sphere faces capping a claimed tool-axis bore of a hole op.

        A cap shares a real edge with a claimed concave bore parallel to the tool axis,
        lies on that bore's axis line within its radius (:meth:`_cap_span`) and wholly
        below it, closing the end away from the tool. Wider countersinks, tilted or
        off-axis cones and caps of unclaimed bores stay ordinary claimed faces.
        """
        caps = set()
        for _, a, b in _shared_edges(self.faces, indices):
            for bore, cap in ((a, b), (b, a)):
                face = self.faces[bore]
                surface = face.Surface
                if (
                    cap in caps
                    or not isinstance(surface, Part.Cylinder)
                    or abs(surface.Axis.dot(Z)) < PARALLEL
                    or not _cylinder_concave(face)
                ):
                    continue
                span = self._cap_span(self.faces[cap], Z, surface.Center, surface.Radius)
                if span is not None and span[1] <= self._bore_span(face, Z)[0] + BBOX_TOL:
                    caps.add(cap)
        return caps

    def _region(self, index):
        """Stock minus a tolerance-thick shell of only the sampled finished face."""
        if index in self.regions:
            return self.regions[index]
        label = self.owner.labels[index]
        try:
            shell = Part.Shell([self.faces[index]]).makeOffsetShape(
                -LIFT, 1e-6, False, False, 0, 0, True
            )
            if shell.Volume <= HIT_MM3 or not shell.isValid():
                raise ValueError("empty or invalid offset solid")
            obstacle = self.part.cut(shell)
        except Exception as exc:
            self.regions[index] = (
                None,
                f"own-face surface shell for {label} failed ({exc})",
            )
        else:
            self.regions[index] = (_Culled(obstacle), None)
        return self.regions[index]

    def _hole_cut(self, op, valid, radius):
        """Geometry-located cut of a hole op: ``centres``, ``bottom``, ``removal``, ``reason``,
        ``cone_slope``.

        ``centres`` are setup-frame vectors on each claimed tool-axis bore axis whose z is
        that axis's own actual tip once known (a through hole exits where its claimed
        bores end); ``bottom`` is the lowest of them, or None beside a debt ``reason``;
        ``cone_slope`` is a pointed tool's tan(point angle / 2), else None. A spot is
        always pointed; a drill is pointed when its hole carries ``point_angle_deg``.
        ``removal`` is the op-radius cutter from each axis's tip (``LIFT`` lower through
        an exit) past the entry-stock top minus unrelated finished material, or None when
        nothing is removed. A pointed cutter is its :func:`_pointed_cutter` cone and body;
        others sweep a cylinder. Every action but a spot adds its own bore wall allowance
        up to the operation radius.
        """
        key = (id(op), tuple(valid), radius)
        if key not in self.hole_cuts:
            try:
                self.hole_cuts[key] = self._hole_record(op, valid, radius)
            except Exception as exc:
                self.hole_cuts[key] = {
                    "centres": [],
                    "bottom": None,
                    "removal": None,
                    "reason": f"hole cut boolean failed ({exc})",
                    "cone_slope": None,
                }
        return self.hole_cuts[key]

    def _hole_record(self, op, indices, radius):
        labels = self.owner.labels

        def debt(reason, axes=()):
            centres = [V(x, y, 0.0) for x, y, _ in axes]
            return {
                "centres": centres,
                "bottom": None,
                "removal": None,
                "reason": reason,
                "cone_slope": None,
            }

        hole = op.get("hole")
        if not isinstance(hole, dict):
            return debt("op carries no hole metadata")
        if radius is None:
            return debt("hole op lacks a measured cutter radius_mm")
        walls, tilted = [], []
        for index in indices:
            face = self.faces[index]
            surface = face.Surface
            if not isinstance(surface, Part.Cylinder) or not _cylinder_concave(face):
                continue
            if abs(surface.Axis.dot(Z)) < PARALLEL:
                tilted.append(labels[index])
            else:
                walls.append((index, surface.Center.x, surface.Center.y, surface.Radius))
        if tilted:
            return debt(
                "hole bore(s) not parallel to the setup tool axis cannot locate the cut: "
                + ", ".join(sorted(tilted))
            )
        if not walls:
            return debt(
                "no claimed concave cylindrical bore parallel to the setup tool axis locates "
                "the hole cut"
            )
        axes = []  # [x, y, [(index, bore radius)]] per distinct claimed bore axis
        for index, x, y, bore in walls:
            for axis in axes:
                if math.hypot(x - axis[0], y - axis[1]) <= BBOX_TOL:
                    axis[2].append((index, bore))
                    break
            else:
                axes.append([x, y, [(index, bore)]])
        axes.sort(key=lambda axis: (axis[0], axis[1]))
        to_z, action, thru = op.get("to_z"), op.get("do"), hole.get("thru")
        entry, depth = hole.get("entry_z_mm"), hole.get("depth_mm")
        through, slope = False, None
        if action == "spot" or (action == "drill" and "point_angle_deg" in hole):
            # A pointed tool cuts with its cone, never a flat-bottomed cylinder: without a
            # known included angle neither its cut nor its flute obstacle is derivable.
            angle = hole.get("point_angle_deg", UNKNOWN)
            if angle == UNKNOWN:
                return debt(f"{action} point_angle_deg is unknown; its point cone is unknown", axes)
            if not (_number(angle) and 0 < angle < 180):
                return debt(
                    f"{action} point_angle_deg {angle!r} is not a number strictly between 0 "
                    "and 180 degrees; its point cone is unknown",
                    axes,
                )
            slope = math.tan(math.radians(angle) / 2)
        # As tip_endpoints: a drill's depth and through exit locate its full-diameter
        # body, so its tip is a point length P below them; a spot's depth is its tip.
        point = radius / slope if action == "drill" and slope is not None else 0.0
        if to_z is not None:
            if not _number(to_z):
                return debt("hole op to_z is unknown", axes)
            bottoms = [float(to_z)] * len(axes)  # an absolute to_z is the actual tip
        elif action in ("spot", "tap") or thru is False:
            # As tip_endpoints: spots and taps stop at their authored depth even in a
            # through hole; other actions use it only in a blind hole.
            if not _number(entry) or not (_number(depth) and depth > 0):
                return debt(
                    f"blind {action} bottom needs a numeric hole entry_z_mm and positive "
                    "depth_mm, or a to_z",
                    axes,
                )
            bottoms = [float(entry) - float(depth) - point] * len(axes)
        elif thru is True:
            # Each axis exits where its own claimed bores end, not at the entry-stock
            # floor: finished material below the exit (a clevis's lower leg, a cross
            # bore's far wall) is never on this tool's path.
            bottoms = [
                min(self._bore_span(self.faces[index], Z)[0] for index, _ in members) - point
                for _, _, members in axes
            ]
            through = True
        else:
            return debt("hole thru is unknown and the op has no to_z; its bottom is unknown", axes)
        centres = [V(x, y, level) for (x, y, _), level in zip(axes, bottoms, strict=True)]
        bottom = min(bottoms)
        top = self.box[5] + 1.0
        tools = []
        for (x, y, _), level in zip(axes, bottoms, strict=True):
            # A through cut starts LIFT past its exit so no face is coincident with it.
            low = level - LIFT if through else level
            if top - low <= LIFT:
                continue
            if slope is None:
                tools.append(Part.makeCylinder(radius, top - low, V(x, y, low)))
            else:
                tools.append(_pointed_cutter(x, y, low, radius, slope, top - low))
        record = {
            "centres": centres,
            "bottom": bottom,
            "removal": None,
            "reason": None,
            "cone_slope": slope,
        }
        if not tools:
            return record
        cylinder = tools[0].fuse(tools[1:]) if len(tools) > 1 else tools[0]
        removal = cylinder.cut(self.finished)
        # A spot never widens its own bore: its mouth must fit the future bore, so an
        # over-deep spot's cone stays an obstacle against that finished wall.
        for _, _, members in axes if action != "spot" else ():
            for index, bore in members:
                excess = radius - bore
                if excess <= PLANE_TOL:
                    continue
                # This op's own bore wall is cutting material; sizing checks its diameter.
                try:
                    shell = Part.Shell([self.faces[index]]).makeOffsetShape(
                        -(excess + LIFT), 1e-6, False, False, 0, 0, True
                    )
                    if shell.Volume <= HIT_MM3 or not shell.isValid():
                        raise ValueError("empty or invalid offset solid")
                except Exception as exc:
                    record["reason"] = (
                        f"own bore wall offset of {labels[index]} to the {_r(radius)} mm op "
                        f"radius failed ({exc})"
                    )
                    return record
                removal = removal.fuse(shell.common(cylinder))
        if removal.Volume > HIT_MM3:
            record["removal"] = removal
        return record

    def _hole_faces(self):
        """Finished-face indices claimed by every planned op carrying hole metadata."""
        indices = set()
        setups = self.owner.job.get("setups")
        for setup in setups if isinstance(setups, list) else ():
            ops = setup.get("ops") if isinstance(setup, dict) else None
            for op in ops if isinstance(ops, list) else ():
                if isinstance(op, dict) and isinstance(op.get("hole"), dict):
                    refs, _ = self._claim_refs(op)
                    found = self.owner._feature(refs)
                    if found != UNKNOWN:
                        indices.update(found)
        return indices

    @staticmethod
    def _bore_span(face, axis, inner=()):
        """Exact (min, max) of the dot product with ``axis`` over a bore or cap face.

        A cylinder's or cone's axial coordinate has no interior extremum, so the face's
        boundary edges, turned so ``axis`` is +Z, bound it exactly (crossing saddles
        included). ``inner`` names the surface's other critical points (a cone apex at a
        degenerated edge, a sphere's poles); each one the face contains joins the span.
        """
        edges = Part.Compound([edge.copy() for edge in face.Edges if not edge.Degenerated])
        edges.transformShape(FreeCAD.Placement(V(), FreeCAD.Rotation(axis, Z)).toMatrix())
        box = edges.optimalBoundingBox(False, False)
        lo, hi = box.ZMin, box.ZMax
        for point in inner:
            if face.distToShape(Part.Vertex(point))[0] < LIFT:
                lo, hi = min(lo, point.dot(axis)), max(hi, point.dot(axis))
        return lo, hi

    @classmethod
    def _cap_span(cls, face, axis, centre, radius):
        """Axial (min, max) of ``face`` if it caps the bore on this axis line, else None.

        A cap is a concave cone (drill point) or sphere (ball end) on the bore's axis
        line lying within its ``radius``, so the bore's nominal column holds its void.
        """
        surface = face.Surface
        if isinstance(surface, Part.Cone):
            if abs(surface.Axis.dot(axis)) < PARALLEL:
                return None
            anchor = surface.Apex
            inner = (anchor,)
        elif isinstance(surface, Part.Sphere):
            anchor = surface.Center
            inner = (anchor + axis * surface.Radius, anchor - axis * surface.Radius)
        else:
            return None
        offset = anchor - centre
        if (offset - axis * offset.dot(axis)).Length > BBOX_TOL:
            return None
        u0, u1, v0, v1 = face.ParameterRange
        point = face.valueAt((u0 + u1) / 2, (v0 + v1) / 2)
        normal = face.normalAt((u0 + u1) / 2, (v0 + v1) / 2)
        if isinstance(surface, Part.Cone):
            # The void lies toward the axis.
            inward = anchor + axis * (point - anchor).dot(axis) - point
        else:
            inward = anchor - point
        if normal.dot(inward) <= 0:
            return None
        lo, hi = cls._bore_span(face, axis, inner)
        # The distance from the axis line is monotone in the axial coordinate away from
        # the apex (cone) or the centre (sphere), so the span's ends bound it.
        level = anchor.dot(axis)
        if isinstance(surface, Part.Cone):
            reach = max(abs(lo - level), abs(hi - level)) * math.tan(surface.SemiAngle)
        elif lo <= level <= hi:
            reach = surface.Radius
        else:
            near = min(abs(lo - level), abs(hi - level))
            reach = math.sqrt(max(surface.Radius**2 - near**2, 0.0))
        return (lo, hi) if reach <= radius + BBOX_TOL else None

    def _hole_columns(self, claimed):
        """Fused bore-long columns of known hole bores outside ``claimed``, or None.

        Each column spans only its bore face's own axial extent and any blind cap
        (:meth:`_cap_span`) sharing an edge with it (± ``LIFT``), so stock above a hole
        mouth or beyond a horizontal blind hole's end is never reserved. Its radius stays
        the bore's nominal radius.
        """
        if self.hole_columns is None:
            self.hole_columns = {}
            bores = []
            for index in sorted(self._hole_faces()):
                face = self.faces[index]
                if isinstance(face.Surface, Part.Cylinder) and _cylinder_concave(face):
                    bores.append(index)
            neighbours = {}
            if bores:
                for _, a, b in _shared_edges(self.faces, range(len(self.faces))):
                    neighbours.setdefault(a, set()).add(b)
                    neighbours.setdefault(b, set()).add(a)
            for index in bores:
                face = self.faces[index]
                surface = face.Surface
                axis, centre = surface.Axis, surface.Center
                lo, hi = self._bore_span(face, axis)
                for other in sorted(neighbours.get(index, ())):
                    cap = self._cap_span(self.faces[other], axis, centre, surface.Radius)
                    if cap is not None:
                        lo, hi = min(lo, cap[0]), max(hi, cap[1])
                lo, hi = lo - LIFT, hi + LIFT
                start = centre + axis * (lo - centre.dot(axis))
                self.hole_columns[index] = Part.makeCylinder(surface.Radius, hi - lo, start, axis)
        claimed = set(claimed)
        columns = [
            column for index, column in sorted(self.hole_columns.items()) if index not in claimed
        ]
        if not columns:
            return None
        return columns[0].fuse(columns[1:]) if len(columns) > 1 else columns[0]

    def _flute_regions(self, op, regions, radius, hole_cut=None):
        """Only this op's derivable allowance is cutting material, not a flute obstacle.

        A hole op uses its (prepared or computed) :meth:`_hole_cut` removal; a milling op
        cuts what :meth:`_output` removes for it, its guard's leave excepted. Holder
        obstacles never see this.
        """
        if self.stock_reason is not None:
            return regions
        if isinstance(op.get("hole"), dict):
            if hole_cut is None:
                valid, _, _ = self._claims(op)
                if not isinstance(valid, list):
                    return regions
                hole_cut = self._hole_cut(op, valid, radius)
            if hole_cut["reason"] is not None:
                return regions
            removal = hole_cut["removal"]
        else:
            valid, away, why = self._claims(op)
            to_z = op.get("to_z")
            if (
                not isinstance(valid, list)
                or away
                or why
                or (to_z is not None and not _number(to_z))
            ):
                return regions
            leave, why = self._guarded(op)
            if why:
                return regions
            carried = self._carried(op)
            if "stock_removal_bounds" in op:
                removal, why = self._bounded(
                    op["stock_removal_bounds"], self.part, valid, away, to_z, radius, leave
                )
                if why:
                    return regions
            else:
                removal = self._removal(valid, to_z, op.get("do"), leave)
            band, why = self._band(self.part, valid, to_z, leave, carried)
            if why:
                return regions
            if band is not None:
                removal = band if removal is None else removal.fuse(band)
        if removal is None:
            return regions
        removal = self.part.common(removal)
        if removal.Volume <= HIT_MM3:
            return regions
        return {
            index: (_Culled(region.shape.cut(removal)), None) if region is not None else (None, why)
            for index, (region, why) in regions.items()
        }

    def _floor_edges(self, index):
        """``(edge, wall index, edge box)`` per sharp concave rising wall of a +Z planar floor.

        One scan of every shared edge caches each floor's walls, the edges each face pair
        shares (for :meth:`_wall_corner`) and the floors whose wall edges could not be
        classified; asking for such a floor raises with the reason.
        """
        if self.floor_adjacency is None:
            walls, failed, pairs = {}, {}, {}
            for edge, a, b in _shared_edges(self.faces, range(len(self.faces))):
                pairs.setdefault((min(a, b), max(a, b)), []).append(edge)
                middle = edge.valueAt((edge.FirstParameter + edge.LastParameter) / 2)
                for floor, wall in ((a, b), (b, a)):
                    face = self.faces[floor]
                    if (
                        not isinstance(face.Surface, Part.Plane)
                        or self.face_boxes[wall][5] <= middle.z + LIFT
                    ):
                        continue
                    try:
                        if _normal_at(face, middle).z < PARALLEL or not _concave_edge(
                            self.finished, edge, face, self.faces[wall]
                        ):
                            continue
                    except Exception as exc:
                        failed.setdefault(
                            floor,
                            f"floor edge with {self.owner.labels[wall]} is unclassified ({exc})",
                        )
                        continue
                    walls.setdefault(floor, []).append((edge, wall, _bbox(edge)))
            self.floor_adjacency = {"walls": walls, "failed": failed, "pairs": pairs, "corners": {}}
        if index in self.floor_adjacency["failed"]:
            raise ValueError(self.floor_adjacency["failed"][index])
        return self.floor_adjacency["walls"].get(index, ())

    def _wall_corner(self, a, b):
        """Whether faces ``a`` and ``b`` meet at a sharp concave shared edge (cached)."""
        key = (min(a, b), max(a, b))
        corners = self.floor_adjacency["corners"]
        if key not in corners:
            corners[key] = any(
                _concave_edge(self.finished, edge, self.faces[a], self.faces[b]) is True
                for edge in self.floor_adjacency["pairs"].get(key, ())
            )
        return corners[key]

    def _floor_contacts(self, index, point, reach):
        """Rising walls of floor ``index`` whose floor edge is within ``reach`` of ``point``.

        Returns ``(incident, near)``: ``(wall, nx, ny)`` for edges through the point and
        ``(wall, nx, ny, offset)`` for the others, where ``(nx, ny)`` is the wall's unit
        in-plane normal into the floor at the edge's nearest point and ``offset`` the
        point's signed in-plane distance from it, positive into the floor.
        """
        incident, near, vertex = [], [], None
        margin = max(reach, STOCK_TOL)
        for edge, wall, box in self._floor_edges(index):
            if any(
                point[axis] < box[axis] - margin or point[axis] > box[axis + 3] + margin
                for axis in range(3)
            ):
                continue
            if vertex is None:
                vertex = Part.Vertex(point)
            distance, nearest, _ = edge.distToShape(vertex)
            if distance > STOCK_TOL and distance >= reach:
                continue
            foot = nearest[0][0]
            normal = _normal_at(self.faces[wall], foot)
            length = math.hypot(normal.x, normal.y)
            if length < 1e-9:
                continue
            nx, ny = normal.x / length, normal.y / length
            if distance <= STOCK_TOL:
                incident.append((wall, nx, ny))
            else:
                near.append((wall, nx, ny, nx * (point.x - foot.x) + ny * (point.y - foot.y)))
        return incident, near

    def _floor_corners(self, index):
        """(vertex, floor normal) where two rising walls meet the floor at a concave corner.

        Convex island corners get no pose of their own: their edge samples already
        stand tangent to one wall each.
        """
        face = self.faces[index]
        found = []
        for vertex in face.Vertexes:
            walls = [wall for wall, _, _ in self._floor_contacts(index, vertex.Point, 0.0)[0]]
            if any(
                a != b and self._wall_corner(a, b)
                for i, a in enumerate(walls)
                for b in walls[i + 1 :]
            ):
                found.append((vertex.Point, _normal_at(face, vertex.Point)))
        return found

    def _floor_axis(self, index, point, radius):
        """User decision 2026-10-05: the nearest axis tangent to the walls bounding a sample.

        Each wall through the sample constrains the axis offset ``d`` by ``n·d >= radius``.
        A wall whose floor edge is nearer than ``radius`` adds ``n·d >= radius - offset``
        only when it meets an incident wall at a concave wall/wall corner, so a sample
        near a pocket corner stands tangent to both walls; convex island corners and
        unrelated walls add nothing.  A sample on no wall keeps its own axis.
        """
        incident, near = self._floor_contacts(index, point, radius)
        if not incident:
            return point.x, point.y
        walls = {wall for wall, _, _ in incident}
        limits = [(nx, ny, radius) for _, nx, ny in incident] + [
            (nx, ny, radius - offset)
            for wall, nx, ny, offset in near
            if wall not in walls and any(self._wall_corner(wall, other) for other in walls)
        ]
        candidates = [(0.0, 0.0)] + [(rhs * nx, rhs * ny) for nx, ny, rhs in limits]
        for i, (ax, ay, ra) in enumerate(limits):
            for bx, by, rb in limits[i + 1 :]:
                determinant = ax * by - ay * bx
                if abs(determinant) > 1e-9:
                    candidates.append(
                        ((ra * by - ay * rb) / determinant, (ax * rb - ra * bx) / determinant)
                    )
        feasible = [
            (dx, dy)
            for dx, dy in candidates
            if all(nx * dx + ny * dy >= rhs - 1e-7 for nx, ny, rhs in limits)
        ]
        if not feasible:
            raise ValueError("no floor-axis pose is tangent to all bounding rising walls")
        dx, dy = min(feasible, key=lambda delta: delta[0] ** 2 + delta[1] ** 2)
        return point.x + dx, point.y + dy

    def _floor_debt(self, index, exc, facts):
        """A floor whose tool pose cannot be derived leaves this op's measured facts unknown."""
        reason = f"{self.owner.labels[index]}: floor tool pose is undefined ({exc})"
        for key in self._MEASURED:
            facts[key] = UNKNOWN
            facts["reasons"][key] = reason

    def _sample_facts(self, op, indices, radius, facts):
        reasons = facts["reasons"]
        hole_cut = self._hole_cut(op, indices, radius) if isinstance(op.get("hole"), dict) else None
        if hole_cut is not None and hole_cut["reason"] is not None:
            for key in self._MEASURED:
                facts[key] = UNKNOWN
                reasons[key] = hole_cut["reason"]
            return
        slope = hole_cut["cone_slope"] if hole_cut is not None else None
        # A rough op's poses stand its known leave off the finished surface along the normal.
        leave, why = (0.0, None) if hole_cut is not None else self._guarded(op)
        if why is not None:
            for key in self._MEASURED:
                facts[key] = UNKNOWN
                reasons[key] = why
            return
        samples, sample_problems = [], []
        for index in indices:
            found, missed = _face_samples(self.faces[index], max(radius, 1.0))
            if (
                isinstance(self.faces[index].Surface, Part.Plane)
                and found
                and found[0][1].z >= PARALLEL
            ):
                try:
                    found.extend(self._floor_corners(index))
                except Exception as exc:
                    self._floor_debt(index, exc, facts)
                    return
            samples.extend((index, point, normal) for point, normal in found)
            if missed:
                sample_problems.append(
                    f"{self.owner.labels[index]}: {missed} sample point(s) "
                    "had no defined surface normal"
                )
        sample_reason = "; ".join(sample_problems) if sample_problems else None
        facts["sample_count"] = UNKNOWN if sample_reason else len(samples)
        if sample_reason:
            reasons["sample_count"] = sample_reason
        flute = _positive(op, "flute_len_mm")
        keys = ("holder_radius_mm", "holder_gauge_len_mm", "projection_mm")
        holder = {key: _positive(op, key) for key in keys}
        holder_missing = sorted(key for key, value in holder.items() if value is None)
        placed = []  # (index, point, axis x, axis y, tip z, downward)
        for index, point, normal in samples:
            horizontal = math.hypot(normal.x, normal.y)
            ax, ay, level = point.x, point.y, point.z
            if hole_cut is not None:
                centre = min(
                    hole_cut["centres"],
                    key=lambda centre: (centre.x - point.x) ** 2 + (centre.y - point.y) ** 2,
                )
                ax, ay = centre.x, centre.y
                level = max(level, centre.z)
            elif horizontal > 1e-9:
                if normal.z >= -1e-3:
                    ax, ay = ax + leave * normal.x, ay + leave * normal.y
                    level += leave * normal.z
                ax += radius * normal.x / horizontal
                ay += radius * normal.y / horizontal
            elif normal.z >= PARALLEL:
                level += leave
                try:
                    ax, ay = self._floor_axis(index, point, radius + leave)
                except Exception as exc:
                    self._floor_debt(index, exc, facts)
                    return
            if str(op.get("do", "")).startswith("rough_") and _number(op.get("to_z")):
                level = max(level, op["to_z"])
            placed.append((index, point, ax, ay, level + LIFT, normal.z < -1e-3))
        if hole_cut is not None:
            for centre in hole_cut["centres"]:
                placed.append((indices[0], centre, centre.x, centre.y, centre.z + LIFT, False))
        top = self.box[5]
        part = self._culled_part()
        # Reach: highest material within r + band of the tool axis above each sample.
        reach = 0.0
        for _, _, ax, ay, tip, downward in sorted(
            placed, key=lambda item: (item[4], item[0], item[2], item[3])
        ):
            if downward:
                continue
            if top - (tip - LIFT) <= reach:
                break
            common = part.common(ax, ay, radius + REACH_BAND, tip, top + 1.0)
            if common is not None:
                reach = max(reach, _bbox(common)[5] - (tip - LIFT))
        facts["reach_depth_mm"] = UNKNOWN if sample_reason else _r(reach)
        if sample_reason:
            reasons["reach_depth_mm"] = sample_reason
        if holder_missing:
            facts["holder_wall_hits"] = UNKNOWN
            reasons["holder_wall_hits"] = "op lacks " + ", ".join(holder_missing)
        else:
            facts["holder_wall_hits"] = sum(
                1
                for _, _, ax, ay, tip, downward in placed
                if not downward and part.common(*self._holder(ax, ay, tip, holder)) is not None
            )
        if sample_reason:
            facts["holder_wall_hits"] = UNKNOWN
            reasons["holder_wall_hits"] = sample_reason
        # A hole op's tool stands on its bore axis LIFT narrower and LIFT higher than any
        # sample, so its own matched caps need no own-face shell (a cone apex has no
        # offset): unmodified stock keeps every wrong profile's or depth's real hit. The
        # cached shell regions stay untouched, so no other op borrows this exemption.
        caps = self._own_caps(indices) if hole_cut is not None else ()
        regions = {
            index: (self._culled_part(), None) if index in caps else self._region(index)
            for index in indices
        }
        flute_regions = self._flute_regions(op, regions, radius, hole_cut=hole_cut)
        region_reason = (
            "; ".join(reason for _, reason in regions.values() if reason is not None) or None
        )
        tool_ready = flute is not None and region_reason is None
        holder_ready = not holder_missing and region_reason is None
        # One op holds its obstacles, fixture, radius, slope and flute fixed, so a
        # non-downward pose's labels and uncertainty are a pure function of its kind, own
        # face (its obstacle and excluded ref) and exact cylinder, which for a tool carries
        # the exact cutter axis and tip. Its refs are not: they may omit refs already in
        # ``known``, that kind's ref union so far. The union is their sole consumer and only
        # grows within this op and kind, so union | refs stays exact on every reuse.
        # Repeated poses classify once per op; every placed row still counts, so sample
        # multiplicity and full counts stay exact.
        outcomes, cutters = {}, {}

        def classify(kind, index, ax, ay, tip, cylinder, known):
            labels, refs = set(), frozenset()
            obstacle = (flute_regions if kind == "tool" else regions)[index][0]
            # A pointed tool's flute is its cone and body, for part and jaws alike; its
            # gross cylinder only culls. Holders keep their own cylinder. The read-only
            # cutter is shared by every own face posing that exact recipe.
            solid = None
            if kind == "tool" and slope is not None:
                recipe = (ax, ay, tip, radius - LIFT, slope, flute)
                if recipe not in cutters:
                    cutters[recipe] = _pointed_cutter(*recipe)
                solid = cutters[recipe]
            common = obstacle.common(*cylinder, solid) if obstacle is not None else None
            if common is not None:
                labels.add("part")
                if solid is not None:
                    refs = frozenset(self._hit_refs(common, cylinder, index, solid, known))
                else:
                    # The shared cache holds only full ref sets: partial ones stay local.
                    key = (cylinder, index)
                    if key in obstacle.hit_refs:
                        refs = frozenset(obstacle.hit_refs[key])
                    elif known:
                        refs = frozenset(self._hit_refs(common, cylinder, index, known=known))
                    else:
                        obstacle.hit_refs[key] = self._hit_refs(common, cylinder, index)
                        refs = frozenset(obstacle.hit_refs[key])
            if self.fixture_ready:
                labels.update(self._fixture_cylinder_hits(cylinder, solid))
            uncertain = not labels and bool(
                not self.fixture_ready
                or self.fixture_gaps
                or any(_tool_hits_box(cylinder, box, solid) for _, box in self.fixture_possible)
            )
            return frozenset(labels), refs, uncertain

        # Per kind: certain hits, hits only in the undeclared jaw extension, labels, refs.
        counters = {"tool": [0, 0, set(), set()], "holder": [0, 0, set(), set()]}
        for index, _, ax, ay, tip, downward in placed:
            checks = []
            if flute is not None:
                checks.append(("tool", (ax, ay, radius - LIFT, tip, tip + flute)))
            if not holder_missing:
                checks.append(("holder", self._holder(ax, ay, tip, holder)))
            for kind, cylinder in checks:
                counter = counters[kind]
                if downward:
                    if kind == "tool":
                        counter[0] += 1
                        counter[2].add("part")
                    continue
                pose = (kind, index, cylinder)
                if pose not in outcomes:
                    outcomes[pose] = classify(kind, index, ax, ay, tip, cylinder, counter[3])
                labels, refs, uncertain = outcomes[pose]
                counter[3].update(refs)
                if labels:
                    counter[0] += 1
                    counter[2].update(labels)
                elif uncertain:
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
            facts["min_hits"][kind] = certain
            if sample_reason:
                facts[key] = UNKNOWN
                reasons[key] = sample_reason
            elif not ready:
                facts[key] = UNKNOWN
                reasons[key] = missing
            elif not self.fixture_ready:
                facts[key] = UNKNOWN
                reasons[key] = (
                    f"fixture solids unresolved ({self.fixture_reason}); "
                    f"{certain} sample(s) hit part material"
                )
            elif uncertain and self.fixture_gaps:
                facts[key] = UNKNOWN
                reasons[key] = (
                    f"undrawn fixture components ({'; '.join(self.fixture_gaps)}); "
                    f"{certain} sample(s) certainly hit"
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

    def _hit_refs(self, common, cylinder, own, solid=None, known=()):
        """Finished face refs bounding a hit, excluding only the sampled face itself.

        ``solid`` is the cutter inside ``cylinder`` when it is not the cylinder itself.
        Only the per-op union is observable: labels already proven for this kind
        need no repeated boolean/distance query. A returned partial set must not
        enter a cross-operation pose cache.
        """
        refs = set()
        common_box = _tolerant_box(common)
        for index, face in enumerate(self.faces):
            if self.owner.labels[index] in known:
                continue
            if index == own or not _cylinder_hits_box(*cylinder, self.face_boxes[index], True):
                continue
            if _distant_box(common_box, self.face_boxes[index]):
                continue
            if solid is None:
                ax, ay, radius, z0, z1 = cylinder
                solid = Part.makeCylinder(radius, z1 - z0, V(ax, ay, z0))
            # Most AABB candidates miss the face itself. Reject those before measuring
            # distance to the much more complex stock/tool intersection.
            if face.common(solid).Area > CONTACT_MM2 and _distance(common, face)[0] < 1e-6:
                refs.add(self.owner.labels[index])
        return refs

    # ------------------------------------------------------------------ turning

    _TURN_TOOL = (
        "radius_mm",
        "insert_angle_deg",
        "entering_angle_deg",
        "edge_len_mm",
        "head_len_mm",
        "shank_width_mm",
        "functional_width_mm",
    )
    _TURN_HOLDER = ("projection_mm", "holder_body_width_mm", "holder_body_depth_mm")

    def _revolution(self, index):
        """(verdict, meridian samples, undefined normals) of a finished face about setup Z.

        ``verdict`` is "external", "internal" (a normal points toward the axis: boring) or
        "away" (a normal leaves its meridian plane: not a surface of revolution about the
        spindle axis). Meridian samples are ((r, z), (n_r, n_z)) pairs; a pole on the axis
        with an axial normal (a dome's apex), which the grid never lands on, is one too.
        """
        if index not in self.revolutions:
            found, skipped = _face_samples(self.faces[index], 1.0)
            verdict, meridian = "external", []
            for point, normal in found:
                rho = math.hypot(point.x, point.y)
                if rho <= AXIS_TOL:
                    if math.hypot(normal.x, normal.y) > REVOLVED_TOL:
                        verdict = "away"
                        break
                    meridian.append(((0.0, point.z), (0.0, normal.z)))
                    continue
                ex, ey = point.x / rho, point.y / rho
                if abs(normal.y * ex - normal.x * ey) > REVOLVED_TOL:
                    verdict = "away"
                    break
                radial = normal.x * ex + normal.y * ey
                if radial < -REVOLVED_TOL:
                    verdict = "internal"
                meridian.append(((rho, point.z), (radial, normal.z)))
            if verdict == "external" and found:
                face = self.faces[index]
                for vertex in face.Vertexes:
                    point = vertex.Point
                    if math.hypot(point.x, point.y) > BBOX_TOL:
                        continue
                    try:
                        normal = _normal_at(face, point)
                    except Exception:
                        continue
                    if math.hypot(normal.x, normal.y) <= REVOLVED_TOL and normal.Length > 0.5:
                        meridian.append(((0.0, point.z), (0.0, normal.z)))
            self.revolutions[index] = (verdict, meridian, skipped if found else max(skipped, 1))
        return self.revolutions[index]

    def _turn_split(self, indices):
        """Claimed indices: turnable, not revolved, (index, undefined normals), internal."""
        valid, away, undefined, internal = [], [], [], []
        for index in indices:
            verdict, _, skipped = self._revolution(index)
            if verdict == "away":
                away.append(index)
            elif skipped:
                undefined.append((index, skipped))
            elif verdict == "internal":
                internal.append(index)
            else:
                valid.append(index)
        return valid, away, undefined, internal

    def _outer(self):
        """A radius beyond every point of the held stock."""
        x0, y0, _, x1, y1, _ = self.box
        return math.hypot(max(abs(x0), abs(x1)), max(abs(y0), abs(y1))) + 1.0

    def _turn_removal(self, op, valid):
        """(revolved stock outside the finished part this turning op removes or None, why).

        A ``to_z`` op faces: everything beyond the plane on its claims' axial side, outside
        their innermost radius, up to the finished part's end on that side (a shoulder) or
        the stock end when nothing finished lies beyond (an end face). A facing op, part-off
        or cut-to-fit given ``to_dia_mm`` sweeps from to_dia/2 (0: the axis) to the stock end
        instead: the separated piece goes, whatever bore the part receives later. Other ops
        cut down to each claimed meridian; with ``z_from``/``z_to`` the profile is extended at
        its end radii and its axial faces swept along their normals to the window, then
        limited to it. Without a window removal stays within the claimed faces' own z extent.
        """
        if not valid:
            return None, None
        meridians = [self._revolution(index)[1] for index in valid]
        outer = self._outer()
        window = None
        if "z_from" in op or "z_to" in op:
            ends = (op.get("z_from"), op.get("z_to"))
            if not all(_number(end) for end in ends):
                return None, "z_from/z_to is unknown"
            window = (min(ends), max(ends))
            if window[1] - window[0] <= PLANE_TOL:
                return None, "z_from and z_to span no length"
        regions = []
        if op.get("to_z") is not None:
            to_dia = op.get("to_dia_mm")
            if "to_dia_mm" in op and not (_number(to_dia) and to_dia >= 0):
                return None, "to_dia is unknown"
            region, why = self._facing_region(meridians, op["to_z"], outer, to_dia)
            if why is not None:
                return None, why
            regions.append(region)
        else:
            regions.extend(self._profile_regions(meridians, window, outer))
        regions = [region for region in regions if region is not None]
        if not regions:
            return None, None
        removal = regions[0].fuse(regions[1:]) if len(regions) > 1 else regions[0]
        if window is not None:
            removal = removal.common(_band(0.0, outer, *window))
        removal = removal.cut(self.finished)
        if removal.Volume <= HIT_MM3:
            return None, None
        return removal, None

    def _facing_region(self, meridians, to_z, outer, to_dia=None):
        samples = [sample for meridian in meridians for sample in meridian]
        sides = {1 if nz > 0 else -1 for _, (_, nz) in samples if abs(nz) > REVOLVED_TOL}
        if len(sides) != 1:
            return None, "to_z facing needs every claimed face to face one axial side"
        side = sides.pop()
        stock_end = self.box[5] + 1.0 if side > 0 else self.box[2] - 1.0
        if to_dia is not None:
            return _band(to_dia / 2, outer, min(to_z, stock_end), max(to_z, stock_end)), None
        inner = min(r for (r, _), _ in samples)
        x0, y0, z0, x1, y1, z1 = _bbox(self.finished)
        finished_end = z1 if side > 0 else z0
        beyond = (finished_end - to_z) * side > PLANE_TOL
        end = finished_end if beyond else stock_end
        return _band(inner, outer, min(to_z, end), max(to_z, end)), None

    def _profile_regions(self, meridians, window, outer):
        regions, ends = [], []
        for meridian in meridians:
            if not meridian:
                continue
            zs = [z for (_, z), _ in meridian]
            if max(zs) - min(zs) <= PLANE_TOL:
                # An axial face: swept along its normal to the window, else nothing.
                nz = max((n for _, (_, n) in meridian), key=abs)
                if window is None or abs(nz) <= REVOLVED_TOL:
                    continue
                z = zs[0]
                inner = min(r for (r, _), _ in meridian)
                end = window[1] if nz > 0 else window[0]
                regions.append(_band(inner, outer, min(z, end), max(z, end)))
                continue
            chain = sorted({(r, z): (nr, nz) for (r, z), (nr, nz) in meridian}.items())
            chain.sort(key=lambda item: (item[0][1], item[0][0]))
            # Chords of a concave meridian run through air: push every point into the
            # material by the largest chord sagitta, so no sliver of overstock survives;
            # cutting the finished part back out keeps the region exact. The region closes
            # through the unshifted end points, so no slab survives under its ends either.
            sag = 0.0
            for ((r0, z0), n0), ((r1, z1), n1) in zip(chain, chain[1:], strict=False):
                cos = max(-1.0, min(1.0, n0[0] * n1[0] + n0[1] * n1[1]))
                angle = math.acos(cos)
                sag = max(sag, math.hypot(r1 - r0, z1 - z0) / 2 * math.tan(min(angle, 3.0) / 4))
            sag += 1e-6
            points = [(r - nr * sag, z - nz * sag) for (r, z), (nr, nz) in chain]
            first, last = chain[0][0], chain[-1][0]
            polygon = []
            for point in [*points, last, (outer, last[1]), (outer, first[1]), first]:
                if not polygon or math.dist(point, polygon[-1]) > 1e-5:
                    polygon.append(point)
            if math.dist(polygon[0], polygon[-1]) <= 1e-5:
                polygon.pop()
            regions.append(_revolved_side(polygon))
            ends.append((chain[0][0][1], chain[0][0][0], chain[-1][0][1], chain[-1][0][0]))
        if window is not None and ends:
            low = min(ends, key=lambda end: end[0])
            high = max(ends, key=lambda end: end[2])
            regions.append(_band(low[1], outer, window[0], low[0]))
            regions.append(_band(high[3], outer, high[2], window[1]))
        return regions

    def _turn_cut(self, op):
        """(this turning op's revolved removal or None, and why it cannot be derived)."""
        valid, _, why = self._claims(op)
        if not isinstance(valid, list):
            return None, why
        to_z = op.get("to_z")
        if to_z is not None and not _number(to_z):
            return None, "to_z is unknown"
        try:
            return self._turn_removal(op, valid)
        except Exception as exc:
            return None, f"turned removal boolean failed ({exc})"

    def _turn_obstacle(self, op):
        """(the profile after this op, or None, and why not): the held stock minus the
        revolved removals of the setup's turning ops up to and including this one."""
        subject = self._subject(op)
        if subject not in self.turn_obstacles:
            stock, failed = self.part, None
            for other in self.ops:
                if not _turned(other):
                    continue
                name = self._subject(other)
                if name in self.turn_obstacles:
                    stock, failed = self.turn_obstacles[name]
                    continue
                if failed is None:
                    removal, why = self._turn_cut(other)
                    if why is None and removal is not None:
                        try:
                            stock = stock.cut(removal)
                        except Exception as exc:
                            why = f"turned removal boolean failed ({exc})"
                    if why is not None:
                        stock, failed = None, (name, why)
                self.turn_obstacles[name] = stock, failed
                if name == subject:
                    break
        stock, failed = self.turn_obstacles[subject]
        if failed is None:
            return stock, None
        name, why = failed
        whose = "this op's" if name == subject else f"earlier op {name}'s"
        return None, f"{whose} turned removal cannot be derived: {why}"

    @classmethod
    def _turn_tool(cls, op):
        """(turning-tool values, missing insert/head/shank keys, missing holder keys).

        ``corners = 2`` is a grooving/parting blade: both front corners nose radius
        ``radius_mm``, a square front edge ``blade_width_mm`` wide."""
        blade = op.get("corners") == 2
        keys = (*cls._TURN_TOOL, *(("blade_width_mm",) if blade else ()))
        tool = {key: _positive(op, key) for key in (*keys, *cls._TURN_HOLDER)}
        tool["feed_z"] = op.get("feed_z") if op.get("feed_z") in (-1, 1) else None
        tool["corners"] = 2 if blade else 1
        missing = sorted(key for key in (*keys, "feed_z") if tool[key] is None)
        if not missing and tool["insert_angle_deg"] + tool["entering_angle_deg"] >= 180:
            missing.append("insert_angle_deg + entering_angle_deg below 180")
        if blade and not missing:
            if abs(tool["entering_angle_deg"] - 90.0) > 1e-9:
                missing.append("entering_angle_deg 90 (a square blade front edge)")
            if tool["blade_width_mm"] < 2 * tool["radius_mm"]:
                missing.append("blade_width_mm at least twice radius_mm")
        holder = sorted(key for key in cls._TURN_HOLDER if tool[key] is None)
        if not holder and tool["projection_mm"] < tool["head_len_mm"]:
            holder.append("projection_mm at least head_len_mm")
        return tool, missing, holder

    @staticmethod
    def _turn_sections(tool, centre, holder):
        """(insert/blade + head polygon, [shank, toolpost body] polygons or None) in (r, z)
        for a nose (a blade's leading corner) centred at ``centre``."""
        nose = tool["radius_mm"]
        cr, cz = centre
        inner = nose - LIFT
        feed = tool["feed_z"]
        against = -feed

        def arc(z):
            return [
                (
                    cr + inner * math.cos(2 * math.pi * k / NOSE_ARC),
                    z + inner * math.sin(2 * math.pi * k / NOSE_ARC),
                )
                for k in range(NOSE_ARC)
            ]

        back = cz + against * tool["functional_width_mm"]
        lead = back - against * tool["shank_width_mm"]
        start = cr + tool["head_len_mm"]
        if tool["corners"] == 2:
            # Blade: both corners on the front edge, its sides straight back to head_len.
            trail = cz + against * (tool["blade_width_mm"] - 2 * nose)
            sides = [(start, cz - against * inner), (start, trail + against * inner)]
            section = _hull(arc(cz) + arc(trail) + sides)
        else:
            points = arc(cz)
            length = tool["edge_len_mm"]
            entering = math.radians(tool["entering_angle_deg"])
            for angle in (entering, entering + math.radians(tool["insert_angle_deg"])):
                dr, dz = math.sin(angle), feed * math.cos(angle)
                er, ez = cr + dr * length, cz + dz * length
                points += [(er - dz * inner, ez + dr * inner), (er + dz * inner, ez - dr * inner)]
            section = _hull(points + [(start, lead), (start, back)])
        if not holder:
            return section, None
        end = cr + tool["projection_mm"]
        far = end + tool["holder_body_depth_mm"]
        side = lead + against * tool["holder_body_width_mm"]
        return section, [
            [(start, lead), (end, lead), (end, back), (start, back)],
            [(end, lead), (far, lead), (far, side), (end, side)],
        ]

    def _turn_pose(self, tool, point, normal, segments):
        """(nose centre, axial extent) of the tool that cuts a meridian sample, posed on
        the profile after the op (``segments``, its meridian section).

        An insert's nose is tangent at the sample (centre ``point + r_e * normal``). A
        blade's front edge lies on a sample whose normal is radial, the blade anywhere
        along it that keeps the sample under the front edge and the blade clear (inside
        the groove: floor spans narrower than the blade are swept by that plunge); any
        other sample is cut by the corner nearest it (the leading corner when the normal
        points against the feed). Where that pose meets the profile at an exposed sample,
        the nose/blade moves to the nearest clear pose within twice the corner radius:
        tangent to both meridian segments of a concave corner, offset from the wall by
        the corner radius. A corner sharper than the nose is thus left for
        ``corner_radii_mm``, not counted as a collision; a buried sample keeps its pose.
        """
        nose, against = tool["radius_mm"], -tool["feed_z"]
        nr, nz = normal
        if tool["corners"] == 2:
            width = tool["blade_width_mm"]
            span = width - 2 * nose

            def free(centre):
                return _polygon_clear(self._turn_sections(tool, centre, False)[0], segments)

            def extent(centre):
                ends = (centre[1] - against * nose, centre[1] + against * (span + nose))
                return min(ends), max(ends)

            if abs(nz) <= REVOLVED_TOL and nr > 0:
                lowest = point[1] - width

                def centre_at(low):
                    return (point[0] + nose, low + nose if against > 0 else low + width - nose)

                nominal = point[1] - nose if against > 0 else lowest + nose
                lows = {nominal} | {lowest + width * k / 32 for k in range(33)}
                # Snap to wall heights so a blade as wide as its groove still fits exactly.
                band = (-math.inf, lowest, math.inf, point[1] + width)
                for _, z0, _, z1 in _near(segments, band):
                    lows |= {z0, z0 - width, z1, z1 - width}
                for low in sorted(
                    (low for low in lows if lowest <= low <= point[1]),
                    key=lambda low: (abs(low - nominal), low),
                ):
                    if free(centre_at(low)):
                        return centre_at(low), extent(centre_at(low))
                start = centre_at(nominal)
            else:
                corner = (point[0] + nr * nose, point[1] + nz * nose)
                leading = nz * against > 0
                start = corner if leading else (corner[0], corner[1] - against * span)
        else:

            def free(centre):
                return _disk_clear(centre, nose - LIFT, segments)

            def extent(centre):
                return centre[1] - nose, centre[1] + nose

            start = (point[0] + nr * nose, point[1] + nz * nose)
        if free(start):
            return start, extent(start)
        exposed = not _in_material(point, segments) or any(
            _segment_distance(point, seg) <= 10 * MERIDIAN_DEFLECTION for seg in segments
        )
        moved = _nearest_free(free, start, 2 * nose) if exposed else None
        return (moved, extent(moved)) if moved is not None else (start, extent(start))

    def _turn_fixture(self, solid):
        """Names of placed fixture solids a revolved tool meets; None while none are placed."""
        if not self.fixture_ready:
            return None
        return self._fixture_hits(solid)

    def _turn_op(self, op, indices):
        """Revolved turning-tool facts for an op (module docstring: Turning)."""
        labels = self.owner.labels
        valid, away, undefined, internal = self._turn_split(indices)
        facts = {"approach": TURNING, "reasons": {}}
        reasons = facts["reasons"]
        facts["claim_errors"] = sorted(labels[index] for index in away)
        if internal:
            facts["unsupported_reason"] = _internal_reason(labels, internal)
        if undefined:
            facts["claimed_indices"] = UNKNOWN
            reasons["claimed_indices"] = self._undefined(undefined)
        elif internal:
            facts["claimed_indices"] = UNKNOWN
            reasons["claimed_indices"] = facts["unsupported_reason"]
        else:
            facts["claimed_indices"] = sorted(valid)
        sampled = sorted(valid + [index for index, _ in undefined])
        if not sampled:
            reason = facts.get("unsupported_reason") or (
                "no claimed face is a surface of revolution about the spindle axis: "
                + ", ".join(facts["claim_errors"])
            )
            for key in (*self._MEASURED, "corner_radii_mm"):
                facts[key] = UNKNOWN
                reasons[key] = reason
        else:
            corner = self._turn_corners(sampled) if not undefined else reasons["claimed_indices"]
            facts["corner_radii_mm"] = corner if isinstance(corner, list) else UNKNOWN
            if not isinstance(corner, list):
                reasons["corner_radii_mm"] = corner
            tool, missing, holder_missing = self._turn_tool(op)
            if missing:
                for key in self._MEASURED:
                    facts[key] = UNKNOWN
                    reasons[key] = "op lacks " + ", ".join(missing)
            else:
                self._turn_samples(op, sampled, tool, holder_missing, facts)
                if undefined or internal:
                    for key in self._MEASURED:
                        if facts.get(key) != UNKNOWN:
                            facts[key] = UNKNOWN
                            reasons[key] = reasons["claimed_indices"]
        unknown = [
            reasons[key]
            for key in ("claimed_indices", *self._MEASURED, "corner_radii_mm")
            if key in reasons
        ]
        if unknown:
            facts["reason"] = unknown[0]
        return facts

    def _turn_samples(self, op, indices, tool, holder_missing, facts):
        reasons = facts["reasons"]
        meridian = {}
        for index in indices:
            for point, normal in self._revolution(index)[1]:
                key = (round(point[0], 6), round(point[1], 6))
                meridian.setdefault(key, (index, point, normal))
        samples = [meridian[key] for key in sorted(meridian)]
        to_z = op.get("to_z")
        sides = {1 if n[1] > 0 else -1 for _, _, n in samples if abs(n[1]) > REVOLVED_TOL}
        if _number(to_z) and len(sides) == 1 and samples:
            # A facing/parting op leaves its to_z plane: it is posed there, across the
            # claims' radii (and down to to_dia/2 when it parts to a diameter).
            side, faced = sides.pop(), {}
            radii = [(index, point[0]) for index, point, _ in samples]
            if _number(op.get("to_dia_mm")) and op["to_dia_mm"] >= 0:
                radii.append((samples[0][0], op["to_dia_mm"] / 2))
            for index, r in radii:
                faced.setdefault(round(r, 6), (index, (r, float(to_z)), (0.0, float(side))))
            samples = [faced[key] for key in sorted(faced)]
        facts["sample_count"] = len(samples)
        obstacle, obstacle_reason = self._turn_obstacle(op)
        # Without the post-op profile only finished material is a certain obstacle.
        part = obstacle if obstacle is not None else self.finished
        try:
            segments = _meridian_segments(part)
        except Exception as exc:
            segments = []
            obstacle_reason = obstacle_reason or f"meridian section for tool poses failed ({exc})"
        part_box = _bbox(part)
        placed = self.fixture_ready
        outer = self._outer()
        counters = {"tool": [0, set(), set()], "holder": [0, set(), set()]}
        uncertain = {"tool": 0, "holder": 0}
        reach, wall_hits = 0.0, 0
        for index, point, normal in samples:
            # Without a section (its reason keeps the hits unknown) the pose is nominal.
            centre, (low, high) = self._turn_pose(tool, point, normal, segments)
            section, pieces = self._turn_sections(tool, centre, not holder_missing)
            solids = {"tool": _revolved(section)}
            if pieces is not None:
                parts = [solid for solid in map(_revolved, pieces) if solid is not None]
                solids["holder"] = parts[0].fuse(parts[1:]) if len(parts) > 1 else parts[0]
            for kind, solid in solids.items():
                if solid is None:
                    continue
                labels = set()
                if _boxes_overlap(_bbox(solid), part_box):
                    common = solid.common(part)
                    if common.Volume > HIT_MM3:
                        labels.add("part")
                        counters[kind][2].update(
                            self._turn_hit_refs(common, solid, index, counters[kind][2])
                        )
                        wall_hits += kind == "holder"
                labels.update(self._turn_fixture(solid) or ())
                if labels:
                    counters[kind][0] += 1
                    counters[kind][1].update(labels)
                elif self.fixture_gaps or any(
                    _boxes_overlap(_bbox(solid), box) for _, box in self.fixture_possible
                ):
                    uncertain[kind] += 1
            # Reach: material radius beside the nose/blade (within its axial extent) beyond
            # the sample.
            band = _band(point[0], outer, low, high)
            if band is not None:
                common = band.common(self.part)
                if common.Volume > HIT_MM3:
                    reach = max(reach, _max_radius(common) - point[0])
        facts["obstacles"] = {kind: sorted(counters[kind][1]) for kind in counters}
        facts["hit_refs"] = {kind: sorted(counters[kind][2]) for kind in counters}
        facts["min_hits"] = {kind: counters[kind][0] for kind in counters}
        facts["reach_depth_mm"] = _r(reach)
        holder_reason = ("op lacks " + ", ".join(holder_missing)) if holder_missing else None
        if holder_reason or obstacle_reason:
            facts["holder_wall_hits"] = UNKNOWN
            reasons["holder_wall_hits"] = holder_reason or obstacle_reason
        else:
            facts["holder_wall_hits"] = wall_hits
        for kind in counters:
            key, certain = kind + "_hits", counters[kind][0]
            if kind == "holder" and holder_reason:
                facts[key] = UNKNOWN
                reasons[key] = holder_reason
            elif obstacle_reason:
                facts[key] = UNKNOWN
                reasons[key] = f"{obstacle_reason}; {certain} sample(s) hit finished material"
            elif not placed:
                facts[key] = UNKNOWN
                reasons[key] = (
                    f"fixture solids unresolved ({self.fixture_reason}); "
                    f"{certain} sample(s) hit part material"
                )
            elif uncertain[kind] and self.fixture_gaps:
                facts[key] = UNKNOWN
                reasons[key] = (
                    f"undrawn fixture components ({'; '.join(self.fixture_gaps)}); "
                    f"{certain} sample(s) certainly hit"
                )
            elif uncertain[kind]:
                facts[key] = UNKNOWN
                reasons[key] = (
                    f"{uncertain[kind]} sample(s) clear of placed solids reach undeclared "
                    f"fixture extents; {certain} sample(s) certainly hit"
                )
            else:
                facts[key] = certain

    def _turn_hit_refs(self, common, solid, own, known=()):
        """New refs bounding a turning-tool hit; already-proven union members stay known."""
        box, refs = _bbox(solid), set()
        common_box = _tolerant_box(common)
        for index, face in enumerate(self.faces):
            if self.owner.labels[index] in known:
                continue
            if index == own or not _boxes_overlap(box, self.face_boxes[index]):
                continue
            if _distant_box(common_box, self.face_boxes[index]):
                continue
            if face.common(solid).Area > CONTACT_MM2 and _distance(common, face)[0] < 1e-6:
                refs.add(self.owner.labels[index])
        return refs

    def _turn_corners(self, indices):
        """Sorted concave meridian corner radii between/inside claims, or why unknown."""
        part, faces, labels = self.finished, self.faces, self.owner.labels
        radii, problems = set(), []
        for index in indices:
            face = faces[index]
            surface = face.Surface
            if isinstance(surface, (Part.Plane, Part.Cylinder, Part.Cone)):
                continue  # straight meridians have no concave corner of their own
            if not _curved_concave(part, face):
                continue
            if isinstance(surface, Part.Toroid):
                radii.add(_r(surface.MinorRadius))
            elif isinstance(surface, Part.Sphere):
                radii.add(_r(surface.Radius))
            else:
                problems.append(f"{labels[index]} is a concave {type(surface).__name__} surface")
        for edge, a, b in _shared_edges(faces, indices):
            if _concave_edge(part, edge, faces[a], faces[b]):
                radii.add(0.0)
        if problems:
            extra = f" (+{len(problems) - 3} more)" if len(problems) > 3 else ""
            return "; ".join(problems[:3]) + extra
        return sorted(radii)

    def _chuck_walls(self, facts):
        """min_wall_mm: the shortest material run under a chuck jaw, from its contact inward.

        Sampled in the chuck frame on the radial line through every jaw at ``WALL_LEVELS``
        depths of the grip zone, so a lathe chuck on setup Z and a dividing head's chuck on
        a horizontal axis are measured alike; a solid bar's run crosses the axis (a full
        diameter), a tube's is its wall.
        """
        chuck = self.chuck
        reasons = facts["reasons"]
        local = self.part.copy()
        local.transformShape(chuck["matrix"].inverse())
        x0, y0, _, x1, y1, _ = _bbox(local)
        outer = math.hypot(max(abs(x0), abs(x1)), max(abs(y0), abs(y1))) + 1.0
        grip = chuck["grip"]
        runs = []
        for angle in chuck["local_angles_deg"]:
            dx, dy = math.cos(math.radians(angle)), math.sin(math.radians(angle))
            for k in range(WALL_LEVELS):
                z = -grip * (k + 0.5) / WALL_LEVELS
                line = Part.makeLine(V(dx * outer, dy * outer, z), V(-dx * outer, -dy * outer, z))
                pieces = local.common(line).Edges
                if pieces:
                    first = max(
                        pieces,
                        key=lambda e: max(v.Point.x * dx + v.Point.y * dy for v in e.Vertexes),
                    )
                    runs.append(first.Length)
        if not runs:
            reasons["min_wall_mm"] = "no held material lies under the chuck jaws in the grip zone"
            return
        facts["min_wall_mm"] = _r(min(runs))
        reasons.pop("min_wall_mm", None)

    def _revolution_facts(self, facts):
        """revolved: each declared feature's finished faces of revolution about setup Z.

        ``z_mm`` is their axial extent and ``radii_mm`` the least/greatest distance from the
        spindle axis: the greatest over boundary vertices and edges (a curved face of
        revolution carries a meridian on its boundary, its seam or an angular limit; a planar
        one its outer circle), the least by distance to the axis (a disk reaches it inside its
        boundary). ``end_radii_mm`` is the greatest boundary radius at each axial end and
        ``kinds`` the surface kinds. A feature whose references are unknown/unmapped, or with
        any face that is not an external surface of revolution about setup Z through
        x = y = 0, is omitted with its reason under ``revolved_reasons``. When none of its
        faces is revolved about setup Z and one is a cylinder/cone/torus/surface of
        revolution whose axis is not parallel to setup Z, ``revolved_off_axis`` also gives
        that axis: the feature is turned (if at all) about another direction.
        """
        revolved, reasons, off_axis = {}, {}, {}
        for name, indices in sorted(self.owner.features.items()):
            if not isinstance(indices, list) or not indices:
                reasons[name] = "face references are unknown or unmapped"
                continue
            problems, kinds, points, axes, away = [], set(), [], [], 0
            for index in indices:
                verdict, _, skipped = self._revolution(index)
                label = self.owner.labels[index]
                face = self.faces[index]
                if verdict == "away":
                    away += 1
                    problems.append(f"{label} is not revolved about setup Z through x = y = 0")
                    surface = face.Surface
                    direction = getattr(surface, "Direction", None)
                    if type(surface).__name__ in {"Cylinder", "Cone", "Toroid"}:
                        direction = surface.Axis
                    if direction is not None and abs(direction.dot(Z)) < PARALLEL:
                        axes.append([_r(value) for value in direction])
                elif verdict == "internal":
                    problems.append(f"{label} is an internal (bored) surface")
                elif skipped:
                    problems.append(f"{label} has {skipped} undefined normal sample(s)")
                kinds.add(type(face.Surface).__name__)
                points.extend(vertex.Point for vertex in face.Vertexes)
                for edge in face.Edges:
                    if not edge.Degenerated and edge.Length >= 1e-7:
                        points.extend(edge.discretize(Deflection=1e-4))
            if problems:
                extra = f" (+{len(problems) - 3} more)" if len(problems) > 3 else ""
                reasons[name] = "; ".join(problems[:3]) + extra
                if axes and away == len(indices):
                    off_axis[name] = {"axis": axes[0]}
                continue
            meridian = [(math.hypot(point.x, point.y), point.z) for point in points]
            low = min(z for _, z in meridian)
            high = max(z for _, z in meridian)
            axis = Part.makeLine(V(0, 0, low - 1), V(0, 0, high + 1))
            least = min(self.faces[index].distToShape(axis)[0] for index in indices)
            revolved[name] = {
                "z_mm": [_r(low), _r(high)],
                "radii_mm": [_r(least), _r(max(r for r, _ in meridian))],
                "end_radii_mm": [
                    _r(max(r for r, z in meridian if z - low <= PLANE_TOL)),
                    _r(max(r for r, z in meridian if high - z <= PLANE_TOL)),
                ],
                "kinds": sorted(kinds),
            }
        facts["revolved"] = revolved
        facts["revolved_reasons"] = reasons
        facts["revolved_off_axis"] = off_axis


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
