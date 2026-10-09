"""Pool workers answer the engine's independent booleans without changing a fact.

The engine hands checkpoint rows and culled cylinder booleans to ``freecadcmd`` worker
processes (``src/prechips/kernel/boolean_pool.py``). ``PRECHIPS_KERNEL_POOL_WAIT`` makes the
engine take every pooled boolean from a worker, so the same batch run with and without
workers must print the same facts while the pooled run reports worker answers. Workers
never outlive the engine, even when the host's runaway guard kills it mid-boolean, and a
worker count that is not a whole number runs no workers. Runs ``freecad_job.py`` under
``freecadcmd`` and skips without it.
"""

import ctypes
import json
import os
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest
from test_kernel_checkpoints import _AUTHOR, MITER, WEST, _bounded, _clamped, _job, _profile
from test_kernel_geometry import ENGINE, Engine

from prechips import kernel


@pytest.fixture(scope="module")
def island(tmp_path_factory, freecad_kernel):
    directory = tmp_path_factory.mktemp("pool-solids")
    script = directory / "author.py"
    script.write_text(_AUTHOR, encoding="utf-8")
    process = subprocess.run(
        [freecad_kernel, str(script), "--", str(directory)],
        capture_output=True,
        text=True,
        errors="replace",
        timeout=300,
    )
    step = directory / "island.step"
    assert step.exists(), process.stdout[-2000:] + process.stderr[-2000:]
    return step


def _facts(response):
    """The batch's results without their non-operative timing."""
    return [{k: v for k, v in result.items() if k != "timing"} for result in response["results"]]


def test_pooled_booleans_keep_every_fact_of_a_checkpointed_and_sampled_batch(
    tmp_path, freecad_kernel, island, monkeypatch
):
    engine = Engine(tmp_path, freecad_kernel)
    # A finish profile whose corner miter lies under a later press pad (rule A' judges its
    # pooled removal against the later setup) and a bounded rough profile (its rows' rough
    # leave windows); both sample the west wall, so reach and pose booleans pool too.
    miter = _profile(3.0, MITER, tip=10.0, overshoot={"S1:10 finish line -X[2]"})
    rough = _bounded([("line -X", [(1.5, 0.0), (1.5, 15.0)])])
    batch = {
        "jobs": [
            _job(engine, island, [miter], later=_clamped((2.0, 50.0)), west=WEST),
            _job(engine, island, [rough], west=WEST),
        ],
        "timing": True,
    }
    monkeypatch.setenv("PRECHIPS_KERNEL_WORKERS", "0")
    alone = engine.run(batch)
    monkeypatch.setenv("PRECHIPS_KERNEL_WORKERS", "2")
    monkeypatch.setenv("PRECHIPS_KERNEL_POOL_WAIT", "1")
    pooled = engine.run(batch)
    assert alone["timing"]["pool_answers"] == 0
    assert pooled["timing"]["pool_answers"] > 0
    assert _facts(pooled) == _facts(alone)
    errors = pooled["results"][0]["ops"]["S1:10"]["checkpoint_errors"]
    assert [error.get("later_setup") for error in errors] == ["S2"], errors


@pytest.mark.parametrize("count", ["²", "-1", "two"])
def test_a_worker_count_that_is_no_whole_number_runs_the_batch_without_workers(
    tmp_path, freecad_kernel, monkeypatch, count
):
    # "²" is a digit to str.isdigit() but no number to int(): it must not abort the run.
    monkeypatch.setenv("PRECHIPS_KERNEL_WORKERS", count)
    response = Engine(tmp_path, freecad_kernel).run({"jobs": [], "timing": True})
    assert response["results"] == []
    assert response["timing"]["pool_answers"] == 0


# The real engine with one extra pool function that blocks inside its worker, as a stuck
# OCC boolean would; the engine waits for that answer until it is killed.
_BLOCKING = r"""
import importlib.util, json, os, sys, time
from pathlib import Path

here, engine = Path(os.environ["POOL_PROBE_DIR"]), os.environ["POOL_PROBE_ENGINE"]
sys.path.insert(0, os.path.dirname(engine))
spec = importlib.util.spec_from_file_location("pool_probe_engine", engine)
job = importlib.util.module_from_spec(spec)
spec.loader.exec_module(job)
import Part


def blocked(shapes):
    (here / "worker.json").write_text(json.dumps({"pid": os.getpid()}))
    time.sleep(300)
    return (shapes[0].Volume,)


made = job._pool


def pool(*args):
    workers = made(*args)
    workers.command[1] = os.path.abspath(__file__)
    return workers


def run(payload):
    with job._ahead() as batch:
        call = batch.submit([Part.makeBox(2, 3, 4)], "blocked")
        record = {"pid": os.getpid(), "directory": job._POOL.directory}
        (here / "engine.json").write_text(json.dumps(record))
        return {"results": [], "value": job.boolean_pool.answer(call)}


job._POOL_FUNCTIONS["blocked"] = blocked
job._pool, job.run = pool, run
job.main(sys.argv)
"""


