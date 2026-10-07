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


def _png(color, *, width=1, height=1, raster_height=None):
    def chunk(kind, content):
        body = kind + content
        return struct.pack(">I", len(content)) + body + struct.pack(">I", zlib.crc32(body))

    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
        + chunk(
            b"IDAT",
            zlib.compress(
                (b"\x00" + bytes(color) * width)
                * (height if raster_height is None else raster_height)
            ),
        )
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

    # Use an otherwise complete plan: an unrelated holding error must not mask kernel debt.
    plan = copy_examples(tmp_path) / "pivot-shaft" / "plan.toml"
    out = tmp_path / "out"
    out.mkdir()
    (out / "setup-S1.png").write_bytes(_png((80, 100, 120)))
    # No prior setup image or inspection sketch may survive an unavailable-kernel run.
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


def _inspection_scene(first_height=512, second_height=512):
    return {
        "width_px": 1600,
        "height_px": first_height + second_height,
        "print_panels": [
            {
                "role": "inspection",
                "label": "ON V-BLOCKS",
                "view_ordinal": 1,
                "top_px": 0,
                "height_px": first_height,
            },
            {
                "role": "inspection",
                "label": "END READING",
                "view_ordinal": 2,
                "top_px": first_height,
                "height_px": second_height,
            },
        ],
    }


