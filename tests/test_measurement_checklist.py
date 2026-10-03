"""The bench checklist names only unresolved measurements on the selected plans."""

import json

from test_cli import copy_examples, run_cli


def measurement_ids(entries):
    return {entry["id"] for entry in entries}


def check_report(plan, out):
    result = run_cli("check", plan, "--out", out)
    assert result.returncode in {0, 2, 4}, result.stderr
    return json.loads((out / "report.json").read_bytes())


def unresolved_measurements(report):
    return {
        entry["id"]
        for finding in report["findings"]
        if finding["status"] == "unknown"
        for entry in finding["numbers"].get("measurements", [])
    }


def test_plan_scoped_checklist_names_report_members_and_debt_free_unknowns(tmp_path):
    examples = copy_examples(tmp_path)
    plan = examples / "pivot-bracket" / "plan.toml"
    inventory = examples / "inventory" / "pedro-shop.toml"
    result = run_cli("tools", "--measure", "--json", "--inventory", inventory, "--plan", plan)
    assert result.returncode == 0, result.stderr
    entries = json.loads(result.stdout)
    ids = measurement_ids(entries)
    report = check_report(plan, tmp_path / "report")
    assert ids == unresolved_measurements(report)
    # These member references, not their set roots, are the installed assemblies.
    assert "holders.r8-collets-lms-4860/3-8in.gauge_len" in ids
    # An unknown grip needs measurement even though this holder has no verify flag.
    assert "holders.r8-collets-lms-4860/3-8in.grip" in ids
    assert not any(identity.startswith("gauges.") for identity in ids)
    assert not any("leadscrew" in identity or "plate_holes" in identity for identity in ids)
    assert not any(identity.startswith("holders.qctp-") for identity in ids)


def test_repeated_plans_union_measurement_debt_without_adding_lathe_holder_gauges(tmp_path):
    examples = copy_examples(tmp_path)
    mill = examples / "pivot-bracket" / "plan.toml"
    lathe = examples / "pivot-shaft" / "plan.toml"
    inventory = examples / "inventory" / "pedro-shop.toml"
    common = ("tools", "--measure", "--json", "--inventory", inventory)
    result = run_cli(*common, "--plan", mill, "--plan", lathe)
    assert result.returncode == 0, result.stderr
    entries = json.loads(result.stdout)
    ids = [entry["id"] for entry in entries]
    assert ids == sorted(set(ids))
    expected = unresolved_measurements(check_report(mill, tmp_path / "mill"))
    expected |= unresolved_measurements(check_report(lathe, tmp_path / "lathe"))
    assert set(ids) == expected
    assert not any(identity.startswith("holders.qctp-") for identity in ids)
    reversed_result = run_cli(*common, "--plan", lathe, "--plan", mill)
    assert reversed_result.returncode == 0, reversed_result.stderr
    assert reversed_result.stdout == result.stdout


def test_default_examples_checklist_has_no_unread_spec_measurements():
    result = run_cli("tools", "--measure", "--json")
    assert result.returncode == 0, result.stderr
    entries = json.loads(result.stdout)
    ids = measurement_ids(entries)
    assert "machines.PM-30MV.envelope.spindle_to_table_min" in ids
    assert "fixtures.vise-pm-6.bed_height" in ids
    assert not any(
        term in identity
        for identity in ids
        for term in (
            "spindle_stack",
            "spindle_taper",
            "t_slot_pitch",
            "table_length",
            "table_width",
        )
    )
    assert not any(identity.startswith("gauges.") or ".leadscrew." in identity for identity in ids)


def test_human_checklist_and_angle_units_match_the_current_measurement_debt(tmp_path):
    examples = copy_examples(tmp_path)
    plan = examples / "pivot-bracket" / "plan.toml"
    common = ("tools", "--measure", "--plan", plan)
    result = run_cli(*common, "--json")
    assert result.returncode == 0, result.stderr
    entries = json.loads(result.stdout)
    human = run_cli(*common)
    assert human.returncode == 0, human.stderr
    for entry in entries:
        assert entry["instruction"] in human.stdout
        if entry["id"].endswith(".resolve"):
            assert entry["units"] == "identity"
        elif entry["id"].endswith(".point_angle"):
            assert entry["units"] == "degrees"
        else:
            assert entry["units"] == "mm"
