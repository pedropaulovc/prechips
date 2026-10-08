"""A bounded op's printed cutter-centre tables are the kernel's clip of them.

An op with stock_removal_bounds may remove stock only inside that box, and only the kernel
knows where its cutter first meets stock outside it. The kernel request carries the whole
printed tables; the rule pass prints the kernel's clip (``checkpoint_clips``): the rows it
keeps and its clip points, marked ``clipped_at``. A path left in pieces is fragments plus
debt, never reconnected; no legal part, no kernel result or a clip that does not match
the printed table prints nothing and is unknown, never the unclipped path. Every printed
value rounds to the safe side on the machine's DRO grid: its declared resolution, else
three decimals.
"""

import math
from pathlib import Path

import pytest
from test_headroom import coordinate_bundle

from prechips.inputs import load_bundle
from prechips.rules import coordinates

# A concave R10 arc about the model origin ending at (+-6, -8). Rough stairs leave
# 0.2 mm radial allowance with the 6 mm cutter; frame A subtracts (5, 2) from model XY.
ARC = "kind = 'profile'\nradius = 10.0\narc_centre = [0.0, 0.0, 0.0]\nend = [6.0, -8.0, 0.0]\n"
CENTRE = (-5.0, -2.0)
ROCKER = Path(__file__).resolve().parents[1] / "examples/rocker-arm/plan.toml"
SUBJECT = "S1:20"
TABLE = "S1:20 rough arc"
CONTACT = "first contact with stock outside stock_removal_bounds"


def plan(tmp_path, bounded=True, do="rough_profile", resolution=None, band=None):
    """S1 op 20 cutting the arc to Z -2.07825, bounded by a box unless ``bounded`` is
    False; the mill declares ``resolution`` mm and the arc a thickness ``band``."""
    bounds = (
        "stock_removal_bounds = { x = [-30.0, 30.0], y = [-30.0, 30.0], z = [-5.0, 0.0] }\n"
        if bounded
        else ""
    )
    path = coordinate_bundle(
        tmp_path,
        ARC
        if do == "rough_profile"
        else "kind = 'plane'\nbounds = { x = [0.0, 20.0], y = [0.0, 10.0], z = [-5.0, 0.0] }\n",
        f"[[setups.ops]]\nop = 20\ndo = '{do}'\nfeature = 'target'\n"
        "tool = 'cutter'\nto_z = -2.07825\ndirection = 'conventional'\n"
        "rough_allowance_mm = 0.2\n"
        + (
            "contour = { method = 'stairs', cusp_mm = 0.1 }\n"
            if do == "rough_profile"
            else "contour = { method = 'linear_table' }\n"
        )
        + bounds,
    )
    root = path.parent
    if band is not None:
        features = root / "features.toml"
        text = features.read_text(encoding="utf-8").replace(
            "requirements = []\n", f"requirements = ['thickness']\nthickness = {list(band)}\n"
        )
        features.write_text(text, encoding="utf-8")
    if resolution is not None:
        inventory = root / "inventory.toml"
        text = inventory.read_text(encoding="utf-8").replace(
            "[machines.mill]\nkind = 'mill'\n",
            f"[machines.mill]\nkind = 'mill'\nresolution_mm = {resolution}\n",
        )
        inventory.write_text(text, encoding="utf-8")
    return path


def finding(path, kernel=None, pre_kernel=False):
    bundle = load_bundle(path)
    if kernel is not None:
        object.__setattr__(bundle, "kernel", kernel)
    return coordinates.evaluate(bundle, pre_kernel=pre_kernel)[0]


def requested(path):
    """The whole printed arc table the kernel request carries."""
    (arc,) = finding(path, pre_kernel=True).numbers["arc_table"]
    assert arc["kernel_clip"] is True
    return arc


def kernel(pieces, rows):
    """A kernel result whose clip of S1:20's arc table (``rows`` long) is ``pieces``."""
    path = {"table": f"{TABLE} row 0", "rows": rows, "pieces": pieces}
    clips = {"clipped_at": CONTACT, "precision_mm": 1e-4, "paths": [path]}
    return {"status": "ok", "ops": {SUBJECT: {"checkpoint_clips": clips}}}


