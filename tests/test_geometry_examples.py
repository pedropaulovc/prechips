"""Synthetic geometry routes discriminate on numeric, prepared in-process stock.

Preparation geometry stays unknown; only the named target is required. FreeCAD
is necessary to measure the route rather than asserting on kernel debt.
"""

import hashlib
import math
import re

import pytest
from test_cli import copy_examples, traveler

from prechips.inputs import load_bundle
from prechips.kernel import run_geometry

GEOMETRY_RULES = {
    "accessibility",
    "reach",
    "internal_corner_radius",
    "coverage",
    "finish_coverage",
    "vise",
    "thin_wall_under_clamp",
    "fixture_interference",
}
# (bundle, plan, target setup, exit, rules that error on the target/part).
# The prescribed sharp-corner wall poses also collide with the adjacent wall.
CASES = [
    ("rocker-jaw-occluded", "plan.toml", "S3", 2, {"accessibility"}),
    ("pocket-reach", "plan.toml", "S2", 2, {"reach", "accessibility"}),
    ("pocket-reach", "long-reach.toml", "S2", 0, set()),
    ("sharp-corner", "plan.toml", "S2", 2, {"internal_corner_radius", "accessibility"}),
    ("unclaimed-face", "plan.toml", "S2", 2, {"coverage"}),
]


def run_fixture(examples, name, plan_filename, out):
    return traveler(examples / "geometry" / name / plan_filename, out)


def finding(report, rule, subject):
    return next(
        row for row in report["findings"] if row["rule"] == rule and row["subject"] == subject
    )


@pytest.mark.parametrize(("name", "plan_filename", "target_sid", "exit_code", "rules"), CASES)
def test_numeric_preparation_changes_only_the_next_setup_stock(
    tmp_path, monkeypatch, freecad_kernel, name, plan_filename, target_sid, exit_code, rules
):
    examples = copy_examples(tmp_path)
    out = tmp_path / "run"
    monkeypatch.setenv("PRECHIPS_KERNEL_CACHE", str(tmp_path / "cache"))
    result, report, html = run_fixture(examples, name, plan_filename, out)
    assert result.returncode == report["expected_exit"] == exit_code, result.stderr
    assert "PLANNED" in html
    bundle = load_bundle(examples / "geometry" / name / plan_filename)
    facts = run_geometry(bundle)
    stocks = facts["setups"]
    supply = bundle.plan["stock"]
    raw_volume = math.prod(supply["section_mm"]) * supply["length_mm"]
    assert stocks["S1"]["stock_volume_mm3"] == pytest.approx(raw_volume, abs=1e-6, rel=0)
    expected_volume = {
        "pocket-reach": 70 * 50 * 60 - (40 * 24 - (4 - math.pi) * 6**2) * 45,
        "sharp-corner": 60 * 40 * 20 - 30 * 12 * 6,
        "unclaimed-face": 60 * 40 * 20 - 30 * 40 * 10,
        # Measured from the frozen source STEP, not an invented production blank.
        "rocker-jaw-occluded": 11522.665862419535,
    }[name]
    assert stocks[target_sid]["stock_volume_mm3"] == pytest.approx(expected_volume, abs=1e-6, rel=0)
    assert raw_volume > stocks[target_sid]["stock_volume_mm3"]
    assert all("stock_reason" not in stock for stock in stocks.values())
    if target_sid == "S3":
        # Successive OCCT cuts at the rounded source bbox accumulate a few 1e-6 mm³.
        assert stocks["S2"]["stock_volume_mm3"] == pytest.approx(
            (raw_volume + expected_volume) / 2, abs=1e-5, rel=0
        )
    for setup in bundle.plan["setups"][:-1]:
        subject = f"{setup['id']}:10"
        assert finding(report, "accessibility", subject)["status"] == "unknown"
        assert finding(report, "reach", subject)["status"] == "unknown"
    render = report["renders"][target_sid]
    image = (out / render["path"]).read_bytes()
    assert image.startswith(b"\x89PNG\r\n\x1a\n")
    assert hashlib.sha256(image).hexdigest() == render["sha256"]
    assert report["inputs"][f"render:{target_sid}"]["sha256"] == render["sha256"]
    assert render["fixture"] == "modeled"
    scene = render["scene"]
    assert {key: scene[key] for key in ("fixture_kind", "jaws", "parallels", "debts")} == {
        "fixture_kind": "vise",
        "jaws": "exact",
        "parallels": "exact",
        "debts": [],
    }
    roles = {component["role"] for component in scene["components"]}
    assert roles >= {"jaw", "parallel"}
    assert all(component["exact"] for component in scene["components"])


