"""Collet/chuck capacity for holds that name an inventory machine, such as a dividing head."""

from pathlib import Path

import pytest

from prechips.inputs import Bundle
from prechips.rules import stock_diameter

DIVIDING_HEAD = {
    "kind": "dividing_head",
    "worm_ratio": 40,
    "included": ["chuck_3jaw_5in_inside_outside_jaws", "tailstock_adjustable"],
    "verify": False,
    "spindle": {"bore_in": 0.708, "mount": "1-1/2 x 8 TPI"},
}


def bundle(head=None, fixtures=None):
    return Bundle(
        plan={
            "part": "stock-diameter-test",
            "features": "features.toml",
            "stock": {"form": "round_bar", "dia_mm": 12.0, "cite": "test authored blank"},
            "setups": [
                {
                    "id": "S1",
                    "machine": "PM-30MV",
                    "stock_state": {"od_mm": 12.0},
                    "hold": {"fixture": "BS-0", "support": "none"},
                    "ops": [],
                }
            ],
        },
        features={"part": "stock-diameter-test", "units": "mm", "features": {}},
        inventory={
            "machines": {
                "PM-30MV": {"kind": "mill", "verify": False},
                "BS-0": dict(DIVIDING_HEAD if head is None else head),
            },
            "fixtures": {} if fixtures is None else fixtures,
        },
        policy={"required": {"stock_diameter": "*"}},
        cutting_data={},
        paths={},
        hashes={},
        root=Path("."),
    )


def finding(data):
    (result,) = stock_diameter.evaluate(data)
    return result


@pytest.mark.parametrize("verify", [False, True])
def test_known_dividing_head_machine_without_capacity_is_not_applicable(verify):
    result = finding(bundle({**DIVIDING_HEAD, "verify": verify}))
    assert result.status == "not_applicable"
    assert result.numbers["fixture_kind"] == "dividing_head"


@pytest.mark.parametrize("capacity", [{}, {"range_mm": [6.0, 14.0]}])
def test_dividing_head_resolves_the_same_under_machines_or_fixtures(capacity):
    head = {**DIVIDING_HEAD, **capacity}
    as_machine = finding(bundle(head))
    data = bundle(fixtures={"BS-0": head})
    data.inventory["machines"].pop("BS-0")
    as_fixture = finding(data)
    assert (as_machine.status, as_machine.numbers) == (as_fixture.status, as_fixture.numbers)


@pytest.mark.parametrize(
    "diameter,expected", [(6.0, "pass"), (14.0, "pass"), (5.9, "error"), (14.1, "error")]
)
def test_machine_declared_chuck_range_is_checked_inclusively(diameter, expected):
    data = bundle({**DIVIDING_HEAD, "range_mm": [6.0, 14.0]})
    data.plan["setups"][0]["stock_state"]["od_mm"] = diameter
    result = finding(data)
    assert result.status == expected
    assert result.numbers["ranges_mm"] == [[6.0, 14.0]]


@pytest.mark.parametrize(
    "capacity,diameter,expected",
    [
        ({"sizes_in": ["1/4", "3/8"]}, 9.525, "pass"),
        ({"sizes_in": ["1/4", "3/8"]}, 8.0, "error"),
        ({"range_mm": 14.0}, 12.0, "unknown"),
        ({"range_mm": "unknown"}, 12.0, "unknown"),
    ],
)
def test_machine_declared_collet_sizes_use_actual_capacity(capacity, diameter, expected):
    data = bundle({**DIVIDING_HEAD, **capacity})
    data.plan["setups"][0]["stock_state"]["od_mm"] = diameter
    assert finding(data).status == expected


@pytest.mark.parametrize("diameter", [12.0, 30.0])
def test_unverified_machine_capacity_cannot_prove_fit_or_mismatch(diameter):
    data = bundle({**DIVIDING_HEAD, "range_mm": [6.0, 14.0], "verify": True})
    data.plan["setups"][0]["stock_state"]["od_mm"] = diameter
    assert finding(data).status == "unknown"


@pytest.mark.parametrize(
    "head,reference",
    [
        ("unknown", "BS-0"),
        ({**DIVIDING_HEAD, "present": False}, "BS-0"),
        ({**DIVIDING_HEAD, "kind": "unknown"}, "BS-0"),
        (DIVIDING_HEAD, "BS-0/chuck"),
        (DIVIDING_HEAD, "BS-1"),
    ],
)
def test_unresolved_machine_hold_identity_stays_unknown(head, reference):
    data = bundle()
    data.inventory["machines"]["BS-0"] = head
    data.plan["setups"][0]["hold"]["fixture"] = reference
    assert finding(data).status == "unknown"
