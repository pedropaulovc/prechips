"""Host-only traveler precision and visible machine instructions with synthetic kernel facts."""

import re
import tomllib
from html.parser import HTMLParser

import pytest
from test_cli import ROOT, SYNTHETIC_KERNEL, copy_examples, traveler
from test_sheet_ops import Markup, content

from prechips.rules.resolution import MANUAL


class VisibleText(HTMLParser):
    """Keep field/cell boundaries, but never split inline readings from their units."""

    blocks = {
        "body",
        "div",
        "h1",
        "h2",
        "h3",
        "li",
        "ol",
        "p",
        "section",
        "table",
        "tbody",
        "td",
        "th",
        "thead",
        "tr",
        "ul",
        "br",
    }

    def __init__(self, html):
        super().__init__()
        self.parts = []
        self.hidden = []
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        if tag in {"script", "style", "head"}:
            self.hidden.append(tag)
        elif not self.hidden and tag in self.blocks:
            self.parts.append("|")

    def handle_endtag(self, tag):
        if self.hidden:
            if tag == self.hidden[-1]:
                self.hidden.pop()
        elif tag in self.blocks:
            self.parts.append("|")

    def handle_data(self, data):
        if not self.hidden:
            self.parts.append(data)


def text(html):
    return "".join(VisibleText(html).parts)


def tagged(markup, tag, within=None):
    """Select actual DOM descendants, including cells containing inline markup."""
    result = []
    for node in markup.nodes:
        if node["tag"] != tag:
            continue
        parent = node
        while parent is not None and parent is not within:
            parent = parent["parent"]
        if within is None or parent is within:
            result.append(node)
    return result


def table_rows(markup, table):
    rows = [
        [content(cell).strip() for cell in tagged(markup, "td", row)]
        for row in tagged(markup, "tr", table)
    ]
    rows = [row for row in rows if row]
    assert rows, "Expected rendered numeric table rows"
    return rows


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
    zeros = findings(report, "zero_check")
    assert len(zeros) == 4
    assert {row["subject"] for row in zeros} == {"S0", "S1", "S2", "S3"}
    for row in zeros:
        x = row["numbers"]["axes"]["x"]
        assert row["status"] == "unknown"
        for key in ("check_reading", "mirrored_reading", "check_expression", "mirrored_expression"):
            assert x[key] == "unknown", (row["subject"], key, x[key])


