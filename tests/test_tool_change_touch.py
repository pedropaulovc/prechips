"""One DRO per setup: a tool that did not set it is touched off before it cuts."""

import math
import re
import subprocess
from copy import deepcopy
from decimal import Decimal
from html import unescape
from types import SimpleNamespace

import pytest
from test_envelope_m5 import measured
from test_kernel_geometry import Engine
from test_sheet_ops import Markup, content

from prechips.rules.zero_recipe.rule import evaluate
from prechips.sheet import _Traveler

DRO = {
    "controller": "el400",
    "mode": "abs",
    "radius_mode": False,
    "direction": {"x": "away_from_spindle_axis", "y": "away", "z": "toward_exposed_end"},
}


def sheet_text(html):
    return content(Markup(f"<div>{html}</div>").nodes[0])


def dro_markup(html, *, units="mm", mode="linear"):
    """Keep numeric probes in the rendered readout's unit and display-mode context."""
    markup = Markup(html)
    (heading,) = [
        node
        for node in markup.nodes
        if node["tag"] == "h2" and content(node).startswith("DRO ZERO")
    ]
    assert re.search(
        rf",\s*{re.escape(units)},\s*{re.escape(mode)}\s+mode\b", content(heading)
    ), content(heading)
    return markup


def dro_paragraphs(html, *, units="mm", mode="linear"):
    markup = dro_markup(html, units=units, mode=mode)
    return [" ".join(content(node).split()) for node in markup.nodes if node["tag"] == "p"]


_NUMBER = r"[+−-]?(?:\d+(?:\.\d+)?|\.\d+)"


def exact_number(text):
    """Parse the whole printed number; padding is immaterial, value changes are not."""
    assert re.fullmatch(_NUMBER, text.strip()), text
    return Decimal(text.strip().replace("−", "-"))


def axis_set_value(text, axis, *, base=None):
    """Read one axis's setting, or its offset from a named measured base."""
    prefix = rf"\bAxis Set\s+{re.escape(axis)}\s+"
    if base is not None:
        prefix += rf"{re.escape(base)}\s*\+\s*"
    # A final full stop is punctuation, never a truncated decimal or identifier.
    (value,) = re.findall(prefix + rf"({_NUMBER})(?!\w|\.[\w.])", text)
    return exact_number(value)


def bundle(machine, zero, ops, stock_state=None):
    data = SimpleNamespace(
        plan={
            "dro": deepcopy(DRO),
            "setups": [
                {
                    "id": "S1",
                    "machine": machine,
                    "frame": "F",
                    "zero": zero,
                    "stock_state": stock_state or {},
                    "ops": ops,
                }
            ],
        },
        features={
            "units": "mm",
            "frames": {"F": {"binding": "nominal"}},
            "features": {"journal": {}},
        },
        inventory={
            "machines": {
                "lathe": {"kind": "lathe", "resolution_mm": measured(0.001)},
                "mill": {
                    "kind": "mill",
                    "resolution_mm": measured(0.001),
                    "spindle": {"rpm_min": 50, "rpm_max": 3000},
                },
            },
            "tools": {
                name: {"kind": kind, "tip_in": 0.2}
                for name, kind in (
                    ("turner", "insert_holder"),
                    ("parter", "parting_blade"),
                    ("finder", "edge_finder"),
                    ("centre", "center_drill_set"),
                    ("drill", "drill"),
                    ("mill", "endmill"),
                )
            },
            "gauges": {"mic": {"kind": "micrometer"}},
        },
        policy={},
        kernel=None,
    )
    data.feature_definitions = data.features["features"]
    # An edge finder's EDGE FINDER box facts (docs/inventory.md "Edge finder").
    data.inventory["tools"]["finder"].update(finder_type="mechanical", rpm_range=[1000, 1200])
    data.inventory["tools"]["centre"].update(
        sizes=[1],
        angle_deg=60,
        members={
            "1": {
                "dia_mm": 1.98,
                "pilot_len_mm": 1.98,
                "shank_mm": 4.7625,
                "point_angle": 118,
            }
        },
    )
    return data


def test_bundles_own_their_readout_configuration(monkeypatch):
    changed = bundle("mill", {}, [])
    monkeypatch.setitem(changed.plan["dro"], "kind", "unknown")
    monkeypatch.setitem(changed.plan["dro"], "mode", "incremental")
    monkeypatch.setitem(changed.plan["dro"]["direction"], "z", "unknown")
    fresh = bundle("mill", {}, [])
    expected = {
        "controller": "el400",
        "mode": "abs",
        "radius_mode": False,
        "direction": {"x": "away_from_spindle_axis", "y": "away", "z": "toward_exposed_end"},
    }
    assert fresh.plan["dro"] == expected
    assert DRO == expected


def op(number, do, feature, tool, **extra):
    return {"op": number, "do": do, "feature": feature, "tool": tool, **extra}


def lathe_zero(touches):
    return {
        "x": {
            "feature": "spindle_axis",
            "edge_mm": 0.0,
            "from": "+x",
            "method": "trial_cut_measure",
            "tool": "turner",
            "gauge": "mic",
            "check_jog_mm": 10.0,
        },
        "z": {
            "face": "stub end",
            "edge_mm": 5.0,
            "from": "+z",
            "method": "touch",
            "tool": "turner",
            "paper_mm": 0.0,
            "check_jog_mm": 10.0,
            "retouch_after": [],
        },
        "tool_touches": touches,
    }


# The shoulder faces the free end (the turner faced it from +Z): the blade meets it with
# its chuck-side corner, from +Z, so its paper stands it off toward the free end. Its X
# is on the journal the turner turned, through the same paper.
BLADE = {
    "tool": "parter",
    "x_method": "touch the journal just measured",
    "x_face": "journal",
    "x_paper_mm": 0.05,
    "gauge": "mic",
    "z_face": "shoulder",
    "edge_mm": -7.5,
    "paper_mm": 0.05,
    "method": "paper",
    "corner": "chuck_side",
    "before_ops": [40],
}
LATHE_OPS = [
    op(10, "rough_turn", "journal", "turner"),
    op(20, "face", "shoulder", "turner", to_z=-7.5),
    op(30, "finish_turn", "journal", "turner"),
    op(40, "form_relief", "relief", "parter"),
]


def test_the_turning_tool_back_after_a_blade_touch_is_re_touched():
    ops = [*LATHE_OPS, op(50, "face", "dome", "turner", to_z=0.0)]
    finding = evaluate(bundle("lathe", lathe_zero([BLADE]), ops))[0]
    assert finding.status == "pass"
    assert finding.numbers["missing_touches"] == []
    [touch] = finding.numbers["derived_touches"]
    # Z repeats the blade's touch on the shoulder; X touches the last diameter turned.
    assert touch["before_ops"] == [50] and touch["tool"] == "turner"
    assert (touch["z_face"], touch["edge_mm"], touch["paper_mm"]) == ("shoulder", -7.5, 0.05)
    assert touch["z_axis_set"] == pytest.approx(-7.45)
    # The blade's own recipe ("paper", its corner) is not the turning tool's.
    assert touch["method"] == "edge_then_set"
    assert (touch["x_face"], touch["gauge"], touch["x_axis_set"]) == (
        "journal",
        "mic",
        "measured D",
    )


def test_a_blade_that_finishes_the_setup_needs_no_re_touch():
    finding = evaluate(bundle("lathe", lathe_zero([BLADE]), LATHE_OPS))[0]
    assert finding.status == "pass"
    assert finding.numbers["derived_touches"] == []


# A tool is the item it selects: ops naming "tools.turner" and touches naming "turner" (or
# the reverse) are one tool, so no touch is invented and none goes missing.
@pytest.mark.parametrize("op_spelling,touch_spelling", [("tools.", ""), ("", "tools.")])
def test_one_tool_spelled_two_ways_is_one_dro_setter(op_spelling, touch_spelling):
    ops = [{**row, "tool": op_spelling + row["tool"]} for row in LATHE_OPS]
    zero = lathe_zero([{**BLADE, "tool": touch_spelling + BLADE["tool"]}])
    for axis in ("x", "z"):
        zero[axis]["tool"] = touch_spelling + zero[axis]["tool"]
    finding = evaluate(bundle("lathe", zero, ops))[0]
    assert finding.status == "pass"
    assert finding.numbers["missing_touches"] == []
    assert finding.numbers["derived_touches"] == []
    # Each toolpost tool is set on centre once, before its first touch-off.
    assert [row["touch"] for row in finding.numbers["tool_setting"]] == ["zero", "tool_touches"]


def test_a_lathe_tool_change_with_no_diameter_to_touch_is_an_error():
    # The blade's X came from its own trial cut: no measured diameter stands for the
    # turning tool to touch, so its X Axis Set cannot be derived.
    touch = {**BLADE, "x_method": "trial_cut_measure", "before_ops": [20]}
    ops = [
        op(10, "face", "shoulder", "turner", to_z=-7.5),
        op(20, "part_off", "relief", "parter"),
        op(30, "face", "dome", "turner", to_z=0.0),
    ]
    finding = evaluate(bundle("lathe", lathe_zero([touch]), ops))[0]
    assert finding.status == "error"
    assert finding.numbers["missing_touches"] == [
        {"before_op": 30, "tool": "turner", "axes": ["x"], "dro_set_by": "parter"}
    ]


def test_a_turned_diameter_formed_away_is_no_longer_touched():
    # The nose turned in op 10 is formed into a dome in op 20: no cylinder is left to
    # touch the blade off on, so its X needs a planned touch.
    ops = [
        op(10, "turn", "nose", "turner"),
        op(20, "form_dome", "nose", "turner"),
        op(30, "part_off", "relief", "parter"),
    ]
    data = bundle("lathe", lathe_zero([]), ops)
    finding = evaluate(data)[0]
    assert finding.status == "error"
    assert finding.numbers["missing_touches"] == [
        {"before_op": 30, "tool": "parter", "axes": ["x"], "dro_set_by": "turner"}
    ]
    # The sheet stops the operator at that op instead of printing a touch.
    html = sheet_text(_Traveler(data, [finding], {}, {}).dro(data.plan["setups"][0], {}))
    assert "STOP: before op 30" in html and "no X touch" in html


def test_a_diameter_a_touch_names_only_in_words_is_not_tracked_for_the_next_tool():
    # Nothing was turned in the setup; the blade's touch surface is prose whose survival
    # past the blade's own cut the rule cannot follow, so the turner's X is planned.
    ops = [
        op(10, "face", "shoulder", "turner", to_z=-7.5),
        op(20, "form_relief", "relief", "parter"),
        op(30, "face", "dome", "turner", to_z=0.0),
    ]
    words = {key: value for key, value in BLADE.items() if key != "x_face"}
    finding = evaluate(bundle("lathe", lathe_zero([{**words, "before_ops": [20]}]), ops))[0]
    assert finding.status == "error"
    assert finding.numbers["missing_touches"] == [
        {"before_op": 30, "tool": "turner", "axes": ["x"], "dro_set_by": "parter"}
    ]


def mill_zero(z, retouch_after=()):
    return {
        "x": {"edge": "left", "edge_mm": 0.0, "from": "-x", "tool": "finder", "check_jog_mm": 5},
        "y": {"edge": "front", "edge_mm": 0.0, "from": "-y", "tool": "finder", "check_jog_mm": 5},
        "z": {
            "from": "+z",
            "check_jog_mm": 5.0,
            "paper_mm": 0.05,
            "retouch_after": list(retouch_after),
            **z,
        },
        "tool_touches": [],
    }


DECK = {"face": "deck", "edge_mm": 10.0, "method": "touch", "tool": "centre/1"}
# The setup's tool names, keyed by the item each tool reference selects.
TURNER = {("tools", "turner"): "T1 turner"}


def test_a_drill_after_the_centre_drill_that_set_z_is_re_touched_on_the_zero_face():
    ops = [op(10, "spot", "hole", "centre/1"), op(20, "drill", "hole", "drill")]
    finding = evaluate(bundle("mill", mill_zero(DECK), ops))[0]
    assert finding.status == "pass"
    [touch] = finding.numbers["derived_touches"]
    assert touch["before_ops"] == [20] and touch["tool"] == "drill"
    assert (touch["z_face"], touch["edge_mm"], touch["paper_mm"]) == ("deck", 10.0, 0.05)
    assert touch["z_axis_set"] == pytest.approx(10.05)
    assert "x_axis_set" not in touch


def carried_stock_bundle(*, journal=False):
    """Synthetic whole sleeve face, bonded on a second branch, then remounted.

    These axis-aligned boxes exercise C4/CH and J3/JH routing, not the cone
    example's oblique native cap or its physical measurements.
    """
    raw_z = -21.0 if journal else -21.3753
    stands = 21.0 if journal else 0.0
    north, south, cylinder, hole = ("#1/NORTH", "#2/SOUTH", "#3/OD", "#4/BORE")
    feature = "cone_boss_north_face" if journal else "crank_boss_faces"
    zero = mill_zero(
        {"face": feature, "edge_mm": stands, "method": "touch_then_set", "tool": "centre/1"}
    )
    zero["z"]["paper_mm"] = 0.0
    data = bundle(
        "mill",
        zero,
        [op(10, "spot", "hole", "centre/1", depth_mm=0.15), op(20, "drill", "hole", "drill")],
    )
    consumer = data.plan["setups"][0]
    consumer.update(id="S9" if journal else "S8", frame="JH" if journal else "CH", stock_in="S7")
    identity = {
        "origin": [0.0, 0.0, 0.0],
        "x": [1.0, 0.0, 0.0],
        "y": [0.0, 1.0, 0.0],
        "z": [0.0, 0.0, 1.0],
        "binding": "nominal",
    }
    source_frame = "J3" if journal else "C4"
    data.features.update(
        units="mm",
        frames={
            "model": identity,
            source_frame: {
                **identity,
                "origin": [0.0, 0.0, raw_z],
                "y": [0.0, -1.0, 0.0],
                "z": [0.0, 0.0, -1.0],
            },
            consumer["frame"]: {
                **identity,
                "origin": [0.0, 0.0, 0.0 if journal else raw_z],
                "x": [0.0, -1.0, 0.0],
                "y": [-1.0, 0.0, 0.0],
                "z": [0.0, 0.0, -1.0],
            },
        },
    )
    data.feature_definitions.update(
        {
            feature: {
                "kind": "face",
                "frame": "model",
                "faces": [north] if journal else [north, south],
            },
            "spigot": {"kind": "boss", "frame": "model", "faces": [cylinder]},
            "hole": {
                "kind": "hole",
                "frame": "model",
                "faces": [hole],
                "at": [0.0, 0.0, 0.0],
                "axis": [0.0, 0.0, 1.0],
                "thru": True,
            },
        }
    )
    preparation = {
        "id": "S2" if journal else "S3",
        "machine": "lathe",
        "frame": source_frame,
        "stock_in": "stock.sleeve",
        "zero": lathe_zero([]),
        "ops": [
            op(10, "face", feature, "turner", faces=[north], to_z=0.0, to_dia=0.0),
            op(20, "finish_turn", "spigot", "turner", z_from=0.0, z_to=-73.0),
            op(40, "part_off", feature, "turner", faces=[south], to_z=-72.0),
        ],
    }
    preparation["zero"]["z"]["edge_mm"] = 1.0
    body = {"id": "S1", "machine": "bench", "frame": "model", "stock_in": "stock.body", "ops": []}
    bond = {
        "id": "S7",
        "machine": "bench",
        "frame": "model",
        "stock_in": [body["id"], preparation["id"]],
        "ops": [op(10, "fit", feature, "unknown")],
    }
    data.inventory["machines"]["bench"] = {"kind": "bench"}
    data.inventory["machines"]["mill"]["resolution_mm"] = measured(0.005)
    data.inventory["tools"]["centre"] = {
        "kind": "center_drill_set",
        "sizes": [1],
        "angle_deg": 60,
        "members": {"1": {"dia_mm": 0.3, "pilot_len_mm": 0.2, "shank_mm": 0.4, "point_angle": 118}},
    }
    data.inventory["tools"]["drill"].update(dia_mm=0.8, point_angle=118)
    data.plan.update(
        stock={"as_is_faces": [], "components": [{"id": "body"}, {"id": "sleeve"}]},
        setups=[body, preparation, bond, consumer],
    )
    data.kernel = {
        "status": "ok",
        "mapping": {ref: i for i, ref in enumerate((north, south, cylinder, hole))},
        "features": {feature: [0] if journal else [0, 1], "spigot": [2], "hole": [3]},
        "faces": [
            {"index": 0, "kind": "Plane", "bbox_mm": [-1.0, -1.0, raw_z, 1.0, 1.0, raw_z]},
            {
                "index": 1,
                "kind": "Plane",
                "bbox_mm": [-1.0, -1.0, raw_z + 72, 1.0, 1.0, raw_z + 72],
            },
            {"index": 2, "kind": "Cylinder", "bbox_mm": [-1.0, -1.0, raw_z, 1.0, 1.0, raw_z + 72]},
            {"index": 3, "kind": "Cylinder", "bbox_mm": [-0.5, -0.5, raw_z, 0.5, 0.5, raw_z + 72]},
        ],
        "ops": {
            f"{preparation['id']}:10": {
                "approach": "turning",
                "claimed_indices": [0],
                "faced_side": 1,
            },
            f"{preparation['id']}:20": {"approach": "turning", "claimed_indices": [2]},
            f"{preparation['id']}:40": {
                "approach": "turning",
                "claimed_indices": [1],
                "faced_side": -1,
            },
            f"{consumer['id']}:10": {"claimed_indices": [3]},
            f"{consumer['id']}:20": {"claimed_indices": [3]},
        },
        "setups": {
            preparation["id"]: {
                "revolved": {
                    feature: {
                        "kinds": ["Plane"],
                        "z_mm": [0.0, 0.0] if journal else [-72.0, 0.0],
                        "radii_mm": [0.5, 1.0],
                        "end_radii_mm": [1.0, 1.0],
                        "end_faces": (
                            [{"z_mm": 0.0, "normal_z": 1}]
                            if journal
                            else [
                                {"z_mm": -72.0, "normal_z": -1},
                                {"z_mm": 0.0, "normal_z": 1},
                            ]
                        ),
                    },
                    "spigot": {
                        "kinds": ["Cylinder"],
                        "z_mm": [-72.0, 0.0],
                        "radii_mm": [1.0, 1.0],
                    },
                }
            }
        },
    }
    return data


