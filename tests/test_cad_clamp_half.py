import re
from pathlib import Path
from xml.etree import ElementTree

import pytest

from prechips.cad import CadError
from prechips.cad_clamp_half import load_clamp_half
from prechips.cad_diagrams import SVG_NS, render_cad_svg
from prechips.clamp_diagrams import _shown_pass
from prechips.shaft_diagrams import CHAR

SVG = f"{{{SVG_NS}}}"

ROOT = Path(__file__).resolve().parents[1]
FRONT = ROOT / "examples/cad/clamp-front-v51.toml"
BACK = ROOT / "examples/cad/clamp-back-v51.toml"
BLANK = {
    "blank_length_min_in": 1.95,
    "blank_length_max_in": 2.05,
    "blank_section_in": 0.75,
}
# The back's plan: the front's bored depth band, .680–.690.
PAIR = {
    "parallel_thickness_mm": 3.175,
    "other_half_depth_min_mm": 17.272,
    "other_half_depth_max_mm": 17.526,
    "screw_length_mm": 31.75,
    "spacer_block_width_mm": 25.4,
    "screw_head_dia_mm": 6.858,
    "back_parallel_end_mm": 15.875,
}
PICTURES = BLANK | {
    "kerf_in": 0.125,
    "parallel_height_mm": 25.4,
    "riser_height_mm": 38.1,
    "vise_jaw_height_mm": 44.9453,
    "parallel_thickness_mm": 3.175,
    "screw_head_height_mm": 3.9624,
    # The tools and the work stop, drawn to scale.
    "face_cutter_dia_mm": 12.7,
    "face_stepover_max_mm": 6.4,
    "face_overhang_mm": 0.5,
    "half_mill_projection_mm": 28.45,
    "drill_tip_height_mm": -2.038,
    "tap_point_depth_mm": 19.05,
    "tap_guide_dia_mm": 12.7,
    "tap_guide_point_dia_mm": 4.7625,
    "stop_rod_dia_mm": 9.525,
    "stop_rod_top_max_mm": 11.176,
}


def test_both_halves_bind_the_envelope_bore_and_ears():
    front = load_clamp_half(FRONT, BLANK, "clamp-front").values
    back = load_clamp_half(BACK, BLANK, "clamp-back").values
    assert (front["half"], back["half"]) == ("front", "back")
    for values in (front, back):
        assert values["width_band_mm"] == [47.752, 48.26]
        assert values["height_band_mm"] == [15.748, 16.256]
        # The bore is the column plus the diametral clearance: 1.004–1.012.
        assert values["bore_dia_band_mm"] == pytest.approx([25.5016, 25.7048])
        assert values["bore_location_band_mm"] == [23.749, 24.257]
        assert values["ear_station_band_mm"] == [17.399, 17.6022]
        # One common zero at the near side: the ears at .256 and 1.634.
        assert values["ear_near_x_in"] == pytest.approx(0.256)
        assert values["ear_far_x_in"] == pytest.approx(1.634)
        # Drilled before the bore: the station band about its nominal location.
        for key, band in (
            ("ear_near_x", (0.252, 0.260)),
            ("ear_far_x", (1.630, 1.638)),
        ):
            assert values[f"{key}_min_in"] == pytest.approx(band[0], abs=1e-4)
            assert values[f"{key}_max_in"] == pytest.approx(band[1], abs=1e-4)
            assert values[f"{key}_band_mm"] == pytest.approx(
                [band[0] * 25.4, band[1] * 25.4], abs=1e-3
            )
        assert values["ear_y_in"] == pytest.approx(0.315)
        assert values["end_stock_min_in"] == pytest.approx(0.05)
    assert front["depth_band_mm"] == [17.272, 17.526]
    assert front["ear_clearance_for"] == "#8"
    # Least ear wall at the extremes: .685 − .200/2 − 1.012/2 = .079 ≥ .072.
    assert front["ear_wall_worst_in"] == pytest.approx(0.079, abs=1e-4)
    assert front["ear_wall_min_in"] == pytest.approx(0.072)
    # The greatest wall: .693 − .196/2 − 1.004/2 = .093.
    assert front["ear_wall_best_in"] == pytest.approx(0.093, abs=1e-4)
    assert front["finish"].startswith("black enamel")
    assert back["ear_thread"] == "#8-32 UNC-2B"
    # The tapped ears' edge is the #8 major, .164: .685 − .082 − .506 = .097.
    assert back["ear_wall_worst_in"] == pytest.approx(0.097, abs=1e-4)
    assert back["ear_edge_wall_worst_in"] == pytest.approx(0.219, abs=1e-4)
    # The back is sized .020 deeper than drawn, then faced back after the bore,
    # so its ears are drilled through the deeper half.
    assert back["grip_offset_band_mm"] == [0.381, 0.635]
    assert back["pre_face_depth_band_mm"] == pytest.approx([15.24, 15.748])
    assert back["bore_axis_depth_mm"] == pytest.approx(15.494)
    assert back["ear_depth_in"] == pytest.approx(0.61)
    required = {
        axis.name: axis.required_mm
        for axis in load_clamp_half(BACK, {}, "clamp-back").stock_requirement.axes
    }
    assert required == pytest.approx(
        {"length": 48.006, "height": 16.002, "depth": 15.494}
    )


