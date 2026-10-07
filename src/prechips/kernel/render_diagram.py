"""Print-oriented setup diagrams from placed meshes and explicit shop-floor facts.

All millimetre measurements come from ``spec``. Outlined machine/table context is
screen-space symbolism, deliberately separate from the modelled fixture geometry.
"""

import math
from collections import defaultdict
from dataclasses import dataclass

try:
    from .render_png import RenderCanvas
except ImportError:  # FreeCAD runs the kernel helpers as standalone modules.
    from render_png import RenderCanvas


_INK = (30, 35, 40)
_MUTED = (85, 93, 100)
_RULE = (183, 190, 195)
_WHITE = (255, 255, 255)
_BLUE = (35, 83, 147)
_GREEN = (24, 91, 58)
_AMBER = (172, 111, 16)
_AMBER_LIGHT = (252, 235, 190)
_NOMINAL_FAINT = (173, 193, 218)
_FIXTURE = (120, 98, 76)
_BODY_SCALE = 3
_AXIS_COLOURS = ((160, 47, 43), (44, 104, 57), (42, 83, 158))
_CAMERAS = {
    "lathe": ((0, 0, 1), (1, 0, 0), (0, -1, 0)),
    "plan": ((1, 0, 0), (0, 1, 0), (0, 0, 1)),
    "isometric": (
        (1 / math.sqrt(2), 1 / math.sqrt(2), 0),
        (-1 / math.sqrt(6), 1 / math.sqrt(6), 2 / math.sqrt(6)),
        (1 / math.sqrt(3), -1 / math.sqrt(3), 1 / math.sqrt(3)),
    ),
}


@dataclass
class _Callout:
    label: str
    points: list
    colour: tuple = _INK
    # "line": a leader from the lane to the point; "keyed": the point carries its own
    # position badge, so the lane entry is the badge's key and draws no leader.
    leader: str = "line"


def _plain(value):
    """Keep shop labels printable without exposing unsupported glyph placeholders."""
    text = str(value).replace("_", " ")
    for old, new in (
        ("?", "not declared"),
        ("−", "-"),
        ("–", "-"),
        ("—", "-"),
        ("×", "x"),
        ("Ø", "DIA "),
        ("ø", "DIA "),
        ("°", " DEG"),
        ("→", " TO "),
        ("≤", " <= "),
        ("≥", " >= "),
    ):
        text = text.replace(old, new)
    return " ".join(text.split()).upper()


def _mm(value):
    text = f"{value:.2f}".rstrip("0").rstrip(".")
    return "0" if text in ("", "-0") else text


def _corners(box):
    if box is None:
        return []
    return [(x, y, z) for x in (box[0], box[3]) for y in (box[1], box[4]) for z in (box[2], box[5])]


def _bounds(points):
    return (
        min(p[0] for p in points),
        min(p[1] for p in points),
        max(p[0] for p in points),
        max(p[1] for p in points),
    )


def _xy_projector(bounds, centre, scales):
    """Bind a panel's graphic transform without changing its physical XY data."""
    xmin, ymin, xmax, ymax = bounds
    cx, cy = centre
    scale_x, scale_y = scales

    def project(point):
        return (
            cx + (point[0] - (xmin + xmax) / 2) * scale_x,
            cy - (point[1] - (ymin + ymax) / 2) * scale_y,
        )

    return project


def _centre(box):
    return tuple((box[i] + box[i + 3]) / 2 for i in range(3))


def _role(component):
    name = component.get("name", "").lower().replace(" ", "_")
    role = component.get("role", "").lower().replace(" ", "_")
    if name in ("fixed_jaw", "moving_jaw"):
        return name
    return role


def _wrap(canvas, text, width, scale=2):
    words = _plain(text).split()
    lines, line = [], ""
    for word in words:
        if canvas.text_width(word, scale=scale) > width:
            if line:
                lines.append(line)
                line = ""
            chunk = ""
            for character in word:
                if chunk and canvas.text_width(chunk + character, scale=scale) > width:
                    lines.append(chunk)
                    chunk = ""
                chunk += character
            line = chunk
        elif line and canvas.text_width(line + " " + word, scale=scale) > width:
            lines.append(line)
            line = word
        else:
            line = (line + " " + word).strip()
    if line:
        lines.append(line)
    return lines or [""]


def _text(canvas, x, y, text, colour=_INK, scale=_BODY_SCALE, align="left", backing=False):
    text = _plain(text)
    width = canvas.text_width(text, scale=scale)
    if align == "centre":
        x -= width / 2
    elif align == "right":
        x -= width
    if backing:
        canvas.rect(x - 4, y - 3, width + 8, 7 * scale + 6, _WHITE)
    canvas.text(x, y, text, colour=colour, scale=scale)


def _outline(canvas, points, colour=_MUTED, width=2, dashed=False):
    for first, second in zip(points, points[1:] + points[:1], strict=True):
        canvas.line(first, second, colour, width=width, dashed=dashed)


def _clip_segment(a, b, box):
    """Clip an underlay segment to its panel, never to a neighbouring key lane."""
    left, top, right, bottom = box
    dx, dy = b[0] - a[0], b[1] - a[1]
    low, high = 0.0, 1.0
    for p, q in ((-dx, a[0] - left), (dx, right - a[0]), (-dy, a[1] - top), (dy, bottom - a[1])):
        if p == 0:
            if q < 0:
                return None
        else:
            crossing = q / p
            if p < 0:
                low = max(low, crossing)
            else:
                high = min(high, crossing)
            if low > high:
                return None
    return ((a[0] + low * dx, a[1] + low * dy), (a[0] + high * dx, a[1] + high * dy))


def _badge_width(canvas, label, scale=3):
    return max(24, canvas.text_width(label, scale=scale) + 12)


def _badge(canvas, point, label, colour=_BLUE, scale=3):
    width = _badge_width(canvas, label, scale)
    height = 7 * scale + 12
    x, y = point[0] - width / 2, point[1] - height / 2
    canvas.rect(x, y, width, height, _WHITE)
    _outline(canvas, [(x, y), (x + width, y), (x + width, y + height), (x, y + height)], colour)
    _text(canvas, point[0], y + 6, label, colour, scale=scale, align="centre")


def _rows_for(widths, span):
    """Fewest interleaved badge rows (every n-th badge per row) that fit ``span``."""
    for rows in range(1, len(widths) + 1):
        if all(sum(w + 8 for w in widths[row::rows]) - 8 <= span for row in range(rows)):
            return rows
    return 0


def _row_positions(targets, widths, left, right):
    """Badge centres in one row, in the targets' order, at least 8 px apart, inside
    ``left``..``right`` and of least squared displacement from the targets."""
    offsets = [0.0]
    for first, second in zip(widths, widths[1:], strict=False):
        offsets.append(offsets[-1] + (first + second) / 2 + 8)
    # Isotonic (pool-adjacent-violators) fit of the offset-free positions.
    blocks = []
    for value in (target - offset for target, offset in zip(targets, offsets, strict=True)):
        blocks.append([value, 1])
        while len(blocks) > 1 and blocks[-2][0] / blocks[-2][1] > blocks[-1][0] / blocks[-1][1]:
            total, count = blocks.pop()
            blocks[-1][0] += total
            blocks[-1][1] += count
    fitted = [total / count for total, count in blocks for _ in range(count)]
    low, high = left + widths[0] / 2, right - widths[-1] / 2 - offsets[-1]
    return [
        min(max(value, low), high) + offset for value, offset in zip(fitted, offsets, strict=True)
    ]