def clip_point(arc, after, t, dro_xy):
    """A kernel clip point a fraction ``t`` along the chord after row ``after``."""
    a, b = arc["rows"][after]["setup_xy"], arc["rows"][after + 1]["setup_xy"]
    exact = [a[i] + t * (b[i] - a[i]) for i in range(2)]
    return {"after": after, "t": t, "exact_xy": exact, "dro_xy": dro_xy}


def row_ids(numbers):
    return [
        [row[0] for row in table["rows"]] for table in coordinates.checkpoints(SUBJECT, numbers, 20)
    ]


def wall_distance(xy):
    return 10.0 - math.dist(xy, CENTRE)


@pytest.mark.parametrize(
    ("result", "why"),
    [
        (None, "no kernel result has clipped it"),
        ({"status": "unknown", "reason": "no FreeCAD"}, "the kernel is unavailable (no FreeCAD)"),
        ({"status": "ok", "ops": {}}, "the kernel reports no clip of it"),
        (
            {"status": "ok", "ops": {SUBJECT: {"checkpoint_clips": {"reason": "OCC failed"}}}},
            "its kernel clip is unknown (OCC failed)",
        ),
    ],
)
def test_without_a_kernel_clip_a_bounded_table_prints_nothing_and_is_unknown(tmp_path, result, why):
    row = finding(plan(tmp_path), kernel=result)
    assert row.status == "unknown"
    assert f"op 20 rough: its bounds clip is unknown: {why}" in row.sentence, row.sentence
    assert row.numbers["arc_table"] == [] and row.numbers["line_table"] == []
    assert coordinates.checkpoints(SUBJECT, row.numbers, 20) == []
    (profile,) = row.numbers["profiles"]
    assert profile["cutter_centre"] == "unknown"


def test_a_clip_that_keeps_every_row_prints_the_whole_table(tmp_path):
    path = plan(tmp_path)
    arc = requested(path)
    count = len(arc["rows"])
    row = finding(path, kernel(([[{"row": i} for i in range(count)]]), count))
    assert row.status == "pass", row.sentence
    (table,) = row.numbers["arc_table"]
    assert [item["dro_xy"] for item in table["rows"]] == [item["dro_xy"] for item in arc["rows"]]
    assert not any(item.get("clipped_at") for item in table["rows"])
    assert "fragment" not in table and "dropped_rows" not in table


def test_a_clip_point_ends_the_printed_path_at_the_kernels_dro_value(tmp_path):
    path = plan(tmp_path)
    arc = requested(path)
    count = len(arc["rows"])
    end = clip_point(arc, 9, 0.5, [-3.5, -8.95])
    row = finding(path, kernel([[{"row": i} for i in range(10)] + [end]], count))
    assert row.status == "pass", row.sentence
    (table,) = row.numbers["arc_table"]
    *kept, last = table["rows"]
    assert [item["setup_xy"] for item in kept] == [item["setup_xy"] for item in arc["rows"][:10]]
    assert last["clipped_at"] == CONTACT
    assert last["setup_xy"] == end["exact_xy"] and last["dro_xy"] == [-3.5, -8.95]
    assert table["dropped_rows"] == count - 10
    # The printed rows are renumbered as the kernel names them; the clip point prints its
    # DRO value at the op's tip.
    (checked,) = coordinates.checkpoints(SUBJECT, row.numbers, 20)
    assert [item[0] for item in checked["rows"]] == [f"{TABLE} row {i}" for i in range(11)]
    assert checked["rows"][-1][1:3] == ([-3.5, -8.95], -2.078)


