"""A saw removes its kerf and discarded side, never any of the finished target.

A straight cut is located by its blade-centre ``cut_plane``; one that ``follows`` an earlier
scribe op's line removes only its declared ``stock_removal_bounds`` and must leave at least
its ``allowance_mm`` of stock between that region and the finished target for the file.
"""

import math
from dataclasses import replace

from prechips.findings import Finding
from prechips.material_routes import feature_material_status
from prechips.measurements import length_debt, length_fact, tooth_pitch_fact
from prechips.rules.geometry_common import (
    kernel_measurement_debts,
    prepared_job,
    unavailable,
    with_measurement_debts,
)
from prechips.rules.resolution import (
    SAW_OPS,
    SLITTING_SAW_MODEL_REASON,
    UNKNOWN,
    _citations,
    number,
    operations,
    record,
    resolve,
    saw_station,
    saw_tool,
    select,
    slitting_saw,
    uncertain,
)

_VOLUMES = ("removed_volume_mm3", "stock_volume_before_mm3", "stock_volume_after_mm3")
_FACTS = (
    "kerf_mm",
    "retained_boundary_mm",
    "kerf_volume_mm3",
    "offcut_volume_mm3",
    *_VOLUMES,
)
# A cut that follows a scribed line removes one declared region: its kerf and offcut are
# not separate solids, and the blade's kerf locates nothing.
_SCRIBED_FACTS = ("allowance_mm", "retained_to_target_mm", *_VOLUMES)


_MISMATCH = {
    "not_a_saw": "selected saw tool is not a bandsaw blade, hand saw or mill slitting saw",
    "hand_saw": "a hand saw cuts only at a bench or manual station",
    "bandsaw": "saw cut-off requires a mill, bench or bandsaw machine",
    "slitting_saw": "a spindle-mounted slitting saw cuts only on a mill",
    "scribed_bandsaw": "a bandsaw blade follows a scribed line only on a vertical bandsaw",
    "no_vertical_mode": "the bandsaw declares no vertical saw_modes, so it cannot follow a "
    "scribed line",
}


def scribe_material_status(bundle, setup, op):
    """Whether the ``follows`` witness is on this saw's material, not just its history.

    The plan validates the witness's existence and order. A pre-partition scribe
    still needs material ownership and registration before it can locate a cut.
    """
    sid, separator, number_ = str(op.get("follows", UNKNOWN)).partition(":")
    if not separator:
        return None
    witness = next(
        (
            (earlier, scribe)
            for earlier, scribe in operations(bundle)
            if earlier.get("id") == sid and str(scribe.get("op")) == number_
        ),
        None,
    )
    if witness is None:
        return None
    earlier, scribe = witness
    if scribe.get("do") != "scribe":
        return None if scribe.get("do") in (None, UNKNOWN) else False
    feature = scribe.get("feature")
    if not isinstance(feature, str) or feature == UNKNOWN:
        return None
    return feature_material_status(
        bundle.plan, setup["id"], earlier["id"], feature, bundle
    )


