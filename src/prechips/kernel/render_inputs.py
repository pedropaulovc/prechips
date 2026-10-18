"""Shop drawing annotations from the same nominal targets as the traveler.

Only explicit setup-frame values and geometry-matched feature identities cross
this boundary. Display annotations never certify a holding or a toolpath.
"""

import math

from prechips.clamp_labels import clamp_labels
from prechips.rules.coordinates import dro_grid, row_id
from prechips.rules.geometry_common import cutting_action
from prechips.rules.resolution import (
    LENGTH_TOLERANCE_MM,
    SAW_OPS,
    hand_fed,
    number,
    op_feature,
    record,
    resolve,
)
from prechips.sheet import tool_label


def _xy(value, scale):
    if isinstance(value, (list, tuple)) and len(value) == 2 and all(number(v) for v in value):
        return [v * scale for v in value]
    return None


def _directed(table):
    return table.get("cut_order") in ("conventional", "climb")


def contour_annotations(numbers, scale, setup_id):
    """Paths and sparse, shared table keys: arc ends/apex and exact line corners.

    Arc and line tables draw the values the DRO prints (``dro_xy``); each key's mm
    geometry binds it to a printed row. Its ``rows`` (:func:`row_id`) references are
    provenance, not index-only matches after clipping. A stair-stepped line
    (``stair_cusp_mm``) is keyed at its ends and miters, not at every
    single-axis step. A bounded op's tables (``kernel_clip``) are not drawn here: the
    kernel draws its clip of them (``FreeCAD job _clipped_sketch``), never the whole
    unclipped path.
    A singleton table retains its real waypoint but draws no connecting path.
    A path is ``directed`` (drawn with travel arrows) only when coordinates established
    its cutting order; otherwise its point order is geometric, not a travel claim.
    """
    paths, waypoints = [], []

    def add_path(op, points, candidates, directed, ids=None, raster=None):
        points = [_xy(value, scale) for value in points]
        if not points or any(point is None for point in points):
            return
        op = str(op)
        if len(points) >= 2:
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
                    if w["op"] == op and math.dist(w["xy"], point) <= LENGTH_TOLERANCE_MM
                ),
                None,
            )
            if match is None:
                waypoint = {"label": f"P{len(waypoints) + 1}", "op": op, "xy": point}
                waypoints.append({**waypoint, "rows": rows} if ids is not None else waypoint)
            elif rows:
                match.setdefault("rows", []).extend(rows)

    table_ops = {
        str(table.get("op"))
        for kind in ("arc_table", "line_table")
        for table in numbers.get(kind, [])
    }
    for arc in numbers.get("arc_table", []):
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
        keys = range(len(points))
        if "stair_cusp_mm" in line:
            flags = line.get("overshoot") or []
            miters = (i for i, flag in enumerate(flags) if flag is True and i < len(points))
            keys = sorted({0, len(points) - 1, *miters})
        add_path(
            line.get("op"),
            points,
            keys,
            _directed(line),
            [row_id(subject, "line_table", line, i) for i in range(len(points))],
        )
    for profile in numbers.get("profiles", []):
        if str(profile.get("op")) in table_ops:
            continue
        points = profile.get("cutter_centre", [])
        if not isinstance(points, list) or not points:
            continue
        if isinstance(points[0], dict):
            points = [[point.get("x"), point.get("y")] for point in points]
        if isinstance(points[0], list) and points[0] and isinstance(points[0][0], list):
            # A raster table contains independent straight passes, not joins between passes.
            # Its rows are numbered passes, never P keys: the picture names passes the same way.
            # Each pass runs in cutting order when the table gives a cutting sense.
            keep_out = bool(record(profile.get("raster")).get("keep_out"))
            for index, segment in enumerate(points):
                add_path(
                    profile.get("op"),
                    segment,
                    [],
                    _directed(profile),
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


def _holding_name(bundle, reference, slot):
    """The shop name of a holding item's kind ('DIVIDING HEAD', '4-JAW CHUCK'), or None."""
    if not isinstance(reference, str) or reference in ("unknown", "none", "not_applicable"):
        return None
    kind = record(resolve(bundle, slot, reference)).get("kind")
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


# Bench actions that take material off edges the stock model does not draw.
_EDGE_ACTIONS = {"deburr"}


def _setup_notes(setup):
    """The picture notes a setup's declared actions establish, and the note the kernel
    prints when it derives no removed volume. A setup without a cutting action lists its
    bench/holding actions; a deburr takes edge material off, so a setup with one never
    says "no material removed"."""
    ops = setup["ops"]
    notes = []
    if not any(cutting_action(op) is not False for op in ops):
        listed = ", ".join(
            f"op {op['op']} {op['do']}" for op in ops if isinstance(op.get("do"), str)
        )
        notes.append(f"No machine cutting: {listed}." if listed else "No ops declared.")
    if any(op.get("do") in _EDGE_ACTIONS for op in ops):
        return notes, None
    return notes, "No material removed in this setup."


def _fit_add(hold):
    """The allowance a fit-up stickout adds to its measured reading (``hold.stickout_fit``),
    when the reading is stated; the picture then labels the stickout as nominal."""
    fit = record(hold.get("stickout_fit"))
    measure, add = fit.get("measure"), fit.get("add_mm")
    stated = isinstance(measure, str) and measure.strip() and measure != "unknown"
    return add if stated and number(add) else None


# Spacing (mm) of the points a drawn blade line runs through.
_BLADE_STEP_MM = 2.0
# The feed end a hand-fed hold declares: the axis and the sign of its start end.
_FEED_END = {"+X": (0, 1), "-X": (0, -1), "+Y": (1, 1), "-Y": (1, -1)}
# How a hand-fed cut's saw table, blade and push aid are drawn (picture only, #335): the
# table's margin round the work and thickness, a 1/2 in band's depth and thickness, and
# the drawn length, width and height of the push aid behind the work's trailing end.
_TABLE_MARGIN_MM, _TABLE_MM = 25.0, 6.0
_BAND_MM = (12.7, 0.64)
_PUSH_MM = (120.0, 24.0, 12.0)
# How far past the saw path the WASTE key points into the offcut (mm).
_WASTE_KEY_MM = 6.0


def hand_fed_scene(bundle, setup, scale):
    """What a hand-fed cut's picture draws beside the work (#335): ``paths`` (each cut's
    saw path, the scribed arc offset by ``allowance_mm`` to the side the saw removes,
    within the op's ``stock_removal_bounds``, run from the hold's ``feed_from`` end with
    feed arrows; the scribed line itself dashed), plain ``waypoints`` keys (START, SAW
    PATH with its minimum leave, SCRIBED LINE, WASTE) and render-only ``boxes`` (the saw
    table under the work, the band standing at the cut start up to the upper guide, the
    push aid behind the work's trailing end). Empty for a hold that is not an admitted
    hand-fed one; a cut whose line the kernel cannot place draws nothing."""
    from prechips.kernel import removal_bounds, scribed_profile

    scene = {"paths": [], "waypoints": [], "boxes": []}
    if hand_fed(bundle, setup)[0] != "admitted":
        return scene
    hold, state = record(setup.get("hold")), record(setup.get("stock_state"))
    start = _FEED_END.get(hold.get("feed_from"))
    margin = [["min", -_TABLE_MARGIN_MM], ["max", _TABLE_MARGIN_MM]]
    scene["boxes"].append(
        {
            "name": "saw table",
            "label": "SAW TABLE",
            "colour": "saw_table",
            "stock_mm": [margin, margin, [["min", -_TABLE_MM], ["min", 0.0]]],
        }
    )
    push = hold.get("push_aid")
    if start is not None and isinstance(push, str) and push != "unknown":
        # The blade starts at the feed_from end, so the work's other end trails.
        axis, sign = start
        trail = ("max", 0.0) if sign < 0 else ("min", 0.0)
        far = ("max", _PUSH_MM[0]) if sign < 0 else ("min", -_PUSH_MM[0])
        along = [trail, far] if sign < 0 else [far, trail]
        across = [("mid", -_PUSH_MM[1] / 2), ("mid", _PUSH_MM[1] / 2)]
        spans = [along, across] if axis == 0 else [across, along]
        scene["boxes"].append(
            {
                "name": "push aid",
                "label": f"{_tool_name(bundle, push)} (TRAILING END)",
                "colour": "push_aid",
                "stock_mm": [*spans, [("min", 0.0), ("min", _PUSH_MM[2])]],
            }
        )
    for op in setup.get("ops") or []:
        if op.get("do") not in SAW_OPS or "follows" not in op:
            continue
        profile = record(scribed_profile(bundle, setup, op))
        bounds = removal_bounds(op.get("stock_removal_bounds"), bundle.features.get("units"))
        centre, radius = profile.get("centre_mm"), profile.get("radius_mm")
        allowance = op.get("allowance_mm")
        if "reason" in bounds or not (
            isinstance(centre, list) and number(radius) and number(allowance) and scale
        ):
            continue
        sign = -1.0 if profile.get("remove") == "inside" else 1.0
        leave = allowance * scale
        saw = _arc_in(centre, radius + sign * leave, bounds["x"], bounds["y"])
        line = _arc_in(centre, radius, bounds["x"], bounds["y"])
        if len(saw) < 2 or len(line) < 2:
            continue
        if start is not None and (saw[-1][start[0]] - saw[0][start[0]]) * start[1] > 0:
            saw.reverse()
        name = str(op["op"])
        scene["paths"] += [
            {"op": name, "xy": saw, "directed": start is not None, "feed": True},
            {"op": name, "xy": line, "dashed": True},
        ]
        middle = saw[len(saw) // 2]
        reach = math.dist(middle, centre)
        waste = [
            centre[i] + (middle[i] - centre[i]) * (reach + sign * _WASTE_KEY_MM) / reach
            for i in (0, 1)
        ]
        keys = [
            ("SAW PATH, LEAVE " + _mm_text(leave) + " MM MIN", middle),
            ("SCRIBED LINE", line[len(line) // 2]),
            ("WASTE", [round(v, 6) for v in waste]),
        ]
        if start is not None:
            keys.insert(0, ("START", saw[0]))
        scene["waypoints"] += [
            {"label": label, "op": name, "xy": xy, "plain": True} for label, xy in keys
        ]
        if start is not None and number(state.get("top_z")) and number(state.get("bottom_z")):
            # The band stands at the cut start, from the table to the upper guide.
            guide = hold.get("guide_above_mm")
            top = state["top_z"] * scale + (guide if number(guide) else 0.0)
            depth, thick = _BAND_MM
            x, y = saw[0]
            half = (depth / 2, thick / 2) if start[0] == 0 else (thick / 2, depth / 2)
            scene["boxes"].append(
                {
                    "name": f"band op {name}",
                    "label": f"BLADE AT CUT START (OP {name})",
                    "colour": "saw_blade",
                    "box_mm": [
                        x - half[0],
                        y - half[1],
                        state["bottom_z"] * scale - _TABLE_MM,
                        x + half[0],
                        y + half[1],
                        top,
                    ],
                }
            )
    return scene


def _mm_text(value):
    return f"{value:.3f}"


def _tool_name(bundle, reference):
    item = record(resolve(bundle, "fixtures", reference))
    return str(item.get("name", reference)).upper()


def _arc_in(centre, radius, xs, ys):
    """Points along the circle ``centre``/``radius``, at most :data:`_BLADE_STEP_MM` apart,
    inside the box ``xs`` x ``ys``, in angle order (over the angles the box spans as seen
    from the centre, or the whole turn when the centre is inside it)."""
    corners = [(x, y) for x in xs for y in ys]
    middle = math.atan2(sum(ys) / 2 - centre[1], sum(xs) / 2 - centre[0])
    inside = xs[0] <= centre[0] <= xs[1] and ys[0] <= centre[1] <= ys[1]
    turns = [
        math.remainder(math.atan2(y - centre[1], x - centre[0]) - middle, 2 * math.pi)
        for x, y in corners
    ]
    low, high = (-math.pi, math.pi) if inside else (min(turns), max(turns))
    count = max(1, math.ceil((high - low) * radius / _BLADE_STEP_MM))
    points = []
    for index in range(count + 1):
        angle = middle + low + (high - low) * index / count
        x, y = centre[0] + radius * math.cos(angle), centre[1] + radius * math.sin(angle)
        if xs[0] <= x <= xs[1] and ys[0] <= y <= ys[1]:
            points.append([round(x, 6), round(y, 6)])
    return points


def setup_annotations(bundle, setup, numbers):
    scale = {"mm": 1.0, "in": 25.4}.get(bundle.features.get("units"))
    hold, state = record(setup.get("hold")), record(setup.get("stock_state"))
    result = {
        "fixed_jaw_label": "FIXED JAW (" + str(hold.get("fixed_jaw", "side not declared")) + ")",
        "stickout_mm": hold.get("stickout_mm") if number(hold.get("stickout_mm")) else None,
        "stickout_add_mm": _fit_add(hold),
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
        "holding_name": _holding_name(bundle, hold.get("fixture"), "workholding"),
        "chuck_name": _holding_name(bundle, hold.get("chuck"), "fixtures"),
        "target": _target(setup),
        # The setup's DRO decimals: picture coordinates and clearances print as the
        # traveler's tables print them (``_Traveler.operative``), one value one text; its
        # step puts a picture's setup coordinates on the grid the fixture tables use.
        "decimals": dro_grid(bundle, setup)[1],
        "dro_step_mm": dro_grid(bundle, setup)[0] * scale if scale else None,
    }
    result["notes"], result["nothing_removed_note"] = _setup_notes(setup)
    if scale:
        # A guided sweep's table-side guide elements, drawn render-only (#255).
        from prechips.rules.guided_sweep import guide_scene

        guides, guide_notes = guide_scene(bundle, setup, numbers, scale)
        if guides:
            result["guides"] = guides
        result["notes"].extend(guide_notes)
    index = record(hold.get("index"))
    if number(index.get("angle_deg")):
        result["index_deg"] = index["angle_deg"]
    result["paths"], result["waypoints"] = (
        contour_annotations(numbers, scale, setup["id"]) if scale else ([], [])
    )
    # A hand-fed cut's saw path, scribed line, keys and saw-side scene (#335).
    scene = hand_fed_scene(bundle, setup, scale)
    result["paths"] += scene["paths"]
    result["waypoints"] += scene["waypoints"]
    if scene["boxes"]:
        result.setdefault("guides", {})["boxes"] = scene["boxes"]
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
    # Each inspect op's set-up sketches, drawn in the part model's own axes (mm), with its
    # place in the setup's route (``position``, the op's index in the setup's op list).
    inspections = [
        {"op": op["op"], "position": position, "requirement": requirement, "views": views}
        for position, op in enumerate(setup["ops"])
        for requirement, views in record(op.get("inspection_views")).items()
        if isinstance(views, list)
    ]
    if inspections:
        result["inspections"] = inspections
    return result
