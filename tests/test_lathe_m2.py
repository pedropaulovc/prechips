"""Declared lathe geometry, selected support and real gripping-capacity boundaries."""

from copy import deepcopy
from pathlib import Path

import pytest
from test_cli import run_cli

from prechips.findings import exit_code
from prechips.inputs import Bundle
from prechips.report import build_report, canonical_bytes
from prechips.rules import coordinates, stickout, stock_diameter, turned_profile


def bundle():
    return Bundle(
        plan={
            "part": "lathe-test",
            "features": "features.toml",
            "stock": {"form": "round_bar", "dia_mm": 12.0, "cite": "test authored blank"},
            "setups": [
                {
                    "id": "S1",
                    "machine": "lathe",
                    "frame": "T",
                    "stock_state": {"od_mm": 12.0, "north_end_z": 20.0, "south_end_z": -5.0},
                    "hold": {"fixture": "chuck", "support": "none", "stickout_mm": 20.0},
                    "ops": [
                        {"op": 10, "do": "finish_turn", "feature": "near", "tool": "turner"},
                        {"op": 20, "do": "finish_turn", "feature": "far", "tool": "turner"},
                    ],
                }
            ],
        },
        features={
            "part": "lathe-test",
            "units": "mm",
            "frames": {
                "model": {
                    "origin": [0.0, 0.0, 0.0],
                    "x": [1.0, 0.0, 0.0],
                    "y": [0.0, 1.0, 0.0],
                    "z": [0.0, 0.0, 1.0],
                    "binding": "nominal",
                },
                "T": {
                    "origin": [0.0, 0.0, 0.0],
                    "x": [1.0, 0.0, 0.0],
                    "y": [0.0, 1.0, 0.0],
                    "z": [0.0, 0.0, 1.0],
                    "binding": "nominal",
                },
            },
            "features": {
                "near": {
                    "kind": "cylinder",
                    "frame": "model",
                    "dia_nominal": 12.0,
                    "z_mm": [0.0, 10.0],
                    "cite": "test authored near diameter/stations",
                },
                "far": {
                    "kind": "cylinder",
                    "frame": "model",
                    "dia_nominal": 8.0,
                    "z_mm": [10.0, 20.0],
                    "cite": "test authored far diameter/stations",
                },
            },
        },
        inventory={
            "machines": {"lathe": {"kind": "lathe", "verify": False}},
            "fixtures": {
                "chuck": {"kind": "chuck_3jaw", "range_mm": [6.0, 14.0], "verify": False},
                "tailstock": {"kind": "tailstock", "verify": False},
                "steady": {"kind": "steady_rest", "verify": False},
            },
        },
        policy={
            "required": {"turned_profile": "*", "stickout": "*", "stock_diameter": "*"},
            "numbers": {"stickout_ld_max": 3.0},
            "numbers_cite": {"stickout_ld_max": "test shop measured L/D policy"},
        },
        cutting_data={},
        paths={},
        hashes={},
        root=Path("."),
    )


def setup(data):
    return data.plan["setups"][0]


def test_unknown_setup_frame_preserves_only_authored_local_lathe_endpoints():
    data = bundle()
    data.features["frames"]["T"] = "unknown"
    setup(data)["ops"][0].update(to_z=0.0, z_from=-2.0, z_to=1.75)
    finding = coordinates.evaluate(data)[0]
    assert finding.status == "unknown"
    rows = {row["point"]: row for row in finding.numbers["rows"]}
    for field, value in {"to_z": 0.0, "z_from": -2.0, "z_to": 1.75}.items():
        row = rows[f"op 10 {field}"]
        assert row["setup"] == ["unknown", "unknown", value]
        assert row["model"] == ["unknown"] * 3
        assert row["local_from"] == {"op": 10, "field": field, "axis": "z"}
    assert rows["drawing station 1"]["setup"] == ["unknown"] * 3
    data.features["frames"]["T"] = deepcopy(data.features["frames"]["model"])
    bound_rows = coordinates.evaluate(data)[0].numbers["rows"]
    endpoint = next(row for row in bound_rows if row["point"] == "op 10 z_to")
    assert endpoint["setup"] == [0.0, 0.0, 1.75]
    assert endpoint["model"] == [0.0, 0.0, 1.75]
    assert "local_from" not in endpoint


def long_stickout_bundle():
    data = bundle()
    setup(data)["stock_state"]["north_end_z"] = 200.0
    setup(data)["hold"]["stickout_mm"] = 200.0
    data.features["features"]["near"]["z_mm"] = [0.0, 100.0]
    data.features["features"]["far"]["z_mm"] = [100.0, 200.0]
    return data


