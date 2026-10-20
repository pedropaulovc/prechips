"""Typed part relationships and shared inspection declarations fail closed at loading."""

import copy

import pytest
from pydantic import ValidationError
from test_batch_material_routes import (
    FEATURES as SOURCE_FEATURES,
)
from test_batch_material_routes import (
    REGISTERED,
    batch,
)
from test_input_contracts import PLAN, bundle_files
from test_material_routes import STEP

from prechips.inputs import BadInput, _inspection_scopes, _inspection_tables, load_bundle
from prechips.model import Features, InspectionScope, ManualAcceptance, Plan

CONTRACT = {
    "kind": "manual",
    "gauge_kind": "mating_part",
    "accept": [
        "Slides freely by hand without objectionable rocking",
        "Shoulders bear without wedging",
    ],
    "cite": "Authored practical comparator acceptance; not a measured result",
}


def manifest():
    return {
        "part": "scratch",
        "frames": "unknown",
        "features": {
            "base": {"kind": "face", "requirements": ["width"], "width": [22.1, 22.3]},
            "shoulders": {"kind": "face", "requirements": []},
            "end": {"kind": "face", "requirements": ["length"], "length": [25.3, 25.5]},
            "hole": {"kind": "threaded_hole", "requirements": []},
        },
        "acceptance": {
            "actual_slot_fit": {
                "features": ["base", "shoulders", "end"],
                "contract": copy.deepcopy(CONTRACT),
            },
            "stud_retention": {
                "features": ["hole"],
                "contract": {
                    "kind": "manual",
                    "gauge_kind": "mating_hardware",
                    "accept": ["The intended stud enters by hand and cannot exit the bottom"],
                    "cite": "Authored intended-stud check",
                },
            },
        },
    }


def test_manual_relationships_are_additive_and_preserve_authored_contracts():
    original = manifest()
    parsed = Features.model_validate(original).model_dump(exclude_unset=True)
    assert parsed["acceptance"] == original["acceptance"]
    assert parsed["features"] == original["features"]
    assert parsed["features"]["base"]["requirements"] == ["width"]
    assert parsed["features"]["end"]["length"] == [25.3, 25.5]


@pytest.mark.parametrize("contract", [None, "unknown"])
def test_absent_or_explicit_unknown_contract_does_not_erase_size_requirements(contract):
    data = manifest()
    relationship = data["acceptance"]["actual_slot_fit"]
    if contract is None:
        relationship.pop("contract")
    else:
        relationship["contract"] = contract
    parsed = Features.model_validate(data)
    assert parsed.acceptance["actual_slot_fit"].contract == "unknown"
    assert parsed.features["base"].requirements == ["width"]
    assert parsed.features["base"].width == [22.1, 22.3]
    assert ("contract" in parsed.acceptance["actual_slot_fit"].model_fields_set) == (
        contract is not None
    )


def test_unknown_manual_facts_remain_independently_unknown():
    parsed = ManualAcceptance.model_validate({"kind": "manual"})
    assert parsed.gauge_kind == parsed.accept == parsed.cite == "unknown"
    assert parsed.model_dump(exclude_unset=True) == {"kind": "manual"}
    explicit = {"kind": "manual", "gauge_kind": "unknown", "accept": "unknown", "cite": "unknown"}
    assert ManualAcceptance.model_validate(explicit).model_dump(exclude_unset=True) == explicit


@pytest.mark.parametrize(
    "change",
    [
        {"kind": "automatic"},
        {"kind": "unknown"},
        {"gauge_kind": "caliper"},
        {"gauge_kind": None},
        {"accept": []},
        {"accept": "Slides freely"},
        {"accept": [""]},
        {"accept": ["   "]},
        {"accept": ["unknown"]},
        {"accept": [" unknown "]},
        {"accept": [1]},
        {"cite": []},
        {"cite": " "},
        {"cite": ["unknown"]},
        {"unexpected": True},
    ],
)
def test_manual_acceptance_is_strict_without_promoting_malformed_to_unknown(change):
    with pytest.raises(ValidationError):
        ManualAcceptance.model_validate(CONTRACT | change)


def test_manual_kind_is_required_not_inferred_from_clauses():
    data = dict(CONTRACT)
    data.pop("kind")
    with pytest.raises(ValidationError, match="kind"):
        ManualAcceptance.model_validate(data)


@pytest.mark.parametrize("value", ["unknown", [], None])
def test_acceptance_mapping_cannot_hide_existing_requirements(value):
    data = manifest()
    data["acceptance"] = value
    with pytest.raises(ValidationError, match="acceptance"):
        Features.model_validate(data)


