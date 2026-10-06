"""Native planar sawing, conservative target protection and routed retained stock."""

import subprocess
from copy import deepcopy

import pytest
from test_kernel_geometry import IDENTITY, _op
from test_kernel_stock import PackagedEngine, _bundle

from prechips import kernel

BOX = {
    "shape": "box",
    "origin_mm": [0.0, 0.0, 0.0],
    "axis": [1.0, 0.0, 0.0],
    "section_axis": [0.0, 1.0, 0.0],
    "length_mm": 10.0,
    "section_mm": [10.0, 10.0],
}
_AUTHOR = r"""
import sys
import Part
from FreeCAD import Vector as V
out = sys.argv[sys.argv.index("--") + 1]
Part.makeBox(6, 6, 6, V(2, 2, 2)).exportStep(out + "/target.step")
Part.makeBox(2, 2, 6, V(0, 0, 1)).exportStep(out + "/fragment-target.step")
"""


@pytest.fixture(scope="module")
def saw_target(tmp_path_factory, freecad_kernel):
    directory = tmp_path_factory.mktemp("saw-solids")
    script = directory / "author.py"
    script.write_text(_AUTHOR, encoding="utf-8")
    process = subprocess.run(
        [freecad_kernel, str(script), "--", str(directory)],
        capture_output=True,
        text=True,
        errors="replace",
        timeout=300,
    )
    step = directory / "target.step"
    assert step.exists(), process.stdout[-2000:] + process.stderr[-2000:]
    return step


@pytest.fixture
def saw_engine(tmp_path, freecad_kernel, kernel_cache):
    return PackagedEngine(tmp_path, freecad_kernel)


def _saw(axis="y", value=8.5, keep="below", kerf=1.0, action="saw_cut", subject="S1:10"):
    return {
        "subject": subject,
        "do": action,
        "cut_plane": {"axis": axis, "value": value, "keep": keep},
        "kerf_mm": kerf,
    }


def _setup(op=None, frame=None, machine="bandsaw", sid="S1", hold=None):
    return {
        "id": sid,
        "frame": deepcopy(IDENTITY if frame is None else frame),
        "machine_kind": machine,
        "hold": {"kind": "unknown", "reason": "holding is undeclared"} if hold is None else hold,
        "ops": [] if op is None else [op],
    }


def _run(engine, target, op, **setup):
    return engine.run(engine.job(target, setups=[_setup(op, **setup), _setup(sid="S2")], stock=BOX))


@pytest.mark.parametrize(
    "axis, keep, machine, action",
    [
        ("x", "below", "mill", "saw_cut"),
        ("x", "above", "bench", "cut_off"),
        ("y", "below", "bandsaw", "cut_off"),
        ("y", "above", "mill", "saw_cut"),
        ("z", "below", "bench", "saw_cut"),
        ("z", "above", "bandsaw", "cut_off"),
    ],
)
def test_axis_and_retained_side_include_half_kerf_and_route_stock(
    saw_engine, saw_target, axis, keep, machine, action
):
    value, boundary = (8.5, 8.0) if keep == "below" else (1.5, 2.0)
    result = _run(saw_engine, saw_target, _saw(axis, value, keep, action=action), machine=machine)
    assert result["status"] == "ok", result
    detail = result["ops"]["S1:10"]
    assert "saw_error" not in detail and "saw_reason" not in detail, detail
    assert detail["claimed_indices"] == []
    assert detail["retained_boundary_mm"] == boundary
    assert detail["kerf_volume_mm3"] == pytest.approx(100.0)
    assert detail["offcut_volume_mm3"] == pytest.approx(100.0)
    assert detail["removed_volume_mm3"] == pytest.approx(200.0)
    assert detail["stock_volume_before_mm3"] == pytest.approx(1000.0)
    assert detail["stock_volume_after_mm3"] == pytest.approx(800.0)
    expected = [0.0, 0.0, 0.0, 10.0, 10.0, 10.0]
    expected["xyz".index(axis) + (3 if keep == "below" else 0)] = boundary
    assert result["setups"]["S2"]["stock_bbox_mm"] == expected
    assert result["setups"]["S2"]["stock_volume_mm3"] == pytest.approx(800.0)
    assert "tool_hits" not in detail and "holder_hits" not in detail


@pytest.mark.parametrize("value", [8.0, 8.4999, 1.5])
def test_blade_and_discarded_offcut_cannot_remove_finished_target(saw_engine, saw_target, value):
    result = _run(saw_engine, saw_target, _saw(value=value))
    detail = result["ops"]["S1:10"]
    assert "finished target" in detail["saw_error"]
    assert "saw_reason" not in detail
    assert "stock_bbox_mm" not in result["setups"]["S2"]
    assert "S1:10" in result["setups"]["S2"]["stock_reason"]


