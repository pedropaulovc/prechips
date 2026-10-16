"""Sequential physical joins and joint-compound input/debt boundaries."""

import copy
import dataclasses
import tomllib

import pytest
from pydantic import ValidationError
from test_joint_features import _load, _plan

from prechips.joint_features import setup_joint
from prechips.model import Plan
from prechips.rules import joints


def three_component_plan():
    plan = tomllib.loads(_plan())
    plan["stock"]["components"].append({"id": "crank"})
    socket = copy.deepcopy(plan["joint_features"]["socket"])
    socket["at"] = [20, 0, 0]
    plan["joint_features"]["crank_socket"] = socket
    spigot = copy.deepcopy(plan["joint_features"]["spigot"])
    spigot.update(component="crank", at=[20, 0, 0])
    plan["joint_features"]["crank_spigot"] = spigot
    plan["setups"][0]["ops"].append({"op": 20, "do": "drill", "feature": "crank_socket"})
    plan["setups"].append(
        {
            "id": "C",
            "stock_in": "stock.crank",
            "ops": [{"op": 10, "do": "finish_turn", "feature": "crank_spigot"}],
        }
    )
    joint = copy.deepcopy(plan["setups"][2]["joint"])
    joint.update(socket="crank_socket", spigot="crank_spigot")
    plan["setups"].append(
        {
            "id": "J2",
            "stock_in": ["J", "C"],
            "joint": joint,
            "ops": [{"op": 10, "do": "fit", "feature": "subject"}],
        }
    )
    return plan


COMPOUND = {
    "product": "AUTHOR'S CHOICE: example Loctite 638-class retaining compound",
    "cure_time_min": 1440,
    "surface_prep": "AUTHOR'S CHOICE: degrease and dry both mating surfaces",
}


def compound(joint, method="slip"):
    """Bond ``joint`` with the example compound; returns its compound block."""
    joint.update(
        method=method,
        process="AUTHOR'S CHOICE: apply to both mating surfaces and assemble",
        compound=dict(COMPOUND),
    )
    return joint["compound"]


def loaded_plan(tmp_path, plan):
    bundle = _load(tmp_path)
    validated = Plan.model_validate(plan).model_dump(exclude_unset=True)
    return dataclasses.replace(bundle, plan=validated)


def test_three_components_join_as_assembly_plus_single_component(tmp_path):
    plan = three_component_plan()
    compound(plan["setups"][-1]["joint"])
    bundle = loaded_plan(tmp_path, plan)
    rows = joints.evaluate_fit(bundle)
    assert [(row.subject, row.status) for row in rows] == [("J", "pass"), ("J2", "pass")]
    second = setup_joint(bundle, bundle.plan["setups"][-1])
    assert second["socket_ref"] == "J"
    assert second["spigot_ref"] == "C"
    assert second["engagement"]["depth_mm"] == pytest.approx(5)


def test_sequential_join_refuses_shared_supply_ancestry():
    plan = three_component_plan()
    plan["setups"][-1]["stock_in"] = ["J", "B"]
    with pytest.raises(ValidationError, match="shares ancestor 'stock.body'"):
        Plan.model_validate(plan)


def test_two_existing_assemblies_cannot_be_joined():
    plan = three_component_plan()
    plan["stock"]["components"].append({"id": "fourth"})
    plan["setups"].insert(
        -1,
        {
            "id": "J3",
            "stock_in": ["C", "stock.fourth"],
            "joint": {
                "kind": "surface",
                "method": "weld",
                "process": "AUTHOR'S CHOICE: butt weld",
                "cite": ["AUTHOR'S CHOICE: fourth component joint"],
                "interfaces": [
                    {
                        "at": [20, 0, 0],
                        "normal": [1, 0, 0],
                        "x": [0, 1, 0],
                        "size_mm": [2, 2],
                        "cite": ["AUTHOR'S CHOICE: butt interface"],
                    }
                ],
            },
            "ops": [{"op": 10, "do": "fit", "feature": "subject"}],
        },
    )
    plan["setups"][-1]["stock_in"] = ["J", "J3"]
    with pytest.raises(ValidationError, match="two already-joined assemblies"):
        Plan.model_validate(plan)


@pytest.mark.parametrize("field", ["clearance_mm", "product", "cure_time_min", "surface_prep"])
def test_unknown_compound_fact_is_debt_and_withholds_join(tmp_path, field):
    plan = tomllib.loads(_plan())
    joint = plan["setups"][-1]["joint"]
    block = compound(joint)
    (block if field in COMPOUND else joint)[field] = "unknown"
    bundle = loaded_plan(tmp_path, plan)
    (row,) = joints.evaluate_fit(bundle)
    assert row.status == "unknown"
    where = "joint" if field == "clearance_mm" else "joint.compound"
    assert f"setups[J].{where}.{field}" in row.numbers["missing"]
    normalized = setup_joint(bundle, bundle.plan["setups"][-1])
    debt = normalized["reason"] if field == "clearance_mm" else normalized["process_reason"]
    assert field in debt
    assert normalized["fit_error"] is None


@pytest.mark.parametrize(
    "field, value",
    [
        ("product", None),
        ("product", ""),
        ("product", "  "),
        ("cure_time_min", None),
        ("cure_time_min", 0),
        ("cure_time_min", -1),
        ("surface_prep", None),
        ("surface_prep", ""),
    ],
)
def test_compound_requires_product_positive_cure_and_declared_prep(field, value):
    plan = tomllib.loads(_plan())
    block = compound(plan["setups"][-1]["joint"])
    control = Plan.model_validate(copy.deepcopy(plan))
    assert control.setups[-1].joint.method == "slip"
    assert control.setups[-1].joint.compound.cure_time_min > 0
    assert control.setups[-1].joint.compound.surface_prep
    if value is None:
        del block[field]
    else:
        block[field] = value
    with pytest.raises(ValidationError) as caught:
        Plan.model_validate(plan)
    errors = caught.value.errors()
    assert any(
        error["loc"][:3] == ("setups", 2, "joint") and error["loc"][4:5] == ("compound",)
        for error in errors
    ), errors


