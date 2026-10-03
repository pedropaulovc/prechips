"""M2 proxies on isolated synthetic bundles, not guessed shop cutting data."""

import copy
import math
from types import SimpleNamespace

import pytest
from test_cli import run_cli

from prechips.findings import exit_code
from prechips.report import canonical_bytes
from prechips.rules import engagement, tool_resolves, turning_deflection

ROW_CITE = "scratch force fixture: synthetic K_c/E, not a material recommendation"
DIA_CITE = "scratch drawing fixture: diameter acceptance band"


def turning_bundle():
    return SimpleNamespace(
        plan={
            "stock": {"material": "scratch alloy", "material_verify": False},
            "setups": [
                {
                    "id": "S1",
                    "machine": "lathe",
                    "hold": {"stickout_mm": 100, "support": "none"},
                    "ops": [
                        {
                            "op": 10,
                            "do": "finish_turn",
                            "feature": "journal",
                            "tool": "cutter",
                            "holder": "holder",
                            "doc_mm": 1,
                            "feed_mm_rev": 0.1,
                        }
                    ],
                }
            ],
        },
        features={
            "units": "mm",
            "features": {
                "journal": {
                    "kind": "cylinder",
                    "dia_nominal": 10,
                    "dia": [9.9, 10.1],
                    "requirements": ["dia"],
                    "cite": {"dia": DIA_CITE},
                }
            },
        },
        inventory={
            "machines": {"lathe": {"kind": "lathe", "verify": False}},
            "fixtures": {},
            "tools": {"cutter": {"kind": "turning_tool"}},
            "holders": {"holder": {"kind": "toolholder"}},
        },
        cutting_data={
            "aliases": {"scratch alloy": "scratch_class"},
            "material": [
                {
                    "material_class": "scratch_class",
                    "kc_n_per_mm2": 1000,
                    "e_gpa": 200,
                    "cite": ROW_CITE,
                }
            ],
        },
        policy={"required": {}},
    )


def milling_bundle():
    data = turning_bundle()
    setup = data.plan["setups"][0]
    setup["machine"] = "mill"
    setup["ops"][0].update(do="finish_profile", doc_mm=2)
    data.inventory["machines"] = {"mill": {"kind": "mill"}}
    data.inventory["tools"]["cutter"] = {
        "kind": "endmill",
        "dia_mm": 10,
        "oal_mm": 75,
        "projection_mm": {"holder": 40},
    }
    data.inventory["holders"]["holder"] = {"kind": "collet", "grip_mm": 25}
    return data


def test_cantilever_force_inertia_and_gpa_conversion():
    finding = turning_deflection.evaluate(turning_bundle())[0]
    values = finding.numbers
    inertia = math.pi * 10**4 / 64
    assert values["force_n"] == pytest.approx(100)
    assert values["inertia_mm4"] == pytest.approx(inertia)
    assert values["e_n_per_mm2"] == 200_000
    assert values["denominator_coefficient"] == 3
    assert values["deflection_mm"] == pytest.approx(100 * 100**3 / (3 * 200_000 * inertia))
    assert values["diameter_tolerance_mm"] == pytest.approx(0.1)
    assert finding.status == "warn"
    assert ROW_CITE in finding.cite
    assert DIA_CITE in finding.cite


@pytest.mark.parametrize("kind", ["tailstock_centre", "steady_rest"])
def test_selected_verified_support_uses_supported_denominator(kind):
    data = turning_bundle()
    unsupported = turning_deflection.evaluate(data)[0]
    data.inventory["fixtures"]["support"] = {"kind": kind, "verify": False}
    data.plan["setups"][0]["hold"]["support"] = "support"
    supported = turning_deflection.evaluate(data)[0]
    assert supported.numbers["denominator_coefficient"] == 48
    assert supported.numbers["deflection_mm"] == pytest.approx(
        unsupported.numbers["deflection_mm"] / 16
    )
    assert supported.status == "pass"


def test_selected_machine_accessory_support_resolves_but_inventory_presence_is_not_selection():
    data = turning_bundle()
    machine = data.inventory["machines"]["lathe"]
    machine["standard_accessories"] = ["dead_centre_tailstock_mt3"]
    assert turning_deflection.evaluate(data)[0].numbers["denominator_coefficient"] == 3
    data.plan["setups"][0]["hold"]["support"] = "dead_centre_tailstock_mt3"
    finding = turning_deflection.evaluate(data)[0]
    assert finding.status == "pass"
    assert finding.numbers["denominator_coefficient"] == 48
    machine["verify"] = True
    finding = turning_deflection.evaluate(data)[0]
    assert finding.status == "unknown"
    assert finding.numbers["deflection_mm"] == "unknown"


