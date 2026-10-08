"""Host-only checklists name unresolved measurements without dispatching native geometry."""

import json
import re

import pytest
from test_cli import ROOT, SYNTHETIC_KERNEL, copy_examples, run_cli

from prechips import kernel
from prechips.inputs import load_bundle
from prechips.measurements import measurement_checklist
from prechips.rules import MEASUREMENT_RULES

SPINDLE_MIN = "machines.PM-30MV.envelope.spindle_to_table_min"
SPINDLE_MAX = "machines.PM-30MV.envelope.spindle_to_table_max"


def forget(path, table, *keys):
    """Scratch defect: delete named single-line facts from one TOML table, leaving them absent."""
    text = path.read_text(encoding="utf-8")
    header = f"[{table}]\n"
    assert text.count(header) == 1, table
    start = text.index(header) + len(header)
    following = re.search(r"(?m)^\[", text[start:])
    end = start + following.start() if following else len(text)
    names = "|".join(re.escape(key) for key in keys)
    body, removed = re.subn(rf"(?m)^(?:{names})\s*=.*\n", "", text[start:end])
    assert removed, (table, keys)
    path.write_text(text[:start] + body + text[end:], encoding="utf-8")


def forget_spindle_minimum(inventory):
    forget(
        inventory, "machines.PM-30MV.envelope", "spindle_to_table_min_in", "spindle_to_table_min_mm"
    )


def forget_to_z(plan, setup_id, op_id):
    """Scratch defect: one op's commanded to_z becomes unknown, so its Z geometry is debt."""
    text = plan.read_text(encoding="utf-8")
    setups = re.split(r"(?m)^(?=\[\[setups\]\]$)", text)
    changed = 0
    for index, setup in enumerate(setups[1:], start=1):
        own = re.search(r'(?m)^id = "([^"]*)"', setup)
        if not own or own.group(1) != setup_id:
            continue
        blocks = re.split(r"(?m)^(?=\[\[setups\.ops\]\]$)", setup)
        for position, block in enumerate(blocks):
            if re.search(rf"(?m)^op = {op_id}\s*(?:#.*)?$", block):
                blocks[position], count = re.subn(r"(?m)^to_z = .*$", 'to_z = "unknown"', block)
                changed += count
        setups[index] = "".join(blocks)
    assert changed == 1, (plan, setup_id, op_id)
    plan.write_text("".join(setups), encoding="utf-8")


def measurement_ids(entries):
    return {entry["id"] for entry in entries}


def check_report(plan, out, *args):
    result = run_cli("check", plan, "--out", out, *args, setup=SYNTHETIC_KERNEL)
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
    # Scratch debt on the installed collet assembly: its gauge length and grip are absent, and
    # the endmill's pair projection is removed so its stick-out must come from OAL minus grip.
    forget(inventory, "holders.r8-collets-lms-4860", "gauge_len_mm", "gauge_len_in")
    forget(inventory, "holders.r8-collets-lms-4860", "grip_mm", "grip_in")
    forget(
        inventory,
        'tools.endmills-lms-6784.members."3-8in-4fl".projection_mm',
        '"r8-collets-lms-4860/3-8in"',
    )
    result = run_cli(
        "tools",
        "--measure",
        "--json",
        "--inventory",
        inventory,
        "--plan",
        plan,
        setup=SYNTHETIC_KERNEL,
    )
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
    result = run_cli(*common, "--plan", mill, "--plan", lathe, setup=SYNTHETIC_KERNEL)
    assert result.returncode == 0, result.stderr
    entries = json.loads(result.stdout)
    ids = [entry["id"] for entry in entries]
    assert ids == sorted(set(ids))
    expected = unresolved_measurements(check_report(mill, tmp_path / "mill"), mill)
    expected |= unresolved_measurements(check_report(lathe, tmp_path / "lathe"), lathe)
    assert set(ids) == expected
    assert not any(identity.startswith("holders.qctp-") for identity in ids)
    reversed_result = run_cli(*common, "--plan", lathe, "--plan", mill, setup=SYNTHETIC_KERNEL)
    assert reversed_result.returncode == 0, reversed_result.stderr
    assert reversed_result.stdout == result.stdout


