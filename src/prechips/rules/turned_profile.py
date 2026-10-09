"""Axial diameter intervals in the setup spindle frame: declared stations and diameters,
gaps filled by the kernel's measured faces of revolution about setup Z."""

import math

from ..findings import Finding
from ..joint_features import joint_of, present, setup_span_mm
from .coordinates import frame_point, model_point
from .resolution import (
    UNKNOWN,
    _citations,
    number,
    plan_frame_cite,
    record,
    resolve,
    same_length,
    setup_frame,
)

PROFILE_OPS = {
    "turn",
    "rough_turn",
    "finish_turn",
    "profile_turn",
    "profile",
    "form",
    "form_dome",
    "form_relief",
    "groove",
    "rough_groove",
    "finish_groove",
}
GROOVE_OPS = {"groove", "rough_groove", "finish_groove", "form_relief"}
CYLINDER_KINDS = {"cylinder", "boss", "shaft"}
AXIAL_KINDS = CYLINDER_KINDS | {"groove", "dome"}
RADIUS_TOL_MM = 1e-4  # kernel radii closer than this are one cylinder / one dome end


def nominal_diameter(bundle, feature):
    """An explicit nominal/scalar dimension only; a tolerance band is not geometry."""
    diameter = UNKNOWN
    for field in ("dia_nominal", "nominal_dia", "dia"):
        if field in feature:
            diameter = feature[field]
            break
    units = bundle.features.get("units", UNKNOWN)
    if not number(diameter) or diameter <= 0 or units not in ("mm", "in"):
        return UNKNOWN
    return diameter * 25.4 if units == "in" else diameter


def _frame_mm(frame, scale):
    result = dict(record(frame))
    origin = result.get("origin")
    if isinstance(origin, list):
        result["origin"] = [value * scale if number(value) else UNKNOWN for value in origin]
    return result


def _scale(bundle):
    units = bundle.features.get("units", UNKNOWN)
    return 25.4 if units == "in" else 1.0 if units == "mm" else None


def _scalar(feature, field):
    """A declared nominal/scalar value; a tolerance band is not geometry."""
    for key in (f"{field}_nominal", f"nominal_{field}", field):
        if key in feature:
            value = feature[key]
            return value if number(value) and value > 0 else UNKNOWN
    return UNKNOWN


def dome_base_diameter(bundle, feature):
    """Declared widest (base) diameter of a spherical dome in mm, else unknown.

    ``2 * base_radius``; else the cap rim ``2 * sqrt(h (2R - h))`` from the declared sphere
    radius R and height h (a cap taller than a hemisphere is widest at its equator, 2R).
    """
    scale = _scale(bundle)
    if scale is None:
        return UNKNOWN
    base = feature.get("base_radius")
    if number(base) and base > 0:
        return 2 * base * scale
    radius, height = feature.get("sphere_radius"), _scalar(feature, "height")
    if not (number(radius) and number(height) and 0 < height <= 2 * radius):
        return UNKNOWN
    cap = min(height, radius)
    return 2 * math.sqrt(cap * (2 * radius - cap)) * scale


def _kernel_revolved(bundle, setup, frame):
    """(setup's kernel revolved facts, their per-feature reasons, why none) from an
    already-present kernel run; this never starts the kernel."""
    kernel = record(getattr(bundle, "kernel", None))
    if kernel.get("status") != "ok":
        return {}, {}, "no kernel geometry is available"
    if frame.get("binding") == UNKNOWN:
        return {}, {}, "the setup frame binding is unknown"
    facts = record(record(kernel.get("setups")).get(setup["id"]))
    if not isinstance(facts.get("revolved"), dict):
        why = (
            "the kernel measured no faces of revolution for this setup "
            "(no turning-model operation, or an unusable setup frame)"
        )
        return {}, {}, why
    return facts["revolved"], record(facts.get("revolved_reasons")), None


def _kernel_off_axis(bundle, setup):
    """{feature: axis} the kernel measured revolved only about a direction other than setup
    Z (``revolved_off_axis``), from an already-present run with a bound setup frame."""
    kernel = record(getattr(bundle, "kernel", None))
    if kernel.get("status") != "ok" or setup_frame(bundle, setup).get("binding") == UNKNOWN:
        return {}
    facts = record(record(kernel.get("setups")).get(setup["id"]))
    return {
        name: fact["axis"]
        for name, fact in record(facts.get("revolved_off_axis")).items()
        if isinstance(fact, dict)
        and isinstance(fact.get("axis"), list)
        and len(fact["axis"]) == 3
        and all(number(value) for value in fact["axis"])
    }


