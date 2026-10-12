"""Fact-local traveler debt, using only isolated host data and existing sheet seams.

No examples, frozen shop inputs, native geometry preparation or subprocesses are used.
"""

import re
from copy import deepcopy
from pathlib import Path

import pytest
from test_sheet_ops import Markup, content

from prechips.findings import Finding
from prechips.inputs import Bundle
from prechips.measurements import length_debt, measurement_entry
from prechips.rules._envelope import measurement_item
from prechips.sheet import _Box, _Plain, _Traveler


def actions(markup):
    return {
        node["attrs"]["data-measurement-id"]: node
        for node in markup.nodes
        if "data-measurement-id" in node["attrs"]
    }


def marker_for(sheet, entry):
    return "?" + sheet.measurement_registry()[entry["id"]][0]


def full_action(sheet, entry):
    """The complete leaf instruction; its subject is supplied by the group heading."""
    return measurement_entry(
        entry["category"],
        entry["identity"],
        tuple(entry["field"]),
        item=measurement_item(sheet.bundle, entry["category"], entry["identity"]),
        subject="its",
    )["instruction"]


FRAME = {
    "origin": [0.0, 0.0, 0.0],
    "x": [1.0, 0.0, 0.0],
    "y": [0.0, 1.0, 0.0],
    "z": [0.0, 0.0, 1.0],
    "binding": "nominal",
}


def fact(value, status="measured"):
    return {
        "value": value,
        "measured": {
            "status": status,
            # This prose must not demote an explicitly complete measured record.
            "by": "synthetic example, not a physical shop measurement",
            "date": "2026-10-01",
            "instrument": "synthetic fixture",
        },
    }


def data(ops=None, tools=None):
    setup = {
        "id": "S1",
        "machine": "mill",
        "frame": "F",
        "stock_in": "stock",
        "stock_state": {"top_z": 10.0, "bottom_z": 0.0},
        "ops": ops
        if ops is not None
        else [{"op": 10, "do": "face", "feature": "deck", "tool": "cutter", "to_z": 8.0}],
    }
    return Bundle(
        plan={
            "part": "Synthetic presentation part",
            "revision": "R1",
            "drawing": {"revision": "R1"},
            "dro": {"controller": "test", "mode": "abs", "radius_mode": False},
            "setups": [setup],
        },
        inventory={
            "machines": {"mill": {"kind": "mill", "resolution_mm": fact(0.005)}},
            "holders": {"collet": {"kind": "collet", "name": "Test collet"}},
            "tools": tools
            if tools is not None
            else {"cutter": {"kind": "endmill", "name": "Test cutter", "dia_mm": 6.35}},
        },
        features={
            "units": "mm",
            "frames": {"F": deepcopy(FRAME)},
            "features": {
                "deck": {"kind": "face", "requirements": []},
                "hole": {"kind": "hole", "thru": True, "requirements": []},
            },
        },
        policy={},
        cutting_data={},
        paths={},
        hashes={},
        root=Path("."),
        kernel={"status": "ok", "ops": {}},
    )


def finding(rule, subject, numbers, status="unknown"):
    return Finding(rule, subject, status, numbers, [], "Synthetic finding.")


def qualifiers():
    assumed = fact(8.0, "assumed")
    illustrative = fact(8.0, "illustrative")
    legacy = fact(8.0)
    legacy["measured"].pop("status")
    incomplete = fact(8.0)
    incomplete["measured"].pop("instrument")
    return [
        pytest.param(fact(8.0), False, id="complete-measured-despite-example-prose"),
        pytest.param({**fact(8.0), "verify": False}, False, id="measured-verify-false"),
        pytest.param(assumed, True, id="assumed"),
        pytest.param(illustrative, True, id="illustrative"),
        pytest.param(legacy, True, id="omitted-status"),
        pytest.param(incomplete, True, id="incomplete-measured"),
        pytest.param({**fact(8.0), "verify": True}, True, id="verify-true"),
        pytest.param({**fact(8.0), "verify": "unknown"}, True, id="verify-unknown"),
    ]


@pytest.mark.parametrize(
    ("field", "label"),
    [
        ("dia", "Ø8.000"),
        ("reach", "max plunge depth 8.000"),
        ("nose_radius", "nose R8.000"),
        ("shank", "shank Ø8.000"),
        ("flute_len", "flute 8.000"),
        ("projection", "projection 8.000 from holder face"),
        ("blade_width", "blade width 8.000"),
    ],
)
@pytest.mark.parametrize(("record", "untrusted"), qualifiers())
def test_tools_marks_only_the_refused_dimension_with_its_record_and_action(
    field, label, record, untrusted
):
    tool = {"kind": "endmill", "name": "Test cutter", "dia_mm": 6.35, "material": "HSS"}
    if field == "projection":
        tool["projection_mm"] = {"collet": deepcopy(record)}
        consumed = ("projection", "collet")
    else:
        tool[field + "_mm"] = deepcopy(record)
        consumed = field
    bundle = data(tools={"cutter": tool})
    setup = bundle.plan["setups"][0]
    setup["ops"][0]["holder"] = "holders.collet"
    sheet = _Traveler(bundle, [], {}, None)
    _, _, html = sheet.tool_table(setup)
    markup = Markup(html)
    marked = markup.find("unverified")
    # Trusted blade width stays in the blade's existing short name, not an extra field.
    if field == "blade_width" and not untrusted:
        assert not marked
        return
    assert label in content(next(node for node in markup.nodes if node["tag"] == "table"))
    assert len(marked) == int(untrusted)
    if untrusted:
        entry = length_debt(
            tool, consumed, "tools", "cutter", require_measured=field == "projection"
        )
        assert label in content(marked[0])
        assert marker_for(sheet, entry) in content(marked[0])
        assert entry["id"] not in content(marked[0])
        assert "measure:" not in content(marked[0])
        summary = Markup(sheet.setup_status_boxes([], [], []))
        assert full_action(sheet, entry) in content(actions(summary)[entry["id"]])
        assert content(marked[0]) == f"{label} {marker_for(sheet, entry)}"
        assert content(summary.find("stop")[0]).count("?M# marks an unverified input") == 1
        assert "HSS" not in content(marked[0])
        if field != "dia":
            assert "Ø6.350" not in content(marked[0])
    else:
        assert "Not verified" not in content(next(n for n in markup.nodes if n["tag"] == "table"))


