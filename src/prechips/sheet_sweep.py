"""The traveler's guided-sweep recipe (docs/plan.md "Manual arcs", rules/guided_sweep.py).

A guided sweep prints no cutter-centre DRO table: the operator sets the guide, touches the
stationary cutter to the named master along one axis, locks X and Y and sweeps the fixture
through the declared span. Every value is the coordinates rule's; nothing is recomputed.
"""

from __future__ import annotations


def _known(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _pair(value):
    return isinstance(value, list) and len(value) == 2 and all(map(_known, value))


def steps(arc, operative, start, stop):
    """The recipe's numbered steps for one guided-sweep table ``arc`` (its ``guided`` record
    and stage); ``operative`` prints a machine target at DRO resolution, ``start`` and
    ``stop`` are the picture keys of its first and last cutter rows (may be empty)."""
    from prechips.sheet import _number, _text

    sweep = arc.get("guided") if isinstance(arc.get("guided"), dict) else {}
    o = operative
    guide, kind = sweep.get("guide"), sweep.get("master_kind")
    fixture, master = _text(sweep.get("fixture_name")), _text(sweep.get("master_name"))
    axis = sweep.get("touch_axis")
    letter = axis[1] if axis in ("+X", "-X", "+Y", "-Y") else "?"
    feed = sweep.get("touch_feed", "?")
    result = []
    cut, band = sweep.get("cut_radius_mm"), sweep.get("band_mm")
    if not _pair(cut) or sweep.get("rotation") not in ("clockwise", "counterclockwise"):
        result.append(
            "STOP: guided sweep not established (cut radius or sweep unknown) — do not run."
        )
    if guide == "pivot":
        holder = "arm"
        result.append(
            f"{fixture}: the work rides the swing arm, which turns on its pivot pin at the arc "
            f"centre (pivot play {_number(sweep.get('pivot_play_mm'))} mm)."
        )
        if kind == "setting_bar":
            result.append(
                f"Seat {master} on the pivot pin, lying along {_text(axis)} from it toward the "
                "spindle."
            )
        else:
            result.append(f"Swing the arm until {master} is under the cutter.")
    elif guide == "rail":
        holder = "sled"
        rollers = sweep.get("rollers_deg")
        where = (
            f"at {_number(rollers[0])}° and {_number(rollers[1])}°"
            if _pair(rollers)
            else "at ? and ?"
        )
        result.append(
            f"{fixture}: the work rides the sled, its R {_number(sweep.get('rail_radius_mm'))} "
            f"mm rail pushed against the two rollers fixed in the T-slots {where} about the "
            "arc centre from the cutter's radial line (counterclockwise from above). The "
            f"rail's {_number(sweep.get('rail_form_error_mm'))} mm form error and the rollers' "
            f"{_number(sweep.get('roller_runout_mm'))} mm runout are carried into the cut "
            "radius below."
        )
        result.append(f"Push the sled until {master}, pinned on it, is under the cutter.")
    else:
        holder = "fixture"
        result.append("STOP: sweep guide not established — do not run.")
    result.append(
        f"Spindle stopped: bring a flute of the cutter itself to touch {master}, feeding "
        f"{_text(feed)} only, on the cutter's radial line along {letter}. Lock X and Y there "
        f"and set DRO {letter} 0."
        + (" Raise Z only, and remove the setting bar." if kind == "setting_bar" else "")
    )
    back = sweep.get("back_off_dro")
    if _known(back):
        result.append(
            f"Rough sweep: unlock {letter} only, move to {letter} {o(back)} (the cutter "
            f"{_number(sweep.get('back_off_mm'))} mm off the line) and lock {letter} again."
        )
    elif arc.get("stage") == "finish":
        result.append(f"Finish sweep: {letter} at 0, the touch, locked.")
    error = sweep.get("centre_error_mm")
    radius = sweep.get("master_radius_mm")
    if _pair(cut) and _pair(band) and _pair(radius):
        result.append(
            f"This cuts R {_number(cut[0])}–{_number(cut[1])} mm worst case (the master's "
            f"R {_number(radius[0])}–{_number(radius[1])} mm, ± {_number(error)} mm the guide "
            f"lets the centre move), inside R {_number(band[0])}–{_number(band[1])} mm."
        )
    overrun = sweep.get("overrun_mm")
    past = (
        f"the cutter running {_number(overrun)} mm past each end of the arc"
        if _known(overrun) and overrun > 0
        else "the cutter stopping at each end of the arc"
    )
    result.append(
        f"Set Z {o(arc.get('dro_tip_z'))}. X and Y stay locked; only the {holder} moves. "
        f"Starting with the cutter clear{' at ' + start if start else ''}, sweep the {holder} "
        f"{_text(sweep.get('rotation'))} (viewed from above) through "
        f"{_number(sweep.get('sweep_deg'))}°, {past} "
        f"({_number(sweep.get('path_mm'))} mm of cutter travel along the work)"
        + (f", to {stop}." if stop else ".")
    )
    return result
