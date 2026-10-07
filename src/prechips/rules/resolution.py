"""Inventory identities and explicit-unit nominal geometry; no catalogue lookups."""

from __future__ import annotations

import math
import re
from fractions import Fraction

UNKNOWN = "unknown"
# Inch fields convert by float multiplication (3/8 in -> 9.524999999999999 mm), so a
# converted length and its exact mm spelling differ by float residue, never by 1 nm.
LENGTH_TOLERANCE_MM = 1e-6
SET_KINDS = {
    "endmill_set",
    "collet_set",
    "parallels_set",
    "center_drill_set",
    "drill_index",
    "drill_set",
    "tap_die_set",
    "tap_set",
    "reamers",
    "countersink_set",
    "qctp_set",
    "insert_holders",
    "micrometer_set",
    "lathe_tool_bits",
}
# Bench filing to a scribed line: hand work (no spindle, cutter or DRO) that still finishes
# its feature's faces: the kernel models its removal and coverage credits its claims.
HAND_FINISH = frozenset({"file_to_line"})
MANUAL = {"inspect", "deburr", "coating", "release", "fit", "scribe"} | HAND_FINISH
SAW_OPS = frozenset({"saw_cut", "cut_off"})
HOLE_KINDS = frozenset({"hole", "counterbore", "thread", "threaded_hole"})
# The hole actions whose cut can form a hole's claimed point cap.
COMPLETE_FORM = frozenset({"drill", "ream", "bore", "counterbore"})
_INVENTORY_CATEGORIES = ("machines", "tools", "holders", "fixtures", "gauges")
WORKHOLDING_CATEGORIES = ("fixtures", "holders", "machines")


def number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def same_length(a, b):
    """Physical length equality in mm: absolute 1 nm, no relative slack."""
    return math.isclose(a, b, rel_tol=0.0, abs_tol=LENGTH_TOLERANCE_MM)


def manifest_mm(bundle, value):
    """A manifest-unit feature length (scalar or band) in mm; unknown units stay unknown."""
    scale = {"mm": 1.0, "in": 25.4}.get(bundle.features.get("units", UNKNOWN))
    if scale is None:
        return UNKNOWN
    if isinstance(value, list):
        return [v * scale if number(v) else UNKNOWN for v in value]
    return value * scale if number(value) else UNKNOWN


def fraction(value):
    try:
        return Fraction(str(value).removesuffix("in").replace("-", "/"))
    except (ValueError, ZeroDivisionError):
        return None


def uncertain(item):
    if not isinstance(item, dict):
        return item == UNKNOWN
    return (
        item.get("verify") is True
        or item.get("verify") == UNKNOWN
        or item.get("present") == UNKNOWN
        or "verify" in str(item.get("coverage", "")).lower()
        or any(uncertain(v) for v in item.values() if isinstance(v, dict))
    )


def record(value):
    return value if isinstance(value, dict) else {}


def drawing_precision(bundle, feature, requirement):
    """The decimals the drawing prints ``requirement`` of ``feature`` at: the feature's own
    ``precision`` entry, else the manifest's general precision."""
    general = bundle.features.get("precision")
    overrides = record(bundle.feature_definitions.get(feature)).get("precision", {})
    return overrides.get(requirement, general) if isinstance(overrides, dict) else overrides


def printed_band(limits, precision):
    """A two-sided band as the traveler prints it: at the drawing's integer precision, rounded
    inward (low up, high down) so printing never loosens it. None when the limits or the
    precision are unknown, or the band is too narrow for that precision (it then prints, and
    is held, at its declared limits)."""
    if not (isinstance(limits, (list, tuple)) and len(limits) == 2 and all(map(number, limits))):
        return None
    if not (isinstance(precision, int) and not isinstance(precision, bool)):
        return None
    scale = 10**precision
    low = math.ceil(round(limits[0] * scale, 6)) / scale
    high = math.floor(round(limits[1] * scale, 6)) / scale
    return [low, high] if low <= high else None


def rough_leave(op):
    """(leave, refusal): the stock per side, in mm, a rough stage of ``op`` leaves.

    A ``rough_*`` op leaves its ``rough_allowance_mm``, else its ``stock_to_leave_mm``; on
    any other op ``rough_allowance_mm`` is the leave its finish removes (a contour finish
    also prints the rough stage that leaves it). ``leave`` is None when the op names no
    leave and UNKNOWN when it is unknown. A negative leave puts the rough inside the
    finished part, which no finish restores: it is never offset by (``leave`` is UNKNOWN)
    and ``refusal`` says why; every rule that offsets a cut or a band by it is an error."""
    if str(op.get("do", "")).startswith("rough_"):
        key = "rough_allowance_mm" if "rough_allowance_mm" in op else "stock_to_leave_mm"
    elif "rough_allowance_mm" in op:
        key = "rough_allowance_mm"
    else:
        return None, None
    value = op.get(key, UNKNOWN)
    if not number(value) or not math.isfinite(value):
        return UNKNOWN, None
    if value < 0:
        return UNKNOWN, (
            f"{key} {value:g} is negative: the rough would cut {-value:g} mm into the finished part"
        )
    return value, None


