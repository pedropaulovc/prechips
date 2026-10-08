"""The printed Zs that link one setup's sheet to the next agree on the printed grid."""

import json
import math
import re
from pathlib import Path

import pytest
from test_operative_surface import FEATURES, ZERO
from test_operative_surface import bundle as scratch_bundle
from test_sheet_ops import Markup, content

from prechips.inputs import load_bundle
from prechips.rules import coordinates, zero_recipe
from prechips.rules.resolution import setup_frame
from prechips.sheet import render_traveler

ROOT = Path(__file__).resolve().parents[1]
PILOTS = [
    "pivot-shaft/plan.toml",
    "rocker-arm/plan.toml",
    "pivot-bracket/plan.toml",
    "cone-pivot-post/built-up.toml",
]
SURFACES = (
    "top_z",
    "bottom_z",
    "north_end_z",
    "south_end_z",
    "plain_end_z",
    "retained_rail_bottom_z",
)
# Z zero methods that set the DRO from a measurement, printing no touched surface.
MEASURED = {"trial_cut_measure", "face_then_set", "measure_then_set"}
_NUMBER = r"-?\d+(?:\.\d+)?"
IDLE = "[[setups.ops]]\nop=90\ndo='deburr'\nfeature='target'\n"


def _within(node, parent):
    while node is not None:
        if node is parent:
            return True
        node = node["parent"]
    return False


def _reading_z(node):
    text = re.sub(r"([+-])\s+(?=\d)", r"\1", content(node).replace("−", "-"))
    numbers = re.findall(_NUMBER, text)
    assert len(numbers) == 1, content(node)
    return float(numbers[0])


def _sheets(page):
    """Each setup's parsed consumer-visible records, across all its sheets."""
    markup = Markup(page)
    sheets = {}
    for section in markup.find("page"):
        label = section["attrs"].get("data-sheet", "")
        match = re.fullmatch(r"SETUP (\S+) sheet \d+", label)
        if match:
            sheets.setdefault(match[1], []).extend(
                node for node in markup.nodes if _within(node, section)
            )
    return sheets


def _records(nodes, attribute, value=None):
    return [
        node
        for node in nodes
        if attribute in node["attrs"] and (value is None or node["attrs"][attribute] == value)
    ]


def _arrival(nodes):
    """``{stock_state key: printed Z}`` from the visible arriving-surface readings."""
    found = {}
    for surface in _records(nodes, "data-stock-surface"):
        key = surface["attrs"]["data-stock-surface"]
        assert key in SURFACES
        readings = [
            node
            for node in nodes
            if "reading" in node["attrs"].get("class", "").split() and _within(node, surface)
        ]
        if surface["attrs"].get("data-stock-state") == "unknown":
            assert not readings, (key, content(surface))
            continue
        assert len(readings) == 1, (key, content(surface))
        value = _reading_z(readings[0])
        assert key not in found or found[key] == value
        found[key] = value
    assert found, "no consumer-visible arriving surface readings"
    return found


def _cut_to(nodes):
    """``{op: printed Z}``: the Z each operation's visible target ends at."""
    found = {}
    for operation in _records(nodes, "data-op"):
        targets = [
            node
            for node in nodes
            if "op-target" in node["attrs"].get("class", "").split() and _within(node, operation)
        ]
        for target in targets:
            values = [node for node in nodes if node["tag"] == "dd" and _within(node, target)]
            assert len(values) == 1, content(target)
            z = re.search(
                rf"\bZ\s*(?:(?:{_NUMBER}|\?)\s*)?→\s*({_NUMBER})",
                content(values[0]).replace("−", "-"),
            )
            if z:
                found[operation["attrs"]["data-op"]] = float(z[1])
    return found


def _transform(bundle, setup, before):
    """``(sign, offset)``: ``Z here = sign * Z before + offset``; None unless parallel."""
    here, there = setup_frame(bundle, setup), setup_frame(bundle, before)
    z_here, z_there = here.get("z"), there.get("z")
    turn = sum(a * b for a, b in zip(z_here, z_there, strict=True))
    if abs(abs(turn) - 1) > 1e-9:
        return None
    offset = sum(
        (a - b) * c for a, b, c in zip(there["origin"], here["origin"], z_here, strict=True)
    )
    return (1 if turn > 0 else -1), offset


