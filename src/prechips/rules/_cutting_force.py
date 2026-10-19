"""The upper-bound cutting force of an end-mill milling op, shared by every holding
provider (docs/rules-physics.md#cutting-force; docs/design/area-hold.md §4).

Kienzle, peripheral milling, every engaged tooth at the maximum chip:

    φ_e   = arccos(1 − 2·ae/D)
    h_max = fz·sin φ_e when φ_e ≤ π/2, else fz
    n_e   = ceil(z·φ_e / 2π)
    F_t   = n_e·kc1·ap·h_max^(1 − mc)
    F_xy  = F_t·sqrt(1 + k_r²)      lateral, in the seat plane
    F_z   = F_t·tan β               lift when the helix hand equals the cutting hand

The model covers endmill-family tools on facing, pocketing and profile actions that
enter from the side. A plunge or an unproven entry, a drill-family tool and any other
cutting op stay unknown; a noncutting action is not applicable. A missing input is never
replaced by a default: only ``ae`` has a bound (a full slot, ``ae = D``).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Literal

from ..measurements import cited_fact
from .resolution import (
    HAND_THREAD,
    MANUAL,
    UNKNOWN,
    _citations,
    length_mm,
    number,
    resolve,
    uncertain,
)
from .speeds_feeds import DRILL_KINDS, chip_load, stock_material_class
from .tip_endpoints import FACING, HOLE_OPS, POCKETING, mapping, records

CITE = "docs/rules-physics.md#cutting-force (Kienzle peripheral milling, upper bound)"
MILLING = FACING | POCKETING | {"profile", "rough_profile", "finish_profile"}
_ENDMILL_KINDS = {"endmill", "endmill_set"}
# Tools that load the work by thrust and torque, not by a peripheral chip.
_THRUST_KINDS = DRILL_KINDS | {
    "spot_drill",
    "center_drill",
    "reamer",
    "reamers",
    "tap",
    "tap_set",
    "tap_die_set",
}
_HANDS = ("right", "left")
# A tooth count z·φ_e/2π within this relative distance of an integer is that integer
# (float residue, ~1e-16); any larger offset still rounds up.
_TOOTH_RESIDUE = 1e-12

type Status = Literal["computed", "unknown", "not_applicable"]
type Entry = Literal["side", "plunge", "unknown"]
type Sense = Literal["lift", "push"]


@dataclass(frozen=True)
class CuttingForce:
    status: Status
    lateral_n: float | str = UNKNOWN
    axial_n: float | str = UNKNOWN
    axial_sense: Sense | str = UNKNOWN
    inputs: dict = field(default_factory=dict)
    debts: list[str] = field(default_factory=list)
    cite: list[str] = field(default_factory=lambda: [CITE])


def entry_of(path) -> Entry:
    """How a coordinates level-path record (rules/level_entry.py) goes down: ``side``
    when it lowers above the stock or every down stands in air, ``plunge`` when any goes
    into material, ``unknown`` without a record."""
    downs = records(mapping(path).get("entries"))
    if not downs:
        return "unknown"
    if "lowered" in path:
        return "side"
    return "side" if all(mapping(down).get("air") is True for down in downs) else "plunge"


def _finite(value):
    return number(value) and math.isfinite(value)


def _material(bundle, debts):
    """``(kc1, mc, k_r, cite)`` from the stock class's one cited ``[[material]]`` row."""
    stock = mapping(bundle.plan.get("stock"))
    material_class = stock_material_class(bundle)
    if stock.get("material_verify", False) is not False:
        debts.append("material: the stock material's material_verify is not false")
    if material_class == UNKNOWN:
        debts.append("material: the stock material has no cutting-data material class")
        return UNKNOWN, UNKNOWN, UNKNOWN, []
    rows = [
        row
        for row in records(mapping(bundle.cutting_data).get("material"))
        if isinstance(row, dict) and row.get("material_class") == material_class
    ]
    if len(rows) != 1:
        debts.append(f"material: {len(rows)} cutting-data material rows match {material_class}")
        return UNKNOWN, UNKNOWN, UNKNOWN, []
    row = rows[0]
    cite = _citations(row.get("cite"))
    if not cite or uncertain(row):
        debts.append(f"material: the {material_class} row is uncited or flagged verify")
    domains = {
        "kc1_n_per_mm2": (lambda v: v > 0, "> 0"),
        "mc": (lambda v: 0 <= v < 1, "0 ≤ mc < 1"),
        "radial_ratio": (lambda v: v >= 0, "≥ 0"),
    }
    values = []
    for name, (inside, text) in domains.items():
        value = row.get(name, UNKNOWN)
        if not _finite(value):
            debts.append(f"{name}: the {material_class} row has no {name}")
            values.append(UNKNOWN)
        elif not inside(value):
            debts.append(f"{name}: {value:g} is outside its domain {text}")
            values.append(UNKNOWN)
        else:
            values.append(value)
    return *values, cite


def _sense(helix_hand, hand) -> Sense:
    """Lift when the hands are equal or either is unknown (the bound), push otherwise."""
    if helix_hand in _HANDS and hand in _HANDS and helix_hand != hand:
        return "push"
    return "lift"


