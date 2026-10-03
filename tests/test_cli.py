"""CLI boundaries exercised through the installed Python entry point."""

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def run_cli(*args, env=None, setup=""):
    """Run the CLI in a clean environment; ``setup`` is Python run before ``main``."""
    environment = os.environ.copy()
    for key in tuple(environment):
        if key.startswith(("PRECHIPS_", "OTEL_")):
            environment.pop(key)
    environment["OTEL_SDK_DISABLED"] = "true"
    environment.update(env or {})
    entry = (
        ["-c", f"{setup}\nimport sys\nfrom prechips.cli import main\nsys.exit(main(sys.argv[1:]))"]
        if setup
        else ["-m", "prechips.cli"]
    )
    return subprocess.run(
        [sys.executable, *entry, *map(str, args)],
        cwd=ROOT,
        env=environment,
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


@pytest.mark.parametrize(
    ("variable", "value"),
    [("OTEL_EXPORTER_OTLP_PROTOCOL", "http/json"), ("OTEL_EXPORTER_OTLP_TIMEOUT", "5s")],
)
def test_malformed_otlp_setting_warns_once_and_keeps_unconfigured_result(variable, value, tmp_path):
    plan = copy_examples(tmp_path) / "pivot-shaft" / "plan.toml"
    plain = run_cli("check", plan, "--out", tmp_path / "plain")
    configured = run_cli(
        "check",
        plan,
        "--out",
        tmp_path / "configured",
        env={"OTEL_EXPORTER_OTLP_ENDPOINT": "http://127.0.0.1:9", variable: value},
    )
    assert plain.returncode in {0, 2, 4}, plain.stderr
    assert configured.returncode == plain.returncode, configured.stderr
    report = (tmp_path / "configured" / "report.json").read_bytes()
    assert report == (tmp_path / "plain" / "report.json").read_bytes()
    # One warning naming the variable precedes the unconfigured run's own stderr.
    assert configured.stderr.endswith(plain.stderr)
    warning = configured.stderr.removesuffix(plain.stderr)
    assert warning.count(variable) == 1
    assert "Traceback" not in warning


RULE_BUGS = {
    "raises": """
from prechips import rules
rules.RULES[0] = rules.Rule(rules.RULES[0].name, lambda bundle: {}["dia"])
""",
    "duplicate_subjects": """
from prechips import rules
first = rules.RULES[0]
rules.RULES[0] = rules.Rule(first.name, lambda bundle: first.evaluate(bundle)[:1] * 2)
""",
}


@pytest.mark.parametrize("bug", sorted(RULE_BUGS))
def test_internal_rule_failure_is_traceback_exit_1_not_bad_input(bug, tmp_path):
    plan = copy_examples(tmp_path) / "pivot-shaft" / "plan.toml"
    out = tmp_path / "out"
    result = run_cli("traveler", plan, "--out", out, setup=RULE_BUGS[bug])
    assert result.returncode == 1, result.stderr
    assert "Traceback" in result.stderr
    assert not out.exists() or not tuple(out.iterdir())


# Each injection makes the filesystem refuse only traveler.html, after report.json is ready.
TRAVELER_REFUSALS = {
    "write": """
import builtins, io, os
_open = io.open
def _refuse(file, mode="r", *args, **kwargs):
    if (
        isinstance(file, (str, os.PathLike))
        and "traveler.html" in os.fspath(file)
        and set(mode) & set("wxa+")
    ):
        raise OSError(28, "No space left on device", os.fspath(file))
    return _open(file, mode, *args, **kwargs)
io.open = builtins.open = _refuse
""",
    "replace": """
import os
_replace = os.replace
def _refuse(source, target, *args, **kwargs):
    if os.path.basename(target) == "traveler.html":
        raise OSError(13, "Permission denied", os.fspath(target))
    return _replace(source, target, *args, **kwargs)
os.replace = _refuse
""",
}


@pytest.mark.parametrize("preexisting", [False, True], ids=["fresh", "preexisting"])
@pytest.mark.parametrize("refusal", sorted(TRAVELER_REFUSALS))
def test_refused_traveler_output_leaves_prior_outputs_exactly(refusal, preexisting, tmp_path):
    plan = copy_examples(tmp_path) / "pivot-shaft" / "plan.toml"
    out = tmp_path / "out"
    prior = {}
    if preexisting:
        out.mkdir()
        prior = {"report.json": b"earlier report\n", "traveler.html": b"earlier traveler\n"}
        for name, data in prior.items():
            (out / name).write_bytes(data)
    result = run_cli("traveler", plan, "--out", out, setup=TRAVELER_REFUSALS[refusal])
    assert result.returncode == 3, result.stderr
    assert "Traceback" not in result.stderr
    # No new report beside an old traveler, no staged temporaries left behind.
    after = {path.name: path.read_bytes() for path in out.iterdir()} if out.exists() else {}
    assert after == prior
