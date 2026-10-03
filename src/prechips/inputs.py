"""Resolve, validate and hash the complete operative input bundle."""

from __future__ import annotations

import hashlib
import os
import tomllib
from contextlib import nullcontext
from dataclasses import dataclass
from pathlib import Path

from pydantic import ValidationError

from prechips.model import CuttingData, Features, InputModel, Inventory, Plan, Policy


class BadInput(Exception):
    """Invalid input must be reported as exit 3 before any output is written."""


@dataclass(frozen=True)
class Bundle:
    plan: dict
    features: dict
    inventory: dict
    policy: dict
    cutting_data: dict
    paths: dict[str, Path]
    hashes: dict[str, str]
    root: Path

    @property
    def input_records(self) -> dict[str, dict[str, str]]:
        records = {}
        for kind, path in self.paths.items():
            try:
                label = path.relative_to(self.root).as_posix()
            except ValueError:
                # Explicit shop files may live elsewhere. Never embed machine-specific roots.
                label = f"external/{kind}/{path.name}"
            records[kind] = {"path": label, "sha256": self.hashes[kind]}
        return records


def _span(kind: str, path: Path):
    from prechips import telemetry

    active = telemetry.current()
    return active.span("input.load", kind=kind, path=str(path)) if active else nullcontext()


def _load(path: Path, model: type[InputModel], kind: str) -> tuple[dict, str]:
    with _span(kind, path):
        try:
            raw = path.read_bytes()
            values = tomllib.loads(raw.decode("utf-8"))
            parsed = model.model_validate(values)
            return parsed.model_dump(exclude_unset=True), hashlib.sha256(raw).hexdigest()
        except (OSError, UnicodeError, tomllib.TOMLDecodeError, ValidationError) as exc:
            raise BadInput(f"Cannot load {kind} {path.name}: {exc}") from exc


def _root(plan_path: Path) -> Path:
    for parent in plan_path.parents:
        if parent.name == "examples":
            return parent.parent
        if (parent / "pyproject.toml").is_file():
            return parent
    return plan_path.parent


def _resolve(value: str | Path, base: Path) -> Path:
    path = Path(value)
    return (path if path.is_absolute() else base / path).resolve()


def load_inventory(path: str | Path) -> dict:
    return _load(Path(path).resolve(), Inventory, "inventory")[0]


def load_bundle(
    plan_path: str | Path,
    inventory: str | Path | None = None,
    policy: str | Path | None = None,
    cutting_data: str | Path | None = None,
) -> Bundle:
    plan_path = Path(plan_path).resolve()
    plan, plan_hash = _load(plan_path, Plan, "plan")
    if plan.get("features") == "unknown":
        raise BadInput("The plan must name its feature manifest.")
    features_path = _resolve(plan["features"], plan_path.parent)
    root = _root(plan_path)
    if not features_path.is_relative_to(root):
        raise BadInput("The feature manifest path escapes the bundle directory.")
    features, features_hash = _load(features_path, Features, "features")
    if plan["part"] != features["part"]:
        raise BadInput("Plan and feature manifest name different parts.")
    if not features["features"]:
        raise BadInput("The feature manifest has no features.")
    setups = plan["setups"]
    if not isinstance(setups, list) or not setups:
        raise BadInput("The plan has no setups.")
    ids = [setup.get("id", "unknown") for setup in setups]
    if "unknown" in ids or len(set(ids)) != len(ids):
        raise BadInput("Setup ids must be known and unique.")
    for setup in setups:
        ops = setup.get("ops")
        if not isinstance(ops, list) or not ops:
            raise BadInput(f"{setup['id']}: the setup has no operations.")
        op_ids = [op.get("op", "unknown") for op in ops]
        if "unknown" in op_ids or len(set(op_ids)) != len(op_ids):
            raise BadInput(f"{setup['id']}: operation numbers must be known and unique.")
        for op in ops:
            if op.get("feature") not in features["features"]:
                raise BadInput(f"{setup['id']}:{op['op']}: feature is not in the manifest.")
        frame = setup.get("frame", "unknown")
        if isinstance(features["frames"], dict) and frame != "unknown" and frame not in features["frames"]:
            raise BadInput(f"{setup['id']}: frame {frame!r} is not in the manifest.")
    declarations = plan.get("paths", {})
    if not isinstance(declarations, dict):
        declarations = {}
    paths = {"plan": plan_path, "features": features_path}
    hashes = {"plan": plan_hash, "features": features_hash}
    resolved = {}
    choices = (
        ("inventory", inventory, "inventory", "PRECHIPS_INVENTORY", Inventory),
        ("shop_policy", policy, "policy", "PRECHIPS_POLICY", Policy),
        ("cutting_data", cutting_data, "cutting_data", None, CuttingData),
    )
    for kind, override, field, variable, model in choices:
        declared = declarations.get(field)
        value = override or declared or (os.environ.get(variable) if variable else None)
        if not value or value == "unknown":
            if kind == "shop_policy":
                # Shop absence uses the shipped required vocabulary, never plan-owned overrides.
                resolved[kind] = {
                    "required": dict.fromkeys(
                        ("tool_resolves", "sizing", "op_chain", "blind_depth", "inspection", "coordinates", "zero_check"),
                        "*",
                    )
                }
                continue
            raise BadInput(f"No {kind.replace('_', ' ')} path was supplied.")
        from_plan = not override and bool(declared)
        path = _resolve(value, plan_path.parent if from_plan else Path.cwd())
        if from_plan and not path.is_relative_to(root):
            raise BadInput(f"The declared {kind.replace('_', ' ')} path escapes the bundle directory.")
        resolved[kind], hashes[kind] = _load(path, model, kind)
        paths[kind] = path
    # Every referenced asset is read, hashed and contained. Citations are never assets.
    for document in (plan, features):
        for field in ("step",):
            value = document.get(field) or (declarations.get(field) if document is plan else None)
            if value and value != "unknown":
                base = plan_path.parent if document is plan else features_path.parent
                path = _resolve(value, base)
                if not path.is_relative_to(root):
                    raise BadInput(f"Referenced {field} path escapes the input bundle.")
                try:
                    with _span(field, path):
                        raw = path.read_bytes()
                except OSError as exc:
                    raise BadInput(f"Cannot read {field} asset: {exc}") from exc
                digest = hashlib.sha256(raw).hexdigest()
                if features.get("step_sha256", "unknown") not in {"unknown", digest}:
                    raise BadInput("The STEP bytes do not match the manifest digest.")
                paths[field], hashes[field] = path, digest
    step_digest = features.get("step_sha256", "unknown")
    if step_digest != "unknown":
        if len(step_digest) != 64 or any(char not in "0123456789abcdef" for char in step_digest):
            raise BadInput("The manifest STEP digest must be lowercase SHA-256 or unknown.")
        if "step" not in paths:
            raise BadInput("A known STEP digest requires its STEP bytes in the bundle.")
    return Bundle(
        plan, features, resolved["inventory"], resolved["shop_policy"], resolved["cutting_data"],
        paths, hashes, root,
    )
