"""Finite, authored-side clearance shared by host and standalone kernel jobs.

Closed packets describe a region: exact line/circle ray parity determines material,
then the nearest *finite* edge determines distance. Open packets describe only local
sides: interior projections have their authored sign, free/convex end caps are
positive, and a shared concave vertex has a negative nearest-vertex sector. No edge
is added to close an open packet. Unsupported or contradictory topology is unknown
(``ValueError``), never an unsigned-distance fallback.
"""

import math
from collections.abc import Mapping
from dataclasses import dataclass, replace

_TAU = 2 * math.pi
_SIDE_EPS = 1e-9


def _number(value):
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return False
    try:
        return math.isfinite(value)
    except OverflowError:
        return False


def _point(value):
    if not isinstance(value, (list, tuple)) or len(value) != 2 or not all(map(_number, value)):
        raise ValueError("boundary points must have two finite numeric coordinates")
    return float(value[0]), float(value[1])


def _sub(a, b):
    return a[0] - b[0], a[1] - b[1]


def _dot(a, b):
    return a[0] * b[0] + a[1] * b[1]


def _cross(a, b):
    return a[0] * b[1] - a[1] * b[0]


def _sincos(degrees):
    angle = degrees % 360
    if angle == 0:
        return 0.0, 1.0
    if angle == 90:
        return 1.0, 0.0
    if angle == 180:
        return 0.0, -1.0
    if angle == 270:
        return -1.0, 0.0
    return math.sin(math.radians(angle)), math.cos(math.radians(angle))


@dataclass(frozen=True, slots=True)
class _Wall:
    kind: str
    a: tuple
    b: tuple
    run: tuple
    length: float
    normal: tuple
    centre: tuple = (0.0, 0.0)
    radius: float = 0.0
    start: float = 0.0
    sweep: float = 0.0
    outward: int = 0
    full: bool = False
    start_unit: tuple = (0.0, 0.0)
    end_unit: tuple = (0.0, 0.0)

    def at(self, t):
        if self.kind == "line":
            return self.a[0] + t * self.run[0], self.a[1] + t * self.run[1]
        if t == 0:
            return self.a
        if t == 1:
            return self.b
        angle = self.start + t * self.sweep
        return (
            self.centre[0] + self.radius * math.cos(angle),
            self.centre[1] + self.radius * math.sin(angle),
        )

    def parameters(self, angle):
        if self.full:
            return ((angle - self.start) * (1 if self.sweep > 0 else -1) % _TAU / _TAU,)
        delta = (angle - self.start) * (1 if self.sweep > 0 else -1) % _TAU
        if delta <= abs(self.sweep):
            return (delta / abs(self.sweep),)
        return ()

    def tangent(self, end):
        if self.kind == "line":
            return self.run[0] / self.length, self.run[1] / self.length
        radial = self.start_unit if end == 0 else self.end_unit
        hand = 1 if self.sweep > 0 else -1
        return -hand * radial[1], hand * radial[0]

    def scrap_normal(self, end):
        if self.kind == "line":
            return self.normal
        radial = self.start_unit if end == 0 else self.end_unit
        return self.outward * radial[0], self.outward * radial[1]

    def nearest(self, point):
        """Return unsigned distance, local sign, and endpoint index (or None)."""
        if self.kind == "line":
            offset = _sub(point, self.a)
            projection = _dot(offset, self.run) / self.length
            if 0 <= projection <= self.length:
                signed = _dot(offset, self.normal)
                return abs(signed), -1 if signed < 0 else 1, None
        else:
            offset = _sub(point, self.centre)
            radial = math.hypot(*offset)
            if not radial or self.full or self.parameters(math.atan2(offset[1], offset[0])):
                signed = self.outward * (radial - self.radius)
                return abs(signed), -1 if signed < 0 else 1, None
        da, db = math.dist(point, self.a), math.dist(point, self.b)
        return (da, 1, 0) if da <= db else (db, 1, 1)


