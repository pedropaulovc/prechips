"""Consumer-visible raster, camera, visibility and print-label contracts; no FreeCAD."""

import json
import math
import re
import struct
import zlib
from pathlib import Path

import pytest

from prechips.kernel.render_diagram import (
    _CONTACT,
    _corners,
    _Diagram,
    _holding_details,
    _tag_at,
    render_diagram,
)
from prechips.kernel.render_inputs import contour_annotations
from prechips.kernel.render_png import RenderCanvas

_FRONT = ((1, 0, 0), (0, 1, 0), (0, 0, 1))
_WHITE = (255, 255, 255)


def _canvas(meshes=(), camera=_FRONT, width=200, height=200):
    return RenderCanvas(meshes, camera, viewport=(0, 0, width, height), width=width, height=height)


def _pixel(canvas, x, y):
    offset = (y * canvas.width + x) * 3
    return tuple(canvas.rgb[offset : offset + 3])


def _decode_png(data):
    """Check the actual PNG envelope, CRCs, compressed rows and RGB pixel payload."""
    assert data[:8] == b"\x89PNG\r\n\x1a\n"
    chunks = []
    offset = 8
    compressed = bytearray()
    while offset < len(data):
        size = struct.unpack_from(">I", data, offset)[0]
        kind = data[offset + 4 : offset + 8]
        payload = data[offset + 8 : offset + 8 + size]
        checksum = struct.unpack_from(">I", data, offset + 8 + size)[0]
        assert checksum == zlib.crc32(kind + payload) & 0xFFFFFFFF
        chunks.append(kind)
        if kind == b"IHDR":
            width, height, bits, colour, compression, filtering, interlace = struct.unpack(
                ">IIBBBBB", payload
            )
            assert (bits, colour, compression, filtering, interlace) == (8, 2, 0, 0, 0)
        elif kind == b"IDAT":
            compressed.extend(payload)
        elif kind == b"IEND":
            assert payload == b""
        offset += size + 12
    assert offset == len(data)
    assert chunks[0] == b"IHDR" and chunks[-1] == b"IEND"
    assert all(kind == b"IDAT" for kind in chunks[1:-1])  # no timestamps or other metadata
    raw = zlib.decompress(compressed)
    stride = width * 3
    assert len(raw) == (stride + 1) * height
    pixels = bytearray()
    previous = bytearray(stride)
    for y in range(height):
        start = y * (stride + 1)
        filtering = raw[start]
        row = bytearray(raw[start + 1 : start + stride + 1])
        # Decode all standard filters so changing the encoder's filter strategy
        # cannot turn an incidental implementation choice into a test contract.
        if filtering:
            assert 1 <= filtering <= 4
            for i in range(stride):
                left = row[i - 3] if i >= 3 else 0
                above = previous[i]
                upper_left = previous[i - 3] if i >= 3 else 0
                if filtering == 1:
                    predictor = left
                elif filtering == 2:
                    predictor = above
                elif filtering == 3:
                    predictor = (left + above) // 2
                else:
                    estimate = left + above - upper_left
                    distances = (
                        abs(estimate - left),
                        abs(estimate - above),
                        abs(estimate - upper_left),
                    )
                    predictor = (left, above, upper_left)[distances.index(min(distances))]
                row[i] = (row[i] + predictor) & 255
        pixels.extend(row)
        previous = row
    return width, height, pixels


def _square(z, colour, hatch=False):
    return (
        ((0, 0, z), (10, 0, z), (10, 10, z), (0, 10, z)),
        ((0, 1, 2), (0, 2, 3)),
        colour,
        hatch,
    )


def _printed_scene():
    camera = (
        (1 / math.sqrt(2), 1 / math.sqrt(2), 0),
        (-1 / math.sqrt(6), 1 / math.sqrt(6), 2 / math.sqrt(6)),
        (1 / math.sqrt(3), -1 / math.sqrt(3), 1 / math.sqrt(3)),
    )
    points = (
        (0, 0, 0),
        (20, 0, 0),
        (20, 10, 0),
        (0, 10, 0),
        (0, 0, 8),
        (20, 0, 8),
        (20, 10, 8),
        (0, 10, 8),
    )
    triangles = (
        (0, 1, 2),
        (0, 2, 3),
        (4, 6, 5),
        (4, 7, 6),
        (0, 4, 5),
        (0, 5, 1),
        (1, 5, 6),
        (1, 6, 2),
        (2, 6, 7),
        (2, 7, 3),
        (3, 7, 4),
        (3, 4, 0),
    )
    removal = (((2, 2, 8.1), (18, 2, 8.1), (2, 8, 8.1)), ((0, 1, 2),), (240, 170, 50), True)
    canvas = RenderCanvas(((points, triangles, (160, 175, 185)), removal), camera)
    canvas.text(70, 70, "Setup 12 — Ø6 ±0.1 mm / 90°")
    canvas.rect(70, 810, 550, 95, (248, 248, 248), outline=(30, 35, 40))
    canvas.text(90, 835, "Clamp here; keep jaw clear!")
    canvas.line((80, 760), (1520, 760), (70, 70, 70), dashed=True)
    canvas.arrow((1350, 110), canvas.project((20, 10, 8)), (35, 45, 55))
    canvas.circle(1320, 825, 25, fill=(255, 230, 180), outline=(30, 35, 40))
    canvas.polygon(((1410, 800), (1460, 850), (1360, 850)), (210, 100, 30))
    return canvas


def test_png_is_deterministic_and_encodes_the_complete_default_canvas():
    first, second = _printed_scene(), _printed_scene()
    encoded = first.png()
    assert encoded == first.png() == second.png()
    width, height, pixels = _decode_png(encoded)
    assert (width, height) == (1600, 1000)
    assert pixels == first.rgb
    assert _pixel(first, 0, 0) == _WHITE
    assert _pixel(first, 1320, 825) == (255, 230, 180)
    # Encoding must not consume or freeze the mutable annotation surface.
    first.rect(0, 0, 4, 4, (10, 20, 30))
    _, _, changed = _decode_png(first.png())
    assert changed[:3] == bytes((10, 20, 30))
    assert encoded != first.png()


