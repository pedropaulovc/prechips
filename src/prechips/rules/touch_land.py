"""Native circular-loop certificates for a usable faced-plane paper-touch square.

A search is only a way to find a witness, never proof by sampling: every accepted
square is checked analytically against the outer circle, every original hole,
and every later cut. Unsupported topology and unsuccessful searches stay unknown.
"""

import math

from .zero_recipe import LENGTH_TOLERANCE_MM, TOUCH_LAND_MM

_ANGLES = 64
_AREA_REL = 1e-6
_AREA_ABS = 1e-6
_NORMAL_TOL = 1e-7


def _finite(value):
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return False
    try:
        return math.isfinite(value)
    except OverflowError:
        return False


def _vector(value):
    return isinstance(value, list) and len(value) == 3 and all(_finite(v) for v in value)


def _normal(value):
    return (
        _vector(value)
        and abs(math.hypot(*value) - 1) <= _NORMAL_TOL
        and math.hypot(*value[:2]) <= _NORMAL_TOL
    )


def _circle(loop, z, normal, debt):
    if not isinstance(loop, dict) or loop.get("kind") != "circle":
        return None
    centre, axis = loop.get("centre_mm"), loop.get("normal")
    radius, error = loop.get("radius_mm"), loop.get("error_mm")
    if not (
        _vector(centre)
        and _normal(axis)
        and abs(abs(sum(a * b for a, b in zip(axis, normal, strict=True))) - 1) <= _NORMAL_TOL
        and _finite(radius)
        and radius > 0
        and _finite(error)
        and error >= 0
        and abs(centre[2] - z) <= error + debt + LENGTH_TOLERANCE_MM
    ):
        return None
    return centre, radius, error + debt


def _square_distance(centre, point, half):
    """Exact distance from a circle centre to an axis-aligned square."""
    return math.hypot(*(max(abs(centre[i] - point[i]) - half, 0) for i in (0, 1)))


def _height_debt(point, normal, anchor):
    """Conservative height departure across the entire certified square."""
    if not (_vector(point) and _normal(normal)):
        return math.inf
    slope = math.hypot(*normal[:2]) / abs(normal[2])
    if anchor is None and slope == 0:
        return 0.0  # An exactly horizontal plane's known Z needs no lateral anchor.
    if not _vector(anchor):
        return math.inf
    if slope == 0:
        return abs(anchor[2] - point[2])
    half = TOUCH_LAND_MM / 2
    distance = max(
        math.hypot(point[0] + dx - anchor[0], point[1] + dy - anchor[1])
        for dx in (-half, half)
        for dy in (-half, half)
    )
    return abs(anchor[2] - point[2]) + distance * slope


