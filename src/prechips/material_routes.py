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
        or binding.strip() == UNKNOWN
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


def route_identities_known(plan: dict, sid: Any) -> bool:
    """Whether route queries can bind identities in a potentially incomplete rendering.

    This is only a query precondition, never material proof or relaxed plan validation.
    Strict loading still uses ``setup_index`` and rejects unresolved setup identities.
    """
    identities = [sid, *(setup.get("id") for setup in plan.get("setups", []))]
    return all(
        isinstance(value, str) and value.strip() and value != UNKNOWN for value in identities
    )


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
class Partition:
    split: str
    output: str


@dataclass(frozen=True)
class Material:
    root: str
    path: tuple[Partition, ...] = ()
    carries: str | None = None
    workpieces: tuple[str, ...] | None = None

    def overlaps(self, other: Material) -> bool:
        if self.root != other.root:
            return False
        for left, right in zip(self.path, other.path, strict=False):
            if left != right:
                return left.split != right.split
        return True


def workpiece_registrations(plan: dict) -> dict[str, dict] | None:
    """Authored instance placements, independent of canonical source ownership."""
    entries = plan.get("workpieces")
    return entries if isinstance(entries, dict) else None


class MaterialGraph:
    """Declared material identities; registrations never assert native containment."""

    def __init__(self, plan: dict, *, validate: bool = False):
        setups = setup_index(plan)
        self.plan = plan
        self.registrations = workpiece_registrations(plan)
        members = tuple(self.registrations) if self.registrations is not None else None
        if validate and self.registrations is not None:
            if not self.registrations or any(
                not name.strip() or name != name.strip() or name == UNKNOWN
                for name in self.registrations
            ):
                raise ValueError("Workpiece ids must be known, non-empty, distinct names.")
            poses: set[tuple] = set()
            for entry in self.registrations.values():
                pose = entry.get("pose")
                if (
                    isinstance(pose, dict)
                    and isinstance(pose.get("binding"), str)
                    and pose["binding"].strip() not in {"", UNKNOWN}
                    and all(_known_vector(pose.get(key)) for key in ("origin", "x", "y", "z"))
                ):
                    identity = tuple(tuple(pose[key]) for key in ("origin", "x", "y", "z"))
                    if identity in poses:
                        raise ValueError("Workpiece registrations alias the same target placement.")
                    poses.add(identity)
        self.nodes: dict[str, tuple[Material, ...]] = {
            "stock": (Material("stock", workpieces=members),)
        }
        stock = plan.get("stock")
        components = stock.get("components", []) if isinstance(stock, dict) else []
        if isinstance(components, list):
            if validate and members is not None and components:
                raise ValueError("Registered workpieces require one canonical stock supply.")
            self.nodes.update(
                {
                    f"stock.{entry['id']}": (Material(f"stock.{entry['id']}"),)
                    for entry in components
                }
            )
        consumed: set[str] = set()
        # Only named-retained routes are exclusive; ordinary state fan-out stays legal.
        exclusive_refs = (
            {
                ref
                for setup in setups.values()
                if retained_outputs(setup)
                for ref in setup_lineage(plan, setup["id"])
            }
            if validate
            else set()
        )
        earlier: set[str] = set()
        split_setups: set[str] = set()
        output_names: set[str] = set()
        setup_ids = set(setups)
        for sid, setup in setups.items():
            atoms: list[Material] = []
            refs = input_refs(setup)
            local: dict[str, str] = {}
            if (
                validate
                and members is not None
                and ("stock_in" not in setup or not isinstance(setup["stock_in"], str))
            ):
                raise ValueError(
                    f"Setup {sid}: a workpiece route requires explicit scalar stock_in."
                )
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
            material = tuple(atoms) or (Material(sid),)
            if validate:
                self._validate_supports(setup, material, earlier, consumed, split_setups)
            # Invalidate existing same-state aliases, not descendants that will be
            # published after this consumption. Batch raw stock is also single-use.
            for ref in refs:
                incoming = self.nodes.get(ref, ())
                if (
                    ref in exclusive_refs
                    or any(atom.path for atom in incoming)
                    or members is not None
                ):
                    consumed.add(ref)
                    if members is not None:
                        consumed.update(
                            alias
                            for alias, states in self.nodes.items()
                            if any(a.overlaps(b) for a in incoming for b in states)
                        )
            self.nodes[sid] = material
            if validate:
                self._validate_claims(setup)
            outputs = retained_outputs(setup)
            if outputs:
                batch = any("carries_workpieces" in entry for entry in outputs.values())
                if validate:
                    if len(outputs) != 2:
                        raise ValueError(
                            f"Setup {sid}: outputs require exactly two retained pieces."
                        )
                    if len(material) != 1:
                        raise ValueError(
                            f"Setup {sid}: named outputs cannot split assembled input."
                        )
                    if material[0].path and not batch:
                        raise ValueError(
                            f"Setup {sid}: an already partitioned input requires "
                            "registered workpieces."
                        )
                    if batch:
                        if any(
                            not isinstance(entry.get("carries_workpieces"), list)
                            or not entry["carries_workpieces"]
                            for entry in outputs.values()
                        ):
                            raise ValueError(
                                f"Setup {sid}: every output requires nonempty carries_workpieces."
                            )
                        live = self.members(sid)
                        claimed = [
                            member
                            for entry in outputs.values()
                            for member in entry.get("carries_workpieces", [])
                        ]
                        if (
                            live is None
                            or any("carries" in entry for entry in outputs.values())
                            or len(claimed) != len(set(claimed))
                            or set(claimed) != live
                        ):
                            raise ValueError(
                                f"Setup {sid}: outputs must carry every live workpiece "
                                "exactly once."
                            )
                        if {entry.get("side") for entry in outputs.values()} != {"below", "above"}:
                            raise ValueError(
                                f"Setup {sid}: outputs require distinct below/above sides."
                            )
                    elif members is not None:
                        raise ValueError(
                            f"Setup {sid}: registered workpiece outputs require carries_workpieces."
                        )
                for name, entry in outputs.items():
                    if validate and name in output_names:
                        raise ValueError(f"Retained output name {name!r} must be globally unique.")
                    output_names.add(name)
                    ref = OUTPUT_PREFIX + name
                    carried = entry.get("carries_workpieces")
                    self.nodes[ref] = tuple(
                        Material(
                            atom.root,
                            (*atom.path, Partition(sid, name)),
                            entry.get("carries"),
                            tuple(carried) if isinstance(carried, list) else None,
                        )
                        for atom in material
                    )
                split_setups.add(sid)
            earlier.add(sid)

    def _validate_claims(self, setup: dict) -> None:
        live = self.members(setup["id"])
        for op in setup.get("ops", []) if isinstance(setup.get("ops"), list) else []:
            claims = op.get("workpiece_faces")
            if isinstance(claims, dict) and (live is None or not set(claims) <= live):
                raise ValueError(
                    f"Setup {setup['id']} op {op.get('op')}: "
                    "workpiece_faces must name live carried members."
                )
            if live is not None and len(live) != 1 and isinstance(op.get("faces"), list):
                raise ValueError(
                    f"Setup {setup['id']} op {op.get('op')}: "
                    "multi-workpiece faces require workpiece_faces."
                )

    def _validate_supports(
        self,
        setup: dict,
        material: tuple[Material, ...],
        earlier: set[str],
        consumed: set[str],
        split_setups: set[str],
    ) -> None:
        hold = setup.get("hold")
        supports = hold.get("supports") if isinstance(hold, dict) else None
        names: set[str] = set()
        for entry in supports if isinstance(supports, list) else []:
            if not isinstance(entry, dict) or entry.get("placement") != "posed":
                continue
            name = entry["id"]
            if name in names:
                raise ValueError(f"Setup {setup['id']}: placed support ids must be unique.")
            names.add(name)
            ref = entry.get("stock_ref")
            if ref is None:
                continue
            producer = producer_setup(self.plan, ref)
            if (
                ref not in self.nodes
                or ref.startswith("stock.")
                or ref == "stock"
                or producer is None
                or producer not in earlier
                or ref in split_setups
                or ref in consumed
            ):
                raise ValueError(
                    f"Setup {setup['id']}: support stock_ref {ref!r} must name "
                    "available already-produced stock."
                )
            if any(a.overlaps(b) for a in self.nodes[ref] for b in material):
                raise ValueError(
                    f"Setup {setup['id']}: borrowed support cannot overlap the cutting stock."
                )

    def roots(self, ref: str) -> frozenset[str]:
        return frozenset(atom.root for atom in self.nodes.get(ref, (Material(ref),)))

    def members(self, ref: str) -> frozenset[str] | None:
        atoms = self.nodes.get(ref, ())
        if not atoms or any(atom.workpieces is None for atom in atoms):
            return None
        return frozenset(member for atom in atoms for member in atom.workpieces)

    def descriptor(self, ref: str, owners: dict[str, str | None]) -> dict:
        atoms = self.nodes.get(ref, ())
        carried = [owners.get(atom.carries) for atom in atoms]
        members = self.members(ref)
        return {
            "roots": sorted(self.roots(ref)),
            "partitions": [
                {
                    "root": atom.root,
                    "path": [{"split": edge.split, "output": edge.output} for edge in atom.path],
                }
                for atom in atoms
                if atom.path
            ],
            "finished_solids": sorted(set(carried)) if carried and all(carried) else None,
            "workpieces": sorted(members) if members is not None else None,
            "registrations": {member: self.registrations[member] for member in sorted(members)}
            if members is not None
            else None,
        }