def _band_cells(points, widths, plot, exclusion):
    """Badge centres in rows wholly above and below ``exclusion``. Neighbouring points on
    the geometry's mid band alternate between the bands; each row keeps its points' left
    to right order directly above or below them, so the leaders fan out without crossing
    and every badge stays beside its own support, clamp or pickup."""
    left, top, right, bottom = plot
    height, pitch = 33, 41
    upper_bottom, lower_top = min(bottom, exclusion[1] - 8), max(top, exclusion[3] + 8)
    capacity = {
        -1: max(0, int((upper_bottom - top + 8) / pitch)),
        1: max(0, int((bottom - lower_top + 8) / pitch)),
    }
    middle = (min(p[1] for p in points) + max(p[1] for p in points)) / 2
    band = 0.1 * (max(p[1] for p in points) - min(p[1] for p in points))
    order = sorted(range(len(points)), key=lambda index: (points[index][0], points[index][1]))
    sides, free = {}, []
    for index in order:
        offset = points[index][1] - middle
        if abs(offset) <= band:
            free.append(index)
            sides[index] = -1 if len(free) % 2 else 1
        else:
            sides[index] = 1 if offset > 0 else -1
    for index in order:
        if not capacity[sides[index]]:
            sides[index] = -sides[index]

    def rows_needed(side):
        return _rows_for([widths[index] for index in order if sides[index] == side], right - left)

    # Move mid-band points to the other band while one band needs more rows than it has.
    for _ in free:
        side = max((-1, 1), key=lambda s: rows_needed(s) - capacity[s])
        if rows_needed(side) <= capacity[side] or not capacity[-side]:
            break
        movable = [index for index in free if sides[index] == side]
        if not movable:
            break
        moved = min(movable, key=lambda index: abs(points[index][1] - middle))
        sides[moved] = -side
        if rows_needed(-side) > capacity[-side]:
            sides[moved] = side
            break
    centres = [None] * len(points)
    for side, edge in ((-1, upper_bottom), (1, lower_top)):
        members = [index for index in order if sides[index] == side]
        rows = rows_needed(side)
        for row in range(rows):
            # Row 0 is nearest the geometry; outer rows interleave between its badges.
            row_members = members[row::rows]
            y = edge + side * (height / 2 + row * pitch)
            xs = _row_positions(
                [points[index][0] for index in row_members],
                [widths[index] for index in row_members],
                left,
                right,
            )
            for index, x in zip(row_members, xs, strict=True):
                centres[index] = (x, y)
    return centres


def _dimension(canvas, first, second, label, colour=_INK):
    """Opposed inward arrowheads; a very short projection still has a readable label."""
    length = math.dist(first, second)
    if length > 18:
        middle = ((first[0] + second[0]) / 2, (first[1] + second[1]) / 2)
        canvas.arrow(middle, first, colour, width=2)
        canvas.arrow(middle, second, colour, width=2)
    else:
        canvas.line(first, second, colour, width=2)
        for point in (first, second):
            canvas.line((point[0], point[1] - 5), (point[0], point[1] + 5), colour, width=2)
    _text(
        canvas,
        (first[0] + second[0]) / 2,
        (first[1] + second[1]) / 2 - 23,
        label,
        colour,
        align="centre",
        backing=True,
    )


def _match(count, cells, cost):
    """Cell index per item, minimising the summed ``cost(item, cell)``: exact over cells
    for up to 8 items, else greedy in item order."""
    table = [[cost(index, cell) for cell in cells] for index in range(count)]
    if count > 8 or count > len(cells):
        free, chosen = list(range(len(cells))), []
        for index in range(count):
            best = min(free, key=lambda cell: table[index][cell])
            free.remove(best)
            chosen.append(best)
        return chosen
    best = {0: (0.0, ())}
    for cell_index in range(len(cells)):
        step = dict(best)
        for mask, (total, pairs) in best.items():
            for index in range(count):
                if mask >> index & 1:
                    continue
                key, value = mask | 1 << index, total + table[index][cell_index]
                if key not in step or value < step[key][0] - 1e-9:
                    step[key] = (value, (*pairs, (index, cell_index)))
        best = step
    return [cell for _, cell in sorted(best[(1 << count) - 1][1])]


def _segment_distance(point, a, b):
    """Pixel distance from ``point`` to the segment ``a``-``b``."""
    dx, dy = b[0] - a[0], b[1] - a[1]
    length = dx * dx + dy * dy
    t = 0.0 if not length else ((point[0] - a[0]) * dx + (point[1] - a[1]) * dy) / length
    t = min(1.0, max(0.0, t))
    return math.dist(point, (a[0] + t * dx, a[1] + t * dy))


def _shoulder(z, small, large):
    return f"SHOULDER Z {_mm(z)}: DIA {_mm(2 * small)} / DIA {_mm(2 * large)}"


def _radial_steps(profiles):
    """(z, smaller radius, larger radius) of every radial step of the finished meridian."""
    steps = {}
    for profile in profiles:
        if profile.get("label") != "after this setup":
            continue
        for line in profile["lines"]:
            for (r0, z0), (r1, z1) in zip(line, line[1:], strict=False):
                if abs(z1 - z0) > 1e-6 or min(r0, r1) <= 0 or abs(r1 - r0) <= 1e-6:
                    continue
                steps[round(z0, 4)] = (z0, min(r0, r1), max(r0, r1))
    return sorted(steps.values())


