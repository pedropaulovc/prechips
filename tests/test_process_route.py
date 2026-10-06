"""Finishing route, multi-feature inspection, hold stop faces and process holds (PLAN §4.1)."""

import re
from html import unescape

import pytest
from test_cli import SYNTHETIC_KERNEL, copy_examples, traveler

from prechips.inputs import BadInput, load_bundle
from prechips.rules import RULES


def evaluate(name, bundle):
    return {row.subject: row for row in next(r for r in RULES if r.name == name).evaluate(bundle)}


def edit(path, old, new):
    text = path.read_text(encoding="utf-8")
    assert old in text, old
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


def op_rows(html, op):
    return [
        unescape(re.sub(r"<[^>]+>", "|", body))
        for number, body in re.findall(r"<tr><td>(\d+)</td>(.*?)</tr>", html, re.DOTALL)
        if number == op
    ]


# ------------------------------------------------------------------ finishing route

COATING_OP = '\n[[setups.ops]]\nop = 90\ndo = "coating"\nfeature = "pivot_bearing"\n'
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
    # The drawing says "turned, oiled": with no coating step the job cannot read clear.
    assert evaluate("finish_route", load_bundle(plan))["pivot-shaft"].status == "warn"
    step = COATING_OP + (f"process = {process}\n" if process else "")
    plan.write_text(plan.read_text(encoding="utf-8") + step, encoding="utf-8")
    if service:
        inventory = examples / "inventory" / "pedro-shop.toml"
        inventory.write_text(inventory.read_text(encoding="utf-8") + SERVICE, encoding="utf-8")
    bundle = load_bundle(plan)
    assert evaluate("finish_route", bundle)["pivot-shaft"].status == "pass"
    assert evaluate("tool_resolves", bundle)["S3:90"].status == resolves


def test_only_a_coating_op_names_a_process(tmp_path):
    plan = copy_examples(tmp_path) / "pivot-shaft" / "plan.toml"
    inspect = 'do = "inspect"\nfeature = "shoulder_thrust"\n'
    edit(plan, inspect, inspect + 'process = "cutting-oil"\n')
    with pytest.raises(BadInput, match="process"):
        load_bundle(plan)


# ------------------------------------------------------- multi-feature inspection

SHOULDER_PAIR = (
    'op = 71\ndo = "inspect"\nfeature = "shoulder_north_face"\n',
    'op = 71\ndo = "inspect"\nfeature = ["shoulder_north_face", "shoulder_thrust"]\n',
)
SECOND_READING = re.compile(r"\[\[setups\.ops\]\]\nop = 72\n.*?length = \"calipers\"\n", re.S)


def one_shoulder_reading(plan):
    edit(plan, *SHOULDER_PAIR)
    plan.write_text(SECOND_READING.sub("", plan.read_text(encoding="utf-8")), encoding="utf-8")


def test_one_inspect_op_reads_a_limit_the_drawing_gives_two_features(tmp_path):
    plan = copy_examples(tmp_path) / "pivot-shaft" / "plan.toml"
    one_shoulder_reading(plan)
    rows = evaluate("inspection", load_bundle(plan))
    for feature in ("shoulder_north_face", "shoulder_thrust"):
        row = rows[f"{feature}:length"]
        assert (row.status, row.numbers["op"]) == ("pass", "S2:71")
    _, _, html = traveler(plan, tmp_path / "out", setup=SYNTHETIC_KERNEL)
    assert not op_rows(html, "72")
    (row,) = op_rows(html, "71")
    assert "shoulder north face, shoulder thrust" in row
    assert row.count("0.99–2.01") == 1


@pytest.mark.parametrize("action", ["face", "deburr"])
def test_only_an_inspect_op_may_name_several_features(tmp_path, action):
    plan = copy_examples(tmp_path) / "pivot-shaft" / "plan.toml"
    edit(plan, *SHOULDER_PAIR)
    edit(
        plan,
        'op = 71\ndo = "inspect"\n',
        f'op = 71\ndo = "{action}"\n',
    )
    with pytest.raises(BadInput, match="feature"):
        load_bundle(plan)


# ------------------------------------------------------------------ hold stop face

STOPS = {
    "S1": 'stop = "push the Ø10 north stub',
    "S2": 'stop = "shoulder thrust face (T2 Z-9)',
}


@pytest.mark.parametrize(
    ("setup", "face", "status"),
    [
        # The blank arrives as plain bar: the shoulder north face is first cut in S2 op 20.
        ("S1", "shoulder_north_face", "error"),
        ("S1", "stock_end", "pass"),
        # S1 op 20 faced the thrust face before the reversal: S2 may stop on it.
        ("S2", "shoulder_thrust", "pass"),
        # A face the setup cuts itself is not on the stock it receives.
        ("S2", "shoulder_north_face", "error"),
    ],
)
def test_hold_stop_face_must_exist_on_the_arriving_stock(tmp_path, setup, face, status):
    plan = copy_examples(tmp_path) / "pivot-shaft" / "plan.toml"
    assert evaluate("hold_fields", load_bundle(plan))[setup].status == "pass"
    edit(plan, STOPS[setup], f'stop_face = "{face}"\n{STOPS[setup]}')
    row = evaluate("hold_fields", load_bundle(plan))[setup]
    assert row.status == status
    if status == "error":
        assert f"stops on {face}" in row.sentence and "first cut in S2 op 20" in row.sentence


def test_a_stop_face_that_names_nothing_is_bad_input(tmp_path):
    plan = copy_examples(tmp_path) / "pivot-shaft" / "plan.toml"
    edit(plan, STOPS["S1"], f'stop_face = "shoulder_far_side"\n{STOPS["S1"]}')
    with pytest.raises(BadInput, match="stop_face"):
        load_bundle(plan)


# ------------------------------------------------------------------- process holds

REAM = 'op = 34\ndo = "ream"\nfeature = "rod_hole"\n'


def hold_ream(plan, band, requirement="dia"):
    edit(
        plan,
        REAM,
        REAM + f'process_holds = [{{ feature = "rod_hole", requirement = "{requirement}", '
        f'band = {band}, gauge = "rocker-rod-limit-gauges", '
        'reason = "S4 clocks datum C on a 1.9875 pin in this hole" }]\n',
    )


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
    hold_ream(plan, band)
    row = evaluate("inspection", load_bundle(plan))["S2:34"]
    assert row.status == status
    assert row.numbers["process_holds"][0]["drawing_band"] == [1.994, 2.094]


def test_a_process_hold_prints_as_a_shop_limit_not_a_drawing_limit(tmp_path):
    plan = copy_examples(tmp_path) / "rocker-arm" / "plan.toml"
    hold_ream(plan, "[2.000, 2.010]")
    _, _, html = traveler(plan, tmp_path / "out", setup=SYNTHETIC_KERNEL)
    (row,) = op_rows(html, "34")
    assert "PROCESS HOLD — not a drawing limit: S4 clocks datum C" in row
    assert "2.000–2.010" in row


def test_a_process_hold_names_an_exported_requirement(tmp_path):
    plan = copy_examples(tmp_path) / "rocker-arm" / "plan.toml"
    hold_ream(plan, "[2.000, 2.010]", requirement="depth")
    with pytest.raises(BadInput, match="process hold rod_hole depth"):
        load_bundle(plan)
