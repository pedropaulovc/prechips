"""A tooling hole a setup works or locates on is there, and its locating pin fits it.

Always required (findings.ALWAYS_REQUIRED) wherever it applies: one finding per setup and
plan ``process_features`` ``tooling_hole`` the setup either works (an op names it) or
locates on (a drawn fixture or clamp solid whose ``locates`` names it). Setups that do
neither emit nothing, so plans without tooling holes are unchanged.

The kernel classifies each tooling hole on the stock entering the setup
(``tooling_holes``): ``undrilled``, ``present``, ``partial``, ``gone`` or unknown. A setup
that names a hole a waste cut has removed (``gone``) is an error, whether an op or a pin
names it; a pin in a hole that is still ``undrilled``, or that no earlier setup of its
stock lineage drills, is an error too. A ``partial`` hole, an unknown state, an unrouted
lineage or an unavailable kernel is unknown.

A locating pin's fit is judged from the hole's ``dia`` band and the pin solid's own trusted
``dia_mm``: the clearance range is ``[lo - pin, hi - pin]`` mm. A pin larger than the hole's
smallest size is an error (it does not enter every hole the band allows); an unknown band,
an untrusted, unmeasured-on-debt or non-cylinder pin is unknown. The kernel's separate
geometric locator proof (``thin_wall_under_clamp``) still checks the drawn pin in the cut
bore. The hole earns no drawing coverage or finishing credit (``process_features``).
"""

from prechips.findings import Finding
from prechips.measurements import record_trusted
from prechips.model import setup_lineage
from prechips.process_features import label, makers, process_of
from prechips.rules._envelope import measurement_item
from prechips.rules.resolution import UNKNOWN, number, record, same_length

_CITE = "PLAN.md §4.1 plan.process_features tooling_hole: locating holes in the work's waste"
_SCALE = {"mm": 1.0, "in": 25.4}


def _holes(bundle):
    """Plan tooling-hole names."""
    return {
        name
        for name, definition in bundle.feature_definitions.items()
        if record(process_of(definition)).get("kind") == "tooling_hole"
    }


def _items(bundle, hold):
    """``(where, item)`` of the hold's fixture and each clamp member."""
    hold = record(hold)
    references = [("hold.fixture", hold.get("fixture", UNKNOWN))]
    clamps = hold.get("clamps", [])
    for index, clamp in enumerate(clamps if isinstance(clamps, list) else [], start=1):
        references.append((f"hold.clamps[{index}]", record(clamp).get("ref", UNKNOWN)))
    for where, reference in references:
        if not isinstance(reference, str) or reference == UNKNOWN:
            continue
        item = measurement_item(bundle, "fixtures", reference)
        if item:
            yield f"{where} {reference}", item


def _locators(bundle, setup, holes):
    """hole -> [(owner, solid)] of the setup's drawn solids whose ``locates`` names it."""
    found = {}
    for owner, item in _items(bundle, setup.get("hold")):
        solids = record(item).get("solids", [])
        for solid in solids if isinstance(solids, list) else []:
            solid = record(solid)
            if solid.get("locates") in holes and solid.get("void") is not True:
                found.setdefault(solid["locates"], []).append((owner, solid))
    return found


