"""Hole tip endpoints and operation-local entry surfaces (PLAN §4.1)."""

from __future__ import annotations

import math
import re

from prechips.measurements import nominal_angle_deg

from ..findings import Finding
from .resolution import UNKNOWN, length_mm, number, resolve, uncertain

FACING = {"face", "rough_face", "finish_face"}
POCKETING = {"pocket", "rough_pocket", "finish_pocket"}
HOLE_OPS = {"spot", "drill", "ream", "tap", "counterbore", "bore"}
# Plan units of float residue within which two authored Zs are one surface.
SAME_Z = 1e-9


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


def _operative(row, bundle, setup, face):
    """Add the endpoint as the DRO shows it, every Z on the setup's grid (``dro_z``):
    ``dro_entry_z`` is the entry surface ``face`` as its producer cut it
    (:func:`operative_z`), ``dro_exit_face`` the exit face. The tip keeps its analytical
    distance below the surface it is worked from (the entry; a through hole's exit face),
    then rounds up, never deeper than worked. ``dro_depth_mm`` is the depth that leaves
    below the entry, held to ``depth_floor_mm`` (unknown unless a band end is authored);
    ``dro_exit_mm`` the break-through it leaves below the nominal exit face, the lower."""
    from .coordinates import dro_grid, dro_z

    grid = dro_grid(bundle, setup)
    through = row["exit_face"] != "not_applicable"
    row["dro_entry_z"] = operative_z(bundle, setup, row["entry_z"], face, source=row["entry_from"])
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
        row.setdefault("depth_floor_mm", UNKNOWN)


def _feature_depth_mm(feature, field, units, end=1):
    """A feature-depth band end (upper by default) uses the model's units, unlike
    depth_mm; a bare number is an upper limit only, so its lower end is unknown."""
    value = feature.get(field, UNKNOWN)
    if isinstance(value, list):
        value = value[end] if len(value) == 2 else UNKNOWN
    elif end == 0:
        value = UNKNOWN
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


def _covers(cut, target, whole=False):
    """Only explicit same-frame footprints can advance another entry surface; ``whole``
    asks that ``target``'s whole footprint (:func:`_footprint`) lie inside them, not
    merely overlap them or hold its ``at`` point."""
    bounds = mapping(cut.get("bounds"))
    if not bounds or cut.get("frame", "model") != target.get("frame", "model"):
        return False
    at = target.get("at")
    other = _footprint(target) if whole else mapping(target.get("bounds"))
    for i, axis in enumerate(("x", "y", "z")):
        if axis not in bounds:
            continue
        band = bounds[axis]
        if not isinstance(band, list) or len(band) != 2 or not all(number(v) for v in band):
            return False
        if isinstance(at, list) and len(at) == 3 and not whole:
            if not number(at[i]) or not band[0] <= at[i] <= band[1]:
                return False
        elif axis in other:
            interval = other[axis]
            if not all(number(v) for v in interval):
                return False
            if whole and not band[0] <= interval[0] <= interval[1] <= band[1]:
                return False
            if max(band[0], interval[0]) >= min(band[1], interval[1]):
                return False
        elif mapping(target.get("plane")).get("axis") == axis:
            value = mapping(target.get("plane")).get("value", UNKNOWN)
            if not number(value) or not band[0] <= value <= band[1]:
                return False
        else:
            return False
    return True


def _footprint(target):
    """``target``'s explicit ``bounds``, else the X/Y square holding a round Z-axis
    feature (its ``at`` plus or minus half its largest ``dia``); empty when unknown."""
    bounds = mapping(target.get("bounds"))
    if bounds:
        return bounds
    at, dia, axis = target.get("at"), target.get("dia"), target.get("axis", [0.0, 0.0, 1.0])
    sizes = dia if isinstance(dia, list) else [dia]
    if not (isinstance(at, list) and len(at) == 3 and all(number(v) for v in at[:2])):
        return {}
    if not sizes or not all(number(v) for v in sizes):
        return {}
    if not (isinstance(axis, list) and len(axis) == 3 and all(number(v) for v in axis)):
        return {}
    if abs(axis[0]) > 1e-9 or abs(axis[1]) > 1e-9:
        return {}
    half = max(sizes) / 2
    return {name: [at[i] - half, at[i] + half] for i, name in enumerate(("x", "y"))}


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


def lineage(bundle, setup):
    """The setups whose output ``setup`` receives, oldest first: its ``stock_in`` chain
    (each branch of a joint), as the geometry kernel builds the stock; supplies end it."""
    by_id = {s.get("id"): s for s in bundle.plan.get("setups", [])}
    chain, seen = [], {setup.get("id")}

    def walk(current):
        refs = current.get("stock_in")
        for ref in refs if isinstance(refs, list) else [refs]:
            if isinstance(ref, str) and ref in by_id and ref not in seen:
                seen.add(ref)
                walk(by_id[ref])
                chain.append(by_id[ref])

    walk(setup)
    return chain


