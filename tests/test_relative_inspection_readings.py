"""Signed datum coordinates require qualified physical readings, not negative travel."""

from copy import deepcopy
from dataclasses import replace

import pytest
from test_practical_inspection import practical_bundle
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
METHOD = (
    "Measure the positive stem-top height; subtract qualified H0 and stem radius, "
    "reverse and repeat at both mouths; record the signed coordinate."
)


def relative_bundle():
    bundle = replace(
        practical_bundle(),
        features={
            "units": "mm",
            "features": {
                "outline": {
                    "kind": "hole",
                    "faces": ["#1"],
                    "requirements": ["station"],
                    "station": [-13.208, -12.7],
                }
            },
        },
        inventory={
            "gauges": {
                "height": {
                    "kind": "height_gauge",
                    "range_mm": [0.0, 300.0],
                    "resolution_mm": 0.001,
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
                "checks": {"station": "height"},
                "inspection_methods": {"station": METHOD},
                "inspection_readings": {"station": deepcopy(QUALIFICATION)},
            }
        ]
    return bundle


def first_op(bundle):
    return bundle.plan["setups"][-4]["ops"][0]


def first_row(bundle):
    return next(row for row in inspection.evaluate(bundle) if row.subject == "nut1/outline:station")


@pytest.mark.parametrize("kind", ["height_gauge", "cmm"])
def test_negative_station_uses_positive_readings_without_changing_instrument_range(kind):
    bundle = relative_bundle()
    bundle.inventory["gauges"]["height"]["kind"] = kind
    row = first_row(bundle)
    assert row.status == "pass", row.sentence
    assert row.numbers["limits"] == [-13.208, -12.7]
    assert row.numbers["physical_reading_band_mm"] == pytest.approx([90.792, 91.3])
    assert row.numbers["band_mm"] == pytest.approx(0.508)
    assert row.numbers["range_mm"] == [0.0, 300.0]
    assert row.numbers["resolution_mm"] == 0.001
    assert row.numbers["inspection_reading"] == QUALIFICATION
    assert row.numbers["evaluation"] == "inspection_plan"
    assert row.numbers["part_result"] == "not_recorded"


@pytest.mark.parametrize("field", ["kind", "offset_mm", "method", "cite"])
def test_missing_datum_qualification_is_unknown_not_negative_travel_success(field):
    bundle = relative_bundle()
    del first_op(bundle)["inspection_readings"]["station"][field]
    row = first_row(bundle)
    assert row.status == "unknown"
    assert "datum qualification is unresolved" in row.sentence
    assert "physical_reading_band_mm" not in row.numbers


@pytest.mark.parametrize("offset", ["unknown", True, float("nan"), float("inf"), -float("inf")])
def test_unknown_or_nonfinite_offset_never_establishes_a_physical_reading(offset):
    bundle = relative_bundle()
    first_op(bundle)["inspection_readings"]["station"]["offset_mm"] = offset
    row = first_row(bundle)
    assert row.status == "unknown"
    assert "physical_reading_band_mm" not in row.numbers
    assert row.numbers["part_result"] == "not_recorded"


@pytest.mark.parametrize("whole_table", [False, True])
def test_explicit_unknown_reading_is_not_treated_as_absent(whole_table):
    bundle = relative_bundle()
    first_op(bundle)["inspection_readings"] = "unknown" if whole_table else {"station": "unknown"}
    row = first_row(bundle)
    assert row.status == "unknown"
    assert row.numbers["inspection_reading"] == "unknown"
    assert "physical_reading_band_mm" not in row.numbers


@pytest.mark.parametrize("method", [None, "unknown", " ", [], ["Read", "unknown"]])
def test_relative_reading_still_requires_the_checks_inspection_method(method):
    bundle = relative_bundle()
    first_op(bundle)["inspection_methods"] = {"station": method}
    assert first_row(bundle).status == "unknown"


@pytest.mark.parametrize("field", ["method", "cite"])
@pytest.mark.parametrize("value", ["unknown", " ", []])
def test_unknown_or_empty_qualification_evidence_stays_unknown(field, value):
    bundle = relative_bundle()
    first_op(bundle)["inspection_readings"]["station"][field] = value
    assert first_row(bundle).status == "unknown"


@pytest.mark.parametrize("offset", [0.0, 1000.0])
def test_qualified_but_physically_unreachable_readings_still_fail(offset):
    bundle = relative_bundle()
    first_op(bundle)["inspection_readings"]["station"]["offset_mm"] = offset
    row = first_row(bundle)
    assert row.status == "error"
    assert "gauge does not span the requirement band" in row.sentence
    assert row.numbers["range_mm"] == [0.0, 300.0]


@pytest.mark.parametrize(
    ("field", "value", "status"),
    [
        ("resolution_mm", 1.0, "error"),
        ("resolution_mm", "unknown", "unknown"),
        ("range_mm", "unknown", "unknown"),
        ("verify", True, "unknown"),
    ],
)
def test_relative_reading_keeps_gauge_range_resolution_and_verification(field, value, status):
    bundle = relative_bundle()
    bundle.inventory["gauges"]["height"][field] = value
    row = first_row(bundle)
    assert row.status == status, row.sentence
    assert row.numbers["part_result"] == "not_recorded"


@pytest.mark.parametrize("kind", ["caliper", "micrometer", "depth_gauge", "dro_scale"])
def test_incompatible_instrument_does_not_gain_relative_capability(kind):
    bundle = relative_bundle()
    bundle.inventory["gauges"]["height"]["kind"] = kind
    row = first_row(bundle)
    assert row.status == "error"
    assert "relative-coordinate reading is unsupported" in row.sentence


def test_absent_reading_preserves_ordinary_station_capability():
    bundle = relative_bundle()
    del first_op(bundle)["inspection_readings"]
    row = first_row(bundle)
    assert row.status == "error"
    assert "gauge does not span" in row.sentence
    assert "inspection_reading" not in row.numbers
    assert "physical_reading_band_mm" not in row.numbers
    bundle.features["features"]["outline"]["station"] = [12.7, 13.208]
    assert first_row(replace(bundle)).status == "pass"


def test_relative_coordinate_is_not_an_offset_for_other_dimensions():
    bundle = relative_bundle()
    feature = bundle.features["features"]["outline"]
    feature.update(requirements=["depth"], depth=[12.7, 13.208])
    op = first_op(bundle)
    op["checks"] = {"depth": "height"}
    op["inspection_methods"] = {"depth": METHOD}
    op["inspection_readings"] = {"depth": deepcopy(QUALIFICATION)}
    status, message, _ = inspection.requirement_check(bundle, "outline", "depth", op)
    assert status == "error"
    assert "relative-coordinate reading is unsupported" in message


@pytest.mark.parametrize("offset", [104.0, "unknown"])
def test_go_no_go_pair_cannot_bypass_relative_reading_refusal(offset):
    bundle = relative_bundle()
    op = first_op(bundle)
    op["inspection_readings"]["station"]["offset_mm"] = offset
    op["go_no_go"] = {"station": {"go": -13.1, "no_go": -12.8}}
    row = first_row(bundle)
    assert row.status == ("unknown" if offset == "unknown" else "error")
    assert "relative-coordinate" in row.sentence


def test_capable_diameter_pair_cannot_hide_an_incompatible_relative_reading():
    bundle = relative_bundle()
    bundle.features["features"]["outline"].update(requirements=["dia"], dia=[12.7, 13.208])
    bundle.inventory["gauges"]["height"].update(kind="pin_gauge_set", sizes_mm=[12.8, 13.1])
    op = first_op(bundle)
    op["checks"] = {"dia": "height"}
    op["go_no_go"] = {"dia": {"go": 12.8, "no_go": 13.1}}
    op["inspection_readings"] = {"dia": deepcopy(QUALIFICATION)}
    status, message, _ = inspection.requirement_check(bundle, "outline", "dia", op)
    assert status == "error"
    assert "relative-coordinate reading is unsupported" in message
    del op["inspection_readings"]
    assert inspection.requirement_check(bundle, "outline", "dia", op)[0] == "pass"


def test_requirement_check_api_consumes_the_same_qualified_reading():
    bundle = relative_bundle()
    setup = bundle.plan["setups"][-4]
    status, _, nums = inspection.requirement_check(
        bundle, "outline", "station", first_op(bundle), setup=setup, workpiece="nut1"
    )
    assert status == "pass"
    assert nums["physical_reading_band_mm"] == pytest.approx([90.792, 91.3])
    assert nums["part_result"] == "not_recorded"


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
    assert row.numbers["part_result"] == "not_recorded"


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


def public_relative_plan(tmp_path, readings, *, other="other"):
    plan = write_bundle(
        tmp_path,
        {
            "outline": 'kind = "hole"\nrequirements = ["station"]\nstation = [-13.208, -12.7]\n',
            other: 'kind = "hole"\nrequirements = ["station"]\nstation = [12.7, 13.208]\n',
        },
        subject="outline",
        requirement="station",
        gauge="height_gauge",
    )
    text = plan.read_text(encoding="utf-8").replace(
        'do = "inspect"\nfeature = "outline"',
        f'do = "inspect"\nfeature = ["outline", "{other}"]',
    )
    plan.write_text(text + f"inspection_readings = {readings}\n", encoding="utf-8")
    return plan


def test_public_scoped_unknown_reading_remains_unresolved(tmp_path):
    plan = public_relative_plan(tmp_path, '{ outline = { station = "unknown" } }')
    bundle = load_bundle(plan)
    row = next(row for row in inspection.evaluate(bundle) if row.subject == "outline:station")
    assert row.status == "unknown", row.sentence
    assert "datum qualification is unresolved" in row.sentence
    assert row.numbers["inspection_reading"] == "unknown"
    assert "physical_reading_band_mm" not in row.numbers
    assert row.numbers["part_result"] == "not_recorded"


def test_public_empty_flat_reading_remains_unresolved(tmp_path):
    plan = public_relative_plan(tmp_path, "{ station = {} }")
    bundle = load_bundle(plan)
    rows = {row.subject: row for row in inspection.evaluate(bundle)}
    for subject in ("outline:station", "other:station"):
        row = rows[subject]
        assert row.status == "unknown", row.sentence
        assert "datum qualification is unresolved" in row.sentence
        assert "physical_reading_band_mm" not in row.numbers
        assert row.numbers["part_result"] == "not_recorded"


def test_public_empty_reading_does_not_hide_feature_requirement_ambiguity(tmp_path):
    plan = public_relative_plan(tmp_path, "{ station = {} }", other="station")
    with pytest.raises(BadInput, match="both a listed feature and an exported requirement"):
        load_bundle(plan)


def test_public_unknown_reading_cannot_scope_to_an_unlisted_feature(tmp_path):
    plan = public_relative_plan(tmp_path, '{ unlisted = { station = "unknown" } }')
    with pytest.raises(BadInput, match="feature the op does not list"):
        load_bundle(plan)


def test_public_requirement_key_does_not_hide_a_malformed_nested_reading(tmp_path):
    plan = public_relative_plan(
        tmp_path, '{ station = { other = { kind = "relative_coordinate" } } }'
    )
    with pytest.raises(BadInput, match="feature the op does not list"):
        load_bundle(plan)