def test_tools_retains_unrelated_bare_nominals_but_marks_unmeasured_installed_projection():
    bundle = data()
    tool = bundle.inventory["tools"]["cutter"]
    tool.update({"verify": True, "projection_mm": {"collet": 28.0}, "flute_len_mm": 20.0})
    setup = bundle.plan["setups"][0]
    setup["ops"][0]["holder"] = "collet"
    sheet = _Traveler(bundle, [], {}, None)
    _, _, html = sheet.tool_table(setup)
    (marked,) = Markup(html).find("unverified")
    assert marker_for(
        sheet, length_debt(tool, ("projection", "collet"), "tools", "cutter", require_measured=True)
    ) in content(marked)
    assert "projection 28.000" in content(marked)
    assert "Ø6.350" not in content(marked) and "flute 20.000" not in content(marked)


def test_parting_blade_name_never_repeats_a_refused_width_as_a_certain_size():
    bundle = data(
        tools={"cutter": {"kind": "parting_blade", "blade_width_mm": fact(1.6, "assumed")}}
    )
    _, _, html = _Traveler(bundle, [], {}, None).tool_table(bundle.plan["setups"][0])
    markup = Markup(html)
    (marked,) = markup.find("unverified")
    assert "blade width 1.600" in content(marked)
    assert "?M1" in content(marked) and "tools.cutter.blade_width" not in content(marked)
    assert "1.6 mm parting blade" not in content(
        next(n for n in markup.nodes if n["tag"] == "table")
    )


def test_a_trusted_nominal_parting_blade_keeps_its_existing_size_name():
    bundle = data(tools={"cutter": {"kind": "parting_blade", "blade_width_mm": 1.6}})
    sheet = _Traveler(bundle, [], {}, None)
    _, _, html = sheet.tool_table(bundle.plan["setups"][0])
    assert sheet.tool_name("cutter") == "1.6 mm parting blade"
    assert not Markup(html).find("unverified")


def stopped_setup():
    ops = [
        {"op": n, "do": "face", "feature": "deck", "tool": "cutter", "to_z": 8.0} for n in (10, 20)
    ] + [
        {"op": 30, "do": "drill", "feature": "hole", "tool": "drill"},
        {"op": 40, "do": "ream", "feature": "hole", "tool": "reamer"},
        {"op": 50, "do": "drill", "feature": "hole", "tool": "other"},
    ]
    tools = {
        "cutter": {"kind": "endmill", "name": "Test cutter", "dia_mm": fact(6.35, "assumed")},
        "drill": {
            "kind": "drill",
            "name": "Test drill",
            "dia_mm": 6.0,
            "point_angle": fact(118.0, "assumed"),
        },
        "reamer": {
            "kind": "reamer",
            "name": "Test reamer",
            "dia_mm": 6.5,
            "lead_mm": fact(1.5, "assumed"),
        },
        "other": {"kind": "drill", "name": "Other drill", "dia_mm": 4.0, "point_angle": 118.0},
    }
    bundle = data(ops, tools)
    cutter = length_debt(tools["cutter"], "dia", "tools", "cutter")
    lead = length_debt(tools["reamer"], "lead", "tools", "reamer")
    unconsumed = length_debt({"length_mm": fact(40.0, "assumed")}, "length", "fixtures", "unused")
    profiles = [
        {
            "op": n,
            "cutter_centre": "unknown",
            "measurements": [cutter],
            "raster_reason": "cutter radius unknown",
        }
        for n in (10, 20)
    ]
    findings = [
        finding("coordinates", "S1", {"profiles": profiles, "measurements": [cutter, unconsumed]}),
        finding(
            "blind_depth",
            "hole",
            {
                "measurements": [lead],
                "endpoints": [
                    {
                        "setup": "S1",
                        "op": 30,
                        "dro_entry_z": 10.0,
                        "exit_face": 0.0,
                        "dro_exit_face": 0.0,
                        "point_mm": "unknown",
                        "tip_z": "unknown",
                        "dro_tip_z": "unknown",
                    },
                    {
                        "setup": "S1",
                        "op": 40,
                        "dro_entry_z": 10.0,
                        "exit_face": 0.0,
                        "dro_exit_face": 0.0,
                        "lead_mm": "unknown",
                        "tip_z": "unknown",
                        "dro_tip_z": "unknown",
                    },
                    {
                        "setup": "S1",
                        "op": 50,
                        "dro_entry_z": 10.0,
                        "exit_face": 0.0,
                        "dro_exit_face": 0.0,
                        "point_mm": 1.0,
                        "tip_z": -1.5,
                        "dro_tip_z": -1.5,
                        "dro_exit_mm": 0.5,
                    },
                ],
            },
        ),
        *[
            finding(
                "speeds_feeds",
                f"S1:{n}",
                {"rpm": "unknown", "feed_mm_min": "unknown", "measurements": [cutter]},
            )
            for n in (10, 20)
        ],
        *[
            finding("speeds_feeds", f"S1:{n}", {"rpm": 500.0, "feed_mm_min": 25.0}, "pass")
            for n in (30, 40, 50)
        ],
    ]
    return bundle, findings, cutter, lead


