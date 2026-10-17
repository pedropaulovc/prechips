"""Every manifest tolerance needs its own real, capable inspection method.

An op's ``process_holds`` are shop limits tighter than the drawing, held for a stated
process reason (a downstream fit, a clocking stop). Each band must lie inside its drawing
requirement's band, limits included; one reaching outside would pass parts the drawing
rejects. Only a scalar zone/maximum (position, coaxiality, angularity, Ra) ``v`` reads as
the band [0, v]; any other scalar is a nominal with no band to hold inside. A hold on a
reference-only dimension (``<name>_ref``, a CUT TO FIT span) has no drawing band at all:
``not_applicable``, its cited ``measure`` being the only limit. Each hold is read with its
own gauge, graded like a drawing check against the hold band.

An op's ``checks``, ``go_no_go`` and ``inspection_methods`` are read per feature through
:func:`.resolution.op_entry`: a multi-feature inspect op's entry scoped to the feature,
else its flat requirement entry, so each listed feature is judged with its own gauge.

A ``go_no_go`` pair (an op's, per requirement, or a hold's) is a limit check: the GO size
must pass the work and the NO-GO size must not, so both must lie inside the band they
accept, the drawing check's band as printed, a hold's own band. Otherwise the gauge
accepts work the band rejects. A pair declared ``"unknown"`` (the op's whole ``go_no_go``
or one requirement's entry) is still a limit check, with sizes nobody has chosen: unknown.

A radius band ``[0, r]`` is a one-sided "R r MAX" limit (sharp allowed): a radius or
profile gauge reads it go/no-go with its leaf at ``r`` (:func:`max_limit`), so its range
need only hold ``r`` and its resolution not exceed it. Any other band, and any other
gauge, is read across the whole band.

A ``dro_scale`` gauge (a machine's own axis read-out) reads a length along that axis
only, never a diameter or a form.

A BASIC scalar a surface profile governs (``surface_profile_governs``) reads against the
band the zone derives for it (:func:`._profile.requirement_band`), in checks and holds
alike; the zone ``surface_profile`` itself is a geometric zone [0, t] like a position.

No gauge declares an angular capability, so an angle band (``*_deg``) is never read
against a gauge's millimetre range and resolution: unknown. An angle band read across a
face is the exception: a BASIC angle a profile bounds by ``tilt_across``, or a drawn band
whose feature declares ``tilt_across``. It is the deviation read end to end across that
length, so it is judged as the linear zone it is (:func:`._profile.tilt_reading`), on
resolution alone like a zone.
"""

from ..findings import Finding
from ..joint_features import source_cite
from ..measurements import length_debt, length_fact, length_keys, record_debt
from ..model import reference_only, tolerance_requirements
from ._profile import (
    DIAMETERS,
    frame_unresolved,
    governing,
    least_extent,
    requirement_band,
    tilt_length,
    tilt_reading,
)
from .resolution import (
    HOLE_KINDS,
    UNKNOWN,
    drawing_precision,
    identity,
    length_mm,
    number,
    op_entry,
    operations,
    printed_band,
    record,
    resolve,
    same_length,
    uncertain,
)

PROCESS_HOLD_CITE = ["PLAN.md §4.1 inspection", "plan process_holds", "features requirement band"]
ZONES = frozenset(
    {"position_dia", "coaxiality_dia", "angularity_dia", "finish_ra", "surface_profile"}
)
# The geometric zones read in a datum frame: a capable gauge needs a declared method.
GEOMETRIC = frozenset({"position_dia", "coaxiality_dia", "angularity_dia", "surface_profile"})
# The lengths a machine axis read-out measures, along its own axis.
AXIAL_LENGTHS = frozenset({"length", "depth", "height", "thickness", "station"})
# A limit check's gauge kinds: plugs/pins enter a hole; rings/snaps pass over a boss or shaft.
LIMIT_GAUGES = {
    "internal": frozenset({"pin_gauge", "pin_gauge_set", "plug_gauge"}),
    "external": frozenset({"ring_gauge", "snap_gauge"}),
}
EXTERNAL_KINDS = frozenset({"boss", "shaft"})
# Leaf gauges: each leaf is one radius, so a one-sided limit is read by the leaf at it.
LEAF_GAUGES = frozenset({"radius_gauge", "profile_gauge"})
RADII = frozenset({"radius", "bottom_radius"})
_SEVERITY = {"error": 3, "unknown": 2, "unsupported": 2, "pass": 1}


