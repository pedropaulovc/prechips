"""M5 conservative setup stack between measured spindle-to-table limits."""

from prechips.findings import Finding
from prechips.rules._envelope import (
    fact,
    fixture_height,
    machine_envelope,
    measurement_item,
    stock_extents,
    tool_projection,
    unknown_sentence,
)
from prechips.rules.resolution import MANUAL, UNKNOWN, number, same_length


def evaluate(bundle):
    findings = []
    for setup in bundle.plan["setups"]:
        machine, _ = machine_envelope(bundle, setup)
        cite = ["PLAN.md §8 M5; docs/rules-setup.md envelope: conservative setup stack"]
        if machine.get("kind") == "lathe":
            findings.append(
                Finding(
                    "envelope",
                    setup["id"],
                    "not_applicable",
                    {},
                    cite,
                    "Spindle-nose-to-table clearance applies to a mill, not a lathe.",
                )
            )
            continue
        debts, missing, errors = {}, [], []
        maximum = fact(
            machine, "envelope.spindle_to_table_max", "machines", setup["machine"], debts, cite
        )
        minimum = fact(
            machine, "envelope.spindle_to_table_min", "machines", setup["machine"], debts, cite
        )
        extents, extent_cite = stock_extents(bundle, setup)
        if maximum["verified"] and minimum["verified"]:
            if minimum["value"] < 0 or maximum["value"] < minimum["value"]:
                errors.append(
                    "measured spindle-to-table limits are negative or reversed; "
                    "remeasure both Z stops"
                )
        cite.extend(extent_cite)
        height = extents["z"]
        if not number(height):
            missing.append(
                f"measure: {setup['id']} supported blank height and setup orientation, "
                "caliper and square, mm; author stock/stock_state and frame"
            )
        elif height <= 0:
            errors.append("supported stock height is not positive")
        fixture, fixture_verified = fixture_height(bundle, setup, debts, cite)
        stacks = []
        for op in setup["ops"]:
            if op.get("do") in MANUAL:
                continue
            holder_ref = op.get("holder", UNKNOWN)
            holder = measurement_item(bundle, "holders", holder_ref)
            gauge = fact(holder, "gauge_len", "holders", holder_ref, debts, cite)
            projection = tool_projection(bundle, op, debts, cite)
            values = (height, fixture, gauge["value"], projection["value"])
            stack = sum(values) if all(number(value) for value in values) else UNKNOWN
            verified = (
                fixture_verified and gauge["verified"] and projection["verified"] and number(height)
            )
            if verified and any(value < 0 for value in values):
                errors.append(f"op {op['op']} has a negative measured stack dimension")
                verified = False
            upper_margin = (
                maximum["value"] - stack
                if all(number(v) for v in (maximum["value"], stack))
                else UNKNOWN
            )
            lower_margin = (
                stack - minimum["value"]
                if all(number(v) for v in (minimum["value"], stack))
                else UNKNOWN
            )
            if number(upper_margin) and same_length(maximum["value"], stack):
                upper_margin = 0
            if number(lower_margin) and same_length(minimum["value"], stack):
                lower_margin = 0
            if verified and maximum["verified"] and number(upper_margin) and upper_margin < 0:
                errors.append(
                    f"op {op['op']} setup stack {stack:g} mm exceeds spindle-to-table maximum "
                    f"{maximum['value']:g} mm by {-upper_margin:g} mm"
                )
            if verified and minimum["verified"] and number(lower_margin) and lower_margin < 0:
                errors.append(
                    f"op {op['op']} setup stack {stack:g} mm is below spindle-to-table minimum "
                    f"{minimum['value']:g} mm by {-lower_margin:g} mm"
                )
            stacks.append(
                {
                    "op": op["op"],
                    "holder": holder_ref,
                    "tool": op.get("tool", UNKNOWN),
                    "holder_gauge_len_mm": gauge["value"],
                    "tool_projection_mm": projection["value"],
                    "stack_mm": stack,
                    "upper_margin_mm": upper_margin,
                    "lower_margin_mm": lower_margin,
                    "verified": bool(verified),
                }
            )
        if not stacks:
            findings.append(
                Finding(
                    "envelope",
                    setup["id"],
                    "not_applicable",
                    {},
                    cite,
                    "No cutting assembly needs a spindle-to-table envelope in this setup.",
                )
            )
            continue
        unknown = bool(debts or missing) or not all(row["verified"] for row in stacks)
        status = "error" if errors else "unknown" if unknown else "pass"
        sentence = (
            f"{setup['id']}: " + "; ".join(errors) + "."
            if errors
            else unknown_sentence(
                setup["id"], "spindle envelope remains unmeasured or unresolved", debts, missing
            )
            if unknown
            else (
                f"{setup['id']}: measured part, fixture and tool stacks fit between "
                "spindle-to-table minimum and maximum."
            )
        )
        findings.append(
            Finding(
                "envelope",
                setup["id"],
                status,
                {
                    "part_extents_mm": extents,
                    "fixture_height_mm": fixture,
                    "spindle_to_table_max_mm": maximum["value"],
                    "spindle_to_table_min_mm": minimum["value"],
                    "stacks": stacks,
                    "measurements": [debts[key] for key in sorted(debts)],
                    "basis": (
                        "conservative jaw height + parallels/supports + supported stock height "
                        "+ holder gauge + tool projection; not a collision proof"
                    ),
                },
                sorted(set(cite)),
                sentence,
            )
        )
    return findings
