"""Every printed DRO cutter-centre checkpoint stands where rule A′ lets the cutter.

The kernel stands the op's cutter cylinder at each printed row, from its tip up above the
setup-entry stock. Finished material, the op's leave and fixture solids always error. A
bounded chain regenerates whole holes on true curves inside its radius-eroded clearing
box. Other bounded paths clip where their cutter first meets stock past that box.
Paths that leave and re-enter are pieces, never reconnected. An unbounded
profile op's printed run-out is credited removal: its corner miter may nick retained scrap,
but never stock a later setup grips, presses, locates, rests or supports on; a later setup
whose contacts are unresolved leaves the rows unknown. An unbounded chain-drill op removes
only its discrete hole cylinders: the webs between them stay stock. FreeCAD-backed tests run
``src/prechips/kernel/freecad_job.py`` under ``freecadcmd`` and skip without it.
"""

import ast
import json
import math
import os
import subprocess
from copy import deepcopy

import pytest
from test_kernel_geometry import ENGINE, Engine, _op, _setup, _vise
from test_kernel_held_split import UP, _box
from test_kernel_stock_prefix import BLANK, HOLD

from prechips.kernel import chain_boundary, table_checkpoints
from prechips.rules.coordinates import FRAGMENT_FORMAT, ROW_FORMAT
from prechips.rules.resolution import LENGTH_TOLERANCE_MM

_AUTHOR = r"""
import sys
import FreeCAD, Part
V = FreeCAD.Vector
out = sys.argv[sys.argv.index("--") + 1]
Part.makeBox(60, 40, 20, V(5, 5, 0)).exportStep(out + "/island.step")
"""
# The island's west wall is x = 5, y 5..45; the blank is x 0..70, y -5..55, z 0..20.
WEST = ((5, 5, 0), (5, 45, 20))
NORTH = ((5, 45, 0), (65, 45, 20))
# The later setup's vise with its parallels drawn under y -3..3 and 47..53.
SEATED = _vise(5.0, centre=35.0, parallels=(150.0, 6.0, [[35.0, 0.0], [35.0, 50.0]]))
# A cutter centre 3 mm off the west wall and 3 mm off the north wall's line: the corner
# miter of the island's north-west corner, 3 mm past the west wall's corridor end disc.
MITER = [("line -X", [(2.0, 5.0), (2.0, 45.0), (2.0, 48.0)])]


@pytest.fixture(scope="module")
def island(tmp_path_factory, freecad_kernel):
    directory = tmp_path_factory.mktemp("checkpoint-solids")
    script = directory / "author.py"
    script.write_text(_AUTHOR, encoding="utf-8")
    process = subprocess.run(
        [freecad_kernel, str(script), "--", str(directory)],
        capture_output=True,
        text=True,
        errors="replace",
        timeout=300,
    )
    step = directory / "island.step"
    assert step.exists(), process.stdout[-2000:] + process.stderr[-2000:]
    return step


@pytest.fixture
def engine(tmp_path, freecad_kernel):
    return Engine(tmp_path, freecad_kernel)


@pytest.fixture(scope="module")
def pure_chain_regeneration():
    """Run the native primitive without FreeCAD, with its real shared predicate."""
    tree = ast.parse(ENGINE.read_text(encoding="utf-8"))
    helpers = [
        node
        for node in tree.body
        if (
            isinstance(node, (ast.FunctionDef, ast.ClassDef))
            and node.name in {"_number", "_positive", "_ClipUnknown"}
            or isinstance(node, ast.Assign)
            and any(
                isinstance(target, ast.Name) and target.id == "PLANE_TOL" for target in node.targets
            )
        )
    ]
    setup = next(
        node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "_Setup"
    )
    regenerate = next(
        node
        for node in setup.body
        if isinstance(node, ast.FunctionDef) and node.name == "_regenerate_chain"
    )
    regenerate.decorator_list = []
    namespace = {"math": math, "chain_boundary": chain_boundary}
    exec(
        compile(ast.Module(body=[*helpers, regenerate], type_ignores=[]), str(ENGINE), "exec"),
        namespace,
    )
    return namespace["_regenerate_chain"], namespace["_ClipUnknown"]


def _printed(
    subject,
    stage,
    tables,
    tip=0.0,
    overshoot=(),
    bounded=False,
    kind="line_table",
):
    """Coordinates checkpoints as build_job passes them: each ``(name, points)`` table
    is a path of named rows, its cutter clearing from the left of its travel; ``overshoot``
    names the corner-miter row ids. A ``bounded`` op's tables print on a 0.001 mm DRO."""
    rows, paths = [], []
    for name, points in tables:
        name = f"{subject} {stage} {name}"
        ids = [name + ROW_FORMAT[kind].format(i) for i in range(len(points))]
        for row_id, xy in zip(ids, points, strict=True):
            row = {"id": row_id, "xy_mm": list(xy), "tip_z_mm": tip}
            rows.append({**row, "overshoot": True} if row_id in overshoot else row)
        paths.append(
            {
                "table": ids[0],
                "name": name,
                "kind": kind,
                "cutter_side": "left",
                "directed": True,
                "xy_mm": [list(xy) for xy in points],
                "tip_z_mm": tip,
                "ids": ids,
                "overshoot": [row_id in overshoot for row_id in ids],
            }
        )
    result = {"rows": rows, "paths": paths, "bounded": bounded}
    if bounded:
        result["dro"] = {"step": 0.001, "decimals": 3, "scale": 1.0}
        result["row_format"], result["fragment_format"] = ROW_FORMAT, FRAGMENT_FORMAT
    return result


def _job(engine, step, ops, later=SEATED, **walls):
    features = {}
    for name, (lo, hi) in walls.items():
        features[name] = engine.refs(step, lo, hi, kind="Plane")
        assert len(features[name]) == 1, name
    setups = [_setup(ops, HOLD, setup_id="S1"), _setup([], later, setup_id="S2")]
    return engine.job(step, features, setups, stock=BLANK)


def _profile(radius, tables, tip=0.0, overshoot=()):
    """A full-depth finish profile of the west wall printing ``tables``."""
    op = _op("S1:10", "west", radius, 25.0, 30.0)
    return {
        **op,
        "do": "finish_profile",
        "to_z": 0.0,
        "checkpoints": _printed("S1:10", "finish", tables, tip, overshoot),
    }


def _clamped(at, gaps=()):
    """A later fixture: a floor plate under the blank and a 10 x 2 x 5 press pad on the
    stock top (z 20) centred at ``at``."""
    pad = _box("pad:pad", [-5.0, -1.0, 0.0], [10.0, 2.0, 5.0])
    return {
        "kind": "solids",
        "fixture_kind": "custom",
        "pose": {"origin_mm": [0.0, 0.0, 0.0], **UP},
        "solids": [_box("nest:floor", [-5.0, -10.0, -5.0], [80.0, 70.0, 5.0])],
        "clamps": [
            {
                "name": "clamp 1 pad",
                "pose": {"origin_mm": [at[0], at[1], 20.0], **UP},
                "solids": [pad],
                "restraint": "press",
            }
        ],
        "debts": [],
        "gaps": list(gaps),
    }


def _errors(op):
    return {(error["row"], error["obstacle"]) for error in op["checkpoint_errors"]}


def _later(op):
    return {
        (error["row"], error["later_setup"], error["contact"])
        for error in op["checkpoint_errors"]
        if "later_setup" in error
    }


# A rough cutter off the DRO grid, so no contact lands on a grid point; the kernel's cutter
# is LIFT (1 um) narrower than its radius.
RADIUS = 3.0003
RHO = RADIUS - 1e-3


def _bounded(tables, stage="rough", box=(0.0, 5.0, -5.0, 20.0), subject="S1:10"):
    """A west-wall profile bounded by default to the blank's west strip south of y 20;
    a rough one leaves 0.2 mm."""
    op = {
        **_op(subject, "west", RADIUS, 25.0, 30.0),
        "do": f"{stage}_profile",
        "to_z": 0.0,
        "stock_removal_bounds": {"x": list(box[:2]), "y": list(box[2:]), "z": [0.0, 20.0]},
    }
    if stage == "rough":
        op["rough_allowance_mm"] = 0.2
    if tables:
        op["checkpoints"] = _printed(subject, stage, tables, bounded=True)
    return op


def _clips(engine, island, tables, ops=(), **bounded):
    job = _job(engine, island, [*ops, _bounded(tables, **bounded)], west=WEST)
    facts = engine.run(job)["ops"]["S1:10"]
    clips = facts["checkpoint_clips"]
    assert "reason" not in clips, clips
    # The clipped rows are all rule A′ judges, and they are clear.
    assert facts["checkpoint_errors"] == [] and facts["checkpoint_hits"] == 0, facts
    return facts, clips


def test_a_bounded_sweep_grazing_the_finished_part_between_clear_rows_is_not_clipped(
    engine, island
):
    # Op 5 clears the frame about the island's south-west corner; op 10's chord then
    # grazes that corner 0.01 mm between two clear rows, as a printed arc's chord sags
    # into its wall. The finished part is rule A′'s obstacle at the rows, never stock the
    # clip stops at, though it lies outside op 10's box.
    cleared = _bounded([], stage="finish", box=(0.0, 20.0, -5.0, 20.0), subject="S1:5")
    c = 10.0 - (RHO - 0.01) * math.sqrt(2)  # the chord x + y = c
    path = [(1.5, c - 1.5), (c - 1.5, 1.5)]
    box = (0.0, 5.0, -5.0, 5.0)
    facts, clips = _clips(engine, island, [("line S", path)], [cleared], stage="finish", box=box)
    (entry,) = clips["paths"]
    assert entry["pieces"] == [[{"row": 0}, {"row": 1}]] and entry["clip_points"] == []
    assert facts["checkpoint_count"] == 2


def test_a_bounded_path_past_its_box_only_through_air_is_not_clipped(engine, island):
    # Inside the box beside the leave, then west and north past the box in the air beyond
    # the blank's x 0: no stock outside the box is ever met.
    path = [(1.5, 0.0), (1.5, 10.0), (-10.0, 10.0), (-10.0, 40.0)]
    facts, clips = _clips(engine, island, [("line -X", path)])
    (entry,) = clips["paths"]
    assert entry["pieces"] == [[{"row": i} for i in range(4)]]
    assert entry["clip_points"] == [] and entry["dropped_rows"] == []
    assert facts["checkpoint_count"] == 4


def test_a_bounded_path_into_stock_past_its_box_ends_at_the_first_contact(engine, island):
    facts, clips = _clips(engine, island, [("line -X", [(1.5, 0.0), (1.5, 40.0)])])
    (entry,) = clips["paths"]
    ((first, end),) = entry["pieces"]
    assert first == {"row": 0} and entry["dropped_rows"] == ["S1:10 rough line -X[1]"]
    # The cutter first meets the blank past the box's y 20 when its edge reaches it.
    contact = 20.0 - RHO
    assert end["after"] == 0
    assert end["exact_xy"][0] == pytest.approx(1.5)
    assert abs(end["exact_xy"][1] - contact) <= clips["precision_mm"], end
    # Printed on the DRO grid on the legal side: short of the contact, never past it.
    assert end["dro_xy"] == [1.5, 17.0]
    assert facts["checkpoint_count"] == 2


def test_a_shallow_clip_on_a_coarse_dro_prints_the_nearest_legal_grid_point_along_it(
    engine, island
):
    # A shallow chord east over the island's north leave into the stock north of a box
    # ending at y 52.2, on a 0.5 mm DRO grid: every grid point within a few steps of the
    # contact either reaches that stock or sits south of the chord, nearer its walls. The
    # nearest legal one lies 6 mm back along the chord.
    op = _bounded([], box=(0.0, 70.0, -5.0, 52.2))
    path = [("line -X", [(10.0, 48.5), (40.0, 49.5)])]
    op["checkpoints"] = _printed("S1:10", "rough", path, tip=10.0, bounded=True)
    op["checkpoints"]["dro"] = {"step": 0.5, "decimals": 1, "scale": 1.0}
    facts = engine.run(_job(engine, island, [op], west=WEST))["ops"]["S1:10"]
    clips = facts["checkpoint_clips"]
    assert "reason" not in clips, clips
    ((_, end),) = clips["paths"][0]["pieces"]
    contact_x = 10.0 + (52.2 - RHO - 48.5) * 30.0
    assert abs(end["exact_xy"][0] - contact_x) <= 30.0 * clips["precision_mm"], end
    assert end["dro_xy"] == [25.0, 49.0]
    # Its printed rows meet neither the leave nor the stock past the box.
    assert facts["checkpoint_errors"] == [], facts["checkpoint_errors"]


def test_a_bounded_path_that_leaves_and_reenters_its_box_is_two_pieces(engine, island):
    # North into stock past y 20, west out of the blank, then south and back east into the
    # box: the legal parts are two pieces, the stock between them never reconnected.
    path = [(1.5, 0.0), (1.5, 40.0), (-10.0, 40.0), (-10.0, 10.0), (1.5, 10.0)]
    facts, clips = _clips(engine, island, [("line -X", path)])
    (entry,) = clips["paths"]
    leave, enter = entry["pieces"]
    assert leave[0] == {"row": 0} and leave[1]["after"] == 0
    assert enter[0]["after"] == 1 and enter[1:] == [{"row": 2}, {"row": 3}, {"row": 4}]
    assert entry["dropped_rows"] == ["S1:10 rough line -X[1]"]
    # It regains the path once the cutter's edge clears the blank's x 0 face.
    assert abs(enter[0]["exact_xy"][0] + RHO) <= clips["precision_mm"], enter[0]
    assert enter[0]["dro_xy"] == [-3.0, 40.0]
    assert [point["after"] for point in entry["clip_points"]] == [
        "S1:10 rough line -X[0]",
        "S1:10 rough line -X[1]",
    ]
    assert facts["checkpoint_count"] == 6


def _endpoint_regeneration_cases():
    """Eight isolated physical controls without eight complete stock-prefix jobs."""
    drill, tol = 1.0, LENGTH_TOLERANCE_MM
    controls = []
    for family, bounds, pitch, kind in (
        ("finished wall", (0.0, 70.0, -5.0, 55.0), 20.0, "line_table"),
        ("uncut stock", (0.0, 70.0, -5.0, 5.0), 4.0, "arc_table"),
    ):
        cases, tables = [], []
        for name, penetration in (
            ("tangent", 0.0),
            ("within length tolerance", tol / 2),
            ("overlap", 0.01),
        ):
            if kind == "line_table":
                # At x=4 the endpoint cylinders touch just the finite west-wall
                # corners (5, 5) and (5, 45). Finished overlap remains a row-check error,
                # never stock that the bounds clip may silently remove.
                curve = {
                    "kind": "line",
                    "ends": [[4.0 + penetration, 5.0], [4.0 + penetration, 45.0]],
                    "normal": [-1.0, 0.0],
                }
                wall = {
                    "kind": "line",
                    "ends": [[5.0 + penetration, 5.0], [5.0 + penetration, 45.0]],
                    "normal": [-1.0, 0.0],
                }
                points = [[4.0 + penetration, y] for y in (5.0, 25.0, 45.0)]
            else:
                # The true R24 offset circle ends at (35, 4), point-tangent to the
                # y=5 bound for a radius-1 cylinder. An overlapping authored end
                # requires a new circle/bound intersection, not a chord clip hole.
                radius = 24.0 + penetration
                curve = {
                    "kind": "arc",
                    "centre": [35.0, -20.0],
                    "radius": radius,
                    "start_deg": 45.0,
                    "sweep_deg": 45.0,
                    "outward": 1,
                    "angle_start_deg": 45.0,
                    "angle_sweep_deg": 45.0,
                }
                wall = {**curve, "radius": radius - drill}
                count = math.ceil(radius * math.radians(45.0) / pitch)
                angles = [math.radians(45.0 + 45.0 * i / count) for i in range(count + 1)]
                points = [
                    [35.0 + radius * math.cos(angle), -20.0 + radius * math.sin(angle)]
                    for angle in angles
                ]
            tables.append((f"{family} {name}", points))
            cases.append((name, penetration, curve, wall, points))
        if kind == "arc_table":
            for name, radius in (("isolated tangent", 6.0), ("short retained span", 6.05)):
                # R6 has one isolated full-cylinder contact. At R6.05 the real
                # retained arc is shorter than Ø2, so it must become one hole,
                # not a pair of overlapping endpoint cylinders.
                curve = {
                    "kind": "arc",
                    "centre": [35.0, 10.0],
                    "radius": radius,
                    "start_deg": 225.0,
                    "sweep_deg": 90.0,
                    "outward": 1,
                    "angle_start_deg": 225.0,
                    "angle_sweep_deg": 90.0,
                }
                wall = {**curve, "radius": radius - drill}
                count = math.ceil(radius * math.radians(90.0) / pitch)
                angles = [math.radians(225.0 + 90.0 * i / count) for i in range(count + 1)]
                points = [
                    [35.0 + radius * math.cos(angle), 10.0 + radius * math.sin(angle)]
                    for angle in angles
                ]
                tables.append((f"{family} {name}", points))
                cases.append((name, 0.0, curve, wall, points))
        for table, case in zip(tables, cases, strict=True):
            checkpoints = _printed("S1:10", "rough", [table], bounded=True, kind=kind)
            (path,) = checkpoints["paths"]
            _, _, curve, wall, _ = case
            path.update(
                method="chain_drill",
                chain_geometry={
                    "pitch_mm": pitch,
                    "offset": drill,
                    "setup_origin": [0.0, 0.0],
                    "basis": [[1.0, 0.0], [0.0, 1.0]],
                    "curves": [curve],
                    "walls": [wall],
                },
            )
            controls.append(
                {
                    "name": table[0],
                    "family": family,
                    "control": case[0],
                    "penetration": case[1],
                    "paths": checkpoints["paths"],
                    "checkpoints": checkpoints,
                    "bounds": {
                        "x": list(bounds[:2]),
                        "y": list(bounds[2:]),
                        "z": [0.0, 3.0],
                    },
                    "radius": drill,
                    "allowance": 0.0,
                    "dro": checkpoints["dro"],
                    "finished": {
                        "kind": "polygon",
                        "points": [[5.0, 5.0], [65.0, 5.0], [65.0, 45.0], [5.0, 45.0]],
                    },
                }
            )
    return controls


def _unsnappable_interval_cases():
    """Fixed finite walls leave one local DRO wedge empty, not the whole bounds."""
    radius, pitch = 1.8, 4.0
    walls = [
        {"kind": "line", "ends": [[x, 0.0], [x, 24.0]], "normal": normal}
        for x, normal in ((2.0, [-1.0, 0.0]), (8.2, [1.0, 0.0]))
    ]
    cases = []
    for name, legs in (
        ("bad-first", ("bad", "good")),
        ("bad-last", ("good", "bad")),
        ("all-unsnappable", ("bad",)),
        ("safe-only", ("good",)),
    ):
        tables = [
            (leg, [[0.2 if leg == "bad" else 10.0, y] for y in (4.0, 8.0, 12.0, 16.0, 20.0)])
            for leg in legs
        ]
        checkpoints = _printed("S1:10", "rough", tables, bounded=True)
        checkpoints["dro"] = {"step": 1.0, "decimals": 0, "scale": 1.0}
        bad_tables = []
        for leg, path in zip(legs, checkpoints["paths"], strict=True):
            x, normal = (0.2, [-1.0, 0.0]) if leg == "bad" else (10.0, [1.0, 0.0])
            path.update(
                method="chain_drill",
                chain_geometry={
                    "pitch_mm": pitch,
                    "offset": radius,
                    "setup_origin": [0.0, 0.0],
                    "basis": [[1.0, 0.0], [0.0, 1.0]],
                    "curves": [{"kind": "line", "ends": [[x, 4.0], [x, 20.0]], "normal": normal}],
                    "walls": deepcopy(walls),
                },
            )
            if leg == "bad":
                bad_tables.append(path["table"])
        cases.append(
            {
                "name": f"unsnappable-{name}",
                "unsnappable": name,
                "bad_tables": bad_tables,
                "paths": checkpoints["paths"],
                "checkpoints": checkpoints,
                "bounds": {"x": [-1.6, 13.8], "y": [2.2, 21.8], "z": [0.0, 3.0]},
                "radius": radius,
                "allowance": 0.0,
                "dro": checkpoints["dro"],
                "finished": {
                    "kind": "polygon",
                    "points": [[2.0, 0.0], [8.2, 0.0], [8.2, 24.0], [2.0, 24.0]],
                },
            }
        )
    return cases


