"""A band-admitted nonnominal turn is held, not machined or certified.

Only its selected nominal skin loses collision certainty. These authored solids
exercise the ordinary source guard and the real native stopping-material helper.
"""

import hashlib
import math
import subprocess

import pytest
from test_fixture_solids import _chuck
from test_kernel_geometry import Engine
from test_kernel_retained_outputs import _probe
from test_turning_geometry import _bar, _lathe, _turn

_REASON = (
    "in-band nonnominal cylindrical target 6.34 mm is unsupported "
    "by nominal-source turning geometry; stock, attainment and downstream "
    "clearance remain unproved"
)
_AUTHOR = r"""
import sys
import FreeCAD, Part
V = FreeCAD.Vector
out = sys.argv[sys.argv.index("--") + 1]
plain = Part.makeCylinder(3.175, 40)
boss = plain.fuse(Part.makeCylinder(4, 4, V(0, 0, 18))).removeSplitter()
for name, shape in (("plain", plain), ("boss", boss)):
    assert shape.isValid() and len(shape.Solids) == 1
    shape.exportStep(out + "/" + name + ".step")
"""


@pytest.fixture(scope="module")
def target_solids(tmp_path_factory, freecad_kernel):
    directory = tmp_path_factory.mktemp("turn-target-hold")
    script = directory / "author.py"
    script.write_text(_AUTHOR, encoding="utf-8")
    process = subprocess.run(
        [freecad_kernel, str(script), "--", str(directory)],
        capture_output=True, text=True, errors="replace", timeout=300,
    )
    paths = {name: directory / f"{name}.step" for name in ("plain", "boss")}
    assert all(path.exists() for path in paths.values()), process.stdout + process.stderr
    return paths


@pytest.fixture
def held_turn(tmp_path, freecad_kernel, target_solids):
    engine = Engine(tmp_path, freecad_kernel)

    def run(*, shape="plain", diameter=6.34, alias=False, window=(40.0, -0.6), hold=None):
        step = target_solids[shape]
        before = step.read_bytes()
        spans = [(0, 40)] if shape == "plain" else [(0, 18), (22, 40)]
        journal = [
            ref for low, high in spans
            for ref in engine.refs(
                step, (-3.175, -3.175, low), (3.175, 3.175, high), kind="Cylinder"
            )
        ]
        assert len(journal) == len(spans)
        features = {"journal": journal}
        bands = {"journal": [6.32968, 6.35]}
        if alias:
            features["alias"] = list(journal)
            bands["alias"] = [6.345, 6.35]
        op = _turn("S1:10", "journal", to_dia_mm=diameter,
                   z_from=window[0], z_to=window[1])
        first = _lathe([op])
        if hold is not None:
            first["hold"] = hold
        job = engine.job(step, features, [first, _lathe([], "S2")], stock=_bar(dia=8.0))
        job["dia_bands"] = bands
        result = engine.run(job)
        assert result["status"] != "error", result.get("reason")
        assert step.read_bytes() == before
        assert job["step_sha256"] == hashlib.sha256(before).hexdigest()
        return result

    return run


def _unaccepted(result):
    detail = result["ops"]["S1:10"]
    target = detail["turn_target"]
    assert target["status"] == target["attained_indices"] == "unknown"
    first, later = result["setups"]["S1"], result["setups"]["S2"]
    assert first["stock_volume_mm3"] == pytest.approx(math.pi * 16 * 40, abs=0.001)
    assert first["stock_out_reason"]
    assert "stock_out_volume_mm3" not in first
    assert later["stock_reason"]
    assert "stock_volume_mm3" not in later
    return detail


def test_admitted_target_is_precisely_unsupported_not_a_nominal_skin_collision(held_turn):
    detail = _unaccepted(held_turn())
    assert detail["unsupported_reason"] == _REASON
    assert detail["turn_target"]["reason"] == _REASON
    assert detail["turn_target"]["diameter_mm"] == 6.34
    assert detail["turn_target"]["z_mm"] == [-0.6, 40.0]
    assert detail["min_hits"]["tool"] == "unknown"
    assert detail["tool_hits"] == "unknown"
    assert _REASON in detail["reasons"]["tool_hits"]


@pytest.mark.parametrize("kwargs", [{"diameter": 6.32}, {"alias": True}])
def test_out_of_band_or_incompatible_owner_retains_physical_material_error(held_turn, kwargs):
    result = held_turn(**kwargs)
    detail = _unaccepted(result)
    reason = result["setups"]["S1"]["stock_out_reason"]
    assert "protected finished material" in reason
    assert "in-band nonnominal" not in reason
    assert "unsupported_reason" not in detail
    assert isinstance(detail["min_hits"]["tool"], int)
    assert detail["min_hits"]["tool"] > 0


