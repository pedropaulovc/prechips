"""Frozen bundles must be reproduced, not consumed, by the real CLI."""

import pytest
from test_cli import copy_examples, traveler


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


@pytest.mark.parametrize(
    ("part", "plan_filename", "expected_subdir", "exit_code"),
    [
        ("pivot-shaft", "plan.toml", "expected", 0),
        ("rocker-arm", "plan.toml", "expected", 0),
        ("pivot-bracket", "plan.toml", "expected", 0),
        ("cone-pivot-post", "built-up.toml", "expected/built-up", 0),
    ],
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
        outputs.append({path.name: path.read_bytes() for path in out.iterdir() if path.is_file()})
    _assert_bundle_bytes_equal(outputs[1], outputs[0], "run-1 vs run-0")
    expected = bundle / expected_subdir
    reference = {
        path.name: path.read_bytes()
        for path in expected.iterdir()
        if path.is_file()
        and (path.name in {"report.json", "traveler.html"} or path.suffix == ".png")
    }
    _assert_bundle_bytes_equal(outputs[0], reference, "run-0 vs golden")
