"""Authored manual rasters cross print/native boundaries unchanged; no native runs."""

from copy import deepcopy
from dataclasses import replace

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
        "measured": {
            "status": "measured",
            "by": "synthetic test",
            "date": "2026-11-07",
            "instrument": "synthetic calibrated gauge",
        },
    }


def raster_bundle(tmp_path, *, kind="ball_endmill", corner_radius=3.0):
    data = replace(rules_bundle(tmp_path), kernel=None)
    data.inventory["tools"]["em"].update(
        kind=kind,
        dia_mm=measured(6.0),
        nose_radius_mm=measured(corner_radius),
        shank_mm=measured(6.0),
        body_envelope_dia_mm=measured(6.0),
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
    op["contour"] = {"method": "manual_raster", "raster": trajectory()}
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
    authored = {
        "start_mm": [0, 0, 8],
        "safe_z_mm": 8,
        "moves": [
            {"to_mm": [10, 0, 8], "mode": "clear"},
        ],
    }
    assert set(normalize(authored)) == {"reason"}


@pytest.mark.parametrize("units", ["mm", "in"])
@pytest.mark.parametrize(("kind", "corner_radius"), [("ball_endmill", 3.0), ("endmill", 0.2)])
def test_public_and_native_raster_are_identical_setup_mm_without_axial_fallback(
    tmp_path, units, kind, corner_radius
):
    data, setup, op = raster_bundle(tmp_path, kind=kind, corner_radius=corner_radius)
    data.features["units"] = units
    public = coordinates.evaluate(data, pre_kernel=True)[0]
    entry = public.numbers["operations"][0]
    assert entry["manual_raster"] == trajectory()
    assert coordinates.printed_xy(public.numbers, op["op"]) == [
        trajectory()["start_mm"][:2],
        *[move["to_mm"][:2] for move in trajectory()["moves"]],
    ]
    assert "z_levels" not in entry
    assert not public.numbers["profiles"]
    assert "axial levels" not in public.sentence
    prepared = kernel.op_inputs(
        data, setup, op, finishing=set(), complete=set(), tables=public.numbers
    )
    native = kernel._engine_op(prepared)
    assert native["manual_raster"] == entry["manual_raster"]
    assert native["contour_method"] == "manual_raster"
    assert native["tool_kind"] == kind
    assert native["radius_mm"] == native["shank_radius_mm"] == 3.0
    assert native["nose_radius_mm"] == corner_radius
    assert native["shank_from_mm"] == native["flute_len_mm"] == 10.0
    assert native["shank_geometry"] == "enclosing_cylinder"
    assert native["shank_envelope_radius_mm"] == 3.0
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
        native = kernel.op_inputs(
            data, setup, operation, finishing=set(), complete=set(), tables=public.numbers
        )
        assert native["manual_raster"] == entry["manual_raster"]


@pytest.mark.parametrize(
    "field", ["dia_mm", "flute_len_mm", "shank_mm", "nose_radius_mm", "body_envelope_dia_mm"]
)
@pytest.mark.parametrize("missing", [False, True], ids=["assumed", "missing"])
@pytest.mark.parametrize("kind", ["ball_endmill", "endmill"])
def test_unmeasured_cutter_dimension_is_never_invented(tmp_path, field, missing, kind):
    data, setup, op = raster_bundle(tmp_path, kind=kind)
    if missing:
        del data.inventory["tools"]["em"][field]
    else:
        data.inventory["tools"]["em"][field] = {"value": 6.0, "measured": {"status": "assumed"}}
    prepared = kernel.op_inputs(data, setup, op, finishing=set(), complete=set())
    assert prepared["refused_fields"]
    assert prepared["reason"]


@pytest.mark.parametrize(
    "overall_length",
    [None, "unknown", {"value": 30.0, "measured": {"status": "assumed"}}],
    ids=["missing", "unknown", "assumed"],
)
def test_optional_oal_never_replaces_measured_mounted_geometry(tmp_path, overall_length):
    data, setup, op = raster_bundle(tmp_path)
    if overall_length is None:
        del data.inventory["tools"]["em"]["oal_mm"]
    else:
        data.inventory["tools"]["em"]["oal_mm"] = overall_length
    prepared = kernel.op_inputs(data, setup, op, finishing=set(), complete=set())
    native = kernel._engine_op(prepared)
    assert "oal_mm" not in native
    assert "reason" not in prepared
    assert not prepared["refused_fields"]
    assert native["projection_mm"] == 25.0
    assert native["flute_len_mm"] == native["shank_from_mm"] == 10.0
    assert native["radius_mm"] == native["nose_radius_mm"] == native["shank_radius_mm"] == 3.0
    assert native["holder_radius_mm"] == 10.0
    assert native["holder_gauge_len_mm"] == 15.0


@pytest.mark.parametrize("method", ["unknown", "ball_magic", "manual_ball_raster", None])
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
    assert coordinates.printed_xy(public.numbers, op["op"]) is None
    prepared = kernel.op_inputs(
        data, setup, op, finishing=set(), complete=set(), tables=public.numbers
    )
    assert prepared["manual_raster"] == printed


@pytest.mark.parametrize("field", ["gauge_dia_mm", "gauge_len_mm"])
def test_unknown_holder_dimensions_withhold_native_envelope(tmp_path, field):
    data, setup, op = raster_bundle(tmp_path)
    data.inventory["holders"]["holder"][field] = "unknown"
    prepared = kernel.op_inputs(data, setup, op, finishing=set(), complete=set())
    assert prepared["refused_fields"]
    assert prepared["reason"]


def test_unmeasured_pair_projection_does_not_use_nominal_oal_fallback(tmp_path):
    data, setup, op = raster_bundle(tmp_path)
    data.inventory["tools"]["em"]["projection_mm"]["holder"] = {
        "value": 25.0,
        "measured": {"status": "assumed"},
    }
    prepared = kernel.op_inputs(data, setup, op, finishing=set(), complete=set())
    assert "projection_mm" not in kernel._engine_op(prepared)
    assert prepared["refused_fields"]
    assert prepared["reason"]


@pytest.mark.parametrize("radius", [0.0, -0.1, "unknown"])
def test_idealized_or_unknown_endmill_corner_cannot_supply_physical_geometry(tmp_path, radius):
    data, setup, op = raster_bundle(tmp_path, kind="endmill")
    data.inventory["tools"]["em"]["nose_radius_mm"] = (
        measured(radius) if isinstance(radius, (int, float)) else radius
    )
    prepared = kernel.op_inputs(data, setup, op, finishing=set(), complete=set())
    native = kernel._engine_op(prepared)
    if isinstance(radius, (int, float)):
        assert native["nose_radius_mm"] == radius
    else:
        assert "nose_radius_mm" not in native
    assert "nose_radius_mm" in prepared["reason"]


@pytest.mark.parametrize("radius", [0.2, 3.0, 3.1])
def test_measured_endmill_radius_reaches_native_shape_validation_unchanged(tmp_path, radius):
    data, setup, op = raster_bundle(tmp_path, kind="endmill", corner_radius=radius)
    prepared = kernel.op_inputs(data, setup, op, finishing=set(), complete=set())
    # The native shape discriminator, not an adapter clamp/default, judges c < R.
    assert kernel._engine_op(prepared)["nose_radius_mm"] == radius


@pytest.mark.parametrize("kind", ["unknown", "face_mill"])
def test_unknown_or_other_cutter_kind_is_not_defaulted_to_flat(tmp_path, kind):
    data, setup, op = raster_bundle(tmp_path, kind=kind, corner_radius=0.2)
    prepared = kernel.op_inputs(data, setup, op, finishing=set(), complete=set())
    assert kernel._engine_op(prepared)["tool_kind"] == kind


@pytest.mark.parametrize("action", ["profile", "rough_profile"])
def test_transient_end_face_raster_keeps_identity_without_legacy_sweep_or_source_claims(
    tmp_path, action
):
    data, setup, op = raster_bundle(tmp_path, kind="endmill", corner_radius=0.2)
    data.plan["process_features"] = {
        "waste_plane": {
            "kind": "end_face",
            "at": [0.0, 0.0, 5.0],
            "axis": [0.0, 0.0, -1.0],
            "cite": {"at": "synthetic waste plane", "axis": "synthetic retained side"},
        }
    }
    op.update(do=action, feature="waste_plane", rough_allowance_mm=0.0)
    public = coordinates.evaluate(data, pre_kernel=True)[0]
    prepared = kernel.op_inputs(
        data, setup, op, finishing=set(), complete=set(), tables=public.numbers
    )
    native = kernel._engine_op(prepared)
    assert native["process_cut"] == {
        "process_feature": "waste_plane",
        "action": action,
        "kind": "end_face",
        "label": "plan.process_features.waste_plane",
        "at_mm": [0.0, 0.0, 5.0],
        "axis": [0.0, 0.0, -1.0],
    }
    assert native["manual_raster"] == trajectory()
    assert native["contour_method"] == "manual_raster"
    assert native["tool_kind"] == "endmill"
    assert native["nose_radius_mm"] == 0.2
    assert native["shank_geometry"] == "enclosing_cylinder"
    assert native["shank_envelope_radius_mm"] == 3.0
    assert "faces" not in native and "workpiece_faces" not in native
    assert "tool_paths" not in native and "checkpoints" not in native


def test_unknown_body_bound_never_defaults_to_cutter_or_shank_diameter(tmp_path):
    data, setup, op = raster_bundle(tmp_path)
    data.inventory["tools"]["em"]["body_envelope_dia_mm"] = "unknown"
    prepared = kernel.op_inputs(data, setup, op, finishing=set(), complete=set())
    native = kernel._engine_op(prepared)
    assert native["radius_mm"] == native["shank_radius_mm"] == 3.0
    assert native["shank_geometry"] == "enclosing_cylinder"
    assert "shank_envelope_radius_mm" not in native
    assert "shank_envelope_radius_mm" in prepared["reason"]
    debt = next(
        entry
        for entry in prepared["measurement_debts"]
        if entry["id"].endswith(".body_envelope_dia")
    )
    assert debt["id"] in prepared["refused_fields"]
    assert "entire noncutting body" in debt["instruction"]
    assert "flute end to tool back" in debt["instruction"]


def test_undersized_measured_body_bound_is_not_enlarged_before_native_refusal(tmp_path):
    data, setup, op = raster_bundle(tmp_path)
    data.inventory["tools"]["em"]["body_envelope_dia_mm"] = measured(5.0)
    prepared = kernel.op_inputs(data, setup, op, finishing=set(), complete=set())
    native = kernel._engine_op(prepared)
    assert native["shank_envelope_radius_mm"] == 2.5
    assert native["shank_envelope_radius_mm"] < native["radius_mm"]
    assert native["shank_envelope_radius_mm"] < native["shank_radius_mm"]
    assert native["shank_geometry"] == "enclosing_cylinder"