def _pair(value):
    return (
        isinstance(value, list)
        and len(value) == 2
        and all(number(item) for item in value)
        and value[0] <= value[1]
    )


def _kernel_fact(context, name):
    """(the feature's well-formed kernel revolved fact or None, why not)."""
    revolved, reasons, missing = context[3:]
    if missing is not None:
        return None, missing
    fact = revolved.get(name)
    if not isinstance(fact, dict):
        return None, reasons.get(name, "the kernel reports no faces of revolution for it")
    ends = fact.get("end_radii_mm")
    if not (
        _pair(fact.get("z_mm"))
        and _pair(fact.get("radii_mm"))
        and fact["radii_mm"][0] >= 0
        and isinstance(ends, list)
        and len(ends) == 2
        and all(number(value) and value >= 0 for value in ends)
    ):
        return None, "its kernel revolved facts are malformed"
    return fact, None


def _context(bundle, setup):
    """Per-setup inputs shared by every feature's geometry."""
    scale = _scale(bundle)
    frame = _frame_mm(setup_frame(bundle, setup), scale or 1.0)
    # Source frames stay manifest-only; the setup frame may be exported or plan-owned.
    frames = record(bundle.features.get("frames"))
    return frame, frames, scale, *_kernel_revolved(bundle, setup, frame)


def _geometry(bundle, name, context):
    """One feature's setup-frame span and turned diameters, with the debt of each unknown.

    Declared values are authoritative (declared stations that do not resolve are never
    replaced); kernel faces of revolution fill what is not declared; the rest stays unknown.
    """
    frame, frames, scale = context[:3]
    feature = record(bundle.feature_definitions.get(name))
    kind = feature.get("kind", UNKNOWN)
    transient = joint_of(feature) is not None
    fact, why = (
        (None, "transient joint features have no finished-face facts")
        if transient
        else _kernel_fact(context, name)
    )
    result = {"sources": {}, "reasons": []}

    def take(field, value, source):
        result[field] = value
        result["sources"][field] = source

    def debt(declared):
        result["reasons"].append(f"{declared}; kernel: {why}")

    result["z_mm"] = UNKNOWN
    if transient:
        span = setup_span_mm(bundle, name, frame)
        if span is None:
            result["reasons"].append(
                "declared joint cylinder does not resolve on the setup spindle"
            )
        else:
            take("z_mm", list(span), "declared")
    elif "z_mm" in feature:
        span = _axial_span(feature, frame, frames, scale)
        if span is None:
            result["reasons"].append("declared z_mm does not resolve along setup Z")
        else:
            take("z_mm", list(span), "declared")
    elif fact is not None:
        take("z_mm", list(fact["z_mm"]), "kernel")
    else:
        debt("no declared z_mm")
    radii = fact["radii_mm"] if fact is not None else None
    if kind in CYLINDER_KINDS or kind == "groove":
        result["diameter_mm"] = UNKNOWN
        diameter = nominal_diameter(bundle, feature)
        if number(diameter):
            take("diameter_mm", diameter, "declared")
        elif fact is None:
            debt("no nominal diameter")
        elif kind == "groove":
            take("diameter_mm", 2 * radii[0], "kernel")
        elif radii[1] - radii[0] <= RADIUS_TOL_MM:
            take("diameter_mm", 2 * radii[1], "kernel")
        else:
            result["reasons"].append(
                f"no nominal diameter; kernel faces span radii {radii[0]:g}..{radii[1]:g} mm, "
                "not one cylinder"
            )
    elif kind == "dome":
        result.update(base_diameter_mm=UNKNOWN, height_mm=UNKNOWN, apex=UNKNOWN)
        base = dome_base_diameter(bundle, feature)
        if number(base):
            take("base_diameter_mm", base, "declared")
        elif fact is not None:
            take("base_diameter_mm", 2 * radii[1], "kernel")
        else:
            debt("no declared base_radius or sphere_radius/height")
        height = _scalar(feature, "height")
        if number(height) and scale is not None:
            take("height_mm", height * scale, "declared")
        elif fact is not None:
            take("height_mm", fact["z_mm"][1] - fact["z_mm"][0], "kernel")
        else:
            debt("no declared nominal height")
        # Which end is the apex comes only from measured geometry: the narrower end.
        if fact is None:
            debt("dome apex direction")
        else:
            low_end, high_end = fact["end_radii_mm"]
            if abs(high_end - low_end) <= RADIUS_TOL_MM:
                result["reasons"].append("kernel dome ends have equal radii; apex is unresolved")
            else:
                take("apex", "high" if high_end < low_end else "low", "kernel")
    elif kind == "face":
        result["height_mm"] = UNKNOWN
        if isinstance(result["z_mm"], list):
            take("height_mm", result["z_mm"][1] - result["z_mm"][0], result["sources"]["z_mm"])
    return result


