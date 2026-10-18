"""A mill vise swivelled about setup Z (``hold.jaws_angle_deg``) and how well it is set.

The jaw frame is the setup frame turned by the swivel: there the jaws run along
``jaws_along`` as square jaws do. The swivel is set to within a setting tolerance δθ
(:func:`setting`): ``indicate_jaw`` derives it from the indicator limit, the printed DRO
move along the jaw line (dialled on the machine's measured DRO grid, so its rounding
off the line counts) and half a DRO step of display on each axis; a stated method
(``graduations``, ``protractor``, ``sine_bar``) cites it.
Unknown is never a pass.

The work turns with the jaws while the cutter feeds along a table axis, so an edge the
setup cuts lies up to δθ off its nominal angle to the rest of the part, and a point L
from the DRO zero (picked up on the work after the swivel) moves L·sin δθ across its
cut. The ``swivel`` rule holds each walled cut's angle band against δθ and reports that
shift; a horizontal face is unchanged by a turn about Z.
"""

import math

from prechips.findings import Finding
from prechips.rules.geometry_common import cutting_action
from prechips.rules.resolution import (
    SAW_OPS,
    UNKNOWN,
    _citations,
    identity,
    number,
    record,
    resolve,
)
from prechips.rules.tip_endpoints import HOLE_OPS

_CITE = "docs/rules-setup.md#swivel (swivelled vise setting tolerance and the bands it widens)"
STATED = frozenset({"graduations", "protractor", "sine_bar"})
# Actions that only plunge on the spindle axis: the swivel moves where they land, not an angle.
_POINT = HOLE_OPS | {"center", "center_drill"}


def swivel_angle(hold):
    """A vise hold's swivel about setup Z in degrees: 0.0 for none, ``UNKNOWN`` when stated
    unknown."""
    angle = record(hold).get("jaws_angle_deg", 0.0)
    return UNKNOWN if angle == UNKNOWN else float(angle) if number(angle) else 0.0


def swivelled(bundle, setup):
    """Whether ``setup`` holds the work in a mill vise with a swivel declared (known or not)."""
    hold = record(setup.get("hold"))
    if swivel_angle(hold) == 0.0:
        return False
    kind = record(resolve(bundle, "workholding", hold.get("fixture"))).get("kind")
    return kind == "vise"


def to_jaw_frame(point, angle):
    """The setup-frame XY ``point`` in the jaw frame (turned back by ``angle`` degrees)."""
    c, s = math.cos(math.radians(angle)), math.sin(math.radians(angle))
    return [point[0] * c + point[1] * s, -point[0] * s + point[1] * c]


def jaw_line_move(angle, over):
    """The table move (ΔX, ΔY) in mm that runs ``over`` mm along a jaw line at ``angle``
    degrees from setup X."""
    return over * math.cos(math.radians(angle)), over * math.sin(math.radians(angle))


def _positive(value):
    return number(value) and value > 0


def set_in(bundle, setup):
    """The setup whose ``hold.align`` set the swivel ``setup`` works in: itself where it
    mounts the vise or changes its swivel (``hold_fields.align_due``), else the nearest
    earlier setup on the same machine that did; the vise stays as that setup left it. A
    setup that is not due prints no setting step, so its own align sets nothing: only a
    setting the traveler prints is the one the cuts are held to."""
    from prechips.rules.hold_fields import align_due

    due = align_due(bundle)
    if setup["id"] in due:
        return setup
    machine = identity(bundle, setup.get("machine"), "machines")
    order = [other["id"] for other in bundle.plan["setups"]]
    for other in reversed(bundle.plan["setups"][: order.index(setup["id"])]):
        if identity(bundle, other.get("machine"), "machines") != machine:
            continue
        if other["id"] in due:
            return other
    return setup


