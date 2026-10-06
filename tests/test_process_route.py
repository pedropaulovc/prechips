"""Finishing route, multi-feature inspection, hold stop faces and process holds (PLAN §4.1).

The example plans evolve, so each test first normalizes the state it exercises (strips
authored coating ops, stop faces and process holds) and locates its targets structurally.
"""

import re
import tomllib
from html import unescape

import pytest
from test_cli import SYNTHETIC_KERNEL, copy_examples, traveler

from prechips.inputs import BadInput, load_bundle
from prechips.rules import RULES

HEADER = re.compile(r"\[\[?([A-Za-z_][\w.\-]*)\]\]?\s*(#.*)?\n?")


def evaluate(name, bundle):
    return {row.subject: row for row in next(r for r in RULES if r.name == name).evaluate(bundle)}


def setups(path):
    return tomllib.loads(path.read_text(encoding="utf-8"))["setups"]


def blocks(lines, plan):
    """``("op", sid, op)`` / ``("hold", sid)`` -> [start, end) line span of each table block."""
    spans, current, index, count = {}, None, -1, 0
    for number, line in enumerate([*lines, "[end]\n"]):
        header = HEADER.fullmatch(line)
        if not header:
            continue
        name = header.group(1)
        if current and not name.startswith(f"{current[1]}."):
            spans[current[0]] = (current[2], number)
            current = None
        if line.startswith("[[setups]]"):
            index, count = index + 1, 0
        elif line.startswith("[[setups.ops]]"):
            setup = plan[index]
            current = (("op", setup["id"], setup["ops"][count]["op"]), "setups.ops", number)
            count += 1
        elif line.startswith("[setups.hold]"):
            current = (("hold", plan[index]["id"]), "setups.hold", number)
    return spans


def drop_key(lines, key):
    """Lines without ``key = ...``, including a value continued over several lines."""
    kept, depth = [], 0
    for line in lines:
        if depth or re.match(rf"{key}\s*=", line):
            depth += sum(line.count(c) for c in "[{") - sum(line.count(c) for c in "]}")
            continue
        kept.append(line)
    return kept


def rewrite(path, block, key=None, value=None, remove=False):
    """Set (or clear) ``key`` in one op/hold table block, or remove the block."""
    lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
    start, end = blocks(lines, setups(path))[block]
    body = [] if remove else drop_key(lines[start + 1 : end], key)
    head = [] if remove else [lines[start], *([f"{key} = {value}\n"] if value else [])]
    path.write_text("".join([*lines[:start], *head, *body, *lines[end:]]), encoding="utf-8")


def find_op(path, test):
    return next(
        (setup["id"], op["op"]) for setup in setups(path) for op in setup["ops"] if test(op)
    )


def append_op(path, body):
    """Append an op to the last setup; returns its sheet subject."""
    last = setups(path)[-1]
    number = max(op["op"] for op in last["ops"]) + 10
    text = path.read_text(encoding="utf-8").rstrip("\n")
    path.write_text(f"{text}\n\n[[setups.ops]]\nop = {number}\n{body}", encoding="utf-8")
    return f"{last['id']}:{number}"


def op_rows(html, op):
    return [
        unescape(re.sub(r"<[^>]+>", "|", body))
        for number, body in re.findall(r"<tr><td>(\d+)</td>(.*?)</tr>", html, re.DOTALL)
        if number == str(op)
    ]


# ------------------------------------------------------------------ finishing route


def without_coating(plan):
    while True:
        try:
            sid, op = find_op(plan, lambda op: op["do"] == "coating")
        except StopIteration:
            return
        rewrite(plan, ("op", sid, op), remove=True)


SERVICE = '\n[services.test-oxide-line]\nkind = "outside_process"\nnote = "test vendor"\n'


