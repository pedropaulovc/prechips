"""Host-only traveler precision and visible machine instructions with synthetic kernel facts."""

import json
import re
import tomllib
from html.parser import HTMLParser

import pytest
from test_cli import ROOT, SYNTHETIC_KERNEL, copy_examples, traveler
from test_envelope_m5 import measured
from test_sheet_ops import Markup, content

from prechips.inputs import load_bundle
from prechips.sheet import _Traveler


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


def job_page(markup):
    (job,) = [
        node
        for node in markup.nodes
        if node["tag"] == "section" and node["attrs"].get("data-sheet") == "job"
    ]
    return job


def setup_sections(markup):
    """Index semantic setup owners, not browser-created physical sheets."""
    owners = {}
    for node in [*markup.find("setup-flow"), *markup.find("setup-family")]:
        for sid in json.loads(node["attrs"]["data-setup-members"]):
            assert sid not in owners, sid
            owners[sid] = node
    assert owners, "Expected rendered setup instructions"
    return owners


def physical_owners(node):
    return [
        owner
        for owner in json.loads(node["attrs"].get("data-physical-ops", "[]"))
        if isinstance(owner, dict)
    ]


def operation(markup, sid, op):
    """Find the instruction, path and inspection at one physical operation."""
    (owner,) = [
        node["parent"]
        for node in markup.find("route-operation", setup_sections(markup)[sid])
        if any(
            item["setup_id"] == sid and str(item["op_id"]) == str(op)
            for item in physical_owners(node["parent"])
        )
    ]
    return owner


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
    markup = Markup(html)
    inspections = [
        content(node)
        for node in markup.find("route-inspection")
        if "? gauges.micrometers/0-1in" in content(node)
    ]
    assert inspections
    assert all(
        re.search(r"\? gauges\.micrometers/0-1in:\s+\? [^?]*Ø", inspection)
        for inspection in inspections
    )


