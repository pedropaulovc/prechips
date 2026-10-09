"""Canonical report bytes are the approval and input binding contract."""

import base64
import hashlib
import re
import tomllib
from copy import deepcopy

import pytest
from test_cli import SYNTHETIC_KERNEL, copy_examples, traveler
from test_kernel_outputs import _inspection_bundle, _png, _setup_scene
from test_sheet_ops import Markup, content

from prechips.report import build_report, canonical_bytes, render_assets, report_hash


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


def test_traveler_preserves_authored_slash_instructions(tmp_path):
    instruction = (
        "Deburr top/bottom/sides then ship; Use S1/S2/S3 pickup; 1/4-20 tap; use 1/4/20 chart"
    )
    section, field = "[[setups.ops]]", "note"
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
    operations = [
        node
        for page in pages
        for node in markup.find("operation", page)
        if node["attrs"]["data-op"] == operation_id
    ]
    notes = [node for operation in operations for node in markup.find("op-note", operation)]
    assert [content(node) for node in notes] == [instruction]
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


def test_inspection_report_preserves_pngs_source_facts_and_exact_owner_bindings(tmp_path):
    bundle, sid, key, scene, png = _inspection_bundle(tmp_path)
    other = next(setup["id"] for setup in bundle.plan["setups"] if setup["id"] != sid)
    other_png = _png((30, 60, 90))
    bundle.kernel["setups"][other] = {
        "render_png_base64": base64.b64encode(other_png).decode("ascii"),
        "render_scene": _setup_scene(),
        "stock_volume_mm3": 31.250001,
    }
    bundle.kernel["setups"][sid]["stock_volume_mm3"] = 47.1250001
    before = deepcopy(bundle.kernel)
    source_inputs = bundle.input_records
    assets = render_assets(bundle)
    report = build_report(bundle, [], assets=assets)
    ordinal = 1 + [setup["id"] for setup in bundle.plan["setups"]].index(sid)
    name = f"setup-S{ordinal}-op{key.replace(':', '-')}.png"
    record = {"path": name, "sha256": hashlib.sha256(png).hexdigest()}
    assert report["renders"][sid]["inspections"] == {key: {**record, "scene": scene}}
    assert report["inputs"][f"render:{sid}:{key}"] == record
    assert "scene" not in report["inputs"][f"render:{sid}:{key}"]
    assert assets[name] == png
    other_name = report["renders"][other]["path"]
    assert assets[other_name] == other_png
    assert report["renders"][other]["sha256"] == hashlib.sha256(other_png).hexdigest()
    assert "inspections" not in report["renders"][other]
    assert set(assets) == {name, other_name, f"setup-S{ordinal}.png"}
    assert {key: report["inputs"][key] for key in source_inputs} == source_inputs
    assert bundle.kernel == before


