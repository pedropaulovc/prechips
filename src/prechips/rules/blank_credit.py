"""Face credit for a profiled blank bought already cut (docs/rules-geometry.md#blank_credit).

An ``as_is_faces`` face of a profiled supply counts as made only when (a) the kernel finds
the finished face on the blank solid's boundary within its as-is contact tolerance
(``STOCK_TOL``, 1e-3 mm), so the vendor's cut is the finished face rather than one buried
in stock, and (b) every drawing band of each exported feature owning that face holds the
vendor's declared ± ``profile_tolerance_mm`` about the nominal the blank STEP carries.

The tolerance is read as the vendor states it: any cut dimension, measured along X or Y,
lands within ± t of its nominal. A length band therefore holds when ``nominal ± t`` lies
inside it: a one-sided band whose nominal is a limit (+0.50/0) never does, since the cut
may fall t past that limit. Without an exported nominal only a band narrower than 2t is
decided (no centring fits); a wider one stays unknown. A zone read across two axes (a
``position_dia`` or a ``surface_profile``, including a BASIC scalar it governs) must hold
the X and Y errors together: a circle of radius t√2, so a zone width of at least 2√2·t.
An angle, a roughness and the other zones are not bounded by a length tolerance and stay
unknown. A face failing either check is not credited: it stays uncovered and needs an op.
"""

from __future__ import annotations

import math

from prechips.findings import Finding
from prechips.inputs import blank_supplies
from prechips.model import LENGTH_REQUIREMENTS, profile_target, tolerance_requirements
from prechips.rules.geometry_common import provenance, unavailable
from prechips.rules.resolution import _citations, number, record

UNKNOWN = "unknown"
RULE = "blank_credit"
# Per-face credit verdicts.
CREDITED, OFF_BLANK, BAND = "credited", "off_blank", "band"
# Per-requirement verdicts of the vendor tolerance against one drawing band.
HOLDS, EXCEEDS = "holds", "exceeds"
# Zones read across the cut plane's two axes: X and Y errors combine.
PLANAR_ZONES = frozenset({"position_dia", "surface_profile"})
_EPS = 1e-9
_SCALE = {"mm": 1.0, "in": 25.4}


def profiled_supplies(bundle):
    """``{supply: blank record}`` for every profiled blank: ``stock`` or ``stock.<id>``."""
    return {
        kind.removesuffix(".blank"): blank for kind, blank in blank_supplies(bundle.plan).items()
    }


def nominal(feature, requirement):
    """The exported nominal of a requirement band, read as inspection reads it."""
    for field in (f"{requirement}_nominal", f"nominal_{requirement}"):
        if number(feature.get(field)):
            return feature[field]
    return UNKNOWN


def _governing_zone(features, name, requirement):
    """The surface profile zone width governing BASIC scalar ``requirement`` of ``name``."""
    for owner, feature in features.items():
        for key in record(feature.get("surface_profile_governs")):
            if profile_target(owner, key) == (name, requirement):
                return feature.get("surface_profile", UNKNOWN)
    return None


def _zone(requirement, width, tolerance):
    numbers = {"requirement": requirement, "zone": width}
    if not number(width) or width <= 0:
        return UNKNOWN, {**numbers, "reason": f"{requirement} has no positive zone width"}
    needed = 2 * math.sqrt(2) * tolerance
    numbers["needed_zone"] = round(needed, 6)
    return (HOLDS if needed <= width + _EPS else EXCEEDS), numbers


