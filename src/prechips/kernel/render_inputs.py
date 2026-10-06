"""Shop drawing annotations from the same nominal targets as the traveler.

Only explicit setup-frame values and geometry-matched feature identities cross
this boundary. Display annotations never certify a holding or a toolpath.
"""

from prechips.rules.coordinates import row_id
from prechips.rules.resolution import number, record, resolve
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

    def add_path(op, points, candidates, directed, ids=None):
        points = [_xy(value, scale) for value in points]
        if any(point is None for point in points):
            return
        if len(points) < 2:
            return
        op = str(op)
        paths.append({"op": op, "xy": points, "directed": directed})
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
            for index, segment in enumerate(points):
                add_path(
                    profile.get("op"),
                    segment,
                    range(len(segment)) if index in (0, len(points) - 1) else [],
                    False,
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
    for index, clamp in enumerate(clamps if isinstance(clamps, list) else [], start=1):
        if not isinstance(clamp, dict):
            continue
        ref = clamp.get("ref", "unknown")
        kind = record(resolve(bundle, "fixtures", ref)).get("kind")
        label = kinds.get(kind, str(ref).split(".", 1)[-1].replace("-", " ").replace("_", " "))
        result.append({"index": index, "owner": f"clamp {index} {ref}", "label": label})
    return result


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
    }
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
