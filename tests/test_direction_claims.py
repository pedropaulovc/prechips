"""Claims are directional and explicit: an op cannot cut a face that faces away from its setup.

Engine cases run ``freecad_job.py`` under ``freecadcmd`` on the authored solids of
``test_kernel_geometry`` and skip without it; rule cases inject synthetic kernel facts.
"""

import shutil
import subprocess
import tomllib
from copy import deepcopy
from pathlib import Path

import pytest
from test_input_contracts import FEATURES, PLAN, bundle_files
from test_kernel_geometry import (
    _AUTHOR,
    _AUTHORED,
    Engine,
    _op,
    _setup,
    _vise,
)

from prechips.inputs import BadInput, Bundle, load_bundle
from prechips.rules import (
    accessibility,
    coverage,
    finish_coverage,
    internal_corner_radius,
    reach,
    vise,
)


@pytest.fixture(scope="module")
def solids(tmp_path_factory, freecad_kernel):
    """The ``test_kernel_geometry`` authored solids, exported once for this module."""
    directory = tmp_path_factory.mktemp("solids")
    script = directory / "author.py"
    script.write_text(_AUTHOR, encoding="utf-8")
    process = subprocess.run(
        [freecad_kernel, str(script), "--", str(directory)],
        capture_output=True,
        text=True,
        errors="replace",
        timeout=300,
    )
    paths = {path.stem: path for path in directory.glob("*.step")}
    assert len(paths) == _AUTHORED, process.stdout[-2000:] + process.stderr[-2000:]
    return paths


@pytest.fixture
def engine(tmp_path, freecad_kernel):
    return Engine(tmp_path, freecad_kernel)


FLIPPED = {"origin": [0, 0, 0], "x": [1, 0, 0], "y": [0, -1, 0], "z": [0, 0, -1]}
SIDEWAYS = {"origin": [0, 0, 0], "x": [1, 0, 0], "y": [0, 0, -1], "z": [0, 1, 0]}
# The authored step block's blank: the 60x40x20 box it was cut from.
BLANK = {
    "shape": "box",
    "origin_mm": [0, 0, 0],
    "axis": [1, 0, 0],
    "section_axis": [0, 1, 0],
    "section_mm": [40, 20],
    "length_mm": 60,
}


def _route(job, *setups):
    """Chain the setups from the supplied blank through each other in order."""
    job["stock"] = BLANK
    previous = "stock"
    for setup in setups:
        setup["stock_in"] = previous
        previous = setup["id"]
    job["setups"] = list(setups)
    return job


def _bare(subject, feature, faces=None):
    """An op without any cutter or holder dimension."""
    op = {"subject": subject, "feature": feature}
    if faces is not None:
        op["faces"] = faces
    return op


def _broad(engine, step):
    top = engine.refs(step, (0, 0, 20), (30, 40, 20))
    bottom = engine.refs(step, (0, 0, 0), (60, 40, 0))
    assert len(top) == 1 and len(bottom) == 1
    return top, bottom


# --------------------------------------------------------------------------- engine


def test_far_side_face_is_a_claim_error_even_with_an_unmeasured_cutter(engine, solids):
    step = solids["step"]
    top, bottom = _broad(engine, step)
    setups = [
        _setup([_bare("S1:10", "broad")], _vise(5.0)),
        _setup([_bare("S2:10", "broad")], _vise(5.0), FLIPPED, "S2"),
    ]
    result = engine.run(engine.job(step, {"broad": top + bottom}, setups))
    index = result["mapping"]
    up, down = result["ops"]["S1:10"], result["ops"]["S2:10"]
    assert up["claim_errors"] == bottom and up["claimed_indices"] == [index[top[0]]]
    assert down["claim_errors"] == top and down["claimed_indices"] == [index[bottom[0]]]
    # The verdict never needed the cutter; the cutter-dependent facts stay unknown.
    assert up["tool_hits"] == "unknown" and "radius_mm" in up["reasons"]["tool_hits"]


