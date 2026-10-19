"""Note-only bench handling waives holding geometry, never process identity."""

import pytest
from test_geometry_rules import rules_bundle

from prechips.findings import Finding
from prechips.rules import (
    fixture_interference,
    stock_diameter,
    thin_wall_under_clamp,
    tool_resolves,
    vise,
)
from prechips.sheet import _Traveler

SCREENS = [fixture_interference, stock_diameter, thin_wall_under_clamp, vise]
NO_KERNEL = {"status": "unknown", "kernel_unavailable": True, "reason": "FreeCAD unavailable"}


def handling_bundle(tmp_path, actions=("inspect", "coating"), kind="bench"):
    data = rules_bundle(tmp_path)
    data.inventory["machines"]["mill"]["kind"] = kind
    setup = data.plan["setups"][0]
    setup["hold"] = {"note": "Support on a clean pad and turn by hand"}
    setup["ops"] = [
        {"op": 10 * (index + 1), "do": action, "feature": "pocket"}
        for index, action in enumerate(actions)
    ]
    return data


@pytest.mark.parametrize("screen", SCREENS)
@pytest.mark.parametrize("kind", ["bench", "manual"])
@pytest.mark.parametrize("actions", [("inspect",), ("coating",), ("inspect", "coating")])
def test_note_only_handling_is_na_even_without_geometry(tmp_path, screen, kind, actions):
    data = handling_bundle(tmp_path, actions, kind)
    data.kernel = dict(NO_KERNEL)
    (row,) = screen.evaluate(data)
    assert row.status == "not_applicable"
    assert row.numbers["machine_kind"] == kind
    assert [entry["do"] for entry in row.numbers["operations"]] == list(actions)
    assert row.numbers.get("kernel_unavailable") is not True


@pytest.mark.parametrize("screen", SCREENS)
@pytest.mark.parametrize("kind", ["unknown", "mill"])
def test_unestablished_bench_machine_keeps_holding_debt(tmp_path, screen, kind):
    data = handling_bundle(tmp_path, kind=kind)
    data.kernel = dict(NO_KERNEL)
    assert screen.evaluate(data)[0].status == "unknown"


@pytest.mark.parametrize("screen", SCREENS)
@pytest.mark.parametrize(
    "actions",
    [
        ("unknown",),
        (),
        ("inspect", "unknown"),
        ("fit",),
        ("deburr",),
        ("scribe",),
        ("file_to_line",),
        ("saw_cut",),
    ],
)
def test_mechanical_or_unestablished_actions_keep_holding_debt(tmp_path, screen, actions):
    data = handling_bundle(tmp_path, actions)
    data.kernel = dict(NO_KERNEL)
    assert screen.evaluate(data)[0].status == "unknown"


@pytest.mark.parametrize("screen", SCREENS)
@pytest.mark.parametrize("field", ["fixture", "clamp", "grip_mm", "supports", "kind"])
def test_declared_unknown_holding_fact_is_not_absence(tmp_path, screen, field):
    data = handling_bundle(tmp_path)
    data.plan["setups"][0]["hold"][field] = "unknown"
    data.kernel = dict(NO_KERNEL)
    assert screen.evaluate(data)[0].status == "unknown"


@pytest.mark.parametrize("screen", SCREENS)
def test_unknown_hold_as_a_whole_is_not_unfixtured_handling(tmp_path, screen):
    data = handling_bundle(tmp_path)
    data.plan["setups"][0]["hold"] = "unknown"
    data.kernel = dict(NO_KERNEL)
    assert screen.evaluate(data)[0].status == "unknown"


@pytest.mark.parametrize("screen", SCREENS)
def test_known_fixture_contradictions_survive_bench_handling(tmp_path, screen):
    data = rules_bundle(tmp_path)
    data.inventory["machines"]["mill"]["kind"] = "bench"
    setup = data.plan["setups"][0]
    setup["ops"] = [{"op": 10, "do": "inspect", "feature": "pocket"}]
    detail = data.kernel["setups"]["S1"]
    if screen is fixture_interference:
        detail["fixture_clashes"] = ["vise jaw intersects stock"]
    elif screen is thin_wall_under_clamp:
        detail["min_wall_mm"] = 1.0
    elif screen is vise:
        detail["parallel_pair"] = False
    else:
        setup["hold"]["fixture"] = "collet"
        setup["stock_state"] = {"od_mm": 20.0}
        data.inventory["fixtures"]["collet"] = {
            "kind": "collet",
            "sizes_mm": [6.0],
            "verify": False,
        }
    assert screen.evaluate(data)[0].status == "error"


def test_unknown_coating_product_stays_debt_and_prints_its_actual_topic(tmp_path):
    data = handling_bundle(tmp_path, ("coating",))
    setup = data.plan["setups"][0]
    setup["ops"][0]["process"] = "unknown"
    findings = tool_resolves.evaluate(data)
    row = next(row for row in findings if row.subject == "S1:10")
    assert row.status == "unknown"
    assert row.numbers["process"] == ["unknown"]
    traveler = _Traveler(data, findings, {}, None)
    stops, cautions, topics = traveler.status_lines([row], setup)
    printed = traveler.status_boxes(stops, cautions, topics).lower()
    assert "coating product identity" in printed
    assert "tool/holder fit" not in printed
    assert "not verified" in printed


@pytest.mark.parametrize("action", ["inspect", "fit", "drill", "unknown"])
def test_coating_words_do_not_relabel_other_operation_identity_debt(tmp_path, action):
    data = handling_bundle(tmp_path, (action,))
    row = Finding("tool_resolves", "S1:10", "unknown", {}, [], "coating oil identity unknown")
    traveler = _Traveler(data, [row], {}, None)
    stops, cautions, topics = traveler.status_lines([row], data.plan["setups"][0])
    printed = traveler.status_boxes(stops, cautions, topics).lower()
    assert "tool/holder fit" in printed
    assert "coating product identity" not in printed
