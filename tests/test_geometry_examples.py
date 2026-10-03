"""examples/geometry fixtures each fail on one named M4 rule through the real CLI.

They need the FreeCAD kernel; without it every geometry row is unknown and the
fixtures cannot discriminate, so the tests skip rather than assert on debt.
"""

import hashlib
import re

import pytest
from test_cli import copy_examples, traveler

GEOMETRY_RULES = {
    "accessibility",
    "reach",
    "internal_corner_radius",
    "coverage",
    "finish_coverage",
    "vise",
    "thin_wall_under_clamp",
}
# (bundle, plan, expected directory, exit, rules that error). A holder standing inside
# the pocket walls is both the reach failure and an occlusion, so pocket-reach errors on
# the same subject under both rules; nothing else errors anywhere.
CASES = [
    ("rocker-jaw-occluded", "plan.toml", "expected", 2, {"accessibility"}),
    ("pocket-reach", "plan.toml", "expected", 2, {"reach", "accessibility"}),
    ("pocket-reach", "long-reach.toml", "expected/long-reach", 0, set()),
    ("sharp-corner", "plan.toml", "expected", 2, {"internal_corner_radius"}),
    ("unclaimed-face", "plan.toml", "expected", 2, {"coverage"}),
]


def run_fixture(examples, name, plan_filename, out):
    result, report, html = traveler(examples / "geometry" / name / plan_filename, out)
    if any(row["numbers"].get("kernel_unavailable") for row in report["findings"]):
        pytest.skip("FreeCAD kernel is not installed")
    return result, report, html


def finding(report, rule):
    return next(row for row in report["findings"] if row["rule"] == rule)


@pytest.mark.parametrize(("name", "plan_filename", "expected_subdir", "exit_code", "rules"), CASES)
def test_fixture_reproduces_reference_bytes_twice(
    tmp_path, name, plan_filename, expected_subdir, exit_code, rules
):
    examples = copy_examples(tmp_path)
    outputs = []
    for run in range(2):
        out = tmp_path / f"run-{run}"
        result, report, html = run_fixture(examples, name, plan_filename, out)
        assert result.returncode == exit_code, result.stderr
        assert report["expected_exit"] == exit_code
        assert "PLANNED" in html
        outputs.append({path.name: path.read_bytes() for path in out.iterdir() if path.is_file()})
    assert outputs[0] == outputs[1]
    expected = examples / "geometry" / name / expected_subdir
    assert outputs[0] == {
        path.name: path.read_bytes() for path in expected.iterdir() if path.is_file()
    }
    render = report["renders"]["S1"]
    image = outputs[0][render["path"]]
    assert image.startswith(b"\x89PNG\r\n\x1a\n")
    assert hashlib.sha256(image).hexdigest() == render["sha256"]
    assert report["inputs"]["render:S1"]["sha256"] == render["sha256"]
    assert render["fixture"] == "modeled"
    assert render["scene"] == {"jaws": "exact", "parallels": "exact", "debts": []}


@pytest.mark.parametrize(("name", "plan_filename", "expected_subdir", "exit_code", "rules"), CASES)
def test_fixture_errors_on_its_named_rules_only(
    tmp_path, name, plan_filename, expected_subdir, exit_code, rules
):
    examples = copy_examples(tmp_path)
    _, report, _ = run_fixture(examples, name, plan_filename, tmp_path / "run")
    assert {row["rule"] for row in report["findings"]} >= GEOMETRY_RULES
    assert {row["rule"] for row in report["findings"] if row["status"] == "error"} == rules
    assert all(
        row["status"] in {"pass", "not_applicable"}
        for row in report["findings"]
        if row["rule"] in GEOMETRY_RULES - rules
    )
    if rules:
        subjects = {row["subject"] for row in report["findings"] if row["status"] == "error"}
        assert len(subjects) == 1