def carried_rectangular_stock_bundle(*, journal=False):
    """The same 2x2-mm native face, explicitly proved filled and rectangular."""
    data = carried_stock_bundle(journal=journal)
    data.kernel["faces"][0].update(fills_bbox=True, area_mm2=4.0)
    source = data.plan["setups"][1]
    source["ops"] = source["ops"][:1]
    feature = data.plan["setups"][-1]["zero"]["z"]["face"]
    data.kernel["setups"][source["id"]]["revolved"][feature].update(
        radii_mm=[0.0, math.sqrt(2.0)], end_radii_mm=[math.sqrt(2.0), math.sqrt(2.0)]
    )
    return data


def carried_two_level_bundle(
    *, units="mm", prepared="lower", lower_mm=0.0, upper_mm=10.0, source_grid_mm=0.005
):
    """The existing component DAG, with two +Z native planes and one whole producer."""
    data = carried_stock_bundle()
    source, receiver = data.plan["setups"][1], data.plan["setups"][-1]
    scale = 25.4 if units == "in" else 1.0
    feature = receiver["zero"]["z"]["face"]
    ref, index, height = (
        ("#1/NORTH", 0, lower_mm) if prepared == "lower" else ("#2/SOUTH", 1, upper_mm)
    )
    data.features["units"] = units
    source["frame"] = receiver["frame"] = "model"
    source["zero"]["z"]["edge_mm"] = (height + 1.0) / scale
    source["ops"] = [
        op(10, "face", feature, "turner", faces=[ref], to_z=height / scale, to_dia=0.0)
    ]
    receiver["zero"]["z"]["edge_mm"] = height / scale
    data.inventory["machines"]["lathe"]["resolution_mm"] = measured(source_grid_mm)
    data.kernel["faces"][0]["bbox_mm"] = [-3.0, -3.0, lower_mm, 3.0, 3.0, lower_mm]
    data.kernel["faces"][1]["bbox_mm"] = [-1.0, -1.0, upper_mm, 1.0, 1.0, upper_mm]
    data.kernel["faces"][0].update(fills_bbox=True, area_mm2=36.0)
    data.kernel["faces"][1].update(fills_bbox=True, area_mm2=4.0)
    data.kernel["ops"][f"{source['id']}:10"].update(claimed_indices=[index], faced_side=1)
    data.kernel["setups"][source["id"]]["revolved"][feature].update(
        z_mm=[lower_mm, upper_mm],
        radii_mm=[0.0, math.sqrt(18.0)],
        end_radii_mm=[math.sqrt(18.0), math.sqrt(2.0)],
        end_faces=[
            {"z_mm": lower_mm, "normal_z": 1},
            {"z_mm": upper_mm, "normal_z": 1},
        ],
    )
    data.feature_definitions["hole"]["at"] = [
        (1.5 if prepared == "lower" else 0.0) / scale,
        0.0,
        height / scale,
    ]
    data.feature_definitions["hole"]["axis"] = [0.0, 0.0, -1.0]
    return data


def carried_supplied_component_bundle():
    """Existing sleeve/body route, with the sleeve face proven before any cut."""
    data = carried_rectangular_stock_bundle(journal=True)
    source, receiver = data.plan["setups"][1], data.plan["setups"][-1]
    feature = receiver["zero"]["z"]["face"]
    source["ops"] = []
    source["stock_state"] = {"top_z": 0.0, "top_feature": feature}
    data.plan["stock"]["as_is_faces"] = ["#1/NORTH"]
    data.features["datums"] = {"D": {"feature": feature, "surface": "north sleeve face"}}
    facts = data.kernel["setups"][source["id"]]
    facts["stock_faces_mm"] = {feature: {"up": {"face_z": 0.0, "stock_z": 0.0}}}
    facts["render_scene"] = {
        "datums": [
            {
                "label": "DATUM D: north sleeve face",
                "normal": [0.0, 0.0, 1.0],
                "outline_mm": [
                    [[-1.0, -1.0, 0.0], [1.0, -1.0, 0.0]],
                    [[1.0, -1.0, 0.0], [1.0, 1.0, 0.0]],
                    [[1.0, 1.0, 0.0], [-1.0, 1.0, 0.0]],
                    [[-1.0, 1.0, 0.0], [-1.0, -1.0, 0.0]],
                ],
            }
        ]
    }
    return data


def carried_native_datum_bundle(*, physical=21.0055):
    """An oblique native plane whose source and received scenes prove its outline."""
    data = carried_stock_bundle(journal=True)
    c, s = math.sin(math.radians(12.5)), math.cos(math.radians(12.5))
    source, consumer = data.plan["setups"][1], data.plan["setups"][-1]
    feature = consumer["zero"]["z"]["face"]
    source_frame, current_frame = data.features["frames"]["J3"], data.features["frames"]["JH"]
    source_frame.update(
        origin=[-c * physical, 0.0, -s * physical],
        x=[s, 0.0, -c],
        y=[0.0, -1.0, 0.0],
        z=[-c, 0.0, -s],
    )
    current_frame.update(
        origin=[0.0, 0.0, 0.0],
        x=[0.0, -1.0, 0.0],
        y=[-s, 0.0, c],
        z=[-c, 0.0, -s],
    )
    source["ops"] = source["ops"][:1]
    data.feature_definitions["hole"].update(
        at=list(source_frame["origin"]), axis=[-v for v in source_frame["z"]]
    )
    consumer["zero"]["z"]["edge_mm"] = physical
    data.inventory["machines"]["mill"]["resolution_mm"] = measured(0.005)
    data.features["datums"] = {"D": {"feature": feature, "surface": "north sleeve face"}}
    data.kernel["features"] = {feature: [0]}
    data.kernel["faces"][0]["bbox_mm"] = [
        -c * physical - s,
        -1.0,
        -s * physical - c,
        -c * physical + s,
        1.0,
        -s * physical + c,
    ]

    def scene(height):
        return {
            "render_scene": {
                "datums": [
                    {
                        "label": "DATUM D: north sleeve face",
                        "normal": [0.0, 0.0, 1.0],
                        "outline_mm": [
                            [[-1.0, -1.0, height], [1.0, -1.0, height]],
                            [[1.0, -1.0, height], [1.0, 1.0, height]],
                            [[1.0, 1.0, height], [-1.0, 1.0, height]],
                            [[-1.0, 1.0, height], [-1.0, -1.0, height]],
                        ],
                    }
                ]
            }
        }

    data.kernel["setups"] = {source["id"]: scene(0.0), consumer["id"]: scene(physical)}
    return data


def carried_native_source_plane_bundle(*, nominal=21.0055, source_grid=0.01, shift=0.0):
    """The receiving world box is oblique; only the exact source native plane is flat."""
    data = carried_native_datum_bundle(physical=nominal)
    source, consumer = data.plan["setups"][1], data.plan["setups"][-1]
    feature = consumer["zero"]["z"]["face"]
    data.features["frames"]["J3"]["origin"] = [0.0, 0.0, 0.0]
    source["zero"]["z"]["edge_mm"] = 22.0
    source["ops"][0]["to_z"] = nominal
    data.inventory["machines"]["lathe"]["resolution_mm"] = measured(source_grid)
    receiving = data.features["frames"][consumer["frame"]]
    receiving["origin"] = [-shift * v for v in receiving["z"]]
    consumer["zero"]["z"]["edge_mm"] = nominal + shift
    data.features["datums"] = {}
    data.kernel["setups"] = {
        source["id"]: {
            "revolved": {
                feature: {
                    "kinds": ["Plane"],
                    "z_mm": [nominal, nominal],
                    "radii_mm": [0.5, 1.0],
                    "end_radii_mm": [1.0, 1.0],
                    "end_faces": [{"z_mm": nominal, "normal_z": 1}],
                }
            }
        }
    }
    return data


def carried_rectangular_source_plane_bundle(*, nominal=21.0055, source_grid=0.01, shift=0.0):
    """Exact source/as-cut height with an actual axis-aligned 2x2 native rectangle."""
    data = carried_native_source_plane_bundle(nominal=nominal, source_grid=source_grid, shift=shift)
    source, receiver = data.plan["setups"][1], data.plan["setups"][-1]
    data.features["frames"][source["frame"]].update(
        origin=[0.0, 0.0, 0.0], x=[1.0, 0.0, 0.0], y=[0.0, 1.0, 0.0], z=[0.0, 0.0, 1.0]
    )
    data.features["frames"][receiver["frame"]].update(
        origin=[0.0, 0.0, -shift], x=[0.0, -1.0, 0.0], y=[1.0, 0.0, 0.0], z=[0.0, 0.0, 1.0]
    )
    data.kernel["faces"][0].update(
        bbox_mm=[-1.0, -1.0, nominal, 1.0, 1.0, nominal], fills_bbox=True, area_mm2=4.0
    )
    data.feature_definitions["hole"].update(at=[0.0, 0.0, nominal], axis=[0.0, 0.0, -1.0])
    feature = receiver["zero"]["z"]["face"]
    data.kernel["setups"][source["id"]]["revolved"][feature].update(
        radii_mm=[0.0, math.sqrt(2.0)], end_radii_mm=[math.sqrt(2.0), math.sqrt(2.0)]
    )
    return data


def carry_with_through_drill(*, aim_shift=0.0):
    data = carried_rectangular_stock_bundle()
    receiver = data.plan["setups"][-1]
    receiver["ops"].append(op(30, "ream", "hole", "reamer"))
    data.inventory["tools"]["reamer"] = {"kind": "reamer", "dia_mm": 0.9}
    data.kernel["ops"]["S8:30"] = {"claimed_indices": [3]}
    if aim_shift:
        data.feature_definitions["reference_axis"] = {
            "kind": "boss",
            "frame": "model",
            "at": [-1.0, 0.0, 0.0],
            "axis": [0.0, 0.0, 1.0],
        }
        data.feature_definitions["hole"].update(
            height_from="reference_axis", separation=[0.9, 1.5], precision={"separation": 3}
        )
        data.plan["aims"] = {
            "hole": {
                "requirement": "separation",
                "value_mm": 1.0 + aim_shift,
                "reason": "Synthetic located drill aim exercises its physical radial envelope",
            }
        }
    return data


def carried_bbox_mill_bundle(*, mode="axial", flipped=False):
    """Synthetic flat box with no native normal/radius fact to borrow."""
    data = carried_stock_bundle(journal=True)
    source, receiver = data.plan["setups"][1], data.plan["setups"][-1]
    source["machine"] = "mill"
    source["zero"]["z"]["tool"] = "mill"
    source["ops"] = source["ops"][:1]
    source["ops"][0]["tool"] = "mill"
    data.kernel["setups"] = {}
    detail = data.kernel["ops"][f"{source['id']}:10"]
    del detail["faced_side"]
    detail["approach"] = "axial" if mode == "cylinder" else mode
    receiver["ops"] = []
    if mode == "rotary":
        source["ops"][0]["approach"] = "rotary"
    elif mode == "cylinder":
        face = data.kernel["faces"][0]
        face.update(kind="Cylinder")
        face["bbox_mm"][5] = face["bbox_mm"][2] + 0.0005
    elif mode == "supplied":
        source["ops"] = []
        data.plan["stock"]["as_is_faces"] = ["#1/NORTH"]
    if flipped:
        data.features["frames"]["JH"].update(y=[1.0, 0.0, 0.0], z=[0.0, 0.0, 1.0])
        receiver["zero"]["z"]["edge_mm"] = -21.0
    return data


def measured_native_retouch_bundle(*, bounded=True):
    """Synthetic measured primary zero followed by an ordinary paper retouch."""
    data = carried_rectangular_stock_bundle()
    receiver = data.plan["setups"][-1]
    face = receiver["zero"]["z"]["face"]
    receiver["ops"] = receiver["ops"][:1]
    receiver["stock_state"] = {"top_z": 0.0, "top_feature": face}
    receiver["zero"]["z"].update(
        method="measure_then_set",
        gauge="mic",
        measure="Synthetic bench reference",
        offset_mm=1.0,
        retouch_after=[10],
    )
    if not bounded:
        del data.inventory["tools"]["centre"]["members"]["1"]["dia_mm"]
    return data


def carry_with_refaced_hole(*, bounded=True, later_setup=False):
    """Synthetic drill then whole re-face; a skim cannot restore lost material."""
    data = carried_rectangular_stock_bundle(journal=True)
    source, bond = data.plan["setups"][1:3]
    first_face = source["ops"][0]
    reface = {**first_face, "op": 20}
    source["ops"] = [first_face, op(15, "drill", "hole", "drill")]
    data.feature_definitions["hole"]["at"] = list(
        data.features["frames"][source["frame"]]["origin"]
    )
    data.kernel["ops"][f"{source['id']}:15"] = {
        "approach": "axial",
        "claimed_indices": [3],
    }
    if later_setup:
        finishing = {
            "id": "S4",
            "machine": "lathe",
            "frame": source["frame"],
            "stock_in": source["id"],
            "zero": lathe_zero([]),
            "ops": [reface],
        }
        # This separate bench registration remains valid independently of whether
        # the carried face still has a touch land; it is not a contact on that face.
        finishing["zero"]["z"].update(
            face="bench reference",
            edge_mm=0.0,
            method="measure_then_set",
            gauge="mic",
            measure="Synthetic independent bench registration",
            offset_mm=0.0,
        )
        data.plan["setups"].insert(2, finishing)
        bond["stock_in"] = [data.plan["setups"][0]["id"], finishing["id"]]
        data.kernel["setups"][finishing["id"]] = data.kernel["setups"][source["id"]]
        owner = finishing["id"]
    else:
        source["ops"].append(reface)
        owner = source["id"]
    data.kernel["ops"][f"{owner}:20"] = dict(data.kernel["ops"][f"{source['id']}:10"])
    if not bounded:
        del data.inventory["tools"]["drill"]["dia_mm"]
    return data


@pytest.mark.parametrize("journal", [False, True], ids=["S3-C4-to-S8-CH", "S2-J3-to-S9-JH"])
def test_a_whole_prepared_face_carries_through_bonding_in_its_new_frame(journal):
    data = carried_rectangular_stock_bundle(journal=journal)
    finding = evaluate(data)[-1]
    stands = 21.0 if journal else 0.0
    assert finding.status == "pass", finding.sentence
    row = finding.numbers["axes"]["z"]
    assert (row["edge_mm"], row["axis_set"], row["credited_faces"]) == (
        stands,
        stands,
        ["#1/NORTH"],
    )
    [touch] = finding.numbers["derived_touches"]
    assert (touch["edge_mm"], touch["z_axis_set"], touch["credited_faces"]) == (
        stands,
        stands,
        ["#1/NORTH"],
    )
    assert row.get("touch_exclusion_dia_mm", 0.0) == 0.0
    assert touch["touch_exclusion_dia_mm"] == pytest.approx(0.3)


@pytest.mark.parametrize("units", ["mm", "in"])
@pytest.mark.parametrize(
    ("prepared", "height_mm", "credited"),
    [("lower", 0.0, ["#1/NORTH"]), ("upper", 10.0, ["#2/SOUTH"])],
    ids=["lower-plus-z-uncredited-upper", "credited-maximum-member"],
)
def test_a_carried_multi_plane_face_selects_the_authored_edge_not_bbox_max(
    units, prepared, height_mm, credited
):
    data = carried_two_level_bundle(units=units, prepared=prepared)
    scale = 25.4 if units == "in" else 1.0
    finding = evaluate(data)[-1]
    assert finding.status == "pass", finding.sentence
    row = finding.numbers["axes"]["z"]
    assert row["edge_mm"] * scale == pytest.approx(height_mm, rel=0, abs=1e-6)
    assert row["native_edge_mm"] * scale == pytest.approx(height_mm, rel=0, abs=1e-6)
    assert row["credited_faces"] == credited
    [touch] = finding.numbers["derived_touches"]
    assert touch["credited_faces"] == credited
    assert touch["edge_mm"] * scale == pytest.approx(height_mm, rel=0, abs=1e-6)
    assert touch["z_axis_set"] == row["axis_set"]


@pytest.mark.parametrize("units", ["mm", "in"])
@pytest.mark.parametrize("offset_mm", [-1e-6, -5e-7, 0.0, 5e-7, 1e-6])
def test_multi_plane_edge_selection_uses_absolute_physical_length_tolerance(units, offset_mm):
    data = carried_two_level_bundle(units=units)
    scale = 25.4 if units == "in" else 1.0
    data.plan["setups"][-1]["zero"]["z"]["edge_mm"] = offset_mm / scale
    finding = evaluate(data)[-1]
    assert finding.status == "pass", finding.sentence
    row = finding.numbers["axes"]["z"]
    assert row["axis_set"] == 0.0 and row["credited_faces"] == ["#1/NORTH"]


@pytest.mark.parametrize("units", ["mm", "in"])
def test_distinct_nearby_native_plane_groups_are_ambiguous_not_nearest(units):
    data = carried_two_level_bundle(units=units, upper_mm=1.5e-6)
    scale = 25.4 if units == "in" else 1.0
    data.plan["setups"][-1]["zero"]["z"]["edge_mm"] = 6e-7 / scale
    finding = evaluate(data)[-1]
    assert finding.status == "unknown"
    assert "multiple distinct native plane groups" in finding.sentence
    row = finding.numbers["axes"]["z"]
    assert row["axis_set"] == "unknown" and "credited_faces" not in row


@pytest.mark.parametrize("units", ["mm", "in"])
def test_a_multi_plane_group_can_be_identified_by_its_proven_as_cut_height(units):
    data = carried_two_level_bundle(units=units, lower_mm=21.0055, upper_mm=30.0)
    scale = 25.4 if units == "in" else 1.0
    receiver = data.plan["setups"][-1]
    receiver["zero"]["z"]["edge_mm"] = 21.01 / scale
    receiver["ops"] = []
    finding = evaluate(data)[-1]
    assert finding.status == "pass", finding.sentence
    row = finding.numbers["axes"]["z"]
    assert row["edge_mm"] * scale == pytest.approx(21.01, rel=0, abs=1e-6)
    assert row["native_edge_mm"] * scale == pytest.approx(21.0055, rel=0, abs=1e-6)
    assert row["credited_faces"] == ["#1/NORTH"]


@pytest.mark.parametrize("units", ["mm", "in"])
def test_near_native_groups_are_not_deduplicated_when_physical_and_native_matches_overlap(units):
    data = carried_two_level_bundle(
        units=units, lower_mm=10.0000002, upper_mm=10.0000011, source_grid_mm=2e-6
    )
    scale = 25.4 if units == "in" else 1.0
    receiver = data.plan["setups"][-1]
    receiver["zero"]["z"]["edge_mm"] = 10.000002 / scale
    receiver["ops"] = []
    finding = evaluate(data)[-1]
    assert finding.status == "unknown"
    assert "multiple distinct native plane groups" in finding.sentence
    row = finding.numbers["axes"]["z"]
    assert row["axis_set"] == "unknown" and "credited_faces" not in row


