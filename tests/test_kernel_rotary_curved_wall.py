"""Rotary floor samples beside a curved wall whose floor edge crosses a seam of the floor.

A cylindrical floor exported as two half-cylinder patches is one floor: a sample on the
seam stands tangent to the wall at its true nearest floor-edge point, whichever patch
carries that point, and a sample beyond one cutter radius of the wall keeps its axis.
Engine tests run ``freecad_job.py`` on solids authored here; the pose case also records
each floor sample's axis offset beside the engine's JSON.
"""

import json
import math
import subprocess

import pytest
from test_kernel_geometry import ENGINE, Engine, _op, _setup
from test_kernel_rotary import _head

_AUTHOR = r"""
import sys
import FreeCAD, Part
out = sys.argv[sys.argv.index("--") + 1]
V = FreeCAD.Vector
X = V(1, 0, 0)
tail = Part.makeCylinder(8, 15, V(-15, 0, 0), X)
# The R10 body x 0..60 as two half-cylinder patches of one surface, seamed at y = 0.
half = Part.makeCylinder(10, 60, V(0, 0, 0), X, 180)
other = half.copy()
other.rotate(V(0, 0, 0), X, 180)
# A round R4 boss (top z 13) centred 3 mm off the top seam: its floor edge crosses the
# seam, and a seam sample's nearest point on that edge lies on the y > 0 patch.
boss = Part.makeCylinder(4, 6, V(30, 3, 7), V(0, 0, 1))
shape = tail.fuse(half.fuse(other)).fuse(boss)
assert shape.isValid() and len(shape.Solids) == 1
shape.exportStep(out + "/seamed.step")
"""

_RUNNER = r"""
import importlib.util
import json
import sys
engine_path, source, target = sys.argv[sys.argv.index("--") + 1:]
spec = importlib.util.spec_from_file_location("seam_engine", engine_path)
engine = importlib.util.module_from_spec(spec)
spec.loader.exec_module(engine)
offsets = []
original = engine._Setup._rotary_floor_offset
def recorded(self, index, point, phi, presented, radius):
    offset = original(self, index, point, phi, presented, radius)
    offsets.append(
        {
            "face": self.owner.labels[index],
            "point": [point.x, point.y, point.z],
            "phi": phi,
            "offset": list(offset),
        }
    )
    return offset
engine._Setup._rotary_floor_offset = recorded
with open(source, encoding="utf-8") as stream:
    result = engine.run(json.load(stream))
result["floor_offsets"] = offsets
with open(target, "w", encoding="utf-8") as stream:
    json.dump(result, stream)
"""

RADIUS = 3.0
# The boss axis (x, y) and radius; each body patch's bounding box.
BOSS = (30.0, 3.0, 4.0)
HALVES = (((0, -10, -10), (60, 0, 10)), ((0, 0, -10), (60, 10, 10)))


class RecordingEngine(Engine):
    """The engine with each rotary floor sample's axis offset added to its JSON."""

    def raw(self, payload):
        runner = self.directory / "runner.py"
        source, target = self.directory / "in.json", self.directory / "out.json"
        runner.write_text(_RUNNER, encoding="utf-8")
        source.write_text(json.dumps(payload), encoding="utf-8")
        target.unlink(missing_ok=True)
        process = subprocess.run(
            [self.executable, str(runner), "--", str(ENGINE), str(source), str(target)],
            capture_output=True,
            text=True,
            errors="replace",
            timeout=600,
        )
        assert target.exists(), process.stdout[-2000:] + process.stderr[-2000:]
        return target.read_bytes()


@pytest.fixture(scope="module")
def parts(tmp_path_factory, freecad_kernel):
    directory = tmp_path_factory.mktemp("rotary-seam")
    script = directory / "author.py"
    script.write_text(_AUTHOR, encoding="utf-8")
    process = subprocess.run(
        [freecad_kernel, str(script), "--", str(directory)],
        capture_output=True,
        text=True,
        errors="replace",
        timeout=300,
    )
    paths = {path.stem: path for path in directory.glob("*.step")}
    assert len(paths) == 1, process.stdout[-2000:] + process.stderr[-2000:]
    return paths


