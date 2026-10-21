"""Plan-owned transient stock-preparation features: a faced stock end, a centre hole and a
tooling (locating) hole in the work's own waste.

Process features resolve once into the operative feature mapping
(``Bundle.feature_definitions``) with their own kinds (``end_face``, ``centre_hole``) and no
drawing requirements; a ``tooling_hole`` resolves as a standard ``hole`` (its ``dia`` band,
``thru`` or ``depth``) whose ``preparation`` identity names it. Operation rules (speeds and
feeds, tip endpoints, accessibility, headroom) resolve their ops like any feature's. They
are never finished drawing surfaces: no exported face maps to them, they earn no drawing
coverage or finishing credit, and the kernel removes their analytic solids from the stock
when their op runs, so later setups hold the faced end, the cut centre and the tooling hole
(until a waste cut takes it). Kernel payloads are normalised to millimetres here;
numeric unknowns stay debt.
"""

from __future__ import annotations

import math
from typing import Any

from prechips.inputs import BadInput
from prechips.material_routes import MaterialGraph, feature_material_status, route_identities_known
from prechips.model import UNKNOWN, setup_lineage

LABEL_PREFIX = "plan.process_features."
# The one public name for plan-authored stock preparation, kept apart from drawing acceptance.
PROCESS_PREP_LABEL = "STOCK PREPARATION — plan only, not a drawing dimension"
# The actions that make each kind. A centre is drilled with a combined drill and
# countersink; an end face is faced to the axis, parted off on a lathe (the parted end a
# later setup faces to length), or on a mill side-milled with the cutter's periphery (a
# blank end overhanging the vise). A cut_to_fit keeps the chuck side and drops the free
# end, the opposite of a part-off, so it makes none.
ACTIONS = {
    "end_face": frozenset(
        {
            "face",
            "rough_face",
            "finish_face",
            "part_off",
            "profile",
            "rough_profile",
            "finish_profile",
        }
    ),
    "centre_hole": frozenset({"spot", "center_drill"}),
    # A tooling hole is spotted, drilled and reamed when its band needs it: the ream
    # finishes the band, the drill roughs it (``sizing`` judges the finishing tool against
    # ``dia``) and the spot only starts it, cutting its own point.
    "tooling_hole": frozenset({"spot", "drill", "ream"}),
}
_CENTRE_KEYS = ("drill_dia_mm", "drill_length_mm", "mouth_dia_mm", "countersink_angle_deg")
# The selected combined drill and countersink's own fact behind each centre size
# (Machinery's Handbook Table 6: drill D, drill length C, the countersink angle and body A)
# and the pilot point that closes the drilled centre.
_TOOL_FACTS = {
    "drill_dia_mm": "dia",
    "drill_length_mm": "pilot_len",
    "countersink_angle_deg": "angle_deg",
    "body_dia_mm": "shank",
    "point_angle_deg": "point_angle",
}
# Authored included angles agree exactly, up to float residue.
ANGLE_TOLERANCE_DEG = 1e-9
_SCALE = {"mm": 1.0, "in": 25.4}


def label(name: str) -> str:
    return LABEL_PREFIX + name


def process_of(definition: Any) -> dict | None:
    """The process identity of an operative feature definition, or None otherwise.

    It lives under ``preparation``: a manifest feature's own ``process`` (``"ream"``)
    names how a drawing feature is finished, not plan stock preparation.
    """
    return definition.get("preparation") if isinstance(definition, dict) else None


def source_cite(definition: Any) -> list[str]:
    """Plan-owned source identity for a process feature; empty for other features."""
    process = process_of(definition)
    return [f"{process['label']}: {PROCESS_PREP_LABEL}"] if process else []


