"""Every kernel ``error`` names its reason (issue #329).

The host runs FreeCAD once per batch (``kernel._execute`` through ``kernel._run_kernel``).
Whatever ends that run, the runaway guard, a signal, an exit without a result file, an
empty or non-JSON result, or an engine error that names no reason, the result is
``status: "error"`` with a specific, non-empty reason, and the engine's progress trail
says which phase it was in. ``_run_kernel`` is faked here, so no FreeCAD is needed, except
for the last test, which runs the real engine.
"""

import hashlib
import json
import subprocess
from copy import deepcopy
from pathlib import Path

import pytest
from test_provenance_kernel import prepared_bundle

from prechips import kernel

TRAIL = [
    {"at": "batch", "event": "enter", "ms": 1.0},
    {"at": "batch/job 0", "event": "enter", "ms": 2.0},
    {"at": "batch/job 0/S1", "event": "enter", "ms": 3.0},
    {"at": "batch/job 0/S1/fixture", "event": "enter", "ms": 4.0},
    {"at": "batch/job 0/S1/fixture", "event": "exit", "ms": 1500.0, "wall_ms": 1496.0},
    {"at": "batch/job 0/S1/stock_states", "event": "enter", "ms": 1600.0},
]


def _fake(monkeypatch, *, code=0, output=None, stdout="", stderr="", trail=None, raises=None):
    """``_run_kernel`` replaced by a run that writes ``output`` (text) and ``trail`` (marks,
    the last one cut short as a kill would) where the engine would, then ends as asked."""

    def run(command):
        target = Path(command[-1])
        if trail is not None:
            lines = [json.dumps(mark) for mark in trail]
            Path(str(target) + ".trail").write_text("\n".join(lines) + '\n{"at": "bat')
        if output is not None:
            target.write_text(output, encoding="utf-8")
        if raises is not None:
            raise raises
        return subprocess.CompletedProcess(command, code, stdout, stderr)

    monkeypatch.setattr(kernel, "_run_kernel", run)


def _execute():
    result = kernel._execute(Path("freecadcmd"), {"jobs": [{}], "timing": True})
    assert result["status"] == "error"
    assert isinstance(result["reason"], str) and result["reason"].strip()
    return result


def test_the_runaway_guard_names_itself_the_open_phase_and_the_engine_output(monkeypatch):
    expired = subprocess.TimeoutExpired(["freecadcmd"], 600, output="", stderr="last words")
    _fake(monkeypatch, trail=TRAIL, raises=expired)
    result = _execute()
    assert "600 s runaway guard" in result["reason"]
    assert "batch/job 0/S1/stock_states" in result["reason"]
    assert "last words" in result["reason"]
    trail = result["timing"]["trail"]
    assert trail["open"][-1] == {"at": "batch/job 0/S1/stock_states", "entered_ms": 1600.0}
    assert trail["finished"] == [{"at": "batch/job 0/S1/fixture", "wall_ms": 1496.0, "ms": 1500.0}]
    assert result["timing"]["host_wall_ms"] >= 0


@pytest.mark.parametrize(
    ("code", "says"),
    [
        (137, "exited 137: killed by SIGKILL"),  # a launcher shell's 128 + 9
        (-9, "exited -9: killed by SIGKILL"),
        (1, "exited 1"),
    ],
)
def test_a_nonzero_exit_names_its_signal_even_with_no_output(monkeypatch, code, says):
    _fake(monkeypatch, code=code)
    reason = _execute()["reason"]
    assert says in reason
    assert "no stderr or stdout output" in reason
    assert "recorded no progress" in reason


def test_a_nonzero_exit_quotes_the_tail_of_a_long_stderr(monkeypatch):
    _fake(monkeypatch, code=1, stderr="x" * 5000 + "Traceback end: MemoryError")
    reason = _execute()["reason"]
    assert reason.endswith("Traceback end: MemoryError")
    assert len(reason) < kernel.OUTPUT_TAIL + 200


def test_an_exit_without_a_result_file_says_so(monkeypatch):
    _fake(monkeypatch, stdout="Exception while processing file", trail=TRAIL)
    reason = _execute()["reason"]
    assert "without writing its result file" in reason
    assert "Exception while processing file" in reason
    assert "batch/job 0/S1/stock_states" in reason


def test_an_empty_result_file_says_so(monkeypatch):
    _fake(monkeypatch, output="")
    assert "empty result file" in _execute()["reason"]


