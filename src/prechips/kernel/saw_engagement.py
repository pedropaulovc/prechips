"""Advancing-rim engagement of a straight-fed finite saw disk (``finite_disk_v1``).

Standard library only: this module is imported both by the host test-suite and by
``freecad_job.py`` inside ``freecadcmd``.

The kerf section is a polygon in feed coordinates ``(s, u)``: ``s`` is distance along the
feed from the cut move's start axis position, ``u`` the transverse offset from the axis
line (the feed turned +90 degrees about setup +Z). A feed-monotone section holds one
material interval ``[a(u), b(u)]`` per ``u``. With blade radius ``R`` the advancing rim
lies ``q(u) = sqrt(R^2 - u^2)`` ahead of the axis, so the rim first meets the material at
``u`` when the axis reaches ``e(u) = a(u) - q(u)`` and leaves it at ``x(u) = b(u) - q(u)``
(docs/rules-geometry.md#mounted-saw-engagement).
"""

from __future__ import annotations

import math
from fractions import Fraction
from numbers import Real

# Endpoint phases closer than this fraction of one tooth pitch cannot resolve a
# threshold reliably. They remain distinct in the exact sweep; a separate bounded
# uncertainty calculation reports their conservative minimum and the tie flag.
TIE_REL = 1e-9


def _finite(value):
    try:
        return isinstance(value, Real) and not isinstance(value, bool) and math.isfinite(value)
    except (OverflowError, TypeError, ValueError):
        return False


def _pair(value):
    try:
        pair = tuple(value)
    except TypeError:
        return None
    if len(pair) != 2 or not all(_finite(number) for number in pair):
        return None
    return tuple(float(number) for number in pair)


def _turn(first, second, third):
    return (second[0] - first[0]) * (third[1] - first[1]) - (second[1] - first[1]) * (
        third[0] - first[0]
    )


def _segments_meet(first, second, third, fourth):
    if any(
        max(first[axis], second[axis]) < min(third[axis], fourth[axis])
        or max(third[axis], fourth[axis]) < min(first[axis], second[axis])
        for axis in (0, 1)
    ):
        return False
    turns = (
        _turn(first, second, third),
        _turn(first, second, fourth),
        _turn(third, fourth, first),
        _turn(third, fourth, second),
    )
    return turns[0] * turns[1] <= 0 and turns[2] * turns[3] <= 0


def monotone_section(points):
    """Return ``(CCW vertex ring, None)`` or ``(None, reason)``.

    Accept one simple polygon, with an optional repeated closing vertex. Exact
    rational orientation predicates on the supplied coordinates reject crossings,
    touching nonadjacent edges, repeated vertices and backtracking edges without
    an epsilon. Holes and nested rings are not a supported input representation.
    A simple ring whose nonhorizontal transverse edges rise once and fall once
    holds one material interval per transverse coordinate.
    """
    try:
        ordered = [_pair(point) for point in points]
    except TypeError:
        return None, "the kerf section is not a finite polygon"
    if any(point is None for point in ordered):
        return None, "the kerf section is not a finite polygon"
    if len(ordered) > 1 and ordered[0] == ordered[-1]:
        ordered.pop()
    if len(ordered) < 3:
        return None, "the kerf section is not a finite polygon"
    if len(set(ordered)) != len(ordered):
        return None, "the kerf section polygon repeats a vertex"

    exact = [tuple(Fraction(value) for value in point) for point in ordered]
    edges = list(zip(exact, exact[1:] + exact[:1], strict=True))
    for index, (first, second) in enumerate(edges):
        third = exact[(index + 2) % len(exact)]
        if (
            _turn(first, second, third) == 0
            and sum((second[axis] - first[axis]) * (third[axis] - second[axis]) for axis in (0, 1))
            < 0
        ):
            return None, "the kerf section polygon has an overlapping backtracking edge"
        for other in range(index + 2, len(edges)):
            if index == 0 and other == len(edges) - 1:
                continue
            if _segments_meet(first, second, *edges[other]):
                return None, "the kerf section polygon is not simple"

    area = sum(first[0] * second[1] - second[0] * first[1] for first, second in edges)
    if area == 0:
        return None, "the kerf section polygon has no area"
    if area < 0:
        ordered.reverse()
    signs = [
        1 if u1 > u0 else -1
        for (_, u0), (_, u1) in zip(ordered, ordered[1:] + ordered[:1], strict=True)
        if u1 != u0
    ]
    changes = sum(
        first != second for first, second in zip(signs, signs[1:] + signs[:1], strict=True)
    )
    if changes != 2:
        return None, (
            "the kerf section holds more than one material interval across the feed "
            "(hollow, re-entrant or multiple-interval sections are unsupported)"
        )
    return ordered, None