def groove_bundle():
    data = bundle()
    data.features["features"] = {
        "shaft": {
            "kind": "cylinder",
            "frame": "model",
            "dia_nominal": 12.0,
            "z_mm": [0.0, 20.0],
            "cite": "test shaft",
        },
        "recess": {
            "kind": "groove",
            "frame": "model",
            "dia_nominal": 8.0,
            "z_mm": [5.0, 7.0],
            "cite": "test groove",
        },
    }
    setup(data)["ops"] = [{"op": 10, "do": "finish_turn", "feature": "shaft", "tool": "turner"}]
    return data


def test_profile_decreasing_and_equal_diameters_are_monotone():
    data = bundle()
    assert turned_profile.evaluate(data)[0].status == "pass"
    data.features["features"]["far"]["dia_nominal"] = 12.0
    assert turned_profile.evaluate(data)[0].status == "pass"


def test_profile_diameter_increase_needs_a_matching_grooving_operation():
    data = bundle()
    data.features["features"]["far"]["dia_nominal"] = 14.0
    finding = turned_profile.evaluate(data)[0]
    assert finding.status == "error"
    assert finding.numbers["transitions"][0]["z_mm"] == 10.0
    assert finding.numbers["transitions"][0]["from_diameter_mm"] == 12.0
    assert finding.numbers["transitions"][0]["to_diameter_mm"] == 14.0


def test_rechuck_uses_setup_spindle_direction_instead_of_model_positive_z():
    data = bundle()
    data.features["features"]["near"]["dia_nominal"] = 8.0
    data.features["features"]["far"]["dia_nominal"] = 12.0
    assert turned_profile.evaluate(data)[0].status == "error"
    data.features["frames"]["T"].update(y=[0.0, -1.0, 0.0], z=[0.0, 0.0, -1.0])
    setup(data)["stock_state"].update(north_end_z=0.0, south_end_z=-20.0)
    finding = turned_profile.evaluate(data)[0]
    assert finding.status == "pass"
    assert [(row["z_mm"], row["diameter_mm"]) for row in finding.numbers["segments"]] == [
        ([-20.0, -10.0], 12.0),
        ([-10.0, 0.0], 8.0),
    ]


def test_profile_feature_frame_is_transformed_before_ordering():
    data = bundle()
    data.features["frames"]["model"].update(
        origin=[0.0, 0.0, 20.0], y=[0.0, -1.0, 0.0], z=[0.0, 0.0, -1.0]
    )
    finding = turned_profile.evaluate(data)[0]
    assert finding.status == "error"
    assert finding.numbers["segments"][0]["features"] == ["far"]


def test_profile_hidden_behind_chuck_is_not_an_exposed_increase():
    data = bundle()
    data.features["features"]["hidden"] = {
        "kind": "cylinder",
        "frame": "model",
        "dia_nominal": 4.0,
        "z_mm": [-20.0, -10.0],
    }
    finding = turned_profile.evaluate(data)[0]
    assert finding.status == "pass"
    assert [row["feature"] for row in finding.numbers["intervals"]] == ["far", "near"]


def test_inch_profile_dimensions_and_frame_origins_convert_together():
    data = bundle()
    data.features["units"] = "in"
    for frame in data.features["frames"].values():
        frame["origin"] = [0.0, 0.0, 1.0]
    data.features["features"]["near"].update(dia_nominal=0.5, z_mm=[0.0, 0.5])
    data.features["features"]["far"].update(dia_nominal=0.25, z_mm=[0.5, 1.0])
    setup(data)["stock_state"].update(north_end_z=25.4, south_end_z=-10.0)
    setup(data)["hold"]["stickout_mm"] = 25.4
    finding = turned_profile.evaluate(data)[0]
    assert finding.status == "pass"
    assert finding.numbers["segments"][0]["z_mm"] == pytest.approx([0.0, 12.7])
    assert finding.numbers["segments"][1]["z_mm"] == pytest.approx([12.7, 25.4])
    assert [row["diameter_mm"] for row in finding.numbers["segments"]] == pytest.approx(
        [12.7, 6.35]
    )


@pytest.mark.parametrize(
    "action,expected",
    [
        ("groove", "pass"),
        ("form_relief", "pass"),
        ("finish_turn", "error"),
        ("unknown", "unknown"),
    ],
)
def test_groove_exception_requires_a_matching_declared_grooving_action(action, expected):
    data = groove_bundle()
    setup(data)["ops"].append({"op": 20, "do": action, "feature": "recess"})
    assert turned_profile.evaluate(data)[0].status == expected


