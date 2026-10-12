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
    return sheet.measurement_action(entry)["instruction"]


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
    entry = length_debt(tool, consumed, "tools", "cutter", require_measured=field == "projection")
    consumers = [finding("reach", "S1:10", {"measurements": [entry]})] if entry else []
    sheet = _Traveler(bundle, consumers, {}, None)
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
        summary = Markup(sheet.job_measurement_box())
        assert full_action(sheet, entry) in content(actions(summary)[entry["id"]])
        assert content(marked[0]) == f"{label} {marker_for(sheet, entry)}"
        assert content(summary.find("stop")[0]).count("?M# marks an unverified decision input") == 1
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
    entry = length_debt(tool, ("projection", "collet"), "tools", "cutter", require_measured=True)
    sheet = _Traveler(bundle, [finding("reach", "S1:10", {"measurements": [entry]})], {}, None)
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
    entry = length_debt(bundle.inventory["tools"]["cutter"], "blade_width", "tools", "cutter")
    sheet = _Traveler(bundle, [finding("reach", "S1:10", {"measurements": [entry]})], {}, None)
    _, _, html = sheet.tool_table(bundle.plan["setups"][0])
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
    register = Markup(sheet.job_measurement_box())
    entries = actions(register)
    assert set(entries) == {
        cutter["id"],
        lead["id"],
        "tools.drill.point_angle",
    }
    for _, entry in sheet.measurement_registry().values():
        instruction = full_action(sheet, entry)
        assert content(register.find("measurement-stop")[0]).count(instruction) == 1
        assert sum(content(node).count("measure:") for node in entries.values()) == len(entries)
        assert "Record measured value here [____]" not in content(entries[entry["id"]])
        assert entry["id"] not in content(summary)
    assert "Ops 10, 20" in content(summary) and "T1" in content(summary)
    assert "Test cutter" in content(summary)
    assert (
        content(register.find("measurement-stop")[0]).count(
            "?M# marks an unverified decision input"
        )
        == 1
    )
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
    assert "Measurement alone does not clear the STOP decisions named on the setup" in content(
        register.find("measurement-stop")[0]
    )
    assert not actions(markup)
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
    register = Markup(sheet.job_measurement_box())
    assert lead["id"] in actions(register)
    assert full_action(sheet, lead) in content(register.find("measurement-stop")[0])
    assert not actions(Markup("".join(pages[0])))
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
    register = Markup(sheet.job_measurement_box())
    assert cutter["id"] in actions(register)
    assert full_action(sheet, cutter) in content(register.find("measurement-stop")[0])
    assert "T1" in summary and "Test cutter" in summary
    assert (
        content(register.find("measurement-stop")[0]).count(
            "?M# marks an unverified decision input"
        )
        == 1
    )
    assert "assumed value, not physically measured" not in summary
    assert content(register.find("measurement-stop")[0]).count(full_action(sheet, cutter)) == 1
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
    summary = Markup(sheet.job_measurement_box())
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
    assert (
        "test installed readout step" in resolution
        and "not consumed by a stopped decision" in resolution
    )
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
    register = Markup(sheet.job_measurement_box())
    assert "machines.mill.resolution" in actions(register)
    assert "test" in summary and "T1" not in content(actions(register)["machines.mill.resolution"])
    assert (
        "installed DRO least readable step, installed readout and indicator check, mm"
        in content(register.find("measurement-stop")[0])
    )
    assert (
        content(register.find("measurement-stop")[0]).count(
            "?M# marks an unverified decision input"
        )
        == 1
    )
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
    entry = length_debt(tool, "dia", "tools", "cutter")
    consumers = [finding("reach", "S1:10", {"measurements": [entry]})] if entry else []
    sheet = _Traveler(bundle, consumers, {}, None)
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
    item = measurement_item(bundle, "tools", "cutter/3-8in")
    entry = length_debt(item, "dia", "tools", "cutter/3-8in")
    sheet = _Traveler(bundle, [finding("reach", "S1:10", {"measurements": [entry]})], {}, None)
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
    assert directive not in content(summary)
    assert (
        content(Markup(sheet.job_measurement_box()).find("measurement-stop")[0]).count(directive)
        == 1
    )
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
    bundle.kernel["ops"]["S1:10"] = {"reasons": {"shank_hits": "missing measured shank_radius_mm"}}
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
    entry = length_debt(bundle.inventory["tools"]["cutter"], "dia", "tools", "cutter")
    sheet = _Traveler(bundle, [finding("reach", "S1:10", {"measurements": [entry]})], {}, None)
    _, _, html = sheet.tool_table(bundle.plan["setups"][0])
    markup = Markup(html)
    assert "shank Ø8.000" not in content(markup.find("tools")[0])
    assert "Ø8.000 ?M1" in content(markup.find("unverified")[0])


def test_registry_preserves_dotted_member_and_holder_identities_jobwide():
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
    item = measurement_item(bundle, "tools", "cutters/6.5mm")
    debts = [
        length_debt(item, field, "tools", "cutters/6.5mm", require_measured=True)
        for field in ("dia", ("projection", "collets/6.5mm"))
    ]
    findings = [
        finding("reach", f"{setup['id']}:10", {"measurements": debts}) for setup in (first, second)
    ]
    sheet = _Traveler(bundle, findings, {}, None)
    for setup in (first, second):
        _, _, html = sheet.tool_table(setup)
        registry = sheet.measurement_registry()
        projection = registry["tools.cutters/6.5mm.projection.collets/6.5mm"][1]
        assert projection["identity"] == "cutters/6.5mm"
        assert projection["field"] == ["projection", "collets/6.5mm"]
        assert {marker for marker, _ in registry.values()} == {"M1", "M2"}
        assert "cutters/" not in content(Markup(html).find("tools")[0])
        assert "collets/" not in content(Markup(html).find("tools")[0])
    assert sheet.setup_measurement_ids["S1"] == sheet.setup_measurement_ids["S2"] == set(registry)
    assert all(sheet.measurement_sources[key] == {"S1", "S2"} for key in registry)
    assert len(actions(Markup(sheet.job_measurement_box()))) == 2