def transitions(points, radius):
    """(advancing-rim engagement transitions, None) or (None, why not).

    ``first_contact_mm``/``entry_complete_mm`` are the least and greatest ``e(u)``,
    ``exit_begins_mm``/``last_contact_mm`` the least and greatest ``x(u)``: each extreme
    lies at a polygon vertex or where ``d/du (m u - q(u)) = 0`` inside a slope-``m`` edge,
    ``u = -m R / sqrt(1 + m^2)``. Edges rising in ``u`` on a counter-clockwise polygon
    bound its far side ``b``; falling edges bound its near side ``a``."""
    if not _finite(radius) or radius <= 0:
        return None, "the blade radius is not positive and finite"
    ordered, why = monotone_section(points)
    if ordered is None:
        return None, why
    umin = min(u for _, u in ordered)
    umax = max(u for _, u in ordered)
    if umin <= -radius or umax >= radius:
        return None, "the kerf section reaches the blade radius across the feed"
    entries, exits = [], []
    for (s0, u0), (s1, u1) in zip(ordered, ordered[1:] + ordered[:1], strict=True):
        if u1 == u0:
            continue
        ds, du = s1 - s0, u1 - u0
        if not math.isfinite(ds) or not math.isfinite(du):
            return None, "the kerf section exceeds the supported arithmetic range"
        norm = math.hypot(ds, du)
        if not math.isfinite(norm):
            return None, "the kerf section exceeds the supported arithmetic range"
        candidates = [(u0, s0), (u1, s1)]
        stationary = -radius * (ds / norm) * (1 if du > 0 else -1)
        if min(u0, u1) < stationary < max(u0, u1):
            fraction = (stationary - u0) / du
            candidates.append((stationary, (1 - fraction) * s0 + fraction * s1))
        # Factoring the radicand preserves the distinction between tangency and a
        # section one representable coordinate inside the radius.
        radicands = [(radius - abs(u)) * (radius + abs(u)) for u, _ in candidates]
        if not all(math.isfinite(value) and value > 0 for value in radicands):
            return None, "the kerf section exceeds the supported arithmetic range"
        values = [
            s - math.sqrt(radicand) for (_, s), radicand in zip(candidates, radicands, strict=True)
        ]
        if not all(math.isfinite(value) for value in values):
            return None, "the kerf section exceeds the supported arithmetic range"
        (exits if u1 > u0 else entries).extend(values)
    if not entries or not exits:
        return None, "the kerf section polygon has no near or far side"
    if max(entries) >= min(exits):
        return None, "the kerf section has no positive established-engagement interval"
    return {
        "transverse_interval_mm": [umin, umax],
        "first_contact_mm": min(entries),
        "entry_complete_mm": max(entries),
        "exit_begins_mm": min(exits),
        "last_contact_mm": max(exits),
    }, None


def engaged_arc(umin, umax, radius):
    """Return one advancing-rim open angular interval, measured from feed.

    The supported established section lies strictly inside the two transverse
    tangencies. Invalid, reversed or zero-width intervals raise ``ValueError``;
    endpoints are never clamped into the blade or moved with an epsilon.
    """
    if not all(_finite(value) for value in (umin, umax, radius)) or not (
        radius > 0 and -radius < umin < umax < radius
    ):
        raise ValueError("the transverse interval must lie strictly inside a positive blade radius")
    return math.asin(umin / radius), math.asin(umax / radius)


def _count(arcs, phase, teeth):
    """Count the union of strict-open arcs, in exact tooth-pitch coordinates."""
    ranges = []
    for start, end in arcs:
        first, last = math.floor(start - phase) + 1, math.ceil(end - phase) - 1
        if first > last:
            continue
        if last - first + 1 >= teeth:
            return teeth
        low = first % teeth
        high = low + last - first
        ranges.append((low, min(high, teeth - 1)))
        if high >= teeth:
            ranges.append((0, high - teeth))
    total, previous = 0, -1
    for low, high in sorted(ranges):
        total += max(0, high - max(low, previous + 1) + 1)
        previous = max(previous, high)
    return total


