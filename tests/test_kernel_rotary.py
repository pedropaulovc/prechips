"""Rotary dividing-head milling: each sample turned under the vertical spindle.

Engine tests run ``freecad_job.py`` on solids authored here and read only its JSON.
"""

import subprocess

import pytest
from test_fixture_solids import _box, _chuck
from test_kernel_geometry import Engine, _op, _setup

_AUTHOR = r"""
import sys
import FreeCAD, Part
out = sys.argv[sys.argv.index("--") + 1]
V = FreeCAD.Vector
X = V(1, 0, 0)
# R8 tail x -15..0 for the head's chuck, R10 body x 0..60 along setup X.
tail = Part.makeCylinder(8, 15, V(-15, 0, 0), X)
# A 10 x 6 pad standing proud of the body (top z 13) at x 25..35.
pad = Part.makeBox(10, 6, 5, V(25, -3, 8))
body = Part.makeCylinder(10, 60, V(0, 0, 0), X)
tail.fuse(body).removeSplitter().exportStep(out + "/plain.step")
tail.fuse(body).fuse(pad).removeSplitter().exportStep(out + "/padded.step")
# The body steps down to R9 at x 30; a pad on the step at x 31..35 rises to z 13.
step = Part.makeCylinder(10, 30, V(0, 0, 0), X).fuse(Part.makeCylinder(9, 30, V(30, 0, 0), X))
near = Part.makeBox(4, 6, 6, V(31, -3, 7))
tail.fuse(step).fuse(near).removeSplitter().exportStep(out + "/stepped.step")
round_near = Part.makeCylinder(3, 6, V(34, 0, 7), V(0, 0, 1))
tail.fuse(step).fuse(round_near).removeSplitter().exportStep(out + "/stepped-boss.step")
# The stepped band and pad with a cone beyond the R9 step: no rotary removal is derivable
# for the cone.
cone = Part.makeCone(9, 7, 10, V(60, 0, 0), X)
tail.fuse(step).fuse(near).fuse(cone).removeSplitter().exportStep(out + "/stepped-cone.step")
# A round R4 boss standing proud of the body (top z 13) at x 30: its curved wall fans
# away from the radial sweep of the holed body face.
boss = Part.makeCylinder(4, 6, V(30, 0, 7), V(0, 0, 1))
tail.fuse(body).fuse(boss).removeSplitter().exportStep(out + "/bossed.step")
# A raised shelf on the boss overhangs the wall-tangent cutter without touching
# the floor. It must remain an obstacle inside the new posed cutting column.
shelf = Part.makeBox(5, 2, 3, V(33, -1, 11))
tail.fuse(body).fuse(boss).fuse(shelf).removeSplitter().exportStep(out + "/overhung.step")
tail.fuse(Part.makeCone(10, 8, 60, V(0, 0, 0), X)).exportStep(out + "/conical.step")
# A cylindrical source parallel to, but displaced from, the dividing-head axis.
tail.fuse(Part.makeCylinder(10, 60, V(0, 3, 0), X)).removeSplitter().exportStep(
    out + "/offset.step"
)
"""

# Head axis along setup +X, jaw face at x = -5: the jaws grip the tail at x -15..-5.
HEAD = {"origin_mm": [-5.0, 0.0, 0.0], "x": [0.0, 0.0, 1.0], "z": [1.0, 0.0, 0.0]}
BODY = ((0, -10, -10), (60, 10, 10))


@pytest.fixture(scope="module")
def parts(tmp_path_factory, freecad_kernel):
    directory = tmp_path_factory.mktemp("rotary")
    script = directory / "author.py"
    script.write_text(_AUTHOR, encoding="utf-8")
    subprocess.run(
        [freecad_kernel, str(script), "--", str(directory)],
        capture_output=True,
        text=True,
        errors="replace",
        timeout=300,
    )
    return {path.stem: path for path in directory.glob("*.step")}