def _number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _stock_box(plan: dict, scale: float | None) -> list[list[float]] | None:
    """The rectangular root stock's model-axis box in manifest units, else None (round,
    built-up, unknown or not aligned with the model axes)."""
    stock = plan.get("stock") if isinstance(plan.get("stock"), dict) else {}
    origin, section = stock.get("origin_mm"), stock.get("section_mm")
    axis, across, length = stock.get("axis"), stock.get("section_axis"), stock.get("length_mm")
    vectors = (origin, axis, across)
    if scale is None or stock.get("components") or "dia_mm" in stock:
        return None
    if not all(isinstance(v, list) and len(v) == 3 and all(map(_number, v)) for v in vectors):
        return None
    if not (isinstance(section, list) and len(section) == 2 and all(map(_number, section))):
        return None
    if not _number(length):
        return None
    third = [
        axis[1] * across[2] - axis[2] * across[1],
        axis[2] * across[0] - axis[0] * across[2],
        axis[0] * across[1] - axis[1] * across[0],
    ]
    box = [[origin[i], origin[i]] for i in range(3)]
    for vector, size in zip((axis, across, third), (length, *section), strict=True):
        hits = [i for i in range(3) if abs(abs(vector[i]) - 1.0) <= 1e-9]
        if len(hits) != 1:
            return None
        i = hits[0]
        box[i][0 if vector[i] < 0 else 1] += vector[i] * size
    return [[low / scale, high / scale] for low, high in box]


def _planar_bounds(feature: dict, box: list[list[float]] | None) -> dict | None:
    """An end face's footprint: the root stock box collapsed onto its plane, for a plane
    square to a model axis; else None (the footprint stays unknown)."""
    at, axis = feature.get("at"), feature.get("axis")
    if box is None or feature["kind"] != "end_face":
        return None
    if not all(isinstance(v, list) and len(v) == 3 and all(map(_number, v)) for v in (at, axis)):
        return None
    hits = [i for i in range(3) if abs(axis[i]) > 1e-9]
    if len(hits) != 1:
        return None
    bounds = {key: list(span) for key, span in zip("xyz", box, strict=True)}
    bounds["xyz"[hits[0]]] = [at[hits[0]], at[hits[0]]]
    return bounds


def feature_definitions(plan: dict, definitions: dict, units: str = UNKNOWN) -> dict[str, dict]:
    """``definitions`` (exported plus joint features) plus resolved plan process features.

    Without process features this is ``definitions`` itself (no copy). A planar end face
    of a rectangular root stock carries ``bounds``: that stock's section in its plane, the
    most its face op can be asked to cover.
    """
    declared = plan.get("process_features") or {}
    if not declared:
        return definitions
    collisions = sorted(set(declared) & set(definitions))
    if collisions:
        raise BadInput(
            f"plan.process_features {', '.join(map(repr, collisions))} collide with manifest "
            "or plan.joint_features names."
        )
    merged = dict(definitions)
    box = _stock_box(plan, _SCALE.get(units))
    for name, feature in declared.items():
        process = {"id": name, "kind": feature["kind"], "label": label(name)}
        process.update({key: feature[key] for key in _CENTRE_KEYS if key in feature})
        tooling = feature["kind"] == "tooling_hole"
        definition = {
            # A tooling hole is a plain hole to every operation rule.
            "kind": "hole" if tooling else feature["kind"],
            "frame": "model",
            "at": feature["at"],
            "axis": feature["axis"],
            # Stock preparation is never a drawing requirement.
            "requirements": [],
            "cite": feature["cite"],
            "preparation": process,
        }
        if tooling:
            definition["dia"] = feature["dia"]
            definition["thru"] = feature.get("thru", False)
            if "depth" in feature:
                definition["depth"] = feature["depth"]
        bounds = _planar_bounds(feature, box)
        if bounds is not None:
            definition["bounds"] = bounds
        for key in ("size", "note"):
            if key in feature:
                definition[key] = feature[key]
        merged[name] = definition
    return merged


def arriving_bounds(bundle, setup: dict, definition: dict) -> dict | None:
    """A process end face's footprint on the stock ``setup`` receives: its root-stock
    ``bounds`` trimmed by each process end face an earlier setup of that stock lineage
    faced on a model-axis plane. Faces it cannot place leave the larger, root footprint."""
    from prechips.rules.resolution import op_feature

    bounds, own = definition.get("bounds"), process_of(definition)
    if not bounds or not own:
        return bounds
    if not route_identities_known(bundle.plan, setup.get("id")):
        # Public rendering may inspect an incomplete setup. Its process footprint is
        # unresolved, while strict complete-plan loading still rejects this identity.
        return None
    # Root-stock bounds are not registered bounds of an independently reposed child.
    if any(atom.path for atom in MaterialGraph(bundle.plan).nodes.get(setup["id"], ())):
        return None
    trimmed = {key: list(span) for key, span in bounds.items()}
    earlier = setup_lineage(bundle.plan, setup["id"]) - {setup["id"]}
    for other in bundle.plan["setups"]:
        if other["id"] not in earlier:
            continue
        for op in other["ops"]:
            made = bundle.feature_definitions.get(op_feature(op))
            process = process_of(made)
            if not process or process["kind"] != "end_face" or process["id"] == own["id"]:
                continue
            if (
                feature_material_status(
                    bundle.plan, setup["id"], other["id"], process["id"], bundle
                )
                is not True
            ):
                continue
            axis, at = made["axis"], made["at"]
            vectors = (axis, at)
            if op.get("do") not in ACTIONS["end_face"] or not all(
                isinstance(v, list) and len(v) == 3 and all(map(_number, v)) for v in vectors
            ):
                continue
            hits = [i for i in range(3) if abs(axis[i]) > 1e-9]
            if len(hits) != 1:
                continue
            span = trimmed["xyz"[hits[0]]]
            if span[0] == span[1]:
                continue  # the face's own plane axis: nothing to trim
            if axis[hits[0]] > 0:
                span[0] = max(span[0], at[hits[0]])
            else:
                span[1] = min(span[1], at[hits[0]])
    return trimmed


