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


_AXES = ("+X", "-X", "+Y", "-Y")


def _points(value):
    """Two known setup X/Y points (a stop's landmarks, a rail's roller contacts)."""
    return isinstance(value, list) and len(value) == 2 and all(map(_pair, value))


def _named(value):
    return isinstance(value, str) and value not in ("", "unknown")


def _depths(arc, levels):
    """The Z (plan units, DRO) the sweep runs at, top level first: the op's axial levels
    when it steps down (``levels``, the heading's list), else the arc's one cut Z; None
    when any of them is unknown."""
    if levels is None:
        levels = [arc.get("dro_tip_z")]
    if not (isinstance(levels, list) and levels and all(map(_known, levels))):
        return None
    return levels


def _unresolved(arc, sweep, levels=None):
    """Every fact the printed recipe states that the coordinates rule left unproven, in
    the operator's words; empty only when each one is established. An unknown input never
    prints a runnable step: each value the recipe reads is checked here, not trusted to
    follow from another."""
    missing = []
    if sweep.get("guide") not in ("pivot", "rail"):
        missing.append("guide unknown")
    if not (
        _named(sweep.get("fixture_name"))
        and _named(sweep.get("master_name"))
        and sweep.get("master_kind") in ("setting_bar", "master_arc")
    ):
        missing.append("guide fixture or master unknown")
    if not (_pair(sweep.get("cut_radius_mm")) and _pair(sweep.get("band_mm"))):
        # A computed cut is proven only against a known band.
        missing.append("cut radius unproven")
    if sweep.get("touch_axis") not in _AXES or sweep.get("touch_feed") not in _AXES:
        missing.append("touch axis unknown")
    back = sweep.get("back_off_mm")
    if not _known(back) or (back > 0 and not _known(sweep.get("back_off_dro"))):
        missing.append("rough back-off unknown")
    if sweep.get("rotation") not in ("clockwise", "counterclockwise") or (
        arc.get("spindle_rotation") not in _TURN
    ):
        missing.append("sweep direction unknown")
    if not all(_known(sweep.get(key)) for key in ("sweep_deg", "path_mm", "stop_overrun_mm")):
        missing.append("sweep angle unknown")
    if not (_points(sweep.get("ends_setup_xy")) and _points(sweep.get("ends_cutter_setup_xy"))):
        # Each stop block is set where the cutter reaches an arc end: without them the
        # sweep has nothing to bound it.
        missing.append("sweep stops unknown")
    marks = sweep.get("marks")
    if not (
        isinstance(marks, dict)
        and marks.get("op") is not None
        and {marks.get("start"), marks.get("end")} == {"A", "B"}
    ):
        # The stops are set on the layout's scribed arc-end marks: nothing else places
        # them on the work.
        missing.append("arc-end marks unknown")
    if _depths(arc, levels) is None:
        missing.append("cut depth Z unknown")
    if sweep.get("start") != "air":
        # The cutter goes down at the first stop at every level: only an entry proven in
        # air is printed, never a plunge nothing checked.
        missing.append("sweep start not proven clear of the stock")
    if sweep.get("guide") == "pivot" and not _known(sweep.get("pivot_play_mm")):
        missing.append("pivot play unknown")
    if sweep.get("guide") == "rail":
        missing += _rail_unresolved(sweep)
    return missing


def established(arc, levels=None):
    """Whether ``arc``'s sweep recipe prints runnable steps, not its STOP."""
    sweep = arc.get("guided") if isinstance(arc.get("guided"), dict) else {}
    return not _unresolved(arc, sweep, levels)


def _rail_unresolved(sweep):
    """A rail sweep's unproven set-up: the rollers' angles and the rail's ends, then where
    the operator sets each roller from the spindle, which the rail's radius places."""
    if not (_pair(sweep.get("rollers_deg")) and _pair(sweep.get("rail_deg"))):
        return ["rollers or rail ends unknown"]
    if sweep.get("rail_coverage") != "proven":
        # Numeric ends are not proof: the rule must have shown both rollers bear on the
        # rail through the whole sweep.
        return ["rollers not proven on the rail through the sweep"]
    if not (_known(sweep.get("rail_radius_mm")) and _points(sweep.get("roller_contacts_mm"))):
        return ["rail radius or roller positions unknown"]
    return []


