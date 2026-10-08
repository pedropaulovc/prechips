"""Traveler HOLD and SHOP-MADE FIXTURE sheet facts from a synthetic bundle."""

import re
from html import unescape
from pathlib import Path

import pytest
from test_sheet_ops import Markup, content

from prechips.findings import Finding
from prechips.inputs import Bundle
from prechips.sheet import _Traveler

# Fixture-local x runs along setup +Y and local z along setup +Z, so local y runs along
# setup -X: local (x, y, z) sits at setup (100 - y, 50 + x, -20 + z).
TURNED = {"origin_mm": [100, 50, -20], "x": [0, 1, 0], "z": [0, 0, 1]}
IDENTITY = {"origin_mm": [0, 0, 0], "x": [1, 0, 0], "z": [0, 0, 1]}


def bundle(holds):
    return Bundle(
        plan={
            "setups": [
                {"id": f"S{n}", "machine": "mill", "frame": "TC", "hold": hold, "ops": []}
                for n, hold in enumerate(holds, 1)
            ]
        },
        inventory={
            "machines": {"mill": {"kind": "mill"}},
            "fixtures": {
                "plate": {
                    "kind": "custom",
                    "solids": [
                        {"name": "pad", "shape": "box", "at_mm": [0, 0, 0], "size_mm": [10, 20, 5]},
                        {
                            "name": "pin",
                            "shape": "cylinder",
                            "at_mm": [5, 5, 5],
                            "axis": [0, 0, 1],
                            "dia_mm": 6,
                            "length_mm": 8,
                            "locates": "datum bore",
                        },
                        {
                            "name": "stud-hole",
                            "shape": "cylinder",
                            "at_mm": [5, 15, 0],
                            "axis": [0, 0, 1],
                            "dia_mm": 5,
                            "length_mm": 5,
                            "void": True,
                            "fastener": "M6 stud",
                        },
                        {
                            "name": "shim-r",
                            "shape": "box",
                            "at_mm": [0, 0, 5],
                            "size_mm": [10, 4, 0.47175],
                            "shim": True,
                            "locates": "rail",
                        },
                        {
                            "name": "shim-l",
                            "shape": "box",
                            "at_mm": [0, 16, 5],
                            "size_mm": [10, 4, 0.47175],
                            "shim": True,
                            "locates": "rail",
                        },
                    ],
                },
                # Upright working face is local y = 0, facing local -y; the base is lowest.
                "angle": {
                    "kind": "angle_plate",
                    "solids": [
                        {
                            "name": "base",
                            "shape": "box",
                            "at_mm": [-50, 0, -90],
                            "size_mm": [100, 80, 10],
                            "fastener": "two 1/2-13 T-bolts",
                        },
                        {
                            "name": "upright",
                            "shape": "box",
                            "at_mm": [-50, 0, -80],
                            "size_mm": [100, 10, 80],
                        },
                    ],
                },
                "strap": {"kind": "strap_clamp"},
                "stop": {"kind": "custom", "shop_made": True},
            },
        },
        features={"features": {}},
        policy={},
        cutting_data={},
        paths={},
        hashes={},
        root=Path("."),
        kernel={"status": "ok", "ops": {}},
    )


def descendants(markup, tag, owner=None):
    result = []
    for node in markup.nodes:
        if node["tag"] != tag:
            continue
        parent = node
        while parent is not None and parent is not owner:
            parent = parent["parent"]
        if owner is None or parent is owner:
            result.append(node)
    return result


class FixturePage:
    """Read inline text intact while retaining the actual table and cell owners."""

    def __init__(self, html, printed_sheets=()):
        self.markup = Markup(html)
        self.printed_sheets = printed_sheets
        self.text = "\n".join(
            content(node)
            for node in self.markup.nodes
            if node["tag"] in {"h2", "p", "li", "th", "td"}
        )

    def __contains__(self, value):
        return value in self.text

    def fixture(self):
        headings = [
            node
            for node in descendants(self.markup, "h2")
            if content(node).startswith("SHOP-MADE FIXTURE —")
        ]
        assert len(headings) == 1
        start = self.markup.nodes.index(headings[0])
        end = next(
            (
                n
                for n in range(start + 1, len(self.markup.nodes))
                if self.markup.nodes[n]["tag"] == "h2"
            ),
            len(self.markup.nodes),
        )
        nodes = self.markup.nodes[start:end]
        tables = [node for node in nodes if node["tag"] == "table"]
        assert len(tables) == 1
        self.table = tables[0]
        self.paragraphs = [content(node) for node in nodes if node["tag"] == "p"]
        self.text = "\n".join(
            content(node) for node in nodes if node["tag"] in {"h2", "p", "th", "td"}
        )
        return self

    def rows(self):
        rows = []
        headers = []
        for row in descendants(self.markup, "tr", self.table):
            heads = descendants(self.markup, "th", row)
            if heads:
                headers = [content(cell) for cell in heads]
            cells = descendants(self.markup, "td", row)
            if cells:
                assert headers and len(cells) == len(headers)
                rows.append(dict(zip(headers, map(content, cells), strict=True)))
        assert rows
        return rows

    def row(self, component):
        rows = [row for row in self.rows() if row["Component"] == component]
        assert len(rows) == 1, (component, self.rows())
        return rows[0]

    def position(self, component):
        row = self.row(component)
        (position,) = [value for key, value in row.items() if key.startswith("Position, Setup ")]
        return position

    def line(self, prefix):
        (line,) = [line for line in self.paragraphs if line.startswith(prefix)]
        return line


def sheets(data):
    traveler = _Traveler(data, [], {}, None)
    pages = []
    for setup in data.plan["setups"]:
        printed = ["".join(blocks) for blocks in traveler.setup_section(setup)]
        pages.append(FixturePage("".join(printed), printed))
    return pages


def test_custom_fixture_solids_print_at_their_setup_frame_positions():
    page = sheets(bundle([{"fixture": "plate", "pose": TURNED}]))[0]
    assert "SHOP-MADE FIXTURE" in page
    # The 10 x 20 x 5 pad: local x 0..10 -> Y 50..60, local y 0..20 -> X 80..100.
    assert "X 80…100, Y 50…60, Z -20…-15" in page.fixture().position("pad")
    # The locating pin stands at local (5, 5) on the pad top: X 95, Y 55, Z -15 up 8.
    assert "axis at X 95, Y 55; Z -15…-7" in page.position("pin")
    assert page.row("pin")["Locates"] == "datum bore"
    assert "M6 stud" in page.position("pad")


def test_shim_stacks_print_their_drawn_nominal_once():
    page = sheets(bundle([{"fixture": "plate", "pose": TURNED}]))[0]
    (step,) = [
        content(node) for node in descendants(page.markup, "li") if "shim stacks" in content(node)
    ]
    assert "2 shim stacks under the rail (shim R, shim L): 0.472 mm nominal" in step
    assert step.count("0.472 mm nominal") == 1


def test_angle_plate_base_and_working_face_print_in_the_setup_frame():
    # Plate turned a quarter about Z and lowered: local -y (the working face normal)
    # lies along setup +X, and the face itself at setup X 10.
    pose = {"origin_mm": [10, 0, -5], "x": [0, 1, 0], "z": [0, 0, 1]}
    page = sheets(bundle([{"fixture": "angle", "pose": pose}]))[0]
    (step,) = [
        content(node) for node in descendants(page.markup, "li") if "Angle plate:" in content(node)
    ]
    for instruction in (
        "base flat on the table",
        "underside at Z -95",
        "working face at X 10, facing +X",
        "hold the base down with two 1/2-13 T-bolts",
    ):
        assert instruction in step


def test_later_setup_points_back_to_the_first_table_at_the_same_pose():
    first, later = sheets(bundle([{"fixture": "plate", "pose": TURNED}] * 2))
    assert "SHOP-MADE FIXTURE" in first
    assert "SHOP-MADE FIXTURE —" not in later
    (owner,) = [
        FixturePage(html)
        for html in first.printed_sheets
        if any(
            content(node).startswith("SHOP-MADE FIXTURE —")
            for node in descendants(Markup(html), "h2")
        )
    ]
    headings = [content(node) for node in descendants(owner.markup, "h2")]
    assert any(heading.startswith("SETUP S1 —") for heading in headings)
    (title,) = [heading for heading in headings if heading.startswith("SHOP-MADE FIXTURE —")]
    item = title.split(" — ", 1)[1]
    assert "X 80…100, Y 50…60, Z -20…-15" in owner.fixture().position("pad")
    references = [
        content(node)
        for node in descendants(later.markup, "li")
        if "SHOP-MADE FIXTURE table" in content(node)
    ]
    assert references
    assert all("Setup S1" in reference and item in reference for reference in references)


