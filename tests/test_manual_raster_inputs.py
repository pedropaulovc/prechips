"""Authored manual rasters cross print/native boundaries unchanged; no native runs."""

from copy import deepcopy

import pytest
from test_geometry_rules import rules_bundle

from prechips import kernel
from prechips.rules import coordinates
from prechips.rules.manual_raster import normalize


def trajectory():
    return {
        "start_mm": [1.125, 2.25, 8.0],
        "safe_z_mm": 8.0,
        "moves": [
            {"to_mm": [1.125, 2.25, 1.5], "mode": "clear"},
            {"to_mm": [12.125, 2.25, 1.5], "mode": "cut"},
            {"to_mm": [12.125, 2.25, 8.0], "mode": "clear"},
            {"to_mm": [12.125, 4.25, 8.0], "mode": "clear"},
            {"to_mm": [12.125, 4.25, 2.5], "mode": "clear"},
            {"to_mm": [1.125, 4.25, 2.5], "mode": "cut"},
            {"to_mm": [1.125, 4.25, 8.0], "mode": "clear"},
        ],
    }


def measured(value):
    return {
        "value": value,
        "measured": {"status": "measured", "by": "synthetic test", "date": "2026-11-07"},
    }


def raster_bundle(tmp_path):
    data = rules_bundle(tmp_path)
    data.kernel = None
    data.inventory["tools"]["em"].update(
        kind="ball_endmill",
        dia_mm=measured(6.0),
        shank_mm=measured(6.0),
        flute_len_mm=measured(10.0),
        oal_mm=measured(30.0),
        projection_mm={"holder": measured(25.0)},
    )
    data.inventory["holders"]["holder"].update(
        gauge_dia_mm=measured(20.0), gauge_len_mm=measured(15.0)
    )
    data.inventory["machines"]["mill"]["resolution_mm"] = measured(0.001)
    data.plan["dro"] = {"controller": "el400", "radius_mode": False}
    setup = data.plan["setups"][0]
    setup["stock_state"] = {"top_z": 5.0, "bottom_z": 0.0}
    op = setup["ops"][0]
    op["contour"] = {"method": "manual_ball_raster", "raster": trajectory()}
    return data, setup, op


def test_normalization_preserves_every_authored_number_and_move():
    authored = trajectory()
    original = deepcopy(authored)
    normalized = normalize(authored)
    assert normalized == original
    assert authored == original
    assert normalized is not authored
    assert normalized["moves"][0]["to_mm"] is not authored["moves"][0]["to_mm"]


@pytest.mark.parametrize("axis", [0, 1, 2])
@pytest.mark.parametrize("bad", ["unknown", float("nan"), float("inf"), True, None])
def test_unknown_nonfinite_or_boolean_point_withholds_entire_trajectory(axis, bad):
    authored = trajectory()
    authored["moves"][1]["to_mm"][axis] = bad
    assert set(normalize(authored)) == {"reason"}


@pytest.mark.parametrize("bad", ["unknown", float("nan"), float("inf"), False, None])
def test_unknown_clearance_withholds_entire_trajectory(bad):
    authored = trajectory()
    authored["safe_z_mm"] = bad
    assert set(normalize(authored)) == {"reason"}


@pytest.mark.parametrize(
    ("index", "target", "mode"),
    [
        (1, [12.125, 3.25, 1.5], "cut"),  # diagonal XY
        (1, [12.125, 2.25, 2.5], "cut"),  # sloping XZ
        (1, [1.125, 2.25, 2.5], "cut"),  # axial cutting
        (1, [1.125, 2.25, 1.5], "cut"),  # no movement
        (1, [12.125, 2.25, 1.5], "clear"),  # unsafe horizontal clear
        (2, [13.125, 2.25, 8.0], "clear"),  # diagonal retract
        (3, [11.125, 4.25, 8.0], "clear"),  # diagonal lifted move
        (1, [12.125, 2.25, 1.5], "rapid"),  # unsupported mode
    ],
)
def test_invalid_segments_never_gain_intermediate_points(index, target, mode):
    authored = trajectory()
    authored["moves"][index] = {"to_mm": target, "mode": mode}
    assert set(normalize(authored)) == {"reason"}


@pytest.mark.parametrize("end", ["start", "finish"])
def test_initial_and_final_clearance_are_required(end):
    authored = trajectory()
    if end == "start":
        authored["start_mm"][2] = 7.0
    else:
        authored["moves"].pop()
    assert set(normalize(authored)) == {"reason"}


