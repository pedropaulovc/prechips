"""One fact, one source: printed plan text that restates a structured fact must agree with it.

The traveler prints these facts from one field each, so an author never needs to restate
them: the TOOLS table's tool numbers (``resolution.tool_numbers``) and flute counts, the
clamp order's hand tightening (``tighten = "hand"``), the DRO ZERO's kept clamping
(``zero.transfer.keep_clamped``), the HOLD's work-top height above the jaw tops
(``resolution.jaw_top_z``) and the op row's GO / NO-GO sizes. Prose that restates one is
read only in the forms below, each tied to one field; any other text is not attributed
(no claim, never an error). Sentences split at ``; ! ?`` and full stops (never a decimal
point), clauses at ``, :`` too. "Negated" means not / never / no / cannot / without /
unlike / instead / -n't in the clause; a "time word" (before, after, until, once, when,
while, then, first, initially, now, was, will, if, …) anywhere in the sentence.

* ``T<n>`` as a word of its own (not in ``6061-T6``, not before a decimal point or a
  hyphen, not a plan frame's name): on this setup's TOOLS table;
* a flute count bound to one tool number, ``2-flute T1``, ``T1 (2-flute …)`` or
  ``T1, the 2-flute …``: the tool's inventory ``flutes``;
* an un-negated clause with ``same chucking as <setup>`` naming ``zero.transfer.from``,
  or a clause that is just ``do not / don't / never loosen the [vise | chuck] jaws | work |
  workpiece | part | chuck | vise``, in a sentence with no time word, when the setup has a
  transfer: ``keep_clamped = true``;
* an un-negated ``hand tight[ened]`` / ``tighten[ed] by hand`` / ``finger tight`` in a
  sentence with no time word, in an ordered clamp's note (or in the hold text of a hold
  with one ordered clamp): the clamp's ``tighten = "hand"``;
* an un-negated clause that starts ``[the] [raw] work | workpiece | part | bar | stock |
  blank stands N mm above the [vise] jaws | jaw tops``, in a sentence with no time word and
  with no tolerance or hedge (``±``, ``+/-``, within, about, …) after it: the HOLD's work-top
  height, to the precision written;
* ``Z v, N mm above the [vise] jaw tops`` with no tolerance or hedge after it: v less the
  jaw-top Z;
* an un-negated inspection clause of an op with a GO / NO-GO pair that starts with push /
  pass / run / slide (after and / then / now / next / finally / so / but) and sends ``the
  NO-GO [plug]``, ``the GO and NO-GO plugs``, ``each / every / both / all [the] plug(s)`` or
  ``the plugs`` through (parenthesised text dropped): contradicts the pair.

Two checks need no prose: ``tighten = "hand"`` with a ``torque_nm``, and ``stock_state``
``top_z`` / ``bottom_z`` against the kernel's setup-entry stock box. A claim whose field,
inventory value, plan units or kernel box is missing or unknown is ``unknown``, never
``pass``.
"""

from __future__ import annotations

import re

from prechips.clamp_labels import clamp_labels
from prechips.findings import Finding
from prechips.rules.level_entry import STOCK_TOL_MM
from prechips.rules.resolution import (
    MANUAL,
    UNKNOWN,
    jaw_top_z,
    number,
    record,
    resolve,
    tool_numbers,
)

_HOLD_TEXTS = ("stop", "grip_on", "clamp", "locate", "note")
_ZERO_TEXTS = frozenset({"edge", "face", "method", "measure", "x_method", "note", "recovery"})
_SENTENCE = re.compile(r"[;!?]|\.(?!\d)")
_COMMA = re.compile(r"[,:]")
_NEGATION = re.compile(
    r"\b(?:not|never|cannot|without|unlike|instead)\b|\bno\b(?![- ]?go\b)|n't\b", re.I
)
_WHEN = re.compile(
    r"\b(?:before|after|until|once|when|whenever|while|then|first|initially|originally"
    r"|finally|later|earlier|now|was|were|will|would|if|unless)\b",
    re.I,
)
# A tolerance or hedge just after a stated height: the figure is not a rounded exact value.
_HEDGE = re.compile(
    r"[\s,(]*(?:±|\+/-|\+-|plus or minus|within|give or take|about|approx|roughly|nominal)",
    re.I,
)
_KEPT = re.compile(r"\b(?i:same chucking as)\s+(?:(?i:setup)\s+)?([A-Z]+\d+[A-Z]*)\b")
_KEEP_JAWS = re.compile(
    r"\s*(?:and\s+|but\s+)?(?:do\s+not|don't|never)\s+loosen\s+the\s+(?:vise\s+|chuck\s+)?"
    r"(?:jaws|work|workpiece|part|chuck|vise)\s*",
    re.I,
)
_HAND = re.compile(
    r"\bhand[- ]tight(?:en(?:ed)?)?\b|\btighten(?:ed)? by hand\b|\bfinger[- ]tight\b", re.I
)
_TOOL = re.compile(r"(?<![\w\-/.])T(\d+)\b(?![.,]\d|-)")
_COUNT = r"\b(one|two|three|four|five|six|[1-8])[- ]?(?:fl|flutes?|fluted)\b"
_FLUTES_BEFORE = re.compile(_COUNT + r"\s+$", re.I)
_FLUTES_AFTER = re.compile(r"(?:\s*\(\s*|,\s+(?:the|a|an)\s+)" + _COUNT, re.I)
_FLUTE_WORDS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6}
_NUMBER = r"(\d+(?:\.\d+)?)"
_STANDS = re.compile(
    r"\s*(?:the\s+)?(?:raw\s+)?(?:work|workpiece|part|bar|stock|blank)\s+stands\s+"
    rf"{_NUMBER}\s*mm\s+above\s+the\s+(?:vise\s+)?(?:jaws|jaw\s+tops?)\b",
    re.I,
)
_JAW_TOPS = re.compile(
    rf"\bZ\s*([+\-−]?)\s*{_NUMBER}\s*,\s*{_NUMBER}\s*mm\s+above\s+the\s+(?:vise\s+)?"
    r"jaw\s+tops?\b"
)
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