def _compile_wall(row, tolerance):
    if not isinstance(row, Mapping):
        raise ValueError("boundary walls must be mappings")
    if row.get("kind") == "line":
        ends = row.get("ends")
        if not isinstance(ends, (list, tuple)) or len(ends) != 2:
            raise ValueError("line boundary needs exactly two endpoints")
        a, b = map(_point, ends)
        run = _sub(b, a)
        length = math.hypot(*run)
        normal = _point(row.get("normal"))
        magnitude = math.hypot(*normal)
        if (
            not math.isfinite(length * length)
            or length <= tolerance
            or not length * length
            or not math.isfinite(magnitude)
            or not magnitude
        ):
            raise ValueError("line boundary or scrap normal is degenerate")
        normal = normal[0] / magnitude, normal[1] / magnitude
        if abs(_dot((run[0] / length, run[1] / length), normal)) > _SIDE_EPS:
            raise ValueError("line scrap normal is not perpendicular to its edge")
        hand = 1 if _cross(run, normal) > 0 else -1
        normal = -hand * run[1] / length, hand * run[0] / length
        return _Wall("line", a, b, run, length, normal)
    if row.get("kind") != "arc":
        raise ValueError("boundary kind must be line or arc")
    centre = _point(row.get("centre"))
    radius, start, sweep = (row.get(key) for key in ("radius", "start_deg", "sweep_deg"))
    outward = row.get("outward")
    if not (
        all(map(_number, (radius, start, sweep, outward)))
        and radius > 0
        and 0 < abs(sweep) <= 360
        and outward in (-1, 1)
    ):
        raise ValueError(
            "arc needs a finite positive radius, finite sweep, and authored scrap side"
        )
    full = abs(sweep) == 360
    length = radius * abs(math.radians(sweep))
    if (
        not math.isfinite(radius * radius)
        or not radius * radius
        or not math.isfinite(length)
        or length <= tolerance
    ):
        raise ValueError("arc boundary is degenerate")
    start %= 360
    sa, ca = _sincos(start)
    sb, cb = _sincos(start + sweep)
    a = centre[0] + radius * ca, centre[1] + radius * sa
    b = a if full else (centre[0] + radius * cb, centre[1] + radius * sb)
    if not all(map(_number, (*a, *b))):
        raise ValueError("arc endpoints overflow")
    if not full and math.dist(a, b) <= tolerance:
        raise ValueError("a partial arc cannot close itself within the join tolerance")
    return _Wall(
        "arc",
        a,
        b,
        (0.0, 0.0),
        length,
        (0.0, 0.0),
        centre,
        float(radius),
        math.radians(start),
        math.radians(sweep),
        int(outward),
        full,
        (ca, sa),
        (cb, sb),
    )


def _same_geometry(first, second, tolerance):
    if first.kind != second.kind:
        return False
    if first.kind == "line":
        return (first.a == second.a and first.b == second.b) or (
            first.a == second.b and first.b == second.a
        )
    if first.centre != second.centre or first.radius != second.radius or first.full != second.full:
        return False
    if first.full:
        return True
    if abs(first.sweep) != abs(second.sweep):
        return False
    if (first.sweep > 0) == (second.sweep > 0):
        return (
            math.dist(first.a, second.a) <= tolerance and math.dist(first.b, second.b) <= tolerance
        )
    return math.dist(first.a, second.b) <= tolerance and math.dist(first.b, second.a) <= tolerance


def _deduplicate(walls, tolerance):
    result = []
    for wall in walls:
        for other in result:
            if _same_geometry(wall, other, tolerance):
                consistent = (
                    _dot(wall.normal, other.normal) > 0
                    if wall.kind == "line"
                    else wall.outward == other.outward
                )
                if not consistent:
                    raise ValueError(
                        "duplicate boundary walls have contradictory authored scrap sides"
                    )
                break
        else:
            result.append(wall)
    return tuple(result)


def _line_intersections(a, b, c, d):
    """Actual finite intersections as parameters on the first segment.

    Collinear overlap returns its endpoints; topology validation rejects positive
    overlap separately. No tolerance extends either segment.
    """
    u, v, offset = _sub(b, a), _sub(d, c), _sub(c, a)
    determinant = _cross(u, v)
    if determinant:
        t, s = _cross(offset, v) / determinant, _cross(offset, u) / determinant
        return (t,) if 0 <= t <= 1 and 0 <= s <= 1 else ()
    if _cross(offset, u):
        return ()
    square = _dot(u, u)
    if not square:
        return ()
    lo, hi = sorted((_dot(offset, u) / square, _dot(_sub(d, a), u) / square))
    lo, hi = max(0.0, lo), min(1.0, hi)
    return (lo, hi) if lo < hi else ((lo,) if lo == hi else ())


