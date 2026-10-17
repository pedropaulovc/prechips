"""Built-up pre-join cuts are judged against their own component's share (#294).

The shipped rocker STEP (exact bytes) as a built-up part: a round-bar ``hub`` pressed
into a flat-bar ``strap``. S0A faces strap datum B, S0B turns the strap over and faces
the other side, T1 drills and reams the strap socket, H1 turns the hub land, J1 presses
the hub in and R1 reams the pivot bore through the joined hub. The pivot bore lies in
the hub's share, so before J1 it reserves none of the strap's stock: the facings leave
no Ø6.5 island over it and no cutter meets one. After J1 the hub's finished material
protects again: F1 faces datum B on the assembly and G1 receives the hub standing.
"""

import json
import math
import shutil

import pytest
from test_cli import copy_examples, run_cli

ROCKER_TOP = 3.52825  # finished hub face, model Z (rocker features.hub_faces.upper_z)
MEASURED = (
    'measured = { status = "measured", by = "example value (realistic, not a shop '
    'measurement)", date = "2026-10-11", instrument = "example fixture (no physical '
    'measurement)" }'
)
# Test-local socket tools: a 10.0 drill and a 10.21 reamer for the Ø10.200-10.218 socket.
TOOLS = f"""
[tools.strap-socket-drill-10]
kind = "drill"
material = "HSS"
present = true
dia_mm = {{ value = 10.0, {MEASURED} }}
shank_in = {{ value = 0.375, {MEASURED} }}
flutes = 2
point_angle = {{ value = 118.0, {MEASURED} }}
flute_len_mm = {{ value = 40.0, {MEASURED} }}
oal_mm = {{ value = 90.0, {MEASURED} }}
projection_mm = {{ "drill-chuck-r8" = {{ value = 60.0, {MEASURED} }} }}

[tools.strap-socket-reamer-10p21]
kind = "reamer"
material = "HSS"
present = true
dia_mm = {{ value = 10.21, {MEASURED} }}
shank_in = {{ value = 0.375, {MEASURED} }}
flutes = 6
lead_mm = {{ value = 1.0, {MEASURED} }}
flute_len_mm = {{ value = 30.0, {MEASURED} }}
oal_mm = {{ value = 100.0, {MEASURED} }}
projection_mm = {{ "drill-chuck-r8" = {{ value = 60.0, {MEASURED} }} }}
"""


def _frame(name, origin, y=(0.0, 1.0, 0.0), z=(0.0, 0.0, 1.0)):
    return f"""
[frames.{name}]
origin = {list(origin)}
x = [1.0, 0.0, 0.0]
y = {list(y)}
z = {list(z)}
binding = "nominal"
note = "test frame"
cite = ["AUTHOR'S CHOICE: #294 regression route"]
"""


def _face(feature, to_z, sweep_z, bounds_y, bounds_top):
    """The issue's S0A facing raster: a Ø9.525 climb pass over the whole strap."""
    sweep = f"sweep_bounds = {{ x = [-181.0, 181.0], y = [-8.0, 36.0], z = {list(sweep_z)} }}"
    return f"""
[[setups.ops]]
op = 10
do = "finish_face"
feature = "{feature}"
tool = "endmills-lms-6784/3-8in-4fl"
holder = "r8-collets-lms-4860/3-8in"
direction = "climb"
to_z = {to_z}
doc_mm = 0.25
approach_mm = 5.0
stock_removal_bounds = {{ x = [-181.0, 181.0], y = {list(bounds_y)}, z = [{to_z}, {bounds_top}] }}
contour = {{ method = "linear_table", step_mm = 7.0, sweep_frame = "model", {sweep} }}
"""


def _setup(sid, frame, stock_in, machine="PM-30MV"):
    return f"""
[[setups]]
id = "{sid}"
machine = "{machine}"
frame = "{frame}"
stock_in = {json.dumps(stock_in)}
"""


