"""One fact, one source: printed plan text that names a structured fact must agree with it.

The traveler prints some facts twice: once from a plan field (or the kernel) and once in
the author's free text beside it. Each check here reads one narrow phrase it can tie to
one field and errors when the two disagree:

* a hold that says the work stays clamped (``same chucking``, ``do not loosen``) against
  ``zero.transfer.keep_clamped``, without which the DRO ZERO says to loosen and re-clamp;
* a clamp called hand tight against its ``tighten = "hand"``, without which the clamp
  order says to tighten it fully (and a hand-tight clamp with a ``torque_nm``);
* a tool number (``T3``), and the flute count said beside it, against the setup's TOOLS
  table (``resolution.tool_numbers``) and the tool's inventory ``flutes``;
* ``stands N mm above the jaws`` and ``Z v, N mm above the jaw tops`` against the stock
  heights and ``jaw_above_parallels_mm``, to the precision the text states;
* ``stock_state`` ``top_z`` / ``bottom_z`` against the kernel's setup-entry stock box;
* inspection text that passes a NO-GO plug through against the op's ``go_no_go`` pair.

Parsing is conservative: text a check cannot tie to exactly one field is not checked,
never an error. A setup or op with nothing checkable is ``not_applicable``.
"""

from __future__ import annotations

import re

from prechips.clamp_labels import clamp_labels
from prechips.findings import Finding
from prechips.rules.level_entry import STOCK_TOL_MM
from prechips.rules.resolution import number, record, resolve, tool_numbers

_HOLD_TEXTS = ("stop", "grip_on", "clamp", "locate", "note")
_ZERO_TEXTS = frozenset({"edge", "face", "method", "measure", "x_method", "note", "recovery"})
_KEPT = re.compile(
    r"\b(?:do not|don't|never) loosen\b|\bwithout loosening\b|\bsame chucking\b"
    r"|\bstays? (?:clamped|chucked)\b",
    re.IGNORECASE,
)
_HAND = re.compile(
    r"\bhand[- ]tight(?:en(?:ed)?)?\b|\btighten(?:ed)? by hand\b|\bfinger[- ]tight\b",
    re.IGNORECASE,
)
_TOOL = re.compile(r"\bT(\d+)\b")
_FLUTES = re.compile(r"\b(two|three|four|six|[2346])[- ]?(?:fl|flutes?)\b", re.IGNORECASE)
_FLUTE_WORDS = {"two": 2, "three": 3, "four": 4, "six": 6}
_NUMBER = r"(\d+(?:\.\d+)?)"
_STANDS = re.compile(
    rf"\bstands\s+{_NUMBER}\s*mm\s+above\s+the\s+(?:vise\s+)?(?:jaws|jaw\s+tops?)\b"
)
_JAW_TOPS = re.compile(
    rf"\bZ\s*([+\-−]?)\s*{_NUMBER}\s*,\s*{_NUMBER}\s*mm\s+above\s+the\s+jaw\s+tops?\b"
)
# Matched within one clause (``_no_go`` splits on ``;`` and sentence stops, not decimals).
_PUSH = r"\b(?:push|pass|run|slide)\b.*"
_THROUGH_ALL = re.compile(
    _PUSH + r"\b(?:each|every|all|both)\b.*\b(?:plugs?|pins?|gauges?)\b.*\bthrough\b",
    re.IGNORECASE,
)
_THROUGH_NO_GO = re.compile(_PUSH + r"\bno-go\b.*\bthrough\b", re.IGNORECASE)
_NEGATED = re.compile(r"\b(?:not|never)\b|n't\b", re.IGNORECASE)


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


def _agrees(stated, derived):
    """Whether ``derived`` rounds to the ``stated`` number at the decimals it is written to."""
    decimals = len(stated.partition(".")[2])
    return abs(float(stated) - derived) <= 0.5 * 10**-decimals + 1e-9


def _clamp_label(hold, index):
    labels = clamp_labels(hold)
    return labels[index - 1] if 0 < index <= len(labels) else f"clamp {index}"


def _kept_hold(setup, hold):
    texts = [t for key in _HOLD_TEXTS for t in _texts(hold.get(key))]
    texts += _texts(record(setup.get("stock_state")).get("note"))
    phrases = [m.group(0) for t in texts for m in [_KEPT.search(t)] if m]
    transfer = record(record(setup.get("zero")).get("transfer"))
    if not (phrases and transfer):
        return 0, []
    if transfer.get("keep_clamped") is True:
        return 1, []
    return 1, [
        f'the hold text says the work stays clamped ("{phrases[0]}"), but zero.transfer '
        "has no keep_clamped = true, so the DRO ZERO says to loosen the work to realign it"
    ]


