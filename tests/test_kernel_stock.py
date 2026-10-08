"""Sequential in-process stock and the engine-only geometry cache key.

The engine sees the authored stock envelope minus what earlier setups' claimed faces
removed, never the finished solid; host-only plan fields never reach its job or cache key.
FreeCAD-backed tests run the ``freecad_job.py`` shipped beside the imported package and
skip without ``freecadcmd``.
"""

import hashlib
import json
import math
import subprocess
import sys
from pathlib import Path

import pytest
from test_geometry_rules import finding, rules_bundle
from test_kernel_geometry import IDENTITY, Engine, _op, _vise

from prechips import kernel
from prechips.inputs import Bundle
from prechips.model import Stock
from prechips.rules import accessibility, reach

ENGINE = Path(kernel.__file__).resolve().parent / "freecad_job.py"
BOX = {
    "shape": "box",
    "origin_mm": [0.0, 0.0, 0.0],
    "axis": [1.0, 0.0, 0.0],
    "section_axis": [0.0, 1.0, 0.0],
    "length_mm": 60.0,
    "section_mm": [40.0, 20.0],
}
PART = {"shape": "part"}  # explicit: the supply is the authored solid itself

_AUTHOR = r"""
import sys
import math
import Part
from FreeCAD import Vector as V
out = sys.argv[sys.argv.index("--") + 1]
# 60x40x20 block, +X half stepped down to z=10: floor x 30..60 and its wall at x=30.
Part.makeBox(60, 40, 20).cut(Part.makeBox(31, 42, 11, V(30, -1, 10))).exportStep(out + "/step.step")
# U channel: 60 long (x), rails y 0..5 and 35..40 up to z=20, floor z=10.
Part.makeBox(60, 40, 20).cut(Part.makeBox(62, 30, 11, V(-1, 5, 10))).exportStep(
    out + "/channel.step"
)
Part.makeBox(60, 40, 20).exportStep(out + "/block.step")
# A 1-degree drafted wall in the review's retained wedge (the wall faces down).
draft = 10 * math.tan(math.radians(1))
points = [V(30, 0, 20), V(30 + draft, 0, 10), V(61, 0, 10), V(61, 0, 21),
          V(30, 0, 21), V(30, 0, 20)]
cut = Part.Face(Part.makePolygon(points)).extrude(V(0, 40, 0))
Part.makeBox(60, 40, 20).common(cut).exportStep(out + "/draftstep.step")
# The actual stepped block with an upward-facing drafted wall: +Z clears only a sliver.
Part.makeBox(60, 40, 20).cut(cut).exportStep(out + "/updraftstep.step")
wide_cut = Part.Face(Part.makePolygon(points)).extrude(V(0, 200, 0))
Part.makeBox(60, 200, 20).cut(wide_cut).exportStep(out + "/wideupdraftstep.step")
# The stepped block with a 4 mm through hole in its floor, axis 6 mm from the x=30 wall.
step = Part.makeBox(60, 40, 20).cut(Part.makeBox(31, 42, 11, V(30, -1, 10)))
step.cut(Part.makeCylinder(2, 12, V(36, 20, -1))).exportStep(out + "/step-hole.step")
# A z10 floor (x >= 30) beside a shoulder up to z13, its 2 mm through hole 1.5 mm from it.
seat = Part.makeBox(60, 40, 13).cut(Part.makeBox(31, 42, 4, V(30, -1, 10)))
seat.cut(Part.makeCylinder(1, 12, V(31.5, 20, -1))).exportStep(out + "/seat.step")
# The stepped block's floor with a 6 mm through hole instead, its axis 6 mm from that wall.
step.cut(Part.makeCylinder(3, 12, V(36, 20, -1))).exportStep(out + "/wide-hole.step")
# A z10 plate whose 6 mm bore opens through a finished 4 mm neck from z8.5 up.
neck = Part.makeBox(60, 40, 10).cut(Part.makeCylinder(3, 9.5, V(36, 20, -1)))
neck.cut(Part.makeCylinder(2, 3, V(36, 20, 8))).exportStep(out + "/neck.step")
"""


# --------------------------------------------------------------------------- host cache


def _bundle(tmp_path):
    step = tmp_path / "part.step"
    step.write_bytes(b"local test STEP identity")
    return Bundle(
        {
            "part": "test-part",
            "stock": {**{k: v for k, v in BOX.items() if k != "shape"}, "material": "1018"},
            "setups": [
                {
                    "id": "S1",
                    "machine": "mill",
                    "frame": "A",
                    "stock_in": "stock",
                    "hold": {
                        "fixture": "vise",
                        "parallels": "parallels",
                        "fixed_jaw": "rear",
                        "jaws_along": "x",
                        "grip_mm": 4.0,
                        "jaw_above_parallels_mm": 4.0,
                        "method": "hard_jaws",
                    },
                    "ops": [
                        {
                            "op": 10,
                            "do": "finish_profile",
                            "feature": "pocket",
                            "tool": "em",
                            "holder": "holder",
                            "to_z": 5.0,
                        }
                    ],
                }
            ],
        },
        {
            "units": "mm",
            "step_sha256": hashlib.sha256(step.read_bytes()).hexdigest(),
            "frames": {"A": dict(IDENTITY)},
            "features": {"pocket": {"kind": "pocket", "faces": ["#1"], "finish_ra": 1.6}},
        },
        {
            "machines": {"mill": {"kind": "mill"}},
            "tools": {
                "em": {
                    "kind": "endmill",
                    "dia_mm": 6.0,
                    "flute_len_mm": 10.0,
                    "oal_mm": 30.0,
                    "projection_mm": {"holder": 25.0},
                    "verify": False,
                }
            },
            "holders": {
                "holder": {
                    "kind": "collet",
                    "gauge_dia_mm": 20.0,
                    "gauge_len_mm": 15.0,
                    "grip_mm": 10.0,
                    "verify": False,
                }
            },
            "fixtures": {
                "vise": {
                    "kind": "vise",
                    "jaw_width_mm": 50.0,
                    "jaw_depth_mm": 12.0,
                    "jaw_height_mm": 20.0,
                    "opening_mm": 60.0,
                    "verify": False,
                },
                "parallels": {"kind": "parallels", "height_mm": 16.0, "verify": False},
            },
        },
        {"required": {}, "numbers": {}, "numbers_verify": False},
        {},
        {"step": step},
        {},
        tmp_path,
    )


def _host_only(bundle):
    """Edits that change only host-rule inputs, never a field the engine reads."""
    setup = bundle.plan["setups"][0]

    yield "hold method", lambda: setup["hold"].update(method="soft_jaws")
    yield "hold grip_mm", lambda: setup["hold"].update(grip_mm=5.5)
    yield "fixture opening_mm", lambda: bundle.inventory["fixtures"]["vise"].update(opening_mm=90.0)
    # projection_mm is declared, so oal_mm (and the op reason its absence writes) is host-only.
    yield "tool oal_mm", lambda: bundle.inventory["tools"]["em"].update(oal_mm=40.0)
    yield "op reason", lambda: bundle.inventory["tools"]["em"].update(oal_mm="unknown")
    yield "holder grip", lambda: bundle.inventory["holders"]["holder"].update(grip_mm=12.0)
    yield "stock material", lambda: bundle.plan["stock"].update(material="6061")
    yield "stock top_z", lambda: setup.setdefault("stock_state", {}).update(top_z=20.0)
    yield "tool metadata verification", lambda: bundle.inventory["tools"]["em"].update(verify=True)
    yield (
        "holder source verification",
        lambda: bundle.inventory["holders"]["holder"].update(source={"verify": True}),
    )
    yield (
        "fixture member debt",
        lambda: bundle.inventory["fixtures"]["vise"].update(
            members={"other": {"jaw_depth_mm": {"value": 12.0, "verify": True}}}
        ),
    )