def steps(arc, operative, start, stop, after_rough=False, feed=None, final=True, levels=None):
    """The recipe's numbered steps for one guided-sweep table ``arc`` (its ``guided`` record
    and stage); ``operative`` prints a machine target at DRO resolution, ``start`` and
    ``stop`` are the picture keys of its first and last cutter rows (may be empty) and
    ``feed`` the op's starting feed, mm/min. A finish ``after_rough`` (the same op's rough
    sweep printed first) only returns to the touch and sweeps between the same stops. Only
    the op's ``final`` sweep stops the spindle at its end. ``levels`` are the op's axial
    levels (the contour heading's Z list, top first) when it steps down; the sweep then
    runs once at each."""
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
    missing = _unresolved(arc, sweep, levels)
    if missing:
        # Nothing actionable prints under an unproven sweep: a guide, touch or stop printed
        # beside a STOP would still be run.
        return [f"STOP: guided sweep not established ({', '.join(missing)}) — do not run."]
    depths = _depths(arc, levels)
    if after_rough and arc.get("stage") == "finish":
        result.append(
            f"Finish sweep, Z still raised clear: unlock {letter} only, return it to the touch "
            f"reading and lock {letter} again."
        )
        result.append(
            _sweep(arc, sweep, o, holder, move, (start, stop), feed, depths, False, final)
        )
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
    else:
        rollers = sweep.get("rollers_deg")
        where = f"at {_number(rollers[0])}° and {_number(rollers[1])}°"
        result.append(
            f"{fixture}: the work rides the sled, its R {_number(sweep.get('rail_radius_mm'))} "
            f"mm rail pushed against two rollers fixed in the T-slots {where} about the arc "
            "centre from the cutter's radial line (counterclockwise from above)."
        )
        places = " and ".join(
            f"X {_number(_round(x, 1))} Y {_number(_round(y, 1))}"
            for x, y in sweep["roller_contacts_mm"]
        )
        result.append(
            "With the spindle over the master's edge where it will touch, set the rollers "
            f"so each bears on the rail about {places} mm from the spindle axis."
        )
        result.append(f"Push the sled until {master}, pinned on it, is under the cutter.")
    result.append(
        f"Spindle stopped: bring a flute of the cutter itself to touch {master}, feeding "
        f"{_text(approach)} only. {other} needs no setting: every point of the master's touch "
        f"face stands at its radius from the arc centre. Lock X and Y there and write the DRO "
        f"{letter} reading at the touch here: ________"
    )
    lift = "remove the setting bar" if kind == "setting_bar" else f"lift {master} off its pins"
    result.append(f"Raise Z only and {lift}: nothing of it may stay in the sweep's path.")
    # The stops are set at the touch pose, before any rough back-off moves the cutter.
    result.append(_stops(sweep, o, holder, move, start, stop))
    back = sweep.get("back_off_dro")
    if _known(back):
        # Off the line is into scrap: toward the arc centre on a concave arc, away from it on
        # a convex one. The sense is the operator's check that the axis reads the right way.
        toward = "away from" if sweep.get("convex") is True else "toward"
        result.append(
            f"Rough sweep: unlock {letter} only, move it {'+' if back > 0 else ''}{o(back)} "
            f"from the touch reading (the cutter {_number(sweep.get('back_off_mm'))} mm off "
            f"the line) and lock {letter} again. The cutter must move {toward} the arc "
            f"centre; if it moves the other way, STOP: {letter} reads reversed."
        )
    result.append(_sweep(arc, sweep, o, holder, move, (start, stop), feed, depths, True, final))
    return result


