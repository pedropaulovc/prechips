"""Shop drawing annotations from the same nominal targets as the traveler.

Only explicit setup-frame values and geometry-matched feature identities cross
this boundary. Display annotations never certify a holding or a toolpath.
"""

from prechips.clamp_labels import clamp_labels
from prechips.rules.coordinates import row_id
from prechips.rules.resolution import number, op_feature, record, resolve, workholding_category
from prechips.sheet import tool_label


def _xy(value, scale):
    if isinstance(value, (list, tuple)) and len(value) == 2 and all(number(v) for v in value):
        return [v * scale for v in value]
    return None


def _directed(table):
    return table.get("cut_order") in ("conventional", "climb")


def contour_annotations(numbers, scale, setup_id):
    """Paths and sparse, shared table keys: arc ends/apex and exact line corners.

    Arc and line tables draw the values the DRO prints (``dro_xy``); each of their keys
    lists the ``rows`` (:func:`row_id`) it labels, which is how the sheet finds it. A
    bounded op's tables (``kernel_clip``) are not drawn here: the kernel draws its clip of
    them (``FreeCAD job _clipped_sketch``), never the whole unclipped path.
    A path is ``directed`` (drawn with travel arrows) only when coordinates established
    its cutting order; otherwise its point order is geometric, not a travel claim.
    """
    paths, waypoints = [], []

    def add_path(op, points, candidates, directed, ids=None, raster=None):
        points = [_xy(value, scale) for value in points]
        if any(point is None for point in points):
            return
        if len(points) < 2:
            return
        op = str(op)
        paths.append({"op": op, "xy": points, "directed": directed})
        if raster is not None:
            paths[-1]["raster"] = raster
        for index in candidates:
            point = points[index]
            rows = [] if ids is None else [ids[index]]
            match = next(
                (
                    w
                    for w in waypoints
                    if w["op"] == op
                    and sum((a - b) ** 2 for a, b in zip(w["xy"], point, strict=False)) < 1e-8
                ),
                None,
            )
            if match is None:
                waypoint = {"label": f"P{len(waypoints) + 1}", "op": op, "xy": point}
                waypoints.append({**waypoint, "rows": rows} if ids is not None else waypoint)
            elif rows:
                match.setdefault("rows", []).extend(rows)

    arc_ops = set()
    for arc in numbers.get("arc_table", []):
        arc_ops.add(arc.get("op"))
        rows = arc.get("rows", [])
        if not rows or arc.get("kernel_clip") is True:
            continue
        subject = f"{setup_id}:{arc.get('op')}"
        add_path(
            arc.get("op"),
            [row.get("dro_xy") for row in rows],
            sorted({0, len(rows) // 2, len(rows) - 1}),
            _directed(arc),
            [row_id(subject, "arc_table", arc, i) for i in range(len(rows))],
        )
    for line in numbers.get("line_table", []):
        if line.get("kernel_clip") is True:
            continue
        points = line.get("dro_xy", [])
        subject = f"{setup_id}:{line.get('op')}"
        add_path(
            line.get("op"),
            points,
            range(len(points)),
            _directed(line),
            [row_id(subject, "line_table", line, i) for i in range(len(points))],
        )
    for profile in numbers.get("profiles", []):
        if profile.get("op") in arc_ops:
            continue
        points = profile.get("cutter_centre", [])
        if not isinstance(points, list) or not points:
            continue
        if isinstance(points[0], dict):
            points = [[point.get("x"), point.get("y")] for point in points]
        if isinstance(points[0], list) and points[0] and isinstance(points[0][0], list):
            # A raster table contains independent straight passes, not joins between passes.
            # Its rows are numbered passes, never P keys: the picture names passes the same way.
            keep_out = bool(record(profile.get("raster")).get("keep_out"))
            for index, segment in enumerate(points):
                add_path(
                    profile.get("op"),
                    segment,
                    [],
                    False,
                    raster={
                        "pass": index + 1,
                        "of": len(points),
                        **({"keep_out": True} if keep_out else {}),
                    },
                )
        else:
            add_path(profile.get("op"), points, range(len(points)), _directed(profile))
    return paths, waypoints


def _clamps(bundle, hold):
    kinds = {
        "shoulder_screw": "SHOULDER SCREW",
        "locating_pin": "CLOCKING PIN",
        "strap_clamp": "STRAP",
        "screw_jack": "SUPPORT JACK",
    }
    result = []
    clamps = hold.get("clamps", [])
    codes = clamp_labels(hold)
    for index, clamp in enumerate(clamps if isinstance(clamps, list) else [], start=1):
        if not isinstance(clamp, dict):
            continue
        ref = clamp.get("ref", "unknown")
        kind = record(resolve(bundle, "fixtures", ref)).get("kind")
        label = kinds.get(kind, str(ref).split(".", 1)[-1].replace("-", " ").replace("_", " "))
        result.append(
            {
                "index": index,
                "code": codes[index - 1],
                "owner": f"clamp {index} {ref}",
                "label": label,
            }
        )
    return result


_HOLDING_NAMES = {"chuck_3jaw": "3-JAW CHUCK", "chuck_4jaw": "4-JAW CHUCK"}


def _holding_name(bundle, reference):
    """The shop name of a holding item's kind ('DIVIDING HEAD', '4-JAW CHUCK'), or None."""
    if not isinstance(reference, str) or reference in ("unknown", "none", "not_applicable"):
        return None
    category = workholding_category(bundle, reference)
    kind = record(resolve(bundle, category, reference)).get("kind")
    if not isinstance(kind, str) or kind == "unknown":
        return None
    return _HOLDING_NAMES.get(kind, kind.replace("_", " ").upper())


def _target(setup):
    """The one feature every op of a setup cuts, else None: a picture names it as the target."""
    # An inspect op naming several features has no single feature: no target then.
    features = {op_feature(op) for op in setup["ops"]}
    if len(features) != 1:
        return None
    (feature,) = features
    if not isinstance(feature, str) or feature == "unknown":
        return None
    ops = [str(op["op"]) for op in setup["ops"]]
    span = f"OP {ops[0]}" if len(ops) == 1 else f"OPS {ops[0]}-{ops[-1]}"
    return {"feature": feature, "label": f"TARGET: {feature.replace('_', ' ')} ({span})"}


def setup_annotations(bundle, setup, numbers):
    scale = {"mm": 1.0, "in": 25.4}.get(bundle.features.get("units"))
    hold, state = record(setup.get("hold")), record(setup.get("stock_state"))
    result = {
        "fixed_jaw_label": "FIXED JAW (" + str(hold.get("fixed_jaw", "side not declared")) + ")",
        "stickout_mm": hold.get("stickout_mm") if number(hold.get("stickout_mm")) else None,
        "ends": [
            {"label": label, "z_mm": state[key]}
            for key, label in (
                ("north_end_z", "NORTH END"),
                ("south_end_z", "SOUTH END"),
                ("plain_end_z", "PLAIN END"),
            )
            if number(state.get(key))
        ],
        "datums": [
            {
                "label": f"DATUM {name}: {datum.get('surface', datum.get('feature', ''))}",
                "feature": datum["feature"],
            }
            for name, datum in record(bundle.features.get("datums")).items()
            if isinstance(datum, dict)
            and isinstance(datum.get("feature"), str)
            and datum["feature"] != "unknown"
        ],
        "clamp_order": hold.get("clamp_order") if isinstance(hold.get("clamp_order"), list) else [],
        "clamp_order_declared": isinstance(hold.get("clamp_order"), list),
        "preload": hold.get("preload_direction")
        if hold.get("preload_direction") in ("clockwise", "counterclockwise")
        else None,
        "clamps": _clamps(bundle, hold),
        "tools": {
            str(op["op"]): tool_label(bundle, op.get("tool", "unknown")) for op in setup["ops"]
        },
        "directions": {
            str(op["op"]): op.get("direction")
            for op in setup["ops"]
            if isinstance(op.get("direction"), str) and op["direction"] != "unknown"
        },
        "holding_name": _holding_name(bundle, hold.get("fixture")),
        "chuck_name": _holding_name(bundle, hold.get("chuck")),
        "target": _target(setup),
    }
    index = record(hold.get("index"))
    if number(index.get("angle_deg")):
        result["index_deg"] = index["angle_deg"]
    result["paths"], result["waypoints"] = (
        contour_annotations(numbers, scale, setup["id"]) if scale else ([], [])
    )
    result["axial_paths"] = []
    for contour in numbers.get("contours", []):
        rows = contour.get("rows", [])
        points = [_xy(row.get("setup_xz"), scale) for row in rows] if scale else []
        if len(points) < 2 or any(point is None for point in points):
            continue
        op = str(contour.get("op"))
        result["axial_paths"].append(
            {"op": op, "xz": points, "x_display": numbers.get("x_display")}
        )
        for index in sorted({0, len(points) // 2, len(points) - 1}):
            result["waypoints"].append(
                {
                    "label": f"P{len(result['waypoints']) + 1}",
                    "op": op,
                    "xz": points[index],
                }
            )
    return result
