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
  2026-10-05, floor samples on or within r of any concave floor-edge (curved
  ones included) shift along the wall's normal at the nearest edge point until
  tangent to every such wall. Convex edges and farther samples are unchanged.
  A +Z planar floor (outside hole ops) whose whole face fits inside the actual
  cutter disc instead gets exactly one pose and no samples or corners: the area
  centroid of every axis whose disc covers its outer wire (exact for line and
  Z-circle edges; a single covering axis is certified as the unique minimal
  enclosing centre; no STOCK_TOL widening), or, with concave rising Z-circle
  walls only, a wall centre meeting every such wall's tangent-circle floor bound
  |c - o| <= rho - r. A rough leave or any
  other rising wall leaves the face on its samples. An outer contour with other
  curves, unless exact face points prove no disc covers it, or a failed native
  locus, makes that floor's pose undefined: its poses drop, every other face's
  certain hits stay, and the op's measured facts become unknown with the reason.
  This is face-inside-cutter only; a face larger than the cutter keeps samples.
  Milling tips (rough or finish) stand at their numeric to_z when above the finished
  face, and hole tools follow their geometry-matched axis to their declared depth
  or through extent. Spot/drill flutes use their point cone plus full-radius body;
  flat tools use an r x flute_len cylinder. The holder starts at tip + projection.
  Both shrink/lift by ``LIFT``.
  Far-side faces cannot be claimed from that setup; undefined normals remain debt.
* Obstacles: stock minus the sampled face's ``LIFT``-thick inward shell, plus
  placed fixture solids. A hole's known matched cap keeps unmodified stock instead
  of an unrepresentable apex shell. The flute meets the stock this setup's earlier
  ops leave, derived once in op order before measuring, less its own actual cut;
  later cuts are never credited, and after an underivable earlier cut only
  finished material counts and tool hits stay unknown. Holders and reach retain
  all setup-entry stock. Unrelated component-owned finished features remain
  obstacles. Milling only: turning keeps its own turned-profile obstacle. A hole's
  own bore radius is sizing, not a corner.
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
  span and limited to it, intersected with the current post-op stock, minus
  component-owned finished material. Null or zero-volume remnants are not removal.
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
import sys
import tempfile
import time

from contextlib import contextmanager

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import FreeCAD  # noqa: E402
import Part  # noqa: E402
from step_faces import FaceRefError, StepError, StepFile  # noqa: E402
from render_diagram import render_diagram  # noqa: E402

UNKNOWN = "unknown"
LIFT = 1e-3  # mm: cylinders shrink radially and lift off the sample by this clearance
GRID = 5  # cell-centred UV samples per face direction
EDGE_SAMPLES = (2, 12)  # per boundary edge
AWAY = -1e-3  # outward normal z below which a face points away from the tool approach
HIT_MM3 = 1e-6  # common volume that counts as an intersection
STOCK_TOL = 1e-3  # mm: as-is face distance to the envelope, claimed-face contact
COVER_MM = 0.01  # mm outside a claimed face where remaining stock means it is not cleared
STOCK_MM3 = 1e-3  # mm^3: finished material outside the envelope, or a detached stock piece
TUBE_REL = 1e-3  # pipe volume vs pi r^2 L: a lineage-skin edge tube must be whole
CONTACT_MM2 = 1e-6  # face/jaw common area that counts as a face inside a jaw
REACH_BAND = 0.05  # mm beyond the cutter radius in which walls set reach depth
FACING_ACTIONS = {"face", "rough_face", "finish_face"}  # sweeps that span planar inner loops
AREA_REL = AREA_ABS = 1e-6  # face-signature area tolerance (relative, absolute mm^2)
BBOX_TOL = 1e-4  # mm, face-signature bbox tolerance
PLANE_TOL = 1e-6  # mm, coplanarity of contact faces / interval ends
PARALLEL = 1 - 1e-9  # |cos| beyond which directions are parallel
COVER_TOL = 1e-9  # mm: numerical slack of the exact whole-face cover check, never a radius
COVER_GAP = 1e-7  # mm: boundary circles this near to touching meet at a tangent point
COVER_ANGLE = 1e-9  # rad: support-gap slack of the whole-face singleton certificate
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
# mm: how far a turning tool's section reaches below centre height (and its toolpost body
# either side of it) when posed against carriage-mounted follow rest jaws. No tool face
# height is modelled, so the tool is taken as unbounded there.
TOOL_DROP_MM = 1000.0
STOCK_AZIMUTHS = 6  # meridian sections (0..150 deg) that must agree for a stock profile
STOCK_ROUND_MM = 2e-3  # mm: radius disagreement between them that still counts as round
TURNING = "turning"
SAW_ACTIONS = {"saw_cut", "cut_off"}
# Facing-type turning actions sweep their claims along +Z (toward the free end).
AXIAL_TURNING = {"face", "cut_to_fit", "part_off"}
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


def _outer_radius(segments, z0, z1):
    """Greatest distance from Z of a section's chords within z0..z1 (clipped), or None
    when no chord reaches that band."""
    best = None
    for s0, za, s1, zb in segments:
        if max(za, zb) < z0 - PLANE_TOL or min(za, zb) > z1 + PLANE_TOL:
            continue
        if abs(zb - za) <= PLANE_TOL:
            values = (abs(s0), abs(s1))
        else:
            values = [
                abs(s0 + (z - za) / (zb - za) * (s1 - s0))
                for z in (max(min(za, zb), z0), min(max(za, zb), z1))
            ]
        best = max(values) if best is None else max(best, *values)
    return best


def _profile_rows(segments):
    """[z_lo, z_hi, r_lo, r_hi] bands of one meridian section's outer radius.

    Bands run between chord end stations; a band no chord spans (a gap in the material)
    is omitted. Within a band each spanning chord is linear: ``r_hi`` is the greatest
    radius any reaches, ``r_lo`` the greatest of their least radii, a lower bound on the
    outer radius anywhere in the band. Neighbouring bands with equal radii merge.
    """
    stations = sorted({round(z, 6) for c in segments for z in (c[1], c[3])})
    rows = []
    for z0, z1 in zip(stations, stations[1:], strict=False):
        spans = [
            [abs(s0 + (z - za) / (zb - za) * (s1 - s0)) for z in (z0, z1)]
            for s0, za, s1, zb in segments
            if abs(zb - za) > 1e-9 and min(za, zb) <= z0 + 1e-6 and max(za, zb) >= z1 - 1e-6
        ]
        if not spans:
            continue
        low, high = max(min(v) for v in spans), max(max(v) for v in spans)
        last = rows[-1] if rows else None
        if (
            last is not None
            and abs(last[1] - z0) <= 1e-6
            and abs(last[2] - low) <= 1e-6
            and abs(last[3] - high) <= 1e-6
        ):
            last[1] = z1
        else:
            rows.append([z0, z1, low, high])
    return rows


def _least_rows(states):
    """[z_lo, z_hi, r_lo, r_hi] bands over several ``_profile_rows`` states: wherever any
    state has material, ``r_lo`` is the least of the states' lower bounds there and
    ``r_hi`` the greatest of their upper bounds. Neighbouring equal bands merge."""
    stations = sorted({z for rows in states for row in rows for z in row[:2]})
    merged = []
    for z0, z1 in zip(stations, stations[1:], strict=False):
        if z1 - z0 <= 1e-9:
            continue
        middle = (z0 + z1) / 2
        present = [row for rows in states for row in rows if row[0] <= middle <= row[1]]
        if not present:
            continue
        low, high = min(row[2] for row in present), max(row[3] for row in present)
        last = merged[-1] if merged else None
        if (
            last is not None
            and abs(last[1] - z0) <= 1e-6
            and abs(last[2] - low) <= 1e-6
            and abs(last[3] - high) <= 1e-6
        ):
            last[1] = z1
        else:
            merged.append([z0, z1, low, high])
    return merged


def _revolved_rows(stock):
    """(``_profile_rows`` of a setup-frame solid, None), or (None, why) unless sections at
    STOCK_AZIMUTHS meridians cover the same length and agree on the outer radius at each
    band's ends and middle (a solid of revolution about setup Z)."""
    try:
        sections = []
        for k in range(STOCK_AZIMUTHS):
            turned = stock.copy()
            turned.rotate(V(0, 0, 0), V(0, 0, 1), 180.0 * k / STOCK_AZIMUTHS)
            sections.append(_meridian_segments(turned))
    except Exception as exc:
        return None, f"has no meridian section ({exc})"
    rows = _profile_rows(sections[0])
    length = sum(z1 - z0 for z0, z1, _, _ in rows)
    for section in sections[1:]:
        other = sum(z1 - z0 for z0, z1, _, _ in _profile_rows(section))
        if abs(other - length) > STOCK_ROUND_MM:
            return None, "is not a solid of revolution about setup Z"
        for z0, z1, _, _ in rows:
            for z in (z0 + (z1 - z0) / 8, (z0 + z1) / 2, z1 - (z1 - z0) / 8):
                here, base = _outer_radius(section, z, z), _outer_radius(sections[0], z, z)
                if here is None or base is None or abs(here - base) > STOCK_ROUND_MM:
                    return None, "is not a solid of revolution about setup Z"
    return rows, None


def _prism(polygon, y0, y1):
    """An (x, z) polygon at heights y0..y1 as a solid (x = the polygon's r), or None."""
    points = [V(r, y0, z) for r, z in polygon]
    try:
        return Part.Face(Part.makePolygon([*points, points[0]])).extrude(V(0, y1 - y0, 0))
    except Exception:
        return None


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


def _crossings(fx, fy, tx, ty, radius, along):
    """Where a line through ``(fx, fy)`` along unit ``(tx, ty)``, ``along`` from a circle's
    centre, crosses that circle of ``radius`` (one point when tangent, none when apart)."""
    square = radius * radius - along * along
    if square < -1e-9:
        return ()
    half = math.sqrt(max(square, 0.0))
    return ((fx + half * tx, fy + half * ty), (fx - half * tx, fy - half * ty))


def _nearest_clear(lines, discs):
    """The smallest axis move ``d`` meeting every bound, or None when none can.

    ``lines`` are half-planes ``n·d >= rhs`` as ``(nx, ny, rhs)``: the tangent at a wall
    edge's nearest point. ``discs`` are ``(cx, cy, rho)`` with ``|d - (cx, cy)| <= rho``:
    the exact axes clear of a circular wall concave toward the floor, ``rho`` its radius
    less the cutter's. The bounds are convex, so the answer is the unique projection of
    the origin onto them: the origin, one bound's own projection or two bound
    boundaries' intersection, and those finitely many candidates find it exactly.
    """
    candidates = [(0.0, 0.0)] + [(rhs * nx, rhs * ny) for nx, ny, rhs in lines]
    for cx, cy, rho in discs:
        length = math.hypot(cx, cy)
        if length > rho:
            candidates.append((cx - rho * cx / length, cy - rho * cy / length))
    for i, (ax, ay, ra) in enumerate(lines):
        for bx, by, rb in lines[i + 1 :]:
            determinant = ax * by - ay * bx
            if abs(determinant) > 1e-9:
                candidates.append(
                    ((ra * by - ay * rb) / determinant, (ax * rb - ra * bx) / determinant)
                )
        for cx, cy, rho in discs:
            along = ra - (ax * cx + ay * cy)
            candidates.extend(_crossings(cx + along * ax, cy + along * ay, -ay, ax, rho, along))
    for i, (ax, ay, ra) in enumerate(discs):
        for bx, by, rb in discs[i + 1 :]:
            gap = math.hypot(bx - ax, by - ay)
            if gap > 1e-9:
                ux, uy = (bx - ax) / gap, (by - ay) / gap
                along = (gap * gap + ra * ra - rb * rb) / (2 * gap)
                candidates.extend(_crossings(ax + along * ux, ay + along * uy, -uy, ux, ra, along))
    feasible = [
        (dx, dy)
        for dx, dy in candidates
        if all(nx * dx + ny * dy >= rhs - 1e-7 for nx, ny, rhs in lines)
        and all(math.hypot(dx - cx, dy - cy) <= rho + 1e-7 for cx, cy, rho in discs)
    ]
    return min(feasible, key=lambda d: d[0] ** 2 + d[1] ** 2) if feasible else None


def _arc_span(curve, first, last):
    """``(a0, a1)``, ``a0 < a1 <= a0 + 2 pi``: the directions from a Z-axis circle's centre
    to its points between curve parameters ``first`` and ``last``, counter-clockwise about
    +Z whatever the sign of the circle's axis or the orientation of its edge."""
    o = curve.Center
    start, end = curve.value(first), curve.value(last)
    a0 = math.atan2(start.y - o.y, start.x - o.x)
    a1 = math.atan2(end.y - o.y, end.x - o.x)
    if last - first >= 2 * math.pi - 1e-12:
        return a0, a0 + 2 * math.pi
    if curve.Axis.z < 0:
        a0, a1 = a1, a0
    while a1 <= a0:
        a1 += 2 * math.pi
    return a0, a1


def _cover_contour(face):
    """``(points, arcs, unsupported)`` of a planar face's outer wire.

    ``points`` are its vertices ``(x, y)``, exact face points; each Z-axis circle edge is
    ``(ox, oy, r, a0, a1)`` (:func:`_arc_span`); any other non-line edge is
    ``(type name, edge)``. Inner wires lie inside the outer wire's hull, so they never
    change which discs cover the face.
    """
    points, arcs, unsupported = [], [], []
    for edge in face.OuterWire.Edges:
        curve = edge.Curve
        if isinstance(curve, Part.Circle) and abs(curve.Axis.z) >= PARALLEL:
            span = _arc_span(curve, edge.FirstParameter, edge.LastParameter)
            arcs.append((curve.Center.x, curve.Center.y, curve.Radius, *span))
        elif not isinstance(curve, (Part.Line, Part.LineSegment)):
            unsupported.append((type(curve).__name__, edge))
        for vertex in edge.Vertexes:
            p = (vertex.Point.x, vertex.Point.y)
            if p not in points:
                points.append(p)
    return points, arcs, unsupported


def _cover_farthest(points, arcs, x, y):
    """The exact farthest distance from axis ``(x, y)`` to a :func:`_cover_contour`: a
    segment's farthest point is an end; an arc's is ``o + r (o - c) / |o - c|`` at
    ``|c - o| + r`` when that direction lies in its span, else an end."""
    far = max((math.hypot(px - x, py - y) for px, py in points), default=0.0)
    for ox, oy, r, a0, a1 in arcs:
        d = math.hypot(ox - x, oy - y)
        if d <= 1e-15:
            far = max(far, r)
            continue
        away = math.atan2(oy - y, ox - x)
        while away < a0:
            away += 2 * math.pi
        if away <= a1:
            far = max(far, d + r)
    return far


def _cover_certified(points, arcs, x, y, radius):
    """Whether 0 lies in the convex hull of the directions ``p - c`` to the contour points
    ``radius`` from ``c = (x, y)``: the smallest enclosing disc's optimality condition, so
    ``c`` is its unique centre and ``radius`` its radius. Supports are angles (a vertex, an
    arc's farthest point) or an arc's whole span when ``c`` is its centre; the origin is
    in their hull exactly when no angular gap between them exceeds pi."""
    spans = []
    for px, py in points:
        if math.hypot(px - x, py - y) >= radius - COVER_TOL:
            angle = math.atan2(py - y, px - x)
            spans.append((angle, angle))
    for ox, oy, r, a0, a1 in arcs:
        d = math.hypot(ox - x, oy - y)
        if d <= COVER_TOL:
            if r >= radius - COVER_TOL:
                spans.append((a0, a1))
            continue
        away = math.atan2(oy - y, ox - x)
        lifted = away
        while lifted < a0:
            lifted += 2 * math.pi
        if lifted <= a1 and d + r >= radius - COVER_TOL:
            spans.append((away, away))
    turn = 2 * math.pi
    if any(hi - lo >= turn - COVER_ANGLE for lo, hi in spans):
        return True
    if not spans:
        return False
    spans = sorted((lo % turn, lo % turn + hi - lo) for lo, hi in spans)
    widest, reach = 0.0, spans[0][1]
    for lo, hi in spans[1:]:
        widest = max(widest, lo - reach)
        reach = max(reach, hi)
    widest = max(widest, spans[0][0] + turn - reach)
    return widest <= math.pi + COVER_ANGLE


def _circle_meets(a, b):
    """Where circles ``a`` and ``b`` ``(x, y, rho)`` meet; circles within COVER_GAP of
    touching meet at their tangent point."""
    (ax, ay, ra), (bx, by, rb) = a, b
    gap = math.hypot(bx - ax, by - ay)
    if gap <= 1e-12 or gap > ra + rb + COVER_GAP or gap < abs(ra - rb) - COVER_GAP:
        return []
    ux, uy = (bx - ax) / gap, (by - ay) / gap
    along = (gap * gap + ra * ra - rb * rb) / (2 * gap)
    half = math.sqrt(max(ra * ra - along * along, 0.0))
    fx, fy = ax + along * ux, ay + along * uy
    return [(fx - half * uy, fy + half * ux), (fx + half * uy, fy - half * ux)]


def _ray_meets(ox, oy, angle, circle):
    """Where the ray from ``(ox, oy)`` at ``angle`` meets ``circle`` ``(x, y, rho)``."""
    wx, wy = math.cos(angle), math.sin(angle)
    dx, dy = ox - circle[0], oy - circle[1]
    b = dx * wx + dy * wy
    square = b * b - (dx * dx + dy * dy - circle[2] ** 2)
    if square < -COVER_GAP:
        return []
    root = math.sqrt(max(square, 0.0))
    return [(ox + t * wx, oy + t * wy) for t in (-b - root, -b + root) if t >= -COVER_GAP]


def _cover_candidates(points, arcs, radius):
    """Finitely many axes containing every vertex of the cover locus and its singleton.

    The locus boundary lies on the circles ``C(p, R)`` per contour point and ``C(o, R-r)``
    per arc with ``R > r``: a positive-area locus has a vertex where two of them meet or
    is the disc ``D(o, R-r)`` about an arc centre, and a single-point locus lies on two of
    them or at an arc centre. Cone rays meeting the circles are kept too.
    """
    circles = [(px, py, radius) for px, py in points]
    circles += [(ox, oy, radius - r) for ox, oy, r, _, _ in arcs if radius - r > 1e-12]
    found = [(ox, oy) for ox, oy, _, _, _ in arcs]
    for i, a in enumerate(circles):
        for b in circles[i + 1 :]:
            found.extend(_circle_meets(a, b))
    for ox, oy, _, a0, a1 in arcs:
        for angle in (a0 + math.pi, a1 + math.pi):
            for circle in circles:
                found.extend(_ray_meets(ox, oy, angle, circle))
    return found


def _extreme_points(face, edge):
    """The points of ``edge`` extreme along -x, +x, -y and +y (exact Extrema solutions)."""
    box = face.BoundBox
    far = 10.0 + box.DiagonalLength
    x0, x1, y0, y1 = box.XMin - far, box.XMax + far, box.YMin - far, box.YMax + far
    found = []
    for a, b in (
        ((x0, y0), (x0, y1)),
        ((x1, y0), (x1, y1)),
        ((x0, y0), (x1, y0)),
        ((x0, y1), (x1, y1)),
    ):
        line = Part.LineSegment(V(a[0], a[1], box.ZMin), V(b[0], b[1], box.ZMin)).toShape()
        _, pairs, _ = edge.distToShape(line)
        if not pairs:
            raise ValueError(f"no extreme point found on its {type(edge.Curve).__name__} edge")
        found.extend((p.x, p.y) for p, _ in pairs)
    return found