@pytest.fixture
def engine(tmp_path, freecad_kernel):
    return Engine(tmp_path, freecad_kernel)


def _head(pose=HEAD):
    return _chuck(
        fixture_kind="dividing_head",
        pose=pose,
        head_solids=[_box("BS-0:body", [-60.0, -60.0, -80.0], [120.0, 120.0, 80.0])],
    )


def _rotary(engine, step, body, hold, stock=None, **window):
    op = {**_op("S1:10", "body", 3.0, 10.0, 30.0), "approach": "rotary", **window}
    job = engine.job(step, {"body": body}, [_setup([op], hold)], stock=stock)
    result = engine.run(job)
    assert result["status"] == "ok", result
    return result["ops"]["S1:10"]


def _window_result(engine, step, body, windows, stock=None):
    ops = [
        {
            **_op(f"S1:{10 * (i + 1)}", "body", window.get("radius_mm", 3.0), 10.0, 30.0),
            "approach": "rotary",
            **window,
        }
        for i, window in enumerate(windows)
    ]
    result = engine.run(engine.job(step, {"body": body}, [_setup(ops, _head())], stock=stock))
    assert result["status"] == "ok", result
    index = result["features"]["body"][0]
    return result, index


def _assert_unproved_coverage(result, index, categories=("cut", "finish")):
    for category in categories:
        coverage = result["rotary_coverage"][category]
        assert coverage["complete_indices"] == [] and coverage["gaps"] == [], coverage
        records = [item for item in coverage["unknown"] if item["index"] == index]
        assert records, coverage
        assert any(
            "sampled rotary poses do not prove executed cuts" in item["reason"] for item in records
        ), coverage


def test_rotary_floor_beside_an_unclaimed_proud_pad_clears_it(engine, parts):
    step = parts["padded"]
    body = engine.refs(step, *BODY, kind="Cylinder")
    assert len(body) == 1
    op = _rotary(engine, step, body, _head())
    assert op["approach"] == "rotary" and op["claim_errors"] == []
    # Every sample, edges on the pad walls included, is turned to the top and clears.
    assert op["tool_hits"] == 0 and op["holder_hits"] == 0, op


def test_rotary_round_stock_is_not_removed_by_diagnostic_boss_poses(engine, parts):
    # Both windows retain the R15 entry bar: sampled poses prove no removal.
    step = parts["bossed"]
    body = engine.refs(step, *BODY, kind="Cylinder")
    assert len(body) == 1
    bar = {"shape": "round", "dia_mm": 30.0, "length_mm": 75.0}
    stock = {**bar, "origin_mm": [-15.0, 0.0, 0.0], "axis": [1.0, 0.0, 0.0]}
    op = _rotary(engine, step, body, _head(), stock, z_from=0.0, z_to=70.0)
    assert op["claim_errors"] == []
    assert op["tool_hits"] == "unknown", op
    assert op["obstacles"]["tool"] == ["part"], op
    assert op["rotary_target"]["attained_indices"] == []
    restricted = _rotary(engine, step, body, _head(), stock, z_from=5.0, z_to=65.0)
    assert restricted["claim_errors"] == []
    assert restricted["tool_hits"] == "unknown"
    assert restricted["obstacles"]["tool"] == ["part"]


def test_rotary_diagnostic_column_preserves_a_finished_overhang(engine, parts):
    step = parts["overhung"]
    body = engine.refs(step, *BODY, kind="Cylinder")
    stock = {
        "shape": "round",
        "dia_mm": 30.0,
        "length_mm": 75.0,
        "origin_mm": [-15.0, 0.0, 0.0],
        "axis": [1.0, 0.0, 0.0],
    }
    op = _rotary(engine, step, body, _head(), stock, z_from=0.0, z_to=70.0)
    assert op["claim_errors"] == []
    assert op["tool_hits"] == "unknown" and op["obstacles"]["tool"] == ["part"], op
    assert op["hit_refs"]["tool"], op