def test_bounded_chain_holes_regenerate_safe_true_curve_endpoints(regeneration_boundaries):
    controls = [(case, result) for case, result in regeneration_boundaries if "control" in case]
    assert {(case["family"], case["control"]) for case, _ in controls} == {
        ("finished wall", "tangent"),
        ("finished wall", "within length tolerance"),
        ("finished wall", "overlap"),
        ("uncut stock", "tangent"),
        ("uncut stock", "within length tolerance"),
        ("uncut stock", "overlap"),
        ("uncut stock", "isolated tangent"),
        ("uncut stock", "short retained span"),
    }
    assert len(controls) == 8
    tol = LENGTH_TOLERANCE_MM
    for case, result in controls:
        family, name, penetration = case["family"], case["control"], case["penetration"]
        drill, step = case["radius"], case["dro"]["step"]
        (path,) = case["paths"]
        geometry = path["chain_geometry"]
        (curve,) = geometry["curves"]
        authored, pitch = path["xy_mm"], geometry["pitch_mm"]
        facts, entry = result["facts"], result["entry"]
        assert "reason" not in facts["checkpoint_clips"], facts
        assert "checkpoint_reason" not in facts, facts
        assert entry["rows"] == len(authored)
        assert entry["regeneration"] == "true_curve"
        assert entry["clip_points"] == []
        (piece,) = entry["pieces"]
        assert piece
        nominal = [point["exact_xy"] for point in piece]
        printed = [point["dro_xy"] for point in piece]
        for point, exact, actual in zip(piece, nominal, printed, strict=True):
            assert point["generated"] is True
            assert "after" not in point and "t" not in point
            assert point["model_xy"] == exact
            assert all(abs(value / step - round(value / step)) < 1e-7 for value in actual)
            assert max(abs(a - b) for a, b in zip(exact, actual, strict=True)) <= 3 * step + tol
            for axis, key in enumerate(("x", "y")):
                lo, hi = case["bounds"][key]
                assert lo + drill - tol <= actual[axis] <= hi - drill + tol
        if curve["kind"] == "line":
            assert nominal[0] == pytest.approx(curve["ends"][0], abs=tol)
            assert nominal[-1] == pytest.approx(curve["ends"][-1], abs=tol)
            assert entry["dropped_ends"] == [False, False]
            gaps = [math.dist(a, b) for a, b in zip(nominal, nominal[1:], strict=False)]
            assert all(actual[0] <= 4.0 + penetration + tol for actual in printed)
        else:
            radius, centre = curve["radius"], curve["centre"]
            if name in ("isolated tangent", "short retained span"):
                half_width = math.sqrt(max(0.0, radius**2 - 6.0**2))
                start, end = [35.0 - half_width, 4.0], [35.0 + half_width, 4.0]
                assert nominal[0] == pytest.approx(start, abs=tol)
                assert len(piece) == 1 and entry["dropped_ends"] == [True, True]
                if name == "isolated tangent":
                    assert nominal[-1] == pytest.approx(end, abs=tol)
                    assert printed == [[35.0, 4.0]]
                    assert all(math.dist(point, printed[0]) > tol for point in authored)
                else:
                    assert nominal[0] != pytest.approx(end, abs=tol)
                assert result["sketch_debts"] == []
                assert result["sketch_paths"] == [{"op": "10", "xy": printed, "directed": True}]
                (waypoint,) = result["waypoints"]
                assert waypoint["op"] == "10"
                assert waypoint["xy"] == printed[0]
                assert waypoint["rows"] == [path["ids"][0]]
            else:
                # At LENGTH/2 the nominal end stays within bounds tolerance.
                # A grid point past the finite wall's 90-degree endpoint can
                # clear its end cap even when it lies inside the infinite circle.
                end = (
                    [35.0 + math.sqrt(radius**2 - 24.0**2), 4.0]
                    if penetration > tol
                    else authored[-1]
                )
                assert nominal[0] == pytest.approx(authored[0], abs=tol)
                assert nominal[-1] == pytest.approx(end, abs=tol)
                assert entry["dropped_ends"] == [False, penetration > tol]
                if name == "within length tolerance":
                    (wall,) = geometry["walls"]
                    wall_end = [centre[0], centre[1] + wall["radius"]]
                    assert printed[-1][0] < centre[0]
                    assert math.dist(printed[-1], centre) < radius
                    assert math.dist(printed[-1], wall_end) >= (
                        min(math.dist(nominal[-1], wall_end), geometry["offset"]) - 1e-9
                    )
                assert math.dist(printed[-1], end) <= 3 * math.sqrt(2) * step + tol
            for point, exact, actual in zip(piece, nominal, printed, strict=True):
                assert math.dist(exact, centre) == pytest.approx(radius, abs=tol)
                angle = math.radians(point["angle_deg"])
                assert exact == pytest.approx(
                    [centre[0] + radius * math.cos(angle), centre[1] + radius * math.sin(angle)],
                    abs=tol,
                )
                radial_tolerance = tol if point is piece[0] or point is piece[-1] else 1e-9
                assert math.dist(actual, centre) >= radius - radial_tolerance
            angles = [point["angle_deg"] for point in piece]
            gaps = [radius * math.radians(b - a) for a, b in zip(angles, angles[1:], strict=False)]
            if penetration > tol:
                assert authored[-1][1] + drill > case["bounds"]["y"][1] + tol
                assert path["ids"][-1] in entry["dropped_rows"]
                assert math.dist(printed[-1], authored[-1]) > step
        dro_gaps = [math.dist(a, b) for a, b in zip(printed, printed[1:], strict=False)]
        if name in ("isolated tangent", "short retained span"):
            assert gaps == dro_gaps == []
        else:
            assert gaps == pytest.approx([gaps[0]] * len(gaps), abs=2 * tol)
            assert max(gaps) <= pitch + 2 * tol
            assert max(dro_gaps) <= pitch + 2 * step + 2 * tol
            assert all(
                math.dist(a, b) > 2 * drill + tol
                for index, a in enumerate(printed)
                for b in printed[index + 1 :]
            )
        assert facts["checkpoint_count"] == len(piece)
        assert [row["xy_mm"] for row in result["rows"]] == printed
        assert all(row["method"] == "chain_drill" for row in result["rows"])
        assert len(result["evidence"]) == len(piece)
        overlap = family == "finished wall" and name == "overlap"
        for proof in result["evidence"]:
            assert proof["outside_bounds_volume"] <= 1e-7
            assert proof["fixture_volume"] <= 1e-7
            for nominal_gap, actual_gap in zip(
                proof["nominal_wall_gaps"], proof["actual_wall_gaps"], strict=True
            ):
                assert actual_gap >= min(nominal_gap, geometry["offset"]) - 1e-9
            if overlap:
                assert proof["finished_volume"] > 1e-7
            else:
                assert proof["finished_volume"] <= 1e-7
        if not overlap:
            # Tangency is a real zero-gap, zero-volume contact, not a clear
            # result obtained by shaving the commanded cylinder radius.
            assert min(proof["finished_gap"] for proof in result["evidence"]) == pytest.approx(
                0.0, abs=tol
            )
        if overlap:
            # Real full-radius cylinders must produce the production row errors;
            # clipping cannot reinterpret finished-part overlap as discardable stock.
            assert facts["checkpoint_hits"] == len(piece)
            assert len(facts["checkpoint_errors"]) == len(piece)
            assert all(
                error["row"] == row["id"]
                and error["obstacle"] == "finished part"
                and error["volume_mm3"] > 0
                for error, row in zip(facts["checkpoint_errors"], result["rows"], strict=True)
            )
        else:
            assert facts["checkpoint_hits"] == 0 and facts["checkpoint_errors"] == [], facts


def _assert_unsnappable_interval_oracle(case, result):
    """Exhaust the whole retained line's neighbourhood, not the engine's walk samples."""
    proof, drill, step = result["unsnappable_oracle"], case["radius"], case["dro"]["step"]
    inner = [[lo + drill, hi - drill] for lo, hi in (case["bounds"][key] for key in ("x", "y"))]
    assert inner[0] == pytest.approx([0.2, 12.0])
    assert inner[1] == pytest.approx([4.0, 20.0])
    assert proof["global_grid_count"] == 12 * 17
    # The globally legal grid is populated, and the other wall has a safe witness.
    assert all(lo <= value <= hi for value, (lo, hi) in zip((10.0, 4.0), inner, strict=True))
    assert proof["safe_witness"]["wall_gaps"] == pytest.approx([8.0, drill])
    assert proof["safe_witness"]["scrap_signed_gap"] == pytest.approx(drill)
    assert {entry["table"] for entry in proof["intervals"]} == set(case["bad_tables"])
    assert proof["intervals"]
    paths = {path["table"]: path for path in case["paths"]}
    for entry in proof["intervals"]:
        geometry = paths[entry["table"]]["chain_geometry"]
        (curve,) = geometry["curves"]
        a, b = curve["ends"]
        wall = geometry["walls"][0]
        assert a == [0.2, 4.0] and b == [0.2, 20.0]
        assert math.dist(a, b) == 16.0
        assert entry["nominal_wall_gaps"] == pytest.approx([drill, drill])
        # Radius erosion rules out x=0; the three-step neighbourhood rules out
        # x>=4. The finite wall covers every admissible y, so x=1,2,3 all have
        # gap <=1 <1.8, including the tempting wrong-side x=3 candidate.
        expected = {(x, y) for x in (1.0, 2.0, 3.0) for y in range(4, 21)}
        assert {tuple(candidate["point"]) for candidate in entry["candidates"]} == expected
        for candidate in entry["candidates"]:
            point = candidate["point"]
            assert all(lo <= value <= hi for value, (lo, hi) in zip(point, inner, strict=True))
            assert _segment_gap(point, a, b) <= 3 * step
            gap = _segment_gap(point, *wall["ends"])
            assert gap <= 1.0 < drill
            assert candidate["wall_gap"] == pytest.approx(gap, abs=LENGTH_TOLERANCE_MM)
            assert candidate["scrap_signed_gap"] < drill - LENGTH_TOLERANCE_MM
        assert any(candidate["scrap_signed_gap"] < 0 for candidate in entry["candidates"])


def _assert_unsnappable_clip_unknown(result):
    facts = result["facts"]
    clips = facts["checkpoint_clips"]
    reason = clips.get("reason", "")
    assert "no safe DRO-grid" in reason, facts
    assert "full-interval" in reason, facts
    assert "first contact could not be derived" not in reason
    assert clips["paths"] == []
    assert result["entry"] is None and result["evidence"] == []
    assert facts["checkpoint_count"] == 0
    assert facts["checkpoint_hits"] == "unknown" and facts["checkpoint_errors"] == []
    assert reason in facts["checkpoint_reason"]
    assert result["rows"] == result["checkpoint_paths"] == []
    assert reason in result["table_reason"]
    assert result["sketch_paths"] == result["waypoints"] == []
    (debt,) = result["sketch_debts"]
    assert "NOT SHOWN" in debt and reason in debt


def _assert_snappable_companion(regeneration_boundaries):
    case, result = next(
        (case, result)
        for case, result in regeneration_boundaries
        if case.get("unsnappable") == "safe-only"
    )
    facts, entry = result["facts"], result["entry"]
    assert "reason" not in facts["checkpoint_clips"] and "checkpoint_reason" not in facts, facts
    assert facts["checkpoint_hits"] == 0 and facts["checkpoint_errors"] == [], facts
    assert facts["checkpoint_count"] == 5
    assert entry["dropped_ends"] == [False, False]
    (piece,) = entry["pieces"]
    expected = [[10.0, y] for y in (4.0, 8.0, 12.0, 16.0, 20.0)]
    assert [point["dro_xy"] for point in piece] == expected
    assert [row["xy_mm"] for row in result["rows"]] == expected
    assert len(result["evidence"]) == len(piece) == 5
    for proof in result["evidence"]:
        assert proof["actual_wall_gaps"] == pytest.approx([8.0, case["radius"]])
        assert proof["finished_volume"] <= 1e-7
        assert proof["outside_bounds_volume"] <= 1e-7
        assert proof["fixture_volume"] <= 1e-7
    assert min(math.dist(a, b) for a, b in zip(expected, expected[1:], strict=False)) > (
        2 * case["radius"] + LENGTH_TOLERANCE_MM
    )


@pytest.mark.parametrize("order", ("bad-first", "bad-last"))
def test_unsnappable_chain_interval_invalidates_other_safe_path(regeneration_boundaries, order):
    case, result = next(
        (case, result)
        for case, result in regeneration_boundaries
        if case.get("unsnappable") == order
    )
    assert len(case["paths"]) == 2 and len(case["bad_tables"]) == 1
    assert (case["paths"][0]["table"] in case["bad_tables"]) == (order == "bad-first")
    _assert_snappable_companion(regeneration_boundaries)
    _assert_unsnappable_interval_oracle(case, result)
    _assert_unsnappable_clip_unknown(result)


def test_all_unsnappable_chain_intervals_report_concrete_unknown(regeneration_boundaries):
    case, result = next(
        (case, result)
        for case, result in regeneration_boundaries
        if case.get("unsnappable") == "all-unsnappable"
    )
    assert {path["table"] for path in case["paths"]} == set(case["bad_tables"])
    _assert_unsnappable_interval_oracle(case, result)
    _assert_unsnappable_clip_unknown(result)


def _regeneration_case(name, curves, walls, bounds, finished, **details):
    """Generic authored inputs, independent of any consumer STEP or recipe."""
    radius, pitch, allowance = 1.435, 4.2, 0.1
    points = []
    for curve in curves:
        length = (
            math.dist(*curve["ends"])
            if curve["kind"] == "line"
            else curve["radius"] * abs(math.radians(curve["sweep_deg"]))
        )
        count = math.ceil(length / pitch)
        leg = []
        for i in range(count + 1):
            if curve["kind"] == "line":
                a, b = curve["ends"]
                point = [a[axis] + (b[axis] - a[axis]) * i / count for axis in range(2)]
            else:
                angle = math.radians(curve["start_deg"] + i / count * curve["sweep_deg"])
                point = [
                    curve["centre"][0] + curve["radius"] * math.cos(angle),
                    curve["centre"][1] + curve["radius"] * math.sin(angle),
                ]
            leg.append(point)
        points.extend(leg[1:] if points and math.dist(points[-1], leg[0]) < 1e-9 else leg)
    kind = "arc_table" if curves[0]["kind"] == "arc" else "line_table"
    printed = _printed("S1:10", "rough", [(name, points)], bounded=True, kind=kind)
    (path,) = printed["paths"]
    path.update(
        method="chain_drill",
        chain_geometry={
            "pitch_mm": pitch,
            "offset": radius + allowance,
            "setup_origin": [2.3, -4.7],
            "basis": [[0.0, -1.0], [1.0, 0.0]],
            "curves": curves,
            "walls": walls,
        },
    )
    return {
        "name": name,
        "paths": [path],
        "bounds": {"x": list(bounds[:2]), "y": list(bounds[2:]), "z": [0.0, 3.0]},
        "radius": radius,
        "allowance": allowance,
        "dro": printed["dro"],
        "finished": finished,
        **details,
    }


def _clipped_count_cases():
    """A long authored line whose retained ends need snap-aware hole counts."""
    cases = []
    for span in (0.5, 0.499):
        name = f"clipped-count-{span:g}"
        curve = {"kind": "line", "ends": [[-5.0, 0.35], [5.0, 0.35]], "normal": [0.0, 1.0]}
        wall = {"kind": "line", "ends": [[-10.0, 0.0], [10.0, 0.0]], "normal": [0.0, 1.0]}
        printed = _printed("S1:10", "rough", [(name, curve["ends"])], bounded=True)
        (path,) = printed["paths"]
        path.update(
            method="chain_drill",
            chain_geometry={
                "pitch_mm": 0.75,
                "offset": 0.35,
                "setup_origin": [2.3, -4.7],
                "basis": [[0.0, -1.0], [1.0, 0.0]],
                "curves": [curve],
                "walls": [wall],
            },
        )
        cases.append(
            {
                "name": name,
                "count_span": span,
                "paths": [path],
                "bounds": {"x": [-0.25, span + 0.25], "y": [-10.25, 10.25], "z": [0.0, 3.0]},
                "radius": 0.25,
                "allowance": 0.1,
                "dro": printed["dro"],
                "finished": {
                    "kind": "polygon",
                    "points": [[-10.0, -10.0], [10.0, -10.0], [10.0, 0.0], [-10.0, 0.0]],
                },
            }
        )
    return cases


def _regeneration_cases():
    radius, offset = 1.435, 1.535
    cases = []
    for angle in (90.0, 30.0, 2.0):
        # X=.0009/Y=.0001 leaves no one-step outward/inside endpoint snap.
        # Near tangency, the endpoint may need to advance on the actual circle.
        endpoint = [20.0009, 20.0001]
        centre = [
            endpoint[0] - 30.0 * math.cos(math.radians(angle)),
            endpoint[1] - 30.0 * math.sin(math.radians(angle)),
        ]
        curve = {
            "kind": "arc",
            "centre": centre,
            "radius": 30.0,
            "start_deg": angle + 35.0,
            "sweep_deg": -35.0 - angle / 2,
            "outward": 1,
            "angle_start_deg": angle + 35.0,
            "angle_sweep_deg": -35.0 - angle / 2,
        }
        wall = {**curve, "radius": 30.0 - offset}
        cases.append(
            _regeneration_case(
                f"boundary-{angle:g}",
                [curve],
                [wall],
                (-70.0, endpoint[0] + radius, -70.0, 70.0),
                {"kind": "circle", "centre": centre, "radius": wall["radius"]},
                boundary=endpoint,
            )
        )

    junction = [10.0001, 10.0001]
    turn = math.radians(112.4)
    normal = [math.sin(turn), math.cos(turn)]
    direction = [math.cos(turn), -math.sin(turn)]
    corner = [junction[0] - offset * normal[0] / (1 + normal[1]), junction[1] - offset]
    first = [[junction[0] - 12.0, junction[1]], junction]
    second = [junction, [junction[i] + 12.0 * direction[i] for i in range(2)]]
    wall_ends = [
        [corner[0] - 20.0, corner[1]],
        [corner[i] + 20.0 * direction[i] for i in range(2)],
    ]
    cases.append(
        _regeneration_case(
            "convex-67.6-miter",
            [
                {"kind": "line", "ends": first, "normal": [0.0, 1.0]},
                {"kind": "line", "ends": second, "normal": normal},
            ],
            [
                {"kind": "line", "ends": [wall_ends[0], corner], "normal": [0.0, 1.0]},
                {"kind": "line", "ends": [corner, wall_ends[1]], "normal": normal},
            ],
            (-70.0, 70.0, -70.0, 70.0),
            {"kind": "polygon", "points": [corner, *wall_ends]},
            junction=junction,
        )
    )

    corner = [value - offset for value in junction]
    right = [corner[0] + 20.0, corner[1]]
    up = [corner[0], corner[1] + 20.0]
    cases.append(
        _regeneration_case(
            "concave-90-miter",
            [
                {
                    "kind": "line",
                    "ends": [[junction[0] + 12.0, junction[1]], junction],
                    "normal": [0.0, 1.0],
                },
                {
                    "kind": "line",
                    "ends": [junction, [junction[0], junction[1] + 12.0]],
                    "normal": [1.0, 0.0],
                },
            ],
            [
                {"kind": "line", "ends": [right, corner], "normal": [0.0, 1.0]},
                {"kind": "line", "ends": [corner, up], "normal": [1.0, 0.0]},
            ],
            (-70.0, 70.0, -70.0, 70.0),
            {
                "kind": "polygon",
                "points": [
                    corner,
                    right,
                    [right[0], corner[1] - 20.0],
                    [corner[0] - 20.0, corner[1] - 20.0],
                    [corner[0] - 20.0, up[1]],
                    up,
                ],
            },
            junction=junction,
        )
    )

    line = {"kind": "line", "ends": [[-10.0, 0.0001], [20.0, 0.0001]], "normal": [0.0, 1.0]}
    wall = {
        "kind": "line",
        "ends": [[-10.0, 0.0001 - offset], [20.0, 0.0001 - offset]],
        "normal": [0.0, 1.0],
    }
    for length, holes in ((1.0, 1), (4.5, 2), (5.0, 2), (8.5, 3)):
        cases.append(
            _regeneration_case(
                f"length-{length:g}",
                [line],
                [wall],
                (0.0001 - radius, 0.0001 + length + radius, -10.0, 10.0),
                {
                    "kind": "polygon",
                    "points": [[-10.0, -6.0], [20.0, -6.0], *reversed(wall["ends"])],
                },
                length=length,
                holes=holes,
            )
        )

    cases.append(
        _regeneration_case(
            "short-junction-tail",
            [
                {
                    "kind": "line",
                    "ends": [[junction[0] - 12.0, junction[1]], junction],
                    "normal": [0.0, 1.0],
                },
                {
                    "kind": "line",
                    "ends": [junction, [junction[0], junction[1] - 5.0]],
                    "normal": [1.0, 0.0],
                },
            ],
            [
                {
                    "kind": "line",
                    "ends": [[corner[0] - 20.0, corner[1]], corner],
                    "normal": [0.0, 1.0],
                },
                {
                    "kind": "line",
                    "ends": [corner, [corner[0], corner[1] - 20.0]],
                    "normal": [1.0, 0.0],
                },
            ],
            (-70.0, 70.0, junction[1] - 1.0 - radius, 70.0),
            {
                "kind": "polygon",
                "points": [corner, [corner[0] - 20.0, corner[1]], [corner[0], corner[1] - 20.0]],
            },
            junction=junction,
        )
    )
    centre = [0.00037, 0.00041]
    curve = {
        "kind": "arc",
        "centre": centre,
        "radius": 10.0,
        "start_deg": 0.0,
        "sweep_deg": 360.0,
        "outward": 1,
        "angle_start_deg": 0.0,
        "angle_sweep_deg": 360.0,
    }
    cases.append(
        _regeneration_case(
            "closed-retained-seam",
            [curve],
            [{**curve, "radius": 10.0 - offset}],
            (centre[0] + 5.0 - radius, centre[0] + 11.0 + radius, -20.0, 20.0),
            {"kind": "circle", "centre": centre, "radius": 10.0 - offset},
        )
    )
    return cases + _endpoint_regeneration_cases()


