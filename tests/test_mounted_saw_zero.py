"""Mounted body-side calibration is distinct from ordinary cutter-tip zeroing."""

from copy import deepcopy

import pytest
from test_slitting_saw import mixed_zero_bundle

from prechips.rules import geometry_common
from prechips.rules.zero_recipe import rule
from prechips.rules.zero_recipe.tool_setting import mounted_saw_settings, tool_changes
from prechips.rules.zero_recipe.touch import mounted_saw_axis_recipe


@pytest.mark.parametrize(
    ("side", "offset", "expected"),
    [("minus_z", 0, 11.575), ("plus_z", 0, 8.425), ("minus_z", 0.2, 11.775)],
)
def test_body_side_axis_set_uses_body_half_thickness_not_kerf_or_radius(side, offset, expected):
    values = mounted_saw_axis_recipe(
        {"edge_mm": 10, "paper_mm": 0.05, "blade_side": side},
        {"thickness_mm": 3.05, "kerf_mm": 4.0, "dia_mm": 100, "kerf_offset_mm": offset},
        5,
    )
    assert values["axis_set"] == pytest.approx(expected)
    assert values["check_reading"] == pytest.approx(expected + 5)
    assert values["mirrored_reading"] == pytest.approx(expected - 5)
    if side == "minus_z" and offset == 0:
        assert values["check_reading"] == pytest.approx(16.575)
        assert values["mirrored_reading"] == pytest.approx(6.575)


@pytest.mark.parametrize("field", ["thickness_mm", "kerf_offset_mm"])
def test_kerf_and_radius_cannot_fill_missing_body_facts(field):
    blade = {"thickness_mm": 3.05, "kerf_offset_mm": 0, "kerf_mm": 4, "dia_mm": 100}
    del blade[field]
    assert (
        mounted_saw_axis_recipe(
            {"edge_mm": 10, "paper_mm": 0.05, "blade_side": "minus_z"}, blade, 5
        )["axis_set"]
        == "unknown"
    )


def normalized_zero(monkeypatch, *, selected=0, method="mounted_saw_side", state="stopped"):
    data = mixed_zero_bundle()
    setup = data.plan["setups"][0]
    touch = {
        "kind": "tool",
        "axis": "z",
        "method": method,
        "tool": "tools.blade",
        "holder": "holders.holder",
        "tool_reference": "blade",
        "holder_reference": "holder",
        "face": "deck",
        "edge_mm": 10,
        "paper_mm": 0.05,
        "position": 1,
        "before_ops": [20],
        "mounted_saw": {
            "blade_side": "minus_z",
            "axis_xy_mm": [0, 0],
            "point_mm": [20, 0, 10],
            "spindle_state": state,
        },
    }
    mounted = {
        "model": "finite_disk_v1",
        "blade": {"thickness_mm": 3.05, "kerf_offset_mm": 0},
        "zero": {"touches": [touch], "selected": selected, "reasons": [], "errors": []},
    }
    monkeypatch.setattr(
        geometry_common, "mounted_saw_inputs", lambda *args, **kwargs: deepcopy(mounted)
    )
    setup["zero"]["tool_touches"] = [
        {
            "tool": "blade",
            "holder": "holder",
            "z_face": "deck",
            "edge_mm": 10,
            "paper_mm": 0.05,
            "method": method,
            "before_ops": [20],
            "mounted_saw": deepcopy(touch["mounted_saw"]),
        }
    ]
    data.kernel = {"status": "ok", "ops": {"S1:20": {"saw": {"model": "finite_disk_v1"}}}}
    return data, setup, mounted


@pytest.mark.parametrize("state", ["stopped", "unknown"])
def test_numeric_zero_and_model_marker_never_certify_contact(monkeypatch, state):
    data, setup, _ = normalized_zero(monkeypatch, state=state)
    setting = mounted_saw_settings(data, setup)["20"]
    assert setting["status"] == "unknown"
    assert setting["z_axis_set"] == "unknown"


def test_running_contact_errors_even_without_other_geometry(monkeypatch):
    data, setup, _ = normalized_zero(monkeypatch, state="running")
    assert mounted_saw_settings(data, setup)["20"]["status"] == "error"
    assert rule.evaluate(data)[0].status == "error"


@pytest.mark.parametrize(
    "reason", ["contact overlaps flange", "contact reaches tooth root", "axial approach collides"]
)
def test_native_bad_contact_precedes_missing_setting_facts(monkeypatch, reason):
    data, setup, mounted = normalized_zero(monkeypatch)
    mounted["blade"].pop("thickness_mm")
    data.kernel["ops"]["S1:20"]["saw"]["zero"] = {"status": "error", "reasons": [reason]}
    setting = mounted_saw_settings(data, setup)["20"]
    assert setting["status"] == "error"
    assert reason in setting["reasons"]


