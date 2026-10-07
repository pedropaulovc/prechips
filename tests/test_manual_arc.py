"""Manual-mill arcs (docs/plan.md "Manual arcs"): the PM-30MV moves one handwheel at a time.

An arc is laid out on the part, roughed outside the line in single-axis stairs or a chain
of drilled holes, then filed to the line against filing buttons or a template and checked
with a radius gauge; or it is cut as straight chords, or turned under the cutter on a
rotary table. Every stair corner and hole stays outside the finished line, the file never
meets more than the shop's cap, chords stay inside the radial band, and every unknown
input stays unknown, never a pass.
"""

import dataclasses
import itertools
import math

import pytest

from prechips.inputs import load_bundle
from prechips.rules import coordinates, manual_arc

# A Ø19.8-20.2 boss about model (20, 10): frame A puts its centre at setup (15, 8); the
# rotary frame puts it on the table axis at setup X0 Y0. Its R9.9-R10.1 band is 0.2 wide.
ARC = (
    "kind = 'boss'\nrequirements = ['dia']\nat = [20.0, 10.0, 0.0]\ndia = [19.8, 20.2]\n"
    "dia_nominal = 20.0\n"
)
SHIFTED = "[5.0, 2.0, 1.0]"
ON_AXIS = "[20.0, 10.0, 1.0]"
CAP = 0.5
POLICY = (
    '[required]\ncoordinates = "*"\nmanual_arc = "*"\n'
    f"[numbers]\nmax_filing_stock_mm = {CAP}\n"
    '[numbers_cite]\nmax_filing_stock_mm = "example filing cap"\n'
    "[numbers_verify]\nmax_filing_stock_mm = false\n"
)
INVENTORY = (
    "[machines.mill]\nkind = 'mill'\nverify = false\n"
    "[machines.mill.spindle]\nrotation = 'cw'\n"
    "[tools.cutter]\nkind = 'endmill'\ndia_mm = 6.0\nverify = false\n"
    "[tools.drill]\nkind = 'drill'\ndia_mm = 3.0\npoint_angle = 118.0\nverify = false\n"
    "[tools.bore-drill]\nkind = 'drill'\ndia_mm = 6.0\npoint_angle = 118.0\nverify = false\n"
    "[fixtures.table]\nkind = 'rotary_table'\ngraduation_deg = 1.0\nvernier_deg = 0.1\n"
    "dial_increases = 'clockwise'\nmax_work_mm = 150.0\nverify = false\n"
    "[fixtures.buttons]\nkind = 'filing_buttons'\ndia_mm = 20.0\nbore_dia_mm = 6.0\n"
    "verify = false\n"
    "[gauges.radius-gauge]\nkind = 'radius_gauge'\nrange_mm = [1.0, 25.0]\nverify = false\n"
    "[gauges.small-gauge]\nkind = 'radius_gauge'\nrange_mm = [1.0, 7.5]\nverify = false\n"
    "[gauges.template]\nkind = 'profile_gauge'\nrange_mm = [9.0, 11.0]\nverify = false\n"
)


def op(number, action, contour=None, *, feature="target", tool="cutter", allowance=None, **more):
    text = (
        f"[[setups.ops]]\nop = {number}\ndo = '{action}'\nfeature = '{feature}'\n"
        f"tool = '{tool}'\nholder = 'unknown'\nto_z = -1.0\ndirection = 'conventional'\n"
    )
    if allowance is not None:
        text += f"rough_allowance_mm = {allowance}\n"
    if contour is not None:
        text += f"contour = {contour}\n"
    return text + "".join(f"{key} = {value}\n" for key, value in more.items())


def bench_op(number, action, **more):
    text = f"[[setups.ops]]\nop = {number}\ndo = '{action}'\nfeature = 'target'\n"
    return text + "".join(f"{key} = {value}\n" for key, value in more.items())


DRILL_BORE = op(10, "drill", feature="bore", tool="bore-drill")


