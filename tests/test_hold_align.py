"""A mill setup that mounts or turns a vise or angle plate squares it to the table travel
before the work goes in: hold_fields requires ``hold.align`` there, and the HOLD prints it."""

import re
from html import unescape

import pytest

from prechips.inputs import Bundle
from prechips.rules import hold_fields, tool_resolves
from prechips.sheet import _Traveler

ALIGN = {"indicator": "dti", "limit_mm": 0.0254, "over_mm": 100.0, "cite": "AUTHOR'S CHOICE"}
PLATE = {**ALIGN, "face": "upright"}
POSE = {"origin_mm": [0.0, 0.0, 0.0], "x": [1.0, 0.0, 0.0], "z": [0.0, 0.0, 1.0]}
TURNED = {**POSE, "x": [0.0, 1.0, 0.0]}


def setup(sid, fixture, machine="mill", align=ALIGN, **hold):
    hold = {"fixture": fixture, "stop": "none", "grip_mm": 10.0, "clamp": "tighten", **hold}
    if fixture == "vise":
        hold = {"jaws_along": "x", "fixed_jaw": "rear", **hold}
    else:
        hold["fixed_jaw"] = "not_applicable"
    if align is not None:
        hold["align"] = align
    return {
        "id": sid,
        "machine": machine,
        "hold": hold,
        "coolant": "none",
        "deburr_mm": 0.2,
        "stock_state": {"top_z": 0.0, "bottom_z": -10.0},
        "ops": [],
    }


def bundle(*setups):
    # The plate's upright face runs along its own x; a square boss on it also locates.
    plate = [
        {"name": "upright", "shape": "box", "size_mm": [127.0, 12.7, 76.2], "locates": "seat"},
        {"name": "boss", "shape": "box", "size_mm": [16.0, 16.0, 6.0], "locates": "end"},
    ]
    return Bundle(
        plan={"setups": list(setups)},
        features={"units": "mm", "features": {}},
        inventory={
            "machines": {"mill": {"kind": "mill"}, "saw": {"kind": "bandsaw"}},
            "fixtures": {
                "vise": {"kind": "vise", "name": "6 in vise"},
                "plate": {"kind": "angle_plate", "name": "angle plate", "solids": plate},
                "jig": {"kind": "custom", "name": "profile jig"},
            },
            "gauges": {
                "dti": {"kind": "dial_test_indicator", "name": "0.0005 in test indicator"},
                "calipers": {"kind": "caliper", "name": "calipers"},
            },
        },
        policy={},
        cutting_data={},
        paths={},
        hashes={},
        root=None,
        kernel={},
    )


def test_a_vise_or_plate_is_squared_where_it_is_mounted_or_turned_on_a_mill():
    data = bundle(
        setup("V1", "vise"),  # first on the mill
        setup("V2", "vise"),  # stays as it was
        setup("V3", "vise", jaws_along="y"),  # turned a quarter
        setup("B1", "vise", machine="saw"),  # a bandsaw vise is not trammed
        setup("V4", "vise", jaws_along="y"),
        setup("J1", "jig"),  # the vise comes off for the jig
        setup("V5", "vise", jaws_along="y"),  # so it goes back on
        setup("P1", "plate", pose=POSE),
        setup("P2", "plate", pose=POSE),
        setup("P3", "plate", pose=TURNED),  # the plate is moved
    )
    assert hold_fields.align_due(data) == {
        "V1": "mounted",
        "V3": "jaws turned",
        "V5": "mounted",
        "P1": "mounted",
        "P3": "plate moved",
    }


# The vise on the mill is one vise on one mill however a setup spells either, so the next
# setup's vise is still squared; spelling never re-mounts it nor leaves it unsquared.
@pytest.mark.parametrize("first,second", [("", "fixtures."), ("fixtures.", "")])
def test_a_vise_stays_squared_however_the_next_setup_spells_it_or_its_mill(first, second):
    machines = {"": "machines.mill", "fixtures.": "mill"}
    data = bundle(
        setup("V1", first + "vise", machine=machines[first], jaws_along="x", fixed_jaw="rear"),
        setup("V2", second + "vise", machine=machines[second], jaws_along="x", fixed_jaw="rear"),
    )
    assert hold_fields.align_due(data) == {"V1": "mounted"}


@pytest.mark.parametrize(
    ("align", "status", "debt"),
    [
        (ALIGN, "pass", []),
        (None, "error", ["hold.align"]),
        ({**ALIGN, "indicator": "calipers"}, "error", ["hold.align.indicator"]),
        ({**ALIGN, "indicator": "unknown"}, "unknown", ["hold.align.indicator"]),
        ({**ALIGN, "limit_mm": 0.0}, "error", ["hold.align.limit_mm"]),
        ({**ALIGN, "over_mm": "unknown"}, "unknown", ["hold.align.over_mm"]),
    ],
)
def test_a_setup_that_mounts_a_vise_must_say_how_it_is_squared(align, status, debt):
    data = bundle(setup("V1", "vise", align=align), setup("V2", "vise", align=None))
    row, again = hold_fields.evaluate(data)
    assert row.status == status and row.numbers["missing"] == debt
    # The vise stays where V1 squared it: V2 needs no align of its own.
    assert again.status == "pass" and again.numbers["align_due"] == "not_applicable"


