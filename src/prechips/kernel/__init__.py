"""One local FreeCAD job per bundle; only verified, explicit dimensions enter it."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import tempfile
from contextlib import nullcontext
from pathlib import Path

from prechips.rules.resolution import (
    WORKHOLDING_CATEGORIES,
    inventory_category,
    length_mm,
    measured,
    number,
    record,
    resolve,
)

UNKNOWN = "unknown"
_INSTALLED = Path("C:/Users/pedro/AppData/Local/Programs/FreeCAD 1.1/bin/freecadcmd.exe")


def _json(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def discover_kernel():
    """An explicit override is authoritative, including an unavailable override."""
    override = os.environ.get("FREECAD_CMD")
    if override:
        path = Path(override)
        return path.resolve() if path.is_file() else shutil.which(override)
    if _INSTALLED.is_file():
        return _INSTALLED
    return (
        shutil.which("freecadcmd.exe") or shutil.which("FreeCADCmd") or shutil.which("freecadcmd")
    )


def op_inputs(bundle, setup, op, finishing=None):
    from prechips.rules.geometry_common import finishing_subjects

    subject = f"{setup['id']}:{op['op']}"
    tool = resolve(bundle, "tools", op.get("tool"))
    holder = resolve(bundle, "holders", op.get("holder"))
    values = {
        "radius_mm": measured(tool, length_mm(tool, "dia")) if tool else UNKNOWN,
        "flute_len_mm": measured(tool, length_mm(tool, "flute_len")) if tool else UNKNOWN,
        "oal_mm": measured(tool, length_mm(tool, "oal")) if tool else UNKNOWN,
        "holder_radius_mm": measured(holder, length_mm(holder, "gauge_dia")) if holder else UNKNOWN,
        "holder_gauge_len_mm": measured(holder, length_mm(holder, "gauge_len"))
        if holder
        else UNKNOWN,
    }
    projection = measured(tool, length_mm(tool, "projection")) if tool else UNKNOWN
    if not number(projection):
        grip = measured(holder, length_mm(holder, "grip")) if holder else UNKNOWN
        projection = (
            values["oal_mm"] - grip if number(values["oal_mm"]) and number(grip) else UNKNOWN
        )
    values["projection_mm"] = projection
    for key in ("radius_mm", "holder_radius_mm"):
        if number(values[key]):
            values[key] /= 2
    result = {
        "subject": subject,
        "feature": op.get("feature", UNKNOWN),
        "do": op.get("do", UNKNOWN),
        "finishing": subject in (finishing_subjects(bundle) if finishing is None else finishing),
    }
    if "faces" in op:
        result["faces"] = op["faces"]
    units = bundle.features.get("units", UNKNOWN)
    scale = {"mm": 1.0, "in": 25.4}.get(units)
    if "to_z" in op:
        # The op's floor in its setup frame bounds the material it removes from the stock.
        result["to_z"] = op["to_z"] * scale if number(op["to_z"]) and scale else UNKNOWN
    if "stock_removal_bounds" in op:
        result["stock_removal_bounds"] = removal_bounds(op["stock_removal_bounds"], units)
    missing = []
    for key, value in values.items():
        if number(value) and value > 0:
            result[key] = value
        else:
            missing.append(key)
    if missing:
        result["reason"] = (
            "Selected tool/holder dimensions unmeasured or unavailable: " + ", ".join(missing)
        )
    return result


def removal_bounds(bounds, units):
    """An op's declared setup-frame clearing box in mm, or why it is not one."""
    scale = {"mm": 1.0, "in": 25.4}.get(units)
    if scale is None:
        return {"reason": f"stock_removal_bounds units {units!r} are not mm or in"}
    bounds = record(bounds)
    result, bad = {}, []
    for axis in ("x", "y", "z"):
        span = bounds.get(axis, UNKNOWN)
        if (
            isinstance(span, list)
            and len(span) == 2
            and all(number(v) for v in span)
            and span[0] < span[1]
        ):
            result[axis] = [span[0] * scale, span[1] * scale]
        else:
            bad.append(axis)
    if bad:
        return {
            "reason": "stock_removal_bounds "
            + ", ".join(bad)
            + " not a numeric [lo, hi] span with lo < hi"
        }
    return result


