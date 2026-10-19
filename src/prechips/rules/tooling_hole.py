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
an untrusted, unmeasured-on-debt or non-cylinder pin is unknown. Each pin also reports,
for information only, how far the work may turn on it about every other locating pin of
the setup (``clocking``): its largest diametral clearance over the distance between the
two axes, and the most that turn moves a point of the entering stock's bounding box. The
kernel's separate geometric locator proof (``thin_wall_under_clamp``) still checks the
drawn pin in the cut bore. The hole earns no drawing coverage or finishing credit
(``process_features``).
"""

from prechips.findings import Finding
from prechips.measurements import record_trusted
from prechips.material_routes import feature_material_status, setup_lineage
from prechips.process_features import label, makers, process_of
from prechips.rules._envelope import measurement_item
from prechips.rules.resolution import UNKNOWN, number, op_features, record, same_length

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
    """``(where, item, pose)`` of the hold's fixture (``hold.pose``) and each clamp member
    (its own ``pose``); a pose is ``None`` when undeclared."""
    hold = record(hold)
    references = [("hold.fixture", hold.get("fixture", UNKNOWN), hold.get("pose"))]
    clamps = hold.get("clamps", [])
    for index, clamp in enumerate(clamps if isinstance(clamps, list) else [], start=1):
        clamp = record(clamp)
        references.append((f"hold.clamps[{index}]", clamp.get("ref", UNKNOWN), clamp.get("pose")))
    for where, reference, pose in references:
        if not isinstance(reference, str) or reference == UNKNOWN:
            continue
        item = measurement_item(bundle, "fixtures", reference)
        if item:
            yield f"{where} {reference}", item, pose if isinstance(pose, dict) else None


def _solids(bundle, setup):
    """``(owner, solid, pose)`` of every drawn solid the setup's hold places that declares
    ``locates``."""
    for owner, item, pose in _items(bundle, setup.get("hold")):
        solids = record(item).get("solids", [])
        for solid in solids if isinstance(solids, list) else []:
            solid = record(solid)
            locates = solid.get("locates")
            if isinstance(locates, str) and locates.strip() and solid.get("void") is not True:
                yield owner, solid, pose


def _locators(bundle, setup, holes):
    """hole -> [(owner, solid)] of the setup's drawn solids whose ``locates`` names it."""
    found = {}
    for owner, solid, _ in _solids(bundle, setup):
        if solid["locates"] in holes:
            found.setdefault(solid["locates"], []).append((owner, solid))
    return found


def _vector(value):
    return isinstance(value, list) and len(value) == 3 and all(map(number, value))


def _unit(vector):
    length = sum(v * v for v in vector) ** 0.5
    return [v / length for v in vector] if length > 1e-9 else None


def _cross(a, b):
    return [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]]


def _posed(pose, point, direction=False):
    """A fixture-local point (mm), or with ``direction`` a vector, in the setup frame
    through ``pose``, else None."""
    pose = record(pose)
    origin, x, z = (pose.get(key) for key in ("origin_mm", "x", "z"))
    if not all(_vector(v) for v in (origin, x, z, point)):
        return None
    y = _cross(z, x)
    base = [0.0, 0.0, 0.0] if direction else origin
    return [base[i] + x[i] * point[0] + y[i] * point[1] + z[i] * point[2] for i in range(3)]


def _across(point, base, axis):
    """Distance from ``point`` to the line through ``base`` along unit ``axis``."""
    offset = [p - b for p, b in zip(point, base, strict=True)]
    along = sum(o * a for o, a in zip(offset, axis, strict=True))
    return sum((o - along * a) ** 2 for o, a in zip(offset, axis, strict=True)) ** 0.5


def _hole_line(bundle, setup, name):
    """(setup-frame mouth point, unit axis) of tooling hole ``name``, else None."""
    from prechips.rules.coordinates import frame_point
    from prechips.rules.geometry_common import prepared_job

    feature = bundle.plan["process_features"][name]
    scale = _SCALE.get(bundle.features.get("units", UNKNOWN))
    at, axis = feature.get("at"), feature.get("axis")
    frame = next(
        (row["frame"] for row in prepared_job(bundle)["setups"] if row["id"] == setup["id"]),
        UNKNOWN,
    )
    if scale is None or not (_vector(at) and _vector(axis)) or not isinstance(frame, dict):
        return None
    mouth = frame_point([v * scale for v in at], frame)
    tip = frame_point([(a + d) * scale for a, d in zip(at, axis, strict=True)], frame)
    if not (_vector(mouth) and _vector(tip)):
        return None
    direction = _unit([t - m for t, m in zip(tip, mouth, strict=True)])
    return (mouth, direction) if direction else None


