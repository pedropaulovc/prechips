"""Manual-mill arcs (docs/plan.md "Manual arcs"): the PM-30MV moves one handwheel at a time.

An arc is laid out on the part, roughed outside the line in single-axis stairs or a chain
of drilled holes, then filed to the line against filing buttons or a template and checked
with a radius gauge; or it is cut as straight chords, or turned under the cutter on a
rotary table. Every stair corner and hole stays outside the finished line, the file never
meets more than the shop's cap, chords stay inside the radial band, and every unknown
input stays unknown, never a pass.
"""

import dataclasses
import itertools
import math
import re
from html import unescape

import pytest

from prechips.inputs import load_bundle
from prechips.kernel import build_job
from prechips.rules import coordinates, manual_arc
from prechips.sheet import _Traveler

# A Ø19.8-20.2 boss about model (20, 10): frame A puts its centre at setup (15, 8); the
# rotary frame puts it on the table axis at setup X0 Y0. Its R9.9-R10.1 band is 0.2 wide.
ARC = (
    "kind = 'boss'\nrequirements = ['dia']\nat = [20.0, 10.0, 0.0]\ndia = [19.8, 20.2]\n"
    "dia_nominal = 20.0\n"
)
SHIFTED = "[5.0, 2.0, 1.0]"
ON_AXIS = "[20.0, 10.0, 1.0]"
CAP = 0.5
POLICY = (
    '[required]\ncoordinates = "*"\nmanual_arc = "*"\n'
    f"[numbers]\nmax_filing_stock_mm = {CAP}\n"
    '[numbers_cite]\nmax_filing_stock_mm = "example filing cap"\n'
    "[numbers_verify]\nmax_filing_stock_mm = false\n"
)
INVENTORY = (
    "[machines.mill]\nkind = 'mill'\nverify = false\n"
    "[machines.mill.spindle]\nrotation = 'cw'\n"
    "[tools.cutter]\nkind = 'endmill'\nmaterial = 'HSS'\ncenter_cutting = true\ndia_mm = 6.0\n"
    "verify = false\n"
    "[tools.drill]\nkind = 'drill'\ndia_mm = 3.0\npoint_angle = 118.0\nverify = false\n"
    "[tools.bore-drill]\nkind = 'drill'\ndia_mm = 6.0\npoint_angle = 118.0\nverify = false\n"
    "[fixtures.table]\nkind = 'rotary_table'\ngraduation_deg = 1.0\nvernier_deg = 0.1\n"
    "dial_increases = 'clockwise'\nbore_dia_mm = 6.0\nmax_work_mm = 150.0\nverify = false\n"
    # Ø19.99-20.00 buttons bored Ø6.00-6.01 with 0.004 OD runout, on a Ø5.99-6.00 pin.
    "[fixtures.buttons]\nkind = 'filing_buttons'\nbutton_dia_limits_mm = [19.99, 20.0]\n"
    "button_bore_limits_mm = [6.0, 6.01]\npin_dia_limits_mm = [5.99, 6.0]\n"
    "button_runout_mm = 0.004\nverify = false\n"
    "[gauges.radius-gauge]\nkind = 'radius_gauge'\nrange_mm = [1.0, 25.0]\nverify = false\n"
    "[gauges.small-gauge]\nkind = 'radius_gauge'\nrange_mm = [1.0, 7.5]\nverify = false\n"
    "[gauges.template]\nkind = 'profile_gauge'\nrange_mm = [9.0, 11.0]\nverify = false\n"
)


def op(number, action, contour=None, *, feature="target", tool="cutter", allowance=None, **more):
    text = (
        f"[[setups.ops]]\nop = {number}\ndo = '{action}'\nfeature = '{feature}'\n"
        f"tool = '{tool}'\nholder = 'unknown'\nto_z = -1.0\ndirection = 'conventional'\n"
    )
    if allowance is not None:
        text += f"rough_allowance_mm = {allowance}\n"
    if contour is not None:
        text += f"contour = {contour}\n"
    return text + "".join(f"{key} = {value}\n" for key, value in more.items())


def bench_op(number, action, **more):
    text = f"[[setups.ops]]\nop = {number}\ndo = '{action}'\nfeature = 'target'\n"
    return text + "".join(f"{key} = {value}\n" for key, value in more.items())


DRILL_BORE = op(10, "drill", feature="bore", tool="bore-drill")


def scratch(
    tmp_path, ops, *, origin=SHIFTED, hold="fixture = 'unknown'", policy=POLICY, target=ARC
):
    """A one-setup mill bundle cutting ``ops`` (TOML text) on the banded ``target`` (the
    boss :data:`ARC` unless given) with the hole ``bore`` on its axis and ``offset`` beside
    it."""
    root = tmp_path / "manual-arc"
    root.mkdir(parents=True)
    plan = root / "plan.toml"
    plan.write_text(
        'part = "manual-arc"\nfeatures = "features.toml"\n'
        "[paths]\ninventory = 'inventory.toml'\npolicy = 'policy.toml'\n"
        "cutting_data = 'cutting.toml'\n[stock]\nmaterial = 'scratch steel'\n"
        "[[setups]]\nid = 'S1'\nmachine = 'mill'\nframe = 'A'\n"
        "coolant = 'unknown'\ndeburr_mm = 'unknown'\n"
        f"[setups.hold]\n{hold}\n"
        "[setups.stock_state]\ntop_z = 0.0\nbottom_z = -10.0\n"
        "local_thickness = { target = 10.0 }\n" + ops,
        encoding="utf-8",
    )
    (root / "features.toml").write_text(
        'part = "manual-arc"\nunits = "mm"\nprecision = 2\n'
        f"[frames.A]\norigin = {origin}\n"
        "x = [1.0, 0.0, 0.0]\ny = [0.0, 1.0, 0.0]\nz = [0.0, 0.0, 1.0]\n"
        'binding = "measured"\n'
        "[frames.model]\norigin = [0.0, 0.0, 0.0]\n"
        "x = [1.0, 0.0, 0.0]\ny = [0.0, 1.0, 0.0]\nz = [0.0, 0.0, 1.0]\n"
        f"[features.target]\nframe = 'model'\n{target}"
        "[features.bore]\nkind = 'hole'\nframe = 'model'\nrequirements = []\n"
        "at = [20.0, 10.0, 0.0]\ndia = [6.0, 6.03]\nthru = true\n"
        "[features.offset]\nkind = 'hole'\nframe = 'model'\nrequirements = []\n"
        "at = [26.0, 10.0, 0.0]\ndia = [6.0, 6.03]\nthru = true\n",
        encoding="utf-8",
    )
    (root / "inventory.toml").write_text(INVENTORY, encoding="utf-8")
    (root / "policy.toml").write_text(policy, encoding="utf-8")
    # Every end mill these plans plunge has a cited plunge feed (level_entry).
    (root / "cutting.toml").write_text(
        "revision = 1\n[aliases]\n'scratch steel' = 'steel'\n"
        "[[plunge]]\nmaterial_class = 'steel'\ntool_material = 'HSS'\n"
        "diameter_range = [0.0, 50.0]\nfeed_mm_rev = 0.05\ncite = 'scratch plunge feed'\n",
        encoding="utf-8",
    )
    return plan


def coordinates_row(plan, stock_bbox=None):
    bundle = load_bundle(plan)
    if stock_bbox is not None:
        kernel = {"status": "ok", "setups": {"S1": {"stock_bbox_mm": stock_bbox}}}
        bundle = dataclasses.replace(bundle, kernel=kernel)
    return next(row for row in coordinates.evaluate(bundle) if row.subject == "S1")


def manual_row(plan, number):
    rows = {row.subject: row for row in manual_arc.evaluate(load_bundle(plan))}
    return rows[f"S1:{number}"]


def arcs(row, number):
    return [table for table in row.numbers["arc_table"] if table["op"] == number]


def errors(row):
    return " ".join(row.numbers.get("arc_errors", []))


def debts(row):
    return " ".join(row.numbers.get("arc_debts", []))


def legs(points, samples=16):
    for a, b in itertools.pairwise(points):
        for k in range(samples + 1):
            yield [a[i] + k / samples * (b[i] - a[i]) for i in range(2)]


def on_grid(value, step=0.001):
    return abs(value / step - round(value / step)) < 1e-6


def assert_printed_chord_band(table, band, scale=1.0):
    """Intersect the cutter's inward tangent lines in physical mm, not reported radii."""
    centre = [v * scale for v in table["centre_setup_xy"]]
    lines = []
    for chord in table["chords"]:
        cut = chord["cut"]
        assert cut["along"] in ("X", "Y")
        # This fixture's dial rises clockwise; undo its physical clockwise index.
        angle = math.radians(cut["index_deg"] or 0.0)
        c, s = math.cos(angle), math.sin(angle)
        normal = [-s, c] if cut["along"] == "X" else [c, s]
        tangent = [c, s] if cut["along"] == "X" else [-s, c]
        level = cut["at"] * scale
        centre_level = sum(a * b for a, b in zip(normal, centre, strict=True))
        scrap = math.copysign(1.0, level - centre_level)
        lines.append((normal, level - scrap * 3.0, tangent, cut))

    def join(first, second):
        (a, da, _, _), (b, db, _, _) = first, second
        det = a[0] * b[1] - a[1] * b[0]
        assert abs(det) > 1e-9
        return [(da * b[1] - a[1] * db) / det, (a[0] * db - da * b[0]) / det]

    corners = [join(lines[k - 1], line) for k, line in enumerate(lines)]
    for k, (_, _, tangent, cut) in enumerate(lines):
        a, b = corners[k], corners[(k + 1) % len(corners)]
        # The printed finite stroke must reach both joins, not merely its infinite line.
        ends = sorted([cut["from"] * scale, cut["to"] * scale])
        for point in (a, b):
            feed = sum(v * t for v, t in zip(point, tangent, strict=True))
            assert ends[0] - 1e-6 <= feed <= ends[1] + 1e-6
        delta = [b[i] - a[i] for i in range(2)]
        fraction = sum((centre[i] - a[i]) * delta[i] for i in range(2)) / sum(v * v for v in delta)
        near = [a[i] + min(1.0, max(0.0, fraction)) * delta[i] for i in range(2)]
        assert math.dist(centre, near) >= band[0] - 1e-6
        assert max(math.dist(centre, a), math.dist(centre, b)) <= band[1] + 1e-6


def change(path, old, new):
    """Rewrite the first ``old`` in the scratch file ``path`` as ``new``."""
    text = path.read_text(encoding="utf-8")
    assert old in text, old
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


def _ray_span(u, p, q, r):
    """The (entry, exit) distances along the unit ray ``u`` from the arc centre through the
    capsule a cutter of radius ``r`` sweeps from ``p`` to ``q`` (centre-relative), or None."""
    spans = []
    for c in (p, q):
        along = c[0] * u[0] + c[1] * u[1]
        disc = along * along - (c[0] ** 2 + c[1] ** 2) + r * r
        if disc >= 0:
            spans.append((along - math.sqrt(disc), along + math.sqrt(disc)))
    length = math.dist(p, q)
    if length > 0:
        d = [(q[i] - p[i]) / length for i in range(2)]
        low, high = -math.inf, math.inf
        for axis, a, b in ((d, 0.0, length), ([-d[1], d[0]], -r, r)):
            speed = u[0] * axis[0] + u[1] * axis[1]
            start = -(p[0] * axis[0] + p[1] * axis[1])
            if abs(speed) < 1e-15:
                low = low if a <= start <= b else math.inf
                continue
            t0, t1 = sorted(((a - start) / speed, (b - start) / speed))
            low, high = max(low, t0), min(high, t1)
        if low <= high:
            spans.append((low, high))
    return (min(s for s, _ in spans), max(e for _, e in spans)) if spans else None


def radial_stock(table, cutter, scale=1.0, step_deg=0.1):
    """The most material (mm) a printed stair leaves outside its wall along any radius of
    the arc, sampled ``step_deg`` apart over its span: a ray from the centre meets the
    capsule a cutter of radius ``cutter`` (plan units) sweeps along each printed move, and
    the material runs from the wall to the nearest such capsule. Independent of the rule."""
    centre, wall = table["centre_setup_xy"], table["wall_radius_mm"]
    convex = table["cutter_centre_radius_mm"] > wall
    points = [[row["dro_xy"][i] - centre[i] for i in range(2)] for row in table["rows"]]
    turns = [math.atan2(p[1], p[0]) for p in points]
    unwrapped = [turns[0]]
    for a, b in itertools.pairwise(turns):
        unwrapped.append(unwrapped[-1] + (b - a + math.pi) % math.tau - math.pi)
    low, high = (0.0, math.tau) if table["full_circle"] else (min(unwrapped), max(unwrapped))

    def gap(a, b):
        return abs((a - b + math.pi) % math.tau - math.pi)

    moves = []  # each move with the angular reach of its capsule about the centre
    for p, q in [*((p, p) for p in points), *itertools.pairwise(points)]:
        near = min(math.hypot(*p), math.hypot(*q))
        reach = math.asin(cutter / near) if near > cutter else math.pi
        ends = [math.atan2(p[1], p[0]), math.atan2(q[1], q[0])]
        moves.append((p, q, ends, reach + gap(*ends)))
    worst = 0.0
    for k in range(round((high - low) / math.radians(step_deg)) + 1):
        theta = low + k * math.radians(step_deg)
        u = [math.cos(theta), math.sin(theta)]
        spans = [
            span
            for p, q, ends, reach in moves
            if min(gap(theta, end) for end in ends) <= reach
            and (span := _ray_span(u, p, q, cutter)) is not None
            and span[1] >= 0
        ]
        if not spans:
            return math.inf
        left = min(s for s, _ in spans) - wall if convex else wall - max(e for _, e in spans)
        worst = max(worst, left * scale)
    return worst