def test_translated_rotated_setup_returns_retained_solid_in_model_axes(saw_engine, saw_target):
    frame = {"origin": [10, 0, 0], "x": [0, 1, 0], "y": [-1, 0, 0], "z": [0, 0, 1]}
    result = _run(saw_engine, saw_target, _saw("y", 1.5, "above"), frame=frame)
    detail = result["ops"]["S1:10"]
    assert "saw_error" not in detail and "saw_reason" not in detail, detail
    assert detail["retained_boundary_mm"] == 2.0
    assert result["setups"]["S1"]["stock_bbox_mm"] == [0, 0, 0, 10, 10, 10]
    assert result["setups"]["S2"]["stock_bbox_mm"] == [0, 0, 0, 8, 10, 10]


def test_zero_blade_plane_is_not_missing_in_a_translated_frame(saw_engine, saw_target):
    frame = {**IDENTITY, "origin": [0, 9, 0]}
    result = _run(saw_engine, saw_target, _saw(value=0.0), frame=frame)
    detail = result["ops"]["S1:10"]
    assert "saw_error" not in detail and "saw_reason" not in detail, detail
    assert detail["cut_plane"]["value"] == 0.0
    assert detail["retained_boundary_mm"] == -0.5
    assert result["setups"]["S2"]["stock_bbox_mm"] == [0, 0, 0, 10, 8.5, 10]
    assert result["setups"]["S2"]["stock_volume_mm3"] == pytest.approx(850.0)


@pytest.mark.parametrize(
    "kerf, plane, missing",
    [
        ("unknown", {"axis": "y", "value": 8.5, "keep": "below"}, "kerf"),
        (None, {"axis": "y", "value": 8.5, "keep": "below"}, "kerf"),
        (1.0, "unknown", "cut_plane"),
        (1.0, {"axis": "y", "value": "unknown", "keep": "below"}, "cut_plane"),
        (1.0, {"axis": "unknown", "value": 8.5, "keep": "below"}, "cut_plane"),
        (1.0, {"axis": "y", "value": 8.5, "keep": "unknown"}, "cut_plane"),
    ],
)
def test_missing_saw_inputs_leave_downstream_stock_unknown(
    saw_engine, saw_target, kerf, plane, missing
):
    op = _saw(kerf=kerf)
    op["cut_plane"] = plane
    result = _run(saw_engine, saw_target, op)
    detail = result["ops"]["S1:10"]
    assert missing in detail["saw_reason"]
    assert "saw_error" not in detail
    assert detail["stock_volume_before_mm3"] == pytest.approx(1000.0)
    assert "stock_bbox_mm" not in result["setups"]["S2"]


@pytest.mark.parametrize(
    "op, error",
    [
        (_saw(kerf=0.0), "kerf"),
        (_saw(kerf=-1.0), "kerf"),
        (_saw(value=12.0), "off-stock"),
        (_saw(value=10.5), "off-stock"),
        (_saw(value=-2.0), "off-stock"),
        (_saw(value=0.5), "no retained stock"),
        (_saw(value=9.5, keep="above"), "no retained stock"),
    ],
)
def test_physical_invalidity_does_not_pass_through_stock(saw_engine, saw_target, op, error):
    result = _run(saw_engine, saw_target, deepcopy(op))
    detail = result["ops"]["S1:10"]
    assert error in detail["saw_error"]
    assert "stock_bbox_mm" not in result["setups"]["S2"]


def test_lathe_never_dispatches_saw_as_turning(saw_engine, saw_target):
    op = _saw()
    op.update(approach="turning", faces=["unknown"])
    result = _run(saw_engine, saw_target, op, machine="lathe")
    detail = result["ops"]["S1:10"]
    assert "lathe" in detail["saw_error"]
    assert "approach" not in detail
    assert "stock_bbox_mm" not in result["setups"]["S2"]


