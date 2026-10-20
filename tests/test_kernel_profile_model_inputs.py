"""Explicit guided-profile intent reaches native inputs without a geometry claim."""

from copy import deepcopy
from pathlib import Path

import pytest
from test_geometry_rules import rules_bundle

from prechips import kernel
from prechips.inputs import load_bundle
from prechips.rules import coordinates

TNUT = Path(__file__).resolve().parents[1] / "examples/blondihacks-t-nuts/plan.toml"


@pytest.mark.parametrize("action", ["profile", "rough_profile", "finish_profile"])
@pytest.mark.parametrize("guide", ["unknown", {}, {"x": [0, 20], "y": [0, 10]}, []])
def test_explicit_sweep_bounds_always_select_guided_profile_model(tmp_path, action, guide):
    data = rules_bundle(tmp_path)
    setup = data.plan["setups"][0]
    op = setup["ops"][0]
    op.update(do=action, contour={"sweep_bounds": deepcopy(guide)})
    prepared = kernel.op_inputs(data, setup, op, finishing=set(), complete=set())
    assert prepared["profile_model"] == "guided_sweep"
    assert kernel._engine_op(prepared)["profile_model"] == "guided_sweep"
    # This is intent, not proof of a path or validity of the authored guide.
    assert "checkpoints" not in prepared
    assert op["contour"]["sweep_bounds"] == guide


def test_guided_marker_preserves_broad_box_precedence_inputs(tmp_path):
    data = rules_bundle(tmp_path)
    setup = data.plan["setups"][0]
    op = setup["ops"][0]
    op.update(
        contour={"sweep_bounds": "unknown"},
        stock_removal_bounds={"x": [0, 20], "y": [0, 10], "z": [0, 6]},
    )
    prepared = kernel.op_inputs(data, setup, op, finishing=set(), complete=set())
    native = kernel._engine_op(prepared)
    assert native["profile_model"] == "guided_sweep"
    assert native["stock_removal_bounds"] == {"x": [0, 20], "y": [0, 10], "z": [0, 6]}


@pytest.mark.parametrize("action", ["finish_face", "rough_face", "drill"])
def test_explicit_guide_does_not_select_profile_model_for_other_actions(tmp_path, action):
    data = rules_bundle(tmp_path)
    setup = data.plan["setups"][0]
    op = setup["ops"][0]
    op.update(do=action, contour={"sweep_bounds": "unknown"})
    prepared = kernel.op_inputs(data, setup, op, finishing=set(), complete=set())
    assert "profile_model" not in prepared
    assert "profile_model" not in kernel._engine_op(prepared)


def test_guided_model_changes_operative_identity_but_presentation_does_not(tmp_path):
    data = rules_bundle(tmp_path)
    setup = data.plan["setups"][0]
    op = setup["ops"][0]
    ordinary = kernel._engine_op(kernel.op_inputs(data, setup, op, finishing=set(), complete=set()))
    assert "profile_model" not in ordinary
    op["contour"] = {"sweep_bounds": "unknown"}
    guided = kernel._engine_op(kernel.op_inputs(data, setup, op, finishing=set(), complete=set()))
    assert kernel._json(kernel._cache_recipe({"stock": {}, "ops": [guided]})) != kernel._json(
        kernel._cache_recipe({"stock": {}, "ops": [ordinary]})
    )
    op["note"] = "Additional hobby explanation; no change to the cut."
    annotated = kernel._engine_op(
        kernel.op_inputs(data, setup, op, finishing=set(), complete=set())
    )
    assert annotated == guided


def linear_numbers(op=20):
    return {
        "operations": [{"op": op, "dro_to_z": -2.0, "z_levels": {"levels": [-1.0, -2.0]}}],
        "profiles": [
            {
                "op": op,
                "stage": "finish",
                "contour": {"method": "linear_table"},
                "dro_to_z": -2.0,
                "cut_order": "conventional",
                "cutter_centre": [[1.0, 2.0], [10.0, 2.0], [10.0, 9.0], [1.0, 2.0]],
            }
        ],
    }


def test_canonical_linear_paths_keep_distinct_final_depth_identity_without_level_copies():
    numbers = linear_numbers()
    source = deepcopy(numbers)
    (path,) = coordinates.checkpoints("S1:20", numbers, 20)
    assert path["kind"] == path["method"] == "linear_table"
    assert path["material_scope"] == "final_depth"
    assert path["name"] == "S1:20 finish linear path 1 final depth"
    assert [row[1] for row in path["rows"]] == numbers["profiles"][0]["cutter_centre"]
    assert [row[2] for row in path["rows"]] == [-2.0] * 4
    assert [row[0] for row in path["rows"]] == [
        f"{path['name']} point {vertex}" for vertex in range(4)
    ]
    assert path["directed"] is True
    assert path["bounded"] is False
    assert numbers == source