def band_verdict(features, name, requirement, tolerance_mm, units):
    """``(holds | exceeds | unknown, numbers)``: whether the vendor's ± ``tolerance_mm``
    cut, aimed at the nominal, keeps ``requirement`` of feature ``name`` inside its band.
    Numbers are in the manifest's units."""
    feature = record(features.get(name))
    if not number(tolerance_mm) or tolerance_mm <= 0:
        return UNKNOWN, {"requirement": requirement, "reason": "vendor tolerance is unknown"}
    if units not in _SCALE:
        return UNKNOWN, {"requirement": requirement, "reason": f"manifest units {units!r}"}
    if requirement == UNKNOWN:
        return UNKNOWN, {"requirement": UNKNOWN, "reason": "requirement identities unresolved"}
    t = tolerance_mm / _SCALE[units]
    value = feature.get(requirement, UNKNOWN)
    if requirement in PLANAR_ZONES:
        return _zone(requirement, value, t)
    if requirement.endswith("_deg") or requirement not in LENGTH_REQUIREMENTS:
        return UNKNOWN, {
            "requirement": requirement,
            "reason": "a length cut tolerance does not bound this requirement",
        }
    if not isinstance(value, list):
        zone = _governing_zone(features, name, requirement)
        if zone is not None:
            return _zone(requirement, zone, t)
        return UNKNOWN, {"requirement": requirement, "reason": "no two-limit band to hold"}
    if not (len(value) == 2 and all(number(v) for v in value) and value[0] <= value[1]):
        return UNKNOWN, {"requirement": requirement, "reason": "band limits are unknown"}
    low, high = value
    numbers = {"requirement": requirement, "band": value, "tolerance": round(t, 6)}
    middle = nominal(feature, requirement)
    if middle == UNKNOWN:
        if high - low < 2 * t - _EPS:
            return EXCEEDS, {**numbers, "band_width": round(high - low, 6)}
        return UNKNOWN, {**numbers, "reason": "the band's nominal is not exported"}
    below, above = (middle - t) - low, high - (middle + t)
    numbers.update(nominal=middle, low_margin=round(below, 6), high_margin=round(above, 6))
    return (HOLDS if min(below, above) >= -_EPS else EXCEEDS), numbers


def _owners(bundle, facts):
    """``{face index: [feature]}`` over exported features, or the features whose faces are
    unresolved (an unresolved face list cannot establish that it owns no as-is face)."""
    mapping = record(facts.get("mapping"))
    owners, unresolved = {}, []
    for name, feature in record(bundle.features.get("features")).items():
        refs = feature.get("faces", UNKNOWN)
        if not isinstance(refs, list) or any(ref not in mapping for ref in refs):
            unresolved.append(name)
            continue
        for ref in refs:
            owners.setdefault(mapping[ref], []).append(name)
    return owners, unresolved


def _face(bundle, facts, ref, owners, tolerances):
    """One as-is face's credit row: its contact, owners and band verdicts."""
    contact = record(record(facts.get("as_is_contact")).get(ref))
    names = sorted(owners.get(record(facts.get("mapping")).get(ref), ()))
    row = {"ref": ref, "contact": contact.get("contact", UNKNOWN)}
    row.update({key: contact[key] for key in ("max_gap_mm", "supplies") if key in contact})
    if row["contact"] == "off_supply":
        return {**row, "owners": names, "verdict": OFF_BLANK}
    if row["contact"] != "on_supply":
        reason = "the kernel measured no blank contact"
        return {**row, "owners": names, "verdict": UNKNOWN, "reason": reason}
    profiled = [tolerances[name] for name in contact.get("supplies", ()) if name in tolerances]
    if not profiled:
        # A bar component's as-is face: supplied as bar stock, credited as for bar stock.
        return {**row, "verdict": CREDITED}
    # Two profiled carriers (a face on a joint line) answer to the looser vendor tolerance.
    tolerance = max(profiled, key=lambda value: value if number(value) else math.inf)
    features = record(bundle.features.get("features"))
    units = bundle.features.get("units", UNKNOWN)
    checks = [
        {"feature": name, **numbers, "verdict": verdict}
        for name in names
        for requirement in tolerance_requirements(record(features.get(name)))
        for verdict, numbers in [band_verdict(features, name, requirement, tolerance, units)]
    ]
    row.update(owners=names, profile_tolerance_mm=tolerance, requirements=checks)
    verdicts = {check["verdict"] for check in checks}
    if EXCEEDS in verdicts:
        return {**row, "verdict": BAND}
    if UNKNOWN in verdicts or not number(tolerance):
        return {**row, "verdict": UNKNOWN}
    return {**row, "verdict": CREDITED}


def credit(bundle, facts):
    """``{as-is ref: credit row}`` for a plan with a profiled supply; ``{}`` otherwise.

    Only rows whose ``verdict`` is ``credited`` count toward coverage."""
    supplies = profiled_supplies(bundle)
    refs = record(bundle.plan.get("stock")).get("as_is_faces", UNKNOWN)
    if not supplies or not isinstance(refs, list):
        return {}
    owners, unresolved = _owners(bundle, facts)
    tolerances = {
        name: record(blank).get("profile_tolerance_mm", UNKNOWN) for name, blank in supplies.items()
    }
    rows = {}
    for ref in refs:
        if ref == UNKNOWN or ref not in record(facts.get("mapping")):
            continue  # Coverage already reports an unknown or unmapped as-is ref.
        row = _face(bundle, facts, ref, owners, tolerances)
        if unresolved and row["verdict"] == CREDITED and "owners" in row:
            row = {**row, "verdict": UNKNOWN, "unresolved_features": unresolved}
        rows[ref] = row
    return rows


