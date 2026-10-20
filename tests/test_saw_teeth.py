"""A saw blade needs its policy minimum of teeth in the thickness it crosses (#336)."""

import html
import re
from pathlib import Path

import pytest
from pydantic import ValidationError

from prechips.inputs import Bundle
from prechips.model import Inventory
from prechips.rules.saw_cut import evaluate_teeth
from prechips.sheet import _Traveler

CITE = "vendor blade catalogue"


def bundle(tpi=(4, 6), thickness=2.5, minimum=3, follows=True):
    op = {"op": 10, "do": "saw_cut", "tool": "blade"}
    if follows:
        op.update(follows="S0:10", allowance_mm=1.0)
    else:
        op["cut_plane"] = {"axis": "x", "value": 10.0, "keep": "below"}
    detail = {"cut_thickness_mm": thickness}
    if not follows:
        detail["cut_thickness_axis"] = "y"
    blade = {"kind": "bandsaw", "kerf_mm": 1.5}
    if tpi is not None:
        blade["tpi"] = {"value": list(tpi) if isinstance(tpi, tuple) else tpi, "cite": CITE}
    numbers, cites = {}, {}
    if minimum is not None:
        numbers["saw_min_teeth_in_work"] = minimum
        cites["saw_min_teeth_in_work"] = "at least 3 teeth in the work"
    return Bundle(
        plan={"setups": [{"id": "S1", "machine": "saw", "ops": [op]}]},
        inventory={
            "machines": {"saw": {"kind": "bandsaw", "saw_modes": ["vertical"]}},
            "tools": {"blade": blade},
        },
        features={"features": {}},
        policy={
            "numbers": numbers,
            "numbers_cite": cites,
            "numbers_verify": dict.fromkeys(numbers, False),
        },
        cutting_data={},
        paths={},
        hashes={},
        root=Path("."),
        kernel={"status": "ok", "ops": {"S1:10": detail}},
    )


def teeth(data):
    (finding,) = evaluate_teeth(data)
    assert finding.rule == "saw_teeth"
    return finding


def test_a_4_6_blade_on_a_2_5_mm_strap_is_an_error_with_numbers():
    finding = teeth(bundle())
    assert finding.status == "error"
    assert finding.numbers["tpi"] == [4, 6]
    assert finding.numbers["tpi_coarse"] == 4
    assert finding.numbers["cut_thickness_mm"] == 2.5
    assert finding.numbers["cut_thickness_axis"] == "z"
    assert finding.numbers["teeth_in_work"] == pytest.approx(0.39)
    assert finding.numbers["saw_min_teeth_in_work"] == 3
    # The fix names the pitch that would put the minimum in the work: 3 x 25.4 / 2.5.
    assert "coarse end is at least 30.5 TPI" in finding.sentence


def test_the_printed_fix_rounds_the_needed_pitch_up():
    # 3 x 25.4 / 18.4 = 4.141 TPI: 4.1 would still put fewer than 3 teeth in the work.
    finding = teeth(bundle(tpi=4, thickness=18.4))
    assert finding.status == "error"
    assert "a blade of at least 4.2 TPI" in finding.sentence


def test_an_op_without_a_saw_tool_asks_for_one():
    data = bundle(thickness=50.0)
    del data.plan["setups"][0]["ops"][0]["tool"]
    finding = teeth(data)
    assert finding.status == "unknown"
    assert "select a saw blade" in finding.sentence


def test_a_24_tpi_blade_passes_where_it_puts_three_teeth_in_the_work():
    finding = teeth(bundle(tpi=24, thickness=3.5))
    assert finding.status == "pass"
    assert finding.numbers["teeth_in_work"] == pytest.approx(3.31)
    # On the 2.5 mm strap itself 24 TPI puts only 2.36 teeth in the work.
    assert teeth(bundle(tpi=24)).status == "error"


def test_a_variable_pitch_blade_is_judged_at_its_coarse_end():
    # 10 mm: 4 TPI puts 1.57 teeth in the work, 10 TPI would put 3.94.
    assert teeth(bundle(tpi=(4, 10), thickness=10.0)).status == "error"
    assert teeth(bundle(tpi=(10, 14), thickness=10.0)).status == "pass"


@pytest.mark.parametrize(
    ("thickness", "status"), [(3.17, "error"), (3.175, "pass"), (3.18, "pass")]
)
def test_teeth_just_below_the_minimum_fail_and_at_or_above_it_pass(thickness, status):
    # 24 TPI puts exactly 3 teeth in 3 x 25.4 / 24 = 3.175 mm.
    assert teeth(bundle(tpi=24, thickness=thickness)).status == status