@pytest.mark.parametrize("groove_before,expected", [(True, "pass"), (False, "error")])
def test_received_profile_can_use_prior_groove_but_never_a_future_setup(groove_before, expected):
    data = groove_bundle()
    first = setup(data)
    second = deepcopy(first)
    second["id"] = "S2"
    second["stock_in"] = "S1"
    data.plan["setups"].append(second)
    groove_setup = first if groove_before else second
    groove_setup["ops"].append({"op": 20, "do": "groove", "feature": "recess", "tool": "groover"})
    subject = "S2" if groove_before else "S1"
    finding = next(row for row in turned_profile.evaluate(data) if row.subject == subject)
    assert finding.status == expected
    groove_ops = finding.numbers["transitions"][0]["grooving"][0]["ops"]
    if groove_before:
        assert [(op["setup"], op["op"]) for op in groove_ops] == [("S1", 20)]
    else:
        assert groove_ops == []


def test_unrelated_grooving_operation_does_not_waive_another_recess():
    data = groove_bundle()
    data.features["features"]["other"] = {
        "kind": "groove",
        "frame": "model",
        "dia_nominal": 9.0,
        "z_mm": [12.0, 14.0],
    }
    setup(data)["ops"].append({"op": 20, "do": "groove", "feature": "other", "tool": "groover"})
    finding = turned_profile.evaluate(data)[0]
    assert finding.status == "error"
    assert [row["status"] for row in finding.numbers["transitions"]] == ["error", "pass"]


@pytest.mark.parametrize("groove_end", [10.0, 12.0])
def test_groove_does_not_waive_a_larger_outward_shoulder(groove_end):
    data = bundle()
    data.features["features"]["near"]["dia_nominal"] = 10.0
    data.features["features"]["far"]["dia_nominal"] = 12.0
    data.features["features"]["recess"] = {
        "kind": "groove",
        "frame": "model",
        "dia_nominal": 8.0,
        "z_mm": [8.0, groove_end],
    }
    setup(data)["ops"].append({"op": 30, "do": "groove", "feature": "recess", "tool": "groover"})
    finding = turned_profile.evaluate(data)[0]
    assert finding.status == "error"
    shoulder = next(
        row for row in finding.numbers["transitions"] if row["reason"] == "base_envelope"
    )
    assert shoulder["z_mm"] == 10.0
    assert shoulder["from_diameter_mm"] == 10.0
    assert shoulder["to_diameter_mm"] == 12.0
    data.features["features"]["far"]["dia_nominal"] = 10.0
    assert turned_profile.evaluate(data)[0].status == "pass"


@pytest.mark.parametrize("missing_exposure", ["stickout", "end", "absent_end"])
def test_unknown_exposure_cannot_prove_a_shoulder_error(missing_exposure):
    data = bundle()
    data.features["features"]["near"]["dia_nominal"] = 8.0
    data.features["features"]["far"]["dia_nominal"] = 12.0
    if missing_exposure == "stickout":
        setup(data)["hold"]["stickout_mm"] = "unknown"
    elif missing_exposure == "end":
        setup(data)["stock_state"]["north_end_z"] = "unknown"
    else:
        setup(data)["stock_state"].pop("south_end_z")
    finding = turned_profile.evaluate(data)[0]
    assert finding.status == "unknown"
    assert all(row["status"] != "error" for row in finding.numbers["transitions"])
    data.features["features"]["near"]["dia_nominal"] = 12.0
    data.features["features"]["far"]["dia_nominal"] = 8.0
    assert turned_profile.evaluate(data)[0].status == "pass"


@pytest.mark.parametrize(
    "change", ["nominal", "station", "frame", "binding", "axis", "gap", "unsupported_form"]
)
def test_nonrecoverable_profile_is_unknown_never_a_false_pass(change):
    data = bundle()
    feature = data.features["features"]["far"]
    if change == "nominal":
        feature.pop("dia_nominal")
        feature["dia"] = [7.9, 8.1]
    elif change == "station":
        feature["z_mm"][1] = "unknown"
    elif change == "frame":
        data.features["frames"]["T"]["origin"] = "unknown"
    elif change == "binding":
        data.features["frames"]["T"]["binding"] = "unknown"
    elif change == "axis":
        feature["axis"] = [1.0, 0.0, 0.0]
    elif change == "gap":
        feature["z_mm"][0] = 11.0
    else:
        feature["kind"] = "spherical_dome"
        setup(data)["ops"][1]["do"] = "form_dome"
    assert turned_profile.evaluate(data)[0].status == "unknown"


