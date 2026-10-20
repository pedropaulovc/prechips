"""Split from zero_recipe.py by scripts/split_modules.py."""

from __future__ import annotations

import math
import re

from ...material_routes import producer_setup, setup_lineage
from ...measurements import length_keys
from ..geometry_common import TURNING_BLADE_KINDS
from ..resolution import (
    UNKNOWN,
    length_mm,
    number,
    resolve,
    setup_frame,
    setup_member_geometry,
    uncertain,
)
from ..speeds_feeds import spindle_ranges
from ..tip_endpoints import mapping, records

# Set from a bench reading, not a plan number: a trial-cut diameter or a measured edge.
MEASURED = {"trial_cut_measure", "measure_then_set"}


# Lathe ops that leave a measurable diameter a later tool can be touched off on.
TURNED = {"turn", "rough_turn", "finish_turn"}


# AUTHOR'S CHOICE: the side of the smallest square of a partly cut surface credited as
# left to touch off on. A paper touch needs a patch the operator can see, set the tool end
# over and slide paper under; a narrower sliver may hold no flat surface once the burrs of
# the cuts beside it are counted, and whether it is there at all can rest on geometry no
# operator can check. Illustrative, not measured: larger only leaves more Z unknown.
TOUCH_LAND_MM = 0.5


# How far inside its recorded box a face that fills it (``fills_bbox``) is known to hold
# surface: the kernel's 1e-6 mm side tolerance, within which a notch may run, plus the
# 5e-7 mm by which the record's 6-decimal rounding may move each side of the box.
FILL_MARGIN_MM = 1.5e-6


DIRECTIONS = {
    "x": ({"right", "away_from_spindle_axis"}, {"left", "toward_spindle_axis"}),
    "y": ({"away"}, {"toward"}),
    "z": ({"up", "toward_exposed_end"}, {"down", "toward_chuck"}),
}


def _touch_diameter(tool):
    """Use the contact tip when authored; only an absent tip can use the tool diameter."""
    field = "tip" if length_keys(tool, "tip", tool.get("units"), bare=True) else "dia"
    return length_mm(tool, field), field


def finder_procedure(bundle, setup, tool):
    """The EDGE FINDER box's facts for an X/Y pick-up with ``tool``: its type, tip Ø and
    radius, and the rpm bands it runs at on this setup's mill (its own band intersected
    with each spindle band; the gaps between spindle bands are never filled).

    ``status`` is unknown while a fact is missing or any band endpoint is unknown, and an
    error where no spindle band turns any of the finder's band. An electronic finder
    signals contact with the spindle stopped, so it needs no speed."""
    kind = tool.get("finder_type", UNKNOWN)
    tip, _ = _touch_diameter(tool)
    band = tool.get("rpm_range", UNKNOWN)
    missing = [
        name
        for name, value in (
            ("finder_type", kind),
            ("tip_in / tip_mm", tip),
            ("rpm_range", band if kind != "electronic" else "not_applicable"),
        )
        if value == UNKNOWN
    ]
    rpm, machine_rpm, status = "not_applicable", "not_applicable", "pass"
    if kind != "electronic":
        machine = resolve(bundle, "machines", setup.get("machine")) or {}
        machine_rpm = spindle_ranges(machine)
        known = (
            isinstance(band, list)
            and len(band) == 2
            and all(number(v) for v in band)
            and machine_rpm != UNKNOWN
        )
        rpm = UNKNOWN
        if known:
            rpm = [
                [max(band[0], lo), min(band[1], hi)]
                for lo, hi in machine_rpm
                if max(band[0], lo) <= min(band[1], hi)
            ]
            status = "pass" if rpm else "error"
    if status == "pass" and (missing or rpm == UNKNOWN):
        status = UNKNOWN
    return {
        "finder_type": kind,
        "tip_dia_mm": tip,
        "radius_mm": tip / 2 if number(tip) else UNKNOWN,
        "finder_rpm_range": band,
        "machine_rpm": machine_rpm,
        "rpm": rpm,
        "missing": missing,
        "status": status,
        "cite": tool.get("cite", UNKNOWN),
    }