def _nearest_endpoint_cases():
    """Non-grid crossings and junctions in every D4 image, with unique safe minima.

    The finite sector deliberately ends before its offset circle meets the bound:
    clearance to its real end/caps, not the infinite supporting circle, decides safety.
    All geometry is authored here; no consumer model or production snapper supplies it.
    """
    drill, offset = 1.435, 1.535
    endpoint = [10.12337, 8.23459]
    direction, normal = [0.8, 0.6], [-0.6, 0.8]
    line = {
        "kind": "line",
        "ends": [
            [endpoint[i] - 14.0 * direction[i] for i in range(2)],
            [endpoint[i] + 6.0 * direction[i] for i in range(2)],
        ],
        "normal": normal,
    }
    wall = {
        "kind": "line",
        "ends": [
            [endpoint[i] + run * direction[i] - offset * normal[i] for i in range(2)]
            for run in (-25.0, 25.0)
        ],
        "normal": normal,
    }
    line_case = _regeneration_case(
        "nearest-line-crossing",
        [line],
        [wall],
        (-40.0, endpoint[0] + drill, -40.0, 40.0),
        {
            "kind": "polygon",
            "points": [
                *wall["ends"],
                *[
                    [point[i] - 12.0 * normal[i] for i in range(2)]
                    for point in reversed(wall["ends"])
                ],
            ],
        },
    )
    line_case["nearest"] = {
        "family": "line-crossing",
        "endpoints": [line["ends"][0], endpoint],
    }

    centre, radius = [0.13729, -0.24861], 20.0

    def circle_point(angle, circle_radius=radius):
        radians = math.radians(angle)
        return [
            centre[0] + circle_radius * math.cos(radians),
            centre[1] + circle_radius * math.sin(radians),
        ]

    arc = {
        "kind": "arc",
        "centre": centre,
        "radius": radius,
        "start_deg": 10.0,
        "sweep_deg": 30.0,
        "outward": 1,
        "angle_start_deg": 10.0,
        "angle_sweep_deg": 30.0,
    }
    endpoint = circle_point(30.0)
    bases = [line_case]
    for finite in (False, True):
        wall = {
            "kind": "arc",
            "centre": centre,
            "radius": radius - offset,
            "start_deg": 0.0,
            "sweep_deg": 25.0 if finite else 45.0,
            "outward": 1,
        }
        walls = [wall]
        if finite:
            walls.extend(
                {
                    "kind": "line",
                    "ends": [circle_point(angle, wall["radius"]), centre],
                    "normal": [
                        side * math.sin(math.radians(angle)),
                        -side * math.cos(math.radians(angle)),
                    ],
                }
                for angle, side in ((0.0, 1), (25.0, -1))
            )
            finished = {"kind": "sector", "arc": wall}
        else:
            finished = {"kind": "circle", "centre": centre, "radius": wall["radius"]}
        family = "finite-arc-end" if finite else "circle-crossing"
        case = _regeneration_case(
            f"nearest-{family}",
            [arc],
            walls,
            (-40.0, 40.0, -40.0, endpoint[1] + drill),
            finished,
        )
        case["nearest"] = {
            "family": family,
            "endpoints": [circle_point(10.0), endpoint],
        }
        bases.append(case)

    junction = [10.12337, 8.23441]
    turn = math.radians(2.0)
    direction, normal = [math.cos(turn), -math.sin(turn)], [math.sin(turn), math.cos(turn)]
    corner = [
        junction[0] - offset * math.sin(turn) / (1 + math.cos(turn)),
        junction[1] - offset,
    ]
    wall_ends = [
        [corner[0] - 20.0, corner[1]],
        [corner[i] + 20.0 * direction[i] for i in range(2)],
    ]
    # A shallow convex corner leaves less than one grid step of radial slack.
    # Ordinary rounding can therefore be too close to its finite wall vertex.
    miter = _regeneration_case(
        "nearest-convex-miter",
        [
            {
                "kind": "line",
                "ends": [[junction[0] - 12.0, junction[1]], junction],
                "normal": [0.0, 1.0],
            },
            {
                "kind": "line",
                "ends": [junction, [junction[i] + 12.0 * direction[i] for i in range(2)]],
                "normal": normal,
            },
        ],
        [
            {"kind": "line", "ends": [wall_ends[0], corner], "normal": [0.0, 1.0]},
            {"kind": "line", "ends": [corner, wall_ends[1]], "normal": normal},
        ],
        (-40.0, 40.0, -40.0, 40.0),
        {"kind": "polygon", "points": [corner, *wall_ends]},
        junction=junction,
    )
    miter["nearest"] = {
        "family": "convex-miter",
        "endpoints": [junction],
        "junction": True,
    }
    bases.append(miter)

    # Close to a grid line, but not a metric tie: the finite line end admits a
    # tempting inward snap that the incident arc rejects (and conversely).
    centre = [0.13700004, -0.24855]
    junction = circle_point(0.0)
    wall_radius = radius - offset
    join_wall = {
        "kind": "line",
        "ends": [circle_point(0.0, wall_radius), [centre[0] + wall_radius, centre[1] + 20.0]],
        "normal": [1.0, 0.0],
    }
    arc = {
        "kind": "arc",
        "centre": centre,
        "radius": radius,
        "start_deg": 0.0,
        "sweep_deg": -30.0,
        "outward": 1,
        "angle_start_deg": 0.0,
        "angle_sweep_deg": -30.0,
    }
    # The finished circle and its tangent-sided extension share a real boundary
    # junction. Both finite incident walls constrain the mandatory shared hole.
    arc_join = _regeneration_case(
        "nearest-arc-join-junction",
        [
            {
                "kind": "line",
                "ends": [[junction[0], junction[1] + 12.0], junction],
                "normal": [1.0, 0.0],
            },
        ],
        [join_wall],
        (-40.0, 40.0, -40.0, 40.0),
        {
            "kind": "arc-join",
            "circle": {"centre": centre, "radius": wall_radius},
            "points": [
                [centre[0] - wall_radius, centre[1]],
                [centre[0] + wall_radius, centre[1]],
                [centre[0] + wall_radius, centre[1] + 20.0],
                [centre[0] - wall_radius, centre[1] + 20.0],
            ],
        },
        junction=junction,
    )
    arc_join["paths"].extend(
        _regeneration_case(
            "nearest-arc-join-arc",
            [arc],
            [{**arc, "radius": wall_radius, "sweep_deg": -90.0}],
            (-40.0, 40.0, -40.0, 40.0),
            arc_join["finished"],
        )["paths"]
    )
    arc_join["nearest"] = {
        "family": "arc-join-junction",
        "endpoints": [junction],
        "junction": True,
    }
    bases.append(arc_join)

    cases = []
    rotations = (
        [[1, 0], [0, 1]],
        [[0, -1], [1, 0]],
        [[-1, 0], [0, -1]],
        [[0, 1], [-1, 0]],
    )
    for base in bases:
        for reflected in (False, True):
            for quarter_turns, rotation in enumerate(rotations):
                # Reflect X first, then apply a proper quarter-turn rotation.
                matrix = [[row[0] * (-1 if reflected else 1), row[1]] for row in rotation]

                def transform(point, matrix=matrix):
                    return [sum(row[i] * point[i] for i in range(2)) for row in matrix]

                def transform_curve(curve, transform=transform, reflected=reflected):
                    if curve["kind"] == "line":
                        curve["ends"] = [transform(point) for point in curve["ends"]]
                        if "normal" in curve:
                            curve["normal"] = transform(curve["normal"])
                        return
                    curve["centre"] = transform(curve["centre"])
                    for key in ("start_deg", "angle_start_deg"):
                        if key in curve:
                            angle = math.radians(curve[key])
                            vector = transform([math.cos(angle), math.sin(angle)])
                            curve[key] = math.degrees(math.atan2(vector[1], vector[0]))
                    if reflected:
                        curve["sweep_deg"] *= -1
                        if "angle_sweep_deg" in curve:
                            curve["angle_sweep_deg"] *= -1

                case = deepcopy(base)
                case["name"] += f"-r{quarter_turns}-{'reflect' if reflected else 'direct'}"
                for path in case["paths"]:
                    geometry = path["chain_geometry"]
                    for curve in geometry["curves"] + geometry["walls"]:
                        transform_curve(curve)
                    geometry["setup_origin"] = transform(geometry["setup_origin"])
                    geometry["basis"] = [transform(axis) for axis in geometry["basis"]]
                    path["xy_mm"] = [transform(point) for point in path["xy_mm"]]
                box = case["bounds"]
                corners = [transform([x, y]) for x in box["x"] for y in box["y"]]
                for axis, key in enumerate(("x", "y")):
                    box[key] = [min(p[axis] for p in corners), max(p[axis] for p in corners)]
                protected = case["finished"]
                if protected["kind"] == "circle":
                    protected["centre"] = transform(protected["centre"])
                elif protected["kind"] == "sector":
                    # deepcopy preserves the shared arc reference: it was already
                    # transformed with geometry["walls"], not transformed twice.
                    assert protected["arc"] is geometry["walls"][0]
                else:
                    protected["points"] = [transform(point) for point in protected["points"]]
                    if protected["kind"] == "arc-join":
                        protected["circle"]["centre"] = transform(protected["circle"]["centre"])
                case["nearest"]["endpoints"] = [
                    transform(point) for point in case["nearest"]["endpoints"]
                ]
                if "junction" in case:
                    case["junction"] = transform(case["junction"])
                case["nearest"]["transform"] = matrix
                cases.append(case)
    return cases


def _signed_boundary_cases():
    """The reviewed coarse-grid input, its safe control, and a circular counterpart."""
    cases = []
    for family, control in (("line", False), ("line", True), ("arc", False)):
        if family == "line":
            curve = {"kind": "line", "ends": [[-5.0, 1.0], [5.0, 1.0]], "normal": [0.0, 1.0]}
            wall = {"kind": "line", "ends": [[-10.0, 0.0], [10.0, 0.0]], "normal": [0.0, 1.0]}
            finished = {
                "kind": "polygon",
                "points": [
                    [-20.0, -20.0],
                    [20.0, -20.0],
                    [20.0, 0.0],
                    [-20.0, 0.0],
                ],
            }
            box = {
                "x": [-4.25, 4.25] if control else [-1.25, 1.25],
                "y": [-10.25, 2.35 if control else 1.35],
            }
            xy = curve["ends"]
        else:
            curve = {
                "kind": "arc",
                "centre": [0.0, 0.0],
                "radius": 1.0,
                "start_deg": 0.0,
                "sweep_deg": 180.0,
                "outward": 1,
                "angle_start_deg": 0.0,
                "angle_sweep_deg": 180.0,
            }
            wall = {**curve, "radius": 0.5, "sweep_deg": 360.0, "angle_sweep_deg": 360.0}
            finished = {"kind": "circle", "centre": [0.0, 0.0], "radius": 0.5}
            box = {"x": [-1.35, 1.35], "y": [-1.35, 1.35]}
            xy = [[1.0, 0.0], [-1.0, 0.0]]
        # The untransformed negative line is exactly the archived before-proof input.
        path = {
            "table": "scrap-boundary[0]",
            "name": "scrap-boundary",
            "kind": f"{family}_table",
            "cutter_side": "left",
            "directed": True,
            "xy_mm": xy,
            "tip_z_mm": 0.0,
            "ids": ["scrap-boundary[0]", "scrap-boundary[1]"],
            "overshoot": [False, False],
            "method": "chain_drill",
            "chain_geometry": {
                "pitch_mm": 4.0,
                "offset": 1.0 if family == "line" else 0.5,
                "setup_origin": [0.0, 0.0],
                "basis": [[1.0, 0.0], [0.0, 1.0]],
                "curves": [curve],
                "walls": [wall],
            },
        }
        base = {
            "paths": [path],
            "bounds": box,
            "radius": 0.25,
            "allowance": 0.0,
            "dro": {"step": 2.0, "decimals": 0, "scale": 1.0},
            "finished": finished,
        }
        rotations = ([[1, 0], [0, 1]], [[0, -1], [1, 0]], [[-1, 0], [0, -1]], [[0, 1], [-1, 0]])
        for reflected in (False, True):
            for turn, rotation in enumerate(rotations):
                case = deepcopy(base)
                matrix = [[row[0] * (-1 if reflected else 1), row[1]] for row in rotation]

                def transform(point, matrix=matrix):
                    return [sum(row[i] * point[i] for i in range(2)) for row in matrix]

                case["name"] = (
                    f"signed-boundary-{family}-{'safe' if control else 'unsafe'}"
                    f"-{int(reflected)}-{turn}"
                )
                case["signed_boundary"] = {"family": family, "control": control, "matrix": matrix}
                geometry = case["paths"][0]["chain_geometry"]
                for item in geometry["curves"] + geometry["walls"]:
                    if item["kind"] == "line":
                        item["ends"] = [transform(p) for p in item["ends"]]
                        if "normal" in item:
                            item["normal"] = transform(item["normal"])
                    else:
                        item["centre"] = transform(item["centre"])
                        start = math.radians(item["start_deg"])
                        direction = transform([math.cos(start), math.sin(start)])
                        item["start_deg"] = math.degrees(math.atan2(direction[1], direction[0]))
                        item["sweep_deg"] *= -1 if reflected else 1
                        item["angle_start_deg"] = item["start_deg"]
                        item["angle_sweep_deg"] = item["sweep_deg"]
                geometry["basis"] = [transform(axis) for axis in geometry["basis"]]
                case["paths"][0]["xy_mm"] = [transform(p) for p in case["paths"][0]["xy_mm"]]
                if reflected:
                    case["paths"][0]["cutter_side"] = "right"
                corners = [transform([x, y]) for x in box["x"] for y in box["y"]]
                case["bounds"] = {
                    key: [min(p[i] for p in corners), max(p[i] for p in corners)]
                    for i, key in enumerate(("x", "y"))
                }
                if family == "line":
                    case["finished"]["points"] = [transform(p) for p in case["finished"]["points"]]
                cases.append(case)
    return cases


def _tiny_tangent_arc_cases():
    """Exact isolated tangency and a sub-tolerance arc with two authored joins."""
    cases = []
    for tiny in (False, True):
        middle = math.degrees(0.5e-6)
        spans = (
            [(0.0, 90.0), (90.0, middle), (90.0 + middle, 90.0 - middle)]
            if tiny
            else [(0.0, 180.0)]
        )
        curves = [
            {
                "kind": "arc",
                "centre": [0.0, 0.0],
                "radius": 1.0,
                "start_deg": start,
                "sweep_deg": sweep,
                "outward": 1,
                "angle_start_deg": start,
                "angle_sweep_deg": sweep,
            }
            for start, sweep in spans
        ]
        wall = {
            "kind": "arc",
            "centre": [0.0, 0.0],
            "radius": 0.65,
            "start_deg": 0.0,
            "sweep_deg": 180.0,
            "outward": 1,
            "angle_start_deg": 0.0,
            "angle_sweep_deg": 180.0,
        }
        case = _regeneration_case(
            "tiny-authored-tangent-joins" if tiny else "exact-isolated-tangent",
            curves,
            [wall],
            (-2.25, 2.25, 0.75, 3.25),
            {"kind": "circle", "centre": [0.0, 0.0], "radius": 0.65},
            tangent_singleton="tiny-joins" if tiny else "exact",
        )
        case["radius"], case["allowance"] = 0.25, 0.1
        case["dro"] = {"step": 0.001, "decimals": 3, "scale": 1.0}
        case["paths"][0]["chain_geometry"].update(pitch_mm=0.75, offset=0.35)
        cases.append(case)
    return cases


def _finite_arc_side_cases():
    """Distinguish material inside a finite arc span from its clear end cap."""
    drill, allowance, pitch = 0.25, 0.25, 0.75
    curve = {
        "kind": "arc",
        "centre": [0.0, 0.0],
        "radius": 4.0,
        "start_deg": 30.0,
        "sweep_deg": 30.0,
        "outward": 1,
        "angle_start_deg": 30.0,
        "angle_sweep_deg": 30.0,
    }
    cases = []
    for control, start, sweep, step, decimals in (
        ("unsafe", 20.0, 50.0, 2.0, 0),
        ("safe-cap", 0.0, 40.0, 0.001, 3),
    ):
        wall = {
            **curve,
            "radius": 3.5,
            "start_deg": start,
            "sweep_deg": sweep,
            "angle_start_deg": start,
            "angle_sweep_deg": sweep,
        }
        wall_ends = [
            [
                wall["radius"] * math.cos(math.radians(angle)),
                wall["radius"] * math.sin(math.radians(angle)),
            ]
            for angle in (start, start + sweep)
        ]
        walls = [
            wall,
            *(
                {
                    "kind": "line",
                    "ends": [end, wall["centre"]],
                    "normal": [side * end[1] / wall["radius"], -side * end[0] / wall["radius"]],
                }
                for end, side in zip(wall_ends, (1, -1), strict=True)
            ),
        ]
        bounds = (
            (2.0 - drill, 3.6 + drill, 2.0 - drill, 3.6 + drill)
            if control == "unsafe"
            else (-10.0, 10.0, -10.0, curve["radius"] * math.sin(math.radians(45.0)) + drill)
        )
        name = f"finite-arc-side-{control}"
        case = _regeneration_case(
            name,
            [deepcopy(curve)],
            walls,
            bounds,
            {"kind": "sector", "arc": wall},
            finite_arc_side=control,
        )
        count = math.ceil(curve["radius"] * math.radians(curve["sweep_deg"]) / pitch)
        angles = [
            math.radians(curve["start_deg"] + i * curve["sweep_deg"] / count)
            for i in range(count + 1)
        ]
        points = [
            [curve["radius"] * math.cos(angle), curve["radius"] * math.sin(angle)]
            for angle in angles
        ]
        (path,) = _printed("S1:10", "rough", [(name, points)], bounded=True, kind="arc_table")[
            "paths"
        ]
        geometry = case["paths"][0]["chain_geometry"]
        geometry.update(pitch_mm=pitch, offset=drill + allowance)
        path.update(method="chain_drill", chain_geometry=geometry)
        case.update(
            paths=[path],
            radius=drill,
            allowance=allowance,
            dro={"step": step, "decimals": decimals, "scale": 1.0},
        )
        cases.append(case)
    return cases