@pytest.mark.parametrize("part", ["stepped", "stepped-boss"])
def test_rotary_cutter_hits_a_pad_or_boss_lying_in_its_path(engine, parts, part):
    # The claimed R10 band ends at a convex step; the cutter centred on that edge
    # reaches over the R9 step onto the pad or round boss 1 mm beyond it.
    step = parts[part]
    body = engine.refs(step, (0, -10, -10), (30, 10, 10), kind="Cylinder")
    assert len(body) == 1
    op = _rotary(engine, step, body, _head())
    assert op["tool_hits"] > 0 and op["obstacles"]["tool"] == ["part"], op
    assert op["hit_refs"]["tool"], op


def test_rotary_partial_angle_window_excludes_outside_obstacles(engine, parts):
    step = parts["overhung"]
    body = engine.refs(step, *BODY, kind="Cylinder")
    full = _rotary(engine, step, body, _head(), to_dia_mm=22.0, angle_window_deg=[-180.0, 180.0])
    assert full["claim_errors"] == [] and full["tool_hits"] > 0, full
    quarter = _rotary(engine, step, body, _head(), to_dia_mm=22.0, angle_window_deg=[90.0, 180.0])
    assert quarter["claim_errors"] == [] and quarter["claimed_indices"] == full["claimed_indices"]
    assert quarter["tool_hits"] == 0, quarter
    assert quarter["rotary_target"]["angle_deg"] == [90.0, 180.0]
    assert quarter["rotary_target"]["sampled_tip_z_mm"] == pytest.approx([11.001, 11.001], abs=1e-5)


def test_head_axis_not_perpendicular_to_setup_z_is_unsupported(engine, parts):
    step = parts["padded"]
    body = engine.refs(step, *BODY, kind="Cylinder")
    upright = {"origin_mm": [0.0, 0.0, -5.0], "x": [1.0, 0.0, 0.0], "z": [0.0, 0.0, 1.0]}
    op = _rotary(engine, step, body, _head(upright))
    assert "not perpendicular to setup Z" in op["unsupported_reason"]
    assert op["tool_hits"] == "unknown" and op["claimed_indices"] == "unknown"


def test_underivable_rotary_removal_stops_the_stock_builder_and_meets_its_entry_stock(
    engine, parts
):
    # A claimed cone has no derivable rotary removal: that cut stops the stock builder.
    # Its flute is credited none of the clearance it failed to derive, so it meets the
    # whole bar it entered with, and the stock this setup leaves is unknown downstream.
    step = parts["conical"]
    body = engine.refs(step, *BODY, kind="Cone")
    assert len(body) == 1
    stock = {
        "shape": "round",
        "dia_mm": 30.0,
        "length_mm": 75.0,
        "origin_mm": [-15.0, 0.0, 0.0],
        "axis": [1.0, 0.0, 0.0],
    }
    op = {**_op("S1:10", "body", 3.0, 10.0, 30.0), "approach": "rotary"}
    setups = [_setup([op], _head()), _setup([], _head(), setup_id="S2")]
    result = engine.run(engine.job(step, {"body": body}, setups, stock=stock))
    assert result["status"] == "ok", result
    stopped = result["ops"]["S1:10"]
    assert stopped["claim_errors"] == []
    assert stopped["tool_hits"] == stopped["min_hits"]["tool"] == "unknown", stopped
    assert stopped["min_hits"]["holder"] == stopped["holder_hits"]
    assert stopped["obstacles"]["tool"] == ["part"], stopped
    assert "S1:10" in result["setups"]["S2"]["stock_reason"], result["setups"]["S2"]


