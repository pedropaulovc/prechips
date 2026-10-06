"""Host-only traveler precision and wording with synthetic kernel facts."""

import re
from html import unescape

import pytest
from test_cli import ROOT, SYNTHETIC_KERNEL, copy_examples, traveler


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
    _, report, html = traveler(plan, root / "out", setup=SYNTHETIC_KERNEL)
    return report, html


def test_omitted_lathe_radius_mode_leaves_x_checks_unknown(tmp_path):
    plan = copy_examples(tmp_path) / "pivot-shaft" / "plan.toml"
    authored = plan.read_text(encoding="utf-8")
    plan.write_text(re.sub(r"(?m)^radius_mode = .*\n", "", authored, count=1), encoding="utf-8")
    _, report, _ = traveler(plan, tmp_path / "out", setup=SYNTHETIC_KERNEL)
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
    _, report, html = traveler(
        examples / "pivot-shaft" / "plan.toml", tmp_path / "out", setup=SYNTHETIC_KERNEL
    )
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
    _, report, html = traveler(
        ROOT / "examples" / "pivot-shaft" / "plan.toml",
        tmp_path / "out",
        setup=SYNTHETIC_KERNEL,
    )
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
    headings = re.findall(r"<th>([^<]*)</th>", table[: table.index("</thead>")])
    # A compensated dome also prints tool X/Z; the stations are the surface Z column.
    column = headings.index("surface Z" if "surface Z" in headings else "Z")
    rows = re.findall(r"<tr>((?:<td>[^<]*</td>)+)</tr>", table)
    stations = [float(re.findall(r"<td>([^<]*)</td>", row)[column]) for row in rows]
    expected = [round(r["z_mm"], 2) for r in dome["rows"]]
    assert stations[: len(expected)] == expected
    assert len(set(expected)) == len(expected)


@pytest.mark.parametrize("plan", ["plan.toml", "built-up.toml"])
def test_machine_backed_workholding_prints_without_missing_label(tmp_path, plan):
    bundle = copy_examples(tmp_path) / "cone-pivot-post"
    _, _, html = traveler(bundle / plan, tmp_path / "out", setup=SYNTHETIC_KERNEL)
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
    _, report, html = traveler(plan, tmp_path / "out", setup=SYNTHETIC_KERNEL)
    row = next(
        cells for number, cells in op_rows(sections(html, "OPERATIONS")[-1]) if number == "30"
    )
    assert "156.67" not in text(row)
    finding = next(
        row for row in findings(report, "inspection") if row["subject"] == "pivot_bearing:length"
    )
    assert finding["status"] == "unknown"
    assert finding["numbers"]["missing_requirement"] is True


def test_lathe_feed_prints_per_revolution_with_the_true_value(tmp_path):
    _, report, html = traveler(
        ROOT / "examples" / "pivot-shaft" / "plan.toml",
        tmp_path / "out",
        setup=SYNTHETIC_KERNEL,
    )
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
    # Every shaft hold carries a chuck pose; the sheet turns it into a jaw-front Z only.
    _, _, html = traveler(
        ROOT / "examples" / "pivot-shaft" / "plan.toml",
        tmp_path / "out",
        setup=SYNTHETIC_KERNEL,
    )
    holds = sections(html, "HOLD")
    assert holds
    for hold in holds:
        words = text(hold)
        assert "origin" not in words and "pose" not in words
        assert not re.search(r"-?\d+(?:\.\d+)? / -?\d+(?:\.\d+)? / -?\d+", words)


def test_job_status_names_every_setup_that_has_a_stop(tmp_path):
    # The job page is read first; it must never look clear over a stopped setup. Each
    # shaft setup parts or grooves with the blade; unselecting it stops all three.
    plan = copy_examples(tmp_path) / "pivot-shaft" / "plan.toml"
    authored = plan.read_text(encoding="utf-8")
    unselected = authored.replace(
        'tool = "parting-blade-lms-1728"\nholder', 'tool = "unknown"\nholder'
    )
    plan.write_text(unselected, encoding="utf-8")
    _, _, html = traveler(plan, tmp_path / "out", setup=SYNTHETIC_KERNEL)
    stopped = [
        re.match(r"\s*SETUP (\S+)", page)[1]
        for page in html.split("<h2>")[1:]
        if page.startswith("SETUP ") and '<div class="stop">' in page
    ]
    assert len(set(stopped)) == 3
    job = sections(html, "JOB STATUS")[0]
    box = job[job.index('<div class="stop">') :]
    box = box[: box.index("</div>")]
    for setup in stopped:
        assert re.search(rf"\b{setup}\b", text(box))


def test_front_sheet_pointers_lead_to_attached_sheets_of_the_same_setup(tmp_path):
    # The machinist follows "contour table on S2 sheet 3" from an op row; that page must
    # exist, belong to the same setup and carry the op's table.
    _, _, html = traveler(ROOT / "examples" / "pivot-shaft" / "plan.toml", tmp_path / "out")
    pages = {}
    for page in html.split('<section class="page"')[1:]:
        heading = re.search(r"<h2>SETUP (\S+) — (?:[^<]*?· )?sheet (\d+) of (\d+)", page)
        if heading:
            pages[(heading[1], heading[2])] = (int(heading[3]), page)
    assert pages
    for (setup, number), (count, page) in pages.items():
        assert set(range(1, count + 1)) == {int(n) for s, n in pages if s == setup}
        if number != "1":
            continue
        followed = 0
        for op, cells in re.findall(r"<tbody[^>]*><tr><td>(\d+)</td>(.*?)</tbody>", page, re.S):
            for kind, target, sheet in re.findall(
                r"(note|contour table) on (\S+) sheet (\d+)", text(cells)
            ):
                assert target == setup
                attached = pages[(setup, sheet)][1]
                if kind == "contour table":
                    assert f"{setup} op {op} —" in text(attached)
                    followed += 1
        if setup in ("S2", "S3"):
            # Both shaft turning setups profile a contour.
            assert followed
