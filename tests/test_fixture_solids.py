"""Chuck, dead-centre, dividing-head, angle-plate/custom and clamp solids in the kernel.

Engine tests run ``freecad_job.py`` on solids authored here and read only its JSON;
host tests check which declared fixture facts reach the engine.
"""

import math
import subprocess

import pytest
from test_kernel_geometry import Engine, _op, _setup, _vise

from prechips.kernel import _engine_hold, hold_inputs

_AUTHOR = r"""
import sys
import FreeCAD, Part
out = sys.argv[sys.argv.index("--") + 1]
V = FreeCAD.Vector
# R10 bar 30 long on the setup Z axis.
Part.makeCylinder(10, 30).exportStep(out + "/bar.step")
# 40 x 20 x 10 plate.
Part.makeBox(40, 20, 10).exportStep(out + "/plate.step")
# 60 x 20 x 3 web with a 20 x 20 boss standing 12 mm above it at x 40..60 (15 tall there).
web = Part.makeBox(60, 20, 3).fuse(Part.makeBox(20, 20, 15, V(40, 0, 0))).removeSplitter()
web.exportStep(out + "/web.step")
# The plate with a vertical 4.004 bore through it at (30, 10).
bored = Part.makeBox(40, 20, 10).cut(Part.makeCylinder(2.002, 12, V(30, 10, -1)))
bored.exportStep(out + "/bored.step")
"""

MEASURED = {"by": "test", "date": "2026-10-05", "instrument": "test fixture author"}


@pytest.fixture(scope="module")
def parts(tmp_path_factory, freecad_kernel):
    directory = tmp_path_factory.mktemp("fixture-solids")
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
    assert len(paths) == 4, process.stdout[-2000:] + process.stderr[-2000:]
    return paths


@pytest.fixture
def engine(tmp_path, freecad_kernel):
    return Engine(tmp_path, freecad_kernel)


UP = {"x": [1.0, 0.0, 0.0], "z": [0.0, 0.0, 1.0]}


def _chuck(jaws=3, face_z=10.0, clock=0.0, **extra):
    """Engine chuck hold: jaw face at ``face_z`` on the setup Z axis, 10 mm grip."""
    return {
        "kind": "chuck",
        "fixture_kind": f"chuck_{jaws}jaw",
        "jaws": jaws,
        "pose": {"origin_mm": [0.0, 0.0, face_z], **UP},
        "jaw_clock_deg": clock,
        "grip_mm": 10.0,
        "body_dia_mm": 150.0,
        "body_length_mm": 60.0,
        "bore_dia_mm": 30.0,
        "jaw_width_mm": 16.0,
        "jaw_height_mm": 25.0,
        "jaw_depth_mm": 20.0,
        "debts": [],
        "gaps": [],
        **extra,
    }


def _box(name, at, size):
    return {"name": name, "shape": "box", "at_mm": at, "size_mm": size}


def _strap(origin):
    """A 50 x 12 x 8 strap whose underside centre sits at ``origin``."""
    return {
        "name": "clamp 1 kit/strap",
        "pose": {"origin_mm": origin, **UP},
        "solids": [_box("kit/strap:strap", [-25.0, -6.0, 0.0], [50.0, 12.0, 8.0])],
    }


def _plate_hold(clamp_z=10.0):
    """The plate on an angle-plate solid behind it (y 20..32), one strap on its top."""
    return {
        "kind": "solids",
        "fixture_kind": "angle_plate",
        "pose": {"origin_mm": [0.0, 0.0, 0.0], **UP},
        "solids": [_box("angle:upright", [-10.0, 20.0, -10.0], [60.0, 12.0, 40.0])],
        "clamps": [_strap([20.0, 10.0, clamp_z])],
        "debts": [],
        "gaps": [],
    }


def _scene(result, setup="S1"):
    return result["setups"][setup]


def test_each_holding_kind_renders_exact_components_without_debts(engine, parts):
    centre = {
        "name": "dead-centre",
        "dia_mm": 20.0,
        "length_mm": 40.0,
        "point_angle_deg": 60.0,
        "quill_dia_mm": 30.0,
        "quill_extension_mm": 10.0,
        "tip_mm": [0.0, 0.0, 30.0],
    }
    holds = {
        "chuck_3jaw": (parts["bar"], _chuck(centre=centre)),
        "chuck_4jaw": (parts["bar"], _chuck(jaws=4, clock=45.0)),
        "dividing_head": (
            parts["bar"],
            _chuck(
                fixture_kind="dividing_head",
                head_solids=[_box("BS-0:body", [-60.0, -60.0, -80.0], [120.0, 120.0, 80.0])],
            ),
        ),
        "angle_plate": (parts["plate"], _plate_hold()),
    }
    for kind, (step, hold) in holds.items():
        setup = _scene(engine.run(engine.job(step, setups=[_setup([], hold)])))
        scene = setup["render_scene"]
        assert scene["fixture_kind"] == kind
        assert scene["debts"] == [], kind
        assert scene["components"] and all(c["exact"] for c in scene["components"]), kind
        assert setup["fixture_rendered"] is True, kind
    roles = {c["name"]: c["role"] for c in scene["components"]}
    assert roles == {"angle:upright": "fixture", "kit/strap:strap": "clamp"}