def _segment_arc(a, b, arc):
    run, offset = _sub(b, a), _sub(a, arc.centre)
    square = _dot(run, run)
    if not square:
        return ()
    # Closest line point avoids the cancellation of the quadratic discriminant.
    middle = -_dot(offset, run) / square
    closest = offset[0] + middle * run[0], offset[1] + middle * run[1]
    height = arc.radius * arc.radius - _dot(closest, closest)
    if height < 0:
        return ()
    reach = math.sqrt(height / square)
    result = []
    for t in (middle - reach, middle + reach):
        if 0 <= t <= 1:
            point = a[0] + t * run[0], a[1] + t * run[1]
            angle = math.atan2(point[1] - arc.centre[1], point[0] - arc.centre[0])
            if arc.parameters(angle) and t not in result:
                result.append(t)
    return tuple(result)


def _arc_intersections(first, second):
    offset = _sub(second.centre, first.centre)
    distance = math.hypot(*offset)
    if not distance:
        if first.radius != second.radius:
            return (), False
        if first.full or second.full:
            return (), True
        # On one circle, endpoints partition all possible overlaps. A midpoint
        # in both finite sweeps proves positive-length overlap, not just a touch.
        angles = sorted(
            {
                first.start % _TAU,
                (first.start + first.sweep) % _TAU,
                second.start % _TAU,
                (second.start + second.sweep) % _TAU,
            }
        )
        for a, b in zip(angles, (*angles[1:], angles[0] + _TAU), strict=True):
            if first.parameters((a + b) / 2) and second.parameters((a + b) / 2):
                return (), True
        points = tuple(
            p
            for p in (first.a, first.b)
            if second.parameters(math.atan2(p[1] - second.centre[1], p[0] - second.centre[0]))
        )
        return points, False
    if distance > first.radius + second.radius or distance < abs(first.radius - second.radius):
        return (), False
    along = (first.radius * first.radius - second.radius * second.radius + distance * distance) / (
        2 * distance
    )
    height = max(0.0, first.radius * first.radius - along * along)
    base = (
        first.centre[0] + along * offset[0] / distance,
        first.centre[1] + along * offset[1] / distance,
    )
    reach = math.sqrt(height)
    points = []
    for hand in (-1, 1):
        point = (
            base[0] - hand * reach * offset[1] / distance,
            base[1] + hand * reach * offset[0] / distance,
        )
        if all(
            w.parameters(math.atan2(point[1] - w.centre[1], point[0] - w.centre[0]))
            for w in (first, second)
        ):
            if point not in points:
                points.append(point)
    return tuple(points), False


def _intersections(first, second):
    if first.kind == second.kind == "arc":
        return _arc_intersections(first, second)
    if first.kind == second.kind == "line":
        parameters = _line_intersections(first.a, first.b, second.a, second.b)
        return tuple(first.at(t) for t in parameters), len(parameters) == 2
    line, arc = (first, second) if first.kind == "line" else (second, first)
    return tuple(line.at(t) for t in _segment_arc(line.a, line.b, arc)), False


@dataclass(frozen=True, slots=True)
class _RaySpan:
    wall: _Wall
    low: float
    high: float
    right: int
    first_y: float = 0.0
    last_y: float = 0.0

    def crosses(self, point):
        x, y = point
        if not self.low <= y < self.high:
            return False
        wall = self.wall
        if wall.kind == "line":
            if wall.run[1]:
                hit = wall.a[0] + (y - wall.a[1]) * wall.run[0] / wall.run[1]
            else:
                # A tolerance-joined horizontal edge can have distinct endpoint
                # events. This join-band event connects their half-open counts;
                # the distance still uses the unchanged actual finite edge.
                hit = wall.a[0] + (y - self.first_y) * wall.run[0] / (self.last_y - self.first_y)
        else:
            height = y - wall.centre[1]
            hit = wall.centre[0] + self.right * math.sqrt(
                max(0.0, wall.radius * wall.radius - height * height)
            )
        return hit > x


