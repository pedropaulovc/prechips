"""Absolute hole commands do not manufacture independent breakthrough evidence."""

from types import SimpleNamespace

import pytest
from test_envelope_m5 import measured

from prechips.rules import tip_endpoints
from prechips.rules._envelope import _z_extent
from prechips.rules.zero_recipe import native, tool_setting

# Independent N20 oracle: D11.2, included angle118 degrees, near .2 removed.
POINT = 3.3648194665543376
FAR = -72.2344
DRILL_MIN = -76.09921946655435
BORE_MIN = -72.7344


def bundle(action="drill", command=-76.100, *, explicit=True, units="mm", through=True):
    scale = 25.4 if units == "in" else 1.0
    operation = {
        "op": 20,
        "do": action,
        "feature": "hole",
        "tool": "tool",
        "exit_mm": 0.5,
        "depth_mm": 5.0,
    }
    if explicit:
        operation["to_z"] = command / scale if isinstance(command, (int, float)) else command
    setup = {
        "id": "S4",
        "machine": "mill",
        "frame": "model",
        "stock_in": "stock",
        "stock_state": {
            "top_z": 0.2 / scale,
            "bottom_z": FAR / scale,
            "entry_z": {"hole": 0.0},
            "local_thickness": {"hole": 72.2344 / scale},
        },
        "ops": [operation],
    }
    features = {
        "units": units,
        "frames": {
            "model": {
                "origin": [0, 0, 0],
                "x": [1, 0, 0],
                "y": [0, 1, 0],
                "z": [0, 0, 1],
            }
        },
        "features": {
            "hole": {
                "kind": "hole",
                "frame": "model",
                "at": [0, 0, 0],
                "dia": 11.2 / scale,
                "thru": through,
                "depth": [0.0, 100.0 / scale],
                "requirements": [],
            }
        },
    }
    return SimpleNamespace(
        plan={"setups": [setup]},
        features=features,
        feature_definitions=features["features"],
        inventory={
            "machines": {"mill": {"kind": "mill", "resolution_mm": measured(0.005)}},
            "tools": {
                "tool": {
                    "kind": "drill" if action in {"drill", "spot"} else action,
                    "dia_mm": measured(11.2),
                    "point_angle": measured(118.0),
                    "lead_mm": measured(1.25),
                    "flute_len_mm": measured(94.0),
                }
            },
        },
        kernel={},
        policy={},
    )


def endpoint(data):
    (finding,) = tip_endpoints.evaluate(data)
    (row,) = finding.numbers["endpoints"]
    return finding, row


@pytest.mark.parametrize(
    "action,command,required,point",
    [("drill", -76.100, DRILL_MIN, POINT), ("bore", -72.735, BORE_MIN, 0.0)],
)
def test_n20_command_and_exact_requirement_remain_distinct(action, command, required, point):
    finding, row = endpoint(bundle(action, command))
    assert row["endpoint_source"] == "to_z"
    assert row["tip_z"] == row["dro_tip_z"] == command
    assert row["entry_z"] == 0.0
    assert row["local_thickness"] == 72.2344
    assert row["exit_face"] == FAR
    assert row["point_mm"] == pytest.approx(point)
    assert row["exit_mm"] == 0.5
    assert row["required_tip_z"] == pytest.approx(required)
    assert row["dro_exit_mm"] == pytest.approx(FAR - point - command)
    assert row["breakthrough_status"] == "pass"
    # Numeric design inputs never qualify the actual after-stock.
    assert row["actual_stock_status"] == finding.status == "unknown"


@pytest.mark.parametrize("action,command", [("drill", -76.100), ("bore", -72.735)])
def test_conflicting_thickness_is_not_reconstructed_from_command(action, command):
    data = bundle(action, command)
    data.plan["setups"][0]["stock_state"]["local_thickness"]["hole"] = 72.4344
    finding, row = endpoint(data)
    assert row["tip_z"] == row["dro_tip_z"] == command
    assert row["local_thickness"] == 72.4344
    assert row["exit_face"] == -72.4344
    assert row["breakthrough_status"] == finding.status == "error"
    assert row["actual_stock_status"] == "unknown"


@pytest.mark.parametrize("through", [True, False])
@pytest.mark.parametrize("action", ["drill", "bore", "ream", "counterbore", "spot", "tap"])
def test_explicit_unknown_never_falls_back_to_depth_or_thickness(action, through):
    finding, row = endpoint(bundle(action, "unknown", through=through))
    assert row["endpoint_source"] == "to_z"
    assert row["tip_z"] == row["dro_tip_z"] == finding.status == "unknown"


