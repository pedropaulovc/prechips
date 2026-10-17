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


def _unresolved(sweep):
    """What the coordinates rule left unproven for a printable sweep, in the operator's
    words; empty when every fact the recipe prints is established."""
    missing = []
    if sweep.get("guide") not in ("pivot", "rail"):
        missing.append("guide unknown")
    if not _pair(sweep.get("cut_radius_mm")):
        missing.append("cut radius unproven")
    if sweep.get("touch_axis") not in ("+X", "-X", "+Y", "-Y"):
        missing.append("touch axis unknown")
    if sweep.get("rotation") not in ("clockwise", "counterclockwise"):
        missing.append("sweep direction unknown")
    if not (_known(sweep.get("sweep_deg")) and _known(sweep.get("path_mm"))):
        missing.append("sweep angle unknown")
    ends = sweep.get("ends_setup_xy")
    if not (isinstance(ends, list) and len(ends) == 2 and all(map(_pair, ends))):
        # Each stop block is set where the cutter reaches an arc end: without them the
        # sweep has nothing to bound it.
        missing.append("sweep stops unknown")
    if sweep.get("guide") == "rail":
        missing += _rail_unresolved(sweep)
    return missing


def _rail_unresolved(sweep):
    """A rail sweep's unproven set-up: the rollers' angles and the rail's ends, then where
    the operator sets each roller from the spindle, which the rail's radius places."""
    if not (_pair(sweep.get("rollers_deg")) and _pair(sweep.get("rail_deg"))):
        return ["rollers or rail ends unknown"]
    contacts = sweep.get("roller_contacts_mm")
    if not (
        _known(sweep.get("rail_radius_mm"))
        and isinstance(contacts, list)
        and len(contacts) == 2
        and all(map(_pair, contacts))
    ):
        return ["rail radius or roller positions unknown"]
    return []


def steps(arc, operative, start, stop, after_rough=False, feed=None, final=True):
    """The recipe's numbered steps for one guided-sweep table ``arc`` (its ``guided`` record
    and stage); ``operative`` prints a machine target at DRO resolution, ``start`` and
    ``stop`` are the picture keys of its first and last cutter rows (may be empty) and
    ``feed`` the op's starting feed, mm/min. A finish ``after_rough`` (the same op's rough
    sweep printed first) only returns to the touch and sweeps between the same stops. Only
    the op's ``final`` sweep stops the spindle at its end."""
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
    missing = _unresolved(sweep)
    if missing:
        # Nothing actionable prints under an unproven sweep: a guide, touch or stop printed
        # beside a STOP would still be run.
        return [f"STOP: guided sweep not established ({', '.join(missing)}) — do not run."]
    if after_rough and arc.get("stage") == "finish":
        result.append(
            f"Finish sweep, Z still raised clear: unlock {letter} only, return it to the touch "
            f"reading and lock {letter} again."
        )
        result.append(
            _sweep(arc, sweep, o, holder, move, start, stop, feed, stops=False, final=final)
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
    result.append(_stops(sweep, o, holder, move, start, stop))
    result.append(_sweep(arc, sweep, o, holder, move, start, stop, feed, stops=True, final=final))
    return result


def _stops(sweep, o, holder, move, start, stop):
    """Where to clamp a stop block for each end of the sweep, from the arc's ends."""
    from prechips.sheet import _number

    ends = sweep.get("ends_setup_xy")
    overrun = sweep.get("overrun_mm")
    # The dry pass with the cutter just over the work: the stock is still there to cut, so
    # only what stands above it (clamps, the fixture) can be checked before cutting.
    dry = (
        f" Then, with the cutter tip just above the work top, {move} the {holder} from stop "
        "to stop once: the cutter, its holder and the spindle nose must pass clear of every "
        f"clamp and of the {holder}."
    )
    keys = [f" ({key})" if key else "" for key in (start, stop)]

    def at(point):
        # Places on the work, not DRO targets: X and Y stay locked, so they print to 0.1.
        return f"X {_number(_round(point[0], 1))} Y {_number(_round(point[1], 1))}"

    centres = sweep.get("ends_cutter_setup_xy")
    centres = centres if isinstance(centres, list) and all(map(_pair, centres)) else None
    # The landmark is on the cutter's own path: its edge reaches the arc's end when its
    # centre stands on the end's radial line, a cutter radius off the arc.
    place = [
        f"edge reaches the arc's end at {at(end)}"
        + (f" (its centre at {at(centre)})" if centre else "")
        for end, centre in zip(ends, centres or [None, None], strict=True)
    ]
    if _known(overrun) and overrun > 0:
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
        f"Set the sweep's stops, spindle stopped and Z raised: {move} the {holder} until the "
        f"cutter's {place[0]}{on}{keys[0]}, and clamp a stop block on the table against the "
        f"{holder}. Do the same at the other end: the cutter's {place[1]}{on}{keys[1]}." + why + dry
    )


def _sweep(arc, sweep, o, holder, move, start, stop, feed, stops, final):
    """Start the spindle, set Z, sweep the fixture from stop to stop and withdraw; the
    ``final`` sweep of the op also stops the spindle."""
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
    turning = f" {turn}" if turn else ""
    first = f" ({start})" if start else ""
    last = f" ({stop})" if stop else ""
    # Every sweep ends withdrawn; the op's last also stops the spindle before anyone
    # reaches in to unclamp or measure.
    end = f" At that stop, raise Z until the cutter clears the work and the {holder}" + (
        ", then stop the spindle and wait for it to stop." if final else "."
    )
    lead = (
        f"{move.capitalize()} the {holder} against the first stop{first}, start the "
        f"spindle{turning}"
        if stops
        else f"{move.capitalize()} the {holder} back against the same first stop (the finish "
        f"path starts at {start or 'its first point'} in the picture) with the spindle "
        f"running{turning}"
    )
    return (
        f"{lead} and set Z {o(arc.get('dro_tip_z'))}. With X and Y locked, move only the "
        f"{holder}: {move} it {_text(sweep.get('rotation'))} (viewed from above) to the other "
        f"stop{last}, {_number(sweep.get('sweep_deg'))}°, "
        f"{_number(_round(path, 1))} mm of cutter travel along the work{pressed}{pace}.{end}"
    )
