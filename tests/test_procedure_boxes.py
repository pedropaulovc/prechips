"""One-time procedure boxes and the inventory schemas behind them: the EDGE FINDER box
and the purchased tooling receipt checks."""

import copy
import re

import pytest
from pydantic import ValidationError
from test_sheet_ops import Markup, content
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
    assert finder["rpm"] == [[1000, 1200]]
    # The mill's lower top speed clips the finder's band.
    clipped = finder_row(mill_bundle(spindle={"rpm_min": 50, "rpm_max": 1100}))
    assert clipped["finder"]["rpm"] == [[1000, 1100]]


def test_a_finder_band_across_a_gap_between_spindle_ranges_runs_only_where_it_turns():
    gapped = {"ranges_rpm": [[50, 900], [1500, 3000]]}
    finding = evaluate(mill_bundle(spindle=gapped))[0]
    # 1000-1200 falls in the gap: no range turns it.
    assert finding.status == "error"
    wide = {**FINDER, "rpm_range": [800, 1600]}
    finder = finder_row(mill_bundle(wide, spindle=gapped))["finder"]
    assert finder["rpm"] == [[800, 900], [1500, 1600]]
    data = mill_bundle(wide, spindle=gapped)
    html = _Traveler(data, evaluate(data), {}, {}).dro(data.plan["setups"][0], {})
    box = html[html.index("<h3>EDGE FINDER") :]
    assert "800–900 or 1500–1600 rpm" in box and "1000" not in box


@pytest.mark.parametrize(
    ("finder", "spindle"),
    [
        ({**FINDER, "rpm_range": ["unknown", 1200]}, None),
        ({**FINDER, "rpm_range": [1000, "unknown"]}, None),
        (FINDER, {"rpm_min": 50, "rpm_max": "unknown"}),
        (FINDER, {"ranges_rpm": [[50, 900], [1000, "unknown"]]}),
        (FINDER, {"ranges_rpm": "unknown"}),
    ],
)
def test_a_partly_unknown_speed_band_leaves_the_finder_speed_unknown(finder, spindle):
    data = mill_bundle(finder, spindle=spindle)
    finding = evaluate(data)[0]
    assert finding.status == "unknown"
    assert finding.numbers["axes"]["x"]["finder"]["rpm"] == "unknown"
    html = _Traveler(data, [finding], {}, {}).dro(data.plan["setups"][0], {})
    assert "STOP" in html[html.index("<h3>EDGE FINDER") :]


def test_each_mill_gets_the_finder_speed_it_can_turn():
    data = mill_bundle({**FINDER, "rpm_range": [750, 1500]}, setups=2)
    data.inventory["machines"]["mill"]["spindle"] = {"rpm_min": 50, "rpm_max": 900}
    data.inventory["machines"]["fast"] = {
        "kind": "mill",
        "spindle": {"rpm_min": 1200, "rpm_max": 3000},
    }
    data.plan["setups"][1]["machine"] = "fast"
    findings = evaluate(data)
    sheet = _Traveler(data, findings, {}, {})
    first, second = (sheet.dro(setup, {}) for setup in data.plan["setups"])
    assert "750–900 rpm" in first[first.index("<h3>EDGE FINDER") :]
    # The second mill's speed is never the first mill's box.
    box = second[second.index("<h3>EDGE FINDER") :]
    assert "1200–1500 rpm" in box and "750–900" not in second
    assert "Setup S1 sheet 1" not in second


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
    assert first.count("<h3>EDGE FINDER") == 1
    assert second.count("<h3>EDGE FINDER") == 0
    box = first[first.index("<h3>EDGE FINDER") :]
    assert "1000–1200 rpm" in box
    assert "kick" in box
    # Half the tip Ø, signed by the side the finder comes from.
    assert "2.540" in box and "edge − 2.540" in box and "edge + 2.540" in box
    # Each X/Y row names the box; a later setup names where it is printed.
    assert first.count("EDGE FINDER box") == 2
    assert second.count("EDGE FINDER box, Setup S1 sheet 1") == 2