def _finite_line_cap_cases():
    """187193:miter:30:0: real convex caps permit an inward authored-side snap."""
    junction = [-29.906261005050702, -18.892132020622505]
    curves = [
        {
            "kind": "line",
            "ends": [[-39.403207070833055, -26.227526721906212], junction],
            "normal": [-0.6112828917736424, 0.7914121721485293],
        },
        {
            "kind": "line",
            "ends": [junction, [-18.013967103070648, -17.287966895416226]],
            "normal": [-0.1336804271005234, 0.9910244918316709],
        },
    ]
    corner = [-29.7665323812725, -19.22645374589369]
    wall_ends = [
        [-45.59477582424309, -31.452111581366538],
        [-9.946042544639084, -16.55284520388322],
    ]
    walls = [
        {"kind": "line", "ends": [wall_ends[0], corner], "normal": curves[0]["normal"]},
        {"kind": "line", "ends": [corner, wall_ends[1]], "normal": curves[1]["normal"]},
    ]
    # The closure is deep in material, remote from the junction and both 12 mm legs.
    back = [corner[i] - 20.0 * sum(curve["normal"][i] for curve in curves) for i in range(2)]
    name = "finite-line-corner-cap"
    (path,) = _printed(
        "S1:10",
        "rough",
        [(name, [curves[0]["ends"][0], junction, curves[1]["ends"][1]])],
        bounded=True,
        kind="line_table",
    )["paths"]
    path.update(
        method="chain_drill",
        chain_geometry={
            "pitch_mm": 1.5,
            "offset": 0.35,
            "setup_origin": junction,
            "basis": [
                [0.7914121721485293, 0.6112828917736424],
                [-0.6112828917736424, 0.7914121721485293],
            ],
            "curves": curves,
            "walls": walls,
        },
    )
    return [
        {
            "name": name,
            "finite_line_cap": True,
            "junction": junction,
            "paths": [path],
            "bounds": {
                "x": [-99.90626100505071, 40.0937389949493],
                "y": [-88.89213202062251, 51.107867979377495],
                "z": [0.0, 3.0],
            },
            "radius": 0.25,
            "allowance": 0.1,
            "dro": {"step": 0.001, "decimals": 3, "scale": 1.0},
            "finished": {"kind": "polygon", "points": [corner, wall_ends[0], back, wall_ends[1]]},
        }
    ]


def _region_clearance_cases(scales=(1.0,)):
    """The observed concave cap gouge, with real closure or without it, in every D4 image."""
    cases = []
    polygon = [
        [3.0, 3.0],
        [13.0, 3.0],
        [13.0, -30.0],
        [-30.0, -30.0],
        [-30.0, 13.0],
        [3.0, 13.0],
    ]
    curves = [
        {"kind": "line", "ends": [[10.5, 4.5], [4.5, 4.5]], "normal": [0.0, 1.0]},
        {"kind": "line", "ends": [[4.5, 4.5], [4.5, 10.5]], "normal": [1.0, 0.0]},
    ]
    open_walls = [
        {"kind": "line", "ends": [[3.0, 3.0], [13.0, 3.0]], "normal": [0.0, 1.0]},
        {"kind": "line", "ends": [[3.0, 3.0], [3.0, 13.0]], "normal": [1.0, 0.0]},
    ]
    # These authored synthetic closing edges belong to the actual finite L solid.
    # Clockwise travel has material on the right, so its scrap normal is on the left.
    closed_walls = []
    for a, b in zip(polygon, polygon[1:] + polygon[:1], strict=True):
        length = math.dist(a, b)
        closed_walls.append(
            {
                "kind": "line",
                "ends": [a, b],
                "normal": [-(b[1] - a[1]) / length, (b[0] - a[0]) / length],
            }
        )
    rotations = (
        [[1, 0], [0, 1]],
        [[0, -1], [1, 0]],
        [[-1, 0], [0, -1]],
        [[0, 1], [-1, 0]],
    )
    translation = [20.0, -30.0]
    for closed in (False, True):
        for control in ("keeper", "refusal"):
            for scale in scales:
                for reflected in (False, True):
                    for turn, rotation in enumerate(rotations):
                        matrix = [[row[0] * (-1 if reflected else 1), row[1]] for row in rotation]

                        def vector(point, matrix=matrix):
                            return [sum(row[i] * point[i] for i in range(2)) for row in matrix]

                        def transformed_mm(point, vector=vector):
                            return [value + translation[i] for i, value in enumerate(vector(point))]

                        def transformed(point, transformed_mm=transformed_mm, scale=scale):
                            return [value / scale for value in transformed_mm(point)]

                        name = (
                            f"region-{'closed' if closed else 'open'}-{control}-{scale:g}"
                            f"-{int(reflected)}-{turn}"
                        )
                        nominal = [curves[0]["ends"][0], [4.5, 4.5], curves[1]["ends"][1]]
                        (path,) = _printed(
                            "S1:10",
                            "rough",
                            [(name, [transformed_mm(p) for p in nominal])],
                            bounded=True,
                        )["paths"]
                        geometry = {
                            "pitch_mm": 20.0,
                            "offset": 1.5 / scale,
                            "setup_origin": transformed([0.0, 0.0]),
                            "basis": [vector([1.0, 0.0]), vector([0.0, 1.0])],
                            "curves": deepcopy(curves),
                            "walls": deepcopy(closed_walls if closed else open_walls),
                        }
                        for wall in geometry["curves"] + geometry["walls"]:
                            wall["ends"] = [transformed(p) for p in wall["ends"]]
                            wall["normal"] = vector(wall["normal"])
                        path.update(method="chain_drill", chain_geometry=geometry)
                        high = 12.0 if control == "keeper" else 9.0
                        corners = [
                            transformed_mm([x, y]) for x in (-1.0, high) for y in (-1.0, high)
                        ]
                        cases.append(
                            {
                                "name": name,
                                "paths": [path],
                                "bounds": {
                                    **{
                                        key: [
                                            min(p[i] for p in corners),
                                            max(p[i] for p in corners),
                                        ]
                                        for i, key in enumerate(("x", "y"))
                                    },
                                    "z": [0.0, 3.0],
                                },
                                "radius": 1.0,
                                "allowance": 0.5,
                                "dro": {
                                    "step": 10.0 / scale,
                                    "decimals": 8 if scale != 1.0 else 0,
                                    "scale": scale,
                                },
                                "junction": transformed([4.5, 4.5]),
                                "finished": {
                                    "kind": "polygon",
                                    "points": [transformed_mm(p) for p in polygon],
                                },
                                "region_clearance": {
                                    "closed": closed,
                                    "control": control,
                                    "scale": scale,
                                    "matrix": matrix,
                                    "translation_mm": translation,
                                    "expected": transformed([10.0, 10.0]),
                                    "gouge": transformed([0.0, 0.0]),
                                },
                            }
                        )
    return cases


@pytest.mark.parametrize(
    "case", _region_clearance_cases(scales=(1.0, 25.4)), ids=lambda case: case["name"]
)
def test_bounded_regeneration_uses_actual_region_for_concave_cap_and_closed_loop(
    pure_chain_regeneration, case
):
    regenerate, unknown = pure_chain_regeneration
    if case["region_clearance"]["control"] == "refusal":
        with pytest.raises(unknown, match="no safe DRO-grid drill centre"):
            regenerate(case["paths"], case["bounds"], case["radius"], case["dro"])
        return
    ((entry, pieces),) = regenerate(case["paths"], case["bounds"], case["radius"], case["dro"])
    assert entry["regeneration"] == "true_curve"
    (point,) = [point for piece in pieces for point in piece]
    assert point["exact_xy"] == pytest.approx(case["junction"], abs=1e-6 / case["dro"]["scale"])
    assert point["dro_xy"] == pytest.approx(case["region_clearance"]["expected"], abs=1e-8)
    assert point["dro_xy"] != case["region_clearance"]["gouge"]
    # Independently: (10,10) is in the L's open scrap square, 7 mm from both walls;
    # the nearer (0,0) and its whole radius-1 disk are finished material.
    assert 10.0 - 3.0 - case["radius"] >= case["allowance"]
    assert case["radius"] < 3.0


def test_regeneration_compiles_identical_wall_packets_once(pure_chain_regeneration, monkeypatch):
    regenerate, unknown = pure_chain_regeneration
    case = next(
        case
        for case in _region_clearance_cases()
        if case["region_clearance"]["control"] == "refusal"
    )
    duplicate = deepcopy(case["paths"][0])
    duplicate["table"] += "-other"
    case["paths"].append(duplicate)
    original = chain_boundary.compile_clearance
    packets = []

    def counted(walls, tolerance):
        packets.append(walls)
        return original(walls, tolerance)

    monkeypatch.setattr(chain_boundary, "compile_clearance", counted)
    with pytest.raises(unknown, match="no safe DRO-grid drill centre"):
        regenerate(case["paths"], case["bounds"], case["radius"], case["dro"])
    assert len(packets) == 1


@pytest.mark.parametrize("missing", (False, True))
def test_regeneration_invalid_or_missing_wall_side_is_unknown(pure_chain_regeneration, missing):
    regenerate, unknown = pure_chain_regeneration
    case = _region_clearance_cases()[0]
    wall = case["paths"][0]["chain_geometry"]["walls"][0]
    if missing:
        wall.pop("normal")
        reason = "true chain geometry is incomplete"
    else:
        wall["normal"] = [1.0, 0.0]
        reason = "finished-region clearance is unknown"
    with pytest.raises(unknown, match=reason):
        regenerate(case["paths"], case["bounds"], case["radius"], case["dro"])


