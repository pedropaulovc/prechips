"""Compare finishing setups to drawing datum cuts, never to frame names.

An indicated pickup must originate after the referenced datum's finishing cut;
indicating an earlier pilot does not establish a later reamed datum.
"""

from prechips.findings import Finding


_NONFINISH = {"spot", "inspect", "release", "fit_up", "scribe", "transfer", "deburr"}


def _mapping(value):
    return value if isinstance(value, dict) else {}


def _number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _cuts(setups, feature):
    cuts = []
    for index, setup in enumerate(setups):
        ops = [op for op in setup["ops"] if op.get("feature") == feature and op["do"] not in _NONFINISH and not op["do"].startswith("rough")]
        if any(op["do"] in ("ream", "tap", "bore") for op in ops):
            ops = [op for op in ops if op["do"] != "drill"]
        cuts.extend((index, setup, op) for op in ops)
    # A pilot is not the final datum when reaming happens in a later setup.
    if any(op["do"] in ("ream", "tap", "bore") for _, _, op in cuts):
        cuts = [(index, setup, op) for index, setup, op in cuts if op["do"] != "drill"]
    return cuts


def _label(cut):
    return f"{cut[1]['id']}:{cut[2]['op']}"


def _indicated(setups, feature_cut, datum_cut, datum_feature, datum_name):
    _, setup, _ = feature_cut
    transfer = _mapping(_mapping(setup.get("zero")).get("transfer"))
    selected = transfer.get("indicate", [])
    if isinstance(selected, str):
        selected = [selected]
    if datum_feature not in selected and datum_name not in selected:
        return False
    source = transfer.get("from")
    source_index = next((index for index, item in enumerate(setups) if item["id"] == source), None)
    # Pickup from an earlier intermediate cannot prove the finished datum.
    return source_index is not None and datum_cut[0] <= source_index < feature_cut[0]


def evaluate(bundle):
    setups = bundle.plan["setups"]
    features = bundle.features["features"]
    datum_map = {name: _mapping(datum).get("feature") for name, datum in _mapping(bundle.features.get("datums")).items()}
    datum_map.update({feature["datum"]: name for name, feature in features.items() if isinstance(feature.get("datum"), str) and feature["datum"] != "unknown"})
    budget = _mapping(bundle.policy.get("numbers")).get("refixture_budget_mm", "unknown")
    verified = bundle.policy.get("numbers_verify", False)
    if isinstance(verified, dict):
        verified = verified.get("refixture_budget_mm", False)
    if verified:
        budget = "unknown"
    findings = []
    for name, feature in features.items():
        position_datums = feature.get("position_datums", [])
        relationships = []
        if isinstance(position_datums, list):
            relationships.extend((datum, datum_map.get(datum), feature.get("position_dia", "unknown")) for datum in position_datums)
        if "coaxial_to" in feature:
            relationships.append((feature["coaxial_to"], feature["coaxial_to"], feature.get("coaxiality_dia", "unknown")))
        if "height_from" in feature:
            band = feature.get("height_above_pivot", "unknown")
            tolerance = band[1] - band[0] if isinstance(band, list) and len(band) == 2 and all(_number(v) for v in band) else "unknown"
            relationships.append((feature["height_from"], feature["height_from"], tolerance))
        numbers = {"position_datums": position_datums}
        if "datum" in feature:
            numbers["datum"] = feature["datum"]
        if not relationships and position_datums != "unknown":
            findings.append(Finding("datum_consistency", name, "not_applicable", numbers, ["PLAN.md §4.1 datum consistency"], "No tolerance on this feature refers to another datum."))
            continue
        feature_cuts = _cuts(setups, name)
        numbers.update({"feature_ops": [_label(cut) for cut in feature_cuts], "refixture_budget_mm": budget, "relationships": [], "datums": {}})
        if feature_cuts:
            numbers["feature_op"] = _label(feature_cuts[-1])
        unknown = position_datums == "unknown" or not feature_cuts
        failed = []
        cross_setup = False
        for datum_name, datum_feature, tolerance in relationships:
            datum_cuts = _cuts(setups, datum_feature)
            numbers["datums"][datum_name] = [_label(cut) for cut in datum_cuts]
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
                for datum_cut in datum_cuts:
                    same_setup = feature_cut[0] == datum_cut[0]
                    indicated = False if same_setup else _indicated(setups, feature_cut, datum_cut, datum_feature, datum_name)
                    cross_setup |= not same_setup
                    verdict = "pass"
                    if not same_setup and not indicated:
                        if not _number(tolerance) or not _number(budget):
                            unknown = True
                            verdict = "unknown"
                        elif tolerance < budget:
                            failed.append(datum_name)
                            verdict = "error"
                    numbers["relationships"].append({"datum": datum_name, "datum_feature": datum_feature,
                                                       "feature_op": _label(feature_cut), "datum_op": _label(datum_cut),
                                                       "same_setup": same_setup, "indicated_transfer": indicated,
                                                       "tolerance_mm": tolerance, "status": verdict})
        numbers["same_setup"] = not cross_setup and bool(feature_cuts) and not unknown
        numbers["transfer"] = [
            _mapping(setup.get("zero")).get("transfer")
            for _, setup, _ in feature_cuts
            if _mapping(setup.get("zero")).get("transfer")
        ]
        status = "error" if failed else "unknown" if unknown else "pass"
        message = ("Re-fixtured datum tolerance is below the measured shop budget: " + ", ".join(sorted(set(failed))) + ".") if failed else "Datum cuts or the re-fixture acceptance budget remain unresolved." if unknown else "Datum relationships share a setup, have an indicated transfer, or fit the measured shop re-fixture budget."
        cite = ["PLAN.md §4.1 datum consistency", "features: datum references and tolerance", "plan: finishing cuts and zero.transfer"]
        budget_cite = _mapping(bundle.policy.get("numbers_cite")).get("refixture_budget_mm")
        if isinstance(budget_cite, str) and budget_cite != "unknown":
            cite.append(budget_cite)
        findings.append(Finding("datum_consistency", name, status, numbers, cite, message))
    return findings
