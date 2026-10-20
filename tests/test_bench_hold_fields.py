"""Manual bench holding applicability without a CAD kernel or fictional mill stations."""

import re

import pytest
from test_bench_routed_screens import bench_bundle
from test_sheet_ops import Markup, content

from prechips.inputs import Bundle
from prechips.model import HAND_FEEDING
from prechips.rules import hold_fields
from prechips.sheet import _Traveler

MECHANICAL = ("fit", "deburr", "scribe", "file_to_line")
PREREQUISITES = (
    "hold.fixture",
    "hold.stop",
    "hold.grip_mm",
    "hold.clamp",
    "coolant",
    "deburr_mm",
)
AXIS_DEBT = {"hold.fixed_jaw", "stock_state.top_z", "stock_state.bottom_z"}
NOTE = "Support the part on the clean felt pad; turn it by hand for inspection"
FIXTURE_NAME = "Soft-lined bench cradle"


def bundle(actions=("fit",), kind="bench"):
    source = bench_bundle(kind=kind, actions=actions)
    setup = source.plan["setups"][0]
    setup.update(
        stock_in="stock",
        hold={
            "fixture": "cradle",
            "stop": "seat against the cradle end",
            "grip_mm": 12.5,
            "clamp": "tighten the strap by hand",
        },
        coolant="none",
        deburr_mm=0.2,
    )
    # A real Bundle supports both the rule and the traveler; no fabricated sheet methods.
    return Bundle(
        plan=source.plan,
        features=source.features,
        inventory={
            "machines": source.inventory["machines"],
            "fixtures": {"cradle": {"kind": "custom", "name": FIXTURE_NAME}},
            "tools": {
                "hacksaw": {"kind": "hand_saw", "name": "Fine-tooth hacksaw", "verify": False},
                "unchecked": {"kind": "hand_saw", "verify": True},
                "powered": {"kind": "bandsaw", "verify": False},
            },
        },
        policy={},
        cutting_data={},
        paths={},
        hashes={},
        root=None,
        kernel=source.kernel,
    )


def setup_of(data):
    return data.plan["setups"][0]


def finding(data):
    (row,) = hold_fields.evaluate(data)
    return row


def change_field(data, path, value=None, *, delete=False):
    target = setup_of(data)
    parts = path.split(".")
    for part in parts[:-1]:
        target = target[part]
    if delete:
        del target[parts[-1]]
    else:
        target[parts[-1]] = value


def handling_bundle(actions=("inspect",), kind="bench"):
    data = bundle(actions, kind)
    setup = setup_of(data)
    setup["hold"] = {"note": NOTE}
    del setup["coolant"], setup["deburr_mm"]
    return data


@pytest.mark.parametrize("kind", ["bench", "manual"])
@pytest.mark.parametrize("action", MECHANICAL)
def test_fixture_held_manual_work_needs_real_holding_not_mill_stations(kind, action):
    data = bundle((action,), kind)
    row = finding(data)
    assert row.status == "pass"
    assert row.numbers["missing"] == []
    assert row.numbers["fixture"] == "cradle"
    assert row.numbers["hold"]["grip_mm"] == 12.5
    assert row.numbers["coolant"] == "none"
    assert row.numbers["deburr_mm"] == 0.2
    assert row.numbers["align_due"] == "not_applicable"


def test_punch_fit_still_has_mechanical_holding_requirements():
    data = bundle()
    data.inventory["tools"]["punch"] = {"kind": "punch", "name": "Hand punch", "verify": False}
    setup_of(data)["ops"][0]["tool"] = "punch"
    assert finding(data).status == "pass"
    del setup_of(data)["hold"]["clamp"]
    row = finding(data)
    assert row.status == "error"
    assert set(row.numbers["missing"]) == {"hold.clamp"}


@pytest.mark.parametrize("action", MECHANICAL)
@pytest.mark.parametrize("field", PREREQUISITES)
@pytest.mark.parametrize("delete,status", [(True, "error"), (False, "unknown")])
def test_no_blanket_manual_waiver_for_mechanical_prerequisites(action, field, delete, status):
    data = bundle((action,))
    change_field(data, field, "unknown", delete=delete)
    row = finding(data)
    assert row.status == status
    assert set(row.numbers["missing"]) == {field}


@pytest.mark.parametrize("kind", ["bench", "manual"])
@pytest.mark.parametrize("actions", [("inspect",), ("coating",), ("inspect", "coating")])
def test_note_only_handling_requires_no_fixture_cutting_or_axis_declarations(kind, actions):
    row = finding(handling_bundle(actions, kind))
    assert row.status == "pass"
    assert row.numbers["missing"] == []
    assert row.numbers["fixture"] == "not_applicable"
    assert row.numbers["coolant"] == "not_applicable"
    assert row.numbers["deburr_mm"] == "not_applicable"
    assert row.numbers["hold"]["note"] == NOTE


