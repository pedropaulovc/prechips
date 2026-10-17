"""Split from zero_recipe.py by scripts/split_modules.py."""

from __future__ import annotations

from itertools import pairwise, product

from prechips.rules.zero_recipe.touch import FILL_MARGIN_MM, TOUCH_LAND_MM, TURNED, _position

from ...model import setup_lineage
from ..resolution import LENGTH_TOLERANCE_MM, MANUAL, UNKNOWN, known_refs, number, setup_frame
from ..tip_endpoints import (
    FACING,
    POCKETING,
    _setup_footprint,
    cut_coverage,
    cut_region,
    mapping,
    records,
)


def paper_offset(paper_mm, side):
    """Where a Z touch through ``paper_mm`` of paper stands off its face along setup Z: the
    paper lies on the ``side`` (:func:`touch_side`) the tool meets the face from, so the
    contact is ``edge + side * paper``. No paper needs no side; an unknown side or paper
    otherwise leaves it unknown. The paper itself is never negative."""
    if not number(paper_mm):
        return UNKNOWN
    if paper_mm == 0:
        return paper_mm
    return side * paper_mm if side in (1, -1) else UNKNOWN


def _boundary(ops, record):
    """The index of the op a Z touch is made before, as :func:`_position`, but with every
    declared name required to resolve: an empty or partly unresolved ``before_ops``, or an
    unresolved ``after_op``, is UNKNOWN, never the initial boundary. A touch declaring
    neither is made before the first op."""
    names = [str(op.get("op")) for op in ops]
    if "before_ops" in record:
        before = record["before_ops"]
        before = before if isinstance(before, list) else [before]
        if not before or any(str(n) not in names for n in before):
            return UNKNOWN
        return min(names.index(str(n)) for n in before)
    after = record.get("after_op")
    if after is None:
        return 0
    return names.index(str(after)) + 1 if str(after) in names else UNKNOWN


def _features(op):
    """The features an op cuts; None when the plan does not name them."""
    feature = op.get("feature")
    names = feature if isinstance(feature, list) else [feature]
    if not names or any(not isinstance(n, str) or n in {"", UNKNOWN} for n in names):
        return None
    return set(names)


def _top_cut(op, names, top_feature):
    """The feature through which face op ``op`` cuts the stock top: the stock's
    ``top_feature`` when the op names it, else (no top feature: every face op is the
    top's) the op's single feature, else None; False when it does not face the top and
    UNKNOWN when the top's feature is unresolved."""
    if op.get("do") not in FACING:
        return False
    if top_feature in {"", UNKNOWN}:
        return UNKNOWN
    if top_feature is not None:
        return top_feature if top_feature in names else False
    return min(names) if len(names) == 1 else None


def _rectangle(bundle, setup, target):
    """(rectangle, land) when ``target``'s surface is known to fill its setup-frame X/Y
    footprint (:func:`_setup_footprint`), else None: the X/Y rectangle it is known to hold
    surface over and :data:`TOUCH_LAND_MM`, both in plan units. The evidence is the
    kernel's one STEP face for it (``faces``): a plane that fills its own box
    (``fills_bbox``: one wire, every edge a straight segment within the kernel's side
    tolerance of a side of the box, and more area than that band along its sides), flat in
    setup Z, with each corner of the box on a corner of its setup X/Y box, which is the
    footprint. The rectangle is that box less :data:`FILL_MARGIN_MM` and the corner
    tolerance on every side, where a notch may still run. Without a kernel result, or for
    a face set of other than one face, a round, holed, notched or L-shaped face, or one
    turned against the setup axes, the box's corners may hold no surface at all, however
    little area the face lacks."""
    from ..coordinates import frame_point

    footprint = _setup_footprint(bundle, setup, target)
    kernel, refs = mapping(getattr(bundle, "kernel", None)), records(target.get("faces"))
    scale = {"mm": 1.0, "in": 25.4}.get(bundle.features.get("units"))
    if footprint is None or kernel.get("status") != "ok" or len(refs) != 1 or scale is None:
        return None
    index = mapping(kernel.get("mapping")).get(refs[0])
    faces = [mapping(f) for f in records(kernel.get("faces"))]
    face = next((f for f in faces if index is not None and f.get("index") == index), {})
    box = face.get("bbox_mm")
    if not (
        face.get("kind") == "Plane"
        and face.get("fills_bbox") is True
        and isinstance(box, list)
        and len(box) == 6
        and all(number(v) for v in box)
    ):
        return None
    frame = setup_frame(bundle, setup)
    ends = [[box[i] / scale, box[i + 3] / scale] for i in range(3)]
    corners = [frame_point(list(p), frame) for p in product(*ends)]
    if not all(number(v) for p in corners for v in p):
        return None
    spans = [[min(p[i] for p in corners), max(p[i] for p in corners)] for i in range(3)]
    tolerance = LENGTH_TOLERANCE_MM
    square = all(min(abs(p[i] - v) for v in spans[i]) <= tolerance for p in corners for i in (0, 1))
    same = all(
        abs(a - b) <= tolerance
        for span, side in zip(spans[:2], footprint, strict=True)
        for a, b in zip(span, side, strict=True)
    )
    if spans[2][1] - spans[2][0] > tolerance or not square or not same:
        return None
    margin = FILL_MARGIN_MM / scale + tolerance
    return [[low + margin, high - margin] for low, high in spans[:2]], TOUCH_LAND_MM / scale