def _consumed(bundle):
    setup = bundle.plan["setups"][0]
    yield "op cutting action", lambda: setup["ops"][0].update(do="rough_profile")
    yield "rough allowance", lambda: setup["ops"][0].update(rough_allowance_mm=0.2)
    yield "jaw width", lambda: bundle.inventory["fixtures"]["vise"].update(jaw_width_mm=60.0)
    yield (
        "selected projection",
        lambda: bundle.inventory["tools"]["em"]["projection_mm"].update(holder=30.0),
    )
    yield (
        "selected projection debt",
        lambda: bundle.inventory["tools"]["em"]["projection_mm"].update(
            holder={"value": 30.0, "verify": True}
        ),
    )
    yield "stock origin", lambda: bundle.plan["stock"].update(origin_mm=[0.0, 0.0, -1.0])
    yield "op to_z", lambda: setup["ops"][0].update(to_z=4.0)
    bounds = {"x": [0.0, 30.0], "y": [0.0, 40.0], "z": [5.0, 20.0]}
    yield "op stock_removal_bounds", lambda: setup["ops"][0].update(stock_removal_bounds=bounds)
    yield "bounds span", lambda: bounds.update(z=[6.0, 20.0])
    # The named faces' heights are engine facts, so naming another face reruns it.
    yield (
        "stock top_feature",
        lambda: setup.setdefault("stock_state", {}).update(top_feature="pocket"),
    )
    yield (
        "stock bottom_feature",
        lambda: setup.setdefault("stock_state", {}).update(bottom_feature="seat"),
    )


def test_host_only_edits_reuse_the_cache_and_consumed_edits_rerun(tmp_path, monkeypatch):
    bundle = _bundle(tmp_path)
    calls = 0

    def execute(executable, batch):
        nonlocal calls
        calls += 1
        return {"results": [{"status": "ok"} for _ in batch["jobs"]]}

    monkeypatch.setattr(kernel, "discover_kernel", lambda: Path(sys.executable))
    monkeypatch.setenv("PRECHIPS_KERNEL_CACHE", str(tmp_path / "cache"))
    monkeypatch.setattr(kernel, "_execute", execute)
    kernel.run_geometry(bundle)
    assert calls == 1
    for name, edit in _host_only(bundle):
        edit()
        object.__setattr__(bundle, "kernel", None)
        kernel.run_geometry(bundle)
        assert calls == 1, f"host-only edit {name} reran FreeCAD"
    for count, (name, edit) in enumerate(_consumed(bundle), start=2):
        edit()
        object.__setattr__(bundle, "kernel", None)
        kernel.run_geometry(bundle)
        assert calls == count, f"consumed edit {name} reused a stale result"


def test_inch_stock_removal_bounds_convert_once(tmp_path):
    bundle = _bundle(tmp_path)
    op = bundle.plan["setups"][0]["ops"][0]
    op["stock_removal_bounds"] = {"x": [0, 1], "y": [-1, 0.5], "z": [0.25, 2]}
    bundle.features["units"] = "in"
    (inputs,) = kernel.build_job(bundle)["setups"][0]["ops"]
    assert inputs["stock_removal_bounds"] == {"x": [0, 25.4], "y": [-25.4, 12.7], "z": [6.35, 50.8]}


def test_a_plan_cannot_declare_its_supply_to_be_the_finished_part(tmp_path):
    bundle = _bundle(tmp_path)
    bundle.plan["stock"]["shape"] = "part"
    assert kernel.stock_inputs(bundle)["shape"] == "box"
    with pytest.raises(ValueError):
        Stock.model_validate({"shape": "part"})


# --------------------------------------------------------------------------- FreeCAD


class PackagedEngine(Engine):
    """The engine shipped with the imported package (so an older tree can be measured)."""

    def raw(self, payload):
        source, target = self.directory / "in.json", self.directory / "out.json"
        source.write_text(json.dumps(payload), encoding="utf-8")
        target.unlink(missing_ok=True)
        process = subprocess.run(
            [self.executable, str(ENGINE), "--", str(source), str(target)],
            capture_output=True,
            text=True,
            errors="replace",
            timeout=600,
        )
        assert target.exists(), process.stdout[-2000:] + process.stderr[-2000:]
        return target.read_bytes()

    def job(self, step, features=None, setups=(), as_is=(), stock=None):
        return super().job(step, features, setups, as_is, BOX if stock is None else stock)


@pytest.fixture(scope="module")
def solids(tmp_path_factory, freecad_kernel):
    directory = tmp_path_factory.mktemp("stock-solids")
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
    assert len(paths) == 10, process.stdout[-2000:] + process.stderr[-2000:]
    return paths


@pytest.fixture
def engine(tmp_path, freecad_kernel):
    return PackagedEngine(tmp_path, freecad_kernel)


def _setup(setup_id, ops, hold=None):
    return {"id": setup_id, "frame": IDENTITY, "hold": hold or _vise(12.0), "ops": ops}


def _floor_op(subject, to_z=None):
    op = _op(subject, "floor", 3.0, 15.0, 30.0)
    if to_z is not None:
        op["to_z"] = to_z
    return op


def _butt_joint(negative, positive, x=30.0):
    return {
        "kind": "surface",
        "refs": [negative, positive],
        "negative_ref": negative,
        "positive_ref": positive,
        "reason": None,
        "method": "weld",
        "process": "Fixture and weld the contacting rectangular butt faces.",
        "cite": ["AUTHOR'S CHOICE: two-piece butt joint"],
        "interfaces": [
            {
                "at_mm": [x, 20.0, 10.0],
                "normal": [1.0, 0.0, 0.0],
                "x": [0.0, 1.0, 0.0],
                "size_mm": [40.0, 20.0],
                "cite": ["AUTHOR'S CHOICE: internal stock interface"],
            }
        ],
    }


def test_later_setup_sees_material_an_earlier_setup_removed(engine, solids):
    step = solids["step"]
    floor = engine.refs(step, (30, 0, 10), (60, 40, 10))
    assert len(floor) == 1
    setups = [_setup("S1", [_floor_op("S1:10")]), _setup("S2", [_floor_op("S2:10")])]
    result = engine.run(engine.job(step, {"floor": floor}, setups))
    first, second = result["setups"]["S1"], result["setups"]["S2"]
    # S1 holds and draws the authored 60x40x20 box, not the stepped finished part.
    assert first["stock_bbox_mm"] == [0.0, 0.0, 0.0, 60.0, 40.0, 20.0]
    assert first["stock_volume_mm3"] == pytest.approx(48000.0)
    assert first["width_mm"] == 40.0 and first["render_png_base64"]
    finished = engine.run(
        engine.job(step, {"floor": floor}, [_setup("S2", [_floor_op("S2:10")])], stock=PART)
    )["ops"]["S2:10"]["tool_hits"]
    # Own allowance is cutting material, but boundary poses still meet the kept wall.
    assert result["ops"]["S1:10"]["tool_hits"] == finished > 0
    # S2 receives the block minus the region S1's floor claim swept away.
    assert second["stock_volume_mm3"] == pytest.approx(48000.0 - 30 * 40 * 10)
    assert second["render_png_base64"] and "stock_reason" not in second
    assert result["ops"]["S2:10"]["tool_hits"] == finished


