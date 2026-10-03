"""Frozen bundles must be reproduced, not consumed, by the real CLI."""

import json
import math

import pytest
from test_cli import copy_examples, run_cli, traveler


@pytest.mark.parametrize(
    ("part", "plan_filename", "expected_subdir", "exit_code"),
    [
        ("pivot-shaft", "plan.toml", "expected", 4),
        ("rocker-arm", "plan.toml", "expected", 2),
        ("pivot-bracket", "plan.toml", "expected", 2),
        ("cone-pivot-post", "plan.toml", "expected", 4),
        ("cone-pivot-post", "built-up.toml", "expected/built-up", 2),
    ],
)
def test_examples_match_reference_bytes_and_repeat(
    tmp_path,
    part,
    plan_filename,
    expected_subdir,
    exit_code,
):
    examples = copy_examples(tmp_path)
    bundle = examples / part
    outputs = []
    for run in range(2):
        out = tmp_path / f"run-{run}"
        result, report, html = traveler(bundle / plan_filename, out)
        assert result.returncode == exit_code, result.stderr
        assert report["expected_exit"] == exit_code
        assert "PLANNED" in html
        outputs.append({path.name: path.read_bytes() for path in out.iterdir() if path.is_file()})
    assert outputs[0] == outputs[1]
    expected = bundle / expected_subdir
    if any(row["numbers"].get("kernel_unavailable") for row in report["findings"]):
        geometry = {
            "accessibility",
            "reach",
            "internal_corner_radius",
            "coverage",
            "finish_coverage",
            "vise",
            "thin_wall_under_clamp",
        }
        assert all(
            row["status"] == "unknown" for row in report["findings"] if row["rule"] in geometry
        )
        assert not report.get("renders")
    else:
        assert outputs[0] == {
            path.name: path.read_bytes()
            for path in expected.iterdir()
            if path.is_file()
            and (path.name in {"report.json", "traveler.html"} or path.suffix == ".png")
        }


def test_cone_comparison_keeps_candidate_identity_volume_and_construction_stop(tmp_path):
    bundle = copy_examples(tmp_path) / "cone-pivot-post"
    outputs = []
    for run in range(2):
        out = tmp_path / f"compare-{run}"
        result = run_cli(
            "compare",
            bundle / "plan.toml",
            bundle / "built-up.toml",
            "--out",
            out,
        )
        assert result.returncode == 2, result.stderr
        outputs.append((out / "compare.json").read_bytes())
    assert outputs[0] == outputs[1] == (bundle / "expected" / "compare.json").read_bytes()
    rows = json.loads(outputs[0])
    assert [(row["plan"], row["part"]) for row in rows] == [
        ("plan.toml", "cone-pivot-post"),
        ("built-up.toml", "cone-pivot-post"),
    ]
    stock_volumes = [math.pi * 55**2 * 120, 46 * 50 * 92 + math.pi * 12.5**2 * 100]
    for row, stock, construction, gate in zip(
        rows,
        stock_volumes,
        ("one_piece", "built_up"),
        ("pass", "error"),
        strict=True,
    ):
        assert row["construction"] == construction
        assert row["stock_volume_mm3"] == pytest.approx(stock)
        assert row["net_volume_mm3"] == 112300.8902
        assert row["waste_ratio"] == pytest.approx(1 - 112300.8902 / stock)
        finding = next(f for f in row["rule_findings"] if f["rule"] == "construction")
        assert finding["status"] == gate