@pytest.mark.parametrize(("button_y", "section_y"), [((2.0, 6.0), 4.0), ((-8.0, 28.0), 10.0)])
def test_a_bench_section_cuts_through_the_holding_that_touches_the_work(
    engine, parts, button_y, section_y
):
    # The 40 x 20 plate sits on one button under it. A section on the plate's centre plane
    # (Y 10) misses a button standing at Y 2..6, so the picture would draw no contact.
    low, high = button_y
    hold = {
        "kind": "solids",
        "fixture_kind": "custom",
        "pose": {"origin_mm": [0.0, 0.0, 0.0], **UP},
        "solids": [_box("rest:button", [15.0, low, -5.0], [10.0, high - low, 5.0])],
        "debts": [],
        "gaps": [],
    }
    setup = _scene(
        engine.run(
            engine.job(parts["plate"], setups=[{**_setup([], hold), "machine_kind": "bench"}])
        )
    )
    scene = setup["render_scene"]
    assert scene["view"] == "elevation"
    assert scene["section"] == {"axis": "y", "at_mm": section_y}


def test_chuck_jaws_close_on_the_stock_at_their_clock_angles(engine, parts):
    setup = _scene(engine.run(engine.job(parts["bar"], setups=[_setup([], _chuck(clock=30.0))])))
    assert setup["chuck"]["jaw_angles_deg"] == [30.0, 150.0, 270.0]
    assert setup["chuck"]["contact_radii_mm"] == [10.0, 10.0, 10.0]
    assert setup["grip_zone_z_mm"] == [0.0, 10.0]
    names = [c["name"] for c in setup["render_scene"]["components"]]
    assert names == ["chuck jaw 1", "chuck jaw 2", "chuck jaw 3", "chuck body"]


def test_chuck_without_stock_in_its_jaws_is_unresolved_not_drawn(engine, parts):
    # Jaw face 5 mm below the bar: nothing lies in the grip zone.
    setup = _scene(engine.run(engine.job(parts["bar"], setups=[_setup([], _chuck(face_z=-5.0))])))
    assert "no stock lies within the chuck jaws" in setup["fixture_reason"]
    assert setup["fixture_rendered"] is False


def test_dividing_head_chuck_wall_is_sampled_along_its_horizontal_axis(engine, parts):
    # Setup z is model X, so the R10 bar (model Z) lies along setup x in the head's chuck.
    frame = {"origin": [0, 0, 0], "x": [0, 0, 1], "y": [0, -1, 0], "z": [1, 0, 0]}
    hold = _chuck(
        fixture_kind="dividing_head",
        pose={"origin_mm": [10.0, 0.0, 0.0], "x": [0.0, 0.0, 1.0], "z": [1.0, 0.0, 0.0]},
    )
    setup = _scene(engine.run(engine.job(parts["bar"], setups=[_setup([], hold, frame)])))
    assert setup["chuck"]["contact_radii_mm"] == [10.0, 10.0, 10.0]
    # A solid bar's run under each jaw crosses the axis: its full diameter.
    assert setup["min_wall_mm"] == pytest.approx(20.0, abs=1e-6)


def test_cutter_beside_the_gripped_bar_hits_a_chuck_jaw(engine, parts):
    step = parts["bar"]
    side = engine.refs(step, (-10, -10, 0), (10, 10, 30), kind="Cylinder")
    assert len(side) == 1
    ops = [_op("S1:10", "od", 3.0, 25.0, 30.0)]
    result = engine.run(engine.job(step, {"od": side}, [_setup(ops, _chuck())]))
    op = result["ops"]["S1:10"]
    assert op["tool_hits"] > 0
    assert any(name.startswith("chuck jaw") for name in op["obstacles"]["tool"])
    # The same chuck leaves the bar's top face clear.
    top = engine.refs(step, (-10, -10, 30), (10, 10, 30))
    ops = [_op("S1:20", "top", 3.0, 25.0, 30.0)]
    clear = engine.run(engine.job(step, {"top": top}, [_setup(ops, _chuck())]))
    assert clear["ops"]["S1:20"]["tool_hits"] == 0


def test_cutter_beside_a_strap_hits_the_clamp_and_debts_misplaced_straps(engine, parts):
    step = parts["plate"]
    top = engine.refs(step, (0, 0, 10), (40, 20, 10))
    assert len(top) == 1
    ops = [_op("S1:10", "top", 3.0, 10.0, 40.0)]
    result = engine.run(engine.job(step, {"top": top}, [_setup(ops, _plate_hold())]))
    op = result["ops"]["S1:10"]
    assert op["tool_hits"] > 0 and "kit/strap:strap" in op["obstacles"]["tool"]
    sunk = _scene(engine.run(engine.job(step, setups=[_setup([], _plate_hold(clamp_z=8.0))])))
    assert any(
        "kit/strap:strap intersects the setup-entry stock" in d
        for d in sunk["render_scene"]["debts"]
    )
    assert sunk["fixture_rendered"] is False
    floating = _scene(engine.run(engine.job(step, setups=[_setup([], _plate_hold(clamp_z=12.0))])))
    assert (
        "clamp 1 kit/strap does not bear on the stock at its pose"
        in floating["render_scene"]["debts"]
    )


def _gripped_hold(clamp_z=10.0, clamps=True):
    """A body gripping the strap's free end 5 mm off the plate, as a bench vise grips the
    stud of filing buttons pressed on the work; it never touches the plate itself."""
    return {
        "kind": "solids",
        "fixture_kind": "custom",
        "pose": {"origin_mm": [0.0, 0.0, 0.0], **UP},
        "solids": [_box("vise:jaws", [-15.0, 4.0, clamp_z], [10.0, 12.0, 8.0])],
        "clamps": [_strap([20.0, 10.0, clamp_z])] if clamps else [],
        "debts": [],
        "gaps": [],
    }