def _fit(bundle, name, owner, solid):
    """(status, numbers, why) of one pin in tooling hole ``name``."""
    band = bundle.feature_definitions[name].get("dia", UNKNOWN)
    scale = _SCALE.get(bundle.features.get("units", UNKNOWN))
    pin = solid.get("dia_mm", UNKNOWN)
    pin_name = f"{owner} solid {solid.get('name', UNKNOWN)}"
    numbers = {"pin": pin_name, "pin_dia_mm": pin, "clearance_mm": UNKNOWN}
    known = isinstance(band, list) and all(map(number, band)) and scale is not None
    numbers["hole_dia_mm"] = [v * scale for v in band] if known else UNKNOWN
    trusted, why = record_trusted(solid, require_measured=False)
    if solid.get("shape") != "cylinder":
        return "unknown", numbers, f"{pin_name} is no cylinder, so its fit is unknown"
    if not trusted:
        return "unknown", numbers, f"{pin_name} size is not accepted: {why}"
    if not (number(pin) and pin > 0):
        return "unknown", numbers, f"{pin_name} dia_mm is unknown"
    if not known:
        return "unknown", numbers, f"the {name} dia band is unknown"
    low, high = numbers["hole_dia_mm"]
    numbers["clearance_mm"] = [low - pin, high - pin]
    if pin > low and not same_length(pin, low):
        return (
            "error",
            numbers,
            f"the Ø{pin:g} {pin_name} is larger than {name}'s Ø{low:g} minimum",
        )
    return (
        "pass",
        numbers,
        f"{pin_name} fits {name} with {low - pin:.4g} to {high - pin:.4g} mm clearance",
    )


def _evaluate(bundle, setup, name, ops, pins, state):
    numbers = {
        "process_feature": label(name),
        "ops": [f"{setup['id']}:{op['op']}" for op in ops],
        "entry_state": state.get("state", UNKNOWN),
    }
    errors, unknown, passed = [], [], []
    entry = numbers["entry_state"]
    if entry == "gone":
        errors.append(f"{name} is gone: an earlier waste cut removed it, yet this setup names it")
    elif entry == "partial":
        unknown.append(f"{name} is only partly in the stock entering this setup")
    elif entry == UNKNOWN:
        unknown.append(state.get("reason") or f"whether the stock still holds {name} is unknown")
    if pins:
        before = makers(bundle, setup, name)
        lineage = setup_lineage(bundle.plan, setup["id"])
        routed = all(
            "stock_in" in other for other in bundle.plan["setups"] if other["id"] in lineage
        )
        numbers["made_by"] = [f"{other['id']} op {op['op']}" for other, op in before]
        if not before:
            (errors if routed else unknown).append(
                f"no earlier setup in its stock lineage drills {name}"
                if routed
                else f"a setup in the stock lineage declares no stock_in, so whether {name} "
                "is drilled is unresolved"
            )
        elif entry == "undrilled":
            errors.append(f"{name} is not drilled in the stock entering this setup")
        numbers["locators"] = []
        for owner, solid in pins:
            status, fit, why = _fit(bundle, name, owner, solid)
            numbers["locators"].append({**fit, "status": status})
            {"error": errors, "unknown": unknown, "pass": passed}[status].append(why)
    if errors:
        return "error", numbers, "; ".join(errors)
    if unknown:
        return "unknown", numbers, "; ".join(unknown)
    if pins:
        return "pass", numbers, "; ".join(passed)
    return "pass", numbers, f"the stock entering this setup still has {name} where its ops cut"


def evaluate(bundle):
    holes = _holes(bundle)
    if not holes:
        return []
    from prechips.kernel import run_geometry

    facts = run_geometry(bundle)
    setup_facts = record(facts.get("setups"))
    findings = []
    for setup in bundle.plan["setups"]:
        pins = _locators(bundle, setup, holes)
        worked = {}
        for op in setup.get("ops", []):
            if op.get("feature") in holes:
                worked.setdefault(op["feature"], []).append(op)
        for name in sorted(set(pins) | set(worked)):
            if facts.get("status") != "ok":
                state = {
                    "state": UNKNOWN,
                    "reason": facts.get("reason", "FreeCAD geometry facts are unavailable"),
                }
            else:
                detail = record(setup_facts.get(setup["id"]))
                state = record(record(detail.get("tooling_holes")).get(name)) or {
                    "state": UNKNOWN,
                    "reason": detail.get("stock_reason")
                    or f"the kernel did not classify {name} on this setup's entry stock",
                }
            status, numbers, why = _evaluate(
                bundle, setup, name, worked.get(name, []), pins.get(name, []), state
            )
            subject = f"{setup['id']}:{name}"
            findings.append(
                Finding("tooling_hole", subject, status, numbers, [_CITE], f"{subject}: {why}.")
            )
    return findings
