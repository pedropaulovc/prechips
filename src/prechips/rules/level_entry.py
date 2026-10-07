"""How a milled path enters each depth level and returns for the next.

For every mill op the coordinates rule prints a cutter path for (arc and join tables,
outlines, raster passes), this walks the path pieces in the order the setup sheet prints
them and records, per piece the cutter has to go down at:

* where it goes down: a cutter wholly outside the stock the setup receives (the kernel's
  setup-frame ``stock_bbox_mm``, by its as-is face tolerance) goes down in air; anything
  else plunges into material, since nothing else proves the spot clear;
* from where: level 1 from the op's DRO start Z, level ``k`` from level ``k-1``'s Z, which
  the same path already cut at that spot (each level runs the whole path);
* how it gets back: a path that ends where it starts goes straight down to the next level;
  otherwise the cutter raises to the op's raise Z (``approach_mm`` above the current top,
  on the DRO grid, as a raster's lift) before moving to the next entry. That height is
  claimed above the stock only when the kernel's stock box proves it.

An op that plunges and has no known plunge feed (``speeds_feeds.plunge_row``) is debt, as
is a return without a known raise Z or with one the stock box puts below the stock top.
Rotary-table and chain-drill tables are not end-mill paths and are skipped.
"""

from __future__ import annotations

import math

from .resolution import UNKNOWN, length_mm, number, resolve
from .speeds_feeds import plunge_row
from .tip_endpoints import mapping

# The kernel's as-is face tolerance (its STOCK_TOL): a cutter clears the stock box only
# past it by this much, so box rounding never makes a claim.
STOCK_TOL_MM = 1e-3
_PATH_METHODS = {"stairs", "chords"}


def stock_box(bundle, setup):
    """The setup-entry stock box (mm, setup frame) the kernel modelled, else None."""
    kernel = getattr(bundle, "kernel", None)
    if not isinstance(kernel, dict) or kernel.get("status") != "ok":
        return None
    box = mapping(mapping(kernel.get("setups")).get(setup["id"])).get("stock_bbox_mm")
    if not (isinstance(box, list) and len(box) == 6 and all(number(v) for v in box)):
        return None
    return box


def in_air(box, point, radius, scale):
    """Whether a cutter of ``radius`` mm centred at ``point`` (plan units) stands wholly
    outside ``box`` in X or Y by the kernel tolerance; False when anything is unknown."""
    if box is None or not number(radius) or not scale:
        return False
    if not (isinstance(point, list) and len(point) >= 2 and all(number(v) for v in point[:2])):
        return False
    return any(
        point[axis] * scale + radius <= box[axis] - STOCK_TOL_MM
        or point[axis] * scale - radius >= box[axis + 3] + STOCK_TOL_MM
        for axis in range(2)
    )


def _xy(point):
    if isinstance(point, dict):
        return [point.get("x"), point.get("y")]
    return list(point[:2]) if isinstance(point, list) else [UNKNOWN, UNKNOWN]


def _pieces(numbers):
    """``{op: [(points, raster)]}`` in the order the setup sheet prints each op's tables:
    rough before finish, then the proven cut sequence, then listed order; outlines and
    rasters after its arc and join tables."""
    stages = {"rough": 0, "finish": 1}
    found = {}
    tables = [
        *(("arc", t) for t in numbers.get("arc_table") or [] if t.get("method") in _PATH_METHODS),
        *(("line", t) for t in numbers.get("line_table") or []),
    ]
    skipped = {
        str(t.get("op"))
        for t in numbers.get("arc_table") or []
        if t.get("method") not in _PATH_METHODS
    }
    for kind, table in tables:
        points = (
            [row.get("dro_xy") for row in table.get("rows", [])]
            if kind == "arc"
            else list(table.get("dro_xy") or [])
        )
        sequence = table.get("sequence")
        rank = (
            stages.get(table.get("stage"), 2),
            sequence if isinstance(sequence, int) else -1,
        )
        found.setdefault(str(table.get("op")), []).append((rank, points, False))
    arc_ops = {str(t.get("op")) for t in numbers.get("arc_table") or []}
    for profile in numbers.get("profiles") or []:
        op = str(profile.get("op"))
        points = profile.get("cutter_centre")
        if op in arc_ops or not isinstance(points, list) or not points:
            continue
        rank = (3, -1)
        if isinstance(profile.get("raster"), dict):
            for piece in points:
                found.setdefault(op, []).append((rank, [_xy(p) for p in piece], True))
        else:
            found.setdefault(op, []).append((rank, [_xy(p) for p in points], False))
    return {
        op: [(points, raster) for _, points, raster in sorted(pieces, key=lambda p: p[0])]
        for op, pieces in found.items()
        if op not in skipped
    }