def test_explicit_faces_split_a_two_sided_feature_across_setups(engine, solids):
    step = solids["step"]
    top, bottom = _broad(engine, step)
    ops = [_op("S1:10", "broad", 4.0, 15.0, 20.0), _op("S2:10", "broad", 4.0, 15.0, 20.0)]
    ops[0]["faces"], ops[1]["faces"] = top, bottom
    setups = [_setup(ops[:1], _vise(5.0)), _setup(ops[1:], _vise(5.0), FLIPPED, "S2")]
    result = engine.run(_route(engine.job(step, {"broad": top + bottom}), *setups))
    index = result["mapping"]
    up, down = result["ops"]["S1:10"], result["ops"]["S2:10"]
    assert up["claim_errors"] == [] and up["claimed_indices"] == [index[top[0]]]
    assert down["claim_errors"] == [] and down["claimed_indices"] == [index[bottom[0]]]
    for op in (up, down):
        assert op["sample_count"] > 0 and op["tool_hits"] == 0 and op["min_hits"]["tool"] == 0


def test_explicit_claim_overrides_feature_metadata_that_binds_the_far_side(engine, solids):
    step = solids["step"]
    top, bottom = _broad(engine, step)
    ops = [_bare("S1:10", "under"), _bare("S1:20", "under", top)]
    result = engine.run(engine.job(step, {"under": bottom}, [_setup(ops, _vise(5.0))]))
    index = result["mapping"]
    by_feature, explicit = result["ops"]["S1:10"], result["ops"]["S1:20"]
    assert by_feature["claim_errors"] == bottom and by_feature["claimed_indices"] == []
    assert explicit["claim_errors"] == [] and explicit["claimed_indices"] == [index[top[0]]]


def test_explicit_claim_of_an_invalid_ref_is_named_not_guessed(engine, solids):
    step = solids["step"]
    top, bottom = _broad(engine, step)
    wrong = top[0] + "x"
    ops = [_op("S1:10", "broad", 4.0, 15.0, 20.0)]
    ops[0]["faces"] = [wrong]
    result = engine.run(engine.job(step, {"broad": top + bottom}, [_setup(ops, _vise(5.0))]))
    assert wrong in result["mapping_errors"] and "carries label" in result["mapping_errors"][wrong]
    op = result["ops"]["S1:10"]
    assert op["mapping_errors"] == [wrong] and op["claimed_indices"] == "unknown"
    assert op["tool_hits"] == "unknown" and wrong in op["reasons"]["tool_hits"]


def test_a_face_with_any_normal_facing_away_is_rejected_whole(engine, solids):
    step = solids["puck"]
    od = engine.refs(step, (-10, -10, 0), (10, 10, 20), kind="Cylinder")
    assert od
    setups = [
        _setup([_bare("S1:10", "od")], {"reason": "none"}),
        _setup([_bare("S2:10", "od")], {"reason": "none"}, SIDEWAYS, "S2"),
    ]
    result = engine.run(engine.job(step, {"od": od}, setups))
    upright, sideways = result["ops"]["S1:10"], result["ops"]["S2:10"]
    assert upright["claim_errors"] == [] and len(upright["claimed_indices"]) == len(od)
    assert sideways["claim_errors"] and set(sideways["claim_errors"]) <= set(od)


# --------------------------------------------------------------------------- loading


def test_explicit_faces_load_as_plan_claims_and_an_empty_list_is_rejected(tmp_path):
    ref = "#492/ADVANCED_FACE[13]/HAF_STRAP_DATUM_B__P01"
    plan = PLAN.replace('feature = "subject"\n', f'feature = "subject"\nfaces = ["{ref}"]\n')
    bundle = load_bundle(bundle_files(tmp_path, plan, FEATURES))
    assert bundle.plan["setups"][0]["ops"][0]["faces"] == [ref]
    empty = PLAN.replace('feature = "subject"\n', 'feature = "subject"\nfaces = []\n')
    with pytest.raises(BadInput):
        load_bundle(bundle_files(tmp_path, empty, FEATURES))


# ------------------------------------------------------------ end to end: plan -> rules