def test_a_named_face_reports_its_height_and_the_entry_stock_over_it(engine, solids):
    step = solids["step"]
    features = {
        "floor": engine.refs(step, (30, 0, 10), (60, 40, 10)),
        "base": engine.refs(step, (0, 0, 0), (60, 40, 0)),
        "wall": engine.refs(step, (30, 0, 10), (30, 40, 20)),
    }
    assert all(len(refs) == 1 for refs in features.values())
    named = {"stock_features": sorted(features)}
    setups = [
        {**_setup("S1", [_floor_op("S1:10")]), **named},
        {**_setup("S2", [_floor_op("S2:10")]), **named},
    ]
    rows = engine.run(engine.job(step, features, setups))["setups"]
    first, second = rows["S1"]["stock_faces_mm"], rows["S2"]["stock_faces_mm"]
    # S1 receives the raw block, 10 mm of stock over the floor; S2 receives it cut.
    assert first["floor"]["up"] == {"face_z": 10.0, "stock_z": 20.0}
    assert second["floor"]["up"] == {"face_z": 10.0, "stock_z": 10.0}
    assert first["base"]["down"] == second["base"]["down"] == {"face_z": 0.0, "stock_z": 0.0}
    # Only a horizontal face has a height: a side the feature lacks says why.
    assert set(first["floor"]["down"]) == {"reason"} and set(first["wall"]["up"]) == {"reason"}
    assert (
        "stock_faces_mm"
        not in engine.run(engine.job(step, features, [_setup("S1", [])]))["setups"]["S1"]
    )


def _thru_drill(subject, radius):
    return {
        **_op(subject, "hole", radius, 25.0, 30.0),
        "do": "drill",
        "hole": {"thru": True, "entry_z_mm": 10.0, "point_angle_deg": 118.0},
    }


def test_a_face_keeps_its_height_when_an_oversize_hole_shaves_its_edge(engine, solids):
    # An R2.1 drill through the R2 hole of the faced floor takes a 0.1 mm ring from the
    # floor and the base, as a reamer over the drawn bore does; both faces remain.
    step = solids["step-hole"]
    features = {
        "floor": engine.refs(step, (30, 0, 10), (60, 40, 10), kind="Plane"),
        "base": engine.refs(step, (0, 0, 0), (60, 40, 0), kind="Plane"),
        "hole": engine.refs(step, (34, 18, 0), (38, 22, 10), kind="Cylinder"),
    }
    assert all(len(refs) == 1 for refs in features.values())
    face = {**_floor_op("S1:10"), "do": "face"}
    setups = [
        _setup("S1", [face, _thru_drill("S1:20", 2.1)]),
        {**_setup("S2", []), "stock_features": ["base", "floor"]},
    ]
    faces = engine.run(engine.job(step, features, setups))["setups"]["S2"]["stock_faces_mm"]
    assert faces["floor"]["up"] == {"face_z": 10.0, "stock_z": 10.0}
    assert faces["base"]["down"] == {"face_z": 0.0, "stock_z": 0.0}


def test_a_face_the_entering_stock_has_lost_has_no_height(engine, solids):
    # The R3 drill through the R2 neck removes the whole ring over the z8.5 shoulder.
    step = solids["neck"]
    features = {
        "shoulder": engine.refs(step, (33, 17, 8.5), (39, 23, 8.5), kind="Plane"),
        "hole": engine.refs(step, (34, 18, 8.5), (38, 22, 10), kind="Cylinder"),
    }
    assert all(len(refs) == 1 for refs in features.values())
    named = {"stock_features": ["shoulder"]}
    setups = [
        {**_setup("S1", [_thru_drill("S1:10", 3.0)]), **named},
        {**_setup("S2", []), **named},
    ]
    rows = engine.run(engine.job(step, features, setups, stock=PART))["setups"]
    assert rows["S1"]["stock_faces_mm"]["shoulder"]["down"] == {"face_z": 8.5, "stock_z": 8.5}
    lost = rows["S2"]["stock_faces_mm"]["shoulder"]["down"]
    assert set(lost) == {"reason"} and "does not carry" in lost["reason"]


def test_to_z_web_and_unclaimed_rails_stay_in_the_next_setup(engine, solids):
    step = solids["channel"]
    floor = engine.refs(step, (0, 5, 10), (60, 35, 10))
    assert len(floor) == 1
    webbed, cleared = (
        engine.run(
            engine.job(
                step,
                {"floor": floor},
                [
                    _setup("S1", [_floor_op("S1:10", to_z)]),
                    _setup("S2", [_floor_op("S2:10", to_z)]),
                ],
            )
        )
        for to_z in (15.0, None)
    )
    # A 5 mm web above the floor stays as overstock in the next setup's entry stock.
    assert webbed["setups"]["S2"]["stock_volume_mm3"] == pytest.approx(48000.0 - 60 * 30 * 5)
    finished = engine.run(
        engine.job(step, {"floor": floor}, [_setup("S2", [_floor_op("S2:10")])], stock=PART)
    )["ops"]["S2:10"]
    # That web lies below the tip, which stands at its authored to_z = 15, so it is not a
    # flute obstacle: only the 20 mm rails rise over the tip, 5 mm against 10 mm above
    # the z = 10 floor of the cleared channel and of the finished part.
    assert webbed["ops"]["S2:10"]["reach_depth_mm"] == 5.0
    assert cleared["ops"]["S2:10"]["reach_depth_mm"] == finished["reach_depth_mm"] == 10.0
    # Without to_z the channel is cleared; the unclaimed 5 mm rails are kept and gripped.
    assert webbed["setups"]["S1"]["min_wall_mm"] == 40.0
    s2 = cleared["setups"]["S2"]
    assert s2["stock_volume_mm3"] == pytest.approx(48000.0 - 60 * 30 * 10)
    assert s2["width_mm"] == 40.0 and s2["min_wall_mm"] == 5.0
    assert cleared["ops"]["S2:10"]["tool_hits"] == finished["tool_hits"]


