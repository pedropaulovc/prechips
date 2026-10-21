"""A hand-fed hold: a vertical bandsaw cut along a scribed line, nothing clamping the work
(#335)."""

import dataclasses
import json
import math
import re

import pytest
from pydantic import ValidationError
from test_bandsaw_scribed import bandsaw_bundle
from test_bench_saw import PLANE, plan, saw, scribed
from test_cli import ROOT, copy_examples, run_cli

from prechips import kernel
from prechips.inputs import BadInput, load_bundle
from prechips.kernel import render_diagram
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


MINIMUM = 76.2  # a 3 in finger-to-blade clearance
NUMBER = r"-?\d+(?:\.\d+)?(?!\d|\.\d)"


def entry_box(length, width=20.0):
    """A setup-entry stock box ``length`` long in X, ``width`` in Y, 2.5 thick."""
    return [0.0, 0.0, 0.0, length, width, 2.5]


def hand_fed_bundle(op=None, minimum=MINIMUM, box=None, **machine):
    """A hand-fed vertical bandsaw setup S2, its shop hand-feed minimum cited and verified
    and the kernel's setup-entry stock 300 x 20 mm unless given."""
    bundle = bandsaw_bundle(op=op, blade_speed_sfm=[80, 200], **machine)
    setup = bundle.plan["setups"][0]
    setup.update(
        hold={**HAND_FED, **FEEDING},
        coolant="none: dry cut",
        deburr_mm=0.0,
        stock_state={"top_z": 2.5, "bottom_z": 0.0},
    )
    bundle.inventory["fixtures"] = {"push-stick": {"kind": "push_stick", "name": "push stick"}}
    bundle.policy.update(
        numbers={"min_hand_feed_mm": minimum},
        numbers_cite={"min_hand_feed_mm": ["test shop hand-feed rule"]},
        numbers_verify={"min_hand_feed_mm": False},
    )
    bundle.kernel["setups"] = {"S2": {"stock_bbox_mm": entry_box(300.0) if box is None else box}}
    return bundle


def hold_text(bundle):
    setup = bundle.plan["setups"][0]
    steps, _ = _Traveler(bundle, hold_fields.evaluate(bundle), {}, None).hold(setup)
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", steps))


def row(rule, bundle, subject="S2"):
    return next(each for each in rule.evaluate(bundle) if each.subject == subject)


# ------------------------------------------------------------------ admitted: decided


def test_a_hand_fed_vertical_saw_cut_owes_no_holding_declaration(monkeypatch):
    straight(monkeypatch, y=18.0)  # a blade path the hand-feed minimum can judge
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
    assert "guided by the line scribed in S1 op 10" in text
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
    (guide,) = re.findall(rf"Upper blade guide: ({NUMBER}) mm above the top of the work", text)
    assert float(guide) == 6.0
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


def setup_holding_text(bundle, sid):
    traveler = _Traveler(bundle, [], {}, None)
    setup = next(setup for setup in bundle.plan["setups"] if setup["id"] == sid)
    (holding,) = [block for block in traveler.setup_blocks(setup) if block.key == "holding"]
    assert holding.setup_id == sid
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", traveler.block_html(holding)))


def test_the_setup_holding_block_and_the_hold_agree_on_a_hand_fed_setup():
    bundle = load_bundle(BUNDLE / "plan.toml")
    setup = bundle.plan["setups"][1]
    steps, _ = _Traveler(bundle, [], {}, None).hold(setup)
    assert "Fed by hand on the saw table" in steps
    holding = setup_holding_text(bundle, "S2")
    assert "Fed by hand on the saw table" in holding
    assert "no vise or clamp holds the work" in holding
    assert "Start the cut at the -X end" in holding
    assert "STOP" not in holding


def test_an_unresolved_hand_fed_setup_stops_in_its_holding_block_and_the_hold(example):
    inventory = example / "inventory.toml"
    text = inventory.read_text(encoding="utf-8")
    inventory.write_text(text.replace('saw_modes = ["horizontal", "vertical"]\n', ""), "utf-8")
    bundle = load_bundle(example / "plan.toml")
    steps, _ = _Traveler(bundle, [], {}, None).hold(bundle.plan["setups"][1])
    assert "STOP" in steps and "Fed by hand" not in steps
    holding = setup_holding_text(bundle, "S2")
    assert "STOP: hand-fed holding not established" in holding
    assert "Fed by hand" not in holding


def scene(bundle, sid=1):
    return hand_fed_scene(bundle, bundle.plan["setups"][sid], 1.0)


def keys(drawn):
    return {key["label"]: key["xy"] for key in drawn["waypoints"]}