# Every fit x method x compound pairing: None accepts, otherwise the message it fails with.
@pytest.mark.parametrize(
    "fit, method, bonded, refusal",
    [
        ("clearance", "silver_braze", False, None),
        ("clearance", "silver_braze", True, "A silver_braze joint takes no compound"),
        ("clearance", "slip", True, None),
        ("clearance", "slip", False, "A slip joint must declare compound"),
        ("clearance", "press", False, "A clearance joint cannot be made by press"),
        ("clearance", "press", True, "A clearance joint cannot be made by press"),
        ("interference", "press", False, None),
        ("interference", "press", True, None),
        ("interference", "slip", True, "An? interference joint cannot be made by slip"),
        ("interference", "slip", False, "An? interference joint cannot be made by slip"),
        ("interference", "silver_braze", False, "interference joint cannot be made by silver"),
        ("interference", "silver_braze", True, "interference joint cannot be made by silver"),
    ],
)
def test_each_fit_takes_its_methods_and_only_a_bondable_method_takes_a_compound(
    fit, method, bonded, refusal
):
    plan = tomllib.loads(_plan(fit=fit, band=(0.1, 0.4)))
    joint = plan["setups"][-1]["joint"]
    if bonded:
        compound(joint, method)
    joint["method"] = method
    if refusal is None:
        validated = Plan.model_validate(plan).setups[-1].joint
        assert (validated.method, validated.compound is not None) == (method, bonded)
        return
    with pytest.raises(ValidationError, match=refusal):
        Plan.model_validate(plan)


@pytest.mark.parametrize(
    "legacy, named",
    [
        ({"method": "retaining_compound"}, 'no longer "retaining_compound"'),
        ({"cure_time_min": 1440}, "cure_time_min moved into its compound block"),
        ({"surface_prep": "degrease"}, "surface_prep moved into its compound block"),
    ],
)
def test_the_retired_compound_form_fails_naming_the_compound_block(legacy, named):
    plan = tomllib.loads(_plan())
    plan["setups"][-1]["joint"].update(legacy)
    with pytest.raises(ValidationError, match=named) as caught:
        Plan.model_validate(plan)
    assert "compound = { product, cure_time_min, surface_prep }" in str(caught.value)


def test_a_press_fit_with_compound_reports_its_interference_band_cure_and_prep(tmp_path):
    plan = tomllib.loads(
        _plan(socket=(9.875, 10.0), spigot=(10.125, 10.25), fit="interference", band=(0.1, 0.4))
    )
    compound(plan["setups"][-1]["joint"], "press")
    bundle = loaded_plan(tmp_path, plan)
    (row,) = joints.evaluate_fit(bundle)
    assert row.status == "pass"
    assert {key: row.numbers[key] for key in ("fit", "method", "band_mm", "guaranteed_mm")} == {
        "fit": "interference",
        "method": "press",
        "band_mm": [0.1, 0.4],
        "guaranteed_mm": [0.125, 0.375],
    }
    assert {key: row.numbers[key] for key in COMPOUND} == COMPOUND
    normalized = setup_joint(bundle, bundle.plan["setups"][-1])
    assert normalized["compound"] == COMPOUND
    assert normalized["process_reason"] is None


def test_a_press_fit_with_unknown_cure_is_debt_and_withholds_join(tmp_path):
    plan = tomllib.loads(
        _plan(socket=(9.875, 10.0), spigot=(10.125, 10.25), fit="interference", band=(0.1, 0.4))
    )
    compound(plan["setups"][-1]["joint"], "press")["cure_time_min"] = "unknown"
    bundle = loaded_plan(tmp_path, plan)
    (row,) = joints.evaluate_fit(bundle)
    assert row.status == "unknown"
    assert row.numbers["missing"] == ["setups[J].joint.compound.cure_time_min"]
    assert row.numbers["cure_time_min"] == "unknown"
    assert "cure_time_min" in setup_joint(bundle, bundle.plan["setups"][-1])["process_reason"]


@pytest.mark.parametrize(
    "joint",
    [
        {},  # silver braze clearance
        {"socket": (9.875, 10.0), "spigot": (10.125, 10.25), "fit": "interference"},
    ],
)
def test_bare_silver_braze_and_press_carry_no_compound_facts(tmp_path, joint):
    band = {"band": (0.1, 0.4)} if joint else {}
    bundle = loaded_plan(tmp_path, tomllib.loads(_plan(**joint, **band)))
    (row,) = joints.evaluate_fit(bundle)
    assert row.status == "pass"
    assert not {"product", "cure_time_min", "surface_prep"} & row.numbers.keys()
    normalized = setup_joint(bundle, bundle.plan["setups"][-1])
    assert "compound" not in normalized and "process_reason" not in normalized


def test_unknown_cure_does_not_hide_known_incompatible_fit(tmp_path):
    plan = tomllib.loads(_plan())
    joint = plan["setups"][-1]["joint"]
    compound(joint)["cure_time_min"] = "unknown"
    joint["clearance_mm"] = [0.1, 0.25]
    bundle = loaded_plan(tmp_path, plan)
    (row,) = joints.evaluate_fit(bundle)
    assert row.status == "error"
    assert row.numbers["violations"] == ["clearance_below_band"]
    normalized = setup_joint(bundle, bundle.plan["setups"][-1])
    assert normalized["fit_error"]
    assert normalized["reason"] is None
    assert "cure_time_min" in normalized["process_reason"]
