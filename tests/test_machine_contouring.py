"""Arc and diagonal contour rows need the machine's declared ``contouring``.

A cutter path that is not parallel to a setup axis (an arc, a circle or a diagonal join)
can be cut only as the machine can move. ``mdi`` types each row as one MDI move: G1 to
the first row, then G2/G3 about the arc centre or G1 along a straight join, at the op's
feed. ``jog`` turns one handwheel at a time, so the rows step in single-axis moves on the
scrap side and the stair's cusp on the wall must stay within the feature's band. A
machine that declares neither leaves those tables unknown, never a pass.
"""

import math
import re
from html import unescape

import pytest
from test_cli import ROOT, SYNTHETIC_KERNEL, traveler
from test_headroom import coordinate_bundle

from prechips.inputs import load_bundle
from prechips.rules import coordinates

# A Ø20 boss about model (20, 10); frame A puts its centre at setup (15, 8). The 6 mm
# cutter runs its centre on R13 about it.
BOSS = "kind = 'boss'\nat = [20.0, 10.0, 0.0]\ndia = 20.0\n"
SLAB = "kind = 'plane'\nbounds = { x = [0.0, 20.0], y = [0.0, 10.0], z = [0.0, 1.0] }\n"
CENTRE = (15.0, 8.0)
CUTTER_CENTRE_RADIUS = 13.0
CUTTER_RADIUS = 3.0
WALL_RADIUS = 10.0


def banded(low, high):
    """The boss with a Ø``low``-``high`` band about its Ø20 nominal."""
    return f"kind = 'boss'\nat = [20.0, 10.0, 0.0]\ndia = [{low}, {high}]\ndia_nominal = 20.0\n"


def scratch(tmp_path, contouring, feature=BOSS, method="arc_table", step=30.0):
    """S1 op 20 finishing ``feature`` conventionally under a cw spindle on a mill that
    declares ``contouring`` (TOML text; None declares nothing)."""
    plan = coordinate_bundle(
        tmp_path,
        feature,
        "[[setups.ops]]\nop = 20\ndo = 'finish_profile'\nfeature = 'target'\n"
        "tool = 'cutter'\nto_z = -1.0\ndirection = 'conventional'\n"
        f"contour = {{ method = '{method}', step_deg = {step} }}\n",
    )
    inventory = plan.with_name("inventory.toml")
    text = inventory.read_text(encoding="utf-8")
    declared = f"contouring = {contouring}\n" if contouring else ""
    inventory.write_text(text.replace("contouring = 'mdi'\n", declared), encoding="utf-8")
    if "dia_nominal" in feature:
        features = plan.with_name("features.toml")
        text = features.read_text(encoding="utf-8")
        features.write_text(
            text.replace("requirements = []\n", "requirements = ['dia']\n"), encoding="utf-8"
        )
    return plan


def finding(plan):
    return next(row for row in coordinates.evaluate(load_bundle(plan)) if row.subject == "S1")


def to_segment(point, a, b):
    delta = [b[i] - a[i] for i in range(2)]
    span = delta[0] ** 2 + delta[1] ** 2
    t = sum((point[i] - a[i]) * delta[i] for i in range(2)) / span if span else 0.0
    t = max(0.0, min(1.0, t))
    return math.dist(point, [a[i] + t * delta[i] for i in range(2)])


def legs(points, samples=8):
    """Points along each straight leg between neighbouring ``points``."""
    for a, b in zip(points, points[1:], strict=False):
        for k in range(samples + 1):
            yield [a[i] + k / samples * (b[i] - a[i]) for i in range(2)]


@pytest.mark.parametrize(
    ("contouring", "why"),
    [
        (None, "not declared"),
        ("'unknown'", "not declared"),
        ("{ value = 'mdi', verify = true }", "flagged verify"),
    ],
)
def test_arc_moves_on_a_machine_without_declared_contouring_are_unknown(
    tmp_path, contouring, why
):
    row = finding(scratch(tmp_path, contouring))
    assert row.status == "unknown", row.sentence
    assert f"the machine's contouring is {why}" in row.sentence, row.sentence
    (arc,) = row.numbers["arc_table"]
    assert arc["contouring"] == "unknown"
    assert not any("mdi" in item or "jog" in item for item in arc["rows"])


def test_an_axis_parallel_outline_needs_no_declared_contouring(tmp_path):
    row = finding(scratch(tmp_path, None, SLAB, "linear_table"))
    assert row.status == "pass", row.sentence
    (profile,) = row.numbers["profiles"]
    assert "mdi" not in profile


def test_mdi_types_each_row_as_one_move_about_the_arc_centre(tmp_path):
    row = finding(scratch(tmp_path, "'mdi'"))
    assert row.status == "pass", row.sentence
    (arc,) = row.numbers["arc_table"]
    assert arc["contouring"] == "mdi"
    rows = arc["rows"]
    assert rows[0]["mdi"] == {"g": "G1"}
    for before, after in zip(rows, rows[1:], strict=False):
        move = after["mdi"]
        # Conventional under a cw spindle runs the outside of the boss counterclockwise.
        assert move["g"] == "G3"
        start = before["dro_xy"]
        assert [start[0] + move["i"], start[1] + move["j"]] == pytest.approx(CENTRE)