def test_the_sketch_draws_the_one_scribed_line_with_its_waste_keep_and_minimum_leave():
    bundle = load_bundle(BUNDLE / "plan.toml")
    drawn = scene(bundle)
    # No drawn saw path: the line, the saw path hidden but for its keyed ends, the arrows.
    line, saw, arrows = drawn["paths"]
    assert saw["hidden"] is True and saw["ends"] == ["ENTER", "LEAVE"]
    assert line["op"] == "10" and "directed" not in line and "waste_xy" in line
    assert arrows["arrows_only"] is True and arrows["directed"] is True and arrows["feed"]
    assert arrows["xy"][0][0] > arrows["xy"][-1][0]  # feed_from = "-X": work moves to -X
    # The arrows stand in the waste, 3 mm off the line (inside the R800 circle here).
    setup = bundle.plan["setups"][1]
    profile = kernel.scribed_profile(bundle, setup, setup["ops"][0])
    centre, radius = profile["centre_mm"], profile["radius_mm"]
    assert {round(math.dist(p, centre) - radius, 3) for p in arrows["xy"]} == {-3.0}
    assert list(keys(drawn)) == [
        "SCRIBED LINE",
        "WASTE: SAW HERE, 0.450 MM MIN OFF THE LINE",
        "KEEP",
    ]
    assert all(key["plain"] for key in drawn["waypoints"])
    # The R800 top edge's saw removes inside the circle (+Y here): waste above, keep below.
    labelled = keys(drawn)
    assert line["waste_xy"] == labelled["WASTE: SAW HERE, 0.450 MM MIN OFF THE LINE"]
    assert labelled["KEEP"][1] < labelled["SCRIBED LINE"][1] < line["waste_xy"][1]


# The example's entry blank in the setup frame T (zero 8 mm up the bar's Y).
BLANK = [-146.254568, -8.0, -8.0565, 146.254568, 21.29464, 1.0]


def on_rim(point, box, tol=1e-6):
    x, y = point
    x0, y0, _, x1, y1, _ = box
    inside = x0 - tol <= x <= x1 + tol and y0 - tol <= y <= y1 + tol
    return inside and min(abs(x - x0), abs(x - x1), abs(y - y0), abs(y - y1)) <= tol


def test_the_shaded_waste_is_bounded_by_the_blank_outline_and_the_scribed_arc():
    bundle = load_bundle(BUNDLE / "plan.toml")
    drawn = scene(bundle)
    line = next(path for path in drawn["paths"] if "waste_xy" in path)
    region = render_diagram._waste_region(line["xy"], BLANK, line["waste_xy"])
    assert region
    arc = {tuple(point) for point in line["xy"]}
    # Every vertex is on the scribed arc or on the blank's outline, and both bound it.
    assert all(tuple(v) in arc or on_rim(v, BLANK) for v in region)
    assert sum(tuple(v) in arc for v in region) > 100
    # The arc leaves the blank through its top face: that edge closes the crescent.
    closing = [v for v in region if tuple(v) not in arc]
    assert len(closing) == 2 and all(v[1] == pytest.approx(BLANK[4]) for v in closing)
    assert render_diagram._contains(region, line["waste_xy"])
    assert not render_diagram._contains(region, keys(drawn)["KEEP"])