def test_unknown_inventory_category_still_renders_its_references(tmp_path):
    examples = copy_examples(tmp_path)
    inventory = examples / "inventory" / "pedro-shop.toml"
    stripped = re.sub(
        r"(?ms)^\[gauges(?:\.[^\n]*)?\]\n.*?(?=^\[(?!gauges[.\]])|\Z)",
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
    # It is named by its whole inventory identity: no item of a category stated unknown
    # is named, and table abbreviations never rewrite a key.
    assert re.search(r"\? Ø [^|]*: \? gauges\.micrometers/0-1in\b", text(html))


def test_known_numbers_without_drawing_precision_print_and_unknowns_stay_explicit(bracket):
    report, html = bracket
    contours = sections(html, "CONTOURS")
    assert contours
    for page in contours:
        markup = Markup(page)
        cells = tagged(markup, "td")
        assert cells and all(content(cell).strip() != "?" for cell in cells)
    coordinate_rows = [
        r for row in findings(report, "coordinates") for r in row["numbers"].get("rows", [])
    ]
    assert coordinate_rows
    assert all(isinstance(v, float) for row in coordinate_rows for v in row["setup"])
    tables = [table for table in sections(html, "FEATURE MAP") if "<table" in table]
    assert tables
    for table in tables:
        markup = Markup(table)
        cells = tagged(markup, "td")
        assert cells and all(content(cell).strip() != "?" for cell in cells)
    # Bench setups (the bracket's S5 send-out) have no DRO, so their findings carry no grid.
    grids = {
        row["subject"]: row["numbers"]["dro_grid"]
        for row in findings(report, "coordinates")
        if "dro_grid" in row["numbers"]
    }
    pages = setup_pages(html)
    checked = 0
    for row in findings(report, "blind_depth"):
        for endpoint in row["numbers"].get("endpoints", []):
            entry, tip = endpoint["entry_z"], endpoint["tip_z"]
            if isinstance(entry, float) and isinstance(tip, float):
                # Known depths print on the setup's DRO grid, within one step of the value.
                grid = grids[endpoint["setup"]]
                markup = Markup(pages[endpoint["setup"]])
                (operation,) = [
                    node
                    for node in markup.find("operation")
                    if node["attrs"]["data-op"] == str(endpoint["op"])
                ]
                targets = [content(node) for node in markup.find("op-target", operation)]
                assert targets
                printed = [
                    match
                    for target in targets
                    for match in re.findall(r"Z (-?\d+\.(\d+)) → (-?\d+\.(\d+))", target)
                ]
                assert any(
                    {len(a_digits), len(b_digits)} == {grid["decimals"]}
                    and abs(float(a) - entry) < grid["step"]
                    and abs(float(b) - tip) < grid["step"]
                    for a, a_digits, b, b_digits in printed
                ), (endpoint, printed)
                checked += 1
    assert checked, "Expected known blind-depth endpoints"


# S3 op 10 parts the waste off on the +Z side of its cut: the synthetic kernel says so,
# as the real one does, so the blade's chuck-side corner forms the kept face.
_PARTED_TOWARD_FREE_END = (
    SYNTHETIC_KERNEL
    + """
_faced = cli.load_bundle
def _faced_bundle(*args, **kwargs):
    bundle = _faced(*args, **kwargs)
    bundle.kernel["ops"]["S3:10"] = {"faced_side": 1}
    return bundle
cli.load_bundle = _faced_bundle
"""
)


def test_operative_z_keeps_its_own_digits_over_drawing_precision(tmp_path):
    _, report, html = traveler(
        ROOT / "examples" / "pivot-shaft" / "plan.toml",
        tmp_path / "out",
        setup=_PARTED_TOWARD_FREE_END,
    )
    coordinates = next(row for row in findings(report, "coordinates") if row["subject"] == "S3")
    endpoints = {row.get("point"): row for row in coordinates["numbers"]["rows"]}
    assert coordinates["status"] == "pass"
    # Nominal frame T3 (z = -model Z from -156.67) maps the authored local endpoints:
    # op 10 parts the waste long, op 20 faces the parted end to the dome apex.
    assert endpoints["op 10 to_z"]["setup"] == [0.0, 0.0, 2.25]
    assert endpoints["op 10 to_z"]["model"] == pytest.approx([0.0, 0.0, -158.92])
    assert endpoints["op 20 to_z"]["setup"] == [0.0, 0.0, 1.75]
    assert endpoints["op 20 to_z"]["model"] == pytest.approx([0.0, 0.0, -158.42])
    markup = Markup(sections(html, "OPERATIONS")[-1])
    operations = {node["attrs"]["data-op"]: node for node in markup.find("operation")}
    op20 = content(markup.find("op-target", operations["20"])[0])
    assert re.search(r"(?<![\d.])1\.75(?!\d)", op20)
    op10 = content(markup.find("op-target", operations["10"])[0])
    assert re.search(r"(?<![\d.])2\.25(?!\d)", op10)
    # The kept face is located by the chuck-side blade corner, not a drawing-rounded Z.
    assert "chuck-side corner" in op10
    dome = next(
        contour
        for row in findings(report, "coordinates")
        for contour in row["numbers"].get("contours", [])
        if contour.get("feature") == "south_dome"
    )
    page = next(page for page in sections(html, "CONTOURS") if "south dome" in page)
    # The dome's rough stair (headed "in to X") leaves stock on the surface; the finish
    # table after it carries the dome stations.
    markup = Markup(page[page.index("south dome") :])
    # Split tables repeat their op/tool header; the last thead row names the columns.
    candidates = []
    for table in tagged(markup, "table"):
        (thead,) = tagged(markup, "thead", table)
        heading_row = tagged(markup, "tr", thead)[-1]
        headings = [content(cell).strip() for cell in tagged(markup, "th", heading_row)]
        if "in to X (Ø)" not in headings:
            candidates.append((table, headings))
    assert candidates
    table, headings = candidates[0]
    # A compensated dome also prints tool X/Z; the stations are the surface Z column.
    column = headings.index("surface Z" if "surface Z" in headings else "Z")
    rows = table_rows(markup, table)
    stations = [float(row[column]) for row in rows]
    expected = [round(r["z_mm"], 2) for r in dome["rows"]]
    assert expected
    assert stations[: len(expected)] == expected
    assert len(set(expected)) == len(expected)


MISSING_LENGTH_OP = """
[[setups.ops]]
op = 50
do = "inspect"
feature = "pivot_bearing"
missing_requirements = { length = "calipers" }

[setups.ops.inspection_methods]
length = "Measure 1.75 past the actual scribe to the cut face with calipers."
"""


def test_shaft_missing_length_prints_as_a_normal_unknown_inspection_row(tmp_path):
    # Appended after S3's last op (40, oiling) with the next free number.
    plan = copy_examples(tmp_path) / "pivot-shaft" / "plan.toml"
    plan.write_text(plan.read_text(encoding="utf-8") + MISSING_LENGTH_OP, encoding="utf-8")
    _, report, html = traveler(plan, tmp_path / "out", setup=SYNTHETIC_KERNEL)
    markup = Markup(sections(html, "OPERATIONS")[-1])
    operation = next(node for node in markup.find("operation") if node["attrs"]["data-op"] == "50")
    messages = markup.find("inspection-message", operation)
    assert any("length" in content(node).lower() and "?" in content(node) for node in messages)
    assert "156.67" not in content(operation)
    assert not markup.find("inspection-record", operation)
    assert not markup.find("result-field", operation)
    finding = next(
        row for row in findings(report, "inspection") if row["subject"] == "pivot_bearing:length"
    )
    assert finding["status"] == "unknown"
    assert finding["numbers"]["missing_requirement"] is True


def test_lathe_feed_prints_per_revolution_with_the_true_value(tmp_path):
    plan = ROOT / "examples" / "pivot-shaft" / "plan.toml"
    _, report, html = traveler(plan, tmp_path / "out", setup=SYNTHETIC_KERNEL)
    ids = [setup["id"] for setup in tomllib.loads(plan.read_text(encoding="utf-8"))["setups"]]
    feeds = {}
    for finding in findings(report, "speeds_feeds"):
        setup, _, op = finding["subject"].partition(":")
        numbers = finding["numbers"]
        value = numbers.get("feed_mm_rev")
        if isinstance(value, float):
            feeds[setup, op] = value, numbers.get("feed_mm_min")
    assert feeds
    pages = sections(html, "OPERATIONS")
    checked = set()
    for setup, page in zip(ids, pages, strict=True):
        markup = Markup(page)
        for operation in markup.find("operation"):
            op = operation["attrs"]["data-op"]
            values = feeds.get((setup, op))
            if values is None:
                continue
            per_rev, per_min = values
            feed = content(markup.find("op-feed", operation)[0])
            printed = re.findall(r"([\d.]+) mm/rev", feed)
            assert feed.count("mm/rev") == len(printed) == 1, (op, feed)
            assert float(printed[0]) == pytest.approx(per_rev, abs=0.005), (op, feed)
            # The optional parenthetical is a different unit, not the primary feed.
            secondary = re.findall(r"\(([\d.]+) mm/min\)", feed)
            assert feed.count("mm/min") == len(secondary) <= 1, (op, feed)
            if secondary:
                assert isinstance(per_min, (int, float)), (op, per_min)
                assert float(secondary[0]) == pytest.approx(per_min, abs=0.5), (op, feed)
            checked.add((setup, op))
    assert checked == set(feeds)


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
    _, _, html = traveler(
        ROOT / "examples" / "pivot-shaft" / "plan.toml",
        tmp_path / "out",
        setup=SYNTHETIC_KERNEL,
    )
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
        markup = Markup(page)
        for operation in markup.find("operation"):
            op = operation["attrs"]["data-op"]
            for kind, target, sheet in re.findall(
                r"(note|contour table) on (\S+) sheet (\d+)", content(operation)
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
        ("current", "FA-001 measured and signed", "a first article is recorded for this plan"),
        ("current", "", "no first article is recorded;"),
        (
            "other",
            "FA-001 measured and signed",
            "the recorded first article was made to a different plan or drawing",
        ),
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
    assert ("sign it off below" in job) == (expected != "a first article is recorded for this plan")


def test_a_named_inventory_item_prints_its_name_not_its_kind_or_slug(tmp_path):
    # The shop names what it owns; the traveler prints that name, not the item's kind or
    # identity key. A member's name is its own: naming the kit does not rename a piece.
    examples = copy_examples(tmp_path)
    inventory = examples / "inventory" / "pedro-shop.toml"
    named = inventory.read_text(encoding="utf-8")
    for header, name in (
        ("[machines.bandsaw-4x6]", "test bandsaw"),
        ("[fixtures.cone-cap-bridge]", "test cap bridge"),
        ("[fixtures.clamping-kit-lms-1144]", "LMS 58-piece clamping kit"),
        ("[fixtures.clamping-kit-lms-1144.members.bracket-bridge]", "test bridge piece"),
    ):
        # Replace a shipped name, if any, so the test owns every name it asserts.
        pattern = rf"\n{re.escape(header)}\n(?:name = [^\n]*\n)?"
        assert len(re.findall(pattern, named)) == 1, header
        named = re.sub(pattern, lambda _, h=header, n=name: f'\n{h}\nname = "{n}"\n', named)
    inventory.write_text(named, encoding="utf-8")
    _, _, cone = traveler(
        examples / "cone-pivot-post" / "built-up.toml", tmp_path / "cone", setup=SYNTHETIC_KERNEL
    )
    sheets = text(cone)
    assert re.search(r"SETUP S\d+ — test bandsaw · sheet 1", sheets)
    assert re.search(r"C1 clamp: test cap bridge\b", sheets)
    assert "bandsaw-4x6" not in sheets and "cone-cap-bridge" not in sheets
    _, _, bracket = traveler(
        examples / "pivot-bracket" / "plan.toml", tmp_path / "bracket", setup=SYNTHETIC_KERNEL
    )
    assert re.search(r"C1 clamp: test bridge piece\b", text(bracket))
    assert "LMS 58-piece clamping kit" not in text(bracket)


def test_job_status_lists_stock_to_obtain_before_the_first_setup(tmp_path):
    # The shaft bar is not on hand: the job page says so beside NOT APPROVED and never
    # reads clear; once the bar is on hand the prerequisite line goes.
    plan = copy_examples(tmp_path) / "pivot-shaft" / "plan.toml"
    _, _, html = traveler(plan, tmp_path / "missing", setup=SYNTHETIC_KERNEL)
    job = text(sections(html, "JOB STATUS")[0])
    assert "Before S0: obtain the stock" in job and "NOT APPROVED" in job
    assert "No stops, cautions" not in job
    authored = plan.read_text(encoding="utf-8")
    plan.write_text(authored.replace("on_hand = false", "on_hand = true", 1), encoding="utf-8")
    _, _, html = traveler(plan, tmp_path / "held", setup=SYNTHETIC_KERNEL)
    assert "obtain the stock" not in text(sections(html, "JOB STATUS")[0])


def test_job_page_states_each_machine_dro_grid(bracket, tmp_path):
    # DRO targets print on the machine's declared resolution; with none declared the
    # job page says the default grid is used rather than implying a measured one.
    _, html = bracket
    markup = Markup(sections(html, "JOB STATUS")[0])
    (resolution,) = [
        content(node) for node in tagged(markup, "p") if content(node).startswith("DRO resolution:")
    ]
    assert re.search(r"PM-30MV 0\.005 mm\b", resolution)
    assert "default grid" not in resolution
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
    markup = Markup(sections(html, "JOB STATUS")[0])
    (resolution,) = [
        content(node) for node in tagged(markup, "p") if content(node).startswith("DRO resolution:")
    ]
    assert re.search(r"PM-30MV 0\.001 mm\b", resolution)
    assert "default grid" in resolution


def test_op_notes_print_under_their_own_row_on_the_front_sheet(tmp_path):
    # The machinist reads an op's note where the op is run, not on another sheet.
    plan = ROOT / "examples" / "pivot-shaft" / "plan.toml"
    _, _, html = traveler(plan, tmp_path / "out", setup=SYNTHETIC_KERNEL)
    authored = tomllib.loads(plan.read_text(encoding="utf-8"))
    noted = 0
    for setup in authored["setups"]:
        front = html.split(f'data-sheet="SETUP {setup["id"]} sheet 1"')[1].split("</section>")[0]
        markup = Markup(front)
        operations = {node["attrs"]["data-op"]: node for node in markup.find("operation")}
        css = "op-action" if all(step["do"] in MANUAL for step in setup["ops"]) else "op-note"
        for op in setup["ops"]:
            if op.get("note"):
                # Display names replace feature-id joints; preserve the entire authored note.
                expected = " ".join(op["note"].replace("_", " ").split()).casefold()
                notes = markup.find(css, operations[str(op["op"])])
                assert any(
                    expected in " ".join(content(note).split()).casefold() for note in notes
                ), (setup["id"], op["op"], expected)
                noted += 1
    assert noted


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
    front = html.split('data-sheet="SETUP S1 sheet 1"')[1].split("</section>")[0]
    markup = Markup(sections(front, "HOLD")[0])
    (line,) = [
        content(node)
        for node in tagged(markup, "li")
        if content(node).startswith("Support: follow")
    ]
    assert f"9.50 mm {where}" in line
    assert not re.search(r"Ø\s*9\.50*\b", line)
    # Trailing jaws ride each pass's new diameter, so the HOLD says they go on and come off
    # every pass; the checked Z and the sequence print once, under each op (rest_steps).
    # Leading jaws ride the uncut stock and are not.
    assert ("every pass" in line) == (side == "turned")
    assert "Z 152" not in line
