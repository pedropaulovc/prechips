"""Plan-owned setup frames: transforms, provenance and refusal to shadow CAD frames."""

import dataclasses
import hashlib
import shutil
import tomllib
from pathlib import Path

import pytest
from pydantic import ValidationError

from prechips import kernel
from prechips.inputs import BadInput, load_bundle
from prechips.rules import coordinates, zero_recipe
from prechips.rules.resolution import PLAN_FRAMES, setup_frame_ref

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
    frame, owner = setup_frame_ref(bundle, bundle.plan["setups"][0])
    assert owner == PLAN_FRAMES
    assert frame == bundle.plan["frames"]["P"]
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
    ("old", "new", "location"),
    [
        ('binding = "nominal"\n', "", ("frames", "P")),
        ('cite = ["AUTHOR\'S CHOICE", "test source geometry"]\n', "", ("frames", "P")),
        ("x = [0.0, 1.0, 0.0]", "x = [0.0, 1.0, 0.1]", ("frames", "P")),
        ("z = [0.0, 0.0, 1.0]", "z = [0.0, 0.0, -1.0]", ("frames", "P")),
        ("[frames.P]", '[frames."unknown"]', ()),
    ],
)
def test_incomplete_or_invalid_plan_frame_is_rejected(tmp_path, old, new, location):
    path = bundle_path(tmp_path)
    assert load_bundle(path).plan["frames"]["P"]["binding"] == "nominal"
    frames = PLAN_FRAME.replace(old, new)
    with pytest.raises(BadInput) as rejected:
        load_bundle(bundle_path(tmp_path, frames=frames))
    cause = rejected.value.__cause__
    assert isinstance(cause, ValidationError)
    assert any(
        error["type"] == "value_error"
        and tuple(part for part in error["loc"] if part in {"frames", "P"}) == location
        for error in cause.errors()
    )


def test_unbound_shaft_frame_keeps_model_z_unknown_and_records_the_local_station(tmp_path):
    examples = Path(shutil.copytree(ROOT / "examples", tmp_path / "examples"))
    plan = examples / "pivot-shaft" / "plan.toml"
    text = plan.read_text(encoding="utf-8")
    head, t3 = text.split("[frames.T3]\n", 1)
    t3 = t3.replace('binding = "nominal"', 'binding = "unknown"', 1)
    plan.write_text(head + "[frames.T3]\n" + t3, encoding="utf-8")
    found = by_setup(coordinates.evaluate(load_bundle(plan)))
    assert {sid: f.numbers["binding"] for sid, f in found.items()} == {
        "S0": "nominal",
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
    if rule is zero_recipe:
        zero = {
            axis: {
                "tool": "indicator",
                "edge_mm": 0,
                "from": "indicated" if axis != "z" else "+z",
                "check_jog_mm": 1,
                **({"paper_mm": 0, "retouch_after": []} if axis == "z" else {}),
            }
            for axis in ("x", "y", "z")
        }
        zero["tool_touches"] = []
        mill = {**mill, "zero": zero, "ops": bench["ops"]}
        bundle = dataclasses.replace(
            bundle,
            plan={
                **bundle.plan,
                "setups": [mill, bench],
                "dro": {
                    "controller": "EL400",
                    "mode": "abs",
                    "radius_mode": True,
                    "direction": {"x": "right", "y": "away", "z": "up"},
                },
            },
            inventory={
                **bundle.inventory,
                "tools": {"indicator": {"kind": "indicator", "verify": False}},
            },
        )
        bound = dataclasses.replace(
            bundle,
            plan={
                **bundle.plan,
                "frames": {"P": {**bundle.plan["frames"]["P"], "binding": "nominal"}},
            },
        )
        baseline = by_setup(rule.evaluate(bound))["S1"]
        assert baseline.status == "pass"
        assert {axis: row["axis_set"] for axis, row in baseline.numbers["axes"].items()} == {
            "x": 0,
            "y": 0,
            "z": 0,
        }
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
    assert bundle.features["frames"] == tomllib.loads(raw.decode())["frames"]
    findings = by_setup(coordinates.evaluate(bundle))
    for setup in bundle.plan["setups"]:
        finding = findings[setup["id"]]
        if finding.status == "not_applicable":
            assert finding.numbers["machine_kind"] in {"bench", "manual"}
            assert "frame" not in finding.numbers
            assert "binding" not in finding.numbers
            assert "rows" not in finding.numbers
            unframed = dataclasses.replace(
                bundle,
                plan={
                    **bundle.plan,
                    "setups": [{key: value for key, value in setup.items() if key != "frame"}],
                },
            )
            (unframed_finding,) = coordinates.evaluate(unframed)
            assert unframed_finding.status == "not_applicable"
            assert unframed_finding.numbers == finding.numbers
            continue
        frame, owner = setup_frame_ref(bundle, setup)
        assert owner == PLAN_FRAMES
        assert frame == bundle.plan["frames"][setup["frame"]]
        assert finding.numbers["frame"] == setup["frame"]
        assert finding.numbers["binding"] == frame["binding"]
    representative = next(
        (setup, row)
        for setup in bundle.plan["setups"]
        if findings[setup["id"]].status != "not_applicable"
        for row in findings[setup["id"]].numbers["rows"]
        if not row.get("local_from")
        and all(isinstance(value, (int, float)) for value in row["model"])
        and all(isinstance(value, (int, float)) for value in row["setup"])
    )
    setup, row = representative
    frame = bundle.plan["frames"][setup["frame"]]
    offset = [value - origin for value, origin in zip(row["model"], frame["origin"], strict=True)]
    expected = [
        sum(value * basis for value, basis in zip(offset, frame[axis], strict=True))
        for axis in ("x", "y", "z")
    ]
    assert row["setup"] == pytest.approx(expected, abs=1e-3)