def _setup_scene():
    return {
        "width_px": 1,
        "height_px": 1,
        "print_panels": [
            {
                "role": "setup",
                "label": "Synthetic output-lifecycle image",
                "top_px": 0,
                "height_px": 1,
            }
        ],
    }


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
[[setups.ops.inspection_views.dia]]
title = "END READING"
up = [0.0, 1.0, 0.0]
toward = [0.0, 0.0, -1.0]
marks = [{label = "S", at_mm = [6.0, 0.0, 20.0], reads = true}]
"""


def _inspection_bundle(tmp_path, first_height=512, second_height=512):
    from test_cli import copy_examples
    from test_process_route import append_op

    plan = copy_examples(tmp_path) / "pivot-shaft" / "plan.toml"
    sid, op = append_op(plan, _SKETCHED_OP).split(":")
    key = f"{op}:dia"
    scene = _inspection_scene(first_height, second_height)
    png = _png((90, 110, 70), width=1600, height=scene["height_px"])
    facts = {
        "render_png_base64": base64.b64encode(_png((80, 100, 120))).decode("ascii"),
        "render_scene": _setup_scene(),
        "inspection_pngs_base64": {key: base64.b64encode(png).decode("ascii")},
        "inspection_scenes": {key: scene},
    }
    bundle = replace(load_bundle(plan), kernel={"status": "ok", "setups": {sid: facts}})
    return bundle, sid, key, scene, png


@pytest.mark.parametrize("changed", [True, False], ids=["changed-sketch", "matching-sketch"])
def test_an_inspection_sketch_is_written_bound_and_printed_on_its_worksheet(
    tmp_path, monkeypatch, changed
):
    import json

    from test_cli import copy_examples
    from test_process_route import append_op
    from test_sheet_ops import Markup

    import prechips.cli as cli
    import prechips.kernel as kernel

    monkeypatch.setenv("OTEL_SDK_DISABLED", "true")
    plan = copy_examples(tmp_path) / "pivot-shaft" / "plan.toml"
    sid, op = append_op(plan, _SKETCHED_OP).split(":")
    sketch = _png((90, 110, 70), width=1600, height=1024)
    scene = _inspection_scene()

    def render_bundles(bundles):
        for index, bundle in enumerate(bundles):
            facts = {
                "render_png_base64": base64.b64encode(_png((80, 100, 120))).decode("ascii"),
                "render_scene": _setup_scene(),
                "inspection_pngs_base64": {
                    f"{op}:dia": base64.b64encode(sketch).decode("ascii"),
                },
                "inspection_scenes": {f"{op}:dia": scene},
            }
            bundles[index] = replace(bundle, kernel={"status": "ok", "setups": {sid: facts}})
        return [bundle.kernel for bundle in bundles]

    monkeypatch.setattr(kernel, "run_geometries", render_bundles)
    out = tmp_path / "out"
    out.mkdir()
    unrelated = out / "operator-note.png"
    unrelated.write_bytes(b"operator-owned image")
    stale = out / "setup-S9-op900-dia.png"
    stale.write_bytes(_png((30, 60, 90)))
    args = [str(plan), "--out", str(out)]
    assert cli.main(["traveler", *args]) in {0, 2, 4}
    report = json.loads((out / "report.json").read_bytes())
    ordinal = 1 + [s["id"] for s in load_bundle(plan).plan["setups"]].index(sid)
    name = f"setup-S{ordinal}-op{op}-dia.png"
    record = {"path": name, "sha256": hashlib.sha256(sketch).hexdigest()}
    assert report["renders"][sid]["inspections"] == {f"{op}:dia": {**record, "scene": scene}}
    assert report["inputs"][f"render:{sid}:{op}:dia"] == record
    assert (out / name).read_bytes() == sketch
    assert not stale.exists()
    assert unrelated.read_bytes() == b"operator-owned image"
    html = (out / "traveler.html").read_text(encoding="utf-8")
    # Both complete authored views belong once to this check's original worksheet.
    markup = Markup(html)
    images = [
        node
        for node in markup.nodes
        if node["tag"] == "image" and node["attrs"].get("href") == name
    ]
    assert len(images) == 2
    owners = []
    for image in images:
        owner = image["parent"]
        while owner is not None and "worksheet" not in owner["attrs"].get("class", "").split():
            owner = owner["parent"]
        assert owner is not None
        assert f"{sid} op {op}" in owner["attrs"]["data-worksheet-title"]
        owners.append(owner)
    assert owners[0] is owners[1]
    windows = [image["parent"]["attrs"]["viewbox"].split() for image in images]
    assert windows == [["0", "0", "1600", "512"], ["0", "512", "1600", "512"]]
    prior_hash = report["hash"]
    if changed:
        sketch = _png((70, 110, 90), width=1600, height=1024)

    assert cli.main(["check", *args]) in {0, 2, 4}
    report = json.loads((out / "report.json").read_bytes())
    assert (
        report["inputs"][f"render:{sid}:{op}:dia"]["sha256"] == hashlib.sha256(sketch).hexdigest()
    )
    assert (report["hash"] != prior_hash) is changed
    assert (out / name).exists() is not changed
    assert unrelated.read_bytes() == b"operator-owned image"


def test_an_inspection_sketch_is_sent_with_the_cut_it_follows_in_the_route(tmp_path):
    # The kernel draws a sketch on the stock as the route stands at its inspect op: the
    # job names the last cut before it (op order, not op number), or none.
    from test_cli import copy_examples
    from test_process_route import append_op

    import prechips.kernel as kernel

    plan = copy_examples(tmp_path) / "pivot-shaft" / "plan.toml"
    sid, op = append_op(plan, _SKETCHED_OP).split(":")
    bundle = load_bundle(plan)

    def sent():
        job = kernel.build_job(bundle)
        (setup,) = [setup for setup in job["setups"] if setup["id"] == sid]
        (inspection,) = setup["render"]["inspections"]
        return [cut["subject"] for cut in setup["ops"]], inspection

    cuts, inspection = sent()
    assert cuts and inspection["op"] == int(op) and inspection["after"] == cuts[-1]
    assert "position" not in inspection
    ops = next(setup for setup in bundle.plan["setups"] if setup["id"] == sid)["ops"]
    ops.insert(0, ops.pop())
    assert sent()[1]["after"] is None


@pytest.mark.parametrize("stale", ["setup-S2.png", "setup-S2-op50-position_dia.png"])
def test_refused_stale_image_deletion_restores_every_prior_output(tmp_path, monkeypatch, stale):
    from contextlib import nullcontext
    from pathlib import Path
    from types import SimpleNamespace

    names = ("report.json", "traveler.html", "setup-S1.png", stale)
    prior = {tmp_path / name: f"old {name}".encode() for name in names}
    for path, data in prior.items():
        path.write_bytes(data)
    original_unlink = Path.unlink

    def refuse_image(path, *args, **kwargs):
        if path.name == stale:
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
                        "render_scene": {
                            "width_px": 1,
                            "height_px": 1,
                            "print_panels": [
                                {
                                    "role": "setup",
                                    "label": "Synthetic output-lifecycle image",
                                    "top_px": 0,
                                    "height_px": 1,
                                }
                            ],
                        },
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


@pytest.mark.parametrize("verb", ["traveler", "check"])
@pytest.mark.parametrize("failure", ["missing-scene", "invalid-raster", "band-gap", "wrong-owner"])
def test_invalid_inspection_output_is_exit_three_before_any_transaction_write(
    tmp_path, monkeypatch, verb, failure
):
    from copy import deepcopy

    import prechips.cli as cli
    import prechips.kernel as kernel

    monkeypatch.setenv("OTEL_SDK_DISABLED", "true")
    bundle, sid, key, scene, _ = _inspection_bundle(tmp_path)
    facts = bundle.kernel["setups"][sid]
    if failure == "missing-scene":
        facts.pop("inspection_scenes")
    elif failure == "invalid-raster":
        facts["inspection_pngs_base64"][key] = base64.b64encode(
            _png((90, 110, 70), width=1600, height=1024, raster_height=1023)
        ).decode("ascii")
    elif failure == "band-gap":
        scene["print_panels"][1]["top_px"] += 1
    else:
        facts["inspection_scenes"]["999:dia"] = facts["inspection_scenes"].pop(key)
    native = deepcopy(bundle.kernel)
    monkeypatch.setattr(cli, "load_bundle", lambda *args: bundle)
    monkeypatch.setattr(kernel, "run_geometries", lambda bundles: [bundle.kernel])
    out = tmp_path / "out"
    out.mkdir()
    names = (
        "report.json",
        "traveler.html",
        "setup-S1.png",
        "setup-S7-op900-dia.png",
        "operator-note.png",
    )
    prior = {name: f"prior {name}".encode() for name in names}
    for name, data in prior.items():
        (out / name).write_bytes(data)
    assert cli.main([verb, str(bundle.paths["plan"]), "--out", str(out)]) == 3
    assert {path.name: path.read_bytes() for path in out.iterdir()} == prior
    assert bundle.kernel == native


def test_declared_inspection_asset_collision_is_refused_before_kernel_execution(
    tmp_path, monkeypatch
):
    import prechips.cli as cli
    import prechips.kernel as kernel

    monkeypatch.setenv("OTEL_SDK_DISABLED", "true")
    bundle, sid, key, _, png = _inspection_bundle(tmp_path)
    ordinal = 1 + [setup["id"] for setup in bundle.plan["setups"]].index(sid)
    out = tmp_path / "out"
    out.mkdir()
    name = f"setup-S{ordinal}-op{key.replace(':', '-')}.png"
    image = out / name
    image.write_bytes(png)
    bundle.paths["step"] = image
    monkeypatch.setattr(cli, "load_bundle", lambda *args: bundle)

    def never_run(bundles):
        pytest.fail("The kernel ran before inspection output/input collision preflight.")

    monkeypatch.setattr(kernel, "run_geometries", never_run)
    assert cli.main(["traveler", str(bundle.paths["plan"]), "--out", str(out)]) == 3
    assert {path.name: path.read_bytes() for path in out.iterdir()} == {name: png}