def test_profile_camera_projects_y_right_z_up_with_aspect_preserving_fit():
    points = ((2, -10, -5), (2, 10, -5), (2, 10, 5), (2, -10, 5))
    camera = ((0, 1, 0), (0, 0, 1), (1, 0, 0))
    canvas = RenderCanvas(
        ((points, ((0, 1, 2), (0, 2, 3)), (180, 150, 120)),),
        camera,
        viewport=(10, 10, 190, 170),
        width=200,
        height=180,
    )
    assert canvas.scale == pytest.approx(8.1)
    assert canvas.project((2, 0, 0)) == pytest.approx((100, 90))
    assert canvas.project((2, 10, 0)) == pytest.approx((181, 90))
    assert canvas.project((2, 0, 5)) == pytest.approx((100, 49.5))
    assert canvas.project((200, 0, 0)) == canvas.project((2, 0, 0))
    assert _pixel(canvas, 100, 90) != _WHITE
    assert _pixel(canvas, 18, 90) == _WHITE
    assert _pixel(canvas, 100, 48) == _WHITE


@pytest.mark.parametrize("toward,visible_channel", [((1, 0, 0), 2), ((-1, 0, 0), 0)])
@pytest.mark.parametrize("reverse", [False, True])
def test_camera_depth_controls_the_visible_face_independently_of_mesh_order(
    toward, visible_channel, reverse
):
    def face(x, colour):
        return (
            ((x, 0, 0), (x, 10, 0), (x, 10, 10), (x, 0, 10)),
            ((0, 1, 2), (0, 2, 3)),
            colour,
        )

    meshes = [face(0, (220, 10, 10)), face(2, (10, 10, 220))]
    if reverse:
        meshes.reverse()
    canvas = _canvas(meshes, ((0, 1, 0), (0, 0, 1), toward))
    pixel = _pixel(canvas, 100, 100)
    assert pixel[visible_channel] > 4 * max(pixel[i] for i in range(3) if i != visible_channel)


def test_hatch_is_clipped_to_visible_triangles_and_cannot_bleed_through_occlusion():
    points = ((0, 0, 0), (10, 0, 0), (0, 10, 0))
    triangles = ((0, 1, 2),)
    colour = (240, 175, 60)
    solid = _canvas(((points, triangles, colour),))
    hatched = _canvas(((points, triangles, colour, True),))
    assert _pixel(hatched, 100, 104) != _pixel(solid, 100, 104)
    assert all(
        a < b for a, b in zip(_pixel(hatched, 100, 104), _pixel(solid, 100, 104), strict=False)
    )
    assert _pixel(hatched, 100, 110) == _pixel(solid, 100, 110)
    assert _pixel(hatched, 110, 40) == _WHITE  # inside bounding box, outside the triangle
    assert _pixel(hatched, 5, 104) == _WHITE
    front = _square(1, (100, 140, 190))
    expected = _canvas((front,))
    for meshes in (
        (front, (points, triangles, colour, True)),
        ((points, triangles, colour, True), front),
    ):
        assert _canvas(meshes).rgb == expected.rgb


def test_bitmap_text_is_crisp_at_print_scale_and_distinguishes_case_and_symbols():
    label = "AaO01I:Ø±90°"
    small = _canvas(width=100, height=20)
    printed = _canvas(width=300, height=60)
    colour = (20, 30, 40)
    small.text(0, 0, label, colour, scale=1)
    printed.text(0, 0, label, colour, scale=3)
    assert printed.text_width(label) == 3 * small.text_width(label, scale=1)
    for y in range(7):
        for x in range(small.text_width(label, scale=1)):
            expected = _pixel(small, x, y)
            for dy in range(3):
                for dx in range(3):
                    assert _pixel(printed, x * 3 + dx, y * 3 + dy) == expected

    def cell(index):
        return tuple(_pixel(small, index * 6 + x, y) for y in range(7) for x in range(5))

    assert cell(0) != cell(1)  # A and a
    assert cell(2) != cell(3)  # O and zero
    assert cell(4) != cell(5)  # one and I
    assert _pixel(printed, 6, 6) == _WHITE  # open counter of A
    assert _pixel(printed, 0, 9) == colour  # readable vertical stroke
    assert _pixel(printed, 14, 20) == colour
    assert _pixel(printed, 15, 9) == _WHITE  # separation from the next glyph


def test_typographic_label_equivalents_and_unknown_characters_are_deterministic():
    typographic = _canvas(width=400, height=80)
    equivalent = _canvas(width=400, height=80)
    source = "Jaw—clear ≥ 6 μm; ⌀4 ‘A’\n90° ± 1° 🛠"
    normalized = "Jaw--clear >= 6 um; Ø4 'A'\n90° ± 1° ?"
    typographic.text(0, 0, source, scale=2)
    equivalent.text(0, 0, normalized, scale=2)
    assert typographic.rgb == equivalent.rgb
    assert typographic.text_width(source, scale=2) == equivalent.text_width(normalized, scale=2)
    assert typographic.text_width("", scale=2) == 0
    assert typographic.text_width("A\nABC", scale=2) == typographic.text_width("ABC", scale=2)


@pytest.mark.parametrize("failure", ["clipping", "overlap"])
def test_setup_png_refuses_unreadable_annotations(failure):
    spec = {
        "setup_id": "S1",
        "view": "lathe",
        "stock_box": [-1, -1, -1, 1, 1, 1],
        "zero_mm": [0, 0, 0],
        "jaw_front_z_mm": -1,
        "stickout_mm": 2,
        "datums": [{"label": "END", "point_mm": [0, 0, 1]}],
    }
    width, height, _ = _decode_png(render_diagram([], spec)[0])
    assert (width, height) == (1600, 1000)
    if failure == "clipping":
        spec["setup_id"] = "LONG-NAME-" * 30
    else:
        spec["datums"] = [{"label": f"DATUM {index}", "point_mm": [0, 0, 1]} for index in range(80)]
    with pytest.raises(ValueError):
        render_diagram([], spec)


@pytest.mark.parametrize("position", [(10, 10), (30, 10), (10, 20)])
def test_text_layout_rejects_overlap_and_insufficient_clearance(position):
    canvas = _canvas()
    canvas.text(10, 10, "badge", scale=1)
    canvas.text(*position, "axis", scale=1)
    # Generic canvas callers can still draw and encode unchecked annotations.
    encoded = canvas.png()
    with pytest.raises(ValueError):
        canvas.assert_text_layout()
    assert canvas.png() == encoded


