"""Host-only consumers name only the recorded physical facts their recipes use."""

import json

import pytest
from test_cli import run_cli
from test_manual_arc import (
    SWING,
    arcs,
    change,
    coordinates_row,
    op,
    rotary_plan,
    scratch,
)

from prechips.inputs import load_bundle
from prechips.measurements import measurement_checklist
from prechips.rules import tip_endpoints
from prechips.rules.zero_recipe import rule as zero_recipe_rule

STATUSES = ["measured", "assumed", "illustrative", None]


def fact(value, status):
    metadata = {
        "by": "synthetic auxiliary-fact machinist",
        "date": "2026-10-11",
        "instrument": "synthetic shop observation or dimensional gauge",
    }
    if status is not None:
        metadata["status"] = status
    fields = ", ".join(f"{key} = {json.dumps(text)}" for key, text in metadata.items())
    return f"{{ value = {json.dumps(value)}, verify = false, measured = {{ {fields} }} }}"


def ids(finding):
    return {entry["id"] for entry in measurement_checklist([finding])}


def assert_same_pass(actual, expected):
    assert actual.status == expected.status == "pass", actual.sentence
    assert actual.numbers == expected.numbers
    assert actual.sentence == expected.sentence
    assert actual.cite == expected.cite


@pytest.mark.parametrize("status", STATUSES)
@pytest.mark.parametrize("method", ["stairs", "rotary_table"])
def test_consumed_spindle_rotation_is_named_without_discarding_numeric_instructions(
    tmp_path, method, status
):
    if method == "rotary_table":
        plan = rotary_plan(tmp_path)
    else:
        plan = scratch(
            tmp_path,
            op(20, "rough_profile", "{ method = 'stairs', cusp_mm = 0.25 }", allowance=0.2),
        )
    change(plan, "machine = 'mill'", "machine = 'machines.mill'")
    baseline = coordinates_row(plan, stock_bbox=SWING)
    change(plan.with_name("inventory.toml"), "rotation = 'cw'", f"rotation = {fact('cw', status)}")
    finding = coordinates_row(plan, stock_bbox=SWING)
    if status == "measured":
        assert_same_pass(finding, baseline)
        return
    assert finding.status == "unknown", finding.sentence
    assert ids(finding) == {"machines.mill.spindle.rotation"}
    (table,) = arcs(finding, 20)
    assert table["cut_order"] == "unknown"
    assert table["rows"]
    assert all(isinstance(value, (int, float)) for row in table["rows"] for value in row["dro_xy"])
    if method == "rotary_table":
        assert table["rotary"]["offset_x"] == pytest.approx(13.0)
        assert table["rotary"]["rotation"] == "unknown"


@pytest.mark.parametrize("status", STATUSES)
@pytest.mark.parametrize("field,value", [("max_work", 150.0), ("bore_dia", 6.0)])
@pytest.mark.parametrize("by", ["pin", "indicate"])
def test_rotary_dimensions_are_named_only_when_the_recipe_consumes_them(
    tmp_path, by, field, value, status
):
    plan = rotary_plan(tmp_path, by=by)
    change(plan, "fixture = 'table'", "fixture = 'fixtures.table'")
    baseline = coordinates_row(plan, stock_bbox=SWING)
    inventory = plan.with_name("inventory.toml")
    change(inventory, f"{field}_mm = {value}", f"{field}_mm = {fact(value, status)}")
    # An unrelated recorded dimension is not a debt of this rotary recipe.
    change(
        inventory,
        "kind = 'rotary_table'",
        f"kind = 'rotary_table'\nwidth_mm = {fact(20, 'illustrative')}",
    )
    finding = coordinates_row(plan, stock_bbox=SWING)
    consumed = field == "max_work" or by == "pin"
    if status == "measured" or not consumed:
        assert_same_pass(finding, baseline)
    else:
        assert finding.status == "unknown", finding.sentence
        assert ids(finding) == {f"fixtures.table.{field}"}
        (table,) = arcs(finding, 20)
        assert table["rotary"]["rotation"] == "unknown"