def _kernel_cite(setup, name):
    return (
        f"kernel: setups.{setup['id']}.revolved.{name} "
        "(finished faces of revolution about setup Z; FreeCAD B-rep)"
    )


def spindle_span(bundle, setup, name):
    """(setup-frame axial span in mm, citation) of a feature the kernel measured with every
    face an external surface of revolution about setup Z through x = y = 0, else
    (None, why not). Reads only an already-present kernel result."""
    fact, why = _kernel_fact(_context(bundle, setup), name)
    if fact is None:
        return None, why
    return list(fact["z_mm"]), _kernel_cite(setup, name)


def feature_span(bundle, setup, name):
    """A feature's setup-frame axial span and turned diameters, declared first, kernel next.

    ``z_mm`` [low, high] in setup-frame mm; ``diameter_mm`` for cylinder/boss/shaft/groove;
    ``base_diameter_mm`` (widest) and ``height_mm`` for a dome; ``height_mm`` (axial extent)
    for a face; other values are "unknown". ``source`` is "kernel" when any value is
    measured by the kernel, "declared" when all resolved values are declared, "unknown"
    when none resolves; ``unresolved`` names the debt of each unknown. Reads only an
    already-present kernel result.
    """
    feature = record(bundle.feature_definitions.get(name))
    geometry = _geometry(bundle, name, _context(bundle, setup))
    fields = ("z_mm", "diameter_mm", "base_diameter_mm", "height_mm")
    sources = {key: value for key, value in geometry["sources"].items() if key in fields}
    kernel = "kernel" in geometry["sources"].values()
    return {
        **{field: geometry.get(field, UNKNOWN) for field in fields},
        "source": "kernel" if kernel else "declared" if sources else UNKNOWN,
        "sources": sources,
        "unresolved": geometry["reasons"],
        "cite": [
            *_citations(feature.get("cite")),
            *([_kernel_cite(setup, name)] if kernel else []),
        ],
    }


def _axial_span(feature, setup_frame, frames, scale):
    stations = feature.get("z_mm")
    source = _frame_mm(frames.get(feature.get("frame", "model")), scale or 1.0)
    source_z, setup_z = source.get("z"), setup_frame.get("z")
    if not (
        scale is not None
        and isinstance(stations, list)
        and len(stations) == 2
        and all(number(value) for value in stations)
        and isinstance(source_z, list)
        and isinstance(setup_z, list)
        and len(source_z) == len(setup_z) == 3
        and all(number(value) for value in source_z + setup_z)
        and (source_z == setup_z or source_z == [-value for value in setup_z])
        and source.get("binding") != UNKNOWN
        and setup_frame.get("binding") != UNKNOWN
    ):
        return None
    axis = feature.get("axis", [0.0, 0.0, 1.0])
    if axis not in ([0.0, 0.0, 1.0], [0.0, 0.0, -1.0]):
        return None
    transformed = [
        frame_point(model_point([0.0, 0.0, value * scale], source), setup_frame)[2]
        for value in stations
    ]
    if not all(number(value) for value in transformed) or transformed[0] == transformed[1]:
        return None
    low, high = sorted(transformed)
    return low, high


def _larger(a, b):
    """A physical diameter increase: beyond the 1 nm length identity, never float residue."""
    return a > b and not same_length(a, b)


def _one_diameter(items):
    values = [item["diameter_mm"] for item in items]
    return all(same_length(value, values[0]) for value in values)


def _grooving(setup, name, bundle):
    route = []
    for earlier in bundle.plan["setups"]:
        route.append(earlier)
        if earlier["id"] == setup["id"]:
            break
    evidence = [
        {"setup": earlier["id"], "op": op["op"], "action": op["do"]}
        for earlier in route
        for op in sorted(earlier["ops"], key=lambda value: value["op"])
        if op.get("feature") == name and op["do"] in GROOVE_OPS
    ]
    if evidence:
        return "pass", evidence
    unknown = any(
        op.get("feature") == name and op["do"] == UNKNOWN
        for earlier in route
        for op in earlier["ops"]
    )
    return ("unknown" if unknown else "error"), evidence


