"""One surface, one printed Z.

S1 finishes a face at an off-grid ``to_z``; the DRO cuts it at the checked ``dro_to_z``,
rounded up on S1's grid. S2 receives S1's stock, starts on that face, zeroes Z on it
and drills from it: every Z it prints for the face is that as-cut value, and every Z it
dials is on its own grid.
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
    "kind = 'plane'\nbounds = { x = [0.0, 20.0], y = [0.0, 10.0], z = [-4.0, 0.0] }\n"
    "[features.hole]\nframe = 'model'\nkind = 'hole'\nrequirements = []\n"
    "at = [10.0, 5.0, -2.27825]\ndia = 6.0\nthru = true\n"
)
ZERO = "[setups.zero.z]\nface = '{}'\n{}method = 'paper'\npaper_mm = 0.05\ncheck_jog_mm = 10.0\n"
MILL = "[machines.mill]\nkind = 'mill'\n"


def setup(sid):
    """A same-frame fine-grid setup that receives S1's stock, its top on S1's face."""
    return (
        f"[[setups]]\nid = '{sid}'\nmachine = 'mill'\nframe = 'A'\nstock_in = 'S1'\n"
        "coolant = 'unknown'\ndeburr_mm = 'unknown'\n"
        "[setups.hold]\nfixture = 'unknown'\nstop = 'unknown'\ngrip_mm = 'unknown'\n"
        "clamp = 'unknown'\nfixed_jaw = 'unknown'\n"
        f"[setups.stock_state]\ntop_z = {NOMINAL}\nbottom_z = -10.0\n"
        f"entry_z = {{ hole = {NOMINAL} }}\nlocal_thickness = {{ hole = 7.72175 }}\n"
        + ZERO.format("target", f"edge_mm = {NOMINAL}\n")
    )


def face(op, to_z):
    return (
        f"[[setups.ops]]\nop = {op}\ndo = 'finish_face'\nfeature = 'target'\ntool = 'cutter'\n"
        f"to_z = {to_z}\ndirection = 'conventional'\n"
    )


def bundle(tmp_path, features, operations, coarse=False):
    """The scratch bundle on an absolute up-reading DRO; mills on the 0.005 grid, S1's on
    0.010 when ``coarse``."""
    path = coordinate_bundle(tmp_path, features, operations)
    text = path.read_text(encoding="utf-8").replace(
        "[[setups]]",
        "[dro]\nmode = 'abs'\n[dro.direction]\nx = 'right'\ny = 'away'\nz = 'up'\n[[setups]]",
        1,
    )
    path.write_text(text.replace("machine = 'mill'", "machine = 'coarse'", int(coarse)), "utf-8")
    inventory = path.with_name("inventory.toml")
    stock = inventory.read_text(encoding="utf-8")
    coarse_mill = (
        stock[stock.index(MILL) :]
        .split("[tools.", 1)[0]
        .replace("machines.mill", "machines.coarse")
    )
    stock = stock.replace(MILL, f"{MILL}resolution_mm = {STEP}\n")
    stock += coarse_mill.replace(
        "kind = 'mill'\n", f"kind = 'mill'\nresolution_mm = {2 * STEP}\n", 1
    )
    inventory.write_text(stock, encoding="utf-8")
    return path


def plan(tmp_path, exit_mm=1.0, depth=None, do="drill", drilled=BLIND, coarse=False, detour=False):
    """S1 finishes ``target`` to Z -2.27825; S2, same frame, receives S1's stock, starts on
    it, zeroes Z on it and ``do``-s ``hole`` from it: through the 7.72175 mm below it,
    ``exit_mm`` past the exit face, or, given a ``depth`` band (or bare upper limit),
    blind and ``drilled`` deep. With ``detour`` an S2 that also receives S1's stock faces
    ``target`` deeper first, and the consumer is S3, which never receives that cut."""
    features = FEATURES
    if depth is not None:
        features = FEATURES.replace("thru = true\n", f"thru = false\ndepth = {depth}\n")
    operations = (
        ZERO.format("top", "")
        + face(10, NOMINAL)
        + (setup("S2") + face(10, NOMINAL - 1.0) if detour else "")
        + setup("S3" if detour else "S2")
        + f"[[setups.ops]]\nop = 10\ndo = '{do}'\nfeature = 'hole'\ntool = 'drill'\n"
        + (f"exit_mm = {exit_mm}\n" if depth is None else f"depth_mm = {drilled}\n")
    )
    return bundle(tmp_path, features, operations, coarse)


def on_grid(value):
    return value / STEP == pytest.approx(round(value / STEP), abs=1e-6)


def printed(html):
    return re.sub(r"\|+", "|", unescape(re.sub(r"<[^>]+>", "|", html)))


def zero(text, name):
    """The Z zero row on ``name``: surface, paper, Axis Set, jog, must read, if reversed."""
    match = re.search(
        rf"\|{name}; [^|]*surface at ([^;|]+); paper ([\d.]+)[^|]*\|([^|]+)\|\+Z ([^|]+)\|([^|]+)\|"
        r"([^|]+)\|",
        text,
    )
    return tuple(map(float, match.groups()))


@pytest.mark.parametrize("coarse,checked", [(False, -2.275), (True, -2.27)])
def test_later_setup_prints_the_checked_as_cut_face(tmp_path, coarse, checked):
    """Cut on S1's grid (0.005, or 0.010 when coarse), the face reads S1's checked depth
    everywhere S2 prints it, re-shown on S2's 0.005 grid without moving."""
    _, report, html = traveler(
        plan(tmp_path, coarse=coarse), tmp_path / "out", setup=SYNTHETIC_KERNEL
    )
    findings = {(row["rule"], row["subject"]): row for row in report["findings"]}
    (cut,) = findings["coordinates", "S1"]["numbers"]["operations"]
    face_z = cut["dro_to_z"]
    # The face is cut where the DRO stops: rounded up, never deeper, off the authored Z.
    assert (cut["to_z"], face_z) == (NOMINAL, checked)
    text = printed(html)
    assert [float(z) for z in re.findall(r"top at Z (-?\d+\.\d+)", text)] == [0.0, face_z]
    surface, paper, axis_set, jog, must, mirrored = zero(text, "target")
    assert surface == face_z
    assert (axis_set, must, mirrored) == pytest.approx(
        (face_z + paper, face_z + paper + jog, face_z + paper - jog)
    )
    entry, tip, exit_face = map(
        float, re.search(r"\|Z ([^|]+) → ([^|]+)\|breaks through at ([^|]+)\|", text).groups()
    )
    (endpoint,) = findings["blind_depth", "hole"]["numbers"]["endpoints"]
    assert entry == endpoint["dro_entry_z"] == face_z
    # The drill works from the stock bottom it exits, as S2 prints it, to a DRO tip on
    # the grid no deeper than the worked tip.
    assert exit_face == -10.0
    assert on_grid(tip) and endpoint["tip_z"] <= tip < endpoint["tip_z"] + STEP
    assert "-2.278" not in text and (not coarse or "-2.275" not in text)