def test_a_holding_body_reaches_the_work_through_a_clamp_that_bears_on_it(engine, parts):
    step = parts["plate"]
    # One clamp's heel touches the body and its strap the plate, 8 mm of air between them:
    # members of one clamp carry no load across a gap.
    split = _gripped_hold()
    split["clamps"][0]["solids"] = [
        _box("kit/strap:heel", [-25.0, -6.0, 0.0], [2.0, 12.0, 8.0]),
        _box("kit/strap:strap", [-15.0, -6.0, 0.0], [40.0, 12.0, 8.0]),
    ]
    holds = [_gripped_hold(), _gripped_hold(clamp_z=12.0), _gripped_hold(clamps=False), split]
    gripped, floating, alone, apart = (
        _scene(result)
        for result in engine.run(
            {"jobs": [engine.job(step, setups=[_setup([], hold)]) for hold in holds]}
        )["results"]
    )
    assert gripped["render_scene"]["debts"] == []
    assert gripped["fixture_rendered"] is True
    # Gripping a strap that bears on nothing, nothing at all, or a member cut off from the
    # one that bears does not hold the work.
    debt = (
        "custom fixture solids touch neither the stock nor a clamp bearing on it at the "
        "declared pose"
    )
    for setup in (floating, alone, apart):
        assert debt in setup["render_scene"]["debts"]
        assert setup["fixture_rendered"] is False


def test_undrawn_fixture_components_leave_clear_samples_unknown(engine, parts):
    step = parts["plate"]
    top = engine.refs(step, (0, 0, 10), (40, 20, 10))
    hold = {**_plate_hold(), "clamps": [], "gaps": ["clamp 1 'kit/strap' pose is undeclared"]}
    ops = [_op("S1:10", "top", 3.0, 10.0, 40.0)]
    result = engine.run(engine.job(step, {"top": top}, [_setup(ops, hold)]))
    op, setup = result["ops"]["S1:10"], _scene(result)
    assert (
        op["tool_hits"] == "unknown" and "undrawn fixture components" in op["reasons"]["tool_hits"]
    )
    assert setup["fixture_rendered"] is False
    assert "not drawn: clamp 1 'kit/strap' pose is undeclared" in setup["render_scene"]["debts"]


# The plate's raw stock is 2 mm taller: op S1:10 takes that layer off its top.
_TALL = {
    "shape": "box",
    "origin_mm": [0.0, 0.0, 0.0],
    "axis": [1.0, 0.0, 0.0],
    "section_axis": [0.0, 1.0, 0.0],
    "length_mm": 40.0,
    "section_mm": [20.0, 12.0],
}


def _behind(**extra):
    """An angle plate whose upright stands 10 mm behind the plate (y 30..35), on its base."""
    return {
        "kind": "solids",
        "fixture_kind": "angle_plate",
        "pose": {"origin_mm": [0.0, 0.0, 0.0], **UP},
        "solids": [
            _box("plate:upright", [0.0, 30.0, 0.0], [40.0, 5.0, 20.0]),
            _box("plate:base", [0.0, 0.0, -5.0], [40.0, 35.0, 5.0]),
        ],
        "clamps": [],
        "debts": [],
        "gaps": [],
        **extra,
    }


def _clearances(engine, step, ops, hold, scene=False):
    top = engine.refs(step, (0, 0, 10), (40, 20, 10))
    job = engine.job(step, {"top": top}, [_setup(ops, hold)], stock=_TALL)
    render = _scene(engine.run(job))["render_scene"]
    return render if scene else render["cut_clearances"]


def _passes(*ys):
    """A facing raster at the plate's top, Z10: one pass along X per ``ys``."""
    return {"paths": [{"xy_mm": [[-5.0, y], [45.0, y]], "z_mm": [10.0, 10.0]} for y in ys]}


def _facing(subject="S1:10", feature="top", **extra):
    """A 6 mm end mill, flutes 10 long, on a 6 mm shank, its holder face 40 above the tip."""
    tool = {"shank_radius_mm": 3.0, "shank_from_mm": 10.0}
    return {**_op(subject, feature, 3.0, 10.0, 40.0), **tool, **extra}


@pytest.mark.parametrize(
    "hold",
    [
        _behind(gaps=["clamp 1 near-cut pose is undeclared"]),
        {"kind": "unknown", "reason": "fixture dimensions unknown"},
    ],
    ids=["a-component-undrawn", "no-holding-drawn"],
)
def test_a_cut_beside_holding_not_wholly_drawn_has_an_unknown_clearance(engine, parts, hold):
    # The last pass at Y19 runs the cutter out to Y22, 8 short of the upright (Y30).
    ops = [_facing(tool_paths=_passes(3.0, 9.0, 15.0, 19.0))]
    # Wholly drawn, the upright is the holding nearest the tool.
    expected = [{"op": "10", "mm": 8.0, "tag": "plate:upright"}]
    assert _clearances(engine, parts["plate"], ops, _behind()) == expected
    # An undrawn component may stand nearer; with none drawn, nothing is measured at all.
    unknown = [{"op": "10", "mm": "unknown", "tag": "unknown"}]
    assert _clearances(engine, parts["plate"], ops, hold) == unknown


def test_the_first_cut_the_stock_builder_cannot_derive_has_an_unknown_clearance(engine, parts):
    # Op 10's feature is undeclared: its cut, and so every later one, is unknown. Their
    # commanded passes are known, but a cutter goes wherever its op takes material off,
    # printed or not: with that unknown, so is how near the holding it goes.
    passes = _passes(3.0, 9.0, 15.0, 19.0)
    ops = [_facing(feature="missing", tool_paths=passes), _facing("S1:20", tool_paths=passes)]
    assert _clearances(engine, parts["plate"], ops, _behind()) == [
        {"op": "10", "mm": "unknown", "tag": "unknown"},
        {"op": "20", "mm": "unknown", "tag": "unknown"},
    ]


