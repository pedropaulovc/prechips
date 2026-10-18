"""A hand-fed hold: a vertical bandsaw cut along a scribed line, nothing clamping the work
(#335)."""

import json
import re

import pytest
from pydantic import ValidationError
from test_bandsaw_scribed import bandsaw_bundle
from test_bench_saw import PLANE, plan, saw, scribed
from test_cli import ROOT, copy_examples, run_cli

from prechips import kernel
from prechips.inputs import BadInput, load_bundle
from prechips.kernel.render_inputs import hand_fed_scene
from prechips.model import Plan
from prechips.rules import fixture_interference, hold_fields, stock_diameter, thin_wall_under_clamp
from prechips.rules import vise as vise_rule
from prechips.rules.resolution import hand_fed
from prechips.sheet import _Traveler

HAND_FED = {"kind": "hand_fed", "note": "flat on the saw table"}
FEEDING = {
    "guide_above_mm": 6.0,
    "push_aid": "push-stick",
    "feed_from": "-X",
    "end_support": "push_aid",
}
BUNDLE = ROOT / "examples" / "geometry" / "hand-fed-saw"


def hand_fed_bundle(op=None, **machine):
    bundle = bandsaw_bundle(op=op, blade_speed_sfm=[80, 200], **machine)
    setup = bundle.plan["setups"][0]
    setup.update(
        hold={**HAND_FED, **FEEDING},
        coolant="none: dry cut",
        deburr_mm=0.0,
        stock_state={"top_z": 2.5, "bottom_z": 0.0},
    )
    bundle.inventory["fixtures"] = {"push-stick": {"kind": "push_stick", "name": "push stick"}}
    return bundle


def hold_text(bundle):
    setup = bundle.plan["setups"][0]
    steps, _ = _Traveler(bundle, hold_fields.evaluate(bundle), {}, None).hold(setup)
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", steps))


def row(rule, bundle, subject="S2"):
    return next(each for each in rule.evaluate(bundle) if each.subject == subject)


# ------------------------------------------------------------------ admitted: decided


def test_a_hand_fed_vertical_saw_cut_owes_no_holding_declaration():
    bundle = hand_fed_bundle()
    assert hand_fed(bundle, bundle.plan["setups"][0]) == ("admitted", "")
    finding = row(hold_fields, bundle)
    assert finding.status == "pass", finding.sentence
    assert finding.numbers["missing"] == []
    assert finding.numbers["fixture"] == "not_applicable"


def test_a_hand_fed_cut_has_no_collet_or_chuck_to_check():
    assert row(stock_diameter, hand_fed_bundle()).status == "not_applicable"


def test_the_kernel_gets_no_fixture_and_no_fixture_debt():
    bundle = hand_fed_bundle()
    hold = kernel.hold_inputs(bundle, bundle.plan["setups"][0])
    assert hold["kind"] == "hand_fed"
    assert hold["measurement_debts"] == [] and hold["gaps"] == []


def test_scribe_deburr_and_inspect_may_share_the_saw_table():
    bundle = hand_fed_bundle()
    ops = bundle.plan["setups"][0]["ops"]
    ops += [{"op": 30, "do": "deburr"}, {"op": 40, "do": "inspect"}]
    assert hand_fed(bundle, bundle.plan["setups"][0])[0] == "admitted"


def test_the_hold_prints_the_hand_fed_line_and_no_stop():
    bundle = hand_fed_bundle()
    setup = bundle.plan["setups"][0]
    findings = hold_fields.evaluate(bundle)
    steps, _ = _Traveler(bundle, findings, {}, None).hold(setup)
    text = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", steps))
    assert "fed by hand on the saw table" in text.lower()
    assert "outside the line scribed in S1 op 10" in text
    assert "STOP" not in text


# ------------------------------------------------- unresolved scope stays unknown


@pytest.mark.parametrize(
    "machine", [{"modes": None}, {"verify": True}], ids=["modes-undeclared", "unverified"]
)
def test_an_unresolved_saw_leaves_the_hand_fed_hold_unknown(machine):
    bundle = hand_fed_bundle(**machine)
    assert hand_fed(bundle, bundle.plan["setups"][0])[0] == "unresolved"
    assert row(hold_fields, bundle).status == "unknown"
    assert row(stock_diameter, bundle).status == "unknown"
    assert kernel.hold_inputs(bundle, bundle.plan["setups"][0])["kind"] == "unknown"