def test_guided_adapter_converts_printed_final_depth_exactly_once():
    numbers = linear_numbers()
    printed = coordinates.checkpoints("S1:20", numbers, 20)
    native = kernel.table_checkpoints("S1:20", numbers, 20, "in", profile_model="guided_sweep")
    assert "reason" not in native
    assert [path["tip_z_mm"] for path in native["paths"]] == [-50.8]
    for path, canonical in zip(native["paths"], printed, strict=True):
        assert path["kind"] == "linear_table"
        assert path["material_scope"] == "final_depth"
        assert path["ids"] == [row[0] for row in canonical["rows"]]
        assert path["xy_mm"] == [[value * 25.4 for value in row[1]] for row in canonical["rows"]]
    assert kernel.table_checkpoints("S1:20", numbers, 20, "in") is None


@pytest.mark.parametrize(
    "levels",
    [None, "unknown", {}, {"levels": []}, {"levels": "unknown"}, {"levels": [-1, "unknown"]}],
)
def test_material_final_depth_does_not_claim_unknown_axial_schedule_is_proven(levels):
    numbers = linear_numbers()
    numbers["operations"][0]["z_levels"] = levels
    source = deepcopy(numbers)
    native = kernel.table_checkpoints("S1:20", numbers, 20, "mm", profile_model="guided_sweep")
    assert "reason" not in native
    assert [path["tip_z_mm"] for path in native["paths"]] == [-2.0]
    assert all(path["material_scope"] == "final_depth" for path in native["paths"])
    assert (
        "Z levels or start Z are unknown" in kernel.tool_paths({"op": 20}, numbers, "mm")["reason"]
    )
    assert numbers == source


def test_final_material_rows_do_not_change_when_axial_recipe_is_absent():
    numbers = linear_numbers()
    del numbers["operations"][0]["z_levels"]
    native = kernel.table_checkpoints("S1:20", numbers, 20, "mm", profile_model="guided_sweep")
    assert "reason" not in native
    assert [path["tip_z_mm"] for path in native["paths"]] == [-2.0]


@pytest.mark.parametrize("bad", ["unknown", float("nan"), float("inf")])
@pytest.mark.parametrize("field", ["xy", "tip"])
def test_one_unknown_or_nonfinite_profile_value_poisoning_the_whole_cut_is_not_omitted(bad, field):
    numbers = linear_numbers()
    if field == "xy":
        numbers["profiles"][0]["cutter_centre"][1][0] = bad
    else:
        numbers["profiles"][0]["dro_to_z"] = bad
    native = kernel.table_checkpoints("S1:20", numbers, 20, "mm", profile_model="guided_sweep")
    assert native["reason"]


def test_raster_checkpoint_passes_never_gain_a_join_or_rapid_return():
    numbers = linear_numbers()
    passes = [[[1.0, 2.0], [10.0, 2.0]], [[10.0, 4.0], [1.0, 4.0]]]
    numbers["profiles"][0]["cutter_centre"] = deepcopy(passes)
    native = kernel.table_checkpoints("S1:20", numbers, 20, "mm", profile_model="guided_sweep")
    assert "reason" not in native
    assert [path["xy_mm"] for path in native["paths"]] == passes
    assert [path["tip_z_mm"] for path in native["paths"]] == [-2.0, -2.0]
    assert [path["name"] for path in native["paths"]] == [
        "S1:20 finish linear path 1 final depth",
        "S1:20 finish linear path 2 final depth",
    ]


@pytest.mark.parametrize("broad", [False, True])
def test_linear_native_bridge_requires_explicit_guided_model_and_no_broad_box(tmp_path, broad):
    data = rules_bundle(tmp_path)
    setup = data.plan["setups"][0]
    op = setup["ops"][0]
    op.update(do="profile", contour={"method": "linear_table"})
    if broad:
        op["contour"]["sweep_bounds"] = {"x": [0, 20], "y": [0, 10], "z": [-2, 0]}
        op["stock_removal_bounds"] = {"x": [0, 20], "y": [0, 10], "z": [-2, 0]}
    prepared = kernel.op_inputs(
        data, setup, op, finishing=set(), complete=set(), tables=linear_numbers(op["op"])
    )
    assert "checkpoints" not in prepared
    assert "tool_paths" in prepared
    if broad:
        assert prepared["profile_model"] == "guided_sweep"
        assert prepared["stock_removal_bounds"] == op["stock_removal_bounds"]
    else:
        assert "profile_model" not in prepared