def hold_inputs(bundle, setup):
    hold = record(setup.get("hold"))
    category = inventory_category(bundle, hold.get("fixture"), WORKHOLDING_CATEGORIES)
    fixture = resolve(bundle, category, hold.get("fixture")) if category else None
    kind = record(fixture).get("kind", UNKNOWN)
    result = {"kind": kind, "method": hold.get("method", UNKNOWN)}
    if kind != "vise":
        result["reason"] = "Fixture solids are not declared for this holding kind."
        return result
    missing = []
    for key in ("fixed_jaw", "jaws_along"):
        value = hold.get(key, UNKNOWN)
        result[key] = value
        if value == UNKNOWN:
            missing.append(key)
    for key in ("grip_mm", "jaw_above_parallels_mm"):
        value = hold.get(key, UNKNOWN)
        if hold.get(key + "_verify") is not False and key + "_verify" in hold:
            value = UNKNOWN
        if number(value) and value > 0:
            result[key] = value
        elif key == "jaw_above_parallels_mm" and value == 0:
            result[key] = value
        else:
            missing.append(key)
    centre = hold.get("jaw_center_along_mm", UNKNOWN)
    if number(centre):
        result["jaw_center_along_mm"] = centre
    centres = hold.get("parallels_centres_mm", UNKNOWN)
    if (
        isinstance(centres, list)
        and len(centres) == 2
        and all(
            isinstance(point, list) and len(point) == 2 and all(number(value) for value in point)
            for point in centres
        )
    ):
        result["parallels_centres_mm"] = centres
    for key in ("jaw_height", "jaw_width", "jaw_depth", "opening"):
        value = measured(fixture, length_mm(fixture, key))
        if number(value) and value > 0:
            result[key + "_mm"] = value
        else:
            missing.append(key + "_mm")
    parallels = resolve(bundle, "fixtures", hold.get("parallels"))
    height = measured(parallels, length_mm(parallels, "height")) if parallels else UNKNOWN
    if number(height) and height > 0:
        result["parallels_height_mm"] = height
    else:
        missing.append("parallels_height_mm")
    for dimension in ("length", "width"):
        value = measured(parallels, length_mm(parallels, dimension)) if parallels else UNKNOWN
        if number(value) and value > 0:
            result["parallels_" + dimension + "_mm"] = value
    if missing:
        result["reason"] = "Fixture pose/dimensions unmeasured or unavailable: " + ", ".join(
            missing
        )
    return result


def build_job(bundle):
    from prechips.rules.geometry_common import cutting_action, finishing_subjects

    units = bundle.features.get("units", UNKNOWN)
    frames = record(bundle.features.get("frames"))
    setups = []
    finishing = finishing_subjects(bundle)
    for setup in bundle.plan["setups"]:
        frame = record(frames.get(setup.get("frame")))
        transformed = {key: frame.get(key, UNKNOWN) for key in ("origin", "x", "y", "z")}
        if units not in {"mm", "in"} or not all(
            isinstance(value, list) and len(value) == 3 and all(number(v) for v in value)
            for value in transformed.values()
        ):
            transformed = UNKNOWN
        elif units == "in":
            transformed["origin"] = [value * 25.4 for value in transformed["origin"]]
        setups.append(
            {
                "id": setup["id"],
                "frame": transformed,
                "hold": hold_inputs(bundle, setup),
                "ops": [
                    op_inputs(bundle, setup, op, finishing)
                    for op in setup["ops"]
                    if cutting_action(op) is not False
                ],
                "stock_in": setup.get("stock_in", UNKNOWN),
            }
        )
    return {
        "version": 1,
        "step_path": str(Path(bundle.paths["step"]).resolve())
        if "step" in bundle.paths
        else UNKNOWN,
        "step_sha256": bundle.features.get("step_sha256", UNKNOWN),
        "features": {
            name: feature.get("faces", UNKNOWN)
            for name, feature in bundle.features["features"].items()
        },
        "as_is_faces": record(bundle.plan.get("stock")).get("as_is_faces", UNKNOWN),
        "stock": stock_inputs(bundle),
        "setups": setups,
    }


def _vector(value):
    return isinstance(value, list) and len(value) == 3 and all(number(v) for v in value)


def stock_inputs(bundle):
    """The authored supplied-stock envelope in model mm, or why it cannot be built."""
    stock = record(bundle.plan.get("stock"))
    if not stock:
        return {"reason": "plan stock is unknown; in-process stock cannot be derived"}
    components = stock.get("components", UNKNOWN)
    if isinstance(components, list) and components:
        return {"reason": "built-up stock components are not one authored stock envelope"}
    section, dia = stock.get("section_mm", UNKNOWN), stock.get("dia_mm", UNKNOWN)
    if section != UNKNOWN and dia != UNKNOWN:
        return {"reason": "stock declares both section_mm and dia_mm; its envelope is ambiguous"}
    shape = "box" if section != UNKNOWN else "round" if dia != UNKNOWN else None
    if shape is None:
        return {"reason": "stock declares neither section_mm nor dia_mm; no envelope is authored"}
    result = {"shape": shape}
    missing = []
    length = stock.get("length_mm", UNKNOWN)
    if number(length) and length > 0:
        result["length_mm"] = length
    else:
        missing.append("length_mm")
    if shape == "box":
        if isinstance(section, list) and len(section) == 2 and all(
            number(v) and v > 0 for v in section
        ):
            result["section_mm"] = section
        else:
            missing.append("section_mm")
    elif number(dia) and dia > 0:
        result["dia_mm"] = dia
    else:
        missing.append("dia_mm")
    for key in ("origin_mm", "axis") + (("section_axis",) if shape == "box" else ()):
        value = stock.get(key, UNKNOWN)
        if _vector(value):
            result[key] = value
        else:
            missing.append(key)
    if missing:
        return {
            "reason": f"{shape} stock placement/dimensions undeclared: "
            + ", ".join(missing)
            + "; in-process stock cannot be derived"
        }
    return result