def test_late_hold_and_dro_measurements_close_in_job_register_with_setup_refs(monkeypatch):
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
    register = Markup(sheet.job_measurement_box())
    assert not actions(markup)
    assert entry["id"] in actions(register)
    assert (
        len(
            [
                node
                for node in register.nodes
                if node["attrs"].get("data-measurement-id") == entry["id"]
            ]
        )
        == 1
    )
    assert "Support block" in content(markup.find("stop")[0])
    assert "Support block" not in content(actions(register)[entry["id"]])
    assert "Make-to-drawing expected settings are not installed measurements" in content(
        register.find("measurement-stop")[0]
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
                {
                    "dro_grid": {"step": 0.005, "decimals": 3},
                    "dro_grid_debt": "untrusted step",
                    "measurements": [entry],
                },
            )
        ],
        {},
        None,
    )
    sheet.setup_section(bundle.plan["setups"][0])
    markup = Markup(sheet.job_measurement_box())
    action = actions(markup)["machines.mill.resolution"]
    assert "EL400" in content(markup.find("measurement-actions")[0])
    assert "measure: its installed DRO least readable step" in content(action)
    header = sheet.dro_resolution(bundle.plan["setups"])
    assert "0.005 mm" in header and "EL400 installed readout step" in header
    assert header.count(marker_for(sheet, entry)) == 1 and "Setup S1 ?M" not in header
    assert "confirm installed readout" not in header
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
    summary = Markup(sheet.job_measurement_box())
    assert entry["id"] in actions(summary)
    assert content(summary.find("stop")[0]).count("?M# marks an unverified decision input") == 1
    assert full_action(sheet, entry) in content(actions(summary)[entry["id"]])


def test_measurement_actions_group_actual_records_without_changing_the_canonical_m_map():
    bundle = data()
    bundle.plan["dro"].update(controller="el400", manual="Electronica EL400 Operation Manual")
    bundle.inventory["machines"]["mill"]["name"] = "Shop mill"
    bundle.inventory["holders"]["second"] = {"kind": "collet", "name": "Second collet"}
    # Identical paper names must not collapse distinct inventory records.
    bundle.inventory["tools"]["other"] = deepcopy(bundle.inventory["tools"]["cutter"])
    sheet = _Traveler(bundle, [], {}, None)
    sheet.measurement_registry()
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
    sheet.finalize_measurements([])
    expected = deepcopy(sheet.measurement_registry())
    markup = Markup(sheet.job_measurement_box())
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
    assert "Shop mill" in content(groups[0]) and "EL400" not in content(groups[0])
    assert "EL400" in content(groups[1]) and "Shop mill" not in content(groups[1])
    assert content(groups[2]).count("Test cutter") == 1
    assert "M3 —" in content(groups[2]) and "M4 —" in content(groups[2])
    assert "M7 —" in content(groups[3]) and "M3 —" not in content(groups[3])
    for canonical, holder in (
        ("tools.cutter.projection.collet", "Test collet"),
        ("tools.cutter.projection.second", "Second collet"),
    ):
        row = actions(markup)[canonical]
        assert row["parent"]["parent"] is groups[2]
        assert content(row).count(f"in {holder}: measure: its holder face to mounted tool tip") == 1
        assert "Test cutter" not in content(row)
    assert len(markup.find("writing-blank")) == len(expected)
    assert [content(node) for node in markup.find("field-label")] == ["mm"] * len(expected)
    text = content(markup.find("stop")[0])
    assert "Record measured value here" not in text and "[____]" not in text
    assert text.count("Record the measured values here and return this traveler for reissue") == 1
    short_sheet = _Traveler(bundle, [], {}, None)
    short_sheet.measurement_registry()
    entries = [entry for _, entry in expected.values()]
    short_sheet.register_measurements(entries)
    short_sheet.finalize_measurements([])
    lines = short_sheet.measurement_lines([*entries, entries[0]])
    assert len(lines) == 6
    assert short_sheet.measurement_registry() == expected
    assert lines[0] == "Shop mill X usable travel ?M1"
    assert lines[1] == "EL400 readout step ?M2"
    assert lines[2] == sheet.measurement_subject(entries[2]) + " cutter Ø ?M3; shank Ø ?M6"
    assert lines[3] == sheet.measurement_subject(entries[3]) + " installed projection ?M4"
    assert lines[4] == sheet.measurement_subject(entries[4]) + " installed projection ?M5"
    assert lines[5] == sheet.measurement_subject(entries[6]) + " cutter Ø ?M7"
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