@pytest.mark.parametrize("units", ["mm", "in"])
@pytest.mark.parametrize("edge_mm", [0.0, 5.0], ids=["native-match", "unresolved-physical-match"])
def test_an_eligible_multi_plane_producer_with_unknown_height_is_not_complete_no_match(
    units, edge_mm
):
    data = carried_two_level_bundle(units=units)
    scale = 25.4 if units == "in" else 1.0
    source, receiver = data.plan["setups"][1], data.plan["setups"][-1]
    source["zero"]["z"]["paper_mm"] = "unknown"
    receiver["zero"]["z"]["edge_mm"] = edge_mm / scale
    receiver["ops"] = []
    finding = evaluate(data)[-1]
    assert finding.status == "unknown"
    assert "incomplete eligible carried-plane height proof" in finding.sentence
    row = finding.numbers["axes"]["z"]
    assert row["axis_set"] == "unknown" and "credited_faces" not in row


@pytest.mark.parametrize("units", ["mm", "in"])
@pytest.mark.parametrize("debt", ["stock", "frame", "claims", "normal", "action", "coverage"])
def test_missing_relevant_multi_plane_proof_cannot_become_a_complete_height_error(units, debt):
    data = carried_two_level_bundle(units=units)
    scale = 25.4 if units == "in" else 1.0
    source, receiver = data.plan["setups"][1], data.plan["setups"][-1]
    receiver["zero"]["z"]["edge_mm"] = 5.0 / scale
    receiver["ops"] = []
    if debt == "stock":
        data.kernel["setups"][source["id"]]["stock_reason"] = "unresolved component stock"
    elif debt == "frame":
        source["frame"] = "unmapped-source-frame"
    elif debt == "claims":
        data.kernel["ops"][f"{source['id']}:10"]["claimed_indices"] = "unknown"
    elif debt == "normal":
        del data.kernel["setups"][source["id"]]["revolved"]
        del data.kernel["ops"][f"{source['id']}:10"]["faced_side"]
    elif debt == "action":
        source["ops"][0]["do"] = "unknown"
    elif debt == "coverage":
        source["ops"][0]["stock_removal_bounds"] = {
            "x": "unknown",
            "y": [-4.0 / scale, 4.0 / scale],
            "z": [-1.0 / scale, 1.0 / scale],
        }
    finding = evaluate(data)[-1]
    assert finding.status == "unknown"
    assert "incomplete eligible carried-plane height proof" in finding.sentence
    row = finding.numbers["axes"]["z"]
    assert row["axis_set"] == "unknown" and "credited_faces" not in row


@pytest.mark.parametrize("units", ["mm", "in"])
@pytest.mark.parametrize("edge_mm", [-2e-6, 2e-6, 5.0, 10.01])
def test_no_matching_known_multi_plane_height_is_an_error_without_plane_borrowing(units, edge_mm):
    data = carried_two_level_bundle(units=units)
    scale = 25.4 if units == "in" else 1.0
    edge = edge_mm / scale
    data.plan["setups"][-1]["zero"]["z"]["edge_mm"] = edge
    expected_candidates = f"known native heights are 0, {10.0 / scale:g}"
    finding = evaluate(data)[-1]
    assert finding.status == "error"
    assert expected_candidates in finding.sentence
    assert f"edge {edge:g}" in finding.sentence and "known native heights" in finding.sentence
    assert "matches no native plane" in finding.sentence
    row = finding.numbers["axes"]["z"]
    assert row["axis_set"] == "unknown" and "credited_faces" not in row
    assert all("credited_faces" not in touch for touch in finding.numbers["derived_touches"])


def test_a_selected_native_plane_group_credits_only_its_exact_coplanar_refs():
    data = carried_two_level_bundle()
    source, receiver = data.plan["setups"][1], data.plan["setups"][-1]
    feature = receiver["zero"]["z"]["face"]
    patch = "#5/LOWER_PATCH"
    data.feature_definitions[feature]["faces"] = [patch, "#2/SOUTH", "#1/NORTH"]
    data.kernel["mapping"][patch] = 4
    data.kernel["features"][feature] = [4, 1, 0]
    data.kernel["faces"].append(
        {"index": 4, "kind": "Plane", "bbox_mm": [3.5, -1.0, 0.0, 4.5, 1.0, 0.0]}
    )
    data.kernel["setups"][source["id"]]["revolved"][feature]["end_faces"].append(
        {"z_mm": 0.0, "normal_z": 1}
    )
    source["ops"][0]["faces"] = [patch, "#1/NORTH"]
    data.kernel["ops"][f"{source['id']}:10"]["claimed_indices"] = [4, 0]
    receiver["ops"] = []
    finding = evaluate(data)[-1]
    assert finding.status == "pass", finding.sentence
    row = finding.numbers["axes"]["z"]
    assert row["axis_set"] == 0.0 and row["credited_faces"] == [patch, "#1/NORTH"]


@pytest.mark.parametrize(
    "debt", ["missing-native", "missing-normal", "unfaced-member", "wrong-normal", "oblique-gap"]
)
def test_a_matching_multi_plane_member_still_needs_its_own_carried_proof(debt):
    data = carried_two_level_bundle()
    source, receiver = data.plan["setups"][1], data.plan["setups"][-1]
    feature = receiver["zero"]["z"]["face"]
    if debt == "missing-native":
        del data.kernel["faces"][0]["bbox_mm"]
    elif debt == "missing-normal":
        del data.kernel["setups"][source["id"]]["revolved"]
        del data.kernel["ops"][f"{source['id']}:10"]["faced_side"]
    elif debt == "unfaced-member":
        receiver["zero"]["z"]["edge_mm"] = 10.0
    elif debt == "wrong-normal":
        data.kernel["setups"][source["id"]]["revolved"][feature]["end_faces"][0]["normal_z"] = -1
        data.kernel["ops"][f"{source['id']}:10"]["faced_side"] = -1
    elif debt == "oblique-gap":
        c, s = math.cos(math.radians(12.5)), math.sin(math.radians(12.5))
        data.features["frames"]["oblique"] = {
            "origin": [0.0, 0.0, 0.0],
            "x": [c, 0.0, -s],
            "y": [0.0, 1.0, 0.0],
            "z": [s, 0.0, c],
            "binding": "nominal",
        }
        receiver["frame"] = "oblique"
        data.kernel["setups"] = {}
    finding = evaluate(data)[-1]
    assert finding.status == "unknown"
    row = finding.numbers["axes"]["z"]
    assert row["axis_set"] == "unknown" and "credited_faces" not in row


@pytest.mark.parametrize(
    "debt",
    [
        "overlap",
        "unknown-bounds",
        "unknown-claims",
        "unknown-stock",
        "broken-route",
        "absent-producer",
        "hand-file",
    ],
)
def test_an_unproven_or_cut_away_prepared_face_never_carries(debt):
    data = carried_stock_bundle()
    source, bond = data.plan["setups"][1:3]
    if debt == "broken-route":
        bond["stock_in"] = "missing-setup"
    elif debt == "absent-producer":
        source["ops"] = source["ops"][1:]
    elif debt == "hand-file":
        bond["ops"].append(op(20, "file_to_line", "crank_boss_faces", "unknown"))
        data.kernel["ops"]["S7:20"] = {"approach": "hand", "claimed_indices": [0]}
    elif debt == "unknown-stock":
        data.kernel["setups"] = {source["id"]: {"stock_out_reason": "unresolved cut"}}
    else:
        cut = op(20, "face", "spigot", "mill", to_z=0.0)
        data.kernel["ops"]["S7:20"] = {"claimed_indices": [2]}
        if debt == "unknown-claims":
            data.kernel["ops"]["S7:20"]["claimed_indices"] = "unknown"
        else:
            cut["stock_removal_bounds"] = {
                "x": "unknown" if debt == "unknown-bounds" else [-2.0, 2.0],
                "y": [-2.0, 2.0],
                "z": [-22.0, -20.0],
            }
        bond["machine"] = "mill"
        bond["ops"].append(cut)
    finding = evaluate(data)[-1]
    assert finding.status == "unknown"
    row = finding.numbers["axes"]["z"]
    assert row["axis_set"] == "unknown" and "credited_faces" not in row
    assert all(t["z_axis_set"] == "unknown" for t in finding.numbers["derived_touches"])


@pytest.mark.parametrize("side", ["-z", "unknown"])
def test_a_carried_plane_requires_an_above_touch(side):
    data = carried_stock_bundle()
    data.plan["setups"][-1]["zero"]["z"]["from"] = side
    finding = evaluate(data)[-1]
    assert finding.status == "unknown"
    assert finding.numbers["axes"]["z"]["axis_set"] == "unknown"


def test_a_carried_plane_keeps_its_physical_edge_comparison():
    data = carried_stock_bundle(journal=True)
    data.plan["setups"][-1]["zero"]["z"]["edge_mm"] = 21.01
    finding = evaluate(data)[-1]
    assert finding.status == "error"
    assert finding.numbers["axes"]["z"]["axis_set"] == 21.0
    assert "stands at 21" in finding.sentence


def test_a_component_supplied_native_face_needs_no_new_facing_credit():
    data = carried_supplied_component_bundle()
    source = data.plan["setups"][1]
    assert source["stock_in"] == "stock.sleeve" and source["ops"] == []
    assert data.plan["setups"][-1]["zero"]["z"]["from"] == "+z"
    finding = evaluate(data)[-1]
    assert finding.status == "pass", finding.sentence
    row = finding.numbers["axes"]["z"]
    assert row["axis_set"] == 21.0 and row["credited_faces"] == ["#1/NORTH"]
    [touch] = finding.numbers["derived_touches"]
    assert touch["z_axis_set"] == 21.0 and touch["credited_faces"] == ["#1/NORTH"]
    assert touch["touch_exclusion_dia_mm"] == pytest.approx(0.3)


@pytest.mark.parametrize("side", ["-z", "unknown"])
def test_a_component_supplied_plane_still_requires_an_above_touch(side):
    data = carried_supplied_component_bundle()
    data.plan["setups"][-1]["zero"]["z"]["from"] = side
    finding = evaluate(data)[-1]
    assert finding.status == "unknown"
    row = finding.numbers["axes"]["z"]
    assert row["axis_set"] == "unknown" and "credited_faces" not in row


def test_a_plain_stock_supplied_native_face_keeps_its_existing_seed_behavior():
    data = carried_rectangular_stock_bundle()
    source, receiver = data.plan["setups"][1], data.plan["setups"][-1]
    data.plan["stock"] = {"as_is_faces": ["#1/NORTH", "#2/SOUTH"]}
    source.update(stock_in="stock", ops=source["ops"][1:])
    receiver["stock_in"] = source["id"]
    data.plan["setups"] = [source, receiver]
    finding = evaluate(data)[-1]
    assert finding.status == "pass", finding.sentence
    assert finding.numbers["axes"]["z"]["axis_set"] == 0.0


def test_a_component_bottom_face_can_flip_rigidly_into_receiving_plus_z():
    data = carried_supplied_component_bundle()
    source, receiver = data.plan["setups"][1], data.plan["setups"][-1]
    feature = receiver["zero"]["z"]["face"]
    data.features["frames"][source["frame"]].update(y=[0.0, 1.0, 0.0], z=[0.0, 0.0, 1.0])
    source["stock_state"] = {"bottom_z": 0.0, "bottom_feature": feature}
    facts = data.kernel["setups"][source["id"]]
    facts["stock_faces_mm"][feature] = {"down": {"face_z": 0.0, "stock_z": 0.0}}
    facts["revolved"][feature]["end_faces"][0]["normal_z"] = -1
    facts["render_scene"]["datums"][0]["normal"] = [0.0, 0.0, -1.0]
    finding = evaluate(data)[-1]
    assert finding.status == "pass", finding.sentence
    assert finding.numbers["axes"]["z"]["axis_set"] == 21.0
    [touch] = finding.numbers["derived_touches"]
    assert touch["z_axis_set"] == 21.0 and touch["credited_faces"] == ["#1/NORTH"]


@pytest.mark.parametrize(
    "debt",
    [
        "not-as-is",
        "unnamed-root",
        "missing-pre-cut",
        "missing-stock-height",
        "pre-cut-reason",
        "missing-source-plane",
        "wrong-source-plane",
        "missing-mapping",
        "missing-datum",
        "wrong-datum-label",
        "wrong-datum-feature",
        "wrong-datum-height",
        "wrong-datum-normal",
        "wrong-stock-side",
        "stock-debt",
        "stock-out-debt",
    ],
)
def test_a_component_as_is_seed_requires_its_own_existing_native_proofs(debt):
    data = carried_supplied_component_bundle()
    source, receiver = data.plan["setups"][1], data.plan["setups"][-1]
    feature = receiver["zero"]["z"]["face"]
    facts = data.kernel["setups"][source["id"]]
    if debt == "not-as-is":
        data.plan["stock"]["as_is_faces"] = []
    elif debt == "unnamed-root":
        source["stock_state"] = {}
    elif debt == "missing-pre-cut":
        del facts["stock_faces_mm"]
    elif debt == "missing-stock-height":
        del facts["stock_faces_mm"][feature]["up"]["stock_z"]
    elif debt == "pre-cut-reason":
        facts["stock_faces_mm"][feature]["up"] = {
            "reason": f"the entering stock does not carry the face of {feature}"
        }
    elif debt == "missing-source-plane":
        del facts["revolved"]
    elif debt == "wrong-source-plane":
        plane = facts["revolved"][feature]
        plane["z_mm"] = [0.01, 0.01]
        plane["end_faces"][0]["z_mm"] = 0.01
    elif debt == "missing-mapping":
        del data.kernel["mapping"]["#1/NORTH"]
    elif debt == "missing-datum":
        del facts["render_scene"]
    elif debt == "wrong-datum-label":
        facts["render_scene"]["datums"][0]["label"] = "DATUM B: another surface"
    elif debt == "wrong-datum-feature":
        data.features["datums"]["D"]["feature"] = "hole"
    elif debt == "wrong-datum-height":
        for edge in facts["render_scene"]["datums"][0]["outline_mm"]:
            for point in edge:
                point[2] = 0.01
    elif debt == "wrong-datum-normal":
        facts["render_scene"]["datums"][0]["normal"] = [0.0, 0.0, -1.0]
    elif debt == "wrong-stock-side":
        source["stock_state"] = {"bottom_z": 0.0, "bottom_feature": feature}
    elif debt == "stock-debt":
        facts["stock_reason"] = "unresolved entering sleeve"
    elif debt == "stock-out-debt":
        facts["stock_out_reason"] = "unresolved retained sleeve"
    finding = evaluate(data)[-1]
    assert finding.status == "unknown"
    assert "stock.sleeve" in finding.sentence and feature in finding.sentence
    row = finding.numbers["axes"]["z"]
    assert row["axis_set"] == "unknown" and "credited_faces" not in row
    [touch] = finding.numbers["derived_touches"]
    assert touch["z_axis_set"] == "unknown" and "credited_faces" not in touch


@pytest.mark.parametrize(
    ("face_z", "stock_z", "status"),
    [
        (0.0, 0.0, "pass"),
        (0.0, 5e-7, "pass"),
        (5e-7, 0.0, "pass"),
        (0.0, 2e-6, "unknown"),
        (2e-6, 0.0, "unknown"),
        (0.01, 0.01, "unknown"),
        (math.nan, 0.0, "unknown"),
        (math.inf, 0.0, "unknown"),
        (0.0, math.nan, "unknown"),
        (0.0, -math.inf, "unknown"),
    ],
)
def test_component_pre_cut_heights_use_finite_absolute_physical_length_equality(
    face_z, stock_z, status
):
    data = carried_supplied_component_bundle()
    source, receiver = data.plan["setups"][1], data.plan["setups"][-1]
    feature = receiver["zero"]["z"]["face"]
    data.kernel["setups"][source["id"]]["stock_faces_mm"][feature]["up"].update(
        face_z=face_z, stock_z=stock_z
    )
    finding = evaluate(data)[-1]
    assert finding.status == status, finding.sentence
    row = finding.numbers["axes"]["z"]
    assert row["axis_set"] == (21.0 if status == "pass" else "unknown")
    if status == "unknown":
        assert "stock.sleeve" in finding.sentence and feature in finding.sentence
        assert "credited_faces" not in row


@pytest.mark.parametrize("named", [False, True], ids=["no-candidate", "wrong-component"])
def test_a_body_route_cannot_borrow_the_sleeves_global_as_is_face(named):
    data = carried_supplied_component_bundle()
    body, source, _, receiver = data.plan["setups"]
    feature = receiver["zero"]["z"]["face"]
    receiver["stock_in"] = body["id"]
    if named:
        body["stock_state"] = {"bottom_z": -21.0, "bottom_feature": feature}
        data.kernel["setups"][body["id"]] = {
            "revolved": data.kernel["setups"][source["id"]]["revolved"],
            "stock_faces_mm": {
                feature: {"reason": f"the entering body does not carry the face of {feature}"}
            },
        }
    finding = evaluate(data)[-1]
    assert finding.status == "unknown"
    assert "stock.body" in finding.sentence and feature in finding.sentence
    row = finding.numbers["axes"]["z"]
    assert row["axis_set"] == "unknown" and "credited_faces" not in row
    [touch] = finding.numbers["derived_touches"]
    assert touch["z_axis_set"] == "unknown" and "credited_faces" not in touch


def test_a_joined_union_is_not_a_component_local_as_is_stock_root():
    data = carried_supplied_component_bundle()
    source, receiver = data.plan["setups"][1], data.plan["setups"][-1]
    source["stock_in"] = ["stock.body", "stock.sleeve"]
    receiver["stock_in"] = source["id"]
    data.plan["setups"] = [source, receiver]
    finding = evaluate(data)[-1]
    assert finding.status == "unknown"
    assert "stock.sleeve" in finding.sentence and "single-component" in finding.sentence
    assert "credited_faces" not in finding.numbers["axes"]["z"]


def test_an_undeclared_stock_prefix_cannot_seed_a_component_face():
    data = carried_supplied_component_bundle()
    data.plan["setups"][1]["stock_in"] = "stock.sleeve-lookalike"
    finding = evaluate(data)[-1]
    assert finding.status == "unknown"
    assert "stock.sleeve-lookalike" in finding.sentence
    assert "credited_faces" not in finding.numbers["axes"]["z"]