def test_moved_fixture_gets_its_own_table_in_the_new_frame():
    first, moved = sheets(
        bundle([{"fixture": "plate", "pose": TURNED}, {"fixture": "plate", "pose": IDENTITY}])
    )
    assert "SHOP-MADE FIXTURE —" in moved
    assert "X 0…10, Y 0…20, Z 0…5" in moved.fixture().position("pad")
    assert "X 80…100, Y 50…60, Z -20…-15" in first.fixture().position("pad")


def test_hold_labels_locators_apart_from_clamps_and_tightens_in_declared_order():
    hold = {
        "fixture": "plate",
        "pose": IDENTITY,
        "clamps": [
            {"ref": "strap", "restraint": "press", "torque_nm": 12},
            {"ref": "stop", "restraint": "locate"},
            {"ref": "strap", "restraint": "press", "torque_nm": 12},
        ],
        "clamp_order": [3, 1],
        "preload_direction": "clockwise",
    }
    page = sheets(bundle([hold]))[0]
    assert "C1 clamp:" in page and "LOC2 locator:" in page and "C3 clamp:" in page
    assert "Clamp 2" not in page
    (action,) = [
        content(node)
        for node in descendants(page.markup, "li")
        if "tighten in order" in content(node)
    ]
    for instruction in (
        "Seat the part against LOC2",
        "clockwise (viewed from above)",
        "tighten in order C3, C1",
        "snug each in turn",
        "tighten each fully in the same order to 12 N·m",
    ):
        assert instruction in action


def cylinder(name, x, z, dia, length, **extra):
    return {
        "name": name,
        "shape": "cylinder",
        "at_mm": [x, 0, z],
        "axis": [0, 0, 1],
        "dia_mm": dia,
        "length_mm": length,
        **extra,
    }


def bridge_page(*extra, precision=3, mill=None, tolerances=None, **policy_numbers):
    """A shop-made two-stud bridge: a made beam and locating pad, bought studs, washers
    and nuts, clearance holes through beam and washers, nut threads, and the machine's
    vise jaw drawn for clearance."""
    data = bundle([{"fixture": "bridge", "pose": IDENTITY}])
    data.features.update(precision=precision, units="mm")
    if tolerances is not None:
        data.features["general_tolerances"] = tolerances
    data.inventory["machines"]["mill"].update(mill or {})
    data.policy["numbers"] = policy_numbers
    bought = {"supply": "bought"}
    data.inventory["fixtures"]["bridge"] = {
        "kind": "custom",
        "solids": [
            {"name": "beam", "shape": "box", "at_mm": [-30, -5, 0], "size_mm": [60, 10, 8.26]},
            {
                "name": "pad",
                "shape": "box",
                "at_mm": [-5, -5, -2.3456],
                "size_mm": [10, 10, 2.3456],
                "locates": "cap face",
            },
            *(
                cylinder(f"stud-{s}", x, -30, 9.525, 50, fastener="3/8-16 x 2 in stud", **bought)
                for s, x in (("l", -20), ("r", 20))
            ),
            *(
                cylinder(f"washer-{s}", x, 8.26, 20.64, 1.6, **bought)
                for s, x in (("l", -20), ("r", 20))
            ),
            *(
                cylinder(f"nut-{s}", x, 9.86, 16.5, 8.33, fastener="3/8-16 hex nut", **bought)
                for s, x in (("l", -20), ("r", 20))
            ),
            *(
                cylinder(f"clearance-{s}", x, -1, 10.5, 12, void=True, cuts=["beam", f"washer-{s}"])
                for s, x in (("l", -20), ("r", 20))
            ),
            *(
                cylinder(f"nut-bore-{s}", x, 9.86, 9.525, 8.33, void=True, cuts=[f"nut-{s}"])
                for s, x in (("l", -20), ("r", 20))
            ),
            {
                "name": "vise-jaw",
                "shape": "box",
                "at_mm": [-40, 20, 0],
                "size_mm": [80, 10, 30],
                "supply": "existing",
            },
            *extra,
        ],
    }
    return sheets(data)[0].fixture()


def test_bought_hardware_is_one_line_not_made_rows():
    table = bridge_page()
    assert (
        "Bought hardware (not made): 2 × 3/8-16 x 2 in stud; 2 × washer Ø20.64 × 1.6; "
        "2 × 3/8-16 hex nut."
    ) == table.line("Bought hardware")
    made = "\n".join(" ".join(row.values()) for row in table.rows())
    for word in ("stud", "washer", "nut"):
        assert word not in made, word


def test_holes_print_in_the_row_of_the_part_they_are_cut_in():
    table = bridge_page()
    made = "\n".join(" ".join(row.values()) for row in table.rows())
    beam = table.position("beam")
    assert ("with 2 × Ø10.5 hole: axis at X -20, Y 0; Z -1…11; axis at X 20, Y 0; Z -1…11") in beam
    # The nut threads are part of the bought nuts; no hole gets a row of its own.
    assert "clearance" not in made and "bore" not in made and "Ø9.525" not in made


def test_existing_shop_parts_drawn_for_clearance_are_not_made():
    assert "vise" not in bridge_page()


def test_made_parts_print_their_make_notes_and_differing_notes_stay_apart():
    hard = "O1 drill rod, hardened 58-60 HRC, OD ground"
    buttons = [
        cylinder(f"button-{s}", x, 8.26, 14, 4, note=note)
        for s, x, note in (("l", -20, hard), ("r", 20, hard), ("c", 0, "mild steel"))
    ]
    collar = cylinder("collar", 40, 8.26, 10, 3, note=hard)
    table = bridge_page(*buttons, collar)
    made = table[table.index("Component") : table.index("Bought hardware")]
    assert "button ×2" in made, "identical parts with one note share a row"
    # Rows sharing a make note are named together before it.
    assert f"Make: button ×2, collar: {hard}; button C: mild steel." in table
    # Bought hardware is not made, so its note is no make instruction: it prints apart.
    table = bridge_page(cylinder("bolt", 0, 0, 6, 20, supply="bought", note="zinc plated"))
    assert "Notes: bolt: zinc plated." in table
    assert "zinc" not in table.split("Notes:")[0]


def test_notes_on_holes_and_on_bought_and_existing_parts_print():
    window = cylinder("window", 0, -1, 5, 10, void=True, cuts=["beam"], note="mill it light")
    shell = {
        "name": "shell",
        "shape": "box",
        "at_mm": [-40, -40, -20],
        "size_mm": [5, 5, 5],
        "supply": "existing",
        "note": "the bought box parallel, as sold",
    }
    table = bridge_page(window, shell)
    make = table[table.index("Make:") :]
    # A made hole's note is how it is made; an existing part's note is not.
    assert "window: mill it light" in make
    assert "Notes: shell: the bought box parallel, as sold." in table
    assert "box parallel" not in make.split("Notes:")[0]


RECORD = {
    "check": "head-to-shoulder TIR",
    "gauge": "dti",
    "how": "shoulder rolled in the V-block",
    "max_mm": 0.01,
    "goal_mm": 0.003,
}


def record_bundle(*records, gauges=None):
    head = cylinder("head", 0, 8.26, 8, 4, records=list(records))
    data = bundle([{"fixture": "bridge", "pose": IDENTITY}])
    data.inventory["gauges"] = {"dti": {"kind": "dti", "name": "0.0005 in test indicator"}}
    data.inventory["gauges"].update(gauges or {})
    data.inventory["fixtures"]["bridge"] = {
        "kind": "custom",
        "solids": [
            {"name": "beam", "shape": "box", "at_mm": [-30, -5, 0], "size_mm": [60, 10, 8.26]},
            head,
        ],
    }
    return data


def record_page(*records, gauges=None):
    data = record_bundle(*records, gauges=gauges)
    return data, sheets(data)[0]


def test_a_measured_and_recorded_value_prints_as_a_fill_in():
    square = {"check": "base-to-right squareness by reversal", "over_mm": 100}
    _, page = record_page(RECORD, square)
    tir = page[page.index("head-to-shoulder TIR") :].split("|")[0]
    assert "0.0005 in test indicator" in tir and "shoulder rolled in the V-block" in tir
    assert "≤ 0.010 mm" in tir and "goal ≤ 0.003 mm" in tir
    assert re.search(r"measured _{4,}", tir)
    # A record with no spec is a characterisation: written down, not judged.
    square_line = page[page.index("base-to-right squareness") :].split("|")[0]
    assert re.search(r"measured _{4,} mm over 100 mm", square_line)
    assert "≤" not in square_line


