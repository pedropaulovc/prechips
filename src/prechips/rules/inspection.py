"""Every manifest tolerance needs its own real, capable inspection method."""
from ..findings import Finding
from .resolution import TOLERANCES, length_mm, number, operations, resolve, uncertain


def evaluate(bundle):
    result = []
    for name, feature in bundle.features["features"].items():
        requirements = sorted(set(feature.get("requirements", [])) & TOLERANCES)
        cite = ["PLAN.md §4.1 inspection", "features requirement manifest", "inventory gauge range/resolution/verification"]
        if not requirements:
            result.append(Finding("inspection", name, "not_applicable", {"requirements": []}, cite, f"{name}: no tolerance requirement to inspect."))
        route = operations(bundle, name)
        finishing = [(s, o) for s, o in route if not o["do"].startswith("rough_") and o["do"] not in {"spot", "deburr", "coating", "release"}]
        for requirement in requirements:
            checks = [(s, o) for s, o in finishing if requirement in o.get("checks", {})]
            cutters = [i for i, (_, o) in enumerate(finishing) if o["do"] != "inspect"]
            if cutters:
                checks = [(s, o) for s, o in finishing[cutters[-1]:] if requirement in o.get("checks", {})]
            value = feature.get(requirement, "unknown")
            nums = {"requirement": requirement, "limits": value, "gauge": "unknown"}
            status = "unknown"
            message = "explicit inspection method is unknown"
            if not checks:
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
                    resolution = length_mm(gauge, "resolution")
                    span = gauge.get("range_mm")
                    if not isinstance(span, list):
                        maximum = length_mm(gauge, "range")
                        span = [0, maximum] if number(maximum) else "unknown"
                    nums.update(gauge_kind=kind, range_mm=span, resolution_mm=resolution)
                    method = op.get("inspection_methods", {}).get(requirement)
                    geometric = requirement in {"position_dia", "coaxiality_dia"}
                    complex_shape = requirement in {"radius", "bottom_radius", "arc_len", "bottom_arc_len", "land_angle_deg", "height_above_pivot"}
                    capable = (kind in {"roughness_gauge", "roughness_comparator", "profilometer"} if requirement == "finish_ra"
                               else kind in {"cmm", "dial_indicator", "dial_test_indicator", "height_gauge"} if geometric
                               else kind in {"cmm", "profile_gauge", "radius_gauge", "angle_gauge"} if complex_shape
                               else kind in {"caliper", "micrometer", "micrometer_set", "pin_gauge", "pin_gauge_set", "bore_gauge", "height_gauge", "depth_gauge", "cmm"})
                    if feature["kind"] in {"hole", "thread", "threaded_hole"} and requirement == "dia" and kind in {"micrometer", "micrometer_set"}:
                        capable = False
                    if not capable:
                        status, message = "error", "named gauge cannot measure this requirement"
                    elif value == "unknown" or bundle.features.get("units") != "mm":
                        message = "requirement limits or units are unresolved"
                    elif requirement == "finish_ra":
                        capability = gauge.get("ra_range", gauge.get("range_ra", "unknown"))
                        nums["ra_range"] = capability
                        if isinstance(capability, list) and all(number(v) for v in capability) and number(value):
                            status = "pass" if capability[0] <= value <= capability[1] else "error"
                            message = "roughness gauge spans requirement" if status == "pass" else "roughness requirement outside gauge range"
                        else:
                            message = "roughness gauge capability unresolved"
                    elif isinstance(value, list) and len(value) == 2 and all(number(v) for v in value):
                        if isinstance(span, list) and all(number(v) for v in span) and number(resolution):
                            nums["band_mm"] = value[1] - value[0]
                            if span[0] > value[0] or span[1] < value[1]:
                                status, message = "error", "gauge does not span the requirement band"
                            elif resolution > value[1] - value[0]:
                                status, message = "error", "gauge resolution exceeds the requirement band"
                            else:
                                status, message = "pass", "gauge spans the band at sufficient resolution"
                        else:
                            message = "gauge range or resolution unresolved"
                    elif geometric and number(value):
                        if number(resolution) and resolution <= value and method:
                            status, message = "pass", "gauge resolution and declared geometric inspection method cover requirement"
                        else:
                            message = "geometric gauge capability or datum inspection method unresolved"
                    else:
                        message = "inspection capability for requirement unresolved"
                    if uncertain(gauge) and status != "error":
                        status, message = "unknown", "named gauge capability needs verification"
                    elif uncertain(gauge) and status == "error" and capable:
                        status, message = "unknown", "unverified gauge dimensions cannot establish capability"
            result.append(Finding("inspection", f"{name}:{requirement}", status, nums, cite, f"{name} {requirement}: {message}."))
    return result