def test_partial_component_carry_at_the_same_z_is_not_a_whole_supplied_datum():
    data = carried_supplied_component_bundle()
    source, receiver = data.plan["setups"][1], data.plan["setups"][-1]
    feature = receiver["zero"]["z"]["face"]
    facts = data.kernel["setups"][source["id"]]
    assert facts["stock_faces_mm"][feature]["up"] == {"face_z": 0.0, "stock_z": 0.0}
    # Native stock_faces_mm retains same-Z proof for a partly carried face.
    # A datum on the later joined/received solid cannot replace the root's
    # missing on-surface datum, which requires the whole named surface.
    datum = facts["render_scene"]["datums"][0]
    facts["render_scene"]["datums"] = []
    data.kernel["setups"][receiver["id"]] = {
        "render_scene": {
            "datums": [
                {
                    **datum,
                    "outline_mm": [
                        [[p[0], p[1], 21.0] for p in edge] for edge in datum["outline_mm"]
                    ],
                }
            ]
        }
    }
    finding = evaluate(data)[-1]
    assert finding.status == "unknown"
    assert "stock.sleeve" in finding.sentence and "on-surface datum" in finding.sentence
    row = finding.numbers["axes"]["z"]
    assert row["axis_set"] == "unknown" and "credited_faces" not in row


@pytest.mark.parametrize(("paper", "typed"), [(0.0, 21.005), (0.0024, 21.005)])
def test_a_carried_native_datum_types_height_plus_paper_once_on_the_safe_down_grid(paper, typed):
    data = carried_native_datum_bundle()
    data.plan["setups"][-1]["zero"]["z"]["paper_mm"] = paper
    finding = evaluate(data)[-1]
    assert finding.status == "unknown", finding.sentence
    row = finding.numbers["axes"]["z"]
    desired = 21.0055 + paper
    assert row["edge_mm"] == pytest.approx(21.0055, rel=0, abs=1e-9)
    assert row["axis_set"] == typed
    assert row["setting_residual_mm"] == pytest.approx(desired - typed)
    assert row["check_reading"] == pytest.approx(typed + 5.0)
    [touch] = finding.numbers["derived_touches"]
    assert touch["z_axis_set"] == "unknown" and "credited_faces" not in touch
    assert "no proven usable touch land" in finding.sentence


@pytest.mark.parametrize(
    "debt",
    [
        "missing",
        "wrong-feature",
        "wrong-label",
        "flipped-normal",
        "scaled-normal",
        "nonflat",
        "nonfinite",
    ],
)
def test_an_oblique_carried_plane_cannot_borrow_or_guess_its_native_datum(debt):
    data = carried_native_datum_bundle()
    if debt == "wrong-feature":
        data.features["datums"]["D"]["feature"] = "hole"
    for setup in data.kernel["setups"].values():
        datum = setup["render_scene"]["datums"][0]
        if debt == "missing":
            del setup["render_scene"]["datums"]
        elif debt == "wrong-label":
            datum["label"] = "DATUM B: some other surface"
        elif debt == "flipped-normal":
            datum["normal"] = [0.0, 0.0, -1.0]
        elif debt == "scaled-normal":
            datum["normal"] = [0.0, 0.0, 2.0]
        elif debt == "nonflat":
            datum["outline_mm"][0][0][2] += 0.01
        elif debt == "nonfinite":
            datum["outline_mm"][0][0][2] = math.inf
    finding = evaluate(data)[-1]
    assert finding.status == "unknown"
    assert finding.numbers["axes"]["z"]["axis_set"] == "unknown"
    assert "credited_faces" not in finding.numbers["axes"]["z"]


def test_a_known_outward_face_flipped_underneath_the_receiving_setup_cannot_carry():
    data = carried_stock_bundle(journal=True)
    data.features["frames"]["JH"].update(y=[1.0, 0.0, 0.0], z=[0.0, 0.0, 1.0])
    data.plan["setups"][-1]["zero"]["z"]["edge_mm"] = -21.0
    finding = evaluate(data)[-1]
    assert finding.status == "unknown"
    assert finding.numbers["axes"]["z"]["axis_set"] == "unknown"


def test_a_listed_retouch_checks_intervening_cuts_of_a_carried_stock_top():
    data = carried_stock_bundle()
    setup = data.plan["setups"][-1]
    face = setup["zero"]["z"]["face"]
    setup["stock_state"] = {"top_z": 0.0, "top_feature": face}
    setup["zero"]["z"].update(face="top", tool="mill", retouch_after=[10])
    setup["ops"][0] = op(
        10,
        "face",
        "spigot",
        "mill",
        to_z=0.0,
        stock_removal_bounds={"x": [-2.0, 2.0], "y": [-2.0, 2.0], "z": [-1.0, 1.0]},
    )
    data.kernel["ops"]["S8:10"] = {"claimed_indices": [2]}
    finding = evaluate(data)[-1]
    assert finding.status == "unknown"
    assert finding.numbers["axes"]["z"]["axis_set"] == 0.0
    [retouch] = finding.numbers["retouch"]
    assert retouch["axis_set"] == "unknown"
    assert "credited_faces" not in retouch


@pytest.mark.parametrize("same_frame", [False, True])
def test_an_exact_source_native_plane_carries_without_an_oblique_bbox_or_datum_guess(same_frame):
    data = carried_native_source_plane_bundle()
    if same_frame:
        data.plan["setups"][-1]["frame"] = "J3"
    finding = evaluate(data)[-1]
    assert finding.status == "unknown", finding.sentence
    row = finding.numbers["axes"]["z"]
    assert row["credited_faces"] == ["#1/NORTH"]
    assert row["edge_mm"] == pytest.approx(21.01)
    assert row["native_edge_mm"] == pytest.approx(21.0055)
    assert row["axis_set"] == 21.01
    assert row["setting_residual_mm"] == 0.0
    [touch] = finding.numbers["derived_touches"]
    assert touch["z_axis_set"] == "unknown" and "credited_faces" not in touch
    assert "no proven usable touch land" in finding.sentence


@pytest.mark.parametrize(
    ("nominal", "source_grid", "receiving_grid", "shift", "physical", "typed"),
    [
        (21.0075, 0.0005, 0.005, 0.0, 21.0075, 21.005),
        (-21.0075, 0.0005, 0.005, 0.0, -21.0075, -21.01),
        (21.0035, 0.005, 0.01, 0.0, 21.005, 21.0),
        (21.0055, 0.01, 0.005, -0.0025, 21.0075, 21.005),
        (21.009999998, 0.000000001, 0.005, 0.0, 21.009999998, 21.005),
        (-21.010000002, 0.000000001, 0.005, 0.0, -21.010000002, -21.015),
    ],
    ids=[
        "half-step",
        "negative-half-step",
        "coarser-receiving-grid",
        "oblique-rigid-offset",
        "positive-near-grid",
        "negative-near-grid",
    ],
)
@pytest.mark.parametrize("route", ["primary-derived", "explicit-touch", "listed-retouch"])
@pytest.mark.parametrize("topology", ["filled-rectangle", "unproved-oblique-outline"])
def test_every_carried_contact_is_safe_down_from_the_producer_as_cut_height(
    nominal, source_grid, receiving_grid, shift, physical, typed, route, topology
):
    fixture = (
        carried_rectangular_source_plane_bundle
        if topology == "filled-rectangle"
        else carried_native_source_plane_bundle
    )
    data = fixture(nominal=nominal, source_grid=source_grid, shift=shift)
    receiver = data.plan["setups"][-1]
    zero = receiver["zero"]["z"]
    face = zero["face"]
    data.inventory["machines"]["mill"]["resolution_mm"] = measured(receiving_grid)
    if route == "explicit-touch":
        receiver["zero"]["tool_touches"] = [
            {
                "tool": "drill",
                "z_face": face,
                "edge_mm": nominal + shift,
                "paper_mm": 0.0,
                "method": "touch_then_set",
                "before_ops": [20],
            }
        ]
    elif route == "listed-retouch":
        receiver["stock_state"] = {"top_z": nominal + shift, "top_feature": face}
        zero.update(face="top", retouch_after=[10])
    finding = evaluate(data)[-1]
    assert finding.status == ("pass" if topology == "filled-rectangle" else "unknown"), (
        finding.sentence
    )
    primary = finding.numbers["axes"]["z"]
    row = (
        finding.numbers["derived_touches"][0]
        if route == "primary-derived"
        else finding.numbers["tool_touches"][0]
        if route == "explicit-touch"
        else finding.numbers["retouch"][0]
    )
    setting = row["axis_set" if route == "listed-retouch" else "z_axis_set"]
    assert primary["edge_mm"] == pytest.approx(physical)
    assert primary["native_edge_mm"] == pytest.approx(nominal + shift)
    assert primary["axis_set"] == typed
    if topology == "filled-rectangle":
        assert setting == typed
        assert row["edge_mm" if route != "listed-retouch" else "top_z"] == pytest.approx(physical)
    else:
        assert setting == "unknown" and "credited_faces" not in row
        assert "no proven usable touch land" in finding.sentence
        assert "https://github.com/pedropaulovc/prechips/issues/208" in finding.sentence
    residual = physical - typed
    assert residual >= 0
    assert primary["setting_residual_mm"] == pytest.approx(residual)
    if topology == "filled-rectangle":
        assert row["setting_residual_mm"] == pytest.approx(residual)
    assert primary["check_reading"] == pytest.approx(typed + 5.0)
    assert primary["mirrored_reading"] == pytest.approx(typed - 5.0)
    # The authored native nominal is valid provenance, but typing high would
    # move every fixed DRO tip below its authored physical Z by that error.
    authored_tip = physical - 2.0
    reached = authored_tip + residual
    assert reached >= authored_tip


def test_same_setup_and_remounted_touches_agree_on_one_producer_as_cut_face():
    data = carried_rectangular_source_plane_bundle()
    source, receiver = data.plan["setups"][1], data.plan["setups"][-1]
    face = receiver["zero"]["z"]["face"]
    source["ops"].append(op(20, "fit", face, "turner"))
    source["zero"]["tool_touches"] = [
        {
            "tool": "turner",
            "x_method": "trial_cut_measure",
            "gauge": "mic",
            "z_face": face,
            "edge_mm": 21.0055,
            "paper_mm": 0.0,
            "method": "touch_then_set",
            "before_ops": [20],
        }
    ]
    findings = evaluate(data)
    made = findings[1].numbers["tool_touches"][0]
    carried = findings[-1].numbers["axes"]["z"]
    assert findings[1].status == findings[-1].status == "pass"
    assert made["edge_mm"] == carried["edge_mm"] == pytest.approx(21.01)
    assert made["z_axis_set"] == carried["axis_set"] == 21.01
    assert carried["setting_residual_mm"] == 0.0


@pytest.mark.parametrize("debt", ["unknown-touch", "raw-cut-mismatch", "partial-cut"])
def test_unknown_or_nonmatching_producer_never_supplies_a_nominal_as_cut_height(debt):
    data = carried_native_source_plane_bundle()
    source = data.plan["setups"][1]
    if debt == "unknown-touch":
        source["zero"]["z"]["paper_mm"] = "unknown"
    elif debt == "raw-cut-mismatch":
        source["ops"][0]["to_z"] = 21.02
    else:
        source["ops"][0]["stock_removal_bounds"] = {
            "x": [-1.0, 0.0],
            "y": [-1.0, 1.0],
            "z": [21.0, 22.0],
        }
    finding = evaluate(data)[-1]
    assert finding.status == "unknown"
    assert finding.numbers["axes"]["z"]["axis_set"] == "unknown"
    assert "credited_faces" not in finding.numbers["axes"]["z"]


def test_keep_out_bounds_are_compared_with_the_producer_as_cut_plane_not_its_native_nominal():
    data = carried_rectangular_stock_bundle(journal=True)
    source, bond, receiver = data.plan["setups"][1:]
    source["ops"] = source["ops"][:1]
    source["ops"][0]["to_z"] = 0.0055
    data.inventory["machines"]["lathe"]["resolution_mm"] = measured(0.01)
    data.kernel["faces"][0]["bbox_mm"][2] = -21.0055
    data.kernel["faces"][0]["bbox_mm"][5] = -21.0055
    fact = data.kernel["setups"][source["id"]]["revolved"][receiver["zero"]["z"]["face"]]
    fact.update(z_mm=[0.0055, 0.0055], end_faces=[{"z_mm": 0.0055, "normal_z": 1}])
    receiver["zero"]["z"]["edge_mm"] = 21.0055
    # This cut spans physical Z21.010 but not the native Z21.0055 box, even
    # with LENGTH tolerance. Native-only disjointness must not credit survival.
    bond.update(machine="mill", frame="JH")
    bond["ops"].append(
        op(
            20,
            "face",
            "spigot",
            "mill",
            to_z=21.01,
            stock_removal_bounds={"x": [-2.0, 2.0], "y": [-2.0, 2.0], "z": [21.009, 21.011]},
        )
    )
    data.kernel["ops"]["S7:20"] = {"approach": "axial", "claimed_indices": [2], "faced_side": 1}
    finding = evaluate(data)[-1]
    assert finding.status == "unknown"
    assert finding.numbers["axes"]["z"]["axis_set"] == "unknown"
    assert "credited_faces" not in finding.numbers["axes"]["z"]


@pytest.mark.parametrize("debt", ["missing", "wrong-binding", "flipped", "wrong-height"])
def test_source_native_plane_evidence_cannot_be_missing_misbound_flipped_or_wrong_height(debt):
    data = carried_native_source_plane_bundle()
    if debt == "missing":
        data.kernel["setups"] = {}
    elif debt == "wrong-binding":
        data.kernel["features"]["cone_boss_north_face"] = [3]
    elif debt == "flipped":
        frame = data.features["frames"]["JH"]
        frame["z"] = [-v for v in frame["z"]]
        frame["y"] = [-v for v in frame["y"]]
    else:
        data.plan["setups"][-1]["zero"]["z"]["edge_mm"] = 21.02
    finding = evaluate(data)[-1]
    assert finding.status == ("error" if debt == "wrong-height" else "unknown")
    if debt == "wrong-height":
        assert finding.numbers["axes"]["z"]["axis_set"] == 21.01
        assert "21.01" in finding.sentence and "21.02" in finding.sentence
    else:
        assert finding.numbers["axes"]["z"]["axis_set"] == "unknown"
        assert "credited_faces" not in finding.numbers["axes"]["z"]


@pytest.mark.parametrize("aim_shift", [0.0, 0.185])
def test_axial_plunges_leave_a_proven_plane_with_a_cumulative_touch_exclusion(aim_shift):
    data = carry_with_through_drill(aim_shift=aim_shift)
    finding = evaluate(data)[-1]
    assert finding.status == ("unknown" if aim_shift else "pass"), finding.sentence
    before = {row["before_ops"][0]: row for row in finding.numbers["derived_touches"]}
    assert before[20]["touch_exclusion_dia_mm"] == pytest.approx(0.3 + 2 * aim_shift)
    assert before[20]["credited_faces"] == ["#1/NORTH"]
    if aim_shift:
        from prechips.rules.zero_recipe.native import _axial_cut_footprint

        receiver = data.plan["setups"][-1]
        point, radius = _axial_cut_footprint(data, receiver, receiver["ops"][1])
        assert 2 * (radius + math.hypot(*point[:2])) == pytest.approx(1.17)
        assert before[30]["z_axis_set"] == "unknown" and "credited_faces" not in before[30]
        assert "no proven usable touch land" in finding.sentence
    else:
        assert before[30]["touch_exclusion_dia_mm"] == pytest.approx(0.8)
        assert before[30]["credited_faces"] == ["#1/NORTH"]


@pytest.mark.parametrize(
    ("reach", "status"),
    [(0.15, "pass"), (0.49999, "pass"), (0.499998, "unknown"), (0.5, "unknown")],
)
def test_a_genuine_filled_rectangle_needs_the_existing_half_mm_square_witness(reach, status):
    data = carried_rectangular_stock_bundle()
    receiver = data.plan["setups"][-1]
    receiver["zero"]["z"]["tool"] = "drill"
    receiver["ops"] = [op(10, "drill", "hole", "drill"), op(20, "ream", "hole", "reamer")]
    data.inventory["tools"]["drill"]["dia_mm"] = 2 * reach
    data.inventory["tools"]["reamer"] = {"kind": "reamer", "dia_mm": 0.9}
    finding = evaluate(data)[-1]
    assert finding.status == status, finding.sentence
    assert finding.numbers["axes"]["z"]["axis_set"] == 0.0
    [touch] = finding.numbers["derived_touches"]
    if status == "pass":
        assert touch["z_axis_set"] == 0.0 and touch["credited_faces"] == ["#1/NORTH"]
        assert touch["touch_exclusion_dia_mm"] == pytest.approx(2 * reach)
    else:
        assert touch["z_axis_set"] == "unknown" and "credited_faces" not in touch
        assert "no proven usable touch land" in finding.sentence
        assert "S8 op 10" in finding.sentence and "0.5 mm square" in finding.sentence


def test_rectangular_touch_land_keeps_the_union_of_prior_and_smaller_plunge_exclusions():
    data = carried_rectangular_stock_bundle()
    receiver = data.plan["setups"][-1]
    receiver["zero"]["z"]["tool"] = "drill"
    receiver["ops"] = [
        op(10, "drill", "hole", "drill"),
        op(20, "spot", "hole", "centre/1", depth_mm=0.15),
        op(30, "ream", "hole", "reamer"),
    ]
    data.inventory["tools"]["reamer"] = {"kind": "reamer", "dia_mm": 0.9}
    data.kernel["ops"]["S8:30"] = {"claimed_indices": [3]}
    finding = evaluate(data)[-1]
    assert finding.status == "pass", finding.sentence
    before = {row["before_ops"][0]: row for row in finding.numbers["derived_touches"]}
    assert before[20]["touch_exclusion_dia_mm"] == pytest.approx(0.8)
    assert before[30]["touch_exclusion_dia_mm"] == pytest.approx(0.8)
    assert all(row["credited_faces"] == ["#1/NORTH"] for row in before.values())