def _same(a, b, tol):
    return all(number(v) for v in (*a[:2], *b[:2])) and math.dist(a[:2], b[:2]) <= tol


def level_paths(bundle, setup, numbers, states, grid, units, dro_z):
    """``(records, debts)``: one record per path op (see the module docstring)."""
    scale = {"mm": 1.0, "in": 25.4}.get(units)
    box = stock_box(bundle, setup)
    tolerance = grid[0] / 2
    entries = {str(e.get("op")): e for e in numbers.get("operations") or []}
    before = {str(op.get("op")): (op, b) for op, b, _ in states}
    profiles = {}
    for profile in numbers.get("profiles") or []:
        profiles.setdefault(str(profile.get("op")), profile)
    records, debts = [], []
    for op_id, pieces in _pieces(numbers).items():
        op, prior = before.get(op_id, ({}, {}))
        entry = entries.get(op_id, {})
        profile = profiles.get(op_id, {})
        levels = mapping(entry.get("z_levels"))
        depths = levels.get("levels")
        if not isinstance(depths, list):
            depths = [entry.get("dro_to_z", dro_z(op.get("to_z", UNKNOWN), grid))]
        start = levels.get("dro_start_z") if levels else None
        if start is None:
            start = dro_z(profile.get("entry_z", prior.get("top_z", UNKNOWN)), grid)
        radius = length_mm(resolve(bundle, "tools", op.get("tool")) or {}, "dia")
        radius = radius / 2 if number(radius) else UNKNOWN
        raster = any(is_raster for _, is_raster in pieces)
        downs, last = [], None
        for points, is_raster in pieces:
            if not points:
                continue
            first = points[0]
            if is_raster or last is None or not _same(first, last, tolerance):
                downs.append(
                    {"xy": first, "air": in_air(box, first, radius, scale), "pass": is_raster}
                )
            last = points[-1]
        if not downs:
            continue
        first_xy = downs[0]["xy"]
        closed = (
            not raster and len(downs) == 1 and last is not None and _same(first_xy, last, tolerance)
        )
        record = {
            "op": op.get("op", op_id),
            "levels": depths,
            "from_z": start,
            "entries": downs,
            "raster": raster,
            "closed": closed,
        }
        # A return to an entry: between levels of an open path, between pieces, and
        # after every raster pass.
        returns = raster or len(downs) > 1 or (len(depths) > 1 and not closed)
        if returns:
            approach, top = op.get("approach_mm", UNKNOWN), prior.get("top_z", UNKNOWN)
            raised = (
                dro_z(top + approach / scale, grid)
                if scale and number(approach) and number(top)
                else UNKNOWN
            )
            record["raise_z"] = raised
            if not number(raised):
                record["raise_clear"] = UNKNOWN
                if not raster:  # a raster's unknown lift is already its own debt
                    debts.append(
                        f"op {record['op']} returns to its entry but its raise Z is unknown: "
                        "it needs approach_mm above a known top"
                    )
            elif box is None:
                record["raise_clear"] = UNKNOWN
            else:
                record["raise_clear"] = raised * scale >= box[5] + STOCK_TOL_MM
                if not record["raise_clear"]:
                    debts.append(
                        f"op {record['op']} returns to its entry at Z {raised:g}, not above "
                        "the stock it receives"
                    )
        if any(not down["air"] for down in downs):
            feed, _, why = plunge_row(bundle, op)
            record["plunge_mm_rev"] = feed
            if not number(feed):
                record["plunge_reason"] = why
                debts.append(
                    f"op {record['op']} plunges into the stock but its plunge feed is "
                    f"unknown: {why}"
                )
        records.append(record)
    return records, debts
