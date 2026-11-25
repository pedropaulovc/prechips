"""Tools drawn to scale in the setup pictures, shared by the templates.

A round tool seen from the side (end mill, drill, tap, tap guide, rod) is
drawn at its diameter × the picture's px per mm, from its tip up to where the
picture stops it: a drill or a guide ground to its point, any other square
end drawn as the near half of its end face (the cue that it is round), and a
tool drawn short ending in a break line. The tap's stack (tap, T-handle
wrench, the spring tap guide's point and body) is drawn by ``_tap_stack``.
"""

from __future__ import annotations

import math

from prechips.cad import CadError
from prechips.cad_diagrams import Element, _el, _rect
from prechips.jig_diagrams import _param

# A round tool's or rod's square end seen from the side is drawn as the near
# half of its end face: an ellipse this fraction of the diameter deep (owner
# 2026-11-25: "some indication that end mill is cylindrical when looking from
# side ; can be something simple like adding a round bottom"); shallow, so a
# square end mill does not read as a ball nose.
_ROUND_RISE = 0.12
# Tools drawn short end in a break line; these lengths are the picture's,
# not the tools': a drill or the tap guide above the part, px.
_SHORT = 60.0
_BREAK = 3.0  # px: a break line's teeth
# The tap's T-handle wrench (no size on record), schematic, px: its gap above
# the face and its thickness.
_WRENCH_GAP = 50.0
_WRENCH = 9.0
# The tap guide's point drawn out of its body at least this long, px; longer
# when its 60° cone at the point's diameter needs it.
_GUIDE_POINT = 20.0
_DRILL_POINT_DEG = 118.0  # a jobber drill's point
_GUIDE_POINT_DEG = 60.0  # the tap guide's point, as it seats in a centre hole


def _zigzag(x0: float, y0: float, x1: float, y1: float) -> list[tuple[float, float]]:
    """A break line's teeth from (``x0``, ``y0``) to (``x1``, ``y1``), ends
    excluded: where a tool or rod drawn to scale is cut off short."""
    length = math.hypot(x1 - x0, y1 - y0)
    teeth = max(2, round(length / 8))
    # Teeth stand off the line, square to it: to the left of the way it is
    # drawn, so a tool's top drawn left to right has them standing up.
    nx, ny = (y1 - y0) / length, (x0 - x1) / length
    points = []
    for k in range(1, 2 * teeth):
        t = k / (2 * teeth)
        lift = _BREAK if k % 2 else 0.0
        points.append((x0 + (x1 - x0) * t + nx * lift, y0 + (y1 - y0) * t + ny * lift))
    return points


def _path(points: list[tuple[float, float]], arc: str = "") -> Element:
    """A closed outline through ``points``; ``arc`` (an SVG arc command from
    the last point) closes it along a curve instead of a straight edge."""
    line = "L".join(f"{x:.1f} {y:.1f}" for x, y in points)
    return _el("path", d=f"M{line}{arc}Z")


def _end_arc(x: float, y: float, half: float) -> str:
    """The arc to (``x``, ``y``) of a round bar's square end seen from the
    side: the near half of its end face, a shallow ellipse ``half`` (the
    radius) by _ROUND_RISE of the diameter."""
    rise = _ROUND_RISE * 2 * half
    return f"A{half:.1f} {rise:.1f} 0 0 0 {x:.1f} {y:.1f}"


def _tool(
    cx: float,
    width: float,
    tip: float,
    top: float,
    point_deg: float | None = None,
    broken: bool = False,
) -> Element:
    """A round tool seen from the side, ``width`` wide (its diameter to the
    picture's scale), from its ``tip`` up to ``top`` (page y): ground to an
    included ``point_deg``, or square ended, its end drawn as the near half
    of the end face (the cue that it is round) with its lowest point at
    ``tip``, so its length is true; ``broken`` ends it in a break line where
    it is drawn short."""
    left, right = cx - width / 2, cx + width / 2
    # The break line drawn left to right, its teeth standing up off the top,
    # then walked back right to left as the outline goes.
    breaks = list(reversed(_zigzag(left, top, right, top))) if broken else []
    if point_deg is not None:
        point = width / 2 / math.tan(math.radians(point_deg / 2))
        if tip - point < top:
            raise CadError(
                f"a {point_deg:g}° point {point:.1f} px long does not fit the "
                f"{tip - top:.1f} px the tool is drawn"
            )
        outline = [(left, top), (left, tip - point), (cx, tip), (right, tip - point)]
        return _path([*outline, (right, top), *breaks])
    corner = tip - _ROUND_RISE * width
    if corner < top:
        raise CadError(
            f"a round end {_ROUND_RISE * width:.1f} px deep does not fit the "
            f"{tip - top:.1f} px the tool is drawn"
        )
    # Up the right side, across the top, down the left, then the arc under
    # it back to the right.
    outline = [(right, corner), (right, top), *breaks, (left, top), (left, corner)]
    return _path(outline, _end_arc(right, corner, width / 2))


def _guide_point(parameters: dict, s: float) -> float:
    """The tap guide's point drawn out of its body, px: its whole 60° cone
    at the point's diameter, and at least _GUIDE_POINT."""
    cone = _param(parameters, "tap_guide_point_dia_mm") * s / 2
    return max(_GUIDE_POINT, cone / math.tan(math.radians(_GUIDE_POINT_DEG / 2)))


def _tap_reach(parameters: dict, s: float) -> float:
    """How far the tap's stack stands above the face it taps, px: the
    wrench's gap and thickness, the guide's point and its body drawn
    short."""
    return _WRENCH_GAP + _WRENCH + _guide_point(parameters, s) + _SHORT


def _tap_stack(
    cx: float,
    thread: float,
    tip: float,
    face: float,
    wrench: float,
    parameters: dict,
    s: float,
) -> list[Element]:
    """The tap by hand under the spring tap guide, on the axis ``cx``: the
    tap ``thread`` wide (its major diameter to scale) from its ``tip`` up to
    its T-handle wrench (``wrench`` px across, no size on record) a little
    above the ``face``; the guide's point (process.tap_guide_point_dia_mm) in
    the wrench's centre hole and its body (process.tap_guide_dia_mm), both
    at their diameters × ``s``, the body drawn short. All of it turns or
    travels with the tap, so all of it is the tool."""
    top = face - _WRENCH_GAP
    seat = top - _WRENCH
    body = seat - _guide_point(parameters, s)
    return [
        _tool(cx, thread, tip, top),
        _rect(cx - wrench / 2, seat, wrench, _WRENCH),
        _tool(
            cx,
            _param(parameters, "tap_guide_point_dia_mm") * s,
            seat,
            body,
            _GUIDE_POINT_DEG,
        ),
        _tool(
            cx,
            _param(parameters, "tap_guide_dia_mm") * s,
            body,
            body - _SHORT,
            broken=True,
        ),
    ]