@pytest.mark.parametrize(
    "bad",
    [
        {**RECORD, "check": " "},
        {**RECORD, "goal_mm": 0.02},
        {**RECORD, "max_mm": "unknown"},
        {**RECORD, "max_mm": -0.01},
        # An explicitly unknown method or gauge, or an unknown list, is declared doubt:
        # refused at validation, never dropped from the printed fill-in.
        {**RECORD, "how": "unknown"},
        {**RECORD, "how": " "},
        {**RECORD, "gauge": " "},
        "unknown",
    ],
)
def test_malformed_record_blanks_are_rejected(bad):
    from pydantic import ValidationError

    from prechips.model import Inventory

    def screw(records):
        head = cylinder("head", 0, 0, 8, 4, records=records)
        return {"fixtures": {"screw": {"kind": "custom", "solids": [head]}}}

    Inventory.model_validate(screw([RECORD]))
    Inventory.model_validate(screw([{"check": "squareness", "over_mm": 100}]))
    with pytest.raises(ValidationError):
        Inventory.model_validate(screw(bad if bad == "unknown" else [bad]))


def test_inventory_keys_named_in_make_notes_print_as_the_item():
    from prechips.rules import tool_resolves

    note = "lap it with gauges.dti on gauges.granite-plate, then gauges.dti/0.5in."
    head = cylinder("head", 0, 8.26, 8, 4, note=note)
    data = bundle([{"fixture": "bridge", "pose": IDENTITY}])
    data.inventory["gauges"] = {"dti": {"kind": "dti", "name": "test indicator"}}
    data.inventory["fixtures"]["bridge"] = {
        "kind": "custom",
        "solids": [
            {"name": "beam", "shape": "box", "at_mm": [-30, -5, 0], "size_mm": [60, 10, 8.26]},
            head,
        ],
    }
    page = sheets(data)[0]
    assert "with test indicator on" in page and "gauges." not in page
    assert "? granite-plate" in page
    named = {f.subject: f.status for f in tool_resolves.evaluate(data) if f.numbers.get("named_in")}
    assert named["gauges.dti"] == "pass"
    assert named["gauges.granite-plate"] == "unknown"
    assert named["gauges.dti/0.5in"] == "unknown"


@pytest.mark.parametrize("where", ["record", "make note", "setup note", "plan prerequisite"])
def test_a_gauge_named_only_in_a_record_or_prose_gets_its_receipt_check(where):
    from prechips.rules import purchased_tooling

    data, _ = record_page(*([RECORD] if where == "record" else []))
    data.inventory["gauges"]["dti"]["acceptance"] = "unknown"
    data.plan["setups"].append({**data.plan["setups"][0], "id": "S2"})
    text = "true the head on gauges.dti first"
    if where == "make note":
        data.inventory["fixtures"]["bridge"]["solids"][1]["note"] = text
    elif where == "setup note":
        data.plan["setups"][0]["note"] = text
    elif where == "plan prerequisite":
        data.plan["stock"] = {"prerequisite": text}
    found = {f.subject: f.status for f in purchased_tooling.evaluate(data)}
    # The setup that first uses the item owns its receipt check; job-level prose is the
    # first setup's. Unknown receipt criteria are never a pass.
    assert found["S1"] == "unknown"


def same_key_receipts(s1_note, s2_note=None, s1_slots=None):
    """``fixtures.pins`` (receipt known) and ``gauges.pins`` (receipt unknown): two items
    under one key. Returns ``{setup: status}`` and ``{setup: receipt text}``."""
    from prechips.rules import purchased_tooling

    data, _ = record_page()
    data.inventory["fixtures"]["pins"] = {
        "kind": "accessory",
        "name": "fixture locating pins",
        "acceptance": [{"check": "condition", "gauge": "none", "accept": "no visible damage"}],
    }
    data.inventory["gauges"]["pins"] = {
        "kind": "pin_gauge",
        "name": "quarter-inch pin gauge",
        "dia_mm": 6.35,
        "acceptance": "unknown",
    }
    data.plan["setups"].append({**data.plan["setups"][0], "id": "S2"})
    data.plan["setups"][0] = {**data.plan["setups"][0], **(s1_slots or {})}
    for setup, note in zip(data.plan["setups"], (s1_note, s2_note), strict=True):
        if note:
            setup["note"] = note
    findings = purchased_tooling.evaluate(data)
    traveler = _Traveler(data, findings, {}, None)
    receipts = {
        setup["id"]: unescape(re.sub(r"<[^>]+>", "|", traveler.purchased_tooling(setup)))
        for setup in data.plan["setups"]
    }
    return {f.subject: f.status for f in findings}, receipts


@pytest.mark.parametrize(
    "note",
    ["Use fixtures.pins, then check with gauges.pins.", "Check with gauges.pins; fixtures.pins."],
)
def test_two_items_under_one_key_in_different_categories_each_get_their_receipt(note):
    found, receipts = same_key_receipts(note)
    assert found["S1"] == "unknown"
    assert "fixture locating pins" in receipts["S1"]
    gauge = receipts["S1"][receipts["S1"].index("quarter-inch pin gauge") :]
    assert "STOP" in gauge


def test_a_same_key_item_first_used_later_gets_its_own_receipt_table_there():
    found, receipts = same_key_receipts("Use fixtures.pins.", "Check with gauges.pins.")
    assert found == {"S1": "pass", "S2": "unknown"}
    assert "quarter-inch pin gauge" in receipts["S2"] and "STOP" in receipts["S2"]
    # The gauge's table is its own, here: no pointer back to the fixture's in S1.
    assert "fixture locating pins" not in receipts["S2"]


def test_a_receipt_table_names_its_own_category_item():
    found, receipts = same_key_receipts("Check with gauges.pins.")
    assert found == {"S1": "unknown"}
    assert "quarter-inch pin gauge" in receipts["S1"]
    assert "fixture locating pins" not in receipts["S1"]


@pytest.mark.parametrize(
    "slots",
    [
        {"hold": {"fixture": "bridge", "pose": IDENTITY, "align": {"indicator": "pins"}}},
        {"ops": [{"op": 10, "do": "inspect", "feature": "bore", "checks": {"dia": "pins"}}]},
    ],
)
def test_a_gauge_slot_reads_the_gauge_not_a_same_key_fixture(slots):
    found, receipts = same_key_receipts(None, s1_slots=slots)
    assert found == {"S1": "unknown"}
    assert "quarter-inch pin gauge" in receipts["S1"]
    assert "fixture locating pins" not in receipts["S1"]


def test_a_gauge_slot_resolves_the_gauge_not_a_same_key_fixture():
    from prechips.rules import tool_resolves

    data, _ = record_page()
    data.inventory["fixtures"]["pins"] = {"kind": "accessory", "name": "fixture locating pins"}
    data.inventory["gauges"]["pins"] = {"kind": "pin_gauge", "dia_mm": 6.35, "verify": True}
    op = {"op": 10, "do": "inspect", "feature": "bore", "checks": {"dia": "pins"}}
    data.plan["setups"][0]["ops"] = [op]
    found = {f.subject: f.status for f in tool_resolves.evaluate(data)}
    # The gauge the check reads still needs verifying: the listed fixture is another item.
    assert found["gauges.pins"] == "unknown"
    data.inventory["gauges"]["pins"]["verify"] = False
    found = {f.subject: f.status for f in tool_resolves.evaluate(data)}
    assert found["gauges.pins"] == "pass"


INSPECT = {"op": 10, "do": "inspect", "feature": "bore"}
# A slug, so a ``hold.clamp`` naming it names an item too.
KEY = "pin-set"


def _put(path, value):
    """A setup mutation setting the ``path`` slot (``hold.parallels``) to ``value``."""

    def put(setup, key):
        *parents, leaf = path.split(".")
        node = setup
        for parent in parents:
            node = node.setdefault(parent, {})
        node[leaf] = value(key)

    return put


