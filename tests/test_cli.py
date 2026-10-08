"""CLI boundaries exercised through the installed Python entry point."""

import json
import os
import re
import shutil
import subprocess
import sys
from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace

import pytest

from prechips.cli import _read_approval
from prechips.inputs import BadInput
from prechips.report import canonical_bytes, report_hash

ROOT = Path(__file__).resolve().parents[1]

# Host-only assertions need explicit geometry facts, not a real FreeCAD process.
# These boxes are synthetic envelopes, never production machining evidence.
SYNTHETIC_KERNEL = """
from dataclasses import replace
import prechips.cli as cli
_load_bundle = cli.load_bundle
def _synthetic_bundle(*args, **kwargs):
    bundle = _load_bundle(*args, **kwargs)
    boxes = {
        "pivot-shaft": [-5, -5, -175, 5, 5, 5],
        "pivot-bracket": [-9, -1, -4, 9, 33.2, 22.2],
        "rocker-arm": [-170, -20, -8, 170, 45, 8],
    }
    bbox = boxes.get(bundle.paths["plan"].parent.name, [-10, -10, -10, 10, 10, 100])
    return replace(bundle, kernel={
        "status": "ok", "bbox_mm": bbox, "ops": {}, "setups": {}, "mapping": {},
    })
cli.load_bundle = _synthetic_bundle
"""


def run_cli(*args, env=None, setup=""):
    """Run the CLI in a clean environment; ``setup`` is Python run before ``main``."""
    environment = os.environ.copy()
    for key in tuple(environment):
        if key.startswith(("PRECHIPS_", "OTEL_")):
            environment.pop(key)
    environment["OTEL_SDK_DISABLED"] = "true"
    if "PRECHIPS_KERNEL_CACHE" in os.environ:
        environment["PRECHIPS_KERNEL_CACHE"] = os.environ["PRECHIPS_KERNEL_CACHE"]
    elif "--out" in args:
        out = Path(args[args.index("--out") + 1])
        environment["PRECHIPS_KERNEL_CACHE"] = str(out.parent / "kernel-cache")
    if "PRECHIPS_KERNEL_WORKERS" in os.environ:
        environment["PRECHIPS_KERNEL_WORKERS"] = os.environ["PRECHIPS_KERNEL_WORKERS"]
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


# The rocker's prep: [stock.prepared] and the process faces and frames only P1-P5 use.
_ROCKER_PREP = re.compile(
    r"(?ms)^\[(?:stock\.prepared|process_features\.|frames\.P)[^\n]*\n.*?(?=^\[|\Z)"
)


def rocker_s1_alone(text):
    """The rocker plan with S1, up to its first op, as its only setup. The prep setups
    (P1-P5) and the tables only they use go, so S1 receives the plan [stock] itself and,
    as the first setup on the mill, mounts the vise: it squares the fixed jaw as the prep
    declared it."""
    first, start = text.index("[[setups]]"), text.index('[[setups]]\nid = "S1"\n')
    aligns = re.findall(r"(?m)^align = .*\n", text[first:start])
    assert len(aligns) == 1, "the prep's vise mounting says how its fixed jaw is squared"
    header = _ROCKER_PREP.sub("", text[:first])
    s1, count = re.subn(
        r"(?m)^stock_in = .*$", 'stock_in = "stock"', text[start:].split("[[setups.ops]]", 1)[0]
    )
    assert count == 1, "S1 names the stock it receives"
    assert not re.search(r"(?m)^align = ", s1), "S1 keeps the vise the prep squared"
    s1, count = re.subn(r"(?m)^\[setups\.hold\]\n", lambda m: m[0] + aligns[0], s1)
    assert count == 1, "S1 declares one hold"
    return header + s1


def traveler(plan, out, *args, setup=""):
    result = run_cli("traveler", plan, "--out", out, *args, setup=setup)
    assert result.returncode in {0, 2, 4}, result.stderr
    report = json.loads((out / "report.json").read_bytes())
    html = (out / "traveler.html").read_text(encoding="utf-8")
    return result, report, html