def _left(before, value, sheet):
    """The Z the setup ``before`` printed for the surface it leaves at ``value``: the last
    facing op that cut it there, else the surface it received there; None if neither."""
    printed = _cut_to(sheet)
    for op in reversed(before.get("ops", [])):
        z = op.get("to_z")
        facing = op.get("do") in {"face", "rough_face", "finish_face"}
        if facing and isinstance(z, (int, float)) and abs(z - value) <= 1e-9:
            return printed.get(str(op["op"]))
    state = before.get("stock_state", {})
    keys = [k for k in SURFACES if abs(state.get(k, math.inf) - value) <= 1e-9]
    received = _arrival(sheet)
    return received.get(keys[0]) if keys else None


def _check(bundle, sheets, setup, before, sign, offset):
    """Check the independently reconstructed shift against the displayed transfer,
    or its refusal when the preceding readings cannot share this setup's grid."""
    nodes = sheets[setup["id"]]
    state, printed = setup["stock_state"], _arrival(nodes)
    grid = coordinates.dro_grid(bundle, setup)
    left, shifts = {}, {}
    for key, z in printed.items():
        found = _left(before, sign * (state[key] - offset), sheets[before["id"]])
        if found is not None:
            left[key] = sign * found
            shifts[key] = round(z - left[key], 6)
    where = f"{setup['id']} from {before['id']}: {printed} less ±{before['id']}'s Zs"
    for z in printed.values():
        assert abs(z / grid[0] - round(z / grid[0])) < 1e-6, f"{where}: {z} off its grid"
    transfers = _records(nodes, "data-transfer-before")
    assert all(
        node["attrs"].get("data-transfer-state") in {"linked", "refused", "unlinked"}
        for node in transfers
    ), transfers
    named = [node for node in transfers if node["attrs"].get("data-transfer-state") == "linked"]
    refused = [node for node in transfers if node["attrs"].get("data-transfer-state") == "refused"]
    assert not (named and refused), transfers
    for transform in named:
        attrs = transform["attrs"]
        keys = json.loads(attrs["data-transfer-surfaces"])
        context = (attrs, shifts, before["id"], setup["id"])
        assert keys and set(keys) <= set(printed), context
        expression = content(transform).replace("−", "-")
        source = rf"its Setup {re.escape(before['id'])} Z"
        if re.search(rf"=\s*[^=]*?-\s*{source}\)", expression):
            visible_sign = -1
        elif re.search(rf"=\s*{source}\s*[+-]", expression):
            visible_sign = 1
        else:
            pytest.fail(f"unreadable transfer source/orientation: {expression}")
        assert visible_sign == sign, expression
        if re.search(r"\beach Z\s*=", expression):
            assert set(keys) == set(printed), (context, printed)
        assert set(keys) <= set(shifts), context
        readings = [
            node for node in _records(nodes, "data-transfer-shift") if _within(node, transform)
        ]
        assert len(readings) == 1, attrs
        shift = _reading_z(readings[0])
        assert all(abs(shifts[key] - shift) < 1e-6 for key in keys), context
    if refused:
        # Only Zs not whole steps of this grid apart refuse; each then prints by itself.
        assert all(node["attrs"]["data-transfer-before"] == before["id"] for node in refused)
        first = next(iter(left.values()))
        apart = [(z - first) / grid[0] for z in left.values()]
        assert any(abs(n - round(n)) > 1e-6 for n in apart), left
        for key, z in printed.items():
            assert z == coordinates.dro_z(state[key], grid), key
    else:
        # One shift links every surface the setup receives.
        assert len(set(shifts.values())) <= 1, f"{where} differ: {shifts}"
    zero = setup.get("zero", {}).get("z", {})
    top = printed.get("top_z")
    if zero.get("face") == "top" and "after_op" not in zero and top is not None:
        # A measured zero sets from its measurement; a touch names the printed top.
        touches = [
            node
            for node in _records(nodes, "data-zero-axis", "z")
            if node["attrs"].get("data-zero-face") == "top"
        ]
        measured = zero.get("method") in MEASURED
        assert measured or (touches and all(_reading_z(touch) == top for touch in touches)), (
            where,
            [content(touch) for touch in touches],
        )
    elif top is not None:
        # An untouched top never prints below the stock top.
        assert top >= state["top_z"] - 1e-9, f"{where}: top below {state['top_z']}"
    return 0 if refused else len(shifts)