def setting(bundle, setup):
    """How the swivel of ``setup``'s vise is set: ``method``, the jaw line's angle from
    setup X (``line_deg``), the setting tolerance ``tolerance_deg`` (``UNKNOWN`` while any
    input is), the inputs still ``unresolved``, ``invalid`` declarations and ``cite``."""
    from prechips.rules.coordinates import UNIT_MM, dro_grid, dro_grid_debt

    hold = record(setup.get("hold"))
    source = f"plan.setups.{setup['id']}.hold"
    angle = swivel_angle(hold)
    # A setup that keeps the vise as an earlier one set it inherits that setting.
    setter = set_in(bundle, setup)
    align = record(setter.get("hold")).get("align")
    align = {} if align is None else align
    aligned = f"plan.setups.{setter['id']}.hold"
    result = {
        "jaws_angle_deg": angle,
        "line_deg": UNKNOWN,
        "method": UNKNOWN,
        "tolerance_deg": UNKNOWN,
        "unresolved": [],
        "invalid": [],
        "cite": [_CITE, source],
        "set_in": setter["id"],
    }
    if angle == UNKNOWN:
        result["unresolved"].append(f"{source}.jaws_angle_deg")
    along = hold.get("jaws_along")
    if angle != UNKNOWN and along in ("x", "y"):
        result["line_deg"] = angle + (90.0 if along == "y" else 0.0)
    elif along != UNKNOWN and along not in ("x", "y"):
        result["invalid"].append(f"{source}.jaws_along must be x or y under a swivel")
    else:
        result["unresolved"].append(f"{source}.jaws_along")
    if align == UNKNOWN or record(align).get("method", UNKNOWN) == UNKNOWN:
        result["unresolved"].append(f"{aligned}.align.method")
        return result
    method = result["method"] = align["method"]
    if method in STATED:
        tolerance, cites = align.get("tolerance_deg", UNKNOWN), _citations(align.get("cite"))
        if tolerance != UNKNOWN and not _positive(tolerance):
            result["invalid"].append(f"{aligned}.align.tolerance_deg must be positive")
        elif tolerance == UNKNOWN:
            result["unresolved"].append(f"{aligned}.align.tolerance_deg")
        elif not cites:
            # A stated tolerance is evidence only with its source beside it.
            result["unresolved"].append(f"{aligned}.align.cite")
        else:
            result["tolerance_deg"] = float(tolerance)
            result["cite"].extend(cites)
        return result
    for key in ("limit_mm", "over_mm"):
        value = align.get(key, UNKNOWN)
        if value == UNKNOWN:
            result["unresolved"].append(f"{aligned}.align.{key}")
        elif not _positive(value):
            result["invalid"].append(f"{aligned}.align.{key} must be positive")
        else:
            result[key] = float(value)
    scale = UNIT_MM.get(bundle.features.get("units"))
    debt = dro_grid_debt(bundle, setup)
    if debt is not None or scale is None:
        result["unresolved"].append(debt or "feature units are not mm or in")
    else:
        step, decimals = dro_grid(bundle, setup)
        result["dro_step_mm"] = step * scale
        result["cite"].append(f"inventory.machines.{setup.get('machine')}.resolution")
    line = result["line_deg"]
    if result["unresolved"] or result["invalid"] or line == UNKNOWN:
        return result
    # The printed move is one the operator can dial: ΔX and ΔY on the DRO grid, so the
    # line from P1 to the printed P2 runs ``rounding_deg`` off the jaw line it stands for.
    move = [
        round(round(v / scale / step) * step, decimals)
        for v in jaw_line_move(line, result["over_mm"])
    ]
    length = math.hypot(*move) * scale
    result["move_dro"] = move
    off = math.degrees(math.atan2(move[1], move[0])) - line
    result["rounding_deg"] = abs((off + 180.0) % 360.0 - 180.0)
    # The indicator reads the jaw's offset across that line at P2, length·sin(error) plus
    # where the DRO really stands: a display shows each axis to within half a step, which
    # project onto the jaw's normal by |sin| and |cos| of its line, at most √2·step/2
    # whatever the error turns it to. The reading agrees with P1 within limit_mm, so the
    # jaw is at most rounding + asin((limit + √2·step/2) / length) off its printed line.
    reading = result["limit_mm"] + math.sqrt(2.0) * result["dro_step_mm"] / 2
    if reading >= length:
        result["invalid"].append(f"{aligned}.align.over_mm must exceed the indicator limit")
        return result
    result["tolerance_deg"] = result["rounding_deg"] + math.degrees(math.asin(reading / length))
    return result


def _base(action):
    return action.removeprefix("rough_").removeprefix("finish_")


def angle_band(bundle, name):
    """(± angular band in degrees or None, its source, cites) for feature ``name``: the
    feature's ``angle_tol_deg``, else none for a BASIC angle, else the title block's
    ``general_tolerances.angular_deg`` (as ``indexing`` sources it)."""
    feature = bundle.feature_definitions.get(name) if isinstance(name, str) else None
    if not isinstance(feature, dict):
        return None, f"plan.feature {name!r}", []
    if "angle_tol_deg" in feature:
        source = f"features.features.{name}.angle_tol_deg"
        return feature["angle_tol_deg"], source, _citations(feature.get("cite"), "angle_tol_deg")
    if feature.get("dimension_type") == "basic":
        return None, f"features.features.{name}.angle_tol_deg", []
    general = record(bundle.features.get("general_tolerances"))
    cites = _citations(general.get("cite"), "angular_deg")
    return general.get("angular_deg"), "features.general_tolerances.angular_deg", cites


