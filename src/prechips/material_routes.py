"""Canonical host-side stock identity and history, without claiming native containment.

A named retained output is a physical partition identity, not another stock supply.
Its declared finished-solid ownership is useful for routing; only the native kernel
can prove the split, registration and whole-solid containment.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

UNKNOWN = "unknown"
OUTPUT_PREFIX = "stock_out."


def input_refs(setup: dict) -> list[str]:
    refs = setup.get("stock_in")
    return refs if isinstance(refs, list) else [refs] if isinstance(refs, str) else []


def retained_outputs(setup: dict) -> dict[str, dict]:
    return {
        name: entry
        for op in (setup["ops"] if isinstance(setup.get("ops"), list) else [])
        for name, entry in (op["outputs"] if isinstance(op.get("outputs"), dict) else {}).items()
        if isinstance(entry, dict)
    }


def _known_vector(value: Any) -> bool:
    return (
        isinstance(value, list)
        and len(value) == 3
        and all(
            isinstance(entry, (int, float)) and not isinstance(entry, bool) and math.isfinite(entry)
            for entry in value
        )
    )


def _output_pose(plan: dict, split: str, name: str) -> dict | None:
    setup = next((entry for entry in plan.get("setups", []) if entry["id"] == split), {})
    pose = retained_outputs(setup).get(name, {}).get("pose")
    binding = pose.get("binding") if isinstance(pose, dict) else None
    if (
        not isinstance(binding, str)
        or not binding.strip()
        or binding == UNKNOWN
        or not all(_known_vector(pose.get(key)) for key in ("origin", "x", "y", "z"))
    ):
        return None
    return pose


def reference_frame(plan: dict, ref: str, frame: dict) -> dict | None:
    """Producer frame after a retained piece's model-point registration, in plan units.

    Frame records store the machine basis in model coordinates. Transforming that
    basis by pose P means ``frame_point(q, result)`` applies the inverse registration:
    F(P^-1(q)), never F(P(q)). The pose itself maps old model points to new ones.
    Missing registration cannot imply a flip or transfer a producer-frame coordinate.
    """
    if not ref.startswith(OUTPUT_PREFIX):
        return frame
    split = producer_setup(plan, ref)
    pose = _output_pose(plan, split, ref.removeprefix(OUTPUT_PREFIX)) if split else None
    if pose is None or not all(_known_vector(frame.get(key)) for key in ("origin", "x", "y", "z")):
        return None

    def rotate(vector):
        return [
            sum(pose[axis][i] * vector[j] for j, axis in enumerate(("x", "y", "z")))
            for i in range(3)
        ]

    origin = rotate(frame["origin"])
    return {
        **frame,
        "origin": [pose["origin"][i] + origin[i] for i in range(3)],
        **{key: rotate(frame[key]) for key in ("x", "y", "z")},
    }


def setup_index(plan: dict) -> dict[str, dict]:
    """Known, unique setup identities; never synthesize a missing material identity."""
    result = {}
    for setup in plan.get("setups", []):
        sid = setup.get("id")
        if not isinstance(sid, str) or not sid.strip() or sid == UNKNOWN:
            raise ValueError("Setup ids must be known and non-empty.")
        if sid in result:
            raise ValueError("Setup ids must be unique.")
        result[sid] = setup
    return result


def producer_setup(plan: dict, ref: str) -> str | None:
    """The producing setup of a setup/output reference; a supply has no producer."""
    for setup in plan.get("setups", []):
        if setup.get("id") == ref or any(
            OUTPUT_PREFIX + name == ref for name in retained_outputs(setup)
        ):
            return setup["id"]
    return None


def setup_lineage(plan: dict, sid: str) -> set[str]:
    """Producer history only. Membership is never proof that a feature survived a split."""
    by_id = setup_index(plan)
    seen: set[str] = set()
    pending = [sid]
    while pending:
        ref = pending.pop()
        current = producer_setup(plan, ref)
        if current is None or current in seen:
            continue
        seen.add(current)
        pending.extend(input_refs(by_id[current]))
    return seen


@dataclass(frozen=True)
class Material:
    root: str
    split: str | None = None
    output: str | None = None
    carries: str | None = None

    def overlaps(self, other: Material) -> bool:
        return self.root == other.root and not (
            self.split is not None and self.split == other.split and self.output != other.output
        )


class MaterialGraph:
    """Route identities for a validated plan; unresolved roots remain explicit identities."""

    def __init__(self, plan: dict, *, validate: bool = False):
        setups = setup_index(plan)
        self.nodes: dict[str, tuple[Material, ...]] = {"stock": (Material("stock"),)}
        stock = plan.get("stock")
        components = stock.get("components", []) if isinstance(stock, dict) else []
        if isinstance(components, list):
            self.nodes.update(
                {
                    f"stock.{entry['id']}": (Material(f"stock.{entry['id']}"),)
                    for entry in components
                }
            )
        consumed: set[str] = set()
        earlier: set[str] = set()
        split_setups: set[str] = set()
        output_names: set[str] = set()
        setup_ids = set(setups)
        for sid, setup in setups.items():
            atoms: list[Material] = []
            refs = input_refs(setup)
            local: dict[str, str] = {}
            for ref in refs:
                where = f"Setup {sid} stock_in reference {ref!r}"
                if validate:
                    if ref == "stock" and isinstance(components, list) and components:
                        raise ValueError(
                            f"{where} requires a single stock supply; use stock.<component id>."
                        )
                    if ref in split_setups:
                        raise ValueError(
                            f"{where} names a partitioned setup; select its stock_out.<name>."
                        )
                    if ref not in self.nodes or ref in setup_ids and ref not in earlier:
                        reason = (
                            "is not an earlier setup"
                            if ref in setup_ids
                            else "is an unknown stock reference"
                        )
                        raise ValueError(f"{where} {reason}.")
                    if ref in consumed:
                        raise ValueError(
                            f"{where} is already consumed and shares ancestor "
                            f"{sorted(self.roots(ref))[0]!r} with its downstream material; "
                            "material may be used only once."
                        )
                incoming = self.nodes.get(ref, (Material(ref),))
                for atom in incoming:
                    conflict = next((other for other in atoms if atom.overlaps(other)), None)
                    if validate and conflict is not None:
                        raise ValueError(
                            f"{where} shares ancestor {atom.root!r} with {local[atom.root]!r}; "
                            "an assembly cannot join the same material twice."
                        )
                    atoms.append(atom)
                    local[atom.root] = ref
                # A raw supply specification may seed alternative root setups, as before.
                # Their common origin still prevents recombining overlapping material.
                if ref != "stock" and not ref.startswith("stock."):
                    consumed.add(ref)
            material = tuple(atoms) or (Material(sid),)
            self.nodes[sid] = material
            outputs = retained_outputs(setup)
            if outputs:
                if validate and (len(material) != 1 or material[0].split is not None):
                    raise ValueError(
                        f"Setup {sid}: named outputs cannot split an already partitioned "
                        "or assembled input."
                    )
                for name, entry in outputs.items():
                    if validate and name in output_names:
                        raise ValueError(f"Retained output name {name!r} must be globally unique.")
                    output_names.add(name)
                    ref = OUTPUT_PREFIX + name
                    self.nodes[ref] = tuple(
                        Material(atom.root, sid, name, entry["carries"]) for atom in material
                    )
                split_setups.add(sid)
            earlier.add(sid)

    def roots(self, ref: str) -> frozenset[str]:
        return frozenset(atom.root for atom in self.nodes.get(ref, (Material(ref),)))

    def descriptor(self, ref: str, owners: dict[str, str | None]) -> dict:
        atoms = self.nodes.get(ref, ())
        carried = [owners.get(atom.carries) for atom in atoms]
        return {
            "roots": sorted(self.roots(ref)),
            "partitions": [
                {"split": atom.split, "output": atom.output}
                for atom in atoms
                if atom.split is not None
            ],
            # An unregistered source bar is unknown, never an empty protected part.
            "finished_solids": sorted(set(carried)) if carried and all(carried) else None,
        }


def stock_ancestry(plan: dict) -> dict[str, frozenset[str]]:
    """Supply ancestry from the complete route, including named retained-output identities."""
    graph = MaterialGraph(plan)
    return {ref: graph.roots(ref) for ref in graph.nodes}


def _owners(features: Any) -> dict[str, str | None]:
    if hasattr(features, "finished_feature_owners"):
        return features.finished_feature_owners
    return features.get("finished_feature_owners", {}) if isinstance(features, dict) else {}


def feature_branch_status(plan: dict, ref: str, feature_id: str, features: Any) -> bool | None:
    """Declared finished-solid membership of a route ref, not native containment proof."""
    atoms = MaterialGraph(plan).nodes.get(ref, ())
    if not atoms:
        return None
    owners = _owners(features)
    owner = owners.get(feature_id)
    uncertain = False
    for atom in atoms:
        if atom.split is None:
            uncertain = True
        elif owner is not None and owners.get(atom.carries) is not None:
            if owner == owners[atom.carries]:
                if _output_pose(plan, atom.split, atom.output) is not None:
                    return True
                uncertain = True
        else:
            uncertain = True
    return None if uncertain else False


def feature_material_status(
    plan: dict, setup_id: str, producer_id: str, feature_id: str, features: Any
) -> bool | None:
    """Whether an upstream feature belongs to this material: False, True, or unproven.

    A transient centre/face cut before partition is not known to survive on either
    child merely because its producing setup is in both children's histories.
    """
    if producer_id not in setup_lineage(plan, setup_id) and not producer_id.startswith("stock"):
        return False
    if feature_branch_status(plan, setup_id, feature_id, features) is False:
        return False
    graph = MaterialGraph(plan)
    source = graph.nodes.get(producer_id, ())
    if producer_id == "stock":
        source = tuple(
            atom
            for ref, atoms in graph.nodes.items()
            if ref == "stock" or ref.startswith("stock.")
            for atom in atoms
        )
    target = graph.nodes.get(setup_id, ())
    owner = _owners(features).get(feature_id)
    uncertain = False
    for atom in target:
        if owner is not None and atom.carries is not None:
            carried_owner = _owners(features).get(atom.carries)
            if carried_owner is not None and owner != carried_owner:
                continue
        for prior in source:
            if owner is not None and prior.carries is not None:
                prior_owner = _owners(features).get(prior.carries)
                if prior_owner is not None and owner != prior_owner:
                    continue
            if atom.root != prior.root or not atom.overlaps(prior):
                continue
            if atom.split is not None and _output_pose(plan, atom.split, atom.output) is None:
                uncertain = True
                continue
            if atom.split == prior.split and atom.output == prior.output:
                return True
            if atom.split is None:
                uncertain = True
                continue
            carried_owner = _owners(features).get(atom.carries)
            if owner is not None and carried_owner is not None:
                if owner == carried_owner:
                    return True
            else:
                uncertain = True
    return None if uncertain else False


def material_coverage_status(plan: dict, covering: str | list[str], target: str) -> bool | None:
    """Whether all target material flowed through covering, not merely a common ancestor."""
    graph = MaterialGraph(plan)
    refs = [covering] if isinstance(covering, str) else covering
    covered = tuple(atom for ref in refs for atom in graph.nodes.get(ref, ()))
    required = graph.nodes.get(target, ())
    if not covered or not required:
        return None
    # Every covered atom is a declared identity; registration remains a native question.
    for atom in required:
        matches = [other for other in covered if other.root == atom.root]
        if any(other == atom for other in matches):
            continue
        if atom.split is not None and any(other.split is None for other in matches):
            continue
        # A parent is covered only when both retained children went through the process.
        children = [other for other in matches if other.split is not None]
        if atom.split is None and children and len({other.output for other in children}) == 2:
            continue
        return False
    return True
