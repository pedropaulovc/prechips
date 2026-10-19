"""EL400 ABS Axis Set recipes; approach side is not jog polarity."""

from __future__ import annotations

from prechips.rules.zero_recipe.faces import _boundary, _tops, paper_offset, x_face_state
from prechips.rules.zero_recipe.native import _retouch_recipe
from prechips.rules.zero_recipe.tool_setting import (
    TOOL_SETTING_CITES,
    _carried_setting,
    _corner_recorder,
    _face_checker,
    tool_changes,
    tool_setting,
    toolpost,
)
from prechips.rules.zero_recipe.touch import (
    DIRECTIONS,
    MEASURED,
    _position,
    _touch_diameter,
    axis_recipe,
    finder_procedure,
    gauge_ready,
    lathe_setup,
    measured,
    measured_edge,
    measured_z,
    touch_side,
    x_touch_set,
)

from ...findings import Finding
from ...measurements import length_debt, measurement_checklist
from .._bench import manual_bench, manual_thread_setup, not_applicable
from ..resolution import (
    MANUAL,
    SAW_OPS,
    SLITTING_SAW_MODEL_REASON,
    UNKNOWN,
    UNRESOLVED_SAW_MODEL_REASON,
    identity,
    number,
    plan_frame_cite,
    resolve,
    saw_setup,
    setup_frame,
    slitting_saw,
    spindle_saw,
    uncertain,
)
from ..swivel import swivel_angle, swivelled
from ..tip_endpoints import mapping, records, stock_states


def _mechanical_zero(bundle, setup):
    """Keep authored physical pickups separate from nominal CAD/frame coordinates.

    Mechanical-dial accuracy and dial-to-part registration are not inferred from a
    source procedure, edge_mm = 0, or a nominal frame. Until independent physical
    evidence exists they remain a held process recipe, never electronic Axis Sets.
    """
    from ..coordinates import handwheel_readout, readout_kind

    readout = handwheel_readout(bundle)
    zero = mapping(setup.get("zero"))
    axes = {
        axis: {
            key: touch.get(key, UNKNOWN)
            for key in ("procedure", "method", "dial_setting", "face", "feature", "tool", "gauge")
        }
        for axis in ("x", "y", "z")
        if isinstance(touch := zero.get(axis), dict)
    }
    needed = ("x", "z") if lathe_setup(bundle, setup) else ("x", "y", "z")
    missing = [
        f"{axis.upper()} physical dial setting"
        for axis in needed
        if not number(mapping(axes.get(axis)).get("dial_setting"))
    ]
    if not axes:
        missing.append("physical zero/pickup procedure")
    for field in ("graduation", "calibration", "backlash"):
        if readout[field] == UNKNOWN:
            missing.append(field)
    directions = mapping(mapping(bundle.plan.get("dro")).get("direction"))
    missing.extend(
        f"{axis.upper()} direction"
        for axis in needed
        if directions.get(axis, UNKNOWN) == UNKNOWN
    )
    if readout["units"] not in {"mm", "in"}:
        missing.append("readout units")
    if lathe_setup(bundle, setup) and readout["x_scale"] == UNKNOWN:
        missing.append("X diameter/radius scale")
    kind = readout_kind(bundle)
    reason = readout["debt"] if kind == "handwheel" else "readout kind is unknown"
    return Finding(
        "zero_check",
        setup["id"],
        UNKNOWN,
        {
            "frame": setup.get("frame", UNKNOWN),
            "readout": readout,
            "axes": axes,
            "physical_setting_debt": missing,
            "tool_touches": records(zero.get("tool_touches")),
        },
        [
            "docs/plan.md readout and zero recipe",
            *plan_frame_cite(bundle, setup),
            *(
                [cite]
                if isinstance(cite := mapping(bundle.plan.get("dro")).get("cite"), str)
                else cite
                if isinstance(cite, list)
                else []
            ),
        ],
        f"{setup['id']}: authored pickup procedures and nominal targets "
        f"do not certify physical settings: {reason}."
        + (" Unknown: " + ", ".join(missing) + "." if missing else ""),
    )


