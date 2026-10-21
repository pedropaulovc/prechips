"""Compare finishing setups to drawing datum cuts, never to frame names.

An indicated pickup must originate after the referenced datum's finishing cut;
indicating an earlier pilot does not establish a later reamed datum. A surface profile
relates each datum of its reference frame at its zone ``t``; a profile with no datums
controls form only and relates none. A ``height_from`` reads the height band, a BASIC
height's band derived from its surface profile included.
Registered members retain independent final cuts and datum producers. An indicated
pickup never transfers a sibling's datum or unproved protected material.
"""

from prechips.findings import Finding
from prechips.material_routes import MaterialGraph
from prechips.rules._profile import datum_features, requirement_band
from prechips.rules.resolution import (
    HAND_FINISH,
    HAND_THREAD,
    MANUAL,
    SAW_OPS,
    TAP_OPS,
    UNKNOWN,
    operation_material_status,
    operation_members,
    operations,
)

_NONFINISH = {"spot", "inspect", "release", "fit", "scribe", "transfer", "deburr"} | SAW_OPS


def _mapping(value):
    return value if isinstance(value, dict) else {}


def _number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _cuts(bundle, feature, workpiece_id=None):
    """Final forming cuts of a feature: its labeled ops plus ops whose explicit faces own it.
    Filing and manual threading materially form faces; other manual work does not.

    An unresolved datum (no feature name) has no cuts, never every op.
    Registered plans select and demote pilots per member; the default result is
    the ordered union, retaining a drill that finishes a different physical member.
    """
    if not isinstance(feature, str):
        return []
    members = bundle.plan.get("workpieces")
    if workpiece_id is None and isinstance(members, dict):
        selected = {id(op) for member in members for _, _, op in _cuts(bundle, feature, member)}
        return [
            (index, setup, op)
            for index, setup, op in _cuts_unselected(bundle, feature)
            if id(op) in selected or operation_members(bundle, setup, op) is None
        ]
    cuts = _cuts_unselected(bundle, feature, workpiece_id)
    # A pilot is not the final datum when reaming happens in a later setup.
    if any(op.get("do") in TAP_OPS | {"ream", "bore"} for _, _, op in cuts):
        cuts = [(index, setup, op) for index, setup, op in cuts if op.get("do") != "drill"]
    return cuts


def _cuts_unselected(bundle, feature, workpiece_id=None):
    """Keep potential cuts until ownership is checked, before granting datum credit."""
    order = {id(setup): index for index, setup in enumerate(bundle.plan["setups"])}
    return [
        (order[id(setup)], setup, op)
        for setup, op in operations(bundle, feature, owned=True, workpiece_id=workpiece_id)
        if op.get("do", UNKNOWN) not in _NONFINISH | (MANUAL - HAND_FINISH - HAND_THREAD)
        and not op.get("do", UNKNOWN).startswith("rough")
    ]


def _label(cut):
    return f"{cut[1]['id']}:{cut[2]['op']}"


def _indicated(
    setups,
    feature_cut,
    datum_cut,
    datum_feature,
    datum_name,
    *,
    bundle=None,
    workpiece_id=None,
):
    _, setup, _ = feature_cut
    transfer = _mapping(_mapping(setup.get("zero")).get("transfer"))
    selected = transfer.get("indicate", [])
    if isinstance(selected, str):
        selected = [selected]
    if datum_feature not in selected and datum_name not in selected:
        return False
    source = transfer.get("from")
    source_index = next((index for index, item in enumerate(setups) if item["id"] == source), None)
    if bundle is not None and workpiece_id is not None:
        source_setup = next((item for item in setups if item["id"] == source), None)
        if source_setup is None:
            return False
        if workpiece_id not in (MaterialGraph(bundle.plan).members(source) or ()):
            return False
        if (
            operation_material_status(
                bundle,
                source_setup,
                datum_cut[1],
                datum_feature,
                producer_op=datum_cut[2],
                workpiece_id=workpiece_id,
            )
            is not True
        ):
            return False
    # Pickup from an earlier intermediate cannot prove the finished datum.
    return source_index is not None and datum_cut[0] <= source_index < feature_cut[0]