def test_installed_artifact_console_script_matches_module(tmp_path):
    artifact = os.environ.get("PRECHIPS_INSTALLED_ARTIFACT")
    if not artifact:
        pytest.skip("The packaging CI job supplies a built wheel or sdist.")
    artifact = Path(artifact).resolve()
    assert artifact.is_file(), artifact
    environment = {
        key: value
        for key, value in os.environ.items()
        if not key.startswith(("PRECHIPS_", "OTEL_"))
        and key not in {"PYTHONPATH", "PYTHONHOME", "VIRTUAL_ENV"}
    }
    environment.update(
        OTEL_SDK_DISABLED="true",
        FREECAD_CMD=str(tmp_path / "unavailable-freecad"),
        PRECHIPS_KERNEL_CACHE=str(tmp_path / "kernel-cache"),
    )
    if "PRECHIPS_KERNEL_WORKERS" in os.environ:
        environment["PRECHIPS_KERNEL_WORKERS"] = os.environ["PRECHIPS_KERNEL_WORKERS"]
    examples = copy_examples(tmp_path)
    plan = examples / "pivot-shaft" / "plan.toml"
    prefix = ["uv", "run", "--quiet", "--isolated", "--no-project", "--with", str(artifact)]

    def invoke(entry, *args):
        return subprocess.run(
            [*prefix, *entry, *map(str, args)],
            cwd=tmp_path,
            env=environment,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=180,
            check=False,
        )

    identity = invoke(
        ["python"],
        "-c",
        "import pathlib, shutil, sys, prechips; "
        "root = pathlib.Path(sys.prefix).resolve(); "
        "assert pathlib.Path(prechips.__file__).resolve().is_relative_to(root); "
        "assert pathlib.Path(shutil.which('prechips')).resolve().is_relative_to(root)",
    )
    assert identity.returncode == 0, identity.stderr

    console = ["prechips"]
    module = ["python", "-m", "prechips.cli"]
    for args, expected_code in [(("--version",), 0), (("not-a-verb",), 3)]:
        installed = invoke(console, *args)
        equivalent = invoke(module, *args)
        assert installed.returncode == equivalent.returncode == expected_code, installed.stderr
        assert installed.stdout == equivalent.stdout
        assert installed.stderr == equivalent.stderr
        if expected_code == 0:
            assert installed.stdout.startswith("prechips ")
        else:
            assert "usage" in (installed.stdout + installed.stderr).lower()

    reports = []
    travelers = []
    for name, entry in [("console", console), ("module", module)]:
        out = tmp_path / name
        result = invoke(entry, "traveler", plan, "--out", out)
        assert result.returncode == 4, result.stderr
        report_bytes = (out / "report.json").read_bytes()
        report = json.loads(report_bytes)
        assert report["hash"] == report_hash(report)
        assert report["expected_exit"] == 4
        assert report["verification"] == "planned"
        assert any(row["status"] == "unknown" for row in report["findings"])
        html = (out / "traveler.html").read_text(encoding="utf-8")
        assert html.strip()
        reports.append(report_bytes)
        travelers.append(html)
    assert reports[0] == reports[1]
    assert travelers[0] == travelers[1]


@pytest.mark.parametrize(
    ("record", "verification", "approved", "warning_count"),
    [
        ('hash = "current"\nfirst_article = "accepted"\n', "checked", True, 0),
        ('hash = "current"\nfirst_article = "  "\n', "checked", False, 1),
        ('hash = "current"\nfirst_article = "accepted"\n', "planned", False, 1),
        (
            'hash = "old"\nfirst_article = "accepted"\n'
            '[inputs]\nfeatures = "prior"\nplan = "unchanged"\n',
            "checked",
            False,
            1,
        ),
    ],
    ids=["exact", "blank-evidence", "unresolved-checks", "stale-input"],
)
def test_approval_record_cannot_waive_report_binding(
    tmp_path, record, verification, approved, warning_count
):
    path = tmp_path / "approval.toml"
    path.write_text(record, encoding="utf-8")
    report = {
        "hash": "current",
        "verification": verification,
        "inputs": {"features": {"sha256": "changed"}, "plan": {"sha256": "unchanged"}},
    }
    logs = []
    tracing = SimpleNamespace(
        span=lambda *args, **kwargs: nullcontext(),
        log=lambda severity, message: logs.append((severity, message)),
    )
    result = _read_approval(path, report, tracing)
    assert result["approved"] is approved
    assert len(result["warnings"]) == warning_count
    assert len(logs) == warning_count
    if record.startswith('hash = "old"'):
        assert "features" in result["warnings"][0]
        assert "plan" not in result["warnings"][0]


