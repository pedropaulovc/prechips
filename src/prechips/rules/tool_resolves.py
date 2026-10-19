"""Resolve selected identities once, then check each cutting assembly.

A non-spindle saw cut uses a ``bandsaw`` blade on a mill, bench or bandsaw, or a
``hand_saw`` at a bench or manual station. A mill-mounted ``slitting_saw`` instead needs
an arbor assembly; its finite disk and mount are not modelled by the planar cut.
The cut is located by ``cut_plane`` or the scribed line it ``follows``. A coating
op has no tool: it names its process, an outside service or in-house consumables. A
shop-made item's make operation names a ``tools`` key and states its cutting data.
"""

from ..findings import Finding
from ..measurements import length_debt, length_fact, limits_fact
from ..thread_specs import match as thread_match
from .geometry_common import _AXIAL_LATHE_ACTIONS
from .resolution import (
    HAND_THREAD,
    MANUAL,
    SAW_MACHINES,
    SAW_OPS,
    SLITTING_SAW_MODEL_REASON,
    UNKNOWN,
    UNRESOLVED_SAW_MODEL_REASON,
    WORKHOLDING_CATEGORIES,
    coating_process,
    identity,
    length_mm,
    make_op_unknowns,
    make_ops,
    make_tool,
    named_item,
    named_references,
    number,
    operations,
    record,
    resolve,
    same_length,
    saw_station,
    select,
    setup_items,
    shop_made_item,
    slitting_saw,
    spindle_saw,
    uncertain,
)

SAW_MACHINE_KINDS = frozenset().union(*SAW_MACHINES.values())
SAW_TOOL_KINDS = frozenset(SAW_MACHINES)

# A cutter shank is ground to a tolerance class below its nominal size: a nominal collet
# accepts the ISO 286 h6 shaft band, upper deviation 0 and lower deviation -IT6. IT6 in
# micrometres by nominal size, "above" the previous bound "up to and including" this one, in
# mm (ISO 286-1:2010 Table 1). A size above the last bound has no IT6 here.
SHANK_FIT = "ISO 286 h6"
SHANK_FIT_CITE = "ISO 286-1:2010 Table 1 IT6"
_IT6_UM = (
    (3, 6),
    (6, 8),
    (10, 9),
    (18, 11),
    (30, 13),
    (50, 16),
    (80, 19),
    (120, 22),
    (180, 25),
    (250, 29),
    (315, 32),
    (400, 36),
    (500, 40),
)


def _h6_band(nominal):
    """``[low, nominal]`` in mm for an h6 shaft of ``nominal`` mm, or :data:`UNKNOWN` above
    the table. The low limit is rounded to the nanometre ``same_length`` compares at."""
    for upper, it6 in _IT6_UM:
        if nominal <= upper or same_length(nominal, upper):
            return [round(nominal - it6 / 1000, 6), nominal]
    return UNKNOWN