def _ledge():
    """An angle plate whose upright stands 2 mm past the plate (Y 22..27), its top at Z8."""
    return {
        **_behind(),
        "solids": [
            _box("plate:upright", [0.0, 22.0, -5.0], [40.0, 5.0, 13.0]),
            _box("plate:base", [0.0, 0.0, -5.0], [40.0, 22.0, 5.0]),
        ],
    }


def test_the_clearance_is_the_tools_whole_sweep_over_the_holding_not_the_material_cut(
    engine, parts
):
    # The last pass at Y21 overhangs the plate's edge: the cutter sweeps Y18..24 at Z10,
    # over the upright's top at Z8. The layer it takes off (Y0..20, Z10..12) is 2.83 from
    # the upright; the cutter itself passes 2.0 over it, and that is the clearance.
    ops = [_facing(tool_paths=_passes(3.0, 9.0, 15.0, 21.0))]
    scene = _clearances(engine, parts["plate"], ops, _ledge(), scene=True)
    assert scene["cut_clearances"] == [{"op": "10", "mm": 2.0, "tag": "plate:upright"}]
    # The picture dimensions that same sweep: one number in the picture and the table.
    cut = scene["closest_cut"]
    assert (cut["tag"], cut["mm"]) == ("plate:upright", pytest.approx(2.0, abs=1e-6))
    assert cut["from_mm"][2] == pytest.approx(10.0) and cut["to_mm"][2] == pytest.approx(8.0)
    # The holder rides 40 above the tip and 7 mm wider than the cutter: an upright at Y32
    # standing to Z55 is 8 from the cutter but 1 from the holder.
    tall = _ledge()
    tall["solids"][0] = _box("plate:upright", [0.0, 32.0, -5.0], [40.0, 5.0, 60.0])
    [row] = _clearances(engine, parts["plate"], ops, tall)
    assert (row["tag"], row["mm"]) == ("plate:upright", pytest.approx(1.0, abs=1e-6))


def test_a_cutter_goes_wherever_its_op_takes_material_off_printed_or_not(engine, parts):
    # The printed passes stop at Y3 (the cutter sweeps Y0..6, 10 over the base) yet the op
    # takes the whole top layer off (Y0..20, Z10..12): its cutter must reach the layer's
    # edge, 2.83 from the upright, whatever the table prints.
    ops = [_facing(tool_paths=_passes(3.0))]
    [row] = _clearances(engine, parts["plate"], ops, _ledge())
    assert (row["tag"], row["mm"]) == ("plate:upright", pytest.approx(2 * math.sqrt(2), abs=1e-6))


def test_a_closed_path_narrower_than_the_tool_is_swept_whole(engine, parts):
    # A loop 10 x 4 at the plate's edge (X15..25, Y17..21): the cutter, shank and holder are
    # each wider than it, so no wire is left offset inward of it. The sweep is still every
    # point within each radius of the loop: the cutter overhangs to Y24, 2.0 over the
    # upright's top, nearer than the layer the op takes off (2.83).
    loop = [[15.0, 17.0], [25.0, 17.0], [25.0, 21.0], [15.0, 21.0], [15.0, 17.0]]
    ops = [_facing(tool_paths={"paths": [{"xy_mm": loop, "z_mm": [10.0, 10.0]}]})]
    assert _clearances(engine, parts["plate"], ops, _ledge()) == [
        {"op": "10", "mm": 2.0, "tag": "plate:upright"}
    ]


@pytest.mark.parametrize(
    "op",
    [
        _facing(),
        {**_op("S1:10", "top", 3.0, 10.0, 40.0), "tool_paths": _passes(3.0, 9.0, 15.0, 21.0)},
    ],
    ids=["no-commanded-path", "no-shank-dimensions"],
)
def test_a_tool_sweep_that_cannot_be_derived_is_an_unknown_clearance(engine, parts, op):
    # The material cut is no stand-in for the tool: the row and the picture stay unknown.
    scene = _clearances(engine, parts["plate"], [op], _ledge(), scene=True)
    assert scene["cut_clearances"] == [{"op": "10", "mm": "unknown", "tag": "unknown"}]
    assert scene["closest_cut"] is None


def _moves(sweep):
    paths = sweep["paths"]
    return sorted((tuple(map(tuple, path["xy_mm"])), tuple(path["z_mm"])) for path in paths)