def _agrees(stated, derived):
    """Whether ``derived`` rounds to the ``stated`` number at the decimals it is written to."""
    decimals = len(stated.partition(".")[2])
    return abs(float(stated) - derived) <= 0.5 * 10**-decimals + 1e-9


def _clamp_label(hold, index):
    labels = clamp_labels(hold)
    return labels[index - 1] if 0 < index <= len(labels) else f"clamp {index}"


def _kept_hold(setup, hold):
    """Hold text that keeps the transfer's chucking, against ``keep_clamped``."""
    transfer = record(record(setup.get("zero")).get("transfer"))
    if not transfer:
        return 0, [], []
    texts = [t for key in _HOLD_TEXTS for t in _texts(hold.get(key))]
    texts += _texts(record(setup.get("stock_state")).get("note"))
    said = []
    for text in texts:
        for _, sentence, clause in _clauses(text):
            if _WHEN.search(sentence):
                continue
            same = _KEPT.search(clause)
            if same and same.group(1) == transfer.get("from") and not _NEGATION.search(clause):
                said.append(same.group(0))
            elif _KEEP_JAWS.fullmatch(clause):
                said.append(clause.strip())
    if not said:
        return 0, [], []
    if transfer.get("keep_clamped") is True:
        return 1, [], []
    return (
        1,
        [
            f'the hold text keeps the work clamped ("{said[0]}"), but zero.transfer has no '
            "keep_clamped = true, so the DRO ZERO says to loosen the work to realign it"
        ],
        [],
    )


def _said_by_hand(texts):
    """The first un-negated hand-tight phrase in a sentence with no time word."""
    for text in texts:
        for _, sentence, clause in _clauses(text):
            match = _HAND.search(clause)
            if match and not (_NEGATION.search(clause) or _WHEN.search(sentence)):
                return match.group(0)
    return None


def _hand_tight(hold):
    """A clamp the text calls hand tight against its ``tighten = "hand"``, and a hand-tight
    clamp with a torque."""
    clamps = hold.get("clamps") if isinstance(hold.get("clamps"), list) else []
    order = hold.get("clamp_order")
    steps = [
        i
        for i in (order if isinstance(order, list) else [])
        if isinstance(i, int) and not isinstance(i, bool) and 1 <= i <= len(clamps)
    ]
    said = {}
    for i in steps:
        phrase = _said_by_hand(_texts(record(clamps[i - 1]).get("note")))
        if phrase:
            said[i] = phrase
    if len(steps) == 1 and steps[0] not in said:
        phrase = _said_by_hand([t for key in _HOLD_TEXTS for t in _texts(hold.get(key))])
        if phrase:
            said[steps[0]] = phrase
    claims, found = len(said), []
    for i, phrase in said.items():
        if record(clamps[i - 1]).get("tighten") != "hand":
            found.append(
                f'{_clamp_label(hold, i)}: the text calls it hand tight ("{phrase}"), but the '
                'clamp has no tighten = "hand", so the clamp order says to tighten it fully'
            )
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
                m.group(1)
                for m in (
                    _FLUTES_BEFORE.search(text[: match.start()]),
                    _FLUTES_AFTER.match(text, match.end()),
                )
                if m
            ]
            reference = by_label[label][0]
            actual = record(resolve(bundle, "tools", reference)).get("flutes")
            for said in bound:
                flutes = _FLUTE_WORDS.get(said.lower()) or int(said)
                if not (isinstance(actual, int) and not isinstance(actual, bool)):
                    unchecked.append(f"{label} ({reference}) has no inventory flute count")
                elif actual != flutes:
                    found.append(
                        f"the text calls {label} {flutes}-flute, but the TOOLS table's {label} "
                        f"({reference}) has {actual} flutes"
                    )
    return claims, found, unchecked


