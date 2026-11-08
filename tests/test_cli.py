import subprocess

import pytest

PLAN = """\
title = "Bracket <trial>"
part = "B&1"
revision = "A"
material = "Aluminium"
stock = "20 × 10 × 40 mm"
note = "Use the drawing's limits."

[[tools]]
id = "internal-mill-id"
description = "6 mm end mill"

[[setups]]
title = "Face stock"
machine = "Manual mill"
holding = "Vise on parallels"
datum = "Top face; left end"
inspection = ["Check thickness & squareness."]

[[setups.operations]]
tool = "internal-mill-id"
instruction = "Face to thickness.\\nKeep < 0.2 mm finishing allowance."
rpm = 1200
feed = "Hand feed, about 50 mm/min"
inspection = "Measure at both ends."
"""


def run_cli(tmp_path, text):
    plan = tmp_path / "plan.toml"
    out = tmp_path / "out" / "traveler.html"
    plan.write_text(text, encoding="utf-8")
    result = subprocess.run(
        ["prechips", "traveler", str(plan), "--out", str(out)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    return result, out


def test_real_cli_renders_escaped_operator_content(tmp_path):
    result, out = run_cli(tmp_path, PLAN)
    assert result.returncode == 0, result.stderr
    html = out.read_text(encoding="utf-8")
    assert "Bracket &lt;trial&gt;" in html
    assert "B&amp;1" in html
    assert "Face to thickness.\nKeep &lt; 0.2 mm" in html
    assert "6 mm end mill" in html
    assert "internal-mill-id" not in html
    assert "1200" in html
    assert "Hand feed, about 50 mm/min" in html
    assert "Measure at both ends." in html
    assert "Check thickness &amp; squareness." in html


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ('title = "unterminated', "Unterminated string"),
        (PLAN.replace('tool = "internal-mill-id"', 'tool = "missing"'), "unknown tool"),
        (PLAN.replace("rpm = 1200", "rpm = true"), "expected a positive integer"),
        (PLAN.replace('title = "Bracket <trial>"', ""), "plan.title"),
    ],
)
def test_bad_input_has_useful_error_without_output(tmp_path, text, message):
    result, out = run_cli(tmp_path, text)
    assert result.returncode == 2
    assert message in result.stderr
    assert "Traceback" not in result.stderr
    assert not out.exists()