def axis_recipe(edge_mm, radius_mm, approach, axis, jog_mm, sign=1, scale=1, paper_mm=None):
    """Return nominal Axis Set/check/mirror; jog is physically along frame +axis.

    A finder approaching from -axis subtracts its radius regardless of DRO
    direction. ``paper_mm`` is a Z touch's signed paper stand-off
    (:func:`paper_offset`: negative for a face met from -Z). ``scale`` is the display
    scale: a lathe diameter display shows twice the physical X position, so the
    contact and the jog both double.
    """
    if paper_mm is not None:
        contact = edge_mm + paper_mm if number(edge_mm) and number(paper_mm) else UNKNOWN
    elif (
        number(edge_mm) and number(radius_mm) and approach in {f"-{axis}", f"+{axis}", "indicated"}
    ):
        contact = edge_mm + (-1 if approach == f"-{axis}" else 1) * radius_mm
    else:
        contact = UNKNOWN
    shown = contact * scale if number(contact) and number(scale) else UNKNOWN
    increment = (
        sign * scale * jog_mm if sign in {-1, 1} and number(scale) and number(jog_mm) else UNKNOWN
    )
    return {
        "axis_set": shown,
        "check_reading": shown + increment if number(shown) and number(increment) else UNKNOWN,
        "mirrored_reading": shown - increment if number(shown) and number(increment) else UNKNOWN,
        "sign": sign,
    }


def _opposed_midpoint_recipe(center_mm, jog_mm, sign=1):
    """Set the authored center only after moving to two actual opposed contacts' mean.

    C− and C+ are readings taken with the same unchanged finder, before resetting
    this axis. Their equal and opposite radius corrections cancel. These symbols
    are instructions for a future setup, never recorded contact measurements.
    """
    known = all(
        number(value) and math.isfinite(value) for value in (center_mm, jog_mm)
    ) and sign in {-1, 1}
    increment = sign * jog_mm if known else UNKNOWN
    return {
        "axis_set": center_mm if known else UNKNOWN,
        "check_reading": center_mm + increment if known else UNKNOWN,
        "mirrored_reading": center_mm - increment if known else UNKNOWN,
        "sign": sign,
        "actual_contact_readings": ["C−", "C+"],
        "midpoint_move": "(C− + C+)/2",
        "axis_set_at": "measured_opposed_midpoint",
        "part_result": "not_recorded",
    }


def mounted_saw_axis_recipe(zero, blade, jog_mm, sign=1):
    """Cutting-midplane Axis Set from a stopped, flat body-side pickup, in mm.

    Physical contact/approach proof is a separate native obligation. In particular a
    numeric plane does not establish contact, and kerf and radius never set this offset.
    """
    side = zero.get("blade_side")
    edge, paper = zero.get("edge_mm"), zero.get("paper_mm")
    body, offset = blade.get("thickness_mm"), blade.get("kerf_offset_mm")
    sense = {"minus_z": 1, "plus_z": -1}.get(side)
    contact = (
        edge + sense * (paper + body / 2) + offset
        if sense and all(number(v) for v in (edge, paper, body, offset)) and paper >= 0 and body > 0
        else UNKNOWN
    )
    increment = sign * jog_mm if sign in {-1, 1} and number(jog_mm) else UNKNOWN
    return {
        "axis_set": contact,
        "check_reading": contact + increment if number(contact) and number(increment) else UNKNOWN,
        "mirrored_reading": contact - increment
        if number(contact) and number(increment)
        else UNKNOWN,
        "sign": sign,
    }


def measured(scale):
    """The bench expression a measured trial-cut diameter is set as on this display."""
    return {2: "D", 1: "D/2"}.get(scale, UNKNOWN)


def x_touch_set(scale, paper_mm, trial_cut):
    """The Axis Set of an authored lathe X touch: the measured diameter on this display,
    plus the paper it touched through, once on the radius (twice on a diameter display);
    a trial cut is its own surface and takes no paper. Unknown paper is unknown."""
    shown = measured(scale)
    if shown == UNKNOWN or trial_cut:
        return UNKNOWN if shown == UNKNOWN else f"measured {shown}"
    if not number(paper_mm) or paper_mm < 0:
        return UNKNOWN
    term = round(paper_mm * scale, 6) + 0.0
    return f"measured {shown}" + (f" + {term:g}" if term else "")


def gauge_ready(bundle, reference):
    """A trial-cut diameter is a bench reading: it needs a resolved, unflagged gauge."""
    gauge = resolve(bundle, "gauges", reference)
    return bool(gauge) and not uncertain(gauge)