def test_setup_stop_summary_covers_contour_cutter_and_depth_debt_once_per_consumed_input():
    bundle, findings, cutter, lead = stopped_setup()
    original = deepcopy([f.to_dict() for f in findings])
    sheet = _Traveler(bundle, findings, {}, None)
    pages = sheet.setup_section(bundle.plan["setups"][0])
    markup = Markup("".join(block for page in pages for block in page))
    summary = markup.find("stop")[0]
    entries = actions(markup)
    assert set(entries) == {
        cutter["id"],
        lead["id"],
        "tools.drill.point_angle",
    }
    for _, entry in sheet.measurement_registry().values():
        instruction = full_action(sheet, entry)
        assert content(summary).count(instruction) == 1
        assert sum(content(node).count("measure:") for node in entries.values()) == len(entries)
        assert "Record measured value here [____]" not in content(entries[entry["id"]])
        assert entry["id"] not in content(summary)
    assert "Ops 10, 20" in content(summary) and "T1" in content(summary)
    assert "Test cutter" in content(summary)
    assert content(summary).count("?M# marks an unverified input") == 1
    assert "assumed value, not physically measured" not in content(summary)
    assert "synthetic example, not a physical shop measurement" not in content(summary)
    assert "by:" not in content(summary)
    assert "T3" in content(summary) and "Test reamer" in content(summary)
    assert "T2" in content(summary) and "Test drill" in content(summary)
    point_action = content(entries["tools.drill.point_angle"])
    assert "included drill point angle, drill point gauge or protractor, degrees" in point_action
    rows = {node["attrs"]["data-op"]: node for node in markup.find("operation")}
    drill, reamer = content(rows["30"]), content(rows["40"])
    point = sheet.measurement_registry()["tools.drill.point_angle"][0]
    assert "drill point length unknown" in drill and f"?{point}" in drill
    assert marker_for(sheet, lead) not in drill
    assert "reamer chamfer / lead length unknown" in reamer and marker_for(sheet, lead) in reamer
    assert "drill point length unknown" not in reamer
    assert "return this traveler for reissue" in content(summary)
    assert "Measurements do not clear planned speeds, depths, contours or clearance" in content(
        summary
    )
    defined = {node["attrs"]["data-measurement-label"] for node in entries.values()}
    references = {node["attrs"]["data-measurement-ref"] for node in markup.find("measurement-ref")}
    assert references == defined
    assert [f.to_dict() for f in findings] == original


def test_depth_stop_still_routes_when_speed_feed_is_already_known():
    bundle, findings, _, lead = stopped_setup()
    setup = bundle.plan["setups"][0]
    setup["ops"] = [setup["ops"][3]]
    findings = [f for f in findings if f.rule == "blind_depth" or f.subject == "S1:40"]
    sheet = _Traveler(bundle, findings, {}, None)
    pages = sheet.setup_section(setup)
    summary = content(Markup("".join(pages[0])).find("stop")[0])
    assert "Op 40" in summary and "T1" in summary and "Test reamer" in summary
    assert lead["id"] in actions(Markup("".join(pages[0])))
    assert full_action(sheet, lead) in summary
    assert "no starting speed / feed" not in summary


@pytest.mark.parametrize("source", ["speeds_feeds", "coordinates"])
def test_each_speed_or_contour_stop_independently_names_its_consumed_field_and_action(source):
    bundle, findings, cutter, _ = stopped_setup()
    setup = bundle.plan["setups"][0]
    setup["ops"] = setup["ops"][:2]
    findings = [f for f in findings if f.rule == source]
    if source == "coordinates":
        findings.extend(
            finding("speeds_feeds", f"S1:{n}", {"rpm": 500.0, "feed_mm_min": 25.0}, "pass")
            for n in (10, 20)
        )
    sheet = _Traveler(bundle, findings, {}, None)
    pages = sheet.setup_section(setup)
    summary = content(Markup("".join(pages[0])).find("stop")[0])
    assert cutter["id"] in actions(Markup("".join(pages[0])))
    assert full_action(sheet, cutter) in summary
    assert "T1" in summary and "Test cutter" in summary
    assert summary.count("?M# marks an unverified input") == 1
    assert "assumed value, not physically measured" not in summary
    assert summary.count(full_action(sheet, cutter)) == 1
    assert "fixtures.unused" not in summary


