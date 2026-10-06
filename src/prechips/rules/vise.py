"""Parallel gripping pair, opening, bilateral contact, jaw exclusion and parallels."""

from prechips.findings import Finding
from prechips.rules.geometry_common import fact_reason, setup_contexts
from prechips.rules.resolution import number, same_length


def evaluate(bundle):
    rows = []
    for setup, _, detail, inputs, cite, blocked in setup_contexts(bundle, "vise"):
        if blocked:
            rows.append(blocked)
            continue
        subject = setup["id"]
        width = detail.get("width_mm", "unknown")
        contacts = detail.get("contact_grip_mm", "unknown")
        parallel = detail.get("parallel_pair", "unknown")
        inside = detail.get("claimed_in_jaws", "unknown")
        opening, grip = inputs["opening_mm"], inputs["grip_mm"]
        values = {
            "width_mm": width,
            "opening_mm": opening,
            "contact_grip_mm": contacts,
            "required_grip_mm": grip,
            "parallel_pair": parallel,
            "claimed_in_jaws": inside,
            "parallels_height_mm": inputs["parallels_height_mm"],
        }
        known = (
            isinstance(parallel, bool)
            and number(width)
            and isinstance(contacts, list)
            and len(contacts) == 2
            and all(number(value) and value >= 0 for value in contacts)
            and isinstance(inside, list)
        )
        errors = []
        if known:
            if not parallel:
                errors.append("gripped faces are not a parallel pair")
            if width > opening and not same_length(width, opening):
                errors.append("part width exceeds vise opening")
            if any(value < grip and not same_length(value, grip) for value in contacts):
                errors.append("both jaws do not provide the declared grip")
            if inside:
                errors.append("claimed faces enter jaw solids: " + ", ".join(inside))
        status = "error" if errors else "pass" if known else "unknown"
        message = (
            "; ".join(errors)
            if errors
            else "parallel gripped faces, opening, both-jaw grip and claimed-face "
            "exclusion fit the declared vise hold"
            if known
            else fact_reason(
                detail,
                ("parallel_pair", "width_mm", "contact_grip_mm", "claimed_in_jaws"),
                "vise contact geometry is unresolved",
            )
        )
        rows.append(Finding("vise", subject, status, values, cite, f"{subject}: {message}."))
    return rows
