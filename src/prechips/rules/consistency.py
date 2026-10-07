"""One fact, one source: plan text must not restate a fact the traveler derives from a
field, nor contradict one it names.

The traveler prints these facts from one source each: the TOOLS table's tool numbers
(``resolution.tool_numbers``) and flute counts, the clamp order's tightening (``tighten`` /
``torque_nm``), the DRO ZERO's kept clamping (``zero.transfer.keep_clamped``), the HOLD's
jaw tops and work-top height above them (``resolution.jaw_top_z``) and the op row's GO /
NO-GO sizes. The rule reads exactly the token patterns below; any other text makes no
claim (never an error, never a pass).

Restated, an error wherever the pattern occurs (negation, time, tolerance and subject do
not matter: the fact has one source, and the text may only leave it to that source):

* ``same chucking`` in a setup's hold, clamp, stock, setup or zero text: the chucking is the
  HOLD's, and keeping it from the transfer's setup is ``zero.transfer.keep_clamped``;
* ``hand tight`` / ``hand-tighten[ed|ing]`` / ``tighten[ed|ing] by hand`` / ``finger tight``
  in the note of a clamp on ``clamp_order``: the HOLD prints its tightening;
* ``N mm|in above|below the [vise] jaw[s] | jaw top[s]`` in the setup or op text of a hold
  with ``jaw_above_parallels_mm``: the jaw tops are derived from the seated bottom and that
  field.

Compared. A ``T<n>`` in a setup's or op's text names that setup's TOOLS row:

* ``T<n>`` as a word of its own (not in ``6061-T6``, not before a decimal point or a
  hyphen, not a plan frame's name): on this setup's TOOLS table;
* a flute count in digits (any integer) bound to one tool number, ``2-flute T1``,
  ``T1 (2-flute …)`` or ``T1, the 2fl …``: the tool's inventory ``flutes``;
* on an op with a GO / NO-GO pair, an un-negated inspection clause (sentences split at
  ``; ! ?`` and full stops, clauses at ``, :`` too; parenthesised text dropped) that starts
  with push / pass / run / slide (after and / then / now / next / finally / so / but) and
  sends ``the NO-GO [plug]``, ``the GO and NO-GO plugs``, ``each / every / both / all
  [the] plug(s)`` or ``the plugs`` through: contradicts the pair.

Two checks need no prose: ``tighten = "hand"`` with a ``torque_nm``, and ``stock_state``
against the kernel's setup-entry stock, each height judged by the one evidence source its
declaration names, never another in its place. A ``top_z`` / ``bottom_z`` whose
``top_feature`` / ``bottom_feature`` names a feature is judged by the kernel's height of that
feature's +Z / -Z face alone: the stock over (under) it while it is uncut, else the face,
within its band; a face the kernel did not measure leaves it unknown. Otherwise the stock
box gives only the highest and lowest points: ``top_z`` is the highest (under an
``"unknown"`` ``top_feature`` only bounded by it), and the lower of an unnamed ``bottom_z``
and ``retained_rail_bottom_z`` the lowest. A named seat proves only its own face: the box
still shows whether stock other than that measured face reaches below every authored point.
A compared fact whose field, inventory value, plan units, band or kernel value is missing or
unknown, or that the kernel cannot prove, is ``unknown``, never ``pass``.
"""

from __future__ import annotations

import re

from prechips.clamp_labels import clamp_labels
from prechips.findings import Finding
from prechips.rules.level_entry import STOCK_TOL_MM
from prechips.rules.resolution import MANUAL, UNKNOWN, number, record, resolve, tool_numbers