@pytest.mark.parametrize("pilot", PILOTS)
def test_each_transfer_prints_one_shift_and_its_zero_touches_the_printed_top(pilot):
    bundle = load_bundle(ROOT / "examples" / pilot)
    findings = coordinates.evaluate(bundle) + zero_recipe.evaluate(bundle)
    sheets = _sheets(render_traveler(bundle, findings, {}))
    setups = {setup["id"]: setup for setup in bundle.plan["setups"]}
    linked = 0
    for setup in bundle.plan["setups"]:
        source = setup.get("stock_in")
        before = setups.get(source) if isinstance(source, str) else None
        move = before and _transform(bundle, setup, before)
        if move:
            linked += _check(bundle, sheets, setup, before, *move) > 1
    assert linked, f"{pilot}: no transfer links two or more printed Zs"


def _turned_over(tmp_path, top, bottom, offset):
    """S1, on a 0.005 DRO, holds the part between Z ``top`` and ``bottom``; S2, on a 0.010
    DRO, receives it turned over, its frame ``offset`` up, and touches Z on its top."""
    second = (
        "[[setups]]\nid = 'S2'\nmachine = 'coarse'\nframe = 'B'\nstock_in = 'S1'\n"
        "coolant = 'unknown'\ndeburr_mm = 'unknown'\n"
        "[setups.hold]\nfixture = 'unknown'\nstop = 'unknown'\ngrip_mm = 'unknown'\n"
        "clamp = 'unknown'\nfixed_jaw = 'unknown'\n"
        f"[setups.stock_state]\ntop_z = {round(offset - bottom, 9)}\n"
        f"bottom_z = {round(offset - top, 9)}\n" + ZERO.format("top", "") + IDLE
    )
    path = scratch_bundle(tmp_path, FEATURES, ZERO.format("top", "") + IDLE + second)
    text = path.read_text(encoding="utf-8")
    path.write_text(
        text.replace("top_z = 0.0\nbottom_z = -10.0\n", f"top_z = {top}\nbottom_z = {bottom}\n"),
        encoding="utf-8",
    )
    features = path.with_name("features.toml")
    features.write_text(
        features.read_text(encoding="utf-8")
        + f"[frames.B]\norigin = [5.0, 2.0, {1.0 + offset}]\nx = [1.0, 0.0, 0.0]\n"
        "y = [0.0, -1.0, 0.0]\nz = [0.0, 0.0, -1.0]\nbinding = 'measured'\n",
        encoding="utf-8",
    )
    return load_bundle(path)


@pytest.mark.parametrize(
    "top, bottom, offset, linked, arriving",
    [
        # S1 prints 0.000 / -10.005: a half step apart on S2's 0.010 DRO, so no one shift.
        (0.0, -10.008, 0.002, 0, {"top_z": 10.01, "bottom_z": 0.01}),
        # S1 prints 0.005 / -10.005: whole steps apart, so one shift, 0.005, carries both.
        (0.003, -10.008, 0.0, 2, {"top_z": 10.01, "bottom_z": 0.0}),
    ],
)
def test_a_finer_sheets_zs_carry_onto_a_coarser_dro_by_one_shift_or_none(
    tmp_path, top, bottom, offset, linked, arriving
):
    bundle = _turned_over(tmp_path, top, bottom, offset)
    findings = coordinates.evaluate(bundle) + zero_recipe.evaluate(bundle)
    sheets = _sheets(render_traveler(bundle, findings, {}))
    first, second = bundle.plan["setups"]
    assert _arrival(sheets[second["id"]]) == arriving
    if linked:
        # This row's 0.005 shift differs from its zero frame offset: the sheet must
        # show the linked transform, not merely happen to print compatible numbers.
        shown = _records(sheets[second["id"]], "data-transfer-state", "linked")
        assert shown and all(
            node["attrs"].get("data-transfer-before") == first["id"] for node in shown
        )
    assert _check(bundle, sheets, second, first, -1, offset) == linked
