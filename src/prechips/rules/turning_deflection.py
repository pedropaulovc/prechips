"""Sourced static turning proxy; no chatter, whip or measured-size claim (PLAN §4.4)."""

from __future__ import annotations

import math

from ..findings import Finding
from ..process_features import process_of
from . import turned_profile
from ._envelope import fact
from .geometry_common import _AXIAL_LATHE_ACTIONS
from .resolution import (
    MANUAL,
    UNKNOWN,
    _citations,
    number,
    operations,
    record,
    resolve,
    same_length,
    uncertain,
)
from .stickout import support_state
from .turned_profile import exposed_profile, nominal_diameter

_PROXY_CITE = "PLAN.md:563-568 (§4.4 physics proxies)"
# Actions whose cut runs across the work face: the loaded section is the workpiece
# entering the setup and the acceptance band is the feature's axial size.
AXIAL_OPS = {"face", "rough_face", "finish_face", "cut_to_fit", "part_off", "form_dome"}
# A rest entry keyed by its geometry: follow rests ride behind the tool, steadies stand still.
_REST_KINDS = {"jaw_lead_mm": "follow_rest", "at_z_mm": "steady_rest"}


def _positive(value):
    return number(value) and math.isfinite(value) and value > 0


def _material(bundle):
    stock = record(bundle.plan.get("stock"))
    material = stock.get("material", record(bundle.features.get("material")).get("spec", UNKNOWN))
    cutting = record(bundle.cutting_data)
    material_class = record(cutting.get("aliases")).get(material, UNKNOWN)
    rows = cutting.get("material")
    candidates = rows if isinstance(rows, list) and material_class != UNKNOWN else []
    matches = [
        row
        for row in candidates
        if isinstance(row, dict) and row.get("material_class") == material_class
    ]
    selected = matches[0] if len(matches) == 1 else {}
    source = _citations(selected.get("cite"))
    verified = stock.get("material_verify", False) is False
    return material, material_class, selected, source, verified


def _tolerance(bundle, feature, field):
    """PLAN's ± comparison is the cited band's half width, not a nominal guess."""
    band = feature.get(field, UNKNOWN)
    source = feature.get("cite", UNKNOWN)
    if isinstance(source, dict):
        source = source.get(field, UNKNOWN)
    cite = _citations(source)
    units = bundle.features.get("units", UNKNOWN)
    valid = (
        isinstance(band, list)
        and len(band) == 2
        and all(number(v) and math.isfinite(v) for v in band)
        and band[1] >= band[0]
        and (field != "dia" or all(v > 0 for v in band))
    )
    if not valid or units not in {"mm", "in"}:
        return UNKNOWN, UNKNOWN, cite
    scale = 25.4 if units == "in" else 1
    band_mm = [value * scale for value in band]
    return band_mm, (band_mm[1] - band_mm[0]) / 2 if cite else UNKNOWN, cite


def _band_field(feature, axial):
    """Radial cuts answer to the diameter band; axial cuts to the feature's axial size."""
    if feature.get("kind") == "dome":
        return "height"
    if not axial:
        return "dia"
    return next((name for name in ("length", "height") if name in feature), "length")


def _rest_entries(hold):
    for key in ("support", "supports"):
        values = hold.get(key)
        for value in values if isinstance(values, list) else [values]:
            if isinstance(value, dict) and any(field in value for field in _REST_KINDS):
                yield value


def _without_rests(setup):
    """Rest tables are scored by the span model, never as a whole-stickout support."""
    hold = record(setup.get("hold"))
    if not isinstance(hold.get("supports"), list):
        return setup
    supports = [
        value
        for value in hold["supports"]
        if not (isinstance(value, dict) and any(field in value for field in _REST_KINDS))
    ]
    return {**setup, "hold": {**hold, "supports": supports}}


def _cut_z(op):
    values = [op.get(key) for key in ("z_from", "z_to")]
    if not all(number(value) for value in values):
        values = [op.get("to_z")]
    return values if all(number(value) for value in values) else UNKNOWN