def scratch(
    tmp_path, ops, *, origin=SHIFTED, hold="fixture = 'unknown'", policy=POLICY, target=ARC
):
    """A one-setup mill bundle cutting ``ops`` (TOML text) on the banded ``target`` (the
    boss :data:`ARC` unless given) with the hole ``bore`` on its axis and ``offset`` beside
    it."""
    root = tmp_path / "manual-arc"
    root.mkdir(parents=True)
    plan = root / "plan.toml"
    plan.write_text(
        'part = "manual-arc"\nfeatures = "features.toml"\n'
        "[paths]\ninventory = 'inventory.toml'\npolicy = 'policy.toml'\n"
        "cutting_data = 'cutting.toml'\n"
        "[[setups]]\nid = 'S1'\nmachine = 'mill'\nframe = 'A'\n"
        "coolant = 'unknown'\ndeburr_mm = 'unknown'\n"
        f"[setups.hold]\n{hold}\n"
        "[setups.stock_state]\ntop_z = 0.0\nbottom_z = -10.0\n"
        "local_thickness = { target = 10.0 }\n" + ops,
        encoding="utf-8",
    )
    (root / "features.toml").write_text(
        'part = "manual-arc"\nunits = "mm"\nprecision = 2\n'
        f"[frames.A]\norigin = {origin}\n"
        "x = [1.0, 0.0, 0.0]\ny = [0.0, 1.0, 0.0]\nz = [0.0, 0.0, 1.0]\n"
        'binding = "measured"\n'
        "[frames.model]\norigin = [0.0, 0.0, 0.0]\n"
        "x = [1.0, 0.0, 0.0]\ny = [0.0, 1.0, 0.0]\nz = [0.0, 0.0, 1.0]\n"
        f"[features.target]\nframe = 'model'\n{target}"
        "[features.bore]\nkind = 'hole'\nframe = 'model'\nrequirements = []\n"
        "at = [20.0, 10.0, 0.0]\ndia = [6.0, 6.03]\nthru = true\n"
        "[features.offset]\nkind = 'hole'\nframe = 'model'\nrequirements = []\n"
        "at = [26.0, 10.0, 0.0]\ndia = [6.0, 6.03]\nthru = true\n",
        encoding="utf-8",
    )
    (root / "inventory.toml").write_text(INVENTORY, encoding="utf-8")
    (root / "policy.toml").write_text(policy, encoding="utf-8")
    (root / "cutting.toml").write_text("revision = 1\n", encoding="utf-8")
    return plan


def coordinates_row(plan, stock_bbox=None):
    bundle = load_bundle(plan)
    if stock_bbox is not None:
        kernel = {"status": "ok", "setups": {"S1": {"stock_bbox_mm": stock_bbox}}}
        bundle = dataclasses.replace(bundle, kernel=kernel)
    return next(row for row in coordinates.evaluate(bundle) if row.subject == "S1")


def manual_row(plan, number):
    rows = {row.subject: row for row in manual_arc.evaluate(load_bundle(plan))}
    return rows[f"S1:{number}"]


def arcs(row, number):
    return [table for table in row.numbers["arc_table"] if table["op"] == number]


def errors(row):
    return " ".join(row.numbers.get("arc_errors", []))


def debts(row):
    return " ".join(row.numbers.get("arc_debts", []))


def legs(points, samples=16):
    for a, b in itertools.pairwise(points):
        for k in range(samples + 1):
            yield [a[i] + k / samples * (b[i] - a[i]) for i in range(2)]


def on_grid(value, step=0.001):
    return abs(value / step - round(value / step)) < 1e-6


def test_stairs_step_one_handwheel_at_a_time_outside_the_line(tmp_path):
    row = coordinates_row(
        scratch(
            tmp_path,
            op(20, "rough_profile", "{ method = 'stairs', cusp_mm = 0.25 }", allowance=0.2),
        )
    )
    assert row.status == "pass", row.sentence
    (table,) = arcs(row, 20)
    printed = [r["dro_xy"] for r in table["rows"]]
    assert all(r["jog"] in {"X", "Y"} for r in table["rows"][1:])
    for a, b in itertools.pairwise(printed):
        assert a[0] == b[0] or a[1] == b[1], f"{a} -> {b} moves two handwheels"
    # Every point the cutter edge sweeps stays outside the R10.1 line.
    assert min(math.dist(p, (15.0, 8.0)) for p in legs(printed)) - 3.0 >= 10.1 - 1e-6
    assert table["line_clear_mm"] >= 0
    assert table["stock_left_mm"] == pytest.approx(0.2 + table["stair_cusp_mm"])
    assert table["stock_left_mm"] <= table["stock_cap_mm"] == CAP


