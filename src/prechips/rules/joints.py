"""Two-branch joints: worst-case cylindrical fit and the kernel's physical join verdict.

Both rules are always required (findings.ALWAYS_REQUIRED): an incompatible or unresolved
joint can never be waived by an absent shop-policy entry.
"""

from prechips.findings import Finding
from prechips.joint_features import describe, fit, label
from prechips.rules.resolution import UNKNOWN, _citations, record


def _assemblies(bundle):
    return [setup for setup in bundle.plan["setups"] if isinstance(setup.get("stock_in"), list)]


def evaluate_fit(bundle):
    rows = []
    features = bundle.plan.get("joint_features", {})
    for setup in _assemblies(bundle):
        joint = setup["joint"]
        if joint["kind"] != "cylindrical":
            continue
        sid = setup["id"]
        result = fit(bundle, setup)
        engagement = result["engagement"]
        numbers = {
            "socket": label(joint["socket"]),
            "spigot": label(joint["spigot"]),
            "fit": joint["fit"],
            "method": joint["method"],
            "band_mm": result["band_mm"],
            "guaranteed_mm": result["guaranteed_mm"],
            "engagement_mm": engagement["depth_mm"] if engagement else UNKNOWN,
            "engagement_dia_mm": engagement["diameter_mm"] if engagement else UNKNOWN,
            "violations": result["violations"],
            "missing": result["missing"],
        }
        cite = [
            "PLAN.md §4.1 joint_fit",
            f"plan.setups.{sid}.joint: fit, diametral band and process",
            *_citations(joint.get("cite")),
            *(
                citation
                for role in ("socket", "spigot")
                for citation in _citations(record(features.get(joint[role])).get("cite"))
            ),
        ]
        if result["missing"]:
            status = "unknown"
            message = f"joint geometry unknown ({', '.join(result['missing'])}); no union"
        elif result["violations"]:
            status = "error"
            message = f"{describe(result['violations'])}; no union"
        else:
            status = "pass"
            message = (
                f"worst-case {joint['fit']} lies within the declared {joint['fit']}_mm over "
                "the derived engagement"
            )
        cite = list(dict.fromkeys(cite))
        rows.append(Finding("joint_fit", sid, status, numbers, cite, f"{sid}: {message}."))
    return rows


def evaluate_assembly(bundle):
    from prechips.kernel import run_geometry
    from prechips.rules.geometry_common import provenance, unavailable

    assemblies = _assemblies(bundle)
    if not assemblies:
        return []
    facts = run_geometry(bundle)
    rows = []
    for setup in assemblies:
        sid = setup["id"]
        cite = [
            *provenance(bundle, "joint_assembly", setup),
            f"plan.setups.{sid}.joint: {setup['joint']['kind']} join",
            *_citations(setup["joint"].get("cite")),
        ]
        blocked = unavailable(bundle, "joint_assembly", sid, facts, cite)
        if blocked is not None:
            rows.append(blocked)
            continue
        detail = record(record(facts.get("setups")).get(sid))
        if detail.get("assembly_error"):
            status, message = "error", f"join refused: {detail['assembly_error']}"
        elif detail.get("stock_reason"):
            status, message = "unknown", f"joined stock unknown: {detail['stock_reason']}"
        elif "stock_bbox_mm" not in detail:
            status, message = "unknown", "the kernel derived no joined stock"
        else:
            status, message = (
                "pass",
                "prepared branches, physical fit and declared fill derive the joined stock",
            )
        numbers = {
            "joint": setup["joint"]["kind"],
            "stock_in": list(setup["stock_in"]),
            "completed_joint_features": detail.get("completed_joint_features", UNKNOWN),
        }
        rows.append(Finding("joint_assembly", sid, status, numbers, cite, f"{sid}: {message}."))
    return rows
