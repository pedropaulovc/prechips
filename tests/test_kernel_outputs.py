"""Generated operative geometry assets participate in approval and output safety."""

import base64
import hashlib
import struct
import zlib
from dataclasses import replace
from pathlib import Path

import pytest

from prechips.cli import _output_paths, _write_outputs
from prechips.inputs import BadInput, load_bundle
from prechips.report import build_report, render_assets

ROOT = Path(__file__).resolve().parents[1]


def _png(color):
    def chunk(kind, content):
        body = kind + content
        return struct.pack(">I", len(content)) + body + struct.pack(">I", zlib.crc32(body))

    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(b"\x00" + bytes(color)))
        + chunk(b"IEND", b"")
    )


def test_render_content_changes_approval_binding_without_changing_source_inputs():
    bundle = load_bundle(ROOT / "examples/pivot-shaft/plan.toml")
    setup = bundle.plan["setups"][0]["id"]

    def rendered(color):
        png = _png(color)
        kernel = {
            "status": "ok",
            "setups": {
                setup: {
                    "render_png_base64": base64.b64encode(png).decode("ascii"),
                    "fixture_reason": "Synthetic unresolved fixture for binding regression.",
                }
            },
        }
        current = replace(bundle, kernel=kernel)
        return current, build_report(current, [])

    first, initial = rendered((80, 100, 120))
    same, repeated = rendered((80, 100, 120))
    _, changed = rendered((120, 100, 80))
    assert initial == repeated
    assert initial["hash"] != changed["hash"]
    assert first.input_records == same.input_records == bundle.input_records
    record = initial["inputs"][f"render:{setup}"]
    assert record["sha256"] == hashlib.sha256(render_assets(first)[record["path"]]).hexdigest()
    assert initial["renders"][setup]["fixture"] == "unresolved"


def test_generated_image_cannot_overwrite_an_input(tmp_path):
    image = tmp_path / "setup-S1.png"
    image.write_bytes(_png((80, 100, 120)))
    with pytest.raises(BadInput):
        _output_paths(tmp_path, ("report.json", "traveler.html", image.name), [image])
    assert image.read_bytes() == _png((80, 100, 120))
    assert not (tmp_path / "report.json").exists()


def test_refused_image_replacement_rolls_back_report_sheet_and_prior_image(tmp_path, monkeypatch):
    from contextlib import nullcontext
    from types import SimpleNamespace

    import prechips.cli as cli

    names = ("report.json", "traveler.html", "setup-S1.png")
    prior = {tmp_path / name: f"old {name}".encode() for name in names}
    for path, data in prior.items():
        path.write_bytes(data)
    original_replace = cli.os.replace

    def refuse_image(source, target):
        if target.name == "setup-S1.png" and source.name.endswith(".tmp"):
            raise OSError("Synthetic refusal replacing geometry asset")
        return original_replace(source, target)

    monkeypatch.setattr(cli.os, "replace", refuse_image)
    tracing = SimpleNamespace(span=lambda *args, **kwargs: nullcontext())
    with pytest.raises(BadInput):
        _write_outputs(
            tmp_path,
            {path: f"new {path.name}".encode() for path in prior},
            tracing,
        )
    assert {path: path.read_bytes() for path in tmp_path.iterdir()} == prior


@pytest.mark.parametrize("verb", ["traveler", "check"])
def test_kernel_absent_run_removes_stale_setup_images(tmp_path, verb):
    import json

    from test_cli import copy_examples, run_cli

    plan = copy_examples(tmp_path) / "geometry" / "pocket-reach" / "long-reach.toml"
    out = tmp_path / "out"
    out.mkdir()
    (out / "setup-S1.png").write_bytes(_png((80, 100, 120)))
    # A previous route can also have had more setups than this one, and an inspection's
    # set-up sketch.
    (out / "setup-S2.png").write_bytes(_png((120, 100, 80)))
    (out / "setup-S2-op50-position_dia.png").write_bytes(_png((100, 120, 80)))
    result = run_cli(
        verb,
        plan,
        "--out",
        out,
        env={"FREECAD_CMD": str(tmp_path / "missing-freecadcmd.exe")},
    )
    assert result.returncode == 4, result.stderr
    report = json.loads((out / "report.json").read_bytes())
    assert not report.get("renders")
    expected = {"report.json", "traveler.html"} if verb == "traveler" else {"report.json"}
    assert {path.name for path in out.iterdir()} == expected