# A concave R29.9-R30.1 arc about model (20, 40) spanning ±36.87° about its lowest point,
# part below it, like the rocker's top edge: the cutter centre dips to that point.
DISH = (
    "kind = 'profile'\nrequirements = ['radius']\nradius = [29.9, 30.1]\nradius_nominal = 30.0\n"
    "arc_centre = [20.0, 40.0, 0.0]\nend = [38.0, 16.0]\n"
)


@pytest.mark.parametrize("target", [ARC, DISH], ids=["convex", "concave"])
def test_a_stair_never_steps_one_handwheel_twice_running(tmp_path, target):
    # A row where the arc is tangent to a setup axis is reached and left on one handwheel:
    # printed as its own stop, it splits one move, or (the concave dip) runs the handwheel
    # down and straight back up through backlash. Each move turns the other handwheel.
    row = coordinates_row(
        scratch(
            tmp_path,
            op(20, "rough_profile", "{ method = 'stairs', cusp_mm = 0.25 }", allowance=0.2),
            target=target,
        )
    )
    assert row.status == "pass", row.sentence
    (table,) = arcs(row, 20)
    jogs = [r["jog"] for r in table["rows"][1:]]
    assert all(a != b for a, b in itertools.pairwise(jogs)), jogs
    assert table["stair_cusp_mm"] <= table["cusp_mm"]


@pytest.mark.parametrize(
    ("contour", "tool", "message"),
    [
        ("{ method = 'stairs', cusp_mm = 0.25 }", "cutter", "past the line"),
        ("{ method = 'chain_drill', pitch_mm = 5.0 }", "drill", "past the line"),
    ],
    ids=["stair", "hole"],
)
def test_a_stair_corner_or_hole_inside_the_line_is_an_error(tmp_path, contour, tool, message):
    row = coordinates_row(
        scratch(tmp_path, op(20, "rough_profile", contour, tool=tool, allowance=-0.3))
    )
    assert row.status == "error"
    assert message in errors(row)
    assert not arcs(row, 20), "a refused manual arc prints no table"


CHAIN = op(
    20, "rough_profile", "{ method = 'chain_drill', pitch_mm = 5.0 }", tool="drill", allowance=0.2
)


def test_chain_drill_keeps_every_full_hole_outside_and_a_web_between(tmp_path):
    # Broken out along the hole centres, a chain leaves 0.2 + a 1.5 drill radius: more than
    # the 0.5 cap, so the chain alone is refused and a finer stair rough must follow it.
    alone = coordinates_row(scratch(tmp_path / "alone", CHAIN))
    assert alone.status == "error"
    assert "chain drill leaves up to 1.700 for the file, more than the shop's 0.5 cap" in errors(
        alone
    )
    stairs = op(30, "rough_profile", "{ method = 'stairs', cusp_mm = 0.25 }", allowance=0.2)
    row = coordinates_row(scratch(tmp_path / "recut", CHAIN + stairs))
    assert row.status == "pass", row.sentence
    (table,) = arcs(row, 20)
    holes = [r["dro_xy"] for r in table["rows"]]
    assert all(math.dist(p, (15.0, 8.0)) - 1.5 >= 10.1 - 1e-6 for p in holes)
    assert all(math.dist(a, b) > 3.0 for a, b in itertools.pairwise(holes))
    assert table["stock_left_mm"] == pytest.approx(1.7) and table["recut_by"] == "S1 op 30"


def test_chain_drill_holes_closer_than_a_drill_leave_no_web(tmp_path):
    row = coordinates_row(
        scratch(
            tmp_path,
            op(
                20,
                "rough_profile",
                "{ method = 'chain_drill', pitch_mm = 2.0 }",
                tool="drill",
                allowance=0.2,
            ),
        )
    )
    assert row.status == "error"
    assert "no web" in errors(row)


