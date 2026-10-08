"""Numerical controls: drill cones, ABS zero/check moves, RPM policy and a scratch
one-hole mill bundle checked through the CLI for route, hold and endpoint stops."""

import json

import pytest
from test_cli import run_cli

from prechips.rules.speeds_feeds import nearest50
from prechips.rules.tip_endpoints import drill_point_mm
from prechips.rules.zero_recipe import axis_recipe

# A minimal verified one-setup mill bundle: face the top, spot and through-drill h1.
# Baseline: exit 0 with every required rule passing.
FEATURES = """part = "mini"
units = "mm"
precision = 2
[frames.A]
origin = [0.0, 0.0, 0.0]
x = [1.0, 0.0, 0.0]
y = [0.0, 1.0, 0.0]
z = [0.0, 0.0, 1.0]
[features.top]
kind = "face"
frame = "A"
requirements = []
[features.h1]
kind = "hole"
frame = "A"
at = [20.0, 10.0, 0.0]
dia = [5.95, 6.10]
thru = true
requirements = ["dia", "thru"]
"""
INVENTORY = """[machines.mill]
kind = "mill"
verify = false
[machines.mill.envelope]
[machines.mill.envelope.spindle_to_table_max_mm]
value = 400.0
measured = { by = "test", date = "2026-10-03", instrument = "synthetic height gauge" }
[machines.mill.spindle]
taper = "R8"
rpm_min = 100.0
rpm_max = 3000.0
[machines.mill.envelope.travel_mm.x]
value = 500.0
measured = { by = "test", date = "2026-10-03", instrument = "synthetic steel rule" }
[machines.mill.envelope.travel_mm.y]
value = 200.0
measured = { by = "test", date = "2026-10-03", instrument = "synthetic steel rule" }
[tools.em10]
kind = "endmill"
dia_mm = 10.0
shank_mm = 10.0
flutes = 4
material = "HSS"
oal_mm = 70.0
projection_mm = { collet10 = 40.0 }
verify = false
[tools.em6]
kind = "endmill"
dia_mm = 6.0
shank_mm = 10.0
flutes = 4
material = "HSS"
oal_mm = 60.0
projection_mm = { collet10 = 30.0 }
verify = false
[tools.spot]
kind = "spot_drill"
dia_mm = 6.0
point_angle = 90.0
shank_mm = 6.0
material = "HSS"
oal_mm = 60.0
projection_mm = { chuck = 30.0 }
verify = false
[tools.drill6]
kind = "drill"
dia_mm = 6.0
point_angle = 118.0
shank_mm = 6.0
material = "HSS"
oal_mm = 90.0
projection_mm = { chuck = 60.0 }
verify = false
[tools.finder]
kind = "edge_finder"
tip_in = 0.2
finder_type = "mechanical"
rpm_range = [750, 1500]
verify = false
[holders.collet10]
kind = "collet"
taper = "R8"
capacity_mm = 10.0
gauge_len_mm = 30.0
verify = false
[holders.chuck]
kind = "drill_chuck"
taper = "R8"
max_shank_in = 0.5
gauge_len_mm = 60.0
verify = false
[fixtures.vise]
kind = "vise"
bed_height_mm = 50.0
jaw_height_mm = 40.0
length_mm = 300.0
width_mm = 150.0
verify = false
[gauges.pin]
kind = "pin_gauge"
range_mm = [5.0, 7.0]
resolution_mm = 0.001
verify = false
[gauges.dti]
kind = "dial_test_indicator"
resolution_mm = 0.0127
verify = false
"""
CUTTING = 'revision = 1\n[aliases]\nsteel = "low_carbon_steel"\n' + "".join(
    f"""[[cut]]
material_class = "low_carbon_steel"
tool_material = "HSS"
operation = "{operation}"
diameter_range = [1.0, 20.0]
sfm = 90.0
chip_load_mm_per_tooth = 0.05
cite = "scratch row"
"""
    for operation in ("face", "spot", "drill", "pocket")
)
POLICY = """[required]
tool_resolves = "*"
sizing = "toleranced_features"
op_chain = "holes"
blind_depth = "holes"
inspection = "toleranced_features"
coordinates = "*"
zero_check = "setups"
hold_fields = "setups"
order = "setups"
"""
HEADER = """part = "mini"
features = "features.toml"
[paths]
inventory = "inventory.toml"
policy = "policy.toml"
cutting_data = "cutting.toml"
[stock]
material = "steel"
[dro]
controller = "el400"
mode = "abs"
radius_mode = true
[dro.direction]
x = "right"
y = "away"
z = "up"
"""


# A setup that mounts the vise squares its fixed jaw to the table travel (hold_fields
# align_due); a later setup on the same vise, jaws unturned, keeps it and declares none.
ALIGN = 'align = { indicator = "dti", limit_mm = 0.0254, over_mm = 100.0, cite = "scratch" }\n'