def test_stairs_step_one_handwheel_at_a_time_outside_the_line(tmp_path):
    row = coordinates_row(
        scratch(
            tmp_path,
            op(20, "rough_profile", "{ method = 'stairs', cusp_mm = 0.25 }", allowance=0.2),
        )
    )
    assert row.status == "pass", row.sentence
    (table,) = arcs(row, 20)
    printed = [r["dro_xy"] for r in table["rows"]]
    assert all(r["jog"] in {"X", "Y"} for r in table["rows"][1:])
    for a, b in itertools.pairwise(printed):
        assert a[0] == b[0] or a[1] == b[1], f"{a} -> {b} moves two handwheels"
    # Every point the cutter edge sweeps stays outside the R10.1 line.
    assert min(math.dist(p, (15.0, 8.0)) for p in legs(printed)) - 3.0 >= 10.1 - 1e-6
    assert table["line_clear_mm"] >= 0
    assert radial_stock(table, 3.0) <= table["stock_left_mm"] + 1e-9
    assert table["stock_left_mm"] <= table["stock_cap_mm"] == CAP


# A concave R29.9-R30.1 arc about model (20, 40) spanning ±36.87° about its lowest point,
# part below it, like the rocker's top edge: the cutter centre dips to that point.
DISH = (
    "kind = 'profile'\nrequirements = ['radius']\nradius = [29.9, 30.1]\nradius_nominal = 30.0\n"
    "arc_centre = [20.0, 40.0, 0.0]\nend = [38.0, 16.0]\n"
)


@pytest.mark.parametrize("target", [ARC, DISH], ids=["convex", "concave"])
@pytest.mark.parametrize("allowance", [0.2, 0.25])
def test_stair_stock_bounds_the_material_left_along_every_radius(tmp_path, target, allowance):
    # At a stair's corner notch the material runs farther along the radius than to the
    # nearest cutter edge: the reported stock bounds every radius, and stays in the cap.
    contour = "{ method = 'stairs', cusp_mm = 0.25 }"
    row = coordinates_row(
        scratch(tmp_path, op(20, "rough_profile", contour, allowance=allowance), target=target)
    )
    assert row.status == "pass", row.sentence
    (table,) = arcs(row, 20)
    assert radial_stock(table, 3.0) <= table["stock_left_mm"] + 1e-9
    assert table["stock_left_mm"] <= table["stock_cap_mm"] == CAP


@pytest.mark.parametrize(
    ("target", "cusp"), [(ARC, 0.195), (DISH, 0.175)], ids=["convex", "concave"]
)
def test_a_stair_respaced_past_a_finer_excess_than_its_step_keeps_its_cusp(tmp_path, target, cusp):
    # The DRO grid leaves these stairs a hair over cusp_mm, finer than one spacing step:
    # respacing must still move a row and land the printed stair within cusp_mm.
    contour = f"{{ method = 'stairs', cusp_mm = {cusp} }}"
    row = coordinates_row(
        scratch(tmp_path, op(20, "rough_profile", contour, allowance=0.1), target=target)
    )
    assert row.status == "pass", row.sentence
    (table,) = arcs(row, 20)
    assert table["stair_cusp_mm"] <= cusp
    assert radial_stock(table, 3.0) <= table["stock_left_mm"] + 1e-9


@pytest.mark.parametrize("target", [ARC, DISH], ids=["convex", "concave"])
def test_a_stair_never_steps_one_handwheel_twice_running(tmp_path, target):
    # A row where the arc is tangent to a setup axis is reached and left on one handwheel:
    # printed as its own stop, it splits one move, or (the concave dip) runs the handwheel
    # down and straight back up through backlash. Each move turns the other handwheel.
    row = coordinates_row(
        scratch(
            tmp_path,
            op(20, "rough_profile", "{ method = 'stairs', cusp_mm = 0.25 }", allowance=0.2),
            target=target,
        )
    )
    assert row.status == "pass", row.sentence
    (table,) = arcs(row, 20)
    jogs = [r["jog"] for r in table["rows"][1:]]
    assert all(a != b for a, b in itertools.pairwise(jogs)), jogs
    assert table["stair_cusp_mm"] <= table["cusp_mm"]


STAIR_CONTOUR = "{ method = 'stairs', cusp_mm = 0.25 }"


def leave_errors(row):
    return row.numbers.get("allowance_errors", [])


@pytest.mark.parametrize("key", ["rough_allowance_mm", "stock_to_leave_mm"])
@pytest.mark.parametrize(("leave", "status"), [(-0.2, "error"), (0.0, "pass"), (0.2, "pass")])
def test_a_rough_stair_stands_off_the_line_by_a_nonnegative_leave(tmp_path, key, leave, status):
    # The stair cutter centre rides R10 + 3 + leave; a negative leave would put every stair
    # corner inside the finished line, so it is refused and nothing is printed.
    stairs = op(20, "rough_profile", STAIR_CONTOUR, **{key: leave})
    row = coordinates_row(scratch(tmp_path, stairs))
    assert row.status == status, row.sentence
    assert bool(leave_errors(row)) == (leave < 0)
    if status == "error":
        assert not arcs(row, 20), "a refused rough prints no table"
        return
    (table,) = arcs(row, 20)
    assert table["cutter_centre_radius_mm"] == pytest.approx(13.0 + leave)


@pytest.mark.parametrize(
    ("ops", "kwargs"),
    [
        (
            op(20, "rough_profile", "{ method = 'chain_drill', pitch_mm = 5.0 }", tool="drill"),
            {},
        ),
        (op(20, "finish_profile", "{ method = 'chords', count = 24 }", approach_mm=2.0), {}),
        (
            DRILL_BORE
            + op(
                20,
                "finish_profile",
                "{ method = 'rotary_table', step_deg = 30.0, centre_by = 'pin', "
                "centre_feature = 'bore' }",
            ),
            {"origin": ON_AXIS},
        ),
        (op(20, "rough_pocket"), {}),
        (op(20, "finish_pocket"), {}),
    ],
    ids=["chain-drill", "chords-paired-rough", "rotary-paired-rough", "pocket", "finish-pocket"],
)
@pytest.mark.parametrize("leave", [-0.3, 0.0, 0.3])
def test_a_leave_inside_the_finished_part_is_an_error_however_the_op_cuts(
    tmp_path, ops, kwargs, leave
):
    # Whatever cuts the op (a drilled chain, chords or the rotary table with their paired
    # rough, a pocket roughing or finishing off a leave), a negative leave is a cut into
    # the finished part: an error, never a shifted band or cut, and no stage of it prints.
    ops = ops.replace("feature = 'target'\n", f"feature = 'target'\nrough_allowance_mm = {leave}\n")
    row = coordinates_row(
        scratch(tmp_path, ops, hold="fixture = 'table'", **kwargs), stock_bbox=SWING
    )
    assert bool(leave_errors(row)) == (leave < 0)
    if leave < 0:
        assert row.status == "error", row.sentence
        assert not arcs(row, 20)
        assert not [
            p
            for p in row.numbers["profiles"]
            if p["op"] == 20 and isinstance(p["cutter_centre"], list)
        ]
        return
    printed = arcs(row, 20)
    if "chain_drill" in ops:
        # A chain alone leaves at least a drill radius, exceeding this shop's filing cap.
        assert row.status == "error", row.sentence
        assert row.numbers["arc_errors"]
        assert not printed
        (profile,) = [p for p in row.numbers["profiles"] if p["op"] == 20]
        assert profile["offset_mm"] == pytest.approx(1.5 + leave)
        assert profile["cutter_centre"] == "unknown"
    elif "chords" in ops or "rotary_table" in ops:
        assert row.status == "pass", row.sentence
        assert len(printed) == 2
        stages = {table["stage"]: table for table in printed}
        assert set(stages) == {"rough", "finish"}
        for stage, allowance in (("rough", leave), ("finish", 0.0)):
            table = stages[stage]
            assert table["allowance_mm"] == allowance
            assert table["offset_mm"] == pytest.approx(3.0 + allowance)
            assert table["cutter_centre_radius_mm"] == pytest.approx(13.0 + allowance)
            assert len(table["rows"]) > 1
            if "rotary" in table:
                assert table["rotary"]["offset_x"] == pytest.approx(13.0 + allowance)
            else:
                assert len(table["chords"]) == 24
                assert_printed_chord_band(table, (9.9 + allowance, 10.1 + allowance))
    else:
        # These pocket aliases author no contour: coordinates accepts the allowance but
        # must not invent a tool path or claim that absent stage geometry is known.
        assert row.status == "pass", row.sentence
        assert not printed
        assert not [p for p in row.numbers["profiles"] if p["op"] == 20]


CHAIN = op(
    20, "rough_profile", "{ method = 'chain_drill', pitch_mm = 5.0 }", tool="drill", allowance=0.2
)


def test_chain_drill_keeps_every_full_hole_outside_and_a_web_between(tmp_path):
    # Broken out along the hole centres, a chain leaves 0.2 + a 1.5 drill radius: more than
    # the 0.5 cap, so the chain alone is refused and a finer stair rough must follow it.
    alone = coordinates_row(scratch(tmp_path / "alone", CHAIN))
    assert alone.status == "error"
    assert "chain drill leaves up to 1.70" in errors(alone)
    assert "more than the shop's 0.5 cap" in errors(alone)
    stairs = op(30, "rough_profile", "{ method = 'stairs', cusp_mm = 0.25 }", allowance=0.2)
    row = coordinates_row(scratch(tmp_path / "recut", CHAIN + stairs))
    assert row.status == "pass", row.sentence
    (table,) = arcs(row, 20)
    holes = [r["dro_xy"] for r in table["rows"]]
    assert all(math.dist(p, (15.0, 8.0)) - 1.5 >= 10.1 - 1e-6 for p in holes)
    assert all(math.dist(a, b) > 3.0 for a, b in itertools.pairwise(holes))
    assert table["stock_left_mm"] == pytest.approx(1.7, abs=1e-3)
    assert table["recut_by"] == "S1 op 30"


def test_chain_drill_holes_closer_than_a_drill_leave_no_web(tmp_path):
    row = coordinates_row(
        scratch(
            tmp_path,
            op(
                20,
                "rough_profile",
                "{ method = 'chain_drill', pitch_mm = 2.0 }",
                tool="drill",
                allowance=0.2,
            ),
        )
    )
    assert row.status == "error"
    assert "no web" in errors(row)


def segment_distance(point, a, b):
    span = [b[i] - a[i] for i in range(2)]
    length = span[0] ** 2 + span[1] ** 2
    t = 0.0 if not length else ((point[0] - a[0]) * span[0] + (point[1] - a[1]) * span[1]) / length
    t = min(1.0, max(0.0, t))
    return math.dist(point, [a[i] + t * span[i] for i in range(2)])


def fine_chain(tmp_path, target, more=""):
    """Ø0.5 holes up to 8 apart, 0.1 outside ``target``'s line, then the ``more`` ops."""
    contour = "{ method = 'chain_drill', pitch_mm = 8.0 }"
    chain = op(20, "rough_profile", contour, tool="drill", allowance=0.1)
    plan = scratch(tmp_path, chain + more, target=target)
    inventory = plan.with_name("inventory.toml")
    change(inventory, "kind = 'drill'\ndia_mm = 3.0", "kind = 'drill'\ndia_mm = 0.5")
    return coordinates_row(plan)


@pytest.mark.parametrize(
    ("target", "message"),
    [(ARC, "past the line"), (DISH, "more than the shop's 0.5 cap")],
    ids=["convex", "concave"],
)
def test_a_chain_breaks_out_along_its_hole_centres_outside_the_line_and_in_the_cap(
    tmp_path, target, message
):
    # Every hole clears the line, but the webs break out along the straight runs between
    # hole centres: on the R10 boss a run dips inside the line, an error even when a later
    # rough recuts it; on the R30 dish a run leaves more than the cap for the file.
    alone = fine_chain(tmp_path / "alone", target)
    assert alone.status == "error" and message in errors(alone)
    fine = op(30, "rough_profile", "{ method = 'stairs', cusp_mm = 0.25 }", allowance=0.2)
    recut = fine_chain(tmp_path / "recut", target, fine)
    if target == ARC:
        assert recut.status == "error" and message in errors(recut)
        return
    assert recut.status == "pass", recut.sentence
    (table,) = arcs(recut, 20)
    centre, wall = table["centre_setup_xy"], table["wall_radius_mm"]
    holes = [row["dro_xy"] for row in table["rows"]]
    deepest = max(wall - segment_distance(centre, a, b) for a, b in itertools.pairwise(holes))
    assert deepest > CAP
    assert table["stock_left_mm"] >= deepest - 1e-9


