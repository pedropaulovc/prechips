"""One surface, one printed Z.

S1 finishes a face at an off-grid ``to_z``; the DRO cuts it at the checked ``dro_to_z``,
rounded up on the mill's 0.005 mm grid. S2 starts on that face, zeroes Z on it and
drills through from it: every Z it prints for the face is that as-cut value, and every
Z it dials is on the grid.
"""

import re
from html import unescape

import pytest
from test_cli import SYNTHETIC_KERNEL, traveler
from test_headroom import coordinate_bundle

NOMINAL = -2.27825
STEP = 0.005
BLIND = 3.0
FEATURES = (
    "kind = 'plane'\nbounds = { x = [0.0, 20.0], y = [0.0, 10.0], z = [-2.27825, 0.0] }\n"
    "[features.hole]\nframe = 'model'\nkind = 'hole'\nrequirements = []\n"
    "at = [10.0, 5.0, -2.27825]\ndia = 6.0\nthru = true\n"
)
ZERO = "[setups.zero.z]\nface = '{}'\n{}method = 'paper'\npaper_mm = 0.05\ncheck_jog_mm = 10.0\n"


def plan(tmp_path, exit_mm=1.0, depth=None):
    """S1 finishes ``target`` to Z -2.27825; S2, same frame, starts on it, zeroes Z on it
    and drills ``hole`` through the 7.72175 mm below it, ``exit_mm`` past the exit face.
    A ``depth`` band (or bare upper limit) makes ``hole`` blind, drilled 3.0 deep."""
    features = FEATURES
    if depth is not None:
        features = FEATURES.replace("thru = true\n", f"thru = false\ndepth = {depth}\n")
    operations = (
        ZERO.format("top", "")
        + "[[setups.ops]]\nop = 10\ndo = 'finish_face'\nfeature = 'target'\ntool = 'cutter'\n"
        f"to_z = {NOMINAL}\ndirection = 'conventional'\n"
        "[[setups]]\nid = 'S2'\nmachine = 'mill'\nframe = 'A'\n"
        "coolant = 'unknown'\ndeburr_mm = 'unknown'\n"
        "[setups.hold]\nfixture = 'unknown'\nstop = 'unknown'\ngrip_mm = 'unknown'\n"
        "clamp = 'unknown'\nfixed_jaw = 'unknown'\n"
        f"[setups.stock_state]\ntop_z = {NOMINAL}\nbottom_z = -10.0\n"
        f"entry_z = {{ hole = {NOMINAL} }}\nlocal_thickness = {{ hole = 7.72175 }}\n"
        + ZERO.format("target", f"edge_mm = {NOMINAL}\n")
        + "[[setups.ops]]\nop = 10\ndo = 'drill'\nfeature = 'hole'\ntool = 'drill'\n"
        + (f"exit_mm = {exit_mm}\n" if depth is None else f"depth_mm = {BLIND}\n")
    )
    path = coordinate_bundle(tmp_path, features, operations)
    path.write_text(
        path.read_text(encoding="utf-8").replace(
            "[[setups]]",
            "[dro]\nmode = 'abs'\n[dro.direction]\nx = 'right'\ny = 'away'\nz = 'up'\n[[setups]]",
            1,
        ),
        encoding="utf-8",
    )
    inventory = path.with_name("inventory.toml")
    inventory.write_text(
        inventory.read_text(encoding="utf-8").replace(
            "[machines.mill]\nkind = 'mill'\n",
            f"[machines.mill]\nkind = 'mill'\nresolution_mm = {STEP}\n",
        ),
        encoding="utf-8",
    )
    return path


def on_grid(value):
    return value / STEP == pytest.approx(round(value / STEP), abs=1e-6)


def test_later_setup_prints_the_checked_as_cut_face(tmp_path):
    _, report, html = traveler(plan(tmp_path), tmp_path / "out", setup=SYNTHETIC_KERNEL)
    findings = {(row["rule"], row["subject"]): row for row in report["findings"]}
    (cut,) = findings["coordinates", "S1"]["numbers"]["operations"]
    face = cut["dro_to_z"]
    # The face is cut where the DRO stops: rounded up, never deeper, off the authored Z.
    assert (cut["to_z"], face) == (NOMINAL, -2.275)
    text = re.sub(r"\|+", "|", unescape(re.sub(r"<[^>]+>", "|", html)))
    assert re.findall(r"top at Z (-?\d+\.\d+)", text) == ["0.000", "-2.275"]
    zero = re.search(
        r"target; surface at ([^;|]+); paper ([^|]+)\|([^|]+)\|\+Z ([^|]+)\|([^|]+)\|([^|]+)\|",
        text,
    )
    surface, paper, axis_set, jog, must, mirrored = map(float, zero.groups())
    assert surface == face
    assert (axis_set, must, mirrored) == pytest.approx(
        (face + paper, face + paper + jog, face + paper - jog)
    )
    entry, tip, exit_face = map(
        float, re.search(r"\|Z ([^|]+) → ([^|]+)\|breaks through at ([^|]+)\|", text).groups()
    )
    (endpoint,) = findings["blind_depth", "hole"]["numbers"]["endpoints"]
    assert entry == face
    # The drill works from the stock bottom it exits, as S2 prints it, to a DRO tip on
    # the grid no deeper than the worked tip.
    assert exit_face == -10.0
    assert on_grid(tip) and endpoint["tip_z"] <= tip < endpoint["tip_z"] + STEP
    assert "-2.278" not in text


@pytest.mark.parametrize("exit_mm,stopped", [(0.0, True), (STEP, False)])
def test_rounded_up_through_tip_that_stops_short_is_a_stop(tmp_path, exit_mm, stopped):
    """A DRO tip rounded up off a zero break-through stops the drill point short of the
    exit face, so the drill row stops; one grid step of authored break-through clears it."""
    _, _, html = traveler(plan(tmp_path, exit_mm), tmp_path / "out", setup=SYNTHETIC_KERNEL)
    (cell,) = re.findall(r"<td>(Z -2\.275 → .*?)</td>", html)
    assert ("STOP" in cell) is stopped


@pytest.mark.parametrize(
    "depth,stopped",
    [([BLIND, 20.0], True), ([BLIND - STEP, 20.0], False), (20.0, True)],
)
def test_rounded_up_blind_tip_outside_its_depth_band_is_a_stop(tmp_path, depth, stopped):
    """Rounded up, the DRO tip leaves a blind hole shallower than drilled. Below the band's
    lower end is a STOP; one grid step of band clears it; a bare upper limit leaves the
    lower end unknown, and unknown is not a pass."""
    _, report, html = traveler(
        plan(tmp_path, depth=depth), tmp_path / "out", setup=SYNTHETIC_KERNEL
    )
    (endpoint,) = [
        row
        for finding in report["findings"]
        if (finding["rule"], finding["subject"]) == ("blind_depth", "hole")
        for row in finding["numbers"]["endpoints"]
    ]
    printed = endpoint["dro_depth_mm"]
    assert BLIND - STEP < printed < BLIND
    (cell,) = re.findall(r"<td>(Z -2\.275 → .*?)</td>", html)
    assert f"depth {printed:.3f}" in cell
    assert ("STOP" in cell) is stopped
