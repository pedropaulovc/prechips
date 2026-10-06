import math

import pytest

from prechips.rules.coordinates import _dome

FEATURE = {"sphere_radius": 4.0}


def _op(apex=4.0, base=0.0, step=1.0):
    return {"op": 60, "z_from": apex, "z_to": base, "contour": {"step_mm": step}}


def test_the_apex_and_base_shift_only_along_the_axis_they_are_tangent_to():
    table = _dome("dome", FEATURE, _op(), radius_mode=False, nose=0.4)
    assert table["tool_nose_compensation_mm"] == 0.4
    apex, base = table["rows"][0], table["rows"][-1]
    # Apex: normal +Z, the face touch-off reads the surface Z; X loses one nose radius.
    assert apex["z_tool_mm"] == pytest.approx(4.0)
    assert apex["x_tool_mm"] == pytest.approx(2 * (0.0 - 0.4))
    # Equator (base at the sphere centre): normal +X, the OD touch-off reads the surface X.
    assert base["x_tool_mm"] == pytest.approx(8.0)
    assert base["z_tool_mm"] == pytest.approx(0.0 - 0.4)


def test_a_mid_point_offsets_by_the_nose_along_its_normal_in_radius_display():
    table = _dome("dome", FEATURE, _op(step=2.0), radius_mode=True, nose=0.4)
    middle = next(r for r in table["rows"] if r["z_mm"] == pytest.approx(2.0))
    radius = math.sqrt(12.0)
    assert middle["x_target_mm"] == pytest.approx(radius)
    assert middle["x_tool_mm"] == pytest.approx(radius + 0.4 * (radius / 4.0 - 1))
    assert middle["z_tool_mm"] == pytest.approx(2.0 + 0.4 * (2.0 / 4.0 - 1))


@pytest.mark.parametrize(
    ("nose", "op", "reason"),
    [
        ("unknown", _op(), "nose radius is unknown"),
        (-0.1, _op(), "nose radius is unknown"),
        (0.4, _op(apex=-4.0, base=0.0), "apex faces the chuck"),
    ],
)
def test_compensation_without_a_nose_or_off_the_touch_off_face_stays_unknown(nose, op, reason):
    table = _dome("dome", FEATURE, op, radius_mode=False, nose=nose)
    assert table["tool_nose_compensation_mm"] == "unknown"
    assert reason in table["tool_nose_compensation_reason"]
    assert all("x_tool_mm" not in row for row in table["rows"])


def test_a_zero_nose_reads_the_surface_itself():
    table = _dome("dome", FEATURE, _op(), radius_mode=False, nose=0.0)
    assert all(
        row["x_tool_mm"] == pytest.approx(row["x_target_mm"])
        and row["z_tool_mm"] == pytest.approx(row["z_mm"])
        for row in table["rows"]
    )