def test_the_commanded_sweep_is_every_pass_at_every_level_and_every_move_between_them():
    from prechips.kernel import tool_paths

    levels = {"levels": [2.0, 0.0], "dro_start_z": 4.0}
    operations = [{"op": 10, "dro_to_z": 0.0, "z_levels": levels}, {"op": 20, "dro_to_z": 0.0}]
    passes = [[[0.0, 0.0], [10.0, 0.0]], [[0.0, 4.0], [10.0, 4.0]]]
    raster = {"op": 10, "cutter_centre": passes, "raster": {"lift_z": 6.0}}
    outline = {"op": 20, "cutter_centre": [[0.0, 0.0], [5.0, 0.0], [5.0, 5.0]]}
    tables = {"operations": operations, "profiles": [raster, outline]}
    # Each pass is cut at Z2 then Z0. After each the cutter lifts to Z6 and rapids to the
    # next pass's start, the last back to the first for the next level: each pass end
    # stands from the floor to the lift. Inch tables scale to millimetres.
    sweep = tool_paths({"op": 10}, tables, "in")
    assert (sweep["levels_mm"], sweep["entry_z_mm"]) == ([0.0, 50.8], 101.6)
    assert _moves(tool_paths({"op": 10}, tables, "mm")) == sorted(
        [
            (((0.0, 0.0), (10.0, 0.0)), (0.0, 2.0)),
            (((0.0, 4.0), (10.0, 4.0)), (0.0, 2.0)),
            *(((end,), (0.0, 6.0)) for end in ((0.0, 0.0), (10.0, 0.0), (0.0, 4.0), (10.0, 4.0))),
            (((10.0, 0.0), (0.0, 4.0)), (6.0, 6.0)),
            (((10.0, 4.0), (0.0, 0.0)), (6.0, 6.0)),
        ]
    )
    # An outline at its one level enters and leaves at its ends.
    assert _moves(tool_paths({"op": 20}, tables, "mm")) == sorted(
        [
            (((0.0, 0.0), (5.0, 0.0), (5.0, 5.0)), (0.0, 0.0)),
            (((0.0, 0.0),), (0.0, 0.0)),
            (((5.0, 5.0),), (0.0, 0.0)),
        ]
    )
    # An arc table's rows reach the kernel as its checkpoints; an unknown pass is unknown.
    rows = {"op": 10, "cutter_centre": [{"id": "A1", "x": 0.0, "y": 0.0}]}
    assert tool_paths({"op": 10}, {**tables, "profiles": [rows]}, "mm")["tables"] is True
    unknown = {**raster, "raster_reason": "open side unknown"}
    assert "open side unknown" in tool_paths({"op": 10}, {**tables, "profiles": [unknown]}, "mm")[
        "reason"
    ]
    assert tool_paths({"op": 30}, tables, "mm") is None



def _web_hold(*origins):
    """The web part on a bare custom floor solid, one strap (along y) per footprint origin."""
    across = {"x": [0.0, 1.0, 0.0], "z": [0.0, 0.0, 1.0]}
    clamps = [
        {**_strap(origin), "name": f"clamp {i} kit/strap", "pose": {"origin_mm": origin, **across}}
        for i, origin in enumerate(origins, start=1)
    ]
    return {
        **_plate_hold(),
        "fixture_kind": "custom",
        "solids": [_box("nest:floor", [-10.0, -10.0, -5.0], [80.0, 40.0, 5.0])],
        "clamps": clamps,
    }


@pytest.mark.parametrize(
    "origins,wall",
    [
        ([[15.0, 10.0, 3.0]], 3.0),  # strap over the thin web
        ([[50.0, 10.0, 15.0]], 15.0),  # strap over the thick boss
        ([[50.0, 10.0, 15.0], [15.0, 10.0, 3.0]], 3.0),  # the thinner footprint governs
    ],
)
def test_strap_wall_is_the_material_run_under_its_footprint(engine, parts, origins, wall):
    setup = _scene(engine.run(engine.job(parts["web"], setups=[_setup([], _web_hold(*origins))])))
    assert setup["min_wall_mm"] == pytest.approx(wall, abs=1e-6)
    assert setup["strap_wall_debts"] == []
    # The 50 mm strap overhangs the 20 mm wide part: those samples are over air, not loaded.
    loaded = {row["loaded"] for row in setup["strap_wall_map"]}
    assert loaded == {True, False}


def test_strap_that_bears_on_nothing_leaves_the_wall_unknown(engine, parts):
    hold = _web_hold([15.0, 10.0, 5.0])  # 2 mm above the web
    setup = _scene(engine.run(engine.job(parts["web"], setups=[_setup([], hold)])))
    assert setup["min_wall_mm"] == "unknown"
    assert (
        "clamp 1 kit/strap has no sampled footprint point bearing on the stock"
        in (setup["reasons"]["min_wall_mm"])
    )


def _cylinder(name, at, dia, length, **extra):
    return {
        "name": name,
        "shape": "cylinder",
        "at_mm": at,
        "axis": [0.0, 0.0, 1.0],
        "dia_mm": dia,
        "length_mm": length,
        **extra,
    }


DOWN = {"x": [1.0, 0.0, 0.0], "z": [0.0, 0.0, -1.0]}
_NEST = {"kind": "custom", "solids": [_box("floor", [-10.0, -10.0, -5.0], [60.0, 40.0, 5.0])]}
_PRESS = {"kind": "strap_clamp", "solids": [_box("strap", [-5.0, -6.0, 0.0], [10.0, 12.0, 8.0])]}


def _pinned(engine, parts, land=None, at=(30.0, 10.0)):
    """Kernel facts of the bored plate on a floor nest, pressed by a strap on its top at x 10
    and located by a pin hanging from the top at ``at``: a dia 4.003 land 6 long that
    ``locates`` the dia 4.004 bore (``land`` overrides its fields) under a dia 8 collar that
    rests on the top. The hold goes through the host inputs, as a plan's does."""
    pin = {
        "kind": "locating_pin",
        "solids": [
            {**_cylinder("land", [0.0, 0.0, 0.0], 4.003, 6.0, locates="the bore"), **(land or {})},
            _cylinder("collar", [0.0, 0.0, -5.0], 8.0, 5.0),
        ],
    }
    hold = {
        "fixture": "nest",
        "pose": {"origin_mm": [0.0, 0.0, 0.0], **UP},
        "clamps": [
            {"ref": "strap", "restraint": "press", "pose": {"origin_mm": [10.0, 10.0, 10.0], **UP}},
            {"ref": "pin", "restraint": "locate", "pose": {"origin_mm": [*at, 10.0], **DOWN}},
        ],
    }
    host = _hold({"nest": _NEST, "strap": _PRESS, "pin": pin}, hold)
    job = engine.job(parts["bored"], setups=[_setup([], _engine_hold(host))])
    return _scene(engine.run(job))