def test_the_sketch_maps_the_blank_and_the_scribed_arc_through_one_transform(freecad_kernel):
    # The blank and the arc are drawn from their real setup-frame coordinates through the
    # one sketch projector: the arc is never fitted to the box.
    bundle = load_bundle(BUNDLE / "plan.toml")
    kernel.run_geometry(bundle)
    blank = bundle.kernel["setups"]["S2"]["stock_bbox_mm"]
    assert blank == pytest.approx(BLANK)  # the kernel's S2 entry stock, setup frame T
    setup = bundle.plan["setups"][1]
    profile = kernel.scribed_profile(bundle, setup, setup["ops"][0])
    (cx, cy), radius = profile["centre_mm"], profile["radius_mm"]
    line = next(path for path in scene(bundle)["paths"] if "waste_xy" in path)
    points = [*map(tuple, line["xy"]), *render_diagram._stock_outline(blank)[:4]]
    scale = 2.0
    project = render_diagram._xy_projector(render_diagram._bounds(points), (0, 0), (scale, scale))

    def model_y(pixel_y):
        return blank[4] - (pixel_y - project((0, blank[4]))[1]) / scale

    # The arc's low point and its ends where it meets the blank's top face land at the Y
    # values S1 prints: low point X 0.000, Y 8.000; ends X +/-145.240, Y 21.295.
    low = min(line["xy"], key=lambda p: p[1])
    assert low[0] == pytest.approx(0.0, abs=1.0)
    assert model_y(project(low)[1]) == pytest.approx(8.000, abs=0.001)
    top = project((0, blank[4]))[1]
    pixels = [project(p) for p in line["xy"]]
    crossings = [
        a[0] + (b[0] - a[0]) * (top - a[1]) / (b[1] - a[1])
        for a, b in zip(pixels, pixels[1:], strict=False)
        if (a[1] - top) * (b[1] - top) < 0
    ]
    ends = sorted(project((0, 0))[0] + (x - project((0, 0))[0]) for x in crossings)
    assert [(x - project((0, 0))[0]) / scale for x in ends] == pytest.approx(
        [-145.240, 145.240], abs=0.01
    )
    assert model_y(top) == pytest.approx(21.295, abs=0.001)
    # The shaded waste's area is the model's: the blank above the arc, from end to end.
    region = render_diagram._waste_region(line["xy"], blank, line["waste_xy"])
    area = 0.5 * abs(
        sum(a[0] * b[1] - b[0] * a[1] for a, b in zip(region, region[1:] + region[:1], strict=True))
    )
    half = math.sqrt(radius**2 - (cy - blank[4]) ** 2)  # where the arc meets the top face
    under = half * math.sqrt(radius**2 - half**2) + radius**2 * math.asin(half / radius)
    model = 2 * half * (blank[4] - cy) + under
    assert cx == pytest.approx(0.0, abs=1e-6) and area == pytest.approx(model, rel=0.002)


def entry_bundle(top=BLANK[4], feed_from="-X"):
    bundle = load_bundle(BUNDLE / "plan.toml")
    bundle.plan["setups"][1]["hold"]["feed_from"] = feed_from
    box = [*BLANK[:4], top, BLANK[5]]
    return dataclasses.replace(bundle, kernel={"setups": {"S2": {"stock_bbox_mm": box}}})


@pytest.mark.parametrize("feed_from", ["-X", "+X"])
def test_a_line_running_to_the_blank_enters_and_leaves_its_allowance_outside(feed_from):
    bundle = entry_bundle(feed_from=feed_from)
    setup = bundle.plan["setups"][1]
    crossings = kernel.saw_crossings(bundle, setup, setup["ops"][0])
    # The saw path, 0.450 mm inside the R800 circle, meets the blank's +Y face.
    half = math.sqrt((800 - 0.45) ** 2 - (808 - BLANK[4]) ** 2)
    first = -half if feed_from == "-X" else half
    assert [c["face"] for c in crossings] == ["+Y", "+Y"]
    assert [c["xy"][0] for c in crossings] == pytest.approx([first, -first], abs=1e-6)
    steps = _Traveler(bundle, [], {}, None).saw_ends(setup, setup["ops"][0])
    assert steps.startswith("Enter at X ") and "and leave at X " in steps
    assert "on the +Y face (from Setup S2 zero)" in steps
    (allowance,) = re.findall(rf"cut, ({NUMBER}) mm off the scribed line on the waste side", steps)
    assert float(allowance) == 0.45
    # The printed points are the computed crossings, not the line's own ends at X 145.240.
    printed = [[float(x), float(y)] for x, y in re.findall(rf"X ({NUMBER}), Y ({NUMBER})", steps)]
    assert printed == [[round(first, 3), 21.295], [round(-first, 3), 21.295]]
    computed = [value for c in crossings for value in c["xy"]]
    assert [value for xy in printed for value in xy] == pytest.approx(computed, abs=5e-4)
    assert all(abs(x) < 145.240 - 2.0 for x, _ in printed)


LAYOUT = {
    "layout": "template",
    "template": "test-r800-template",
    "radius_mm": 800.0,
    "centre_setup_xy": [0.0, 808.0],
    "ends_setup_xy": [[-145.24, 21.295], [145.24, 21.295]],
}


