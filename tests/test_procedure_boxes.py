"""One-time procedure boxes and the inventory schemas behind them: the EDGE FINDER box
and the purchased tooling receipt checks."""

import copy

import pytest
from pydantic import ValidationError
from test_tool_change_touch import DECK, bundle, mill_zero, op

from prechips.findings import is_required
from prechips.model import Inventory
from prechips.rules import purchased_tooling
from prechips.rules.zero_recipe import evaluate
from prechips.sheet import _Traveler

FINDER = {
    "kind": "edge_finder",
    "finder_type": "mechanical",
    "tip_in": 0.2,
    "rpm_range": [1000, 1200],
}


def mill_bundle(finder=FINDER, spindle=None, setups=1):
    """A mill setup zeroed in X and Y with ``finder``; ``setups`` copies of it."""
    data = bundle("mill", mill_zero(DECK), [op(10, "spot", "hole", "centre")])
    data.inventory["tools"]["finder"] = dict(finder)
    data.inventory["machines"]["mill"]["spindle"] = (
        {"rpm_min": 50, "rpm_max": 3000} if spindle is None else spindle
    )
    first = data.plan["setups"][0]
    data.plan["setups"] = [{**copy.deepcopy(first), "id": f"S{n + 1}"} for n in range(setups)]
    return data


def finder_row(data, setup=0, axis="x"):
    return evaluate(data)[setup].numbers["axes"][axis]


# ------------------------------------------------------------------ edge finder


def test_a_complete_edge_finder_gives_its_speed_band_inside_the_mill():
    finding = evaluate(mill_bundle())[0]
    assert finding.status == "pass"
    finder = finding.numbers["axes"]["x"]["finder"]
    assert finder["finder_type"] == "mechanical"
    assert finder["tip_dia_mm"] == pytest.approx(5.08)
    assert finder["radius_mm"] == pytest.approx(2.54)
    assert finder["rpm"] == [1000, 1200]
    # The mill's lower top speed clips the finder's band.
    clipped = finder_row(mill_bundle(spindle={"rpm_min": 50, "rpm_max": 1100}))
    assert clipped["finder"]["rpm"] == [1000, 1100]


@pytest.mark.parametrize("missing", ["finder_type", "rpm_range", "tip_in"])
def test_an_edge_finder_missing_a_field_leaves_the_zero_unknown(missing):
    finder = {key: value for key, value in FINDER.items() if key != missing}
    finding = evaluate(mill_bundle(finder))[0]
    assert finding.status == "unknown"
    assert missing.removesuffix("_in") in " ".join(
        finding.numbers["axes"]["x"]["finder"]["missing"]
    )


def test_an_unknown_mill_speed_range_leaves_the_finder_speed_unknown():
    finding = evaluate(mill_bundle(spindle={}))[0]
    assert finding.status == "unknown"
    assert finding.numbers["axes"]["x"]["finder"]["rpm"] == "unknown"


def test_a_finder_band_the_mill_cannot_turn_is_an_error():
    finding = evaluate(mill_bundle(spindle={"rpm_min": 50, "rpm_max": 900}))[0]
    assert finding.status == "error"
    assert "rpm" in finding.sentence


def test_an_electronic_finder_runs_with_the_spindle_stopped_and_needs_no_speed():
    finder = {"kind": "edge_finder", "finder_type": "electronic", "tip_in": 0.2}
    finding = evaluate(mill_bundle(finder, spindle={}))[0]
    assert finding.status == "pass"
    assert finding.numbers["axes"]["x"]["finder"]["rpm"] == "not_applicable"


def test_one_edge_finder_box_per_traveler_and_every_zero_points_to_it():
    data = mill_bundle(setups=2)
    findings = evaluate(data)
    sheet = _Traveler(data, findings, {}, {})
    first, second = (sheet.dro(setup, {}) for setup in data.plan["setups"])
    assert first.count("EDGE FINDER") >= 1 and second.count("<h3>EDGE FINDER") == 0
    assert "<h3>EDGE FINDER" in first
    box = first[first.index("<h3>EDGE FINDER") :]
    assert "1000–1200 rpm" in box
    assert "kick" in box
    # Half the tip Ø, signed by the side the finder comes from.
    assert "2.540" in box and "edge − 2.540" in box and "edge + 2.540" in box
    # Each X/Y row names the box; a later setup names where it is printed.
    assert first.count("EDGE FINDER box") == 2
    assert second.count("EDGE FINDER box, Setup S1 sheet 1") == 2


def test_the_edge_finder_box_stops_on_a_missing_field():
    finder = {key: value for key, value in FINDER.items() if key != "rpm_range"}
    data = mill_bundle(finder)
    html = _Traveler(data, evaluate(data), {}, {}).dro(data.plan["setups"][0], {})
    box = html[html.index("<h3>EDGE FINDER") :]
    assert "STOP" in box and "rpm" in box


# ------------------------------------------------------------- purchased tooling

