"""Authored material routes reject bad references before running any machining rules."""

import json
import tomllib
from types import SimpleNamespace

import pytest
from test_cli import run_cli
from test_input_contracts import PLAN, bundle_files

from prechips.inputs import BadInput, load_bundle
from prechips.model import Plan
from prechips.rules import op_order

JOINT = (
    'joint = {kind = "surface", method = "weld", process = "Weld butt faces", '
    'cite = "AUTHOR\'S CHOICE", interfaces = [{at = [30, 20, 10], normal = [1, 0, 0], '
    'x = [0, 1, 0], size_mm = [40, 20], cite = "Internal butt interface"}]}\n'
)


def plan_with_routes(routes, components=None):
    plan = {
        "part": "route-test",
        "features": "features.toml",
        "setups": [
            {
                "id": sid,
                "stock_in": source,
                **(tomllib.loads(JOINT) if isinstance(source, list) else {}),
            }
            for sid, source in routes
        ],
    }
    if components is not None:
        plan["stock"] = {"components": components}
    return plan


@pytest.mark.parametrize(
    "source",
    ["S2", "S1", "missing", "unknown", "stock.missing", ["stock", "S2"], []],
)
def test_invalid_route_exits_three_without_outputs(tmp_path, source):
    authored = json.dumps(source)
    text = PLAN.replace('id = "S1"', f'id = "S1"\nstock_in = {authored}')
    if isinstance(source, list):
        text = text.replace(f"stock_in = {authored}\n", f"stock_in = {authored}\n{JOINT}")
    text += '\n[[setups]]\nid = "S2"\nstock_in = "S1"\n'
    path = bundle_files(tmp_path, text)
    with pytest.raises(BadInput):
        load_bundle(path)
    out = tmp_path / "out"
    result = run_cli("check", path, "--out", out)
    assert result.returncode == 3, result.stderr
    assert "stock_in" in result.stderr
    if source in ("S1", "S2"):
        assert "earlier setup" in result.stderr
    assert not out.exists() or not tuple(out.iterdir())


@pytest.mark.parametrize(
    "components",
    [[{}], [{"id": "unknown"}], [{"id": "body"}, {"id": "body"}], [{"id": " "}]],
)
def test_components_require_unique_known_ids(components):
    with pytest.raises(ValueError):
        Plan.model_validate(plan_with_routes([], components))


def test_nonprevious_and_assembly_routes_resolve_but_root_stock_is_not_a_component():
    routes = [("S0", "stock.body"), ("S1", "stock.boss"), ("S2", "S0"), ("S3", ["S2", "S1"])]
    Plan.model_validate(plan_with_routes(routes, [{"id": "body"}, {"id": "boss"}]))
    with pytest.raises(ValueError, match="single stock supply"):
        Plan.model_validate(plan_with_routes([("S0", "stock")], [{"id": "body"}]))


@pytest.mark.parametrize("ids", [["S1", "S1"], ["stock"], ["stock.body"], [""]])
def test_setup_ids_cannot_be_ambiguous_with_supply_refs(ids):
    with pytest.raises(ValueError):
        Plan.model_validate(plan_with_routes([(sid, "stock") for sid in ids]))


@pytest.mark.parametrize(
    "second_source, third_source, status",
    [
        ("stock.boss", ["S1", "S2"], "pass"),
        ("stock.boss", "S2", "error"),
        ("S1", "S2", "pass"),
    ],
)
def test_ream_requires_drilled_material_in_its_direct_or_transitive_route(
    second_source, third_source, status
):

    plan = {
        "setups": [
            {
                "id": "S1",
                "stock_in": "stock.body",
                "ops": [{"op": 10, "do": "drill", "feature": "bore"}],
            },
            {"id": "S2", "ops": [], "stock_in": second_source},
            {
                "id": "S3",
                "stock_in": third_source,
                "zero": {"transfer": {"from": "S1"}},
                "ops": [{"op": 10, "do": "ream", "feature": "bore"}],
            },
        ]
    }
    if isinstance(third_source, list):
        plan["setups"][2].update(tomllib.loads(JOINT))
    bundle = SimpleNamespace(plan=plan, feature_definitions={"bore": {}})
    rows = {row.subject: row for row in op_order.evaluate(bundle)}
    assert rows["S3"].status == status


@pytest.mark.parametrize("refs", [["stock", "S1"], ["S0", "S1"], ["S1", "S1"]])
def test_joining_shared_material_ancestry_exits_three(tmp_path, refs):
    text = PLAN.replace('id = "S1"', 'id = "S0"\nstock_in = "stock"')
    text += (
        '\n[[setups]]\nid = "S1"\nstock_in = "S0"\n'
        f'\n[[setups]]\nid = "S2"\nstock_in = {json.dumps(refs)}\n'
        + JOINT
    )
    path = bundle_files(tmp_path, text)
    out = tmp_path / "out"
    result = run_cli("check", path, "--out", out)
    assert result.returncode == 3, result.stderr
    assert "ancestor 'stock'" in result.stderr
    assert not out.exists() or not tuple(out.iterdir())
