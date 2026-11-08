"""Signed datum coordinates must map to qualified physical gauge readings."""

from copy import deepcopy
from dataclasses import replace

import pytest
from test_optical_comparator import comparator_bundle, first_row
from test_surface_profile import write_bundle

from prechips.inputs import BadInput, load_bundle
from prechips.rules import inspection


QUALIFICATION = {
    "kind": "relative_coordinate",
    "offset_mm": 104.0,
    "method": "Set the reference-arbor axis at H0=100 above the plate; qualify by "
    "blocks and reversal. Ground stem radius is 4. Coordinate = stem top - 104.",
    "cite": ["Synthetic 100 mm reference stand and ground 4 mm stem radius qualification"],
}


def relative_bundle():
    bundle = comparator_bundle("station", [-13.208, -12.7], feature_kind="hole")
    bundle.inventory["gauges"]["projector"] = {
        "kind": "height_gauge",
        "range_mm": [0.0, 300.0],
        "resolution_mm": 0.001,
    }
    for setup in bundle.plan["setups"][-4:]:
        op = setup["ops"][0]
        op["inspection_methods"] = {
            "station": "Measure the positive stem-top height; subtract qualified H0 and "
            "stem radius, reverse and repeat at both mouths; record the signed coordinate."
        }
        op["inspection_readings"] = {"station": deepcopy(QUALIFICATION)}
    return bundle


def test_negative_station_uses_actual_positive_readings_without_changing_instrument_range():
    row = first_row(relative_bundle())
    assert row.status == "pass", row.sentence
    assert row.numbers["limits"] == [-13.208, -12.7]
    assert row.numbers["physical_reading_band_mm"] == pytest.approx([90.792, 91.3])
    assert row.numbers["range_mm"] == [0.0, 300.0]
    assert row.numbers["resolution_mm"] == 0.001
    assert row.numbers["inspection_reading"] == QUALIFICATION
    assert row.numbers["part_result"] == "not_recorded"


@pytest.mark.parametrize("field", ["kind", "offset_mm", "method", "cite"])
def test_missing_datum_qualification_is_unknown_not_negative_travel_success(field):
    bundle = relative_bundle()
    del bundle.plan["setups"][-4]["ops"][0]["inspection_readings"]["station"][field]
    row = first_row(bundle)
    assert row.status == "unknown"
    assert "datum qualification is unresolved" in row.sentence
    assert "physical_reading_band_mm" not in row.numbers


@pytest.mark.parametrize("offset", [0.0, 1000.0])
def test_qualified_but_physically_unreachable_readings_still_fail(offset):
    bundle = relative_bundle()
    bundle.plan["setups"][-4]["ops"][0]["inspection_readings"]["station"]["offset_mm"] = offset
    row = first_row(bundle)
    assert row.status == "error"
    assert "gauge does not span the requirement band" in row.sentence
    assert row.numbers["range_mm"] == [0.0, 300.0]


def test_relative_reading_keeps_gauge_resolution_and_verification_requirements():
    bundle = relative_bundle()
    gauge = bundle.inventory["gauges"]["projector"]
    gauge["resolution_mm"] = 1.0
    row = first_row(bundle)
    assert row.status == "error"
    assert "resolution exceeds" in row.sentence
    gauge["resolution_mm"] = 0.001
    gauge["verify"] = True
    assert first_row(bundle).status == "unknown"


def test_unqualified_station_and_incompatible_instrument_do_not_gain_relative_capability():
    bundle = relative_bundle()
    op = bundle.plan["setups"][-4]["ops"][0]
    del op["inspection_readings"]
    assert first_row(bundle).status == "error"
    op["inspection_readings"] = {"station": deepcopy(QUALIFICATION)}
    bundle.inventory["gauges"]["projector"]["kind"] = "caliper"
    row = first_row(bundle)
    assert row.status == "error"
    assert "relative-coordinate reading is unsupported" in row.sentence


def test_each_feature_and_branch_uses_only_its_own_qualified_reading():
    bundle = relative_bundle()
    features = deepcopy(bundle.features)
    features["features"]["other"] = {
        "kind": "hole",
        "faces": ["#2"],
        "requirements": ["station"],
        "station": [12.7, 13.208],
    }
    bundle = replace(bundle, features=features)
    for setup in bundle.plan["setups"][-4:]:
        op = setup["ops"][0]
        op["feature"] = ["outline", "other"]
        op["inspection_readings"] = {
            "outline": {"station": deepcopy(QUALIFICATION)},
            "other": {"station": {**QUALIFICATION, "offset_mm": 100.0}},
        }
    bundle.plan["setups"][-3]["ops"][0]["inspection_readings"]["outline"]["station"][
        "offset_mm"
    ] = "unknown"
    rows = {row.subject: row for row in inspection.evaluate(bundle)}
    assert rows["nut1/outline:station"].status == "pass"
    assert rows["nut2/outline:station"].status == "unknown"
    for member in ("nut1", "nut2", "nut3", "nut4"):
        row = rows[f"{member}/other:station"]
        assert row.status == "pass", row.sentence
        assert row.numbers["physical_reading_band_mm"] == pytest.approx([112.7, 113.208])


@pytest.mark.parametrize("offset", ["104.0", '"unknown"'])
def test_reading_contract_loads_through_public_input_boundary(tmp_path, offset):
    plan = write_bundle(
        tmp_path,
        {"outline": 'kind = "hole"\nrequirements = ["station"]\nstation = [-13.208, -12.7]\n'},
        subject="outline",
        requirement="station",
        gauge="height_gauge",
    )
    with plan.open("a", encoding="utf-8") as stream:
        stream.write(
            'inspection_readings = { station = { kind = "relative_coordinate", '
            f'offset_mm = {offset}, method = "Qualify datum stand and stem by reversal", '
            'cite = ["Synthetic reference stand qualification"] } }\n'
        )
    bundle = load_bundle(plan)
    row = next(row for row in inspection.evaluate(bundle) if row.subject == "outline:station")
    assert row.status == ("unknown" if offset == '"unknown"' else "pass"), row.sentence


def test_reading_contract_cannot_name_an_unchecked_requirement(tmp_path):
    plan = write_bundle(
        tmp_path,
        {"top_edge": 'kind = "face"\nrequirements = ["length"]\nlength = [1, 2]\n'},
        requirement="length",
    )
    with plan.open("a", encoding="utf-8") as stream:
        stream.write('inspection_readings = { station = { kind = "relative_coordinate" } }\n')
    with pytest.raises(BadInput, match="names no checks gauge"):
        load_bundle(plan)