PASSING_RECEIPT = [{"check": "condition", "gauge": "none", "accept": "no visible damage"}]
# The categories a kind of slot reads, in order (docs/inventory.md, Identity); any other
# slot reads its one category. A bare key in prose names no slot: the item it would read is
# put in gauges.
SLOT_ORDER = {
    "workholding": ("fixtures", "holders", "machines"),
    "spindle": ("tools", "gauges"),
    None: ("gauges",),
}
# The order a bare key with no slot reads, then a category no slot reads.
DEFAULT_ORDER = ("machines", "tools", "holders", "fixtures", "gauges", "services")
# Every way a setup reaches an inventory item: (path, the kind of slot, the mutation using
# the slot, whether the item is shop-made, its record blank naming a gauge).
ITEM_PATHS = [
    ("machine", "machines", _put("machine", str), False),
    ("hold.fixture", "workholding", _put("hold.fixture", str), False),
    *(
        (f"hold.{slot}", "fixtures", _put(f"hold.{slot}", str), False)
        for slot in (
            "chuck",
            "parallels",
            "riser",
            "jaw_bar",
            "jaw_buttons",
            "support",
            "supports",
            "stop_fixture",
            "support_blocks",
            "clamp",
        )
    ),
    ("hold.clamps", "fixtures", _put("hold.clamps", lambda k: [{"ref": k}]), False),
    ("hold.index.fixture", "workholding", _put("hold.index.fixture", str), False),
    ("hold.align.indicator", "gauges", _put("hold.align.indicator", str), False),
    ("zero.x.tool", "spindle", _put("zero.x.tool", str), False),
    ("zero.x.holder", "holders", _put("zero.x.holder", str), False),
    ("zero.x.gauge", "gauges", _put("zero.x.gauge", str), False),
    (
        "zero.tool_touches.tool",
        "spindle",
        _put("zero.tool_touches", lambda k: [{"tool": k}]),
        False,
    ),
    (
        "zero.tool_touches.z_gauge",
        "gauges",
        _put("zero.tool_touches", lambda k: [{"z_gauge": k}]),
        False,
    ),
    ("zero.transfer.tool", "spindle", _put("zero.transfer.tool", str), False),
    ("zero.transfer.gauge", "gauges", _put("zero.transfer.gauge", str), False),
    ("op.tool", "tools", _put("ops", lambda k: [{**INSPECT, "tool": k}]), False),
    ("op.holder", "holders", _put("ops", lambda k: [{**INSPECT, "holder": k}]), False),
    *(
        (f"op.{key}", "gauges", _put("ops", lambda k, key=key: [{**INSPECT, key: {"d": k}}]), False)
        for key in ("checks", "missing_requirements")
    ),
    (
        "op.process_holds",
        "gauges",
        _put("ops", lambda k: [{**INSPECT, "process_holds": [{"gauge": k}]}]),
        False,
    ),
    *(
        (
            f"op.guide.{slot}",
            kind,
            _put("ops", lambda k, s=slot: [{**INSPECT, "guide": {s: k}}]),
            False,
        )
        for slot, kind in (("buttons", "fixtures"), ("template", "gauges"), ("gauge", "gauges"))
    ),
    ("prose, qualified", "gauges", _put("note", lambda k: f"Check with gauges.{k}."), False),
    ("prose, bare", None, _put("note", lambda k: f"Check with the {k}."), False),
    ("shop-made fixture", "workholding", _put("hold.fixture", str), True),
    (
        "shop-made clamp",
        "fixtures",
        _put("hold.clamps", lambda k: [{"ref": k, "pose": IDENTITY}]),
        True,
    ),
    ("shop-made holder", "holders", _put("ops", lambda k: [{**INSPECT, "holder": k}]), True),
]
CATEGORY_STATES = ("listed", "item unknown", "item {}", "category unknown", "category absent")
# How the slot spells the item: its key or a set's member, bare or with its category.
REF_FORMS = ("key", "category.key", "key/member", "category.key/member")
MEMBER = "small"


def _forms(path, shop_made):
    """The spellings a path can hold. Prose is bare or qualified by the path itself; a
    ``hold.clamp`` names an item only as a slug key; a shop-made item is one solid, no set."""
    if path == "hold.clamp":
        return ("key",)
    if path.startswith("prose"):
        return ("key", "key/member")
    return ("key", "category.key") if shop_made else REF_FORMS


def _decoy_category(kind, placement):
    """A category the slot never reads, before (``earlier``) or after (``later``) the one
    it selects in the default order; None when there is none that side."""
    order = SLOT_ORDER.get(kind, (kind,))
    at = DEFAULT_ORDER.index(order[0])
    side = DEFAULT_ORDER[:at][::-1] if placement == "earlier" else DEFAULT_ORDER[at + 1 :]
    return next((category for category in side if category not in order), None)


ITEM_CASES = [
    pytest.param(
        path, kind, use, shop_made, state, placement, form, id=f"{path}|{state}|{placement}|{form}"
    )
    for path, kind, use, shop_made in ITEM_PATHS
    for state in CATEGORY_STATES
    for placement in ("none", "earlier", "later")
    for form in _forms(path, shop_made)
    if placement == "none" or _decoy_category(kind, placement)
]
# Paths this bare setup does not print by name (no align step due, no stop pointer, no
# guide or hold-feature records): there the receipt table is the only place a listed item
# is named, and an unknown one has no receipt. A bare key in prose is never a shop name.
UNPRINTED_HERE = {
    "hold.stop_fixture",
    "hold.align.indicator",
    "zero.tool_touches.z_gauge",
    "op.holder",
    "op.process_holds",
    "op.guide.buttons",
    "op.guide.template",
    "op.guide.gauge",
    "prose, bare",
    "shop-made holder",
}
# Paths the sheet names only where a bare key in prose names them: as the item the slot
# selects when a bare key reads that item too, else as written.
BARE_ONLY = {"hold.support_blocks", "hold.clamp"}


@pytest.mark.parametrize(
    ("path", "kind", "use", "shop_made", "state", "placement", "form"), ITEM_CASES
)
def test_every_item_path_reads_only_the_item_its_slot_selects(
    path, kind, use, shop_made, state, placement, form
):
    """An item is its category and key. A slot reads its own categories in order and the
    first that lists the key or is stated unknown is final; a ``<category>.<key>`` reads
    that category alone, and is the same item as its key there. The selected item (a key,
    or a set's member) is listed (unverified, receipt unknown), stated unknown, listed with
    nothing about it, its category is stated unknown, or the category is absent; a
    category the slot never reads, before or after it in the default order, lists the same
    key verified with a passing receipt. Receipt checks, resolution and every printed name
    read the selected item; the other is never read."""
    from prechips.rules import purchased_tooling, tool_resolves

    data = record_bundle()
    order = SLOT_ORDER.get(kind, (kind,))
    real = order[0]
    decoy = _decoy_category(kind, placement) if placement != "none" else None
    member = form.endswith("/member")
    key = f"{KEY}/{MEMBER}" if member else KEY
    reference = f"{real}.{key}" if form.startswith("category.") else key
    data.inventory["fixtures"]["par"] = {"kind": "parallels"}
    data.plan["setups"][0]["hold"]["parallels"] = "par"
    item = {"kind": "accessory", "name": "REAL item", "acceptance": "unknown", "verify": True}
    if shop_made:
        item = {
            "kind": "custom",
            "name": "REAL item",
            "verify": True,
            "solids": [cylinder("head", 0, 0, 8, 4, records=[RECORD])],
        }
        data.inventory["gauges"]["dti"]["acceptance"] = "unknown"
    unknown = "unknown"
    if member:
        # The set is listed; its member is the item (or is stated unknown).
        item = {**item, "name": "REAL set", "members": {MEMBER: {"name": "REAL item"}}}
        unknown = {**item, "members": {MEMBER: "unknown"}}
    for category in order:
        data.inventory.setdefault(category, {})
    if state == "category unknown":
        data.inventory[real] = "unknown"
    elif state == "category absent":
        del data.inventory[real]
    else:
        data.inventory[real][KEY] = {"listed": item, "item unknown": unknown, "item {}": {}}[state]
    if decoy:
        other = {"kind": "accessory", "name": "DECOY", "acceptance": PASSING_RECEIPT}
        if member:
            other["members"] = {MEMBER: {"name": "DECOY"}}
        listed = {**data.inventory.pop(decoy, {}), KEY: other}
        rest = dict(data.inventory)
        data.inventory.clear()
        # In the shop list's own order too, the decoy is where the placement says.
        data.inventory.update(
            {decoy: listed, **rest} if placement == "earlier" else {**rest, decoy: listed}
        )
    setup = data.plan["setups"][0]
    use(setup, reference)

    receipts = purchased_tooling.evaluate(data)
    owners = [(row["category"], row["ref"]) for f in receipts for row in f.numbers["items"]]
    assert not {(decoy, KEY), (decoy, key)} & set(owners)
    if state == "listed" and kind is not None:
        (receipt,) = receipts
        assert receipt.status == "unknown"
        assert (("gauges", "dti") if shop_made else (real, KEY)) in owners
    resolved = [f for f in tool_resolves.evaluate(data) if f.numbers.get("reference") == key]
    assert {f.subject for f in resolved} <= {key, f"{real}.{key}"}
    assert {f.numbers["category"] for f in resolved} <= {real}
    if kind is None:
        assert not resolved  # a bare key in prose is no slot: it selects nothing
    else:
        # Unverified, unknown or empty is unknown; not listed where the slot reads is an
        # error (a named one in prose is unknown). Never a pass: only the decoy passes.
        absent = "unknown" if path == "prose, qualified" else "error"
        assert {f.status for f in resolved} == {absent if state == "category absent" else "unknown"}

    # The dividing head names the hold's fixture; touch-offs name their tool.
    index = Finding("indexing", "S1", "pass", {"rotation": True, "fixture": reference}, [], ".")
    traveler = _Traveler(data, [*receipts, index], {}, None)
    printed = traveler.purchased_tooling(setup)
    if path != "op.process_holds":  # an inspect op without its hold feature does not render
        printed += sheets(data)[0]
    if kind == "workholding" and not shop_made:
        printed += traveler.indexing({**setup, "hold": {"index": {}, **setup["hold"]}})
    if kind in ("spindle", "tools"):
        printed += traveler.touched_tool(reference, {}, kind)
    bare = traveler.bench(f"Use the {key}.", setup)
    printed += bare
    assert "DECOY" not in printed
    if kind is None or placement == "earlier":
        # A bare key reads the decoy's category first, or names no slot: it names no one
        # item and prints as written.
        assert bare == f"Use the {key}."
    if state == "listed" and path not in ("prose, bare", "shop-made holder"):
        assert "REAL" in printed  # (a shop-made holder prints its record's gauge)
    unprinted = path in UNPRINTED_HERE or (path in BARE_ONLY and placement == "earlier")
    if state in ("item unknown", "item {}", "category unknown") and not unprinted:
        assert f"? {real}.{key}" in printed


