"""Posed auxiliaries stay native obstacles; legacy bearing supports retain their stack."""

from copy import deepcopy

import pytest
from test_headroom import bundle, measured

from prechips.rules.headroom import evaluate


def posed(**source):
    return {
        "placement": "posed",
        "id": "auxiliary",
        **source,
        "pose": {"origin_mm": [120, 0, 0], "x": [1, 0, 0], "z": [0, 0, 1]},
        "note": "Independent auxiliary beside the primary fixture, not beneath the work.",
    }


def support_bundle(supports):
    data = bundle()
    data.plan["setups"][0]["hold"]["supports"] = supports
    # Keep the cutter clear of the jaws even when no bearing blocks are present.
    data.inventory["fixtures"]["vise"]["jaw_height_mm"] = 10
    return data


@pytest.mark.parametrize("source", [{"ref": "blocks"}, {"stock_ref": "earlier-output"}])
def test_posed_auxiliary_does_not_add_an_underpart_stack(source):
    data = support_bundle([posed(**source)])
    original = deepcopy(data.plan["setups"][0]["hold"]["supports"])
    finding = evaluate(data)[0]
    assert finding.status == "pass"
    assert finding.numbers["support_blocks_mm"] == 0
    assert finding.numbers["bed_height_mm"] == 20
    assert finding.numbers["parallels_mm"] == 10
    assert finding.numbers["sum_mm"] == pytest.approx(156)
    assert data.plan["setups"][0]["hold"]["supports"] == original


def test_unknown_auxiliary_pose_is_native_debt_not_an_invented_stack_layer():
    auxiliary = posed(ref="blocks")
    auxiliary["pose"] = "unknown"
    finding = evaluate(support_bundle([auxiliary]))[0]
    assert finding.numbers["support_blocks_mm"] == 0
    assert finding.numbers["sum_mm"] == pytest.approx(156)


@pytest.mark.parametrize("supports", ["blocks", ["blocks"], [{"ref": "blocks"}]])
def test_actual_legacy_support_still_adds_its_oriented_height(supports):
    finding = evaluate(support_bundle(supports))[0]
    assert finding.status == "pass"
    assert finding.numbers["support_blocks_mm"] == pytest.approx(25.4)
    assert finding.numbers["sum_mm"] == pytest.approx(181.4)


@pytest.mark.parametrize("supports", [None, [posed(ref="blocks")], []])
def test_explicit_riser_remains_a_bearing_layer_with_or_without_auxiliaries(supports):
    data = support_bundle(supports)
    hold = data.plan["setups"][0]["hold"]
    if supports is None:
        del hold["supports"]
    hold["riser"] = "blocks"
    finding = evaluate(data)[0]
    assert finding.status == "pass"
    assert finding.numbers["support_blocks_mm"] == pytest.approx(25.4)
    assert finding.numbers["sum_mm"] == pytest.approx(181.4)


def test_mixed_auxiliary_and_one_legacy_reference_preserve_the_legacy_height():
    finding = evaluate(support_bundle([posed(ref="blocks"), "blocks"]))[0]
    assert finding.status == "pass"
    assert finding.numbers["support_blocks_mm"] == pytest.approx(25.4)
    assert finding.numbers["sum_mm"] == pytest.approx(181.4)


@pytest.mark.parametrize(
    "supports",
    [
        ["blocks", "spacer"],
        [posed(ref="blocks"), "blocks", {"ref": "spacer"}],
        ["blocks", "blocks"],
    ],
)
def test_multiple_legacy_candidates_do_not_invent_serial_bearing_layers(supports):
    data = support_bundle(supports)
    data.inventory["fixtures"]["spacer"] = {"kind": "spacer", "height_mm": 5}
    finding = evaluate(data)[0]
    assert finding.status == "unknown"
    assert finding.numbers["support_blocks_mm"] == "unknown"
    assert finding.numbers["sum_mm"] == "unknown"


@pytest.mark.parametrize("riser", ["blocks", "fixtures.blocks"])
@pytest.mark.parametrize("support", ["blocks", "fixtures.blocks"])
def test_explicit_riser_is_not_counted_twice_when_also_listed_as_a_support(riser, support):
    data = support_bundle([posed(ref="blocks"), support])
    data.plan["setups"][0]["hold"]["riser"] = riser
    finding = evaluate(data)[0]
    assert finding.status == "pass"
    assert finding.numbers["support_blocks_mm"] == pytest.approx(25.4)
    assert finding.numbers["sum_mm"] == pytest.approx(181.4)


