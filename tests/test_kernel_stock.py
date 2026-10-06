"""Sequential in-process stock and the engine-only geometry cache key.

The engine sees the authored stock envelope minus what earlier setups' claimed faces
removed, never the finished solid; host-only plan fields never reach its job or cache key.
FreeCAD-backed tests run the ``freecad_job.py`` shipped beside the imported package and
skip without ``freecadcmd``.
"""

import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest
from test_kernel_geometry import IDENTITY, Engine, _op, _vise

from prechips import kernel
from prechips.inputs import Bundle
from prechips.model import Stock

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
    assert len(paths) == 6, process.stdout[-2000:] + process.stderr[-2000:]
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
    # A 5 mm web above the floor stays as overstock; a target retaining it still collides.
    assert webbed["setups"]["S2"]["stock_volume_mm3"] == pytest.approx(48000.0 - 60 * 30 * 5)
    finished = engine.run(
        engine.job(step, {"floor": floor}, [_setup("S2", [_floor_op("S2:10")])], stock=PART)
    )["ops"]["S2:10"]["tool_hits"]
    assert webbed["ops"]["S2:10"]["tool_hits"] > finished
    # Without to_z the channel is cleared; the unclaimed 5 mm rails are kept and gripped.
    assert webbed["setups"]["S1"]["min_wall_mm"] == 40.0
    s2 = cleared["setups"]["S2"]
    assert s2["stock_volume_mm3"] == pytest.approx(48000.0 - 60 * 30 * 10)
    assert s2["width_mm"] == 40.0 and s2["min_wall_mm"] == 5.0
    assert cleared["ops"]["S2:10"]["tool_hits"] == finished


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
    assert webbed["ops"]["S2:10"]["tool_hits"] > ops["S2:10"]["tool_hits"]


def _refused(engine, step):
    wall = engine.refs(step, (30, 0, 10), (30, 40, 20))
    bottom = engine.refs(step, (0, 0, 0), (60, 40, 0))
    yield _clearing({**CLEAR, "z": [22.0, 10.0]}), ALLOWED
    yield _clearing({"x": [30.0, 60.0], "z": [10.0, 22.0]}), ALLOWED
    yield _clearing("unknown"), ALLOWED
    yield _clearing({"reason": "host named why"}), ALLOWED
    yield _clearing(CLEAR, faces=["unknown"]), ALLOWED
    yield _clearing(CLEAR, faces=wall + bottom), ALLOWED
    yield _clearing({**CLEAR, "x": [40.0, 60.0]}), ALLOWED
    # This disconnected end piece borders no claim, even though broad multipass bounds
    # themselves are permitted with a measured cutter radius.
    end = {**BOX, "origin_mm": [-5.0, 0.0, 0.0], "length_mm": 65.0}
    box = {"x": [-5.0, 60.0], "y": [0.0, 40.0], "z": [10.0, 20.0]}
    yield _clearing(box), end


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
        for op, stock in cases
    ]
    results = engine.run({"jobs": jobs})["results"]
    for result in results:
        first, second = result["setups"]["S1"], result["setups"]["S2"]
        # S1's own facts stand on its known entry stock; only its output is unknown.
        assert "stock_reason" not in first and first["render_png_base64"]
        assert "S1:10" in second["stock_reason"] and "render_png_base64" not in second
        assert "stock_volume_mm3" not in second and "stock_out_volume_mm3" not in second
        assert result["ops"]["S2:10"]["tool_hits"] == "unknown"


def _variants(engine, step):
    top = engine.refs(step, (0, 0, 20), (30, 40, 20))
    yield {"reason": "plan stock is unknown; in-process stock cannot be derived"}, (), {}
    yield {**BOX, "section_mm": [40.0, 25.0]}, top, {}
    yield {**BOX, "origin_mm": [0.0, 0.0, 1.0]}, (), {}
    yield BOX, (), {"stock_in": "missing"}


def test_unknown_supply_as_is_or_route_never_measures_or_renders(engine, solids):
    step = solids["step"]
    floor = engine.refs(step, (30, 0, 10), (60, 40, 10))
    for stock, as_is, extra in _variants(engine, step):
        setup = {**_setup("S1", [_floor_op("S1:10")]), **extra}
        result = engine.run(engine.job(step, {"floor": floor}, [setup], as_is, stock))
        assert result["status"] == "ok", result
        facts, op = result["setups"]["S1"], result["ops"]["S1:10"]
        assert "render_png_base64" not in facts and facts["width_mm"] == "unknown"
        assert "stock_volume_mm3" not in facts and "stock_out_volume_mm3" not in facts
        assert op["tool_hits"] == op["holder_hits"] == op["reach_depth_mm"] == "unknown"


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
    clear = _clearing({**CLEAR, "y": [3.0, 40.0]}, faces=wall + floor, subject="S1:20")
    result = engine.run(
        engine.job(
            step,
            {"wall": wall},
            [
                _setup("S1", [_op("S1:10", "wall", 3.0, 15.0, 30.0), clear]),
                _setup("S2", [_op("S2:10", "wall", 3.0, 15.0, 30.0)]),
            ],
        )
    )
    assert wall[0] in result["setups"]["S2"].get("stock_reason", "")
    assert "stock_volume_mm3" not in result["setups"]["S2"]


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


def test_another_ops_removal_and_a_retained_web_do_not_clear_the_current_flute(engine, solids):
    step = solids["block"]
    top = engine.refs(step, (0, 0, 20), (60, 40, 20))
    stock = {**BOX, "section_mm": [40.0, 25.0]}
    leave_web = {**_op("S1:10", "top", 5.0, 20.0, 40.0), "to_z": 23.0}
    clear_later = _op("S1:20", "top", 5.0, 20.0, 40.0)
    result = engine.run(
        engine.job(step, {"top": top}, [_setup("S1", [leave_web, clear_later])], stock=stock)
    )
    assert result["ops"]["S1:10"]["tool_hits"] > 0
    assert result["ops"]["S1:20"]["tool_hits"] == 0


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