def _cover_disc(x, y, z, radius):
    return Part.Face(Part.Wire(Part.makeCircle(radius, V(x, y, z))))


def _cover_cone(ox, oy, z, a0, a1, length):
    """The closed sector at ``(ox, oy)`` over directions ``a0..a1``, ``length`` long."""
    if a1 - a0 >= 2 * math.pi - 1e-12:
        return _cover_disc(ox, oy, z, length)
    centre = V(ox, oy, z)
    ends = [
        V(ox + length * math.cos(a), oy + length * math.sin(a), z) for a in (a0, (a0 + a1) / 2, a1)
    ]
    return Part.Face(
        Part.Wire(
            [
                Part.LineSegment(centre, ends[0]).toShape(),
                Part.Arc(*ends).toShape(),
                Part.LineSegment(ends[2], centre).toShape(),
            ]
        )
    )


def _cover_region_problem(locus, faces, points, arcs, radius):
    """Why the native partition ``faces`` of ``locus`` is not the one convex cover locus,
    or None.

    The locus ``{c : g(c) <= radius}`` is convex and its boundary is where ``g`` reaches
    ``radius``: arcs of ``D(p, radius)`` about the outer wire's points and, for each arc
    ``(o, r)``, of ``D(o, radius - r)``. The partition must be valid faces that merge,
    without overlap, into one face bounded by one wire; that wire must turn one way only
    (arcs and corners alike, total one full turn), every edge must lie on one of those
    circles, and every vertex and edge midpoint must have ``g`` within PLANE_TOL of
    ``radius``. A split, an overlap, a lost corner or a foreign boundary fails.
    """
    area = sum(f.Area for f in faces)
    if not locus.isValid() or not all(f.isValid() for f in faces) or area <= 0:
        return "is not a valid native face set"
    union = faces[0] if len(faces) == 1 else faces[0].fuse(faces[1:]).removeSplitter()
    if len(union.Faces) != 1 or len(union.Faces[0].Wires) != 1:
        return "is not one simply connected piece"
    if abs(union.Area - area) > 1e-9 * max(1.0, area):
        return "has overlapping pieces"
    circles = [(x, y, radius) for x, y in points]
    circles += [(ox, oy, radius - r) for ox, oy, r, _, _ in arcs if radius - r > 1e-12]
    edges = union.Faces[0].OuterWire.OrderedEdges
    turns, ends = [], []
    for edge in edges:
        first, last = edge.FirstParameter, edge.LastParameter
        sign = -1.0 if edge.Orientation == "Reversed" else 1.0
        start, end = (first, last) if sign > 0 else (last, first)
        ends.append(
            (
                edge.valueAt(start),
                edge.tangentAt(start) * sign,
                edge.valueAt(end),
                edge.tangentAt(end) * sign,
            )
        )
        curve = edge.Curve
        if not isinstance(curve, Part.Circle) or not any(
            math.hypot(curve.Center.x - x, curve.Center.y - y) <= PLANE_TOL
            and abs(curve.Radius - rho) <= PLANE_TOL
            for x, y, rho in circles
        ):
            return "has a boundary edge on no cover circle"
        turns.append(math.copysign(last - first, curve.Axis.z * sign))
        mid = edge.valueAt((first + last) / 2)
        for p in (mid, edge.valueAt(first)):
            if abs(_cover_farthest(points, arcs, p.x, p.y) - radius) > PLANE_TOL:
                return "has boundary off the cover circle"
    for (_, _, p, t), (q, u, _, _) in zip(ends, ends[1:] + ends[:1], strict=True):
        if (p - q).Length > PLANE_TOL:
            return "has an open boundary"
        turns.append(math.atan2(t.x * u.y - t.y * u.x, t.x * u.x + t.y * u.y))
    total = sum(turns)
    if abs(abs(total) - 2 * math.pi) > 1e-6 or any(t * total < -1e-6 for t in turns):
        return "is not convex"
    return None


