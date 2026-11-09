"""Small analytic oracles for the declared longitudinal-turning screen."""

import math
from pathlib import Path

import pytest

from prechips.traveler import LoadedPlan
from prechips.turning import (
    TurningError,
    _bending_factor,
    _bounding_passes,
    _feed_factor,
    _follower_factor,
    _load_config,
    check_turning_deflection,
)


def _cut(**changes):
    cut = {
        "name": "body finish",
        "phase": "finish",
        "start_z_mm": 10.0,
        "end_z_mm": 1.0,
        "start_diameter_mm": 10.508,
        "end_diameter_mm": 10.0,
        "max_radial_doc_mm": 0.254,
        "feed_mm_rev": 0.254,
        "minimum_diameter_mm": 10.0,
    }
    cut.update(changes)
    return cut


def _plan(cut=None, support=None):
    return LoadedPlan(
        data={
            "turning_material": "steel_1018",
            "setups": [
                {
                    "title": "RH end",
                    "machine_kind": "lathe",
                    "turning_support": support
                    or {"kind": "chuck_only", "chuck_z_mm": 0},
                    "operations": [
                        {
                            "cut_kind": "longitudinal_turning",
                            "turning_cuts": [cut or _cut()],
                        }
                    ],
                }
            ],
        },
        path=Path("synthetic.toml"),
        cad=None,
        parameters={},
        shop=None,
    )


def _oracle_config(tmp_path):
    path = tmp_path / "force.toml"
    path.write_text(
        "[force]\nradial_ratio=0.0\nfinish_wear=1.0\nrough_wear=1.0\n"
        "feed_factors=[[0.001,1.0],[0.060,1.0]]\n"
        "[materials.steel_1018]\nunit_power_hp_min_per_in3=1.0\n"
        "elastic_modulus_gpa=200.0\n",
        encoding="utf-8",
    )
    return path


@pytest.mark.parametrize("sign", [1, -1])
def test_known_load_cantilever_and_midspan(sign):
    # Independent closed forms: 100 N, E=200000 N/mm2, I=1000 mm4.
    force, ei = 100, 200000 * 1000
    factor, z, _ = _bending_factor(
        {"kind": "chuck_only", "chuck_z_mm": 7},
        7 + sign * 100,
        7 + sign * 20,
    )
    assert force * factor / ei == pytest.approx(1 / 6)
    assert z == 7 + sign * 100
    factor, z, _ = _bending_factor(
        {"kind": "tailstock", "chuck_z_mm": 7, "centre_z_mm": 7 + sign * 100},
        7 + sign * 80,
        7 + sign * 20,
    )
    assert force * factor / ei == pytest.approx(1 / 96)
    assert z == 7 + sign * 50


def test_tailstock_uses_actual_cut_position_not_midspan_always():
    support = {"kind": "tailstock", "chuck_z_mm": 0, "centre_z_mm": 100}
    factor, z, _ = _bending_factor(support, 10, 20)
    assert z == 20
    assert factor == pytest.approx(20**2 * 80**2 / 300)
    with pytest.raises(TurningError, match="within.*span"):
        _bending_factor(support, 10, 101)


def _follower(**changes):
    support = {
        "kind": "follower",
        "chuck_z_mm": 0,
        "centre_z_mm": 100,
        "engage_z_mm": 40,
        "offset_mm": 8,
        "pad_width_mm": 4,
    }
    support.update(changes)
    return support


def test_pre_engagement_interior_maximum_is_not_skipped():
    factor, z, state = _bending_factor(_follower(), 90, 10)
    assert z == 50
    assert factor == pytest.approx(100**3 / 48)
    assert state == "before follower engagement"


def test_pre_engagement_boundary_is_checked_on_tailstock():
    factor, z, state = _bending_factor(_follower(engage_z_mm=70), 90, 10)
    assert z == 70
    assert factor == pytest.approx(70**2 * 30**2 / 300)
    assert state == "before follower engagement"


def test_follower_span_is_chuck_to_pad_not_cantilever_gap():
    factor = _follower_factor(90, 8)
    assert factor == pytest.approx(90**2 * 8**2 / (3 * 98))
    assert factor != pytest.approx(8**3 / 3)
    assert _follower_factor(10, 8) < factor


@pytest.mark.parametrize(
    ("support", "start", "end", "message"),
    [
        (_follower(offset_mm=1), 90, 10, "pad band"),
        (_follower(engage_z_mm=85), 90, 10, "pad band"),
        (_follower(), 10, 90, "toward-chuck"),
        (_follower(engage_z_mm=5), 90, 10, "engagement within cut"),
    ],
)
def test_follower_rejects_unearned_support(support, start, end, message):
    with pytest.raises(TurningError, match=message):
        _bending_factor(support, start, end)


