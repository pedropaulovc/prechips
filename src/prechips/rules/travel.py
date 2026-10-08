"""Declared mill operation spans, not a toolpath or stock-position certificate.

Located cutter envelopes are unioned in setup axes. Unlocated broad cuts use
conservative stock spans without inventing where that stock sits in the frame.
A child feature (``hole``/``parent``) without its own ``at`` is located at its
parent's ``at`` in the parent's frame; it inherits no parent bounds.
Saw cuts drive no spindle cutter and are skipped.
"""

from prechips.findings import Finding
from prechips.rules import tip_endpoints
from prechips.rules._envelope import (
    _band,
    _known,
    _point,
    authoring_entry,
    fact,
    machine_envelope,
    selected_item,
    spindle_nose_band,
    stock_extents,
    transformed_bounds,
    unknown_sentence,
)
from prechips.rules.coordinates import AXES, CENTRE_OPS, located_by
from prechips.rules.resolution import (
    MANUAL,
    SAW_OPS,
    UNKNOWN,
    _citations,
    record,
    rough_leave,
    same_length,
    saw_setup,
    setup_frame_ref,
)


def _input_cite(item, label):
    item = record(item)
    return [label, *_citations(item.get("cite")), *_citations(item.get("source"))]


def _include(bands, band):
    if _band(band):
        bands.append(band)


def _span(bands):
    return max(band[1] for band in bands) - min(band[0] for band in bands) if bands else UNKNOWN


