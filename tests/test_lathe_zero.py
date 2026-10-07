"""Lathe zero recipes: a measured trial cut and per-tool touches are complete recipes."""

from types import SimpleNamespace

import pytest

from prechips.rules.zero_recipe import evaluate


def lathe(radius_mode=False, x=None, touches=None, inventory=None):
    x = {
        "feature": "spindle_axis",
        "edge_mm": 0.0,
        "from": "+x",
        "method": "trial_cut_measure",
        "tool": "turner",
        "gauge": "mic",
        "check_jog_mm": 10.0,
        **(x or {}),
    }
    zero = {
        "x": {key: value for key, value in x.items() if value is not None},
        "z": {
            "face": "shoulder",
            "edge_mm": 0.0,
            "from": "+z",
            "method": "face_then_set",
            "tool": "turner",
            "paper_mm": 0.0,
            "check_jog_mm": 10.0,
            "retouch_after": [],
        },
        "tool_touches": touches if touches is not None else [],
    }
    data = SimpleNamespace(
        plan={
            "dro": {
                "controller": "el400",
                "mode": "abs",
                "radius_mode": radius_mode,
                "direction": {"x": "away_from_spindle_axis", "z": "toward_exposed_end"},
            },
            "setups": [{"id": "S1", "machine": "lathe", "frame": "L", "zero": zero, "ops": []}],
        },
        features={"frames": {"L": {"binding": "nominal"}}, "features": {}},
        inventory={
            "machines": {"lathe": {"kind": "lathe"}},
            "tools": {"turner": {"kind": "insert_holder"}, "parter": {"kind": "parting_blade"}},
            "gauges": {"mic": {"kind": "micrometer"}, **(inventory or {})},
        },
    )
    data.feature_definitions = data.features["features"]
    return data


def row(bundle):
    return evaluate(bundle)[0]


# Its X on the X zero's trial-cut land, no cut since, touched without paper.
TOUCH = {
    "tool": "parter",
    "gauge": "mic",
    "x_face": "x_zero",
    "x_paper_mm": 0.0,
    "z_face": "shoulder",
    "edge_mm": 0.0,
    "paper_mm": 0.0,
}


@pytest.mark.parametrize(
    "radius_mode,axis_set,check,mirror",
    [(False, "measured D", "D +20", "D -20"), (True, "measured D/2", "D/2 +10", "D/2 -10")],
)
def test_measured_trial_cut_with_gauge_and_jog_is_a_complete_recipe(
    radius_mode, axis_set, check, mirror
):
    finding = row(lathe(radius_mode, touches=[TOUCH]))
    x = finding.numbers["axes"]["x"]
    assert finding.status == "pass"
    assert (x["axis_set"], x["check_reading"], x["mirrored_reading"]) == (axis_set, check, mirror)
    touch = finding.numbers["tool_touches"][0]
    assert touch["x_axis_set"] == axis_set and touch["z_axis_set"] == 0.0


@pytest.mark.parametrize(
    "x",
    [
        {"gauge": None},
        {"gauge": "unknown"},
        {"gauge": "missing-gauge"},
        {"gauge": "flagged"},
        {"check_jog_mm": None},
        {"check_jog_mm": "unknown"},
    ],
)
def test_trial_cut_without_a_ready_gauge_or_jog_stays_unknown(x):
    bundle = lathe(x=x, inventory={"flagged": {"kind": "micrometer", "verify": True}})
    finding = row(bundle)
    assert finding.status == "unknown"
    assert finding.numbers["axes"]["x"]["axis_set"] == "unknown"


def test_trial_cut_needs_a_known_display_mode():
    bundle = lathe()
    bundle.plan["dro"]["radius_mode"] = "unknown"
    assert row(bundle).numbers["axes"]["x"]["axis_set"] == "unknown"


@pytest.mark.parametrize(
    "change",
    [
        {"gauge": "unknown"},
        {"tool": "missing-tool"},
        {"edge_mm": "unknown"},
        {"paper_mm": "unknown"},
    ],
)
def test_a_tool_touch_needs_tool_gauge_edge_and_paper(change):
    finding = row(lathe(touches=[{**TOUCH, **change}]))
    assert finding.status == "unknown"


def test_diameter_display_sets_the_gauge_diameter_not_its_radius():
    # +x touch on a known 6.35 mm gauge pin at the spindle axis (physical X = its radius).
    bundle = lathe(
        x={"method": "indicated_touch", "tool": "pin", "gauge": None, "from": "+x"},
        inventory={},
    )
    bundle.inventory["tools"]["pin"] = {"kind": "gauge_pin", "dia_mm": 6.35}
    x = row(bundle).numbers["axes"]["x"]
    assert x["axis_set"] == pytest.approx(6.35)
    assert x["check_reading"] == pytest.approx(26.35)
    assert x["mirrored_reading"] == pytest.approx(-13.65)


TRANSFER = {"from": "S0", "indicate": "shoulder", "gauge": "mic", "runout_limit_mm": 0.02}


@pytest.mark.parametrize(
    ("transfer", "status"),
    [
        (TRANSFER, "pass"),
        ({**TRANSFER, "keep_clamped": False}, "pass"),
        ({**TRANSFER, "keep_clamped": True, "recovery": "index back and re-clock"}, "pass"),
        # Kept clamped with no recovery: what to do with a sweep over the limit is unknown.
        ({**TRANSFER, "keep_clamped": True}, "unknown"),
        ({**TRANSFER, "keep_clamped": True, "recovery": " "}, "unknown"),
        ({**TRANSFER, "keep_clamped": True, "recovery": "unknown"}, "unknown"),
    ],
)
def test_a_transfer_kept_clamped_needs_its_recovery(transfer, status):
    bundle = lathe(touches=[TOUCH])
    bundle.plan["setups"][0]["zero"]["transfer"] = transfer
    finding = row(bundle)
    assert finding.status == status
    assert ("transfer.recovery" in finding.sentence) == (status == "unknown")
