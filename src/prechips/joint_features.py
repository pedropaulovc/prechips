"""Plan-owned transient joint cylinders and the two-branch joints that consume them.

Joint features resolve once into the operative feature mapping (``Bundle.feature_definitions``)
as standard hole/boss definitions in manifest units, so dimensional and operation rules treat
them like exported features. The exported manifest, its hash and its finished faces are never
altered. Kernel payloads are normalised here to millimetres; numeric unknowns stay debt.
"""

from __future__ import annotations

import math
from typing import Any

from prechips.inputs import BadInput
from prechips.measurements import angle_fact, length_fact
from prechips.model import UNIT_TOLERANCE, UNKNOWN, stock_ancestry

LABEL_PREFIX = "plan.joint_features."
# The one public name for plan-authored preparation, kept apart from drawing acceptance.
TEMPORARY_LABEL = "TEMPORARY JOINT FEATURE (removed by later ops)"
# Absolute physical-length equality (resolution.LENGTH_TOLERANCE_MM): exact fit limits pass.
LENGTH_TOLERANCE_MM = 1e-6
_STANDARD_KIND = {"cylinder_bore": "hole", "cylinder_spigot": "boss"}
# Actions whose cut diameter is the cutter's own accepted diameter.
_TOOL_SIZED = {"drill", "ream", "spot"}
# Pointed cutters leave a cone below their full-diameter end.
_POINTED = {"drill", "spot"}
# Actions that cut the transient cylinder itself and so may complete it, per kind.
_CYLINDER_CUTS = {
    "cylinder_bore": frozenset({"drill", "ream", "bore", "rough_bore", "finish_bore"}),
    "cylinder_spigot": frozenset({"turn", "rough_turn", "finish_turn"}),
}
# Actions that remove only their own pointed tool profile (as accessibility poses do);
# they never prepare the full cylinder.
_PROFILE_CUTS = {
    "cylinder_bore": frozenset({"spot"}),
    "cylinder_spigot": frozenset(),
}
# Hole actions whose real removal needs geometry the joint model does not represent yet;
# on a transient joint feature they are refused as named debt, never a cylinder stand-in.
_UNMODELLED_GEOMETRY = {"tap": "thread", "counterbore": "counterbore step"}
_SCALE = {"mm": 1.0, "in": 25.4}


def label(name: str) -> str:
    return LABEL_PREFIX + name


def source_cite(definition: Any) -> list[str]:
    """Plan-owned source identity for a transient joint feature; empty for exported ones."""
    joint = joint_of(definition)
    return [f"{joint['label']}: {TEMPORARY_LABEL}"] if joint else []


def _number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def feature_definitions(plan: dict, features: dict) -> dict[str, dict]:
    """Exported features plus resolved plan joint features, keyed by bare name.

    Without joint features this is the exported mapping itself (no copy).
    """
    exported = features.get("features", {})
    declared = plan.get("joint_features") or {}
    if not declared:
        return exported
    collisions = sorted(set(declared) & set(exported))
    if collisions:
        raise BadInput(
            f"plan.joint_features {', '.join(map(repr, collisions))} collide with exported "
            "manifest feature names."
        )
    definitions = dict(exported)
    for name, feature in declared.items():
        definition = {
            "kind": _STANDARD_KIND[feature["kind"]],
            "frame": "model",
            "at": feature["at"],
            "axis": feature["axis"],
            "dia": feature["dia"],
            # Only the authored nominal is geometry; a band midpoint is never inferred.
            "dia_nominal": feature["nominal_dia"],
            "depth": feature["depth"],
            "thru": feature["thru"],
            "requirements": list(feature.get("requirements", ["dia"])),
            "cite": feature["cite"],
            "joint": {
                "id": name,
                "kind": feature["kind"],
                "component": feature["component"],
                "label": label(name),
            },
        }
        for key in ("precision", "note"):
            if key in feature:
                definition[key] = feature[key]
        definitions[name] = definition
    return definitions


