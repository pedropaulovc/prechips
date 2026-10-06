"""Contour tables list cutter centres in the real traverse: spindle, direction and frame."""

import math
from pathlib import Path

import pytest
from test_headroom import coordinate_bundle

from prechips.inputs import load_bundle
from prechips.rules import coordinates

ROCKER = Path(__file__).resolve().parents[1] / "examples/rocker-arm/plan.toml"
BOSS = "kind = 'boss'\nat = [20.0, 10.0, 0.0]\ndia = 20.0\n"
SLAB = "kind = 'plane'\nbounds = { x = [0.0, 20.0], y = [0.0, 10.0], z = [0.0, 1.0] }\n"
OUTSIDE = 1  # orientation sign of a counterclockwise path in the setup top view


def scratch(tmp_path, feature, method, direction, rotation="'cw'", flipped=False):
    plan = coordinate_bundle(
        tmp_path,
        feature,
        "[[setups.ops]]\nop = 20\ndo = 'finish_profile'\nfeature = 'target'\n"
        f"tool = 'cutter'\nto_z = -1.0\ndirection = {direction}\n"
        f"contour = {{ method = '{method}', step_deg = 30.0 }}\n",
    )
    inventory = plan.with_name("inventory.toml")
    text = inventory.read_text(encoding="utf-8")
    spindle = f"rotation = {rotation}\n" if rotation else ""
    inventory.write_text(text.replace("rotation = 'cw'\n", spindle), encoding="utf-8")
    if flipped:  # a right-handed roll about X, as a part turned over between setups
        features = plan.with_name("features.toml")
        features.write_text(
            features.read_text(encoding="utf-8").replace(
                "y = [0.0, 1.0, 0.0]\nz = [0.0, 0.0, 1.0]\nbinding",
                "y = [0.0, -1.0, 0.0]\nz = [0.0, 0.0, -1.0]\nbinding",
            ),
            encoding="utf-8",
        )
    return next(row for row in coordinates.evaluate(load_bundle(plan)) if row.subject == "S1")


def turning(points, centre):
    """Sign of the swept angle about ``centre``: +1 counterclockwise in the setup top view."""
    total = sum(
        (a[0] - centre[0]) * (b[1] - centre[1]) - (a[1] - centre[1]) * (b[0] - centre[0])
        for a, b in zip(points, points[1:], strict=False)
    )
    return 1 if total > 0 else -1


@pytest.mark.parametrize(
    ("direction", "rotation", "flipped", "sense"),
    [
        ("'conventional'", "'cw'", False, OUTSIDE),
        ("'climb'", "'cw'", False, -OUTSIDE),
        ("'conventional'", "'ccw'", False, -OUTSIDE),
        ("'climb'", "'ccw'", False, OUTSIDE),
        ("'conventional'", "{ value = 'ccw', verify = false }", False, -OUTSIDE),
        ("'conventional'", "'cw'", True, OUTSIDE),  # sense is judged in the setup view
        ("'climb'", "'cw'", True, -OUTSIDE),
    ],
)
@pytest.mark.parametrize("method", ["arc_table", "linear_table"])
def test_outside_contours_follow_spindle_direction_and_setup_frame(
    tmp_path, method, direction, rotation, flipped, sense
):
    feature = BOSS if method == "arc_table" else SLAB
    row = scratch(tmp_path, feature, method, direction, rotation, flipped)
    assert row.status == "pass", row.sentence
    if method == "arc_table":
        (arc,) = row.numbers["arc_table"]
        points = [item["setup_xy"] for item in arc["rows"]]
        centre = arc["centre_setup_xy"]
        assert arc["cut_order"] == direction.strip("'")
    else:
        (profile,) = row.numbers["profiles"]
        points = profile["cutter_centre"]
        centre = [sum(p[i] for p in points[:-1]) / (len(points) - 1) for i in range(2)]
        assert profile["cut_order"] == direction.strip("'")
    assert turning(points, centre) == sense


@pytest.mark.parametrize(
    ("direction", "rotation", "reason"),
    [
        ("'conventional'", None, "spindle rotation is not declared"),
        ("'conventional'", "'unknown'", "spindle rotation is not declared"),
        ("'conventional'", "{ value = 'cw', verify = true }", "flagged verify"),
        ("'unknown'", "'cw'", "neither conventional nor climb"),
        ("'positive_setup_x'", "'cw'", "neither conventional nor climb"),
    ],
)
@pytest.mark.parametrize("method", ["arc_table", "linear_table"])
def test_undetermined_traverse_is_unknown_never_a_claimed_order(
    tmp_path, method, direction, rotation, reason
):
    row = scratch(tmp_path, BOSS if method == "arc_table" else SLAB, method, direction, rotation)
    table = row.numbers["arc_table"][0] if method == "arc_table" else row.numbers["profiles"][0]
    assert table["cut_order"] == "unknown"
    assert reason in table["cut_order_reason"]
    assert row.status == "unknown"
    assert "Cutting order is unknown" in row.sentence


def rocker_profile_chains(bundle):
    """(setup, op, stage, bottom arc rows, join fragments) for each rocker outline pass."""
    for row in coordinates.evaluate(bundle):
        for arc in row.numbers["arc_table"]:
            lines = [
                line["setup_xy"]
                for line in row.numbers["line_table"]
                if line["op"] == arc["op"] and line["stage"] == arc["stage"]
            ]
            if lines:
                yield row.subject, arc, lines


@pytest.mark.parametrize("direction", ["conventional", "climb"])
def test_rocker_outline_fragments_chain_through_the_bottom_arc_in_cutting_order(direction):
    bundle = load_bundle(ROCKER)
    for setup in bundle.plan["setups"]:
        for op in setup["ops"]:
            if "contour" in op:
                op["direction"] = direction
    chains = list(rocker_profile_chains(bundle))
    assert chains, "the rocker outline needs its mirrored join fragments"
    for subject, arc, lines in chains:
        rows = [item["setup_xy"] for item in arc["rows"]]
        # The convex bottom arc runs counterclockwise for conventional under a cw spindle.
        expected = OUTSIDE if direction == "conventional" else -OUTSIDE
        assert turning(rows, arc["centre_setup_xy"]) == expected, (subject, arc["op"])
        # One fragment arrives at the arc's first row and the other leaves its last row.
        assert any(math.dist(line[-1], rows[0]) < 0.05 for line in lines), (subject, arc["op"])
        assert any(math.dist(line[0], rows[-1]) < 0.05 for line in lines), (subject, arc["op"])