@pytest.mark.parametrize(
    "shank, clash, shank_clear, verdict",
    [
        (2.5, False, 3.5, "pass"),
        (6.5, True, -0.5, "error"),
        (None, "unknown", "unknown", "unknown"),
    ],
)
def test_spot_reach_holder_and_shank_meet_the_stock_earlier_ops_leave(
    engine, solids, tmp_path, shank, clash, shank_clear, verdict
):
    # The facing op clears the 10 mm over the floor, across its hole; the setup-entry
    # block still holds it.
    # The R2.5 spot stands 0.5 deep on the floor 6 mm from the retained x=30 wall (z20).
    step = solids["step-hole"]
    floor = engine.refs(step, (30, 0, 10), (60, 40, 10), kind="Plane")
    hole = engine.refs(step, (34, 18, 0), (38, 22, 10), kind="Cylinder")
    assert len(floor) == len(hole) == 1
    face = {**_floor_op("S1:10"), "do": "face"}
    spot = {
        **_op("S1:20", "hole", 2.5, 6.0, 12.0, holder_radius=10.0),
        "do": "spot",
        "hole": {"thru": True, "depth_mm": 0.5, "entry_z_mm": 10.0, "point_angle_deg": 90.0},
        "shank_from_mm": 6.0,
    }
    if shank is not None:
        spot["shank_radius_mm"] = shank
    result = engine.run(
        engine.job(step, {"floor": floor, "hole": hole}, [_setup("S1", [face, spot])])
    )
    op = result["ops"]["S1:20"]
    # Reach from the floor the facing op left, not the entry block's z20 top.
    assert op["reach_depth_mm"] == pytest.approx(0.5, abs=0.01)
    assert op["reach_top_z_mm"] == pytest.approx(10.0, abs=0.01)
    # Holder face at 9.5 + 12 stands 1.5 above the retained wall; the flute body (to 15.5)
    # and the shank past it pass that wall 6 mm from the axis.
    assert op["holder_wall_hits"] == 0
    assert op["holder_clear_mm"] == pytest.approx(1.5, abs=0.01)
    assert op["holder_clear_top_z_mm"] == pytest.approx(20.0, abs=0.01)
    assert op["body_clear_mm"] == pytest.approx(3.5, abs=0.01)
    # Every spot pose's shank meets the retained wall, or none does.
    assert op["shank_hits"] == clash if clash == "unknown" else (op["shank_hits"] > 0) == clash
    assert op["shank_clear_mm"] == (
        shank_clear if shank_clear == "unknown" else pytest.approx(shank_clear, abs=0.01)
    )
    if shank is None:
        assert "shank_radius_mm" in op["reasons"]["shank_hits"]
    # The reach rule on these native facts: the 0.5 mm spot is well within its 6 mm flute,
    # yet only a resolved shank passes beside the retained wall; an unknown one never does.
    rules = rules_bundle(tmp_path)
    tool = rules.inventory["tools"]["em"]
    tool.update(dia_mm=5.0, flute_len_mm=6.0, projection_mm={"holder": 12.0}, oal_mm=100.0)
    if shank is not None:
        tool["shank_mm"] = 2 * shank
    rules.kernel["ops"]["S1:10"] = {**op, "claimed_indices": [1], "claim_errors": []}
    assert finding(reach, rules).status == verdict


# A combined drill and countersink's R1 pilot, 1.9 mm long, under its 60 degree seat cone.
PILOT, PILOT_LEN, SEAT_SLOPE = 1.0, 1.9, math.tan(math.radians(30.0))


@pytest.mark.parametrize(
    "name, depth, shank, hits, seat_clear",
    [
        # 0.5 deep, 1.5 mm from the shoulder (z13): the cone (z11.4-13.79) widens past it.
        ("seat", 0.5, 2.38125, True, 1.5 - (PILOT + (13.0 - 11.4) * SEAT_SLOPE)),
        # A seat ending at R1.4 (z12.09) stays 0.1 mm off that shoulder.
        ("seat", 0.5, 1.4, False, 0.1),
        # 2 mm deep after facing: the cone sinks its own countersink into the mouth, which
        # is its cut, not an obstacle; the retained x=30 wall stands 6 mm off its R2.38 top.
        ("step-hole", 2.0, 2.38125, False, 6.0 - 2.38125),
    ],
)
def test_centre_drill_seat_cone_is_cutting_body_checked_against_retained_stock(
    engine, solids, name, depth, shank, hits, seat_clear
):
    step = solids[name]
    centre = (31.5, 20) if name == "seat" else (36, 20)
    hole = engine.refs(
        step, (centre[0] - 2.5, 17.5, 0), (centre[0] + 2.5, 22.5, 10), kind="Cylinder"
    )
    spot = {
        **_op("S1:20", "hole", PILOT, PILOT_LEN, 20.0),
        "do": "spot",
        "hole": {"thru": True, "depth_mm": depth, "entry_z_mm": 10.0, "point_angle_deg": 118.0},
        "shank_from_mm": PILOT_LEN + (shank - PILOT) / SEAT_SLOPE,
        "shank_radius_mm": shank,
    }
    if name == "seat":
        job = engine.job(step, {"hole": hole}, [_setup("S1", [spot])], stock=PART)
    else:
        floor = engine.refs(step, (30, 0, 10), (60, 40, 10), kind="Plane")
        face = {**_floor_op("S1:10"), "do": "face"}
        job = engine.job(step, {"floor": floor, "hole": hole}, [_setup("S1", [face, spot])])
    op = engine.run(job)["ops"]["S1:20"]
    assert (op["tool_hits"] > 0) == hits, op
    assert op["obstacles"]["tool"] == (["part"] if hits else [])
    assert op["seat_clear_mm"] == pytest.approx(seat_clear, abs=1e-3)
    # The pilot alone stands 0.5 mm off the shoulder; the shank starts at the seat's top.
    if name == "seat":
        assert op["body_clear_mm"] == pytest.approx(0.5, abs=1e-3)
        assert op["shank_hits"] == 0


# The size 2 centre drill's 3/16 in body: its seat top stands 1.9 + 2.392 mm over the tip.
SHANK = 2.38125


def _centre_spot(depth):
    return {
        **_op("S1:20", "hole", PILOT, PILOT_LEN, 20.0),
        "do": "spot",
        "hole": {"thru": True, "depth_mm": depth, "entry_z_mm": 10.0, "point_angle_deg": 118.0},
        "shank_from_mm": PILOT_LEN + (SHANK - PILOT) / SEAT_SLOPE,
        "shank_radius_mm": SHANK,
    }


@pytest.mark.parametrize("depth", [4.2, 4.4, 5.0])
def test_seat_cone_feeds_down_its_own_shank_bore_to_its_final_pose(engine, solids, tmp_path, depth):
    # After facing, the spot on the future 6 mm bore, 6 mm from the retained z20 wall.
    # Past 4.292 mm deep the seat's widest edge has crossed the z10 entry, boring what it
    # passed out to the shank radius; no pose on the way down meets stock it bored away.
    step = solids["wide-hole"]
    floor = engine.refs(step, (30, 0, 10), (60, 40, 10), kind="Plane")
    hole = engine.refs(step, (33, 17, 0), (39, 23, 10), kind="Cylinder")
    assert len(floor) == len(hole) == 1
    face = {**_floor_op("S1:10"), "do": "face"}
    setup = _setup("S1", [face, _centre_spot(depth)])
    op = engine.run(engine.job(step, {"floor": floor, "hole": hole}, [setup]))["ops"]["S1:20"]
    assert op["tool_hits"] == 0, op
    assert op["obstacles"]["tool"] == []
    assert op["shank_hits"] == 0
    rules = rules_bundle(tmp_path)
    tool = rules.inventory["tools"]["em"]
    tool.update(
        dia_mm=2 * PILOT,
        flute_len_mm=PILOT_LEN,
        projection_mm={"holder": 20.0},
        oal_mm=100.0,
        shank_mm=2 * SHANK,
    )
    rules.kernel["ops"]["S1:10"] = {**op, "claimed_indices": [1], "claim_errors": []}
    assert finding(accessibility, rules).status == "pass"
    assert finding(reach, rules).status == "pass"