def _stops(sweep, o, holder, move, start, stop):
    """Where to clamp a stop block for each end of the sweep: on the arc-end marks the
    layout scribed, set at the touch with X and Y locked."""
    from prechips.sheet import _number

    marks = sweep["marks"]
    overrun = sweep.get("stop_overrun_mm")
    # The dry pass with the cutter just over the work: the stock is still there to cut, so
    # only what stands above it (clamps, the fixture) can be checked before cutting.
    dry = (
        f" Then, with the cutter tip just above the work top, {move} the {holder} from stop "
        "to stop once: the cutter, its holder and the spindle nose must pass clear of every "
        f"clamp and of the {holder}."
    )
    keys = [f" ({key})" if key else "" for key in (start, stop)]
    # The mark is the arc's end on the work: the cutter's edge over it puts the cutter's
    # centre on the end's radial line, where the stop's measured overrun begins.
    place = [
        f"mark {marks[side]} (op {marks['op']}) stands under the cutter's edge"
        for side in ("start", "end")
    ]
    if overrun > 0:
        far = _number(_round(overrun, 1))
        on = (
            f", then on {far} mm more, measured with a steel rule along the cutter's path, "
            "outward, away from the arc"
        )
        why = (
            f" The stops lie {far} mm of cutter travel beyond the arc's ends on purpose, so the "
            "cutter enters and leaves clear of the arc."
        )
    else:
        on, why = "", ""
    return (
        "Set the sweep's stops at the touch, X and Y still locked, spindle stopped and Z "
        f"raised just clear of the work top: {move} the {holder} until {place[0]}{on}"
        f"{keys[0]}, and clamp a stop block on the table against the {holder}. Do the same "
        f"the other way: until {place[1]}{on}{keys[1]}." + why + dry
    )


def _sweep(arc, sweep, o, holder, move, keys, feed, depths, stops, final):
    """Start the spindle, set Z, sweep the fixture from stop to stop and withdraw, once at
    each of ``depths`` (top first, returning to the first stop between them); the op's
    ``final`` sweep also stops the spindle."""
    from prechips.sheet import _number, _text

    start, stop = keys
    pressed = (
        ", keeping the rail pressed against both rollers" if sweep.get("guide") == "rail" else ""
    )
    turn = _TURN[arc["spindle_rotation"]]
    path = sweep["path_mm"]
    pace = ""
    if _known(feed) and feed > 0:
        pace = (
            f", at about the op's {_number(_round(feed, 0))} mm/min feed: "
            f"{_number(_round(path / feed * 60.0, 0))} s from stop to stop"
        )
    first = f" ({start})" if start else ""
    last = f" ({stop})" if stop else ""
    raise_z = f" At that stop, raise Z until the cutter clears the work and the {holder}"
    # A stepped op sweeps once per level, top first, back from the first stop each time,
    # never straight to the full depth.
    again = ""
    if len(depths) > 1:
        again = (
            f"{raise_z}, {move} the {holder} back against the first stop and set the next Z "
            "in the heading; sweep the same way at each Z in the heading, in order, down to "
            f"Z {o(depths[-1])}."
        )
        raise_z = " After the last level," + raise_z[len(" At that stop,") :]
    # Every sweep ends withdrawn; the op's last also stops the spindle before anyone
    # reaches in to unclamp or measure.
    end = raise_z + (", then stop the spindle and wait for it to stop." if final else ".")
    lead = (
        f"{move.capitalize()} the {holder} against the first stop{first}, start the spindle {turn}"
        if stops
        else f"{move.capitalize()} the {holder} back against the same first stop (the finish "
        f"path starts at {start or 'its first point'} in the picture) with the spindle "
        f"running {turn}"
    )
    return (
        f"{lead} and set Z {o(depths[0])}. With X and Y locked, move only the "
        f"{holder}: {move} it {_text(sweep.get('rotation'))} (viewed from above) to the other "
        f"stop{last}, {_number(sweep.get('sweep_deg'))}°, "
        f"{_number(_round(path, 1))} mm of cutter travel along the work{pressed}{pace}."
        f"{again}{end}"
    )
