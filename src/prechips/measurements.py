"""Fact-local shop measurements, nominal lengths and an authored-inventory checklist."""

from __future__ import annotations

from datetime import date
from typing import get_args, get_origin

UNKNOWN = "unknown"
ENVELOPE_LENGTH_FIELDS = (
    "travel.x",
    "travel.y",
    "travel.z",
    "spindle_to_table_max",
    "spindle_to_table_min",
    "table_length",
    "table_width",
    "t_slot_pitch",
    "spindle_stack.r8",
    "spindle_stack.er_collet_chuck",
    "spindle_stack.drill_chuck",
)
_METADATA = {"measured", "verify", "present", "source", "cite", "by", "sku"}
_LEGACY_MILL_FIELDS = {
    "travel.x": "envelope.travel.x",
    "travel.y": "envelope.travel.y",
    "travel.z": "envelope.travel.z",
    "spindle_to_table_max": "envelope.spindle_to_table_max",
    "table.length": "envelope.table_length",
    "table.width": "envelope.table_width",
}


def _canonical(field):
    return ".".join(part.removesuffix("_mm").removesuffix("_in") for part in field.split("."))


def _aliases(part):
    stem = part.removesuffix("_mm").removesuffix("_in")
    units = ("_in", "_mm", "") if part.endswith("_in") else ("_mm", "_in", "")
    aliases = [stem + unit for unit in units]
    if part.endswith(("_mm", "_in")):
        aliases.insert(0, part)
    return list(dict.fromkeys(aliases))


def _complete(value):
    if not isinstance(value, dict) or set(value) != {"by", "date", "instrument"}:
        return False
    if not all(
        isinstance(text, str) and text.strip() and text.strip() != UNKNOWN
        for text in value.values()
    ):
        return False
    try:
        return date.fromisoformat(value["date"]).isoformat() == value["date"]
    except ValueError:
        return False


def _debt(item):
    source = item.get("source")
    return (
        item.get("verify") is True
        or item.get("verify") == UNKNOWN
        or "verify" in str(item.get("coverage", "")).casefold()
        or isinstance(source, dict)
        and (source.get("verify") is True or source.get("verify") == UNKNOWN)
    )


def _verification(layers, fact, require_measured):
    if any(layer.get("present") is False or layer.get("present") == UNKNOWN for layer in layers):
        return (
            False,
            "Inventory availability is absent or unknown; measurement cannot establish it.",
        )
    if fact and _debt(layers[-1]):
        return False, "This fact explicitly requires verification."
    for index in range(len(layers) - 1, -1, -1):
        if _complete(layers[index].get("measured")):
            if any(_debt(layer) for layer in layers[index:]):
                return False, "The measured fact or block still explicitly requires verification."
            return True, "This dimension is qualified by a complete shop measurement."
    if any(_debt(layer) for layer in layers):
        return False, "Inherited inventory verification requires a fact-local measurement."
    if require_measured:
        return False, "No complete measurement by, date and instrument qualifies this dimension."
    return True, "Trusted nominal inventory dimension; no verification debt is declared."


def _sources(item, field):
    from prechips.rules.resolution import fraction, number

    def walk(mapping, parts, unit, layers, path):
        if not isinstance(mapping, dict):
            return
        units = mapping.get("units")
        if units in {"mm", "in", "inch"}:
            unit = "in" if units == "inch" else units
        found = False
        for key in _aliases(parts[0]):
            if key not in mapping:
                continue
            found = True
            current_unit = "mm" if key.endswith("_mm") else "in" if key.endswith("_in") else unit
            value = mapping[key]
            current_path = [*path, key]
            if len(parts) > 1:
                if isinstance(value, dict):
                    yield from walk(value, parts[1:], current_unit, [*layers, value], current_path)
                else:
                    yield UNKNOWN, layers, False, current_path
                continue
            fact = isinstance(value, dict) and "value" in value
            current_layers = [*layers, value] if fact else layers
            raw = value.get("value") if fact else value
            result = UNKNOWN
            if number(raw) and current_unit == "mm":
                result = raw
            elif current_unit == "in":
                parsed = fraction(raw)
                if parsed is not None:
                    result = float(parsed) * 25.4
            yield result, current_layers, fact, current_path
        if not found:
            yield UNKNOWN, layers, False, [*path, parts[0]]

    yield from walk(item, field.split("."), None, [item], [])


def _source(item, field):
    if not isinstance(item, dict):
        return UNKNOWN, [], False, field.split(".")
    fallback = None
    for source in _sources(item, field):
        if source[0] != UNKNOWN:
            return source
        if fallback is None or len(source[1]) > len(fallback[1]):
            fallback = source
    return fallback or (UNKNOWN, [item], False, field.split("."))