def _alive(pid):
    if sys.platform == "win32":
        api = ctypes.WinDLL("kernel32", use_last_error=True)
        api.OpenProcess.restype = ctypes.c_void_p
        api.OpenProcess.argtypes = [ctypes.c_ulong, ctypes.c_int, ctypes.c_ulong]
        api.WaitForSingleObject.argtypes = [ctypes.c_void_p, ctypes.c_ulong]
        api.CloseHandle.argtypes = [ctypes.c_void_p]
        handle = api.OpenProcess(0x00100000, False, pid)  # SYNCHRONIZE
        if not handle:
            return False
        try:
            return api.WaitForSingleObject(handle, 0) == 0x102  # WAIT_TIMEOUT: still running
        finally:
            api.CloseHandle(handle)
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    stat = Path(f"/proc/{pid}/stat")
    return not stat.exists() or stat.read_text().rsplit(")", 1)[1].split()[0] != "Z"


def _assert_process_exited(pid, message):
    # These JSON records identify a former process, not an owned live process handle.
    # A surviving (or reused) PID must fail the test, never become a cleanup target.
    assert not _alive(pid), message


def _blocking_run(tmp_path, monkeypatch):
    """The blocking engine script, with one patient worker; its pids land in ``tmp_path``."""
    script = tmp_path / "blocking.py"
    script.write_text(_BLOCKING, encoding="utf-8")
    monkeypatch.setenv("PRECHIPS_KERNEL_WORKERS", "1")
    monkeypatch.setenv("PRECHIPS_KERNEL_POOL_WAIT", "1")
    monkeypatch.setenv("POOL_PROBE_DIR", str(tmp_path))
    monkeypatch.setenv("POOL_PROBE_ENGINE", str(ENGINE))
    return script


def _assert_nothing_left(tmp_path):
    worker = json.loads((tmp_path / "worker.json").read_text())["pid"]
    engine = json.loads((tmp_path / "engine.json").read_text())
    assert worker != engine["pid"], "the engine ran the blocked boolean itself"
    directory = Path(engine["directory"])
    # Before _execute ends, the host has SIGKILLed the run's process group (POSIX) or
    # ended the engine, whose job then ends its workers (Windows); exits are asynchronous.
    deadline = time.monotonic() + 10
    while (_alive(engine["pid"]) or _alive(worker)) and time.monotonic() < deadline:
        time.sleep(0.1)
    _assert_process_exited(engine["pid"], "the host left the engine running")
    _assert_process_exited(worker, "a busy worker outlived its killed engine")
    assert not directory.exists(), f"the pool's shape files outlived the run: {directory}"


def _launch(script, launched):
    class Launch(subprocess.Popen):
        # The host's real launch, of the blocking script in place of freecad_job.py.
        def __init__(self, command, **options):
            super().__init__([command[0], str(script), *command[2:]], **options)
            launched.append(self)

    return Launch


def test_the_hosts_runaway_guard_leaves_no_worker_or_pool_file_behind(
    tmp_path, freecad_kernel, monkeypatch
):
    script = _blocking_run(tmp_path, monkeypatch)
    wait = kernel._await_launcher

    def guard(process, timeout):
        # The host's 600 s guard expiring while the worker is inside its boolean, the real
        # wait running until then. The engine is FREECAD_CMD's process or, under a launcher
        # such as the Linux AppImage's AppRun shell, that process's child.
        assert timeout == 600
        deadline = time.monotonic() + 300
        while not (tmp_path / "worker.json").exists():
            try:
                wait(process, 0.1)
            except subprocess.TimeoutExpired:
                pass
            else:
                pytest.fail("the engine ended before its worker blocked")
            assert time.monotonic() < deadline, "the worker never entered its boolean"
        raise subprocess.TimeoutExpired(process.args, timeout)

    monkeypatch.setattr(kernel.subprocess, "Popen", _launch(script, []))
    monkeypatch.setattr(kernel, "_await_launcher", guard)
    with pytest.raises(subprocess.TimeoutExpired):
        kernel._execute(freecad_kernel, {"jobs": [], "timing": True})
    monkeypatch.undo()
    _assert_nothing_left(tmp_path)


@pytest.mark.skipif(os.name != "posix", reason="a POSIX launcher and SIGINT")
def test_an_interrupted_host_leaves_nothing_behind_when_its_launcher_died_first(
    tmp_path, freecad_kernel, monkeypatch
):
    # FREECAD_CMD's process (the AppImage's AppRun shell on CI) ends on its own while the
    # engine and its busy worker run on, then the host gets Ctrl-C.
    script = _blocking_run(tmp_path, monkeypatch)
    launched = []

    def interrupt():
        deadline = time.monotonic() + 300
        while not (tmp_path / "worker.json").exists() and time.monotonic() < deadline:
            time.sleep(0.01)
        launched[0].kill()
        os.kill(os.getpid(), signal.SIGINT)

    monkeypatch.setattr(kernel.subprocess, "Popen", _launch(script, launched))
    thread = threading.Thread(target=interrupt)
    thread.start()
    with pytest.raises(KeyboardInterrupt):
        kernel._execute(freecad_kernel, {"jobs": [], "timing": True})
        thread.join(330)  # a run that already ended takes the interrupt here
        time.sleep(1)
    thread.join()
    monkeypatch.undo()
    _assert_nothing_left(tmp_path)