PLAN = (
    """
part = "rocker-arm"
features = "features.toml"
construction = "built_up"
quantity = 1
[paths]
inventory = "../inventory/pedro-shop.toml"
policy = "../shop-policy.toml"
cutting_data = "../cutting-data.toml"
[stock]
form = "built_up"
material = "1018 low-carbon steel"
as_is_faces = []
cite = ["AUTHOR'S CHOICE: #294 regression route"]
[[stock.components]]
id = "hub"
form = "round_bar"
dia_mm = 11.1125
length_mm = 8.4
origin_mm = [0.0, 8.0, 4.2]
axis = [0.0, 0.0, -1.0]
cite = ["AUTHOR'S CHOICE: #294 regression route"]
[[stock.components]]
id = "strap"
form = "flat_bar"
section_mm = [40.0, 3.0]
length_mm = 350.0
origin_mm = [-175.0, -6.0, -1.5]
axis = [1.0, 0.0, 0.0]
section_axis = [0.0, 1.0, 0.0]
cite = ["AUTHOR'S CHOICE: #294 regression route"]
"""
    + _frame("SA", (0.0, 8.0, -1.5))
    + _frame("SB", (0.0, 8.0, 1.25), y=(0.0, -1.0, 0.0), z=(0.0, 0.0, -1.0))
    + _frame("T1", (0.0, 8.0, 1.25))
    + _frame("H1", (0.0, 8.0, 0.0))
    + _frame("R1", (0.0, 8.0, ROCKER_TOP))
    + """
[joint_features.strap_hole]
kind = "cylinder_bore"
component = "strap"
at = [0.0, 8.0, 1.25]
axis = [0.0, 0.0, -1.0]
dia = [10.200, 10.218]
nominal_dia = 10.209
depth = 2.5
thru = true
cite = ["AUTHOR'S CHOICE: #294 regression route"]
[joint_features.hub_land]
kind = "cylinder_spigot"
component = "hub"
at = [0.0, 8.0, 4.2]
axis = [0.0, 0.0, -1.0]
dia = [10.223, 10.234]
nominal_dia = 10.2285
depth = 8.4
thru = false
cite = ["AUTHOR'S CHOICE: #294 regression route"]
"""
    + _setup("S0A", "SA", "stock.strap")
    + _face("strap_datum_b", 2.75, (1.25, 1.5), (-16.0, 28.0), 3.5)
    + _setup("S0B", "SB", "S0A")
    + """
[setups.stock_state]
top_z = 2.75
bottom_z = 0.0
"""
    + _face("strap_faces", 2.5, (-1.5, -1.25), (-28.0, 16.0), 3.5)
    + _setup("T1", "T1", "S0B")
    + """
[[setups.ops]]
op = 10
do = "drill"
feature = "strap_hole"
tool = "strap-socket-drill-10"
holder = "drill-chuck-r8"
exit_mm = 1.0
approach_mm = 5.0
[[setups.ops]]
op = 20
do = "ream"
feature = "strap_hole"
tool = "strap-socket-reamer-10p21"
holder = "drill-chuck-r8"
exit_mm = 1.5
approach_mm = 5.0
"""
    + _setup("H1", "H1", "stock.hub", machine="PM-1127VF-LB")
    + """
[[setups.ops]]
op = 10
do = "finish_turn"
feature = "hub_land"
tool = "turning-tools-warner-lms-4132/AR"
holder = "qctp-axa-lms-2280/1-turning-facing"
z_from = 4.2
z_to = -4.2
direction = "toward_chuck"
doc_mm = 0.4
feed_mm_rev = 0.05
approach_mm = 3.0
"""
    + _setup("J1", "T1", ["T1", "H1"])
    + """
[setups.joint]
kind = "cylindrical"
socket = "strap_hole"
spigot = "hub_land"
fit = "interference"
interference_mm = [0.005, 0.034]
method = "press"
process = "press the hub into the strap socket"
cite = ["AUTHOR'S CHOICE: #294 regression route"]
[[setups.ops]]
op = 10
do = "fit"
feature = "hub_od"
"""
    + _setup("R1", "R1", "J1")
    + """
[[setups.ops]]
op = 10
do = "drill"
feature = "pivot_bore"
tool = "drill-index-115/D"
holder = "drill-chuck-r8"
exit_mm = 2.0
approach_mm = 5.0
[[setups.ops]]
op = 20
do = "ream"
feature = "pivot_bore"
tool = "reamers-metric/6.5mm"
holder = "drill-chuck-r8"
exit_mm = 2.0
approach_mm = 5.0
"""
    + _setup("F1", "SA", "J1")
    + _face("strap_datum_b", 2.75, (1.25, 1.5), (-16.0, 28.0), 6.0)
    + _setup("G1", "SA", "F1")
    + """
[[setups.ops]]
op = 10
do = "inspect"
feature = "strap_faces"
"""
)


