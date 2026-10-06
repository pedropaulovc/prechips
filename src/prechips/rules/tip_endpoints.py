"""Hole tip endpoints and operation-local entry surfaces (PLAN §4.1)."""

from __future__ import annotations

import math

from prechips.measurements import nominal_angle_deg

from ..findings import Finding
from .resolution import UNKNOWN, length_mm, number, resolve, uncertain

FACING = {"face", "rough_face", "finish_face"}
POCKETING = {"pocket", "rough_pocket", "finish_pocket"}
HOLE_OPS = {"spot", "drill", "ream", "tap", "counterbore", "bore"}


def mapping(value):
    return value if isinstance(value, dict) else {}


def records(value):
    return value if isinstance(value, list) else []


def drill_point_mm(diameter_mm, point_angle_deg):
    """Axial cone length: D / (2 tan(included angle / 2))."""
    if not (
        number(diameter_mm)
        and diameter_mm > 0
        and number(point_angle_deg)
        and 0 < point_angle_deg < 180
    ):
        return UNKNOWN
    return diameter_mm / (2 * math.tan(math.radians(point_angle_deg / 2)))


def _subtract(*values):
    return values[0] - sum(values[1:]) if all(number(v) for v in values) else UNKNOWN


def _operative(row, grid):
    """Add the endpoint as the DRO shows it, every Z on the setup's grid (``dro_z``):
    ``dro_entry_z`` is the entry surface (the ``dro_to_z`` of the op that faced it),
    ``dro_exit_face`` the exit face. The tip keeps its analytical distance below the
    surface it is worked from (the entry; a through hole's exit face), then rounds up,
    never deeper than worked. ``dro_depth_mm`` is the depth that leaves below the entry;
    ``dro_exit_mm`` the break-through it leaves below the nominal exit face, the lower."""
    from .coordinates import dro_z

    through = row["exit_face"] != "not_applicable"
    row["dro_entry_z"] = dro_z(row["entry_z"], grid)
    if through:
        row["dro_exit_face"] = dro_z(row["exit_face"], grid)
    surface, worked = ("dro_exit_face", "exit_face") if through else ("dro_entry_z", "entry_z")
    shift = _subtract(row[surface], row[worked])
    tip = row["tip_z"] + shift if number(row["tip_z"]) and number(shift) else UNKNOWN
    row["dro_tip_z"] = dro_z(tip, grid)
    if through:
        lead = row.get("lead_mm", row.get("point_mm", UNKNOWN))
        row["dro_exit_mm"] = _subtract(row["exit_face"], lead, row["dro_tip_z"])
    elif "depth_mm" in row:
        row["dro_depth_mm"] = _subtract(row["depth_mm"], _subtract(row["dro_tip_z"], tip))


def _feature_depth_mm(feature, field, units):
    """An upper feature-depth limit uses the model's units, unlike depth_mm."""
    value = feature.get(field, UNKNOWN)
    if isinstance(value, list):
        value = value[1] if len(value) == 2 else UNKNOWN
    scale = {"mm": 1.0, "in": 25.4}.get(units)
    return value * scale if number(value) and scale is not None else UNKNOWN


def hole_depth_mm(op, feature, units):
    """Operation depth in machine mm; taps may use their feature's upper depth."""
    if "depth_mm" in op:
        value = op["depth_mm"]
        return value if number(value) else UNKNOWN
    if op.get("do") == "tap":
        field = "thread_depth" if "thread_depth" in feature else "depth"
        return _feature_depth_mm(feature, field, units)
    return UNKNOWN


def _covers(cut, target):
    """Only explicit same-frame footprints can advance another entry surface."""
    bounds = mapping(cut.get("bounds"))
    if not bounds or cut.get("frame", "model") != target.get("frame", "model"):
        return False
    at = target.get("at")
    other = mapping(target.get("bounds"))
    for i, axis in enumerate(("x", "y", "z")):
        if axis not in bounds:
            continue
        band = bounds[axis]
        if not isinstance(band, list) or len(band) != 2 or not all(number(v) for v in band):
            return False
        if isinstance(at, list) and len(at) == 3:
            if not number(at[i]) or not band[0] <= at[i] <= band[1]:
                return False
        elif axis in other:
            interval = other[axis]
            if not all(number(v) for v in interval) or max(band[0], interval[0]) >= min(
                band[1], interval[1]
            ):
                return False
        elif mapping(target.get("plane")).get("axis") == axis:
            value = mapping(target.get("plane")).get("value", UNKNOWN)
            if not number(value) or not band[0] <= value <= band[1]:
                return False
        else:
            return False
    return True


def stock_states(setup, features=None):
    """Yield (op, before, after); profiles never move the touched top surface.

    Entry values are separate from the setup's touched top. Explicit pocket/face
    footprints may advance entry planes inside the cut, not adjoining strips.
    Local thickness is authored at the eventual hole entry, not raw stock height.
    """
    features = mapping(features)
    stock = mapping(setup.get("stock_state"))
    top = stock.get("top_z", UNKNOWN)
    entries = dict(mapping(stock.get("entry_z")))
    origins = {name: f"{setup['id']} stock_state.entry_z.{name}" for name in entries}
    top_from = f"{setup['id']} stock_state.top_z"
    for op in setup.get("ops", []):
        before = {
            "top_z": top,
            "entry_z": dict(entries),
            "entry_from": dict(origins),
            "top_from": top_from,
        }
        if "to_z" in op and op.get("do") in FACING | POCKETING:
            name = op.get("feature")
            cut = mapping(features.get(name))
            for target in entries:
                if target == name or _covers(cut, mapping(features.get(target))):
                    entries[target] = op["to_z"]
                    origins[target] = f"{setup['id']} op {op['op']} to_z"
            if op.get("do") in FACING and (
                stock.get("top_feature") is None or name == stock["top_feature"]
            ):
                top = op["to_z"]
                top_from = f"{setup['id']} op {op['op']} to_z"
        after = {
            "top_z": top,
            "entry_z": dict(entries),
            "entry_from": dict(origins),
            "top_from": top_from,
        }
        yield op, before, after