class _Diagram:
    def __init__(self, meshes, spec):
        self.spec = spec
        self.view = spec["view"]
        self.camera = (
            tuple(map(tuple, spec["camera"])) if spec.get("camera") else _CAMERAS[self.view]
        )
        self.components = spec.get("components", [])
        self.stock = spec.get("stock_box")
        self.tool = spec.get("primary_tool")
        self.nominal = [line for line in spec.get("nominal_outline_mm", []) if len(line) >= 2]
        if self.view == "lathe":
            self.nominal = []
        self.is_vise = any(_role(c) in ("fixed_jaw", "moving_jaw", "jaw") for c in self.components)
        self.is_chuck = self.view == "lathe" or any(
            _role(c).startswith("chuck") for c in self.components
        )
        self.callouts = []
        self.obstacles = []
        self.context_labels = []
        self.position_badges = []
        self.leaders = []  # printed leaders: (label, pixel polyline from the point)
        self.dimensions = {}  # printed dimension label -> its two arrow ends (pixels)
        self.jaw_marker = None  # projected jaw-front marker, where stickout starts
        self.lathe_window = None
        self.off_window_keys = []
        self.shoulders = (
            _radial_steps(spec.get("lathe_profiles", [])) if self.view == "lathe" else []
        )
        if self.view == "lathe":
            profile_points = [
                p
                for profile in spec.get("lathe_profiles", [])
                for line in profile["lines"]
                for p in line
            ]
            if profile_points:
                self.lathe_window = (
                    min(p[1] for p in profile_points),
                    max(p[1] for p in profile_points),
                )
                display = {
                    str(p["op"]): p.get("x_display", "radius") for p in spec.get("axial_paths", [])
                }
                for waypoint in spec.get("waypoints", []):
                    if "xz" not in waypoint:
                        continue
                    x, z = waypoint["xz"]
                    if self.lathe_window[0] <= z <= self.lathe_window[1]:
                        continue
                    convention = waypoint.get(
                        "x_display",
                        display.get(str(waypoint.get("op")), "radius"),
                    )
                    radius = x / 2 if convention == "diameter" else x
                    self.off_window_keys.append((waypoint["label"], (radius, 0, z)))
        self.meshes = list(meshes)
        points = _corners(self.stock)
        points.extend(point for line in self.nominal for point in line)
        points.extend(point for _, point in self.off_window_keys)
        framed = self._framed()
        if spec.get("zero_mm") is not None:
            points.append(spec["zero_mm"])
        for datum in spec.get("datums", []):
            points.append(datum["point_mm"])
        for component in framed:
            points.extend(_corners(component.get("box_mm")))
            points.append(component["center_mm"])
        if self.tool:
            outlines = self.tool.get("outlines_mm") or [self.tool.get("outline_mm", [])]
            points.extend(point for outline in outlines for point in outline)
            points.extend(self.tool.get("approach_mm", []))
            points.extend(self.tool.get("feed_mm") or [])
            points.append(self.tool["tip_mm"])
        for marker in spec.get("index_arc", {}).get("points_mm", []):
            points.append(marker)
        fit = points if self.view == "isometric" else None
        if fit is None:
            self.meshes.append((points, [], _WHITE))
        self.components = framed
        self.canvas = RenderCanvas([], self.camera, (0, 0, 1, 1), width=1, height=1)
        # Keep the printable scene large. Verbose source legends must not turn
        # into a second notes column and push the placed geometry off the page.
        self.footer_top = 740
        self.scene_bottom = 620
        # Footer type stays at print size; a longer key or note list grows the footer.
        self.note_lines = self._notes()
        self.legend_rows = self._legend()
        footer_height = 57 + max(
            max(0, len(self.legend_rows) - 1) * 30 + 21,
            max(0, len(self.note_lines) - 1) * 27 + 21,
        )
        self.footer_top = min(self.footer_top, 984 - footer_height)
        self.scene_bottom = min(self.scene_bottom, self.footer_top - 120)
        viewport = (278, 225, 900, self.scene_bottom)
        if self.view in ("plan", "elevation") and (
            any(component.get("code") for component in self.components)
            or any(_role(component) == "pad" for component in self.components)
        ):
            # Leave real exterior key bands even for a vertically tall fixture.
            viewport = (278, 278, 900, 540)
        self.viewport = viewport
        self.canvas = RenderCanvas(self.meshes, self.camera, viewport, fit=fit)
        self.stock_pixels = [self.canvas.project(p) for p in _corners(self.stock)]
        self.position_badges.extend(
            {"label": label, "xy": self.canvas.project(point), "colour": _BLUE}
            for label, point in self.off_window_keys
        )

    def _in_lathe_window(self, z):
        """Whether the jaw-end profile inset draws station ``z``."""
        return self.lathe_window is not None and self.lathe_window[0] <= z <= self.lathe_window[1]

    def _framed(self):
        """Components the view is scaled to. An isometric view frames the stock and the
        holding that touches it, at most 1.5x the stock's largest size: a vise or table
        many times the part's size is cropped, not allowed to shrink the work."""
        if self.view != "isometric" or self.stock is None:
            return list(self.components)
        size = max(self.stock[i + 3] - self.stock[i] for i in range(3))
        pad = 0.25 * size
        frame = [self.stock[i] - pad for i in range(3)] + [
            self.stock[i + 3] + pad for i in range(3)
        ]
        touch = [self.stock[i] - 1.0 for i in range(3)] + [
            self.stock[i + 3] + 1.0 for i in range(3)
        ]
        framed = []
        for component in self.components:
            box = component.get("box_mm")
            if box is None:
                framed.append(component)
                continue
            if any(box[i] > touch[i + 3] or box[i + 3] < touch[i] for i in range(3)):
                continue
            framed.append(
                dict(
                    component,
                    box_mm=[max(box[i], frame[i]) for i in range(3)]
                    + [min(box[i + 3], frame[i + 3]) for i in range(3)],
                    center_mm=[
                        (max(box[i], frame[i]) + min(box[i + 3], frame[i + 3])) / 2
                        for i in range(3)
                    ],
                )
            )
        return framed

    def _notes(self):
        notes = [_plain(note) for note in self.spec.get("notes", [])]
        if self.tool:
            notes.append(
                f"Selected tool: {self.tool['label']} / op {self.tool.get('op', 'not declared')}"
            )
        if self.spec.get("zero_mm") is None:
            notes.append("Z0: not declared")
        if "datums" not in self.spec:
            notes.append("Datums: not declared")
        if self.is_chuck and self.spec.get("stickout_mm") is None:
            notes.append("Stickout: not declared")
        return [line for note in notes for line in _wrap(self.canvas, note, 720, scale=3)]

    def _legend(self):
        rows = []
        kinds = set()
        meanings = (
            ("retained", "RETAINED AFTER SETUP", "stock"),
            ("arriving", "ARRIVING / CUTS UNCONFIRMED", "stock"),
            ("removed", "REMOVED THIS SETUP", "removal"),
            ("holding", "WORKHOLDING", "fixture"),
            ("tool", "TOOL / APPROACH", "tool"),
            ("context", "MACHINE OUTLINE", "context"),
            ("nominal", "FINISHED OUTLINE, THIS SETUP", "nominal"),
        )
        for supplied in self.spec.get("legend", []):
            text = _plain(supplied)
            match = next((m for m in meanings if m[0] in text.lower()), None)
            if match:
                _, label, kind = match
                if kind not in kinds:
                    rows.append((label, kind))
                    kinds.add(kind)
            else:
                rows.extend((line, "text") for line in _wrap(self.canvas, text, 480, scale=3))
        required = [("ARRIVING STOCK", "stock"), ("WORKHOLDING", "fixture")]
        if any(len(mesh) > 3 and mesh[3] for mesh in self.meshes):
            required.append(("REMOVED THIS SETUP", "removal"))
        if self.tool:
            required.append(("TOOL / APPROACH", "tool"))
        if self.view == "lathe" and any(_role(c).startswith("chuck") for c in self.components):
            required.append(("MACHINE OUTLINE", "context"))
        for label, kind in required:
            if kind not in kinds:
                rows.append((label, kind))
                kinds.add(kind)
        if any("pad" in _plain(c.get("label") or c["name"]).lower() for c in self.components):
            rows.append(("PAD BADGES: POSITIONS", "text"))
        if self.nominal and "nominal" not in kinds:
            rows.append(("FINISHED OUTLINE, THIS SETUP", "nominal"))
        return rows

    def render(self):
        self._header()
        self._context()
        if self.nominal:
            self._nominal_overlay(self.canvas.project)
            self.callouts.append(
                _Callout("FINISHED OUTLINE", [self.canvas.project(self.nominal[0][0])], _BLUE)
            )
        self._components()
        self._origin_datums_tool()
        self._measurements()
        for z, small, large in self.shoulders:
            # A step too small to see at print scale is named with both diameters; the
            # jaw-end profile names the steps inside its window beside its own tick.
            if (large - small) * self.canvas.scale >= 3 or self._in_lathe_window(z):
                continue
            point = self.canvas.project((large, 0, z))
            self.callouts.append(_Callout(_shoulder(z, small, large), [point], _INK))
        self._labels()
        if self.position_badges:
            exclusion = None
            if self.view in ("plan", "elevation"):
                pixels = self.stock_pixels + self._component_pixels(self.components)
                pixels.extend(self.canvas.project(p) for line in self.nominal for p in line)
                if pixels:
                    exclusion = _bounds(pixels)
            self._waypoint_badges(
                self.position_badges,
                lambda p: p,
                (278, 205, 900, 593),
                prefix="",
                colour=_FIXTURE,
                exclusion=exclusion,
            )
        self._insets()
        for x, y, label, scale in self.context_labels:
            _text(self.canvas, x, y, label, _MUTED, scale=scale, align="centre", backing=True)
        self._footer()
        self.canvas.assert_text_layout(min_scale=_BODY_SCALE)
        return self.canvas.png()

    def _header(self):
        c = self.canvas
        _text(c, 32, 27, f"SETUP {self.spec['setup_id']}  /  {self.view.upper()} VIEW", scale=4)
        subtitles = {
            "lathe": "SPINDLE Z TO RIGHT  /  RADIAL X UP  /  FULL ARRIVING STOCK",
            "plan": "SETUP X TO RIGHT  /  Y UP  /  VIEW FROM +Z",
            "isometric": "PLACED GEOMETRY IN THE SETUP FRAME",
            "elevation": self.spec.get("view_note", "SETUP Z UP"),
        }
        _text(c, 34, 76, subtitles[self.view], _MUTED)
        _text(c, 1565, 77, "DIMENSIONS IN mm", _MUTED, align="right")
        c.line((32, 112), (1568, 112), _INK, width=2)
        _text(c, 32, 138, "PLACED STOCK + WORKHOLDING", _INK)

    def _component_pixels(self, components):
        return [
            self.canvas.project(p)
            for item in components
            for p in (_corners(item.get("box_mm")) or [item["center_mm"]])
        ]

    def _context(self):
        c = self.canvas
        if self.view == "lathe":
            chuck = [item for item in self.components if _role(item).startswith("chuck")]
            if chuck:
                left, top, _, bottom = _bounds(self._component_pixels(chuck))
                x, y = left - 100, (top + bottom) / 2 - 55
                _outline(c, [(x, y), (x + 94, y), (x + 94, y + 110), (x, y + 110)], dashed=True)
                _outline(
                    c,
                    [(x - 8, y + 110), (x + 98, y + 110), (x + 98, y + 128), (x - 8, y + 128)],
                    dashed=True,
                )
                self.obstacles.append((x - 36, y - 30, x + 130, y + 130))
                self.context_labels.append((x + 47, y - 26, "HEADSTOCK", 3))
            centres = [item for item in self.components if _role(item) in ("centre", "center")]
            if centres:
                # A tailstock is drawn only where a centre actually supports the work.
                _, top, right, bottom = _bounds(self._component_pixels(centres))
                x, y = right + 8, (top + bottom) / 2 - 44
                _outline(
                    c,
                    [(x, y + 20), (x + 20, y), (x + 82, y), (x + 82, y + 88), (x, y + 88)],
                    dashed=True,
                )
                _outline(
                    c,
                    [(x - 4, y + 88), (x + 88, y + 88), (x + 88, y + 106), (x - 4, y + 106)],
                    dashed=True,
                )
                self.obstacles.append((x - 40, y - 30, x + 125, y + 110))
                self.context_labels.append((x + 41, y - 26, "TAILSTOCK", 3))

    def _nominal_overlay(self, project, clip=None, faint=False):
        """Keep dash phase across small tessellated chords of each exact edge."""
        c = self.canvas
        colour = _NOMINAL_FAINT if faint else _BLUE
        for polyline in self.nominal:
            pixels = [project(p) for p in polyline]
            phase = 0.0
            for a, b in zip(pixels, pixels[1:], strict=False):
                length = math.dist(a, b)
                if length == 0:
                    continue
                distance = 0.0
                while distance < length:
                    on = phase < 8
                    run = min(length - distance, (8 if on else 14) - phase)
                    if on and run > 0:
                        start = (
                            a[0] + (b[0] - a[0]) * distance / length,
                            a[1] + (b[1] - a[1]) * distance / length,
                        )
                        end = (
                            a[0] + (b[0] - a[0]) * (distance + run) / length,
                            a[1] + (b[1] - a[1]) * (distance + run) / length,
                        )
                        segment = _clip_segment(start, end, clip) if clip else (start, end)
                        if segment:
                            c.line(*segment, colour, width=2)
                    distance += run
                    phase = (phase + run) % 14

    def _components(self):
        c = self.canvas
        groups = defaultdict(list)
        pads = []
        numbered = {}
        chuck = _plain(self.spec.get("chuck_name") or "CHUCK")
        role_groups = {
            "parallel": "PARALLELS",
            "riser": "RISERS",
            "chuck_jaw": f"{chuck} JAWS",
            "chuck_body": f"{chuck} BODY",
            "centre": "CENTRE",
        }
        if self.spec.get("holding_name"):
            # A dividing head's or rotary table's own solids carry its kind, not a part name.
            role_groups["head"] = _plain(self.spec["holding_name"])
        for component in self.components:
            role = _role(component)
            label = _plain(component.get("label") or component["name"])
            if role == "fixed_jaw":
                fixed = _plain(self.spec.get("fixed_jaw_label") or "FIXED JAW")
                label = fixed if fixed.upper().startswith("FIXED JAW") else "FIXED JAW / " + fixed
            elif role == "moving_jaw":
                label = "MOVING JAW"
            elif role in role_groups:
                label = role_groups[role]
            elif label.upper().startswith(("RAIL REST", "SHIM", "HOLD-DOWN", "HOLD DOWN")):
                label = (
                    next(
                        prefix
                        for prefix in ("RAIL REST", "SHIM", "HOLD-DOWN", "HOLD DOWN")
                        if label.upper().startswith(prefix)
                    )
                    + "S"
                )
            if "pad" in label.lower() and role in ("fixture", "support", "pad"):
                pads.append(component)
                continue
            if component.get("code"):
                # The declared clamp number: the same C/LOC/SUP code as the HOLD text.
                numbered[label] = _plain(component["code"])
            groups[label].append(component)
        for label, components in groups.items():
            points = [c.project(item["center_mm"]) for item in components]
            if label not in numbered:
                self.callouts.append(_Callout(label.upper(), points, _FIXTURE))
                continue
            # Each position carries its code badge; the lane entry is the badge's key.
            self.callouts.append(_Callout(label.upper(), points, _FIXTURE, leader="keyed"))
            for point in points:
                self.position_badges.append({"label": numbered[label], "xy": point})
        if pads:
            for index, component in enumerate(pads, 1):
                point = c.project(component["center_mm"])
                label = _plain(component.get("label") or component["name"]).upper()
                code = label.removeprefix("PAD ").removeprefix("SUPPORT PAD ") or str(index)
                if self.view == "plan" and component.get("box_mm"):
                    left, top, right, bottom = _bounds(self._component_pixels([component]))
                    _outline(
                        c,
                        [(left, top), (right, top), (right, bottom), (left, bottom)],
                        _FIXTURE,
                        width=2,
                        dashed=True,
                    )
                self.position_badges.append({"label": code, "xy": point})
            self.callouts.append(
                _Callout(
                    "SUPPORT PADS", [c.project(pads[0]["center_mm"])], _FIXTURE, leader="keyed"
                )
            )
        if self.stock_pixels:
            left, top, right, _ = _bounds(self.stock_pixels)
            self.callouts.append(_Callout("STOCK", [((left + right) / 2, top)], _INK))

    def _origin_datums_tool(self):
        c = self.canvas
        if self.spec.get("zero_mm") is not None:
            point = c.project(self.spec["zero_mm"])
            c.circle(*point, 10, fill=_WHITE, outline=_BLUE)
            c.line((point[0] - 15, point[1]), (point[0] + 15, point[1]), _BLUE, width=2)
            c.line((point[0], point[1] - 15), (point[0], point[1] + 15), _BLUE, width=2)
            self.callouts.append(_Callout("Z0", [point], _BLUE))
        for datum in self.spec.get("datums", []):
            point = c.project(datum["point_mm"])
            c.circle(*point, 5, fill=_WHITE, outline=_INK)
            c.circle(*point, 2, fill=_INK)
            label = _plain(datum["label"]).upper()
            if datum.get("kind") != "end" and not label.startswith("DATUM "):
                label = "DATUM " + label
            self.callouts.append(_Callout(label, [point]))
        target = self.spec.get("target")
        if target:
            point = c.project(target["point_mm"])
            c.circle(*point, 11, outline=_AMBER)
            c.circle(*point, 8, outline=_AMBER)
            c.circle(*point, 3, fill=_AMBER)
            self.callouts.append(_Callout(_plain(target["label"]), [point], _AMBER))
        arc = self.spec.get("index_arc")
        if arc:
            pixels = [c.project(p) for p in arc["points_mm"]]
            for a, b in zip(pixels, pixels[1:], strict=False):
                c.line(a, b, _BLUE, width=3)
            if len(pixels) > 2:
                c.arrow(pixels[-2], pixels[-1], _BLUE, width=3)
            reference = [c.project(p) for p in arc["reference_mm"]]
            c.line(*reference, _BLUE, width=2, dashed=True)
            self.callouts.append(_Callout(_plain(arc["label"]), [pixels[-1]], _BLUE))
        if self.tool:
            outlines = self.tool.get("outlines_mm") or [self.tool.get("outline_mm", [])]
            for polygon in outlines:
                outline = [c.project(point) for point in polygon]
                if len(outline) >= 3:
                    _outline(c, outline, _GREEN, width=3)
                elif len(outline) == 2:
                    c.line(*outline, _GREEN, width=3)
            approach = self.tool.get("approach_mm", [])
            if len(approach) == 2:
                c.arrow(c.project(approach[0]), c.project(approach[1]), _GREEN, width=3)
            feed = self.tool.get("feed_mm") or []
            if len(feed) == 2:
                a, b = c.project(feed[0]), c.project(feed[1])
                c.arrow(a, b, _GREEN, width=3)
                middle = ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2)
                self.callouts.append(_Callout("FEED", [middle], _GREEN))
            point = c.project(self.tool["tip_mm"])
            c.circle(*point, 4, fill=_GREEN)
            self.callouts.append(_Callout("PRIMARY TOOL", [point], _GREEN))

    def _measurements(self):
        c = self.canvas
        y = 674
        if self.stock is None:
            _text(c, 285, y, "STOCK EXTENTS: NOT DECLARED", _MUTED)
            return
        box = self.stock
        sizes = [box[i + 3] - box[i] for i in range(3)]
        stock_text = f"STOCK BOX: X {_mm(sizes[0])}  /  Y {_mm(sizes[1])}  /  Z {_mm(sizes[2])} mm"
        _text(c, 32, self.footer_top - 36, stock_text)
        axis = (
            2
            if self.view == "lathe"
            else max(range(3), key=lambda index: abs(self.camera[0][index]))
        )
        first, second = list(_centre(box)), list(_centre(box))
        first[axis], second[axis] = box[axis], box[axis + 3]
        a, b = c.project(first), c.project(second)
        c.line(a, (a[0], y), _MUTED, width=2, dashed=True)
        c.line(b, (b[0], y), _MUTED, width=2, dashed=True)
        label = f"STOCK {'XYZ'[axis]} {_mm(sizes[axis])} mm"
        _dimension(c, (a[0], y), (b[0], y), label)
        self.dimensions[label] = ((a[0], y), (b[0], y))
        jaw = self.spec.get("jaw_front_z_mm")
        jaw_marker = None
        if jaw is not None:
            plane = [
                (box[0], box[1], jaw),
                (box[3], box[1], jaw),
                (box[3], box[4], jaw),
                (box[0], box[4], jaw),
            ]
            pixels = [c.project(p) for p in plane]
            jaw_marker = self.jaw_marker = pixels[0]
            if self.view == "lathe":
                x = jaw_marker[0]
                _, top, _, bottom = _bounds(self.stock_pixels)
                c.line((x, top - 24), (x, bottom + 24), _BLUE, width=2, dashed=True)
                anchor = (x, top - 24)
            else:
                _outline(c, pixels, _BLUE, width=2, dashed=True)
                anchor = jaw_marker
            self.callouts.append(_Callout(f"JAW FRONT Z {_mm(jaw)} mm", [anchor], _BLUE))
        stickout = self.spec.get("stickout_mm")
        if stickout is not None:
            label = f"STICKOUT {_mm(stickout)} mm"
            if jaw_marker is not None and self.view == "lathe":
                # The declared distance runs from the jaw-front marker itself, on its own
                # row, never from the stock-length extension line.
                a = jaw_marker
                b = c.project((box[0], box[1], box[5]))
                dim_y = 622
                c.line(a, (a[0], dim_y), _BLUE, width=2, dashed=True)
                c.line(b, (b[0], dim_y), _BLUE, width=2, dashed=True)
                _dimension(c, (a[0], dim_y), (b[0], dim_y), label, _BLUE)
                self.dimensions[label] = ((a[0], dim_y), (b[0], dim_y))
            else:
                x = 32 + c.text_width(_plain(stock_text), scale=_BODY_SCALE) + 48
                _text(c, x, self.footer_top - 36, label, _BLUE)

    def _labels(self):
        """Two lanes of print-size keys. Type never shrinks: lanes rebalance, then tighten
        their leading; a leader never runs along the axis through another callout."""
        c = self.canvas
        lane_specs = ((32, 214, 249), (928, 210, 916))
        limit = self.footer_top - 64
        anchors = [(callout, point) for callout in self.callouts for point in callout.points]
        wrapped = {
            (id(item), side): _wrap(c, item.label, lane_specs[side][1], scale=3)
            for item in self.callouts
            for side in (0, 1)
        }

        def blocked(item, point, side):
            # A horizontal run to this lane that passes another callout's point reads as
            # that point's leader (two ends of a bar on one axis line).
            elbow_x = lane_specs[side][2] + (14 if side == 0 else -14)
            low, high = sorted((point[0], elbow_x))
            return any(
                abs(other[1] - point[1]) < 6
                and low < other[0] < high
                and abs(other[0] - point[0]) > 1
                for owner, other in anchors
                if owner is not item
            )

        def pack(items, side, pitch, gap):
            x, width, _ = lane_specs[side]
            rows, row_y = [], 202
            for item in items:
                lines = wrapped[(id(item), side)]
                span = max(c.text_width(line, scale=3) for line in lines) + 8
                left, right = (
                    (x - 4, x - 4 + span) if side == 0 else (x + width + 4 - span, x + width + 4)
                )
                height = len(lines) * pitch + 6
                for o_left, top, o_right, bottom in sorted(self.obstacles, key=lambda b: b[1]):
                    if (
                        left < o_right
                        and right > o_left
                        and row_y < bottom
                        and row_y + height > top
                    ):
                        row_y = bottom + 10
                rows.append(row_y)
                row_y += height + gap
            return rows, row_y - gap

        def ordered(items):
            return sorted(items, key=lambda item: item.points[0][1])

        def overflow(items, side):
            return pack(ordered(items), side, 27, 5)[1] - limit

        lanes = [[], []]
        for callout in self.callouts:
            lanes[0 if callout.points[0][0] < 590 else 1].append(callout)
        for _ in self.callouts:
            source = max((0, 1), key=lambda side: overflow(lanes[side], side))
            if overflow(lanes[source], source) <= 0:
                break
            target = 1 - source
            candidates = [
                item
                for item in lanes[source]
                if (
                    item.leader == "keyed"
                    or not any(blocked(item, point, target) for point in item.points)
                )
                and overflow(lanes[target] + [item], target) <= 0
            ]
            if not candidates:
                break
            moved = min(
                candidates,
                key=lambda item: (item.leader != "keyed", abs(item.points[0][0] - 590)),
            )
            lanes[source].remove(moved)
            lanes[target].append(moved)
        for side, items in enumerate(lanes):
            callouts = ordered(items)
            x, width, edge = lane_specs[side]
            # Tighter leading before closer rows; the glyphs stay at print size.
            pitch, floor = next(
                (
                    (pitch, floor)
                    for pitch, floor in ((27, 5), (25, 5), (25, 0))
                    if pack(callouts, side, pitch, floor)[1] <= limit
                ),
                (25, 0),
            )
            lo, hi = float(floor), 60.0
            for _ in range(12):
                gap = (lo + hi) / 2
                if pack(callouts, side, pitch, gap)[1] <= limit:
                    lo = gap
                else:
                    hi = gap
            rows, _ = pack(callouts, side, pitch, lo)
            for item, row_y in zip(callouts, rows, strict=True):
                lines = wrapped[(id(item), side)]
                target_y = row_y + ((len(lines) - 1) * pitch + 21) / 2
                for point in item.points if item.leader == "line" else []:
                    end = (edge, target_y)
                    path = [point, end]
                    if not blocked(item, point, side):
                        path = [point, (edge + (14 if side == 0 else -14), point[1]), end]
                    for a, b in zip(path, path[1:], strict=False):
                        c.line(a, b, item.colour, width=2)
                    c.circle(*point, 3, fill=item.colour)
                    self.leaders.append((item.label, path))
                for index, line in enumerate(lines):
                    _text(
                        c,
                        x + width if side else x,
                        row_y + index * pitch,
                        line,
                        item.colour,
                        scale=3,
                        align="right" if side else "left",
                        backing=True,
                    )

    def _insets(self):
        c = self.canvas
        left, right = 1174, 1568
        c.line((1157, 134), (1157, self.footer_top - 17), _RULE, width=2)
        profiles = self.spec.get("lathe_profiles", []) if self.view == "lathe" else []
        if profiles or (
            self.view == "lathe"
            and (
                self.spec.get("axial_paths")
                or any("xz" in p for p in self.spec.get("waypoints", []))
            )
        ):
            top = self._lathe_detail(left, right, profiles) + 24
            if self.spec.get("paths") or any("xy" in p for p in self.spec.get("waypoints", [])):
                self._path_inset(left, right, top, self.footer_top - 70)
        else:
            self._path_inset(left, right, 142, self.footer_top - 70)
        if self.spec.get("preload") == "counterclockwise":
            center = (left + 17, self.footer_top - 37)
            arc = [
                (center[0] + 13 * math.cos(a), center[1] - 13 * math.sin(a))
                for a in (i * math.pi / 12 for i in range(2, 23))
            ]
            for a, b in zip(arc, arc[1:], strict=False):
                c.line(a, b, _FIXTURE, width=2)
            c.arrow(arc[-2], arc[-1], _FIXTURE, width=2)
            _text(c, left + 42, center[1] - 10, "CCW PRELOAD / +Z", _FIXTURE, scale=3)

    def _lathe_detail(self, left, right, profiles):
        c = self.canvas
        _text(c, left, 140, "JAW-END PROFILE")
        _text(c, left, 169, "Z RIGHT / RADIAL UP", _MUTED)
        axial = self.spec.get("axial_paths", [])
        display = {str(path["op"]): path.get("x_display", "radius") for path in axial}

        def radial(point, convention):
            return (point[0] / 2 if convention == "diameter" else point[0], point[1])

        paths = [
            (path, [radial(p, path.get("x_display", "radius")) for p in path["xz"]])
            for path in axial
        ]
        waypoints = [
            {
                "label": p["label"],
                "xy": radial(p["xz"], p.get("x_display", display.get(str(p.get("op")), "radius"))),
            }
            for p in self.spec.get("waypoints", [])
            if "xz" in p
        ]
        points = [p for profile in profiles for line in profile["lines"] for p in line]
        if self.lathe_window:
            zmin, zmax = self.lathe_window
            slab = (-math.inf, zmin, math.inf, zmax)
            for _, path in paths:
                for a, b in zip(path, path[1:], strict=False):
                    segment = _clip_segment(a, b, slab)
                    if segment:
                        points.extend(segment)
            waypoints = [p for p in waypoints if zmin <= p["xy"][1] <= zmax]
        else:
            points.extend(p for _, path in paths for p in path)
        points.extend(p["xy"] for p in waypoints)
        if not points:
            _text(c, left, 208, "PROFILE NOT DECLARED", _MUTED)
            return 239
        if not self.lathe_window:
            zmin, zmax = min(p[1] for p in points), max(p[1] for p in points)
        rmin, rmax = min(p[0] for p in points), max(p[0] for p in points)
        window_label = f"Z {_mm(zmin)} TO {_mm(zmax)} MM"
        _text(c, left, 198, window_label, _MUTED)
        scale = min((right - left - 134) / max(zmax - zmin, 1e-9), 234 / max(rmax - rmin, 1e-9))
        cx, cy = (left + right) / 2, 355
        # A contour much smaller than the window gets its own enlarged local detail.
        local = None
        contour = [p for _, path in paths for p in path] + [p["xy"] for p in waypoints]
        if contour and (rmax - rmin) * scale <= 80:
            bounds = _bounds([(p[1], p[0]) for p in contour])
            span = max(bounds[2] - bounds[0], bounds[3] - bounds[1], 1e-9)
            if span * scale < 150:
                margin = 0.15 * span
                local = (
                    bounds[0] - margin,
                    min(bounds[1], 0) - margin,
                    bounds[2] + margin,
                    bounds[3] + margin,
                )
                cy = 236 + (rmax - rmin) * scale / 2

        def project(point):
            return (
                cx + (point[1] - (zmin + zmax) / 2) * scale,
                cy - (point[0] - (rmin + rmax) / 2) * scale,
            )

        closed = [
            (profile, line)
            for profile in profiles
            for line in profile["lines"]
            if len(line) >= 4 and line[0] == line[-1]
        ]
        for profile, line in closed:
            if profile["label"] == "arriving stock":
                c.polygon([project(p) for p in line], _AMBER_LIGHT)
        for profile, line in closed:
            if profile["label"] == "after this setup":
                c.polygon([project(p) for p in line], _WHITE)
        if rmin <= 0 <= rmax:
            c.line(project((0, zmin)), project((0, zmax)), _RULE, width=2, dashed=True)
        row = 510
        for profile in profiles:
            colour = tuple(profile.get("colour", _INK))
            for line in profile["lines"]:
                for a, b in zip(line, line[1:], strict=False):
                    c.line(
                        project(a),
                        project(b),
                        colour,
                        width=3,
                        dashed=profile["label"] == "arriving stock",
                    )
            c.line(
                (left, row + 10),
                (left + 25, row + 10),
                colour,
                width=3,
                dashed=profile["label"] == "arriving stock",
            )
            for line in _wrap(c, profile["label"].upper(), right - left - 34, scale=3):
                _text(c, left + 34, row, line, colour)
                row += 30
        for z, small, large in self.shoulders:
            step = large - small
            # The main view names no step inside this window; every step either view
            # cannot show is named here.
            if not zmin <= z <= zmax or min(step * scale, step * self.canvas.scale) >= 3:
                continue
            point = project((large, z))
            c.line((point[0], point[1] - 12), (point[0], point[1] + 12), _INK, width=2)
            for line in _wrap(c, _shoulder(z, small, large), right - left, scale=3):
                _text(c, left, row, line, _INK)
                row += 30
        if local is not None:
            zlo, rlo, zhi, rhi = local
            box = (left, cy + (rmax - rmin) * scale / 2 + 22, right, 493)
            frame = [project((rlo, zlo)), project((rhi, zhi))]
            _outline(
                c,
                [
                    (frame[0][0], frame[1][1]),
                    (frame[1][0], frame[1][1]),
                    (frame[1][0], frame[0][1]),
                    (frame[0][0], frame[0][1]),
                ],
                _GREEN,
                width=1,
                dashed=True,
            )
            plot = (box[0] + 8, box[1] + 30, box[2] - 8, box[3] - 6)
            detail = min(
                (plot[2] - plot[0] - 40) / (zhi - zlo),
                max(20, plot[3] - plot[1] - 2 * 31) / (rhi - rlo),
            )
            centre = ((plot[0] + plot[2]) / 2, (plot[1] + plot[3]) / 2)

            def enlarged(point):
                return (
                    centre[0] + (point[1] - (zlo + zhi) / 2) * detail,
                    centre[1] - (point[0] - (rlo + rhi) / 2) * detail,
                )

            _outline(
                c,
                [(box[0], box[1]), (box[2], box[1]), (box[2], box[3]), (box[0], box[3])],
                _RULE,
                width=1,
            )
            _text(c, box[0] + 8, box[1] + 6, f"DETAIL  x{_mm(detail / scale)}", _GREEN)
            clip = (box[0] + 1, box[1] + 1, box[2] - 1, box[3] - 1)
            for profile in profiles:
                colour = tuple(profile.get("colour", _INK))
                for line in profile["lines"]:
                    for a, b in zip(line, line[1:], strict=False):
                        segment = _clip_segment(enlarged(a), enlarged(b), clip)
                        if segment:
                            c.line(
                                *segment,
                                colour,
                                width=2,
                                dashed=profile["label"] == "arriving stock",
                            )
            for _, points in paths:
                self._ordered_path([enlarged(p) for p in points], _GREEN, clip=clip)
            self._waypoint_badges(waypoints, enlarged, plot, perimeter=True)
        for path, points in paths:
            window = (project((0, zmin))[0], 228, project((0, zmax))[0], 493)
            if local is None:
                self._ordered_path([project(p) for p in points], _GREEN, clip=window)
            else:
                pixels = [project(p) for p in points]
                for a, b in zip(pixels, pixels[1:], strict=False):
                    segment = _clip_segment(a, b, window)
                    if segment:
                        c.line(*segment, _GREEN, width=3)
            for line in _wrap(c, f"OP {path['op']} SURFACE", right - left - 34, scale=3):
                c.line((left, row + 10), (left + 25, row + 10), _GREEN, width=3)
                _text(c, left + 34, row, line, _GREEN)
                row += 30
        if local is None:
            self._waypoint_badges(waypoints, project, (left, 205, right, 493))
        if paths:
            _text(c, left, row, "ARROWS: POINT ORDER", _MUTED)
            row += 30
        if closed:
            for line in _wrap(c, "TINT: PROFILE DIFFERENCE", right - left, scale=3):
                _text(c, left, row, line, _AMBER)
                row += 30
        if self.off_window_keys:
            for line in _wrap(c, "OFF-WINDOW P KEYS: FULL VIEW", right - left, scale=3):
                _text(c, left, row, line, _MUTED)
                row += 30
        return row

    def _path_inset(self, left, right, top, bottom):
        c = self.canvas
        paths = self.spec.get("paths", [])
        waypoints = [p for p in self.spec.get("waypoints", []) if "xy" in p]
        points = [point for path in paths for point in path["xy"]]
        points.extend(item["xy"] for item in waypoints)
        if not points:
            return
        _text(c, left, top, "PROFILE SKETCH / XY")
        content_top = top + 40
        ops = list(dict.fromkeys(str(p.get("op", "")) for p in paths + waypoints))
        if len(ops) > 1:
            self._operation_panels(left, right, content_top, bottom - 34, ops, paths, waypoints)
            _text(c, left, bottom - 21, "ARROWS: POINT ORDER", _MUTED)
            return
        xmin, ymin, xmax, ymax = _bounds(points)
        ops = list(dict.fromkeys(_plain(path.get("op", "")) for path in paths))
        key_lines = [(op, line) for op in ops for line in _wrap(c, op, right - left - 36, scale=3)]
        plot_top, plot_bottom = content_top + 14, bottom - 40 - 30 * len(key_lines)
        scale = min(
            (right - left - 74) / max(xmax - xmin, 1e-9),
            max(50, plot_bottom - plot_top - 28) / max(ymax - ymin, 1e-9),
        )
        cx, cy = (left + right) / 2, (plot_top + plot_bottom) / 2

        def project(point):
            return (
                cx + (point[0] - (xmin + xmax) / 2) * scale,
                cy - (point[1] - (ymin + ymax) / 2) * scale,
            )

        if self.nominal:
            self._nominal_overlay(
                lambda p: project(p[:2]), (left, plot_top, right, plot_bottom), faint=True
            )
        palette = (_BLUE, _GREEN, _AMBER, (113, 65, 137))
        colours = {op: palette[index % len(palette)] for index, op in enumerate(ops)}
        labels = []
        for op in ops:
            op_paths = [path for path in paths if _plain(path.get("op", "")) == op]
            for path in self._raster_band(op_paths, project, colours[op], labels):
                self._ordered_path([project(point) for point in path["xy"]], colours[op])
        self._waypoint_badges(waypoints + labels, project, (left, plot_top, right, plot_bottom))
        row = plot_bottom + 18
        for op, line in key_lines:
            c.line((left, row + 10), (left + 23, row + 10), colours[op], width=3)
            _text(c, left + 32, row, line, colours[op])
            row += 30
        _text(c, left, bottom - 22, "ARROWS: POINT ORDER", _MUTED)

    def _operation_panels(self, left, right, top, bottom, ops, paths, waypoints):
        """Separate authored operations, not every raster pass or curve record."""
        c = self.canvas
        columns = 2 if len(ops) > 1 else 1
        rows = math.ceil(len(ops) / columns)
        width = (right - left - 12 * (columns - 1)) / columns
        height = (bottom - top - 12 * (rows - 1)) / rows
        palette = (_BLUE, _GREEN, _AMBER, (113, 65, 137))
        for index, op in enumerate(ops):
            x = left + (index % columns) * (width + 12)
            y = top + (index // columns) * (height + 12)
            colour = palette[index % len(palette)]
            _outline(
                c,
                [(x, y), (x + width, y), (x + width, y + height), (x, y + height)],
                _RULE,
                width=1,
            )
            _text(c, x + 8, y + 5, f"OP {op}", colour)
            op_paths = [p for p in paths if str(p.get("op", "")) == op]
            op_waypoints = [p for p in waypoints if str(p.get("op", "")) == op]
            points = [p for path in op_paths for p in path["xy"]]
            points.extend(p["xy"] for p in op_waypoints)
            if not points:
                continue
            bounds = _bounds(points)
            xmin, ymin, xmax, ymax = bounds
            span_x, span_y = xmax - xmin, ymax - ymin
            plot_top, plot_bottom = y + 66, y + height - 44
            factor = min(
                (width - 72) / max(span_x, 1e-9),
                max(12, plot_bottom - plot_top) / max(span_y, 1e-9),
            )
            factor_y = factor
            badge_top = y + 31
            exclusion = None
            # Keep the dense six-panel grid unchanged. Shallow wider panels can
            # instead use a declared, unequal graphic scale and exterior P keys.
            if rows <= 2 and 0 < span_y * factor < 24 and span_x * factor >= 60:
                key_widths = [_badge_width(c, _plain(p["label"])) for p in op_waypoints]
                # Either band may have to hold every key: a shallow arc's points can all
                # sit on one side of it.
                key_rows = max(1, _rows_for(key_widths, width - 12))
                exaggeration_lines = (
                    1 if c.text_width("Y EXAG x00.00", scale=3) <= width - 16 else 2
                )
                badge_top = y + 35 + 27 * exaggeration_lines
                plot_top = badge_top + 41 * key_rows
                plot_bottom = y + height - 6 - 41 * key_rows
                if plot_bottom - plot_top >= 24:
                    # Limit graphic distortion even when the key bands leave ample space.
                    factor_y = min((plot_bottom - plot_top) / span_y, 4 * factor)
                    exaggeration = f"Y EXAG x{_mm(factor_y / factor)}"
                    for index, line in enumerate(_wrap(c, exaggeration, width - 16, scale=3)):
                        _text(c, x + 8, y + 31 + 27 * index, line, _MUTED)
                    exclusion = (x + 7, plot_top, x + width - 7, plot_bottom)
                else:
                    plot_top, plot_bottom = y + 66, y + height - 44
                    badge_top = y + 31
            cx, cy = x + width / 2, (plot_top + plot_bottom) / 2
            project = _xy_projector(bounds, (cx, cy), (factor, factor_y))

            if self.nominal:
                self._nominal_overlay(
                    project, (x + 7, plot_top, x + width - 7, plot_bottom), faint=True
                )
            labels = []
            op_paths = self._raster_band(op_paths, project, colour, labels)
            direction_keys = {0, len(op_paths) // 2, len(op_paths) - 1}
            for path_index, path in enumerate(op_paths):
                directed = path.get("directed") is True
                self._ordered_path(
                    [project(p) for p in path["xy"]],
                    colour,
                    width=2,
                    arrows=directed and path_index in direction_keys,
                )
            self._waypoint_badges(
                op_waypoints + labels,
                project,
                (x + 6, badge_top, x + width - 6, y + height - 6),
                colour=colour,
                perimeter=True,
                exclusion=exclusion,
            )

    def _raster_band(self, paths, project, colour, labels):
        """Draw ordinary rasters as a band, but keep-out rasters as independent lines.

        Sparse endpoint labels use the table's independent PASS 1 ... PASS n numbers;
        a filled band must never claim that the clearance between split passes is swept.
        Return non-raster paths for the caller to draw separately.
        """
        c = self.canvas
        raster = sorted((p for p in paths if p.get("raster")), key=lambda p: p["raster"]["pass"])
        if not raster:
            return paths
        first, last = raster[0], raster[-1]
        if len(raster) > 2 and not any(path["raster"].get("keep_out") for path in raster):
            f0, f1 = project(first["xy"][0]), project(first["xy"][-1])
            l0, l1 = project(last["xy"][0]), project(last["xy"][-1])
            same = (f1[0] - f0[0]) * (l1[0] - l0[0]) + (f1[1] - f0[1]) * (l1[1] - l0[1]) >= 0
            tint = tuple(int(255 - (255 - channel) * 0.22) for channel in colour)
            c.polygon([f0, f1, l1, l0] if same else [f0, f1, l0, l1], tint)
            shown = [first, last]
        else:
            shown = raster
        for path in shown:
            c.line(project(path["xy"][0]), project(path["xy"][-1]), colour, width=3)
        for path in (first, last) if last is not first else (first,):
            a, b = path["xy"][0], path["xy"][-1]
            middle = ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2)
            labels.append({"label": f"PASS {path['raster']['pass']}", "xy": middle})
        return [p for p in paths if not p.get("raster")]

    def _ordered_path(self, pixels, colour, width=3, arrows=True, clip=None):
        """Space direction keys by travelled distance, not by tessellation chords."""
        c = self.canvas
        runs = []
        previous = None
        for a, b in zip(pixels, pixels[1:], strict=False):
            segment = _clip_segment(a, b, clip) if clip else (a, b)
            if segment is None:
                previous = None
                continue
            a, b = segment
            length = math.dist(a, b)
            if length <= 1e-9:
                continue
            c.line(a, b, colour, width=width)
            if not arrows:
                continue
            if previous is None or math.dist(previous, a) > 1e-6:
                runs.append([])
            runs[-1].append((a, b, length))
            previous = b

        def point_at(segments, distance):
            for a, b, length in segments:
                if distance <= length:
                    fraction = distance / length
                    return (
                        a[0] + (b[0] - a[0]) * fraction,
                        a[1] + (b[1] - a[1]) * fraction,
                    )
                distance -= length
            return segments[-1][1]

        for run in runs:
            length = sum(segment[2] for segment in run)
            if length < 14:
                continue
            count = max(1, min(3, int(length / 36)))
            half_span = min(9, length / (2 * count))
            for index in range(count):
                distance = (index + 0.5) * length / count
                tail = point_at(run, distance - half_span)
                tip = point_at(run, distance + half_span)
                c.arrow(tail, tip, colour, width=width)

    def _waypoint_badges(
        self,
        waypoints,
        project,
        plot,
        prefix="P",
        colour=_BLUE,
        perimeter=False,
        exclusion=None,
    ):
        """Pack disjoint print-size cells, optionally wholly above/below projected geometry;
        returns [(label, badge centre, point)] in pixels."""
        if not waypoints:
            return []
        c = self.canvas
        left, top, right, bottom = plot
        labels = [_plain(item["label"]) for item in waypoints]
        labels = [
            prefix + label if prefix and not label.upper().startswith(prefix) else label
            for label in labels
        ]
        points = [project(item["xy"]) for item in waypoints]
        if exclusion is not None:
            available = _band_cells(
                points, [_badge_width(c, label) for label in labels], plot, exclusion
            )
            cells = list(range(len(points)))
        else:
            available, cells = self._grid_cells(points, labels, plot, perimeter)
        placed = [
            (available[cell], label, point, item.get("colour", colour))
            for item, label, point, cell in zip(waypoints, labels, points, cells, strict=True)
        ]
        for badge, label, point, point_colour in placed:
            c.line(point, badge, _MUTED, width=2)
            c.circle(*point, 3, fill=point_colour)
            self.leaders.append((label, [point, badge]))
        for badge, label, _, badge_colour in placed:
            _badge(c, badge, label, badge_colour)
        return [(label, badge, point) for badge, label, point, _ in placed]

    def _grid_cells(self, points, labels, plot, perimeter):
        """Evenly spread cells and each point's cell (least leader length, no grazing)."""
        c = self.canvas
        left, top, right, bottom = plot
        span_x, span_y = right - left, bottom - top
        cell_width = max(_badge_width(c, label) for label in labels)
        cell_height = 33
        columns = max(1, int((span_x + 8) / (cell_width + 8)))
        if perimeter:
            columns = min(columns, math.ceil(math.sqrt(len(labels))))
        required_rows = math.ceil(len(labels) / columns)
        rows = (
            max(required_rows, 2 if 2 * cell_height + 8 <= span_y else 1)
            if perimeter
            else max(required_rows, int((span_y + 8) / (cell_height + 8)))
        )
        ys = (
            [top + cell_height / 2 + i * (span_y - cell_height) / (rows - 1) for i in range(rows)]
            if rows > 1
            else [(top + bottom) / 2]
        )
        xs = (
            [
                left + cell_width / 2 + i * (span_x - cell_width) / (columns - 1)
                for i in range(columns)
            ]
            if columns > 1
            else [(left + right) / 2]
        )
        available = [(x, y) for y in ys for x in xs]
        if perimeter:
            # Each badge goes to a cell on its point's own side of the geometry (an arc's
            # low apex keys below it); straight leaders of least total length never cross.
            middle = (min(p[1] for p in points) + max(p[1] for p in points)) / 2
            band = 0.1 * (max(p[1] for p in points) - min(p[1] for p in points))

            def cost(index, cell):
                point = points[index]
                side = 0 if abs(point[1] - middle) <= band else (1 if point[1] > middle else -1)
                wrong = side and (1 if cell[1] > middle else -1) != side
                return math.dist(cell, point) + (10000 if wrong else 0) + passing(index, cell)
        else:

            def cost(index, cell):
                point = points[index]
                target = (point[0], point[1] - cell_height / 2 - 12)
                return math.dist(cell, target) + passing(index, cell)

        def passing(index, cell):
            # A leader that grazes another waypoint reads as attached to it.
            return 1000 * sum(
                _segment_distance(other, points[index], cell) < 9
                for other_index, other in enumerate(points)
                if other_index != index and math.dist(other, points[index]) > 1
            )

        return available, _match(len(points), available, cost)

    def _footer(self):
        c = self.canvas
        c.line((32, self.footer_top), (1568, self.footer_top), _INK, width=2)
        self._triad(112, self.footer_top + 139)
        _text(c, 273, self.footer_top + 23, "KEY")
        legend_start = self.footer_top + 57
        for index, (label, kind) in enumerate(self.legend_rows):
            y = legend_start + index * 30
            if kind == "stock":
                c.rect(274, y + 2, 27, 18, (160, 174, 184), outline=_INK)
            elif kind == "fixture":
                c.rect(274, y + 2, 27, 18, _FIXTURE, outline=_INK)
            elif kind == "removal":
                c.rect(274, y + 2, 27, 18, _AMBER_LIGHT, outline=_AMBER)
                for dx in (0, 7, 14, 21):
                    c.line((276 + dx, y + 17), (282 + dx, y + 6), _AMBER, width=2)
            elif kind == "tool":
                c.arrow((274, y + 10), (301, y + 10), _GREEN, width=3)
            elif kind == "context":
                c.line((274, y + 10), (301, y + 10), _MUTED, width=2, dashed=True)
            elif kind == "nominal":
                c.line((274, y + 10), (301, y + 10), _BLUE, width=2, dashed=True)
            _text(c, 318, y, label, _MUTED if kind == "text" else _INK)
        _text(c, 840, self.footer_top + 23, "SETUP NOTES")
        note_start = self.footer_top + 57
        for index, line in enumerate(self.note_lines):
            _text(c, 840, note_start + index * 27, line, _MUTED)

    def _triad(self, x, y):
        c = self.canvas
        _text(c, 32, self.footer_top + 23, "SETUP AXES")
        right, up, toward = self.camera
        normal_axis = None
        for index, label in enumerate("XYZ"):
            dx, dy = right[index] * 61, -up[index] * 61
            colour = _AXIS_COLOURS[index]
            if math.hypot(dx, dy) < 1e-9:
                normal_axis = index
                c.circle(x, y, 8, fill=_WHITE, outline=colour)
                if toward[index] > 0:
                    c.circle(x, y, 3, fill=colour)
                else:
                    c.line((x - 5, y - 5), (x + 5, y + 5), colour, width=2)
                    c.line((x - 5, y + 5), (x + 5, y - 5), colour, width=2)
                _text(c, x - 29, y + 17, label, colour)
            else:
                end = (x + dx, y + dy)
                c.arrow((x, y), end, colour, width=3)
                _text(
                    c,
                    end[0] + (7 if dx >= 0 else -17),
                    end[1] + (4 if dy >= 0 else -17),
                    label,
                    colour,
                )
        if normal_axis is not None:
            direction = "TOWARD" if toward[normal_axis] > 0 else "AWAY"
            _text(c, 32, self.footer_top + 211, f"{'XYZ'[normal_axis]} {direction}", _MUTED)
        else:
            c.circle(37, self.footer_top + 218, 6, fill=_WHITE, outline=_MUTED)
            c.circle(37, self.footer_top + 218, 2, fill=_MUTED)
            _text(c, 49, self.footer_top + 211, "VIEW NORMAL", _MUTED)


def render_diagram(meshes, spec):
    """Return a 1600 x 1000 setup PNG without inventing physical dimensions.

    ``meshes`` contain numeric setup-frame XYZ triples, triangle index triples,
    RGB and optionally a removal-hatch flag. ``spec`` is the kernel's plain JSON
    diagram record; optional ``lathe_profiles`` contain exact [radius, Z] lines.
    """
    return _Diagram(meshes, spec).render()