_HOLD_TEXTS = ("stop", "grip_on", "clamp", "locate", "note")
_ZERO_TEXTS = frozenset({"edge", "face", "method", "measure", "x_method", "note", "recovery"})
_SENTENCE = re.compile(r"[;!?]|\.(?!\d)")
_COMMA = re.compile(r"[,:]")
_NEGATION = re.compile(
    r"\b(?:not|never|cannot|without|unlike|instead)\b|\bno\b(?![- ]?go\b)|n't\b", re.I
)
_SAME_CHUCKING = re.compile(r"\bsame\s+chucking\b", re.I)
_HAND = re.compile(
    r"\bhand[- ]tight(?:en(?:ed|ing)?)?\b|\btighten(?:ed|ing)?\s+by\s+hand\b"
    r"|\bfinger[- ]tight\b",
    re.I,
)
_JAW_HEIGHT = re.compile(
    r"(?<![\w.])\d+(?:\.\d+)?\s*(?:mm|in)\s+(?:above|below)\s+the\s+(?:vise\s+)?"
    r"(?:jaw\s+tops?|jaws?)\b",
    re.I,
)
_TOOL = re.compile(r"(?<![\w\-/.])T(\d+)\b(?![.,]\d|-)")
_COUNT = r"(?<![\w.])(\d+)[- ]?(?:fl|flutes?|fluted)\b"
_FLUTES_BEFORE = re.compile(_COUNT + r"\s+$", re.I)
_FLUTES_AFTER = re.compile(r"(?:\s*\(\s*|,\s+(?:the|a|an)\s+)" + _COUNT, re.I)
_PLUGS = r"(?:plugs?|pins?|gauges?)"
_NO_GO_PLUGS = (
    rf"(?:the\s+)?(?:drawing\s+|shop\s+)?(?:GO\s+(?:and|&)\s+)?NO[- ]?GO(?:\s+{_PLUGS})?",
    rf"(?:both|each|every|all)(?:\s+of)?(?:\s+the)?(?:\s+(?:two|drawing|shop))?\s+{_PLUGS}",
    r"the(?:\s+(?:two|drawing|shop))?\s+(?:plugs|pins|gauges)",
)
_THROUGH = re.compile(
    r"\s*(?:(?:and|then|now|next|finally|so|but)\s+)*(?:push|pass|run|slide)\s+(?:"
    + "|".join(_NO_GO_PLUGS)
    + r")(?:\s+[\w-]+){0,4}?\s+through\b",
    re.I,
)


def _texts(value):
    """The strings of a text field: one string, or a list of procedure steps."""
    if isinstance(value, str):
        return [value]
    return [v for v in value if isinstance(v, str)] if isinstance(value, list) else []


def _zero_texts(value):
    """The printed text fields of a setup's zero (axes, tool touches, transfer)."""
    if isinstance(value, dict):
        return [
            text
            for key, item in value.items()
            for text in (_texts(item) if key in _ZERO_TEXTS else _zero_texts(item))
        ]
    if isinstance(value, list):
        return [text for item in value for text in _zero_texts(item)]
    return []


def _pieces(pattern, text, start, end):
    """``(start, end)`` of the pieces of ``text[start:end]`` between ``pattern``'s matches."""
    for stop in pattern.finditer(text, start, end):
        yield start, stop.start()
        start = stop.end()
    yield start, end


def _clauses(text):
    """``(start, sentence, clause)`` for each clause of ``text``: sentences split at
    ``; ! ?`` and full stops (never a decimal point), clauses at ``, :`` as well."""
    for s, e in _pieces(_SENTENCE, text, 0, len(text)):
        for start, end in _pieces(_COMMA, text, s, e):
            yield start, text[s:e], text[start:end]


def _clamp_label(hold, index):
    labels = clamp_labels(hold)
    return labels[index - 1] if 0 < index <= len(labels) else f"clamp {index}"


def _restated_chucking(texts):
    """``same chucking`` anywhere in the setup's text: the HOLD and ``keep_clamped`` say it."""
    found = [
        f'the text restates the chucking ("{clause.strip()}"): the HOLD prints the work '
        "holding, and the DRO ZERO whether the work stays clamped from the transfer's setup "
        "(zero.transfer.keep_clamped), so set that field and drop the restatement"
        for text in texts
        for _, _, clause in _clauses(text)
        if _SAME_CHUCKING.search(clause)
    ]
    return len(found), found, []


def _hand_tight(hold):
    """Hand tightening restated in an ordered clamp's note, and a hand-tight clamp with a
    torque."""
    clamps = hold.get("clamps") if isinstance(hold.get("clamps"), list) else []
    order = hold.get("clamp_order")
    steps = dict.fromkeys(
        i
        for i in (order if isinstance(order, list) else [])
        if isinstance(i, int) and not isinstance(i, bool) and 1 <= i <= len(clamps)
    )
    found = [
        f'{_clamp_label(hold, i)}: its note restates its tightening ("{match.group(0)}"), but '
        "the HOLD prints the tightening from the clamp's tighten / torque_nm, so set the "
        "field and drop the restatement"
        for i in steps
        for text in _texts(record(clamps[i - 1]).get("note"))
        for match in _HAND.finditer(text)
    ]
    claims = len(found)
    for i, clamp in enumerate(clamps, 1):
        clamp = record(clamp)
        if clamp.get("tighten") == "hand" and number(clamp.get("torque_nm")):
            claims += 1
            found.append(
                f'{_clamp_label(hold, i)}: tighten = "hand" and torque_nm '
                f"{clamp['torque_nm']:g} are both set; a hand-tight clamp takes no torque"
            )
    return claims, found, []