def test_top_zero_after_an_op_is_the_top_that_op_left(tmp_path):
    """A top zero picked up after op 10 is on the face op 10 cut, not the incoming top
    and not the deeper face op 20 cuts later."""
    operations = ZERO.format("top", "after_op = 10\n") + face(10, NOMINAL) + face(20, -3.0)
    path = bundle(tmp_path, FEATURES.split("[features.hole]")[0], operations)
    _, report, html = traveler(path, tmp_path / "out", setup=SYNTHETIC_KERNEL)
    surface, paper, axis_set, jog, must, mirrored = zero(printed(html), "top")
    assert (surface, axis_set, must, mirrored) == pytest.approx(
        (-2.275, -2.275 + paper, -2.275 + paper + jog, -2.275 + paper - jog)
    )


def test_pickup_follows_the_stock_it_received(tmp_path):
    """S3 receives S1's stock, not the deeper face S2 cut in its own branch: its zero,
    arrival and entry are S1's checked face on S1's 0.010 grid."""
    path = plan(tmp_path, coarse=True, detour=True)
    _, report, html = traveler(path, tmp_path / "out", setup=SYNTHETIC_KERNEL)
    text = printed(html)
    assert zero(text, "target")[0] == -2.27
    endpoints = {
        row["setup"]: row
        for finding in report["findings"]
        if (finding["rule"], finding["subject"]) == ("blind_depth", "hole")
        for row in finding["numbers"]["endpoints"]
    }
    assert endpoints["S3"]["dro_entry_z"] == -2.27
    assert "-2.275" not in text


@pytest.mark.parametrize("exit_mm,stopped", [(0.0, True), (STEP, False)])
def test_rounded_up_through_tip_that_stops_short_is_a_stop(tmp_path, exit_mm, stopped):
    """A DRO tip rounded up off a zero break-through stops the drill point short of the
    exit face, so the drill row stops; one grid step of authored break-through clears it."""
    _, _, html = traveler(plan(tmp_path, exit_mm), tmp_path / "out", setup=SYNTHETIC_KERNEL)
    (cell,) = re.findall(r"<td>(Z -2\.275 → .*?)</td>", html)
    assert ("STOP" in cell) is stopped


@pytest.mark.parametrize(
    "do,drilled,depth,stopped",
    [
        ("drill", BLIND, [BLIND, 20.0], True),
        ("drill", BLIND, [BLIND - STEP, 20.0], False),
        ("drill", BLIND, 20.0, True),
        ("tap", 3.001, [3.001, 3.001], True),
        ("tap", 3.001, [3.0, 3.001], False),
    ],
)
def test_rounded_up_depth_outside_its_depth_band_is_a_stop(tmp_path, do, drilled, depth, stopped):
    """Rounded up, the DRO tip leaves a blind hole or thread shallower than authored.
    Below the band's lower end is a STOP; a band that reaches it clears it; a bare upper
    limit leaves the lower end unknown, and unknown is not a pass."""
    path = plan(tmp_path, depth=depth, do=do, drilled=drilled)
    _, report, html = traveler(path, tmp_path / "out", setup=SYNTHETIC_KERNEL)
    (endpoint,) = [
        row
        for finding in report["findings"]
        if (finding["rule"], finding["subject"]) == ("blind_depth", "hole")
        for row in finding["numbers"]["endpoints"]
    ]
    shown = endpoint["dro_depth_mm"]
    assert drilled - STEP < shown < drilled
    (cell,) = re.findall(r"<td>(Z -2\.275 → .*?)</td>", html)
    assert f"depth {shown:.3f}" in cell
    assert ("STOP" in cell) is stopped
