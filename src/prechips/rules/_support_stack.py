"""Classify nominal bearing layers without consuming native auxiliary obstacles.

``bearing_layers`` returns ``(layers, issues)``. Each layer is the authored
``(field, reference, orientation)`` for one actual legacy bearing item; parallels
remain the caller's responsibility. Each issue is a plain ``(field, reason)`` pair
and makes the stack unresolved, even when a selected layer is also returned.
Valid posed supports remain independent native obstacles, never bearing heights.
"""

from fractions import Fraction

from pydantic import ValidationError

from prechips.model import PlacedSupport, Reference
from prechips.rules.resolution import identity, length_mm, number, resolve

_UNKNOWN = "unknown"
_ABSENT = (None, "none", "not_applicable")
_REST_FIELDS = ("ops", "jaw_side", "jaw_lead_mm", "at_z_mm", "engage_at_z_mm")


def support_height(item, orientation=None):
    """Read the existing nominal height policy, not a physical measurement proof."""
    if not item:
        return _UNKNOWN
    height = length_mm(item, "height")
    if number(height):
        return height
    # Blocks have three different dimensions: use only the authored orientation.
    if isinstance(orientation, str) and orientation.endswith(" in height"):
        try:
            selected = float(Fraction(orientation.removesuffix(" in height")))
        except (ValueError, ZeroDivisionError):
            return _UNKNOWN
        if selected in item.get("size_in", []):
            return selected * 25.4
    return _UNKNOWN


def _legacy_layer(bundle, field, value, orientation, issues):
    if isinstance(value, dict):
        try:
            Reference.model_validate(value)
        except ValidationError:
            issues.append((field, "Malformed legacy bearing reference."))
            return None
        if any(key in value for key in _REST_FIELDS):
            issues.append((field, "A rest or jaw role does not declare a bearing layer."))
            return None
        reference = value.get("ref")
        orientation = value.get("orientation", orientation)
    else:
        reference = value
    if not isinstance(reference, str) or reference.strip() in ("", *_ABSENT[1:], _UNKNOWN):
        issues.append((field, "A bearing source must be a known, non-empty inventory reference."))
        return None
    if orientation is not None and not isinstance(orientation, str):
        issues.append((field, "A bearing orientation must be authored text or absent."))
        return None
    item = resolve(bundle, "fixtures", reference)
    if not isinstance(item, dict) or not item or item.get("kind") == _UNKNOWN:
        issues.append((field, "The bearing inventory source is unknown or unresolved."))
        return None
    return field, reference, orientation


def bearing_layers(bundle, hold):
    """Select at most one bearing item; malformed or ambiguous declarations are debt.

    Posed entries are skipped only after structural/source validation. Their pose
    and borrowed-stock geometry remain native proof, and no authored input is changed.
    An explicit riser selects the bearing item; one matching supports entry is merely
    a second spelling only when its exact inventory identity and orientation agree.
    """
    if not isinstance(hold, dict):
        return [], [("supports", "The hold support declaration is malformed.")]
    issues, candidates, seen = [], [], set()
    orientation = hold.get("support_orientation")
    supports = hold.get("supports")
    if isinstance(supports, list):
        values = supports
    elif supports in _ABSENT:
        values = []
    elif isinstance(supports, str):
        values = [supports]
    else:
        values = []
        issues.append(("supports", "Supports must be a reference or a list of support entries."))
    for value in values:
        if isinstance(value, dict) and "placement" in value:
            try:
                placed = PlacedSupport.model_validate(value)
            except ValidationError:
                issues.append(("supports", "Malformed posed auxiliary support."))
                continue
            if placed.id in seen:
                issues.append(("supports", "Posed auxiliary support ids must be unique."))
                continue
            seen.add(placed.id)
            if placed.ref is not None:
                item = resolve(bundle, "fixtures", placed.ref)
                if not isinstance(item, dict) or not item or item.get("kind") == _UNKNOWN:
                    issues.append(
                        ("supports", "The auxiliary inventory source is unknown or unresolved.")
                    )
            continue
        layer = _legacy_layer(bundle, "supports", value, orientation, issues)
        if layer is not None:
            candidates.append(layer)
    if len(candidates) > 1:
        issues.append(
            ("supports", "Multiple legacy supports do not declare serial bearing layers.")
        )
    riser = hold.get("riser")
    if riser not in _ABSENT:
        if not isinstance(riser, str):
            issues.append(("riser", "A riser must be one inventory reference."))
            return [], issues
        selected = _legacy_layer(bundle, "riser", riser, orientation, issues)
        if selected is None:
            return [], issues
        for _, reference, support_orientation in candidates:
            if identity(bundle, reference, "fixtures") != identity(bundle, riser, "fixtures"):
                issues.append(
                    ("supports", "A legacy support differs from the explicitly selected riser.")
                )
            elif support_orientation != selected[2]:
                issues.append(
                    ("supports", "The legacy support and explicit riser orientations conflict.")
                )
        return [selected], issues
    return candidates if len(candidates) == 1 else [], issues