@pytest.mark.parametrize("position", [(7, 8), (8, 7), (64, 8), (8, 66)])
def test_text_layout_rejects_labels_outside_any_inset_canvas_edge(position):
    canvas = _canvas(width=100, height=80)
    canvas.text(*position, "footer", scale=1)
    with pytest.raises(ValueError):
        canvas.assert_text_layout()


def test_text_layout_accepts_normalized_multiline_space_and_rounding_boundaries():
    canvas = _canvas(width=76, height=84)
    canvas.assert_text_layout()
    canvas.text(-4.5, 8.5, " A B\u0378  \n C \n   \n D ", scale=2)
    canvas.text(58.5, 8.5, "E", scale=2)
    canvas.text(-100, -100, "  \n", scale=2)
    assert canvas.text_boxes == [
        ("A B?", 8, 8, 54, 22),
        ("C", 8, 26, 18, 40),
        ("D", 8, 62, 18, 76),
        ("E", 58, 8, 68, 22),
    ]
    encoded = canvas.png()
    canvas.assert_text_layout()
    assert canvas.png() == encoded
    with pytest.raises(ValueError):
        canvas.assert_text_layout(min_gap=5)
    with pytest.raises(ValueError):
        canvas.assert_text_layout(margin=9)


def test_annotation_primitives_are_clipped_and_overlays_are_not_depth_tested():
    canvas = _canvas((_square(10, (100, 140, 190)),), width=160, height=160)
    red, green, blue = (200, 30, 20), (20, 160, 40), (30, 50, 210)
    canvas.rect(-20, -20, 40, 40, red)
    canvas.polygon(((30, 30), (80, 30), (80, 45), (45, 45), (45, 80), (30, 80)), green)
    assert _pixel(canvas, 0, 0) == red
    assert _pixel(canvas, 35, 65) == green
    assert _pixel(canvas, 65, 35) == green
    assert _pixel(canvas, 65, 65) != green  # concave corner stays unfilled
    canvas.circle(110, 45, 15, fill=blue, outline=red)
    assert _pixel(canvas, 110, 45) == blue
    assert _pixel(canvas, 124, 45) == red
    assert _pixel(canvas, 126, 45) != blue
    canvas.line((-1_000_000, 100), (1_000_000, 100), red, width=4)
    assert _pixel(canvas, 0, 100) == red
    assert _pixel(canvas, 159, 100) == red
    canvas.arrow((20, 130), (100, 130), blue)
    assert _pixel(canvas, 50, 130) == blue
    assert _pixel(canvas, 89, 134) == blue  # head wider than shaft
    assert _pixel(canvas, 104, 130) != blue
    assert len(canvas.rgb) == canvas.width * canvas.height * 3


def test_dash_gaps_remain_visible_and_off_image_geometry_does_not_shift_the_pattern():
    colour = (20, 30, 40)
    canvas = _canvas(width=120, height=40)
    canvas.line((0, 10), (100, 10), colour, width=2, dashed=True)
    assert _pixel(canvas, 4, 10) == colour
    assert _pixel(canvas, 11, 10) == _WHITE
    assert _pixel(canvas, 18, 10) == colour
    clipped = _canvas(width=120, height=40)
    clipped.line((-140, 10), (100, 10), colour, width=2, dashed=True)
    assert clipped.rgb == canvas.rgb


def test_empty_and_degenerate_meshes_still_support_annotations_and_finite_projection():
    empty = _canvas()
    assert empty.project((0, 0, 0)) == (100, 100)
    point = _canvas(((((4, 5, 6),), ((0, 0, 0),), (100, 100, 100)),))
    assert point.project((4, 5, 6)) == (100, 100)
    assert math.isfinite(point.scale)
    assert point.rgb == empty.rgb
    point.text(10, 10, "Datum", scale=2)
    assert _pixel(point, 10, 10) == (30, 35, 40)
    assert _pixel(empty, 10, 10) == _WHITE


@pytest.mark.parametrize("reverse", [False, True])
def test_contour_direction_arrows_survive_subpixel_tessellation(reverse):
    colour = (35, 83, 147)
    spec = {"view": "plan", "stock_box": [0, 0, 0, 10, 10, 1]}
    fine = _Diagram([], spec)
    samples = [(300 + index / 4, 400) for index in range(1601)]
    if reverse:
        samples.reverse()
    fine._ordered_path(samples, colour, width=3)

    assert _pixel(fine.canvas, 500, 400) == colour
    # A three-pixel path cannot colour this row; visible arrowhead wings can.
    assert any(_pixel(fine.canvas, x, 404) == colour for x in range(300, 700))


def test_stickout_dimension_starts_at_the_jaw_front_marker_not_the_stock_end():
    spec = {
        "setup_id": "S1",
        "view": "lathe",
        "stock_box": [-10, -10, -60, 10, 10, 40],
        "jaw_front_z_mm": -40,
        "stickout_mm": 80,
    }
    diagram = _Diagram([], spec)
    diagram.render()

    start, end = diagram.dimensions["STICKOUT 80 mm"]
    assert start[0] == pytest.approx(diagram.jaw_marker[0])
    assert end[0] == pytest.approx(diagram.canvas.project((0, 0, 40))[0])
    # The stock length runs from the bar's buried end, a different extension line.
    assert diagram.dimensions["STOCK Z 100 mm"][0][0] < start[0] - 10


def test_a_stickout_from_a_fit_up_is_labelled_nominal_with_its_setting():
    spec = {
        "setup_id": "S1",
        "view": "lathe",
        "stock_box": [-10, -10, -60, 10, 10, 40],
        "jaw_front_z_mm": -40,
        "stickout_mm": 80,
        "stickout_add_mm": 8,
    }
    diagram = _Diagram([], spec)
    diagram.render()
    assert "NOMINAL STICKOUT 80 mm (SET = MEASURED + 8)" in diagram.dimensions
    assert not any(label.startswith("STICKOUT") for label in diagram.dimensions)


@pytest.mark.parametrize(("round_dia", "printed"), [(20, "STOCK DIA 20 MM"), (None, "STOCK BOX")])
def test_round_stock_prints_its_diameter_not_a_bounding_box(round_dia, printed):
    spec = {"setup_id": "S1", "view": "lathe", "stock_box": [-10, -10, -60, 10, 10, 40]}
    if round_dia is not None:
        spec["stock_round_dia_mm"] = round_dia
    diagram = _Diagram([], spec)
    diagram.render()
    texts = [box[0] for box in diagram.canvas.text_boxes]
    assert any(text.startswith(printed) for text in texts), texts
    # Round stock: the box would only repeat the length the stock dimension already gives.
    assert any(text.startswith("STOCK BOX") for text in texts) is (round_dia is None)
    assert "STOCK Z 100 mm" in diagram.dimensions


