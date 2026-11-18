"""Requirement coverage: every CAD requirement band is gauged or process-held.

A requirement band is a manifest feature's ``requirements`` entry whose value is
a two-number ``[low, high]`` list; single values (thread class, through, finish,
nominal angles) are not bands. A plan binds a band by name,
``"<feature>.<requirement>"``, in one of two places:

- a ``gauge_checks`` entry's ``requirements`` list: the bands that gauge reading
  accepts. The entry's ``band_mm`` must lie within each named band (a gauge
  reads a distance, so a band wholly at or below zero is compared by magnitude),
  and a degree band (``*_deg``) cannot be named, since ``band_mm`` is in mm;
- plan ``process_held``, ``[{ requirements = [...], reason = "..." }]``: bands
  the process holds without a gauge reading (drill size, CNC interpolation,
  assembly transfer), each with the reason.

Every band must be bound exactly one way; a name that is no band, a band that
is both gauged and held, or one held twice refuses. Plans without a CAD
manifest have no bands and may not name any.
"""

from __future__ import annotations

import tomllib
from typing import TYPE_CHECKING

from prechips.checks import CheckError
from prechips.gauges import band, owners

if TYPE_CHECKING:
    from prechips.traveler import LoadedPlan


def _bands(features: object) -> dict[str, tuple[float, float]]:
    if not isinstance(features, dict):
        raise CheckError("cad.features: expected a table")
    bands = {}
    for name, feature in features.items():
        if not isinstance(feature, dict):
            continue
        requirements = feature.get("requirements", [])
        if not isinstance(requirements, list):
            raise CheckError(f"cad.features.{name}.requirements: expected an array")
        for key in requirements:
            value = feature.get(key)
            if (
                isinstance(value, list)
                and len(value) == 2
                and all(type(item) in (int, float) for item in value)
            ):
                bands[f"{name}.{key}"] = (float(value[0]), float(value[1]))
    return bands


def _names(value: object, bands: dict, where: str) -> list[str]:
    if (
        not isinstance(value, list)
        or not value
        or any(not isinstance(item, str) for item in value)
    ):
        raise CheckError(f"{where}: expected a nonempty array of feature.requirement")
    if len(set(value)) != len(value):
        raise CheckError(f"{where}: names a requirement twice")
    for name in value:
        if name not in bands:
            raise CheckError(f"{where}: {name!r} is not a CAD requirement band")
    return value


def _gauged(plan: LoadedPlan, bands: dict) -> set[str]:
    gauged = set()
    for where, owner in owners(plan):
        declared = owner.get("gauge_checks")
        if not isinstance(declared, list):
            continue
        for index, item in enumerate(declared, 1):
            if not isinstance(item, dict) or "requirements" not in item:
                continue
            item_where = f"{where}.gauge_checks[{index}]"
            names = _names(item["requirements"], bands, f"{item_where}.requirements")
            low, high = band(item.get("band_mm"), f"{item_where}.band_mm")
            for name in names:
                if name.endswith("_deg"):
                    raise CheckError(
                        f"{item_where}: {name} is in degrees; band_mm cannot read it"
                    )
                limit_low, limit_high = bands[name]
                if limit_high <= 0:
                    limit_low, limit_high = -limit_high, -limit_low
                if low < limit_low or high > limit_high:
                    raise CheckError(
                        f"{item_where}: band {low:g}–{high:g} mm is outside "
                        f"{name} {limit_low:g}–{limit_high:g} mm"
                    )
            gauged.update(names)
    return gauged


def _held(plan: LoadedPlan, bands: dict, gauged: set[str]) -> set[str]:
    declared = plan.data.get("process_held")
    if declared is None:
        return set()
    if not isinstance(declared, list) or not declared:
        raise CheckError("process_held: expected a nonempty array of tables")
    held = set()
    for index, item in enumerate(declared, 1):
        where = f"process_held[{index}]"
        if not isinstance(item, dict) or item.keys() != {"requirements", "reason"}:
            raise CheckError(f"{where}: expected a table with requirements and reason")
        reason = item["reason"]
        if not isinstance(reason, str) or not reason.strip():
            raise CheckError(f"{where}.reason: expected a nonempty string")
        for name in _names(item["requirements"], bands, f"{where}.requirements"):
            if name in held:
                raise CheckError(f"{where}: {name} is already process-held")
            if name in gauged:
                raise CheckError(f"{where}: {name} is also gauged")
            held.add(name)
    return held


def check(plan: LoadedPlan) -> None:
    if plan.cad is None:
        bands = {}
    else:
        with plan.cad.source.open("rb") as source:
            bands = _bands(tomllib.load(source).get("features"))
    gauged = _gauged(plan, bands)
    missing = sorted(bands.keys() - gauged - _held(plan, bands, gauged))
    if missing:
        raise CheckError(
            f"CAD requirement(s) neither gauged nor process-held: "
            f"{', '.join(missing)}; name each in a gauge_checks entry's "
            "requirements or in process_held"
        )