@pytest.mark.parametrize("missing", ["entry", "thickness", "point", "exit"])
def test_known_command_keeps_missing_proof_unknown(missing):
    data = bundle()
    state = data.plan["setups"][0]["stock_state"]
    if missing == "entry":
        state["entry_z"]["hole"] = "unknown"
    elif missing == "thickness":
        state["local_thickness"]["hole"] = "unknown"
    elif missing == "point":
        data.inventory["tools"]["tool"]["point_angle"] = "unknown"
    else:
        data.plan["setups"][0]["ops"][0]["exit_mm"] = "unknown"
    finding, row = endpoint(data)
    assert row["tip_z"] == row["dro_tip_z"] == -76.100
    assert row["required_tip_z"] == row["breakthrough_status"] == finding.status == "unknown"


@pytest.mark.parametrize("command", [-75.0, DRILL_MIN])
def test_short_raw_or_rounded_command_is_an_error_without_deepening(command):
    finding, row = endpoint(bundle(command=command))
    assert row["tip_z"] == command
    assert row["dro_tip_z"] >= command
    assert row["dro_exit_mm"] < 0.5
    assert row["breakthrough_status"] == finding.status == "error"


def test_negative_exit_intent_is_error_but_does_not_hide_command():
    data = bundle()
    data.plan["setups"][0]["ops"][0]["exit_mm"] = -0.5
    finding, row = endpoint(data)
    assert finding.status == "error"
    assert row["exit_mm"] == -0.5
    assert row["tip_z"] == row["dro_tip_z"] == -76.100


@pytest.mark.parametrize("action,expected", [("drill", DRILL_MIN), ("bore", BORE_MIN)])
def test_no_explicit_endpoint_preserves_legacy_derivation(action, expected):
    finding, row = endpoint(bundle(action, explicit=False))
    assert row["tip_z"] == pytest.approx(expected)
    assert row["dro_tip_z"] == (-76.095 if action == "drill" else -72.730)
    assert "endpoint_source" not in row
    assert "required_tip_z" not in row
    assert "actual_stock_status" not in row
    assert finding.status == "pass"


def test_inch_coordinates_keep_point_and_exit_in_machine_mm():
    finding, row = endpoint(bundle(units="in"))
    assert row["tip_z"] == pytest.approx(-76.100 / 25.4)
    assert row["dro_tip_z"] * 25.4 == pytest.approx(-76.100, abs=2e-8)
    assert row["exit_face"] == pytest.approx(FAR / 25.4)
    assert row["required_tip_z"] == pytest.approx(DRILL_MIN / 25.4)
    assert row["point_mm"] == pytest.approx(POINT)
    assert row["dro_exit_mm"] == pytest.approx(0.50078053344566, abs=2e-8)
    assert row["breakthrough_status"] == "pass"
    assert finding.status == "unknown"


@pytest.mark.parametrize("setting", [0.055, "unknown"])
def test_carried_touch_moves_evidence_not_absolute_command(monkeypatch, setting):
    monkeypatch.setattr(
        tool_setting,
        "carried_z_reading",
        lambda *args: {
            "native_edge_mm": 0.0,
            "edge_mm": 0.005,
            "paper_offset_mm": 0.05,
            "z_axis_set": setting,
            "setting_residual_mm": 0.0,
        },
    )
    finding, row = endpoint(bundle())
    assert row["tip_z"] == row["dro_tip_z"] == -76.100
    assert row["entry_z"] == 0.0
    assert row["exit_face"] == FAR
    assert row["physical_entry_z"] == pytest.approx(0.005)
    assert row["physical_exit_bound_z"] == pytest.approx(-72.2294)
    if setting == "unknown":
        assert row["dro_exit_mm"] == row["breakthrough_status"] == "unknown"
    else:
        assert row["dro_entry_z"] == 0.005
        assert row["dro_exit_mm"] == pytest.approx(0.50578053344566)
    assert finding.status == "unknown"


@pytest.mark.parametrize(
    "action,lead",
    [
        ("spot", 0.0),
        ("tap", 0.0),
        ("drill", POINT),
        ("ream", 1.25),
        ("bore", 0.0),
        ("counterbore", 0.0),
    ],
)
@pytest.mark.parametrize("units", ["mm", "in"])
def test_blind_commands_override_conflicting_depth_with_unit_safe_operative_depth(
    action, lead, units
):
    data = bundle(action, -10.0, through=False, units=units)
    # An unused authored recipe must not replace the absolute command or fail its guard.
    data.plan["setups"][0]["ops"][0]["depth_mm"] = 200.0
    finding, row = endpoint(data)
    scale = 25.4 if units == "in" else 1.0
    assert row["tip_z"] == pytest.approx(-10.0 / scale)
    assert row["dro_tip_z"] * scale == pytest.approx(-10.0, abs=2e-8)
    assert row["depth_mm"] == pytest.approx(10.0 - lead)
    assert row["dro_depth_mm"] == pytest.approx(10.0 - lead, abs=2e-8)
    assert finding.status == "pass"