def test_rotary_op_after_an_underivable_rotary_removal_keeps_only_its_certain_finished_hits(
    engine, parts
):
    # The cone's rotary removal cannot be derived, so the stock the band's flute meets after
    # it is unknown: only finished material, present in any real stock, stays certain.
    step = parts["stepped-cone"]
    band = engine.refs(step, (0, -10, -10), (30, 10, 10), kind="Cylinder")
    cone = engine.refs(step, (60, -9, -9), (70, 9, 9), kind="Cone")
    assert len(band) == 1 and len(cone) == 1
    features = {"band": band, "cone": cone}

    def run(*features_in_order):
        ops = [
            {**_op(f"S1:{10 * (i + 1)}", feature, 3.0, 10.0, 30.0), "approach": "rotary"}
            for i, feature in enumerate(features_in_order)
        ]
        result = engine.run(engine.job(step, features, [_setup(ops, _head())]))
        assert result["status"] == "ok", result
        return result

    # Positive control: on finished-material stock the band's cutter certainly hits the pad.
    alone = run("band")["ops"]["S1:10"]
    assert alone["tool_hits"] > 0 and alone["obstacles"]["tool"] == ["part"], alone
    result = run("cone", "band")
    stopped, later = result["ops"]["S1:10"], result["ops"]["S1:20"]
    # A valid cone claim also withholds removal: poses are not executed cuts.
    assert stopped["claim_errors"] == [], stopped
    assert stopped["claimed_indices"] == result["features"]["cone"], stopped
    # Its clear flute meets the known before-stock, an upper bound on every after-stock.
    assert stopped["tool_hits"] == stopped["min_hits"]["tool"] == 0, stopped
    assert "tool_hits" not in stopped.get("reasons", {}), stopped
    assert later["tool_hits"] == "unknown", later
    why = later["reasons"]["tool_hits"]
    assert "S1:10" in why and "sampled rotary poses do not prove executed cuts" in why, later
    assert later["min_hits"]["tool"] == "unknown", later
    assert later["obstacles"]["tool"] == ["part"], later


@pytest.mark.parametrize(
    "ends",
    [
        [(5.0, 30.0), (40.0, 65.0)],
        [(5.0, 45.0), (25.0, 60.0)],
        [(5.0, 34.999), (35.001, 65.0)],
    ],
)
def test_rotary_axial_windows_withhold_union_and_gap_credit(engine, parts, ends):
    step = parts["plain"]
    body = engine.refs(step, *BODY, kind="Cylinder")
    result, index = _window_result(
        engine, step, body, [{"z_from": lo, "z_to": hi} for lo, hi in ends]
    )
    for op in result["ops"].values():
        assert op["claim_errors"] == [] and op["claimed_indices"] == [index], op
    _assert_unproved_coverage(result, index)


@pytest.mark.parametrize("join", [(35.0, 35.0), (40.0, 30.0)])
def test_rotary_mixed_cutters_withhold_adjacent_or_overlapping_window_credit(engine, parts, join):
    step = parts["plain"]
    body = engine.refs(step, *BODY, kind="Cylinder")
    result, index = _window_result(
        engine,
        step,
        body,
        [
            {"z_from": 0.0, "z_to": join[0], "radius_mm": 9.525 / 2},
            {"z_from": join[1], "z_to": 70.0, "radius_mm": 3.175 / 2},
        ],
        stock={
            "shape": "round",
            "dia_mm": 30.0,
            "length_mm": 75.0,
            "origin_mm": [-15.0, 0.0, 0.0],
            "axis": [1.0, 0.0, 0.0],
        },
    )
    _assert_unproved_coverage(result, index)
    # Entry stock is retained for diagnostics; the second op has unknown stock.
    first, second = result["ops"]["S1:10"], result["ops"]["S1:20"]
    for op in (first, second):
        assert op["claim_errors"] == [] and op["claimed_indices"] == [index]
    assert first["tool_hits"] == "unknown" and first["obstacles"]["tool"] == ["part"], first
    assert second["tool_hits"] == "unknown", second


def test_rotary_rough_and_finish_portions_both_withhold_attainment(engine, parts):
    step = parts["plain"]
    body = engine.refs(step, *BODY, kind="Cylinder")
    result, index = _window_result(
        engine,
        step,
        body,
        [
            {"z_from": 5.0, "z_to": 40.0, "finishing": False},
            {"z_from": 30.0, "z_to": 65.0, "finishing": True},
        ],
    )
    _assert_unproved_coverage(result, index)


