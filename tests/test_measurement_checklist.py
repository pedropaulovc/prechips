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


def checklist_plans(tmp_path, *, separate_inventories=False):
    """Two authored mill consumers; unknown dimensions remain real measurement debt."""
    inventory = tmp_path / "inventory.toml"
    inventory.write_text(
        """[machines.PM-30MV]
kind = "mill"
[machines.PM-30MV.envelope]
spindle_to_table_max_mm = "unknown"
spindle_to_table_min_mm = "unknown"
travel_mm = { x = "unknown", y = "unknown", z = "unknown" }
[tools.endmill]
kind = "endmill"
dia_mm = "unknown"
oal_mm = "unknown"
[holders.collet]
kind = "collet"
gauge_len_mm = "unknown"
grip_mm = "unknown"
[fixtures.vise]
kind = "vise"
bed_height_mm = "unknown"
""",
        encoding="utf-8",
    )
    other_inventory = (
        inventory.with_name("other-inventory.toml") if separate_inventories else inventory
    )
    if separate_inventories:
        other_inventory.write_bytes(inventory.read_bytes())
    (tmp_path / "features.toml").write_text(
        """part = "scratch"
units = "mm"
[frames.model]
origin = [0, 0, 0]
x = [1, 0, 0]
y = [0, 1, 0]
z = [0, 0, 1]
[features.subject]
kind = "face"
frame = "model"
requirements = []
""",
        encoding="utf-8",
    )
    (tmp_path / "policy.toml").write_text(
        '[required]\ninspection = "*"\nop_chain = "*"\nheadroom = "*"\n',
        encoding="utf-8",
    )
    (tmp_path / "cutting.toml").write_text("revision = 1\n", encoding="utf-8")
    plans = []
    for name, source, z_field in (
        ("first", inventory, "to_z"),
        ("second", other_inventory, "z_to"),
    ):
        plan = tmp_path / f"{name}.toml"
        plan.write_text(
            f"""part = "scratch"
features = "features.toml"
[paths]
inventory = "{source.name}"
policy = "policy.toml"
cutting_data = "cutting.toml"
[[setups]]
id = "S1"
machine = "PM-30MV"
frame = "model"
coolant = "unknown"
deburr_mm = "unknown"
hold = {{ fixture = "vise" }}
stock_state = {{ top_z = "unknown", bottom_z = "unknown" }}
zero = "unknown"
[[setups.ops]]
op = 20
do = "face"
feature = "subject"
tool = "endmill"
holder = "collet"
approach_mm = "unknown"
{z_field} = "unknown"
""",
            encoding="utf-8",
        )
        plans.append(plan)
    return (*plans, inventory, other_inventory)


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
    first, second, inventory, _ = checklist_plans(tmp_path)
    # Same S1/op 20 identity, but independently unknown authored Z target fields.
    common = ("tools", "--measure", "--json")
    result = run_cli(*common, "--plan", first, "--plan", second, setup=SYNTHETIC_KERNEL)
    assert result.returncode == 0, result.stderr
    entries = json.loads(result.stdout)
    ids = measurement_ids(entries)
    first_report = check_report(first, tmp_path / "first-report")
    second_report = check_report(second, tmp_path / "second-report")
    expected = unresolved_measurements(first_report, first)
    expected |= unresolved_measurements(second_report, second)
    assert ids == expected
    assert [entry["id"] for entry in entries] == sorted(ids)
    by_id = {entry["id"]: entry for entry in entries}
    local_id = "plan.setups.S1.ops.20.z_geometry"
    instructions = []
    for plan, report, z_field in (
        (first, first_report, "to_z"),
        (second, second_report, "z_to"),
    ):
        report_entry = next(
            entry
            for finding in report["findings"]
            if finding["status"] == "unknown"
            for entry in finding["numbers"].get("measurements", [])
            if entry["id"] == local_id
        )
        entry = by_id[f"{plan.as_posix()}:{local_id}"]
        assert entry["instruction"] == f"{plan.as_posix()}: {report_entry['instruction']}"
        assert f"plan.setups.S1.ops.20.{z_field}" in report_entry["instruction"]
        assert entry["units"] == report_entry["units"] == "mm"
        assert entry["cite"] == report_entry["cite"] == ["plan.setups.S1.ops.20"]
        instructions.append(report_entry["instruction"])
    assert instructions[0] != instructions[1]
    assert sum(entry["id"] == SPINDLE_MIN for entry in entries) == 1
    assert by_id[SPINDLE_MIN]["units"] == "mm"
    assert by_id[SPINDLE_MIN]["cite"] == [f"inventory.{SPINDLE_MIN}"]
    assert not by_id[SPINDLE_MIN]["instruction"].startswith(f"{inventory.as_posix()}: ")
    reversed_result = run_cli(*common, "--plan", second, "--plan", first, setup=SYNTHETIC_KERNEL)
    assert reversed_result.returncode == 0, reversed_result.stderr
    reversed_entries = json.loads(reversed_result.stdout)
    assert measurement_ids(reversed_entries) == ids
    assert [entry["id"] for entry in reversed_entries] == sorted(ids)
    for entry in reversed_entries:
        if entry["id"].startswith((f"{first.as_posix()}:", f"{second.as_posix()}:")):
            assert entry == by_id[entry["id"]]