@pytest.mark.parametrize(
    "row_actions",
    [
        ("Check holder face and holding beside the cut ?M1.",) * 2,
        ("Check holder face ?M1.", "Check holding beside the cut ?M2."),
        ("Check holder face ?M1.", ""),
        ("Check holder face ?M1.", "Check holder face ?M1.", "Check holding ?M2."),
    ],
)
def test_clearance_shares_only_an_identical_nonempty_action_for_every_row(monkeypatch, row_actions):
    bundle = data()
    setup = bundle.plan["setups"][0]
    sheet = _Traveler(bundle, [finding("headroom", "S1", {"stacks": []})], {}, None)
    rows = [
        (str(index * 10), f"T{index}", f"Stock beside tool ?M{index}", "?", action)
        for index, action in enumerate(row_actions, 1)
    ]
    original = deepcopy(rows)
    monkeypatch.setattr(sheet, "clearance_rows", lambda setup, numbers, tools: rows)
    markup = Markup(sheet.clearance(setup))
    table = markup.find("clearance")[0]
    bodies = [node for node in markup.nodes if node["tag"] == "tbody" and node["parent"] is table]
    assert len(bodies) == len(rows)
    common = bool(row_actions[0]) and all(action == row_actions[0] for action in row_actions)
    for body, row in zip(bodies, rows, strict=True):
        cells = [
            node
            for node in markup.nodes
            if node["tag"] == "td"
            and node["parent"]["parent"] is body
            and node["parent"]["attrs"].get("class") != "warn"
        ]
        assert [content(cell) for cell in cells] == list(row[:4])
        if row[4]:
            assert content(body).count(row[4]) == (0 if common else 1)
    text = content(markup.nodes[0])
    if common:
        assert text.count(row_actions[0]) == 1
        assert "action for every clearance row: " + row_actions[0] in text
        assert not markup.find("see", within=table)
    else:
        assert "action for every clearance row:" not in text
        assert len(markup.find("see", within=table)) == sum(bool(action) for action in row_actions)
    assert rows == original


def bench_bundle():
    bundle = data(ops=[{"op": 10, "do": "inspect", "feature": "deck"}])
    setup = bundle.plan["setups"][0]
    setup["hold"] = {"fixture": "support", "clamp": "none"}
    bundle.inventory["machines"]["mill"].update(
        kind="bench",
        name="Fitting bench",
        envelope={"travel_mm": {"x": fact(500.0, "assumed"), "y": fact(200.0, "assumed")}},
    )
    bundle.inventory["fixtures"] = {
        "support": {
            "kind": "accessory",
            "name": "Bench support",
            "height_mm": fact(15.0, "assumed"),
            "solids": [
                {
                    "name": "body",
                    "label": "Support body",
                    "shape": "box",
                    "size_mm": [40.0, 20.0, 15.0],
                    "at_mm": [0.0, 0.0, 0.0],
                    "measured": fact(0.0, "assumed")["measured"],
                }
            ],
        }
    }
    return bundle


@pytest.mark.parametrize("status", ["pass", "not_applicable", "unsupported"])
def test_bench_unused_assumed_facts_have_no_stop_register_or_job_listing(status):
    bundle = bench_bundle()
    solid = measurement_entry("fixtures", "support", ("solids", "body"), status="assumed")
    travel = measurement_entry("machines", "mill", ("envelope", "travel", "x"), status="assumed")
    findings = [
        finding("fixture_interference", "S1", {"measurements": [solid, travel]}, status),
        finding("headroom", "S1", {}, "not_applicable"),
    ]
    before = deepcopy([f.to_dict() for f in findings])
    sheet = _Traveler(bundle, findings, {}, None)
    pages = sheet.setup_section(bundle.plan["setups"][0])
    assert not sheet.measurement_registry()
    assert sheet.setup_stops["S1"] == 0
    assert "STOP — do not run this setup" not in "".join(pages[0])
    assert not actions(Markup("".join(block for page in pages for block in page)))
    header = sheet.header(bundle.plan["setups"])
    assert "STOP items on the setup page" not in header
    assert "JOB MEASUREMENT REGISTER" not in header
    assert [f.to_dict() for f in findings] == before


@pytest.mark.parametrize(
    "category,field",
    [
        ("fixtures", ("solids", "body")),
        ("machines", ("envelope", "travel", "x")),
    ],
)
def test_true_local_unknown_consumer_retains_named_physical_records(category, field):
    bundle = bench_bundle()
    if category == "machines":
        bundle.inventory["machines"]["mill"]["kind"] = "mill"
        bundle.plan["setups"][0]["ops"] = data().plan["setups"][0]["ops"]
    key = "support" if category == "fixtures" else "mill"
    entry = measurement_entry(category, key, field, status="assumed")
    rule = "fixture_interference" if category == "fixtures" else "headroom"
    bundle.kernel["setups"] = {"S1": {"stock_bbox_mm": [0, 0, 0, 40, 20, 15]}}
    bundle.kernel["measurement_debts"] = {"setups": {"S1": [entry]}, "ops": {}}
    numbers = {"measurements": [entry]}
    if category == "machines":
        numbers["travel_checks"] = {"x": {"required_mm": 40.0, "travel_mm": "unknown"}}
    findings = [finding(rule, "S1", numbers)]
    before = deepcopy(findings[0].to_dict())
    sheet = _Traveler(bundle, findings, {}, None)
    pages = sheet.setup_section(bundle.plan["setups"][0])
    assert sheet.setup_stops["S1"] > 0
    assert "STOP — do not run this setup" in "".join(pages[0])
    register = Markup(sheet.job_measurement_box())
    assert actions(register)
    assert all(
        row["attrs"]["data-measurement-binding"] == entry["id"]
        for row in actions(register).values()
    )
    assert ("Bench support" if category == "fixtures" else "Fitting bench") in content(
        register.find("measurement-stop")[0]
    )
    assert not actions(Markup("".join(pages[0])))
    assert findings[0].to_dict() == before


