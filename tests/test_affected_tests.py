"""scripts/affected_tests.py: local selection never silently drops a changed file."""

import runpy
import subprocess
from pathlib import Path

from prechips import kernel

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = runpy.run_path(str(ROOT / "scripts" / "affected_tests.py"))
SELECT = SCRIPT["select"]
FULL = SCRIPT["FULL"]
CONFIG = SCRIPT["tomllib"].loads(SCRIPT["MAP"].read_text("utf-8"))


def tracked(pattern):
    result = subprocess.run(
        ["git", "ls-files", pattern], cwd=ROOT, capture_output=True, text=True, check=True
    )
    return result.stdout.split()


def test_every_tracked_source_is_in_the_map():
    """Locally an unmapped source falls back to the full suite; here it fails, so the map
    cannot rot. Fix by listing the new source in [sources] with the test modules that
    exercise it, or regenerate them with `uv run scripts/affected_tests.py --rebuild-map`."""
    unmapped = []
    for source in tracked("src/prechips"):
        selected, reasons = SELECT([source], CONFIG)
        if selected == FULL and not any("full-suite trigger" in r for r in reasons):
            unmapped.append(source)
            continue
        assert selected == FULL or selected, (source, reasons)
    assert unmapped == [], "not in tests/affected_tests.toml; see this test's docstring"


def test_every_mapped_module_exists():
    named = set(CONFIG["keepers"])
    for table in ("paths", "sources"):
        for modules in CONFIG[table].values():
            named.update(modules)
    assert sorted(module for module in named if not (ROOT / module).is_file()) == []


def test_an_unmapped_file_selects_the_full_suite():
    selected, reasons = SELECT(["src/prechips/brand_new_module.py"], CONFIG)
    assert selected == FULL
    assert "not in the map" in reasons[-1]


def test_docs_only_select_nothing():
    assert SELECT(["README.md", "docs/plan.md"], CONFIG) == ([], [])


def test_a_changed_helper_module_selects_its_importers_and_the_keepers():
    selected, _ = SELECT(["tests/test_cli.py"], CONFIG)
    assert {"tests/test_cli.py", "tests/test_examples.py", "tests/test_compare_m2.py"} <= set(
        selected
    )


def test_a_kernel_source_selects_every_real_kernel_test():
    selected, _ = SELECT(["src/prechips/kernel/freecad_job.py"], CONFIG)
    consumers = SCRIPT["consumers"]("freecad_kernel")
    assert "tests/test_kernel_guard_frames.py" in consumers
    assert consumers <= set(selected)


def test_a_module_the_map_does_not_name_runs_with_every_selection():
    config = {**CONFIG, "sources": {"src/prechips/sheet.py": ["tests/test_sheet_ops.py"]}}
    selected, reasons = SELECT(["src/prechips/sheet.py"], config)
    assert {"tests/test_sheet_ops.py", "tests/test_kernel_strap_batch.py"} <= set(selected)
    assert any("not in the map yet" in reason for reason in reasons)


def test_a_cli_change_selects_every_subprocess_cli_test():
    selected, _ = SELECT(["src/prechips/cli.py"], CONFIG)
    assert SCRIPT["consumers"]("run_cli(") <= set(selected)
    assert "tests/test_input_contracts.py" in selected


def test_every_engine_source_selects_every_real_kernel_test():
    engine = {
        path.removeprefix("src/prechips/kernel/")
        for path, token in CONFIG["consumers"].items()
        if token == "freecad_kernel"
    }
    assert engine == set(kernel.ENGINE_SOURCES)