def test_the_pair_and_its_holds():
    values = load_clamp_half(BACK, PAIR, "clamp-back").values
    assert values["pair_depth_band_mm"] == pytest.approx([32.512, 33.274])
    assert values["pair_depth_in"] == pytest.approx(1.295)
    # A 1-1/4 screw stops .030 short of the back face of the thinnest pair.
    assert values["screw_short_in"] == pytest.approx(0.030)
    # A 1 in block between heads Ø.270 at .685 least: .050 clear each side.
    assert values["block_head_clear_in"] == pytest.approx(0.050)
    assert values["back_parallel_clear_in"] == pytest.approx(0.119, abs=1e-6)
    for change, message in (
        # The back's wall behind the bore is .094 at the extremes.
        ({"back_parallel_end_mm": 12.8}, "must clear the"),
        # Past the near side, the parallel is not under the back at all.
        ({"back_parallel_end_mm": 24.0}, "still reach under the back"),
        # 32.8 mm passes the nominal 32.893 but not the least 32.512.
        ({"screw_length_mm": 32.8}, "reaches the back face of the thinnest"),
        ({"spacer_block_width_mm": 28.0}, "reaches the"),
        # The back's threads come within .219 of its bottom and top faces.
        ({"parallel_thickness_mm": 5.7}, "reach the ear holes"),
        ({"other_half_depth_min_mm": 17.6}, "over other_half_depth_max_mm"),
    ):
        with pytest.raises(CadError, match=message):
            load_clamp_half(BACK, PAIR | change, "clamp-back")
    # The same pair judged from the front's plan, the back's band authored:
    # a 2.5 mm parallel reaches the back's bore at its 15.24 mm least depth.
    front = PAIR | {
        "other_half_depth_min_mm": 15.24,
        "other_half_depth_max_mm": 15.748,
        "parallel_thickness_mm": 2.5,
    }
    del front["back_parallel_end_mm"]
    with pytest.raises(CadError, match="stop it short with back_parallel_end_mm"):
        load_clamp_half(FRONT, front, "clamp-front")
    with pytest.raises(CadError, match="also need other_half_depth_max_mm"):
        load_clamp_half(BACK, {"other_half_depth_min_mm": 17.272}, "clamp-back")
    with pytest.raises(CadError, match="under the largest bored depth, 0.690"):
        load_clamp_half(FRONT, BLANK | {"blank_section_in": 0.65}, "clamp-front")
    without = {
        key: value for key, value in PAIR.items() if key != "back_parallel_end_mm"
    }
    with pytest.raises(CadError, match="stop it short with back_parallel_end_mm"):
        load_clamp_half(BACK, without, "clamp-back")
    with pytest.raises(CadError, match="also need blank_length_max_in"):
        load_clamp_half(BACK, {"blank_length_min_in": 1.95}, "clamp-back")
    with pytest.raises(CadError, match="shorter than the widest finished half"):
        load_clamp_half(BACK, BLANK | {"blank_length_min_in": 1.89}, "clamp-back")