def evaluate(bundle):
    from ..coordinates import dro_grid_debt, dro_grid_measurements

    result = []
    dro = mapping(bundle.plan.get("dro"))
    for setup in bundle.plan["setups"]:
        bench = manual_bench(bundle, setup) or manual_thread_setup(bundle, setup)
        if bench is not None:
            result.append(
                not_applicable("zero_check", setup, bench, "zero recipe", "DRO zero to set")
            )
            continue
        if saw_setup(bundle, setup):
            result.append(
                Finding(
                    "zero_check",
                    setup["id"],
                    "not_applicable",
                    {"frame": setup.get("frame", UNKNOWN)},
                    ["PLAN.md §4.1 zero recipe", *plan_frame_cite(bundle, setup)],
                    "A dedicated saw setup locates its cut by cut_plane; no spindle XYZ "
                    "zero is set.",
                )
            )
            continue
        from ..coordinates import readout_kind

        if readout_kind(bundle) != "digital":
            result.append(_mechanical_zero(bundle, setup))
            continue
        spindle_ops = [op for op in setup["ops"] if spindle_saw(bundle, setup, op)]
        spindle_debt = "; ".join(
            dict.fromkeys(
                SLITTING_SAW_MODEL_REASON
                if slitting_saw(bundle, op)
                else UNRESOLVED_SAW_MODEL_REASON
                for op in spindle_ops
            )
        )
        spindle_numbers = (
            {
                "spindle_saw_ops": [op["op"] for op in spindle_ops],
                "spindle_saw_debt": spindle_debt,
            }
            if spindle_ops
            else {}
        )
        ordinary = [op for op in setup["ops"] if op.get("do") not in MANUAL | SAW_OPS]
        if spindle_ops and not ordinary:
            result.append(
                Finding(
                    "zero_check",
                    setup["id"],
                    "error" if dro.get("mode", UNKNOWN) not in {"abs", UNKNOWN} else UNKNOWN,
                    {
                        "frame": setup.get("frame", UNKNOWN),
                        **spindle_numbers,
                    },
                    ["PLAN.md §4.1 zero recipe", *plan_frame_cite(bundle, setup)],
                    f"{setup['id']}: {spindle_debt}; mounted-blade zero setting is unresolved.",
                )
            )
            continue
        frame = setup_frame(bundle, setup)
        lathe = lathe_setup(bundle, setup)
        zero = mapping(setup.get("zero"))
        ops = records(setup.get("ops"))
        states = list(stock_states(bundle, setup))
        spindle_tools = {
            identity(bundle, op["tool"], "spindle")
            for op in spindle_ops
            if op.get("tool") not in (None, UNKNOWN)
        }

        def unsupported_touch(reference, tools=spindle_tools):
            return (
                reference not in (None, UNKNOWN) and identity(bundle, reference, "spindle") in tools
            )

        # The top as each op left it, unknown where no stated depth proves it.
        tops = [z for z, _ in _tops(bundle, setup, states)]
        axes = {}
        # Blade Z touches whose authored corner the touched face cannot give. An unknown
        # corner leaves the Axis Set known: the blade ops whose Zs it reads stay unknown
        # under coordinates instead.
        corner_errors = []
        blade_corner = _corner_recorder(bundle, setup, lathe, corner_errors)
        # Z touches that set their DRO off where their face stands, or on a face standing
        # at an unknown Z (:func:`_face_checker`).
        face_errors, face_unknowns = [], []
        face_check = _face_checker(bundle, setup, face_errors, face_unknowns)
        # The edge finder's procedure facts (:func:`finder_procedure`) of each pick-up.
        finder_status = set()
        tip_measurements = []
        # X/Y pick-ups a swivelled vise leaves unproven: the work's edges stand at the
        # swivel to the travel, so only an indicated centre sets X or Y (#300).
        swivel = swivel_angle(mapping(setup.get("hold"))) if swivelled(bundle, setup) else 0.0
        slanted = []

        unknown = (
            bool(spindle_ops)
            or not frame
            or frame.get("binding") == UNKNOWN
            or dro.get("controller", UNKNOWN) == UNKNOWN
            or dro.get("radius_mode") == UNKNOWN
            or dro.get("mode", UNKNOWN) == UNKNOWN
        )
        bad = dro.get("mode", UNKNOWN) not in {"abs", UNKNOWN}
        # A setup whose every spindle op is a guided sweep sets X and Y by touching the
        # cutter to its master and locks them: it picks up no X/Y zero (#255).
        from ..guided_sweep import touch_set, trammel_set

        swept = [] if lathe else touch_set(setup)
        # A trammel's rails fix the cut: no X/Y handwheel move, so no X/Y DRO sign (#269).
        railed = bool(swept) and trammel_set(setup)
        # An X/Y pickup moves the table off the rails' crossing the trammel cuts on.
        railed_errors = [
            f"zero.{axis} picks up an edge, but the trammel ({', '.join(map(str, swept))}) "
            "cuts where its rails cross the spindle axis with X and Y locked: remove it"
            for axis in ("x", "y")
            if railed and isinstance(zero.get(axis), dict)
        ]
        for axis in ("x", "y", "z"):
            recipe = zero.get(axis)
            if not isinstance(recipe, dict):
                if axis in ("x", "y") and railed:
                    continue
                if axis in ("x", "y") and swept:
                    # No edge pickup, but the sweep's touch feed and rough back-off still
                    # move this axis by its DRO sign: a reversed or undeclared direction
                    # is the same error or debt it is under a pickup.
                    direction = mapping(dro.get("direction")).get(axis, UNKNOWN)
                    positive, negative = DIRECTIONS[axis]
                    bad |= direction in negative
                    unknown |= direction not in positive and direction not in negative
                    continue
                if axis != "y" or not lathe:
                    unknown = True
                continue
            direction = mapping(dro.get("direction")).get(axis, UNKNOWN)
            positive, negative = DIRECTIONS[axis]
            sign = 1 if direction in positive else -1 if direction in negative else UNKNOWN
            # Frames are installed machine-aligned: a flipped model frame changes
            # the model basis, not the machine's authored right/away/up convention.
            bad |= sign == -1
            if unsupported_touch(recipe.get("tool")):
                axes[axis] = {
                    **recipe,
                    "axis_set": UNKNOWN,
                    "check_reading": UNKNOWN,
                    "mirrored_reading": UNKNOWN,
                    "axis_set_status": UNKNOWN,
                    "tool_setting_state": "unsupported_spindle_saw",
                }
                unknown = True
                continue
            edge = recipe.get("edge_mm", UNKNOWN)
            paper = recipe.get("paper_mm", UNKNOWN) if axis == "z" else None
            tool = resolve(bundle, "spindle", recipe.get("tool")) or {}
            method = recipe.get("method")
            indicated = recipe.get("from") == "indicated"
            if swivel and axis != "z" and not indicated:
                slanted.append(axis.upper())
            radius = (
                "not_applicable"
                if axis == "z" or method == "trial_cut_measure"
                else 0
                if indicated
                else _touch_diameter(tool)[0]
            )
            if not indicated and number(radius):
                radius /= 2
            if axis != "z" and not indicated and method not in MEASURED and tool:
                _, field = _touch_diameter(tool)
                category, tool_ref = identity(bundle, recipe.get("tool"), "spindle")
                if tool.get("kind") != UNKNOWN:
                    debt = length_debt(tool, field, category, tool_ref)
                    if debt:
                        tip_measurements.append(debt)
            # A named after_op that does not resolve places the touch nowhere known,
            # never at the initial boundary.
            done = _boundary(ops, {"after_op": recipe.get("after_op")})
            if axis == "z" and recipe.get("face") == "top":
                # The top as the ops up to and including after_op left it, not the
                # incoming stock top.
                edge = tops[done] if done != UNKNOWN else UNKNOWN
            # Paper stands the tool off its face on the side it meets the face from.
            face = recipe.get("face", recipe.get("feature"))
            stand_off = None
            credited, carried = [], False
            if axis == "z":
                edge, credited, carried = face_check(
                    {**recipe, "from": recipe.get("from", UNKNOWN)},
                    face,
                    edge,
                    done,
                    "the Z zero touch",
                )
                side = touch_side(bundle, setup, recipe, face, edge, lathe)
                stand_off = paper_offset(paper, side)
            # Only an authored radius/diameter display fixes the lathe X jog scale.
            scale = (
                {True: 1, False: 2}.get(dro.get("radius_mode"), UNKNOWN)
                if axis == "x" and lathe
                else 1
            )
            values = axis_recipe(
                edge,
                radius,
                recipe.get("from"),
                axis,
                recipe.get("check_jog_mm", UNKNOWN),
                sign,
                scale,
                stand_off,
            )
            if carried:
                _carried_setting(bundle, setup, values, "axis_set", carried)
            gauge = gauge_ready(bundle, recipe.get("gauge"))
            if method == "trial_cut_measure":
                # The diameter is measured at the machine after the cut, like paper
                # thickness: the recipe is complete once the gauge and jog are known.
                display = measured(scale) if axis == "x" and lathe else UNKNOWN
                jog = recipe.get("check_jog_mm", UNKNOWN)
                increment = (
                    sign * scale * jog
                    if sign in {-1, 1} and number(scale) and number(jog)
                    else UNKNOWN
                )
                known = display != UNKNOWN and number(increment) and gauge
                values = {
                    "axis_set": f"measured {display}" if known else UNKNOWN,
                    "check_reading": f"{display} {increment:+g}" if known else UNKNOWN,
                    "mirrored_reading": f"{display} {-increment:+g}" if known else UNKNOWN,
                    "sign": sign,
                }
            elif method == "measure_then_set":
                # The edge is read at the machine (M), like a trial-cut diameter: Axis
                # Set M + offset + paper, then jog from it.
                base = (
                    measured_z(
                        bundle,
                        recipe.get("gauge"),
                        recipe.get("measure"),
                        recipe.get("offset_mm", UNKNOWN),
                        stand_off,
                    )
                    if axis == "z"
                    else UNKNOWN
                )
                jog = recipe.get("check_jog_mm", UNKNOWN)
                step = sign * jog if sign in {-1, 1} and number(jog) else UNKNOWN
                known = number(base) and number(step)
                values = {
                    "axis_set": measured_edge(base) if known else UNKNOWN,
                    "check_reading": measured_edge(base + step) if known else UNKNOWN,
                    "mirrored_reading": measured_edge(base - step) if known else UNKNOWN,
                    "sign": sign,
                }
            row = dict(recipe)
            row.pop("retouch_after", None)
            row.update(
                values,
                edge_mm=edge,
                radius_mm=radius,
                paper_mm=paper if paper is not None else "not_applicable",
                jog_mm=recipe.get("check_jog_mm", UNKNOWN),
                dro_direction=direction,
                axis_set_status=(
                    "measured"
                    if method in MEASURED and values["axis_set"] != UNKNOWN
                    else "computed"
                    if number(values["axis_set"])
                    else UNKNOWN
                ),
            )
            if credited:
                row["credited_faces"] = credited
            if method in MEASURED:
                row["check_expression"] = values["check_reading"]
                row["mirrored_expression"] = values["mirrored_reading"]
                row["gauge_verify"] = not gauge
            elif axis != "z":
                row["indicator_verify" if indicated else "finder_verify"] = uncertain(
                    tool
                ) or not bool(tool)
                if not indicated and tool.get("kind") == "edge_finder":
                    # The one EDGE FINDER box on the traveler prints these facts.
                    finder = row["finder"] = finder_procedure(bundle, setup, tool)
                    finder_status.add(finder["status"])
            axes[axis] = row
            if axis == "z":
                blade_corner(row, recipe, face, edge, "the Z zero touch")
            unknown |= (
                any(values[k] == UNKNOWN for k in ("axis_set", "check_reading", "mirrored_reading"))
                or not tool
                or uncertain(tool)
            )
        retouch = []
        recipe = mapping(zero.get("z"))
        paper = recipe.get("paper_mm", UNKNOWN)
        unknown |= (
            recipe.get("retouch_after", UNKNOWN) == UNKNOWN or zero.get("tool_touches") == UNKNOWN
        )
        for index, (op, _, after) in enumerate(states):
            if op.get("op") in records(recipe.get("retouch_after")):
                if unsupported_touch(recipe.get("tool")):
                    retouch.append(
                        {
                            "op": op["op"],
                            "top_z": UNKNOWN,
                            "paper_mm": paper,
                            "axis_set": UNKNOWN,
                            "tool_setting_state": "unsupported_spindle_saw",
                        }
                    )
                    unknown = True
                    continue
                who = f"the retouch after op {op['op']}"
                top, credited, carried = face_check(
                    _retouch_recipe(recipe),
                    "top",
                    tops[index + 1],
                    index + 1,
                    who,
                    after["top_from"],
                )
                touch = top + paper if number(top) and number(paper) else UNKNOWN
                row = {"op": op["op"], "top_z": top, "paper_mm": paper, "axis_set": touch}
                if carried:
                    _carried_setting(bundle, setup, row, "axis_set", carried)
                if credited:
                    row["credited_faces"] = credited
                retouch.append(row)
                unknown |= row["axis_set"] == UNKNOWN
        touches = []
        x_scale = {True: 1, False: 2}.get(dro.get("radius_mode"), UNKNOWN) if lathe else UNKNOWN
        # Authored X touches on a diameter that is gone (errors) or not shown standing.
        x_errors, x_unknowns = [], []
        for record in records(zero.get("tool_touches")):
            if unsupported_touch(record.get("tool")):
                touches.append(
                    {
                        **record,
                        "edge_mm": UNKNOWN,
                        "x_axis_set": UNKNOWN,
                        "z_axis_set": UNKNOWN,
                        "tool_setting_state": "unsupported_spindle_saw",
                    }
                )
                unknown = True
                continue
            edge, paper = record.get("edge_mm", UNKNOWN), record.get("paper_mm", UNKNOWN)
            who = f"the {record.get('tool', UNKNOWN)} touch"
            edge, credited, carried = face_check(
                record, record.get("z_face"), edge, _boundary(ops, record), who
            )
            side = touch_side(bundle, setup, record, record.get("z_face"), edge, lathe)
            stand_off = paper_offset(paper, side)
            tool = resolve(bundle, "spindle", record.get("tool")) or {}
            # A mill's X/Y read the spindle axis whatever the tool: its touches set Z only.
            x_set = (
                "not_applicable"
                if not lathe
                else x_touch_set(
                    x_scale,
                    record.get("x_paper_mm", UNKNOWN),
                    record.get("x_method") == "trial_cut_measure",
                )
                if gauge_ready(bundle, record.get("gauge"))
                else UNKNOWN
            )
            if record.get("method") == "measure_then_set":
                z_set = measured_edge(
                    measured_z(
                        bundle,
                        record.get("z_gauge"),
                        record.get("z_measure"),
                        record.get("z_offset_mm", UNKNOWN),
                        stand_off,
                    )
                )
            else:
                z_set = edge + stand_off if number(edge) and number(stand_off) else UNKNOWN
            row = {**record, "edge_mm": edge, "x_axis_set": x_set, "z_axis_set": z_set}
            if carried:
                _carried_setting(bundle, setup, row, "z_axis_set", carried)
            if credited:
                row["credited_faces"] = credited
            if lathe:
                at = _position(ops, record) or 0
                state, reason = x_face_state(
                    bundle, setup, record, mapping(zero.get("x")), states, at
                )
                row["x_face_status"] = state
                if state != "pass":
                    (x_errors if state == "error" else x_unknowns).append(f"{who} {reason}")
            blade_corner(row, record, record.get("z_face"), edge, who)
            touches.append(row)
            unknown |= (
                x_set == UNKNOWN or row["z_axis_set"] == UNKNOWN or not tool or uncertain(tool)
            )
        unknown |= bool(x_unknowns)
        derived, missing, changes_unknown, _, served = tool_changes(
            bundle, setup, zero, lathe, x_scale, touches
        )
        unknown |= changes_unknown
        # A listed retouch names the op that reads it and the tool that goes in first;
        # one no later cutting op reads serves no tool.
        idle = {"next_op": "not_applicable", "next_tool": "not_applicable", "tool_change": False}
        for row in retouch:
            row.update(served.get(str(row["op"]), idle))
        for row in derived:
            who = f"the {row.get('tool', UNKNOWN)} re-touch"
            done = _boundary(ops, row)
            previous = row.get("edge_mm")
            offset = (
                row["z_axis_set"] - previous
                if number(previous) and number(row.get("z_axis_set"))
                else UNKNOWN
            )
            edge, credited, carried = face_check(row, row.get("z_face"), previous, done, who)
            if carried and "native_edge_mm" in carried:
                offset = paper_offset(
                    row.get("paper_mm", UNKNOWN),
                    touch_side(bundle, setup, row, row.get("z_face"), edge, lathe),
                )
            if row.get("z_face"):
                row["edge_mm"] = edge
                row["z_axis_set"] = edge + offset if number(edge) and number(offset) else UNKNOWN
                if carried:
                    _carried_setting(bundle, setup, row, "z_axis_set", carried)
                unknown |= row["z_axis_set"] == UNKNOWN
            if credited:
                row["credited_faces"] = credited
            blade_corner(row, row, row.get("z_face"), row.get("edge_mm"), who)
        unknown |= bool(face_unknowns)
        numbers = {
            "frame": setup.get("frame", UNKNOWN),
            "binding": frame.get("binding", "nominal"),
            "dro": {
                "mode": dro.get("mode", UNKNOWN),
                "radius_mode": dro.get("radius_mode", UNKNOWN),
            },
            "axes": axes,
            "retouch": retouch,
            "tool_touches": touches,
            "derived_touches": derived,
            "missing_touches": missing,
            **spindle_numbers,
        }
        touched = [axis for axis in ("x", "y") if swept and not isinstance(zero.get(axis), dict)]
        if touched:
            numbers["touch_set"] = {
                "axes": touched,
                "ops": swept,
                "by": "trammel" if railed else "touch",
            }
        grid_debt = dro_grid_debt(bundle, setup) if face_unknowns else None
        if grid_debt:
            numbers["dro_grid_debt"] = grid_debt
            numbers["measurements"] = dro_grid_measurements(bundle, setup)
        if tip_measurements:
            numbers["measurements"] = measurement_checklist(
                [], debts=[*numbers.get("measurements", []), *tip_measurements]
            )
        if lathe:
            numbers["tool_setting"] = tool_setting(bundle, setup, zero, touches, derived)
        if "transfer" in zero:
            numbers["transfer"] = zero["transfer"]
        # A hold that must stay clamped cannot be tapped true: a sweep over its limit needs
        # the plan's recovery, else what to do then is unknown.
        transfer = mapping(zero.get("transfer"))
        recovery = transfer.get("recovery")
        unrecovered = transfer.get("keep_clamped") is True and not (
            isinstance(recovery, str) and recovery.strip() and recovery != UNKNOWN
        )
        unknown |= unrecovered or UNKNOWN in finder_status or bool(slanted)
        if slanted:
            numbers["swivel_unproven_axes"] = slanted
        finder_error = "error" in finder_status
        errors = (
            bad
            or missing
            or corner_errors
            or face_errors
            or x_errors
            or finder_error
            or railed_errors
        )
        status = "error" if errors else "unknown" if unknown else "pass"
        sentence = (
            "DRO direction or mode disagrees with the setup convention; stop and correct it "
            "before the check jog."
            if bad
            else (
                "Touch, Axis Set the compensated value, then jog without retouching "
                "and compare expected versus mirrored readings."
                + (
                    " Each tool change is touched off on the last touched or faced surface "
                    "still standing."
                    if derived
                    else ""
                )
                + (
                    " A tool cuts on a DRO another tool set and no standing plan surface "
                    "is known to touch it off on: plan a tool touch before "
                    + ", ".join(f"op {row['before_op']}" for row in missing)
                    + "."
                    if missing
                    else ""
                )
                + (
                    " Measured setup/tool or trial-cut verification remains unknown."
                    if unknown
                    else ""
                )
            )
        )
        if finder_error:
            sentence += (
                " The edge finder's rpm range lies outside the spindle's: the mill cannot "
                "run it at a speed its maker allows. Use a finder whose band the spindle turns."
            )
        elif UNKNOWN in finder_status:
            sentence += (
                " The edge finder's type, tip Ø, rpm range or the spindle's rpm range is not "
                "stated: its procedure (speed, kick-out, tip-radius offset) cannot be printed."
            )
        if slanted:
            turned = "an unknown angle" if swivel == UNKNOWN else f"{swivel:g}°"
            sentence += (
                f" The vise is swivelled {turned}: the work's edges stand off the table "
                "travel, so a touch on an edge does not set "
                + " or ".join(slanted)
                + '; pick that axis up by indicating a bore\'s centre (from = "indicated").'
            )
        if unrecovered:
            sentence += (
                " The datum transfer keeps the work clamped but plans no recovery for a sweep "
                "over its limit: state transfer.recovery."
            )
        if corner_errors:
            sentence += (
                " A blade's Z touch names a corner its face cannot give ("
                + "; ".join(corner_errors)
                + "): plan its Zs from the corner the face gives."
            )
        if face_errors:
            sentence += (
                " A Z touch sets its DRO off where its face stands ("
                + "; ".join(face_errors)
                + "): every Z the tool then cuts to lands off by the difference. Plan the "
                "face onto this DRO's grid, or set Z from a measured reading of it."
            )
        if face_unknowns:
            sentence += (
                (
                    " A Z touch cannot be certified on an unverified DRO grid ("
                    if grid_debt
                    else " A Z touch meets a face its op left at an unknown Z ("
                )
                + "; ".join(face_unknowns)
                + "): its Axis Set is not known."
            )
        if railed_errors:
            sentence += " " + "; ".join(railed_errors) + "."
        if x_errors:
            sentence += (
                " An X touch measures a diameter that does not stand where it touches ("
                + "; ".join(x_errors)
                + "): touch X on a diameter standing then (D2), or trial-cut one."
            )
        if x_unknowns:
            sentence += (
                " An X touch's diameter is not shown standing where it touches ("
                + "; ".join(x_unknowns)
                + "): name it in x_face, on a diameter the rule can follow."
            )
        if spindle_debt:
            sentence += f" {spindle_debt}."
        result.append(
            Finding(
                "zero_check",
                setup["id"],
                status,
                numbers,
                [
                    "PLAN.md §4.1 zero recipe",
                    "Electronica EL400 Operation Manual §6.2 p20, §7.4 p31, §8.1 p37, §9.2.1 p62",
                    "plan zero and stock_state; inventory finder nominal size",
                    *plan_frame_cite(bundle, setup),
                    *(TOOL_SETTING_CITES if lathe else []),
                    *(records(toolpost(bundle, setup).get("cite")) if lathe else []),
                ],
                sentence,
            )
        )
    return result