def op_features(op):
    """Every feature an op names: its one feature, or an inspect op's list; none if absent."""
    feature = op.get("feature")
    if isinstance(feature, list):
        return list(feature)
    return [] if feature is None else [feature]


def op_feature(op):
    """The one feature an op cuts or works on; ``None`` when absent or an inspect list."""
    feature = op.get("feature")
    return feature if isinstance(feature, str) else None


def claim_refs(bundle, op):
    """The face refs an op claims: its explicit ``faces``, else its feature's ``faces``; a
    plan-owned transient (joint or process) feature claims its one plan label."""
    if "faces" in op:
        return op["faces"]
    feature = record(bundle.feature_definitions.get(op_feature(op)))
    owner = record(feature.get("joint")) or record(feature.get("preparation"))
    return [owner["label"]] if owner else feature.get("faces", UNKNOWN)


def known_refs(refs):
    return isinstance(refs, list) and bool(refs) and UNKNOWN not in refs


def owns_feature(bundle, op, name):
    """Whether an op's explicit ``faces`` claim every declared face of feature ``name``.

    Ownership needs a known, nonempty feature face list and a known, nonempty explicit
    claim that contains all of it; empty, unknown, malformed or partial claims never
    establish it, and a label alone never does. A hole-family feature is owned only by a
    complete-form action (drill/ream/bore/counterbore): a spot, tap, pilot or profile op
    never becomes a hole's owner through its claim.
    """
    if "faces" not in op:
        return False
    feature = record(bundle.feature_definitions.get(name))
    if feature.get("kind") in HOLE_KINDS and op.get("do") not in COMPLETE_FORM:
        return False
    claimed, declared = op["faces"], feature.get("faces", UNKNOWN)
    return known_refs(claimed) and known_refs(declared) and set(declared) <= set(claimed)


EXPORTED_FRAMES = "features.frames"
PLAN_FRAMES = "plan.frames"


def setup_frame_ref(bundle, setup):
    """The setup's frame and its owner: the exported manifest, else the plan's own frames.

    Loading rejects plan frames that reuse an exported name, and an exported name still
    wins here, so a plan never shadows CAD. Feature source frames are manifest-only.
    """
    name = setup.get("frame", UNKNOWN)
    exported = record(bundle.features.get("frames"))
    planned = record(bundle.plan.get("frames"))
    if name not in exported and name in planned:
        return record(planned[name]), PLAN_FRAMES
    return record(exported.get(name)), EXPORTED_FRAMES


def setup_frame(bundle, setup):
    return setup_frame_ref(bundle, setup)[0]


def plan_frame_cite(bundle, setup):
    """Name a plan-owned setup frame and its cites; exported frames keep existing cites."""
    frame, owner = setup_frame_ref(bundle, setup)
    if owner == EXPORTED_FRAMES:
        return []
    label = f"{owner}.{setup.get('frame')}: author-declared setup frame"
    return [label, *_citations(frame.get("cite"))]


def _citations(value, field=None):
    """Keep usable cited strings; a field selects only that fact from a citation map."""
    if isinstance(value, dict):
        if field is not None:
            return _citations(value.get(field))
        return [text for key in sorted(value) for text in _citations(value[key])]
    if isinstance(value, list):
        return [text for item in value for text in _citations(item, field)]
    if isinstance(value, str) and value.strip() and value.strip() != UNKNOWN:
        return [value]
    return []


def inch_sizes(value):
    """Declared inch sizes from a flat list or from every group of a grouped mapping."""
    groups = value.values() if isinstance(value, dict) else (value,)
    return [size for group in groups if isinstance(group, list) for size in group]


def flute_counts(value):
    """Declared flute counts from a single count or a list of counts."""
    return value if isinstance(value, list) else [value] if number(value) else []


def inventory_record(value):
    item = dict(record(value))
    for key in ("members", "nominal_dia_mm", "nominal_dia_cite", "holders"):
        if key in item and not isinstance(item[key], dict):
            item[key] = {}
            item["verify"] = True
    for key in (
        "standard_accessories",
        "included",
        "sizes",
        "sizes_mm",
        "sizes_in",
        "styles",
        "ranges_in",
        "heights_in",
        "flutes",
    ):
        if item.get(key) == UNKNOWN:
            item[key] = []
            item["verify"] = True
    return item


def length_mm(item, field):
    from prechips.measurements import nominal_length_mm

    return nominal_length_mm(item, field)


# The categories each kind of slot reads, in order; any other slot reads its one category.
# A hold's fixture (and its dividing head) is workholding: a fixture, a holder or a machine.
# A spindle slot (a zero's touch tool, a transfer's tool) holds a tool or an indicator. A
# coating's process is in-house consumables or an outside service.
SLOT_CATEGORIES = {
    "workholding": WORKHOLDING_CATEGORIES,
    "spindle": ("tools", "gauges"),
    "process": ("consumables", "services"),
}
# A reference that names its category: ``gauges.dti``, ``tools.drills/#61``.
_QUALIFIED = re.compile(r"(machines|tools|holders|fixtures|gauges|services)\.(.+)", re.DOTALL)
_NO_ITEM = frozenset({UNKNOWN, "none", "not_applicable"})