def test_seat_sweep_never_bores_finished_material_in_its_path(engine, solids):
    # 6 mm deep in the plate's 6 mm bore the final seat cone (z5.9-8.29) clears the
    # finished 4 mm neck above it (z8.5-10), but the seat passes through that neck on its
    # way down: its bore is never credited with finished material, so the seat hits it.
    step = solids["neck"]
    hole = engine.refs(step, (33, 17, 0), (39, 23, 10), kind="Cylinder")
    assert len(hole) == 2
    job = engine.job(step, {"hole": hole}, [_setup("S1", [_centre_spot(6.0)])], stock=PART)
    op = engine.run(job)["ops"]["S1:20"]
    assert op["tool_hits"] > 0, op
    assert op["obstacles"]["tool"] == ["part"]


@pytest.mark.parametrize("shank, clash", [(3.0, False), (4.0, True)])
def test_milling_shank_trails_its_own_cut_and_meets_only_the_retained_wall(
    engine, solids, shank, clash
):
    # A 6 mm flute clears the 10 mm over the floor pass by pass: past the flute the shank
    # meets the x=30 wall the op leaves, not the overstock its own passes remove first.
    step = solids["step"]
    floor = engine.refs(step, (30, 0, 10), (60, 40, 10), kind="Plane")
    op = {**_op("S1:10", "floor", 3.0, 6.0, 30.0), "shank_radius_mm": shank, "shank_from_mm": 6.0}
    facts = engine.run(engine.job(step, {"floor": floor}, [_setup("S1", [op])]))["ops"]["S1:10"]
    assert facts["reach_depth_mm"] == pytest.approx(10.0, abs=0.01)
    assert (facts["shank_hits"] > 0) == clash


def test_unswept_profile_wall_makes_only_later_stock_unknown(engine, solids):
    step = solids["step"]
    wall = engine.refs(step, (30, 0, 10), (30, 40, 20))
    floor = engine.refs(step, (30, 0, 10), (60, 40, 10))
    assert len(wall) == 1
    setups = [
        _setup("S1", [{**_floor_op("S1:10"), "feature": "wall"}]),
        _setup("S2", [_floor_op("S2:10")]),
    ]
    result = engine.run(engine.job(step, {"wall": wall, "floor": floor}, setups))
    first, second = result["setups"]["S1"], result["setups"]["S2"]
    assert first["render_png_base64"] and "stock_reason" not in first
    assert "S1:10" in second["stock_reason"] and wall[0] in second["stock_reason"]
    assert "render_png_base64" not in second and second["width_mm"] == "unknown"
    op = result["ops"]["S2:10"]
    assert op["tool_hits"] == "unknown" and op["stock_reason"] == second["stock_reason"]


# 60 x 50 x 22 blank: 5 mm side rails (y -5..0, 40..45) and 2 mm over the top.
ALLOWED = {**BOX, "origin_mm": [0.0, -5.0, 0.0], "section_mm": [50.0, 22.0]}
CLEAR = {"x": [30.0, 60.0], "y": [0.0, 40.0], "z": [10.0, 22.0]}  # the step, rails excluded


def _clearing(bounds, **claim):
    """S1:10 clears ``bounds`` while claiming only the step wall (or ``claim``)."""
    return {**_floor_op("S1:10"), "feature": "wall", "stock_removal_bounds": bounds, **claim}


def test_declared_clearing_box_derives_the_next_setup_and_keeps_unclaimed_rails(engine, solids):
    step = solids["step"]
    wall = engine.refs(step, (30, 0, 10), (30, 40, 20))
    floor = engine.refs(step, (30, 0, 10), (60, 40, 10))
    features = {"wall": wall, "floor": floor}
    target = _setup("S2", [_floor_op("S2:10"), _op("S2:20", "wall", 3.0, 15.0, 30.0)])
    full, webbed = (
        engine.run(
            engine.job(
                step,
                features,
                [
                    _setup("S1", [_clearing(CLEAR, faces=wall + floor, to_z=to_z)]),
                    _setup("S2", [_floor_op("S2:10", to_z), _op("S2:20", "wall", 3.0, 15.0, 30.0)]),
                ],
                (),
                ALLOWED,
            )
        )
        for to_z in (10.0, 15.0)
    )
    first, second = full["setups"]["S1"], full["setups"]["S2"]
    # Holding, rendering, reach and holder checks still use the raw setup-entry stock.
    assert first["stock_volume_mm3"] == pytest.approx(60 * 50 * 22)
    assert first["render_png_base64"] and "stock_reason" not in first
    # The floor and wall jointly bound the claimed clearing footprint. Rails and
    # top allowance over the unclaimed high half stay.
    assert "stock_reason" not in second and second["render_png_base64"]
    assert second["stock_volume_mm3"] == pytest.approx(60 * 50 * 22 - 30 * 40 * 12)
    assert second["stock_bbox_mm"] == [0.0, -5.0, 0.0, 60.0, 45.0, 22.0]
    assert second["width_mm"] == 50.0 and second["min_wall_mm"] == 5.0
    # A to_z endpoint above the floor leaves a 5 mm web behind as well.
    assert webbed["setups"]["S2"]["stock_volume_mm3"] == pytest.approx(60 * 50 * 22 - 30 * 40 * 7)
    finished = engine.run(engine.job(step, features, [target], stock=PART))["ops"]
    ops = full["ops"]
    # Wall end poses still meet retained rails, even though the op cuts its own allowance.
    assert ops["S2:20"]["tool_hits"] > finished["S2:20"]["tool_hits"]
    # The floor tip stands at its authored endpoint over the retained 22 mm entry stock
    # (the high half's top allowance and the rails): 12 mm above the z = 10 floor (10 mm
    # on the finished part) but 7 mm above to_z = 15, whose web stays below the tip.
    assert ops["S2:10"]["reach_depth_mm"] == 12.0
    assert webbed["ops"]["S2:10"]["reach_depth_mm"] == 7.0
    assert finished["S2:10"]["reach_depth_mm"] == 10.0


