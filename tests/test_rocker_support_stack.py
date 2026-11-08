"""Current rocker bearing stack: one native subplate, one M5 contribution.

The oracle uses the authored solids' contact planes, the raw strap and the completed
first face, not a saved report or M5's own height/band helpers. Inventory measurements
are explicitly illustrative demonstration facts, never evidence of shop acceptance.
The native cases run the unmodified current route once and require its actual arriving
stock, exact fixture scene and boolean interference results. They need FreeCAD and all
current bundle assets; historical STEP/manifests and expected packets are not inputs.
"""

from collections import Counter
from copy import deepcopy
from pathlib import Path

import pytest

from prechips.inputs import load_bundle
from prechips.kernel import _engine_hold, hold_inputs, run_geometry
from prechips.rules import envelope, tip_endpoints
from prechips.rules._envelope import fixture_height

ROOT = Path(__file__).resolve().parents[1]
SETUPS = ("P1", "P1E", "P2", "P2E")


@pytest.fixture(scope="module")
def rocker():
    return load_bundle(ROOT / "examples/rocker-arm/plan.toml")


@pytest.fixture(scope="module")
def native_rocker(freecad_kernel):
    # Do not truncate/reorder the route or invent stock for the reholds. The normal
    # content-addressed kernel cache can reuse the parent's actual-route proof.
    bundle = load_bundle(ROOT / "examples/rocker-arm/plan.toml")
    with pytest.MonkeyPatch.context() as patch:
        patch.setenv("FREECAD_CMD", freecad_kernel)
        facts = run_geometry(bundle)
    assert facts["status"] == "ok", facts.get("reason")
    return bundle, facts


def _setup(bundle, name):
    return next(setup for setup in bundle.plan["setups"] if setup["id"] == name)


def _primitive(item, name):
    (solid,) = [solid for solid in item["solids"] if solid["name"] == name]
    assert not solid.get("void")
    assert solid["shape"] == "box"
    return solid


def _posed_box(solid, pose):
    # All four actual holds are upright in their respective setup axes, including
    # the reversed work. A rotated/tilted redesign must update this physical oracle.
    assert pose["x"] == [1, 0, 0]
    assert pose["z"] == [0, 0, 1]
    low = [a + b for a, b in zip(solid["at_mm"], pose["origin_mm"], strict=True)]
    return low + [a + b for a, b in zip(low, solid["size_mm"], strict=True)]


def _arriving_z(bundle, setup):
    """Independently derive the two extremal stock planes before these face cuts."""
    (strap,) = [stock for stock in bundle.plan["stock"]["components"] if stock["id"] == "strap"]
    assert strap["axis"] == [1, 0, 0]
    assert strap["section_axis"] == [0, 1, 0]
    bottom = strap["origin_mm"][2]
    top = bottom + strap["section_mm"][1]
    frame = bundle.plan["frames"][setup["frame"]]
    if setup["id"] in ("P2", "P2E"):
        first = _setup(bundle, "P1")
        first_frame = bundle.plan["frames"][first["frame"]]
        (face,) = first["ops"]
        # P1 finishes the centre; P1E finishes BOTH ears to the same model plane.
        ears = _setup(bundle, "P1E")["ops"]
        assert len(ears) == 2
        assert all(op["to_z"] == face["to_z"] for op in ears)
        top = first_frame["origin"][2] + first_frame["z"][2] * face["to_z"]
    assert frame["z"] in ([0, 0, 1], [0, 0, -1])
    # The still-uncut ears retain the incoming maximum in P1E and P2E.
    return sorted((z - frame["origin"][2]) * frame["z"][2] for z in (bottom, top))