def test_a_locating_pin_bears_in_the_bore_its_land_stands_in(engine, parts):
    setup = _pinned(engine, parts)
    assert setup["strap_wall_debts"] == []
    # The pin carries no clamping load: the wall is the run under the press strap alone.
    assert setup["min_wall_mm"] == pytest.approx(10.0, abs=1e-6)
    (bearing,) = setup["locator_bearings"]
    assert bearing["clamp"] == "clamp 2 pin" and bearing["solid"] == "clamp 2 pin:land"
    assert bearing["bears"] == "bore"
    assert bearing["pin_dia_mm"] == 4.003 and bearing["bore_dia_mm"] == 4.004
    assert bearing["gap_mm"] == pytest.approx(0.0005, abs=1e-6)
    assert bearing["axis_offset_mm"] == pytest.approx(0.0, abs=1e-6)
    assert bearing["engaged_mm"] == pytest.approx(6.0, abs=1e-6)


@pytest.mark.parametrize(
    "land,at,debt",
    [
        # Beside the plate (x 0..40): the land stands in air.
        (None, (45.0, 10.0), "stands in no bore of the stock and has no flat face bearing on it"),
        # Oversize: it cannot enter the bore it is drawn in.
        ({"dia_mm": 4.1}, (30.0, 10.0), "dia 4.1 is larger than the dia 4.004 bore it stands in"),
        # Loose: the collar rests on the top, but the land itself touches nothing.
        (
            {"dia_mm": 3.9},
            (30.0, 10.0),
            "dia 3.9 comes no nearer than 0.052 to the wall of the dia 4.004 bore it stands in",
        ),
    ],
)
def test_a_locating_pin_that_does_not_bear_in_a_bore_is_a_wall_debt(engine, parts, land, at, debt):
    setup = _pinned(engine, parts, land, at)
    assert setup["locator_bearings"] == []
    (named,) = setup["strap_wall_debts"]
    assert named.startswith("clamp 2 pin:land " + debt), named


def test_a_locating_pin_whose_land_is_unmeasured_stays_unproven(engine, parts):
    setup = _pinned(engine, parts, {"dia_mm": "unknown"})
    assert setup["locator_bearings"] == []
    debts = setup["strap_wall_debts"]
    assert any(debt.startswith("clamp 2 pin solid land: needs shape") for debt in debts), debts
    # Its collar on the top is drawn, but it is not the solid that locates.
    assert "clamp 2 pin draws no solid that declares what it locates" in debts


def _stud_hold(stud_x, hole=True):
    """The plate on a custom floor plate; a strap whose Ø6 stud drops ``stud_x`` along it.

    Strap underside centre on the plate top at (20, 10, 10); the stud runs from the floor
    bottom (z -10) up through the strap's slot; a heel at strap x -45..-39 rests on the floor.
    """
    floor = [_box("nest:floor", [-30.0, -10.0, -10.0], [100.0, 40.0, 10.0])]
    if hole:
        floor.append(_cylinder("nest:hole", [20.0 - 35.0, 10.0, -11.0], 8.0, 12.0, void=True))
    strap = [
        _box("kit/strap:beam", [-45.0, -6.0, 0.0], [70.0, 12.0, 8.0]),
        {
            **_box("kit/strap:slot", [stud_x - 4.0, -3.5, -1.0], [8.0, 7.0, 10.0]),
            "void": True,
            "local": "slot",
            "cuts": ["beam"],
        },
        _cylinder("kit/strap:stud", [stud_x, 0.0, -20.0], 6.0, 36.0, local="stud"),
        _box("kit/strap:heel", [-45.0, -6.0, -10.0], [6.0, 12.0, 10.0]),
    ]
    strap[0]["local"] = "beam"
    return {
        **_plate_hold(),
        "fixture_kind": "custom",
        "solids": floor,
        "clamps": [{**_strap([20.0, 10.0, 10.0]), "solids": strap}],
    }


@pytest.mark.parametrize(
    "stud_x,hole,clash",
    [
        (-35.0, True, None),  # stud beside the part through the floor's clearance hole
        (-35.0, False, "nest:floor interpenetrates kit/strap:stud"),  # no hole drawn
        (5.0, True, "kit/strap:stud interpenetrates the setup-entry stock"),  # through the part
    ],
)
def test_strap_stud_and_heel_only_touch_the_work_and_the_floor(engine, parts, stud_x, hole, clash):
    hold = _stud_hold(stud_x, hole)
    setup = _scene(engine.run(engine.job(parts["plate"], setups=[_setup([], hold)])))
    assert setup["fixture_clash_debts"] == []
    clashes = setup["fixture_clashes"]
    if clash is None:
        assert clashes == []  # heel on the floor and beam on the plate are contacts
    else:
        assert any(text.startswith(clash) for text in clashes), clashes


@pytest.mark.parametrize(
    "riser_across,parallel_ys,clash",
    [
        (16.0, (3.0, 17.0), None),  # inside the 0..20 opening
        (30.0, (3.0, 17.0), "riser 1 blocks spans y -5.0..25.0 mm"),  # wider than the opening
        (16.0, (1.0, 17.0), "parallel 1 spans y -1.0..3.0 mm"),  # overhangs the moving jaw
    ],
)
def test_vise_parallels_and_risers_fit_the_jaw_opening(
    engine, parts, riser_across, parallel_ys, clash
):
    # Plate 40 x 20 x 10 gripped across Y (opening y 0..20); parallels 4 wide below it.
    hold = _vise(5.0, centre=20.0, parallels=(40.0, 4.0, [[20.0, y] for y in parallel_ys]))
    hold["riser"] = {
        "name": "blocks",
        "size_mm": [25.0, riser_across, 25.0],
        "centres_mm": [[20.0, 10.0]],
    }
    setup = _scene(engine.run(engine.job(parts["plate"], setups=[_setup([], hold)])))
    assert setup["fixture_clash_debts"] == []
    if clash is None:
        assert setup["fixture_clashes"] == []
    else:
        assert any(text.startswith(clash) for text in setup["fixture_clashes"])