@pytest.mark.parametrize("detail", ["pro", "hobby", "pedantic"])
def test_segmented_handling_uses_full_note_and_preserves_authored_evidence(detail):
    from prechips.model import note_text

    data = handling_bundle()
    note = [
        {
            "text": "Support the part on the clean felt pad; turn it by hand for inspection. "
            "Stop the spindle before handling.",
            "detail": "pedantic",
        },
    ]
    setup_of(data)["hold"]["note"] = note
    rendered = note_text(note, detail=detail)
    row = finding(data)
    assert row.status == "pass"
    assert row.numbers["missing"] == []
    assert row.numbers["hold"]["note"] == note
    assert setup_of(data)["hold"]["note"] is note
    assert bool(rendered) is (detail == "pedantic")


@pytest.mark.parametrize("text", ["none", "not_applicable", " \t\n"])
def test_segmented_note_cannot_bypass_missing_handling(text):
    data = handling_bundle()
    setup_of(data)["hold"]["note"] = [{"text": text, "detail": "pedantic"}]
    if text.strip():
        row = finding(data)
        assert row.status == "error"
        assert row.numbers["missing"] == ["hold.note"]
    else:
        with pytest.raises(ValueError, match="known and non-empty"):
            finding(data)


@pytest.mark.parametrize(
    "note,status",
    [
        (None, "error"),
        ("", "error"),
        (" \t\n", "error"),
        ("none", "error"),
        ("not_applicable", "error"),
        ("unknown", "unknown"),
    ],
)
def test_handling_note_must_be_known_and_nonblank(note, status):
    data = handling_bundle()
    if note is None:
        del setup_of(data)["hold"]["note"]
    else:
        setup_of(data)["hold"]["note"] = note
    row = finding(data)
    assert row.status == status
    assert set(row.numbers["missing"]) == {"hold.note"}


@pytest.mark.parametrize("field", ["fixture", "stop", "grip_mm", "clamp", "supports", "parallels"])
def test_supplied_unknown_physical_fields_cannot_become_note_only_handling(field):
    data = handling_bundle()
    setup_of(data)["hold"][field] = "unknown"
    row = finding(data)
    expected = set(PREREQUISITES)
    if field not in {"fixture", "stop", "grip_mm", "clamp"}:
        expected.add(f"hold.{field}")
    assert row.status == "error"
    assert set(row.numbers["missing"]) == expected


def test_unknown_holding_kind_cannot_become_note_only_handling():
    data = handling_bundle()
    setup_of(data)["hold"]["kind"] = "unknown"
    row = finding(data)
    assert row.status == "error"
    assert set(row.numbers["missing"]) == {
        "hold.kind",
        "coolant",
        "deburr_mm",
        *(f"hold.{key}" for key in HAND_FEEDING),
    }


@pytest.mark.parametrize("kind", ["bench", "manual"])
@pytest.mark.parametrize("actions", [("inspect",), ("coating",), ("inspect", "coating")])
def test_unknown_hold_as_a_whole_is_unknown_handling_not_an_empty_declaration(kind, actions):
    data = handling_bundle(actions, kind)
    setup_of(data)["hold"] = "unknown"
    row = finding(data)
    assert row.status == "unknown"
    assert set(row.numbers["missing"]) == {"hold.note"}


@pytest.mark.parametrize("actions", [("fit", "drill"), ("inspect", "face"), ("fit", "unknown"), ()])
def test_mixed_nonmanual_unknown_and_empty_ops_keep_machine_holding_requirements(actions):
    data = bundle(actions)
    extra = set()
    for op in setup_of(data)["ops"]:
        if op["do"] in {"drill", "face", "unknown"}:
            extra.add(f"ops.{op['op']}.holder")
        if op["do"] in {"face", "unknown"}:
            extra.add(f"ops.{op['op']}.direction")
    row = finding(data)
    assert row.status == "error"
    assert set(row.numbers["missing"]) == AXIS_DEBT | extra


@pytest.mark.parametrize(
    "kind,status", [("mill", "error"), ("lathe", "error"), ("unknown", "error")]
)
def test_manual_actions_do_not_waive_nonbench_machine_requirements(kind, status):
    row = finding(bundle(kind=kind))
    expected = (
        {"stock_state.od_mm", "hold.support", "hold.grip_on", "stock_state.end_station"}
        if kind == "lathe"
        else AXIS_DEBT
    )
    assert row.status == status
    assert set(row.numbers["missing"]) == expected


