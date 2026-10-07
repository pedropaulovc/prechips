"""Declared mill extents and measurement debt shared by the M5 screens."""

import math
from itertools import product

from prechips.measurements import angle_fact, length_fact, measurement_entry
from prechips.rules import tip_endpoints
from prechips.rules.coordinates import AXES, frame_point, model_point
from prechips.rules.resolution import (
    EXPORTED_FRAMES,
    UNKNOWN,
    _citations,
    authored,
    number,
    record,
    resolve,
    select,
    setup_frame_ref,
)


def measurement_item(bundle, slot, reference):
    """The item ``slot`` selects (:func:`select`), its selected members resolved, without
    promoting item metadata into length facts: a whole item is read as authored."""
    resolved = resolve(bundle, slot, reference) or {}
    if not resolved:
        return resolved
    category, reference, _ = select(bundle, reference, slot)
    stated = authored(bundle, category, reference)
    return stated if stated and "/" not in reference else resolved


def fact(item, field, category, identity, debts, cite, *, require_measured=True):
    result = length_fact(item, field, require_measured=require_measured)
    cite.extend(result["cite"])
    cite.append(f"inventory.{category}.{identity}.{field}")
    if not result["verified"]:
        entry = measurement_entry(category, identity, field)
        debts[entry["id"]] = entry
    return result


def tool_projection(bundle, op, debts, cite, *, require_measured=True):
    """Use only this exact tool/holder pair, otherwise selected OAL minus grip."""
    tool_ref, holder_ref = op.get("tool", UNKNOWN), op.get("holder", UNKNOWN)
    tool = measurement_item(bundle, "tools", tool_ref)
    holder = measurement_item(bundle, "holders", holder_ref)
    for field in ("projection_mm", "projection_in"):
        if holder_ref in record(tool.get(field)):
            result = length_fact(
                tool, ("projection", holder_ref), require_measured=require_measured
            )
            citation = f"inventory.tools.{tool_ref}.{field}.{holder_ref}"
            cite.extend([*result["cite"], citation])
            if not result["verified"]:
                entry = measurement_entry("tools", tool_ref, ("projection", holder_ref))
                entry["cite"] = [citation, *result["cite"]]
                debts[entry["id"]] = entry
            return result
    oal = fact(tool, "oal", "tools", tool_ref, debts, cite, require_measured=require_measured)
    grip = fact(
        holder, "grip", "holders", holder_ref, debts, cite, require_measured=require_measured
    )
    value = (
        oal["value"] - grip["value"]
        if all(number(v) for v in (oal["value"], grip["value"]))
        else UNKNOWN
    )
    return {
        "value": value,
        "verified": oal["verified"] and grip["verified"],
        "cite": [*oal["cite"], *grip["cite"]],
        "reason": "Selected tool OAL minus selected holder grip.",
    }


def unknown_sentence(setup, description, debts, missing=()):
    instructions = [debts[key]["instruction"] for key in sorted(debts)]
    covered = " ".join(instructions)
    extra = [text for text in dict.fromkeys(missing) if text not in covered]
    return f"{setup}: {description}. " + "; ".join([*extra, *instructions]) + "."


def transformed_bounds(bounds, source_frame, target_frame):
    """Project all eight declared box corners; never guess an omitted axis."""
    bands = [record(bounds).get(axis) for axis in AXES]
    if not all(
        isinstance(band, list)
        and len(band) == 2
        and all(number(v) for v in band)
        and band[0] <= band[1]
        for band in bands
    ):
        return UNKNOWN
    points = [
        frame_point(model_point(list(p), source_frame), target_frame) for p in product(*bands)
    ]
    if not all(number(value) for point in points for value in point):
        return UNKNOWN
    return {
        axis: [min(p[i] for p in points), max(p[i] for p in points)] for i, axis in enumerate(AXES)
    }


def _supported_extents(extents, setup):
    state = record(setup.get("stock_state"))
    bottom = state.get("retained_rail_bottom_z", state.get("bottom_z", UNKNOWN))
    top = state.get("top_z", UNKNOWN)
    # The received blank, not the shorter finished STEP, occupies the fixture.
    if all(number(value) for value in (top, bottom)):
        extents["z"] = top - bottom
    return extents


