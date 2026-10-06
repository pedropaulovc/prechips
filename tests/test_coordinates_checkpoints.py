"""Printed cutter-centre tables stop where an op's stock_removal_bounds stop its removal.

A bounded op credits removal only inside its clearing box, so its cutter centre stays r
inside each XY bound, rounded inward to the DRO grid. The printed path is clipped there:
a crossing becomes an exact row marked ``clipped_at``, a path the box splits is debt with
each piece a fragment, and a path wholly outside prints nothing and is debt. Every printed
value rounds to the safe side: XY no nearer the wall and inside the box, the tip never
deeper than authored.
"""

import math
from pathlib import Path

import pytest
from test_headroom import coordinate_bundle

from prechips.inputs import load_bundle
from prechips.rules import coordinates

# A concave R10 arc about the model origin ending at (+-6, -8): the 6 mm cutter runs its
# centre on R7 from (-4.2, -5.6) through (0, -7) to (4.2, -5.6). Frame A puts setup XY at
# model XY - (5, 2): the path spans setup x -9.2..-0.8, y -9..-7.6, about (-5, -2).
ARC = "kind = 'profile'\nradius = 10.0\narc_centre = [0.0, 0.0, 0.0]\nend = [6.0, -8.0, 0.0]\n"
CENTRE = (-5.0, -2.0)
EPSILON = 1e-6
ROCKER = Path(__file__).resolve().parents[1] / "examples/rocker-arm/plan.toml"


def finding(tmp_path, x=(-30.0, 30.0), y=(-30.0, 30.0)):
    plan = coordinate_bundle(
        tmp_path,
        ARC,
        "[[setups.ops]]\nop = 20\ndo = 'finish_profile'\nfeature = 'target'\n"
        "tool = 'cutter'\nto_z = -2.07825\ndirection = 'conventional'\n"
        "contour = { method = 'arc_table', step_deg = 5.0 }\n"
        f"stock_removal_bounds = {{ x = [{x[0]}, {x[1]}], y = [{y[0]}, {y[1]}], "
        "z = [-5.0, 0.0] }\n",
    )
    return coordinates.evaluate(load_bundle(plan))[0]


def wall_distance(xy):
    return 10.0 - math.dist(xy, CENTRE)


@pytest.mark.parametrize(("slack", "clipped"), [(EPSILON, False), (-EPSILON, True)])
def test_an_end_r_inside_its_bound_is_kept_and_one_just_past_it_is_clipped(
    tmp_path, slack, clipped
):
    # The path's +X end stands at setup x -0.8: exactly r inside a bound at x 2.2.
    row = finding(tmp_path, x=(-30.0, 2.2 + slack))
    (arc,) = row.numbers["arc_table"]
    markers = [item["clipped_at"] for item in arc["rows"] if item.get("clipped_at")]
    xs = [item["setup_xy"][0] for item in arc["rows"]]
    assert row.status == "pass", row.sentence
    if clipped:
        # The inset bound -0.800001 rounds inward to the DRO's -0.81.
        assert len(markers) == 1 and markers[0].startswith("stock_removal_bounds x ")
        assert max(xs) == pytest.approx(-0.81)
        assert arc["dropped_rows"] == 1
    else:
        assert markers == [] and "dropped_rows" not in arc
        assert max(xs) == pytest.approx(-0.8)


def test_the_clip_point_is_the_exact_crossing_and_names_its_bound(tmp_path):
    # x -0.6 - r is setup x -3.6, model x 1.4: the R7 path crosses it at asin(0.2).
    row = finding(tmp_path, x=(-30.0, -0.6))
    assert row.status == "pass", row.sentence
    (arc,) = row.numbers["arc_table"]
    (clip,) = [item for item in arc["rows"] if item.get("clipped_at")]
    assert clip["clipped_at"] == "stock_removal_bounds x -0.6 − r"
    assert clip["angle_deg"] == pytest.approx(math.degrees(math.asin(0.2)))
    depth = 7.0 * math.sqrt(1 - 0.2**2)
    assert clip["model_xy"] == pytest.approx([1.4, -depth])
    assert clip["setup_xy"] == pytest.approx([-3.6, -2.0 - depth])
    # The rows past the crossing (15..35 deg and the end) are dropped, none kept beyond it.
    assert arc["dropped_rows"] == 6
    assert all(item["setup_xy"][0] <= -3.6 + 1e-9 for item in arc["rows"])
    # Printed: inside the inset box and no nearer the concave wall (toward its centre).
    assert clip["dro_xy"] == [-3.6, -8.85]