def _saw_assembly(bundle, subject, setup, op, tool, machine, machine_ref):
    nums = {
        "tool": op.get("tool", UNKNOWN),
        "holder": "not_applicable",
        "machine": machine_ref,
        "machine_kind": (machine or {}).get("kind", UNKNOWN),
        "tool_kind": (tool or {}).get("kind", UNKNOWN),
    }
    problems = []
    station = saw_station(bundle, setup, op)
    if spindle_saw(bundle, setup, op):
        model_reason = (
            SLITTING_SAW_MODEL_REASON if slitting_saw(bundle, op) else UNRESOLVED_SAW_MODEL_REASON
        )
        holder_ref = op.get("holder", UNKNOWN)
        holder = record(resolve(bundle, "holders", holder_ref))
        nums.update(
            holder=holder_ref,
            arbor=record(tool).get("arbor", UNKNOWN),
            arbor_fit=UNKNOWN,
            spindle_interface=record(record(machine).get("spindle")).get("taper", UNKNOWN),
            holder_interface=holder.get("taper", holder.get("standard", UNKNOWN)),
            model_reason=model_reason,
        )
        missing = [model_reason]
        debts = []
        category, reference, _ = select(bundle, op.get("tool"), "tools")
        for field, label in (("dia", "blade_diameter_mm"), ("kerf", "kerf_mm")):
            fact = length_fact(record(tool), field, require_measured=False)
            value = fact["value"] if fact["verified"] else UNKNOWN
            nums[label] = value
            if number(value) and value <= 0:
                problems.append(f"blade {field} must be positive")
            elif not number(value):
                missing.append(f"known, verified positive blade {field}")
            debt = length_debt(record(tool), field, category, reference)
            if debt is not None:
                debts.append(debt)
        if debts:
            nums["measurements"] = debts
        if not holder or uncertain(holder):
            missing.append("resolved, verified mounted arbor/holder")
        if machine and holder and not any(uncertain(item) for item in (machine, holder)):
            spindle_interface = nums["spindle_interface"]
            holder_interface = nums["holder_interface"]
            if (
                all(
                    isinstance(value, str) and value.strip() and value != UNKNOWN
                    for value in (spindle_interface, holder_interface)
                )
                and spindle_interface != holder_interface
            ):
                problems.append("holder interface does not match machine")
        if station == UNKNOWN:
            missing.append("resolved, verified slitting saw and mill")
        if station == "wrong_station":
            problems.append(
                f"tool kind {nums['tool_kind']} cannot run a saw cut"
                if nums["tool_kind"] not in SAW_TOOL_KINDS
                else f"a spindle-mounted slitting saw cuts only on a mill, not "
                f"a {nums['machine_kind']}"
            )
        return Finding(
            "tool_resolves",
            subject,
            "error" if problems else UNKNOWN,
            nums,
            [
                "inventory spindle, selected holder, blade dia and kerf",
                "docs/rules-tools.md: Shop-made tooling and saws",
            ],
            f"{subject}: " + "; ".join(problems or missing) + ".",
        )
    scribed_blade = nums["tool_kind"] == "bandsaw" and "follows" in op
    if station == "no_vertical_mode":
        problems.append(
            f"machine {machine_ref} declares no vertical saw_modes; a bandsaw blade follows a "
            "scribed line only in vertical mode"
        )
    if station == "wrong_station":
        for kind, accepted, label in (
            (nums["machine_kind"], SAW_MACHINE_KINDS, "machine"),
            (nums["tool_kind"], SAW_TOOL_KINDS, "tool"),
        ):
            if kind not in accepted and kind != UNKNOWN:
                problems.append(
                    f"{label} kind {kind} cannot run a saw cut "
                    f"(accepted: {', '.join(sorted(accepted))})"
                )
        pairs = SAW_MACHINES.get(nums["tool_kind"])
        if not problems and scribed_blade:
            problems.append(
                "a bandsaw blade follows a scribed line only on a bandsaw machine in vertical "
                f"mode, not a {nums['machine_kind']}"
            )
        if not problems:
            problems.append(
                f"a {nums['tool_kind']} cuts only on a {' or '.join(sorted(pairs))} machine, "
                f"not a {nums['machine_kind']}"
            )
    status = "error" if problems else "unknown" if station == "unknown" else "pass"
    unknown = status == "unknown"
    blade, place = (
        ("hand saw", "bench or manual station")
        if nums["tool_kind"] == "hand_saw"
        else ("bandsaw blade", "bandsaw with a declared vertical mode")
        if scribed_blade
        else ("bandsaw blade", "saw-capable machine")
    )
    message = (
        "; ".join(problems)
        if problems
        else f"saw assembly needs a resolved, verified {blade} and {place}"
        if unknown
        else f"{blade} on a {place}; no spindle, collet or holder applies"
    )
    return Finding(
        "tool_resolves",
        subject,
        status,
        nums,
        ["inventory machine kind and tool kind", "PLAN.md §4.1"],
        f"{subject}: {message}.",
    )


