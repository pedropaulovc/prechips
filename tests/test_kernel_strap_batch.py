"""Native strap batches retain physical runs, footprint rows and scalar error precedence.

Authored B-reps run under the shared FreeCAD fixture; absent FreeCAD skips the module's
cases. Real-job raw/byte proofs belong to the integration harness, not this fixture.
"""

import json
import os
import subprocess

import pytest
from test_kernel_geometry import ENGINE


_NATIVE = r"""
import importlib.util
import json
import os
import sys
import FreeCAD, Part

V = FreeCAD.Vector
spec = importlib.util.spec_from_file_location("strap_engine", os.environ["ENGINE"])
engine = importlib.util.module_from_spec(spec)
spec.loader.exec_module(engine)
target = sys.argv[sys.argv.index("--") + 1] + "/strap.json"
answers = {}


def setup(stock):
    instance = engine._Setup.__new__(engine._Setup)
    instance.part = stock
    instance.hold = {}
    instance.clamp_parts = []
    return instance


def scalar_intervals(stock, point, force, span):
    line = Part.LineSegment(point - force * 0.01, point + force * span).toShape()
    return sorted(
        sorted((vertex.Point - point).dot(force) for vertex in edge.Vertexes)
        for edge in line.common(stock).Edges
    )


def query(name, stock, points, force, span=20, fast=True):
    assert stock.isValid(), name
    instance = setup(stock)
    # Independent deep copies prevent one Boolean's TShapes becoming another's input.
    scalar_stock = stock.copy()
    scalar = setup(scalar_stock)
    raw = instance._strap_batch(points, force, span)
    native_raw = [scalar_intervals(scalar_stock, p, force, span) for p in points]
    if fast:
        assert raw is not None, name + ": physical batch fell back"
    if raw is not None:
        assert raw == native_raw, name + ": raw intervals differ"
    answers[name] = {
        "bulk": instance._strap_runs(points, force, span),
        "scalar": [scalar._strap_run(p, force, span) for p in points],
        "fast": raw is not None,
    }


plate = Part.makeBox(20, 12, 3)
bored = plate.cut(Part.makeCylinder(2, 5, V(10, 6, -1)))
down = V(0, 0, -1)
points = [V(2, 2, 3), V(10, 6, 3), V(18, 10, 3), V(22, 2, 3)]
query("plate-hole", bored, points, down)
query("finite-span", bored, points, down, span=1.25)
query("reversed", bored, [V(2, 2, 0), V(10, 6, 0), V(18, 10, 0)], V(0, 0, 1))
# Preserve the old dot(force) interval measure: a 3 mm run is 6 with force length 2.
query("nonunit", bored, points, V(0, 0, -2))
query("all-air", bored, [V(23, 2, 3), V(25, 2, 3)], down)

pocket = Part.makeBox(20, 12, 8).cut(Part.makeBox(6, 6, 6, V(7, 3, 3)))
query("pocket-top", pocket, [V(2, 2, 8), V(10, 6, 8)], down)
query("pocket-floor", pocket, [V(8, 4, 3), V(12, 8, 3)], down)

rotation = FreeCAD.Rotation(V(1, 2, 3), 37)
placement = FreeCAD.Placement(V(11, -7, 4), rotation)
turned = bored.copy()
turned.Placement = placement
query("rotated", turned, [placement.multVec(p) for p in points], rotation.multVec(down))

for name, gap in [("separated-solids", 2.0), ("merged-gap", 0.8e-6), ("open-gap", 4e-6)]:
    layers = Part.makeCompound([
        Part.makeBox(20, 12, 3, V(0, 0, 0)),
        Part.makeBox(20, 12, 3, V(0, 0, -3 - gap)),
    ])
    query(name, layers, [V(2, 2, 3), V(18, 10, 3)], down,
          fast=name == "separated-solids")

# Shared supporting lines, including different axial origins, must not share answers.
query("coincident-height", bored, [V(2, 2, 3), V(2, 2, 4), V(2, 2, 3)], down, fast=False)
query("near-height", bored, [V(2, 2, 3), V(2 + 2e-6, 2, 4)], down, fast=False)


# Real bearing faces: two identical loaded footprints retain every physical row;
# the 4x4 face over the bore has four loaded corner cells and twelve air cells.
clamp_loaded = Part.makeBox(4, 4, 1, V(2, 2, 3))
clamp_mixed = Part.makeBox(4, 4, 1, V(8, 4, 3))
# Its corners touch the rim, but every cell centre of this 3x3 face lies over air.
clamp_air = Part.makeBox(3, 3, 1, V(8.5, 4.5, 3))
wall = setup(bored)
wall.hold = {"clamp_debts": ["undrawn toe"]}
wall.clamp_parts = [
    ("loaded", down, [clamp_loaded, clamp_loaded]),
    ("mixed", down, [clamp_mixed]),
    ("air", down, [clamp_air]),
    ("absent", down, []),
]
facts = {"reasons": {}}
wall._strap_walls(facts)
answers["walls"] = facts
scalar_rows = []
span = bored.BoundBox.DiagonalLength + 1.0
for name, force, parts in wall.clamp_parts:
    for point in wall._footprint(parts, force, bored):
        scalar_rows.append({"clamp": name, "point": list(point),
                            "run": wall._strap_run(point, force, span)})
answers["wall-scalars"] = scalar_rows

unloaded = setup(bored)
unloaded.hold = {"clamp_debts": ["undrawn toe"]}
unloaded.clamp_parts = [("absent", down, [])]
unresolved = {"reasons": {}}
unloaded._strap_walls(unresolved)
answers["unresolved"] = unresolved


def exception(call):
    try:
        call()
    except Exception as error:
        return {"type": type(error).__name__, "message": str(error)}
    raise AssertionError("expected an actual native scalar exception")


# Only optional compound creation is fault-injected. Each fallback still performs
# native per-query line/stock Booleans; no fake scalar answers or call-count proof.
original_compound = Part.makeCompound


class OptionalResult:
    def __init__(self, result):
        self.result = result

    def common(self, stock):
        return self.result


class InvalidResult:
    def isNull(self):
        return False

    def isValid(self):
        return False


class FailedBoolean:
    def common(self, stock):
        raise RuntimeError("optional compound Boolean failed")


def fail_compound(lines):
    raise RuntimeError("optional compound unavailable")


foreign = Part.LineSegment(V(30, 30, 3), V(30, 30, 0)).toShape()
faults = {
    "boolean-failure": lambda lines: FailedBoolean(),
    "null-result": lambda lines: OptionalResult(Part.Shape()),
    "invalid-result": lambda lines: OptionalResult(InvalidResult()),
    "unmatched-result": lambda lines: OptionalResult(foreign),
}
for name, fault in faults.items():
    instance = setup(bored.copy())
    scalar = setup(bored.copy())
    expected = [scalar._strap_run(p, down, 20) for p in points]
    try:
        Part.makeCompound = fault
        bulk = instance._strap_runs(points, down, 20)
        wall_fault = setup(bored.copy())
        wall_fault.hold = wall.hold
        wall_fault.clamp_parts = wall.clamp_parts
        actual_walls = {"reasons": {}}
        wall_fault._strap_walls(actual_walls)
    finally:
        Part.makeCompound = original_compound
    answers[name] = {"bulk": bulk, "scalar": expected, "walls": actual_walls}

# A null stock triggers an actual native Boolean error. Optional batch failures
# must neither replace it nor catch its scalar replay.
null_stock = setup(Part.Shape())
null_error = exception(lambda: null_stock._strap_run(points[0], down, 20))
try:
    Part.makeCompound = fail_compound
    null_bulk = exception(lambda: null_stock._strap_runs(points[:2], down, 20))
finally:
    Part.makeCompound = original_compound
answers["null-stock-error"] = {"scalar": null_error, "bulk": null_bulk}

# Zero force gives the original native line-construction error, not a batch error.
zero = V(0, 0, 0)
instance = setup(bored)
answers["query-error"] = {
    "scalar": exception(lambda: instance._strap_run(points[0], zero, 20)),
    "bulk": exception(lambda: instance._strap_runs(points[:2], zero, 20)),
}


class BrokenFootprint(engine._Setup):
    @staticmethod
    def _footprint(parts, force, stock):
        yield points[0]
        raise RuntimeError("later footprint failure")


def broken_walls(stock, force):
    instance = BrokenFootprint.__new__(BrokenFootprint)
    instance.part = stock
    instance.hold = {}
    instance.clamp_parts = [("broken", force, [])]
    instance._strap_walls({"reasons": {}})


answers["footprint-error"] = {
    "native-first": exception(lambda: broken_walls(bored.copy(), zero)),
    "generator-only": exception(lambda: broken_walls(bored.copy(), down)),
    "scalar": exception(lambda: setup(bored.copy())._strap_run(points[0], zero, 20)),
}

with open(target, "w", encoding="utf-8") as stream:
    json.dump(answers, stream)
"""