@pytest.mark.parametrize(
    "units,nominal,expected", [("mm", 6.35, 6.35), ("in", 0.25, 6.35), ("unknown", 0.25, "unknown")]
)
def test_nominal_diameter_uses_explicit_units_and_never_a_band_midpoint(units, nominal, expected):
    data = bundle()
    data.features["units"] = units
    assert turned_profile.nominal_diameter(data, {"nominal_dia": nominal}) == expected
    assert turned_profile.nominal_diameter(data, {"dia": [nominal, nominal + 0.1]}) == "unknown"
    assert (
        turned_profile.nominal_diameter(data, {"dia_nominal": "unknown", "dia": nominal})
        == "unknown"
    )


def test_stickout_finished_exposed_diameter_refuses_slender_section_in_large_bar():
    data = bundle()
    setup(data)["stock_state"].update(od_mm=20.0, north_end_z=40.0)
    setup(data)["hold"]["stickout_mm"] = 40.0
    data.policy["numbers"]["stickout_ld_max"] = 4.0
    data.features["features"]["near"].update(dia_nominal=6.0, z_mm=[0.0, 20.0])
    data.features["features"]["far"].update(dia_nominal=6.0, z_mm=[20.0, 40.0])
    finding = stickout.evaluate(data)[0]
    assert finding.status == "error"
    assert finding.numbers["diameter_mm"] == 6.0
    assert finding.numbers["unsupported_limit_mm"] == 24.0
    assert finding.numbers["diameter_features"] == ["far", "near"]
    assert finding.numbers["exposed_z_mm"] == [0.0, 40.0]
    assert "test authored near diameter/stations" in finding.cite
    assert "test authored far diameter/stations" in finding.cite
    assert exit_code([finding], data.policy, data) == 2


@pytest.mark.parametrize("diameter", [1.0, "unknown", [0.9, 1.1]])
def test_stickout_hidden_diameter_does_not_control_exposed_limit(diameter):
    data = bundle()
    data.features["features"]["hidden"] = {
        "kind": "cylinder",
        "frame": "model",
        "dia_nominal": diameter,
        "z_mm": [-20.0, -10.0],
        "cite": "test authored hidden diameter/stations",
    }
    finding = stickout.evaluate(data)[0]
    assert finding.status == "pass"
    assert finding.numbers["diameter_mm"] == 8.0
    assert finding.numbers["unsupported_limit_mm"] == 24.0
    assert finding.numbers["diameter_features"] == ["far"]
    assert "test authored hidden diameter/stations" not in finding.cite


@pytest.mark.parametrize(
    "change",
    [
        "nominal",
        "band",
        "station",
        "frame",
        "binding",
        "axis",
        "gap",
        "near_end_gap",
        "far_end_gap",
        "empty_profile",
        "missing_span",
        "units",
        "overlap",
        "unsupported_form",
    ],
)
def test_stickout_unresolved_exposed_geometry_never_uses_held_bar_to_pass(change):
    data = bundle()
    feature = data.features["features"]["far"]
    if change == "nominal":
        feature["dia_nominal"] = "unknown"
    elif change == "band":
        feature.pop("dia_nominal")
        feature["dia"] = [7.9, 8.1]
    elif change == "station":
        feature["z_mm"][1] = "unknown"
    elif change == "frame":
        data.features["frames"]["T"]["origin"] = "unknown"
    elif change == "binding":
        data.features["frames"]["T"]["binding"] = "unknown"
    elif change == "axis":
        feature["axis"] = [1.0, 0.0, 0.0]
    elif change == "gap":
        feature["z_mm"][0] = 11.0
    elif change == "near_end_gap":
        data.features["features"]["near"]["z_mm"][0] = 1.0
    elif change == "far_end_gap":
        feature["z_mm"][1] = 19.0
    elif change == "empty_profile":
        data.features["features"] = {}
        setup(data)["ops"] = []
    elif change == "missing_span":
        setup(data)["stock_state"].pop("north_end_z")
    elif change == "units":
        data.features["units"] = "unknown"
    elif change == "overlap":
        data.features["features"]["near"]["z_mm"][1] = 11.0
    else:
        feature["kind"] = "spherical_dome"
        setup(data)["ops"][1]["do"] = "form_dome"
    finding = stickout.evaluate(data)[0]
    assert finding.status == "unknown"
    assert finding.numbers["diameter_mm"] == "unknown"
    assert finding.numbers["unsupported_limit_mm"] == "unknown"
    assert exit_code([finding], data.policy, data) == 4


def test_stickout_groove_is_finished_minimum_not_parent_envelope():
    data = groove_bundle()
    data.features["features"]["recess"]["dia_nominal"] = 6.0
    setup(data)["ops"].append({"op": 20, "do": "groove", "feature": "recess"})
    finding = stickout.evaluate(data)[0]
    assert finding.status == "error"
    assert finding.numbers["diameter_mm"] == 6.0
    assert finding.numbers["unsupported_limit_mm"] == 18.0
    assert finding.numbers["diameter_features"] == ["recess"]
    assert "test groove" in finding.cite


