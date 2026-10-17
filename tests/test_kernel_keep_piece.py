"""A held split's ``keep`` leaves only the piece that carries the named feature (#182).

The issue's shape: S5 clears a ring round the part, so the blank's rim is a frame
standing free of it and taller than it, both pressed onto a stand (a held split); its
release op keeps the part. S6 holds the part alone in a vise and S7 takes it on: both
receive only the kept piece, so their ``stock_state`` describes the part, not scrap.
Without ``keep`` every piece is carried on as today. A keep that cannot name one piece
is stock debt with an instruction, never a guess. FreeCAD-backed tests run
``src/prechips/kernel/freecad_job.py`` under ``freecadcmd`` and skip without it.
"""

import json
import os
import subprocess
from pathlib import Path

import pytest
from test_kernel_geometry import ENGINE, Engine, _setup, _vise
from test_kernel_held_split import solids  # noqa: F401  (solids is a pytest fixture)
from test_kernel_stock_prefix import _rough

from prechips.findings import is_required
from prechips.inputs import Bundle
from prechips.kernel import _cache_recipe, _keeps, engine_job
from prechips.rules import consistency, keep_piece

UP = {"x": [1.0, 0.0, 0.0], "z": [0.0, 0.0, 1.0]}
# The island part (x 5..65, y 5..45, z 0..20) in a blank 1 mm taller than it.
BLANK = {
    "shape": "box",
    "origin_mm": [0.0, -5.0, 0.0],
    "axis": [1.0, 0.0, 0.0],
    "section_axis": [0.0, 1.0, 0.0],
    "length_mm": 70.0,
    "section_mm": [60.0, 21.0],
}
# Everything within 2-3 mm of the blank's edge stays: a closed frame round the part.
RING = {"x": [2.0, 68.0], "y": [-2.0, 52.0], "z": [0.0, 21.0]}
LEAVE = 0.2  # the rough op's leave: the part piece is the part offset by it, within the blank
PART_BOX = [5 - LEAVE, 5 - LEAVE, 0.0, 65 + LEAVE, 45 + LEAVE, 20 + LEAVE]
FRAME_BOX = [0.0, -5.0, 0.0, 70.0, 55.0, 21.0]
FRAME_MM3 = (70.0 * 60.0 - 66.0 * 54.0) * 21.0
SPLIT, RELEASE = {"op": 60, "do": "rough_profile", "feature": "south"}, {"op": 70, "do": "release"}


def _pad(name, x, y, z):
    return {
        "name": name,
        "restraint": "press",
        "pose": {"origin_mm": [x, y, z], **UP},
        "solids": [
            {"name": "pad:pad", "shape": "box", "at_mm": [-5, -1, 0], "size_mm": [10, 2, 5]}
        ],
    }


# The stand: a floor plate under the blank, one strap on the part, one on the frame rail.
STAND = {
    "kind": "solids",
    "fixture_kind": "custom",
    "pose": {"origin_mm": [0.0, 0.0, 0.0], **UP},
    "solids": [
        {"name": "stand:floor", "shape": "box", "at_mm": [-5, -10, -5], "size_mm": [80, 80, 5]}
    ],
    "clamps": [_pad("strap 1", 35.0, 30.0, 20 + LEAVE), _pad("strap 2", 35.0, -3.5, 21.0)],
    "debts": [],
    "gaps": [],
}


@pytest.fixture
def engine(tmp_path, freecad_kernel):
    return Engine(tmp_path, freecad_kernel)


@pytest.fixture(scope="module")
def module_engine(tmp_path_factory, freecad_kernel):
    return Engine(tmp_path_factory.mktemp("keep-piece"), freecad_kernel)


def _south(engine, step):
    south = engine.refs(step, (5, 5, 0), (65, 5, 20), kind="Plane")
    assert len(south) == 1
    return south


def _job(engine, step, keep="absent", feature="south"):
    s5 = _setup([{**_rough(RING), "subject": "S5:60", "feature": "south"}], STAND, setup_id="S5")
    if keep != "absent":
        s5["keep"] = [{"subject": "S5:70", "feature": feature, "after": keep}]
    vise = _vise(5.0, centre=35.0)
    setups = [s5, _setup([], vise, setup_id="S6"), _setup([], vise, setup_id="S7")]
    features = {"south": _south(engine, step), "ghost": "unknown"}
    return engine.job(step, features, setups, stock=BLANK)