def setup_span_mm(bundle, name: str, frame: dict) -> tuple[float, float] | None:
    """Exact setup-Z extent (mm) of a transient cylinder turned about the spindle, else None.

    ``frame`` is the setup frame in mm. Both authored ends (``at`` and ``at + axis * depth``)
    transform into it; the cylinder axis must be collinear with setup Z and lie on the spindle
    (setup X = Y = 0). Any unknown, skewed or off-centre input stays unresolved, never guessed.
    """
    from prechips.rules.coordinates import frame_point

    target = primitive(bundle, name)
    at, axis, depth = target["at_mm"], target["axis"], target["depth_mm"]
    spindle = frame.get("z")
    if (
        UNKNOWN in (at, axis, depth)
        or frame.get("binding") == UNKNOWN
        or not (isinstance(spindle, list) and len(spindle) == 3)
        or not all(_number(value) for value in spindle)
        or abs(abs(_dot(axis, spindle)) - 1.0) > UNIT_TOLERANCE
    ):
        return None
    far = [a + d * depth for a, d in zip(at, axis, strict=True)]
    ends = [frame_point(point, frame) for point in (at, far)]
    if not all(_number(value) for end in ends for value in end) or not all(
        abs(value) <= LENGTH_TOLERANCE_MM for end in ends for value in end[:2]
    ):
        return None
    low, high = sorted(end[2] for end in ends)
    return low, high


def _lineage(plan: dict, sid: str) -> set[str]:
    """The setup and every earlier setup whose output material flows into it."""
    setups = {setup["id"]: setup for setup in plan.get("setups", [])}
    seen, pending = set(), [sid]
    while pending:
        current = pending.pop()
        if current in seen or current not in setups:
            continue
        seen.add(current)
        refs = setups[current].get("stock_in")
        pending.extend(refs if isinstance(refs, list) else [refs] if isinstance(refs, str) else [])
    return seen


def present(bundle, setup: dict, name: str) -> bool:
    """Whether a transient joint feature exists on this setup's in-process material.

    It exists only on its own unjoined component branch once that lineage has cut it; a
    join consumes it. Exported features are always part of the declared final geometry.
    """
    joint = joint_of(bundle.feature_definitions.get(name))
    if joint is None:
        return True
    if setup_ancestry(bundle.plan).get(setup["id"]) != {f"stock.{joint['component']}"}:
        return False
    lineage = _lineage(bundle.plan, setup["id"])
    return any(
        earlier["id"] in lineage and op.get("feature") == name
        for earlier in bundle.plan["setups"]
        for op in earlier["ops"]
    )


def joint_of(definition: Any) -> dict | None:
    """The joint identity of an operative feature definition, or None for exported ones."""
    return definition.get("joint") if isinstance(definition, dict) else None


def setup_ancestry(plan: dict) -> dict[str, frozenset[str]]:
    """Root supplies (``stock`` / ``stock.<component>``) behind every setup output."""
    routes = []
    for setup in plan.get("setups", []):
        refs = setup.get("stock_in")
        routes.append(
            (setup["id"], None if refs is None else refs if isinstance(refs, list) else [refs])
        )
    return stock_ancestry(routes)


def _scale(bundle) -> float | None:
    return _SCALE.get(bundle.features.get("units", UNKNOWN))


def _scaled(value: Any, scale: float | None) -> Any:
    if scale is None or value == UNKNOWN:
        return UNKNOWN
    return [v * scale for v in value] if isinstance(value, list) else value * scale


def primitive(bundle, name: str) -> dict:
    """One joint feature in model-frame mm; unknown manifest units leave lengths unknown."""
    feature = bundle.plan["joint_features"][name]
    scale = _scale(bundle)
    return {
        "kind": feature["kind"],
        "component": feature["component"],
        "label": label(name),
        "at_mm": _scaled(feature["at"], scale),
        "axis": feature["axis"],
        "dia_mm": _scaled(feature["dia"], scale),
        "nominal_dia_mm": _scaled(feature["nominal_dia"], scale),
        "depth_mm": _scaled(feature["depth"], scale),
        "thru": feature["thru"],
    }


def primitives_mm(bundle) -> dict[str, dict]:
    return {name: primitive(bundle, name) for name in bundle.plan.get("joint_features", {})}


def _unknown_fields(name: str, values: dict, keys: tuple[str, ...]) -> list[str]:
    return [f"{label(name)}.{key}" for key in keys if values[key] == UNKNOWN]


def _dot(a, b) -> float:
    return sum(x * y for x, y in zip(a, b, strict=True))


