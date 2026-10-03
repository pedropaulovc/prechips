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
from copy import deepcopy
from pathlib import Path

import pytest
from test_kernel_geometry import FREECAD, IDENTITY, Engine, _op, _vise, needs_freecad

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
import Part
from FreeCAD import Vector as V
out = sys.argv[sys.argv.index("--") + 1]
# 60x40x20 block, +X half stepped down to z=10: floor x 30..60 and its wall at x=30.
Part.makeBox(60, 40, 20).cut(Part.makeBox(31, 42, 11, V(30, -1, 10))).exportStep(out + "/step.step")
# U channel: 60 long (x), rails y 0..5 and 35..40 up to z=20, floor z=10.
Part.makeBox(60, 40, 20).cut(Part.makeBox(62, 30, 11, V(-1, 5, 10))).exportStep(
    out + "/channel.step"
)
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
    op = setup["ops"][0]
    yield "op do / finishing", lambda: op.update(do="rough_profile")
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
    calls = []

    def execute(executable, batch):
        calls.append(deepcopy(batch))
        return {"results": [{"status": "ok"} for _ in batch["jobs"]]}

    monkeypatch.setattr(kernel, "discover_kernel", lambda: Path(sys.executable))
    monkeypatch.setenv("PRECHIPS_KERNEL_CACHE", str(tmp_path / "cache"))
    monkeypatch.setattr(kernel, "_execute", execute)
    kernel.run_geometry(bundle)
    assert len(calls) == 1
    job = calls[0]["jobs"][0]
    assert job["stock"]["origin_mm"] == [0.0, 0.0, 0.0]
    assert job["setups"][0]["ops"][0]["to_z"] == 5.0
    for name, edit in _host_only(bundle):
        edit()
        object.__setattr__(bundle, "kernel", None)
        kernel.run_geometry(bundle)
        assert len(calls) == 1, f"host-only edit {name} reran FreeCAD"
    for count, (name, edit) in enumerate(_consumed(bundle), start=2):
        edit()
        object.__setattr__(bundle, "kernel", None)
        kernel.run_geometry(bundle)
        assert len(calls) == count, f"consumed edit {name} reused a stale result"


@pytest.mark.parametrize(
    "stock, reason",
    [
        (None, "plan stock is unknown"),
        ({"form": "finished_test_solid", "as_is_faces": ["#2"]}, "neither section_mm nor dia_mm"),
        ({**BOX, "dia_mm": 20.0}, "both section_mm and dia_mm"),
        ({k: v for k, v in BOX.items() if k != "origin_mm"}, "origin_mm"),
        ({**BOX, "components": [{"section_mm": [1, 1]}]}, "built-up stock components"),
    ],
)
def test_unauthored_stock_envelope_is_a_named_reason(tmp_path, stock, reason):
    bundle = _bundle(tmp_path)
    if stock is None:
        del bundle.plan["stock"]
    else:
        bundle.plan["stock"] = {k: v for k, v in stock.items() if k != "shape"}
    assert reason in kernel.stock_inputs(bundle)["reason"]


def test_stock_removal_bounds_reach_the_engine_in_mm_or_as_a_named_reason(tmp_path):
    bundle = _bundle(tmp_path)
    op = bundle.plan["setups"][0]["ops"][0]
    op["stock_removal_bounds"] = {"x": [0, 1], "y": [-1, 0.5], "z": [0.25, 2]}
    bundle.features["units"] = "in"
    (inputs,) = kernel.build_job(bundle)["setups"][0]["ops"]
    assert inputs["stock_removal_bounds"] == {"x": [0, 25.4], "y": [-25.4, 12.7], "z": [6.35, 50.8]}
    for bad, axes in (
        ({"x": [1, 1], "y": [0, 1], "z": [0, 1]}, "x"),  # zero-thickness box
        ({"x": [0, 1], "y": [1, 0], "z": ["unknown", 1]}, "y, z"),
        ({"x": [0, 1], "y": [0, 1]}, "z"),
        ("unknown", "x, y, z"),
    ):
        op["stock_removal_bounds"] = bad
        (inputs,) = kernel.engine_job(kernel.build_job(bundle))["setups"][0]["ops"]
        assert inputs["stock_removal_bounds"] == {
            "reason": f"stock_removal_bounds {axes} not a numeric [lo, hi] span with lo < hi"
        }