def centre_depth_mm(definition: Any) -> dict:
    """A centre hole's feed depth below its faced end, in mm, from its declared sizes.

    The countersink of included angle ``a`` opens from the drill diameter ``D`` to the
    mouth ``M`` over ``(M - D) / 2 / tan(a / 2)``; the pilot's ``drill_length_mm`` (the
    Machinery's Handbook Table 6 drill length C, point included) runs on below it. Any
    unknown size or unrepresentable cone leaves its depth unknown.
    """
    process = process_of(definition) or {}
    drill, length, mouth, angle = (process.get(key, UNKNOWN) for key in _CENTRE_KEYS)
    tangent = math.tan(math.radians(angle / 2)) if _number(angle) else 0.0
    if not all(_number(value) for value in (drill, length, mouth, angle)) or tangent <= 0:
        return {
            "countersink_depth_mm": UNKNOWN,
            "drill_length_mm": length if _number(length) else UNKNOWN,
            "depth_mm": UNKNOWN,
        }
    countersink = (mouth - drill) / 2 / tangent
    depth = countersink + length
    return {
        "countersink_depth_mm": countersink if math.isfinite(countersink) else UNKNOWN,
        "drill_length_mm": length,
        "depth_mm": depth if math.isfinite(depth) else UNKNOWN,
    }