def test_an_unknown_hold_kind_decides_nothing():
    bundle = hand_fed_bundle()
    bundle.plan["setups"][0]["hold"] = {"kind": "unknown"}
    finding = row(hold_fields, bundle)
    assert finding.status == "unknown"
    assert "hold.kind" in finding.numbers["missing"]


# ----------------------------------------------------- refused scope: exit 3 at load


@pytest.mark.parametrize(
    "op, extra, machine",
    [
        (None, {"op": 30, "do": "rough_profile", "feature": "arc"}, {}),
        (None, None, {"modes": ("horizontal",)}),
        (saw(tool="hacksaw", cut_plane=PLANE), None, {}),
        (None, {"op": 30, "do": "file_to_line", "feature": "arc"}, {}),
        (None, None, {"kind": "mill"}),
    ],
    ids=["milling-op", "horizontal-only", "straight-cut", "filing", "mill"],
)
def test_a_hand_fed_hold_outside_its_scope_is_refused(op, extra, machine):
    bundle = hand_fed_bundle(op=op, **machine)
    if extra:
        bundle.plan["setups"][0]["ops"].append(extra)
    scope, why = hand_fed(bundle, bundle.plan["setups"][0])
    assert scope == "refused" and why
    assert row(hold_fields, bundle).status == "error"


def test_a_hand_saw_is_not_a_hand_fed_bandsaw_cut():
    bundle = hand_fed_bundle()
    bundle.inventory["tools"]["hacksaw"]["kind"] = "hand_saw"
    bundle.inventory["machines"]["station"]["kind"] = "bench"
    assert hand_fed(bundle, bundle.plan["setups"][0])[0] == "refused"


@pytest.fixture
def example(tmp_path):
    return copy_examples(tmp_path) / "geometry" / "hand-fed-saw"


def edit(directory, old, new):
    path = directory / "plan.toml"
    text = path.read_text(encoding="utf-8")
    assert old in text
    path.write_text(text.replace(old, new), encoding="utf-8")
    return path


def test_the_example_loads_with_its_hand_fed_hold():
    bundle = load_bundle(BUNDLE / "plan.toml")
    assert hand_fed(bundle, bundle.plan["setups"][1])[0] == "admitted"


@pytest.mark.parametrize(
    "old, new, words",
    [
        ('machine = "test-bandsaw"', 'machine = "test-bench"', "not a bandsaw"),
        (
            'follows = "S1:10"\nallowance_mm = 0.45\n'
            "stock_removal_bounds = { x = [-147.5, 147.5], y = [7.0, 22.5], z = [-9.0, 2.0] }",
            'cut_plane = { axis = "y", value = 21.0, keep = "below" }',
            "straight saw cut",
        ),
    ],
    ids=["bench", "straight-cut"],
)
def test_loading_an_out_of_scope_hand_fed_hold_is_bad_input(example, old, new, words):
    with pytest.raises(BadInput, match=words):
        load_bundle(edit(example, old, new))


def test_a_horizontal_only_bandsaw_refuses_the_hand_fed_hold_with_exit_3(example, tmp_path):
    inventory = example / "inventory.toml"
    text = inventory.read_text(encoding="utf-8")
    inventory.write_text(text.replace('["horizontal", "vertical"]', '["horizontal"]'), "utf-8")
    result = run_cli("check", example / "plan.toml", "--out", tmp_path / "out")
    assert result.returncode == 3, result.stdout + result.stderr
    assert "vertical saw_modes" in result.stdout + result.stderr


# ------------------------------------------------------------- schema: nothing else


@pytest.mark.parametrize("field", ["fixture", "stop", "clamp", "grip_mm", "fixed_jaw"])
def test_a_hand_fed_hold_declares_no_fixture_field(field):
    data = plan(scribed())
    data["setups"][1]["hold"] = {**HAND_FED, field: "not_applicable"}
    with pytest.raises(ValidationError, match=f"declares no {field}"):
        Plan.model_validate(data)


def test_a_hand_fed_hold_with_only_its_note_is_valid():
    data = plan(scribed())
    data["setups"][1]["hold"] = dict(HAND_FED)
    Plan.model_validate(data)


