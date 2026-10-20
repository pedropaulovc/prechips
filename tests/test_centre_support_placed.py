"""Borrowed material is not inventory centre tooling; unresolved sources retain debt."""

from copy import deepcopy
from pathlib import Path

import pytest
from test_batch_material_routes import batch

from prechips.inputs import Bundle
from prechips.model import Plan
from prechips.rules import centre_support


def bundle():
    return Bundle(
        plan=Plan.model_validate(batch()).model_dump(exclude_unset=True),
        features={"features": {}},
        inventory={
            "fixtures": {
                "post": {"kind": "custom", "verify": True},
                "dead": {"kind": "dead_centre"},
            }
        },
        policy={},
        cutting_data={},
        paths={},
        hashes={},
        root=Path("."),
    )


def receiver(data):
    return next(setup for setup in data.plan["setups"] if setup["id"] == "C2")


def support(data):
    return receiver(data)["hold"]["supports"][0]


def finding(data):
    return next(row for row in centre_support.evaluate(data) if row.subject == "C2")


def test_validated_borrowed_stock_is_not_inventory_centre_tooling():
    data = bundle()
    before = deepcopy(data.plan)
    row = finding(data)
    assert row.status == "not_applicable"
    assert "unresolved_supports" not in row.numbers
    assert data.plan == before


@pytest.mark.parametrize(
    "reference",
    [
        "unknown",
        "",
        "stock_out.missing",
        "stock",
        "E1",
        "stock_out.lower1",
        "stock_out.lower2",
    ],
)
def test_unregistered_unavailable_or_overlapping_borrowed_source_stays_unknown(reference):
    data = bundle()
    support(data)["stock_ref"] = reference
    row = finding(data)
    assert row.status == "unknown"
    assert row.numbers["unresolved_supports"] == [reference]


@pytest.mark.parametrize("mutation", ["both", "neither", "untagged", "missing-id", "missing-pose"])
def test_malformed_or_ambiguous_borrowed_source_never_erases_centre_debt(mutation):
    data = bundle()
    entry = support(data)
    if mutation == "both":
        entry["ref"] = "fixtures.post"
    elif mutation == "neither":
        entry.pop("stock_ref")
    elif mutation == "untagged":
        entry.pop("placement")
    elif mutation == "missing-id":
        entry.pop("id")
    else:
        entry.pop("pose")
    row = finding(data)
    assert row.status == "unknown"
    assert row.numbers["unresolved_supports"]


def test_borrowed_source_does_not_hide_an_unknown_inventory_support():
    data = bundle()
    receiver(data)["hold"]["supports"].append("unknown")
    row = finding(data)
    assert row.status == "unknown"
    assert row.numbers["unresolved_supports"] == ["unknown"]


@pytest.mark.parametrize(
    ("reference", "expected"),
    [
        ("fixtures.post", "not_applicable"),
        ("fixtures.dead", "unknown"),
        ("fixtures.missing", "unknown"),
    ],
)
def test_tagged_inventory_support_keeps_inventory_kind_classification(reference, expected):
    data = bundle()
    entry = support(data)
    entry.pop("stock_ref")
    entry["ref"] = reference
    row = finding(data)
    assert row.status == expected
    if reference == "fixtures.dead":
        assert row.numbers["centres"] == [reference]
        assert row.numbers["centre_hole"] == "unknown"
    elif reference == "fixtures.missing":
        assert row.numbers["unresolved_supports"] == [reference]


def test_explicit_centre_seat_claim_is_not_waived_by_borrowed_material():
    data = bundle()
    receiver(data)["hold"]["centre_hole"] = "unknown"
    row = finding(data)
    assert row.status == "unknown"
    assert row.numbers["centre_hole"] == "unknown"


def test_borrowed_source_must_be_in_the_tagged_support_array():
    data = bundle()
    receiver(data)["hold"]["supports"] = support(data)
    row = finding(data)
    assert row.status == "unknown"
    assert row.numbers["unresolved_supports"] == ["stock_out.nut1_b"]
