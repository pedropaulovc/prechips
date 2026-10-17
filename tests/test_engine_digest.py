"""The geometry cache's engine identity covers exactly the sources freecadcmd executes.

Host-only kernel modules stay out of the digest; whatever they change in the job the
engine receives changes the cache key through the job itself.
"""

import ast
import hashlib
import shutil
from copy import deepcopy
from pathlib import Path

import pytest
from test_provenance_kernel import prepared_bundle

from prechips import kernel

KERNEL = Path(kernel.__file__).parent


def _sources(base, dotted):
    """Kernel files that importing ``dotted`` from ``base`` loads: each module or package
    ``__init__`` along the dotted path, flat (``step_faces``) or nested (``engine.job``)."""
    found = set()
    directory = base
    for part in dotted.split("."):
        for candidate in (directory / f"{part}.py", directory / part / "__init__.py"):
            if candidate.is_file() and candidate.is_relative_to(KERNEL):
                found.add(candidate.relative_to(KERNEL).as_posix())
        directory = directory / part
    return found


def _local_imports(path):
    """Kernel files ``path`` imports, at any depth of its syntax tree. The engine runs
    with the kernel directory on ``sys.path``, so absolute names resolve against it."""
    found = set()
    for node in ast.walk(ast.parse(path.read_bytes())):
        if isinstance(node, ast.Import):
            for alias in node.names:
                found |= _sources(KERNEL, alias.name)
        if not isinstance(node, ast.ImportFrom):
            continue
        base = KERNEL if node.level == 0 else path.parents[node.level - 1]
        module = node.module or ""
        found |= _sources(base, module) if module else set()
        for alias in node.names:
            found |= _sources(base, f"{module}.{alias.name}".lstrip("."))
    return found


def _engine_closure():
    seen = set()
    pending = ["freecad_job.py"]
    while pending:
        name = pending.pop()
        if name in seen:
            continue
        seen.add(name)
        pending.extend(_local_imports(KERNEL / name) - seen)
    return seen


def test_engine_sources_cover_every_module_the_engine_imports():
    missing = _engine_closure() - set(kernel.ENGINE_SOURCES)
    assert not missing, f"freecad_job.py imports {sorted(missing)} outside the engine digest"


def test_every_engine_source_is_imported_by_the_engine():
    extra = set(kernel.ENGINE_SOURCES) - _engine_closure()
    assert not extra, f"{sorted(extra)} key the geometry cache but freecadcmd never runs them"


@pytest.fixture
def kernel_copy(tmp_path):
    root = tmp_path / "kernel"
    shutil.copytree(KERNEL, root, ignore=shutil.ignore_patterns("__pycache__"))
    return root


def _edit(path):
    path.write_bytes(path.read_bytes() + b"\n# edited\n")


def test_host_only_kernel_edits_keep_the_engine_digest(kernel_copy):
    before = kernel._engine_digest(kernel_copy)
    host = sorted(path.relative_to(kernel_copy).as_posix() for path in kernel_copy.rglob("*.py"))
    host = [name for name in host if name not in kernel.ENGINE_SOURCES]
    assert "__init__.py" in host
    for name in host:
        _edit(kernel_copy / name)
    (kernel_copy / "new_host_module.py").write_text("VALUE = 1\n", encoding="utf-8")
    assert kernel._engine_digest(kernel_copy) == before


@pytest.mark.parametrize("name", kernel.ENGINE_SOURCES)
def test_every_engine_source_edit_moves_the_engine_digest(kernel_copy, name):
    before = kernel._engine_digest(kernel_copy)
    _edit(kernel_copy / name)
    assert kernel._engine_digest(kernel_copy) != before


def test_cache_key_covers_exactly_the_job_the_engine_receives(tmp_path, monkeypatch):
    # A host-side change that alters the job alters its key, digest or not.
    data = prepared_bundle(tmp_path)
    step = tmp_path / "part.STEP"
    step.write_bytes(b"cache identity specimen")
    data.paths["step"] = step
    data.features["step_sha256"] = hashlib.sha256(step.read_bytes()).hexdigest()
    object.__setattr__(data, "kernel", None)
    executable = tmp_path / "native-boundary"
    executable.write_bytes(b"counted native boundary")
    cache = tmp_path / "cache"
    monkeypatch.setenv("PRECHIPS_KERNEL_CACHE", str(cache))
    monkeypatch.setattr(kernel, "discover_kernel", lambda: executable)
    sent = []

    def execute(command, request):
        sent.extend(deepcopy(request["jobs"]))
        return {"results": [{"status": "ok"} for _ in request["jobs"]]}

    def run():
        fresh = deepcopy(data)
        object.__setattr__(fresh, "kernel", None)
        kernel.run_geometry(fresh)

    monkeypatch.setattr(kernel, "_execute", execute)
    run()
    assert len(sent) == 1
    identity = {
        "job": kernel._cache_recipe(sent[0]),
        "engine": kernel._engine_digest(),
        "kernel": kernel._kernel_identity(executable),
    }
    key = hashlib.sha256(kernel._json(identity).encode()).hexdigest()
    assert [path.name for path in cache.glob("*.json")] == [key + ".json"]

    original = kernel.engine_job

    def host_change(job):
        changed = original(job)
        changed["setups"][0]["ops"][0]["host_side_change"] = 1
        return changed

    monkeypatch.setattr(kernel, "engine_job", host_change)
    run()
    assert len(sent) == 2
    assert sent[1]["setups"][0]["ops"][0]["host_side_change"] == 1
    monkeypatch.setattr(kernel, "engine_job", original)
    run()
    assert len(sent) == 2
