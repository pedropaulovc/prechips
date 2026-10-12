"""Chain drilling is axial drilling, not end-mill profiling or plunging."""

import pytest
from test_deep_hole_speed import drill_bundle

from prechips.rules import speeds_feeds
from prechips.sheet import _Traveler


def chain_bundle(diameter=6.35):
    data = drill_bundle(deep=(), action="rough_profile")
    op = data.plan["setups"][0]["ops"][0]
    op["contour"] = {"method": "chain_drill", "pitch_mm": 4.0}
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
    assert feed.startswith("axial ") and feed.endswith(" mm/min")
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


def test_example_validator_checks_drilling_action_and_rejects_profile_claim():
    from test_validate_examples import VALIDATOR

    data = chain_bundle()
    setup = data.plan["setups"][0]
    [finding] = speeds_feeds.evaluate(data)
    row = finding.to_dict()
    args = (
        data.plan,
        data.features,
        setup,
        setup["ops"][0],
        row,
        VALIDATOR["Entries"](data.inventory),
        data.cutting_data,
        data.feature_definitions,
        {},
    )
    VALIDATOR["check_speeds"](*args)
    row["numbers"]["operation"] = "profile"
    with pytest.raises(ValueError):
        VALIDATOR["check_speeds"](*args)


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