EXAMPLES = Path(__file__).resolve().parents[1] / "examples"
# examples/geometry/unclaimed-face/step-block.STEP: the +Z upper land and the -Z bottom.
TOP, BOTTOM = "#104/ADVANCED_FACE[3]/", "#168/ADVANCED_FACE[5]/"


def _two_sided_bundle(tmp_path, monkeypatch, s1_faces, s2_faces):
    """The unclaimed-face example with a two-sided finish feature cut over two setups."""
    root = tmp_path / "examples"
    shutil.copytree(EXAMPLES / "geometry" / "unclaimed-face", root / "geometry" / "two-sided")
    for name in ("geometry/inventory.toml", "geometry/shop-policy.toml", "cutting-data.toml"):
        shutil.copy(EXAMPLES / name, root / name)
    bundle_dir = root / "geometry" / "two-sided"
    features = (bundle_dir / "features.toml").read_text(encoding="utf-8")
    features = features.replace(
        "[features.end_face]",
        '[features.broad]\nkind = "face"\nframe = "model"\nrequirements = ["finish_ra"]\n'
        f'finish_ra = 1.6\nfaces = ["{TOP}", "{BOTTOM}"]\n\n[features.end_face]',
    )
    features += (
        "\n[frames.B]\norigin = [0.0, 0.0, 0.0]\nx = [1.0, 0.0, 0.0]\ny = [0.0, -1.0, 0.0]\n"
        'z = [0.0, 0.0, -1.0]\nbinding = "unknown"\n'
    )
    (bundle_dir / "features.toml").write_text(features, encoding="utf-8")
    path = bundle_dir / "plan.toml"
    bundle = load_bundle(path)
    supplied_faces = bundle.plan["stock"]["as_is_faces"]
    bundle.plan["stock"] = {
        "form": "rectangular_blank",
        "section_mm": [40.0, 20.0],
        "length_mm": 60.0,
        "origin_mm": [0.0, 0.0, 0.0],
        "axis": [1.0, 0.0, 0.0],
        "section_axis": [0.0, 1.0, 0.0],
        "as_is_faces": sorted((set(supplied_faces) | {"#185/ADVANCED_FACE[6]/"}) - {TOP, BOTTOM}),
    }

    first = deepcopy(bundle.plan["setups"][-1])
    first.update(id="S1", frame="A", stock_in="stock")
    first["ops"] = [
        {
            "op": 10,
            "do": "rough_pocket",
            "feature": "step",
            "tool": "em-preparation",
            "holder": "unknown",
            "to_z": 10.0,
            "stock_removal_bounds": {
                "x": [30.0, 60.0],
                "y": [0.0, 40.0],
                "z": [10.0, 20.0],
            },
        },
        {
            "op": 20,
            "do": "finish_face",
            "feature": "broad",
            "tool": "em-8-std",
            "holder": "r8-collet-8mm",
            "to_z": 20.0,
            **tomllib.loads(s1_faces),
        },
    ]
    second = deepcopy(first)
    second.update(id="S2", frame="B", stock_in="S1")
    second["ops"] = [
        {
            "op": 10,
            "do": "finish_face",
            "feature": "broad",
            "tool": "em-8-std",
            "holder": "r8-collet-8mm",
            "to_z": 0.0,
            **tomllib.loads(s2_faces),
        }
    ]
    bundle.plan["setups"] = [first, second]
    monkeypatch.setenv("PRECHIPS_KERNEL_CACHE", str(tmp_path / "cache"))
    return bundle


def test_complementary_top_and_bottom_finishing_cuts_cover_a_two_sided_feature(
    tmp_path, monkeypatch, freecad_kernel
):
    bundle = _two_sided_bundle(tmp_path, monkeypatch, f'faces = ["{TOP}"]', f'faces = ["{BOTTOM}"]')
    for rule in (accessibility, reach):
        rows = _rows(rule, bundle)
        assert rows["S1:20"].status == "pass" and rows["S2:10"].status == "pass", rule
    assert _rows(finish_coverage, bundle)["broad"].status == "pass"
    assert _rows(coverage, bundle)["step-block"].status == "pass"