@pytest.mark.parametrize(
    ("process", "service", "resolves"),
    [
        (None, False, "unknown"),
        ('"test-oxide-line"', False, "error"),
        ('"cutting-oil"', False, "pass"),
        ('"test-oxide-line"', True, "pass"),
        ('["cutting-oil", "test-oxide-line"]', True, "pass"),
    ],
)
def test_a_drawing_finish_needs_a_coating_step_naming_a_resolvable_process(
    tmp_path, process, service, resolves
):
    examples = copy_examples(tmp_path)
    plan = examples / "pivot-shaft" / "plan.toml"
    without_coating(plan)
    # The drawing says "turned, oiled": with no coating step the job cannot read clear.
    assert evaluate("finish_route", load_bundle(plan))["pivot-shaft"].status == "warn"
    subject = append_op(
        plan,
        'do = "coating"\nfeature = "pivot_bearing"\n'
        + (f"process = {process}\n" if process else ""),
    )
    if service:
        inventory = examples / "inventory" / "pedro-shop.toml"
        inventory.write_text(inventory.read_text(encoding="utf-8") + SERVICE, encoding="utf-8")
    bundle = load_bundle(plan)
    assert evaluate("finish_route", bundle)["pivot-shaft"].status == "pass"
    assert evaluate("tool_resolves", bundle)[subject].status == resolves


def test_an_outside_coating_names_the_service_and_what_it_applies(tmp_path):
    examples = copy_examples(tmp_path)
    plan = examples / "pivot-shaft" / "plan.toml"
    without_coating(plan)
    subject = append_op(
        plan, 'do = "coating"\nfeature = "pivot_bearing"\nprocess = "test-oxide-line"\n'
    )
    inventory = examples / "inventory" / "pedro-shop.toml"
    service = SERVICE + 'coating = "hot black oxide, matte"\n'
    inventory.write_text(inventory.read_text(encoding="utf-8") + service, encoding="utf-8")
    _, _, html = traveler(plan, tmp_path / "out", setup=SYNTHETIC_KERNEL)
    (row,) = [row for row in op_rows(html, subject.split(":")[1]) if "coating" in row]
    # The machinist must see what is sent out and to whom, not the item kind.
    assert "outside: test-oxide-line (hot black oxide, matte)" in row


def test_only_a_coating_op_names_a_process(tmp_path):
    plan = copy_examples(tmp_path) / "pivot-shaft" / "plan.toml"
    append_op(plan, 'do = "inspect"\nfeature = "pivot_bearing"\nprocess = "cutting-oil"\n')
    with pytest.raises(BadInput, match="only a coating op names a coating process"):
        load_bundle(plan)


# ------------------------------------------------------- multi-feature inspection

SHOULDER = ("shoulder_north_face", "shoulder_thrust")


def shoulder_readings(plan):
    def reads(op):
        named = op.get("feature")
        named = named if isinstance(named, list) else [named]
        return (
            op["do"] == "inspect" and "length" in op.get("checks", {}) and set(named) & {*SHOULDER}
        )

    return [(s["id"], op["op"]) for s in setups(plan) for op in s["ops"] if reads(op)]


def one_shoulder_reading(plan, action="inspect"):
    """The drawing's one shoulder length, read once for both faces it is given to."""
    (sid, op), *others = shoulder_readings(plan)
    for other in others:
        rewrite(plan, ("op", *other), remove=True)
    rewrite(plan, ("op", sid, op), "feature", '["shoulder_north_face", "shoulder_thrust"]')
    if action != "inspect":
        rewrite(plan, ("op", sid, op), "do", f'"{action}"')
    return sid, op


def test_one_inspect_op_reads_a_limit_the_drawing_gives_two_features(tmp_path):
    plan = copy_examples(tmp_path) / "pivot-shaft" / "plan.toml"
    sid, op = one_shoulder_reading(plan)
    rows = evaluate("inspection", load_bundle(plan))
    for feature in SHOULDER:
        row = rows[f"{feature}:length"]
        assert (row.status, row.numbers["op"]) == ("pass", f"{sid}:{op}")
    _, _, html = traveler(plan, tmp_path / "out", setup=SYNTHETIC_KERNEL)
    (row,) = [row for row in op_rows(html, op) if "shoulder north face" in row]
    assert "shoulder north face, shoulder thrust" in row
    assert row.count("0.99–2.01") == 1


