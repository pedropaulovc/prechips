from fractions import Fraction
from pathlib import Path

import pytest

from prechips import indexing
from prechips.checks import CheckError
from prechips.cli import main
from prechips.traveler import load_plan, render_traveler

EXAMPLES = Path(__file__).parents[1] / "examples"

PLAN = """\
shop = "shop.toml"
title = "Test part"
part = "T1"
revision = "A"
material = "Steel"
stock = "Bar"

[[tools]]
id = "drill"
description = "Drill"

[[setups]]
title = "Index"
machine = "Mill / dividing head"
indexing = {indexing}

[[setups.operations]]
instruction = "Drill."
"""

SHOP = """\
[machines.head]
kind = "dividing_head"
worm_ratio = 40
direct_index_positions = 24
plate_holes = { A = [15, 16, 17, 18, 19, 20], B = [21, 23, 27, 29, 31, 33], C = [37, 39, 41, 43, 47, 49] }
"""


def run(tmp_path, indexing, *extra):
    plan = tmp_path / "plan.toml"
    plan.write_text(PLAN.format(indexing=indexing), encoding="utf-8")
    (tmp_path / "shop.toml").write_text(SHOP, encoding="utf-8")
    profile = tmp_path / "profile.toml"
    profile.write_text('name = "Indexing"\nfeatures = []\nenforce = ["indexing"]\n')
    out = tmp_path / "out.html"
    code = main(["traveler", str(plan), "--out", str(out), "--profile", str(profile)])
    return code, out


def index_line(tmp_path, indexing):
    plan = tmp_path / "plan.toml"
    plan.write_text(PLAN.format(indexing=indexing), encoding="utf-8")
    (tmp_path / "shop.toml").write_text(SHOP, encoding="utf-8")
    html = render_traveler(load_plan(plan))
    return html.split("<dt>Index:</dt><dd>")[1].split("</dd>")[0]


def test_cone_reproduces_hand_setting_and_passes(tmp_path, capsys):
    profile = tmp_path / "profile.toml"
    profile.write_text('name = "Indexing"\nfeatures = []\nenforce = ["indexing"]\n')
    out = tmp_path / "cone.html"
    plan = EXAMPLES / "comparison" / "cone-pivot-post.toml"
    args = ["traveler", str(plan), "--out", str(out), "--profile", str(profile)]
    assert main(args) == 0
    line = "B 23-hole circle: 1 turn + 9 spaces; 12.5217° (target 12.5182°)"
    assert out.read_text(encoding="utf-8").count(line) == 2


def test_tight_tolerance_refuses_landing_error(tmp_path, capsys):
    code, out = run(
        tmp_path, '{ head = "head", tolerance_deg = 0.0035, angle_deg = 12.5182 }'
    )
    assert code == 2
    assert not out.exists()
    error = capsys.readouterr().err
    assert "setup 1 (Index): B 23-hole circle" in error
    assert "landing 1 is +0.00353913° off" in error


def test_complete_pattern_selects_exact_circle(tmp_path):
    line = index_line(
        tmp_path, '{ head = "head", tolerance_deg = 0.01, positions = 7 }'
    )
    assert line.startswith("B 21-hole circle: 5 turns + 15 spaces per step × 7")
    assert line.endswith("51.4286° (target 51.4286°)")


def test_exact_direct_wins_tie_and_open_pattern(tmp_path):
    line = index_line(
        tmp_path,
        '{ head = "head", tolerance_deg = 0.01, angle_deg = 30, positions = 3 }',
    )
    assert (
        line == "Direct 24-hole plate: 2 holes per step × 3; 30.0000° (target 30.0000°)"
    )


def test_complete_pattern_without_exact_circle_refuses(tmp_path, capsys):
    code, _ = run(
        tmp_path, '{ head = "head", tolerance_deg = 0.0795, positions = 127 }'
    )
    assert code == 2
    error = capsys.readouterr().err
    assert "A 19-hole circle: 6 spaces per step × 127 (full circle)" in error
    assert "landing 127 is +0.947368° off" in error


def test_closure_is_total_against_nearest_revolution(tmp_path):
    plan = tmp_path / "plan.toml"
    plan.write_text(
        PLAN.format(indexing='{ head = "head", tolerance_deg = 1, positions = 127 }'),
        encoding="utf-8",
    )
    (tmp_path / "shop.toml").write_text(SHOP, encoding="utf-8")
    loaded = load_plan(plan)
    selected = indexing.setting(loaded, loaded.data["setups"][0], "setup 1")
    # A19, 6 spaces: 54/19° per step; 127 steps total 6858/19° = 360° + 18/19°.
    assert selected["actual"] == Fraction(54, 19)
    assert selected["closure_error"] == Fraction(18, 19)
    indexing.check(loaded)


def test_missing_declaration_refuses(tmp_path, capsys):
    plan = tmp_path / "plan.toml"
    plan.write_text(
        PLAN.format(indexing='"none"').replace('indexing = "none"\n', ""),
        encoding="utf-8",
    )
    (tmp_path / "shop.toml").write_text(SHOP, encoding="utf-8")
    profile = tmp_path / "profile.toml"
    profile.write_text('name = "Indexing"\nfeatures = []\nenforce = ["indexing"]\n')
    code = main(
        [
            "traveler",
            str(plan),
            "--out",
            str(tmp_path / "o.html"),
            "--profile",
            str(profile),
        ]
    )
    assert code == 2
    assert "setup 1 (Index): missing indexing" in capsys.readouterr().err


@pytest.mark.parametrize(
    "indexing",
    [
        '{ head = "nope", tolerance_deg = 0.1, angle_deg = 10 }',
        '{ head = "head", tolerance_deg = 0.1 }',
        '{ head = "head", tolerance_deg = 0.1, positions = 1 }',
    ],
)
def test_uncomputable_table_is_an_error_without_enforcement(tmp_path, indexing):
    plan = tmp_path / "plan.toml"
    plan.write_text(PLAN.format(indexing=indexing), encoding="utf-8")
    (tmp_path / "shop.toml").write_text(SHOP, encoding="utf-8")
    with pytest.raises(CheckError, match=r"setup 1 \(Index\): indexing"):
        render_traveler(load_plan(plan))