@pytest.mark.parametrize(
    ("source", "old", "new", "message"),
    [
        # A bore up to 1.0236 (.0236 clearance) leaves the ears under .072.
        (
            FRONT,
            '"diametral_clearance" = [0.1016, 0.3048]',
            '"diametral_clearance" = [0.1016, 0.7]',
            "under the 1.8288 mm least ear wall",
        ),
        (
            FRONT,
            '"station" = [-17.6022, -17.399]',
            '"station" = [-17.6022, -17.3]',
            "mirror of ear_hole_1",
        ),
        (
            BACK,
            '"grip_offset_nominal" = 0.508',
            '"grip_offset_nominal" = 0.6',
            "grip offset behind the bore axis",
        ),
        # Clamped, the gap is the grip offset less the clearance: .010 at
        # least against .012 most closes the halves on each other.
        (
            BACK,
            '"grip_offset" = [0.381, 0.635]',
            '"grip_offset" = [0.254, 0.635]',
            "would close before gripping the column",
        ),
        (
            BACK,
            '"thread" = "#8-32 UNC-2B"\n"dia" = [3.454, 3.5556]\n"tap_drill_nominal" = 3.454\n"thru" = true\n"thread_length_nominal" = 14.986\n"station" = [-17.6022',
            '"thread" = "#10-32 UNF-2B"\n"dia" = [3.454, 3.5556]\n"tap_drill_nominal" = 3.454\n"thru" = true\n"thread_length_nominal" = 14.986\n"station" = [-17.6022',
            "ear_tap_2.thread: disagrees",
        ),
        (
            FRONT,
            '"location_nominal" = 24.003',
            '"location_nominal" = 24.1',
            "location from near_side",
        ),
        (FRONT, '"open_to" = "mating_face"', '"open_to" = "bar_face"', "half bore"),
    ],
)
def test_manifests_that_disagree_with_themselves_refuse(
    tmp_path, source, old, new, message
):
    text = source.read_text(encoding="utf-8")
    assert text.count(old) == 1
    path = tmp_path / "cad.toml"
    path.write_text(text.replace(old, new), encoding="utf-8")
    with pytest.raises(CadError, match=message):
        load_clamp_half(path, {}, source.stem.removesuffix("-v51"))


def _picture(cad, parameters, **attrs: str) -> str:
    extra = "".join(f' data-{key}="{value}"' for key, value in attrs.items())
    root = (
        '<svg xmlns="http://www.w3.org/2000/svg" data-cad-template="clamp-half"'
        f"{extra}/>"
    ).encode()
    return render_cad_svg(root, cad, parameters).decode()


def test_every_picture_binds_for_both_halves():
    halves = (
        (
            FRONT,
            "clamp-front",
            PAIR
            | {"other_half_depth_min_mm": 15.24, "other_half_depth_max_mm": 15.748},
        ),
        (BACK, "clamp-back", PAIR),
    )
    holds = [
        {"step": "saw"},
        {"step": "pair"},
        {"step": "inspect"},
        {"step": "inspect", "bored": "no"},
        {"step": "half", "up": "end", "work": "face", "end": "first"},
        {"step": "half", "up": "end", "work": "face", "end": "length"},
        {"step": "half", "up": "bottom", "work": "face"},
        {"step": "half", "up": "top", "work": "face"},
        {"step": "half", "up": "mating", "work": "face"},
        {"step": "half", "up": "outside", "work": "drill"},
        {"step": "half", "up": "outside", "work": "tap"},
    ]
    for source, part, pair in halves:
        parameters = PICTURES | pair
        cad = load_clamp_half(source, parameters, part)
        for attrs in holds:
            if attrs.get("work") == "tap" and part == "clamp-front":
                with pytest.raises(CadError, match="only the back's ears"):
                    _picture(cad, parameters, **attrs)
                continue
            assert "{{" not in _picture(cad, parameters, **attrs)
        # The bore is a REF size with its fit, not a size band, once cut.
        assert "REF" in _picture(cad, parameters, step="inspect")
        assert "REF" not in _picture(cad, parameters, step="inspect", bored="no")
    back = load_clamp_half(BACK, PICTURES | PAIR, "clamp-back")
    drill = _picture(back, PICTURES, step="half", up="outside", work="drill")
    assert "#8-32 UNC-2B tap drill" in drill
    assert "face .015–.025 off," in _picture(
        back, PICTURES, step="half", up="mating", work="face-off"
    )
    pair = _picture(back, PICTURES | PAIR, step="pair")
    assert "ends .625 from the axis" in pair
    assert ".050 clear each side" in pair
    # A back parallel thin enough to run full length draws without a stop.
    thin = PAIR | {"parallel_thickness_mm": 2.0}
    del thin["back_parallel_end_mm"]
    whole = load_clamp_half(BACK, PICTURES | thin, "clamp-back")
    assert "from the axis" not in _picture(whole, PICTURES | thin, step="pair")
    # A long blank still fits the saw picture, with bar left beyond the kerf.
    long = PICTURES | {"blank_length_max_in": 4.5}
    saw = _picture(load_clamp_half(BACK, long, "clamp-back"), long, step="saw")
    assert not re.search(r'width="-', saw)
    front = load_clamp_half(FRONT, PICTURES, "clamp-front")
    with pytest.raises(CadError, match="only the back's mating face"):
        _picture(front, PICTURES, step="half", up="mating", work="face-off")
    with pytest.raises(CadError, match="data-work must be one of face, drill, tap"):
        _picture(front, PICTURES, step="half", up="outside", work="face-off")