def measured_edge(base):
    """The bench expression a measured edge is set as: the reading M plus ``base``."""
    if not number(base):
        return UNKNOWN
    return "M " + f"{round(base, 6) + 0.0:+.6f}".rstrip("0").rstrip(".")


def measured_z(bundle, gauge, measure, offset_mm, paper_mm):
    """A ``measure_then_set`` Z: Axis Set M + offset + paper, where M is read at the
    machine with a ready gauge and ``paper_mm`` is the paper's signed stand-off
    (:func:`paper_offset`); the returned offset + paper is unknown until the gauge
    resolves unflagged and the measurement is named (``"unknown"`` names none)."""
    named = isinstance(measure, str) and measure.strip() not in {"", UNKNOWN}
    if not (named and gauge_ready(bundle, gauge) and number(offset_mm) and number(paper_mm)):
        return UNKNOWN
    return offset_mm + paper_mm


# The corner a grooving/parting blade's Z touch sets, by the touched face's outward normal
# along setup Z: a face toward the free end (+1) is met from +Z by the blade's chuck-side
# corner, a face toward the chuck (-1) by its tailstock-side corner.
CORNERS = {1: "chuck_side", -1: "tailstock_side"}


# The side of its face (along setup Z) a blade corner meets it from: the inverse of CORNERS.
SIDES = {corner: normal for normal, corner in CORNERS.items()}


_NAMED_CORNER = re.compile(r"\b(chuck|tailstock)-side\s+corner\b", re.IGNORECASE)


# Millimetres within which a kernel end face stands at a touch's plan Z.
FACE_Z_TOL_MM = 1e-3


def blade(bundle, reference):
    """Whether tool ``reference`` is a two-cornered grooving/parting blade."""
    return (resolve(bundle, "tools", reference) or {}).get("kind") in TURNING_BLADE_KINDS


def face_normal_z(bundle, setup, face, edge):
    """The outward normal sign along setup Z (+1/-1) of ``face`` where a Z touch at plan
    ``edge`` meets it: the kernel's measured ``end_faces`` of an already-present run (this
    never starts the kernel). With no end face at ``edge`` (stock still stands on it), the
    feature's end faces decide only when they all agree; otherwise unknown."""
    kernel = mapping(getattr(bundle, "kernel", None))
    if kernel.get("status") != "ok" or not isinstance(face, str):
        return UNKNOWN
    if setup_frame(bundle, setup).get("binding", UNKNOWN) == UNKNOWN:
        return UNKNOWN
    revolved = setup_member_geometry(bundle, setup, "revolved", kernel)
    ends = [
        end
        for end in records(mapping(revolved.get(face)).get("end_faces"))
        if isinstance(end, dict) and end.get("normal_z") in CORNERS and number(end.get("z_mm"))
    ]
    scale = {"mm": 1.0, "in": 25.4}.get(bundle.features.get("units"))
    if number(edge) and scale:
        at = [end for end in ends if abs(end["z_mm"] - edge * scale) <= FACE_Z_TOL_MM]
        ends = at or ends
    signs = {end["normal_z"] for end in ends}
    return signs.pop() if len(signs) == 1 else UNKNOWN


def touch_corner(bundle, setup, touch, face, edge):
    """Which corner of a grooving/parting blade a Z touch on ``face`` at plan ``edge`` sets
    (None for any other tool): ``reference_corner`` is the corner the DRO Z then reads,
    from the face's outward normal (``corner_from`` "face normal"), else the touch's
    authored ``corner`` ("authored"), else unknown. An authored corner, or one its
    ``method`` names, that the face cannot give is ``corner_error`` and leaves the corner
    unknown: the plan is never re-read to fit."""
    if not blade(bundle, touch.get("tool")):
        return None
    normal = face_normal_z(bundle, setup, face, edge)
    derived = CORNERS.get(normal, UNKNOWN)
    authored = touch.get("corner") if touch.get("corner") in CORNERS.values() else None
    named = {match.lower() + "_side" for match in _NAMED_CORNER.findall(str(touch.get("method")))}
    claimed = named | ({authored} if authored else set())
    error = None
    if len(claimed) > 1:
        error = "names both the chuck-side and the tailstock-side corner"
    elif derived != UNKNOWN and claimed and claimed != {derived}:
        error = (
            f"names the {next(iter(claimed)).replace('_', '-')} corner, but its "
            f"{face} faces {'+Z (the free end)' if normal == 1 else '-Z (the chuck)'}: a "
            f"blade touches it with its {derived.replace('_', '-')} corner"
        )
    if error is not None:
        return {"reference_corner": UNKNOWN, "corner_from": UNKNOWN, "corner_error": error}
    if derived != UNKNOWN:
        return {"reference_corner": derived, "corner_from": "face normal"}
    if authored:
        return {"reference_corner": authored, "corner_from": "authored"}
    return {"reference_corner": UNKNOWN, "corner_from": UNKNOWN}