@pytest.mark.parametrize(
    ("inner", "reach"),
    [(0.0, 0.15), (5.0, 0.15), (9.999, 0.15), (0.0, 9.999)],
    ids=["ample-round", "ample-annular-extrema", "original-tiny-annulus", "plunge-tiny-annulus"],
)
@pytest.mark.parametrize("shape_fact", [False, None], ids=["nonrectangular", "missing-shape"])
def test_radial_extrema_never_prove_usable_round_or_holed_touch_land(inner, reach, shape_fact):
    data = carried_stock_bundle()
    source, receiver = data.plan["setups"][1], data.plan["setups"][-1]
    source["ops"] = source["ops"][:1]
    fact = data.kernel["setups"][source["id"]]["revolved"]["crank_boss_faces"]
    fact.update(radii_mm=[inner, 10.0], end_radii_mm=[10.0, 10.0])
    data.kernel["faces"][0].update(
        bbox_mm=[-10.0, -10.0, -21.3753, 10.0, 10.0, -21.3753],
        area_mm2=math.pi * (100.0 - inner * inner),
        fills_bbox=False,
    )
    if shape_fact is None:
        del data.kernel["faces"][0]["fills_bbox"]
    receiver["zero"]["z"]["tool"] = "drill"
    receiver["ops"] = [op(10, "drill", "hole", "drill"), op(20, "ream", "hole", "reamer")]
    data.inventory["tools"]["drill"]["dia_mm"] = 2 * reach
    data.inventory["tools"]["reamer"] = {"kind": "reamer", "dia_mm": 0.9}
    from prechips.rules.zero_recipe.native import _axial_cut_footprint

    point, radius = _axial_cut_footprint(data, receiver, receiver["ops"][0])
    assert point[:2] == [0.0, 0.0]
    assert radius == pytest.approx(reach)
    finding = evaluate(data)[-1]
    assert finding.status == "unknown"
    assert finding.numbers["axes"]["z"]["axis_set"] == 0.0
    [touch] = finding.numbers["derived_touches"]
    assert touch["z_axis_set"] == "unknown" and "credited_faces" not in touch
    assert "no proven usable touch land" in finding.sentence
    assert "S8 op 10" in finding.sentence and "crank_boss_faces" in finding.sentence
    assert "https://github.com/pedropaulovc/prechips/issues/208" in finding.sentence


def test_a_nonrectangular_native_datum_outline_cannot_borrow_its_radius_for_touch_land():
    data = carried_native_datum_bundle()
    for facts in data.kernel["setups"].values():
        for edge in facts["render_scene"]["datums"][0]["outline_mm"]:
            for point in edge:
                point[0] *= 10.0
    finding = evaluate(data)[-1]
    assert finding.status == "unknown"
    assert finding.numbers["axes"]["z"]["axis_set"] == pytest.approx(21.005)
    [touch] = finding.numbers["derived_touches"]
    assert touch["z_axis_set"] == "unknown" and "credited_faces" not in touch
    assert "no proven usable touch land" in finding.sentence


@pytest.mark.parametrize(
    ("depth", "diameter"),
    [(0.15, 0.3), (0.2, 0.3), (0.25, 0.3 + 0.1 * math.tan(math.radians(30))), (0.8, 0.4)],
    ids=["pilot-only", "pilot-end", "countersink-mouth", "body-radius-cap"],
)
@pytest.mark.parametrize("aim_shift", [0.0, 0.185])
def test_resolved_combined_drill_member_bounds_its_engaged_mouth_and_aim_shift(
    depth, diameter, aim_shift
):
    from prechips.rules.resolution import resolve

    data = carry_with_through_drill(aim_shift=aim_shift)
    receiver = data.plan["setups"][-1]
    spot = receiver["ops"][0]
    spot["depth_mm"] = depth
    tool = resolve(data, "tools", spot["tool"])
    assert spot["tool"] == "centre/1"
    assert tool["kind"] == "center_drill_set"
    assert tool["pilot_len_mm"] == 0.2
    finding = evaluate(data)[-1]
    assert finding.status == ("unknown" if aim_shift else "pass"), finding.sentence
    touch = finding.numbers["derived_touches"][0]
    assert touch["touch_exclusion_dia_mm"] == pytest.approx(diameter + 2 * aim_shift)


@pytest.mark.parametrize("depth", [0.25, 0.8], ids=["countersink-mouth", "body-radius-cap"])
@pytest.mark.parametrize("aim_shift", [0.0, 0.185])
def test_combined_drill_footprint_and_blind_depth_use_the_same_explicit_spot_depth(
    depth, aim_shift
):
    from prechips.rules.tip_endpoints import evaluate as evaluate_depth

    data = carry_with_through_drill(aim_shift=aim_shift)
    receiver = data.plan["setups"][-1]
    receiver["ops"][0]["depth_mm"] = depth
    data.feature_definitions["hole"]["depth"] = [0.2, 1.0]
    finding = evaluate(data)[-1]
    assert finding.status == ("unknown" if aim_shift else "pass"), finding.sentence
    endpoint_finding = next(row for row in evaluate_depth(data) if row.subject == "hole")
    spot_endpoint = next(
        row
        for row in endpoint_finding.numbers["endpoints"]
        if row["setup"] == receiver["id"] and row["op"] == 10
    )
    assert spot_endpoint["depth_mm"] == depth
    touch = finding.numbers["derived_touches"][0]
    diameter = min(0.4, 0.3 + 2 * (spot_endpoint["depth_mm"] - 0.2) * math.tan(math.radians(30)))
    assert touch["touch_exclusion_dia_mm"] == pytest.approx(diameter + 2 * aim_shift)


@pytest.mark.parametrize("debt", ["absent", "unknown", "unverified", "unknown-upper-band", "known"])
def test_combined_drill_feature_only_spot_depth_leaves_next_touch_unknown(debt):
    data = carry_with_through_drill()
    receiver = data.plan["setups"][-1]
    del receiver["ops"][0]["depth_mm"]
    feature = data.feature_definitions["hole"]
    if debt == "unknown":
        feature["depth"] = "unknown"
    elif debt == "unverified":
        feature["depth"] = {"value": 0.25, "verify": True}
    elif debt == "unknown-upper-band":
        feature["depth"] = [0.2, "unknown"]
    elif debt == "known":
        feature["depth"] = [0.2, 0.25]
    finding = evaluate(data)[-1]
    assert finding.status == "unknown"
    touch = finding.numbers["derived_touches"][0]
    assert touch["z_axis_set"] == "unknown"
    assert "credited_faces" not in touch


@pytest.mark.parametrize("depth", ["unknown", {"value": 0.25, "verify": True}])
def test_combined_drill_unknown_explicit_depth_cannot_fall_back_to_known_feature_depth(depth):
    data = carry_with_through_drill()
    receiver = data.plan["setups"][-1]
    receiver["ops"][0]["depth_mm"] = depth
    data.feature_definitions["hole"]["depth"] = 0.25
    finding = evaluate(data)[-1]
    assert finding.status == "unknown"
    touch = finding.numbers["derived_touches"][0]
    assert touch["z_axis_set"] == "unknown"
    assert "credited_faces" not in touch


@pytest.mark.parametrize("feature_depth", ["absent", "unknown", "unverified", 0.8])
def test_combined_drill_explicit_depth_does_not_inherit_feature_engagement(feature_depth):
    data = carry_with_through_drill()
    receiver = data.plan["setups"][-1]
    receiver["ops"][0]["depth_mm"] = 0.25
    feature = data.feature_definitions["hole"]
    if feature_depth == "unverified":
        feature["depth"] = {"value": 0.8, "verify": True}
    elif feature_depth != "absent":
        feature["depth"] = feature_depth
    finding = evaluate(data)[-1]
    assert finding.status == "pass", finding.sentence
    touch = finding.numbers["derived_touches"][0]
    assert touch["touch_exclusion_dia_mm"] == pytest.approx(0.3 + 0.1 * math.tan(math.radians(30)))


@pytest.mark.parametrize(
    "fact", ["dia_mm", "pilot_len_mm", "shank_mm", "point_angle", "angle_deg", "depth_mm"]
)
@pytest.mark.parametrize("missing", ["absent", "unknown", "unverified"])
def test_combined_drill_missing_engagement_facts_leave_the_next_touch_unknown(fact, missing):
    data = carried_stock_bundle()
    receiver = data.plan["setups"][-1]
    receiver["ops"][0]["depth_mm"] = 0.25
    record = (
        receiver["ops"][0]
        if fact == "depth_mm"
        else data.inventory["tools"]["centre"]
        if fact == "angle_deg"
        else data.inventory["tools"]["centre"]["members"]["1"]
    )
    if missing == "absent":
        del record[fact]
    elif missing == "unknown":
        record[fact] = "unknown"
    else:
        record[fact] = {"value": record[fact], "verify": True}
    finding = evaluate(data)[-1]
    assert finding.status == "unknown"
    touch = finding.numbers["derived_touches"][0]
    assert touch["z_axis_set"] == "unknown"
    assert "credited_faces" not in touch


@pytest.mark.parametrize(
    "debt",
    ["whole-face", "oblique-plunge", "scaled-axis", "lateral-sweep", "unknown-footprint"],
)
def test_cutting_without_proven_remaining_plane_area_invalidates_the_next_touch(debt):
    data = carry_with_through_drill()
    if debt == "whole-face":
        data.inventory["tools"]["drill"]["dia_mm"] = 2.0
    elif debt == "oblique-plunge":
        data.feature_definitions["hole"]["axis"] = [1.0, 0.0, 0.0]
    elif debt == "scaled-axis":
        data.feature_definitions["hole"]["axis"] = [0.0, 0.0, 2.0]
    elif debt == "lateral-sweep":
        data.plan["setups"][-1]["ops"][1].update(do="face", to_z=0.0)
    else:
        del data.inventory["tools"]["drill"]["dia_mm"]
    finding = evaluate(data)[-1]
    assert finding.status == "unknown"
    before = {row["before_ops"][0]: row for row in finding.numbers["derived_touches"]}
    assert before[30]["z_axis_set"] == "unknown"
    assert "credited_faces" not in before[30]
    if debt == "lateral-sweep":
        # Owning the hole's cylindrical refs did not make a new planar datum.
        assert before[30]["z_face"] == data.plan["setups"][-1]["zero"]["z"]["face"]
        assert before[30]["repeats"] != "op 20 face"


@pytest.mark.parametrize("thin_cylinder", [False, True], ids=["axial-span", "tolerance-flat-box"])
@pytest.mark.parametrize("route", ["primary", "explicit-touch", "listed-retouch"])
def test_a_native_cylinder_wholly_owned_by_facing_is_not_a_new_touch_plane(route, thin_cylinder):
    data = carry_with_through_drill()
    receiver = data.plan["setups"][-1]
    receiver["ops"][1].update(do="face", to_z=0.0)
    if thin_cylinder:
        # Its axial box fits LENGTH tolerance, but its known normal remains radial.
        face = data.kernel["faces"][3]
        face["bbox_mm"][5] = face["bbox_mm"][2] + 0.0005
    if route == "primary":
        # The incoming tool sets Z after the cut; isolate that primary datum debt
        # rather than requiring an unrelated subsequent tool-change pick-up.
        receiver["zero"]["z"].update(face="hole", edge_mm=0.0, after_op=20, tool="reamer")
    elif route == "explicit-touch":
        receiver["zero"]["tool_touches"] = [
            {
                "tool": "reamer",
                "z_face": "hole",
                "edge_mm": 0.0,
                "paper_mm": 0.0,
                "method": "touch_then_set",
                "before_ops": [30],
            }
        ]
    else:
        receiver["stock_state"] = {"top_z": 0.0, "top_feature": "hole"}
        receiver["zero"]["z"]["retouch_after"] = [20]
    finding = evaluate(data)[-1]
    assert finding.status == "unknown"
    row, field = (
        (finding.numbers["axes"]["z"], "axis_set")
        if route == "primary"
        else (finding.numbers["tool_touches"][0], "z_axis_set")
        if route == "explicit-touch"
        else (finding.numbers["retouch"][0], "axis_set")
    )
    assert row[field] == "unknown"
    assert "credited_faces" not in row
    assert "no eligible native plane at raw to_z" in finding.sentence


def test_remaining_plane_area_uses_that_native_end_radius_not_another_end():
    data = carry_with_through_drill()
    data.plan["setups"][1]["ops"] = data.plan["setups"][1]["ops"][:1]
    fact = data.kernel["setups"]["S3"]["revolved"]["crank_boss_faces"]
    fact["end_radii_mm"] = [2.0, 1.0]
    fact["radii_mm"] = [0.5, 2.0]
    data.kernel["faces"][1]["bbox_mm"][:2] = [-2.0, -2.0]
    data.kernel["faces"][1]["bbox_mm"][3:5] = [2.0, 2.0]
    data.inventory["tools"]["drill"]["dia_mm"] = 2.2
    finding = evaluate(data)[-1]
    assert finding.status == "unknown"
    last = finding.numbers["derived_touches"][-1]
    assert last["z_axis_set"] == "unknown" and "credited_faces" not in last


def test_a_cut_on_an_independent_prebond_branch_does_not_mutate_the_carried_face():
    data = carried_rectangular_stock_bundle()
    body = data.plan["setups"][0]
    data.plan["setups"][:2] = [data.plan["setups"][1], body]
    body["machine"] = "mill"
    body["ops"] = [op(10, "face", "spigot", "mill", to_z=0.0)]
    data.kernel["ops"]["S1:10"] = {"claimed_indices": [2]}
    finding = evaluate(data)[-1]
    assert finding.status == "pass", finding.sentence
    assert finding.numbers["axes"]["z"]["credited_faces"] == ["#1/NORTH"]


def test_an_existing_native_parting_face_is_also_a_valid_carry_producer():
    data = carried_rectangular_source_plane_bundle()
    source = data.plan["setups"][1]
    data.inventory["tools"]["parter"] = {"kind": "parting_blade", "blade_width_mm": 1.0}
    source["zero"]["x"]["tool"] = "parter"
    source["zero"]["z"].update(tool="parter", corner="tailstock_side")
    source["ops"][0].update(do="part_off", tool="parter")
    finding = evaluate(data)[-1]
    assert finding.status == "pass", finding.sentence
    assert finding.numbers["axes"]["z"]["axis_set"] == 21.01
    assert finding.numbers["axes"]["z"]["credited_faces"] == ["#1/NORTH"]


@pytest.mark.parametrize("route", ["explicit-touch", "listed-retouch"])
def test_every_carried_touch_route_retains_the_same_bounded_exclusion(route):
    data = carry_with_through_drill(aim_shift=0.185)
    receiver = data.plan["setups"][-1]
    face = receiver["zero"]["z"]["face"]
    if route == "explicit-touch":
        receiver["zero"]["tool_touches"] = [
            {
                "tool": "reamer",
                "z_face": face,
                "edge_mm": 0.0,
                "paper_mm": 0.0,
                "method": "touch_then_set",
                "before_ops": [30],
            }
        ]
    else:
        receiver["stock_state"] = {"top_z": 0.0, "top_feature": face}
        receiver["zero"]["z"].update(face="top", retouch_after=[20])
    finding = evaluate(data)[-1]
    assert finding.status == "unknown", finding.sentence
    row = (
        finding.numbers["tool_touches"][0]
        if route == "explicit-touch"
        else finding.numbers["retouch"][0]
    )
    assert row["z_axis_set" if route == "explicit-touch" else "axis_set"] == "unknown"
    assert "credited_faces" not in row
    assert "no proven usable touch land" in finding.sentence


def test_a_supplied_native_face_with_known_outward_normal_cannot_borrow_an_upward_bbox():
    data = carried_supplied_component_bundle()
    data.features["frames"]["JH"].update(y=[1.0, 0.0, 0.0], z=[0.0, 0.0, 1.0])
    data.plan["setups"][-1]["zero"]["z"]["edge_mm"] = -21.0
    finding = evaluate(data)[-1]
    assert finding.status == "unknown"
    assert finding.numbers["axes"]["z"]["axis_set"] == "unknown"


@pytest.mark.parametrize(
    ("mode", "flipped", "status"),
    [
        ("axial", False, "pass"),
        ("axial", True, "unknown"),
        ("rotary", False, "unknown"),
        ("cylinder", False, "unknown"),
        ("supplied", False, "unknown"),
    ],
)
def test_a_flat_carried_box_needs_a_proven_receiving_normal(mode, flipped, status):
    data = carried_bbox_mill_bundle(mode=mode, flipped=flipped)
    finding = evaluate(data)[-1]
    assert finding.status == status
    row = finding.numbers["axes"]["z"]
    if status == "pass":
        assert row["axis_set"] == 21.0
        assert row["credited_faces"] == ["#1/NORTH"]
    else:
        assert row["axis_set"] == "unknown"
        assert "credited_faces" not in row


@pytest.mark.parametrize("bounded", [False, True], ids=["unknown-footprint", "bounded-spot"])
def test_a_listed_retouch_does_not_inherit_its_primary_measured_zero_mode(bounded):
    data = measured_native_retouch_bundle(bounded=bounded)
    finding = evaluate(data)[-1]
    assert finding.status == ("pass" if bounded else "unknown")
    assert finding.numbers["axes"]["z"]["axis_set"] == "M +1"
    [row] = finding.numbers["retouch"]
    assert row["axis_set"] == (0.0 if bounded else "unknown")
    if bounded:
        assert row["credited_faces"] == ["#1/NORTH"]
        assert row["touch_exclusion_dia_mm"] == pytest.approx(0.3)
    else:
        assert "credited_faces" not in row


def test_a_listed_retouch_after_a_measured_zero_still_checks_its_physical_edge():
    data = measured_native_retouch_bundle()
    data.plan["setups"][-1]["stock_state"]["top_z"] = 0.01
    finding = evaluate(data)[-1]
    assert finding.status == "error"
    assert finding.numbers["axes"]["z"]["axis_set"] == "M +1"
    [row] = finding.numbers["retouch"]
    assert row["axis_set"] == row["top_z"] == "unknown"
    assert "credited_faces" not in row
    assert "the retouch after op 10 on top: edge 0.01" in finding.sentence
    assert "matches no native plane of crank_boss_faces" in finding.sentence
    assert "known native heights are -72, 0" in finding.sentence
    assert "eligible as-cut heights are 0" in finding.sentence


@pytest.mark.parametrize("later_setup", [False, True], ids=["same-setup", "downstream-setup"])
@pytest.mark.parametrize("bounded", [False, True], ids=["unknown-hole", "bounded-hole"])
def test_re_facing_never_erases_the_carried_planes_prior_hole_debt(bounded, later_setup):
    data = carry_with_refaced_hole(bounded=bounded, later_setup=later_setup)
    finding = evaluate(data)[-1]
    assert finding.status == ("pass" if bounded else "unknown")
    row = finding.numbers["axes"]["z"]
    assert row["axis_set"] == (21.0 if bounded else "unknown")
    if bounded:
        assert row["credited_faces"] == ["#1/NORTH"]
        assert row["touch_exclusion_dia_mm"] == pytest.approx(0.8)
    else:
        assert "credited_faces" not in row


def test_a_faced_away_top_is_not_touched_again_the_new_face_is():
    zero = mill_zero({"face": "top", "tool": "mill"})
    ops = [op(10, "face", "deck", "mill", to_z=0.0), op(20, "drill", "hole", "drill")]
    finding = evaluate(bundle("mill", zero, ops, {"top_z": 2.0}))[0]
    [touch] = finding.numbers["derived_touches"]
    assert (touch["z_face"], touch["edge_mm"], touch["z_axis_set"]) == ("deck", 0.0, 0.05)