@pytest.mark.parametrize("identity", ["base", "width", "base:width", "unknown", " "])
def test_relationship_identity_cannot_collide_with_feature_or_requirement(identity):
    data = manifest()
    data["acceptance"][identity] = data["acceptance"].pop("actual_slot_fit")
    with pytest.raises(ValidationError, match="identity|collides"):
        Features.model_validate(data)


@pytest.mark.parametrize("participants", [[], ["base", "base"], ["missing"], ["unknown"], [" "]])
def test_relationship_participants_are_distinct_existing_features(participants):
    data = manifest()
    data["acceptance"]["actual_slot_fit"]["features"] = participants
    with pytest.raises(ValidationError, match="features|participant"):
        Features.model_validate(data)


def test_acceptance_cannot_replace_an_exported_requirement_value():
    data = manifest()
    data["features"]["base"].pop("width")
    with pytest.raises(ValidationError, match="missing required field width"):
        Features.model_validate(data)


FEATURES = """part = "scratch"
units = "mm"
frames = "unknown"
[features.base]
kind = "face"
requirements = ["width"]
width = [22.1, 22.3]
[features.shoulders]
kind = "face"
requirements = []
[features.end]
kind = "face"
requirements = ["length"]
length = [25.3, 25.5]
[features.hole]
kind = "threaded_hole"
requirements = []
[acceptance.actual_slot_fit]
features = ["base", "shoulders", "end"]
contract = {kind = "manual", gauge_kind = "mating_part", \
accept = ["Slides freely by hand"], cite = "Authored comparator check"}
[acceptance.stud_retention]
features = ["hole"]
contract = {kind = "manual", gauge_kind = "mating_hardware", \
accept = ["Stud enters by hand and stops before exiting"], cite = "Authored stud check"}
"""
CHECKS = 'checks = {end = {length = "calipers"}, actual_slot_fit = "slot", stud_retention = "stud"}'
METHODS = (
    'inspection_methods = {end = {length = "Read between finished ends"}, '
    'actual_slot_fit = "Try the intended slot by hand", stud_retention = "Try the intended stud"}'
)
MANUAL_PLAN = PLAN.replace(
    'feature = "subject"', 'feature = ["base", "shoulders", "end", "hole"]'
).replace('checks = "unknown"', CHECKS + "\n" + METHODS)


def test_loader_binds_flat_part_keys_alongside_scoped_size_check(tmp_path):
    bundle = load_bundle(bundle_files(tmp_path, MANUAL_PLAN, FEATURES))
    op = bundle.plan["setups"][0]["ops"][0]
    assert op["checks"] == {
        "end": {"length": "calipers"},
        "actual_slot_fit": "slot",
        "stud_retention": "stud",
    }
    assert op["inspection_methods"]["end"] == {"length": "Read between finished ends"}
    assert set(bundle.features["acceptance"]) == {"actual_slot_fit", "stud_retention"}
    assert bundle.features["features"]["base"]["requirements"] == ["width"]


@pytest.mark.parametrize(
    "before,after,reason",
    [
        (
            '"base", "shoulders", "end", "hole"',
            '"base", "end", "hole"',
            "every acceptance participant",
        ),
        ('actual_slot_fit = "slot"', 'actual_slot_fit = {width = "slot"}', "flat"),
        (
            'end = {length = "calipers"}',
            'end = {actual_slot_fit = "slot"}',
            "exported requirements",
        ),
        (
            CHECKS,
            CHECKS + '\nmissing_requirements = {actual_slot_fit = "legacy placeholder"}',
            "already exported",
        ),
        ('actual_slot_fit = "slot"', 'unknown_fit = "slot"', "not in the exported requirements"),
        ('do = "inspect"', 'do = "face"', "only an inspect op may name a feature list"),
        (
            METHODS,
            METHODS + "\ngo_no_go = {actual_slot_fit = {go = 1.0, no_go = 2.0}}",
            "GO / NO-GO",
        ),
    ],
)
def test_malformed_manual_bindings_fail_loading(tmp_path, before, after, reason):
    path = bundle_files(tmp_path, MANUAL_PLAN.replace(before, after), FEATURES)
    with pytest.raises(BadInput, match=reason):
        load_bundle(path)


def test_manual_method_is_not_a_feature_scope(tmp_path):
    text = MANUAL_PLAN.replace(
        'actual_slot_fit = "Try the intended slot by hand"',
        'actual_slot_fit = {width = "Try the slot"}',
    )
    with pytest.raises(BadInput, match="flat"):
        load_bundle(bundle_files(tmp_path, text, FEATURES))