def test_support_from_another_machine_cannot_lower_deflection():
    data = turning_bundle()
    data.inventory["machines"]["other"] = {
        "kind": "lathe",
        "standard_accessories": ["dead_centre_tailstock_mt3"],
    }
    data.plan["setups"][0]["hold"]["support"] = "dead_centre_tailstock_mt3"
    finding = turning_deflection.evaluate(data)[0]
    assert finding.status == "unknown"
    assert finding.numbers["denominator_coefficient"] == "unknown"


def test_explicit_inch_feature_nominal_and_band_convert_to_mm():
    data = turning_bundle()
    data.features["units"] = "in"
    data.features["features"]["journal"].update(dia_nominal=0.25, dia=[0.24, 0.26])
    values = turning_deflection.evaluate(data)[0].numbers
    assert values["diameter_mm"] == pytest.approx(6.35)
    assert values["dia_band_mm"] == pytest.approx([6.096, 6.604])
    assert values["diameter_tolerance_mm"] == pytest.approx(0.254)
    inertia = math.pi * 6.35**4 / 64
    assert values["deflection_mm"] == pytest.approx(100 * 100**3 / (3 * 200_000 * inertia))


def test_tolerance_boundary_is_inclusive_and_narrower_band_warns():
    data = turning_bundle()
    data.plan["setups"][0]["hold"]["stickout_mm"] = 1
    op = data.plan["setups"][0]["ops"][0]
    row = data.cutting_data["material"][0]
    row["kc_n_per_mm2"] = 1
    op["feed_mm_rev"] = 1
    op["doc_mm"] = 2 * 3 * 200_000 * (math.pi * 10**4 / 64)
    data.features["features"]["journal"]["dia"] = [8, 12]
    finding = turning_deflection.evaluate(data)[0]
    assert finding.numbers["deflection_mm"] == 2
    assert finding.status == "pass"
    data.features["features"]["journal"]["dia"] = [9, 11]
    assert turning_deflection.evaluate(data)[0].status == "warn"


@pytest.mark.parametrize("field", ["doc_mm", "feed_mm_rev"])
@pytest.mark.parametrize("value", ["unknown", 0, -1])
def test_unknown_or_nonpositive_cut_values_do_not_guess_force(field, value):
    data = turning_bundle()
    data.plan["setups"][0]["ops"][0][field] = value
    finding = turning_deflection.evaluate(data)[0]
    assert finding.status == "unknown"
    assert finding.numbers["force_n"] == "unknown"
    assert finding.numbers["deflection_mm"] == "unknown"


@pytest.mark.parametrize("field", ["kc_n_per_mm2", "e_gpa"])
@pytest.mark.parametrize("value", ["unknown", 0])
def test_material_coefficients_are_never_invented(field, value):
    data = turning_bundle()
    data.cutting_data["material"][0][field] = value
    finding = turning_deflection.evaluate(data)[0]
    assert finding.status == "unknown"
    assert finding.numbers["deflection_mm"] == "unknown"


@pytest.mark.parametrize("problem", ["missing", "duplicate", "uncited", "unmapped", "verify"])
def test_material_resolution_requires_one_cited_verified_row(problem):
    data = turning_bundle()
    if problem == "missing":
        data.cutting_data["material"] = "unknown"
    elif problem == "duplicate":
        data.cutting_data["material"] *= 2
    elif problem == "uncited":
        data.cutting_data["material"][0]["cite"] = "unknown"
    elif problem == "unmapped":
        data.cutting_data["aliases"] = "unknown"
    else:
        data.plan["stock"]["material_verify"] = True
    finding = turning_deflection.evaluate(data)[0]
    assert finding.status == "unknown"
    assert finding.numbers["deflection_mm"] == "unknown"