def test_rotary_trimmed_floor_claims_withhold_gap_area(engine, parts):
    step = parts["padded"]
    body = engine.refs(step, *BODY, kind="Cylinder")
    result, index = _window_result(
        engine,
        step,
        body,
        [{"z_from": 5.0, "z_to": 30.0}, {"z_from": 40.0, "z_to": 65.0}],
    )
    for op in result["ops"].values():
        assert op["claimed_indices"] == [index] and op["claim_errors"] == []
    _assert_unproved_coverage(result, index)


@pytest.mark.parametrize(
    "angles",
    [
        [[0.0, 90.0]],
        [[150.0, 210.0]],
        [[-180.0, 120.0], [-120.0, 150.0]],
        [[-180.0, 0.0], [0.0, 180.0]],
    ],
)
def test_rotary_angular_portions_are_valid_claims_without_union_credit(engine, parts, angles):
    step = parts["plain"]
    body = engine.refs(step, *BODY, kind="Cylinder")
    result, index = _window_result(
        engine, step, body, [{"angle_window_deg": span} for span in angles]
    )
    assert all(
        op["claim_errors"] == [] and op["claimed_indices"] == [index]
        for op in result["ops"].values()
    )
    _assert_unproved_coverage(result, index)


def test_rotary_axial_and_angular_extrema_do_not_certify_an_uncovered_corner(engine, parts):
    step = parts["plain"]
    body = engine.refs(step, *BODY, kind="Cylinder")
    result, index = _window_result(
        engine,
        step,
        body,
        [
            {"angle_window_deg": [-180.0, 0.0]},
            {"z_from": 5.0, "z_to": 35.0, "angle_window_deg": [0.0, 180.0]},
        ],
    )
    _assert_unproved_coverage(result, index)


def test_rotary_half_windows_in_different_frames_do_not_prove_a_union(engine, parts):
    step = parts["plain"]
    body = engine.refs(step, *BODY, kind="Cylinder")
    op = {
        **_op("S1:10", "body", 3.0, 10.0, 30.0),
        "approach": "rotary",
        "angle_window_deg": [-180.0, 0.0],
    }
    flipped = {
        "origin": [0.0, 0.0, 0.0],
        "x": [1.0, 0.0, 0.0],
        "y": [0.0, -1.0, 0.0],
        "z": [0.0, 0.0, -1.0],
    }
    setups = [
        _setup([op], _head()),
        _setup([{**op, "subject": "S2:10"}], _head(), frame=flipped, setup_id="S2"),
    ]
    result = engine.run(engine.job(step, {"body": body}, setups))
    assert result["status"] == "ok", result
    index = result["features"]["body"][0]
    _assert_unproved_coverage(result, index)


@pytest.mark.parametrize("span", [(70.0, 80.0), (65.0, 70.0)])
def test_rotary_empty_or_edge_only_window_is_a_claim_error(engine, parts, span):
    step = parts["plain"]
    body = engine.refs(step, *BODY, kind="Cylinder")
    result, _ = _window_result(engine, step, body, [{"z_from": span[0], "z_to": span[1]}])
    op = result["ops"]["S1:10"]
    assert op["claimed_indices"] == [] and op["claim_errors"] == body
    assert op["tool_hits"] == "unknown", op
    for category in ("cut", "finish"):
        assert result["rotary_coverage"][category] == {
            "complete_indices": [],
            "gaps": [],
            "unknown": [],
        }


def test_rotary_positive_area_end_plane_at_window_boundary_is_not_an_empty_claim(engine, parts):
    step = parts["plain"]
    end = engine.refs(step, (60, -10, -10), (60, 10, 10), kind="Plane")
    assert len(end) == 1
    result, index = _window_result(engine, step, end, [{"z_from": 65.0, "z_to": 70.0}])
    assert result["ops"]["S1:10"]["claimed_indices"] == [index]
    assert result["ops"]["S1:10"]["claim_errors"] == []
    _assert_unproved_coverage(result, index)