def test_clearance_uses_compact_fact_references_and_full_kind_aware_actions_only_in_summary():
    bundle = data()
    setup = bundle.plan["setups"][0]
    setup["hold"] = {"fixture": "riser"}
    setup["ops"][0]["holder"] = "collet"
    bundle.inventory["fixtures"] = {
        "riser": {
            "kind": "custom",
            "name": "Test riser",
            "bed_height_mm": fact(18.5, "assumed"),
            "length_mm": fact(120.0, "assumed"),
        }
    }
    tool = bundle.inventory["tools"]["cutter"]
    tool["oal_mm"] = fact(60.0, "assumed")
    tool["projection_mm"] = {"collet": fact(28.0, "assumed")}
    bundle.inventory["holders"]["collet"]["gauge_len_mm"] = fact(30.0, "assumed")
    entries = [
        length_debt(bundle.inventory[category][key], field, category, key)
        for category, key, field in (
            ("fixtures", "riser", "bed_height"),
            ("fixtures", "riser", "length"),
            ("holders", "collet", "gauge_len"),
            ("tools", "cutter", "oal"),
            ("tools", "cutter", ("projection", "collet")),
        )
    ]
    numbers = {
        "bed_height_mm": "unknown",
        "sum_mm": "unknown",
        "stacks": [{"op": 10, "tool": "cutter", "margin_mm": "unknown"}],
        "measurements": [*entries, entries[0]],
    }
    sheet = _Traveler(bundle, [finding("headroom", "S1", numbers)], {}, None)
    before = deepcopy(numbers)
    tool_numbers, _, _ = sheet.tool_table(setup)
    text = "".join(node for node in Markup(sheet.clearance(setup, tool_numbers)).nodes[0]["text"])
    assert "measure:" not in text
    assert "Authored fixture coordinates are setup settings, not verified clearance" in text
    for entry in entries:
        assert marker_for(sheet, entry) in text and entry["id"] not in text
    assert text.count("Test riser") == 1
    assert (
        f"Test riser work-support height {marker_for(sheet, entries[0])}; "
        f"length {marker_for(sheet, entries[1])}"
    ) in text
    summary = Markup(sheet.setup_status_boxes([], [], []))
    for entry in entries:
        assert content(summary.find("stop")[0]).count(full_action(sheet, entry)) == 1
    riser = content(actions(summary)[entries[0]["id"]])
    assert "Test riser" in content(summary.find("stop")[0])
    assert "Test riser" not in riser and "work-support contact surface" in riser
    assert "vise" not in riser and "parallels" not in riser and "jaws" not in riser
    assert numbers == before


def test_dro_header_has_one_inline_hedge_no_orphan_mark_and_preserves_other_rounding():
    bundle = data(ops=[])
    bundle.inventory["machines"]["mill"]["resolution_mm"] = fact(0.005, "assumed")
    setup = bundle.plan["setups"][0]
    sheet = _Traveler(
        bundle,
        [
            finding(
                "coordinates",
                "S1",
                {"dro_grid": {"step": "not used", "decimals": "not used"}},
                "not_applicable",
            )
        ],
        {},
        None,
    )
    markup = Markup(sheet.header([setup]))
    (resolution,) = [
        content(node)
        for node in markup.nodes
        if node["tag"] == "p" and content(node).startswith("DRO resolution:")
    ]
    assert "0.005 mm" in resolution and "grid not verified" in resolution
    assert "test installed readout step" in resolution and "see setup STOPs" in resolution
    assert "assumed" not in resolution
    assert resolution.count("not verified") == 1
    assert "†" not in resolution
    assert "no coordinate targets" in resolution and "grid: not used" not in resolution
    assert "DRO targets print on this grid" not in resolution
    # Coordinates did not consume this grid; another printed setting still rounds on it.
    assert sheet.surface_z(setup, 7.497) == 7.5


def test_a_grid_rounded_depth_stop_names_only_the_consumed_resolution_debt():
    bundle = data(
        ops=[{"op": 10, "do": "drill", "feature": "hole", "tool": "cutter", "depth_mm": 2.003}]
    )
    bundle.inventory["machines"]["mill"]["resolution_mm"] = fact(0.005, "assumed")
    endpoint = {
        "setup": "S1",
        "op": 10,
        "depth_mm": 2.003,
        "dro_depth_mm": 2.0,
        "depth_floor_mm": "unknown",
        "dro_entry_z": 10.0,
        "exit_face": "not_applicable",
        "point_mm": 1.0,
        "tip_z": 7.997,
        "dro_tip_z": 8.0,
        "dro_grid_debt": "Synthetic untrusted declared grid.",
    }
    findings = [
        finding("blind_depth", "hole", {"endpoints": [endpoint]}),
        finding("speeds_feeds", "S1:10", {"rpm": 500.0, "feed_mm_min": 25.0}, "pass"),
    ]
    sheet = _Traveler(bundle, findings, {}, None)
    pages = sheet.setup_section(bundle.plan["setups"][0])
    front = Markup("".join(pages[0]))
    summary = content(front.find("stop")[0])
    assert "machines.mill.resolution" in actions(front)
    assert "test" in summary and "T1" not in content(actions(front)["machines.mill.resolution"])
    assert "installed DRO least readable step, installed readout and indicator check, mm" in summary
    assert summary.count("?M# marks an unverified input") == 1
    assert "assumed value, not physically measured" not in summary
    assert "DRO depth rounded; feature depth band unknown" in summary
    assert "tools.cutter.dia" not in summary