def _scope(action, kind):
    """``(status, reason)`` when the op is outside the model, else None."""
    if action == UNKNOWN:
        return "unknown", "operation: the op's action is unknown"
    if action in HAND_THREAD:
        return (
            "not_applicable",
            "operation: manual thread torque is outside the powered cutter model",
        )
    if action in MANUAL:
        return "not_applicable", f"operation: {action} does not cut"
    if kind in _THRUST_KINDS:
        return "unknown", f"tool: no thrust/torque force model for {kind}"
    if kind not in _ENDMILL_KINDS:
        return "unknown", f"tool: no force model for tool kind {kind}"
    if action in HOLE_OPS:
        return "unknown", f"entry: no axial-entry force model for an end mill's {action}"
    if action not in MILLING:
        return "unknown", f"operation: no force model for {action}"
    return None


def milling_force(bundle, op, entry: Entry) -> CuttingForce:
    """The bound of ``op``'s lateral and axial cutting force. ``entry`` is how its path
    goes down (:func:`entry_of`), which the caller reads from coordinates."""
    action = op.get("do", UNKNOWN)
    tool = resolve(bundle, "tools", op.get("tool", UNKNOWN)) or {}
    kind = tool.get("kind", UNKNOWN)
    inputs = {"operation": action, "tool": op.get("tool", UNKNOWN), "tool_kind": kind}
    scoped = _scope(action, kind)
    if scoped is not None:
        status, reason = scoped
        return CuttingForce(status, inputs=inputs, debts=[reason])
    if entry != "side":
        why = "its path plunges" if entry == "plunge" else "its entry is unproven"
        return CuttingForce(
            "unknown", inputs=inputs, debts=[f"entry: no axial-entry force model ({why})"]
        )

    debts, cite = [], [CITE]
    if uncertain(tool):
        debts.append("tool: the selected tool is unresolved or flagged verify")
    diameter = length_mm(tool, "dia")
    if not (_finite(diameter) and diameter > 0):
        debts.append("D: the tool diameter is unknown, unverified or not > 0")
        diameter = UNKNOWN
    flutes = tool.get("flutes", UNKNOWN)
    if not (type(flutes) is int and flutes >= 1):
        debts.append("z: the tool's flutes are not one integer ≥ 1")
        flutes = UNKNOWN
    helix = cited_fact(tool, "helix_deg", domain=((lambda v: 0 <= v < 90), "0 ≤ β < 90"))
    if not helix["verified"]:
        debts.append(f"helix_deg: {helix['reason']}")
    cite += helix["cite"]
    fz, fz_cite, why = chip_load(bundle, op, tool)
    if why is not None:
        debts.append(f"fz: {why}")
    else:
        cite += _citations(fz_cite)
    ap = op.get("doc_mm", UNKNOWN)
    if not (_finite(ap) and ap > 0):
        debts.append("ap: the op's doc_mm is not > 0")
        ap = UNKNOWN
    ae, basis = op.get("ae_mm", UNKNOWN), "op_ae_mm"
    if not number(ae):
        ae, basis = diameter, "bound_full_slot"
    elif not (_finite(ae) and ae > 0 and (diameter == UNKNOWN or ae <= diameter + 1e-9)):
        debts.append(f"ae: ae_mm {ae:g} is outside its domain 0 < ae ≤ D")
        ae = UNKNOWN
    kc1, mc, ratio, row_cite = _material(bundle, debts)
    cite += row_cite
    helix_hand, hand = tool.get("helix_hand", UNKNOWN), tool.get("hand", UNKNOWN)
    inputs.update(
        D_mm=diameter,
        z=flutes,
        helix_deg=helix["value"],
        helix_hand=helix_hand if helix_hand in _HANDS else UNKNOWN,
        hand=hand if hand in _HANDS else UNKNOWN,
        fz_mm=fz,
        ap_mm=ap,
        ae_mm=ae,
        ae_basis=basis,
        kc1_n_per_mm2=kc1,
        mc=mc,
        radial_ratio=ratio,
    )
    if debts:
        return CuttingForce("unknown", inputs=inputs, debts=debts, cite=cite)

    phi = math.acos(max(-1.0, min(1.0, 1 - 2 * ae / diameter)))
    h_max = fz * math.sin(phi) if phi <= math.pi / 2 else fz
    teeth = flutes * phi / (2 * math.pi)
    nearest = round(teeth)
    whole = abs(teeth - nearest) <= _TOOTH_RESIDUE * max(1.0, teeth)
    engaged = max(1, nearest if whole else math.ceil(teeth))
    tangential = engaged * kc1 * ap * h_max ** (1 - mc)
    inputs.update(phi_e_deg=math.degrees(phi), h_max_mm=h_max, n_e=engaged, tangential_n=tangential)
    return CuttingForce(
        "computed",
        lateral_n=tangential * math.sqrt(1 + ratio**2),
        axial_n=tangential * math.tan(math.radians(helix["value"])),
        axial_sense=_sense(helix_hand, hand),
        inputs=inputs,
        cite=cite,
    )