_REGENERATION_NATIVE = r"""
import importlib.util
import json
import math
import os
import sys
import FreeCAD, Part

V = FreeCAD.Vector
spec = importlib.util.spec_from_file_location("checkpoint_engine", os.environ["ENGINE"])
engine = importlib.util.module_from_spec(spec)
spec.loader.exec_module(engine)
directory = sys.argv[sys.argv.index("--") + 1]
with open(directory + "/cases.json", encoding="utf-8") as stream:
    cases = json.load(stream)
answers = []
fixture = Part.makeBox(5, 5, 3, V(72, 72, 0))
blank = Part.makeBox(70, 60, 3, V(0, -5, 0))


def wall_edge(wall):
    if wall["kind"] == "line":
        return Part.makeLine(*(V(*point, 0) for point in wall["ends"]))
    ends = sorted((wall["start_deg"], wall["start_deg"] + wall["sweep_deg"]))
    return Part.makeCircle(wall["radius"], V(*wall["centre"], 0), V(0, 0, 1), *ends)


def signed_finished_gap(point, finished):
    # Native distance to the actual finite solid; negative means finished material.
    centre = V(*point, 1.5)
    distance = Part.Vertex(centre).distToShape(finished.Shells[0])[0]
    return -distance if finished.isInside(centre, 1e-9, False) else distance


def endpoint_candidates(case, piece, walls, finished, exacts=None):
    # Measure an exhaustive grid square, without calling any engine safety helper.
    step, decimals = case["dro"]["step"], case["dro"]["decimals"]
    drill, box = case["radius"], case["bounds"]
    results = []
    for exact in case["nearest"]["endpoints"] if exacts is None else exacts:
        # Authored targets can be interior holes or shared table endpoints.
        matches = [i for i, point in enumerate(piece)
                   if math.dist(point["exact_xy"], exact) <= 1e-9]
        if not matches and exacts is not None:
            results.append({"missing": True, "exact_xy": exact})
            continue
        assert matches, case["name"]
        index = matches[0]
        assert all(piece[i]["dro_xy"] == piece[index]["dro_xy"] for i in matches), case["name"]
        nominal = Part.Vertex(V(*exact, 0))
        nominal_gaps = [nominal.distToShape(wall)[0] for wall in walls]
        others = [point["dro_xy"] for i, point in enumerate(piece) if i not in matches]
        # Integer grid bounds derive from a symmetric metric window, not the
        # snapper's floor/base/offset loops. Reverse enumeration forbids relying
        # on the first candidate or reproducing its point-sorting tie-break.
        spans = [
            range(math.floor((value + 3 * step) / step),
                  math.ceil((value - 3 * step) / step) - 1, -1)
            for value in exact
        ]
        candidates = []
        for x in spans[0]:
            for y in spans[1]:
                point = [round(x * step, decimals), round(y * step, decimals)]
                vertex = Part.Vertex(V(*point, 0))
                candidates.append({
                    "point": point,
                    "distance_squared": sum((point[i] - exact[i]) ** 2 for i in range(2)),
                    "wall_gaps": [vertex.distToShape(wall)[0] for wall in walls],
                    "bound_gaps": [
                        point[0] - drill - box["x"][0], box["x"][1] - point[0] - drill,
                        point[1] - drill - box["y"][0], box["y"][1] - point[1] - drill,
                    ],
                    "scrap_signed_gap": signed_finished_gap(point, finished),
                    "minimum_web": min(math.dist(point, other) - 2 * drill for other in others),
                })
        actual = piece[index]["dro_xy"]
        cylinder = Part.makeCylinder(drill, 3, V(*actual, 0))
        results.append({
            "index": index,
            "indices": matches,
            "nominal_wall_gaps": nominal_gaps,
            "candidates": candidates,
            "actual_cylinder_wall_gaps": [cylinder.distToShape(wall)[0] for wall in walls],
            "actual_cylinder_minimum_web": min(
                cylinder.distToShape(Part.makeCylinder(drill, 3, V(*other, 0)))[0]
                for other in others
            ),
        })
    return results


def unsnappable_interval_oracle(case, walls, finished):
    # A Cartesian lattice enumeration covers every y of the retained line,
    # independently of choices(), backed_end(), and their half-step samples.
    drill, step = case["radius"], case["dro"]["step"]
    inner = [[lo + drill, hi - drill] for lo, hi in (case["bounds"][key] for key in ("x", "y"))]
    grid = [range(math.ceil(lo / step), math.floor(hi / step) + 1) for lo, hi in inner]
    witness = Part.Vertex(V(10.0, 4.0, 0))
    intervals = []
    for path in case["paths"]:
        if path["table"] not in case["bad_tables"]:
            continue
        curve = path["chain_geometry"]["curves"][0]
        a, b = curve["ends"]
        spans = [
            range(math.ceil(max(lo, min(a[i], b[i]) - 3 * step) / step),
                  math.floor(min(hi, max(a[i], b[i]) + 3 * step) / step) + 1)
            for i, (lo, hi) in enumerate(inner)
        ]
        candidates = []
        for x in spans[0]:
            for y in spans[1]:
                point = [x * step, y * step]
                vertex = Part.Vertex(V(*point, 0))
                candidates.append({
                    "point": point,
                    "wall_gap": vertex.distToShape(walls[0])[0],
                    "scrap_signed_gap": signed_finished_gap(point, finished),
                })
        intervals.append({
            "table": path["table"],
            "nominal_wall_gaps": [
                Part.Vertex(V(*point, 0)).distToShape(walls[0])[0] for point in (a, b)
            ],
            "candidates": candidates,
        })
    return {
        "global_grid_count": len(grid[0]) * len(grid[1]),
        "safe_witness": {
            "wall_gaps": [witness.distToShape(wall)[0] for wall in walls],
            "scrap_signed_gap": signed_finished_gap([10.0, 4.0], finished),
        },
        "intervals": intervals,
    }


def clipped_count_oracle(case, walls, finished, bounds):
    # Enumerate endpoint grid neighbourhoods independently of engine safe()/sample().
    # Their whole three-step window is included, not just the eventual printed pair.
    drill, step, box = case["radius"], case["dro"]["step"], case["bounds"]
    endpoints = [[0.0, 0.35], [case["count_span"], 0.35]]
    candidates = []
    for endpoint in endpoints:
        safe = []
        for ix in range(round(endpoint[0] / step) - 3, round(endpoint[0] / step) + 4):
            for iy in range(round(endpoint[1] / step) - 3, round(endpoint[1] / step) + 4):
                point = [round(ix * step, 3), round(iy * step, 3)]
                if not all(box[key][0] + drill - 1e-6 <= point[i]
                           <= box[key][1] - drill + 1e-6 for i, key in enumerate(("x", "y"))):
                    continue
                if any(Part.Vertex(V(*point, 0)).distToShape(wall)[0] < 0.35 - 1e-9
                       for wall in walls):
                    continue
                if signed_finished_gap(point, finished) < drill + case["allowance"] - 1e-9:
                    continue
                safe.append(point)
        candidates.append(safe)
    proof = {
        "endpoints": endpoints,
        "candidates": candidates,
        "maximum_web": max(math.dist(a, b) - 2 * drill
                           for a in candidates[0] for b in candidates[1]),
    }
    if case["count_span"] == 0.5:
        # An authored witness proves existence, not a required production tie-break.
        witness = [[0.0, 0.35], [0.5, 0.352]]
        cylinders = [Part.makeCylinder(drill, 3, V(*point, 0)) for point in witness]
        proof["witness"] = witness
        proof["witness_evidence"] = [{
            "wall_gaps": [Part.Vertex(V(*point, 0)).distToShape(wall)[0] for wall in walls],
            "finished_gap": cylinder.distToShape(finished)[0],
            "finished_volume": cylinder.common(finished).Volume,
            "outside_bounds_volume": cylinder.cut(bounds).Volume,
        } for point, cylinder in zip(witness, cylinders)]
        proof["witness_native_web"] = cylinders[0].distToShape(cylinders[1])[0]
        proof["witness_overlap_volume"] = cylinders[0].common(cylinders[1]).Volume
    return proof


def signed_boundary_oracle(case, finished):
    # Exhaust a generous +/-10 grid-index square. Signed half-plane/radial
    # distances are authored geometry, not unsigned OCC wall distance or safe().
    family = case["signed_boundary"]["family"]
    matrix = case["signed_boundary"]["matrix"]
    drill, step = case["radius"], case["dro"]["step"]
    candidates = []
    for ix in range(-10, 11):
        for iy in range(-10, 11):
            point = [ix * step, iy * step]
            if not all(case["bounds"][key][0] + drill - 1e-9 <= point[i]
                       <= case["bounds"][key][1] - drill + 1e-9
                       for i, key in enumerate(("x", "y"))):
                continue
            # D4 inverse is the transpose, independent of production normals.
            canonical = [sum(matrix[j][i] * point[j] for j in range(2)) for i in range(2)]
            wall_signed = canonical[1] if family == "line" else math.hypot(*canonical) - 0.5
            candidates.append({
                "point": point,
                "curve_signed": (
                    canonical[1] - 1.0 if family == "line" else math.hypot(*canonical) - 1.0
                ),
                "finished_cylinder_signed_gap": wall_signed - drill,
                "native_finished_signed_gap": signed_finished_gap(point, finished),
                "native_finished_inside": finished.isInside(V(*point, 1.5), 1e-9, False),
                "native_finished_volume": Part.makeCylinder(
                    drill, 3, V(*point, 0)
                ).common(finished).Volume,
            })
    return candidates


def finite_arc_side_oracle(case, pieces, walls, finished):
    # Supporting-circle sign applies only when the radial projection lies on
    # the finite finished arc. Beyond it, independently measure its real caps.
    geometry = case["paths"][0]["chain_geometry"]
    (curve,) = geometry["curves"]
    arc = case["finished"]["arc"]
    drill, step, decimals = case["radius"], case["dro"]["step"], case["dro"]["decimals"]
    cap_points = [
        [arc["centre"][0] + arc["radius"] * math.cos(math.radians(angle)),
         arc["centre"][1] + arc["radius"] * math.sin(math.radians(angle))]
        for angle in (arc["start_deg"], arc["start_deg"] + arc["sweep_deg"])
    ]
    inner = [[case["bounds"][key][0] + drill, case["bounds"][key][1] - drill] for key in ("x", "y")]
    bound_indices = [[math.ceil(lo / step), math.floor(hi / step)] for lo, hi in inner]
    if case["finite_arc_side"] == "unsafe":
        target = [
            curve["centre"][0] + curve["radius"] * math.cos(math.radians(45.0)),
            curve["centre"][1] + curve["radius"] * math.sin(math.radians(45.0)),
        ]
        spans = [range(lo, hi + 1) for lo, hi in bound_indices]
    else:
        y = inner[1][1]
        target = [
            curve["centre"][0] + math.sqrt(curve["radius"]**2 - (y - curve["centre"][1])**2),
            y,
        ]
        # Exhaust +/-10 steps, rather than mirror the production three-step loop.
        spans = [
            range(math.floor((value + 10 * step) / step),
                  math.ceil((value - 10 * step) / step) - 1, -1)
            for value in target
        ]
    nominal = Part.Vertex(V(*target, 0))
    nominal_gaps = [nominal.distToShape(wall)[0] for wall in walls]
    points = [point for piece in pieces for point in piece]
    others = [point["dro_xy"] for point in points[:-1]]
    candidates = []
    for ix in spans[0]:
        for iy in spans[1]:
            point = [round(ix * step, decimals), round(iy * step, decimals)]
            if not all(lo - 1e-9 <= point[i] <= hi + 1e-9 for i, (lo, hi) in enumerate(inner)):
                continue
            radial = math.dist(point, arc["centre"])
            angle = math.degrees(
                math.atan2(point[1] - arc["centre"][1], point[0] - arc["centre"][0])
            )
            progress = ((angle - arc["start_deg"]) if arc["sweep_deg"] > 0
                        else (arc["start_deg"] - angle)) % 360.0
            projected = progress <= abs(arc["sweep_deg"]) + 1e-12
            closest_cap = min(cap_points, key=lambda cap: math.dist(point, cap))
            cap_gap = math.dist(point, closest_cap) - drill
            cap_projection = sum(
                (point[i] - arc["centre"][i]) * (closest_cap[i] - arc["centre"][i])
                for i in range(2)
            ) / arc["radius"]
            signed_gap = arc["outward"] * (radial - arc["radius"]) - drill if projected else cap_gap
            vertex = Part.Vertex(V(*point, 0))
            candidate = {
                "point": point,
                "distance_squared": sum((point[i] - target[i])**2 for i in range(2)),
                "projection_within_finite_wall": projected,
                "projection_strictly_inside_finite_wall": 0.0 < progress < abs(arc["sweep_deg"]),
                "authored_circle_signed_side": curve["outward"] * (
                    math.dist(point, curve["centre"]) - curve["radius"]
                ),
                "finite_arc_signed_cylinder_gap": signed_gap,
                "finite_cap_cylinder_gap": cap_gap,
                "closest_cap_radial_projection": cap_projection,
                "native_finished_signed_gap": signed_finished_gap(point, finished),
                "wall_gaps": [vertex.distToShape(wall)[0] for wall in walls],
                "bound_gaps": [
                    gap for i, (lo, hi) in enumerate(inner)
                    for gap in (point[i] - lo, hi - point[i])
                ],
                "minimum_web": min(
                    (math.dist(point, other) - 2 * drill for other in others), default=None
                ),
            }
            if case["finite_arc_side"] == "unsafe":
                candidate["native_finished_volume"] = Part.makeCylinder(
                    drill, 3, V(*point, 0)
                ).common(finished).Volume
            candidates.append(candidate)
    return {"target": target, "bound_grid_indices": bound_indices,
            "nominal_wall_gaps": nominal_gaps, "candidates": candidates}


def finite_line_cap_oracle(case, pieces, walls, finished):
    # OCC measures the actual finite material; authored infinite sides are evidence,
    # never a safety predicate. No production snap/side/gap helper participates.
    geometry = case["paths"][0]["chain_geometry"]
    target, drill, step = case["junction"], case["radius"], case["dro"]["step"]
    points = [point for piece in pieces for point in piece]
    indices = [i for i, point in enumerate(points)
               if math.dist(point["exact_xy"], target) <= 1e-9]
    others = [point["dro_xy"] for i, point in enumerate(points) if i not in indices]
    nominal = Part.Vertex(V(*target, 0))
    nominal_gaps = [nominal.distToShape(wall)[0] for wall in walls]
    spans = [
        range(math.floor((value + 10 * step) / step),
              math.ceil((value - 10 * step) / step) - 1, -1)
        for value in target
    ]
    candidates = []
    for ix in spans[0]:
        for iy in spans[1]:
            point = [round(index * step, case["dro"]["decimals"]) for index in (ix, iy)]
            vertex = Part.Vertex(V(*point, 0))
            projections = []
            for spec in geometry["walls"]:
                a, b = spec["ends"]
                projections.append(sum((point[i] - a[i]) * (b[i] - a[i])
                                       for i in range(2)) / math.dist(a, b)**2)
            candidates.append({
                "point": point,
                "distance_squared": sum((point[i] - target[i])**2 for i in range(2)),
                "wall_projection_fractions": projections,
                "authored_line_signed_sides": [
                    sum((point[i] - curve["ends"][0][i]) * curve["normal"][i]
                        for i in range(2)) for curve in geometry["curves"]
                ],
                "native_finished_signed_gap": signed_finished_gap(point, finished),
                "wall_gaps": [vertex.distToShape(wall)[0] for wall in walls],
                "bound_gaps": [
                    gap for i, key in enumerate(("x", "y"))
                    for gap in (point[i] - drill - case["bounds"][key][0],
                                case["bounds"][key][1] - point[i] - drill)
                ],
                "minimum_web": min(
                    (math.dist(point, other) - 2 * drill for other in others), default=None
                ),
            })
    actual_cylinders = [
        Part.makeCylinder(drill, 3, V(*points[i]["dro_xy"], 0)) for i in indices
    ]
    return {
        "target": target, "indices": indices, "nominal_wall_gaps": nominal_gaps,
        "candidates": candidates,
        "actual_cylinders": [{
            "wall_gaps": [cylinder.distToShape(wall)[0] for wall in walls],
            "finished_gap": cylinder.distToShape(finished)[0],
            "finished_volume": cylinder.common(finished).Volume,
            "minimum_web": min(
                (cylinder.distToShape(Part.makeCylinder(drill, 3, V(*other, 0)))[0]
                 for other in others), default=None
            ),
        } for cylinder in actual_cylinders],
    }


def region_clearance_oracle(case, walls, finished):
    # Enumerate the entire eroded box; OCC's actual L solid, not a side predicate,
    # decides which coarse-grid cylinders are in scrap and preserve the allowance.
    drill, step = case["radius"], case["dro"]["step"]
    box = case["bounds"]
    spans = [
        range(math.ceil((box[key][0] + drill) / step),
              math.floor((box[key][1] - drill) / step) + 1)
        for key in ("x", "y")
    ]
    candidates = []
    for x in spans[0]:
        for y in spans[1]:
            point = [x * step, y * step]
            cylinder = Part.makeCylinder(drill, 3, V(*point, 0))
            candidates.append({
                "point": point,
                "centre_gap": signed_finished_gap(point, finished),
                "finished_gap": cylinder.distToShape(finished)[0],
                "finished_volume": cylinder.common(finished).Volume,
                "wall_gaps": [Part.Vertex(V(*point, 0)).distToShape(wall)[0] for wall in walls],
            })
    gouge = case["region_clearance"]["gouge"]
    return {
        "candidates": candidates,
        "gouge_inside": finished.isInside(V(*gouge, 1.5), 1e-9, False),
        "gouge_volume": Part.makeCylinder(drill, 3, V(*gouge, 0)).common(finished).Volume,
    }


for case in cases:
    geometry = case["paths"][0]["chain_geometry"]
    wall_specs = (
        [wall for path in case["paths"] for wall in path["chain_geometry"]["walls"]]
        if "nearest" in case else geometry["walls"]
    )
    walls = [wall_edge(wall) for wall in wall_specs]
    protected = case["finished"]
    if protected["kind"] == "circle":
        finished = Part.makeCylinder(protected["radius"], 3, V(*protected["centre"], 0))
    elif protected["kind"] == "sector":
        arc = wall_edge(protected["arc"])
        first, last = (vertex.Point for vertex in arc.Vertexes)
        centre = V(*protected["arc"]["centre"], 0)
        finished = Part.Face(Part.Wire([
            arc, Part.makeLine(last, centre), Part.makeLine(centre, first),
        ])).extrude(V(0, 0, 3))
    else:
        vertices = [V(*point, 0) for point in protected["points"]]
        finished = Part.Face(Part.makePolygon(vertices + [vertices[0]])).extrude(V(0, 0, 3))
        if protected["kind"] == "arc-join":
            circle = protected["circle"]
            finished = finished.fuse(
                Part.makeCylinder(circle["radius"], 3, V(*circle["centre"], 0))
            ).removeSplitter()
    assert finished.isValid(), case["name"]
    box = case["bounds"]
    bounds = Part.makeBox(box["x"][1] - box["x"][0], box["y"][1] - box["y"][0],
                          3, V(box["x"][0], box["y"][0], 0))
    details = {}
    if "checkpoints" in case:
        # Supply explicit native state at the checkpoint seam. Each control
        # gets a fresh setup/op; only that case's paths share its web constraints.
        # The production clip, full-radius guard, errors and sketch all run.
        op = {
            "subject": "S1:10",
            "do": "rough_profile",
            "radius_mm": case["radius"],
            "rough_allowance_mm": 0.0,
            "to_z": 0.0,
            "stock_removal_bounds": box,
            "contour": {"method": "chain_drill", "pitch_mm": geometry["pitch_mm"]},
            "checkpoints": case["checkpoints"],
        }
        setup = engine._Setup(None, {"id": "S1", "ops": [op]}, held=blank)
        setup.matrix = FreeCAD.Matrix()
        setup.finished = setup.protected = finished
        setup.part = blank
        setup.box = engine._bbox(blank)
        setup.stock_states = [blank]
        setup.cuts = {id(op): (blank, None, None)}
        setup.fixture = [{
            "name": "fixture",
            "envelope": fixture,
            "envelope_bbox": engine._bbox(fixture),
            "subjects": "all",
        }]
        setup.fixture_ready = True
        facts = {}
        setup._checkpoint_facts(op, facts)
        setup._finish_checkpoints([])
        entries = facts["checkpoint_clips"]["paths"]
        entry = entries[0] if len(entries) == 1 else None
        pieces = [piece for entry in entries for piece in entry["pieces"]]
        sketch_paths, waypoints, sketch_debts = setup._clipped_sketch({})
        details = {
            "facts": facts,
            "rows": op["checkpoints"]["rows"],
            "checkpoint_paths": op["checkpoints"]["paths"],
            "table_reason": op["checkpoints"].get("reason"),
            "sketch_paths": sketch_paths,
            "waypoints": waypoints,
            "sketch_debts": sketch_debts,
        }
        if "unsnappable" in case:
            details["unsnappable_oracle"] = unsnappable_interval_oracle(case, walls, finished)
    else:
        try:
            regenerated = engine._Setup._regenerate_chain(
                case["paths"], box, case["radius"], case["dro"]
            )
        except engine._ClipUnknown as error:
            if not any(
                key in case for key in (
                    "signed_boundary", "finite_arc_side", "finite_line_cap", "region_clearance",
                )
            ):
                raise
            details["unknown_reason"] = str(error)
            regenerated = None
        if regenerated is None:
            entry, pieces = None, []
        elif "nearest" in case:
            entry = regenerated[0][0]
            pieces = [piece for _, table_pieces in regenerated for piece in table_pieces]
            details["entries"] = [table_entry for table_entry, _ in regenerated]
            details["repeat_matches"] = regenerated == engine._Setup._regenerate_chain(
                case["paths"], box, case["radius"], case["dro"]
            )
            points = [point for piece in pieces for point in piece]
            details["nearest"] = endpoint_candidates(case, points, walls, finished)
            if case["nearest"]["family"] == "arc-join-junction":
                details["line_nearest"] = endpoint_candidates(
                    case, points, walls, finished, case["paths"][0]["xy_mm"]
                )
        else:
            (entry, pieces), = regenerated
    evidence = []
    for piece in pieces:
        for point in piece:
            exact = Part.Vertex(V(*point["exact_xy"], 0))
            actual = Part.Vertex(V(*point["dro_xy"], 0))
            cylinder = Part.makeCylinder(case["radius"], 3, V(*point["dro_xy"], 0))
            evidence.append({
                "nominal_wall_gaps": [exact.distToShape(wall)[0] for wall in walls],
                "actual_wall_gaps": [actual.distToShape(wall)[0] for wall in walls],
                "finished_volume": cylinder.common(finished).Volume,
                "finished_gap": cylinder.distToShape(finished)[0],
                "outside_bounds_volume": cylinder.cut(bounds).Volume,
                "fixture_volume": cylinder.common(fixture).Volume,
            })
    if "signed_boundary" in case:
        details["signed_boundary_oracle"] = signed_boundary_oracle(case, finished)
        for proof, point in zip(evidence, (point for piece in pieces for point in piece)):
            actual = point["dro_xy"]
            matrix = case["signed_boundary"]["matrix"]
            canonical = [sum(matrix[j][i] * actual[j] for j in range(2)) for i in range(2)]
            radial = math.hypot(*canonical)
            proof["curve_signed"] = (
                canonical[1] - 1.0 if case["signed_boundary"]["family"] == "line" else radial - 1.0
            )
            proof["finished_cylinder_signed_gap"] = (
                canonical[1] if case["signed_boundary"]["family"] == "line" else radial - 0.5
            ) - case["radius"]
    if "count_span" in case:
        details["count_oracle"] = clipped_count_oracle(case, walls, finished, bounds)
        cylinders = [Part.makeCylinder(case["radius"], 3, V(*point["dro_xy"], 0))
                     for piece in pieces for point in piece]
        details["pair_evidence"] = [{
            "web": a.distToShape(b)[0],
            "overlap_volume": a.common(b).Volume,
        } for i, a in enumerate(cylinders) for b in cylinders[i + 1:]]
    if "finite_arc_side" in case:
        details["finite_arc_side_oracle"] = finite_arc_side_oracle(case, pieces, walls, finished)
    if "finite_line_cap" in case:
        details["finite_line_cap_oracle"] = finite_line_cap_oracle(case, pieces, walls, finished)
    if "region_clearance" in case:
        details["region_clearance_oracle"] = region_clearance_oracle(case, walls, finished)
    answers.append({"entry": entry, "evidence": evidence, **details})
with open(directory + "/answers.json", "w", encoding="utf-8") as stream:
    json.dump(answers, stream)
"""


@pytest.fixture(scope="module")
def regeneration_boundaries(tmp_path_factory, freecad_kernel):
    """One cheap native batch; no STEP import, stock-prefix rebuild or consumer model."""
    directory = tmp_path_factory.mktemp("regeneration-boundaries")
    cases = (
        _regeneration_cases()
        + _nearest_endpoint_cases()
        + _unsnappable_interval_cases()
        + _clipped_count_cases()
        + _signed_boundary_cases()
        + _tiny_tangent_arc_cases()
        + _finite_arc_side_cases()
        + _finite_line_cap_cases()
        + _region_clearance_cases()
    )
    (directory / "cases.json").write_text(json.dumps(cases), encoding="utf-8")
    script = directory / "probe.py"
    script.write_text(_REGENERATION_NATIVE, encoding="utf-8")
    process = subprocess.run(
        [freecad_kernel, str(script), "--", str(directory)],
        env={**os.environ, "ENGINE": str(ENGINE)},
        capture_output=True,
        text=True,
        errors="replace",
        timeout=60,
    )
    answers = directory / "answers.json"
    assert process.returncode == 0 and answers.exists(), (
        process.stdout[-2000:] + process.stderr[-2000:]
    )
    results = json.loads(answers.read_text(encoding="utf-8"))
    assert len(results) == len(cases)
    return list(zip(cases, results, strict=True))


@pytest.mark.parametrize("closed", (False, True))
@pytest.mark.parametrize("control", ("keeper", "refusal"))
@pytest.mark.parametrize("reflected", (False, True))
@pytest.mark.parametrize("turn", range(4))
def test_native_bounded_concave_corner_and_closed_region_coarse_grid(
    regeneration_boundaries, closed, control, reflected, turn
):
    case, result = next(
        (case, result)
        for case, result in regeneration_boundaries
        if case["name"]
        == f"region-{'closed' if closed else 'open'}-{control}-1-{int(reflected)}-{turn}"
    )
    oracle = result["region_clearance_oracle"]
    assert oracle["gouge_inside"] is True
    assert oracle["gouge_volume"] == pytest.approx(3 * math.pi * case["radius"] ** 2, abs=1e-7)
    required = case["radius"] + case["allowance"]
    legal = [
        candidate
        for candidate in oracle["candidates"]
        if candidate["centre_gap"] >= required - 1e-9
    ]
    if control == "refusal":
        assert legal == []
        assert result["entry"] is None and result["evidence"] == []
        assert "no safe DRO-grid drill centre" in result["unknown_reason"]
        return
    (nearest,) = legal
    assert nearest["point"] == pytest.approx(case["region_clearance"]["expected"], abs=1e-9)
    assert nearest["finished_volume"] <= 1e-7
    assert nearest["finished_gap"] >= case["allowance"] - LENGTH_TOLERANCE_MM
    _assert_regenerated_cylinders(case, result)
    (point,) = [point for piece in result["entry"]["pieces"] for point in piece]
    assert point["exact_xy"] == pytest.approx(case["junction"], abs=1e-9)
    assert point["dro_xy"] == nearest["point"]


@pytest.mark.parametrize("control", ("exact", "tiny-joins"))
def test_tangent_singleton_has_one_unique_actual_cylinder(regeneration_boundaries, control):
    case, result = next(
        (case, result)
        for case, result in regeneration_boundaries
        if case.get("tangent_singleton") == control
    )
    entry = result["entry"]
    assert "reason" not in entry and entry["regeneration"] == "true_curve"
    points = [point for piece in entry["pieces"] for point in piece]
    assert len(points) == len(result["evidence"]) == 1, result
    assert points[0]["dro_xy"] == pytest.approx([0.0, 1.0], abs=1e-9)
    assert points[0]["exact_xy"] == pytest.approx([0.0, 1.0], abs=LENGTH_TOLERANCE_MM)
    proof = result["evidence"][0]
    assert proof["finished_volume"] <= 1e-7
    assert proof["finished_gap"] >= case["allowance"] - 2 * LENGTH_TOLERANCE_MM
    assert proof["outside_bounds_volume"] <= 1e-7
    assert proof["fixture_volume"] <= 1e-7


@pytest.mark.parametrize("family", ("line", "arc"))
@pytest.mark.parametrize("reflected", (0, 1))
@pytest.mark.parametrize("turn", range(4))
def test_wrong_side_boundary_grid_reports_concrete_unknown(
    regeneration_boundaries,
    family,
    reflected,
    turn,
):
    case, result = next(
        (case, result)
        for case, result in regeneration_boundaries
        if case["name"] == f"signed-boundary-{family}-unsafe-{reflected}-{turn}"
    )
    # The before-fix failure must be the unsafe engine outcome, not an oracle
    # mismatch encountered before checking whether regeneration was refused.
    reason = result.get("unknown_reason", "")
    assert "no safe DRO-grid" in reason and "full-interval" in reason, result
    assert result["entry"] is None and result["evidence"] == []
    candidates = result["signed_boundary_oracle"]
    assert candidates
    assert not any(
        p["curve_signed"] >= -1e-9 and p["finished_cylinder_signed_gap"] >= -1e-9
        for p in candidates
    )
    for candidate in candidates:
        if family == "line":
            # The finite 3D shell includes Z faces: its inside distance is not
            # the depth below the infinite XY plane. Occupancy and signed
            # membership independently agree with that plane's side instead.
            plane_gap = candidate["finished_cylinder_signed_gap"] + case["radius"]
            assert candidate["native_finished_inside"] == (plane_gap < -1e-9)
            if plane_gap < -1e-9:
                assert candidate["native_finished_signed_gap"] < 0
            elif plane_gap > 1e-9:
                assert candidate["native_finished_signed_gap"] > 0
            else:
                assert candidate["native_finished_signed_gap"] == pytest.approx(
                    0.0, abs=LENGTH_TOLERANCE_MM
                )
            assert (candidate["native_finished_volume"] > 1e-7) == (
                candidate["finished_cylinder_signed_gap"] < -LENGTH_TOLERANCE_MM
            )
        else:
            assert candidate["native_finished_signed_gap"] - case["radius"] == pytest.approx(
                candidate["finished_cylinder_signed_gap"],
                abs=LENGTH_TOLERANCE_MM,
            )


@pytest.mark.parametrize("reflected", (0, 1))
@pytest.mark.parametrize("turn", range(4))
def test_safe_coarse_grid_boundary_control_stays_on_scrap_side(
    regeneration_boundaries,
    reflected,
    turn,
):
    case, result = next(
        (case, result)
        for case, result in regeneration_boundaries
        if case["name"] == f"signed-boundary-line-safe-{reflected}-{turn}"
    )
    safe = [
        p
        for p in result["signed_boundary_oracle"]
        if p["curve_signed"] >= -1e-9 and p["finished_cylinder_signed_gap"] >= -1e-9
    ]
    assert len(safe) >= 2
    _assert_regenerated_cylinders(case, result)
    assert len(result["evidence"]) >= 2
    for proof in result["evidence"]:
        assert proof["curve_signed"] >= -1e-9
        assert proof["finished_cylinder_signed_gap"] >= -1e-9


