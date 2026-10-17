"""Resolve, validate and hash the complete operative input bundle."""

from __future__ import annotations

import hashlib
import os
import tomllib
from contextlib import nullcontext
from dataclasses import dataclass
from dataclasses import field as dataclass_field
from functools import cached_property
from pathlib import Path

from pydantic import ValidationError

from prechips.model import (
    CuttingData,
    Features,
    InputModel,
    Inventory,
    Plan,
    Policy,
    profiled,
    reference_only,
)


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
    kernel: dict | None = dataclass_field(default=None, compare=False)

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

    @cached_property
    def feature_definitions(self) -> dict[str, dict]:
        """Operative features: the exported manifest plus resolved plan joint and process
        features.

        ``features`` stays the original exported document (hash, faces and coverage).
        """
        return operative_definitions(self.plan, self.features)


def operative_definitions(plan: dict, features: dict) -> dict[str, dict]:
    """The exported manifest plus resolved plan joint and process features."""
    from prechips import joint_features, process_features

    return process_features.feature_definitions(
        plan, joint_features.feature_definitions(plan, features), features.get("units", "unknown")
    )


def _span(kind: str, path: Path):
    from prechips import telemetry

    active = telemetry.current()
    return active.span("input.load", kind=kind, path=str(path)) if active else nullcontext()


def _exported(feature: dict) -> list:
    requirements = feature.get("requirements")
    return requirements if isinstance(requirements, list) else []


def _prepared_blank(plan: dict, ids: list[str]) -> None:
    """A prepared blank names a known receiving setup and is cut from one rectangular root
    stock; its size check (rule ``prepared_blank``) has no other root to trim. An explicitly
    ``"unknown"`` preparation names no setup: the rule leaves it unknown."""
    stock = plan.get("stock")
    prepared = stock.get("prepared") if isinstance(stock, dict) else None
    if prepared is None:
        return
    receiver = prepared.get("setup", "unknown") if isinstance(prepared, dict) else "unknown"
    if receiver != "unknown" and receiver not in ids:
        raise BadInput(f"stock.prepared.setup {receiver!r} is not a plan setup.")
    if stock.get("components") or "dia_mm" in stock or profiled(stock):
        raise BadInput(
            "stock.prepared squares one rectangular root stock; a round, built-up or "
            "profiled stock has no box to trim."
        )


def _inspection_tables(where: str, op: dict, names: list[str], definitions: dict) -> None:
    """An op's ``checks``, ``go_no_go`` and ``inspection_methods``: requirement-keyed, or on
    a multi-feature inspect op scoped to one listed feature (``{ <feature> = { <requirement>
    = ... } }``). A scoped requirement is one its feature exports, a requirement is flat or
    scoped in one table, never both, and a GO / NO-GO pair or scoped method has a checks gauge
    for every feature it applies to."""
    from prechips.rules.resolution import INSPECTION_TABLES, op_entries, op_entry

    exported = {name: set(_exported(definitions[name])) for name in names}
    every = set().union(*exported.values())
    for table in INSPECTION_TABLES:
        for key, value in (op.get(table) if isinstance(op.get(table), dict) else {}).items():
            # A table of entries, never a flat value (a GO / NO-GO pair is a table too).
            scoping = isinstance(value, dict) and not (
                table == "go_no_go" and {"go", "no_go"} & set(value)
            )
            if key not in names and scoping:
                raise BadInput(
                    f"{where} {table}.{key} scopes entries to a feature the op does not list; "
                    f"scope them to one of {', '.join(names)}."
                )
            if key not in names:
                continue
            if key in every:
                raise BadInput(
                    f"{where} {table}.{key} is both a listed feature and an exported "
                    "requirement; the key is ambiguous."
                )
            if len(names) == 1:
                raise BadInput(
                    f"{where} {table}.{key} scopes entries to the op's only feature; a "
                    f"single-feature op keys {table} by requirement alone."
                )
            if not scoping:
                raise BadInput(
                    f"{where} {table}.{key} names a listed feature: scope its entries as "
                    f"{table}.{key}.<requirement>."
                )
        entries = op_entries(op, table)
        flat = {requirement for scope, requirement, _ in entries if scope is None}
        for scope, requirement, _ in entries:
            if scope is None and table == "checks" and requirement not in every:
                raise BadInput(
                    f"{where} checks.{requirement} is not in the exported requirements; use "
                    "missing_requirements for an absent requirement."
                )
            if scope is None:
                continue
            if requirement not in exported[scope]:
                raise BadInput(
                    f"{where} {table}.{scope}.{requirement} is not one of {scope}'s exported "
                    "requirements; use missing_requirements for an absent requirement."
                )
            if requirement in flat:
                raise BadInput(
                    f"{where} {table}.{requirement} is given both for every listed feature "
                    f"and for {scope} alone; give it flat or per feature, not both."
                )
            if table != "checks" and op_entry(op, "checks", scope, requirement) is None:
                raise BadInput(
                    f"{where} {table}.{scope}.{requirement} names no checks gauge for "
                    f"{scope}; it needs a checks entry for that feature's {requirement}."
                )
        for requirement in flat if table == "go_no_go" else ():
            owners = [name for name in names if requirement in exported[name]]
            if not owners or any(
                op_entry(op, "checks", name, requirement) is None for name in owners
            ):
                raise BadInput(
                    f"{where} go_no_go.{requirement} names no checks gauge; a GO / NO-GO pair "
                    "needs its checks entry."
                )


