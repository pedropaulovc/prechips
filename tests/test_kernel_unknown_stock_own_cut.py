"""Unknown stock cannot turn an accepted own bore cut into a certain collision.

One native launch authors two small solids and runs the public kernel jobs. A
read-only witness also intersects the actual flute regions with the bore-axis
cylinder, independently of the hit-count certainty backstop. No geometry is
mocked; ``freecad_kernel`` supplies the shared native executable. Mutation
mode ``PRECHIPS_TEST_OWN_CUT_MUTATION=omit-own-cut`` changes only the source
compiled in that native process; it never edits the repository or writes a
production geometry cache entry.
"""

import json
import os
import subprocess
import time
from copy import deepcopy

import pytest
from test_envelope_m5 import measured
from test_geometry_rules import finding, rules_bundle
from test_kernel_geometry import ENGINE, _op, _setup, _vise

from prechips.rules import accessibility

_RADIUS = 2.1  # The accepted reamer may cut its own R2 bore-wall allowance.
_HOLD = _vise(2.0, height=10.0, width=12.0, depth=2.0, centre=6.0)
_NATIVE = r"""
import hashlib
import importlib.util
import json
import os
import sys
import time
from pathlib import Path
import FreeCAD, Part

source, target, engine_path, module_directory = sys.argv[sys.argv.index("--") + 1:]
sys.path.insert(0, module_directory)
spec = importlib.util.spec_from_file_location("own_cut_engine", engine_path)
engine = importlib.util.module_from_spec(spec)
mutation = os.environ.get("PRECHIPS_TEST_OWN_CUT_MUTATION", "")
if mutation:
    assert mutation == "omit-own-cut", mutation
    text = Path(engine_path).read_text(encoding="utf-8")
    locator = (
        "                    if kept.isNull() or kept.isValid():\n"
        "                        stock = kept\n"
    )
    assert text.count(locator) == 1, "own-cut mutation locator must be unique"
    text = text.replace(locator, locator.replace("stock = kept", "pass"))
    exec(compile(text, engine_path, "exec"), engine.__dict__)
else:
    spec.loader.exec_module(engine)
V = FreeCAD.Vector
with open(source, encoding="utf-8") as stream:
    cases = json.load(stream)

job_timings = {}
def run_native(name, payload):
    started = time.monotonic()
    result = engine.run_job(payload)
    job_timings[name] = time.monotonic() - started
    return result

# The second solid has an unclaimed R1 neck above its claimed R2 bore. That
# finished neck is NOT this operation's bore wall, and must remain an obstacle.
box = Part.makeBox(12, 12, 10)
shapes = {
    "hole": box.cut(Part.makeCylinder(2, 12, V(6, 6, -1))),
    "neck": box.cut(Part.makeCylinder(2, 9, V(6, 6, -1))).cut(
        Part.makeCylinder(1, 12, V(6, 6, -1))
    ),
}
jobs = {}
for name, shape in shapes.items():
    assert shape.isValid() and len(shape.Solids) == 1, name
    path = Path(target).with_name(name + ".step")
    shape.exportStep(str(path))
    base = {
        "version": 1,
        "step_path": str(path),
        "step_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "stock": {"shape": "part"},
        "as_is_faces": [],
        "features": {},
        "setups": [],
    }
    inventory = run_native("inventory-" + name, base)
    assert inventory["status"] == "ok" and not inventory["mapping_errors"], inventory
    bore_top = 10 if name == "hole" else 8
    bore = [
        face["ref"] for face in inventory["faces"]
        if face["kind"] == "Cylinder"
        and abs(face["bbox_mm"][0] - 4) < 1e-6
        and abs(face["bbox_mm"][5] - bore_top) < 1e-6
    ]
    top = [
        face["ref"] for face in inventory["faces"]
        if face["kind"] == "Plane"
        and abs(face["bbox_mm"][2] - 10) < 1e-6
        and abs(face["bbox_mm"][5] - 10) < 1e-6
    ]
    assert len(bore) == len(top) == 1, inventory["faces"]
    base["features"] = {"bore": bore, "top": top}
    jobs[name] = base

witnesses = {}
original_flute_regions = engine._Setup._flute_regions
current = None

def witnessed_regions(setup, op, regions):
    if op.get("feature") != "bore":
        return original_flute_regions(setup, op, regions)
    index = setup._indices(op)[0]
    before = regions[index][0]
    actual = original_flute_regions(setup, op, regions)
    after = actual[index][0]
    assert before is not None and after is not None
    bore_top = 10 if current.startswith("hole-") else 8
    bore = Part.makeCylinder(
        op["radius_mm"] - engine.LIFT,
        bore_top - 2 * engine.LIFT,
        V(6, 6, engine.LIFT),
    )
    flute = Part.makeCylinder(
        op["radius_mm"] - engine.LIFT, op["flute_len_mm"], V(6, 6, engine.LIFT)
    )
    row = {
        "bore_before_mm3": before.shape.common(bore).Volume,
        "bore_after_mm3": after.shape.common(bore).Volume,
        "flute_after_mm3": after.shape.common(flute).Volume,
        "holder_region_unchanged": regions[index][0] is before,
    }
    if current.startswith("neck-"):
        # Also exercise the transient-joint/process axial fact writer with the same
        # real obstacle, tool and upstream stock lineage, not a mocked collision.
        row["transient_axial"] = setup._axial_facts(
            op, after.shape, V(6, 6, 10), 0.0, None
        )
    if setup.stock_reason is not None:
        rejected = {}
        for debt in ("radius", "claims", "depth", "to_z"):
            candidate = {**op, "hole": dict(op["hole"])}
            if debt == "radius":
                candidate["radius_mm"] = "unknown"
            elif debt == "claims":
                candidate["faces"] = ["unknown"]
            elif debt == "depth":
                candidate["hole"]["thru"] = "unknown"
            else:
                candidate["to_z"] = "unknown"
            uncredited = original_flute_regions(setup, candidate, regions)
            rejected[debt] = uncredited[index][0].shape.common(bore).Volume
        row["rejected_own_cuts_mm3"] = rejected
    witnesses[current] = row
    return actual

engine._Setup._flute_regions = witnessed_regions
results = {}
for current, case in cases.items():
    job = {**jobs[case["shape"]], "setups": case["setups"]}
    result = run_native(current, job)
    assert result["status"] == "ok" and not result["mapping_errors"], result
    results[current] = result

# Complementary source-boundary case: even pre-existing numeric tool minima
# cannot escape _unproven, while genuine holder minima retain their meaning.
guarded = {
    "tool_hits": 7,
    "holder_hits": 3,
    "min_hits": {"tool": 7, "holder": 3},
    "corner_radii_mm": [0.0],
    "reasons": {},
}
engine._Setup._unproven(guarded, "S1:10: upstream cut cannot be derived")
with open(target, "w", encoding="utf-8") as stream:
    json.dump(
        {
            "results": results,
            "witnesses": witnesses,
            "guarded": guarded,
            "native_job_timings_s": job_timings,
            "mutation": mutation,
            "configured_workers": os.environ.get("PRECHIPS_KERNEL_WORKERS"),
            "pool_active": engine._POOL is not None,
        },
        stream,
    )
"""


