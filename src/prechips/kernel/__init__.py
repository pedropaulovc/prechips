"""One local FreeCAD job per bundle; only verified, explicit dimensions enter it."""

from __future__ import annotations

import hashlib
import json
import math
import os
import shutil
import signal
import subprocess
import tempfile
import time
from contextlib import nullcontext
from contextvars import ContextVar
from functools import wraps
from pathlib import Path

from prechips.measurements import (
    angle_fact,
    length_debt,
    length_fact,
    limits_fact,
    measurement_entry,
    record_debt,
    record_trusted,
)
from prechips.model import profiled
from prechips.rules._envelope import selected_item, tool_projection
from prechips.rules.geometry_common import (
    TURNING_BLADE_KEYS,
    TURNING_BLADE_KINDS,
    TURNING_HOLDER_KEYS,
    TURNING_TOOL_KEYS,
)
from prechips.rules.resolution import (
    HAND_FED,
    HAND_FINISH,
    hand_fed,
    identity,
    number,
    op_feature,
    projection_holder,
    record,
    resolve,
    rough_leave,
    saw_station,
    saw_tool,
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


# Scoped to one input preparation, never shared across concurrent bundles or native jobs.
_INPUT_DEBTS = ContextVar("kernel_input_debts", default=None)


def _collect_debts(prepare):
    @wraps(prepare)
    def collected(*args, **kwargs):
        state = {"items": {}, "debts": {}, "host_only": set()}
        token = _INPUT_DEBTS.set(state)
        try:
            result = prepare(*args, **kwargs)
            result["measurement_debts"] = [state["debts"][key] for key in sorted(state["debts"])]
            result["refused_fields"] = sorted(state["debts"].keys() - state["host_only"])
            return result
        finally:
            _INPUT_DEBTS.reset(token)

    return collected


def measurement_item(bundle, slot, reference):
    category, key, item = selected_item(bundle, slot, reference)
    state = _INPUT_DEBTS.get()
    if state is not None:
        state["items"][id(item)] = (item, category, key, "")
    return item


def _nested_item(item, field):
    nested = record(record(item).get(field))
    state = _INPUT_DEBTS.get()
    if state is not None and id(item) in state["items"]:
        _, category, key, prefix = state["items"][id(item)]
        state["items"][id(nested)] = (nested, category, key, prefix + field + ".")
    return nested


def _length_debt(item, field, require_measured):
    state = _INPUT_DEBTS.get()
    if state is not None and id(item) in state["items"]:
        _, category, key, prefix = state["items"][id(item)]
        entry = length_debt(item, field, category, key, require_measured=require_measured)
        if entry is not None:
            if prefix:
                canonical = (
                    *prefix.rstrip(".").split("."),
                    *entry["field"],
                )
                display = measurement_entry(
                    category, key, canonical, status=entry["status"], item=item
                )
                entry.update(
                    id=display["id"],
                    field=display["field"],
                    instruction=display["instruction"],
                    cite=[*display["cite"], *entry["cite"]],
                )
            state["debts"][entry["id"]] = entry


def _record_debt(item, value, field, fact=None):
    state = _INPUT_DEBTS.get()
    if state is None or id(item) not in state["items"]:
        return None
    _, category, key, prefix = state["items"][id(item)]
    parts = field if isinstance(field, tuple) else tuple(field.split("."))
    if prefix:
        parts = (*prefix.rstrip(".").split("."), *parts)
    entry = record_debt(value, category, key, parts, require_measured=False, owner=item)
    if entry is None and fact is not None and not fact["verified"]:
        entry = measurement_entry(category, key, parts, item=item)
        entry.update(
            status="missing" if fact["value"] == UNKNOWN else fact["measurement_status"],
            reason=fact["reason"],
        )
    if entry is not None:
        state["debts"][entry["id"]] = entry
    return entry


def _host_only_debt(item, field):
    """A consumed host comparison that cannot change the native geometry payload."""
    state = _INPUT_DEBTS.get()
    if state is not None and id(item) in state["items"]:
        _, category, key, prefix = state["items"][id(item)]
        state["host_only"].add(measurement_entry(category, key, prefix + field, item=item)["id"])


def _projection(bundle, op):
    debts = {}
    result = tool_projection(bundle, op, debts, [], require_measured=False)
    tool = measurement_item(bundle, "tools", op.get("tool"))
    pair, conflict = projection_holder(bundle, tool, op.get("holder"))
    if pair is not None or conflict:
        # OAL is still consumed by reach, but native placement uses the selected pair.
        _host_only_debt(tool, "oal")
    if conflict:
        state = _INPUT_DEBTS.get()
        if state is not None:
            for key, entry in debts.items():
                state["debts"][key] = {**entry, "status": UNKNOWN, "reason": conflict}
    elif pair is not None:
        _length_debt(tool, ("projection", pair), False)
    else:
        _length_debt(tool, "oal", False)
        _length_debt(measurement_item(bundle, "holders", op.get("holder")), "grip", False)
    return result


def _accepted_length(item, field):
    fact = length_fact(item, field, require_measured=False)
    _length_debt(item, field, False)
    return fact["value"] if fact["verified"] else UNKNOWN


def _accepted_angle(item, field):
    fact = angle_fact(item, field, require_measured=False)
    _record_debt(item, record(item).get(field), field, fact)
    return fact["value"] if fact["verified"] else UNKNOWN


def _measured_length(item, field):
    """A positive measured length fact, else unknown (rest jaws and bodies)."""
    fact = length_fact(item, field, require_measured=True)
    _length_debt(item, field, True)
    value = fact["value"] if fact["verified"] else UNKNOWN
    return value if number(value) and value > 0 else UNKNOWN


def _shank_from(tool, values):
    """Height above the tip where the tool's full shank diameter begins, or unknown.

    That is the flute end, except on a combined drill and countersink: its ``angle_deg``
    seat cone cuts from the pilot out to a wider body, so its shank begins where that
    cone reaches the shank diameter. An unknown shank keeps the flute end, which only
    lowers the start of a body whose diameter is itself unknown. An unrepresentable seat
    cone height stays unknown.
    """
    flute, cutter = values["flute_len_mm"], values["radius_mm"]
    shank = values["shank_radius_mm"]
    if not (number(flute) and flute > 0):
        return UNKNOWN
    if not (number(cutter) and number(shank)) or shank <= cutter:
        return flute
    # An absent or unverified seat angle keeps the flute end: it never blocks the
    # placement, so it is not measurement debt here (only a verified value is read).
    fact = angle_fact(tool, "angle_deg", require_measured=False)
    seat = fact["value"] if fact["verified"] else UNKNOWN
    if not number(seat):
        return flute
    if not 0 < seat < 180:
        return UNKNOWN
    tangent = math.tan(math.radians(seat / 2))
    if tangent <= 0:
        return UNKNOWN
    shoulder = flute + (shank - cutter) / tangent
    return shoulder if math.isfinite(shoulder) else UNKNOWN


def _turning_values(bundle, op):
    """Insert, head, shank and toolpost-body facts in mm/degrees, or what is missing."""
    tool = measurement_item(bundle, "tools", op.get("tool"))
    holder = measurement_item(bundle, "holders", op.get("holder"))
    projection = _projection(bundle, op)
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
    # Reach rule: the declared reach, else the radial depth the cutting edge itself spans.
    # A reach is debt only when that edge fallback cannot stand in for it.
    fact = length_fact(tool, "reach", require_measured=False)
    reach = fact["value"] if fact["verified"] else UNKNOWN
    if number(reach) and reach > 0:
        values["flute_len_mm"] = reach
    elif "edge_len_mm" not in missing and "entering_angle_deg" not in missing:
        values["flute_len_mm"] = values["edge_len_mm"] * math.sin(math.radians(entering))
    else:
        _length_debt(tool, "reach", False)
    if "projection_mm" not in missing:
        # Nose to toolpost body: the deepest the holder can stay clear of a wall.
        values["oal_mm"] = values["projection_mm"]
    return values, sorted(set(missing))


@_collect_debts
def op_inputs(bundle, setup, op, finishing=None, complete=None, tables=None):
    """One op's kernel inputs; ``tables`` is its setup's coordinates numbers, whose printed
    cutter-centre checkpoints the kernel checks against the stock model (``checkpoints``)."""
    from prechips.joint_features import joint_operation
    from prechips.process_features import centre_tool, parting_plane, parts_off, process_operation
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
        units = bundle.features.get("units", UNKNOWN)
        # The host's one saw verdict (rules.resolution.saw_tool/saw_station) decides whether
        # the kernel may route this cut's stock: a verified saw on a station that carries it
        # names its kind (a hand saw's straight cut also reports the kept piece's length); a
        # known mismatch is refused; any unresolved tool or machine leaves it unrouted.
        station = saw_station(bundle, setup, op)
        verdict = {
            "fits": saw_tool(bundle, op),
            "wrong_station": "refused",
            "no_vertical_mode": "refused",
        }
        saw_tool_marker = {"saw_tool": verdict.get(station, "unresolved")}
        if "follows" in op:
            # The scribed line's cut takes only its declared region (unknown extent is
            # plan-input debt), clipped to stay its allowance outside a scribed arc; the
            # blade's kerf locates nothing, so no kerf is consumed.
            bounds = op.get("stock_removal_bounds", UNKNOWN)
            profile = scribed_profile(bundle, setup, op)
            return {
                "subject": subject,
                "do": op["do"],
                "follows": op["follows"],
                "allowance_mm": op.get("allowance_mm", UNKNOWN),
                "stock_removal_bounds": {
                    "reason": f"declare stock_removal_bounds for {subject}: the setup-frame "
                    f"region the saw and its offcut take outside the line {op['follows']} "
                    "scribed"
                }
                if bounds == UNKNOWN
                else removal_bounds(bounds, units),
                **({} if profile is None else {"scribed_profile": profile}),
                **saw_tool_marker,
            }
        tool = measurement_item(bundle, "tools", op.get("tool"))
        return {
            "subject": subject,
            "do": op["do"],
            "kerf_mm": _accepted_length(tool, "kerf"),
            "cut_plane": saw_plane(op.get("cut_plane"), units),
            **saw_tool_marker,
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
        projection = _projection(bundle, op)
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
        if op.get("do") in {"spot", "drill", "ream"}:
            tool = measurement_item(bundle, "tools", op.get("tool"))
            _accepted_length(tool, "dia")
            if op.get("do") in {"spot", "drill"}:
                _accepted_angle(tool, "point_angle")
            if joint_cut.get("reason") and (
                not number(joint_cut.get("diameter_mm"))
                or joint_cut.get("point_angle_deg") == UNKNOWN
            ):
                result.setdefault("refusal_reasons", []).append("joint_cut")
        result["joint_cut"] = joint_cut
    process_cut = process_operation(bundle, op)
    if process_cut is not None:
        if op.get("do") == "center_drill" and "reason" not in process_cut:
            # The kernel cuts only the centre the selected tool itself makes, closed by its
            # own accepted pilot point: never an assumed angle.
            binding = centre_tool(bundle, op)
            tool = measurement_item(bundle, "tools", op.get("tool"))
            for field in ("dia", "pilot_len", "shank"):
                _accepted_length(tool, field)
            for field in ("angle_deg", "point_angle"):
                _accepted_angle(tool, field)
            if binding["status"] != "pass":
                process_cut["reason"] = (
                    f"{process_cut['label']} is not the centre tool {op.get('tool')!r} cuts: "
                    + "; ".join(binding["reasons"])
                )
                if binding["status"] == "unknown":
                    result.setdefault("refusal_reasons", []).append("process_cut")
            else:
                process_cut["point_angle_deg"] = binding["tool"]["point_angle_deg"]
                process_cut["body_dia_mm"] = binding["tool"]["body_dia_mm"]
        elif parts_off(bundle, op) and "reason" not in process_cut:
            # The blade parts the disc at to_z: the kernel cuts only a part-off whose end
            # face is that plane and keeps the exposed-end side its axis points into.
            plane = parting_plane(bundle, setup, op)
            if plane["status"] != "pass":
                process_cut["reason"] = (
                    f"{process_cut['label']} is not the face part_off {subject} leaves: "
                    + "; ".join(plane["reasons"])
                )
        elif process_cut.get("kind") == "end_face" and not turned and "reason" not in process_cut:
            process_cut.update(face_sweep(op, tables, bundle.features.get("units", UNKNOWN)))
        elif process_cut.get("kind") == "tooling_hole" and "reason" not in process_cut:
            tooling = _tooling_inputs(bundle, setup, op, process_cut)
            # An unaccepted tool fact is a refused (debt-carrying) input; a missing plan
            # value keeps its own reason.
            if tooling.pop("refused", False):
                result.setdefault("refusal_reasons", []).append("process_cut")
            process_cut.update(tooling)
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
    feature = record(bundle.feature_definitions.get(op_feature(op)))
    # Joint and tooling-hole cuts use transient geometry, never the finished-face bore path.
    if (
        joint_cut is None
        and process_cut is None
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
                entry = before["entry_z"].get(op_feature(op), before["top_z"])
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
                op_feature(op)
            )
            allowance = op.get("exit_mm")
            if number(entry) and number(thickness) and number(allowance) and allowance >= 0:
                result["hole"]["exit_z_mm"] = entry - thickness - allowance
        if op.get("do") in {"spot", "drill"}:
            result["hole"]["point_angle_deg"] = _accepted_angle(tool, "point_angle")
    if "stock_removal_bounds" in op:
        result["stock_removal_bounds"] = removal_bounds(op["stock_removal_bounds"], units)
    if tables is not None and not turned:
        table = table_checkpoints(subject, tables, op["op"], units)
        if table is not None:
            result["checkpoints"] = table
        sweep = tool_paths(op, tables, units)
        if sweep is not None:
            result["tool_paths"] = sweep
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


def _tooling_inputs(bundle, setup, op, cut):
    """What the kernel drills a tooling hole (``process_cut``) with: the selected tool's
    accepted diameter (a drill also its accepted point angle) and, through the stock, the
    op's exit allowance. ``reason`` names the first unaccepted fact; the cut then stays
    unknown, never a nominal stand-in."""
    tool = measurement_item(bundle, "tools", op.get("tool"))
    result = {"diameter_mm": _accepted_length(tool, "dia")}
    if not (number(result["diameter_mm"]) and result["diameter_mm"] > 0):
        return {
            **result,
            "refused": True,
            "reason": f"{cut['label']}: the {op.get('do')} tool diameter is unknown",
        }
    if op.get("do") in {"drill", "spot"}:
        angle = _accepted_angle(tool, "point_angle")
        result["point_angle_deg"] = angle
        if not (number(angle) and 0 < angle < 180):
            return {
                **result,
                "refused": True,
                "reason": f"{cut['label']}: the {op.get('do')} point angle is unknown",
            }
    if op.get("do") == "ream":
        # The lead below the full diameter reaches deeper, as blind_depth prints the tip.
        lead = _accepted_length(tool, "lead")
        result["lead_mm"] = lead
        if not (number(lead) and lead >= 0):
            return {
                **result,
                "refused": True,
                "reason": f"{cut['label']}: the reamer lead is unknown",
            }
    if not cut.get("thru") or op.get("do") == "spot":
        # As blind_depth: the op's depth_mm is the full-diameter depth below the mouth (a
        # spot's: its tip, even in a through hole); the feature's depth only bounds it.
        depth = op.get("depth_mm", UNKNOWN)
        result["op_depth_mm"] = depth
        if not (number(depth) and depth > 0):
            return {
                **result,
                "reason": f"{cut['label']}: op {op['op']} depth_mm in the blind hole is unknown",
            }
    if cut.get("thru") and op.get("do") != "spot":
        # As blind_depth: the authored local thickness plus the exit allowance, never the
        # far side the geometry suggests.
        allowance = op.get("exit_mm", UNKNOWN)
        thickness = record(record(setup.get("stock_state")).get("local_thickness")).get(
            op_feature(op), UNKNOWN
        )
        result["exit_mm"] = allowance
        if not (number(allowance) and allowance >= 0):
            return {
                **result,
                "reason": f"{cut['label']}: op {op['op']} exit_mm through the stock is unknown",
            }
        if not (number(thickness) and thickness > 0):
            return {
                **result,
                "reason": f"{cut['label']}: stock_state.local_thickness.{op.get('feature')} "
                "is unknown, so its through exit is unplanned",
            }
        result["through_mm"] = thickness + allowance
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


def tool_paths(op, tables, units):
    """Every cutter-centre move a milled op's coordinates tables command, in setup-frame mm,
    for the kernel's sweep of the tool and its holder against the holding:
    ``{"paths": [{"xy_mm", "z_mm": [low, high]}], "levels_mm": [low, high], "entry_z_mm"}``,
    the cutter tip anywhere from ``low`` to ``high`` along each path.

    A printed pass or outline (a list ``cutter_centre``) is cut at every one of the op's
    Z levels (``z_levels.levels``, else its ``dro_to_z``), and its cutter stands at each end
    from the lowest level up to where it enters and leaves: the op's start Z (its level
    plan's ``dro_start_z``, else its profile's ``entry_z`` on the DRO grid; never its own
    depth, which would leave the plunge and the holder above it out), and a raster's lift
    Z. A raster is one way: its cutter rapids at the lift Z from each pass's end to the
    next pass's start, and from the last back to the first when another level follows. An
    arc table's rows (dict ``cutter_centre`` rows, ``tables``) reach the kernel as the op's
    ``checkpoints``, clipped there for a bounded op; ``levels_mm`` and ``entry_z_mm`` stand
    them the same way. ``{"reason": ...}`` when a pass, level, start or lift is unknown;
    None when the op prints no cutter-centre path.
    """
    name = op.get("op")
    profiles = [
        profile
        for profile in record(tables).get("profiles", [])
        if isinstance(profile, dict) and profile.get("op") == name
    ]
    if not profiles:
        return None
    scale = {"mm": 1.0, "in": 25.4}.get(units)
    if scale is None:
        return {"reason": f"feature units {units!r} are not mm or in"}
    operation = next(
        (
            record(entry)
            for entry in record(tables).get("operations", [])
            if record(entry).get("op") == name
        ),
        {},
    )
    levels = record(operation.get("z_levels"))
    tips = levels.get("levels") or [operation.get("dro_to_z", UNKNOWN)]
    known = isinstance(tips, list) and all(map(number, tips))
    if levels:
        starts = [levels.get("dro_start_z", UNKNOWN)]
    else:
        # One level: the op starts where its cutter enters, the surface its profile names
        # (its feature's declared entry_z, else the current top) as the DRO shows it, as the
        # traveler prints it (:func:`prechips.rules.level_entry.level_paths`).
        from prechips.rules.coordinates import dro_z

        grid = record(record(tables).get("dro_grid"))
        step, places = grid.get("step"), grid.get("decimals")
        on_grid = number(step) and step > 0 and isinstance(places, int)
        starts = [
            dro_z(profile.get("entry_z", UNKNOWN), (step, places)) if on_grid else UNKNOWN
            for profile in profiles
        ]
    if not (known and all(map(number, starts))):
        return {"reason": f"op {name} Z levels or start Z are unknown"}
    low, high = min(tips) * scale, max(tips) * scale
    entry = max(max(starts) * scale, high)
    paths, printed_tables = [], False
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
            return {"reason": f"op {name} cutter-centre paths are unknown: {why}"}
        centre = profile.get("cutter_centre")
        if isinstance(centre, list) and centre and all(isinstance(row, dict) for row in centre):
            printed_tables = True
            continue
        if isinstance(centre, list) and centre and _xy(centre[0]):
            centre = [centre]  # one path of points, not a list of passes
        if not (
            isinstance(centre, list)
            and centre
            and all(isinstance(path, list) and path and all(map(_xy, path)) for path in centre)
        ):
            return {"reason": f"op {name} cutter-centre paths are unknown"}
        passes = [[[v * scale for v in point] for point in path] for path in centre]
        top = entry
        raster = profile.get("raster")
        if isinstance(raster, dict):
            lift = raster.get("lift_z")
            if not number(lift):
                return {"reason": f"op {name} raster lift Z is unknown"}
            lift *= scale
            top = max(top, lift)
            again = len(tips) > 1
            for k, path in enumerate(passes):
                if k + 1 < len(passes) or again:
                    rapid = [path[-1], passes[(k + 1) % len(passes)][0]]
                    paths.append({"xy_mm": rapid, "z_mm": [lift, lift]})
        for path in passes:
            paths.append({"xy_mm": path, "z_mm": [low, high]})
            for end in dict.fromkeys(map(tuple, (path[0], path[-1]))):
                paths.append({"xy_mm": [list(end)], "z_mm": [low, top]})
    result = {"paths": paths, "levels_mm": [low, high], "entry_z_mm": entry}
    if printed_tables:
        result["tables"] = True
    return result


def _hand_inputs(bundle, setup, op, subject, finishing):
    """A bench file's kernel inputs: its claims and the policy's ``max_filing_stock_mm``,
    the most stock a file takes off its claimed faces; it has no machine cutter or holder.
    A file guided by filing buttons held in this setup names the kit's solids by their
    kernel owner (``guide_owner``), retaining the held item's spelling after resolved
    identity selects it, and the diameter band its rims stand at
    (``guide_rim_dia_mm``): twice the radius band the kit files to worst case over its
    declared stack, proven as the manual-arc rule proves it
    (:func:`prechips.rules.manual_arc.rim_band`: the button OD limits widened by the rim
    centre's shift off the bore axis), so a button drawn at its nominal OD is one of them
    though its bought OD band excludes the nominal. Only a button of the kit, a turned
    solid of that band whose rim lies on the filed surface, is where the file stops;
    ``"unknown"`` when the rule proves no radius (the kit flagged to verify, any stack
    element unknown, a pin that may not enter its seats) or the feature units are unknown,
    so whether the file bears on a kit solid is unknown."""
    from prechips.rules.coordinates import filing_cap
    from prechips.rules.geometry_common import HAND, finishing_subjects
    from prechips.rules.manual_arc import rim_band
    from prechips.rules.resolution import identity

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
    guide = record(op.get("guide"))
    kit = guide.get("buttons")
    hold = record(setup.get("hold"))
    clamps = hold.get("clamps") if isinstance(hold.get("clamps"), list) else []
    key = identity(bundle, kit, "fixtures")
    owner = next(
        (
            _clamp_owner(index, record(clamp).get("ref"))
            for index, clamp in enumerate(clamps, start=1)
            if record(clamp).get("ref") is not None
            and identity(bundle, record(clamp).get("ref"), "fixtures") == key
        ),
        hold.get("fixture")
        if hold.get("fixture") is not None
        and identity(bundle, hold.get("fixture"), "workholding") == key
        else None,
    )
    if isinstance(kit, str) and kit != UNKNOWN and owner is not None:
        result["guide_owner"] = owner
        item = measurement_item(bundle, "fixtures", kit)
        _record_debt(item, item, "verify")
        for field in ("button_dia_limits", "button_bore_limits", "pin_dia_limits"):
            fact = limits_fact(item, field, require_measured=False)
            keys = [field + suffix for suffix in ("_mm", "_in") if field + suffix in item]
            raw = item[keys[0]] if len(keys) == 1 else None
            _record_debt(item, raw, field, fact)
        _accepted_length(item, "button_runout")
        scale = {"mm": 1.0, "in": 25.4}.get(bundle.features.get("units"))
        reach = rim_band(bundle, item, guide.get("bore"), scale) if scale else None
        result["guide_rim_dia_mm"] = [2 * r for r in reach] if reach else UNKNOWN
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


def _exact_arc(arc, scale):
    """``{"exact_arc_mm": {centre, radius}}`` (setup mm) for a path whose rows lie on one
    exact cutter-centre circle (a trammel, #269), else {}."""
    arc = arc if isinstance(arc, dict) else {}
    centre, radius = arc.get("centre"), arc.get("radius")
    if not (
        isinstance(centre, list)
        and len(centre) == 2
        and all(number(v) for v in (*centre, radius))
        and radius > 0
    ):
        return {}
    return {"exact_arc_mm": {"centre": [v * scale for v in centre], "radius": radius * scale}}


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

    Chain drilling also carries ``method`` and internal ``chain_geometry``: exact finite
    offset arcs/joins and walls, a feature-plane-to-setup basis (plan units), and physical
    ``pitch_mm``. The native kernel regenerates bounded holes from these curves, never
    from rounded row chords; the public input schema is unchanged.
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
                point = {
                    "id": name,
                    "xy_mm": xy_mm,
                    "tip_z_mm": tip * scale,
                    "method": path["method"],
                }
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
                    "method": path["method"],
                    "chain_geometry": path["chain_geometry"],
                    **_exact_arc(path.get("exact_arc"), scale),
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


def scribed_profile(bundle, setup, op):
    """The scribed arc a saw that ``follows`` it must stay its allowance outside, in the saw
    setup's axes and mm: ``{"centre_mm", "radius_mm", "remove"}``, ``remove`` the side of the
    circle the saw takes (``"outside"`` when the part lies inside it, else ``"inside"``);
    ``{"reason"}`` when the arc's layout in this setup is unknown; None when the scribed
    feature is no arc (a straight line), whose declared box alone governs."""
    from prechips.rules.coordinates import arc_layout, frame_point, model_point
    from prechips.rules.manual_arc import _arc_feature
    from prechips.rules.resolution import setup_frame

    sid, _, number_ = str(op["follows"]).partition(":")
    scribe = next(
        (
            other
            for each in bundle.plan["setups"]
            if each["id"] == sid
            for other in each["ops"]
            if str(other.get("op")) == number_
        ),
        None,
    )
    name = record(scribe).get("feature")
    feature = record(bundle.feature_definitions.get(name))
    if not _arc_feature(feature):
        return None
    if record(scribe).get("layout") == "ends":
        # An ends-only layout marks a guided sweep's stops: no line for a saw to follow.
        return {"reason": f"the scribe op lays out only {name}'s two ends, not its line"}
    scale = {"mm": 1.0, "in": 25.4}.get(bundle.features.get("units"))
    layout = arc_layout(bundle, setup, name)
    if layout is None or scale is None:
        return {"reason": f"the scribed arc {name}'s layout in setup {setup['id']} is unknown"}
    # The arc lies in its feature frame's XY plane; the kernel clips with a setup-Z
    # cylinder, so that plane must be the saw setup's XY.
    source = record(bundle.features.get("frames")).get(feature.get("frame", "model"))
    base, tip = (
        frame_point(model_point(point, source), setup_frame(bundle, setup))
        for point in ([0.0, 0.0, 0.0], [0.0, 0.0, 1.0])
    )
    axis = [b - a if number(a) and number(b) else UNKNOWN for a, b in zip(base, tip, strict=True)]
    if UNKNOWN in axis or math.hypot(axis[0], axis[1]) > 1e-6:
        return {
            "reason": f"the scribed arc {name} does not lie in setup {setup['id']}'s XY plane, "
            "so its offset cannot clip the saw's removal"
        }
    return {
        "centre_mm": [value * scale for value in layout["centre_setup_xy"]],
        "radius_mm": layout["radius_mm"] * scale,
        "remove": "outside" if layout["convex"] else "inside",
    }


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


def saw_crossings(bundle, setup, op):
    """Where a saw that follows a scribed arc crosses the setup-entry blank's XY outline
    (#335): the saw path, the arc offset by ``allowance_mm`` into the waste, meets the
    blank's sides there, so a cut whose line runs to the blank enters and leaves through
    them at least the allowance outside the line's ends. ``[{"face", "xy"}]`` in setup-frame
    mm along the arc from the ``hold.feed_from`` end when declared (``face`` the side's
    ``"+X"``/``"-X"``/``"+Y"``/``"-Y"``), within the op's ``stock_removal_bounds``; empty when
    the path stays inside the blank; None when the arc, allowance, bounds or the kernel's
    entry box is unknown."""
    profile = record(scribed_profile(bundle, setup, op))
    bounds = removal_bounds(op.get("stock_removal_bounds"), bundle.features.get("units"))
    detail = record(record(record(getattr(bundle, "kernel", None)).get("setups")).get(setup["id"]))
    box = detail.get("stock_bbox_mm")
    centre, radius = profile.get("centre_mm"), profile.get("radius_mm")
    scale = {"mm": 1.0, "in": 25.4}.get(bundle.features.get("units"))
    allowance = op.get("allowance_mm")
    if (
        "reason" in bounds
        or not (isinstance(box, list) and len(box) == 6 and all(map(number, box)))
        or not (isinstance(centre, list) and number(radius) and number(allowance) and scale)
    ):
        return None
    reach = radius + (-1.0 if profile.get("remove") == "inside" else 1.0) * allowance * scale
    x0, y0, x1, y1 = box[0], box[1], box[3], box[4]
    xs, ys = bounds["x"], bounds["y"]
    found = []
    for axis, value, face in ((0, x0, "-X"), (0, x1, "+X"), (1, y0, "-Y"), (1, y1, "+Y")):
        other = 1 - axis
        offset = value - centre[axis]
        if abs(offset) > reach:
            continue
        half = math.sqrt(reach**2 - offset**2)
        for along in (centre[other] - half, centre[other] + half):
            xy = [value, along] if axis == 0 else [along, value]
            low, high = (y0, y1) if axis == 0 else (x0, x1)
            if not low <= along <= high:
                continue
            if not (xs[0] <= xy[0] <= xs[1] and ys[0] <= xy[1] <= ys[1]):
                continue
            found.append({"face": face, "xy": [round(xy[0], 6), round(xy[1], 6)]})
    # Order along the arc: by angle about the centre, measured from the crossings' mean
    # direction so an arc spanning the +/-180 degree seam still sorts in order.
    middle = math.atan2(
        sum(c["xy"][1] - centre[1] for c in found), sum(c["xy"][0] - centre[0] for c in found)
    )
    found.sort(
        key=lambda c: math.remainder(
            math.atan2(c["xy"][1] - centre[1], c["xy"][0] - centre[0]) - middle, 2 * math.pi
        )
    )
    start = record(setup.get("hold")).get("feed_from")
    if isinstance(start, str) and len(start) == 2 and found:
        index, sign = (0 if start[1] == "X" else 1), (1 if start[0] == "+" else -1)
        if (found[-1]["xy"][index] - found[0]["xy"][index]) * sign > 0:
            found.reverse()
    return found


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
        trusted, _ = record_trusted(solid, require_measured=False)
        if not trusted:
            entry = _record_debt(item, solid, ("solids", name))
            debts.append(entry["id"] if entry is not None else f"{label}: untrusted solid")
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
            # The locating element: a locate clamp proves it bears the way it declares.
            bears = solid.get("bears")
            primitive["locates"] = bears if bears in ("bore", "face") else UNKNOWN
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
    _host_only_debt(fixture, "opening")
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
    # A swivel turns the jaws about setup Z; none (or 0) leaves today's square jaws and
    # their engine input unchanged, while a stated-unknown angle leaves them unplaced.
    swivel = hold.get("jaws_angle_deg")
    if swivel == UNKNOWN:
        missing.append("jaws_angle_deg")
        result["jaws_angle_deg"] = UNKNOWN
    elif number(swivel) and swivel != 0:
        result["jaws_angle_deg"] = swivel
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
        "quill_dia_mm": _positive_length(_nested_item(machine, "tailstock"), "quill_dia"),
    }
    angle = angle_fact(item, "point_angle", require_measured=False)
    _record_debt(item, record(item).get("point_angle"), "point_angle", angle)
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
    # The riser drawn from ``supports`` is that item however the entry spells it.
    riser = identity(bundle, drawn, "fixtures") if drawn is not None else None
    follow, steady = [], []
    for value in values:
        reference = record(value).get("ref", UNKNOWN) if isinstance(value, dict) else value
        if reference in _ABSENT or identity(bundle, reference, "fixtures") == riser:
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


@_collect_debts
def hold_inputs(bundle, setup):
    hold = record(setup.get("hold"))
    if hand_fed(bundle, setup)[0] == "admitted":
        # Fed by hand on the saw table: nothing holds the work, so nothing is drawn or owed.
        reason = "The work is fed by hand on the saw table; no fixture holds it."
        return {"kind": HAND_FED, "method": UNKNOWN, "reason": reason, "debts": [], "gaps": []}
    fixture = measurement_item(bundle, "workholding", hold.get("fixture"))
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


def _inspections_after(setup, sent, render):
    """``render`` with each inspection's route ``position`` replaced by ``after``: the
    subject of the last op sent to the kernel (``sent``) before it in the setup's route,
    or None when none precedes it. The kernel draws the stock as it stands there."""
    for inspection in render.get("inspections", []):
        before = [
            op
            for op in setup["ops"][: inspection.pop("position")]
            if any(op is other for other in sent)
        ]
        inspection["after"] = f"{setup['id']}:{before[-1]['op']}" if before else None
    return render


def _keeps(setup, sent):
    """Each op's ``keep`` in route order as ``{subject, feature, after}``: ``after`` is the
    subject of the last op sent to the kernel at or before it (None when none is), where
    the kernel keeps the piece that carries ``feature`` and discards every other."""
    keeps = []
    for position, op in enumerate(setup["ops"]):
        if "keep" not in op:
            continue
        before = [o for o in setup["ops"][: position + 1] if any(o is other for other in sent)]
        keeps.append(
            {
                "subject": f"{setup['id']}:{op['op']}",
                "feature": op["keep"],
                "after": f"{setup['id']}:{before[-1]['op']}" if before else None,
            }
        )
    return keeps


def build_job(bundle):
    from prechips.joint_features import dia_bands_mm, primitives_mm, setup_joint
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
        sent = [
            op
            for op in setup["ops"]
            if cutting_action(op) is not False or op.get("do") in HAND_FINISH
        ]
        keeps = _keeps(setup, sent)
        setups.append(
            {
                "id": setup["id"],
                "frame": transformed,
                "hold": hold_inputs(bundle, setup),
                "ops": [
                    op_inputs(bundle, setup, op, finishing, complete, coordinates.get(setup["id"]))
                    for op in sent
                ],
                "stock_in": setup.get("stock_in", UNKNOWN),
                **({"keep": keeps} if keeps else {}),
                "render": _inspections_after(
                    setup, sent, setup_annotations(bundle, setup, coordinates.get(setup["id"], {}))
                ),
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
        debts = {
            entry["id"]: entry
            for entry in [
                *setups[-1]["hold"]["measurement_debts"],
                *coordinates.get(setup["id"], {}).get("measurements", []),
            ]
        }
        setups[-1]["measurement_debts"] = [debts[key] for key in sorted(debts)]
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
        "dia_bands": dia_bands_mm(bundle),
        "process_features": process_primitives_mm(bundle),
        "as_is_faces": record(bundle.plan.get("stock")).get("as_is_faces", UNKNOWN),
        # The part the plan cuts: its faced aims move those finished faces.
        **({"aimed_faces": aimed} if aimed else {}),
        "stock": stock_inputs(bundle),
        "setups": setups,
        "measurement_debts": {
            "setups": {setup["id"]: setup["measurement_debts"] for setup in setups},
            "ops": {
                op["subject"]: op["measurement_debts"] for setup in setups for op in setup["ops"]
            },
        },
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
            "components": {
                component["id"]: _stock_envelope(bundle, component, f"stock.{component['id']}")
                for component in components
            }
        }
    return _stock_envelope(bundle, stock, "stock")


def _profiled_envelope(bundle, stock, name):
    """A profiled blank's own STEP solid, authored in model coordinates and bound by its
    declared digest; its vendor tolerance is host-only (rule ``blank_credit``)."""
    path = bundle.paths.get(f"{name}.blank")
    digest = record(stock.get("blank")).get("step_sha256", UNKNOWN)
    missing = [
        field
        for field, value in (("blank.step", path), ("blank.step_sha256", digest))
        if value in (None, UNKNOWN)
    ]
    if missing:
        return {
            "reason": "profiled blank "
            + ", ".join(missing)
            + " undeclared; in-process stock cannot be derived"
        }
    return {"shape": "profiled", "step_path": str(Path(path).resolve()), "step_sha256": digest}


def _stock_envelope(bundle, stock, name):
    """One box/round supply's explicit dimensions and placement, never a STEP substitute;
    a profiled blank is its own cited STEP."""
    if profiled(stock):
        return _profiled_envelope(bundle, stock, name)
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
    "follows",
    "allowance_mm",
    "scribed_profile",
    "saw_tool",
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
    "tool_paths",
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
    "guide_rim_dia_mm",
    "to_dia_mm",
    *TURNING_TOOL_KEYS,
    *TURNING_HOLDER_KEYS,
    "corners",
    *TURNING_BLADE_KEYS,
    "refused_fields",
)
_ENGINE_HOLD = (
    "fixed_jaw",
    "jaws_along",
    "jaw_above_parallels_mm",
    "jaw_center_along_mm",
    "jaws_angle_deg",
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
    "refused_fields",
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
        if hold.get("jaws_angle_deg") == UNKNOWN:
            missing.append("jaws_angle_deg")
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


def _engine_op(op):
    result = {key: op[key] for key in _ENGINE_OP if key in op}
    for key in op.get("refusal_reasons", []):
        result[key] = {
            **result[key],
            "reason": "Refused kernel inputs: " + ", ".join(op["refused_fields"]),
        }
    return result


def engine_job(job):
    """Only the fields freecad_job.py reads; host-only inputs never key the geometry cache."""
    return {
        "version": job["version"],
        "step_path": job["step_path"],
        "step_sha256": job["step_sha256"],
        "features": job["features"],
        "joint_features": job.get("joint_features", {}),
        **({"dia_bands": job["dia_bands"]} if job.get("dia_bands") else {}),
        "process_features": job.get("process_features", {}),
        "as_is_faces": job["as_is_faces"],
        **({"aimed_faces": job["aimed_faces"]} if job.get("aimed_faces") else {}),
        "stock": job["stock"],
        "setups": [
            {
                "id": setup["id"],
                "frame": setup["frame"],
                "hold": _engine_hold(setup["hold"]),
                "ops": [_engine_op(op) for op in setup["ops"]],
                "stock_in": setup["stock_in"],
                **({"keep": setup["keep"]} if setup.get("keep") else {}),
                "joint": setup.get("joint"),
                "machine_kind": setup["machine_kind"],
                "locate_revolved": setup["locate_revolved"],
                "render": setup.get("render", {}),
                "stock_features": setup.get("stock_features", []),
            }
            for setup in job["setups"]
        ],
    }


def _blank_supplies(stock):
    """``(supply, spec)`` for each profiled blank the job's stock declares."""
    if not isinstance(stock, dict):
        return []
    components = stock.get("components")
    pieces = (
        [(f"stock.{name}", spec) for name, spec in components.items()]
        if isinstance(components, dict)
        else [("stock", stock)]
    )
    return [
        (name, spec)
        for name, spec in pieces
        if isinstance(spec, dict) and spec.get("shape") == "profiled"
    ]


def _blank_mismatch(job):
    """Why a profiled blank's STEP bytes are not the ones its declared digest names."""
    for name, spec in _blank_supplies(job["stock"]):
        try:
            actual = hashlib.sha256(Path(spec["step_path"]).read_bytes()).hexdigest()
        except OSError:
            return f"Profiled blank {name} STEP bytes became unavailable before geometry."
        if actual != spec["step_sha256"]:
            return (
                f"Profiled blank {name} STEP bytes do not match its step_sha256; the supplied "
                "stock is unverified."
            )
    return None


def _cache_recipe(job):
    """The job as the cache keys it: content digests, never absolute file paths."""

    def bare(spec):
        if isinstance(spec, dict) and spec.get("shape") == "profiled":
            return {key: value for key, value in spec.items() if key != "step_path"}
        return spec

    recipe = {name: value for name, value in job.items() if name != "step_path"}
    stock = recipe["stock"]
    components = stock.get("components") if isinstance(stock, dict) else None
    if isinstance(components, dict):
        recipe["stock"] = {
            **stock,
            "components": {name: bare(spec) for name, spec in components.items()},
        }
        return recipe
    recipe["stock"] = bare(stock)
    return recipe


# The sources freecadcmd executes, relative to this directory: freecad_job.py and its
# transitive local imports.
# Host-only modules (this one, render_inputs.py) stay out, so editing them reuses cached
# geometry; whatever they change in the job already changes its key.
ENGINE_SOURCES = (
    "boolean_pool.py",
    "chain_boundary.py",
    "freecad_job.py",
    "render_diagram.py",
    "render_png.py",
    "step_faces.py",
)


def _engine_digest(root=Path(__file__).parent):
    digest = hashlib.sha256()
    for name in ENGINE_SOURCES:
        digest.update(name.encode())
        digest.update((root / name).read_bytes())
    return digest.hexdigest()


def _kernel_identity(executable):
    """Identify the executed launcher by its resolved path and current content."""
    executable = Path(executable)
    with executable.open("rb") as stream:
        executable_sha256 = hashlib.file_digest(stream, "sha256").hexdigest()
    identity = {
        "path": str(executable.resolve()),
        "sha256": executable_sha256,
    }
    return identity


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


def _await_launcher(process, timeout):
    """Wait up to ``timeout`` seconds for ``process`` to end, else raise TimeoutExpired. On
    POSIX the ended process stays unreaped (WNOWAIT), so its pid, which is also its process
    group's id, cannot name another group until :func:`_run_kernel` has killed that group."""
    if os.name != "posix":
        process.wait(timeout)
        return
    deadline = time.monotonic() + timeout
    delay = 0.0005
    while os.waitid(os.P_PID, process.pid, os.WEXITED | os.WNOHANG | os.WNOWAIT) is None:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise subprocess.TimeoutExpired(process.args, timeout)
        delay = min(delay * 2, remaining, 0.05)  # Popen.wait(timeout)'s own polling
        time.sleep(delay)


# Runaway guard on one FreeCAD batch, in seconds: about twice the heaviest example's cold
# batch. That is rocker-arm, measured at 525 s cold on a 4-vCPU host with one pool worker
# (issue #329), and nearly all of it is serial engine CPU, so a slower core stretches it in
# proportion. The guard stops a runaway; it is not a budget a healthy job should approach.
RUNAWAY_GUARD_S = 1200
OUTPUT_TAIL = 2000  # characters of the engine's stderr/stdout an error reason quotes


def _run_kernel(command):
    """``command`` run to its end under the runaway guard; no process of the run outlives it.

    ``command`` (FREECAD_CMD) may be a launcher that runs ``freecadcmd`` as its child
    rather than replacing itself with it: the Linux AppImage's ``AppRun`` shell does. Its
    engine and pool workers can then outlive it, whether the guard or the host's interrupt
    kills only the launcher or the launcher dies on its own. On POSIX the run therefore has
    its own session, whose process group every process of the run inherits, and once the
    launcher has ended, or the guard expires, or the host is interrupted, that group is
    killed before the launcher is reaped. Output goes to files, so nothing reaps the launcher
    while it is waited for. On Windows ``command`` is the engine, and its job object ends
    its workers (boolean_pool). When the guard expires, the raised ``TimeoutExpired``
    carries the run's stdout and stderr."""
    posix = os.name == "posix"
    with (
        tempfile.TemporaryFile("w+", errors="replace") as stdout,
        tempfile.TemporaryFile("w+", errors="replace") as stderr,
        subprocess.Popen(command, stdout=stdout, stderr=stderr, start_new_session=posix) as process,
    ):
        expired = None
        try:
            _await_launcher(process, RUNAWAY_GUARD_S)
        except subprocess.TimeoutExpired as exc:
            expired = exc
        finally:
            if posix:
                os.killpg(process.pid, signal.SIGKILL)
            elif process.returncode is None:
                process.kill()
        process.wait()
        stdout.seek(0)
        stderr.seek(0)
        out, err = stdout.read(), stderr.read()
        if expired is not None:
            raise subprocess.TimeoutExpired(process.args, expired.timeout, output=out, stderr=err)
        return subprocess.CompletedProcess(process.args, process.returncode, out, err)


def _exit_text(code):
    """How the launcher ended: a negative code is the signal that killed it, and on POSIX a
    launcher shell (the AppImage's AppRun) reports a child killed by signal N as 128 + N."""
    number = -code if code < 0 else code - 128 if code > 128 and os.name == "posix" else None
    try:
        name = signal.Signals(number).name if number is not None else None
    except ValueError:
        name = None
    if name is None:
        return f"exited {code}"
    hint = " (often the host's out-of-memory killer)" if name == "SIGKILL" else ""
    return f"exited {code}: killed by {name}{hint}"


def _output_tail(stdout, stderr):
    for name, text in (("stderr", stderr), ("stdout", stdout)):
        if isinstance(text, bytes):
            text = text.decode(errors="replace")
        text = (text or "").strip()
        if text:
            clipped = "..." + text[-OUTPUT_TAIL:] if len(text) > OUTPUT_TAIL else text
            return f"{name} tail: {clipped}"
    return "no stderr or stdout output"


def _read_trail(path):
    """The engine's progress trail (``freecad_job._mark``): the phases it entered and has
    not left, deepest last, and the last phases it finished, each with engine-clock ms."""
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return None
    entered, finished = {}, []
    for line in lines:
        try:
            mark = json.loads(line)
            at, event, ms = mark["at"], mark["event"], mark["ms"]
        except (ValueError, TypeError, KeyError):
            continue  # a line the kill cut short
        if event == "enter":
            entered[at] = ms
        elif event == "exit" and at in entered:
            finished.append({"at": at, "wall_ms": mark.get("wall_ms"), "ms": ms})
            del entered[at]
    if not lines:
        return None
    return {
        "open": [{"at": at, "entered_ms": ms} for at, ms in entered.items()],
        "finished": finished[-20:],
        "last_mark_ms": max([0, *entered.values(), *(item["ms"] for item in finished)]),
    }


def _failure(reason, started, trail_path, stdout=None, stderr=None):
    """An error result whose reason says what failed, what the engine printed and, from its
    progress trail, which phase it was in; ``timing`` keeps the host wall time and trail."""
    trail = _read_trail(trail_path)
    timing = {"host_wall_ms": round((time.perf_counter() - started) * 1000, 3)}
    if trail is None:
        where = "the engine recorded no progress"
    elif trail["open"]:
        deepest = trail["open"][-1]
        where = (
            f"the engine was in {deepest['at']} (entered at "
            f"{deepest['entered_ms'] / 1000:.1f} s, last mark at "
            f"{trail['last_mark_ms'] / 1000:.1f} s of engine time)"
        )
    else:
        where = (
            f"the engine had finished every phase it entered ({trail['last_mark_ms'] / 1000:.1f} s)"
        )
    if trail is not None:
        timing["trail"] = trail
    parts = [reason, where]
    if stdout is not None or stderr is not None:
        parts.append(_output_tail(stdout, stderr))
    return {"status": "error", "reason": "; ".join(parts), "timing": timing}


def _reasoned(result, fallback):
    """``result``, with ``fallback`` as its reason when it is an error that names none."""
    if not isinstance(result, dict) or result.get("status") != "error":
        return result
    reason = result.get("reason")
    if isinstance(reason, str) and reason.strip():
        return result
    return {**result, "reason": fallback}


def _execute(executable, job):
    with tempfile.TemporaryDirectory(prefix="prechips-kernel-") as directory:
        source = Path(directory) / "input.json"
        target = Path(directory) / "output.json"
        trail = Path(directory) / "output.json.trail"  # freecad_job.main's progress trail
        source.write_text(_json(job), encoding="utf-8")
        started = time.perf_counter()
        try:
            process = _run_kernel(
                [
                    str(executable),
                    str(Path(__file__).with_name("freecad_job.py")),
                    "--",
                    str(source),
                    str(target),
                ]
            )
        except subprocess.TimeoutExpired as exc:
            reason = f"FreeCAD kernel exceeded the {exc.timeout:g} s runaway guard and was killed"
            return _failure(reason, started, trail, exc.output, exc.stderr)
        output = process.stdout, process.stderr
        if process.returncode:
            reason = f"FreeCAD kernel {_exit_text(process.returncode)}"
            return _failure(reason, started, trail, *output)
        try:
            text = target.read_text(encoding="utf-8")
        except FileNotFoundError:
            reason = "FreeCAD kernel exited 0 without writing its result file"
            return _failure(reason, started, trail, *output)
        except (OSError, UnicodeDecodeError) as exc:
            reason = f"FreeCAD kernel result file is unreadable: {exc}"
            return _failure(reason, started, trail, *output)
        if not text.strip():
            return _failure("FreeCAD kernel wrote an empty result file", started, trail, *output)
        try:
            result = json.loads(text)
        except ValueError as exc:
            reason = f"FreeCAD kernel did not return valid JSON: {exc}"
            return _failure(reason, started, trail, *output)
        host_wall_ms = round((time.perf_counter() - started) * 1000, 3)
        if _valid_result(result) and result["status"] == "error":
            # The engine's own reason leads; the host adds the phase, output and timing.
            reason = _reasoned(result, "FreeCAD kernel reported a batch error without a reason")
            return {**result, **_failure(reason["reason"], started, trail, *output)}
        if (
            isinstance(result, dict)
            and isinstance(result.get("results"), list)
            and all(_valid_result(value) for value in result["results"])
        ):
            result["results"] = [
                _reasoned(
                    value, f"FreeCAD kernel reported job {index} as an error without a reason"
                )
                for index, value in enumerate(result["results"])
            ]
            timing = result.get("timing")
            if isinstance(timing, dict):
                timing["host_wall_ms"] = host_wall_ms
            return result
        return _failure(
            "FreeCAD kernel returned an invalid batch result contract", started, trail, *output
        )


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


def run_geometries(bundles, jobs=None):
    """Prewarm all candidates in one FreeCAD batch, reusing per-job content caches.

    ``jobs``, when given, are the bundles' :func:`build_job` results in order, already
    built by the caller; otherwise each pending bundle's job is built here."""
    from prechips import telemetry

    bundles = list(bundles)
    pending = [bundle for bundle in bundles if getattr(bundle, "kernel", None) is None]
    if not pending:
        return [bundle.kernel for bundle in bundles]
    built = {} if jobs is None else dict(zip(map(id, bundles), jobs, strict=True))
    prepared = {
        id(bundle): built[id(bundle)] if id(bundle) in built else build_job(bundle)
        for bundle in pending
    }
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
                engine = _engine_digest()
                identity = _kernel_identity(executable)
            except OSError as exc:
                for bundle in pending:
                    object.__setattr__(
                        bundle,
                        "kernel",
                        {"status": "error", "reason": f"Cannot identify FreeCAD kernel: {exc}"},
                    )
            if identity is not None:
                for bundle in pending:
                    job = engine_job(prepared[id(bundle)])
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
                    # The key carries each blank's declared digest, so its bytes must
                    # still be the ones that digest names.
                    mismatch = _blank_mismatch(job)
                    if mismatch is not None:
                        object.__setattr__(
                            bundle, "kernel", {"status": "unknown", "reason": mismatch}
                        )
                        continue
                    key = hashlib.sha256(
                        _json(
                            {"job": _cache_recipe(job), "engine": engine, "kernel": identity}
                        ).encode()
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
                        timing = response.get("timing", {})
                        attributes = {
                            f"kernel.batch.{name}": value
                            for name, value in timing.items()
                            if name in {"wall_ms", "cpu_ms", "host_wall_ms"}
                        }
                        if response.get("status") == "error":
                            attributes["kernel.batch.error"] = response["reason"]
                            open_phases = timing.get("trail", {}).get("open")
                            if open_phases:
                                attributes["kernel.batch.open_phase"] = open_phases[-1]["at"]
                        geometry_span.set_attributes(attributes)
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
    for bundle in pending:
        object.__setattr__(
            bundle,
            "kernel",
            {**bundle.kernel, "measurement_debts": prepared[id(bundle)]["measurement_debts"]},
        )
    return [bundle.kernel for bundle in bundles]


def run_geometry(bundle):
    """Populate the frozen bundle's non-operative memo once, including unavailable results."""
    return run_geometries([bundle])[0]
