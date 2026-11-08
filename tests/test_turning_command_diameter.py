"""Explicit bounded turning diameters change real eccentric stock and commanded poses."""

import ast
import math
import subprocess

import pytest
from test_kernel_geometry import ENGINE, Engine
from test_turning_geometry import _lathe, _turn

_RADIUS = 41.91 / 2
_LENGTH = 80.0
_RAW = {
    "shape": "box",
    "origin_mm": [-55.0, -30.0, 0.0],
    "axis": [0.0, 0.0, 1.0],
    "section_axis": [1.0, 0.0, 0.0],
    "length_mm": _LENGTH,
    "section_mm": [100.0, 80.0],
}
_AUTHOR = r"""
import sys
import Part
path = sys.argv[sys.argv.index("--") + 1]
Part.makeCylinder(41.91 / 2, 80).exportStep(path)
"""


@pytest.fixture(scope="module")
def commanded_journal(tmp_path_factory, freecad_kernel):
    directory = tmp_path_factory.mktemp("turn-command-diameter")
    script, step = directory / "author.py", directory / "journal.step"
    script.write_text(_AUTHOR, encoding="utf-8")
    process = subprocess.run(
        [freecad_kernel, str(script), "--", str(step)],
        capture_output=True,
        text=True,
        errors="replace",
        timeout=300,
    )
    assert step.exists(), process.stdout[-2000:] + process.stderr[-2000:]
    return step


@pytest.fixture
def commanded_engine(tmp_path, freecad_kernel, commanded_journal):
    engine = Engine(tmp_path, freecad_kernel)
    refs = engine.refs(
        commanded_journal,
        (-_RADIUS, -_RADIUS, 0),
        (_RADIUS, _RADIUS, _LENGTH),
        kind="Cylinder",
    )
    assert len(refs) == 1
    return engine, commanded_journal, {"journal": refs}


def _command(subject, diameter, low=-0.6, high=_LENGTH, **extra):
    # R0.4 plus 0.2 mm real overtravel puts the terminal blend below the kept end.
    return _turn(
        subject,
        "journal",
        **{
            "do": "rough_turn",
            "to_dia_mm": diameter,
            "z_from": high,
            "z_to": low,
            **extra,
        },
    )


def test_intermediate_46_mm_stock_is_real_and_consumed_by_the_next_setup(commanded_engine):
    engine, step, features = commanded_engine
    rough = _command("S1:10", 46.0)
    finish = _command("S2:10", 41.91, do="finish_turn")
    result = engine.run(
        engine.job(
            step,
            features,
            [_lathe([rough]), _lathe([finish], "S2"), _lathe([], "S3")],
            stock=_RAW,
        )
    )
    assert result["status"] != "error", result.get("reason")
    setups, ops = result["setups"], result["ops"]
    # The real supply is the eccentric rectangular blank, not its swing envelope.
    assert setups["S1"]["stock_volume_mm3"] == pytest.approx(100 * 80 * _LENGTH)
    assert setups["S1"]["stock_bbox_mm"] == pytest.approx([-55, -30, 0, 45, 50, 80])
    assert setups["S2"]["stock_volume_mm3"] == pytest.approx(math.pi * 23**2 * _LENGTH)
    assert setups["S2"]["stock_bbox_mm"] == pytest.approx([-23, -23, 0, 23, 23, 80], abs=1e-3)
    assert setups["S3"]["stock_volume_mm3"] == pytest.approx(math.pi * _RADIUS**2 * _LENGTH)
    assert ops["S2:10"]["reach_depth_mm"] == pytest.approx(23 - _RADIUS, abs=1e-3)
    rough_facts, finish_facts = ops["S1:10"], ops["S2:10"]
    assert rough_facts["turn_target"]["status"] == "accepted"
    assert rough_facts["turn_target"]["attained_indices"] == []
    assert finish_facts["turn_target"]["attained_indices"] == finish_facts["claimed_indices"]
    assert rough_facts["reach_depth_basis"] == "entry_stock_radial_upper_bound"
    for facts, diameter in ((rough_facts, 46.0), (finish_facts, 41.91)):
        assert {pose["dia_mm"] for pose in facts["window_poses"]} == {diameter}
        assert facts["min_hits"]["tool"] == facts["min_hits"]["holder"] == 0


@pytest.mark.parametrize("ends", [(20.0, 60.0), (60.0, 20.0)])
def test_explicit_cylinder_removes_only_the_commanded_axial_window(commanded_engine, ends):
    engine, step, features = commanded_engine
    op = _command("S1:10", 46.0, z_from=ends[0], z_to=ends[1])
    result = engine.run(
        engine.job(step, features, [_lathe([op]), _lathe([], "S2")], stock=_RAW)
    )
    after = result["setups"]["S2"]
    assert "stock_reason" not in after, after.get("stock_reason")
    nose, radius = 0.4, 23.0
    blend_excess = math.pi * (
        (2 * radius * nose + nose**2) * nose
        + 2 * nose**3 / 3
        - math.pi * (radius + nose) * nose**2 / 2
    )
    expected = 100 * 80 * 40 + math.pi * radius**2 * 40 + blend_excess
    assert after["stock_volume_mm3"] == pytest.approx(expected)
    facts = result["ops"]["S1:10"]
    assert facts["turn_target"]["z_mm"] == [20.0, 60.0]
    assert facts["turn_target"]["attained_indices"] == []
    assert {pose["dia_mm"] for pose in facts["window_poses"]} == {46.0}
    assert facts["nose_z_mm"][0] >= 19.0
    assert facts["nose_z_mm"][1] <= 61.0