def _text_x(svg: str, text: str) -> float:
    return float(re.search(rf'<text x="([-\d.]+)"[^>]*>{re.escape(text)}<', svg)[1])


def _datum_x(svg: str) -> float:
    return float(re.search(r'<g class="datum"><line x1="([-\d.]+)"', svg)[1])


def test_lying_holds_put_the_near_side_where_the_hold_does():
    front = load_clamp_half(FRONT, PICTURES, "clamp-front")
    back = load_clamp_half(BACK, PICTURES | PAIR, "clamp-back")
    width = back.values["width_mm"] * 6

    def hold(cad, up, work):
        return _picture(cad, PICTURES, step="half", up=up, work=work)

    # Bottom face on the fixed jaw: the face up looking toward +X (the
    # front's outside, the back's mating face) puts the near side at the right.
    for cad, left, right in (
        (front, ("mating", "face"), ("outside", "drill")),
        (back, ("outside", "drill"), ("mating", "face")),
    ):
        plain, mirror = hold(cad, *left), hold(cad, *right)
        assert _datum_x(mirror) >= _datum_x(plain) + width - 0.01
        assert _text_x(mirror, "X0: near side") > _datum_x(mirror)
        # The jaw label, now ending left of the part, stays on the page at
        # the pictures' conservative glyph width.
        label = "fixed jaw: BOTTOM face"
        assert _text_x(mirror, label) > len(label) * CHAR
    assert _datum_x(hold(back, "mating", "face-off")) == _datum_x(
        hold(back, "mating", "face")
    )
    # The stations run away from the near side.
    plain, mirror = hold(back, "outside", "drill"), hold(front, "outside", "drill")
    assert _text_x(plain, ".256") < _text_x(plain, "1.634")
    assert _text_x(mirror, ".256") > _text_x(mirror, "1.634")
    for attrs, message in (
        ({"step": "pair", "bored": "no"}, "data-bored goes with the inspect step"),
        ({"step": "inspect", "bored": "maybe"}, "data-bored must be yes or no"),
    ):
        with pytest.raises(CadError, match=message):
            _picture(back, PICTURES, **attrs)


def _group(svg: str, role: str) -> list[ElementTree.Element]:
    root = ElementTree.fromstring(svg)
    return [
        child
        for group in root.iter(f"{SVG}g")
        if group.get("class") == role
        for child in group
    ]


def _points(element: ElementTree.Element) -> list[tuple[float, float]]:
    """A path's points: each M/L pair and each arc's end point."""
    points = []
    for command, body in re.findall(r"([MLA])([^MLAZ]*)", element.get("d")):
        numbers = [float(n) for n in re.findall(r"-?[\d.]+", body)]
        if command == "A":
            points.append((numbers[-2], numbers[-1]))
        else:
            points += list(zip(numbers[::2], numbers[1::2]))
    return points


def _span(element: ElementTree.Element, axis: int) -> float:
    """A path's extent along x (0) or y (1), px. A tool's round end bulges
    its arc's vertical radius below its lowest corners: that apex is its tip."""
    values = [point[axis] for point in _points(element)]
    arcs = re.findall(r"A\s*[-\d.]+\s+([-\d.]+)", element.get("d"))
    if axis == 1 and arcs:
        values.append(max(values) + float(arcs[0]))
    return max(values) - min(values)


def test_the_pass_shown_stands_over_the_part():
    # The plan's own count: a 3/4 in face takes four passes of 4.89 (19.05
    # plus the 0.5 overhang), the .630 face three of 5.50. The first hangs
    # over the fixed jaw; the picture shows the one least past either edge.
    inside, step, index, count = _shown_pass(PICTURES, 19.05)
    assert (index, count) == (2, 4)
    assert step == pytest.approx(19.55 / 4)
    assert inside == pytest.approx(3 * 19.55 / 4 - 6.35)
    assert inside - 6.35 >= 0 and inside + 6.35 <= 19.05
    assert _shown_pass(PICTURES, 16.002)[1:] == (pytest.approx(16.502 / 3), 2, 3)
    with pytest.raises(CadError, match="face_overhang_mm: must not be negative"):
        _shown_pass(PICTURES | {"face_overhang_mm": -0.1}, 19.05)