def test_a_jog_stair_coarser_than_the_band_is_an_error_and_prints_no_rows(tmp_path):
    # 30° steps on R13 stand the stair corners ~3 mm off the path; the band is 0.05.
    row = finding(scratch(tmp_path, "'jog'", banded(19.9, 20.1), step=30.0))
    assert row.status == "error", row.sentence
    assert "op 20 finish" in row.sentence and "0.05 band" in row.sentence, row.sentence
    assert row.numbers["arc_table"] == []
    (profile,) = row.numbers["profiles"]
    assert profile["cutter_centre"] == "unknown"
    assert "0.05 band" in profile["stair_reason"]


def test_a_jog_stair_needs_a_band_to_hold_its_cusp_to(tmp_path):
    row = finding(scratch(tmp_path, "'jog'", BOSS, step=2.0))
    assert row.status == "unknown", row.sentence
    assert "no tolerance band" in row.sentence, row.sentence


def test_jog_steps_one_axis_per_row_outside_the_path_with_the_cusp_it_leaves(tmp_path):
    # 7° steps miss the 90° tangents, where a plain two-move stair would dip into the boss.
    row = finding(scratch(tmp_path, "'jog'", banded(19.0, 21.0), step=7.0))
    assert row.status == "pass", row.sentence
    (arc,) = row.numbers["arc_table"]
    assert arc["contouring"] == "jog"
    printed = [item["dro_xy"] for item in arc["rows"]]
    for a, b in zip(printed, printed[1:], strict=False):
        assert a[0] == b[0] or a[1] == b[1], (a, b)
    assert [item.get("jog") for item in arc["rows"][1:]] == [
        "X" if a[1] == b[1] else "Y" for a, b in zip(printed, printed[1:], strict=False)
    ]
    # No point on any single-axis leg comes inside the cutter-centre circle.
    assert min(math.dist(p, CENTRE) for p in legs(printed)) >= CUTTER_CENTRE_RADIUS - 1e-9
    # The stair's cusp: the most material any wall point keeps from the stepped cutter.
    wall = [
        [
            CENTRE[0] + WALL_RADIUS * math.cos(math.radians(k / 20)),
            CENTRE[1] + WALL_RADIUS * math.sin(math.radians(k / 20)),
        ]
        for k in range(360 * 20)
    ]
    left = max(
        min(to_segment(w, a, b) for a, b in zip(printed, printed[1:], strict=False))
        - CUTTER_RADIUS
        for w in wall
    )
    assert arc["stair_cusp_mm"] == pytest.approx(left, abs=2e-3)
    assert 0 < arc["stair_cusp_mm"] <= 0.5


def text(html):
    return unescape(re.sub(r"<[^>]+>", "|", html))


WORD = re.compile(r"(G[123]) X(-?[\d.]+) Y(-?[\d.]+)(?: I(-?[\d.]+) J(-?[\d.]+))? F(\S+?)\|")


@pytest.mark.parametrize("contouring", [None, "'jog'"])
def test_without_mdi_the_sheet_claims_no_continuous_circle_or_g_words(tmp_path, contouring):
    plan = scratch(tmp_path, contouring, banded(19.0, 21.0), step=2.0)
    _, _, html = traveler(plan, tmp_path / "out", setup=SYNTHETIC_KERNEL)
    assert "continuous circle" not in html
    assert not WORD.search(text(html))


def test_rocker_contour_tables_print_one_mdi_move_per_row_at_the_op_feed(tmp_path):
    _, report, html = traveler(
        ROOT / "examples" / "rocker-arm" / "plan.toml", tmp_path / "out", setup=SYNTHETIC_KERNEL
    )
    feeds = {
        row["subject"]: row["numbers"].get("feed_mm_min")
        for row in report["findings"]
        if row["rule"] == "speeds_feeds"
    }
    arcs = {
        f"{row['subject']}:{arc['op']}": arc
        for row in report["findings"]
        if row["rule"] == "coordinates"
        for arc in row["numbers"].get("arc_table", [])
    }
    typed = set()
    for block in html.split('<div class="contour">')[1:]:
        setup, op = re.search(r"<h3>(S\d+) op (\d+)", block).groups()
        subject = f"{setup}:{op}"
        if subject not in arcs:
            continue
        words = WORD.findall(text(block))
        assert words, subject
        centre = arcs[subject]["centre_setup_xy"]
        assert words[0][0] == "G1", subject
        for before, word in zip(words, words[1:], strict=False):
            assert word[5] == f"{feeds[subject]:.0f}", (subject, word)
            if word[0] in {"G2", "G3"}:
                at = [float(before[1]) + float(word[3]), float(before[2]) + float(word[4])]
                assert math.dist(at, centre) < 0.01, (subject, word)
        typed.add(subject)
    assert {"S3:10", "S4:30", "S4:40"} <= typed
    assert "continuous circle" in html