def stock_extents(bundle, setup):
    """Use an already-returned STEP bbox, else the authored blank, in setup axes."""
    frame, owner = setup_frame_ref(bundle, setup)
    # Exported frames keep their historical label; a plan-owned frame names itself.
    basis = owner if owner == EXPORTED_FRAMES else f"{owner}.{setup.get('frame')}"
    kernel = record(getattr(bundle, "kernel", None))
    bbox = kernel.get("bbox_mm")
    if kernel.get("status") == "ok" and isinstance(bbox, list) and len(bbox) == 6:
        bounds = {axis: [bbox[i], bbox[i + 3]] for i, axis in enumerate(AXES)}
        identity = {"origin": [0, 0, 0], "x": [1, 0, 0], "y": [0, 1, 0], "z": [0, 0, 1]}
        placed = transformed_bounds(bounds, identity, frame)
        if isinstance(placed, dict):
            return _supported_extents(
                {axis: band[1] - band[0] for axis, band in placed.items()}, setup
            ), [
                "kernel.bbox_mm: already-present STEP bounding box transformed to setup frame",
                "plan.setups.stock_state: physical supported stock height",
            ]
        return _supported_extents({axis: UNKNOWN for axis in AXES}, setup), [
            f"kernel.bbox_mm; {basis} setup basis",
            "plan.setups.stock_state: physical supported stock height",
        ]
    stock = record(bundle.plan.get("stock"))
    section = stock.get("section_mm")
    if isinstance(section, list) and len(section) == 2:
        dimensions = [stock.get("length_mm", UNKNOWN), *section]
    elif stock.get("form") in {"round", "round_bar"}:
        dimensions = [
            stock.get("length_mm", UNKNOWN),
            stock.get("dia_mm", UNKNOWN),
            stock.get("dia_mm", UNKNOWN),
        ]
    else:
        dimensions = [UNKNOWN] * 3
    extent_cite = [
        f"plan.stock.section_mm/length_mm/dia_mm; {basis} setup basis",
        *_citations(stock.get("cite")),
    ]
    if not all(number(value) for value in dimensions) and bundle.features.get("units") == "mm":
        frames = record(bundle.features.get("frames"))
        features = record(bundle.features.get("features"))
        boxes = [
            transformed_bounds(
                feature.get("bounds"), frames.get(feature.get("frame", "model")), frame
            )
            for feature in features.values()
        ]
        if boxes and all(isinstance(box, dict) for box in boxes):
            return _supported_extents(
                {
                    axis: max(box[axis][1] for box in boxes) - min(box[axis][0] for box in boxes)
                    for axis in AXES
                },
                setup,
            ), [
                "plan.setups.stock_state: physical supported stock height",
                "features.*.bounds: complete authored feature extents transformed to setup frame",
                *_citations(bundle.features.get("cite")),
                *[
                    citation
                    for feature in features.values()
                    for citation in _citations(feature.get("cite"))
                ],
            ]
    extents = {}
    for axis in AXES:
        basis = frame.get(axis)
        extents[axis] = (
            sum(abs(basis[i]) * dimensions[i] for i in range(3))
            if isinstance(basis, list)
            and len(basis) == 3
            and all(number(v) for v in [*basis, *dimensions])
            else UNKNOWN
        )
    return _supported_extents(extents, setup), [
        *extent_cite,
        "plan.setups.stock_state: physical supported stock height",
    ]


def fixture_height(bundle, setup, debts, cite):
    hold = record(setup.get("hold"))
    identity = hold.get("fixture", UNKNOWN)
    category = select(bundle, identity, "workholding")[0]
    fixture = measurement_item(bundle, "workholding", identity)
    if not fixture or fixture.get("kind") == UNKNOWN:
        authoring_entry(
            debts,
            f"{category}.{identity}.resolve",
            f"resolve: add or select an owned fixture for {identity} in inventory "
            f"and author plan.setups.{setup['id']}.hold.fixture",
            f"inventory.{category}.{identity}",
        )
        values, verified = [UNKNOWN], False
    else:
        field = "bed_height" if fixture.get("kind") == "vise" else "height"
        height = fact(fixture, field, category, identity, debts, cite)
        values, verified = [height["value"]], height["verified"]
    for field in ("parallels", "supports", "riser"):
        reference = hold.get(field)
        if reference in (None, "none", "not_applicable"):
            continue  # Known absence of an optional support is not a zero measurement.
        support = measurement_item(bundle, "fixtures", reference)
        if not support or support.get("kind") == UNKNOWN:
            authoring_entry(
                debts,
                f"fixtures.{reference}.resolve",
                f"resolve: add or select an owned fixture for {reference} in inventory "
                f"and author plan.setups.{setup['id']}.hold.{field}",
                f"inventory.fixtures.{reference}",
            )
            values.append(UNKNOWN)
            verified = False
            continue
        value = fact(support, "height", "fixtures", reference, debts, cite)
        values.append(value["value"])
        verified &= value["verified"]
    return sum(values) if all(number(v) for v in values) else UNKNOWN, verified


def machine_envelope(bundle, setup):
    machine = measurement_item(bundle, "machines", setup.get("machine"))
    return machine, record(machine.get("envelope"))


