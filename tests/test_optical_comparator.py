"""External silhouette metrology is distinct from a fixed profile template."""

from dataclasses import replace

import pytest
from test_practical_inspection import practical_bundle

from prechips.rules import inspection


def comparator_bundle(requirement="height", band=None, *, feature_kind="profile"):
    bundle = replace(
        practical_bundle(),
        features={
            "units": "mm",
            "features": {
                "outline": {
                    "kind": feature_kind,
                    "faces": ["#1"],
                    "requirements": [requirement],
                    requirement: [1.27, 1.778] if band is None else band,
                }
            },
        },
        inventory={
            "gauges": {
                "projector": {
                    "kind": "optical_comparator",
                    "range_mm": [0.0, 150.0],
                    "resolution_mm": 0.001,
                    "profile_resolution_mm": 0.01,
                    "cite": "Synthetic comparator stage and magnified contour capability",
                }
            }
        },
    )
    for setup in bundle.plan["setups"]:
        setup["ops"] = [op for op in setup["ops"] if op["do"] == "cut_off"]
    for setup in bundle.plan["setups"][-4:]:
        setup["ops"] = [
            {
                "op": 10,
                "do": "inspect",
                "feature": "outline",
                "checks": {requirement: "projector"},
                "inspection_methods": {
                    requirement: "Align the external silhouette with the calibrated stage; "
                    "read the two local extremes, or compare the magnified radius trace."
                },
            }
        ]
    return bundle


def first_row(bundle):
    return next(row for row in inspection.evaluate(bundle) if row.subject.startswith("nut1/"))


@pytest.mark.parametrize("requirement", ["height", "length", "station", "width", "thickness"])
def test_declared_external_silhouette_dimensions_use_linear_stage_capability(requirement):
    row = first_row(comparator_bundle(requirement))
    assert row.status == "pass", row.sentence
    assert row.numbers["gauge_kind"] == "optical_comparator"
    assert row.numbers["resolution_mm"] == 0.001
    assert row.numbers["inspection_method"].startswith("Align the external silhouette")


@pytest.mark.parametrize("requirement", ["radius", "bottom_radius"])
def test_contour_reading_uses_profile_discrimination_not_stage_scale_or_leaf(requirement):
    bundle = comparator_bundle(requirement, [0.0, 0.2032])
    row = first_row(bundle)
    assert row.status == "pass", row.sentence
    assert row.numbers["resolution_mm"] == 0.01
    assert "limit_check" not in row.numbers
    del bundle.inventory["gauges"]["projector"]["profile_resolution_mm"]
    row = first_row(bundle)
    assert row.status == "unknown"
    assert "range or resolution unresolved" in row.sentence


@pytest.mark.parametrize("missing", ["method", "evidence", "range", "resolution", "verified"])
def test_optical_reading_requires_declared_method_and_trusted_capability(missing):
    bundle = comparator_bundle()
    gauge = bundle.inventory["gauges"]["projector"]
    if missing == "method":
        bundle.plan["setups"][-4]["ops"][0]["inspection_methods"] = {}
    elif missing == "evidence":
        del gauge["cite"]
    elif missing == "range":
        del gauge["range_mm"]
    elif missing == "resolution":
        del gauge["resolution_mm"]
    else:
        gauge["verify"] = True
    assert first_row(bundle).status == "unknown"


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("range_mm", [0.0, 1.0], "does not span the requirement band"),
        ("resolution_mm", 1.0, "resolution exceeds the requirement band"),
    ],
)
def test_inadequate_optical_stage_still_fails(field, value, message):
    bundle = comparator_bundle()
    bundle.inventory["gauges"]["projector"][field] = value
    row = first_row(bundle)
    assert row.status == "error"
    assert message in row.sentence


@pytest.mark.parametrize(
    "requirement",
    ["depth", "dia", "height_above_pivot", "position_dia", "surface_profile", "finish_ra"],
)
def test_projector_is_not_universal_internal_or_datum_frame_metrology(requirement):
    row = first_row(comparator_bundle(requirement))
    assert row.status == "error"
    assert "named gauge cannot measure this requirement" in row.sentence


@pytest.mark.parametrize("feature_kind", ["hole", "threaded_hole", "pocket", "unknown"])
def test_internal_or_unknown_feature_does_not_gain_silhouette_capability(feature_kind):
    row = first_row(comparator_bundle(feature_kind=feature_kind))
    assert row.status == ("unknown" if feature_kind == "unknown" else "error")


def test_fixed_profile_gauge_does_not_gain_linear_stage_capability():
    bundle = comparator_bundle()
    bundle.inventory["gauges"]["projector"]["kind"] = "profile_gauge"
    row = first_row(bundle)
    assert row.status == "error"
    assert "named gauge cannot measure this requirement" in row.sentence