def operative_z(bundle, setup, value, face=None, done=0, source=None):
    """One printed Z for the surface at nominal ``value`` in ``setup``: the ``dro_to_z``
    of the op that produced it, on that op's own setup grid (:func:`formed_z`: for a
    grooving/parting blade, the face its rounded corner reading leaves), then as this
    setup's DRO shows it (``dro_z``: rounded up on its grid; a value on both grids
    stays); with no producer, ``dro_z`` of ``value``. An unknown stays unknown.

    The producer is the op ``source`` names in this setup (``"S2 op 20 to_z"``,
    :func:`stock_states`). Else, for the stock ``"top"``, the op that last faced it in
    this setup's first ``done`` ops (:func:`stock_states`). Else the last facing or
    pocketing op proven to cut feature ``face`` in the same-frame setups of this setup's
    :func:`lineage` (and, for a feature, this setup's first ``done`` ops), when it cut it
    to ``value``: for ``"top"`` a facing op on ``top_feature`` (any, if none is named),
    for a feature an op on it or whose feature's XY footprint covers it
    (:func:`_covers_xy`). An equal Z alone is never proof; no ``face`` names no
    producer."""
    from .coordinates import dro_grid, dro_z, formed_z

    if not number(value):
        return value
    producer = _producer(bundle, setup, value, face, done, source)
    if producer:
        value = formed_z(bundle, *producer)
    return dro_z(value, dro_grid(bundle, setup))


def _covers_xy(cut, target):
    """``cut``'s explicit footprint, its X/Y bounds, holds all of ``target``
    (:func:`_covers`, ``whole``): a surface it leaves at Z is only the surface that
    starts there where it spans that surface's whole footprint."""
    bounds = {k: v for k, v in mapping(cut.get("bounds")).items() if k in ("x", "y")}
    return _covers({**cut, "bounds": bounds}, target, whole=True)


def _producer(bundle, setup, value, face, done, source):
    ops = setup.get("ops", [])
    features = bundle.feature_definitions
    if source is None and face == "top" and done:
        states = list(stock_states(setup, features))[:done]
        source = states[-1][2]["top_from"] if states else None
    match = re.fullmatch(r"(\S+) op (\S+) to_z", source) if isinstance(source, str) else None
    if match and match[1] == setup.get("id"):
        return next(((setup, op) for op in ops if str(op.get("op")) == match[2]), None)
    if not isinstance(face, str):
        return None
    frame = setup.get("frame")
    cuts = [
        (earlier, op)
        for earlier in lineage(bundle, setup)
        if frame not in (None, UNKNOWN) and earlier.get("frame") == frame
        for op in earlier.get("ops", [])
    ]
    if face != "top":
        cuts += [(setup, op) for op in ops[:done]]
    top = mapping(setup.get("stock_state")).get("top_feature")
    for cut_setup, op in reversed(cuts):
        name, to_z = op.get("feature"), op.get("to_z")
        if op.get("do") not in FACING | POCKETING or not number(to_z):
            continue
        if face == "top":
            hit = op["do"] in FACING and top in (None, name)
        else:
            hit = name == face or _covers_xy(
                mapping(features.get(name)), mapping(features.get(face))
            )
        if hit:
            return (cut_setup, op) if abs(to_z - value) <= SAME_Z else None
    return None


def evaluate(bundle):
    features = bundle.feature_definitions
    endpoints = {name: [] for name in features}
    unresolved = set()
    errors = set()
    negative_exit = set()
    for setup in bundle.plan["setups"]:
        for op, before, _ in stock_states(setup, features):
            name = op.get("feature")
            if op.get("do") not in HOLE_OPS or name not in features:
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
                # The thread depth band a tap's depth answers to (hole_depth_mm's field).
                band = "thread_depth" if "thread_depth" in feature else "depth"
                row.update(
                    depth_mm=depth,
                    depth_floor_mm=_feature_depth_mm(
                        feature, band, bundle.features.get("units"), 0
                    ),
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
                units = bundle.features.get("units")
                limit = _feature_depth_mm(feature, "depth", units)
                total = depth + lead if number(depth) and number(lead) else UNKNOWN
                row.update(
                    depth_mm=depth,
                    depth_limit_mm=limit,
                    depth_floor_mm=_feature_depth_mm(feature, "depth", units, 0),
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
            face = name if name in before["entry_z"] else "top"
            _operative(row, bundle, setup, face)
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
