"""B-rep entry-to-floor depth; beyond flute needs OAL and proven holder clearance."""

from prechips.findings import Finding
from prechips.rules.geometry_common import fact_reason, op_contexts
from prechips.rules.resolution import number, same_length


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
        values = {
            "reach_depth_mm": depth,
            "flute_len_mm": flute,
            "oal_mm": oal,
            "projection_mm": inputs.get("projection_mm", "unknown"),
            "holder_wall_hits": hits,
        }
        holder_known = all(
            number(inputs.get(key))
            for key in ("holder_radius_mm", "holder_gauge_len_mm", "projection_mm")
        )
        status, message = (
            "unknown",
            fact_reason(
                detail,
                ("reach_depth_mm", "holder_wall_hits"),
                "entry-to-floor depth or holder wall clearance is unresolved",
            ),
        )
        if number(depth) and depth >= 0:
            if depth <= flute or same_length(depth, flute):
                status, message = "pass", "entry-to-floor depth is within the selected flute length"
            elif number(oal) and depth > oal and not same_length(depth, oal):
                status, message = "error", "entry-to-floor depth exceeds the selected tool OAL"
            elif holder_known and number(hits) and hits > 0:
                status, message = (
                    "error",
                    "depth exceeds flute length and the holder intersects walls",
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
                    "clear of walls",
                )
        rows.append(Finding("reach", subject, status, values, cite, f"{subject}: {message}."))
    return rows
