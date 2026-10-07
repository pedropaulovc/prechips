"""Consumer-visible raster, camera, visibility and print-label contracts; no FreeCAD."""

import json
import math
import re
import struct
import zlib
from pathlib import Path

import pytest

import prechips.kernel.render_diagram as render_module
from prechips.kernel.render_diagram import (
    _CONTACT,
    _corners,
    _Diagram,
    _guide_view,
    _holding_details,
    _main_diagram,
    _solid_name,
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


def test_setup_png_refuses_clipped_annotations():
    # A title wider than the canvas cannot print; the renderer refuses it.
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
    spec["setup_id"] = "LONG-NAME-" * 30
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
    # The dimension is the nominal; the setting rule goes to the wrapping notes, so a
    # short stickout's dimension label never runs into the lane labels.
    assert "NOM STICKOUT 80 mm" in diagram.dimensions
    assert not any(label.startswith("STICKOUT") for label in diagram.dimensions)
    text = " ".join(box[0] for box in diagram.canvas.text_boxes)
    assert "STICKOUT 80 MM IS NOMINAL: SET IT AS THE MEASURED FIT-UP + 8 MM." in text, text


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
    diagram, _ = _main_diagram([], _example_spec(name))

    assert [box for box in diagram.canvas.text_boxes if box[4] - box[2] < 21] == []


def test_a_panel_with_many_point_keys_gets_the_height_to_print_them_apart():
    # Rocker S1: seven operation panels; op 40 alone keys seven profile points (P3-P9).
    # The picture grows until every panel's keys print apart.
    diagram, _ = _main_diagram([], _example_spec("rocker-s1"))
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
    diagram, _ = _main_diagram([], spec)
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
        # Three passes: each is drawn in ink over the band; between them is the tint.
        tint = tuple(int(255 - (255 - channel) * 0.22) for channel in colour)
        assert _pixel(diagram.canvas, 520, 400) == colour
        assert _pixel(diagram.canvas, 520, 500) == tint
    assert _pixel(diagram.canvas, 520, 600) == colour
    assert _pixel(diagram.canvas, 520, 200) == colour
    # A few passes are each labelled with the table's pass number.
    assert [label["label"] for label in labels] == [
        f"PASS {n}" for n in range(1, len(segments) + 1)
    ]
    # Each key leads to a point inside its own pass.
    for label, level in ((labels[0], 600), (labels[-1], 200)):
        x, y = project(label["xy"])
        assert y == pytest.approx(level) and 400 < x < 1000, label
    # Decode the direct renderer's output too: the tested surface is the actual
    # printable PNG payload, not a recording or mocked drawing collaborator.
    _, _, pixels = _decode_png(diagram.canvas.png())
    assert pixels == diagram.canvas.rgb


@pytest.mark.parametrize("order", ["climb", "unknown"])
def test_a_raster_sketch_draws_every_pass_and_claims_arrows_only_when_drawn(order):
    """The cone's S11 sketch: six passes, every one drawn and labelled as the pass table
    numbers them, each with its cutting direction when the table gives one; the legend
    names arrows only when arrows are drawn. A known one-way cycle dashes each lift and
    rapid back to the next pass's start, so a return never reads as a cut."""
    segments = [[[0, y], [40, y]] for y in range(0, 12, 2)]
    profile = {"op": "40", "cutter_centre": segments, "raster": {}, "cut_order": order}
    paths, waypoints = contour_annotations({"profiles": [profile]}, 1.0, "S1")
    spec = {"view": "plan", "stock_box": [0, 0, 0, 40, 10, 5], "paths": paths}
    diagram = _Diagram([], {**spec, "waypoints": waypoints})
    diagram._path_inset(40, 760, 100, 900)
    texts = [box[0] for box in diagram.canvas.text_boxes]
    assert [f"PASS {n}" for n in range(1, 7)] == [t for t in texts if t.startswith("PASS")]
    assert (diagram.arrows_drawn >= 6) is (order == "climb")
    assert ("ARROWS: POINT ORDER" in texts) is (order == "climb")
    assert diagram.returns_drawn == (5 if order == "climb" else 0)
    assert ("DASHED: LIFTED RETURN" in texts) is (order == "climb")
    diagram.canvas.assert_text_layout(min_scale=3)


# The sketch's operation colours (``_operation_panels``) and their raster band tint.
_SKETCH_INK = {(35, 83, 147), (24, 91, 58), (172, 111, 16), (113, 65, 137)}
_SKETCH_INK |= {tuple(int(255 - (255 - c) * 0.22) for c in ink) for ink in _SKETCH_INK}


@pytest.mark.parametrize("case", ["one_raster", "rocker_s1_panels"])
def test_profile_sketch_keys_sit_beside_the_paths_never_over_them(case, monkeypatch):
    # Rocker P1: seven passes along a thin strap, every one keyed; rocker S1: eight
    # operation panels, each keying its rasters' first and last pass or its points. A key
    # printed over the path hides the path it names: each sits clear of every pass, arrow
    # and band, with a leader to its point.
    if case == "one_raster":
        segments = [[[0, y], [340, y]] for y in range(0, 14, 2)]
        profile = {"op": "10", "cutter_centre": segments, "raster": {}, "cut_order": "climb"}
        paths, waypoints = contour_annotations({"profiles": [profile]}, 1.0, "S1")
        spec = {
            "setup_id": "P1",
            "view": "plan",
            "stock_box": [0, -26, 0, 340, 39, 16],
            "paths": paths,
            "waypoints": waypoints,
        }
    else:
        spec = _example_spec("rocker-s1")
    keyed, _ = _main_diagram([], spec)
    keys = [box for box in keyed.canvas.text_boxes if re.fullmatch(r"P\d+|PASS \d+", box[0])]
    assert len(keys) >= 7
    # The same picture without the keys' boxes: what each box would have covered.
    monkeypatch.setattr(render_module, "_badge", lambda *args, **kwargs: None)
    bare, _ = _main_diagram([], spec)
    assert bare.canvas.height == keyed.canvas.height
    for label, x0, y0, x1, y1 in keys:
        covered = {
            _pixel(bare.canvas, x, y)
            for y in range(math.floor(y0) - 4, math.ceil(y1) + 4)
            for x in range(math.floor(x0) - 4, math.ceil(x1) + 4)
        }
        assert not covered & _SKETCH_INK, label
    keyed.canvas.assert_text_layout(min_scale=3)


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


@pytest.mark.parametrize(
    ("decimals", "cut", "plane"), [(3, "6.655", "12.000"), (4, "6.6547", "12.0000")]
)
def test_picture_coordinates_and_clearances_print_as_the_setup_tables_print_them(
    decimals, cut, plane
):
    # The kernel measures the jaw tops 6.6547 below the cut; the setup's tables print that
    # at its DRO decimals, and so must the picture: never 6.65 beside a table's 6.655.
    meshes, spec = _vise_spec(12)
    spec["decimals"] = decimals
    spec["jaw_front_z_mm"] = -6.6547
    spec["closest_cut"] = {
        "mm": 6.6547,
        "tag": "fixed_jaw",
        "from_mm": [0, 6, 10],
        "to_mm": [0, 6, 10 - 6.6547],
    }
    main = _Diagram(meshes, spec)
    main.render()
    (detail,) = _holding_details(meshes, spec, main)
    text = " ".join(box[0] for drawn in (main, detail) for box in drawn.canvas.text_boxes)
    assert f"JAW FRONT Z -{cut} MM" in text, text
    assert f"CUT {cut} MM FROM" in text, text
    assert f"CONTACT AT X {plane}" in text, text


def _button_kit():
    """A 340 mm arm sectioned on its long side, held at its hub between two 10 mm buttons
    on a stud (clamp C1): ``(meshes, spec, solids)``."""
    stock = [0, 0, 0, 340, 40, 16]
    solids = {
        "kit:upper-button": [165, 15, 16, 175, 25, 20],
        "kit:lower-button": [165, 15, -4, 175, 25, 0],
        "kit:stud": [168, 18, -60, 172, 22, 24],
    }
    meshes = [_block(stock, (160, 175, 185), "part")]
    meshes += [_block(box, (120, 98, 76), name) for name, box in solids.items()]
    contacts = [
        {"tag": tag, "lines_mm": [[[165, 15, z], [175, 15, z], [175, 25, z], [165, 25, z]]]}
        for tag, z in (("kit:upper-button", 16), ("kit:lower-button", 0))
    ]
    spec = {
        "setup_id": "S1",
        "view": "elevation",
        "camera": [[1, 0, 0], [0, 0, 1], [0, -1, 0]],
        "stock_box": stock,
        "zero_mm": [170, 20, 16],
        "contacts": contacts,
        "components": [
            {
                "name": "clamp 1 kit",
                "label": "C1: kit",
                "role": "clamp",
                "code": "C1",
                "box_mm": [165, 15, -60, 175, 25, 24],
                "center_mm": [170, 20, -18],
                "meshes": list(solids),
            }
        ],
    }
    return meshes, spec, solids


def test_long_work_held_at_a_small_hub_gets_a_detail_windowed_on_its_holding():
    # A 340 mm arm sectioned on its long side, held at its hub between two 10 mm buttons
    # on a stud: framing the whole arm draws the buttons no larger, so the detail frames
    # the holding that touches the work and says which stretch of the work it shows.
    meshes, spec, solids = _button_kit()
    stock = spec["stock_box"]
    main = _Diagram(meshes, spec)
    main.render()
    (detail,) = _holding_details(meshes, spec, main)

    drawn = _stock_short_side(main.canvas, stock)
    assert _stock_short_side(detail.canvas, stock) >= 1.5 * drawn
    # Both button seats and the stud they hang on are inside the window.
    left, top, right, bottom = detail.viewport
    for box in solids.values():
        for point in _corners(box):
            x, y = detail.canvas.project(point)
            assert left <= x <= right and top <= y <= bottom, point
    text = " ".join(box[0] for box in detail.canvas.text_boxes)
    assert "SETUP X -" in text and " TO " in text, text
    assert text.count("CONTACT AT Z") == 2, text


def _guided_buttons(stops=2):
    """``_button_kit`` with the arm's hub filed down to the buttons' west rims (X 165):
    the file's stops and their rims, the nearest holding it must clear (the stud, its
    clearance keyed between the rims), and the unsectioned look along the stud axis:
    ``(meshes, spec, removal box)``."""
    meshes, spec, solids = _button_kit()
    rims = {"kit:upper-button": 16, "kit:lower-button": 0}
    spec["guide_stops"] = [
        {"tag": tag, "at_mm": [165, 20, z], "rim_mm": [[[165, 15, z], [165, 25, z]]]}
        for tag, z in rims.items()
    ][:stops]
    spec["decimals"] = 3
    spec["closest_cut"] = {
        "mm": 3.755,
        "tag": "kit:stud",
        "from_mm": [164.245, 20, 8],
        "to_mm": [168, 20, 8],
    }
    removal = [160, 0, 0, 165, 40, 16]
    removed = _block(removal, (226, 177, 60), "removal")
    spec["guide_view"] = {
        "axis_mm": [[170, 20, 0], [0, 0, 1]],
        "meshes": [
            _block([0, 0, 0, 160, 40, 16], (160, 175, 185), "part"),
            _block([165, 0, 0, 340, 40, 16], (160, 175, 185), "part"),
            (*removed[:3], True, "removal"),
        ]
        + [_block(box, (120, 98, 76), name) for name, box in solids.items()],
    }
    return meshes, spec, removal


@pytest.mark.parametrize("stops", [2, 1], ids=["both_rims", "one_rim"])
def test_a_file_guided_by_buttons_keys_where_it_stops_never_a_zero_clearance(stops):
    # The hub is filed down to the buttons' rims: the file touching them is the intended
    # stop, keyed as such with a leader to each rim it rides on. The nearest holding the
    # file must clear (here the stud) is still dimensioned. Its clearance is keyed between
    # the rims, so the rims are keyed apart, each by its own name: never one "BOTH" key
    # printed twice with a leader to one rim each.
    meshes, spec, _ = _guided_buttons(stops)
    main = _Diagram(meshes, spec)
    main.render()
    (detail,) = _holding_details(meshes, spec, main)

    project = detail.canvas.project
    ends = {}
    for label, path in detail.leaders:
        if label.startswith("FILE STOPS ON"):
            ends.setdefault(label, []).append(path[0])
    for stop in spec["guide_stops"]:
        rim = _solid_name(stop["tag"])
        keys = [label for label, points in ends.items() if project(stop["at_mm"]) in points]
        assert keys in ([f"FILE STOPS ON {rim} RIM"], ["FILE STOPS ON BOTH BUTTON RIMS"]), ends
    if "FILE STOPS ON BOTH BUTTON RIMS" in ends:
        assert len(ends["FILE STOPS ON BOTH BUTTON RIMS"]) == 2, ends
    printed = " ".join(box[0] for box in detail.canvas.text_boxes)
    assert printed.count("BOTH") <= 1, printed
    labels = [label for label, _ in detail.leaders]
    assert "CUT 3.755 mm FROM C1 STUD" in labels, labels
    assert not any(label.startswith("CUT 0") for label in labels), labels
    detail.canvas.assert_text_layout(min_scale=3)


def test_a_guided_file_gets_a_view_along_its_guide_axis_showing_the_rims_it_stops_on():
    # The edge-on section shows the button sandwich but not the rims the file rides on.
    # Looking down the stud: both rims (one over the other) are keyed once where the file
    # stops, the stock it files off is named, and the file comes in from outside the rims.
    meshes, spec, removal = _guided_buttons()
    main = _Diagram(meshes, spec)
    main.render()
    view = _guide_view(spec, main)

    assert view is not None
    assert view.camera[2] == pytest.approx((0, 0, 1))
    text = " ".join(box[0] for box in view.canvas.text_boxes)
    assert "VIEW ALONG THE BUTTON AXIS" in text, text
    project = view.canvas.project
    rims = [
        (project(run[0]), project(run[-1]))
        for stop in spec["guide_stops"]
        for run in stop["rim_mm"]
    ]
    left, top, right, bottom = view.viewport
    for x, y in [p for rim in rims for p in rim] + [project(p) for p in _corners(removal)]:
        assert left <= x <= right and top <= y <= bottom, (x, y)
    stops = [path for label, path in view.leaders if label == "FILE STOPS ON BOTH BUTTON RIMS"]
    assert len(stops) == 1, view.leaders
    end = stops[0][0]
    assert min(_point_segment_px(end, *rim) for rim in rims) <= 3, (end, rims)
    leaders = dict(view.leaders)
    assert _tag_at(view.canvas, *leaders["STOCK TO FILE OFF"][0]) == "removal"
    # The file comes in from beyond the rims, away from the stud axis.
    axis = project(spec["guide_view"]["axis_mm"][0])
    tail = leaders["FILE APPROACH"][0]
    assert math.dist(tail, axis) > max(math.dist(p, axis) for rim in rims for p in rim)
    view.canvas.assert_text_layout(min_scale=3)

    # The picture prints it below its holding detail.
    png, _ = render_diagram(meshes, spec)
    plain, _ = render_diagram(meshes, {k: v for k, v in spec.items() if k != "guide_view"})
    assert _decode_png(png)[1] == _decode_png(plain)[1] + view.canvas.height

    # A picture already looking along the axis needs no second look.
    spec["guide_view"]["axis_mm"][1] = [0, -1, 0]
    assert _guide_view(spec, main) is None


def _point_segment_px(point, a, b):
    dx, dy = b[0] - a[0], b[1] - a[1]
    span = dx * dx + dy * dy
    t = (
        0.0
        if span == 0
        else max(0.0, min(1.0, ((point[0] - a[0]) * dx + (point[1] - a[1]) * dy) / span))
    )
    return math.dist(point, (a[0] + t * dx, a[1] + t * dy))


def test_picture_contact_coordinates_print_on_the_setup_dro_grid_and_clearances_do_not():
    # A contact face 0.0031 off the zero prints on the 0.005 DRO grid as the fixture
    # tables print it; a clearance is a measured gap, printed at the decimals, unrounded.
    meshes, spec = _vise_spec(12)
    spec["decimals"] = 3
    spec["dro_step_mm"] = 0.005
    spec["zero_mm"] = [-0.0031, 0, 0]
    spec["closest_cut"] = {
        "mm": 6.6531,
        "tag": "fixed_jaw",
        "from_mm": [0, 6, 10],
        "to_mm": [0, 6, 10 - 6.6531],
    }
    main = _Diagram(meshes, spec)
    main.render()
    (detail,) = _holding_details(meshes, spec, main)
    labels = [label for label, _ in detail.leaders]
    assert "FIXED JAW CONTACT AT X 0.005" in labels, labels
    assert "MOVING JAW CONTACT AT X 12.005" in labels, labels
    assert "CUT 6.653 mm FROM FIXED JAW" in labels, labels


def test_keys_too_many_for_their_lanes_move_the_footer_down_never_across_it():
    # Thirty datum keys on small work: the lanes beside the scene cannot hold them at
    # body size above the divider. The picture grows; no key runs into the key below.
    spec = {
        "setup_id": "S1",
        "view": "isometric",
        "stock_box": [0, 0, 0, 40, 20, 10],
        "zero_mm": [0, 0, 0],
        "datums": [
            {"label": f"F{index}", "point_mm": [40 * (index % 2), index * 0.6, 10]}
            for index in range(30)
        ],
    }
    fixed = _Diagram([], spec)
    fixed.grows_to_fit = True
    fixed.render()
    assert fixed.lane_overflow > 0  # the 1000 px picture cannot hold them

    diagram, png = _main_diagram([], spec)
    keys = [box for box in diagram.canvas.text_boxes if box[0].startswith("DATUM F")]
    assert len(keys) == 30
    assert all(bottom + 4 <= diagram.footer_top for *_, bottom in keys), diagram.footer_top
    assert all(bottom - top >= 21 for _, _, top, _, bottom in keys)
    assert _decode_png(render_diagram([], spec)[0])[:2] == _decode_png(png)[:2]


def test_a_label_naming_points_on_both_sides_leads_from_each_lane_to_its_own_side():
    # One fixture name on both ends of long work: a single key would fan a leader from
    # one lane across the whole picture to the far end.
    spec = {
        "setup_id": "S4",
        "view": "plan",
        "stock_box": [0, 0, 0, 200, 20, 10],
        "zero_mm": [0, 0, 0],
        "components": [
            {"name": "rest slot", "role": "fixture", "center_mm": [x, 10, 0]} for x in (5, 195)
        ],
    }
    diagram, _ = _main_diagram([], spec)

    keys = [box for box in diagram.canvas.text_boxes if box[0] == "REST SLOT"]
    assert sorted(box[1] < diagram.lane_split for box in keys) == [False, True]
    leaders = [points for label, points in diagram.leaders if label == "REST SLOT"]
    assert len(leaders) == 2
    for points in leaders:
        sides = {x < diagram.lane_split for x, _ in points}
        assert len(sides) == 1, points


def test_lane_leaders_on_a_crowded_strip_never_cross_each_other_or_cut_across_the_work():
    # Rocker S4 from above: a thin strap on a plate, its pivot carrying datum A, the zero
    # and a datum B face key; slots either side of it on the strap's own centre line, and
    # a rest slot above and below the strap at one end.
    stock = [0, 0, 0, 300, 20, 10]
    meshes = [
        _slab(0, 0, 300, 20, 10, (160, 175, 185), "part"),
        _slab(-20, -60, 320, 80, 0, (104, 88, 120), "fx:plate"),
    ]
    slot = {"role": "detail"}
    spec = {
        "setup_id": "S4",
        "view": "plan",
        "stock_box": stock,
        "zero_mm": [150, 10, 10],
        "datums": [
            {"label": "A: PIVOT BORE", "point_mm": [150, 10, 10]},
            {"label": "B: BROAD FACE", "point_mm": [150, 12, 10]},
        ],
        "components": [
            {
                "name": "base",
                "label": "FIXTURE PLATE",
                "role": "plate",
                "center_mm": [150, -30, 0],
                "meshes": ["fx:plate"],
            },
            *({**slot, "name": "pad slots", "center_mm": [x, 10, 0]} for x in (60, 90, 120)),
            *({**slot, "name": "rest slots", "center_mm": [40, y, 0]} for y in (-8, 28)),
        ],
    }
    diagram, _ = _main_diagram(meshes, spec)

    lane = {callout.label for callout in diagram.callouts}
    leaders = [(label, path) for label, path in diagram.leaders if label in lane]
    assert {label for label, _ in leaders} >= {"STOCK", "FIXTURE PLATE", "Z0", "PAD SLOTS"}
    for index, (label, path) in enumerate(leaders):
        for other, other_path in leaders[index + 1 :]:
            for a, b in zip(path, path[1:], strict=False):
                for c, d in zip(other_path, other_path[1:], strict=False):
                    assert not _segments_cross(a, b, c, d), (label, other)
    # The plate shows beside the strap and the strap ends near the lane: neither leader
    # runs over the work to reach its solid (the stock's dot sits just inside its edge).
    (x0, y1), (x1, y0) = (diagram.canvas.project(p) for p in ((0, 0, 10), (300, 20, 10)))
    over = {"FIXTURE PLATE": 0, "STOCK": 8}
    for label, path in leaders:
        if label in over:
            inside = 0.0
            for a, b in zip(path, path[1:], strict=False):
                steps = max(1, round(math.dist(a, b)))
                for i in range(steps):
                    x = a[0] + (i + 0.5) / steps * (b[0] - a[0])
                    y = a[1] + (i + 0.5) / steps * (b[1] - a[1])
                    inside += (x0 < x < x1 and y0 < y < y1) * math.dist(a, b) / steps
            assert inside <= over[label], (label, path)


def test_a_named_void_at_numbered_positions_is_keyed_by_their_badges_not_leaders():
    # Rocker S4: a slot under each support pad. The pads' badges already mark every slot.
    spec = {
        "setup_id": "S4",
        "view": "plan",
        "stock_box": [0, 0, 0, 300, 20, 10],
        "zero_mm": [0, 0, 0],
        "components": [
            *(
                {
                    "name": f"pad-{code}",
                    "label": f"PAD {code.upper()}",
                    "role": "pad",
                    "center_mm": [x, 10, 0],
                    "box_mm": [x - 4, 6, -2, x + 4, 14, 0],
                }
                for code, x in (("l1", 60), ("l2", 90), ("l3", 120), ("r1", 200))
            ),
            *(
                {
                    "name": f"pad-{code}-slot",
                    "label": "Pad slots",
                    "role": "detail",
                    "center_mm": [x, 10, -3],
                }
                for code, x in (("l1", 60), ("l2", 90), ("l3", 120), ("r1", 200))
            ),
        ],
    }
    diagram, _ = _main_diagram([], spec)

    assert [label for label, _ in diagram.leaders if "SLOT" in label] == []
    lines = [box[0] for box in diagram.canvas.text_boxes]
    assert " ".join(lines).count("PAD SLOTS AT L1-L3, R1") == 1, lines


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


def _view_camera(up, toward):
    """The [right, up, toward] camera of a view with ``up`` up the page."""
    right = (
        up[1] * toward[2] - up[2] * toward[1],
        up[2] * toward[0] - up[0] * toward[2],
        up[0] * toward[1] - up[1] * toward[0],
    )
    return [right, up, toward]


def test_an_inspection_sketch_stands_the_part_on_the_plate_and_points_each_reading_up():
    # A 120 x 20 x 40 bar with a rod pin across its end, inspected standing on its -X end
    # and then tipped a quarter turn onto its -Z side: a band per orientation. In each,
    # the plate lies under the lowest solid, every mark and aid is keyed with a leader
    # ending on it, and the reading's + arrow points up the page (the way that
    # orientation's height reading rises), whichever part axis that is.
    from prechips.kernel.render_diagram import _GREEN, _InspectionSketch, render_inspection

    meshes = [
        _block([0, 0, 0, 120, 20, 40], (164, 177, 189), "part"),
        _block([100, -15, 15, 110, 35, 25], (164, 132, 64), "rod pin"),
    ]
    views = [
        {
            "title": title,
            "camera": _view_camera(up, (0, -1, 0)),
            "meshes": meshes,
            "aids": ["rod pin"],
            "marks": [
                {"label": "C", "at_mm": [0, 10, 20]},
                {"label": "H1", "at_mm": crown, "reads": True},
            ],
        }
        for title, up, crown in (
            ("VIEW 1: ON ITS END", (1, 0, 0), [110, 10, 20]),
            ("VIEW 2: ON ITS SIDE", (0, 0, 1), [105, 10, 25]),
        )
    ]

    png, debts = render_inspection(views)

    assert debts == []
    heights = []
    for view in views:
        band = _InspectionSketch(view)
        band.render()
        c = band.canvas
        heights.append(c.height)
        leaders = dict(band.leaders)
        assert set(leaders) == {"C", "H1", "ROD PIN", "SURFACE PLATE"}
        for mark in view["marks"]:
            assert leaders[mark["label"]][0] == pytest.approx(c.project(mark["at_mm"]), abs=1)
        assert _tag_at(c, *leaders["ROD PIN"][0]) == "rod pin"
        lowest = max(c.project(p)[1] for mesh in meshes for p in mesh[0])
        assert 0 <= leaders["SURFACE PLATE"][0][1] - lowest <= 2
        x, y = (math.floor(v) for v in c.project(view["marks"][1]["at_mm"]))
        assert _pixel(c, x, y - 30) == _GREEN
        assert _pixel(c, x, y + 30) != _GREEN
    width, height, _ = _decode_png(png)
    assert (width, height) == (1600, sum(heights))