@pytest.fixture
def engine(tmp_path, freecad_kernel):
    return Engine(tmp_path, freecad_kernel)


def _halves(engine, step):
    halves = [engine.refs(step, *box, kind="Cylinder") for box in HALVES]
    assert [len(refs) for refs in halves] == [1, 1], halves
    return [refs[0] for refs in halves]


def _job(engine, step, body):
    op = {**_op("S1:10", "body", RADIUS, 10.0, 30.0), "approach": "rotary"}
    return engine.job(step, {"body": body}, [_setup([op], _head())])


def _edge_distance(point):
    """Distance from ``point`` to the boss's floor edge on the upper half of the R10 body."""
    x, y, z = point
    centre_x, centre_y, radius = BOSS
    best = math.inf
    for step in range(36000):
        angle = math.radians(step / 100)
        edge_x = centre_x + radius * math.cos(angle)
        edge_y = centre_y + radius * math.sin(angle)
        edge_z = math.sqrt(100.0 - edge_y**2)
        best = min(best, math.dist((x, y, z), (edge_x, edge_y, edge_z)))
    return best


def test_seam_patch_floor_clears_a_wall_whose_nearest_edge_is_on_the_other_patch(engine, parts):
    # The y < 0 patch carries only the seam end of the boss's floor edge; its seam samples
    # beside the boss must still stand tangent to the edge's nearest point on the y > 0
    # patch rather than keep their axes inside the boss.
    step = parts["seamed"]
    lower, _ = _halves(engine, step)
    result = engine.run(_job(engine, step, [lower]))
    assert result["status"] == "ok", result
    op = result["ops"]["S1:10"]
    assert op["claim_errors"] == [] and op["sample_count"] > 0
    assert op["tool_hits"] == 0 and op["obstacles"]["tool"] == [], op


def test_seam_samples_take_one_axis_from_either_patch_tangent_within_the_radius(
    parts, tmp_path, freecad_kernel
):
    engine = RecordingEngine(tmp_path, freecad_kernel)
    step = parts["seamed"]
    halves = _halves(engine, step)
    result = engine.run(_job(engine, step, halves))
    assert result["status"] == "ok", result
    seam = {}
    for call in result["floor_offsets"]:
        x, y, z = call["point"]
        if abs(y) <= 1e-6 and z > 0:
            # The top seam is already presented: offsets are in the part frame.
            assert abs(call["phi"]) <= 1e-6, call
            seam.setdefault(round(x, 6), []).append(call)
    within, beyond = [], []
    for x, calls in sorted(seam.items()):
        # The same physical point is sampled on both patches and gets one offset.
        assert {call["face"] for call in calls} == set(halves), calls
        dx, dy = calls[0]["offset"]
        for call in calls[1:]:
            assert math.dist(call["offset"], (dx, dy)) <= 1e-6, calls
        distance = _edge_distance(calls[0]["point"])
        if distance >= RADIUS + 0.05:
            # Beyond one cutter radius of the wall the sample keeps its own axis.
            assert (dx, dy) == (0.0, 0.0), (x, distance, calls)
            beyond.append(distance)
        elif distance <= RADIUS - 0.05:
            # Within it the axis moves along the curved wall's normal until the cutter
            # is tangent to the R4 boss.
            gap = math.hypot(x + dx - BOSS[0], dy - BOSS[1])
            assert abs(gap - (BOSS[2] + RADIUS)) <= 1e-3, (x, distance, gap, calls)
            within.append(distance)
    assert len(within) == 2, (within, beyond)
    # Seam samples just beyond the radius on each side of the boss keep their axes.
    assert sum(distance < RADIUS + 0.5 for distance in beyond) == 2, beyond
