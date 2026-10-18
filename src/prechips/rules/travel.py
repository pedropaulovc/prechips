"""Declared mill operation spans, not a toolpath or stock-position certificate.

Located cutter envelopes are unioned in setup axes. Unlocated broad cuts use
conservative stock spans without inventing where that stock sits in the frame; such a
span is only a lower bound (the cutter's approach and exit past the stock are undeclared
plan input), never a pass. An op whose cutter-centre XY the traveler prints
(``coordinates.printed_xy``: arc rows, join lines, linear-table outlines and face raster
passes) is that printed path, approach and exit included, instead of its declared extent
(#297). Each X/Y axis names its basis: the path, the declared extent or the stock span.
A child feature (``hole``/``parent``) without its own ``at`` is located at its
parent's ``at`` in the parent's frame; it inherits no parent bounds.
Saw cuts drive no spindle cutter and are skipped.
"""

from prechips.findings import Finding
from prechips.model import profiled
from prechips.rules import tip_endpoints
from prechips.rules._envelope import (
    _band,
    _known,
    _point,
    authoring_entry,
    entry_stock,
    fact,
    machine_envelope,
    raw_supply,
    selected_item,
    spindle_nose_band,
    stock_extents,
    transformed_bounds,
    unknown_sentence,
)
from prechips.rules.coordinates import AXES, CENTRE_OPS, located_by, printed_xy
from prechips.rules.geometry_common import rule_rows
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


def _basis(axis, minimum_required, located_span, sourced):
    """What an axis's span is the stroke of: the printed ``cutter-centre path``, the
    ``declared cut extent`` (feature bounds or centres, the cutter radius on a profile),
    both, or a broad cut's ``stock span`` (a lower bound whose approach and exit are
    undeclared)."""
    if not _known(minimum_required) or axis not in sourced:
        return UNKNOWN
    if not (_known(located_span) and same_length(located_span, minimum_required)):
        return "stock span"
    governing = [
        name
        for name, found in sourced[axis].items()
        if found and same_length(_span(found), located_span)
    ]
    return governing[0] if len(governing) == 1 else "cutter-centre path and declared cut extent"


