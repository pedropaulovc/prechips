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
    if sweep.get("guide") == "trammel":
        return _trammel_unresolved(arc, sweep, levels)
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
    if sweep.get("transverse") not in ("bar_centred", "rollers_set"):
        # Nothing else puts the cutter on the radial line (a master arc on a swing arm).
        missing.append("no radial line to centre the cutter on: use a setting bar or a rail")
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
    open_debts = sweep.get("open_debts")
    if not missing and open_debts != []:
        # The rule left something the sweep rests on unproven that no printed value shows
        # (the machine being a mill, say): never a runnable recipe.
        first = open_debts[0] if isinstance(open_debts, list) and open_debts else None
        missing.append(
            str(first).split(": ", 1)[-1] if first else "the coordinates rule did not prove it"
        )
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
    missing = []
    if not (_known(sweep.get("rail_radius_mm")) and _points(sweep.get("roller_contacts_mm"))):
        missing.append("rail radius or roller positions unknown")
    if sweep.get("rail_coverage") != "proven":
        # Numeric ends are not proof: the rule must have shown both rollers bear on the
        # rail through the travel the stops set.
        missing.append("rollers not proven on the rail through the sweep")
    return missing


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
    if sweep.get("guide") == "trammel":
        return _trammel(arc, sweep, o, start, stop, feed, final, levels)
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
        # A setting bar lies along the radial line: centred between its two sides, the
        # cutter stands on that line, so a later back-off along the touch axis is radial.
        result.append(
            f"Seat {master} on the pivot pin, lying along {_text(axis)} from it toward the spindle."
        )
        result.append(
            f"Centre {other} on {master}, spindle stopped, the cutter's flutes level with the "
            f"bar: touch its -{other} side feeding +{other} only and write the {other} "
            f"reading, then its +{other} side feeding -{other} only and write that; set "
            f"{other} to the middle of the two readings and lock {other}. The cutter now "
            "stands on the bar's centre line, the arc's radial line."
        )
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
        # Set from the locked spindle, the rollers put the rail's centre on the spindle's
        # radial line, so a later back-off along the touch axis is radial.
        result.append(
            f"With the spindle over the master's edge where it will touch, lock {other}: it "
            f"stays locked from here. Set the rollers so each bears on the rail about {places} "
            f"mm from the spindle axis: that puts the rail's centre on the spindle's {letter} "
            "line, the arc's radial line."
        )
        result.append(f"Push the sled until {master}, pinned on it, is under the cutter.")
    result.append(
        f"Spindle stopped: bring a flute of the cutter itself to touch {master}, feeding "
        f"{_text(approach)} only ({other} stays locked on the radial line). Lock {letter} "
        f"there and write the DRO {letter} reading at the touch here: ________"
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
    # Each mark's stroke lies on its arc end's radial line: run through the cutter's axis,
    # it puts the cutter's centre on that line, whatever radius the master set, where the
    # stop's measured overrun begins. Only the point the line passes through counts, never
    # the stroke's direction: a mark a cutter radius off the axis makes its printed angle's
    # rounding move the stop by thousandths.
    place = [
        f"the stroke of mark {marks[side]} (op {marks['op']}), extended, runs through the "
        "cutter's axis (lay a straightedge on it)"
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


def _positive(value):
    return _known(value) and value > 0


def _pairs(value):
    return isinstance(value, list) and len(value) == 2 and all(map(_pair, value))


# Every value the trammel card prints, with the proof that establishes it (#289): one gate.
# A field the card prints is listed here, or it does not print; each failing check names
# itself and the card is a STOP. (field, check(arc, sweep, levels), words)
TRAMMEL_PRINTED = (
    ("stage", lambda a, s, _: a.get("stage") != "rough", "a trammel cannot rough"),
    ("fixture_name", lambda a, s, _: _named(s.get("fixture_name")), "trammel fixture unknown"),
    ("pin_pair", lambda a, s, _: _named(s.get("pin_pair")), "pin pair unknown"),
    ("pin_spacing_mm", lambda a, s, _: _positive(s.get("pin_spacing_mm")), "pin spacing unknown"),
    ("rail_angle_deg", lambda a, s, _: _positive(s.get("rail_angle_deg")), "rail angle unknown"),
    ("rails_dir", lambda a, s, _: _pairs(s.get("rails_dir")), "rails' directions unknown"),
    (
        "cut_radius_mm",
        lambda a, s, _: _pair(s.get("cut_radius_mm")) and _pair(s.get("band_mm")),
        "cut radius unproven",
    ),
    ("stations_mm", lambda a, s, _: _pairs(s.get("stations_mm")), "pin stations unknown"),
    ("rail_travel_mm", lambda a, s, _: _pair(s.get("rail_travel_mm")), "rail travel unknown"),
    (
        "commissioning_record",
        lambda a, s, _: _named(s.get("commissioning_record")),
        "trammel commissioning record unknown",
    ),
    (
        "dowel_reading_mm",
        lambda a, s, _: _known(s.get("dowel_reading_mm")) and s["dowel_reading_mm"] >= 0,
        "trammel commissioning dowel reading unknown",
    ),
    (
        "stops",
        lambda a, s, _: s.get("stops") == "proven",
        "stops not proven to hold the carrier past the arc's ends",
    ),
    (
        "start",
        lambda a, s, _: s.get("start") == "air",
        "sweep start not proven clear of the stock",
    ),
    ("overrun_mm", lambda a, s, _: _known(s.get("overrun_mm")), "sweep overrun unknown"),
    (
        "carrier_turn_deg",
        lambda a, s, _: _positive(s.get("carrier_turn_deg")),
        "carrier turn unknown",
    ),
    (
        "rotation",
        lambda a, s, _: s.get("rotation") in ("clockwise", "counterclockwise"),
        "sweep direction unknown",
    ),
    (
        "spindle_rotation",
        lambda a, s, _: a.get("spindle_rotation") in _TURN,
        "spindle direction unknown",
    ),
    ("sweep_deg", lambda a, s, _: _positive(s.get("sweep_deg")), "sweep angle unknown"),
    ("path_mm", lambda a, s, _: _positive(s.get("path_mm")), "cutter travel unknown"),
    ("depths", lambda a, s, levels: _depths(a, levels) is not None, "cut depth Z unknown"),
)


def _trammel_unresolved(arc, sweep, levels=None):
    """What :data:`TRAMMEL_PRINTED` finds unproven, in the operator's words; then, as for
    every guided sweep, anything else the rule left open (``open_debts``)."""
    missing = [words for _, check, words in TRAMMEL_PRINTED if not check(arc, sweep, levels)]
    open_debts = sweep.get("open_debts")
    if not missing and open_debts != []:
        first = open_debts[0] if isinstance(open_debts, list) and open_debts else None
        missing.append(
            str(first).split(": ", 1)[-1] if first else "the coordinates rule did not prove it"
        )
    return missing


def _rail_names(rails):
    """Each rail named by the setup direction it runs from the spindle axis: the -X rail,
    the +X rail; by number when both run the same way."""
    names = []
    for x, y in rails:
        if abs(x) >= abs(y):
            names.append(("+" if x > 0 else "-") + "X")
        else:
            names.append(("+" if y > 0 else "-") + "Y")
    if names[0] == names[1]:
        return ["rail 1", "rail 2"]
    return [f"the {name} rail" for name in names]


def _trammel(arc, sweep, o, start, stop, feed, final, levels=None):
    """The trammel recipe's numbered steps (#269): the pin pair in the carriages, X/Y/Z
    locked on the rails' crossing, a stop on one rail at the pin's station for each end of
    the sweep, a dry pass, then the carrier fed by its hand lever from stop to stop."""
    from prechips.sheet import _number, _text

    missing = _unresolved(arc, sweep, levels)
    if missing:
        return [f"STOP: guided sweep not established ({', '.join(missing)}) — do not run."]
    fixture, pair = _text(sweep.get("fixture_name")), _text(sweep.get("pin_pair"))
    names = _rail_names(sweep["rails_dir"])
    stations = sweep["stations_mm"]

    def mm(value):
        return _number(_round(value, 1))

    result = [
        f"{fixture}: the work rides the carrier on its {pair} pin pair "
        f"({_number(sweep.get('pin_spacing_mm'))} mm apart on the carrier, pin centre to pin "
        f"centre), one pin in a carriage on each of two rails clamped to the table, "
        f"{names[0]} and {names[1]}, whose pin-lines cross on the spindle axis at "
        f"{_number(sweep.get('rail_angle_deg'))}° to each other. The pins, not the DRO, set "
        "where the cutter cuts.",
        f"This op neither builds nor aligns the trammel: it runs on its commissioning, kept "
        f"in {_text(sweep.get('commissioning_record'))}, where a dowel in each carriage read "
        f"within {_number(sweep.get('dowel_reading_mm'))} mm of its predicted stations along "
        "its rail. If the rails have been moved or their studs loosened since, STOP: "
        "recommission them before this op.",
        f"Seat the {pair} pins in the carriages. Check the spindle stands on the rails' "
        "crossing and lock X and Y there: neither moves for the rest of this op.",
    ]
    turn = sweep.get("carrier_turn_deg")
    overrun = sweep.get("overrun_mm")
    why = (
        f" The stops lie {mm(overrun)} mm of cutter travel beyond each end of the arc on "
        "purpose, so the cutter enters and leaves clear of the arc."
        if overrun > 0
        else ""
    )
    keys = [f" ({key})" if key else "" for key in (start, stop)]
    near = sweep["rail_travel_mm"][0]

    def read(value):
        # A rule hooks on the carriage, not the spindle axis: measure the carriage's move
        # from where it stands against the rail's near end stop.
        return (
            f"{mm(value)} mm from the spindle axis ({mm(value - near)} mm along the rail "
            f"from where the carriage stands on the rail's near end stop, {mm(near)} mm)"
        )

    result.append(
        f"Set the sweep's stops, spindle stopped and Z raised: lever the carrier until the "
        f"pin on {names[0]} stands {read(stations[0][0])}{keys[0]}, measured with a steel "
        f"rule along the rail, and clamp a stop on that rail against its carriage. Do the "
        f"same at {read(stations[0][1])} for the other end{keys[1]}. The pin on {names[1]} "
        f"then stands {mm(stations[1][0])} and "
        f"{mm(stations[1][1])} mm from the spindle axis; if it does not, STOP: the rails or "
        f"pins are not as set.{why} Then, with the cutter tip just above the work top, lever "
        "the carrier from stop to stop once: the cutter, its holder and the spindle nose "
        "must pass clear of every clamp and of the carrier, and neither carriage may reach "
        "its rail's end."
    )
    turning = _TURN[arc["spindle_rotation"]]
    path = sweep["path_mm"]
    pace = ""
    if _known(feed) and feed > 0:
        pace = (
            f", at about the op's {_number(_round(feed, 0))} mm/min feed: "
            f"{_number(_round(path / feed * 60.0, 0))} s from stop to stop"
        )
    depths = _depths(arc, levels)
    raise_z = (
        " At that stop, unlock Z and raise it until the cutter clears the work and the carrier"
    )
    again = ""
    if len(depths) > 1:
        # A stepped op sweeps once per level, top first, back from the first stop each time.
        again = (
            f"{raise_z}, lever the carrier back against the first stop, set the next Z in the "
            f"heading and lock Z; sweep the same way at each Z in the heading, in order, down "
            f"to Z {o(depths[-1])}."
        )
        raise_z = " After the last level," + raise_z[len(" At that stop,") :]
    end = raise_z + (", then stop the spindle and wait for it to stop." if final else ".")
    first = f" ({start})" if start else ""
    last = f" ({stop})" if stop else ""
    result.append(
        f"Lever the carrier against the first stop{first}, start the spindle"
        f" {turning} and set Z {o(depths[0])}, then lock "
        f"Z. With X, Y and Z locked, move only the carrier by its hand lever to the other "
        f"stop{last}: the cutter sweeps {_number(sweep.get('sweep_deg'))}° of arc about the "
        f"arc's centre, {mm(path)} mm of cutter travel along the work, while the carrier "
        f"itself turns {_number(_round(turn, 1))}° in all, "
        f"{_number(_round(turn / 2, 2))}° each side of the sweep's middle, "
        f"{_text(sweep.get('rotation'))} (viewed from above), and both pins slide along their "
        f"rails, kept seated in their carriages{pace}.{again}{end}"
    )
    return result
