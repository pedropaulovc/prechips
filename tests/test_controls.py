"""Each negative control asserts the prescribed stop and its named cause."""

import json

import pytest
from test_cli import copy_examples, traveler


def finding(report, rule, subject):
    return next(
        row for row in report["findings"] if row["rule"] == rule and row["subject"] == subject
    )


def test_removed_reamer_is_named_inventory_error(tmp_path):
    examples = copy_examples(tmp_path)
    plan = examples / "rocker-arm" / "plan.toml"
    inventory = examples / "inventory" / "pedro-shop.toml"
    original = inventory.read_text(encoding="utf-8")
    plan.write_text(
        plan.read_text(encoding="utf-8").replace("reamers-metric/6.5-H7", "control-reamer-6.5"),
        encoding="utf-8",
    )
    known = (
        '\n[tools."control-reamer-6.5"]\nkind = "reamer"\nverify = false\n'
        'dia_mm = 6.5\nshank_mm = 6.5\nlead_mm = 1.0\nunits = "mm"\n'
    )
    inventory.write_text(original + known, encoding="utf-8")
    _, present, _ = traveler(plan, tmp_path / "present")
    assert finding(present, "tool_resolves", "control-reamer-6.5")["status"] == "pass"
    inventory.write_text(original, encoding="utf-8")
    result, absent, html = traveler(plan, tmp_path / "absent")
    assert result.returncode == 2, result.stderr
    row = finding(absent, "tool_resolves", "control-reamer-6.5")
    assert row["status"] == "error"
    assert "reamer" in row["message"].lower()
    assert "reamer" in (html + result.stderr).lower()


def test_reversed_dro_direction_swaps_expected_and_mirrored_readings(tmp_path):
    examples = copy_examples(tmp_path)
    plan = examples / "rocker-arm" / "plan.toml"
    _, baseline, _ = traveler(plan, tmp_path / "baseline")
    before = finding(baseline, "zero_check", "S1")["numbers"]["axes"]["x"]
    assert before["axis_set"] == pytest.approx(-157.54)
    assert before["check_reading"] == pytest.approx(-147.54)
    assert before["mirrored_reading"] == pytest.approx(-167.54)
    plan.write_text(
        plan.read_text(encoding="utf-8").replace('x = "right"', 'x = "left"', 1), encoding="utf-8"
    )
    result, reversed_report, _ = traveler(plan, tmp_path / "reversed")
    row = finding(reversed_report, "zero_check", "S1")
    after = row["numbers"]["axes"]["x"]
    assert after["axis_set"] == before["axis_set"]
    assert after["check_reading"] == before["mirrored_reading"]
    assert after["mirrored_reading"] == before["check_reading"]
    assert row["status"] == "error"
    assert result.returncode == 2


def test_removed_position_check_is_named_error_not_size_coverage(tmp_path):
    examples = copy_examples(tmp_path)
    plan = examples / "rocker-arm" / "plan.toml"
    text = plan.read_text(encoding="utf-8")
    lines = [line for line in text.splitlines() if not line.startswith("position_dia =")]
    plan.write_text("\n".join(lines) + "\n", encoding="utf-8")
    result, report, _ = traveler(plan, tmp_path / "out")
    assert result.returncode == 2, result.stderr
    row = finding(report, "inspection", "rod_hole:position_dia")
    assert row["status"] == "error"
    assert "position" in row["message"].lower()
    assert finding(report, "inspection", "rod_hole:dia")["status"] != "error"