def test_a_listed_retouch_serves_only_the_next_tool():
    zero = mill_zero({"face": "top", "tool": "mill"}, retouch_after=[10])
    ops = [
        op(10, "face", "deck", "mill", to_z=0.0),
        op(20, "spot", "hole", "centre/1"),
        op(30, "drill", "hole", "drill"),
    ]
    finding = evaluate(bundle("mill", zero, ops, {"top_z": 2.0}))[0]
    [touch] = finding.numbers["derived_touches"]
    assert touch["before_ops"] == [30] and touch["z_face"] in ("deck", "top")
    assert touch["z_axis_set"] == pytest.approx(0.05)


def test_a_listed_retouch_installs_the_incoming_tool_and_none_for_the_same_tool():
    # Ops 10 and 20 both run the end mill: the retouch after op 10 is no tool change. The
    # one after op 20 serves the drill, which goes in before its touch.
    zero = mill_zero({"face": "top", "tool": "mill"}, retouch_after=[10, 20])
    ops = [
        op(10, "face", "deck", "mill", to_z=0.0),
        op(20, "face", "deck", "mill", to_z=0.0),
        op(30, "drill", "hole", "drill"),
    ]
    data = bundle("mill", zero, ops, {"top_z": 2.0})
    finding = evaluate(data)[0]
    after = {row["op"]: row for row in finding.numbers["retouch"]}
    assert (after[10]["next_op"], after[10]["tool_change"]) == (20, False)
    assert (after[20]["next_op"], after[20]["next_tool"], after[20]["tool_change"]) == (
        30,
        "drill",
        True,
    )
    sheet, setup = sheet_of(data)
    tools = {("tools", "mill"): "T1 end mill", ("tools", "drill"): "T2 drill"}
    html = sheet.dro(setup, tools)
    lines = dro_paragraphs(html)
    assert not re.search(r"install\s+T1\b", sheet_text(html))
    (retained,) = [line for line in lines if re.search(r"\bAfter op 10\b", line)]
    (incoming,) = [line for line in lines if re.search(r"\bAfter op 20\b", line)]
    assert re.search(r"\bop 20\b", retained) and "T1 end mill" in retained
    assert "install" not in retained
    assert "top" in retained
    assert axis_set_value(retained, "Z") == Decimal("0.05")
    assert re.search(r"\bop 30\b", incoming) and "T2 drill" in incoming
    assert incoming.index("install") < incoming.index("T2 drill") < incoming.index("touch")
    assert "top" in incoming
    assert axis_set_value(incoming, "Z") == Decimal("0.05")
    assert finding.numbers["derived_touches"] == []


def test_several_tool_changes_to_one_touch_name_their_ops_not_the_tools_again():
    # The op rows carry each op's T number and the TOOLS table names it: the touch
    # paragraph lists where the changes fall, not a second tool-by-tool itinerary.
    zero = mill_zero({"face": "top", "tool": "mill"}, retouch_after=[10, 20])
    ops = [
        op(10, "face", "deck", "mill", to_z=0.0),
        op(20, "spot", "hole", "centre/1"),
        op(30, "drill", "hole", "drill"),
    ]
    sheet, setup = sheet_of(bundle("mill", zero, ops, {"top_z": 2.0}))
    tools = {
        ("tools", "mill"): "T1 end mill",
        ("tools", "centre/1"): "T2 centre drill",
        ("tools", "drill"): "T3 drill",
    }
    html = sheet.dro(setup, tools)
    lines = dro_paragraphs(html)
    (line,) = [line for line in lines if "install" in line and "Axis Set Z" in line]
    # Both operation identities belong to the one shared touch, independently of list punctuation.
    assert re.findall(r"\d+", line.split(":", 1)[0]) == ["20", "30"], line
    assert line.index("install") < line.index("touch"), line
    assert "top" in line, line
    assert axis_set_value(line, "Z") == Decimal("0.05")
    for name in ("T2 centre drill", "T3 drill"):
        assert name not in sheet_text(html), (name, sheet_text(html))


def test_a_mill_tool_touch_installs_its_tool_first():
    ops = [op(10, "spot", "hole", "centre/1"), op(20, "drill", "hole", "drill")]
    sheet, setup = sheet_of(bundle("mill", mill_zero(DECK), ops))
    tools = {("tools", "centre/1"): "T1 centre drill", ("tools", "drill"): "T2 drill"}
    (line,) = [line for line in dro_paragraphs(sheet.dro(setup, tools)) if "install" in line]
    assert re.search(r"\bop 20\b", line), line
    assert line.index("install") < line.index("T2 drill") < line.index("touch"), line
    assert "deck" in line
    assert axis_set_value(line, "Z") == Decimal("10.05")


def _cells(html):
    return [re.sub(r"<[^>]+>", "", cell).strip() for cell in re.findall(r"<td>(.*?)</td>", html)]


@pytest.mark.parametrize("qualified", ["op", "touch"])
def test_a_tool_keeps_one_t_number_however_its_ops_and_touches_spell_it(qualified):
    # A tool is the (category, key) it selects: "tools.drill" and "drill" are one drill.
    spell = {"op": ("tools.", ""), "touch": ("", "tools.")}[qualified]
    ops = [
        op(10, "spot", "hole", spell[0] + "centre/1"),
        op(20, "drill", "hole", spell[0] + "drill"),
        op(30, "drill", "hole", "drill"),
    ]
    zero = mill_zero({**DECK, "tool": spell[1] + "centre/1"})
    data = bundle("mill", zero, ops)
    sheet, setup = sheet_of(data)
    numbers, tools, table = sheet.tool_table(setup)
    cells = _cells(table)
    assert [cell for cell in cells if re.fullmatch(r"T\d+", cell)] == ["T1", "T2"]
    assert "20, 30" in cells
    # Every op row prints its tool's one number; the zero names the tool that set it.
    rows, _ = sheet.operations(setup, numbers)
    markup = Markup(rows)
    visible_tools = {}
    for operation in markup.find("operation"):
        (tool,) = markup.find("op-tool", operation)
        (value,) = [node for node in markup.nodes if node["tag"] == "dd" and node["parent"] is tool]
        visible_tools[operation["attrs"]["data-op"]] = content(value).strip()
    assert visible_tools == {"10": "T1", "20": "T2", "30": "T2"}
    printed = " ".join(visible_tools.values())
    assert "T3" not in printed and printed.count("T2") == 2, printed
    [touch] = evaluate(data)[0].numbers["derived_touches"]
    assert touch["before_ops"] == [20]
    assert touch["tool"].removeprefix("tools.") == "drill"
    (line,) = [line for line in dro_paragraphs(sheet.dro(setup, tools)) if "install" in line]
    assert re.search(r"\bop 20\b", line) and not re.search(r"\bop 30\b", line), line
    name = tools[("tools", "drill")]
    assert line.index("install") < line.index(name) < line.index("touch")
    assert re.findall(r"\bT\d+\b", line) == ["T2"]
    assert (
        sheet.touched_tool(spell[1] + "centre/1", tools, "spindle") == tools[("tools", "centre/1")]
    )
    setter = sheet.touched_tool(spell[1] + "centre/1", tools, "spindle")
    assert re.findall(r"\bT\d+\b", setter) == ["T1"]


def test_a_lathe_keeps_its_toolpost_numbers_however_its_setups_spell_the_machine():
    first = [op(10, "rough_turn", "journal", "turner")]
    data = bundle("lathe", lathe_zero([]), first)
    second = {**data.plan["setups"][0], "id": "S2", "machine": "machines.lathe"}
    second["ops"] = [op(10, "form_relief", "relief", "parter"), op(20, "face", "end", "turner")]
    data.plan["setups"].append(second)
    sheet = _Traveler(data, [], {}, {})
    numbers, _, _ = sheet.tool_table(second)
    # The turner keeps the number its first use on this lathe gave it.
    assert sorted(numbers.values()) == ["T1", "T2"]
    assert numbers[(("tools", "turner"), ("holders", None))] == "T1"
    assert numbers[(("tools", "parter"), ("holders", None))] == "T2"


def test_a_top_picked_up_after_a_facing_op_is_re_touched_where_that_op_left_it():
    # The face runs before the zero (no tool has set Z yet); the centre drill then
    # touches the faced top, and the drill repeats that touch at -2, not the incoming 0.
    zero = mill_zero({"face": "top", "tool": "centre/1", "after_op": 10})
    ops = [
        op(10, "face", "deck", "mill", to_z=-2.0),
        op(20, "spot", "hole", "centre/1"),
        op(30, "drill", "hole", "drill"),
    ]
    finding = evaluate(bundle("mill", zero, ops, {"top_z": 0.0}))[0]
    assert finding.numbers["missing_touches"] == []
    [touch] = finding.numbers["derived_touches"]
    assert touch["before_ops"] == [30] and touch["edge_mm"] == pytest.approx(-2.0)
    assert touch["z_axis_set"] == pytest.approx(-1.95)


def test_a_face_cut_to_an_unknown_depth_leaves_no_known_z_to_re_touch():
    zero = mill_zero({**DECK, "tool": "mill"})
    ops = [op(10, "face", "deck", "mill", to_z="unknown"), op(20, "drill", "hole", "drill")]
    finding = evaluate(bundle("mill", zero, ops, {"top_z": 10.0}))[0]
    assert finding.status == "unknown"
    [touch] = finding.numbers["derived_touches"]
    assert (touch["z_face"], touch["z_axis_set"]) == ("deck", "unknown")


def test_a_floor_re_pocketed_to_an_unknown_depth_falls_back_to_a_face_still_standing():
    zero = mill_zero({**DECK, "tool": "mill"})
    ops = [
        op(10, "face", "deck", "mill", to_z=5.0),
        op(20, "pocket", "field", "mill", to_z=0.0),
        op(30, "pocket", "field", "mill", to_z="unknown"),
        op(40, "drill", "hole", "drill"),
    ]
    finding = evaluate(bundle("mill", zero, ops, {"top_z": 10.0}))[0]
    [touch] = finding.numbers["derived_touches"]
    assert (touch["z_face"], touch["edge_mm"]) == ("deck", 5.0)
    assert touch["z_axis_set"] == pytest.approx(5.05)


@pytest.mark.parametrize(
    "top_feature", [{"top_feature": "deck"}, {}, {"top_feature": "unknown"}], ids=str
)
@pytest.mark.parametrize(
    "depth, status, axis_set",
    [
        ({}, "unknown", "unknown"),
        ({"to_z": "unknown"}, "unknown", "unknown"),
        ({"to_z": 9.0}, "pass", 9.05),
    ],
    ids=["omitted", "unknown", "known"],
)
def test_a_top_faced_to_no_stated_depth_is_no_known_z_to_re_touch(
    depth, status, axis_set, top_feature
):
    # The zero touched the top. Facing the deck leaves the top wherever that op took it
    # when the deck is (or may be: no or an unknown top feature) the top: a depth left
    # out states it no more than an explicit "unknown" does.
    zero = mill_zero({"face": "top", "tool": "mill"})
    ops = [op(10, "face", "deck", "mill", **depth), op(20, "drill", "hole", "drill")]
    finding = evaluate(bundle("mill", zero, ops, {"top_z": 10.0, **top_feature}))[0]
    assert finding.status == status
    assert finding.numbers["missing_touches"] == []
    [touch] = finding.numbers["derived_touches"]
    assert touch["z_face"] == "deck"
    assert touch["z_axis_set"] == (axis_set if axis_set == "unknown" else pytest.approx(axis_set))


@pytest.mark.parametrize("depth", [{}, {"to_z": "unknown"}], ids=["omitted", "unknown"])
@pytest.mark.parametrize("producer", ["retouch_after", "after_op"])
def test_a_top_touched_after_a_face_to_no_stated_depth_is_unknown(producer, depth):
    # The top is touched again after op 10 faced it (a listed retouch), or first touched
    # then (a zero after op 10): no stated depth leaves that top's Z unknown, not the
    # incoming Z 10.
    z = {"face": "top", "tool": "mill"}
    zero = mill_zero(z, [10]) if producer == "retouch_after" else mill_zero({**z, "after_op": 10})
    ops = [
        op(10, "face", "deck", "mill", **depth),
        op(20, "spot", "hole", "centre/1"),
        op(30, "drill", "hole", "drill"),
    ]
    finding = evaluate(bundle("mill", zero, ops, {"top_z": 10.0, "top_feature": "deck"}))[0]
    assert finding.status == "unknown"
    assert finding.numbers["missing_touches"] == []
    derived = [t["z_axis_set"] for t in finding.numbers["derived_touches"]]
    assert derived and set(derived) == {"unknown"}
    if producer == "retouch_after":
        assert [r["axis_set"] for r in finding.numbers["retouch"]] == ["unknown"]
    else:
        assert finding.numbers["axes"]["z"]["axis_set"] == "unknown"


@pytest.mark.parametrize("cut", ["deck", "unknown"])
def test_a_cut_whose_feature_is_unnamed_leaves_the_datum_unproven(cut):
    # A profile on the deck cuts the touched surface away; a profile on a feature the plan
    # does not name may have, so the drill's touch on the deck is unknown, not 10.05.
    zero = mill_zero({**DECK, "tool": "mill"})
    ops = [op(10, "profile", cut, "mill"), op(20, "drill", "hole", "drill")]
    finding = evaluate(bundle("mill", zero, ops, {"top_z": 10.0}))[0]
    if cut == "deck":
        assert finding.status == "error"
        assert finding.numbers["missing_touches"] == [
            {"before_op": 20, "tool": "drill", "axes": ["z"], "dro_set_by": "mill"}
        ]
    else:
        assert finding.status == "unknown"
        assert finding.numbers["missing_touches"] == []
        [touch] = finding.numbers["derived_touches"]
        assert (touch["z_face"], touch["z_axis_set"]) == ("deck", "unknown")


@pytest.mark.parametrize("face", [{"face": "field"}, {}], ids=["named", "absent"])
def test_a_zero_on_an_unnamed_face_is_no_proven_surface(face):
    # The floor the zero touched is re-pocketed to an unknown depth. Named, the re-pocket
    # visibly ends it; unnamed, nothing can show it survived, so neither is a known Z.
    zero = mill_zero({"edge_mm": 0.0, "method": "touch", "tool": "mill", **face})
    ops = [
        op(10, "pocket", "field", "mill", to_z=0.0),
        op(20, "pocket", "field", "mill", to_z="unknown"),
        op(30, "drill", "hole", "drill"),
    ]
    finding = evaluate(bundle("mill", zero, ops, {"top_z": 10.0}))[0]
    assert finding.status == "unknown"
    assert finding.numbers["missing_touches"] == []
    [touch] = finding.numbers["derived_touches"]
    assert touch["z_axis_set"] == "unknown"


def deck_bundle(face, cuts, footprint=True):
    """A deck X 0..20, Y 0..10 at Z 10 (its footprint unresolved unless ``footprint``, then
    the kernel's one plane face filling it), touched as ``face`` by the mill, faced to Z 5
    over each X span of ``cuts``, then drilled."""
    zero = mill_zero({"face": face, "edge_mm": 10.0, "method": "touch", "tool": "mill"})
    ops = [
        op(10 + 10 * i, "face", "deck", "mill", to_z=5.0, stock_removal_bounds=bounds)
        for i, bounds in enumerate({"x": x, "y": [0.0, 10.0], "z": [5.0, 10.0]} for x in cuts)
    ]
    ops.append(op(10 + 10 * len(cuts), "drill", "hole", "drill"))
    data = bundle("mill", zero, ops, {"top_z": 10.0, "top_feature": "deck"})
    identity = {"origin": [0.0, 0.0, 0.0], "x": [1.0, 0.0, 0.0], "y": [0.0, 1.0, 0.0]}
    identity["z"] = [0.0, 0.0, 1.0]
    data.features["frames"] = {"F": {**identity, "binding": "nominal"}, "model": identity}
    data.features["units"] = "mm"
    deck = {"frame": "model", "kind": "plane", "faces": ["#1/FACE"]}
    if footprint:
        deck["bounds"] = {"x": [0.0, 20.0], "y": [0.0, 10.0], "z": [10.0, 10.0]}
        box = [0.0, 0.0, 10.0, 20.0, 10.0, 10.0]
        plane = {"index": 0, "ref": "#1/FACE", "kind": "Plane", "area_mm2": 200.0, "bbox_mm": box}
        plane["fills_bbox"] = True
        data.kernel = {"status": "ok", "mapping": {"#1/FACE": 0}, "faces": [plane]}
    data.features["features"]["deck"] = deck
    return data


@pytest.mark.parametrize(
    "cuts, status, edge",
    [
        ([[0.0, 10.0]], "pass", 10.0),
        ([[0.0, 20.0]], "pass", 5.0),
        ([[0.0, 10.0], [10.0, 20.0]], "unknown", "unknown"),
        ([[0.0, 12.0], [8.0, 20.0]], "unknown", "unknown"),
        ([[0.0, 8.0], [12.0, 20.0]], "pass", 10.0),
    ],
    ids=["part", "whole", "halves", "overlapping", "strip-left"],
)
@pytest.mark.parametrize("face", ["deck", "top"])
def test_a_datum_faced_in_parts_stands_only_where_every_cut_spared_it(face, cuts, status, edge):
    # Faces over part of the deck leave the rest of it at Z 10, where the drill is touched
    # off, as long as some of it is outside every cut; faces that together cover it leave
    # no Z 10 to touch, and no one of them made the Z 5 face. A whole face moves it to Z 5.
    finding = evaluate(deck_bundle(face, cuts))[0]
    assert finding.status == status
    assert finding.numbers["missing_touches"] == []
    [touch] = finding.numbers["derived_touches"]
    if status == "pass":
        assert touch["edge_mm"] == pytest.approx(edge)
        assert touch["z_axis_set"] == pytest.approx(edge + 0.05)
    else:
        assert (touch["edge_mm"], touch["z_axis_set"]) == ("unknown", "unknown")


@pytest.mark.parametrize("face", ["deck", "top"])
def test_a_bounded_face_over_a_datum_of_unknown_extent_neither_spares_nor_makes_it(face):
    # Without the deck's footprint the bounded face may have cut all or part of it: the
    # drill's touch is neither the old Z 10 nor the cut's Z 5.
    finding = evaluate(deck_bundle(face, [[0.0, 10.0]], footprint=False))[0]
    assert finding.status == "unknown"
    [touch] = finding.numbers["derived_touches"]
    assert touch["z_axis_set"] == "unknown"


ROUND = {"frame": "model", "kind": "plane", "at": [10.0, 5.0, 10.0], "dia": 10.0}
BOX = {"bounds": {"x": [5.0, 15.0], "y": [0.0, 10.0], "z": [10.0, 10.0]}}


