"""Declared mill extents and measurement debt shared by the M5 screens."""

from itertools import product

from prechips.measurements import length_fact, measurement_entry
from prechips.rules.coordinates import AXES, frame_point, model_point
from prechips.rules.resolution import UNKNOWN, _citations, number, record, resolve


def measurement_item(bundle, category, reference):
    """Keep identity resolution, without promoting sibling fact debt to this fact."""
    resolved = resolve(bundle, category, reference) or {}
    if not resolved or not isinstance(reference, str):
        return resolved
    root, separator, member = reference.partition("/")
    authored = record(record(bundle.inventory.get(category)).get(root))
    if not authored or resolved.get("kind") == UNKNOWN:
        return resolved
    if not separator:
        return authored
    selected = record(record(authored.get("members")).get(member))
    # Derived member size/height remains the resolver's supported nominal identity.
    item = dict(resolved)
    if "verify" in selected:
        item["verify"] = selected["verify"]
    elif "verify" in authored:
        item["verify"] = authored["verify"]
    else:
        item.pop("verify", None)
    return item


def fact(item, field, category, identity, debts, cite, *, require_measured=True):
    result = length_fact(item, field, require_measured=require_measured)
    cite.extend(result["cite"])
    cite.append(f"inventory.{category}.{identity}.{field}")
    if not result["verified"]:
        entry = measurement_entry(category, identity, field)
        debts[entry["id"]] = entry
    return result


def tool_projection(bundle, op, debts, cite):
    tool_ref, holder_ref = op.get("tool", UNKNOWN), op.get("holder", UNKNOWN)
    tool = measurement_item(bundle, "tools", tool_ref)
    holder = measurement_item(bundle, "holders", holder_ref)
    for item, category, identity in (
        (tool, "tools", tool_ref),
        (holder, "holders", holder_ref),
    ):
        if any(key in item for key in ("projection_mm", "projection_in", "projection")):
            return fact(item, "projection", category, identity, debts, cite)
    oal = fact(tool, "oal", "tools", tool_ref, debts, cite)
    grip = fact(holder, "grip", "holders", holder_ref, debts, cite)
    value = (
        oal["value"] - grip["value"]
        if all(number(v) for v in (oal["value"], grip["value"]))
        else UNKNOWN
    )
    return {"value": value, "verified": oal["verified"] and grip["verified"]}


def unknown_sentence(setup, description, debts, missing=()):
    instructions = [debts[key]["instruction"] for key in sorted(debts)]
    return f"{setup}: {description}. " + "; ".join([*missing, *instructions]) + "."


def setup_frame(bundle, setup):
    return record(record(bundle.features.get("frames")).get(setup.get("frame")))


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
    frame = setup_frame(bundle, setup)
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
            "kernel.bbox_mm; features.frames setup basis",
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
        "plan.stock.section_mm/length_mm/dia_mm; features.frames setup basis",
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
    fixture = measurement_item(bundle, "fixtures", identity)
    field = "jaw_height" if fixture.get("kind") == "vise" else "height"
    height = fact(fixture, field, "fixtures", identity, debts, cite, require_measured=False)
    values, verified = [height["value"]], height["verified"]
    for field in ("parallels", "supports", "riser"):
        reference = hold.get(field)
        if reference in (None, "none", "not_applicable"):
            continue  # Known absence of an optional support is not a zero measurement.
        support = measurement_item(bundle, "fixtures", reference)
        value = fact(support, "height", "fixtures", reference, debts, cite, require_measured=False)
        values.append(value["value"])
        verified &= value["verified"]
    return sum(values) if all(number(v) for v in values) else UNKNOWN, verified


def machine_envelope(bundle, setup):
    machine = measurement_item(bundle, "machines", setup.get("machine"))
    return machine, record(machine.get("envelope"))