@pytest.mark.parametrize(
    ("note", "tagged"),
    [
        (None, True),  # the example's note: global STEP x +/-146.25, y 0..29.29
        ("Authored 292.5 x 29.3 x 9.1 mm supply.", False),  # a size, no coordinates
        ("Relative to Setup S2 zero the blank is Y -8..21.3.", False),  # frame named
    ],
)
def test_op_row_coordinates_name_their_frame_when_the_job_page_prints_global_ones(note, tagged):
    bundle = entry_bundle()
    if note is not None:
        bundle.plan["stock"]["note"] = note
    traveler = _Traveler(bundle, [], {}, None)
    s1, s2 = bundle.plan["setups"]
    traveler.setup = s1
    (layout,) = traveler.manual_arc_steps(s1["ops"][0], LAYOUT, True)
    ends = traveler.saw_ends(s2, s2["ops"][0])
    coordinates = re.findall(rf"X ({NUMBER}), Y ({NUMBER})", str(layout))
    assert [[float(x), float(y)] for x, y in coordinates] == [
        [0.0, 808.0],
        [-145.24, 21.295],
        [145.24, 21.295],
    ]
    centre = re.search(
        rf"about the centre X {NUMBER}, Y {NUMBER}( \(from Setup S1 zero\))?", str(layout)
    )
    arc_ends = re.search(
        rf"arc ends X {NUMBER}, Y {NUMBER} and X {NUMBER}, Y {NUMBER}"
        r"( \(from Setup S1 zero\))?",
        str(layout),
    )
    assert centre and arc_ends
    assert bool(centre.group(1)) is tagged
    assert bool(arc_ends.group(1)) is tagged
    assert ("+Y face (from Setup S2 zero):" in ends) is tagged
    assert ("(from Setup" in str(layout) + ends) is tagged


def test_a_line_inside_the_blank_or_without_kernel_facts_gets_no_entry_rule():
    bundle = entry_bundle(top=40.0)
    setup = bundle.plan["setups"][1]
    # Cut only the middle 200 mm of the taller blank: the line never reaches its outline.
    setup["ops"][0]["stock_removal_bounds"]["x"] = [-100.0, 100.0]
    assert kernel.saw_crossings(bundle, setup, setup["ops"][0]) == []
    assert _Traveler(bundle, [], {}, None).saw_ends(setup, setup["ops"][0]) == ""
    bundle = load_bundle(BUNDLE / "plan.toml")  # no kernel run
    assert kernel.saw_crossings(bundle, setup, setup["ops"][0]) is None


def test_a_line_that_does_not_cross_the_blank_shades_nothing():
    arc = [[x, 5.0 + x * x / 1600] for x in range(-50, 51, 5)]  # ends inside the blank
    assert render_diagram._waste_region(arc, BLANK, [0.0, 15.0]) is None
    full = [[x, 5.0] for x in range(-200, 201, 5)]  # crosses it: the side above is waste
    region = render_diagram._waste_region(full, BLANK, [0.0, 15.0])
    assert sorted(region) == sorted(
        [(BLANK[0], 5.0), *[(x, 5.0) for x in range(-145, 146, 5)], (BLANK[3], 5.0)]
        + [(BLANK[3], BLANK[4]), (BLANK[0], BLANK[4])]
    )


def test_the_picture_draws_the_saw_table_blade_and_push_aid():
    bundle = load_bundle(BUNDLE / "plan.toml")
    boxes = {box["name"]: box for box in scene(bundle)["boxes"]}
    assert set(boxes) == {"saw table", "push aid", "band op 10"}
    assert boxes["push aid"]["label"] == "PUSH STICK (TRAILING END)"
    # Fed from -X, the work trails at its +X end: the push aid stands past the max X.
    assert boxes["push aid"]["stock_mm"][0][0] == ("max", 0.0)
    assert boxes["band op 10"]["box_mm"][5] == pytest.approx(1.0 + 6.0)  # top + guide
    (feed,) = scene(bundle)["feed_lines"]
    assert feed["label"] == "WORK FEED INTO THE BLADE (OP 10)"
    assert feed["xyz"][0][2] == 1.0


@pytest.mark.parametrize(("feed_from", "sign", "trailing"), [("-X", -1, "max"), ("+X", 1, "min")])
def test_the_feed_arrows_push_aid_and_hold_all_follow_the_declared_start_end(
    feed_from, sign, trailing
):
    # The cut starts at the feed_from end, so the work moves toward feed_from into the
    # stationary blade, and the push aid stands behind the opposite, trailing end.
    bundle = load_bundle(BUNDLE / "plan.toml")
    setup = bundle.plan["setups"][1]
    setup["hold"]["feed_from"] = feed_from
    drawn = scene(bundle)
    (feed,) = drawn["feed_lines"]
    line, saw, arrows = drawn["paths"]
    for xy in (feed["xyz"], arrows["xy"]):
        assert (xy[-1][0] - xy[0][0]) * sign > 0  # arrows run the way the work moves
    # The sketch keys ENTER where the saw path crosses the blank at the feed_from end,
    # the end the arrows run toward, and LEAVE at the other.
    *_, waypoints, _ = render_diagram._panel_items("10", drawn["paths"], [], BLANK)
    marked = {key["label"]: key for key in waypoints}
    start, leave = marked["ENTER"]["xy"], marked["LEAVE"]["xy"]
    assert (start[0] - leave[0]) * sign > 0 and start[1] == pytest.approx(BLANK[4])
    # The scribed line's own ends are keyed apart from the cut's, with their own marker.
    ends = [key for key in waypoints if key["label"] == "LINE END"]
    assert {key["marker"] for key in ends} == {"square"}
    assert {marked["ENTER"]["marker"], marked["LEAVE"]["marker"]} == {"cross"}
    assert sorted(abs(key["xy"][0]) for key in ends)[0] > abs(start[0]) + 2.0
    boxes = {box["name"]: box for box in drawn["boxes"]}
    assert [trailing, 0.0] in map(list, boxes["push aid"]["stock_mm"][0])
    blade = boxes["band op 10"]["box_mm"]
    assert blade[0] < start[0] < blade[3]
    steps, _ = _Traveler(bundle, [], {}, None).hold(setup)
    assert (
        f"Start the cut at the {feed_from} end of the line: feed the work toward {feed_from}"
        in steps
    )


