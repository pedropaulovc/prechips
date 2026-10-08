"""Fact-local shop measurements, nominal lengths and the consumed-measurement checklist."""

from __future__ import annotations

from datetime import date

UNKNOWN = "unknown"
ENVELOPE_LENGTH_FIELDS = (
    "travel.x",
    "travel.y",
    "travel.z",
    "spindle_to_table_max",
    "spindle_to_table_min",
)
_UNITS = {"mm": "mm", "in": "in", "inch": "in"}
_NO_LENGTH = "No numeric length with explicit millimetre or inch units is recorded."


def length_keys(mapping, part, unit, *, bare=False):
    """Authored keys giving ``part`` a length: ``_mm``/``_in`` keys, or a bare key with units.

    More than one key is an ambiguous authoring; callers never choose between them.
    """
    stem = part.removesuffix("_mm").removesuffix("_in")
    keys = [stem + suffix for suffix in ("_mm", "_in") if stem + suffix in mapping]
    if stem in mapping and (bare or unit is not None):
        keys.insert(0, stem)
    return keys


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


def _trust(fact, require_measured):
    """Only the fact's own ``measured``/``verify`` qualify it; no record above it is read."""
    if fact is not None:
        if fact.get("verify") is True or fact.get("verify") == UNKNOWN:
            return False, "This fact explicitly requires verification."
        measured = fact.get("measured", UNKNOWN)
        if _complete(measured):
            return True, "This fact is qualified by its own complete shop measurement."
        if measured != UNKNOWN:
            return False, "This fact's measurement record is incomplete."
    if require_measured:
        return False, "No complete fact-local measurement (by, date, instrument) is recorded."
    return True, "Trusted nominal value; this fact declares no verification debt."


def record_trusted(fact, *, require_measured=True):
    """(trusted, reason) for a record carrying its own ``measured``/``verify`` qualifiers."""
    return _trust(fact if isinstance(fact, dict) else {}, require_measured)


def _resolve(item, field):
    """(value in mm, fact record or None, reason) for one dotted or tuple length path.

    A tuple names its first part by length stem and every later part as an exact
    key, so a full holder reference selects one entry of a tool projection map.
    """
    from prechips.rules.resolution import fraction, number

    exact = isinstance(field, tuple)
    parts = list(field) if exact else field.split(".")
    mapping, unit = item, None
    for index, part in enumerate(parts):
        if not isinstance(mapping, dict):
            return UNKNOWN, None, _NO_LENGTH
        literal = exact and index > 0
        if literal:
            keys = [part] if part in mapping else []
        else:
            unit = _UNITS.get(mapping.get("units"), unit)
            keys = length_keys(mapping, part, unit, bare=index < len(parts) - 1)
        if len(keys) > 1:
            return UNKNOWN, None, f"{' and '.join(keys)} author one length twice."
        if not keys:
            return UNKNOWN, None, _NO_LENGTH
        key = keys[0]
        if not literal:
            unit = "mm" if key.endswith("_mm") else "in" if key.endswith("_in") else unit
        mapping = mapping[key]
    fact = mapping if isinstance(mapping, dict) and "value" in mapping else None
    raw = fact["value"] if fact is not None else mapping
    if unit == "mm" and number(raw):
        return raw, fact, None
    if unit == "in" and not isinstance(raw, (bool, dict, list)):
        parsed = fraction(raw)
        if parsed is not None:
            return float(parsed) * 25.4, fact, None
    return UNKNOWN, fact, _NO_LENGTH


def nominal_length_mm(item, field):
    """Resolve length units and fact values without imposing measurement readiness."""
    return _resolve(item, field)[0]


def nominal_limits_mm(item, field):
    """A declared ``[least, greatest]`` diameter pair in mm, from ``<field>_mm`` or
    ``<field>_in`` (a plain pair or a ``{value, measured, verify}`` fact), without imposing
    measurement readiness; UNKNOWN unless one key authors two positive ordered numbers."""
    from prechips.rules.resolution import number

    keys = length_keys(item, field, None) if isinstance(item, dict) else []
    if len(keys) != 1:
        return UNKNOWN
    raw = item[keys[0]]
    raw = raw.get("value") if isinstance(raw, dict) else raw
    if not (isinstance(raw, list) and len(raw) == 2 and all(number(v) for v in raw)):
        return UNKNOWN
    scale = 25.4 if keys[0].endswith("_in") else 1.0
    low, high = raw[0] * scale, raw[1] * scale
    return [low, high] if 0 < low <= high else UNKNOWN