_ENGINE_OP = (
    "subject",
    "feature",
    "faces",
    "radius_mm",
    "flute_len_mm",
    "holder_radius_mm",
    "holder_gauge_len_mm",
    "projection_mm",
    "to_z",
    "stock_removal_bounds",
)
_ENGINE_HOLD = (
    "fixed_jaw",
    "jaws_along",
    "jaw_above_parallels_mm",
    "jaw_center_along_mm",
    "parallels_centres_mm",
    "jaw_height_mm",
    "jaw_width_mm",
    "jaw_depth_mm",
    "parallels_height_mm",
    "parallels_length_mm",
    "parallels_width_mm",
)
# Vise inputs whose absence stops jaw placement in the engine.
_ENGINE_HOLD_REQUIRED = (
    "fixed_jaw",
    "jaws_along",
    "jaw_above_parallels_mm",
    "jaw_height_mm",
    "jaw_width_mm",
    "jaw_depth_mm",
    "parallels_height_mm",
)


def _engine_hold(hold):
    if hold["kind"] != "vise":
        return {"kind": hold["kind"]}
    result = {"kind": "vise"}
    result.update(
        {key: hold[key] for key in _ENGINE_HOLD if key in hold and hold[key] != UNKNOWN}
    )
    missing = [key for key in _ENGINE_HOLD_REQUIRED if key not in result]
    if missing:
        result["reason"] = "Fixture pose/dimensions unmeasured or unavailable: " + ", ".join(
            missing
        )
    return result


def engine_job(job):
    """Only the fields freecad_job.py reads; host-only inputs never key the geometry cache."""
    return {
        "version": job["version"],
        "step_path": job["step_path"],
        "step_sha256": job["step_sha256"],
        "features": job["features"],
        "as_is_faces": job["as_is_faces"],
        "stock": job["stock"],
        "setups": [
            {
                "id": setup["id"],
                "frame": setup["frame"],
                "hold": _engine_hold(setup["hold"]),
                "ops": [{key: op[key] for key in _ENGINE_OP if key in op} for op in setup["ops"]],
                "stock_in": setup["stock_in"],
            }
            for setup in job["setups"]
        ],
    }


def _engine_digest():
    digest = hashlib.sha256()
    for path in sorted(Path(__file__).parent.glob("*.py")):
        digest.update(path.name.encode())
        digest.update(path.read_bytes())
    return digest.hexdigest()


def _cache_path(key):
    base = os.environ.get("PRECHIPS_KERNEL_CACHE")
    root = (
        Path(base)
        if base
        else Path(os.environ.get("LOCALAPPDATA", Path.home() / ".cache")) / "prechips" / "geometry"
    )
    return root / (key + ".json")


def _valid_result(value):
    return isinstance(value, dict) and value.get("status") in {"ok", "unknown", "error"}


def _execute(executable, job):
    with tempfile.TemporaryDirectory(prefix="prechips-kernel-") as directory:
        source = Path(directory) / "input.json"
        target = Path(directory) / "output.json"
        source.write_text(_json(job), encoding="utf-8")
        process = subprocess.run(
            [
                str(executable),
                str(Path(__file__).with_name("freecad_job.py")),
                "--",
                str(source),
                str(target),
            ],
            capture_output=True,
            text=True,
            errors="replace",
            timeout=300,
        )
        if process.returncode:
            detail = (process.stderr or process.stdout).strip()
            return {
                "status": "error",
                "reason": f"FreeCAD kernel exited {process.returncode}: {detail}",
            }
        try:
            result = json.loads(target.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            return {"status": "error", "reason": f"FreeCAD kernel did not return valid JSON: {exc}"}
        if _valid_result(result) and result["status"] == "error":
            return result
        if (
            isinstance(result, dict)
            and isinstance(result.get("results"), list)
            and all(_valid_result(value) for value in result["results"])
        ):
            return result
        return {
            "status": "error",
            "reason": "FreeCAD kernel returned an invalid batch result contract.",
        }


def _read_cache(path):
    try:
        cached = json.loads(path.read_text(encoding="utf-8"))
        return cached if _valid_result(cached) and cached["status"] == "ok" else None
    except (OSError, ValueError):
        return None


def _write_cache(path, result):
    if result.get("status") != "ok":
        return
    temporary = None
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=path.parent, delete=False
        ) as stream:
            temporary = Path(stream.name)
            stream.write(_json(result))
        os.replace(temporary, path)
    except OSError:
        # Cache availability cannot change machining findings.
        pass
    finally:
        if temporary is not None:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass


