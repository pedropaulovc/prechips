"""Chain drilling is axial drilling, not end-mill profiling or plunging."""

import pytest
from test_deep_hole_speed import drill_bundle

from prechips.rules import speeds_feeds
from prechips.sheet import _Box, _Traveler


def chain_bundle(diameter=6.35):
    data = drill_bundle(action="rough_profile")
    op = data.plan["setups"][0]["ops"][0]
    op["contour"] = {"method": "chain_drill", "pitch_mm": 4.0}
    op["to_z"] = -5.0
    data.inventory["tools"]["drill"]["dia_mm"] = diameter
    data.cutting_data["cut"] = [
        {
            "material_class": "low_carbon_steel",
            "tool_material": "HSS",
            "operation": action,
            "diameter_range": [0.5, 13.0],
            "sfm": sfm,
            "chip_load_mm_per_tooth": chip,
            "cite": cite,
        }
        for action, sfm, chip, cite in (
            ("drill", 60.0, 0.0127, "drilling source"),
            ("profile", 65.0, 0.0254, "end-mill source"),
        )
    ]
    data.cutting_data["plunge"] = [
        {
            "material_class": "low_carbon_steel",
            "tool_material": "HSS",
            "diameter_range": [0.5, 13.0],
            "feed_mm_rev": 0.5,
            "cite": "end-mill plunge source",
        }
    ]
    return data


@pytest.mark.parametrize("diameter", [2.87, 3.454, 6.35])
def test_chain_drill_selects_drill_row_not_matching_endmill_row(diameter):
    data = chain_bundle(diameter)
    [finding] = speeds_feeds.evaluate(data)
    n = finding.numbers
    assert finding.status == "pass"
    assert n["operation"] == "drill"
    assert n["cutting_data_row"] == "drilling source"
    assert n["sfm"] == 60.0
    assert n["chip_load_mm_per_tooth"] == 0.0127
    assert n["feed_mm_min"] == pytest.approx(n["rpm"] * 2 * 0.0127)
    assert n["plunge_mm_rev"] == pytest.approx(0.0254)
    assert n["plunge_mm_min"] == n["feed_mm_min"]
    assert "end-mill plunge source" not in finding.cite
    setup = data.plan["setups"][0]
    _, feed, stop = _Traveler(data, [finding], {}, None).speeds(setup, setup["ops"][0], False)
    assert feed.startswith("axial ") and feed.endswith(" (0.025 mm/rev)")
    assert not stop


@pytest.mark.parametrize("fault", ["missing", "ambiguous", "uncited", "unverified"])
def test_drill_data_debt_never_falls_back_to_profile_or_plunge(fault):
    data = chain_bundle()
    rows = data.cutting_data["cut"]
    if fault == "missing":
        rows.pop(0)
    elif fault == "ambiguous":
        rows.append(dict(rows[0]))
    elif fault == "uncited":
        rows[0]["cite"] = "unknown"
    else:
        rows[0]["verify"] = True
    [finding] = speeds_feeds.evaluate(data)
    assert finding.status == "unknown"
    assert finding.numbers["plunge_mm_rev"] == "unknown"
    assert finding.numbers["cutting_data_row"] != "end-mill source"


def test_cited_drill_chart_still_governs_speed_and_axial_entry():
    data = chain_bundle()
    tool = data.inventory["tools"]["drill"]
    tool.update(chart="own drill chart", sfm=50.0, chip_load_mm_per_tooth=0.01)
    [finding] = speeds_feeds.evaluate(data)
    assert finding.numbers["operation"] == "drill"
    assert finding.numbers["cutting_data_row"] == "own drill chart"
    assert finding.numbers["plunge_mm_rev"] == 0.02


@pytest.mark.parametrize("method,kind", [("stairs", "drill"), ("chain_drill", "endmill")])
def test_tool_kind_alone_or_contour_method_alone_does_not_change_action(method, kind):
    data = chain_bundle()
    data.plan["setups"][0]["ops"][0]["contour"]["method"] = method
    data.inventory["tools"]["drill"]["kind"] = kind
    [finding] = speeds_feeds.evaluate(data)
    assert finding.numbers["operation"] == "profile"
    assert finding.numbers["cutting_data_row"] == "end-mill source"
    assert "feed_direction" not in finding.numbers
    assert finding.numbers["plunge_mm_rev"] == "unknown"