def test_pass_bounds_keep_actual_doc_and_diameter_together():
    assert _bounding_passes(10, 7.5, 1) == [(1, 8), (0.25, 7.5)]
    assert _bounding_passes(10, 8, 1) == [(1, 8)]
    assert _bounding_passes(10, 9, 1) == [(0.5, 9)]
    # A trillion passes remains at most two analytic candidates.
    assert len(_bounding_passes(10, 8, 1e-12)) <= 2


@pytest.mark.parametrize("end", [7.5, 6.2])
def test_two_pass_acceptance_uses_full_and_partial_oracles(tmp_path, end):
    config = _oracle_config(tmp_path)
    cut = _cut(
        start_diameter_mm=10,
        end_diameter_mm=end,
        max_radial_doc_mm=1,
        minimum_diameter_mm=10,
    )
    # Last full pass: D8, DOC1. Final pass: D=end, DOC=(8-end)/2.
    # Feed .254mm = .01in; modulus200000; L10 cantilever; no radial force.
    force_per_mm = 396000 * 0.01 / 25.4 * 4.4482216152605
    full = force_per_mm * 10**3 / (3 * 200000 * math.pi * 8**4 / 64)
    partial = (
        force_per_mm * ((8 - end) / 2) * 10**3 / (3 * 200000 * math.pi * end**4 / 64)
    )
    expected = max(full, partial)
    cut["max_deflection_mm"] = expected * 1.000001
    check_turning_deflection(_plan(cut), config)
    cut["max_deflection_mm"] = expected * 0.999999
    with pytest.raises(TurningError, match="estimated total transverse bending"):
        check_turning_deflection(_plan(cut), config)


def test_force_units_radial_resultant_and_existing_minimum_section(tmp_path):
    config = _oracle_config(tmp_path)
    # 0.01in radial DOC and feed: Fc=39.6lbf=176.149575964N.
    # Existing D5 relief, not new D10 cut, controls uniform minimum-section I.
    force = 39.6 * 4.4482216152605
    expected = force * 10**3 / (3 * 200000 * math.pi * 5**4 / 64)
    cut = _cut(minimum_diameter_mm=5, max_deflection_mm=expected * 1.000001)
    check_turning_deflection(_plan(cut), config)
    # Doubling E alone halves bending: partial overrides retain all other leaves.
    text = config.read_text(encoding="utf-8")
    config.write_text(
        text.replace("radial_ratio=0.0", "radial_ratio=1.0"), encoding="utf-8"
    )
    with pytest.raises(TurningError, match="transverse force"):
        check_turning_deflection(_plan(cut), config)
    config.write_text(
        text.replace("elastic_modulus_gpa=200.0", "elastic_modulus_gpa=400.0"),
        encoding="utf-8",
    )
    cut["max_deflection_mm"] = expected * 0.500001
    check_turning_deflection(_plan(cut), config)


def test_full_feed_table_interpolates_and_refuses_extrapolation():
    pairs = _load_config(None)["force"]["feed_factors"]
    # Values missing from the initial sparse source summary matter to results.
    assert _feed_factor(0.003, pairs) == pytest.approx(1.30)
    assert _feed_factor(0.017, pairs) == pytest.approx(0.93)
    assert _feed_factor(0.060, pairs) == pytest.approx(0.72)
    for feed in (0.0009, 0.0601):
        with pytest.raises(TurningError, match="no extrapolation"):
            _feed_factor(feed, pairs)


def test_partial_config_and_new_material(tmp_path):
    path = tmp_path / "custom.toml"
    path.write_text(
        "[limits]\nfinish_mm=0.02\n[materials.steel_1018]\n"
        "elastic_modulus_gpa=210\n[materials.custom]\n"
        "elastic_modulus_gpa=100\nunit_power_hp_min_per_in3=0.4\n",
        encoding="utf-8",
    )
    config = _load_config(path)
    assert config["limits"]["finish_mm"] == 0.02
    assert config["limits"]["rough_mm"] == 0.1
    assert config["materials"]["steel_1018"] == {
        "elastic_modulus_gpa": 210,
        "unit_power_hp_min_per_in3": 0.78,
    }
    plan = _plan()
    plan.data["turning_material"] = "custom"
    check_turning_deflection(plan, path)


