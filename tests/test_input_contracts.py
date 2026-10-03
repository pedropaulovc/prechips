"""Sparse schema defaults, shop path precedence and expressible requirements."""

import hashlib
import json

import pytest
from test_cli import run_cli

from prechips.inputs import load_bundle

PLAN = """part = "scratch"
features = "features.toml"
[paths]
inventory = "inventory.toml"
policy = "policy.toml"
cutting_data = "cutting.toml"
[[setups]]
id = "S1"
machine = "mill"
frame = "unknown"
coolant = "unknown"
deburr_mm = "unknown"
hold = "unknown"
stock_state = "unknown"
zero = "unknown"
[[setups.ops]]
op = 10
do = "inspect"
feature = "subject"
tool = "unknown"
holder = "unknown"
checks = "unknown"
"""
FEATURES = """part = "scratch"
units = "mm"
frames = "unknown"
[features.subject]
kind = "face"
requirements = []
"""
INVENTORY = '[machines.mill]\nkind = "mill"\n'
POLICY = '[required]\ninspection = "*"\nop_chain = "*"\nheadroom = "*"\n'


def bundle_files(tmp_path, plan=PLAN, features=FEATURES, policy=POLICY):
    for name, text in (
        ("plan.toml", plan),
        ("features.toml", features),
        ("inventory.toml", INVENTORY),
        ("policy.toml", policy),
        ("cutting.toml", "revision = 1\n"),
    ):
        (tmp_path / name).write_text(text, encoding="utf-8")
    return tmp_path / "plan.toml"


@pytest.mark.parametrize("omitted", ["machine", "do", "kind", "all"])
def test_omitted_rule_identities_remain_unknown_and_do_not_crash(tmp_path, omitted):
    plan_text, feature_text = PLAN, FEATURES
    if omitted in {"machine", "all"}:
        plan_text = plan_text.replace('machine = "mill"\n', "")
    if omitted in {"do", "all"}:
        plan_text = plan_text.replace('do = "inspect"\n', "")
    if omitted in {"kind", "all"}:
        feature_text = feature_text.replace('kind = "face"\n', "")
    plan = bundle_files(tmp_path, plan_text, feature_text)
    bundle = load_bundle(plan)
    setup = bundle.plan["setups"][0]
    if omitted in {"machine", "all"}:
        assert setup["machine"] == "unknown"
    if omitted in {"do", "all"}:
        assert setup["ops"][0]["do"] == "unknown"
    if omitted in {"kind", "all"}:
        assert bundle.features["features"]["subject"]["kind"] == "unknown"
    out = tmp_path / "out"
    result = run_cli("check", plan, "--out", out)
    assert result.returncode == 4, result.stderr
    findings = {
        (row["rule"], row["subject"]): row
        for row in json.loads((out / "report.json").read_bytes())["findings"]
    }
    if omitted in {"machine", "all"}:
        assert findings["headroom", "S1"]["status"] == "unknown"
    if omitted in {"do", "kind", "all"}:
        assert findings["op_chain", "subject"]["status"] == "unknown"
        assert findings["inspection", "subject"]["status"] == "unknown"
    if omitted in {"do", "all"}:
        assert findings["order", "S1"]["status"] == "unknown"
        assert findings["tool_resolves", "S1:10"]["status"] == "unknown"


@pytest.mark.parametrize(
    ("document", "before", "after"),
    [
        ("plan", 'machine = "mill"', "machine = true"),
        ("plan", 'do = "inspect"', "do = 12"),
        ("features", 'kind = "face"', "kind = false"),
        ("plan", 'hold = "unknown"', 'hold = {index = {arbitrary = "value"}}'),
        ("plan", 'hold = "unknown"', "hold = {index = {positions = 4.5}}"),
    ],
)
def test_invalid_schema_still_exits_three_before_outputs(tmp_path, document, before, after):
    plan_text = PLAN.replace(before, after) if document == "plan" else PLAN
    feature_text = FEATURES.replace(before, after) if document == "features" else FEATURES
    plan = bundle_files(tmp_path, plan_text, feature_text)
    out = tmp_path / "out"
    result = run_cli("check", plan, "--out", out)
    assert result.returncode == 3, result.stderr
    assert "Traceback" not in result.stderr
    assert not out.exists() or not tuple(out.iterdir())


