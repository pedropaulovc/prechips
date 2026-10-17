"""One-sided radius limits: "R MAX" (band [0, r]) is read go/no-go by the leaf at r (#302)."""

from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from prechips.model import Features
from prechips.rules import inspection

MEASURED = {"status": "measured", "by": "test", "date": "2026-10-17", "instrument": "certificate"}
FACE = "#1/ADVANCED_FACE[1]/HAF_HUB_ROOT__P01"


def bundle(
    range_mm,
    *,
    band=(0.0, 0.2),
    kind="radius_gauge",
    verify=False,
    resolution=0.1,
    leaf_tolerance=None,
):
    feature = {
        "kind": "fillet",
        "frame": "model",
        "requirements": ["radius"],
        "radius": list(band),
        "note": "2X R0.2 MAX",
        "faces": [FACE],
    }
    plan = {
        "setups": [
            {
                "id": "F1",
                "machine": "bench",
                "ops": [
                    {
                        "op": 45,
                        "do": "inspect",
                        "feature": "hub_root",
                        "checks": {"radius": "radius-gauge-small"},
                    }
                ],
            }
        ]
    }
    gauge = {
        "kind": kind,
        "verify": verify,
        "range_mm": range_mm,
        "resolution_mm": {"value": resolution, "measured": dict(MEASURED)},
    }
    if leaf_tolerance is not None:
        gauge["leaf_tolerance_mm"] = leaf_tolerance
    return SimpleNamespace(
        plan=plan,
        inventory={"gauges": {"radius-gauge-small": gauge}},
        features={"units": "mm", "features": {"hub_root": feature}},
        feature_definitions={"hub_root": feature},
    )


def finding(b):
    (row,) = [f for f in inspection.evaluate(b) if f.subject == "hub_root:radius"]
    return row


@pytest.mark.parametrize("kind", ["radius_gauge", "profile_gauge"])
def test_leaf_set_starting_at_the_max_limit_passes_as_a_limit_check(kind):
    # The issue's repro: Fuji 272HRMAA leaves R0.2-R1.0 read "R0.2 MAX" with the R0.2 leaf.
    row = finding(bundle([0.2, 1.0], kind=kind))
    assert row.status == "pass", row.sentence
    assert "limit check" in row.sentence
    assert "not a reading across the band" in row.sentence
    assert row.numbers["limit_check"] == "max"
    assert row.numbers["limit_mm"] == 0.2
    assert "band_mm" not in row.numbers
    assert "leaf_tolerance_mm" not in row.numbers


def test_leaf_tolerance_crossing_the_limit_is_not_a_clean_pass():
    # Fuji 272HRMAA's leaves are ±0.01: the R0.2 leaf may be R0.21 and accept a corner
    # past R0.2 MAX. The set has no leaf at or under R0.19, so the limit is undecided.
    tolerance = {"value": 0.01, "measured": dict(MEASURED)}
    row = finding(bundle([0.2, 1.0], leaf_tolerance=tolerance))
    assert row.status == "error"
    assert "tolerance crosses the MAX limit" in row.sentence
    assert row.numbers["leaf_tolerance_mm"] == 0.01


def test_a_leaf_under_the_limit_by_its_tolerance_is_not_named_so_not_a_pass():
    # Leaves R0.1-R1.0 by 0.01 hold a safe R0.19 leaf, but the traveler prints only the
    # band and gauge: the operator would reach for R0.2, which may accept R0.21.
    tolerance = {"value": 0.01, "measured": dict(MEASURED)}
    row = finding(bundle([0.1, 1.0], resolution=0.01, leaf_tolerance=tolerance))
    assert row.status == "unknown", row.sentence
    assert "only a leaf at or under R0.19 reads the limit" in row.sentence
    assert row.numbers["leaf_max_mm"] == pytest.approx(0.19)


def test_no_leaf_at_the_limit_is_an_error_whatever_the_tolerance():
    row = finding(bundle([0.3, 1.0], leaf_tolerance="unknown"))
    assert row.status == "error"
    assert "no leaf at the MAX limit" in row.sentence


@pytest.mark.parametrize(
    "tolerance",
    ["unknown", {"value": 0.01, "measured": {**MEASURED, "status": "assumed"}}],
)
def test_unknown_or_unverified_leaf_tolerance_is_debt(tolerance):
    row = finding(bundle([0.2, 1.0], leaf_tolerance=tolerance))
    assert row.status == "unknown"
    assert row.numbers["leaf_tolerance_mm"] == "unknown"


@pytest.mark.parametrize("span", [[0.3, 1.0], [0.05, 0.15]])
def test_leaf_set_that_does_not_reach_the_limit_is_an_error(span):
    row = finding(bundle(span))
    assert row.status == "error"
    assert "no leaf at the MAX limit" in row.sentence


def test_resolution_coarser_than_the_limit_is_an_error():
    row = finding(bundle([0.2, 1.0], resolution=0.25))
    assert row.status == "error"
    assert "resolution exceeds the MAX limit" in row.sentence


def test_unverified_gauge_is_debt_not_a_pass():
    row = finding(bundle([0.2, 1.0], verify=True))
    assert row.status == "unknown"
    assert row.numbers["measurements"]