def test_reach_rescue_needs_only_the_longer_cutter(tmp_path):
    examples = copy_examples(tmp_path)
    _, short, _ = run_fixture(examples, "pocket-reach", "plan.toml", tmp_path / "short")
    _, long, _ = run_fixture(examples, "pocket-reach", "long-reach.toml", tmp_path / "long")
    reach = {"short": finding(short, "reach"), "long": finding(long, "reach")}
    assert reach["short"]["status"] == "error"
    assert reach["long"]["status"] == "pass"
    depths = {label: row["numbers"]["reach_depth_mm"] for label, row in reach.items()}
    assert depths["short"] == depths["long"] > reach["long"]["numbers"]["flute_len_mm"]
    assert reach["short"]["numbers"]["holder_wall_hits"] > 0
    assert reach["long"]["numbers"]["holder_wall_hits"] == 0
    assert reach["long"]["numbers"]["oal_mm"] > reach["short"]["numbers"]["oal_mm"]
    assert finding(short, "accessibility")["numbers"]["tool_hits"] == 0
    assert finding(long, "accessibility")["numbers"]["holder_hits"] == 0


def test_coverage_error_names_the_unclaimed_face_reference(tmp_path):
    examples = copy_examples(tmp_path)
    _, report, _ = run_fixture(examples, "unclaimed-face", "plan.toml", tmp_path / "run")
    coverage = finding(report, "coverage")
    assert coverage["status"] == "error"
    assert coverage["numbers"]["unclaimed_faces"] == ["#185/ADVANCED_FACE[6]/"]
    assert coverage["numbers"]["face_count"] == 8


def test_sharp_corner_is_smaller_than_the_quarter_inch_cutter(tmp_path):
    examples = copy_examples(tmp_path)
    _, report, _ = run_fixture(examples, "sharp-corner", "plan.toml", tmp_path / "run")
    corner = finding(report, "internal_corner_radius")
    assert corner["status"] == "error"
    assert corner["numbers"]["minimum_corner_radius_mm"] == 0
    assert corner["numbers"]["tool_radius_mm"] == pytest.approx(3.175)


def test_jaw_beside_the_strap_face_occludes_the_cutter_cylinder(tmp_path):
    examples = copy_examples(tmp_path)
    bundle = examples / "geometry" / "rocker-jaw-occluded"
    _, report, _ = run_fixture(examples, "rocker-jaw-occluded", "plan.toml", tmp_path / "run")
    access = finding(report, "accessibility")
    assert access["status"] == "error"
    vise = finding(report, "vise")
    assert vise["status"] == "pass"
    assert vise["numbers"]["parallel_pair"] is True
    assert vise["numbers"]["width_mm"] == pytest.approx(7.0565)
    # Same part, cutter and clamp planes with the jaw tops dropped to the tips: the
    # strap face no longer stands beside a jaw, so only the hub boss still occludes.
    plan = (bundle / "plan.toml").read_text(encoding="utf-8")
    assert plan.count("jaw_above_parallels_mm = 26.0") == 1
    (bundle / "low-jaws.toml").write_text(
        plan.replace("jaw_above_parallels_mm = 26.0", "jaw_above_parallels_mm = 1.0"),
        encoding="utf-8",
    )
    _, lowered, _ = traveler(bundle / "low-jaws.toml", tmp_path / "low")
    low = finding(lowered, "accessibility")
    assert low["numbers"]["sample_count"] == access["numbers"]["sample_count"]
    assert 0 < low["numbers"]["tool_hits"] < access["numbers"]["tool_hits"]


def test_declared_pose_is_what_completes_the_scene(tmp_path):
    examples = copy_examples(tmp_path)
    bundle = examples / "geometry" / "pocket-reach"
    _, exact, _ = run_fixture(examples, "pocket-reach", "long-reach.toml", tmp_path / "exact")
    plan = (bundle / "long-reach.toml").read_text(encoding="utf-8")
    lines = plan.splitlines(keepends=True)
    for key in ("jaw_center_along_mm", "parallels_centres_mm"):
        assert sum(line.startswith(key + " = ") for line in lines) == 1
    (bundle / "no-pose.toml").write_text(
        "".join(
            line
            for line in lines
            if not line.startswith(("jaw_center_along_mm", "parallels_centres_mm"))
        ),
        encoding="utf-8",
    )
    result, vague, _ = traveler(bundle / "no-pose.toml", tmp_path / "vague")
    assert result.returncode == exact["expected_exit"] == 0
    scene = vague["renders"]["S1"]["scene"]
    assert scene["jaws"] == "lateral_undeclared"
    assert scene["parallels"] == "not_modelled"
    assert len(scene["debts"]) == 2
    assert vague["renders"]["S1"]["fixture"] != "modeled"
    assert vague["renders"]["S1"]["sha256"] != exact["renders"]["S1"]["sha256"]
    assert (
        finding(vague, "vise")["numbers"]["width_mm"]
        == finding(exact, "vise")["numbers"]["width_mm"]
    )