def test_real_tnut_job_consumes_actual_canonical_printed_guided_paths():
    bundle = load_bundle(TNUT)
    numbers = next(
        row.numbers for row in coordinates.evaluate(bundle, pre_kernel=True) if row.subject == "S1"
    )
    job = kernel.build_job(bundle)
    native = kernel._engine_setup(next(setup for setup in job["setups"] if setup["id"] == "S1"))
    for op_number, xs, ys in (
        (10, (-19.304, 107.569), (-12.8905, 12.8905)),
        (20, (-19.05, 107.315), (-12.6365, 12.6365)),
    ):
        op = next(item for item in native["ops"] if item["subject"] == f"S1:{op_number}")
        assert op["profile_model"] == "guided_sweep"
        assert "stock_removal_bounds" not in op
        checkpoints = op["checkpoints"]
        assert "reason" not in checkpoints
        printed = coordinates.checkpoints(f"S1:{op_number}", numbers, op_number)
        assert checkpoints["paths"]
        assert len(checkpoints["paths"]) == len(printed)
        operation = next(item for item in numbers["operations"] if item["op"] == op_number)
        assert {path["tip_z_mm"] for path in checkpoints["paths"]} == {operation["dro_to_z"]}
        assert operation["dro_to_z"] == -6.35
        for path, canonical in zip(checkpoints["paths"], printed, strict=True):
            assert path["kind"] == path["method"] == "linear_table"
            assert path["material_scope"] == "final_depth"
            assert path["ids"] == [row[0] for row in canonical["rows"]]
            assert path["xy_mm"] == [row[1] for row in canonical["rows"]]
            assert path["tip_z_mm"] == canonical["rows"][0][2]
            assert len(path["xy_mm"]) == 5 and path["xy_mm"][0] == path["xy_mm"][-1]
            assert (
                min(x for x, _ in path["xy_mm"]),
                max(x for x, _ in path["xy_mm"]),
            ) == pytest.approx(xs)
            assert (
                min(y for _, y in path["xy_mm"]),
                max(y for _, y in path["xy_mm"]),
            ) == pytest.approx(ys)


@pytest.mark.parametrize("guide", ["unknown", [], {}, {"x": [0, 113.665]}])
def test_explicit_unresolved_guide_never_uses_real_feature_bounds_instead(guide):
    bundle = load_bundle(TNUT)
    setup = next(item for item in bundle.plan["setups"] if item["id"] == "S1")
    op = next(item for item in setup["ops"] if item["op"] == 10)
    op["contour"]["sweep_bounds"] = deepcopy(guide)
    numbers = next(
        row.numbers for row in coordinates.evaluate(bundle, pre_kernel=True) if row.subject == "S1"
    )
    profiles = [profile for profile in numbers["profiles"] if profile["op"] == 10]
    assert profiles and all(profile["cutter_centre"] == "unknown" for profile in profiles)
    prepared = kernel.op_inputs(bundle, setup, op, finishing=set(), complete=set(), tables=numbers)
    assert prepared["profile_model"] == "guided_sweep"
    assert prepared["checkpoints"]["paths"] == []
    assert prepared["checkpoints"]["reason"]


def test_known_axial_schedule_cannot_replace_missing_final_printed_tip():
    numbers = linear_numbers()
    del numbers["profiles"][0]["dro_to_z"]
    native = kernel.table_checkpoints("S1:20", numbers, 20, "mm", profile_model="guided_sweep")
    assert native["paths"] == []
    assert native["reason"]


def test_unknown_raster_pass_is_not_omitted_beside_a_valid_final_depth_path():
    numbers = linear_numbers()
    numbers["profiles"][0]["cutter_centre"] = [
        [[0, 0], [10, 0]],
        [[10, 2], ["unknown", 2]],
    ]
    native = kernel.table_checkpoints("S1:20", numbers, 20, "mm", profile_model="guided_sweep")
    assert len(native["paths"]) == 1
    assert native["paths"][0]["xy_mm"] == [[0, 0], [10, 0]]
    assert native["reason"]