def test_two_sided_band_keeps_the_full_span_rule():
    # R5 ±0.1: both ends are read, so a leaf set must span the band.
    assert finding(bundle([1.0, 7.5], band=(4.9, 5.1))).status == "pass"
    row = finding(bundle([5.0, 7.5], band=(4.9, 5.1)))
    assert row.status == "error"
    assert "does not span the requirement band" in row.sentence
    assert "limit_check" not in row.numbers


def test_a_reading_gauge_still_spans_a_max_only_band():
    # A CMM reads the corner's radius: it is no leaf, so its range must hold the band.
    row = finding(bundle([0.2, 1.0], kind="cmm"))
    assert row.status == "error"
    assert "limit_check" not in row.numbers


def test_min_only_radius_band_is_not_expressible():
    # The mirror "R MIN" band [r, inf] cannot be written: inputs refuse inf, so only the
    # MAX case exists.
    feature = {"kind": "fillet", "requirements": ["radius"], "radius": [0.2, float("inf")]}
    with pytest.raises(ValidationError):
        Features.model_validate(
            {"part": "p", "units": "mm", "frames": "unknown", "features": {"f": feature}}
        )
    Features.model_validate(
        {
            "part": "p",
            "units": "mm",
            "frames": "unknown",
            "features": {"f": {**feature, "radius": [0.2, 1.0]}},
        }
    )


def test_coarse_resolution_is_an_error_whatever_the_tolerance():
    row = finding(bundle([0.1, 1.0], resolution=0.5, leaf_tolerance="unknown"))
    assert row.status == "error"
    assert "resolution exceeds the MAX limit" in row.sentence


def test_a_set_that_brackets_the_limit_without_a_leaf_at_it_is_not_a_pass():
    # Leaves from R0.15 by 0.1 hold R0.15 and R0.25, never R0.2: the safe R0.15 is unnamed.
    row = finding(bundle([0.15, 1.0]))
    assert row.status == "unknown"
    assert "no R0.2 leaf" in row.sentence
    assert row.numbers["leaf_max_mm"] == pytest.approx(0.15)


@pytest.mark.parametrize(("sizes", "status"), [([0.1, 0.2, 0.5], "pass"), ([0.1, 0.5], "unknown")])
def test_listed_leaf_sizes_decide_whether_the_limit_leaf_exists(sizes, status):
    b = bundle([0.1, 0.5])
    b.inventory["gauges"]["radius-gauge-small"]["sizes_mm"] = sizes
    assert finding(b).status == status


def test_an_empty_leaf_list_has_no_leaf_at_the_limit():
    # A declared empty inventory is no leaves, never a grid inferred from range and pitch.
    b = bundle([0.2, 1.0])
    b.inventory["gauges"]["radius-gauge-small"]["sizes_mm"] = []
    row = finding(b)
    assert row.status == "error"
    assert "no leaf at the MAX limit" in row.sentence


def test_a_zero_leaf_pitch_is_unresolved_not_a_crash():
    row = finding(bundle([0.2, 1.0], resolution=0.0))
    assert row.status == "unknown"
    assert "range or resolution unresolved" in row.sentence


@pytest.mark.parametrize(
    ("tolerance", "expected"),
    [(None, 0.1), ({"value": 0.01, "measured": dict(MEASURED)}, 0.1)],
)
def test_the_safe_leaf_named_is_a_listed_one(tolerance, expected):
    # Listed R0.1 and R0.5 only: the safe leaf under R0.2 (or R0.19) is R0.1, never an
    # inferred R0.2 or R0.19 the set does not hold.
    b = bundle([0.1, 0.5], resolution=0.01, leaf_tolerance=tolerance)
    b.inventory["gauges"]["radius-gauge-small"]["sizes_mm"] = [0.1, 0.5]
    row = finding(b)
    assert row.status == "unknown"
    assert row.numbers["leaf_max_mm"] == pytest.approx(expected)


@pytest.mark.parametrize("sizes", ["unknown", [0.2, "unknown"], ["unknown"]])
def test_an_unknown_leaf_inventory_is_debt_not_an_absence(sizes):
    b = bundle([0.2, 1.0])
    b.inventory["gauges"]["radius-gauge-small"]["sizes_mm"] = sizes
    row = finding(b)
    # Never the certain "no leaf" error: a wholly unknown list makes the gauge itself
    # unverified (resolution's inventory reading), a partly unknown one the leaf sizes.
    assert row.status == "unknown"
    assert "no leaf" not in row.sentence


def test_the_leaf_is_the_printed_max_not_the_raw_limit():
    # R0.24 MAX prints "0.0–0.2" at precision 1: the operator checks R0.2, so a set holding
    # only R0.24 cannot read the printed limit, while one holding R0.2 can.
    def row(sizes):
        b = bundle([0.2, 1.0], band=(0.0, 0.24))
        b.features["precision"] = 1
        b.inventory["gauges"]["radius-gauge-small"]["sizes_mm"] = sizes
        return finding(b)

    raw_only = row([0.24, 0.5])
    assert raw_only.status != "pass"
    assert raw_only.numbers["limit_mm"] == pytest.approx(0.2)
    assert raw_only.numbers["drawing_limit_mm"] == pytest.approx(0.24)
    assert row([0.2, 0.5]).status == "pass"