def upstream_bench_case():
    bundle = bench_bundle()
    bench = bundle.plan["setups"][0]
    bench["id"], bench["stock_in"] = "S2", "S1"
    source = deepcopy(data().plan["setups"][0])
    source["machine"] = "source-mill"
    source["hold"] = {"fixture": "support", "clamp": "none"}
    bundle.inventory["machines"]["source-mill"] = {"kind": "mill", "resolution_mm": fact(0.005)}
    bundle.inventory["tools"]["cutter"].update(
        dia_mm=fact(6.35, "assumed"),
        flute_len_mm=fact(20.0, "assumed"),
        projection_mm={"collet": fact(28.0, "assumed")},
    )
    source["ops"][0]["holder"] = "collet"
    bundle.plan["setups"] = [source, bench]
    cause = (
        "S1:10 stock_removal_bounds is unresolved: missing measured cutter radius_mm; "
        "the in-process stock setup S1 leaves cannot be derived"
    )
    cutter = length_debt(bundle.inventory["tools"]["cutter"], "dia", "tools", "cutter")
    flute = length_debt(bundle.inventory["tools"]["cutter"], "flute_len", "tools", "cutter")
    projection = length_debt(
        bundle.inventory["tools"]["cutter"], ("projection", "collet"), "tools", "cutter"
    )
    solid = measurement_entry("fixtures", "support", ("solids", "body"), status="assumed")
    travel = measurement_entry("machines", "mill", ("envelope", "travel", "x"), status="assumed")
    bundle.kernel.update(
        setups={
            "S1": {"stock_bbox_mm": [0, 0, 0, 40, 20, 15], "stock_out_reason": cause},
            "S2": {"stock_reason": cause, "stock_out_reason": cause},
        },
        ops={"S1:10": {"reasons": {"stock_removal_bounds": "missing measured cutter radius_mm"}}},
        measurement_debts={
            "setups": {"S2": [solid, travel]},
            "ops": {"S1:10": [cutter, flute, projection]},
        },
    )
    findings = [
        finding(
            "fixture_interference",
            "S2",
            {"measurements": [solid, travel, cutter, flute, projection]},
        ),
        finding(
            "thin_wall_under_clamp",
            "S2",
            {"measurements": [solid, travel, cutter, flute, projection]},
        ),
        finding(
            "consistency",
            "S2",
            {
                "claims": 0,
                "contradictions": [],
                "unchecked": ["the kernel gave no setup-entry stock box for this setup"],
                "measurements": [solid],
            },
        ),
    ]
    return bundle, bench, findings, cutter


def test_prerequisite_fat_union_blocks_bench_with_source_ref_without_local_records():
    bundle, bench, findings, cutter = upstream_bench_case()
    before = deepcopy([f.to_dict() for f in findings])
    kernel_before = deepcopy(bundle.kernel)
    sheet = _Traveler(bundle, findings, {}, None)
    assert sheet.collect_measurements(bench) == []
    pages = sheet.setup_section(bench)
    assert sheet.setup_stops["S2"] > 0
    assert set(sheet.measurement_registry()) == {cutter["id"]}
    assert sheet.measurement_sources[cutter["id"]] == {"S1"}
    assert not sheet.setup_measurement_ids.get("S2")
    summary = content(Markup("".join(pages[0])).find("stop")[0])
    assert "Depends on Setup S1 op 10 — upstream stock not established" in summary
    assert marker_for(sheet, cutter) in summary
    assert "JOB measurements" in summary and "reissue" in summary
    assert "planned speeds, depths, contours" not in summary
    assert not actions(Markup("".join(block for page in pages for block in page)))
    header = sheet.header(bundle.plan["setups"])
    job_status = content(Markup(header).find("stop")[0])
    assert "Setup S2: STOP items" in job_status
    assert job_status.count("upstream stock depends on Setup S1 op 10") == 1
    register = Markup(sheet.job_measurement_box())
    assert set(actions(register)) == {cutter["id"]}
    assert "source Setup S1" in content(register.find("measurement-actions")[0])
    assert [f.to_dict() for f in findings] == before
    assert bundle.kernel == kernel_before


def test_unknown_unattributed_stock_prerequisite_stays_blocked_without_invented_records():
    bundle, bench, findings, _ = upstream_bench_case()
    bundle.kernel["setups"]["S2"]["stock_reason"] = "an upstream stock boolean is unresolved"
    sheet = _Traveler(bundle, findings, {}, None)
    pages = sheet.setup_section(bench)
    assert sheet.setup_stops["S2"] > 0 and not sheet.measurement_registry()
    text = content(Markup("".join(pages[0])).find("stop")[0])
    assert "upstream stock boolean is unresolved" in text and "reissue" in text
    assert "?M" not in text