def max_limit(requirement, value):
    """The MAX of a one-sided radius limit, else None. A radius band ``[0, r]`` can only
    mean "R r MAX, sharp allowed": a radius has no measured zero to read. Every other band,
    a two-sided one such as R5 ±0.1 included, is read across its whole span."""
    if requirement not in RADII or not isinstance(value, list) or len(value) != 2:
        return None
    low, high = value
    return high if number(low) and number(high) and low == 0 and high > 0 else None


def leaf_tolerance(gauge):
    """A leaf gauge's ± on each leaf (mm): 0 when the gauge declares none, None when the
    declared fact is unknown or unverified."""
    if not length_keys(gauge, "leaf_tolerance", None):
        return 0.0
    fact = length_fact(gauge, "leaf_tolerance", require_measured=False)
    value = fact["value"]
    return value if fact["verified"] and number(value) and value >= 0 else None


def _drawing_band(requirement, value):
    if number(value):
        return [0, value] if requirement in ZONES else None
    if isinstance(value, list) and len(value) == 2 and all(number(v) for v in value):
        return value
    return None


def go_no_go_pair(op, feature, requirement):
    """The GO / NO-GO pair ``op`` declares for ``feature``'s ``requirement`` (its scoped
    entry, else the flat one): its sizes, ``"unknown"`` when declared unknown (the whole
    ``go_no_go`` or that entry), or None for no limit check. Only a requirement the op
    checks on that feature has one."""
    if op_entry(op, "checks", feature, requirement) is None:
        return None
    if op.get("go_no_go") == UNKNOWN:
        return UNKNOWN
    return op_entry(op, "go_no_go", feature, requirement)


def _gauge_measurements(bundle, gauge, reference, fields):
    """Debt only for the gauge facts this capability check actually used.

    Raw capability lists do not accept fact records. Their existing item-level
    verification flag names the consumed list, without extending record support.
    """
    category, key = identity(bundle, reference, "gauges")
    debts = []
    for field in fields:
        raw = field in {"sizes", "ra_range", "range_ra"} or (
            field == "range" and isinstance(gauge.get("range_mm"), list)
        )
        debt = None if raw else length_debt(gauge, field, category, key)
        if debt is None and gauge.get("verify") in (True, UNKNOWN):
            debt = record_debt(gauge, category, key, field)
        if debt:
            debts.append(debt)
    return debts


