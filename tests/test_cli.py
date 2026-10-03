"""CLI boundaries exercised through the installed Python entry point."""

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest


ROOT = Path(__file__).resolve().parents[1]


def run_cli(*args):
    env = os.environ.copy()
    for key in tuple(env):
        if key.startswith(("PRECHIPS_", "OTEL_")):
            env.pop(key)
    env["OTEL_SDK_DISABLED"] = "true"
    return subprocess.run(
        [sys.executable, "-m", "prechips.cli", *map(str, args)],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=60,
        check=False,
    )


def copy_examples(tmp_path):
    return Path(shutil.copytree(ROOT / "examples", tmp_path / "examples"))


def traveler(plan, out, *args):
    result = run_cli("traveler", plan, "--out", out, *args)
    assert result.returncode in {0, 2, 4}, result.stderr
    report = json.loads((out / "report.json").read_bytes())
    html = (out / "traveler.html").read_text(encoding="utf-8")
    return result, report, html


@pytest.mark.parametrize("args", [(), ("not-a-verb",)])
def test_missing_or_unknown_verb_is_bad_input(args, tmp_path):
    result = run_cli(*args, "--out", tmp_path)
    assert result.returncode == 3, result.stderr
    assert "usage" in (result.stdout + result.stderr).lower()
    assert not tuple(tmp_path.iterdir())


def test_empty_operations_rejects_before_outputs(tmp_path):
    examples = copy_examples(tmp_path)
    plan = examples / "rocker-arm" / "plan.toml"
    text = plan.read_text(encoding="utf-8")
    # Keep a complete first setup, but remove every operation and later setup.
    plan.write_text(text.split("[[setups.ops]]", 1)[0], encoding="utf-8")
    out = tmp_path / "out"
    result = run_cli("traveler", plan, "--out", out)
    assert result.returncode == 3, result.stderr
    assert "op" in result.stderr.lower()
    assert not out.exists() or not tuple(out.iterdir())


def test_output_input_collision_rejects_before_any_write(tmp_path):
    examples = copy_examples(tmp_path)
    plan = examples / "rocker-arm" / "plan.toml"
    out = tmp_path / "out"
    out.mkdir()
    inventory = out / "report.json"
    inventory.write_bytes((examples / "inventory" / "pedro-shop.toml").read_bytes())
    before = inventory.read_bytes()
    result = run_cli("traveler", plan, "--inventory", inventory, "--out", out)
    assert result.returncode == 3, result.stderr
    assert inventory.read_bytes() == before
    assert {path.name for path in out.iterdir()} == {"report.json"}