def test_numeric_flat_scoped_ambiguity_survives_manual_relationship_support(tmp_path):
    text = MANUAL_PLAN.replace(
        'end = {length = "calipers"}', 'end = {length = "calipers"}, length = "calipers"'
    )
    with pytest.raises(BadInput, match="both for every listed feature"):
        load_bundle(bundle_files(tmp_path, text, FEATURES))


def test_single_feature_relationship_remains_a_flat_part_check():
    data = manifest()
    op = {
        "do": "inspect",
        "feature": "hole",
        "checks": {"stud_retention": "stud"},
        "inspection_methods": {"stud_retention": "Try the intended stud by hand"},
    }
    _inspection_tables("F1:10", op, ["hole"], data["features"], data["acceptance"])
    assert op["checks"] == {"stud_retention": "stud"}


def test_manual_relationship_cannot_aggregate_multiple_workpieces():
    data = manifest()
    op = {
        "do": "inspect",
        "feature": "hole",
        "inspect_workpieces": ["nut1", "nut2"],
        "inspection_scope": "unknown",
        "checks": {"stud_retention": "stud"},
    }
    with pytest.raises(BadInput, match="one workpiece"):
        _inspection_tables("F1:10", op, ["hole"], data["features"], data["acceptance"])


SCOPED_FEATURES = {"features": {"face": {"requirements": ["width"], "width": [22.1, 22.3]}}}


def scoped_batch():
    plan = batch()
    plan["setups"][0]["ops"] = [
        {"op": 20, "do": "face", "feature": "face"},
        {
            "op": 30,
            "do": "inspect",
            "feature": "face",
            "inspect_workpieces": ["nut1", "nut2", "nut3", "nut4"],
            "inspection_scope": {"after": "P0:20", "before": "C1a:10"},
            "checks": {"width": "calipers"},
        },
    ]
    return plan


def bind_scope(plan):
    normalized = Plan.model_validate(plan).model_dump(exclude_unset=True)
    _inspection_scopes(normalized, SCOPED_FEATURES)
    return normalized


def test_shared_scope_binds_one_bar_record_to_all_registered_descendants():
    normalized = bind_scope(scoped_batch())
    op = normalized["setups"][0]["ops"][1]
    assert op["inspect_workpieces"] == ["nut1", "nut2", "nut3", "nut4"]
    assert op["inspection_scope"] == {"after": "P0:20", "before": "C1a:10"}
    assert "workpiece_faces" not in op
    assert op["checks"] == {"width": "calipers"}


@pytest.mark.parametrize(
    "scope",
    [
        "unknown",
        {"after": "unknown", "before": "C1a:10"},
        {"after": "P0:20", "before": "unknown"},
        {"after": "unknown", "before": "unknown"},
    ],
)
def test_explicit_unknown_shared_scope_is_preserved_not_malformed(scope):
    plan = scoped_batch()
    plan["setups"][0]["ops"][1]["inspection_scope"] = scope
    normalized = bind_scope(plan)
    assert normalized["setups"][0]["ops"][1]["inspection_scope"] == scope


@pytest.mark.parametrize("field", ["inspect_workpieces", "inspection_scope"])
@pytest.mark.parametrize("value", ["unknown", "known"])
def test_inspection_selector_fields_are_inspect_only_even_when_unknown(field, value):
    plan = scoped_batch()
    op = plan["setups"][0]["ops"][0]
    if value == "unknown":
        op[field] = "unknown"
    elif field == "inspect_workpieces":
        op[field] = ["nut1"]
    else:
        op[field] = {"after": "P0:20", "before": "C1a:10"}
    with pytest.raises(ValidationError, match="only an inspect op"):
        Plan.model_validate(plan)


@pytest.mark.parametrize("members", [[], ["nut1", "nut1"], ["missing"], ["unknown"], [" "]])
def test_malformed_inspection_targets_do_not_become_unknown(members):
    plan = scoped_batch()
    plan["setups"][0]["ops"][1]["inspect_workpieces"] = members
    with pytest.raises(ValidationError, match="inspect_workpieces|inspected workpiece"):
        Plan.model_validate(plan)


@pytest.mark.parametrize("reference", ["", " ", "P0", "P0:x", "P0:020", "unknown:20", " P0:20"])
def test_scope_operation_references_are_strict(reference):
    with pytest.raises(ValidationError, match="setup:op"):
        InspectionScope.model_validate({"after": reference, "before": "unknown"})