# ------------------------------------------- geometry screens: no fixture to check


@pytest.mark.parametrize("rule", [vise_rule, thin_wall_under_clamp, fixture_interference])
def test_the_fixture_screens_do_not_apply_to_a_hand_fed_hold(rule, freecad_kernel):
    bundle = load_bundle(BUNDLE / "plan.toml")
    kernel.run_geometry(bundle)
    assert row(rule, bundle).status == "not_applicable"


def test_an_unclaimed_hold_kind_never_borrows_the_hand_fed_waiver():
    bundle = hand_fed_bundle()
    bundle.plan["setups"][0]["hold"] = {"fixture": "unknown"}
    assert hand_fed(bundle, bundle.plan["setups"][0]) == ("fixture", "")
    assert row(stock_diameter, bundle).status == "unknown"


# ------------------------------- a known machine refuses whatever the blade's debt (review)


@pytest.mark.parametrize(
    "machine, words",
    [({"kind": "mill"}, "is a mill"), ({"modes": ("horizontal",)}, "no vertical saw_modes")],
    ids=["mill", "horizontal-only"],
)
def test_a_known_machine_out_of_scope_is_refused_with_an_unverified_blade(machine, words):
    bundle = hand_fed_bundle(**machine)
    bundle.inventory["tools"]["hacksaw"]["verify"] = True
    scope, why = hand_fed(bundle, bundle.plan["setups"][0])
    assert scope == "refused" and words in why


def test_an_unresolved_hand_fed_hold_prints_a_stop_not_the_hand_fed_line():
    bundle = hand_fed_bundle(verify=True)
    setup = bundle.plan["setups"][0]
    steps, _ = _Traveler(bundle, hold_fields.evaluate(bundle), {}, None).hold(setup)
    text = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", steps))
    assert "STOP" in text
    assert "fed by hand on the saw table" not in text.lower()


def test_an_unresolved_hand_fed_scope_is_owed_as_the_scope_not_the_kind():
    finding = row(hold_fields, hand_fed_bundle(verify=True))
    assert finding.numbers["missing"] == ["hand_fed_scope"]


def test_compare_lists_no_unknown_fixture_for_a_hand_fed_setup(example):
    plan = edit(
        example,
        'hold = { fixture = "unknown", stop = "unknown", grip_mm = "unknown", '
        'clamp = "unknown", fixed_jaw = "unknown" }',
        'hold = { fixture = "test-bench", stop = "unknown", grip_mm = "unknown", '
        'clamp = "unknown", fixed_jaw = "unknown" }',
    )
    result = run_cli("compare", plan, "--json")
    assert result.returncode in (0, 2, 4), result.stderr
    # No unknown primary fixture for the hand-fed setup; its push aid is still listed.
    assert sorted(json.loads(result.stdout)[0]["fixtures"]) == ["test-bench", "test-push-stick"]


# ------------------------------------- declared feeding (machinist review of #342, 17e665d)


def test_the_hold_prints_each_declared_feeding_step():
    text = hold_text(hand_fed_bundle())
    assert "Upper blade guide: 6.000 mm above the top of the work." in text
    assert "Push aid: push stick." in text
    assert "Start the cut at the -X end of the line" in text
    assert "End of the cut: finish it with the push aid" in text
    assert "STOP" not in text


@pytest.mark.parametrize("field", sorted(FEEDING))
def test_an_undeclared_feeding_step_is_debt_that_stops(field):
    bundle = hand_fed_bundle()
    del bundle.plan["setups"][0]["hold"][field]
    finding = row(hold_fields, bundle)
    assert finding.status == "unknown"
    assert f"hold.{field}" in finding.numbers["missing"]
    assert "STOP" in hold_text(bundle)


@pytest.mark.parametrize("field, value", sorted(FEEDING.items()))
def test_only_a_hand_fed_hold_declares_feeding(field, value):
    data = plan(scribed())
    data["setups"][1]["hold"] = {"fixture": "vise", field: value}
    with pytest.raises(ValidationError, match="only a hand-fed hold"):
        Plan.model_validate(data)