@pytest.fixture(scope="module")
def runs(module_engine, solids):  # noqa: F811
    """The kernel's results with the release keeping the part, and with no keep."""
    step = solids["island"]
    kept, carried = module_engine.run(
        {"jobs": [_job(module_engine, step, keep="S5:60"), _job(module_engine, step)]}
    )["results"]
    return {"keep": kept, "none": carried, "south": _south(module_engine, step)}


def test_release_keep_drops_the_frame_so_later_setups_see_the_part_alone(runs):
    result = runs["keep"]
    s5 = result["setups"]["S5"]
    # Both pieces were pressed onto the stand while S5 cut: the split itself is held.
    rows = result["ops"]["S5:60"]["split_hold"]
    assert [row["held"] for row in rows] == [True, True], rows
    keep = s5["keeps"]["S5:70"]
    assert keep["feature"] == "south" and keep["after"] == "S5:60"
    assert keep["kept"]["bbox_mm"] == pytest.approx(PART_BOX, abs=1e-3)
    [frame] = keep["discarded"]
    assert frame["bbox_mm"] == pytest.approx(FRAME_BOX, abs=1e-3)
    assert frame["volume_mm3"] == pytest.approx(FRAME_MM3, rel=1e-6)
    assert s5["stock_out_bbox_mm"] == pytest.approx(PART_BOX, abs=1e-3)
    for later in ("S6", "S7"):
        facts = result["setups"][later]
        assert "stock_reason" not in facts, facts.get("stock_reason")
        assert facts["stock_bbox_mm"] == pytest.approx(PART_BOX, abs=1e-3)
        assert facts["stock_volume_mm3"] == pytest.approx(keep["kept"]["volume_mm3"], rel=1e-9)


def test_without_keep_every_held_piece_is_carried_on_as_before(runs):
    carried = runs["none"]
    assert "keeps" not in carried["setups"]["S5"]
    for later in ("S6", "S7"):
        assert carried["setups"][later]["stock_bbox_mm"] == pytest.approx(FRAME_BOX, abs=1e-3)
    kept = runs["keep"]["setups"]["S5"]["keeps"]["S5:70"]["kept"]["volume_mm3"]
    volume = carried["setups"]["S6"]["stock_volume_mm3"]
    assert volume == pytest.approx(kept + FRAME_MM3, rel=1e-6)


def _bundle(result, south, keep=True):
    """The issue's plan: S5 splits and releases, S6 and S7 state the part's own heights."""
    state = {"stock_state": {"top_z": 20 + LEAVE, "bottom_z": 0.0}}
    release = {**RELEASE, "keep": "south"} if keep else RELEASE
    return Bundle(
        plan={
            "setups": [
                {"id": "S5", "machine": "bench", "ops": [SPLIT, release]},
                {"id": "S6", "machine": "mill", "ops": [], **state},
                {"id": "S7", "machine": "mill", "ops": [], **state},
            ]
        },
        inventory={"machines": {"mill": {"kind": "mill"}, "bench": {"kind": "bench"}}},
        features={"features": {"south": {"kind": "wall", "faces": south}}, "units": "mm"},
        policy={},
        cutting_data={},
        paths={},
        hashes={},
        root=Path("."),
        kernel=result,
    )


def test_the_report_logs_the_discard_and_later_stock_states_describe_the_part(runs):
    data = _bundle(runs["keep"], runs["south"])
    [row] = keep_piece.evaluate(data)
    assert (row.subject, row.status) == ("S5:70", "pass")
    assert row.numbers["after"] == "S5:60" and row.numbers["feature"] == "south"
    assert row.numbers["kept"]["bbox_mm"] == pytest.approx(PART_BOX, abs=1e-3)
    assert "discards piece 1 (" in row.sentence
    assert "bbox [0.0, -5.0, 0.0, 70.0, 55.0, 21.0]" in row.sentence
    found = {f.subject: f for f in consistency.evaluate(data)}
    for later in ("S6", "S7"):
        assert found[later].status == "pass", found[later].sentence
    # Without keep the frame is carried on and the part's heights contradict the kernel.
    carried = _bundle(runs["none"], runs["south"], keep=False)
    found = {f.subject: f for f in consistency.evaluate(carried)}
    for later in ("S6", "S7"):
        assert found[later].status == "error"
        assert "the kernel's setup-entry stock top is at Z 21.0000" in found[later].sentence