def centre_tool(bundle, op: dict) -> dict:
    """How centre op ``op``'s selected combined drill and countersink fixes its centre.

    A drilled centre is its cutter's own shape: the selected tool's pilot diameter D
    (``dia``), Table 6 drill length C (``pilot_len``: countersink start to tip, point
    included) closed by its pilot point (``point_angle``), and its included countersink
    angle (``angle_deg``), opened no wider than its body diameter A (its ``shank``). The
    process feature must declare exactly those sizes. These are every fact the kernel
    builds the drilled centre from. ``status`` is ``error`` when a declared size differs
    from the tool's, the mouth is wider than its body, or the tool's point is no included
    angle or no shorter than its pilot. Otherwise it is ``unknown`` while a declared size or
    a tool fact is unknown or not accepted, the tool is not in the inventory, or its record
    is unconfirmed (``verify`` or an unknown flag anywhere on it, as every endpoint
    requires). Otherwise it is ``pass``. ``reasons`` explains each, ``tool`` holds the
    accepted facts and ``measurements`` the debt behind each unaccepted one.
    """
    from prechips.measurements import angle_fact, length_fact, measurement_entry
    from prechips.rules._envelope import selected_item
    from prechips.rules.resolution import (
        LENGTH_TOLERANCE_MM,
        op_feature,
        resolve,
        same_length,
        uncertain,
    )
    from prechips.rules.tip_endpoints import drill_point_mm

    process = process_of(bundle.feature_definitions.get(op_feature(op))) or {}
    reference = op.get("tool", UNKNOWN)
    category, tool_key, item = selected_item(bundle, "tools", reference)
    resolved = resolve(bundle, "tools", reference)
    errors, unknown, measurements, tool = [], [], [], {}
    if not resolved:
        unknown.append(f"tool {reference!r} is not in the inventory")
    elif uncertain(resolved):
        unknown.append(f"tool {reference!r} is unconfirmed (verify or unknown on its record)")
    for key, field in _TOOL_FACTS.items():
        read = angle_fact if key.endswith("_deg") else length_fact
        fact = read(item, field, require_measured=False)
        tool[key] = fact["value"] if fact["verified"] else UNKNOWN
        if not fact["verified"]:
            unknown.append(f"tool {reference!r} {field} is not accepted: {fact['reason']}")
            if item:
                measurements.append(
                    measurement_entry(
                        category, tool_key, field, status=fact["measurement_status"], item=item
                    )
                )
    for key in ("drill_dia_mm", "drill_length_mm", "countersink_angle_deg"):
        declared, own = process.get(key, UNKNOWN), tool[key]
        if not _number(declared):
            unknown.append(f"the declared {key} is unknown")
        elif _number(own) and not (
            abs(declared - own) <= ANGLE_TOLERANCE_DEG
            if key == "countersink_angle_deg"
            else same_length(declared, own)
        ):
            errors.append(
                f"the declared {key} {declared:g} is not tool {reference!r}'s "
                f"{_TOOL_FACTS[key]} {own:g}"
            )
    mouth, body = process.get("mouth_dia_mm", UNKNOWN), tool["body_dia_mm"]
    if not _number(mouth):
        unknown.append("the declared mouth_dia_mm is unknown")
    elif _number(body) and mouth > body + LENGTH_TOLERANCE_MM:
        errors.append(
            f"the declared Ø{mouth:g} mouth is wider than tool {reference!r}'s Ø{body:g} body"
        )
    point, drill, pilot = (
        tool[key] for key in ("point_angle_deg", "drill_dia_mm", "drill_length_mm")
    )
    if _number(point) and not 0 < point < 180:
        errors.append(f"tool {reference!r} point_angle {point:g} is no included angle")
    elif _number(point) and _number(drill) and _number(pilot):
        # Table 6 C includes the point: the pilot must run on past it.
        tip = drill_point_mm(drill, point)
        if tip == UNKNOWN:
            unknown.append(
                f"tool {reference!r}'s pilot drill diameter {drill:g} is nonpositive"
                if drill <= 0
                else f"tool {reference!r}'s {point:g}° pilot point cone is unrepresentable"
            )
        elif pilot - tip <= LENGTH_TOLERANCE_MM:
            errors.append(
                f"tool {reference!r}'s {point:g}° pilot point ({tip:g} mm) is not shorter "
                f"than its {pilot:g} mm pilot_len"
            )
    status = "error" if errors else "unknown" if unknown else "pass"
    return {
        "status": status,
        "reasons": errors or unknown,
        "tool": tool,
        "measurements": measurements,
    }


def parts_off(bundle, op: dict) -> bool:
    """Whether ``op`` parts off onto a process end face."""
    if op.get("do") != "part_off" or not isinstance(op.get("feature"), str):
        return False
    process = process_of(bundle.feature_definitions.get(op["feature"])) or {}
    return process.get("kind") == "end_face"


def parting_plane(bundle, setup: dict, op: dict) -> dict:
    """How part-off ``op`` of lathe ``setup`` leaves its process end face.

    The blade parts the disc at ``to_z``, so the end face must be that plane: ``at`` at
    setup Z ``to_z``, and ``axis`` (into the kept material) along the spindle, toward the
    exposed end (+Z), because the part comes off the free end and the remainder stays in
    the chuck with the bar. ``status`` is ``error`` when the axis is not along setup Z,
    points toward the chuck, or ``at`` lies on another Z; ``unknown`` while the machine is
    not known to be a lathe, or the frame, ``at``, ``axis``, ``to_z`` or manifest units
    are unknown; otherwise ``pass``. ``reasons`` explains each; ``face_z`` is ``at``'s
    setup Z (manifest units) when known.
    """
    from prechips.rules.coordinates import frame_point
    from prechips.rules.resolution import op_feature, record, resolve, same_length, setup_frame

    definition = bundle.feature_definitions.get(op_feature(op), {})
    at, axis, to_z = definition.get("at"), definition.get("axis"), op.get("to_z", UNKNOWN)
    scale = _SCALE.get(bundle.features.get("units", UNKNOWN))
    kind = record(resolve(bundle, "machines", setup.get("machine", UNKNOWN))).get("kind")
    errors, unknown, face_z = [], [], UNKNOWN
    if kind != "lathe":
        unknown.append(f"machine {setup.get('machine')!r} is not known to be a lathe")
    vectors = (at, axis)
    if not all(isinstance(v, list) and len(v) == 3 and all(map(_number, v)) for v in vectors):
        unknown.append("its at or axis is unknown")
    else:
        frame = setup_frame(bundle, setup)
        face = frame_point(at, frame)
        ahead = frame_point([a + d for a, d in zip(at, axis, strict=True)], frame)
        if not all(map(_number, face + ahead)):
            unknown.append("its plane in the setup frame is unknown")
        else:
            face_z = face[2]
            normal = [b - a for a, b in zip(face, ahead, strict=True)]
            length = math.sqrt(sum(v * v for v in normal))
            along = normal[2] / length if length else 0.0
            if abs(along) < 1 - 1e-6:
                errors.append(
                    "its axis is not along setup Z, the spindle axis the blade parts square to"
                )
            elif along < 0:
                errors.append(
                    "its axis points toward the chuck (setup -Z); a part-off keeps the piece "
                    "toward the exposed end, so the axis must point along setup +Z"
                )
    if not _number(to_z):
        unknown.append("the op's to_z is unknown")
    if scale is None:
        unknown.append("the manifest units are unknown")
    elif _number(to_z) and _number(face_z) and not same_length(face_z * scale, to_z * scale):
        errors.append(f"it lies at setup Z {face_z:g}, not on the to_z {to_z:g} the blade parts at")
    status = "error" if errors else "unknown" if unknown else "pass"
    return {"status": status, "reasons": errors or unknown, "face_z": face_z}


