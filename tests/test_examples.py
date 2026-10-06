"""Frozen bundles must be reproduced, not consumed, by the real CLI."""

import pytest
from test_cli import copy_examples, traveler


@pytest.mark.parametrize(
    ("part", "plan_filename", "expected_subdir", "exit_code"),
    [
        ("pivot-shaft", "plan.toml", "expected", 0),
        ("rocker-arm", "plan.toml", "expected", 2),
        ("pivot-bracket", "plan.toml", "expected", 2),
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
        outputs.append({path.name: path.read_bytes() for path in out.iterdir() if path.is_file()})
    assert outputs[0] == outputs[1]
    expected = bundle / expected_subdir
    assert outputs[0] == {
        path.name: path.read_bytes()
        for path in expected.iterdir()
        if path.is_file()
        and (path.name in {"report.json", "traveler.html"} or path.suffix == ".png")
    }