def _geometry(bundle, setup):
    hold = setup["hold"]
    assert hold["fixture"] == "rocker-strip-mechanical-plate"
    assert hold["riser"] == "rocker-table-subplate"
    (support,) = hold["supports"]
    assert support["placement"] == "posed"
    assert support["ref"] == hold["riser"]
    assert support["id"] == "table-base"
    primary = bundle.inventory["fixtures"][hold["fixture"]]
    subplate = bundle.inventory["fixtures"][support["ref"]]
    base_box = _posed_box(_primitive(primary, "base"), hold["pose"])
    plate_box = _posed_box(_primitive(subplate, "tooling-subplate"), support["pose"])
    bearing = plate_box[5] - plate_box[2]
    primary_rise = base_box[5] - base_box[2]
    assert bearing == pytest.approx(16)
    assert primary_rise == pytest.approx(22)
    assert plate_box[5] == pytest.approx(base_box[2])
    assert subplate["height_mm"]["value"] == pytest.approx(bearing)
    assert primary["height_mm"]["value"] == pytest.approx(primary_rise)
    assert subplate["height_mm"]["measured"]["status"] == "measured"
    assert primary["height_mm"]["measured"]["status"] == "measured"
    stock_z = _arriving_z(bundle, setup)
    assert base_box[5] == pytest.approx(stock_z[0])
    assert [setup["stock_state"][key] for key in ("bottom_z", "top_z")] == pytest.approx(stock_z)
    # The table is the plate's underside, NOT the bottom of its T-slot fasteners.
    nuts = [solid for solid in subplate["solids"] if solid["name"].endswith("-tnut")]
    assert len(nuts) == 2
    for nut in nuts:
        box = _posed_box(nut, support["pose"])
        assert box[2] < box[5] < plate_box[2]
    return base_box, plate_box, stock_z


def _assembly(bundle, setup, op):
    # Read the installed pair directly, independently of M5's projection resolver.
    root, member = op["tool"].split("/", 1)
    tool = bundle.inventory["tools"][root]["members"][member]
    projection = tool["projection_mm"][op["holder"]]
    holder_root, _ = op["holder"].split("/", 1)
    gauge = bundle.inventory["holders"][holder_root]["gauge_len_mm"]
    assert projection["measured"]["status"] == gauge["measured"]["status"] == "measured"
    # The ear operations really select the longer 3/8 cutter, not the 1/4 cutter.
    assert projection["value"] == (25 if setup["id"] in ("P1", "P2") else 38)
    assert gauge["value"] == 6
    return projection["value"], gauge["value"]


def _assert_m5(bundle, setup, row, base_box, plate_box, stock_z):
    ear_setup = setup["id"] in ("P1E", "P2E")
    assert row.status == ("unknown" if ear_setup else "pass"), row.sentence
    if ear_setup:
        # The first disjoint ear cut does not establish a global top for op 20.
        # This pre-existing route debt is independent of the known bearing rise:
        # do not turn its partial Z band into a clearance certification.
        arriving = {op["op"]: before for op, before, _ in tip_endpoints.stock_states(bundle, setup)}
        assert arriving[20]["top_z"] == "unknown"
        assert any(
            debt["id"] == f"plan.setups.{setup['id']}.ops.20.z_geometry"
            for debt in row.numbers["measurements"]
        )
    assert "supported_height_datum" not in row.numbers
    rise = base_box[5] - plate_box[2]
    assert row.numbers["fixture_height_mm"] == pytest.approx(rise)
    stacks = {stack["op"]: stack for stack in row.numbers["stacks"]}
    assert set(stacks) == {op["op"] for op in setup["ops"]}
    for op in setup["ops"]:
        projection, gauge = _assembly(bundle, setup, op)
        assert op["do"] == "face"
        # These disjoint central/ear cuts leave uncut stock at the incoming maximum
        # until their last cut. Approach is above that top, not above finished Z0.
        tip_band = [op["to_z"], stock_z[1] + op["approach_mm"]]
        expected = [tip - plate_box[2] + projection + gauge for tip in tip_band]
        stack = stacks[op["op"]]
        assert stack["tool_projection_mm"] == projection
        assert stack["holder_gauge_len_mm"] == gauge
        assert stack["stack_mm"] == pytest.approx(
            rise + stock_z[1] - stock_z[0] + projection + gauge
        )
        if ear_setup and op["op"] == 20:
            assert stack["verified"] is False
            continue
        assert stack["verified"] is True
        assert stack["tip_z_bounds_mm"] == pytest.approx(tip_band)
        assert stack["spindle_nose_table_band_mm"] == pytest.approx(expected)
        assert stack["lower_margin_mm"] >= 0
        assert stack["upper_margin_mm"] >= 0
        # In particular the subplate is neither omitted nor counted a second time.
        assert expected[0] - (op["to_z"] - base_box[2] + projection + gauge) == pytest.approx(
            plate_box[5] - plate_box[2]
        )