def _rest_diameters(bundle, setup, at_z):
    """Declared finished diameters under a steady's jaws at ``at_z_mm``."""
    segments = [
        segment
        for segment in exposed_profile(bundle, setup)["segments"]
        if segment["z_mm"][0] <= at_z <= segment["z_mm"][1]
    ]
    values = [segment["diameter_mm"] for segment in segments]
    return values if values and all(_positive(value) for value in values) else UNKNOWN


def _rest(bundle, setup, op, turned, debts, cite):
    """(span_mm, evidence, missing) from the declared follow/steady rests serving this op.

    A rest serves an op it lists (omitted ``ops`` = every turning op in the setup)
    when the diameter its jaws ride on lies inside the rest's measured capacity.
    The shortest served span wins; any unresolved serving rest leaves the span unknown.
    """
    spans, evidence, missing = [], [], []
    for entry in _rest_entries(record(setup.get("hold"))):
        ops = entry.get("ops", "all")
        if isinstance(ops, list) and op.get("op") not in ops:
            continue
        reference = entry.get("ref", UNKNOWN)
        kinds = [_REST_KINDS[field] for field in _REST_KINDS if field in entry]
        kind = kinds[0] if len(kinds) == 1 else UNKNOWN
        row = {"reference": reference, "kind": kind, "ops": ops}
        evidence.append(row)
        item = resolve(bundle, "fixtures", reference)
        cite.append(f"plan.setups[{setup['id']}].hold.supports[{reference}]")
        if (
            kind == UNKNOWN
            or (not isinstance(ops, list) and ops != "all")
            or item is None
            or uncertain(item)
            or item.get("kind") != kind
        ):
            row["status"] = "unknown"
            missing.append(f"one resolved verified follow_rest/steady_rest for '{reference}'")
            continue
        low = fact(item, "capacity_min", "fixtures", reference, debts, cite)
        high = fact(item, "capacity_max", "fixtures", reference, debts, cite)
        row.update(capacity_min_mm=low["value"], capacity_max_mm=high["value"])
        if kind == "follow_rest":
            lead = entry.get("jaw_lead_mm", UNKNOWN)
            span = lead if _positive(lead) else UNKNOWN
            # Trailing jaws (the default) ride the diameter this op turns; leading jaws ride
            # the uncut one, which this rule does not derive.
            trailing = entry.get("jaw_side", "turned") == "turned"
            ridden = [turned] if trailing and _positive(turned) else UNKNOWN
            row.update(jaw_lead_mm=lead, jaw_side=entry.get("jaw_side", "turned"))
        else:
            at_z, cut_z = entry.get("at_z_mm", UNKNOWN), _cut_z(op)
            known = number(at_z) and cut_z != UNKNOWN
            span = max(abs(z - at_z) for z in cut_z) if known else UNKNOWN
            ridden = _rest_diameters(bundle, setup, at_z) if number(at_z) else UNKNOWN
            row.update(at_z_mm=at_z, cut_z_mm=cut_z)
        row.update(span_mm=span, ridden_diameter_mm=ridden)
        if not (low["verified"] and high["verified"]):
            row["status"] = "unknown"
            missing.append(f"measured {reference} capacity_min/capacity_max")
        elif ridden == UNKNOWN:
            row["status"] = "unknown"
            missing.append(f"diameter riding in {reference}")
        elif not all(
            (value > low["value"] or same_length(value, low["value"]))
            and (value < high["value"] or same_length(value, high["value"]))
            for value in ridden
        ):
            row["status"] = "outside_capacity"
        elif span == UNKNOWN:
            row["status"] = "unknown"
            missing.append(
                f"{reference} positive jaw_lead_mm"
                if kind == "follow_rest"
                else f"{reference} at_z_mm and operation cut z"
            )
        else:
            row["status"] = "pass"
            spans.append(span)
    if missing:
        return UNKNOWN, evidence, missing
    return (min(spans) if spans else None), evidence, missing