def test_filing_stock_over_the_cap_is_an_error_unless_a_later_rough_recuts_it(tmp_path):
    coarse = op(20, "rough_profile", "{ method = 'stairs', cusp_mm = 0.4 }", allowance=0.45)
    row = coordinates_row(scratch(tmp_path / "alone", coarse))
    assert row.status == "error"
    assert "more than the shop's 0.5 cap" in errors(row)
    fine = op(30, "rough_profile", "{ method = 'stairs', cusp_mm = 0.1 }", allowance=0.2)
    row = coordinates_row(scratch(tmp_path / "recut", coarse + fine))
    assert row.status == "pass", row.sentence
    (first,), (second,) = arcs(row, 20), arcs(row, 30)
    assert first["recut_by"] == "S1 op 30" and "stock_cap_mm" not in first
    assert second["stock_left_mm"] <= second["stock_cap_mm"] == CAP


@pytest.mark.parametrize(
    "policy",
    [
        '[required]\ncoordinates = "*"\n',
        POLICY.replace("max_filing_stock_mm = false", "max_filing_stock_mm = true"),
        POLICY.replace(
            'max_filing_stock_mm = "example filing cap"', 'max_filing_stock_mm = "unknown"'
        ),
        POLICY.replace(f"max_filing_stock_mm = {CAP}", "max_filing_stock_mm = -0.1"),
    ],
    ids=["absent", "verify", "uncited", "negative"],
)
def test_an_unestablished_filing_cap_is_unknown_never_a_pass(tmp_path, policy):
    row = coordinates_row(
        scratch(
            tmp_path,
            op(20, "rough_profile", "{ method = 'stairs', cusp_mm = 0.25 }", allowance=0.2),
            policy=policy,
        )
    )
    assert row.status == "unknown"
    assert "sets no max_filing_stock_mm" in debts(row)


def test_an_unknown_cutter_leaves_the_stairs_unknown(tmp_path):
    plan = scratch(
        tmp_path, op(20, "rough_profile", "{ method = 'stairs', cusp_mm = 0.25 }", allowance=0.2)
    )
    inventory = plan.with_name("inventory.toml")
    inventory.write_text(
        inventory.read_text(encoding="utf-8").replace(
            "dia_mm = 6.0\nverify", "dia_mm = 'unknown'\nverify", 1
        ),
        encoding="utf-8",
    )
    row = coordinates_row(plan)
    assert row.status == "unknown"
    assert not row.numbers.get("arc_errors")


@pytest.mark.parametrize("method", ["stairs", "chain_drill"])
def test_rough_methods_cannot_finish_the_line(tmp_path, method):
    need = "cusp_mm = 0.25" if method == "stairs" else "pitch_mm = 5.0"
    row = coordinates_row(
        scratch(tmp_path, op(20, "finish_profile", f"{{ method = '{method}', {need} }}"))
    )
    assert row.status == "error"
    assert "only roughs outside the line" in errors(row)


def test_authored_arc_table_is_an_error(tmp_path):
    row = coordinates_row(
        scratch(tmp_path, op(20, "finish_profile", "{ method = 'arc_table', step_deg = 30.0 }"))
    )
    assert row.status == "error"
    assert "arc_table moves two handwheels at once" in errors(row)
    assert not arcs(row, 20)


def chords(tmp_path, count, hold="fixture = 'table'"):
    return coordinates_row(
        scratch(
            tmp_path,
            op(20, "finish_profile", f"{{ method = 'chords', count = {count} }}"),
            hold=hold,
        )
    )


def test_chord_sagitta_wider_than_the_band_is_an_error(tmp_path):
    # Eight chords on R10 leave a 0.76 sagitta; the band is 0.2.
    row = chords(tmp_path, 8)
    assert row.status == "error"
    assert "sagitta" in errors(row) and "radial band" in errors(row)


def test_chords_are_proven_inside_the_band_with_cuts_on_the_dro_grid(tmp_path):
    row = chords(tmp_path, 24)
    assert row.status == "pass", row.sentence
    (table,) = arcs(row, 20)
    assert table["sagitta_mm"] <= 0.2 and table["indexed"] is True
    assert len(table["chords"]) == 24
    for chord in table["chords"]:
        low, high = chord["face_radius_mm"]
        assert 9.9 - 1e-6 <= low <= high <= 10.1 + 1e-6
        cut = chord["cut"]
        assert cut["along"] == "X" and on_grid(cut["index_deg"], 0.1)
        assert all(on_grid(cut[key]) for key in ("at", "from", "to"))
    assert all(on_grid(v) for r in table["rows"] for v in r["dro_xy"])