def select(bundle_or_inventory, reference, slot=None):
    """``(category, reference, item)``: the one inventory item ``reference`` names. This is
    the only place the inventory is read by key; every rule, receipt and printed name reads
    the item it returns.

    A reference that names its category (``gauges.dti``) is in that category, whatever the
    slot. A slot reads its own categories in order (:data:`SLOT_CATEGORIES`), and the first
    that lists the key, or is stated unknown as a whole (it may list it), is final; only a
    bare reference with no slot reads every category, in the default order, the same way.
    ``reference`` comes back without its category; ``category`` is the one read (with
    nothing found, the slot's first, or None for a bare reference). ``item`` is the
    resolved record (a member's merged over its set's, a whole set as itself);
    :data:`UNKNOWN` when the category, item or member is stated unknown or the item is
    listed with nothing about it (``{}``); None when nothing in order lists it (a machine's
    standard accessory of that name excepted), it is not present, or its member is not one
    it declares. A same-key item in another category is never read."""
    # A bundle with no shop list lists nothing.
    inventory = record(getattr(bundle_or_inventory, "inventory", bundle_or_inventory))
    qualified = _QUALIFIED.fullmatch(reference) if isinstance(reference, str) else None
    if qualified:
        order, reference = (qualified[1],), qualified[2]
    elif slot:
        order = SLOT_CATEGORIES.get(slot, (slot,))
    else:
        order = _INVENTORY_CATEGORIES
    first = order[0] if qualified or slot else None
    if not isinstance(reference, str) or reference in _NO_ITEM:
        return first, reference, None
    root, separator, member = reference.partition("/")
    for category in order:
        entries = inventory.get(category, {})
        if entries == UNKNOWN:
            return category, reference, UNKNOWN
        if isinstance(entries, dict) and root in entries:
            return category, reference, _item(entries[root], separator, member)
    machines = inventory.get("machines", {})
    for machine in machines.values() if isinstance(machines, dict) else ():
        machine = inventory_record(machine)
        if reference in machine.get("standard_accessories", []) + machine.get("included", []):
            accessory = {
                "kind": "accessory",
                "verify": uncertain(machine),
                "source": machine.get("source", "inventory machine accessories"),
            }
            return first, reference, accessory
    return first, reference, None


def identity(bundle_or_inventory, reference, slot=None):
    """``(category, key)``: the one item ``reference`` names in ``slot`` (:func:`select`),
    however it is spelled (``tools.drill`` and ``drill``; a member's key keeps its member).
    Every map, set and comparison of items downstream keys on this, never on a spelling;
    the spelling is kept only to print."""
    return select(bundle_or_inventory, reference, slot)[:2]


def authored(bundle_or_inventory, category, reference):
    """The record the shop list states for a selected ``(category, reference)``
    (:func:`select`), as written: a member's set's own; {} when that category lists none."""
    inventory = getattr(bundle_or_inventory, "inventory", bundle_or_inventory)
    root = reference.partition("/")[0] if isinstance(reference, str) else None
    return record(record(inventory.get(category)).get(root)) if category else {}


def projection_holder(bundle_or_inventory, tool, holder):
    """``(key, conflict)``: the key of ``tool``'s projection map (``projection_mm`` /
    ``projection_in``) that names the holder ``holder`` selects. A key and a holder
    reference are one holder when they select the same ``(category, reference)``, however
    each is spelled. ``(None, None)`` when no key names it. When more than one key names it
    (``holder`` and ``holders.holder``, or one key in both maps) the map states one
    projection twice: ``(None, reason)``, and the projection is unknown, never the entry
    dictionary order puts first."""
    selected = identity(bundle_or_inventory, holder, "holders")
    keys = [
        f"{field}.{key}"
        for field in ("projection_mm", "projection_in")
        for key in record(record(tool).get(field))
        if identity(bundle_or_inventory, key, "holders") == selected
    ]
    if len(keys) > 1:
        return None, (
            f"{' and '.join(keys)} each state the projection in {selected[0]}.{selected[1]}; "
            "state it once"
        )
    return (keys[0].partition(".")[2] if keys else None), None


# The hold's item slots after its fixture, in the order the HOLD uses them: each a fixture.
_HOLD_ITEMS = ("chuck", "parallels", "riser", "jaw_bar", "jaw_buttons", "support")
# A ``hold.clamp`` is prose unless it is a slug (``toe-clamps``): then it names a fixture.
_CLAMP_SLUG = re.compile(r"[\w]+(?:-[\w]+)+")