def _coating(subject, op, bundle):
    """A coating op's named process must resolve to a service or in-house consumables."""
    process = op.get("process", UNKNOWN)
    refs = process if isinstance(process, list) else [process]
    sources = {}
    for ref in refs:
        category, item = coating_process(bundle, ref)
        sources[ref] = "unlisted" if item is None else UNKNOWN if uncertain(item) else category
    unlisted = [ref for ref in refs if ref != UNKNOWN and sources[ref] == "unlisted"]
    unresolved = UNKNOWN in refs or any(source == UNKNOWN for source in sources.values())
    status = "error" if unlisted else "unknown" if unresolved else "pass"
    message = (
        f"coating process {', '.join(unlisted)} is not an inventory service or consumable"
        if unlisted
        else "coating names no process (outside service or in-house consumables)"
        if UNKNOWN in refs
        else "coating process is listed; presence or identity needs verification"
        if unresolved
        else "coating process resolves to "
        + ", ".join(
            f"{'outside service' if sources[ref] == 'services' else 'in-house consumables'} {ref}"
            for ref in refs
        )
    )
    return Finding(
        "tool_resolves",
        subject,
        status,
        {"process": refs, "sources": sources},
        ["inventory services/consumables", "PLAN.md §4.1 finishing route"],
        f"{subject}: {message}.",
    )


def _make_ops(bundle):
    """One finding per make operation (:func:`make_ops`) of each shop-made item a setup
    holds with: its ``tool`` must be a ``tools`` key the shop list has (:func:`make_tool`:
    no other category or machine accessory stands in) and trusts, and every fact its line
    prints known; anything else is never a pass."""
    findings, done = [], set()
    for setup in bundle.plan.get("setups") or []:
        for category, ref, *_ in setup_items(bundle, setup):
            if category not in WORKHOLDING_CATEGORIES or (category, ref) in done:
                continue
            done.add((category, ref))
            item = f"{category}.{ref}"
            ops = make_ops(shop_made_item(bundle, ref, category))
            for index, (solid, op) in enumerate(ops, 1):
                subject = f"{item} make op {index}"
                unknowns = make_op_unknowns(op)
                reference = record(op).get("tool", UNKNOWN)
                tool = None if "tool" in unknowns else make_tool(bundle, reference)
                if tool is not None and uncertain(tool):
                    unknowns.append("tool verification")
                unlisted = tool is None and "tool" not in unknowns
                status = "error" if unlisted else "unknown" if unknowns else "pass"
                reason = (
                    f"tool {reference} is not in the shop's tools"
                    if unlisted
                    else f"{', '.join(unknowns)} not known"
                    if unknowns
                    else "its tool resolves and its cutting data is stated"
                )
                findings.append(
                    Finding(
                        "tool_resolves",
                        subject,
                        status,
                        {
                            "item": item,
                            "make_op": index,
                            "solid": record(solid).get("name"),
                            "tool": reference,
                            "present": tool is not None,
                            "unknown": unknowns,
                        },
                        ["inventory make_ops", "docs/inventory.md Shop-made fixtures"],
                        f"{subject}: {reason}.",
                    )
                )
    return findings