def drill_note(note):
    from prechips.rules import tool_resolves

    data, _ = record_page()
    data.inventory["tools"] = {
        "drills": {
            "kind": "drill_index",
            "name": "jobber drill index",
            "coverage": "#1-60, A-Z, 1/16-1/2 by 64ths",
        }
    }
    data.inventory["gauges"]["pins"] = {
        "kind": "pin_gauge_set",
        "name": "pin set",
        "members": {
            "1": {"kind": "pin_gauge", "name": "one-inch pin", "dia_mm": 25.4},
            "1/4": {"kind": "pin_gauge", "name": "quarter-inch pin", "dia_mm": 6.35},
        },
    }
    data.inventory["fixtures"]["bridge"]["solids"][1]["note"] = note
    named = {f.subject: f.status for f in tool_resolves.evaluate(data) if f.numbers.get("named_in")}
    return sheets(data)[0], named


@pytest.mark.parametrize(
    ("reference", "status", "printed"),
    [
        ("tools.drills/#7", "pass", "#7 drill index."),
        ("tools.drills/#61", "unknown", "? drills/#61."),
        ("tools.drills/1/4", "pass", "1/4 drill index."),
        ("tools.drills/1-4", "pass", "1-4 drill index."),
        ("gauges.pins/1/4", "pass", "quarter-inch pin."),
        ("gauges.pins/1", "pass", "one-inch pin."),
    ],
)
def test_a_named_member_is_the_whole_member_never_a_prefix(reference, status, printed):
    page, named = drill_note(f"Use {reference}.")
    assert named == {reference: status}
    assert page[page.index("Use ") :].split("|")[0].endswith(printed)


def test_a_record_gauge_must_be_in_the_shop_list():
    from prechips.rules import tool_resolves

    data, page = record_page({**RECORD, "gauge": "no-such-gauge"})
    assert "? no-such-gauge" in page
    named = {f.subject: f.status for f in tool_resolves.evaluate(data) if f.numbers.get("named_in")}
    assert named["gauges.no-such-gauge"] == "unknown"


def test_bought_part_drawn_as_head_and_shank_counts_once():
    screw = {"supply": "bought", "fastener": "M8 SHCS"}
    parts = [
        piece
        for x in (-40, 40)
        for piece in (
            cylinder(f"screw-head-{x}", x, 30, 13, 8, **screw),
            cylinder(f"screw-shank-{x}", x, 0, 8, 30, **screw),
        )
    ]
    table = bridge_page(*parts)
    hardware = table.line("Bought hardware")
    assert "; 2 × M8 SHCS." in hardware
    assert hardware.count("M8 SHCS") == 1


def test_custom_item_with_nothing_to_make_gets_no_table_or_pointer():
    data = bundle([{"fixture": "rest", "pose": IDENTITY}])
    data.inventory["fixtures"]["rest"] = {
        "kind": "custom",
        "solids": [
            {
                "name": "plate",
                "shape": "box",
                "at_mm": [0, 0, -10],
                "size_mm": [50, 50, 10],
                "supply": "existing",
            }
        ],
    }
    page = sheets(data)[0]
    assert "SHOP-MADE" not in page and "shop-made" not in page


def test_existing_part_drilled_here_lists_only_its_holes():
    plate = {
        "name": "plate",
        "shape": "box",
        "at_mm": [-50, -50, -20],
        "size_mm": [100, 100, 10],
        "supply": "existing",
    }
    hole = cylinder("tap", 40, -20, 8.5, 10, void=True, cuts=["plate"], fastener="M10 tapped")
    table = bridge_page(plate, hole)
    assert table.row("plate (existing part: make the holes only)")["Size mm"] == "—"
    assert "with 1 × M10 tapped: axis at X 40, Y 0; Z -20…-10" in table.position(
        "plate (existing part: make the holes only)"
    )
    assert "100 × 100 × 10" not in table and "vise" not in table


def existing_tapped_fixture(count=1, identity_words=()):
    """An existing plate whose only made features are the declared tapped holes."""
    data = bundle([{"fixture": "plate", "pose": IDENTITY}])
    data.inventory["fixtures"]["plate"]["solids"] = [
        {
            "name": "plate",
            "shape": "box",
            "at_mm": [0, -5, -20],
            "size_mm": [100, 10, 10],
            "supply": "existing",
        },
        *(
            cylinder(
                f"tap-{index}",
                index,
                -20,
                8.5,
                10,
                void=True,
                cuts=["plate"],
                fastener=" ".join(["M10 tapped", f"Feature{index:03}", *identity_words]),
            )
            for index in range(count)
        ),
    ]
    return data


def test_existing_tapped_feature_identity_and_coordinates_keep_their_original_owner():
    data = existing_tapped_fixture(2)
    table = sheets(data)[0].fixture()
    (row,) = table.rows()
    assert row["Component"] == "plate (existing part: make the holes only)"
    assert row["Size mm"] == "—"
    assert list(row) == ["Component", "Size mm", "Position, Setup S1 X / Y / Z mm"]
    clauses = row["Position, Setup S1 X / Y / Z mm"].split("with ")
    assert clauses[0].split() == "X 0…100, Y -5…5, Z -20…-10".split()
    assert [clause.split() for clause in clauses[1:]] == [
        "1 × M10 tapped Feature000: axis at X 0, Y 0; Z -20…-10".split(),
        "1 × M10 tapped Feature001: axis at X 1, Y 0; Z -20…-10".split(),
    ]


def test_fixture_numbers_print_at_policy_make_precision_and_fits_at_drawing_precision():
    table = bridge_page(fixture_make_decimals=1)
    assert table.row("beam")["Size mm"] == "60 × 10 × 8.3"
    assert "Ø20.6 × 1.6" in table.line("Bought hardware")
    # The locating pad is a fit: drawing precision (3), not the make precision.
    assert table.row("pad")["Size mm"] == "10 × 10 × 2.346"


def test_a_locating_solid_with_a_bore_in_it_is_a_fit_as_well_as_its_bore():
    # A stand locates the part on its own top face; the bore through it does not make that
    # face a make-precision number.
    stand = cylinder("stand", 0, -17, 9.94, 9.94, locates="hub face")
    bore = cylinder("stand-bore", 0, -18, 4.5, 12, void=True, cuts=["stand"])
    table = bridge_page(stand, bore, fixture_make_decimals=1)
    assert table.row("stand")["Size mm"] == "Ø9.94 × 9.94"
    assert "Z -17…-7.06" in table.position("stand")
    assert "Ø9.9 × 9.9" not in table and "-7.1" not in table


# The shop's mill reads 0.005 mm; a pin locating the part stands in a hole in the beam.
FIVE_MICRON = {"resolution_mm": 0.005}
DIAL = (
    cylinder("pin", -0.368, 8.26, 4, 6, locates="cap bore"),
    cylinder("pin-hole", -0.368, -1, 4, 12, void=True, cuts=["beam"]),
    # A 3/4 in rail: half a 0.1 make step rounds up, whatever the float noise.
    {"name": "rail", "shape": "box", "at_mm": [60, -5, 0], "size_mm": [19.05, 5, 5]},
)