def test_undrawn_or_unplaced_fixture_leaves_interference_unknown(engine, parts):
    hold = {**_plate_hold(), "clamps": [], "gaps": ["clamp 1 'kit/strap' pose is undeclared"]}
    setup = _scene(engine.run(engine.job(parts["plate"], setups=[_setup([], hold)])))
    assert setup["fixture_clashes"] == []
    assert setup["fixture_clash_debts"] == ["clamp 1 'kit/strap' pose is undeclared"]
    # Jaws standing above material-free space are not placed: parallels cannot be checked.
    unplaced = _vise(0.0, centre=20.0, parallels=(40.0, 4.0, [[20.0, 3.0], [20.0, 17.0]]))
    setup = _scene(engine.run(engine.job(parts["plate"], setups=[_setup([], unplaced)])))
    assert any(debt.startswith("vise jaws not placed") for debt in setup["fixture_clash_debts"])


@pytest.mark.parametrize("origin_x,clashes", [(-4.0, False), (-2.0, True)])
def test_stop_contact_is_allowed_but_stock_overlap_is_reported(engine, parts, origin_x, clashes):
    hold = _plate_hold()
    hold["stop"] = {
        "pose": {"origin_mm": [origin_x, 8.0, 0.0], **UP},
        "solids": [_box("stop:left", [0.0, 0.0, 0.0], [4.0, 4.0, 10.0])],
    }
    row = _scene(engine.run(engine.job(parts["plate"], setups=[_setup([], hold)])))
    assert any(component["name"] == "stop:left" for component in row["render_scene"]["components"])
    assert any("stop:left" in clash for clash in row["fixture_clashes"]) is clashes
    assert row["fixture_rendered"] is not clashes


# --------------------------------------------------------------------------- host inputs


class _Inventory:
    def __init__(self, inventory):
        self.inventory = inventory


_CHUCK_ITEM = {
    "kind": "chuck_3jaw",
    "body_dia_mm": 150.0,
    "body_length_mm": 60.0,
    "bore_dia_mm": 30.0,
    "jaw_width_mm": 16.0,
    "jaw_height_mm": 25.0,
    "jaw_depth_mm": 20.0,
}
_CHUCK_HOLD = {
    "fixture": "chuck",
    "pose": {"origin_mm": [0.0, 0.0, 10.0], **UP},
    "jaw_clock_deg": 0.0,
    "grip_mm": 10.0,
}


def _hold(fixtures, hold, machines=None):
    bundle = _Inventory(
        {"fixtures": fixtures, "machines": machines or {"lathe": {"kind": "lathe"}}}
    )
    return hold_inputs(bundle, {"machine": "lathe", "hold": hold})


def test_chuck_inputs_pass_only_trusted_dimensions_and_poses():
    ready = _hold({"chuck": _CHUCK_ITEM}, _CHUCK_HOLD)
    assert "reason" not in ready and ready["jaws"] == 3 and ready["jaw_depth_mm"] == 20.0
    flagged = {**_CHUCK_ITEM, "jaw_depth_mm": {"value": 20.0, "verify": True}}
    unverified = _hold({"chuck": flagged}, _CHUCK_HOLD)
    assert "jaw_depth_mm" in unverified["reason"] and "jaw_depth_mm" not in unverified
    skewed = {**_CHUCK_HOLD, "pose": {"origin_mm": [0, 0, 0], "x": [1, 0, 0], "z": [1, 0, 0]}}
    assert "pose" in _hold({"chuck": _CHUCK_ITEM}, skewed)["reason"]


def test_unverified_solids_and_undeclared_supports_become_gaps():
    plate = {
        "kind": "angle_plate",
        "solids": [
            {**_box("upright", [0, 0, 0], [10, 10, 10]), "verify": True},
            {**_box("base", [0, 0, 0], [10, 10, 10]), "measured": MEASURED},
        ],
    }
    hold = _hold({"angle": plate}, {"fixture": "angle", "pose": {"origin_mm": [0, 0, 0], **UP}})
    assert [solid["name"] for solid in hold["solids"]] == ["angle:base"]
    assert hold["gaps"] == ["angle solid upright: This fact explicitly requires verification."]
    centre = {"kind": "dead_centre", "dia_mm": 20.0, "length_mm": 40.0, "point_angle": 60.0}
    supported = _hold(
        {"chuck": _CHUCK_ITEM, "centre": centre},
        {**_CHUCK_HOLD, "support": "centre", "support_tip_mm": [0, 0, 30]},
    )
    assert "centre" not in supported
    assert supported["gaps"] == [
        "dead centre 'centre' not drawn: quill_dia_mm, quill_extension_mm unresolved"
    ]


@pytest.mark.parametrize(
    "cuts,drawn",
    [
        (None, []),  # a bore that names no target withholds every solid of its owner
        (["plate"], ["base:stand"]),  # only the solid it cuts is withheld
    ],
)
def test_unresolved_void_withholds_the_solids_it_cuts(cuts, drawn):
    bore = {**_cylinder("bore", [0, 0, -1], 6.6, 30), "void": True, "verify": True}
    if cuts is not None:
        bore["cuts"] = cuts
    base = {
        "kind": "custom",
        "solids": [
            {**_box("plate", [-20, -20, 0], [40, 40, 10]), "measured": MEASURED},
            {**_cylinder("stand", [15, 15, 10], 9.5, 12), "measured": MEASURED},
            bore,
        ],
    }
    hold = _hold({"base": base}, {"fixture": "base", "pose": {"origin_mm": [0, 0, 0], **UP}})
    assert [solid["name"] for solid in hold.get("solids", [])] == drawn
    assert "base solid plate: not drawn, its void bore is unresolved" in hold["gaps"]


