"""The traveler's guided-sweep recipe (docs/plan.md "Manual arcs", rules/guided_sweep.py).

A guided sweep prints no cutter-centre DRO table: the operator sets the guide, touches the
stationary cutter to the named master along one axis, locks X and Y, clears the master,
sets a stop at each end of the sweep and pushes the fixture from stop to stop. Every value
is the coordinates rule's (and the op's starting feed); nothing is recomputed.
"""

from __future__ import annotations


def _known(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _round(value, places):
    return round(value, places) if _known(value) else value


def _pair(value):
    return isinstance(value, list) and len(value) == 2 and all(map(_known, value))


_TURN = {"cw": "clockwise", "ccw": "counterclockwise"}


def steps(arc, operative, start, stop, after_rough=False, feed=None):
    """The recipe's numbered steps for one guided-sweep table ``arc`` (its ``guided`` record
    and stage); ``operative`` prints a machine target at DRO resolution, ``start`` and
    ``stop`` are the picture keys of its first and last cutter rows (may be empty) and
    ``feed`` the op's starting feed, mm/min. A finish ``after_rough`` (the same op's rough
    sweep printed first) only returns to the touch and sweeps between the same stops."""
    from prechips.sheet import _number, _text

    sweep = arc.get("guided") if isinstance(arc.get("guided"), dict) else {}
    o = operative
    guide, kind = sweep.get("guide"), sweep.get("master_kind")
    fixture, master = _text(sweep.get("fixture_name")), _text(sweep.get("master_name"))
    axis = sweep.get("touch_axis")
    letter = axis[1] if axis in ("+X", "-X", "+Y", "-Y") else "?"
    other = {"X": "Y", "Y": "X"}.get(letter, "?")
    approach = sweep.get("touch_feed", "?")
    holder = {"pivot": "arm", "rail": "sled"}.get(guide, "fixture")
    move = {"pivot": "swing", "rail": "push"}.get(guide, "move")
    result = []
    cut = sweep.get("cut_radius_mm")
    if not _pair(cut) or sweep.get("rotation") not in ("clockwise", "counterclockwise"):
        result.append(
            "STOP: guided sweep not established (cut radius or sweep unknown) — do not run."
        )
    if after_rough and arc.get("stage") == "finish":
        result.append(
            f"Finish sweep: unlock {letter} only, return it to the touch reading and lock "
            f"{letter} again."
        )
        result.extend(_cut(sweep))
        result.append(_sweep(arc, sweep, o, holder, move, start, stop, feed, stops=False))
        return result
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
            result.append(f"Swing the arm until {master}, pinned on it, is under the cutter.")
    elif guide == "rail":
        rollers = sweep.get("rollers_deg")
        where = (
            f"at {_number(rollers[0])}° and {_number(rollers[1])}°"
            if _pair(rollers)
            else "at ? and ?"
        )
        result.append(
            f"{fixture}: the work rides the sled, its R {_number(sweep.get('rail_radius_mm'))} "
            f"mm rail pushed against two rollers fixed in the T-slots {where} about the arc "
            "centre from the cutter's radial line (counterclockwise from above). The rail's "
            f"{_number(sweep.get('rail_form_error_mm'))} mm form error and the rollers' "
            f"{_number(sweep.get('roller_runout_mm'))} mm runout are carried into the cut "
            "radius below."
        )
        contacts = sweep.get("roller_contacts_mm")
        if isinstance(contacts, list) and all(map(_pair, contacts)):
            places = " and ".join(
                f"X {_number(_round(x, 1))} Y {_number(_round(y, 1))}" for x, y in contacts
            )
            result.append(
                "With the spindle over the master's edge where it will touch, set the rollers "
                f"so each bears on the rail about {places} mm from the spindle axis."
            )
        result.append(f"Push the sled until {master}, pinned on it, is under the cutter.")
    else:
        result.append("STOP: sweep guide not established — do not run.")
    result.append(
        f"Spindle stopped: bring a flute of the cutter itself to touch {master}, feeding "
        f"{_text(approach)} only. {other} needs no setting: every point of the master's touch "
        f"face stands at its radius from the arc centre. Lock X and Y there and write the DRO "
        f"{letter} reading at the touch here: ________ ."
    )
    lift = "remove the setting bar" if kind == "setting_bar" else f"lift {master} off its pins"
    result.append(f"Raise Z only and {lift}: nothing of it may stay in the sweep's path.")
    back = sweep.get("back_off_dro")
    if _known(back):
        result.append(
            f"Rough sweep: unlock {letter} only, move it {'+' if back > 0 else ''}{o(back)} "
            f"from the touch reading (the cutter {_number(sweep.get('back_off_mm'))} mm off "
            f"the line) and lock {letter} again."
        )
    result.extend(_cut(sweep))
    result.append(_stops(sweep, o, holder, move, start, stop))
    result.append(_sweep(arc, sweep, o, holder, move, start, stop, feed, stops=True))
    return result


def _cut(sweep):
    """The cut radius the touch proves against the band."""
    from prechips.sheet import _number

    cut, band = sweep.get("cut_radius_mm"), sweep.get("band_mm")
    error, radius = sweep.get("centre_error_mm"), sweep.get("master_radius_mm")
    back = sweep.get("back_off_mm")
    if not (_pair(cut) and _pair(band) and _pair(radius)):
        return []
    moved = f", moved {_number(back)} mm off the line" if _known(back) and back else ""
    return [
        f"This sweep cuts R {_number(cut[0])}–{_number(cut[1])} mm worst case: the master's "
        f"R {_number(radius[0])}–{_number(radius[1])} mm{moved}, ± "
        f"{_number(_round(error, 3))} mm the guide lets the arc centre move. The band is "
        f"R {_number(band[0])}–{_number(band[1])} mm."
    ]


def _stops(sweep, o, holder, move, start, stop):
    """Where to clamp a stop block for each end of the sweep, from the arc's ends."""
    from prechips.sheet import _number

    ends = sweep.get("ends_setup_xy")
    overrun = sweep.get("overrun_mm")
    if not (isinstance(ends, list) and len(ends) == 2 and all(map(_pair, ends))):
        return (
            f"Set the sweep's stops: with Z raised, {move} the {holder} round once and clamp a "
            "stop block on the table against it at each end of the sweep."
        )
    past = (
        f"{_number(_round(overrun, 1))} mm along the arc past the arc's end at"
        if _known(overrun) and overrun > 0
        else "on the arc's end at"
    )
    keys = [f" ({key})" if key else "" for key in (start, stop)]
    # Places on the work, not DRO targets: X and Y stay locked, so they print to 0.1.
    first, last = (f"X {_number(_round(x, 1))} Y {_number(_round(y, 1))}" for x, y in ends)
    return (
        f"Set the sweep's stops: with Z raised, {move} the {holder} until the cutter{keys[0]} "
        f"stands {past} {first} (a place on the work, measured from its X0 Y0), and clamp a "
        f"stop block on the table against the {holder}; do the same at the other end: the "
        f"cutter{keys[1]} {past} {last}."
    )


def _sweep(arc, sweep, o, holder, move, start, stop, feed, stops):
    """Start the spindle, set Z and sweep the fixture from stop to stop."""
    from prechips.sheet import _number, _text

    pressed = (
        ", keeping the rail pressed against both rollers" if sweep.get("guide") == "rail" else ""
    )
    turn = _TURN.get(arc.get("spindle_rotation"))
    path = sweep.get("path_mm")
    pace = ""
    if _known(feed) and feed > 0 and _known(path):
        pace = (
            f", at about the op's {_number(_round(feed, 0))} mm/min feed: "
            f"{_number(_round(path / feed * 60.0, 0))} s from stop to stop"
        )
    first = f" ({start})" if start else ""
    turning = f" {turn}" if turn else ""
    lead = (
        f"{move.capitalize()} the {holder} against the first stop{first}, start the "
        f"spindle{turning}"
        if stops
        else f"Raise Z, {move} the {holder} back against the first stop{first} with the "
        f"spindle running{turning}"
    )
    return (
        f"{lead} and set Z {o(arc.get('dro_tip_z'))}. With X and Y locked, move only the "
        f"{holder}: {move} it {_text(sweep.get('rotation'))} (viewed from above) to the other "
        f"stop{' (' + stop + ')' if stop else ''}, {_number(sweep.get('sweep_deg'))}°, "
        f"{_number(_round(path, 1))} mm of cutter travel along the work{pressed}{pace}."
    )
