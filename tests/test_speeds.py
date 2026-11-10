import pytest

from prechips.cli import main
from prechips.speeds import calculated_rpm
from prechips.traveler import load_plan

PLAN = """\
shop = "shop.toml"
material_key = "1018"
title = "Test part"
part = "T1"
revision = "A"
material = "Steel"
stock = "Blank"

[parameters]
dia_mm = 6.35

[[tools]]
id = "bit"
ref = "bit"

[[setups]]
title = "Turn"
machine = "Lathe"
machine_ref = "lathe"

[[setups.operations]]
tool = "bit"
speed_kind = "spindle"
settings = "finish"
cut_diameter_mm = "{{process.dia_mm}}"
instruction = "Finish."
"""

SHOP = """\
[machines.lathe]
kind = "lathe"
rpm_ranges = [[70, 380], [380, 2000]]

[tools.bit]
description = "HSS bit"

[settings.finish]
tool = "bit"
material = "1018"
sfm = 110
feed_mm_rev = 0.05
"""

LATHE = [(70.0, 380.0), (380.0, 2000.0)]


def prepare(tmp_path, plan_text=PLAN, shop_text=SHOP):
    plan = tmp_path / "plan.toml"
    plan.write_text(plan_text, encoding="utf-8")
    (tmp_path / "shop.toml").write_text(shop_text, encoding="utf-8")
    profile = tmp_path / "speeds.toml"
    profile.write_text('name = "Speeds"\nfeatures = []\nenforce = ["cutting_speeds"]\n')
    return plan, profile


def operation(plan):
    return load_plan(plan).data["setups"][0]["operations"][0]


def run(tmp_path, capsys, plan_text=PLAN, shop_text=SHOP):
    plan, profile = prepare(tmp_path, plan_text, shop_text)
    out = tmp_path / "traveler.html"
    code = main(["traveler", str(plan), "--out", str(out), "--profile", str(profile)])
    return code, capsys.readouterr().err, out


@pytest.mark.parametrize(
    ("raw", "ranges", "rpm"),
    [
        (825.0, [(50.0, 3000.0)], 800),  # tie to even: 16.5 -> 16
        (875.0, [(50.0, 3000.0)], 900),  # tie to even: 17.5 -> 18
        (1186.4, [(50.0, 3000.0)], 1200),
        (2910.6, LATHE, 2000),  # above the top limit
        (40.0, [(72.0, 2000.0)], 72),  # below the bottom, not a multiple of 50
        (440.0, [(70.0, 380.0), (500.0, 2000.0)], 380),  # gap: top of range below
        (500.0, [(70.0, 380.0), (500.0, 2000.0)], 500),  # gap edge is selectable
    ],
)
def test_rounding_clamping_and_gap(raw, ranges, rpm):
    assert calculated_rpm(raw, ranges) == rpm


@pytest.mark.parametrize(
    ("sfm", "diameter", "rpm"),
    [(90, 10.0, 850), (90, 6.55, 1350), (110, 6.35, 1700), (70, 5.7, 1200)],
)
def test_archive_speeds_from_surface_speed(tmp_path, sfm, diameter, rpm):
    plan, _ = prepare(
        tmp_path,
        PLAN.replace("dia_mm = 6.35", f"dia_mm = {diameter}"),
        SHOP.replace("sfm = 110", f"sfm = {sfm}"),
    )
    assert operation(plan)["rpm"] == rpm
    assert operation(plan)["feed"] == "0.05 mm/rev"


@pytest.mark.parametrize(
    ("unit", "feed"), [("", "122 mm/min"), ('feed_unit = "in/min"\n', "4.8 in/min")]
)
def test_milling_feed_from_chip_load(tmp_path, unit, feed):
    shop = SHOP.replace(
        "sfm = 110\nfeed_mm_rev = 0.05\n",
        f"sfm = 165\nchip_load_mm_per_tooth = 0.0508\nflutes = 2\n{unit}",
    )
    plan, _ = prepare(tmp_path, PLAN.replace("6.35", "13.49375"), shop)
    assert operation(plan)["rpm"] == 1200
    assert operation(plan)["feed"] == feed


def test_authored_values_win(tmp_path):
    text = PLAN.replace(
        'cut_diameter_mm = "{{process.dia_mm}}"\n', 'rpm = 900\nfeed = "Local"\n'
    )
    plan, _ = prepare(tmp_path, text)
    assert operation(plan)["rpm"] == 900
    assert operation(plan)["feed"] == "Local"


def test_cli_smoke(tmp_path, capsys):
    code, err, out = run(tmp_path, capsys)
    assert code == 0, err
    assert "1700 rpm; 0.05 mm/rev" in out.read_text(encoding="utf-8")


@pytest.mark.parametrize(
    ("plan_text", "shop_text", "message"),
    [
        (
            PLAN.replace('cut_diameter_mm = "{{process.dia_mm}}"\n', ""),
            SHOP,
            "operations[1].cut_diameter_mm: required by shop.settings.finish.sfm",
        ),
        (
            PLAN.replace('machine_ref = "lathe"\n', ""),
            SHOP,
            "operations[1]: shop.settings.finish.sfm requires setup machine_ref",
        ),
        (PLAN, SHOP.replace("sfm = 110", "sfm = 110\nrpm = 900"), "not both"),
        (
            PLAN,
            SHOP.replace("rpm_ranges = [[70, 380], [380, 2000]]\n", ""),
            "shop.machines.lathe.rpm_ranges: required but not declared",
        ),
        (
            PLAN.replace('speed_kind = "spindle"\n', ""),
            SHOP,
            "cutting_speeds: setup 1 (Turn), Op 10: speed_kind must declare",
        ),
        (
            PLAN.replace('speed_kind = "spindle"', 'speed_kind = "other"'),
            SHOP,
            "setup 1 (Turn), Op 10: speed_kind other contradicts 1700 rpm",
        ),
        (
            PLAN + "rpm = 2400\n",
            SHOP,
            "Op 10: 2400 rpm is outside shop.machines.lathe rpm_ranges 70–380, 380–2000",
        ),
        (
            PLAN.replace(
                'cut_diameter_mm = "{{process.dia_mm}}"\n', 'feed = "Hand"\n'
            ).replace('settings = "finish"\n', ""),
            SHOP,
            "setup 1 (Turn), Op 10: spindle operation has no rpm",
        ),
        (
            PLAN.replace(
                'tool = "bit"\nspeed_kind = "spindle"\nsettings = "finish"\n', ""
            ).replace('cut_diameter_mm = "{{process.dia_mm}}"\n', "rpm = 900\n"),
            SHOP,
            "setup 1 (Turn), Op 10: 900 rpm without a tool",
        ),
    ],
)
def test_refusals_are_located(tmp_path, capsys, plan_text, shop_text, message):
    code, err, out = run(tmp_path, capsys, plan_text, shop_text)
    assert code == 2
    assert message in err
    assert not out.exists()