def _setups(mode):
    prep = {**_op("S1:10", "top", 1.0, 20.0, 30.0), "to_z": 10.0}
    ream = {
        **_op("S2:10", "bore", _RADIUS, 20.0, 30.0, holder_radius=1.0, gauge=2.0),
        "do": "ream",
        "hole": {"thru": True, "entry_z_mm": 10.0},
    }
    if mode != "trusted":
        prep["to_z"] = "unknown"
    if mode == "later-op":
        ream["subject"] = "S1:20"
        return [{**_setup([prep, ream], _HOLD), "stock_in": "stock"}]
    return [
        {**_setup([prep], _HOLD), "stock_in": "stock"},
        {**_setup([ream], _HOLD, setup_id="S2"), "stock_in": "S1"},
    ]


@pytest.fixture(scope="module")
def native_own_cut(tmp_path_factory, freecad_kernel):
    directory = tmp_path_factory.mktemp("unknown-stock-own-cut")
    mutation = os.environ.get("PRECHIPS_TEST_OWN_CUT_MUTATION", "")
    source = directory / "in.json"
    target = directory / ("mutant-out.json" if mutation else "out.json")
    cases = {
        f"{shape}-{mode}": {"shape": shape, "setups": _setups(mode)}
        for shape in ("hole", "neck")
        for mode in ("trusted", "unknown-entry", "later-op")
    }
    source.write_text(json.dumps(cases), encoding="utf-8")
    script = directory / "probe.py"
    script.write_text(_NATIVE, encoding="utf-8")
    started = time.monotonic()
    process = subprocess.run(
        [
            freecad_kernel,
            str(script),
            "--",
            str(source),
            str(target),
            str(ENGINE),
            str(ENGINE.parent),
        ],
        capture_output=True,
        text=True,
        errors="replace",
        timeout=60,
        # Imported run_job does not enter main(), so no pool is created even with workers=1.
        env={**os.environ, "PRECHIPS_KERNEL_WORKERS": "1"},
    )
    assert target.exists(), process.stdout[-2000:] + process.stderr[-2000:]
    report = json.loads(target.read_text(encoding="utf-8"))
    elapsed = time.monotonic() - started
    print(
        "own-cut native probe: direct_subprocess_launches=1, cache_writes=0, "
        f"configured_workers={report['configured_workers']}, pool_active={report['pool_active']}, "
        f"elapsed_s={elapsed:.3f}, report={target}"
    )
    print("native_job_timings_s=" + json.dumps(report["native_job_timings_s"], sort_keys=True))
    return report