def makers(bundle, setup: dict, name: str) -> list[tuple[dict, dict]]:
    """The ``(setup, op)`` pairs of earlier setups in ``setup``'s stock lineage that work
    process feature ``name``, in plan order; the setup itself never counts."""
    earlier = setup_lineage(bundle.plan, setup["id"]) - {setup["id"]}
    return [
        (other, op)
        for other in bundle.plan.get("setups", [])
        if other["id"] in earlier
        for op in other.get("ops", [])
        if op.get("feature") == name
        and feature_material_status(bundle.plan, setup["id"], other["id"], name, bundle)
        is not False
    ]


def _scaled(value: Any, scale: float | None) -> Any:
    if scale is None or value == UNKNOWN:
        return UNKNOWN
    return [v * scale for v in value] if isinstance(value, list) else value * scale


def primitive(bundle, name: str) -> dict:
    """One process feature in model-frame mm; unknown manifest units leave ``at`` unknown."""
    feature = bundle.plan["process_features"][name]
    scale = _SCALE.get(bundle.features.get("units", UNKNOWN))
    result = {
        "kind": feature["kind"],
        "label": label(name),
        "at_mm": _scaled(feature["at"], scale),
        "axis": feature["axis"],
    }
    if feature["kind"] == "centre_hole":
        result.update({key: feature[key] for key in _CENTRE_KEYS})
        result["depth_mm"] = centre_depth_mm(
            {"preparation": {key: feature[key] for key in _CENTRE_KEYS}}
        )["depth_mm"]
    if feature["kind"] == "tooling_hole":
        result["dia_mm"] = _scaled(feature["dia"], scale)
        result["thru"] = feature.get("thru", False)
        if not result["thru"]:
            result["depth_mm"] = _scaled(feature["depth"], scale)
    return result


def primitives_mm(bundle) -> dict[str, dict]:
    return {name: primitive(bundle, name) for name in bundle.plan.get("process_features", {})}


def process_operation(bundle, op: dict) -> dict | None:
    """The kernel's analytic cut for an op on a process feature, else None.

    ``reason`` names why the cut cannot be modelled (an action that does not make this
    kind, or an unknown size); the kernel then leaves the op's stock unknown.
    """
    from prechips.rules.resolution import op_feature

    definition = bundle.feature_definitions.get(op_feature(op))
    process = process_of(definition)
    if process is None:
        return None
    name = process["id"]
    result = {"process_feature": name, "action": op.get("do", UNKNOWN), **primitive(bundle, name)}
    if result["action"] not in ACTIONS[process["kind"]]:
        result["reason"] = (
            f"{label(name)} ({process['kind']}) is made only by "
            + " or ".join(sorted(ACTIONS[process["kind"]]))
            + f", not {result['action']}"
        )
        return result
    unknown = [key for key in ("at_mm", "axis", "depth_mm", "dia_mm") if result.get(key) == UNKNOWN]
    if unknown:
        result["reason"] = f"{label(name)} geometry is unknown: " + ", ".join(unknown)
    return result