def setup(sid, retouch, extra="", align=ALIGN):
    return f"""[[setups]]
id = "{sid}"
machine = "mill"
frame = "A"
coolant = "flood"
deburr_mm = 0.2
{extra}[setups.stock_state]
top_z = 0.5
bottom_z = -10.0
[setups.stock_state.local_thickness]
h1 = 10.0
[setups.hold]
fixture = "vise"
jaws_along = "x"
fixed_jaw = "rear"
{align}stop = "left"
grip_mm = 5.0
clamp = "snug"
[setups.zero.x]
edge = "left"
from = "-x"
tool = "finder"
edge_mm = 0.0
check_jog_mm = 10.0
[setups.zero.y]
edge = "front"
from = "-y"
tool = "finder"
edge_mm = 0.0
check_jog_mm = 10.0
[setups.zero.z]
face = "top"
method = "paper"
paper_mm = 0.05
tool = "em10"
check_jog_mm = 10.0
retouch_after = {retouch}
"""


def face(op=10):
    return f"""[[setups.ops]]
op = {op}
do = "face"
feature = "top"
tool = "em10"
holder = "collet10"
to_z = 0.0
direction = "climb"
"""


def spot(op=20):
    return f"""[[setups.ops]]
op = {op}
do = "spot"
feature = "h1"
tool = "spot"
holder = "chuck"
depth_mm = 1.0
"""


def drill(op=30, exit_mm=1.0):
    return f"""[[setups.ops]]
op = {op}
do = "drill"
feature = "h1"
tool = "drill6"
holder = "chuck"
exit_mm = {exit_mm}
checks = {{ dia = "pin" }}
"""


def release(op):
    return f'[[setups.ops]]\nop = {op}\ndo = "release"\nfeature = "top"\n'


def check(tmp_path, *setups):
    for name, text in (
        ("features.toml", FEATURES),
        ("inventory.toml", INVENTORY),
        ("cutting.toml", CUTTING),
        ("policy.toml", POLICY),
        ("plan.toml", HEADER + "".join(setups)),
    ):
        (tmp_path / name).write_text(text, encoding="utf-8")
    out = tmp_path / "out"
    result = run_cli("check", tmp_path / "plan.toml", "--out", out)
    assert result.returncode in {0, 2, 4}, result.stderr
    report = json.loads((out / "report.json").read_bytes())
    return result.returncode, {(f["rule"], f["subject"]): f for f in report["findings"]}


def one_setup(*ops):
    return setup("S1", "[10, 20]") + "".join(ops)


def test_release_may_precede_the_next_setups_cuts(tmp_path, freecad_kernel):
    # PLAN's own route: release the part from S1, then S2 cuts again.
    s1 = one_setup(face(), spot(), drill(), release(40))
    s2 = setup("S2", "[10]", 'stock_in = "S1"\n', align="") + face()
    code, findings = check(tmp_path, s1, s2)
    assert findings[("order", "S1")]["status"] == "pass"
    assert code == 0


def test_release_before_a_same_setup_cut_is_an_order_error(tmp_path):
    code, findings = check(tmp_path, one_setup(face(), spot(), release(25), drill()))
    row = findings[("order", "S1")]
    assert row["status"] == "error"
    [violation] = row["numbers"]["violations"]
    assert "op 25" in violation and "release" in violation
    assert code == 2


@pytest.mark.parametrize("exit_mm,tip_z", [(0.0, -11.802582), (1.0, -12.802582)])
def test_nonnegative_through_exit_allowance_sets_the_drill_stop(
    tmp_path, freecad_kernel, exit_mm, tip_z
):
    code, findings = check(tmp_path, one_setup(face(), spot(), drill(exit_mm=exit_mm)))
    row = findings[("blind_depth", "h1")]
    assert row["status"] == "pass"
    assert row["numbers"]["endpoints"][-1]["tip_z"] == pytest.approx(tip_z)
    assert code == 0


def test_negative_through_exit_allowance_is_an_error_without_a_stop(tmp_path):
    # -3 mm leaves the full 6 mm diameter 3 mm short of the exit face at Z -10.
    code, findings = check(tmp_path, one_setup(face(), spot(), drill(exit_mm=-3.0)))
    row = findings[("blind_depth", "h1")]
    assert row["status"] == "error"
    assert "exit" in row["message"].lower()
    endpoint = row["numbers"]["endpoints"][-1]
    assert endpoint["exit_mm"] == -3.0
    assert endpoint["tip_z"] == "unknown"
    assert code == 2


def pocket(action, direction=""):
    return f"""[[setups.ops]]
op = 40
do = "{action}"
feature = "top"
tool = "em6"
holder = "collet10"
to_z = -2.0
{direction}"""