@pytest.mark.parametrize("problem", ["missing_band", "uncited", "unrelated_cite"])
def test_computed_deflection_without_sourced_acceptance_stays_unknown(problem):
    data = turning_bundle()
    feature = data.features["features"]["journal"]
    if problem == "missing_band":
        feature["dia"] = "unknown"
    elif problem == "uncited":
        feature["cite"] = "unknown"
    else:
        feature["cite"] = {"length": "scratch unrelated length source"}
    finding = turning_deflection.evaluate(data)[0]
    assert finding.status == "unknown"
    assert finding.numbers["deflection_mm"] == pytest.approx(0.33953054526271004)
    assert finding.numbers["diameter_tolerance_mm"] == "unknown"
    assert "acceptance threshold" in finding.sentence


@pytest.mark.parametrize("problem", ["band_only", "unknown_nominal", "units", "hold", "support"])
def test_geometry_and_support_unknowns_are_not_inferred(problem):
    data = turning_bundle()
    feature = data.features["features"]["journal"]
    setup = data.plan["setups"][0]
    if problem == "band_only":
        del feature["dia_nominal"]
    elif problem == "unknown_nominal":
        feature.update(dia_nominal="unknown", nominal_dia=10)
    elif problem == "units":
        data.features["units"] = "unknown"
    elif problem == "hold":
        setup["hold"] = "unknown"
    else:
        del setup["hold"]["support"]
    finding = turning_deflection.evaluate(data)[0]
    assert finding.status == "unknown"
    assert finding.numbers["deflection_mm"] == "unknown"


@pytest.mark.parametrize("kind,action", [("drill", "drill"), ("reamer", "ream"), ("tap", "tap")])
@pytest.mark.parametrize("doc", [None, 1])
def test_engagement_scope_excludes_hole_tools_with_or_without_doc(kind, action, doc):
    data = milling_bundle()
    op = data.plan["setups"][0]["ops"][0]
    op["do"] = action
    if doc is None:
        del op["doc_mm"]
    else:
        op["doc_mm"] = doc
    data.inventory["tools"]["cutter"] = {"kind": kind, "dia_mm": 6.35, "oal_mm": 101}
    finding = engagement.evaluate(data)[0]
    assert finding.status == "not_applicable"
    assert exit_code([finding], {"required": {"engagement": "*"}}, data) == 0


@pytest.mark.parametrize("action", ["face", "rough_turn", "finish_turn"])
def test_engagement_scope_excludes_lathe_turning_tools_without_cutter_diameter(action):
    data = turning_bundle()
    data.plan["setups"][0]["ops"][0]["do"] = action
    finding = engagement.evaluate(data)[0]
    assert finding.status == "not_applicable"
    assert exit_code([finding], {"required": {"engagement": "*"}}, data) == 0


@pytest.mark.parametrize("kind", ["boring_bar", "boring_head", "insert_holders", "face_mill"])
def test_engagement_scope_excludes_known_non_endmill_families_even_with_doc(kind):
    data = milling_bundle()
    data.inventory["tools"]["cutter"].update(kind=kind, projection_mm={"holder": 50})
    if kind == "insert_holders":
        data.inventory["tools"]["cutter"]["members"] = {"AR": {}}
        data.plan["setups"][0]["ops"][0]["tool"] = "cutter/AR"
    assert engagement.evaluate(data)[0].status == "not_applicable"


@pytest.mark.parametrize("action", ["fit_up", "transfer"])
def test_engagement_scope_excludes_noncutting_operations_even_with_endmill_and_doc(action):
    data = milling_bundle()
    data.plan["setups"][0]["ops"][0]["do"] = action
    data.inventory["tools"]["cutter"]["projection_mm"]["holder"] = 50
    assert engagement.evaluate(data)[0].status == "not_applicable"


@pytest.mark.parametrize("projection", [40, 50])
def test_engagement_scope_omitted_doc_is_not_applicable_even_with_endmill(projection):
    data = milling_bundle()
    del data.plan["setups"][0]["ops"][0]["doc_mm"]
    data.inventory["tools"]["cutter"]["projection_mm"]["holder"] = projection
    finding = engagement.evaluate(data)[0]
    assert finding.status == "not_applicable"
    assert exit_code([finding], {"required": {"engagement": "*"}}, data) == 0


@pytest.mark.parametrize("projection", [40, 50])
@pytest.mark.parametrize("doc", ["unknown", 0, -1])
def test_engagement_scope_authored_unknown_or_nonpositive_doc_cannot_pass(projection, doc):
    data = milling_bundle()
    data.plan["setups"][0]["ops"][0]["doc_mm"] = doc
    data.inventory["tools"]["cutter"]["projection_mm"]["holder"] = projection
    finding = engagement.evaluate(data)[0]
    assert finding.status == "unknown"
    assert finding.numbers["projection_ld"] == projection / 10
    assert finding.numbers["recommended_doc_mm"] == "unknown"
    assert exit_code([finding], {"required": {"engagement": "*"}}, data) == 4


