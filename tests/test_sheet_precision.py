"""Bench traveler numbers: known values print in their own digits; unknowns stay explicit."""

import re
from html import unescape

import pytest
from test_cli import ROOT, copy_examples, traveler


def text(html):
    return unescape(re.sub(r"<[^>]+>", "|", html))


def sections(html, heading):
    return [
        part[: part.find("<h2>", 1) if "<h2>" in part[1:] else None]
        for part in html.split(f"<h2>{heading}")[1:]
    ]


def findings(report, rule):
    return [row for row in report["findings"] if row["rule"] == rule]


@pytest.fixture(scope="module")
def bracket(tmp_path_factory):
    """The bracket traveler with an explicitly unknown scratch S1 deburr limit."""
    root = tmp_path_factory.mktemp("bracket")
    plan = copy_examples(root) / "pivot-bracket" / "plan.toml"
    authored = plan.read_text(encoding="utf-8")
    authored, deburrs = re.subn(r"(?m)^deburr_mm = .*$", 'deburr_mm = "unknown"', authored, count=1)
    assert deburrs == 1
    plan.write_text(authored, encoding="utf-8")
    _, report, html = traveler(plan, root / "out")
    return report, html


def test_omitted_lathe_radius_mode_leaves_x_checks_unknown(tmp_path):
    plan = copy_examples(tmp_path) / "pivot-shaft" / "plan.toml"
    authored = plan.read_text(encoding="utf-8")
    plan.write_text(re.sub(r"(?m)^radius_mode = .*\n", "", authored, count=1), encoding="utf-8")
    _, report, _ = traveler(plan, tmp_path / "out")
    for row in findings(report, "zero_check"):
        x = row["numbers"]["axes"]["x"]
        assert row["status"] == "unknown"
        for key in ("check_reading", "mirrored_reading", "check_expression", "mirrored_expression"):
            assert x[key] == "unknown", (row["subject"], key, x[key])


def test_unknown_inventory_category_still_renders_its_references(tmp_path):
    examples = copy_examples(tmp_path)
    inventory = examples / "inventory" / "pedro-shop.toml"
    stripped = re.sub(
        r"(?ms)^\[gauges(?:\.[^\n]*)?\]\n.*?(?=^\[(?!gauges[.\]]))",
        "",
        inventory.read_text(encoding="utf-8"),
    )
    inventory.write_text('gauges = "unknown"\n' + stripped, encoding="utf-8")
    _, report, html = traveler(examples / "pivot-shaft" / "plan.toml", tmp_path / "out")
    gauges = [row for row in findings(report, "tool_resolves") if "micrometers" in row["subject"]]
    assert gauges and all(row["status"] == "unknown" for row in gauges)
    # The unresolved gauge stays on the sheet and its check is marked unknown, not passed.
    assert re.search(r"\? Ø [^|]*: 0-1 in mic", text(html))


def op_rows(html):
    return re.findall(r"<tr><td>(\d+)</td>(.*?)</tr>", html, re.DOTALL)


def test_known_numbers_without_drawing_precision_print_and_unknowns_stay_explicit(bracket):
    report, html = bracket
    contours = sections(html, "CONTOURS")
    assert contours
    for page in contours:
        assert "<td>?</td>" not in page
    for row in findings(report, "coordinates"):
        assert all(isinstance(v, float) for r in row["numbers"].get("rows", []) for v in r["setup"])
    tables = [table for table in sections(html, "FEATURE MAP") if "<table" in table]
    assert tables and all("<td>?</td>" not in table for table in tables)
    targets = text("".join(sections(html, "OPERATIONS")))
    for row in findings(report, "blind_depth"):
        for endpoint in row["numbers"].get("endpoints", []):
            entry, tip = endpoint["entry_z"], endpoint["tip_z"]
            if isinstance(entry, float) and isinstance(tip, float):
                assert f"Z {entry:.2f} → {tip:.2f}" in targets
    # The scratch S1 deburr_mm is unknown: the sentinel survives the precision fallback.
    assert re.search(r"Break edges[^|]*\?", text(html))


