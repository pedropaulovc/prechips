"""The rule catalogue; unsupported policy requests stay unresolved."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from prechips.findings import Finding, SelectorMatch, Status, selector_match
from prechips.inputs import Bundle
from prechips.rules import (
    accessibility,
    blank_credit,
    centre_support,
    consistency,
    construction,
    coordinates,
    coverage,
    datum_consistency,
    engagement,
    envelope,
    finish_coverage,
    finish_route,
    fixture_interference,
    headroom,
    hold_fields,
    indexing,
    inspection,
    internal_corner_radius,
    joints,
    keep_piece,
    manual_arc,
    op_chain,
    op_order,
    parting_face,
    prepared_blank,
    purchased_tooling,
    reach,
    saw_cut,
    sizing,
    speeds_feeds,
    stickout,
    stock_diameter,
    swivel,
    thin_wall_under_clamp,
    tip_endpoints,
    tool_resolves,
    tooling_hole,
    travel,
    turned_profile,
    turning_deflection,
    vise,
)
from prechips.rules.zero_recipe import rule as zero_recipe_rule


@dataclass(frozen=True)
class Rule:
    name: str
    evaluate: Callable[[Bundle], list[Finding]]


RULES: list[Rule] = [
    Rule("tool_resolves", tool_resolves.evaluate),
    Rule("sizing", sizing.evaluate),
    Rule("op_chain", op_chain.evaluate),
    Rule("order", op_order.evaluate),
    Rule("speeds_feeds", speeds_feeds.evaluate),
    Rule("zero_check", zero_recipe_rule.evaluate),
    Rule("coordinates", coordinates.evaluate),
    Rule("manual_arc", manual_arc.evaluate),
    Rule("inspection", inspection.evaluate),
    Rule("hold_fields", hold_fields.evaluate),
    Rule("purchased_tooling", purchased_tooling.evaluate),
    Rule("centre_support", centre_support.evaluate),
    Rule("tooling_hole", tooling_hole.evaluate),
    Rule("prepared_blank", prepared_blank.evaluate),
    Rule("parting_face", parting_face.evaluate),
    Rule("blind_depth", tip_endpoints.evaluate),
    Rule("headroom", headroom.evaluate),
    Rule("envelope", envelope.evaluate),
    Rule("travel", travel.evaluate),
    Rule("turning_deflection", turning_deflection.evaluate),
    Rule("datum_consistency", datum_consistency.evaluate),
    Rule("turned_profile", turned_profile.evaluate),
    Rule("stickout", stickout.evaluate),
    Rule("stock_diameter", stock_diameter.evaluate),
    Rule("indexing", indexing.evaluate),
    Rule("swivel", swivel.evaluate),
    Rule("engagement", engagement.evaluate),
    Rule("construction", construction.evaluate),
    Rule("finish_route", finish_route.evaluate),
    Rule("joint_fit", joints.evaluate_fit),
    Rule("joint_thread", joints.evaluate_thread),
    Rule("consistency", consistency.evaluate),
]

GEOMETRY_RULES = [
    Rule("accessibility", accessibility.evaluate),
    Rule("reach", reach.evaluate),
    Rule("internal_corner_radius", internal_corner_radius.evaluate),
    Rule("coverage", coverage.evaluate),
    Rule("blank_credit", blank_credit.evaluate),
    Rule("finish_coverage", finish_coverage.evaluate),
    Rule("vise", vise.evaluate),
    Rule("thin_wall_under_clamp", thin_wall_under_clamp.evaluate),
    Rule("saw_cut", saw_cut.evaluate),
    Rule("saw_teeth", saw_cut.evaluate_teeth),
    Rule("keep_piece", keep_piece.evaluate),
    Rule("fixture_interference", fixture_interference.evaluate),
    Rule("joint_assembly", joints.evaluate_assembly),
]
RULES.extend(GEOMETRY_RULES)


def required_coverage(bundle: Bundle, findings: list[Finding]) -> list[Finding]:
    """A shop cannot accidentally obtain checked readiness by naming a missing rule."""
    from prechips.model import tolerance_requirements
    from prechips.rules.resolution import HOLE_KINDS

    rows = []
    required = bundle.policy.get("required", "unknown")
    if required == "unknown":
        required = {"required_policy": "*"}
    for name, selector in required.items():
        actual = {f.subject for f in findings if f.rule == name}
        family = [finding for finding in findings if finding.rule == name]
        if isinstance(selector, list):
            subjects = selector
        elif selector == "setups":
            subjects = [s["id"] for s in bundle.plan["setups"]]
        elif selector in {"holes", "toleranced_features"}:
            subjects = [
                feature
                for feature, item in bundle.feature_definitions.items()
                if (
                    item.get("kind") in HOLE_KINDS
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
            # Lists and setup selectors name exact subjects. Feature selectors also
            # cover structured member/shared dimensions and participating relationships.
            match = [subject] if isinstance(selector, list) or selector == "setups" else subject
            if any(
                selector_match(finding, match, bundle) == SelectorMatch.MATCH for finding in family
            ):
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