def test_shared_setup_and_operation_ids_keep_each_plans_authoring_debt(tmp_path):
    examples = copy_examples(tmp_path)
    rocker = examples / "rocker-arm" / "plan.toml"
    bracket = examples / "pivot-bracket" / "plan.toml"
    # Both plans share the S1 op 20 identity and one inventory; each gets explicit debt.
    forget_to_z(rocker, "S1", 20)
    forget_to_z(bracket, "S1", 20)
    forget_spindle_minimum(examples / "inventory" / "pedro-shop.toml")
    common = ("tools", "--measure", "--json")
    result = run_cli(*common, "--plan", rocker, "--plan", bracket, setup=SYNTHETIC_KERNEL)
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
    assert sum(entry["id"] == SPINDLE_MIN for entry in entries) == 1
    reversed_result = run_cli(*common, "--plan", bracket, "--plan", rocker, setup=SYNTHETIC_KERNEL)
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
    forget_spindle_minimum(inventory)
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
    result = run_cli(*common, "--plan", rocker, "--plan", bracket, setup=SYNTHETIC_KERNEL)
    assert result.returncode == 0, result.stderr
    entries = json.loads(result.stdout)
    expected = unresolved_measurements(
        check_report(rocker, tmp_path / "rocker"), rocker, None if override else inventory
    )
    expected |= unresolved_measurements(
        bracket_report, bracket, None if override else other_inventory
    )
    assert measurement_ids(entries) == expected
    if override:
        assert sum(entry["id"] == SPINDLE_MIN for entry in entries) == 1
    else:
        by_id = {entry["id"]: entry for entry in entries}
        for source in (inventory, other_inventory):
            entry = by_id[f"{source.as_posix()}:{SPINDLE_MIN}"]
            assert entry["instruction"].startswith(f"{source.as_posix()}: ")
    reversed_result = run_cli(*common, "--plan", bracket, "--plan", rocker, setup=SYNTHETIC_KERNEL)
    assert reversed_result.returncode == 0, reversed_result.stderr
    assert measurement_ids(json.loads(reversed_result.stdout)) == expected


def test_default_examples_checklist_needs_no_native_geometry_or_warm_cache(tmp_path):
    cache = tmp_path / "fresh-kernel-cache"
    result = run_cli(
        "tools",
        "--measure",
        "--json",
        env={
            "FREECAD_CMD": str(tmp_path / "nonexistent-freecadcmd"),
            "PRECHIPS_KERNEL_CACHE": str(cache),
        },
    )
    assert result.returncode == 0, result.stderr
    entries = json.loads(result.stdout)
    assert isinstance(entries, list)
    ids = [entry["id"] for entry in entries]
    assert ids == sorted(set(ids))
    assert not cache.exists()