def test_rotary_clipped_boundary_keeps_a_nearby_finished_pad_as_an_obstacle(engine, parts):
    step = parts["stepped"]
    body = engine.refs(step, (0, -10, -10), (30, 10, 10), kind="Cylinder")
    # This thin band contains no original axial grid point or original end edge;
    # its new boundary is still sampled and the R3 cutter reaches the pad at x 31.
    op = _rotary(
        engine,
        step,
        body,
        _head(),
        to_dia_mm=21.0,
        z_from=34.9,
        z_to=34.95,
        angle_window_deg=[-2.0, 2.0],
    )
    assert op["claim_errors"] == [] and op["claimed_indices"] != []
    assert op["tool_hits"] > 0 and op["obstacles"]["tool"] == ["part"], op
    assert op["hit_refs"]["tool"], op


@pytest.mark.parametrize("finishing", [False, True])
@pytest.mark.parametrize("complete", [False, True])
def test_unresolved_rotary_contribution_is_unknown_not_a_definite_gap(
    engine, parts, finishing, complete
):
    step = parts["plain"]
    body = engine.refs(step, *BODY, kind="Cylinder")
    result, index = _window_result(
        engine,
        step,
        body,
        [
            {"z_from": 5.0, "z_to": 65.0 if complete else 35.0},
            {"z_from": "unknown", "z_to": 65.0, "finishing": finishing},
        ],
    )
    failed = result["ops"]["S1:20"]
    assert failed["claimed_indices"] == "unknown" and failed["claim_errors"] == []
    cut = result["rotary_coverage"]["cut"]
    finish = result["rotary_coverage"]["finish"]
    _assert_unproved_coverage(result, index)
    assert any(
        "S1:20" in item["reason"] and "z_from/z_to is unknown" in item["reason"]
        for item in cut["unknown"]
    ), cut
    if finishing:
        assert any("S1:20" in item["reason"] for item in finish["unknown"]), finish


def test_unusable_rotary_setup_contribution_does_not_become_a_definite_union_gap(engine, parts):
    step = parts["plain"]
    body = engine.refs(step, *BODY, kind="Cylinder")
    first = {
        **_op("S1:10", "body", 3.0, 10.0, 30.0),
        "approach": "rotary",
        "z_from": 5.0,
        "z_to": 35.0,
    }
    second = {**first, "subject": "S2:10", "z_from": 35.0, "z_to": 65.0}
    bad_frame = {
        "origin": "unknown",
        "x": [1.0, 0.0, 0.0],
        "y": [0.0, 1.0, 0.0],
        "z": [0.0, 0.0, 1.0],
    }
    result = engine.run(
        engine.job(
            step,
            {"body": body},
            [
                _setup([first], _head()),
                _setup([second], _head(), frame=bad_frame, setup_id="S2"),
            ],
        )
    )
    assert result["status"] == "ok", result
    index = result["features"]["body"][0]
    assert result["ops"]["S2:10"]["claimed_indices"] == "unknown"
    for category in ("cut", "finish"):
        coverage = result["rotary_coverage"][category]
        assert coverage["complete_indices"] == [] and coverage["gaps"] == []
        assert any(item["index"] == index for item in coverage["unknown"])
        assert any(
            "S2:10" in item["reason"] and "frame" in item["reason"] for item in coverage["unknown"]
        ), coverage


def test_empty_rotary_claim_adds_no_unknown_beyond_valid_sampled_claim(engine, parts):
    step = parts["plain"]
    body = engine.refs(step, *BODY, kind="Cylinder")
    result, index = _window_result(
        engine,
        step,
        body,
        [{"z_from": 5.0, "z_to": 35.0}, {"z_from": 70.0, "z_to": 80.0}],
    )
    assert result["ops"]["S1:20"]["claim_errors"] == body
    _assert_unproved_coverage(result, index)
    for category in ("cut", "finish"):
        assert all(
            "S1:20" not in item["reason"] for item in result["rotary_coverage"][category]["unknown"]
        )