def test_whole_feature_claims_from_both_sides_finish_it_but_each_op_names_its_far_side(
    tmp_path, monkeypatch, freecad_kernel
):
    bundle = _two_sided_bundle(tmp_path, monkeypatch, "", "")
    rows = _rows(accessibility, bundle)
    assert rows["S1:20"].status == "error" and BOTTOM in rows["S1:20"].sentence
    assert rows["S2:10"].status == "error" and TOP in rows["S2:10"].sentence
    assert _rows(finish_coverage, bundle)["broad"].status == "pass"
    assert _rows(coverage, bundle)["step-block"].status == "pass"


def test_a_far_side_claim_never_credits_finish_or_coverage(tmp_path, monkeypatch, freecad_kernel):
    bundle = _two_sided_bundle(tmp_path, monkeypatch, f'faces = ["{BOTTOM}"]', f'faces = ["{TOP}"]')
    finish = _rows(finish_coverage, bundle)["broad"]
    assert finish.status == "error" and "lack a finishing cut" in finish.sentence
    cover = _rows(coverage, bundle)["step-block"]
    assert cover.status == "error" and cover.numbers["unclaimed_faces"] == [TOP, BOTTOM]


# --------------------------------------------------------------------------- rules


def _frame(z):
    return {"origin": [0.0, 0.0, 0.0], "x": [1.0, 0.0, 0.0], "y": [0.0, z, 0.0], "z": [0.0, 0.0, z]}


def _op_row(number, feature, faces=None, do="finish_face"):
    row = {"op": number, "do": do, "feature": feature, "tool": "em", "holder": "holder"}
    if faces is not None:
        row["faces"] = faces
    return row


def _facts(claimed, errors):
    return {
        "sample_count": 4,
        "tool_hits": 0,
        "holder_hits": 0,
        "reach_depth_mm": 8.0,
        "holder_wall_hits": 0,
        "corner_radii_mm": [],
        "claimed_indices": claimed,
        "claim_errors": errors,
    }


@pytest.fixture
def bundle(tmp_path):
    """Two setups flip a block; feature ``ends`` binds both broad faces #1 (+Z) and #2 (-Z)."""
    hold = {
        "fixture": "vise",
        "parallels": "parallels",
        "fixed_jaw": "rear",
        "jaws_along": "x",
        "grip_mm": 4.0,
        "jaw_above_parallels_mm": 4.0,
        "method": "hard_jaws",
    }
    return Bundle(
        {
            "part": "block",
            "stock": {"as_is_faces": ["#3"]},
            "setups": [
                {
                    "id": "S1",
                    "machine": "mill",
                    "frame": "A",
                    "hold": hold,
                    "ops": [_op_row(10, "ends")],
                },
                {
                    "id": "S2",
                    "machine": "mill",
                    "frame": "B",
                    "hold": hold,
                    "ops": [_op_row(10, "ends")],
                },
            ],
        },
        {
            "units": "mm",
            "step_sha256": "a" * 64,
            "frames": {"A": _frame(1.0), "B": _frame(-1.0)},
            "features": {
                "ends": {
                    "kind": "face",
                    "faces": ["#1", "#2"],
                    "finish_ra": 1.6,
                    "requirements": ["finish_ra"],
                }
            },
        },
        {
            "machines": {"mill": {"kind": "mill"}},
            "tools": {
                "em": {
                    "kind": "endmill",
                    "dia_mm": 6.0,
                    "flute_len_mm": 10.0,
                    "oal_mm": 30.0,
                    "projection_mm": {"holder": 25.0},
                    "verify": False,
                }
            },
            "holders": {
                "holder": {
                    "kind": "collet",
                    "gauge_dia_mm": 20.0,
                    "gauge_len_mm": 15.0,
                    "verify": False,
                }
            },
            "fixtures": {
                "vise": {
                    "kind": "vise",
                    "jaw_width_mm": 50.0,
                    "jaw_depth_mm": 12.0,
                    "jaw_height_mm": 20.0,
                    "opening_mm": 60.0,
                    "verify": False,
                },
                "parallels": {"kind": "parallels", "height_mm": 16.0, "verify": False},
            },
        },
        {"required": {}, "numbers": {"thin_wall_floor_mm": 2.0}, "numbers_verify": False},
        {},
        {},
        {},
        tmp_path,
        {
            "status": "ok",
            "bbox_mm": [0.0, 0.0, 0.0, 50.0, 20.0, 10.0],
            "faces": [
                {"ref": "#1", "index": 1},
                {"ref": "#2", "index": 2},
                {"ref": "#3", "index": 3},
            ],
            "mapping": {"#1": 1, "#2": 2, "#3": 3},
            "mapping_errors": {},
            "features": {"ends": [1, 2]},
            "ops": {"S1:10": _facts([1], ["#2"]), "S2:10": _facts([2], ["#1"])},
            "setups": {
                name: {
                    "parallel_pair": True,
                    "width_mm": 20.0,
                    "contact_grip_mm": [4.0, 4.0],
                    "claimed_in_jaws": [],
                    "min_wall_mm": 2.0,
                }
                for name in ("S1", "S2")
            },
        },
    )