def test_a_plan_cannot_declare_its_supply_to_be_the_finished_part(tmp_path):
    bundle = _bundle(tmp_path)
    bundle.plan["stock"]["shape"] = "part"
    assert kernel.stock_inputs(bundle)["shape"] == "box"
    with pytest.raises(ValueError, match="shape"):
        Stock.model_validate({"shape": "part"})


# --------------------------------------------------------------------------- FreeCAD


class PackagedEngine(Engine):
    """The engine shipped with the imported package (so an older tree can be measured)."""

    def raw(self, payload):
        source, target = self.directory / "in.json", self.directory / "out.json"
        source.write_text(json.dumps(payload), encoding="utf-8")
        target.unlink(missing_ok=True)
        process = subprocess.run(
            [FREECAD, str(ENGINE), "--", str(source), str(target)],
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
def solids(tmp_path_factory):
    if FREECAD is None:
        pytest.skip("FreeCAD freecadcmd is not installed")
    directory = tmp_path_factory.mktemp("stock-solids")
    script = directory / "author.py"
    script.write_text(_AUTHOR, encoding="utf-8")
    process = subprocess.run(
        [FREECAD, str(script), "--", str(directory)],
        capture_output=True,
        text=True,
        errors="replace",
        timeout=300,
    )
    paths = {path.stem: path for path in directory.glob("*.step")}
    assert len(paths) == 2, process.stdout[-2000:] + process.stderr[-2000:]
    return paths


@pytest.fixture
def engine(tmp_path):
    return PackagedEngine(tmp_path)


def _setup(setup_id, ops, hold=None):
    return {"id": setup_id, "frame": IDENTITY, "hold": hold or _vise(12.0), "ops": ops}


def _floor_op(subject, to_z=None):
    op = _op(subject, "floor", 3.0, 15.0, 30.0)
    if to_z is not None:
        op["to_z"] = to_z
    return op


@needs_freecad
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
    # The raw block still covers the floor in S1; edge samples also meet the kept wall.
    assert result["ops"]["S1:10"]["tool_hits"] > finished
    # S2 receives the block minus the region S1's floor claim swept away.
    assert second["stock_volume_mm3"] == pytest.approx(48000.0 - 30 * 40 * 10)
    assert second["render_png_base64"] and "stock_reason" not in second
    assert result["ops"]["S2:10"]["tool_hits"] == finished


@needs_freecad
def test_to_z_web_and_unclaimed_rails_stay_in_the_next_setup(engine, solids):
    step = solids["channel"]
    floor = engine.refs(step, (0, 5, 10), (60, 35, 10))
    assert len(floor) == 1
    webbed, cleared = (
        engine.run(
            engine.job(
                step,
                {"floor": floor},
                [_setup("S1", [_floor_op("S1:10", to_z)]), _setup("S2", [_floor_op("S2:10")])],
            )
        )
        for to_z in (15.0, None)
    )
    # A 5 mm web above the floor stays as overstock and still collides.
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


@needs_freecad
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
    assert "cleared XY footprint" in second["stock_reason"]
    assert "render_png_base64" not in second and second["width_mm"] == "unknown"
    op = result["ops"]["S2:10"]
    assert op["tool_hits"] == "unknown" and op["stock_reason"] == second["stock_reason"]


# 60 x 50 x 22 blank: 5 mm side rails (y -5..0, 40..45) and 2 mm over the top.
ALLOWED = {**BOX, "origin_mm": [0.0, -5.0, 0.0], "section_mm": [50.0, 22.0]}
CLEAR = {"x": [30.0, 60.0], "y": [0.0, 40.0], "z": [10.0, 22.0]}  # the step, rails excluded


def _clearing(bounds, **claim):
    """S1:10 clears ``bounds`` while claiming only the step wall (or ``claim``)."""
    return {**_floor_op("S1:10"), "feature": "wall", "stock_removal_bounds": bounds, **claim}


@needs_freecad
def test_declared_clearing_box_derives_the_next_setup_and_keeps_unclaimed_rails(engine, solids):
    step = solids["step"]
    wall = engine.refs(step, (30, 0, 10), (30, 40, 20))
    floor = engine.refs(step, (30, 0, 10), (60, 40, 10))
    features = {"wall": wall, "floor": floor}
    target = _setup("S2", [_floor_op("S2:10"), _op("S2:20", "wall", 3.0, 15.0, 30.0)])
    full, webbed = (
        engine.run(
            engine.job(step, features, [_setup("S1", [_clearing(box)]), target], (), ALLOWED)
        )
        for box in (CLEAR, {**CLEAR, "z": [15.0, 22.0]})
    )
    first, second = full["setups"]["S1"], full["setups"]["S2"]
    # S1 is still checked and drawn on the raw blank; its clearance only shapes S2's stock.
    assert first["stock_volume_mm3"] == pytest.approx(60 * 50 * 22)
    assert first["render_png_base64"] and "stock_reason" not in first
    # A vertical wall sweeps nothing, but the declared box clears the step down to the part
    # and nothing outside it: the rails and the top allowance over the high half stay.
    assert "stock_reason" not in second and second["render_png_base64"]
    assert second["stock_volume_mm3"] == pytest.approx(60 * 50 * 22 - 30 * 40 * 12)
    assert second["stock_bbox_mm"] == [0.0, -5.0, 0.0, 60.0, 45.0, 22.0]
    assert second["width_mm"] == 50.0 and second["min_wall_mm"] == 5.0
    # A box stopping above the floor leaves that 5 mm web behind as well.
    assert webbed["setups"]["S2"]["stock_volume_mm3"] == pytest.approx(60 * 50 * 22 - 30 * 40 * 7)
    finished = engine.run(engine.job(step, features, [target], stock=PART))["ops"]
    ops = full["ops"]
    # The wall is buried in S1, exposed in S2, yet its end poses still meet the kept rails.
    assert ops["S1:10"]["tool_hits"] > ops["S2:20"]["tool_hits"] > finished["S2:20"]["tool_hits"]
    assert webbed["ops"]["S2:10"]["tool_hits"] > ops["S2:10"]["tool_hits"]


def _refused(engine, step):
    wall = engine.refs(step, (30, 0, 10), (30, 40, 20))
    bottom = engine.refs(step, (0, 0, 0), (60, 40, 0))
    lo_hi = "not a numeric [lo, hi] span with lo < hi"
    yield _clearing({**CLEAR, "z": [22.0, 10.0]}), ALLOWED, f"stock_removal_bounds z {lo_hi}"
    yield _clearing({"x": [30.0, 60.0], "z": [10.0, 22.0]}), ALLOWED, f"bounds y {lo_hi}"
    yield _clearing("unknown"), ALLOWED, "stock_removal_bounds is unknown"
    yield _clearing({"reason": "host named why"}), ALLOWED, "S1:10 host named why"
    yield _clearing(CLEAR, faces=["unknown"]), ALLOWED, "claimed faces are unresolved"
    away = f"facing away from the setup approach: {bottom[0]}"
    yield _clearing(CLEAR, faces=wall + bottom), ALLOWED, away
    outside = f"outside its stock_removal_bounds: {wall[0]}"
    yield _clearing({**CLEAR, "x": [40.0, 60.0]}), ALLOWED, outside
    # A 5 mm end overstock (x -5..0) inside the box borders no claimed face.
    end = {**BOX, "origin_mm": [-5.0, 0.0, 0.0], "length_mm": 65.0}
    box = {"x": [-5.0, 60.0], "y": [0.0, 40.0], "z": [10.0, 20.0]}
    yield _clearing(box), end, "removes 2000.0 mm^3 in 1 piece(s) bordering none of its claimed"


@needs_freecad
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
        for op, stock, _ in cases
    ]
    results = engine.run({"jobs": jobs})["results"]
    for (_, _, reason), result in zip(cases, results, strict=True):
        first, second = result["setups"]["S1"], result["setups"]["S2"]
        # S1's own facts stand on its known entry stock; only its output is unknown.
        assert "stock_reason" not in first and first["render_png_base64"]
        assert reason in second["stock_reason"], (reason, second["stock_reason"])
        assert "S1:10" in second["stock_reason"] and "render_png_base64" not in second
        assert result["ops"]["S2:10"]["tool_hits"] == "unknown"


