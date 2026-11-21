"""Small analytic oracles for the declared longitudinal-turning screen."""

import math
from pathlib import Path

import pytest

from prechips.traveler import LoadedPlan
from prechips.turning import (
    TurningError,
    _bending_factor,
    _follower_factor,
    _stepped_bending,
    check_turning_deflection,
    load_config,
    table_factor,
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
    cut.setdefault("kept_start_z_mm", cut["start_z_mm"])
    cut.setdefault("kept_end_z_mm", cut["end_z_mm"])
    return cut


def _whole(support, start, end):
    return _bending_factor(support, start, end, (start, end))


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
        shop_data={},
    )


def _oracle_config(tmp_path):
    path = tmp_path / "force.toml"
    path.write_text(
        "[limits]\nfinish_mm=1.0\n"
        "[force]\nradial_ratio=1.0\nfinish_wear=1.0\nrough_wear=1.0\n"
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
    factor, z, _ = _whole(
        {"kind": "chuck_only", "chuck_z_mm": 7},
        7 + sign * 100,
        7 + sign * 20,
    )
    assert force * factor / ei == pytest.approx(1 / 6)
    assert z == 7 + sign * 100
    factor, z, _ = _whole(
        {"kind": "tailstock", "chuck_z_mm": 7, "centre_z_mm": 7 + sign * 100},
        7 + sign * 80,
        7 + sign * 20,
    )
    assert force * factor / ei == pytest.approx(1 / 96)
    assert z == 7 + sign * 50


def test_tailstock_uses_actual_cut_position_not_midspan_always():
    support = {"kind": "tailstock", "chuck_z_mm": 0, "centre_z_mm": 100}
    factor, z, _ = _whole(support, 10, 20)
    assert z == 20
    assert factor == pytest.approx(20**2 * 80**2 / 300)
    with pytest.raises(TurningError, match="within.*span"):
        _whole(support, 10, 101)


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
    factor, z, state = _whole(_follower(), 90, 10)
    assert z == 50
    assert factor == pytest.approx(100**3 / 48)
    assert state == "before follower engagement"


def test_pre_engagement_boundary_is_checked_on_tailstock():
    factor, z, state = _whole(_follower(engage_z_mm=70), 90, 10)
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
        _whole(support, start, end)


def test_uneven_pass_order_cannot_escape_final_diameter_bound(tmp_path):
    config = _oracle_config(tmp_path)
    cut = _cut(
        start_diameter_mm=10,
        end_diameter_mm=7.5,
        max_radial_doc_mm=1,
        minimum_diameter_mm=10,
    )
    # Valid radial schedule .25 then 1 reaches D7.5 with a full-depth last pass.
    # MAX DOC does not mandate the weaker greedy schedule 1 then .25.
    # Feed .254mm = .01in; modulus200000; L10 cantilever; no radial force.
    force_per_mm = 396000 * 0.01 / 25.4 * 4.4482216152605
    expected = force_per_mm * 10**3 / (3 * 200000 * math.pi * 7.5**4 / 64)
    cut["max_deflection_mm"] = expected * 1.000001
    check_turning_deflection(_plan(cut), load_config(config))
    cut["max_deflection_mm"] = expected * 0.999999
    with pytest.raises(TurningError, match="estimated radial bending"):
        check_turning_deflection(_plan(cut), load_config(config))


def test_force_units_radial_ratio_and_existing_minimum_section(tmp_path):
    config = _oracle_config(tmp_path)
    # 0.01in radial DOC and feed: Ft=39.6lbf=176.149575964N; Fr=Ft at ratio 1.
    # Existing D5 relief, not new D10 cut, controls uniform minimum-section I.
    force = 39.6 * 4.4482216152605
    expected = force * 10**3 / (3 * 200000 * math.pi * 5**4 / 64)
    cut = _cut(minimum_diameter_mm=5, max_deflection_mm=expected * 1.000001)
    check_turning_deflection(_plan(cut), load_config(config))
    # Only the radial component bends toward the tool: doubling the ratio fails.
    text = config.read_text(encoding="utf-8")
    config.write_text(
        text.replace("radial_ratio=1.0", "radial_ratio=2.0"), encoding="utf-8"
    )
    with pytest.raises(TurningError, match="radial force"):
        check_turning_deflection(_plan(cut), load_config(config))
    config.write_text(
        text.replace("elastic_modulus_gpa=200.0", "elastic_modulus_gpa=400.0"),
        encoding="utf-8",
    )
    cut["max_deflection_mm"] = expected * 0.500001
    check_turning_deflection(_plan(cut), load_config(config))


def test_full_feed_table_interpolates_and_refuses_extrapolation():
    pairs = load_config(None)["force"]["feed_factors"]

    def factor(feed):
        return table_factor(feed, pairs, "feed", "in/rev", "feed-factor")

    # Values missing from the initial sparse source summary matter to results.
    assert factor(0.003) == pytest.approx(1.30)
    assert factor(0.017) == pytest.approx(0.93)
    assert factor(0.060) == pytest.approx(0.72)
    for feed in (0.0009, 0.0601):
        with pytest.raises(TurningError, match="no extrapolation"):
            factor(feed)


def test_partial_config_and_new_material(tmp_path):
    path = tmp_path / "custom.toml"
    path.write_text(
        "[limits]\nfinish_mm=0.02\n[materials.steel_1018]\n"
        "elastic_modulus_gpa=210\n[materials.custom]\n"
        "elastic_modulus_gpa=100\nunit_power_hp_min_per_in3=0.4\n",
        encoding="utf-8",
    )
    config = load_config(path)
    assert config["limits"]["finish_mm"] == 0.02
    assert config["limits"]["rough_mm"] == 0.1
    assert config["materials"]["steel_1018"] == {
        "elastic_modulus_gpa": 210,
        "unit_power_hp_min_per_in3": 0.78,
        "drill_kd": 24000.0,
    }
    plan = _plan()
    plan.data["turning_material"] = "custom"
    check_turning_deflection(plan, load_config(path))


@pytest.mark.parametrize(
    "text",
    [
        "[limits]\nfinish_mm=nan",
        "[force]\nrough_wear=true",
        "[force]\nradial_ratio=-1",
        "[force]\nradial_ratio=0",
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
        check_turning_deflection(_plan(), load_config(path))


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
        check_turning_deflection(plan, load_config(None))


def test_explicit_other_needs_no_physics_data_and_pass_is_silent(capsys):
    plan = _plan()
    plan.data.pop("turning_material")
    setup = plan.data["setups"][0]
    setup.pop("turning_support")
    setup["operations"] = [{"cut_kind": "other"}]
    check_turning_deflection(plan, load_config(None))
    setup["machine_kind"] = "other"
    setup["operations"] = [{}]
    check_turning_deflection(plan, load_config(None))
    assert capsys.readouterr() == ("", "")


def test_failure_names_cut_and_pre_engagement_state():
    cut = _cut(start_z_mm=90, end_z_mm=10, max_deflection_mm=1e-9)
    with pytest.raises(TurningError) as caught:
        check_turning_deflection(_plan(cut, _follower()), load_config(None))
    message = str(caught.value)
    for fragment in (
        "RH end",
        "Op 10",
        "body finish",
        "before follower engagement",
        "at Z 50",
        "radial force",
        "limit",
        "not measured diameter error",
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
        check_turning_deflection(plan, load_config(None))


def test_current_shaft_finish_independent_hand_oracle():
    # Parent's independent handbook calculation: Ft=Fr=16.4721 N, D6.35,
    # chuck Z=-1.5, centre166, kept body to Z156.25, at Z152 BEFORE follower
    # engagement. The kept range still reaches past engagement, so the
    # refusal stands with identical kept and whole-traverse maxima.
    cut = _cut(
        start_z_mm=166,
        end_z_mm=0,
        kept_start_z_mm=156.25,
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
        check_turning_deflection(_plan(cut, support), load_config(None))
    for fragment in (
        "0.00916328 mm (about 0.0183266 mm on diameter)",
        "limit 0.005 mm at Z 152 mm (before follower engagement)",
        "over kept Z 156.25..0 mm; whole traverse 0.00916328 mm at Z 152 mm",
        "radial force 16.4721 N, tangential 16.4721 N",
    ):
        assert fragment in str(caught.value)


def test_kept_range_bounds_the_maximum_not_the_support_checks():
    chuck = {"kind": "chuck_only", "chuck_z_mm": 0}
    # Sacrificial stub beyond Z5 is traversed but not held to the limit.
    factor, z, _ = _bending_factor(chuck, 10, 1, (5, 1))
    assert (factor, z) == (5**3 / 3, 5)
    assert _bending_factor(chuck, 10, 1, (5, 1)) == _bending_factor(
        chuck, 10, 1, (1, 5)
    )
    with pytest.raises(TurningError, match="kept range must lie within"):
        _bending_factor(chuck, 10, 1, (11, 1))
    # A narrowed range never relaxes traverse validity: the cut still crosses.
    with pytest.raises(TurningError, match="crosses chuck"):
        _bending_factor(chuck, 10, -1, (5, 1))
    # Tailstock: the maximum moves to the kept end nearest midspan.
    support = {"kind": "tailstock", "chuck_z_mm": 0, "centre_z_mm": 100}
    factor, z, _ = _bending_factor(support, 90, 10, (90, 70))
    assert z == 70
    assert factor == pytest.approx(70**2 * 30**2 / 300)


def test_kept_range_entirely_after_follower_engagement_uses_pad_support():
    support = _follower()
    factor, z, state = _bending_factor(support, 90, 10, (30, 10))
    assert (z, state) == (30, "follower engaged")
    assert factor == pytest.approx(30**2 * 8**2 / (3 * 38))
    # Straddling engagement keeps the pre-engagement interior maximum.
    factor, z, state = _bending_factor(support, 90, 10, (60, 10))
    assert (z, state) == (50, "before follower engagement")
    assert factor == pytest.approx(100**3 / 48)


def test_refusal_reports_kept_and_whole_traverse_maxima(tmp_path):
    config = _oracle_config(tmp_path)
    cut = _cut(start_z_mm=10, end_z_mm=1, kept_start_z_mm=5, max_deflection_mm=1e-9)
    with pytest.raises(TurningError) as caught:
        check_turning_deflection(_plan(cut), load_config(config))
    message = str(caught.value)
    assert "at Z 5 mm (chuck only) over kept Z 5..1 mm; whole traverse" in message
    assert "at Z 10 mm (chuck only)" in message
    # Narrowing to the kept stub-free region passes under the same limit that
    # the whole traverse exceeds.
    limit = 176.149575964 * 5**3 / (3 * 200000 * math.pi * 10**4 / 64) * 1.000001
    check_turning_deflection(
        _plan(
            _cut(start_z_mm=10, end_z_mm=1, kept_start_z_mm=5, max_deflection_mm=limit)
        ),
        load_config(config),
    )
    with pytest.raises(TurningError, match="at Z 10 mm"):
        check_turning_deflection(
            _plan(_cut(start_z_mm=10, end_z_mm=1, max_deflection_mm=limit)),
            load_config(config),
        )


@pytest.mark.parametrize("field", ["kept_start_z_mm", "kept_end_z_mm"])
def test_kept_range_is_mandatory_not_defaulted(field):
    # The author must state the retained extent; nothing is assumed from the
    # traverse, even where the whole traverse would pass.
    cut = _cut(max_deflection_mm=1.0)
    del cut[field]
    with pytest.raises(TurningError, match=f"{field}: expected a finite number"):
        check_turning_deflection(_plan(cut), load_config(None))


def test_pad_band_can_exactly_fit_and_axis_can_be_reversed():
    support = _follower(engage_z_mm=80, offset_mm=8, pad_width_mm=4)
    expected, expected_z, state = _whole(support, 90, 10)
    reversed_support = _follower(
        centre_z_mm=-100,
        engage_z_mm=-80,
        offset_mm=8,
        pad_width_mm=4,
    )
    factor, z, reverse_state = _whole(reversed_support, -90, -10)
    assert factor == pytest.approx(expected)
    assert z == -expected_z
    assert reverse_state == state


def test_invalid_toml_reports_override_path(tmp_path):
    path = tmp_path / "broken-assumptions.toml"
    path.write_text("[force\n", encoding="utf-8")
    with pytest.raises(TurningError) as caught:
        check_turning_deflection(_plan(), load_config(path))
    assert str(path) in str(caught.value)


def test_per_cut_limit_only_tightens_but_config_can_raise_limit(tmp_path):
    plan = _plan(_cut(start_z_mm=50, max_deflection_mm=1.0))
    with pytest.raises(TurningError, match="limit 0.005 mm"):
        check_turning_deflection(plan, load_config(None))
    config = tmp_path / "explicit-limit.toml"
    config.write_text("[limits]\nfinish_mm=1.0\n", encoding="utf-8")
    check_turning_deflection(plan, load_config(config))


@pytest.mark.parametrize(
    ("machine", "support", "operation"),
    [
        ("other", True, {}),
        ("other", False, {"cut_kind": "longitudinal_turning"}),
        ("other", False, {"turning_cuts": [_cut()]}),
        ("lathe", True, {"cut_kind": "other", "turning_cuts": [_cut()]}),
    ],
)
def test_other_classification_rejects_contradictory_physics(
    machine, support, operation
):
    plan = _plan()
    setup = plan.data["setups"][0]
    setup["machine_kind"] = machine
    setup["operations"] = [operation]
    if not support:
        setup.pop("turning_support")
    with pytest.raises(TurningError, match="contradicts"):
        check_turning_deflection(plan, load_config(None))


def _step_plan(*cuts, step=None, support=None):
    """Issue #515: Ø1/4 in brass bar, a Ø.058 in spigot step-turned 0.70 in
    back from the free end, 30.7 mm out of the jaws (chuck Z0), no tailstock."""
    plan = _plan(support=support)
    plan.data["turning_material"] = "brass"
    operation = plan.data["setups"][0]["operations"][0]
    operation["turning_cuts"] = list(cuts)
    operation["turning_step"] = step or {"length_mm": 2.032, "load_diameter_mm": 6.35}
    return plan


def _spigot(phase, **changes):
    rough = phase == "rough"
    cut = {
        "name": f"spigot {phase}",
        "phase": phase,
        "start_z_mm": 30.7,
        "end_z_mm": 30.7 - 0.70 * 25.4,
        "start_diameter_mm": 6.35 if rough else 1.6002,
        "end_diameter_mm": 1.6002 if rough else 1.4732,
        "max_radial_doc_mm": 0.024 * 25.4 if rough else 0.0025 * 25.4,
        "feed_mm_rev": 0.002 * 25.4 if rough else 0.001 * 25.4,
    }
    cut.update(changes)
    cut.setdefault("kept_start_z_mm", cut["start_z_mm"])
    cut.setdefault("kept_end_z_mm", cut["end_z_mm"])
    return cut


def test_step_bending_reduces_to_closed_form_cantilevers():
    # 100 N per mm DOC at 1 mm DOC, E=200000, x=50: no step ahead is the
    # load-section cantilever; a step as long as the cantilever is the thin
    # cantilever at end + 2 DOC; between them the two segments add.
    per_doc, x, modulus = 100.0, 50.0, 200000.0

    def cantilever(length, diameter):
        return 100 * length**3 / (3 * modulus * math.pi * diameter**4 / 64)

    bend, depth = _stepped_bending(per_doc, x, 0.0, 10.0, 2.0, 1.0, modulus)
    assert (bend, depth) == (pytest.approx(cantilever(50, 10)), 1.0)
    bend, _ = _stepped_bending(per_doc, x, x, 10.0, 6.0, 1.0, modulus)
    assert bend == pytest.approx(cantilever(50, 8))
    bend, _ = _stepped_bending(per_doc, x, 5.0, 10.0, 6.0, 1.0, modulus)
    expected = cantilever(50, 10) - cantilever(5, 10) + cantilever(5, 8)
    assert bend == pytest.approx(expected)


def test_step_bending_finds_a_shallower_worse_pass():
    # A long thin step ahead: a pass shallower than the max DOC meets a
    # thinner step and bends more; no sampled pass depth bends more.
    per_doc, x, ahead, load, end, doc, modulus = 100, 40, 30, 12, 2, 3, 200000

    def bend_at(t):
        load_side = (x**3 - ahead**3) / (3 * modulus * math.pi * load**4 / 64)
        step_side = ahead**3 / (3 * modulus * math.pi * (end + 2 * t) ** 4 / 64)
        return per_doc * t * (load_side + step_side)

    bend, depth = _stepped_bending(per_doc, x, ahead, load, end, doc, modulus)
    assert end / 6 < depth < end / 3
    assert bend > 5 * bend_at(doc)
    samples = [bend_at(doc * i / 20000) for i in range(1, 20001)]
    assert max(samples) <= bend * (1 + 1e-12)
    assert max(samples) == pytest.approx(bend, rel=1e-6)


def test_issue_515_step_turning_passes_where_the_finished_section_refuses():
    config = load_config(None)
    check_turning_deflection(_step_plan(_spigot("rough"), _spigot("finish")), config)
    for index, (phase, expected) in enumerate((("rough", 0.0909), ("finish", 0.00487))):
        assert expected < config["limits"][f"{phase}_mm"]
        cuts = [_spigot("rough"), _spigot("finish")]
        # Just under and over the estimate: the estimate itself, per phase.
        cuts[index]["max_deflection_mm"] = expected * 0.99
        with pytest.raises(TurningError, match=f"spigot {phase}.*steps of 2.032 mm"):
            check_turning_deflection(_step_plan(*cuts), config)
        cuts[index]["max_deflection_mm"] = expected * 1.01
        check_turning_deflection(_step_plan(*cuts), config)
        # Without turning_step the same cut bends at the finished Ø over the
        # whole 30.7 mm: refused by an order of magnitude.
        plain = _plan(dict(_spigot(phase), minimum_diameter_mm=1.4732))
        plain.data["turning_material"] = "brass"
        with pytest.raises(TurningError, match="model diameter 1.4732"):
            check_turning_deflection(plain, config)


@pytest.mark.parametrize(
    ("cuts", "step", "message"),
    [
        # One full-depth .096 in pass in a step: about 0.18 mm against 0.005.
        (
            [_spigot("finish", start_diameter_mm=6.35, max_radial_doc_mm=2.4384)],
            None,
            r"estimated radial bending 0\.1",
        ),
        # The issue's .10 in steps: the finish pass sees .10 in of Ø1.60 ahead.
        (
            [_spigot("rough"), _spigot("finish")],
            {"length_mm": 2.54, "load_diameter_mm": 6.35},
            "0.00518",
        ),
        # A thinner load section (the head turned first) refuses the rough.
        ([_spigot("rough")], {"length_mm": 2.032, "load_diameter_mm": 5.5}, "Ø5.5"),
        # A return pass, away from the chuck, cuts the finished length again.
        (
            [_spigot("finish", start_z_mm=12.92, end_z_mm=30.7)],
            None,
            "must run toward the chuck",
        ),
        ([_spigot("finish")], {"length_mm": 18.0, "load_diameter_mm": 6.35}, "exceeds"),
        ([_spigot("finish", minimum_diameter_mm=6.35)], None, "no minimum_diameter_mm"),
        ([_spigot("finish")], {"length_mm": 2.0, "load_diameter_mm": 7.0}, "over the"),
        ([_spigot("finish")], {"length_mm": 2.0}, "load_diameter_mm"),
        (
            [_spigot("finish")],
            {"length_mm": 2.0, "load_diameter_mm": 6.35, "x": 1},
            "x",
        ),
    ],
)
def test_declared_step_turning_still_refuses_failing_numbers(cuts, step, message):
    with pytest.raises(TurningError, match=message):
        check_turning_deflection(_step_plan(*cuts, step=step), load_config(None))


@pytest.mark.parametrize("kind", ["tailstock", "follower"])
def test_step_turning_needs_chuck_only_support(kind):
    support = {"kind": kind, "chuck_z_mm": 0, "centre_z_mm": 40}
    with pytest.raises(TurningError, match="needs chuck_only support"):
        check_turning_deflection(
            _step_plan(_spigot("rough"), support=support), load_config(None)
        )


@pytest.mark.parametrize("machine", ["lathe", "other"])
def test_turning_step_outside_longitudinal_turning_contradicts(machine):
    plan = _plan()
    setup = plan.data["setups"][0]
    setup["machine_kind"] = machine
    setup.pop("turning_support")
    setup["operations"] = [
        {"cut_kind": "other", "turning_step": {"length_mm": 1, "load_diameter_mm": 6}}
    ]
    with pytest.raises(TurningError, match="contradicts"):
        check_turning_deflection(plan, load_config(None))
