"""Host-only traveler precision and wording with synthetic kernel facts."""

import re
import tomllib
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
    """The bracket traveler."""
    root = tmp_path_factory.mktemp("bracket")
    plan = copy_examples(root) / "pivot-bracket" / "plan.toml"
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
    printed = re.findall(r"Z (-?\d+\.(\d+)) → (-?\d+\.(\d+))", targets)
    grids = {row["subject"]: row["numbers"]["dro_grid"] for row in findings(report, "coordinates")}
    for row in findings(report, "blind_depth"):
        for endpoint in row["numbers"].get("endpoints", []):
            entry, tip = endpoint["entry_z"], endpoint["tip_z"]
            if isinstance(entry, float) and isinstance(tip, float):
                # Known depths print on the setup's DRO grid, within one step of the value.
                grid = grids[endpoint["setup"]]
                assert any(
                    {len(a_digits), len(b_digits)} == {grid["decimals"]}
                    and abs(float(a) - entry) < grid["step"]
                    and abs(float(b) - tip) < grid["step"]
                    for a, a_digits, b, b_digits in printed
                ), (endpoint, printed)


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


def setup_pages(html):
    """Each setup's sheets, joined: {setup id: html}."""
    parts = re.split(r'<section class="page" data-sheet="SETUP (\S+) sheet \d+"', html)
    pages = {}
    for setup, page in zip(parts[1::2], parts[2::2], strict=True):
        pages[setup] = pages.get(setup, "") + page
    return pages


def test_bench_and_saw_setups_print_no_machine_zero_or_clearance(tmp_path):
    # A bench fit/inspect setup has no spindle, DRO or axes, and a saw cut-off is located
    # by its cut plane: their sheets carry no DRO ZERO and no CLEARANCE, while the
    # machine setups keep both.
    plan = ROOT / "examples" / "cone-pivot-post" / "built-up.toml"
    _, _, html = traveler(plan, tmp_path / "out", setup=SYNTHETIC_KERNEL)
    authored = tomllib.loads(plan.read_text(encoding="utf-8"))
    inventory = tomllib.loads(
        (ROOT / "examples" / "inventory" / "pedro-shop.toml").read_text(encoding="utf-8")
    )
    kinds = {
        s["id"]: inventory["machines"].get(s["machine"], {}).get("kind") for s in authored["setups"]
    }
    pages = setup_pages(html)
    bench = [sid for sid, kind in kinds.items() if kind == "bench"]
    saws = [sid for sid, kind in kinds.items() if kind == "bandsaw"]
    mills = [sid for sid, kind in kinds.items() if kind == "mill"]
    assert bench and saws and mills
    for sid in bench + saws:
        assert "DRO ZERO" not in pages[sid] and "CLEARANCE" not in pages[sid], sid
    for sid in mills:
        assert "DRO ZERO" in pages[sid] and "CLEARANCE" in pages[sid], sid


def test_a_setup_edge_break_tighter_than_the_drawing_prints_on_its_own_sheet(tmp_path):
    # The job page carries the drawing's edge break once; a setup that must break its
    # edges smaller (a bonded socket mouth) says so on its own sheet, and a setup on the
    # drawing's limit does not repeat it.
    plan = ROOT / "examples" / "cone-pivot-post" / "built-up.toml"
    _, _, html = traveler(plan, tmp_path / "out", setup=SYNTHETIC_KERNEL)
    authored = tomllib.loads(plan.read_text(encoding="utf-8"))
    pages = setup_pages(html)
    tighter = [s["id"] for s in authored["setups"] if 0 < s.get("deburr_mm", 0) < 0.25]
    drawing = [s["id"] for s in authored["setups"] if s.get("deburr_mm") == 0.25]
    assert tighter and drawing
    for sid in tighter:
        assert re.search(
            r"Break edges 0\.10* mm max in this setup, not the drawing's 0\.25", text(pages[sid])
        ), sid
    for sid in drawing:
        assert "Break edges" not in text(pages[sid]), sid


@pytest.mark.parametrize(
    ("record_hash", "evidence", "expected"),
    [
        ("current", "FA-001 measured and signed", "a first article is recorded for this input"),
        ("current", "", "no first article is recorded for this input bundle"),
        ("other", "FA-001 measured and signed", "the recorded first article is for other inputs"),
    ],
    ids=["recorded-unchecked", "no-evidence", "stale"],
)
def test_job_status_states_the_first_article_record_it_was_given(
    record_hash, evidence, expected, tmp_path
):
    # The job page tells the operator whether a first article exists for these inputs;
    # a recorded one on an unchecked plan is not "none recorded, make a new one".
    plan = copy_examples(tmp_path) / "pivot-shaft" / "plan.toml"
    _, report, _ = traveler(plan, tmp_path / "plain", setup=SYNTHETIC_KERNEL)
    assert report["verification"] != "checked"
    digest = report["hash"] if record_hash == "current" else "0" * 64
    approval = tmp_path / "approvals.toml"
    approval.write_text(f'hash = "{digest}"\nfirst_article = "{evidence}"\n', encoding="utf-8")
    _, _, html = traveler(plan, tmp_path / "out", "--approval", approval, setup=SYNTHETIC_KERNEL)
    job = text(sections(html, "JOB STATUS")[0])
    assert f"NOT APPROVED: {expected}" in job
    assert ("sign it off below" in job) == (
        expected != "a first article is recorded for this input"
    )