def test_a_refused_tool_nose_offset_stop_names_the_cutter_radius_record_and_action():
    bundle = data(
        tools={
            "cutter": {
                "kind": "lathe_tool_bit",
                "name": "Test profiling tool",
                "hand": "right",
                "nose_radius_mm": fact(0.8, "assumed"),
            }
        }
    )
    bundle.inventory["machines"]["mill"]["kind"] = "lathe"
    setup = bundle.plan["setups"][0]
    contour = {"op": 10, "method": "axial_table", "tool_nose_compensation_mm": "unknown"}
    findings = [
        finding("coordinates", "S1", {"contours": [contour]}),
        finding("speeds_feeds", "S1:10", {"rpm": 500.0, "feed_mm_rev": 0.05}, "pass"),
    ]
    sheet = _Traveler(bundle, findings, {}, None)
    numbers, _, _ = sheet.tool_table(setup)
    html, _, _, stops = sheet.operations(setup, numbers, {"notes": 2, "contours": 3})
    debt = length_debt(bundle.inventory["tools"]["cutter"], "nose_radius", "tools", "cutter")
    named = [text for text in stops if "tool-nose offset not computed" in text]
    assert len(named) == 1 and stops[named[0]] == ["10"]
    assert "T1" in named[0] and "Test profiling tool" in named[0]
    assert marker_for(sheet, debt) in named[0]
    assert "measure:" not in named[0]
    assert marker_for(sheet, debt) in content(Markup(html).find("operation")[0])


@pytest.mark.parametrize("resolution", [None, "unknown"])
def test_coordinate_nonconsumer_with_no_declared_grid_does_not_print_a_fallback(resolution):
    bundle = data(ops=[])
    machine = bundle.inventory["machines"]["mill"]
    if resolution is None:
        machine.pop("resolution_mm")
    else:
        machine["resolution_mm"] = resolution
    sheet = _Traveler(
        bundle,
        [
            finding(
                "coordinates",
                "S1",
                {"dro_grid": {"step": "not used", "decimals": "not used"}},
                "not_applicable",
            )
        ],
        {},
        None,
    )
    shown = sheet.dro_resolution(bundle.plan["setups"])
    assert "no coordinate targets" in shown
    assert "0.001" not in shown and "default" not in shown and "provisional" not in shown
    assert "not verified" not in shown and "†" not in shown


@pytest.mark.parametrize("kind", ["endmill", "drill", "reamer"])
@pytest.mark.parametrize(("record", "untrusted"), qualifiers())
def test_tool_identity_does_not_repeat_a_refused_diameter_as_a_certain_size(
    kind, record, untrusted
):
    tool = {"kind": kind, "name": "Catalogue cutter", "dia_mm": deepcopy(record)}
    bundle = data(tools={"cutter": tool})
    sheet = _Traveler(bundle, [], {}, None)
    _, _, html = sheet.tool_table(bundle.plan["setups"][0])
    markup = Markup(html)
    cells = [node for node in markup.nodes if node["tag"] == "td"]
    name = content(cells[1])
    assert name == ("Catalogue cutter" if untrusted else "8 mm Catalogue cutter")
    assert sheet.tool_name("cutter") == name
    if untrusted:
        (marked,) = markup.find("unverified")
        entry = length_debt(tool, "dia", "tools", "cutter")
        assert "Ø8.000" in content(marked) and marker_for(sheet, entry) in content(marked)
        assert "measure:" not in content(marked) and entry["id"] not in content(marked)
    else:
        assert not markup.find("unverified")


def test_refused_member_diameter_keeps_the_authored_catalogue_member_name():
    member = "Catalogue 3/8 in cutter"
    bundle = data(
        ops=[
            {
                "op": 10,
                "do": "face",
                "feature": "deck",
                "tool": "cutter/3-8in",
                "to_z": 8.0,
            }
        ],
        tools={
            "cutter": {
                "kind": "endmill_set",
                "members": {
                    "3-8in": {"name": member, "dia_mm": fact(9.525, "assumed"), "flutes": 4}
                },
            }
        },
    )
    sheet = _Traveler(bundle, [], {}, None)
    _, _, html = sheet.tool_table(bundle.plan["setups"][0])
    markup = Markup(html)
    cells = [node for node in markup.nodes if node["tag"] == "td"]
    assert content(cells[1]) == member
    (marked,) = markup.find("unverified")
    assert "Ø9.525" in content(marked) and "?M1" in content(marked)
    assert "tools.cutter/3-8in.dia" not in content(marked)


@pytest.mark.parametrize("kind", ["endmill", "drill", "reamer"])
def test_bare_nominal_tool_diameter_keeps_its_existing_identity_prefix(kind):
    bundle = data(tools={"cutter": {"kind": kind, "name": "Catalogue cutter", "dia_mm": 8.0}})
    sheet = _Traveler(bundle, [], {}, None)
    _, _, html = sheet.tool_table(bundle.plan["setups"][0])
    markup = Markup(html)
    cells = [node for node in markup.nodes if node["tag"] == "td"]
    assert content(cells[1]) == "8 mm Catalogue cutter"
    assert not markup.find("unverified")