def setup_items(bundle, setup):
    """``[(category, reference, item)]`` (:func:`select`): every inventory item a setup puts
    its hands on, first use first, each as its slot selects it. The slots: the machine;
    the hold's fixture and dividing head (workholding); its chuck, parallels, riser, jaw
    bar / buttons, support, clamps, stop, supports and support blocks (fixtures) and
    alignment indicator (a gauge); the zero's touch tools (spindle), holders and gauges (a
    tool touch's Z measuring gauge too), the transfer's tool (spindle) and gauge; then each
    op's filing guide (its buttons a fixture, its template and gauge gauges), tool,
    holder, inspection gauges (``checks`` and ``missing_requirements``) and process-hold
    gauges. A shop-made holding item is followed by the tool of each of its make
    operations (:func:`make_ops`), a ``tools`` item only (:func:`make_tool`). One reference
    two kinds of slot select in two categories is two items. An item is its category and
    reference from here on: every reader uses that pair, never the bare key again."""
    hold = record(setup.get("hold"))
    uses = [("workholding", hold.get("fixture"))]
    uses += [("fixtures", hold.get(key)) for key in _HOLD_ITEMS]
    clamps = hold.get("clamps") if isinstance(hold.get("clamps"), list) else []
    uses += [("fixtures", c if isinstance(c, str) else record(c).get("ref")) for c in clamps]
    uses.append(("fixtures", hold.get("stop_fixture")))
    supports = hold.get("supports")
    for support in supports if isinstance(supports, list) else [supports]:
        ref = record(support).get("ref") if isinstance(support, dict) else support
        uses.append(("fixtures", ref))
    uses.append(("gauges", record(hold.get("align")).get("indicator")))
    zero = record(setup.get("zero"))
    touches = zero.get("tool_touches") if isinstance(zero.get("tool_touches"), list) else []
    slots = (("tool", "spindle"), ("holder", "holders"), ("gauge", "gauges"), ("z_gauge", "gauges"))
    for touch in [*(zero.get(axis) for axis in "xyz"), *touches]:
        uses += [(kind, record(touch).get(key)) for key, kind in slots]
    transfer = record(zero.get("transfer"))
    uses += [("spindle", transfer.get("tool")), ("gauges", transfer.get("gauge"))]
    for op in setup.get("ops") or []:
        op = record(op)
        guide = record(op.get("guide"))
        uses += [("fixtures", guide.get("buttons"))]
        uses += [("gauges", guide.get("template")), ("gauges", guide.get("gauge"))]
        uses += [("tools", op.get("tool")), ("holders", op.get("holder"))]
        for key in ("checks", "missing_requirements"):
            uses += [("gauges", gauge) for gauge in record(op.get(key)).values()]
        process_holds = op.get("process_holds")
        for held in process_holds if isinstance(process_holds, list) else []:
            uses.append(("gauges", record(held).get("gauge")))
    # Last, so the order the slots above print their receipts in stands: the machine, the
    # dividing head, support blocks and a clamp named by its slug.
    uses += [("machines", setup.get("machine"))]
    uses += [("workholding", record(hold.get("index")).get("fixture"))]
    uses += [("fixtures", hold.get("support_blocks"))]
    clamp = hold.get("clamp")
    if isinstance(clamp, str) and _CLAMP_SLUG.fullmatch(clamp):
        uses.append(("fixtures", clamp))
    items, seen = [], set()
    for slot, ref in uses:
        if not isinstance(ref, str) or ref in _NO_ITEM:
            continue
        category, reference, item = select(bundle, ref, slot)
        made = (
            shop_made_item(bundle, reference, category)
            if category in WORKHOLDING_CATEGORIES
            else None
        )
        found = [(category, reference, item)] + [
            ("tools", tool, make_tool(bundle, tool))
            for tool in (record(op).get("tool") for _, op in make_ops(made))
            if isinstance(tool, str) and tool not in _NO_ITEM
        ]
        for entry in found:
            if entry[:2] not in seen:
                seen.add(entry[:2])
                items.append(entry)
    return items


def shop_made_item(bundle, reference, slot):
    """The inventory record of a shop-made holding item (``kind = "custom"`` or flagged
    ``shop_made``) with something to make, else None: an item whose every solid is bought
    or existing (a plain ground plate) has no make table. ``slot`` is the using slot's kind
    or the category it selected (:func:`setup_items`); the item is the one
    :func:`select` reads there, never another category's of the same key."""
    item = record(resolve(bundle, slot, reference))
    if not (item.get("kind") == "custom" or item.get("shop_made") is True):
        return None
    solids = [s for s in item.get("solids") or [] if isinstance(s, dict)]
    if solids and not any(s.get("supply", "made") == "made" for s in solids):
        return None
    return item