# A synthetic finite outline, unrelated to any consumer STEP: the upper concave R10
# meets a land, a corner and a taper, then the convex R20 bottom arc. Both sides mirror.
JOIN_TOP = (6.0, -8.0)
JOIN_TIP = (16.0, -10.0)
JOIN_BOTTOM = (12.0, -16.0)
JOIN_DRILL = 0.5
JOIN_ALLOWANCE = 0.1
JOIN_PITCH = 1.5


def joined_chain_plan(tmp_path, *, cap=1.0, bounded=False, tip=JOIN_TIP):
    """Build only temporary synthetic inputs; kernel facts are injected per test."""
    policy = '[required]\ncoordinates = "*"\nmanual_arc = "*"\n'
    if cap is not None:
        policy += (
            f"[numbers]\nmax_filing_stock_mm = {cap}\n"
            '[numbers_cite]\nmax_filing_stock_mm = "synthetic test filing cap"\n'
            "[numbers_verify]\nmax_filing_stock_mm = false\n"
        )
    target = (
        "kind = 'profile'\nrequirements = []\narc_centre = [0.0, 0.0, 0.0]\n"
        "bottom_radius = 20.0\nbottom_radius_nominal = 20.0\n"
        f"radial_tip_end = {list(tip)}\nbottom_end = {list(JOIN_BOTTOM)}\n"
        "top_edge_feature = 'top'\nmirror_symmetric = true\n"
        "[features.top]\nkind = 'profile'\nframe = 'model'\nrequirements = []\n"
        "radius = 10.0\nradius_nominal = 10.0\narc_centre = [0.0, 0.0, 0.0]\n"
        f"end = {list(JOIN_TOP)}\n"
    )
    more = (
        {"stock_removal_bounds": ("{ x = [-30.0, 30.0], y = [-30.0, 30.0], z = [-10.0, 0.0] }")}
        if bounded
        else {}
    )
    plan = scratch(
        tmp_path,
        op(
            20,
            "rough_profile",
            f"{{ method = 'chain_drill', pitch_mm = {JOIN_PITCH} }}",
            tool="drill",
            allowance=JOIN_ALLOWANCE,
            **more,
        ),
        target=target,
        policy=policy,
    )
    change(
        plan.with_name("inventory.toml"),
        "kind = 'drill'\ndia_mm = 3.0",
        f"kind = 'drill'\ndia_mm = {JOIN_DRILL}",
    )
    return plan


def joined_chain_finding(bundle, *, pre_kernel=False):
    return next(
        row for row in coordinates.evaluate(bundle, pre_kernel=pre_kernel) if row.subject == "S1"
    )


def joined_chain_lines(row):
    return [line for line in row.numbers["line_table"] if line["op"] == 20]


def exact_join_vertices(tip=JOIN_TIP):
    """Independently intersect the two offset lines and their finite arc endpoints."""
    offset = JOIN_DRILL / 2 + JOIN_ALLOWANCE

    def cross(a, b):
        return a[0] * b[1] - a[1] * b[0]

    def line(a, b):
        span = math.dist(a, b)
        u = [(b[i] - a[i]) / span for i in range(2)]
        return [a[0] - offset * u[1], a[1] + offset * u[0]], u

    def circle(p, u, radius, endpoint):
        along = sum(p[i] * u[i] for i in range(2))
        root = math.sqrt(along**2 - sum(v**2 for v in p) + radius**2)
        points = [[p[i] + t * u[i] for i in range(2)] for t in (-along - root, -along + root)]
        return min(points, key=lambda point: math.dist(point, endpoint))

    (p, u), (q, v) = line(JOIN_TOP, tip), line(tip, JOIN_BOTTOM)
    t = cross([q[i] - p[i] for i in range(2)], v) / cross(u, v)
    miter = [p[i] + t * u[i] for i in range(2)]
    return [circle(p, u, 10.0 - offset, JOIN_TOP), miter, circle(q, v, 20.0 + offset, JOIN_BOTTOM)]


def finite_wall_residual(points, walls, tolerance=1e-10):
    """Maximum nearest-finite-wall distance over a retained break-out polyline.

    Distance to a finite segment is convex along each break-out segment. Thus the
    smaller of the walls' endpoint maxima bounds the nearest-wall distance above.
    Subdivide only intervals whose bound can still exceed the observed maximum.
    This oracle uses point/segment distances, never wall normals or ray intersections.
    """
    distances = [[segment_distance(point, *wall) for wall in walls] for point in points]
    worst = max(min(values) for values in distances)
    pending = [
        (a, b, da, db)
        for (a, da), (b, db) in itertools.pairwise(zip(points, distances, strict=True))
    ]
    while pending:
        a, b, da, db = pending.pop()
        upper = min(max(x, y) for x, y in zip(da, db, strict=True))
        if upper <= worst + tolerance:
            continue
        middle = [(x + y) / 2 for x, y in zip(a, b, strict=True)]
        dm = [segment_distance(middle, *wall) for wall in walls]
        worst = max(worst, min(dm))
        pending.extend(((a, middle, da, dm), (middle, b, dm, db)))
    return worst


def printed_join_residual(row, tip=JOIN_TIP):
    """Rebuild stock from printed centre break-outs and the fixture's finite walls."""
    stock = JOIN_DRILL / 2 + JOIN_ALLOWANCE
    for arc in arcs(row, 20):
        centre, wall = arc["centre_setup_xy"], arc["wall_radius_mm"]
        holes = [item["dro_xy"] for item in arc["rows"]]
        stock = max(stock, *(math.dist(point, centre) - wall for point in holes))
    for line in joined_chain_lines(row):
        side = 1 if line["side"] == "+X" else -1
        vertices = [
            [side * point[0] - 5.0, point[1] - 2.0] for point in (JOIN_TOP, tip, JOIN_BOTTOM)
        ]
        stock = max(stock, finite_wall_residual(line["dro_xy"], list(itertools.pairwise(vertices))))
    return stock


def synthetic_join_clip(bundle, requested, select, *, regenerated=False):
    """Inject selected authored rows, their true-curve regeneration, or raw clip points."""
    paths = []
    for table in coordinates.checkpoints("S1:20", requested.numbers, 20):
        selected = list(select(table))
        if regenerated:
            original = next(
                item
                for item in requested.numbers[table["kind"]]
                if coordinates.row_id("S1:20", table["kind"], item, 0) == table["rows"][0][0]
            )
            points = []
            for index in selected:
                if table["kind"] == "arc_table":
                    item = original["rows"][index]
                else:
                    item = {
                        key: original[key][index]
                        for key in ("model_xy", "setup_xy", "dro_xy", "overshoot")
                    }
                point = {
                    "generated": True,
                    "exact_xy": item["setup_xy"],
                    "dro_xy": item["dro_xy"],
                    "model_xy": item["model_xy"],
                    "overshoot": item.get("overshoot", False),
                }
                if "angle_deg" in item:
                    point["angle_deg"] = item["angle_deg"]
                points.append(point)
        else:
            points = [{"row": item} if isinstance(item, int) else dict(item) for item in selected]
        entry = {
            "table": table["rows"][0][0],
            "rows": len(table["rows"]),
            "pieces": [points] if points else [],
        }
        if regenerated:
            entry.update(
                regeneration="true_curve",
                dropped_ends=[0 not in selected, len(table["rows"]) - 1 not in selected],
                dropped_rows=[item[0] for i, item in enumerate(table["rows"]) if i not in selected],
                clip_points=[],
            )
        paths.append(entry)
    kernel = {
        "status": "ok",
        "ops": {
            "S1:20": {
                "checkpoint_clips": {
                    "clipped_at": "synthetic first contact outside stock_removal_bounds",
                    "precision_mm": 1e-4,
                    "paths": paths,
                }
            }
        },
    }
    return dataclasses.replace(bundle, kernel=kernel)


@pytest.mark.parametrize(
    ("points", "walls", "expected"),
    [
        (
            [[1.0, 0.5], [3.0, 0.5]],
            [[[0.0, 0.0], [0.0, 1.0]], [[4.0, 0.0], [4.0, 1.0]]],
            2.0,
        ),
        ([[0.0, 2.0], [2.0, 2.0]], [[[0.0, 0.0], [1.0, 0.0]]], math.sqrt(5.0)),
    ],
    ids=["interior-nearest-wall-switch", "finite-wall-endpoint"],
)
def test_finite_wall_residual_oracle_covers_the_whole_breakout(points, walls, expected):
    assert finite_wall_residual(points, walls) == pytest.approx(expected, abs=1e-9)


@pytest.mark.parametrize("kind", ["line_table", "arc_table"], ids=["join", "arc"])
@pytest.mark.parametrize("fraction", [0.2, 0.5], ids=["shorter-than-a-drill", "off-pitch"])
def test_bounded_chain_clip_retains_only_actual_holes(tmp_path, kind, fraction):
    bundle = load_bundle(joined_chain_plan(tmp_path, bounded=True))
    requested = joined_chain_finding(bundle, pre_kernel=True)
    selected = next(
        table
        for table in coordinates.checkpoints("S1:20", requested.numbers, 20)
        if table["kind"] == kind and (kind == "arc_table" or table["name"] == "S1:20 rough line +X")
    )
    a, b = [item[1] for item in selected["rows"][:2]]
    exact = [a[axis] + fraction * (b[axis] - a[axis]) for axis in range(2)]
    fractional_point = {
        "after": 0,
        "t": fraction,
        "exact_xy": exact,
        "dro_xy": [round(value, 3) for value in exact],
    }
    clipped = synthetic_join_clip(
        bundle,
        requested,
        lambda table: [{"row": 0}, fractional_point] if table["name"] == selected["name"] else [],
    )
    row = joined_chain_finding(clipped)
    # The kernel clips a swept chord, but neither its short nor its wider clip point
    # is a drilled hole. Only row 0 may reach the printed table or hole validation.
    assert row.status == "pass", row.sentence
    assert row.numbers.get("arc_errors", []) == row.numbers.get("arc_debts", []) == []
    if kind == "arc_table":
        assert joined_chain_lines(row) == []
        (retained,) = arcs(row, 20)
        assert retained["rows"] == arcs(requested, 20)[0]["rows"][:1]
        assert "clipped_at" not in retained["rows"][0]
    else:
        assert arcs(row, 20) == []
        (retained,) = joined_chain_lines(row)
        original = next(line for line in joined_chain_lines(requested) if line["side"] == "+X")
        for column in ("model_xy", "setup_xy", "dro_xy", "overshoot"):
            assert retained[column] == original[column][:1]
        assert row.numbers["profiles"][0]["cutter_centre"] == []
    assert retained["method"] == "chain_drill"
    dropped_key = "dropped_rows" if kind == "arc_table" else "dropped_points"
    assert retained[dropped_key] == len(selected["rows"]) - 1
    assert retained["pitch_mm"] == 0.0
    assert retained["stock_left_mm"] == pytest.approx(printed_join_residual(row), abs=1e-8)
    (checkpoint,) = coordinates.checkpoints("S1:20", row.numbers, 20)
    assert len(checkpoint["rows"]) == 1
    assert checkpoint["rows"][0][1] == a
    assert checkpoint["rows"][0][1] != fractional_point["dro_xy"]


@pytest.mark.parametrize("kind", ["line_table", "arc_table"], ids=["join", "arc"])
def test_bounded_chain_regenerated_whole_holes_preserve_legal_endpoints_and_spacing(
    tmp_path,
    kind,
):
    bundle = load_bundle(joined_chain_plan(tmp_path, bounded=True))
    requested = joined_chain_finding(bundle, pre_kernel=True)
    tables = coordinates.checkpoints("S1:20", requested.numbers, 20)
    selected = next(
        table
        for table in tables
        if table["kind"] == kind and (kind == "arc_table" or table["name"] == "S1:20 rough line +X")
    )
    if kind == "arc_table":
        (original,) = arcs(requested, 20)
    else:
        original = next(line for line in joined_chain_lines(requested) if line["side"] == "+X")
    # Legal tangent endpoints remain the same true-curve holes. Explicit generated
    # provenance must not make coordinates invent a different pitch or a chord hole.
    clipped = synthetic_join_clip(
        bundle,
        requested,
        lambda table: list(range(len(table["rows"]))) if table["name"] == selected["name"] else [],
        regenerated=True,
    )
    row = joined_chain_finding(clipped)
    assert row.status == "pass", row.sentence
    assert row.numbers.get("arc_errors", []) == row.numbers.get("arc_debts", []) == []
    if kind == "arc_table":
        assert joined_chain_lines(row) == []
        (retained,) = arcs(row, 20)
        for column in ("model_xy", "setup_xy", "dro_xy", "angle_deg"):
            assert [item[column] for item in retained["rows"]] == [
                item[column] for item in original["rows"]
            ]
    else:
        assert arcs(row, 20) == []
        (retained,) = joined_chain_lines(row)
        for column in ("model_xy", "setup_xy", "dro_xy", "overshoot"):
            assert retained[column] == original[column]
    assert retained["method"] == "chain_drill"
    assert retained["regeneration"] == "true_curve"
    assert retained["dropped_ends"] == [False, False]
    assert "fragment" not in retained
    dropped_key = "dropped_rows" if kind == "arc_table" else "dropped_points"
    assert retained[dropped_key] == 0
    (checkpoint,) = coordinates.checkpoints("S1:20", row.numbers, 20)
    assert checkpoint["rows"] == selected["rows"]
    authored = [item[1] for item in selected["rows"]]
    assert checkpoint["rows"][0][1] == authored[0]
    assert checkpoint["rows"][-1][1] == authored[-1]
    gaps = [math.dist(a, b) for a, b in itertools.pairwise(authored)]
    assert retained["pitch_mm"] == pytest.approx(max(gaps), abs=1e-9)
    assert max(gaps) <= JOIN_PITCH + 0.002