def test_every_holding_kind_is_modeled_and_its_strap_or_centre_occludes_the_top(
    tmp_path, monkeypatch, freecad_kernel
):
    examples = copy_examples(tmp_path)
    monkeypatch.setenv("PRECHIPS_KERNEL_CACHE", str(tmp_path / "cache"))
    result, report, _ = run_fixture(examples, "fixture-holds", "plan.toml", tmp_path / "run")
    assert result.returncode == report["expected_exit"] == 2, result.stderr
    kinds = {
        sid: (render["fixture"], render["scene"]["fixture_kind"], render["scene"]["debts"])
        for sid, render in report["renders"].items()
    }
    assert kinds == {
        "S1": ("modeled", "vise", []),
        "S2": ("modeled", "angle_plate", []),
        "S3": ("modeled", "custom", []),
        "S4": ("modeled", "dividing_head", []),
        "S5": ("modeled", "chuck_4jaw", []),
        "S6": ("modeled", "chuck_3jaw", []),
    }
    access = {sid: finding(report, "accessibility", f"{sid}:10")["status"] for sid in kinds}
    # Strap over the top face (S2, S3) and the head's dead centre on it (S4) occlude it.
    assert access == {
        "S1": "pass",
        "S2": "error",
        "S3": "error",
        "S4": "error",
        "S5": "pass",
        "S6": "pass",
    }
    # Every drawn solid only touches the puck and the other solids.
    assert {finding(report, "fixture_interference", sid)["status"] for sid in kinds} == {"pass"}


def test_wide_risers_and_a_stud_through_the_part_are_fixture_interference_errors(
    tmp_path, monkeypatch, freecad_kernel
):
    examples = copy_examples(tmp_path)
    monkeypatch.setenv("PRECHIPS_KERNEL_CACHE", str(tmp_path / "cache"))
    result, report, _ = run_fixture(examples, "fixture-holds", "clash.toml", tmp_path / "run")
    assert result.returncode == report["expected_exit"] == 2, result.stderr
    rows = {sid: finding(report, "fixture_interference", sid) for sid in ("S1", "S2", "S3")}
    assert {sid: row["status"] for sid, row in rows.items()} == {
        "S1": "error",  # riser blocks span y -30..30 across the y -15..15 jaw opening
        "S2": "error",  # the stud enters the puck and the plate where it has no hole
        "S3": "pass",  # stud through the tapped-hole void and the beam's slot, heel on plate
    }
    assert rows["S1"]["numbers"]["clashes"] == [
        f"riser {n} test-riser-blocks spans y -30.0..30.0 mm, outside the jaw opening "
        "y -15.0..15.0 mm closed on the stock"
        for n in (1, 2)
    ]
    stud = "clamp 1 test-clamp-kit/stud-strap:stud"
    clashes = rows["S2"]["numbers"]["clashes"]
    assert any(c.startswith(f"{stud} interpenetrates the setup-entry stock") for c in clashes)
    assert any(c.startswith(f"test-tapped-plate:floor interpenetrates {stud}") for c in clashes)