@pytest.mark.parametrize(
    "controls, expected_radius",
    [
        ({"to_dia_mm": 22.0}, 11.0),
        ({"rough_allowance_mm": 0.5}, 10.5),
        ({"to_dia_mm": 21.0, "rough_allowance_mm": 0.5}, 10.5),
        ({"to_dia_mm": 20.0, "rough_allowance_mm": 0.0}, 10.0),
    ],
)
def test_rotary_rough_target_moves_actual_diagnostic_tips(engine, parts, controls, expected_radius):
    step = parts["plain"]
    body = engine.refs(step, *BODY, kind="Cylinder")
    result, index = _window_result(
        engine, step, body, [{"do": "rough_profile", "finishing": False, **controls}]
    )
    op = result["ops"]["S1:10"]
    target = op["rotary_target"]
    assert op["sample_count"] > 0, op
    assert target["status"] == "unknown" and target["attained_indices"] == []
    assert target["faces"] == [{"index": index, "radius_mm": expected_radius}]
    # Native positive LIFT is 0.001 mm; this is not a target/source self-comparison.
    assert target["sampled_tip_z_mm"] == pytest.approx(
        [expected_radius + 0.001, expected_radius + 0.001], abs=1e-5
    )
    assert "sampled rotary poses do not prove executed cuts" in target["reason"]
    _assert_unproved_coverage(result, index, categories=("cut",))
    assert result["rotary_coverage"]["finish"] == {
        "complete_indices": [],
        "gaps": [],
        "unknown": [],
    }


@pytest.mark.parametrize(
    "controls, reason",
    [
        ({"to_dia_mm": 22.0, "rough_allowance_mm": 0.5}, "disagree"),
        ({"to_dia_mm": 19.0}, "inside protected source cylinder"),
        *[
            ({"to_dia_mm": value}, "not a known positive diameter")
            for value in (
                0.0,
                -1.0,
                float("nan"),
                float("inf"),
                -float("inf"),
                True,
                "22",
                None,
                [],
            )
        ],
        *[
            ({"rough_allowance_mm": value}, "rough_allowance_mm")
            for value in (-0.5, float("nan"), float("inf"), -float("inf"), True, "0.5", None, [])
        ],
    ],
)
def test_rotary_invalid_target_rejects_diagnostic_measurements(engine, parts, controls, reason):
    step = parts["plain"]
    body = engine.refs(step, *BODY, kind="Cylinder")
    op = _rotary(engine, step, body, _head(), do="rough_profile", finishing=False, **controls)
    target = op["rotary_target"]
    assert target["status"] == "unknown" and target["attained_indices"] == []
    assert reason in target["reason"], target
    assert "sampled_tip_z_mm" not in target
    assert op["sample_count"] == op["tool_hits"] == op["holder_hits"] == "unknown", op


@pytest.mark.parametrize(
    "part, bounds, kind",
    [
        ("conical", BODY, "Cone"),
        ("plain", ((60, -10, -10), (60, 10, 10)), "Plane"),
        ("offset", ((0, -7, -10), (60, 13, 10)), "Cylinder"),
    ],
)
def test_rotary_intermediate_target_requires_coaxial_cylinder(engine, parts, part, bounds, kind):
    step = parts[part]
    body = engine.refs(step, *bounds, kind=kind)
    assert len(body) == 1
    op = _rotary(engine, step, body, _head(), to_dia_mm=22.0)
    assert "require coaxial cylindrical claims" in op["rotary_target"]["reason"], op
    assert op["rotary_target"]["attained_indices"] == []
    assert "sampled_tip_z_mm" not in op["rotary_target"]
    assert op["sample_count"] == op["tool_hits"] == op["holder_hits"] == "unknown", op