def stock_ancestry(plan: dict) -> dict[str, frozenset[str]]:
    """Supply ancestry from the complete route, including named retained-output identities."""
    graph = MaterialGraph(plan)
    return {ref: graph.roots(ref) for ref in graph.nodes}


def _owners(features: Any) -> dict[str, str | None]:
    if hasattr(features, "finished_feature_owners"):
        return features.finished_feature_owners
    return features.get("finished_feature_owners", {}) if isinstance(features, dict) else {}


def workpiece_status(plan: dict, ref: str, workpiece_id: str) -> bool | None:
    """Declared member presence only; unknown registration remains unknown."""
    members = MaterialGraph(plan).members(ref)
    return workpiece_id in members if members is not None else None


def _identity(
    feature_id: str | tuple[str, str], workpiece_id: str | None
) -> tuple[str | None, str]:
    if isinstance(feature_id, tuple):
        member, feature = feature_id
        if workpiece_id is not None and workpiece_id != member:
            raise ValueError("Qualified feature member contradicts workpiece_id.")
        return member, feature
    return workpiece_id, feature_id


def _registered(plan: dict, atom: Material, member: str | None = None) -> bool:
    if any(_output_pose(plan, edge.split, edge.output) is None for edge in atom.path):
        return False
    if member is None:
        return True
    entry = (workpiece_registrations(plan) or {}).get(member, {})
    pose = entry.get("pose")
    return (
        isinstance(pose, dict)
        and isinstance(pose.get("binding"), str)
        and bool(pose["binding"].strip())
        and pose["binding"].strip() != UNKNOWN
        and all(_known_vector(pose.get(key)) for key in ("origin", "x", "y", "z"))
    )