def _reach(bundle, setup, op, memo):
    """The farthest the op's cut lies from the DRO zero in setup XY (mm), else UNKNOWN."""
    from prechips.rules.coordinates import UNIT_MM, printed_xy
    from prechips.rules.headroom import _setup_coordinates

    scale = UNIT_MM.get(bundle.features.get("units"))
    points = printed_xy(_setup_coordinates(bundle, setup, memo), op["op"])
    if points is None:
        bounds = record(op.get("stock_removal_bounds"))
        x, y = bounds.get("x"), bounds.get("y")
        if all(isinstance(v, list) and len(v) == 2 and all(map(number, v)) for v in (x, y)):
            points = [[a, b] for a in x for b in y]
    if not points or scale is None:
        return UNKNOWN
    return max(math.hypot(*p) for p in points) * scale


def registration(bundle, setup):
    """Whether the work is registered to the swivelled jaws: True when the kernel proves
    flat faces of it seated on both jaw planes (``parallel_pair``), False when it proves
    they are not, else ``UNKNOWN``."""
    kernel = getattr(bundle, "kernel", None)
    if not isinstance(kernel, dict) or kernel.get("status") != "ok":
        return UNKNOWN
    detail = record(record(kernel.get("setups")).get(setup["id"]))
    pair = detail.get("parallel_pair", UNKNOWN)
    return pair if isinstance(pair, bool) else UNKNOWN


def evaluate(bundle):
    findings, memo = [], {}
    for setup in bundle.plan["setups"]:
        if not swivelled(bundle, setup):
            continue
        set_by = setting(bundle, setup)
        tolerance = set_by["tolerance_deg"]
        unresolved, invalid = list(set_by["unresolved"]), list(set_by["invalid"])
        cite = list(set_by["cite"])
        # The swivel's tolerance reaches an edge only when the work turns with the jaws:
        # flat faces of it seated on both jaw planes (the kernel's parallel_pair). Work held
        # on a line, or not proven seated, has its own unknown angle to the jaw.
        registered = registration(bundle, setup)
        if registered is not True:
            unresolved.append(f"kernel.setups.{setup['id']}.parallel_pair")
            cite.append(f"kernel.setups.{setup['id']}.parallel_pair")
        rows, failed = [], []
        for op in setup.get("ops", []):
            action = op.get("do", UNKNOWN)
            # Non-cutting work (manual steps, a datum transfer), saws and facing turn no wall.
            if cutting_action(op) is False or action in SAW_OPS or _base(action) == "face":
                continue
            point = action in _POINT
            reach = _reach(bundle, setup, op, memo)
            row = {
                "op": op["op"],
                "feature": op.get("feature", UNKNOWN),
                "cut": "point" if point else "edge",
                "reach_mm": reach,
                "shift_mm": reach * math.sin(math.radians(tolerance))
                if number(reach) and number(tolerance)
                else UNKNOWN,
            }
            rows.append(row)
            if point:
                continue
            band, source, cites = angle_band(bundle, op.get("feature"))
            cite.extend([source, *cites])
            row["band_deg"], row["band_source"] = band if band is not None else UNKNOWN, source
            if band is None or band == UNKNOWN or not number(band):
                unresolved.append(source)
                continue
            if band < 0:
                invalid.append(f"{source} must be nonnegative")
                continue
            if number(tolerance) and registered is True:
                row["within"] = tolerance <= band
                if not row["within"]:
                    failed.append(f"op {op['op']} ({row['feature']}: ±{band:g}°)")
        numbers = {
            "jaws_angle_deg": set_by["jaws_angle_deg"],
            "work_registered": registered,
            "line_deg": set_by["line_deg"],
            "method": set_by["method"],
            "tolerance_deg": tolerance,
            "cuts": rows,
            "unresolved": sorted(set(unresolved)),
            "invalid": invalid,
        }
        for key in ("limit_mm", "over_mm", "dro_step_mm"):
            if key in set_by:
                numbers[key] = set_by[key]
        if invalid or failed:
            status = "error"
            message = (
                f"{setup['id']}: the swivel set to ±{tolerance:.3g}° does not hold "
                + ", ".join(failed)
                + "."
                if failed
                else f"{setup['id']}: swivel setting declarations are invalid: "
                + "; ".join(invalid)
                + "."
            )
        elif unresolved or tolerance == UNKNOWN:
            status = "unknown"
            message = (
                f"{setup['id']}: whether the swivel holds its cuts' angle bands is unresolved: "
                + ", ".join(sorted(set(unresolved)) or ["setting tolerance"])
                + "."
            )
        else:
            status = "pass"
            walled = any(row["cut"] == "edge" for row in rows)
            message = f"{setup['id']}: the swivel set to ±{tolerance:.3g}° " + (
                "holds every walled cut's angle band."
                if walled
                else "turns no walled cut, so it widens no angle band."
            )
        findings.append(
            Finding("swivel", setup["id"], status, numbers, list(dict.fromkeys(cite)), message)
        )
    return findings