def fit(bundle, setup: dict) -> dict:
    """Worst-case diametral fit and derived engagement of one cylindrical joint.

    ``missing`` lists numeric debt (no union); ``violations`` names certain errors.
    """
    joint = setup["joint"]
    names = {role: joint[role] for role in ("socket", "spigot")}
    socket, spigot = (primitive(bundle, names[role]) for role in ("socket", "spigot"))
    band = joint[f"{joint['fit']}_mm"]
    geometry = ("at_mm", "axis", "dia_mm", "nominal_dia_mm", "depth_mm")
    missing = [
        *_unknown_fields(names["socket"], socket, geometry),
        *_unknown_fields(names["spigot"], spigot, geometry),
    ]
    if band == UNKNOWN:
        missing.append(f"setups[{setup['id']}].joint.{joint['fit']}_mm")
    result = {
        "fit": joint["fit"],
        "band_mm": band,
        "guaranteed_mm": UNKNOWN,
        "engagement": None,
        "missing": missing,
        "violations": [],
    }
    if missing:
        return result
    s_lo, s_hi = socket["dia_mm"]
    p_lo, p_hi = spigot["dia_mm"]
    guaranteed = (
        [s_lo - p_hi, s_hi - p_lo] if joint["fit"] == "clearance" else [p_lo - s_hi, p_hi - s_lo]
    )
    result["guaranteed_mm"] = guaranteed
    violations = result["violations"]
    if guaranteed[0] < band[0] - LENGTH_TOLERANCE_MM:
        violations.append(f"{joint['fit']}_below_band")
    if guaranteed[1] > band[1] + LENGTH_TOLERANCE_MM:
        violations.append(f"{joint['fit']}_above_band")
    origin, axis = socket["at_mm"], socket["axis"]
    along = _dot(spigot["axis"], axis)
    offset = [b - a for a, b in zip(origin, spigot["at_mm"], strict=True)]
    start = _dot(offset, axis)
    radial = math.sqrt(max(0.0, _dot(offset, offset) - start * start))
    if abs(abs(along) - 1.0) > UNIT_TOLERANCE or radial > LENGTH_TOLERANCE_MM:
        violations.append("axes_not_collinear")
        return result
    end = start + spigot["depth_mm"] * along
    low = max(0.0, min(start, end))
    high = min(socket["depth_mm"], max(start, end))
    if high - low <= LENGTH_TOLERANCE_MM:
        violations.append("no_engagement")
        return result
    result["engagement"] = {
        "at_mm": [o + low * u for o, u in zip(origin, axis, strict=True)],
        "axis": list(axis),
        "diameter_mm": max(s_hi, p_hi),
        "depth_mm": high - low,
    }
    return result


_VIOLATIONS = {
    "clearance_below_band": "worst-case minimum clearance is below the declared clearance_mm",
    "clearance_above_band": "worst-case maximum clearance exceeds the declared clearance_mm",
    "interference_below_band": (
        "worst-case minimum interference is below the declared interference_mm"
    ),
    "interference_above_band": (
        "worst-case maximum interference exceeds the declared interference_mm"
    ),
    "axes_not_collinear": "socket and spigot axes are not collinear",
    "no_engagement": "socket and spigot finite depths do not overlap",
}


def describe(violations: list[str]) -> str:
    return "; ".join(_VIOLATIONS[name] for name in violations)


def _owner(refs: list[str], ancestry: dict[str, frozenset[str]], component: str) -> str:
    root = f"stock.{component}"
    return next(ref for ref in refs if root in ancestry.get(ref, frozenset((ref,))))


def setup_joint(bundle, setup: dict) -> dict | None:
    """Normalised mm joint descriptor of a two-branch assembly setup, else None.

    ``reason`` is numeric joint debt (no union); ``fit_error`` is a certain fit failure.
    """
    refs = setup.get("stock_in")
    if not isinstance(refs, list):
        return None
    joint = setup["joint"]
    common = {
        "kind": joint["kind"],
        "refs": list(refs),
        "method": joint["method"],
        "process": joint["process"],
    }
    if joint["kind"] == "surface":
        scale = _scale(bundle)
        interfaces, missing = [], []
        for index, interface in enumerate(joint["interfaces"]):
            normalised = {
                "at_mm": _scaled(interface["at"], scale),
                "normal": interface["normal"],
                "x": interface["x"],
                "size_mm": interface["size_mm"],
            }
            missing.extend(
                f"setups[{setup['id']}].joint.interfaces[{index}].{key}"
                for key, value in normalised.items()
                if value == UNKNOWN
            )
            interfaces.append(normalised)
        # Side ownership is the stock_in order, never inferred from geometry: stock_in[0]
        # owns the interface's negative-normal half-space and stock_in[1] the positive one.
        return {
            **common,
            "negative_ref": refs[0],
            "positive_ref": refs[1],
            "interfaces": interfaces,
            "reason": f"joint geometry unknown: {', '.join(missing)}" if missing else None,
        }
    ancestry = setup_ancestry(bundle.plan)
    result = fit(bundle, setup)
    features = bundle.plan["joint_features"]
    return {
        **common,
        "socket": joint["socket"],
        "spigot": joint["spigot"],
        "socket_ref": _owner(refs, ancestry, features[joint["socket"]]["component"]),
        "spigot_ref": _owner(refs, ancestry, features[joint["spigot"]]["component"]),
        "fit": joint["fit"],
        "band_mm": result["band_mm"],
        "guaranteed_mm": result["guaranteed_mm"],
        "engagement": result["engagement"],
        "fit_error": describe(result["violations"]) or None,
        "reason": (
            f"joint geometry unknown: {', '.join(result['missing'])}"
            if result["missing"]
            else None
        ),
    }


