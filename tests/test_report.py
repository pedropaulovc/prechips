"""Canonical report bytes are the approval and input binding contract."""

import hashlib
import re
import tomllib

import pytest
from test_cli import SYNTHETIC_KERNEL, copy_examples, traveler
from test_sheet_ops import Markup, content

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

    markup = Markup(html)
    setup = tomllib.loads(plan.read_text(encoding="utf-8"))["setups"][0]
    setup_id = setup["id"]
    operation_id = str(setup["ops"][0]["op"])
    pages = [
        page
        for page in markup.find("page")
        if page["attrs"]["data-sheet"].startswith(f"SETUP {setup_id} sheet ")
    ]
    if field == "inspection_note":
        blocks = [
            node
            for page in pages
            for node in markup.find("keep", page)
            if any(
                child["parent"] is node and content(child) == "INSPECTION NOTES"
                for child in markup.nodes
            )
        ]
        notes = [
            node
            for block in blocks
            for node in markup.nodes
            if node["tag"] == "li"
            and node["parent"]["parent"] is block
            and content(node).startswith(f"{setup_id} op {operation_id}: ")
        ]
        assert [
            content(node).removeprefix(f"{setup_id} op {operation_id}: ") for node in notes
        ] == [instruction]
    elif section == "[[setups.ops]]":
        operations = [
            node
            for page in pages
            for node in markup.find("operation", page)
            if node["attrs"]["data-op"] == operation_id
        ]
        notes = [node for operation in operations for node in markup.find("op-note", operation)]
        assert [content(node) for node in notes] == [instruction]
    else:
        blocks = [node for page in pages for node in markup.find("hold-steps", page)]
        notes = [
            node
            for block in blocks
            for node in markup.nodes
            if node["tag"] == "li"
            and node["parent"]["parent"] is block
            and content(node).startswith("Note: ")
        ]
        assert [content(node).removeprefix("Note: ").removesuffix(".") for node in notes] == [
            instruction
        ]
    instruction_blocks = [
        node
        for node in markup.nodes
        if node["tag"] == "li" or "op-note" in node["attrs"].get("class", "").split()
    ]
    assert sum(content(node).count(instruction) for node in instruction_blocks) == 1
    assert all(
        repo_citation not in content(node) and url_citation not in content(node) for node in notes
    )
    assert repo_citation not in html
    assert url_citation not in html


@pytest.mark.parametrize("revision", [None, "unknown"])
def test_traveler_unconfirmed_revision_has_no_printed_or_serialized_revision(tmp_path, revision):
    examples = copy_examples(tmp_path)
    plan = examples / "pivot-shaft" / "plan.toml"
    source = plan.read_text(encoding="utf-8")
    replacement = "" if revision is None else 'revision = "unknown"'
    source, count = re.subn(r"(?m)^revision = .*$", replacement, source)
    assert count == 1
    plan.write_text(source, encoding="utf-8")

    _, _, html = traveler(plan, tmp_path / "out", setup=SYNTHETIC_KERNEL)

    markup = Markup(html)
    pages = markup.find("page")
    assert pages
    assert all(page["attrs"]["data-revision"] == "" for page in pages)
    for page in pages:
        headings = [
            node
            for node in markup.nodes
            if node["tag"] == "h1" and node["parent"] in markup.find("meta", page)
        ]
        assert len(headings) == 1
        assert content(headings[0]).endswith("REV NOT CONFIRMED")
    assert "Drawing revision not confirmed" in content(pages[0])