def make_ops(item):
    """``[(solid, op)]``: the make operations of a shop-made item (:func:`shop_made_item`)
    in the order they are run: the item's own ``make_ops`` (solid ``None``), then each
    primitive's, in ``solids`` order. Primitives sharing a ``label`` (one make-table row)
    with the same list give it once. A list stated ``unknown`` is one ``(solid,
    "unknown")`` entry: unknown, never no operation."""
    item = record(item)
    found = []
    seen = set()
    for solid in [None, *(s for s in item.get("solids") or [] if isinstance(s, dict))]:
        owner = item if solid is None else solid
        if "make_ops" not in owner:
            continue
        ops = owner["make_ops"]
        key = (record(solid).get("label"), repr(ops))
        if solid is not None and key[0] is not None and key in seen:
            continue
        seen.add(key)
        found += [(solid, op) for op in ops] if isinstance(ops, list) else [(solid, UNKNOWN)]
    return found


# What one make-operation line states, in print order.
MAKE_OP_FIELDS = ("hold", "tool", "rpm", "feed", "doc_mm", "cite")


def make_op_unknowns(op):
    """The fields of a make operation (:func:`make_ops`) its line cannot state: all of an
    unknown list's; else each text (hold, tool, feed, cite) omitted, blank or ``unknown``
    and each number (``rpm`` a number or [low, high] range, ``doc_mm``) not known. An
    omitted field is no more known than an ``unknown`` one."""
    if not isinstance(op, dict):
        return list(MAKE_OP_FIELDS)

    def known(key, value):
        if key == "rpm" and isinstance(value, list):
            return len(value) == 2 and all(map(number, value))
        if key in ("rpm", "doc_mm"):
            return number(value)
        return isinstance(value, str) and value.strip() not in ("", UNKNOWN)

    return [key for key in MAKE_OP_FIELDS if not known(key, op.get(key))]


def make_tool(bundle, reference):
    """The ``tools`` record a make operation's ``tool`` names: read in ``tools`` only, never
    a same-key item of another category or a machine's standard accessory. ``{"kind":
    "unknown", "verify": True}`` when the tools list or the item is stated unknown; None when
    the tools do not list it, it is not present or it is no member its set declares."""
    if not isinstance(reference, str) or reference in (UNKNOWN, "none", "not_applicable"):
        return None
    tools = getattr(bundle, "inventory", bundle).get("tools", {})
    if tools == UNKNOWN:
        return {"kind": UNKNOWN, "verify": True}
    if reference.partition("/")[0] not in record(tools):
        return None
    return resolve(bundle, "tools", reference)


# An inventory item named in prose (a make note, a plan note): ``<category>.<key>`` with an
# optional ``/<member>``, as in ``gauges.granite-surface-plate`` or ``tools.drills/#61``.
# The member is everything :func:`resolve` reads as one (``#61``, ``1/4``, ``1-4in``,
# ``6.49mm``, ``0-1in``), up to its last letter, digit or ``#``: a name is taken whole and
# never cut back to a prefix that happens to resolve (``drills/#61`` is not ``drills``).
NAMED_REFERENCE = re.compile(
    r"\b(machines|tools|holders|fixtures|gauges|services)"
    r"\.([A-Za-z0-9](?:[\w-]*\w)?(?:/[\w#./-]*[\w#])?)"
)

# A link or path in authored text, taken literally to the next whitespace: a URL
# (``scheme://…``), a drive-letter path (``C:\…``, ``C:/…``), a UNC path (``\\server\…``), a
# relative path (``./…``, ``../…``) or a rooted one (``/srv/…/…``). Nothing in it is a name.
LITERAL_SPAN = re.compile(
    r"(?<![\w.+-])[A-Za-z][A-Za-z0-9+.-]*://\S*"
    r"|(?<![\w\\])[A-Za-z]:[\\/]\S*"
    r"|(?<![\w\\])\\\\[^\s\\]+\\\S*"
    r"|(?<![\w./\\])\.{1,2}[\\/]\S*"
    r"|(?<![\w./\\:])/[^\s/]+/\S*"
)


def authored_names(text):
    """``[(start, end, "<category>.<key>")]``: each inventory item authored text (a make
    operation's hold or source, printed as written) names (:data:`NAMED_REFERENCE`),
    outside its links and paths (:data:`LITERAL_SPAN`): a name next to punctuation or in
    quotes is a name, nothing inside ``https://tools.example.com/x`` or
    ``C:\\shop\\tools.chart.pdf`` is."""
    text = text if isinstance(text, str) else ""
    prose = LITERAL_SPAN.sub(lambda span: " " * len(span[0]), text)
    return [(m.start(), m.end(), m[0]) for m in NAMED_REFERENCE.finditer(prose)]


