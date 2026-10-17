"""One-sided radius limits: "R MAX" (band [0, r]) is read go/no-go by the leaf at r (#302)."""

from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from prechips.model import Features
from prechips.rules import inspection

MEASURED = {"status": "measured", "by": "test", "date": "2026-10-17", "instrument": "certificate"}
FACE = "#1/ADVANCED_FACE[1]/HAF_HUB_ROOT__P01"


def bundle(range_mm, *, band=(0.0, 0.2), kind="radius_gauge", verify=False, resolution=0.1):
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