@pytest.mark.parametrize(
    "deck",
    [ROUND, {**ROUND, **BOX}, {"frame": "model", "kind": "face", "faces": ["#1/FACE"], **BOX}],
    ids=["round", "round-with-bounds", "face-box"],
)
def test_a_datum_not_known_to_fill_its_box_is_not_spared_by_its_corners(deck):
    # The deck is a dia 10 disc at X 10, Y 5 (or a face known only by its box), faced in
    # two passes that between them cover all of such a disc but not the corners of its
    # box: nothing shows any Z 10 is left for the drill.
    data = deck_bundle("deck", [[5.0, 15.0], [6.4, 13.6]])
    ops = data.plan["setups"][0]["ops"]
    ops[0]["stock_removal_bounds"]["y"] = [1.5, 8.5]
    data.features["features"]["deck"] = deck
    finding = evaluate(data)[0]
    assert finding.status == "unknown"
    [touch] = finding.numbers["derived_touches"]
    assert touch["z_axis_set"] == "unknown"


@pytest.mark.parametrize("kernel", ["L-shaped", "none"])
def test_a_plane_face_not_shown_to_fill_its_box_is_not_spared_by_its_corners(kernel):
    # The deck's one plane face is an L (X 0..20 at Y 0..5 and X 0..5 at Y 5..10, 125 of
    # its box's 200 mm^2, not filling it), or no kernel result shows its shape. Faced over
    # X 0..5, then over X 5..20 at Y 0..5, the only uncut part of its box is the empty
    # corner.
    data = deck_bundle("deck", [[0.0, 5.0], [5.0, 20.0]])
    data.plan["setups"][0]["ops"][1]["stock_removal_bounds"]["y"] = [0.0, 5.0]
    if kernel == "none":
        del data.kernel
    else:
        data.kernel["faces"][0].update(area_mm2=125.0, fills_bbox=False)
    finding = evaluate(data)[0]
    assert finding.status == "unknown"
    [touch] = finding.numbers["derived_touches"]
    assert touch["z_axis_set"] == "unknown"


_DECKS = r"""
import sys
import FreeCAD, Part
V = FreeCAD.Vector
out = sys.argv[sys.argv.index("--") + 1]
deck = Part.makeBox(20, 10, 10)
for name, shape in [
    ("filled", deck),
    # A 0.005 mm square hole through the middle: its top has a second, inner wire.
    ("small-hole", deck.cut(Part.makeBox(0.005, 0.005, 12, V(9.9975, 4.9975, -1)))),
    # The same square notched out of the X 20, Y 10 corner: one wire of six edges.
    ("notch", deck.cut(Part.makeBox(0.005, 0.005, 12, V(19.995, 9.995, -1)))),
    # A block beside it as tall splits the top's X 20 edge at Y 5, a rectangle still.
    ("split-edge", deck.fuse(Part.makeBox(10, 5, 10, V(20, 0, 0)))),
    # X 0..20.0000006, notched through its X end 0.0000009 mm deep at Y 4..6: every edge
    # within the kernel's 1e-6 mm of a side, and its box rounded out to X 20.000001.
    (
        "thin-notch",
        Part.makeBox(20.0000006, 10, 10).cut(Part.makeBox(1, 2, 12, V(19.9999997, 4, -1))),
    ),
    # Pocketed to Z 5 inside 0.0000009 mm walls on three sides, open at Y 10: its Z 10
    # top is a rim along three sides of its box, every edge within 1e-6 mm of a side.
    ("rim", deck.cut(Part.makeBox(20 - 1.8e-6, 11, 6, V(9e-7, 9e-7, 5)))),
]:
    assert shape.isValid() and len(shape.Solids) == 1, name
    shape.exportStep(out + "/" + name + ".step")
"""


@pytest.fixture(scope="module")
def deck_tops(tmp_path_factory, freecad_kernel):
    """The kernel's face record of each authored deck's Z 10 top from X 0, Y 0..10."""
    directory = tmp_path_factory.mktemp("decks")
    script = directory / "author.py"
    script.write_text(_DECKS, encoding="utf-8")
    process = subprocess.run(
        [freecad_kernel, str(script), "--", str(directory)],
        capture_output=True,
        text=True,
        errors="replace",
        timeout=300,
    )
    engine, tops = Engine(directory, freecad_kernel), {}
    for path in directory.glob("*.step"):
        [tops[path.stem]] = [
            f
            for f in engine.faces(path)
            if f["bbox_mm"][:3] == [0.0, 0.0, 10.0] and f["bbox_mm"][4:] == [10.0, 10.0]
        ]
    assert len(tops) == 6, process.stdout[-2000:] + process.stderr[-2000:]
    return tops


def deck_faced_in(face, regions):
    """:func:`deck_bundle` faced to Z 5 over each X/Y region of ``regions``."""
    data = deck_bundle(face, [x for x, _ in regions])
    for cut, (_, y) in zip(data.plan["setups"][0]["ops"][:-1], regions, strict=True):
        cut["stock_removal_bounds"]["y"] = y
    return data


def sparing(x, y):
    """Regions that between them face all of X -1..21, Y -1..11 but the box ``x`` by ``y``."""
    (x0, x1), (y0, y1) = x, y
    return [
        [[-1.0, x0], [-1.0, 11.0]],
        [[x1, 21.0], [-1.0, 11.0]],
        [[x0, x1], [-1.0, y0]],
        [[x0, x1], [y1, 11.0]],
    ]


def drill_pickup(data):
    """(status, Z Axis Set) of the one touch derived for ``data``'s drill."""
    finding = evaluate(data)[0]
    [touch] = finding.numbers["derived_touches"]
    return finding.status, touch["z_axis_set"]


UNPROVEN, SPARED = ("unknown", "unknown"), ("pass", pytest.approx(10.05))
# The 0.005 mm squares of the hole and the notch, and 1 mm squares about them.
HOLE, NOTCH = ([9.9975, 10.0025], [4.9975, 5.0025]), ([19.995, 20.0], [9.995, 10.0])
CENTRE, CORNER = ([9.5, 10.5], [4.5, 5.5]), ([19.0, 20.0], [9.0, 10.0])
# Faces to Z 5 sparing only the thin notch's X 19.9999997.. end of the deck at Y 4..6.
THIN_NOTCH_CUTS = [
    [[0.0, 19.9999997], [0.0, 10.0]],
    [[19.9999997, 21.0], [0.0, 4.0]],
    [[19.9999997, 21.0], [6.0, 10.0]],
]


@pytest.mark.parametrize(
    "deck, cuts, pickup",
    [
        ("small-hole", sparing(*HOLE), UNPROVEN),
        ("small-hole", sparing(*CENTRE), UNPROVEN),
        ("notch", sparing(*NOTCH), UNPROVEN),
        ("notch", sparing(*CORNER), UNPROVEN),
        ("thin-notch", THIN_NOTCH_CUTS, UNPROVEN),
        ("rim", sparing([10.0, 20.0], [0.0, 10.0]), UNPROVEN),
        ("filled", sparing(*CENTRE), SPARED),
        ("filled", sparing(*CORNER), SPARED),
        ("filled", sparing([10.0, 20.0], [0.0, 10.0]), SPARED),
        ("split-edge", sparing(*CENTRE), SPARED),
        ("thin-notch", sparing([19.0, 20.5], [0.0, 1.0]), SPARED),
    ],
    ids=[
        "small-hole",
        "about-small-hole",
        "notch",
        "about-notch",
        "thin-notch",
        "rim",
        "filled-centre",
        "filled-corner",
        "filled-half",
        "split-edge",
        "thin-notch-clear-end",
    ],
)
@pytest.mark.parametrize("face", ["deck", "top"])
def test_a_land_every_cut_spares_holds_the_datum_only_where_the_face_fills_its_box(
    deck_tops, face, deck, cuts, pickup
):
    # The deck's top as the kernel measures it, bounded by its box, faced in parts. A
    # hole or notch in the spared square leaves no Z 10 at all there, however little of
    # the box the face lacks; so does a notch 0.0000009 mm deep, inside the kernel's side
    # tolerance, at the only part of the box (rounded out past the notch) every cut
    # spares, and a rim along three sides with no surface inside it. Where the face fills
    # its box, the spared 1 mm square is still Z 10, as is the thin notch's clear end.
    data = deck_faced_in(face, cuts)
    top = deck_tops[deck]
    box = top["bbox_mm"]
    bounds = {"x": [box[0], box[3]], "y": [box[1], box[4]], "z": [box[2], box[5]]}
    data.features["features"]["deck"]["bounds"] = bounds
    data.kernel = {"status": "ok", "mapping": {"#1/FACE": top["index"]}, "faces": [top]}
    assert drill_pickup(data) == pickup


@pytest.mark.parametrize(
    "cuts, pickup",
    [
        (sparing(*HOLE), UNPROVEN),
        (sparing([9.7505, 10.2495], [4.5, 5.5]), UNPROVEN),
        (sparing([9.75, 10.25], [4.75, 5.25]), SPARED),
        (sparing([19.6, 20.0], [0.0, 10.0]), UNPROVEN),
        # An L of the X 19..20, Y 9..10 corner, 0.3 mm wide along X 19 and along Y 10.
        (
            [[[-1.0, 19.0], [-1.0, 11.0]], [[19.0, 21.0], [-1.0, 9.0]], [[19.3, 21.0], [9.0, 9.7]]],
            UNPROVEN,
        ),
        # That 1 mm corner whole, with two other cuts ending at X 19.4 and X 19.6.
        (
            [
                [[-1.0, 19.0], [-1.0, 11.0]],
                [[19.0, 21.0], [-1.0, 9.0]],
                [[19.4, 21.0], [-1.0, 1.0]],
                [[18.0, 19.6], [-1.0, 1.0]],
            ],
            SPARED,
        ),
    ],
    ids=["hole-sized", "just-narrower", "touch-sized", "strip", "narrow-L", "across-cut-ends"],
)
@pytest.mark.parametrize("face", ["deck", "top"])
def test_a_spared_patch_holds_the_datum_only_where_a_touch_fits_on_it(face, cuts, pickup):
    # The deck fills its box, faced in parts that spare a 0.005 mm square, a 0.499 by
    # 1 mm patch, a 0.5 mm square, a 0.4 by 10 mm strip or a 0.3 mm wide L: only a land
    # 0.5 mm square holds a touch, wherever the other cuts' ends cross it.
    assert drill_pickup(deck_faced_in(face, cuts)) == pickup


@pytest.mark.parametrize(
    "turn, cuts, pickup",
    [
        # Its setup X/Y box is X 0..22.32, Y -10..8.66; the spared X 0..2, Y -10..-8
        # corner of it lies off the face.
        (30, [[[2.0, 22.4], [-10.1, 8.7]], [[-0.1, 2.0], [-8.0, 8.7]]], UNPROVEN),
        # Its setup X/Y box is the face, X 0..10, Y -20..0: the spared corner is Z 10.
        (90, [[[2.0, 10.0], [-20.0, 0.0]], [[0.0, 2.0], [-18.0, 0.0]]], SPARED),
    ],
    ids=["turned-30", "turned-90"],
)
def test_a_face_filling_its_box_fills_the_setup_box_only_square_to_the_setup(turn, cuts, pickup):
    # The deck fills its model box, but the setup's X/Y axes are turned against the
    # model's about Z: turned 30 deg, the face's setup box has corners the face is not in.
    data = deck_faced_in("deck", cuts)
    c, s = math.cos(math.radians(turn)), math.sin(math.radians(turn))
    data.features["frames"]["F"].update(x=[c, s, 0.0], y=[-s, c, 0.0])
    assert drill_pickup(data) == pickup


def retouch_deck(data, retouch):
    """Re-touch ``data``'s deck after op 10: a listed top retouch, else a touch authored
    for the centre drill before op 20."""
    zero = data.plan["setups"][0]["zero"]
    if retouch == "listed":
        zero["z"] = {**zero["z"], "face": "top", "retouch_after": [10]}
    else:
        touch = {"tool": "centre/1", "z_face": "deck", "edge_mm": 10.0, "paper_mm": 0.05}
        zero["tool_touches"] = [{**touch, "method": "touch_then_set", "before_ops": [20]}]


@pytest.mark.parametrize("retouch", ["listed", "authored"])
def test_a_datum_re_touched_after_a_cut_of_unknown_extent_stays_unproven(retouch):
    # Op 10 faces part of the deck, whose footprint is unresolved, so whether any of its
    # Z 10 is left is unknown; touching it again at its nominal Z 10 does not show it.
    data = deck_bundle("deck", [[0.0, 10.0]], footprint=False)
    ops = data.plan["setups"][0]["ops"]
    ops[1:] = [op(20, "spot", "hole", "centre/1"), op(30, "drill", "hole", "drill")]
    retouch_deck(data, retouch)
    finding = evaluate(data)[0]
    assert finding.status == "unknown"
    assert finding.numbers["missing_touches"] == []
    derived = [t["z_axis_set"] for t in finding.numbers["derived_touches"]]
    assert derived and set(derived) == {"unknown"}


@pytest.mark.parametrize(
    "depth, status, axis_set",
    [({"to_z": 5.0}, "error", 5.05), ({}, "unknown", "unknown")],
    ids=["to-z-5", "omitted"],
)
@pytest.mark.parametrize("face", ["deck", "top"])
def test_a_touch_at_a_z_its_surface_was_not_made_at_is_not_repeated(face, depth, status, axis_set):
    # Op 10 faces the whole deck, the stock top (to Z 5, or to no stated depth), then the
    # centre drill is touched off as if still at Z 10. The derived touch uses the standing
    # face, but a known standing Z 5 contradicts the authored edge and stops the recipe.
    data = deck_bundle("deck", [[0.0, 20.0]])
    ops = data.plan["setups"][0]["ops"]
    ops[0] = op(10, "face", "deck", "mill", **depth)
    ops[1:] = [op(20, "spot", "hole", "centre/1"), op(30, "drill", "hole", "drill")]
    retouch_deck(data, "authored")
    data.plan["setups"][0]["zero"]["tool_touches"][0]["z_face"] = face
    finding = evaluate(data)[0]
    assert finding.status == status
    if depth:
        assert finding.numbers["tool_touches"][0]["z_axis_set"] == pytest.approx(axis_set)
        assert "edge 10" in finding.sentence and "stands at 5" in finding.sentence
    [touch] = finding.numbers["derived_touches"]
    assert touch["z_axis_set"] == (axis_set if axis_set == "unknown" else pytest.approx(axis_set))


@pytest.mark.parametrize("retouch", ["listed", "authored"])
def test_a_datum_re_touched_between_partial_faces_keeps_the_first_cut(retouch):
    # Op 10 faces the left half of the deck, the deck is touched again at its uncut Z 10,
    # then op 30 faces the right half: the re-touch does not undo op 10, so no Z 10 is
    # left for the drill.
    data = deck_bundle("deck", [[0.0, 10.0]])
    ops = data.plan["setups"][0]["ops"]
    right = {**ops[0], "op": 30, "stock_removal_bounds": {**ops[0]["stock_removal_bounds"]}}
    right["stock_removal_bounds"]["x"] = [10.0, 20.0]
    ops[1:] = [op(20, "spot", "hole", "centre/1"), right, op(40, "drill", "hole", "drill")]
    retouch_deck(data, retouch)
    finding = evaluate(data)[0]
    assert finding.status == "unknown"
    assert finding.numbers["missing_touches"] == []
    before_30, before_40 = finding.numbers["derived_touches"]
    assert before_30["before_ops"] == [30]
    assert before_30["z_axis_set"] == pytest.approx(10.05)
    assert (before_40["before_ops"], before_40["z_axis_set"]) == ([40], "unknown")


@pytest.mark.parametrize("incoming", ["unknown", "not-in-inventory"])
def test_an_unresolved_incoming_tool_keeps_the_tool_change_unknown(incoming):
    ops = [op(10, "spot", "hole", "centre/1"), op(20, "drill", "hole", incoming)]
    finding = evaluate(bundle("mill", mill_zero(DECK), ops))[0]
    assert finding.status == "unknown"
    assert finding.numbers["missing_touches"] == []


@pytest.mark.parametrize("machine", ["mill", "lathe"])
def test_a_setup_with_no_zero_has_no_tool_dro_to_change(machine):
    # No recipe set the DRO, so no tool cuts on another tool's Axis Set: the zero is
    # missing (unknown), not a tool change to touch off.
    ops = [op(10, "spot", "hole", "centre/1"), op(20, "drill", "hole", "drill")]
    if machine == "lathe":
        ops = [op(10, "face", "end", "turner"), op(20, "part_off", "relief", "parter")]
    finding = evaluate(bundle(machine, {}, ops))[0]
    assert finding.status == "unknown"
    assert finding.numbers["derived_touches"] == []
    assert finding.numbers["missing_touches"] == []


def test_a_measured_zero_gives_no_plan_z_to_re_touch_so_the_change_is_an_error():
    z = {
        "face": "deck",
        "edge_mm": 10.0,
        "method": "measure_then_set",
        "gauge": "mic",
        "measure": "deck height above the vise floor",
        "offset_mm": -1.0,
        "tool": "centre/1",
    }
    ops = [op(10, "spot", "hole", "centre/1"), op(20, "drill", "hole", "drill")]
    finding = evaluate(bundle("mill", mill_zero(z), ops))[0]
    assert finding.status == "error"
    assert finding.numbers["missing_touches"] == [
        {"before_op": 20, "tool": "drill", "axes": ["z"], "dro_set_by": "centre/1"}
    ]


@pytest.mark.parametrize(
    "change,axis_set,check,mirror",
    [
        ({}, "M -0.95", "M +4.05", "M -5.95"),
        ({"gauge": "unknown"}, "unknown", "unknown", "unknown"),
        ({"measure": ""}, "unknown", "unknown", "unknown"),
        ({"measure": "unknown"}, "unknown", "unknown", "unknown"),
        ({"offset_mm": "unknown"}, "unknown", "unknown", "unknown"),
    ],
)
def test_a_measured_z_zero_sets_the_measurement_plus_offset_and_paper(
    change, axis_set, check, mirror
):
    z = {
        "face": "deck",
        "edge_mm": 10.0,
        "method": "measure_then_set",
        "gauge": "mic",
        "measure": "deck height above the vise floor",
        "offset_mm": -1.0,
        "tool": "centre/1",
        **change,
    }
    finding = evaluate(bundle("mill", mill_zero(z), [op(10, "spot", "hole", "centre/1")]))[0]
    row = finding.numbers["axes"]["z"]
    assert (row["axis_set"], row["check_reading"], row["mirrored_reading"]) == (
        axis_set,
        check,
        mirror,
    )
    assert finding.status == ("pass" if axis_set != "unknown" else "unknown")