def certify(topology, exclusions, *, grid_mm=None, reference_z_mm=None, touch_plane=None):
    """Return a 0.5 mm square witness, or None without an adequate native fact.

    Circles must reproduce the native area, with every inner wire strictly inside
    the outer and disjoint from the others. Straight polygons are serialized for
    provenance but do not borrow this circular proof. The deterministic search
    visits 64 increasing angles, starting at +X, at the midpoint of a conservative
    concentric ring enclosing all holes and exclusions. Each square must also
    stay within the length tolerance of the native and carried-source heights.
    The first certified square wins. Search failure does not prove absence of material.
    """
    if not isinstance(topology, dict) or topology.get("kind") != "Plane":
        return None
    normal, z = topology.get("normal"), topology.get("z_mm")
    area, debt = topology.get("area_mm2"), topology.get("error_mm")
    holes = topology.get("inner")
    if not (
        _normal(normal)
        and _finite(z)
        and _finite(area)
        and area > 0
        and _finite(debt)
        and debt >= 0
        and isinstance(holes, list)
        and isinstance(exclusions, list)
    ):
        return None
    if grid_mm is not None and not (_finite(grid_mm) and grid_mm > 0):
        return None
    reference = z if reference_z_mm is None else reference_z_mm
    if not _finite(reference):
        return None
    if touch_plane is not None and not (
        isinstance(touch_plane, dict)
        and _normal(touch_plane.get("normal"))
        and _vector(touch_plane.get("centre_mm"))
        and _finite(touch_plane.get("reference_z_mm", touch_plane["centre_mm"][2]))
    ):
        return None
    outer = _circle(topology.get("outer"), z, normal, debt)
    inner = [_circle(hole, z, normal, debt) for hole in holes]
    if outer is None or any(hole is None for hole in inner):
        return None
    centre, radius, outer_error = outer
    for i, (point, r, error) in enumerate(inner):
        distance = math.dist(point[:2], centre[:2])
        if distance + r + error >= radius - outer_error:
            return None
        if any(
            math.dist(point[:2], other[:2]) <= r + other_r + error + other_error
            for other, other_r, other_error in inner[:i]
        ):
            return None
    reconstructed = math.pi * (radius * radius - sum(r * r for _, r, _ in inner))
    if not _finite(reconstructed) or reconstructed <= 0:
        return None
    area_debt = 2 * math.pi * (
        radius * outer_error + sum(r * error for _, r, error in inner)
    ) + math.pi * (outer_error * outer_error + sum(error * error for _, _, error in inner))
    if not _finite(area_debt) or abs(reconstructed - area) > (
        _AREA_ABS + _AREA_REL * max(area, 1) + area_debt
    ):
        return None
    forbidden = list(inner)
    for exclusion in exclusions:
        if not isinstance(exclusion, dict):
            return None
        point = exclusion.get("centre_mm")
        r, error = exclusion.get("radius_mm"), exclusion.get("error_mm")
        if not (_vector(point) and _finite(r) and r > 0 and _finite(error) and error >= 0):
            return None
        # A footprint is a column: its own original Z is not a contact-height claim.
        forbidden.append((point, r, error))
    reach = max(
        (math.dist(point[:2], centre[:2]) + r + error for point, r, error in forbidden),
        default=0.0,
    )
    outside = radius - outer_error - LENGTH_TOLERANCE_MM
    inside = reach + LENGTH_TOLERANCE_MM
    if outside <= inside:
        return None
    at, half = (inside + outside) / 2, TOUCH_LAND_MM / 2
    for candidate in range(_ANGLES):
        angle = 2 * math.pi * candidate / _ANGLES
        point = [centre[0] + at * math.cos(angle), centre[1] + at * math.sin(angle), z]
        if grid_mm is not None:
            from .coordinates import dro_point

            decimals = next((d for d in range(9) if abs(round(grid_mm, d) - grid_mm) <= 1e-12), 9)
            point[:2] = dro_point(point, (grid_mm, decimals))[:2]
        if any(
            math.hypot(point[0] + dx - centre[0], point[1] + dy - centre[1]) > outside
            for dx in (-half, half)
            for dy in (-half, half)
        ):
            continue
        if any(
            _square_distance(point, other, half) < r + error + LENGTH_TOLERANCE_MM
            for other, r, error in forbidden
        ):
            continue
        height_debt = abs(z - reference) + _height_debt(point, normal, topology.get("centre_mm"))
        if touch_plane is not None:
            # The physical source need not equal the native nominal. It must,
            # however, bound the standing height actually printed for the group.
            source_point = [
                *point[:2],
                touch_plane.get("reference_z_mm", touch_plane["centre_mm"][2]),
            ]
            height_debt = max(
                height_debt,
                _height_debt(source_point, touch_plane["normal"], touch_plane["centre_mm"]),
            )
        if not _finite(height_debt) or height_debt > LENGTH_TOLERANCE_MM:
            continue
        return {
            "centre_mm": point,
            "width_mm": TOUCH_LAND_MM,
            "candidate": candidate,
            "search": "64 fixed angles at conservative ring mid-radius; first certified square",
            "area_mm2": reconstructed,
            "keep_off_radius_mm": reach,
            "height_debt_mm": height_debt,
        }
    return None