def test_arc_apex_below_its_ends_keys_below_and_no_leader_grazes_another_point():
    diagram = _Diagram([], {"view": "plan", "stock_box": [0, 0, 0, 10, 10, 1]})
    # A semicircle sagging below its ends, keyed end, apex, end as the table lists it.
    left, apex, right = (420, 300), (500, 330), (580, 300)
    waypoints = [{"label": "P1", "xy": left}, {"label": "P2", "xy": apex}]
    waypoints.append({"label": "P3", "xy": right})

    diagram._waypoint_badges(waypoints, lambda point: point, (360, 200, 640, 480), perimeter=True)

    # Badge centres as printed (the label text is centred in its badge).
    badges = {
        text: ((x0 + x1) / 2, (y0 + y1) / 2)
        for text, x0, y0, x1, y1 in diagram.canvas.text_boxes
        if text in ("P1", "P2", "P3")
    }
    points = {"P1": left, "P2": apex, "P3": right}
    assert badges["P2"][1] > apex[1]
    assert badges["P1"][1] < left[1] and badges["P3"][1] < right[1]
    for label, badge in badges.items():
        others = [point for other, point in points.items() if other != label]
        assert all(_leader_clearance(other, points[label], badge) >= 9 for other in others)


def _leader_clearance(point, a, b):
    dx, dy = b[0] - a[0], b[1] - a[1]
    t = ((point[0] - a[0]) * dx + (point[1] - a[1]) * dy) / (dx * dx + dy * dy)
    t = min(1.0, max(0.0, t))
    return math.dist(point, (a[0] + t * dx, a[1] + t * dy))


_SPECS = Path(__file__).resolve().parent / "data" / "render"


def _example_spec(name):
    """A setup picture spec the kernel built for a shipped example setup (meshes omitted)."""
    return json.loads((_SPECS / f"{name}.json").read_text(encoding="utf-8"))


def _segments_cross(a, b, c, d):
    def orient(p, q, r):
        return (q[0] - p[0]) * (r[1] - p[1]) - (q[1] - p[1]) * (r[0] - p[0])

    return orient(a, b, c) * orient(a, b, d) < 0 and orient(c, d, a) * orient(c, d, b) < 0


def test_text_layout_rejects_type_below_the_minimum_print_scale():
    canvas = _canvas(width=200, height=60)
    canvas.text(10, 10, "SOUTH END", scale=2)
    canvas.assert_text_layout()
    with pytest.raises(ValueError):
        canvas.assert_text_layout(min_scale=3)


@pytest.mark.parametrize("name", ["shaft-s1", "cone-s1", "rocker-s3", "rocker-s4"])
def test_dense_setup_pictures_print_every_label_at_body_size(name):
    # Letter print: scale 3 (21 px) is about 7 pt cap height; scale 2 is under 5 pt.
    diagram = _Diagram([], _example_spec(name))
    diagram.render()

    assert [box for box in diagram.canvas.text_boxes if box[4] - box[2] < 21] == []


def test_a_panel_with_many_point_keys_gets_the_height_to_print_them_apart():
    # Rocker S1: seven operation panels; op 40 alone keys seven profile points (P3-P9).
    diagram = _Diagram([], _example_spec("rocker-s1"))
    diagram.render()
    keys = [box for box in diagram.canvas.text_boxes if re.fullmatch(r"P\d+|PASS \d+", box[0])]
    assert {box[0] for box in keys} >= {f"P{number}" for number in range(1, 13)}
    for index, (label, x0, y0, x1, y1) in enumerate(keys):
        for other, a0, b0, a1, b1 in keys[index + 1 :]:
            apart = x1 + 4 <= a0 or a1 + 4 <= x0 or y1 + 4 <= b0 or b1 + 4 <= y0
            assert apart, (label, other)


@pytest.mark.parametrize("keys", [("P1",), ("P2", "P3"), ("P1", "P2", "P3")])
def test_lathe_point_keys_that_would_crowd_get_an_enlarged_detail_with_keys_apart(keys):
    # Shaft S2's jaw-end dome: P2 and P3 are about 1 mm apart, under 20 px at the window's
    # scale, so their keys cannot both sit beside them; a lone key never crowds.
    spec = _example_spec("shaft-s2")
    spec["waypoints"] = [point for point in spec["waypoints"] if point["label"] in keys]
    diagram = _Diagram([], spec)
    diagram.render()

    details = [box[0] for box in diagram.canvas.text_boxes if box[0].startswith("DETAIL")]
    if keys == ("P1",):
        assert details == []
        return
    (detail,) = details
    assert float(detail.split("X")[1]) >= 2
    badges = {box[0]: box[1:] for box in diagram.canvas.text_boxes if box[0] in keys}
    points = {label: path[0] for label, path in diagram.leaders if label in keys}
    assert badges.keys() == points.keys() == set(keys)
    for label, (x0, y0, x1, y1) in badges.items():
        # No key covers a point, and no leader passes next to another point.
        for other, point in points.items():
            assert not (x0 - 4 <= point[0] <= x1 + 4 and y0 - 4 <= point[1] <= y1 + 4)
            if other != label:
                badge = ((x0 + x1) / 2, (y0 + y1) / 2)
                assert _leader_clearance(point, points[label], badge) >= 9, (label, other)
    for label, (x0, y0, x1, y1) in badges.items():
        for other, (a0, b0, a1, b1) in badges.items():
            if other != label:
                assert x1 + 4 <= a0 or a1 + 4 <= x0 or y1 + 4 <= b0 or b1 + 4 <= y0
    # Every printed label still keeps the print size and clearance rules.
    diagram.canvas.assert_text_layout(min_scale=3)