def _detail(native, case):
    subject = "S1:20" if case.endswith("later-op") else "S2:10"
    return native["results"][case]["ops"][subject]


def _accessibility(tmp_path, native, case):
    """Feed actual native facts to the normal host rule, without a second native run."""
    result = native["results"][case]
    sid, op_number = ("S1", 20) if case.endswith("later-op") else ("S2", 10)
    bundle = rules_bundle(tmp_path)
    setup = bundle.plan["setups"][0]
    setup["id"] = sid
    setup["ops"][0].update(op=op_number, do="ream", feature="bore")
    bundle.features["features"] = {
        "bore": {
            "kind": "hole",
            "thru": True,
            "diameter": [4.0, 4.4],
            "faces": [result["faces"][index]["ref"] for index in result["features"]["bore"]],
        }
    }
    bundle.inventory["tools"]["em"].update(
        kind="reamer",
        dia_mm=measured(2 * _RADIUS),
        flute_len_mm=measured(20.0),
        projection_mm={"holder": measured(30.0)},
    )
    bundle.inventory["holders"]["holder"].update(
        gauge_dia_mm=measured(2.0), gauge_len_mm=measured(2.0)
    )
    setup["hold"].update(grip_mm=5.0, jaw_above_parallels_mm=2.0, jaw_center_along_mm=6.0)
    bundle.inventory["fixtures"]["vise"].update(
        kind="vise",
        jaw_width_mm=measured(12.0),
        jaw_depth_mm=measured(2.0),
        jaw_height_mm=measured(10.0),
        opening_mm=measured(150.0),
    )
    bundle.inventory["fixtures"]["parallels"]["height_mm"] = measured(25.0)
    object.__setattr__(bundle, "kernel", deepcopy(result))
    return finding(accessibility, bundle)


@pytest.mark.parametrize("mode", ["unknown-entry", "later-op"])
def test_unknown_upstream_stock_excludes_own_bore_geometry(native_own_cut, mode):
    case = f"hole-{mode}"
    witness = native_own_cut["witnesses"][case]
    # This assertion kills removal of the own-cut subtraction even if both hit
    # counts are still demoted to UNKNOWN by the independent certainty guard.
    assert witness["bore_before_mm3"] > 0.01
    assert witness["bore_after_mm3"] <= 1e-6
    assert witness["flute_after_mm3"] <= 1e-6
    assert witness["holder_region_unchanged"]
    detail = _detail(native_own_cut, case)
    assert detail["obstacles"]["tool"] == []
    assert detail["hit_refs"]["tool"] == []
    assert detail["tool_hits"] == detail["min_hits"]["tool"] == "unknown"
    assert detail["min_hits"]["holder"] == 0
    assert "S1:10" in detail["reasons"]["tool_hits"]
    assert "to_z is unknown" in detail["reasons"]["tool_hits"]
    if mode == "unknown-entry":
        reason = native_own_cut["results"][case]["setups"]["S2"]["stock_reason"]
        assert detail["stock_reason"] == reason
        assert "S1:10" in reason and "to_z is unknown" in reason


