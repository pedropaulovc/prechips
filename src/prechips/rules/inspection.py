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

Inspection-plan passes describe a capable declared checkpoint, never an observed part:
``evaluation="inspection_plan"`` and ``part_result="not_recorded"``. Physical results stay
blank. Registered final checks own exactly one member; typed manual acceptance belongs
once to that part, not once to each participating feature, and grants no machining credit.
The shared target selector is :func:`.resolution.op_check_targets`.

Ordinary unscoped checks retain final-cutter ordering. A scoped shared dimensional check
may precede later work only with requirement-specific native supporting-surface survival
through every member's actual descendant route. Registered containment alone is not that
proof. Explicit unknown scope, comparator identity or capability remains unresolved.

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

A height from a datum axis (``height_above_pivot``, from the feature's ``height_from``) is
a linear height, not a form: a CMM, a height gauge over a pin in the datum bore on a
surface plate, or a profile template carrying its own datum pin reads it. A radius or angle
gauge reads no height, and a caliper has no reference plane to read it square to the
datum, only a nearest-point distance. The setup is debt until both the datum
(``height_from`` naming another exported manifest feature) and an authored procedure are
declared.
"""

import math

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
    _citations,
    drawing_precision,
    identity,
    inspection_preservation_evidence,
    length_mm,
    number,
    op_check_targets,
    op_entry,
    op_features,
    operation_members,
    operations,
    printed_band,
    record,
    registered_workpieces,
    resolve,
    same_length,
    thread_class_acceptance,
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
# The heights read from a datum axis (``height_from``) to a surface.
DATUM_HEIGHTS = frozenset({"height_above_pivot"})
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


def leaves_unknown(gauge):
    """Whether the gauge declares its leaf inventory ``sizes_mm`` as unknown, wholly or in
    part: it then neither shows a leaf nor rules one out."""
    if "sizes_mm" not in gauge:
        return False
    sizes = gauge["sizes_mm"]
    return not isinstance(sizes, list) or any(not number(leaf) for leaf in sizes)


def leaf_under(gauge, span, resolution, size):
    """The largest leaf of the set at or under ``size``, else None. A declared
    ``sizes_mm`` is the leaf inventory, an empty one none at all; without it the leaves
    are the steps of ``resolution`` (the leaf pitch, positive) up from ``range_mm[0]``."""
    if "sizes_mm" in gauge:
        sizes = gauge["sizes_mm"]
        listed = [leaf for leaf in sizes if number(leaf)] if isinstance(sizes, list) else []
        under = [leaf for leaf in listed if leaf <= size or same_length(leaf, size)]
        return max(under) if under else None
    if size < span[0] and not same_length(size, span[0]):
        return None
    steps = math.floor((size - span[0]) / resolution + 1e-9)
    return span[0] + resolution * steps


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
            name=hold["feature"],
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
    numbers = {
        "process_holds": rows,
        "setup_id": setup["id"],
        "op_id": op["op"],
        "op": subject,
        "evaluation": "inspection_plan",
        "part_result": "not_recorded",
    }
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


def _height_datum(bundle, name, feature):
    """The exported manifest feature ``name``'s ``height_from`` names as its datum, else None:
    unknown, a plan joint or process feature, or ``name`` itself (no independent datum)."""
    datum = feature.get("height_from", UNKNOWN)
    if datum == UNKNOWN or datum == name:
        return None
    return datum if datum in record(bundle.features.get("features")) else None


def _capability(
    bundle, feature, requirement, value, gauge_ref, method, nums, limits=None, tilt=None, name=None
):
    """``(status, message)`` and consumed debt in ``nums`` for an unresolved capability of the
    feature ``name`` (``feature`` its definition).

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
        # Only the resolution fact's own trust lets it establish or refute capability; a
        # step that is not positive reads nothing, so it is never sufficient (#315).
        fact = length_fact(gauge, "resolution", require_measured=False)
        trusted = fact["verified"] and number(fact["value"]) and fact["value"] > 0
        resolution = fact["value"] if trusted else "unknown"
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
        datum_height = requirement in DATUM_HEIGHTS
        height_from = feature.get("height_from", UNKNOWN)
        if geometric or datum_height:
            nums["inspection_method"] = method or "unknown"
        if datum_height:
            nums["height_from"] = height_from
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
        }
        capable = (
            kind in {"roughness_gauge", "roughness_comparator", "profilometer"}
            if requirement == "finish_ra"
            else kind in {"cmm", "dial_indicator", "dial_test_indicator", "height_gauge"}
            if geometric
            else kind in {"cmm", "height_gauge", "profile_gauge"}
            if datum_height
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
        elif datum_height and not (method_known and _height_datum(bundle, name, feature)):
            # The datum pin and plate setup the reading stands on: unknown until declared.
            message = "datum height setup (height_from datum or inspection method) unresolved"
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
            # The operator reads the MAX the traveler prints, rounded inward to the drawing's
            # precision: the leaf must be that one, never the raw limit.
            printed = accept[1] if isinstance(accept, list) and len(accept) == 2 else None
            if limit is not None and number(printed) and printed != limit:
                nums["drawing_limit_mm"] = limit
                limit = printed
            tolerance = 0.0
            if limit is not None:
                nums.update(limit_check="max", limit_mm=limit)
                tolerance = leaf_tolerance(gauge)
                if length_keys(gauge, "leaf_tolerance", None):
                    consumed += ("leaf_tolerance",)
                    nums["leaf_tolerance_mm"] = UNKNOWN if tolerance is None else tolerance
            if not (isinstance(span, list) and all(number(v) for v in span) and number(resolution)):
                message = "gauge range or resolution unresolved"
            elif limit is not None and resolution <= 0:
                # No leaf pitch: the set's leaves cannot be laid out to find the limit's.
                message = "gauge range or resolution unresolved"
            elif limit is not None and not span[0] <= limit <= span[1]:
                status, message = "error", "limit check: gauge has no leaf at the MAX limit"
            elif limit is not None and resolution > limit:
                status, message = "error", "limit check: gauge resolution exceeds the MAX limit"
            elif limit is not None and tolerance is None:
                message = "limit check: gauge leaf tolerance unresolved"
            elif limit is not None and leaves_unknown(gauge):
                # An unknown inventory cannot show which leaves exist, nor that none does.
                message = "limit check: gauge leaf sizes unresolved"
            elif limit is not None:
                # Go/no-go at the limit: a leaf at or under R MAX seats without rocking on a
                # corner at or under it. A leaf marked L may really be L + t, accepting
                # corners past the limit, so the leaf read must be one at or under r - t.
                # Sharp needs no leaf, so the band is never read across.
                guard = limit - tolerance
                safe = leaf_under(gauge, span, resolution, guard)
                at_limit = leaf_under(gauge, span, resolution, limit)
                if safe is not None:
                    nums["leaf_max_mm"] = safe
                if safe is None and tolerance > 0:
                    status, message = (
                        "error",
                        f"limit check: the leaf's ±{tolerance:g} tolerance crosses the MAX "
                        "limit (no leaf at or under the limit less its tolerance)",
                    )
                elif safe is None:
                    status, message = "error", "limit check: gauge has no leaf at the MAX limit"
                elif tolerance > 0:
                    # Only a leaf under the limit is safe, and the traveler prints the band
                    # and gauge, never which leaf: the operator would reach for the limit's.
                    message = (
                        f"limit check: only a leaf at or under R{guard:g} reads the limit, "
                        "and the traveler does not name it"
                    )
                elif not same_length(at_limit, limit):
                    # The set brackets the limit but no leaf is R MAX: a smaller leaf is
                    # safe, yet the traveler names no leaf, so the operator has none to use.
                    message = (
                        f"limit check: the gauge has no R{limit:g} leaf, and the traveler "
                        "does not name the smaller one that reads the limit"
                    )
                else:
                    status, message = (
                        "pass",
                        "limit check: the gauge's leaf at the MAX limit reads go/no-go "
                        "(not a reading across the band)",
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


def requirement_check(bundle, name, requirement, op, *, setup=None, workpiece=None):
    """Inspection-plan capability, preserving the historical four-argument/triple API.

    ``name=None`` selects a typed part relationship. An inspection-plan pass never
    records a measured result or certifies the physical part.
    """
    if name is None:
        return _manual_check(bundle, requirement, op, setup=setup, workpiece=workpiece)
    feature = record(bundle.feature_definitions.get(name))
    value, _ = _limits(bundle, name, requirement, feature)
    gauge_ref = op_entry(op, "checks", name, requirement)
    nums = {
        "requirement": requirement,
        "limits": value,
        "gauge": gauge_ref,
        "identity": {"workpiece": workpiece, "feature_owner": name, "requirement": requirement},
        "evaluation": "inspection_plan",
        "part_result": "not_recorded",
    }
    tilt = _tilt(bundle, name, requirement, feature, nums)
    accept = printed_band(value, drawing_precision(bundle, name, requirement))
    accept = accept or _drawing_band(requirement, value)
    status, message = _capability(
        bundle,
        feature,
        requirement,
        value,
        gauge_ref,
        op_entry(op, "inspection_methods", name, requirement),
        nums,
        (go_no_go_pair(op, name, requirement), accept),
        tilt,
        name=name,
    )
    if setup is not None:
        nums.update(setup_id=setup["id"], op_id=op["op"], op=f"{setup['id']}:{op['op']}")
        if workpiece is not None and registered_workpieces(bundle):
            targets = [
                target
                for target in op_check_targets(bundle, setup, op)
                if target["identity"]["feature_owner"] == name
                and target["identity"]["requirement"] == requirement
            ]
            if any(target["selection_status"] == UNKNOWN for target in targets):
                if status != "error":
                    status, message = UNKNOWN, "inspection workpiece identity is unresolved"
            elif not any(
                target["identity"]["workpiece"] == workpiece
                or workpiece in target["covered_workpieces"]
                for target in targets
            ):
                status, message = "error", "inspection belongs to a different workpiece"
    return status, message, nums


def _manual_check(bundle, requirement, op, *, setup=None, workpiece=None):
    from prechips.thread_specs import match, mating_classes, selected_class_status

    relationship = record(record(bundle.features.get("acceptance")).get(requirement))
    contract = record(relationship.get("contract"))
    gauge_ref = op_entry(op, "checks", None, requirement)
    method = op_entry(op, "inspection_methods", None, requirement)
    nums = {
        "requirement": requirement,
        "identity": {"workpiece": workpiece, "feature_owner": None, "requirement": requirement},
        "gauge": gauge_ref,
        "inspection_method": method if method is not None else UNKNOWN,
        "contract": relationship.get("contract", UNKNOWN),
        "participants": relationship.get("features", []),
        "evaluation": "inspection_plan",
        "part_result": "not_recorded",
    }
    errors, debts = [], []
    clauses = contract.get("accept")
    if contract.get("kind") != "manual":
        debts.append("manual acceptance contract is unresolved")
    if not (
        isinstance(clauses, list)
        and clauses
        and all(
            isinstance(text, str) and text.strip() and text.strip() != UNKNOWN for text in clauses
        )
    ):
        debts.append("manual acceptance clauses are unresolved")
    if not _citations(contract.get("cite")):
        debts.append("manual acceptance source is unresolved")
    if not procedure_known(method):
        debts.append("manual inspection method is unresolved")
    gauge = resolve(bundle, "gauges", gauge_ref)
    if gauge is None:
        if gauge_ref in (None, UNKNOWN):
            debts.append("comparator identity is unresolved")
        else:
            errors.append("named comparator is not listed")
    elif not isinstance(gauge, dict):
        debts.append("comparator identity is unresolved")
    else:
        kind = gauge.get("kind", UNKNOWN)
        expected = contract.get("gauge_kind", UNKNOWN)
        nums.update(gauge_kind=kind, required_gauge_kind=expected)
        if kind == UNKNOWN or expected == UNKNOWN:
            debts.append("comparator kind is unresolved")
        elif kind != expected:
            errors.append("named comparator has the wrong kind")
        if gauge.get("present") is False:
            errors.append("named comparator is not present")
        elif uncertain(gauge):
            debts.append("named comparator identity or presence needs verification")
        if expected == "mating_hardware" and kind == expected:
            for name in relationship.get("features", []):
                feature = record(bundle.feature_definitions.get(name))
                if feature.get("kind") not in {"thread", "threaded_hole"}:
                    continue
                matched = match(feature.get("thread"), gauge.get("thread"))
                if matched is False:
                    errors.append(f"{name}: comparator thread designation differs")
                elif matched is None:
                    debts.append(f"{name}: comparator thread designation is unresolved")
                hands = (feature.get("thread_hand"), gauge.get("thread_hand"))
                if all(hand in {"right", "left"} for hand in hands):
                    if hands[0] != hands[1]:
                        errors.append(f"{name}: comparator thread hand differs")
                else:
                    debts.append(f"{name}: comparator thread hand is unresolved")
                class_status = selected_class_status(
                    feature, gauge, acceptance=thread_class_acceptance(bundle, name)
                )
                if class_status != "not_adopted":
                    classes = mating_classes(feature.get("thread_class"), gauge.get("thread_class"))
                    if classes is False:
                        errors.append(f"{name}: comparator thread class has the wrong mating role")
                    elif classes is None:
                        debts.append(f"{name}: comparator thread class is unresolved")
    if setup is not None:
        nums.update(setup_id=setup["id"], op_id=op["op"], op=f"{setup['id']}:{op['op']}")
        if registered_workpieces(bundle):
            targets = [
                target
                for target in op_check_targets(bundle, setup, op)
                if target["kind"] == "manual" and target["identity"]["requirement"] == requirement
            ]
            if workpiece is None or any(
                target["selection_status"] == UNKNOWN for target in targets
            ):
                debts.append("inspection workpiece identity is unresolved")
            elif not any(target["identity"]["workpiece"] == workpiece for target in targets):
                errors.append("inspection belongs to a different workpiece")
    nums.update(errors=errors, unresolved=debts)
    if errors:
        return "error", "; ".join(errors), nums
    if debts:
        return UNKNOWN, "; ".join(debts), nums
    return "pass", "declared manual comparator and method cover the acceptance contract", nums


def _dimensional_finding(name, workpiece, subject, status, nums, cite, sentence):
    nums.update(
        identity={
            "workpiece": workpiece,
            "feature_owner": name,
            "requirement": nums.get("requirement"),
        },
        kind="dimensional",
        shared_check_id=None,
        covered_workpieces=[],
        evaluation="inspection_plan",
        part_result="not_recorded",
    )
    return Finding(
        "inspection",
        f"{workpiece}/{subject}" if workpiece is not None else subject,
        status,
        nums,
        cite,
        sentence,
    )


def _target_applies(bundle, setup, target, workpiece):
    if target["identity"]["workpiece"] == workpiece:
        return True
    if target["selection_status"] != UNKNOWN:
        return False
    if workpiece is None:
        return True
    from prechips.material_routes import MaterialGraph

    return workpiece in (MaterialGraph(bundle.plan).members(setup["id"]) or ())


def _selected_target(bundle, setup, op, name, requirement, workpiece):
    return next(
        (
            target
            for target in op_check_targets(bundle, setup, op)
            if target["identity"]["feature_owner"] == name
            and target["identity"]["requirement"] == requirement
            and target["shared_check_id"] is None
            and _target_applies(bundle, setup, target, workpiece)
        ),
        None,
    )


def _dimensional_findings(bundle, *, workpiece=None, shared_coverage=frozenset()):
    result = []
    for name, feature in bundle.feature_definitions.items():
        requirements = tolerance_requirements(feature)
        # A transient joint feature cites its plan identity, never the drawing manifest.
        cite = [
            "PLAN.md §4.1 inspection",
            *(source_cite(feature) or ["features requirement manifest"]),
            "inventory gauge range/resolution/verification",
        ]
        route = [
            (setup, op)
            for setup, op in operations(bundle, name)
            if workpiece is None
            or workpiece in (operation_members(bundle, setup, op) or ())
            or any(
                _target_applies(bundle, setup, target, workpiece)
                for target in op_check_targets(bundle, setup, op)
            )
        ]
        missing_checks = False
        for setup, op in route:
            for requirement, gauge in record(op.get("missing_requirements")).items():
                missing_checks = True
                method = op_entry(op, "inspection_methods", name, requirement)
                result.append(
                    _dimensional_finding(
                        name,
                        workpiece,
                        f"{name}:{requirement}",
                        "unknown",
                        {
                            "requirement": requirement,
                            "missing_requirement": True,
                            "limits": "unknown",
                            "gauge": gauge,
                            "op": f"{setup['id']}:{op['op']}",
                            "setup_id": setup["id"],
                            "op_id": op["op"],
                            "inspection_method": UNKNOWN if method is None else method,
                        },
                        cite,
                        f"{name} {requirement}: requirement is absent from the exported "
                        "manifest; acceptance limits are unresolved.",
                    )
                )
        if requirements and all(
            (workpiece, name, requirement) in shared_coverage for requirement in requirements
        ):
            continue
        if feature["kind"] == "unknown" or any(o["do"] == "unknown" for _, o in route):
            for requirement in requirements or [None]:
                if (workpiece, name, requirement) in shared_coverage:
                    continue
                subject = f"{name}:{requirement}" if requirement else name
                nominal_error = _nominal_band_error(feature, requirement)
                result.append(
                    _dimensional_finding(
                        name,
                        workpiece,
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
                _dimensional_finding(
                    name,
                    workpiece,
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
            if (workpiece, name, requirement) in shared_coverage:
                continue
            if requirement == "unknown":
                result.append(
                    _dimensional_finding(
                        name,
                        workpiece,
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
                if _selected_target(bundle, s, o, name, requirement, workpiece) is not None
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
                target = _selected_target(bundle, setup, op, name, requirement, workpiece)
                nums.update(target)
                gauge_ref = op_entry(op, "checks", name, requirement)
                nums.update(gauge=gauge_ref, op=f"{setup['id']}:{op['op']}")
                pair = go_no_go_pair(op, name, requirement)
                method = op_entry(op, "inspection_methods", name, requirement)
                limits = (pair, accept)
                status, message = _capability(
                    bundle,
                    feature,
                    requirement,
                    value,
                    gauge_ref,
                    method,
                    nums,
                    limits,
                    tilt,
                    name=name,
                )
                if target["selection_status"] == UNKNOWN and status != "error":
                    status, message = UNKNOWN, "inspection workpiece identity is unresolved"
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
                    name=name,
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
                _dimensional_finding(
                    name,
                    workpiece,
                    f"{name}:{requirement}",
                    status,
                    nums,
                    cite,
                    f"{name} {requirement}: {message}.",
                )
            )
    return result


def _shared_finding(bundle, setup, op, target, route):
    from prechips.material_routes import MaterialGraph

    name = target["identity"]["feature_owner"]
    requirement = target["identity"]["requirement"]
    feature = record(bundle.feature_definitions.get(name))
    status, message, nums = requirement_check(bundle, name, requirement, op, setup=setup)
    nums.update(target)
    if feature.get("kind") == UNKNOWN and status != "error":
        status, message = UNKNOWN, "inspection feature applicability is unresolved"
    scope = record(op.get("inspection_scope"))
    positions = {f"{s['id']}:{o['op']}": index for index, (s, o) in enumerate(route)}
    endpoints = [scope.get(key) for key in ("after", "before")]
    scope_status, scope_message = "pass", ""
    if not all(isinstance(value, str) and value != UNKNOWN for value in endpoints):
        scope_status, scope_message = UNKNOWN, "shared inspection scope is unresolved"
    elif (
        any(value not in positions for value in endpoints)
        or not positions[endpoints[0]] < positions[target["op"]] < positions[endpoints[1]]
    ):
        scope_status, scope_message = "error", "shared inspection timing violates its scope"
    proofs = []
    if scope_status == "pass":
        graph = MaterialGraph(bundle.plan)
        for member in target["covered_workpieces"]:
            receivers = [
                current
                for current in bundle.plan["setups"]
                if member in (graph.members(current["id"]) or ())
            ]
            proof = (
                inspection_preservation_evidence(
                    bundle, receivers[-1], op, name, requirement, member
                )
                if receivers
                else {"status": UNKNOWN, "reasons": [], "proof": {}}
            )
            proofs.append({"workpiece_id": member, **proof})
        worst = max(proofs, key=lambda row: _SEVERITY[row["status"]], default=None)
        if worst is None or worst["status"] != "pass":
            scope_status = worst["status"] if worst else UNKNOWN
            scope_message = (
                "a later operation changes the inspected dimensional region"
                if scope_status == "error"
                else "requirement-specific native inspection preservation is unresolved"
            )
    nums.update(inspection_scope=op.get("inspection_scope", UNKNOWN), preservation=proofs)
    if _SEVERITY[scope_status] > _SEVERITY[status]:
        status, message = scope_status, scope_message
    others = []
    for other_setup, other in operations(bundle, name):
        if other is op or go_no_go_pair(other, name, requirement) is None:
            continue
        other_status, other_message, row = requirement_check(
            bundle, name, requirement, other, setup=other_setup
        )
        row.update(
            op=f"{other_setup['id']}:{other['op']}", status=other_status, message=other_message
        )
        others.append(row)
        if _SEVERITY[other_status] > _SEVERITY[status]:
            status, message = other_status, f"{row['op']}: {other_message}"
    if others:
        nums["other_go_no_go"] = others
    nominal_error = _nominal_band_error(feature, requirement)
    if nominal_error:
        nums.update(nominal_error)
        status, message = "error", "exported nominal is outside the requirement band"
    return Finding(
        "inspection",
        target["subject"],
        status,
        nums,
        [
            "PLAN.md §4.1 inspection",
            *(source_cite(feature) or ["features requirement manifest"]),
            "native requirement-specific material preservation",
            "inventory gauge range/resolution/verification",
        ],
        f"{name} {requirement}: {message}.",
    )


def _manual_findings(bundle, selected, route, members):
    from prechips.material_routes import MaterialGraph

    graph = MaterialGraph(bundle.plan) if registered_workpieces(bundle) else None
    result = []
    for requirement, relationship in record(bundle.features.get("acceptance")).items():
        relationship = record(relationship)
        participants = relationship.get("features", [])
        contract = relationship.get("contract", UNKNOWN)
        for member in members:
            candidates = [
                (index, setup, op, target)
                for index, setup, op, target in selected
                if target["kind"] == "manual"
                and target["identity"]["requirement"] == requirement
                and (
                    target["identity"]["workpiece"] == member
                    or target["selection_status"] == UNKNOWN
                    and (graph is None or member in (graph.members(setup["id"]) or ()))
                )
            ]
            last_change = max(
                (
                    index
                    for index, (setup, op) in enumerate(route)
                    if op.get("do") not in {"inspect", "spot", "release", "scribe"}
                    and any(name in participants for name in op_features(op))
                    and (graph is None or member in (graph.members(setup["id"]) or ()))
                ),
                default=-1,
            )
            subject = f"part:{requirement}"
            if member is not None:
                subject = f"{member}/{subject}"
            nums = {
                "identity": {
                    "workpiece": member,
                    "feature_owner": None,
                    "requirement": requirement,
                },
                "requirement": requirement,
                "kind": "manual",
                "contract": contract,
                "participants": participants,
                "shared_check_id": None,
                "covered_workpieces": [],
                "evaluation": "inspection_plan",
                "part_result": "not_recorded",
            }
            if not candidates:
                status, message = "error", "no requirement-keyed manual inspection check"
                if any(op.get("checks") == UNKNOWN for _, op in route):
                    status, message = UNKNOWN, "inspection checks are explicitly unknown"
            else:
                index, setup, op, target = candidates[-1]
                status, message, capability = requirement_check(
                    bundle, None, requirement, op, setup=setup, workpiece=member
                )
                nums.update(capability)
                nums.update(target)
                if index < last_change:
                    status, message = (
                        "error",
                        "manual inspection precedes later work on its participants",
                    )
                elif target["selection_status"] == UNKNOWN and status != "error":
                    status, message = UNKNOWN, "inspection workpiece identity is unresolved"
            result.append(
                Finding(
                    "inspection",
                    subject,
                    status,
                    nums,
                    [
                        "PLAN.md §4.1 inspection",
                        f"features.acceptance.{requirement}",
                        *_citations(record(contract).get("cite")),
                        "inventory comparator identity/presence/verification",
                    ],
                    f"{requirement}: {message}.",
                )
            )
    return result


def evaluate(bundle):
    route = operations(bundle)
    selected = [
        (index, setup, op, target)
        for index, (setup, op) in enumerate(route)
        for target in op_check_targets(bundle, setup, op)
    ]
    shared_coverage = set()
    result = []
    for _, setup, op, target in selected:
        if target["kind"] != "dimensional" or target["shared_check_id"] is None:
            continue
        result.append(_shared_finding(bundle, setup, op, target, route))
        shared_coverage.update(
            (member, target["identity"]["feature_owner"], target["identity"]["requirement"])
            for member in target["covered_workpieces"]
        )
    registered = bundle.plan.get("workpieces")
    members = tuple(registered) if isinstance(registered, dict) and registered else (None,)
    for member in members:
        result.extend(
            _dimensional_findings(bundle, workpiece=member, shared_coverage=shared_coverage)
        )
    result.extend(_manual_findings(bundle, selected, route, members))
    for setup, op in route:
        if "process_holds" in op:
            result.append(process_holds(bundle, setup, op))
    return result
