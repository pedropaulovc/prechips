"""Chuck, dead-centre, dividing-head, angle-plate/custom and clamp solids in the kernel.

Engine tests run ``freecad_job.py`` on solids authored here and read only its JSON;
host tests check which declared fixture facts reach the engine.
"""

import subprocess

import pytest
from test_kernel_geometry import Engine, _op, _setup, _vise

from prechips.kernel import hold_inputs

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
    assert len(paths) == 3, process.stdout[-2000:] + process.stderr[-2000:]
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
