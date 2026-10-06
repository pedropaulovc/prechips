"""Sourced static turning proxy; no chatter, whip or measured-size claim (PLAN §4.4)."""

from __future__ import annotations

import math

from ..findings import Finding
from .resolution import MANUAL, UNKNOWN, _citations, number, operations, record, resolve, uncertain
from .stickout import support_state
from .turned_profile import nominal_diameter

_PROXY_CITE = "PLAN.md:563-568 (§4.4 physics proxies)"


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


def _tolerance(bundle, feature):
    """PLAN's ± comparison is the cited diameter band's half width, not a nominal guess."""
    band = feature.get("dia", UNKNOWN)
    source = feature.get("cite", UNKNOWN)
    if isinstance(source, dict):
        source = source.get("dia", UNKNOWN)
    cite = _citations(source)
    units = bundle.features.get("units", UNKNOWN)
    if (
        not isinstance(band, list)
        or len(band) != 2
        or not all(_positive(v) for v in band)
        or band[1] < band[0]
        or units not in {"mm", "in"}
    ):
        return UNKNOWN, UNKNOWN, cite
    scale = 25.4 if units == "in" else 1
    band_mm = [value * scale for value in band]
    return band_mm, (band_mm[1] - band_mm[0]) / 2 if cite else UNKNOWN, cite


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
        if action in MANUAL or (machine and kind not in {"lathe", UNKNOWN}):
            result.append(
                Finding(
                    "turning_deflection",
                    subject,
                    "not_applicable",
                    numbers,
                    cite,
                    f"{subject}: the static turning proxy does not apply to this operation.",
                )
            )
            continue

        feature_name = op.get("feature", UNKNOWN)
        feature = record(bundle.feature_definitions.get(feature_name))
        hold = record(setup.get("hold"))
        length = hold.get("stickout_mm", UNKNOWN)
        diameter = nominal_diameter(bundle, feature)
        doc, feed = op.get("doc_mm", UNKNOWN), op.get("feed_mm_rev", UNKNOWN)
        kc, e_gpa = row.get("kc_n_per_mm2", UNKNOWN), row.get("e_gpa", UNKNOWN)
        support, support_evidence = support_state(bundle, setup)
        coefficient = 48 if support == "pass" else 3 if support == "not_applicable" else UNKNOWN
        band, tolerance, feature_cite = _tolerance(bundle, feature)
        missing = []
        if action == UNKNOWN or kind != "lathe" or not machine or uncertain(machine):
            missing.append("verified lathe/operation")
        if not material_verified:
            missing.append("verified stock material")
        if not row_cite:
            missing.append("one cited cutting-data material row")
        for name, value in (
            ("stickout_mm", length),
            ("feature nominal diameter", diameter),
            ("doc_mm", doc),
            ("feed_mm_rev", feed),
            ("kc_n_per_mm2", kc),
            ("e_gpa", e_gpa),
        ):
            if not _positive(value):
                missing.append(name)
        if support == "unknown":
            missing.append("declared/resolved tailstock or steady support, or explicit none")

        force = inertia = modulus = deflection = UNKNOWN
        if not missing:
            force = kc * doc * feed
            inertia = math.pi * diameter**4 / 64
            modulus = e_gpa * 1000
            deflection = force * length**3 / (coefficient * modulus * inertia)
        if tolerance == UNKNOWN:
            missing.append("sourced feature diameter tolerance/acceptance threshold")
        numbers.update(
            stickout_mm=length,
            diameter_mm=diameter,
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
            dia_band_mm=band,
            diameter_tolerance_mm=tolerance,
            deflection_mm=deflection,
            tolerance_basis="(dia_high_mm - dia_low_mm) / 2",
            missing_inputs=missing,
        )
        cite.extend(
            [
                "PLAN.md:567 F = K_c·doc_mm·feed_mm_rev; δ = F·L³/(3EI) or /(48EI)",
                "PLAN.md:567 circular-section evaluation: I = π·D⁴/64; "
                "GPa-to-N/mm² conversion E_gpa × 1000",
                f"plan.setups[{setup['id']}].hold.stickout_mm; ops[{op['op']}].doc_mm/feed_mm_rev",
                f"features.features.{feature_name}: declared nominal diameter "
                "and dia acceptance band",
                "cutting-data aliases and unique material row",
            ]
        )
        if bundle.features.get("units") == "in":
            cite.append("explicit feature inch units × 25.4 mm/in")
        cite.extend(row_cite)
        cite.extend(feature_cite)
        cite.extend(
            evidence["source"]
            for evidence in support_evidence
            if isinstance(evidence.get("source"), str) and evidence["source"] != UNKNOWN
        )
        if missing:
            status = "unknown"
            prefix = (
                f"Computed static deflection {deflection:g} mm; "
                if number(deflection)
                else "Static deflection is unknown; "
            )
            message = prefix + "needs " + ", ".join(missing) + "."
        elif deflection > tolerance:
            status = "warn"
            message = (
                f"Expected static deflection {deflection:g} mm exceeds the sourced diameter "
                f"half-band ±{tolerance:g} mm; reduce the cutting load or add resolved support."
            )
        else:
            status = "pass"
            message = (
                f"Expected static deflection {deflection:g} mm is within the sourced diameter "
                f"half-band ±{tolerance:g} mm; this proxy does not certify chatter, whip or size."
            )
        result.append(
            Finding("turning_deflection", subject, status, numbers, cite, f"{subject}: {message}")
        )
    return result