@pytest.mark.parametrize(
    "case",
    [
        "missing-scenes",
        "non-map-scenes",
        "extra-scene-owner",
        "unrequested-image-owner",
        "wrong-scene-owner",
        "non-map-scene",
        "zero-width",
        "negative-height",
        "mismatched-width",
        "mismatched-height",
        "boolean-dimension",
        "floating-dimension",
        "non-list-panels",
        "empty-panels",
        "omitted-view",
        "non-map-panel",
        "wrong-role",
        "missing-label",
        "inherited-holding-label",
        "reordered-labels",
        "reversed-panels",
        "wrong-ordinal",
        "boolean-ordinal",
        "gap",
        "overlap",
        "zero-band",
        "negative-band",
        "boolean-band",
        "omitted-bottom",
        "repeated-bottom",
    ],
)
def test_invalid_inspection_scenes_cannot_pass_either_report_boundary(tmp_path, case):
    bundle, sid, key, scene, _ = _inspection_bundle(tmp_path)
    assets = render_assets(bundle)
    facts = bundle.kernel["setups"][sid]
    panels = scene["print_panels"]
    if case == "missing-scenes":
        facts.pop("inspection_scenes")
    elif case == "non-map-scenes":
        facts["inspection_scenes"] = None
    elif case == "extra-scene-owner":
        facts["inspection_scenes"]["999:dia"] = deepcopy(scene)
    elif case == "unrequested-image-owner":
        facts["inspection_pngs_base64"]["999:dia"] = facts["inspection_pngs_base64"].pop(key)
        facts["inspection_scenes"]["999:dia"] = facts["inspection_scenes"].pop(key)
    elif case == "wrong-scene-owner":
        facts["inspection_scenes"]["999:dia"] = facts["inspection_scenes"].pop(key)
    elif case == "non-map-scene":
        facts["inspection_scenes"][key] = None
    elif case == "zero-width":
        scene["width_px"] = 0
    elif case == "negative-height":
        scene["height_px"] = -1024
    elif case == "mismatched-width":
        scene["width_px"] = 1599
    elif case == "mismatched-height":
        scene["height_px"] += 1
    elif case == "boolean-dimension":
        scene["width_px"] = True
    elif case == "floating-dimension":
        scene["height_px"] = 1024.0
    elif case == "non-list-panels":
        scene["print_panels"] = {"first": panels[0]}
    elif case == "empty-panels":
        scene["print_panels"] = []
    elif case == "omitted-view":
        panels.pop()
    elif case == "non-map-panel":
        panels[0] = None
    elif case == "wrong-role":
        panels[0]["role"] = "holding"
    elif case == "missing-label":
        panels[0].pop("label")
    elif case == "inherited-holding-label":
        panels[0]["label"] = "HOLDING DETAIL"
    elif case == "reordered-labels":
        panels[0]["label"], panels[1]["label"] = panels[1]["label"], panels[0]["label"]
    elif case == "reversed-panels":
        panels.reverse()
    elif case == "wrong-ordinal":
        panels[0]["view_ordinal"] = 2
    elif case == "boolean-ordinal":
        panels[0]["view_ordinal"] = True
    elif case == "gap":
        panels[1]["top_px"] += 1
    elif case == "overlap":
        panels[1]["top_px"] -= 1
    elif case == "zero-band":
        panels[0]["height_px"] = 0
    elif case == "negative-band":
        panels[0]["height_px"] = -512
    elif case == "boolean-band":
        panels[0]["height_px"] = True
    elif case == "omitted-bottom":
        panels[1]["height_px"] -= 1
    elif case == "repeated-bottom":
        panels[1]["height_px"] += 1
    with pytest.raises(ValueError):
        render_assets(bundle)
    # Callers supplying already-decoded bytes cannot bypass scene/ownership validation.
    with pytest.raises(ValueError):
        build_report(bundle, [], assets=assets)


@pytest.mark.parametrize(
    "case",
    [
        "signature-only",
        "zero-width",
        "zero-height",
        "wrong-width",
        "truncated",
        "bad-crc",
        "short-raster",
        "extra-raster",
        "invalid-base64",
    ],
)
def test_inspection_png_requires_a_real_positive_complete_decoded_raster(tmp_path, case):
    bundle, sid, key, _, png = _inspection_bundle(tmp_path)
    assets = render_assets(bundle)
    if case == "signature-only":
        png = b"\x89PNG\r\n\x1a\n"
    elif case == "zero-width":
        png = _png((90, 110, 70), width=0, height=1024)
    elif case == "zero-height":
        png = _png((90, 110, 70), width=1600, height=0)
    elif case == "wrong-width":
        png = _png((90, 110, 70), width=1599, height=1024)
    elif case == "truncated":
        png = png[:-1]
    elif case == "bad-crc":
        png = png[:16] + bytes([png[16] ^ 1]) + png[17:]
    elif case == "short-raster":
        png = _png((90, 110, 70), width=1600, height=1024, raster_height=1023)
    elif case == "extra-raster":
        png = _png((90, 110, 70), width=1600, height=1024, raster_height=1025)
    encoded = "not-base64" if case == "invalid-base64" else base64.b64encode(png).decode("ascii")
    bundle.kernel["setups"][sid]["inspection_pngs_base64"][key] = encoded
    with pytest.raises(ValueError):
        render_assets(bundle)
    with pytest.raises(ValueError):
        build_report(bundle, [], assets=assets)