_SKETCHED_OP = """do = "inspect"
feature = "pivot_bearing"
[setups.ops.checks]
dia = "micrometers/0-1in"
[setups.ops.inspection_methods]
dia = [
  "Read the bearing at its north end {N} and its south end {S}.",
  "Calculate: mean = (N + S) / 2 = {mean}",
  "Calculate: taper = N - S = {taper}",
]
[[setups.ops.inspection_views.dia]]
title = "ON V-BLOCKS"
up = [1.0, 0.0, 0.0]
toward = [0.0, -1.0, 0.0]
marks = [{label = "N", at_mm = [6.0, 0.0, 10.0], reads = true}]
"""


@pytest.mark.parametrize("changed", [True, False], ids=["changed-sketch", "matching-sketch"])
def test_an_inspection_sketch_is_written_bound_and_printed_on_its_worksheet(
    tmp_path, monkeypatch, changed
):
    import json

    from test_cli import copy_examples
    from test_process_route import append_op

    import prechips.cli as cli
    import prechips.kernel as kernel

    monkeypatch.setenv("OTEL_SDK_DISABLED", "true")
    plan = copy_examples(tmp_path) / "pivot-shaft" / "plan.toml"
    sid, op = append_op(plan, _SKETCHED_OP).split(":")
    sketch = _png((90, 110, 70))

    def render_bundles(bundles):
        for index, bundle in enumerate(bundles):
            facts = {
                "render_png_base64": base64.b64encode(_png((80, 100, 120))).decode("ascii"),
                "inspection_pngs_base64": {
                    f"{op}:dia": base64.b64encode(sketch).decode("ascii"),
                },
            }
            bundles[index] = replace(bundle, kernel={"status": "ok", "setups": {sid: facts}})
        return [bundle.kernel for bundle in bundles]

    monkeypatch.setattr(kernel, "run_geometries", render_bundles)
    out = tmp_path / "out"
    args = [str(plan), "--out", str(out)]
    assert cli.main(["traveler", *args]) in {0, 2, 4}
    report = json.loads((out / "report.json").read_bytes())
    ordinal = 1 + [s["id"] for s in load_bundle(plan).plan["setups"]].index(sid)
    name = f"setup-S{ordinal}-op{op}-dia.png"
    record = {"path": name, "sha256": hashlib.sha256(sketch).hexdigest()}
    assert report["renders"][sid]["inspections"] == {f"{op}:dia": record}
    assert report["inputs"][f"render:{sid}:{op}:dia"] == record
    assert (out / name).read_bytes() == sketch
    html = (out / "traveler.html").read_text(encoding="utf-8")
    # The figure heads the worksheet the check's readings are worked on.
    worksheet = html[html.index("Take each reading at its step") :]
    assert worksheet.index(f'<img src="{name}"') < worksheet.index('<ol class="steps">')
    prior_hash = report["hash"]
    if changed:
        sketch = _png((70, 110, 90))

    assert cli.main(["check", *args]) in {0, 2, 4}
    report = json.loads((out / "report.json").read_bytes())
    assert (
        report["inputs"][f"render:{sid}:{op}:dia"]["sha256"] == hashlib.sha256(sketch).hexdigest()
    )
    assert (report["hash"] != prior_hash) is changed
    assert (out / name).exists() is not changed