def test_a_result_file_that_is_not_utf8_says_so(monkeypatch):
    def run(command):
        Path(command[-1]).write_bytes(b'{"results": ["\xff\xfe"]}')
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(kernel, "_run_kernel", run)
    assert "result file is unreadable" in _execute()["reason"]


def test_a_result_that_is_not_json_says_so(monkeypatch):
    _fake(monkeypatch, output='{"results": [')
    assert "did not return valid JSON" in _execute()["reason"]


def test_an_invalid_batch_contract_says_so(monkeypatch):
    _fake(monkeypatch, output='{"results": "none"}')
    assert "invalid batch result contract" in _execute()["reason"]


@pytest.mark.parametrize("reason", [None, "", "  "])
def test_an_engine_batch_error_without_a_reason_gets_one(monkeypatch, reason):
    error = {"status": "error"} if reason is None else {"status": "error", "reason": reason}
    _fake(monkeypatch, output=json.dumps(error))
    assert "batch error without a reason" in _execute()["reason"]


def test_an_engine_batch_error_keeps_its_reason_and_gains_the_hosts_diagnostics(monkeypatch):
    error = {"status": "error", "reason": "kernel batch failed: OSError: pool"}
    _fake(monkeypatch, output=json.dumps(error), stderr="pool start-up noise", trail=TRAIL)
    result = _execute()
    assert result["reason"].startswith("kernel batch failed: OSError: pool; ")
    assert "batch/job 0/S1/stock_states" in result["reason"]
    assert "pool start-up noise" in result["reason"]
    assert result["timing"]["trail"]["open"]
    assert result["timing"]["host_wall_ms"] >= 0


def test_an_engine_job_error_without_a_reason_gets_one(monkeypatch):
    results = [{"status": "ok"}, {"status": "error"}, {"status": "error", "reason": "kept"}]
    _fake(monkeypatch, output=json.dumps({"results": results, "timing": {"wall_ms": 1.0}}))
    result = kernel._execute(Path("freecadcmd"), {"jobs": [{}, {}, {}], "timing": True})
    assert result["results"][0] == {"status": "ok"}
    assert "job 1 as an error without a reason" in result["results"][1]["reason"]
    assert result["results"][2]["reason"] == "kept"
    assert result["timing"]["host_wall_ms"] >= 0


def test_the_reason_reaches_the_bundle(tmp_path, monkeypatch):
    bundle = prepared_bundle(tmp_path)
    step = tmp_path / "part.STEP"
    step.write_bytes(b"error reason specimen")
    bundle.paths["step"] = step
    bundle.features["step_sha256"] = hashlib.sha256(step.read_bytes()).hexdigest()
    object.__setattr__(bundle, "kernel", None)
    monkeypatch.setenv("PRECHIPS_KERNEL_CACHE", str(tmp_path / "cache"))
    executable = tmp_path / "freecadcmd"
    executable.write_bytes(b"fake kernel")
    monkeypatch.setattr(kernel, "discover_kernel", lambda: executable)
    _fake(monkeypatch, code=137, trail=TRAIL)
    facts = kernel.run_geometry(deepcopy(bundle))
    assert facts["status"] == "error"
    assert "killed by SIGKILL" in facts["reason"]
    assert "batch/job 0/S1/stock_states" in facts["reason"]
    assert facts["timing"]["trail"]["open"]
    # A failed run is never cached: the next run executes again.
    assert not list((tmp_path / "cache").glob("*.json"))


def test_the_real_engine_names_a_failed_job_and_leaves_its_trail(tmp_path, freecad_kernel):
    source, target = tmp_path / "input.json", tmp_path / "output.json"
    job = {"version": 1, "step_path": str(tmp_path / "absent.STEP"), "step_sha256": "0" * 64}
    source.write_text(json.dumps({"jobs": [job], "timing": True}), encoding="utf-8")
    script = Path(kernel.__file__).with_name("freecad_job.py")
    subprocess.run(
        [freecad_kernel, str(script), "--", str(source), str(target)],
        capture_output=True,
        timeout=300,
        check=True,
    )
    (result,) = json.loads(target.read_text(encoding="utf-8"))["results"]
    assert result["status"] == "error"
    assert result["reason"].startswith("FileNotFoundError: ")
    assert " at freecad_job.py:" in result["reason"]
    marks = [json.loads(line) for line in Path(str(target) + ".trail").read_text().splitlines()]
    assert [(mark["at"], mark["event"]) for mark in marks] == [
        ("batch", "enter"),
        ("batch/job 0", "enter"),
        ("batch/job 0", "exit"),
        ("batch", "exit"),
    ]