def test_finite_arc_in_span_wrong_side_grid_reports_concrete_unknown(
    regeneration_boundaries,
):
    case, result = next(
        (case, result)
        for case, result in regeneration_boundaries
        if case.get("finite_arc_side") == "unsafe"
    )
    # Fail on the old engine's unsafe acceptance before considering any oracle.
    reason = result.get("unknown_reason", "")
    assert "no safe DRO-grid" in reason and "full-interval" in reason, result
    assert result["entry"] is None and result["evidence"] == []
    oracle = result["finite_arc_side_oracle"]
    candidates = oracle["candidates"]
    assert candidates
    x_indices, y_indices = oracle["bound_grid_indices"]
    assert {tuple(candidate["point"]) for candidate in candidates} == {
        (ix * case["dro"]["step"], iy * case["dro"]["step"])
        for ix in range(x_indices[0], x_indices[1] + 1)
        for iy in range(y_indices[0], y_indices[1] + 1)
    }
    arc = case["finished"]["arc"]
    for candidate in candidates:
        assert candidate["projection_within_finite_wall"]
        assert candidate["projection_strictly_inside_finite_wall"]
        expected = math.dist(candidate["point"], arc["centre"]) - arc["radius"] - case["radius"]
        assert candidate["finite_arc_signed_cylinder_gap"] == pytest.approx(expected, abs=1e-9)
        assert expected < 0
        assert candidate["native_finished_signed_gap"] - case["radius"] == pytest.approx(
            expected, abs=LENGTH_TOLERANCE_MM
        )
        assert candidate["native_finished_volume"] > 1e-7
    required_centre_gap = case["radius"] + case["allowance"]
    assert not any(
        candidate["finite_arc_signed_cylinder_gap"] >= case["allowance"] - 1e-9
        and candidate["native_finished_signed_gap"] >= required_centre_gap - 1e-9
        for candidate in candidates
    )


def test_finite_arc_clear_cap_keeps_independently_nearest_grid_endpoint(
    regeneration_boundaries,
):
    case, result = next(
        (case, result)
        for case, result in regeneration_boundaries
        if case.get("finite_arc_side") == "safe-cap"
    )
    assert "unknown_reason" not in result, result
    _assert_regenerated_cylinders(case, result)
    entry, oracle = result["entry"], result["finite_arc_side_oracle"]
    (piece,) = entry["pieces"]
    assert len(piece) >= 2
    assert entry["dropped_ends"] == [False, True]
    assert piece[-1]["exact_xy"] == pytest.approx(oracle["target"], abs=1e-9)
    geometry = case["paths"][0]["chain_geometry"]
    required_centre_gap = case["radius"] + case["allowance"]
    legal = [
        candidate
        for candidate in oracle["candidates"]
        if min(candidate["bound_gaps"]) >= -1e-9
        and candidate["finite_arc_signed_cylinder_gap"] >= case["allowance"] - 1e-9
        and candidate["native_finished_signed_gap"] >= required_centre_gap - 1e-9
        and candidate["minimum_web"] > LENGTH_TOLERANCE_MM
        and all(
            actual >= required_centre_gap - 1e-9
            and actual >= min(nominal, geometry["offset"]) - 1e-9
            for nominal, actual in zip(
                oracle["nominal_wall_gaps"], candidate["wall_gaps"], strict=True
            )
        )
    ]
    assert len(legal) >= 2
    nearest = min(legal, key=lambda candidate: candidate["distance_squared"])
    runner_up = min(
        candidate["distance_squared"] for candidate in legal if candidate is not nearest
    )
    assert runner_up - nearest["distance_squared"] > 1e-6 * case["dro"]["step"] ** 2
    # Every omitted lattice point is >=10 steps away along one axis, proving
    # this strict metric winner globally nearest without pinning its coordinate.
    assert nearest["distance_squared"] < (10 * case["dro"]["step"]) ** 2
    assert piece[-1]["dro_xy"] == nearest["point"]
    assert nearest["projection_within_finite_wall"] is False
    assert nearest["authored_circle_signed_side"] < 0
    assert nearest["finite_cap_cylinder_gap"] >= case["allowance"]
    assert nearest["closest_cap_radial_projection"] > case["finished"]["arc"]["radius"]
    actual = result["evidence"][-1]
    assert actual["finished_gap"] == pytest.approx(
        nearest["native_finished_signed_gap"] - case["radius"], abs=1e-8
    )
    assert actual["finished_gap"] == pytest.approx(nearest["finite_cap_cylinder_gap"], abs=1e-8)
    assert actual["finished_gap"] >= case["allowance"] - LENGTH_TOLERANCE_MM
    assert actual["finished_volume"] <= 1e-7


def test_finite_line_corner_cap_keeps_independently_nearest_shared_junction(
    regeneration_boundaries,
):
    case, result = next(
        (case, result) for case, result in regeneration_boundaries if case.get("finite_line_cap")
    )
    assert "unknown_reason" not in result, result
    _assert_regenerated_cylinders(case, result)
    entry, oracle = result["entry"], result["finite_line_cap_oracle"]
    geometry = case["paths"][0]["chain_geometry"]
    assert [math.dist(*curve["ends"]) for curve in geometry["curves"]] == pytest.approx(
        [12.0, 12.0], abs=1e-9
    )
    assert [math.dist(*wall["ends"]) for wall in geometry["walls"]] == pytest.approx(
        [20.0, 20.0], abs=1e-9
    )
    assert entry["dropped_ends"] == [False, False]
    points = [point for piece in entry["pieces"] for point in piece]
    shared = [point for point in points if math.dist(point["exact_xy"], oracle["target"]) <= 1e-9]
    assert shared and len(shared) == len(oracle["indices"])
    assert all(point["overshoot"] is True for point in shared)
    required = case["radius"] + case["allowance"]
    legal = [
        candidate
        for candidate in oracle["candidates"]
        if min(candidate["bound_gaps"]) >= -1e-9
        and candidate["native_finished_signed_gap"] >= required - 1e-9
        and candidate["minimum_web"] > LENGTH_TOLERANCE_MM
        and all(
            actual >= required - 1e-9 and actual >= min(nominal, geometry["offset"]) - 1e-9
            for nominal, actual in zip(
                oracle["nominal_wall_gaps"], candidate["wall_gaps"], strict=True
            )
        )
    ]
    assert len(legal) >= 2
    nearest = min(legal, key=lambda candidate: candidate["distance_squared"])
    runner_up = min(
        candidate["distance_squared"] for candidate in legal if candidate is not nearest
    )
    assert runner_up - nearest["distance_squared"] > 1e-6 * case["dro"]["step"] ** 2
    # Omitted grid points are >=10 steps away on one axis: the winner is global.
    assert nearest["distance_squared"] < (10 * case["dro"]["step"]) ** 2
    assert all(point["dro_xy"] == nearest["point"] for point in shared)
    assert nearest["wall_projection_fractions"][0] > 1.0
    assert nearest["wall_projection_fractions"][1] < 0.0
    assert min(nearest["authored_line_signed_sides"]) < 0.0
    physical_gap = nearest["native_finished_signed_gap"] - case["radius"]
    assert physical_gap >= case["allowance"]
    assert physical_gap == pytest.approx(min(nearest["wall_gaps"]) - case["radius"], abs=1e-8)
    for index, cylinder in zip(oracle["indices"], oracle["actual_cylinders"], strict=True):
        assert points[index]["dro_xy"] == nearest["point"]
        assert cylinder["finished_gap"] == pytest.approx(physical_gap, abs=1e-8)
        assert cylinder["finished_volume"] <= 1e-7
        assert min(cylinder["wall_gaps"]) >= case["allowance"] - 1e-8
        assert cylinder["minimum_web"] > LENGTH_TOLERANCE_MM
        assert result["evidence"][index]["finished_gap"] == pytest.approx(physical_gap, abs=1e-8)


def _segment_gap(point, a, b):
    """Finite-segment distance by endpoint/projection tests, not wall normals."""
    length = math.dist(a, b)
    along = sum((point[i] - a[i]) * (b[i] - a[i]) for i in range(2)) / length
    if along <= 0:
        return math.dist(point, a)
    if along >= length:
        return math.dist(point, b)
    return abs((b[0] - a[0]) * (point[1] - a[1]) - (b[1] - a[1]) * (point[0] - a[0])) / length


def _assert_regenerated_cylinders(case, result):
    """Independent OCC finite-wall/solid oracles, not the snapping algorithm."""
    tol, step = LENGTH_TOLERANCE_MM, case["dro"]["step"]
    entry, geometry = result["entry"], case["paths"][0]["chain_geometry"]
    assert entry["regeneration"] == "true_curve"
    assert "reason" not in entry and entry["clip_points"] == []
    points = [point for piece in entry["pieces"] for point in piece]
    assert points and len(points) == len(result["evidence"])
    for piece in entry["pieces"]:
        for point in piece:
            exact, actual, model = (point[key] for key in ("exact_xy", "dro_xy", "model_xy"))
            assert point["generated"] is True and "after" not in point and "t" not in point
            reconstructed = [
                geometry["setup_origin"][axis]
                + sum(model[i] * geometry["basis"][i][axis] for i in range(2))
                for axis in range(2)
            ]
            assert exact == pytest.approx(reconstructed, abs=tol)
            assert all(abs(value / step - round(value / step)) < 1e-7 for value in actual)
            assert max(abs(a - b) for a, b in zip(exact, actual, strict=True)) <= 3 * step + tol
            if "angle_deg" in point:
                (curve,) = [curve for curve in geometry["curves"] if curve["kind"] == "arc"]
                assert math.dist(exact, curve["centre"]) == pytest.approx(curve["radius"], abs=tol)
                angle = math.radians(point["angle_deg"])
                assert exact == pytest.approx(
                    [
                        curve["centre"][0] + curve["radius"] * math.cos(angle),
                        curve["centre"][1] + curve["radius"] * math.sin(angle),
                    ],
                    abs=tol,
                )
            else:
                assert (
                    min(
                        _segment_gap(exact, *curve["ends"])
                        for curve in geometry["curves"]
                        if curve["kind"] == "line"
                    )
                    <= tol
                )
        # Actual full cylinders need webs, including between non-neighbouring holes.
        assert all(
            math.dist(a["dro_xy"], b["dro_xy"]) > 2 * case["radius"] + tol
            for i, a in enumerate(piece)
            for b in piece[i + 1 :]
        )
    for proof in result["evidence"]:
        assert proof["finished_volume"] <= 1e-7
        assert proof["finished_gap"] >= case["allowance"] - 2 * tol
        assert proof["outside_bounds_volume"] <= 1e-7
        assert proof["fixture_volume"] <= 1e-7
        for nominal, actual in zip(
            proof["nominal_wall_gaps"], proof["actual_wall_gaps"], strict=True
        ):
            assert actual >= min(nominal, geometry["offset"]) - 1e-9
            assert actual >= case["radius"] + case["allowance"] - 1e-9


def test_non_grid_boundaries_and_both_miters_have_safe_actual_cylinders(regeneration_boundaries):
    for case, result in regeneration_boundaries:
        if not ("boundary" in case or "miter" in case["name"]):
            continue
        _assert_regenerated_cylinders(case, result)
        (piece,) = result["entry"]["pieces"]
        assert len(piece) >= 3
        if "boundary" in case:
            assert result["entry"]["dropped_ends"] == [False, True]
            end = piece[-1]
            assert (
                math.dist(end["exact_xy"], case["boundary"]) > LENGTH_TOLERANCE_MM
                or math.dist(end["dro_xy"], end["exact_xy"]) > case["dro"]["step"]
            )
            angles = [point["angle_deg"] for point in piece]
            gaps = [
                30.0 * abs(math.radians(b - a)) for a, b in zip(angles, angles[1:], strict=False)
            ]
            assert gaps == pytest.approx([gaps[0]] * len(gaps), abs=2e-6)
            assert max(gaps) <= 4.2 + 2e-6
        else:
            assert result["entry"]["dropped_ends"] == [False, False]
            joins = [
                point for point in piece if math.dist(point["exact_xy"], case["junction"]) <= 1e-6
            ]
            assert len(joins) == 1 and joins[0]["overshoot"] is True
            split = piece.index(joins[0])
            for leg in (piece[: split + 1], piece[split:]):
                gaps = [
                    math.dist(a["exact_xy"], b["exact_xy"])
                    for a, b in zip(leg, leg[1:], strict=False)
                ]
                assert gaps == pytest.approx([gaps[0]] * len(gaps), abs=2e-6)
                assert max(gaps) <= 4.2 + 2e-6
            if case["name"] == "concave-90-miter":
                assert math.dist(joins[0]["exact_xy"], joins[0]["dro_xy"]) > case["dro"]["step"]


def test_clipped_lengths_and_short_junction_tail_preserve_actual_webs(regeneration_boundaries):
    for case, result in regeneration_boundaries:
        if "length" not in case and case["name"] != "short-junction-tail":
            continue
        _assert_regenerated_cylinders(case, result)
        (piece,) = result["entry"]["pieces"]
        if "length" in case:
            assert len(piece) == case["holes"]
            assert result["entry"]["dropped_ends"] == [True, True]
            assert all(
                -1e-6 <= point["exact_xy"][0] - 0.0001 <= case["length"] + 1e-6 for point in piece
            )
        else:
            assert result["entry"]["dropped_ends"] == [False, True]
            assert piece[-1]["exact_xy"] == pytest.approx(case["junction"], abs=1e-6)
            assert piece[-1]["overshoot"] is True
            assert (
                sum(math.dist(point["exact_xy"], case["junction"]) <= 1e-6 for point in piece) == 1
            )
        gaps = [
            math.dist(a["exact_xy"], b["exact_xy"]) for a, b in zip(piece, piece[1:], strict=False)
        ]
        if gaps:
            assert gaps == pytest.approx([gaps[0]] * len(gaps), abs=2e-6)
            assert max(gaps) <= 4.2 + 2e-6


def _assert_clipped_count_safety(case, result):
    _assert_regenerated_cylinders(case, result)
    points = [point for piece in result["entry"]["pieces"] for point in piece]
    for point in points:
        for axis, key in enumerate(("x", "y")):
            assert case["bounds"][key][0] - 1e-6 <= point["dro_xy"][axis] - case["radius"]
            assert point["dro_xy"][axis] + case["radius"] <= case["bounds"][key][1] + 1e-6
    for pair in result["pair_evidence"]:
        assert pair["web"] > 1e-6
        assert pair["overlap_volume"] <= 1e-7
    return points


def test_clipped_long_line_keeps_two_snapped_endpoint_holes_below_nominal_web_limit(
    regeneration_boundaries,
):
    case, result = next(
        (case, result) for case, result in regeneration_boundaries if case.get("count_span") == 0.5
    )
    proof = result["count_oracle"]
    witness = proof["witness"]
    assert case["count_span"] < 2 * case["radius"] + 1e-6
    assert math.dist(*witness) - 2 * case["radius"] > 1e-6
    assert proof["maximum_web"] > 1e-6
    assert proof["witness_native_web"] > 1e-6
    assert proof["witness_overlap_volume"] <= 1e-7
    for point, candidates, evidence in zip(
        witness, proof["candidates"], proof["witness_evidence"], strict=True
    ):
        assert point in candidates
        for axis, key in enumerate(("x", "y")):
            assert case["bounds"][key][0] + case["radius"] <= point[axis]
            assert point[axis] <= case["bounds"][key][1] - case["radius"]
        assert all(gap >= 0.35 - 1e-9 for gap in evidence["wall_gaps"])
        assert evidence["finished_gap"] >= 0.1 - 1e-9
        assert evidence["finished_volume"] <= 1e-7
        assert evidence["outside_bounds_volume"] <= 1e-7
    points = _assert_clipped_count_safety(case, result)
    assert len(points) == 2
    assert result["entry"]["dropped_ends"] == [True, True]
    assert points[0]["exact_xy"] == pytest.approx(proof["endpoints"][0], abs=1e-6)
    assert points[-1]["exact_xy"] == pytest.approx(proof["endpoints"][-1], abs=1e-6)


def test_clipped_long_line_without_feasible_endpoint_web_drops_free_tail(
    regeneration_boundaries,
):
    case, result = next(
        (case, result)
        for case, result in regeneration_boundaries
        if case.get("count_span") == 0.499
    )
    proof = result["count_oracle"]
    assert all(proof["candidates"])
    assert max(
        math.dist(a, b) - 2 * case["radius"]
        for a in proof["candidates"][0]
        for b in proof["candidates"][1]
    ) == pytest.approx(proof["maximum_web"], abs=1e-12)
    assert proof["maximum_web"] < 0
    points = _assert_clipped_count_safety(case, result)
    assert len(points) == 1
    assert result["entry"]["dropped_ends"] == [True, True]
    assert points[0]["exact_xy"] == pytest.approx(proof["endpoints"][0], abs=1e-6)


def test_a_clipped_360_chain_keeps_one_continuous_piece_across_zero(regeneration_boundaries):
    case, result = next(
        (case, result)
        for case, result in regeneration_boundaries
        if case["name"] == "closed-retained-seam"
    )
    _assert_regenerated_cylinders(case, result)
    entry = result["entry"]
    (piece,) = entry["pieces"]
    assert entry["dropped_ends"] == [True, True]
    angles = [point["angle_deg"] for point in piece]
    assert 290.0 < angles[0] < 310.0 < 360.0 < 410.0 < angles[-1] < 430.0
    assert all(a < b for a, b in zip(angles, angles[1:], strict=False))
    assert sum(abs(angle - 360.0) <= 1e-6 for angle in angles) == 1
    assert len({tuple(point["dro_xy"]) for point in piece}) == len(piece)
    gaps = [10.0 * math.radians(b - a) for a, b in zip(angles, angles[1:], strict=False)]
    assert max(gaps) <= 4.2 + 2e-6
    seam = angles.index(next(angle for angle in angles if abs(angle - 360.0) <= 1e-6))
    for leg in (gaps[:seam], gaps[seam:]):
        assert leg == pytest.approx([leg[0]] * len(leg), abs=2e-6)