@dataclass(frozen=True, slots=True)
class _Loop:
    indices: tuple
    spans: tuple
    circle: _Wall | None
    interior_kept: bool

    def inside(self, point):
        if self.circle is not None:
            return math.dist(point, self.circle.centre) < self.circle.radius
        return sum(span.crosses(point) for span in self.spans) % 2 == 1


def _ray_spans(wall, endpoint_y):
    if wall.kind == "line":
        low, high = sorted(endpoint_y)
        if low == high:
            return ()
        return (_RaySpan(wall, low, high, 0, *endpoint_y),)
    cuts = [0.0, 1.0]
    for angle in (math.pi / 2, 3 * math.pi / 2):
        cuts.extend(t for t in wall.parameters(angle) if 0 < t < 1)
    cuts = sorted(set(cuts))
    spans = []
    for a, b in zip(cuts, cuts[1:], strict=False):
        ya = endpoint_y[0] if a == 0 else wall.at(a)[1]
        yb = endpoint_y[1] if b == 1 else wall.at(b)[1]
        low, high = sorted((ya, yb))
        if low < high:
            right = 1 if math.cos(wall.start + (a + b) / 2 * wall.sweep) > 0 else -1
            spans.append(_RaySpan(wall, low, high, right))
    return tuple(spans)


def _poly_add(first, second, factor=1.0):
    result = list(first) + [0.0] * max(0, len(second) - len(first))
    for index, value in enumerate(second):
        result[index] += factor * value
    return result


def _poly_mul(first, second):
    result = [0.0] * (len(first) + len(second) - 1)
    for i, a in enumerate(first):
        for j, b in enumerate(second):
            result[i + j] += a * b
    return result


def _poly_roots(coefficients):
    """Isolate real roots on [0, 1] between derivative roots; not tessellation.

    Open-side nearest-feature switches are algebraic (degree at most four).
    Extra roots introduced by squaring are harmless additional partitions.
    """
    while len(coefficients) > 1 and coefficients[-1] == 0:
        coefficients.pop()
    magnitude = max(map(abs, coefficients))
    if not magnitude or len(coefficients) == 1:
        return ()
    coefficients = [value / magnitude for value in coefficients]
    if len(coefficients) == 2:
        root = -coefficients[0] / coefficients[1]
        return (root,) if 0 <= root <= 1 else ()

    def value(t):
        result = 0.0
        for coefficient in reversed(coefficients):
            result = result * t + coefficient
        return result

    critical = _poly_roots([i * coefficients[i] for i in range(1, len(coefficients))])
    cuts = sorted({0.0, *critical, 1.0})
    roots = [t for t in cuts if abs(value(t)) <= 64 * math.ulp(1.0)]
    for low, high in zip(cuts, cuts[1:], strict=False):
        lv, hv = value(low), value(high)
        if (lv < 0) == (hv < 0) or not lv or not hv:
            continue
        for _ in range(60):
            middle = (low + high) / 2
            mv = value(middle)
            if not mv or middle == low or middle == high:
                low = high = middle
                break
            if (mv < 0) == (lv < 0):
                low, lv = middle, mv
            else:
                high = middle
        roots.append((low + high) / 2)
    return tuple(roots)


def _feature_switches(first, second):
    q, r = first
    p, s = second
    if not r and not s:
        return _poly_roots(_poly_add(q, p, -1))
    if not r:
        q, p, r, s = p, q, s, r
    difference = _poly_add(_poly_add(q, p, -1), [r * r - s * s])
    if not s:
        return _poly_roots(_poly_add(_poly_mul(difference, difference), q, -4 * r * r))
    middle = _poly_add([4 * r * r * v for v in q], p, 4 * s * s)
    middle = _poly_add(middle, _poly_mul(difference, difference), -1)
    return _poly_roots(_poly_add(_poly_mul(middle, middle), _poly_mul(q, p), -64 * r * r * s * s))


