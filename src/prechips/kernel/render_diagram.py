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
# Two point keys closer than two badge cells cannot both sit beside their points.
_KEY_ROOM_PX = 66
# Height of a lathe window shrunk to orientation so its crowded contour's detail has room.
_ORIENTATION_PX = 70
# A setup picture drawing the stock's narrower side under this many pixels shows it small
# beside its holding; a holding detail is added when it draws that side at least
# ``_DETAIL_GAIN`` times larger.
_DETAIL_MIN_PX = 200
_DETAIL_GAIN = 1.5
# A long plan-view work's detail is split into at most this many bands along its length.
_DETAIL_TILES = 2
# Contact outlines in the holding detail.
_CONTACT = (178, 34, 34)
# Contact points within this many mm of one setup-axis plane lie on it.
_PLANE_MM = 1e-3
# The detail's view of a plan setup: from the long side, raised this far, so the contact
# heights a plan view cannot show are seen.
_DETAIL_RISE_DEG = 30


@dataclass
class _Callout:
    label: str
    points: list
    colour: tuple = _INK
    # "line": a leader from the lane to the point; "keyed": the point carries its own
    # position badge, so the lane entry is the badge's key and draws no leader.
    leader: str = "line"
    # Mesh tags of the drawn solids the label names: its leader must end on one of them.
    targets: tuple = ()


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


def _is_pad(component, label):
    return "pad" in label.lower() and _role(component) in ("fixture", "support", "pad")


def _pad_code(component, index):
    label = _plain(component.get("label") or component["name"]).upper()
    return label.removeprefix("PAD ").removeprefix("SUPPORT PAD ") or str(index)


def _dot3(a, b):
    return sum(x * y for x, y in zip(a, b, strict=True))


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


def _keys_crowd(points, scale):
    """Whether two distinct points ``scale`` px/mm apart crowd their keys together."""
    return any(
        0 < math.dist(a, b) * scale < _KEY_ROOM_PX
        for index, a in enumerate(points)
        for b in points[index + 1 :]
    )


def _dashed(canvas, polylines, project, colour, clip=None):
    """Dashed polylines that keep dash phase across small tessellated chords of an edge."""
    for polyline in polylines:
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
                        canvas.line(*segment, colour, width=2)
                distance += run
                phase = (phase + run) % 14


def _visible(canvas, viewport):
    """Visible pixels per drawn-solid tag inside ``viewport``."""
    owned = defaultdict(list)
    left, top, right, bottom = (int(v) for v in viewport)
    tags, owner, width = canvas.tags, canvas.owner, canvas.width
    for y in range(max(0, top), min(canvas.height, bottom + 1)):
        row = y * width
        for x in range(max(0, left), min(width, right + 1)):
            index = owner[row + x]
            if index >= 0 and tags[index] is not None:
                owned[tags[index]].append((x, y))
    return owned


def _tag_at(canvas, x, y):
    x, y = math.floor(x), math.floor(y)
    if not (0 <= x < canvas.width and 0 <= y < canvas.height):
        return None
    index = canvas.owner[y * canvas.width + x]
    return canvas.tags[index] if index >= 0 else None


def _lands_on(canvas, point, targets):
    """Whether a leader ending at ``point`` ends on a visible pixel of a named solid."""
    return _tag_at(canvas, *point) in targets


def _anchor_on(canvas, owned, targets, near, inset=4):
    """The visible pixel of a named solid nearest ``near``, preferring one ``inset`` pixels
    inside its silhouette so the leader dot sits wholly on it; None when it is hidden."""
    pixels = [pixel for tag in targets for pixel in owned.get(tag, ())]
    pixels.sort(key=lambda p: (p[0] + 0.5 - near[0]) ** 2 + (p[1] + 0.5 - near[1]) ** 2)
    steps = ((inset, 0), (-inset, 0), (0, inset), (0, -inset))
    for x, y in pixels:
        if all(_tag_at(canvas, x + dx, y + dy) in targets for dx, dy in steps):
            return (x + 0.5, y + 0.5)
    return (pixels[0][0] + 0.5, pixels[0][1] + 0.5) if pixels else None


def _hull(points):
    """The convex hull of pixel points, in order around it (monotone chain)."""
    points = sorted(set(points))
    if len(points) <= 2:
        return points

    def turn(o, a, b):
        return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])

    lower, upper = [], []
    for point in points:
        while len(lower) >= 2 and turn(lower[-2], lower[-1], point) <= 0:
            lower.pop()
        lower.append(point)
    for point in reversed(points):
        while len(upper) >= 2 and turn(upper[-2], upper[-1], point) <= 0:
            upper.pop()
        upper.append(point)
    return lower[:-1] + upper[:-1]


