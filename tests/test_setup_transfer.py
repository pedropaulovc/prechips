"""The printed Zs that link one setup's sheet to the next agree on the printed grid."""

import math
import re
from html import unescape
from pathlib import Path

import pytest

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
LABELS = {
    "top": "top_z",
    "bottom": "bottom_z",
    "north end": "north_end_z",
    "south end": "south_end_z",
    "plain end": "plain_end_z",
    "rail bottoms": "retained_rail_bottom_z",
}
# Z zero methods that set the DRO from a measurement, printing no touched surface.
MEASURED = {"trial_cut_measure", "face_then_set", "measure_then_set"}
_NUMBER = r"-?\d+(?:\.\d+)?"


def _sheets(page):
    """Each setup's HTML, its sheets joined."""
    sheets = {}
    parts = re.split(r'<section class="page" data-sheet="SETUP (\S+) sheet \d+"', page)
    for setup, html in zip(parts[1::2], parts[2::2], strict=True):
        sheets[setup] = sheets.get(setup, "") + html
    return sheets


def _arrival(html):
    """``{stock_state key: printed Z}`` from the setup's "Starts from" line."""
    line = re.search(r"Starts from:[^<]*", unescape(html)).group(0)
    return {
        LABELS[label]: float(z)
        for label, z in re.findall(rf"({'|'.join(LABELS)})(?: \([^)]*\))? at Z ({_NUMBER})", line)
    }


def _cut_to(html):
    """``{op: printed Z}``: the Z each op row's target ends at."""
    rows = re.findall(r'<tbody class="op"><tr><td>([^<]+)</td>(.*?)</tr>', html)
    found = {}
    for op, cells in rows:
        target = re.search(rf"<td>Z ({_NUMBER})(?: → ({_NUMBER}))?", cells)
        if target:
            found[op] = float(target[2] or target[1])
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
    keys = [k for k in LABELS.values() if abs(state.get(k, math.inf) - value) <= 1e-9]
    received = _arrival(sheet)
    return received.get(keys[0]) if keys else None


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
        if not move:
            continue
        sign, offset = move
        state, printed = setup["stock_state"], _arrival(sheets[setup["id"]])
        shifts = {}
        for key, z in printed.items():
            left = _left(before, sign * (state[key] - offset), sheets[before["id"]])
            if left is not None:
                shifts[key] = round(z - sign * left, 6)
        where = f"{setup['id']} from {before['id']}: {printed} less ±{before['id']}'s Zs"
        # One shift links every surface the setup receives, and it is on its grid.
        assert len(set(shifts.values())) <= 1, f"{where} differ: {shifts}"
        step = coordinates.dro_grid(bundle, setup)[0]
        for shift in shifts.values():
            assert abs(shift / step - round(shift / step)) < 1e-6, f"{where}: {shift} off-grid"
        linked += len(shifts) > 1
        zero = setup.get("zero", {}).get("z", {})
        top = printed.get("top_z")
        if zero.get("face") == "top" and "after_op" not in zero and top is not None:
            # Its Z zero touches the top where the arrival line prints it (a measured
            # touch sets the DRO from the measurement and prints no surface).
            touch = re.search(
                rf"<td>Z</td><td>top;[^<]*surface at ({_NUMBER})", sheets[setup["id"]]
            )
            measured = zero.get("method") in MEASURED
            assert measured or (touch and float(touch[1]) == top), (where, touch and touch[0])
        elif top is not None:
            # An untouched top never prints below the stock top.
            assert top >= state["top_z"] - 1e-9, f"{where}: top below {state['top_z']}"
    assert linked, f"{pilot}: no transfer links two or more printed Zs"
