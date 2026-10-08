"""Canonical UTF-8/LF report bytes and full input-bundle binding."""

from __future__ import annotations

import base64
import hashlib
import json
import struct
import zlib
from typing import Any

from prechips import __version__
from prechips.findings import Finding, exit_code
from prechips.inputs import Bundle


def canonical_bytes(data: Any) -> bytes:
    """Python's shortest round-trip finite float form, sorted keys, two spaces, LF."""
    return (
        json.dumps(data, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n"
    ).encode("utf-8")


def report_hash(report: dict) -> str:
    return hashlib.sha256(
        canonical_bytes({k: v for k, v in report.items() if k != "hash"})
    ).hexdigest()


def inspection_sketch_name(ordinal: int, key: str) -> str:
    """The file an inspection's set-up sketch is written to: ``key`` is the kernel's
    ``"<op>:<requirement>"``."""
    op, requirement = key.split(":", 1)
    return f"setup-S{ordinal}-op{op}-{requirement}.png"


def inspection_sketch_names(plan: dict) -> tuple[str, ...]:
    """Every inspection sketch file ``plan`` asks for (its ops' ``inspection_views``)."""
    return tuple(
        inspection_sketch_name(ordinal, f"{op['op']}:{requirement}")
        for ordinal, setup in enumerate(plan["setups"], start=1)
        for op in setup["ops"]
        if isinstance(op.get("inspection_views"), dict)
        for requirement in op["inspection_views"]
    )


def _png(encoded: str) -> bytes:
    png = base64.b64decode(encoded, validate=True)
    if not png.startswith(b"\x89PNG\r\n\x1a\n"):
        raise ValueError("The kernel returned an invalid PNG render.")
    return png


def _inspection_dimensions(png: bytes) -> tuple[int, int]:
    """Decode the RGB8, unfiltered PNG raster emitted by ``RenderCanvas.png``."""
    view = memoryview(png)
    offset = 8
    header = None
    compressed = None
    for expected in (b"IHDR", b"IDAT", b"IEND"):
        if offset + 12 > len(view):
            raise ValueError("The kernel returned an incomplete inspection PNG.")
        length = struct.unpack_from(">I", view, offset)[0]
        end = offset + 12 + length
        if (
            end > len(view)
            or view[offset + 4 : offset + 8] != expected
            or zlib.crc32(view[offset + 4 : end - 4]) != struct.unpack_from(">I", view, end - 4)[0]
        ):
            raise ValueError("The kernel returned an invalid inspection PNG chunk.")
        payload = view[offset + 8 : end - 4]
        if expected == b"IHDR":
            if length != 13:
                raise ValueError("The kernel returned an invalid inspection PNG header.")
            header = struct.unpack(">IIBBBBB", payload)
        elif expected == b"IDAT":
            compressed = payload
        elif length:
            raise ValueError("The kernel returned an invalid inspection PNG end.")
        offset = end
    if offset != len(view) or header is None or compressed is None:
        raise ValueError("The kernel returned an invalid inspection PNG.")
    width, height, *encoding = header
    if width != 1600 or height <= 0 or encoding != [8, 2, 0, 0, 0]:
        raise ValueError("The kernel returned an invalid inspection PNG geometry or encoding.")
    stride = width * 3 + 1
    expected_size = stride * height
    decoder = zlib.decompressobj()
    try:
        raster = decoder.decompress(compressed, expected_size + 1)
    except zlib.error as exc:
        raise ValueError("The kernel returned an invalid inspection PNG raster.") from exc
    if (
        len(raster) != expected_size
        or not decoder.eof
        or decoder.unused_data
        or decoder.unconsumed_tail
        or any(raster[row] != 0 for row in range(0, expected_size, stride))
    ):
        raise ValueError("The kernel returned an incomplete inspection PNG raster.")
    return width, height


def _inspection_assets(setup: dict, facts: dict) -> tuple[bytes | None, dict[str, bytes]]:
    """Validate inspection assets and their actual native parent against authored owners."""
    sketches = facts.get("inspection_pngs_base64", {})
    scenes = facts.get("inspection_scenes", {})
    if (
        not isinstance(sketches, dict)
        or not isinstance(scenes, dict)
        or sketches.keys() != scenes.keys()
    ):
        raise ValueError(f"Setup {setup['id']} inspection images and scenes have different owners.")
    if not sketches:
        return None, {}
    encoded_parent = facts.get("render_png_base64")
    if encoded_parent is None:
        raise ValueError(f"Setup {setup['id']} inspection images have no setup render.")
    try:
        parent_png = _png(encoded_parent)
    except (TypeError, ValueError) as exc:
        raise ValueError(
            f"Setup {setup['id']} inspection images have an invalid setup PNG."
        ) from exc
    authored = {
        f"{op['op']}:{requirement}": views
        for op in setup["ops"]
        if isinstance(op.get("inspection_views"), dict)
        for requirement, views in op.get("inspection_views", {}).items()
    }
    result = {}
    for key, encoded in sketches.items():
        if key not in authored:
            raise ValueError(
                f"Setup {setup['id']} has an inspection image without an authored owner."
            )
        try:
            png = _png(encoded)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"Setup {setup['id']} inspection {key} has an invalid PNG.") from exc
        width, height = _inspection_dimensions(png)
        scene = scenes[key]
        if (
            not isinstance(scene, dict)
            or type(scene.get("width_px")) is not int
            or type(scene.get("height_px")) is not int
            or scene["width_px"] != width
            or scene["height_px"] != height
        ):
            raise ValueError(
                f"Setup {setup['id']} inspection {key} dimensions do not match its PNG."
            )
        panels = scene.get("print_panels")
        views = authored[key]
        if not isinstance(panels, list) or len(panels) != len(views) or not panels:
            raise ValueError(
                f"Setup {setup['id']} inspection {key} does not cover its authored views."
            )
        next_top = 0
        for ordinal, (panel, authored_view) in enumerate(zip(panels, views, strict=True), start=1):
            if (
                not isinstance(panel, dict)
                or panel.get("role") != "inspection"
                or panel.get("label") != authored_view["title"]
                or type(panel.get("view_ordinal")) is not int
                or panel["view_ordinal"] != ordinal
                or type(panel.get("top_px")) is not int
                or panel["top_px"] != next_top
                or type(panel.get("height_px")) is not int
                or not 0 < panel["height_px"] <= 1792
                or next_top + panel["height_px"] > height
            ):
                raise ValueError(
                    f"Setup {setup['id']} inspection {key} has incomplete or unordered view bands."
                )
            next_top += panel["height_px"]
        if next_top != height:
            raise ValueError(f"Setup {setup['id']} inspection {key} view bands omit image content.")
        result[key] = png
    return parent_png, result