def _nearest_on_outline(outline, point):
    """The point of a closed pixel polygon's edges nearest ``point``."""
    best = None
    for a, b in zip(outline, outline[1:] + outline[:1], strict=True):
        dx, dy = b[0] - a[0], b[1] - a[1]
        length = dx * dx + dy * dy
        t = 0.0 if not length else ((point[0] - a[0]) * dx + (point[1] - a[1]) * dy) / length
        t = min(1.0, max(0.0, t))
        candidate = (a[0] + t * dx, a[1] + t * dy)
        if best is None or math.dist(candidate, point) < math.dist(best, point):
            best = candidate
    return best


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
    grows_to_fit = False

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
        # Badge leaders to a hidden solid's dashed outline, never to what lies in front of it.
        self.hidden_leaders = []
        # Operator-facing lines for what the picture could not show truthfully.
        self.render_debts = []
        self._owned = None
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
        # Label lanes: the first row's top and the last row's bottom limit; each side's
        # (text left, text width, leader end x), and the x that splits points between them.
        self.lanes = (202, self.footer_top - 64)
        self.lane_specs = ((32, 214, 249), (928, 210, 916))
        self.lane_split = 590
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

    def _anchor(self, targets, near):
        """Leader end on the named solid's visible pixels nearest ``near``, or None."""
        if self._owned is None:
            self._owned = _visible(self.canvas, self.viewport)
        return _anchor_on(self.canvas, self._owned, targets, near)

    def _hidden(self, label):
        self.render_debts.append(f"NOT SHOWN: {label} is hidden in this view, so it has no leader.")

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
        _dashed(self.canvas, self.nominal, project, _NOMINAL_FAINT if faint else _BLUE, clip)

    def _component_label(self, component):
        """A holding component's printed name: role groups, jaw names and plural kits."""
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
        role = _role(component)
        label = _plain(component.get("label") or component["name"])
        if role == "fixed_jaw":
            fixed = _plain(self.spec.get("fixed_jaw_label") or "FIXED JAW")
            return fixed if fixed.upper().startswith("FIXED JAW") else "FIXED JAW / " + fixed
        if role == "moving_jaw":
            return "MOVING JAW"
        if role in role_groups:
            return role_groups[role]
        for prefix in ("RAIL REST", "SHIM", "HOLD-DOWN", "HOLD DOWN"):
            if label.upper().startswith(prefix):
                return prefix + "S"
        return label

    def _components(self):
        c = self.canvas
        groups = defaultdict(list)
        pads = []
        numbered = {}
        for component in self.components:
            label = self._component_label(component)
            if _is_pad(component, label):
                pads.append(component)
                continue
            if component.get("code"):
                # The declared clamp number: the same C/LOC/SUP code as the HOLD text.
                numbered[label] = _plain(component["code"])
            groups[label].append(component)
        for label, components in groups.items():
            if label in numbered:
                # Each position carries its code badge; the lane entry is the badge's key.
                badges = [self._numbered_badge(numbered[label], label, item) for item in components]
                badges = [badge for badge in badges if badge]
                if badges:
                    points = [badge["xy"] for badge in badges]
                    self.callouts.append(_Callout(label.upper(), points, _FIXTURE, leader="keyed"))
                    self.position_badges.extend(badges)
                continue
            points, targets = [], ()
            for item in components:
                near = c.project(item["center_mm"])
                tags = tuple(item.get("meshes", ()))
                if not tags:
                    # Not a drawn solid (a named void in the fixture): its own point.
                    points.append(near)
                    continue
                targets += tags
                point = self._anchor(tags, near)
                if point is not None:
                    points.append(point)
            if not points:
                self._hidden(label.upper())
                continue
            self.callouts.append(_Callout(label.upper(), points, _FIXTURE, targets=targets))
        badges = []
        for index, component in enumerate(pads, 1):
            outline = None
            if self.view == "plan" and component.get("box_mm"):
                # A plan view outlines every pad, even where the work covers it.
                outline = self._box_outline(component)
            label = self._component_label(component)
            badge = self._numbered_badge(_pad_code(component, index), label, component, outline)
            if badge:
                badges.append(badge)
        if badges:
            self.callouts.append(
                _Callout("SUPPORT PADS", [badges[0]["xy"]], _FIXTURE, leader="keyed")
            )
            self.position_badges.extend(badges)
        self._stock_callout()

    def _numbered_badge(self, code, label, component, outline=None):
        """A numbered component's position badge (a coded clamp or a pad), or None. Its
        leader ends on the component's own visible pixels. A component hidden in this view
        is a hidden-position symbol: its box drawn as a dashed outline (``outline`` when
        already drawn), the leader ending on that outline, never on what lies in front of
        it. One with no box to outline is a render debt."""
        near = self.canvas.project(component["center_mm"])
        tags = tuple(component.get("meshes", ()))
        if not tags:
            # Not a drawn solid (a named void in the fixture): its own point.
            return {"label": code, "xy": near}
        point = self._anchor(tags, near)
        if point is not None:
            return {"label": code, "xy": point}
        if outline is None and component.get("box_mm"):
            outline = self._box_outline(component)
        if outline is None:
            self._hidden(label.upper())
            return None
        return {"label": code, "xy": near, "outline": outline}

    def _box_outline(self, component):
        """Draw a component's projected box as a dashed outline; returns its pixel polygon."""
        outline = _hull([self.canvas.project(p) for p in _corners(component["box_mm"])])
        _outline(self.canvas, outline, _FIXTURE, width=2, dashed=True)
        return outline

    def _stock_callout(self):
        if not self.stock_pixels:
            return
        # The leader ends on the drawn stock nearest the top of its box, never on a
        # jaw in front of it or in the air the box encloses beside a section.
        left, top, right, _ = _bounds(self.stock_pixels)
        targets = ("part", "removal")
        point = self._anchor(targets, ((left + right) / 2, top))
        if point is None:
            self._hidden("STOCK")
            return
        self.callouts.append(_Callout("STOCK", [point], _INK, targets=targets))

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
            label = _plain(datum["label"]).upper()
            if datum.get("kind") != "end" and not label.startswith("DATUM "):
                label = "DATUM " + label
            facing = []
            normal = datum.get("normal")
            if normal is not None and normal[2] <= -0.99:
                facing.append("UNDERSIDE")
            if normal is not None and _dot3(normal, self.camera[2]) < -0.01:
                # The face looks away from the viewer: its edges are dashed hidden lines
                # and its marker a dashed diamond, never the ring of a face in front.
                facing.append("HIDDEN")
                _dashed(c, datum.get("outline_mm", []), c.project, _INK)
                x, y = point
                _outline(c, [(x, y - 9), (x + 9, y), (x, y + 9), (x - 9, y)], _INK, dashed=True)
            else:
                c.circle(*point, 5, fill=_WHITE, outline=_INK)
                c.circle(*point, 2, fill=_INK)
            if facing:
                label += f" ({', '.join(facing)})"
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
        # A leader naming a drawn solid must end on that solid's visible pixels; one that
        # cannot is a render debt, never a printed leader to the wrong thing.
        kept = []
        for callout in self.callouts:
            if callout.leader == "line" and callout.targets:
                callout.points = [
                    point for point in callout.points if _lands_on(c, point, callout.targets)
                ]
                if not callout.points:
                    self._hidden(callout.label)
                    continue
            kept.append(callout)
        self.callouts = kept
        lane_specs = self.lane_specs
        limit = self.lanes[1]
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
            rows, row_y = [], self.lanes[0]
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
            lanes[0 if callout.points[0][0] < self.lane_split else 1].append(callout)
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
                key=lambda item: (item.leader != "keyed", abs(item.points[0][0] - self.lane_split)),
            )
            lanes[source].remove(moved)
            lanes[target].append(moved)
        # A band that can grow (the holding detail) is redrawn taller instead of
        # printing keys past its edge.
        self.lane_overflow = max(
            pack(ordered(items), side, 25, 0)[1] - limit for side, items in enumerate(lanes)
        )
        if self.lane_overflow > 0 and self.grows_to_fit:
            return
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
        cy = 355
        # A contour much smaller than the window, or whose point keys would crowd one
        # another at the window's scale, gets its own enlarged local detail.
        local = None
        contour = [p for _, path in paths for p in path] + [p["xy"] for p in waypoints]
        crowded = _keys_crowd([p["xy"] for p in waypoints], scale)
        if contour and ((rmax - rmin) * scale <= 80 or crowded):
            bounds = _bounds([(p[1], p[0]) for p in contour])
            span = max(bounds[2] - bounds[0], bounds[3] - bounds[1], 1e-9)
            if span * scale < 150 or crowded:
                if crowded:
                    # The window shrinks to an orientation strip; the detail takes the room.
                    scale = min(scale, _ORIENTATION_PX / max(rmax - rmin, 1e-9))
                margin = 0.15 * span
                local = (
                    bounds[0] - margin,
                    min(bounds[1], 0) - margin,
                    bounds[2] + margin,
                    bounds[3] + margin,
                )
                cy = 236 + (rmax - rmin) * scale / 2
        cx = (left + right) / 2

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
        # Key rows (text, colour, sample line): drawn last, below whatever detail is drawn.
        rows = []
        for profile in profiles:
            colour = tuple(profile.get("colour", _INK))
            dashed = profile["label"] == "arriving stock"
            for line in profile["lines"]:
                for a, b in zip(line, line[1:], strict=False):
                    c.line(project(a), project(b), colour, width=3, dashed=dashed)
            for index, line in enumerate(
                _wrap(c, profile["label"].upper(), right - left - 34, scale=3)
            ):
                rows.append((line, colour, (colour, dashed) if index == 0 else None, 34))
        for z, small, large in self.shoulders:
            step = large - small
            # The main view names no step inside this window; every step either view
            # cannot show is named here.
            if not zmin <= z <= zmax or min(step * scale, step * self.canvas.scale) >= 3:
                continue
            point = project((large, z))
            c.line((point[0], point[1] - 12), (point[0], point[1] + 12), _INK, width=2)
            for line in _wrap(c, _shoulder(z, small, large), right - left, scale=3):
                rows.append((line, _INK, None, 0))
        for path, _ in paths:
            for line in _wrap(c, f"OP {path['op']} SURFACE", right - left - 34, scale=3):
                rows.append((line, _GREEN, (_GREEN, False), 34))
        if paths:
            rows.append(("ARROWS: POINT ORDER", _MUTED, None, 0))
        if closed:
            for line in _wrap(c, "TINT: PROFILE DIFFERENCE", right - left, scale=3):
                rows.append((line, _AMBER, None, 0))
        if self.off_window_keys:
            for line in _wrap(c, "OFF-WINDOW P KEYS: FULL VIEW", right - left, scale=3):
                rows.append((line, _MUTED, None, 0))
        row = 510
        if crowded and local is not None:
            # The key rows end at the column foot so the detail gets every free row.
            row = max(row, self.footer_top - 17 - 30 * len(rows))
        if local is not None:
            zlo, rlo, zhi, rhi = local
            box = (left, cy + (rmax - rmin) * scale / 2 + 22, right, row - 17)
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
            # Keys go above and below a wide contour, or beside a tall one.
            cell = max((_badge_width(c, _plain(p["label"])) for p in waypoints), default=0)
            detail = max(
                min(
                    (plot[2] - plot[0] - 40) / (zhi - zlo),
                    max(20, plot[3] - plot[1] - 2 * 31) / (rhi - rlo),
                ),
                min(
                    max(20, plot[2] - plot[0] - 2 * (cell + 16)) / (zhi - zlo),
                    (plot[3] - plot[1] - 8) / (rhi - rlo),
                ),
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
        for _, points in paths:
            window = (project((0, zmin))[0], 228, project((0, zmax))[0], 493)
            if local is None:
                self._ordered_path([project(p) for p in points], _GREEN, clip=window)
            else:
                pixels = [project(p) for p in points]
                for a, b in zip(pixels, pixels[1:], strict=False):
                    segment = _clip_segment(a, b, window)
                    if segment:
                        c.line(*segment, _GREEN, width=3)
        if local is None:
            self._waypoint_badges(waypoints, project, (left, 205, right, 493))
        for line, colour, sample, indent in rows:
            if sample is not None:
                c.line(
                    (left, row + 10), (left + 25, row + 10), sample[0], width=3, dashed=sample[1]
                )
            _text(c, left + indent, row, line, colour)
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
        heights = self._panel_heights(ops, paths, waypoints, width, bottom - top, columns)
        tops = [top + sum(heights[:row]) + 12 * row for row in range(rows)]
        palette = (_BLUE, _GREEN, _AMBER, (113, 65, 137))
        for index, op in enumerate(ops):
            x = left + (index % columns) * (width + 12)
            y = tops[index // columns]
            height = heights[index // columns]
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

    def _panel_heights(self, ops, paths, waypoints, width, span, columns):
        """Each panel row's height: equal rows unless an operation's keys need more room.

        A panel keys its points in perimeter cells (at most sqrt(n) columns, as in
        :meth:`_grid_cells`) between its title band and its bottom edge; rows whose keys
        would stack closer than one badge height plus a 4 px gap take height from rows
        with spare room, so dense key sets never overprint."""
        c = self.canvas
        rows = math.ceil(len(ops) / columns)
        total = span - 12 * (rows - 1)
        # Title band (31) and bottom margin (6) around one badge row (33 high).
        needs = [37.0 + 33.0] * rows
        for index, op in enumerate(ops):
            labels = [
                label if label.upper().startswith("P") else "P" + label
                for label in (_plain(p["label"]) for p in waypoints if str(p.get("op", "")) == op)
            ]
            raster = sorted(
                p["raster"]["pass"] for p in paths if str(p.get("op", "")) == op and p.get("raster")
            )
            labels.extend(f"PASS {number}" for number in dict.fromkeys(raster[:1] + raster[-1:]))
            if not labels:
                continue
            cell = max(_badge_width(c, label) for label in labels)
            fit = max(1, int((width - 12 + 8) / (cell + 8)))
            key_rows = math.ceil(len(labels) / min(fit, math.ceil(math.sqrt(len(labels)))))
            # Further badge rows on a 37 px pitch (33 high plus a 4 px gap).
            need = 37 + 33 + 37 * (key_rows - 1)
            needs[index // columns] = max(needs[index // columns], need)
        equal = total / rows
        if all(need <= equal for need in needs):
            return [equal] * rows
        if sum(needs) <= total:
            spare = (total - sum(needs)) / rows
            return [need + spare for need in needs]
        return [total * need / sum(needs) for need in needs]

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
        returns [(label, badge centre, point)] in pixels. A waypoint with an ``outline``
        marks a hidden solid: its leader stops on that dashed outline at an open ring."""
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
        placed = []
        for item, label, point, cell in zip(waypoints, labels, points, cells, strict=True):
            badge, outline = available[cell], item.get("outline")
            end = _nearest_on_outline(outline, badge) if outline else point
            placed.append((badge, label, end, item.get("colour", colour), bool(outline)))
        for badge, label, point, point_colour, hidden in placed:
            c.line(point, badge, _MUTED, width=2)
            if hidden:
                c.circle(*point, 4, fill=_WHITE, outline=point_colour)
                self.hidden_leaders.append((label, [point, badge]))
                continue
            c.circle(*point, 3, fill=point_colour)
            self.leaders.append((label, [point, badge]))
        for badge, label, _, badge_colour, _ in placed:
            _badge(c, badge, label, badge_colour)
        return [(label, badge, point) for badge, label, point, _, _ in placed]

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
    """Return ``(png, debts)``: a setup PNG 1600 px wide (taller when holding detail bands
    are printed below it), and the NOT SHOWN lines for what it could not draw truthfully
    (a named solid hidden from its leader). Those lines are also printed in the picture's
    own notes. No physical dimension is invented.

    ``meshes`` contain numeric setup-frame XYZ triples, triangle index triples,
    RGB, optionally a removal-hatch flag and the tag of the solid each draws. ``spec``
    is the kernel's plain JSON diagram record; optional ``lathe_profiles`` contain
    exact [radius, Z] lines.
    """
    debts, details = [], []
    # A debt found while laying out is printed in the notes, which can move the layout:
    # redraw until the printed notes are exactly the debts of the picture they sit in.
    for attempt in range(4):
        diagram = _Diagram(meshes, {**spec, "notes": list(spec.get("notes", [])) + debts})
        png = diagram.render()
        if attempt == 0:
            details = _holding_details(meshes, spec, diagram)
        found = [debt for detail in details for debt in detail.render_debts]
        found += diagram.render_debts
        if found != debts:
            debts = found
            continue
        if not details:
            return png, debts
        for detail in details:
            diagram.canvas.grow(detail.canvas.height)
            diagram.canvas.paste(detail.canvas, 0, diagram.canvas.height - detail.canvas.height)
        return diagram.canvas.png(), debts
    raise ValueError(f"setup picture debts do not settle: {debts}")


def _holding_details(meshes, spec, diagram):
    """The rendered holding detail bands for a setup picture, else []. They are drawn only
    when something touches the stock and ``diagram`` draws the stock's narrower side under
    ``_DETAIL_MIN_PX`` (small beside its holding). One band is drawn when it draws that
    side at least ``_DETAIL_GAIN`` times larger. A plan view, which cannot show contact
    heights, always gets the detail's raised view, split along the work's length into the
    fewest bands (at most ``_DETAIL_TILES``) that reach the gain, else the most."""
    frame = _detail_frame(spec)
    if frame is None or not diagram.stock_pixels:
        return []
    drawn = _short_side(diagram.stock_pixels)
    if drawn >= _DETAIL_MIN_PX:
        return []
    camera = _HoldingDetail.camera_for(spec)
    stock = _corners(spec["stock_box"])
    across = _short_side([(_dot3(p, camera[0]), _dot3(p, camera[1])) for p in stock])
    counts = range(1, _DETAIL_TILES + 1) if spec["view"] == "plan" else (1,)
    for count in counts:
        tiles = _tiles(frame, camera, count)
        scale = min(
            _fit_scale(_corners(tile), camera, _detail_viewport(tile, camera)) for tile in tiles
        )
        if scale * across >= _DETAIL_GAIN * drawn:
            break
    else:
        if spec["view"] != "plan":
            return []
    details = []
    for index, tile in enumerate(tiles, 1):
        extra = 0
        while True:
            detail = _HoldingDetail(
                meshes,
                spec,
                tile,
                camera,
                scale / diagram.canvas.scale,
                (index, len(tiles)),
                extra,
            )
            detail.render()
            if detail.lane_overflow <= 0:
                break
            extra += math.ceil(detail.lane_overflow)
        details.append(detail)
    return details


def _tiles(frame, camera, count):
    """``frame`` cut into ``count`` equal boxes along the setup axis the detail camera
    draws left to right, in that order."""
    if count == 1:
        return [frame]
    axis = max(range(3), key=lambda i: abs(camera[0][i]))
    low, high = frame[axis], frame[axis + 3]
    step = (high - low) / count
    tiles = []
    for index in range(count):
        tile = list(frame)
        tile[axis] = low + index * step
        tile[axis + 3] = low + (index + 1) * step
        tiles.append(tile)
    if camera[0][axis] < 0:
        tiles.reverse()
    return tiles


def _detail_viewport(frame, camera, extra=0):
    """The detail band's viewport: full width, and only as tall as the framed geometry
    needs at that width, between the room its keys need and the full band, plus
    ``extra`` rows the keys turned out to need."""
    left, top, right = 370, 100, 1230
    xs = [_dot3(p, camera[0]) for p in _corners(frame)]
    ys = [_dot3(p, camera[1]) for p in _corners(frame)]
    needed = (max(ys) - min(ys)) * (right - left) / max(max(xs) - min(xs), 1e-9)
    return (left, top, right, top + min(600, max(300, needed)) + extra)


def _short_side(points):
    left, top, right, bottom = _bounds(points)
    return min(right - left, bottom - top)


def _fit_scale(points, camera, viewport):
    """The scale ``RenderCanvas`` fits ``points`` to ``viewport`` at, without drawing."""
    xs = [_dot3(p, camera[0]) for p in points]
    ys = [_dot3(p, camera[1]) for p in points]
    left, top, far, bottom = viewport
    scales = []
    if max(xs) > min(xs):
        scales.append(0.9 * (far - left) / (max(xs) - min(xs)))
    if max(ys) > min(ys):
        scales.append(0.9 * (bottom - top) / (max(ys) - min(ys)))
    return min(scales) if scales else 1.0


def _detail_frame(spec):
    """The box a holding detail frames: the stock, its contact outlines and the closest
    cut's ends, padded; None when nothing touches the stock."""
    stock = spec.get("stock_box")
    contacts = spec.get("contacts") or []
    if stock is None or not contacts:
        return None
    points = _corners(stock)
    points += [p for contact in contacts for line in contact["lines_mm"] for p in line]
    cut = spec.get("closest_cut")
    if cut:
        points += [cut["from_mm"], cut["to_mm"]]
    low = [min(p[i] for p in points) for i in range(3)]
    high = [max(p[i] for p in points) for i in range(3)]
    pads = [0.05 * (high[i] - low[i]) + 2.0 for i in range(3)]
    return [low[i] - pads[i] for i in range(3)] + [high[i] + pads[i] for i in range(3)]


def _solid_name(tag):
    """A fixture solid's own printed name: the part of its tag after the fixture's name."""
    return _plain(tag.rsplit(":", 1)[-1]).replace("-", " ").upper()


def _common_plane(lines):
    """(axis, value) of the one setup-axis plane the points of ``lines`` lie on, or None.
    Points on one straight line (a lone point, a single edge) lie on many planes and name
    none: a seating face a section reduces to one edge is not a lateral plane."""
    points = [p for line in lines for p in line]
    if not points:
        return None
    first = points[0]
    far = max(points, key=lambda p: math.dist(p, first))
    span = [far[i] - first[i] for i in range(3)]
    length = math.hypot(*span)

    def off_line(point):
        d = [point[i] - first[i] for i in range(3)]
        return math.hypot(
            d[1] * span[2] - d[2] * span[1],
            d[2] * span[0] - d[0] * span[2],
            d[0] * span[1] - d[1] * span[0],
        )

    if length <= _PLANE_MM or all(off_line(p) <= _PLANE_MM * length for p in points):
        return None
    for axis in range(3):
        values = [p[axis] for p in points]
        if max(values) - min(values) <= _PLANE_MM:
            return axis, sum(values) / len(values)
    return None


def _same_plane(a, b):
    """Whether two (axis, value) planes are one, or are both unknown."""
    if a is None or b is None:
        return a is b
    return a[0] == b[0] and abs(a[1] - b[1]) <= _PLANE_MM


def _shared_plane(planes):
    """The one known plane every one of ``planes`` is, else None."""
    first = planes[0] if planes else None
    return first if first is not None and all(_same_plane(first, p) for p in planes) else None


def _contact_plane(contact):
    """A contact's setup-axis plane: the kernel's, measured on the whole contact before a
    section view clips it, else that of its outline."""
    if "plane" in contact:
        plane = contact["plane"]
        return None if plane is None else (int(plane[0]), float(plane[1]))
    return _common_plane(contact["lines_mm"])


class _HoldingDetail(_Diagram):
    """A second, larger look at the work in its holding, printed below the setup picture:
    the same placed solids framed on the stock and the holding that touches it. Each
    contact is outlined (solid where seen, dashed where hidden) and keyed with the setup
    coordinate of its plane, and the removal nearest the holding is dimensioned."""

    @staticmethod
    def camera_for(spec):
        if spec["view"] != "plan":
            return (
                tuple(map(tuple, spec["camera"])) if spec.get("camera") else _CAMERAS[spec["view"]]
            )
        rise = math.radians(_DETAIL_RISE_DEG)
        s, c = math.sin(rise), math.cos(rise)
        box = spec["stock_box"]
        if box[3] - box[0] >= box[4] - box[1]:
            return ((1, 0, 0), (0, s, c), (0, -c, s))  # from -Y, raised
        return ((0, 1, 0), (-s, 0, c), (c, 0, s))  # from +X, raised

    grows_to_fit = True

    def __init__(self, meshes, spec, frame, camera, gain, tile=(1, 1), extra=0):
        self.spec = spec
        self.view = spec["view"]
        self.camera = camera
        self.gain = gain
        self.frame = frame
        self.tile = tile
        self.components = spec.get("components", [])
        self.stock = spec.get("stock_box")
        self.callouts = []
        self.obstacles = []
        self.position_badges = []
        self.leaders = []
        self.hidden_leaders = []
        self.render_debts = []
        self._owned = None
        self.meshes = list(meshes)
        self.viewport = _detail_viewport(frame, camera, extra)
        self.footer_top = math.ceil(self.viewport[3]) + 28
        self.lanes = (self.viewport[1], self.footer_top - 16)
        self.lane_specs = ((32, 300, 344), (1268, 300, 1256))
        self.lane_split = (self.viewport[0] + self.viewport[2]) / 2
        self.canvas = RenderCanvas(
            self.meshes,
            camera,
            self.viewport,
            width=1600,
            height=self.footer_top,
            fit=_corners(frame),
        )
        self.stock_pixels = [self.canvas.project(p) for p in _corners(self.stock)]

    def _title(self):
        index, count = self.tile
        title = "HOLDING DETAIL" if count == 1 else f"HOLDING DETAIL {index} OF {count}"
        title += f" X{self.gain:.1f}"
        zero = self.spec.get("zero_mm")
        if count == 1 or zero is None:
            return title
        axis = max(range(3), key=lambda i: abs(self.camera[0][i]))
        low, high = self.frame[axis] - zero[axis], self.frame[axis + 3] - zero[axis]
        return f"{title}  /  SETUP {'XYZ'[axis]} {_mm(low)} TO {_mm(high)}"

    def _contact_groups(self):
        """[(label, plane, [(member name or None, badge code or None, lines)])]: each
        contacting solid under the holding name it is printed with and the setup-axis plane
        it lies on (None when unknown). A component's contacting solids are split by plane
        first: on one plane it is keyed once (a pad or a coded clamp by its badge); on
        several, each solid is keyed by its own name and plane, under the component's
        label when that carries a pad or clamp code. Solids of one name on different planes
        are keyed plane by plane."""
        contacts = {contact["tag"]: contact for contact in self.spec["contacts"]}
        planes = {tag: _contact_plane(contact) for tag, contact in contacts.items()}
        groups, named, loose = [], set(), []

        def add(label, plane, member, code, lines):
            for key, key_plane, members in groups:
                if key == label and _same_plane(key_plane, plane):
                    members.append((member, code, lines))
                    return
            groups.append((label, plane, [(member, code, lines)]))

        def add_solid(prefix, tag):
            # Twins named "<stem> <short member>" (rail shims LU, RU) share their stem's key.
            name = _solid_name(tag)
            stem, _, member = name.rpartition(" ")
            if stem and len(member) <= 2:
                add(prefix + stem, planes[tag], member, None, contacts[tag]["lines_mm"])
            else:
                add(prefix + name, planes[tag], None, None, contacts[tag]["lines_mm"])

        for component in self.components:
            tags = [tag for tag in component.get("meshes", ()) if tag in contacts]
            if not tags:
                continue
            named.update(tags)
            label = self._component_label(component)
            numbered = _is_pad(component, label) or component.get("code")
            parts = []
            for tag in tags:
                part = next((p for p in parts if _same_plane(p[0], planes[tag])), None)
                if part is None:
                    parts.append((planes[tag], [tag]))
                else:
                    part[1].append(tag)
            if len(parts) > 1:
                if numbered:
                    # Its badge would key several heights at once: each solid is keyed and
                    # led to on its own plane, under the label that carries its code.
                    for tag in tags:
                        add_solid(label + " ", tag)
                else:
                    loose.extend(tags)
                continue
            ((plane, _),) = parts
            lines = [line for tag in tags for line in contacts[tag]["lines_mm"]]
            if _is_pad(component, label):
                add("SUPPORT PADS", plane, None, _pad_code(component, 1), lines)
            elif numbered:
                add(label, plane, None, _plain(component["code"]), lines)
            elif len(tags) == 1 or plane is not None:
                add(label, plane, None, None, lines)
            else:
                loose.extend(tags)
        loose.extend(tag for tag in contacts if tag not in named)
        for tag in loose:
            add_solid("", tag)
        return groups

    def render(self):
        c = self.canvas
        c.line((32, 8), (1568, 8), _INK, width=2)
        _text(c, 32, 22, self._title(), scale=4)
        _text(c, 34, 62, "CONTACT FACES: SOLID WHERE SEEN, DASHED WHERE HIDDEN", _CONTACT)
        groups = self._contact_groups()
        keyed = []
        for label, plane, members in groups:
            for _, _, lines in members:
                self._contact_outline(lines)
            shown = [
                (member, code, lines, c.project(self._contact_anchor(lines)))
                for member, code, lines in members
                if self._in_tile(self._contact_anchor(lines))
            ]
            if shown:
                keyed.append((label, plane, shown))
        labels = [label for label, _, _ in keyed]
        for label, plane, shown in keyed:
            names = [member for member, _, _, _ in shown if member]
            codes = [code for _, code, _, _ in shown]
            if not names and labels.count(label) > 1:
                # One name keyed at several heights (pads on two planes): each key names
                # the badges it keys, so each badge reads its own height.
                names = list(dict.fromkeys(code for code in codes if code))
            text = label
            if len(names) == 1:
                text += f" {names[0]}"
            elif names:
                text += f" ({', '.join(names)})"
            text += f" CONTACT{self._plane_text(plane)}"
            points = [point for _, _, _, point in shown]
            if not any(codes):
                self.callouts.append(_Callout(text, points, _CONTACT))
                continue
            self.callouts.append(_Callout(text, points[:1], _CONTACT, leader="keyed"))
            self.position_badges.extend(
                {"label": code, "xy": point} for code, point in zip(codes, points, strict=True)
            )
        self._closest_cut()
        self._stock_callout()
        self._labels()
        if self.lane_overflow > 0:
            return
        if self.position_badges:
            contact = [
                c.project(p)
                for _, _, members in groups
                for _, _, lines in members
                for line in lines
                for p in line
            ]
            exclusion = _bounds(self.stock_pixels + contact)
            _, top, _, bottom = self.viewport
            self._waypoint_badges(
                self.position_badges,
                lambda p: p,
                self.viewport,
                prefix="",
                colour=_CONTACT,
                exclusion=(
                    exclusion[0],
                    max(top, exclusion[1]),
                    exclusion[2],
                    min(bottom, exclusion[3]),
                ),
            )
        self.canvas.assert_text_layout(min_scale=_BODY_SCALE)

    def _seen(self, point):
        """Whether a point on a contact face is the surface drawn at its pixel."""
        c = self.canvas
        x, y = (math.floor(v) for v in c.project(point))
        depth = c.depth_of(point)
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                if not (0 <= x + dx < c.width and 0 <= y + dy < c.height):
                    continue
                if c.depth[(y + dy) * c.width + x + dx] <= depth + 0.3:
                    return True
        return False

    def _contact_outline(self, lines):
        c = self.canvas
        for line in lines:
            if len(line) == 1:
                point = c.project(line[0])
                fill = _CONTACT if self._seen(line[0]) else _WHITE
                c.circle(*point, 6, fill=fill, outline=_CONTACT)
                continue
            runs = []
            for a, b in zip(line, line[1:], strict=False):
                seen = self._seen([(a[i] + b[i]) / 2 for i in range(3)])
                if runs and runs[-1][0] == seen:
                    runs[-1][1].append(b)
                else:
                    runs.append((seen, [a, b]))
            for seen, run in runs:
                if not seen:
                    _dashed(c, [run], c.project, _CONTACT, clip=self.viewport)
                    continue
                for a, b in zip(run, run[1:], strict=False):
                    segment = _clip_segment(c.project(a), c.project(b), self.viewport)
                    if segment:
                        c.line(*segment, _CONTACT, width=3)

    def _contact_anchor(self, lines):
        """The outline point nearest the contact's centre, in setup mm."""
        points = [p for line in lines for p in line]
        centre = [sum(p[i] for p in points) / len(points) for i in range(3)]
        return min(points, key=lambda p: math.dist(p, centre))

    def _in_tile(self, point):
        """Whether a setup point is this band's to key: inside its share of the work's
        length when the detail is split, else inside its picture."""
        if self.tile[1] > 1:
            axis = max(range(3), key=lambda i: abs(self.camera[0][i]))
            return self.frame[axis] <= point[axis] <= self.frame[axis + 3]
        left, top, right, bottom = self.viewport
        x, y = self.canvas.project(point)
        return left <= x <= right and top <= y <= bottom

    def _plane_text(self, plane):
        zero = self.spec.get("zero_mm")
        if zero is None or plane is None:
            return ""
        axis, value = plane
        return f" AT {'XYZ'[axis]} {_mm(value - zero[axis])}"

    def _closest_cut(self):
        cut = self.spec.get("closest_cut")
        if not cut:
            return
        c = self.canvas
        a, b = c.project(cut["from_mm"]), c.project(cut["to_mm"])
        middle = ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2)
        if not self._in_tile([(cut["from_mm"][i] + cut["to_mm"][i]) / 2 for i in range(3)]):
            return
        c.line(a, b, _AMBER, width=3)
        for point in (a, b):
            c.circle(*point, 4, fill=_AMBER)
        holder = _solid_name(cut["tag"])
        for component in self.components:
            if cut["tag"] not in component.get("meshes", ()):
                continue
            if component.get("meshes") == [cut["tag"]]:
                holder = self._component_label(component)
            elif component.get("code"):
                holder = f"{_plain(component['code'])} {holder}"
        label = f"CUT {_mm(cut['mm'])} mm FROM {holder.upper()}"
        self.callouts.append(_Callout(label, [middle], _AMBER))