@pytest.mark.parametrize("method", ["paper", "measure_then_set"])
def test_ordinary_touch_does_not_transfer_to_mounted_saw(monkeypatch, method):
    data, setup, _ = normalized_zero(monkeypatch, method=method)
    assert mounted_saw_settings(data, setup)["20"]["status"] == "unknown"


def test_reinstalled_or_different_pair_requires_new_matching_touch(monkeypatch):
    data, setup, _ = normalized_zero(monkeypatch, selected="unknown")
    assert mounted_saw_settings(data, setup)["20"]["z_axis_set"] == "unknown"


def test_saw_side_touch_is_not_an_ordinary_tip_setting(monkeypatch):
    data, setup, _ = normalized_zero(monkeypatch)
    # Even naming an ordinary tool does not turn a saw-side touch into its tip pickup.
    touch = {**setup["zero"]["tool_touches"][0], "tool": "centre/1", "before_ops": [10]}
    _, _, _, readings, _ = tool_changes(data, setup, setup["zero"], False, "unknown", [touch])
    assert readings.get("10") is None or readings["10"].get("method") != "mounted_saw_side"


def prove_zero(data, mounted):
    touch = mounted["zero"]["touches"][0]
    contact = touch["mounted_saw"]
    proof = {
        "index": 0,
        "status": "pass",
        "reasons": [],
        **deepcopy(contact),
        "surface_side": "+z",
        "plane_z_mm": 10,
        "plane_normal_z": 1,
        "paper_mm": 0.05,
        "body_thickness_mm": 3.05,
        "kerf_offset_mm": 0,
        "body_face_z_mm": 10.05,
        "cutting_midplane_z_mm": 11.575,
        "contact_radius_mm": 20,
        "exposed_inner_radius_mm": 10,
        "root_radius_mm": 40,
        "approach_start_z_mm": 16.575,
        "approach_end_z_mm": 11.575,
        "collisions": [],
    }
    data.kernel["ops"]["S1:20"]["saw"]["zero"] = {
        "status": "pass",
        "reasons": [],
        "selected": 0,
        "touches": [proof],
    }
    return proof


def test_complete_native_contact_and_approach_clear_a_mounted_tool_touch(monkeypatch):
    data, setup, mounted = normalized_zero(monkeypatch)
    prove_zero(data, mounted)
    setting = mounted_saw_settings(data, setup)["20"]
    assert setting["status"] == "pass"
    assert setting["z_axis_set"] == pytest.approx(11.575)
    finding = rule.evaluate(data)[0]
    assert finding.status == "pass"
    # The ordinary initial Z is retained, and only the mounted tool touch reads 11.575.
    assert finding.numbers["axes"]["z"]["axis_set"] == pytest.approx(10.05)
    assert finding.numbers["tool_touches"][0]["z_axis_set"] == pytest.approx(11.575)


def test_complete_mounted_axis_zero_keeps_positive_and_mirrored_jogs_distinct(monkeypatch):
    data, setup, mounted = normalized_zero(monkeypatch)
    touch = mounted["zero"]["touches"][0]
    touch.update(kind="axis", position=0)
    touch.pop("before_ops")
    setup["ops"] = [setup["ops"][-1]]
    setup["zero"]["z"].update(
        tool="blade",
        holder="holder",
        method="mounted_saw_side",
        mounted_saw=deepcopy(touch["mounted_saw"]),
        check_jog_mm=5,
    )
    setup["zero"]["tool_touches"] = []
    prove_zero(data, mounted)
    finding = rule.evaluate(data)[0]
    assert finding.status == "pass"
    z = finding.numbers["axes"]["z"]
    assert z["axis_set"] == pytest.approx(11.575)
    assert z["check_reading"] == pytest.approx(16.575)
    assert z["mirrored_reading"] == pytest.approx(6.575)


@pytest.mark.parametrize("setter", ["endmill", "other_saw", "other_holder"])
def test_a_passing_native_proof_does_not_override_the_last_z_setter(monkeypatch, setter):
    data, setup, mounted = normalized_zero(monkeypatch)
    prove_zero(data, mounted)
    touch = deepcopy(setup["zero"]["tool_touches"][0])
    if setter == "endmill":
        touch.update(method="paper", tool="centre/1")
        touch.pop("mounted_saw")
    elif setter == "other_saw":
        touch["tool"] = "another-saw"
    else:
        touch["holder"] = "another-arbor"
    setup["zero"]["tool_touches"].append(touch)
    # Deliberately retain the earlier host/native pass: setter tracking is its own gate.
    setting = mounted_saw_settings(data, setup)["20"]
    assert setting["status"] == "pass"
    assert tool_changes(
        data,
        setup,
        setup["zero"],
        False,
        "unknown",
        setup["zero"]["tool_touches"],
        mounted={"20": setting},
    )[2]
    assert rule.evaluate(data)[0].status == "unknown"