def _hand_tight(hold):
    clamps = hold.get("clamps") if isinstance(hold.get("clamps"), list) else []
    order = hold.get("clamp_order")
    steps = [
        i
        for i in (order if isinstance(order, list) else [])
        if isinstance(i, int) and 1 <= i <= len(clamps)
    ]
    said = {}
    for i in steps:
        match = next(
            (m for t in _texts(record(clamps[i - 1]).get("note")) for m in [_HAND.search(t)] if m),
            None,
        )
        if match:
            said[i] = match.group(0)
    if len(steps) == 1 and steps[0] not in said:
        match = next(
            (
                m
                for key in _HOLD_TEXTS
                for t in _texts(hold.get(key))
                for m in [_HAND.search(t)]
                if m
            ),
            None,
        )
        if match:
            said[steps[0]] = match.group(0)
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
    return claims, found


def _tool_claims(bundle, texts, numbers, frames):
    """Tool numbers (and a flute count said beside one) in ``texts`` against the setup's
    TOOLS table."""
    by_label = {label: key for key, label in numbers.items()}
    listed = ", ".join(sorted(by_label, key=lambda label: int(label[1:]))) or "no tools"
    claims, found = 0, []
    for text in texts:
        matches = list(_TOOL.finditer(text))
        for k, match in enumerate(matches):
            label = match.group(0)
            if label in frames:
                continue  # A frame of the same name: the text may mean either.
            claims += 1
            if label not in by_label:
                found.append(f"the text names {label}, but this setup's TOOLS table has {listed}")
                continue
            end = matches[k + 1].start() if k + 1 < len(matches) else len(text)
            clause = re.split(r"[;:()]|\.(?!\d)", text[match.end() : end], maxsplit=1)[0]
            said = _FLUTES.findall(clause)
            if len(said) != 1:
                continue
            flutes = _FLUTE_WORDS.get(said[0].lower()) or int(said[0])
            reference = by_label[label][0]
            actual = record(resolve(bundle, "tools", reference)).get("flutes")
            if isinstance(actual, int) and not isinstance(actual, bool) and actual != flutes:
                found.append(
                    f"the text calls {label} {flutes}-flute, but the TOOLS table's {label} "
                    f"({reference}) has {actual} flutes"
                )
    return claims, found


def _jaw_heights(setup, hold, scale):
    state = record(setup.get("stock_state"))
    top, bottom, jaw = state.get("top_z"), state.get("bottom_z"), hold.get("jaw_above_parallels_mm")
    if not (scale and number(top) and number(bottom) and number(jaw)):
        return 0, []
    rail = state.get("retained_rail_bottom_z")
    seated = min(bottom, rail) if number(rail) else bottom
    texts = [t for key in _HOLD_TEXTS for t in _texts(hold.get(key))] + _texts(setup.get("note"))
    claims, found = 0, []
    height = (top - seated) * scale
    for text in texts:
        for match in _STANDS.finditer(text):
            claims += 1
            if not _agrees(match.group(1), height - jaw):
                found.append(
                    f"the text says the work stands {match.group(1)} mm above the jaws, but the "
                    f"stock height {height:.3f} mm less jaw_above_parallels_mm {jaw:g} leaves "
                    f"{height - jaw:.3f} mm"
                )
        for match in _JAW_TOPS.finditer(text):
            claims += 1
            z = float(match.group(2)) * (-1 if match.group(1) in ("-", "−") else 1)
            jaw_top = seated + jaw / scale
            if not _agrees(match.group(3), (z - jaw_top) * scale):
                found.append(
                    f"the text puts Z {match.group(1)}{match.group(2)} {match.group(3)} mm above "
                    f"the jaw tops, but the jaw tops are at Z {jaw_top:.3f} (stock bottom plus "
                    f"jaw_above_parallels_mm), {(z - jaw_top) * scale:.3f} mm below it"
                )
    return claims, found


