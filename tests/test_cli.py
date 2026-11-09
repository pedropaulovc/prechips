import subprocess
from html.parser import HTMLParser

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

SECOND_SETUP = """
[[setups]]
title = "Drill pattern"
machine = "Manual mill"

[[setups.operations]]
instruction = "Locate the pattern."

[setups.operations.table]
columns = ["Feature", "X", "Y"]
rows = [["Hole <A>", "12.50", "-3.25"], ["Hole B", "25.00", "0.00\\n4.00"]]
"""


class OperatorText(HTMLParser):
    def __init__(self, html):
        super().__init__()
        self.in_body = False
        self.parts = []
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        if tag == "body":
            self.in_body = True

    def handle_endtag(self, tag):
        if tag == "body":
            self.in_body = False

    def handle_data(self, data):
        if self.in_body and data.strip():
            self.parts.append(data.strip())


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


def test_numbered_setups_operations_and_authored_table_content(tmp_path):
    text = (
        PLAN.replace(
            'description = "6 mm end mill"',
            'name = "End mill <6>"\ndescription = "6 mm end mill"',
        )
        + SECOND_SETUP
    )
    result, out = run_cli(tmp_path, text)
    assert result.returncode == 0, result.stderr
    parts = OperatorText(out.read_text(encoding="utf-8")).parts
    assert "Setup 1 — Face stock" in parts
    assert "Setup 2 — Drill pattern" in parts
    assert parts.index("10") < parts.index("20")
    assert "End mill <6>" in parts
    assert "Locate the pattern." in parts
    assert "6 mm end mill" in parts
    assert "Feature" in parts
    assert "Hole <A>" in parts
    assert "12.50" in parts
    assert "-3.25" in parts
    assert "25.00" in parts
    assert "0.00\n4.00" in parts
    assert "Measure at both ends." in parts
    assert "Check thickness & squareness." in parts
    assert "internal-mill-id" not in parts


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ('title = "unterminated', "Unterminated string"),
        (PLAN.replace('tool = "internal-mill-id"', 'tool = "missing"'), "unknown tool"),
        (PLAN.replace("rpm = 1200", "rpm = true"), "expected a positive integer"),
        (PLAN.replace('title = "Bracket <trial>"', ""), "plan.title"),
        (
            PLAN.replace(
                'description = "6 mm end mill"',
                'name = ""\ndescription = "6 mm end mill"',
            ),
            "tools[1].name",
        ),
        (
            PLAN
            + SECOND_SETUP.replace(
                '"Hole <A>", "12.50", "-3.25"', '"Hole <A>", "12.50"'
            ),
            "rows matching the columns",
        ),
        (
            PLAN
            + SECOND_SETUP.replace('columns = ["Feature", "X", "Y"]', "columns = []"),
            "column names",
        ),
    ],
)
def test_bad_input_has_useful_error_without_output(tmp_path, text, message):
    result, out = run_cli(tmp_path, text)
    assert result.returncode == 2
    assert message in result.stderr
    assert "Traceback" not in result.stderr
    assert not out.exists()


@pytest.mark.parametrize("output_kind", ["input", "hardlink"])
def test_output_cannot_replace_input_plan(tmp_path, output_kind):
    plan = tmp_path / "plan.toml"
    plan.write_text(PLAN, encoding="utf-8")
    out = plan
    if output_kind == "hardlink":
        out = tmp_path / "alias.html"
        out.hardlink_to(plan)
    result = subprocess.run(
        ["prechips", "traveler", str(plan), "--out", str(out)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 2
    assert plan.read_text(encoding="utf-8") == PLAN
    assert out.read_text(encoding="utf-8") == PLAN