@pytest.mark.parametrize("name", ["shaft-s1", "cone-s1"])
def test_bar_end_labels_key_their_own_end_and_never_lead_along_the_axis_past_another_point(name):
    spec = _example_spec(name)
    diagram = _Diagram([], spec)
    diagram.render()
    project = diagram.canvas.project
    anchors = [project(datum["point_mm"]) for datum in spec["datums"]]
    anchors.append(project(spec["zero_mm"]))

    ends = [datum for datum in spec["datums"] if datum.get("kind") == "end"]
    assert len(ends) == 2
    for datum in ends:
        point, label = project(datum["point_mm"]), datum["label"].upper()
        (box,) = [box for box in diagram.canvas.text_boxes if box[0] == label]
        # The chuck-side end is keyed in the left lane, the exposed end in the right one.
        assert (box[1] < 590) == (point[0] < 590), label
    for datum in ends:
        point, label = project(datum["point_mm"]), datum["label"].upper()
        (path,) = [path for leader, path in diagram.leaders if leader == label]
        assert path[0] == point
        for a, b in zip(path, path[1:], strict=False):
            if abs(a[1] - b[1]) > 1e-6:
                continue
            for other in anchors:
                if math.dist(other, point) > 1 and min(a[0], b[0]) < other[0] < max(a[0], b[0]):
                    assert abs(other[1] - a[1]) >= 6, (label, other)


@pytest.mark.parametrize("name", ["rocker-s3", "rocker-s4"])
def test_plan_view_pad_and_clamp_badges_have_separate_uncrossed_leaders(name):
    # Twelve pads under a thin strap plus straps, a pivot screw and a clocking pin.
    spec = _example_spec(name)
    diagram = _Diagram([], spec)
    diagram.render()
    targets, keyed = {}, {"SUPPORT PADS"}
    for component in spec["components"]:
        label = component["label"].upper()
        code = component.get("code") or (
            label.removeprefix("PAD ") if component["role"] == "pad" else None
        )
        if code:
            targets[code] = diagram.canvas.project(component["center_mm"])
        if component.get("code"):
            keyed.add(label)
    badges = {
        text: ((x0 + x1) / 2, (y0 + y1) / 2)
        for text, x0, y0, x1, y1 in diagram.canvas.text_boxes
        if text in targets
    }
    assert badges.keys() == targets.keys()

    leaders = [(code, point, badges[code]) for code, point in targets.items()]
    for index, (code, point, badge) in enumerate(leaders):
        for other, other_point, other_badge in leaders[index + 1 :]:
            assert not _segments_cross(point, badge, other_point, other_badge), (code, other)
        for other, other_point, _ in leaders:
            if other != code:
                assert _leader_clearance(other_point, point, badge) >= 6, (code, other)
    # A keyed group's lane entry names it without another leader into the badged points.
    assert [label for label, _ in diagram.leaders if label in keyed] == []


@pytest.mark.parametrize("keep_out", [None, [], [{"at": [5, 5], "dia_mm": 2}]])
@pytest.mark.parametrize("axis", ["x", "y"])
def test_raster_keep_out_draws_independent_segments_without_filling_clearance(keep_out, axis):
    split = bool(keep_out)
    segments = [
        [[0, 0], [10, 0]],
        *([[[0, 5], [4, 5]], [[6, 5], [10, 5]]] if split else [[[0, 5], [10, 5]]]),
        [[10, 10], [0, 10]],
    ]
    if axis == "y":
        segments = [[[y, x] for x, y in segment] for segment in segments]
    profile = {"op": "clear", "cutter_centre": segments, "raster": {}}
    if keep_out is not None:
        profile["raster"]["keep_out"] = keep_out
    paths, waypoints = contour_annotations({"profiles": [profile]}, 25.4, "S1")
    diagram = _Diagram([], {"view": "plan", "stock_box": [0, 0, 0, 254, 254, 1]})
    colour = (35, 83, 147)

    def project(point):
        x, y = point if axis == "x" else point[::-1]
        return 400 + x / 25.4 * 60, 600 - y / 25.4 * 40

    labels = []
    assert diagram._raster_band(paths, project, colour, labels) == []
    assert waypoints == []
    if split:
        # Both middle pieces must be ink, not the band's faint tint. The island
        # and space between stepover positions must remain completely unswept.
        assert _pixel(diagram.canvas, 520, 400) == colour
        assert _pixel(diagram.canvas, 880, 400) == colour
        assert _pixel(diagram.canvas, 700, 400) == _WHITE
        assert _pixel(diagram.canvas, 520, 500) == _WHITE
    else:
        tint = tuple(int(255 - (255 - channel) * 0.22) for channel in colour)
        assert _pixel(diagram.canvas, 520, 400) == tint
        assert _pixel(diagram.canvas, 700, 400) == tint
        assert _pixel(diagram.canvas, 520, 500) == tint
    assert _pixel(diagram.canvas, 520, 600) == colour
    assert _pixel(diagram.canvas, 520, 200) == colour
    assert [label["label"] for label in labels] == ["PASS 1", f"PASS {len(segments)}"]
    assert project(labels[0]["xy"]) == pytest.approx((700, 600))
    assert project(labels[-1]["xy"]) == pytest.approx((700, 200))
    # Decode the direct renderer's output too: the tested surface is the actual
    # printable PNG payload, not a recording or mocked drawing collaborator.
    _, _, pixels = _decode_png(diagram.canvas.png())
    assert pixels == diagram.canvas.rgb


def _slab(x0, y0, x1, y1, z, colour, tag):
    """A flat plan-view rectangle at height ``z``: the visible top of a tagged solid."""
    points = ((x0, y0, z), (x1, y0, z), (x1, y1, z), (x0, y1, z))
    return (points, ((0, 1, 2), (0, 2, 3)), colour, False, tag)


def _leader_start(diagram, label):
    (path,) = [path for leader, path in diagram.leaders if leader == label]
    return path[0]


def _inside(diagram, point, box):
    """Whether a pixel point lies inside a plan-view XY rectangle's projection."""
    left, top = diagram.canvas.project((box[0], box[3], 0))
    right, bottom = diagram.canvas.project((box[2], box[1], 0))
    return left < point[0] < right and top < point[1] < bottom


@pytest.mark.parametrize(
    "case",
    ["box_top_in_air", "box_top_under_a_jaw"],
)
def test_stock_leader_ends_on_the_drawn_stock_not_its_bounding_box(case):
    # The stock box's top edge is air beside a section, or a jaw stands over it.
    stock = (0, 0, 10, 10)
    meshes = [_slab(*stock, 1, (160, 175, 185), "part")]
    box = [0, 0, 0, 10, 10, 1]
    jaw = (-2, 7, 12, 12)
    if case == "box_top_in_air":
        box = [0, 0, 0, 10, 20, 1]
    else:
        meshes.append(_slab(*jaw, 5, (120, 98, 76), "moving_jaw"))
    spec = {"setup_id": "S1", "view": "plan", "stock_box": box}
    diagram = _Diagram(meshes, spec)
    diagram.render()

    start = _leader_start(diagram, "STOCK")
    assert _inside(diagram, start, stock)
    if case == "box_top_under_a_jaw":
        assert not _inside(diagram, start, jaw)
    assert diagram.render_debts == []