def _measured(value):
    return {"value": value, "measured": MEASURED}


_FOLLOW = {
    "kind": "follow_rest",
    "jaw_width_mm": _measured(12.0),
    "jaw_height_mm": _measured(40.0),
    "jaw_depth_mm": _measured(10.0),
    "jaw_angles_deg": [90.0, 180.0],
}


def _rested(reference, item, entry):
    """Host hold inputs of a chucked S1 with one rest table in ``hold.supports``."""
    bundle = _Inventory(
        {
            "fixtures": {"chuck": _CHUCK_ITEM, reference: item},
            "machines": {"lathe": {"kind": "lathe"}},
        }
    )
    hold = {**_CHUCK_HOLD, "supports": [{"ref": reference, **entry}]}
    return hold_inputs(bundle, {"id": "S1", "machine": "lathe", "hold": hold})


def test_follow_rest_jaws_reach_the_engine_only_when_every_jaw_fact_is_measured():
    entry = {"ops": [10], "jaw_lead_mm": 8.0}
    (ready,) = _rested("fr", _FOLLOW, entry)["follow_rests"]
    assert ready == {
        "name": "fr",
        "subjects": ["S1:10"],
        "side": "turned",
        "lead_mm": 8.0,
        "jaw_width_mm": 12.0,
        "jaw_height_mm": 40.0,
        "jaw_depth_mm": 10.0,
        "jaw_angles_deg": [90.0, 180.0],
    }
    # A bare number is no measurement, and the jaw directions are not defaulted.
    item = {key: value for key, value in _FOLLOW.items() if key != "jaw_angles_deg"}
    item["jaw_width_mm"] = 12.0
    hold = _rested("fr", item, {**entry, "jaw_side": "leading"})
    (rest,) = hold["follow_rests"]
    missing = [
        "plan hold.supports[fr].jaw_side (turned or uncut)",
        "fixtures.fr.jaw_width_mm (measured)",
        "fixtures.fr.jaw_angles_deg",
    ]
    assert rest["missing"] == missing and "jaw_width_mm" not in rest
    assert f"follow rest 'fr' not drawn: {', '.join(missing)} unresolved" in hold["debts"]


def test_steady_rest_without_measured_body_is_a_gap_naming_both_dimensions():
    item = {
        "kind": "steady_rest",
        "body_dia_mm": _measured(200.0),
        "body_length_mm": _measured(40.0),
    }
    ready = _rested("sr", item, {"at_z_mm": 30.0})
    assert ready["steady_rests"] == [
        {
            "name": "sr",
            "subjects": "all",
            "at_z_mm": 30.0,
            "body_dia_mm": 200.0,
            "body_length_mm": 40.0,
        }
    ]
    gapped = _rested("sr", {"kind": "steady_rest", "body_dia_mm": 200.0}, {"at_z_mm": 30.0})
    assert "steady_rests" not in gapped
    assert gapped["gaps"] == [
        "steady rest 'sr' not drawn: fixtures.sr.body_dia_mm (measured), "
        "fixtures.sr.body_length_mm (measured) unresolved"
    ]


_CENTRE_3_IN = {
    "name": "dead-centre",
    "dia_mm": 20.0,
    "length_mm": 40.0,
    "point_angle_deg": 60.0,
    "quill_dia_mm": 30.0,
    "quill_extension_mm": 10.0,
    "tip_mm": [0.0, 0.0, 27.0],
}


def test_a_dead_centre_seated_in_its_declared_centre_hole_is_not_a_stock_clash(engine, parts):
    # The tip sits 3 mm inside the bar's end face (z 30): the entry stock has no centre
    # hole, so the point overlaps it unless the hold declares the hole the centre rides in,
    # a 60 degree countersink whose mouth on that face is 2 * 3 tan 30 = 3.464 across.
    centre = _CENTRE_3_IN
    bare, seated = (
        _scene(engine.run(engine.job(parts["bar"], setups=[_setup([], _chuck(centre=c))])))
        for c in (centre, {**centre, "hole_dia_mm": 2 * 3.0 * math.tan(math.radians(30))})
    )
    stock = "dead centre dead-centre intersects the setup-entry stock"
    assert any(debt.startswith(stock) for debt in bare["render_scene"]["debts"])
    assert bare["fixture_rendered"] is False
    assert any("interpenetrates the setup-entry stock" in c for c in bare["fixture_clashes"])
    assert seated["render_scene"]["debts"] == []
    assert seated["fixture_rendered"] is True
    assert seated["fixture_clashes"] == []


def test_a_centre_short_of_its_declared_centre_hole_seat_does_not_hold_the_work(engine, parts):
    # A 5 mm mouth on the z 30 face puts the seat apex at z 25.67: the tip at z 27 stands
    # 1.33 mm short of it, touching nothing, so the work is not held on the centre.
    centre = {**_CENTRE_3_IN, "hole_dia_mm": 5.0}
    scene = _scene(engine.run(engine.job(parts["bar"], setups=[_setup([], _chuck(centre=centre))])))
    debts = scene["render_scene"]["debts"]
    assert any("does not seat in the declared centre hole" in debt for debt in debts)
    assert scene["fixture_rendered"] is False
