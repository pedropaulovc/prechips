"""Plan-owned setup frames: transforms, provenance and refusal to shadow CAD frames."""

import dataclasses
import hashlib
import shutil
import tomllib
from pathlib import Path

import pytest

from prechips import kernel
from prechips.inputs import BadInput, load_bundle
from prechips.rules import coordinates, zero_recipe

ROOT = Path(__file__).resolve().parents[1]
SHAFT = ROOT / "examples" / "pivot-shaft" / "plan.toml"
BUILT_UP = ROOT / "examples" / "cone-pivot-post" / "built-up.toml"

PLAN_FRAME = """[frames.P]
origin = [10.0, 0.0, 5.0]
x = [0.0, 1.0, 0.0]
y = [-1.0, 0.0, 0.0]
z = [0.0, 0.0, 1.0]
binding = "nominal"
note = "AUTHOR'S CHOICE: rotated test setup"
cite = ["AUTHOR'S CHOICE", "test source geometry"]
"""
PLAN = """part = "scratch"
features = "features.toml"
[paths]
inventory = "inventory.toml"
policy = "policy.toml"
cutting_data = "cutting.toml"
{frames}
[[setups]]
id = "S1"
machine = "mill"
frame = "{frame}"
coolant = "unknown"
deburr_mm = "unknown"
hold = "unknown"
stock_state = "unknown"
zero = "unknown"
[[setups.ops]]
op = 10
do = "drill"
feature = "hole"
tool = "unknown"
holder = "unknown"
"""
FEATURES = """part = "scratch"
units = "mm"
[frames.model]
origin = [0.0, 0.0, 0.0]
x = [1.0, 0.0, 0.0]
y = [0.0, 1.0, 0.0]
z = [0.0, 0.0, 1.0]
[frames.A]
origin = [1.0, 2.0, 3.0]
x = [1.0, 0.0, 0.0]
y = [0.0, 1.0, 0.0]
z = [0.0, 0.0, 1.0]
binding = "unknown"
[features.hole]
kind = "hole"
frame = "model"
at = [10.0, 20.0, 5.0]
requirements = []
"""


def bundle_path(tmp_path, frames=PLAN_FRAME, frame="P"):
    for name, text in (
        ("plan.toml", PLAN.format(frames=frames, frame=frame)),
        ("features.toml", FEATURES),
        ("inventory.toml", '[machines.mill]\nkind = "mill"\n'),
        ("policy.toml", '[required]\ncoordinates = "*"\n'),
        ("cutting.toml", "revision = 1\n"),
    ):
        (tmp_path / name).write_text(text, encoding="utf-8")
    return tmp_path / "plan.toml"


def by_setup(findings):
    return {finding.subject: finding for finding in findings}


def rows(finding):
    return {(row["feature"], row.get("point", "centre")): row for row in finding.numbers["rows"]}


def test_plan_frame_drives_setup_transform_without_touching_the_manifest(tmp_path):
    bundle = load_bundle(bundle_path(tmp_path))
    (finding,) = coordinates.evaluate(bundle)
    assert finding.numbers["frame"] == "P"
    assert finding.numbers["binding"] == "nominal"
    assert rows(finding)["hole", "centre"]["model"] == [10.0, 20.0, 5.0]
    assert rows(finding)["hole", "centre"]["setup"] == [20.0, 0.0, 0.0]
    assert "plan.frames.P: author-declared setup frame" in finding.cite
    assert "test source geometry" in finding.cite
    assert kernel.build_job(bundle)["setups"][0]["frame"] == {
        "origin": [10.0, 0.0, 5.0],
        "x": [0.0, 1.0, 0.0],
        "y": [-1.0, 0.0, 0.0],
        "z": [0.0, 0.0, 1.0],
    }
    # Plan frames stay in the plan; the exported manifest is neither merged nor rehashed.
    raw = (tmp_path / "features.toml").read_bytes()
    assert bundle.features["frames"] == tomllib.loads(raw.decode())["frames"]
    assert bundle.hashes["features"] == hashlib.sha256(raw).hexdigest()


def test_exported_setup_frame_keeps_manifest_provenance(tmp_path):
    bundle = load_bundle(bundle_path(tmp_path, frame="A"))
    (finding,) = coordinates.evaluate(bundle)
    assert rows(finding)["hole", "centre"]["setup"] == [9.0, 18.0, 2.0]
    assert not any("plan.frames" in text for text in finding.cite)


@pytest.mark.parametrize("name", ["A", "model", "setup"])
def test_plan_frame_may_not_shadow_an_exported_frame(tmp_path, name):
    frames = PLAN_FRAME.replace("[frames.P]", f"[frames.{name}]")
    path = bundle_path(tmp_path, frames=frames, frame=name)
    # An exported unknown frame name is still CAD-owned.
    features = FEATURES.replace("[frames.model]", '[frames]\nsetup = "unknown"\n[frames.model]')
    (tmp_path / "features.toml").write_text(features, encoding="utf-8")
    with pytest.raises(BadInput, match="shadow exported manifest frames"):
        load_bundle(path)