def _cover_locus(face, radius):
    """The axes ``c`` whose cutter disc ``D(c, radius)`` holds the whole planar face.

    The locus is the intersection of ``D(p, radius)`` over the face's points: convex and
    fixed by its outer wire. A line contributes its end discs; a Z-axis arc (centre
    ``o``, radius ``r``) its end discs and, across the cone opposite its span, ``|c - o|
    <= radius - r``. Returns ``("empty", None)`` when no candidate axis
    (:func:`_cover_candidates`) covers the face; ``("point", (x, y))`` for a certified
    singleton (:func:`_cover_certified`); else ``("region", (x, y))``, the area centroid
    of every face of the native locus, accepted only when :func:`_cover_region_problem`
    certifies those faces as the one convex locus, the centroid covers the face and every
    covering candidate lies on that locus. Any other
    contour has no exact locus here: unless discs about its exact points (vertices,
    extremes) share no point, it raises ValueError, as does a failed native locus.
    """
    points, arcs, unsupported = _cover_contour(face)
    if not points:
        raise ValueError("its outer wire has no vertex")
    span = 2 * radius + COVER_TOL
    if any(
        math.hypot(ax - bx, ay - by) > span
        for i, (ax, ay) in enumerate(points)
        for bx, by in points[i + 1 :]
    ):
        return "empty", None
    if unsupported:
        exact = points + [p for _, edge in unsupported for p in _extreme_points(face, edge)]
        if all(
            _cover_farthest(exact, [], x, y) > radius + COVER_TOL
            for x, y in _cover_candidates(exact, [], radius)
        ):
            return "empty", None
        names = ", ".join(sorted({name for name, _ in unsupported}))
        raise ValueError(f"its outer contour ({names}) has no exact whole-face cover locus")
    feasible = [
        (x, y)
        for x, y in _cover_candidates(points, arcs, radius)
        if _cover_farthest(points, arcs, x, y) <= radius + COVER_TOL
    ]
    if not feasible:
        return "empty", None
    for x, y in feasible:
        if _cover_farthest(points, arcs, x, y) >= radius - COVER_TOL and _cover_certified(
            points, arcs, x, y, radius
        ):
            if any(math.hypot(x - u, y - v) > COVER_GAP for u, v in feasible):
                raise ValueError("its certified covering axis is not the only covering one")
            return "point", (x, y)
    z = face.BoundBox.ZMin
    sx, sy = points[0]
    locus = _cover_disc(sx, sy, z, radius)
    for x, y in points[1:]:
        locus = locus.common(_cover_disc(x, y, z, radius))
    for ox, oy, r, a0, a1 in arcs:
        # D(seed, R) already holds every surviving axis, so this length encloses them.
        length = math.hypot(ox - sx, oy - sy) + radius + 1.0
        cone = _cover_cone(ox, oy, z, a0 + math.pi, a1 + math.pi, length)
        if radius - r > 1e-12:
            cone = cone.cut(_cover_disc(ox, oy, z, radius - r))
        locus = locus.cut(cone)
    faces = sorted(
        locus.Faces,
        key=lambda f: (round(f.CenterOfMass.x, 9), round(f.CenterOfMass.y, 9), f.Area),
    )
    if not faces:
        raise ValueError("its whole-face cover locus has area but the native boolean lost it")
    problem = _cover_region_problem(locus, faces, points, arcs, radius)
    if problem is not None:
        raise ValueError(f"its native whole-face cover locus {problem}")
    area = sum(f.Area for f in faces)
    cx = sum(f.Area * f.CenterOfMass.x for f in faces) / area
    cy = sum(f.Area * f.CenterOfMass.y for f in faces) / area
    if _cover_farthest(points, arcs, cx, cy) > radius + COVER_TOL or any(
        locus.distToShape(Part.Vertex(V(x, y, z)))[0] > PLANE_TOL for x, y in feasible
    ):
        raise ValueError("its native whole-face cover locus disagrees with the exact check")
    return "region", (cx, cy)


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
        self.answers = {}
        self.hit_refs = {}  # exact (cylinder, own face) -> read-only label set
        self.kept = 0

    def common(self, cx, cy, radius, z0, z1, solid=None):
        """The solid's material inside the cylinder, or None when there is none.

        A cutter ``solid`` lying inside that cylinder (a spot's point cone and body)
        replaces it in the boolean; the cylinder still bounds the face culling.
        Actual solids bypass the cylinder-answer cache.
        """
        if self.shape.isNull():
            return None
        key = (cx, cy, radius, z0, z1)
        cacheable = solid is None
        if cacheable and key in self.answers:
            return self.answers[key]
        if not any(_cylinder_hits_box(cx, cy, radius, z0, z1, box, True) for box in self.boxes):
            # No face reaches the cylinder, so it lies wholly inside or wholly outside.
            if not self.shape.isInside(V(cx, cy, (z0 + z1) / 2), 1e-9, False):
                answer = None
            else:
                answer = (
                    solid
                    if solid is not None
                    else Part.makeCylinder(radius, z1 - z0, V(cx, cy, z0))
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


def _clearing_span(bounds, within=None):
    """(setup-frame (x0, y0, z0, x1, y1, z1) of an op's ``stock_removal_bounds`` in mm, or
    None, and why not).

    Given the stock bbox ``within``, the span is clipped to it grown by 1 mm, so huge finite
    bounds never become huge boolean operands; its intersection with that stock and face
    contact within ``STOCK_TOL`` are unchanged.
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
    return (*lo, *hi), None


def _clearing_box(bounds, within=None):
    """(setup-frame solid of an op's :func:`_clearing_span`, or None, and why not)."""
    span, why = _clearing_span(bounds, within)
    return (None, why) if span is None else (_box_shape(span), None)


def _depth_window(span, to_z):
    """``span`` above an op's ``to_z``, or None when nothing of it is."""
    if to_z is None:
        return span
    z0 = max(span[2], float(to_z))
    return None if z0 >= span[5] else (span[0], span[1], z0, *span[3:])


def _sweep_window(sweep):
    """A box holding a whole +Z claim sweep."""
    box = _bbox(sweep)
    return (*(v - COVER_MM for v in box[:3]), *(v + COVER_MM for v in box[3:]))


def _offset(shape, distance, join=0, fill=False):
    """``shape`` offset by ``distance`` (``fill``: thickened into a solid), built on a deep
    copy: OCC's offset rewrites the edge tolerances and pcurves of the shape it runs on in
    place, so offsetting a face shared with the finished part would change that part's
    geometry, and every later Boolean on it, depending on call order."""
    return shape.copy().makeOffsetShape(distance, 1e-6, False, False, 0, join, fill)


def _tube(edge, radius):
    """Points within ``radius`` of an edge, swept normal to it (balls cap its ends).

    A line gets an exact cylinder; an arc a pipe whose volume must equal pi r^2 L
    (Pappus), so a pipe OCC builds short of material, or one folding over a bend tighter
    than ``radius``, fails instead of keeping less.
    """
    start, tangent = edge.valueAt(edge.FirstParameter), edge.tangentAt(edge.FirstParameter)
    if isinstance(edge.Curve, Part.Line):
        return Part.makeCylinder(radius, edge.Length, start, tangent)
    tube = Part.Wire([edge.copy()]).makePipeShell(
        [Part.Wire([Part.makeCircle(radius, start, tangent)])], True, True
    )
    expected = math.pi * radius * radius * edge.Length
    if (
        not tube.isValid()
        or len(tube.Solids) != 1
        or abs(tube.Volume - expected) > TUBE_REL * expected
    ):
        raise ValueError(f"its {_r(radius)} mm tube is not a valid full-volume solid")
    return tube


def _dihedral(edge, first, second):
    """``"tangent"``, ``"convex"`` or ``"concave"`` where two faces meet along ``edge``, or
    None unless that is provably the same all along it.

    It is when the edge is a line both surfaces are invariant along (planes, cylinders on
    a parallel axis, cones through their apex) or a circle both are invariant around
    (coaxial planes, cylinders, cones, tori, spheres): the dihedral then moves rigidly
    along the edge, and its midpoint decides it.
    """
    curve = edge.Curve
    if not (_invariant(first.Surface, curve) and _invariant(second.Surface, curve)):
        return None
    try:
        t = (edge.FirstParameter + edge.LastParameter) / 2
        point, tangent = edge.valueAt(t), edge.tangentAt(t)
        n1, n2 = _normal_at(first, point), _normal_at(second, point)
        if n1.cross(n2).Length < 1e-7 and n1.dot(n2) > 0:
            return "tangent"
        into = tangent.cross(n1)
        into.normalize()
        step = 10 * STOCK_TOL
        ahead = first.distToShape(Part.Vertex(point + into * step))[0]
        behind = first.distToShape(Part.Vertex(point - into * step))[0]
        if ahead > behind:
            into = -into
        return "convex" if into.dot(n2) < 0 else "concave"
    except Exception:
        return None


def _invariant(surface, curve):
    """Whether ``surface`` maps to itself when a point slides along the line ``curve`` or
    turns about the circle ``curve``'s axis."""

    def parallel(a, b):
        return a.cross(b).Length < 1e-9 * a.Length * b.Length

    def on_axis(point, origin, direction):
        offset = point - origin
        return offset.cross(direction).Length < STOCK_TOL * direction.Length

    if isinstance(curve, Part.Line):
        if isinstance(surface, Part.Plane):
            return True
        if isinstance(surface, Part.Cylinder):
            return parallel(surface.Axis, curve.Direction)
        if isinstance(surface, Part.Cone):
            return on_axis(surface.Apex, curve.Location, curve.Direction)
        return False
    if isinstance(curve, Part.Circle):
        if isinstance(surface, Part.Plane):
            return parallel(surface.Axis, curve.Axis)
        if isinstance(surface, Part.Sphere):
            return on_axis(surface.Center, curve.Center, curve.Axis)
        if isinstance(surface, (Part.Cylinder, Part.Toroid)):
            return parallel(surface.Axis, curve.Axis) and on_axis(
                curve.Center, surface.Center, surface.Axis
            )
        if isinstance(surface, Part.Cone):
            return parallel(surface.Axis, curve.Axis) and on_axis(
                curve.Center, surface.Apex, surface.Axis
            )
    return False


def _material(shape, what):
    """``shape`` when a Boolean left solid material, None when it left nothing at all.

    A result with faces but no solid is invalid topology, not an empty intersection.
    """
    if shape.Solids:
        return shape
    if shape.Faces or shape.Shells:
        raise ValueError(f"{what} is faces without a solid")
    return None


def _valid(shape, what):
    """:func:`_material` of ``shape``, which must also be valid topology."""
    shape = _material(shape, what)
    if shape is not None and not shape.isValid():
        raise ValueError(f"{what} is not valid")
    return shape


def _cleared(original, rest, group):
    """Whether a band ``group`` needs no cut from ``rest``, what is left of the stock piece
    ``original`` after the cuts before it: none of the group is in ``rest``, or those cuts
    took all but a mere hit of a group ``original`` held more of. A tiny group still whole,
    or one whose remainder is not valid topology, is not cleared."""

    def within(stock):
        try:
            commons = [_valid(stock.common(piece), "band group in stock") for piece in group]
        except ValueError:
            return None
        return sum(common.Volume for common in commons if common is not None)

    left = within(rest)
    if left is None or left > HIT_MM3:
        return False
    return left == 0.0 or (within(original) or 0.0) > HIT_MM3


def _breaking(original, applied):
    """Label of the first ``(label, removal)`` pair of ``applied`` that leaves ``original``
    invalid when they are cut from it in order. Only an explanation of stock already found
    invalid: a replay that fails says so instead of replacing that finding."""
    rest = original
    try:
        for label, removal in applied:
            rest = rest.cut(removal)
            if not rest.isValid():
                return label
    except Exception as exc:
        return f"replaying its cuts to find the first that breaks it failed ({exc})"
    return "only once all are cut"


def _touching(solids):
    """``solids`` grouped by contact: the connected pieces their fusion would give."""
    groups = []
    for solid in solids:
        box = solid.BoundBox
        box.enlarge(STOCK_TOL)
        joined = [
            group
            for group in groups
            if any(
                box.intersect(other.BoundBox) and _distance(solid, other)[0] <= HIT_MM3
                for other in group
            )
        ]
        merged = [solid]
        for group in joined:
            merged.extend(group)
        groups = [group for group in groups if not any(group is j for j in joined)]
        groups.append(merged)
    return groups


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


def _joint_parameters(spec, diameter=None, depth=None, at=None):
    """A finite authored target, never an unbounded through-hole or inferred nominal."""
    diameter = spec.get("nominal_dia_mm") if diameter is None else diameter
    depth = spec.get("depth_mm") if depth is None else depth
    if not all(_number(value) and value > 0 for value in (diameter, depth)):
        raise _Unknown("joint cylinder diameter/depth is unknown")
    at = spec.get("at_mm") if at is None else at
    if not isinstance(at, list) or len(at) != 3 or not all(_number(v) for v in at):
        raise _Unknown("joint cylinder starting centre is unknown")
    axis = spec.get("axis")
    if not isinstance(axis, list) or len(axis) != 3 or not all(_number(v) for v in axis):
        raise _Unknown("joint cylinder axis is unknown")
    direction = V(*axis)
    if abs(direction.Length - 1) > 1e-6:
        raise ValueError("joint cylinder axis is not a unit vector")
    return diameter, depth, V(*at), direction


def _joint_cylinder(spec, diameter=None, depth=None, at=None):
    diameter, depth, at, direction = _joint_parameters(spec, diameter, depth, at)
    return Part.makeCylinder(diameter / 2, depth, at, direction)


def _joint_engagement(socket, spigot):
    for spec in (socket, spigot):
        _joint_parameters(spec)
    axis, other = V(*socket["axis"]), V(*spigot["axis"])
    offset = V(*spigot["at_mm"]) - V(*socket["at_mm"])
    if abs(axis.dot(other)) < PARALLEL or offset.cross(axis).Length > AXIS_TOL:
        raise ValueError("socket and spigot cylinders are not coaxial")
    ends = [offset.dot(axis), (offset + other * spigot["depth_mm"]).dot(axis)]
    start, end = max(0.0, min(ends)), min(socket["depth_mm"], max(ends))
    if end - start <= PLANE_TOL:
        raise ValueError("socket and spigot have no finite axial engagement")
    bands = [socket.get("dia_mm"), spigot.get("dia_mm")]
    if not all(
        isinstance(band, list)
        and len(band) == 2
        and all(_number(v) and v > 0 for v in band)
        and band[0] <= band[1]
        for band in bands
    ):
        raise _Unknown("joint engagement diameter bands are unknown")
    return {
        "at_mm": list(V(*socket["at_mm"]) + axis * start),
        "axis": list(axis),
        "depth_mm": end - start,
        "diameter_mm": max(band[1] for band in bands),
    }


def _joint_cut_spec(cut, frame):
    """The operation's finite cylinder, including its authored depth or spindle window."""
    action = cut.get("action")
    if action in {"tap", "counterbore"}:
        geometry = "thread" if action == "tap" else "counterbore step"
        raise _Unknown(
            f"{action} on plan.joint_features.{cut.get('joint_feature')} is refused: "
            f"its {geometry} geometry is not modelled on transient joint features"
        )
    spec = dict(cut)
    _joint_parameters(spec, spec.get("diameter_mm"))
    if spec["kind"] == "cylinder_bore":
        matrix, reason = _frame_matrix(frame)
        if reason:
            raise _Unknown(reason)
        at, axis = V(*spec["at_mm"]), V(*spec["axis"])
        local = matrix.multVec(at)
        direction = matrix.multVec(at + axis) - local
        if abs(direction.z) < PARALLEL:
            raise ValueError("socket cylinder is not parallel to the axial tool feed")
        if direction.z > 0:
            if not spec.get("thru"):
                raise ValueError("blind socket starting centre is not its tool-entry cap")
            # A through cylinder has two equivalent geometric caps, but the tool feeds -Z.
            spec["at_mm"] = list(at + axis * spec["depth_mm"])
            spec["axis"] = list(-axis)
    if "op_depth_mm" in spec:
        depth = spec["op_depth_mm"]
        if not _number(depth) or depth <= 0:
            raise _Unknown("joint operation depth is unknown")
        spec["depth_mm"] = depth
    if "z_from" in spec or "z_to" in spec:
        if not all(_number(spec.get(key)) for key in ("z_from", "z_to")):
            raise _Unknown("joint operation z_from/z_to is unknown")
        matrix, reason = _frame_matrix(frame)
        if reason:
            raise _Unknown(reason)
        origin, axis = V(*spec["at_mm"]), V(*spec["axis"])
        local = matrix.multVec(origin)
        direction = matrix.multVec(origin + axis) - local
        if abs(direction.z) < PARALLEL:
            raise ValueError("joint spindle window is not parallel to its cylinder axis")
        ends = sorted((spec[key] - local.z) / direction.z for key in ("z_from", "z_to"))
        if ends[1] - ends[0] <= PLANE_TOL:
            raise ValueError("joint operation spindle window spans no length")
        spec["at_mm"] = list(origin + axis * ends[0])
        spec["depth_mm"] = ends[1] - ends[0]
    return spec


def _joint_profile(spec, frame, top=None):
    """The same pointed/flat axial tool profiles used by ordinary hole operations."""
    action = spec.get("action")
    if spec["kind"] == "cylinder_spigot":
        if action not in {"turn", "rough_turn", "finish_turn"}:
            raise _Unknown(f"{action!r} has no supported spigot cutting profile")
        return _joint_cylinder(spec, spec.get("diameter_mm"))
    if action not in {"drill", "ream", "bore", "rough_bore", "finish_bore", "spot"}:
        raise _Unknown(f"{action!r} has no supported socket cutting profile")
    if action == "spot" and "op_depth_mm" not in spec:
        raise _Unknown(f"{action} joint cut needs an authored finite op_depth_mm")
    _joint_parameters(spec, spec.get("diameter_mm"))
    if action not in {"drill", "spot"} and top is None:
        return _joint_cylinder(spec, spec["diameter_mm"])
    angle = spec.get("point_angle_deg")
    if action in {"drill", "spot"} and (not _number(angle) or not 0 < angle < 180):
        raise _Unknown(f"{action} joint cut lacks an accepted point angle")
    matrix, reason = _frame_matrix(frame)
    if reason:
        raise _Unknown(reason)
    entry = matrix.multVec(V(*spec["at_mm"]))
    axis = matrix.multVec(V(*spec["at_mm"]) + V(*spec["axis"])) - entry
    if axis.dot(Z) > -PARALLEL:
        raise ValueError("joint axial tool profile is not aligned with -setup Z")
    radius = spec["diameter_mm"] / 2
    depth = spec["depth_mm"]
    tip = entry.z - depth
    ceiling = entry.z if top is None else max(entry.z, top)
    if action in {"drill", "spot"}:
        slope = math.tan(math.radians(angle / 2))
        if action == "drill":
            tip -= radius / slope
        profile = _pointed_cutter(entry.x, entry.y, tip, radius, slope, ceiling - tip)
    else:
        profile = Part.makeCylinder(radius, ceiling - tip, V(entry.x, entry.y, tip), Z)
    profile.transformShape(matrix.inverse())
    return profile


def _joint_faces(spec, cylinder):
    faces = []
    axis, end = V(*spec["axis"]), V(*spec["at_mm"]) + V(*spec["axis"]) * spec["depth_mm"]
    for face in cylinder.Faces:
        if isinstance(face.Surface, (Part.Cylinder, Part.Cone)):
            target = face.copy()
            if spec["kind"] == "cylinder_bore":
                target.reverse()
            faces.append(target)
        elif spec["kind"] == "cylinder_bore" and not spec.get("thru"):
            point = _inner_point(face)
            if point is not None and abs((point - end).dot(axis)) < PLANE_TOL:
                target = face.copy()
                target.reverse()
                faces.append(target)
    return faces


def _interface(spec):
    """The finite contact rectangle, centred at the authored point in model millimetres."""
    if not all(
        isinstance(spec.get(key), list)
        and len(spec[key]) == 3
        and all(_number(v) for v in spec[key])
        for key in ("at_mm", "normal", "x")
    ):
        raise _Unknown("joint interface placement is unknown")
    at, normal, across = (
        _stock_vector(spec, key, unit)
        for key, unit in (("at_mm", False), ("normal", True), ("x", True))
    )
    if abs(normal.dot(across)) > 1e-6:
        raise ValueError("joint interface normal and x are not orthogonal")
    size = spec.get("size_mm")
    if not isinstance(size, list) or len(size) != 2 or not all(_number(v) and v > 0 for v in size):
        raise _Unknown("joint interface size is unknown")
    across, along = across * (size[0] / 2), normal.cross(across) * (size[1] / 2)
    points = [at - across - along, at + across - along, at + across + along, at - across + along]
    return Part.Face(Part.makePolygon(points + points[:1])), at, normal


def _axis_extent(shape, axis):
    box = _bbox(shape)
    values = [
        V(x, y, z).dot(axis)
        for x in (box[0], box[3])
        for y in (box[1], box[4])
        for z in (box[2], box[5])
    ]
    return min(values), max(values)


def _straight_sweep(shape, vector):
    """Exact linear occupied sweep: endpoint solids plus prisms of the boundary faces."""
    moved = shape.copy()
    moved.translate(vector)
    pieces = [shape, moved]
    for face in shape.Faces:
        if _vertical(face, vector / vector.Length):
            continue
        prism = face.extrude(vector)
        if abs(prism.Volume) > HIT_MM3:
            if prism.Volume < 0:
                prism.reverse()
            pieces.append(prism)
    return pieces[0].multiFuse(pieces[1:]).removeSplitter()


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


_COLOURS = {
    "part": (164, 177, 189),
    "removed": (226, 166, 66),
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
    "rest": (176, 96, 72),
}


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
        self.raw_supplies = supplies
        self.states = {
            ref: {"components": {ref.removeprefix("stock.")}, "completed": {}, "joined": set()}
            for ref in supplies
        }
        self._init_joints()
        result["transient_faces"] = [
            {"index": len(signatures) + index, "label": self.labels[len(signatures) + index]}
            for index in range(len(self.synthetic_faces))
        ]
        result["stock"] = (
            {"bbox_mm": [_r(v) for v in _bbox(stock)], "volume_mm3": _r(stock.Volume)}
            if reason is None
            else {"reason": reason}
        )
        outputs = dict(supplies)
        leaves = dict.fromkeys(outputs, 0.0)  # largest known rough leave each lineage carries
        for setup in setups:
            held, held_reason, state, assembly_error = self._held(setup, outputs)
            if held_reason is None:
                box = _bbox(held)
                self.sweep_mm = 2 * math.dist(box[:3], box[3:]) + 10
            stock_in = setup.get("stock_in") if isinstance(setup, dict) else None
            refs = stock_in if isinstance(stock_in, list) else [stock_in]
            leave = max([0.0] + [leaves.get(ref, 0.0) for ref in refs if isinstance(ref, str)])
            runner = _Setup(self, setup, held, held_reason, state, leave)
            clocks = self.timing["setups"] if self.timing is not None else None
            with _timed(clocks, str(setup.get("id"))) as setup_clocks:
                runner.timing = setup_clocks
                facts, ops = runner.run()
            if assembly_error is not None:
                facts["assembly_error"] = assembly_error
            sid = str(setup.get("id"))
            result["setups"][sid] = facts
            result["ops"].update(ops)
            outputs[sid] = runner.stock_out, runner.stock_out_reason
            self.states[sid] = {
                "components": state["components"],
                "completed": runner.completed if runner.stock_out_reason is None else {},
                "joined": state["joined"],
            }
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
        """Resolve one exact branch, or validate and join exactly two independent branches."""
        stock_in = setup.get("stock_in", UNKNOWN)
        refs = stock_in if isinstance(stock_in, list) else [stock_in]
        state = {"components": set(), "completed": {}, "joined": set()}
        error = None
        try:
            for ref in refs:
                if ref not in sources or ref not in self.states:
                    raise ValueError(
                        f"stock_in reference {ref!r} is not a supply or earlier output"
                    )
                upstream = self.states[ref]
                if state["components"] & upstream["components"]:
                    raise ValueError("stock_in branches share component ancestry")
                state["components"].update(upstream["components"])
                state["completed"].update(upstream["completed"])
                state["joined"].update(upstream["joined"])
                if sources[ref][1] is not None:
                    raise _Unknown(sources[ref][1])
            for component in state["components"] - state["joined"]:
                if component in self.ownership_errors:
                    raise ValueError(self.ownership_errors[component])
                if component in self.ownership_reasons:
                    raise _Unknown(self.ownership_reasons[component])
            if not isinstance(stock_in, list):
                return sources[refs[0]][0], None, state, None
            if len(refs) != 2:
                raise ValueError("a declared joint requires exactly two stock_in branches")
            joint = setup.get("joint")
            if not isinstance(joint, dict):
                raise ValueError("every stock_in array requires a declared joint")
            if joint.get("fit_error"):
                raise ValueError(joint["fit_error"])
            if joint.get("reason"):
                raise _Unknown(joint["reason"])
            if joint.get("kind") == "cylindrical":
                joined = self._cylindrical_join(refs, sources, joint, state)
            elif joint.get("kind") == "surface":
                joined = self._surface_join(refs, sources, joint)
            else:
                raise ValueError("joint kind is not cylindrical or surface")
            raw = [self.raw_supplies["stock." + name][0] for name in state["components"]]
            envelope = raw[0].multiFuse(raw[1:]) if len(raw) > 1 else raw[0]
            missing = self.solid.common(envelope).cut(joined).Volume
            if missing > STOCK_MM3:
                raise ValueError(
                    f"assembled outputs leave {_r(missing)} mm^3 "
                    "of protected finished material missing"
                )
            if not joined.isValid() or len(joined.Solids) != 1:
                raise ValueError("declared joint leaves disconnected or invalid material")
            state["joined"].update(state["components"])
            return joined, None, state, None
        except _Unknown as exc:
            return None, str(exc), state, None
        except (ValueError, KeyError) as exc:
            error = str(exc)
        return None, error, state, error

    def _init_joints(self):
        self.joint_features = self.job.get("joint_features", {})
        self.synthetic_faces, self.joint_indices, self.joint_op_indices = [], {}, {}
        self.joint_targets, self.ownership_reasons = {}, {}
        self.ownership_errors = {}
        self.protected = {
            name: self.solid for state in self.states.values() for name in state["components"]
        }
        roots = {ref: state["components"] for ref, state in self.states.items()}
        for setup in self.job["setups"]:
            refs = setup.get("stock_in")
            refs = refs if isinstance(refs, list) else [refs]
            roots[setup["id"]] = set().union(*(roots.get(ref, set()) for ref in refs))
        spigots = []
        for name, spec in sorted(self.joint_features.items()):
            try:
                target = _joint_cylinder(spec)
            except _Unknown:
                continue
            self.joint_targets[name] = target
            self.joint_indices[name] = self._add_joint_faces(spec, target)
        for setup in self.job["setups"]:
            joint = setup.get("joint")
            if not isinstance(joint, dict):
                continue
            if joint.get("kind") == "cylindrical":
                socket = self.joint_features.get(joint.get("socket"), {})
                spigot = self.joint_features.get(joint.get("spigot"), {})
                target = self.joint_targets.get(joint.get("spigot"))
                if target is None:
                    for spec in (socket, spigot):
                        if spec:
                            self.ownership_reasons[spec["component"]] = (
                                "joint ownership cylinder is unknown"
                            )
                    continue
                owned = self.solid.common(target)
                components = {socket["component"], spigot["component"]}
                for other, material, other_components in spigots:
                    if owned.common(material).Volume > STOCK_MM3:
                        error = (
                            "spigot ownership overlaps finished material: "
                            f"{other}, {joint['spigot']}"
                        )
                        for component in components | other_components:
                            self.ownership_errors[component] = error
                spigots.append((joint["spigot"], owned, components))
                self.protected[spigot["component"]] = self.protected[spigot["component"]].common(
                    owned
                )
                self.protected[socket["component"]] = self.protected[socket["component"]].cut(owned)
            elif joint.get("kind") == "surface":
                try:
                    interfaces = joint.get("interfaces")
                    if not isinstance(interfaces, list) or not interfaces:
                        raise _Unknown("surface joint interfaces are unknown")
                    refs = setup["stock_in"]
                    size = 4 * math.dist(_bbox(self.solid)[:3], _bbox(self.solid)[3:]) + 10
                    for spec in interfaces:
                        _, at, normal = _interface(spec)
                        for ref in refs:
                            names = roots.get(ref, set())
                            if ref == joint.get("negative_ref", refs[0]):
                                sign = -1
                            elif ref == joint.get("positive_ref", refs[1]):
                                sign = 1
                            else:
                                raise ValueError("surface joint side reference is not received")
                            wide, _, _ = _interface({**spec, "size_mm": [size, size]})
                            half = wide.extrude(normal * (sign * size))
                            for name in names:
                                self.protected[name] = self.protected[name].common(half)
                        if joint.get("negative_ref", refs[0]) == joint.get("positive_ref", refs[1]):
                            raise ValueError(
                                "surface joint requires opposite branch side ownership"
                            )
                except _Unknown as exc:
                    for ref in setup["stock_in"]:
                        for name in roots.get(ref, set()):
                            self.ownership_reasons[name] = str(exc)
                except ValueError as exc:
                    for ref in setup["stock_in"]:
                        for name in roots.get(ref, set()):
                            self.ownership_errors[name] = str(exc)
        for setup in self.job["setups"]:
            for op in setup.get("ops", []):
                cut = op.get("joint_cut")
                if isinstance(cut, dict) and not cut.get("reason"):
                    try:
                        spec = _joint_cut_spec(cut, setup.get("frame"))
                        cylinder = _joint_profile(spec, setup.get("frame"))
                    except (_Unknown, ValueError):
                        continue
                    self.joint_op_indices[op["subject"]] = self._add_joint_faces(spec, cylinder)
        self.features.update(
            {name: self.joint_indices.get(name, UNKNOWN) for name in self.joint_features}
        )

    def _add_joint_faces(self, spec, target):
        indices = []
        for face in _joint_faces(spec, target):
            indices.append(len(self.labels))
            self.labels.append(
                spec.get("label", "plan.joint_features." + spec.get("joint_feature", ""))
            )
            self.synthetic_faces.append(face)
        return indices

    def _prepared(self, solid, name, state):
        spec = self.joint_features[name]
        cut = state["completed"].get(name)
        if not cut or cut.get("component") != spec["component"]:
            raise ValueError(
                f"joint feature {name} has no completed preparation on its received ancestor"
            )
        target = _joint_cylinder(spec, cut["diameter_mm"])
        if spec["kind"] == "cylinder_bore":
            if solid.common(target).Volume > STOCK_MM3:
                raise ValueError(f"prepared socket {name} still contains material")
        else:
            if target.cut(solid).Volume > STOCK_MM3:
                raise ValueError(f"prepared spigot {name} is missing target material")
            outer = _joint_cylinder(spec, 4 * math.dist(_bbox(solid)[:3], _bbox(solid)[3:]) + 10)
            if solid.common(outer).cut(target).Volume > STOCK_MM3:
                raise ValueError(
                    f"prepared spigot {name} retains exterior stock in its finite span"
                )
        return cut

    def _cylindrical_join(self, refs, sources, joint, state):
        socket_name, spigot_name = joint["socket"], joint["spigot"]
        socket_spec, spigot_spec = (
            self.joint_features[socket_name],
            self.joint_features[spigot_name],
        )
        socket_ref, spigot_ref = joint["socket_ref"], joint["spigot_ref"]
        if socket_ref == spigot_ref or {socket_ref, spigot_ref} != set(refs):
            raise ValueError("socket and spigot must arrive on different received branches")
        for ref, spec in ((socket_ref, socket_spec), (spigot_ref, spigot_spec)):
            if self.states[ref]["components"] != {spec["component"]}:
                raise ValueError(
                    "joint feature does not belong to its exact received component ancestry"
                )
        socket, spigot = sources[socket_ref][0], sources[spigot_ref][0]
        socket_cut = self._prepared(socket, socket_name, self.states[socket_ref])
        spigot_cut = self._prepared(spigot, spigot_name, self.states[spigot_ref])
        a, b = socket_spec["dia_mm"], spigot_spec["dia_mm"]
        fit = joint.get("fit")
        if not all(
            isinstance(band, list) and len(band) == 2 and all(_number(v) for v in band)
            for band in (a, b, joint.get("band_mm"))
        ):
            raise _Unknown("joint fit diameter bands are unknown")
        guaranteed = (
            [a[0] - b[1], a[1] - b[0]] if fit == "clearance" else [b[0] - a[1], b[1] - a[0]]
        )
        band = joint["band_mm"]
        if (
            fit not in {"clearance", "interference"}
            or guaranteed[0] < -1e-9
            or guaranteed[0] < band[0] - 1e-9
            or guaranteed[1] > band[1] + 1e-9
        ):
            raise ValueError("socket/spigot fit fails at a worst-case diameter extreme")
        if (fit == "interference" and joint.get("method") != "press") or (
            fit == "clearance" and joint.get("method") not in {"silver_braze", "retaining_compound"}
        ):
            raise ValueError("joint method does not match its declared fit")
        engagement = _joint_engagement(socket_spec, spigot_spec)
        fill = _joint_cylinder(engagement, engagement.get("diameter_mm"))
        allowed_overlap = Part.Shape()
        if fit == "interference":
            outer = _joint_cylinder(engagement, spigot_cut["diameter_mm"])
            inner = _joint_cylinder(engagement, socket_cut["diameter_mm"])
            allowed_overlap = outer.cut(inner)
        overlap = socket.common(spigot)
        if fit == "interference":
            overlap = overlap.cut(allowed_overlap)
        if overlap.Volume > STOCK_MM3:
            raise ValueError(
                f"joint branches overlap {_r(overlap.Volume)} mm^3 outside the press-fit annulus"
            )
        axis = V(*socket_spec["axis"])
        distance = _axis_extent(spigot, axis)[1] - _axis_extent(socket, axis)[0] + 1.0
        swept = _straight_sweep(spigot, axis * -distance).common(socket)
        if fit == "interference":
            swept = swept.cut(allowed_overlap)
        if swept.Volume > STOCK_MM3:
            raise ValueError(
                "spigot insertion sweep meets socket material outside the interference annulus"
            )
        if fit == "interference":
            return socket.fuse(spigot).removeSplitter()
        if not joint.get("process"):
            raise ValueError("clearance joint fill requires an authored joining process")
        return socket.multiFuse([spigot, fill]).removeSplitter()

    def _surface_join(self, refs, sources, joint):
        negative, positive = joint.get("negative_ref", refs[0]), joint.get("positive_ref", refs[1])
        if negative == positive or {negative, positive} != set(refs):
            raise ValueError("surface joint side references must be the two received branches")
        first, second = sources[negative][0], sources[positive][0]
        if first.common(second).Volume > STOCK_MM3:
            raise ValueError("surface joint branches have undeclared overlapping bulk")
        interfaces = joint.get("interfaces")
        if not isinstance(interfaces, list) or not interfaces:
            raise _Unknown("surface joint interfaces are unknown")
        if joint.get("method") not in {"weld", "silver_braze"}:
            raise ValueError("surface joint method must be weld or silver_braze")
        for spec in interfaces:
            rectangle, at, normal = _interface(spec)
            tolerance = max(AREA_ABS, rectangle.Area * AREA_REL)
            for sign in (-1, 1):
                inside = rectangle.copy()
                inside.translate(normal * (sign * STOCK_TOL))
                if inside.cut(self.solid).Area > tolerance:
                    raise ValueError("surface joint interface is not internal to finished material")
            sides = []
            for shape, sign in ((first, 1), (second, -1)):
                faces = []
                for face in shape.Faces:
                    if not isinstance(face.Surface, Part.Plane):
                        continue
                    point = _inner_point(face)
                    if point is None or abs((point - at).dot(normal)) > PLANE_TOL:
                        continue
                    outward = _normal_at(face, point)
                    if outward.dot(normal) * sign >= PARALLEL:
                        faces.append((face, outward))
                sides.append(faces)
            patches = [
                a.common(b).common(rectangle)
                for a, na in sides[0]
                for b, nb in sides[1]
                if na.dot(nb) <= -PARALLEL
            ]
            if not patches:
                raise ValueError("surface joint interface has no opposing physical contact faces")
            covered = patches[0].multiFuse(patches[1:]) if len(patches) > 1 else patches[0]
            missing = rectangle.cut(covered).Area
            if missing > max(AREA_ABS, rectangle.Area * AREA_REL):
                raise ValueError(
                    f"surface joint interface lacks {_r(missing)} mm^2 of declared contact"
                )
        return first.fuse(second).removeSplitter()

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
        self,
        owner,
        setup,
        held=None,
        stock_reason="in-process stock was not derived",
        state=None,
        leave=0.0,
    ):
        self.owner = owner
        self.setup = setup if isinstance(setup, dict) else {}
        self.ops = [op for op in self.setup.get("ops", []) if isinstance(op, dict)]
        # Largest known rough leave the entry stock's lineage may carry, and the output's.
        self.leave_in = leave
        self.leave_out = max([leave] + [a for a, _ in map(_leave, self.ops) if a is not None])
        self.reasons = {}
        self.state = state or {"components": set(), "completed": {}, "joined": set()}
        self.completed = dict(self.state["completed"])
        self.protected = None
        self.certain = None
        self.joint_errors = {}
        # Model-frame stock this setup receives, or why it is unknown.
        self.held, self.stock_reason = (None, stock_reason) if held is None else (held, None)
        # Model-frame stock this setup leaves for the next one, or why it is unknown.
        self.stock_out, self.stock_out_reason = None, self.stock_reason
        # Setup-frame stock entering the setup and after each op that changes it.
        self.stock_states = []
        # Stock builder (:meth:`_build`): id(op) -> (setup-frame stock before it, the stock
        # accepted after it (its before stock when it stopped the builder), None) or (None,
        # None, why that stock is unknown); the facts of each saw it reached; and (end
        # stock, None) or (None, why it stopped).
        self.cuts = {}
        self.saws = {}
        self.built = None
        self.matrix = None
        self.finished = None  # the finished solid in the setup frame
        # Imported faces, then analytic transient surfaces; owner.labels indexes both.
        self.faces = []
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
        # (follow rest name, op subject) -> its carriage-relative jaw poses for that op
        self.rest_poses = {}
        self.chuck = None  # placed chuck geometry for the turning model, else None
        self.regions = {}
        self.culled_part = None
        self.directions = {}  # finished face index -> direction verdict cache
        self.revolutions = {}  # finished face index -> turning verdict cache
        # Turning op subject -> (profile after it, or None, and (failing op, why) or None).
        self.turn_obstacles = {}
        self.floor_adjacency = None
        self.cover_axes = {}  # (floor index, radius, leave) -> (whole-face axis or None, error)
        self.hole_cuts = {}  # (id(op), indices, radius) -> _hole_cut record
        self.hole_columns = None  # finished hole-face index -> entry-stock-long bore column
        # rough leave -> (protected solid offset outward by it, or None, why); and
        # (leave, window) -> (exact offset pieces of protected material within it, or None, why)
        self.guards = {}
        self.slabs = {}  # (face index, thickness) -> (face thickened outward, or None, why)
        self.skins = {}  # (claimed indices, leave) -> (their offset skin primitives, or None, why)
        self.sweeps = {}  # (claimed indices, facing?) -> (swept faces, +Z sweep or None)
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
                self.faces += [self._placed(face) for face in self.owner.synthetic_faces]
                owned = [
                    self.owner.protected[component]
                    for component in self.state["components"]
                    if self.owner.protected[component].Volume > HIT_MM3
                ]
                protection = (
                    owned[0].multiFuse(owned[1:])
                    if len(owned) > 1
                    else owned[0]
                    if owned
                    else Part.Shape()
                )
                self.protected = self._placed(protection)
                self.certain = self._placed(self._certain_material())
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
            # Only protected material belonging to these received components is certain.
            # Other components and the permitted socket void are not present on this branch.
            self._use(self.certain)
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
        # The stock builder derives every op's before-op stock, the saw facts and the end stock
        # once, before measuring: a flute meets the stock this setup's earlier cuts leave, while
        # holders, reach, fixtures and the render see the stock as it enters the setup.
        if self.stock_reason is None:
            with _timed(phases, "stock_states"):
                self.built = self._build()
        ops = {}
        for op in self.ops:
            with _timed(op_clocks, self._subject(op)):
                result = self._op(op)
                if self.stock_reason is not None and not _sawn(op):
                    self._unproven(result, self.stock_reason)
                ops[self._subject(op)] = result
        self._rest_interference(facts, ops)
        if self.stock_reason is None:
            with _timed(phases, "stock_output"):
                self.stock_out, self.stock_out_reason = self._finish(ops)
            with _timed(phases, "render"):
                png, scene = self._render()
            facts["render_png_base64"] = base64.b64encode(png).decode("ascii")
            facts["render_scene"] = scene
            facts["fixture_rendered"] = (
                self.fixture_ready and bool(scene["components"]) and not scene["debts"]
            )
            if any(_turned(op) for op in self.ops):
                self._stock_profile(facts)
            saws = [
                {"subject": self._subject(op), **ops[self._subject(op)]}
                for op in self.ops
                if _sawn(op)
            ]
            if saws:
                scene["saw_cuts"] = saws
            if self.stock_out_reason is None:
                facts["stock_out_volume_mm3"] = _r(self.stock_out.Volume)
                facts["stock_out_bbox_mm"] = [_r(v) for v in _bbox(self.stock_out)]
                facts["completed_joint_features"] = sorted(self.completed)
        if self.stock_out_reason is not None:
            facts["stock_out_reason"] = self.stock_out_reason
        for result in ops.values():
            completion = result.get("cap_completion")
            if completion is not None and completion["unformed"] == UNKNOWN:
                completion["reason"] = self.stock_out_reason
        for subject, error in self.joint_errors.items():
            ops[subject]["joint_error"] = error
        if self.fixture_reason is not None:
            facts["fixture_reason"] = self.fixture_reason
        unknown = [facts["reasons"][key] for key in sorted(facts["reasons"])]
        if self.fixture_reason is not None:
            facts["reason"] = self.fixture_reason
        elif unknown:
            facts["reason"] = unknown[0]
        return facts, ops

    def _stock_profile(self, facts):
        """stock_profile: [z_lo, z_hi, r_lo, r_hi] setup-frame bands of the least outer
        radius the setup's stock presents while material is there (``_least_rows``).

        Each in-process state (entering, then after every op that removes material) is
        sectioned; a band the setup later cuts away still counts at its thinnest before
        removal, so a raw collar, a stub turned then faced off and an end sawn off are all
        covered. An op is atomic: a parting groove part-way through its own cut is not a
        state. Every state must be a solid of revolution about setup Z: sections at
        STOCK_AZIMUTHS meridians must cover the same length and agree on the outer radius
        at each band's ends and middle; otherwise ``stock_profile_reason`` says why not.
        """
        if self.stock_out is None:
            facts["stock_profile_reason"] = self.stock_out_reason
            return
        states = []
        for index, stock in enumerate(self.stock_states):
            rows, why = _revolved_rows(stock)
            if why is not None:
                state = "entering" if index == 0 else f"after removal {index}"
                facts["stock_profile_reason"] = f"the stock {state} {why}"
                return
            states.append(rows)
        facts["stock_profile"] = [[_r(value) for value in row] for row in _least_rows(states)]

    # ------------------------------------------------------------------ in-process stock

    def _placed(self, shape):
        """A setup-frame copy of a model-frame shape."""
        placed = shape.copy()
        if not placed.isNull():
            placed.transformShape(self.matrix)
        return placed

    def _use(self, solid):
        """Make ``solid`` the material present for the following facts."""
        self.part = solid
        self.culled_part = None
        self.regions = {}

    def _certain_material(self):
        pieces = []
        for component in self.state["components"]:
            ref = "stock" if component == "stock" else "stock." + component
            raw = self.owner.raw_supplies.get(ref, (None, None))[0]
            if raw is None:
                continue
            piece = self.owner.protected[component].common(raw)
            if component not in self.state["joined"]:
                for setup in self.owner.job["setups"]:
                    joint = setup.get("joint")
                    if not isinstance(joint, dict) or joint.get("kind") != "cylindrical":
                        continue
                    socket = self.owner.joint_features[joint["socket"]]
                    if socket["component"] != component:
                        continue
                    try:
                        engagement = _joint_engagement(
                            socket, self.owner.joint_features[joint["spigot"]]
                        )
                    except (_Unknown, ValueError):
                        continue
                    piece = piece.cut(_joint_cylinder(engagement, engagement["diameter_mm"]))
            if piece.Volume > HIT_MM3:
                pieces.append(piece)
        return (
            pieces[0].multiFuse(pieces[1:])
            if len(pieces) > 1
            else pieces[0]
            if pieces
            else Part.Shape()
        )

    def _joint_check(self, op):
        cut = op.get("joint_cut")
        if not isinstance(cut, dict):
            raise ValueError("joint operation has no analytic cut declaration")
        name = cut.get("joint_feature")
        declared = self.owner.joint_features.get(name)
        if not declared or op.get("feature") != name or cut.get("kind") != declared["kind"]:
            raise ValueError("joint operation feature identity or cylinder kind is inconsistent")
        if "faces" in op:
            raise ValueError("joint operations cannot claim finished STEP faces")
        if (
            self.state["components"] != {declared["component"]}
            or declared["component"] in self.state["joined"]
        ):
            raise ValueError(
                "joint operation does not consume its exact unjoined component ancestor"
            )
        if cut.get("component") != declared["component"]:
            raise ValueError("joint operation component does not match its declaration")
        if cut.get("reason"):
            raise _Unknown(cut["reason"])
        spec = _joint_cut_spec(cut, self.setup.get("frame"))
        cylinder = _joint_profile(spec, self.setup.get("frame"))
        at = self.matrix.multVec(V(*spec["at_mm"]))
        axis = self.matrix.multVec(V(*spec["at_mm"]) + V(*spec["axis"])) - at
        if declared["kind"] == "cylinder_bore":
            if _turned(op) or axis.dot(Z) > -PARALLEL:
                raise ValueError("socket cut requires an axial approach opposite its depth axis")
        elif not _turned(op) or abs(axis.dot(Z)) < PARALLEL or math.hypot(at.x, at.y) > AXIS_TOL:
            raise ValueError("spigot cut requires turning coaxially about setup Z")
        diameter, band = spec.get("diameter_mm"), declared.get("dia_mm")
        if not isinstance(band, list) or len(band) != 2 or not all(_number(v) for v in band):
            raise _Unknown("joint operation diameter band is unknown")
        if (
            spec.get("finishing")
            and spec.get("completes")
            and not band[0] - 1e-9 <= diameter <= band[1] + 1e-9
        ):
            raise ValueError("finishing joint cylinder diameter is outside its declared band")
        return name, spec, cylinder

    def _joint_removal(self, op, stock):
        try:
            name, spec, cylinder = self._joint_check(op)
            target = self._placed(cylinder)
            if spec["kind"] == "cylinder_bore":
                path = _joint_profile(spec, self.setup.get("frame"), _bbox(stock)[5] + STOCK_TOL)
                removal = stock.common(self._placed(path))
            else:
                outer = _joint_cylinder(
                    spec, 4 * math.dist(_bbox(stock)[:3], _bbox(stock)[3:]) + 10
                )
                removal = stock.common(self._placed(outer))
                if removal.isNull() or removal.Volume <= HIT_MM3:
                    return None, None
                removal = removal.cut(target)
            if removal.isNull() or removal.Volume <= HIT_MM3:
                return None, None
            intrusion = (
                removal.common(self.protected) if self.protected.Volume > HIT_MM3 else Part.Shape()
            )
            if spec["kind"] == "cylinder_bore" and intrusion.Volume > HIT_MM3:
                for setup in self.owner.job["setups"]:
                    joint = setup.get("joint")
                    if (
                        isinstance(joint, dict)
                        and joint.get("kind") == "cylindrical"
                        and joint.get("socket") == name
                    ):
                        engagement = _joint_engagement(
                            self.owner.joint_features[name],
                            self.owner.joint_features[joint["spigot"]],
                        )
                        allowance = _joint_cylinder(engagement, engagement["diameter_mm"])
                        intrusion = intrusion.cut(self._placed(allowance))
            if intrusion.Volume > STOCK_MM3:
                raise ValueError(
                    f"joint cut removes {_r(intrusion.Volume)} mm^3 "
                    "of protected finished material outside joint engagement"
                )
            return removal, None
        except _Unknown as exc:
            return None, str(exc)
        except ValueError as exc:
            self.joint_errors[self._subject(op)] = str(exc)
            return None, str(exc)

    def _joint_corners(self, op):
        """Primitive topology checked against the actual post-cut branch, not final STEP."""
        name, spec, cylinder = self._joint_check(op)
        if spec["kind"] == "cylinder_spigot":
            after, reason = self._turn_obstacle(op)
        else:
            removal, reason = self._joint_removal(op, self.part)
            after = self.part if removal is None else self.part.cut(removal)
        if reason:
            return reason
        if spec["kind"] == "cylinder_bore":
            if spec.get("action") in {"drill", "spot", "ream"}:
                return []  # The accepted axial tool profile itself generates its bore/floor.
            axis = V(*spec["axis"])
            end = V(*spec["at_mm"]) + axis * spec["depth_mm"]
            for face in cylinder.Faces:
                point = _inner_point(face)
                if (
                    isinstance(face.Surface, Part.Plane)
                    and point is not None
                    and abs((point - end).dot(axis)) < PLANE_TOL
                ):
                    if self._placed(face).common(after).Area > CONTACT_MM2:
                        return (
                            f"plan.joint_features.{name}: blind-floor corner needs "
                            "the cutter's floor-edge geometry, not its radial diameter"
                        )
            if spec.get("thru"):
                return []
            return (
                f"plan.joint_features.{name}: blind-cylinder floor topology "
                "is not established on received stock"
            )
        declared = self.owner.joint_features[name]
        axis, at = V(*declared["axis"]), V(*declared["at_mm"])
        radius = spec["diameter_mm"] / 2
        for centre in (at - axis * STOCK_TOL, at + axis * declared["depth_mm"]):
            probe = {**spec, "at_mm": list(centre), "depth_mm": STOCK_TOL}
            outer = _joint_cylinder(probe, 2 * (radius + REACH_BAND))
            inner = _joint_cylinder(probe, 2 * radius)
            if self._placed(outer.cut(inner)).common(after).Volume > HIT_MM3:
                return (
                    f"plan.joint_features.{name}: retained stock forms a shoulder "
                    "at the finite target end; no shoulder radius or seat is authored"
                )
        return []  # Standalone external cylinder: lateral surface and convex end caps.

    def _complete_joint(self, op, stock):
        name, spec, _ = self._joint_check(op)
        if not spec.get("finishing") or not spec.get("completes"):
            return
        declared = self.owner.joint_features[name]
        actual = _joint_cylinder(spec, spec["diameter_mm"])
        full = _joint_cylinder(declared, spec["diameter_mm"])
        if full.cut(actual).Volume > STOCK_MM3:
            self.completed.pop(name, None)
            return
        record = {
            "component": declared["component"],
            "diameter_mm": spec["diameter_mm"],
            "subject": self._subject(op),
        }
        model = stock.copy()
        model.transformShape(self.matrix.inverse())
        self.owner._prepared(model, name, {"completed": {name: record}})
        self.completed[name] = record

    def _where(self):
        return f"the in-process stock setup {self.setup.get('id')} leaves cannot be derived"

    def _build(self):
        """(setup-frame stock after this setup's cuts, or None, and why it cannot be derived).

        One pass in op order, before any op is measured: ``cuts`` records the stock before
        each op and the stock it accepted after removing the cut derived for it
        (:meth:`_cut`), ``saws`` each reached saw's facts (:meth:`_saw_stock`) and
        ``stock_states`` the stock after every op that changes it. Each input stock solid
        loses the same cut separately (:meth:`_remove`); separate solids are never fused.
        The first op whose cut cannot be derived (or splits, empties, leaves invalid or
        band-holding stock, or fails a boolean) stops the pass: its own before-op stock stays
        known and is also its after stock, so its failed clearance is never credited; every
        later op's is unknown for that reason, and no later cut is ever credited to an
        earlier op.
        """
        where = self._where()
        stock, stopped = self.part, None
        self.stock_states = [stock]
        for op in self.ops:
            subject = self._subject(op)
            if stopped is not None:
                self.cuts[id(op)] = (None, None, stopped)
                continue
            before = stock
            try:
                if _sawn(op):
                    after, detail = self._saw_stock(op, stock)
                    self.saws[id(op)] = detail
                    why = detail.get("saw_error") or detail.get("saw_reason")
                    if why is not None:
                        stopped = f"{subject}: {why}; {where}"
                    else:
                        stock = after
                        self.stock_states.append(stock)
                    continue
                plan, why = self._cut(op, stock)
                if why is not None:
                    stopped = f"{subject} {why}; {where}"
                    continue
                own, groups = plan
                after = stock
                if own is not None or groups:
                    pieces = []
                    for original in stock.Solids:
                        kept, why = self._remove(original, own, groups)
                        if why is not None:
                            stopped = f"{subject}: {why}; {where}"
                            break
                        pieces.extend(kept)
                    if stopped is None and not pieces:
                        stopped = f"{subject}: claimed clearance leaves no stock; {where}"
                    if stopped is None:
                        after = pieces[0] if len(pieces) == 1 else Part.makeCompound(pieces)
                if stopped is None and isinstance(op.get("joint_cut"), dict):
                    # A finishing joint cut completes its feature on the stock it leaves.
                    try:
                        self._complete_joint(op, after)
                    except ValueError as exc:
                        self.joint_errors[subject] = str(exc)
                        stopped = f"{subject}: {exc}; {where}"
                if stopped is None and after is not stock:
                    stock = after
                    self.stock_states.append(stock)
            except Exception as exc:
                stopped = f"in-process stock boolean failed ({exc}); {where}"
            finally:
                self.cuts[id(op)] = (before, stock, None)
        return (None, stopped) if stopped is not None else (stock, None)

    @staticmethod
    def _remove(original, own, groups):
        """(the stock solid ``original`` less one op's cut, as its kept pieces, or None, and
        why that is not one valid piece free of the cut's band).

        Its own clearance goes first, then each connected band group, piece by piece and
        never fused. A group the cuts before it already cleared (:func:`_cleared`) is not
        cut again. Only the end is judged, so a fragment one piece splits off may still go
        with a later piece: at most one piece above ``STOCK_MM3`` may remain, valid and
        holding no more than ``STOCK_MM3`` of the band.
        """
        rest, applied = original, []
        if own is not None:
            rest = rest.cut(own)
            applied.append(("its own clearance", own))
        for number, group in enumerate(groups, 1):
            if not rest.Solids:
                break
            if _cleared(original, rest, group):
                # Cutting what is gone only adds OCC coincident-face artefacts.
                continue
            for piece in group:
                if rest.Solids:
                    rest = rest.cut(piece)
                    applied.append((f"lineage band group {number}", piece))
        kept = [piece for piece in rest.Solids if piece.Volume > STOCK_MM3]
        if len(kept) > 1:
            return None, (
                f"removing its claimed clearance splits an input stock piece into "
                f"{len(kept)} pieces"
            )
        if not all(piece.isValid() for piece in kept):
            return None, (
                "removing its claimed clearance leaves an invalid stock piece "
                f"({_breaking(original, applied)})"
            )
        left = sum(piece.common(cut).Volume for piece in kept for group in groups for cut in group)
        if left > STOCK_MM3:
            return None, f"{_r(left)} mm^3 of its lineage leave band survived its removal"
        return kept, None

    def _cut(self, op, stock):
        """(the cut ``op`` makes in ``stock``, or None, and why it cannot be derived).

        A cut is ``(own clearance or None, connected band groups)``, each group a list of
        solids; ``(None, [])`` removes nothing. A joint op (``joint_cut``) removes its
        analytic transient cylinder (:meth:`_joint_removal`), a turning op its revolved stock
        (:meth:`_turn_removal`) and a hole op (``hole`` metadata) its geometry-located bore
        cylinder (see :meth:`_hole_cut`). Other ops remove only stock outside their guard:
        the component-owned finished solid offset by their own rough leave
        (:meth:`_protect`). An authored clearing box removes that within the box above
        ``to_z``, leaving unclaimed hole columns to their own ops; its pieces must border a
        claim on the stock entering the setup, so an earlier op clearing the bridge between a
        claim and the rest of its box never strands that box. Other ops sweep direction-valid
        claims along +Z, keeping unclaimed rails, ears, webs and overstock. A lower-leave op
        also cuts the lineage leave off its claimed lateral faces of ``stock`` (:meth:`_band`).
        """
        valid, away, why = self._claims(op)
        if not isinstance(valid, list):
            return None, f"claimed faces are unresolved ({why})"
        to_z = op.get("to_z")
        if to_z is not None and not _number(to_z):
            return None, "to_z is unknown"
        if isinstance(op.get("joint_cut"), dict):
            removal, why = self._joint_removal(op, stock)
            return (None, why) if why is not None else ((removal, []), None)
        if _turned(op):
            removal, why = self._turn_removal(op, valid, stock)
            return (None, why) if why is not None else ((removal, []), None)
        if isinstance(op.get("hole"), dict):
            cut = self._hole_cut(op, valid, _positive(op, "radius_mm"))
            if cut["reason"] is not None:
                return None, cut["reason"]
            return (cut["removal"], []), None
        leave, why = self._guarded(op)
        if why is not None:
            return None, why
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
        else:
            removal, why = self._removal(valid, to_z, op.get("do"), leave)
        if why is not None:
            return None, why
        band, why = self._band(
            stock, valid, to_z, leave, carried, self._reach_window(op, leave, carried)
        )
        if why is not None:
            return None, why
        return (removal, band or []), None

    def _finish(self, ops):
        """(model-frame stock this setup leaves, or None, and why it cannot be derived).

        Judged once on the builder's end stock, after every op is measured; neither debt
        changes any op's before-op stock. Every face an unbounded milling op claims with a
        horizontal normal component must be clear of overstock beyond its op's guard at its
        interior (:meth:`_protect` within the claims' reach, the guard's derivable window);
        merely sweeping a sliver from a drafted wall does not prove it cleared.
        Each complete-form hole op's own claimed caps (``cap_completion`` in its ``ops``
        facts) must likewise be clear of it, even when its cut removes nothing new; touched
        caps are named there and make the output stock debt.
        """
        stock, why = self.built
        if why is not None:
            return None, why
        where = self._where()
        try:
            for op in self.ops:
                if (
                    isinstance(op.get("joint_cut"), dict)
                    or _sawn(op)
                    or _turned(op)
                    or isinstance(op.get("hole"), dict)
                    or "stock_removal_bounds" in op
                ):
                    continue
                claimed = self._indices(op)
                if not claimed:
                    continue
                subject, to_z = self._subject(op), op.get("to_z")
                leave, carried = self._guarded(op)[0], self._carried(op)
                # Raw stock beyond the larger of its own and the lineage leave is uncleared.
                reach = max(leave, carried) + COVER_MM
                overstock, why = self._protect(stock, leave, self._claim_window(claimed, reach))
                if why is not None:
                    return None, f"{subject} {why}; {where}"
                covered = self._covered(overstock, claimed, to_z, reach)
                if covered:
                    return None, (
                        f"{subject}: overstock still touches claimed wall(s) "
                        f"{', '.join(covered)} above its to_z; the setup approach does not "
                        "fully clear this profile wall and the op declares no "
                        "stock_removal_bounds (cleared XY footprint, retained rail/ear volume "
                        f"of an interrupted profile) for it; {where}"
                    )
            forms = [
                (self._subject(op), ops[self._subject(op)]["cap_completion"])
                for op in self.ops
                if isinstance(op.get("hole"), dict) and "cap_completion" in ops[self._subject(op)]
            ]
            # The exact wall contact test without a to_z clip or leave: a complete-form
            # cut is never rough, and stock left below its floor still leaves a cap unformed.
            residue = stock.cut(self.finished) if forms else None
            labels, unformed = self.owner.labels, []
            for subject, completion in forms:
                touched = self._covered(residue, completion["caps"], None)
                completion["unformed"] = [i for i in completion["caps"] if labels[i] in touched]
                if touched:
                    unformed.append(f"{subject} {', '.join(touched)}")
            if unformed:
                return None, (
                    "stock still touches claimed hole cap(s) after the setup's cuts, so their "
                    f"final cut does not form them: {'; '.join(unformed)}; {where}"
                )
            model = stock.copy()
            model.transformShape(self.matrix.inverse())
            for name in list(self.completed):
                try:
                    self.owner._prepared(model, name, {"completed": self.completed})
                except (ValueError, _Unknown):
                    del self.completed[name]
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
            bounds = [value - 1.0 for value in box[:3]] + [value + 1.0 for value in box[3:]]
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
                target_loss = (
                    self.protected.common(removed).Volume
                    if self.protected.Volume > HIT_MM3
                    else 0.0
                )
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
        span, why = _clearing_span(bounds, _bbox(stock))
        if span is None:
            return None, why
        box = _box_shape(span)
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
        window = _depth_window(span, to_z)
        if window is None:
            return None, None
        removed, why = self._protect(stock.common(box), leave, window)
        if why is not None:
            return None, why
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
        """(stock outside the op's guard swept by direction-valid claims along +Z, or None,
        and why not).

        A facing ``action`` sweeps each planar claim's outer loop, so raw pins over hole
        mouths go too; subtracting the guard still keeps islands, bosses and the leave. The
        whole sweep is guarded and its pieces judged by claim contact before ``to_z``
        clips them.
        """
        faces, sweep = self._sweep(valid, action)
        if sweep is None:
            return None, None
        cut, why = self._protect(sweep, leave, _sweep_window(sweep))
        if why is not None:
            return None, why
        kept = [
            piece
            for piece in cut.Solids
            if piece.Volume > HIT_MM3
            and any(_distance(piece, f)[0] < leave + STOCK_TOL for f in faces)
        ]
        if not kept:
            return None, None
        removal = kept[0].fuse(kept[1:]) if len(kept) > 1 else kept[0]
        if to_z is not None:
            removal = removal.common(self._above(to_z))
            if removal.Volume <= HIT_MM3:
                return None, None
        return removal, None

    def _sweep(self, valid, action):
        """(swept claimed faces, their +Z sweep or None), cached per claims and action."""
        facing = action in FACING_ACTIONS
        key = (tuple(valid), facing)
        if key not in self.sweeps:
            up = V(0, 0, 1)
            faces, prisms = [], []
            for index in valid:
                face = self.faces[index]
                surface = face.Surface
                if (
                    isinstance(surface, Part.Cylinder)
                    and abs(surface.Axis.dot(up)) >= PARALLEL
                    and _cylinder_concave(face)
                ):
                    z0 = _bbox(face)[2]
                    faces.append(face)
                    prisms.append(
                        Part.makeCylinder(
                            surface.Radius,
                            self.owner.sweep_mm,
                            V(surface.Center.x, surface.Center.y, z0),
                            up,
                        )
                    )
                    continue
                if _vertical(face, up):
                    continue
                if facing and isinstance(face.Surface, Part.Plane) and len(face.Wires) > 1:
                    face = Part.Face(face.OuterWire)
                prism = face.extrude(up * self.owner.sweep_mm)
                if prism.Volume > HIT_MM3:
                    faces.append(face)
                    prisms.append(prism)
            sweep = None
            if prisms:
                sweep = prisms[0].fuse(prisms[1:]) if len(prisms) > 1 else prisms[0]
            self.sweeps[key] = (faces, sweep)
        return self.sweeps[key]

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
        """(op's known rough leave whose guard is derivable, or None, and why not).

        Derivable means the whole finished part offsets, or, where OCC cannot build that
        (tangent zero-height lands), the exact offset within every window this op's
        consumers protect (:meth:`_windows`) does.
        """
        leave, why = _leave(op)
        if why is None:
            why = self._guard(leave)[1]
        if why is not None and leave is not None:
            windows, debt = self._windows(op, leave)
            for window in windows if debt is None else ():
                debt = self._guard(leave, window)[1]
                if debt is not None:
                    break
            why = None if debt is None else f"{why}; {debt}"
        return (leave, None) if why is None else (None, why)

    def _windows(self, op, leave):
        """(setup-frame boxes in which this op's consumers subtract its own guard, or why
        not): its claimed faces grown by the reach of the wall check, band and pose
        contacts; its clearing box above ``to_z``, or its whole unclipped claim sweep."""
        indices = self._indices(op)
        valid, _, why = self._claims(op)
        if indices == UNKNOWN or not isinstance(valid, list):
            return [], f"claimed faces are unresolved ({why})"
        to_z = op.get("to_z")
        if to_z is not None and not _number(to_z):
            return [], "to_z is unknown"
        windows = []
        if indices:
            windows.append(self._reach_window(op, leave, self._carried(op)))
        if "stock_removal_bounds" in op:
            span, _ = _clearing_span(op["stock_removal_bounds"], _bbox(self.part))
            window = None if span is None else _depth_window(span, to_z)
            if window is not None:
                windows.append(window)
        else:
            sweep = self._sweep(valid, op.get("do"))[1]
            if sweep is not None:
                windows.append(_sweep_window(sweep))
        return windows, None

    def _reach_window(self, op, leave, carried):
        """:meth:`_claim_window` of an op's claims at its wall-check reach."""
        indices = self._indices(op)
        if indices == UNKNOWN:
            return None
        return self._claim_window(indices, max(leave, carried) + COVER_MM)

    def _claim_window(self, indices, reach):
        """The claimed faces' box grown by ``reach``: every point within it of them."""
        if not indices:
            return None
        boxes = [_bbox(self.faces[index]) for index in indices]
        return (
            *(min(box[axis] for box in boxes) - reach for axis in range(3)),
            *(max(box[axis] for box in boxes) + reach for axis in range(3, 6)),
        )

    def _protect(self, shape, leave, window):
        """(``shape`` less the op's guard, or None, and why not).

        With the whole-part guard, all of ``shape``. Otherwise only its part inside
        ``window``, less the exact guard there: nothing outside the window is touched.
        """
        guard, why = self._guard(leave)
        if why is None:
            return shape.cut(guard), None
        if window is None:
            return None, why
        pieces, why = self._guard(leave, window)
        if why is not None:
            return None, why
        shape = shape.common(_box_shape(window))
        for piece in pieces:
            shape = shape.cut(piece)
        return shape, None

    def _guard(self, leave, window=None):
        """(component-owned finished solid offset outward by ``leave``, or None, and why not).

        Arc joins give the exact offset; where OCC cannot build them (a drill-point apex)
        sharp intersection joins give a superset that keeps more stock. The leave stays
        stock: a valid finite solid containing the branch's protected material, or named
        debt, never the nominal solid in its place.

        With a ``window`` box: the exact offset's pieces inside it, as
        :meth:`_window_guard` builds them.
        """
        if leave == 0 or self.protected.isNull():
            return (self.protected if window is None else [self.protected]), None
        if window is not None:
            key = (leave, tuple(window))
            if key not in self.guards:
                self.guards[key] = self._window_guard(leave, key[1])
            return self.guards[key]
        if leave not in self.guards:
            errors = []
            for join in (0, 2):
                try:
                    guard = _offset(self.protected, leave, join)
                    if (
                        not guard.isValid()
                        or len(guard.Solids) != len(self.protected.Solids)
                        or not all(math.isfinite(v) for v in _bbox(guard))
                        or guard.Volume <= self.protected.Volume
                    ):
                        raise ValueError("not a valid finite enclosing solid")
                    if self.protected.cut(guard).Volume > STOCK_MM3:
                        raise ValueError("it does not contain the branch's protected material")
                    self.guards[leave] = (guard, None)
                    break
                except Exception as exc:
                    errors.append(f"{('arc', '', 'intersection')[join]} joins: {exc}")
            else:
                self.guards[leave] = (
                    None,
                    f"protected finished material offset by its {_r(leave)} mm "
                    f"rough_allowance_mm leave failed ({'; '.join(errors)})",
                )
        return self.guards[leave]

    def _window_guard(self, leave, window):
        """(exact offset pieces of the protected material inside ``window``, or None, and
        why not).

        The branch's protected material (:meth:`_guard`) offset within a box equals the
        offset of its part within the box grown by at least ``leave``, cropped to the box:
        no point beyond the grown box is within ``leave`` of the box. Grown by twice the
        leave, the cut faces' own offsets stay outside the box. Only arc joins, the exact
        offset, qualify; each solid of the material within the grown box, however small,
        must offset to one valid enclosing solid, and every positive cropped component is
        kept. The source and containment Booleans must be valid: faces without a solid are
        invalid, not an empty window.
        """
        grown = (*(v - 2 * leave for v in window[:3]), *(v + 2 * leave for v in window[3:]))
        box = _box_shape(window)
        pieces = []
        try:
            source = _valid(
                self.protected.common(_box_shape(grown)), "the protected material in the grown box"
            )
            for solid in [] if source is None else source.Solids:
                offset = _offset(solid, leave)
                if (
                    not offset.isValid()
                    or len(offset.Solids) != 1
                    or not all(math.isfinite(v) for v in _bbox(offset))
                    or offset.Volume <= solid.Volume
                ):
                    raise ValueError("not a valid finite enclosing solid")
                if solid.cut(offset).Volume > STOCK_MM3:
                    raise ValueError("it does not contain the branch's protected material")
                cropped = _valid(offset.common(box), "cropped to the window it")
                if cropped is not None:
                    pieces.extend(piece for piece in cropped.Solids if piece.Volume > 0)
            inside = _valid(self.protected.common(box), "the protected material in the window")
            for piece in pieces:
                if inside is not None:
                    inside = _valid(inside.cut(piece), "the part in the window less the guard")
            if inside is not None and inside.Volume > STOCK_MM3:
                raise ValueError(
                    "cropped to the window it does not contain the branch's protected material"
                )
        except Exception as exc:
            return None, (
                f"protected finished material offset by its {_r(leave)} mm rough_allowance_mm "
                f"leave within [{', '.join(_r(v) for v in window)}] failed (arc joins: {exc})"
            )
        return pieces, None

    def _slabs(self, valid, leave, carried):
        """(unclaimed neighbours of claimed lateral faces thickened past ``carried``, the
        lateral faces, and why not) when ``carried`` exceeds this op's ``leave``."""
        lateral = [index for index in valid if self._lateral(index)]
        if carried <= leave or not lateral:
            return [], [], None
        if self.neighbours is None:
            self.neighbours = {}
            for _, a, b in _shared_edges(self.faces, range(len(self.finished.Faces))):
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
                    slab = _offset(self.faces[index], thickness, fill=True)
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

    def _band(self, stock, valid, to_z, leave, carried, window):
        """(connected groups of lineage leave pieces a lower-leave op cuts off its claimed
        lateral faces, or None, and why not).

        Stock within the ``carried`` leave of the finished part but outside this op's own
        guard, less its unclaimed neighbours thickened past that leave, in groups bordering
        a claimed lateral face: convex wedges between claimed faces go, unclaimed faces keep
        their skin, and raw stock beyond the leave stays for :meth:`_covered`. Where the
        whole part does not offset by ``carried``, that leave near the claims is the exact
        union of their :meth:`_skin` primitives, cut piece by piece and joined by contact,
        never fused; own guard within ``window``. Neighbour slabs are cut one by one. Every
        positive fragment is kept, however small, in every group that borders a claimed
        lateral face; no kept piece may overlap a slab or the finished part.
        """
        slabs, lateral, why = self._slabs(valid, leave, carried)
        if why is not None or not lateral or carried <= leave:
            return None, why
        outer, why = self._guard(carried)
        if why is None:
            parts = [stock.common(outer)]
        else:
            parts, skin_why = self._skin(valid, carried)
            if skin_why is not None:
                return None, f"{why}; {skin_why}"
            parts = [stock.common(primitive) for primitive in parts]
        solids = []
        try:
            for part in parts:
                part = _material(part, "stock within the lineage leave")
                if part is not None:
                    part, why = self._protect(part, leave, window)
                    if why is not None:
                        return None, why
                    part = _material(part, "that stock outside the op's guard")
                for slab in slabs:
                    if part is not None:
                        part = _material(part.cut(slab), "that stock less a neighbour's skin")
                if to_z is not None and part is not None:
                    part = _material(part.common(self._above(to_z)), "that stock above to_z")
                if part is not None:
                    solids.extend(piece for piece in part.Solids if piece.Volume > 0)
        except ValueError as exc:
            return None, f"the {_r(carried)} mm lineage leave band is not derivable ({exc})"
        groups = [[piece] for piece in solids] if outer is not None else _touching(solids)
        groups = [
            group
            for group in groups
            if any(
                _distance(piece, self.faces[i])[0] < leave + STOCK_TOL
                for piece in group
                for i in lateral
            )
        ]
        for piece in (piece for group in groups for piece in group):
            overlap = sum(piece.common(solid).Volume for solid in [self.finished, *slabs])
            # The stock these pieces leave is checked valid and free of them in _remove.
            if overlap > STOCK_MM3:
                return None, (
                    f"the {_r(carried)} mm lineage leave band overlaps the finished part or "
                    f"an unclaimed neighbour's skin by {_r(overlap)} mm^3"
                )
        return (groups or None), None

    def _skin(self, valid, leave):
        """(primitives whose union is the finished part offset by ``leave`` near the claimed
        faces and their convex shared edges, or None, and why not).

        Each claimed face thickened along its normal; on each convex edge two claimed
        faces share, a :func:`_tube` with a ball on each of its vertices, so the convex
        wedge between claimed faces goes. Tangent and concave shared edges add nothing
        beyond the slabs. A shared edge whose kind :func:`_dihedral` cannot prove for its
        whole length is debt. Built per primitive and never fused, so OCC cannot silently
        drop one.
        """
        key = (tuple(valid), leave)
        if key not in self.skins:
            primitives, vertices = [], []
            try:
                for index in valid:
                    face, label = self.faces[index], self.owner.labels[index]
                    try:
                        slab = _offset(face, leave, fill=True)
                        if slab.Volume <= HIT_MM3 or not slab.isValid():
                            raise ValueError("empty or invalid thickened face")
                    except Exception as exc:
                        raise ValueError(f"{label} thickened: {exc}") from exc
                    primitives.append(slab)
                for edge, a, b in _shared_edges(self.faces, valid):
                    labels = f"the edge {self.owner.labels[a]} shares with {self.owner.labels[b]}"
                    kind = _dihedral(edge, self.faces[a], self.faces[b])
                    if kind is None:
                        raise ValueError(
                            f"{labels} is not a line or arc both faces are invariant along, "
                            "so its tangent, concave or convex kind is unproven"
                        )
                    if kind in ("tangent", "concave"):
                        continue
                    try:
                        primitives.append(_tube(edge, leave))
                    except Exception as exc:
                        raise ValueError(f"{labels}: {exc}") from exc
                    for vertex in edge.Vertexes:
                        if not any(vertex.isSame(v) for v in vertices):
                            vertices.append(vertex)
                            primitives.append(Part.makeSphere(leave, vertex.Point))
            except Exception as exc:
                self.skins[key] = (
                    None,
                    f"claimed faces' {_r(leave)} mm lineage leave skin failed ({exc})",
                )
            else:
                self.skins[key] = (primitives, None)
        return self.skins[key]

    @staticmethod
    def _unproven(facts, reason):
        """Unknown stock blocks clearance; only component-certain hits and corner radii survive."""
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
        if name in self.owner.joint_features:
            return [self.owner.joint_features[name]["label"]], f"joint feature {name!r}"
        declared = self.owner._declared()
        if not isinstance(name, str) or name not in declared:
            return None, f"feature {name!r} is not declared"
        return declared[name], f"feature {name!r}"

    def _indices(self, op):
        """Claimed STEP or analytic transient indexes; only STEP indexes earn final coverage."""
        if isinstance(op.get("joint_cut"), dict):
            return self.owner.joint_op_indices.get(self._subject(op), UNKNOWN)
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
        if isinstance(op.get("joint_cut"), dict):
            try:
                self._joint_check(op)
            except (ValueError, _Unknown) as exc:
                return UNKNOWN, [], str(exc)
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
        stop = hold.get("stop")
        if stop:
            self._add_owned(stop["solids"], "fixture", _pose_matrix(stop["pose"]), "stop")
        clamps = self._place_clamps(hold)
        self.clamp_parts = [
            (name, V(*clamp["pose"]["z"]) * -1, parts)
            for (name, parts), clamp in zip(clamps, hold.get("clamps", []), strict=True)
        ]
        self.fixture_debts.extend(str(debt) for debt in hold.get("debts", []))
        self.fixture_gaps.extend(str(gap) for gap in hold.get("gaps", []))
        self._place_steady_rests(hold)
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

    def _place_steady_rests(self, hold):
        """A steady rest is a static ring at ``at_z_mm``, ``body_length_mm`` long: from the
        entry stock's outer radius under it (its jaws ride there) out to half its measured
        ``body_dia_mm``. It obstructs only the ops it serves."""
        for rest in hold.get("steady_rests", []):
            name = f"steady rest {rest['name']}"
            z0 = rest["at_z_mm"] - rest["body_length_mm"] / 2
            z1 = z0 + rest["body_length_mm"]
            under = _band(0.0, self._outer(), z0, z1)
            common = under.common(self.part) if under is not None else None
            if common is None or common.Volume <= STOCK_MM3:
                self.fixture_gaps.append(
                    f"{name} at z {_r(rest['at_z_mm'])} mm has no work to ride"
                )
                continue
            ring = _band(_max_radius(common), rest["body_dia_mm"] / 2, z0, z1)
            if ring is None:
                self.fixture_gaps.append(f"{name} body_dia_mm does not clear the work it rides")
                continue
            self._add(name, "rest", ring)["subjects"] = rest["subjects"]

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

    def _fixture_hits(self, solid, subject=None):
        """Names of placed fixture components (revolved on a lathe) that ``solid`` meets.

        A rest component serving only listed ops is parked off the work for any other
        ``subject``; without a subject every component counts.
        """
        box = _bbox(solid)
        names = set()
        for component in self.fixture:
            subjects = component.get("subjects", "all")
            if subject is not None and subjects != "all" and subject not in subjects:
                continue
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
        for index, box in enumerate(self.face_boxes[: len(self.finished.Faces)]):
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
        """Arriving stock, exact fixture, and this setup's derived removal, in setup axes."""
        size = max(self.box[3] - self.box[0], self.box[4] - self.box[1], self.box[5] - self.box[2])
        tolerance = max(0.01, size / 400)
        meshes, render_debts = [], []
        lathe = self.setup.get("machine_kind") == "lathe"
        output, removal = None, None
        if self.stock_out is not None:
            try:
                output = self._placed(self.stock_out)
                removal = self.part.cut(output)
            except Exception:
                render_debts.append("NOT SHOWN: material removed could not be drawn.")
                output = None
        else:
            render_debts.append("NOT SHOWN: cuts are unresolved; this is the arriving stock only.")

        meridian = None
        if lathe:
            x0, _, z0, x1, _, z1 = self.box
            vertices = [
                V(x0 - 1, 0, z0 - 1),
                V(x1 + 1, 0, z0 - 1),
                V(x1 + 1, 0, z1 + 1),
                V(x0 - 1, 0, z1 + 1),
            ]
            meridian = Part.Face(Part.makePolygon(vertices + [vertices[0]]))

        def mesh(shape, colour, hatch=False, section=False):
            # A lathe elevation is a meridian section: the removed annulus's
            # outside surface must not hide the retained core behind it.
            points, triangles = (
                shape.common(meridian) if section else shape
            ).tessellate(tolerance)
            meshes.append(([(p.x, p.y, p.z) for p in points], triangles, colour, hatch))

        mesh(output if output is not None else self.part, _COLOURS["part"], section=lathe)
        if removal is not None and removal.Volume > STOCK_MM3:
            mesh(removal, _COLOURS["removed"], True, section=lathe)
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
        rests = self._rest_render(debts)
        solids += [(name, jaw, _COLOURS["rest"]) for name, jaws, _ in rests for jaw in jaws]
        for _, shape, colour in solids + possible:
            mesh(shape, colour)
        parallels = any(c["role"] == "parallel" for c in self.fixture)
        scene = {
            "fixture_kind": _fixture_kind(self.setup.get("hold")),
            "jaws": jaws,
            "parallels": "absent"
            if not self._expects_parallels()
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
            ]
            + [
                {"name": name, "role": "follow_rest", "exact": True, "pose": pose}
                for name, _, pose in rests
            ],
            "debts": debts,
        }
        annotation = self.setup.get("render", {})
        view = "lathe" if lathe else "plan" if scene["fixture_kind"] == "custom" else "isometric"
        tool, tool_debt = self._render_tool(annotation, lathe)
        if tool_debt:
            render_debts.append(tool_debt)
        jaw_z = (
            self.hold["pose"]["origin_mm"][2]
            if lathe and self.hold and isinstance(self.hold.get("pose"), dict)
            else max(self.jaws[side][5] for side in ("fixed", "moving"))
            if self.jaws is not None
            else None
        )
        datums = [{"label": end["label"], "point_mm": [0.0, 0.0, end["z_mm"]]}
                  for end in annotation.get("ends", [])]
        for datum in annotation.get("datums", []):
            indices = self.owner.features.get(datum["feature"])
            if isinstance(indices, list) and indices:
                boxes = [self.face_boxes[i] for i in indices]
                box = [min(b[i] for b in boxes) for i in range(3)] + [
                    max(b[i] for b in boxes) for i in range(3, 6)
                ]
                datums.append({
                    "label": datum["label"],
                    "point_mm": [(box[i] + box[i + 3]) / 2 for i in range(3)],
                })
        notes = []
        if not self.ops:
            notes.append("Holding/fit-up only: no cutting operation in this setup.")
        if removal is not None and removal.Volume <= STOCK_MM3:
            notes.append("No material removed in this setup.")
        if lathe and self.hold and _number(jaw_z):
            back = jaw_z - self.hold.get("jaw_depth_mm", 0) - self.hold.get("body_length_mm", 0)
            if self.box[2] < back - STOCK_TOL:
                notes.append("Bar passes through the spindle bore.")
        if (
            view == "plan"
            and self.hold
            and self.hold.get("clamps")
            and not annotation.get("clamp_order_declared")
        ):
            render_debts.append("NOT SHOWN: tightening order is not declared; follow the hold instructions.")
        shows = ["holding", "setup axes and zero"]
        if tool is not None:
            shows.append("selected tool approach")
        if removal is not None:
            shows.append("material removed this setup (amber hatch)")
        if annotation.get("paths") or annotation.get("axial_paths"):
            shows.append("profile sketch keyed to the coordinate rows")
        legend = [
            "Blue-grey: material retained after this setup.",
            "Amber hatch: material removed in this setup.",
            "Brown/purple: holding. Green: selected tool and approach.",
            "Dashed machine outlines: context only, not measured solids.",
        ]
        if not lathe:
            legend.append("Dashed blue: nominal part outline, not proof that it has been cut.")
        if removal is None:
            legend[0] = "Blue-grey: arriving stock; cuts not confirmed."
            legend.pop(1)
        components = self._render_components(annotation)
        for name, jaws, _ in rests:
            boxes = [_bbox(jaw) for jaw in jaws]
            box = [min(b[i] for b in boxes) for i in range(3)] + [
                max(b[i] for b in boxes) for i in range(3, 6)
            ]
            centre = [(box[i] + box[i + 3]) / 2 for i in range(3)]
            components.append(
                {"name": name, "label": "FOLLOW REST", "role": "rest", "box_mm": box,
                 "center_mm": centre}
            )
        clamp_labels = {
            component["label"].split(": ", 1)[0]: component["label"]
            for component in components if component["label"].startswith("C") and ": " in component["label"]
        }
        spec = {
            "setup_id": self.setup.get("id"),
            "view": view,
            "stock_box": list(self.box),
            "components": components,
            "zero_mm": [0.0, 0.0, 0.0],
            "jaw_front_z_mm": jaw_z,
            "stickout_mm": annotation.get("stickout_mm"),
            "datums": datums,
            "primary_tool": tool,
            "paths": annotation.get("paths", []),
            "axial_paths": annotation.get("axial_paths", []),
            "waypoints": annotation.get("waypoints", []),
            "fixed_jaw_label": annotation.get("fixed_jaw_label"),
            "custom_clamp_order": [
                clamp_labels[key]
                for key in sorted(
                    (key for key in clamp_labels if key[1:].isdigit()),
                    key=lambda key: int(key[1:]),
                )
            ],
            "preload": annotation.get("preload"),
            "legend": legend,
            "notes": notes + render_debts,
            "nominal_outline_mm": [
                [[p.x, p.y, p.z] for p in edge.discretize(Deflection=tolerance)]
                for edge in self.finished.Edges
                if edge.Length > STOCK_TOL
            ] if not lathe else [],
        }
        if lathe:
            spec["lathe_profiles"] = self._render_profiles(output, jaw_z)
        scene.update({
            "view": view, "width_px": 1600, "height_px": 1000,
            "shows": shows, "legend": legend, "render_debts": render_debts,
            "waypoints": spec["waypoints"], "primary_op": tool.get("op") if tool else None,
        })
        return render_diagram(meshes, spec), scene

    def _render_components(self, annotation):
        """Callout assemblies, keeping every exact solid in the actual drawing."""
        grouped = {}
        order = annotation.get("clamp_order", [])
        for component in self.fixture:
            name, owner, role = component["name"], component["owner"], component["role"]
            local = name.rsplit(":", 1)[-1]
            key = owner if role == "clamp" or owner == "stop" else local
            if role == "clamp":
                index = next((c["index"] for c in annotation.get("clamps", [])
                              if c["owner"] == owner), None)
                label = next((c["label"] for c in annotation.get("clamps", [])
                              if c["owner"] == owner), owner.replace("_", " "))
                if index in order:
                    label = f"C{order.index(index) + 1}: {label}"
            elif owner == "stop":
                key, label, role = owner, "STOP", "stop"
            else:
                label = local.replace("_", " ").replace("-", " ").upper()
                if name == "fixed_jaw":
                    label, role = annotation.get("fixed_jaw_label", "FIXED JAW"), "fixed_jaw"
                elif name == "moving_jaw":
                    label, role = "MOVING JAW", "moving_jaw"
                elif local.startswith("pad"):
                    role = "pad"
                elif local.startswith("base"):
                    label, role = "FIXTURE PLATE", "plate"
                elif role == "fixture":
                    # The shop view labels the assembly, not every bolt/shim
                    # primitive. All exact solids and names stay in the scene.
                    key, label = owner + ":body_supports", "FIXTURE BODY / SUPPORTS"
            box = component["bbox"]
            if key in grouped:
                previous = grouped[key]["box_mm"]
                box = [min(previous[i], box[i]) for i in range(3)] + [
                    max(previous[i], box[i]) for i in range(3, 6)
                ]
            grouped[key] = {"name": key, "label": label, "role": role, "box_mm": list(box)}
        for component in grouped.values():
            box = component["box_mm"]
            component["center_mm"] = [(box[i] + box[i + 3]) / 2 for i in range(3)]
        return list(grouped.values())

    def _render_tool(self, annotation, lathe):
        """Selected primary cutter's actual silhouette at an illustrative approach pose."""
        if not self.ops:
            return None, None
        op = self.ops[0]
        label = annotation.get("tools", {}).get(str(op.get("subject", "").rsplit(":", 1)[-1]))
        op_number = str(op.get("subject", "")).rsplit(":", 1)[-1]
        label = label or "selected tool"
        if lathe and _turned(op):
            tool, missing, holder_missing = self._turn_tool(op)
            if missing:
                return None, "STOP: selected turning tool dimensions are unresolved; do not run."
            if _number(op.get("to_z")):
                z = op["to_z"]
            elif _number(op.get("z_from")) and _number(op.get("z_to")):
                z = (op["z_from"] + op["z_to"]) / 2
            else:
                indices = self._indices(op)
                z = max(self.faces[index].CenterOfMass.z for index in indices) if isinstance(indices, list) and indices else self.box[5]
            r = max(abs(self.box[0]), abs(self.box[3])) + tool["radius_mm"] + 3
            section, holders = self._turn_sections(tool, (r, z), not holder_missing)
            outlines = [[[x, 0.0, station] for x, station in polygon]
                        for polygon in [section] + (holders or [])]
            tip = [r, 0.0, z]
            approach = [[r + 15, 0.0, z], tip]
        elif _sawn(op) and _positive(op, "kerf_mm") is not None:
            plane = op.get("cut_plane", {})
            if not isinstance(plane, dict):
                return None, "STOP: saw cut plane is unresolved; do not run."
            axis = {"x": 0, "y": 1, "z": 2}.get(plane.get("axis"))
            if axis is None or not _number(plane.get("value")):
                return None, "STOP: saw cut plane is unresolved; do not run."
            transverse = (axis + 1) % 3
            tip = [(self.box[i] + self.box[i + 3]) / 2 for i in range(3)]
            tip[axis] = plane["value"]
            kerf = op["kerf_mm"]
            outline = []
            for side, end in ((-1, 0), (1, 0), (1, 3), (-1, 3)):
                point = list(tip)
                point[axis] += side * kerf / 2
                point[transverse] = self.box[transverse + end]
                outline.append(point)
            outlines = [outline]
            start = list(tip)
            start[transverse] = self.box[transverse + 3] + 15
            approach = [start, tip]
            label += " (blade symbol; width = kerf)"
        else:
            radius, length = _positive(op, "radius_mm"), _positive(op, "flute_len_mm")
            if radius is None or length is None:
                return None, "STOP: selected cutter dimensions are unresolved; do not run."
            indices = self._indices(op)
            point = self.faces[indices[0]].CenterOfMass if isinstance(indices, list) and indices else V(0, 0, self.box[5])
            x, y, z = point.x, point.y, self.box[5] + 5
            tip = [x, y, z]
            outlines = [[[x - radius, y, z], [x + radius, y, z],
                         [x + radius, y, z + length], [x - radius, y, z + length]]]
            approach = [[x, y, z + length + 12], [x, y, self.box[5]]]
        feed = None
        direction = annotation.get("directions", {}).get(op_number)
        if lathe:
            delta = (
                [0.0, 0.0, -12.0] if direction == "toward_chuck"
                else [0.0, 0.0, 12.0] if direction == "from_chuck"
                else [12.0, 0.0, 0.0] if direction == "radially_outward"
                else [-12.0, 0.0, 0.0] if direction == "radially_inward"
                else [-12.0, 0.0, 0.0] if op.get("do") in ("part_off", "cut_to_fit")
                else None
            )
            if delta is not None:
                start = [tip[0] + 8.0, tip[1], tip[2]]
                feed = [start, [start[i] + delta[i] for i in range(3)]]
        return {
            "label": label, "op": op_number, "tip_mm": tip,
            "outline_mm": outlines[0], "outlines_mm": outlines, "approach_mm": approach,
            "feed_mm": feed,
        }, None

    def _render_profiles(self, output, jaw_z):
        """Clipped real meridian chords for the enlarged exposed-end detail."""
        lower = jaw_z if _number(jaw_z) else self.box[2]
        diameter = max(self.box[3] - self.box[0], self.box[4] - self.box[1])
        upper = min(self.box[5], lower + 3 * diameter)
        profiles = []
        for label, shape, colour in (
            ("arriving stock", self.part, _COLOURS["removed"]),
            ("after this setup", output, _COLOURS["part"]),
        ):
            if shape is None:
                continue
            lines = []
            for r0, z0, r1, z1 in _meridian_segments(shape):
                if max(z0, z1) < lower or min(z0, z1) > upper:
                    continue
                if z1 != z0:
                    t0, t1 = sorted(((lower - z0) / (z1 - z0), (upper - z0) / (z1 - z0)))
                    lo, hi = max(0.0, t0), min(1.0, t1)
                    if hi < lo:
                        continue
                    lines.append([[r0 + (r1 - r0) * lo, z0 + (z1 - z0) * lo],
                                  [r0 + (r1 - r0) * hi, z0 + (z1 - z0) * hi]])
                else:
                    lines.append([[r0, z0], [r1, z1]])
            profiles.append({"label": label, "colour": colour, "lines": lines})
        return profiles

    def _rest_render(self, debts):
        """[(name, jaw solids, pose)] of each posed follow rest at its first served op's
        first cutting point; an unposed complete rest is a scene debt."""
        drawn = []
        for rest in (self.hold or {}).get("follow_rests", []):
            if rest.get("missing"):
                continue  # its host debt is already a scene debt
            name = f"follow rest {rest['name']}"
            for op in self.ops:
                record = self.rest_poses.get((rest["name"], self._subject(op)))
                if record is not None and record["render"] is not None:
                    jaws, z = record["render"]
                    pose = f"jaws for {self._subject(op)} cutting at z {z} mm"
                    drawn.append((name, jaws, pose))
                    break
            else:
                debts.append(f"{name} not drawn: no served op posed its jaws")
        return drawn

    def _expects_parallels(self):
        """Named parallels, or a vise not declared seated on its bed (zero parallels height)."""
        hold = self.hold
        if hold is None:
            return False
        if "parallels_ref" in hold:
            return True
        return hold.get("kind") == "vise" and hold.get("parallels_height_mm") != 0

    def _parallels(self):
        """Parallel boxes from declared dimensions and centres, or the debt that prevents them."""
        if not self._expects_parallels():
            return None, None
        hold = self.hold
        vise = hold.get("kind") == "vise"
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

    def _joint_axial_op(self, op):
        """Centred real axial tool/holder solids, never tangent offset cylinders on a cone."""
        _, spec, _ = self._joint_check(op)
        removal, reason = self._joint_removal(op, self.part)
        if reason:
            return self._op_unknown(op, reason)
        after = self.part if removal is None else self.part.cut(removal)
        entry = self.matrix.multVec(V(*spec["at_mm"]))
        radius = _positive(op, "radius_mm")
        flute = _positive(op, "flute_len_mm")
        tip = entry.z - spec["depth_mm"]
        slope = None
        if spec["action"] in {"drill", "spot"}:
            slope = math.tan(math.radians(spec["point_angle_deg"] / 2))
            if spec["action"] == "drill":
                tip -= spec["diameter_mm"] / (2 * slope)
        facts = {
            "reasons": {},
            "claimed_indices": self._indices(op),
            "claim_errors": [],
            "sample_count": 1,
            "corner_radii_mm": [],
            "reach_depth_mm": _r(max(entry.z, self.box[5]) - tip),
            "obstacles": {"tool": [], "holder": []},
            "hit_refs": {"tool": [], "holder": []},
            "min_hits": {"tool": 0, "holder": 0},
        }
        solids = {}
        if radius is not None and flute is not None:
            if radius <= LIFT:
                facts["reasons"]["tool_hits"] = "axial tool radius is below modelling clearance"
            elif slope is None:
                solids["tool"] = Part.makeCylinder(
                    radius - LIFT, flute, V(entry.x, entry.y, tip + LIFT), Z
                )
            else:
                solids["tool"] = _pointed_cutter(
                    entry.x, entry.y, tip + LIFT, radius - LIFT, slope, flute
                )
        else:
            facts["reasons"]["tool_hits"] = "axial tool radius/flute length is unmeasured"
        keys = ("holder_radius_mm", "holder_gauge_len_mm", "projection_mm")
        holder = {key: _positive(op, key) for key in keys}
        missing = [key for key, value in holder.items() if value is None]
        if not missing:
            solids["holder"] = Part.makeCylinder(
                holder["holder_radius_mm"],
                holder["holder_gauge_len_mm"],
                V(entry.x, entry.y, tip + holder["projection_mm"]),
                Z,
            )
        else:
            facts["reasons"]["holder_hits"] = "op lacks " + ", ".join(missing)
        for kind in ("tool", "holder"):
            solid = solids.get(kind)
            if solid is None:
                facts[kind + "_hits"] = UNKNOWN
                if kind == "holder":
                    facts["holder_wall_hits"] = UNKNOWN
                    facts["reasons"]["holder_wall_hits"] = facts["reasons"]["holder_hits"]
                continue
            hit = solid.common(after).Volume > HIT_MM3
            obstacles = set(self._fixture_hits(solid)) if self.fixture_ready else set()
            if hit:
                obstacles.add("part")
            certain = int(bool(obstacles))
            facts["min_hits"][kind] = certain
            facts["obstacles"][kind] = sorted(obstacles)
            if kind == "holder":
                facts["holder_wall_hits"] = int(hit)
            if not self.fixture_ready or self.fixture_gaps or self.fixture_possible:
                facts[kind + "_hits"] = UNKNOWN
                facts["reasons"][kind + "_hits"] = (
                    self.fixture_reason or "fixture geometry is incomplete"
                )
            else:
                facts[kind + "_hits"] = certain
        if facts["reasons"]:
            facts["reason"] = next(iter(facts["reasons"].values()))
        return facts

    def _op(self, op):
        if _sawn(op):
            # The stock builder's facts; otherwise why the stock before this saw is unknown.
            if self.stock_reason is not None:
                return self._saw_facts(op, self.stock_reason)
            if id(op) in self.saws:
                return self.saws[id(op)]
            return self._saw_facts(op, self.cuts[id(op)][2])
        owner = self.owner
        if isinstance(op.get("joint_cut"), dict):
            if self.stock_reason is not None:
                return self._op_unknown(op, self.stock_reason)
            _, reason = self._joint_removal(op, self.part)
            if reason is not None:
                facts = self._op_unknown(op, reason)
                if self._subject(op) in self.joint_errors:
                    facts["joint_error"] = self.joint_errors[self._subject(op)]
                return facts
            if op["joint_cut"].get("action") in {"drill", "spot", "ream"}:
                return self._joint_axial_op(op)
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
            facts = self._turn_op(op, indices)
            if isinstance(op.get("joint_cut"), dict):
                previous = facts["reasons"].pop("corner_radii_mm", None)
                corner = self._joint_corners(op)
                facts["corner_radii_mm"] = corner if isinstance(corner, list) else UNKNOWN
                if not isinstance(corner, list):
                    facts["reasons"]["corner_radii_mm"] = corner
                if facts.get("reason") == previous:
                    facts.pop("reason", None)
                if facts["reasons"] and "reason" not in facts:
                    facts["reason"] = next(iter(facts["reasons"].values()))
            return facts
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
            hole_meta = op.get("hole")
            if isinstance(hole_meta, dict) and hole_meta.get("complete_form") is True:
                caps = sorted(self._own_caps(valid))
                if caps:
                    # Its claimed caps must be formed by the setup's final stock: run()
                    # fills ``unformed`` from :meth:`_finish`, or why it stays unknown.
                    facts["cap_completion"] = {"caps": caps, "unformed": UNKNOWN}
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
            corner = (
                (
                    self._joint_corners(op)
                    if isinstance(op.get("joint_cut"), dict)
                    else self._corners(sampled, hole)
                )
                if not undefined
                else reasons["claimed_indices"]
            )
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
        if any(index >= len(self.finished.Faces) for index in indices):
            return "transient joint targets do not establish finished-part corner topology"
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
            shell = _offset(Part.Shell([self.faces[index]]), -LIFT, fill=True)
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
        removal = cylinder.cut(self.protected)
        # A spot never widens its own bore: its mouth must fit the future bore, so an
        # over-deep spot's cone stays an obstacle against that finished wall.
        for _, _, members in axes if action != "spot" else ():
            for index, bore in members:
                excess = radius - bore
                if excess <= PLANE_TOL:
                    continue
                # This op's own bore wall is cutting material; sizing checks its diameter.
                try:
                    shell = _offset(Part.Shell([self.faces[index]]), -(excess + LIFT), fill=True)
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
                if (
                    isinstance(op, dict)
                    and not isinstance(op.get("joint_cut"), dict)
                    and isinstance(op.get("hole"), dict)
                ):
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
                for _, a, b in _shared_edges(self.faces, range(len(self.finished.Faces))):
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

    def _flute_regions(self, op, regions):
        """The material a flute meets: the stock the builder accepted after this op
        (:meth:`_build`), each region keeping its sampled face's shell out.

        Earlier ops' material is absent only because their accepted cuts removed it; later
        cuts are never credited, nor is the cut of an op that stopped the builder: it meets
        its whole before-op stock. A milling op with a claim facing away from the approach
        is credited no removal either; a hole op always is. Once an earlier cut is
        underivable the stock before this op is unknown: only finished material, present in
        any real stock, remains a flute obstacle. Holder obstacles and reach never see this;
        they keep the setup-entry ``regions``.
        """
        if self.stock_reason is not None:
            return regions
        before, after, unknown = self.cuts[id(op)]
        if unknown is not None:
            stock = self.finished
        elif isinstance(op.get("hole"), dict) or not self._claims(op)[1]:
            stock = after
        else:
            stock = before
        if stock is self.part:
            return regions
        gone = self.part.cut(stock)
        if gone.Volume <= HIT_MM3:
            return regions
        # Fresh per op: its culling memos describe only this op's flute material.
        return {
            index: (_Culled(region.shape.cut(gone)), None) if region is not None else (None, why)
            for index, (region, why) in regions.items()
        }

    def _floor_edges(self, index):
        """``(edge, wall index, edge box, end points)`` per sharp concave rising wall of a
        +Z planar floor.

        One scan of every shared edge caches each floor's walls, the edges each face pair
        shares (for :meth:`_wall_corner` and :meth:`_wall_edge_at`) and the floors whose
        wall edges could not be classified; asking for such a floor raises with the reason.
        """
        if self.floor_adjacency is None:
            walls, failed, pairs = {}, {}, {}
            for edge, a, b in _shared_edges(self.faces, range(len(self.finished.Faces))):
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
                    ends = [vertex.Point for vertex in edge.Vertexes]
                    walls.setdefault(floor, []).append((edge, wall, _bbox(edge), ends))
            self.floor_adjacency = {
                "walls": walls,
                "failed": failed,
                "pairs": pairs,
                "corners": {},
                "sharp": {},
            }
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

    def _floor_contacts(self, index, point, reach, origin):
        """Rising walls of floor ``index`` whose concave floor edge is on or within ``reach``.

        Returns ``(wall, nx, ny, offset, circle, incident, slot)`` per edge: ``(nx, ny)`` is
        the unit in-plane normal into the floor at the edge's nearest point, ``offset`` the
        point's distance from that point along it (0 for an edge through the point),
        ``circle`` ``(cx, cy, radius)`` when the edge is a circle concave toward the floor,
        else None, and ``slot`` the edge's position in :meth:`_floor_edges`. Along an edge,
        and at a concave wall/wall corner, that normal is the wall's. A point beyond an
        edge's end rather than along its normal is bounded by that edge only through the
        wall/wall edge rising from that end (:meth:`_floor_end`): at a concave corner by the
        wall's own line; at a sharp convex corner past the end of every wall meeting there
        by the corner itself, whose normal points from the corner to the point (the nearest
        boundary point has no single wall normal there); past a tangent junction or a
        split face nothing. A solved axis ``point`` away from its sample
        ``origin`` whose nearest such edge has it behind that edge's interior stands in the
        wall's material: it crossed that wall, which then bounds it. A sample on the floor
        behind a farther face (a thin rib's far side) is not inside material and is not.
        """
        near, vertex = [], None
        margin = max(reach, STOCK_TOL)
        for slot, (edge, wall, box, _) in enumerate(self._floor_edges(index)):
            if any(
                point[axis] < box[axis] - margin or point[axis] > box[axis + 3] + margin
                for axis in range(3)
            ):
                continue
            if vertex is None:
                vertex = Part.Vertex(point)
            distance, nearest, support = edge.distToShape(vertex)
            if distance <= STOCK_TOL or distance < reach:
                # The native nearest support: the edge's end vertex, or None inside the edge.
                end = edge.Vertexes[support[0][1]] if support[0][0] == "Vertex" else None
                near.append((slot, edge, wall, distance, nearest[0][0], end))
        closest = min((entry[3] for entry in near), default=0.0)
        moved = point.distanceToPoint(origin) > STOCK_TOL
        contacts = []
        for slot, edge, wall, distance, foot, _ in near:
            incident = distance <= STOCK_TOL
            normal = _normal_at(self.faces[wall], foot)
            length = math.hypot(normal.x, normal.y)
            if length < 1e-9:
                continue
            nx, ny = normal.x / length, normal.y / length
            offset, radial = 0.0, False
            if not incident:
                offset = nx * (point.x - foot.x) + ny * (point.y - foot.y)
                crossed = (
                    moved and distance <= closest + PLANE_TOL and distance + offset <= PLANE_TOL
                )
                if distance - offset > PLANE_TOL and not crossed:
                    corner = self._floor_end(index, slot, point, near)
                    if corner is None:
                        continue
                    if corner is not True:
                        # The nearest boundary point is the convex corner: the axis moves
                        # straight away from it until tangent.
                        nx, ny = (point.x - corner.x) / distance, (point.y - corner.y) / distance
                        offset, radial = distance, True
            circle, curve = None, edge.Curve
            if not radial and isinstance(curve, Part.Circle) and abs(curve.Axis.z) >= PARALLEL:
                centre = curve.Center
                if nx * (centre.x - foot.x) + ny * (centre.y - foot.y) > 0:
                    circle = (centre.x, centre.y, curve.Radius)
            contacts.append((wall, nx, ny, offset, circle, incident, slot))
        return contacts

    def _floor_end(self, index, slot, point, near):
        """How floor edge ``slot`` of floor ``index`` bounds ``point`` beyond its end:
        True by the wall's own line, the corner vertex's point to stand clear of, or None.

        ``near`` is :meth:`_floor_contacts`'s ``(slot, edge, wall, distance, foot, end)``
        per floor edge within reach, ``end`` the edge's end vertex when that is the native
        nearest support (None for a foot inside the edge, however close to its end). Only
        the wall/wall edges rising from that vertex classify the corner
        (:meth:`_wall_edge_at`), never another edge the two faces share elsewhere. A
        concave one makes it a corner bounded by the wall's line. A sharp convex corner
        bounds by the vertex only when ``point`` is past the end of every other wall's
        floor edge there too: the vertex is that edge's native nearest support and
        ``point`` lies off its normal (``distance - offset > PLANE_TOL``), so a point in
        front of or behind a wall's interior is bounded by that wall alone.
        """
        found = {entry[0]: entry for entry in near}
        wall, end = found[slot][2], found[slot][5]
        if end is None:
            return None
        others = []
        for other_slot, (edge, other, _, _) in enumerate(self._floor_edges(index)):
            if other_slot == slot or other == wall:
                continue
            if any(vertex.isSame(end) for vertex in edge.Vertexes):
                sharp = self._wall_edge_at(wall, other, end)
                if sharp is True:
                    return True
                others.append((found.get(other_slot), other, sharp))
        if not others:
            return None
        for entry, other, sharp in others:
            if sharp is not False or entry is None or entry[5] is None or not entry[5].isSame(end):
                return None
            _, _, _, distance, foot, _ = entry
            normal = _normal_at(self.faces[other], foot)
            length = math.hypot(normal.x, normal.y)
            if length < 1e-9:
                return None
            offset = (normal.x * (point.x - foot.x) + normal.y * (point.y - foot.y)) / length
            if distance - offset <= PLANE_TOL:
                return None
        return end.Point

    def _wall_edge_at(self, a, b, vertex):
        """:func:`_concave_edge` of the edge faces ``a`` and ``b`` share at ``vertex``:
        True when one is concave, False when every one is convex, None when they share
        none there or one is tangent (cached per shared edge)."""
        key = (min(a, b), max(a, b))
        sharp = self.floor_adjacency["sharp"]
        verdicts = []
        for at, edge in enumerate(self.floor_adjacency["pairs"].get(key, ())):
            if not any(end.isSame(vertex) for end in edge.Vertexes):
                continue
            if (key, at) not in sharp:
                sharp[key, at] = _concave_edge(self.finished, edge, self.faces[a], self.faces[b])
            verdicts.append(sharp[key, at])
        if True in verdicts:
            return True
        return False if verdicts and all(v is False for v in verdicts) else None

    def _floor_corners(self, index):
        """(vertex, floor normal) where two rising walls meet the floor at a concave corner.

        Convex island corners get no pose of their own: samples beside them stand tangent
        to one wall, or past both walls' ends to the corner itself (:meth:`_floor_end`).
        """
        face = self.faces[index]
        found = []
        for vertex in face.Vertexes:
            walls = [
                contact[0]
                for contact in self._floor_contacts(index, vertex.Point, 0.0, vertex.Point)
                if contact[5]
            ]
            if any(
                a != b and self._wall_corner(a, b)
                for i, a in enumerate(walls)
                for b in walls[i + 1 :]
            ):
                found.append((vertex.Point, _normal_at(face, vertex.Point)))
        return found

    def _floor_axis(self, index, point, radius):
        """User decision 2026-10-05: the nearest axis tangent to the walls bounding a sample.

        Every concave floor edge (curved ones included) on or within ``radius`` of the
        sample, as :meth:`_floor_contacts` keeps it, bounds the axis offset ``d`` from the
        sample (:func:`_nearest_clear`). Moving the axis can bring it within ``radius`` of
        a concave edge the sample was not near (the far wall of an acute cusp), or carry it
        across one (past an island in a narrow corner), so each such edge within
        ``radius`` of the solved axis joins the bounds and the axis is solved again. This
        constraint closure only ever adds an edge not yet bounding, so it ends after at
        most one round per rising floor edge: it is not a search.
        A sample bounded by no wall keeps its own axis, and so does one no axis can
        clear every bounding wall from (a tool wider than its slot, gap or circle), so
        that pose reports the real hit. A half-plane is exact for a straight edge and for
        one convex edge alone; on a non-circular concave curve, or a circle smaller than
        the tool, it is only the nearest point's tangent, so a pose still crossing the
        wall reports that real hit.
        """
        lines, discs, seen = [], [], set()
        at, dx, dy = point, 0.0, 0.0
        while True:
            fresh = False
            contacts = self._floor_contacts(index, at, radius, point)
            for _, nx, ny, offset, circle, _, slot in contacts:
                if slot in seen:
                    continue
                seen.add(slot)
                fresh = True
                if circle is not None and circle[2] >= radius:
                    discs.append((circle[0] - point.x, circle[1] - point.y, circle[2] - radius))
                else:
                    # ``offset`` is measured from ``at``; the bound is on ``d`` from ``point``.
                    lines.append((nx, ny, radius - offset + nx * dx + ny * dy))
            if not fresh:
                return at.x, at.y
            solved = _nearest_clear(lines, discs)
            if solved is None:
                return point.x, point.y
            dx, dy = solved
            at = FreeCAD.Vector(point.x + dx, point.y + dy, point.z)

    def _cover_axis(self, index, radius, leave):
        """The one tool axis of a +Z planar floor the whole of which fits inside the
        cutter disc, or None when no such axis is legal.

        The axis is the area centroid of the axes covering the face (:func:`_cover_locus`,
        cover by the actual ``radius``), or its certified single point. A rising wall's
        concave floor edge is part of the face, so a cutter covering that edge and
        standing ``radius + leave`` clear of the wall stands on its centre of curvature:
        any wall with a leave and any wall that is not a concave Z circle leave no axis.
        Else the axis is a wall centre, taken in sorted order, that meets every wall's
        own floor bound ``|c - o| <= rho - radius`` (the tangent-circle bound of
        :meth:`_floor_axis`, within its 1e-7 mm) and that the exact check
        (:func:`_cover_farthest`) shows covers the face; none means no axis. With walls
        the area locus is built only for an outer contour with other curves. No axis
        means the face keeps its surface samples. Raises ValueError, cached per (face,
        radius, leave), when a wall or the cover locus cannot be decided.
        """
        key = (index, radius, leave)
        if key not in self.cover_axes:
            try:
                self.cover_axes[key] = (self._cover_axis_of(index, radius, leave), None)
            except Exception as exc:
                self.cover_axes[key] = (None, exc)
        axis, exc = self.cover_axes[key]
        if exc is not None:
            raise ValueError(str(exc)) from exc
        return axis

    def _cover_axis_of(self, index, radius, leave):
        face = self.faces[index]
        walls = []
        for edge, wall, _, _ in self._floor_edges(index):
            curve = edge.Curve
            if leave > 0 or not isinstance(curve, Part.Circle) or abs(curve.Axis.z) < PARALLEL:
                return None
            foot = edge.valueAt((edge.FirstParameter + edge.LastParameter) / 2)
            normal = _normal_at(self.faces[wall], foot)
            centre = curve.Center
            if normal.x * (centre.x - foot.x) + normal.y * (centre.y - foot.y) <= 0:
                return None  # an island's foot: its centre lies inside the wall
            walls.append((centre.x, centre.y, curve.Radius))
        points, arcs, unsupported = _cover_contour(face)
        if not walls or unsupported:
            # With rising walls and a line/circle contour the exact check at each wall
            # centre decides alone: the area locus may be a sub-tolerance sliver.
            kind, axis = _cover_locus(face, radius)
            if kind == "empty":
                return None
            if not walls:
                return axis
        for x, y, _ in sorted(walls):
            if _cover_farthest(points, arcs, x, y) <= radius + COVER_TOL and all(
                math.hypot(x - ox, y - oy) <= rho - radius + COVER_GAP for ox, oy, rho in walls
            ):
                return x, y
        return None

    def _sample_facts(self, op, indices, radius, facts):
        reasons = facts["reasons"]
        joint = isinstance(op.get("joint_cut"), dict)
        hole_cut = (
            self._hole_cut(op, indices, radius)
            if not joint and isinstance(op.get("hole"), dict)
            else None
        )
        if hole_cut is not None and hole_cut["reason"] is not None:
            for key in self._MEASURED:
                facts[key] = UNKNOWN
                reasons[key] = hole_cut["reason"]
            return
        slope = hole_cut["cone_slope"] if hole_cut is not None else None
        # Transient faces already include their joint cut's allowance; ordinary rough
        # poses stand their known leave off the finished surface along the normal.
        leave, why = (0.0, None) if joint or hole_cut is not None else self._guarded(op)
        if why is not None:
            for key in self._MEASURED:
                facts[key] = UNKNOWN
                reasons[key] = why
            return
        # (index, point, normal, whether the point is already the face's one tool axis)
        samples, sample_problems, undefined = [], [], {}
        for index in indices:
            face = self.faces[index]
            # Transient joint faces are not finished-part floors with corner topology.
            floor = (
                not joint
                and isinstance(face.Surface, Part.Plane)
                and _normal_at(face, face.Surface.Position).z >= PARALLEL
            )
            if floor and hole_cut is None:
                # The whole face fits the cutter disc: one pose stands for all of it.
                try:
                    axis = self._cover_axis(index, radius, leave)
                except Exception as exc:
                    undefined[index] = exc
                    continue
                if axis is not None:
                    point = FreeCAD.Vector(axis[0], axis[1], face.Surface.Position.z)
                    samples.append((index, point, _normal_at(face, point), True))
                    continue
            found, missed = _face_samples(face, max(radius, 1.0))
            if floor and found:
                try:
                    found.extend(self._floor_corners(index))
                except Exception as exc:
                    undefined[index] = exc
                    continue
            samples.extend((index, point, normal, False) for point, normal in found)
            if missed:
                sample_problems.append(
                    f"{self.owner.labels[index]}: {missed} sample point(s) "
                    "had no defined surface normal"
                )
        flute = _positive(op, "flute_len_mm")
        keys = ("holder_radius_mm", "holder_gauge_len_mm", "projection_mm")
        holder = {key: _positive(op, key) for key in keys}
        holder_missing = sorted(key for key, value in holder.items() if value is None)
        placed = []  # (index, point, axis x, axis y, tip z, downward)
        for index, point, normal, fixed in samples:
            if index in undefined:
                continue
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
                if not joint and not fixed:
                    try:
                        ax, ay = self._floor_axis(index, point, radius + leave)
                    except Exception as exc:
                        undefined[index] = exc
                        continue
            # An authored to_z above the finished face is the cut's actual endpoint.
            if _number(op.get("to_z")):
                level = max(level, op["to_z"])
            placed.append((index, point, ax, ay, level + LIFT, normal.z < -1e-3))
        # A floor with no derivable pose drops its own poses only: every other face's
        # certain hits stay counted while the op's measured facts become unknown.
        placed = [entry for entry in placed if entry[0] not in undefined]
        sample_problems.extend(
            f"{self.owner.labels[index]}: floor tool pose is undefined ({exc})"
            for index, exc in undefined.items()
        )
        sample_reason = "; ".join(sample_problems) if sample_problems else None
        facts["sample_count"] = UNKNOWN if sample_reason else len(samples)
        if sample_reason:
            reasons["sample_count"] = sample_reason
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
        flute_regions = self._flute_regions(op, regions)
        # Why the stock before this op is unknown: its flute then met finished material only.
        unbuilt = None if self.stock_reason is not None else self.cuts[id(op)][2]
        region_reason = (
            "; ".join(reason for _, reason in regions.values() if reason is not None) or None
        )
        tool_ready = flute is not None and region_reason is None
        holder_ready = not holder_missing and region_reason is None
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
                labels = set()
                obstacle = (flute_regions if kind == "tool" else regions)[index][0]
                # A pointed tool's flute is its cone and body, for part and jaws alike; its
                # gross cylinder only culls. Holders keep their own cylinder.
                solid = (
                    _pointed_cutter(ax, ay, tip, radius - LIFT, slope, flute)
                    if kind == "tool" and slope is not None
                    else None
                )
                common = obstacle.common(*cylinder, solid) if obstacle is not None else None
                if common is not None:
                    labels.add("part")
                    if solid is not None:
                        counter[3].update(self._hit_refs(common, cylinder, index, solid))
                    else:
                        key = (cylinder, index)
                        if key not in obstacle.hit_refs:
                            obstacle.hit_refs[key] = self._hit_refs(common, cylinder, index)
                        counter[3].update(obstacle.hit_refs[key])
                if self.fixture_ready:
                    labels.update(self._fixture_cylinder_hits(cylinder, solid))
                if labels:
                    counter[0] += 1
                    counter[2].update(labels)
                elif (
                    not self.fixture_ready
                    or self.fixture_gaps
                    or any(_tool_hits_box(cylinder, box, solid) for _, box in self.fixture_possible)
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
            facts["min_hits"][kind] = certain
            if sample_reason:
                facts[key] = UNKNOWN
                reasons[key] = sample_reason
            elif not ready:
                facts[key] = UNKNOWN
                reasons[key] = missing
            elif kind == "tool" and unbuilt is not None:
                facts[key] = UNKNOWN
                reasons[key] = (
                    f"the stock before this op is unknown ({unbuilt}); "
                    f"{certain} sample(s) certainly hit finished or fixture material"
                )
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

    def _hit_refs(self, common, cylinder, own, solid=None):
        """Finished face refs bounding a hit, excluding only the sampled face itself.

        ``solid`` is the cutter inside ``cylinder`` when it is not the cylinder itself.
        """
        refs = set()
        common_box = _tolerant_box(common)
        for index in range(len(self.finished.Faces)):
            face = self.faces[index]
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

    def _turn_removal(self, op, valid, stock):
        """(revolved stock outside component-owned finished material removed here or None, why).

        A ``to_z`` op faces: everything beyond the plane on its claims' axial side, outside
        their innermost radius, up to the protected material's end on that side (a shoulder)
        or the stock end when nothing protected lies beyond (an end face). A facing op, part-off
        or cut-to-fit given ``to_dia_mm`` sweeps from to_dia/2 (0: the axis) to the stock end
        instead: the separated piece goes, whatever bore the part receives later. Other ops
        cut down to each claimed meridian; with ``z_from``/``z_to`` the profile is extended at
        its end radii and its axial faces swept along their normals to the window, then
        limited to it. Without a window removal stays within the claimed faces' own z extent.
        Only material still present after preceding ops is removal: coincident faces and
        zero-volume boolean remnants from a spring pass never become cutting solids.
        """
        if isinstance(op.get("joint_cut"), dict):
            return self._joint_removal(op, stock)
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
        regions = [
            region
            for region in regions
            if region is not None and not region.isNull() and region.Volume > HIT_MM3
        ]
        if not regions:
            return None, None
        removal = regions[0].fuse(regions[1:]) if len(regions) > 1 else regions[0]
        if window is not None:
            removal = removal.common(_band(0.0, outer, *window))
        if removal.isNull() or removal.Volume <= HIT_MM3:
            return None, None
        removal = stock.common(removal)
        if removal.isNull() or removal.Volume <= HIT_MM3:
            return None, None
        if self.protected.Volume > HIT_MM3:
            removal = removal.cut(self.protected)
        pieces = [piece for piece in removal.Solids if piece.Volume > HIT_MM3]
        if not pieces:
            return None, None
        if not all(piece.isValid() for piece in pieces):
            return None, "turned removal boolean is invalid"
        return (pieces[0] if len(pieces) == 1 else Part.makeCompound(pieces)), None

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
        end = stock_end
        if self.protected.Solids:
            box = _bbox(self.protected)
            protected_end = box[5] if side > 0 else box[2]
            if (protected_end - to_z) * side > PLANE_TOL:
                end = protected_end
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
            # cutting protected material back out keeps the region exact. The region closes
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

    def _turn_cut(self, op, stock):
        """(this turning op's revolved removal or None, and why it cannot be derived)."""
        valid, _, why = self._claims(op)
        if not isinstance(valid, list):
            return None, why
        to_z = op.get("to_z")
        if to_z is not None and not _number(to_z):
            return None, "to_z is unknown"
        try:
            return self._turn_removal(op, valid, stock)
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
                    removal, why = self._turn_cut(other, stock)
                    if why is None and removal is not None:
                        try:
                            after = stock.cut(removal)
                            if after.isNull() or after.Volume <= STOCK_MM3:
                                why = "turned removal leaves no stock"
                            elif not after.isValid():
                                why = "turned remaining-stock boolean is invalid"
                            else:
                                stock = after
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

    def _turn_fixture(self, solid, subject):
        """Names of placed fixture solids a revolved tool meets; None while none are placed."""
        if not self.fixture_ready:
            return None
        return self._fixture_hits(solid, subject)

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
        # A failed removal proves only protected material present on this exact branch.
        part = obstacle if obstacle is not None else self.certain
        try:
            segments = _meridian_segments(part)
        except Exception as exc:
            segments = []
            obstacle_reason = obstacle_reason or f"meridian section for tool poses failed ({exc})"
        part_box = _bbox(part) if part.Solids else self.box
        placed = self.fixture_ready
        outer = self._outer()
        subject = self._subject(op)
        # Served rests that cannot be posed leave every clear sample uncertain.
        posed, blocked = self._rest_setup(op, obstacle, segments, obstacle_reason)
        rest_gaps = list(blocked)
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
            rest_hits, rest_gap = self._rest_hits(posed, tool, point, section, pieces, subject)
            if rest_gap is not None and rest_gap not in rest_gaps:
                rest_gaps.append(rest_gap)
            for kind, solid in solids.items():
                if solid is None:
                    continue
                labels = set(rest_hits[kind])
                if _boxes_overlap(_bbox(solid), part_box):
                    common = solid.common(part)
                    if common.Volume > HIT_MM3:
                        labels.add("part")
                        counters[kind][2].update(self._turn_hit_refs(common, solid, index))
                        wall_hits += kind == "holder"
                labels.update(self._turn_fixture(solid, subject) or ())
                if labels:
                    counters[kind][0] += 1
                    counters[kind][1].update(labels)
                elif (
                    self.fixture_gaps
                    or rest_gap is not None
                    or blocked
                    or any(_boxes_overlap(_bbox(solid), box) for _, box in self.fixture_possible)
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
                reasons[key] = f"{obstacle_reason}; {certain} sample(s) hit certain branch material"
            elif not placed:
                facts[key] = UNKNOWN
                reasons[key] = (
                    f"fixture solids unresolved ({self.fixture_reason}); "
                    f"{certain} sample(s) hit part material"
                )
            elif uncertain[kind] and (self.fixture_gaps or rest_gaps):
                facts[key] = UNKNOWN
                reasons[key] = (
                    f"undrawn fixture components ({'; '.join([*self.fixture_gaps, *rest_gaps])}); "
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

    # ------------------------------------------------------------------ follow rests

    def _follow_rests(self, op):
        """Declared follow rests serving this turning op; any other op sees them parked
        off the work (docs/rules-geometry.md "Follow and steady rests")."""
        subject = self._subject(op)
        rests = (self.hold or {}).get("follow_rests", [])
        return [rest for rest in rests if rest["subjects"] == "all" or subject in rest["subjects"]]

    def _turn_before(self, op):
        """(the profile a turning op meets, or None, and why not)."""
        previous = None
        for other in self.ops:
            if other is op:
                break
            if _turned(other):
                previous = other
        return (self.part, None) if previous is None else self._turn_obstacle(previous)

    def _rest_setup(self, op, obstacle, segments, obstacle_reason):
        """([(rest, profile under its jaws, its meridian section, pose record)], why each
        other serving rest cannot be posed).

        Jaws trailing the tool (``turned``) ride the profile after the op; jaws leading it
        (``uncut``) the profile before it.
        """
        if not self.fixture_ready:
            return [], []
        posed, blocked = [], []
        for rest in self._follow_rests(op):
            label = f"follow rest {rest['name']!r}"
            if rest.get("missing"):
                blocked.append(f"{label} not drawn: " + ", ".join(rest["missing"]) + " unresolved")
                continue
            if rest["side"] == "turned":
                profile, why, section = obstacle, obstacle_reason, segments
            else:
                profile, why = self._turn_before(op)
                section = None
                if profile is not None:
                    try:
                        section = _meridian_segments(profile)
                    except Exception as exc:
                        profile, why = None, f"meridian section failed ({exc})"
            if profile is None or why is not None:
                blocked.append(f"{label} jaws cannot be posed: {why}")
                continue
            record = {"poses": 0, "clashes": {}, "gaps": [], "render": None}
            self.rest_poses[(rest["name"], self._subject(op))] = record
            posed.append((rest, profile, section, record))
        return posed, blocked

    def _rest_hits(self, posed, tool, point, section, pieces, subject):
        """({tool kind: follow rest names its jaws meet}, why a rest could not be posed or
        None) for one cutting point; jaw clashes with the work and the fixture are recorded.

        The tool is no longer revolved here: rest and tool both ride the carriage. Its
        insert, head and shank lie on and below centre height (the rake face on centre,
        +Y toward the jaws' positive angles), the toolpost body on both sides of it.
        """
        hits = {"tool": set(), "holder": set()}
        if not posed:
            return hits, None
        prisms = {"tool": _prism(section, -TOOL_DROP_MM, 0.0)}
        if pieces is not None:
            shank = _prism(pieces[0], -TOOL_DROP_MM, 0.0)
            body = _prism(pieces[1], -TOOL_DROP_MM, TOOL_DROP_MM)
            prisms["holder"] = shank.fuse(body) if shank is not None and body is not None else None
        if any(prism is None for prism in prisms.values()):
            return hits, "a tool section could not be built against the follow rest jaws"
        gap = None
        for rest, profile, rest_section, record in posed:
            label = f"follow rest {rest['name']}"
            # The jaws are set to the diameter at the cutting point: the one just turned
            # (trailing) or the one about to be cut (leading).
            radius = _outer_radius(rest_section, point[1], point[1])
            if radius is None or radius <= PLANE_TOL:
                why = f"{label} has no work diameter at the cut z {_r(point[1])} mm to ride"
                if why not in record["gaps"]:
                    record["gaps"].append(why)
                gap = gap or why
                continue
            ahead = tool["feed_z"] if rest["side"] == "uncut" else -tool["feed_z"]
            middle = point[1] + ahead * rest["lead_mm"]
            z0, depth = middle - rest["jaw_depth_mm"] / 2, rest["jaw_depth_mm"]
            width = rest["jaw_width_mm"]
            jaws = []
            for angle in rest["jaw_angles_deg"]:
                jaw = Part.makeBox(rest["jaw_height_mm"], width, depth, V(radius, -width / 2, z0))
                jaw.rotate(V(0, 0, 0), V(0, 0, 1), angle)
                jaws.append(jaw)
                for other in self._fixture_hits(jaw, subject):
                    key = f"{label} jaw at {_r(angle)} deg meets {other}"
                    record["clashes"][key] = record["clashes"].get(key, 0) + 1
            record["poses"] += 1
            if record["render"] is None:
                record["render"] = (jaws, _r(point[1]))
            # Riding the set diameter is contact; work beyond it under the jaws is a clash.
            band = _band(radius + STOCK_TOL, self._outer(), z0, z0 + depth)
            if band is not None and band.common(profile).Volume > STOCK_MM3:
                key = (
                    f"{label} jaws set to the {_r(2 * radius)} mm diameter meet larger work "
                    "under them"
                )
                record["clashes"][key] = record["clashes"].get(key, 0) + 1
            for kind, prism in prisms.items():
                if any(prism.common(jaw).Volume > HIT_MM3 for jaw in jaws):
                    hits[kind].add(label)
        return hits, gap

    def _rest_interference(self, facts, ops):
        """Fold each served op's follow-rest poses into the setup's fixture clashes/debts."""
        if self.hold is None or "fixture_clashes" not in facts:
            return
        clashes, debts = [], []
        for rest in self.hold.get("follow_rests", []):
            if rest.get("missing"):
                continue  # its host debt is already a fixture_clash debt
            for op in self.ops:
                subject = self._subject(op)
                if not _turned(op) or rest not in self._follow_rests(op):
                    continue
                record = self.rest_poses.get((rest["name"], subject))
                if record is None:
                    why = ops.get(subject, {}).get("reason", "the op's tool poses are unresolved")
                    debts.append(f"follow rest {rest['name']!r} not posed for {subject}: {why}")
                    continue
                clashes += [
                    f"{text} at {count} of {record['poses']} pose(s) of {subject}"
                    for text, count in sorted(record["clashes"].items())
                ]
                debts += record["gaps"]
        facts["fixture_clashes"] = facts["fixture_clashes"] + clashes
        facts["fixture_clash_debts"] = list(dict.fromkeys(facts["fixture_clash_debts"] + debts))

    def _turn_hit_refs(self, common, solid, own):
        """Finished face refs bounding a turning-tool hit, excluding the sampled face."""
        box, refs = _bbox(solid), set()
        common_box = _tolerant_box(common)
        for index in range(len(self.finished.Faces)):
            face = self.faces[index]
            if index == own or not _boxes_overlap(box, self.face_boxes[index]):
                continue
            if _distant_box(common_box, self.face_boxes[index]):
                continue
            if face.common(solid).Area > CONTACT_MM2 and _distance(common, face)[0] < 1e-6:
                refs.add(self.owner.labels[index])
        return refs

    def _turn_corners(self, indices):
        """Sorted concave meridian corner radii between/inside claims, or why unknown."""
        if any(index >= len(self.finished.Faces) for index in indices):
            return "transient joint targets do not establish finished-part corner topology"
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