def _manual_thread(bundle, subject, op):
    """Hand thread tools have real holders, but never a powered spindle stack."""
    tapping = op["do"] == "hand_tap"
    cutter, support = ("tap", "tap wrench/follower") if tapping else ("die", "die stock")
    tool_kinds = {"tap", "tap_set", "tap_die_set"} if tapping else {"die", "die_set", "tap_die_set"}
    holder_kinds = {"tap_wrench", "tap_follower"} if tapping else {"die_stock"}
    feature_kinds = {"thread", "threaded_hole"} if tapping else {"external_thread"}
    tool_ref, holder_ref = op.get("tool"), op.get("holder")
    tool = resolve(bundle, "tools", tool_ref)
    holder = resolve(bundle, "holders", holder_ref)
    definitions = record(getattr(bundle, "feature_definitions", None))
    feature = record(definitions.get(op.get("feature")))
    problems, missing = [], []
    nums = {
        "tool": tool_ref or UNKNOWN,
        "holder": holder_ref or UNKNOWN,
        "feature": op.get("feature", UNKNOWN),
        "manual": True,
    }
    if number(op.get("rpm")) and op["rpm"] != 0:
        problems.append("manual threading requires a stopped spindle, not a powered rpm")
    for label, item, kinds in ((cutter, tool, tool_kinds), (support, holder, holder_kinds)):
        kind = record(item).get("kind", UNKNOWN)
        if kind != UNKNOWN and kind not in kinds:
            problems.append(f"selected {label} has wrong tool kind {kind}")
        elif item is None or kind == UNKNOWN or uncertain(item):
            missing.append(f"resolve and verify the {label} identity")
    _, reference, _ = select(bundle, tool_ref, "tools")
    if tool is None and isinstance(reference, str) and "/" in reference:
        root, _, member = reference.partition("/")
        parent = record(select(bundle, root, "tools")[2])
        if isinstance(parent.get("members"), dict) and member not in parent["members"]:
            problems.append(f"selected {cutter} member is not declared in its set")
    kind = feature.get("kind", UNKNOWN)
    if kind != UNKNOWN and kind not in feature_kinds:
        problems.append(
            f"feature kind {kind} is not an {'internal' if tapping else 'external'} thread"
        )
    elif kind == UNKNOWN:
        missing.append("thread feature identity is unknown")
    for field in ("thread", "thread_hand", "thread_class"):
        required = feature.get(field, UNKNOWN)
        actual = record(tool).get(field, UNKNOWN)
        nums[field] = {"required": required, cutter: actual}
        if field == "thread":
            matches = thread_match(required, actual)
        else:
            matches = (
                required.strip().casefold() == actual.strip().casefold()
                if isinstance(required, str)
                and isinstance(actual, str)
                and required.strip().casefold() not in {"", UNKNOWN}
                and actual.strip().casefold() not in {"", UNKNOWN}
                else None
            )
        if matches is False:
            problems.append(f"{cutter} {field} does not match the thread feature")
        elif matches is None:
            missing.append(f"{cutter} and feature {field} must be known")
    fits = record(holder).get("fits", UNKNOWN)
    nums["holder_fits"] = fits
    fit_known = (
        fits not in (None, "", UNKNOWN) and tool_ref not in (None, UNKNOWN) and tool is not None
    )
    if fit_known and identity(bundle, fits, "tools") != identity(bundle, tool_ref, "tools"):
        problems.append(f"{support} does not fit the selected {cutter} identity")
    if tapping:
        # Wrench ranges are nominal tap sizes, not a spindle collet's shank fit.
        capacity_field = (
            "range"
            if any(key in record(holder) for key in ("range_mm", "range_in"))
            else "capacity"
        )
        capacity = limits_fact(holder, capacity_field, require_measured=False)
        maximum = length_mm(holder, capacity_field)
        diameter = length_mm(tool, "dia")
        nums.update(
            tap_dia_mm=diameter,
            holder_capacity_mm=capacity["value"] if capacity["verified"] else maximum,
        )
        if number(diameter) and capacity["verified"]:
            low, high = capacity["value"]
            if (diameter < low and not same_length(diameter, low)) or (
                diameter > high and not same_length(diameter, high)
            ):
                problems.append("tap nominal diameter is outside the wrench/follower capacity")
        elif number(diameter) and number(maximum):
            if diameter > maximum and not same_length(diameter, maximum):
                problems.append("tap nominal diameter exceeds the wrench/follower capacity")
        elif not fit_known:
            missing.append("tap wrench/follower fit or nominal tap-size capacity is unknown")
    elif not fit_known:
        missing.append("die stock fit to the selected die identity is unknown")
    status = "error" if problems else "unknown" if missing else "pass"
    message = "; ".join(problems or missing) or f"manual {cutter} and {support} match the thread"
    return Finding(
        "tool_resolves",
        subject,
        status,
        nums,
        ["inventory thread tool/member/spec/hand/class and manual holder fit or capacity"],
        f"{subject}: {message}.",
    )