def test_multiple_saws_use_successive_stock_and_keep_fixture_render(saw_engine, saw_target):
    fixture = {
        "kind": "solids",
        "fixture_kind": "custom_fixture",
        "pose": {"origin_mm": [0, 0, 0], "x": [1, 0, 0], "z": [0, 0, 1]},
        "solids": [{"name": "bed", "shape": "box", "at_mm": [0, 0, -2], "size_mm": [10, 10, 2]}],
    }
    first = _setup(_saw("y"), hold=fixture)
    first["ops"].append(_saw("x", subject="S1:20"))
    third = _setup(_saw("z", subject="S2:10"), sid="S2", machine="mill")
    result = saw_engine.run(
        saw_engine.job(saw_target, setups=[first, third, _setup(sid="S3")], stock=BOX)
    )
    assert result["ops"]["S1:20"]["stock_volume_before_mm3"] == pytest.approx(800.0)
    assert result["ops"]["S1:20"]["stock_volume_after_mm3"] == pytest.approx(640.0)
    assert result["ops"]["S2:10"]["stock_volume_after_mm3"] == pytest.approx(512.0)
    assert result["setups"]["S3"]["stock_bbox_mm"] == [0, 0, 0, 8, 8, 8]
    scene = result["setups"]["S1"]["render_scene"]
    assert scene["components"] == [{"name": "bed", "role": "fixture", "exact": True}]
    assert scene["debts"] == []
    assert result["setups"]["S1"]["fixture_rendered"] is True
    assert result["setups"]["S1"]["stock_volume_mm3"] == pytest.approx(1000.0)
    assert [cut["subject"] for cut in scene["saw_cuts"]] == ["S1:10", "S1:20"]
    assert [cut["stock_volume_after_mm3"] for cut in scene["saw_cuts"]] == [800.0, 640.0]


def test_later_mill_removal_uses_native_sawn_stock(saw_engine, saw_target):
    top = saw_engine.refs(saw_target, [2, 2, 8], [8, 8, 8])
    assert len(top) == 1
    mill = _op("S2:10", "top", 0.5, 20.0, 30.0, holder_radius=0.5)
    mill.update(
        to_z=8.0,
        stock_removal_bounds={"x": [2, 8], "y": [2, 8], "z": [8, 10]},
    )
    result = saw_engine.run(
        saw_engine.job(
            saw_target,
            features={"top": top},
            setups=[_setup(_saw()), _setup(mill, sid="S2", machine="mill"), _setup(sid="S3")],
            stock=BOX,
        )
    )
    assert result["setups"]["S2"]["stock_volume_mm3"] == pytest.approx(800.0)
    assert result["setups"]["S3"]["stock_volume_mm3"] == pytest.approx(728.0)
    assert result["setups"]["S3"]["stock_bbox_mm"] == [0, 0, 0, 10, 8, 10]


@pytest.mark.parametrize("loose_width", [2.0, 0.000025])
def test_saw_rejects_retained_fragmentation_of_one_connected_stock_piece(
    saw_engine, saw_target, loose_width
):
    target = saw_target.parent / "fragment-target.step"
    left = {**BOX, "length_mm": 2.0, "section_mm": [2.0, 10.0]}
    right = {
        **left,
        "origin_mm": [8.0, 0.0, 0.0],
        "length_mm": loose_width,
    }
    bridge = {**BOX, "origin_mm": [0.0, 0.0, 8.0], "section_mm": [2.0, 2.0]}
    stock = {"components": {"left": left, "right": right, "bridge": bridge}}
    first = _setup(_saw("z"))
    first["stock_in"] = ["stock.left", "stock.right", "stock.bridge"]
    result = saw_engine.run(saw_engine.job(target, setups=[first, _setup(sid="S2")], stock=stock))
    detail = result["ops"]["S1:10"]
    assert "saw_error" in detail and "saw_reason" not in detail, detail
    assert detail["kerf_volume_mm3"] == pytest.approx(20.0)
    assert detail["offcut_volume_mm3"] == pytest.approx(20.0)
    assert detail["removed_volume_mm3"] == pytest.approx(40.0)
    assert detail["stock_volume_after_mm3"] == pytest.approx(32.0 + 16.0 * loose_width)
    assert detail["stock_volume_before_mm3"] == pytest.approx(72.0 + 16.0 * loose_width)
    assert "stock_bbox_mm" not in result["setups"]["S2"]


@pytest.mark.parametrize("discarded_component", [False, True])
def test_saw_retains_preexisting_disconnected_stock_components(
    saw_engine, saw_target, discarded_component
):
    target = saw_target.parent / "fragment-target.step"
    left = {**BOX, "length_mm": 2.0, "section_mm": [2.0, 10.0]}
    right = {**left, "origin_mm": [8.0, 0.0, 0.0]}
    stock = {"components": {"left": left, "right": right}}
    first = _setup(_saw("z"))
    first["stock_in"] = ["stock.left", "stock.right"]
    if discarded_component:
        stock["components"]["discard"] = {
            **left,
            "origin_mm": [12.0, 0.0, 9.0],
            "section_mm": [2.0, 1.0],
        }
        first["stock_in"].append("stock.discard")
    result = saw_engine.run(saw_engine.job(target, setups=[first, _setup(sid="S2")], stock=stock))
    detail = result["ops"]["S1:10"]
    assert "saw_error" not in detail and "saw_reason" not in detail, detail
    assert detail["stock_volume_before_mm3"] == pytest.approx(84.0 if discarded_component else 80.0)
    assert detail["stock_volume_after_mm3"] == pytest.approx(64.0)
    assert detail["kerf_volume_mm3"] == pytest.approx(8.0)
    assert detail["offcut_volume_mm3"] == pytest.approx(12.0 if discarded_component else 8.0)
    assert result["setups"]["S2"]["stock_volume_mm3"] == pytest.approx(64.0)
    assert result["setups"]["S2"]["stock_bbox_mm"] == [0, 0, 0, 10, 2, 8]