def _uncut(rectangle, land, regions):
    """Whether a ``land`` by ``land`` square of X/Y ``rectangle`` lies outside every X/Y
    region (it may touch one). Such a square's low corner lies in the rectangle less
    ``land`` at its high ends, and overlaps a region when strictly inside it grown by
    ``land`` at its low ends. The free corners, if any, include a crossing or midpoint of
    the lines through all these ends."""
    lows = [(low, high - land) for low, high in rectangle]
    grown = [[(r[axis][0] - land, r[axis][1]) for axis in (0, 1)] for r in regions]
    lines = []
    for axis, (low, high) in enumerate(lows):
        if high < low:
            return False
        ends = sorted({low, high, *(v for g in grown for v in g[axis] if low < v < high)})
        lines.append({*ends, *((a + b) / 2 for a, b in pairwise(ends))})
    return any(
        not any(g[0][0] < x < g[0][1] and g[1][0] < y < g[1][1] for g in grown)
        for x in lines[0]
        for y in lines[1]
    )


def _cuts(bundle, setup, event, states, start, end):
    """(state, scars) of a touched or faced Z surface over ops ``start`` to ``end``.

    State is False once one of these ops cut it whole (:func:`cut_coverage`; the stock
    top: faced the top feature) to another or no stated Z, or cut it other than by
    facing/pocketing; None (unknown) when the surface is unnamed, an op cut a feature
    the plan (or the stock's top feature) does not name, or a coverage is unknown; else
    True. Scars are the (feature, X/Y region) of each op that cut only part of it."""
    features = mapping(bundle.feature_definitions)
    top_feature = mapping(setup.get("stock_state")).get("top_feature")
    gone, unproven, scars = False, event["face"] in {None, "", UNKNOWN}, []
    for op, _, _ in states[start:end]:
        action = op.get("do")
        if action in MANUAL:
            continue
        names = _features(op)
        if names is None:
            unproven = True
            continue
        cut = event["face"] if event["face"] in names else False
        if cut is False and event["top"]:
            cut = _top_cut(op, names, top_feature)
        if cut is False:
            continue
        if cut == UNKNOWN:
            unproven = True
            continue
        to_z = op.get("to_z")
        if action in FACING | POCKETING and number(to_z) and number(event["z"]):
            if abs(to_z - event["z"]) <= LENGTH_TOLERANCE_MM:
                continue
        coverage = cut_coverage(bundle, setup, op, mapping(features.get(cut)))
        if coverage == "partial":
            scars.append((cut, cut_region(op)))
        gone |= coverage == "whole"
        unproven |= coverage not in {"whole", "partial"}
    return (False if gone else None if unproven else True), scars


def _standing(bundle, setup, event, states, index):
    """Whether a touched or faced Z surface still stands at op ``index``.

    The surface is tracked across the ops since the event (:func:`_cuts`). A touch
    carries what the ops since its surface was made left of it: not ``proven`` when
    those ops may have cut it away, and their partial cuts as ``scars``. Ops that each
    cut only part of it, before or since the event, leave it at its uncut Z only while
    a square land of the rectangle it is known to hold (:func:`_rectangle`) lies outside
    all of their regions (:func:`_uncut`); else, or with more than one feature named for
    it, None (unknown)."""
    state, scars = _cuts(bundle, setup, event, states, event["index"], index)
    # A touch does not prove what cuts before it left of its surface.
    state = state if event["proven"] or state is False else None
    scars = event["scars"] + scars
    if scars and state:
        names = {name for name, _ in scars}
        target = mapping(mapping(bundle.feature_definitions).get(min(names)))
        held = _rectangle(bundle, setup, target)
        if len(names) > 1 or held is None or not _uncut(*held, [r for _, r in scars]):
            return None
    return state