def _incomplete(bundle, setup):
    """Whether a cutting op the TOOLS table would number has no tool chosen yet."""
    lathe = record(resolve(bundle, "machines", setup.get("machine"))).get("kind") == "lathe"
    setups = [
        s
        for s in bundle.plan.get("setups", [])
        if s is setup or (lathe and s.get("machine") == setup.get("machine"))
    ]
    return any(
        op.get("do") not in MANUAL and op.get("tool") in (None, UNKNOWN)
        for s in setups
        for op in s.get("ops", [])
    )


def _tool_claims(bundle, setup, texts, frames):
    """Tool numbers, and a flute count bound to one, against the setup's TOOLS table."""
    numbers = tool_numbers(bundle, setup)
    by_label = {label: key for key, label in numbers.items()}
    listed = ", ".join(sorted(by_label, key=lambda label: int(label[1:]))) or "no tools"
    claims, found, unchecked = 0, [], []
    for text in texts:
        for match in _TOOL.finditer(text):
            label = match.group(0)
            if label in frames:
                continue  # A frame of the same name: the text may mean either.
            claims += 1
            if label not in by_label:
                if _incomplete(bundle, setup):
                    unchecked.append(f"{label}: an op's tool is not chosen, so TOOLS is open")
                else:
                    found.append(f"the text names {label}, but this setup's TOOLS has {listed}")
                continue
            bound = [
                int(m.group(1))
                for m in (
                    _FLUTES_BEFORE.search(text[: match.start()]),
                    _FLUTES_AFTER.match(text, match.end()),
                )
                if m
            ]
            reference = by_label[label][0]
            actual = record(resolve(bundle, "tools", reference)).get("flutes")
            for flutes in bound:
                if not (isinstance(actual, int) and not isinstance(actual, bool)):
                    unchecked.append(f"{label} ({reference}) has no inventory flute count")
                elif actual != flutes:
                    found.append(
                        f"the text calls {label} {flutes}-flute, but the TOOLS table's {label} "
                        f"({reference}) has {actual} flutes"
                    )
    return claims, found, unchecked


def _restated_jaw_heights(hold, texts):
    """A height from the jaw tops in a hold whose jaw tops the HOLD derives."""
    if record(hold).get("jaw_above_parallels_mm") is None:
        return 0, [], []
    found = [
        f'the text gives a height from the jaw tops ("{match.group(0)}"), but the jaw tops '
        "are derived from the seated stock bottom and jaw_above_parallels_mm, and the HOLD "
        "prints the work top above them; give other heights as Z values and drop the "
        "restatement"
        for text in texts
        for match in _JAW_HEIGHT.finditer(text)
    ]
    return len(found), found, []


_NAMED = {"top_z": ("top_feature", "up"), "bottom_z": ("bottom_feature", "down")}


def _named_faces(state, authored, faces):
    """``{field: {name, face, stock} | {name, reason}}`` for each authored ``top_z`` /
    ``bottom_z`` whose ``top_feature`` / ``bottom_feature`` names a feature: the kernel's
    mm Z of that feature's +Z / -Z face and of the entering stock over / under it."""
    named = {}
    for field, (key, side) in _NAMED.items():
        name = state.get(key)
        if field not in authored or not isinstance(name, str) or name in ("", UNKNOWN):
            continue
        measured = record(faces.get(name))
        height = record(measured.get(side))
        if number(height.get("face_z")) and number(height.get("stock_z")):
            named[field] = {"name": name, "face": height["face_z"], "stock": height["stock_z"]}
        else:
            reason = measured.get("reason") or height.get("reason") or "no height given"
            named[field] = {"name": name, "reason": reason}
    return named