def _cites(item):
    """Inventory item and source citations; a measurement fact carries none of its own."""
    from prechips.rules.resolution import _citations

    if not isinstance(item, dict):
        return []
    result = _citations(item.get("cite"))
    source = item.get("source")
    if isinstance(source, dict):
        result.extend(_citations(source.get("cite")))
        result.extend(_citations(source.get("url")))
    else:
        result.extend(_citations(source))
    return list(dict.fromkeys(result))


def _fact(item, value, fact, reason, require_measured):
    verified, trust = _trust(fact, require_measured)
    if value == UNKNOWN:
        verified, trust = False, reason
    return {"value": value, "verified": verified, "cite": _cites(item), "reason": trust}


def length_fact(item, field, *, require_measured=True):
    """Return a millimetre fact qualified only by its own ``{value, measured, verify}``.

    A complete local measurement qualifies the value unless that fact's own
    ``verify`` is true or unknown. Item, block and source flags never qualify or
    disqualify it. A bare nominal is trusted only when ``require_measured`` is false.
    """
    value, fact, reason = _resolve(item, field)
    return _fact(item, value, fact, reason, require_measured)


def _angle(item, field):
    from prechips.rules.resolution import number

    value = item.get(field, UNKNOWN) if isinstance(item, dict) else UNKNOWN
    fact = value if isinstance(value, dict) and "value" in value else None
    raw = fact["value"] if fact is not None else value
    return (raw, fact) if number(raw) else (UNKNOWN, fact)


def nominal_angle_deg(item, field):
    """A degree value, unwrapping a fact record, without imposing measurement readiness."""
    return _angle(item, field)[0]


def angle_fact(item, field, *, require_measured=True):
    """A degree fact under the same fact-local trust as ``length_fact``."""
    value, fact = _angle(item, field)
    return _fact(item, value, fact, "No numeric angle in degrees is recorded.", require_measured)


def measurement_entry(category, identity, field):
    """A report/checklist identity for one consumed fact, including tool/holder pairs."""
    parts = field if isinstance(field, tuple) else tuple(field.split("."))
    canonical = (
        (parts[0].removesuffix("_mm").removesuffix("_in"), *parts[1:])
        if isinstance(field, tuple)
        else tuple(part.removesuffix("_mm").removesuffix("_in") for part in parts)
    )
    field = ".".join(canonical)
    identity_field = f"{category}.{identity}.{field}"
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
        description = "spindle nose to mounted holder exit face"
        instrument = "steel rule or height gauge"
    elif field.startswith("projection."):
        description = f"holder face to tool tip installed in {parts[-1]}"
    elif field == "bed_height":
        description = "table to vise bed supporting the parallels or part"
        instrument = "height gauge"
    elif field == "point_angle":
        description = "included drill point angle"
        instrument, units = "protractor", "degrees"
    elif field == "dia":
        description = "selected cutter diameter"
        instrument = "micrometer"
    elif field == "oal":
        description = "selected tool overall length"
    elif field == "grip":
        description = "installed tool insertion from holder exit face"
    elif field == "lead":
        description = "reamer lead length"
    elif field == "pilot_len":
        description = "centre drill pilot length, countersink start to point tip (Table 6 C)"
        instrument = "calipers"
    elif field == "angle_deg":
        description = "centre drill countersink included angle"
        instrument, units = "protractor", "degrees"
    return {
        "id": identity_field,
        "instruction": f"measure: {identity} {description}, {instrument}, {units}",
        "units": units,
        "cite": [f"inventory.{identity_field}"],
    }


def envelope_measurements(item):
    """Per-dimension M5 envelope limits, each qualified only by its own fact."""
    return {field: length_fact(item, f"envelope.{field}") for field in ENVELOPE_LENGTH_FIELDS}


def measurement_checklist(findings):
    """Only measurement debt that produced an unknown on the current input plans."""
    entries = {}
    for finding in findings:
        if finding.status != UNKNOWN:
            continue
        for entry in finding.numbers.get("measurements", []):
            existing = entries.setdefault(entry["id"], {**entry, "cite": []})
            existing["cite"] = sorted(set(existing["cite"]) | set(entry["cite"]))
    return [entries[key] for key in sorted(entries)]