def evaluate(bundle):
    result = []
    material, material_class, row, row_cite, material_verified = _material(bundle)
    for setup, op in operations(bundle):
        subject = f"{setup['id']}:{op['op']}"
        action = op.get("do", UNKNOWN)
        machine = resolve(bundle, "machines", setup.get("machine"))
        kind = record(machine).get("kind", UNKNOWN)
        cite = [_PROXY_CITE]
        numbers = {"operation": action, "feature": op.get("feature", UNKNOWN)}
        reason = (
            "the static turning proxy does not apply to this operation"
            if action in MANUAL or (machine and kind not in {"lathe", UNKNOWN})
            else "a tailstock tool on the spindle axis loads the work axially, not as a turning cut"
            if kind == "lathe" and action in _AXIAL_LATHE_ACTIONS
            else "stock preparation has no drawing acceptance band to deflect out of"
            if process_of(bundle.feature_definitions.get(op.get("feature")))
            else None
        )
        if reason:
            result.append(
                Finding(
                    "turning_deflection",
                    subject,
                    "not_applicable",
                    numbers,
                    cite,
                    f"{subject}: {reason}.",
                )
            )
            continue

        feature_name = op.get("feature", UNKNOWN)
        feature = record(bundle.feature_definitions.get(feature_name))
        axial = action in AXIAL_OPS
        rough = isinstance(action, str) and action.startswith("rough_")
        dome = feature.get("kind") == "dome"
        hold = record(setup.get("hold"))
        missing, debts = [], {}
        if dome:
            span_facts = turned_profile.feature_span(bundle, setup, feature_name)
            diameter = span_facts.get("base_diameter_mm", UNKNOWN)
            diameter_name = "dome base diameter (turned_profile.feature_span)"
            diameter_basis = "turned_profile.feature_span base_diameter_mm"
            cite.extend(_citations(span_facts.get("cite")))
        elif axial:
            diameter = record(setup.get("stock_state")).get("od_mm", UNKNOWN)
            diameter_name = "stock_state.od_mm"
            diameter_basis = f"plan.setups[{setup['id']}].stock_state.od_mm"
        else:
            diameter = nominal_diameter(bundle, feature)
            diameter_name = "feature nominal diameter"
            diameter_basis = f"features.features.{feature_name}: declared nominal diameter"
        allowance = op.get("rough_allowance_mm", UNKNOWN)
        turned = diameter
        if rough and not axial and not dome:
            turned = (
                diameter + allowance if _positive(diameter) and _positive(allowance) else UNKNOWN
            )
        doc, feed = op.get("doc_mm", UNKNOWN), op.get("feed_mm_rev", UNKNOWN)
        kc, e_gpa = row.get("kc_n_per_mm2", UNKNOWN), row.get("e_gpa", UNKNOWN)

        rest_span, rests, rest_missing = _rest(bundle, setup, op, turned, debts, cite)
        missing.extend(rest_missing)
        if rest_span is None:
            support, support_evidence = support_state(bundle, _without_rests(setup))
            length = hold.get("stickout_mm", UNKNOWN)
            coefficient = 48 if support == "pass" else 3 if support == "not_applicable" else UNKNOWN
            span_model, length_name = "stickout", "stickout_mm"
            if support == "unknown":
                missing.append("declared/resolved tailstock or steady support, or explicit none")
        else:
            # An unresolved serving rest already names its own missing span inputs.
            support, support_evidence = "rest", []
            length, coefficient = rest_span, 3
            span_model = next(
                (rest["kind"] for rest in rests if rest.get("span_mm") == rest_span),
                "rest",
            )
            length_name = None if rest_span == UNKNOWN else "rest span_mm"

        band_field = _band_field(feature, axial)
        label = "diameter" if band_field == "dia" else band_field
        band, tolerance, feature_cite = _tolerance(bundle, feature, band_field)
        if rough:
            threshold = allowance / 2 if _positive(allowance) else UNKNOWN
            threshold_basis = "rough_allowance_mm / 2"
        else:
            threshold = tolerance
            threshold_basis = f"({band_field}_high_mm - {band_field}_low_mm) / 2"
        if action == UNKNOWN or kind != "lathe" or not machine or uncertain(machine):
            missing.append("verified lathe/operation")
        if not material_verified:
            missing.append("verified stock material")
        if not row_cite:
            missing.append("one cited cutting-data material row")
        for name, value in (
            (length_name, length),
            (diameter_name, diameter),
            ("doc_mm", doc),
            ("feed_mm_rev", feed),
            ("kc_n_per_mm2", kc),
            ("e_gpa", e_gpa),
        ):
            if name is not None and not _positive(value):
                missing.append(name)

        force = inertia = modulus = deflection = UNKNOWN
        if not missing:
            force = kc * doc * feed
            inertia = math.pi * diameter**4 / 64
            modulus = e_gpa * 1000
            deflection = force * length**3 / (coefficient * modulus * inertia)
        if threshold == UNKNOWN:
            missing.append(
                "positive rough_allowance_mm acceptance threshold"
                if rough
                else f"sourced feature {label} tolerance/acceptance threshold"
            )
        numbers.update(
            stickout_mm=hold.get("stickout_mm", UNKNOWN),
            span_mm=length,
            span_model=span_model,
            rests=rests,
            diameter_mm=diameter,
            diameter_basis=diameter_basis,
            turned_diameter_mm=turned,
            feature_units=bundle.features.get("units", UNKNOWN),
            doc_mm=doc,
            feed_mm_rev=feed,
            material=material,
            material_class=material_class,
            material_verified=material_verified,
            kc_n_per_mm2=kc,
            e_gpa=e_gpa,
            e_n_per_mm2=modulus,
            force_n=force,
            inertia_mm4=inertia,
            support_status=support,
            supports=support_evidence,
            denominator_coefficient=coefficient,
            acceptance_field=band_field,
            acceptance_band_mm=band,
            rough_allowance_mm=allowance if rough else "not_applicable",
            acceptance_threshold_mm=threshold,
            deflection_mm=deflection,
            tolerance_basis=threshold_basis,
            missing_inputs=missing,
        )
        if debts:
            numbers["measurements"] = list(debts.values())
        cite.extend(
            [
                "PLAN.md:567 F = K_c·doc_mm·feed_mm_rev; δ = F·L³/(3EI) or /(48EI)",
                "PLAN.md:567 circular-section evaluation: I = π·D⁴/64; "
                "GPa-to-N/mm² conversion E_gpa × 1000",
                f"plan.setups[{setup['id']}].hold.stickout_mm; ops[{op['op']}].doc_mm/feed_mm_rev",
                diameter_basis,
                f"features.features.{feature_name}: {band_field} acceptance band"
                if not rough
                else f"plan.setups[{setup['id']}].ops[{op['op']}].rough_allowance_mm",
                "cutting-data aliases and unique material row",
            ]
        )
        if bundle.features.get("units") == "in":
            cite.append("explicit feature inch units × 25.4 mm/in")
        cite.extend(row_cite)
        if not rough:
            cite.extend(feature_cite)
        cite.extend(
            evidence["source"]
            for evidence in support_evidence
            if isinstance(evidence.get("source"), str) and evidence["source"] != UNKNOWN
        )
        cite = list(dict.fromkeys(cite))
        accepted = "rough allowance" if rough else f"sourced {label}"
        if missing:
            status = "unknown"
            prefix = (
                f"Computed static deflection {deflection:g} mm; "
                if number(deflection)
                else "Static deflection is unknown; "
            )
            message = prefix + "needs " + ", ".join(missing) + "."
        elif deflection > threshold:
            status = "warn"
            message = (
                f"Expected static deflection {deflection:g} mm exceeds the {accepted} "
                f"half-band ±{threshold:g} mm; reduce the cutting load or add resolved support."
            )
        else:
            status = "pass"
            message = (
                f"Expected static deflection {deflection:g} mm is within the {accepted} "
                f"half-band ±{threshold:g} mm; this proxy does not certify chatter, whip or size."
            )
        result.append(
            Finding("turning_deflection", subject, status, numbers, cite, f"{subject}: {message}")
        )
    return result