def setup_named_references(bundle, setup, job=False):
    """``{"<category>.<key>": [where, ...]}`` for one setup: every inventory item named
    (:data:`NAMED_REFERENCE`) in the setup's own prose and in the solid notes, record
    blanks and make operations' hold and source (:func:`authored_names`: never inside a
    link or path) of the shop-made items it uses, each record's gauge as
    ``gauges.<gauge>``.
    With ``job``, the plan's prose outside its setups (the job page's, before the first
    setup) too."""
    named = {}

    def add(name, where):
        places = named.setdefault(name, [])
        if where not in places:
            places.append(where)

    def scan(value, where):
        if isinstance(value, dict):
            for child in value.values():
                scan(child, where)
        elif isinstance(value, list):
            for child in value:
                scan(child, where)
        elif isinstance(value, str):
            for category, key in NAMED_REFERENCE.findall(value):
                add(f"{category}.{key}", where)

    setup = record(setup)
    if job:
        scan({key: value for key, value in bundle.plan.items() if key != "setups"}, "plan")
    scan(setup, f"Setup {setup.get('id', '?')}")
    # A shop-made item holds the work: read the one each slot selected, in its category.
    held = [(c, ref) for c, ref, _ in setup_items(bundle, setup) if c in WORKHOLDING_CATEGORIES]
    for category, ref in held:
        item = shop_made_item(bundle, ref, category)
        for solid in (item or {}).get("solids") or []:
            where = f"{ref} {record(solid).get('name', '?')}"
            scan(record(solid).get("note"), f"{where} note")
            blanks = record(solid).get("records")
            for blank in blanks if isinstance(blanks, list) else []:
                scan([record(blank).get("check"), record(blank).get("how")], f"{where} record")
                gauge = record(blank).get("gauge")
                if isinstance(gauge, str) and gauge not in ("none", "not_applicable"):
                    add(f"gauges.{gauge}", f"{where} record")
        for solid, op in make_ops(item):
            where = f"{ref} {record(solid).get('name', 'item')} make op"
            for text in (record(op).get("hold"), record(op).get("cite")):
                for *_, name in authored_names(text):
                    add(name, where)
    return named


def named_references(bundle):
    """``{"<category>.<key>": [where, ...]}``: :func:`setup_named_references` over every
    setup, the plan's own prose with the first."""
    named = {}
    for index, setup in enumerate(bundle.plan.get("setups") or []):
        for name, places in setup_named_references(bundle, setup, job=index == 0).items():
            named.setdefault(name, [])
            named[name] += [where for where in places if where not in named[name]]
    return named


def named_item(bundle, name):
    """The inventory record a :data:`NAMED_REFERENCE` ``<category>.<key>`` names
    (:func:`select`), else None. A whole set (``tools.reamers-metric``) is named as itself;
    a member is resolved. An item, member or category stated unknown, or an item listed
    with nothing about it (``{}``), is unknown (needs verifying), not absent."""
    _, _, item = select(bundle, name)
    return {"kind": UNKNOWN, "verify": True} if item == UNKNOWN else item


def resolve(bundle_or_inventory, slot, reference):
    """The item :func:`select` reads for ``reference`` in ``slot`` (a slot kind or one
    category; None for a bare reference), as a rule uses it: an unknown one as
    ``{"kind": "unknown", "verify": True}``, and a whole set as None (its member is the
    tool)."""
    _, reference, item = select(bundle_or_inventory, reference, slot)
    if item == UNKNOWN:
        return {"kind": UNKNOWN, "verify": True}
    if isinstance(item, dict) and "/" not in reference and item.get("kind") in SET_KINDS:
        return None
    return item


