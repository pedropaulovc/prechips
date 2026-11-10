from pathlib import Path

import pytest

from prechips.cad import CadError, RoundStock, load_cad
from prechips.cli import main
from prechips.profiles import HOBBY, PRO, load_profile
from prechips.stock import StockError, check_stock_fit
from prechips.traveler import PlanError, load_plan, render_traveler

ROOT = Path(__file__).resolve().parents[1]
PLAN = ROOT / "examples/comparison/pivot-shaft.toml"
SOURCE = ROOT / "examples/cad/pivot-shaft-v40.toml"


def prepare(tmp_path, replacements=(), plan_replacements=()):
    text = SOURCE.read_text(encoding="utf-8")
    for old, new in replacements:
        assert old in text
        text = text.replace(old, new)
    (tmp_path / "cad.toml").write_text(text, encoding="utf-8")
    (tmp_path / "shop.toml").write_bytes((ROOT / "examples/shop.toml").read_bytes())
    text = (
        PLAN.read_text(encoding="utf-8")
        .replace("../cad/pivot-shaft-v40.toml", "cad.toml")
        .replace('shop = "../shop.toml"', 'shop = "shop.toml"')
    )
    for old, new in plan_replacements:
        assert old in text
        text = text.replace(old, new)
    path = tmp_path / "plan.toml"
    path.write_text(text, encoding="utf-8")
    return path


def test_attachment_radius_and_cap_frames_follow_source():
    plan = load_plan(PLAN)
    values = plan.cad.values
    for end in ("north", "south"):
        assert values[f"{end}_frame_edge_to_tip"] == pytest.approx(8.872708333333334)
    assert values["north_sphere_center_z"] == pytest.approx(-4.1102083333333335)
    assert values["south_sphere_center_z"] == pytest.approx(-2.3602083333333335)
    assert values["north_apex_z"] == 0
    assert values["south_apex_z"] == 1.75
    html = render_traveler(plan)
    assert "6.330–6.350" in html
    assert plan.cad.stock_requirement == RoundStock(10.0, 180.5)


@pytest.mark.parametrize(
    "diameter,length,error",
    [
        (10.0, 180.5, None),
        (9.999999, 180.5, "diameter"),
        (10.0, 180.499999, "length"),
    ],
)
def test_round_stock_exact_and_short_dimensions(diameter, length, error):
    plan = load_plan(PLAN)
    plan.parameters.update(stock_dia_mm=diameter, stock_length_mm=length)
    if error is None:
        check_stock_fit(plan)
    else:
        with pytest.raises(StockError, match=f"stock_fit: {error}:") as caught:
            check_stock_fit(plan)
        required = "10" if error == "diameter" else "180.5"
        assert f"{required} mm" in str(caught.value)


@pytest.mark.parametrize("key", ["stock_dia_mm", "stock_length_mm"])
@pytest.mark.parametrize("value", [None, 0, -1, float("nan"), float("inf"), True])
def test_round_stock_requires_finite_positive_actual_dimensions(key, value):
    plan = load_plan(PLAN)
    plan.parameters.update(stock_dia_mm=10.0, stock_length_mm=180.5)
    if value is None:
        del plan.parameters[key]
    else:
        plan.parameters[key] = value
    with pytest.raises(StockError, match=rf"parameters\.{key}"):
        check_stock_fit(plan)


def test_shaft_without_stock_requirement_is_not_implicitly_accepted():
    plan = load_plan(PLAN)
    plan.cad.stock_requirement = None
    with pytest.raises(StockError, match="does not provide a stock requirement"):
        check_stock_fit(plan)


def test_round_stock_diameter_tracks_nominal_not_source_limit(tmp_path):
    path = prepare(
        tmp_path,
        [('"dia_nominal" = 10.0', '"dia_nominal" = 10.1')],
    )
    plan = load_plan(path)
    assert plan.cad.stock_requirement == RoundStock(10.1, 180.5)
    plan.parameters["stock_length_mm"] = 180.5
    with pytest.raises(StockError, match="diameter"):
        check_stock_fit(plan)