def _tops(bundle, setup, states):
    """(Z, made) of the stock top before each op and after the last: the incoming top
    (made before op 0), then each face op that wholly cuts the top feature makes a new
    top at its ``to_z``; Z unknown when that top states no Z or is not proven still to
    stand (:func:`_standing`)."""
    stock = mapping(setup.get("stock_state"))
    features = mapping(bundle.feature_definitions)
    z = stock.get("top_z", UNKNOWN)
    track = {"index": 0, "face": "top", "z": z, "top": True, "scars": [], "proven": True}
    tops = []
    for index in range(len(states) + 1):
        standing = _standing(bundle, setup, track, states, index) is True
        tops.append((track["z"] if number(track["z"]) and standing else UNKNOWN, track["index"]))
        op = states[index][0] if index < len(states) else {}
        names = _features(op)
        cut = _top_cut(op, names, stock.get("top_feature")) if names else False
        if cut not in {False, UNKNOWN}:
            if cut_coverage(bundle, setup, op, mapping(features.get(cut))) == "whole":
                z = op.get("to_z") if number(op.get("to_z")) else UNKNOWN
                track = {**track, "index": index + 1, "z": z}
    return tops


def _turned_standing(event, states, index):
    """A diameter turned before op ``event["index"]`` stands at op ``index`` unless an op
    since cut that feature other than by turning it, or cut a feature the plan does not
    name."""
    for op, _, _ in states[event["index"] : index]:
        if op.get("do") in MANUAL:
            continue
        names = _features(op)
        if names is None or (event["x_face"] in names and op.get("do") not in TURNED):
            return False
    return True


def _named(value):
    return isinstance(value, str) and value.strip() not in {"", UNKNOWN}


def x_face_state(bundle, setup, touch, x_recipe, states, index):
    """(status, reason) of the diameter an authored lathe X touch measures, at op
    ``index`` (D2: the zero is set on the surface actually touched; unknown is not pass).

    A touch that trial-cuts (``x_method = "trial_cut_measure"``) makes its own diameter.
    ``x_face = "x_zero"`` is this setup's X-zero trial-cut land: it needs a trial-cut X
    zero made before the touch and stands until a cutting op runs after the zero, when
    whether that cut took it is unknown (the land is no plan feature to follow). Any other
    ``x_face`` is a plan feature: the latest op naming it before the touch (this setup,
    then the earlier setups of its stock lineage) must turn it, or it must be supplied
    as-is and never cut; an op naming no feature since leaves it unknown, and so does a
    feature turned only upstream of an undeclared stock route. Without ``x_face`` the
    words name no surface the rule can follow: unknown."""
    if touch.get("x_method") == "trial_cut_measure":
        return "pass", None
    face = touch.get("x_face")
    if not _named(face):
        return UNKNOWN, "names no x_face"
    if face == "x_zero":
        ops = [op for op, _, _ in states]
        made = _position(ops, {"after_op": x_recipe.get("after_op")}) or 0
        if x_recipe.get("method") != "trial_cut_measure":
            return "error", "touches the X zero's trial-cut land, but the X zero cuts none"
        if index < made:
            return "error", "touches the X zero's trial-cut land before the zero cuts it"
        cut = next((op for op in ops[made:index] if op.get("do") not in MANUAL), None)
        if cut is not None:
            return UNKNOWN, f"touches the X zero's trial-cut land after op {cut['op']} cut"
        return "pass", None
    if face not in mapping(bundle.feature_definitions):
        return "error", f"names x_face {face}, no plan feature"
    lineage = setup_lineage(bundle.plan, setup["id"])
    earlier = [
        (other["id"], op)
        for other in bundle.plan["setups"]
        if other["id"] in lineage - {setup["id"]}
        for op in records(other.get("ops"))
    ]
    history = earlier + [(setup["id"], op) for op, _, _ in states[:index]]
    for owner, op in reversed(history):
        if op.get("do") in MANUAL:
            continue
        names = _features(op)
        where = f"{owner} op {op.get('op')}"
        if names is None:
            return UNKNOWN, f"touches {face} after {where}, which names no feature"
        if face in names:
            if op.get("do") in TURNED:
                return "pass", None
            return "error", f"touches {face} after {where} cut it other than by turning"
    faces = mapping(bundle.feature_definitions.get(face)).get("faces", UNKNOWN)
    as_is = mapping(bundle.plan.get("stock")).get("as_is_faces", UNKNOWN)
    if known_refs(faces) and isinstance(as_is, list) and set(faces) <= set(as_is):
        return "pass", None
    if not all("stock_in" in other for other in bundle.plan["setups"] if other["id"] in lineage):
        return UNKNOWN, f"touches {face}, whose turning upstream is not routed to this setup"
    return "error", f"touches {face} before any op turns it"
