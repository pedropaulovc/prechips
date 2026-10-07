"""Plan-owned transient stock-preparation features: a faced stock end and a centre hole.

Process features resolve once into the operative feature mapping
(``Bundle.feature_definitions``) with their own kinds (``end_face``, ``centre_hole``) and no
drawing requirements, so operation rules (speeds and feeds, tip endpoints, accessibility,
headroom) resolve their ops like any feature's. They are never finished drawing surfaces:
no exported face maps to them, they earn no drawing coverage or finishing credit, and the
kernel removes their analytic solids from the stock when their op runs, so later setups
hold the faced end and the cut centre. Kernel payloads are normalised to millimetres here;
numeric unknowns stay debt.
"""

from __future__ import annotations

import math
from typing import Any

from prechips.inputs import BadInput
from prechips.joint_features import _lineage
from prechips.model import UNKNOWN

LABEL_PREFIX = "plan.process_features."
# The one public name for plan-authored stock preparation, kept apart from drawing acceptance.
PROCESS_PREP_LABEL = "STOCK PREPARATION — plan only, not a drawing dimension"
# The actions that make each kind. A centre is drilled with a combined drill and
# countersink; an end face is faced to the axis.
ACTIONS = {
    "end_face": frozenset({"face", "rough_face", "finish_face"}),
    "centre_hole": frozenset({"center_drill"}),
}
_CENTRE_KEYS = ("drill_dia_mm", "drill_length_mm", "mouth_dia_mm", "countersink_angle_deg")
_SCALE = {"mm": 1.0, "in": 25.4}


def label(name: str) -> str:
    return LABEL_PREFIX + name


def process_of(definition: Any) -> dict | None:
    """The process identity of an operative feature definition, or None otherwise."""
    return definition.get("process") if isinstance(definition, dict) else None


def source_cite(definition: Any) -> list[str]:
    """Plan-owned source identity for a process feature; empty for other features."""
    process = process_of(definition)
    return [f"{process['label']}: {PROCESS_PREP_LABEL}"] if process else []


def _number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def feature_definitions(plan: dict, definitions: dict) -> dict[str, dict]:
    """``definitions`` (exported plus joint features) plus resolved plan process features.

    Without process features this is ``definitions`` itself (no copy).
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
    for name, feature in declared.items():
        process = {"id": name, "kind": feature["kind"], "label": label(name)}
        process.update({key: feature[key] for key in _CENTRE_KEYS if key in feature})
        definition = {
            "kind": feature["kind"],
            "frame": "model",
            "at": feature["at"],
            "axis": feature["axis"],
            # Stock preparation is never a drawing requirement.
            "requirements": [],
            "cite": feature["cite"],
            "process": process,
        }
        for key in ("size", "note"):
            if key in feature:
                definition[key] = feature[key]
        merged[name] = definition
    return merged


def centre_depth_mm(definition: Any) -> dict:
    """A centre hole's feed depth below its faced end, in mm, from its declared sizes.

    The countersink of included angle ``a`` opens from the drill diameter ``D`` to the
    mouth ``M`` over ``(M - D) / 2 / tan(a / 2)``; the pilot's ``drill_length_mm`` (the
    Machinery's Handbook Table 6 drill length C, point included) runs on below it. Any
    unknown size leaves every depth unknown.
    """
    process = process_of(definition) or {}
    drill, length, mouth, angle = (process.get(key, UNKNOWN) for key in _CENTRE_KEYS)
    if not all(_number(value) for value in (drill, length, mouth, angle)):
        return {
            "countersink_depth_mm": UNKNOWN,
            "drill_length_mm": length if _number(length) else UNKNOWN,
            "depth_mm": UNKNOWN,
        }
    countersink = (mouth - drill) / 2 / math.tan(math.radians(angle / 2))
    return {
        "countersink_depth_mm": countersink,
        "drill_length_mm": length,
        "depth_mm": countersink + length,
    }


def makers(bundle, setup: dict, name: str) -> list[tuple[dict, dict]]:
    """The ``(setup, op)`` pairs of earlier setups in ``setup``'s stock lineage that work
    process feature ``name``, in plan order; the setup itself never counts."""
    earlier = _lineage(bundle.plan, setup["id"]) - {setup["id"]}
    return [
        (other, op)
        for other in bundle.plan.get("setups", [])
        if other["id"] in earlier
        for op in other.get("ops", [])
        if op.get("feature") == name
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
            {"process": {key: feature[key] for key in _CENTRE_KEYS}}
        )["depth_mm"]
    return result


def primitives_mm(bundle) -> dict[str, dict]:
    return {name: primitive(bundle, name) for name in bundle.plan.get("process_features", {})}


def process_operation(bundle, op: dict) -> dict | None:
    """The kernel's analytic cut for an op on a process feature, else None.

    ``reason`` names why the cut cannot be modelled (an action that does not make this
    kind, or an unknown size); the kernel then leaves the op's stock unknown.
    """
    definition = bundle.feature_definitions.get(op.get("feature"))
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
    unknown = [key for key in ("at_mm", "axis", "depth_mm") if result.get(key) == UNKNOWN]
    if unknown:
        result["reason"] = f"{label(name)} geometry is unknown: " + ", ".join(unknown)
    return result