@pytest.mark.parametrize("name", SETUPS)
def test_current_custom_stack_counts_table_bearing_once(rocker, name):
    setup = _setup(rocker, name)
    base_box, plate_box, _ = _geometry(rocker, setup)
    debts = {}
    height, verified = fixture_height(rocker, setup, debts, [])
    assert verified and not debts, debts
    assert height == pytest.approx(base_box[5] - plate_box[2])
    for op in setup["ops"]:
        _assembly(rocker, setup, op)


@pytest.mark.parametrize("name", SETUPS)
def test_missing_riser_is_not_the_same_known_current_stack(rocker, name):
    # The explicit bearing role is required even though the same physical subplate
    # remains posed. Generic malformed/matched datum cases live in their own suite.
    data = deepcopy(rocker)
    setup = _setup(data, name)
    base_box, plate_box, _ = _geometry(data, setup)
    before = _engine_hold(hold_inputs(data, setup))
    del setup["hold"]["riser"]
    assert _engine_hold(hold_inputs(data, setup)) == before
    row = next(row for row in envelope.evaluate(data) if row.subject == name)
    assert row.numbers["fixture_height_mm"] != pytest.approx(base_box[5] - plate_box[2])
    for stack in row.numbers["stacks"]:
        op = next(op for op in setup["ops"] if op["op"] == stack["op"])
        projection, gauge = _assembly(data, setup, op)
        known_minimum = op["to_z"] - plate_box[2] + projection + gauge
        band = stack["spindle_nose_table_band_mm"]
        if band == "unknown":
            assert not stack["verified"]
            assert row.status != "pass", row.sentence
        else:
            assert band[0] != pytest.approx(known_minimum)
            assert band[0] == pytest.approx(known_minimum - (plate_box[5] - plate_box[2]))


@pytest.mark.parametrize("name", SETUPS)
def test_native_current_subplate_is_one_seated_noninterpenetrating_instance(native_rocker, name):
    bundle, facts = native_rocker
    setup = _setup(bundle, name)
    base_box, plate_box, stock_z = _geometry(bundle, setup)
    detail = facts["setups"][name]
    assert "stock_reason" not in detail, detail.get("stock_reason")
    assert [detail["stock_bbox_mm"][i] for i in (2, 5)] == pytest.approx(stock_z)
    assert detail["stock_volume_mm3"] > 0
    assert detail["fixture_rendered"] is True
    assert detail["fixture_clashes"] == [], detail["fixture_clashes"]
    assert detail["fixture_clash_debts"] == [], detail["fixture_clash_debts"]
    scene = detail["render_scene"]
    assert scene["debts"] == [], scene["debts"]
    components = scene["components"]
    assert components and all(component["exact"] for component in components)
    subplate = bundle.inventory["fixtures"][setup["hold"]["riser"]]
    expected_names = Counter(
        f"support table-base:{solid['name']}"
        for solid in subplate["solids"]
        if not solid.get("void")
    )
    actual = [component for component in components if component.get("support_id") == "table-base"]
    assert Counter(component["name"] for component in actual) == expected_names
    assert all(component["ref"] == f"fixtures.{setup['hold']['riser']}" for component in actual)
    # Check the physical instances globally, not just a support-id filtered count.
    (plate,) = [
        component for component in components if component["name"].endswith(":tooling-subplate")
    ]
    (base,) = [
        component
        for component in components
        if component["name"] == f"{setup['hold']['fixture']}:base"
    ]
    assert plate["bbox_mm"] == pytest.approx(plate_box)
    assert base["bbox_mm"] == pytest.approx(base_box)
    assert base["bbox_mm"][2] == pytest.approx(plate["bbox_mm"][5])
    assert base["bbox_mm"][5] == pytest.approx(detail["stock_bbox_mm"][2])
    assert not any(component["role"] == "riser" for component in components)
    # M5 consumes the same real route proof but gets its expectation from these
    # independent table/contact/stock planes, not from native report stack fields.
    row = next(row for row in envelope.evaluate(bundle) if row.subject == name)
    _assert_m5(bundle, setup, row, base_box, plate_box, stock_z)
