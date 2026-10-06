"""Authored material routes reject bad references before running any machining rules."""

import pytest
from test_cli import run_cli
from test_input_contracts import PLAN, bundle_files

from prechips.inputs import BadInput, load_bundle
from prechips.model import Plan
from prechips.rules import op_order


def plan_with_routes(routes, components=None):
    plan = {
        "part": "route-test",
        "features": "features.toml",
        "setups": [{"id": sid, "stock_in": source} for sid, source in routes],
    }
    if components is not None:
        plan["stock"] = {"components": components}
    return plan


@pytest.mark.parametrize(
    "source",
    ["S2", "S1", "missing", "unknown", "stock.missing", ["stock", "S2"], []],
)
def test_invalid_route_exits_three_without_outputs(tmp_path, source):
    import json

    authored = json.dumps(source)
    text = PLAN.replace('id = "S1"', f'id = "S1"\nstock_in = {authored}')
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
    [[{}], [{"id": "unknown"}], [{"id": "body"}, {"id": "body"}], [{"id": "bad.id"}]],
)
def test_components_require_unique_known_ids(components):
    with pytest.raises(ValueError):
        Plan.model_validate(plan_with_routes([("S1", "stock.body")], components))


def test_nonprevious_and_assembly_routes_resolve_but_root_stock_is_not_a_component():
    routes = [("S0", "stock.body"), ("S1", "stock.boss"), ("S2", "S0"), ("S3", ["S2", "S1"])]
    Plan.model_validate(plan_with_routes(routes, [{"id": "body"}, {"id": "boss"}]))
    with pytest.raises(ValueError, match="single stock supply"):
        Plan.model_validate(plan_with_routes([("S0", "stock")], [{"id": "body"}]))


@pytest.mark.parametrize("ids", [["S1", "S1"], ["stock"], ["stock.body"], [""]])
def test_setup_ids_cannot_be_ambiguous_with_supply_refs(ids):
    with pytest.raises(ValueError):
        Plan.model_validate(plan_with_routes([(sid, "stock") for sid in ids]))


def test_assembly_receives_drilled_stock_for_a_later_ream(tmp_path):
    from types import SimpleNamespace

    plan = {
        "setups": [
            {"id": "S1", "ops": [{"op": 10, "do": "drill", "feature": "bore"}]},
            {"id": "S2", "ops": [], "stock_in": "stock.boss"},
            {
                "id": "S3",
                "stock_in": ["S1", "S2"],
                "ops": [{"op": 10, "do": "ream", "feature": "bore"}],
            },
        ]
    }
    bundle = SimpleNamespace(plan=plan, features={"features": {"bore": {}}})
    rows = {row.subject: row for row in op_order.evaluate(bundle)}
    assert rows["S3"].status == "pass"
