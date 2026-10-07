"""B-rep entry-to-floor depth on the stock the op meets; beyond the flute it needs OAL and
the holder clear of that stock, and at any depth the shank past the flutes clear of the
stock the op's own cut leaves behind them.

Turning ops: the depth is the wall beside the insert nose, the "flute" the radial
span of the cutting edge (or declared reach) and the "OAL" the nose-to-toolpost-body
projection; holder clearance is the shank and toolpost body clear of remaining walls.
"""

from prechips.findings import Finding
from prechips.rules.geometry_common import TURNING, TURNING_HOLDER_KEYS, fact_reason, op_contexts
from prechips.rules.resolution import number, same_length

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
    an interference and ``unknown`` is unmeasured. No such stock: no entry."""
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
        obstacle = "stock under the holder"
        if number(top):
            obstacle += f" at Z{_mm(top)}"
        rows.append({"part": "holder face", "obstacle": obstacle, "mm": gap})
    return rows


def evaluate(bundle):
    rows = []
    for setup, op, _, detail, inputs, cite, blocked in op_contexts(
        bundle, "reach", ("flute_len_mm",)
    ):
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
        rows.append(Finding("reach", subject, status, values, cite, f"{subject}: {message}."))
    return rows