def test_keep_on_the_entering_stock_keeps_its_only_piece_and_discards_nothing(engine, solids):  # noqa: F811
    # Placed before any cut, the keep sees the whole blank: one piece, nothing discarded,
    # and the later ring cut still leaves both pieces to the next setup.
    result = engine.run(_job(engine, solids["island"], keep=None))
    keep = result["setups"]["S5"]["keeps"]["S5:70"]
    assert keep["after"] is None and keep["discarded"] == []
    assert keep["kept"]["bbox_mm"] == pytest.approx(FRAME_BOX, abs=1e-3)
    assert result["setups"]["S6"]["stock_bbox_mm"] == pytest.approx(FRAME_BOX, abs=1e-3)


@pytest.mark.parametrize(
    ("feature", "words"),
    [
        ("missing", "keep names missing, which is not a feature of the part"),
        ("ghost", "keep feature ghost has no resolved faces; resolve its face references"),
    ],
)
def test_an_unresolvable_keep_is_stock_debt_with_its_instruction(engine, solids, feature, words):  # noqa: F811
    result = engine.run(_job(engine, solids["island"], keep="S5:60", feature=feature))
    s5 = result["setups"]["S5"]
    assert s5["keeps"]["S5:70"]["reason"].startswith(words), s5["keeps"]
    assert "kept" not in s5["keeps"]["S5:70"]
    # The splitting cut itself stays credited; only the stock after the keep is unknown.
    assert "stock_reason" not in result["ops"]["S5:60"].get("reasons", {})
    assert words in s5["stock_out_reason"] and s5["stock_out_reason"].startswith("S5:70: ")
    for later in ("S6", "S7"):
        assert words in result["setups"][later]["stock_reason"]
        assert "stock_bbox_mm" not in result["setups"][later]


_CLASSIFY = r"""
import importlib.util, json, os, sys
from types import SimpleNamespace
import FreeCAD, Part
V = FreeCAD.Vector
# freecadcmd would run a .py argument itself, so the engine path comes by environment.
engine_path, (target,) = os.environ["KEEP_ENGINE"], sys.argv[sys.argv.index("--") + 1:]
spec = importlib.util.spec_from_file_location("keep_engine", engine_path)
engine = importlib.util.module_from_spec(spec)
spec.loader.exec_module(engine)

west, east = Part.makeBox(10, 10, 10), Part.makeBox(10, 10, 10, V(20, 0, 0))
def plane(x0, x1):
    return Part.makePlane(x1 - x0, 10, V(x0, 0, 10))
faces = [plane(2, 8), plane(22, 28), plane(5, 25), plane(12, 18)]
owner = SimpleNamespace(features={
    "west_top": [0], "east_top": [1], "both_tops": [0, 1], "bridge": [2], "gap": [3],
})
owner._declared = lambda: owner.features
fake = SimpleNamespace(owner=owner, faces=faces)
out = {}
for stock_name, stock in {
    "split": Part.makeCompound([west, east]),
    "overlap": Part.makeCompound([west, west.copy()]),
}.items():
    for feature in owner.features:
        kept, record = engine._Setup._kept(fake, feature, stock, "S1:10")
        out[stock_name + ":" + feature] = {
            "shape": None if kept is None else [round(v, 6) for v in engine._bbox(kept)],
            **record,
        }
with open(target, "w", encoding="utf-8") as stream:
    json.dump(out, stream)
"""


def test_the_kept_piece_is_the_one_that_carries_the_whole_feature(tmp_path, freecad_kernel):
    # Two 10 mm cubes 10 mm apart; top-face patches on one, both, across the gap, or none.
    script, target = tmp_path / "classify.py", tmp_path / "classify.json"
    script.write_text(_CLASSIFY, encoding="utf-8")
    process = subprocess.run(
        [freecad_kernel, str(script), "--", str(target)],
        env={**os.environ, "KEEP_ENGINE": str(ENGINE)},
        capture_output=True,
        text=True,
        errors="replace",
        timeout=300,
    )
    assert target.exists(), process.stdout[-2000:] + process.stderr[-2000:]
    out = json.loads(target.read_text(encoding="utf-8"))
    assert out["split:west_top"]["shape"] == [0, 0, 0, 10, 10, 10]
    assert out["split:west_top"]["kept"]["piece"] == 1
    assert [row["piece"] for row in out["split:west_top"]["discarded"]] == [2]
    assert out["split:east_top"]["shape"] == [20, 0, 0, 30, 10, 10]
    for feature in ("both_tops", "bridge"):
        record = out[f"split:{feature}"]
        assert record["shape"] is None and "kept" not in record
        assert f"feature {feature} spans pieces [1, 2] of the stock after S1:10" in record["reason"]
    assert out["split:gap"]["reason"].startswith("no piece of the stock after S1:10 carries")
    assert "pieces [1, 2] of the stock after S1:10 each carry" in out["overlap:west_top"]["reason"]