@pytest.mark.parametrize("action", ["pocket", "rough_pocket", "finish_pocket"])
def test_pocket_cut_needs_a_direction(tmp_path, action):
    code, findings = check(tmp_path, one_setup(face(), spot(), drill(), pocket(action)))
    row = findings[("hold_fields", "S1")]
    assert row["status"] == "error"
    assert row["numbers"]["missing"] == ["ops.40.direction"]
    assert code == 2


def test_directed_pocket_and_undirected_point_and_manual_ops_pass(tmp_path, freecad_kernel):
    ops = (face(), spot(), drill(), pocket("pocket", 'direction = "climb"\n'), release(50))
    code, findings = check(tmp_path, one_setup(*ops))
    row = findings[("hold_fields", "S1")]
    assert row["status"] == "pass"
    assert row["numbers"]["cut_directions"] == {"10": "climb", "40": "climb"}
    assert code == 0


def test_drill_before_its_spot_is_an_order_error(tmp_path):
    code, findings = check(tmp_path, one_setup(face(), drill(20), spot(30)))
    row = findings[("order", "S1")]
    assert row["status"] == "error"
    [violation] = row["numbers"]["violations"]
    assert "op 20" in violation and "spot" in violation
    assert code == 2


def test_spot_then_drill_order_passes(tmp_path, freecad_kernel):
    code, findings = check(tmp_path, one_setup(face(), spot(), drill()))
    assert findings[("order", "S1")]["status"] == "pass"
    assert code == 0


@pytest.mark.parametrize(
    "diameter,angle,expected", [(6.0, 90.0, 3.0), (10.0, 120.0, 2.886751345948129)]
)
def test_drill_point(diameter, angle, expected):
    assert drill_point_mm(diameter, angle) == pytest.approx(expected)


@pytest.mark.parametrize("angle", [float.fromhex("0x0.0000000000001p-1022"), 1e-310])
def test_an_unrepresentable_drill_cone_stays_unknown(angle):
    # These are positive finite angles, but the radian half-angle underflows to zero
    # or the resulting cone depth exceeds the finite floating-point range.
    assert drill_point_mm(6.0, angle) == "unknown"


@pytest.mark.parametrize(
    "diameter,angle", [(0, 118), (6, 0), (6, 180), ("unknown", 118), (6, "unknown")]
)
def test_missing_or_invalid_drill_geometry(diameter, angle):
    assert drill_point_mm(diameter, angle) == "unknown"


@pytest.mark.parametrize(
    "approach,sign,contact,expected,mirror",
    [
        ("-x", 1, -2.54, 7.46, -12.54),
        ("-x", -1, -2.54, -12.54, 7.46),
        ("+x", 1, 2.54, 12.54, -7.46),
    ],
)
def test_finder_side_is_independent_of_direction(approach, sign, contact, expected, mirror):
    row = axis_recipe(0.0, 2.54, approach, "x", 10.0, sign)
    assert row["axis_set"] == pytest.approx(contact)
    assert row["check_reading"] == pytest.approx(expected)
    assert row["mirrored_reading"] == pytest.approx(mirror)


def test_paper_compensation_and_check_jog():
    row = axis_recipe(9.53, "not_applicable", "+z", "z", 10.0, paper_mm=0.05)
    assert row["axis_set"] == pytest.approx(9.58)
    assert row["check_reading"] == pytest.approx(19.58)
    assert row["mirrored_reading"] == pytest.approx(-0.42)


@pytest.mark.parametrize("scale,shown", [(2, 6.35), (1, 3.175)])
def test_display_scale_applies_to_the_contact_and_the_jog(scale, shown):
    # A +x touch on a 6.35 mm gauge at the axis: physical contact is its radius.
    row = axis_recipe(0.0, 3.175, "+x", "x", 10.0, scale=scale)
    assert row["axis_set"] == pytest.approx(shown)
    assert row["check_reading"] == pytest.approx(shown + 10.0 * scale)
    assert row["mirrored_reading"] == pytest.approx(shown - 10.0 * scale)


def test_unknown_display_scale_leaves_a_nonzero_contact_unknown():
    row = axis_recipe(0.0, 3.175, "+x", "x", 10.0, scale="unknown")
    assert row["axis_set"] == row["check_reading"] == "unknown"


@pytest.mark.parametrize(
    "raw,low,high,expected",
    [
        (1024.9, 50, 3000, 1000),
        (1025, 50, 3000, 1000),
        (1075, 50, 3000, 1100),
        (1499, 50, 3000, 1500),
        (4000, 50, 3000, 3000),
        (1, 70, 2200, 70),
        (9999, 50, 2180, 2180),
        (125, 120, 130, 120),
        (300, 150, 100, "unknown"),
        (40, 75, 3000, 75),
        (1040, 50, 1025, 1025),
    ],
)
def test_rpm_nearest50_ties_and_boundaries(raw, low, high, expected):
    assert nearest50(raw, low, high) == expected