@pytest.fixture(scope="module")
def built_up_rocker(tmp_path_factory, pilot_kernel_cache):
    tmp_path = tmp_path_factory.mktemp("built-up-rocker")
    examples = copy_examples(tmp_path)
    bundle = examples / "rocker-built-up"
    bundle.mkdir()
    shutil.copyfile(examples / "rocker-arm" / "rocker-arm.STEP", bundle / "rocker-arm.STEP")
    features = (examples / "rocker-arm" / "features.toml").read_text(encoding="utf-8")
    one_piece = '"construction" = "one_piece"'
    assert features.count(one_piece) == 1
    (bundle / "features.toml").write_text(
        features.replace(one_piece, '"construction" = "built_up_permitted"'), encoding="utf-8"
    )
    inventory = examples / "inventory" / "pedro-shop.toml"
    inventory.write_text(inventory.read_text(encoding="utf-8") + TOOLS, encoding="utf-8")
    plan = bundle / "plan.toml"
    plan.write_text(PLAN, encoding="utf-8")
    facts = pilot_kernel_cache(plan)
    out = tmp_path / "out"
    result = run_cli("check", plan, "--out", out)
    report = json.loads((out / "report.json").read_bytes())
    assert result.returncode == report["expected_exit"], result.stderr
    return report, facts


def _finding(report, rule, subject):
    return next(
        row for row in report["findings"] if row["rule"] == rule and row["subject"] == subject
    )


@pytest.mark.parametrize("subject", ["S0A:10", "S0B:10"])
def test_prejoin_strap_facing_meets_no_hub_material(built_up_rocker, subject):
    report, facts = built_up_rocker
    row = _finding(report, "accessibility", subject)
    # No fixture solids are declared, so the verdict stays unknown, but no sample is hit.
    assert row["status"] == "unknown", row
    assert row["numbers"]["certain_tool_hits"] == row["numbers"]["certain_holder_hits"] == 0
    assert "hit_owners" not in row["numbers"]
    op = facts["ops"][subject]
    assert op["min_hits"] == {"tool": 0, "holder": 0}
    assert op["hit_refs"] == {"tool": [], "holder": []}


def test_prejoin_strap_facings_leave_flat_entry_stock(built_up_rocker):
    report, facts = built_up_rocker
    setups = facts["setups"]
    # S0A faces 0.25 off the 40 x 3 x 350 strap: no island over the hub's pivot bore.
    assert setups["S0B"]["stock_bbox_mm"] == [-175.0, -26.0, 0.0, 175.0, 14.0, 2.75]
    assert setups["S0B"]["stock_volume_mm3"] == pytest.approx(350 * 40 * 2.75, abs=1e-6)
    assert setups["T1"]["stock_bbox_mm"] == [-175.0, -14.0, -2.5, 175.0, 26.0, 0.0]
    assert setups["T1"]["stock_volume_mm3"] == pytest.approx(350 * 40 * 2.5, abs=1e-6)
    consistency = _finding(report, "consistency", "S0B")
    assert consistency["status"] != "error", consistency
    assert consistency["numbers"]["contradictions"] == []


def test_joined_hub_still_protects_its_finished_material(built_up_rocker):
    _, facts = built_up_rocker
    setups = facts["setups"]
    # J1 presses the turned Ø10.2285 x 8.4 hub through the 2.5 mm strap's reamed socket.
    hub = math.pi * (10.2285 / 2) ** 2
    assert setups["J1"]["stock_volume_mm3"] == pytest.approx(
        350 * 40 * 2.5 + hub * (8.4 - 2.5), abs=1e-3
    )
    # F1 faces datum B on the assembly: it takes the hub's raw top (SA Z 5.7) but the
    # finished hub face (SA Z 5.02825) stays, with the pivot bore's column for R1.
    entry = setups["F1"]["stock_bbox_mm"]
    left = setups["G1"]["stock_bbox_mm"]
    assert entry[5] == pytest.approx(4.2 + 1.5, abs=1e-6)
    assert ROCKER_TOP + 1.5 <= left[5] < entry[5]
    assert setups["G1"]["stock_volume_mm3"] < setups["F1"]["stock_volume_mm3"]
    assert facts["ops"]["F1:10"]["min_hits"]["tool"] == 0