def nominal_length_mm(item, field):
    """Resolve length units and fact values without imposing measurement readiness."""
    return _source(item, field)[0]


def _cites(layers, path):
    from prechips.rules.resolution import _citations

    result = []
    for layer in layers:
        result.extend(_citations(layer.get("cite")))
        source = layer.get("source")
        if isinstance(source, dict):
            result.extend(_citations(source.get("cite")))
            result.extend(_citations(source.get("url")))
        else:
            result.extend(_citations(source))
        if path:
            result.extend(_citations(layer.get(path[-1] + "_cite")))
    return list(dict.fromkeys(result))


def length_fact(item, field, *, require_measured=True):
    """Return a millimetre fact qualified only by its own provenance ancestry.

    Complete local measurements override vendor/item verification, never an
    explicit verification flag on that same fact. Sibling facts cannot qualify
    or disqualify this dimension. Known nominals remain evidence, not certification.
    """
    value, layers, fact, path = _source(item, field)
    verified, reason = _verification(layers, fact, require_measured)
    if value == UNKNOWN:
        verified = False
        reason = "No numeric length with explicit millimetre or inch units is recorded."
    return {
        "value": value,
        "verified": verified,
        "cite": _cites(layers, path),
        "reason": reason,
    }


def measurement_entry(category, identity, field):
    """One stable instruction; aliases share an identity and lengths use mm."""
    authored_field = field
    field = _canonical(field)
    identity_field = f"{category}.{identity}.{field}"
    parts = [part for part in field.split(".") if not part.isdigit()]
    instrument, units = "steel rule or calipers", "mm"
    description = f"record {field}"
    if field.startswith("envelope.travel."):
        description = f"{field.rsplit('.', 1)[-1].upper()} safe usable travel, stop-to-stop"
    elif field == "envelope.spindle_to_table_max":
        description = "spindle nose to table at full Z-up"
        instrument = "steel rule or height gauge"
    elif field == "envelope.spindle_to_table_min":
        description = "spindle nose to table at full Z-down"
        instrument = "steel rule or height gauge"
    elif field == "gauge_len":
        description = (
            "mounted datum to holder exit face "
            "(spindle nose to holder face for a mill; toolpost reference for a lathe)"
        )
        instrument = "steel rule or height gauge"
    elif field == "projection":
        description = "holder face to tool tip for the installed cutting assembly"
    elif field.endswith("spindle_taper") or field.endswith(".taper"):
        description = "identify spindle taper"
        instrument, units = "inspect stamp or taper gauge", "identity"
    elif "angle" in field or any(part.endswith("_deg") for part in parts):
        description = "included tool point angle" if field == "point_angle" else f"record {field}"
        instrument, units = "protractor", "degrees"
    elif any(
        part in {"pieces", "plates", "flutes", "count", "positions", "holders", "plate_holes"}
        for part in parts
    ):
        instrument, units = "count and inspect", "count"
    elif "sizes" in parts and "_in" not in authored_field and "_mm" not in authored_field:
        instrument, units = "inspect size stamp or gauge", "identity"
    elif "tpi" in field:
        instrument, units = "thread pitch gauge", "threads/in"
    elif field.endswith("worm_ratio"):
        instrument, units = "index and count revolutions", "ratio"
    elif field.endswith("rpm_min") or field.endswith("rpm_max") or "ranges_rpm" in field:
        instrument, units = "tachometer", "rpm"
    elif field.endswith("weight_lb"):
        instrument, units = "scale", "lb"
    elif field.endswith("hp"):
        instrument, units = "inspect motor nameplate", "hp"
    return {
        "id": identity_field,
        "instruction": f"measure: {identity} {description}, {instrument}, {units}",
        "cite": [f"inventory.{identity_field}"],
    }


def envelope_measurements(item):
    """Dimension-specific length and taper readiness without losing vendor values."""
    facts = {field: length_fact(item, f"envelope.{field}") for field in ENVELOPE_LENGTH_FIELDS}
    item = item if isinstance(item, dict) else {}
    envelope = item.get("envelope")
    envelope = envelope if isinstance(envelope, dict) else {}
    layers = [item, envelope]
    verified, reason = _verification(layers, False, True)
    taper = envelope.get("spindle_taper", UNKNOWN)
    if not isinstance(taper, str) or not taper.strip() or taper.strip() == UNKNOWN:
        taper, verified, reason = UNKNOWN, False, "No spindle taper identity is recorded."
    facts["spindle_taper"] = {
        "value": taper,
        "verified": verified,
        "cite": _cites(layers, ["envelope", "spindle_taper"]),
        "reason": reason,
    }
    return facts


def _arguments(annotation):
    if hasattr(annotation, "__value__"):
        return _arguments(annotation.__value__)
    return get_args(annotation)