# The finder and the mill are the items they select: a setup spelling them ``tools.finder``
# and ``machines.mill`` (or one axis spelling the finder so) reuses the one box, and the
# mill's DRO grid prints once.
def test_one_edge_finder_box_however_setups_spell_the_finder_or_the_mill():
    data = mill_bundle(setups=2)
    first, second = data.plan["setups"]
    first["zero"]["y"]["tool"] = "tools." + first["zero"]["y"]["tool"]
    second["machine"] = "machines." + second["machine"]
    for axis in ("x", "y"):
        second["zero"][axis]["tool"] = "tools." + second["zero"][axis]["tool"]
    sheet = _Traveler(data, evaluate(data), {}, {})
    one, two = (sheet.dro(setup, {}) for setup in data.plan["setups"])
    assert one.count("<h3>EDGE FINDER") == 1 and two.count("<h3>EDGE FINDER") == 0
    assert one.count("EDGE FINDER box") == 2
    assert two.count("EDGE FINDER box, Setup S1 sheet 1") == 2
    assert sheet.dro_resolution(data.plan["setups"]).count("default grid") == 1


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
    markup = Markup(html)
    (row,) = [
        node
        for node in markup.nodes
        if node["tag"] == "tr"
        and any(
            cell["tag"] == "td"
            and cell["parent"] is node
            and content(cell).strip() == "each button OD"
            for cell in markup.nodes
        )
    ]
    cells = [
        content(cell) for cell in markup.nodes if cell["tag"] == "td" and cell["parent"] is row
    ]
    assert len(cells) == 3
    assert "?" in cells[1] and "no-such-gauge" in cells[1]
    assert "STOP" in cells[2] and "gauge" in cells[2] and "no-such-gauge" in cells[2]


def receipt_html(data):
    findings = purchased_tooling.evaluate(data)
    return findings, _Traveler(data, findings, {}, {}).purchased_tooling(data.plan["setups"][0])


@pytest.mark.parametrize(
    "change",
    [
        {"limits_mm": ["unknown", 14.03]},
        {"limits_mm": [13.95, "unknown"]},
        {"limits_mm": "unknown"},
        {"limits": "unknown"},
        {"check": "unknown"},
        {"how": "unknown"},
    ],
)
def test_an_unknown_receipt_criterion_stops_instead_of_accepting(change):
    kit = copy.deepcopy(KIT)
    row = kit["acceptance"][0]
    row.pop("limits")
    row.update({"limits_mm": [13.95, 14.03], **change})
    if "limits" in change:
        row.pop("limits_mm")
    [finding], html = receipt_html(kit_bundle(kit))
    assert finding.status == "unknown"
    assert "STOP" in html


@pytest.mark.parametrize("accept", ["unknown", "", "   "])
def test_an_unknown_hand_criterion_stops_instead_of_accepting(accept):
    kit = copy.deepcopy(KIT)
    kit["acceptance"][2]["accept"] = accept
    [finding], html = receipt_html(kit_bundle(kit))
    assert finding.status == "unknown"
    assert "STOP" in html


@pytest.mark.parametrize("field", ["acceptance", "purchase"])
def test_an_explicitly_unknown_receipt_declaration_stops(field):
    kit = {**copy.deepcopy(KIT), field: "unknown"}
    [finding], html = receipt_html(kit_bundle(kit))
    assert finding.status == "unknown"
    assert is_required(finding, {"required": {}})
    assert "STOP" in html


@pytest.mark.parametrize(
    ("use", "category"),
    [
        ({"hold": {"fixture": "vise", "jaw_buttons": "kit"}}, "fixtures"),
        ({"hold": {"fixture": "vise", "jaw_bar": "kit"}}, "fixtures"),
        ({"hold": {"fixture": "vise", "parallels": "kit"}}, "fixtures"),
        ({"hold": {"fixture": "kit"}}, "fixtures"),
        ({"hold": {"fixture": "kit"}}, "holders"),
        ({"hold": {"fixture": "lathe-chuck", "chuck": "kit"}}, "fixtures"),
        ({"hold": {"fixture": "vise", "support": "kit"}}, "fixtures"),
        ({"hold": {"fixture": "vise", "riser": "kit"}}, "fixtures"),
        ({"hold": {"fixture": "vise", "stop_fixture": "kit"}}, "fixtures"),
        ({"hold": {"fixture": "vise", "align": {"indicator": "kit"}}}, "gauges"),
        ({"zero": {"x": {"tool": "kit"}}}, "tools"),
        ({"zero": {"x": {"tool": "kit"}}}, "gauges"),
        ({"zero": {"x": {"gauge": "kit"}}}, "gauges"),
        ({"zero": {"transfer": {"gauge": "kit"}}}, "gauges"),
        ({"zero": {"transfer": {"tool": "kit"}}}, "gauges"),
        ({"zero": {"tool_touches": [{"tool": "centre", "z_gauge": "kit"}]}}, "gauges"),
        ({"ops": [{"op": 10, "tool": "centre", "holder": "kit"}]}, "holders"),
        ({"ops": [{"op": 10, "tool": "centre", "checks": {"dia": "kit"}}]}, "gauges"),
        ({"ops": [{"op": 10, "tool": "centre", "guide": {"gauge": "kit"}}]}, "gauges"),
        ({"ops": [{"op": 10, "tool": "centre", "process_holds": [{"gauge": "kit"}]}]}, "gauges"),
    ],
)
def test_every_slot_a_setup_uses_an_item_in_reads_its_receipt_checks(use, category):
    """The kit is listed in a category the slot reads (docs/inventory.md, Identity)."""
    data = kit_bundle()
    kit = data.inventory["fixtures"].pop("kit")
    data.inventory.setdefault(category, {})["kit"] = kit
    setup = data.plan["setups"][0]
    setup["hold"] = {"fixture": "vise"}
    assert purchased_tooling.evaluate(data) == []
    setup.update(copy.deepcopy(use))
    [finding] = purchased_tooling.evaluate(data)
    assert finding.numbers["items"][0]["ref"] == "kit"
    assert finding.numbers["items"][0]["category"] == category