def test_stickout_transformed_inch_span_excludes_hidden_smaller_diameter():
    data = bundle()
    data.features["units"] = "in"
    data.features["frames"]["model"]["origin"] = [0.0, 0.0, 2.0]
    data.features["frames"]["T"].update(
        origin=[0.0, 0.0, 3.0], y=[0.0, -1.0, 0.0], z=[0.0, 0.0, -1.0]
    )
    data.features["features"]["near"].update(dia_nominal=0.5, z_mm=[0.0, 0.5])
    data.features["features"]["far"].update(dia_nominal=0.25, z_mm=[0.5, 1.0])
    data.features["features"]["hidden"] = {
        "kind": "cylinder",
        "frame": "model",
        "dia_nominal": 0.125,
        "z_mm": [1.0, 1.5],
    }
    setup(data)["stock_state"].update(od_mm=20.0, north_end_z=25.4, south_end_z=-10.0)
    setup(data)["hold"]["stickout_mm"] = 25.4
    data.policy["numbers"]["stickout_ld_max"] = 4.0
    finding = stickout.evaluate(data)[0]
    assert finding.status == "pass"
    assert finding.numbers["diameter_mm"] == pytest.approx(6.35)
    assert finding.numbers["unsupported_limit_mm"] == pytest.approx(25.4)
    assert finding.numbers["exposed_z_mm"] == pytest.approx([0.0, 25.4])
    assert finding.numbers["diameter_features"] == ["far"]
    setup(data)["hold"]["stickout_mm"] = 25.5
    setup(data)["stock_state"]["north_end_z"] = 25.5
    data.features["features"]["near"]["z_mm"][0] = -0.1
    assert stickout.evaluate(data)[0].status == "error"


@pytest.mark.parametrize(
    "length,expected", [(24.0, "pass"), (24.1, "error"), ("unknown", "unknown"), (-1.0, "unknown")]
)
def test_stickout_inclusive_policy_boundary_and_unknown_length(length, expected):
    data = bundle()
    data.features["features"]["far"]["z_mm"][1] = 50.0
    setup(data)["stock_state"]["north_end_z"] = 50.0
    setup(data)["hold"]["stickout_mm"] = length
    finding = stickout.evaluate(data)[0]
    assert finding.status == expected
    assert finding.numbers["unsupported_limit_mm"] == (
        24.0 if isinstance(length, float) and length >= 0 else "unknown"
    )
    assert "test shop measured L/D policy" in finding.cite


_FIT = {"measure": "trial-fit scribe to the plain end", "nominal_mm": 16.0, "add_mm": 8.0}


@pytest.mark.parametrize(
    ("fit", "length", "expected"),
    [
        (_FIT, 24.0, "pass"),
        # The printed stickout must be the fit-up nominal plus the jaw allowance.
        (_FIT, 23.0, "error"),
        ({**_FIT, "add_mm": 7.0}, 24.0, "error"),
        ({**_FIT, "nominal_mm": "unknown"}, 24.0, "unknown"),
        ({**_FIT, "measure": "unknown"}, 24.0, "unknown"),
        ({**_FIT, "measure": " "}, 24.0, "unknown"),
    ],
)
def test_a_stickout_set_from_a_measured_fit_up_is_its_nominal_plus_the_allowance(
    fit, length, expected
):
    data = bundle()
    data.features["features"]["far"]["z_mm"][1] = 50.0
    setup(data)["stock_state"]["north_end_z"] = 50.0
    setup(data)["hold"]["stickout_mm"] = length
    setup(data)["hold"]["stickout_fit"] = fit
    finding = stickout.evaluate(data)[0]
    assert finding.status == expected
    assert ("stickout_fit" in finding.sentence) == (expected != "pass")


def test_zero_stickout_preserves_policy_debt_and_verified_support_exception():
    data = bundle()
    setup(data)["hold"]["stickout_mm"] = 0.0
    assert stickout.evaluate(data)[0].status == "pass"
    data.policy["numbers_verify"] = {"stickout_ld_max": True}
    assert stickout.evaluate(data)[0].status == "unknown"
    setup(data)["hold"]["support"] = "tailstock"
    assert stickout.evaluate(data)[0].status == "pass"