def test_job_register_deterministically_reuses_shared_quantities_and_holder_contexts():
    bundle = data()
    bundle.plan["dro"].update(controller="el400", manual="Electronica EL400 Operation Manual")
    second = deepcopy(bundle.plan["setups"][0])
    second["id"] = "S2"
    bundle.plan["setups"].append(second)
    bundle.inventory["holders"]["second"] = {"kind": "collet", "name": "Second collet"}
    bundle.inventory["fixtures"] = {
        "riser": {"kind": "custom", "name": "Shop riser", "bed_height_mm": fact(25.0, "assumed")}
    }
    quantities = [
        measurement_entry("tools", "cutter", ("dia",)),
        measurement_entry("tools", "cutter", ("projection", "collet")),
        measurement_entry("tools", "cutter", ("projection", "second")),
        measurement_entry("machines", "mill", ("resolution",)),
        measurement_entry("machines", "mill", ("envelope", "travel", "x")),
        measurement_entry("holders", "collet", ("gauge_len",)),
        measurement_entry("fixtures", "riser", ("bed_height",)),
    ]
    outputs = []
    for order in (quantities, list(reversed(quantities))):
        sheet = _Traveler(bundle, [], {}, None)
        blocks = []
        for setup in bundle.plan["setups"]:
            sheet.setup = setup
            blocks.append(
                [
                    [
                        "<p>"
                        + " ".join(sheet.measurement_marker(e) for e in order)
                        + "; authored M -5.219 and M1</p>"
                    ]
                ]
            )
        sheet.setup = None
        resolved = sheet.finalize_measurements(blocks)
        markup = Markup(sheet.job_measurement_box())
        assert list(sheet.measurement_registry()) == sorted(e["id"] for e in quantities)
        labels = [row["attrs"]["data-measurement-label"] for row in actions(markup).values()]
        assert labels == [f"M{n}" for n in range(1, len(quantities) + 1)]
        assert len(markup.find("writing-blank")) == len(quantities)
        assert all(
            sheet.measurement_sources[key] == {"S1", "S2"} for key in sheet.measurement_registry()
        )
        assert len({marker_for(sheet, e) for e in quantities[1:3]}) == 2
        for quantity in quantities:
            assert content(actions(markup)[quantity["id"]]).count(full_action(sheet, quantity)) == 1
            assert all(marker_for(sheet, quantity) in page[0][0] for page in resolved)
        assert all("authored M -5.219 and M1" in page[0][0] for page in resolved)
        assert sheet.dro_resolution(bundle.plan["setups"]).count("?M") == 0
        outputs.append(sheet.job_measurement_box())
    assert outputs[0] == outputs[1]


@pytest.mark.parametrize(
    "solid,expected_fields",
    [
        (
            {
                "name": "block",
                "label": "Support block",
                "shape": "box",
                "size_mm": [30.0, 20.0, 15.0],
                "at_mm": [4.0, 5.0, 6.0],
            },
            {("size_mm", axis) for axis in "xyz"} | {("at_mm", axis) for axis in "xyz"},
        ),
        (
            {
                "name": "bore",
                "label": "Locating bore",
                "shape": "cylinder",
                "void": True,
                "dia_mm": 6.5,
                "length_mm": 12.0,
                "at_mm": [4.0, 5.0, 6.0],
                "axis": [0.0, 0.0, 1.0],
            },
            {("dia_mm",), ("length_mm",)} | {("at_mm", axis) for axis in "xyz"},
        ),
    ],
)
def test_composite_fixture_each_physical_leaf_has_one_full_size_blank_and_root_binding(
    solid, expected_fields
):
    bundle = data()
    bundle.inventory["fixtures"] = {
        "fixture": {"kind": "custom", "name": "Shop fixture", "solids": [solid]}
    }
    entry = {
        **measurement_entry("fixtures", "fixture", ("solids", solid["name"]), status="assumed"),
        "status": "assumed",
    }
    before = deepcopy(entry)
    sheet = _Traveler(bundle, [], {}, None)
    sheet.register_measurements([entry], bundle.plan["setups"][0])
    sheet.finalize_measurements([])
    register = Markup(sheet.job_measurement_box())
    quantities = [quantity for _, quantity in sheet.measurement_registry().values()]
    assert {tuple(q["physical_field"]) for q in quantities} == expected_fields
    assert all(q["status"] == "assumed" and q["binding"] == entry["id"] for q in quantities)
    assert len(actions(register)) == len(expected_fields)
    for quantity in quantities:
        row = actions(register)[quantity["id"]]
        assert row["attrs"]["data-measurement-binding"] == entry["id"]
        assert len(register.find("writing-blank", within=row)) == 1
        assert content(row).count(full_action(sheet, quantity)) == 1
    text = content(register.find("measurement-stop")[0])
    assert "length, width and height" not in text
    assert "Table 6" not in text and "fixtures.fixture" not in text
    anchor = "minimum corner" if solid["shape"] == "box" else "base centre"
    assert all(
        f"{anchor} local {axis.upper()} position from the fixture-local origin" in text
        for axis in "xyz"
    )
    assert entry == before


def test_scope_derived_reissue_and_legend_keep_authored_m_and_selected_reamer_meaning():
    bundle = data()
    bundle.inventory["tools"]["reamers"] = {
        "kind": "reamers",
        "members": {"6.5mm": {"dia_mm": fact(6.5, "assumed")}},
    }
    sheet = _Traveler(bundle, [], {}, None)
    sheet.register_measurements([measurement_entry("tools", "cutter", ("point_angle",))])
    job = content(Markup(sheet.job_measurement_box()).find("measurement-stop")[0])
    assert "Bare M is an authored measurement variable" in job
    assert "Bare M is a touch-off reading" not in job
    assert "6.5 mm reamer" == sheet.tool_name("reamers/6.5mm")
    stopped = content(
        Markup(
            sheet.setup_status_boxes(
                ["Depends on Setup S1 op 10 — upstream stock not established"], [], []
            )
        ).find("stop")[0]
    )
    assert "decisions named above" in stopped and "reissue" in stopped
    assert all(word not in stopped for word in ("speeds", "depths", "contours", "clearance"))