def test_clear_only_path_cannot_claim_material_removal():
    authored = {"start_mm": [0, 0, 8], "safe_z_mm": 8, "moves": [
        {"to_mm": [10, 0, 8], "mode": "clear"},
    ]}
    assert set(normalize(authored)) == {"reason"}


@pytest.mark.parametrize("units", ["mm", "in"])
def test_public_and_native_raster_are_identical_setup_mm_without_axial_fallback(tmp_path, units):
    data, setup, op = raster_bundle(tmp_path)
    data.features["units"] = units
    public = coordinates.evaluate(data, pre_kernel=True)[0]
    entry = public.numbers["operations"][0]
    assert entry["manual_raster"] == trajectory()
    assert "z_levels" not in entry
    assert not public.numbers["profiles"]
    assert "axial levels" not in public.sentence
    prepared = kernel.op_inputs(data, setup, op, finishing=set(), complete=set(), tables=public.numbers)
    native = kernel._engine_op(prepared)
    assert native["manual_raster"] == entry["manual_raster"]
    assert native["contour_method"] == "manual_ball_raster"
    assert native["tool_kind"] == "ball_endmill"
    assert native["radius_mm"] == native["shank_radius_mm"] == 3.0
    assert native["shank_from_mm"] == native["flute_len_mm"] == 10.0
    assert native["projection_mm"] == 25.0
    assert native["oal_mm"] == 30.0
    assert native["holder_radius_mm"] == 10.0
    assert native["holder_gauge_len_mm"] == 15.0
    assert "tool_paths" not in native and "checkpoints" not in native
    assert not prepared["refused_fields"]


def test_printed_native_disagreement_withholds_trajectory(tmp_path):
    data, setup, op = raster_bundle(tmp_path)
    printed = {"operations": [{"op": op["op"], "manual_raster": trajectory()}]}
    printed["operations"][0]["manual_raster"]["moves"][1]["to_mm"][0] = 11.0
    prepared = kernel.op_inputs(data, setup, op, finishing=set(), complete=set(), tables=printed)
    assert set(prepared["manual_raster"]) == {"reason"}


def test_multiple_operations_keep_separate_authored_trajectories(tmp_path):
    data, setup, op = raster_bundle(tmp_path)
    second = deepcopy(op)
    second["op"] = 20
    second["contour"]["raster"]["safe_z_mm"] = 7.0
    setup["ops"].append(second)
    public = coordinates.evaluate(data, pre_kernel=True)[0]
    for entry, operation in zip(public.numbers["operations"], setup["ops"], strict=True):
        assert entry["manual_raster"] == operation["contour"]["raster"]
        native = kernel.op_inputs(data, setup, operation, finishing=set(), complete=set(), tables=public.numbers)
        assert native["manual_raster"] == entry["manual_raster"]


@pytest.mark.parametrize("field", ["dia_mm", "flute_len_mm", "shank_mm", "oal_mm"])
def test_unmeasured_ball_dimension_is_never_invented(tmp_path, field):
    data, setup, op = raster_bundle(tmp_path)
    data.inventory["tools"]["em"][field] = {"value": 6.0, "measured": {"status": "assumed"}}
    prepared = kernel.op_inputs(data, setup, op, finishing=set(), complete=set())
    assert prepared["refused_fields"]
    assert prepared["reason"]


@pytest.mark.parametrize("method", ["unknown", "ball_magic", None])
def test_unregistered_contour_method_reaches_native_refusal_guard(tmp_path, method):
    data, setup, op = raster_bundle(tmp_path)
    op["contour"] = {} if method is None else {"method": method}
    public = coordinates.evaluate(data, pre_kernel=True)[0]
    assert public.status == "unknown"
    assert "no registered motion proof" in public.sentence
    assert "z_levels" not in public.numbers["operations"][0]
    prepared = kernel.op_inputs(data, setup, op, finishing=set(), complete=set())
    assert kernel._engine_op(prepared)["contour_method"] == (method or "unknown")


def test_invalid_raster_remains_identically_refused_in_public_and_native_tables(tmp_path):
    data, setup, op = raster_bundle(tmp_path)
    op["contour"]["raster"]["moves"][0]["to_mm"][0] = "unknown"
    public = coordinates.evaluate(data, pre_kernel=True)[0]
    assert public.status == "unknown"
    printed = public.numbers["operations"][0]["manual_raster"]
    assert set(printed) == {"reason"}
    prepared = kernel.op_inputs(data, setup, op, finishing=set(), complete=set(), tables=public.numbers)
    assert prepared["manual_raster"] == printed