def _refused(engine, step):
    wall = engine.refs(step, (30, 0, 10), (30, 40, 20))
    floor = engine.refs(step, (30, 0, 10), (60, 40, 10))
    bottom = engine.refs(step, (0, 0, 0), (60, 40, 0))
    accepted = _clearing(CLEAR, faces=wall + floor)
    for name, bounds, cause in (
        ("reversed-z", {**CLEAR, "z": [22.0, 10.0]}, ("stock_removal_bounds z", "lo < hi")),
        (
            "missing-y",
            {"x": [30.0, 60.0], "z": [10.0, 22.0]},
            ("stock_removal_bounds y", "lo < hi"),
        ),
        ("unknown-bounds", "unknown", ("stock_removal_bounds is unknown",)),
        ("host-debt", {"reason": "host named why"}, ("host named why",)),
    ):
        yield name, {**accepted, "stock_removal_bounds": bounds}, ALLOWED, cause, accepted
    yield (
        "unknown-face",
        _clearing(CLEAR, faces=["unknown"]),
        ALLOWED,
        (
            "claimed faces are unresolved",
            "unknown",
        ),
        accepted,
    )
    yield (
        "away-face",
        _clearing(CLEAR, faces=wall + bottom),
        ALLOWED,
        (
            "facing away",
            bottom[0],
        ),
        accepted,
    )
    yield (
        "outside-claim",
        _clearing({**CLEAR, "x": [40.0, 60.0]}, faces=wall + floor),
        ALLOWED,
        (
            "lie outside its stock_removal_bounds",
            wall[0],
        ),
        accepted,
    )
    # The end piece borders no claim; repairing only X leaves that unclaimed end intact.
    end = {**BOX, "origin_mm": [-5.0, 0.0, 0.0], "length_mm": 65.0}
    box = {"x": [-5.0, 60.0], "y": [0.0, 40.0], "z": [10.0, 20.0]}
    invalid = _clearing(box, faces=wall + floor)
    repaired = {**invalid, "stock_removal_bounds": {**box, "x": [30.0, 60.0]}}
    yield "disconnected-end", invalid, end, ("bordering none of its claimed faces",), repaired


def test_unknown_or_unclaimed_clearance_never_derives_the_next_setup(engine, solids):
    step = solids["step"]
    wall = engine.refs(step, (30, 0, 10), (30, 40, 20))
    floor = engine.refs(step, (30, 0, 10), (60, 40, 10))
    cases = list(_refused(engine, step))
    jobs = [
        engine.job(
            step,
            {"wall": wall, "floor": floor},
            [_setup("S1", [op]), _setup("S2", [_floor_op("S2:10")])],
            (),
            stock,
        )
        for _, invalid, stock, _, repaired in cases
        for op in (invalid, repaired)
    ]
    results = engine.run({"jobs": jobs})["results"]
    assert len(results) == 2 * len(cases)
    for index, (name, _, stock, causes, _) in enumerate(cases):
        result, repaired = results[2 * index : 2 * index + 2]
        first, second = result["setups"]["S1"], result["setups"]["S2"]
        # S1's own facts stand on its known entry stock; only its output is unknown.
        assert "stock_reason" not in first and first["render_png_base64"], name
        assert "S1:10" in second["stock_reason"], name
        for cause in causes:
            assert cause in second["stock_reason"], (name, second["stock_reason"])
        assert "render_png_base64" not in second
        assert "stock_volume_mm3" not in second and "stock_out_volume_mm3" not in second
        assert result["ops"]["S2:10"]["tool_hits"] == "unknown"
        control = repaired["setups"]["S2"]
        removed_height = stock["section_mm"][1] - 10.0
        supplied = stock["length_mm"] * math.prod(stock["section_mm"])
        assert "stock_reason" not in control and control["render_png_base64"], name
        assert control["stock_volume_mm3"] == pytest.approx(supplied - 30 * 40 * removed_height)


def _variants(engine, step):
    top = engine.refs(step, (0, 0, 20), (30, 40, 20))
    yield (
        "unknown-supply",
        {"reason": "plan stock is unknown; in-process stock cannot be derived"},
        (),
        {},
        (
            "plan stock is unknown",
            "in-process stock cannot be derived",
        ),
        BOX,
        (),
        {},
    )
    yield (
        "as-is",
        {**BOX, "section_mm": [40.0, 25.0]},
        top,
        {},
        (
            "as-is face(s) do not lie on the authored stock envelope",
            top[0],
        ),
        BOX,
        top,
        {},
    )
    yield (
        "containment",
        {**BOX, "origin_mm": [0.0, 0.0, 1.0]},
        (),
        {},
        (
            "finished part extends",
            "outside the authored stock envelope",
        ),
        BOX,
        (),
        {},
    )
    yield (
        "missing-route",
        BOX,
        (),
        {"stock_in": "missing"},
        (
            "stock_in reference 'missing'",
            "not a supply or earlier",
        ),
        BOX,
        (),
        {"stock_in": "stock"},
    )


def test_unknown_supply_as_is_or_route_never_measures_or_renders(engine, solids):
    step = solids["step"]
    floor = engine.refs(step, (30, 0, 10), (60, 40, 10))
    cases = list(_variants(engine, step))
    jobs = [
        engine.job(
            step,
            {"floor": floor},
            [{**_setup("S1", [_floor_op("S1:10")]), **extra}],
            as_is,
            stock,
        )
        for (
            _,
            invalid_stock,
            invalid_as_is,
            invalid_extra,
            _,
            fixed_stock,
            fixed_as_is,
            fixed_extra,
        ) in cases
        for stock, as_is, extra in (
            (invalid_stock, invalid_as_is, invalid_extra),
            (fixed_stock, fixed_as_is, fixed_extra),
        )
    ]
    results = engine.run({"jobs": jobs})["results"]
    assert len(results) == 2 * len(cases)
    for index, (name, _, _, _, causes, _, _, _) in enumerate(cases):
        result, repaired = results[2 * index : 2 * index + 2]
        assert result["status"] == "ok", result
        facts, op = result["setups"]["S1"], result["ops"]["S1:10"]
        for cause in causes:
            assert cause in facts["stock_reason"], (name, facts["stock_reason"])
        assert "render_png_base64" not in facts and facts["width_mm"] == "unknown"
        assert "stock_volume_mm3" not in facts and "stock_out_volume_mm3" not in facts
        assert op["tool_hits"] == op["holder_hits"] == op["reach_depth_mm"] == "unknown"
        control, control_op = repaired["setups"]["S1"], repaired["ops"]["S1:10"]
        assert "stock_reason" not in control and control["render_png_base64"], name
        assert control["stock_volume_mm3"] == pytest.approx(60 * 40 * 20)
        assert control_op["tool_hits"] != "unknown"
        assert control_op["holder_hits"] != "unknown"
        assert control_op["reach_depth_mm"] != "unknown"


def test_authored_clearing_without_cutter_radius_keeps_later_stock_unknown(engine, solids):
    step = solids["step"]
    wall = engine.refs(step, (30, 0, 10), (30, 40, 20))
    wide = {"x": [0.0, 60.0], "y": [0.0, 40.0], "z": [10.0, 22.0]}
    op = {**_clearing(wide), "radius_mm": None}
    target = _op("S2:10", "wall", 3.0, 10.0, 10.5, holder_radius=6.0, gauge=10.0)
    result = engine.run(
        engine.job(
            step,
            {"wall": wall},
            [_setup("S1", [op]), _setup("S2", [target])],
            stock={**BOX, "section_mm": [40.0, 22.0]},
        )
    )
    first = result["ops"]["S1:10"]
    assert "stock_removal_error" not in first
    assert first["tool_hits"] == "unknown"
    second = result["setups"]["S2"]
    assert "S1:10" in second["stock_reason"]
    assert "stock_volume_mm3" not in second and "render_png_base64" not in second
    assert result["ops"]["S2:10"]["holder_hits"] == "unknown"
    assert result["ops"]["S2:10"]["reach_depth_mm"] == "unknown"