@pytest.mark.parametrize(
    "measure,axis_set,status",
    [("boss height above the deck", "M +10.05", "pass"), ("unknown", "unknown", "unknown")],
)
def test_a_mill_tool_touch_is_z_only_and_may_be_measured(measure, axis_set, status):
    touch = {
        "tool": "drill",
        "z_face": "boss",
        "edge_mm": 3.0,
        "paper_mm": 0.05,
        "method": "measure_then_set",
        "z_gauge": "mic",
        "z_measure": measure,
        "z_offset_mm": 10.0,
        "before_ops": [20],
    }
    zero = {**mill_zero(DECK), "tool_touches": [touch]}
    ops = [op(10, "spot", "hole", "centre/1"), op(20, "drill", "hole", "drill")]
    finding = evaluate(bundle("mill", zero, ops))[0]
    assert finding.status == status
    [row] = finding.numbers["tool_touches"]
    assert (row["x_axis_set"], row["z_axis_set"]) == ("not_applicable", axis_set)
    assert finding.numbers["derived_touches"] == []


def sheet_of(data):
    finding = evaluate(data)[0]
    return _Traveler(data, [finding], {}, {}), data.plan["setups"][0]


def test_the_datum_transfer_prints_before_the_zero_it_sets_up():
    transfer = {"from": "S0", "indicate": "journal", "gauge": "mic", "runout_limit_mm": 0.02}
    data = bundle(
        "lathe", {**lathe_zero([]), "transfer": transfer}, [op(10, "turn", "j", "turner")]
    )
    sheet, setup = sheet_of(data)
    markup = Markup(sheet.dro(setup, {("tools", "turner"): "T1 turner"}))
    (transfer,) = markup.find("zero-transfer")
    axes = markup.find("zero")[0]
    setting = next(
        node
        for node in markup.nodes
        if node["tag"] == "p" and content(node).startswith("Before touching off")
    )
    # One original sweep precedes both its tool setting and the zero table.
    assert content(transfer).startswith("Before zeroing: indicate the")
    assert markup.nodes.index(transfer) < markup.nodes.index(setting) < markup.nodes.index(axes)


def measured_hold(before_hold):
    zero = lathe_zero([])
    zero["z"] = {
        "face": "stub end",
        "edge_mm": 5.0,
        "from": "+z",
        "method": "measure_then_set",
        "gauge": "mic",
        "measure": "length from the thrust face to the stub end",
        "offset_mm": -9.0,
        "tool": "turner",
        "paper_mm": 0.0,
        "check_jog_mm": 10.0,
        "retouch_after": [],
    }
    if before_hold is not None:
        zero["z"]["measure_before_hold"] = before_hold
    data = bundle("lathe", zero, [op(10, "face", "stub end", "turner", to_z=0.0)])
    data.plan["setups"][0]["hold"] = {
        "fixture": "chuck",
        "stop": "thrust face seated on the jaw fronts",
        "clamp": "tighten the chuck at all three pinions",
    }
    return sheet_of(data)


def test_a_zero_measured_before_the_hold_is_measured_before_clamping():
    sheet, setup = measured_hold(True)
    steps, _ = sheet.hold(setup)
    markup = Markup(steps)
    entries = [node for node in markup.nodes if node["tag"] == "li"]
    measure = next(node for node in entries if "length from the thrust face" in content(node))
    seat = next(node for node in entries if "thrust face seated" in content(node))
    clamp = next(node for node in entries if "Tighten the chuck" in content(node))
    assert entries.index(measure) < entries.index(seat) < entries.index(clamp)
    assert "measure Z M = length from the thrust face" in content(measure)
    assert len(markup.find("writing-blank")) == 1
    assert [content(label) for label in markup.find("field-label", measure)] == ["Z M"]
    # The zero row refers back to that sole original acquisition.
    row_html = sheet.dro(setup, {("tools", "turner"): "T1 turner"})
    row = Markup(row_html)
    assert "length from the thrust face" not in sheet_text(row_html)
    assert any("M measured before clamping" in content(node) for node in row.nodes)
    assert not row.find("writing-blank")


@pytest.mark.parametrize("before_hold", [None, False])
def test_a_zero_measured_at_the_machine_stays_in_the_zero_table(before_hold):
    sheet, setup = measured_hold(before_hold)
    steps, _ = sheet.hold(setup)
    markup = Markup(steps)
    assert "length from the thrust face" not in sheet_text(steps)
    assert not markup.find("field") and not markup.find("writing-blank")
    assert "M = length from the thrust face" in sheet_text(
        sheet.dro(setup, {("tools", "turner"): "T1 turner"})
    )


def x_touch(x_face, before, ops=LATHE_OPS, x_method="paper on the measured diameter", x=None):
    """The blade's authored touch before op ``before`` with its X on ``x_face`` (None:
    words only)."""
    touch = {**BLADE, "x_method": x_method, "x_face": x_face, "before_ops": [before]}
    if x_face is None:
        del touch["x_face"]
    zero = lathe_zero([touch])
    zero["x"].update(x or {})
    data = bundle("lathe", zero, ops)
    data.plan["setups"][0]["stock_in"] = "stock"
    return data


def x_row(data, setup=0):
    finding = evaluate(data)[setup]
    [row] = finding.numbers["tool_touches"]
    return finding, row


FORMED = [*LATHE_OPS[:3], op(35, "form_dome", "journal", "turner"), LATHE_OPS[3]]


@pytest.mark.parametrize(
    ("x_face", "before", "ops", "x", "status"),
    [
        # Turned in ops 10 and 30, it stands at op 40.
        ("journal", 40, LATHE_OPS, None, "pass"),
        # Formed in op 35: the diameter the touch names is gone.
        ("journal", 40, FORMED, None, "error"),
        # Not yet turned when the blade touches it before op 10.
        ("journal", 10, LATHE_OPS, None, "error"),
        ("no_such_feature", 40, LATHE_OPS, None, "error"),
        # The X zero's trial-cut land stands until a cut runs.
        ("x_zero", 10, LATHE_OPS, None, "pass"),
        ("x_zero", 40, LATHE_OPS, None, "unknown"),
        # No trial cut, no land.
        ("x_zero", 10, LATHE_OPS, {"method": "touch"}, "error"),
        # Words alone name no surface the rule can follow.
        (None, 40, LATHE_OPS, None, "unknown"),
    ],
)
def test_an_authored_x_touch_is_on_a_surface_standing_where_it_touches(
    x_face, before, ops, x, status
):
    finding, row = x_row(x_touch(x_face, before, ops, x=x))
    assert row["x_face_status"] == status, row
    if status == "error":
        assert finding.status == "error" and "X touch" in finding.sentence
    elif status == "unknown":
        assert finding.status in ("unknown", "error")


def test_a_blade_trial_cut_is_its_own_x_surface():
    _, row = x_row(x_touch(None, 40, x_method="trial_cut_measure"))
    assert row["x_face_status"] == "pass"


@pytest.mark.parametrize(
    ("earlier_op", "routed", "status"),
    [
        (op(10, "finish_turn", "journal", "turner"), True, "pass"),
        # Formed after it was turned: no cylinder arrives.
        (op(10, "form_dome", "journal", "turner"), True, "error"),
        # Turned in a setup the plan does not route to this one.
        (op(10, "finish_turn", "journal", "turner"), False, "unknown"),
    ],
)
def test_a_diameter_turned_in_an_earlier_setup_stands_for_a_touch(earlier_op, routed, status):
    data = x_touch("journal", 40, [op(40, "form_relief", "relief", "parter")])
    earlier = {
        "id": "S0",
        "machine": "lathe",
        "frame": "F",
        "zero": {},
        "stock_state": {},
        "stock_in": "stock",
        "ops": [earlier_op],
    }
    data.plan["setups"].insert(0, earlier)
    if routed:
        data.plan["setups"][1]["stock_in"] = "S0"
    else:
        del data.plan["setups"][1]["stock_in"]
    _, row = x_row(data, setup=1)
    assert row["x_face_status"] == status


@pytest.mark.parametrize(
    ("radius_mode", "paper", "axis_set"),
    [
        (False, 0.05, "measured D + 0.1"),
        (True, 0.05, "measured D/2 + 0.05"),
        (False, 0.0, "measured D"),
        (False, "unknown", "unknown"),
    ],
)
def test_an_x_touch_through_paper_sets_the_measured_diameter_plus_the_paper(
    radius_mode, paper, axis_set
):
    data = x_touch("journal", 40)
    data.plan["dro"] = {**DRO, "radius_mode": radius_mode}
    data.plan["setups"][0]["zero"]["tool_touches"][0]["x_paper_mm"] = paper
    _, row = x_row(data)
    assert row["x_axis_set"] == axis_set


@pytest.mark.parametrize(
    ("x_face", "ops", "stop"),
    [("journal", LATHE_OPS, False), ("journal", FORMED, True), (None, LATHE_OPS, True)],
)
def test_an_authored_x_touch_prints_its_axis_set_and_stops_on_a_diameter_not_shown_standing(
    x_face, ops, stop
):
    sheet, setup = sheet_of(x_touch(x_face, 40, ops))
    tools = {("tools", "parter"): "T4 blade", ("tools", "turner"): "T1 turner"}
    (touch,) = [
        line
        for line in dro_paragraphs(sheet.dro(setup, tools), mode="diameter")
        if "T4 blade" in line and "Axis Set X" in line
    ]
    assert re.search(r"\bop 40\b", touch), touch
    line = touch.split("X —", 1)[1].split("Z —", 1)[0]
    # The paper counts once on the radius, twice on a diameter display.
    assert "paper on the measured diameter" in line, line
    assert axis_set_value(line, "X", base="measured Ø") == Decimal("0.10")
    assert ("STOP" in line) is stop, line


def x_printed(data, touch):
    """The X half of ``touch`` as the sheet prints it."""
    sheet, setup = sheet_of(data)
    return sheet.tool_touch(setup, touch, {}, "spindle").split("X — ", 1)[1].split(" Z — ", 1)[0]


@pytest.mark.parametrize(
    ("x_method", "paper", "contact"),
    [
        # Words that name the surface but not the paper the Axis Set counts.
        ("touch the journal just measured", 0.05, "paper 0.05"),
        ("touch the journal just measured", 0.0, "no paper"),
        # Words that name neither.
        ("bring the blade in until it drags", 0.05, "paper 0.05"),
        # Paper not stated: its Axis Set is unknown, and so is the paper printed.
        ("touch the journal just measured", "unknown", "paper ?"),
    ],
)
def test_an_authored_x_touch_prints_the_surface_and_paper_its_axis_set_counts(
    x_method, paper, contact
):
    data = x_touch("journal", 40, x_method=x_method)
    data.plan["setups"][0]["zero"]["tool_touches"][0]["x_paper_mm"] = paper
    _, row = x_row(data)
    printed = x_printed(data, row)
    assert x_method in printed, printed
    assert "journal Ø" in printed and contact in printed, printed


def test_a_derived_x_re_touch_prints_the_surface_and_that_it_takes_no_paper():
    ops = [*LATHE_OPS, op(50, "face", "dome", "turner", to_z=0.0)]
    data = bundle("lathe", lathe_zero([BLADE]), ops)
    [touch] = evaluate(data)[0].numbers["derived_touches"]
    printed = x_printed(data, touch)
    # Its Axis Set is the measured diameter alone: a direct touch on the journal.
    assert "journal Ø" in printed and "no paper" in printed, printed
    assert printed.endswith("Axis Set X measured Ø."), printed


def test_a_trial_cut_is_withdrawn_along_z_and_the_spindle_stopped_before_it_is_measured():
    # The X zero's trial cut and a blade's own: the tool backs off along Z only (its X is
    # what the Axis Set counts) and the spindle stops before the mic touches the work.
    touch = {**BLADE, "x_method": "trial_cut_measure"}
    del touch["x_face"]
    sheet, setup = sheet_of(bundle("lathe", lathe_zero([touch]), LATHE_OPS))
    tools = {("tools", "turner"): "T1 turner", ("tools", "parter"): "T2 parter"}
    html = sheet.dro(setup, tools)
    text = " ".join(unescape(re.sub(r"<[^>]+>", " ", html)).split())
    steps = re.findall(r"trial cut.*?measure", text)
    assert len(steps) == 2, text
    for step in steps:
        assert "withdraw along Z without moving X, stop the spindle," in step, step


def test_authored_prose_keeps_its_proper_nouns_as_written():
    # Shop words come from the plan's own identifiers; a maker's or vendor's name an author
    # wrote is a name to look up, printed as written.
    sheet, setup = sheet_of(bundle("lathe", lathe_zero([]), LATHE_OPS))
    note = "Buttons from McMaster, oil from LittleMachineShop, ProTap on the tap."
    assert sheet.bench(note, setup) == note


# A Z touch the checker credited with the kernel face its cut produced (zero_check
# ``credited_faces``): the raw STEP reference, so the sheet and the report name one plane.
FACE = "#533/ADVANCED_FACE[12]/P02"


def credited(data, path, faces):
    """The setup's sheet with ``faces`` on the zero row at ``path`` (keys / list indexes)."""
    import copy
    import dataclasses

    finding = evaluate(data)[0]
    numbers = copy.deepcopy(finding.numbers)
    row = numbers
    for step in path:
        row = row[step]
    row["credited_faces"] = faces
    sheet = _Traveler(data, [dataclasses.replace(finding, numbers=numbers)], {}, {})
    return sheet, data.plan["setups"][0]


def zero_rows(html):
    """``{axis: (touch / pick up, Axis Set)}`` of the DRO ZERO table, as printed."""
    markup = dro_markup(html)
    headings = ["axis", "touch / datum", "Axis Set", "check jog", "must read", "if reversed"]
    (table,) = [
        table
        for table in markup.nodes
        if table["tag"] == "table"
        and [
            content(cell).strip()
            for cell in markup.nodes
            if cell["tag"] == "th" and cell["parent"]["parent"]["parent"] is table
        ]
        == headings
    ]
    rows = {}
    for row in markup.nodes:
        if (
            row["tag"] != "tr"
            or row["parent"]["tag"] != "tbody"
            or row["parent"]["parent"] is not table
        ):
            continue
        cells = [
            " ".join(content(cell).split())
            for cell in markup.nodes
            if cell["tag"] == "td" and cell["parent"] is row
        ]
        assert len(cells) == len(headings), cells
        axis, contact, setting, *_ = cells
        assert axis not in rows, axis
        rows[axis] = (contact, setting)
    assert rows
    return rows


def test_a_credited_z_zero_keeps_native_proof_in_the_report_not_the_contact():
    ops = [op(10, "spot", "hole", "centre/1"), op(20, "drill", "hole", "drill")]
    tools = {("tools", "centre/1"): "T1 centre drill", ("tools", "drill"): "T2 drill"}
    sheet, setup = credited(bundle("mill", mill_zero(DECK), ops), ("axes", "z"), [FACE])
    contact, axis_set = zero_rows(sheet.dro(setup, tools))["Z"]
    assert "deck" in contact and "produced plane" not in contact and FACE not in contact, contact
    assert sheet.records[("zero_check", setup["id"])]["axes"]["z"]["credited_faces"] == [FACE]
    assert exact_number(axis_set) == Decimal("10.05")
    # Native proof metadata never changes the operator's named contact or setting.
    plain, setup = sheet_of(bundle("mill", mill_zero(DECK), ops))
    html = plain.dro(setup, tools)
    assert exact_number(zero_rows(html)["Z"][1]) == Decimal("10.05")
    assert "produced plane" not in sheet_text(html) and "ADVANCED_FACE" not in html


@pytest.mark.parametrize("faces", [[], "unknown"])
def test_an_absent_or_unknown_credit_prints_no_plane(faces):
    ops = [op(10, "spot", "hole", "centre/1"), op(20, "drill", "hole", "drill")]
    sheet, setup = credited(bundle("mill", mill_zero(DECK), ops), ("axes", "z"), faces)
    html = sheet.dro(setup, {})
    assert "produced plane" not in sheet_text(html) and "unknown" not in zero_rows(html)["Z"][0]


def test_a_credited_derived_touch_keeps_native_proof_out_of_the_operator_recipe():
    ops = [op(10, "spot", "hole", "centre/1"), op(20, "drill", "hole", "drill")]
    tools = {("tools", "centre/1"): "T1 centre drill", ("tools", "drill"): "T2 drill"}
    sheet, setup = credited(
        bundle("mill", mill_zero(DECK), ops), ("derived_touches", 0), [FACE, FACE + "b"]
    )
    (line,) = [line for line in dro_paragraphs(sheet.dro(setup, tools)) if "install" in line]
    assert axis_set_value(line, "Z") == Decimal("10.05")
    assert "produced plane" not in line and FACE not in line, line
    assert sheet.records[("zero_check", setup["id"])]["derived_touches"][0]["credited_faces"] == [
        FACE,
        FACE + "b",
    ]


def test_a_credited_listed_retouch_keeps_native_proof_out_of_both_operator_recipes():
    zero = mill_zero({"face": "top", "tool": "mill"}, retouch_after=[10, 20])
    ops = [
        op(10, "face", "deck", "mill", to_z=0.0),
        op(20, "face", "deck", "mill", to_z=0.0),
        op(30, "drill", "hole", "drill"),
    ]
    data = bundle("mill", zero, ops, {"top_z": 2.0})
    ops_listed = [row["op"] for row in evaluate(data)[0].numbers["retouch"]]
    sheet, setup = credited(data, ("retouch", ops_listed.index(10)), [FACE])
    tools = {("tools", "mill"): "T1 end mill", ("tools", "drill"): "T2 drill"}
    lines = dro_paragraphs(sheet.dro(setup, tools))
    (first,) = [line for line in lines if re.search(r"\bAfter op 10\b", line)]
    (second,) = [line for line in lines if re.search(r"\bAfter op 20\b", line)]
    assert axis_set_value(first, "Z") == Decimal("0.05")
    assert "produced plane" not in first and FACE not in first, first
    assert axis_set_value(second, "Z") == Decimal("0.05")
    assert "produced plane" not in second and FACE not in second, second
    assert sheet.records[("zero_check", setup["id"])]["retouch"][ops_listed.index(10)][
        "credited_faces"
    ] == [FACE]


def test_a_native_proof_reference_never_becomes_operator_markup():
    ops = [op(10, "spot", "hole", "centre/1"), op(20, "drill", "hole", "drill")]
    hostile = "#7/ADVANCED_FACE[1]/<b>&P"
    sheet, setup = credited(bundle("mill", mill_zero(DECK), ops), ("axes", "z"), [hostile])
    html = sheet.dro(setup, {})
    assert "<b>" not in html and "&lt;b&gt;&amp;P" not in html
    assert hostile not in zero_rows(html)["Z"][0]
    assert sheet.records[("zero_check", setup["id"])]["axes"]["z"]["credited_faces"] == [hostile]