def test_slanted_chords_without_a_rotary_table_are_an_error(tmp_path):
    row = chords(tmp_path, 16, hold="fixture = 'unknown'")
    assert row.status == "error"
    assert "index each chord square to X on a rotary table" in errors(row)


def rotary(tmp_path, *, origin=ON_AXIS, hold="fixture = 'table'", centre="bore", ops=DRILL_BORE):
    contour = (
        "{ method = 'rotary_table', step_deg = 30.0, centre_by = 'pin', "
        f"centre_feature = '{centre}' }}"
    )
    plan = scratch(tmp_path, ops + op(20, "finish_profile", contour), origin=origin, hold=hold)
    return coordinates_row(plan, stock_bbox=[-12.0, -12.0, -10.0, 12.0, 12.0, 0.0])


def test_rotary_table_recipe_locks_the_offset_and_reads_the_dial_on_its_vernier(tmp_path):
    row = rotary(tmp_path)
    assert row.status == "pass", row.sentence
    (table,) = arcs(row, 20)
    recipe = table["rotary"]
    assert recipe["table"] == "table" and recipe["centre_feature"] == "bore"
    assert recipe["pin_dia_mm"] == 6.0
    assert recipe["offset_axis"] == "X" and recipe["offset_mm"] == pytest.approx(13.0)
    assert recipe["resolution_deg"] == 0.1 and recipe["sweep_deg"] == 360.0
    assert on_grid(recipe["start_deg"], 0.1) and recipe["start_deg"] == recipe["stop_deg"]
    assert recipe["rotation"] in {"clockwise", "counterclockwise"}
    assert recipe["work_radius_mm"] <= recipe["max_work_radius_mm"]


@pytest.mark.parametrize(
    ("case", "message"),
    [
        ("off_axis", "off the table axis"),
        ("no_table", "needs the work held on a rotary table"),
        ("not_made", "no earlier drill, ream or bore makes bore"),
        ("wrong_centre", "offset's axis is not the arc centre"),
    ],
)
def test_rotary_table_errors(tmp_path, case, message):
    kwargs = {
        "off_axis": {"origin": SHIFTED},
        "no_table": {"hold": "fixture = 'unknown'"},
        "not_made": {"ops": ""},
        "wrong_centre": {
            "centre": "offset",
            "ops": op(10, "drill", feature="offset", tool="bore-drill"),
        },
    }[case]
    row = rotary(tmp_path, **kwargs)
    assert row.status == "error"
    assert message in errors(row)


def test_rotary_table_without_the_stock_swing_is_unknown(tmp_path):
    contour = (
        "{ method = 'rotary_table', step_deg = 30.0, centre_by = 'pin', centre_feature = 'bore' }"
    )
    plan = scratch(
        tmp_path,
        DRILL_BORE + op(20, "finish_profile", contour),
        origin=ON_AXIS,
        hold="fixture = 'table'",
    )
    row = coordinates_row(plan)
    assert row.status == "unknown"
    assert "stock's swing" in debts(row)


STAIRS = op(20, "rough_profile", "{ method = 'stairs', cusp_mm = 0.25 }", allowance=0.2)
BUTTONS = "{ buttons = 'buttons', bore = 'bore', gauge = 'radius-gauge' }"


def filing(
    tmp_path, guide=BUTTONS, *, ops=DRILL_BORE + STAIRS, hold="fixture = 'buttons'", extra=""
):
    plan = scratch(tmp_path, ops + extra + bench_op(30, "file_to_line", guide=guide), hold=hold)
    return manual_row(plan, 30)


def test_filing_to_buttons_through_the_axis_bore_files_inside_the_band(tmp_path):
    row = filing(tmp_path)
    assert row.status == "pass", row.sentence
    guide = row.numbers["guide"]
    # Ø20 buttons on a Ø6 pin in a Ø6.00-6.03 bore shift at most 0.015 radially.
    assert guide["files_to_mm"] == pytest.approx([9.985, 10.015])
    assert row.numbers["rough_op"] == "S1 op 20" and row.numbers["stock_cap_mm"] == CAP
    assert row.numbers["gauge"]["range_mm"] == [1.0, 25.0]


