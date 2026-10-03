"""Declared mill operation spans, not a toolpath or stock-position certificate.

Located cutter envelopes are unioned in setup axes. Unlocated broad cuts use
conservative stock spans without inventing where that stock sits in the frame.
"""

import math

from prechips.findings import Finding
from prechips.measurements import measurement_entry
from prechips.rules import tip_endpoints
from prechips.rules._envelope import (
    fact,
    machine_envelope,
    measurement_item,
    setup_frame,
    stock_extents,
    transformed_bounds,
    unknown_sentence,
)
from prechips.rules.coordinates import AXES, CENTRE_OPS, frame_point, model_point
from prechips.rules.resolution import (
    MANUAL,
    UNKNOWN,
    _citations,
    number,
    record,
    same_length,
    uncertain,
)


def _input_cite(item, label):
    item = record(item)
    return [label, *_citations(item.get("cite")), *_citations(item.get("source"))]


def _known(value):
    return number(value) and math.isfinite(value)


def _point(feature, source, target):
    at = feature.get("at")
    if not isinstance(at, list) or len(at) != 3 or not all(_known(v) for v in at):
        return UNKNOWN
    point = frame_point(model_point(at, source), target)
    return {axis: [point[i], point[i]] for i, axis in enumerate(AXES)}


def _band(value):
    return isinstance(value, list) and len(value) == 2 and all(_known(v) for v in value)


def _include(bands, band):
    if _band(band):
        bands.append(band)


def _span(bands):
    return max(band[1] for band in bands) - min(band[0] for band in bands) if bands else UNKNOWN