# --------------------------------------------------------------------------- host side
def test_keep_follows_the_last_op_sent_to_the_kernel_at_or_before_it():
    setup = {"id": "S5", "ops": [{**SPLIT, "keep": "a"}, {**RELEASE, "keep": "b"}, RELEASE]}
    first = {"id": "S5", "ops": [{**RELEASE, "keep": "c"}, SPLIT]}
    assert _keeps(setup, [setup["ops"][0]]) == [
        {"subject": "S5:60", "feature": "a", "after": "S5:60"},
        {"subject": "S5:70", "feature": "b", "after": "S5:60"},
    ]
    assert _keeps(first, [first["ops"][1]]) == [{"subject": "S5:70", "feature": "c", "after": None}]


def test_the_keep_declaration_keys_the_kernel_job_and_its_absence_changes_nothing():
    def job(**extra):
        setup = {
            "id": "S5",
            "frame": "unknown",
            "hold": {"kind": "unknown"},
            "ops": [],
            "stock_in": "stock",
            "machine_kind": "bench",
            "locate_revolved": [],
            **extra,
        }
        return {
            "version": 1,
            "step_path": "part.step",
            "step_sha256": "a" * 64,
            "features": {},
            "as_is_faces": [],
            "stock": {},
            "setups": [setup],
        }

    plain = engine_job(job())
    assert "keep" not in plain["setups"][0]
    assert engine_job(job(keep=[])) == plain
    keys = {
        json.dumps(_cache_recipe(engine_job(job(keep=[spec]))), sort_keys=True)
        for spec in (
            {"subject": "S5:70", "feature": "south", "after": "S5:60"},
            {"subject": "S5:70", "feature": "north", "after": "S5:60"},
            {"subject": "S5:70", "feature": "south", "after": None},
        )
    }
    assert len(keys | {json.dumps(_cache_recipe(plain), sort_keys=True)}) == 4


def _rule_bundle(keep, kernel):
    return Bundle(
        plan={"setups": [{"id": "S5", "machine": "bench", "ops": [SPLIT, {**RELEASE, **keep}]}]},
        inventory={},
        features={"features": {"south": {"kind": "wall", "faces": ["#1"]}}, "units": "mm"},
        policy={},
        cutting_data={},
        paths={},
        hashes={},
        root=Path("."),
        kernel=kernel,
    )


@pytest.mark.parametrize(
    ("keep", "words"),
    [
        ({"keep": "missing"}, "S5:70: keep names missing, which is not a feature of the part"),
        ({"keep": "unknown"}, "S5:70: keep is unknown; name the finished feature"),
    ],
)
def test_a_keep_naming_no_feature_is_unknown_without_a_kernel(keep, words):
    absent = {"status": "unknown", "reason": "FreeCAD kernel not found"}
    [row] = keep_piece.evaluate(_rule_bundle(keep, absent))
    assert row.status == "unknown" and row.sentence.startswith(words), row.sentence


def test_a_keep_is_unknown_while_the_kernel_or_the_stock_before_it_is():
    absent = {"status": "unknown", "reason": "FreeCAD kernel not found"}
    [row] = keep_piece.evaluate(_rule_bundle({"keep": "south"}, absent))
    assert row.status == "unknown" and "FreeCAD kernel not found" in row.sentence
    stopped = {"status": "ok", "setups": {"S5": {"stock_reason": "plan stock is unknown"}}}
    [row] = keep_piece.evaluate(_rule_bundle({"keep": "south"}, stopped))
    assert row.status == "unknown"
    assert "in-process stock unknown: plan stock is unknown" in row.sentence
    refused = {
        "status": "ok",
        "setups": {"S5": {"keeps": {"S5:70": {"feature": "south", "reason": "no piece of x"}}}},
    }
    [row] = keep_piece.evaluate(_rule_bundle({"keep": "south"}, refused))
    assert (row.status, row.sentence) == ("unknown", "S5:70: no piece of x.")


def test_plans_without_keep_add_no_finding_and_a_keep_is_always_required():
    assert keep_piece.evaluate(_rule_bundle({}, {"status": "ok", "setups": {}})) == []
    absent = {"status": "unknown", "reason": "FreeCAD kernel not found"}
    [row] = keep_piece.evaluate(_rule_bundle({"keep": "south"}, absent))
    assert is_required(row, {"required": {}})