def _rows(rule, bundle):
    return {row.subject: row for row in rule.evaluate(bundle)}


@pytest.mark.parametrize("rule", [accessibility, reach, internal_corner_radius])
def test_whole_feature_claims_name_the_face_facing_away_in_each_setup(bundle, rule):
    rows = _rows(rule, bundle)
    assert rows["S1:10"].status == rows["S2:10"].status == "error"
    assert "#2" in rows["S1:10"].sentence and "#1" not in rows["S1:10"].sentence
    assert "#1" in rows["S2:10"].sentence and "#2" not in rows["S2:10"].sentence
    assert rows["S1:10"].numbers["claim_errors"] == ["#2"]


@pytest.mark.parametrize("rule", [accessibility, reach, internal_corner_radius])
def test_far_side_claim_is_an_error_before_cutter_dimensions_are_asked_for(bundle, rule):
    bundle.inventory["tools"]["em"]["verify"] = True
    bundle.inventory["fixtures"]["vise"]["verify"] = True
    rows = _rows(rule, bundle)
    assert rows["S1:10"].status == "error" and "#2" in rows["S1:10"].sentence


def test_coverage_and_finish_credit_only_the_side_each_setup_can_cut(bundle):
    assert _rows(coverage, bundle)["block"].status == "pass"
    assert _rows(finish_coverage, bundle)["ends"].status == "pass"
    # Without the flipped setup, S1:10's rejected far side credits nothing.
    del bundle.plan["setups"][1]
    row = _rows(coverage, bundle)["block"]
    assert row.status == "error" and row.numbers["unclaimed_faces"] == ["#2"]
    finish = _rows(finish_coverage, bundle)["ends"]
    assert finish.status == "error" and finish.numbers["uncovered_faces"] == [2]


def test_explicit_faces_make_valid_claims_and_coverage_follows_them(bundle):
    for position, ref, index in ((0, "#1", 1), (1, "#2", 2)):
        bundle.plan["setups"][position]["ops"][0]["faces"] = [ref]
        bundle.kernel["ops"][f"S{position + 1}:10"] = _facts([index], [])
    for rule, status in ((accessibility, "pass"), (reach, "pass"), (internal_corner_radius, "n/a")):
        expected = "not_applicable" if status == "n/a" else status
        assert {row.status for row in rule.evaluate(bundle)} == {expected}
    assert _rows(coverage, bundle)["block"].status == "pass"
    assert _rows(finish_coverage, bundle)["ends"].status == "pass"
    assert _rows(vise, bundle)["S1"].status == "pass"


def test_explicit_claim_may_name_a_bound_face_outside_its_feature(bundle):
    bundle.features["features"]["ends"]["faces"] = ["#2"]
    bundle.kernel["features"]["ends"] = [2]
    bundle.plan["setups"][0]["ops"][0]["faces"] = ["#1"]
    bundle.kernel["ops"]["S1:10"] = _facts([1], [])
    assert _rows(accessibility, bundle)["S1:10"].status == "pass"
    assert _rows(coverage, bundle)["block"].status == "pass"


