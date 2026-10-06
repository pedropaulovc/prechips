"""Every manifest tolerance needs its own real, capable inspection method."""

from ..findings import Finding
from ..joint_features import source_cite
from ..measurements import length_fact
from ..model import tolerance_requirements
from .resolution import length_mm, number, operations, record, resolve, uncertain


def _nominal_band_error(feature, requirement):
    limits = feature.get(requirement)
    if not (isinstance(limits, list) and len(limits) == 2 and all(number(v) for v in limits)):
        return {}
    for field in (f"{requirement}_nominal", f"nominal_{requirement}"):
        nominal = feature.get(field)
        if number(nominal) and not limits[0] <= nominal <= limits[1]:
            return {"nominal_field": field, "nominal": nominal, "limits": limits}
    return {}


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
                        isinstance(method, str)
                        and bool(method.strip())
                        and method.strip() != "unknown"
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
                        else kind
                        in {"cmm", "dial_indicator", "dial_test_indicator", "height_gauge"}
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
                        not method_known
                        or (requirement == "angularity_dia" and not angularity_geometry_known)
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
                    elif (
                        isinstance(value, list)
                        and len(value) == 2
                        and all(number(v) for v in value)
                    ):
                        if (
                            isinstance(span, list)
                            and all(number(v) for v in span)
                            and number(resolution)
                        ):
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
                                "gauge resolution and declared geometric inspection method "
                                "cover requirement",
                            )
                        else:
                            message = (
                                "geometric gauge capability or datum inspection method unresolved"
                            )
                    else:
                        message = "inspection capability for requirement unresolved"
                    if uncertain(gauge) and status != "error":
                        status, message = "unknown", "named gauge capability needs verification"
                    elif uncertain(gauge) and status == "error" and capable:
                        status, message = (
                            "unknown",
                            "unverified gauge dimensions cannot establish capability",
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
    return result
