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
    # A previous route can also have had more setups than this one.
    (out / "setup-S2.png").write_bytes(_png((120, 100, 80)))
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