def test_a_regenerated_short_chain_span_is_a_concrete_no_web_error(tmp_path):
    bundle = load_bundle(joined_chain_plan(tmp_path, tip=(6.2, -8.0), bounded=True))
    requested = joined_chain_finding(bundle, pre_kernel=True)
    selected = next(
        table
        for table in coordinates.checkpoints("S1:20", requested.numbers, 20)
        if table["name"] == "S1:20 rough line +X"
    )
    index = min(
        range(len(selected["rows"]) - 1),
        key=lambda i: math.dist(selected["rows"][i][1], selected["rows"][i + 1][1]),
    )
    assert math.dist(selected["rows"][index][1], selected["rows"][index + 1][1]) < JOIN_DRILL
    clipped = synthetic_join_clip(
        bundle,
        requested,
        lambda table: [index, index + 1] if table["name"] == selected["name"] else [],
        regenerated=True,
    )
    row = joined_chain_finding(clipped)
    assert row.status == "error", row.sentence
    assert "no web" in errors(row)
    assert not row.numbers.get("arc_debts", [])
    assert arcs(row, 20) == joined_chain_lines(row) == []
    (profile,) = row.numbers["profiles"]
    assert "clip_reason" not in profile


def test_a_regenerated_legal_singleton_hole_remains_a_coordinate_checkpoint(tmp_path):
    bundle = load_bundle(joined_chain_plan(tmp_path, bounded=True))
    requested = joined_chain_finding(bundle, pre_kernel=True)
    selected = next(
        table
        for table in coordinates.checkpoints("S1:20", requested.numbers, 20)
        if table["kind"] == "arc_table"
    )
    index = len(selected["rows"]) // 2
    assert 0 < index < len(selected["rows"]) - 1
    clipped = synthetic_join_clip(
        bundle,
        requested,
        lambda table: [index] if table["name"] == selected["name"] else [],
        regenerated=True,
    )
    row = joined_chain_finding(clipped)
    assert row.status == "pass", row.sentence
    assert not row.numbers.get("arc_errors", []) and not row.numbers.get("arc_debts", [])
    (retained,) = arcs(row, 20)
    assert joined_chain_lines(row) == []
    assert retained["regeneration"] == "true_curve"
    assert retained["dropped_ends"] == [True, True]
    assert len(retained["rows"]) == 1
    assert retained["pitch_mm"] == 0.0
    (checkpoint,) = coordinates.checkpoints("S1:20", row.numbers, 20)
    assert len(checkpoint["rows"]) == 1
    assert checkpoint["rows"][0][1:] == selected["rows"][index][1:]


@pytest.mark.parametrize("clip_state", ["absent", "empty"])
def test_bounded_chain_finish_stage_is_an_error_before_clipping(tmp_path, clip_state):
    bundle = load_bundle(joined_chain_plan(tmp_path, bounded=True))
    setup = bundle.plan["setups"][0]
    # Zero allowance makes rough and finish request identical geometry and row counts.
    rough = {**setup["ops"][0], "rough_allowance_mm": 0.0}
    bundle = dataclasses.replace(
        bundle, plan={**bundle.plan, "setups": [{**setup, "ops": [rough]}]}
    )
    if clip_state == "empty":
        requested = joined_chain_finding(bundle, pre_kernel=True)
        bundle = synthetic_join_clip(bundle, requested, lambda table: [])
        for path in bundle.kernel["ops"]["S1:20"]["checkpoint_clips"]["paths"]:
            path["table"] = path["table"].replace(" rough ", " finish ")
    finish = {**rough, "do": "finish_profile"}
    bundle = dataclasses.replace(
        bundle, plan={**bundle.plan, "setups": [{**setup, "ops": [finish]}]}
    )
    row = joined_chain_finding(bundle)
    assert row.status == "error", row.sentence
    assert "chain_drill only roughs outside the line" in errors(row)
    assert arcs(row, 20) == joined_chain_lines(row) == []


@pytest.mark.parametrize("clip_state", ["absent", "empty"])
def test_bounded_chain_full_holes_inside_line_are_errors_before_clipping(
    tmp_path, monkeypatch, clip_state
):
    bundle = load_bundle(joined_chain_plan(tmp_path, bounded=True))
    if clip_state == "empty":
        requested = joined_chain_finding(bundle, pre_kernel=True)
        bundle = synthetic_join_clip(bundle, requested, lambda table: [])
    make_arc = coordinates._arc

    def inside_holes(*args, **kwargs):
        arc_tables, lines, walls = make_arc(*args, **kwargs)
        # Inject invalid printed centres without changing the checkpoint identities
        # or counts. Every full hole now lies inside the convex arc's finished wall.
        centre = arc_tables[0]["centre_setup_xy"]
        for arc in arc_tables:
            for item in arc["rows"]:
                item["dro_xy"] = list(centre)
        for line in lines:
            line["dro_xy"] = [list(centre) for point in line["dro_xy"]]
        return arc_tables, lines, walls

    monkeypatch.setattr(coordinates, "_arc", inside_holes)
    row = joined_chain_finding(bundle)
    assert row.status == "error", row.sentence
    assert any(
        "hole " in error and "past the line" in error for error in row.numbers.get("arc_errors", [])
    )
    assert arcs(row, 20) == joined_chain_lines(row) == []


def test_chain_drill_spaces_both_finite_join_legs_and_preserves_kernel_consumers(tmp_path):
    bundle = load_bundle(joined_chain_plan(tmp_path))
    row = joined_chain_finding(bundle)
    assert row.status == "pass", row.sentence
    lines = joined_chain_lines(row)
    assert {line["side"] for line in lines} == {"-X", "+X"}
    vertices = exact_join_vertices()
    (arc,) = arcs(row, 20)
    for line in lines:
        assert line["method"] == "chain_drill" and "jog" not in line
        side = 1 if line["side"] == "+X" else -1
        points = [[side * point[0], point[1]] for point in line["model_xy"]]
        if math.dist(points[0], vertices[0]) > math.dist(points[-1], vertices[0]):
            points.reverse()
        first_count = math.ceil(math.dist(vertices[0], vertices[1]) / JOIN_PITCH)
        second_count = math.ceil(math.dist(vertices[1], vertices[2]) / JOIN_PITCH)
        assert len(points) == first_count + second_count + 1
        for actual, expected in zip(
            (points[0], points[first_count], points[-1]), vertices, strict=True
        ):
            assert actual == pytest.approx(expected, abs=1e-8)
        for leg, count in (
            (points[: first_count + 1], first_count),
            (points[first_count:], second_count),
        ):
            gaps = [math.dist(a, b) for a, b in itertools.pairwise(leg)]
            assert len(gaps) == count
            assert max(gaps) <= JOIN_PITCH + 1e-9
            assert gaps == pytest.approx([gaps[0]] * count, abs=1e-8)
            for index, point in enumerate(leg):
                assert point == pytest.approx(
                    [
                        leg[0][axis] + index / count * (leg[-1][axis] - leg[0][axis])
                        for axis in range(2)
                    ],
                    abs=1e-8,
                )
        assert all(math.dist(a, b) > JOIN_DRILL for a, b in itertools.pairwise(line["dro_xy"]))
        assert sum(line["overshoot"]) == 1
        assert (
            len(line["model_xy"])
            == len(line["setup_xy"])
            == len(line["dro_xy"])
            == len(line["overshoot"])
        )
        for model, setup in zip(line["model_xy"], line["setup_xy"], strict=True):
            assert setup == pytest.approx([model[0] - 5.0, model[1] - 2.0], abs=1e-9)
        arc_end = next(
            item for item in (arc["rows"][0], arc["rows"][-1]) if side * item["model_xy"][0] > 0
        )
        end = min(
            (0, len(line["setup_xy"]) - 1),
            key=lambda i: math.dist(line["setup_xy"][i], arc_end["setup_xy"]),
        )
        assert line["setup_xy"][end] == pytest.approx(arc_end["setup_xy"], abs=1e-8)
        assert line["dro_xy"][end] == arc_end["dro_xy"]

    residual = printed_join_residual(row)
    for table in (arc, *lines):
        assert table["drill_dia_mm"] == JOIN_DRILL
        assert table["pitch_mm"] <= JOIN_PITCH + 0.002
        assert table["hole_clear_mm"] >= JOIN_ALLOWANCE - 1e-6
        assert table["stock_left_mm"] == pytest.approx(residual, abs=1e-8)
        assert table["stock_cap_mm"] == 1.0
        assert table["break_out"] == coordinates.CHAIN_BREAK_OUT
    (profile,) = row.numbers["profiles"]
    assert profile["stock_left_mm"] == pytest.approx(residual, abs=1e-8)
    assert profile["stock_cap_mm"] == 1.0

    kernel_op = next(
        op
        for setup in build_job(bundle)["setups"]
        for op in setup["ops"]
        if op["subject"] == "S1:20"
    )
    checkpoints = kernel_op["checkpoints"]
    assert kernel_op["tool_paths"]["tables"] is True
    for path in checkpoints["paths"]:
        assert path["method"] == "chain_drill"
        geometry = path["chain_geometry"]
        assert geometry["pitch_mm"] == JOIN_PITCH
        assert geometry["offset"] == pytest.approx(JOIN_DRILL / 2 + JOIN_ALLOWANCE)
        assert geometry["setup_origin"] == pytest.approx([-5.0, -2.0])
        assert geometry["basis"] == [[1.0, 0.0], [0.0, 1.0]]
        assert geometry["walls"]
        assert geometry["curves"]
        curve_kind = "arc" if path["kind"] == "arc_table" else "line"
        assert all(curve["kind"] == curve_kind for curve in geometry["curves"])
    for line in lines:
        expected_ids = [
            f"S1:20 rough line {line['side']}[{index}]" for index in range(len(line["dro_xy"]))
        ]
        path = next(path for path in checkpoints["paths"] if path["table"] == expected_ids[0])
        assert path["ids"] == expected_ids
        assert path["xy_mm"] == line["dro_xy"]
        assert path["overshoot"] == line["overshoot"]
        assert path["stepped"] is False
        checked = {point["id"]: point for point in checkpoints["rows"]}
        assert [checked[name]["xy_mm"] for name in expected_ids] == line["dro_xy"]
        assert all(checked[name]["tip_z_mm"] == line["dro_tip_z"] for name in expected_ids)


def test_chain_join_cap_error_keeps_concrete_residual_in_profile_numbers(tmp_path):
    passing = joined_chain_finding(load_bundle(joined_chain_plan(tmp_path / "passing")))
    assert passing.status == "pass", passing.sentence
    residual = printed_join_residual(passing)
    cap = 0.3
    row = joined_chain_finding(load_bundle(joined_chain_plan(tmp_path / "over-cap", cap=cap)))
    assert row.status == "error", row.sentence
    assert f"leaves up to {residual:.3f}" in errors(row)
    assert "more than the shop's 0.3 cap" in errors(row)
    assert row.numbers["arc_table"] == row.numbers["line_table"] == []
    (profile,) = row.numbers["profiles"]
    assert profile["stock_left_mm"] == pytest.approx(residual, abs=1e-8)
    assert profile["stock_cap_mm"] == cap


def test_chain_join_without_a_filing_cap_retains_numerical_stock_and_debt(tmp_path):
    row = joined_chain_finding(load_bundle(joined_chain_plan(tmp_path, cap=None)))
    assert row.status == "unknown", row.sentence
    assert "sets no max_filing_stock_mm" in debts(row)
    assert {line["side"] for line in joined_chain_lines(row)} == {"-X", "+X"}
    residual = printed_join_residual(row)
    for table in (*arcs(row, 20), *joined_chain_lines(row), *row.numbers["profiles"]):
        assert table["stock_left_mm"] == pytest.approx(residual, abs=1e-8)
        assert table["stock_cap_mm"] == "unknown"


def test_kernel_excludes_invalid_short_chain_joins_before_validation(tmp_path):
    # This land is shorter than the drill diameter even after exact offset joins.
    # Raw holes have no web; excluded join holes are not a cut and cannot veto the arc.
    tip = (6.2, -8.0)
    vertices = exact_join_vertices(tip)
    assert math.dist(vertices[0], vertices[1]) < JOIN_DRILL
    unbounded = joined_chain_finding(load_bundle(joined_chain_plan(tmp_path / "raw", tip=tip)))
    assert unbounded.status == "error" and "no web" in errors(unbounded)

    bundle = load_bundle(joined_chain_plan(tmp_path / "bounded", tip=tip, cap=0.36, bounded=True))
    requested = joined_chain_finding(bundle, pre_kernel=True)
    assert {line["side"] for line in joined_chain_lines(requested)} == {"-X", "+X"}
    assert not requested.numbers.get("arc_errors", [])
    assert all(
        table["bounded"] for table in coordinates.checkpoints("S1:20", requested.numbers, 20)
    )
    clipped = synthetic_join_clip(
        bundle,
        requested,
        lambda table: list(range(len(table["rows"]))) if table["kind"] == "arc_table" else [],
    )
    row = joined_chain_finding(clipped)
    assert row.status == "pass", row.sentence
    assert joined_chain_lines(row) == []
    assert row.numbers.get("arc_errors", []) == row.numbers.get("arc_debts", []) == []
    (arc,) = arcs(row, 20)
    assert arc["rows"] == arcs(requested, 20)[0]["rows"]
    assert arc["stock_left_mm"] == pytest.approx(printed_join_residual(row, tip), abs=1e-8)
    assert arc["stock_left_mm"] <= arc["stock_cap_mm"] == 0.36
    (profile,) = row.numbers["profiles"]
    assert "clip_reason" not in profile
    assert profile["cutter_centre"] == arc["rows"]
    assert profile["stock_left_mm"] == arc["stock_left_mm"]


