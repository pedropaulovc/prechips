"""Declared exposed finished diameter and selected support; no inferred shop limit."""

from ..findings import Finding
from .resolution import UNKNOWN, _citations, number, record, resolve, uncertain
from .turned_profile import exposed_profile

SUPPORT_KINDS = {
    "tailstock",
    "tailstock_centre",
    "tailstock_center",
    "steady_rest",
}


def held_diameter_source(setup):
    return (
        "plan.setups.stock_state.od_mm"
        if setup.get("stock_state") == UNKNOWN or "od_mm" in record(setup.get("stock_state"))
        else "plan.stock.dia_mm"
    )


def held_diameter(bundle, setup):
    if setup.get("stock_state") == UNKNOWN:
        return UNKNOWN
    state = record(setup.get("stock_state"))
    if "od_mm" in state:
        value = state["od_mm"]
    else:
        stock = record(bundle.plan.get("stock"))
        if stock.get("form_verify") in (True, UNKNOWN):
            return UNKNOWN
        value = stock.get("dia_mm")
    return value if number(value) and value > 0 else UNKNOWN


def support_state(bundle, setup):
    """Return pass for a selected verified support, unknown for unresolved debt.

    Only the selected machine can supply a machine-accessory identity. The M1
    resolver also searches other machines' accessories, so that fallback must
    not establish support for this setup.
    """
    hold = record(setup.get("hold"))
    declared = any(key in hold for key in ("support", "supports"))
    refs = set()
    unresolved = not declared
    for key in ("support", "supports"):
        if key not in hold:
            continue
        values = hold[key] if isinstance(hold[key], list) else [hold[key]]
        for value in values:
            reference = value.get("ref", UNKNOWN) if isinstance(value, dict) else value
            if reference in ("none", "not_applicable"):
                continue
            if not isinstance(reference, str) or reference in (UNKNOWN, ""):
                unresolved = True
            else:
                refs.add(reference)
    machine = resolve(bundle, "machines", setup.get("machine"))
    accessories = record(machine).get("standard_accessories", []) + record(machine).get(
        "included", []
    )
    evidence = []
    fixtures = record(bundle.inventory.get("fixtures"))
    for reference in sorted(refs):
        item = resolve(bundle, "fixtures", reference)
        if item is not None and item.get("kind") == "accessory":
            item = None
        if (
            item is None
            and reference in accessories
            and reference.partition("/")[0] not in fixtures
        ):
            item = {
                "kind": "accessory",
                "verify": machine is None or uncertain(machine),
                "source": "inventory selected machine accessories",
            }
        kind = record(item).get("kind", UNKNOWN)
        accessory_name = reference.lower().replace("-", "_")
        capable = kind in SUPPORT_KINDS or (
            kind in {"accessory", "dead_centre", "dead_center", "live_centre", "live_center"}
            and ("tailstock" in accessory_name.split("_") or accessory_name == "steady_rest")
        )
        status = (
            "unknown"
            if item is None or uncertain(item) or kind == UNKNOWN
            else "pass"
            if capable
            else "not_applicable"
        )
        evidence.append(
            {
                "reference": reference,
                "kind": kind,
                "status": status,
                "source": "inventory selected machine accessories"
                if kind == "accessory"
                else "inventory.fixtures",
            }
        )
        unresolved |= status == "unknown"
    if any(item["status"] == "pass" for item in evidence):
        return "pass", evidence
    return ("unknown" if unresolved else "not_applicable"), evidence


def evaluate(bundle):
    findings = []
    for setup in bundle.plan["setups"]:
        machine = resolve(bundle, "machines", setup.get("machine"))
        kind = record(machine).get("kind", UNKNOWN)
        held = held_diameter(bundle, setup)
        geometry = exposed_profile(bundle, setup)
        segments = geometry["segments"]
        diameter = (
            min(segment["diameter_mm"] for segment in segments) if geometry["complete"] else UNKNOWN
        )
        diameter_features = sorted(
            {
                name
                for segment in segments
                if number(diameter) and segment["diameter_mm"] == diameter
                for name in segment["features"]
            }
        )
        length = record(setup.get("hold")).get("stickout_mm", UNKNOWN)
        policy = record(bundle.policy.get("numbers"))
        ratio = policy.get("stickout_ld_max", UNKNOWN)
        citations = _citations(record(bundle.policy.get("numbers_cite")).get("stickout_ld_max"))
        verify = record(bundle.policy.get("numbers_verify")).get("stickout_ld_max", False)
        known_limit = number(ratio) and ratio > 0 and bool(citations) and verify is False
        limit = ratio * diameter if known_limit and number(diameter) else UNKNOWN
        support, support_evidence = support_state(bundle, setup)
        numbers = {
            "diameter_mm": diameter,
            "diameter_source": "features declared finished profile in exposed setup Z",
            "diameter_features": diameter_features,
            "held_diameter_mm": held,
            "held_diameter_source": held_diameter_source(setup),
            "exposed_z_mm": geometry["exposed_z_mm"],
            "segments": segments,
            "unresolved": sorted(set(geometry["unresolved"])),
            "stickout_mm": length,
            "stickout_ld_max": ratio,
            "unsupported_limit_mm": limit,
            "support_status": support,
            "supports": support_evidence,
        }
        if kind != "lathe":
            status = "unknown" if kind == UNKNOWN else "not_applicable"
            message = "machine kind is unresolved" if status == "unknown" else "not a lathe setup"
        elif not number(length) or length < 0 or not number(held):
            status, message = "unknown", "stick-out or held diameter is unresolved"
        elif length == 0 and (known_limit or support == "pass"):
            status, message = "pass", "there is no declared unsupported length"
        elif not number(diameter):
            status, message = (
                "unknown",
                "the finished diameter or geometry in the exposed span is unresolved",
            )
        elif support == "pass":
            status, message = (
                "pass",
                "a selected verified tailstock/steady support supplies the exception",
            )
        elif not known_limit:
            status, message = (
                "unknown",
                "the shop stick-out ratio needs a verified cited policy value",
            )
        elif length <= limit:
            status, message = "pass", "declared stick-out is within the unsupported shop limit"
        elif support == "unknown":
            status, message = (
                "unknown",
                "stick-out exceeds the unsupported limit; selected support is unresolved",
            )
        else:
            status, message = (
                "error",
                "stick-out exceeds the unsupported shop limit; "
                "add a listed tailstock/steady support",
            )
        findings.append(
            Finding(
                "stickout",
                setup["id"],
                status,
                numbers,
                [
                    "PLAN.md §4.1 stick-out (line 541)",
                    held_diameter_source(setup),
                    "plan.setups.hold.stickout_mm; "
                    "inventory selected support identity/verification",
                    "features declared finished diameters/z_mm/frame; "
                    "plan.setups.frame and stock_state.north_end_z/south_end_z "
                    "define the exposed span; 25.4 mm/in",
                    *[
                        f"features.features.{name}: defines exposed minimum diameter"
                        for name in diameter_features
                    ],
                    *geometry["cite"],
                    *citations,
                ],
                f"{setup['id']}: {message}.",
            )
        )
    return findings