@pytest.mark.parametrize(
    "identity",
    ["unresolved_ref", "unknown_record", "unknown_inventory", "omitted_kind", "unknown_kind"],
)
def test_engagement_scope_unknown_tool_identity_cannot_certify_exclusion(identity):
    data = milling_bundle()
    if identity == "unresolved_ref":
        data.plan["setups"][0]["ops"][0]["tool"] = "not_in_inventory"
    elif identity == "unknown_record":
        data.inventory["tools"]["cutter"] = "unknown"
    elif identity == "unknown_inventory":
        data.inventory["tools"] = "unknown"
    elif identity == "omitted_kind":
        del data.inventory["tools"]["cutter"]["kind"]
    else:
        data.inventory["tools"]["cutter"]["kind"] = "unknown"
    finding = engagement.evaluate(data)[0]
    assert finding.status == "unknown"
    assert finding.numbers["projection_ld"] == "unknown"
    assert finding.numbers["recommended_doc_mm"] == "unknown"


@pytest.mark.parametrize("action", ["rough_pocket", "counterbore"])
def test_engagement_cutting_endmill_with_doc_remains_eligible(action):
    data = milling_bundle()
    data.plan["setups"][0]["ops"][0]["do"] = action
    data.inventory["tools"]["cutter"]["projection_mm"]["holder"] = 50
    finding = engagement.evaluate(data)[0]
    assert finding.status == "warn"
    assert finding.numbers["projection_ld"] == 5
    assert finding.numbers["recommended_doc_mm"] == 1


@pytest.mark.parametrize(
    "kind,status", [("endmill", "warn"), ("drill", "not_applicable"), ("unknown", "unknown")]
)
def test_engagement_scope_resolved_set_member_kind_controls_applicability(kind, status):
    data = milling_bundle()
    data.inventory["tools"] = {
        "mills": {
            "kind": "endmill_set",
            "members": {
                "selected": {"kind": kind, "dia_in": 0.5, "projection_in": {"holder": 2.5}},
            },
        }
    }
    data.plan["setups"][0]["ops"][0]["tool"] = "mills/selected"
    finding = engagement.evaluate(data)[0]
    assert finding.status == status
    if status == "warn":
        assert finding.numbers["projection_ld"] == 5
        assert finding.numbers["recommended_doc_mm"] == 1
    elif status == "unknown":
        assert finding.numbers["recommended_doc_mm"] == "unknown"


def test_engagement_four_diameter_boundary_and_doc_halving():
    data = milling_bundle()
    at_limit = engagement.evaluate(data)[0]
    assert at_limit.status == "pass"
    assert at_limit.numbers["projection_ld"] == 4
    assert at_limit.numbers["recommended_doc_mm"] == 2
    data.inventory["tools"]["cutter"]["projection_mm"]["holder"] = 40.01
    over_limit = engagement.evaluate(data)[0]
    assert over_limit.status == "warn"
    assert over_limit.numbers["doc_scale"] == 0.5
    assert over_limit.numbers["recommended_doc_mm"] == 1
    assert data.plan["setups"][0]["ops"][0]["doc_mm"] == 2


def test_explicit_projection_takes_precedence_over_oal_minus_grip():
    data = milling_bundle()
    data.inventory["tools"]["cutter"]["projection_mm"]["holder"] = 35
    explicit = engagement.evaluate(data)[0]
    assert explicit.status == "pass"
    assert explicit.numbers["projection_mm"] == 35
    del data.inventory["tools"]["cutter"]["projection_mm"]
    fallback = engagement.evaluate(data)[0]
    assert fallback.status == "warn"
    assert fallback.numbers["projection_mm"] == 50
    assert fallback.numbers["recommended_doc_mm"] == 1