@pytest.mark.parametrize("action", ["face", "deburr"])
def test_only_an_inspect_op_may_name_several_features(tmp_path, action):
    plan = copy_examples(tmp_path) / "pivot-shaft" / "plan.toml"
    one_shoulder_reading(plan, action)
    with pytest.raises(BadInput, match="only an inspect op may name a feature list"):
        load_bundle(plan)


# ------------------------------------------------------------------ hold stop face


def stop_on(plan, sid, face):
    rewrite(plan, ("hold", sid), "stop_face", f'"{face}"' if face else None)


@pytest.mark.parametrize(
    ("setup", "face", "status"),
    [
        # The blank arrives as plain bar: the shoulder north face is first cut in S2.
        ("S1", "shoulder_north_face", "error"),
        ("S1", "stock_end", "pass"),
        # S1 faced the thrust face before the reversal: S2 may stop on it.
        ("S2", "shoulder_thrust", "pass"),
        # A face the setup cuts itself is not on the stock it receives.
        ("S2", "shoulder_north_face", "error"),
    ],
)
def test_hold_stop_face_must_exist_on_the_arriving_stock(tmp_path, setup, face, status):
    plan = copy_examples(tmp_path) / "pivot-shaft" / "plan.toml"
    stop_on(plan, setup, None)
    assert evaluate("hold_fields", load_bundle(plan))[setup].status == "pass"
    stop_on(plan, setup, face)
    row = evaluate("hold_fields", load_bundle(plan))[setup]
    assert row.status == status
    if status == "error":
        sid, op = find_op(plan, lambda op: op.get("feature") == face and op["do"] == "face")
        assert f"stops on {face}" in row.sentence
        assert f"first cut in {sid} op {op}" in row.sentence


def test_a_stop_face_that_names_nothing_is_bad_input(tmp_path):
    plan = copy_examples(tmp_path) / "pivot-shaft" / "plan.toml"
    stop_on(plan, "S1", "shoulder_far_side")
    with pytest.raises(BadInput, match="stop_face"):
        load_bundle(plan)


# ------------------------------------------------------------------- process holds

REASON = "test hold: a later setup clocks on a pin in this hole"


def hold_ream(plan, band, requirement="dia"):
    sid, op = find_op(plan, lambda op: op["do"] == "ream" and op.get("feature") == "rod_hole")
    rewrite(
        plan,
        ("op", sid, op),
        "process_holds",
        f'[{{ feature = "rod_hole", requirement = "{requirement}", band = {band}, '
        f'gauge = "rocker-rod-limit-gauges", reason = "{REASON}" }}]',
    )
    return sid, op


@pytest.mark.parametrize(
    ("band", "status"),
    [
        ("[1.994, 2.010]", "pass"),  # on the drawing's lower limit
        ("[2.000, 2.094]", "pass"),  # on its upper limit
        ("[1.993, 2.010]", "error"),
        ("[2.000, 2.095]", "error"),
    ],
)
def test_a_process_hold_must_lie_inside_its_drawing_band(tmp_path, band, status):
    plan = copy_examples(tmp_path) / "rocker-arm" / "plan.toml"
    sid, op = hold_ream(plan, band)
    row = evaluate("inspection", load_bundle(plan))[f"{sid}:{op}"]
    assert row.status == status
    assert row.numbers["process_holds"][0]["drawing_band"] == [1.994, 2.094]


def test_a_process_hold_prints_as_a_shop_limit_not_a_drawing_limit(tmp_path):
    plan = copy_examples(tmp_path) / "rocker-arm" / "plan.toml"
    _, op = hold_ream(plan, "[2.000, 2.010]")
    _, _, html = traveler(plan, tmp_path / "out", setup=SYNTHETIC_KERNEL)
    (row,) = [row for row in op_rows(html, op) if REASON in row]
    assert f"PROCESS HOLD — not a drawing limit: {REASON}" in row
    assert "2.000–2.010" in row


def test_a_process_hold_names_an_exported_requirement(tmp_path):
    plan = copy_examples(tmp_path) / "rocker-arm" / "plan.toml"
    hold_ream(plan, "[2.000, 2.010]", requirement="depth")
    with pytest.raises(BadInput, match="process hold rod_hole depth"):
        load_bundle(plan)
