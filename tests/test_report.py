"""Canonical report bytes are the approval and input binding contract."""

import hashlib

import pytest
from test_cli import SYNTHETIC_KERNEL, copy_examples, traveler

from prechips.report import canonical_bytes, report_hash


def test_canonical_report_unicode_sorted_keys_float_and_final_lf():
    report = {"z": 1.25, "hash": "stale", "a": {"é": "Ø", "hash": "input", "b": 2.0}}
    expected = (
        '{\n  "a": {\n    "b": 2.0,\n    "hash": "input",\n    "é": "Ø"\n  },\n  "z": 1.25\n}\n'
    ).encode()
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


@pytest.mark.parametrize(
    "instruction",
    [
        "Deburr top/bottom/sides then ship",
        "Use S1/S2/S3 pickup",
        "1/4-20 tap; use 1/4/20 chart",
    ],
)
@pytest.mark.parametrize(
    ("section", "field"),
    [
        ("[[setups.ops]]", "note"),
        ("[[setups.ops]]", "inspection_note"),
        ("[setups.hold]", "note"),
    ],
)
def test_traveler_preserves_authored_slash_instructions(tmp_path, instruction, section, field):
    examples = copy_examples(tmp_path)
    plan = examples / "rocker-arm" / "plan.toml"
    before, marker, remainder = plan.read_text(encoding="utf-8").partition(section)
    assert marker
    contents, next_section, after = remainder.partition("\n[")
    lines = [line for line in contents.splitlines() if not line.startswith(f"{field} =")]
    repo_citation = "src/prechips/slash-fidelity.py:123"
    url_citation = "https://example.invalid/slash-fidelity"
    lines.append(f'{field} = "{instruction} {repo_citation} {url_citation}"')
    plan.write_text(
        before + marker + "\n".join(lines) + "\n" + next_section + after,
        encoding="utf-8",
    )

    _, _, html = traveler(plan, tmp_path / "out", setup=SYNTHETIC_KERNEL)

    assert instruction in html
    assert repo_citation not in html
    assert url_citation not in html