def test_rotation_and_rotary_dimensions_survive_the_final_measurement_merge(tmp_path):
    plan = rotary_plan(tmp_path)
    inventory = plan.with_name("inventory.toml")
    change(inventory, "rotation = 'cw'", f"rotation = {fact('cw', 'illustrative')}")
    for field, value in (("max_work", 150.0), ("bore_dia", 6.0)):
        change(inventory, f"{field}_mm = {value}", f"{field}_mm = {fact(value, 'assumed')}")
    finding = coordinates_row(plan, stock_bbox=SWING)
    assert finding.status == "unknown", finding.sentence
    assert ids(finding) == {
        "machines.mill.spindle.rotation",
        "fixtures.table.max_work",
        "fixtures.table.bore_dia",
    }


def zero_plan(tmp_path, tool_facts, *, lathe=False, gauge=False):
    plan = scratch(
        tmp_path,
        "[[setups.ops]]\nop = 10\ndo = 'inspect'\nfeature = 'target'\n"
        "checks = { dia = 'unknown' }\n",
    )
    change(
        plan,
        "[[setups]]",
        "[dro]\ncontroller = 'el400'\nmode = 'abs'\nradius_mode = false\n"
        "direction = { x = 'away_from_spindle_axis', y = 'away', z = 'toward_exposed_end' }\n"
        "[[setups]]",
    )
    category, name, kind = (
        ("gauges", "pin", "gauge_pin") if gauge else ("tools", "finder", "edge_finder")
    )
    reference = f"{category}.{name}"
    recipe = "\n[setups.zero]\ntool_touches = []\n[setups.zero.x]\n"
    recipe += (
        "edge_mm = 0.0\nfrom = '+x'\nmethod = 'indicated_touch'\n"
        if lathe
        else "edge_mm = 0.0\nfrom = '-x'\n"
    )
    recipe += f"tool = '{reference}'\ncheck_jog_mm = 5.0\n"
    if not lathe:
        recipe += (
            "[setups.zero.y]\nedge_mm = 0.0\nfrom = '-y'\n"
            f"tool = '{reference}'\ncheck_jog_mm = 5.0\n"
        )
    recipe += (
        "[setups.zero.z]\nface = 'top'\nedge_mm = 0.0\nfrom = '+z'\n"
        f"tool = '{reference}'\nmethod = 'touch'\npaper_mm = 0.0\n"
        "check_jog_mm = 5.0\nretouch_after = []\n"
    )
    plan.write_text(plan.read_text(encoding="utf-8") + recipe, encoding="utf-8")
    inventory = plan.with_name("inventory.toml")
    if lathe:
        change(inventory, "kind = 'mill'", "kind = 'lathe'")
    inventory.write_text(
        inventory.read_text(encoding="utf-8")
        + f"\n[{category}.{name}]\nkind = '{kind}'\nverify = false\n"
        + ("finder_type = 'electronic'\n" if not gauge else "")
        + tool_facts,
        encoding="utf-8",
    )
    return plan


def zero_row(plan):
    return zero_recipe_rule.evaluate(load_bundle(plan))[0]


def test_explicit_unknown_tip_does_not_fall_back_to_the_finders_body_diameter(tmp_path):
    plan = zero_plan(tmp_path, "tip_in = 'unknown'\ndia_mm = 6.0\n")
    finding = zero_row(plan)
    assert finding.status == "unknown", finding.sentence
    assert ids(finding) == {"tools.finder.tip"}
    for axis in ("x", "y"):
        row = finding.numbers["axes"][axis]
        assert row["radius_mm"] == row["axis_set"] == "unknown"
        assert row["finder"]["tip_dia_mm"] == "unknown"
        assert row["finder"]["status"] == "unknown"


@pytest.mark.parametrize("status", STATUSES)
@pytest.mark.parametrize("lathe,gauge", [(False, False), (True, True)])
def test_absent_tip_uses_only_a_trusted_selected_diameter_and_names_its_debt(
    tmp_path, lathe, gauge, status
):
    plan = zero_plan(tmp_path, "dia_mm = 6.0\n", lathe=lathe, gauge=gauge)
    baseline = zero_row(plan)
    prefix = "kind = 'gauge_pin'\nverify = false\n" if gauge else "finder_type = 'electronic'\n"
    change(
        plan.with_name("inventory.toml"),
        prefix + "dia_mm = 6.0\n",
        prefix + f"dia_mm = {fact(6, status)}\n",
    )
    finding = zero_row(plan)
    if status == "measured":
        assert_same_pass(finding, baseline)
    else:
        assert finding.status == "unknown", finding.sentence
        expected = "gauges.pin.dia" if gauge else "tools.finder.dia"
        assert ids(finding) == {expected}
        assert finding.numbers["axes"]["x"]["radius_mm"] == "unknown"
        assert finding.numbers["axes"]["x"]["axis_set"] == "unknown"
        if not gauge:
            assert finding.numbers["axes"]["x"]["finder"]["status"] == "unknown"


