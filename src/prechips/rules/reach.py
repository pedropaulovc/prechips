"""B-rep entry-to-floor depth on the stock the op meets; beyond the flute it needs OAL and
the holder clear of that stock, and at any depth the shank past the flutes clear of the
stock the op's own cut leaves behind them.

Turning ops: the depth is the wall beside the insert nose, the "flute" the radial
span of the cutting edge (or declared reach) and the "OAL" the nose-to-toolpost-body
projection; holder clearance is the shank and toolpost body clear of remaining walls.

Mounted disks consume the shared finite kerf-coverage and assembly-clearance result;
neither axial flute depth nor diameter minus flange radius establishes their reach.
"""

import math

from prechips.findings import Finding
from prechips.rules.geometry_common import (
    TURNING,
    TURNING_HOLDER_KEYS,
    fact_reason,
    op_contexts,
    with_measurement_debts,
)
from prechips.rules.resolution import number, op_feature, record, same_length

# A radial gap this close to the cutter's own radius is the bore the op itself cuts.
OWN_BORE_MM = 0.01


def _mm(value):
    return f"{value:.3f}".rstrip("0").rstrip(".")


def _obstacle(gap, body, cutter):
    """Shop words for the stock nearest a tool part ``gap`` mm outside its ``body`` radius."""
    if not (number(gap) and number(body)):
        return "stock beside the tool"
    wall = gap + body
    if number(cutter) and abs(wall - cutter) <= OWN_BORE_MM:
        return f"the Ø{_mm(2 * cutter)} bore this op cuts"
    return f"stock {_mm(wall)} from the tool axis"


def _clearances(detail, inputs):
    """Each measured tool-part clearance as ``{part, obstacle, mm}``; a negative ``mm`` is
    an interference and ``unknown`` is unmeasured. No such stock: no entry. The holder
    face's entry carries the kernel Z (mm) of the stock under it as ``z_mm``, for the
    sheet to print as that surface's DRO Z."""
    cutter, shank = inputs.get("radius_mm"), inputs.get("shank_radius_mm")
    rows = []
    for key, part, body in (
        ("body_clear_mm", "tool body", cutter),
        # A cone has no single radius: its gap names no distance from the axis.
        ("seat_clear_mm", "seat cone", None),
        ("shank_clear_mm", "tool shank", shank),
    ):
        gap = detail.get(key, "not_applicable")
        if gap != "not_applicable":
            rows.append({"part": part, "obstacle": _obstacle(gap, body, cutter), "mm": gap})
    gap, top = detail.get("holder_clear_mm", "not_applicable"), detail.get("holder_clear_top_z_mm")
    if gap != "not_applicable":
        row = {"part": "holder face", "obstacle": "stock under the holder", "mm": gap}
        if number(top):
            row["z_mm"] = top
        rows.append(row)
    return rows


def _represented_hand_tap_reach(bundle, setup, op, facts, inputs, cite, blocked):
    """Qualified tip travel from a proved entry plane, not exact helical cut credit."""

    if op.get("do") != "hand_tap":
        return None
    feature = record(bundle.feature_definitions.get(op_feature(op)))
    if feature.get("kind") != "threaded_hole" or feature.get("representation") != "thread_envelope":
        return None
    from prechips.kernel import op_inputs
    from prechips.rules.coverage import represented_thread_envelope

    if blocked is not None and (blocked.status == "error" or facts.get("status") != "ok"):
        return blocked
    subject = f"{setup['id']}:{op['op']}"
    request = record(op_inputs(bundle, setup, op).get("manual_thread"))
    material = record(record(record(facts.get("ops")).get(subject)).get("manual_thread"))
    lengths = ("tip_depth_mm", "lead_mm", "formed_depth_mm", "flute_len_mm")
    depth = record(request.get("region")).get("depth_mm", "unknown")
    values = {
        "model": "qualified_hand_tap_reach_v1",
        "evaluation": "represented_geometry",
        "helical_geometry": "unmodeled",
        "tool": request.get("tool", "unknown"),
        "workpiece_id": request.get("workpiece_id"),
        "threaded_span_mm": depth,
        **{key: request.get(key, "unknown") for key in lengths},
    }

    def result(status, message):
        return with_measurement_debts(
            Finding("reach", subject, status, values, cite, f"{subject}: {message}."),
            inputs.get("measurement_debts", []),
        )

    if request.get("status") == "error":
        return result("error", "; ".join(request.get("reasons", [])) or "tap reach is invalid")
    if request.get("model") != "bounded_thread_envelope_v1" or request.get("status") != "ready":
        return result(
            "unknown",
            "the selected tap, threaded span, lead or cutting reach is unresolved",
        )
    tip, lead, formed, flute = (values[key] for key in lengths)
    if not all(
        number(value) and math.isfinite(value) for value in (tip, lead, formed, flute, depth)
    ):
        return result(
            "unknown",
            "qualified tap reach needs finite tip, lead, cutting and span lengths",
        )
    if min(tip, formed, flute, depth) <= 0 or lead < 0:
        return result("error", "tap tip travel, formed span and cutting length must be positive")
    if not same_length(formed, tip - lead):
        return result("error", "formed thread reach does not equal tip travel minus qualified lead")
    if (formed < depth and not same_length(formed, depth)) or (
        tip < depth + lead and not same_length(tip, depth + lead)
    ):
        return result(
            "error",
            "tap tip travel does not form the complete span beyond its qualified lead",
        )
    if tip > flute and not same_length(tip, flute):
        return result("error", "required tap tip travel exceeds its qualified cutting length")
    indices, evidence = represented_thread_envelope(bundle, facts, setup, op)
    values["represented_thread_envelope"] = evidence
    matching = (
        material.get("model") == "bounded_thread_envelope_v1"
        and material.get("producer") == subject
        and material.get("feature") == request.get("feature")
        and material.get("workpiece_id") == request.get("workpiece_id")
        and material.get("region") == request.get("region")
        and material.get("diameter_mm") == request.get("diameter_mm")
        and "registration" in evidence
        and material.get("registration") == evidence["registration"]
        and "partition_path" in evidence
        and material.get("partition_path") == evidence["partition_path"]
        and all(material.get(key) == request.get(key) for key in lengths)
    )
    if matching and material.get("status") == "error":
        return result(
            "error", "; ".join(material.get("reasons", [])) or "native tap reach proof is invalid"
        )
    if not indices or evidence.get("status") != "pass":
        reasons = evidence.get("reasons", [])
        return result(
            "unknown", "; ".join(reasons) or "native represented-thread reach is unproven"
        )
    if not matching:
        return result(
            "unknown",
            "native tap tip, lead and cutting reach do not match current qualification",
        )
    if inputs.get("measurement_debts"):
        return result("unknown", "current tool or stock measurement requirements remain unresolved")
    # The material proof establishes the actual global stock entry plane at
    # this feature mouth. With all tip travel inside the cutting length, the
    # noncutting shank past the flutes never reaches that plane.
    values["shank_reach"] = "outside_stock_entry_plane"
    return result(
        "pass",
        "qualified tap cutting length covers tip travel and lead for the represented span; "
        "the shank stays outside the proved stock entry plane, "
        "without claiming exact helical geometry",
    )