@pytest.mark.parametrize("support", ["tailstock", "steady"])
def test_selected_verified_fixture_support_excuses_long_stickout(support):
    data = long_stickout_bundle()
    setup(data)["hold"].update(stickout_mm=200.0, support=support)
    assert stickout.evaluate(data)[0].status == "pass"
    data.inventory["fixtures"][support]["verify"] = True
    assert stickout.evaluate(data)[0].status == "unknown"


def test_machine_accessory_support_must_belong_to_selected_machine_and_be_verified():
    data = long_stickout_bundle()
    setup(data)["hold"].update(stickout_mm=200.0, support="dead_centre_tailstock_mt3")
    data.inventory["machines"]["other"] = {
        "kind": "lathe",
        "standard_accessories": ["dead_centre_tailstock_mt3"],
        "verify": False,
    }
    assert stickout.evaluate(data)[0].status == "unknown"
    data.inventory["machines"]["lathe"]["standard_accessories"] = ["dead_centre_tailstock_mt3"]
    assert stickout.evaluate(data)[0].status == "pass"
    data.inventory["machines"]["lathe"]["verify"] = True
    assert stickout.evaluate(data)[0].status == "unknown"


@pytest.mark.parametrize(
    "selected_verify,other_verify,expected", [(False, True, "pass"), (True, False, "unknown")]
)
def test_duplicate_accessory_names_use_selected_machine_verification(
    selected_verify, other_verify, expected
):
    data = long_stickout_bundle()
    setup(data)["hold"].update(stickout_mm=200.0, support="dead_centre_tailstock_mt3")
    data.inventory["machines"] = {
        "other": {
            "kind": "lathe",
            "standard_accessories": ["dead_centre_tailstock_mt3"],
            "verify": other_verify,
        },
        "lathe": {
            "kind": "lathe",
            "standard_accessories": ["dead_centre_tailstock_mt3"],
            "verify": selected_verify,
        },
    }
    assert stickout.evaluate(data)[0].status == expected


def test_explicit_absent_fixture_is_not_resurrected_by_machine_accessory_listing():
    data = long_stickout_bundle()
    setup(data)["hold"].update(stickout_mm=200.0, support="tailstock")
    data.inventory["fixtures"]["tailstock"]["present"] = False
    data.inventory["machines"]["lathe"]["standard_accessories"] = ["tailstock"]
    assert stickout.evaluate(data)[0].status == "unknown"


def test_inventory_presence_without_selected_support_does_not_excuse_stickout():
    data = long_stickout_bundle()
    setup(data)["hold"]["stickout_mm"] = 200.0
    assert stickout.evaluate(data)[0].status == "error"
    setup(data)["hold"].pop("support")
    assert stickout.evaluate(data)[0].status == "unknown"


def test_support_reference_list_can_select_verified_steady_rest():
    data = long_stickout_bundle()
    setup(data)["hold"].update(stickout_mm=200.0, supports=[{"ref": "steady", "note": "installed"}])
    assert stickout.evaluate(data)[0].status == "pass"


def test_headstock_centre_or_non_support_fixture_does_not_supply_exception():
    data = long_stickout_bundle()
    data.inventory["fixtures"]["headstock-centre"] = {"kind": "dead_centre", "verify": False}
    setup(data)["hold"].update(stickout_mm=200.0, support="headstock-centre")
    assert stickout.evaluate(data)[0].status == "error"


@pytest.mark.parametrize("change", ["missing", "unknown", "uncited", "verify", "verify_unknown"])
def test_unresolved_policy_ratio_does_not_invent_a_limit(change):
    data = bundle()
    if change == "missing":
        data.policy.pop("numbers")
    elif change == "unknown":
        data.policy["numbers"]["stickout_ld_max"] = "unknown"
    elif change == "uncited":
        data.policy.pop("numbers_cite")
    else:
        data.policy["numbers_verify"] = {
            "stickout_ld_max": True if change == "verify" else "unknown"
        }
    finding = stickout.evaluate(data)[0]
    assert finding.status == "unknown"
    assert finding.numbers["unsupported_limit_mm"] == "unknown"


def test_held_od_controls_grip_but_finished_diameter_controls_stickout():
    data = bundle()
    data.plan["stock"]["dia_mm"] = 30.0
    setup(data)["stock_state"]["od_mm"] = 6.0
    data.features["features"]["far"]["dia_nominal"] = 6.0
    setup(data)["hold"]["stickout_mm"] = 20.0
    assert stickout.evaluate(data)[0].status == "error"
    assert stock_diameter.evaluate(data)[0].status == "pass"
    setup(data)["stock_state"].pop("od_mm")
    finding = stickout.evaluate(data)[0]
    assert finding.status == "error"
    assert finding.numbers["diameter_mm"] == 6.0
    assert finding.numbers["held_diameter_mm"] == 30.0
    assert stock_diameter.evaluate(data)[0].status == "error"
    setup(data)["stock_state"]["od_mm"] = "unknown"
    assert stickout.evaluate(data)[0].status == "unknown"
    assert stock_diameter.evaluate(data)[0].status == "unknown"


