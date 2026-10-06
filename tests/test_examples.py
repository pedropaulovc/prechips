"""Frozen bundles must be reproduced, not consumed, by the real CLI."""

import json
import math

import pytest
from test_cli import copy_examples, run_cli, traveler

_GEOMETRY_RULES = {
    "accessibility",
    "reach",
    "internal_corner_radius",
    "coverage",
    "finish_coverage",
    "vise",
    "thin_wall_under_clamp",
    "fixture_interference",
}


@pytest.mark.parametrize(
    ("part", "plan_filename", "expected_subdir", "exit_code"),
    [
        ("pivot-shaft", "plan.toml", "expected", 4),
        ("rocker-arm", "plan.toml", "expected", 2),
        ("pivot-bracket", "plan.toml", "expected", 2),
        ("cone-pivot-post", "plan.toml", "expected", 2),
        ("cone-pivot-post", "built-up.toml", "expected/built-up", 2),
    ],
)
def test_examples_match_reference_bytes_and_repeat(
    tmp_path,
    freecad_kernel,
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
    assert outputs[0] == {
        path.name: path.read_bytes()
        for path in expected.iterdir()
        if path.is_file()
        and (path.name in {"report.json", "traveler.html"} or path.suffix == ".png")
    }


@pytest.mark.parametrize("without_kernel", [False, True], ids=["default-kernel", "forced-absent"])
def test_cone_comparison_keeps_candidate_identity_volume_and_approved_construction(
    tmp_path, monkeypatch, request, without_kernel
):
    if without_kernel:
        monkeypatch.setenv("FREECAD_CMD", str(tmp_path / "no-such-freecadcmd"))
    else:
        request.getfixturevalue("freecad_kernel")
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
        outputs.append((out / "compare.json").read_bytes())
        exits = {row["exit"] for row in json.loads(outputs[-1])}
        # The command exit is the worst candidate exit: error, then unknown, then ready.
        assert result.returncode == next(c for c in (2, 4, 0) if c in exits), result.stderr
    assert outputs[0] == outputs[1]
    rows = json.loads(outputs[0])
    if without_kernel:
        for row in rows:
            geometry = [f for f in row["rule_findings"] if f["rule"] in _GEOMETRY_RULES]
            assert {f["rule"] for f in geometry} == _GEOMETRY_RULES
            assert all(
                f["status"] == "unknown" and f["numbers"].get("kernel_unavailable")
                for f in geometry
            )
            # Unchecked geometry can never leave a candidate ready.
            assert row["exit"] in {2, 4}
    else:
        assert outputs[0] == (bundle / "expected" / "compare.json").read_bytes()
    assert [(row["plan"], row["part"]) for row in rows] == [
        ("plan.toml", "cone-pivot-post"),
        ("built-up.toml", "cone-pivot-post"),
    ]
    stock_volumes = [math.pi * 55**2 * 120, 46 * 50 * 92 + math.pi * 12.5**2 * 100]
    # The example drawing permission is the user-approved built_up_permitted divergence,
    # so neither candidate is refused on construction.
    for row, stock, construction in zip(
        rows, stock_volumes, ("one_piece", "built_up"), strict=True
    ):
        assert row["construction"] == construction
        assert row["stock_volume_mm3"] == pytest.approx(stock)
        # The CAD export has face bindings but no sourced analytic volume.
        assert row["net_volume_mm3"] == "unknown"
        assert row["waste_ratio"] == "unknown"
        finding = next(f for f in row["rule_findings"] if f["rule"] == "construction")
        assert finding["status"] == "pass"
        assert finding["numbers"]["drawing_construction"] == "built_up_permitted"


def test_cone_built_up_candidate_is_refused_without_drawing_permission(tmp_path, monkeypatch):
    # Scratch defect: restore the export's one-piece-only drawing in a copied bundle.
    monkeypatch.setenv("FREECAD_CMD", str(tmp_path / "no-such-freecadcmd"))
    bundle = copy_examples(tmp_path) / "cone-pivot-post"
    features = bundle / "features.toml"
    text = features.read_text(encoding="utf-8")
    approved = '"construction" = "built_up_permitted"'
    assert text.count(approved) == 1
    features.write_text(text.replace(approved, '"construction" = "one_piece"'), encoding="utf-8")
    out = tmp_path / "compare"
    result = run_cli("compare", bundle / "plan.toml", bundle / "built-up.toml", "--out", out)
    assert result.returncode == 2, result.stderr
    rows = json.loads((out / "compare.json").read_bytes())
    gates = {
        row["construction"]: next(f for f in row["rule_findings"] if f["rule"] == "construction")
        for row in rows
    }
    assert gates["one_piece"]["status"] == "pass"
    assert gates["built_up"]["status"] == "error"
    assert gates["built_up"]["message"] == "drawing permits one-piece only"
    assert rows[1]["exit"] == 2