@pytest.mark.parametrize(("cap", "over_cap"), [(1.0, True), (3.1, False)])
def test_retained_chain_join_breakout_reports_farthest_finite_wall_distance(cap, over_cap):
    wall = [[0.0, 0.0], [10.0, 0.0]]
    line = {
        "dro_xy": [[5.0, 2.0], [5.0, 3.0]],
        "side": "synthetic",
        "join_walls": [{"ends": wall, "normal": [0.0, 1.0]}],
    }
    errors, debts = coordinates._chain(
        arcs=[],
        lines=[line],
        walls=[lambda point: segment_distance(point, *wall)],
        drill=0.25,
        allowance=0.1,
        cap=cap,
        label="retained join",
        scale=1.0,
    )
    # The full retained break-out reaches Y3, even though a wall-normal ray first
    # meets it at Y2. The residual is the worst nearest-wall distance, not first contact.
    residual = finite_wall_residual(line["dro_xy"], [wall])
    assert residual == pytest.approx(3.0)
    assert line["stock_left_mm"] == pytest.approx(residual)
    assert line["stock_cap_mm"] == cap
    assert debts == []
    assert bool(errors) is over_cap
    if over_cap:
        assert any(
            "leaves up to 3.000" in error and "more than the shop's 1 cap" in error
            for error in errors
        )


def test_concave_chain_join_stock_is_nearest_finite_wall_distance_not_ray_runout():
    turn = math.radians(80.0)
    direction = [math.cos(turn), math.sin(turn)]
    normals = [[0.0, 1.0], [-direction[1], direction[0]]]
    walls = [
        [[-10.0, 0.0], [0.0, 0.0]],
        [[0.0, 0.0], [10.0 * value for value in direction]],
    ]
    drill, allowance, cap = 0.25, 0.1, 1.0
    offset = drill + allowance
    miter = [offset * (direction[0] - 1.0) / direction[1], offset]
    start = [-9.0, offset]
    end = [9.0 * direction[axis] + offset * normals[1][axis] for axis in range(2)]
    holes = [
        [start[axis] + k / 6 * (miter[axis] - start[axis]) for axis in range(2)] for k in range(7)
    ] + [
        [miter[axis] + k / 6 * (end[axis] - miter[axis]) for axis in range(2)] for k in range(1, 7)
    ]
    assert all(math.dist(a, b) > 2 * drill for a, b in itertools.pairwise(holes))
    assert all(
        min(
            sum((point[axis] - wall[0][axis]) * normal[axis] for axis in range(2))
            for wall, normal in zip(walls, normals, strict=True)
        )
        >= offset - 1e-9
        for point in holes
    )
    residual = finite_wall_residual(holes, walls)
    assert residual == pytest.approx(0.350, abs=1e-9)
    line = {
        "dro_xy": holes,
        "side": "synthetic",
        "join_walls": [
            {"ends": wall, "normal": normal} for wall, normal in zip(walls, normals, strict=True)
        ],
    }
    chain_errors, chain_debts = coordinates._chain(
        arcs=[],
        lines=[line],
        walls=[lambda point, wall=wall: segment_distance(point, *wall) for wall in walls],
        drill=drill,
        allowance=allowance,
        cap=cap,
        label="concave retained join",
        scale=1.0,
    )
    # A single-wall normal can overreach to 0.35 / cos(80°) = 2.016 mm, but that
    # point is much nearer the other finished wall. It must not trip the 1 mm cap.
    assert chain_errors == chain_debts == []
    assert line["stock_left_mm"] == pytest.approx(residual, abs=1e-9)
    assert line["stock_cap_mm"] == cap