def evaluate(bundle):
    from prechips.kernel import run_geometry

    cuts = [(setup, op) for setup, op in operations(bundle) if op.get("do") in SAW_OPS]
    if not cuts:
        return []
    facts = run_geometry(bundle)
    findings = []
    job = None
    for setup, op in cuts:
        subject = f"{setup['id']}:{op['op']}"
        scribed = "follows" in op
        tool = saw_tool(bundle, op)
        machine = record(resolve(bundle, "machines", setup.get("machine")))
        blade = record(resolve(bundle, "tools", op.get("tool")))
        kerf = length_fact(blade, "kerf", require_measured=False)
        detail = record(record(facts.get("ops")).get(subject))
        fields = _SCRIBED_FACTS if scribed else _FACTS
        numbers = {"operation": op["do"], "tool": op.get("tool", UNKNOWN)}
        if scribed:
            numbers["follows"] = op["follows"]
            numbers["stock_removal_bounds"] = op.get("stock_removal_bounds", UNKNOWN)
        else:
            numbers["cut_plane"] = detail.get("cut_plane", op.get("cut_plane", UNKNOWN))
        numbers.update({field: detail.get(field, UNKNOWN) for field in fields})
        if tool == "hand_saw" and not scribed:
            # A bench has no DRO: the card measures the kept piece, not a coordinate.
            numbers["retained_length_mm"] = detail.get("retained_length_mm", UNKNOWN)
        where = f"plan.setups.{setup['id']}.ops.{op['op']}"
        cite = (
            [
                f"{where}.follows",
                f"{where}.allowance_mm",
                f"{where}.stock_removal_bounds",
                "docs/rules-geometry.md: saw to a scribed line",
            ]
            if scribed
            else [
                f"{where}.cut_plane",
                f"inventory.tools.{op.get('tool', UNKNOWN)}.kerf",
                "docs/rules-geometry.md: saw cut-off",
                *kerf["cite"],
            ]
        )
        debts = []
        if blade and not scribed:
            category, identity, _ = select(bundle, op.get("tool"), "tools")
            debt = length_debt(blade, "kerf", category, identity)
            if debt is not None:
                debts.append(debt)
        invalid = []
        missing = []
        if scribed:
            material = scribe_material_status(bundle, setup, op)
            numbers["scribe_on_arriving_stock"] = UNKNOWN if material is None else material
            if material is None:
                missing.append(
                    f"whether {op['follows']}'s scribed line survives the material partition "
                    "and registration is unknown"
                )
            elif material is False:
                invalid.append(f"{op['follows']}'s scribed line is not on this saw's material")
        disk = slitting_saw(bundle, op)
        if disk:
            # The planar Boolean describes an ideal complete cut, not whether a finite
            # disk and its arbor can make it. Even complete native slab facts stay debt.
            missing.append(SLITTING_SAW_MODEL_REASON)
            numbers["model_reason"] = SLITTING_SAW_MODEL_REASON
        station = saw_station(bundle, setup, op)
        if station == "wrong_station":
            invalid.append(_MISMATCH["scribed_bandsaw" if scribed and tool == "bandsaw" else tool])
        if station == "no_vertical_mode":
            invalid.append(_MISMATCH[station])
        if station == "unknown" and scribed and tool == "bandsaw":
            missing.append(
                f"declare the saw_modes of machine {setup.get('machine', UNKNOWN)}: a bandsaw "
                "blade follows a scribed line only in vertical mode"
            )
        if not scribed and kerf["verified"] and number(kerf["value"]) and kerf["value"] <= 0:
            invalid.append("blade kerf must be positive")
        if not machine or machine.get("kind", UNKNOWN) == UNKNOWN or uncertain(machine):
            missing.append("resolved, verified saw machine")
        if tool in ("unknown", "unverified"):
            label = {
                "hand_saw": "hand saw",
                "slitting_saw": "slitting saw",
            }.get(blade.get("kind"), "bandsaw blade")
            missing.append(f"resolved, verified {label}")
        if not scribed and (not kerf["verified"] or not number(kerf["value"])):
            missing.append("known, verified blade kerf")
        if scribed and not number(op.get("allowance_mm")):
            missing.append(
                f"declare allowance_mm for {subject}: the stock left outside the scribed line "
                "for the file"
            )
        if detail.get("saw_error"):
            invalid.append(detail["saw_error"])
        blocked = unavailable(bundle, "saw_cut", subject, facts, cite)
        if invalid:
            status, message = "error", "; ".join(invalid)
        elif blocked is not None:
            if disk:
                blocked = replace(
                    blocked,
                    numbers={**blocked.numbers, "model_reason": SLITTING_SAW_MODEL_REASON},
                    sentence=f"{blocked.sentence} {SLITTING_SAW_MODEL_REASON}.",
                )
            if blocked.status == UNKNOWN and facts.get("measurement_debts"):
                if job is None:
                    job = prepared_job(bundle)
                debts.extend(kernel_measurement_debts(job, setup, op, stock=True))
            findings.append(with_measurement_debts(blocked, debts))
            continue
        else:
            reason = detail.get("saw_reason", detail.get("stock_reason"))
            if reason:
                missing.append(reason)
            if not all(number(detail.get(field)) for field in fields):
                missing.append(
                    "native saw stock volumes and clearance to the target"
                    if scribed
                    else "native saw stock/kerf/offcut volumes"
                )
            status = "unknown" if missing else "pass"
            message = (
                "; ".join(missing)
                if missing
                else "the declared removal stays outside the scribed line by at least its "
                "allowance; the retained piece keeps that stock for the file"
                if scribed
                else "blade kerf and discarded slab remove only excess stock; "
                "the retained piece preserves the finished target"
            )
        finding = Finding("saw_cut", subject, status, numbers, cite, f"{subject}: {message}.")
        if status == UNKNOWN and facts.get("measurement_debts") and detail.get("stock_reason"):
            if job is None:
                job = prepared_job(bundle)
            debts.extend(kernel_measurement_debts(job, setup, op, stock=True))
        findings.append(with_measurement_debts(finding, debts))
    return findings


MM_PER_INCH = 25.4
_MIN_TEETH = "saw_min_teeth_in_work"


def min_teeth(bundle):
    """(the shop policy ``numbers.saw_min_teeth_in_work``, its citations): unknown when
    absent, not positive, uncited or not explicitly verified (``numbers_verify`` false)."""
    minimum = record(bundle.policy.get("numbers")).get(_MIN_TEETH, UNKNOWN)
    verify = bundle.policy.get("numbers_verify", False)
    if isinstance(verify, dict):
        verify = verify.get(_MIN_TEETH, False)
    cited = _citations(record(bundle.policy.get("numbers_cite")).get(_MIN_TEETH))
    known = number(minimum) and minimum > 0 and verify is False and bool(cited)
    return (minimum if known else UNKNOWN), cited


