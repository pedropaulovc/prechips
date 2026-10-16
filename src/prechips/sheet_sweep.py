"""The traveler's guided-sweep recipe (docs/plan.md "Manual arcs", rules/guided_sweep.py).

A guided sweep prints no cutter-centre DRO table: the operator sets the guide, touches the
stationary cutter to the named master along one axis, locks X and Y and sweeps the fixture
through the declared span. Every value is the coordinates rule's; nothing is recomputed.
"""

from __future__ import annotations


def _known(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _round(value, places):
    return round(value, places) if _known(value) else value


def _pair(value):
    return isinstance(value, list) and len(value) == 2 and all(map(_known, value))


def steps(arc, operative, start, stop, after_rough=False):
    """The recipe's numbered steps for one guided-sweep table ``arc`` (its ``guided`` record
    and stage); ``operative`` prints a machine target at DRO resolution, ``start`` and
    ``stop`` are the picture keys of its first and last cutter rows (may be empty). A finish
    ``after_rough`` (the same op's rough sweep printed first) only returns to the touch."""
    from prechips.sheet import _number, _text

    sweep = arc.get("guided") if isinstance(arc.get("guided"), dict) else {}
    o = operative
    guide, kind = sweep.get("guide"), sweep.get("master_kind")
    fixture, master = _text(sweep.get("fixture_name")), _text(sweep.get("master_name"))
    axis = sweep.get("touch_axis")
    letter = axis[1] if axis in ("+X", "-X", "+Y", "-Y") else "?"
    feed = sweep.get("touch_feed", "?")
    holder = {"pivot": "arm", "rail": "sled"}.get(guide, "fixture")
    result = []
    cut = sweep.get("cut_radius_mm")
    if not _pair(cut) or sweep.get("rotation") not in ("clockwise", "counterclockwise"):
        result.append(
            "STOP: guided sweep not established (cut radius or sweep unknown) — do not run."
        )
    if after_rough and arc.get("stage") == "finish":
        result.append(
            f"Finish sweep: unlock {letter} only, return it to {letter} 0 (the touch) and lock "
            f"{letter} again."
        )
        return [*result, *_cut_and_sweep(arc, sweep, o, holder, start, stop)]
    if guide == "pivot":
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
        result.append("STOP: sweep guide not established — do not run.")
    result.append(
        f"Spindle stopped: bring a flute of the cutter itself to touch {master}, feeding "
        f"{_text(feed)} only, on the cutter's radial line along {letter}. Lock X and Y there "
        f"and set DRO {letter} 0."
        + (" Raise Z only and remove the setting bar." if kind == "setting_bar" else "")
    )
    back = sweep.get("back_off_dro")
    if _known(back):
        result.append(
            f"Rough sweep: unlock {letter} only, move to {letter} {o(back)} (the cutter "
            f"{_number(sweep.get('back_off_mm'))} mm off the line) and lock {letter} again."
        )
    return [*result, *_cut_and_sweep(arc, sweep, o, holder, start, stop)]


def _cut_and_sweep(arc, sweep, o, holder, start, stop):
    """The cut radius the touch proves, then the sweep itself."""
    from prechips.sheet import _number, _text

    result = []
    cut, band = sweep.get("cut_radius_mm"), sweep.get("band_mm")
    error, radius = sweep.get("centre_error_mm"), sweep.get("master_radius_mm")
    back = sweep.get("back_off_mm")
    if _pair(cut) and _pair(band) and _pair(radius):
        moved = f", moved {_number(back)} mm off the line" if _known(back) and back else ""
        result.append(
            f"This sweep cuts R {_number(cut[0])}–{_number(cut[1])} mm worst case: the "
            f"master's R {_number(radius[0])}–{_number(radius[1])} mm{moved}, ± "
            f"{_number(_round(error, 3))} mm the guide lets the arc centre move. The band is "
            f"R {_number(band[0])}–{_number(band[1])} mm."
        )
    overrun = sweep.get("overrun_mm")
    past = (
        f"running the cutter {_number(_round(overrun, 1))} mm past each end of the arc"
        if _known(overrun) and overrun > 0
        else "stopping the cutter at each end of the arc"
    )
    pressed = (
        ", keeping the rail pressed against both rollers" if sweep.get("guide") == "rail" else ""
    )
    result.append(
        f"With Z raised clear, bring the {holder} to the start of the sweep"
        + (f" (the cutter at {start})" if start else "")
        + f"; set Z {o(arc.get('dro_tip_z'))}. With X and Y locked, move only the {holder}: "
        f"sweep it {_text(sweep.get('rotation'))} (viewed from above) through "
        f"{_number(sweep.get('sweep_deg'))}°{pressed}, {past} "
        f"({_number(_round(sweep.get('path_mm'), 1))} mm of cutter travel along the work)"
        + (f", to {stop}." if stop else ".")
    )
    return result