def test_kernel_keeps_only_a_connected_partial_chain_join(tmp_path):
    bundle = load_bundle(joined_chain_plan(tmp_path, bounded=True))
    requested = joined_chain_finding(bundle, pre_kernel=True)
    (arc,) = arcs(requested, 20)
    line = next(line for line in joined_chain_lines(requested) if line["side"] == "+X")
    count = len(line["dro_xy"])
    ends = [arc["rows"][0]["dro_xy"], arc["rows"][-1]["dro_xy"]]
    from_start = any(line["dro_xy"][0] == point for point in ends)
    kept = list(range(count // 2)) if from_start else list(range(count // 2, count))
    row = joined_chain_finding(
        synthetic_join_clip(
            bundle,
            requested,
            lambda table: (
                list(range(len(table["rows"])))
                if table["kind"] == "arc_table"
                else kept
                if table["name"] == "S1:20 rough line +X"
                else []
            ),
        )
    )
    assert row.status == "pass", row.sentence
    (partial,) = joined_chain_lines(row)
    assert partial["side"] == "+X" and partial["method"] == "chain_drill"
    assert partial["dro_xy"] == [line["dro_xy"][index] for index in kept]
    assert partial["dropped_points"] == count - len(kept)
    assert "jog" not in partial and "fragment" not in partial
    residual = printed_join_residual(row)
    assert partial["stock_left_mm"] == arcs(row, 20)[0]["stock_left_mm"]
    assert partial["stock_left_mm"] == pytest.approx(residual, abs=1e-8)
    (profile,) = row.numbers["profiles"]
    assert "clip_reason" not in profile


def test_filing_stock_over_the_cap_is_an_error_unless_a_later_rough_recuts_it(tmp_path):
    coarse = op(20, "rough_profile", "{ method = 'stairs', cusp_mm = 0.4 }", allowance=0.45)
    row = coordinates_row(scratch(tmp_path / "alone", coarse))
    assert row.status == "error"
    assert "more than the shop's 0.5 cap" in errors(row)
    fine = op(30, "rough_profile", "{ method = 'stairs', cusp_mm = 0.1 }", allowance=0.2)
    row = coordinates_row(scratch(tmp_path / "recut", coarse + fine))
    assert row.status == "pass", row.sentence
    (first,), (second,) = arcs(row, 20), arcs(row, 30)
    assert first["recut_by"] == "S1 op 30" and "stock_cap_mm" not in first
    assert second["stock_left_mm"] <= second["stock_cap_mm"] == CAP


def test_leftover_goes_to_the_rough_that_hands_the_faces_to_the_file(tmp_path):
    # Two coarse roughs (one from each face of a part, say), then a fine one: the file
    # meets what the fine rough leaves, so it takes both coarse leftovers.
    coarse = [
        op(n, "rough_profile", "{ method = 'stairs', cusp_mm = 0.4 }", allowance=0.45)
        for n in (20, 25)
    ]
    fine = op(30, "rough_profile", "{ method = 'stairs', cusp_mm = 0.1 }", allowance=0.2)
    row = coordinates_row(scratch(tmp_path, "".join(coarse) + fine))
    assert row.status == "pass", row.sentence
    assert [arcs(row, n)[0]["recut_by"] for n in (20, 25)] == ["S1 op 30", "S1 op 30"]


@pytest.mark.parametrize(
    "policy",
    [
        '[required]\ncoordinates = "*"\n',
        POLICY.replace("max_filing_stock_mm = false", "max_filing_stock_mm = true"),
        POLICY.replace(
            'max_filing_stock_mm = "example filing cap"', 'max_filing_stock_mm = "unknown"'
        ),
        POLICY.replace(f"max_filing_stock_mm = {CAP}", "max_filing_stock_mm = -0.1"),
    ],
    ids=["absent", "verify", "uncited", "negative"],
)
def test_an_unestablished_filing_cap_is_unknown_never_a_pass(tmp_path, policy):
    row = coordinates_row(
        scratch(
            tmp_path,
            op(20, "rough_profile", "{ method = 'stairs', cusp_mm = 0.25 }", allowance=0.2),
            policy=policy,
        )
    )
    assert row.status == "unknown"
    assert "sets no max_filing_stock_mm" in debts(row)


def test_an_unknown_cutter_leaves_the_stairs_unknown(tmp_path):
    plan = scratch(
        tmp_path, op(20, "rough_profile", "{ method = 'stairs', cusp_mm = 0.25 }", allowance=0.2)
    )
    inventory = plan.with_name("inventory.toml")
    inventory.write_text(
        inventory.read_text(encoding="utf-8").replace(
            "dia_mm = 6.0\nverify", "dia_mm = 'unknown'\nverify", 1
        ),
        encoding="utf-8",
    )
    row = coordinates_row(plan)
    assert row.status == "unknown"
    assert not row.numbers.get("arc_errors")


@pytest.mark.parametrize("method", ["stairs", "chain_drill"])
def test_rough_methods_cannot_finish_the_line(tmp_path, method):
    need = "cusp_mm = 0.25" if method == "stairs" else "pitch_mm = 5.0"
    row = coordinates_row(
        scratch(tmp_path, op(20, "finish_profile", f"{{ method = '{method}', {need} }}"))
    )
    assert row.status == "error"
    assert "only roughs outside the line" in errors(row)


def test_authored_arc_table_is_an_error(tmp_path):
    row = coordinates_row(
        scratch(tmp_path, op(20, "finish_profile", "{ method = 'arc_table', step_deg = 30.0 }"))
    )
    assert row.status == "error"
    assert "arc_table moves two handwheels at once" in errors(row)
    assert not arcs(row, 20)


def chords(tmp_path, count, hold="fixture = 'table'"):
    return coordinates_row(
        scratch(
            tmp_path,
            op(20, "finish_profile", f"{{ method = 'chords', count = {count} }}"),
            hold=hold,
        )
    )


def test_chord_sagitta_wider_than_the_band_is_an_error(tmp_path):
    # Eight chords on R10 leave a 0.76 sagitta; the band is 0.2.
    row = chords(tmp_path, 8)
    assert row.status == "error"
    assert "sagitta" in errors(row) and "radial band" in errors(row)


def test_chords_are_proven_inside_the_band_with_cuts_on_the_dro_grid(tmp_path):
    row = chords(tmp_path, 24)
    assert row.status == "pass", row.sentence
    (table,) = arcs(row, 20)
    assert table["sagitta_mm"] <= 0.2 and table["indexed"] is True
    assert len(table["chords"]) == 24
    for chord in table["chords"]:
        low, high = chord["face_radius_mm"]
        assert 9.9 - 1e-6 <= low <= high <= 10.1 + 1e-6
        cut = chord["cut"]
        assert cut["along"] == "X" and on_grid(cut["index_deg"], 0.1)
        assert all(on_grid(cut[key]) for key in ("at", "from", "to"))
    assert all(on_grid(v) for r in table["rows"] for v in r["dro_xy"])
    assert_printed_chord_band(table, (9.9, 10.1))


def test_slanted_chords_without_a_rotary_table_are_an_error(tmp_path):
    row = chords(tmp_path, 16, hold="fixture = 'unknown'")
    assert row.status == "error"
    assert "index each chord square to X on a rotary table" in errors(row)


@pytest.mark.parametrize("count", [1, 2])
def test_a_full_circle_cut_in_fewer_than_three_chords_is_an_error(tmp_path, count):
    row = chords(tmp_path, count)
    assert row.status == "error"
    assert not arcs(row, 20)


SWING = [-12.0, -12.0, -10.0, 12.0, 12.0, 0.0]


def rotary_plan(
    tmp_path,
    *,
    origin=ON_AXIS,
    hold="fixture = 'table'",
    centre="bore",
    ops=DRILL_BORE,
    by="pin",
    step=30.0,
    target=ARC,
):
    contour = (
        f"{{ method = 'rotary_table', step_deg = {step}, centre_by = '{by}', "
        f"centre_feature = '{centre}' }}"
    )
    plan = ops + op(20, "finish_profile", contour)
    return scratch(tmp_path, plan, origin=origin, hold=hold, target=target)


def rotary(tmp_path, **kwargs):
    return coordinates_row(rotary_plan(tmp_path, **kwargs), stock_bbox=SWING)


def test_rotary_table_recipe_locks_the_offset_and_reads_the_dial_on_its_vernier(tmp_path):
    row = rotary(tmp_path)
    assert row.status == "pass", row.sentence
    (table,) = arcs(row, 20)
    recipe = table["rotary"]
    assert recipe["table"] == "table" and recipe["centre_feature"] == "bore"
    # A Ø6 pin in the Ø6.00-6.03 bore and the table's Ø6 bore shifts the centre ≤ 0.015.
    assert recipe["pin_dia_mm"] == 6.0 and recipe["table_bore_dia_mm"] == 6.0
    assert recipe["centre_play_mm"] == pytest.approx(0.015)
    assert recipe["offset_axis"] == "X" and recipe["offset_x"] == pytest.approx(13.0)
    assert recipe["resolution_deg"] == 0.1 and recipe["sweep_deg"] == 360.0
    assert on_grid(recipe["start_deg"], 0.1) and recipe["start_deg"] == recipe["stop_deg"]
    assert recipe["rotation"] == "clockwise"
    assert recipe["work_radius_mm"] <= recipe["max_work_radius_mm"]


@pytest.mark.parametrize("spindle", ["cw", "ccw"])
@pytest.mark.parametrize("feed", ["conventional", "climb"])
@pytest.mark.parametrize("shape", ["convex-full", "convex-partial", "concave-partial"])
def test_rotary_feed_turns_the_work_back_from_the_physical_cut(tmp_path, spindle, feed, shape):
    # At the rightmost point a CW cutter moves down its left (convex) contact side.
    # Conventional traverse moves the cutter up, hence turns the work clockwise;
    # an inside contact, reversed spindle, or climb feed each reverses that turn.
    if shape == "convex-full":
        target, sweep, ends = ARC, 360.0, (0.0, 0.0)
    elif shape == "convex-partial":
        target = (
            "kind = 'profile'\nrequirements = ['radius']\nradius = [9.9, 10.1]\n"
            "radius_nominal = 10.0\narc_centre = [20.0, 10.0, 0.0]\n"
            "arc = 'upper_semicircle'\n"
        )
        sweep, ends = 180.0, (0.0, 180.0)
    else:
        target = (
            "kind = 'profile'\nrequirements = ['radius']\nradius = [9.9, 10.1]\n"
            "radius_nominal = 10.0\narc_centre = [20.0, 10.0, 0.0]\n"
            "end = [26.0, 2.0]\n"
        )
        sweep, ends = 73.6, (233.2, 306.8)
    plan = rotary_plan(tmp_path, target=target, step=1.0)
    change(plan.with_name("inventory.toml"), "rotation = 'cw'", f"rotation = '{spindle}'")
    if feed != "conventional":
        change(plan, "direction = 'conventional'", f"direction = '{feed}'")
        change(plan, "direction = 'conventional'", f"direction = '{feed}'")
    row = coordinates_row(plan, stock_bbox=SWING)
    assert row.status == "pass", row.sentence
    (table,) = arcs(row, 20)
    recipe = table["rotary"]
    clockwise = (spindle == "cw") == (feed == "conventional")
    if shape == "concave-partial":
        clockwise = not clockwise
    assert recipe["rotation"] == ("clockwise" if clockwise else "counterclockwise")
    start, stop = ends if clockwise else ends[::-1]
    assert recipe["start_deg"] == pytest.approx(start)
    assert recipe["stop_deg"] == pytest.approx(stop)
    assert recipe["sweep_deg"] == pytest.approx(sweep)
    assert recipe["offset_x"] == pytest.approx(7.0 if shape == "concave-partial" else 13.0)


def short_arc(tmp_path, span, vernier, clock):
    """A concave R100 arc about the table axis spanning ``span`` degrees about its lowest
    point, turned ``clock`` degrees in the setup, on a table dial read to ``vernier``."""
    half = math.radians(span / 2)
    end = [20.0 + 100.0 * math.sin(half), 10.0 - 100.0 * math.cos(half)]
    target = (
        "kind = 'profile'\nrequirements = ['radius']\nradius = [99.9, 100.1]\n"
        f"radius_nominal = 100.0\narc_centre = [20.0, 10.0, 0.0]\nend = {end}\n"
    )
    plan = rotary_plan(tmp_path, step=1.0, target=target)
    inventory = plan.with_name("inventory.toml")
    change(inventory, "vernier_deg = 0.1", f"vernier_deg = {vernier}")
    change(inventory, "max_work_mm = 150.0", "max_work_mm = 300.0")
    c, s = math.cos(math.radians(clock)), math.sin(math.radians(clock))
    change(  # the first frame is the setup's frame A
        plan.with_name("features.toml"),
        "x = [1.0, 0.0, 0.0]\ny = [0.0, 1.0, 0.0]",
        f"x = [{c}, {s}, 0.0]\ny = [{-s}, {c}, 0.0]",
    )
    return coordinates_row(plan, stock_bbox=[-2.0, -101.0, -10.0, 2.0, -99.0, 0.0])


@pytest.mark.parametrize(
    ("span", "vernier", "clock", "status"),
    [(0.4, 1.0, 0.5, "error"), (0.04, 0.1, 0.0, "error"), (2.4, 1.0, 0.5, "pass")],
    ids=["wraps", "collapses", "resolves"],
)
def test_rotary_ends_round_inward_and_an_arc_the_dial_cannot_resolve_is_an_error(
    tmp_path, span, vernier, clock, status
):
    # Rounding both ends inward to the dial crosses them on an arc shorter than one
    # graduation: never read as the long way round (359°) or a zero sweep.
    row = short_arc(tmp_path, span, vernier, clock)
    assert row.status == status, row.sentence
    if status == "error":
        assert "dial" in errors(row) and not arcs(row, 20)
        return
    recipe = arcs(row, 20)[0]["rotary"]
    assert vernier <= recipe["sweep_deg"] <= span
    assert on_grid(recipe["start_deg"], vernier) and on_grid(recipe["stop_deg"], vernier)
    turned = (recipe["stop_deg"] - recipe["start_deg"]) % 360.0
    assert recipe["sweep_deg"] == pytest.approx(min(turned, 360.0 - turned))


@pytest.mark.parametrize(
    ("bore", "by", "status"),
    [
        ("bore_dia_mm = 20.0", "pin", "error"),
        ("bore_dia_mm = 5.9", "pin", "error"),
        ("", "pin", "unknown"),
        ("bore_dia_mm = { value = 6.0, verify = true }", "pin", "unknown"),
        ("bore_dia_mm = 20.0", "indicate", "pass"),
    ],
    ids=["loose", "tight", "unknown", "unverified", "indicated"],
)
def test_a_centre_pin_locates_the_arc_only_in_a_table_bore_it_fits(tmp_path, bore, by, status):
    # A Ø6 pin through the part rattles 7 mm in a Ø20 table bore and never enters a Ø5.9
    # one; an unknown or unverified bore proves nothing. Indicating needs no table bore.
    plan = rotary_plan(tmp_path, by=by)
    change(plan.with_name("inventory.toml"), "bore_dia_mm = 6.0\nmax_work", f"{bore}\nmax_work")
    row = coordinates_row(plan, stock_bbox=SWING)
    assert row.status == status, row.sentence


def banded_rotary(tmp_path, side, by, resolution, band):
    """A rotary cut, centred ``by`` a pin with no play or by indicating, on a mill whose DRO
    reads ``resolution`` mm: the convex Ø20.010 boss, or a concave R100.015 arc, of the
    radial ``band`` (mm)."""
    if side == "convex":
        dia = f"[{2 * band[0]}, {2 * band[1]}]"
        target = ARC.replace("[19.8, 20.2]", dia).replace("= 20.0\n", "= 20.010\n")
        plan, swing = rotary_plan(tmp_path, by=by, target=target), SWING
    else:
        half = math.radians(1.2)
        end = [20.0 + 100.0 * math.sin(half), 10.0 - 100.0 * math.cos(half)]
        target = (
            f"kind = 'profile'\nrequirements = ['radius']\nradius = {list(band)}\n"
            f"radius_nominal = 100.015\narc_centre = [20.0, 10.0, 0.0]\nend = {end}\n"
        )
        plan = rotary_plan(tmp_path, by=by, step=1.0, target=target)
        change(plan.with_name("inventory.toml"), "max_work_mm = 150.0", "max_work_mm = 300.0")
        swing = [-2.0, -101.0, -10.0, 2.0, -99.0, 0.0]
    inventory = plan.with_name("inventory.toml")
    change(inventory, "kind = 'mill'", f"kind = 'mill'\nresolution_mm = {resolution}")
    change(plan.with_name("features.toml"), "dia = [6.0, 6.03]", "dia = [6.0, 6.0]")
    return coordinates_row(plan, stock_bbox=swing)


@pytest.mark.parametrize("side", ["convex", "concave"])
@pytest.mark.parametrize(
    ("by", "resolution", "status"),
    [
        ("indicate", 0.02, "error"),
        ("indicate", 0.005, "pass"),
        ("pin", 0.02, "error"),
        ("pin", 0.005, "pass"),
    ],
    ids=["indicated-coarse", "indicated-fine", "pinned-coarse", "pinned-fine"],
)
def test_the_printed_table_offset_cuts_inside_the_band_however_the_centre_is_found(
    tmp_path, side, by, resolution, status
):
    # The exact cutter-centre radius (R±0.005 off a 0.01 band's middle) lies off a 0.02 mm
    # DRO grid: the offset printed off the line cuts 0.005 past the band whether the centre
    # is pinned or indicated; a 0.005 mm grid prints it exactly.
    band = (10.0, 10.01) if side == "convex" else (100.01, 100.02)
    row = banded_rotary(tmp_path, side, by, resolution, band)
    assert row.status == status, row.sentence
    if status == "error":
        assert not arcs(row, 20)
        return
    recipe = arcs(row, 20)[0]["rotary"]
    cutter = 3.0 if side == "convex" else -3.0
    assert on_grid(recipe["offset_x"], resolution)
    assert band[0] <= recipe["offset_x"] - cutter <= band[1]


@pytest.mark.parametrize("by", ["pin", "indicate"])
@pytest.mark.parametrize(
    ("leave", "status", "offsets"),
    [(-0.2, "error", []), (0.0, "pass", [13.0, 13.0]), (0.2, "pass", [13.0, 13.2])],
)
def test_a_rough_rotary_stage_leaves_its_allowance_off_the_band(
    tmp_path, by, leave, status, offsets
):
    # A finish paired with a rough allowance turns the boss twice: the rough at R10 + leave
    # (its band, R9.9 to R10.1, moved off the line by the leave), then the finish. A
    # negative leave would turn the rough inside the finished boss (Ø19.6 for -0.2): it is
    # an error and no offset for either stage is printed.
    contour = (
        f"{{ method = 'rotary_table', step_deg = 30.0, centre_by = '{by}', "
        "centre_feature = 'bore' }"
    )
    plan = scratch(
        tmp_path,
        DRILL_BORE + op(20, "finish_profile", contour, allowance=leave),
        origin=ON_AXIS,
        hold="fixture = 'table'",
    )
    row = coordinates_row(plan, stock_bbox=SWING)
    assert row.status == status, row.sentence
    printed = sorted(table["rotary"]["offset_x"] for table in arcs(row, 20))
    assert printed == pytest.approx(offsets)


def test_a_negative_rough_leave_prints_a_stop_and_no_table_offset(tmp_path):
    # The machinist reads the traveler: a refused leave must stop the op there, not print
    # the X 12.8 offset that would turn the Ø19.8-20.2 boss to Ø19.6.
    contour = (
        "{ method = 'rotary_table', step_deg = 30.0, centre_by = 'pin', centre_feature = 'bore' }"
    )
    plan = scratch(
        tmp_path,
        DRILL_BORE + op(20, "finish_profile", contour, allowance=-0.2),
        origin=ON_AXIS,
        hold="fixture = 'table'",
    )
    kernel = {"status": "ok", "setups": {"S1": {"stock_bbox_mm": SWING}}}
    bundle = dataclasses.replace(load_bundle(plan), kernel=kernel)
    row = next(row for row in coordinates.evaluate(bundle) if row.subject == "S1")
    tools = {("tools", "cutter"): "6 mm endmill", ("tools", "bore-drill"): "6 mm drill"}
    html = _Traveler(bundle, [row], {}, None).contours(bundle.plan["setups"][0], tools)
    printed = " ".join(unescape(re.sub(r"<[^>]+>", " ", html)).split())
    assert "STOP" in printed and "do not run" in printed
    assert "offset the table" not in printed and "12.8" not in printed


@pytest.mark.parametrize("by", ["pin", "indicate"])
def test_a_rotary_cut_without_a_drawing_band_is_unknown(tmp_path, by):
    row = rotary(tmp_path, by=by, target=ARC.replace("[19.8, 20.2]", "'unknown'"))
    assert row.status == "unknown", row.sentence


@pytest.mark.parametrize(
    ("case", "message"),
    [
        ("off_axis", "off the table axis"),
        ("no_table", "needs the work held on a rotary table"),
        ("not_made", "no earlier drill, ream or bore makes bore"),
        ("wrong_centre", "offset's axis is not the arc centre"),
    ],
)
def test_rotary_table_errors(tmp_path, case, message):
    kwargs = {
        "off_axis": {"origin": SHIFTED},
        "no_table": {"hold": "fixture = 'unknown'"},
        "not_made": {"ops": ""},
        "wrong_centre": {
            "centre": "offset",
            "ops": op(10, "drill", feature="offset", tool="bore-drill"),
        },
    }[case]
    row = rotary(tmp_path, **kwargs)
    assert row.status == "error"
    assert message in errors(row)


def test_rotary_table_without_the_stock_swing_is_unknown(tmp_path):
    contour = (
        "{ method = 'rotary_table', step_deg = 30.0, centre_by = 'pin', centre_feature = 'bore' }"
    )
    plan = scratch(
        tmp_path,
        DRILL_BORE + op(20, "finish_profile", contour),
        origin=ON_AXIS,
        hold="fixture = 'table'",
    )
    row = coordinates_row(plan)
    assert row.status == "unknown"
    assert "stock's swing" in debts(row)


STAIRS = op(20, "rough_profile", "{ method = 'stairs', cusp_mm = 0.25 }", allowance=0.2)
BUTTONS = "{ buttons = 'buttons', bore = 'bore', gauge = 'radius-gauge' }"


def filing(
    tmp_path, guide=BUTTONS, *, ops=DRILL_BORE + STAIRS, hold="fixture = 'buttons'", extra=""
):
    plan = scratch(tmp_path, ops + extra + bench_op(30, "file_to_line", guide=guide), hold=hold)
    return manual_row(plan, 30)


def test_filing_to_buttons_through_the_axis_bore_files_inside_the_band(tmp_path):
    row = filing(tmp_path)
    assert row.status == "pass", row.sentence
    guide = row.numbers["guide"]
    # The button centre shifts up to 0.032 off the bore axis: the pin in the Ø6.00-6.03
    # bore (0.02), the button on the pin (0.01) and half the OD runout (0.002); so the
    # R9.995-10.000 rims file R9.963 to R10.032 worst case.
    assert guide["files_to_mm"] == pytest.approx([9.963, 10.032])
    assert row.numbers["rough_op"] == "S1 op 20" and row.numbers["stock_cap_mm"] == CAP
    assert row.numbers["gauge"]["range_mm"] == [1.0, 25.0]


# The guide's kit and the hold's fixture are one item however each spells it: the kit is
# held, so the band is proven, never a "not in the hold" debt.
@pytest.mark.parametrize(
    ("guide", "hold", "owner"),
    [
        (BUTTONS.replace("'buttons'", "'fixtures.buttons'"), "fixture = 'buttons'", "buttons"),
        (BUTTONS, "fixture = 'fixtures.buttons'", "fixtures.buttons"),
        (
            BUTTONS,
            "fixture = 'unknown'\nclamps = [{ ref = 'fixtures.buttons' }]",
            "clamp 1 fixtures.buttons",
        ),
    ],
    ids=["guide-qualified", "hold-qualified", "clamp-qualified"],
)
def test_filing_buttons_are_held_however_the_guide_and_hold_spell_them(
    tmp_path, guide, hold, owner
):
    plan = scratch(
        tmp_path, DRILL_BORE + STAIRS + bench_op(30, "file_to_line", guide=guide), hold=hold
    )
    row = manual_row(plan, 30)
    assert row.status == "pass", row.sentence
    assert row.numbers["guide"]["files_to_mm"] == pytest.approx([9.963, 10.032])
    filed = _filing_input(plan)
    assert filed["guide_owner"] == owner
    assert filed["guide_rim_dia_mm"] == pytest.approx([19.926, 20.064])


# Each element of the stack, given more tolerance, widens the worst-case filed band.
@pytest.mark.parametrize(
    ("name", "old", "new", "band"),
    [
        ("inventory.toml", "[19.99, 20.0]", "[19.95, 20.04]", [9.943, 10.052]),
        ("inventory.toml", "[6.0, 6.01]", "[6.0, 6.05]", [9.943, 10.052]),
        ("inventory.toml", "[5.99, 6.0]", "[5.95, 6.0]", [9.923, 10.072]),
        ("inventory.toml", "button_runout_mm = 0.004", "button_runout_mm = 0.04", [9.945, 10.05]),
        ("features.toml", "dia = [6.0, 6.03]", "dia = [6.0, 6.07]", [9.943, 10.052]),
        (
            "inventory.toml",
            "button_dia_limits_mm = [19.99, 20.0]",
            "button_dia_limits_in = [0.787, 0.7874]",
            [0.787 * 12.7 - 0.032, 0.7874 * 12.7 + 0.032],
        ),
    ],
    ids=["button-dia", "button-bore", "pin", "runout", "part-bore", "inch-button-dia"],
)
def test_every_stack_tolerance_widens_the_worst_case_filed_band(tmp_path, name, old, new, band):
    plan = scratch(tmp_path, FILE_BY_BUTTONS, hold="fixture = 'buttons'")
    change(plan.with_name(name), old, new)
    row = manual_row(plan, 30)
    assert row.status == "pass", row.sentence
    assert row.numbers["guide"]["files_to_mm"] == pytest.approx(band)


def _filing_input(plan):
    [filed] = [
        op
        for setup in build_job(load_bundle(plan))["setups"]
        for op in setup["ops"]
        if op["do"] == "file_to_line"
    ]
    return filed


# The kernel tells the buttons the file stops on from the rest of the kit (whose
# clearances it dimensions) by the rim band the declared stack files to worst case, the
# band the traveler prints: a button drawn at its Ø20 nominal is in it though the bought
# OD band (Ø19.980-19.993, a fit class below the nominal) is not. A stack element unknown
# leaves the band unknown, so whether the file bears on a kit solid stays unknown.
def test_the_kernel_finds_the_buttons_by_the_rim_band_the_stack_files_to(tmp_path):
    plan = scratch(tmp_path, FILE_BY_BUTTONS, hold="fixture = 'buttons'")
    change(plan.with_name("inventory.toml"), "[19.99, 20.0]", "[19.98, 19.993]")
    reach = [9.958, 10.0285]
    assert manual_row(plan, 30).numbers["guide"]["files_to_mm"] == pytest.approx(reach)
    filed = _filing_input(plan)
    assert filed["guide_owner"] == "buttons"
    low, high = filed["guide_rim_dia_mm"]
    assert [low / 2, high / 2] == pytest.approx(reach)
    assert low < 20.0 < high
    change(plan.with_name("inventory.toml"), "pin_dia_limits_mm = [5.99, 6.0]\n", "")
    assert _filing_input(plan)["guide_rim_dia_mm"] == "unknown"


# The kernel's rim band is the rule's proof: a stack the rule proves no filed radius from
# (a fact or the kit flagged to verify, a pin that may not enter its seats) gives the
# kernel no band, so whether the file bears on a kit solid stays unknown.
@pytest.mark.parametrize(
    ("old", "new"),
    [
        ("button_runout_mm = 0.004", "button_runout_mm = { value = 0.004, verify = true }"),
        (
            "pin_dia_limits_mm = [5.99, 6.0]",
            "pin_dia_limits_mm = { value = [5.99, 6.0], verify = true }",
        ),
        ("button_runout_mm = 0.004\nverify = false", "button_runout_mm = 0.004\nverify = true"),
        ("[5.99, 6.0]", "[5.99, 6.02]"),
    ],
    ids=["runout-to-verify", "pin-to-verify", "kit-to-verify", "pin-blocked"],
)
def test_the_kernel_has_no_rim_band_where_the_rule_proves_no_filed_radius(tmp_path, old, new):
    plan = scratch(tmp_path, FILE_BY_BUTTONS, hold="fixture = 'buttons'")
    change(plan.with_name("inventory.toml"), old, new)
    row = manual_row(plan, 30)
    assert row.status in ("unknown", "error"), row.sentence
    assert "files_to_mm" not in row.numbers["guide"]
    assert _filing_input(plan)["guide_rim_dia_mm"] == "unknown"


@pytest.mark.parametrize(
    ("name", "old", "new"),
    [
        # R9.925 - 0.032 = R9.893 under the R9.9 limit; R10.075 + 0.032 = R10.107 over R10.1.
        ("inventory.toml", "[19.99, 20.0]", "[19.85, 20.0]"),
        ("inventory.toml", "[19.99, 20.0]", "[19.99, 20.15]"),
        # Nominal Ø20 buttons fit, but a 0.15 runout shifts the rim 0.075 more both ways.
        ("inventory.toml", "button_runout_mm = 0.004", "button_runout_mm = 0.15"),
        # The collar-on-pin play alone carries the rim past both limits.
        ("inventory.toml", "[6.0, 6.01]", "[6.0, 6.15]"),
    ],
    ids=["under-the-low-limit", "over-the-high-limit", "runout", "collar-on-pin-play"],
)
def test_a_worst_case_filed_band_past_a_drawing_limit_is_an_error(tmp_path, name, old, new):
    plan = scratch(tmp_path, FILE_BY_BUTTONS, hold="fixture = 'buttons'")
    change(plan.with_name(name), old, new)
    row = manual_row(plan, 30)
    assert row.status == "error", row.sentence
    reach = row.numbers["guide"]["files_to_mm"]
    assert reach[0] < 9.9 or reach[1] > 10.1


@pytest.mark.parametrize(
    ("name", "old", "new"),
    [
        ("features.toml", "dia = [6.0, 6.03]", "dia = [5.998, 6.03]"),
        ("inventory.toml", "[6.0, 6.01]", "[5.998, 6.01]"),
    ],
    ids=["part-bore", "button-bore"],
)
def test_a_pin_that_may_not_enter_a_bore_at_its_limits_is_an_error(tmp_path, name, old, new):
    # The Ø6.000 largest pin does not enter a Ø5.998 smallest bore.
    plan = scratch(tmp_path, FILE_BY_BUTTONS, hold="fixture = 'buttons'")
    change(plan.with_name(name), old, new)
    row = manual_row(plan, 30)
    assert row.status == "error", row.sentence
    assert "files_to_mm" not in row.numbers["guide"]


@pytest.mark.parametrize(
    ("guide", "hold", "message"),
    [
        ("{ gauge = 'radius-gauge' }", "fixture = 'buttons'", "no filing guide"),
        ("{ buttons = 'buttons', bore = 'bore' }", "fixture = 'buttons'", "no radius gauge"),
        (BUTTONS, "fixture = 'unknown'", "not in setup S1's hold"),
        (
            "{ buttons = 'missing', bore = 'bore', gauge = 'radius-gauge' }",
            "fixture = 'buttons'",
            "not a filing_buttons kit",
        ),
        (
            "{ template = 'template', gauge = 'radius-gauge' }",
            "fixture = 'unknown'",
            "no scribe op lays out target",
        ),
    ],
    ids=[
        "no-guide",
        "no-gauge",
        "buttons-not-held",
        "buttons-not-in-inventory",
        "template-no-layout",
    ],
)
def test_missing_filing_kit_is_unknown(tmp_path, guide, hold, message):
    row = filing(tmp_path, guide, hold=hold)
    assert row.status == "unknown"
    assert message in " ".join(row.numbers["debts"])


@pytest.mark.parametrize(
    ("guide", "ops", "message"),
    [
        (
            "{ buttons = 'buttons', bore = 'bore', gauge = 'small-gauge' }",
            None,
            "reads 1 to 7.5 mm, not R10",
        ),
        (
            "{ buttons = 'buttons', bore = 'offset', gauge = 'radius-gauge' }",
            op(10, "drill", feature="offset", tool="bore-drill") + STAIRS,
            "offset is not on the arc's axis",
        ),
        (
            "{ buttons = 'buttons', bore = 'bore', gauge = 'radius-gauge' }",
            STAIRS,
            "not drilled, reamed or bored",
        ),
    ],
    ids=["gauge-range", "bore-off-axis", "bore-not-made"],
)
def test_filing_kit_that_cannot_reach_r_is_an_error(tmp_path, guide, ops, message):
    row = filing(tmp_path, guide, ops=ops if ops is not None else DRILL_BORE + STAIRS)
    assert row.status == "error"
    assert message in " ".join(row.numbers["errors"])


def test_filing_without_a_rough_or_an_established_cap_is_unknown(tmp_path):
    assert "no stairs or chain_drill op roughs target" in " ".join(
        filing(tmp_path / "rough", ops=DRILL_BORE).numbers["debts"]
    )
    plan = scratch(
        tmp_path / "cap",
        DRILL_BORE + STAIRS + bench_op(30, "file_to_line", guide=BUTTONS),
        hold="fixture = 'buttons'",
        policy='[required]\ncoordinates = "*"\n',
    )
    row = manual_row(plan, 30)
    assert row.status == "unknown"
    assert "sets no max_filing_stock_mm" in " ".join(row.numbers["debts"])


def test_template_guide_files_to_the_scribed_layout(tmp_path):
    scribe = bench_op(25, "scribe", layout="'template'", guide="{ template = 'template' }")
    row = filing(
        tmp_path,
        "{ template = 'template', gauge = 'radius-gauge' }",
        hold="fixture = 'unknown'",
        extra=scribe,
    )
    assert row.status == "pass", row.sentence
    assert row.numbers["layout_op"] == "S1:25"
    assert row.numbers["guide"] == {"kind": "template", "kit": "template"}


FILE_BY_BUTTONS = DRILL_BORE + STAIRS + bench_op(30, "file_to_line", guide=BUTTONS)
TEMPLATE_FILING = (
    STAIRS
    + bench_op(25, "scribe", layout="'template'", guide="{ template = 'template' }")
    + bench_op(30, "file_to_line", guide="{ template = 'template', gauge = 'radius-gauge' }")
)


_LIMITS = (
    "button_dia_limits_mm = [19.99, 20.0]\nbutton_bore_limits_mm = [6.0, 6.01]\n"
    "pin_dia_limits_mm = [5.99, 6.0]\nbutton_runout_mm = 0.004\n"
)


@pytest.mark.parametrize(
    ("ops", "name", "old", "new"),
    [
        (FILE_BY_BUTTONS, "features.toml", "dia = [6.0, 6.03]", "dia = [6.0, 'unknown']"),
        (FILE_BY_BUTTONS, "inventory.toml", "0.004\nverify = false", "0.004\nverify = true"),
        (
            FILE_BY_BUTTONS,
            "inventory.toml",
            "pin_dia_limits_mm = [5.99, 6.0]",
            "pin_dia_limits_mm = { value = [5.99, 6.0], verify = true }",
        ),
        (TEMPLATE_FILING, "features.toml", "dia = [19.8, 20.2]", "dia = 'unknown'"),
        # A kit known only by nominal sizes proves no worst-case band.
        (FILE_BY_BUTTONS, "inventory.toml", _LIMITS, "dia_mm = 20.0\nbore_dia_mm = 6.0\n"),
        (FILE_BY_BUTTONS, "inventory.toml", "button_dia_limits_mm = [19.99, 20.0]\n", ""),
        (FILE_BY_BUTTONS, "inventory.toml", "button_bore_limits_mm = [6.0, 6.01]\n", ""),
        (FILE_BY_BUTTONS, "inventory.toml", "pin_dia_limits_mm = [5.99, 6.0]\n", ""),
        (FILE_BY_BUTTONS, "inventory.toml", "button_runout_mm = 0.004\n", ""),
        (FILE_BY_BUTTONS, "inventory.toml", "[19.99, 20.0]", "[20.0, 19.99]"),
        (FILE_BY_BUTTONS, "inventory.toml", "[5.99, 6.0]", "[0.0, 6.0]"),
        (FILE_BY_BUTTONS, "inventory.toml", "[6.0, 6.01]", "[6.0, 'unknown']"),
        (FILE_BY_BUTTONS, "inventory.toml", "runout_mm = 0.004", "runout_mm = -0.004"),
    ],
    ids=[
        "bore-partly-unknown",
        "buttons-to-verify",
        "pin-to-verify",
        "arc-band-unknown",
        "nominal-sizes-only",
        "no-button-dia-limits",
        "no-button-bore-limits",
        "no-pin-limits",
        "no-runout",
        "reversed-limits",
        "zero-pin",
        "button-bore-partly-unknown",
        "negative-runout",
    ],
)
def test_filing_on_an_unknown_size_or_an_unverified_kit_is_unknown(tmp_path, ops, name, old, new):
    plan = scratch(tmp_path, ops, hold="fixture = 'buttons'")
    change(plan.with_name(name), old, new)
    row = manual_row(plan, 30)
    assert row.status == "unknown", row.sentence
    assert "files_to_mm" not in row.numbers["guide"]


SCRIBE_BY_TEMPLATE = bench_op(10, "scribe", layout="'template'", guide="{ template = 'template' }")
_SCRIBE_OP = bench_op(25, "scribe", layout="'template'", guide="{ template = 'template' }")
_NO_RANGE = "range_mm = 'unknown'"


# Every input the manual_arc rule leaves unknown, on a real evaluated finding: the
# traveler must stop that op, never print its layout or filing as an established step.
@pytest.mark.parametrize(
    ("ops", "number", "name", "old", "new"),
    [
        (FILE_BY_BUTTONS, 30, "features.toml", "dia = [19.8, 20.2]", "dia = 'unknown'"),
        (FILE_BY_BUTTONS, 30, "features.toml", "dia = [19.8, 20.2]", "dia = [19.8, 'unknown']"),
        (FILE_BY_BUTTONS, 30, "features.toml", "dia = [6.0, 6.03]", "dia = [6.0, 'unknown']"),
        (FILE_BY_BUTTONS, 30, "inventory.toml", "pin_dia_limits_mm = [5.99, 6.0]\n", ""),
        (FILE_BY_BUTTONS, 30, "inventory.toml", "0.004\nverify = false", "0.004\nverify = true"),
        (FILE_BY_BUTTONS, 30, "plan.toml", "fixture = 'buttons'", "fixture = 'unknown'"),
        (FILE_BY_BUTTONS, 30, "plan.toml", ", gauge = 'radius-gauge'", ""),
        (FILE_BY_BUTTONS, 30, "inventory.toml", "range_mm = [1.0, 25.0]", _NO_RANGE),
        (FILE_BY_BUTTONS, 30, "plan.toml", STAIRS, ""),
        (FILE_BY_BUTTONS, 30, "policy.toml", POLICY, '[required]\nmanual_arc = "*"\n'),
        (TEMPLATE_FILING, 30, "features.toml", "dia = [19.8, 20.2]", "dia = 'unknown'"),
        (TEMPLATE_FILING, 30, "plan.toml", _SCRIBE_OP, ""),
        (TEMPLATE_FILING, 30, "inventory.toml", "range_mm = [9.0, 11.0]", _NO_RANGE),
        (bench_op(10, "scribe", layout="'chalk'"), 10, "plan.toml", "", ""),
        (SCRIBE_BY_TEMPLATE, 10, "inventory.toml", "range_mm = [9.0, 11.0]", _NO_RANGE),
        (SCRIBE_BY_TEMPLATE, 10, "features.toml", "at = [20.0, 10.0, 0.0]", "at = 'unknown'"),
    ],
    ids=[
        "filing-arc-band-unknown",
        "filing-arc-band-partly-unknown",
        "filing-bore-partly-unknown",
        "filing-no-pin-limits",
        "filing-kit-to-verify",
        "filing-buttons-not-held",
        "filing-no-gauge",
        "filing-gauge-range-unknown",
        "filing-no-rough",
        "filing-no-stock-cap",
        "template-arc-band-unknown",
        "template-no-layout",
        "template-range-unknown",
        "scribe-layout-unknown",
        "scribe-template-range-unknown",
        "scribe-centre-unknown",
    ],
)
def test_every_unknown_manual_arc_input_stops_its_op_on_the_traveler(
    tmp_path, ops, number, name, old, new
):
    plan = scratch(tmp_path, ops, hold="fixture = 'buttons'")
    change(plan.with_name(name), old, new)
    bundle = load_bundle(plan)
    row = next(r for r in manual_arc.evaluate(bundle) if r.subject == f"S1:{number}")
    assert row.status == "unknown", row.sentence
    setup = bundle.plan["setups"][0]
    sheet = _Traveler(bundle, [row], {}, None)
    sheet.setup = setup
    table, _, _, stops = sheet.operations(setup, {}, {"notes": 2, "contours": None})
    printed = " ".join(unescape(re.sub(r"<[^>]+>", " ", table)).split())
    # The op's own manual instruction carries the STOP, and the setup's STOP list names it.
    step = printed[printed.index("Layout:" if number == 10 else "Bench filing:") :]
    assert "STOP" in step, step
    assert str(number) in [op for ops in stops.values() for op in ops], stops


@pytest.mark.parametrize(("layout", "status"), [("'dividers'", "pass"), ("'chalk'", "unknown")])
def test_scribe_prints_the_centre_radius_and_layout(tmp_path, layout, status):
    plan = scratch(tmp_path, bench_op(10, "scribe", layout=layout))
    row = manual_row(plan, 10)
    assert row.status == status
    assert row.numbers["centre_setup_xy"] == pytest.approx([15.0, 8.0])
    assert row.numbers["radius_mm"] == pytest.approx(10.0)
    assert row.numbers["radius_band_mm"] == pytest.approx([9.9, 10.1])
    assert row.numbers["ends_setup_xy"] is None  # a full circle has no ends


def inch(tmp_path, ops, dia="[1.99, 2.01]", *, units="in", hold="fixture = 'unknown'"):
    """The R1 in boss (band ``dia``) in ``units`` with the mm inventory: a Ø6 mm cutter."""
    target = ARC.replace("[19.8, 20.2]", dia).replace("dia_nominal = 20.0", "dia_nominal = 2.0")
    plan = scratch(tmp_path, ops, target=target, hold=hold)
    change(plan.with_name("features.toml"), 'units = "mm"', f'units = "{units}"')
    return plan


def test_inch_stairs_step_the_millimetre_cutter_and_report_millimetres(tmp_path):
    row = coordinates_row(inch(tmp_path, STAIRS))
    assert row.status == "pass", row.sentence
    (table,) = arcs(row, 20)
    centre, printed = table["centre_setup_xy"], [r["dro_xy"] for r in table["rows"]]
    assert min(math.dist(p, centre) for p in legs(printed)) - 3.0 / 25.4 >= 1.005 - 1e-6
    assert radial_stock(table, 3.0 / 25.4, 25.4) <= table["stock_left_mm"] + 1e-9
    assert table["stock_left_mm"] <= CAP


def test_inch_chords_offset_the_millimetre_cutter_inside_the_band_in_millimetres(tmp_path):
    contour = "{ method = 'chords', count = 24 }"
    chords = op(20, "finish_profile", contour)
    plan = inch(tmp_path, chords, "[1.98, 2.02]", hold="fixture = 'table'")
    row = coordinates_row(plan)
    assert row.status == "pass", row.sentence
    (table,) = arcs(row, 20)
    band = [0.99 * 25.4, 1.01 * 25.4]
    assert table["band_mm"] == pytest.approx(band)
    for chord in table["chords"]:
        low, high = chord["face_radius_mm"]
        assert band[0] - 1e-6 <= low <= high <= band[1] + 1e-6
    assert_printed_chord_band(table, band, scale=25.4)
    # Each printed cutter-centre corner sits about a 3 mm cutter radius outside R1 in.
    for r in table["rows"]:
        assert math.dist(r["dro_xy"], table["centre_setup_xy"]) == pytest.approx(
            1.0 + 3.0 / 25.4, abs=0.02
        )


def test_inch_chain_drills_the_millimetre_drill_at_the_millimetre_pitch(tmp_path):
    fine = op(30, "rough_profile", "{ method = 'stairs', cusp_mm = 0.25 }", allowance=0.2)
    row = coordinates_row(inch(tmp_path, CHAIN + fine))
    assert row.status == "pass", row.sentence
    (table,) = arcs(row, 20)
    centre, holes = table["centre_setup_xy"], [r["dro_xy"] for r in table["rows"]]
    assert table["drill_dia_mm"] == 3.0
    assert all(math.dist(p, centre) * 25.4 - 1.5 >= 1.005 * 25.4 - 1e-6 for p in holes)
    gaps = [math.dist(a, b) * 25.4 for a, b in itertools.pairwise(holes)]
    assert 3.0 < min(gaps) and max(gaps) <= 5.0 + 0.01
    assert table["pitch_mm"] == pytest.approx(max(gaps))
    wall = table["wall_radius_mm"]
    left = max(math.dist(p, centre) - wall for p in holes) * 25.4
    assert left >= 1.7 and table["stock_left_mm"] >= left - 1e-9


def test_a_manual_arc_in_unknown_units_is_unknown(tmp_path):
    row = coordinates_row(inch(tmp_path, STAIRS, units="unknown"))
    assert row.status == "unknown", row.sentence
    assert not arcs(row, 20)


def boundary_boss(tmp_path):
    """A 0.2 drill chain-drilling the Ø20 boss moved to Y 6.806673556724439 at a 0.29417
    pitch: row 127's model Y, 2.0000001275 at 207.8181818181818°, rounds to 9 decimals
    either way as its sine's last bit falls (the Windows CRT's -0.4666673232256736 against
    glibc's -0.46666732322567367)."""
    plan = scratch(
        tmp_path,
        op(20, "rough_profile", "{ method = 'chain_drill', pitch_mm = 0.29417 }", tool="drill")
        + "rough_allowance_mm = 0.2\n",
        target=ARC.replace("[20.0, 10.0, 0.0]", "[20.0, 6.806673556724439, 0.0]"),
    )
    inventory = plan.parent / "inventory.toml"
    inventory.write_text(INVENTORY.replace("dia_mm = 3.0", "dia_mm = 0.2"), encoding="utf-8")
    return plan


@pytest.mark.parametrize("toward", [math.inf, -math.inf], ids=["up", "down"])
@pytest.mark.parametrize(
    "build",
    [
        lambda tmp_path: (scratch(tmp_path, STAIRS), None),
        lambda tmp_path: (scratch(tmp_path, STAIRS, target=DISH), None),
        lambda tmp_path: (
            scratch(
                tmp_path,
                op(20, "finish_profile", "{ method = 'chords', count = 24 }"),
                hold="fixture = 'table'",
            ),
            None,
        ),
        lambda tmp_path: (rotary_plan(tmp_path), SWING),
        lambda tmp_path: (boundary_boss(tmp_path), None),
        lambda tmp_path: (joined_chain_plan(tmp_path), None),
    ],
    ids=[
        "convex stairs",
        "concave stairs",
        "chords",
        "rotary table",
        "decimal boundary",
        "finite chain joins",
    ],
)
def test_cutter_centre_tables_read_the_same_whichever_last_bit_libm_rounds_to(
    tmp_path, monkeypatch, build, toward
):
    # The Windows CRT's sine is not correctly rounded, so it can land an ULP either side of
    # glibc's: the rocker's report differed between Windows and Linux in those bits alone,
    # and no rounding of the table merges a pair that straddles its rounding boundary.
    plan, swing = build(tmp_path)
    exact = coordinates_row(plan, swing).numbers
    for name in ("sin", "cos", "atan2"):
        real = getattr(math, name)
        monkeypatch.setattr(math, name, lambda *a, real=real: math.nextafter(real(*a), toward))
    assert coordinates_row(plan, swing).numbers == exact
