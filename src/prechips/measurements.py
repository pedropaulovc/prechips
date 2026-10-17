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
    if not isinstance(value, dict) or set(value) != {"status", "by", "date", "instrument"}:
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
        if isinstance(measured, dict):
            status = measured.get("status", "assumed")
            if status != "measured":
                by = measured.get("by", UNKNOWN)
                return False, (
                    f"This fact's measurement is {status} (by: {by}), "
                    "not a physical shop measurement."
                )
            if _complete(measured):
                return True, "This fact is qualified by its own complete shop measurement."
        if measured != UNKNOWN:
            return False, "This fact's measurement record is incomplete."
    if require_measured:
        return False, (
            "No complete fact-local measurement (status = measured, by, date, instrument) "
            "is recorded."
        )
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
            refused = next(
                (
                    mapping[key]
                    for key in keys
                    if isinstance(mapping[key], dict)
                    and "value" in mapping[key]
                    and not _trust(mapping[key], False)[0]
                ),
                None,
            )
            return UNKNOWN, refused, f"{' and '.join(keys)} author one length twice."
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
        trust = f"{reason} {trust}" if not verified and fact is not None else reason
        verified = False
    measured = fact.get("measured") if isinstance(fact, dict) else None
    status = measured.get("status", "assumed") if isinstance(measured, dict) else UNKNOWN
    return {
        "value": value,
        "verified": verified,
        "cite": _cites(item),
        "reason": trust,
        "measurement_status": status,
    }


def length_fact(item, field, *, require_measured=True):
    """Return a millimetre fact qualified only by its own ``{value, measured, verify}``.

    An explicitly measured, complete local record qualifies the value unless that fact's
    own ``verify`` is true or unknown. Assumed, illustrative and status-less records never
    qualify it. A bare nominal is trusted only when ``require_measured`` is false.
    """
    value, fact, reason = _resolve(item, field)
    return _fact(item, value, fact, reason, require_measured)


def limits_fact(item, field, *, require_measured=True):
    """A length-limit pair under the same fact-local trust as ``length_fact``."""
    value = nominal_limits_mm(item, field)
    keys = length_keys(item, field, None) if isinstance(item, dict) else []
    raw = item[keys[0]] if len(keys) == 1 else None
    fact = raw if isinstance(raw, dict) and "value" in raw else None
    return _fact(
        item, value, fact, "No positive ordered length-limit pair is recorded.", require_measured
    )


def _angle(item, field):
    from prechips.rules.resolution import number

    value = item.get(field, UNKNOWN) if isinstance(item, dict) else UNKNOWN
    fact = value if isinstance(value, dict) and "value" in value else None
    raw = fact["value"] if fact is not None else value
    return (raw, fact) if number(raw) else (UNKNOWN, fact)


def angle_fact(item, field, *, require_measured=True):
    """A degree fact under the same fact-local trust as ``length_fact``."""
    value, fact = _angle(item, field)
    return _fact(item, value, fact, "No numeric angle in degrees is recorded.", require_measured)


def cited_fact(item, field, *, tested=False):
    """A non-length fact (``{value, cite, measured, verify}``) under its own qualifiers only.

    It is trusted when its value is positive and it has a known citation or a complete
    ``status = "measured"`` record, and its own ``verify`` is not true or unknown. A bare
    number, a blank or unknown cite and an incomplete, assumed or illustrative measurement
    are debt; a cite never stands in for a refused measurement. ``tested`` facts (an
    adhesive's strength) also need a known ``test`` naming their method, never parsed.
    """
    from prechips.rules.resolution import _citations, number

    raw = item.get(field, UNKNOWN) if isinstance(item, dict) else UNKNOWN
    fact = raw if isinstance(raw, dict) and "value" in raw else None
    value = fact["value"] if fact is not None else raw
    value = value if number(value) and value > 0 else UNKNOWN
    cite = _citations(fact.get("cite")) if fact is not None else []
    measured = fact.get("measured", UNKNOWN) if fact is not None else UNKNOWN
    status = measured.get("status", "assumed") if isinstance(measured, dict) else UNKNOWN
    result = {"value": value, "verified": False, "cite": cite, "measurement_status": status}
    if value == UNKNOWN:
        return {**result, "reason": f"No positive {field} is recorded."}
    if fact is None:
        return {**result, "reason": f"{field} is a bare value with no citation or measurement."}
    if fact.get("verify") is True or fact.get("verify") == UNKNOWN:
        return {**result, "reason": "This fact explicitly requires verification."}
    if measured != UNKNOWN:
        trusted, reason = _trust({"measured": measured}, True)
        if not trusted:
            return {**result, "reason": reason}
    elif not cite:
        return {**result, "reason": f"{field} names no citation or measurement."}
    test = fact.get("test", UNKNOWN)
    if tested and (not isinstance(test, str) or test.strip() in ("", UNKNOWN)):
        return {**result, "reason": f"{field} does not name the test method its value is from."}
    reason = (
        "This fact is qualified by its own complete shop measurement."
        if measured != UNKNOWN
        else "This fact is qualified by its own citation."
    )
    return {**result, "verified": True, "reason": reason}


