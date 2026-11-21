import re
from pathlib import Path

import pytest

from prechips.cad import CadError
from prechips.cad_clamp_half import load_clamp_half
from prechips.cad_diagrams import render_cad_svg
from prechips.shaft_diagrams import CHAR

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
        {"step": "half", "up": "mating", "work": "face", "x0": "right"},
        {"step": "half", "up": "outside", "work": "drill"},
        {"step": "half", "up": "outside", "work": "drill", "x0": "right"},
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
        text = "\n".join(
            re.findall(r">([^<]+)</text>", _picture(cad, parameters, step="inspect"))
        )
        assert "Ø(1.008) REF\non the bore axis," in text
        assert ".004–.012 clearance\non the column" in text
        assert "Ø1.004" not in text
        unbored = _picture(cad, parameters, step="inspect", bored="no")
        assert "drill exits: deburr" in unbored
        assert "REF" not in unbored
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
    with pytest.raises(CadError, match="data-work must be one of drill, tap"):
        _picture(front, PICTURES, step="half", up="outside", work="face")


def _text_x(svg: str, text: str) -> float:
    return float(re.search(rf'<text x="([-\d.]+)"[^>]*>{re.escape(text)}<', svg)[1])


def _datum_x(svg: str) -> float:
    return float(re.search(r'<g class="datum"><line x1="([-\d.]+)"', svg)[1])


def test_mirrored_hold_draws_the_near_side_at_the_right():
    back = load_clamp_half(BACK, PICTURES | PAIR, "clamp-back")
    plain = _picture(back, PICTURES, step="half", up="outside", work="drill")
    mirror = _picture(
        back, PICTURES, step="half", up="outside", work="drill", x0="right"
    )
    # X0 moves to the part's other end, and the stations run leftward.
    assert _datum_x(mirror) >= _datum_x(plain) + back.values["width_mm"] * 6 - 0.01
    # The jaw label, now ending left of the part, stays on the page at the
    # pictures' conservative glyph width.
    label = "fixed jaw: BOTTOM face"
    assert _text_x(mirror, label) > len(label) * CHAR
    assert _text_x(plain, ".256") < _text_x(plain, "1.634")
    assert _text_x(mirror, ".256") > _text_x(mirror, "1.634")
    assert _text_x(mirror, "X0: near side") > _datum_x(mirror)
    pair = _picture(back, PICTURES | PAIR, step="pair")
    assert "interpolate Ø(1.008) REF<" in pair
    assert ".004–.012 clearance<" in pair
    for attrs, message in (
        ({"x0": "middle"}, "data-x0 must be left or right"),
        ({"step": "inspect", "x0": "right"}, "data-x0 goes with the half step"),
        ({"up": "end", "end": "first", "x0": "right"}, "not data-up end"),
        ({"step": "pair", "bored": "no"}, "data-bored goes with the inspect step"),
        ({"step": "inspect", "bored": "maybe"}, "data-bored must be yes or no"),
    ):
        attrs = {"step": "half", "up": "outside", "work": "drill"} | attrs
        if attrs["up"] == "end":
            attrs["work"] = "face"
        with pytest.raises(CadError, match=message):
            _picture(back, PICTURES, **attrs)