def _clocking(bundle, setup, name, fit, detail):
    """How far the work may turn on the pin in ``name`` about each other locating pin of the
    setup: the hole's largest diametral clearance over the distance between the two axes
    (``angle_rad``), and the most that turn moves a point of the entering stock's bounding
    box (``max_shift_mm``). Informational: it never changes the finding's status."""
    line = _hole_line(bundle, setup, name)
    clearance = fit["clearance_mm"]
    largest = clearance[1] if isinstance(clearance, list) else UNKNOWN
    box = detail.get("stock_bbox_mm")
    corners = (
        [[box[i], box[j + 1], box[k + 2]] for i in (0, 3) for j in (0, 3) for k in (0, 3)]
        if isinstance(box, list) and len(box) == 6 and all(map(number, box))
        else None
    )
    rows = []
    for owner, solid, pose in _solids(bundle, setup):
        if solid["locates"] == name or solid.get("shape") != "cylinder":
            continue
        row = {"about": f"{owner} solid {solid.get('name', UNKNOWN)}", "locates": solid["locates"]}
        pivot = _posed(pose, solid.get("at_mm")) if pose is not None else None
        turned = _posed(pose, solid.get("axis"), direction=True) if pose is not None else None
        turned = _unit(turned) if turned is not None else None
        # Only a pivot pin parallel to the hole turns the work in the hole's plane.
        parallel = (
            turned is not None
            and line is not None
            and abs(abs(sum(a * b for a, b in zip(turned, line[1], strict=True))) - 1.0) <= 1e-6
        )
        if turned is not None and line is not None and not parallel:
            row["reason"] = "its axis is not parallel to the hole's, so the turn is unknown"
        distance = _across(pivot, *line) if pivot is not None and parallel else None
        row["distance_mm"] = distance if distance is not None else UNKNOWN
        angle = (
            max(largest, 0.0) / distance
            if number(largest) and distance is not None and distance > 1e-6
            else UNKNOWN
        )
        row["angle_rad"] = angle
        row["max_shift_mm"] = (
            angle * max(_across(corner, pivot, line[1]) for corner in corners)
            if number(angle) and corners is not None
            else UNKNOWN
        )
        rows.append(row)
    return rows


def _sizing_action(bundle, name):
    """The action that sizes tooling hole ``name`` to its band: ``ream`` when any op reams
    it, else ``drill``."""
    actions = {
        op.get("do")
        for setup in bundle.plan["setups"]
        for op in setup.get("ops", [])
        if op.get("feature") == name
    }
    return "ream" if "ream" in actions else "drill"


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


def _evaluate(bundle, setup, name, ops, pins, state, detail):
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
        candidates = makers(bundle, setup, name)
        material = [
            (other, op, feature_material_status(bundle.plan, setup["id"], other["id"], name, bundle))
            for other, op in candidates
        ]
        before = [(other, op) for other, op, status in material if status is True]
        unresolved = [f"{other['id']} op {op['op']}" for other, op, status in material if status is None]
        if unresolved:
            numbers["unresolved_makers"] = unresolved
            unknown.append(f"whether drilling of {name} survived the stock partition is unresolved")
        lineage = setup_lineage(bundle.plan, setup["id"])
        routed = all(
            "stock_in" in other for other in bundle.plan["setups"] if other["id"] in lineage
        )
        numbers["made_by"] = [f"{other['id']} op {op['op']}" for other, op in before]
        if not before and not unresolved:
            (errors if routed else unknown).append(
                f"no earlier setup in its stock lineage drills {name}"
                if routed
                else f"a setup in the stock lineage declares no stock_in, so whether {name} "
                "is drilled is unresolved"
            )
        elif before and entry == "undrilled":
            errors.append(f"{name} is not drilled in the stock entering this setup")
        # The fit is judged against the band, so the op that sizes it (the ream when the
        # hole has one, else the drill, as ``sizing`` picks) must already have run.
        sizing = _sizing_action(bundle, name)
        numbers["sized_by"] = [
            f"{other['id']} op {op['op']}" for other, op in before if op.get("do") == sizing
        ]
        if before and not numbers["sized_by"]:
            later = [
                f"{other['id']} op {op['op']}"
                for other in bundle.plan["setups"]
                for op in other.get("ops", [])
                if op.get("feature") == name
                and op.get("do") == sizing
                and (other, op) not in before
            ]
            why = (
                f"{name} is not yet sized to its band when this setup locates on it: its "
                f"{sizing} " + (f"runs later ({', '.join(later)})" if later else "never runs")
            )
            (errors if routed and not unresolved else unknown).append(why)
        numbers["locators"] = []
        for owner, solid in pins:
            status, fit, why = _fit(bundle, name, owner, solid)
            fit["clocking"] = _clocking(bundle, setup, name, fit, detail)
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
            # Only an inspect op names a list, and the loader keeps process features out
            # of one, so this matches exactly the op whose one feature is the hole.
            for name in op_features(op):
                if name in holes:
                    worked.setdefault(name, []).append(op)
        for name in sorted(set(pins) | set(worked)):
            detail = record(setup_facts.get(setup["id"]))
            if facts.get("status") != "ok":
                state = {
                    "state": UNKNOWN,
                    "reason": facts.get("reason", "FreeCAD geometry facts are unavailable"),
                }
            else:
                state = record(record(detail.get("tooling_holes")).get(name)) or {
                    "state": UNKNOWN,
                    "reason": detail.get("stock_reason")
                    or f"the kernel did not classify {name} on this setup's entry stock",
                }
            status, numbers, why = _evaluate(
                bundle, setup, name, worked.get(name, []), pins.get(name, []), state, detail
            )
            subject = f"{setup['id']}:{name}"
            findings.append(
                Finding("tooling_hole", subject, status, numbers, [_CITE], f"{subject}: {why}.")
            )
    return findings