def test_a_named_solid_hidden_from_view_is_a_render_debt_not_a_leader():
    # Plan view from +Z: the parallel lies wholly under the stock, so no pixel shows it.
    meshes = [
        _slab(0, 0, 10, 10, 2, (160, 175, 185), "part"),
        _slab(2, 2, 8, 8, 1, (120, 98, 76), "parallel_1"),
    ]
    spec = {
        "setup_id": "S1",
        "view": "plan",
        "stock_box": [0, 0, 0, 10, 10, 2],
        "components": [
            {
                "name": "parallel_1",
                "role": "parallel",
                "box_mm": [2, 2, 0, 8, 8, 1],
                "center_mm": [5, 5, 0.5],
                "meshes": ["parallel_1"],
            }
        ],
    }
    png, debts = render_diagram(meshes, spec)

    assert debts == ["NOT SHOWN: PARALLELS is hidden in this view, so it has no leader."]
    diagram = _Diagram(meshes, {**spec, "notes": debts})
    diagram.render()
    assert [label for label, _ in diagram.leaders if label == "PARALLELS"] == []
    # The debt is printed in the picture's own notes, and the picture is the one returned.
    assert png == diagram.canvas.png()
    # Moved out from under the stock, the same parallel is drawn and keeps its leader.
    meshes[1] = _slab(12, 2, 18, 8, 1, (120, 98, 76), "parallel_1")
    spec["components"][0].update(box_mm=[12, 2, 0, 18, 8, 1], center_mm=[15, 5, 0.5])
    spec["stock_box"] = [0, 0, 0, 18, 10, 2]
    _, debts = render_diagram(meshes, spec)
    assert debts == []


def test_a_solid_wholly_behind_another_shows_no_pixel_through_its_triangle_seams():
    # The front square's two triangles share a 45° diagonal that crosses every pixel row
    # exactly at a pixel centre, at whatever scale the square is fitted to. The face
    # behind it must not show through along that seam at any of those scales.
    square = ((0, 1, 2), (0, 2, 3))
    front = ((0, 0, 2), (10, 0, 2), (10, 10, 2), (0, 10, 2))
    back = ((2, 2, 1), (8, 2, 1), (8, 8, 1), (2, 8, 1))
    meshes = [
        (front, square, (160, 175, 185), False, "front"),
        (back, square, (120, 98, 76), False, "back"),
    ]
    for size in range(20, 202, 2):
        canvas = _canvas(meshes, width=size, height=size)
        seen = {canvas.tags[index] for index in canvas.owner if index >= 0}
        assert seen == {"front"}, size


@pytest.mark.parametrize("kind", ["coded_clamp", "pad"])
@pytest.mark.parametrize("hidden", [True, False], ids=["under_the_work", "beside_the_work"])
def test_a_numbered_position_badge_never_leads_to_the_solid_in_front_of_it(kind, hidden):
    # Plan view from +Z: a clamp declared as C1, or support pad 1, wholly under the stock
    # or beside it.
    box = [2, 2, 0, 8, 8, 1] if hidden else [12, 2, 0, 18, 8, 1]
    tag = "fx:clamp" if kind == "coded_clamp" else "fx:pad-1"
    meshes = [
        _slab(0, 0, 10, 10, 2, (160, 175, 185), "part"),
        _slab(box[0], box[1], box[3], box[4], 1, (120, 98, 76), tag),
    ]
    component = {
        "name": tag,
        "box_mm": box,
        "center_mm": [(box[i] + box[i + 3]) / 2 for i in range(3)],
        "meshes": [tag],
    }
    if kind == "coded_clamp":
        component.update(label="C1: TOE CLAMP", role="clamp", code="C1")
    else:
        component.update(label="PAD 1", role="pad")
    badge = "C1" if kind == "coded_clamp" else "1"
    spec = {
        "setup_id": "S1",
        "view": "plan",
        "stock_box": [0, 0, 0, 10, 10, 2],
        "components": [component],
    }
    diagram = _Diagram(meshes, spec)
    diagram.render()

    assert diagram.render_debts == []
    # A badge leader drawn to a solid ends on that solid's own pixels, never the stock's.
    ends = [_tag_at(diagram.canvas, *path[0]) for label, path in diagram.leaders if label == badge]
    if not hidden:
        assert ends == [tag]
        return
    assert ends == []
    # Hidden, its position is a dashed outline of its box, and the badge's leader stops
    # on that outline at an open ring.
    (path,) = [path for label, path in diagram.hidden_leaders if label == badge]
    left, top = diagram.canvas.project((box[0], box[4], 0))
    right, bottom = diagram.canvas.project((box[3], box[1], 0))
    x, y = path[0]
    assert left - 1 <= x <= right + 1 and top - 1 <= y <= bottom + 1
    assert min(abs(x - left), abs(x - right), abs(y - top), abs(y - bottom)) < 1
    assert _pixel(diagram.canvas, math.floor(x), math.floor(y)) == _WHITE
    far_edge = bottom if abs(y - top) < abs(y - bottom) else top
    inked = {
        _pixel(diagram.canvas, column, math.floor(far_edge))
        for column in range(math.ceil(left), math.floor(right))
    }
    assert (120, 98, 76) in inked