def clean_inspection_bundle(tmp_path):
    examples = copy_examples(tmp_path)
    plan = examples / "rocker-arm" / "plan.toml"
    prefix = plan.read_text(encoding="utf-8").split("[[setups.ops]]", 1)[0]
    prefix = prefix.replace("retouch_after = [10, 20, 25, 50, 60]", "retouch_after = []")
    plan.write_text(
        prefix + '\n[[setups.ops]]\nop = 10\ndo = "inspect"\nfeature = "hub_faces"\n'
        'checks = { dia = "control-micrometer", length = "control-micrometer" }\n',
        encoding="utf-8",
    )
    features = plan.with_name("features.toml")
    features.write_text(
        'part = "rocker-arm"\nunits = "mm"\nprecision = 2\nstep_sha256 = "unknown"\n'
        "[frames.A]\norigin = [0.0, 0.0, 0.0]\nx = [1.0, 0.0, 0.0]\ny = [0.0, 1.0, 0.0]\n"
        "z = [0.0, 0.0, 1.0]\n"
        '[features.hub_faces]\nkind = "boss"\nframe = "A"\nat = [0.0, 0.0, 0.0]\n'
        'dia = [6.50, 6.53]\nlength = [5.0, 6.0]\nrequirements = ["dia", "length"]\n',
        encoding="utf-8",
    )
    inventory = examples / "inventory" / "pedro-shop.toml"
    with inventory.open("a", encoding="utf-8") as stream:
        stream.write(
            '\n[gauges.control-micrometer]\nkind = "micrometer"\nrange_mm = [0.0, 25.0]\n'
            "resolution_mm = 0.001\nverify = false\n"
        )
    (examples / "shop-policy.toml").write_text(
        '[required]\ninspection = "toleranced_features"\n', encoding="utf-8"
    )
    return plan


def test_one_unknown_tolerance_blocks_otherwise_clean_policy(tmp_path):
    plan = clean_inspection_bundle(tmp_path)
    result, baseline, _ = traveler(plan, tmp_path / "known")
    assert result.returncode == 0, result.stderr
    assert finding(baseline, "inspection", "hub_faces:dia")["status"] == "pass"
    features = plan.with_name("features.toml")
    features.write_text(
        features.read_text(encoding="utf-8").replace("dia = [6.50, 6.53]", 'dia = "unknown"'),
        encoding="utf-8",
    )
    result, report, html = traveler(plan, tmp_path / "unknown")
    assert result.returncode == 4, result.stderr
    row = finding(report, "inspection", "hub_faces:dia")
    assert row["status"] == "unknown"
    assert row["numbers"]["limits"] == "unknown"
    assert finding(report, "inspection", "hub_faces:length")["status"] == "pass"
    assert not any(row["status"] == "error" for row in report["findings"])
    assert "PLANNED" in html
    assert "hub_faces" in (html + result.stderr)


def test_approval_stales_when_feature_input_changes(tmp_path):
    plan = clean_inspection_bundle(tmp_path)
    result, baseline, _ = traveler(plan, tmp_path / "baseline")
    assert result.returncode == 0, result.stderr
    approval = tmp_path / "approvals.toml"
    lines = [
        f'hash = "{baseline["hash"]}"',
        'first_article = "Control first article accepted"',
    ]
    for kind, record in baseline["inputs"].items():
        lines.extend(
            [
                f'[inputs."{kind}"]',
                f"path = {json.dumps(record['path'])}",
                f'sha256 = "{record["sha256"]}"',
            ]
        )
    approval.write_text("\n".join(lines) + "\n", encoding="utf-8")
    result, _, html = traveler(plan, tmp_path / "approved", "--approval", approval)
    assert result.returncode == 0, result.stderr
    assert "CHECKED" in html
    assert "PLANNED" not in html
    features = plan.with_name("features.toml")
    features.write_text(
        features.read_text(encoding="utf-8").replace("[6.50, 6.53]", "[6.50, 6.54]"),
        encoding="utf-8",
    )
    result, report, html = traveler(plan, tmp_path / "stale", "--approval", approval)
    assert result.returncode == 0, result.stderr
    assert report["hash"] != baseline["hash"]
    assert "PLANNED" in html
    assert "CHECKED" not in html
    assert "features" in result.stderr.lower()
    assert "features" in html.lower()