def test_explicit_undersize_is_refused_not_clipped_back_to_the_nominal_part(commanded_engine):
    engine, step, features = commanded_engine
    op = _command("S1:10", 41.8)
    result = engine.run(
        engine.job(step, features, [_lathe([op]), _lathe([], "S2")], stock=_RAW)
    )
    after = result["setups"]["S2"]
    assert "protected finished material" in after["stock_reason"]
    assert "stock_volume_mm3" not in after
    facts = result["ops"]["S1:10"]
    assert facts["turn_target"]["status"] == "unknown"
    assert facts["turn_target"]["attained_indices"] == "unknown"
    assert facts["min_hits"]["tool"] > 0


def test_explicit_final_diameter_over_a_partial_face_does_not_attain_the_whole_face(
    commanded_engine,
):
    engine, step, features = commanded_engine
    op = _command("S1:10", 41.91, 20.0, 60.0, do="finish_turn")
    result = engine.run(engine.job(step, features, [_lathe([op])], stock=_RAW))
    target = result["ops"]["S1:10"]["turn_target"]
    assert target["status"] == "accepted"
    assert target["attained_indices"] == []


@pytest.mark.parametrize("window", [(-0.6, 80.0), (20.0, 60.0)])
def test_legacy_bounded_profile_has_whole_face_attainment_only_for_the_full_window(
    commanded_engine, window
):
    engine, step, features = commanded_engine
    op = _turn("S1:10", "journal", z_from=window[1], z_to=window[0])
    result = engine.run(engine.job(step, features, [_lathe([op])], stock=_RAW))
    facts = result["ops"]["S1:10"]
    evidence = facts["turn_window"]
    assert evidence["status"] == "accepted"
    assert evidence["z_mm"] == list(window)
    expected = facts["claimed_indices"] if window == (-0.6, 80.0) else []
    assert evidence["attained_indices"] == expected


@pytest.fixture(scope="module")
def native_turn_command():
    tree = ast.parse(ENGINE.read_text(encoding="utf-8"))
    names = {"_turn_command", "_number"}
    functions = [
        node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef) and node.name in names
    ]
    assert {node.name for node in functions} == names
    for node in functions:
        node.decorator_list = []
    namespace = {"math": math, "PLANE_TOL": 1e-6}
    exec(compile(ast.Module(body=functions, type_ignores=[]), str(ENGINE), "exec"), namespace)
    return namespace["_turn_command"]


def test_native_explicit_target_is_one_shared_positive_finite_cylinder(native_turn_command):
    target, reason = native_turn_command(_command("S1:10", 46.0, 60.0, 20.0))
    assert target == (23.0, 20.0, 60.0)
    assert reason is None


@pytest.mark.parametrize(
    "change",
    [
        {"to_dia_mm": "unknown"},
        {"to_dia_mm": float("nan")},
        {"to_dia_mm": float("inf")},
        {"to_dia_mm": True},
        {"to_dia_mm": 0.0},
        {"to_dia_mm": -46.0},
        {"z_from": "unknown"},
        {"z_to": "unknown"},
        {"z_from": 0.0, "z_to": 0.0},
        {"corners": 2},
        {"do": "groove"},
    ],
)
def test_native_refuses_unsupported_explicit_target_instead_of_ignoring_it(
    native_turn_command, change
):
    target, reason = native_turn_command(_command("S1:10", 46.0, **change))
    assert target is None
    assert isinstance(reason, str) and reason


def test_native_preserves_host_final_target_refusal(native_turn_command):
    target, reason = native_turn_command(
        _command("S1:10", "unknown", to_dia_reason="final target outside source diameter band")
    )
    assert target is None
    assert reason == "final target outside source diameter band"


def test_facing_diameter_keeps_its_existing_separate_semantics(native_turn_command):
    assert native_turn_command(_command("S1:10", 0.0, to_z=0.0)) == (None, None)


def test_leading_stop_retains_real_blend_without_an_extra_out_of_travel_pose(commanded_engine):
    engine, step, features = commanded_engine
    stock = {**_RAW, "origin_mm": [-55.0, -30.0, -20.0], "length_mm": 100.0}
    op = _command("S1:10", 41.91, 0.0, 80.0, do="finish_turn")
    result = engine.run(
        engine.job(step, features, [_lathe([op]), _lathe([], "S2")], stock=stock)
    )
    facts = result["ops"]["S1:10"]
    target = facts["turn_target"]
    assert target["z_mm"] == [0.0, 80.0]
    assert target["centre_z_mm"] == pytest.approx([0.4, 80.4])
    assert target["contact_z_mm"] == pytest.approx([0.4, 80.0])
    assert target["attained_indices"] == []
    assert facts["nose_z_mm"][0] == pytest.approx(0.0, abs=1e-6)
    assert facts["min_hits"]["tool"] == facts["min_hits"]["holder"] == 0
    nose, radius = 0.4, _RADIUS
    blend_excess = math.pi * (
        (2 * radius * nose + nose**2) * nose
        + 2 * nose**3 / 3
        - math.pi * (radius + nose) * nose**2 / 2
    )
    expected = 100 * 80 * 20 + math.pi * radius**2 * 80 + blend_excess
    assert result["setups"]["S2"]["stock_volume_mm3"] == pytest.approx(expected)