def measurement_entry(category, identity, field, *, status=None, item=None, subject=None):
    """Describe one consumed fact; display context never changes its identity or trust.

    Tuple/list paths preserve exact member and holder keys, including embedded dots.
    ``item`` supplies only kind/shape context and ``subject`` only the shop-facing name.
    """
    exact = isinstance(field, (tuple, list))
    parts = tuple(field) if exact else tuple(field.split("."))
    canonical = (
        (parts[0].removesuffix("_mm").removesuffix("_in"), *parts[1:])
        if exact
        else tuple(part.removesuffix("_mm").removesuffix("_in") for part in parts)
    )
    field = ".".join(canonical)
    identity_field = f"{category}.{identity}.{field}"
    item = item if isinstance(item, dict) else {}
    kind = item.get("kind")
    centre_drill = kind in {"center_drill", "center_drill_set"}
    made = item.get("shop_made") is True or kind == "custom"
    instrument, units = "steel rule or calipers", "mm"
    description = " ".join(part.replace("_", " ") for part in canonical)
    if field.startswith("envelope.travel."):
        description = f"{field.rsplit('.', 1)[-1].upper()} safe usable travel, stop-to-stop"
        instrument = "calibrated DRO or indicator"
    elif field == "envelope.spindle_to_table_max":
        description = "spindle nose to table at full Z-up"
        instrument = "steel rule or height gauge"
    elif field == "envelope.spindle_to_table_min":
        description = "spindle nose to table at full Z-down"
        instrument = "steel rule or height gauge"
    elif field == "spindle.rotation":
        description = "spindle rotation direction in the declared viewing convention"
        instrument, units = "safe direction observation", "cw/ccw"
    elif field == "gauge_len":
        description = "spindle nose to mounted holder exit face"
        instrument = "steel rule or height gauge"
    elif field.startswith("projection."):
        description = "holder face to mounted tool tip"
    elif field == "bed_height":
        description = (
            "table to vise bed supporting the parallels or part"
            if kind == "vise"
            else "table to work-support contact surface"
        )
        instrument = "height gauge"
        if made and kind != "vise":
            description = f"drawing support height; check as made: {description}"
            instrument = "calipers or height gauge"
    elif field in {"length", "width", "height"} and category in {"fixtures", "holders", "machines"}:
        description = {
            "length": "overall fixture length along its local X axis",
            "width": "overall fixture width along its local Y axis",
            "height": "fixture height, bottom bearing face to top contact surface",
        }[field]
        if kind in {"parallels", "parallels_set"}:
            description = {
                "length": "parallel length along the jaws",
                "width": "parallel width across the clamp axis",
                "height": "parallel height between its bottom and top bearing faces",
            }[field]
        instrument = "calipers or height gauge" if field == "height" else "steel rule or calipers"
        if made:
            description = f"drawing {field}; check as made: {description}"
    elif field in {"jaw_height", "jaw_width", "jaw_depth", "opening"}:
        description = {
            "jaw_height": (
                "jaw height above its supporting bed" if kind == "vise" else "jaw height"
            ),
            "jaw_width": "jaw face width",
            "jaw_depth": "jaw depth, gripping face to back",
            "opening": "usable jaw opening",
        }[field]
        if kind in {"chuck_3jaw", "chuck_4jaw", "follow_rest"} and field != "opening":
            jaw_owner = "follow rest" if kind == "follow_rest" else "chuck"
            description = {
                "jaw_height": f"{jaw_owner} jaw radial height outward from the gripping surface",
                "jaw_width": f"{jaw_owner} jaw tangential width",
                "jaw_depth": f"{jaw_owner} jaw axial depth",
            }[field]
    elif field == "resolution":
        description = (
            "gauge least readable step"
            if category == "gauges"
            else "installed DRO least readable step"
        )
        instrument = (
            "installed gauge graduations and calibration check"
            if category == "gauges"
            else "installed readout and indicator check"
        )
    elif field in {"ra_range", "range_ra"}:
        description = "usable surface-roughness comparison range"
        instrument, units = "roughness standard or comparator", "µm"
    elif canonical[0] == "solids":
        name = ".".join(canonical[1:])
        solids = item.get("solids")
        solid = next(
            (
                value
                for value in (solids if isinstance(solids, list) else ())
                if isinstance(value, dict) and value.get("name") == name
            ),
            {},
        )
        label = solid.get("label") or name.replace("_", " ").replace("-", " ")
        shape = solid.get("shape")
        if shape == "box":
            description = (
                f"fixture solid {label} length, width and height, and position from its "
                "mounting datum"
            )
            instrument = "calipers and height gauge"
        elif shape == "cylinder":
            description = (
                f"fixture solid {label} bore diameter, depth and axis position from its "
                "mounting datum"
                if solid.get("void") is True
                else f"fixture solid {label} diameter, axial length and axis position from "
                "its mounting datum"
            )
            instrument = (
                "bore gauge, depth gauge and height gauge"
                if solid.get("void") is True
                else "micrometer or calipers, and height gauge"
            )
        else:
            description = f"fixture solid {label} dimensions and position from its mounting datum"
            instrument = "calipers and height gauge"
        if made and solid.get("supply", "made") == "made":
            description = f"drawing dimensions; check as made: {description}"
    elif field == "flute_len":
        description = (
            "centre drill usable cutting length"
            if centre_drill
            else "selected cutter usable flute length"
        )
        instrument = "calipers"
    elif field == "shank":
        description = (
            "centre drill countersink body diameter A (Table 6 A)"
            if centre_drill
            else "shank diameter"
        )
        instrument = "micrometer or calipers"
    elif field == "reach":
        description = "usable cutting reach"
        instrument = "calipers or optical comparator"
    elif field == "nose_radius":
        description = "cutting-edge nose radius"
        instrument = "radius gauge or optical comparator"
    elif field == "blade_width":
        description = "grooving or parting blade front cutting-edge width"
        instrument = "micrometer or calipers"
    elif field in {
        "edge_len",
        "head_len",
        "shank_width",
        "functional_width",
        "body_width",
        "body_depth",
    }:
        description = {
            "edge_len": "insert cutting-edge length",
            "head_len": "tool head length from the nose to the shank",
            "shank_width": "tool shank width",
            "functional_width": "nose centre to tool shank back face",
            "body_width": "holder body width along the spindle axis",
            "body_depth": "holder body depth in the radial direction",
        }[field]
        instrument = "calipers"
    elif field == "gauge_dia":
        description = "mounted holder outside diameter"
        instrument = "micrometer or calipers"
    elif field == "max_work":
        description = "rotary table supported work-diameter limit"
    elif field == "bore_dia":
        description = "central bore diameter"
        instrument = "inside micrometer or bore gauge"
    elif field == "tip":
        description = "edge finder contacting-tip diameter"
        instrument = "micrometer"
    elif field == "point_angle":
        description = "pilot point included angle" if centre_drill else "included drill point angle"
        instrument, units = "drill point gauge or protractor", "degrees"
    elif field == "dia":
        description = (
            "centre drill pilot diameter D (Table 6 D)"
            if centre_drill
            else "jaw bar outside diameter"
            if category == "fixtures" and kind == "round_bar"
            else "fixture outside diameter"
            if category == "fixtures"
            else "selected cutter diameter"
        )
        instrument = "micrometer or calipers" if centre_drill else "micrometer"
    elif field == "oal":
        description = "selected tool overall length"
    elif field == "grip":
        description = "installed tool insertion from holder exit face"
    elif field == "lead":
        description = "reamer lead length"
    elif field == "pilot_len":
        description = (
            "centre drill pilot length, countersink start to point tip (Table 6 C)"
            if centre_drill
            else "pilot length, shoulder to point tip"
        )
        instrument = "calipers"
    elif field == "angle_deg":
        description = (
            "centre drill countersink included angle" if centre_drill else "included angle"
        )
        instrument, units = "protractor", "degrees"
    elif field in {"insert_angle_deg", "entering_angle_deg"}:
        description = {
            "insert_angle_deg": "insert included angle",
            "entering_angle_deg": "installed cutting-edge entering angle",
        }[field]
        instrument, units = "protractor", "degrees"
    elif field.endswith("_deg"):
        instrument, units = "protractor", "degrees"
    elif field in {"body_dia", "quill_dia", "tailstock.quill_dia", "spigot_dia"}:
        description = {
            "body_dia": "fixture body outside diameter",
            "quill_dia": "tailstock quill outside diameter",
            "tailstock.quill_dia": "tailstock quill outside diameter",
            "spigot_dia": "locating spigot diameter",
        }[field]
        instrument = "micrometer or calipers"
    elif field in {"body_length", "spigot_length", "thickness", "centre_height"}:
        description = {
            "body_length": "fixture body axial length",
            "spigot_length": "locating spigot length from its shoulder",
            "thickness": "fixture thickness between its bearing faces",
            "centre_height": "base contact face to spindle or centre axis",
        }[field]
        instrument = "height gauge" if field == "centre_height" else "calipers"
    elif field == "kerf":
        description = "saw blade cutting width across the tooth set"
        instrument = "micrometer or calipers"
    elif field in {"button_dia_limits", "button_bore_limits", "pin_dia_limits"}:
        description = {
            "button_dia_limits": "filing button outside-diameter limits",
            "button_bore_limits": "filing button bore-diameter limits",
            "pin_dia_limits": "filing button pin-diameter limits",
        }[field]
        instrument = "bore gauge" if field == "button_bore_limits" else "micrometer"
    elif field == "button_runout":
        description = "filing button outside-diameter runout about its bore"
        instrument = "dial indicator on a fitted mandrel"
    elif field == "range" and category == "gauges":
        description = "gauge usable measuring range"
        instrument = "calibrated gauge blocks or length standard"
    elif field == "verify":
        description = "physical dimensions and condition required by the selected setup"
        instrument = "appropriate calibrated gauges and visual inspection"
    display_subject = identity if subject is None else subject
    instruction = f"measure: {display_subject} {description}, {instrument}, {units}"
    if status in {"assumed", "illustrative"}:
        instruction += f" ({status} value, not physically measured)"
    return {
        "id": identity_field,
        "category": category,
        "identity": identity,
        "field": list(canonical),
        "instruction": instruction,
        "units": units,
        "cite": [f"inventory.{identity_field}"],
    }