def test_explicit_claim_of_an_unmapped_ref_names_it(bundle):
    bundle.plan["setups"][0]["ops"][0]["faces"] = ["#999"]
    bundle.kernel["mapping_errors"]["#999"] = "STEP entity does not exist"
    bundle.kernel["ops"]["S1:10"] = {"reason": "x", "reasons": {}, "mapping_errors": ["#999"]}
    for rule in (accessibility, reach, internal_corner_radius, coverage, finish_coverage):
        rows = rule.evaluate(bundle)
        assert any(row.status == "error" and "#999" in row.sentence for row in rows), rule


def _unresolved(bundle, subject="S1:10", **extra):
    """Engine facts for a claim whose direction is unresolved: measured facts unknown."""
    reason = "face normal undefined at 3 sample(s) of #1"
    facts = {"claimed_indices": "unknown", "claim_errors": [], "reasons": {}, "reason": reason}
    for key in ("sample_count", "tool_hits", "holder_hits", "reach_depth_mm", "holder_wall_hits"):
        facts[key] = "unknown"
        facts["reasons"][key] = reason
    facts["corner_radii_mm"] = "unknown"
    facts["reasons"]["corner_radii_mm"] = reason
    facts["reasons"]["claimed_indices"] = reason
    facts.update(extra)
    bundle.kernel["ops"][subject] = facts
    return reason


@pytest.mark.parametrize("rule", [accessibility, reach, internal_corner_radius])
def test_unresolved_claim_direction_is_unknown_with_its_reason(bundle, rule):
    reason = _unresolved(bundle)
    row = _rows(rule, bundle)["S1:10"]
    assert row.status == "unknown" and reason in row.sentence


def test_unresolved_claim_direction_is_never_credited(bundle):
    _unresolved(bundle)
    assert _rows(coverage, bundle)["block"].status == "unknown"
    assert _rows(finish_coverage, bundle)["ends"].status == "unknown"


def test_certain_hits_still_fail_accessibility_when_the_claim_direction_is_unresolved(bundle):
    _unresolved(bundle, min_hits={"tool": 40, "holder": 0})
    row = _rows(accessibility, bundle)["S1:10"]
    assert row.status == "error" and "certainly occluded" in row.sentence
    assert row.numbers["certain_tool_hits"] == 40


# --------------------------------------------------------------------------- stock debt


STOCK_REASON = "stock_in 'unknown' of the first setup is not the supplied 'stock'"


def _unproven_stock(bundle):
    """A setup whose in-process stock is unknown while its tool and vise are also unmeasured."""
    for subject in ("S1:10", "S2:10"):
        bundle.kernel["ops"][subject] = _facts([int(subject[1])], [])
    op = bundle.kernel["ops"]["S1:10"]
    op["stock_reason"] = STOCK_REASON
    op["reason"] = f"in-process stock unknown: {STOCK_REASON}"
    op["reasons"] = {}
    measured = ("tool_hits", "holder_hits", "reach_depth_mm", "holder_wall_hits")
    for key in measured:
        op[key] = "unknown"
        op["reasons"][key] = op["reason"]
    setup = bundle.kernel["setups"]["S1"]
    setup["stock_reason"] = setup["reason"] = STOCK_REASON
    setup["reasons"] = {}
    for key in ("parallel_pair", "width_mm", "contact_grip_mm", "claimed_in_jaws", "min_wall_mm"):
        setup[key] = "unknown"
        setup["reasons"][key] = STOCK_REASON
    bundle.inventory["tools"]["em"]["verify"] = True
    bundle.inventory["fixtures"]["vise"]["verify"] = True


@pytest.mark.parametrize("rule", [accessibility, reach])
def test_unknown_stock_is_named_before_tool_and_holding_debt(bundle, rule):
    _unproven_stock(bundle)
    row = _rows(rule, bundle)["S1:10"]
    assert row.status == "unknown" and STOCK_REASON in row.sentence
    assert "unmeasured" not in row.sentence