@pytest.mark.parametrize(("name", "plan_filename", "target_sid", "exit_code", "rules"), CASES)
def test_fixture_errors_on_its_named_target_rules_only(
    tmp_path, freecad_kernel, name, plan_filename, target_sid, exit_code, rules
):
    examples = copy_examples(tmp_path)
    _, report, _ = run_fixture(examples, name, plan_filename, tmp_path / "run")
    assert {row["rule"] for row in report["findings"]} >= GEOMETRY_RULES
    errors = [row for row in report["findings"] if row["status"] == "error"]
    preparation_subjects = {"rocker-jaw-occluded": {"S1:10", "S2:10"}, "sharp-corner": {"S1:10"}}
    bundle = load_bundle(examples / "geometry" / name / plan_filename)
    preparation_prefixes = tuple(f"{setup['id']}:" for setup in bundle.plan["setups"][:-1])
    preparation_errors = [row for row in errors if row["subject"].startswith(preparation_prefixes)]
    assert {(row["rule"], row["subject"]) for row in preparation_errors} == {
        ("internal_corner_radius", subject) for subject in preparation_subjects.get(name, set())
    }
    target_errors = [row for row in errors if row not in preparation_errors]
    assert {row["rule"] for row in target_errors} == rules
    assert all(
        row["status"] in {"pass", "not_applicable"}
        for row in report["findings"]
        if row["rule"] in GEOMETRY_RULES - rules
        and (
            row["rule"] in {"coverage", "finish_coverage"}
            or row["subject"] == target_sid
            or row["subject"].startswith(target_sid + ":")
        )
    )
    if rules:
        subjects = {row["subject"] for row in target_errors}
        assert len(subjects) == 1


def test_reach_rescue_needs_only_the_longer_cutter(tmp_path, freecad_kernel):
    examples = copy_examples(tmp_path)
    _, short, _ = run_fixture(examples, "pocket-reach", "plan.toml", tmp_path / "short")
    _, long, _ = run_fixture(examples, "pocket-reach", "long-reach.toml", tmp_path / "long")
    reach = {
        "short": finding(short, "reach", "S2:10"),
        "long": finding(long, "reach", "S2:10"),
    }
    assert reach["short"]["status"] == "error"
    assert reach["long"]["status"] == "pass"
    depths = {label: row["numbers"]["reach_depth_mm"] for label, row in reach.items()}
    assert depths["short"] == depths["long"] == 45.0
    assert depths["long"] > reach["long"]["numbers"]["flute_len_mm"]
    assert reach["short"]["numbers"]["holder_wall_hits"] > 0
    assert reach["long"]["numbers"]["holder_wall_hits"] == 0
    assert reach["long"]["numbers"]["oal_mm"] > reach["short"]["numbers"]["oal_mm"]
    assert finding(short, "accessibility", "S2:10")["numbers"]["tool_hits"] == 0
    assert finding(long, "accessibility", "S2:10")["numbers"]["holder_hits"] == 0


def test_coverage_error_names_the_unclaimed_face_reference(tmp_path, freecad_kernel):
    examples = copy_examples(tmp_path)
    _, report, _ = run_fixture(examples, "unclaimed-face", "plan.toml", tmp_path / "run")
    coverage = finding(report, "coverage", "step-block")
    assert coverage["status"] == "error"
    assert coverage["numbers"]["unclaimed_faces"] == ["#185/ADVANCED_FACE[6]/"]
    assert coverage["numbers"]["face_count"] == 8


def test_sharp_corner_is_smaller_than_the_quarter_inch_cutter(tmp_path, freecad_kernel):
    examples = copy_examples(tmp_path)
    _, report, _ = run_fixture(examples, "sharp-corner", "plan.toml", tmp_path / "run")
    corner = finding(report, "internal_corner_radius", "S2:10")
    assert corner["status"] == "error"
    assert corner["numbers"]["minimum_corner_radius_mm"] == 0
    assert corner["numbers"]["tool_radius_mm"] == pytest.approx(3.175)