def test_explicit_blind_depth_still_enforces_independent_feature_limit():
    data = bundle(command=-101.0, through=False)
    finding, row = endpoint(data)
    assert row["tip_z"] == row["dro_tip_z"] == -101.0
    assert row["depth_limit_mm"] == 100.0
    assert finding.status == "error"


def test_existing_native_stock_debt_cannot_be_repaired_by_a_command():
    data = bundle()
    data.kernel = {
        "status": "ok",
        "setups": {"S4": {}},
        "ops": {"S4:20": {"stock_reason": "prior facing after-stock is unproved"}},
    }
    finding, row = endpoint(data)
    assert row["tip_z"] == -76.100
    assert row["required_tip_z"] == pytest.approx(DRILL_MIN)
    assert row["breakthrough_status"] == "pass"
    assert row["actual_stock_status"] == finding.status == "unknown"


@pytest.mark.parametrize("command,expected", [(-2.0, 6.6), (0.0, None), ("unknown", None)])
def test_combined_spot_erosion_uses_commanded_tip_travel(command, expected):
    data = bundle("spot", command)
    data.feature_definitions["hole"]["axis"] = [0, 0, -1]
    data.inventory["tools"]["tool"].update(
        kind="center_drill_set",
        pilot_len_mm=measured(1.0),
        shank_mm=measured(20.0),
        angle_deg=measured(90.0),
    )
    setup = data.plan["setups"][0]
    setup["ops"][0]["depth_mm"] = 100.0
    footprint = native._axial_cut_footprint(data, setup, setup["ops"][0])
    if expected is None:
        assert footprint is None
    else:
        assert footprint[1] == pytest.approx(expected)


@pytest.mark.parametrize("through,command,complete", [(False, -10.0, True), (True, -76.100, False)])
def test_safety_extent_uses_command_without_inventing_stock_proof(through, command, complete):
    data = bundle(command=command, through=through)
    setup = data.plan["setups"][0]
    operation = setup["ops"][0]
    operation.update(depth_mm=200.0, approach_mm=5.0)
    _, row = endpoint(data)
    _, before, _ = next(tip_endpoints.stock_states(data, setup))
    span, known = _z_extent(
        operation,
        before,
        {},
        row,
        ("tools", "tool", data.inventory["tools"]["tool"]),
        {"verified": True, "value": 11.2},
        {},
        [],
        [],
        [],
        "S4:20",
    )
    assert span == [command, 5.2]
    assert known is complete


def test_facing_advances_entry_without_moving_the_authored_command():
    data = bundle()
    setup = data.plan["setups"][0]
    setup["stock_state"]["entry_z"]["hole"] = 0.2
    setup["stock_state"]["top_feature"] = "near"
    data.feature_definitions["near"] = {
        "kind": "face",
        "frame": "model",
        "bounds": {"x": [-10.0, 10.0], "y": [-10.0, 10.0], "z": [0.0, 0.2]},
        "requirements": [],
    }
    setup["ops"].insert(0, {"op": 5, "do": "face", "feature": "near", "to_z": 0.0, "tool": "tool"})
    findings = tip_endpoints.evaluate(data)
    finding = next(item for item in findings if item.subject == "hole")
    (row,) = finding.numbers["endpoints"]
    assert setup["stock_state"]["top_z"] == 0.2
    assert row["entry_z"] == 0.0
    assert row["exit_face"] == FAR
    assert row["required_tip_z"] == pytest.approx(DRILL_MIN)
    assert row["tip_z"] == row["dro_tip_z"] == -76.100
    assert row["actual_stock_status"] == finding.status == "unknown"


def test_negative_depth_intent_is_error_without_replacing_command():
    data = bundle(command=-10.0, through=False)
    data.plan["setups"][0]["ops"][0]["depth_mm"] = -5.0
    finding, row = endpoint(data)
    assert row["authored_depth_mm"] == -5.0
    assert row["tip_z"] == row["dro_tip_z"] == -10.0
    assert row["depth_mm"] == pytest.approx(10.0 - POINT)
    assert finding.status == "error"