def evaluate(bundle):
    findings = []
    # Each item a slot selects (setup_items), once: under its bare key when a bare reference
    # reads the same category, else as ``<category>.<key>`` (a ``checks`` gauge ``pins``
    # is ``gauges.pins`` when a fixture ``pins`` is listed first). Read as the rules read
    # it, so a whole set with no member is not a tool.
    selected = {}
    hand_items = {
        identity(bundle, op.get(field), category)
        for _, op in operations(bundle)
        if op.get("do") in HAND_THREAD
        for field, category in (("tool", "tools"), ("holder", "holders"))
    }
    powered_items = {
        identity(bundle, op.get(field), category)
        for _, op in operations(bundle)
        if op.get("do") not in HAND_THREAD
        for field, category in (("tool", "tools"), ("holder", "holders"))
    }
    hand_only_items = hand_items - powered_items
    for setup in bundle.plan.get("setups") or []:
        for category, ref, _ in setup_items(bundle, setup):
            bare = select(bundle, ref)[0] in (None, category)
            selected.setdefault(ref if bare else f"{category}.{ref}", (category, ref))
    for subject, (category, ref) in sorted(selected.items()):
        item = resolve(bundle, category, ref)
        status = "error" if item is None else "unknown" if uncertain(item) else "pass"
        if item is None and (category, ref) in hand_only_items:
            status = "unknown"
        numbers = {
            "reference": ref,
            "category": category,
            "present": item is not None,
            "verified": item is not None and not uncertain(item),
        }
        diameter_reason = None
        if item:
            numbers["kind"] = item.get("kind", "unknown")
            diameter = length_fact(item, "dia", require_measured=False)
            if diameter["verified"] and number(diameter["value"]):
                numbers["dia_mm"] = diameter["value"]
            elif diameter["measurement_status"] != UNKNOWN or (
                uncertain(item) and number(diameter["value"])
            ):
                status = "unknown"
                numbers["verified"] = False
                diameter_reason = diameter["reason"]
                debt = length_debt(item, "dia", category, ref)
                if debt:
                    numbers["measurements"] = [debt]
        findings.append(
            Finding(
                "tool_resolves",
                subject,
                status,
                numbers,
                ["inventory selected identity/declared member coverage", "PLAN.md §3.3"],
                f"{subject}: "
                + (
                    "not listed in the inventory."
                    if item is None
                    else "listed; presence or catalogue identity needs verification."
                    if uncertain(item)
                    else (
                        "listed identity resolves, but its diameter is unverified: "
                        f"{diameter_reason}"
                    )
                    if diameter_reason
                    else "listed inventory identity resolves."
                ),
            )
        )
    # An item the prose names (``gauges.granite-surface-plate`` in a make note, a record
    # blank's gauge) must be in the shop list: the traveler prints its name, and a name it
    # cannot find, or an item still to verify, is unknown, never a pass.
    # One item is one finding, however it is spelled: a slot's ``tools.drills/#61`` and its
    # bare ``drills/#61`` select the same item.
    chosen = set(selected.values())
    named = {k: v for k, v in named_references(bundle).items() if identity(bundle, k) not in chosen}
    for name, where in sorted(named.items()):
        category, reference, _ = select(bundle, name)
        item = named_item(bundle, name)
        verified = item is not None and not uncertain(item)
        places = "; ".join(where)
        findings.append(
            Finding(
                "tool_resolves",
                name,
                "pass" if verified else "unknown",
                {
                    "reference": reference,
                    "category": category,
                    "present": item is not None,
                    "verified": verified,
                    "named_in": where,
                },
                ["inventory item named in prose", "docs/inventory.md Shop-made fixtures"],
                f"{name}: named in {places}; "
                + (
                    "not listed in the inventory: list it or name a listed item."
                    if item is None
                    else "listed; presence or catalogue identity needs verification."
                    if not verified
                    else "listed inventory identity resolves."
                ),
            )
        )
    findings += _make_ops(bundle)
    for setup, op in operations(bundle):
        subject = f"{setup['id']}:{op['op']}"
        if op["do"] == "coating":
            findings.append(_coating(subject, op, bundle))
            continue
        if op["do"] in HAND_THREAD:
            findings.append(_manual_thread(bundle, subject, op))
            continue
        if op["do"] in MANUAL:
            continue
        if op["do"] in SAW_OPS:
            findings.append(
                _saw_assembly(
                    bundle,
                    subject,
                    setup,
                    op,
                    resolve(bundle, "tools", op.get("tool")),
                    resolve(bundle, "machines", setup["machine"]),
                    setup["machine"],
                )
            )
            continue
        tool = resolve(bundle, "tools", op.get("tool"))
        holder = resolve(bundle, "holders", op.get("holder"))
        machine = resolve(bundle, "machines", setup["machine"])
        nums = {
            "tool": op.get("tool", "unknown"),
            "holder": op.get("holder", "unknown"),
            "machine": setup["machine"],
        }
        problems = []
        cite = ["inventory spindle/holder/shank fields", "PLAN.md §4.1"]
        fit_unknown = None
        unknown = op["do"] == "unknown" or tool is None or holder is None or machine is None
        if not unknown:
            spindle = machine.get("spindle", {})
            toolpost = machine.get("toolpost", {})
            tailstock = machine.get("tailstock", {})
            # A lathe's spindle-axis tools ride in the tailstock quill, not the toolpost.
            machine_standard = (
                (spindle.get("taper") if isinstance(spindle, dict) else None)
                if machine.get("kind") != "lathe"
                else (tailstock.get("taper") if isinstance(tailstock, dict) else None)
                if op["do"] in _AXIAL_LATHE_ACTIONS
                else (toolpost.get("series") if isinstance(toolpost, dict) else None)
            )
            holder_standard = holder.get("taper", holder.get("standard", holder.get("series")))
            nums.update(
                machine_standard=machine_standard or "unknown",
                holder_standard=holder_standard or "unknown",
            )
            if (
                machine_standard
                and holder_standard
                and machine_standard != "unknown"
                and holder_standard != "unknown"
            ):
                if machine_standard != holder_standard:
                    problems.append("holder interface does not match machine")
            else:
                unknown = True
            shank = length_mm(tool, "shank")
            capacity = length_mm(holder, "capacity")
            max_shank = length_mm(holder, "max_shank")
            nums.update(shank_mm=shank, holder_capacity_mm=capacity)
            if number(shank) and number(capacity):
                # A shank at nominal needs no class; one off nominal is judged on the band.
                if not same_length(shank, capacity):
                    band = _h6_band(capacity)
                    nums.update(shank_fit=SHANK_FIT, shank_band_mm=band)
                    cite.append(SHANK_FIT_CITE)
                    if band == UNKNOWN and shank < capacity:
                        fit_unknown = (
                            "ISO 286-1 Table 1 gives no IT6 above 500 mm, so a shank under "
                            "the nominal collet size has no known fit"
                        )
                    elif band == UNKNOWN or not (
                        band[0] <= shank <= capacity or same_length(shank, band[0])
                    ):
                        problems.append("tool shank does not match selected collet")
            elif number(shank) and number(max_shank):
                if shank > max_shank and not same_length(shank, max_shank):
                    problems.append("tool shank exceeds holder capacity")
            elif number(shank) and isinstance(holder.get("capacity_mm"), list):
                low, high = holder["capacity_mm"]
                inside = low <= shank <= high
                if not (inside or same_length(shank, low) or same_length(shank, high)):
                    problems.append("tool shank outside holder range")
            else:
                unknown = True
            # Unverified dimensions cannot establish either a fit or a mismatch.
            if any(uncertain(item) for item in (tool, holder, machine)):
                unknown = True
                problems = []
        reasons = ["assembly fit needs measured shank, holder and machine facts"] if unknown else []
        if fit_unknown:
            reasons.append(fit_unknown)
        status = "error" if problems else "unknown" if reasons else "pass"
        message = "; ".join(problems or reasons) or "holder interface and shank fit"
        findings.append(
            Finding(
                "tool_resolves",
                subject,
                status,
                nums,
                cite,
                f"{subject}: {message}.",
            )
        )
    return findings