def _band(bundle, name, faces, scale):
    """(requirement, low, high, nominal) in mm when ``name``'s one requirement band is the
    separation of its two horizontal faces: the kernel puts its +Z and -Z faces the
    requirement's nominal apart, so a thicker feature moves each face outward. Else None."""
    feature = record(bundle.feature_definitions.get(name))
    requirements = feature.get("requirements")
    if not (isinstance(requirements, list) and len(requirements) == 1):
        return None
    (requirement,) = requirements
    band, nominal = feature.get(requirement), feature.get(f"{requirement}_nominal")
    if not (
        isinstance(band, list)
        and len(band) == 2
        and all(map(number, (*band, nominal)))
        and band[0] <= band[1]
    ):
        return None
    up, down = (record(record(faces.get(name)).get(side)).get("face_z") for side in ("up", "down"))
    if not (number(up) and number(down)) or abs(up - down - nominal * scale) > STOCK_TOL_MM:
        return None
    return requirement, band[0] * scale, band[1] * scale, nominal * scale


def _face_heights(bundle, authored, named, faces, scale):
    """Found and unchecked for the measured named faces. Still under raw stock, a face's
    height is the stock's over (under) it. Cut, it may sit off its CAD Z only as far as its
    feature's band lets the feature grow outward or shrink (:func:`_band`), the other face
    held at its CAD Z. With both faces of one feature cut, their authored separation is the
    band's, and each face may move only as far as the other's own range allows: the band's
    span. A cut face off its CAD Z without such a band is unknown."""
    found, unchecked = [], []
    measured = {field: face for field, face in named.items() if "face" in face}
    cut = {f for f, face in measured.items() if abs(face["stock"] - face["face"]) <= STOCK_TOL_MM}

    def said(field):
        face = measured[field]
        return (
            f"stock_state.{field} {authored[field]:g} is {_NAMED[field][0]} {face['name']}'s "
            f"face, which the kernel finishes at Z {face['face'] / scale:.4f}"
        )

    for field in sorted(set(measured) - cut):
        face = measured[field]
        if abs(authored[field] * scale - face["stock"]) > STOCK_TOL_MM:
            where = "over" if field == "top_z" else "under"
            found.append(
                f"{said(field)}; uncut, the setup-entry stock {where} it is at "
                f"Z {face['stock'] / scale:.4f}"
            )
    pair = cut == {"top_z", "bottom_z"} and len({measured[f]["name"] for f in cut}) == 1
    if pair:
        name = measured["top_z"]["name"]
        band = _band(bundle, name, faces, scale)
        apart = (authored["top_z"] - authored["bottom_z"]) * scale
        if band is not None and not band[1] - STOCK_TOL_MM <= apart <= band[2] + STOCK_TOL_MM:
            found.append(
                f"stock_state.top_z {authored['top_z']:g} and bottom_z {authored['bottom_z']:g} "
                f"are {name}'s two cut faces, {apart / scale:g} apart, outside its {band[0]} "
                f"band {band[1] / scale:g}-{band[2] / scale:g}"
            )
    for field in sorted(cut):
        face = measured[field]
        off = authored[field] * scale - face["face"]
        if abs(off) <= STOCK_TOL_MM:
            continue
        band = _band(bundle, face["name"], faces, scale)
        if band is None:
            unchecked.append(
                f"{said(field)}; no band of {face['name']} is proved to be its faces' "
                "separation, so the departure is not judged"
            )
            continue
        requirement, low, high, nominal = band
        # Outward is growth: the feature thickens by it on this face's side.
        grows = off if field == "top_z" else -off
        least, most = (low - high, high - low) if pair else (low - nominal, high - nominal)
        if not least - STOCK_TOL_MM <= grows <= most + STOCK_TOL_MM:
            lowest, highest = (
                (face["face"] + least, face["face"] + most)
                if field == "top_z"
                else (face["face"] - most, face["face"] - least)
            )
            found.append(
                f"{said(field)}; its {requirement} band {low / scale:g}-{high / scale:g} puts it "
                f"between Z {lowest / scale:.4f} and Z {highest / scale:.4f}"
            )
    return found, unchecked