@pytest.mark.parametrize("length", [None, 180.499999, 180.5])
def test_round_stock_length_gate_runs_before_output(tmp_path, capsys, length):
    path = prepare(tmp_path)
    text = "\n".join(
        line
        for line in path.read_text(encoding="utf-8").splitlines()
        if not line.startswith("stock_length_mm =")
    )
    if length is not None:
        text = text.replace("[parameters]", f"[parameters]\nstock_length_mm = {length}")
    path.write_text(text, encoding="utf-8")
    output = tmp_path / "out/traveler.html"
    result = main(
        [
            "traveler",
            str(path),
            "--out",
            str(output),
            "--profile",
            "pro",
            "--disable-check",
            "turning_deflection",
        ]
    )
    if length == 180.5:
        assert result == 0
        assert output.exists()
    else:
        assert result == 2
        error = capsys.readouterr().err
        assert "stock_fit: length:" in error
        assert "180.5 mm" in error
        assert not output.parent.exists()


def test_source_limits_and_finish_reach_both_inspections(tmp_path):
    path = prepare(
        tmp_path,
        [
            ('"dia" = [6.33, 6.35]', '"dia" = [6.31, 6.37]'),
            ('"finish_ra" = 1.6', '"finish_ra" = 2.0'),
            ('"length_ref" = 156.67000000000002', '"length_ref" = 157.67'),
            ('"base_z" = -156.67000000000002', '"base_z" = -157.67'),
        ],
    )
    plan = load_plan(path)
    html = render_traveler(plan)
    assert html.count("6.310–6.370") == 2
    assert html.count("Ra ≤2") == 3
    assert "157.67" in html
    assert "15.33–16.33" in html
    assert "1.50–2.00" in html
    assert plan.data["tools"] == load_plan(PLAN).data["tools"]


def test_changed_cap_shifts_apex_frame_and_attachment_radius(tmp_path):
    path = prepare(
        tmp_path,
        [
            ('"height_nominal" = 1.5', '"height_nominal" = 1.6'),
            ('"sphere_radius" = 4.1102083333333335', '"sphere_radius" = 3.9501953125'),
        ],
    )
    plan = load_plan(path)
    values = plan.cad.values
    assert values["thrust_z"] == pytest.approx(-9.1)
    assert values["north_shoulder_z"] == pytest.approx(-7.6)
    assert values["north_relief_end"] == pytest.approx(-5.6)
    assert values["south_base_z"] == pytest.approx(0.15)
    assert values["plain_end_z"] == pytest.approx(165.9)
    assert values["north_grip"] == pytest.approx(12.6)
    assert values["north_grip"] + values["supported_projection"] == pytest.approx(180)
    assert values["rest_scribe_min"] == pytest.approx(11.30)
    html = render_traveler(plan)
    assert "Z-9.1" in html and "Z-7.6" in html
    assert "Z0.15" in html and "R3.95" in html
    assert "12.6 mm" in html
    assert "11.30" in html
    for end in ("north", "south"):
        assert values[f"{end}_frame_edge_to_tip"] == pytest.approx(8.7126953125)
    assert values["north_sphere_center_z"] == pytest.approx(-3.9501953125)
    assert values["south_sphere_center_z"] == pytest.approx(-2.2001953125)


def test_shoulder_and_relief_transforms_follow_source(tmp_path):
    path = prepare(
        tmp_path,
        [
            ('"value" = -6.0', '"value" = -6.2'),
            ('"value" = -7.5', '"value" = -7.7'),
            ('"upper_z" = -6.0', '"upper_z" = -6.2'),
            ('"lower_z" = -7.5', '"lower_z" = -7.7'),
            ('"length_nominal" = 6.0', '"length_nominal" = 6.2'),
            ('"at" = [0.0, 0.0, -5.0]', '"at" = [0.0, 0.0, -5.2]'),
            ('"at" = [0.0, 0.0, -8.5]', '"at" = [0.0, 0.0, -8.7]'),
        ],
    )
    plan = load_plan(path)
    values = plan.cad.values
    assert values["north_relief_start"] == pytest.approx(-7.7)
    assert values["north_relief_end"] == pytest.approx(-5.7)
    assert values["south_relief_start"] == 0.0
    assert values["south_relief_end"] == pytest.approx(2)
    html = render_traveler(plan)
    assert "Z-7.7" in html
    assert "Z0…1.6" in html
    assert "11.30" in html


def test_width_and_blade_change_plunges_not_source_limits(tmp_path):
    path = prepare(
        tmp_path,
        [
            ('"width_nominal" = 2.0', '"width_nominal" = 2.2'),
            ('"at" = [0.0, 0.0, -5.0]', '"at" = [0.0, 0.0, -4.9]'),
            ('"at" = [0.0, 0.0, -8.5]', '"at" = [0.0, 0.0, -8.6]'),
        ],
        [("blade_width_mm = 1.6", "blade_width_mm = 1.4")],
    )
    plan = load_plan(path)
    assert plan.cad.values["north_relief_first_end"] == pytest.approx(-6.1)
    assert plan.cad.values["north_relief_second_start"] == pytest.approx(-6.7)
    html = render_traveler(plan)
    assert "Z-7.5…-6.1" in html
    assert "0.8…2.2" in html
    assert "1.2–2.8" in html


