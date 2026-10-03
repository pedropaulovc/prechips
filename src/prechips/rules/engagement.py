"""Selected endmill projection / diameter proxy; PLAN §4.4 owns the 4×D limit."""

from __future__ import annotations

import math

from ..findings import Finding
from ._envelope import tool_projection
from .resolution import (
    UNKNOWN,
    length_mm,
    number,
    operations,
    record,
    resolve,
    same_length,
    uncertain,
)
from .tip_endpoints import FACING, HOLE_OPS, POCKETING
from .turned_profile import PROFILE_OPS

_LIMIT_LD = 4
_DOC_SCALE = 0.5
_PROXY_CITE = "PLAN.md:563-568 (§4.4 engagement: projection/D ≤ 4, else halve DOC)"
_ENDMILL_KINDS = {"endmill", "endmill_set"}
_CUTTING_OPS = (
    FACING
    | HOLE_OPS
    | POCKETING
    | PROFILE_OPS
    | {"center", "rough_profile", "finish_profile", "part_off", "cut_to_fit"}
)


def _positive(value):
    return number(value) and math.isfinite(value) and value > 0


def evaluate(bundle):
    result = []
    for setup, op in operations(bundle):
        subject = f"{setup['id']}:{op['op']}"
        action = op.get("do", UNKNOWN)
        tool_ref, holder_ref = op.get("tool", UNKNOWN), op.get("holder", UNKNOWN)
        tool = resolve(bundle, "tools", tool_ref)
        kind = (tool or {}).get("kind", UNKNOWN)
        numbers = {"operation": action, "tool": tool_ref, "holder": holder_ref, "tool_kind": kind}
        cite = [_PROXY_CITE]
        if (
            (action != UNKNOWN and action not in _CUTTING_OPS)
            or "doc_mm" not in op
            or (kind != UNKNOWN and kind not in _ENDMILL_KINDS)
        ):
            result.append(
                Finding(
                    "engagement",
                    subject,
                    "not_applicable",
                    numbers,
                    cite,
                    f"{subject}: engagement applies only to an endmill cutting operation "
                    "with an authored DOC.",
                )
            )
            continue

        holder = resolve(bundle, "holders", holder_ref)
        diameter = length_mm(tool, "dia")
        oal, grip = length_mm(tool, "oal"), length_mm(holder, "grip")
        projection_fact = tool_projection(bundle, op, {}, cite, require_measured=False)
        projection = projection_fact["value"]
        explicit = any(
            holder_ref in record((tool or {}).get(field))
            for field in ("projection_mm", "projection_in")
        )
        basis = "selected tool/holder projection" if explicit else "tool OAL - selected holder grip"
        doc = op.get("doc_mm", UNKNOWN)
        missing = []
        if action == UNKNOWN:
            missing.append("known cutting operation")
        if kind not in _ENDMILL_KINDS:
            missing.append("known endmill family")
        if not tool or uncertain(tool):
            missing.append("resolved/verified selected tool")
        if not holder or uncertain(holder):
            missing.append("resolved/verified selected holder")
        if not _positive(diameter):
            missing.append("explicit-unit tool diameter")
        if not _positive(projection) or not projection_fact["verified"]:
            missing.append("positive selected tool/holder projection or OAL minus holder grip")

        ratio = projection / diameter if not missing else UNKNOWN
        over_limit = (
            number(ratio)
            and projection > _LIMIT_LD * diameter
            and not same_length(projection, _LIMIT_LD * diameter)
        )
        scale = recommended = UNKNOWN
        if number(ratio):
            scale = _DOC_SCALE if over_limit else 1
            if _positive(doc):
                recommended = doc * scale
        if not _positive(doc):
            missing.append("positive authored DOC")
        numbers.update(
            diameter_mm=diameter,
            tool_oal_mm=oal,
            holder_grip_mm=grip,
            projection_mm=projection,
            projection_basis=basis,
            projection_ld=ratio,
            projection_ld_max=_LIMIT_LD,
            over_limit=over_limit if number(ratio) else UNKNOWN,
            doc_mm=doc,
            doc_scale=scale,
            recommended_doc_mm=recommended,
            missing_inputs=missing,
        )
        cite.extend(
            [
                f"inventory.tools.{tool_ref}: explicit-unit diameter/projection/OAL",
                f"inventory.holders.{holder_ref}: selected holder grip/verification",
                f"plan.setups[{setup['id']}].ops[{op['op']}].doc_mm",
                "inventory explicit inch length × 25.4 mm/in (resolution.length_mm)",
                "resolution.same_length: existing physical-length equality precision "
                "(1 nm absolute, no relative slack) at projection = 4·D",
            ]
        )
        if missing:
            status = "unknown"
            message = "Engagement proxy needs " + ", ".join(missing) + "."
            if over_limit:
                message = (
                    f"Tool projection is {ratio:g}×D, above {_LIMIT_LD}×D; "
                    "DOC reduction is unknown without positive authored DOC."
                )
        elif over_limit:
            status = "warn"
            message = (
                f"Tool projection is {ratio:g}×D, above {_LIMIT_LD}×D; "
                f"halve DOC from {doc:g} to {recommended:g} mm or shorten the projection."
            )
        else:
            status = "pass"
            message = (
                f"Tool projection is {ratio:g}×D, within {_LIMIT_LD}×D; "
                "this engagement proxy requires no DOC reduction."
            )
        result.append(
            Finding("engagement", subject, status, numbers, cite, f"{subject}: {message}")
        )
    return result