@pytest.mark.parametrize("field", ["projection_mm", "projection_in"])
def test_explicit_unknown_projection_never_falls_back_to_oal_minus_grip(field):
    data = milling_bundle()
    tool = data.inventory["tools"]["cutter"]
    del tool["projection_mm"]
    tool["oal_mm"] = 65
    omitted = engagement.evaluate(data)[0]
    assert omitted.status == "pass"
    assert omitted.numbers["projection_mm"] == 40
    tool[field] = {"holder": "unknown"}
    declared_unknown = engagement.evaluate(data)[0]
    assert declared_unknown.status == "unknown"
    assert declared_unknown.numbers["projection_mm"] == "unknown"
    assert declared_unknown.numbers["projection_ld"] == "unknown"
    assert declared_unknown.numbers["recommended_doc_mm"] == "unknown"


def test_inventory_generic_inch_units_and_projection_fallback_convert_once():
    data = milling_bundle()
    data.inventory["tools"]["cutter"] = {
        "kind": "endmill",
        "dia": 0.5,
        "oal": 3,
        "units": "in",
    }
    data.inventory["holders"]["holder"]["grip_mm"] = 25.4
    finding = engagement.evaluate(data)[0]
    assert finding.status == "pass"
    assert finding.numbers["diameter_mm"] == 12.7
    assert finding.numbers["projection_mm"] == pytest.approx(50.8)
    assert finding.numbers["projection_ld"] == pytest.approx(4)


def test_exact_inch_boundary_is_not_a_warning_from_conversion_residue():
    data = milling_bundle()
    data.inventory["tools"]["cutter"] = {
        "kind": "endmill",
        "dia_in": 0.375,
        "projection_mm": {"holder": 38.1},
    }
    finding = engagement.evaluate(data)[0]
    assert finding.numbers["projection_ld"] > 4
    assert finding.status == "pass"
    assert finding.numbers["over_limit"] is False
    assert finding.numbers["recommended_doc_mm"] == 2


def test_declared_set_member_projection_and_diameter_resolve():
    data = milling_bundle()
    data.inventory["tools"] = {
        "mills": {
            "kind": "endmill_set",
            "sizes_in": ["1/2"],
            "flutes": [2],
            "members": {"1-2in-2fl": {"dia_in": 0.5, "projection_in": {"holder": 2}}},
        }
    }
    data.plan["setups"][0]["ops"][0]["tool"] = "mills/1-2in-2fl"
    finding = engagement.evaluate(data)[0]
    assert finding.status == "pass"
    assert finding.numbers["projection_ld"] == 4
    data.inventory["tools"]["mills"]["members"]["1-2in-2fl"]["projection_in"]["holder"] = 2.5
    over_limit = engagement.evaluate(data)[0]
    assert over_limit.status == "warn"
    assert over_limit.numbers["projection_ld"] == 5
    assert over_limit.numbers["recommended_doc_mm"] == 1
    data.inventory["tools"]["mills"]["verify"] = True
    assert engagement.evaluate(data)[0].status == "unknown"


@pytest.mark.parametrize("problem", ["tool", "holder", "dia", "units", "projection", "verify"])
def test_engagement_missing_or_unverified_assembly_stays_unknown(problem):
    data = milling_bundle()
    tool = data.inventory["tools"]["cutter"]
    if problem == "tool":
        data.inventory["tools"] = {}
    elif problem == "holder":
        data.inventory["holders"] = "unknown"
    elif problem == "dia":
        tool["dia_mm"] = "unknown"
    elif problem == "units":
        del tool["dia_mm"]
        tool["dia"] = 10
    elif problem == "projection":
        del tool["projection_mm"]
        data.inventory["holders"]["holder"]["grip_mm"] = "unknown"
    else:
        data.inventory["holders"]["holder"]["verify"] = True
    finding = engagement.evaluate(data)[0]
    assert finding.status == "unknown"
    assert finding.numbers["projection_ld"] == "unknown"
    assert finding.numbers["recommended_doc_mm"] == "unknown"


def test_engagement_long_projection_with_authored_unknown_doc_does_not_guess_depth():
    data = milling_bundle()
    data.inventory["tools"]["cutter"]["projection_mm"]["holder"] = 50
    data.plan["setups"][0]["ops"][0]["doc_mm"] = "unknown"
    finding = engagement.evaluate(data)[0]
    assert finding.status == "unknown"
    assert finding.numbers["projection_ld"] == 5
    assert finding.numbers["recommended_doc_mm"] == "unknown"