def _jaw_heights(setup, hold, scale):
    """The work's stated height above the jaw tops, and a Z stated above them, against the
    HOLD's jaw-top Z (``resolution.jaw_top_z``)."""
    top = record(setup.get("stock_state")).get("top_z")
    jaw_top = jaw_top_z(setup, hold, scale)
    texts = [t for key in _HOLD_TEXTS for t in _texts(hold.get(key))] + _texts(setup.get("note"))
    missing = "the stock top/bottom, jaw_above_parallels_mm or the plan units are unknown"
    claims, found, unchecked = 0, [], []
    for text in texts:
        for start, sentence, clause in _clauses(text):
            match = _STANDS.match(clause)
            if not match or _WHEN.search(sentence) or _NEGATION.search(clause):
                continue
            if _HEDGE.match(text, start + match.end()):
                continue
            claims += 1
            stated = match.group(1)
            if jaw_top is None or not number(top):
                unchecked.append(f"the work stands {stated} mm above the jaws: {missing}")
                continue
            above = (top - jaw_top) * scale
            if not _agrees(stated, above):
                found.append(
                    f"the text says the work stands {stated} mm above the jaws, but the HOLD's "
                    f"work top is {above:.3f} mm above the jaw tops (stock top less the seated "
                    f"bottom and jaw_above_parallels_mm {hold['jaw_above_parallels_mm']:g})"
                )
        for match in _JAW_TOPS.finditer(text):
            if _HEDGE.match(text, match.end()):
                continue
            claims += 1
            sign, value, stated = match.groups()
            if jaw_top is None:
                unchecked.append(f"Z {sign}{value}, {stated} mm above the jaw tops: {missing}")
                continue
            z = float(value) * (-1 if sign in ("-", "−") else 1)
            if not _agrees(stated, (z - jaw_top) * scale):
                found.append(
                    f"the text puts Z {sign}{value} {stated} mm above the jaw tops, but the jaw "
                    f"tops are at Z {jaw_top:.3f} (seated stock bottom plus "
                    f"jaw_above_parallels_mm), {(z - jaw_top) * scale:.3f} mm below it"
                )
    return claims, found, unchecked


def _kernel_stock(bundle, setup, scale):
    """``top_z`` / ``bottom_z`` against the kernel's setup-entry stock box: the stock's
    highest and lowest points (``retained_rail_bottom_z`` the lowest when lower). A
    ``top_feature``'s ``top_z`` is that touched face, which may stand below a retained raw
    rail: it is only wrong above the whole stock. An unknown ``top_feature`` leaves a top
    below the stock unresolved: it may be a touched face or a wrong stock top."""
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
    box = record(record(kernel.get("setups")).get(setup["id"])).get("stock_bbox_mm")
    if not (isinstance(box, list) and len(box) == 6 and all(map(number, box))):
        return 0, [], ["the kernel gave no setup-entry stock box for this setup"]
    top, bottom = state.get("top_z"), state.get("bottom_z")
    rail = state.get("retained_rail_bottom_z")
    if number(bottom) and number(rail):
        bottom = min(bottom, rail)
    face = state.get("top_feature")
    found, unchecked = [], []
    for field, authored, modelled, end in (
        ("top_z", top, box[5], "top"),
        ("bottom_z", bottom, box[2], "bottom"),
    ):
        if not number(authored):
            continue
        off = authored * scale - modelled
        message = (
            f"stock_state.{field} {authored:g}, but the kernel's setup-entry stock {end} is at "
            f"Z {modelled / scale:.4f}"
        )
        if field == "bottom_z" or face in (None, ""):
            if abs(off) > STOCK_TOL_MM:
                found.append(message)
        elif off > STOCK_TOL_MM:
            found.append(message)
        elif face == UNKNOWN and off < -STOCK_TOL_MM:
            unchecked.append(
                f"{message}; top_feature is unknown, so a touched face cannot be told from "
                "a wrong stock top"
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
            "Plan text contradicts the field it names: "
            + "; ".join(found)
            + ". Correct one of them."
        )
    elif unchecked:
        sentence = "Plan text names a fact that cannot be compared: " + "; ".join(unchecked) + "."
    elif claims:
        sentence = "Every attributed fact in the plan text agrees with its field."
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
            _kept_hold(setup, hold),
            _hand_tight(hold),
            _tool_claims(bundle, setup, setup_texts, frames),
            _jaw_heights(setup, hold, scale),
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
            checks = [_tool_claims(bundle, setup, texts, frames), _no_go(op)]
            if any(c or fs or us for c, fs, us in checks):
                result.append(
                    _finding(
                        f"{sid}:{op.get('op')}",
                        checks,
                        [f"plan setups {sid} op {op.get('op')}: note, inspection text, go_no_go"],
                    )
                )
    return result
