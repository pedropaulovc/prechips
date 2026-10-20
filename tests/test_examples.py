"""Frozen bundles must be reproduced, not consumed, by the real CLI."""

import runpy
from pathlib import Path

import pytest
from test_cli import copy_examples, traveler

ROOT = Path(__file__).resolve().parents[1]
GOLDEN_FILES = {"report.json", "traveler.html"}
# (bundle under examples/, plan, expected directory under the bundle, exit code)
PILOT_CASES = (
    ("pivot-shaft", "plan.toml", "expected", 0),
    ("rocker-arm", "plan.toml", "expected", 0),
    ("pivot-bracket", "plan.toml", "expected", 0),
    ("cone-pivot-post", "built-up.toml", "expected/built-up", 4),
)
PEDANTIC_GOLDEN_FILENAME = "traveler-pedantic.html"
PEDANTIC_GOLDEN_CASES = (
    ("blondihacks-t-nuts", "plan.toml", "expected", 0),
    ("pivot-bracket", "plan.toml", "expected", 0),
    ("rocker-arm", "plan.toml", "expected", 0),
)
STANDALONE_GOLDEN_CASES = runpy.run_path(str(ROOT / "scripts" / "validate_examples.py"))[
    "STANDALONE_CASES"
]
GEOMETRY_GOLDEN_CASES = tuple(
    (f"geometry/{part}", plan, expected, exit_code)
    for part, plan, expected, exit_code, *_ in runpy.run_path(
        str(ROOT / "scripts" / "validate_examples.py")
    )["GEOMETRY_CASES"]
)


def _assert_bundle_bytes_equal(actual, expected, comparison):
    actual_names = set(actual)
    expected_names = set(expected)
    if actual_names != expected_names:
        missing = expected_names - actual_names
        extra = actual_names - expected_names
        first_missing = repr(min(missing)[:120]) if missing else "none"
        first_extra = repr(min(extra)[:120]) if extra else "none"
        pytest.fail(
            f"{comparison}: filename sets differ; "
            f"missing={len(missing)} (first={first_missing}), "
            f"extra={len(extra)} (first={first_extra})",
            pytrace=False,
        )
    for name in sorted(expected_names):
        actual_bytes = actual[name]
        expected_bytes = expected[name]
        if actual_bytes != expected_bytes:
            offset = next(
                (
                    index
                    for index, (actual_byte, expected_byte) in enumerate(
                        zip(actual_bytes, expected_bytes, strict=False)
                    )
                    if actual_byte != expected_byte
                ),
                min(len(actual_bytes), len(expected_bytes)),
            )
            pytest.fail(
                f"{comparison}: file {name[:120]!r} differs; "
                f"actual length={len(actual_bytes)}, "
                f"expected length={len(expected_bytes)}, "
                f"first differing offset={offset} (zero-based; shorter length if prefix)",
                pytrace=False,
            )


def _outputs(out):
    return {path.name: path.read_bytes() for path in out.iterdir() if path.is_file()}


def _golden(expected):
    return {
        path.name: path.read_bytes()
        for path in expected.iterdir()
        if path.is_file() and (path.name in GOLDEN_FILES or path.suffix == ".png")
    }


@pytest.mark.parametrize(
    ("part", "plan_filename", "expected_subdir", "exit_code"),
    (*PILOT_CASES, *STANDALONE_GOLDEN_CASES),
)
def test_examples_match_reference_bytes_and_repeat(
    tmp_path,
    pilot_kernel_cache,
    part,
    plan_filename,
    expected_subdir,
    exit_code,
):
    examples = copy_examples(tmp_path)
    bundle = examples / part
    pilot_kernel_cache(bundle / plan_filename)
    outputs = []
    for run in range(2):
        out = tmp_path / f"run-{run}"
        result, report, html = traveler(bundle / plan_filename, out)
        assert result.returncode == exit_code, result.stderr
        assert report["expected_exit"] == exit_code
        outputs.append(_outputs(out))
    _assert_bundle_bytes_equal(outputs[1], outputs[0], "run-1 vs run-0")
    _assert_bundle_bytes_equal(outputs[0], _golden(bundle / expected_subdir), "run-0 vs golden")


@pytest.mark.parametrize(
    ("part", "plan_filename", "expected_subdir", "exit_code"), PEDANTIC_GOLDEN_CASES
)
def test_pedantic_examples_match_reference_bytes(
    tmp_path,
    pilot_kernel_cache,
    part,
    plan_filename,
    expected_subdir,
    exit_code,
):
    bundle = copy_examples(tmp_path) / part
    pilot_kernel_cache(bundle / plan_filename)
    out = tmp_path / "out"
    result, report, _ = traveler(bundle / plan_filename, out, "--detail", "pedantic")
    assert result.returncode == exit_code, result.stderr
    assert report["expected_exit"] == exit_code
    expected = bundle / expected_subdir
    golden = _golden(expected)
    # Only HTML changes with detail; reports, PNGs and the CLI filename set stay fixed.
    golden["traveler.html"] = (expected / PEDANTIC_GOLDEN_FILENAME).read_bytes()
    _assert_bundle_bytes_equal(_outputs(out), golden, "pedantic run vs golden")


@pytest.mark.parametrize(
    ("part", "plan_filename", "expected_subdir", "exit_code"), GEOMETRY_GOLDEN_CASES
)
def test_geometry_examples_match_reference_bytes(
    tmp_path,
    pilot_kernel_cache,
    part,
    plan_filename,
    expected_subdir,
    exit_code,
):
    """One run each: the pilots above already pin repeat-run determinism."""
    bundle = copy_examples(tmp_path) / part
    pilot_kernel_cache(bundle / plan_filename)
    out = tmp_path / "out"
    result, report, _ = traveler(bundle / plan_filename, out)
    assert result.returncode == exit_code, result.stderr
    assert report["expected_exit"] == exit_code
    _assert_bundle_bytes_equal(_outputs(out), _golden(bundle / expected_subdir), "run vs golden")


def test_every_example_golden_is_byte_compared():
    """A new example's golden needs a case above, or it can drift while CI stays green."""
    examples = ROOT / "examples"
    covered = {
        examples / part / expected
        for part, _, expected, _ in (
            *PILOT_CASES,
            *STANDALONE_GOLDEN_CASES,
            *GEOMETRY_GOLDEN_CASES,
        )
    }
    goldens = {
        path.parent
        for name in GOLDEN_FILES
        for path in examples.rglob(name)
        if any(part.startswith("expected") for part in path.relative_to(examples).parts)
    }
    uncovered = sorted(golden.relative_to(ROOT).as_posix() for golden in goldens - covered)
    assert uncovered == [], f"no byte-compare case in tests/test_examples.py for {uncovered}"


def test_every_pedantic_example_golden_is_byte_compared():
    """Sidecars require real CLI consumers, and every registered sidecar must exist."""
    examples = ROOT / "examples"
    covered = {
        examples / part / expected / PEDANTIC_GOLDEN_FILENAME
        for part, _, expected, _ in PEDANTIC_GOLDEN_CASES
    }
    assert covered, "pedantic byte-compare cases must not be empty"
    goldens = {
        path
        for path in examples.rglob(PEDANTIC_GOLDEN_FILENAME)
        if any(part.startswith("expected") for part in path.relative_to(examples).parts)
    }
    uncovered = sorted(golden.relative_to(ROOT).as_posix() for golden in goldens - covered)
    missing = sorted(golden.relative_to(ROOT).as_posix() for golden in covered - goldens)
    assert not uncovered and not missing, (
        f"pedantic byte-compare registrations differ: unregistered={uncovered}, missing={missing}"
    )