def test_known_numbers_without_drawing_precision_print_and_unknowns_stay_explicit(tmp_path):
    plan = copy_examples(tmp_path) / "pivot-bracket" / "plan.toml"
    # This rendering scenario supplies only the cutter sizes, one drill cone and
    # the DRO/spindle evidence it needs; the other example facts remain illustrative.
    setup = (
        SYNTHETIC_KERNEL
        + """
def measured(value):
    return {"value": value, "measured": {
        "status": "measured", "by": "synthetic test operator",
        "date": "2026-10-05", "instrument": "synthetic precision specification",
    }}
_precision_load = cli.load_bundle
def _precision_bundle(*args, **kwargs):
    bundle = _precision_load(*args, **kwargs)
    machine = bundle.inventory["machines"]["PM-30MV"]
    machine["resolution_mm"] = measured(0.005)
    machine["spindle"]["rotation"] = {"value": "cw", "measured": measured(0)["measured"]}
    tools = bundle.inventory["tools"]
    for member, diameter in (
        ("1-4in-2fl", 6.35), ("1-4in-4fl", 6.35),
        ("3-8in-2fl", 9.525), ("3-8in-4fl", 9.525), ("3-4in-4fl", 19.05),
    ):
        tools["endmills-lms-6784"]["members"][member]["dia_mm"] = measured(diameter)
    tools["bracket-long-endmill"]["dia_mm"] = measured(9.525)
    tools["drill-index-115"]["members"]["#15"].update(
        dia_mm=measured(4.572), point_angle=measured(118)
    )
    # This host-only rendering fixture explicitly retains the one bounded arch table.
    # It is synthetic clip output, not a certificate for the shipped stock or tooling.
    from prechips.rules import coordinates
    requested = next(
        row for row in coordinates.evaluate(bundle, pre_kernel=True) if row.subject == "S4"
    )
    paths = coordinates.checkpoints("S4:15", requested.numbers, 15)
    assert paths, "Expected the synthetic S4 arch contour"
    bundle.kernel["ops"]["S4:15"] = {"checkpoint_clips": {
        "clipped_at": "synthetic printing scenario",
        "precision_mm": 1e-4,
        "paths": [
            {"table": path["rows"][0][0], "rows": len(path["rows"]),
             "pieces": [[{"row": i} for i in range(len(path["rows"]))]]}
            for path in paths
        ],
    }}
    return bundle
cli.load_bundle = _precision_bundle
"""
    )
    _, report, html = traveler(plan, tmp_path / "out", setup=setup)
    markup = Markup(html)
    contours = markup.find("coords")
    assert contours
    for table in contours:
        cells = tagged(markup, "td", table)
        assert cells and all(content(cell).strip() != "?" for cell in cells)
    coordinate_rows = [
        r for row in findings(report, "coordinates") for r in row["numbers"].get("rows", [])
    ]
    assert coordinate_rows
    assert all(isinstance(v, float) for row in coordinate_rows for v in row["setup"])
    # Bench setups (the bracket's S5 send-out) have no DRO, so their findings carry no grid.
    grids = {
        row["subject"]: row["numbers"]["dro_grid"]
        for row in findings(report, "coordinates")
        if "dro_grid" in row["numbers"]
    }
    checked = 0
    for row in findings(report, "blind_depth"):
        for endpoint in row["numbers"].get("endpoints", []):
            entry, tip = endpoint["entry_z"], endpoint["tip_z"]
            if isinstance(entry, float) and isinstance(tip, float):
                # Known depths print on the setup's DRO grid, within one step of the value.
                grid = grids[endpoint["setup"]]
                target = content(operation(markup, endpoint["setup"], endpoint["op"]))
                printed = re.findall(r"Z (-?\d+(?:\.\d+)?) → (-?\d+(?:\.\d+)?)", target)
                # Compact instructions omit the redundant zero entry, but still name
                # the controlled endpoint as a tip reading, not an arbitrary Z value.
                if entry == 0:
                    printed += [
                        ("0", value) for value in re.findall(r"\btip Z\s*(-?\d+(?:\.\d+)?)", target)
                    ]
                assert any(
                    len(a.partition(".")[2]) <= grid["decimals"]
                    and len(b.partition(".")[2]) <= grid["decimals"]
                    and abs(float(a) - entry) < grid["step"]
                    and abs(float(b) - tip) < grid["step"]
                    for a, b in printed
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
    def measured(value):
        return {"value": value, "measured": {
            "status": "measured", "by": "synthetic test operator",
            "date": "2026-10-05", "instrument": "synthetic lathe specification",
        }}
    bundle.inventory["machines"]["PM-1127VF-LB"]["resolution_mm"] = measured(0.01)
    bundle.inventory["tools"]["hss-toolbit-3-8-rh"].update(
        nose_radius_mm=measured(0.4), entering_angle_deg=measured(93.0),
        insert_angle_deg=measured(60.0),
    )
    bundle.inventory["tools"]["parting-blade-lms-1728"].update(
        blade_width_mm=measured(1.6), nose_radius_mm=measured(0.1),
    )
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
    markup = Markup(html)
    op20 = content(operation(markup, "S3", 20))
    assert re.search(r"(?<![\d.])1\.75(?!\d)", op20)
    op10 = content(operation(markup, "S3", 10))
    assert re.search(r"(?<![\d.])2\.25(?!\d)", op10)
    # The kept face is located by the chuck-side blade corner, not a drawing-rounded Z.
    assert "chuck-side corner" in op10
    dome = next(
        contour
        for row in findings(report, "coordinates")
        for contour in row["numbers"].get("contours", [])
        if contour.get("feature") == "south_dome"
    )
    # The dome's rough stair leaves stock on the surface; its finish table remains
    # with the physical profiling operation, independent of pagination.
    owner = operation(markup, "S3", dome["op"])
    candidates = []
    for table in markup.find("coords", owner):
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
    markup = Markup(html)
    owner = operation(markup, "S3", 50)
    message = content(owner)
    assert "length" in message.lower() and "?" in message
    assert re.search(r"\bcalipers?\b", message.lower()) and "(no drawing limit)" in message
    assert re.search(
        r"Measure 1\.75 past the actual scribe to the cut face with calipers?\b", message
    )
    assert "156.67" not in message
    assert not markup.find("inspection-record", owner)
    assert not markup.find("result-field", owner)
    finding = next(
        row for row in findings(report, "inspection") if row["subject"] == "pivot_bearing:length"
    )
    assert finding["status"] == "unknown"
    assert finding["numbers"]["missing_requirement"] is True


def test_lathe_feed_prints_per_revolution_with_the_true_value(tmp_path):
    plan = ROOT / "examples" / "pivot-shaft" / "plan.toml"
    _, report, html = traveler(plan, tmp_path / "out", setup=SYNTHETIC_KERNEL)
    feeds = {}
    for finding in findings(report, "speeds_feeds"):
        setup, _, op = finding["subject"].partition(":")
        numbers = finding["numbers"]
        value = numbers.get("feed_mm_rev")
        if isinstance(value, float):
            feeds[setup, op] = value, numbers.get("feed_mm_min")
    assert feeds
    markup = Markup(html)
    entries = markup.find("tool-setting-entry")
    checked = set()
    for (setup, op), (per_rev, per_min) in feeds.items():
        (entry,) = [
            node
            for node in entries
            if f"{setup}:{op}" in json.loads(node["attrs"]["data-physical-ops"])
        ]
        feed = content(entry)
        printed = re.findall(r"([\d.]+) mm/rev", feed)
        assert feed.count("mm/rev") == len(printed) == 1, (setup, op, feed)
        assert float(printed[0]) == pytest.approx(per_rev, abs=0.005), (setup, op, feed)
        # A secondary feed is explicitly a different unit, not the primary feed.
        secondary = re.findall(r"\(([\d.]+) mm/min\)", feed)
        assert feed.count("mm/min") == len(secondary) <= 1, (setup, op, feed)
        if secondary:
            assert isinstance(per_min, (int, float)), (op, per_min)
            assert float(secondary[0]) == pytest.approx(per_min, abs=0.5), (op, feed)
        checked.add((setup, op))
    assert checked == set(feeds)


def test_job_status_names_every_setup_that_has_a_stop(tmp_path):
    # The job page must name all stopped setups. Unselect the blade for S1-S3 and
    # S0's centre drill, so every stop is owned by this test, not example provenance.
    plan = copy_examples(tmp_path) / "pivot-shaft" / "plan.toml"
    authored = plan.read_text(encoding="utf-8")
    blade_consumers = {
        setup["id"]
        for setup in tomllib.loads(authored)["setups"]
        if any(op.get("tool") == "parting-blade-lms-1728" for op in setup["ops"])
    }
    assert blade_consumers == {"S1", "S2", "S3"}
    unselected = authored.replace(
        'tool = "parting-blade-lms-1728"\nholder', 'tool = "unknown"\nholder'
    )
    unselected, changed = re.subn(
        r'tool = "center-drills-lms-4859/2"\nholder',
        'tool = "unknown"\nholder',
        unselected,
        count=1,
    )
    assert changed == 1
    plan.write_text(unselected, encoding="utf-8")
    _, _, html = traveler(plan, tmp_path / "out", setup=SYNTHETIC_KERNEL)
    markup = Markup(html)
    stopped = {sid for sid, owner in setup_sections(markup).items() if markup.find("stop", owner)}
    assert stopped == {"S0", *blade_consumers}
    (summary,) = [
        content(node)
        for node in tagged(markup, "p", job_page(markup))
        if content(node).startswith("Blocked setups:")
    ]
    assert set(re.findall(r"\bS\d+\b", summary)) == stopped


def test_contour_paths_remain_at_their_own_setup_operation(tmp_path):
    # A contour no longer needs a sheet-number pointer: the path belongs directly to
    # the same physical setup/op as its instruction, including both turning setups.
    _, report, html = traveler(
        ROOT / "examples" / "pivot-shaft" / "plan.toml",
        tmp_path / "out",
        setup=SYNTHETIC_KERNEL,
    )
    markup = Markup(html)
    checked = set()
    for finding in findings(report, "coordinates"):
        sid, numbers = finding["subject"], finding["numbers"]
        expected = {}
        for path in [*numbers.get("contours", []), *numbers.get("stair_tables", [])]:
            if path.get("rows"):
                expected[path["op"]] = expected.get(path["op"], 0) + len(path["rows"])
        for op, count in expected.items():
            owner = operation(markup, sid, op)
            tables = markup.find("coords", owner)
            assert tables, (sid, op)
            assert sum(len(table_rows(markup, table)) for table in tables) == count, (sid, op)
            checked.add(sid)
    assert checked == {"S2", "S3"}


def test_bench_and_saw_setups_print_no_machine_zero_or_clearance(tmp_path):
    # Bench and dedicated saw setups have no spindle zero or machine-clearance
    # instruction. Mill setups retain those facts or their explicit unresolved stop.
    plan = ROOT / "examples" / "cone-pivot-post" / "built-up.toml"
    _, report, html = traveler(plan, tmp_path / "out", setup=SYNTHETIC_KERNEL)
    authored = tomllib.loads(plan.read_text(encoding="utf-8"))
    inventory = tomllib.loads(
        (ROOT / "examples" / "inventory" / "pedro-shop.toml").read_text(encoding="utf-8")
    )
    kinds = {
        s["id"]: inventory["machines"].get(s["machine"], {}).get("kind") for s in authored["setups"]
    }
    markup = Markup(html)
    owners = setup_sections(markup)
    bench = [sid for sid, kind in kinds.items() if kind == "bench"]
    saws = [sid for sid, kind in kinds.items() if kind == "bandsaw"]
    mills = [sid for sid, kind in kinds.items() if kind == "mill"]
    assert bench and saws and mills
    records = {
        (row["rule"], row["subject"]): row
        for rule in ("zero_check", "headroom")
        for row in findings(report, rule)
    }
    for sid in bench + saws:
        assert not markup.find("datum-clause", owners[sid]), sid
        assert "Axis Set" not in content(owners[sid]), sid
        for rule in ("zero_check", "headroom"):
            assert records[rule, sid]["status"] == "not_applicable", (sid, rule)
    for sid in mills:
        evidence = [
            item
            for node in markup.find("decision", owners[sid])
            for item in json.loads(node["attrs"]["data-decision-evidence"])
        ]
        for rule in ("zero_check", "headroom"):
            status = records[rule, sid]["status"]
            assert status != "not_applicable", (sid, rule)
            if status != "pass":
                assert any(
                    item["source"] == rule and item["scope"] == sid and item["status"] == status
                    for item in evidence
                ), (sid, rule, status)


def test_a_setup_edge_break_tighter_than_the_drawing_prints_on_its_own_sheet(tmp_path):
    # The job page carries the drawing's edge break once; a setup that must break its
    # edges smaller (a bonded socket mouth) says so on its own sheet, and a setup on the
    # drawing's limit does not repeat it.
    plan = ROOT / "examples" / "cone-pivot-post" / "built-up.toml"
    _, _, html = traveler(plan, tmp_path / "out", setup=SYNTHETIC_KERNEL)
    authored = tomllib.loads(plan.read_text(encoding="utf-8"))
    markup = Markup(html)
    pages = setup_sections(markup)
    tighter = [s["id"] for s in authored["setups"] if 0 < s.get("deburr_mm", 0) < 0.25]
    drawing = [s["id"] for s in authored["setups"] if s.get("deburr_mm") == 0.25]
    assert tighter and drawing
    for sid in tighter:
        assert re.search(
            r"Break edges 0\.10* mm max in this setup, not the drawing's 0\.25",
            content(pages[sid]),
        ), sid
    for sid in drawing:
        assert "Break edges" not in content(pages[sid]), sid


@pytest.mark.parametrize(
    ("record_hash", "evidence", "expected"),
    [
        ("current", "FA-001 measured and signed", "unresolved shop-required checks"),
        ("current", "", "No first-article evidence is recorded"),
        (
            "other",
            "FA-001 measured and signed",
            "Approval no longer matches",
        ),
    ],
    ids=["recorded-unchecked", "no-evidence", "stale"],
)
def test_job_status_states_the_first_article_record_it_was_given(
    record_hash, evidence, expected, tmp_path
):
    # Approval cannot waive unresolved checks. Current, absent and stale evidence
    # retain their distinct warning without requiring redundant positive boilerplate.
    plan = copy_examples(tmp_path) / "pivot-shaft" / "plan.toml"
    _, report, _ = traveler(plan, tmp_path / "plain", setup=SYNTHETIC_KERNEL)
    assert report["verification"] != "checked"
    digest = report["hash"] if record_hash == "current" else "0" * 64
    approval = tmp_path / "approvals.toml"
    approval.write_text(f'hash = "{digest}"\nfirst_article = "{evidence}"\n', encoding="utf-8")
    result, approved_report, html = traveler(
        plan, tmp_path / "out", "--approval", approval, setup=SYNTHETIC_KERNEL
    )
    assert approved_report == report
    assert expected in result.stderr
    markup = Markup(html)
    (notice,) = [
        node
        for node in markup.find("decision", job_page(markup))
        if node["attrs"]["data-source"] == "approval"
    ]
    assert expected in content(notice)
    assert notice["attrs"]["data-scope"] == "approval"
    assert notice["attrs"]["data-status"] == "warn"
    assert notice["attrs"]["data-decision"] == "caution"
    (banner,) = markup.find("banner")
    assert "PLANNED" in content(banner) and "NOT APPROVED" in content(banner)
    assert "CHECKED" not in content(banner)


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
    markup = Markup(cone)
    sheets = content(job_page(markup))
    (summary,) = markup.find("job-summary")
    assert "test bandsaw" in content(summary)
    assert re.search(r"\bclamp:\s+test cap bridge\b", content(setup_sections(markup)["S10"]))
    assert "bandsaw-4x6" not in sheets and "cone-cap-bridge" not in sheets
    _, _, bracket = traveler(
        examples / "pivot-bracket" / "plan.toml", tmp_path / "bracket", setup=SYNTHETIC_KERNEL
    )
    markup = Markup(bracket)
    assert re.search(r"\bclamp:\s+test bridge piece\b", content(setup_sections(markup)["S4"]))
    assert "LMS 58-piece clamping kit" not in text(bracket)


def test_job_status_lists_stock_to_obtain_before_the_first_setup(tmp_path):
    # The shaft bar is not on hand: the job page says so beside NOT APPROVED and never
    # reads clear; once the bar is on hand the prerequisite line goes.
    plan = copy_examples(tmp_path) / "pivot-shaft" / "plan.toml"
    _, _, html = traveler(plan, tmp_path / "missing", setup=SYNTHETIC_KERNEL)
    markup = Markup(html)
    (stock_stop,) = [
        node
        for node in markup.find("decision", job_page(markup))
        if node["attrs"]["data-source"] == "stock" and node["attrs"]["data-scope"] == "stock"
    ]
    assert stock_stop["attrs"]["data-status"] == "unknown"
    assert stock_stop["attrs"]["data-decision"] == "block"
    assert re.search(r"\bBefore S0\b.*\bobtain\b.*\bstock\b", content(stock_stop))
    assert "NOT APPROVED" in content(markup.find("banner")[0])
    authored = plan.read_text(encoding="utf-8")
    plan.write_text(authored.replace("on_hand = false", "on_hand = true", 1), encoding="utf-8")
    _, _, html = traveler(plan, tmp_path / "held", setup=SYNTHETIC_KERNEL)
    markup = Markup(html)
    assert not [
        node
        for node in markup.find("decision", job_page(markup))
        if node["attrs"]["data-source"] == "stock" and node["attrs"]["data-scope"] == "stock"
    ]


def test_job_page_states_each_machine_dro_grid(tmp_path):
    # An illustrative DRO still controls instruction rounding but never certifies
    # a judgement. Only an absent declaration uses the provisional default grid.
    examples = copy_examples(tmp_path)
    inventory = examples / "inventory" / "pedro-shop.toml"
    authored = inventory.read_text(encoding="utf-8")
    illustrative_grid, changed = re.subn(
        r"(?m)^resolution_mm = .*\n",
        'resolution_mm = { value = 0.005, measured = { status = "illustrative", '
        'by = "synthetic test operator", date = "2026-10-05", instrument = "DRO readout" } }\n',
        authored,
        count=1,
    )
    assert changed == 1
    inventory.write_text(illustrative_grid, encoding="utf-8")
    _, _, html = traveler(
        examples / "pivot-bracket" / "plan.toml", tmp_path / "illustrative", setup=SYNTHETIC_KERNEL
    )
    markup = Markup(html)
    (summary,) = markup.find("job-summary", job_page(markup))
    resolution = content(summary)
    assert "PM-30MV" in resolution
    assert re.search(r"DRO resolution:[^;]*\bPM-30MV\b[^;]*\b0\.005 mm\b", resolution)
    assert "grid not verified; EL400 installed readout step" in resolution
    assert "?" in resolution
    assert resolution.count("not verified") == 1
    assert "default grid" not in resolution
    measured_grid, changed = re.subn(
        r"(?m)^resolution_mm = .*\n",
        'resolution_mm = { value = 0.005, measured = { status = "measured", '
        'by = "synthetic test operator", date = "2026-10-05", instrument = "DRO readout" } }\n',
        illustrative_grid,
        count=1,
    )
    assert changed == 1
    inventory.write_text(measured_grid, encoding="utf-8")
    _, _, measured_html = traveler(
        examples / "pivot-bracket" / "plan.toml", tmp_path / "measured", setup=SYNTHETIC_KERNEL
    )
    measured_markup = Markup(measured_html)
    (summary,) = measured_markup.find("job-summary", job_page(measured_markup))
    measured_resolution = content(summary)
    assert "PM-30MV" in measured_resolution
    assert re.search(r"DRO resolution:[^;]*\bPM-30MV\b[^;]*\b0\.005 mm\b", measured_resolution)
    assert "grid not verified" not in measured_resolution
    assert "default grid" not in measured_resolution
    stripped, removed = re.subn(
        r"(?m)^resolution_mm = .*\n", "", inventory.read_text(encoding="utf-8"), count=1
    )
    assert removed == 1
    inventory.write_text(stripped, encoding="utf-8")
    _, _, html = traveler(
        examples / "pivot-bracket" / "plan.toml", tmp_path / "out", setup=SYNTHETIC_KERNEL
    )
    markup = Markup(html)
    (summary,) = markup.find("job-summary", job_page(markup))
    resolution = content(summary)
    assert "PM-30MV" in resolution
    assert re.search(r"DRO resolution:[^;]*\bPM-30MV\b[^;]*\b0\.001 mm\b", resolution)
    assert "default grid" in resolution


def test_op_notes_print_at_their_own_physical_operation(tmp_path):
    # The machinist reads an op's note where the op is run, not on another sheet.
    plan = ROOT / "examples" / "pivot-shaft" / "plan.toml"
    _, _, html = traveler(plan, tmp_path / "out", setup=SYNTHETIC_KERNEL)
    authored = tomllib.loads(plan.read_text(encoding="utf-8"))
    markup = Markup(html)
    noted = 0
    for setup in authored["setups"]:
        for op in setup["ops"]:
            if op.get("note"):
                # Display names replace feature-id joints; preserve the entire authored note.
                expected = " ".join(op["note"].replace("_", " ").split()).casefold()
                owner = operation(markup, setup["id"], op["op"])
                assert expected in " ".join(content(owner).split()).casefold(), (
                    setup["id"],
                    op["op"],
                    expected,
                )
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
    bundle = load_bundle(plan)
    # This distance-formatting case owns its 0.01 mm grid, not the example's DRO fact.
    bundle.inventory["machines"]["PM-1127VF-LB"]["resolution_mm"] = measured(0.01)
    setup = next(setup for setup in bundle.plan["setups"] if setup["id"] == "S1")
    front = "".join(sum(_Traveler(bundle, [], {}, None).setup_section(setup), []))
    markup = Markup(sections(front, "HOLD")[0])
    (line,) = [
        content(node)
        for node in tagged(markup, "li")
        if content(node).startswith("Support: follow")
    ]
    assert re.search(rf"\b9\.50* mm {re.escape(where)}\b", line)
    assert not re.search(r"Ø\s*9\.50*\b", line)
    # Trailing jaws ride each pass's new diameter, so the HOLD says they go on and come off
    # every pass; the checked Z and the sequence print once, under each op (rest_steps).
    # Leading jaws ride the uncut stock and are not.
    assert ("every pass" in line) == (side == "turned")
    assert "Z 152" not in line