def test_a_path_the_clip_splits_is_fragments_and_debt_never_reconnected(tmp_path):
    path = plan(tmp_path)
    arc = requested(path)
    count = len(arc["rows"])
    pieces = [
        [{"row": i} for i in range(5)] + [clip_point(arc, 4, 0.25, [-7.0, -8.6])],
        [clip_point(arc, 10, 0.75, [-3.0, -8.9])] + [{"row": i} for i in range(11, count)],
    ]
    row = finding(path, kernel(pieces, count))
    debt = "splits its cutter-centre path into 2 pieces; no credited cut links them"
    assert row.status == "unknown" and debt in row.sentence, row.sentence
    (profile,) = row.numbers["profiles"]
    assert debt in profile["clip_reason"]
    first, second = row.numbers["arc_table"]
    assert [first["fragment"], second["fragment"]] == [[1, 2], [2, 2]]
    assert first["rows"][-1]["clipped_at"] == second["rows"][0]["clipped_at"] == CONTACT
    # Each piece is its own printed path: nothing joins fragment 1's end to fragment 2.
    assert profile["cutter_centre"] == [first["rows"], second["rows"]]
    assert row_ids(row.numbers) == [
        [f"{TABLE} fragment 1 row {i}" for i in range(6)],
        [f"{TABLE} fragment 2 row {i}" for i in range(count - 10)],
    ]
    for piece in (first, second):
        assert (piece["stage"], piece["allowance_mm"], piece["offset_mm"]) == ("rough", 0.2, 3.2)


def test_a_clip_with_no_legal_part_prints_nothing_and_is_unknown(tmp_path):
    path = plan(tmp_path)
    row = finding(path, kernel([], len(requested(path)["rows"])))
    assert row.status == "unknown"
    assert "no part of its cutter-centre path is clear of stock outside" in row.sentence
    assert row.numbers["arc_table"] == []


def test_a_clip_that_does_not_match_the_printed_table_is_unknown(tmp_path):
    path = plan(tmp_path)
    count = len(requested(path)["rows"])
    row = finding(path, kernel([[{"row": i} for i in range(count + 1)]], count + 1))
    assert row.status == "unknown"
    assert "the kernel's clip does not match its printed table" in row.sentence
    assert row.numbers["arc_table"] == []


@pytest.mark.parametrize(
    ("resolution", "step", "tip"), [(None, 0.001, -2.078), (0.01, 0.01, -2.07)]
)
def test_printed_values_round_to_the_safe_side_of_the_dro_grid(tmp_path, resolution, step, tip):
    row = finding(plan(tmp_path, bounded=False, resolution=resolution))
    assert row.numbers["dro_grid"]["step"] == step
    (arc,) = row.numbers["arc_table"]
    for item in arc["rows"]:
        printed = item["dro_xy"]
        assert all(abs(v / step - round(v / step)) < 1e-6 for v in printed), item
        assert math.dist(printed, item["setup_xy"]) < 2 * step * math.sqrt(2), item
        assert wall_distance(printed) >= wall_distance(item["setup_xy"]) - 1e-9, item
    # The tip rounds up: the DRO never cuts below the authored -2.07825.
    assert arc["dro_tip_z"] == tip
    assert {item["dro_tip_z"] for item in arc["rows"]} == {tip}
    (profile,) = row.numbers["profiles"]
    (operation,) = row.numbers["operations"]
    assert profile["dro_to_z"] == operation["dro_to_z"] == tip


def test_the_kernel_stands_the_tool_up_to_the_entry_the_rule_computed_not_a_rounding(tmp_path):
    # The tool stands at its pass ends from its level up to its entry Z, read up the DRO
    # grid: 0.0001000004 on a 0.0001 grid reads 0.0002. The request the kernel sweeps is the
    # rule's own numbers, so an entry rounded for print first (0.0001) would stand it a
    # whole step short.
    from prechips.kernel import tool_paths

    path = plan(tmp_path, bounded=False, do="finish_profile", resolution=0.0001)
    text = path.read_text(encoding="utf-8").replace("top_z = 0.0\n", "top_z = 0.0001000004\n")
    path.write_text(text, encoding="utf-8")
    numbers = finding(path, pre_kernel=True).numbers
    assert [profile["entry_z"] for profile in numbers["profiles"]] == [0.0001000004] * 2
    sweep = tool_paths({"op": 20}, numbers, "mm")
    assert sweep["entry_z_mm"] == 0.0002
    standing = [move["z_mm"] for move in sweep["paths"] if len(move["xy_mm"]) == 1]
    assert standing == [[-2.0782, 0.0002]] * 2  # the rough pass's end, then the finish's