def evaluate_teeth(bundle):
    """Teeth in the work: the thickness the blade crosses times the blade's coarsest
    pitch must reach the shop's minimum, or the teeth straddle the work and strip."""
    from prechips.kernel import run_geometry

    cuts = [(setup, op) for setup, op in operations(bundle) if op.get("do") in SAW_OPS]
    if not cuts:
        return []
    facts = run_geometry(bundle)
    minimum, policy_cite = min_teeth(bundle)
    findings = []
    for setup, op in cuts:
        subject = f"{setup['id']}:{op['op']}"
        tool = op.get("tool", UNKNOWN)
        if slitting_saw(bundle, op):
            findings.append(
                Finding(
                    "saw_teeth",
                    subject,
                    UNKNOWN,
                    {
                        "operation": op["do"],
                        "tool": tool,
                        "tooth_count": record(resolve(bundle, "tools", tool)).get(
                            "flutes", UNKNOWN
                        ),
                        "teeth_in_work": UNKNOWN,
                        "engagement_arc_deg": UNKNOWN,
                    },
                    [
                        f"inventory.tools.{tool}.flutes",
                        "docs/rules-geometry.md: saw teeth in the work",
                    ],
                    f"{subject}: circular slitting-saw tooth engagement needs the finite "
                    "disk, arbor and feed trajectory; the planar stock section and a linear "
                    "blade's TPI cannot establish teeth in the work.",
                )
            )
            continue
        pitch = tooth_pitch_fact(record(resolve(bundle, "tools", tool)))
        detail = record(record(facts.get("ops")).get(subject))
        thickness = detail.get("cut_thickness_mm", UNKNOWN)
        coarse = pitch["value"] if pitch["verified"] else UNKNOWN
        numbers = {
            "operation": op["do"],
            "tool": tool,
            "tpi": pitch["declared"],
            "tpi_coarse": coarse,
            "cut_thickness_mm": thickness,
            "cut_thickness_axis": "z"
            if "follows" in op
            else detail.get("cut_thickness_axis", UNKNOWN),
            "teeth_in_work": UNKNOWN,
            _MIN_TEETH: minimum,
        }
        cite = [
            f"inventory.tools.{tool}.tpi",
            *pitch["cite"],
            f"shop-policy.numbers.{_MIN_TEETH}",
            *policy_cite,
            "docs/rules-geometry.md: saw teeth in the work",
        ]
        blocked = unavailable(bundle, "saw_teeth", subject, facts, cite)
        if blocked is not None:
            findings.append(blocked)
            continue
        missing = []
        if tool == UNKNOWN:
            missing.append("select a saw blade for this op: its tooth pitch is unknown")
        elif coarse == UNKNOWN:
            missing.append(
                f"declare tools.{tool}.tpi with its citation: {pitch['reason'].rstrip('.')}"
            )
        if minimum == UNKNOWN:
            missing.append(f"the shop policy sets no cited, verified numbers.{_MIN_TEETH}")
        if not number(thickness) or thickness <= 0:
            reason = record(detail.get("reasons")).get("cut_thickness_mm")
            reason = reason or detail.get("saw_reason") or detail.get("saw_error")
            missing.append(
                "the thickness the blade crosses is unknown" + (f" ({reason})" if reason else "")
            )
        if missing:
            message = "; ".join(missing)
            findings.append(
                Finding("saw_teeth", subject, UNKNOWN, numbers, cite, f"{subject}: {message}.")
            )
            continue
        teeth = thickness / MM_PER_INCH * coarse
        short = teeth < minimum - 1e-9
        # A count short of the minimum is shown rounded down, so it never prints as the
        # minimum it fails (2.995 teeth is 2.99, not 3.00).
        shown = math.floor(teeth * 100) / 100 if short else round(teeth, 2)
        numbers["teeth_in_work"] = shown
        declared = pitch["declared"]
        blade = (
            f"the {declared[0]:g}/{declared[1]:g} variable-pitch blade at its {coarse:g} TPI "
            "coarse end"
            if isinstance(declared, list)
            else f"the {coarse:g} TPI blade"
        )
        if short:
            # Rounded up: a printed pitch below the one needed would still fail.
            finer = math.ceil(minimum * MM_PER_INCH / thickness * 10 - 1e-9) / 10
            coarsest = "whose coarse end is " if isinstance(declared, list) else "of "
            status = "error"
            message = (
                f"{shown:.2f} teeth of {blade} are in the "
                f"{thickness:.2f} mm the blade crosses, fewer than the shop's {minimum:g}; "
                f"the teeth straddle the work and strip: choose a blade {coarsest}at least "
                f"{finer:.1f} TPI"
            )
        elif detail.get("saw_error") or detail.get("saw_reason"):
            # Never pass a refused or unresolved cut on its pitch alone.
            status = UNKNOWN
            message = (
                f"{shown:.2f} teeth would be in the work, but the saw cut itself is "
                f"unresolved ({detail.get('saw_error') or detail.get('saw_reason')})"
            )
        else:
            status = "pass"
            message = (
                f"{shown:.2f} teeth of {blade} are in the "
                f"{thickness:.2f} mm the blade crosses, at least the shop's {minimum:g}"
            )
        findings.append(
            Finding("saw_teeth", subject, status, numbers, cite, f"{subject}: {message}.")
        )
    return findings