def test_nominal_tip_does_not_inherit_an_unconsumed_body_diameter_debt(tmp_path):
    plan = zero_plan(tmp_path, "tip_in = 0.2\ndia_mm = 6.0\n")
    baseline = zero_row(plan)
    change(
        plan.with_name("inventory.toml"),
        "tip_in = 0.2\ndia_mm = 6.0\n",
        f"tip_in = 0.2\ndia_mm = {fact(6, 'illustrative')}\n",
    )
    finding = zero_row(plan)
    assert_same_pass(finding, baseline)
    assert finding.numbers["axes"]["x"]["radius_mm"] == pytest.approx(2.54)


def endpoint_plan(tmp_path, through, *, action="ream", lathe=False):
    target = (
        "kind = 'hole'\nrequirements = ['depth']\nat = [20.0, 10.0, 0.0]\n"
        f"dia = [6.0, 6.03]\nthru = {str(through).lower()}\ndepth = [4.0, 6.0]\n"
    )
    tool = "reamer" if action == "ream" else "bore-drill"
    plan = scratch(tmp_path, op(10, action, tool=tool, depth_mm=4.0, exit_mm=0.5), target=target)
    inventory = plan.with_name("inventory.toml")
    if lathe:
        change(inventory, "kind = 'mill'", "kind = 'lathe'")
    if action == "ream":
        inventory.write_text(
            inventory.read_text(encoding="utf-8")
            + "\n[tools.reamer]\nkind = 'reamer'\nverify = false\ndia_mm = 6.0\nlead_mm = 0.3\n",
            encoding="utf-8",
        )
    return plan


@pytest.mark.parametrize("status", STATUSES)
@pytest.mark.parametrize("through", [False, True])
def test_blind_and_through_reamer_endpoints_name_the_selected_lead_record(
    tmp_path, through, status
):
    plan = endpoint_plan(tmp_path, through)
    inventory = plan.with_name("inventory.toml")
    baseline = next(
        row for row in tip_endpoints.evaluate(load_bundle(plan)) if row.subject == "target"
    )
    change(inventory, "lead_mm = 0.3", f"lead_mm = {fact(0.3, status)}")
    # Body length is recorded but is not an input to this endpoint.
    change(inventory, "kind = 'reamer'", f"kind = 'reamer'\noal_mm = {fact(80, 'illustrative')}")
    finding = next(
        row for row in tip_endpoints.evaluate(load_bundle(plan)) if row.subject == "target"
    )
    if status == "measured":
        assert_same_pass(finding, baseline)
    else:
        assert finding.status == "unknown", finding.sentence
        assert ids(finding) == {"tools.reamer.lead"}
        (endpoint,) = finding.numbers["endpoints"]
        assert endpoint["lead_mm"] == endpoint["tip_z"] == endpoint["dro_tip_z"] == "unknown"


@pytest.mark.parametrize("status", [*STATUSES, "verify"])
@pytest.mark.parametrize("through", [False, True])
def test_lathe_drill_endpoint_names_the_diameter_consumed_by_its_point(tmp_path, through, status):
    plan = endpoint_plan(tmp_path, through, action="drill", lathe=True)
    baseline = next(
        row for row in tip_endpoints.evaluate(load_bundle(plan)) if row.subject == "target"
    )
    diameter = "{ value = 6.0, verify = true }" if status == "verify" else fact(6, status)
    change(
        plan.with_name("inventory.toml"),
        "[tools.bore-drill]\nkind = 'drill'\ndia_mm = 6.0\n",
        f"[tools.bore-drill]\nkind = 'drill'\ndia_mm = {diameter}\n",
    )
    finding = next(
        row for row in tip_endpoints.evaluate(load_bundle(plan)) if row.subject == "target"
    )
    if status == "measured":
        assert_same_pass(finding, baseline)
    else:
        assert finding.status == "unknown", finding.sentence
        assert ids(finding) == {"tools.bore-drill.dia"}
        (endpoint,) = finding.numbers["endpoints"]
        assert endpoint["point_mm"] == endpoint["tip_z"] == "unknown"