def _go_no_go(bundle, feature, requirement, band, pair, gauge, gauge_ref, nums):
    """``(status, message)`` of a declared GO / NO-GO pair against the band it accepts.

    A hole's GO size enters and its NO-GO size must not, so the gauge accepts [GO, NO-GO):
    GO at or above the low limit, NO-GO at or below the high one and above GO. A boss or
    shaft is mirrored (its gauge accepts (NO-GO, GO]). Both sizes must be listed sizes of
    the named gauge."""
    unknown = pair == UNKNOWN
    go, no_go = (UNKNOWN, UNKNOWN) if unknown else (pair["go"], pair["no_go"])
    nums.update(go_mm=go, no_go_mm=no_go, accept_band=band if band is not None else UNKNOWN)
    kind = feature.get("kind", UNKNOWN)
    side = "internal" if kind in HOLE_KINDS else "external" if kind in EXTERNAL_KINDS else None
    gauge_kind = gauge.get("kind", UNKNOWN)
    if requirement != "dia":
        return "unknown", "a GO / NO-GO pair is read only for a diameter"
    if side is None:
        return "unknown", f"GO / NO-GO direction is unresolved for a {kind} feature"
    if gauge_kind == UNKNOWN:
        return "unknown", "gauge identity or capability is explicitly unknown"
    if gauge_kind not in LIMIT_GAUGES[side]:
        return "error", "named gauge cannot make a GO / NO-GO check of this feature"
    if unknown:
        return "unknown", "the GO / NO-GO pair is explicitly unknown"
    if band is None or bundle.features.get("units") != "mm":
        return "unknown", "requirement limits or units are unresolved"
    low, high = band
    inside = low <= go and no_go <= high if side == "internal" else low <= no_go and go <= high
    if not inside:
        return "error", "GO / NO-GO sizes accept work outside the band"
    if (go >= no_go) if side == "internal" else (no_go >= go):
        return "error", "GO / NO-GO sizes accept no work"
    sizes = gauge.get("sizes_mm")
    if not (isinstance(sizes, list) and sizes and all(map(number, sizes))):
        return "unknown", "the gauge lists no sizes_mm to hold the GO / NO-GO sizes"
    absent = [size for size in (go, no_go) if not any(same_length(size, s) for s in sizes)]
    if absent:
        nums["absent_sizes_mm"] = absent
        return "error", "the gauge has no GO / NO-GO size of that diameter"
    if uncertain(gauge):
        debts = _gauge_measurements(bundle, gauge, gauge_ref, ("sizes",))
        if debts:
            nums["measurements"] = debts
        return "unknown", "named gauge capability needs verification"
    return "pass", "GO / NO-GO sizes lie inside the band"


def process_holds(bundle, setup, op):
    """One finding per op: each process hold band against its drawing band."""
    subject = f"{setup['id']}:{op['op']}"
    rows = []
    for hold in op["process_holds"]:
        feature = record(bundle.feature_definitions.get(hold["feature"]))
        limits = _limits(bundle, hold["feature"], hold["requirement"], feature)[0]
        drawing = _drawing_band(hold["requirement"], limits)
        low, high = hold["band"]
        inside = None if drawing is None else drawing[0] <= low and high <= drawing[1]
        if reference_only(feature, hold["requirement"]):
            inside = "not_applicable"
        row = {
            "feature": hold["feature"],
            "requirement": hold["requirement"],
            "band": hold["band"],
            "drawing_band": limits,
            "gauge": hold["gauge"],
            "reason": hold["reason"],
            "inside_drawing_band": UNKNOWN if inside is None else inside,
        }
        for key in ("measure", "cite"):
            if hold.get(key) is not None:
                row[key] = hold[key]
        # The shop reads the hold with its gauge: it must measure that requirement at this band
        # or, as a limit check, accept only the hold band. A REF span is read as its own
        # dimension (``length_ref`` as a length).
        requirement = hold["requirement"]
        if inside == "not_applicable":
            requirement = requirement.removesuffix("_ref")
        tilt = _tilt(bundle, hold["feature"], requirement, feature, row)
        capability, reading = _capability(
            bundle,
            feature,
            requirement,
            hold["band"],
            hold["gauge"],
            op_entry(op, "inspection_methods", hold["feature"], requirement),
            row,
            limits=(hold.get("go_no_go"), hold["band"]),
            tilt=tilt,
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
        else (
            "pass",
            "every process hold lies inside its drawing band (a reference-only dimension "
            "has none), read by a capable gauge",
        )
    )
    numbers = {"process_holds": rows}
    if status == UNKNOWN:
        debts = {entry["id"]: entry for row in rows for entry in row.get("measurements", [])}
        if debts:
            numbers["measurements"] = [debts[key] for key in sorted(debts)]
    return Finding(
        "inspection",
        subject,
        status,
        numbers,
        PROCESS_HOLD_CITE,
        f"{subject}: {message}.",
    )


def _limits(bundle, name, requirement, feature):
    """``(limits, reason)``: ``requirement``'s value as drawn, but a BASIC scalar a surface
    profile governs reads as its derived band (``"unknown"`` with the reason, unresolved)."""
    if not governing(bundle, name, requirement):
        return feature.get(requirement, UNKNOWN), None
    band, reason = requirement_band(bundle, name, requirement)
    return band or UNKNOWN, reason