@pytest.mark.parametrize(
    "case,reason,error",
    [
        ("missing_scope", "complete scope", BadInput),
        ("missing_endpoint", "before", ValidationError),
        ("missing_operation", "names no operation", BadInput),
        ("wrong_after", "scope order", BadInput),
        ("wrong_before", "scope order", BadInput),
        ("subset", "complete descendant membership", BadInput),
        ("sibling", "incoming material lineage", BadInput),
    ],
)
def test_invalid_known_scopes_fail_before_native(case, reason, error):
    plan = scoped_batch()
    op = plan["setups"][0]["ops"][1]
    if case == "missing_scope":
        op.pop("inspection_scope")
    elif case == "missing_endpoint":
        op["inspection_scope"].pop("before")
    elif case == "missing_operation":
        op["inspection_scope"]["before"] = "C1a:999"
    elif case == "wrong_after":
        op["inspection_scope"]["after"] = "C1a:10"
    elif case == "wrong_before":
        op["inspection_scope"]["before"] = "P0:20"
    elif case == "subset":
        op["inspect_workpieces"].remove("nut4")
    else:
        op["inspection_scope"]["before"] = "E1:10"
    with pytest.raises(error, match=reason):
        bind_scope(plan)


@pytest.mark.parametrize(
    "endpoint,value",
    [("after", "C1a:10"), ("before", "P0:20"), ("before", "missing:10")],
)
def test_unknown_counterpart_does_not_hide_a_known_invalid_endpoint(endpoint, value):
    plan = scoped_batch()
    op = plan["setups"][0]["ops"][1]
    op["inspection_scope"] = {"after": "unknown", "before": "unknown", endpoint: value}
    with pytest.raises(BadInput, match="scope order|names no operation"):
        bind_scope(plan)


def test_unknown_targets_remain_unknown_but_do_not_hide_wrong_scope_order():
    plan = scoped_batch()
    op = plan["setups"][0]["ops"][1]
    op["inspect_workpieces"] = "unknown"
    assert bind_scope(plan)["setups"][0]["ops"][1]["inspect_workpieces"] == "unknown"
    op["inspection_scope"]["after"] = "C1a:10"
    with pytest.raises(BadInput, match="scope order"):
        bind_scope(plan)


def test_shared_root_without_causal_incoming_lineage_is_not_a_scope():
    plan = {
        "part": "scratch",
        "features": "features.toml",
        "setups": [
            {"id": "A", "stock_in": "stock", "ops": [{"op": 10, "do": "face", "feature": "face"}]},
            {
                "id": "B",
                "stock_in": "stock",
                "ops": [
                    {
                        "op": 10,
                        "do": "inspect",
                        "feature": "face",
                        "inspect_workpieces": "unknown",
                        "inspection_scope": {"after": "A:10", "before": "C:10"},
                    }
                ],
            },
            {"id": "C", "stock_in": "B", "ops": [{"op": 10, "do": "face", "feature": "face"}]},
        ],
    }
    with pytest.raises(BadInput, match="incoming material lineage"):
        bind_scope(plan)


def test_registered_sibling_target_cannot_borrow_another_members_final_check():
    plan = scoped_batch()
    plan["setups"][-1]["ops"][0]["inspect_workpieces"] = ["nut1"]
    with pytest.raises(BadInput, match="live incoming workpieces"):
        bind_scope(plan)


def test_actual_authored_operation_order_not_numeric_sort_controls_scope():
    plan = scoped_batch()
    op = plan["setups"][0]["ops"][1]
    op["op"] = 10
    normalized = bind_scope(plan)
    assert [row["op"] for row in normalized["setups"][0]["ops"]] == [20, 10]


def shared_loader_plan(scope):
    second = REGISTERED.replace("nut1", "nut2").replace(
        "origin = [1.0, 0.0, 0.0]", "origin = [2.0, 0.0, 0.0]"
    )
    text = PLAN.replace("[[setups]]", REGISTERED + second + "[[setups]]")
    text = text.replace('id = "S1"', 'id = "S1"\nstock_in = "stock"')
    text = text.replace(
        "[[setups.ops]]",
        '[[setups.ops]]\nop = 5\ndo = "face"\nfeature = "subject"\n[[setups.ops]]',
    )
    text = text.replace(
        'checks = "unknown"',
        'checks = {width = "calipers"}\ninspect_workpieces = ["nut1", "nut2"]\n'
        f"inspection_scope = {scope}",
    )
    return (
        text + '\n[[setups]]\nid = "C1"\nstock_in = "S1"\n'
        '[[setups.ops]]\nop = 10\ndo = "face"\nfeature = "subject"\n'
    )


