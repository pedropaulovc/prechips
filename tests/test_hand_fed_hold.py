"""A hand-fed hold: a vertical bandsaw cut along a scribed line, nothing clamping the work
(#335)."""

import re

import pytest
from pydantic import ValidationError
from test_bandsaw_scribed import bandsaw_bundle
from test_bench_saw import PLANE, plan, saw, scribed
from test_cli import ROOT, copy_examples, run_cli

from prechips import kernel
from prechips.inputs import BadInput, load_bundle
from prechips.model import Plan
from prechips.rules import fixture_interference, hold_fields, stock_diameter, thin_wall_under_clamp
from prechips.rules import vise as vise_rule
from prechips.rules.resolution import hand_fed
from prechips.sheet import _Traveler

HAND_FED = {"kind": "hand_fed", "note": "flat on the saw table"}
BUNDLE = ROOT / "examples" / "geometry" / "hand-fed-saw"


def hand_fed_bundle(op=None, **machine):
    bundle = bandsaw_bundle(op=op, blade_speed_sfm=[80, 200], **machine)
    setup = bundle.plan["setups"][0]
    setup.update(
        hold=dict(HAND_FED),
        coolant="none: dry cut",
        deburr_mm=0.0,
        stock_state={"top_z": 2.5, "bottom_z": 0.0},
    )
    return bundle


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