@pytest.mark.parametrize("name", ["draftstep", "updraftstep", "wideupdraftstep"])
def test_drafted_claimed_wall_keeps_named_stock_debt(engine, solids, name):
    step = solids[name]
    width = 200.0 if name == "wideupdraftstep" else 40.0
    wall = engine.refs(step, (30, 0, 10), (30.2, width, 20))
    assert len(wall) == 1
    result = engine.run(
        engine.job(
            step,
            {"wall": wall},
            [
                _setup("S1", [_op("S1:10", "wall", 3.0, 15.0, 30.0)]),
                _setup("S2", [_op("S2:10", "wall", 3.0, 15.0, 30.0)]),
            ],
            stock={**BOX, "section_mm": [width, 20.0]},
        )
    )
    second = result["setups"]["S2"]
    assert "S1:10" in second["stock_reason"] and wall[0] in second["stock_reason"]
    assert second["width_mm"] == "unknown" and second["min_wall_mm"] == "unknown"
    assert "render_png_base64" not in second


def test_a_retained_ear_between_sample_rows_keeps_stock_unknown(engine, solids):
    step = solids["step"]
    wall = engine.refs(step, (30, 0, 10), (30, 40, 20))
    floor = engine.refs(step, (30, 0, 10), (60, 40, 10))
    partial = _clearing({**CLEAR, "y": [3.0, 40.0]}, faces=wall + floor, subject="S1:20")
    complete = {**partial, "stock_removal_bounds": CLEAR}
    wall_op = _op("S1:10", "wall", 3.0, 15.0, 30.0)
    jobs = [
        engine.job(
            step,
            {"wall": wall, "floor": floor},
            [
                _setup("S1", ops),
                _setup("S2", [_op("S2:10", "wall", 3.0, 15.0, 30.0)]),
            ],
        )
        for ops in ([wall_op, partial], [wall_op, complete], [partial])
    ]
    retained, cleared, witness = engine.run({"jobs": jobs})["results"]
    first, second = retained["setups"]["S1"], retained["setups"]["S2"]
    assert "stock_reason" not in first and first["render_png_base64"]
    assert first["stock_volume_mm3"] == pytest.approx(60 * 40 * 20)
    assert retained["ops"]["S1:10"]["tool_hits"] != "unknown"
    assert retained["ops"]["S1:20"]["tool_hits"] != "unknown"
    assert "S1:10" in second["stock_reason"] and wall[0] in second["stock_reason"]
    assert "overstock still touches claimed wall" in second["stock_reason"]
    assert "stock_volume_mm3" not in second and "render_png_base64" not in second
    assert retained["ops"]["S2:10"]["tool_hits"] == "unknown"
    control = cleared["setups"]["S2"]
    assert "stock_reason" not in control and control["render_png_base64"]
    finished_volume = 60 * 40 * 20 - 30 * 40 * 10
    assert control["stock_volume_mm3"] == pytest.approx(finished_volume)
    assert cleared["ops"]["S2:10"]["tool_hits"] != "unknown"
    # Without the unbounded wall claim, the same partial box has known output:
    # its omitted 3 mm strip is real retained material, not a drafted-wall failure.
    strip = witness["setups"]["S2"]
    assert "stock_reason" not in strip and strip["render_png_base64"]
    assert strip["stock_volume_mm3"] == pytest.approx(finished_volume + 30 * 3 * 10)
    assert strip["stock_volume_mm3"] - control["stock_volume_mm3"] == pytest.approx(900.0)


def test_facing_own_allowance_is_not_a_flute_obstacle_but_still_hits_a_low_holder(engine, solids):
    step = solids["block"]
    top = engine.refs(step, (0, 0, 20), (60, 40, 20))
    stock = {**BOX, "section_mm": [40.0, 25.0]}
    clear = _op("S1:10", "top", 5.0, 20.0, 40.0)
    low = _op("S1:20", "top", 5.0, 20.0, 2.0)
    result = engine.run(engine.job(step, {"top": top}, [_setup("S1", [clear, low])], stock=stock))
    clear_facts, low_facts = result["ops"]["S1:10"], result["ops"]["S1:20"]
    assert clear_facts["tool_hits"] == 0 and clear_facts["holder_hits"] == 0
    assert clear_facts["reach_depth_mm"] == 5.0
    assert low_facts["tool_hits"] == 0 and low_facts["holder_hits"] > 0


def test_current_flute_meets_raw_outside_its_authorised_window_despite_a_later_facing(
    engine, solids
):
    step = solids["block"]
    top = engine.refs(step, (0, 0, 20), (60, 40, 20))
    stock = {**BOX, "section_mm": [40.0, 25.0]}
    # S1:10 claims the whole top but authorises clearing only its x 0..30 half. Its floor
    # poses take their nearest legal centre ignoring raw stock, so those over the
    # uncleared right half meet the real 5 mm raw above their actual tip at z = 20.
    half = {
        **_op("S1:10", "top", 5.0, 20.0, 40.0),
        "do": "face",
        "to_z": 20.0,
        "stock_removal_bounds": {"x": [0.0, 30.0], "y": [0.0, 40.0], "z": [20.0, 25.0]},
    }
    later = _op("S1:20", "top", 5.0, 20.0, 40.0)
    jobs = [
        engine.job(step, {"top": top}, [_setup("S1", ops), _setup("S2", [])], stock=stock)
        for ops in ([half], [half, later])
    ]
    alone, faced = engine.run({"jobs": jobs})["results"]
    # Alone it removes only its authorised half; the later facing clears the rest.
    assert alone["setups"]["S2"]["stock_volume_mm3"] == pytest.approx(60 * 40 * 25 - 30 * 40 * 5)
    assert faced["setups"]["S2"]["stock_volume_mm3"] == pytest.approx(60 * 40 * 20)
    # The later clearance is never credited to the earlier flute.
    hits = alone["ops"]["S1:10"]["tool_hits"]
    assert hits > 0 and faced["ops"]["S1:10"]["tool_hits"] == hits
    assert faced["ops"]["S1:20"]["tool_hits"] == 0


def test_nonprevious_output_keeps_its_removal_despite_an_unresolved_other_branch(engine, solids):
    step = solids["step"]
    floor = engine.refs(step, (30, 0, 10), (60, 40, 10))
    setups = [
        _setup("S1", [_floor_op("S1:10")]),
        {**_setup("S2", [_floor_op("S2:10")]), "stock_in": "stock"},
        {**_setup("S3", []), "stock_in": "S1"},
    ]
    setups[1]["ops"][0]["feature"] = "unmapped"
    result = engine.run(engine.job(step, {"floor": floor}, setups))
    assert "stock_reason" not in result["setups"]["S3"]
    assert result["setups"]["S3"]["stock_volume_mm3"] == pytest.approx(36000.0)
    # S2 restarts from supplied material, not from S1's already machined output.
    assert result["setups"]["S2"]["stock_volume_mm3"] == pytest.approx(48000.0)