def _tilt(bundle, name, requirement, feature, nums):
    """``(nominal angle, length)``: an angle ``requirement`` read as the linear zone across
    a face length, else None. A BASIC angle a surface profile bounds by ``tilt_across`` reads
    about its BASIC value; a drawn band its feature reads ``tilt_across`` a face reads about
    its mid angle, where a template reads both limits alike. The length, or why there is
    none, goes in ``nums``."""
    if not requirement.endswith("_deg"):
        return None
    if governing(bundle, name, requirement):
        nominal = feature[requirement]
        length, reason = tilt_length(bundle, name, requirement)
    elif requirement in record(feature.get("tilt_across")):
        drawn = feature[requirement]
        nominal = sum(drawn) / 2 if all(number(v) for v in drawn) else None
        length, reason = least_extent(feature["tilt_across"][requirement], feature)
    else:
        return None
    nums["tilt_across_length"] = UNKNOWN if length is None else length
    if length is None:
        nums["tilt_across_reason"] = reason
        return None
    return None if nominal is None else (nominal, length)


def _nominal_band_error(feature, requirement):
    limits = feature.get(requirement)
    if not (isinstance(limits, list) and len(limits) == 2 and all(number(v) for v in limits)):
        return {}
    for field in (f"{requirement}_nominal", f"nominal_{requirement}"):
        nominal = feature.get(field)
        if number(nominal) and not limits[0] <= nominal <= limits[1]:
            return {"nominal_field": field, "nominal": nominal, "limits": limits}
    return {}


def procedure_known(method):
    """An authored inspection procedure: a non-empty string other than ``unknown``, or a
    list of steps each of which is one."""
    steps = method if isinstance(method, list) else [method]
    return bool(steps) and all(
        isinstance(step, str) and bool(step.strip()) and step.strip() != "unknown" for step in steps
    )