def test_an_unvalidated_collision_still_resolves_to_the_exported_frame(tmp_path):
    bundle = load_bundle(bundle_path(tmp_path))
    plan = {**bundle.plan, "frames": {"A": bundle.plan["frames"]["P"]}}
    plan["setups"] = [{**bundle.plan["setups"][0], "frame": "A"}]
    (finding,) = coordinates.evaluate(dataclasses.replace(bundle, plan=plan))
    assert rows(finding)["hole", "centre"]["setup"] == [9.0, 18.0, 2.0]
    assert finding.numbers["binding"] == "unknown"


def test_setup_frame_must_be_exported_or_plan_owned(tmp_path):
    with pytest.raises(BadInput, match="neither exported in the manifest nor declared"):
        load_bundle(bundle_path(tmp_path, frame="Q"))


@pytest.mark.parametrize(
    ("old", "new", "message"),
    [
        ('binding = "nominal"\n', "", "must state its binding"),
        ('cite = ["AUTHOR\'S CHOICE", "test source geometry"]\n', "", "must cite"),
        ("x = [0.0, 1.0, 0.0]", "x = [0.0, 1.0, 0.1]", "orthonormal"),
        ("z = [0.0, 0.0, 1.0]", "z = [0.0, 0.0, -1.0]", "right-handed"),
        ("[frames.P]", '[frames."unknown"]', "known, non-empty names"),
    ],
)
def test_incomplete_or_invalid_plan_frame_is_rejected(tmp_path, old, new, message):
    frames = PLAN_FRAME.replace(old, new)
    with pytest.raises(BadInput, match=message):
        load_bundle(bundle_path(tmp_path, frames=frames))


def test_unbound_shaft_frame_keeps_model_z_unknown_and_records_the_local_station(tmp_path):
    examples = Path(shutil.copytree(ROOT / "examples", tmp_path / "examples"))
    plan = examples / "pivot-shaft" / "plan.toml"
    text = plan.read_text(encoding="utf-8")
    head, t3 = text.split("[frames.T3]\n", 1)
    t3 = t3.replace('binding = "nominal"', 'binding = "unknown"', 1)
    plan.write_text(head + "[frames.T3]\n" + t3, encoding="utf-8")
    found = by_setup(coordinates.evaluate(load_bundle(plan)))
    assert {sid: f.numbers["binding"] for sid, f in found.items()} == {
        "S1": "nominal",
        "S2": "nominal",
        "S3": "unknown",
    }
    # A bound frame maps the op's setup Z into model Z.
    assert rows(found["S1"])["shoulder_thrust", "op 20 to_z"]["model"] == [0.0, 0.0, -7.5]
    # An unbound frame invents no model Z; the authored local station is kept and attributed.
    # S3 parts long (op 10), faces the apex (op 20) and forms the dome from it (op 30).
    apex = rows(found["S3"])["south_dome", "op 30 z_from"]
    assert apex["model"][2] == "unknown"
    assert apex["setup"] == [0.0, 0.0, 1.75]
    assert apex["local_from"] == {"op": 30, "field": "z_from", "axis": "z"}
    assert found["S3"].status == "unknown"


@pytest.mark.parametrize("rule", [coordinates, zero_recipe])
def test_unbound_frames_stay_unknown_without_inventing_a_bench_binding(tmp_path, rule):
    path = bundle_path(tmp_path, frames=PLAN_FRAME.replace('"nominal"', '"unknown"'))
    bundle = load_bundle(path)
    mill = bundle.plan["setups"][0]
    bench = {
        **mill,
        "id": "B1",
        "machine": "bench",
        "ops": [{"op": 10, "do": "inspect", "feature": "hole"}],
    }
    bundle = dataclasses.replace(
        bundle,
        plan={**bundle.plan, "setups": [mill, bench]},
        inventory={
            **bundle.inventory,
            "machines": {**bundle.inventory["machines"], "bench": {"kind": "bench"}},
        },
    )
    found = by_setup(rule.evaluate(bundle))
    assert found["S1"].numbers["binding"] == "unknown"
    assert found["S1"].status == "unknown"
    assert found["B1"].status == "not_applicable"
    assert "binding" not in found["B1"].numbers
    if rule is coordinates:
        assert rows(found["S1"])["hole", "centre"]["setup"] == [20.0, 0.0, 0.0]


@pytest.mark.parametrize("plan", [SHAFT, BUILT_UP])
def test_restored_setup_frames_live_only_in_the_plan(plan):
    bundle = load_bundle(plan)
    raw = bundle.paths["features"].read_bytes()
    assert bundle.hashes["features"] == hashlib.sha256(raw).hexdigest()
    assert bundle.features["frames"] == {
        "setup": "unknown",
        "model": tomllib.loads(raw.decode())["frames"]["model"],
    }
    planned = set(bundle.plan["frames"])
    assert {setup["frame"] for setup in bundle.plan["setups"]} == planned