def feature_branch_status(
    plan: dict,
    ref: str,
    feature_id: str | tuple[str, str],
    features: Any,
    *,
    workpiece_id: str | None = None,
) -> bool | None:
    """Declared feature membership, independently preserving canonical source ownership."""
    graph = MaterialGraph(plan)
    atoms = graph.nodes.get(ref, ())
    if not atoms:
        return None
    member, feature = _identity(feature_id, workpiece_id)
    owners = _owners(features)
    owner = owners.get(feature)
    registered = workpiece_registrations(plan)
    if registered is not None:
        live = graph.members(ref)
        if member is None:
            if live is None or len(live) != 1:
                return None
            member = next(iter(live))
        if member not in registered or live is not None and member not in live:
            return False
        if owner is None:
            return None
        return (
            True
            if any(
                atom.workpieces is not None
                and member in atom.workpieces
                and _registered(plan, atom, member)
                for atom in atoms
            )
            else None
        )
    if member is not None:
        return None
    uncertain = False
    for atom in atoms:
        if not atom.path:
            uncertain = True
        elif owner is not None and owners.get(atom.carries) is not None:
            if owner == owners[atom.carries]:
                if _registered(plan, atom):
                    return True
                uncertain = True
        else:
            uncertain = True
    return None if uncertain else False


