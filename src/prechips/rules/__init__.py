"""Declared-input rule catalogue; unsupported policy requests stay unresolved."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from prechips.findings import Finding, Status
from prechips.inputs import Bundle
from prechips.rules import (
    construction,
    coordinates,
    datum_consistency,
    engagement,
    envelope,
    headroom,
    hold_fields,
    holder_stack,
    indexing,
    inspection,
    op_chain,
    op_order,
    sizing,
    speeds_feeds,
    stickout,
    stock_diameter,
    tip_endpoints,
    tool_resolves,
    travel,
    turned_profile,
    turning_deflection,
    zero_recipe,
)


@dataclass(frozen=True)
class Rule:
    name: str
    evaluate: Callable[[Bundle], list[Finding]]


RULES: list[Rule] = [
    Rule("tool_resolves", tool_resolves.evaluate),
    Rule("sizing", sizing.evaluate),
    Rule("op_chain", op_chain.evaluate),
    Rule("order", op_order.evaluate),
    Rule("blind_depth", tip_endpoints.evaluate),
    Rule("speeds_feeds", speeds_feeds.evaluate),
    Rule("zero_check", zero_recipe.evaluate),
    Rule("coordinates", coordinates.evaluate),
    Rule("inspection", inspection.evaluate),
    Rule("hold_fields", hold_fields.evaluate),
    Rule("headroom", headroom.evaluate),
    Rule("envelope", envelope.evaluate),
    Rule("travel", travel.evaluate),
    Rule("holder_stack", holder_stack.evaluate),
    Rule("datum_consistency", datum_consistency.evaluate),
    Rule("turned_profile", turned_profile.evaluate),
    Rule("stickout", stickout.evaluate),
    Rule("stock_diameter", stock_diameter.evaluate),
    Rule("indexing", indexing.evaluate),
    Rule("turning_deflection", turning_deflection.evaluate),
    Rule("engagement", engagement.evaluate),
    Rule("construction", construction.evaluate),
]


def required_coverage(bundle: Bundle, findings: list[Finding]) -> list[Finding]:
    """A shop cannot accidentally obtain checked readiness by naming a missing rule."""
    from prechips.model import tolerance_requirements

    rows = []
    required = bundle.policy.get("required", "unknown")
    if required == "unknown":
        required = {"required_policy": "*"}
    for name, selector in required.items():
        actual = {f.subject for f in findings if f.rule == name}
        if isinstance(selector, list):
            subjects = selector
        elif selector == "setups":
            subjects = [s["id"] for s in bundle.plan["setups"]]
        elif selector in {"holes", "toleranced_features"}:
            subjects = [
                feature
                for feature, item in bundle.features["features"].items()
                if (
                    item.get("kind") in {"hole", "counterbore", "thread"}
                    if selector == "holes"
                    else bool(tolerance_requirements(item))
                )
            ]
        elif selector == "*":
            subjects = [] if actual else ["*"]
        else:
            subjects = [selector]
        if not subjects and not actual:
            subjects = ["*"]
        for subject in subjects:
            if any(value == subject or value.startswith(subject + ":") for value in actual):
                continue
            rows.append(
                Finding(
                    name,
                    subject,
                    Status.UNKNOWN,
                    {"required": selector},
                    ["PLAN.md §3.4 required subjects"],
                    "The shop requires a check with no matching supported subject.",
                )
            )
    return rows