def _z_extent(op, before, extent, endpoint, tool, diameter, debts, cite, missing, errors, label):
    """Bound the commanded tip, touched top and explicitly authored safe approach."""
    values = []
    complete = True
    if isinstance(extent, dict) and _band(extent.get("z")):
        values.extend(extent["z"])
    top = before["top_z"]
    approach = op.get("approach_mm", UNKNOWN)
    if _known(top):
        values.append(top)
    else:
        complete = False
        missing.append(
            f"Measure {label} current stock top from the setup datum with a height gauge or "
            "touch-off; record plan.setups.stock_state.top_z in mm"
        )
    if _known(approach) and approach < 0:
        errors.append(f"op {op['op']} approach_mm must be >= 0")
        complete = False
    elif _known(approach) and _known(top):
        values.append(top + approach)
    else:
        complete = False
        missing.append(
            f"Measure and declare {label}.approach_mm >= 0 with a height gauge or machine "
            "Z readout in mm above the current stock top for the safe Z approach"
        )

    targets = []
    for field in ("to_z", "z_from", "z_to"):
        if field in op:
            value = op[field]
            if _known(value):
                targets.append(value)
            else:
                complete = False
                missing.append(
                    f"Measure {label}.{field} from the setup datum using the machine Z "
                    "readout or depth gauge and record the commanded target in mm"
                )
    if op.get("do") in tip_endpoints.HOLE_OPS:
        endpoint_complete = endpoint is not None and _known(endpoint.get("tip_z"))
        if endpoint is not None:
            for field in ("entry_z", "exit_face", "tip_z"):
                value = endpoint.get(field, UNKNOWN)
                if _known(value):
                    targets.append(value)
        action = op.get("do")
        if action == "drill":
            endpoint_complete &= diameter["verified"] and _known(diameter["value"])
            # A local diameter measurement cannot certify a vendor-debt point angle.
            angle = tool.get("point_angle", tool.get("point_angle_deg", UNKNOWN))
            angle_verified = (
                _known(angle)
                and 0 < angle < 180
                and not uncertain(
                    {
                        key: tool[key]
                        for key in ("verify", "present", "coverage", "source")
                        if key in tool
                    }
                )
            )
            endpoint_complete &= angle_verified
            if not angle_verified:
                entry = measurement_entry("tools", op.get("tool", UNKNOWN), "point_angle")
                debts[entry["id"]] = entry
            cite.append(f"inventory.tools.{op.get('tool', UNKNOWN)}.point_angle")
        elif action == "ream":
            lead = fact(
                tool, "lead", "tools", op.get("tool", UNKNOWN), debts, cite, require_measured=False
            )
            endpoint_complete &= lead["verified"] and _known(lead["value"])
        complete &= endpoint_complete
        if not endpoint_complete:
            missing.append(
                f"Measure {label} hole entry and local thickness/depth with a depth gauge, "
                "drill point or reamer lead with an optical comparator, and exit allowance "
                "in mm; record stock_state.entry_z/local_thickness and operation depth_mm/exit_mm"
            )
    if "depth_mm" in op:
        depth = op["depth_mm"]
        entry = before["entry_z"].get(op.get("feature"), top)
        if _known(depth) and depth >= 0 and _known(entry):
            targets.extend((entry, entry - depth))
        else:
            complete = False
            missing.append(
                f"Measure {label}.depth_mm and local entry using a depth gauge or machine "
                "Z readout; record a nonnegative depth and entry_z in mm"
            )
    elif not targets and op.get("do") == "center" and isinstance(extent, dict):
        if _band(extent.get("z")):
            targets.extend(extent["z"])
    if not targets:
        complete = False
        missing.append(
            f"Measure and declare {label} commanded to_z, z_from/z_to or depth_mm from "
            "the setup datum with a depth gauge or machine Z readout in mm"
        )
    values.extend(targets)
    return ([min(values), max(values)] if values else UNKNOWN), complete


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
        cite = _input_cite(setup, f"plan.setups.{setup['id']}")
        cite.extend(_input_cite(machine, f"inventory.machines.{setup.get('machine', UNKNOWN)}"))
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
        debts, missing, errors, operations = {}, [], [], []
        bands = {axis: [] for axis in AXES}
        scalar_spans = {axis: [] for axis in AXES}
        complete = {axis: True for axis in AXES}
        target = setup_frame(bundle, setup)
        cite.extend(_input_cite(target, f"features.frames.{setup.get('frame', UNKNOWN)}"))
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
        for op, before, _ in tip_endpoints.stock_states(setup, features):
            if op.get("do") in MANUAL:
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
            tool = measurement_item(bundle, "tools", tool_ref)
            diameter = fact(tool, "dia", "tools", tool_ref, debts, cite, require_measured=False)
            radius = diameter["value"] / 2 if _known(diameter["value"]) else UNKNOWN
            radius_known = diameter["verified"] and _known(radius) and radius > 0
            if not radius_known:
                missing.append(
                    f"Measure inventory.tools.{tool_ref}.dia_mm across the cutting diameter "
                    "with calipers or a micrometer, in mm; clear verification debt or record "
                    "a fact-local shop measurement before using its cutter radius"
                )
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
            point = _point(feature, source, target) if manifest_mm else UNKNOWN
            if not isinstance(extent, dict) and op.get("do") in CENTRE_OPS:
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
            fallback = broad and not isinstance(extent, dict)
            if fallback and invalid_stock:
                errors.append(
                    f"op {op['op']} conservative stock requires positive plan.stock."
                    + "/".join(invalid_stock)
                    + " dimensions in mm"
                )
            rough = action.startswith("rough_")
            allowance = op.get("rough_allowance_mm", UNKNOWN) if rough else 0
            allowance_known = _known(allowance) and allowance >= 0
            if not allowance_known:
                missing.append(
                    f"Measure and declare {label}.rough_allowance_mm >= 0 with calipers "
                    "or a micrometer in mm per side of the rough cut"
                )
            padding = radius + allowance if radius_known and allowance_known else UNKNOWN
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
            endpoint = endpoints.get((setup["id"], op["op"], name))
            z_band, z_complete = _z_extent(
                op, before, extent, endpoint, tool, diameter, debts, cite, missing, errors, label
            )
            z_complete &= path_known
            if z_complete:
                _include(bands["z"], z_band)
            complete["z"] &= z_complete
            operations.append(
                {
                    "op": op["op"],
                    "do": action,
                    "feature": name,
                    "tool": tool_ref,
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
                setup.get("machine", UNKNOWN),
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
                f"{setup['id']}: declared cutter spans, tip endpoints and safe Z approaches "
                "fit measured XYZ travel."
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