@pytest.mark.parametrize(
    "text",
    [
        "[limits]\nfinish_mm=nan",
        "[force]\nrough_wear=true",
        "[force]\nradial_ratio=-1",
        "[limits]\nfinish_mmm=0.1",
        "[materials.custom]\nelastic_modulus_gpa=200",
        "[force]\nfeed_factors=[[0.01,1],[0.01,2]]",
        "[force]\nfeed_factors=[[0.02,1],[0.01,2]]",
        "[force]\nfeed_factors=[[0.01,0],[0.02,1]]",
    ],
)
def test_invalid_config_refuses_instead_of_falling_back(tmp_path, text):
    path = tmp_path / "invalid.toml"
    path.write_text(text, encoding="utf-8")
    with pytest.raises(TurningError):
        check_turning_deflection(_plan(), path)


@pytest.mark.parametrize(
    "field", ["turning_material", "machine_kind", "cut_kind", "turning_cuts"]
)
def test_missing_coverage_is_not_success(field):
    plan = _plan()
    setup = plan.data["setups"][0]
    target = (
        plan.data
        if field == "turning_material"
        else setup
        if field == "machine_kind"
        else setup["operations"][0]
    )
    del target[field]
    with pytest.raises(TurningError, match=field):
        check_turning_deflection(plan)


def test_explicit_other_needs_no_physics_data_and_pass_is_silent(capsys):
    plan = _plan()
    plan.data.pop("turning_material")
    setup = plan.data["setups"][0]
    setup.pop("turning_support")
    setup["operations"] = [{"cut_kind": "other"}]
    check_turning_deflection(plan)
    setup["machine_kind"] = "other"
    setup["operations"] = [{}]
    check_turning_deflection(plan)
    assert capsys.readouterr() == ("", "")


def test_failure_names_cut_and_pre_engagement_state():
    cut = _cut(start_z_mm=90, end_z_mm=10, max_deflection_mm=1e-9)
    with pytest.raises(TurningError) as caught:
        check_turning_deflection(_plan(cut, _follower()))
    message = str(caught.value)
    for fragment in (
        "RH end",
        "Op 10",
        "body finish",
        "before follower engagement",
        "worst Z 50",
        "transverse force",
        "limit",
        "not actual diameter error",
        "--disable-check turning_deflection",
    ):
        assert fragment in message


def test_numbering_counts_other_setups_and_other_operations():
    plan = _plan(_cut(max_deflection_mm=1e-12))
    plan.data["setups"].insert(
        0,
        {
            "title": "Bench",
            "machine_kind": "other",
            "operations": [{}, {}],
        },
    )
    plan.data["setups"][1]["operations"].insert(0, {"cut_kind": "other"})
    with pytest.raises(TurningError, match=r"setup 2 \(RH end\), Op 40"):
        check_turning_deflection(plan)


def test_current_shaft_finish_independent_hand_oracle():
    # Parent's independent handbook calculation: Ft/resultant=23.295079 N,
    # D6.35, chuck Z=-1.5, centre166, at Z152 BEFORE follower engagement.
    cut = _cut(
        start_z_mm=166,
        end_z_mm=0,
        start_diameter_mm=6.55,
        end_diameter_mm=6.35,
        max_radial_doc_mm=0.1,
        feed_mm_rev=0.05,
        minimum_diameter_mm=10,
    )
    support = _follower(
        chuck_z_mm=-1.5,
        centre_z_mm=166,
        engage_z_mm=152,
        offset_mm=8,
        pad_width_mm=10,
    )
    with pytest.raises(TurningError) as caught:
        check_turning_deflection(_plan(cut, support))
    for fragment in (
        "0.0129588 mm",
        "limit 0.005 mm",
        "23.2951 N",
        "worst Z 152 mm (before follower engagement)",
    ):
        assert fragment in str(caught.value)


def test_pad_band_can_exactly_fit_and_axis_can_be_reversed():
    support = _follower(engage_z_mm=80, offset_mm=8, pad_width_mm=4)
    expected, expected_z, state = _bending_factor(support, 90, 10)
    reversed_support = _follower(
        centre_z_mm=-100,
        engage_z_mm=-80,
        offset_mm=8,
        pad_width_mm=4,
    )
    factor, z, reverse_state = _bending_factor(reversed_support, -90, -10)
    assert factor == pytest.approx(expected)
    assert z == -expected_z
    assert reverse_state == state


def test_invalid_toml_reports_override_path(tmp_path):
    path = tmp_path / "broken-assumptions.toml"
    path.write_text("[force\n", encoding="utf-8")
    with pytest.raises(TurningError) as caught:
        check_turning_deflection(_plan(), path)
    assert str(path) in str(caught.value)