@pytest.mark.parametrize("status", [*STATUSES, "verify"])
def test_lathe_coordinate_offset_names_the_diameter_it_consumes(tmp_path, status):
    plan = scratch(
        tmp_path,
        op(20, "finish_profile", "{ method = 'linear_table' }"),
        target=(
            "kind = 'plane'\nrequirements = []\n"
            "bounds = { x = [0.0, 20.0], y = [0.0, 10.0], z = [-1.0, 0.0] }\n"
        ),
    )
    change(
        plan,
        "[[setups]]",
        "[dro]\ncontroller = 'el400'\nmode = 'abs'\nradius_mode = false\n[[setups]]",
    )
    inventory = plan.with_name("inventory.toml")
    change(inventory, "kind = 'mill'", "kind = 'lathe'")
    change(inventory, "kind = 'endmill'", "kind = 'endmill'\nnose_radius_mm = 0.4")
    baseline = coordinates_row(plan)
    diameter = "{ value = 6.0, verify = true }" if status == "verify" else fact(6, status)
    change(
        inventory,
        "center_cutting = true\ndia_mm = 6.0\n",
        f"center_cutting = true\ndia_mm = {diameter}\n",
    )
    finding = coordinates_row(plan)
    if status == "measured":
        assert_same_pass(finding, baseline)
    else:
        assert finding.status == "unknown", finding.sentence
        assert ids(finding) == {"tools.cutter.dia"}
        (profile,) = finding.numbers["profiles"]
        assert profile["cutter_centre"] == "unknown"


@pytest.mark.parametrize("consumer", ["stairs", "rotary_table", "no-direction", "chain_drill"])
def test_declared_cut_order_debt_survives_a_blocked_cutter_in_row_and_host_cli(tmp_path, consumer):
    if consumer == "rotary_table":
        plan = rotary_plan(tmp_path)
    else:
        contour = (
            "{ method = 'chain_drill', pitch_mm = 5.0 }"
            if consumer == "chain_drill"
            else "{ method = 'stairs', cusp_mm = 0.25 }"
        )
        plan = scratch(
            tmp_path,
            op(
                20,
                "rough_profile",
                contour,
                tool="drill" if consumer == "chain_drill" else "cutter",
                allowance=0.2,
            ),
        )
    if consumer == "no-direction":
        change(plan, "direction = 'conventional'\n", "")
    inventory = plan.with_name("inventory.toml")
    change(inventory, "rotation = 'cw'", f"rotation = {fact('cw', 'assumed')}")
    if consumer == "chain_drill":
        change(inventory, "dia_mm = 3.0\n", f"dia_mm = {fact(3, 'assumed')}\n")
        diameter_id = "tools.drill.dia"
    else:
        change(
            inventory,
            "center_cutting = true\ndia_mm = 6.0\n",
            f"center_cutting = true\ndia_mm = {fact(6, 'assumed')}\n",
        )
        diameter_id = "tools.cutter.dia"
    rotation_id = "machines.mill.spindle.rotation"
    expected = {diameter_id}
    if consumer in {"stairs", "rotary_table"}:
        expected.add(rotation_id)
    finding = coordinates_row(plan, stock_bbox=SWING)
    assert finding.status == "unknown", finding.sentence
    assert ids(finding) == expected
    assert finding.numbers["arc_table"] == finding.numbers["line_table"] == []
    assert finding.numbers["profiles"][-1]["cutter_centre"] == "unknown"
    cache = tmp_path / "uncreated-kernel-cache"
    result = run_cli(
        "tools",
        "--measure",
        "--json",
        "--plan",
        plan,
        env={
            "FREECAD_CMD": str(tmp_path / "nonexistent-freecadcmd"),
            "PRECHIPS_KERNEL_CACHE": str(cache),
        },
    )
    assert result.returncode == 0, result.stderr
    entries = json.loads(result.stdout)
    checklist_ids = {entry["id"] for entry in entries}
    assert expected <= checklist_ids
    assert (rotation_id in checklist_ids) is (rotation_id in expected)
    assert not cache.exists()
