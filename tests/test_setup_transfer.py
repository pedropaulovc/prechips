"""The printed Zs that link one setup's sheet to the next agree on the printed grid."""

import math
import re
from html import unescape
from pathlib import Path

import pytest
from test_operative_surface import FEATURES, ZERO
from test_operative_surface import bundle as scratch_bundle

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
# The one transform a "Starts from" line names: who, turned over, from which setup, shift.
_TRANSFORM = re.compile(r"\((each|[a-z ]+?) Z = (−\()?its Setup (\S+) Z\)? ([+−]) ([\d.]+)\)")
# Its refusal, when no one shift lands the Zs before on this setup's grid.
_REFUSED = "no one shift carries them"
IDLE = "[[setups.ops]]\nop=90\ndo='deburr'\nfeature='target'\n"


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


def _check(bundle, sheets, setup, before, sign, offset):
    """Assert the printed Zs ``setup`` receives from ``before`` follow one shift from the Zs
    ``before`` printed, as any transform its line names says, or that its line refuses
    when no one shift lands them on its grid; return how many Zs that shift links."""
    html = sheets[setup["id"]]
    line = re.search(r"Starts from:[^<]*", unescape(html)).group(0)
    state, printed = setup["stock_state"], _arrival(html)
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
    named, refused = _TRANSFORM.search(line), _REFUSED in line
    assert not (named and refused), line
    if named:
        # Every Z the named transform covers took exactly it.
        who, turned, source, plus, shift = named.groups()
        keys = list(printed) if who == "each" else [LABELS[label] for label in who.split(" and ")]
        assert (source, bool(turned)) == (before["id"], sign < 0), line
        shift = float(shift) * (-1 if plus == "−" else 1)
        assert all(abs(shifts[key] - shift) < 1e-6 for key in keys), (line, shifts)
    if refused:
        # Only Zs not whole steps of this grid apart refuse; each then prints by itself.
        first = next(iter(left.values()))
        apart = [(z - first) / grid[0] for z in left.values()]
        assert any(abs(n - round(n)) > 1e-6 for n in apart), (line, left)
        for key, z in printed.items():
            assert z == coordinates.dro_z(state[key], grid), (line, key)
    else:
        # One shift links every surface the setup receives.
        assert len(set(shifts.values())) <= 1, f"{where} differ: {shifts}"
    zero = setup.get("zero", {}).get("z", {})
    top = printed.get("top_z")
    if zero.get("face") == "top" and "after_op" not in zero and top is not None:
        # Its Z zero touches the top where the arrival line prints it (a measured touch
        # sets the DRO from the measurement and prints no surface).
        touch = re.search(rf"<td>Z</td><td>top;[^<]*surface at ({_NUMBER})", html)
        measured = zero.get("method") in MEASURED
        assert measured or (touch and float(touch[1]) == top), (where, touch and touch[0])
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
    "top, bottom, offset, linked",
    [
        # S1 prints 0.000 / -10.005: a half step apart on S2's 0.010 DRO, so no one shift.
        (0.0, -10.008, 0.002, 0),
        # S1 prints 0.005 / -10.005: whole steps apart, so one shift, 0.005, carries both.
        (0.003, -10.008, 0.0, 2),
    ],
)
def test_a_finer_sheets_zs_carry_onto_a_coarser_dro_by_one_shift_or_none(
    tmp_path, top, bottom, offset, linked
):
    bundle = _turned_over(tmp_path, top, bottom, offset)
    findings = coordinates.evaluate(bundle) + zero_recipe.evaluate(bundle)
    sheets = _sheets(render_traveler(bundle, findings, {}))
    first, second = bundle.plan["setups"]
    assert _check(bundle, sheets, second, first, -1, offset) == linked