@pytest.mark.parametrize("diameter", [0.0, -6.0, "unknown"])
def test_nonpositive_or_unknown_held_od_is_not_replaced_by_the_blank(diameter):
    data = bundle()
    setup(data)["stock_state"]["od_mm"] = diameter
    assert stickout.evaluate(data)[0].status == "unknown"
    assert stock_diameter.evaluate(data)[0].status == "unknown"


def test_unknown_stock_state_and_unverified_fallback_stock_remain_unknown():
    data = bundle()
    setup(data)["stock_state"] = "unknown"
    assert stickout.evaluate(data)[0].status == "unknown"
    assert stock_diameter.evaluate(data)[0].status == "unknown"
    setup(data)["stock_state"] = {}
    data.plan["stock"]["form_verify"] = True
    assert stickout.evaluate(data)[0].status == "unknown"
    assert stock_diameter.evaluate(data)[0].status == "unknown"


@pytest.mark.parametrize(
    "diameter,expected", [(6.0, "pass"), (14.0, "pass"), (5.9, "error"), (14.1, "error")]
)
def test_chuck_actual_gripping_range_is_inclusive(diameter, expected):
    data = bundle()
    setup(data)["stock_state"]["od_mm"] = diameter
    assert stock_diameter.evaluate(data)[0].status == expected


@pytest.mark.parametrize(
    "capacity,diameter,expected",
    [
        ({"sizes_mm": [6.0, 8.0]}, 6.0, "pass"),
        ({"sizes_mm": [6.0, 8.0]}, 7.0, "error"),
        ({"sizes_in": {"imperial": ["1/4", "3/8"]}}, 6.35, "pass"),
        ({"range_in": [0.25, 0.5]}, 12.7, "pass"),
        ({"range_in": [0.25, 0.5]}, 12.8, "error"),
        ({"range_mm": "unknown"}, 6.0, "unknown"),
        ({"range_mm": 14.0}, 6.0, "unknown"),
    ],
)
def test_stock_diameter_uses_declared_sizes_or_explicit_two_endpoint_range(
    capacity, diameter, expected
):
    data = bundle()
    setup(data)["hold"]["fixture"] = "collets"
    setup(data)["stock_state"]["od_mm"] = diameter
    data.inventory["holders"] = {"collets": {"kind": "collet_set", "verify": False, **capacity}}
    assert stock_diameter.evaluate(data)[0].status == expected


# A member is the same collet whether the plan names it bare or with its category.
SPELLINGS = pytest.mark.parametrize("spelling", ["", "holders."])


@SPELLINGS
def test_selected_collet_member_restricts_capacity_to_that_member(spelling):
    data = bundle()
    setup(data)["hold"]["fixture"] = spelling + "collets/8mm"
    setup(data)["stock_state"]["od_mm"] = 6.0
    data.inventory["holders"] = {
        "collets": {"kind": "collet_set", "sizes_mm": [6.0, 8.0], "verify": False}
    }
    assert stock_diameter.evaluate(data)[0].status == "error"
    setup(data)["stock_state"]["od_mm"] = 8.0
    assert stock_diameter.evaluate(data)[0].status == "pass"


@SPELLINGS
@pytest.mark.parametrize(
    "member,diameter,expected",
    [
        ("3-8in", 9.525, "pass"),
        ("1/4", 6.35, "pass"),
        # The set also holds 1/2 in, but the selected 1/4 in collet cannot.
        ("1/4", 12.7, "error"),
        ("1-4in", 12.7, "error"),
    ],
)
def test_selected_inch_collet_holds_only_its_own_size(spelling, member, diameter, expected):
    data = bundle()
    setup(data)["hold"]["fixture"] = f"{spelling}collets/{member}"
    setup(data)["stock_state"]["od_mm"] = diameter
    data.inventory["holders"] = {
        "collets": {"kind": "collet_set", "sizes_in": ["1/4", "3/8", "1/2"], "verify": False}
    }
    finding = stock_diameter.evaluate(data)[0]
    assert finding.status == expected
    member_mm = 9.525 if member == "3-8in" else 6.35
    assert finding.numbers["sizes_mm"] == [pytest.approx(member_mm)]