def render_assets(bundle: Bundle) -> dict[str, bytes]:
    """Decode only this run's kernel renders; generated assets bind to approval."""
    kernel = getattr(bundle, "kernel", None) or {}
    setups = kernel.get("setups", {})
    assets = {}
    for ordinal, setup in enumerate(bundle.plan["setups"], start=1):
        facts = setups.get(setup["id"], {})
        parent_png, sketches = _inspection_assets(setup, facts)
        encoded = facts.get("render_png_base64")
        if encoded is None:
            continue
        assets[f"setup-S{ordinal}.png"] = parent_png if parent_png is not None else _png(encoded)
        for key, png in sorted(sketches.items()):
            assets[inspection_sketch_name(ordinal, key)] = png
    return assets


def build_report(
    bundle: Bundle, findings: list[Finding], *, assets: dict[str, bytes] | None = None
) -> dict:
    result = exit_code(findings, bundle.policy, bundle)
    if assets is None:
        assets = render_assets(bundle)
    renders = {}
    kernel_setups = (getattr(bundle, "kernel", None) or {}).get("setups", {})
    inputs = dict(bundle.input_records)
    for ordinal, setup in enumerate(bundle.plan["setups"], start=1):
        facts = kernel_setups.get(setup["id"], {})
        parent_png, sketches_pngs = _inspection_assets(setup, facts)
        for key, png in sketches_pngs.items():
            name = inspection_sketch_name(ordinal, key)
            if assets.get(name) != png:
                raise ValueError(
                    f"Setup {setup['id']} inspection {key} asset differs from its PNG."
                )
        filename = f"setup-S{ordinal}.png"
        if sketches_pngs and assets.get(filename) != parent_png:
            raise ValueError(f"Setup {setup['id']} inspection parent asset differs from its PNG.")
        if filename not in assets:
            continue
        record = {"path": filename, "sha256": hashlib.sha256(assets[filename]).hexdigest()}
        inputs[f"render:{setup['id']}"] = record
        renders[setup["id"]] = {
            **record,
            "fixture": "modeled" if facts.get("fixture_rendered") is True else "unresolved",
            "scene": facts.get("render_scene", {}),
        }
        sketches = {}
        for key in sorted(sketches_pngs):
            name = inspection_sketch_name(ordinal, key)
            record = {"path": name, "sha256": hashlib.sha256(assets[name]).hexdigest()}
            sketches[key] = {**record, "scene": facts["inspection_scenes"][key]}
            inputs[f"render:{setup['id']}:{key}"] = dict(record)
        if sketches:
            renders[setup["id"]]["inspections"] = sketches
    report = {
        "expected_exit": result,
        "findings": [f.to_dict() for f in sorted(findings, key=lambda f: (f.rule, f.subject))],
        "inputs": inputs,
        "prechips_version": __version__,
        "rules_version": "m5-rev10",
        "step_sha256": bundle.features.get("step_sha256", "unknown"),
        "verification": "checked" if result == 0 else "planned",
    }
    if renders:
        report["renders"] = renders
    report["hash"] = report_hash(report)
    return report
