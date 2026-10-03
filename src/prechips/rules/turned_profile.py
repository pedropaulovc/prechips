"""Declared axial diameter intervals in the setup spindle frame, not a B-rep."""

from ..findings import Finding
from .coordinates import frame_point, model_point
from .resolution import UNKNOWN, number, record, resolve, same_length

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
AXIAL_KINDS = {"cylinder", "boss", "groove"}


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


def _citations(value):
    if isinstance(value, str):
        return [value] if value not in (UNKNOWN, "") else []
    if isinstance(value, dict):
        return [text for key in sorted(value) for text in _citations(value[key])]
    if isinstance(value, list):
        return [text for item in value for text in _citations(item)]
    return []


def exposed_profile(bundle, setup):
    """Reuse the declared setup-Z geometry for profile and unsupported-diameter checks."""
    features = bundle.features["features"]
    frames = record(bundle.features.get("frames"))
    units = bundle.features.get("units", UNKNOWN)
    scale = 25.4 if units == "in" else 1.0 if units == "mm" else None
    frame = _frame_mm(frames.get(setup.get("frame")), scale or 1.0)
    claimed = {
        op.get("feature", UNKNOWN) for op in setup["ops"] if op["do"] in PROFILE_OPS
    }
    names = {
        name for name, feature in features.items() if feature.get("kind") in AXIAL_KINDS
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
    intervals, segments, unresolved = [], [], []
    exposed_names = set()
    for name in sorted(names):
        feature = record(features.get(name))
        span = _axial_span(feature, frame, frames, scale)
        if span is None:
            unresolved.append(name)
            exposed_names.add(name)
            continue
        low, high = span
        if isinstance(exposure, list):
            low, high = max(low, exposure[0]), min(high, exposure[1])
            if low >= high:
                continue
        exposed_names.add(name)
        diameter = nominal_diameter(bundle, feature)
        if feature.get("kind") not in AXIAL_KINDS or not number(diameter):
            unresolved.append(name)
            continue
        intervals.append(
            {
                "feature": name,
                "kind": feature["kind"],
                "z_mm": [low, high],
                "diameter_mm": diameter,
            }
        )
    boundaries = sorted({z for interval in intervals for z in interval["z_mm"]})
    previous = None
    for low, high in zip(boundaries, boundaries[1:], strict=False):
        active = [
            item for item in intervals if item["z_mm"][0] <= low and high <= item["z_mm"][1]
        ]
        cylinders = [item for item in active if item["kind"] != "groove"]
        grooves = [item for item in active if item["kind"] == "groove"]
        candidates = grooves or cylinders
        ambiguous = not candidates or len({item["diameter_mm"] for item in candidates}) != 1
        if grooves and cylinders:
            ambiguous |= (
                len({item["diameter_mm"] for item in cylinders}) != 1
                or grooves[0]["diameter_mm"] > cylinders[0]["diameter_mm"]
            )
        if ambiguous:
            segments.append(
                {
                    "z_mm": [low, high],
                    "diameter_mm": UNKNOWN,
                    "features": sorted(item["feature"] for item in active),
                }
            )
            unresolved.append(f"interval {low:g}..{high:g}")
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
    complete = (
        isinstance(exposure, list)
        and bool(segments)
        and not unresolved
        and same_length(segments[0]["z_mm"][0], exposure[0])
        and same_length(segments[-1]["z_mm"][1], exposure[1])
    )
    return {
        "names": exposed_names,
        "exposed_z_mm": exposure,
        "intervals": intervals,
        "segments": segments,
        "unresolved": unresolved,
        "complete": complete,
        "cite": sorted(
            {
                text
                for name in exposed_names
                for text in _citations(record(features.get(name)).get("cite"))
            }
        ),
    }


def evaluate(bundle):
    findings = []
    features = bundle.features["features"]
    for setup in bundle.plan["setups"]:
        machine = resolve(bundle, "machines", setup.get("machine"))
        kind = record(machine).get("kind", UNKNOWN)
        profile_ops = [op for op in setup["ops"] if op["do"] in PROFILE_OPS]
        unknown_action = any(op["do"] == UNKNOWN for op in setup["ops"])
        intervals, unresolved, segments, transitions = [], [], [], []
        names = set()
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
            names = geometry["names"]
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
                    and base_diameter > previous["base_diameter_mm"]
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
                elif previous is not None and current["diameter_mm"] > previous["diameter_mm"]:
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
        citations = sorted(
            {text for name in names for text in _citations(record(features.get(name)).get("cite"))}
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
                },
                [
                    "PLAN.md §4.1 turned profile (line 540); §8 M2 spindle Z convention",
                    "features declared nominal diameters/z_mm/frame; "
                    "plan setup frame and current/preceding grooving ops; 25.4 mm/in",
                    *citations,
                ],
                f"{setup['id']}: {message}.",
            )
        )
    return findings