def test_metric_receipt_limits_round_inward():
    kit = copy.deepcopy(KIT)
    kit["button_dia_limits_mm"] = [13.9504, 14.0296]
    kit["button_runout_mm"] = 0.0104
    _, html = receipt_html(kit_bundle(kit))
    assert "13.951–14.029 mm" in html and "≤ 0.010 mm" in html


def printed_band(html, unit):
    """Every ``lo–hi unit`` band the receipt table prints, as numbers."""
    return [
        (float(lo), float(hi)) for lo, hi in re.findall(rf"(\d+\.\d+)–(\d+\.\d+) {unit}\b", html)
    ]


@pytest.mark.parametrize(
    ("band", "most"),
    [([13.9504, 13.9506], 0.0004), ([13.95, 13.95], 0.00001), ([6.4999, 6.5001], 0.0104)],
)
def test_a_narrow_receipt_band_never_prints_reversed_or_wider(band, most):
    kit = copy.deepcopy(KIT)
    kit["button_dia_limits_mm"] = band
    kit["button_runout_mm"] = most
    data = kit_bundle(kit)
    data.inventory["gauges"]["mic"] = {"kind": "micrometer", "range_in": [0, 1]}
    _, html = receipt_html(data)
    [(lo, hi)] = printed_band(html, "mm")
    assert band[0] <= lo <= hi <= band[1]
    # An inch band prints for an inch gauge unless no inch decimals fit inside the band.
    inches = printed_band(html, "in")
    assert len(inches) == (band[0] < band[1])
    for lo_in, hi_in in inches:
        assert band[0] / 25.4 <= lo_in <= hi_in <= band[1] / 25.4
    [cap] = [float(v) for v in re.findall(r"≤ (\d+\.\d+) mm", html)]
    assert 0 < cap <= most


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
    item = {"kind": "filing_buttons", "acceptance": [KIT["acceptance"][0]]}
    validate({"kit": item})
    with pytest.raises(ValidationError) as rejected:
        validate({"kit": {**item, "acceptance": [row]}})
    errors = rejected.value.errors()
    assert len(errors) == 1
    assert errors[0]["type"] == "value_error"
    assert str(errors[0]["ctx"]["error"]).startswith("fixtures.kit.acceptance[0]:")


def test_a_shop_made_item_has_no_receipt_check():
    row = {"check": "OD", "gauge": "mic", "limits_mm": [1.0, 2.0]}
    item = {"kind": "filing_buttons", "shop_made": True}
    validate({"kit": item})
    with pytest.raises(ValidationError) as rejected:
        validate({"kit": {**item, "acceptance": [row]}})
    errors = rejected.value.errors()
    assert len(errors) == 1
    assert errors[0]["type"] == "value_error"
    error = str(errors[0]["ctx"]["error"])
    assert error.startswith("fixtures.kit:") and "acceptance" in error


def test_an_unaccepted_receipt_check_stops_whatever_the_shop_policy_lists():
    kit = copy.deepcopy(KIT)
    kit["acceptance"][0]["gauge"] = "unknown"
    [finding] = purchased_tooling.evaluate(kit_bundle(kit))
    assert is_required(finding, {"required": {}})