def _touch_boundaries(walls, tolerance):
    """Analytic distance=tolerance partitions, never material/closure edges."""
    if not tolerance:
        return ()
    result = []
    endpoints = set()
    for wall in walls:
        if wall.kind == "line":
            for hand in (-1, 1):
                shift = hand * tolerance * wall.normal[0], hand * tolerance * wall.normal[1]
                result.append(
                    replace(
                        wall,
                        a=(wall.a[0] + shift[0], wall.a[1] + shift[1]),
                        b=(wall.b[0] + shift[0], wall.b[1] + shift[1]),
                    )
                )
        else:
            for radius in (wall.radius - tolerance, wall.radius + tolerance):
                if radius <= 0:
                    continue
                if not math.isfinite(radius * radius):
                    raise ValueError("boundary touch tolerance overflows finite circle math")
                result.append(
                    replace(
                        wall,
                        radius=radius,
                        length=radius * abs(wall.sweep),
                        a=(
                            wall.centre[0] + radius * wall.start_unit[0],
                            wall.centre[1] + radius * wall.start_unit[1],
                        ),
                        b=(
                            wall.centre[0] + radius * wall.end_unit[0],
                            wall.centre[1] + radius * wall.end_unit[1],
                        ),
                    )
                )
        if not wall.full:
            endpoints.update((wall.a, wall.b))
    for point in endpoints:
        result.append(
            _Wall(
                "arc",
                point,
                point,
                (0.0, 0.0),
                _TAU * tolerance,
                (0.0, 0.0),
                point,
                tolerance,
                0.0,
                _TAU,
                1,
                True,
                (1.0, 0.0),
                (1.0, 0.0),
            )
        )
    return tuple(result)


class _Clearance:
    __slots__ = (
        "walls",
        "tolerance",
        "closed",
        "loops",
        "outside_kept",
        "concave",
        "nodes",
        "endpoint_nodes",
        "segment_boundaries",
    )

    def __init__(
        self, walls, tolerance, closed, loops, outside_kept, concave, nodes, endpoint_nodes
    ):
        self.walls = walls
        self.tolerance = tolerance
        self.closed = closed
        self.loops = loops
        self.outside_kept = outside_kept
        self.concave = concave
        self.nodes = nodes
        self.endpoint_nodes = endpoint_nodes
        self.segment_boundaries = walls + _touch_boundaries(walls, tolerance)

    def _kept(self, point):
        return self.outside_kept ^ (sum(loop.inside(point) for loop in self.loops) % 2 == 1)

    def __call__(self, point):
        try:
            point = _point(point)
        except ValueError:
            return -math.inf
        nearest = [wall.nearest(point) for wall in self.walls]
        if any(not math.isfinite(item[0]) for item in nearest):
            return -math.inf
        distance = min(item[0] for item in nearest)
        if distance <= self.tolerance:
            return 0.0
        if self.closed:
            return -distance if self._kept(point) else distance
        negative = False
        for index, (gap, side, end) in enumerate(nearest):
            if gap > distance + self.tolerance:
                continue
            if side < 0:
                negative = True
            if end is not None:
                node = self.endpoint_nodes[index][end]
                if node in self.concave:
                    # Both actual finite edges, not their supporting extensions,
                    # must select this shared cap. Distance ties are conservative.
                    incident = self.nodes[node][1]
                    if all(
                        nearest[i][2] == e and nearest[i][0] <= distance + self.tolerance
                        for i, e in incident
                    ):
                        negative = True
        return -distance if negative else distance

    def cuts_segment(self, a, b):
        """Whether a finite centreline enters material beyond the touch tolerance."""
        a, b = _point(a), _point(b)
        if self(a) < 0 or self(b) < 0:
            return True
        run = _sub(b, a)
        square = _dot(run, run)
        if not square:
            return False
        cuts = {0.0, 1.0}
        for wall in self.segment_boundaries:
            cuts.update(
                _line_intersections(a, b, wall.a, wall.b)
                if wall.kind == "line"
                else _segment_arc(a, b, wall)
            )
        if not self.closed:
            self._open_segment_cuts(a, run, cuts)
        cuts = sorted(cuts)
        return any(
            self((a[0] + (low + high) / 2 * run[0], a[1] + (low + high) / 2 * run[1])) < 0
            for low, high in zip(cuts, cuts[1:], strict=False)
        )

    def _open_segment_cuts(self, a, run, cuts):
        features = []
        square = _dot(run, run)

        def point_feature(point, radius=0.0):
            offset = _sub(a, point)
            features.append(([_dot(offset, offset), 2 * _dot(offset, run), square], radius))

        def linear_cut(value, delta):
            if delta:
                t = -value / delta
                if 0 < t < 1:
                    cuts.add(t)

        for wall in self.walls:
            point_feature(wall.a)
            point_feature(wall.b)
            if wall.kind == "line":
                normal = wall.normal
                value, delta = _dot(_sub(a, wall.a), normal), _dot(run, normal)
                features.append(([value * value, 2 * value * delta, delta * delta], 0.0))
                tangent = wall.run[0] / wall.length, wall.run[1] / wall.length
                linear_cut(_dot(_sub(a, wall.a), tangent), _dot(run, tangent))
                linear_cut(_dot(_sub(a, wall.b), tangent), _dot(run, tangent))
            else:
                point_feature(wall.centre, wall.radius)
                for end in (wall.a, wall.b):
                    radial = _sub(end, wall.centre)
                    linear_cut(_cross(_sub(a, wall.centre), radial), _cross(run, radial))
        for index, feature in enumerate(features):
            for other in features[index + 1 :]:
                cuts.update(_feature_switches(feature, other))