def _kernel_stock(bundle, setup, scale):
    """``stock_state`` heights against the kernel's setup-entry stock, each by the one
    evidence source its declaration names. A ``top_z`` / ``bottom_z`` whose
    ``top_feature`` / ``bottom_feature`` names a feature is that feature's +Z / -Z face,
    judged by the kernel's height of it alone (:func:`_face_heights`); a face the kernel
    did not measure leaves the height unknown, the box never standing in. Any other
    ``top_z`` is the stock box's highest point, an ``"unknown"`` ``top_feature``'s only
    bounded by it. Any other ``bottom_z`` and ``retained_rail_bottom_z`` are the box's
    lowest point where they are the lowest authored point, else not compared; a rail with
    no ``bottom_z`` is proved only when it is below the stock. A named seat proves only its
    own face: as the lowest authored point it is still wrong when the kernel measures that
    face above the box's lowest point, since stock then hangs below it that nothing
    authored reaches. Where its measured face is the box's lowest point, its face verdict
    alone judges it, a displacement its band permits included; unmeasured, it is unknown."""
    from prechips.kernel import run_geometry

    state = record(setup.get("stock_state"))
    authored = {
        field: state[field]
        for field in ("top_z", "bottom_z", "retained_rail_bottom_z")
        if state.get(field) is not None
    }
    if not authored:
        return 0, [], []
    unset = [f"stock_state.{f} is {v}" for f, v in authored.items() if not number(v)]
    if unset:
        return 0, [], [", ".join(unset) + ", so the authored stock is not compared"]
    if not scale:
        return 0, [], ["the plan units are unknown, so the authored heights have no mm value"]
    kernel = record(run_geometry(bundle))
    if kernel.get("status") != "ok":
        return 0, [], [f"the kernel did not model the stock (status {kernel.get('status')})"]
    facts = record(record(kernel.get("setups")).get(setup["id"]))
    box = facts.get("stock_bbox_mm")
    if not (isinstance(box, list) and len(box) == 6 and all(map(number, box))):
        return 0, [], ["the kernel gave no setup-entry stock box for this setup"]
    faces = record(facts.get("stock_faces_mm"))
    named = _named_faces(state, authored, faces)
    found, unchecked = _face_heights(bundle, authored, named, faces, scale)
    unchecked += [
        f"stock_state.{field} {authored[field]:g} is {_NAMED[field][0]} {face['name']}'s face, "
        f"whose height the kernel did not give ({face['reason']}), so it is not compared"
        for field, face in sorted(named.items())
        if "face" not in face
    ]
    top, feature = authored.get("top_z"), state.get("top_feature")
    if top is not None and "top_z" not in named:
        off = top * scale - box[5]
        message = (
            f"stock_state.top_z {top:g}, but the kernel's setup-entry stock top is at "
            f"Z {box[5] / scale:.4f}"
        )
        if off > STOCK_TOL_MM or (feature in (None, "") and off < -STOCK_TOL_MM):
            found.append(message)
        elif off < -STOCK_TOL_MM:
            unchecked.append(
                f"{message}; top_feature is unknown, so a touched face cannot be told from a "
                "wrong stock top"
            )
    lows = {f: authored[f] for f in ("bottom_z", "retained_rail_bottom_z") if f in authored}
    if not lows:
        return 1, found, unchecked
    lowest = min(lows.values())
    boxed = {field: value for field, value in lows.items() if field not in named}
    for field, value in boxed.items():
        if (value - lowest) * scale > STOCK_TOL_MM:
            unchecked.append(
                f"stock_state.{field} {value:g} is above the lowest authored point, and the "
                "kernel box gives only the stock's lowest point, so it is not compared"
            )
            continue
        off = value * scale - box[2]
        message = (
            f"stock_state.{field} {value:g}, the lowest authored stock point, but the "
            f"kernel's setup-entry stock bottom is at Z {box[2] / scale:.4f}"
        )
        if off < -STOCK_TOL_MM or (off > STOCK_TOL_MM and "bottom_z" in lows):
            found.append(message)
        elif "bottom_z" not in lows:
            unchecked.append(
                f"stock_state.retained_rail_bottom_z {value:g} with no bottom_z: the kernel's "
                f"stock bottom (Z {box[2] / scale:.4f}) may be the seat's, so the rail is not "
                "compared"
            )
    seat_lowest = not any((value - lowest) * scale <= STOCK_TOL_MM for value in boxed.values())
    seat = named.get("bottom_z", {})
    if (
        seat_lowest
        and "stock" in seat
        and min(lowest * scale, seat["stock"]) - box[2] > STOCK_TOL_MM
    ):
        found.append(
            f"stock_state.bottom_z {lowest:g}, bottom_feature {seat['name']}'s face, is the "
            f"lowest authored stock point; the kernel puts the stock under that face at "
            f"Z {seat['stock'] / scale:.4f}, but its setup-entry stock reaches "
            f"Z {box[2] / scale:.4f} below it, and no authored point does"
        )
    return 1, found, unchecked