def test_an_undeclared_feed_end_draws_no_arrows_start_band_or_push_aid():
    bundle = load_bundle(BUNDLE / "plan.toml")
    bundle.plan["setups"][1]["hold"].pop("feed_from")
    drawn = scene(bundle)
    assert [path.get("directed") for path in drawn["paths"]] == [None]  # no arrows
    assert ["LINE END", "LINE END"] == [e for p in drawn["paths"] for e in p.get("ends", [])]
    assert [box["name"] for box in drawn["boxes"]] == ["saw table"]
    assert drawn["feed_lines"] == []


def test_a_fixture_hold_draws_no_hand_fed_scene():
    bundle = load_bundle(BUNDLE / "plan.toml")
    assert scene(bundle, 0) == {"paths": [], "waypoints": [], "boxes": [], "feed_lines": []}


# ------------------------------------------- a feed end that names no end (Codex round 3)


@pytest.mark.parametrize("feed_from", ["+Y", "-Y"])
def test_a_feed_end_level_with_both_line_ends_is_unresolved(feed_from):
    # The R800 top arc's two ends lie level in Y: "start at the +Y end" names neither.
    bundle = entry_bundle(feed_from=feed_from)
    setup = bundle.plan["setups"][1]
    assert "names no end" in kernel.feed_from_ambiguity(bundle, setup)
    drawn = scene(bundle)
    assert not any(path.get("directed") for path in drawn["paths"])
    assert not any("ENTER" in path.get("ends", []) for path in drawn["paths"])
    assert [box["name"] for box in drawn["boxes"]] == ["saw table"]
    traveler = _Traveler(bundle, [], {}, None)
    steps, _ = traveler.hold(setup)
    assert "STOP: feed_from" in steps and "Start the cut" not in steps
    assert str(traveler.feed_direction(setup)).startswith("STOP: feed_from")
    assert traveler.saw_ends(setup, setup["ops"][0]).startswith("Cut through at")
    finding = row(hold_fields, bundle)
    assert finding.status == "unknown" and "hold.feed_from" in finding.numbers["missing"]
    assert "names no end" in finding.sentence


def test_an_x_feed_end_names_an_end_of_the_same_arc():
    bundle = entry_bundle(feed_from="-X")
    assert kernel.feed_from_ambiguity(bundle, bundle.plan["setups"][1]) == ""


def test_feed_arrows_outside_the_removal_bounds_are_left_off_not_a_crash():
    bundle = load_bundle(BUNDLE / "plan.toml")
    op = bundle.plan["setups"][1]["ops"][0]
    # The line (Y 8.0..8.25) and the saw path fit; the arrows, 3 mm into the waste, do not.
    op["stock_removal_bounds"] = {"x": [-20.0, 20.0], "y": [7.0, 9.5], "z": [-9.0, 2.0]}
    drawn = scene(bundle)
    assert [p.get("arrows_only") for p in drawn["paths"]] == [None, None]
    assert any("waste_xy" in path for path in drawn["paths"])


# ------------------------------------------- the hand-feed minimum (#343): policy gate

# A blade path so flat it runs straight through the work: the arc about a centre 1e5 mm off.
FAR = 1e5


def straight(monkeypatch, x=None, y=None):
    """Make the kernel's scribed arc for every saw op a near-straight line at setup ``x``
    (running along Y) or ``y`` (running along X), with no allowance."""

    def profile(bundle, setup, op):
        if x is not None:
            return {"centre_mm": [x + FAR, 10.0], "radius_mm": FAR, "remove": "outside"}
        return {"centre_mm": [150.0, y + FAR], "radius_mm": FAR, "remove": "outside"}

    monkeypatch.setattr(kernel, "scribed_profile", profile)