@pytest.mark.parametrize("hidden", [True, False], ids=["behind_the_work", "beside_the_work"])
def test_a_vise_jaw_hidden_by_the_work_is_a_dashed_outline_with_its_leader_not_a_debt(hidden):
    # Plan view from +Z: a bar standing taller than its jaws hides the jaw behind it, as a
    # tall bar held on edge hides the rear jaw from the isometric camera. The jaw is the
    # face the work seats on, so its position is still drawn.
    box = [2, 2, 0, 8, 8, 1] if hidden else [12, 2, 0, 18, 8, 1]
    meshes = [
        _slab(0, 0, 10, 10, 2, (160, 175, 185), "part"),
        _slab(box[0], box[1], box[3], box[4], 1, (120, 98, 76), "fixed_jaw"),
    ]
    spec = {
        "setup_id": "S1",
        "view": "plan",
        "stock_box": [0, 0, 0, 10, 10, 2],
        "components": [
            {
                "name": "fixed_jaw",
                "role": "fixed_jaw",
                "box_mm": box,
                "center_mm": [(box[i] + box[i + 3]) / 2 for i in range(3)],
                "meshes": ["fixed_jaw"],
            }
        ],
    }
    diagram = _Diagram(meshes, spec)
    diagram.render()

    assert diagram.render_debts == []
    seen = [path for label, path in diagram.leaders if label == "FIXED JAW"]
    if not hidden:
        assert [_tag_at(diagram.canvas, *path[0]) for path in seen] == ["fixed_jaw"]
        return
    assert seen == []
    # Its leader stops at an open ring on the dashed outline of its box, never on the
    # work in front of it.
    (path,) = [path for label, path in diagram.hidden_leaders if label == "FIXED JAW"]
    left, top = diagram.canvas.project((box[0], box[4], 0))
    right, bottom = diagram.canvas.project((box[3], box[1], 0))
    x, y = path[0]
    assert left - 1 <= x <= right + 1 and top - 1 <= y <= bottom + 1
    assert min(abs(x - left), abs(x - right), abs(y - top), abs(y - bottom)) < 1
    assert _pixel(diagram.canvas, math.floor(x), math.floor(y)) == _WHITE


def _block(box, colour, tag):
    """A tagged box solid: its six faces as twelve triangles."""
    x0, y0, z0, x1, y1, z1 = box
    points = [(x, y, z) for x in (x0, x1) for y in (y0, y1) for z in (z0, z1)]
    faces = ((0, 1, 3, 2), (4, 6, 7, 5), (0, 4, 5, 1), (2, 3, 7, 6), (0, 2, 6, 4), (1, 5, 7, 3))
    triangles = [t for a, b, c, d in faces for t in ((a, b, c), (a, c, d))]
    return (points, triangles, colour, False, tag)


@pytest.mark.parametrize("pressing", [True, False], ids=["through_a_round_bar", "nothing_between"])
def test_a_moving_jaw_pressing_the_work_through_a_round_bar_keeps_its_leader(pressing):
    # Isometric: the bar on edge seats on the fixed jaw; a round bar between it and the
    # moving jaw holds the moving jaw 6 mm off the work. Without the bar the jaw stands
    # off alone and is not holding.
    stock = [0, 0, 0, 100, 20, 60]
    boxes = {
        "fixed_jaw": [10, 20, 0, 90, 38, 40],
        "moving_jaw": [10, -24, 0, 90, -6, 40],
    }
    if pressing:
        boxes["jaw_bar"] = [12, -6, 17, 88, 0, 23]
    meshes = [_block(stock, (160, 175, 185), "part")]
    meshes += [_block(box, (120, 98, 76), name) for name, box in boxes.items()]
    labels = {"fixed_jaw": "FIXED JAW", "moving_jaw": "MOVING JAW", "jaw_bar": "ROUND BAR"}
    spec = {
        "setup_id": "P2",
        "view": "isometric",
        "stock_box": stock,
        "components": [
            {
                "name": name,
                "label": labels[name],
                "role": name,
                "box_mm": box,
                "center_mm": [(box[i] + box[i + 3]) / 2 for i in range(3)],
                "meshes": [name],
            }
            for name, box in boxes.items()
        ],
    }
    diagram = _Diagram(meshes, spec)
    diagram.render()

    named = {label for label, _ in diagram.leaders}
    assert ("MOVING JAW" in named) is pressing
    assert ("ROUND BAR" in named) is pressing


def _vise_spec(size, touching=True):
    """Plan view of a ``size`` x ``size`` x 10 block between two 160 mm long vise jaws."""
    stock = [0, 0, 0, size, size, 10]
    jaws = {
        "fixed_jaw": [-12, -74, -20, 0, 86, 10],
        "moving_jaw": [size, -74, -20, size + 12, 86, 10],
    }
    meshes = [_block(stock, (160, 175, 185), "part")]
    meshes += [_block(box, (120, 98, 76), name) for name, box in jaws.items()]
    top = min(size, 86)
    contacts = [
        {"tag": name, "lines_mm": [[[x, 0, 0], [x, top, 0], [x, top, 10], [x, 0, 10], [x, 0, 0]]]}
        for name, x in (("fixed_jaw", 0), ("moving_jaw", size))
    ]
    components = [
        {
            "name": name,
            "role": name,
            "box_mm": box,
            "center_mm": [(box[i] + box[i + 3]) / 2 for i in range(3)],
            "meshes": [name],
        }
        for name, box in jaws.items()
    ]
    spec = {
        "setup_id": "S1",
        "view": "plan",
        "stock_box": stock,
        "zero_mm": [0, 0, 0],
        "components": components,
        "contacts": contacts if touching else [],
    }
    return meshes, spec


def _stock_short_side(canvas, box):
    points = [canvas.project(p) for p in _corners(box)]
    return min(max(p[i] for p in points) - min(p[i] for p in points) for i in (0, 1))


@pytest.mark.parametrize(
    ("size", "touching", "detailed"),
    [(12, True, True), (150, True, False), (12, False, False)],
    ids=["small_work_in_long_jaws", "work_larger_than_its_jaws", "small_work_nothing_touching"],
)
def test_small_work_in_its_holding_gets_an_enlarged_contact_detail(size, touching, detailed):
    meshes, spec = _vise_spec(size, touching)
    png, debts = render_diagram(meshes, spec)
    _, height, _ = _decode_png(png)
    main = _Diagram(meshes, spec)
    main.render()
    details = _holding_details(meshes, spec, main)

    assert debts == []
    if not detailed:
        assert details == []
        assert height == main.canvas.height
        return
    # The detail is printed below the setup picture and draws the work far larger.
    (detail,) = details
    assert height == main.canvas.height + detail.canvas.height
    drawn = _stock_short_side(main.canvas, spec["stock_box"])
    assert _stock_short_side(detail.canvas, spec["stock_box"]) >= 1.5 * drawn
    # Each jaw's contact key leads to its own outlined contact face, apart from the other.
    ends = {}
    for label, path in detail.leaders:
        x, y = (math.floor(v) for v in path[0])
        near = {_pixel(detail.canvas, x + dx, y + dy) for dx in (-3, 0, 3) for dy in (-3, 0, 3)}
        if _CONTACT in near:
            ends[label] = path[0]
    assert len(ends) == 2
    first, second = ends.values()
    assert math.dist(first, second) > 20
    detail.canvas.assert_text_layout(min_scale=3)