def evaluate(bundle):
    setups = bundle.plan["setups"]
    features = bundle.features["features"]
    datum_map = datum_features(bundle)
    budget = _mapping(bundle.policy.get("numbers")).get("refixture_budget_mm", "unknown")
    verified = bundle.policy.get("numbers_verify", False)
    if isinstance(verified, dict):
        verified = verified.get("refixture_budget_mm", False)
    if verified:
        budget = "unknown"
    # Profile zones and the bands they derive are in manifest units; the budget is mm.
    scale = {"mm": 1.0, "in": 25.4}.get(bundle.features.get("units"))
    findings = []
    for name, feature in features.items():
        position_datums = feature.get("position_datums", [])
        angularity_datums = feature.get(
            "angularity_datums", "unknown" if "angularity_dia" in feature else []
        )
        angularity_unknown = angularity_datums == "unknown" or (
            "angularity_dia" in feature and angularity_datums == []
        )
        profile_datums = feature.get(
            "surface_profile_datums", "unknown" if "surface_profile" in feature else []
        )
        relationships = []
        if isinstance(position_datums, list):
            relationships.extend(
                (datum, datum_map.get(datum), feature.get("position_dia", "unknown"))
                for datum in position_datums
            )
        if isinstance(angularity_datums, list):
            band = feature.get("angularity_dia", "unknown")
            tolerance = (
                band[1] - band[0]
                if isinstance(band, list) and len(band) == 2 and all(_number(v) for v in band)
                else band
                if _number(band)
                else "unknown"
            )
            relationships.extend(
                (datum, datum_map.get(datum), tolerance) for datum in angularity_datums
            )
        if isinstance(profile_datums, list):
            zone = feature.get("surface_profile", "unknown")
            zone_mm = zone * scale if _number(zone) and scale else "unknown"
            relationships.extend((datum, datum_map.get(datum), zone_mm) for datum in profile_datums)
        if "coaxial_to" in feature:
            relationships.append(
                (
                    feature["coaxial_to"],
                    feature["coaxial_to"],
                    feature.get("coaxiality_dia", "unknown"),
                )
            )
        if "height_from" in feature:
            # The band measured from `height_from` is whichever height-like
            # requirement the feature declares; the first present one is it.
            key = next(
                (k for k in ("height_above_pivot", "height", "separation") if k in feature),
                None,
            )
            band, reason = requirement_band(bundle, name, key) if key else (None, None)
            tolerance = band[1] - band[0] if band else "unknown"
            if band and reason != "drawing band":
                tolerance = tolerance * scale if scale else "unknown"
            relationships.append((feature["height_from"], feature["height_from"], tolerance))
        numbers = {
            "position_datums": position_datums,
            "angularity_datums": angularity_datums,
        }
        if "surface_profile" in feature:
            numbers["surface_profile_datums"] = profile_datums
        if "datum" in feature:
            numbers["datum"] = feature["datum"]
        resolved = position_datums != "unknown" and not angularity_unknown
        resolved &= profile_datums != "unknown"
        if not relationships and resolved:
            findings.append(
                Finding(
                    "datum_consistency",
                    name,
                    "not_applicable",
                    numbers,
                    ["PLAN.md §4.1 datum consistency"],
                    "No tolerance on this feature refers to another datum.",
                )
            )
            continue
        feature_cuts = _cuts(bundle, name)
        numbers.update(
            {
                "feature_ops": [_label(cut) for cut in feature_cuts],
                "refixture_budget_mm": budget,
                "relationships": [],
                "datums": {},
            }
        )
        if feature_cuts:
            numbers["feature_op"] = _label(feature_cuts[-1])
        unknown = not resolved or not feature_cuts
        registered = bundle.plan.get("workpieces")
        if isinstance(registered, dict):
            unknown |= any(not _cuts(bundle, name, member) for member in registered)
        failed = []
        cross_setup = False
        for datum_name, datum_feature, tolerance in relationships:
            datum_cuts = _cuts(bundle, datum_feature)
            numbers["datums"][datum_name] = [_label(cut) for cut in datum_cuts]
            unknown |= any(
                operation_members(bundle, setup, op) is None for _, setup, op in datum_cuts
            )
            numbers["tolerance_mm"] = tolerance
            if "coaxial_to" in feature:
                numbers["coaxial_to"] = feature["coaxial_to"]
            if "height_from" in feature:
                numbers["from"] = feature["height_from"]
            if datum_cuts:
                numbers["datum_op"] = _label(datum_cuts[-1])
            if not datum_cuts:
                unknown = True
                continue
            for feature_cut in feature_cuts:
                members = operation_members(bundle, feature_cut[1], feature_cut[2])
                if members is None:
                    unknown = True
                    continue
                matching = []
                for member in members or (None,):
                    if member is not None and not any(
                        cut[2] is feature_cut[2] for cut in _cuts(bundle, name, member)
                    ):
                        continue
                    member_datums = _cuts(bundle, datum_feature, member)
                    if not member_datums:
                        unknown = True
                    matching.extend((member, cut) for cut in member_datums)
                for member, datum_cut in matching:
                    material = (
                        True
                        if member is None
                        else operation_material_status(
                            bundle,
                            feature_cut[1],
                            datum_cut[1],
                            datum_feature,
                            op=feature_cut[2],
                            producer_op=datum_cut[2],
                            workpiece_id=member,
                        )
                    )
                    if material is False:
                        unknown = True
                        continue
                    unknown |= material is None
                    same_setup = feature_cut[0] == datum_cut[0]
                    indicated = (
                        False
                        if same_setup
                        else _indicated(
                            setups,
                            feature_cut,
                            datum_cut,
                            datum_feature,
                            datum_name,
                            bundle=bundle,
                            workpiece_id=member,
                        )
                    )
                    cross_setup |= not same_setup
                    verdict = "unknown" if material is None else "pass"
                    if not same_setup and not indicated:
                        if not _number(tolerance) or not _number(budget):
                            unknown = True
                            verdict = "unknown"
                        elif tolerance < budget:
                            failed.append(datum_name)
                            verdict = "error"
                    numbers["relationships"].append(
                        {
                            "datum": datum_name,
                            "datum_feature": datum_feature,
                            **({"workpiece_id": member} if member is not None else {}),
                            "feature_op": _label(feature_cut),
                            "datum_op": _label(datum_cut),
                            "same_setup": same_setup,
                            "indicated_transfer": indicated,
                            "tolerance_mm": tolerance,
                            "status": verdict,
                        }
                    )
        numbers["same_setup"] = not cross_setup and bool(feature_cuts) and not unknown
        numbers["transfer"] = [
            _mapping(setup.get("zero")).get("transfer")
            for _, setup, _ in feature_cuts
            if _mapping(setup.get("zero")).get("transfer")
        ]
        status = "error" if failed else "unknown" if unknown else "pass"
        message = (
            (
                "Re-fixtured datum tolerance is below the measured shop budget: "
                + ", ".join(sorted(set(failed)))
                + "."
            )
            if failed
            else "Datum cuts or the re-fixture acceptance budget remain unresolved."
            if unknown
            else (
                "Datum relationships share a setup, have an indicated transfer, or fit the "
                "measured shop re-fixture budget."
            )
        )
        cite = [
            "PLAN.md §4.1 datum consistency",
            "features: datum references and tolerance",
            "plan: finishing cuts and zero.transfer",
        ]
        budget_cite = _mapping(bundle.policy.get("numbers_cite")).get("refixture_budget_mm")
        if isinstance(budget_cite, str) and budget_cite != "unknown":
            cite.append(budget_cite)
        findings.append(Finding("datum_consistency", name, status, numbers, cite, message))
    return findings