@pytest.mark.parametrize(
    "extra",
    [
        "STOP: no tool",
        "STOP: spindle direction not known — the tool's hand is not declared",
        "STOP: plunge feed not set — cutter is not proven centre-cutting",
        "STOP: X endpoint diameter not set",
        "STOP: the follow rest's jaw side or lead is not known",
        "STOP: START Z 12.000 is not checked clear of the rest",
        "STOP: PATH ENDS 0.500 INSIDE JAWS (Z 2.000)",
        "TIP 0.500 BELOW JAW TOP — STOP",
        "STOP: manual arc not proven",
        "Bench filing; STOP: filing stock limit not established",
    ],
)
def test_setup_semantic_stop_union_is_the_union_of_actual_operation_rows(monkeypatch, extra):
    bundle, findings, _, _ = stopped_setup()
    sheet = _Traveler(bundle, findings, {}, None)
    monkeypatch.setattr(sheet, "crash_boxes", lambda setup, op: [_Box(extra)])
    # A full-width plain manual/action clause is also a STOP producer, not just _Box.
    monkeypatch.setattr(
        sheet,
        "rest_steps",
        lambda setup, op: ([], [_Plain("Pass sequence; STOP: rest return not checked")]),
    )
    pages = sheet.setup_section(bundle.plan["setups"][0])
    markup = Markup("".join(block for page in pages for block in page))
    summary = markup.find("stop")[0]
    row_union = set()
    for row in markup.find("operation"):
        for node in [*markup.find("box", row), *markup.find("see", row)]:
            text = content(node)
            matches = list(re.finditer(r"\bSTOP\b", text))
            for index, match in enumerate(matches):
                end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
                kind = text[match.end() : end].lstrip(": —").strip().rstrip(".; ")
                if not kind:
                    kind = text[: match.start()].rstrip(" —:").strip()
                row_union.add(kind)
    assert row_union
    # Summary op lines are independently read off the final markup. No debt-text-only
    # shortcut can satisfy this, because rpm, feed and endpoint kinds occur alongside M#.
    summary_lines = [
        re.sub(r"^(?:Ops? [\d, ]+|All ops) — ", "", content(node))
        for node in markup.nodes
        if node["tag"] == "p"
        and node["parent"] is summary
        and re.match(r"^(?:Ops? [\d, ]+|All ops) — ", content(node))
    ]
    summary_union = set()
    for line in summary_lines:
        if re.fullmatch(r"no starting rpm(?: \?M\d+)*; no starting feed(?: \?M\d+)*", line):
            summary_union.update(line.split("; "))
        else:
            summary_union.add(line)
    assert summary_union == row_union
    assert all("return traveler for reissue" not in line for line in summary_lines)
    directive = "Record the measured values here and return this traveler for reissue"
    assert content(summary).count(directive) == 1
    for kind in (
        "no starting rpm",
        "no starting feed",
        "drill point length unknown",
        "reamer chamfer / lead length unknown",
        "contour points not computed",
    ):
        assert any(kind in line for line in summary_union)
    assert all("measure:" not in line for line in row_union)


def test_consumed_bare_shank_has_one_refused_value_while_unconsumed_nominals_stay_plain():
    bundle = data(
        tools={
            "cutter": {
                "kind": "endmill",
                "name": "Catalogue cutter",
                "dia_mm": 8.0,
                "shank_mm": 8.0,
            }
        }
    )
    setup = bundle.plan["setups"][0]
    shank = length_debt(
        bundle.inventory["tools"]["cutter"], "shank", "tools", "cutter", require_measured=True
    )
    bundle.kernel["measurement_debts"] = {
        "setups": {},
        "ops": {
            "S1:10": [shank],
            "S2:10": [length_debt({"oal_mm": fact(50.0, "assumed")}, "oal", "tools", "cutter")],
        },
    }
    sheet = _Traveler(bundle, [], {}, None)
    _, _, html = sheet.tool_table(setup)
    markup = Markup(html)
    (marked,) = markup.find("unverified")
    assert "shank Ø8.000" in content(marked) and marker_for(sheet, shank) in content(marked)
    assert content(markup.find("tools")[0]).count("shank Ø8.000") == 1
    assert "tools.cutter.oal" not in sheet.measurement_registry()
    del bundle.kernel["measurement_debts"]
    _, _, plain = _Traveler(bundle, [], {}, None).tool_table(setup)
    assert not Markup(plain).find("unverified")
    assert "Ø8.000" in content(Markup(plain).find("tools")[0])


def test_refused_diameter_does_not_add_a_competing_plain_same_size_shank():
    bundle = data(
        tools={
            "cutter": {
                "kind": "endmill",
                "name": "Test cutter",
                "dia_mm": fact(8.0, "assumed"),
                "shank_mm": 8.0,
            }
        }
    )
    _, _, html = _Traveler(bundle, [], {}, None).tool_table(bundle.plan["setups"][0])
    markup = Markup(html)
    assert "shank Ø8.000" not in content(markup.find("tools")[0])
    assert "Ø8.000 ?M1" in content(markup.find("unverified")[0])