def test_reference_rocker_arm_binds_the_labelled_export_and_names_unbound_faces(tmp_path):
    examples = copy_examples(tmp_path)
    result, report, html = traveler(examples / "rocker-arm" / "plan.toml", tmp_path / "ref")
    if any(row["numbers"].get("kernel_unavailable") for row in report["findings"]):
        pytest.skip("FreeCAD kernel is not installed")
    assert result.returncode == 2, result.stderr
    raw = (examples / "rocker-arm" / "rocker-arm.STEP").read_bytes()
    assert raw == (examples / "geometry" / "rocker-jaw-occluded" / "rocker-arm.STEP").read_bytes()
    assert b"\r\n" in raw  # the consumer's bytes, not a newline-normalised copy
    assert (
        report["step_sha256"]
        == report["inputs"]["step"]["sha256"]
        == hashlib.sha256(raw).hexdigest()
    )
    assert report["inputs"]["step"]["path"] == "examples/rocker-arm/rocker-arm.STEP"
    assert set(report["renders"]) == {"S1", "S2", "S3"}
    assert all(render["fixture"] != "modeled" for render in report["renders"].values())
    assert not any(
        row["status"] == "error" for row in report["findings"] if row["rule"] in GEOMETRY_RULES
    )
    coverage = finding(report, "coverage")
    assert coverage["status"] == "unknown"
    assert coverage["numbers"]["face_count"] == 18
    assert coverage["numbers"]["unclaimed_faces"] == [
        "#248/ADVANCED_FACE[6]/HAF_TIP_LAND_POS_X__P01",
        "#431/ADVANCED_FACE[10]/HAF_TIP_LAND_NEG_X__P01",
        "#492/ADVANCED_FACE[13]/HAF_STRAP_DATUM_B__P01",
    ]
    corner = {
        row["subject"]: row for row in report["findings"] if row["rule"] == "internal_corner_radius"
    }
    assert corner["S1:40"]["status"] == "pass"
    assert corner["S1:40"]["numbers"]["corner_radii_mm"] == [800.0]


def test_periodic_patches_resolve_by_entity_and_ordinal_not_label(tmp_path):
    examples = copy_examples(tmp_path)
    bundle = examples / "geometry" / "rocker-jaw-occluded"
    step = (bundle / "rocker-arm.STEP").read_text(encoding="latin-1")
    records = re.findall(r"#(\d+)\s*=\s*ADVANCED_FACE\s*\(\s*'([^']*)'", step)
    labels = [label for _, label in records]
    assert len(records) == 18
    assert labels.count("HAF_PIVOT_BORE__P01") == 2
    assert [entity for entity, label in records if label == "HAF_PIVOT_BORE__P01"] == ["233", "382"]
    _, report, _ = run_fixture(examples, "rocker-jaw-occluded", "plan.toml", tmp_path / "run")
    coverage = finding(report, "coverage")
    assert coverage["status"] == "pass"
    assert coverage["numbers"]["claimed_face_count"] == coverage["numbers"]["face_count"] == 18
    # The sibling patch's ordinal under the shared label is a different record: refused,
    # never guessed.
    manifest = (bundle / "features.toml").read_text(encoding="utf-8")
    good = '"#492/ADVANCED_FACE[13]/HAF_STRAP_DATUM_B__P01"'
    bad = "#233/ADVANCED_FACE[8]/HAF_PIVOT_BORE__P01"
    assert manifest.count(good) == 1
    (bundle / "features-bad.toml").write_text(
        manifest.replace(good, f'{good}, "{bad}"'), encoding="utf-8"
    )
    plan = (bundle / "plan.toml").read_text(encoding="utf-8")
    (bundle / "bad.toml").write_text(
        plan.replace('features = "features.toml"', 'features = "features-bad.toml"'),
        encoding="utf-8",
    )
    result, broken, _ = traveler(bundle / "bad.toml", tmp_path / "bad")
    assert result.returncode == 2
    for rule in ("accessibility", "reach", "coverage"):
        row = finding(broken, rule)
        assert row["status"] == "error"
        assert row["numbers"]["mapping_errors"] == [bad]
        assert bad in row["message"]
