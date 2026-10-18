"""An inspect op may name a list of features (#333).

The plan schema accepts ``feature = [a, b]`` on an inspect op; a rule that hashes an op's
``feature`` as one name (a set or dict lookup) raised ``TypeError`` on it and the CLI died
with a traceback. Each bundle here gains such an op in every setup.
"""

import json
import re
import shutil
from dataclasses import replace

import pytest
from test_cli import ROOT, SYNTHETIC_KERNEL, run_cli
from test_tooling_hole import ROUTE, bundle_plan, rows, with_states

from prechips.inputs import load_bundle
from prechips.process_features import process_of
from prechips.rules import RULES

EXAMPLE_PLANS = sorted(
    path.relative_to(ROOT / "examples")
    for path in (ROOT / "examples").glob("**/*.toml")
    if "[[setups]]" in path.read_text(encoding="utf-8")
)


def inspect_lists(plan, names):
    """Append an inspect op naming the feature list ``names`` to every setup of ``plan``."""
    op = f'\n[[setups.ops]]\nop = 999\ndo = "inspect"\nfeature = {json.dumps(names)}\n'
    head, *setups = plan.read_text(encoding="utf-8").split("\n[[setups]]")
    plan.write_text(
        head + "".join(f"\n[[setups]]{setup.rstrip()}\n{op}" for setup in setups),
        encoding="utf-8",
    )


def finished(bundle):
    """Two distinct finished (non-process) features of ``bundle``, or None."""
    names = [n for n, d in bundle.feature_definitions.items() if not process_of(d)][:2]
    return names if len(names) == 2 else None


def test_check_finishes_on_a_tooling_hole_plan_with_a_list_inspect(tmp_path):
    plan = bundle_plan(tmp_path)
    inspect_lists(plan, ["strap_faces", "hub_faces"])
    out = tmp_path / "out"
    result = run_cli("check", plan, "--out", out, setup=SYNTHETIC_KERNEL)
    assert "Traceback" not in result.stderr, result.stderr
    assert result.returncode in {0, 2, 4}, result.stderr
    report = json.loads((out / "report.json").read_bytes())
    subjects = {f["subject"] for f in report["findings"] if f["rule"] == "tooling_hole"}
    assert {"S1:cl_tooling_hole", "T3:cl_tooling_hole", "T5:cl_tooling_hole"} <= subjects


def test_a_list_inspect_leaves_the_tooling_hole_rows_unchanged(tmp_path):
    plain = rows(with_states(load_bundle(bundle_plan(tmp_path / "plain")), ROUTE))
    plan = bundle_plan(tmp_path / "listed")
    inspect_lists(plan, ["strap_faces", "hub_faces"])
    listed = rows(with_states(load_bundle(plan), ROUTE))
    assert {s: (r.status, r.sentence) for s, r in listed.items()} == {
        s: (r.status, r.sentence) for s, r in plain.items()
    }


@pytest.mark.parametrize("example", EXAMPLE_PLANS, ids=str)
def test_no_rule_raises_on_a_list_inspect_in_every_setup(tmp_path, example):
    shutil.copytree(ROOT / "examples", tmp_path / "examples")
    plan = tmp_path / "examples" / example
    names = finished(load_bundle(plan))
    if names is None:
        pytest.skip("the bundle has fewer than two finished features to list")
    inspect_lists(plan, names)
    bundle = replace(
        load_bundle(plan),
        kernel={
            "status": "ok",
            "bbox_mm": [-10, -10, -10, 10, 10, 100],
            "ops": {},
            "setups": {},
            "mapping": {},
        },
    )
    for rule in RULES:
        rule.evaluate(bundle)


def test_the_tooling_hole_bundle_has_a_list_inspect_in_every_setup(tmp_path):
    plan = bundle_plan(tmp_path)
    inspect_lists(plan, ["strap_faces", "hub_faces"])
    text = plan.read_text(encoding="utf-8")
    assert len(re.findall(r'(?m)^feature = \["strap_faces", "hub_faces"\]$', text)) == len(
        re.findall(r"(?m)^\[\[setups\]\]$", text)
    )
    for rule in RULES:
        rule.evaluate(with_states(load_bundle(plan), ROUTE))