def _no_go(op):
    """Inspection text that sends a NO-GO plug through an op checked by GO / NO-GO plugs."""
    pairs = {
        req: pair.get("no_go")
        for req, pair in record(op.get("go_no_go")).items()
        if isinstance(pair, dict) and "no_go" in pair
    }
    for hold in op.get("process_holds") or []:
        pair = record(record(hold).get("go_no_go"))
        if "no_go" in pair:
            pairs.setdefault(hold.get("requirement"), pair["no_go"])
    methods = record(op.get("inspection_methods"))
    sources = [(req, t) for req in pairs for t in _texts(methods.get(req))]
    if len(pairs) == 1:
        (req,) = pairs
        sources += [(req, t) for key in ("inspection_note", "note") for t in _texts(op.get(key))]
    found = []
    for req, text in sources:
        for _, _, clause in _clauses(re.sub(r"\([^()]*\)", " ", text)):
            if _THROUGH.match(clause) and not _NEGATION.search(clause):
                size = f" {pairs[req]:g}" if number(pairs[req]) else ""
                found.append(
                    f"the {req} inspection text passes the NO-GO plug through "
                    f'("{clause.strip()}"), but the go/no-go check\'s NO-GO{size} must not enter'
                )
                break
    return len(found), found, []


def _finding(subject, checks, cite):
    claims = sum(c for c, _, _ in checks)
    found = [f for _, fs, _ in checks for f in fs]
    unchecked = [u for _, _, us in checks for u in us]
    status = (
        "error" if found else "unknown" if unchecked else "pass" if claims else "not_applicable"
    )
    if found:
        sentence = (
            "Plan text conflicts with the one source of a fact: "
            + "; ".join(found)
            + ". Correct the text or the field."
        )
    elif unchecked:
        sentence = "A stated fact cannot be compared: " + "; ".join(unchecked) + "."
    elif claims:
        sentence = "Every fact this rule reads agrees with its one source."
    else:
        sentence = "No plan text here restates a structured fact in a form this rule reads."
    numbers = {"claims": claims, "contradictions": found, "unchecked": unchecked}
    return Finding("consistency", subject, status, numbers, cite, sentence)


def evaluate(bundle):
    scale = {"mm": 1.0, "in": 25.4}.get(bundle.features.get("units"))
    frames = set(record(bundle.plan.get("frames")))
    result = []
    for setup in bundle.plan.get("setups", []):
        sid = setup["id"]
        hold = record(setup.get("hold"))
        setup_texts = (
            [t for key in _HOLD_TEXTS for t in _texts(hold.get(key))]
            + [t for clamp in hold.get("clamps") or [] for t in _texts(record(clamp).get("note"))]
            + _texts(setup.get("note"))
            + _texts(record(setup.get("stock_state")).get("note"))
            + _zero_texts(setup.get("zero"))
        )
        checks = [
            _restated_chucking(setup_texts),
            _hand_tight(hold),
            _tool_claims(bundle, setup, setup_texts, frames),
            _restated_jaw_heights(hold, setup_texts),
            _kernel_stock(bundle, setup, scale),
        ]
        result.append(
            _finding(
                sid,
                checks,
                [
                    f"plan setups {sid}: hold, zero, stock_state and notes",
                    "kernel setup-entry stock box",
                ],
            )
        )
        for op in setup.get("ops", []):
            texts = [
                t for key in ("note", "inspection_note", "layout") for t in _texts(op.get(key))
            ] + [t for v in record(op.get("inspection_methods")).values() for t in _texts(v)]
            checks = [
                _tool_claims(bundle, setup, texts, frames),
                _restated_jaw_heights(hold, texts),
                _no_go(op),
            ]
            if any(c or fs or us for c, fs, us in checks):
                result.append(
                    _finding(
                        f"{sid}:{op.get('op')}",
                        checks,
                        [f"plan setups {sid} op {op.get('op')}: note, inspection text, go_no_go"],
                    )
                )
    return result
