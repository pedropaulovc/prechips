"""Run the tests a local change can affect; CI still runs the full suite.

    uv run scripts/affected_tests.py --base main            # select and run
    uv run scripts/affected_tests.py --base main --dry-run  # only print the selection
    uv run scripts/affected_tests.py --base main -- -x -k sheet

The selection is the union of:

* every changed ``tests/test_*.py`` module (a deleted one only through its
  importers), plus each test module that imports a changed test module
  (``from test_cli import ...``), transitively; the ``[consumers]`` and
  ``[paths]`` hits below get the same closure;
* for each changed ``src/prechips`` file, the test modules that executed it,
  from the committed map ``tests/affected_tests.toml`` (``[sources]``,
  measured per-test coverage; rebuild with ``--rebuild-map``);
* ``[consumers]``: for a changed file matching a glob, every test module whose
  source names the rule's token. The kernel's engine sources
  (``kernel.ENGINE_SOURCES``) select every ``freecad_kernel`` test: they run
  inside ``freecadcmd``, where coverage cannot see them, and they make up the
  engine digest, so any such edit re-runs geometry cold. ``cli.py`` selects
  every ``run_cli`` test, which drives the CLI as a subprocess;
* the ``[paths]`` globs for non-Python inputs (examples, goldens, scripts);
* the always-run ``keepers`` whenever anything outside ``ignore`` changed: the
  golden-example tests, which compare every pilot's CLI output byte for byte,
  plus every test module the map does
  not name yet (added since the last ``--rebuild-map``).

A ``full`` trigger (conftest, pyproject, the lock, the package version) or a
changed file that nothing above covers (a new source module) selects the full
suite, never nothing. Changes are measured from the merge base with
``--base``, plus staged, unstaged and untracked files. Tests run with
``-n 2 --dist loadscope`` and ``PRECHIPS_KERNEL_WORKERS=1`` unless the caller
set them.
"""

import argparse
import fnmatch
import functools
import os
import re
import sqlite3
import subprocess
import sys
import tempfile
import tomllib
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
TESTS = ROOT / "tests"
MAP = TESTS / "affected_tests.toml"
FULL = "FULL"
COMPLETENESS = "tests/test_affected_tests.py::test_every_tracked_source_is_in_the_map"


def git(*args):
    result = subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True, check=True)
    return [line for line in result.stdout.splitlines() if line]


def changed_files(base):
    merge_base = git("merge-base", base, "HEAD")[0]
    tracked = git("diff", "--name-only", merge_base)
    untracked = git("ls-files", "--others", "--exclude-standard")
    return sorted(set(tracked) | set(untracked))


@functools.cache
def source(module):
    return (ROOT / module).read_text("utf-8")


def test_modules():
    return sorted(path.relative_to(ROOT).as_posix() for path in TESTS.glob("test_*.py"))


@functools.cache
def importers():
    """Map each test module to the test modules that import it."""
    found = {}
    pattern = re.compile(r"^\s*(?:from|import)\s+(test_\w+)", re.MULTILINE)
    for module in test_modules():
        for name in pattern.findall(source(module)):
            found.setdefault(f"tests/{name}.py", set()).add(module)
    return found


def with_importers(selected):
    reverse = importers()
    pending = list(selected)
    while pending:
        for module in reverse.get(pending.pop(), ()):
            if module not in selected:
                selected.add(module)
                pending.append(module)
    return selected


def consumers(token):
    """Test modules whose source names ``token``: a fixture or helper that marks them as
    driving code in a subprocess, where per-test coverage cannot attribute it."""
    return {module for module in test_modules() if token in source(module)}


def matches(path, patterns):
    return any(fnmatch.fnmatchcase(path, pattern) for pattern in patterns)


def unmapped(config):
    """Test modules no map entry names: new since the last --rebuild-map, or ones whose
    tests run nothing in process. They run with every selection until the map names them."""
    named = set(config.get("keepers", []))
    for table in ("paths", "sources"):
        for modules in config.get(table, {}).values():
            named.update(modules)
    return set(test_modules()) - named