def _item(entry, separator, member):
    """A listed entry as :func:`select` returns it: the record, merged with its member's (a
    member listed ``{}`` is its set's)."""
    if entry == UNKNOWN or not isinstance(entry, dict) or not entry:
        return UNKNOWN
    item = inventory_record(entry)
    if item.get("present") is False:
        return None
    item["verify"] = uncertain(item)
    parent_uncertain = item["verify"]
    if not separator:
        return item
    kind = item.get("kind")
    size = fraction(member)
    if member in item.get("members", {}):
        selected = item["members"][member]
        if selected == UNKNOWN:
            return UNKNOWN
        item.update(inventory_record(selected))
    elif kind in {"collet_set", "parallels_set", "countersink_set"}:
        choices = inch_sizes(item.get("sizes_in", item.get("heights_in", [])))
        if size is None or size not in {fraction(v) for v in choices}:
            return None
        item[
            {
                "collet_set": "capacity_mm",
                "parallels_set": "height_mm",
                "countersink_set": "dia_mm",
            }[kind]
        ] = float(size) * 25.4
    elif kind in {"reamers", "drill_set"}:
        if member.endswith("mm"):
            selected = fraction(member.removesuffix("mm"))
            if selected is None or selected not in {fraction(v) for v in item.get("sizes_mm", [])}:
                return None
            item["dia_mm"] = float(selected)
        elif (
            member.endswith("in")
            and size is not None
            and size in {fraction(v) for v in inch_sizes(item.get("sizes_in"))}
        ):
            item["dia_mm"] = float(size) * 25.4
        else:
            return None
    elif kind == "endmill_set":
        match = re.fullmatch(r"(.+in)-(\d+)fl", member)
        if not match:
            return None
        size = fraction(match[1])
        flutes = int(match[2])
        choices = {fraction(v) for v in inch_sizes(item.get("sizes_in"))}
        if size is None or size not in choices or flutes not in flute_counts(item.get("flutes")):
            return None
        item.update(dia_mm=float(size) * 25.4, flutes=flutes)
        for shank, sizes in record(item.get("shank_in")).items():
            if isinstance(sizes, list) and size in {fraction(v) for v in sizes}:
                item["shank_mm"] = float(fraction(shank)) * 25.4
    elif kind == "center_drill_set":
        selected = member.removeprefix("#")
        if not selected.isdigit() or int(selected) not in item.get("sizes", []):
            return None
    elif kind == "drill_index":
        coverage = str(item.get("coverage", ""))
        numbered = re.fullmatch(r"#(\d+)", member)
        valid = (
            (numbered and "#1-60" in coverage and 1 <= int(numbered[1]) <= 60)
            or (re.fullmatch(r"[A-Z]", member) and "A-Z" in coverage)
            or (
                size is not None
                and "1/16-1/2 by 64ths" in coverage
                and Fraction(1, 16) <= size <= Fraction(1, 2)
                and (size * 64).denominator == 1
            )
        )
        if not valid:
            return None
        item["dia_mm"] = item.get("nominal_dia_mm", {}).get(
            member, float(size) * 25.4 if size is not None else UNKNOWN
        )
        item["dia_cite"] = item.get("nominal_dia_cite", {}).get(
            member, "inventory declared fractional drill coverage × 25.4 mm/in"
        )
    elif kind == "qctp_set":
        names = {
            "1-turning-facing": "#1 turning/facing",
            "2-boring-turning-facing": "#2 boring/turning/facing",
            "4-heavy-boring": "#4 heavy boring",
            "7-parting": "#7 parting (1/2 blade)",
        }
        if names.get(member, member) not in item.get("holders", {}):
            return None
    elif kind == "insert_holders":
        if member not in item.get("styles", []):
            return None
    elif kind == "micrometer_set":
        if member.removesuffix("in") not in item.get("ranges_in", []):
            return None
        low, high = member.removesuffix("in").split("-")
        item["range_mm"] = [float(low) * 25.4, float(high) * 25.4]
    else:
        return None
    if item.get("present") is False:
        return None
    item["verify"] = parent_uncertain or uncertain(item)
    return item


def tool_numbers(bundle, setup):
    """``{(tool, holder): "T<n>"}`` for ``setup``'s cutting ops in first-use order: the
    numbers its TOOLS table prints, one per tool + holder pair, keyed by the items the pair
    selects (:func:`identity`; ``tools.drill`` and ``drill`` are one drill). A lathe's
    holders stay on its toolpost between setups, so there a pair keeps one number on every
    setup that machine (by identity) runs (first use over the plan)."""

    def pair(op):
        return identity(bundle, op["tool"], "tools"), identity(bundle, op.get("holder"), "holders")

    lathe = record(resolve(bundle, "machines", setup.get("machine"))).get("kind") == "lathe"
    machine = identity(bundle, setup.get("machine"), "machines")
    setups = (
        [
            each
            for each in bundle.plan.get("setups", [])
            if identity(bundle, each.get("machine"), "machines") == machine
        ]
        if lathe
        else [setup]
    )
    fixed = {}
    for each in setups:
        for op in each.get("ops", []):
            if op.get("do") in MANUAL or op.get("tool") in (None, UNKNOWN):
                continue
            fixed.setdefault(pair(op), f"T{len(fixed) + 1}")
    numbers = {}
    for op in setup.get("ops", []):
        if op.get("do") in MANUAL or op.get("tool") in (None, UNKNOWN):
            continue
        numbers.setdefault(pair(op), fixed[pair(op)])
    return numbers


def jaw_top_z(bundle, setup, hold, scale):
    """The vise jaw tops' Z in ``setup``'s frame (plan units): the work's seated bottom
    (``retained_rail_bottom_z`` when lower than ``bottom_z``) plus the hold's
    ``jaw_above_parallels_mm``, as the kernel seats its jaws. None when any input is unknown
    or unverified, as the kernel's vise inputs read them: a jaw height flagged
    ``jaw_above_parallels_mm_verify`` (anything but false) or not a number at least 0;
    parallels other than ``"none"`` / ``"not_applicable"`` that do not resolve, are
    uncertain or lack an accepted positive ``height``; an unknown seat (an authored but
    unknown rail included); or ``scale`` (mm per plan unit)."""
    from prechips.measurements import length_fact
    from prechips.rules._envelope import measurement_item

    hold = record(hold)
    state = record(setup.get("stock_state"))
    bottom, rail = state.get("bottom_z"), state.get("retained_rail_bottom_z")
    jaw = hold.get("jaw_above_parallels_mm")
    if not (scale and number(bottom) and number(jaw) and jaw >= 0) or (
        rail is not None and not number(rail)
    ):
        return None
    if hold.get("jaw_above_parallels_mm_verify", False) is not False:
        return None
    parallels = hold.get("parallels")
    if parallels not in ("none", "not_applicable"):
        if not isinstance(parallels, str) or uncertain(resolve(bundle, "fixtures", parallels)):
            return None
        height = length_fact(
            measurement_item(bundle, "fixtures", parallels), "height", require_measured=False
        )
        if not (height["verified"] and number(height["value"]) and height["value"] > 0):
            return None
    return (min(bottom, rail) if rail is not None else bottom) + jaw / scale