def feed_bundle(minimum=MINIMUM, box=None, feed_from="-X"):
    """``feed_from`` must name an end of the line: ``-Y`` for a :func:`straight` ``x``
    path, which runs along Y (#342's feed_from check)."""
    bundle = hand_fed_bundle(minimum=minimum, box=box)
    bundle.plan["setups"][0]["hold"]["feed_from"] = feed_from
    op = bundle.plan["setups"][0]["ops"][0]
    # The saw may run anywhere over the work.
    op.update(
        allowance_mm=0.0,
        stock_removal_bounds={"x": [-1.0, 301.0], "y": [-1.0, 91.0], "z": [-1.0, 3.5]},
    )
    return bundle


def test_a_cut_along_a_long_work_keeps_work_beyond_the_minimum(monkeypatch):
    # 300 x 20 mm, sawn along y = 18: mid-cut the ends are still 150 mm from the blade.
    straight(monkeypatch, y=18.0)
    finding = row(hold_fields, feed_bundle())
    assert finding.status == "pass", finding.sentence
    low, high = finding.numbers["hand_fed_reach_mm"]
    assert 148.0 < low <= 150.0 and high > 150.0
    assert finding.numbers["hand_feed_cite"] == ["test shop hand-feed rule"]


def test_a_cut_across_a_short_work_brings_the_fingers_to_the_blade(monkeypatch):
    # Codex's case: 100 x 20 mm sawn across its middle; no work is more than ~54 mm away.
    straight(monkeypatch, x=50.0)
    finding = row(hold_fields, feed_bundle(box=entry_box(100.0), feed_from="-Y"))
    assert finding.status == "error"
    assert finding.numbers["hand_fed_reach_mm"][1] == pytest.approx(math.hypot(50, 10), abs=0.6)
    assert "76.2 mm hand-feed minimum" in finding.sentence


def test_a_box_too_loose_to_decide_is_debt(monkeypatch):
    # 120 x 20 sawn across its middle: the corners are 61 mm off, the sides only 60.
    straight(monkeypatch, x=60.0)
    bundle = feed_bundle(minimum=60.5, box=entry_box(120.0), feed_from="-Y")
    finding = row(hold_fields, bundle)
    assert finding.status == "unknown"
    assert "not established" in finding.sentence


def _reach(monkeypatch, minimum, **path):
    straight(monkeypatch, **path)
    box = entry_box(100.0) if "x" in path else None
    feed = "-Y" if "x" in path else "-X"
    return row(hold_fields, feed_bundle(minimum=minimum, box=box, feed_from=feed))


@pytest.mark.parametrize("delta, status", [(1e-3, "error"), (-1e-3, "not-error")])
def test_the_error_boundary_is_the_farthest_corner(monkeypatch, delta, status):
    high = _reach(monkeypatch, 1.0, x=50.0).numbers["hand_fed_reach_mm"][1]
    finding = _reach(monkeypatch, high + delta, x=50.0)
    assert (finding.status == "error") == (status == "error")


@pytest.mark.parametrize("delta, status", [(-1e-3, "pass"), (1e-3, "unknown")])
def test_the_pass_boundary_is_the_nearest_side_less_a_step(monkeypatch, delta, status):
    low = _reach(monkeypatch, 1.0, y=18.0).numbers["hand_fed_reach_mm"][0]
    assert _reach(monkeypatch, low + delta, y=18.0).status == status


@pytest.mark.parametrize(
    "policy",
    [
        {"numbers": {}},
        {"numbers": {"min_hand_feed_mm": "unknown"}},
        {"numbers_cite": {}},
        {"numbers_cite": {"min_hand_feed_mm": "unknown"}},
        {"numbers_cite": {"min_hand_feed_mm": ["", "unknown"]}},
        {"numbers_verify": {"min_hand_feed_mm": True}},
        {"numbers_verify": {"min_hand_feed_mm": "unknown"}},
        {"numbers": {"min_hand_feed_mm": 0.0}},
    ],
    ids=[
        "absent",
        "unknown",
        "uncited",
        "cite-unknown",
        "cite-blank",
        "flagged",
        "verify-unknown",
        "zero",
    ],
)
def test_an_unestablished_hand_feed_minimum_is_debt(monkeypatch, policy):
    straight(monkeypatch, x=5.0)
    bundle = feed_bundle(box=entry_box(10.0, 10.0), feed_from="-Y")
    bundle.policy.update(policy)
    finding = row(hold_fields, bundle)
    assert finding.status == "unknown"
    assert finding.numbers["min_hand_feed_mm"] == "unknown"
    assert "min_hand_feed_mm" in finding.sentence