@pytest.mark.parametrize("first_height", [1792, 1793])
def test_inspection_view_band_limit_uses_actual_complete_png_coverage(tmp_path, first_height):
    bundle, sid, key, scene, png = _inspection_bundle(tmp_path, first_height=first_height)
    ordinal = 1 + [setup["id"] for setup in bundle.plan["setups"]].index(sid)
    name = f"setup-S{ordinal}-op{key.replace(':', '-')}.png"
    if first_height == 1793:
        with pytest.raises(ValueError):
            render_assets(bundle)
        supplied = {
            f"setup-S{ordinal}.png": _png((80, 100, 120)),
            name: png,
        }
        with pytest.raises(ValueError):
            build_report(bundle, [], assets=supplied)
    else:
        assets = render_assets(bundle)
        report = build_report(bundle, [], assets=assets)
        assert assets[name] == png
        assert report["renders"][sid]["inspections"][key]["scene"] == scene


def test_supplied_inspection_asset_cannot_replace_the_native_png_bytes(tmp_path):
    bundle, sid, key, _, _ = _inspection_bundle(tmp_path)
    assets = render_assets(bundle)
    ordinal = 1 + [setup["id"] for setup in bundle.plan["setups"]].index(sid)
    assets[f"setup-S{ordinal}-op{key.replace(':', '-')}.png"] = _png(
        (70, 110, 90), width=1600, height=1024
    )
    with pytest.raises(ValueError):
        build_report(bundle, [], assets=assets)


def test_supplied_assets_cannot_manufacture_an_inspection_parent_absent_from_native_output(
    tmp_path,
):
    bundle, sid, _, _, _ = _inspection_bundle(tmp_path)
    supplied = render_assets(bundle)
    bundle.kernel["setups"][sid].pop("render_png_base64")
    before = deepcopy(bundle.kernel)
    # A formerly generated setup PNG is not provenance for this kernel result.
    with pytest.raises(ValueError):
        build_report(bundle, [], assets=supplied)
    with pytest.raises(ValueError):
        render_assets(bundle)
    assert bundle.kernel == before


def test_supplied_inspection_parent_must_match_this_runs_native_setup_png(tmp_path):
    bundle, sid, _, _, _ = _inspection_bundle(tmp_path)
    supplied = render_assets(bundle)
    ordinal = 1 + [setup["id"] for setup in bundle.plan["setups"]].index(sid)
    parent_name = f"setup-S{ordinal}.png"
    actual = supplied[parent_name]
    supplied[parent_name] = _png((120, 100, 80))
    with pytest.raises(ValueError):
        build_report(bundle, [], assets=supplied)
    # Refusing a stale supplied parent does not change this run's canonical image.
    assert render_assets(bundle)[parent_name] == actual


def test_noninspection_supplied_setup_asset_retains_its_existing_binding_semantics(tmp_path):
    bundle, sid, _, _, _ = _inspection_bundle(tmp_path)
    supplied = render_assets(bundle)
    facts = bundle.kernel["setups"][sid]
    facts.pop("inspection_pngs_base64")
    facts.pop("inspection_scenes")
    facts.pop("render_png_base64")
    ordinal = 1 + [setup["id"] for setup in bundle.plan["setups"]].index(sid)
    name = f"setup-S{ordinal}.png"
    report = build_report(bundle, [], assets=supplied)
    assert report["inputs"][f"render:{sid}"] == {
        "path": name,
        "sha256": hashlib.sha256(supplied[name]).hexdigest(),
    }
    assert "inspections" not in report["renders"][sid]


def test_unresolved_inspection_does_not_acquire_fake_image_geometry(tmp_path):
    bundle, sid, _, _, _ = _inspection_bundle(tmp_path)
    facts = bundle.kernel["setups"][sid]
    facts.pop("inspection_pngs_base64")
    facts.pop("inspection_scenes")
    facts["render_scene"]["render_debts"] = ["Synthetic inspection view unavailable."]
    bundle.kernel["status"] = "unknown"
    before = deepcopy(bundle.kernel)
    report = build_report(bundle, [])
    assert "inspections" not in report["renders"][sid]
    assert not any(key.startswith(f"render:{sid}:") for key in report["inputs"])
    assert bundle.kernel == before