def test_fixture_positions_print_on_the_mill_grid_one_value_per_place():
    table = bridge_page(*DIAL, precision="unknown", mill=FIVE_MICRON, fixture_make_decimals=1)
    # The pin is a fit: on the mill's 0.005 grid, not 3 places off it.
    assert "axis at X -0.37, Y 0; Z 8.26…14.26" in table.position("pin")
    # The hole the pin stands in prints the same X, not the 0.1 make precision.
    assert "with 1 × Ø4 hole: axis at X -0.37, Y 0; Z -1…11" in table.position("beam")
    assert "-0.368" not in table and "X -0.4," not in table
    # The locating pad's 2.3456 thickness and underside are on the grid too.
    assert table.row("pad")["Size mm"] == "10 × 10 × 2.345"
    assert "Z -2.345…0" in table.position("pad")
    assert table.row("rail")["Size mm"] == "19.1 × 5 × 5"


@pytest.mark.parametrize(
    ("tolerances", "printed"),
    [({"linear_3pl": 0.13}, "X -0.37,"), ({"linear_3pl": 0.001}, "X ?,"), ({}, "X ?,")],
)
def test_a_fit_the_mill_grid_moves_beyond_the_drawing_tolerance_is_unknown(tolerances, printed):
    table = bridge_page(*DIAL, precision=3, mill=FIVE_MICRON, tolerances=tolerances)
    pin = table.position("pin")
    assert f"axis at {printed} Y 0; Z 8.26…14.26" in pin
    # The hole it stands in is the same place: never a different, silently moved value.
    assert f"with 1 × Ø4 hole: axis at {printed} Y 0" in table.position("beam")
    if "?" in printed:
        assert "cannot hold" in table and "linear_3pl" in table


def test_separate_bought_parts_with_one_fastener_text_count_apart():
    screw = {"supply": "bought", "fastener": "M8 SHCS"}
    table = bridge_page(
        cylinder("screw-a", -40, 20, 8, 20, **screw), cylinder("screw-b", 40, 20, 8, 30, **screw)
    )
    assert "; 2 × M8 SHCS." in table.line("Bought hardware")


def test_hole_through_stacked_parts_prints_in_every_part_it_cuts():
    lower = {"name": "lower", "shape": "box", "at_mm": [60, -5, 0], "size_mm": [10, 10, 5]}
    upper = {"name": "upper", "shape": "box", "at_mm": [60, -5, 5], "size_mm": [10, 10, 4]}
    hole = cylinder("pin-hole", 65, 0, 3, 9, void=True, cuts=["lower", "upper"])
    table = bridge_page(lower, upper, hole)
    for component in ("lower", "upper"):
        assert table.position(component).count("with 1 × Ø3 hole: axis at X 65, Y 0; Z 0…9") == 1


def test_unverified_primitive_prints_no_make_numbers():
    block = {
        "name": "gauge-block",
        "shape": "box",
        "at_mm": [70, -5, 0],
        "size_mm": [12.5, 7, 3],
        "verify": True,
    }
    table = bridge_page(block)
    assert table.row("gauge block")["Size mm"] == "?"
    assert "? not set: unverified; verify before making" in table.position("gauge block")
    assert "12.5 × 7 × 3" not in table and "X 70" not in table


def test_existing_and_made_parts_of_one_size_keep_separate_rows():
    old = {
        "name": "old",
        "shape": "box",
        "at_mm": [60, -5, 0],
        "size_mm": [10, 10, 5],
        "supply": "existing",
    }
    new = {"name": "new", "shape": "box", "at_mm": [80, -5, 0], "size_mm": [10, 10, 5]}
    hole = cylinder("tap", 65, 0, 5, 5, void=True, cuts=["old"], fastener="M6 tapped")
    table = bridge_page(old, new, hole)
    assert table.row("old (existing part: make the holes only)")["Size mm"] == "—"
    assert "with 1 × M6 tapped: axis at X 65, Y 0; Z 0…5" in table.position(
        "old (existing part: make the holes only)"
    )
    assert table.row("new")["Size mm"] == "10 × 10 × 5"
    assert "X 80…90, Y -5…5, Z 0…5" in table.position("new")
    assert "old / new" not in table


def test_renumbered_clamp_gets_its_own_table_not_a_pointer():
    clamp = {"ref": "plate", "restraint": "press", "pose": IDENTITY}
    first, later = sheets(
        bundle([{"clamps": [clamp]}, {"clamps": [{"ref": "strap", "restraint": "none"}, clamp]}])
    )
    assert "(C1)" in first
    assert "SHOP-MADE FIXTURE —" in later
    assert not any(
        "Setup S1" in content(node) and "SHOP-MADE FIXTURE table" in content(node)
        for node in descendants(later.markup, "li")
    )


def test_each_placement_of_an_item_builds_its_own_shim_stacks():
    clamps = [
        {"ref": "plate", "restraint": "press", "pose": IDENTITY},
        {"ref": "plate", "restraint": "press", "pose": TURNED},
    ]
    page = sheets(bundle([{"clamps": clamps}]))[0]
    (step,) = [
        content(node) for node in descendants(page.markup, "li") if "shim stacks" in content(node)
    ]
    assert "4 shim stacks under the rail (C1 shim R, C2 shim R, C1 shim L, C2 shim L)" in step
    assert step.count("0.472 mm nominal") == 1


def test_hole_without_cuts_prints_in_every_part_it_passes_through():
    lower = {"name": "lower", "shape": "box", "at_mm": [60, -5, 0], "size_mm": [10, 10, 5]}
    upper = {"name": "upper", "shape": "box", "at_mm": [60, -5, 5], "size_mm": [10, 10, 4]}
    hole = cylinder("pin-hole", 65, 0, 3, 9, void=True)
    table = bridge_page(lower, upper, hole)
    for component in ("lower", "upper"):
        assert table.position(component).count("with 1 × Ø3 hole: axis at X 65, Y 0; Z 0…9") == 1
    # Unverified, the same hole withholds both parts it would cut.
    table = bridge_page(lower, upper, {**hole, "verify": True})
    for component in ("lower", "upper"):
        assert table.row(component)["Size mm"] == "?"
        assert "? not set: its hole pin-hole is unverified" in table.position(component)
    assert "X 60…70" not in table


def test_bought_primitives_count_together_only_when_they_touch():
    screw = {"supply": "bought", "fastener": "M8 SHCS"}
    # Parallel Ø8 shanks 9.9 apart: their bounding boxes overlap, the screws do not.
    near = cylinder("screw-a", 0, 20, 8, 20, **screw)
    apart = {**cylinder("screw-b", 7, 20, 8, 20, **screw), "at_mm": [7, 7, 20]}
    assert "; 2 × M8 SHCS." in bridge_page(near, apart).line("Bought hardware")
    # A Ø13 head resting on the end of its shank is one screw.
    head = cylinder("screw-head", 0, 40, 13, 8, **screw)
    assert "; 1 × M8 SHCS." in bridge_page(near, head).line("Bought hardware")


def test_oblique_hole_without_cuts_withholds_the_part_it_may_cross():
    plate = {"name": "plate", "shape": "box", "at_mm": [60, -5, 0], "size_mm": [10, 10, 0.1]}
    hole = {
        "name": "slant",
        "shape": "cylinder",
        "at_mm": [35, 0, -40],
        "axis": [0.6, 0, 0.8],
        "dia_mm": 1,
        "length_mm": 100,
        "void": True,
    }
    table = bridge_page(plate, hole)
    assert table.row("plate")["Size mm"] == "?"
    assert "? not set: oblique hole slant may cross it; name it in cuts" in table.position("plate")
    assert "X 60…70" not in table
    # Named in cuts, the hole prints in the plate's row.
    table = bridge_page(plate, {**hole, "cuts": ["plate"]})
    assert "X 60…70, Y -5…5, Z 0…0.1|with 1 × Ø1 hole" in table


# A soft-jaw plate bolted to a vise jaw, drawn in its own frame: the vise places it.
SOFT_JAWS = {
    "kind": "vise",
    "shop_made": True,
    "solids": [
        {"name": "jaw-plate", "shape": "box", "at_mm": [0, 0, 0], "size_mm": [150, 20, 60]},
        {
            "name": "bolt-hole",
            "shape": "cylinder",
            "at_mm": [25, 0, 30],
            "axis": [0, 1, 0],
            "dia_mm": 11,
            "length_mm": 20,
            "void": True,
            "fastener": "M10 jaw bolt",
        },
    ],
}
BUTTONS = {
    "kind": "jaw_buttons",
    "shop_made": True,
    "solids": [
        {
            "name": "button",
            "shape": "cylinder",
            "at_mm": [0, 0, 0],
            "axis": [0, 0, 1],
            "dia_mm": 20,
            "length_mm": 6,
        },
    ],
}