def check_speed_oracle(data, row):
    from test_validate_examples import VALIDATOR, validator_test_bundle

    entries = VALIDATOR["Entries"](data.inventory)
    depths = VALIDATOR["check_endpoints"](validator_test_bundle(data), {}, entries)
    setup = data.plan["setups"][0]
    VALIDATOR["check_speeds"](
        data.plan,
        data.features,
        setup,
        setup["ops"][0],
        row,
        entries,
        data.cutting_data,
        data.feature_definitions,
        depths,
    )


def test_example_validator_checks_drilling_action_and_rejects_profile_claim():
    data = chain_bundle()
    [finding] = speeds_feeds.evaluate(data)
    row = finding.to_dict()
    check_speed_oracle(data, row)
    row["numbers"]["operation"] = "profile"
    with pytest.raises(ValueError):
        check_speed_oracle(data, row)


@pytest.mark.parametrize("kind", ["drill_index", "drill_set"])
def test_chain_drill_resolves_family_members_as_drills(kind):
    data = chain_bundle()
    drill = data.inventory["tools"].pop("drill")
    data.inventory["tools"]["index"] = {
        "kind": kind,
        "material": "HSS",
        "members": {"selected": drill},
    }
    # The member inherits its family kind, as the trial's #29 and #33 do.
    del drill["kind"]
    data.plan["setups"][0]["ops"][0]["tool"] = "index/selected"
    [finding] = speeds_feeds.evaluate(data)
    assert finding.status == "pass"
    assert finding.numbers["operation"] == "drill"
    assert finding.numbers["cutting_data_row"] == "drilling source"
    assert finding.numbers["plunge_mm_rev"] == pytest.approx(0.0254)
    check_speed_oracle(data, finding.to_dict())


@pytest.mark.parametrize(
    "depth,rpm,derate", [(5.0, 900, "not_applicable"), (20.0, 450, "deep row")]
)
def test_chain_drill_material_depth_drives_deep_hole_derate(depth, rpm, derate):
    data = chain_bundle()
    data.plan["setups"][0]["ops"][0]["to_z"] = -depth
    [finding] = speeds_feeds.evaluate(data)
    assert finding.status == "pass"
    assert finding.numbers["depth_over_dia"] == pytest.approx(depth / 6.35)
    assert finding.numbers["deep_hole_row"] == derate
    assert finding.numbers["rpm"] == rpm
    assert finding.numbers["feed_mm_min"] == pytest.approx(rpm * 0.0254)
    check_speed_oracle(data, finding.to_dict())


@pytest.mark.parametrize("flutes", [None, 0, -2, "unknown"])
def test_missing_or_nonpositive_drill_flutes_leave_axial_feed_unknown(flutes):
    data = chain_bundle()
    data.inventory["tools"]["drill"]["flutes"] = flutes
    [finding] = speeds_feeds.evaluate(data)
    assert finding.status == "unknown"
    assert finding.numbers["feed_mm_min"] == "unknown"
    assert finding.numbers["plunge_mm_rev"] == "unknown"
    setup = data.plan["setups"][0]
    _, feed, stop = _Traveler(data, [finding], {}, None).speeds(setup, setup["ops"][0], False)
    assert isinstance(feed, _Box)
    assert (feed.source, feed.status, feed.scope, feed.kind) == (
        "speeds_feeds",
        "unknown",
        f"{setup['id']}:{setup['ops'][0]['op']}",
        "block",
    )
    assert stop


def test_uncertain_drill_chart_leaves_plunge_unresolved():
    data = chain_bundle()
    data.inventory["tools"]["drill"].update(
        chart="own drill chart", sfm=50.0, chip_load_mm_per_tooth=0.01, verify=True
    )
    [finding] = speeds_feeds.evaluate(data)
    assert finding.status == "unknown"
    assert finding.numbers["plunge_mm_rev"] == "unknown"


def test_stairs_with_declared_centre_cutting_keeps_profile_plunge_semantics():
    data = chain_bundle()
    data.plan["setups"][0]["ops"][0]["contour"]["method"] = "stairs"
    data.inventory["tools"]["drill"]["center_cutting"] = True
    [finding] = speeds_feeds.evaluate(data)
    assert finding.numbers["operation"] == "profile"
    assert finding.numbers["plunge_mm_rev"] == 0.5
    assert "end-mill plunge source" in finding.cite