def feature_material_status(
    plan: dict,
    setup_id: str,
    producer_id: str,
    feature_id: str | tuple[str, str],
    features: Any,
    *,
    workpiece_id: str | None = None,
) -> bool | None:
    """Whether an upstream feature survives on this material, not just in its history."""
    if producer_id not in setup_lineage(plan, setup_id) and not producer_id.startswith("stock"):
        return False
    member, feature = _identity(feature_id, workpiece_id)
    target_status = feature_branch_status(plan, setup_id, feature, features, workpiece_id=member)
    if target_status is False:
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
    owner = _owners(features).get(feature)
    registered = workpiece_registrations(plan)
    if registered is not None and feature in _owners(features) and owner is None:
        return None
    if registered is not None and member is None:
        live = graph.members(setup_id)
        if live is None or len(live) != 1:
            return None
        member = next(iter(live))
    uncertain = False
    for atom in target:
        if registered is not None and (atom.workpieces is None or member not in atom.workpieces):
            continue
        if owner is not None and atom.carries is not None:
            carried_owner = _owners(features).get(atom.carries)
            if carried_owner is not None and owner != carried_owner:
                continue
        for prior in source:
            if registered is not None and (
                prior.workpieces is None or member not in prior.workpieces
            ):
                continue
            if owner is not None and prior.carries is not None:
                prior_owner = _owners(features).get(prior.carries)
                if prior_owner is not None and owner != prior_owner:
                    continue
            if not atom.overlaps(prior):
                continue
            if not _registered(plan, atom, member):
                uncertain = True
                continue
            if atom.path == prior.path:
                return True
            if not atom.path:
                uncertain = True
                continue
            if registered is not None:
                if owner is not None and target_status is True:
                    return True
                uncertain = True
            else:
                carried_owner = _owners(features).get(atom.carries)
                if owner is not None and carried_owner is not None:
                    if owner == carried_owner:
                        return True
                else:
                    uncertain = True
    return None if uncertain else False


def material_coverage_status(plan: dict, covering: str | list[str], target: str) -> bool | None:
    """Whether all target material flowed through covering, including nested siblings."""
    graph = MaterialGraph(plan)
    refs = [covering] if isinstance(covering, str) else covering
    covered = tuple(atom for ref in refs for atom in graph.nodes.get(ref, ()))
    required = graph.nodes.get(target, ())
    if not covered or not required:
        return None

    def covers(atom: Material) -> bool:
        matches = [other for other in covered if other.root == atom.root]
        if any(atom.path[: len(other.path)] == other.path for other in matches):
            return True
        children = {
            other.path[len(atom.path)]
            for other in matches
            if len(other.path) > len(atom.path) and other.path[: len(atom.path)] == atom.path
        }
        for split in {edge.split for edge in children}:
            siblings = {edge.output for edge in children if edge.split == split}
            if len(siblings) == 2 and all(
                covers(Material(atom.root, (*atom.path, Partition(split, name))))
                for name in siblings
            ):
                return True
        return False

    return all(covers(atom) for atom in required)