def select(changed, config):
    """Return (test modules, reasons), or (FULL, reasons) when nothing safe covers a change."""
    sources = config.get("sources", {})
    paths = config.get("paths", {})
    ignore = config.get("ignore", [])
    selected, closed, reasons = set(), set(), []
    needs_keepers = False
    for path in changed:
        if matches(path, ignore):
            continue
        needs_keepers = True
        if matches(path, config.get("full", [])):
            reasons.append(f"{path}: full-suite trigger")
            return FULL, reasons
        if re.fullmatch(r"tests/test_\w+\.py", path):
            closed.add(path)  # deleted too: its importers now fail to import it
            reasons.append(f"{path}: changed test module")
            continue
        tokens = [
            token
            for pattern, token in config.get("consumers", {}).items()
            if fnmatch.fnmatchcase(path, pattern)
        ]
        for token in tokens:
            closed |= consumers(token)
            reasons.append(f"{path}: every test module naming {token!r}")
        hits = [modules for pattern, modules in paths.items() if fnmatch.fnmatchcase(path, pattern)]
        if not (tokens or hits or path in sources):
            reasons.append(f"{path}: not in the map, running the full suite")
            return FULL, reasons
        selected.update(sources.get(path, []))
        for modules in hits:
            closed.update(modules)
            reasons.append(f"{path}: [paths] rule")
    if needs_keepers:
        selected.update(config.get("keepers", []))
        for module in sorted(unmapped(config)):
            selected.add(module)
            reasons.append(f"{module}: not in the map yet, always run")
    existing = set(test_modules())
    return sorted((selected | with_importers(closed)) & existing), reasons


def rebuild_map(pytest_args, datafile=None):
    """Record which test modules executed each source, from one full testmon run.

    Without ``datafile`` this runs the full suite under ``--testmon-noselect`` first. The
    map-completeness test is deselected: it fails until this run rewrites the map. A failing
    test still executed what it covers, so failures still rewrite the map (and are reported);
    an interrupted or broken session keeps the old one."""
    if datafile is not None:
        return write_sources(sources_from(datafile))
    with tempfile.TemporaryDirectory(prefix="prechips-affected-") as directory:
        datafile = Path(directory) / "testmondata"
        env = {**os.environ, "TESTMON_DATAFILE": str(datafile)}
        env.setdefault("PRECHIPS_KERNEL_WORKERS", "1")
        command = [sys.executable, "-m", "pytest", "--testmon-noselect", "-n", "2"]
        command += ["--dist", "loadscope", "-q", "--deselect", COMPLETENESS, *pytest_args]
        status = subprocess.run(command, cwd=ROOT, env=env).returncode
        if status not in (pytest.ExitCode.OK, pytest.ExitCode.TESTS_FAILED):
            print(f"pytest exited {status}; keeping the existing map", file=sys.stderr)
            return status
        write_sources(sources_from(datafile))
        if status:
            print("some tests failed; the map still records what they ran", file=sys.stderr)
        return status


def sources_from(datafile):
    database = sqlite3.connect(f"file:{datafile}?mode=ro", uri=True)
    rows = database.execute(
        "SELECT te.test_name, f.filename FROM test_execution te"
        " JOIN test_execution_file_fp tf ON tf.test_execution_id = te.id"
        " JOIN file_fp f ON f.id = tf.fingerprint_id"
    ).fetchall()
    database.close()
    sources = {}
    for test, filename in rows:
        if filename.startswith("src/prechips/"):
            sources.setdefault(filename, set()).add(test.split("::")[0])
    return sources


def write_sources(sources):
    text = MAP.read_text("utf-8")
    head = text.split("[sources]")[0].rstrip() + "\n\n[sources]\n"
    body = []
    for path in sorted(sources):
        modules = "".join(f'    "{module}",\n' for module in sorted(sources[path]))
        body.append(f'"{path}" = [\n{modules}]\n')
    MAP.write_text(head + "".join(body), "utf-8")
    print(f"mapped {len(sources)} source files to their test modules in {MAP.name}")
    return 0


def main():
    parser = argparse.ArgumentParser(
        description=__doc__.splitlines()[0], formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--base", default="main", help="compare against this ref's merge base")
    parser.add_argument("--dry-run", action="store_true", help="print the selection, run nothing")
    parser.add_argument(
        "--rebuild-map", action="store_true", help="regenerate [sources] from a full testmon run"
    )
    parser.add_argument(
        "--testmondata", type=Path, help="with --rebuild-map, read this existing testmon database"
    )
    parser.add_argument("pytest_args", nargs="*", help="extra pytest arguments after --")
    args = parser.parse_args()
    if args.rebuild_map:
        return rebuild_map(args.pytest_args, args.testmondata)

    config = tomllib.loads(MAP.read_text("utf-8"))
    changed = changed_files(args.base)
    selected, reasons = select(changed, config)
    for reason in reasons:
        print(reason)
    if selected == FULL:
        targets = []
        print("selected: the full suite")
    else:
        targets = selected
        print(f"selected {len(targets)} test modules from {len(changed)} changed files")
        for module in targets:
            print(f"  {module}")
        if not targets:
            print("nothing to run")
            return 0
    if args.dry_run:
        return 0
    env = {**os.environ}
    env.setdefault("PRECHIPS_KERNEL_WORKERS", "1")
    command = [sys.executable, "-m", "pytest", "-n", "2", "--dist", "loadscope", *targets]
    return subprocess.run([*command, *args.pytest_args], cwd=ROOT, env=env).returncode


if __name__ == "__main__":
    sys.exit(main())