def evaluate(bundle):
    rows = []
    for setup, op, facts, detail, inputs, cite, blocked in op_contexts(
        bundle, "reach", ("flute_len_mm",)
    ):
        represented = _represented_hand_tap_reach(bundle, setup, op, facts, inputs, cite, blocked)
        if represented is not None:
            rows.append(represented)
            continue
        if blocked:
            rows.append(blocked)
            continue
        subject = f"{setup['id']}:{op['op']}"
        depth = detail.get("reach_depth_mm", "unknown")
        flute, oal = inputs["flute_len_mm"], inputs.get("oal_mm", "unknown")
        hits = detail.get("holder_wall_hits", "unknown")
        turning = inputs.get("approach") == TURNING
        values = {
            "reach_depth_mm": depth,
            "flute_len_mm": flute,
            "oal_mm": oal,
            "projection_mm": inputs.get("projection_mm", "unknown"),
            "holder_wall_hits": hits,
        }
        if "reach_top_z_mm" in detail:
            # The Z of the highest retained stock the reach is measured from.
            values["reach_top_z_mm"] = detail["reach_top_z_mm"]
        shank = "not_applicable" if turning else detail.get("shank_hits", "unknown")
        if not turning:
            radius = inputs.get("shank_radius_mm")
            values["shank_dia_mm"] = 2 * radius if number(radius) else "unknown"
            values["shank_from_mm"] = inputs.get("shank_from_mm", "unknown")
            values["shank_hits"] = shank
            for key in ("body_clear_mm", "seat_clear_mm", "shank_clear_mm", "holder_clear_mm"):
                if key in detail:
                    values[key] = detail[key]
            values["clearances"] = _clearances(detail, inputs)
        holder_keys = (
            (*TURNING_HOLDER_KEYS, "projection_mm", "shank_width_mm", "head_len_mm")
            if turning
            else ("holder_radius_mm", "holder_gauge_len_mm", "projection_mm")
        )
        holder_known = all(number(inputs.get(key)) for key in holder_keys)
        status, message = (
            "unknown",
            fact_reason(
                detail,
                ("reach_depth_mm", "holder_wall_hits"),
                "entry-to-floor depth or holder wall clearance is unresolved",
            ),
        )
        if number(depth) and depth >= 0:
            within = depth <= flute or same_length(depth, flute)
            if number(oal) and depth > oal and not same_length(depth, oal):
                status, message = "error", "entry-to-floor depth exceeds the selected tool OAL"
            elif number(shank) and shank > 0:
                status, message = (
                    "error",
                    "the tool shank past its flutes meets the retained stock",
                )
            elif within and (turning or number(shank)):
                status, message = "pass", "entry-to-floor depth is within the selected flute length"
            elif not within and holder_known and number(hits) and hits > 0:
                status, message = (
                    "error",
                    "depth exceeds flute length and the holder intersects walls",
                )
            elif not turning and not number(shank):
                # An unresolved shank never passes, at any depth: a short spot still sinks
                # the shank beside a retained wall the cut never reaches.
                status, message = (
                    "unknown",
                    fact_reason(
                        detail,
                        ("shank_hits",),
                        "the shank past the flutes is unresolved against the retained stock",
                    ),
                )
            elif (
                number(oal)
                and (depth <= oal or same_length(depth, oal))
                and hits == 0
                and holder_known
            ):
                status, message = (
                    "pass",
                    "depth exceeds flute length but fits OAL with the holder cylinder "
                    "clear of walls"
                    if turning
                    else "depth exceeds flute length but fits OAL with the shank and holder "
                    "clear of the retained stock",
                )
        rows.append(
            with_measurement_debts(
                Finding("reach", subject, status, values, cite, f"{subject}: {message}."),
                inputs["measurement_debts"],
            )
        )
    return rows