@pytest.mark.parametrize("guide", [0.0, -1.0])
def test_the_upper_guide_height_is_positive(guide):
    data = plan(scribed())
    data["setups"][1]["hold"] = {**HAND_FED, "guide_above_mm": guide}
    with pytest.raises(ValidationError, match="must be positive"):
        Plan.model_validate(data)


def route_cell(bundle, sid):
    html = _Traveler(bundle, [], {}, None).header(bundle.plan["setups"])
    text = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html))
    match = re.search(rf"{sid} part as it arrives from Setup \S+ \S+ (.+?) (?:DRAWING|S\d)", text)
    return match.group(1) if match else text


def test_the_route_row_and_the_hold_agree_on_a_hand_fed_setup():
    bundle = load_bundle(BUNDLE / "plan.toml")
    setup = bundle.plan["setups"][1]
    steps, _ = _Traveler(bundle, [], {}, None).hold(setup)
    assert "Fed by hand on the saw table" in steps
    assert route_cell(bundle, "S2") == "fed by hand on the saw table"


def test_an_unresolved_hand_fed_setup_stops_in_the_route_and_the_hold(example):
    inventory = example / "inventory.toml"
    text = inventory.read_text(encoding="utf-8")
    inventory.write_text(text.replace('saw_modes = ["horizontal", "vertical"]\n', ""), "utf-8")
    bundle = load_bundle(example / "plan.toml")
    steps, _ = _Traveler(bundle, [], {}, None).hold(bundle.plan["setups"][1])
    assert "STOP" in steps and "Fed by hand" not in steps
    assert route_cell(bundle, "S2").startswith("STOP")


def scene(bundle, sid=1):
    return hand_fed_scene(bundle, bundle.plan["setups"][sid], 1.0)


def test_the_picture_draws_the_saw_path_from_the_declared_end_beside_the_scribed_line():
    bundle = load_bundle(BUNDLE / "plan.toml")
    drawn = scene(bundle)
    saw, line = drawn["paths"]
    assert saw["op"] == "10" and saw["directed"] is True and saw["feed"] is True
    assert line["dashed"] is True and "directed" not in line
    assert saw["xy"][0][0] < saw["xy"][-1][0]  # feed_from = "-X": it starts at -X
    keys = [key["label"] for key in drawn["waypoints"]]
    assert keys == ["START", "SAW PATH, LEAVE 0.450 MM MIN", "SCRIBED LINE", "WASTE"]
    assert all(key["plain"] for key in drawn["waypoints"])
    # The R800 top edge's saw removes inside the circle: the WASTE key points that way.
    assert drawn["waypoints"][-1]["xy"][1] > drawn["waypoints"][1]["xy"][1]


def test_the_picture_draws_the_saw_table_blade_and_push_aid():
    bundle = load_bundle(BUNDLE / "plan.toml")
    boxes = {box["name"]: box for box in scene(bundle)["boxes"]}
    assert set(boxes) == {"saw table", "push aid", "band op 10"}
    assert boxes["push aid"]["label"] == "PUSH STICK (TRAILING END)"
    # Fed from -X, the work trails at its +X end: the push aid stands past the max X.
    assert boxes["push aid"]["stock_mm"][0][0] == ("max", 0.0)
    assert boxes["band op 10"]["box_mm"][5] == pytest.approx(1.0 + 6.0)  # top + guide
    (feed,) = scene(bundle)["feed_lines"]
    assert feed["label"] == "FEED: SAW PATH (OP 10)"
    assert feed["xyz"][0][0] < feed["xyz"][-1][0] and feed["xyz"][0][2] == 1.0


def test_an_undeclared_feed_end_draws_no_arrows_start_band_or_push_aid():
    bundle = load_bundle(BUNDLE / "plan.toml")
    bundle.plan["setups"][1]["hold"].pop("feed_from")
    drawn = scene(bundle)
    assert drawn["paths"][0]["directed"] is False
    assert "START" not in [key["label"] for key in drawn["waypoints"]]
    assert [box["name"] for box in drawn["boxes"]] == ["saw table"]
    assert drawn["feed_lines"] == []


def test_a_fixture_hold_draws_no_hand_fed_scene():
    bundle = load_bundle(BUNDLE / "plan.toml")
    assert scene(bundle, 0) == {"paths": [], "waypoints": [], "boxes": [], "feed_lines": []}