def compile_clearance(walls, tolerance):
    """Compile finite wall math/topology once; return signed-distance predicate.

    ``normal`` is the line's authored scrap normal (normalized here); ``outward``
    is an arc's radial scrap sign. Endpoint joins use only the supplied length
    tolerance. Closed loops must be simple, non-touching, and have consistent
    authored material occupancy, including nested/disjoint loops. Open paths may
    be disconnected, but branches/intersections and mixed open/closed packets are
    ambiguous and rejected. No tessellation, inferred closure, or global cache.
    Repeated equivalent finite walls collapse before topology construction;
    contradictory duplicate scrap sides are invalid. Invalid query coordinates
    conservatively return negative infinity, never NaN.
    """
    if not _number(tolerance) or tolerance < 0:
        raise ValueError("boundary tolerance must be finite and nonnegative")
    if not isinstance(walls, (list, tuple)) or not walls:
        raise ValueError("boundary needs at least one finite wall")
    tolerance = float(tolerance)
    walls = _deduplicate(tuple(_compile_wall(row, tolerance) for row in walls), tolerance)
    endpoints = [
        (i, end, wall.a if end == 0 else wall.b)
        for i, wall in enumerate(walls)
        if not wall.full
        for end in (0, 1)
    ]
    parent = list(range(len(endpoints)))

    def root(index):
        while parent[index] != index:
            parent[index] = parent[parent[index]]
            index = parent[index]
        return index

    for i, (_, _, a) in enumerate(endpoints):
        for j in range(i):
            if math.dist(a, endpoints[j][2]) <= tolerance:
                parent[root(i)] = root(j)
    groups = {}
    for i, entry in enumerate(endpoints):
        groups.setdefault(root(i), []).append(entry)
    nodes = []
    endpoint_nodes = [[None, None] for _ in walls]
    for entries in groups.values():
        if len(entries) > 2 or any(
            math.dist(a[2], b[2]) > tolerance for a in entries for b in entries
        ):
            raise ValueError("ambiguous or branching boundary endpoint joins")
        point = tuple(
            math.fsum(entry[2][axis] for entry in entries) / len(entries) for axis in range(2)
        )
        node = len(nodes)
        incident = tuple((i, end) for i, end, _ in entries)
        nodes.append((point, incident))
        for i, end in incident:
            endpoint_nodes[i][end] = node
        if len(incident) == 2:
            (i, ei), (j, ej) = incident
            ti, tj = walls[i].tangent(ei), walls[j].tangent(ej)
            ti = ti if ei == 0 else (-ti[0], -ti[1])
            tj = tj if ej == 0 else (-tj[0], -tj[1])
            if abs(_cross(ti, tj)) <= 32 * math.ulp(1.0) and _dot(ti, tj) > 0:
                raise ValueError("a shared endpoint has an ambiguous reversing cusp")

    for i, first in enumerate(walls):
        for j, second in enumerate(walls[:i]):
            hits, overlap = _intersections(first, second)
            shared = set(endpoint_nodes[i]) & set(endpoint_nodes[j]) - {None}
            if overlap or any(
                not any(math.dist(point, nodes[node][0]) <= tolerance for node in shared)
                for point in hits
            ):
                raise ValueError("intersecting or overlapping finite boundary edges")

    visited = set()
    components = []
    for first, wall in enumerate(walls):
        if first in visited:
            continue
        if wall.full:
            visited.add(first)
            components.append((True, ((first, 1),)))
            continue
        pending, indices = [first], set()
        while pending:
            index = pending.pop()
            if index in indices:
                continue
            indices.add(index)
            for node in endpoint_nodes[index]:
                pending.extend(i for i, _ in nodes[node][1] if i not in indices)
        ends = [
            (index, end)
            for index in indices
            for end, node in enumerate(endpoint_nodes[index])
            if len(nodes[node][1]) == 1
        ]
        closed = not ends
        if not closed and len(ends) != 2:
            raise ValueError("boundary component is not a simple finite path")
        index, entry = (first, 0) if closed else ends[0]
        ordered = []
        while index not in visited:
            visited.add(index)
            ordered.append((index, 1 if entry == 0 else -1))
            exit_node = endpoint_nodes[index][1 - entry]
            following = [(i, end) for i, end in nodes[exit_node][1] if i != index]
            if not following:
                break
            index, entry = following[0]
        components.append((closed, tuple(ordered)))
    if any(closed for closed, _ in components) and not all(closed for closed, _ in components):
        raise ValueError("mixed open and closed boundary packets are unsupported")
    closed = components[0][0]
    concave = set()
    loops = []
    for is_closed, ordered in components:
        sides = []
        for index, direction in ordered:
            wall = walls[index]
            side = _cross(wall.tangent(0), wall.scrap_normal(0)) * direction
            sides.append(1 if side > 0 else -1)
        if len(set(sides)) != 1:
            raise ValueError("authored scrap sides contradict the connected boundary")
        if is_closed:
            # Rebase area to a real boundary point, avoiding translation cancellation.
            origin = walls[ordered[0][0]].a
            areas = []
            for index, direction in ordered:
                wall = walls[index]
                if wall.kind == "line":
                    area = _cross(_sub(wall.a, origin), _sub(wall.b, origin)) / 2
                else:
                    centre = _sub(wall.centre, origin)
                    area = (
                        centre[0] * (wall.b[1] - wall.a[1])
                        - centre[1] * (wall.b[0] - wall.a[0])
                        + wall.radius * wall.radius * wall.sweep
                    ) / 2
                areas.append(direction * area)
            area = math.fsum(areas)
            if not math.isfinite(area) or abs(area) <= tolerance * sum(
                walls[i].length for i, _ in ordered
            ):
                raise ValueError("closed boundary has ambiguous or degenerate enclosed area")
            interior_kept = sides[0] != (1 if area > 0 else -1)
            circle = (
                walls[ordered[0][0]] if len(ordered) == 1 and walls[ordered[0][0]].full else None
            )
            spans = (
                tuple(
                    span
                    for index, _ in ordered
                    for span in _ray_spans(
                        walls[index], tuple(nodes[node][0][1] for node in endpoint_nodes[index])
                    )
                )
                if circle is None
                else ()
            )
            loops.append(_Loop(tuple(index for index, _ in ordered), spans, circle, interior_kept))
    if not closed:
        for node, (_, incident) in enumerate(nodes):
            if len(incident) != 2:
                continue
            (i, ei), (j, ej) = incident
            ti, tj = walls[i].tangent(ei), walls[j].tangent(ej)
            ti = ti if ei == 0 else (-ti[0], -ti[1])
            tj = tj if ej == 0 else (-tj[0], -tj[1])
            ni, nj = walls[i].scrap_normal(ei), walls[j].scrap_normal(ej)
            if _dot(ni, tj) > _SIDE_EPS and _dot(nj, ti) > _SIDE_EPS:
                concave.add(node)
    outside_kept = None
    for index, loop in enumerate(loops):
        point = walls[loop.indices[0]].at(0.5)
        depth = sum(other.inside(point) for j, other in enumerate(loops) if j != index)
        outside = loop.interior_kept ^ ((depth + 1) % 2 == 1)
        if outside_kept is not None and outside != outside_kept:
            raise ValueError("nested/disjoint loop material identities are inconsistent")
        outside_kept = outside
    return _Clearance(
        walls,
        tolerance,
        closed,
        tuple(loops),
        bool(outside_kept),
        frozenset(concave),
        tuple(nodes),
        tuple(tuple(pair) for pair in endpoint_nodes),
    )
