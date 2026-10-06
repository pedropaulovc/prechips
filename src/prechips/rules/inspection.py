"""Every manifest tolerance needs its own real, capable inspection method.

An op's ``process_holds`` are shop limits tighter than the drawing, held for a stated
process reason (a downstream fit, a clocking stop). Each band must lie inside its drawing
requirement's band, limits included; one reaching outside would pass parts the drawing
rejects. Only a scalar zone/maximum (position, coaxiality, angularity, Ra) ``v`` reads as
the band [0, v]; any other scalar is a nominal with no band to hold inside. Each hold is
read with its own gauge, graded like a drawing check against the hold band.
"""

from ..findings import Finding
from ..joint_features import source_cite
from ..measurements import length_fact
from ..model import tolerance_requirements
from .resolution import UNKNOWN, length_mm, number, operations, record, resolve, uncertain

PROCESS_HOLD_CITE = ["PLAN.md §4.1 inspection", "plan process_holds", "features requirement band"]
ZONES = frozenset({"position_dia", "coaxiality_dia", "angularity_dia", "finish_ra"})


def _drawing_band(requirement, value):
    if number(value):
        return [0, value] if requirement in ZONES else None
    if isinstance(value, list) and len(value) == 2 and all(number(v) for v in value):
        return value
    return None


def process_holds(bundle, setup, op):
    """One finding per op: each process hold band against its drawing band."""
    subject = f"{setup['id']}:{op['op']}"
    rows = []
    for hold in op["process_holds"]:
        feature = record(bundle.feature_definitions.get(hold["feature"]))
        limits = feature.get(hold["requirement"], UNKNOWN)
        drawing = _drawing_band(hold["requirement"], limits)
        low, high = hold["band"]
        inside = None if drawing is None else drawing[0] <= low and high <= drawing[1]
        row = {
            "feature": hold["feature"],
            "requirement": hold["requirement"],
            "band": hold["band"],
            "drawing_band": limits,
            "gauge": hold["gauge"],
            "reason": hold["reason"],
            "inside_drawing_band": UNKNOWN if inside is None else inside,
        }
        # The shop reads the hold with its gauge: it must measure that requirement at this band.
        capability, reading = _capability(
            bundle, feature, hold["requirement"], hold["band"], hold["gauge"], op, row
        )
        row.update(gauge_status=capability, gauge_message=reading)
        rows.append(row)
    outside = [row for row in rows if row["inside_drawing_band"] is False]
    incapable = [row for row in rows if row["gauge_status"] == "error"]
    unresolved = [
        row
        for row in rows
        if row["inside_drawing_band"] == UNKNOWN or row["gauge_status"] not in {"pass", "error"}
    ]

    def label(chosen):
        return ", ".join(
            f"{row['feature']} {row['requirement']}: {row['gauge_message']}" for row in chosen
        )

    status, message = (
        ("error", f"process hold band outside the drawing band ({label(outside)})")
        if outside
        else ("error", f"process hold gauge cannot hold the band ({label(incapable)})")
        if incapable
        else ("unknown", f"process hold band or gauge unresolved ({label(unresolved)})")
        if unresolved
        else ("pass", "every process hold lies inside its drawing band, read by a capable gauge")
    )
    return Finding(
        "inspection",
        subject,
        status,
        {"process_holds": rows},
        PROCESS_HOLD_CITE,
        f"{subject}: {message}.",
    )


def _nominal_band_error(feature, requirement):
    limits = feature.get(requirement)
    if not (isinstance(limits, list) and len(limits) == 2 and all(number(v) for v in limits)):
        return {}
    for field in (f"{requirement}_nominal", f"nominal_{requirement}"):
        nominal = feature.get(field)
        if number(nominal) and not limits[0] <= nominal <= limits[1]:
            return {"nominal_field": field, "nominal": nominal, "limits": limits}
    return {}


