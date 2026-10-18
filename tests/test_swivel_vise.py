"""A mill vise swivelled about Z (issue #300): ``jaws_along`` names only the jaw axis
before any swivel, so an angle written into it is bad input, never silent free text."""

import json
import math

import pytest
from test_cli import ROOT, run_cli
from test_kernel_geometry import IDENTITY, Engine, _op, _setup, _vise
from test_kernel_rocker_regression import _author

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


_CHANNEL = r"""
import sys
import FreeCAD, Part
V = FreeCAD.Vector
out = sys.argv[sys.argv.index("--") + 1]
# A 60 x 40 x 20 block with a 30 wide, 10 deep channel along X: two 5 mm rails.
solid = Part.makeBox(60, 40, 20).cut(Part.makeBox(62, 30, 11, V(-1, 5, 10)))
solid.exportStep(out + "/channel.step")
"""


@pytest.fixture(scope="module")
def channel(tmp_path_factory, freecad_kernel):
    return _author(tmp_path_factory.mktemp("swivel"), _CHANNEL, "channel.step", freecad_kernel)


@pytest.fixture
def engine(tmp_path, freecad_kernel):
    return Engine(tmp_path, freecad_kernel)


def test_case_c_a_swivel_angle_loads_and_its_setting_is_checked(tmp_path):
    result = repro(tmp_path, 'jaws_along = "x"\njaws_angle_deg = 43.77')
    assert result.returncode == 2, result.stdout + result.stderr
    report = json.loads((tmp_path / "out" / "report.json").read_text(encoding="utf-8"))
    (row,) = [f for f in report["findings"] if f["rule"] == "swivel"]
    # No align block says how the swivel is set: its tolerance, and so the edge, is unknown.
    assert row["status"] == "unknown" and row["numbers"]["jaws_angle_deg"] == 43.77
    assert row["numbers"]["tolerance_deg"] == "unknown"


def _turned(point, degrees):
    c, s = math.cos(math.radians(degrees)), math.sin(math.radians(degrees))
    return [point[0] * c - point[1] * s, point[0] * s + point[1] * c]


def _frame(degrees):
    """A setup frame that shows the model turned ``degrees`` about setup Z."""
    c, s = math.cos(math.radians(-degrees)), math.sin(math.radians(-degrees))
    return {"origin": [0, 0, 0], "x": [c, s, 0], "y": [-s, c, 0], "z": [0, 0, 1]}


_FACTS = ("width_mm", "contact_grip_mm", "parallel_pair", "claimed_in_jaws", "min_wall_mm")


@pytest.mark.parametrize("angle", [30.0, -43.77])
def test_a_swivelled_vise_grips_the_turned_work_as_square_jaws_grip_it_unturned(
    engine, channel, angle
):
    """The work turned with the jaws is held exactly as square jaws hold it unturned: the
    grip facts match, the holder meets the turned jaws as it met the square ones, and the
    turned parallels stand clear of the jaws as the square ones did."""
    step = channel
    outer = engine.refs(step, (0, 0, 0), (60, 0, 20))
    channel = engine.refs(step, (0, 5, 10), (60, 35, 20))
    features = {"channel": channel, "outer": outer}
    ops = [_op("S1:10", "channel", 3.0, 4.0, 10.5), _op("S1:20", "outer", 3.0, 4.0, 5.0)]
    centres = [[30.0, 7.0], [30.0, 33.0]]
    square = _vise(30.0, centre=30.0, parallels=(150.0, 6.0, centres))
    swivelled = _vise(
        30.0, centre=30.0, parallels=(150.0, 6.0, [_turned(c, angle) for c in centres])
    )
    swivelled["jaws_angle_deg"] = angle
    plain, turned = (
        engine.run(engine.job(step, features, [_setup(ops, hold, frame=frame)]))
        for hold, frame in ((square, IDENTITY), (swivelled, _frame(angle)))
    )
    held, turned_held = plain["setups"]["S1"], turned["setups"]["S1"]
    assert {k: held[k] for k in _FACTS} == {k: turned_held[k] for k in _FACTS}
    assert held["width_mm"] == 40.0 and held["parallel_pair"] is True
    assert turned_held["jaws_angle_deg"] == angle
    assert turned_held["jaw_frame_stock_bbox_mm"] == pytest.approx(held["stock_bbox_mm"], abs=1e-4)
    for scene in (held["render_scene"], turned_held["render_scene"]):
        assert scene["jaws"] == scene["parallels"] == "exact"
    assert turned_held["fixture_clashes"] == held["fixture_clashes"] == []
    # The picture prints the stock's own size along and across the jaws, not its footprint.
    assert turned_held["render_scene"]["swivel"] == {
        "deg": angle,
        "along_mm": 60.0,
        "across_mm": 40.0,
    }
    assert "swivel" not in held["render_scene"]
    standing, turned_standing = plain["ops"]["S1:10"], turned["ops"]["S1:10"]
    assert standing["obstacles"]["holder"] == ["fixed_jaw", "moving_jaw"]
    assert turned_standing["obstacles"]["holder"] == standing["obstacles"]["holder"]
    assert turned_standing["holder_hits"] == standing["holder_hits"] > 0


def test_the_swivel_turns_the_jaws_not_the_work(engine, channel):
    """Swivelling the jaws under unturned work closes them on the work's extent across
    the turned jaw line, not its square width: the angle reaches the placement."""
    step = channel
    hold = _vise(12.0)
    hold["jaws_angle_deg"] = 30.0
    setup = engine.run(engine.job(step, setups=[_setup([], hold)]))["setups"]["S1"]
    # 60 x 40 seen across a jaw line at 30 degrees: 60 sin 30 + 40 cos 30.
    assert setup["width_mm"] == pytest.approx(30.0 + 40.0 * math.cos(math.radians(30.0)), abs=1e-4)
    assert setup["parallel_pair"] is False