def test_unselected_in_window_source_boss_is_still_a_certain_collision(held_turn):
    result = held_turn(shape="boss")
    detail = _unaccepted(result)
    assert detail["unsupported_reason"] == _REASON
    assert "protected finished material" in result["setups"]["S1"]["stock_out_reason"]
    assert isinstance(detail["min_hits"]["tool"], int)
    assert detail["min_hits"]["tool"] > 0


def test_upper_start_inside_raw_keeps_out_of_window_endpoint_collision(held_turn):
    detail = _unaccepted(held_turn(window=(30.0, 10.0)))
    assert detail["unsupported_reason"] == _REASON
    assert isinstance(detail["min_hits"]["tool"], int)
    assert detail["min_hits"]["tool"] > 0
    start = next(pose for pose in detail["window_poses"] if pose["end"] == "z_from")
    assert "part" in start["meets"]


def test_measured_chuck_hits_remain_certain_for_an_unsupported_target(held_turn):
    detail = _unaccepted(held_turn(hold=_chuck(face_z=10.0)))
    assert detail["unsupported_reason"] == _REASON
    assert isinstance(detail["min_hits"]["tool"], int)
    assert detail["min_hits"]["tool"] > 0
    assert any(set(pose["meets"]) - {"part"} for pose in detail["window_poses"])


_NATIVE = r"""
import importlib.util, os
import FreeCAD, Part
spec = importlib.util.spec_from_file_location("held_target_engine", os.environ["RETAINED_ENGINE"])
engine = importlib.util.module_from_spec(spec)
spec.loader.exec_module(engine)
V = FreeCAD.Vector
source = Part.makeCylinder(3.175, 40)
raw = Part.makeCylinder(4, 40)
owner = engine._Job.__new__(engine._Job)
owner.job = {"dia_bands": {"journal": [6.32968, 6.35]}}
indices = [i for i, face in enumerate(source.Faces) if isinstance(face.Surface, Part.Cylinder)]
owner.face_features = {i: ["journal"] for i in indices}
runner = engine._Setup.__new__(engine._Setup)
runner.owner = owner
runner.faces = list(source.Faces)
runner.finished_face_count = len(runner.faces)
runner.box = engine._bbox(raw)
runner.protected = source.copy()
runner.turn_target_holds = {}
op = {"do": "finish_turn", "approach": "turning", "to_dia_mm": 6.34,
      "z_from": 30.0, "z_to": 10.0}
runner.stopped_cut = id(op)
runner.stopped_plan = None
runner.cuts = {id(op): (raw, raw, None)}
protected_before = runner.protected.Volume
source_before = source.Volume
hold = runner._turn_target_hold(op, indices)
assert hold is not None
certain = runner._stopping_tool_material(op)
core = Part.makeCylinder(3.17, 20, V(0, 0, 10))
skin = source.cut(Part.makeCylinder(3.17, 40)).common(Part.makeCylinder(4, 20, V(0, 0, 10)))
outside = raw.cut(Part.makeCylinder(4, 20, V(0, 0, 10)))
out = {
    "reason": hold["reason"], "indices": hold["indices"], "expected_indices": indices,
    "skin_mm3": hold["skin"].Volume, "expected_skin_mm3": skin.Volume,
    "core_missing_mm3": core.cut(certain).Volume,
    "skin_certain_mm3": skin.common(certain).Volume,
    "outside_missing_mm3": outside.cut(certain).Volume,
    "source_before_mm3": source_before, "source_after_mm3": source.Volume,
    "protected_before_mm3": protected_before, "protected_after_mm3": runner.protected.Volume,
    "raw_after_mm3": runner.cuts[id(op)][1].Volume,
    "cached": runner._turn_target_hold(op, indices) is hold,
}
"""


def test_native_stopping_material_excludes_only_the_exact_skin(tmp_path, freecad_kernel):
    facts = _probe(_NATIVE, tmp_path, freecad_kernel)
    assert facts["reason"] == _REASON
    assert facts["indices"] == facts["expected_indices"]
    assert facts["cached"] is True
    assert facts["skin_mm3"] == pytest.approx(math.pi * (3.175**2 - 3.17**2) * 20, abs=1e-6)
    assert facts["skin_mm3"] == pytest.approx(facts["expected_skin_mm3"], abs=1e-6)
    for key in ("core_missing_mm3", "skin_certain_mm3", "outside_missing_mm3"):
        assert facts[key] == pytest.approx(0.0, abs=1e-6)
    for prefix in ("source", "protected"):
        assert facts[f"{prefix}_before_mm3"] == pytest.approx(math.pi * 3.175**2 * 40, abs=1e-6)
        assert facts[f"{prefix}_after_mm3"] == facts[f"{prefix}_before_mm3"]
    assert facts["raw_after_mm3"] == pytest.approx(math.pi * 16 * 40, abs=1e-6)