def test_rotary_target_bounded_pose_window_does_not_clip_collision_geometry(engine, parts):
    step = parts["overhung"]
    body = engine.refs(step, *BODY, kind="Cylinder")
    op = _rotary(
        engine,
        step,
        body,
        _head(),
        to_dia_mm=22.0,
        z_from=40.1,
        z_to=40.2,
        angle_window_deg=[-2.0, 2.0],
    )
    assert op["claim_errors"] == [] and op["sample_count"] > 0, op
    target = op["rotary_target"]
    assert target["z_mm"] == pytest.approx([40.1, 40.2])
    assert target["angle_deg"] == pytest.approx([-2.0, 2.0])
    assert target["sampled_tip_z_mm"] == pytest.approx([11.001, 11.001], abs=1e-5)
    # Source x35.1..35.2 poses reach the shelf at x33..38 outside the narrow tip window.
    assert op["tool_hits"] > 0 and op["obstacles"]["tool"] == ["part"], op
    assert op["hit_refs"]["tool"], op
    assert target["attained_indices"] == []


@pytest.mark.parametrize("diameter, radius", [(None, 10.0), (22.0, 11.0)])
def test_rotary_finishing_target_withholds_attainment_and_downstream_stock(
    engine, parts, diameter, radius
):
    step = parts["plain"]
    body = engine.refs(step, *BODY, kind="Cylinder")
    op = {
        **_op("S1:10", "body", 3.0, 10.0, 30.0),
        "approach": "rotary",
        # On finishing this is the prior leave to remove, not another target offset.
        "rough_allowance_mm": 0.5,
    }
    if diameter is not None:
        op["to_dia_mm"] = diameter
    later = {**op, "subject": "S1:20"}
    result = engine.run(
        engine.job(
            step,
            {"body": body},
            [_setup([op, later], _head()), _setup([], _head(), setup_id="S2")],
        )
    )
    assert result["status"] == "ok", result
    index = result["features"]["body"][0]
    first, second = result["ops"]["S1:10"], result["ops"]["S1:20"]
    for measured in (first, second):
        target = measured["rotary_target"]
        assert target["faces"] == [{"index": index, "radius_mm": radius}]
        assert target["sampled_tip_z_mm"] == pytest.approx(
            [radius + 0.001, radius + 0.001], abs=1e-5
        )
        assert target["status"] == "unknown" and target["attained_indices"] == []
    _assert_unproved_coverage(result, index)
    assert second["tool_hits"] == second["reach_depth_mm"] == "unknown", second
    assert "S1:10" in second["reasons"]["tool_hits"], second
    assert "S1:10" in result["setups"]["S2"]["stock_reason"]


def test_rejected_rotary_undersize_preserves_source_pad_for_later_diagnostics(engine, parts):
    step = parts["stepped"]
    body = engine.refs(step, (0, -10, -10), (30, 10, 10), kind="Cylinder")
    result, index = _window_result(
        engine,
        step,
        body,
        [
            {"to_dia_mm": 19.0},
            {
                "to_dia_mm": 21.0,
                "z_from": 34.9,
                "z_to": 34.95,
                "angle_window_deg": [-2.0, 2.0],
            },
        ],
    )
    rejected, later = result["ops"]["S1:10"], result["ops"]["S1:20"]
    assert "inside protected source cylinder" in rejected["rotary_target"]["reason"]
    assert rejected["sample_count"] == "unknown"
    assert "sampled_tip_z_mm" not in rejected["rotary_target"]
    assert later["claimed_indices"] == [index] and later["sample_count"] > 0
    assert later["rotary_target"]["sampled_tip_z_mm"] == pytest.approx([10.501, 10.501], abs=1e-5)
    assert later["obstacles"]["tool"] == ["part"] and later["hit_refs"]["tool"], later
    assert later["tool_hits"] == "unknown", later
    assert later["rotary_target"]["attained_indices"] == []