def test_printed_values_round_to_the_safe_side(tmp_path):
    row = finding(tmp_path)
    (arc,) = row.numbers["arc_table"]
    for item in arc["rows"]:
        printed = item["dro_xy"]
        assert all(round(v, 2) == v for v in printed), item
        assert math.dist(printed, item["setup_xy"]) < 0.01 * math.sqrt(2) + 1e-9, item
        assert wall_distance(printed) >= wall_distance(item["setup_xy"]) - 1e-9, item
    # The tip rounds up: the DRO's -2.07 never cuts below the authored -2.07825.
    assert arc["dro_tip_z"] == -2.07
    assert {item["dro_tip_z"] for item in arc["rows"]} == {-2.07}
    (profile,) = row.numbers["profiles"]
    assert profile["dro_to_z"] == -2.07


def test_a_path_the_box_splits_is_fragments_and_debt(tmp_path):
    # y -11.5 + r is setup y -8.5: the arc's middle (setup y down to -9) leaves the box.
    row = finding(tmp_path, y=(-11.5, 30.0))
    debt = "its bounds inset by r split its cutter-centre path into 2 pieces"
    assert row.status == "unknown" and debt in row.sentence, row.sentence
    (profile,) = row.numbers["profiles"]
    assert debt in profile["clip_reason"]
    pieces = row.numbers["arc_table"]
    assert [piece["fragment"] for piece in pieces] == [[1, 2], [2, 2]]
    for piece in pieces:
        ends = [piece["rows"][0], piece["rows"][-1]]
        (inner,) = [item for item in ends if item.get("clipped_at")]
        assert inner["clipped_at"] == "stock_removal_bounds y -11.5 + r"
        assert inner["setup_xy"][1] == pytest.approx(-8.5)
    # Each piece is its own printed path with its own row ids.
    paths = coordinates.checkpoints("S1:20", row.numbers, 20)
    assert [path[0][0] for path in paths] == [
        "S1:20 finish arc fragment 1 row 0",
        "S1:20 finish arc fragment 2 row 0",
    ]
    assert all(xy[1] >= -8.5 for path in paths for _, xy, _, _ in path), paths


def test_a_path_wholly_outside_the_box_prints_nothing_and_is_unknown(tmp_path):
    # x -7 - r is setup x -10: the whole path (x -9.2..-0.8) lies past it.
    row = finding(tmp_path, x=(-30.0, -7.0))
    assert row.status == "unknown"
    assert "its cutter-centre path lies wholly outside its bounds inset by r" in row.sentence
    assert row.numbers["arc_table"] == []
    assert coordinates.checkpoints("S1:20", row.numbers, 20) == []


def _to_model(point, setup, model):
    """``point`` (setup XY) in model XY by the affine map three point pairs fix."""
    (a, b, c), (p, q, r) = setup, model
    e, f, d = ([w[i] - a[i] for i in range(2)] for w in (b, c, point))
    det = e[0] * f[1] - e[1] * f[0]
    u, v = (d[0] * f[1] - d[1] * f[0]) / det, (e[0] * d[1] - e[1] * d[0]) / det
    return [p[i] + u * (q[i] - p[i]) + v * (r[i] - p[i]) for i in range(2)]


def _to_segment(point, a, b):
    delta = [b[i] - a[i] for i in range(2)]
    t = sum((point[i] - a[i]) * delta[i] for i in range(2)) / (delta[0] ** 2 + delta[1] ** 2)
    t = max(0.0, min(1.0, t))
    return math.dist(point, [a[i] + t * delta[i] for i in range(2)])


@pytest.mark.parametrize("bound", [24.0, 27.0])
def test_printed_join_points_keep_the_authored_offset_from_every_land_and_taper(bound):
    # S1:40's join ends clip at y bound - r. At y 27 the clip point sits 0.02 mm off the top
    # arc's circle past the arc's end: neither that circle nor the nearest wall overall may
    # let the printed value step into the land's offset.
    bundle = load_bundle(ROCKER)
    features = bundle.feature_definitions
    (s1,) = [setup for setup in bundle.plan["setups"] if setup["id"] == "S1"]
    (op,) = [op for op in s1["ops"] if op["op"] == 40]
    op["stock_removal_bounds"]["y"][1] = bound
    lines = [
        line for row in coordinates.evaluate(bundle) for line in row.numbers.get("line_table", [])
    ]
    assert any(any(line.get("clipped_at") or []) for line in lines)
    for line in lines:
        outer = features[line["feature"]]
        top = features[outer["top_edge_feature"]]
        side, x0 = (1 if line["side"] == "+X" else -1), outer["arc_centre"][0]
        ends = [
            [x0 + side * (p[0] - x0), p[1]]
            for p in (top["end"], outer["radial_tip_end"], outer["bottom_end"])
        ]
        for printed in line["dro_xy"]:
            at = _to_model(printed, line["setup_xy"], line["model_xy"])
            for a, b in zip(ends, ends[1:], strict=False):
                assert _to_segment(at, a, b) >= line["offset_mm"] - 1e-9, (line, printed)