def test_operative_z_keeps_its_own_digits_over_drawing_precision(tmp_path):
    _, report, html = traveler(ROOT / "examples" / "pivot-shaft" / "plan.toml", tmp_path / "out")
    coordinates = next(row for row in findings(report, "coordinates") if row["subject"] == "S3")
    endpoint = next(
        row for row in coordinates["numbers"]["rows"] if row.get("point") == "op 10 to_z"
    )
    assert coordinates["status"] == "pass"
    # Nominal frame T3 (z = -model Z from -156.67) maps the authored local endpoint.
    assert endpoint["setup"] == [0.0, 0.0, 1.75]
    assert endpoint["model"] == pytest.approx([0.0, 0.0, -158.42])
    s3_ops = sections(html, "OPERATIONS")[-1]
    op10 = next(cells for number, cells in op_rows(s3_ops) if number == "10")
    assert "1.75" in text(op10)
    dome = next(
        contour
        for row in findings(report, "coordinates")
        for contour in row["numbers"].get("contours", [])
        if contour.get("feature") == "south_dome"
    )
    page = next(page for page in sections(html, "CONTOURS") if "south dome" in page)
    table = page[page.index("<table", page.index("south dome")) :]
    stations = [float(z) for z in re.findall(r"<tr><td>[^<]*</td><td>([^<]*)</td></tr>", table)]
    expected = [round(r["z_mm"], 2) for r in dome["rows"]]
    assert stations[: len(expected)] == expected
    assert len(set(expected)) == len(expected)


@pytest.mark.parametrize("plan", ["plan.toml", "built-up.toml"])
def test_machine_backed_workholding_prints_without_missing_label(tmp_path, plan):
    bundle = copy_examples(tmp_path) / "cone-pivot-post"
    _, _, html = traveler(bundle / plan, tmp_path / "out")
    route = text(sections(html, "STOCK AND ROUTE")[0])
    assert "BS-0" in route
    assert "BS-0 (not in shop list)" not in route


MISSING_LENGTH_OP = """
[[setups.ops]]
op = 30
do = "inspect"
feature = "pivot_bearing"
missing_requirements = { length = "calipers" }

[setups.ops.inspection_methods]
length = "Measure 1.75 past the actual scribe to the cut face with calipers."
"""


def test_shaft_missing_length_prints_as_a_normal_unknown_inspection_row(tmp_path):
    plan = copy_examples(tmp_path) / "pivot-shaft" / "plan.toml"
    plan.write_text(plan.read_text(encoding="utf-8") + MISSING_LENGTH_OP, encoding="utf-8")
    _, report, html = traveler(plan, tmp_path / "out")
    row = next(
        cells
        for number, cells in op_rows(sections(html, "OPERATIONS")[-1])
        if number == "30"
    )
    assert "calipers" in text(row)
    assert "156.67" not in text(row)
    finding = next(
        row for row in findings(report, "inspection") if row["subject"] == "pivot_bearing:length"
    )
    assert finding["status"] == "unknown"
    assert finding["numbers"]["missing_requirement"] is True


def test_lathe_feed_prints_per_revolution_with_the_true_value(tmp_path):
    _, report, html = traveler(ROOT / "examples" / "pivot-shaft" / "plan.toml", tmp_path / "out")
    per_rev = {}
    for finding in findings(report, "speeds_feeds"):
        setup, _, op = finding["subject"].partition(":")
        value = finding["numbers"].get("feed_mm_rev")
        if isinstance(value, float):
            per_rev[setup, op] = value
    assert per_rev
    pages = sections(html, "OPERATIONS")
    for index, page in enumerate(pages, start=1):
        for op, cells in op_rows(page):
            value = per_rev.get((f"S{index}", op))
            if value is None:
                continue
            printed = re.findall(r"([\d.]+) mm/rev", text(cells))
            # A per-rev feed must never carry the mm/min magnitude.
            assert printed and float(printed[0]) == pytest.approx(value, abs=0.005), (op, cells)


def test_hold_text_has_no_pose_vectors(tmp_path):
    _, _, html = traveler(ROOT / "examples" / "rocker-arm" / "plan.toml", tmp_path / "out")
    holds = sections(html, "HOLD")
    assert holds
    for hold in holds:
        words = text(hold)
        assert "origin" not in words and "pose" not in words
        assert not re.search(r"-?\d+(?:\.\d+)? / -?\d+(?:\.\d+)? / -?\d+", words)