def test_fresh_matching_mounted_touch_after_another_setter_remains_usable(monkeypatch):
    data, setup, mounted = normalized_zero(monkeypatch)
    prove_zero(data, mounted)
    setup["zero"]["tool_touches"].insert(
        0,
        {
            "tool": "centre/1",
            "z_face": "deck",
            "edge_mm": 10,
            "paper_mm": 0.05,
            "before_ops": [20],
        },
    )
    setting = mounted_saw_settings(data, setup)["20"]
    assert setting["status"] == "pass"
    assert not tool_changes(
        data,
        setup,
        setup["zero"],
        False,
        "unknown",
        setup["zero"]["tool_touches"],
        mounted={"20": setting},
    )[2]
    assert rule.evaluate(data)[0].status == "pass"


@pytest.mark.parametrize("before_ops", [[999, 20], [999]])
def test_unresolved_mounted_boundary_stays_unknown_with_a_stale_native_pass(
    monkeypatch, before_ops
):
    data, setup, mounted = normalized_zero(monkeypatch)
    prove_zero(data, mounted)
    setup["zero"]["tool_touches"][0]["before_ops"] = before_ops
    mounted["zero"]["touches"][0]["before_ops"] = before_ops
    setting = mounted_saw_settings(data, setup)["20"]
    assert setting["status"] == "unknown"
    assert "mounted-saw touch operation boundary is unresolved" in setting["reasons"]
    assert tool_changes(
        data,
        setup,
        setup["zero"],
        False,
        "unknown",
        setup["zero"]["tool_touches"],
        mounted={"20": {"status": "pass", "selected": 0}},
    )[2]
    assert rule.evaluate(data)[0].status == "unknown"


@pytest.mark.parametrize(
    "field", ["point_mm", "axis_xy_mm", "blade_side", "spindle_state", "body_thickness_mm"]
)
def test_stale_native_touch_proof_cannot_clear_changed_normalized_facts(monkeypatch, field):
    data, setup, mounted = normalized_zero(monkeypatch)
    proof = prove_zero(data, mounted)
    proof[field] = "unknown"
    assert mounted_saw_settings(data, setup)["20"]["status"] != "pass"


def test_native_arithmetic_using_kerf_instead_of_body_is_an_error(monkeypatch):
    data, setup, mounted = normalized_zero(monkeypatch)
    proof = prove_zero(data, mounted)
    proof["cutting_midplane_z_mm"] = 12.05
    assert mounted_saw_settings(data, setup)["20"]["status"] == "error"


def test_known_ordinary_direction_error_precedes_proved_mounted_zero(monkeypatch):
    data, _, mounted = normalized_zero(monkeypatch)
    prove_zero(data, mounted)
    data.plan["dro"]["direction"]["x"] = "left"
    assert rule.evaluate(data)[0].status == "error"


def test_trajectory_dro_rows_reference_spindle_xy_and_cutting_midplane(monkeypatch):
    from prechips.rules import coordinates

    data, _, mounted = normalized_zero(monkeypatch)
    mounted["trajectory"] = {
        "start_mm": [-20, -10, 11.575],
        "moves": [{"to_mm": [20, -10, 11.575], "mode": "cut"}],
    }
    finding = coordinates.evaluate(data)[0]
    entry = next(row for row in finding.numbers["operations"] if row["op"] == 20)
    path = entry["mounted_saw_trajectory"]
    assert path["coordinate_reference"] == "spindle_xy_cutting_midplane_z"
    assert path["start_mm"] == [-20, -10, 11.575]
    assert path["dro_moves"][0]["mode"] == "cut"
    assert path["status"] == "unknown"
    assert finding.status != "pass"


def test_pre_kernel_coordinates_do_not_build_a_recursive_mounted_job(monkeypatch):
    from prechips.rules import coordinates

    data = mixed_zero_bundle()

    def forbidden(*args, **kwargs):
        raise AssertionError("pre-kernel coordinates cannot request another prepared job")

    monkeypatch.setattr(geometry_common, "mounted_saw_inputs", forbidden)
    finding = coordinates.evaluate(data, pre_kernel=True)[0]
    assert not any("mounted_saw_trajectory" in row for row in finding.numbers["operations"])