def test_a_named_inventory_item_prints_its_name_not_its_kind_or_slug(tmp_path):
    # The shop names what it owns; the traveler prints that name, not the item's kind or
    # identity key. A member's name is its own: naming the kit does not rename a piece.
    examples = copy_examples(tmp_path)
    inventory = examples / "inventory" / "pedro-shop.toml"
    named = inventory.read_text(encoding="utf-8")
    for header, name in (
        ("[machines.bandsaw-4x6]", "4x6 bandsaw"),
        ("[fixtures.cone-cap-bridge]", "cap bridge clamp"),
        ("[fixtures.clamping-kit-lms-1144]", "LMS 58-piece clamping kit"),
    ):
        assert named.count(f"\n{header}\n") == 1, header
        named = named.replace(f"\n{header}\n", f'\n{header}\nname = "{name}"\n')
    inventory.write_text(named, encoding="utf-8")
    _, _, cone = traveler(
        examples / "cone-pivot-post" / "built-up.toml", tmp_path / "cone", setup=SYNTHETIC_KERNEL
    )
    sheets = text(cone)
    assert re.search(r"SETUP S\d+ — 4x6 bandsaw · sheet 1", sheets)
    assert "Clamp 1: cap bridge clamp —" in sheets
    assert "bandsaw-4x6" not in sheets and "cone-cap-bridge" not in sheets
    _, _, bracket = traveler(
        examples / "pivot-bracket" / "plan.toml", tmp_path / "bracket", setup=SYNTHETIC_KERNEL
    )
    assert "Clamp 1: bracket bridge strap clamp —" in text(bracket)
    assert "LMS 58-piece clamping kit" not in text(bracket)


def test_job_status_lists_stock_to_obtain_before_the_first_setup(tmp_path):
    # The shaft bar is not on hand: the job page says so beside NOT APPROVED and never
    # reads clear; once the bar is on hand the prerequisite line goes.
    plan = copy_examples(tmp_path) / "pivot-shaft" / "plan.toml"
    _, _, html = traveler(plan, tmp_path / "missing", setup=SYNTHETIC_KERNEL)
    job = text(sections(html, "JOB STATUS")[0])
    assert "Before S1: obtain the stock" in job and "NOT APPROVED" in job
    assert "No stops, cautions" not in job
    authored = plan.read_text(encoding="utf-8")
    plan.write_text(authored.replace("on_hand = false", "on_hand = true", 1), encoding="utf-8")
    _, _, html = traveler(plan, tmp_path / "held", setup=SYNTHETIC_KERNEL)
    assert "obtain the stock" not in text(sections(html, "JOB STATUS")[0])


def test_job_page_states_each_machine_dro_grid(bracket, tmp_path):
    # DRO targets print on the machine's declared resolution; with none declared the
    # job page says the default grid is used rather than implying a measured one.
    _, html = bracket
    assert re.search(r"DRO resolution: [^|]*PM-30MV 0\.005 mm(?! \(resolution)", text(html))
    examples = copy_examples(tmp_path)
    inventory = examples / "inventory" / "pedro-shop.toml"
    stripped, removed = re.subn(
        r"(?m)^resolution_mm = .*\n", "", inventory.read_text(encoding="utf-8"), count=1
    )
    assert removed == 1
    inventory.write_text(stripped, encoding="utf-8")
    _, _, html = traveler(
        examples / "pivot-bracket" / "plan.toml", tmp_path / "out", setup=SYNTHETIC_KERNEL
    )
    assert "PM-30MV 0.001 mm (resolution not in the shop list: default grid)" in text(html)


def test_op_notes_print_under_their_own_row_on_the_front_sheet(tmp_path):
    # The machinist reads an op's note where the op is run, not on another sheet.
    plan = ROOT / "examples" / "pivot-shaft" / "plan.toml"
    _, _, html = traveler(plan, tmp_path / "out", setup=SYNTHETIC_KERNEL)
    authored = tomllib.loads(plan.read_text(encoding="utf-8"))
    noted = 0
    for setup in authored["setups"]:
        front = html.split(f'data-sheet="SETUP {setup["id"]} sheet 1"')[1].split("</section>")[0]
        rows = dict(re.findall(r"<tbody[^>]*><tr><td>(\d+)</td>(.*?)</tbody>", front, re.S))
        for op in setup["ops"]:
            if op.get("note"):
                # The bench reading may rename a leading feature id; the words after it stay.
                words = " ".join(op["note"].split()[1:5]).lower()
                assert words in text(rows[str(op["op"])]).lower(), op["op"]
                noted += 1
    assert noted
    assert "See note on" not in text(html)


@pytest.mark.parametrize(
    ("side", "where"), [("turned", "behind the tool"), ("uncut", "ahead of the tool")]
)
def test_follow_rest_hold_prints_its_jaw_lead_as_a_distance_not_a_diameter(side, where, tmp_path):
    # The jaw lead is how far the rest jaws trail (or lead) the tool along the work. Printed
    # after a Ø sign it read as a fixed contact diameter, contradicting the ops that reset
    # the jaws on every newly turned diameter.
    plan = copy_examples(tmp_path) / "pivot-shaft" / "plan.toml"
    authored = plan.read_text(encoding="utf-8")
    edited, count = re.subn(
        r'jaw_lead_mm = 8\.0, jaw_side = "turned"',
        f'jaw_lead_mm = 9.5, jaw_side = "{side}"',
        authored,
    )
    assert count == 1
    plan.write_text(edited, encoding="utf-8")
    _, _, html = traveler(plan, tmp_path / "out", setup=SYNTHETIC_KERNEL)
    hold = text(sections(html, "HOLD")[0])
    (line,) = [part for part in hold.split("|") if part.startswith("Support: follow")]
    assert f"9.50 mm {where}" in line
    assert not re.search(r"Ø\s*9\.50*\b", line)
    # Trailing jaws ride each pass's new diameter, so the HOLD says they are reset per pass,
    # at the declared engagement Z; leading jaws ride the uncut stock and are not.
    assert ("every pass" in line and "Z 152.00" in line) == (side == "turned")
