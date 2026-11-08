"""Current manufacturing material, not future finished-face nominal identity."""

from copy import deepcopy

import pytest
from test_lathe_m2 import bundle, setup
from test_turned_profile_kernel import _shaft_and_dome

from prechips.rules import stickout, turned_profile


def _future_dome():
    data = _shaft_and_dome(
        body=(0.0, 18.0, 4.0, 4.0, 4.0, 4.0),
        tip=(18.0, 20.0, 0.0, 4.0, 0.0, 4.0),
    )
    later = deepcopy(setup(data))
    later.update(id="S2", stock_in="S1", ops=[later["ops"][1]])
    setup(data)["ops"] = setup(data)["ops"][:1]
    data.plan["setups"].append(later)
    data.kernel["setups"]["S1"]["stock_profile"] = [[0.0, 20.0, 4.0, 6.0]]
    return data


def test_future_dome_uses_current_native_stock_but_already_formed_dome_does_not():
    data = _future_dome()
    assert turned_profile.evaluate(data)[0].status == "pass"
    assert stickout.evaluate(data)[0].numbers["diameter_mm"] == 8.0
    # Moving the forming operation into this setup makes its geometry simultaneous.
    setup(data)["ops"].extend(data.plan["setups"][1]["ops"])
    finding = turned_profile.evaluate(data)[0]
    assert finding.status == "unknown"
    assert "widens away" in finding.numbers["unresolved_reasons"]["tip"]


def test_unproved_downstream_lineage_does_not_discard_finished_feature():
    data = _future_dome()
    data.plan["setups"][1]["stock_in"] = "stock"
    finding = turned_profile.evaluate(data)[0]
    assert finding.status == "unknown"
    assert "lineage is unproven" in finding.numbers["unresolved_reasons"]["tip"]


@pytest.mark.parametrize("rows", [None, [[0.0, 19.0, 4.0, 6.0]]])
def test_future_phase_without_complete_current_stock_proof_stays_unknown(rows):
    data = _future_dome()
    facts = data.kernel["setups"]["S1"]
    if rows is None:
        del facts["stock_profile"]
    else:
        facts["stock_profile"] = rows
    finding = turned_profile.evaluate(data)[0]
    assert finding.status == "unknown"
    assert "current-stock proof" in finding.numbers["unresolved_reasons"]["tip"]
    assert stickout.evaluate(data)[0].status == "unknown"


def test_current_thin_cut_is_not_hidden_by_raw_entry_or_finished_nominal():
    data = _future_dome()
    data.kernel["setups"]["S1"]["stock_profile"] = [
        [0.0, 10.0, 2.0, 6.0], [10.0, 20.0, 4.0, 6.0]
    ]
    finding = stickout.evaluate(data)[0]
    assert finding.numbers["diameter_mm"] == 4.0
    assert finding.status == "error"


@pytest.mark.parametrize(
    "target_band,prep_band,formed,accepted",
    [
        ([9.906, 10.414], [10.18286, 10.19302], False, True),
        ([9.906, 10.17], [10.18286, 10.19302], False, False),
        ([9.906, 10.414], [10.18, 10.5], False, False),
        ([9.906, 10.414], "unknown", False, False),
        ([9.906, 10.414], [10.18286, 10.19302], True, False),
    ],
)
def test_prejoin_actual_diameter_requires_compatible_complete_acceptance_bands(
    target_band, prep_band, formed, accepted
):
    data = bundle()
    data.features["features"] = {
        "hub_od": {"kind": "boss", "dia_nominal": 10.16, "dia": target_band},
        "hub_land": {
            "kind": "boss", "dia_nominal": 10.18794, "dia": prep_band,
            "joint": {"id": "hub_land"},
        },
    }
    setup(data)["ops"] = [{"op": 10, "do": "finish_turn", "feature": "hub_land"}]
    if formed:
        setup(data)["ops"].append({"op": 20, "do": "finish_turn", "feature": "hub_od"})
    items = [
        {"feature": "hub_od", "diameter_mm": 10.16},
        {"feature": "hub_land", "diameter_mm": 10.18794},
    ]
    result = turned_profile._accepted_preparation(data, setup(data), items, {"hub_land"})
    assert (result is not None) is accepted
    if accepted:
        assert result == [items[1]]