_AREA_FORM = 'hold.area = { ref = "<consumables adhesive_tape id>", on = "<fixture solid>" }'


def _area_holds(plan: dict, inventory: dict) -> None:
    """An area hold is typed (docs/design/area-hold.md): ``hold.method`` no longer carries
    tape, ``area.ref`` names an inventory ``adhesive_tape`` consumable, and ``area.on``
    names exactly one non-void solid of the holding fixture. A literal unknown identity stays
    unresolved debt for the rules, and so does a named seat the kernel cannot draw (an
    untrusted or incomplete solid): that is the phase 3 seat check's ``?``, never a pass."""
    from prechips.rules.resolution import select

    for setup in plan["setups"]:
        hold = setup.get("hold")
        if not isinstance(hold, dict):
            continue
        where = f"{setup['id']}: hold"
        method = hold.get("method")
        if isinstance(method, str) and method.strip().lower() == "tape":
            raise BadInput(
                f"{where}.method {method!r} is no longer a holding method: name the "
                f"consumables adhesive_tape item with {_AREA_FORM}."
            )
        area = hold.get("area")
        if not isinstance(area, dict):
            continue
        ref, on = area.get("ref", "unknown"), area.get("on", "unknown")
        # Every inventory reference resolves through the one selector the rules use, so
        # a qualified hold.fixture (fixtures.plate) names the same item as a bare one.
        # A qualified ref keeps its own category, so only a consumables item was
        # validated as an AdhesiveTape record.
        category, _, tape = (
            select(inventory, ref, "consumables") if ref != "unknown" else (None,) * 3
        )
        if ref != "unknown" and not (
            category == "consumables"
            and isinstance(tape, dict)
            and tape.get("kind") == "adhesive_tape"
        ):
            raise BadInput(f"{where}.area.ref {ref!r} is not a consumables adhesive_tape item.")
        fixture = hold.get("fixture", "unknown")
        item = select(inventory, fixture, "workholding")[2] if fixture != "unknown" else None
        # An unresolved fixture or a solids list stated unknown is debt for the rules; a
        # known fixture that draws no solids has no seat to name.
        solids = item.get("solids", []) if isinstance(item, dict) else "unknown"
        if on == "unknown" or not isinstance(solids, list):
            continue
        named = [
            solid
            for solid in solids
            if isinstance(solid, dict) and solid.get("name") == on and solid.get("void") is not True
        ]
        if len(named) != 1:
            raise BadInput(
                f"{where}.area.on {on!r} must name exactly one non-void solid of fixture "
                f"{fixture!r} (found {len(named)})."
            )


def blank_supplies(plan: dict) -> dict[str, dict]:
    """Each declared profiled blank keyed by its input kind: ``stock.blank`` for the root
    stock, ``stock.<id>.blank`` for a component."""
    stock = plan.get("stock") if isinstance(plan.get("stock"), dict) else {}
    components = stock.get("components")
    pieces = [("stock", stock)] + [
        (f"stock.{component['id']}", component)
        for component in (components if isinstance(components, list) else ())
    ]
    return {
        f"{name}.blank": piece["blank"]
        for name, piece in pieces
        if isinstance(piece.get("blank"), dict)
    }