def joint_operation(bundle, op: dict, finishing: bool) -> dict | None:
    """The transient target an op cuts on its own branch, in mm, or None.

    None for exported features and noncutting actions (the canonical
    ``geometry_common.cutting_action``). ``completes`` is true only for an action that cuts
    the cylinder itself (bore family on a socket, turning on a spigot); spot on a socket
    removes only its own pointed tool profile and never prepares the full cylinder. Tap and
    counterbore are refused (``reason``) until thread/step geometry exists; any other action
    is unsupported debt. Tool-sized actions carry the cutter's accepted diameter, pointed
    ones its accepted ``point_angle_deg``; other finishing cuts the authored nominal and
    other rough cuts leave ``rough_allowance_mm``. ``op_depth_mm`` stays separate from the
    target depth.
    """
    from prechips.rules._envelope import measurement_item
    from prechips.rules.geometry_common import cutting_action

    joint = joint_of(bundle.feature_definitions.get(op.get("feature")))
    if joint is None or cutting_action(op) is False:
        return None
    target = primitive(bundle, joint["id"])
    result = {
        "joint_feature": joint["id"],
        "action": op.get("do", UNKNOWN),
        "finishing": finishing,
        **target,
    }
    scale = _scale(bundle)
    if "depth_mm" in op:
        result["op_depth_mm"] = op["depth_mm"]
    for key in ("z_from", "z_to"):
        if key in op:
            result[key] = _scaled(op[key], scale) if _number(op[key]) else UNKNOWN
    action = op.get("do", UNKNOWN)
    allowance = op.get("rough_allowance_mm", UNKNOWN)
    nominal = target["nominal_dia_mm"]
    diameter, reason = UNKNOWN, None
    kind = target["kind"]
    result["completes"] = action in _CYLINDER_CUTS[kind]
    if action == UNKNOWN:
        reason = "the joint cut action is unknown"
    elif action in _UNMODELLED_GEOMETRY:
        reason = (
            f"{action} on {label(joint['id'])} is refused: its "
            f"{_UNMODELLED_GEOMETRY[action]} geometry is not modelled on transient joint "
            "features"
        )
    elif action not in _CYLINDER_CUTS[kind] | _PROFILE_CUTS[kind]:
        reason = (
            f"{action} has no supported physical cut profile on {label(joint['id'])} ({kind})"
        )
    elif action in _TOOL_SIZED:
        tool = measurement_item(bundle, "tools", op.get("tool"))
        fact = length_fact(tool, "dia", require_measured=False)
        if fact["verified"]:
            diameter = fact["value"]
        else:
            reason = f"{action} tool diameter is not accepted: {fact['reason']}"
        if action in _POINTED:
            # The point cone below the full-diameter end is real removal; unknown is debt.
            point = angle_fact(tool, "point_angle", require_measured=False)
            accepted = point["verified"] and 0 < point["value"] < 180
            result["point_angle_deg"] = point["value"] if accepted else UNKNOWN
            if not accepted and reason is None:
                reason = (
                    f"{action} point angle is not accepted: {point['reason']}"
                    if not point["verified"]
                    else f"{action} point angle must lie strictly between 0 and 180 degrees"
                )
    elif finishing:
        diameter = nominal
        if nominal == UNKNOWN:
            reason = f"{label(joint['id'])}.nominal_dia is unknown"
    elif _number(allowance) and allowance >= 0:
        if nominal == UNKNOWN:
            reason = f"{label(joint['id'])}.nominal_dia is unknown"
        else:
            # A rough socket stays undersize, a rough spigot oversize, by the allowance.
            sign = -1.0 if target["kind"] == "cylinder_bore" else 1.0
            diameter = nominal + sign * allowance
    else:
        reason = "a non-finishing joint cut needs an authored rough_allowance_mm"
    result["diameter_mm"] = diameter
    if reason is not None:
        result["reason"] = reason
    return result