def test_endpoint_grid_candidates_are_independently_safe_nearest_and_d4_equivariant(
    regeneration_boundaries,
):
    """Native finite solids decide safety; a unique metric minimum decides nearest.

    Exact grid equidistance is deliberately excluded. Repeated regeneration proves
    determinism without inventing a tie contract that could conflict with D4 symmetry.
    """
    cases = [(case, result) for case, result in regeneration_boundaries if "nearest" in case]
    families = {
        "line-crossing",
        "circle-crossing",
        "finite-arc-end",
        "convex-miter",
        "arc-join-junction",
    }
    assert len(cases) == 8 * len(families)
    for family in families:
        transforms = {
            tuple(tuple(row) for row in case["nearest"]["transform"])
            for case, _ in cases
            if case["nearest"]["family"] == family
        }
        assert len(transforms) == 8, family
    reference = {}
    for case, result in cases:
        shared_junction = case["nearest"].get("junction", False)
        piece = []
        evidence_start = 0
        for path, entry in zip(case["paths"], result["entries"], strict=True):
            (table_piece,) = entry["pieces"]
            assert len(table_piece) >= 3
            evidence_end = evidence_start + len(table_piece)
            _assert_regenerated_cylinders(
                {**case, "paths": [path]},
                {"entry": entry, "evidence": result["evidence"][evidence_start:evidence_end]},
            )
            evidence_start = evidence_end
            assert entry["dropped_ends"] == [False, not shared_junction]
            geometry = path["chain_geometry"]
            if (
                case["nearest"]["family"] == "arc-join-junction"
                and geometry["curves"][0]["kind"] == "line"
            ):
                assert path["kind"] == "line_table"
                assert entry["rows"] == len(path["ids"]) == len(path["xy_mm"]) == 4
                assert len(table_piece) == 4
                for point, exact in zip(table_piece, path["xy_mm"], strict=True):
                    assert point["exact_xy"] == pytest.approx(exact, abs=1e-9)
                    assert "angle_deg" not in point
            if shared_junction and len(geometry["curves"]) == 2:
                splits = [
                    i
                    for i, point in enumerate(table_piece)
                    if math.dist(point["exact_xy"], case["junction"]) <= 1e-9
                ]
                (split,) = splits
                assert 0 < split < len(table_piece) - 1
                assert table_piece[split]["overshoot"] is True
                legs = [table_piece[: split + 1], table_piece[split:]]
            else:
                legs = [table_piece]
            for curve, leg in zip(geometry["curves"], legs, strict=True):
                exact_gaps = [
                    math.dist(a["exact_xy"], b["exact_xy"])
                    if curve["kind"] == "line"
                    else curve["radius"] * abs(math.radians(b["angle_deg"] - a["angle_deg"]))
                    for a, b in zip(leg, leg[1:], strict=False)
                ]
                assert exact_gaps == pytest.approx([exact_gaps[0]] * len(exact_gaps), abs=2e-6)
                assert max(exact_gaps) <= geometry["pitch_mm"] + 2e-6
            piece.extend(table_piece)
        assert evidence_start == len(result["evidence"])
        assert result["repeat_matches"] is True, case["name"]
        geometry = case["paths"][0]["chain_geometry"]
        if shared_junction:
            (proof,) = result["nearest"]
            assert len(proof["indices"]) == len(case["paths"])
            if len(case["paths"]) == 2:
                end_index = len(result["entries"][0]["pieces"][0]) - 1
                assert proof["indices"] == [end_index, end_index + 1]
        else:
            assert [proof["indices"] for proof in result["nearest"]] == [[0], [len(piece) - 1]]
        for i, a in enumerate(piece):
            for b in piece[i + 1 :]:
                if math.dist(a["exact_xy"], b["exact_xy"]) <= LENGTH_TOLERANCE_MM:
                    assert a["dro_xy"] == b["dro_xy"]
                else:
                    assert math.dist(a["dro_xy"], b["dro_xy"]) > (
                        2 * case["radius"] + LENGTH_TOLERANCE_MM
                    )
        targets = list(zip(case["nearest"]["endpoints"], result["nearest"], strict=True))
        if case["nearest"]["family"] == "arc-join-junction":
            line_exacts = case["paths"][0]["xy_mm"]
            assert len(result["line_nearest"]) == len(line_exacts) == 4
            assert all(not proof.get("missing", False) for proof in result["line_nearest"]), (
                case["name"],
                result["line_nearest"],
            )
            assert [proof["index"] for proof in result["line_nearest"]] == list(range(4))
            targets.extend(zip(line_exacts, result["line_nearest"], strict=True))
        for exact, proof in targets:
            index = proof["index"]
            assert piece[index]["exact_xy"] == pytest.approx(exact, abs=1e-9), case["name"]
            candidates = proof["candidates"]
            assert len(candidates) == 36

            def safe(candidate, case=case, geometry=geometry, proof=proof):
                return (
                    min(candidate["bound_gaps"]) >= -1e-9
                    and candidate["scrap_signed_gap"] >= case["radius"] + case["allowance"] - 1e-9
                    and candidate["minimum_web"] > LENGTH_TOLERANCE_MM
                    and min(candidate["wall_gaps"]) >= case["radius"] + case["allowance"] - 1e-9
                    and all(
                        actual >= min(nominal, geometry["offset"]) - 1e-9
                        for nominal, actual in zip(
                            proof["nominal_wall_gaps"], candidate["wall_gaps"], strict=True
                        )
                    )
                )

            if shared_junction:
                # These translations make naive rounding unsafe: the finite native
                # incident walls, not an unconstrained grid tie-break, decide the hole.
                closest = min(candidates, key=lambda candidate: candidate["distance_squared"])
                assert not safe(closest), case["name"]

            legal = [candidate for candidate in candidates if safe(candidate)]
            assert len(legal) >= 2, case["name"]
            # Select by scalar distance alone, not production's (distance, point)
            # sorting. A strict runner-up margin makes floating ties irrelevant.
            nearest = min(legal, key=lambda candidate: candidate["distance_squared"])
            runner_up = min(
                candidate["distance_squared"] for candidate in legal if candidate is not nearest
            )
            step = case["dro"]["step"]
            assert runner_up - nearest["distance_squared"] > 1e-6 * step**2, case["name"]
            if (
                case["nearest"]["family"] == "arc-join-junction"
                and proof is not result["nearest"][0]
            ):
                # All four authored line holes have native-safe grid choices, but
                # none in the former one-step Euclidean disc. They must not cause
                # the full 12 mm leg to lose its free start or its interior holes.
                assert all(candidate["distance_squared"] > step**2 for candidate in legal)
            # Every omitted grid point is at least three steps away on one axis.
            # This winner is closer, proving global nearest, not just local nearest.
            assert nearest["distance_squared"] < (3 * step) ** 2, case["name"]
            assert piece[index]["dro_xy"] == nearest["point"], case["name"]
            assert all(piece[i]["dro_xy"] == nearest["point"] for i in proof["indices"])
            if case["nearest"]["family"] == "arc-join-junction" and proof is result["nearest"][0]:
                # Each table's nearest point under only its own native finite wall
                # is closer, but fails the OTHER incident wall. This requires the
                # global prepass to constrain both tables' shared commanded hole.
                for wall_index in range(len(proof["nominal_wall_gaps"])):
                    local = [
                        candidate
                        for candidate in candidates
                        if min(candidate["bound_gaps"]) >= -1e-9
                        and candidate["minimum_web"] > LENGTH_TOLERANCE_MM
                        and candidate["wall_gaps"][wall_index]
                        >= min(proof["nominal_wall_gaps"][wall_index], geometry["offset"]) - 1e-9
                    ]
                    local_nearest = min(local, key=lambda candidate: candidate["distance_squared"])
                    assert local_nearest["distance_squared"] < nearest["distance_squared"]
                    other_wall = 1 - wall_index
                    assert local_nearest["wall_gaps"][other_wall] < (
                        min(proof["nominal_wall_gaps"][other_wall], geometry["offset"]) - 1e-9
                    )
                    assert not safe(local_nearest)
            assert proof["actual_cylinder_wall_gaps"] == pytest.approx(
                [gap - case["radius"] for gap in nearest["wall_gaps"]], abs=1e-8
            )
            assert proof["actual_cylinder_minimum_web"] == pytest.approx(
                nearest["minimum_web"], abs=1e-8
            )
            assert proof["actual_cylinder_minimum_web"] > LENGTH_TOLERANCE_MM
            if case["nearest"]["family"] == "finite-arc-end" and index == len(piece) - 1:
                (curve,) = geometry["curves"]
                # A radial-only endpoint predicate would reject the true nearest
                # candidate even though the native finite wall/caps/solid allow it.
                assert math.dist(nearest["point"], curve["centre"]) < curve["radius"] - 1e-9
                assert min(nearest["wall_gaps"]) > geometry["offset"]

        family, matrix = case["nearest"]["family"], case["nearest"]["transform"]
        if matrix == [[1, 0], [0, 1]]:
            reference[family] = piece
        base = reference[family]
        assert len(piece) == len(base)
        for point, original in zip(piece, base, strict=True):
            for key in ("exact_xy", "dro_xy"):
                expected = [sum(row[i] * original[key][i] for i in range(2)) for row in matrix]
                assert point[key] == pytest.approx(expected, abs=1e-9), (case["name"], key)
            assert point["model_xy"] == pytest.approx(original["model_xy"], abs=1e-9)


def test_a_corner_miter_into_retained_scrap_is_legal_and_noted(engine, island):
    profile = _profile(3.0, MITER, tip=10.0, overshoot={"S1:10 finish line -X[2]"})
    result = engine.run(_job(engine, island, [profile], later=_clamped((35.0, 30.0)), west=WEST))
    facts = result["ops"]["S1:10"]
    assert facts["checkpoint_hits"] == 0 and facts["checkpoint_errors"] == [], facts
    assert facts["checkpoint_overshoot_ok"] == ["S1:10 finish line -X[2]"]
    # The builder credits the printed miter, so the later setup sees the notch.
    assert "stock_reason" not in result["setups"]["S2"], result["setups"]["S2"]


def test_the_same_miter_under_a_later_press_pad_is_an_error_naming_the_setup(engine, island):
    profile = _profile(3.0, MITER, tip=10.0, overshoot={"S1:10 finish line -X[2]"})
    # The pad spans y 49..51 over the miter's scrap, which reaches y 51.
    result = engine.run(_job(engine, island, [profile], later=_clamped((2.0, 50.0)), west=WEST))
    facts = result["ops"]["S1:10"]
    assert _later(facts) == {("S1:10 finish line -X[2]", "S2", "clamp press")}, facts
    assert facts["checkpoint_hits"] == 1
    (error,) = facts["checkpoint_errors"]
    assert error["area_mm2"] > 1.0, error
    # A row with an error keeps it: no operator OK note.
    assert facts["checkpoint_overshoot_ok"] == []


def test_an_unresolved_later_contact_leaves_the_rows_unknown(engine, island):
    profile = _profile(3.0, MITER, tip=10.0, overshoot={"S1:10 finish line -X[2]"})
    later = _clamped((35.0, 30.0), gaps=["a toe clamp is not drawn"])
    result = engine.run(_job(engine, island, [profile], later=later, west=WEST))
    facts = result["ops"]["S1:10"]
    assert facts["checkpoint_hits"] == "unknown", facts
    assert (
        "later setup S2 has undrawn components (a toe clamp is not drawn)"
        in (facts["checkpoint_reason"])
    )
    assert facts["checkpoint_overshoot_ok"] == []


def test_a_run_out_that_parts_the_stock_is_refused_by_the_held_split_check(engine, island):
    # A 4 mm corridor leaves a 1 mm web west of it joining the gripped frame; run-outs
    # west across it at both wall ends cut a free strip out of the frame.
    walled = [("line -X", [(3.0, 5.0), (3.0, 45.0)])]
    run_out = [("line -X", [(-3.0, 5.0), (3.0, 5.0), (3.0, 45.0), (-3.0, 45.0)])]
    plain, parted = engine.run(
        {
            "jobs": [
                _job(engine, island, [_profile(2.0, walled)], west=WEST),
                _job(engine, island, [_profile(2.0, run_out)], west=WEST),
            ]
        }
    )["results"]
    assert "stock_reason" not in plain["setups"]["S2"], plain["setups"]["S2"]
    reason = parted["setups"]["S2"]["stock_reason"]
    assert "S1:10: removing its claimed clearance splits an input stock piece" in reason, reason
    facts = parted["ops"]["S1:10"]
    # Rule A′ cannot judge the rows against a later setup whose entry stock is unknown.
    assert facts["checkpoint_hits"] == "unknown"
    assert "later setup S2's entry stock is unknown" in facts["checkpoint_reason"]


def _coordinate_free_checkpoint_job(engine, island):
    """The physical miter above, followed by explicitly contact-free manual work."""
    profile = _profile(3.0, MITER, tip=10.0, overshoot={"S1:10 finish line -X[2]"})
    job = _job(engine, island, [profile], west=WEST)
    later = job["setups"][1]
    later.pop("frame")
    later["hold"] = {
        "kind": "unknown",
        "fixture_kind": "unknown",
        "contact_model": "none",
        "reason": "Coordinate-free manual work; no fixture contacts are declared",
        "debts": [],
        "gaps": [],
        "refused_fields": [],
    }
    later["preservation_ledger"] = [
        {"subject": "S2:10", "do": "inspect", "effect": "metadata"},
        {"subject": "S2:20", "do": "coating", "effect": "unmodeled"},
        {"subject": "S2:30", "do": "release", "effect": "metadata"},
    ]
    return job


def test_coordinate_free_manual_descendants_do_not_add_future_frame_unknown(engine, island):
    base = _coordinate_free_checkpoint_job(engine, island)
    ledger = base["setups"][1]["preservation_ledger"]
    cases, jobs = [], []
    for entries in ([ledger[0]], [ledger[1]], [ledger[2]], ledger):
        for hold in ({"contact_model": "none"}, base["setups"][1]["hold"]):
            job = deepcopy(base)
            job["setups"][1].update(preservation_ledger=deepcopy(entries), hold=deepcopy(hold))
            cases.append((entries, hold))
            jobs.append(job)
    results = engine.run({"jobs": jobs})["results"]
    for case, result in zip(cases, results, strict=True):
        assert result["status"] == "ok", (case, result)
        facts = result["ops"]["S1:10"]
        assert facts["checkpoint_count"] == 3, (case, facts)
        assert facts["checkpoint_hits"] == 0 and facts["checkpoint_errors"] == [], (case, facts)
        assert "checkpoint_reason" not in facts, (case, facts)
        assert facts["checkpoint_overshoot_ok"] == ["S1:10 finish line -X[2]"], (case, facts)
        # Exempting a contact consumer does not invent a usable frame or propagate stock.
        later = result["setups"]["S2"]
        assert later["reason"] == "numeric setup frame is unknown", (case, later)
        assert later["fixture_reason"] == later["reason"], (case, later)
        assert "stock_bbox_mm" not in later, (case, later)


def test_coordinate_free_checkpoint_exemption_requires_an_exact_complete_ledger(engine, island):
    base = _coordinate_free_checkpoint_job(engine, island)
    inspect = {"subject": "S2:10", "do": "inspect", "effect": "metadata"}
    ledgers = {
        "null ledger": None,
        "non-list ledger": inspect,
        "empty ledger": [],
        "non-entry ledger": ["inspect"],
        "missing effect": [{"subject": "S2:10", "do": "inspect"}],
        "foreign subject": [{**inspect, "subject": "S3:10"}],
        "empty subject suffix": [{**inspect, "subject": "S2:"}],
        "non-string subject": [{**inspect, "subject": 10}],
        "duplicate subject": [inspect, {**inspect, "do": "release"}],
        "hidden geometry": [{**inspect, "stock_removal_bounds": deepcopy(BOX)}],
        "unknown action": [{**inspect, "do": "unknown"}],
        "unknown effect": [{**inspect, "effect": "unknown"}],
        "native inspect": [{**inspect, "effect": "native"}],
        "unmodeled inspect": [{**inspect, "effect": "unmodeled"}],
        "metadata coating": [{**inspect, "do": "coating"}],
        "mixed unknown action": [
            inspect,
            {"subject": "S2:20", "do": "unknown", "effect": "unmodeled"},
        ],
    }
    for action in ("deburr", "fit", "scribe"):
        for effect in ("metadata", "unmodeled"):
            ledgers[f"{effect} {action}"] = [{**inspect, "do": action, "effect": effect}]
    jobs = []
    for ledger in ledgers.values():
        job = deepcopy(base)
        job["setups"][1]["preservation_ledger"] = ledger
        jobs.append(job)
    missing = deepcopy(base)
    missing["setups"][1].pop("preservation_ledger")
    jobs.append(missing)
    results = engine.run({"jobs": jobs})["results"]
    for name, result in zip([*ledgers, "missing ledger"], results, strict=True):
        facts = result["ops"]["S1:10"]
        assert facts["checkpoint_hits"] == "unknown", (name, facts)
        assert facts["checkpoint_errors"] == [], (name, facts)
        assert "later setup S2's frame is unusable" in facts["checkpoint_reason"], (name, facts)
        assert facts["checkpoint_overshoot_ok"] == [], (name, facts)


def test_coordinate_free_checkpoint_exemption_keeps_native_and_holding_consumers(engine, island):
    base = _coordinate_free_checkpoint_job(engine, island)
    placeholder = base["setups"][1]["hold"]
    holds = {
        "missing positive contact model": {
            key: value for key, value in placeholder.items() if key != "contact_model"
        },
        "unresolved contact model": {**placeholder, "contact_model": "unknown"},
        "null contact model": {**placeholder, "contact_model": None},
        "null hold": None,
        "non-dict hold": [],
        "null kind": {**placeholder, "kind": None},
        "null fixture kind": {**placeholder, "fixture_kind": None},
        "known kind": {**placeholder, "kind": "solids"},
        "known fixture kind": {**placeholder, "fixture_kind": "custom"},
        "holding debt": {**placeholder, "debts": ["support contact is unresolved"]},
        "holding gap": {**placeholder, "gaps": ["a toe clamp is not drawn"]},
        "refused holding field": {**placeholder, "refused_fields": ["clamps"]},
        "hidden pose": {**placeholder, "pose": deepcopy(_clamped((2.0, 50.0))["pose"])},
        "hidden solids": {**placeholder, "solids": _clamped((2.0, 50.0))["solids"]},
        "hidden clamps": {**placeholder, "clamps": _clamped((2.0, 50.0))["clamps"]},
        "empty geometry field": {**placeholder, "solids": []},
        "structured press pad": {**_clamped((2.0, 50.0)), "contact_model": "none"},
        "structured vise": {**deepcopy(SEATED), "contact_model": "none"},
    }
    jobs = []
    for hold in holds.values():
        job = deepcopy(base)
        job["setups"][1]["hold"] = hold
        jobs.append(job)
    native_ops = {
        "native metadata inspect": {"subject": "S2:10", "do": "inspect"},
        "native cutting operation": {**deepcopy(base["setups"][0]["ops"][0]), "subject": "S2:10"},
        "inspect with operative profile geometry": {
            **deepcopy(base["setups"][0]["ops"][0]),
            "subject": "S2:10",
            "do": "inspect",
            "stock_removal_bounds": {"x": [0.0, 5.0], "y": [-5.0, 55.0], "z": [0.0, 20.0]},
        },
    }
    for op in native_ops.values():
        job = deepcopy(base)
        op.pop("checkpoints", None)
        job["setups"][1]["ops"] = [op]
        if op["do"] == "finish_profile":
            job["setups"][1]["preservation_ledger"].append(
                {"subject": "S2:40", "do": "finish_profile", "effect": "native"}
            )
            op["subject"] = "S2:40"
        jobs.append(job)
    results = engine.run({"jobs": jobs})["results"]
    for name, result in zip([*holds, *native_ops], results, strict=True):
        facts = result["ops"]["S1:10"]
        assert facts["checkpoint_hits"] == "unknown", (name, facts)
        assert facts["checkpoint_errors"] == [], (name, facts)
        assert "later setup S2's frame is unusable" in facts["checkpoint_reason"], (name, facts)
        assert facts["checkpoint_overshoot_ok"] == [], (name, facts)


def test_coordinate_free_descendant_does_not_hide_real_branch_contacts_or_support_debt(
    engine, island
):
    base = _coordinate_free_checkpoint_job(engine, island)
    jobs = []
    for hold in (
        _clamped((2.0, 50.0)),
        _clamped((35.0, 30.0), gaps=["a toe clamp is not drawn"]),
    ):
        job = deepcopy(base)
        # Both descendants receive S1's actually derived stock. S3 does not pretend
        # that the frameless S2 has supplied any new stock or a coordinate transform.
        job["setups"].append({**_setup([], hold, setup_id="S3"), "stock_in": "S1"})
        jobs.append(job)
    pressed, unresolved = engine.run({"jobs": jobs})["results"]
    facts = pressed["ops"]["S1:10"]
    assert "stock_reason" not in pressed["setups"]["S3"], pressed["setups"]["S3"]
    assert _later(facts) == {("S1:10 finish line -X[2]", "S3", "clamp press")}, facts
    assert facts["checkpoint_hits"] == 1 and "checkpoint_reason" not in facts, facts
    (error,) = facts["checkpoint_errors"]
    assert error["area_mm2"] > 1.0, error
    assert facts["checkpoint_overshoot_ok"] == []
    facts = unresolved["ops"]["S1:10"]
    assert facts["checkpoint_hits"] == "unknown" and facts["checkpoint_errors"] == [], facts
    assert (
        "later setup S3 has undrawn components (a toe clamp is not drawn)"
        in facts["checkpoint_reason"]
    ), facts
    assert "later setup S2's frame is unusable" not in facts["checkpoint_reason"], facts
    assert facts["checkpoint_overshoot_ok"] == []


def test_coordinate_free_intermediary_does_not_hide_a_later_consumers_unknown_stock(engine, island):
    job = _coordinate_free_checkpoint_job(engine, island)
    job["setups"].append({**_setup([], _clamped((2.0, 50.0)), setup_id="S3"), "stock_in": "S2"})
    result = engine.run(job)
    facts = result["ops"]["S1:10"]
    assert facts["checkpoint_hits"] == "unknown" and facts["checkpoint_errors"] == [], facts
    assert "later setup S3's entry stock is unknown" in facts["checkpoint_reason"], facts
    assert "setup S2 frame is unusable" in result["setups"]["S3"]["stock_reason"]
    assert "later setup S2's frame is unusable" not in facts["checkpoint_reason"], facts
    assert facts["checkpoint_overshoot_ok"] == []


def test_coordinate_free_coating_does_not_clear_independent_material_preservation_debt(
    engine, island
):
    base = _coordinate_free_checkpoint_job(engine, island)
    frame = deepcopy(base["setups"][0]["frame"])
    base["workpieces"] = {"island": {"pose": deepcopy(frame)}}
    top = engine.refs(island, (5.0, 5.0, 20.0), (65.0, 45.0, 20.0), kind="Plane")
    assert len(top) == 1
    base["features"]["thickness"] = top
    source, later = base["setups"]
    source["ops"][0]["workpiece_faces"] = {"island": base["features"]["west"]}
    source["preservation_ledger"] = [
        {"subject": "S1:10", "do": "finish_profile", "effect": "native"}
    ]
    # Use a real frame for this independent proof: the contact-only exemption must
    # not make coating a dimensional no-op, nor fake stock through a frameless setup.
    later["frame"] = deepcopy(frame)
    later["inspection_preservation"] = [
        {
            "check_id": "S2:10",
            "feature": "thickness",
            "requirement": "height",
            "workpiece_id": "island",
            "after": "S1:10",
            "before": "S3:10",
            "nominal_mm": 20.0,
        }
    ]
    boundary = {
        **_setup([{"subject": "S3:10", "do": "release"}], _clamped((35.0, 30.0)), setup_id="S3"),
        "stock_in": "S2",
        "preservation_ledger": [{"subject": "S3:10", "do": "release", "effect": "metadata"}],
    }
    base["setups"].append(boundary)
    metadata = deepcopy(base)
    metadata["setups"][1]["preservation_ledger"] = [
        entry for entry in metadata["setups"][1]["preservation_ledger"] if entry["do"] != "coating"
    ]
    plain, coated = engine.run({"jobs": [metadata, base]})["results"]
    for result in (plain, coated):
        facts = result["ops"]["S1:10"]
        assert facts["checkpoint_hits"] == 0 and facts["checkpoint_errors"] == [], facts
        assert "checkpoint_reason" not in facts, facts
        assert facts["checkpoint_overshoot_ok"] == ["S1:10 finish line -X[2]"]
        assert "stock_reason" not in result["setups"]["S3"], result["setups"]["S3"]
    for sid in ("S2", "S3"):
        (clear,) = plain["setups"][sid]["inspection_preservation"]
        assert clear["status"] == "pass" and clear["reasons"] == [], clear
        (debt,) = coated["setups"][sid]["inspection_preservation"]
        assert debt["status"] == "unknown", debt
        assert debt["reasons"] == ["S2:20: material effects are unmodeled"], debt
        assert debt["operations"] == ["S1:10", "S2:20"], debt
        assert debt["region"] == clear["region"] and debt["region"]["nominal_mm"] == 20.0


