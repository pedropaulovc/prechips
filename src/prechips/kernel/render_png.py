"""Dependency-free, deterministic orthographic setup diagrams and bitmap annotations.

``camera`` contains world-space (right, up, toward-viewer) unit vectors;
``viewport`` is (left, top, right, bottom) in image pixels. Meshes are
(points, triangle-index-triples, RGB) with an optional fourth ``hatch`` bool.
Geometry is fitted at 90% of the viewport, drawn once, and then annotations
can be added in image coordinates. ``rgb`` is the packed, mutable RGB buffer.

Text uses an original 5x7 bitmap alphabet, with a six-pixel character advance
and nine-pixel line advance, multiplied by ``scale``. At the default scale 3,
letters are 21 pixels high (10.5 pixels when the image is printed at half size).
Text coordinates locate the upper-left of the first character cell, not a
baseline. Degree, diameter and plus/minus have their own glyphs; typographic
dashes/quotes and common mathematical signs have deterministic equivalents.
Other unsupported characters are shown as '?', never silently omitted.

PNG encoding is implemented here using only Python's standard-library zlib
and struct primitives: 8-bit RGB, filter-zero scanlines, no metadata or clock.
"""

import math
import struct
import zlib
from array import array

# Authored here as seven rows of five bits, most-significant bit at the left.
# Lowercase is deliberately distinct; small x-height labels keep their case.
_GLYPH_ROWS = {
    " ": "00 00 00 00 00 00 00",
    "!": "04 04 04 04 04 00 04",
    '"': "0A 0A 0A 00 00 00 00",
    "#": "0A 1F 0A 0A 1F 0A 00",
    "$": "04 0F 14 0E 05 1E 04",
    "%": "19 19 02 04 08 13 13",
    "&": "0C 12 14 08 15 12 0D",
    "'": "04 04 08 00 00 00 00",
    "(": "02 04 08 08 08 04 02",
    ")": "08 04 02 02 02 04 08",
    "*": "00 04 15 0E 15 04 00",
    "+": "00 04 04 1F 04 04 00",
    ",": "00 00 00 00 00 04 08",
    "-": "00 00 00 1F 00 00 00",
    ".": "00 00 00 00 00 00 04",
    "/": "01 02 02 04 08 08 10",
    "0": "0E 11 13 15 19 11 0E",
    "1": "04 0C 04 04 04 04 0E",
    "2": "0E 11 01 02 04 08 1F",
    "3": "1E 01 01 0E 01 01 1E",
    "4": "02 06 0A 12 1F 02 02",
    "5": "1F 10 10 1E 01 01 1E",
    "6": "0E 10 10 1E 11 11 0E",
    "7": "1F 01 02 04 08 08 08",
    "8": "0E 11 11 0E 11 11 0E",
    "9": "0E 11 11 0F 01 01 0E",
    ":": "00 04 04 00 04 04 00",
    ";": "00 04 04 00 04 04 08",
    "<": "02 04 08 10 08 04 02",
    "=": "00 00 1F 00 1F 00 00",
    ">": "08 04 02 01 02 04 08",
    "?": "0E 11 01 02 04 00 04",
    "@": "0E 11 17 15 17 10 0E",
    "A": "0E 11 11 1F 11 11 11",
    "B": "1E 11 11 1E 11 11 1E",
    "C": "0E 11 10 10 10 11 0E",
    "D": "1E 11 11 11 11 11 1E",
    "E": "1F 10 10 1E 10 10 1F",
    "F": "1F 10 10 1E 10 10 10",
    "G": "0E 11 10 17 11 11 0F",
    "H": "11 11 11 1F 11 11 11",
    "I": "0E 04 04 04 04 04 0E",
    "J": "07 02 02 02 12 12 0C",
    "K": "11 12 14 18 14 12 11",
    "L": "10 10 10 10 10 10 1F",
    "M": "11 1B 15 15 11 11 11",
    "N": "11 19 15 13 11 11 11",
    "O": "0E 11 11 11 11 11 0E",
    "P": "1E 11 11 1E 10 10 10",
    "Q": "0E 11 11 11 15 12 0D",
    "R": "1E 11 11 1E 14 12 11",
    "S": "0F 10 10 0E 01 01 1E",
    "T": "1F 04 04 04 04 04 04",
    "U": "11 11 11 11 11 11 0E",
    "V": "11 11 11 11 11 0A 04",
    "W": "11 11 11 15 15 1B 11",
    "X": "11 11 0A 04 0A 11 11",
    "Y": "11 11 0A 04 04 04 04",
    "Z": "1F 01 02 04 08 10 1F",
    "[": "0E 08 08 08 08 08 0E",
    "\\": "10 08 08 04 02 02 01",
    "]": "0E 02 02 02 02 02 0E",
    "^": "04 0A 11 00 00 00 00",
    "_": "00 00 00 00 00 00 1F",
    "`": "08 04 02 00 00 00 00",
    "a": "00 00 0E 01 0F 11 0F",
    "b": "10 10 1E 11 11 11 1E",
    "c": "00 00 0E 10 10 11 0E",
    "d": "01 01 0F 11 11 11 0F",
    "e": "00 00 0E 11 1F 10 0F",
    "f": "06 09 08 1C 08 08 08",
    "g": "00 0F 11 11 0F 01 0E",
    "h": "10 10 1E 11 11 11 11",
    "i": "04 00 0C 04 04 04 0E",
    "j": "02 00 06 02 02 12 0C",
    "k": "10 10 12 14 18 14 12",
    "l": "0C 04 04 04 04 04 0E",
    "m": "00 00 1A 15 15 15 15",
    "n": "00 00 1E 11 11 11 11",
    "o": "00 00 0E 11 11 11 0E",
    "p": "00 1E 11 11 1E 10 10",
    "q": "00 0F 11 11 0F 01 01",
    "r": "00 00 16 19 10 10 10",
    "s": "00 00 0F 10 0E 01 1E",
    "t": "08 08 1C 08 08 09 06",
    "u": "00 00 11 11 11 13 0D",
    "v": "00 00 11 11 11 0A 04",
    "w": "00 00 11 11 15 15 0A",
    "x": "00 00 11 0A 04 0A 11",
    "y": "00 11 11 11 0F 01 0E",
    "z": "00 00 1F 02 04 08 1F",
    "{": "03 04 04 08 04 04 03",
    "|": "04 04 04 04 04 04 04",
    "}": "18 04 04 02 04 04 18",
    "~": "00 00 09 16 00 00 00",
    "°": "06 09 09 06 00 00 00",
    "Ø": "0F 13 15 15 15 19 1E",
    "ø": "00 00 0F 13 15 19 1E",
    "±": "04 04 1F 04 04 00 1F",
    "×": "00 11 0A 04 0A 11 00",
}
_GLYPHS = {char: tuple(int(row, 16) for row in rows.split()) for char, rows in _GLYPH_ROWS.items()}
del _GLYPH_ROWS
_TEXT_EQUIVALENTS = str.maketrans(
    {
        "\u00a0": " ",
        "\u202f": " ",
        "–": "-",
        "—": "--",
        "−": "-",
        "‘": "'",
        "’": "'",
        "′": "'",
        "“": '"',
        "”": '"',
        "″": '"',
        "…": "...",
        "⌀": "Ø",
        "∅": "Ø",
        "µ": "u",
        "μ": "u",
        "≤": "<=",
        "≥": ">=",
        "≠": "!=",
        "\t": "    ",
        "\r": "",
    }
)
_LIGHT_LENGTH = math.sqrt(0.4**2 + 0.6**2 + 1.0)
_LIGHT = (0.4 / _LIGHT_LENGTH, -0.6 / _LIGHT_LENGTH, 1.0 / _LIGHT_LENGTH)