def operations(bundle, feature=None, owned=False):
    """Every (setup, op), or those naming ``feature``; ``owned`` adds complete claimers.

    An inspect op naming a feature list selects each feature it names. With ``owned`` an
    op also selects a feature it does not name when its explicit faces claim the whole
    feature (``owns_feature``). Labels keep describing the op's own feature, so
    label-scoped callers (chains, sizing, inspection) keep the default.
    """
    return [
        (setup, op)
        for setup in bundle.plan["setups"]
        for op in setup["ops"]
        if feature is None
        or feature in op_features(op)
        or (owned and owns_feature(bundle, op, feature))
    ]


def coating_process(bundle_or_inventory, reference):
    """Where a coating op's process resolves (:func:`select`, in-house consumables before
    outside services): ``("consumables", record)`` for in-house kit, ``("services", item)``
    for an outside process, else ``(None, None)``. Consumables stated unknown, as a whole or
    the entry, are unknown in-house kit."""
    inventory = getattr(bundle_or_inventory, "inventory", bundle_or_inventory)
    category, reference, item = select(inventory, reference, "process")
    if item is None:
        return None, None
    if category == "consumables" and (item == UNKNOWN or authored(inventory, category, reference)):
        entry = item if isinstance(item, dict) else {}
        products = entry.get("products", UNKNOWN)
        # A blank or "unknown" product is not a resolved product.
        known = (
            isinstance(products, list)
            and bool(products)
            and all(isinstance(p, str) and p.strip() not in {"", UNKNOWN} for p in products)
        )
        return "consumables", {
            "kind": "consumables",
            "name": entry.get("name", UNKNOWN),
            "products": products if known else UNKNOWN,
            "verify": not known,
        }
    # An outside service (a machine's accessory of that name too, as any slot reads one).
    return "services", {"kind": UNKNOWN, "verify": True} if item == UNKNOWN else item


def saw_setup(setup):
    """A dedicated saw setup: at least one saw op and every non-manual op is a saw op.

    An explicitly unknown action is not a saw op, so it keeps the setup assessed.
    """
    actions = [op.get("do", UNKNOWN) for op in setup.get("ops", [])]
    cutting = [action for action in actions if action not in MANUAL]
    return bool(cutting) and all(action in SAW_OPS for action in cutting)


def candidate_refs(inventory):
    """Enumerate declared identities/coverage, never hypothetical purchases."""
    for category in ("machines", "fixtures", "holders", "tools", "gauges"):
        entries = inventory.get(category, {})
        if not isinstance(entries, dict):
            continue
        for root, item in sorted(entries.items()):
            yield category, root
            item = inventory_record(item)
            members = set(item.get("members", {}))
            kind = item.get("kind")
            if kind == "endmill_set":
                flute_choices = flute_counts(item.get("flutes"))
                for size in inch_sizes(item.get("sizes_in")):
                    value = fraction(size)
                    if value is not None:
                        token = str(value).replace("/", "-") + "in"
                        members.update(f"{token}-{flutes}fl" for flutes in flute_choices)
            elif kind in {"collet_set", "parallels_set", "countersink_set", "reamers", "drill_set"}:
                members.update(
                    str(value).replace("/", "-") + "in"
                    for value in inch_sizes(item.get("sizes_in", item.get("heights_in", [])))
                )
                if kind in {"reamers", "drill_set"}:
                    members.update(str(value) + "mm" for value in item.get("sizes_mm", []))
            elif kind == "center_drill_set":
                members.update(str(value) for value in item.get("sizes", []))
            elif kind == "drill_index":
                coverage = str(item.get("coverage", ""))
                members.update(item.get("nominal_dia_mm", {}))
                if "#1-60" in coverage:
                    members.update(f"#{value}" for value in range(1, 61))
                if "A-Z" in coverage:
                    members.update(chr(value) for value in range(ord("A"), ord("Z") + 1))
                if "1/16-1/2 by 64ths" in coverage:
                    members.update(
                        str(Fraction(value, 64)).replace("/", "-") + "in" for value in range(4, 33)
                    )
            elif kind == "qctp_set":
                names = {
                    "#1 turning/facing": "1-turning-facing",
                    "#2 boring/turning/facing": "2-boring-turning-facing",
                    "#4 heavy boring": "4-heavy-boring",
                    "#7 parting (1/2 blade)": "7-parting",
                }
                members.update(names.get(value, value) for value in item.get("holders", {}))
            elif kind == "insert_holders":
                members.update(item.get("styles", []))
            elif kind == "micrometer_set":
                members.update(value + "in" for value in item.get("ranges_in", []))
            for member in sorted(members):
                yield category, root + "/" + member
            for accessory in sorted(
                item.get("standard_accessories", []) + item.get("included", [])
            ):
                yield category, accessory