def test_refused_stale_image_deletion_restores_every_prior_output(tmp_path, monkeypatch):
    from contextlib import nullcontext
    from pathlib import Path
    from types import SimpleNamespace

    names = ("report.json", "traveler.html", "setup-S1.png", "setup-S2.png")
    prior = {tmp_path / name: f"old {name}".encode() for name in names}
    for path, data in prior.items():
        path.write_bytes(data)
    original_unlink = Path.unlink

    def refuse_image(path, *args, **kwargs):
        if path.name == "setup-S2.png":
            raise OSError("Synthetic refusal deleting stale geometry asset")
        return original_unlink(path, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", refuse_image)
    tracing = SimpleNamespace(span=lambda *args, **kwargs: nullcontext())
    with pytest.raises(BadInput):
        _write_outputs(
            tmp_path,
            {
                tmp_path / name: None if name.endswith(".png") else f"new {name}".encode()
                for name in names
            },
            tracing,
        )
    assert {path: path.read_bytes() for path in tmp_path.iterdir()} == prior


def test_absent_deletion_does_not_interrupt_rollback_of_earlier_outputs(tmp_path, monkeypatch):
    from contextlib import nullcontext
    from types import SimpleNamespace

    import prechips.cli as cli

    report = tmp_path / "report.json"
    report.write_bytes(b"earlier report")
    absent = tmp_path / "setup-S1.png"
    refused = tmp_path / "setup-S2.png"
    original_replace = cli.os.replace

    def refuse_image(source, target):
        if target == refused:
            raise OSError("Synthetic later output failure")
        return original_replace(source, target)

    monkeypatch.setattr(cli.os, "replace", refuse_image)
    tracing = SimpleNamespace(span=lambda *args, **kwargs: nullcontext())
    with pytest.raises(BadInput, match="Synthetic later output failure"):
        _write_outputs(
            tmp_path,
            {report: b"new report", absent: None, refused: _png((80, 100, 120))},
            tracing,
        )
    assert {path.name: path.read_bytes() for path in tmp_path.iterdir()} == {
        "report.json": b"earlier report"
    }


@pytest.mark.parametrize("changed", [True, False], ids=["changed-render", "matching-render"])
def test_check_after_traveler_removes_stale_assets_and_binds_current_render(
    tmp_path, monkeypatch, changed
):
    import json

    import prechips.cli as cli
    import prechips.kernel as kernel

    monkeypatch.setenv("OTEL_SDK_DISABLED", "true")
    current_png = _png((80, 100, 120))

    def render_bundles(bundles):
        for index, bundle in enumerate(bundles):
            rendered_kernel = {
                "status": "ok",
                "setups": {
                    bundle.plan["setups"][0]["id"]: {
                        "render_png_base64": base64.b64encode(current_png).decode("ascii"),
                        "fixture_reason": "Synthetic unresolved fixture for output regression.",
                    }
                },
            }
            bundles[index] = replace(bundle, kernel=rendered_kernel)
        return [bundle.kernel for bundle in bundles]

    monkeypatch.setattr(kernel, "run_geometries", render_bundles)
    plan = str(ROOT / "examples/pivot-shaft/plan.toml")
    args = [plan, "--out", str(tmp_path)]
    assert cli.main(["traveler", *args]) in {0, 2, 4}
    prior_report = json.loads((tmp_path / "report.json").read_bytes())
    assert (tmp_path / "traveler.html").is_file()
    prior_image = tmp_path / prior_report["inputs"]["render:S0"]["path"]
    assert prior_image.read_bytes() == current_png
    if changed:
        current_png = _png((120, 100, 80))

    assert cli.main(["check", *args]) in {0, 2, 4}
    report = json.loads((tmp_path / "report.json").read_bytes())
    assert report["inputs"]["render:S0"]["sha256"] == hashlib.sha256(current_png).hexdigest()
    if changed:
        assert report["hash"] != prior_report["hash"]
        assert not prior_image.exists()
    else:
        assert prior_image.read_bytes() == current_png
    assert not (tmp_path / "traveler.html").exists()