def test_tools_are_drawn_to_scale():
    front = load_clamp_half(FRONT, PICTURES, "clamp-front")
    back = load_clamp_half(BACK, PICTURES | PAIR, "clamp-back")

    def cutters(cad, parameters=PICTURES, **attrs):
        return _group(_picture(cad, parameters, step="half", **attrs), "cutter")

    # The end mill along the jaws, 1/2 in wide at the picture's px per mm
    # (6 lying, 4 upright) and its stick-out tall; from above a 1/2 in circle.
    side, above = cutters(front, up="bottom", work="face")
    assert _span(side, 0) == pytest.approx(12.7 * 6, abs=0.2)
    assert _span(side, 1) == pytest.approx(28.45 * 6, abs=0.2)
    # Its square end drawn round (the near half of the end face), shallow:
    # 12 % of the diameter deep, its apex the tool's true end.
    rise = float(re.search(r"A\s*[-\d.]+\s+([-\d.]+)", side.get("d"))[1])
    assert rise == pytest.approx(0.12 * 12.7 * 6, abs=0.1)
    assert float(above.get("r")) == pytest.approx(12.7 * 3, abs=0.01)
    upright = cutters(front, up="end", work="face", end="first")[0]
    assert _span(upright, 0) == pytest.approx(12.7 * 4, abs=0.2)
    # One moment per picture: facing the outside face draws the end mill in
    # both views; the drill's own picture the drill at its hole's diameter
    # (the front's #9, the back's #29) in both, and no end mill.
    side, above = cutters(front, up="outside", work="face")
    assert _span(side, 0) == pytest.approx(12.7 * 6, abs=0.2)
    assert float(above.get("r")) == pytest.approx(12.7 * 3, abs=0.01)
    for cad in (front, back):
        drill, hole = cutters(cad, up="outside", work="drill")
        width = cad.values["ear_dia_in"] * 25.4 * 6
        assert _span(drill, 0) == pytest.approx(width, abs=0.2)
        assert float(hole.get("r")) == pytest.approx(width / 2, abs=0.01)
    # The tap at its thread's major diameter, the guide at its own sizes.
    tap, point, guide, plan = cutters(back, up="outside", work="tap")
    assert _span(tap, 0) == pytest.approx(
        back.values["ear_thread_major_mm"] * 6, abs=0.2
    )
    assert _span(point, 0) == pytest.approx(4.7625 * 6, abs=0.2)
    assert _span(guide, 0) == pytest.approx(12.7 * 6, abs=0.2)
    assert float(plan.get("r")) == pytest.approx(
        back.values["ear_thread_major_mm"] * 3, abs=0.01
    )
    # The pair's end mill on the bore's wall.
    pair = _group(_picture(back, PICTURES | PAIR, step="pair"), "cutter")[0]
    assert float(pair.get("r")) == pytest.approx(12.7 * 3, abs=0.01)


def test_the_work_stop_is_drawn_where_the_template_fits_it():
    front = load_clamp_half(FRONT, PICTURES, "clamp-front")
    back = load_clamp_half(BACK, PICTURES | PAIR, "clamp-back")

    def rods(cad, **attrs):
        svg = _picture(cad, PICTURES, step="half", **attrs)
        return svg, _group(svg, "stop-rod")

    hold = {"up": "mating", "work": "face"}
    assert rods(front, **hold)[1] == []
    # From above a bar its diameter wide; end-on a circle, its top at the
    # highest the plan allows.
    svg, (end, bar) = rods(front, **hold, stop="rod")
    ys = [y for _, y in _points(bar)]
    assert max(ys) - min(ys) == pytest.approx(9.525 * 6, abs=0.2)
    assert float(end.get("r")) == pytest.approx(9.525 * 3, abs=0.01)
    assert "work stop" not in svg
    # At the near side: left of the X0 line for a front's mating face (in
    # front of the part along the jaws), right of it for a back's (behind).
    for cad, outward in ((front, -1), (back, 1)):
        svg, (end, bar) = rods(cad, **hold, stop="rod")
        xs = [x for x, _ in _points(bar)]
        tip = _datum_x(svg)
        assert all((x - tip) * outward >= -0.1 for x in xs)
        assert (end.get("stroke-dasharray") is None) == (outward < 0)
    # Named once, upright, with when it is set.
    svg, _ = rods(front, up="end", work="face", end="first", stop="rod-labelled")
    assert "work stop: Ø.375 rod from its post" in svg
    assert "touch-offs, then set on the LEFT face" in svg
    for attrs, message in (
        ({"step": "pair", "stop": "rod"}, "data-stop goes with the half step"),
        ({"step": "half", **hold, "stop": "post"}, "data-stop must be one of rod"),
    ):
        with pytest.raises(CadError, match=message):
            _picture(front, PICTURES, **attrs)