@pytest.fixture(scope="module")
def native_straps(tmp_path_factory, freecad_kernel):
    directory = tmp_path_factory.mktemp("strap-batches")
    script = directory / "strap.py"
    script.write_text(_NATIVE, encoding="utf-8")
    process = subprocess.run(
        [freecad_kernel, str(script), "--", str(directory)],
        capture_output=True,
        text=True,
        errors="replace",
        timeout=300,
        env={**os.environ, "ENGINE": str(ENGINE)},
    )
    target = directory / "strap.json"
    assert target.exists(), process.stdout[-4000:] + process.stderr[-4000:]
    return json.loads(target.read_text(encoding="utf-8"))


@pytest.mark.parametrize(
    "name, expected, fast",
    [
        ("plate-hole", [3, None, 3, None], True),
        ("finite-span", [1.25, None, 1.25, None], True),
        ("reversed", [3, None, 3], True),
        ("nonunit", [6, None, 6, None], True),
        ("all-air", [None, None], True),
        ("pocket-top", [8, None], True),
        ("pocket-floor", [3, 3], True),
        ("rotated", [3, None, 3, None], True),
        ("separated-solids", [3, 3], True),
        ("merged-gap", [6 + 0.8e-6, 6 + 0.8e-6], False),
        ("open-gap", [3, 3], False),
        ("coincident-height", [3, None, 3], False),
        ("near-height", [3, None], False),
    ],
)
def test_native_batch_keeps_first_physical_run(native_straps, name, expected, fast):
    row = native_straps[name]
    assert row["bulk"] == row["scalar"]
    assert len(row["bulk"]) == len(expected)
    for actual, known in zip(row["bulk"], expected, strict=True):
        if known is None:
            assert actual is None
        else:
            assert actual == pytest.approx(known, abs=1e-9, rel=0)
    if fast:
        assert row["fast"] is True