def _capability(bundle, feature, requirement, value, gauge_ref, op, nums):
    """``(status, message)``: can the named gauge read ``value`` for ``requirement``."""
    status, message = "unknown", "explicit inspection method is unknown"
    gauge = resolve(bundle, "gauges", gauge_ref)
    if gauge_ref != "unknown" and gauge is None:
        # The inventory reference finding owns the single missing-item error.
        message = "named gauge is not listed; capability unresolved"
    elif gauge:
        kind = gauge.get("kind", "unknown")
        # Only the resolution fact's own trust lets it establish or refute capability.
        fact = length_fact(gauge, "resolution", require_measured=False)
        resolution = fact["value"] if fact["verified"] else "unknown"
        span = gauge.get("range_mm")
        if not isinstance(span, list):
            maximum = length_mm(gauge, "range")
            span = [0, maximum] if number(maximum) else "unknown"
        nums.update(gauge_kind=kind, range_mm=span, resolution_mm=resolution)
        method = record(op.get("inspection_methods")).get(requirement)
        geometric = requirement in {"position_dia", "coaxiality_dia", "angularity_dia"}
        method_known = (
            isinstance(method, str) and bool(method.strip()) and method.strip() != "unknown"
        )
        angularity_datums = feature.get("angularity_datums", "unknown")
        angularity_geometry_known = (
            isinstance(angularity_datums, list)
            and bool(angularity_datums)
            and all(
                isinstance(datum, str) and bool(datum.strip()) and datum != "unknown"
                for datum in angularity_datums
            )
        )
        if geometric:
            nums["inspection_method"] = method or "unknown"
        if requirement == "angularity_dia":
            nums["angularity_datums"] = angularity_datums
        complex_shape = requirement in {
            "radius",
            "bottom_radius",
            "arc_len",
            "bottom_arc_len",
            "land_angle_deg",
            "height_above_pivot",
        }
        capable = (
            kind in {"roughness_gauge", "roughness_comparator", "profilometer"}
            if requirement == "finish_ra"
            else kind in {"cmm", "dial_indicator", "dial_test_indicator", "height_gauge"}
            if geometric
            else kind in {"cmm", "profile_gauge", "radius_gauge", "angle_gauge"}
            if complex_shape
            else kind
            in {
                "caliper",
                "micrometer",
                "micrometer_set",
                "pin_gauge",
                "pin_gauge_set",
                "bore_gauge",
                "height_gauge",
                "depth_gauge",
                "cmm",
            }
        )
        if (
            feature["kind"] in {"hole", "thread", "threaded_hole"}
            and requirement == "dia"
            and kind in {"micrometer", "micrometer_set"}
        ):
            capable = False
        if kind == "unknown":
            message = "gauge identity or capability is explicitly unknown"
        elif not capable:
            status, message = "error", "named gauge cannot measure this requirement"
        elif value == "unknown" or bundle.features.get("units") != "mm":
            message = "requirement limits or units are unresolved"
        elif geometric and (
            not method_known or (requirement == "angularity_dia" and not angularity_geometry_known)
        ):
            message = "geometric gauge capability or datum inspection method unresolved"
        elif requirement == "finish_ra":
            capability = gauge.get("ra_range", gauge.get("range_ra", "unknown"))
            nums["ra_range"] = capability
            if (
                isinstance(capability, list)
                and all(number(v) for v in capability)
                and number(value)
            ):
                status = "pass" if capability[0] <= value <= capability[1] else "error"
                message = (
                    "roughness gauge spans requirement"
                    if status == "pass"
                    else "roughness requirement outside gauge range"
                )
            else:
                message = "roughness gauge capability unresolved"
        elif isinstance(value, list) and len(value) == 2 and all(number(v) for v in value):
            if isinstance(span, list) and all(number(v) for v in span) and number(resolution):
                nums["band_mm"] = value[1] - value[0]
                if span[0] > value[0] or span[1] < value[1]:
                    status, message = (
                        "error",
                        "gauge does not span the requirement band",
                    )
                elif resolution > value[1] - value[0]:
                    status, message = (
                        "error",
                        "gauge resolution exceeds the requirement band",
                    )
                else:
                    status, message = (
                        "pass",
                        "gauge spans the band at sufficient resolution",
                    )
            else:
                message = "gauge range or resolution unresolved"
        elif geometric and number(value):
            if number(resolution) and resolution <= value and method_known:
                status, message = (
                    "pass",
                    "gauge resolution and declared geometric inspection method cover requirement",
                )
            else:
                message = "geometric gauge capability or datum inspection method unresolved"
        else:
            message = "inspection capability for requirement unresolved"
        if uncertain(gauge) and status != "error":
            status, message = "unknown", "named gauge capability needs verification"
        elif uncertain(gauge) and status == "error" and capable:
            status, message = (
                "unknown",
                "unverified gauge dimensions cannot establish capability",
            )
    return status, message