def test_a_count_just_short_of_the_minimum_never_prints_as_the_minimum():
    # 3.17 / 25.4 x 24 = 2.995 teeth: shown as 2.99, never the 3.00 it fails.
    finding = teeth(bundle(tpi=24, thickness=3.17))
    assert finding.status == "error"
    assert finding.numbers["teeth_in_work"] == 2.99
    assert finding.sentence.startswith("S1:10: 2.99 teeth")


@pytest.mark.parametrize(
    "tpi",
    [None, "unknown", {"value": [4, 6]}, {"value": 24, "cite": CITE, "verify": True}],
    ids=["absent", "unknown", "uncited", "verify"],
)
def test_an_unknown_or_unqualified_pitch_is_debt_never_a_pass(tpi):
    data = bundle(tpi=None, thickness=50.0)
    if tpi is not None:
        data.inventory["tools"]["blade"]["tpi"] = tpi
    finding = teeth(data)
    assert finding.status == "unknown"
    assert finding.numbers["tpi_coarse"] == "unknown"
    assert "tools.blade.tpi" in finding.sentence


@pytest.mark.parametrize("policy", ["absent", "uncited", "unverified", "zero"])
def test_an_unknown_policy_minimum_is_debt_never_a_pass(policy):
    data = bundle(tpi=24, thickness=50.0, minimum=None if policy == "absent" else 3)
    if policy == "uncited":
        data.policy["numbers_cite"] = {}
    if policy == "unverified":
        data.policy["numbers_verify"] = {"saw_min_teeth_in_work": True}
    if policy == "zero":
        data.policy["numbers"]["saw_min_teeth_in_work"] = 0
    finding = teeth(data)
    assert finding.status == "unknown"
    assert finding.numbers["saw_min_teeth_in_work"] == "unknown"
    assert "saw_min_teeth_in_work" in finding.sentence


def test_an_unknown_thickness_is_debt_never_a_pass():
    data = bundle(tpi=24)
    data.kernel["ops"]["S1:10"] = {"reasons": {"cut_thickness_mm": "stock_state is unknown"}}
    finding = teeth(data)
    assert finding.status == "unknown"
    assert "stock_state is unknown" in finding.sentence


def test_a_straight_cut_reports_the_section_axis_it_crosses():
    finding = teeth(bundle(tpi=(4, 6), thickness=42.75, follows=False))
    assert finding.status == "pass"
    assert finding.numbers["cut_thickness_axis"] == "y"
    assert finding.numbers["teeth_in_work"] == pytest.approx(6.73)


def test_a_refused_cut_never_passes_on_its_pitch_alone():
    data = bundle(tpi=24, thickness=50.0)
    data.kernel["ops"]["S1:10"]["saw_error"] = "saw leaves no retained stock"
    assert teeth(data).status == "unknown"


def test_a_missing_kernel_leaves_the_teeth_unknown():
    data = bundle(tpi=24, thickness=50.0)
    data.kernel.clear()
    data.kernel.update(status="unknown", kernel_unavailable=True, reason="no kernel")
    finding = teeth(data)
    assert finding.status == "unknown"
    assert finding.numbers["kernel_unavailable"] is True


@pytest.mark.parametrize("value", [[6, 4], [4, 4], [0, 6], 0, -24, [4, 6, 8]])
def test_tpi_schema_rejects_a_disordered_or_nonpositive_pitch(value):
    with pytest.raises(ValidationError):
        Inventory.model_validate({"tools": {"b": {"kind": "bandsaw", "tpi": {"value": value}}}})


def test_tpi_schema_rejects_pitch_mm_and_a_bare_number():
    for blade in ({"kind": "bandsaw", "pitch_mm": 4.2}, {"kind": "hand_saw", "tpi": 24}):
        with pytest.raises(ValidationError):
            Inventory.model_validate({"tools": {"b": blade}})
    Inventory.model_validate(
        {"tools": {"b": {"kind": "hand_saw", "tpi": {"value": 32, "cite": CITE}}}}
    )


def test_the_op_row_prints_too_few_teeth_as_a_stop():
    data = bundle()
    finding = teeth(data)
    setup = data.plan["setups"][0]
    page, _ = _Traveler(data, [finding], {}, None).operations(setup, {})
    text = " ".join(html.unescape(re.sub(r"<[^>]+>", " ", page)).split())
    assert "STOP: 0.39 teeth" in text
    assert "coarse end is at least 30.5 TPI" in text