def test_unknown_stock_is_named_by_the_vise_rule_before_holding_debt(bundle):
    _unproven_stock(bundle)
    row = _rows(vise, bundle)["S1"]
    assert row.status == "unknown" and STOCK_REASON in row.sentence


def test_far_side_claims_outrank_unknown_stock(bundle):
    _unproven_stock(bundle)
    bundle.kernel["ops"]["S1:10"]["claim_errors"] = ["#2"]
    row = _rows(accessibility, bundle)["S1:10"]
    assert row.status == "error" and "#2" in row.sentence


def test_stale_claim_facts_are_not_used_when_the_claimed_refs_are_unknown(bundle):
    bundle.plan["setups"][0]["ops"][0]["faces"] = "unknown"
    assert _rows(accessibility, bundle)["S1:10"].status == "unknown"
    assert _rows(accessibility, bundle)["S2:10"].status == "error"
    assert _rows(coverage, bundle)["block"].status == "unknown"


LATHE_APPROACH_REASON = "lathe approach model not implemented (engine approaches along -Z only)"


@pytest.mark.parametrize("rule", [accessibility, reach, internal_corner_radius])
@pytest.mark.parametrize("machine", ["lathe", "mill", "unknown"])
@pytest.mark.parametrize("action", ["finish_turn", "form_dome", "finish_groove", "part_off"])
def test_turning_actions_never_use_milling_direction_verdicts(bundle, rule, machine, action):
    setup = bundle.plan["setups"][0]
    setup["machine"] = machine
    setup["ops"][0]["do"] = action
    bundle.inventory["machines"]["lathe"] = {"kind": "lathe"}
    # Raw -Z facts reject #2 and even report a collision on #1; neither is a lathe fact.
    bundle.kernel["ops"]["S1:10"]["min_hits"] = {"tool": 40, "holder": 0}
    row = _rows(rule, bundle)["S1:10"]
    assert row.status == "unsupported"
    assert row.sentence == f"S1:10: {LATHE_APPROACH_REASON}."
    assert "claim_errors" not in row.numbers


@pytest.mark.parametrize("rule", [accessibility, reach, internal_corner_radius])
def test_lathe_machine_blocks_shared_facing_action_direction_verdict(bundle, rule):
    setup = bundle.plan["setups"][0]
    setup["machine"] = "selected-machine"
    bundle.inventory["machines"]["selected-machine"] = {"kind": "lathe"}
    row = _rows(rule, bundle)["S1:10"]
    assert row.status == "unsupported"
    assert row.sentence == f"S1:10: {LATHE_APPROACH_REASON}."
    # The other setup is still a mill and must retain its real far-side error.
    milling = _rows(rule, bundle)["S2:10"]
    assert milling.status == "error"
    assert milling.numbers["claim_errors"] == ["#1"]


@pytest.mark.parametrize(
    "rule", [accessibility, reach, internal_corner_radius, coverage, finish_coverage]
)
def test_invalid_lathe_face_claim_is_error_before_unsupported_model(bundle, rule):
    setup = bundle.plan["setups"][0]
    setup["ops"][0].update(do="finish_turn", faces=["#999"])
    bundle.kernel["mapping_errors"]["#999"] = "STEP entity does not exist"
    subject = "block" if rule is coverage else "ends" if rule is finish_coverage else "S1:10"
    row = _rows(rule, bundle)[subject]
    assert row.status == "error"
    assert row.numbers["mapping_errors"] == ["#999"]


@pytest.mark.parametrize("refs", ["unknown", ["#unmapped"]])
@pytest.mark.parametrize(
    "rule", [accessibility, reach, internal_corner_radius, coverage, finish_coverage]
)
def test_unresolved_lathe_refs_are_not_hidden_by_unsupported_model(bundle, rule, refs):
    bundle.plan["setups"][0]["ops"][0].update(do="finish_turn", faces=refs)
    bundle.kernel["ops"]["S1:10"]["min_hits"] = {"tool": 40, "holder": 0}
    subject = "block" if rule is coverage else "ends" if rule is finish_coverage else "S1:10"
    row = _rows(rule, bundle)[subject]
    assert row.status == "unknown"