@pytest.mark.parametrize(
    "record",
    [
        '[[approvals]]\nhash = "current"\nfirst_article = "accepted"\n',
        'hash = "current"\nfirst_article = "accepted"\n[inputs.features]\nsha256 = "changed"\n',
    ],
    ids=["history-array", "nested-digest"],
)
def test_approval_record_rejects_superseded_formats(tmp_path, record):
    path = tmp_path / "approval.toml"
    path.write_text(record, encoding="utf-8")
    tracing = SimpleNamespace(span=lambda *args, **kwargs: nullcontext())
    report = {"hash": "current", "verification": "checked", "inputs": {}}
    with pytest.raises(BadInput):
        _read_approval(path, report, tracing)


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
    # Keep a complete S1 as the only setup, but remove every operation.
    plan.write_text(rocker_s1_alone(text), encoding="utf-8")
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
    plain = run_cli("check", plan, "--out", tmp_path / "plain", setup=SYNTHETIC_KERNEL)
    configured = run_cli(
        "check",
        plan,
        "--out",
        tmp_path / "configured",
        env={"OTEL_EXPORTER_OTLP_ENDPOINT": "http://127.0.0.1:9", variable: value},
        setup=SYNTHETIC_KERNEL,
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
    result = run_cli("traveler", plan, "--out", out, setup=SYNTHETIC_KERNEL + RULE_BUGS[bug])
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
    result = run_cli(
        "traveler", plan, "--out", out, setup=SYNTHETIC_KERNEL + TRAVELER_REFUSALS[refusal]
    )
    assert result.returncode == 3, result.stderr
    assert "Traceback" not in result.stderr
    # No new report beside an old traveler, no staged temporaries left behind.
    after = {path.name: path.read_bytes() for path in out.iterdir()} if out.exists() else {}
    assert after == prior


@pytest.mark.parametrize(
    ("prior_inputs", "changed"),
    [
        ("absent", "the operative bundle"),
        ("empty", "the operative bundle"),
        ("partial_unchanged", "the operative bundle"),
        ("partial_changed", "features"),
        ("unreferenced", "the operative bundle"),
    ],
)
def test_stale_approval_names_only_compared_input_changes(prior_inputs, changed, tmp_path):
    plan = copy_examples(tmp_path) / "pivot-shaft" / "plan.toml"
    plain, report, _ = traveler(plan, tmp_path / "plain", setup=SYNTHETIC_KERNEL)
    inputs = {
        "absent": "",
        "empty": "\n[inputs]\n",
        "partial_unchanged": f'\n[inputs]\nplan = "{report["inputs"]["plan"]["sha256"]}"\n',
        "partial_changed": (
            f'\n[inputs]\nplan = "{report["inputs"]["plan"]["sha256"]}"\nfeatures = "{"0" * 64}"\n'
        ),
        "unreferenced": f'\n[inputs]\nretired_asset = "{"0" * 64}"\n',
    }[prior_inputs]
    approval = tmp_path / "approvals.toml"
    approval.write_text(
        f'hash = "{"0" * 64}"\n'
        'first_article = "Synthetic regression record, not shop evidence."\n' + inputs,
        encoding="utf-8",
    )
    result, approved_report, html = traveler(
        plan, tmp_path / "stale", "--approval", approval, setup=SYNTHETIC_KERNEL
    )
    assert result.returncode == plain.returncode
    assert approved_report == report
    warning = " ".join(result.stderr.split()).split("Approval no longer matches: ", 1)[1]
    assert warning.split(" changed.", 1)[0] == changed
    assert f"Approval no longer matches: {changed} changed." in html
    assert "PLANNED" in html
    assert "CHECKED —" not in html


@pytest.mark.parametrize("json_output", [False, True], ids=["human", "json"])
@pytest.mark.parametrize(
    ("field", "value", "missing"),
    [
        ("status", "invalid", False),
        ("status", None, False),
        ("status", None, True),
        ("numbers", [], False),
        ("numbers", "not an object", False),
        ("numbers", None, False),
        ("numbers", None, True),
        ("cite", [123], False),
        ("cite", "not a citation list", False),
        ("cite", {"page": "source"}, False),
        ("cite", None, False),
        ("cite", None, True),
        ("subject", 123, False),
        ("subject", None, True),
        ("message", [], False),
        ("message", None, True),
    ],
)
def test_explain_rejects_all_malformed_matches_before_any_finding_output(
    field, value, missing, json_output, tmp_path, monkeypatch
):
    # Deliberately withdraw the kernel; completed pilots need not have missing facts.
    monkeypatch.setenv("FREECAD_CMD", str(tmp_path / "unavailable-freecadcmd"))
    plan = copy_examples(tmp_path) / "pivot-shaft" / "plan.toml"
    _, report, _ = traveler(plan, tmp_path / "plain")
    first = next(row for row in report["findings"] if row["status"] == "unknown")
    malformed = {**first, "subject": first["subject"] + ":malformed"}
    if missing:
        malformed.pop(field)
    else:
        malformed[field] = value
    # A later bad match must not emit the earlier valid finding to stdout or logs.
    report["findings"] = [first, malformed]
    report["hash"] = report_hash(report)
    path = tmp_path / "malformed.json"
    path.write_bytes(canonical_bytes(report))
    result = run_cli("explain", path, first["rule"], *(["--json"] if json_output else []))
    assert result.returncode == 3, result.stderr
    assert "Cannot explain report" in result.stderr
    assert "Traceback" not in result.stderr
    assert result.stdout == ""
    assert first["message"] not in " ".join(result.stderr.split())


@pytest.mark.parametrize("json_output", [False, True], ids=["human", "json"])
def test_explain_valid_selected_finding_keeps_structured_evidence(
    json_output, tmp_path, monkeypatch
):
    monkeypatch.setenv("FREECAD_CMD", str(tmp_path / "unavailable-freecadcmd"))
    plan = copy_examples(tmp_path) / "pivot-shaft" / "plan.toml"
    _, report, _ = traveler(plan, tmp_path / "plain")
    row = next(row for row in report["findings"] if row["status"] == "unknown")
    result = run_cli(
        "explain",
        tmp_path / "plain" / "report.json",
        f"{row['rule']}:{row['subject']}",
        *(["--json"] if json_output else []),
    )
    assert result.returncode == 0, result.stderr
    if json_output:
        assert json.loads(result.stdout) == row
    else:
        header, evidence = result.stdout.split("\n", 1)
        numbers, cite = evidence.rsplit("\nCite: ", 1)
        assert header == f"{row['rule']}:{row['subject']} — {row['status']}"
        assert json.loads(numbers) == row["numbers"]
        assert cite.rstrip("\n") == "; ".join(row["cite"])