def _kernel_stock(bundle, setup, scale):
    """``top_z`` / ``bottom_z`` against the kernel's setup-entry stock box: the stock's
    highest and lowest points (``retained_rail_bottom_z`` the lowest when lower). A
    ``top_feature``'s ``top_z`` is that touched face, which may stand below a retained
    raw rail: it is only wrong above the whole stock. Returns the claims, the
    contradictions and why authored heights went uncompared (None when compared)."""
    from prechips.kernel import run_geometry

    state = record(setup.get("stock_state"))
    top, bottom = state.get("top_z"), state.get("bottom_z")
    if not (scale and (number(top) or number(bottom))):
        return 0, [], None
    kernel = record(run_geometry(bundle))
    if kernel.get("status") != "ok":
        return 0, [], f"the kernel did not model the stock (status {kernel.get('status')})"
    box = record(record(kernel.get("setups")).get(setup["id"])).get("stock_bbox_mm")
    if not (isinstance(box, list) and len(box) == 6 and all(map(number, box))):
        return 0, [], "the kernel gave no setup-entry stock box for this setup"
    rail = state.get("retained_rail_bottom_z")
    if number(bottom) and number(rail):
        bottom = min(bottom, rail)
    face = state.get("top_feature") not in (None, "")
    found = []
    for field, authored, modelled, end in (
        ("top_z", top, box[5], "top"),
        ("bottom_z", bottom, box[2], "bottom"),
    ):
        if not number(authored):
            continue
        off = authored * scale - modelled
        if (off > STOCK_TOL_MM) if face and field == "top_z" else abs(off) > STOCK_TOL_MM:
            found.append(
                f"stock_state.{field} {authored:g}, but the kernel's setup-entry stock {end} "
                f"is at Z {modelled / scale:.4f}"
            )
    return 1, found, None


def _no_go(op):
    """Inspection text that passes a NO-GO plug through an op checked by GO / NO-GO plugs."""
    pairs = {
        req: pair["no_go"]
        for req, pair in record(op.get("go_no_go")).items()
        if isinstance(pair, dict) and number(pair.get("no_go"))
    }
    for hold in op.get("process_holds") or []:
        pair = record(record(hold).get("go_no_go"))
        if number(pair.get("no_go")):
            pairs.setdefault(hold.get("requirement"), pair["no_go"])
    if not pairs:
        return 0, []
    methods = record(op.get("inspection_methods"))
    sources = [(req, t) for req in pairs for t in _texts(methods.get(req))]
    if len(pairs) == 1:
        (req,) = pairs
        sources += [(req, t) for key in ("inspection_note", "note") for t in _texts(op.get(key))]
    claims, found = 0, []
    for req, text in sources:
        if "no-go" not in text.lower():
            continue
        claims += 1
        for clause in re.split(r";|\.(?!\d)", text):
            if (
                _THROUGH_ALL.search(clause) or _THROUGH_NO_GO.search(clause)
            ) and not _NEGATED.search(clause):
                found.append(
                    f"the {req} inspection text passes the NO-GO plug through "
                    f'("{clause.strip()}"), but the go/no-go check\'s NO-GO {pairs[req]:g} '
                    "must not enter"
                )
                break
    return claims, found


def _finding(subject, claims, found, cite, unchecked=None):
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
        sentence = f"The authored stock heights are not compared: {unchecked}."
    elif claims:
        sentence = "Every attributable fact in the plan text agrees with its field."
    else:
        sentence = "No plan text here names a structured fact this rule can attribute."
    return Finding(
        "consistency", subject, status, {"claims": claims, "contradictions": found}, cite, sentence
    )


def evaluate(bundle):
    scale = {"mm": 1.0, "in": 25.4}.get(bundle.features.get("units"))
    frames = set(record(bundle.plan.get("frames")))
    result = []
    for setup in bundle.plan.get("setups", []):
        sid = setup["id"]
        hold = record(setup.get("hold"))
        numbers = tool_numbers(bundle, setup)
        setup_texts = (
            [t for key in _HOLD_TEXTS for t in _texts(hold.get(key))]
            + [t for clamp in hold.get("clamps") or [] for t in _texts(record(clamp).get("note"))]
            + _texts(setup.get("note"))
            + _texts(record(setup.get("stock_state")).get("note"))
            + _zero_texts(setup.get("zero"))
        )
        stock_claims, stock_found, unchecked = _kernel_stock(bundle, setup, scale)
        checks = [
            _kept_hold(setup, hold),
            _hand_tight(hold),
            _tool_claims(bundle, setup_texts, numbers, frames),
            _jaw_heights(setup, hold, scale),
            (stock_claims, stock_found),
        ]
        result.append(
            _finding(
                sid,
                sum(c for c, _ in checks),
                [f for _, found in checks for f in found],
                [
                    f"plan setups {sid}: hold, zero, stock_state and notes",
                    "kernel setup-entry stock box",
                ],
                unchecked,
            )
        )
        for op in setup.get("ops", []):
            texts = [
                t for key in ("note", "inspection_note", "layout") for t in _texts(op.get(key))
            ] + [t for v in record(op.get("inspection_methods")).values() for t in _texts(v)]
            checks = [_tool_claims(bundle, texts, numbers, frames), _no_go(op)]
            claims = sum(c for c, _ in checks)
            if claims:
                result.append(
                    _finding(
                        f"{sid}:{op.get('op')}",
                        claims,
                        [f for _, found in checks for f in found],
                        [f"plan setups {sid} op {op.get('op')}: note, inspection text, go_no_go"],
                    )
                )
    return result