@pytest.mark.parametrize(
    "kernel_facts",
    [
        {"status": "ok", "setups": {}},
        {"status": "ok", "setups": {"S2": {"stock_bbox_mm": "unknown"}}},
        {"status": "unknown", "kernel_unavailable": True, "reason": "no FreeCAD"},
    ],
    ids=["no-entry-stock", "unknown-box", "kernel-unavailable"],
)
def test_an_unknown_work_size_is_debt(monkeypatch, kernel_facts):
    straight(monkeypatch, y=18.0)
    bundle = feed_bundle()
    bundle.kernel.clear()
    bundle.kernel.update(kernel_facts)
    finding = row(hold_fields, bundle)
    assert finding.status == "unknown"
    assert "setup-entry stock" in finding.sentence


def test_an_unplaced_blade_path_is_debt():
    # No scribed arc the kernel places (here, no feature geometry): the path is unknown.
    finding = row(hold_fields, feed_bundle())
    assert finding.status == "unknown"
    assert "blade path" in finding.sentence


def test_a_fixture_hold_reads_no_hand_feed_minimum():
    bundle = hand_fed_bundle(box=entry_box(10.0, 10.0))
    bundle.plan["setups"][0]["hold"] = {"fixture": "unknown"}
    assert "min_hand_feed_mm" not in row(hold_fields, bundle).numbers


def test_the_example_work_clears_its_cited_minimum(freecad_kernel):
    bundle = load_bundle(BUNDLE / "plan.toml")
    kernel.run_geometry(bundle)
    finding = row(hold_fields, bundle)
    assert finding.status == "pass", finding.sentence
    assert finding.numbers["hand_fed_reach_mm"][0] >= 76.2


def test_only_the_declared_removal_span_is_judged(monkeypatch):
    # 300 x 20 sawn along y = 18 but only x 0..40 is declared: the blade never reaches the
    # middle, so the work beyond x = 40 stays at least 260 mm off (150 over the whole run).
    straight(monkeypatch, y=18.0)
    bundle = feed_bundle()
    bounds = bundle.plan["setups"][0]["ops"][0]["stock_removal_bounds"]
    bounds["x"] = [0.0, 40.0]
    finding = row(hold_fields, bundle)
    assert finding.status == "pass"
    assert finding.numbers["hand_fed_reach_mm"][0] > 250.0


def test_removal_bounds_outside_the_work_leave_the_minimum_unknown(monkeypatch):
    straight(monkeypatch, y=18.0)
    bundle = feed_bundle()
    bundle.plan["setups"][0]["ops"][0]["stock_removal_bounds"]["x"] = [400.0, 500.0]
    finding = row(hold_fields, bundle)
    assert finding.status == "unknown"
    assert "does not cross" in finding.sentence


def test_unknown_removal_bounds_leave_the_minimum_unknown(monkeypatch):
    straight(monkeypatch, y=18.0)
    bundle = feed_bundle()
    bundle.plan["setups"][0]["ops"][0]["stock_removal_bounds"] = "unknown"
    assert row(hold_fields, bundle).status == "unknown"


def two_cuts(monkeypatch, second_box):
    """A hand-fed setup sawing along Y 18 twice: op 20 on the 300 x 20 entry stock, op 30
    on what op 20 left, the kernel boxing op 30's stock as ``second_box`` (None: no box)."""
    straight(monkeypatch, y=18.0)
    bundle = feed_bundle()
    ops = bundle.plan["setups"][0]["ops"]
    ops.append({**ops[0], "op": 30})
    if second_box is not None:
        bundle.kernel["ops"]["S2:30"] = {"stock_bbox_before_mm": second_box}
    return bundle


def test_a_second_cut_on_stock_still_long_enough_passes(monkeypatch):
    finding = row(hold_fields, two_cuts(monkeypatch, entry_box(200.0)))
    assert finding.status == "pass", finding.sentence
    by_op = finding.numbers["hand_fed_reach_by_op"]
    assert set(by_op) == {"20", "30"}
    # Each cut is judged on its own stock: op 30's 200 mm piece reaches less than op 20's.
    assert by_op["30"][1] < by_op["20"][1] and by_op["30"][0] >= MINIMUM


def test_a_second_cut_fails_on_its_own_smaller_stock(monkeypatch):
    # Op 30 saws a 100 mm piece: mid-cut no work is more than ~53 mm from the blade.
    finding = row(hold_fields, two_cuts(monkeypatch, entry_box(100.0)))
    assert finding.status == "error"
    assert finding.numbers["hand_fed_reach_by_op"]["20"][0] >= MINIMUM  # op 20 alone passes
    assert finding.numbers["hand_fed_reach_mm"][1] == pytest.approx(math.hypot(50, 18), abs=0.6)
    assert "op 30's cut" in finding.sentence and "76.2 mm hand-feed minimum" in finding.sentence