_STOCK_CITE = (
    "kernel: setups.{setup}.stock_profile (least outer radius of the in-process stock "
    "while present during the setup, about setup Z; FreeCAD B-rep)"
)


def _kernel_stock(bundle, setup):
    """(well-formed kernel ``stock_profile`` rows [z_lo, z_hi, r_lo, r_hi], why none)
    from an already-present kernel run; this never starts the kernel."""
    kernel = record(getattr(bundle, "kernel", None))
    if kernel.get("status") != "ok":
        return None, "no kernel geometry is available"
    if setup_frame(bundle, setup).get("binding") == UNKNOWN:
        return None, "the setup frame binding is unknown"
    facts = record(record(kernel.get("setups")).get(setup["id"]))
    rows = facts.get("stock_profile")
    if not isinstance(rows, list):
        return None, str(
            facts.get("stock_profile_reason")
            or "the kernel reports no stock profile for this setup"
        )
    if not all(
        isinstance(row, list)
        and len(row) == 4
        and all(number(value) for value in row)
        and row[0] < row[1]
        and 0 <= row[2] <= row[3]
        for row in rows
    ):
        return None, "the kernel stock profile is malformed"
    return rows, None


def _stock_fill(bundle, setup, uncovered):
    """(stock segments, spans still uncovered, why) for exposed spans beyond every finished
    feature: the kernel's stock profile must cover a span end to end, and each piece takes
    the least outer radius of its band over every in-process state that has material there
    (entering stock, then after each removing op). Without it the span stays uncovered:
    the stock state's od_mm cannot show that no op reduced it."""
    if not uncovered:
        return [], [], None
    rows, why = _kernel_stock(bundle, setup)
    if rows is None:
        return [], uncovered, why
    filled, remaining = [], []
    for low, high in uncovered:
        pieces, reach = [], low
        for z0, z1, r_lo, _ in sorted(rows):
            if z1 <= reach or same_length(z1, reach) or z0 >= high:
                continue
            if z0 > reach and not same_length(z0, reach):
                break
            top = min(z1, high)
            pieces.append(
                {
                    "z_mm": [reach, top],
                    "diameter_mm": 2 * r_lo,
                    "features": [],
                    "source": "kernel_stock",
                }
            )
            reach = top
        if reach >= high or same_length(reach, high):
            filled.extend(pieces)
        else:
            remaining.append([low, high])
    reason = None if not remaining else "the kernel stock profile does not cover the whole span"
    return filled, remaining, reason