def run_geometries(bundles):
    """Prewarm all candidates in one FreeCAD batch, reusing per-job content caches."""
    from prechips import telemetry

    bundles = list(bundles)
    pending = [bundle for bundle in bundles if getattr(bundle, "kernel", None) is None]
    if not pending:
        return [bundle.kernel for bundle in bundles]
    active = telemetry.current()
    with active.span("kernel.geometry", candidates=len(pending)) if active else nullcontext():
        executable = discover_kernel()
        if executable is None:
            result = {
                "status": "unknown",
                "kernel_unavailable": True,
                "reason": "FreeCAD kernel unavailable; install FreeCAD or set FREECAD_CMD.",
            }
            for bundle in pending:
                object.__setattr__(bundle, "kernel", dict(result))
        else:
            jobs = []
            targets = []
            keys = {}
            identity = None
            try:
                executable = Path(executable)
                stat = executable.stat()
                identity = {
                    "path": str(executable.resolve()),
                    "sha256": hashlib.sha256(executable.read_bytes()).hexdigest(),
                    "size": stat.st_size,
                    "mtime_ns": stat.st_mtime_ns,
                }
                engine = _engine_digest()
            except OSError as exc:
                for bundle in pending:
                    object.__setattr__(
                        bundle,
                        "kernel",
                        {"status": "error", "reason": f"Cannot identify FreeCAD kernel: {exc}"},
                    )
            if identity is not None:
                for bundle in pending:
                    job = engine_job(build_job(bundle))
                    if job["step_path"] == UNKNOWN or job["step_sha256"] == UNKNOWN:
                        object.__setattr__(
                            bundle,
                            "kernel",
                            {
                                "status": "unknown",
                                "reason": "STEP bytes and their manifest SHA-256 are "
                                "required for FreeCAD geometry.",
                            },
                        )
                        continue
                    try:
                        actual = hashlib.sha256(Path(job["step_path"]).read_bytes()).hexdigest()
                    except OSError:
                        object.__setattr__(
                            bundle,
                            "kernel",
                            {
                                "status": "unknown",
                                "reason": "STEP bytes became unavailable before "
                                "geometry evaluation.",
                            },
                        )
                        continue
                    if actual != job["step_sha256"]:
                        object.__setattr__(
                            bundle,
                            "kernel",
                            {
                                "status": "unknown",
                                "reason": "STEP bytes do not match the manifest SHA-256; "
                                "face identity is unresolved.",
                            },
                        )
                        continue
                    normalized = {name: value for name, value in job.items() if name != "step_path"}
                    key = hashlib.sha256(
                        _json({"job": normalized, "engine": engine, "kernel": identity}).encode()
                    ).hexdigest()
                    path = _cache_path(key)
                    cached = _read_cache(path)
                    if cached is not None:
                        object.__setattr__(bundle, "kernel", cached)
                    elif key in keys:
                        targets[keys[key]][1].append(bundle)
                    else:
                        keys[key] = len(jobs)
                        jobs.append(job)
                        targets.append((path, [bundle]))
                if jobs:
                    try:
                        response = _execute(executable, {"jobs": jobs})
                    except (OSError, subprocess.SubprocessError) as exc:
                        response = {
                            "status": "error",
                            "reason": f"FreeCAD kernel job failed: {exc}",
                        }
                    results = response.get("results")
                    if not isinstance(results, list) or len(results) != len(jobs):
                        error = (
                            response
                            if response.get("status") == "error"
                            else {
                                "status": "error",
                                "reason": "FreeCAD kernel batch returned the wrong "
                                "number of results.",
                            }
                        )
                        results = [error] * len(jobs)
                    for result, (path, consumers) in zip(results, targets, strict=True):
                        _write_cache(path, result)
                        for bundle in consumers:
                            object.__setattr__(bundle, "kernel", dict(result))
    return [bundle.kernel for bundle in bundles]


def run_geometry(bundle):
    """Populate the frozen bundle's non-operative memo once, including unavailable results."""
    return run_geometries([bundle])[0]
