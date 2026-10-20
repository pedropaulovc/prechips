"""Measured grip-zone wall below the shop floor needs a named protective method."""

from math import isfinite

from prechips.findings import Finding
from prechips.rules._bench import manual_bench, not_applicable, unfixtured_handling
from prechips.rules.geometry_common import (
    fact_reason,
    setup_contexts,
    strap_clamped,
    with_measurement_debts,
)
from prechips.rules.resolution import number, record, same_length

# Tape is a typed area hold (hold.area), never a method name.
_PROTECTED = {"soft_jaws", "soft jaws", "mandrel", "wax"}


def _finite_number(value):
    return number(value) and (isinstance(value, int) or isfinite(value))


def _proven_wall_bounds(detail):
    """Accept only native, common-contact bounds on the same loaded ligament."""
    bounds = record(detail.get("min_wall_bounds_mm"))
    proof = record(detail.get("material_wall"))
    contact = record(detail.get("material_contact"))
    material = record(detail.get("stock_material"))
    lower, upper = bounds.get("lower"), bounds.get("upper")
    samples = proof.get("sample_count")
    if (
        detail.get("min_wall_mm", "unknown") != "unknown"
        or proof.get("model") != "bounded_wall_rays_v1"
        or proof.get("status") != "pass"
        or proof.get("state") != "bounded"
        or proof.get("metric") != "contact_loaded_ligament"
        or not isinstance(samples, int)
        or isinstance(samples, bool)
        or samples <= 0
        or contact.get("model") != "common_exterior_v1"
        or contact.get("status") != "pass"
        or contact.get("outside_unmodeled_regions") != "proved"
        or material.get("model") != "bounded_material_v1"
        or material.get("state") != "bounded"
        or not _finite_number(lower)
        or not _finite_number(upper)
        or not 0 <= lower <= upper
    ):
        return None
    return lower, upper


def evaluate(bundle):
    rows = []
    floor = record(bundle.policy.get("numbers")).get("thin_wall_floor_mm", "unknown")
    verified = bundle.policy.get("numbers_verify", False)
    if (
        verified == "unknown"
        or verified is True
        or isinstance(verified, dict)
        and verified.get("thin_wall_floor_mm", False) is not False
    ):
        floor = "unknown"
    for setup, _, detail, inputs, cite, blocked in setup_contexts(bundle, "thin_wall_under_clamp"):
        bench = manual_bench(bundle, setup)
        hold = setup.get("hold", {})
        if isinstance(hold, dict) and unfixtured_handling(bench, hold):
            rows.append(
                not_applicable(
                    "thin_wall_under_clamp", setup, bench, "holding", "clamping load on a wall"
                )
            )
            continue
        cite = cite + [
            "shop-policy.numbers.thin_wall_floor_mm; "
            "PLAN.md §4.3 named soft jaws / mandrel / tape / wax"
        ]
        if blocked:
            rows.append(blocked)
            continue
        subject = setup["id"]
        wall, method = detail.get("min_wall_mm", "unknown"), inputs.get("method", "unknown")
        values = {"min_wall_mm": wall, "thin_wall_floor_mm": floor, "method": method}
        # Strap holds: the run under each posed strap footprint along its clamp force.
        straps = strap_clamped(inputs) and inputs["kind"] != "vise"
        zone = "under the strap footprints" if straps else "inside the grip zone"
        debts = detail.get("strap_wall_debts", []) if straps else []
        if debts:
            values["strap_wall_debts"] = debts
        status, message = (
            "unknown",
            fact_reason(
                detail,
                ("min_wall_mm",),
                "grip-zone wall thickness or shop thin-wall floor is unmeasured",
            ),
        )
        if "min_wall_bounds_mm" in detail:
            values["min_wall_bounds_mm"] = detail["min_wall_bounds_mm"]
            for key in ("material_wall", "material_contact", "stock_material"):
                if key in detail:
                    values[key] = detail[key]
            bounds = _proven_wall_bounds(detail)
            message = "minimum wall interval or its native material/contact proof is unresolved"
            if bounds is not None and _finite_number(floor) and floor > 0:
                lower, upper = bounds
                if lower >= floor:
                    status, message = (
                        "pass",
                        f"minimum wall lower bound {zone} meets the shop floor",
                    )
                    if debts:
                        status = "unknown"
                        message = (
                            "drawn straps meet the shop floor but other clamps are unresolved: "
                            + "; ".join(debts)
                        )
                elif str(method).strip().lower() in _PROTECTED:
                    status, message = (
                        "pass",
                        f"bounded wall {zone} has a named protective holding method",
                    )
                    if debts:
                        status = "unknown"
                        message = "protective holding leaves other clamps unresolved: " + "; ".join(
                            debts
                        )
                elif upper < floor:
                    status, message = (
                        "error",
                        f"minimum wall upper bound {zone} is below the shop floor",
                    )
                else:
                    message = "minimum wall interval straddles the shop floor"
            elif bounds is not None:
                message = "shop thin-wall floor is unmeasured"
        elif number(wall) and wall > 0 and number(floor) and floor > 0:
            if wall >= floor or same_length(wall, floor):
                status, message = "pass", f"minimum wall {zone} meets the shop floor"
                if debts:
                    # An undrawn or non-bearing clamp may load a thinner wall.
                    status = "unknown"
                    message = (
                        "drawn straps meet the shop floor but other clamps are unresolved: "
                        + "; ".join(debts)
                    )
            elif method == "unknown":
                message = "wall is below the shop floor and protective holding method is unknown"
            elif str(method).strip().lower() in _PROTECTED:
                status, message = (
                    "pass",
                    "wall is below the shop floor with a named protective holding method",
                )
            else:
                status, message = (
                    "error",
                    "wall is below the shop floor; name soft jaws, mandrel or wax, "
                    "or hold it by area (hold.area)",
                )
        rows.append(
            with_measurement_debts(
                Finding(
                    "thin_wall_under_clamp", subject, status, values, cite, f"{subject}: {message}."
                ),
                inputs["measurement_debts"],
            )
        )
    return rows