KIT = {
    "name": "button kit",
    "kind": "filing_buttons",
    "purchase": "two hardened ground Ø14 g6 x 4 buttons bored 6.5 H7",
    "button_dia_limits_mm": [13.95, 14.03],
    "button_runout_mm": 0.01,
    "acceptance": [
        {"check": "each button OD", "gauge": "mic", "limits": "button_dia_limits_mm"},
        {
            "check": "each button OD runout",
            "gauge": "dti",
            "how": "button on the GO pin in a V-block, one turn",
            "limits": "button_runout_mm",
        },
        {"check": "stud thread", "gauge": "none", "accept": "the nut runs on by hand"},
    ],
}


def kit_bundle(kit=KIT, setups=1):
    data = bundle("mill", mill_zero(DECK), [op(10, "spot", "hole", "centre")])
    data.inventory["fixtures"] = {"kit": copy.deepcopy(kit)}
    data.inventory["gauges"] = {"mic": {"kind": "micrometer"}, "dti": {"kind": "dti"}}
    first = data.plan["setups"][0]
    first["hold"] = {"fixture": "vise", "clamps": [{"ref": "kit"}]}
    data.plan["setups"] = [{**copy.deepcopy(first), "id": f"S{n + 1}"} for n in range(setups)]
    return data


def test_purchased_tooling_receipt_checks_resolve_their_gauges_and_limits():
    [finding] = purchased_tooling.evaluate(kit_bundle())
    assert (finding.subject, finding.status) == ("S1", "pass")
    [item] = finding.numbers["items"]
    od, runout, thread = item["checks"]
    assert od["limits_mm"] == [13.95, 14.03]
    assert runout["max_mm"] == pytest.approx(0.01)
    assert thread["gauge"] == "none" and thread["accept"] == "the nut runs on by hand"


@pytest.mark.parametrize(
    ("change", "why"),
    [
        ({"gauge": "no-such-gauge"}, "gauge"),
        ({"gauge": "unknown"}, "gauge"),
        ({"limits": "button_bore_limits_mm"}, "limits"),
    ],
)
def test_an_unresolved_receipt_check_stops_the_setup(change, why):
    kit = copy.deepcopy(KIT)
    kit["acceptance"][0].update(change)
    [finding] = purchased_tooling.evaluate(kit_bundle(kit))
    assert finding.status == "unknown"
    assert why in finding.sentence


def test_an_item_without_acceptance_is_not_a_receipt_check():
    kit = {key: value for key, value in KIT.items() if key != "acceptance"}
    assert purchased_tooling.evaluate(kit_bundle(kit)) == []


def test_the_receipt_check_table_prints_once_where_the_item_is_first_used():
    data = kit_bundle(setups=2)
    sheet = _Traveler(data, purchased_tooling.evaluate(data), {}, {})
    first, second = (sheet.purchased_tooling(setup) for setup in data.plan["setups"])
    assert "<h3>PURCHASED TOOLING / RECEIPT CHECK" in first
    assert "13.950–14.030" in first and "≤ 0.010" in first
    assert "the nut runs on by hand" in first
    assert "two hardened ground" in first
    assert "<h3>" not in second and "13.950" not in second
    assert "RECEIPT CHECK table, Setup S1 sheet 1" in second


def test_the_receipt_check_table_stops_on_an_unresolved_gauge():
    kit = copy.deepcopy(KIT)
    kit["acceptance"][0]["gauge"] = "no-such-gauge"
    data = kit_bundle(kit)
    html = _Traveler(data, purchased_tooling.evaluate(data), {}, {}).purchased_tooling(
        data.plan["setups"][0]
    )
    assert "STOP" in html


def validate(items, category="fixtures"):
    return Inventory.model_validate({category: items})


@pytest.mark.parametrize(
    "row",
    [
        {"check": "OD", "gauge": "mic"},  # no limit and no criterion
        {"check": "OD", "gauge": "mic", "limits": "x_mm", "limits_mm": [1.0, 2.0]},
        {"check": "OD", "gauge": "none", "limits_mm": [1.0, 2.0]},  # a number needs a gauge
        {"check": "", "gauge": "mic", "accept": "fits"},
        {"check": "OD", "gauge": "mic", "limits_mm": [2.0, 1.0]},
    ],
)
def test_malformed_receipt_checks_are_rejected(row):
    with pytest.raises(ValidationError):
        validate({"kit": {"kind": "filing_buttons", "acceptance": [row]}})


def test_a_shop_made_item_has_no_receipt_check():
    row = {"check": "OD", "gauge": "mic", "limits_mm": [1.0, 2.0]}
    with pytest.raises(ValidationError):
        validate({"kit": {"kind": "filing_buttons", "shop_made": True, "acceptance": [row]}})


def test_an_unaccepted_receipt_check_stops_whatever_the_shop_policy_lists():
    kit = copy.deepcopy(KIT)
    kit["acceptance"][0]["gauge"] = "unknown"
    [finding] = purchased_tooling.evaluate(kit_bundle(kit))
    assert is_required(finding, {"required": {}})