def evaluate(bundle):
    features = bundle.feature_definitions
    frames = record(bundle.features.get("frames"))
    endpoints = {
        (row["setup"], row["op"], row["feature"]): row
        for finding in tip_endpoints.evaluate(bundle)
        for row in finding.numbers["endpoints"]
    }
    findings = []
    for setup in bundle.plan["setups"]:
        machine_ref, machine = machine_envelope(bundle, setup)
        cite = _input_cite(setup, f"plan.setups.{setup['id']}")
        cite.extend(_input_cite(machine, f"inventory.machines.{machine_ref}"))
        if machine.get("kind") == "lathe":
            findings.append(
                Finding(
                    "travel",
                    setup["id"],
                    "not_applicable",
                    {},
                    cite,
                    f"{setup['id']}: mill XYZ travel does not apply to a lathe.",
                )
            )
            continue
        if saw_setup(setup):
            findings.append(
                Finding(
                    "travel",
                    setup["id"],
                    "not_applicable",
                    {},
                    cite,
                    f"{setup['id']}: saw cuts drive no spindle cutter, so mill XYZ "
                    "cutter travel does not apply.",
                )
            )
            continue
        debts, missing, errors, operations = {}, [], [], []
        bands = {axis: [] for axis in AXES}
        scalar_spans = {axis: [] for axis in AXES}
        complete = {axis: True for axis in AXES}
        target, owner = setup_frame_ref(bundle, setup)
        cite.extend(_input_cite(target, f"{owner}.{setup.get('frame', UNKNOWN)}"))
        stock, stock_cite = stock_extents(bundle, setup)
        authored_stock = record(bundle.plan.get("stock"))
        dimensions = [
            (field, authored_stock.get(field, UNKNOWN)) for field in ("length_mm", "dia_mm")
        ]
        section = authored_stock.get("section_mm")
        if isinstance(section, list):
            dimensions.extend((f"section_mm[{i}]", value) for i, value in enumerate(section))
        invalid_stock = [field for field, value in dimensions if _known(value) and value <= 0]
        manifest_mm = bundle.features.get("units") == "mm"
        for op, before, _ in tip_endpoints.stock_states(bundle, setup):
            if op.get("do") in MANUAL or op.get("do") in SAW_OPS:
                continue
            label = f"plan.setups.{setup['id']}.ops.{op['op']}"
            name = op.get("feature", UNKNOWN)
            feature = record(features.get(name))
            source_name = feature.get("frame", "model")
            source = record(frames.get(source_name))
            cite.extend(_input_cite(op, label))
            cite.extend(_input_cite(feature, f"features.features.{name}.bounds/at"))
            cite.extend(_input_cite(source, f"features.frames.{source_name}"))
            tool_ref = op.get("tool", UNKNOWN)
            reversed_bounds = [
                axis
                for axis, band in record(feature.get("bounds")).items()
                if axis in AXES and _band(band) and band[0] > band[1]
            ]
            if reversed_bounds:
                errors.append(
                    f"op {op['op']} feature.bounds has reversed "
                    + "/".join(reversed_bounds)
                    + " limits; record low <= high in mm"
                )
            extent = (
                transformed_bounds(feature.get("bounds"), source, target)
                if manifest_mm
                else UNKNOWN
            )
            locator, locator_frame, locator_name = located_by(features, name, feature)
            locator_source = record(frames.get(locator_frame))
            if locator_name != name:
                cite.extend(
                    [
                        f"features.features.{locator_name}.at",
                        *_citations(locator.get("cite"), "at"),
                    ]
                )
                cite.extend(_input_cite(locator_source, f"features.frames.{locator_frame}"))
            point = _point(locator, locator_source, target) if manifest_mm else UNKNOWN
            if op.get("do") in CENTRE_OPS:
                extent = point
            action = op.get("do", UNKNOWN)
            action_known = isinstance(action, str) and action not in {UNKNOWN, ""}
            if not action_known:
                action = UNKNOWN
                for axis in AXES:
                    complete[axis] = False
                missing.append(
                    f"Identify and declare {label}.do from the intended machining operation "
                    "before determining its cutter-centre path; measure the corresponding "
                    "extents and commanded targets with a CMM or machine readout in mm"
                )
            path_known = action_known and manifest_mm
            if not manifest_mm:
                for axis in AXES:
                    complete[axis] = False
                missing.append(
                    "Confirm features.units and frame coordinate units from the drawing; "
                    "measure and author feature/frame extents in mm with a steel rule or CMM. "
                    "Inch or unknown manifest coordinates are not silently treated as millimetres"
                )
            base_action = action.removeprefix("rough_").removeprefix("finish_")
            broad = base_action in {"profile", "face", "pocket"}
            radius_needed = base_action == "profile"
            tool_category, tool_key, tool = selected_item(bundle, "tools", tool_ref)
            diameter = (
                fact(tool, "dia", tool_category, tool_key, debts, cite)
                if radius_needed and tool and tool.get("kind") != UNKNOWN
                else {"value": UNKNOWN, "verified": False}
            )
            radius = diameter["value"] / 2 if _known(diameter["value"]) else UNKNOWN
            radius_known = diameter["verified"] and _known(radius) and radius > 0
            fallback = broad and not isinstance(extent, dict)
            if fallback and invalid_stock:
                errors.append(
                    f"op {op['op']} conservative stock requires positive plan.stock."
                    + "/".join(invalid_stock)
                    + " dimensions in mm"
                )
            # A rough stage runs its leave farther out than the finished line: an explicit
            # rough, or the rough a contour finish pairs with its rough_allowance_mm (the
            # coordinates rule prints both). A negative leave anywhere is refused, never
            # padded; an unknown one a rough stage needs stays debt.
            leave, refusal = rough_leave(op)
            staged = action.startswith("rough_") or "contour" in op
            allowance = leave if staged and leave is not None else 0
            allowance_known = _known(allowance)
            if refusal:
                errors.append(f"op {op['op']} {refusal}")
            elif not allowance_known:
                missing.append(
                    f"Measure and declare {label}.rough_allowance_mm >= 0 with calipers "
                    "or a micrometer in mm per side of the rough cut"
                )
            padding = (
                (radius + allowance if radius_known and allowance_known else UNKNOWN)
                if radius_needed
                else allowance
                if allowance_known
                else UNKNOWN
            )
            xy = {}
            op_xy_complete = True
            for axis in ("x", "y"):
                band = record(extent).get(axis)
                located = record(point).get(axis) if fallback else band
                if path_known and _band(located) and _known(padding):
                    xy[axis] = [located[0] - padding, located[1] + padding]
                    _include(bands[axis], xy[axis])
                else:
                    xy[axis] = UNKNOWN
                if fallback:
                    span = stock.get(axis, UNKNOWN)
                    if _known(span) and span <= 0:
                        errors.append(
                            f"op {op['op']} conservative {axis.upper()} stock span "
                            "must be positive in mm"
                        )
                    if (
                        path_known
                        and _known(span)
                        and span > 0
                        and _known(padding)
                        and not invalid_stock
                    ):
                        scalar_spans[axis].append(span + 2 * padding)
                    else:
                        complete[axis] = False
                        op_xy_complete = False
                elif not _band(band) or not _known(padding):
                    complete[axis] = False
                    op_xy_complete = False
            if fallback:
                cite.extend(stock_cite)
            if not op_xy_complete:
                missing.append(
                    f"Measure {label} full feature.bounds x/y/z or point-operation feature.at "
                    "in its declared frame with calipers, a height gauge or CMM, in mm; "
                    "for a broad cut record plan.stock.length_mm and section_mm/dia_mm "
                    "with calipers instead of using a nominal feature width"
                )
                authoring_entry(
                    debts,
                    f"{label}.xy_geometry",
                    missing[-1],
                    f"features.features.{name}.bounds/at; plan.stock",
                )
            endpoint = endpoints.get((setup["id"], op["op"], name))
            assembly = spindle_nose_band(
                bundle, op, before, extent, endpoint, debts, cite, missing, errors, label
            )
            z_band = assembly["nose_band_mm"]
            z_complete = assembly["verified"] and path_known
            if z_complete:
                _include(bands["z"], z_band)
            complete["z"] &= z_complete
            operations.append(
                {
                    "op": op["op"],
                    "do": action,
                    "feature": name,
                    "tool": tool_ref,
                    "holder": op.get("holder", UNKNOWN),
                    "holder_gauge_len_mm": assembly["gauge"]["value"],
                    "tool_projection_mm": assembly["projection"]["value"],
                    "tip_z_bounds_mm": assembly["tip_band_mm"],
                    "extent_mm": extent,
                    "xy_cutter_bounds_mm": xy,
                    "conservative_stock_spans_mm": stock if fallback else "not_applicable",
                    "tool_radius_mm": radius,
                    "tool_radius_verified": radius_known,
                    "rough_allowance_mm": allowance,
                    "approach_mm": op.get("approach_mm", UNKNOWN),
                    "z_bounds_mm": z_band,
                    "z_verified": z_complete,
                    "endpoint": endpoint if endpoint is not None else "not_applicable",
                }
            )
        checks = {}
        for axis in AXES:
            travel = fact(
                machine,
                f"envelope.travel.{axis}",
                "machines",
                machine_ref,
                debts,
                cite,
            )
            candidates = [*scalar_spans[axis]]
            located_span = _span(bands[axis])
            if _known(located_span):
                candidates.append(located_span)
            minimum_required = max(candidates) if candidates else UNKNOWN
            required = minimum_required if complete[axis] else UNKNOWN
            verified = travel["verified"] and _known(travel["value"]) and travel["value"] >= 0
            if travel["verified"] and not verified:
                missing.append(
                    f"Measure inventory.machines.{setup.get('machine', UNKNOWN)}."
                    f"envelope.travel.{axis} safe usable stop-to-stop stroke with a steel rule "
                    "or calipers and record a finite nonnegative travel in mm"
                )
            lower_margin = (
                travel["value"] - minimum_required
                if verified and _known(minimum_required)
                else UNKNOWN
            )
            # Translated decimal bands can leave sub-nanometre float residue.
            # Use the repository's existing physical-length equality, not relative slack.
            if _known(lower_margin) and same_length(travel["value"], minimum_required):
                lower_margin = 0
            margin = lower_margin if complete[axis] else UNKNOWN
            checks[axis] = {
                "required_mm": required,
                "travel_mm": travel["value"],
                "margin_mm": margin,
                "required_verified": complete[axis] and _known(required),
                "travel_verified": verified,
                "located_span_mm": located_span,
                "minimum_required_mm": minimum_required,
                "lower_bound_margin_mm": lower_margin,
            }
            if _known(lower_margin) and lower_margin < 0:
                bound = "" if complete[axis] else "at least "
                errors.append(
                    f"declared {axis.upper()} operation span {bound}{minimum_required:g} mm "
                    f"exceeds measured travel {travel['value']:g} mm by {-lower_margin:g} mm"
                )
        if not operations:
            status, sentence = (
                "not_applicable",
                f"{setup['id']}: no nonmanual mill operations require travel.",
            )
        elif errors:
            status, sentence = "error", f"{setup['id']}: " + "; ".join(errors) + "."
        elif any(
            not row["required_verified"] or not row["travel_verified"] for row in checks.values()
        ):
            status = "unknown"
            sentence = unknown_sentence(
                setup["id"],
                "declared operation travel remains unmeasured or unresolved",
                debts,
                list(dict.fromkeys(missing)),
            )
        else:
            status = "pass"
            sentence = (
                f"{setup['id']}: declared XY cutter-centre spans and spindle-nose Z bands "
                "including safe approaches fit measured XYZ travel."
            )
        findings.append(
            Finding(
                "travel",
                setup["id"],
                status,
                {
                    "travel_checks": checks,
                    "operations": operations,
                    "measurements": [debts[key] for key in sorted(debts)],
                },
                list(dict.fromkeys(cite)),
                sentence,
            )
        )
    return findings