@pytest.mark.parametrize("evaluate", [turning_deflection.evaluate, engagement.evaluate])
def test_manual_operation_is_not_a_cutting_proxy(evaluate):
    data = milling_bundle() if evaluate is engagement.evaluate else turning_bundle()
    data.plan["setups"][0]["ops"][0]["do"] = "inspect"
    assert evaluate(data)[0].status == "not_applicable"
    data.plan["setups"][0]["ops"][0]["do"] = "unknown"
    assert evaluate(data)[0].status == "unknown"


@pytest.mark.parametrize(
    "factory,evaluate",
    [
        (turning_bundle, turning_deflection.evaluate),
        (milling_bundle, engagement.evaluate),
    ],
)
def test_proxies_are_deterministic_and_leave_authored_inputs_unchanged(factory, evaluate):
    data = factory()
    before = copy.deepcopy(vars(data))
    first = canonical_bytes({"findings": [row.to_dict() for row in evaluate(data)]})
    second = canonical_bytes({"findings": [row.to_dict() for row in evaluate(data)]})
    assert second == first
    assert vars(data) == before


@pytest.mark.parametrize(
    "factory,evaluate,rule",
    [
        (turning_bundle, turning_deflection.evaluate, "turning_deflection"),
        (milling_bundle, engagement.evaluate, "engagement"),
    ],
)
def test_proxy_warning_uses_existing_required_gate_not_hard_error(factory, evaluate, rule):
    data = factory()
    if rule == "engagement":
        data.inventory["tools"]["cutter"]["projection_mm"]["holder"] = 50
    findings = evaluate(data)
    assert findings[0].status == "warn"
    assert exit_code(findings, {"required": {}}, data) == 0
    required = {"required": {rule: "*"}}
    assert exit_code(findings, required, data) == 4
    del data.inventory["tools"]["cutter"]
    assert exit_code(findings + tool_resolves.evaluate(data), required, data) == 2


def test_unknown_and_clean_physics_follow_the_same_required_gate():
    data = turning_bundle()
    required = {"required": {"turning_deflection": "*"}}
    data.plan["setups"][0]["ops"][0]["doc_mm"] = "unknown"
    unknown = turning_deflection.evaluate(data)
    assert exit_code(unknown, required, data) == 4
    assert exit_code(unknown, {"required": {}}, data) == 0
    data.plan["setups"][0]["ops"][0]["doc_mm"] = 0.1
    clean = turning_deflection.evaluate(data)
    assert clean[0].status == "pass"
    assert exit_code(clean, required, data) == 0


def test_malformed_cut_input_exits_three_before_rules_or_output(tmp_path):
    files = {
        "plan.toml": """part = "scratch"
features = "features.toml"
[paths]
inventory = "inventory.toml"
policy = "policy.toml"
cutting_data = "cutting.toml"
[[setups]]
id = "S1"
machine = "lathe"
[setups.hold]
support = "none"
stickout_mm = 100
[[setups.ops]]
op = 10
do = "finish_turn"
feature = "journal"
doc_mm = "not-a-number"
feed_mm_rev = 0.1
""",
        "features.toml": """part = "scratch"
units = "mm"
frames = "unknown"
[features.journal]
kind = "cylinder"
dia_nominal = 10
requirements = []
""",
        "inventory.toml": '[machines.lathe]\nkind = "lathe"\n',
        "policy.toml": '[required]\nturning_deflection = "*"\n',
        "cutting.toml": "revision = 1\n",
    }
    for name, content in files.items():
        (tmp_path / name).write_text(content, encoding="utf-8")
    out = tmp_path / "out"
    result = run_cli("check", tmp_path / "plan.toml", "--out", out)
    assert result.returncode == 3, result.stderr
    assert "doc_mm" in result.stderr
    assert not out.exists() or not tuple(out.iterdir())


def test_review_2_engagement_selects_projection_for_exact_holder():
    data = milling_bundle()
    data.inventory["tools"]["cutter"]["projection_mm"] = {"holder": 35, "other": 60}
    data.inventory["holders"]["other"] = {"kind": "collet", "grip_mm": 25}
    op = data.plan["setups"][0]["ops"][0]
    selected = engagement.evaluate(data)[0]
    assert selected.status == "pass"
    assert selected.numbers["projection_mm"] == 35
    op["holder"] = "other"
    selected = engagement.evaluate(data)[0]
    assert selected.status == "warn"
    assert selected.numbers["projection_ld"] == 6
    assert selected.numbers["recommended_doc_mm"] == 1