@SPELLINGS
@pytest.mark.parametrize("diameter,expected", [(6.0, "error"), (7.8, "pass"), (8.5, "error")])
def test_selected_explicit_member_does_not_inherit_parent_set_sizes(spelling, diameter, expected):
    data = bundle()
    setup(data)["hold"]["fixture"] = spelling + "collets/selected"
    setup(data)["stock_state"]["od_mm"] = diameter
    data.inventory["holders"] = {
        "collets": {
            "kind": "collet_set",
            "sizes_mm": [6.0, 8.0],
            "verify": False,
            "members": {"selected": {"kind": "collet", "range_mm": [7.5, 8.0]}},
        }
    }
    assert stock_diameter.evaluate(data)[0].status == expected


@pytest.mark.parametrize(
    "diameter,present,capacity,expected",
    [
        (12.0, True, [6.0, 14.0], "pass"),
        (15.0, True, [6.0, 14.0], "error"),
        (12.0, True, None, "unknown"),
        (12.0, "unknown", [6.0, 14.0], "unknown"),
        (15.0, "unknown", [6.0, 14.0], "unknown"),
    ],
)
def test_collet_chuck_checks_real_capacity_and_preserves_presence_debt(
    diameter, present, capacity, expected
):
    data = bundle()
    setup(data)["stock_state"]["od_mm"] = diameter
    fixture = {"kind": "collet_chuck", "verify": False, "present": present}
    if capacity is not None:
        fixture["range_mm"] = capacity
    data.inventory["fixtures"]["chuck"] = fixture
    assert stock_diameter.evaluate(data)[0].status == expected


def test_exterior_chuck_diameter_is_not_a_gripping_range():
    data = bundle()
    data.inventory["fixtures"]["chuck"] = {
        "kind": "chuck_3jaw",
        "diameter_in": 6.0,
        "verify": False,
    }
    assert stock_diameter.evaluate(data)[0].status == "unknown"


def test_machine_accessory_chuck_without_declared_capacity_is_unknown():
    data = bundle()
    data.inventory["fixtures"].pop("chuck")
    data.inventory["machines"]["lathe"]["standard_accessories"] = ["chuck"]
    assert stock_diameter.evaluate(data)[0].status == "unknown"


@pytest.mark.parametrize(
    "uncertainty",
    [{"verify": True}, {"verify": "unknown"}, {"present": "unknown"}, {"source": {"verify": True}}],
)
def test_unverified_capacity_cannot_prove_fit_or_mismatch(uncertainty):
    data = bundle()
    setup(data)["stock_state"]["od_mm"] = 30.0
    data.inventory["fixtures"]["chuck"].update(uncertainty)
    assert stock_diameter.evaluate(data)[0].status == "unknown"


def test_lathe_family_report_is_repeatable_without_mutating_input_bundle():
    data = groove_bundle()
    setup(data)["ops"].append({"op": 20, "do": "groove", "feature": "recess", "tool": "groover"})
    original = deepcopy((data.plan, data.features, data.inventory, data.policy))

    def report():
        findings = (
            turned_profile.evaluate(data) + stickout.evaluate(data) + stock_diameter.evaluate(data)
        )
        return canonical_bytes(build_report(data, findings))

    assert report() == report()
    assert original == (data.plan, data.features, data.inventory, data.policy)


def test_required_unknown_and_error_exit_precedence():
    data = bundle()
    findings = (
        turned_profile.evaluate(data) + stickout.evaluate(data) + stock_diameter.evaluate(data)
    )
    assert exit_code(findings, data.policy, data) == 0
    data.inventory["fixtures"]["chuck"].pop("range_mm")
    findings = (
        turned_profile.evaluate(data) + stickout.evaluate(data) + stock_diameter.evaluate(data)
    )
    assert exit_code(findings, data.policy, data) == 4
    data.policy["required"].pop("stock_diameter")
    assert exit_code(findings, data.policy, data) == 0
    setup(data)["hold"]["stickout_mm"] = 200.0
    data.features["features"]["near"]["z_mm"][0] = -180.0
    findings = (
        turned_profile.evaluate(data) + stickout.evaluate(data) + stock_diameter.evaluate(data)
    )
    assert exit_code(findings, data.policy, data) == 2


def test_bad_stickout_input_exits_three_without_writing_a_report(tmp_path):
    plan = tmp_path / "plan.toml"
    plan.write_text(
        'part = "lathe-test"\nfeatures = "features.toml"\n'
        '[[setups]]\nid = "S1"\nmachine = "lathe"\n'
        '[setups.hold]\nstickout_mm = "too long"\n'
        '[[setups.ops]]\nop = 10\ndo = "finish_turn"\n',
        encoding="utf-8",
    )
    out = tmp_path / "out"
    result = run_cli("check", plan, "--out", out)
    assert result.returncode == 3
    assert not out.exists()
