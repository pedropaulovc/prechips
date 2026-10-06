"""Measured mill spindle-nose bands between table-clearance limits."""

from prechips.findings import Finding
from prechips.rules import tip_endpoints
from prechips.rules._envelope import (
    _band,
    _point,
    authoring_entry,
    fact,
    fixture_height,
    machine_envelope,
    spindle_nose_band,
    stock_extents,
    transformed_bounds,
    unknown_sentence,
)
from prechips.rules.coordinates import CENTRE_OPS
from prechips.rules.resolution import (
    MANUAL,
    SAW_OPS,
    UNKNOWN,
    number,
    plan_frame_cite,
    record,
    same_length,
    saw_setup,
    setup_frame_ref,
)


def evaluate(bundle):
    features = record(bundle.features.get("features"))
    frames = record(bundle.features.get("frames"))
    endpoints = {
        (row["setup"], row["op"], row["feature"]): row
        for finding in tip_endpoints.evaluate(bundle)
        for row in finding.numbers["endpoints"]
    }
    findings = []
    for setup in bundle.plan["setups"]:
        machine, _ = machine_envelope(bundle, setup)
        cite = ["PLAN.md §8 M5; docs/rules-setup.md envelope: conservative setup stack"]
        if saw_setup(setup):
            findings.append(
                Finding(
                    "envelope",
                    setup["id"],
                    "not_applicable",
                    {},
                    cite,
                    "A dedicated saw setup has no spindle-nose-to-table stack.",
                )
            )
            continue
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
        target, owner = setup_frame_ref(bundle, setup)
        cite.extend(plan_frame_cite(bundle, setup))
        initial_top = record(setup.get("stock_state")).get("top_z", UNKNOWN)
        if missing:
            authoring_entry(
                debts,
                f"plan.setups.{setup['id']}.supported_height",
                missing[-1],
                f"plan.setups.{setup['id']}.stock_state",
            )
        stacks = []
        for op, before, _ in tip_endpoints.stock_states(setup, features):
            # Saw cuts have no spindle stack; the setup's other cutting ops are still assessed.
            if op.get("do") in MANUAL or op.get("do") in SAW_OPS:
                continue
            label = f"plan.setups.{setup['id']}.ops.{op['op']}"
            name = op.get("feature", UNKNOWN)
            feature = record(features.get(name))
            source = record(frames.get(feature.get("frame", "model")))
            extent = transformed_bounds(feature.get("bounds"), source, target)
            if op.get("do") in CENTRE_OPS:
                extent = _point(feature, source, target)
            cite.extend(
                [
                    f"features.features.{name}.bounds/at",
                    f"features.frames.{feature.get('frame', 'model')}; "
                    f"{owner}.{setup.get('frame')}",
                ]
            )
            assembly = spindle_nose_band(
                bundle,
                op,
                before,
                extent,
                endpoints.get((setup["id"], op["op"], name)),
                debts,
                cite,
                missing,
                errors,
                label,
            )
            gauge, projection = assembly["gauge"], assembly["projection"]
            values = (height, fixture, gauge["value"], projection["value"])
            stack = sum(values) if all(number(value) for value in values) else UNKNOWN
            nose = assembly["nose_band_mm"]
            table_band = (
                [fixture + height - initial_top + value for value in nose]
                if _band(nose) and all(number(value) for value in (fixture, height, initial_top))
                else UNKNOWN
            )
            verified = (
                fixture_verified and assembly["verified"] and number(height) and _band(table_band)
            )
            if verified and any(value < 0 for value in values):
                errors.append(f"op {op['op']} has a negative measured stack dimension")
                verified = False
            lower, upper = table_band if _band(table_band) else (UNKNOWN, UNKNOWN)
            upper_margin = (
                maximum["value"] - upper
                if all(number(v) for v in (maximum["value"], upper))
                else UNKNOWN
            )
            lower_margin = (
                lower - minimum["value"]
                if all(number(v) for v in (minimum["value"], lower))
                else UNKNOWN
            )
            if number(upper_margin) and same_length(maximum["value"], upper):
                upper_margin = 0
            if number(lower_margin) and same_length(minimum["value"], lower):
                lower_margin = 0
            if verified and maximum["verified"] and number(upper_margin) and upper_margin < 0:
                errors.append(
                    f"op {op['op']} required spindle-nose height {upper:g} mm exceeds "
                    f"spindle-to-table maximum {maximum['value']:g} mm by {-upper_margin:g} mm"
                )
            if verified and minimum["verified"] and number(lower_margin) and lower_margin < 0:
                errors.append(
                    f"op {op['op']} deepest spindle-nose height {lower:g} mm is below "
                    f"spindle-to-table minimum {minimum['value']:g} mm by {-lower_margin:g} mm"
                )
            stacks.append(
                {
                    "op": op["op"],
                    "holder": op.get("holder", UNKNOWN),
                    "tool": op.get("tool", UNKNOWN),
                    "holder_gauge_len_mm": gauge["value"],
                    "tool_projection_mm": projection["value"],
                    "stack_mm": stack,
                    "approach_mm": op.get("approach_mm", UNKNOWN),
                    "tip_z_bounds_mm": assembly["tip_band_mm"],
                    "spindle_nose_table_band_mm": table_band,
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
                        "measured fixture bed/height + parallels/supports + supported part height "
                        "+ selected holder gauge + tool/holder projection "
                        "+ tip Z relative to part top; "
                        "authored approach and deepest cut included; not a collision proof"
                    ),
                },
                sorted(set(cite)),
                sentence,
            )
        )
    return findings