def test_known_non_radius_stock_frontier_keeps_true_blocker_without_quantity_guessing():
    bundle, bench, findings, _ = upstream_bench_case()
    reason = "the stock boolean did not complete"
    cause = f"S1:10 stock_removal_bounds is unresolved: {reason}"
    bundle.kernel["setups"]["S1"]["stock_out_reason"] = cause
    bundle.kernel["setups"]["S2"].update(stock_reason=cause, stock_out_reason=cause)
    bundle.kernel["ops"]["S1:10"]["reasons"]["stock_removal_bounds"] = reason
    sheet = _Traveler(bundle, findings, {}, None)
    pages = sheet.setup_section(bench)
    text = content(Markup("".join(pages[0])).find("stop")[0])
    assert "Depends on Setup S1 op 10" in text and reason in text
    assert "reissue" in text and "?M" not in text
    assert sheet.setup_stops["S2"] > 0 and not sheet.measurement_registry()
    assert reason in sheet.header(bundle.plan["setups"])


def test_shared_upstream_cause_has_one_job_line_and_only_source_owned_quantity():
    bundle, bench, findings, cutter = upstream_bench_case()
    third = deepcopy(bench)
    third.update(id="S3", stock_in="S2")
    bundle.plan["setups"].append(third)
    bundle.kernel["setups"]["S3"] = deepcopy(bundle.kernel["setups"]["S2"])
    findings.append(finding("fixture_interference", "S3", deepcopy(findings[0].numbers)))
    sheet = _Traveler(bundle, findings, {}, None)
    pages = [sheet.setup_section(setup) for setup in (bench, third)]
    sheet.finalize_measurements(pages)
    header = sheet.header(bundle.plan["setups"])
    job_status = content(Markup(header).find("stop")[0])
    assert job_status.count("upstream stock depends on Setup S1 op 10") == 1
    assert "Setups S2, S3:" in job_status
    assert all(sheet.setup_stops[sid] > 0 for sid in ("S2", "S3"))
    assert sheet.measurement_sources[cutter["id"]] == {"S1"}
    assert set(actions(Markup(header))) == {cutter["id"]}
    assert len(Markup(header).find("writing-blank")) == 1


def test_unused_assumed_tool_metadata_does_not_create_a_job_measurement():
    bundle = data()
    bundle.inventory["tools"]["cutter"].update(
        dia_mm=fact(6.35, "assumed"),
        flute_len_mm=fact(20.0, "assumed"),
        oal_mm=fact(60.0, "assumed"),
    )
    setup = bundle.plan["setups"][0]
    sheet = _Traveler(bundle, [], {}, None)
    _, _, html = sheet.tool_table(setup)
    text = content(Markup(html).find("tools")[0])
    assert "not verified" in text and "?M" not in text
    assert not sheet.measurement_registry() and not sheet.job_measurement_box()


def test_passed_clearance_diagnostic_measurements_do_not_register_local_records():
    bundle = data()
    unused = measurement_entry("machines", "mill", ("envelope", "travel", "x"), status="assumed")
    numbers = {
        "sum_mm": 20.0,
        "spindle_to_table_max_mm": 100.0,
        "travel_checks": {"x": {"required_mm": 40.0, "travel_mm": 500.0}},
        "stacks": [],
        "measurements": [unused],
    }
    sheet = _Traveler(bundle, [finding("headroom", "S1", numbers, "pass")], {}, None)
    html = sheet.clearance(bundle.plan["setups"][0])
    assert "?M" not in html and "measure:" not in html
    assert not sheet.measurement_registry()


def test_point_length_stop_names_angle_before_its_untrusted_cutter_diameter():
    bundle, findings, _, _ = stopped_setup()
    bundle.inventory["tools"]["drill"]["dia_mm"] = fact(6.0, "assumed")
    sheet = _Traveler(bundle, findings, {}, None)
    pages = sheet.setup_section(bundle.plan["setups"][0])
    rows = {
        node["attrs"]["data-op"]: content(node)
        for node in Markup("".join(block for page in pages for block in page)).find("operation")
    }
    point = rows["30"]
    start = point.index("drill point length unknown")
    heading = point[start:]
    assert heading.index("point angle") < heading.index("cutter Ø")


def test_semantic_pilot_body_and_as_made_height_instructions_have_no_missing_table():
    bundle = data(
        tools={
            "cutter": {
                "kind": "center_drill",
                "name": "Centre drill",
                "dia_mm": fact(2.0, "assumed"),
                "shank_mm": fact(6.0, "assumed"),
                "pilot_len_mm": fact(3.0, "assumed"),
            }
        }
    )
    bundle.inventory["fixtures"] = {
        "support": {
            "kind": "custom",
            "name": "Shop support",
            "bed_height_mm": fact(12.0, "assumed"),
        }
    }
    sheet = _Traveler(bundle, [], {}, None)
    entries = [
        measurement_entry("tools", "cutter", (field,), status="assumed")
        for field in ("dia", "shank", "pilot_len")
    ] + [measurement_entry("fixtures", "support", ("bed_height",), status="assumed")]
    before = deepcopy(entries)
    sheet.register_measurements(entries, bundle.plan["setups"][0])
    rows = {
        key: content(node) for key, node in actions(Markup(sheet.job_measurement_box())).items()
    }
    assert "centre drill pilot diameter" in rows[entries[0]["id"]]
    assert "centre drill countersink body diameter" in rows[entries[1]["id"]]
    assert "pilot length, countersink start to point tip" in rows[entries[2]["id"]]
    assert "as-made support height, table to work-support contact surface" in rows[entries[3]["id"]]
    assert all(
        "Table 6" not in text and " D " not in text and " A " not in text for text in rows.values()
    )
    assert entries == before


