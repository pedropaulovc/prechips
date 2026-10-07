"""Consumer-visible raster, camera, visibility and print-label contracts; no FreeCAD."""

import json
import math
import struct
import zlib
from pathlib import Path

import pytest

from prechips.kernel.render_diagram import _Diagram, render_diagram
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
    width, height, _ = _decode_png(render_diagram([], spec))
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