def evaluate(bundle):
    result = []
    for name, feature in bundle.feature_definitions.items():
        requirements = tolerance_requirements(feature)
        # A transient joint feature cites its plan identity, never the drawing manifest.
        cite = [
            "PLAN.md §4.1 inspection",
            *(source_cite(feature) or ["features requirement manifest"]),
            "inventory gauge range/resolution/verification",
        ]
        route = operations(bundle, name)
        missing_checks = False
        for setup, op in route:
            for requirement, gauge in record(op.get("missing_requirements")).items():
                missing_checks = True
                result.append(
                    Finding(
                        "inspection",
                        f"{name}:{requirement}",
                        "unknown",
                        {
                            "requirement": requirement,
                            "missing_requirement": True,
                            "limits": "unknown",
                            "gauge": gauge,
                            "op": f"{setup['id']}:{op['op']}",
                            "inspection_method": record(op.get("inspection_methods")).get(
                                requirement, "unknown"
                            ),
                        },
                        cite,
                        f"{name} {requirement}: requirement is absent from the exported "
                        "manifest; acceptance limits are unresolved.",
                    )
                )
        if feature["kind"] == "unknown" or any(o["do"] == "unknown" for _, o in route):
            for requirement in requirements or [None]:
                subject = f"{name}:{requirement}" if requirement else name
                nominal_error = _nominal_band_error(feature, requirement)
                result.append(
                    Finding(
                        "inspection",
                        subject,
                        "error" if nominal_error else "unknown",
                        {"requirement": requirement or "unknown", **nominal_error},
                        cite,
                        f"{name} {requirement}: exported nominal is outside the requirement band."
                        if nominal_error
                        else f"{name}: inspection applicability or finishing action is "
                        "explicitly unknown.",
                    )
                )
            continue
        if not requirements and not missing_checks:
            result.append(
                Finding(
                    "inspection",
                    name,
                    "not_applicable",
                    {"requirements": []},
                    cite,
                    f"{name}: no tolerance requirement to inspect.",
                )
            )
        finishing = [
            (s, o)
            for s, o in route
            if not o["do"].startswith("rough_")
            and o["do"] not in {"spot", "deburr", "coating", "release"}
        ]
        for requirement in requirements:
            if requirement == "unknown":
                result.append(
                    Finding(
                        "inspection",
                        f"{name}:unknown",
                        "unknown",
                        {"requirement": "unknown"},
                        cite,
                        f"{name}: requirement identity is explicitly unknown.",
                    )
                )
                continue
            checks = [(s, o) for s, o in finishing if requirement in record(o.get("checks"))]
            cutters = [i for i, (_, o) in enumerate(finishing) if o["do"] != "inspect"]
            if cutters:
                checks = [
                    (s, o)
                    for s, o in finishing[cutters[-1] :]
                    if requirement in record(o.get("checks"))
                ]
            value = feature.get(requirement, "unknown")
            nums = {"requirement": requirement, "limits": value, "gauge": "unknown"}
            status = "unknown"
            message = "explicit inspection method is unknown"
            if not checks:
                if any(
                    o.get("checks") == "unknown"
                    for _, o in finishing[cutters[-1] if cutters else 0 :]
                ):
                    message = "inspection checks are explicitly unknown"
                else:
                    status = "error"
                    message = "no requirement-keyed inspection check"
            else:
                setup, op = checks[-1]
                gauge_ref = op["checks"][requirement]
                nums.update(gauge=gauge_ref, op=f"{setup['id']}:{op['op']}")
                status, message = _capability(
                    bundle, feature, requirement, value, gauge_ref, op, nums
                )
            nominal_error = _nominal_band_error(feature, requirement)
            if nominal_error:
                nums.update(nominal_error)
                status, message = "error", "exported nominal is outside the requirement band"
            result.append(
                Finding(
                    "inspection",
                    f"{name}:{requirement}",
                    status,
                    nums,
                    cite,
                    f"{name} {requirement}: {message}.",
                )
            )
    for setup, op in operations(bundle):
        if "process_holds" in op:
            result.append(process_holds(bundle, setup, op))
    return result