def _known(value):
    return number(value) and math.isfinite(value)


def _band(value):
    return isinstance(value, list) and len(value) == 2 and all(_known(v) for v in value)


def _point(feature, source, target):
    at = feature.get("at")
    if not isinstance(at, list) or len(at) != 3 or not all(_known(v) for v in at):
        return UNKNOWN
    point = frame_point(model_point(at, source), target)
    return {axis: [point[i], point[i]] for i, axis in enumerate(AXES)}


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
            f"Author {label}.approach_mm >= 0 in mm above the current stock top "
            "from the intended safe Z approach; no approach is assumed"
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
        if not tool or tool.get("kind") == UNKNOWN:
            endpoint_complete = False
        elif action == "drill":
            endpoint_complete &= diameter["verified"] and _known(diameter["value"])
            angle = angle_fact(tool, "point_angle")
            angle_verified = (
                angle["verified"] and _known(angle["value"]) and 0 < angle["value"] < 180
            )
            endpoint_complete &= angle_verified
            if not angle_verified:
                entry = measurement_entry("tools", op.get("tool", UNKNOWN), "point_angle")
                debts[entry["id"]] = entry
            cite.extend([*angle["cite"], f"inventory.tools.{op.get('tool', UNKNOWN)}.point_angle"])
        elif action == "ream":
            lead = fact(tool, "lead", "tools", op.get("tool", UNKNOWN), debts, cite)
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


def authoring_entry(debts, identity, instruction, cite):
    if not instruction.startswith("resolve:"):
        instruction = "author: " + instruction
    debts[identity] = {
        "id": identity,
        "instruction": instruction,
        "cite": [cite],
        "units": "identity" if identity.endswith(".resolve") else "mm",
    }


def spindle_nose_band(bundle, op, before, extent, endpoint, debts, cite, missing, errors, label):
    """Shared tip band plus measured selected assembly, in setup-datum Z."""
    tool_ref, holder_ref = op.get("tool", UNKNOWN), op.get("holder", UNKNOWN)
    tool = measurement_item(bundle, "tools", tool_ref)
    holder = measurement_item(bundle, "holders", holder_ref)
    unresolved = False
    for category, reference, item in (("tools", tool_ref, tool), ("holders", holder_ref, holder)):
        if not item or item.get("kind") == UNKNOWN:
            unresolved = True
            authoring_entry(
                debts,
                f"{category}.{reference}.resolve",
                f"resolve: add or select an owned {category[:-1]} for {reference} in inventory "
                f"and author {label}.{category[:-1]}",
                f"inventory.{category}.{reference}",
            )
    unknown_fact = {"value": UNKNOWN, "verified": False}
    if unresolved:
        gauge = projection = unknown_fact
    else:
        gauge = fact(holder, "gauge_len", "holders", holder_ref, debts, cite)
        projection = tool_projection(bundle, op, debts, cite)
    diameter = (
        fact(tool, "dia", "tools", tool_ref, debts, cite)
        if op.get("do") == "drill" and tool and tool.get("kind") != UNKNOWN
        else unknown_fact
    )
    missing_start = len(missing)
    tip, complete = _z_extent(
        op, before, extent, endpoint, tool, diameter, debts, cite, missing, errors, label
    )
    if len(missing) > missing_start:
        authoring_entry(debts, f"{label}.z_geometry", "; ".join(missing[missing_start:]), label)
    action = op.get("do")
    complete &= (
        isinstance(action, str)
        and action not in {UNKNOWN, ""}
        and bundle.features.get("units") == "mm"
        and not unresolved
    )
    if not complete and not unresolved and len(missing) == missing_start:
        authoring_entry(
            debts,
            f"{label}.z_geometry",
            f"Author {label}.do and setup-datum Z geometry with features.units = mm",
            label,
        )
    cite.extend(
        [
            f"{label}.approach_mm/to_z/z_from/z_to/depth_mm/exit_mm",
            f"{label}: stock_states current top and local entry; hole tip/exit endpoints",
            "plan.setups.stock_state.top_z/entry_z/local_thickness",
        ]
    )
    dimensions = (gauge["value"], projection["value"])
    length = sum(dimensions) if all(_known(value) for value in dimensions) else UNKNOWN
    measured = gauge["verified"] and projection["verified"] and _known(length)
    if measured and any(value < 0 for value in dimensions):
        errors.append(f"op {op['op']} has a negative measured holder gauge or tool projection")
        measured = False
    nose = [value + length for value in tip] if _band(tip) and _known(length) else UNKNOWN
    return {
        "tip_band_mm": tip,
        "nose_band_mm": nose,
        "gauge": gauge,
        "projection": projection,
        "verified": bool(complete and measured),
    }