def test_unequal_caps_keep_independent_radii_heights_and_frames(tmp_path):
    path = prepare(
        tmp_path,
        [
            (
                (
                    '"height_nominal" = 1.5\n"sphere_radius" = 4.1102083333333335\n'
                    '"base_z" = -156.67000000000002'
                ),
                (
                    '"height_nominal" = 2.0\n"sphere_radius" = 3.52015625\n'
                    '"base_z" = -156.67000000000002'
                ),
            ),
        ],
    )
    values = load_plan(path).cad.values
    assert values["north_frame_edge_to_tip"] == pytest.approx(8.872708333333334)
    assert values["south_frame_edge_to_tip"] == pytest.approx(8.28265625)
    assert values["north_base_z"] == -1.5
    assert values["south_base_z"] == -0.25
    assert values["north_sphere_center_z"] == pytest.approx(-4.1102083333333335)
    assert values["south_sphere_center_z"] == pytest.approx(-1.77015625)
    assert values["thrust_z"] == -9


@pytest.mark.parametrize("preset", ["pro", "hobby", "custom-on", "custom-off"])
def test_detailed_instruction_replaces_compact_and_other_operations_fall_back(
    tmp_path, preset
):
    plan = load_plan(PLAN)
    operation = plan.data["setups"][2]["operations"][-1]
    operation["instruction"] = "Compact <cap> method"
    operation["instruction_detailed"] = "Detailed <cap> method"
    fallback = plan.data["setups"][0]["operations"][0]
    fallback["instruction"] = "Ordinary fallback operation"
    if preset.startswith("custom"):
        profile_path = tmp_path / "profile.toml"
        enabled = '["detailed_instructions"]' if preset == "custom-on" else "[]"
        profile_path.write_text(
            f'name = "Custom"\nfeatures = {enabled}\nenforce = []\n',
            encoding="utf-8",
        )
        profile = load_profile(str(profile_path))
    else:
        profile = HOBBY if preset == "hobby" else PRO
    html = render_traveler(plan, profile=profile)
    detailed = preset in {"hobby", "custom-on"}
    assert html.count("Detailed &lt;cap&gt; method") == int(detailed)
    assert html.count("Compact &lt;cap&gt; method") == int(not detailed)
    assert html.count("Ordinary fallback operation") == 1


@pytest.mark.parametrize(
    "old,new",
    [
        ('"height" = [0.7, 2.3]', '"height" = [2.3, 0.7]'),
        ('"sphere_radius" = 4.1102083333333335', '"sphere_radius" = nan'),
        ('"dia_nominal" = 6.35', '"dia_nominal" = 6.34'),
        ('"axis" = [0.0, 0.0, 1.0]', '"axis" = [0.0, 1.0, 0.0]'),
        ('"units" = "mm"', '"units" = "in"'),
        ('"height_nominal" = 1.5', '"missing_height" = 1.5'),
    ],
)
def test_unusable_source_refuses_before_output(tmp_path, capsys, old, new):
    path = prepare(tmp_path, [(old, new)])
    output = tmp_path / "out/traveler.html"
    assert main(["traveler", str(path), "--out", str(output)]) == 2
    assert "stock_fit:" not in capsys.readouterr().err
    assert not output.parent.exists()


@pytest.mark.parametrize(
    "old,new",
    [
        ("blade_width_mm = 1.6", "blade_width_mm = 2.1"),
        ("supply_length_mm = 175.0", "supply_length_mm = 174.0"),
        ("short_grip_mm = 20.0", "short_grip_mm = -1.0"),
    ],
)
def test_unsupported_authored_tool_strategy_refuses(tmp_path, old, new):
    path = prepare(tmp_path, plan_replacements=[(old, new)])
    with pytest.raises(PlanError):
        load_plan(path)


def test_required_dispatcher_does_not_guess_adapter(tmp_path):
    with pytest.raises(CadError, match="adapter"):
        load_cad(SOURCE, {}, "unknown")
    path = prepare(
        tmp_path,
        plan_replacements=[
            ('adapter = "harmonic_pivot_shaft"', 'adapter = "unknown"'),
        ],
    )
    with pytest.raises(PlanError, match="adapter"):
        load_plan(path)