def test_jaw_beside_the_strap_face_occludes_the_cutter_cylinder(tmp_path, freecad_kernel):
    examples = copy_examples(tmp_path)
    bundle = examples / "geometry" / "rocker-jaw-occluded"
    _, report, _ = run_fixture(examples, "rocker-jaw-occluded", "plan.toml", tmp_path / "run")
    access = finding(report, "accessibility", "S3:10")
    assert access["status"] == "error"
    vise = finding(report, "vise", "S3")
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
    low = finding(lowered, "accessibility", "S3:10")
    assert low["numbers"]["sample_count"] == access["numbers"]["sample_count"]
    assert 0 < low["numbers"]["tool_hits"] < access["numbers"]["tool_hits"]


def test_declared_pose_is_what_completes_the_scene(tmp_path, freecad_kernel):
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
    scene = vague["renders"]["S2"]["scene"]
    assert scene["jaws"] == "lateral_undeclared"
    assert scene["parallels"] == "not_modelled"
    assert len(scene["debts"]) == 2
    assert vague["renders"]["S2"]["fixture"] != "modeled"
    assert vague["renders"]["S2"]["sha256"] != exact["renders"]["S2"]["sha256"]
    assert (
        finding(vague, "vise", "S2")["numbers"]["width_mm"]
        == finding(exact, "vise", "S2")["numbers"]["width_mm"]
    )


def test_reference_rocker_arm_binds_the_labelled_export_and_models_each_setup(
    tmp_path, pilot_kernel_cache
):
    examples = copy_examples(tmp_path)
    plan = examples / "rocker-arm" / "plan.toml"
    pilot_kernel_cache(plan)
    result, report, _ = traveler(plan, tmp_path / "ref")
    assert result.returncode == 2, result.stderr
    raw = (examples / "rocker-arm" / "rocker-arm.STEP").read_bytes()
    assert (
        report["step_sha256"]
        == report["inputs"]["step"]["sha256"]
        == hashlib.sha256(raw).hexdigest()
    )
    assert report["inputs"]["step"]["path"] == "examples/rocker-arm/rocker-arm.STEP"
    assert set(report["renders"]) == {"S1", "S2", "S3", "S4"}
    for _setup, render in report["renders"].items():
        assert render["fixture"] == "modeled"
        assert render["scene"]["debts"] == []
        assert all(component["exact"] for component in render["scene"]["components"])
        image = (tmp_path / "ref" / render["path"]).read_bytes()
        assert image.startswith(b"\x89PNG\r\n\x1a\n")
        assert hashlib.sha256(image).hexdigest() == render["sha256"]
    for setup in ("S2", "S3"):
        assert finding(report, "accessibility", setup + ":10")["status"] != "unknown"
    coverage = finding(report, "coverage", "rocker-arm")
    assert coverage["numbers"]["claimed_face_count"] == coverage["numbers"]["face_count"]
    assert coverage["numbers"]["unclaimed_faces"] == []


def test_periodic_patches_resolve_by_entity_and_ordinal_not_label(tmp_path, freecad_kernel):
    examples = copy_examples(tmp_path)
    bundle = examples / "geometry" / "rocker-jaw-occluded"
    step = (bundle / "rocker-arm.STEP").read_text(encoding="latin-1")
    records = re.findall(r"#(\d+)\s*=\s*ADVANCED_FACE\s*\(\s*'([^']*)'", step)
    labels = [label for _, label in records]
    assert len(records) == 18
    assert labels.count("HAF_PIVOT_BORE__P01") == 2
    assert [entity for entity, label in records if label == "HAF_PIVOT_BORE__P01"] == ["233", "382"]
    _, report, _ = run_fixture(examples, "rocker-jaw-occluded", "plan.toml", tmp_path / "run")
    coverage = finding(report, "coverage", "rocker-arm")
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
        row = finding(broken, rule, "rocker-arm" if rule == "coverage" else "S3:10")
        assert row["status"] == "error"
        assert row["numbers"]["mapping_errors"] == [bad]
        assert bad in row["message"]