# ------------------------------------------------------------ discrete chain-drill stock

# Two radius-1 drill holes 0.5 mm west of the island's west wall (x = 5): an arc table's
# rows 20 degrees apart on R10 about (-6.5, 18), and a line table's rows 4 mm apart. Each
# pair leaves a positive physical web between its cylinders (1.4729635533 and 2 mm).
DRILL = 1.0
CHAIN_HOLES = {
    "arc_table": [
        [-6.5 + 10.0 * math.cos(math.radians(angle)), 18.0 + 10.0 * math.sin(math.radians(angle))]
        for angle in (0.0, 20.0)
    ],
    "line_table": [[3.5, 20.0], [3.5, 24.0]],
}
PROBE = 0.05  # mm: a 0.1 mm diameter column at the midpoint between a table's two holes
# An authored clearing box over the west strip around the line table's holes.
BOX = {"x": [0.0, 5.0], "y": [10.0, 30.0], "z": [0.0, 20.0]}


def _exported(kind):
    """A chain-drill table's checkpoints exactly as the production exporter passes them."""
    points = CHAIN_HOLES[kind]
    table = {
        "op": 10,
        "stage": "finish",
        "method": "chain_drill",
        "side": "+Y",
        "dro_tip_z": 0.0,
        "cut_order": "conventional",
        "cutter_side": "left",
    }
    if kind == "arc_table":
        table["rows"] = [{"dro_xy": list(point)} for point in points]
    else:
        table["setup_xy"] = table["dro_xy"] = [list(point) for point in points]
    checkpoints = table_checkpoints("S1:10", {kind: [table]}, 10, "mm")
    (path,) = checkpoints["paths"]
    assert path["method"] == "chain_drill" and path["xy_mm"] == points, path
    assert [row["method"] for row in checkpoints["rows"]] == ["chain_drill"] * len(points)
    return checkpoints


def _milled(checkpoints):
    """The same printed rows with no path method: ordinary milling, never a vacuous chain."""
    milled = deepcopy(checkpoints)
    for entry in (*milled["rows"], *milled["paths"]):
        entry.pop("method", None)
        entry.pop("chain_geometry", None)
    return milled


def _bounded_chain(checkpoints):
    """A table as a bounded op prints it: whole, on a 0.001 mm DRO, its chain paths with
    their true finite line and the west wall (the bounds clip is not judged here)."""
    table = deepcopy(checkpoints)
    table.update(
        bounded=True,
        dro={"step": 0.001, "decimals": 3, "scale": 1.0},
        row_format=ROW_FORMAT,
        fragment_format=FRAGMENT_FORMAT,
    )
    for path in table["paths"]:
        if path.get("method") == "chain_drill":
            path["chain_geometry"] = {
                "pitch_mm": 4.2,
                "offset": 1.5,
                "setup_origin": [0.0, 0.0],
                "basis": [[1.0, 0.0], [0.0, 1.0]],
                "curves": [{"kind": "line", "ends": path["xy_mm"], "normal": [-1.0, 0.0]}],
                "walls": [
                    {"kind": "line", "ends": [[5.0, 5.0], [5.0, 45.0]], "normal": [-1.0, 0.0]}
                ],
            }
    return table


def _chain_op(checkpoints, allowance=0.0, bounds=None):
    """A full-depth profile of the west wall with a radius-1 drill printing ``checkpoints``;
    rough when it leaves ``allowance``."""
    op = {
        **_op("S1:10", "west", DRILL, 25.0, 30.0),
        "do": "rough_profile" if allowance else "finish_profile",
        "to_z": 0.0,
        "checkpoints": checkpoints,
    }
    if allowance:
        op["rough_allowance_mm"] = allowance
    if bounds is not None:
        op["stock_removal_bounds"] = bounds
    return op


_DISPATCH = ("_cut", "_removal", "_op_sweep", "_run_out")
# Whatever exists of these in the engine under test; a missing one is never required.
_DISPATCH_HELPERS = {
    "_number",
    "_positive",
    "_unbounded_chain",
    "_turned",
    "_rotary",
    "_hand",
    "_sawn",
    "_islands",
    "_segments",
}
_DISPATCH_CONSTANTS = {
    "HIT_MM3",
    "STOCK_TOL",
    "COVER_MM",
    "PROFILE_ACTIONS",
    "TURNING",
    "ROTARY",
    "HAND",
    "SAW_ACTIONS",
}


class _Pieces:
    """Boolean-free solids whose pieces keep their identity: a fuse is their union."""

    def __init__(self, *tags):
        self.tags = list(tags)

    @property
    def Solids(self):
        return [_Pieces(tag) for tag in self.tags]

    @property
    def Volume(self):
        return float(len(self.tags))

    def fuse(self, others):
        return _Pieces(*self.tags, *(tag for other in others for tag in other.tags))

    def common(self, other):
        return self


@pytest.fixture(scope="module")
def stock_dispatch():
    """The engine's own stock dispatch, ``_cut`` through ``_removal``, ``_op_sweep`` and
    ``_run_out``, without FreeCAD. Only the cutter-centre sweep, wall corridor, lineage band,
    clearing box and guard are recorded stand-ins; every decision is production code."""
    tree = ast.parse(ENGINE.read_text(encoding="utf-8"))
    nodes = [
        node
        for node in tree.body
        if (
            isinstance(node, ast.FunctionDef)
            and node.name in _DISPATCH_HELPERS
            or isinstance(node, ast.Assign)
            and any(
                isinstance(target, ast.Name) and target.id in _DISPATCH_CONSTANTS
                for target in node.targets
            )
        )
    ]
    setup = next(
        node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "_Setup"
    )
    methods = [
        node for node in setup.body if isinstance(node, ast.FunctionDef) and node.name in _DISPATCH
    ]
    assert sorted(node.name for node in methods) == sorted(_DISPATCH)
    sweeps = []

    def centre_sweep(paths, radius, top):
        sweeps.append([(tuple(map(tuple, xy)), z0) for xy, z0 in paths])
        tags = [
            ("hole" if len(xy) == 1 else "path", tuple(map(tuple, xy)))
            for xy, z0 in paths
            if z0 < top
        ]
        return _Pieces(*tags) if tags else None

    namespace = {
        "math": math,
        "Z": (0.0, 0.0, 1.0),
        "_bbox": lambda shape: (0.0, -5.0, 0.0, 70.0, 55.0, 20.0),
        "_centre_sweep": centre_sweep,
        "_vertical": lambda face, axis: True,
        # Only the corridor borders the claimed wall; every hole stands 0.5 mm off it.
        "_distance": lambda piece, face: (0.0 if piece.tags == ["corridor"] else 0.5,),
        "_sweep_window": lambda sweep: None,
    }
    module = ast.Module(body=[*nodes, *methods], type_ignores=[])
    exec(compile(module, str(ENGINE), "exec"), namespace)
    production = type("Dispatch", (), {name: namespace[name] for name in _DISPATCH})

    def cut(op):
        calls = {"corridor_calls": [], "band_calls": [], "bounded_calls": []}

        class Setup(production):
            faces, part = ["west wall"], "entry stock"

            def __init__(self):
                self.run_outs, self.designs = {}, {}

            def _claims(self, op):
                return [0], [], None

            def _guarded(self, op):
                return op.get("rough_allowance_mm", 0.0), None

            def _carried(self, op):
                return 0.3  # an earlier op's larger lineage leave

            def _reach_window(self, op, leave, carried):
                return None

            def _sweep(self, valid, action):
                return [], None

            def _protect(self, shape, leave, window):
                return shape, None

            def _above(self, z):
                return None

            def _corridor(self, walls, radius, to_z):
                calls["corridor_calls"].append(walls)
                return _Pieces("corridor"), None

            def _band(self, stock, valid, to_z, leave, carried, window):
                calls["band_calls"].append(carried)
                return [[_Pieces("band")]], None

            def _bounded(self, bounds, *args):
                calls["bounded_calls"].append(bounds)
                return _Pieces("box"), None

        setup = Setup()
        sweeps.clear()
        result, why = setup._cut(op, "entry stock")
        assert why is None, why
        removal, band = result
        design = setup.designs.get(id(op), "unset")
        return {
            "removal": None if removal is None else removal.tags,
            "band": [[piece.tags for piece in group] for group in band],
            "sweeps": list(sweeps),
            "design": design.tags if isinstance(design, _Pieces) else design,
            **calls,
        }

    return cut


@pytest.mark.parametrize("allowance", (0.0, 0.25))
@pytest.mark.parametrize("kind", sorted(CHAIN_HOLES))
def test_unbounded_chain_drill_removes_only_its_discrete_hole_cylinders(
    stock_dispatch, kind, allowance
):
    points = [tuple(point) for point in CHAIN_HOLES[kind]]
    cut = stock_dispatch(_chain_op(_exported(kind), allowance))
    # One single-point path per printed row: the drill never travels between its holes.
    assert cut["sweeps"] == [[((point,), 0.0) for point in points]]
    # Every actual hole, though 0.5 mm off the claimed wall past a 0.25 mm leave; no more.
    assert cut["removal"] == [("hole", (point,)) for point in points]
    # No wall corridor or lineage band, and no design: all a hole removes is A′ scrap.
    assert cut["corridor_calls"] == [] and cut["band_calls"] == [] and cut["band"] == []
    assert cut["design"] is None


@pytest.mark.parametrize("kind", sorted(CHAIN_HOLES))
def test_unbounded_milling_of_the_same_rows_keeps_its_sweep_corridor_and_band(stock_dispatch, kind):
    points = tuple(tuple(point) for point in CHAIN_HOLES[kind])
    cut = stock_dispatch(_chain_op(_milled(_exported(kind)), 0.25))
    assert cut["sweeps"] == [[(points, 0.0)]]
    assert cut["corridor_calls"] == [[0]] and cut["design"] == ["corridor"]
    assert "corridor" in cut["removal"]
    assert cut["band_calls"] == [0.3] and cut["band"] == [[["band"]]]


def _untagged_rows(checkpoints):
    """The same table with its rows' method tags removed: the path is the stock contract,
    the row the collision payload."""
    table = deepcopy(checkpoints)
    for row in table["rows"]:
        row.pop("method", None)
    return table


@pytest.mark.parametrize("kind", sorted(CHAIN_HOLES))
def test_chain_path_methods_drill_discrete_holes_without_row_method_tags(stock_dispatch, kind):
    points = [tuple(point) for point in CHAIN_HOLES[kind]]
    cut = stock_dispatch(_chain_op(_untagged_rows(_exported(kind)), 0.25))
    assert cut["sweeps"] == [[((point,), 0.0) for point in points]]
    assert cut["removal"] == [("hole", (point,)) for point in points]
    assert cut["corridor_calls"] == [] and cut["band_calls"] == [] and cut["design"] is None


@pytest.mark.parametrize("method", (None, "", "stairs"))
def test_a_missing_empty_or_other_path_method_mills_despite_chain_row_tags(stock_dispatch, method):
    table = _exported("line_table")
    for path in table["paths"]:
        path.pop("method")
        if method is not None:
            path["method"] = method
    points = tuple(tuple(point) for point in CHAIN_HOLES["line_table"])
    cut = stock_dispatch(_chain_op(table, 0.25))
    # Chain-tagged rows never make the path's stock a chain: it sweeps continuously.
    assert all(row["method"] == "chain_drill" for row in table["rows"])
    assert cut["sweeps"] == [[(points, 0.0)]]
    assert cut["corridor_calls"] == [[0]] and cut["design"] == ["corridor"]
    assert cut["band_calls"] == [0.3] and cut["band"] == [[["band"]]]


def test_a_mixed_table_drills_its_chain_rows_and_keeps_milling_credit(stock_dispatch):
    chain, milled = _exported("line_table"), _milled(_exported("arc_table"))
    mixed = {
        **chain,
        "rows": chain["rows"] + milled["rows"],
        "paths": chain["paths"] + milled["paths"],
    }
    cut = stock_dispatch(_chain_op(mixed))
    holes = [((tuple(point),), 0.0) for point in CHAIN_HOLES["line_table"]]
    arc = (tuple(tuple(point) for point in CHAIN_HOLES["arc_table"]), 0.0)
    assert cut["sweeps"] == [[*holes, arc]]
    # Not every path is a chain, so the milling path's corridor and band stay credited.
    assert cut["corridor_calls"] == [[0]] and cut["band_calls"] == [0.3]


@pytest.mark.parametrize("kind", sorted(CHAIN_HOLES))
def test_a_bounded_chain_keeps_its_authored_clearing_box(stock_dispatch, kind):
    cut = stock_dispatch(_chain_op(_exported(kind), 0.25, BOX))
    assert cut["bounded_calls"] == [BOX] and cut["removal"] == ["box"]
    assert cut["sweeps"] == [] and cut["corridor_calls"] == []
    assert cut["band_calls"] == [0.3] and cut["band"] == [[["band"]]]


_DISCRETE_NATIVE = r"""
import importlib.util
import json
import os
import sys
import FreeCAD, Part

V = FreeCAD.Vector
spec = importlib.util.spec_from_file_location("discrete_engine", os.environ["ENGINE"])
engine = importlib.util.module_from_spec(spec)
spec.loader.exec_module(engine)
directory = sys.argv[sys.argv.index("--") + 1]
with open(directory + "/cases.json", encoding="utf-8") as stream:
    cases = json.load(stream)
built = {}
finish = engine._Setup._finish


def recorded(self, ops):
    # The builder's actual end stock, recorded before the production wall/debt judgement.
    built[str(self.setup.get("id"))] = self.built
    return finish(self, ops)


engine._Setup._finish = recorded


def column(xy, radius):
    return Part.makeCylinder(radius, 18.0, V(xy[0], xy[1], 1.0))


answers = []
for case in cases:
    built.clear()
    result = engine.run(case["job"])
    stock, why = built.get("S1", (None, "setup S1 never finished"))
    holes, probe = case["holes"], case["probe"]
    web = [(a + b) / 2 for a, b in zip(*holes)]
    probes = {f"hole {i}": column(hole, probe) for i, hole in enumerate(holes)}
    probes["web"] = column(web, probe)
    # The continuous capsule the exact base credited, built by the production helper.
    credited = engine._centre_sweep([(holes, 0.0)], case["radius"], 20.0 + engine.COVER_MM)
    answers.append({
        "status": result.get("status"),
        "built_reason": why,
        "built_volume": None if stock is None else stock.Volume,
        "probes": {
            name: {
                "volume": solid.Volume,
                "in_stock": None if stock is None else stock.common(solid).Volume,
            }
            for name, solid in probes.items()
        },
        "credited_web": credited.common(probes["web"]).Volume,
        "setups": {
            sid: {key: facts.get(key) for key in ("stock_reason", "stock_out_reason")}
            for sid, facts in result.get("setups", {}).items()
        },
    })
with open(directory + "/answers.json", "w", encoding="utf-8") as stream:
    json.dump(answers, stream)
"""


@pytest.fixture(scope="module")
def discrete_stock(tmp_path_factory, freecad_kernel, island):
    """One native batch of whole jobs on the island: each records its first setup's actual
    built stock at :meth:`_Setup._finish` and probes it, then the job runs on unchanged."""
    directory = tmp_path_factory.mktemp("discrete-stock")
    engine = Engine(directory, freecad_kernel)
    ops = {}
    for kind in sorted(CHAIN_HOLES):
        ops[f"chain {kind}"] = _chain_op(_exported(kind))
        ops[f"milled {kind}"] = _chain_op(_milled(_exported(kind)))
    ops["chain line_table rough"] = _chain_op(_exported("line_table"), 0.25)
    bounded = _bounded_chain(_exported("line_table"))
    ops["bounded chain"] = _chain_op(bounded, bounds=BOX)
    ops["bounded milled"] = _chain_op(_milled(bounded), bounds=BOX)
    cases = [
        {
            "job": _job(engine, island, [op], west=WEST),
            "holes": CHAIN_HOLES["arc_table" if "arc_table" in name else "line_table"],
            "probe": PROBE,
            "radius": DRILL,
        }
        for name, op in ops.items()
    ]
    (directory / "cases.json").write_text(json.dumps(cases), encoding="utf-8")
    script = directory / "probe.py"
    script.write_text(_DISCRETE_NATIVE, encoding="utf-8")
    process = subprocess.run(
        [freecad_kernel, str(script), "--", str(directory)],
        env={**os.environ, "ENGINE": str(ENGINE)},
        capture_output=True,
        text=True,
        errors="replace",
        timeout=600,
    )
    answers = directory / "answers.json"
    assert process.returncode == 0 and answers.exists(), (
        process.stdout[-2000:] + process.stderr[-2000:]
    )
    results = json.loads(answers.read_text(encoding="utf-8"))
    assert len(results) == len(ops)
    return dict(zip(ops, results, strict=True))


def _drilled(probe):
    return probe["in_stock"] <= 1e-6


def _whole(probe):
    return probe["in_stock"] == pytest.approx(probe["volume"], rel=1e-9)


@pytest.mark.parametrize("name", ("chain arc_table", "chain line_table", "chain line_table rough"))
def test_native_unbounded_chain_drills_holes_keeps_webs_and_points_at_bounds(discrete_stock, name):
    answer = discrete_stock[name]
    holes = CHAIN_HOLES["arc_table" if "arc_table" in name else "line_table"]
    web = [(a + b) / 2 for a, b in zip(*holes, strict=True)]
    # Independent geometry: the whole probe clears both drilled discs.
    assert min(math.dist(web, hole) for hole in holes) - DRILL - PROBE > 0.6
    assert answer["status"] == "ok" and answer["built_reason"] is None, answer
    probes = answer["probes"]
    assert all(_drilled(probes[f"hole {i}"]) for i in range(len(holes))), probes
    # The web stays stock, though the base's continuous capsule held all of it.
    assert _whole(probes["web"]), probes
    assert answer["credited_web"] == pytest.approx(probes["web"]["volume"], rel=1e-9)
    reason = answer["setups"]["S1"]["stock_out_reason"]
    assert "overstock still touches claimed wall(s)" in reason, reason
    assert all(word in reason for word in ("chain_drill", "stock_removal_bounds", "break-out"))
    # The next setup inherits that debt and its pointer, never a guessed stock.
    assert answer["setups"]["S2"]["stock_reason"] == reason


@pytest.mark.parametrize("kind", sorted(CHAIN_HOLES))
def test_native_unbounded_milling_of_the_same_rows_still_clears_the_web(discrete_stock, kind):
    answer = discrete_stock[f"milled {kind}"]
    assert answer["status"] == "ok" and answer["built_reason"] is None, answer
    assert all(_drilled(probe) for probe in answer["probes"].values()), answer["probes"]
    assert answer["setups"]["S1"]["stock_out_reason"] is None, answer["setups"]
    assert answer["setups"]["S2"]["stock_reason"] is None, answer["setups"]


def test_native_bounded_chain_removes_its_authored_box_like_milling(discrete_stock):
    chain, milled = discrete_stock["bounded chain"], discrete_stock["bounded milled"]
    for answer in (chain, milled):
        assert answer["status"] == "ok" and answer["built_reason"] is None, answer
        assert all(_drilled(probe) for probe in answer["probes"].values()), answer["probes"]
        assert answer["setups"]["S1"]["stock_out_reason"] is None, answer["setups"]
    # The box (5 x 20 x 20 mm, all outside the island) is all either removes.
    assert chain["built_volume"] == pytest.approx(milled["built_volume"], abs=1e-6)
    assert chain["built_volume"] == pytest.approx(70.0 * 60.0 * 20.0 - 2000.0, abs=1e-3)