def _capability(
    bundle, feature, requirement, value, gauge_ref, method, nums, limits=None, tilt=None
):
    """``(status, message)`` and consumed debt in ``nums`` for an unresolved capability.

    ``method`` is the op's authored inspection procedure for this check, or None.

    ``limits`` is ``(pair, band the pair must accept)``, the GO / NO-GO pair being sizes,
    ``"unknown"`` or None: a declared pair, even an unknown one, makes it a limit check,
    judged by :func:`_go_no_go` instead of span and resolution. ``tilt`` is ``(nominal
    angle, face length)`` when an angle band is read across that face (:func:`_tilt`): the
    band is then judged as its linear zone, on resolution alone; any other angle band has
    no gauge path."""
    pair, accept = limits or (None, None)
    status, message = "unknown", "explicit inspection method is unknown"
    gauge = resolve(bundle, "gauges", gauge_ref)
    if gauge_ref != "unknown" and gauge is None:
        # The inventory reference finding owns the single missing-item error.
        message = "named gauge is not listed; capability unresolved"
    elif gauge:
        kind = gauge.get("kind", "unknown")
        consumed = ()
        # Only the resolution fact's own trust lets it establish or refute capability.
        fact = length_fact(gauge, "resolution", require_measured=False)
        resolution = fact["value"] if fact["verified"] else "unknown"
        span = gauge.get("range_mm")
        if not isinstance(span, list):
            maximum = length_mm(gauge, "range")
            span = [0, maximum] if number(maximum) else "unknown"
        nums.update(gauge_kind=kind, range_mm=span, resolution_mm=resolution)
        if pair is not None:
            return _go_no_go(bundle, feature, requirement, accept, pair, gauge, gauge_ref, nums)
        angular = (
            requirement.endswith("_deg")
            and isinstance(value, list)
            and len(value) == 2
            and all(number(v) for v in value)
        )
        # An angle band read across a face is the deviation end to end over that length: a
        # linear zone of that width, never degrees against a millimetre gauge.
        linear = tilt_reading(value, *tilt) if angular and tilt is not None else None
        angular = angular and linear is None
        geometric = requirement in GEOMETRIC
        method_known = procedure_known(method)
        angularity_datums = feature.get("angularity_datums", "unknown")
        angularity_geometry_known = (
            isinstance(angularity_datums, list)
            and bool(angularity_datums)
            and all(
                isinstance(datum, str) and bool(datum.strip()) and datum != "unknown"
                for datum in angularity_datums
            )
        )
        # A profile's frame may be empty (form only), but each datum must resolve to a
        # manifest feature.
        profile_datums = feature.get("surface_profile_datums", "unknown")
        profile_frame_known = (
            requirement == "surface_profile" and frame_unresolved(bundle, profile_datums) is None
        )
        if geometric:
            nums["inspection_method"] = method or "unknown"
        if requirement == "angularity_dia":
            nums["angularity_datums"] = angularity_datums
        if requirement == "surface_profile":
            nums["surface_profile_datums"] = profile_datums
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
            else requirement in AXIAL_LENGTHS
            if kind == "dro_scale"
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
            and requirement in DIAMETERS
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
            or (requirement == "surface_profile" and not profile_frame_known)
        ):
            message = "geometric gauge capability or datum inspection method unresolved"
        elif requirement == "finish_ra":
            consumed = ("ra_range" if "ra_range" in gauge else "range_ra",)
            capability = gauge.get("ra_range", gauge.get("range_ra", "unknown"))
            nums["ra_range"] = capability
            # The Ra limits the gauge must read: a scalar maximum, or a band's nonzero ends.
            readings = (
                [value]
                if number(value)
                else [v for v in value if v]
                if isinstance(value, list) and len(value) == 2 and all(number(v) for v in value)
                else None
            )
            if (
                isinstance(capability, list)
                and all(number(v) for v in capability)
                and readings is not None
            ):
                spans = all(capability[0] <= v <= capability[1] for v in readings)
                status = "pass" if spans else "error"
                message = (
                    "roughness gauge spans requirement"
                    if status == "pass"
                    else "roughness requirement outside gauge range"
                )
            else:
                message = "roughness gauge capability unresolved"
        elif angular:
            # Gauges declare millimetre range and resolution only: degrees never meet them.
            message = "no angular gauge capability"
        elif linear is not None:
            # Like every zone, judged on resolution alone: an end-to-end deviation reading
            # has no size for the gauge's range to span.
            consumed = ("resolution",)
            nums["band_mm"] = linear
            if not number(resolution):
                message = "gauge resolution unresolved"
            elif resolution > linear:
                status, message = "error", "gauge resolution exceeds the requirement band"
            else:
                status, message = "pass", "gauge resolves the tilt's linear zone across its face"
        elif isinstance(value, list) and len(value) == 2 and all(number(v) for v in value):
            consumed = ("range", "resolution")
            limit = max_limit(requirement, value) if kind in LEAF_GAUGES else None
            tolerance = 0.0
            if limit is not None:
                nums.update(limit_check="max", limit_mm=limit)
                tolerance = leaf_tolerance(gauge)
                if length_keys(gauge, "leaf_tolerance", None):
                    consumed += ("leaf_tolerance",)
                    nums["leaf_tolerance_mm"] = UNKNOWN if tolerance is None else tolerance
            if not (isinstance(span, list) and all(number(v) for v in span) and number(resolution)):
                message = "gauge range or resolution unresolved"
            elif limit is not None and tolerance is None:
                message = "limit check: gauge leaf tolerance unresolved"
            elif limit is not None:
                # Go/no-go at the limit: a leaf at or under R MAX seats without rocking on a
                # corner at or under it. A leaf marked L may really be L + t, accepting
                # corners past the limit, so the leaf read is one at or under r - t. Sharp
                # needs no leaf, so the band is never read across.
                guard = limit - tolerance
                if span[0] <= limit <= span[1] and guard < span[0]:
                    status, message = (
                        "error",
                        f"limit check: the leaf's ±{tolerance:g} tolerance crosses the MAX "
                        "limit (no leaf at or under the limit less its tolerance)",
                    )
                elif not span[0] <= guard <= span[1]:
                    status, message = "error", "limit check: gauge has no leaf at the MAX limit"
                elif resolution > limit:
                    status, message = (
                        "error",
                        "limit check: gauge resolution exceeds the MAX limit",
                    )
                else:
                    status, message = (
                        "pass",
                        "limit check: a gauge leaf at or under the MAX limit, less its "
                        "tolerance, reads go/no-go (not a reading across the band)",
                    )
            else:
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
        elif geometric and number(value):
            consumed = ("resolution",)
            if number(resolution) and resolution <= value and method_known:
                status, message = (
                    "pass",
                    "gauge resolution and declared geometric inspection method cover requirement",
                )
            else:
                message = "geometric gauge capability or datum inspection method unresolved"
        else:
            message = "inspection capability for requirement unresolved"
        if uncertain(gauge) and status != "error" and not angular:
            status, message = "unknown", "named gauge capability needs verification"
        elif uncertain(gauge) and status == "error" and capable:
            status, message = (
                "unknown",
                "unverified gauge dimensions cannot establish capability",
            )
        if status == UNKNOWN:
            debts = _gauge_measurements(bundle, gauge, gauge_ref, consumed)
            if debts:
                nums["measurements"] = debts
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
                method = op_entry(op, "inspection_methods", name, requirement)
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
                            "inspection_method": UNKNOWN if method is None else method,
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
            cutters = [i for i, (_, o) in enumerate(finishing) if o["do"] != "inspect"]
            checks = [
                (s, o)
                for s, o in finishing[cutters[-1] if cutters else 0 :]
                if op_entry(o, "checks", name, requirement) is not None
            ]
            value, profile_band = _limits(bundle, name, requirement, feature)
            nums = {"requirement": requirement, "limits": value, "gauge": "unknown"}
            if profile_band is not None:
                nums["profile_band"] = profile_band
            tilt = _tilt(bundle, name, requirement, feature, nums)
            # A limit check accepts the band as the traveler prints it (rounded inward).
            accept = printed_band(value, drawing_precision(bundle, name, requirement))
            accept = accept or _drawing_band(requirement, value)
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
                gauge_ref = op_entry(op, "checks", name, requirement)
                nums.update(gauge=gauge_ref, op=f"{setup['id']}:{op['op']}")
                pair = go_no_go_pair(op, name, requirement)
                method = op_entry(op, "inspection_methods", name, requirement)
                limits = (pair, accept)
                status, message = _capability(
                    bundle, feature, requirement, value, gauge_ref, method, nums, limits, tilt
                )
            # Every other op's GO / NO-GO pair for this requirement also prints the drawing
            # band, so it must accept only that band too.
            final = checks[-1][1] if checks else None
            others = []
            for other_setup, other in route:
                pair = go_no_go_pair(other, name, requirement)
                if pair is None or other is final:
                    continue
                row = {
                    "op": f"{other_setup['id']}:{other['op']}",
                    "gauge": op_entry(other, "checks", name, requirement),
                }
                row["status"], row["message"] = _capability(
                    bundle,
                    feature,
                    requirement,
                    value,
                    row["gauge"],
                    op_entry(other, "inspection_methods", name, requirement),
                    row,
                    (pair, accept),
                    tilt,
                )
                others.append(row)
            if others:
                nums["other_go_no_go"] = others
                worst = max(others, key=lambda row: _SEVERITY[row["status"]])
                if _SEVERITY[worst["status"]] > _SEVERITY[status]:
                    status, message = worst["status"], f"{worst['op']}: {worst['message']}"
            nominal_error = _nominal_band_error(feature, requirement)
            if nominal_error:
                nums.update(nominal_error)
                status, message = "error", "exported nominal is outside the requirement band"
            if status == UNKNOWN:
                debts = {entry["id"]: entry for entry in nums.get("measurements", [])}
                debts.update(
                    (entry["id"], entry) for row in others for entry in row.get("measurements", [])
                )
                if debts:
                    nums["measurements"] = [debts[key] for key in sorted(debts)]
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
