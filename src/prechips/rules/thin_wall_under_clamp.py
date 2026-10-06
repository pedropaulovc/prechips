"""Measured grip-zone wall below the shop floor needs a named protective method."""

from prechips.findings import Finding
from prechips.rules.geometry_common import fact_reason, setup_contexts, strap_clamped
from prechips.rules.resolution import number, record, same_length

_PROTECTED = {"soft_jaws", "soft jaws", "mandrel", "tape", "wax"}


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
        if number(wall) and wall > 0 and number(floor) and floor > 0:
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
                    "wall is below the shop floor; name soft jaws, mandrel, tape or wax",
                )
        rows.append(
            Finding(
                "thin_wall_under_clamp", subject, status, values, cite, f"{subject}: {message}."
            )
        )
    return rows
