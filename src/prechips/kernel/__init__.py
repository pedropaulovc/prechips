"""One local FreeCAD job per bundle; only verified, explicit dimensions enter it."""

from __future__ import annotations

import hashlib
import json
import math
import os
import shutil
import subprocess
import tempfile
from contextlib import nullcontext
from pathlib import Path

from prechips.measurements import angle_fact, length_fact, record_trusted
from prechips.rules._envelope import measurement_item, tool_projection
from prechips.rules.geometry_common import (
    TURNING_BLADE_KEYS,
    TURNING_BLADE_KINDS,
    TURNING_HOLDER_KEYS,
    TURNING_TOOL_KEYS,
)
from prechips.rules.resolution import (
    HAND_FINISH,
    WORKHOLDING_CATEGORIES,
    inventory_category,
    number,
    record,
    resolve,
    rough_leave,
    setup_frame,
)

from .render_inputs import setup_annotations

UNKNOWN = "unknown"


def _json(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def discover_kernel():
    """An explicit override is authoritative, including an unavailable override."""
    override = os.environ.get("FREECAD_CMD")
    if override:
        path = Path(override)
        return path.resolve() if path.is_file() else shutil.which(override)
    base = os.environ.get("LOCALAPPDATA")
    if base:
        installed = Path(base) / "Programs" / "FreeCAD 1.1" / "bin" / "freecadcmd.exe"
        if installed.is_file():
            return installed
    return (
        shutil.which("freecadcmd.exe") or shutil.which("FreeCADCmd") or shutil.which("freecadcmd")
    )


def _accepted_length(item, field):
    fact = length_fact(item, field, require_measured=False)
    return fact["value"] if fact["verified"] else UNKNOWN


def _accepted_angle(item, field):
    fact = angle_fact(item, field, require_measured=False)
    return fact["value"] if fact["verified"] else UNKNOWN


def _measured_length(item, field):
    """A positive measured length fact, else unknown (rest jaws and bodies)."""
    fact = length_fact(item, field, require_measured=True)
    value = fact["value"] if fact["verified"] else UNKNOWN
    return value if number(value) and value > 0 else UNKNOWN


def _shank_from(tool, values):
    """Height above the tip where the tool's full shank diameter begins, or unknown.

    That is the flute end, except on a combined drill and countersink: its ``angle_deg``
    seat cone cuts from the pilot out to a wider body, so its shank begins where that
    cone reaches the shank diameter. An unknown shank keeps the flute end, which only
    lowers the start of a body whose diameter is itself unknown.
    """
    flute, cutter = values["flute_len_mm"], values["radius_mm"]
    shank = values["shank_radius_mm"]
    if not (number(flute) and flute > 0):
        return UNKNOWN
    seat = _accepted_angle(tool, "angle_deg")
    if not (number(seat) and number(cutter) and number(shank)) or shank <= cutter:
        return flute
    if not 0 < seat < 180:
        return UNKNOWN
    return flute + (shank - cutter) / math.tan(math.radians(seat / 2))


def _turning_values(bundle, op):
    """Insert, head, shank and toolpost-body facts in mm/degrees, or what is missing."""
    tool = measurement_item(bundle, "tools", op.get("tool"))
    holder = measurement_item(bundle, "holders", op.get("holder"))
    projection = tool_projection(bundle, op, {}, [], require_measured=False)
    hand = record(tool).get("hand", UNKNOWN)
    values = {
        "radius_mm": _accepted_length(tool, "nose_radius"),
        "insert_angle_deg": _accepted_angle(tool, "insert_angle_deg"),
        "entering_angle_deg": _accepted_angle(tool, "entering_angle_deg"),
        # A right-hand tool feeds toward the chuck: -Z in a lathe setup frame.
        "feed_z": {"right": -1, "left": 1}.get(hand, UNKNOWN),
        "edge_len_mm": _accepted_length(tool, "edge_len"),
        "head_len_mm": _accepted_length(tool, "head_len"),
        "shank_width_mm": _accepted_length(tool, "shank_width"),
        "functional_width_mm": _accepted_length(tool, "functional_width"),
        "projection_mm": projection["value"] if projection["verified"] else UNKNOWN,
        "holder_body_width_mm": _accepted_length(holder, "body_width"),
        "holder_body_depth_mm": _accepted_length(holder, "body_depth"),
    }
    if record(resolve(bundle, "tools", op.get("tool"))).get("kind") in TURNING_BLADE_KINDS:
        # A two-cornered grooving/parting blade: both corners nose_radius, front edge
        # blade_width wide (docs/rules-geometry.md "Approach models").
        values["corners"] = 2
        values["blade_width_mm"] = _accepted_length(tool, "blade_width")
    missing = [
        key
        for key, value in values.items()
        if not number(value) or (key != "feed_z" and value <= 0)
    ]
    insert, entering = values["insert_angle_deg"], values["entering_angle_deg"]
    if number(insert) and number(entering) and insert + entering >= 180:
        # The minor (trailing) edge would lead the nose: no real insert has this shape.
        missing += ["insert_angle_deg", "entering_angle_deg"]
    # A tool set out shorter than its head (holder on the head) is measured, not missing:
    # both stay in the job, which leaves the holder unposed, and the rules say why
    # (geometry_common.op_contexts).
    # Reach rule: the radial depth the cutting edge itself spans, else the declared reach.
    reach = _accepted_length(tool, "reach")
    if number(reach) and reach > 0:
        values["flute_len_mm"] = reach
    elif "edge_len_mm" not in missing and "entering_angle_deg" not in missing:
        values["flute_len_mm"] = values["edge_len_mm"] * math.sin(math.radians(entering))
    if "projection_mm" not in missing:
        # Nose to toolpost body: the deepest the holder can stay clear of a wall.
        values["oal_mm"] = values["projection_mm"]
    return values, sorted(set(missing))


def op_inputs(bundle, setup, op, finishing=None, complete=None, tables=None):
    """One op's kernel inputs; ``tables`` is its setup's coordinates numbers, whose printed
    cutter-centre checkpoints the kernel checks against the stock model (``checkpoints``)."""
    from prechips.joint_features import joint_operation
    from prechips.process_features import centre_tool, process_operation
    from prechips.rules.geometry_common import (
        ROTARY,
        TURNING,
        approach,
        complete_form_subjects,
        finishing_subjects,
    )
    from prechips.rules.tip_endpoints import HOLE_OPS, hole_depth_mm, stock_states

    subject = f"{setup['id']}:{op['op']}"
    if op.get("do") in {"saw_cut", "cut_off"}:
        tool = measurement_item(bundle, "tools", op.get("tool"))
        return {
            "subject": subject,
            "do": op["do"],
            "kerf_mm": _accepted_length(tool, "kerf"),
            "cut_plane": saw_plane(op.get("cut_plane"), bundle.features.get("units", UNKNOWN)),
        }
    if op.get("do") in HAND_FINISH:
        return _hand_inputs(bundle, setup, op, subject, finishing)
    model = approach(bundle, setup, op)
    turned = model == TURNING
    if turned:
        values, missing = _turning_values(bundle, op)
    else:
        tool = measurement_item(bundle, "tools", op.get("tool"))
        holder = measurement_item(bundle, "holders", op.get("holder"))
        projection = tool_projection(bundle, op, {}, [], require_measured=False)
        values = {
            "radius_mm": _accepted_length(tool, "dia"),
            "flute_len_mm": _accepted_length(tool, "flute_len"),
            "oal_mm": _accepted_length(tool, "oal"),
            "holder_radius_mm": _accepted_length(holder, "gauge_dia"),
            "holder_gauge_len_mm": _accepted_length(holder, "gauge_len"),
            "projection_mm": projection["value"] if projection["verified"] else UNKNOWN,
            # The tool body past its cutting length: only a reach past the flute needs it.
            "shank_radius_mm": _accepted_length(tool, "shank"),
        }
        for key in ("radius_mm", "holder_radius_mm", "shank_radius_mm"):
            if number(values[key]):
                values[key] /= 2
        values["shank_from_mm"] = _shank_from(tool, values)
        missing = [
            key
            for key, value in values.items()
            if not (number(value) and value > 0)
            and key not in {"oal_mm", "shank_radius_mm", "shank_from_mm"}
        ]
    result = {
        "subject": subject,
        "feature": op.get("feature", UNKNOWN),
        "do": op.get("do", UNKNOWN),
        "finishing": subject in (finishing_subjects(bundle) if finishing is None else finishing),
    }
    joint_cut = joint_operation(bundle, op, result["finishing"])
    if joint_cut is not None:
        result["joint_cut"] = joint_cut
    process_cut = process_operation(bundle, op)
    if process_cut is not None:
        if op.get("do") == "center_drill" and "reason" not in process_cut:
            # The kernel cuts only the centre the selected tool itself makes, closed by its
            # own accepted pilot point: never an assumed angle.
            binding = centre_tool(bundle, op)
            if binding["status"] != "pass":
                process_cut["reason"] = (
                    f"{process_cut['label']} is not the centre tool {op.get('tool')!r} cuts: "
                    + "; ".join(binding["reasons"])
                )
            else:
                process_cut["point_angle_deg"] = binding["tool"]["point_angle_deg"]
                process_cut["body_dia_mm"] = binding["tool"]["body_dia_mm"]
        elif process_cut.get("kind") == "end_face" and not turned and "reason" not in process_cut:
            process_cut.update(face_sweep(op, tables, bundle.features.get("units", UNKNOWN)))
        result["process_cut"] = process_cut
    if "faces" in op:
        result["faces"] = op["faces"]
    if model in (TURNING, ROTARY):
        result["approach"] = model
    units = bundle.features.get("units", UNKNOWN)
    scale = {"mm": 1.0, "in": 25.4}.get(units)
    if "to_z" in op:
        # The op's floor in its setup frame bounds the material it removes from the stock.
        result["to_z"] = op["to_z"] * scale if number(op["to_z"]) and scale else UNKNOWN
    if not turned and str(op.get("do", "")).startswith("rough_"):
        # Always machine mm per side, independent of feature units; a negative leave is
        # unknown here (the coordinates rule reports it as an error).
        result["rough_allowance_mm"] = rough_leave(op)[0]
    feature = record(bundle.feature_definitions.get(op.get("feature")))
    # Joint cuts use transient geometry, never the ordinary finished-face bore path.
    if (
        joint_cut is None
        and op.get("do") in HOLE_OPS
        and feature.get("kind")
        in {
            "hole",
            "counterbore",
            "thread",
            "threaded_hole",
        }
    ):
        # stock_state entry/top heights are machine-frame mm, never scaled by feature units.
        entry = UNKNOWN
        for stock_op, before, _ in stock_states(bundle, setup):
            if stock_op is op or stock_op.get("op") == op["op"]:
                entry = before["entry_z"].get(op.get("feature"), before["top_z"])
                break
        depth = hole_depth_mm(op, feature, units)
        # As tip_endpoints: an absent thru is blind; only an explicit boolean is known.
        thru = feature.get("thru", False)
        result["hole"] = {
            "thru": thru if isinstance(thru, bool) else UNKNOWN,
            "depth_mm": depth if number(depth) else UNKNOWN,
            "entry_z_mm": entry if number(entry) else UNKNOWN,
            # Only the feature's last drill/ream/bore/counterbore must leave its claimed
            # caps formed; a pilot's partial cone or a spot/tap is never checked.
            "complete_form": subject
            in (complete_form_subjects(bundle) if complete is None else complete),
        }
        if thru is True:
            # As tip_endpoints: a through tool's full diameter runs to the exit face (entry
            # less the authored local thickness) plus its exit allowance.
            thickness = record(record(setup.get("stock_state")).get("local_thickness")).get(
                op.get("feature")
            )
            allowance = op.get("exit_mm")
            if number(entry) and number(thickness) and number(allowance) and allowance >= 0:
                result["hole"]["exit_z_mm"] = entry - thickness - allowance
        if op.get("do") in {"spot", "drill"}:
            point = angle_fact(tool, "point_angle", require_measured=False)
            result["hole"]["point_angle_deg"] = point["value"] if point["verified"] else UNKNOWN
    if "stock_removal_bounds" in op:
        result["stock_removal_bounds"] = removal_bounds(op["stock_removal_bounds"], units)
    if tables is not None and not turned:
        table = table_checkpoints(subject, tables, op["op"], units)
        if table is not None:
            result["checkpoints"] = table
    if not turned and "keep_out" in record(op.get("contour")):
        result["keep_out"], result["keep_out_passes"] = raster_keep_out(tables, op["op"], units)
    if model in (TURNING, ROTARY):
        # Turning: the declared span on setup Z bounds and extends the revolved removal.
        # Rotary: the span along the head axis from the chuck pose origin.
        for key in ("z_from", "z_to"):
            if key in op:
                result[key] = op[key] * scale if number(op[key]) and scale else UNKNOWN
    if turned:
        # Facing, parting and cutting to length sweep radially to an explicit to_dia (0:
        # the axis; a part_off omitting it parts to the axis); a bore is never inferred
        # from the finished part, so a later-drilled bore does not leave a core behind.
        if op.get("do") in {"face", "rough_face", "finish_face", "part_off", "cut_to_fit"} and (
            "to_dia" in op or op.get("do") == "part_off"
        ):
            to_dia = op.get("to_dia", 0.0)
            result["to_dia_mm"] = (
                to_dia * scale if number(to_dia) and to_dia >= 0 and scale else UNKNOWN
            )
    if model == ROTARY and "angle_window_deg" in op:
        window = op["angle_window_deg"]
        result["angle_window_deg"] = window if all(number(v) for v in window) else UNKNOWN
    for key, value in values.items():
        if key not in missing and number(value) and (value > 0 or key == "feed_z"):
            result[key] = value
    if missing:
        result["reason"] = (
            "Selected tool/holder dimensions unmeasured or unavailable: " + ", ".join(missing)
        )
    return result


def _xy(value):
    return isinstance(value, list) and len(value) == 2 and all(number(v) for v in value)


def face_sweep(op, tables, units):
    """``{"sweep": ...}``: what a milled process end face op cuts, its generated
    cutter-centre passes (the coordinates ``profiles`` the sheet prints for it) as
    setup-frame mm polylines ``paths`` and its cutter end ``to_z_mm``. The kernel removes
    only the stock that sweep reaches, never the whole slab past the face's plane: a pass
    too shallow, too short or off the stock leaves its material. ``{"reason": ...}`` when
    the passes or depth are unknown."""
    scale = {"mm": 1.0, "in": 25.4}.get(units)
    if scale is None:
        return {"reason": f"feature units {units!r} are not mm or in"}
    to_z = op.get("to_z", UNKNOWN)
    if not number(to_z):
        return {"reason": f"op {op.get('op')} to_z is unknown, so the face it cuts is unknown"}
    profiles = [
        profile
        for profile in record(tables).get("profiles", [])
        if isinstance(profile, dict) and profile.get("op") == op.get("op")
    ]
    if not profiles:
        return {"reason": f"op {op.get('op')} prints no cutter-centre passes for its end face"}
    paths = []
    for profile in profiles:
        why = next(
            (
                profile[key]
                for key in ("raster_reason", "arc_reason", "clip_reason")
                if key in profile
            ),
            None,
        )
        if why is not None:
            return {"reason": f"op {op.get('op')} cutter-centre passes are unknown: {why}"}
        centre = profile.get("cutter_centre")
        if isinstance(centre, list) and centre and _xy(centre[0]):
            centre = [centre]  # one path of points, not a list of passes
        if not (
            isinstance(centre, list)
            and centre
            and all(isinstance(path, list) and path and all(map(_xy, path)) for path in centre)
        ):
            return {"reason": f"op {op.get('op')} cutter-centre passes are unknown"}
        paths.extend([[v * scale for v in point] for point in path] for path in centre)
    return {"sweep": {"paths": paths, "to_z_mm": to_z * scale}}


def _hand_inputs(bundle, setup, op, subject, finishing):
    """A bench file's kernel inputs: its claims and the policy's ``max_filing_stock_mm``,
    the most stock a file takes off its claimed faces; it has no machine cutter or holder.
    A file guided by filing buttons held in this setup names the kit's solids by their
    kernel owner (``guide_owner``): where its cut reaches them is where the file stops."""
    from prechips.rules.coordinates import filing_cap
    from prechips.rules.geometry_common import HAND, finishing_subjects

    result = {
        "subject": subject,
        "feature": op.get("feature", UNKNOWN),
        "do": op["do"],
        "finishing": subject in (finishing_subjects(bundle) if finishing is None else finishing),
        "approach": HAND,
        "max_filing_stock_mm": filing_cap(bundle),
    }
    if "faces" in op:
        result["faces"] = op["faces"]
    kit = record(op.get("guide")).get("buttons")
    hold = record(setup.get("hold"))
    clamps = hold.get("clamps") if isinstance(hold.get("clamps"), list) else []
    owner = next(
        (
            _clamp_owner(index, kit)
            for index, clamp in enumerate(clamps, start=1)
            if record(clamp).get("ref") == kit
        ),
        kit if hold.get("fixture") == kit else None,
    )
    if isinstance(kit, str) and kit != UNKNOWN and owner is not None:
        result["guide_owner"] = owner
    return result


def _clamp_owner(index, reference):
    """The kernel owner of clamp ``index``'s solids: their tags are ``<owner>:<name>``."""
    return f"clamp {index} {reference}"


def raster_keep_out(tables, op, units):
    """(An op's face-raster ``keep_out`` circles as the coordinates rule mapped them into
    its setup frame, ``at_mm`` setup XY and ``dia_mm``, and its passes as that rule split
    them, ``printed`` cutter-centre pieces and the ``skipped`` parts the circles removed,
    each ``[[x, y], [x, y]]`` setup-frame mm), both UNKNOWN unless every raster record of
    the op carries them: the kernel never cuts or poses through an unmapped island, nor
    takes stock that no printed piece sweeps."""
    scale = {"mm": 1.0, "in": 25.4}.get(units)
    circles, passes = None, {"printed": [], "skipped": []}

    def segments(value):
        if not isinstance(value, list) or not all(
            isinstance(segment, list)
            and len(segment) == 2
            and all(isinstance(p, list) and len(p) == 2 and all(map(number, p)) for p in segment)
            for segment in value
        ):
            return None
        return [[[v * scale for v in point] for point in segment] for segment in value]

    for profile in record(tables).get("profiles", []):
        profile = record(profile)
        if profile.get("op") != op:
            continue
        raster = record(profile.get("raster"))
        printed = segments(profile.get("cutter_centre"))
        skipped = segments(raster.get("keep_out_skipped"))
        mapped = raster.get("keep_out")
        if scale is None or not isinstance(mapped, list) or printed is None or skipped is None:
            return UNKNOWN, UNKNOWN
        islands = []
        for circle in map(record, mapped):
            at = circle.get("at")
            if not (isinstance(at, list) and all(number(v) for v in at)):
                return UNKNOWN, UNKNOWN
            islands.append({"at_mm": [v * scale for v in at], "dia_mm": circle.get("dia_mm")})
        circles = circles or islands
        passes["printed"].extend(printed)
        passes["skipped"].extend(skipped)
    return (UNKNOWN, UNKNOWN) if circles is None else (circles, passes)


def table_checkpoints(subject, tables, op, units):
    """An op's printed DRO cutter-centre checkpoints in setup-frame mm: ``rows`` of id,
    ``xy_mm`` and ``tip_z_mm`` (the values the DRO shows, ``overshoot`` on a corner miter),
    each printed table's ``paths`` (``xy_mm`` in cutting order, its ``tip_z_mm``, row
    ``ids``, ``overshoot`` flags and ``stepped``), and why any is unknown; None when it
    prints none.

    A bounded op's tables (``bounded``) are whole: the kernel clips them where the cutter
    first meets stock outside the op's stock_removal_bounds. Each path then carries its
    ``table`` (first row id), ``name``, ``kind`` and ``cutter_side``, and ``dro`` the DRO
    grid (plan-unit ``step``, ``decimals``, mm ``scale``) its clip points print on; the
    row-id formats (``row_format``, ``fragment_format``) name the pieces' rows.
    """
    from prechips.rules.coordinates import FRAGMENT_FORMAT, ROW_FORMAT, checkpoints

    printed = [path for path in checkpoints(subject, tables, op) if path["rows"]]
    if not printed:
        return None
    bounded = any(path["bounded"] for path in printed)
    scale = {"mm": 1.0, "in": 25.4}.get(units)
    if scale is None:
        reason = f"feature units {units!r} are not mm or in"
        return {"rows": [], "paths": [], "bounded": bounded, "reason": reason}
    rows, paths, unknown = [], [], []
    for path in printed:
        points = []
        for name, xy, tip, overshoot in path["rows"]:
            if isinstance(xy, list) and len(xy) == 2 and all(number(v) for v in (*xy, tip)):
                xy_mm = [v * scale for v in xy]
                point = {"id": name, "xy_mm": xy_mm, "tip_z_mm": tip * scale}
                points.append({**point, "overshoot": True} if overshoot else point)
            else:
                unknown.append(name)
        rows.extend(points)
        if len(points) == len(path["rows"]) and len({p["tip_z_mm"] for p in points}) == 1:
            paths.append(
                {
                    "table": points[0]["id"],
                    "name": path["name"],
                    "kind": path["kind"],
                    "cutter_side": path["cutter_side"],
                    "directed": path["directed"],
                    "xy_mm": [point["xy_mm"] for point in points],
                    "tip_z_mm": points[0]["tip_z_mm"],
                    "ids": [point["id"] for point in points],
                    "overshoot": [point.get("overshoot") is True for point in points],
                    "stepped": path["stepped"],
                }
            )
        elif len(points) == len(path["rows"]):
            unknown.append(f"{path['rows'][0][0]} (its rows stand at different tips)")
    result = {"rows": rows, "paths": paths, "bounded": bounded}
    if bounded:
        grid = tables.get("dro_grid", {})
        result["dro"] = {"step": grid.get("step"), "decimals": grid.get("decimals"), "scale": scale}
        result["row_format"] = ROW_FORMAT
        result["fragment_format"] = FRAGMENT_FORMAT
    if unknown:
        more = f" (+{len(unknown) - 3} more)" if len(unknown) > 3 else ""
        result["reason"] = (
            "printed checkpoint setup XY or tip Z is unknown: " + ", ".join(unknown[:3]) + more
        )
    return result


def saw_plane(plane, units):
    """A blade centre plane in setup axes, normalized from feature units to mm."""
    scale = {"mm": 1.0, "in": 25.4}.get(units)
    if scale is None:
        return {"reason": f"cut_plane units {units!r} are not mm or in"}
    plane = record(plane)
    if (
        plane.get("axis") not in ("x", "y", "z")
        or plane.get("keep") not in ("below", "above")
        or not number(plane.get("value"))
    ):
        return {"reason": "cut_plane needs axis x/y/z, numeric value and keep below/above"}
    return {"axis": plane["axis"], "value": plane["value"] * scale, "keep": plane["keep"]}


def removal_bounds(bounds, units):
    """An op's declared setup-frame clearing box in mm, or why it is not one."""
    scale = {"mm": 1.0, "in": 25.4}.get(units)
    if scale is None:
        return {"reason": f"stock_removal_bounds units {units!r} are not mm or in"}
    bounds = record(bounds)
    result, bad = {}, []
    for axis in ("x", "y", "z"):
        span = bounds.get(axis, UNKNOWN)
        if (
            isinstance(span, list)
            and len(span) == 2
            and all(number(v) for v in span)
            and span[0] < span[1]
        ):
            result[axis] = [span[0] * scale, span[1] * scale]
        else:
            bad.append(axis)
    if bad:
        return {
            "reason": "stock_removal_bounds "
            + ", ".join(bad)
            + " not a numeric [lo, hi] span with lo < hi"
        }
    return result


_CHUCK_JAWS = {"chuck_3jaw": 3, "chuck_4jaw": 4}
_CHUCK_DIMS = ("body_dia", "body_length", "bore_dia", "jaw_width", "jaw_height", "jaw_depth")
_ABSENT = (None, "none", "not_applicable")
_BLOCK_EDGES = ("length", "width", "height")


def _positive_length(item, field):
    value = _accepted_length(item, field)
    return value if number(value) and value > 0 else UNKNOWN


def _pose(value):
    """A setup-frame pose with unit, orthogonal x and z axes, or None."""
    pose = record(value)
    if not all(_vector(pose.get(key)) for key in ("origin_mm", "x", "z")):
        return None
    x, z = pose["x"], pose["z"]
    norms = [sum(v * v for v in axis) ** 0.5 for axis in (x, z)]
    dot = sum(a * b for a, b in zip(x, z, strict=True))
    if any(abs(n - 1) > 1e-6 for n in norms) or abs(dot) > 1e-6:
        return None
    return {key: list(pose[key]) for key in ("origin_mm", "x", "z")}


def _solids(item, owner):
    """(engine primitives, debts) for an inventory item's authored ``solids``.

    A ``void`` primitive is cut from the owner's other primitives (or those it ``cuts``);
    a solid whose void is untrusted or malformed is not drawn, since uncut it would read
    as material where the owner has a bore or slot.
    """
    solids = record(item).get("solids", UNKNOWN)
    if not isinstance(solids, list) or not solids:
        return [], [f"{owner} declares no solids"]
    result, debts, bad_voids = [], [], []
    for index, solid in enumerate(solids, start=1):
        solid = record(solid)
        name = solid.get("name", UNKNOWN)
        name = name if name != UNKNOWN else f"#{index}"
        label = f"{owner} solid {name}"
        void = solid.get("void") is True
        cuts = solid.get("cuts", UNKNOWN)
        cuts = cuts if isinstance(cuts, list) and cuts else None
        trusted, why = record_trusted(solid, require_measured=False)
        if not trusted:
            debts.append(f"{label}: {why}")
            if void:
                bad_voids.append((name, cuts))
            continue
        at, shape = solid.get("at_mm"), solid.get("shape")
        primitive = {"name": f"{owner}:{name}", "local": name, "shape": shape, "at_mm": at}
        caption = solid.get("label")
        if isinstance(caption, str) and caption.strip() and caption != UNKNOWN:
            primitive["label"] = caption.strip()
        locates = solid.get("locates")
        if isinstance(locates, str) and locates.strip() and locates != UNKNOWN:
            # The locating element: a locate clamp must prove it bears on the stock.
            primitive["locates"] = True
        if void:
            primitive["void"] = True
            if cuts is not None:
                primitive["cuts"] = cuts
        if shape == "box":
            size = solid.get("size_mm")
            ok = _vector(at) and _vector(size) and all(v > 0 for v in size)
            primitive["size_mm"] = size
        elif shape == "cylinder":
            axis = solid.get("axis")
            dims = [solid.get("dia_mm"), solid.get("length_mm")]
            ok = (
                _vector(at)
                and _vector(axis)
                and abs(sum(v * v for v in axis) ** 0.5 - 1) <= 1e-6
                and all(number(v) and v > 0 for v in dims)
            )
            primitive.update(axis=axis, dia_mm=dims[0], length_mm=dims[1])
        else:
            ok = False
        if ok:
            result.append(primitive)
        else:
            debts.append(
                f"{label}: needs shape box (at_mm, positive size_mm) or cylinder "
                "(at_mm, unit axis, positive dia_mm and length_mm)"
            )
            if void:
                bad_voids.append((name, cuts))
    for void, cuts in bad_voids:
        uncut = [p for p in result if not p.get("void") and (cuts is None or p["local"] in cuts)]
        for primitive in uncut:
            debts.append(
                f"{owner} solid {primitive['local']}: not drawn, its void {void} is unresolved"
            )
            result.remove(primitive)
    if not any(not p.get("void") for p in result):
        result = []
    return result, debts


def _vise_inputs(bundle, hold, fixture, result):
    missing = []
    for key in ("fixed_jaw", "jaws_along"):
        value = hold.get(key, UNKNOWN)
        result[key] = value
        if value == UNKNOWN:
            missing.append(key)
    for key in ("grip_mm", "jaw_above_parallels_mm"):
        value = hold.get(key, UNKNOWN)
        if hold.get(key + "_verify") is not False and key + "_verify" in hold:
            value = UNKNOWN
        if number(value) and value > 0:
            result[key] = value
        elif key == "jaw_above_parallels_mm" and value == 0:
            result[key] = value
        else:
            missing.append(key)
    centre = hold.get("jaw_center_along_mm", UNKNOWN)
    if number(centre):
        result["jaw_center_along_mm"] = centre
    for key in ("jaw_height", "jaw_width", "jaw_depth", "opening"):
        value = _accepted_length(fixture, key)
        if number(value) and value > 0:
            result[key + "_mm"] = value
        else:
            missing.append(key + "_mm")
    reference = hold.get("parallels")
    if reference in ("none", "not_applicable"):
        # Declared absence (not a missing key): the stock seats on the vise bed, zero lift.
        result["parallels_height_mm"] = 0.0
    else:
        height = _accepted_length(measurement_item(bundle, "fixtures", reference), "height")
        if number(height) and height > 0:
            result["parallels_height_mm"] = height
        else:
            missing.append("parallels_height_mm")
    _jaw_bar_inputs(bundle, hold, result)
    _jaw_buttons_inputs(bundle, hold, result)
    if missing:
        result["reason"] = "Fixture pose/dimensions unmeasured or unavailable: " + ", ".join(
            missing
        )


def _jaw_bar_inputs(bundle, hold, result):
    """A declared round bar between the work and the moving jaw, or why it is unplaceable.

    The moving jaw's position depends on the bar, so an unresolved bar leaves the jaws
    unplaced (``jaw_bar_reason``), never drawn as if the jaw closed on the work.
    """
    bar = hold.get("jaw_bar")
    if bar is None:
        return
    item = measurement_item(bundle, "fixtures", bar) if bar != UNKNOWN else {}
    dims = {key: _measured_length(item, key) for key in ("dia", "length")}
    missing = [] if record(item).get("kind") == "round_bar" else [f"{bar!r} as a round_bar"]
    missing.extend(f"{key}_mm (measured)" for key, value in dims.items() if value == UNKNOWN)
    if missing:
        result["jaw_bar_reason"] = "jaw_bar unresolved: " + ", ".join(missing)
        return
    result["jaw_bar"] = {"name": bar, "dia_mm": dims["dia"], "length_mm": dims["length"]}


_JAW_BUTTON_SIZES = ("dia", "thickness", "spigot_dia", "spigot_length")


def _jaw_buttons_inputs(bundle, hold, result):
    """Declared jaw buttons (one between each jaw and the work), or why they are unplaceable.

    The jaws close on the buttons, so an unresolved button leaves the jaws unplaced
    (``jaw_buttons_reason``): every size is a measured fact, never a default.
    """
    buttons = hold.get("jaw_buttons")
    if buttons is None:
        return
    item = measurement_item(bundle, "fixtures", buttons) if buttons != UNKNOWN else {}
    dims = {key: _measured_length(item, key) for key in _JAW_BUTTON_SIZES}
    kind = record(item).get("kind")
    missing = [] if kind == "jaw_buttons" else [f"{buttons!r} as jaw_buttons"]
    missing.extend(f"{key}_mm (measured)" for key, value in dims.items() if value == UNKNOWN)
    if missing:
        result["jaw_buttons_reason"] = "jaw_buttons unresolved: " + ", ".join(missing)
        return
    result["jaw_buttons"] = {"name": buttons, **{key + "_mm": dims[key] for key in dims}}


def _centres(value, minimum, maximum=None):
    return (
        isinstance(value, list)
        and minimum <= len(value) <= (maximum or len(value))
        and all(
            isinstance(point, list) and len(point) == 2 and all(number(v) for v in point)
            for point in value
        )
    )


def _parallels_inputs(bundle, hold, result):
    """Parallel boxes (below the seat) need dimensions, two centres and a length axis."""
    reference = hold.get("parallels")
    if reference in _ABSENT:
        return
    result["parallels_ref"] = reference
    parallels = measurement_item(bundle, "fixtures", reference)
    for dimension in ("height", "length", "width"):
        value = _positive_length(parallels, dimension)
        if value != UNKNOWN:
            result["parallels_" + dimension + "_mm"] = value
    if _centres(hold.get("parallels_centres_mm"), 2, 2):
        result["parallels_centres_mm"] = hold["parallels_centres_mm"]
    along = hold.get("jaws_along") if result["kind"] == "vise" else hold.get("parallels_along")
    if along in ("x", "y"):
        result["parallels_along"] = along


def _riser_inputs(bundle, hold, result, debts):
    """Vise riser blocks under the parallels: oriented edges and declared centres."""
    reference = hold.get("riser")
    if reference in _ABSENT and isinstance(hold.get("supports"), str):
        candidate = measurement_item(bundle, "fixtures", hold["supports"])
        if record(candidate).get("kind") == "blocks_123":
            reference = hold["supports"]
    if reference in _ABSENT:
        return
    block = measurement_item(bundle, "fixtures", reference)
    edges = {edge: _positive_length(block, edge) for edge in _BLOCK_EDGES}
    up, along = hold.get("riser_up"), hold.get("riser_along")
    missing = [f"{reference} {edge}" for edge, value in edges.items() if value == UNKNOWN]
    if up not in _BLOCK_EDGES or along not in _BLOCK_EDGES or up == along:
        missing.append("riser_up / riser_along (two different block edges)")
    if not _centres(hold.get("riser_centres_mm"), 1):
        missing.append("riser_centres_mm")
    if result.get("jaws_along") not in ("x", "y"):
        missing.append("jaws_along")
    if missing:
        debts.append("riser blocks not drawn: " + ", ".join(missing) + " undeclared")
        return
    across = next(edge for edge in _BLOCK_EDGES if edge not in (up, along))
    result["riser"] = {
        "name": reference,
        "size_mm": [edges[along], edges[across], edges[up]],
        "centres_mm": hold["riser_centres_mm"],
    }


def _chuck_inputs(chuck, hold, result, reference):
    """Chuck body/jaw dimensions and pose; jaws close on the stock in the kernel."""
    missing = []
    result["chuck_ref"] = reference
    result["jaws"] = _CHUCK_JAWS.get(record(chuck).get("kind"))
    if result["jaws"] is None:
        missing.append(f"chuck {reference!r} kind (chuck_3jaw or chuck_4jaw)")
    pose = _pose(hold.get("pose"))
    if pose is None:
        missing.append("pose (origin_mm and unit orthogonal x, z)")
    else:
        result["pose"] = pose
    clock = hold.get("jaw_clock_deg", UNKNOWN)
    if number(clock):
        result["jaw_clock_deg"] = clock
    else:
        missing.append("jaw_clock_deg")
    grip = hold.get("grip_mm", UNKNOWN)
    if hold.get("grip_mm_verify") is not False and "grip_mm_verify" in hold:
        grip = UNKNOWN
    if number(grip) and grip > 0:
        result["grip_mm"] = grip
    else:
        missing.append("grip_mm")
    for dimension in _CHUCK_DIMS:
        value = _positive_length(chuck, dimension)
        if value == UNKNOWN:
            missing.append(dimension + "_mm")
        else:
            result[dimension + "_mm"] = value
    if missing:
        result["reason"] = "Fixture pose/dimensions unmeasured or unavailable: " + ", ".join(
            missing
        )
    elif result["bore_dia_mm"] >= result["body_dia_mm"]:
        result["reason"] = f"chuck {reference!r} bore_dia is not smaller than its body_dia"


def _centre_inputs(bundle, machine, hold, result, gaps):
    """A dead centre and the ``machine``'s tailstock quill on the chuck axis, or the gap."""
    reference = hold.get("support")
    if reference in _ABSENT:
        return
    item = measurement_item(bundle, "fixtures", reference) if reference != UNKNOWN else {}
    if record(item).get("kind") != "dead_centre":
        gaps.append(f"support {reference!r} has no dead_centre fixture solid model")
        return
    values = {
        "dia_mm": _positive_length(item, "dia"),
        "length_mm": _positive_length(item, "length"),
        "quill_dia_mm": _positive_length(record(machine.get("tailstock")), "quill_dia"),
    }
    angle = angle_fact(item, "point_angle", require_measured=False)
    values["point_angle_deg"] = (
        angle["value"] if angle["verified"] and 0 < angle["value"] < 180 else UNKNOWN
    )
    extension = hold.get("quill_extension_mm", UNKNOWN)
    values["quill_extension_mm"] = extension if number(extension) and extension >= 0 else UNKNOWN
    tip = hold.get("support_tip_mm", UNKNOWN)
    values["tip_mm"] = tip if _vector(tip) else UNKNOWN
    missing = [key for key, value in values.items() if value == UNKNOWN]
    if "pose" not in result:
        missing.append("hold.pose (centre axis)")
    if missing:
        gaps.append(f"dead centre {reference!r} not drawn: " + ", ".join(missing) + " unresolved")
        return
    hole = hold.get("centre_hole_dia_mm")
    if hole is not None and not (number(hole) and hole > 0):
        gaps.append(f"dead centre {reference!r} not drawn: centre_hole_dia_mm is not positive")
        return
    result["centre"] = {"name": reference, **values}
    if hole is not None and "centre_hole" not in hold:
        # The work's centre-hole countersink: the stock the centre point seats in. A named
        # process centre is instead cut by its own earlier op into the stock received here.
        result["centre"]["hole_dia_mm"] = hole


def _clamp_inputs(bundle, hold, result, gaps):
    """Posed clamp members' solids; every undrawn clamp is a gap and a strap-wall debt."""
    clamps = hold.get("clamps", [])
    placed, debts = [], []
    for index, clamp in enumerate(clamps if isinstance(clamps, list) else [], start=1):
        clamp = record(clamp)
        reference = clamp.get("ref", UNKNOWN)
        item = measurement_item(bundle, "fixtures", reference) if reference != UNKNOWN else {}
        pose = _pose(clamp.get("pose"))
        if not item:
            debts.append(f"clamp {index} {reference!r} is not a listed fixture")
            continue
        if pose is None:
            debts.append(f"clamp {index} {reference!r} pose is undeclared or not orthonormal")
            continue
        solids, missing = _solids(item, _clamp_owner(index, reference))
        debts.extend(missing)
        if solids:
            placed.append(
                {
                    "name": _clamp_owner(index, reference),
                    "pose": pose,
                    "solids": solids,
                    # Undeclared is no restraint; a press is credited only by the kernel's
                    # contact and support proof, never by this label alone.
                    "restraint": clamp.get("restraint", "none"),
                }
            )
    gaps.extend(debts)
    if placed:
        result["clamps"] = placed
    if debts:
        result["clamp_debts"] = debts


# Follow rest jaw sides: trailing the cutting point on the diameter just turned (the
# default, the diameter turning_deflection rides), or leading it on the uncut one.
_JAW_SIDES = ("turned", "uncut")


def _rest_subjects(setup, entry):
    """Op subjects a rest serves; omitted ``ops`` serves every op (as turning_deflection)."""
    ops = entry.get("ops", UNKNOWN)
    return [f"{setup['id']}:{op}" for op in ops] if isinstance(ops, list) else "all"


def _follow_rest(setup, entry, item, reference):
    """Engine follow-rest record: carriage-relative jaws, or the fields it still needs."""
    rest = {
        "name": reference,
        "subjects": _rest_subjects(setup, entry),
        "side": entry.get("jaw_side", "turned"),
    }
    missing = []
    lead = entry.get("jaw_lead_mm", UNKNOWN)
    if number(lead) and lead > 0:
        rest["lead_mm"] = lead
    else:
        missing.append(f"plan hold.supports[{reference}].jaw_lead_mm (positive)")
    if rest["side"] not in _JAW_SIDES:
        missing.append(f"plan hold.supports[{reference}].jaw_side (turned or uncut)")
    engage = entry.get("engage_at_z_mm", UNKNOWN)
    if number(engage):
        # Where the jaws go on: the picture poses them there, beside the tool.
        rest["engage_at_z_mm"] = engage
    if record(item).get("kind") != "follow_rest":
        missing.append(f"fixtures.{reference} kind follow_rest")
    for dimension in ("jaw_width", "jaw_height", "jaw_depth"):
        value = _measured_length(item, dimension)
        if value == UNKNOWN:
            missing.append(f"fixtures.{reference}.{dimension}_mm (measured)")
        else:
            rest[dimension + "_mm"] = value
    angles = record(item).get("jaw_angles_deg", UNKNOWN)
    if isinstance(angles, list) and angles and all(number(a) for a in angles):
        rest["jaw_angles_deg"] = angles
    else:
        missing.append(f"fixtures.{reference}.jaw_angles_deg")
    if missing:
        rest["missing"] = missing
    return rest


def _steady_rest(setup, entry, item, reference):
    """Engine steady-rest record: a static band at ``at_z_mm``, or why it is not drawn."""
    missing = []
    at_z = entry.get("at_z_mm", UNKNOWN)
    if not number(at_z):
        missing.append(f"plan hold.supports[{reference}].at_z_mm")
    if record(item).get("kind") != "steady_rest":
        missing.append(f"fixtures.{reference} kind steady_rest")
    values = {}
    for dimension in ("body_dia", "body_length"):
        value = _measured_length(item, dimension)
        if value == UNKNOWN:
            missing.append(f"fixtures.{reference}.{dimension}_mm (measured)")
        values[dimension + "_mm"] = value
    if missing:
        return None, f"steady rest {reference!r} not drawn: " + ", ".join(missing) + " unresolved"
    record_ = {"name": reference, "subjects": _rest_subjects(setup, entry), "at_z_mm": at_z}
    return {**record_, **values}, None


def _supports_inputs(bundle, setup, hold, result, debts, gaps):
    """Rests become engine records; any other undrawn support is a gap (or a vise debt).

    A follow rest rides the carriage, so it is no static solid: the engine poses its jaws
    with the tool of every op it serves. While it lacks a measured field it is a scene and
    interference debt, and the ops it serves stay unknown in the engine; ops it does not
    serve see it parked off the work.
    """
    supports = hold.get("supports")
    values = supports if isinstance(supports, list) else [supports]
    drawn = record(result.get("riser")).get("name")
    follow, steady = [], []
    for value in values:
        reference = record(value).get("ref", UNKNOWN) if isinstance(value, dict) else value
        if reference in _ABSENT or reference == drawn:
            continue
        if isinstance(value, dict) and ("jaw_lead_mm" in value or "at_z_mm" in value):
            item = measurement_item(bundle, "fixtures", reference) if reference != UNKNOWN else {}
            if "jaw_lead_mm" in value and "at_z_mm" not in value:
                rest = _follow_rest(setup, value, item, reference)
                follow.append(rest)
                if rest.get("missing"):
                    debts.append(
                        f"follow rest {reference!r} not drawn: "
                        + ", ".join(rest["missing"])
                        + " unresolved"
                    )
                continue
            if "at_z_mm" in value and "jaw_lead_mm" not in value:
                rest, gap = _steady_rest(setup, value, item, reference)
                if rest is None:
                    gaps.append(gap)
                else:
                    steady.append(rest)
                continue
        gaps.append(f"supports {reference!r} has no fixture solid model")
    if follow:
        result["follow_rests"] = follow
    if steady:
        result["steady_rests"] = steady


def hold_inputs(bundle, setup):
    hold = record(setup.get("hold"))
    category = inventory_category(bundle, hold.get("fixture"), WORKHOLDING_CATEGORIES)
    fixture = measurement_item(bundle, category, hold.get("fixture")) if category else {}
    kind = record(fixture).get("kind", UNKNOWN)
    result = {"kind": kind, "method": hold.get("method", UNKNOWN)}
    # Scene-only debts (supports below the seat) and gaps (undrawn possible obstacles).
    debts, gaps = [], []
    if kind == "vise":
        _vise_inputs(bundle, hold, fixture, result)
        _riser_inputs(bundle, hold, result, debts)
    elif kind in _CHUCK_JAWS:
        _chuck_inputs(fixture, hold, result, hold.get("fixture"))
        machine = measurement_item(bundle, "machines", setup.get("machine"))
        _centre_inputs(bundle, machine, hold, result, gaps)
    elif kind == "dividing_head":
        reference = hold.get("chuck", UNKNOWN)
        chuck = measurement_item(bundle, "fixtures", reference) if reference != UNKNOWN else {}
        _chuck_inputs(chuck, hold, result, reference)
        solids, missing = _solids(fixture, hold.get("fixture"))
        result["head_solids"] = solids
        gaps.extend(missing)
        # A dividing head's own tailstock carries the centre.
        _centre_inputs(bundle, fixture, hold, result, gaps)
    elif kind != UNKNOWN and isinstance(record(fixture).get("solids"), list):
        pose = _pose(hold.get("pose"))
        if pose is None:
            result["reason"] = "Fixture pose/dimensions unmeasured or unavailable: pose"
        else:
            result["pose"] = pose
        result["solids"], missing = _solids(fixture, hold.get("fixture"))
        gaps.extend(missing)
    else:
        result["reason"] = "Fixture solids are not declared for this holding kind."
    stop_ref = hold.get("stop_fixture")
    if stop_ref not in _ABSENT:
        stop_item = measurement_item(bundle, "fixtures", stop_ref)
        stop_pose = _pose(hold.get("stop_pose"))
        if stop_pose is None:
            gaps.append("stop not drawn: declare its position and orientation")
        elif not stop_item:
            gaps.append("stop not drawn: selected stop fixture is not in the inventory")
        else:
            stop_solids, missing = _solids(stop_item, f"stop {stop_ref}")
            gaps.extend(missing)
            if stop_solids:
                result["stop"] = {"pose": stop_pose, "solids": stop_solids}
    _parallels_inputs(bundle, hold, result)
    _clamp_inputs(bundle, hold, result, gaps)
    # Vise supports sit below the seat (render-only); elsewhere an undrawn support may collide.
    support_gaps = []
    _supports_inputs(bundle, setup, hold, result, debts, support_gaps)
    (debts if kind == "vise" else gaps).extend(support_gaps)
    result["debts"], result["gaps"] = debts, gaps
    return result


def build_job(bundle):
    from prechips.joint_features import primitives_mm, setup_joint
    from prechips.process_features import primitives_mm as process_primitives_mm
    from prechips.rules.coordinates import evaluate as coordinate_findings
    from prechips.rules.coordinates import faced_aims, revolved_located
    from prechips.rules.geometry_common import (
        complete_form_subjects,
        cutting_action,
        finishing_subjects,
    )

    units = bundle.features.get("units", UNKNOWN)
    setups = []
    # The kernel request: a bounded op's printed tables go whole, for the kernel to clip.
    coordinates = {
        finding.subject: finding.numbers for finding in coordinate_findings(bundle, pre_kernel=True)
    }
    finishing = finishing_subjects(bundle)
    complete = complete_form_subjects(bundle)
    for setup in bundle.plan["setups"]:
        frame = setup_frame(bundle, setup)
        transformed = {key: frame.get(key, UNKNOWN) for key in ("origin", "x", "y", "z")}
        if units not in {"mm", "in"} or not all(
            isinstance(value, list) and len(value) == 3 and all(number(v) for v in value)
            for value in transformed.values()
        ):
            transformed = UNKNOWN
        elif units == "in":
            transformed["origin"] = [value * 25.4 for value in transformed["origin"]]
        setups.append(
            {
                "id": setup["id"],
                "frame": transformed,
                "hold": hold_inputs(bundle, setup),
                "ops": [
                    op_inputs(bundle, setup, op, finishing, complete, coordinates.get(setup["id"]))
                    for op in setup["ops"]
                    if cutting_action(op) is not False or op.get("do") in HAND_FINISH
                ],
                "stock_in": setup.get("stock_in", UNKNOWN),
                "render": setup_annotations(bundle, setup, coordinates.get(setup["id"], {})),
                "joint": setup_joint(bundle, setup),
                # A lathe setup's spindle axis is setup Z: rotating fixture solids revolve.
                "machine_kind": record(resolve(bundle, "machines", setup.get("machine"))).get(
                    "kind", UNKNOWN
                ),
                # Located features with neither ``at`` nor a parent locator: the engine
                # measures their faces of revolution about setup Z in any setup (a turning
                # setup measures every feature) so the axis through X0 Y0 can locate them.
                "locate_revolved": revolved_located(setup, bundle.feature_definitions),
                # The features whose faces stock_state's top_z / bottom_z name: the engine
                # gives their heights and the entering stock's over them (consistency).
                "stock_features": sorted(
                    {
                        name
                        for name in (
                            record(setup.get("stock_state")).get(key)
                            for key in ("top_feature", "bottom_feature")
                        )
                        if isinstance(name, str) and name not in ("", UNKNOWN)
                    }
                ),
            }
        )
    aimed = faced_aims(bundle)
    return {
        "version": 1,
        "step_path": str(Path(bundle.paths["step"]).resolve())
        if "step" in bundle.paths
        else UNKNOWN,
        "step_sha256": bundle.features.get("step_sha256", UNKNOWN),
        "features": {
            name: feature.get("faces", UNKNOWN)
            for name, feature in bundle.features["features"].items()
        },
        "joint_features": primitives_mm(bundle),
        "process_features": process_primitives_mm(bundle),
        "as_is_faces": record(bundle.plan.get("stock")).get("as_is_faces", UNKNOWN),
        # The part the plan cuts: its faced aims move those finished faces.
        **({"aimed_faces": aimed} if aimed else {}),
        "stock": stock_inputs(bundle),
        "setups": setups,
    }


def _vector(value):
    return isinstance(value, list) and len(value) == 3 and all(number(v) for v in value)


def stock_inputs(bundle):
    """Authored model-frame supplies; each component keeps its own geometry debt."""
    stock = record(bundle.plan.get("stock"))
    if not stock:
        return {"reason": "plan stock is unknown; in-process stock cannot be derived"}
    components = stock.get("components", UNKNOWN)
    if isinstance(components, list) and components:
        return {
            "components": {component["id"]: _stock_envelope(component) for component in components}
        }
    return _stock_envelope(stock)


def _stock_envelope(stock):
    """One box/round supply's explicit dimensions and placement, never a STEP substitute."""
    section, dia = stock.get("section_mm", UNKNOWN), stock.get("dia_mm", UNKNOWN)
    if section != UNKNOWN and dia != UNKNOWN:
        return {"reason": "stock declares both section_mm and dia_mm; its envelope is ambiguous"}
    shape = "box" if section != UNKNOWN else "round" if dia != UNKNOWN else None
    if shape is None:
        return {"reason": "stock declares neither section_mm nor dia_mm; no envelope is authored"}
    result = {"shape": shape}
    missing = []
    length = stock.get("length_mm", UNKNOWN)
    if number(length) and length > 0:
        result["length_mm"] = length
    else:
        missing.append("length_mm")
    if shape == "box":
        if (
            isinstance(section, list)
            and len(section) == 2
            and all(number(v) and v > 0 for v in section)
        ):
            result["section_mm"] = section
        else:
            missing.append("section_mm")
    elif number(dia) and dia > 0:
        result["dia_mm"] = dia
    else:
        missing.append("dia_mm")
    for key in ("origin_mm", "axis") + (("section_axis",) if shape == "box" else ()):
        value = stock.get(key, UNKNOWN)
        if _vector(value):
            result[key] = value
        else:
            missing.append(key)
    if missing:
        return {
            "reason": f"{shape} stock placement/dimensions undeclared: "
            + ", ".join(missing)
            + "; in-process stock cannot be derived"
        }
    return result


_ENGINE_OP = (
    "subject",
    "do",
    "cut_plane",
    "kerf_mm",
    "feature",
    "faces",
    "joint_cut",
    "process_cut",
    "finishing",
    "hole",
    "radius_mm",
    "flute_len_mm",
    "holder_radius_mm",
    "holder_gauge_len_mm",
    "projection_mm",
    "shank_radius_mm",
    "shank_from_mm",
    "to_z",
    "checkpoints",
    "rough_allowance_mm",
    "stock_removal_bounds",
    "keep_out",
    "keep_out_passes",
    "approach",
    "z_from",
    "z_to",
    "angle_window_deg",
    "max_filing_stock_mm",
    "guide_owner",
    "to_dia_mm",
    *TURNING_TOOL_KEYS,
    *TURNING_HOLDER_KEYS,
    "corners",
    *TURNING_BLADE_KEYS,
)
_ENGINE_HOLD = (
    "fixed_jaw",
    "jaws_along",
    "jaw_above_parallels_mm",
    "jaw_center_along_mm",
    "parallels_centres_mm",
    "jaw_height_mm",
    "jaw_width_mm",
    "jaw_depth_mm",
    "parallels_height_mm",
    "parallels_length_mm",
    "parallels_width_mm",
    "parallels_along",
    "riser",
    "jaw_bar",
    "jaw_buttons",
)
# Vise inputs whose absence stops jaw placement in the engine.
_ENGINE_HOLD_REQUIRED = (
    "fixed_jaw",
    "jaws_along",
    "jaw_above_parallels_mm",
    "jaw_height_mm",
    "jaw_width_mm",
    "jaw_depth_mm",
    "parallels_height_mm",
)
_ENGINE_CHUCK = (
    "jaws",
    "pose",
    "jaw_clock_deg",
    "grip_mm",
    *(dimension + "_mm" for dimension in _CHUCK_DIMS),
    "centre",
    "head_solids",
)
_ENGINE_COMMON = (
    "parallels_ref",
    "parallels_height_mm",
    "parallels_length_mm",
    "parallels_width_mm",
    "parallels_centres_mm",
    "parallels_along",
    "clamps",
    "clamp_debts",
    "stop",
    "debts",
    "gaps",
    "follow_rests",
    "steady_rests",
)


def _engine_hold(hold):
    """The kernel's view of one hold: kind-specific placement plus drawn accessories."""
    kind = hold["kind"]
    common = {key: hold[key] for key in _ENGINE_COMMON if key in hold}
    if kind == "vise":
        result = {"kind": "vise", "fixture_kind": "vise", **common}
        result.update(
            {key: hold[key] for key in _ENGINE_HOLD if key in hold and hold[key] != UNKNOWN}
        )
        missing = [key for key in _ENGINE_HOLD_REQUIRED if key not in result]
        if missing:
            result["reason"] = "Fixture pose/dimensions unmeasured or unavailable: " + ", ".join(
                missing
            )
        elif "jaw_bar_reason" in hold or "jaw_buttons_reason" in hold:
            result["reason"] = "; ".join(
                hold[key] for key in ("jaw_bar_reason", "jaw_buttons_reason") if key in hold
            )
        return result
    if kind in _CHUCK_JAWS or kind == "dividing_head":
        result = {"kind": "chuck", "fixture_kind": kind, **common}
        result.update({key: hold[key] for key in _ENGINE_CHUCK if key in hold})
    elif "solids" in hold:
        result = {"kind": "solids", "fixture_kind": kind, **common}
        result.update({key: hold[key] for key in ("pose", "solids") if key in hold})
    else:
        return {"kind": kind, "fixture_kind": kind, **common, "reason": hold.get("reason")}
    if hold.get("reason"):
        result["reason"] = hold["reason"]
    return result


def engine_job(job):
    """Only the fields freecad_job.py reads; host-only inputs never key the geometry cache."""
    return {
        "version": job["version"],
        "step_path": job["step_path"],
        "step_sha256": job["step_sha256"],
        "features": job["features"],
        "joint_features": job.get("joint_features", {}),
        "process_features": job.get("process_features", {}),
        "as_is_faces": job["as_is_faces"],
        **({"aimed_faces": job["aimed_faces"]} if job.get("aimed_faces") else {}),
        "stock": job["stock"],
        "setups": [
            {
                "id": setup["id"],
                "frame": setup["frame"],
                "hold": _engine_hold(setup["hold"]),
                "ops": [{key: op[key] for key in _ENGINE_OP if key in op} for op in setup["ops"]],
                "stock_in": setup["stock_in"],
                "joint": setup.get("joint"),
                "machine_kind": setup["machine_kind"],
                "locate_revolved": setup["locate_revolved"],
                "render": setup.get("render", {}),
                "stock_features": setup.get("stock_features", []),
            }
            for setup in job["setups"]
        ],
    }


def _engine_digest():
    digest = hashlib.sha256()
    for path in sorted(Path(__file__).parent.glob("*.py")):
        digest.update(path.name.encode())
        digest.update(path.read_bytes())
    return digest.hexdigest()


def _cache_path(key):
    base = os.environ.get("PRECHIPS_KERNEL_CACHE")
    root = (
        Path(base)
        if base
        else Path(os.environ.get("LOCALAPPDATA", Path.home() / ".cache")) / "prechips" / "geometry"
    )
    return root / (key + ".json")


def _valid_result(value):
    return isinstance(value, dict) and value.get("status") in {"ok", "unknown", "error"}


def _execute(executable, job):
    with tempfile.TemporaryDirectory(prefix="prechips-kernel-") as directory:
        source = Path(directory) / "input.json"
        target = Path(directory) / "output.json"
        source.write_text(_json(job), encoding="utf-8")
        process = subprocess.run(
            [
                str(executable),
                str(Path(__file__).with_name("freecad_job.py")),
                "--",
                str(source),
                str(target),
            ],
            capture_output=True,
            text=True,
            errors="replace",
            timeout=600,  # runaway guard: about twice the heaviest example's cold batch
        )
        if process.returncode:
            detail = (process.stderr or process.stdout).strip()
            return {
                "status": "error",
                "reason": f"FreeCAD kernel exited {process.returncode}: {detail}",
            }
        try:
            result = json.loads(target.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            return {"status": "error", "reason": f"FreeCAD kernel did not return valid JSON: {exc}"}
        if _valid_result(result) and result["status"] == "error":
            return result
        if (
            isinstance(result, dict)
            and isinstance(result.get("results"), list)
            and all(_valid_result(value) for value in result["results"])
        ):
            return result
        return {
            "status": "error",
            "reason": "FreeCAD kernel returned an invalid batch result contract.",
        }


def _read_cache(path):
    try:
        cached = json.loads(path.read_text(encoding="utf-8"))
        return cached if _valid_result(cached) and cached["status"] == "ok" else None
    except (OSError, ValueError):
        return None


def _write_cache(path, result):
    if result.get("status") != "ok":
        return
    temporary = None
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=path.parent, delete=False
        ) as stream:
            temporary = Path(stream.name)
            stream.write(_json(result))
        os.replace(temporary, path)
    except OSError:
        # Cache availability cannot change machining findings.
        pass
    finally:
        if temporary is not None:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass


def _timing_attributes(timing, source):
    prefix = "kernel.original_" if source == "cache" else "kernel."
    return {prefix + name: timing[name] for name in ("wall_ms", "cpu_ms") if name in timing}


def _export_timing(active, result, source):
    """Export measured facts, not synthetic spans of past native execution."""
    if active is None:
        return
    provenance = {"kernel.timing_source": source, "kernel.executed": source == "execution"}
    for setup_id, timing in result.get("timing", {}).get("setups", {}).items():
        attrs = {**provenance, **_timing_attributes(timing, source)}
        for phase, measured in timing.get("phases", {}).items():
            attrs.update(
                {
                    name.replace("kernel.", f"kernel.{phase}.", 1): value
                    for name, value in _timing_attributes(measured, source).items()
                }
            )
        with active.span("kernel.setup", setup_id=setup_id, **attrs):
            for subject, measured in timing.get("ops", {}).items():
                with active.span(
                    "kernel.op",
                    setup_id=setup_id,
                    subject=subject,
                    **provenance,
                    **_timing_attributes(measured, source),
                ):
                    pass


def run_geometries(bundles):
    """Prewarm all candidates in one FreeCAD batch, reusing per-job content caches."""
    from prechips import telemetry

    bundles = list(bundles)
    pending = [bundle for bundle in bundles if getattr(bundle, "kernel", None) is None]
    if not pending:
        return [bundle.kernel for bundle in bundles]
    active = telemetry.current()
    with (
        active.span("kernel.geometry", candidates=len(pending)) if active else nullcontext()
    ) as geometry_span:
        executable = discover_kernel()
        if executable is None:
            result = {
                "status": "unknown",
                "kernel_unavailable": True,
                "reason": "FreeCAD kernel unavailable; install FreeCAD or set FREECAD_CMD.",
            }
            for bundle in pending:
                object.__setattr__(bundle, "kernel", dict(result))
        else:
            jobs = []
            targets = []
            keys = {}
            cached_keys = set()
            identity = None
            try:
                executable = Path(executable)
                stat = executable.stat()
                identity = {
                    "path": str(executable.resolve()),
                    "sha256": hashlib.sha256(executable.read_bytes()).hexdigest(),
                    "size": stat.st_size,
                    "mtime_ns": stat.st_mtime_ns,
                }
                engine = _engine_digest()
            except OSError as exc:
                for bundle in pending:
                    object.__setattr__(
                        bundle,
                        "kernel",
                        {"status": "error", "reason": f"Cannot identify FreeCAD kernel: {exc}"},
                    )
            if identity is not None:
                for bundle in pending:
                    job = engine_job(build_job(bundle))
                    if job["step_path"] == UNKNOWN or job["step_sha256"] == UNKNOWN:
                        object.__setattr__(
                            bundle,
                            "kernel",
                            {
                                "status": "unknown",
                                "reason": "STEP bytes and their manifest SHA-256 are "
                                "required for FreeCAD geometry.",
                            },
                        )
                        continue
                    try:
                        actual = hashlib.sha256(Path(job["step_path"]).read_bytes()).hexdigest()
                    except OSError:
                        object.__setattr__(
                            bundle,
                            "kernel",
                            {
                                "status": "unknown",
                                "reason": "STEP bytes became unavailable before "
                                "geometry evaluation.",
                            },
                        )
                        continue
                    if actual != job["step_sha256"]:
                        object.__setattr__(
                            bundle,
                            "kernel",
                            {
                                "status": "unknown",
                                "reason": "STEP bytes do not match the manifest SHA-256; "
                                "face identity is unresolved.",
                            },
                        )
                        continue
                    normalized = {name: value for name, value in job.items() if name != "step_path"}
                    key = hashlib.sha256(
                        _json({"job": normalized, "engine": engine, "kernel": identity}).encode()
                    ).hexdigest()
                    path = _cache_path(key)
                    cached = _read_cache(path)
                    if cached is not None:
                        object.__setattr__(bundle, "kernel", cached)
                        if key not in cached_keys:
                            _export_timing(active, cached, "cache")
                            cached_keys.add(key)
                    elif key in keys:
                        targets[keys[key]][1].append(bundle)
                    else:
                        keys[key] = len(jobs)
                        jobs.append(job)
                        targets.append((path, [bundle]))
                if active:
                    geometry_span.set_attributes(
                        {
                            "kernel.executed_jobs": len(jobs),
                            "kernel.cached_jobs": len(cached_keys),
                            "kernel.executed": bool(jobs),
                            "kernel.timing_source": (
                                "mixed"
                                if jobs and cached_keys
                                else "execution"
                                if jobs
                                else "cache"
                                if cached_keys
                                else "none"
                            ),
                        }
                    )
                if jobs:
                    try:
                        response = _execute(executable, {"jobs": jobs, "timing": True})
                    except (OSError, subprocess.SubprocessError) as exc:
                        response = {
                            "status": "error",
                            "reason": f"FreeCAD kernel job failed: {exc}",
                        }
                    if active:
                        geometry_span.set_attributes(
                            {
                                f"kernel.batch.{name}": value
                                for name, value in response.get("timing", {}).items()
                                if name in {"wall_ms", "cpu_ms"}
                            }
                        )
                    results = response.get("results")
                    if not isinstance(results, list) or len(results) != len(jobs):
                        error = (
                            response
                            if response.get("status") == "error"
                            else {
                                "status": "error",
                                "reason": "FreeCAD kernel batch returned the wrong "
                                "number of results.",
                            }
                        )
                        results = [error] * len(jobs)
                    for result, (path, consumers) in zip(results, targets, strict=True):
                        _write_cache(path, result)
                        _export_timing(active, result, "execution")
                        for bundle in consumers:
                            object.__setattr__(bundle, "kernel", dict(result))
    return [bundle.kernel for bundle in bundles]


def run_geometry(bundle):
    """Populate the frozen bundle's non-operative memo once, including unavailable results."""
    return run_geometries([bundle])[0]