def test_registry_preserves_dotted_member_and_holder_identities_and_resets_per_setup():
    bundle = data(
        tools={
            "cutters": {
                "kind": "endmill_set",
                "members": {
                    "6.5mm": {
                        "name": "Metric cutter",
                        "dia_mm": fact(6.5, "assumed"),
                        "projection_mm": {"collets/6.5mm": fact(28.0, "assumed")},
                    }
                },
            }
        }
    )
    bundle.inventory["holders"] = {
        "collets": {"kind": "collet_set", "members": {"6.5mm": {"name": "Metric collet"}}}
    }
    first = bundle.plan["setups"][0]
    first["ops"][0].update(tool="cutters/6.5mm", holder="collets/6.5mm")
    second = deepcopy(first)
    second["id"] = "S2"
    bundle.plan["setups"].append(second)
    sheet = _Traveler(bundle, [], {}, None)
    for setup in (first, second):
        _, _, html = sheet.tool_table(setup)
        registry = sheet.measurement_registry(setup)
        projection = registry["tools.cutters/6.5mm.projection.collets/6.5mm"][1]
        assert projection["identity"] == "cutters/6.5mm"
        assert projection["field"] == ["projection", "collets/6.5mm"]
        assert {marker for marker, _ in registry.values()} == {"M1", "M2"}
        assert "cutters/" not in content(Markup(html).find("tools")[0])
        assert "collets/" not in content(Markup(html).find("tools")[0])
    assert sheet._setup_measurements["S1"] is not sheet._setup_measurements["S2"]


def test_late_hold_and_dro_measurements_close_in_the_front_stop_box(monkeypatch):
    bundle = data()
    sheet = _Traveler(bundle, [], {}, None)
    entry = length_debt({"height_mm": fact(12.0, "assumed")}, "height", "fixtures", "block")
    bundle.inventory["fixtures"] = {
        "block": {"kind": "custom", "name": "Support block", "height_mm": fact(12.0, "assumed")}
    }

    def hold(setup):
        return "<p>Support height " + sheet.measurement_marker(entry) + "</p>", ""

    monkeypatch.setattr(sheet, "hold", hold)
    monkeypatch.setattr(
        sheet, "dro", lambda setup, tools: "<p>Readout " + sheet.measurement_marker(entry) + "</p>"
    )
    pages = sheet.setup_section(bundle.plan["setups"][0])
    markup = Markup("".join(pages[0]))
    assert entry["id"] in actions(markup)
    assert (
        len(
            [
                node
                for node in markup.nodes
                if node["attrs"].get("data-measurement-id") == entry["id"]
            ]
        )
        == 1
    )
    assert "Support block" in content(markup.find("stop")[0])
    assert "Support block" not in content(actions(markup)[entry["id"]])
    assert "Make-to-drawing expected settings are not installed measurements" in content(
        markup.find("stop")[0]
    )
    assert all(
        node["attrs"]["data-measurement-ref"] == "M1" for node in markup.find("measurement-ref")
    )


def test_el400_owns_the_installed_readout_step_action_without_changing_printed_grid():
    bundle = data()
    bundle.plan["dro"].update(controller="el400", manual="Electronica EL400 Operation Manual")
    bundle.inventory["machines"]["mill"]["resolution_mm"] = fact(0.005, "assumed")
    entry = length_debt(bundle.inventory["machines"]["mill"], "resolution", "machines", "mill")
    sheet = _Traveler(
        bundle,
        [
            finding(
                "coordinates",
                "S1",
                {"dro_grid": {"step": 0.005, "decimals": 3}, "measurements": [entry]},
            )
        ],
        {},
        None,
    )
    pages = sheet.setup_section(bundle.plan["setups"][0])
    markup = Markup("".join(pages[0]))
    action = actions(markup)["machines.mill.resolution"]
    assert "EL400" in content(markup.find("measurement-actions")[0])
    assert "measure: its installed DRO least readable step" in content(action)
    header = sheet.dro_resolution(bundle.plan["setups"])
    assert "0.005 mm" in header and "EL400 installed readout step" in header
    assert "Setup S1 ?M" in header and "confirm installed readout" not in header
    assert sheet.surface_z(bundle.plan["setups"][0], 7.497) == 7.5
    assert sheet.operative(7.5) == "7.500"


@pytest.mark.parametrize(
    ("field", "dimension"),
    [
        (("envelope", "swing_over_bed"), "swing over bed"),
        (("envelope", "between_centres"), "between centres"),
        (("envelope", "swing_over_cross_slide"), "swing over cross slide"),
    ],
)
def test_compact_dimension_fallback_never_prints_database_field_spelling(field, dimension):
    bundle = data(ops=[])
    bundle.inventory["machines"]["mill"].update(kind="lathe", name="Test lathe")
    sheet = _Traveler(bundle, [], {}, None)
    entry = measurement_entry("machines", "mill", field, status="assumed")
    line = " ".join(sheet.measurement_lines([entry]))
    assert line == f"Test lathe {dimension} ?M1"
    assert "_".join(field) not in line
    summary = Markup(sheet.setup_status_boxes([], [], []))
    assert entry["id"] in actions(summary)
    assert content(summary.find("stop")[0]).count("?M# marks an unverified input") == 1
    assert full_action(sheet, entry) in content(actions(summary)[entry["id"]])