@pytest.mark.parametrize("override", [False, True])
def test_different_declared_inventories_scope_debt_unless_overridden(tmp_path, override):
    first, second, inventory, other_inventory = checklist_plans(tmp_path, separate_inventories=True)
    assert inventory != other_inventory
    assert inventory.read_bytes() == other_inventory.read_bytes()
    common = ("tools", "--measure", "--json")
    inventory_args = ("--inventory", inventory) if override else ()
    common += inventory_args
    first_report = check_report(first, tmp_path / "first-report", *inventory_args)
    second_report = check_report(second, tmp_path / "second-report", *inventory_args)
    result = run_cli(*common, "--plan", first, "--plan", second, setup=SYNTHETIC_KERNEL)
    assert result.returncode == 0, result.stderr
    entries = json.loads(result.stdout)
    expected = unresolved_measurements(first_report, first, None if override else inventory)
    expected |= unresolved_measurements(
        second_report, second, None if override else other_inventory
    )
    assert measurement_ids(entries) == expected
    assert [entry["id"] for entry in entries] == sorted(expected)
    by_id = {entry["id"]: entry for entry in entries}
    spindle_entry = next(
        entry
        for finding in first_report["findings"]
        if finding["status"] == "unknown"
        for entry in finding["numbers"].get("measurements", [])
        if entry["id"] == SPINDLE_MIN
    )
    if override:
        assert sum(entry["id"] == SPINDLE_MIN for entry in entries) == 1
        assert not any(
            f"{source.as_posix()}:{SPINDLE_MIN}" in by_id for source in (inventory, other_inventory)
        )
        assert by_id[SPINDLE_MIN] == spindle_entry
    else:
        assert SPINDLE_MIN not in by_id
        for source in (inventory, other_inventory):
            entry = by_id[f"{source.as_posix()}:{SPINDLE_MIN}"]
            assert entry["instruction"] == f"{source.as_posix()}: {spindle_entry['instruction']}"
            assert entry["units"] == spindle_entry["units"] == "mm"
            assert entry["cite"] == spindle_entry["cite"] == [f"inventory.{SPINDLE_MIN}"]
    reversed_result = run_cli(*common, "--plan", second, "--plan", first, setup=SYNTHETIC_KERNEL)
    assert reversed_result.returncode == 0, reversed_result.stderr
    reversed_entries = json.loads(reversed_result.stdout)
    assert measurement_ids(reversed_entries) == expected
    assert reversed_entries == entries


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
