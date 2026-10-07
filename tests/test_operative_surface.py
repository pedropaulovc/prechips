"""One surface, one printed Z.

S1 finishes a face at an off-grid ``to_z``; the DRO cuts it at the checked ``dro_to_z``,
rounded up on S1's grid. S2 receives S1's stock, starts on that face, zeroes Z on it
and drills from it: every Z it prints for the face is that as-cut value, and every Z it
dials is on its own grid.
"""

import re
from html import unescape
from pathlib import Path

import pytest
from test_cli import SYNTHETIC_KERNEL, traveler
from test_headroom import coordinate_bundle

from prechips.inputs import Bundle
from prechips.model import Features, Inventory, Plan
from prechips.rules import coordinates, tip_endpoints, zero_recipe
from prechips.sheet import _Traveler

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


def plan(tmp_path, exit_mm=1.0, depth=None, do="drill", drilled=BLIND, coarse=False, detour=None):
    """S1 finishes ``target`` to Z -2.27825; S2, same frame, receives S1's stock, starts on
    it, zeroes Z on it and ``do``-s ``hole`` from it: through the 7.72175 mm below it,
    ``exit_mm`` past the exit face, or, given a ``depth`` band (or bare upper limit),
    blind and ``drilled`` deep. Given a ``detour`` Z, an S2 that also receives S1's stock
    refaces ``target`` to it first, and the consumer is S3, which never receives that cut."""
    features = FEATURES
    if depth is not None:
        features = FEATURES.replace("thru = true\n", f"thru = false\ndepth = {depth}\n")
    operations = (
        ZERO.format("top", "")
        + face(10, NOMINAL)
        + (setup("S2") + face(10, detour) if detour is not None else "")
        + setup("S2" if detour is None else "S3")
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


@pytest.mark.parametrize("detour", [NOMINAL - 1.0, NOMINAL])
def test_pickup_follows_the_stock_it_received(tmp_path, detour):
    """S3 receives S1's stock, not S2's refaced one: S2's cut, deeper or to the same
    nominal on its finer grid, is in another branch. S3's arrival, zero and entry are
    S1's checked face on S1's 0.010 grid, whatever S2 checked."""
    path = plan(tmp_path, coarse=True, detour=detour)
    _, report, html = traveler(path, tmp_path / "out", setup=SYNTHETIC_KERNEL)
    text = printed(html)
    arrivals = re.findall(r"arrives from Setup (\S+) — top at Z (-?\d+\.\d+)", text)
    assert arrivals == [("S1", "-2.270"), ("S1", "-2.270")]
    zeros = re.findall(r"\|target; [^|]*surface at ([^;|]+);", text)
    assert [float(z) for z in zeros] == [-2.27, -2.27]
    endpoints = {
        row["setup"]: row
        for finding in report["findings"]
        if (finding["rule"], finding["subject"]) == ("blind_depth", "hole")
        for row in finding["numbers"]["endpoints"]
    }
    assert endpoints["S3"]["dro_entry_z"] == -2.27


FRAME = {"origin": [0.0] * 3, "x": [1.0, 0, 0], "y": [0, 1.0, 0], "z": [0, 0, 1.0]}


def turned_from(tmp_path, cut, shaft_xy):
    """S1 on a 0.010 mill ``cut``-s (finish_face ``target``, x 0..20 y 0..10, or
    finish_pocket ``other``, x/y 10..20) to Z -2.27825; L2, a 0.005 lathe receiving S1's
    stock in the same frame, turns ``shaft`` (X/Y footprint ``shaft_xy``, or none) from
    that Z. Returns L2's (start Z of the op row, feature map text)."""
    plane = {"kind": "plane", "frame": "model", "requirements": []}
    shaft = {"kind": "shaft", "frame": "model", "dia": 6.0, "z_mm": [NOMINAL, -10.0]}
    if shaft_xy:
        shaft["bounds"] = {"x": shaft_xy, "y": shaft_xy, "z": [-10.0, NOMINAL]}
    features = {
        "target": {**plane, "bounds": {"x": [0.0, 20.0], "y": [0.0, 10.0], "z": [NOMINAL, 0.0]}},
        "other": {**plane, "bounds": {"x": [10.0, 20.0], "y": [10.0, 20.0], "z": [NOMINAL, 0.0]}},
        "shaft": {**shaft, "requirements": []},
    }
    do, feature = cut
    setups = [
        {
            "id": "S1",
            "stock_in": "stock",
            "machine": "coarse",
            "frame": "A",
            "stock_state": {"top_z": 0.0},
            "ops": [{"op": 10, "do": do, "feature": feature, "tool": "cutter", "to_z": NOMINAL}],
        },
        {
            "id": "L2",
            "stock_in": "S1",
            "machine": "fine",
            "frame": "A",
            "stock_state": {"top_z": NOMINAL},
            "ops": [
                {
                    "op": 10,
                    "do": "finish_turn",
                    "feature": "shaft",
                    "tool": "cutter",
                    "z_from": NOMINAL,
                    "z_to": -10.0,
                }
            ],
        },
    ]
    direction = {"x": "right", "y": "away", "z": "up"}
    dro = {"controller": "EL400", "mode": "abs", "radius_mode": False, "direction": direction}
    machines = {
        "coarse": {"kind": "mill", "resolution_mm": 2 * STEP},
        "fine": {"kind": "lathe", "resolution_mm": STEP},
    }
    tools = {"cutter": {"kind": "endmill", "dia_mm": 6.0, "nose_radius_mm": 0.0}}
    frames = {"A": {**FRAME, "binding": "nominal"}, "model": {**FRAME, "binding": "nominal"}}
    bundle = Bundle(
        Plan.model_validate(
            {"part": "p", "features": "features.toml", "dro": dro, "setups": setups}
        ).model_dump(exclude_unset=True),
        Features.model_validate(
            {"part": "p", "units": "mm", "frames": frames, "features": features}
        ).model_dump(exclude_unset=True),
        Inventory.model_validate({"machines": machines, "tools": tools}).model_dump(
            exclude_unset=True
        ),
        {},
        {},
        {},
        {},
        Path(tmp_path),
    )
    findings = [
        *coordinates.evaluate(bundle),
        *tip_endpoints.evaluate(bundle),
        *zero_recipe.evaluate(bundle),
    ]
    sheet = _Traveler(bundle, findings, {}, {})
    lathe = bundle.plan["setups"][1]
    sheet.setup = lathe
    (row,) = sheet.tip(lathe, lathe["ops"][0])
    start = re.fullmatch(r"Z (-?\d+\.\d+) → -10\.000", row)[1]
    # The lathe map prints the drawing Ø limits (here none) apart from the turn-to Ø.
    mapped = re.search(
        r"\|shaft\|+[^|]*\|+Ø6(?:\.0+)?\|+(-?\d+\.\d+)\|+-10\.000\|",
        unescape(re.sub(r"<[^>]+>", "|", sheet.feature_map(lathe))),
    )[1]
    return start, mapped


@pytest.mark.parametrize(
    "cut,shaft_xy,printed",
    [
        (("finish_face", "target"), [2.0, 8.0], "-2.270"),
        (("finish_pocket", "other"), [2.0, 8.0], "-2.275"),
        # Half the shaft lies outside the face's x/y 0..20 x 0..10: overlap is not cover.
        (("finish_face", "target"), [-3.0, 3.0], "-2.275"),
        (("finish_face", "target"), None, "-2.275"),
    ],
)
def test_turned_start_links_only_a_cut_that_covers_it(tmp_path, cut, shaft_xy, printed):
    """A turned surface starts on S1's coarse as-cut -2.270 only when S1's cut covers its
    X/Y footprint; a disjoint pocket at the same nominal Z, or a shaft with no footprint
    to prove it, starts on the nominal as L2's 0.005 DRO shows it. Its op row and the
    feature map print the same value."""
    assert turned_from(tmp_path, cut, shaft_xy) == (printed, printed)


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
