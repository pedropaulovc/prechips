"""The bench checklist names only unresolved measurements on the selected plans."""

import json

import pytest
from test_cli import copy_examples, run_cli

pytestmark = pytest.mark.usefixtures("kernel_cache")


def measurement_ids(entries):
    return {entry["id"] for entry in entries}


def check_report(plan, out, *args):
    result = run_cli("check", plan, "--out", out, *args)
    assert result.returncode in {0, 2, 4}, result.stderr
    return json.loads((out / "report.json").read_bytes())


def unresolved_measurements(report, plan, inventory=None):
    return {
        f"{plan.as_posix()}:{entry['id']}"
        if entry["id"].startswith("plan.")
        else f"{inventory.as_posix()}:{entry['id']}"
        if inventory
        else entry["id"]
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
    assert ids == unresolved_measurements(report, plan)
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
    expected = unresolved_measurements(check_report(mill, tmp_path / "mill"), mill)
    expected |= unresolved_measurements(check_report(lathe, tmp_path / "lathe"), lathe)
    assert set(ids) == expected
    assert not any(identity.startswith("holders.qctp-") for identity in ids)
    reversed_result = run_cli(*common, "--plan", lathe, "--plan", mill)
    assert reversed_result.returncode == 0, reversed_result.stderr
    assert reversed_result.stdout == result.stdout


def test_shared_setup_and_operation_ids_keep_each_plans_authoring_debt(tmp_path):
    examples = copy_examples(tmp_path)
    rocker = examples / "rocker-arm" / "plan.toml"
    bracket = examples / "pivot-bracket" / "plan.toml"
    rocker.write_text(
        rocker.read_text(encoding="utf-8").replace("to_z = -2.07825", 'to_z = "unknown"'),
        encoding="utf-8",
    )
    common = ("tools", "--measure", "--json")
    result = run_cli(*common, "--plan", rocker, "--plan", bracket)
    assert result.returncode == 0, result.stderr
    entries = json.loads(result.stdout)
    ids = measurement_ids(entries)
    rocker_report = check_report(rocker, tmp_path / "rocker")
    bracket_report = check_report(bracket, tmp_path / "bracket")
    expected = unresolved_measurements(rocker_report, rocker)
    expected |= unresolved_measurements(bracket_report, bracket)
    assert ids == expected
    by_id = {entry["id"]: entry for entry in entries}
    local_id = "plan.setups.S1.ops.20.z_geometry"
    instructions = []
    for plan, report in ((rocker, rocker_report), (bracket, bracket_report)):
        report_entry = next(
            entry
            for finding in report["findings"]
            if finding["status"] == "unknown"
            for entry in finding["numbers"].get("measurements", [])
            if entry["id"] == local_id
        )
        entry = by_id[f"{plan.as_posix()}:{local_id}"]
        assert entry["instruction"] == f"{plan.as_posix()}: {report_entry['instruction']}"
        instructions.append(report_entry["instruction"])
    assert instructions[0] != instructions[1]
    shared_id = "machines.PM-30MV.envelope.spindle_to_table_min"
    assert sum(entry["id"] == shared_id for entry in entries) == 1
    reversed_result = run_cli(*common, "--plan", bracket, "--plan", rocker)
    assert reversed_result.returncode == 0, reversed_result.stderr
    reversed_entries = json.loads(reversed_result.stdout)
    assert measurement_ids(reversed_entries) == ids
    for entry in reversed_entries:
        if entry["id"].startswith((f"{rocker.as_posix()}:", f"{bracket.as_posix()}:")):
            assert entry == by_id[entry["id"]]


@pytest.mark.parametrize("override", [False, True])
def test_different_declared_inventories_scope_debt_unless_overridden(tmp_path, override):
    examples = copy_examples(tmp_path)
    rocker = examples / "rocker-arm" / "plan.toml"
    bracket = examples / "pivot-bracket" / "plan.toml"
    inventory = examples / "inventory" / "pedro-shop.toml"
    other_inventory = inventory.with_name("other-shop.toml")
    other_inventory.write_bytes(inventory.read_bytes())
    bracket.write_text(
        bracket.read_text(encoding="utf-8").replace("pedro-shop.toml", "other-shop.toml"),
        encoding="utf-8",
    )
    common = ("tools", "--measure", "--json")
    inventory_args = ("--inventory", inventory) if override else ()
    common += inventory_args
    bracket_report = check_report(bracket, tmp_path / "bracket", *inventory_args)
    result = run_cli(*common, "--plan", rocker, "--plan", bracket)
    assert result.returncode == 0, result.stderr
    entries = json.loads(result.stdout)
    expected = unresolved_measurements(
        check_report(rocker, tmp_path / "rocker"), rocker, None if override else inventory
    )
    expected |= unresolved_measurements(
        bracket_report, bracket, None if override else other_inventory
    )
    assert measurement_ids(entries) == expected
    shared_id = "machines.PM-30MV.envelope.spindle_to_table_min"
    if override:
        assert sum(entry["id"] == shared_id for entry in entries) == 1
    else:
        by_id = {entry["id"]: entry for entry in entries}
        for source in (inventory, other_inventory):
            entry = by_id[f"{source.as_posix()}:{shared_id}"]
            assert entry["instruction"].startswith(f"{source.as_posix()}: ")
    reversed_result = run_cli(*common, "--plan", bracket, "--plan", rocker)
    assert reversed_result.returncode == 0, reversed_result.stderr
    assert measurement_ids(json.loads(reversed_result.stdout)) == expected


def test_default_examples_checklist_has_no_unread_spec_measurements():
    result = run_cli("tools", "--measure", "--json")
    assert result.returncode == 0, result.stderr
    entries = json.loads(result.stdout)
    ids = measurement_ids(entries)
    assert "machines.PM-30MV.envelope.spindle_to_table_min" in ids
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