def evaluate(bundle):
    from .coordinates import dro_grid

    features = bundle.feature_definitions
    endpoints = {name: [] for name in features}
    unresolved = set()
    errors = set()
    negative_exit = set()
    for setup in bundle.plan["setups"]:
        grid = dro_grid(bundle, setup)
        for op, before, _ in stock_states(setup, features):
            name = op.get("feature")
            if name not in features or op.get("do") not in HOLE_OPS:
                continue
            feature = features[name]
            if feature.get("kind") not in {"hole", "counterbore", "thread", "threaded_hole"}:
                continue
            entry = before["entry_z"].get(name, before["top_z"])
            row = {
                "setup": setup["id"],
                "op": op["op"],
                "feature": name,
                "entry_z": entry,
                "entry_from": before["entry_from"].get(name, before["top_from"]),
            }
            tool = resolve(bundle, "tools", op.get("tool")) or {}
            action = op["do"]
            point = drill_point_mm(
                length_mm(tool, "dia"),
                nominal_angle_deg(tool, "point_angle"),
            )
            if action == "spot":
                depth = hole_depth_mm(op, feature, bundle.features.get("units"))
                row.update(
                    depth_mm=depth,
                    point_mm=point,
                    exit_face="not_applicable",
                    tip_z=_subtract(entry, depth),
                )
            elif action == "tap":
                depth = hole_depth_mm(op, feature, bundle.features.get("units"))
                flute = length_mm(tool, "flute_len")
                row.update(
                    depth_mm=depth,
                    flute_len_mm=flute,
                    tip_z=_subtract(entry, depth),
                    exit_face="not_applicable",
                )
                if number(flute) and number(depth) and not uncertain(tool) and flute < depth:
                    errors.add(name)
                elif not (number(flute) and number(depth)):
                    unresolved.add(name)
            elif feature.get("thru") is True:
                thickness = mapping(mapping(setup.get("stock_state")).get("local_thickness")).get(
                    name, UNKNOWN
                )
                lead = (
                    length_mm(tool, "lead")
                    if action == "ream"
                    else point
                    if action == "drill"
                    else 0
                )
                exit_face = _subtract(entry, thickness)
                allowance = op.get("exit_mm", UNKNOWN)
                negative = number(allowance) and allowance < 0
                if negative:
                    # A negative allowance stops short of breaking through; no stop is offered.
                    negative_exit.add(name)
                row.update(
                    local_thickness=thickness,
                    exit_face=exit_face,
                    exit_mm=allowance,
                    tip_z=UNKNOWN if negative else _subtract(exit_face, lead, allowance),
                )
                row["lead_mm" if action == "ream" else "point_mm"] = lead
            else:
                depth = hole_depth_mm(op, feature, bundle.features.get("units"))
                lead = (
                    length_mm(tool, "lead")
                    if action == "ream"
                    else point
                    if action == "drill"
                    else 0
                )
                limit = _feature_depth_mm(feature, "depth", bundle.features.get("units"))
                total = depth + lead if number(depth) and number(lead) else UNKNOWN
                row.update(
                    depth_mm=depth,
                    depth_limit_mm=limit,
                    total_depth_mm=total,
                    exit_face="not_applicable",
                    tip_z=_subtract(entry, total),
                )
                row["lead_mm" if action == "ream" else "point_mm"] = lead
                if feature.get("thru") == UNKNOWN or not (number(total) and number(limit)):
                    unresolved.add(name)
                elif total > limit and not uncertain(tool):
                    errors.add(name)
            if row.get("tip_z") == UNKNOWN or not tool or uncertain(tool):
                unresolved.add(name)
            _operative(row, grid)
            endpoints[name].append(row)
    result = []
    for name, feature in features.items():
        rows = endpoints[name]
        if feature.get("kind") not in {"hole", "counterbore", "thread", "threaded_hole"}:
            status, sentence = "not_applicable", "Not a hole; no tip endpoint applies."
        elif name in errors or name in negative_exit:
            sentence = " ".join(
                text
                for flagged, text in (
                    (negative_exit, "A through exit allowance is negative; exit_mm must be >= 0."),
                    (errors, "The blind tip or tap flute length exceeds the declared depth guard."),
                )
                if name in flagged
            )
            status = "error"
        elif not rows or name in unresolved:
            status, sentence = (
                "unknown",
                "Hole endpoints need the missing or unverified entry, "
                "tool geometry or depth inputs.",
            )
        else:
            status, sentence = (
                "pass",
                "Hole tip endpoints and blind-depth guards are computed from the advanced "
                "local entry surfaces.",
            )
        result.append(
            Finding(
                "blind_depth",
                name,
                status,
                {"kind": feature.get("kind", UNKNOWN), "endpoints": rows},
                [
                    "PLAN.md §4.1 tip endpoints",
                    "features manifest hole geometry",
                    "plan stock_state and operation depth/exit",
                    "inventory selected tool geometry",
                ],
                sentence,
            )
        )
    return result
