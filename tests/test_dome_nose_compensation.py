import math

import pytest

from prechips.rules.coordinates import _dome

FEATURE = {"sphere_radius": 4.0}
# A right-hand 93-degree tool with a 55-degree insert: its nose spans normals -32..93 deg.
AR = {"hand": "right", "entering_angle_deg": 93.0, "insert_angle_deg": 55.0}


def _op(apex=4.0, base=0.0, step=1.0):
    return {"op": 60, "z_from": apex, "z_to": base, "contour": {"step_mm": step}}


def test_the_apex_and_base_shift_only_along_the_axis_they_are_tangent_to():
    table = _dome("dome", FEATURE, _op(), radius_mode=False, nose=0.4, edges=AR)
    assert table["tool_nose_compensation_mm"] == 0.4
    apex, base = table["rows"][0], table["rows"][-1]
    # Apex: normal +Z, the face touch-off reads the surface Z; X loses one nose radius.
    assert apex["z_tool_mm"] == pytest.approx(4.0)
    assert apex["x_tool_mm"] == pytest.approx(2 * (0.0 - 0.4))
    # Equator (base at the sphere centre): normal +X, the OD touch-off reads the surface X.
    assert base["x_tool_mm"] == pytest.approx(8.0)
    assert base["z_tool_mm"] == pytest.approx(0.0 - 0.4)


def test_a_mid_point_offsets_by_the_nose_along_its_normal_in_radius_display():
    table = _dome("dome", FEATURE, _op(step=2.0), radius_mode=True, nose=0.4, edges=AR)
    middle = next(r for r in table["rows"] if r["z_mm"] == pytest.approx(2.0))
    radius = math.sqrt(12.0)
    assert middle["x_target_mm"] == pytest.approx(radius)
    assert middle["x_tool_mm"] == pytest.approx(radius + 0.4 * (radius / 4.0 - 1))
    assert middle["z_tool_mm"] == pytest.approx(2.0 + 0.4 * (2.0 / 4.0 - 1))


@pytest.mark.parametrize(
    ("entering", "compensated"),
    # The apex normal is 90 deg: the major edge bounds the nose arc at the entering angle.
    [(90.0, True), (89.9, False)],
)
def test_the_apex_needs_the_nose_arc_to_reach_the_axial_normal(entering, compensated):
    edges = {**AR, "entering_angle_deg": entering}
    table = _dome("dome", FEATURE, _op(), radius_mode=False, nose=0.4, edges=edges)
    assert (table["tool_nose_compensation_mm"] == 0.4) is compensated
    if not compensated:
        assert "Z 4" in table["tool_nose_compensation_reason"]
        assert all("x_tool_mm" not in row for row in table["rows"])


def test_a_dome_below_its_equator_needs_the_trailing_edge_clear():
    # Rows below the sphere centre face the chuck (normal below +X); a 93/80 insert's
    # trailing edge bounds its nose at -7 deg, short of the -14.5 deg at Z -1.
    deep = {"op": 60, "z_from": 4.0, "z_to": -1.0, "contour": {"step_mm": 1.0}}
    narrow = {**AR, "insert_angle_deg": 80.0}
    assert _dome("dome", FEATURE, deep, False, 0.4, AR)["tool_nose_compensation_mm"] == 0.4
    table = _dome("dome", FEATURE, deep, False, 0.4, narrow)
    assert table["tool_nose_compensation_mm"] == "unknown"
    assert "Z -1 lie outside" in table["tool_nose_compensation_reason"]


@pytest.mark.parametrize(
    ("nose", "op", "edges", "reason"),
    [
        ("unknown", _op(), AR, "nose radius is unknown"),
        (-0.1, _op(), AR, "nose radius is unknown"),
        (0.4, _op(apex=-4.0, base=0.0), AR, "apex faces the chuck"),
        (0.4, _op(), None, "right-hand tool"),
        (0.4, _op(), {**AR, "hand": "left"}, "right-hand tool"),
        (0.4, _op(), {**AR, "entering_angle_deg": "unknown"}, "angle is unknown"),
        (0.4, _op(), {**AR, "insert_angle_deg": 90.0}, "do not form an insert"),
    ],
)
def test_compensation_without_a_confirmed_nose_contact_stays_unknown(nose, op, edges, reason):
    table = _dome("dome", FEATURE, op, radius_mode=False, nose=nose, edges=edges)
    assert table["tool_nose_compensation_mm"] == "unknown"
    assert reason in table["tool_nose_compensation_reason"]
    assert all("x_tool_mm" not in row for row in table["rows"])


def test_a_zero_nose_reads_the_surface_itself():
    table = _dome("dome", FEATURE, _op(), radius_mode=False, nose=0.0, edges=AR)
    assert all(
        row["x_tool_mm"] == pytest.approx(row["x_target_mm"])
        and row["z_tool_mm"] == pytest.approx(row["z_mm"])
        for row in table["rows"]
    )