def _blank_assets(plan, base, root, paths, hashes):
    """Read and hash every profiled blank STEP; a known digest must match its bytes."""
    for kind, blank in blank_supplies(plan).items():
        value = blank.get("step", "unknown")
        if value == "unknown":
            continue
        path = _resolve(value, base)
        if not path.is_relative_to(root):
            raise BadInput(f"{kind}.step escapes the input bundle.")
        try:
            with _span(kind, path):
                raw = path.read_bytes()
        except OSError as exc:
            raise BadInput(f"Cannot read {kind}.step asset: {exc}") from exc
        digest = hashlib.sha256(raw).hexdigest()
        if blank.get("step_sha256", "unknown") not in {"unknown", digest}:
            raise BadInput(f"The {kind} STEP bytes do not match its step_sha256.")
        paths[kind], hashes[kind] = path, digest


def _load(path: Path, model: type[InputModel], kind: str) -> tuple[dict, str]:
    with _span(kind, path):
        try:
            raw = path.read_bytes()
            values = tomllib.loads(raw.decode("utf-8"))
            parsed = model.model_validate(values)
            # Sparse dumps retain authored presence for semantic optional fields;
            # record serializers also retain defaults for keys rules directly index.
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
    from prechips.rules.coordinates import aim_band_error, faced_aim_error
    from prechips.rules.resolution import SAW_OPS, op_features

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
    from prechips import joint_features, process_features

    definitions = operative_definitions(plan, features)
    for name, feature in features["features"].items():
        faces = feature.get("faces")
        for prefix, what in (
            (joint_features.LABEL_PREFIX, "joint"),
            (process_features.LABEL_PREFIX, "stock-preparation"),
        ):
            if isinstance(faces, list) and any(str(face).startswith(prefix) for face in faces):
                raise BadInput(
                    f"features.{name}.faces names a synthetic {prefix}* label; transient "
                    f"{what} geometry never maps to finished STEP faces."
                )
    setups = plan["setups"]
    if not isinstance(setups, list) or not setups:
        raise BadInput("The plan has no setups.")
    ids = [setup.get("id", "unknown") for setup in setups]
    if "unknown" in ids or len(set(ids)) != len(ids):
        raise BadInput("Setup ids must be known and unique.")
    _prepared_blank(plan, ids)
    planned_frames = plan.get("frames") if isinstance(plan.get("frames"), dict) else {}
    for name, aim in plan.get("aims", {}).items():
        if aim["requirement"] not in _exported(definitions.get(name, {})):
            raise BadInput(
                f"aims.{name}: {aim['requirement']} is not an exported drawing requirement "
                "of a manifest feature."
            )
        # The aimed value itself, before any DRO rounding could bring its target back in.
        error = aim_band_error(features, name, definitions[name], aim) or faced_aim_error(
            plan, features, name, aim
        )
        if error is not None:
            raise BadInput(f"{error}.")
    for setup in setups:
        ops = setup.get("ops")
        if not isinstance(ops, list) or not ops:
            raise BadInput(f"{setup['id']}: the setup has no operations.")
        op_ids = [op.get("op", "unknown") for op in ops]
        if "unknown" in op_ids or len(set(op_ids)) != len(op_ids):
            raise BadInput(f"{setup['id']}: operation numbers must be known and unique.")
        for op in ops:
            for hold in op.get("process_holds", []):
                held = definitions.get(hold["feature"], {})
                where = f"{setup['id']}:{op['op']}: process hold {hold['feature']}"
                if reference_only(held, hold["requirement"]):
                    if hold.get("measure") is None or hold.get("cite") is None:
                        raise BadInput(
                            f"{where} {hold['requirement']} is reference-only (the drawing "
                            "sets no limit): name what the gauge reads (measure) and where "
                            "the band comes from (cite)."
                        )
                elif hold["requirement"] not in _exported(held):
                    raise BadInput(
                        f"{where} {hold['requirement']} is not an exported drawing requirement."
                    )
                elif hold.get("measure") is not None:
                    raise BadInput(
                        f"{where} {hold['requirement']}: only a hold on a reference-only "
                        "dimension names a measure; this one reads its drawing requirement."
                    )
            if op.get("do") in SAW_OPS and "feature" not in op:
                if op.get("checks") or op.get("missing_requirements"):
                    raise BadInput(
                        f"{setup['id']}:{op['op']}: saw inspection checks need a manifest feature."
                    )
                continue
            names = op_features(op)
            if not names or any(name not in definitions for name in names):
                raise BadInput(
                    f"{setup['id']}:{op['op']}: feature is neither in the manifest, "
                    "plan.joint_features nor plan.process_features."
                )
            preparing = [name for name in names if process_features.process_of(definitions[name])]
            if preparing:
                authored = [key for key in ("faces", "checks", "missing_requirements") if key in op]
                if authored or len(names) != 1:
                    raise BadInput(
                        f"{setup['id']}:{op['op']}: plan.process_features.{preparing[0]} is "
                        "stock preparation; its op works that one feature alone and claims "
                        "no finished faces, checks or drawing requirements"
                        + (f" (remove {', '.join(authored)})." if authored else ".")
                    )
            label = "/".join(names)
            exported = {item for name in names for item in _exported(definitions[name])}
            _inspection_tables(f"{setup['id']}:{op['op']}: {label}", op, names, definitions)
            missing = op.get("missing_requirements")
            if isinstance(missing, dict):
                for requirement in missing:
                    if requirement in exported:
                        raise BadInput(
                            f"{setup['id']}:{op['op']}: {label} "
                            f"missing_requirements.{requirement} is already exported; "
                            "use checks for that requirement."
                        )
        hold = setup.get("hold")
        face = hold.get("stop_face") if isinstance(hold, dict) else None
        if face not in (None, "unknown", "stock_end") and face not in definitions:
            raise BadInput(
                f"{setup['id']}: hold.stop_face {face!r} is neither a manifest feature, "
                'plan.joint_features, plan.process_features nor "stock_end".'
            )
        centre = hold.get("centre_hole") if isinstance(hold, dict) else None
        made = process_features.process_of(definitions.get(centre)) if centre else None
        if centre is not None and (made is None or made["kind"] != "centre_hole"):
            raise BadInput(
                f"{setup['id']}: hold.centre_hole {centre!r} is not a "
                "plan.process_features centre_hole."
            )
        frame = setup.get("frame", "unknown")
        if (
            isinstance(features["frames"], dict)
            and frame != "unknown"
            and frame not in features["frames"]
            and frame not in planned_frames
        ):
            raise BadInput(
                f"{setup['id']}: frame {frame!r} is neither exported in the manifest "
                "nor declared in plan.frames."
            )
    exported_frames = features["frames"] if isinstance(features["frames"], dict) else {}
    shadowed = sorted(set(planned_frames) & set(exported_frames))
    if shadowed:
        raise BadInput(
            f"plan.frames {', '.join(map(repr, shadowed))} would shadow exported manifest "
            "frames; rename the plan-owned setup frame."
        )
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
        if declared == "unknown":
            declared = None
        value = override or declared or (os.environ.get(variable) if variable else None)
        if not value or value == "unknown":
            if kind == "shop_policy":
                # Shop absence uses the shipped required vocabulary, never plan-owned overrides.
                resolved[kind] = {
                    "required": dict.fromkeys(
                        (
                            "tool_resolves",
                            "sizing",
                            "op_chain",
                            "blind_depth",
                            "inspection",
                            "coordinates",
                            "zero_check",
                        ),
                        "*",
                    )
                }
                continue
            raise BadInput(f"No {kind.replace('_', ' ')} path was supplied.")
        from_plan = not override and bool(declared)
        path = _resolve(value, plan_path.parent if from_plan else Path.cwd())
        if from_plan and not path.is_relative_to(root):
            raise BadInput(
                f"The declared {kind.replace('_', ' ')} path escapes the bundle directory."
            )
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
    _blank_assets(plan, plan_path.parent, root, paths, hashes)
    _area_holds(plan, resolved["inventory"])
    step_digest = features.get("step_sha256", "unknown")
    if step_digest != "unknown":
        if len(step_digest) != 64 or any(char not in "0123456789abcdef" for char in step_digest):
            raise BadInput("The manifest STEP digest must be lowercase SHA-256 or unknown.")
        if "step" not in paths:
            raise BadInput("A known STEP digest requires its STEP bytes in the bundle.")
    bundle = Bundle(
        plan,
        features,
        resolved["inventory"],
        resolved["shop_policy"],
        resolved["cutting_data"],
        paths,
        hashes,
        root,
    )
    # Seed the cached operative mapping already resolved above; it is built once.
    bundle.__dict__["feature_definitions"] = definitions
    return bundle