def _variants(engine, step):
    top = engine.refs(step, (0, 0, 20), (30, 40, 20))
    yield (
        {"reason": "plan stock is unknown; in-process stock cannot be derived"},
        (),
        {},
        ("plan stock is unknown"),
    )
    yield {**BOX, "section_mm": [40.0, 25.0]}, top, {}, "as-is face(s) do not lie"
    yield {**BOX, "origin_mm": [0.0, 0.0, 1.0]}, (), {}, "outside the authored stock envelope"
    yield BOX, (), {"stock_in": "S0"}, "stock_in 'S0' of the first setup"


@needs_freecad
def test_unknown_supply_as_is_or_route_never_measures_or_renders(engine, solids):
    step = solids["step"]
    floor = engine.refs(step, (30, 0, 10), (60, 40, 10))
    for stock, as_is, extra, reason in _variants(engine, step):
        setup = {**_setup("S1", [_floor_op("S1:10")]), **extra}
        result = engine.run(engine.job(step, {"floor": floor}, [setup], as_is, stock))
        facts, op = result["setups"]["S1"], result["ops"]["S1:10"]
        assert reason in facts["stock_reason"], (reason, facts)
        assert "render_png_base64" not in facts and facts["width_mm"] == "unknown"
        assert op["tool_hits"] == "unknown" and reason in op["stock_reason"]