@pytest.mark.parametrize("raw_claimed,raw_away", [([], ["#1", "#2"]), ([1, 2], [])])
def test_lathe_only_coverage_is_unsupported_for_raw_away_or_valid_claims(
    bundle, raw_claimed, raw_away
):
    del bundle.plan["setups"][1]
    bundle.plan["setups"][0]["ops"][0]["do"] = "finish_turn"
    bundle.kernel["ops"]["S1:10"] = _facts(raw_claimed, raw_away)
    cover = _rows(coverage, bundle)["block"]
    finish = _rows(finish_coverage, bundle)["ends"]
    assert cover.status == finish.status == "unsupported"
    assert cover.sentence == f"block: {LATHE_APPROACH_REASON}."
    assert finish.sentence == f"ends: {LATHE_APPROACH_REASON}."
    assert cover.numbers["claimed_face_count"] == 1  # Only the as-stock face is credited.
    assert finish.numbers["uncovered_faces"] == [1, 2]


def test_supported_milling_claims_can_complete_coverage_alongside_lathe(bundle):
    lathe = bundle.plan["setups"][0]["ops"][0]
    lathe.update(do="finish_turn", faces=["#1"])
    mill = bundle.plan["setups"][1]["ops"][0]
    mill.update(faces=["#1", "#2"])
    bundle.kernel["ops"]["S2:10"] = _facts([1, 2], [])
    assert _rows(coverage, bundle)["block"].status == "pass"
    assert _rows(finish_coverage, bundle)["ends"].status == "pass"


def test_unsupported_lathe_claim_does_not_hide_uncovered_milling_faces(bundle):
    lathe = bundle.plan["setups"][0]["ops"][0]
    lathe.update(do="finish_turn", faces=["#1"])
    mill = bundle.plan["setups"][1]["ops"][0]
    mill.update(faces=["#2"])
    bundle.kernel["ops"]["S2:10"] = _facts([], ["#2"])
    assert _rows(accessibility, bundle)["S2:10"].status == "error"
    assert _rows(coverage, bundle)["block"].status == "error"
    assert _rows(finish_coverage, bundle)["ends"].status == "error"


def test_finish_coverage_limits_unsupported_to_faces_needed_by_each_feature(bundle):
    bundle.plan["setups"][0]["ops"][0].update(do="finish_turn", faces=["#1"])
    bundle.plan["setups"][1]["ops"][0]["faces"] = ["#2"]
    bundle.kernel["ops"]["S2:10"] = _facts([2], [])
    bundle.features["features"]["milled_side"] = {
        "kind": "face",
        "faces": ["#2"],
        "finish_ra": 1.6,
        "requirements": ["finish_ra"],
    }
    bundle.kernel["features"]["milled_side"] = [2]
    rows = _rows(finish_coverage, bundle)
    assert rows["ends"].status == "unsupported"
    assert rows["ends"].numbers["uncovered_faces"] == [1]
    assert rows["milled_side"].status == "pass"
    assert rows["milled_side"].numbers["uncovered_faces"] == []


@pytest.mark.parametrize("rule", [accessibility, reach, internal_corner_radius])
def test_generic_milling_profile_keeps_its_real_direction_error(bundle, rule):
    bundle.plan["setups"][0]["ops"][0]["do"] = "profile"
    row = _rows(rule, bundle)["S1:10"]
    assert row.status == "error"
    assert row.numbers["claim_errors"] == ["#2"]


def test_generic_profile_on_a_resolved_lathe_is_still_unsupported(bundle):
    setup = bundle.plan["setups"][0]
    setup["machine"] = "selected-machine"
    setup["ops"][0]["do"] = "profile"
    bundle.inventory["machines"]["selected-machine"] = {"kind": "lathe"}
    row = _rows(accessibility, bundle)["S1:10"]
    assert row.status == "unsupported"
    assert row.sentence == f"S1:10: {LATHE_APPROACH_REASON}."