def test_measurement_actions_group_actual_records_without_changing_the_canonical_m_map():
    bundle = data()
    bundle.plan["dro"].update(controller="el400", manual="Electronica EL400 Operation Manual")
    bundle.inventory["machines"]["mill"]["name"] = "Shop mill"
    bundle.inventory["holders"]["second"] = {"kind": "collet", "name": "Second collet"}
    # Identical paper names must not collapse distinct inventory records.
    bundle.inventory["tools"]["other"] = deepcopy(bundle.inventory["tools"]["cutter"])
    sheet = _Traveler(bundle, [], {}, None)
    sheet.measurement_registry(bundle.plan["setups"][0])
    specs = [
        ("tools", "cutter", ("dia",)),
        ("tools", "other", ("dia",)),
        ("tools", "cutter", ("shank",)),
        ("tools", "cutter", ("projection", "collet")),
        ("tools", "cutter", ("projection", "second")),
        ("machines", "mill", ("envelope", "travel", "x")),
        ("machines", "mill", ("resolution",)),
    ]
    for category, key, field in specs:
        sheet.measurement_marker(measurement_entry(category, key, field))
    expected = deepcopy(sheet.measurement_registry())
    markup = Markup(sheet.setup_status_boxes([], [], []))
    groups = markup.find("measurement-actions")
    assert len(groups) == 4
    ids = [
        node["attrs"]["data-measurement-id"]
        for node in markup.nodes
        if "data-measurement-id" in node["attrs"]
    ]
    assert sorted(ids) == sorted(expected) and len(ids) == len(set(ids))
    assert sheet.measurement_registry() == expected
    for canonical, (marker, entry) in expected.items():
        row = actions(markup)[canonical]
        assert row["tag"] == "tr"
        assert row["attrs"]["data-measurement-label"] == marker
        assert content(row).count(full_action(sheet, entry)) == 1
        assert content(row).count(f"{marker} —") == 1
        assert len(markup.find("writing-blank", within=row)) == 1
        assert canonical not in content(markup.find("stop")[0])
    assert content(groups[0]).count("Test cutter") == 1
    assert "M1 —" in content(groups[0]) and "M3 —" in content(groups[0])
    assert "M2 —" in content(groups[1]) and "M1 —" not in content(groups[1])
    for canonical, holder in (
        ("tools.cutter.projection.collet", "Test collet"),
        ("tools.cutter.projection.second", "Second collet"),
    ):
        row = actions(markup)[canonical]
        assert row["parent"]["parent"] is groups[0]
        assert content(row).count(f"in {holder}: measure: its holder face to mounted tool tip") == 1
        assert "Test cutter" not in content(row)
    assert "Shop mill" in content(groups[2]) and "EL400" not in content(groups[2])
    assert "EL400" in content(groups[3]) and "Shop mill" not in content(groups[3])
    assert len(markup.find("writing-blank")) == len(expected)
    assert [content(node) for node in markup.find("field-label")] == ["mm"] * len(expected)
    text = content(markup.find("stop")[0])
    assert "Record measured value here" not in text and "[____]" not in text
    assert text.count("Record the measured values here and return this traveler for reissue") == 1
    short_sheet = _Traveler(bundle, [], {}, None)
    short_sheet.measurement_registry(bundle.plan["setups"][0])
    entries = [entry for _, entry in expected.values()]
    lines = short_sheet.measurement_lines([*entries, entries[0]])
    assert len(lines) == 6
    assert short_sheet.measurement_registry() == expected
    assert lines[0] == sheet.measurement_subject(entries[0]) + " cutter Ø ?M1; shank Ø ?M3"
    assert lines[1] == sheet.measurement_subject(entries[1]) + " cutter Ø ?M2"
    assert lines[2] == sheet.measurement_subject(entries[3]) + " installed projection ?M4"
    assert lines[3] == sheet.measurement_subject(entries[4]) + " installed projection ?M5"
    assert lines[4] == "Shop mill X usable travel ?M6"
    assert lines[5] == "EL400 readout step ?M7"
    assert sorted(re.findall(r"\?M\d+\b", " ".join(lines))) == [
        f"?M{index}" for index in range(1, 8)
    ]
    assert all(entry["id"] not in " ".join(lines) for entry in entries)


@pytest.mark.parametrize(
    ("stops", "expected"),
    [
        (
            {"no starting rpm ?M1 ?M2": ["10", "20"], "no starting feed ?M1 ?M2": ["20", "10"]},
            ["no starting rpm ?M1 ?M2; no starting feed ?M1 ?M2"],
        ),
        (
            {"no starting feed": ["10"], "no starting rpm": ["10"]},
            ["no starting rpm; no starting feed"],
        ),
        (
            {"no starting rpm ?M1": ["10"], "no starting feed ?M2": ["10"]},
            ["no starting rpm ?M1", "no starting feed ?M2"],
        ),
        (
            {"no starting rpm ?M1": ["10"], "no starting feed ?M1": ["20"]},
            ["no starting rpm ?M1", "no starting feed ?M1"],
        ),
        (
            {
                "no starting rpm ?M1 — obtain approved cutting data": ["10"],
                "no starting feed ?M1": ["10"],
            },
            ["no starting rpm ?M1 — obtain approved cutting data", "no starting feed ?M1"],
        ),
    ],
)
def test_compact_operation_stops_require_identical_scope_and_refs(stops, expected):
    original = deepcopy(stops)
    compact = list(_Traveler.compact_operation_stops(stops))
    assert [text for text, _ in compact] == expected
    assert stops == original
    if len(compact) == len(stops):
        assert compact == list(stops.items())
    else:
        assert set(compact[0][1]) == set(next(iter(stops.values())))