def _text(row):
    """One face's verdict as a predicate, without its subject (:func:`_sentence`)."""
    if row["verdict"] == OFF_BLANK:
        return (
            f"lies {row.get('max_gap_mm', UNKNOWN)} mm off the supplied blank: it is buried "
            "in stock, not supplied as cut"
        )
    if row["verdict"] == BAND:
        failed = [check for check in row["requirements"] if check["verdict"] == EXCEEDS]
        return "is out of band as cut: " + "; ".join(map(_exceeds, failed))
    if row["verdict"] == UNKNOWN:
        return f"has undecided credit ({_undecided(row)})"
    return "is supplied as cut"


def _sentence(owner, faces):
    """Each distinct verdict once: for the whole feature when its faces share it."""
    reasons = {}
    for row in faces:
        reasons.setdefault(_text(row), []).append(row["ref"])
    if len(reasons) == 1:
        (reason,) = reasons
        whole = "its face" if len(faces) == 1 else f"each of its {len(faces)} faces"
        return f"{owner}: {whole} {reason}"
    return f"{owner}: " + "; ".join(
        f"{refs[0] if len(refs) == 1 else 'each of ' + ', '.join(refs)} {reason}"
        for reason, refs in reasons.items()
    )


def _exceeds(check):
    name, requirement, t = check["feature"], check["requirement"], check.get("tolerance")
    if "zone" in check:
        return (
            f"{name} {requirement} zone {check['zone']:g} is narrower than the "
            f"{check['needed_zone']:g} the cut needs"
        )
    low, high = check["band"]
    if "nominal" not in check:
        return (
            f"{name} {requirement} band {low:g}-{high:g} is narrower than the vendor's "
            f"±{t:g} spread"
        )
    side, margin = min(
        (("below", check["low_margin"]), ("above", check["high_margin"])), key=lambda m: m[1]
    )
    return (
        f"{name} {requirement} {check['nominal']:g} ±{t:g} exits its band {low:g}-{high:g} "
        f"by {-margin:g} {side}"
    )


def _undecided(row):
    if row.get("reason"):
        return row["reason"]
    if row.get("unresolved_features"):
        return "faces of " + ", ".join(row["unresolved_features"]) + " are unresolved"
    reasons = [
        f"{check['feature']} {check['requirement']}: {check.get('reason', 'unknown')}"
        for check in row.get("requirements", ())
        if check["verdict"] == UNKNOWN
    ]
    return "; ".join(reasons) or "the vendor tolerance is unknown"


def evaluate(bundle):
    supplies = profiled_supplies(bundle)
    if not supplies:
        return []
    from prechips.kernel import run_geometry

    facts = run_geometry(bundle)
    subject = bundle.plan["part"]
    cite = provenance(bundle, RULE) + [
        "plan.stock.as_is_faces; kernel as_is_contact (STOCK_TOL 1e-3 mm)",
        *[
            f"{name}.blank: {blank.get('step', UNKNOWN)} SHA-256 "
            f"{blank.get('step_sha256', UNKNOWN)}, ±{blank.get('profile_tolerance_mm', UNKNOWN)} mm"
            for name, blank in sorted(supplies.items())
        ],
        *[text for blank in supplies.values() for text in _citations(record(blank).get("cite"))],
    ]
    blocked = unavailable(bundle, RULE, subject, facts, cite)
    if blocked:
        return [blocked]
    groups = {}
    for row in credit(bundle, facts).values():
        if "owners" not in row and row["verdict"] == CREDITED:
            continue  # A bar component's face: no vendor tolerance to judge.
        for owner in row.get("owners") or [row["ref"]]:
            groups.setdefault(owner, []).append(row)
    findings = []
    for owner, faces in sorted(groups.items()):
        verdicts = {row["verdict"] for row in faces}
        status = (
            "error"
            if verdicts & {OFF_BLANK, BAND}
            else "unknown"
            if UNKNOWN in verdicts
            else "pass"
        )
        values = {"faces": faces}
        sentence = _sentence(owner, faces) + "."
        if status == "error":
            sentence += " Not credited as supplied: each face refused here needs a cutting op."
        findings.append(Finding(RULE, owner, status, values, cite, sentence))
    return findings