@pytest.mark.parametrize(
    ("guide", "hold", "message"),
    [
        ("{ gauge = 'radius-gauge' }", "fixture = 'buttons'", "no filing guide"),
        ("{ buttons = 'buttons', bore = 'bore' }", "fixture = 'buttons'", "no radius gauge"),
        (BUTTONS, "fixture = 'unknown'", "not in setup S1's hold"),
        (
            "{ buttons = 'missing', bore = 'bore', gauge = 'radius-gauge' }",
            "fixture = 'buttons'",
            "not a filing_buttons kit",
        ),
        (
            "{ template = 'template', gauge = 'radius-gauge' }",
            "fixture = 'unknown'",
            "no scribe op lays out target",
        ),
    ],
    ids=[
        "no-guide",
        "no-gauge",
        "buttons-not-held",
        "buttons-not-in-inventory",
        "template-no-layout",
    ],
)
def test_missing_filing_kit_is_unknown(tmp_path, guide, hold, message):
    row = filing(tmp_path, guide, hold=hold)
    assert row.status == "unknown"
    assert message in " ".join(row.numbers["debts"])


@pytest.mark.parametrize(
    ("guide", "ops", "message"),
    [
        (
            "{ buttons = 'buttons', bore = 'bore', gauge = 'small-gauge' }",
            None,
            "reads 1 to 7.5 mm, not R10",
        ),
        (
            "{ buttons = 'buttons', bore = 'offset', gauge = 'radius-gauge' }",
            op(10, "drill", feature="offset", tool="bore-drill") + STAIRS,
            "offset is not on the arc's axis",
        ),
        (
            "{ buttons = 'buttons', bore = 'bore', gauge = 'radius-gauge' }",
            STAIRS,
            "not drilled, reamed or bored",
        ),
    ],
    ids=["gauge-range", "bore-off-axis", "bore-not-made"],
)
def test_filing_kit_that_cannot_reach_r_is_an_error(tmp_path, guide, ops, message):
    row = filing(tmp_path, guide, ops=ops if ops is not None else DRILL_BORE + STAIRS)
    assert row.status == "error"
    assert message in " ".join(row.numbers["errors"])


def test_filing_without_a_rough_or_an_established_cap_is_unknown(tmp_path):
    assert "no stairs or chain_drill op roughs target" in " ".join(
        filing(tmp_path / "rough", ops=DRILL_BORE).numbers["debts"]
    )
    plan = scratch(
        tmp_path / "cap",
        DRILL_BORE + STAIRS + bench_op(30, "file_to_line", guide=BUTTONS),
        hold="fixture = 'buttons'",
        policy='[required]\ncoordinates = "*"\n',
    )
    row = manual_row(plan, 30)
    assert row.status == "unknown"
    assert "sets no max_filing_stock_mm" in " ".join(row.numbers["debts"])


def test_template_guide_files_to_the_scribed_layout(tmp_path):
    scribe = bench_op(25, "scribe", layout="'template'", guide="{ template = 'template' }")
    row = filing(
        tmp_path,
        "{ template = 'template', gauge = 'radius-gauge' }",
        hold="fixture = 'unknown'",
        extra=scribe,
    )
    assert row.status == "pass", row.sentence
    assert row.numbers["layout_op"] == "S1:25"
    assert row.numbers["guide"] == {"kind": "template", "kit": "template"}


@pytest.mark.parametrize(("layout", "status"), [("'dividers'", "pass"), ("'chalk'", "unknown")])
def test_scribe_prints_the_centre_radius_and_layout(tmp_path, layout, status):
    plan = scratch(tmp_path, bench_op(10, "scribe", layout=layout))
    row = manual_row(plan, 10)
    assert row.status == status
    assert row.numbers["centre_setup_xy"] == pytest.approx([15.0, 8.0])
    assert row.numbers["radius_mm"] == pytest.approx(10.0)
    assert row.numbers["radius_band_mm"] == pytest.approx([9.9, 10.1])
    assert row.numbers["ends_setup_xy"] is None  # a full circle has no ends