@pytest.mark.parametrize("mode", ["unknown-entry", "later-op"])
def test_unknown_stock_other_finished_flute_obstacle_is_unknown_not_error(
    native_own_cut, tmp_path, mode
):
    case = f"neck-{mode}"
    witness = native_own_cut["witnesses"][case]
    assert witness["bore_after_mm3"] <= 1e-6
    assert witness["flute_after_mm3"] > 0.01  # The unclaimed neck was not removed.
    detail = _detail(native_own_cut, case)
    assert detail["obstacles"]["tool"] == ["part"]
    assert detail["hit_refs"]["tool"]
    assert detail["tool_hits"] == detail["min_hits"]["tool"] == "unknown"
    assert detail["min_hits"]["holder"] == 0
    row = _accessibility(tmp_path, native_own_cut, case)
    assert row.status == "unknown", row
    assert "S1:10" in row.sentence and "to_z is unknown" in row.sentence


def test_trusted_stock_other_finished_flute_obstacle_remains_error(native_own_cut, tmp_path):
    case = "neck-trusted"
    witness = native_own_cut["witnesses"][case]
    assert witness["bore_after_mm3"] <= 1e-6
    assert witness["flute_after_mm3"] > 0.01
    detail = _detail(native_own_cut, case)
    assert detail["tool_hits"] > 0
    assert detail["min_hits"]["tool"] == detail["tool_hits"]
    assert detail["min_hits"]["holder"] == 0
    assert "stock_reason" not in detail
    assert _accessibility(tmp_path, native_own_cut, case).status == "error"


def test_trusted_stock_own_bore_stays_clear(native_own_cut):
    detail = _detail(native_own_cut, "hole-trusted")
    assert detail["tool_hits"] == detail["min_hits"]["tool"] == 0
    assert detail["obstacles"]["tool"] == []
    assert detail["hit_refs"]["tool"] == []


@pytest.mark.parametrize("mode", ["unknown-entry", "later-op"])
def test_stopping_op_keeps_its_known_before_stock(native_own_cut, mode):
    result = native_own_cut["results"][f"hole-{mode}"]
    prep = result["ops"]["S1:10"]
    assert prep["tool_hits"] == prep["min_hits"]["tool"] == 0
    assert "stock_reason" not in prep


@pytest.mark.parametrize("debt", ["radius", "claims", "depth", "to_z"])
def test_unknown_or_invalid_own_cut_receives_no_geometry_credit(native_own_cut, debt):
    witness = native_own_cut["witnesses"]["hole-unknown-entry"]
    assert witness["rejected_own_cuts_mm3"][debt] == pytest.approx(witness["bore_before_mm3"])
    assert witness["rejected_own_cuts_mm3"][debt] > 0.01


@pytest.mark.parametrize("mode", ["unknown-entry", "later-op", "trusted"])
def test_transient_axial_writer_respects_unknown_before_stock(native_own_cut, mode):
    facts = native_own_cut["witnesses"][f"neck-{mode}"]["transient_axial"]
    assert facts["obstacles"]["tool"] == ["part"]
    assert facts["min_hits"]["holder"] == 0
    if mode == "trusted":
        assert facts["tool_hits"] == facts["min_hits"]["tool"] == 1
    else:
        assert facts["tool_hits"] == facts["min_hits"]["tool"] == "unknown"
        assert "S1:10" in facts["reasons"]["tool_hits"]
        assert "to_z is unknown" in facts["reasons"]["tool_hits"]


def test_source_stock_guard_removes_tool_certainty_but_preserves_holder_minimum(native_own_cut):
    facts = native_own_cut["guarded"]
    assert facts["min_hits"] == {"tool": "unknown", "holder": 3}
    assert facts["tool_hits"] == facts["holder_hits"] == facts["shank_hits"] == "unknown"
    assert facts["corner_radii_mm"] == [0.0]
    assert "S1:10" in facts["stock_reason"]
