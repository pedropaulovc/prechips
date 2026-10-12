"""Fact-local traveler debt, using only isolated host data and existing sheet seams.

No examples, frozen shop inputs, native geometry preparation or subprocesses are used.
"""

from copy import deepcopy
from pathlib import Path

import pytest
from test_sheet_ops import Markup, content

from prechips.findings import Finding
from prechips.inputs import Bundle
from prechips.measurements import length_debt, measurement_entry
from prechips.sheet import _Traveler

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
        assert entry["id"] in content(marked[0])
        assert entry["instruction"] in content(marked[0])
        assert "Not verified" in content(marked[0])
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
    _, _, html = _Traveler(bundle, [], {}, None).tool_table(setup)
    (marked,) = Markup(html).find("unverified")
    assert "tools.cutter.projection.collet" in content(marked)
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
    assert "tools.cutter.blade_width" in content(marked)
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
    front = Markup("".join(pages[0]))
    summary = content(front.find("stop")[0])
    assert summary.count(cutter["id"]) == 1
    assert "Ops 10, 20" in summary and "T1" in summary and "Test cutter" in summary
    assert cutter["instruction"] in summary
    assert "assumed value, not physically measured" in summary
    assert summary.count(lead["id"]) == 1
    assert "Op 40" in summary and "T3" in summary and "Test reamer" in summary
    assert lead["instruction"] in summary
    assert "tools.drill.point_angle" in summary and "T2" in summary and "Test drill" in summary
    assert "included drill point angle, protractor, degrees" in summary
    assert "fixtures.unused.length" not in summary
    assert "tools.other" not in summary
    operation_rows = {node["attrs"]["data-op"]: node for node in front.find("operation")}
    drill = content(operation_rows["30"])
    reamer = content(operation_rows["40"])
    assert "drill point length unknown" in drill and "tools.drill.point_angle" in drill
    assert lead["id"] not in drill
    assert "reamer chamfer / lead length unknown" in reamer and lead["id"] in reamer
    assert "drill point length unknown" not in reamer
    attached = "".join(block for page in pages[1:] for block in page)
    contour_stops = [content(node) for node in Markup(attached).find("stop")]
    assert contour_stops and all(cutter["id"] in stop for stop in contour_stops)
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
    assert lead["id"] in summary and lead["instruction"] in summary
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
    assert cutter["id"] in summary and cutter["instruction"] in summary
    assert "T1" in summary and "Test cutter" in summary
    assert "assumed value, not physically measured" in summary
    assert summary.count(cutter["id"]) == 1
    assert "fixtures.unused" not in summary


def test_clearance_names_exact_headroom_debt_and_groups_repeated_actions_without_new_inputs():
    bundle = data()
    entries = [
        length_debt({field + "_mm": fact(value, "assumed")}, field, category, key)
        for category, key, field, value in (
            ("fixtures", "riser", "bed_height", 18.5),
            ("fixtures", "riser", "length", 120.0),
            ("holders", "collet", "gauge_len", 30.0),
            ("tools", "cutter", "oal", 60.0),
            ("tools", "other", "oal", 50.0),
        )
    ]
    projection = length_debt(
        {"projection_mm": {"collet": fact(28.0, "assumed")}},
        ("projection", "collet"),
        "tools",
        "cutter",
    )
    limit = measurement_entry("machines", "mill", "envelope.spindle_to_table_max", status="assumed")
    entries += [projection, limit, entries[0]]
    numbers = {
        "bed_height_mm": "unknown",
        "fixture_height_mm": 18.5,
        "sum_mm": "unknown",
        "spindle_to_table_max_mm": 400.0,
        "stacks": [{"op": 10, "tool": "cutter", "sum_mm": "unknown", "margin_mm": "unknown"}],
        "measurements": entries,
    }
    sheet = _Traveler(bundle, [finding("headroom", "S1", numbers)], {}, None)
    setup = bundle.plan["setups"][0]
    before = deepcopy(numbers)
    html = sheet.clearance(setup, sheet.tool_table(setup)[0])
    text = content(next(n for n in Markup(html).nodes if n["tag"] == "div"))
    assert "holding height not known" not in text
    for entry in {e["id"]: e for e in entries}.values():
        assert text.count(entry["id"]) == 1
    assert (
        "measure: riser table to vise bed supporting the parallels or part, height gauge, mm"
        in text
    )
    assert (
        "measure: collet spindle nose to mounted holder exit face, steel rule or height gauge, mm"
        in text
    )
    assert "measure: cutter, other selected tool overall length, steel rule or calipers, mm" in text
    assert projection["instruction"] in text and limit["instruction"] in text
    assert "Authored fixture coordinates are setup settings, not verified clearance" in text
    assert "fixtures.unused" not in text
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
    assert "confirm installed readout step before use" in resolution
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
    assert "machines.mill.resolution" in summary and "T1" in summary and "Test cutter" in summary
    assert "installed DRO least readable step, installed readout and indicator check, mm" in summary
    assert "assumed value, not physically measured" in summary
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
    named = [text for text in stops if debt["id"] in text]
    assert len(named) == 1 and stops[named[0]] == ["10"]
    assert "T1" in named[0] and "Test profiling tool" in named[0]
    assert debt["instruction"] in named[0]
    assert debt["id"] in content(Markup(html).find("operation")[0])


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
        assert "Ø8.000" in content(marked) and "tools.cutter.dia" in content(marked)
        assert measurement_entry("tools", "cutter", "dia")["instruction"] in content(marked)
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
    assert "Ø9.525" in content(marked) and "tools.cutter/3-8in.dia" in content(marked)


@pytest.mark.parametrize("kind", ["endmill", "drill", "reamer"])
def test_bare_nominal_tool_diameter_keeps_its_existing_identity_prefix(kind):
    bundle = data(tools={"cutter": {"kind": kind, "name": "Catalogue cutter", "dia_mm": 8.0}})
    sheet = _Traveler(bundle, [], {}, None)
    _, _, html = sheet.tool_table(bundle.plan["setups"][0])
    markup = Markup(html)
    cells = [node for node in markup.nodes if node["tag"] == "td"]
    assert content(cells[1]) == "8 mm Catalogue cutter"
    assert not markup.find("unverified")