def test_every_physical_footprint_row_keeps_order_minimum_and_debts(native_straps):
    facts = native_straps["walls"]
    rows = facts["strap_wall_map"]
    scalars = native_straps["wall-scalars"]
    assert len(rows) == len(scalars) == 64
    assert rows[:16] == rows[16:32]
    assert [r["clamp"] for r in rows] == ["loaded"] * 32 + ["mixed"] * 16 + ["air"] * 16
    assert sum(r["loaded"] for r in rows[:32]) == 32
    assert sum(r["loaded"] for r in rows[32:48]) == 4
    assert not any(r["loaded"] for r in rows[48:])
    for row, scalar in zip(rows, scalars, strict=True):
        assert row["point_mm"] == pytest.approx(scalar["point"], abs=1e-6)
        x, y, z = row["point_mm"]
        assert z == 3
        loaded = (x - 10) ** 2 + (y - 6) ** 2 > 4
        assert row["loaded"] is loaded
        assert row["run_mm"] == (3 if loaded else "unknown")
        assert scalar["run"] == (3 if loaded else None)
    assert facts["min_wall_mm"] == 3
    assert facts["strap_wall_debts"] == [
        "undrawn toe",
        "air has no sampled footprint point bearing on the stock",
        "absent has no sampled footprint point bearing on the stock",
    ]
    assert facts["reasons"] == {}


def test_no_bearing_footprint_retains_unresolved_wall_debt(native_straps):
    facts = native_straps["unresolved"]
    assert facts["strap_wall_map"] == []
    assert "min_wall_mm" not in facts
    assert facts["reasons"]["min_wall_mm"] == (
        "strap walls unresolved: undrawn toe; "
        "absent has no sampled footprint point bearing on the stock"
    )


@pytest.mark.parametrize(
    "name", ["boolean-failure", "null-result", "invalid-result", "unmatched-result"]
)
def test_optional_batch_fault_replays_native_runs_and_complete_walls(native_straps, name):
    row = native_straps[name]
    assert row["bulk"] == row["scalar"] == [3, None, 3, None]
    assert row["walls"] == native_straps["walls"]


@pytest.mark.parametrize("name", ["null-stock-error", "query-error"])
def test_original_native_scalar_error_escapes_batch_fallback(native_straps, name):
    row = native_straps[name]
    assert row["bulk"] == row["scalar"]


def test_later_footprint_failure_cannot_replace_earlier_native_query_error(native_straps):
    row = native_straps["footprint-error"]
    assert row["native-first"] == row["scalar"]
    assert row["generator-only"] == {
        "type": "RuntimeError", "message": "later footprint failure"
    }