def loose_page(hold, **items):
    data = bundle([hold])
    data.inventory["fixtures"].update(items)
    page = sheets(data)[0]
    return page, page[page.index("SHOP-MADE FIXTURE —") :]


def test_an_item_the_hold_places_prints_its_make_table_in_its_own_frame():
    _, table = loose_page({"fixture": "soft-jaws", "jaws_along": "x"}, **{"soft-jaws": SOFT_JAWS})
    assert "loose: placed as the HOLD says" in table
    assert "? not posed" not in table
    # Sizes and the bolt hole stand where the make table draws them, in the item frame.
    assert "150 × 20 × 60" in table and "X 0…150, Y 0…20, Z 0…60" in table
    assert "M10 jaw bolt" in table and "axis at X 25, Z 30" in table


def test_jaw_buttons_get_a_make_table_and_the_hold_points_to_it():
    page, table = loose_page({"fixture": "angle", "jaw_buttons": "buttons"}, buttons=BUTTONS)
    assert "Jaw buttons: " in page and "(shop-made: SHOP-MADE FIXTURE table, sheet 2)" in page
    assert "Ø20 × 6" in table and "loose: placed as the HOLD says" in table


def test_a_fixture_placed_by_its_pose_still_stops_without_one():
    _, table = loose_page({"fixture": "plate"})
    assert "? not posed" in table and "loose" not in table


MAKE_OP = {
    "hold": "vise on parallels",
    "tool": "endmill-6",
    "rpm": 1600,
    "feed": "0.05 mm/rev",
    "doc_mm": 0.5,
    "cite": "MH 31st Table 17 p.1061",
}
END_MILL = {"kind": "endmill", "name": "3-flute end mill", "dia_mm": 6}


def make_page(*ops, item_ops=None, tools=None):
    """The bridge fixture made by ``item_ops`` (the item's own) and ``ops`` (its head's);
    the shop's tools list ``endmill-6``."""
    head = cylinder("head", 0, 8.26, 8, 4, **({"make_ops": list(ops)} if ops else {}))
    data = bundle([{"fixture": "bridge", "pose": IDENTITY}])
    data.inventory["tools"] = {"endmill-6": dict(END_MILL)} if tools is None else tools
    data.inventory["fixtures"]["bridge"] = {
        "kind": "custom",
        "solids": [
            {"name": "beam", "shape": "box", "at_mm": [-30, -5, 0], "size_mm": [60, 10, 8.26]},
            head,
        ],
        **({} if item_ops is None else {"make_ops": item_ops}),
    }
    page = sheets(data)[0]
    return data, page[page.index("SHOP-MADE FIXTURE") :]


def make_lines(table):
    """The table's numbered make-operation lines, in print order."""
    return [line for line in table.split("|") if re.match(r"\d+\. ", line)]


def test_each_make_operation_prints_one_cutting_data_line_in_order():
    rough = {**MAKE_OP, "hold": "bandsaw vise", "rpm": [400, 600], "feed": "0.1 mm/rev"}
    finish = {**MAKE_OP, "doc_mm": 0.25, "cite": "MH 31st Table 15a p.1040"}
    _, table = make_page(finish, item_ops=[rough])
    first, second = make_lines(table)
    # The item's own operations run first, then each primitive's after its row name.
    assert first.startswith("1. ") and second.startswith("2. head")
    for line, op, speed in ((first, rough, "400–600 rpm"), (second, finish, "1600 rpm")):
        assert f"hold: {op['hold']}" in line and "6 mm 3-flute end mill" in line
        assert speed in line and op["feed"] in line and op["cite"] in line
        assert f"{op['doc_mm']:g} mm/pass" in line and "STOP" not in line and "?" not in line


@pytest.mark.parametrize("field", ["hold", "tool", "rpm", "feed", "doc_mm", "cite"])
def test_an_unknown_make_fact_prints_and_stops_never_omitted(field):
    _, table = make_page(item_ops=[{**MAKE_OP, field: "unknown"}])
    (line,) = make_lines(table)
    assert "?" in line and "STOP" in line
    # Every other fact still prints: one unknown never hides the rest of the line.
    known = {key: value for key, value in MAKE_OP.items() if key != field}
    assert all(str(value) in line for key, value in known.items() if key != "tool")
    assert field == "tool" or "6 mm 3-flute end mill" in line


@pytest.mark.parametrize("tools", [{}, {"endmill-8": END_MILL}, "unknown"])
def test_a_make_tool_the_shop_tools_do_not_list_stops(tools):
    _, table = make_page(item_ops=[MAKE_OP], tools=tools)
    (line,) = make_lines(table)
    assert "? endmill-6" in line and "STOP" in line


def test_an_unknown_make_operation_list_stops():
    _, table = make_page(item_ops="unknown")
    (line,) = make_lines(table)
    assert "?" in line and "STOP" in line


@pytest.mark.parametrize(
    "bad",
    [
        {**MAKE_OP, "feed": "0.05"},
        {**MAKE_OP, "feed": "0.05 per rev"},
        {**MAKE_OP, "feed": " "},
        {**MAKE_OP, "cite": " "},
        {key: value for key, value in MAKE_OP.items() if key != "cite"},
        {key: value for key, value in MAKE_OP.items() if key != "rpm"},
        {**MAKE_OP, "rpm": [600, 400]},
        {**MAKE_OP, "rpm": 0},
        {**MAKE_OP, "doc_mm": -0.5},
        {**MAKE_OP, "tool": ""},
        {**MAKE_OP, "speed": 600},
    ],
)
def test_malformed_make_operations_are_rejected(bad):
    from pydantic import ValidationError

    from prechips.model import Inventory

    def item(op, **extra):
        head = cylinder("head", 0, 0, 8, 4, **extra)
        return {"fixtures": {"screw": {"kind": "custom", "solids": [head], "make_ops": [op]}}}

    unknown = dict.fromkeys(MAKE_OP, "unknown")
    for good in (MAKE_OP, unknown, {**MAKE_OP, "rpm": [400, 600], "feed": "120 mm/min"}):
        Inventory.model_validate(item(good))
    with pytest.raises(ValidationError):
        Inventory.model_validate(item(bad))


@pytest.mark.parametrize("owner", ["bought item", "bought primitive"])
def test_only_what_is_made_here_has_make_operations(owner):
    from pydantic import ValidationError

    from prechips.model import Inventory

    plate = {"kind": "angle_plate", "make_ops": [MAKE_OP]}
    if owner == "bought primitive":
        stud = cylinder("stud", 0, 0, 8, 4, supply="bought", make_ops=[MAKE_OP])
        plate = {"kind": "custom", "solids": [stud]}
    with pytest.raises(ValidationError):
        Inventory.model_validate({"fixtures": {"plate": plate}})


@pytest.mark.parametrize(
    ("change", "status"),
    [
        ({}, "pass"),
        ({"rpm": "unknown"}, "unknown"),
        ({"tool": "unknown"}, "unknown"),
        ({"tool": "dti"}, "error"),
        ({"tool": "endmill-8"}, "error"),
    ],
)
def test_a_make_operation_tool_must_resolve_in_the_shop_tools(change, status):
    from prechips.rules import tool_resolves

    data, _ = make_page({**MAKE_OP, **change})
    data.inventory["gauges"] = {"dti": {"kind": "dti"}}
    found = [f for f in tool_resolves.evaluate(data) if f.numbers.get("make_op")]
    assert [f.status for f in found] == [status]


def test_a_make_operation_tool_gets_its_receipt_check():
    from prechips.rules import purchased_tooling

    tools = {"endmill-6": {**END_MILL, "acceptance": "unknown"}}
    data, _ = make_page(item_ops=[MAKE_OP], tools=tools)
    found = {f.subject: f.status for f in purchased_tooling.evaluate(data)}
    assert found["S1"] == "unknown"


def test_an_item_a_make_operation_names_in_its_hold_is_checked():
    from prechips.rules import tool_resolves

    data, table = make_page(item_ops=[{**MAKE_OP, "hold": "clamped on gauges.granite-plate"}])
    (line,) = make_lines(table)
    assert "? granite-plate" in line and "gauges." not in line
    named = {f.subject: f.status for f in tool_resolves.evaluate(data) if f.numbers.get("named_in")}
    assert named["gauges.granite-plate"] == "unknown"


def make_statuses(data):
    from prechips.rules import tool_resolves

    return [f.status for f in tool_resolves.evaluate(data) if f.numbers.get("make_op")]