def test_long_thin_plan_work_gets_split_details_that_key_each_contact_height_once():
    # A 300 x 12 mm bar seen from above: its holding heights cannot show in the plan, and
    # one band across the whole length would draw the bar hardly larger than the plan.
    stock = [0, 0, 10, 300, 12, 18]
    solids = {
        "fx:hub-stand": [20, -2, 0, 40, 14, 10],
        "fx:rail-shim-lu": [250, -2, 0, 258, 4, 12],
        "fx:rail-shim-ru": [270, -2, 0, 278, 4, 12],
    }
    meshes = [_block(stock, (160, 175, 185), "part")]
    meshes += [_block(box, (120, 98, 76), tag) for tag, box in solids.items()]
    contacts = [
        {
            "tag": tag,
            "lines_mm": [
                [[x0, y0, z1], [x1, y0, z1], [x1, min(y1, 12), z1], [x0, min(y1, 12), z1]]
            ],
        }
        for tag, (x0, y0, _, x1, y1, z1) in solids.items()
    ]
    spec = {
        "setup_id": "S3",
        "view": "plan",
        "stock_box": stock,
        "zero_mm": [0, 0, 0],
        "components": [
            {
                "name": "body_supports",
                "role": "fixture",
                "box_mm": [20, -2, 0, 278, 14, 12],
                "center_mm": [149, 6, 6],
                "meshes": list(solids),
            }
        ],
        "contacts": contacts,
    }
    main = _Diagram(meshes, spec)
    main.render()
    details = _holding_details(meshes, spec, main)

    assert len(details) == 2
    drawn = _stock_short_side(main.canvas, stock)
    keyed = []
    for detail in details:
        assert _stock_short_side(detail.canvas, stock) >= 1.5 * drawn
        keyed.append(sorted(c.label for c in detail.callouts if c.colour == _CONTACT))
        detail.canvas.assert_text_layout(min_scale=3)
    # One support on two planes: each plane is keyed with its own height, in the band
    # that holds it, exactly once.
    (near,), (far,) = keyed
    assert near.endswith("AT Z 10")
    assert far.endswith("AT Z 12")
    _, height, _ = _decode_png(render_diagram(meshes, spec)[0])
    assert height == main.canvas.height + sum(d.canvas.height for d in details)


@pytest.mark.parametrize(
    ("heights", "keys"),
    [
        ((10, 12), ["RAIL SHIM LU CONTACT AT Z 10", "RAIL SHIM RU CONTACT AT Z 12"]),
        ((12, 12), ["BODY SUPPORTS CONTACT AT Z 12"]),
    ],
    ids=["stepped_work_on_two_heights", "flat_work_on_one_height"],
)
def test_one_named_family_in_one_band_is_keyed_once_per_contact_height(heights, keys):
    # Both rail shims touch the work within one detail band. A stepped underside sets
    # them at two heights, and each height is what the operator sets that shim to; on
    # flat work the whole support shares one plane and is keyed once.
    left, right = heights
    solids = {
        "fx:rail-shim-lu": [20, -2, 0, 28, 4, left],
        "fx:rail-shim-ru": [40, -2, 0, 48, 4, right],
    }
    stock = [0, 0, min(heights), 100, 12, 18]
    meshes = [
        _block([0, 0, left, 35, 12, 18], (160, 175, 185), "part"),
        _block([35, 0, right, 100, 12, 18], (160, 175, 185), "part"),
    ]
    meshes += [_block(box, (120, 98, 76), tag) for tag, box in solids.items()]
    contacts = [
        {"tag": tag, "lines_mm": [[[x0, 0, z1], [x1, 0, z1], [x1, 4, z1], [x0, 4, z1]]]}
        for tag, (x0, _, _, x1, _, z1) in solids.items()
    ]
    spec = {
        "setup_id": "S3",
        "view": "plan",
        "stock_box": stock,
        "zero_mm": [0, 0, 0],
        "components": [
            {
                "name": "body_supports",
                "role": "fixture",
                "box_mm": [20, -2, 0, 48, 4, 12],
                "center_mm": [34, 1, 6],
                "meshes": list(solids),
            }
        ],
        "contacts": contacts,
    }
    main = _Diagram(meshes, spec)
    main.render()
    details = _holding_details(meshes, spec, main)

    keyed = [[c.label for c in d.callouts if c.colour == _CONTACT] for d in details]
    assert [sorted(band) for band in keyed if band] == [keys]


@pytest.mark.parametrize(("normal", "hidden"), [((0, 0, -1), True), ((0, 0, 1), False)])
def test_a_datum_face_turned_away_from_the_view_is_marked_hidden_not_drawn_in_front(normal, hidden):
    # Isometric from +Z: a datum on the block's underside cannot be the face in front.
    z = 0 if hidden else 10
    outline = [[0, 0, z], [20, 0, z], [20, 20, z], [0, 20, z], [0, 0, z]]
    spec = {
        "setup_id": "S2",
        "view": "isometric",
        "stock_box": [0, 0, 0, 20, 20, 10],
        "datums": [
            {
                "label": "B: strap face",
                "point_mm": [10, 10, z],
                "normal": list(normal),
                "outline_mm": [outline],
            },
        ],
    }
    diagram = _Diagram([_block(spec["stock_box"], (160, 175, 185), "part")], spec)
    diagram.render()

    (label,) = [label for label, _ in diagram.leaders if label.startswith("DATUM B")]
    x, y = (math.floor(v) for v in diagram.canvas.project([10, 10, z]))
    # The marker's top: a hidden face's dashed diamond reaches it; a seen face's ring not.
    marker_top = _pixel(diagram.canvas, x, y - 9)
    if hidden:
        assert "UNDERSIDE" in label and "HIDDEN" in label
        assert marker_top == (30, 35, 40)
        # The hidden face's edges are drawn dashed over the block.
        edge = [diagram.canvas.project([t, 0, 0]) for t in range(2, 19)]
        inked = [_pixel(diagram.canvas, math.floor(px), math.floor(py)) for px, py in edge]
        assert (30, 35, 40) in inked
    else:
        assert "HIDDEN" not in label and "UNDERSIDE" not in label
        assert marker_top != (30, 35, 40)