def exposed_profile(bundle, setup):
    """Setup-Z profile (declared, kernel-filled) for profile and unsupported-diameter checks."""
    features = bundle.feature_definitions
    context = _context(bundle, setup)
    claimed = {op.get("feature", UNKNOWN) for op in setup["ops"] if op["do"] in PROFILE_OPS}
    # A transient joint feature belongs only to its own in-process branch (joint_features).
    names = {
        name
        for name, feature in features.items()
        if feature.get("kind") in AXIAL_KINDS and present(bundle, setup, name)
    } | claimed
    state, hold = record(setup.get("stock_state")), record(setup.get("hold"))
    north, south, length = (
        state.get("north_end_z"),
        state.get("south_end_z"),
        hold.get("stickout_mm"),
    )
    exposure = UNKNOWN
    if all(number(value) for value in (north, south, length)) and length > 0:
        exposed_end = max(north, south)
        exposure = [exposed_end - length, exposed_end]
    intervals, segments, unresolved, reasons, off_axis = [], [], [], {}, {}
    exposed_names, kernel_names = set(), set()
    measured_off_axis = _kernel_off_axis(bundle, setup)

    def unresolve(name, why):
        unresolved.append(name)
        reasons[name] = why

    for name in sorted(names):
        feature = record(features.get(name))
        kind = feature.get("kind", UNKNOWN)
        geometry = _geometry(bundle, name, context)
        span = geometry["z_mm"]
        if (
            not isinstance(span, list)
            and name in measured_off_axis
            and name not in claimed
            and not joint_of(feature)
        ):
            # Revolved about another direction and not turned here: not on this spindle's
            # profile. Transient cylinders retain their authored spindle debt instead.
            off_axis[name] = measured_off_axis[name]
            continue
        if not isinstance(span, list) or span[0] >= span[1]:
            exposed_names.add(name)
            unresolve(name, "; ".join(geometry["reasons"]) or "its axial span has no length")
            continue
        low, high = span
        if isinstance(exposure, list):
            low, high = max(low, exposure[0]), min(high, exposure[1])
            if low >= high:
                continue
        exposed_names.add(name)
        if kind not in AXIAL_KINDS:
            unresolve(name, f"kind {kind!r} has no axial diameter model")
            continue
        diameter = geometry["base_diameter_mm" if kind == "dome" else "diameter_mm"]
        if not number(diameter):
            unresolve(name, "; ".join(geometry["reasons"]))
            continue
        if kind == "dome" and geometry["apex"] != "high":
            # A dome narrowing away from the chuck is bounded by its base diameter; one
            # widening away from it is an outward rise this model does not represent.
            unresolve(
                name,
                "; ".join(geometry["reasons"])
                if geometry["apex"] == UNKNOWN
                else "the dome widens away from the chuck (apex toward the chuck)",
            )
            continue
        source = "kernel" if "kernel" in geometry["sources"].values() else "declared"
        if source == "kernel":
            kernel_names.add(name)
        intervals.append(
            {
                "feature": name,
                "kind": kind,
                "z_mm": [low, high],
                "diameter_mm": diameter,
                "source": source,
            }
        )
    boundaries = sorted({z for interval in intervals for z in interval["z_mm"]})
    previous = None
    for low, high in zip(boundaries, boundaries[1:], strict=False):
        active = [item for item in intervals if item["z_mm"][0] <= low and high <= item["z_mm"][1]]
        cylinders = [item for item in active if item["kind"] != "groove"]
        grooves = [item for item in active if item["kind"] == "groove"]
        candidates = grooves or cylinders
        ambiguous = not candidates or not _one_diameter(candidates)
        if grooves and cylinders:
            ambiguous |= not _one_diameter(cylinders) or _larger(
                grooves[0]["diameter_mm"], cylinders[0]["diameter_mm"]
            )
        if ambiguous:
            segments.append(
                {
                    "z_mm": [low, high],
                    "diameter_mm": UNKNOWN,
                    "features": sorted(item["feature"] for item in active),
                }
            )
            unresolve(
                f"interval {low:g}..{high:g}",
                "no exposed feature covers it"
                if not active
                else "overlapping features disagree on its diameter",
            )
            previous = None
            continue
        base_diameter = (
            cylinders[0]["diameter_mm"]
            if cylinders
            else previous["base_diameter_mm"]
            if previous is not None
            else UNKNOWN
        )
        previous = {
            "z_mm": [low, high],
            "diameter_mm": candidates[0]["diameter_mm"],
            "base_diameter_mm": base_diameter,
            "features": sorted(item["feature"] for item in candidates),
        }
        segments.append(previous)
    # Exposed stock beyond the outermost finished intervals has no finished diameter.
    uncovered = [list(exposure)] if isinstance(exposure, list) and not segments else []
    if isinstance(exposure, list) and segments:
        if segments[0]["z_mm"][0] > exposure[0] and not same_length(
            segments[0]["z_mm"][0], exposure[0]
        ):
            uncovered.append([exposure[0], segments[0]["z_mm"][0]])
        if segments[-1]["z_mm"][1] < exposure[1] and not same_length(
            segments[-1]["z_mm"][1], exposure[1]
        ):
            uncovered.append([segments[-1]["z_mm"][1], exposure[1]])
    stock_segments, uncovered, stock_reason = _stock_fill(bundle, setup, uncovered)
    # A span the kernel's stock profile wholly fills (stock preparation ahead of every
    # finished feature) is as known as one finished features cover.
    complete = (
        isinstance(exposure, list)
        and bool(segments or stock_segments)
        and not unresolved
        and not uncovered
    )
    return {
        "names": exposed_names,
        "exposed_z_mm": exposure,
        "intervals": intervals,
        "segments": segments,
        "stock_segments": stock_segments,
        "unresolved": unresolved,
        "unresolved_reasons": {name: reasons[name] for name in sorted(set(unresolved))},
        "uncovered_z_mm": uncovered,
        "stock_reason": stock_reason,
        "off_axis": off_axis,
        "complete": complete,
        "cite": sorted(
            {
                text
                for name in exposed_names
                for text in _citations(record(features.get(name)).get("cite"))
            }
            | {_kernel_cite(setup, name) for name in kernel_names}
            | {
                f"kernel: setups.{setup['id']}.revolved_off_axis.{name} "
                "(revolved about another axis; FreeCAD B-rep)"
                for name in off_axis
            }
            | ({_STOCK_CITE.format(setup=setup["id"])} if stock_segments else set())
        ),
    }