def test_component_supplies_and_butt_assembly_use_model_frame_without_implicit_transforms(
    engine, solids
):
    stock = {
        "components": {
            "body": {**BOX, "length_mm": 30.0},
            "boss": {**BOX, "origin_mm": [30.0, 0.0, 0.0], "length_mm": 30.0},
        }
    }
    first = {
        **_setup("S0", []),
        "stock_in": "stock.body",
        "frame": {**IDENTITY, "origin": [10.0, 0.0, 0.0]},
    }
    second = {
        **_setup("S1", []),
        "stock_in": "stock.boss",
        "frame": {
            "origin": [30.0, 0.0, 0.0],
            "x": [0.0, 1.0, 0.0],
            "y": [-1.0, 0.0, 0.0],
            "z": [0.0, 0.0, 1.0],
        },
    }
    result = engine.run(
        engine.job(
            solids["block"],
            setups=[
                first,
                second,
                {
                    **_setup("S2", []),
                    "stock_in": ["S0", "S1"],
                    "joint": _butt_joint("S0", "S1"),
                },
            ],
            stock=stock,
        )
    )
    rows = result["setups"]
    assert rows["S0"]["stock_bbox_mm"] == [-10.0, 0.0, 0.0, 20.0, 40.0, 20.0]
    assert rows["S0"]["stock_volume_mm3"] == pytest.approx(24000.0)
    assert rows["S1"]["stock_bbox_mm"] == [0.0, -30.0, 0.0, 40.0, 0.0, 20.0]
    assert rows["S1"]["stock_volume_mm3"] == pytest.approx(24000.0)
    joined = rows["S2"]
    assert joined["stock_bbox_mm"] == [0.0, 0.0, 0.0, 60.0, 40.0, 20.0]
    assert joined["stock_volume_mm3"] == pytest.approx(48000.0)
    assert joined["render_png_base64"] and "stock_reason" not in joined


def test_missing_component_geometry_only_blocks_routes_that_receive_it(engine, solids):
    stock = {
        "components": {
            "body": {**BOX, "length_mm": 30.0},
            "boss": {"reason": "round stock placement/dimensions undeclared: origin_mm"},
        }
    }
    setups = [
        {**_setup("S0", []), "stock_in": "stock.body"},
        {**_setup("S1", []), "stock_in": "stock.boss"},
        {**_setup("S2", []), "stock_in": "S0"},
        {
            **_setup("S3", []),
            "stock_in": ["S2", "S1"],
            "joint": _butt_joint("S2", "S1"),
        },
    ]
    result = engine.run(engine.job(solids["block"], setups=setups, stock=stock))
    assert result["status"] == "ok", result
    rows = result["setups"]
    assert rows["S0"]["stock_volume_mm3"] == pytest.approx(24000.0)
    assert rows["S2"]["stock_out_volume_mm3"] == pytest.approx(24000.0)
    assert rows["S2"]["stock_volume_mm3"] == pytest.approx(24000.0)
    assert rows["S2"]["render_png_base64"] and "stock_reason" not in rows["S2"]
    assert "render_png_base64" not in rows["S1"]
    assert "render_png_base64" not in rows["S3"]
    for name in ("S1", "S3"):
        assert "stock_volume_mm3" not in rows[name]
        assert "stock_out_volume_mm3" not in rows[name]


def test_component_as_is_faces_are_checked_on_the_union_exterior(engine, solids):
    step = solids["block"]
    top = engine.refs(step, (0, 0, 20), (60, 40, 20))
    setup = {
        **_setup("S0", []),
        "stock_in": ["stock.body", "stock.boss"],
        "joint": _butt_joint("stock.body", "stock.boss"),
    }
    stock = {
        "components": {
            "body": {**BOX, "length_mm": 30.0},
            "boss": {**BOX, "origin_mm": [30.0, 0.0, 0.0], "length_mm": 30.0},
        }
    }
    valid = engine.run(engine.job(step, setups=[setup], as_is=top, stock=stock))["setups"]["S0"]
    assert valid["stock_volume_mm3"] == pytest.approx(48000.0)
    for component in stock["components"].values():
        component["section_mm"] = [40.0, 25.0]
    invalid = engine.run(engine.job(step, setups=[setup], as_is=top, stock=stock))["setups"]["S0"]
    assert "stock_reason" in invalid and "stock_volume_mm3" not in invalid
    assert "render_png_base64" not in invalid


def test_disconnected_assembly_is_refused_before_clearing(engine, solids):
    step = solids["block"]
    top = engine.refs(step, (0, 0, 20), (60, 40, 20))
    stock = {
        "components": {
            "left": {**BOX, "section_mm": [40.0, 25.0]},
            "right": {
                **BOX,
                "origin_mm": [80.0, 0.0, 0.0],
                "length_mm": 20.0,
                "section_mm": [40.0, 25.0],
            },
        }
    }
    setups = [
        {
            **_setup("S1", [_floor_op("S1:10")]),
            "stock_in": ["stock.left", "stock.right"],
            "joint": _butt_joint("stock.left", "stock.right", 60.0),
        },
        {**_setup("S2", []), "stock_in": "S1"},
    ]
    rows = engine.run(engine.job(step, {"floor": top}, setups, stock=stock))["setups"]
    assert rows["S1"]["assembly_error"]
    for row in rows.values():
        assert "stock_volume_mm3" not in row
        assert "render_png_base64" not in row
        assert row["stock_reason"]


def test_known_component_union_must_contain_the_finished_part(engine, solids):
    stock = {
        "components": {
            "body": {**BOX, "length_mm": 30.0},
            "boss": {**BOX, "origin_mm": [30.0, 0.0, 0.0], "length_mm": 20.0},
        }
    }
    setups = [
        {**_setup("S0", []), "stock_in": "stock.body"},
        {**_setup("S1", []), "stock_in": "stock.boss"},
        {
            **_setup("S2", []),
            "stock_in": ["S0", "S1"],
            "joint": _butt_joint("S0", "S1"),
        },
    ]
    result = engine.run(engine.job(solids["block"], setups=setups, stock=stock))
    assert "reason" in result["stock"]
    for row in result["setups"].values():
        assert "stock_reason" in row and "stock_volume_mm3" not in row
        assert "render_png_base64" not in row
        assert row["width_mm"] == "unknown"


def test_clearing_one_component_cannot_split_its_retained_material(engine, solids):
    step = solids["channel"]
    floor = engine.refs(step, (0, 5, 10), (60, 35, 10))
    stock = {
        "components": {
            "body": BOX,
            "rail": {**BOX, "origin_mm": [0.0, 0.0, 30.0], "section_mm": [40.0, 5.0]},
        }
    }
    clearing = _floor_op("S1:10", 10.0)
    setups = [
        {
            **_setup("S1", [clearing]),
            "stock_in": "stock.rail",
        },
        {**_setup("S2", []), "stock_in": "S1"},
    ]
    rows = engine.run(engine.job(step, {"floor": floor}, setups, stock=stock))["setups"]
    assert rows["S1"]["stock_volume_mm3"] == pytest.approx(12000.0)
    assert "S1:10" in rows["S2"]["stock_reason"]
    assert "stock_volume_mm3" not in rows["S2"]
    assert "render_png_base64" not in rows["S2"]
