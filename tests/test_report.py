"""Canonical report bytes are the approval and input binding contract."""

import hashlib

import pytest

from prechips.report import canonical_bytes, report_hash


def test_canonical_report_unicode_sorted_keys_float_and_final_lf():
    report = {"z": 1.25, "hash": "stale", "a": {"é": "Ø", "hash": "input", "b": 2.0}}
    expected = (
        '{\n  "a": {\n    "b": 2.0,\n    "hash": "input",\n'
        '    "é": "Ø"\n  },\n  "z": 1.25\n}\n'
    ).encode("utf-8")
    payload = {key: value for key, value in report.items() if key != "hash"}
    assert canonical_bytes(payload) == expected
    assert report_hash(report) == hashlib.sha256(expected).hexdigest()
    assert report_hash({**report, "hash": "other"}) == report_hash(report)
    assert report_hash({**report, "z": 1.5}) != report_hash(report)
    assert report_hash({**report, "a": {**report["a"], "hash": "changed"}}) != report_hash(report)
    assert report["hash"] == "stale"


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")])
def test_nonfinite_report_numbers_are_rejected(value):
    with pytest.raises(ValueError):
        canonical_bytes({"measurement": value})
