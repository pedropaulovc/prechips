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
from prechips.rules.geometry_common import TURNING_HOLDER_KEYS, TURNING_TOOL_KEYS
from prechips.rules.resolution import (
    WORKHOLDING_CATEGORIES,
    inventory_category,
    number,
    record,
    resolve,
    setup_frame,
)

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
    missing = [
        key
        for key, value in values.items()
        if not number(value) or (key != "feed_z" and value <= 0)
    ]
    insert, entering = values["insert_angle_deg"], values["entering_angle_deg"]
    if number(insert) and number(entering) and insert + entering >= 180:
        # The minor (trailing) edge would lead the nose: no real insert has this shape.
        missing += ["insert_angle_deg", "entering_angle_deg"]
    if number(values["head_len_mm"]) and number(values["projection_mm"]):
        if values["head_len_mm"] > values["projection_mm"]:
            missing.append("head_len_mm")
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


def op_inputs(bundle, setup, op, finishing=None):
    from prechips.joint_features import joint_operation
    from prechips.rules.geometry_common import TURNING, approach, finishing_subjects

    subject = f"{setup['id']}:{op['op']}"
    turned = approach(bundle, setup, op) == TURNING
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
        }
        for key in ("radius_mm", "holder_radius_mm"):
            if number(values[key]):
                values[key] /= 2
        missing = [
            key
            for key, value in values.items()
            if not (number(value) and value > 0) and key != "oal_mm"
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
    if "faces" in op:
        result["faces"] = op["faces"]
    if turned:
        result["approach"] = TURNING
    units = bundle.features.get("units", UNKNOWN)
    scale = {"mm": 1.0, "in": 25.4}.get(units)
    if "to_z" in op:
        # The op's floor in its setup frame bounds the material it removes from the stock.
        result["to_z"] = op["to_z"] * scale if number(op["to_z"]) and scale else UNKNOWN
    if "stock_removal_bounds" in op:
        result["stock_removal_bounds"] = removal_bounds(op["stock_removal_bounds"], units)
    if turned:
        # The declared turned span (setup-frame Z) bounds and extends the revolved removal.
        for key in ("z_from", "z_to"):
            if key in op:
                result[key] = op[key] * scale if number(op[key]) and scale else UNKNOWN
    for key, value in values.items():
        if key not in missing and number(value) and (value > 0 or key == "feed_z"):
            result[key] = value
    if missing:
        result["reason"] = (
            "Selected tool/holder dimensions unmeasured or unavailable: " + ", ".join(missing)
        )
    return result


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
    parallels = measurement_item(bundle, "fixtures", hold.get("parallels"))
    height = _accepted_length(parallels, "height")
    if number(height) and height > 0:
        result["parallels_height_mm"] = height
    else:
        missing.append("parallels_height_mm")
    if missing:
        result["reason"] = "Fixture pose/dimensions unmeasured or unavailable: " + ", ".join(
            missing
        )


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
    result["centre"] = {"name": reference, **values}


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
        solids, missing = _solids(item, f"clamp {index} {reference}")
        debts.extend(missing)
        if solids:
            placed.append({"name": f"clamp {index} {reference}", "pose": pose, "solids": solids})
    gaps.extend(debts)
    if placed:
        result["clamps"] = placed
    if debts:
        result["clamp_debts"] = debts


def _supports_gaps(hold, result, gaps):
    supports = hold.get("supports")
    values = supports if isinstance(supports, list) else [supports]
    drawn = record(result.get("riser")).get("name")
    for value in values:
        reference = record(value).get("ref", UNKNOWN) if isinstance(value, dict) else value
        if reference in _ABSENT or reference == drawn:
            continue
        gaps.append(f"supports {reference!r} has no fixture solid model")


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
    _parallels_inputs(bundle, hold, result)
    _clamp_inputs(bundle, hold, result, gaps)
    # Vise supports sit below the seat (render-only); elsewhere an undrawn support may collide.
    _supports_gaps(hold, result, debts if kind == "vise" else gaps)
    result["debts"], result["gaps"] = debts, gaps
    return result


def build_job(bundle):
    from prechips.joint_features import primitives_mm, setup_joint
    from prechips.rules.geometry_common import cutting_action, finishing_subjects

    units = bundle.features.get("units", UNKNOWN)
    setups = []
    finishing = finishing_subjects(bundle)
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
                    op_inputs(bundle, setup, op, finishing)
                    for op in setup["ops"]
                    if cutting_action(op) is not False
                ],
                "stock_in": setup.get("stock_in", UNKNOWN),
                "joint": setup_joint(bundle, setup),
                # A lathe setup's spindle axis is setup Z: rotating fixture solids revolve.
                "machine_kind": record(resolve(bundle, "machines", setup.get("machine"))).get(
                    "kind", UNKNOWN
                ),
            }
        )
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
        "as_is_faces": record(bundle.plan.get("stock")).get("as_is_faces", UNKNOWN),
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
    "feature",
    "do",
    "faces",
    "joint_cut",
    "radius_mm",
    "flute_len_mm",
    "holder_radius_mm",
    "holder_gauge_len_mm",
    "projection_mm",
    "to_z",
    "stock_removal_bounds",
    "approach",
    "z_from",
    "z_to",
    *TURNING_TOOL_KEYS,
    *TURNING_HOLDER_KEYS,
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
    "debts",
    "gaps",
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
        "as_is_faces": job["as_is_faces"],
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
            timeout=300,
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


def run_geometries(bundles):
    """Prewarm all candidates in one FreeCAD batch, reusing per-job content caches."""
    from prechips import telemetry

    bundles = list(bundles)
    pending = [bundle for bundle in bundles if getattr(bundle, "kernel", None) is None]
    if not pending:
        return [bundle.kernel for bundle in bundles]
    active = telemetry.current()
    with active.span("kernel.geometry", candidates=len(pending)) if active else nullcontext():
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
                    elif key in keys:
                        targets[keys[key]][1].append(bundle)
                    else:
                        keys[key] = len(jobs)
                        jobs.append(job)
                        targets.append((path, [bundle]))
                if jobs:
                    try:
                        response = _execute(executable, {"jobs": jobs})
                    except (OSError, subprocess.SubprocessError) as exc:
                        response = {
                            "status": "error",
                            "reason": f"FreeCAD kernel job failed: {exc}",
                        }
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
                        for bundle in consumers:
                            object.__setattr__(bundle, "kernel", dict(result))
    return [bundle.kernel for bundle in bundles]


def run_geometry(bundle):
    """Populate the frozen bundle's non-operative memo once, including unavailable results."""
    return run_geometries([bundle])[0]