@pytest.mark.parametrize(
    ("do", "band", "error"),
    [
        ("finish_profile", (1.995, 2.0), True),
        ("finish_profile", (1.99, 2.0), False),
        ("rough_profile", (1.995, 2.0), False),
    ],
)
def test_a_finish_depth_the_dro_leaves_above_its_face_past_its_band_is_an_error(
    tmp_path, do, band, error
):
    # A 0.01 mm DRO shows to_z -2.07825 as -2.07: 0.00825 mm of skin stays on the face.
    row = finding(plan(tmp_path, bounded=False, do=do, resolution=0.01, band=band))
    residuals = row.numbers.get("dro_z_residual_errors", [])
    assert (row.status == "error") is error, row.sentence
    assert bool(residuals) is error
    if error:
        assert "op 20 prints Z -2.07 for to_z -2.07825" in residuals[0], residuals


def test_rocker_join_records_carry_their_stage_allowance_and_offset():
    bundle = load_bundle(ROCKER)
    rows = coordinates.evaluate(bundle, pre_kernel=True)
    assert rows
    populations = {
        (row.subject, table["op"], table["stage"], kind)
        for row in rows
        for kind in ("arc_table", "line_table")
        for table in row.numbers.get(kind, [])
    }
    # The current manual recipe roughs these joined outlines; file_to_line finishes
    # them, not a superseded finish arc-table operation.
    assert {
        (setup, op, "rough", kind)
        for setup, op in (("S1", 40), ("S2", 40), ("S4", 27))
        for kind in ("arc_table", "line_table")
    } <= populations
    for row in rows:
        for table in (*row.numbers.get("arc_table", []), *row.numbers.get("line_table", [])):
            assert table.get("rows") if "rows" in table else table["dro_xy"], table
            radius = next(
                p["cutter_radius_mm"]
                for p in row.numbers["profiles"]
                if p["op"] == table["op"] and p["stage"] == table["stage"]
            )
            assert table["stage"] in ("rough", "finish"), table
            allowance = table["allowance_mm"]
            assert isinstance(allowance, float | int) and (table["stage"] == "rough") == (
                allowance > 0
            ), table
            assert table["offset_mm"] == pytest.approx(radius + allowance), table


def _to_segment(point, a, b):
    delta = [b[i] - a[i] for i in range(2)]
    t = sum((point[i] - a[i]) * delta[i] for i in range(2)) / (delta[0] ** 2 + delta[1] ** 2)
    t = max(0.0, min(1.0, t))
    return math.dist(point, [a[i] + t * delta[i] for i in range(2)])


def test_printed_join_points_keep_the_authored_offset_from_every_land_and_taper():
    bundle = load_bundle(ROCKER)
    features = bundle.feature_definitions
    frames = bundle.features["frames"]
    setups = {setup["id"]: setup for setup in bundle.plan["setups"]}
    lines = [
        (line, coordinates.setup_frame(bundle, setups[row.subject]))
        for row in coordinates.evaluate(bundle, pre_kernel=True)
        for line in row.numbers.get("line_table", [])
    ]
    assert lines
    for line, frame in lines:
        outer = features[line["feature"]]
        top = features[outer["top_edge_feature"]]
        side, x0 = (1 if line["side"] == "+X" else -1), outer["arc_centre"][0]
        ends = [
            [x0 + side * (p[0] - x0), p[1]]
            for p in (top["end"], outer["radial_tip_end"], outer["bottom_end"])
        ]
        for printed in line["dro_xy"]:
            world = coordinates.model_point([*printed, 0.0], frame)
            at = coordinates.frame_point(world, frames[outer["frame"]])[:2]
            for a, b in zip(ends, ends[1:], strict=False):
                assert _to_segment(at, a, b) >= line["offset_mm"] - 1e-9, (line, printed)