def evaluate(bundle):
    findings = []
    for setup in bundle.plan["setups"]:
        machine = resolve(bundle, "machines", setup.get("machine"))
        kind = record(machine).get("kind", UNKNOWN)
        profile_ops = [op for op in setup["ops"] if op["do"] in PROFILE_OPS]
        unknown_action = any(op["do"] == UNKNOWN for op in setup["ops"])
        intervals, unresolved, segments, transitions = [], [], [], []
        reasons, citations, off_axis = {}, [], {}
        exposure = UNKNOWN
        status, message = "not_applicable", "no declared axial turning operation"
        if kind == UNKNOWN:
            status, message = "unknown", "machine kind is unresolved"
        elif kind != "lathe":
            message = "not a lathe setup"
        elif not profile_ops:
            if unknown_action:
                status, message = "unknown", "turning action is unresolved"
        else:
            geometry = exposed_profile(bundle, setup)
            citations = geometry["cite"]
            reasons, off_axis = geometry["unresolved_reasons"], geometry["off_axis"]
            exposure = geometry["exposed_z_mm"]
            intervals, segments, unresolved = (
                geometry["intervals"],
                geometry["segments"],
                geometry["unresolved"],
            )
            previous = None
            for current in segments:
                if not number(current["diameter_mm"]):
                    previous = None
                    continue
                low = current["z_mm"][0]
                base_diameter = current["base_diameter_mm"]
                base_increase = (
                    previous is not None
                    and number(previous["base_diameter_mm"])
                    and number(base_diameter)
                    and _larger(base_diameter, previous["base_diameter_mm"])
                )
                if base_increase:
                    transitions.append(
                        {
                            "z_mm": low,
                            "from_diameter_mm": previous["base_diameter_mm"],
                            "to_diameter_mm": base_diameter,
                            "reason": "base_envelope",
                            "status": "error" if isinstance(exposure, list) else "unknown",
                            "grooving": [],
                        }
                    )
                elif previous is not None and _larger(
                    current["diameter_mm"], previous["diameter_mm"]
                ):
                    exceptions = []
                    for name in previous["features"]:
                        exception_status, ops = _grooving(setup, name, bundle)
                        exceptions.append({"feature": name, "status": exception_status, "ops": ops})
                    transition_status = (
                        "pass"
                        if any(item["status"] == "pass" for item in exceptions)
                        else "unknown"
                        if any(item["status"] == "unknown" for item in exceptions)
                        else "error"
                    )
                    if (
                        not number(previous["base_diameter_mm"])
                        or not isinstance(exposure, list)
                        and transition_status == "error"
                    ):
                        transition_status = "unknown"
                    transitions.append(
                        {
                            "z_mm": low,
                            "from_diameter_mm": previous["diameter_mm"],
                            "to_diameter_mm": current["diameter_mm"],
                            "reason": "groove_recovery",
                            "status": transition_status,
                            "grooving": exceptions,
                        }
                    )
                previous = current
            if any(item["status"] == "error" for item in transitions):
                status, message = (
                    "error",
                    "an exposed shoulder increases away from the chuck, "
                    "or a groove lacks a matching grooving operation",
                )
            elif (
                unresolved
                or unknown_action
                or not segments
                or any(item["status"] == "unknown" for item in transitions)
            ):
                status, message = (
                    "unknown",
                    "axial profile geometry or the selected grooving exception is unresolved",
                )
            else:
                status, message = (
                    "pass",
                    "declared profile is monotone away from the chuck, "
                    "with declared grooving exceptions where needed",
                )
        findings.append(
            Finding(
                "turned_profile",
                setup["id"],
                status,
                {
                    "frame": setup.get("frame", UNKNOWN),
                    "direction": "+setup Z toward exposed end",
                    "exposed_z_mm": exposure,
                    "intervals": intervals,
                    "segments": segments,
                    "transitions": transitions,
                    "unresolved": sorted(set(unresolved)),
                    "unresolved_reasons": reasons,
                    "off_axis": off_axis,
                },
                [
                    "PLAN.md §4.1 turned profile; §8 M2 spindle Z convention",
                    "features declared nominal diameters/z_mm/frame, else the kernel's "
                    "finished faces of revolution about setup Z; "
                    "plan setup frame and current/preceding grooving ops; 25.4 mm/in",
                    *citations,
                    *plan_frame_cite(bundle, setup),
                ],
                f"{setup['id']}: {message}.",
            )
        )
    return findings
