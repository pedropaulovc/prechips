"""A mill vise swivelled about Z (issue #300): ``jaws_along`` names only the jaw axis
before any swivel, so an angle written into it is bad input, never silent free text."""

import pytest
from test_cli import ROOT, run_cli

FEATURES = """\
part = "bar"
units = "mm"
frames = "unknown"

[features.end_chamfer]
kind = "face"
frame = "model"
requirements = []
note = "45 deg end chamfer of a 100 x 20 x 3 bar, side-milled along table X"
"""

INVENTORY = """\
[machines.mill]
kind = "mill"

[fixtures.vise]
kind = "vise"
bed_height_mm = 20
jaw_height_mm = 40

[tools.em]
kind = "endmill"
dia_mm = 9.525

[holders.collet]
kind = "collet"
"""

PLAN = """\
part = "bar"
features = "features.toml"

[stock]
form = "bar"
material = "1018"
length_mm = 100
section_mm = [20, 3]

[[setups]]
id = "V1"
machine = "mill"
frame = "SU"

[setups.stock_state]
top_z = 1.5
bottom_z = -1.5

[setups.hold]
fixture = "vise"
fixed_jaw = "rear"
{hold}

[[setups.ops]]
op = 10
do = "side_mill"
feature = "end_chamfer"
tool = "em"
holder = "collet"
"""


def repro(tmp_path, hold):
    """The issue's one-feature bundle checked with ``hold`` lines, kernel absent."""
    (tmp_path / "features.toml").write_text(FEATURES, encoding="utf-8")
    (tmp_path / "inventory.toml").write_text(INVENTORY, encoding="utf-8")
    plan = tmp_path / "plan.toml"
    plan.write_text(PLAN.replace("{hold}", hold), encoding="utf-8")
    shop = ROOT / "examples"
    return run_cli(
        "check",
        "--inventory",
        tmp_path / "inventory.toml",
        "--cutting-data",
        shop / "cutting-data.toml",
        "--policy",
        shop / "shop-policy.toml",
        "--out",
        tmp_path / "out",
        plan,
        env={"FREECAD_CMD": str(tmp_path / "no-freecad")},
    )


def test_case_a_a_plain_vise_hold_loads(tmp_path):
    result = repro(tmp_path, 'jaws_along = "x"')
    assert result.returncode == 2, result.stdout + result.stderr


@pytest.mark.parametrize("along", ["43.77", "X", "45deg", "xy"])
def test_case_b_an_angle_written_into_jaws_along_is_bad_input(along, tmp_path):
    result = repro(tmp_path, f'jaws_along = "{along}"')
    assert result.returncode == 3, result.stdout + result.stderr
    assert f"jaws_along '{along}' is not a jaw axis" in result.stderr
    assert "jaws_angle_deg" in result.stderr