def _numeric_annotation(annotation):
    if annotation is float or annotation is int:
        return True
    return any(_numeric_annotation(arg) for arg in _arguments(annotation))


def _record_type(annotation):
    from prechips.model import InputModel

    if isinstance(annotation, type) and issubclass(annotation, InputModel):
        return annotation
    return next((model for arg in _arguments(annotation) if (model := _record_type(arg))), None)


def measurement_checklist(inventory):
    """Sorted, unique measurement debt from existing authored inventory records.

    Missing envelope dimensions are requested for mills or authored envelopes;
    missing gauge/projection dimensions are requested for authored holders. All
    other facts come from strict schema fields actually present in the input,
    including authored set members, not catalogue-generated member inventories.
    """
    from prechips.model import InventoryItem, LengthMeasurement
    from prechips.rules.resolution import fraction, number

    entries = {}

    def add(category, identity, field, item):
        canonical = _canonical(field)
        if category == "machines" and (item.get("kind") == "mill" or "envelope" in item):
            target = _LEGACY_MILL_FIELDS.get(canonical)
            if target is not None:
                if length_fact(item, target)["verified"]:
                    return
                canonical = target
        entry = measurement_entry(
            category, identity, field if canonical == _canonical(field) else canonical
        )
        existing = entries.setdefault(entry["id"], entry)
        sources = [*existing["cite"], f"inventory.{category}.{identity}.{field}"]
        _, layers, _, path = _source(item, field)
        sources.extend(_cites(layers, path))
        existing["cite"] = list(dict.fromkeys(sources))

    def walk(value, annotation, category, identity, path, layers, root):
        model = _record_type(annotation)
        if isinstance(value, dict):
            if model is LengthMeasurement:
                if length_fact(root, _canonical(path))["verified"]:
                    return
                raw = value.get("value", UNKNOWN)
                verified, _ = _verification([*layers, value], True, False)
                if not verified or raw == UNKNOWN:
                    add(category, identity, path, root)
                return
            if model is not None:
                current_layers = [*layers, value]
                for key in sorted(value):
                    if key in _METADATA or key.endswith("_cite") or key not in model.model_fields:
                        continue
                    if key == "members":
                        members = value[key]
                        if isinstance(members, dict):
                            for member, item in sorted(members.items()):
                                visit(category, f"{identity}/{member}", item, current_layers)
                        continue
                    walk(
                        value[key],
                        model.model_fields[key].annotation,
                        category,
                        identity,
                        f"{path}.{key}" if path else key,
                        current_layers,
                        root,
                    )
                return
            arguments = _arguments(annotation)
            mapping = next((arg for arg in arguments if get_origin(arg) is dict), annotation)
            arguments = _arguments(mapping)
            if get_origin(mapping) is dict and len(arguments) == 2:
                for key, child in sorted(value.items()):
                    walk(child, arguments[1], category, identity, f"{path}.{key}", layers, root)
            return
        if isinstance(value, list):
            arguments = _arguments(annotation)
            sequence = next((arg for arg in arguments if get_origin(arg) is list), annotation)
            arguments = _arguments(sequence)
            if arguments:
                for index, child in enumerate(value):
                    walk(child, arguments[0], category, identity, f"{path}.{index}", layers, root)
            return
        length_field = any(part.endswith(("_mm", "_in")) for part in path.split(".")) or (
            _canonical(path).split(".")[-1]
            in {
                "gauge_len",
                "projection",
                "oal",
                "flute_len",
                "dia",
                "shank",
            }
        )
        if length_field and length_fact(root, _canonical(path))["verified"]:
            return
        numeric = (
            number(value)
            or value == UNKNOWN
            and (_numeric_annotation(annotation) or path.split(".")[-1] == "shank")
        )
        if not numeric and "_in" in path and isinstance(value, str):
            numeric = fraction(value) is not None
        verified, _ = _verification(layers, False, False)
        if numeric and (not verified or value == UNKNOWN and any(_debt(layer) for layer in layers)):
            add(category, identity, path, root)

    def visit(category, identity, item, parents=()):
        if not isinstance(item, dict):
            return
        if category == "machines" and (item.get("kind") == "mill" or "envelope" in item):
            for field, fact in envelope_measurements(item).items():
                if not fact["verified"]:
                    add(category, identity, f"envelope.{field}", item)
        if category == "holders":
            for field in ("gauge_len", "projection"):
                if not length_fact(item, field)["verified"]:
                    add(category, identity, field, item)
        walk(item, InventoryItem, category, identity, "", list(parents), item)

    for category in ("machines", "tools", "holders", "fixtures", "gauges"):
        items = inventory.get(category)
        if isinstance(items, dict):
            for identity, item in sorted(items.items()):
                visit(category, identity, item)
    return [entries[key] for key in sorted(entries)]