def touch_side(bundle, setup, touch, face, edge, lathe):
    """The side of ``face`` along setup Z (+1 toward the free end or up, -1 toward the
    chuck) a Z touch at plan ``edge`` meets it from, where its paper lies. Off a lathe a Z
    touch comes down on its face: +1. On a lathe it is the face's measured outward normal
    (:func:`face_normal_z`); without one a grooving/parting blade meets it on the side of
    the corner it sets (:func:`touch_corner`: its authored corner), unknown when that is,
    and any other tool from +Z."""
    if not lathe:
        return 1
    normal = face_normal_z(bundle, setup, face, edge)
    if normal != UNKNOWN:
        return normal
    corner = touch_corner(bundle, setup, touch, face, edge)
    return 1 if corner is None else SIDES.get(corner["reference_corner"], UNKNOWN)


def _kernel_face(bundle, face):
    """Whether ``face`` needs a native-plane producer, rather than authored bounds."""
    target = mapping(mapping(bundle.feature_definitions).get(face))
    return target.get("kind") == "face" and "bounds" not in target


def _stock_route(bundle, setup):
    """Explicit upstream stock DAG, in processing order; None for any broken route."""
    setups = records(bundle.plan.get("setups"))
    by_id = {s.get("id"): s for s in setups}
    order = {s.get("id"): i for i, s in enumerate(setups)}
    stock = mapping(bundle.plan.get("stock"))
    components = records(stock.get("components"))
    component_ids = [mapping(component).get("id") for component in components]
    if not all(isinstance(cid, str) and cid.strip() and cid != UNKNOWN for cid in component_ids):
        return None
    if len(set(component_ids)) != len(component_ids):
        return None
    supplies = {f"stock.{cid}" for cid in component_ids} if components else {"stock"}
    lineage = setup_lineage(bundle.plan, setup.get("id"))
    for current in setups:
        sid = current.get("id")
        if sid not in lineage:
            continue
        refs = current.get("stock_in")
        refs = refs if isinstance(refs, list) else [refs]
        if not refs:
            return None
        for ref in refs:
            if not isinstance(ref, str):
                return None
            if ref in supplies:
                continue
            previous = producer_setup(bundle.plan, ref)
            if previous not in by_id or order[previous] >= order[sid]:
                return None
    return [current for current in setups if current.get("id") in lineage]


def _position(ops, record):
    """The index of the op a touch is made before: the first of its ``before_ops``, else
    the op after its ``after_op``; None when neither names one of ``ops``."""
    names = [str(op.get("op")) for op in ops]
    before = record.get("before_ops")
    named = [
        names.index(str(n))
        for n in (before if isinstance(before, list) else [before])
        if str(n) in names
    ]
    if named:
        return min(named)
    after = str(record.get("after_op"))
    return names.index(after) + 1 if after in names else None


def lathe_setup(bundle, setup):
    """Whether ``setup`` runs on a lathe: a lathe-kind (or lathe-type) machine."""
    machine = resolve(bundle, "machines", setup.get("machine")) or {}
    return machine.get("kind") == "lathe" or "lathe" in str(machine.get("type", "")).lower()


def _framed(setup, op):
    """Whether ``setup``'s ``op`` cut under its Z zero: ops before the zero's ``after_op``
    run before any tool set the Z DRO, so the zero, not they, places their faces."""
    ops = records(setup.get("ops"))
    recipe = mapping(mapping(setup.get("zero")).get("z"))
    start = _position(ops, {"after_op": recipe.get("after_op")}) or 0
    return any(cut is op for cut in ops[start:])
