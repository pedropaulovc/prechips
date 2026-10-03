"""Face-local cutter clearance and incomplete-normal facts under real FreeCAD."""

import json
import os
import subprocess

import pytest
from test_kernel_geometry import ENGINE, FREECAD, Engine, _op, _setup, _vise, needs_freecad

_AUTHOR = r"""
import sys
import FreeCAD, Part
out = sys.argv[sys.argv.index("--") + 1]
V = FreeCAD.Vector
# Review #2: through-groove along X, width 6, floor z=12, in a 60x40x20 block.
groove = Part.makeBox(60, 40, 20).cut(Part.makeBox(62, 6, 9, V(-1, 17, 12)))
assert groove.isValid() and len(groove.Solids) == 1
groove.exportStep(out + "/groove.step")
Part.makeBox(60, 40, 20).exportStep(out + "/block.step")
Part.makeBox(60, 40, 20).cut(Part.makeBox(31, 42, 11, V(30, -1, 10))).exportStep(out + "/step.step")
"""

_RUNNER = r"""
import importlib.util
import json
import sys
engine_path, source, target, missing = sys.argv[sys.argv.index("--") + 1:]
spec = importlib.util.spec_from_file_location("region_engine", engine_path)
engine = importlib.util.module_from_spec(spec)
spec.loader.exec_module(engine)
if missing == "missing":
    original = engine._face_samples
    def incomplete(face, spacing):
        samples, skipped = original(face, spacing)
        return samples[1:], skipped + 1
    engine._face_samples = incomplete
with open(source, encoding="utf-8") as stream:
    result = engine.run(json.load(stream))
with open(target, "w", encoding="utf-8") as stream:
    json.dump(result, stream)
"""


class RegionEngine(Engine):
    def __init__(self, directory, missing=False):
        super().__init__(directory)
        self.missing = missing

    def raw(self, payload):
        runner = self.directory / "runner.py"
        source, target = self.directory / "in.json", self.directory / "out.json"
        runner.write_text(_RUNNER, encoding="utf-8")
        source.write_text(json.dumps(payload), encoding="utf-8")
        target.unlink(missing_ok=True)
        process = subprocess.run(
            [
                FREECAD,
                str(runner),
                "--",
                os.environ.get("PRECHIPS_TEST_REGION_ENGINE", str(ENGINE)),
                str(source),
                str(target),
                "missing" if self.missing else "complete",
            ],
            capture_output=True,
            text=True,
            errors="replace",
            timeout=600,
        )
        assert target.exists(), process.stdout[-2000:] + process.stderr[-2000:]
        return target.read_bytes()


@pytest.fixture(scope="module")
def region_solids(tmp_path_factory):
    if FREECAD is None:
        pytest.skip("FreeCAD freecadcmd is not installed")
    directory = tmp_path_factory.mktemp("region-solids")
    author = directory / "author.py"
    author.write_text(_AUTHOR, encoding="utf-8")
    process = subprocess.run(
        [FREECAD, str(author), "--", str(directory)],
        capture_output=True,
        text=True,
        errors="replace",
        timeout=300,
    )
    paths = {name: directory / f"{name}.step" for name in ("groove", "block", "step")}
    assert all(path.exists() for path in paths.values()), process.stdout + process.stderr
    return paths


@needs_freecad
def test_cutter_wider_than_claimed_through_groove_hits_opposite_claimed_wall(
    region_solids, tmp_path
):
    engine = RegionEngine(tmp_path)
    step = region_solids["groove"]
    groove = engine.refs(step, (0, 17, 12), (60, 23, 20))
    walls = [
        face["ref"]
        for face in engine.faces(step)
        if face["ref"] in groove and face["bbox_mm"][2] != face["bbox_mm"][5]
    ]
    assert len(groove) == 3 and len(walls) == 2
    op = _op("S1:10", "groove", 5.0, 15.0, 40.0)
    result = engine.run(engine.job(step, {"groove": groove}, [_setup([op], _vise(5, centre=30))]))
    detail = result["ops"]["S1:10"]
    assert detail["corner_radii_mm"] == []
    assert detail["holder_hits"] == 0
    assert detail["tool_hits"] > 0  # D10 cannot fit between walls 6 mm apart.
    assert set(walls).issubset(detail["hit_refs"]["tool"])


@needs_freecad
@pytest.mark.parametrize("radius, blocked", [(5.0, True), (2.5, False)])
def test_through_groove_wall_poses_discriminate_cutter_width(
    region_solids, tmp_path, radius, blocked
):
    engine = RegionEngine(tmp_path)
    step = region_solids["groove"]
    wall = engine.refs(step, (0, 17, 12), (60, 17, 20))
    opposite = engine.refs(step, (0, 23, 12), (60, 23, 20))
    assert len(wall) == len(opposite) == 1
    op = _op("S1:10", "wall", radius, 15.0, 40.0)
    result = engine.run(engine.job(step, {"wall": wall}, [_setup([op], _vise(5, centre=30))]))
    detail = result["ops"]["S1:10"]
    assert detail["holder_hits"] == 0
    if blocked:
        assert detail["tool_hits"] > 0 and opposite[0] in detail["hit_refs"]["tool"]
    else:
        assert detail["tool_hits"] == 0 and detail["hit_refs"]["tool"] == []


@needs_freecad
def test_normal_offset_clears_claimed_own_side_wall(region_solids, tmp_path):
    engine = RegionEngine(tmp_path)
    step = region_solids["step"]
    wall = engine.refs(step, (30, 0, 10), (30, 40, 20))
    assert len(wall) == 1
    op = _op("S1:10", "wall", 3.0, 15.0, 40.0)
    result = engine.run(engine.job(step, {"wall": wall}, [_setup([op], _vise(5, centre=30))]))
    detail = result["ops"]["S1:10"]
    assert detail["tool_hits"] == 0 and detail["obstacles"]["tool"] == []


@needs_freecad
def test_missing_normal_makes_clearance_and_reach_unknown_naming_affected_face(
    region_solids, tmp_path
):
    engine = RegionEngine(tmp_path, missing=True)
    step = region_solids["block"]
    top = engine.refs(step, (0, 0, 20), (60, 40, 20))
    assert len(top) == 1
    op = _op("S1:10", "top", 3.0, 15.0, 40.0)
    result = engine.run(engine.job(step, {"top": top}, [_setup([op], _vise(5, centre=30))]))
    detail = result["ops"]["S1:10"]
    for key in ("sample_count", "tool_hits", "holder_hits", "reach_depth_mm", "holder_wall_hits"):
        assert detail[key] == "unknown"
        assert top[0] in detail["reasons"][key]
    assert detail["min_hits"] == {"tool": 0, "holder": 0}


@needs_freecad
def test_missing_normal_keeps_observed_collision_as_certain_lower_bound(region_solids, tmp_path):
    engine = RegionEngine(tmp_path, missing=True)
    step = region_solids["groove"]
    wall = engine.refs(step, (0, 17, 12), (60, 17, 20))
    assert len(wall) == 1
    op = _op("S1:10", "wall", 5.0, 15.0, 40.0)
    result = engine.run(engine.job(step, {"wall": wall}, [_setup([op], _vise(5, centre=30))]))
    detail = result["ops"]["S1:10"]
    assert detail["tool_hits"] == "unknown"
    assert detail["min_hits"]["tool"] > 0
    assert detail["reach_depth_mm"] == "unknown"
    assert wall[0] in detail["reasons"]["tool_hits"]
