"""The fixture's footprint against the mill table: never a pass until the table is known.

Travel bounds what the spindle reaches (``headroom``, ``travel``); whether the fixture
seats on the table is a separate question. It needs the table's extents (and any
extension), the allowed overhang and the table load, which are not inventory facts yet
(#272 item 1, #297). Until they are, each mill setup's row is ``unknown`` with a
``check:`` naming them, and the fixture's length/width (turned into setup X/Y by
``jaws_along`` or ``hold.pose``) is evidence. It never errors or passes. Lathe, saw-only
and manual bench setups do not seat a fixture on a mill table.
"""

import math

from prechips.findings import Finding
from prechips.model import UNIT_TOLERANCE
from prechips.rules._bench import manual_bench, not_applicable
from prechips.rules.headroom import _UNKNOWN, _length, _mapping, _numeric
from prechips.rules.resolution import resolve, saw_setup, select


def _footprint(fixture, hold, length, width):
    """(X, Y, basis) of the fixture's ``length`` x ``width`` footprint in the setup frame.

    A vise's ``length`` runs along its screw, across the jaws: ``jaws_along = "x"`` puts
    it along Y. A posed fixture rotates by its pose (y = z x x): a dividing head's
    ``length`` lies along its axis (pose z), any other fixture's along pose x, and
    ``width`` along pose y. Without that pose the footprint stays unknown."""
    if not (_numeric(length) and _numeric(width)):
        return _UNKNOWN, _UNKNOWN, "fixture length/width unknown"
    if fixture.get("kind") == "vise":
        along = hold.get("jaws_along")
        if along == "x":
            return width, length, 'jaws_along = "x": length along Y'
        if along == "y":
            return length, width, 'jaws_along = "y": length along X'
        return _UNKNOWN, _UNKNOWN, "vise jaws_along not declared"
    pose = _mapping(hold.get("pose"))
    x, z = pose.get("x"), pose.get("z")
    if not all(isinstance(v, list) and len(v) == 3 and all(map(_numeric, v)) for v in (x, z)):
        return _UNKNOWN, _UNKNOWN, "fixture pose not declared"
    # A scaled or skewed pose would stretch the footprint: unit, orthogonal axes only.
    norms = [math.hypot(*axis) for axis in (x, z)]
    if (
        any(abs(norm - 1) > UNIT_TOLERANCE for norm in norms)
        or abs(sum(a * b for a, b in zip(x, z, strict=True))) > UNIT_TOLERANCE
    ):
        return _UNKNOWN, _UNKNOWN, "fixture pose axes are not unit and orthogonal"
    y = [z[1] * x[2] - z[2] * x[1], z[2] * x[0] - z[0] * x[2], z[0] * x[1] - z[1] * x[0]]
    head = fixture.get("kind") == "dividing_head"
    along = z if head else x
    extents = [abs(along[i]) * length + abs(y[i]) * width for i in (0, 1)]
    return *extents, f"hold.pose: length along pose {'z' if head else 'x'}, width along pose y"


def evaluate(bundle):
    findings = []
    for setup in bundle.plan["setups"]:
        sid = setup["id"]
        bench = manual_bench(bundle, setup)
        if bench is not None:
            findings.append(
                not_applicable("fixture_table", setup, bench, "headroom", "fixture on a mill table")
            )
            continue
        machine = resolve(bundle, "machines", setup["machine"]) or {}
        machine_ref = select(bundle, setup["machine"], "machines")[1]
        cite = ["PLAN.md §4.1 headroom", f"plan.setups.{sid}.hold"]
        if machine.get("kind") == "lathe" or saw_setup(setup):
            findings.append(_not_on_table(sid, machine, cite))
            continue
        hold = _mapping(setup.get("hold"))
        fixture_ref = hold.get("fixture")
        fixture = resolve(bundle, "workholding", fixture_ref) or {}
        debts = {}
        length = _length(bundle, fixture, "length", "workholding", fixture_ref, debts)
        width = _length(bundle, fixture, "width", "workholding", fixture_ref, debts)
        x, y, basis = _footprint(fixture, hold, length, width)
        size = f" {x:g} x {y:g} mm" if _numeric(x) and _numeric(y) else ""
        name = fixture_ref if isinstance(fixture_ref, str) else "fixture"
        cite.extend([f"inventory: {name} length/width", f"inventory.machines.{machine_ref}"])
        numbers = {
            "fixture": fixture_ref if fixture_ref is not None else _UNKNOWN,
            "fixture_length_mm": length,
            "fixture_width_mm": width,
            "footprint_x_mm": x,
            "footprint_y_mm": y,
            "footprint_basis": basis,
            "table_mm": _UNKNOWN,
            "missing": [
                f"inventory.machines.{machine_ref} table length/width (and any extension)",
                "allowed fixture overhang",
                "table load limit",
            ],
            "measurements": [debts[key] for key in sorted(debts)],
        }
        findings.append(
            Finding(
                "fixture_table",
                sid,
                "unknown",
                numbers,
                cite,
                f"{sid}: the fixture on the table is not checked: the machine has no table "
                f"size, overhang or load facts; check: the {name}{size} footprint seats on "
                "the table within its allowed overhang and the fixture plus work weight is "
                "within the table load.",
            )
        )
    return findings


def _not_on_table(sid, machine, cite):
    lathe = machine.get("kind") == "lathe"
    return Finding(
        "fixture_table",
        sid,
        "not_applicable",
        {},
        cite,
        f"{sid}: "
        + (
            "a lathe holds the work on its spindle, not on a mill table."
            if lathe
            else "saw cuts seat no fixture on a mill table."
        ),
    )
