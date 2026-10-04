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
    out = tmp_path_factory.mktemp("bracket") / "out"
    _, report, html = traveler(ROOT / "examples" / "pivot-bracket" / "plan.toml", out)
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
    assert "micrometers" in text(html)


def test_transfer_feature_list_prints_as_words(bracket):
    _, html = bracket
    sheet = text(html)
    assert "indicate foot profile, foot top, ear relief with" in sheet
    assert "['" not in sheet


def test_known_numbers_without_drawing_precision_print_and_unknowns_stay_explicit(bracket):
    report, html = bracket
    pages = sections(html, "CONTOUR CONTINUATION")
    assert pages
    for page in pages:
        assert "<td>?</td>" not in page
        assert not re.search(r"(tool dia|to z|step mm|centre X): \?", text(page))
    for row in findings(report, "coordinates"):
        assert all(isinstance(v, float) for r in row["numbers"].get("rows", []) for v in r["setup"])
    tables = [table for table in sections(html, "COORDINATES") if "<table" in table]
    assert tables and all("<td>?</td>" not in table for table in tables)
    assert "<td>-8.2</td>" in "".join(tables)
    for row in findings(report, "blind_depth"):
        for endpoint in row["numbers"].get("endpoints", []):
            entry, tip = endpoint["entry_z"], endpoint["tip_z"]
            if isinstance(entry, float) and isinstance(tip, float):
                assert f"entry {entry:g} → tip {tip:g}" in text(html)
    # The bracket plan leaves deburr_mm unknown: the sentinel survives the fallback.
    assert "deburr maximum: ? mm" in text(html)


def test_operative_z_keeps_its_own_digits_over_drawing_precision(tmp_path):
    _, report, html = traveler(ROOT / "examples" / "pivot-shaft" / "plan.toml", tmp_path / "out")
    coordinates = next(row for row in findings(report, "coordinates") if row["subject"] == "S3")
    endpoint = next(
        row for row in coordinates["numbers"]["rows"] if row.get("point") == "op 10 to_z"
    )
    assert coordinates["status"] == "unknown"
    # Plan frame T3 restores X/Y; its unbound Z keeps the authored local endpoint.
    assert endpoint["setup"] == [0.0, 0.0, 1.75]
    assert endpoint["model"] == [0.0, 0.0, "unknown"]
    assert endpoint["local_from"] == {"op": 10, "field": "to_z", "axis": "z"}
    assert any("frame T3" in heading for heading in sections(html, "COORDINATES"))
    coordinate_rows = re.findall(r"<tr>.*?</tr>", "".join(sections(html, "COORDINATES")), re.DOTALL)
    endpoint_row = next(
        row for row in coordinate_rows if "op 10 to z" in row and "south dome" in row
    )
    assert "<td>1.75</td>" in endpoint_row
    dome = next(
        contour
        for row in findings(report, "coordinates")
        for contour in row["numbers"].get("contours", [])
        if contour.get("feature") == "south_dome"
    )
    assert "1.75 → 0.25" in text(html)
    page = next(page for page in sections(html, "CONTOUR CONTINUATION") if "south dome" in page)
    table = page[page.index("Z station", page.index("south dome")) :]
    stations = re.findall(r"<tr><td>[^<]*</td><td>([^<]*)</td></tr>", table)
    expected = [f"{round(r['z_mm'], 6):g}" for r in dome["rows"]]
    assert stations[: len(expected)] == expected
    assert len(set(expected)) == len(expected)


@pytest.mark.parametrize("plan", ["plan.toml", "built-up.toml"])
def test_machine_backed_workholding_prints_without_missing_label(tmp_path, plan):
    bundle = copy_examples(tmp_path) / "cone-pivot-post"
    _, _, html = traveler(bundle / plan, tmp_path / "out")
    assert "<td>PM-30MV / BS-0</td>" in html


def test_shaft_missing_length_prints_as_a_normal_unknown_inspection_row(tmp_path):
    _, report, html = traveler(ROOT / "examples" / "pivot-shaft" / "plan.toml", tmp_path / "out")
    row = next(
        row
        for row in re.findall(r"<tr>.*?</tr>", html, re.DOTALL)
        if "missing requirement pivot_bearing:length" in row
    )
    sheet = text(row)
    assert "<td>inspect</td>" in row
    assert "<td>pivot bearing</td>" in row
    assert "? length ?:" in sheet
    assert "missing requirement pivot_bearing:length" in sheet
    assert (
        "Measure 1.75 past the actual scribe to the cut face with calipers; after doming "
        "verify cylinder end 0.25 past scribe and trial fit over the installed ears."
    ) in sheet
    assert "156.67" not in sheet
    finding = next(
        row for row in findings(report, "inspection") if row["subject"] == "pivot_bearing:length"
    )
    assert finding["status"] == "unknown"
    assert finding["numbers"]["missing_requirement"] is True