@needs_freecad
def test_rocker_s1_holds_the_raw_blank_and_s2_names_the_missing_profile_footprint(
    tmp_path, monkeypatch
):
    from prechips.inputs import load_bundle

    monkeypatch.setenv("PRECHIPS_KERNEL_CACHE", str(tmp_path / "cache"))
    bundle = load_bundle(Path(__file__).resolve().parents[1] / "examples/rocker-arm/plan.toml")
    result = kernel.run_geometry(bundle)
    first, second = result["setups"]["S1"], result["setups"]["S2"]
    # Frame A sees the authored 310x45x16 blank, rails and ears included.
    assert first["stock_bbox_mm"] == [-155.0, -16.0, -11.52825, 155.0, 29.0, 4.47175]
    assert first["render_png_base64"] and "stock_reason" not in first
    # The upper strap face is measured under the raw blank top, not the finished hub face.
    assert result["ops"]["S1:20"]["reach_depth_mm"] == pytest.approx(4.47175 + 2.27825)
    # Rough-profile walls sweep nothing along +Z and no interrupted-profile footprint is
    # authored, so the stock S1 leaves (and everything measured on it) is unknown.
    reason = second["stock_reason"]
    assert "S1:40" in reason and "HAF_TOP_EDGE" in reason and "interrupted profile" in reason
    assert "render_png_base64" not in second and second["width_mm"] == "unknown"
    assert all(
        result["ops"][subject]["stock_reason"] == reason
        for subject in result["ops"]
        if not subject.startswith("S1:")
    )