def evaluate(bundle):
    features = bundle.feature_definitions
    frames = record(bundle.features.get("frames"))
    endpoints = {
        (row["setup"], row["op"], row["feature"]): row
        for finding in tip_endpoints.evaluate(bundle)
        for row in finding.numbers["endpoints"]
    }
    from prechips.rules import coordinates

    printed = {
        row.subject: row.numbers for row in rule_rows(bundle, "coordinates", coordinates.evaluate)
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
        sourced = {axis: {"cutter-centre path": [], "declared cut extent": []} for axis in "xy"}
        scalar_spans = {axis: [] for axis in AXES}
        complete = {axis: True for axis in AXES}
        target, owner = setup_frame_ref(bundle, setup)
        cite.extend(_input_cite(target, f"{owner}.{setup.get('frame', UNKNOWN)}"))
        stock, stock_cite = stock_extents(bundle, setup)
        # A broad cut sweeps the stock this setup receives (the same box headroom reads,
        # placed by the stock's own axes): a routed stock without it is unknown, never the
        # raw blank or the finished part.
        entry = entry_stock(bundle, setup, target)
        if all(_known(entry[axis]) for axis in ("x", "y")):
            stock = {**stock, "x": entry["x"], "y": entry["y"]}
            stock_cite = [*entry["cite"], *stock_cite]
        elif not raw_supply(bundle, setup):
            stock = {**stock, "x": UNKNOWN, "y": UNKNOWN}
            stock_cite = [*entry["cite"], *stock_cite]
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
            # A guided sweep locks X and Y and its fixture moves the work: the arc's span is
            # no table stroke. Its swept footprint stays a debt below (#255).
            fixture_driven = record(op.get("contour")).get("method") == "guided_sweep"
            if fixture_driven:
                xy = {"x": "not_applicable", "y": "not_applicable"}
            # A printed cutter-centre path is the op's XY motion, approach and exit
            # included: what the table must reach. It replaces the declared extent.
            path = (
                None if fixture_driven else printed_xy(record(printed.get(setup["id"])), op["op"])
            )
            path_bounds = "not_applicable"
            stock_only = False
            if path:
                path_bounds = {
                    axis: [min(p[i] for p in path), max(p[i] for p in path)]
                    for i, axis in enumerate(("x", "y"))
                }
                xy = dict(path_bounds)
                for axis, band in path_bounds.items():
                    _include(bands[axis], band)
                    _include(sourced[axis]["cutter-centre path"], band)
                cite.append(
                    f"coordinates.{setup['id']}: printed cutter-centre path of op {op['op']}"
                )
            for axis in () if fixture_driven or path else ("x", "y"):
                band = record(extent).get(axis)
                located = record(point).get(axis) if fallback else band
                if path_known and _band(located) and _known(padding):
                    xy[axis] = [located[0] - padding, located[1] + padding]
                    _include(bands[axis], xy[axis])
                    _include(sourced[axis]["declared cut extent"], xy[axis])
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
                        # A lower bound only: a stock span is no cutter path, and the
                        # cutter's approach and exit past it are undeclared plan input.
                        scalar_spans[axis].append(span + 2 * padding)
                        stock_only = True
                    complete[axis] = False
                    op_xy_complete = False
                elif not _band(band) or not _known(padding):
                    complete[axis] = False
                    op_xy_complete = False
            if fallback:
                cite.extend(stock_cite)
            if not op_xy_complete:
                geometry_pending = (
                    fallback
                    and path_known
                    and not invalid_stock
                    and any(axis in stock.get("geometry_pending_axes", []) for axis in ("x", "y"))
                )
                if geometry_pending:
                    missing.append(
                        f"Geometry pending: {label} broad-cut XY spans need the kernel "
                        "bounding box in the declared setup frame"
                    )
                # A stock-sized broad cut owes its X/Y extent whether or not the stock box
                # is computed yet: the same plan-input debt in both modes.
                if stock_only or geometry_pending:
                    missing.append(
                        f"Author {label} feature.bounds x/y in its declared frame (or a "
                        "contour the traveler prints as a cutter-centre path): the stock span "
                        "is only a lower bound and does not include the cutter's approach and "
                        "exit"
                    )
                    authoring_entry(
                        debts,
                        f"{label}.xy_geometry",
                        missing[-1],
                        f"features.features.{name}.bounds; plan.setups.{setup['id']}.ops",
                    )
                else:
                    # A profiled blank has no bar dimensions to record: its STEP sizes it.
                    broad = (
                        ""
                        if profiled(authored_stock)
                        else "; for a broad cut record plan.stock.length_mm and "
                        "section_mm/dia_mm with calipers instead of using a nominal feature width"
                    )
                    missing.append(
                        f"Measure {label} full feature.bounds x/y/z or point-operation feature.at "
                        "in its declared frame with calipers, a height gauge or CMM, in mm" + broad
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
                    "printed_xy_bounds_mm": path_bounds,
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
            basis = _basis(axis, minimum_required, located_span, sourced)
            verified = travel["verified"] and _known(travel["value"]) and travel["value"] >= 0
            if travel["verified"] and not verified:
                missing.append(
                    f"Measure inventory.machines.{setup.get('machine', UNKNOWN)}."
                    f"envelope.travel.{axis} safe usable stop-to-stop stroke with a calibrated "
                    "DRO or indicator and record a finite nonnegative travel in mm"
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
                "basis": basis,
            }
            if _known(lower_margin) and lower_margin < 0:
                bound = "" if complete[axis] else "at least "
                errors.append(
                    f"declared {axis.upper()} operation span {bound}{minimum_required:g} mm "
                    f"exceeds measured travel {travel['value']:g} mm by {-lower_margin:g} mm"
                )
        # A guided sweep's fixture moves while the table stays put: its swept footprint is
        # not modelled, so the setup is never a travel pass (#255).
        from .guided_sweep import unmodelled

        swept = unmodelled(bundle, setup, "travel")
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
            if swept:
                sentence = sentence.rstrip(".") + "; " + "; ".join(swept) + "."
        elif swept:
            status, sentence = "unknown", f"{setup['id']}: " + "; ".join(swept) + "."
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
                    **({"guided_sweep_debts": swept} if swept else {}),
                },
                list(dict.fromkeys(cite)),
                sentence,
            )
        )
    return findings
