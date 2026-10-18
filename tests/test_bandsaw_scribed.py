"""A vertical bandsaw following a scribed curve, leaving stock to the line (#249)."""

import re
from copy import deepcopy

import pytest
from pydantic import ValidationError
from test_bench_saw import NATIVE, PLANE, saw, saw_bundle, scribed

from prechips import kernel
from prechips.inputs import load_bundle
from prechips.model import Inventory
from prechips.rules import saw_cut, speeds_feeds, tool_resolves
from prechips.rules.resolution import saw_station
from prechips.sheet import _Traveler

ROW = {
    "material_class": "steel",
    "tool_material": "bimetal",
    "operation": "saw_cut",
    "sfm": 120.0,
    "cite": "synthetic test cutting data",
}


def bandsaw_bundle(modes=("horizontal", "vertical"), op=None, kind="bandsaw", **machine):
    bundle = saw_bundle(
        kind, "bandsaw", op=op or scribed(), kernel={"status": "ok", "ops": {"S2:20": NATIVE}}
    )
    station = bundle.inventory["machines"]["station"]
    station.update(machine)
    if modes is not None:
        station["saw_modes"] = list(modes)
    bundle.plan["stock"] = {"material": "steel"}
    bundle.cutting_data.update(aliases={"steel": "steel"}, cut=[dict(ROW)])
    return bundle


# ------------------------------------------------- the vertical-mode station, one verdict


@pytest.mark.parametrize(
    "bundle_args, station, assembly, verdict, routed",
    [
        ({}, "fits", "pass", "pass", "bandsaw"),
        ({"modes": ("horizontal",)}, "no_vertical_mode", "error", "error", "refused"),
        ({"modes": None}, "unknown", "unknown", "unknown", "unresolved"),
        ({"verify": True}, "unknown", "unknown", "unknown", "unresolved"),
        ({"kind": "bench"}, "wrong_station", "error", "error", "refused"),
        ({"kind": "mill"}, "wrong_station", "error", "error", "refused"),
    ],
    ids=["vertical", "horizontal-only", "modes-undeclared", "machine-unverified", "bench", "mill"],
)
def test_a_bandsaw_follows_a_line_only_in_vertical_mode(
    bundle_args, station, assembly, verdict, routed
):
    bundle = bandsaw_bundle(**bundle_args)
    setup, op = bundle.plan["setups"][0], bundle.plan["setups"][0]["ops"][0]
    assert saw_station(bundle, setup, op) == station
    row = next(row for row in tool_resolves.evaluate(bundle) if row.subject == "S2:20")
    assert row.status == assembly
    finding = saw_cut.evaluate(bundle)[0]
    assert finding.status == verdict
    if station == "unknown" and "modes" in bundle_args:
        assert "declare the saw_modes of machine station" in finding.sentence
    assert kernel.op_inputs(bundle, setup, op)["saw_tool"] == routed


def test_a_straight_bandsaw_cut_needs_no_vertical_mode():
    bundle = bandsaw_bundle(modes=("horizontal",), op=saw(tool="hacksaw", cut_plane=PLANE))
    setup, op = bundle.plan["setups"][0], bundle.plan["setups"][0]["ops"][0]
    assert saw_station(bundle, setup, op) == "fits"


def test_unverified_kerf_leaves_the_vertical_cut_unresolved():
    bundle = bandsaw_bundle()
    bundle.inventory["tools"]["hacksaw"]["kerf_mm"] = {"value": "unknown", "verify": True}
    setup, op = bundle.plan["setups"][0], bundle.plan["setups"][0]["ops"][0]
    assert saw_station(bundle, setup, op) == "unknown"
    assert saw_cut.evaluate(bundle)[0].status == "unknown"


def test_saw_modes_are_horizontal_or_vertical():
    with pytest.raises(ValidationError):
        Inventory.model_validate({"machines": {"saw": {"kind": "bandsaw", "saw_modes": ["tilt"]}}})


# ------------------------------------------------------------ hand-fed blade speed


def test_a_vertical_cut_is_fed_by_hand_with_a_sourced_blade_speed():
    row = speeds_feeds.evaluate(bandsaw_bundle(blade_speed_sfm=[80, 200]))[0]
    assert row.status == "pass", row.sentence
    assert row.numbers["blade_speed_sfm"] == 120.0
    assert row.numbers["feed_mm_min"] == "not_applicable"


def test_a_straight_bandsaw_cut_keeps_its_descent_feed_screen():
    bundle = bandsaw_bundle(op=saw(cut_plane=PLANE), blade_speed_sfm=[80, 200])
    row = speeds_feeds.evaluate(bundle)[0]
    assert row.status == "unknown"
    assert row.numbers["feed_mm_min"] == "unknown"


def test_the_vertical_bandsaw_card_names_the_line_and_the_stock_to_leave():
    bundle = bandsaw_bundle(blade_speed_sfm=[80, 200])
    findings = saw_cut.evaluate(bundle) + speeds_feeds.evaluate(bundle)
    setup = bundle.plan["setups"][0]
    html, _, _, _ = _Traveler(bundle, findings, {}, None).operations(setup, {}, {"notes": 2})
    text = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html))
    assert "outside the line scribed in S1 op 10" in text
    assert "by hand along the line" in text
    assert "leave at least 0.500 mm outside the line, the scribed line still showing" in text
    assert "STOP: no feed" not in text


# ------------------------------------------------- the offset scribed arc the kernel clips to


@pytest.fixture(scope="module")
def rocker():
    return load_bundle("examples/rocker-arm/plan.toml")


def _follow(bundle, scribe, sid="S4"):
    data = deepcopy(bundle)
    setup = next(each for each in data.plan["setups"] if each["id"] == sid)
    op = {"op": 99, "do": "saw_cut", "tool": "bandsaw-blade-4-6", "follows": scribe}
    op.update(allowance_mm=0.45)
    return data, setup, op


@pytest.mark.parametrize(
    "scribe, radius, remove",
    [("S4:10", 800.0, "inside"), ("S4:20", 816.0, "outside")],
    ids=["top-edge", "profile-outer"],
)
def test_the_kernel_gets_the_scribed_arc_in_the_saw_setup(rocker, scribe, radius, remove):
    data, setup, op = _follow(rocker, scribe)
    profile = kernel.scribed_profile(data, setup, op)
    assert profile == {"centre_mm": [0.0, 808.0], "radius_mm": radius, "remove": remove}


def test_an_unplaceable_scribed_arc_is_debt_not_a_box(rocker):
    data, setup, op = _follow(rocker, "S4:10")
    setup["frame"] = "unknown"
    assert "layout in setup S4 is unknown" in kernel.scribed_profile(data, setup, op)["reason"]


def test_an_arc_not_in_the_saw_setups_xy_plane_is_debt(rocker):
    data, setup, op = _follow(rocker, "S4:10")
    tilted = deepcopy(data.plan["frames"][setup["frame"]])
    tilted.update(y=[0.0, 0.0, 1.0], z=[0.0, -1.0, 0.0])
    data.plan["frames"]["TILT"] = tilted
    setup["frame"] = "TILT"
    profile = kernel.scribed_profile(data, setup, op)
    assert profile is not None
    assert "does not lie in setup S4's XY plane" in profile.get("reason", ""), profile


def test_a_straight_scribed_line_keeps_the_declared_box(rocker):
    data, setup, op = _follow(rocker, "S4:10")
    scribe_op = next(each for each in setup["ops"] if each["op"] == 10)
    scribe_op["feature"] = "strap_datum_b"
    assert kernel.scribed_profile(data, setup, op) is None