@pytest.mark.parametrize(
    "scope",
    [
        '{after = "S1:5", before = "C1:10"}',
        '"unknown"',
        '{after = "unknown", before = "C1:10"}',
    ],
)
def test_shared_scope_survives_full_source_bound_bundle_loading(tmp_path, scope):
    features = SOURCE_FEATURES.replace(
        "requirements = []", 'requirements = ["width"]\nwidth = [22.1, 22.3]'
    )
    path = bundle_files(tmp_path, shared_loader_plan(scope), features)
    (tmp_path / "source.STEP").write_text(STEP, encoding="ascii")
    loaded = load_bundle(path)
    op = loaded.plan["setups"][0]["ops"][1]
    assert op["inspect_workpieces"] == ["nut1", "nut2"]
    assert loaded.features["features"]["subject"]["width"] == [22.1, 22.3]
    if scope == '"unknown"':
        assert op["inspection_scope"] == "unknown"
    else:
        assert op["inspection_scope"]["before"] == "C1:10"


def test_invalid_scope_is_rejected_by_full_loader_not_only_binding_helper(tmp_path):
    features = SOURCE_FEATURES.replace(
        "requirements = []", 'requirements = ["width"]\nwidth = [22.1, 22.3]'
    )
    scope = '{after = "unknown", before = "missing:10"}'
    path = bundle_files(tmp_path, shared_loader_plan(scope), features)
    with pytest.raises(BadInput, match="inspection_scope.before names no operation"):
        load_bundle(path)


def test_unknown_scope_cannot_hide_incomplete_known_batch_membership():
    plan = scoped_batch()
    op = plan["setups"][0]["ops"][1]
    op["inspection_scope"] = "unknown"
    op["inspect_workpieces"].remove("nut4")
    with pytest.raises(BadInput, match="complete descendant membership"):
        bind_scope(plan)


def test_scope_cannot_bind_a_known_transient_instead_of_a_registered_feature():
    plan = scoped_batch()
    plan["setups"][0]["ops"][1]["feature"] = "transient-preparation-face"
    plan["setups"][0]["ops"][1]["inspection_scope"] = "unknown"
    with pytest.raises(BadInput, match="registered finished features"):
        bind_scope(plan)


def test_inspection_after_split_needs_an_actual_receiving_material():
    plan = scoped_batch()
    op = copy.deepcopy(plan["setups"][0]["ops"][1])
    op["op"] = 20
    op["inspection_scope"] = {"after": "unknown", "before": "unknown"}
    plan["setups"][1]["ops"].append(op)
    with pytest.raises(BadInput, match="partition without a receiving material"):
        bind_scope(plan)


def test_geometry_member_claims_never_become_implicit_inspection_targets():
    normalized = bind_scope(scoped_batch())
    final = normalized["setups"][-1]["ops"][0]
    assert final["workpiece_faces"].keys() == {"nut4"}
    assert "inspect_workpieces" not in final


def test_scope_before_boundary_cannot_name_a_postpartition_operation():
    plan = scoped_batch()
    plan["setups"][1]["ops"].append({"op": 20, "do": "inspect", "feature": "face"})
    plan["setups"][0]["ops"][1]["inspection_scope"]["before"] = "C1a:20"
    with pytest.raises(BadInput, match="incoming material lineage"):
        bind_scope(plan)


@pytest.mark.parametrize("registry", [None, "unknown", {}])
def test_known_inspection_targets_require_actual_registered_identities(registry):
    plan = {
        "part": "scratch",
        "features": "features.toml",
        "setups": [
            {
                "id": "F1",
                "stock_in": "stock",
                "ops": [
                    {
                        "op": 10,
                        "do": "inspect",
                        "feature": "face",
                        "inspect_workpieces": ["nut1"],
                    }
                ],
            }
        ],
    }
    if registry is not None:
        plan["workpieces"] = registry
    with pytest.raises(ValidationError, match="registered workpieces"):
        Plan.model_validate(plan)


@pytest.mark.parametrize(
    "relationship",
    [
        "unknown",
        {},
        {"features": "unknown", "contract": "unknown"},
        {"features": ["base"], "contract": None},
        {"features": ["base"], "contract": "unknown", "requirements": []},
    ],
)
def test_relationship_entry_cannot_erase_participants_or_add_requirement_overrides(relationship):
    data = manifest()
    data["acceptance"]["actual_slot_fit"] = relationship
    with pytest.raises(ValidationError, match="acceptance"):
        Features.model_validate(data)