def test_unprewarmed_measurement_rules_keep_derived_geometry_unknown_and_fact_debt(
    tmp_path, monkeypatch
):
    examples = copy_examples(tmp_path)
    inventory = examples / "inventory" / "pedro-shop.toml"
    forget(
        inventory, "machines.PM-30MV.envelope", "spindle_to_table_max_in", "spindle_to_table_max_mm"
    )
    bundle = load_bundle(examples / "rocker-arm" / "plan.toml")
    assert bundle.kernel is None

    def refuse_geometry(*args, **kwargs):
        pytest.fail("Measurement rules must not dispatch the native kernel.")

    monkeypatch.setattr(kernel, "run_geometry", refuse_geometry)
    monkeypatch.setattr(kernel, "run_geometries", refuse_geometry)
    findings = [finding for rule in MEASUREMENT_RULES for finding in rule.evaluate(bundle)]
    received = next(
        finding for finding in findings if finding.rule == "headroom" and finding.subject == "P2"
    )
    assert received.status == "unknown"
    assert bundle.kernel is None
    assert received.numbers["stock_extent_x_mm"] == "unknown"
    assert received.numbers["stock_extent_y_mm"] == "unknown"
    assert received.numbers["kernel_status"] == "unknown"
    assert received.numbers["stock_entry_reason"]
    assert received.numbers["stock_entry_basis"] == "kernel setup-entry stock"
    assert "kernel.setups.P2.stock_bbox_mm: setup-entry stock in the setup frame" in received.cite
    assert measurement_ids(received.numbers["measurements"]) == {SPINDLE_MAX}
    by_id = {entry["id"]: entry for entry in measurement_checklist(findings)}
    debt = by_id[SPINDLE_MAX]
    assert debt["units"] == "mm"
    assert debt["instruction"].startswith("measure: PM-30MV ")
    assert "spindle nose to table at full Z-up" in debt["instruction"]
    assert "steel rule or height gauge" in debt["instruction"]
    assert debt["cite"] == [f"inventory.{SPINDLE_MAX}"]
    assert not any("stock_bbox" in identity or "stock_entry" in identity for identity in by_id)


def test_default_examples_checklist_shares_one_inventory_debt_across_default_plans(tmp_path):
    inventory = tmp_path / "inventory.toml"
    inventory.write_bytes((ROOT / "examples" / "inventory" / "pedro-shop.toml").read_bytes())
    forget_spindle_minimum(inventory)
    result = run_cli(
        "tools",
        "--measure",
        "--json",
        "--inventory",
        inventory,
        env={
            "FREECAD_CMD": str(tmp_path / "nonexistent-freecadcmd"),
            "PRECHIPS_KERNEL_CACHE": str(tmp_path / "fresh-kernel-cache"),
        },
    )
    assert result.returncode == 0, result.stderr
    ids = [entry["id"] for entry in json.loads(result.stdout)]
    # One override inventory: its debt is unprefixed and listed once for every default plan.
    assert ids.count(SPINDLE_MIN) == 1
    assert not any(identity.startswith("gauges.") or ".leadscrew." in identity for identity in ids)


def test_human_checklist_and_angle_units_match_the_current_measurement_debt(tmp_path):
    examples = copy_examples(tmp_path)
    plan = examples / "pivot-bracket" / "plan.toml"
    inventory = examples / "inventory" / "pedro-shop.toml"
    forget(inventory, 'tools.drill-index-115.members."#15"', "point_angle")
    forget_spindle_minimum(inventory)
    text = plan.read_text(encoding="utf-8")
    owned_holder = 'holder = "r8-collets-lms-4860/3-8in"'
    assert owned_holder in text
    plan.write_text(
        text.replace(owned_holder, 'holder = "inspection-unowned-holder"'), encoding="utf-8"
    )
    common = ("tools", "--measure", "--plan", plan)
    result = run_cli(*common, "--json", setup=SYNTHETIC_KERNEL)
    assert result.returncode == 0, result.stderr
    entries = json.loads(result.stdout)
    by_id = {entry["id"]: entry for entry in entries}
    required_units = {
        "tools.drill-index-115/#15.point_angle": "degrees",
        "holders.inspection-unowned-holder.resolve": "identity",
        SPINDLE_MIN: "mm",
    }
    assert required_units.keys() <= by_id.keys()
    for identity, units in required_units.items():
        assert by_id[identity]["units"] == units
    human = run_cli(*common, setup=SYNTHETIC_KERNEL)
    assert human.returncode == 0, human.stderr
    for entry in entries:
        assert entry["instruction"] in human.stdout
        if entry["id"].endswith(".resolve"):
            assert entry["units"] == "identity"
        elif entry["id"].endswith(".point_angle"):
            assert entry["units"] == "degrees"
        else:
            assert entry["units"] == "mm"