@pytest.mark.parametrize(
    "old,new,blank,grip,passes",
    [
        ("supply_length_mm = 175.0", "supply_length_mm = 176.0", 181.5, 12.5, 2),
        ("stub_allowance_mm = 5.0", "stub_allowance_mm = 6.0", 181.5, 13.5, 2),
        (
            "plain_end_face_allowance_mm = 0.5",
            "plain_end_face_allowance_mm = 0.75",
            180.75,
            12.5,
            3,
        ),
    ],
)
def test_blank_and_facing_follow_authored_inputs(
    tmp_path, old, new, blank, grip, passes
):
    path = prepare(tmp_path, plan_replacements=[(old, new)])
    plan = load_plan(path)
    assert plan.cad.values["blank_length"] == pytest.approx(blank)
    assert plan.cad.stock_requirement.length_mm == pytest.approx(blank)
    assert plan.cad.values["north_grip"] == pytest.approx(grip)
    assert plan.cad.values["plain_end_face_passes"] == passes
    assert str(blank) in plan.data["stock"]
    assert str(grip) in plan.data["setups"][1]["holding"]
    assert str(passes) in plan.data["setups"][0]["operations"][0]["instruction"]
    assert (
        str(plan.parameters["plain_end_face_allowance_mm"])
        in (plan.data["setups"][0]["datum"])
    )


def test_shorter_journal_updates_follow_rest_waste_threshold(tmp_path):
    path = prepare(
        tmp_path,
        [
            ('"value" = -6.0', '"value" = -5.2'),
            ('"value" = -7.5', '"value" = -6.7'),
            ('"upper_z" = -6.0', '"upper_z" = -5.2'),
            ('"lower_z" = -7.5', '"lower_z" = -6.7'),
            ('"length_nominal" = 6.0', '"length_nominal" = 5.2'),
            ('"at" = [0.0, 0.0, -5.0]', '"at" = [0.0, 0.0, -4.2]'),
            ('"at" = [0.0, 0.0, -8.5]', '"at" = [0.0, 0.0, -7.7]'),
        ],
    )
    plan = load_plan(path)
    assert plan.cad.values["plain_end_z"] == pytest.approx(166.8)
    assert plan.cad.values["rest_scribe_min"] == pytest.approx(12.3)
    html = render_traveler(plan)
    assert "12.30" in html
    assert "11.50" not in html


@pytest.mark.parametrize("profile", ["pro", "hobby"])
def test_authored_shaft_default_refuses_pre_follower_finish(tmp_path, capsys, profile):
    path = prepare(tmp_path)
    output = tmp_path / "out" / "traveler.html"
    assert (
        main(
            [
                "traveler",
                str(path),
                "--out",
                str(output),
                "--profile",
                profile,
                "--disable-check",
                "setup_diagrams",
            ]
        )
        == 2
    )
    error = capsys.readouterr().err
    assert "turning_deflection" in error
    assert "Body finish" in error
    assert "before follower" in error
    assert not output.parent.exists()


def test_analysis_bindings_follow_cad_and_process_as_numbers(tmp_path):
    baseline = load_plan(PLAN)
    path = prepare(
        tmp_path,
        [('"dia_nominal" = 5.7', '"dia_nominal" = 5.8')],
        [
            ("supply_length_mm = 175.0", "supply_length_mm = 176.0"),
            ("follow_rest_lead_mm = 8.0", "follow_rest_lead_mm = 9.0"),
        ],
    )
    changed = load_plan(path)

    def cuts(plan):
        return {
            cut["name"]: cut
            for setup in plan.data["setups"]
            for operation in setup["operations"]
            for cut in operation.get("turning_cuts", [])
        }

    before, after = cuts(baseline), cuts(changed)
    support = changed.data["setups"][1]["turning_support"]
    for key in (
        "chuck_z_mm",
        "centre_z_mm",
        "engage_z_mm",
        "offset_mm",
        "pad_width_mm",
    ):
        assert isinstance(support[key], (int, float))
    assert support["offset_mm"] == 9.0
    assert after["Body rough"]["start_z_mm"] == pytest.approx(
        before["Body rough"]["start_z_mm"] + 1.0
    )
    assert after["Journal finish"]["minimum_diameter_mm"] == pytest.approx(
        before["Journal finish"]["minimum_diameter_mm"] + 0.1
    )
    for cut in after.values():
        for key, value in cut.items():
            if key not in {"name", "phase"}:
                assert isinstance(value, (int, float)), (cut["name"], key, value)