def test_direction_unit_keeps_each_abbreviation_intact_with_break_after_slash():
    sheet = _Traveler(data(), [], {}, None)
    sheet.register_measurements([measurement_entry("machines", "mill", ("spindle", "rotation"))])
    html = sheet.job_measurement_box()
    assert '<span class="reading">cw</span>/<wbr><span class="reading">ccw</span>' in html
    assert "cw/ccw" in content(Markup(html).find("field-label")[0])


def test_coordinate_cut_order_debt_is_retained_without_generated_path_or_grid_debt():
    bundle = data()
    setup = bundle.plan["setups"][0]
    setup["ops"][0]["direction"] = "climb"
    bundle.inventory["machines"]["mill"]["spindle_rotation"] = fact("cw", "assumed")
    rotation = measurement_entry("machines", "mill", ("spindle", "rotation"), status="assumed")
    numbers = {
        "contours": [{"op": 10, "cut_order_reason": "spindle rotation is not verified"}],
        "measurements": [rotation],
    }
    sheet = _Traveler(bundle, [finding("coordinates", "S1", numbers)], {}, None)
    assert sheet.collect_measurements(setup) == [rotation]
    sheet.tool_table(setup)
    assert set(actions(Markup(sheet.job_measurement_box()))) == {rotation["id"]}


@pytest.mark.parametrize(
    "depth,shank,hits,holder_verified,status,consumed",
    [
        ("unknown", 0, 0, True, "unknown", False),
        (10.0, 0, 0, True, "unknown", False),
        (30.0, 0, 0, True, "unknown", True),
        (30.0, "unknown", 0, True, "unknown", False),
        (30.0, 1, 0, True, "error", False),
        (30.0, 0, 1, True, "error", False),
        (30.0, 0, 0, False, "unknown", False),
    ],
)
def test_reach_oal_requires_a_real_beyond_flute_host_comparison(
    depth, shank, hits, holder_verified, status, consumed
):
    bundle = data(
        tools={
            "cutter": {
                "kind": "endmill",
                "name": "Test cutter",
                "dia_mm": fact(6.35),
                "flute_len_mm": fact(20.0),
                "oal_mm": fact(60.0, "assumed"),
                "projection_mm": {"collet": fact(30.0)},
            }
        }
    )
    bundle.inventory["holders"]["collet"].update(
        gauge_dia_mm=fact(18.0),
        gauge_len_mm=fact(30.0, "measured" if holder_verified else "assumed"),
    )
    setup = bundle.plan["setups"][0]
    setup["ops"][0]["holder"] = "collet"
    oal = length_debt(bundle.inventory["tools"]["cutter"], "oal", "tools", "cutter")
    numbers = {
        "reach_depth_mm": depth,
        "flute_len_mm": 20.0,
        "oal_mm": "unknown",
        "measurements": [oal],
        "shank_hits": shank,
        "holder_wall_hits": hits,
    }
    sheet = _Traveler(bundle, [finding("reach", "S1:10", numbers, status)], {}, None)
    assert sheet.collect_measurements(setup) == ([oal] if consumed else [])


def test_saw_unknown_keeps_only_own_consumed_kerf_from_upstream_union():
    bundle, bench, _, cutter = upstream_bench_case()
    bundle.inventory["tools"]["blade"] = {
        "kind": "bandsaw",
        "name": "Saw blade",
        "kerf_mm": fact(0.8, "assumed"),
    }
    bench["ops"] = [{"op": 10, "do": "saw_cut", "tool": "blade", "cut_plane": {"z": 20.0}}]
    kerf = length_debt(bundle.inventory["tools"]["blade"], "kerf", "tools", "blade")
    bundle.kernel["ops"]["S2:10"] = {"stock_reason": bundle.kernel["setups"]["S2"]["stock_reason"]}
    sheet = _Traveler(
        bundle,
        [finding("saw_cut", "S2:10", {"kerf_mm": "unknown", "measurements": [kerf, cutter]})],
        {},
        None,
    )
    assert sheet.collect_measurements(bench) == [kerf]


def test_native_local_holder_refusal_survives_stock_block_without_inherited_radius_debt():
    bundle, bench, findings, cutter = upstream_bench_case()
    bundle.inventory["holders"]["second"] = {"kind": "collet", "name": "Second collet"}
    bench["ops"] = [
        {"op": 10, "do": "face", "tool": "cutter", "holder": "second", "feature": "deck"}
    ]
    holder = measurement_entry("holders", "second", ("gauge_dia",), status="assumed")
    cause = bundle.kernel["setups"]["S2"]["stock_reason"]
    bundle.kernel["measurement_debts"]["ops"]["S2:10"] = [cutter, holder]
    bundle.kernel["ops"]["S2:10"] = {
        "stock_reason": cause,
        "reasons": {
            "holder_hits": "missing measured holder_radius_mm",
            "stock_removal_bounds": cause,
            "shank_hits": f"the stock before this op is unknown: {cause}",
        },
    }
    sheet = _Traveler(bundle, findings, {}, None)
    assert sheet.collect_measurements(bench) == [holder]


