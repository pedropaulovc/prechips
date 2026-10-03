"""Frozen bundles must be reproduced, not consumed, by the real CLI."""

import pytest

from test_cli import copy_examples, traveler


@pytest.mark.parametrize(
    ("part", "exit_code"),
    [("pivot-shaft", 4), ("rocker-arm", 2), ("pivot-bracket", 2)],
)
def test_examples_match_reference_bytes_and_repeat(tmp_path, part, exit_code):
    examples = copy_examples(tmp_path)
    bundle = examples / part
    outputs = []
    for run in range(2):
        out = tmp_path / f"run-{run}"
        result, report, html = traveler(bundle / "plan.toml", out)
        assert result.returncode == exit_code, result.stderr
        assert report["expected_exit"] == exit_code
        assert "PLANNED" in html
        outputs.append(
            ((out / "report.json").read_bytes(), (out / "traveler.html").read_bytes())
        )
    assert outputs[0] == outputs[1]
    assert outputs[0] == (
        (bundle / "expected" / "report.json").read_bytes(),
        (bundle / "expected" / "traveler.html").read_bytes(),
    )