@pytest.mark.parametrize(
    ("field", "variable", "kind"),
    [
        ("inventory", "PRECHIPS_INVENTORY", "inventory"),
        ("policy", "PRECHIPS_POLICY", "shop_policy"),
    ],
)
@pytest.mark.parametrize("source", ["override", "declared", "unknown", "omitted"])
def test_shop_path_precedence_and_unknown_environment_fallback(
    tmp_path, monkeypatch, field, variable, kind, source
):
    inputs = tmp_path / "inputs"
    inputs.mkdir()
    plan_text = PLAN
    declaration = f'{field} = "{field}.toml"\n'
    if source == "unknown":
        plan_text = plan_text.replace(declaration, f'{field} = "unknown"\n')
    elif source == "omitted":
        plan_text = plan_text.replace(declaration, "")
    plan = bundle_files(inputs, plan_text)
    shop = tmp_path / "shop"
    shop.mkdir()
    for name, revision in (("environment", 7), ("override", 8)):
        text = (
            INVENTORY + f'note = "{name}"\n'
            if field == "inventory"
            else f'revision = {revision}\nrequired = {{inspection = "*"}}\n'
        )
        (shop / f"{name}.toml").write_text(text, encoding="utf-8")
    monkeypatch.chdir(shop)
    monkeypatch.setenv(variable, "environment.toml")
    overrides = {field: "override.toml"} if source == "override" else {}
    bundle = load_bundle(plan, **overrides)
    chosen = (
        inputs / f"{field}.toml"
        if source == "declared"
        else shop / ("override.toml" if source == "override" else "environment.toml")
    )
    assert bundle.paths[kind] == chosen
    assert bundle.hashes[kind] == hashlib.sha256(chosen.read_bytes()).hexdigest()
    if source != "declared":
        if field == "inventory":
            assert bundle.inventory["machines"]["mill"]["note"] == (
                "override" if source == "override" else "environment"
            )
        else:
            assert bundle.policy["revision"] == (8 if source == "override" else 7)


@pytest.mark.parametrize(
    ("value", "expected_exit", "status"),
    [
        ("[9.9, 10.1]", 0, "pass"),
        ('"unknown"', 4, "unknown"),
        ('["unknown", 10.1]', 4, "unknown"),
        (None, 3, None),
    ],
)
def test_separation_requirement_has_its_own_inspection_contract(
    tmp_path, request, value, expected_exit, status
):
    if expected_exit == 0:
        request.getfixturevalue("freecad_kernel")
    feature_text = FEATURES.replace("requirements = []", 'requirements = ["separation"]')
    if value is not None:
        feature_text += f"separation = {value}\n"
    plan_text = PLAN.replace('checks = "unknown"', 'checks = {separation = "caliper"}')
    plan = bundle_files(tmp_path, plan_text, feature_text, '[required]\ninspection = "*"\n')
    inventory = tmp_path / "inventory.toml"
    inventory.write_text(
        INVENTORY + '\n[gauges.caliper]\nkind = "caliper"\nrange_mm = [0.0, 25.0]\n'
        "resolution_mm = 0.01\nverify = false\n",
        encoding="utf-8",
    )
    out = tmp_path / "out"
    result = run_cli("check", plan, "--out", out)
    assert result.returncode == expected_exit, result.stderr
    if status is None:
        assert not out.exists() or not tuple(out.iterdir())
    else:
        report = json.loads((out / "report.json").read_bytes())
        finding = next(
            row
            for row in report["findings"]
            if row["rule"] == "inspection" and row["subject"] == "subject:separation"
        )
        assert finding["status"] == status
        assert finding["numbers"]["limits"] == json.loads(value)