def _phase_minimum(arcs, teeth):
    events = sorted({endpoint % 1 for arc in arcs for endpoint in arc})
    if not events:
        return 0
    # These are exhaustive phase cells, not a sampled phase grid. Fraction keeps
    # even a cell narrower than one float ULP and its exact midpoint distinct.
    cells = [
        (first + second) / 2
        for first, second in zip(events, events[1:] + [events[0] + 1], strict=True)
    ]
    return min(_count(arcs, phase, teeth) for phase in events + cells)


def min_interior_teeth(arcs, teeth):
    """Return ``(conservative minimum, unresolved numeric tie)`` over tooth phase.

    Arcs are disjoint strict-open, increasing, unwrapped angular intervals within
    one revolution. Adjacent arcs retain their excluded common endpoint. Malformed,
    overlapping or multi-revolution input raises ``ValueError``. Empty input has
    minimum zero. Only uniform spacing with a positive integer count is supported.

    Every folded endpoint event and intervening phase cell is evaluated using exact
    rational arithmetic on the supplied angles and ``math.tau / teeth``. Exact
    coincident events are known strict-boundary cases, not numeric uncertainty.
    Distinct events separated by at most ``TIE_REL`` tooth pitches receive bounded
    endpoint uncertainty; contraction/expansion then bound the possible minimum.
    A differing bound sets the tie flag, including a value just below a threshold.
    With multiple arcs the uncertain range can exceed one tooth; callers must not
    infer an upper bound of ``minimum + 1`` from the boolean alone.
    """
    if not isinstance(teeth, int) or isinstance(teeth, bool) or teeth <= 0:
        raise ValueError("tooth count must be a positive integer")
    try:
        pairs = [_pair(arc) for arc in arcs]
    except TypeError as error:
        raise ValueError("engaged arcs must be finite endpoint pairs") from error
    if any(pair is None for pair in pairs):
        raise ValueError("engaged arcs must be finite endpoint pairs")
    if not pairs:
        return 0, False
    exact = sorted((Fraction(start), Fraction(end)) for start, end in pairs)
    if any(start >= end for start, end in exact):
        raise ValueError("engaged arcs must have strictly increasing endpoints")
    if any(second[0] < first[1] for first, second in zip(exact, exact[1:], strict=False)):
        raise ValueError("engaged arcs must not overlap")
    revolution = Fraction(math.tau)
    origin = exact[0][0]
    if exact[-1][1] - origin > revolution:
        raise ValueError("engaged arcs must lie within one unwrapped revolution")
    pitch = revolution / teeth
    scaled = [((start - origin) / pitch, (end - origin) / pitch) for start, end in exact]
    events = sorted({endpoint % 1 for arc in scaled for endpoint in arc})
    tolerance = Fraction(TIE_REL)
    uncertain = set()
    for first, second in zip(events, events[1:] + [events[0] + 1], strict=True):
        if 0 < second - first <= tolerance:
            uncertain.update((first % 1, second % 1))
    if not uncertain:
        return _phase_minimum(scaled, teeth), False
    contracted, expanded = [], []
    for start, end in scaled:
        start_error = tolerance if start % 1 in uncertain else 0
        end_error = tolerance if end % 1 in uncertain else 0
        if start + start_error < end - end_error:
            contracted.append((start + start_error, end - end_error))
        expanded.append((start - start_error, end + end_error))
    lower = _phase_minimum(contracted, teeth)
    upper = _phase_minimum(expanded, teeth)
    return lower, lower != upper


def single_arc_teeth(angle, teeth):
    """Conservative ``max(0, ceil(angle / pitch) - 1)``; use the full API for ties."""
    if _finite(angle) and angle == 0:
        # Still validate the installed tooth count.
        return min_interior_teeth([], teeth)[0]
    return min_interior_teeth([(0, angle)], teeth)[0]


def mounted_midplane(blade_side, plane_z, paper, body, offset):
    """The cutting-band-midplane DRO setting after a stopped body-side touch.

    Lower body side on a +Z plane ``E`` through paper ``p``: ``E + p + B/2 + C``; upper
    side on a -Z plane: ``E - p - B/2 + C``. Body thickness ``B``, never the kerf or the
    blade radius; ``C`` the signed kerf-centre offset from the body midplane."""
    if blade_side == "minus_z":
        return plane_z + paper + body / 2 + offset
    if blade_side == "plus_z":
        return plane_z - paper - body / 2 + offset
    raise ValueError(f"blade_side {blade_side!r} is not minus_z or plus_z")