def test_plain_drill_card_prints_axial_speed_and_feed_per_revolution():
    data = drill_bundle(depth_mm=5.0)
    [finding] = speeds_feeds.evaluate(data)
    setup = data.plan["setups"][0]
    _, feed, stop = _Traveler(data, [finding], {}, None).speeds(setup, setup["ops"][0], False)
    assert feed == "axial 155 mm/min (0.100 mm/rev)"
    assert not stop


def test_chain_drill_uses_its_entry_plane_and_manifest_units_not_approach_air():
    data = chain_bundle()
    data.features["units"] = "in"
    setup = data.plan["setups"][0]
    setup["stock_state"]["top_z"] = 2.0
    setup["stock_state"]["entry_z"] = {"hole": 1.0}
    setup["ops"][0].update(to_z=0.5, approach_mm=100.0)
    [finding] = speeds_feeds.evaluate(data)
    assert finding.status == "pass"
    assert finding.numbers["depth_over_dia"] == 2.0
    assert finding.numbers["deep_hole_row"] == "not_applicable"
    check_speed_oracle(data, finding.to_dict())


def test_preceding_chain_drill_does_not_lower_next_chain_start():
    data = chain_bundle()
    setup = data.plan["setups"][0]
    setup["ops"][0]["to_z"] = -20.0
    setup["ops"].append({**setup["ops"][0], "op": 20})
    findings = speeds_feeds.evaluate(data)
    assert [row.status for row in findings] == ["pass", "pass"]
    assert [row.numbers["depth_over_dia"] for row in findings] == pytest.approx(
        [20.0 / 6.35, 20.0 / 6.35]
    )


@pytest.mark.parametrize("start,end", [("unknown", -5.0), (0.0, "unknown"), (0.0, 1.0)])
def test_unknown_or_noncutting_chain_depth_stays_unresolved(start, end):
    data = chain_bundle()
    setup = data.plan["setups"][0]
    setup["stock_state"]["top_z"] = start
    setup["ops"][0]["to_z"] = end
    [finding] = speeds_feeds.evaluate(data)
    assert finding.status == "unknown"
    assert finding.numbers["depth_over_dia"] == "unknown"
    _, feed, stop = _Traveler(data, [finding], {}, None).speeds(setup, setup["ops"][0], False)
    assert isinstance(feed, _Box)
    assert (feed.source, feed.status, feed.scope, feed.kind) == (
        "speeds_feeds",
        "unknown",
        f"{setup['id']}:{setup['ops'][0]['op']}",
        "block",
    )
    assert stop


@pytest.mark.parametrize("field", ["feed_direction", "axial_feed_mm_rev"])
@pytest.mark.parametrize("corruption", ["missing", "wrong"])
def test_independent_oracle_rejects_incorrect_chain_axial_feed_evidence(field, corruption):
    data = chain_bundle()
    [finding] = speeds_feeds.evaluate(data)
    row = finding.to_dict()
    check_speed_oracle(data, row)
    if corruption == "missing":
        del row["numbers"][field]
    else:
        row["numbers"][field] = "table" if field == "feed_direction" else 0.0127
    with pytest.raises(ValueError):
        check_speed_oracle(data, row)


def test_independent_oracle_checks_plain_drill_per_revolution_feed():
    from test_validate_examples import speed_finding

    row, check = speed_finding(drill_bundle(depth_mm=5.0))
    check()
    row["numbers"]["axial_feed_mm_rev"] *= 2
    with pytest.raises(ValueError):
        check()


def test_lathe_tailstock_drill_uses_planned_axial_feed_not_row_or_tooth_feed():
    from test_validate_examples import speed_finding

    data = drill_bundle(depth_mm=5.0)
    data.inventory["machines"]["mill"]["kind"] = "lathe"
    data.plan["setups"][0]["ops"][0]["feed_mm_rev"] = 0.03
    data.cutting_data["cut"][0]["feed_mm_rev"] = 0.08
    row, check = speed_finding(data)
    assert row["status"] == "pass"
    assert row["numbers"]["feed_direction"] == "axial"
    assert row["numbers"]["feed_mm_rev"] == 0.03
    assert row["numbers"]["axial_feed_mm_rev"] == 0.03
    assert row["numbers"]["feed_mm_min"] == pytest.approx(row["numbers"]["rpm"] * 0.03)
    check()
    row["numbers"]["axial_feed_mm_rev"] = 0.08
    with pytest.raises(ValueError):
        check()