def test_local_fixture_unknown_does_not_consume_merged_machine_coordinate_metadata():
    bundle = bench_bundle()
    setup = bundle.plan["setups"][0]
    solid = measurement_entry("fixtures", "support", ("solids", "body"), status="assumed")
    metadata = [
        measurement_entry("machines", "mill", field, status="assumed")
        for field in (("resolution",), ("spindle", "rotation"), ("envelope", "travel", "x"))
    ]
    bundle.kernel["setups"] = {"S1": {"stock_bbox_mm": [0, 0, 0, 40, 20, 15]}}
    bundle.kernel["measurement_debts"] = {"setups": {"S1": [solid, *metadata]}, "ops": {}}
    sheet = _Traveler(
        bundle,
        [finding("fixture_interference", "S1", {"measurements": [solid, *metadata]})],
        {},
        None,
    )
    assert sheet.collect_measurements(setup) == [solid]
    sheet.tool_table(setup)
    assert all(
        entry["binding"] == solid["id"] for _, entry in sheet.measurement_registry().values()
    )


def test_local_geometry_unknown_does_not_consume_another_operations_tool_record():
    bundle = data()
    selected = measurement_entry("tools", "cutter", ("dia",), status="assumed")
    other = measurement_entry("tools", "other", ("dia",), status="assumed")
    bundle.inventory["tools"]["other"] = {"kind": "endmill", "name": "Other cutter"}
    sheet = _Traveler(
        bundle, [finding("reach", "S1:10", {"measurements": [selected, other]})], {}, None
    )
    assert sheet.collect_measurements(bundle.plan["setups"][0]) == [selected]


def test_stock_block_does_not_erase_independent_engagement_and_speed_consumers():
    bundle, bench, findings, cutter = upstream_bench_case()
    source = bundle.plan["setups"][0]
    bench.update(machine=source["machine"], ops=deepcopy(source["ops"]))
    projection = bundle.kernel["measurement_debts"]["ops"]["S1:10"][2]
    findings.extend(
        [
            finding("engagement", "S2:10", {"measurements": [cutter, projection]}),
            finding("speeds_feeds", "S2:10", {"measurements": [cutter]}),
        ]
    )
    before = deepcopy([f.to_dict() for f in findings])
    cause = bundle.kernel["setups"]["S2"]["stock_reason"]
    bundle.kernel["ops"]["S2:10"] = {
        "stock_reason": cause,
        "reasons": {"stock_removal_bounds": cause},
    }
    sheet = _Traveler(bundle, findings, {}, None)
    assert sheet.collect_measurements(bench) == sorted([cutter, projection], key=lambda e: e["id"])
    sheet.tool_table(bench)
    upstream = sheet.upstream_stock_stop(bench)
    assert marker_for(sheet, cutter) in upstream
    assert set(sheet.measurement_registry()) == {cutter["id"], projection["id"]}
    assert sheet.measurement_sources[cutter["id"]] == {"S1", "S2"}
    assert sheet.measurement_sources[projection["id"]] == {"S2"}
    assert [f.to_dict() for f in findings] == before


def test_job_el400_readout_line_has_one_ref_and_one_register_owner():
    bundle = data()
    bundle.plan["dro"].update(controller="el400", manual="Electronica EL400 Operation Manual")
    bundle.inventory["machines"]["mill"].update(
        name="PM-30MV", resolution_mm=fact(0.005, "assumed")
    )
    second = deepcopy(bundle.plan["setups"][0])
    second["id"] = "S2"
    bundle.plan["setups"].append(second)
    step = measurement_entry("machines", "mill", ("resolution",), status="assumed")
    findings = [
        finding(
            "coordinates",
            setup["id"],
            {"dro_grid_debt": "installed step is not verified", "measurements": [step]},
        )
        for setup in bundle.plan["setups"]
    ]
    sheet = _Traveler(bundle, findings, {}, None)
    for setup in bundle.plan["setups"]:
        sheet.tool_table(setup)
    sheet.finalize_measurements([])
    readout = sheet.dro_resolution(bundle.plan["setups"])
    assert "EL400" in readout and "PM-30MV" not in readout
    assert re.findall(r"\?M\d+", readout) == [marker_for(sheet, step)]
    header = sheet.header(bundle.plan["setups"])
    assert set(actions(Markup(header))) == {step["id"]}
    assert len(Markup(header).find("writing-blank")) == 1
    assert content(actions(Markup(header))[step["id"]]).count(full_action(sheet, step)) == 1


@pytest.mark.parametrize("rule,subject", [("engagement", "S1:10"), ("headroom", "S1")])
def test_undeclared_projection_keeps_engagement_and_headroom_oal_consumer(rule, subject):
    bundle = data(
        tools={
            "cutter": {
                "kind": "endmill",
                "name": "Test cutter",
                "dia_mm": fact(6.35),
                "flute_len_mm": fact(20.0),
                "oal_mm": fact(60.0, "assumed"),
            }
        }
    )
    setup = bundle.plan["setups"][0]
    setup["ops"][0]["holder"] = "collet"
    bundle.inventory["holders"]["collet"].update(
        gauge_dia_mm=fact(18.0),
        gauge_len_mm=fact(30.0),
        grip_mm=fact(15.0),
    )
    oal = length_debt(bundle.inventory["tools"]["cutter"], "oal", "tools", "cutter")
    consumer = finding(rule, subject, {"projection_mm": "unknown", "measurements": [oal]})
    before = deepcopy(consumer.to_dict())
    inventory_before = deepcopy(bundle.inventory)
    sheet = _Traveler(bundle, [consumer], {}, None)
    assert sheet.collect_measurements(setup) == [oal]
    sheet.tool_table(setup)
    assert set(actions(Markup(sheet.job_measurement_box()))) == {oal["id"]}
    assert consumer.to_dict() == before and bundle.inventory == inventory_before