def _debt_entry(category, identity, field, status, reason, cite, *, item=None):
    entry = measurement_entry(category, identity, field, status=status, item=item)
    entry["status"] = status
    entry["reason"] = reason
    entry["cite"] = sorted(set(entry["cite"]) | set(cite))
    return entry


def _fact_debt(fact, field, category, identity, *, item):
    if fact["verified"]:
        return None
    status = fact["measurement_status"]
    if status == UNKNOWN:
        status = "missing" if fact["value"] == UNKNOWN else "nominal"
    return _debt_entry(category, identity, field, status, fact["reason"], fact["cite"], item=item)


def length_debt(item, field, category, identity, *, require_measured=False):
    """One refused consumed length, with a stable id and current trust diagnostics."""
    return _fact_debt(
        length_fact(item, field, require_measured=require_measured),
        field,
        category,
        identity,
        item=item,
    )


def limits_debt(item, field, category, identity, *, require_measured=False):
    """One refused consumed length-limit pair, never inferred from attribution prose."""
    return _fact_debt(
        limits_fact(item, field, require_measured=require_measured),
        field,
        category,
        identity,
        item=item,
    )


def record_debt(item, category, identity, field, *, require_measured=False, owner=None):
    """One refused whole-record fact; ``owner`` gives scalar/solid facts display context."""
    trusted, reason = record_trusted(item, require_measured=require_measured)
    if trusted:
        return None
    measured = item.get("measured") if isinstance(item, dict) else None
    status = measured.get("status", "assumed") if isinstance(measured, dict) else "unmeasured"
    return _debt_entry(
        category,
        identity,
        field,
        status,
        reason,
        _cites(item),
        item=item if owner is None else owner,
    )


def envelope_measurements(item):
    """Per-dimension M5 envelope limits, each qualified only by its own fact."""
    return {field: length_fact(item, f"envelope.{field}") for field in ENVELOPE_LENGTH_FIELDS}


def measurement_checklist(findings, *, debts=()):
    """Consumed refused facts: rule unknowns plus host-only kernel input debt."""
    entries = {}
    current_debts = list(debts)
    for finding in findings:
        if finding.status == UNKNOWN:
            current_debts.extend(finding.numbers.get("measurements", []))
    for entry in current_debts:
        existing = entries.setdefault(entry["id"], {**entry, "cite": []})
        existing["cite"] = sorted(set(existing["cite"]) | set(entry["cite"]))
        for key in ("status", "reason"):
            if key in entry and key not in existing:
                existing[key] = entry[key]
    return [entries[key] for key in sorted(entries)]