@pytest.mark.parametrize("action", ["saw_cut", "cut_off"])
@pytest.mark.parametrize("tool", [None, "not-listed", "unknown", "unchecked"])
def test_unresolved_and_unverified_saws_keep_machine_stations(action, tool):
    data = bundle((action,))
    if tool is not None:
        setup_of(data)["ops"][0]["tool"] = tool
    row = finding(data)
    assert row.status == "error"
    assert set(row.numbers["missing"]) == AXIS_DEBT


@pytest.mark.parametrize("action", ["saw_cut", "cut_off"])
@pytest.mark.parametrize("tool", ["hacksaw", "powered"])
@pytest.mark.parametrize("field", [None, *PREREQUISITES])
@pytest.mark.parametrize("delete", [False, True])
def test_verified_bench_saw_waives_axes_not_fixture_or_retention(action, tool, field, delete):
    data = bundle((action,))
    setup_of(data)["ops"][0]["tool"] = tool
    if field is not None:
        change_field(data, field, "unknown", delete=delete)
    row = finding(data)
    assert row.status == ("pass" if field is None else "error" if delete else "unknown")
    assert set(row.numbers["missing"]) == (set() if field is None else {field})


@pytest.mark.parametrize(
    "field", ["supports", "support_orientation", "parallels", "jaws_along", "locate", "stop_face"]
)
def test_supplied_fixture_specific_unknowns_remain_debt_on_manual_bench(field):
    data = bundle()
    setup_of(data)["hold"][field] = "unknown"
    row = finding(data)
    assert row.status == "unknown"
    assert set(row.numbers["missing"]) == {f"hold.{field}"}


@pytest.mark.parametrize("known_faces,status", [(False, "unknown"), (True, "error")])
def test_manual_bench_does_not_waive_unavailable_stop_face(known_faces, status):
    data = bundle()
    setup_of(data)["hold"]["stop_face"] = "future_face"
    data.features["features"]["future_face"] = {"faces": ["face-9"]}
    if known_faces:
        data.plan["stock"]["as_is_faces"] = []
    row = finding(data)
    assert row.status == status
    assert row.numbers["missing"] == []
    assert row.numbers["stop_face"]["on_arriving_stock"] == (False if known_faces else "unknown")


def rendered_holding(data):
    sheet = _Traveler(data, hold_fields.evaluate(data), {}, None)
    setup = setup_of(data)
    steps, below = sheet.hold(setup)
    markup = Markup(steps + below)
    stops = [
        node
        for node in markup.nodes
        if node["tag"] in {"li", "p", "td"} and re.search(r"\bSTOP\b", content(node))
    ]
    text = " ".join(content(node) for node in markup.nodes if node["tag"] == "li")
    return text, stops


@pytest.mark.parametrize("actions", [("inspect",), ("coating",), ("inspect", "coating")])
def test_sheet_known_handling_prints_its_note_without_inventing_fixture_stops(actions):
    text, stops = rendered_holding(handling_bundle(actions))
    assert stops == []
    assert NOTE in text
    assert FIXTURE_NAME not in text


@pytest.mark.parametrize("note", [None, "", " \t", "none", "not_applicable", "unknown"])
def test_sheet_unestablished_handling_stops_holding(note):
    data = handling_bundle()
    if note is None:
        del setup_of(data)["hold"]["note"]
    else:
        setup_of(data)["hold"]["note"] = note
    _, stops = rendered_holding(data)
    assert stops


@pytest.mark.parametrize("actions", [("fit",), ("deburr",), ("scribe",), ("file_to_line",)])
def test_sheet_mechanical_note_cannot_replace_a_missing_fixture(actions):
    data = handling_bundle(actions)
    _, stops = rendered_holding(data)
    assert stops


@pytest.mark.parametrize("actions", [("fit",), ("inspect",), ("coating",)])
def test_sheet_selected_real_fixture_keeps_its_shop_name(actions):
    text, stops = rendered_holding(bundle(actions))
    assert stops == []
    assert FIXTURE_NAME in text


@pytest.mark.parametrize("selection", ["fixture", "kind"])
def test_sheet_explicit_unknown_selection_never_prints_as_known_handling(selection):
    data = handling_bundle()
    setup_of(data)["hold"][selection] = "unknown"
    _, stops = rendered_holding(data)
    assert stops