@pytest.mark.parametrize("supplies", [["bought"], ["existing"], ["bought", "existing"]])
def test_make_operations_on_an_item_with_nothing_made_here_are_refused(supplies):
    from pydantic import ValidationError

    from prechips.model import Inventory

    def plate(*supply):
        solids = [cylinder(f"part-{n}", 10 * n, 0, 8, 4, supply=s) for n, s in enumerate(supply)]
        return {"fixtures": {"plate": {"kind": "custom", "solids": solids, "make_ops": [MAKE_OP]}}}

    # No solid is made here, so no make table prints: its operations are refused, never
    # accepted and then left off the traveler.
    Inventory.model_validate(plate(*supplies, "made"))
    with pytest.raises(ValidationError):
        Inventory.model_validate(plate(*supplies))


@pytest.mark.parametrize("where", ["tools", "gauges", "services", "member"])
def test_make_operations_go_only_where_a_make_table_prints_them(where):
    from pydantic import ValidationError

    from prechips.model import Inventory

    item = {"kind": "custom", "solids": [cylinder("ring", 0, 0, 20, 6)], "make_ops": [MAKE_OP]}
    for category in ("fixtures", "holders", "machines"):
        Inventory.model_validate({category: {"lap": item}})
    plain = {key: value for key, value in item.items() if key != "make_ops"}
    bad = (
        {"fixtures": {"laps": {**plain, "members": {"a": item}}}}
        if where == "member"
        else {where: {"lap": item}}
    )
    with pytest.raises(ValidationError):
        Inventory.model_validate(bad)


@pytest.mark.parametrize("slot", ["parallels", "jaw_bar", "support"])
def test_a_held_item_without_a_make_table_still_prints_its_make_operations(slot):
    data = bundle([{"fixture": "angle", slot: "rest"}, {"fixture": "angle", slot: "rest"}])
    data.inventory["tools"] = {"endmill-6": dict(END_MILL)}
    data.inventory["fixtures"]["rest"] = {
        "kind": "custom",
        "solids": [cylinder("rest", 0, 0, 20, 6)],
        "make_ops": [MAKE_OP],
    }
    first, second = (page.partition("SHOP-MADE")[2] for page in sheets(data))
    # Once, before the first setup holding with it; its finding is the line's.
    (line,) = make_lines(first)
    assert not make_lines(second)
    assert "6 mm 3-flute end mill" in line and MAKE_OP["cite"] in line and "STOP" not in line
    assert make_statuses(data) == ["pass"]


@pytest.mark.parametrize("flag", [{"verify": True}, {"verify": "unknown"}, {"present": "unknown"}])
def test_an_unverified_make_tool_prints_unknown_and_stops(flag):
    data, table = make_page(item_ops=[MAKE_OP], tools={"endmill-6": {**END_MILL, **flag}})
    (line,) = make_lines(table)
    assert "? " in line and "STOP" in line and "6 mm 3-flute end mill" in line
    assert make_statuses(data) == ["unknown"]


@pytest.mark.parametrize("key", ["included", "standard_accessories"])
def test_a_machine_accessory_the_tools_do_not_list_is_no_make_tool(key):
    from prechips.rules.resolution import setup_items

    data, _ = make_page(item_ops=[MAKE_OP], tools={})
    data.inventory["machines"]["mill"][key] = ["endmill-6"]
    page = sheets(data)[0]
    (line,) = make_lines(page[page.index("SHOP-MADE FIXTURE") :])
    assert "? endmill-6" in line and "STOP" in line
    assert make_statuses(data) == ["error"]
    # Its receipt slot is the tools item, never the accessory: the tools list lacks it.
    assert ("tools", "endmill-6", None) in setup_items(data, data.plan["setups"][0])


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("cite", "https://example.com/cutting-data"),
        ("cite", "Vendor chart https://example.com/em.pdf p.3"),
        ("hold", "as drawn in https://example.com/hold.png"),
        ("hold", "per /srv/charts/fixtures.bridge.pdf"),
        ("cite", r"\\shop-nas\charts\tools.chart.pdf"),
        ("cite", "./charts/tools.chart.pdf"),
        ("hold", "per ../charts/fixtures.bridge.pdf"),
    ],
)
def test_authored_make_text_prints_whole(field, value):
    from prechips.rules import tool_resolves

    data, table = make_page(item_ops=[{**MAKE_OP, field: value}])
    (line,) = make_lines(table)
    assert value in line and "STOP" not in line
    assert make_statuses(data) == ["pass"]
    # A link or path is the source as written: nothing in it is read as an inventory name.
    assert not [f for f in tool_resolves.evaluate(data) if f.numbers.get("named_in")]


@pytest.mark.parametrize(
    ("hold", "printed", "unknown"),
    [
        ("indicate with gauges.dti", "indicate with ? dti", ["gauges.dti"]),
        ("indicate with (gauges.dti),", "indicate with (? dti),", ["gauges.dti"]),
        ("indicate with `gauges.dti`", "indicate with `? dti`", ["gauges.dti"]),
        ("indicate with “gauges.dti”", "indicate with “? dti”", ["gauges.dti"]),
        (
            "use fixtures.missing,gauges.dti",
            "use ? missing,? dti",
            ["fixtures.missing", "gauges.dti"],
        ),
        (
            "indicate with gauges.dti;check runout",
            "indicate with ? dti;check runout",
            ["gauges.dti"],
        ),
        (
            "indicate with gauges.dti (https://tools.example.com/chart)",
            "indicate with ? dti (https://tools.example.com/chart)",
            ["gauges.dti"],
        ),
        ("per https://tools.example.com/chart", "per https://tools.example.com/chart", []),
        (r"per C:\shop\tools.chart.pdf", r"per C:\shop\tools.chart.pdf", []),
    ],
    ids=[f"token-{n}" for n in range(9)],
)
def test_an_item_named_in_make_text_is_checked_outside_links_and_paths(hold, printed, unknown):
    from prechips.rules import tool_resolves

    data, table = make_page(item_ops=[{**MAKE_OP, "hold": hold}])
    (line,) = make_lines(table)
    # Each name the shop list lacks prints its marker and stays unknown, whatever
    # punctuation or quotes sit next to it; a link or path prints as written.
    assert f"hold: {printed};" in line
    named = {f.subject: f.status for f in tool_resolves.evaluate(data) if f.numbers.get("named_in")}
    assert named == dict.fromkeys(unknown, "unknown")


@pytest.mark.parametrize(
    ("holds", "tabled"),
    [
        ([{"fixture": "angle", "support": "rest"}, {"fixture": "rest", "pose": IDENTITY}], [2]),
        ([{"fixture": "rest", "pose": IDENTITY}, {"fixture": "rest", "pose": TURNED}], [1, 2]),
        ([{"fixture": "rest", "pose": IDENTITY}, {"fixture": "angle", "support": "rest"}], [1]),
    ],
    ids=["support-then-table", "two-tables", "table-then-support"],
)
def test_make_operations_print_once_at_the_first_use(holds, tabled):
    data = bundle(holds)
    data.inventory["tools"] = {"endmill-6": dict(END_MILL)}
    data.inventory["fixtures"]["rest"] = {
        "kind": "custom",
        "solids": [cylinder("rest", 0, 0, 20, 6)],
        "make_ops": [MAKE_OP],
    }
    first, second = (page.partition("SHOP-MADE")[2] for page in sheets(data))
    # Made before the first setup holding with it, whichever slot; never again later.
    (line,) = make_lines(first)
    assert MAKE_OP["cite"] in line and "STOP" not in line
    assert not make_lines(second) and "Make before Setup S2" not in second
    assert make_statuses(data) == ["pass"]
    # A later make table and the operations before it each name the other's sheet.
    if 2 in tabled:
        assert "Setup S1 sheet 2" in second
    if 1 not in tabled:
        assert "Setup S2 sheet 2" in first


@pytest.mark.parametrize(
    "member", [{"supply": "bought"}, {"supply": "existing"}, {"kind": "plate"}]
)
def test_a_member_keeps_its_set_make_operations_only_where_it_is_made(member):
    from pydantic import ValidationError

    from prechips.model import Inventory

    def bridge(own):
        supply = {"supply": own["supply"]} if "supply" in own else {}
        override = {key: value for key, value in own.items() if key != "supply"}
        one = {"solids": [cylinder("one", 0, 0, 20, 6, **supply)], **override}
        return {
            "fixtures": {
                "bridge": {
                    "kind": "custom",
                    "solids": [cylinder("head", 0, 0, 8, 4)],
                    "make_ops": [MAKE_OP],
                    "members": {"one": one},
                }
            }
        }

    # The member is the set's record with its own keys over it: the set's operations are
    # its own, so a member that makes nothing here (no make table) is refused.
    Inventory.model_validate(bridge({"supply": "made"}))
    with pytest.raises(ValidationError):
        Inventory.model_validate(bridge(member))