@pytest.mark.parametrize(
    ("align", "pose", "status", "debt"),
    [
        (PLATE, POSE, "pass", []),
        (ALIGN, POSE, "error", ["hold.align.face"]),  # which face of the plate is squared
        ({**PLATE, "face": "base"}, POSE, "error", ["hold.align.face"]),  # no such solid
        ({**PLATE, "face": "boss"}, POSE, "unknown", ["hold.align.travel"]),  # 16 x 16
        (PLATE, {**POSE, "x": [0.6, 0.8, 0.0]}, "unknown", ["hold.align.travel"]),  # skewed
    ],
)
def test_an_angle_plate_names_the_face_it_squares_and_that_face_runs_along_x_or_y(
    align, pose, status, debt
):
    (row,) = hold_fields.evaluate(bundle(setup("P1", "plate", pose=pose, align=align)))
    assert row.status == status and row.numbers["missing"] == debt


def hold_text(data, sid):
    findings = hold_fields.evaluate(data)
    sheet = _Traveler(data, findings, {}, None)
    plan_setup = next(s for s in data.plan["setups"] if s["id"] == sid)
    steps, _ = sheet.hold(plan_setup)
    return " ".join(unescape(re.sub(r"<[^>]+>", " ", steps)).split())


def test_the_hold_squares_the_fixed_jaw_along_its_travel_with_the_named_indicator():
    data = bundle(setup("V1", "vise", jaws_along="y"), setup("V2", "vise", jaws_along="y"))
    text = hold_text(data, "V1")
    assert (
        "Square the fixed jaw to the Y travel: with the 0.0005 in test indicator held from the "
        "spindle head on the fixed jaw, traverse Y 100 mm along it; tap the vise round until "
        "the reading changes no more than 0.0254 mm (0.001 in) over that length"
    ) in text
    # Squared once the vise is on, before the work goes in.
    assert text.index("Mount the") < text.index("Square the fixed jaw")
    assert "Square" not in hold_text(data, "V2")


def test_the_hold_squares_an_angle_plate_face_along_the_run_its_pose_gives():
    text = hold_text(bundle(setup("P1", "plate", pose=TURNED, align=PLATE)), "P1")
    assert "Square the plate's upright face to the Y travel" in text


@pytest.mark.parametrize(
    ("fixture", "align", "stop"),
    [
        ("vise", {**ALIGN, "limit_mm": "unknown"}, "the fixed jaw to the table travel — the limit"),
        ("plate", ALIGN, "the plate's locating face to the table travel — the travel it runs"),
    ],
)
def test_an_align_not_established_is_a_stop_on_the_hold(fixture, align, stop):
    text = hold_text(bundle(setup("S1", fixture, pose=POSE, align=align)), "S1")
    assert f"STOP: square {stop}" in text and "do not run" in text


@pytest.mark.parametrize(
    "gauge",
    [{"verify": True}, {"present": "unknown"}, {"kind": "unknown"}],
    ids=["unverified", "presence-unknown", "kind-unknown"],
)
def test_an_indicator_not_established_on_hand_leaves_the_squaring_unknown_and_a_stop(gauge):
    data = bundle(setup("V1", "vise"))
    data.inventory["gauges"]["dti"].update(gauge)
    (row,) = hold_fields.evaluate(data)
    assert row.status == "unknown" and row.numbers["missing"] == ["hold.align.indicator"]
    text = hold_text(data, "V1")
    assert "STOP: square the fixed jaw to the table travel — the indicator" in text, text
    assert "Square the fixed jaw" not in text


def test_the_indicator_an_align_selects_is_an_inventory_reference_like_any_other():
    # Named only in hold.align, the indicator's identity is still checked: unverified, it
    # is unknown there too, and verified it resolves.
    data = bundle(setup("V1", "vise"))
    rows = {f.subject: f for f in tool_resolves.evaluate(data)}
    assert rows["dti"].status == "pass"
    data.inventory["gauges"]["dti"]["verify"] = True
    rows = {f.subject: f for f in tool_resolves.evaluate(data)}
    assert rows["dti"].status == "unknown"


@pytest.mark.parametrize(
    ("fixture", "debt"),
    [
        ("vise", ["hold.align.indicator", "hold.align.limit_mm", "hold.align.over_mm"]),
        (
            "plate",
            [
                "hold.align.indicator",
                "hold.align.limit_mm",
                "hold.align.over_mm",
                "hold.align.face",
            ],
        ),
    ],
)
def test_an_align_stated_unknown_is_unknown_never_absent(fixture, debt):
    data = bundle(setup("S1", fixture, pose=POSE, align="unknown"))
    (row,) = hold_fields.evaluate(data)
    assert row.status == "unknown" and row.numbers["missing"] == debt
    assert "do not run" in hold_text(data, "S1")