@pytest.mark.parametrize("support", ["spacer", "fixtures.spacer", "missing", "unknown"])
def test_distinct_or_unknown_support_beside_explicit_riser_retains_debt(support):
    data = support_bundle([posed(ref="blocks"), support])
    data.plan["setups"][0]["hold"]["riser"] = "blocks"
    data.inventory["fixtures"]["spacer"] = {"kind": "spacer", "height_mm": 5}
    finding = evaluate(data)[0]
    assert finding.status == "unknown"
    assert finding.numbers["support_blocks_mm"] == "unknown"
    assert finding.numbers["sum_mm"] == "unknown"


def test_reference_orientation_selects_the_actual_legacy_block_height():
    data = support_bundle([posed(ref="blocks"), {"ref": "blocks", "orientation": "2 in height"}])
    finding = evaluate(data)[0]
    assert finding.numbers["support_blocks_mm"] == pytest.approx(50.8)
    assert finding.numbers["sum_mm"] == pytest.approx(206.8)
    assert finding.status == "error"


@pytest.mark.parametrize(
    "supports",
    [
        "unknown",
        ["unknown"],
        ["missing"],
        [None],
        [{}],
        [{"ref": None}],
        [{"ref": "blocks", "placement": "unposed"}],
        [{"ref": "blocks", "unsupported_role": "rest"}],
        [{"ref": "blocks", "jaw_lead_mm": 5}],
        [{"ref": "blocks", "at_z_mm": 5}],
        [posed(ref="missing")],
        [posed(ref="unknown")],
        [posed(ref="blocks", stock_ref="earlier-output")],
        [posed()],
        [{key: value for key, value in posed(ref="blocks").items() if key != "note"}],
        [posed(ref="blocks"), posed(stock_ref="earlier-output")],
        [posed(ref="blocks"), "missing"],
    ],
)
def test_unknown_or_malformed_support_never_becomes_a_zero_layer(supports):
    finding = evaluate(support_bundle(supports))[0]
    assert finding.status == "unknown"
    assert finding.numbers["support_blocks_mm"] == "unknown"
    assert finding.numbers["sum_mm"] == "unknown"
    assert finding.numbers["stacks"][0]["margin_mm"] == "unknown"


def test_missing_legacy_orientation_is_unknown_even_beside_a_posed_auxiliary():
    data = support_bundle([posed(ref="blocks"), "blocks"])
    del data.plan["setups"][0]["hold"]["support_orientation"]
    finding = evaluate(data)[0]
    assert finding.status == "unknown"
    assert finding.numbers["support_blocks_mm"] == "unknown"
    assert finding.numbers["sum_mm"] == "unknown"


def test_unverified_legacy_support_keeps_its_nominal_stack_and_debt():
    data = support_bundle([posed(ref="blocks"), "spacer"])
    data.inventory["fixtures"]["spacer"] = {
        "kind": "spacer",
        "height_mm": 5,
        "verify": True,
    }
    finding = evaluate(data)[0]
    assert finding.status == "unknown"
    assert finding.numbers["support_blocks_mm"] == 5
    assert finding.numbers["sum_mm"] == pytest.approx(161)
    assert finding.numbers["stacks"][0]["verify"] is True


def test_posed_auxiliary_does_not_suppress_a_primary_stack_limit_error():
    data = support_bundle([posed(ref="blocks")])
    data.inventory["machines"]["mill"]["envelope"]["spindle_to_table_max_mm"] = measured(150)
    finding = evaluate(data)[0]
    assert finding.status == "error"
    assert finding.numbers["stacks"][0]["margin_mm"] == pytest.approx(-6)


def test_headroom_leaves_native_obstacle_clearance_evidence_untouched():
    data = support_bundle([posed(stock_ref="earlier-output")])
    data.kernel = {
        "status": "ok",
        "setups": {
            "S1": {
                "stock_bbox_mm": [0, 0, -12, 100, 30, 4],
                "fixture_gaps": ["support auxiliary: borrowed support geometry is unknown"],
            }
        },
    }
    original = deepcopy(data.kernel)
    finding = evaluate(data)[0]
    assert finding.numbers["support_blocks_mm"] == 0
    assert data.kernel == original