def test_a_later_cut_the_kernel_does_not_box_leaves_the_minimum_unknown(monkeypatch):
    # Never the entry stock for a cut after the first: it works what the first left.
    finding = row(hold_fields, two_cuts(monkeypatch, None))
    assert finding.status == "unknown"
    assert "op 30 works stock the kernel does not box" in finding.sentence


def test_a_known_short_cut_stays_an_error_beside_a_later_unboxed_cut(monkeypatch):
    # Op 20 works a 100 mm entry piece (no work past ~53 mm mid-cut); op 30's stock is
    # not boxed. The known shortfall wins: never downgraded to debt (Codex round 1).
    straight(monkeypatch, y=18.0)
    bundle = feed_bundle(box=entry_box(100.0))
    ops = bundle.plan["setups"][0]["ops"]
    ops.append({**ops[0], "op": 30})
    finding = row(hold_fields, bundle)
    assert finding.status == "error"
    assert set(finding.numbers["hand_fed_reach_by_op"]) == {"20"}
    assert "op 20's cut" in finding.sentence


def test_a_known_short_cut_stays_an_error_beside_a_later_unplaced_path(monkeypatch):
    # Op 30's removal bounds are unknown, so its path cannot be placed; op 20 still fails
    # on its 100 mm piece, and that known shortfall wins (Codex round 2).
    straight(monkeypatch, y=18.0)
    bundle = feed_bundle(box=entry_box(100.0))
    ops = bundle.plan["setups"][0]["ops"]
    ops.append({**ops[0], "op": 30, "stock_removal_bounds": "unknown"})
    bundle.kernel["ops"]["S2:30"] = {"stock_bbox_before_mm": entry_box(100.0)}
    finding = row(hold_fields, bundle)
    assert finding.status == "error"
    assert set(finding.numbers["hand_fed_reach_by_op"]) == {"20"}
    # Without op 20's shortfall, op 30's unplaced path is the debt it reports.
    bundle = feed_bundle()
    ops = bundle.plan["setups"][0]["ops"]
    ops.append({**ops[0], "op": 30, "stock_removal_bounds": "unknown"})
    finding = row(hold_fields, bundle)
    assert finding.status == "unknown" and "op 30's stock_removal_bounds" in finding.sentence


def test_the_kernel_boxes_each_saw_cut_on_the_stock_before_it(example, freecad_kernel):
    # Two hand-fed cuts along the same line: op 10 saws its -X half, op 20 the +X half.
    edit(
        example,
        "stock_removal_bounds = { x = [-147.5, 147.5], y = [7.0, 22.5], z = [-9.0, 2.0] }",
        "stock_removal_bounds = { x = [-147.5, 0.0], y = [7.0, 22.5], z = [-9.0, 2.0] }\n\n"
        '[[setups.ops]]\nop = 20\ndo = "saw_cut"\ntool = "test-bandsaw-blade"\n'
        'follows = "S1:10"\nallowance_mm = 0.45\n'
        "stock_removal_bounds = { x = [0.0, 147.5], y = [7.0, 22.5], z = [-9.0, 2.0] }",
    )
    bundle = load_bundle(example / "plan.toml")
    kernel.run_geometry(bundle)
    first, second = bundle.kernel["ops"]["S2:10"], bundle.kernel["ops"]["S2:20"]
    assert first["stock_bbox_before_mm"] == bundle.kernel["setups"]["S2"]["stock_bbox_mm"]
    # Op 20 starts from what op 10 left: its volume and a box inside op 10's.
    assert second["stock_volume_before_mm3"] == pytest.approx(first["stock_volume_after_mm3"])
    assert second["stock_volume_before_mm3"] < first["stock_volume_before_mm3"]
    low, high = first["stock_bbox_before_mm"], second["stock_bbox_before_mm"]
    assert all(high[i] >= low[i] - 1e-6 and high[i + 3] <= low[i + 3] + 1e-6 for i in range(3))


def test_removal_bounds_above_the_work_leave_the_minimum_unknown(monkeypatch):
    straight(monkeypatch, y=18.0)
    bundle = feed_bundle()
    bundle.plan["setups"][0]["ops"][0]["stock_removal_bounds"]["z"] = [10.0, 20.0]
    finding = row(hold_fields, bundle)
    assert finding.status == "unknown"
    assert "does not cross" in finding.sentence
