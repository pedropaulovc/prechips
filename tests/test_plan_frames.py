"""Plan-owned setup frames: transforms, provenance and refusal to shadow CAD frames."""

import dataclasses
import hashlib
import tomllib
from pathlib import Path

import pytest

from prechips import kernel
from prechips.inputs import BadInput, load_bundle
from prechips.rules import coordinates, envelope, turned_profile, zero_recipe

ROOT = Path(__file__).resolve().parents[1]
SHAFT = ROOT / "examples" / "pivot-shaft" / "plan.toml"
CONE = ROOT / "examples" / "cone-pivot-post" / "plan.toml"
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


def test_restored_shaft_frames_return_nominal_rows_and_keep_t3_unbound():
    bundle = load_bundle(SHAFT)
    found = by_setup(coordinates.evaluate(bundle))
    assert {sid: f.numbers["binding"] for sid, f in found.items()} == {
        "S1": "nominal",
        "S2": "nominal",
        "S3": "unknown",
    }
    s1, s2, s3 = (rows(found[sid]) for sid in ("S1", "S2", "S3"))
    assert s1["pivot_journal", "centre"]["setup"] == [0.0, 0.0, 3.0]
    assert s1["pivot_bearing", "centre"]["setup"] == [0.0, 0.0, -11.5]
    assert s1["shoulder_thrust", "op 60 to_z"]["model"] == [0.0, 0.0, -7.5]
    assert s2["north_dome", "op 20 z_to"]["model"] == [0.0, 0.0, 0.0]
    assert s2["pivot_journal", "centre"]["setup"] == [0.0, 0.0, -4.5]
    # T3 is a nominal transform awaiting the installed-ear span: no model Z is invented.
    apex = s3["south_dome", "op 20 z_from"]
    assert apex["model"][2] == "unknown"
    assert apex["setup"] == [0.0, 0.0, 1.75]
    assert apex["local_from"] == {"op": 20, "field": "z_from", "axis": "z"}
    assert all(f.status == "unknown" for f in found.values())
    # Turned segments without exported z_mm stay named debt rather than invented spans.
    profile = by_setup(turned_profile.evaluate(bundle))["S1"].numbers
    assert profile["intervals"] == []
    assert {"pivot_bearing", "pivot_journal", "shoulder_od"} <= set(profile["unresolved"])


@pytest.mark.parametrize("plan", [CONE, BUILT_UP])
def test_restored_cone_frames_return_numbers_but_never_a_physical_binding(plan):
    bundle = load_bundle(plan)
    found = by_setup(coordinates.evaluate(bundle))
    assert {f.numbers["binding"] for f in found.values()} == {"unknown"}
    assert all(f.status == "unknown" for f in found.values())
    assert rows(found["S3"])["journal_bore", "centre"]["setup"] == [0.0, 0.0, 0.0]
    assert rows(found["S4"])["crank_bore", "centre"]["setup"] == [0.0, 0.0, -21.3753]
    assert rows(found["S2"])["mount_west", "centre"]["setup"] == [-12.98, 0.0, 86.0]
    zero = by_setup(zero_recipe.evaluate(bundle))
    assert {f.numbers["binding"] for f in zero.values()} == {"unknown"}
    assert all(f.status != "pass" for f in zero.values())
    assert "plan.frames.J3: author-declared setup frame" in zero["S3"].cite


def test_restored_cone_envelope_extents_are_numeric_in_setup_axes():
    found = by_setup(envelope.evaluate(load_bundle(CONE)))
    assert found["S2"].numbers["part_extents_mm"] == {"x": 120.0, "y": 110.0, "z": 114.0}
    s3 = found["S3"].numbers["part_extents_mm"]
    assert s3["x"] == pytest.approx(120.0 * 0.9762272058393484 + 110.0 * 0.21674972336567902)
    assert (s3["y"], s3["z"]) == (110.0, 42.011)
    assert found["S4"].numbers["part_extents_mm"] == {"x": 120.0, "y": 110.0, "z": 72.0344}
    assert "plan.stock.section_mm/length_mm/dia_mm; plan.frames.M2 setup basis" in found["S2"].cite
    assert all(f.status == "unknown" for f in found.values() if f.subject != "S1")


@pytest.mark.parametrize("plan", [SHAFT, CONE, BUILT_UP])
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
