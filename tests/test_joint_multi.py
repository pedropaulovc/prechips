"""Sequential physical joins and retaining-compound input/debt boundaries."""

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


def compound(joint):
    joint.update(
        method="retaining_compound",
        process="AUTHOR'S CHOICE: example Loctite 638-class retaining compound",
        cure_time_min=1440,
        surface_prep="AUTHOR'S CHOICE: degrease and dry both mating surfaces",
    )
    return joint


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


@pytest.mark.parametrize("field", ["clearance_mm", "cure_time_min", "surface_prep"])
def test_unknown_compound_fact_is_debt_and_withholds_join(tmp_path, field):
    plan = tomllib.loads(_plan())
    compound(plan["setups"][-1]["joint"])[field] = "unknown"
    bundle = loaded_plan(tmp_path, plan)
    (row,) = joints.evaluate_fit(bundle)
    assert row.status == "unknown"
    assert f"setups[J].joint.{field}" in row.numbers["missing"]
    normalized = setup_joint(bundle, bundle.plan["setups"][-1])
    assert field in normalized["reason"]
    assert normalized["fit_error"] is None


@pytest.mark.parametrize(
    "field, value",
    [
        ("cure_time_min", None),
        ("cure_time_min", 0),
        ("cure_time_min", -1),
        ("surface_prep", None),
        ("surface_prep", ""),
    ],
)
def test_compound_requires_positive_cure_and_declared_prep(field, value):
    plan = tomllib.loads(_plan())
    joint = compound(plan["setups"][-1]["joint"])
    if value is None:
        del joint[field]
    else:
        joint[field] = value
    with pytest.raises(ValidationError):
        Plan.model_validate(plan)


def test_silver_braze_does_not_require_compound_process_fields(tmp_path):
    bundle = loaded_plan(tmp_path, tomllib.loads(_plan()))
    (row,) = joints.evaluate_fit(bundle)
    assert row.status == "pass"
    assert "cure_time_min" not in setup_joint(bundle, bundle.plan["setups"][-1])


def test_unknown_cure_does_not_hide_known_incompatible_fit(tmp_path):
    plan = tomllib.loads(_plan())
    joint = compound(plan["setups"][-1]["joint"])
    joint.update(cure_time_min="unknown", clearance_mm=[0.1, 0.25])
    bundle = loaded_plan(tmp_path, plan)
    (row,) = joints.evaluate_fit(bundle)
    assert row.status == "error"
    assert row.numbers["violations"] == ["clearance_below_band"]
    normalized = setup_joint(bundle, bundle.plan["setups"][-1])
    assert normalized["fit_error"]
    assert "cure_time_min" in normalized["reason"]