def _label(text):
    return "".join(
        char if char in _GLYPHS or char == "\n" else "?"
        for char in str(text).translate(_TEXT_EQUIVALENTS)
    )


def _text_scale(scale):
    if isinstance(scale, bool) or not isinstance(scale, int) or scale < 1:
        raise ValueError("text scale must be a positive integer")
    return scale


def _dot(point, vector):
    return point[0] * vector[0] + point[1] * vector[1] + point[2] * vector[2]


def _chunk(kind, data):
    checksum = zlib.crc32(data, zlib.crc32(kind)) & 0xFFFFFFFF
    return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", checksum)


class RenderCanvas:
    """White RGB canvas with fitted orthographic meshes and pixel-space overlays.

    Overlays are painted in call order without a depth test. Larger mesh depth
    (dot product with ``toward``) occludes smaller depth; equal depths retain
    the first triangle. Hatch stripes alternate on the pixel grid and obey
    exactly the same visibility test as solid faces. No geometry is redrawn
    by ``png()``, so repeated encoding is idempotent.
    """

    def __init__(
        self, meshes, camera, viewport=(180, 160, 1420, 730), width=1600, height=1000, fit=None
    ):
        """``fit``: world points the view is scaled to; every mesh when None. Geometry
        outside the fitted viewport is cropped at its edge."""
        if (
            isinstance(width, bool)
            or isinstance(height, bool)
            or not isinstance(width, int)
            or not isinstance(height, int)
            or width < 1
            or height < 1
        ):
            raise ValueError("canvas dimensions must be positive integers")
        left, top, right, bottom = viewport
        if not all(math.isfinite(v) for v in viewport) or right <= left or bottom <= top:
            raise ValueError("viewport must have finite, positive extents")
        self.width, self.height = width, height
        self.rgb = bytearray(b"\xff") * (width * height * 3)
        self.text_boxes = []
        self._right, self._up, self._toward = camera
        self._pixel_centre = ((left + right) / 2, (top + bottom) / 2)
        self._world_centre = (0.0, 0.0)
        self.scale = 1.0
        projected = []
        xmin = ymin = math.inf
        xmax = ymax = -math.inf
        for mesh in meshes:
            points, triangles, colour = mesh[:3]
            hatch = bool(mesh[3]) if len(mesh) > 3 else False
            screen = []
            for point in points:
                x = _dot(point, self._right)
                y = _dot(point, self._up)
                screen.append((x, y, _dot(point, self._toward)))
                xmin, xmax = min(xmin, x), max(xmax, x)
                ymin, ymax = min(ymin, y), max(ymax, y)
            projected.append((points, screen, triangles, colour, hatch))
        if fit is not None:
            fitted = [(_dot(p, self._right), _dot(p, self._up)) for p in fit]
            if fitted:
                xmin, xmax = min(x for x, _ in fitted), max(x for x, _ in fitted)
                ymin, ymax = min(y for _, y in fitted), max(y for _, y in fitted)
        if xmin == math.inf:
            return
        self._world_centre = ((xmin + xmax) / 2, (ymin + ymax) / 2)
        scales = []
        if xmax > xmin:
            scales.append(0.9 * (right - left) / (xmax - xmin))
        if ymax > ymin:
            scales.append(0.9 * (bottom - top) / (ymax - ymin))
        if scales:
            self.scale = min(scales)
        bounds = (
            max(0, math.ceil(left - 0.5)),
            max(0, math.ceil(top - 0.5)),
            min(width - 1, math.ceil(right - 0.5) - 1),
            min(height - 1, math.ceil(bottom - 0.5) - 1),
        )
        depth = array("d", [-math.inf]) * (width * height)
        for points, screen, triangles, colour, hatch in projected:
            pix = [(*self._project_xy(x, y), d) for x, y, d in screen]
            for a, b, c in triangles:
                p0, p1, p2 = points[a], points[b], points[c]
                ux, uy, uz = (p1[i] - p0[i] for i in range(3))
                vx, vy, vz = (p2[i] - p0[i] for i in range(3))
                normal = (uy * vz - uz * vy, uz * vx - ux * vz, ux * vy - uy * vx)
                length = math.sqrt(_dot(normal, normal))
                if length == 0:
                    continue
                shade = 0.3 + 0.7 * min(1.0, abs(_dot(normal, _LIGHT)) / length)
                pixel = bytes(min(255, max(0, int(channel * shade + 0.5))) for channel in colour)
                stripe = bytes(int(channel * 0.55 + 0.5) for channel in pixel)
                self._triangle(pix[a], pix[b], pix[c], pixel, stripe, hatch, depth, bounds)

    def _project_xy(self, x, y):
        cx, cy = self._world_centre
        px, py = self._pixel_centre
        return px + (x - cx) * self.scale, py - (y - cy) * self.scale

    def project(self, xyz):
        """Return image x/y for a world-space point, including fitted translation."""
        return self._project_xy(_dot(xyz, self._right), _dot(xyz, self._up))

    def _triangle(self, p0, p1, p2, pixel, stripe, hatch, depth, bounds):
        (x0, y0, d0), (x1, y1, d1), (x2, y2, d2) = p0, p1, p2
        area = (x1 - x0) * (y2 - y0) - (x2 - x0) * (y1 - y0)
        if abs(area) < 1e-12:
            return
        if area < 0:
            x1, y1, d1, x2, y2, d2 = x2, y2, d2, x1, y1, d1
            area = -area
        gx = ((d1 - d0) * (y2 - y0) - (d2 - d0) * (y1 - y0)) / area
        gy = ((d2 - d0) * (x1 - x0) - (d1 - d0) * (x2 - x0)) / area
        g0 = d0 - gx * x0 - gy * y0
        edges = ((x0, y0, x1, y1), (x1, y1, x2, y2), (x2, y2, x0, y0))
        left, top, right, bottom = bounds
        row_lo = max(top, math.ceil(min(y0, y1, y2) - 0.5))
        row_hi = min(bottom, math.floor(max(y0, y1, y2) - 0.5))
        left_bound, right_bound = min(x0, x1, x2), max(x0, x1, x2)
        rgb, width = self.rgb, self.width
        for row in range(row_lo, row_hi + 1):
            yc = row + 0.5
            lo, hi = left_bound, right_bound
            for ax, ay, bx, by in edges:
                slope = -(by - ay)
                offset = (bx - ax) * (yc - ay) + (by - ay) * ax
                if slope > 0:
                    lo = max(lo, -offset / slope)
                elif slope < 0:
                    hi = min(hi, -offset / slope)
                elif offset < 0:
                    lo, hi = 1.0, 0.0
                    break
            first = max(left, math.ceil(lo - 0.5))
            last = min(right, math.floor(hi - 0.5))
            base = row * width
            row_depth = gy * yc + g0
            for column in range(first, last + 1):
                value = gx * (column + 0.5) + row_depth
                slot = base + column
                if value > depth[slot]:
                    depth[slot] = value
                    colour = stripe if hatch and (column + row) % 12 < 3 else pixel
                    offset = slot * 3
                    rgb[offset : offset + 3] = colour

    def _span(self, row, first, last, pixel):
        if row < 0 or row >= self.height:
            return
        first, last = max(0, first), min(self.width - 1, last)
        if first <= last:
            start = (row * self.width + first) * 3
            self.rgb[start : start + (last - first + 1) * 3] = pixel * (last - first + 1)

    def text_width(self, text, scale=3):
        """Pixel width of the longest normalized line, excluding its trailing gap."""
        scale = _text_scale(scale)
        count = max((len(line) for line in _label(text).split("\n")), default=0)
        return max(0, count * 6 - 1) * scale

    def text(self, x, y, text, colour=(30, 35, 40), scale=3):
        """Paint bundled bitmap text; multiline labels advance by nine scaled pixels."""
        scale = _text_scale(scale)
        pixel = bytes(colour)
        x, y = round(x), round(y)
        for line_index, line in enumerate(_label(text).split("\n")):
            top = y + line_index * 9 * scale
            label = line.strip(" ")
            if label:
                left = x + (len(line) - len(line.lstrip(" "))) * 6 * scale
                self.text_boxes.append(
                    (label, left, top, left + (len(label) * 6 - 1) * scale, top + 7 * scale)
                )
            for char_index, char in enumerate(line):
                left = x + char_index * 6 * scale
                for row, bits in enumerate(_GLYPHS[char]):
                    if not bits:
                        continue
                    for column in range(5):
                        if bits & (1 << (4 - column)):
                            first = left + column * scale
                            for offset in range(scale):
                                self._span(
                                    top + row * scale + offset, first, first + scale - 1, pixel
                                )

    def assert_text_layout(self, *, margin=8, min_gap=4):
        """Reject text outside the inset canvas or closer than ``min_gap`` pixels.

        ``text_boxes`` contains normalized, nonblank lines with exclusive right
        and bottom bounds; surrounding spaces do not contribute to the bounds.
        Checking is opt-in and never changes the painted pixels.
        """
        for index, (label, left, top, right, bottom) in enumerate(self.text_boxes):
            if (
                left < margin
                or top < margin
                or right > self.width - margin
                or bottom > self.height - margin
            ):
                raise ValueError(
                    f"Text {label!r} bounds {(left, top, right, bottom)} exceed "
                    f"canvas bounds {(margin, margin, self.width - margin, self.height - margin)}"
                )
            for other_index in range(index):
                other_label, other_left, other_top, other_right, other_bottom = self.text_boxes[
                    other_index
                ]
                if (
                    left < other_right + min_gap
                    and other_left < right + min_gap
                    and top < other_bottom + min_gap
                    and other_top < bottom + min_gap
                ):
                    raise ValueError(
                        f"Text {label!r} bounds {(left, top, right, bottom)} and "
                        f"{other_label!r} bounds "
                        f"{(other_left, other_top, other_right, other_bottom)} "
                        f"overlap with required gap {min_gap}"
                    )

    def polygon(self, points, fill, outline=None):
        """Paint a simple polygon with an even-odd fill, including concave outlines."""
        points = list(points)
        if not points:
            return
        if fill is not None and len(points) >= 3:
            pixel = bytes(fill)
            low = max(0, math.ceil(min(p[1] for p in points) - 0.5))
            high = min(self.height - 1, math.ceil(max(p[1] for p in points) - 0.5) - 1)
            edges = list(zip(points, points[1:] + points[:1], strict=False))
            for row in range(low, high + 1):
                yc = row + 0.5
                crossings = []
                for (ax, ay), (bx, by) in edges:
                    if ay <= yc < by or by <= yc < ay:
                        crossings.append(ax + (yc - ay) * (bx - ax) / (by - ay))
                crossings.sort()
                for index in range(0, len(crossings) - 1, 2):
                    self._span(
                        row,
                        math.ceil(crossings[index] - 0.5),
                        math.ceil(crossings[index + 1] - 0.5) - 1,
                        pixel,
                    )
        if outline is not None:
            for start, end in zip(points, points[1:] + points[:1], strict=False):
                self.line(start, end, outline, width=1)

    def rect(self, x, y, w, h, fill, outline=None):
        """Paint an axis-aligned rectangle; outlines are one pixel thick."""
        x1, x2 = sorted((x, x + w))
        y1, y2 = sorted((y, y + h))
        if fill is not None:
            pixel = bytes(fill)
            first, last = math.ceil(x1 - 0.5), math.ceil(x2 - 0.5) - 1
            for row in range(max(0, math.ceil(y1 - 0.5)), min(self.height, math.ceil(y2 - 0.5))):
                self._span(row, first, last, pixel)
        if outline is not None:
            self.polygon(((x1, y1), (x2, y1), (x2, y2), (x1, y2)), None, outline)

    def circle(self, x, y, r, fill=None, outline=None):
        """Paint a disk and/or a one-pixel ring, clipped to the image."""
        if r < 0 or fill is None and outline is None:
            return
        outer = r + 0.5 if outline is not None else r
        inner = max(0, r - 0.5)
        fill_pixel = bytes(fill) if fill is not None else None
        outline_pixel = bytes(outline) if outline is not None else None
        low = max(0, math.ceil(y - outer - 0.5))
        high = min(self.height - 1, math.floor(y + outer - 0.5))
        for row in range(low, high + 1):
            dy = row + 0.5 - y
            reach = math.sqrt(max(0, outer * outer - dy * dy))
            first, last = math.ceil(x - reach - 0.5), math.floor(x + reach - 0.5)
            if outline_pixel is None:
                self._span(row, first, last, fill_pixel)
            elif abs(dy) >= inner:
                self._span(row, first, last, outline_pixel)
            else:
                inside = math.sqrt(inner * inner - dy * dy)
                inner_first = math.ceil(x - inside - 0.5)
                inner_last = math.floor(x + inside - 0.5)
                self._span(row, first, inner_first - 1, outline_pixel)
                self._span(row, inner_last + 1, last, outline_pixel)
                if fill_pixel is not None:
                    self._span(row, inner_first, inner_last, fill_pixel)

    def line(self, a, b, colour, width=2, dashed=False):
        """Paint a round-ended stroke; dashed strokes use an 8-on/6-off pixel pattern."""
        if width <= 0:
            return
        ax, ay = a
        bx, by = b
        dx, dy = bx - ax, by - ay
        length = math.hypot(dx, dy)
        radius = width / 2
        if length == 0:
            self.circle(ax, ay, radius, fill=colour)
            return
        # Clip the centreline to the canvas plus its stroke radius before walking
        # dashes. This also bounds work for annotations whose ends lie off-image.
        t0, t1 = 0.0, 1.0
        for p, q in (
            (-dx, ax + radius),
            (dx, self.width + radius - ax),
            (-dy, ay + radius),
            (dy, self.height + radius - ay),
        ):
            if p == 0:
                if q < 0:
                    return
                continue
            t = q / p
            if p < 0:
                t0 = max(t0, t)
            else:
                t1 = min(t1, t)
            if t0 > t1:
                return
        ux, uy = dx / length, dy / length
        nx, ny = -uy * radius, ux * radius

        def stroke(start, end):
            sx, sy = ax + ux * start, ay + uy * start
            ex, ey = ax + ux * end, ay + uy * end
            self.polygon(
                ((sx + nx, sy + ny), (ex + nx, ey + ny), (ex - nx, ey - ny), (sx - nx, sy - ny)),
                colour,
            )
            self.circle(sx, sy, radius, fill=colour)
            self.circle(ex, ey, radius, fill=colour)

        start, end = t0 * length, t1 * length
        if not dashed:
            stroke(start, end)
            return
        dash = math.floor(start / 14) * 14
        while dash <= end:
            lo, hi = max(start, dash), min(end, dash + 8)
            if lo < hi:
                stroke(lo, hi)
            dash += 14

    def arrow(self, a, b, colour, width=3):
        """Paint a shaft from a to b and a filled triangular head pointing at b."""
        if width <= 0:
            return
        dx, dy = b[0] - a[0], b[1] - a[1]
        length = math.hypot(dx, dy)
        if length == 0:
            self.line(a, b, colour, width)
            return
        ux, uy = dx / length, dy / length
        head = min(length, max(10, width * 4))
        wing = head * 0.45
        base = (b[0] - ux * head, b[1] - uy * head)
        self.line(a, (b[0] - ux * head * 0.65, b[1] - uy * head * 0.65), colour, width)
        self.polygon(
            (
                b,
                (base[0] - uy * wing, base[1] + ux * wing),
                (base[0] + uy * wing, base[1] - ux * wing),
            ),
            colour,
        )

    def png(self):
        """Encode the current canvas as deterministic truecolour PNG bytes."""
        stride = self.width * 3
        raw = bytearray((stride + 1) * self.height)
        source = memoryview(self.rgb)
        for row in range(self.height):
            start = row * (stride + 1) + 1
            raw[start : start + stride] = source[row * stride : (row + 1) * stride]
        header = struct.pack(">IIBBBBB", self.width, self.height, 8, 2, 0, 0, 0)
        return (
            b"\x89PNG\r\n\x1a\n"
            + _chunk(b"IHDR", header)
            + _chunk(b"IDAT", zlib.compress(raw, 9))
            + _chunk(b"IEND", b"")
        )
