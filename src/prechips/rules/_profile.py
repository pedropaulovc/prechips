"""Surface-profile zones give the BASIC dimensions they govern a band (HA#1544).

An ASME Y14.5 SURFACE PROFILE ``t`` to a datum reference frame holds every point of its
surface inside a zone ``t`` wide about the true profile the BASIC dimensions locate from
that frame, ``U`` of it on the side where material is added (``t / 2`` when unstated).
The band it gives a governed BASIC requirement is pointwise: a length read along the
surface normal from the DRF-located BASIC origin (a radius about its BASIC centre, a
height at a point of the surface; a diameter spans two such radii), never a fitted size.
Docs: docs/features.md "Surface profiles".
"""

import math

from prechips import trig
from prechips.model import profile_target

from .resolution import UNKNOWN, number, record

# BASIC diameters: the surface moves radially on both sides, so each offset counts twice.
DIAMETERS = frozenset({"dia", "nominal_dia"})


def governing(bundle, name, requirement):
    """``[(owner, entry)]``: each manifest surface profile governing ``requirement`` of
    feature ``name``, with its ``surface_profile_governs`` entry."""
    return [
        (owner, entry)
        for owner, feature in record(bundle.features.get("features")).items()
        for key, entry in record(feature.get("surface_profile_governs")).items()
        if profile_target(owner, key) == (name, requirement)
    ]


def requirement_band(bundle, name, requirement):
    """``(band, reason)``: the acceptance band ``[lo, hi]`` (manifest units, or degrees) of
    ``requirement`` of feature ``name``, or ``None`` and why it is unknown.

    A drawing band is returned as drawn. A BASIC scalar governed by surface profiles takes
    the intersection of their bands; each band contains the BASIC value, so the
    intersection is never empty. One unresolved profile leaves the requirement unknown."""
    feature = record(bundle.feature_definitions.get(name))
    value = feature.get(requirement, UNKNOWN)
    if isinstance(value, list) and len(value) == 2 and all(number(v) for v in value):
        return list(value), "drawing band"
    profiles = governing(bundle, name, requirement)
    if not profiles:
        return None, f"the drawing states no band for {name} {requirement}"
    bands = []
    for owner, entry in profiles:
        band, reason = _zone_band(bundle, owner, entry, feature, value, requirement)
        if band is None:
            return None, f"{owner} surface profile: {reason}"
        bands.append(band)
    owners = ", ".join(owner for owner, _ in profiles)
    return [max(lo for lo, _ in bands), min(hi for _, hi in bands)], f"surface profile {owners}"


def _zone_band(bundle, owner, entry, feature, nominal, requirement):
    """``(band, reason)`` one profile of feature ``owner`` gives the BASIC ``nominal`` of
    ``requirement`` of ``feature``, which it governs with ``entry``."""
    profile = record(record(bundle.features.get("features")).get(owner))
    zone = profile.get("surface_profile", UNKNOWN)
    datums = profile.get("surface_profile_datums", UNKNOWN)
    if not number(zone):
        return None, "the zone t is unknown"
    if not isinstance(datums, list) or any(not d.strip() or d == UNKNOWN for d in datums):
        return None, "the datum reference frame is unknown"
    if not datums:
        return None, "with no datums it controls form only, never a size, location or angle"
    if entry == UNKNOWN:
        return None, "how the requirement reads in the zone is unknown"
    if isinstance(entry, dict) and "tilt_across" in entry:
        across = entry["tilt_across"]
        extent = across if number(across) else feature.get(across)
        limits = [extent] if number(extent) else extent if isinstance(extent, list) else []
        if not limits or not all(number(v) for v in limits):
            return None, f"the least limit of {across} is unknown"
        least = min(limits)
        if zone >= least:
            return None, f"t {zone} is not less than the {least} face extent, so no tilt is bounded"
        # asin(t / l) as atan2 of the legs: trig's platform-stable arc tangent.
        tilt = math.degrees(trig.atan2(zone, math.sqrt(least * least - zone * zone)))
        return [nominal - tilt, nominal + tilt], None
    disposition = profile.get("surface_profile_u", zone / 2)
    if not number(disposition):
        return None, "the disposition U is unknown"
    sense, obliquity = (
        (entry["sense"], entry["obliquity_deg"]) if isinstance(entry, dict) else (entry, 0.0)
    )
    scale = (2.0 if requirement in DIAMETERS else 1.0) / trig.cos(math.radians(obliquity))
    added, removed = disposition * scale, (zone - disposition) * scale
    if sense == "increases":
        return [nominal - removed, nominal + added], None
    return [nominal - added, nominal + removed], None