@pytest.mark.parametrize("missing", ["machine", "frame", "stock"])
def test_unknown_scene_inputs_cannot_prove_retained_saw_stock(saw_engine, saw_target, missing):
    first = _setup(_saw())
    stock = deepcopy(BOX)
    if missing == "machine":
        first["machine_kind"] = "unknown"
    elif missing == "frame":
        first["frame"] = "unknown"
    else:
        stock = {"reason": "stock placement is unknown"}
    result = saw_engine.run(
        saw_engine.job(saw_target, setups=[first, _setup(sid="S2")], stock=stock)
    )
    detail = result["ops"]["S1:10"]
    assert missing in detail["saw_reason"]
    assert "saw_error" not in detail and "tool_hits" not in detail
    assert "stock_bbox_mm" not in result["setups"]["S2"]


def _host_bundle(tmp_path, target):
    bundle = _bundle(tmp_path)
    bundle.paths["step"] = target
    bundle.features["step_sha256"] = kernel.hashlib.sha256(target.read_bytes()).hexdigest()
    bundle.features["features"] = {}
    bundle.plan["stock"] = {key: value for key, value in BOX.items() if key != "shape"}
    bundle.inventory["tools"] = {
        "blade": {"kind": "bandsaw", "kerf_in": {"value": "1/16", "verify": False}}
    }
    bundle.inventory["machines"] = {"bench": {"kind": "bench"}}
    setup = bundle.plan["setups"][0]
    setup["machine"] = "bench"
    setup["ops"] = [
        {
            "op": 10,
            "do": "cut_off",
            "tool": "blade",
            "cut_plane": {"axis": "y", "value": 8.79375, "keep": "below"},
        }
    ]
    bundle.plan["setups"].append({**deepcopy(setup), "id": "S2", "stock_in": "S1", "ops": []})
    return bundle


def test_host_serialization_accepts_inch_kerf_without_spindle_holder(
    tmp_path, saw_target, freecad_kernel, kernel_cache
):
    bundle = _host_bundle(tmp_path, saw_target)
    kernel.run_geometry(bundle)
    detail = bundle.kernel["ops"]["S1:10"]
    assert "saw_error" not in detail and "saw_reason" not in detail, detail
    assert detail["kerf_mm"] == pytest.approx(1.5875)
    assert detail["cut_plane"] == {"axis": "y", "value": 8.79375, "keep": "below"}
    assert detail["retained_boundary_mm"] == pytest.approx(8.0)
    assert bundle.kernel["setups"]["S2"]["stock_volume_mm3"] == pytest.approx(800.0)


@pytest.mark.parametrize("verify", [True, "unknown"])
def test_fact_local_kerf_debt_cannot_be_promoted_by_item_or_source(
    tmp_path, saw_target, freecad_kernel, kernel_cache, verify
):
    bundle = _host_bundle(tmp_path, saw_target)
    blade = bundle.inventory["tools"]["blade"]
    blade.update(verify=False, source={"verify": False})
    blade["kerf_in"]["verify"] = verify
    kernel.run_geometry(bundle)
    detail = bundle.kernel["ops"]["S1:10"]
    assert "kerf" in detail["saw_reason"]
    assert detail["kerf_mm"] == "unknown"
    assert "stock_bbox_mm" not in bundle.kernel["setups"]["S2"]


def test_plan_plane_uses_feature_units(tmp_path, saw_target, freecad_kernel, kernel_cache):
    bundle = _host_bundle(tmp_path, saw_target)
    bundle.features["units"] = "in"
    bundle.features["frames"]["A"]["origin"] = [0, 8.0 / 25.4, 0]
    bundle.plan["setups"][0]["ops"][0]["cut_plane"]["value"] = 0.79375 / 25.4
    bundle.features["frames"]["B"] = deepcopy(IDENTITY)
    bundle.plan["setups"][1]["frame"] = "B"
    kernel.run_geometry(bundle)
    detail = bundle.kernel["ops"]["S1:10"]
    assert detail["cut_plane"]["value"] == pytest.approx(0.79375)
    assert detail["retained_boundary_mm"] == pytest.approx(0.0)
    assert bundle.kernel["setups"]["S2"]["stock_bbox_mm"] == [0, 0, 0, 10, 8, 10]