@pytest.mark.parametrize("kind", ["bench", "manual"])
@pytest.mark.parametrize("action", ["saw_cut", "cut_off"])
def test_known_portable_bandsaw_with_vise_needs_no_fabricated_mill_axes(kind, action):
    data = bundle((action, "deburr", "inspect"), kind)
    data.inventory["fixtures"]["cradle"]["kind"] = "vise"
    data.inventory["tools"]["powered"].update(kerf_mm="unknown", tpi="unknown")
    setup_of(data)["ops"][0]["tool"] = "powered"
    row = finding(data)
    assert row.status == "pass"
    assert row.numbers["missing"] == []
    assert row.numbers["fixture"] == "cradle"
    assert row.numbers["hold"]["grip_mm"] == 12.5
    assert row.numbers["align_due"] == "not_applicable"


@pytest.mark.parametrize("kind", ["mill", "lathe", "unknown", "bandsaw"])
def test_portable_blade_does_not_waive_nonbench_machine_holding(kind):
    data = bundle(("saw_cut",), kind)
    setup_of(data)["ops"][0]["tool"] = "powered"
    row = finding(data)
    expected = (
        {"stock_state.od_mm", "hold.support", "hold.grip_on", "stock_state.end_station"}
        if kind == "lathe"
        else AXIS_DEBT
    )
    assert row.status == "error"
    assert set(row.numbers["missing"]) == expected


@pytest.mark.parametrize("target", ["machine", "tool"])
@pytest.mark.parametrize(
    "declaration",
    [
        {"verify": True},
        {"verify": "unknown"},
        {"present": "unknown"},
        {"coverage": "verify physical identity"},
    ],
)
def test_portable_saw_requires_known_machine_and_tool_identity(target, declaration):
    data = bundle(("saw_cut",))
    setup_of(data)["ops"][0]["tool"] = "powered"
    item = (
        data.inventory["machines"]["station"]
        if target == "machine"
        else data.inventory["tools"]["powered"]
    )
    item.update(declaration)
    row = finding(data)
    assert row.status == "error"
    assert set(row.numbers["missing"]) == AXIS_DEBT


@pytest.mark.parametrize("tool_kind", ["unknown", "endmill", "slitting_saw"])
def test_portable_saw_requires_a_known_nonspindle_saw_tool(tool_kind):
    data = bundle(("saw_cut",))
    setup_of(data)["ops"][0]["tool"] = "powered"
    data.inventory["tools"]["powered"]["kind"] = tool_kind
    row = finding(data)
    assert row.status == "error"
    expected = AXIS_DEBT | ({"ops.10.holder"} if tool_kind == "slitting_saw" else set())
    assert set(row.numbers["missing"]) == expected


@pytest.mark.parametrize("action", ["drill", "face", "unknown"])
def test_portable_saw_mixed_with_ordinary_or_unknown_cut_keeps_old_requirements(action):
    data = bundle(("saw_cut", action))
    setup_of(data)["ops"][0]["tool"] = "powered"
    row = finding(data)
    expected = AXIS_DEBT | {"ops.20.holder"}
    if action in {"face", "unknown"}:
        expected.add("ops.20.direction")
    assert row.status == "error"
    assert set(row.numbers["missing"]) == expected


@pytest.mark.parametrize("second_tool", ["not-listed", "unknown", "unchecked"])
def test_every_saw_in_portable_bench_setup_must_have_known_identity(second_tool):
    data = bundle(("saw_cut", "cut_off"))
    first, second = setup_of(data)["ops"]
    first["tool"] = "powered"
    second["tool"] = second_tool
    row = finding(data)
    assert row.status == "error"
    assert set(row.numbers["missing"]) == AXIS_DEBT


def test_portable_saw_preserves_supplied_unknown_support_debt():
    data = bundle(("saw_cut",))
    setup_of(data)["ops"][0]["tool"] = "powered"
    setup_of(data)["hold"]["supports"] = "unknown"
    row = finding(data)
    assert row.status == "unknown"
    assert set(row.numbers["missing"]) == {"hold.supports"}


def test_portable_saw_preserves_unavailable_stop_face_debt():
    data = bundle(("saw_cut",))
    setup_of(data)["ops"][0]["tool"] = "powered"
    setup_of(data)["hold"]["stop_face"] = "future_face"
    data.features["features"]["future_face"] = {"faces": ["face-9"]}
    data.plan["stock"]["as_is_faces"] = []
    row = finding(data)
    assert row.status == "error"
    assert row.numbers["missing"] == []
    assert row.numbers["stop_face"]["on_arriving_stock"] is False


def test_portable_saw_preserves_swivel_declared_on_nonvise_contradiction():
    data = bundle(("saw_cut",))
    setup_of(data)["ops"][0]["tool"] = "powered"
    setup_of(data)["hold"]["jaws_angle_deg"] = 15.0
    row = finding(data)
    assert row.status == "error"
    assert row.numbers["missing"] == []
    assert len(row.numbers["misdeclared"]) == 1
