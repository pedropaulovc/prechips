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


def _plain(value):
    """Keep shop labels printable without exposing unsupported glyph placeholders."""
    text = str(value).replace("_", " ")
    for old, new in (("?", "not declared"), ("−", "-"), ("–", "-"), ("—", "-"),
                     ("×", "x"), ("Ø", "DIA "), ("ø", "DIA "), ("°", " DEG"),
                     ("→", " TO "), ("≤", " <= "), ("≥", " >= ")):
        text = text.replace(old, new)
    return " ".join(text.split()).upper()


def _mm(value):
    text = f"{value:.2f}".rstrip("0").rstrip(".")
    return "0" if text in ("", "-0") else text


def _corners(box):
    if box is None:
        return []
    return [(x, y, z) for x in (box[0], box[3])
            for y in (box[1], box[4]) for z in (box[2], box[5])]


def _bounds(points):
    return (min(p[0] for p in points), min(p[1] for p in points),
            max(p[0] for p in points), max(p[1] for p in points))


def _xy_projector(bounds, centre, scales):
    """Bind a panel's graphic transform without changing its physical XY data."""
    xmin, ymin, xmax, ymax = bounds
    cx, cy = centre
    scale_x, scale_y = scales

    def project(point):
        return (cx + (point[0] - (xmin + xmax) / 2) * scale_x,
                cy - (point[1] - (ymin + ymax) / 2) * scale_y)

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
    for p, q in ((-dx, a[0] - left), (dx, right - a[0]),
                 (-dy, a[1] - top), (dy, bottom - a[1])):
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
    return ((a[0] + low * dx, a[1] + low * dy),
            (a[0] + high * dx, a[1] + high * dy))


def _badge(canvas, point, label, colour=_BLUE, scale=3):
    width = max(24, canvas.text_width(label, scale=scale) + 12)
    height = 7 * scale + 12
    x, y = point[0] - width / 2, point[1] - height / 2
    canvas.rect(x, y, width, height, _WHITE)
    _outline(canvas, [(x, y), (x + width, y), (x + width, y + height), (x, y + height)], colour)
    _text(canvas, point[0], y + 6, label, colour, scale=scale, align="centre")


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
    _text(canvas, (first[0] + second[0]) / 2, (first[1] + second[1]) / 2 - 23,
          label, colour, align="centre", backing=True)


class _Diagram:
    def __init__(self, meshes, spec):
        self.spec = spec
        self.view = spec["view"]
        self.camera = _CAMERAS[self.view]
        self.components = spec.get("components", [])
        self.stock = spec.get("stock_box")
        self.tool = spec.get("primary_tool")
        self.nominal = [line for line in spec.get("nominal_outline_mm", []) if len(line) >= 2]
        if self.view == "lathe":
            self.nominal = []
        self.is_vise = any(_role(c) in ("fixed_jaw", "moving_jaw", "jaw")
                           for c in self.components)
        self.is_chuck = self.view == "lathe" or any(_role(c).startswith("chuck")
                                                   for c in self.components)
        self.callouts = []
        self.obstacles = []
        self.context_labels = []
        self.position_badges = []
        self.lathe_window = None
        self.off_window_keys = []
        if self.view == "lathe":
            profile_points = [p for profile in spec.get("lathe_profiles", [])
                              for line in profile["lines"] for p in line]
            if profile_points:
                self.lathe_window = (min(p[1] for p in profile_points),
                                     max(p[1] for p in profile_points))
                display = {str(p["op"]): p.get("x_display", "radius")
                           for p in spec.get("axial_paths", [])}
                for waypoint in spec.get("waypoints", []):
                    if "xz" not in waypoint:
                        continue
                    x, z = waypoint["xz"]
                    if self.lathe_window[0] <= z <= self.lathe_window[1]:
                        continue
                    convention = waypoint.get(
                        "x_display", display.get(str(waypoint.get("op")), "radius")
                    )
                    radius = x / 2 if convention == "diameter" else x
                    self.off_window_keys.append((waypoint["label"], (radius, 0, z)))
        self.meshes = list(meshes)
        points = _corners(self.stock)
        points.extend(point for line in self.nominal for point in line)
        points.extend(point for _, point in self.off_window_keys)
        if spec.get("zero_mm") is not None:
            points.append(spec["zero_mm"])
        for datum in spec.get("datums", []):
            points.append(datum["point_mm"])
        for component in self.components:
            points.extend(_corners(component.get("box_mm")))
            points.append(component["center_mm"])
        if self.tool:
            outlines = self.tool.get("outlines_mm") or [self.tool.get("outline_mm", [])]
            points.extend(point for outline in outlines for point in outline)
            points.extend(self.tool.get("approach_mm", []))
            points.extend(self.tool.get("feed_mm") or [])
            points.append(self.tool["tip_mm"])
        self.meshes.append((points, [], _WHITE))
        self.canvas = RenderCanvas([], self.camera, (0, 0, 1, 1), width=1, height=1)
        # Keep the printable scene large. Verbose source legends must not turn
        # into a second notes column and push the placed geometry off the page.
        self.footer_top = 740
        self.scene_bottom = 620
        self.note_scale = 3
        self.note_lines = self._notes()
        if len(self.note_lines) > 8:
            self.note_scale = 2
            self.note_lines = self._notes()
        self.legend_rows = self._legend()
        viewport = (278, 225, 900, self.scene_bottom)
        if self.view == "plan" and (
            spec.get("custom_clamp_order")
            or any(_role(component) == "pad" for component in self.components)
        ):
            # Leave real exterior key bands even for a vertically tall fixture.
            viewport = (278, 278, 900, 540)
        self.canvas = RenderCanvas(self.meshes, self.camera, viewport)
        self.stock_pixels = [self.canvas.project(p) for p in _corners(self.stock)]
        self.position_badges.extend(
            {"label": label, "xy": self.canvas.project(point), "colour": _BLUE}
            for label, point in self.off_window_keys
        )

    def _notes(self):
        notes = [_plain(note) for note in self.spec.get("notes", [])]
        if self.tool:
            notes.append("Tool approach is illustrative, not a machining pose or simulated path.")
            notes.append(
                f"Selected tool: {self.tool['label']} / "
                f"op {self.tool.get('op', 'not declared')}"
            )
        if self.spec.get("zero_mm") is None:
            notes.append("Z0: not declared")
        if not self.spec.get("datums"):
            notes.append("Datums: not declared")
        if self.nominal:
            notes.append("NOMINAL OUTLINE IS NOT A CUT-PART MODEL.")
        if self.is_chuck:
            if self.spec.get("jaw_front_z_mm") is None:
                notes.append("Jaw-front Z: not declared")
            if self.spec.get("stickout_mm") is None:
                notes.append("Stickout: not declared")
        return [
            line for note in notes
            for line in _wrap(self.canvas, note, 720, scale=self.note_scale)
        ]

    def _legend(self):
        rows = []
        kinds = set()
        meanings = (
            ("retained", "RETAINED AFTER SETUP", "stock"),
            ("arriving", "ARRIVING / CUTS UNCONFIRMED", "stock"),
            ("removed", "REMOVED THIS SETUP", "removal"),
            ("holding", "WORKHOLDING", "fixture"),
            ("tool", "TOOL / APPROACH", "tool"),
            ("context", "CONTEXT SYMBOLS ONLY", "context"),
            ("nominal", "NOMINAL OUTLINE", "nominal"),
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
        required.append(("CONTEXT SYMBOLS ONLY", "context"))
        for label, kind in required:
            if kind not in kinds:
                rows.append((label, kind))
                kinds.add(kind)
        if any("pad" in _plain(c.get("label") or c["name"]).lower() for c in self.components):
            rows.append(("PAD BADGES: POSITIONS", "text"))
        if self.nominal and "nominal" not in kinds:
            rows.append(("NOMINAL OUTLINE", "nominal"))
        return rows

    def render(self):
        self._header()
        self._context()
        if self.nominal:
            self._nominal_overlay(self.canvas.project)
            self.callouts.append(_Callout("NOMINAL OUTLINE",
                                         [self.canvas.project(self.nominal[0][0])], _BLUE))
        self._components()
        self._origin_datums_tool()
        self._measurements()
        self._labels()
        if self.position_badges:
            exclusion = None
            if self.view == "plan":
                pixels = self.stock_pixels + self._component_pixels(self.components)
                pixels.extend(self.canvas.project(p) for line in self.nominal for p in line)
                if pixels:
                    exclusion = _bounds(pixels)
            self._waypoint_badges(
                self.position_badges, lambda p: p, (278, 205, 900, 593),
                prefix="", colour=_FIXTURE, exclusion=exclusion,
            )
        self._insets()
        for x, y, label, scale in self.context_labels:
            _text(self.canvas, x, y, label, _MUTED, scale=scale, align="centre", backing=True)
        self._footer()
        return self.canvas.png()

    def _header(self):
        c = self.canvas
        _text(c, 32, 27, f"SETUP {self.spec['setup_id']}  /  {self.view.upper()} VIEW", scale=4)
        subtitles = {
            "lathe": "SPINDLE Z TO RIGHT  /  RADIAL X UP  /  FULL ARRIVING STOCK",
            "plan": "SETUP X TO RIGHT  /  Y UP  /  VIEW FROM +Z",
            "isometric": "PLACED GEOMETRY IN THE SETUP FRAME",
        }
        _text(c, 34, 76, subtitles[self.view], _MUTED)
        _text(c, 1565, 77, "DIMENSIONS IN mm", _MUTED, align="right")
        c.line((32, 112), (1568, 112), _INK, width=2)
        _text(c, 32, 138, "PLACED STOCK + WORKHOLDING", _INK, scale=2)
        _text(c, 32, 166, "Machine context is symbolic, not modelled geometry.", _MUTED)

    def _component_pixels(self, components):
        return [self.canvas.project(p) for item in components
                for p in (_corners(item.get("box_mm")) or [item["center_mm"]])]

    def _context(self):
        c = self.canvas
        if self.view == "lathe":
            chuck = [item for item in self.components if _role(item).startswith("chuck")]
            if chuck:
                left, top, _, bottom = _bounds(self._component_pixels(chuck))
                x, y = left - 100, (top + bottom) / 2 - 55
                _outline(c, [(x, y), (x + 94, y), (x + 94, y + 110), (x, y + 110)], dashed=True)
                _outline(c, [(x - 8, y + 110), (x + 98, y + 110),
                             (x + 98, y + 128), (x - 8, y + 128)], dashed=True)
                self.obstacles.append((x - 36, y - 30, x + 130, y + 130))
                self.context_labels.extend(((x + 47, y - 26, "HEADSTOCK", 3),
                                            (x + 47, y + 87, "SYMBOL", 2)))
            centres = [item for item in self.components if _role(item) in ("centre", "center")]
            if centres or self.stock_pixels:
                pixels = self._component_pixels(centres) if centres else self.stock_pixels
                _, top, right, bottom = _bounds(pixels)
                if not centres:
                    tool_pixels = [c.project(point) for outline in (
                        self.tool.get("outlines_mm") or [self.tool.get("outline_mm", [])]
                    ) for point in outline] if self.tool else []
                    right = max([right] + [point[0] for point in tool_pixels]) + 44
                x, y = right + 8, (top + bottom) / 2 - 44
                _outline(c, [(x, y + 20), (x + 20, y), (x + 82, y),
                             (x + 82, y + 88), (x, y + 88)], dashed=True)
                _outline(c, [(x - 4, y + 88), (x + 88, y + 88),
                             (x + 88, y + 106), (x - 4, y + 106)], dashed=True)
                self.obstacles.append((x - 40, y - 30, x + 125, y + 110))
                self.context_labels.extend(
                    ((x + 41, y - 26, "TAILSTOCK", 3),
                     (x + 41, y + 66, "SYMBOL" if centres else "NO CENTRE DRAWN", 2))
                )
        elif self.is_vise:
            jaws = [item for item in self.components
                    if _role(item) in ("fixed_jaw", "moving_jaw", "jaw")]
            left, top, right, bottom = _bounds(self._component_pixels(jaws))
            # Dashed screen-space frames provide context without inventing solids.
            vise = [(left - 18, top - 18), (right + 18, top - 18),
                    (right + 18, bottom + 24), (left - 18, bottom + 24)]
            table = [(left - 45, top - 40), (right + 45, top - 40),
                     (right + 45, bottom + 45), (left - 45, bottom + 45)]
            _outline(c, table, dashed=True)
            _outline(c, vise, dashed=True)
            self.context_labels.append(((left + right) / 2, 194, "TABLE / VISE: SYMBOLS ONLY", 3))

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
                        start = (a[0] + (b[0] - a[0]) * distance / length,
                                 a[1] + (b[1] - a[1]) * distance / length)
                        end = (a[0] + (b[0] - a[0]) * (distance + run) / length,
                               a[1] + (b[1] - a[1]) * (distance + run) / length)
                        segment = _clip_segment(start, end, clip) if clip else (start, end)
                        if segment:
                            c.line(*segment, colour, width=2)
                    distance += run
                    phase = (phase + run) % 14

    def _components(self):
        c = self.canvas
        groups = defaultdict(list)
        pads = []
        order = self.spec.get("custom_clamp_order", [])
        numbered = {}
        role_groups = {"parallel": "PARALLELS", "riser": "RISERS",
                       "chuck_jaw": "CHUCK JAWS", "centre": "CENTRE"}
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
                label = next(prefix for prefix in ("RAIL REST", "SHIM", "HOLD-DOWN", "HOLD DOWN")
                             if label.upper().startswith(prefix)) + "S"
            if "pad" in label.lower() and role in ("fixture", "support", "pad"):
                pads.append(component)
                continue
            for index, declared in enumerate(order, 1):
                if declared in (component.get("label"), component.get("name"),
                                component.get("clamp_label")):
                    code = f"C{index}"
                    declared_label = _plain(declared)
                    suffix = (
                        declared_label.split(":", 1)[1].strip()
                        if ":" in declared_label else declared_label
                    )
                    label = code if suffix.upper() == code else f"{code}: {suffix}"
                    numbered[label] = code
                    break
            groups[label].append(component)
        for label, components in groups.items():
            points = [c.project(item["center_mm"]) for item in components]
            self.callouts.append(_Callout(label.upper(), points, _FIXTURE))
            if label in numbered:
                for point in points:
                    self.position_badges.append({"label": numbered[label], "xy": point})
        if pads:
            for index, component in enumerate(pads, 1):
                point = c.project(component["center_mm"])
                label = _plain(component.get("label") or component["name"]).upper()
                code = label.removeprefix("PAD ").removeprefix("SUPPORT PAD ") or str(index)
                if self.view == "plan" and component.get("box_mm"):
                    left, top, right, bottom = _bounds(self._component_pixels([component]))
                    _outline(c, [(left, top), (right, top), (right, bottom), (left, bottom)],
                             _FIXTURE, width=2, dashed=True)
                self.position_badges.append({"label": code, "xy": point})
            self.callouts.append(_Callout("SUPPORT PADS",
                                         [c.project(pads[0]["center_mm"])], _FIXTURE))
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
            self.callouts.append(_Callout(label if label.startswith("DATUM ") else "DATUM " + label,
                                         [point]))
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
        _text(c, 32, self.footer_top - 36,
              f"ACTUAL STOCK BOX: X {_mm(sizes[0])}  /  Y {_mm(sizes[1])}"
              f"  /  Z {_mm(sizes[2])} mm")
        axis = 2 if self.view == "lathe" else 0
        first, second = list(_centre(box)), list(_centre(box))
        first[axis], second[axis] = box[axis], box[axis + 3]
        a, b = c.project(first), c.project(second)
        c.line(a, (a[0], y), _MUTED, width=2, dashed=True)
        c.line(b, (b[0], y), _MUTED, width=2, dashed=True)
        _dimension(c, (a[0], y), (b[0], y),
                   f"STOCK {'XYZ'[axis]} {_mm(sizes[axis])} mm")
        jaw = self.spec.get("jaw_front_z_mm")
        if jaw is not None:
            plane = [(box[0], box[1], jaw), (box[3], box[1], jaw),
                     (box[3], box[4], jaw), (box[0], box[4], jaw)]
            pixels = [c.project(p) for p in plane]
            if self.view == "lathe":
                x = pixels[0][0]
                _, top, _, bottom = _bounds(self.stock_pixels)
                c.line((x, top - 24), (x, bottom + 24), _BLUE, width=2, dashed=True)
                anchor = (x, top - 24)
            else:
                _outline(c, pixels, _BLUE, width=2, dashed=True)
                anchor = pixels[0]
            self.callouts.append(_Callout(f"JAW FRONT Z {_mm(jaw)} mm", [anchor], _BLUE))
        stickout = self.spec.get("stickout_mm")
        if stickout is not None:
            if jaw is not None and self.view == "lathe":
                # The declared distance is shown from the declared jaw front,
                # not reverse-engineered from a guessed fixture contact point.
                start = (_centre(box)[0], _centre(box)[1], jaw)
                end = (start[0], start[1], box[5])
                a, b = c.project(start), c.project(end)
                dim_y = 622
                c.line(a, (a[0], dim_y), _BLUE, width=2, dashed=True)
                c.line(b, (b[0], dim_y), _BLUE, width=2, dashed=True)
                _dimension(c, (a[0], dim_y), (b[0], dim_y),
                           f"STICKOUT {_mm(stickout)} mm", _BLUE)
            else:
                _text(c, 1126, self.footer_top - 36,
                      f"STICKOUT {_mm(stickout)} mm", _BLUE, align="right")

    def _labels(self):
        c = self.canvas
        lanes = [[], []]
        for callout in self.callouts:
            side = 0 if callout.points[0][0] < 590 else 1
            lanes[side].append(callout)
        lane_specs = ((32, 214, 249), (928, 210, 916))
        capacities = []
        for x, width, _ in lane_specs:
            intervals = sorted((max(202, b[1]), min(self.footer_top - 64, b[3]))
                               for b in self.obstacles if x < b[2] and x + width > b[0])
            blocked, end = 0, 202
            for top, bottom in intervals:
                if bottom > max(top, end):
                    blocked += bottom - max(top, end)
                    end = bottom
            capacities.append(self.footer_top - 64 - 202 - blocked)

        def cost(items, side):
            return sum(len(_wrap(c, item.label, lane_specs[side][1], scale=3)) * 27 + 11
                       for item in items)

        # Balance wrapped height rather than raw label count before reducing type.
        for _ in self.callouts:
            source = max((0, 1), key=lambda side: cost(lanes[side], side) - capacities[side])
            if cost(lanes[source], source) <= capacities[source]:
                break
            target = 1 - source
            candidates = [item for item in lanes[source]
                          if cost(lanes[target] + [item], target) <= capacities[target]]
            if not candidates:
                break
            moved = min(candidates, key=lambda item: abs(item.points[0][0] - 590))
            lanes[source].remove(moved)
            lanes[target].append(moved)
        for side, callouts in enumerate(lanes):
            callouts.sort(key=lambda item: item.points[0][1])
            x, width, edge = lane_specs[side]
            obstacles = sorted((b for b in self.obstacles if x < b[2] and x + width > b[0]),
                               key=lambda b: b[1])
            scale = 3
            labels = [_wrap(c, item.label, width, scale=scale) for item in callouts]

            def pack(gap, current_labels, current_scale, current_obstacles):
                rows, row_y = [], 202
                for lines in current_labels:
                    height = len(lines) * (9 * current_scale) + 6
                    for _, top, _, bottom in current_obstacles:
                        if row_y < bottom and row_y + height > top:
                            row_y = bottom + 10
                    rows.append(row_y)
                    row_y += height + gap
                return rows, row_y - gap

            # Dense fixture keys use the smaller body face only when necessary;
            # no label may spill into dimensions, a context symbol or the footer.
            if pack(5, labels, scale, obstacles)[1] > self.footer_top - 64:
                scale = 2
                labels = [_wrap(c, item.label, width, scale=scale) for item in callouts]
            lo, hi = 5.0, 60.0
            for _ in range(12):
                gap = (lo + hi) / 2
                if pack(gap, labels, scale, obstacles)[1] <= self.footer_top - 64:
                    lo = gap
                else:
                    hi = gap
            rows, _ = pack(lo, labels, scale, obstacles)
            for item, lines, row_y in zip(callouts, labels, rows, strict=True):
                target_y = row_y + (len(lines) * 9 * scale - 3 * scale) / 2
                for point in item.points:
                    elbow = (edge + (14 if side == 0 else -14), point[1])
                    c.line(point, elbow, item.colour, width=2)
                    c.line(elbow, (edge, target_y), item.colour, width=2)
                    c.circle(*point, 3, fill=item.colour)
                for index, line in enumerate(lines):
                    _text(c, x + width if side else x, row_y + index * 9 * scale,
                          line, item.colour, scale=scale,
                          align="right" if side else "left", backing=True)

    def _insets(self):
        c = self.canvas
        left, right = 1174, 1568
        c.line((1157, 134), (1157, self.footer_top - 17), _RULE, width=2)
        profiles = self.spec.get("lathe_profiles", []) if self.view == "lathe" else []
        if profiles or (self.view == "lathe" and (self.spec.get("axial_paths")
                       or any("xz" in p for p in self.spec.get("waypoints", [])))):
            top = self._lathe_detail(left, right, profiles) + 24
            if not self.spec.get("paths") and not any(
                "xy" in p for p in self.spec.get("waypoints", [])
            ):
                _text(c, left, top, "NO PATH SIMULATION", _MUTED)
            else:
                self._path_inset(left, right, top, self.footer_top - 70)
        else:
            self._path_inset(left, right, 142, self.footer_top - 70)
        if self.spec.get("preload") == "counterclockwise":
            center = (left + 17, self.footer_top - 37)
            arc = [(center[0] + 13 * math.cos(a), center[1] - 13 * math.sin(a))
                   for a in (i * math.pi / 12 for i in range(2, 23))]
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

        paths = [(path, [radial(p, path.get("x_display", "radius")) for p in path["xz"]])
                 for path in axial]
        waypoints = [{"label": p["label"], "xy": radial(p["xz"],
                      p.get("x_display", display.get(str(p.get("op")), "radius")))}
                     for p in self.spec.get("waypoints", []) if "xz" in p]
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
        window_scale = 3 if c.text_width(window_label, scale=3) <= right - left else 2
        _text(c, left, 198, window_label, _MUTED, scale=window_scale)
        scale = min((right - left - 134) / max(zmax - zmin, 1e-9),
                    234 / max(rmax - rmin, 1e-9))
        cx, cy = (left + right) / 2, 355

        def project(point):
            return (cx + (point[1] - (zmin + zmax) / 2) * scale,
                    cy - (point[0] - (rmin + rmax) / 2) * scale)

        closed = [(profile, line) for profile in profiles for line in profile["lines"]
                  if len(line) >= 4 and line[0] == line[-1]]
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
                    c.line(project(a), project(b), colour, width=3,
                           dashed=profile["label"] == "arriving stock")
            c.line((left, row + 10), (left + 25, row + 10), colour, width=3,
                   dashed=profile["label"] == "arriving stock")
            for line in _wrap(c, profile["label"].upper(), right - left - 34, scale=3):
                _text(c, left + 34, row, line, colour)
                row += 30
        for path, points in paths:
            window = (project((0, zmin))[0], 228, project((0, zmax))[0], 493)
            self._ordered_path([project(p) for p in points], _GREEN, clip=window)
            for line in _wrap(c, f"OP {path['op']} SURFACE", right - left - 34, scale=3):
                c.line((left, row + 10), (left + 25, row + 10), _GREEN, width=3)
                _text(c, left + 34, row, line, _GREEN)
                row += 30
        self._waypoint_badges(waypoints, project, (left, 205, right, 493))
        if paths:
            _text(c, left, row, "ARROWS: POINT ORDER", _MUTED)
            row += 30
        if closed:
            _text(c, left, row, "TINT: PROFILE DIFFERENCE", _AMBER, scale=2)
            row += 24
        if self.off_window_keys:
            _text(c, left, row, "OFF-WINDOW P KEYS: FULL VIEW", _MUTED, scale=2)
            row += 24
        return row

    def _path_inset(self, left, right, top, bottom):
        c = self.canvas
        _text(c, left, top, "PROFILE SKETCH / XY")
        _text(c, left, top + 30, "NO PATH SIMULATION", _MUTED)
        if self.nominal:
            _text(c, left, top + 54, "NOMINAL OUTLINE UNDERLAY", _MUTED, scale=2)
        paths = self.spec.get("paths", [])
        waypoints = [p for p in self.spec.get("waypoints", []) if "xy" in p]
        ops = list(dict.fromkeys(str(p.get("op", "")) for p in paths + waypoints))
        if len(ops) > 1:
            self._operation_panels(left, right, top + 68, bottom - 34, ops, paths, waypoints)
            _text(c, left, bottom - 21, "ARROWS: POINT ORDER", _MUTED)
            return
        points = [point for path in paths for point in path["xy"]]
        points.extend(item["xy"] for item in waypoints)
        if not points:
            _text(c, left, top + 69, "Paths not declared.", _MUTED)
            return
        xmin, ymin, xmax, ymax = _bounds(points)
        ops = list(dict.fromkeys(_plain(path.get("op", "")) for path in paths))
        key_lines = [
            (op, line) for op in ops
            for line in _wrap(c, op, right - left - 36, scale=3)
        ]
        plot_top, plot_bottom = top + 82, bottom - 40 - 30 * len(key_lines)
        scale = min((right - left - 74) / max(xmax - xmin, 1e-9),
                    max(50, plot_bottom - plot_top - 28) / max(ymax - ymin, 1e-9))
        cx, cy = (left + right) / 2, (plot_top + plot_bottom) / 2

        def project(point):
            return (cx + (point[0] - (xmin + xmax) / 2) * scale,
                    cy - (point[1] - (ymin + ymax) / 2) * scale)

        if self.nominal:
            self._nominal_overlay(lambda p: project(p[:2]),
                                  (left, plot_top, right, plot_bottom), faint=True)
        palette = (_BLUE, _GREEN, _AMBER, (113, 65, 137))
        colours = {op: palette[index % len(palette)] for index, op in enumerate(ops)}
        for path in paths:
            colour = colours[_plain(path.get("op", ""))]
            self._ordered_path([project(point) for point in path["xy"]], colour)
        self._waypoint_badges(waypoints, project, (left, plot_top, right, plot_bottom))
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
            _outline(c, [(x, y), (x + width, y), (x + width, y + height), (x, y + height)],
                     _RULE, width=1)
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
            factor = min((width - 72) / max(span_x, 1e-9),
                         max(12, plot_bottom - plot_top) / max(span_y, 1e-9))
            factor_y = factor
            badge_top = y + 31
            exclusion = None
            # Keep the dense six-panel grid unchanged. Shallow wider panels can
            # instead use a declared, unequal graphic scale and exterior P keys.
            if rows <= 2 and 0 < span_y * factor < 24 and span_x * factor >= 60:
                key_width = max(
                    [24] + [c.text_width(p["label"], scale=2) + 12 for p in op_waypoints]
                )
                key_columns = max(1, int((width - 4) / (key_width + 8)))
                key_rows = math.ceil(len(op_waypoints) / key_columns)
                upper_rows = math.ceil(key_rows / 2)
                lower_rows = key_rows - upper_rows
                badge_top = y + 46
                plot_top = badge_top + 26 * upper_rows + 8 * max(0, upper_rows - 1) + 8
                plot_bottom = (
                    y + height - 6 - 26 * lower_rows - 8 * max(0, lower_rows - 1) - 8
                )
                if plot_bottom - plot_top >= 24:
                    # Limit graphic distortion even when the key bands leave ample space.
                    factor_y = min((plot_bottom - plot_top) / span_y, 4 * factor)
                    _text(c, x + 8, y + 30, f"Y EXAG x{_mm(factor_y / factor)}",
                          _MUTED, scale=2)
                    exclusion = (x + 7, plot_top, x + width - 7, plot_bottom)
                else:
                    plot_top, plot_bottom = y + 66, y + height - 44
                    badge_top = y + 31
            cx, cy = x + width / 2, (plot_top + plot_bottom) / 2
            project = _xy_projector(bounds, (cx, cy), (factor, factor_y))

            if self.nominal:
                self._nominal_overlay(
                    project, (x + 7, plot_top, x + width - 7, plot_bottom), faint=True,
                )
            direction_keys = {0, len(op_paths) // 2, len(op_paths) - 1}
            for path_index, path in enumerate(op_paths):
                self._ordered_path([project(p) for p in path["xy"]], colour, width=2,
                                   arrows=path_index in direction_keys)
            self._waypoint_badges(
                op_waypoints, project,
                (x + 6, badge_top, x + width - 6, y + height - 6),
                colour=colour, perimeter=True, exclusion=exclusion,
            )

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
                    return (a[0] + (b[0] - a[0]) * fraction,
                            a[1] + (b[1] - a[1]) * fraction)
                distance -= length
            return segments[-1][1]

        for run in runs:
            length = sum(segment[2] for segment in run)
            if length < 14:
                continue
            count = max(1, min(3, int(length / 36)))
            half_span = min(9, length / (2 * count))
            for index in range(count):
                distance = (index + .5) * length / count
                tail = point_at(run, distance - half_span)
                tip = point_at(run, distance + half_span)
                c.arrow(tail, tip, colour, width=width)

    def _waypoint_badges(
        self, waypoints, project, plot, prefix="P", colour=_BLUE, perimeter=False,
        exclusion=None,
    ):
        """Pack disjoint cells, optionally wholly above/below projected geometry."""
        if not waypoints:
            return
        c = self.canvas
        left, top, right, bottom = plot
        labels = [_plain(item["label"]) for item in waypoints]
        labels = [prefix + label if prefix and not label.upper().startswith(prefix) else label
                  for label in labels]
        span_x, span_y = right - left, bottom - top
        for scale in (3, 2, 1):
            cell_width = max(24, max(c.text_width(label, scale=scale) for label in labels) + 12)
            cell_height = 7 * scale + 12
            columns = max(1, int((span_x + 8) / (cell_width + 8)))
            if perimeter and exclusion is None:
                columns = min(columns, math.ceil(math.sqrt(len(labels))))
            required_rows = math.ceil(len(labels) / columns)
            if exclusion is not None:
                upper_bottom = min(bottom, exclusion[1] - 8)
                lower_top = max(top, exclusion[3] + 8)
                upper_rows = max(0, int((upper_bottom - top + 8) / (cell_height + 8)))
                lower_rows = max(0, int((bottom - lower_top + 8) / (cell_height + 8)))
                if upper_rows + lower_rows >= required_rows:
                    break
            elif cell_height * required_rows + 8 * (required_rows - 1) <= span_y:
                break
        if exclusion is not None:
            # Work outward from the exact projected boundary, never over the part.
            ys = [
                upper_bottom - cell_height / 2 - i * (cell_height + 8)
                for i in range(upper_rows)
            ]
            ys.extend(
                lower_top + cell_height / 2 + i * (cell_height + 8)
                for i in range(lower_rows)
            )
        else:
            rows = required_rows if perimeter else max(
                required_rows, int((span_y + 8) / (cell_height + 8))
            )
            ys = [top + cell_height / 2 + i * (span_y - cell_height) / (rows - 1)
                  for i in range(rows)] if rows > 1 else [(top + bottom) / 2]
        xs = [left + cell_width / 2 + i * (span_x - cell_width) / (columns - 1)
              for i in range(columns)] if columns > 1 else [(left + right) / 2]
        available = [(x, y) for y in ys for x in xs]
        placed = []
        for item, label in zip(waypoints, labels, strict=True):
            point = project(item["xy"])
            target = (point[0], point[1] - cell_height / 2 - 12)
            badge = min(available, key=lambda p: math.dist(p, target))
            available.remove(badge)
            placed.append((badge, label, point, item.get("colour", colour)))
        top_points = (
            exclusion[1] if exclusion is not None
            else min(point[1] for _, _, point, _ in placed)
        )
        bottom_points = (
            exclusion[3] if exclusion is not None
            else max(point[1] for _, _, point, _ in placed)
        )
        upper_index = lower_index = 0
        for badge, _, point, point_colour in placed:
            if perimeter or exclusion is not None:
                above = badge[1] < point[1]
                edge = (badge[0], badge[1] + (cell_height / 2 if above else -cell_height / 2))
                if above:
                    guide = top_points - 7 - 3 * upper_index
                    upper_index += 1
                else:
                    guide = bottom_points + 7 + 3 * lower_index
                    lower_index += 1
                c.line(point, (point[0], guide), _MUTED, width=2)
                c.line((point[0], guide), (edge[0], guide), _MUTED, width=2)
                c.line((edge[0], guide), edge, _MUTED, width=2)
            else:
                c.line(point, badge, _MUTED, width=2)
            c.circle(*point, 3, fill=point_colour)
        for badge, label, _, badge_colour in placed:
            _badge(c, badge, label, badge_colour, scale=scale)

    def _footer(self):
        c = self.canvas
        c.line((32, self.footer_top), (1568, self.footer_top), _INK, width=2)
        self._triad(112, self.footer_top + 125)
        _text(c, 273, self.footer_top + 23, "KEY")
        legend_scale = 3 if len(self.legend_rows) <= 8 else 2
        legend_start = self.footer_top + 57
        legend_pitch = min(30, (984 - legend_start - 7 * legend_scale)
                           / max(1, len(self.legend_rows) - 1))
        for index, (label, kind) in enumerate(self.legend_rows):
            y = legend_start + index * legend_pitch
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
            _text(c, 318, y, label, _MUTED if kind == "text" else _INK, scale=legend_scale)
        _text(c, 840, self.footer_top + 23, "SETUP NOTES")
        note_start = self.footer_top + 57
        note_pitch = min(9 * self.note_scale, (984 - note_start - 7 * self.note_scale)
                         / max(1, len(self.note_lines) - 1))
        for index, line in enumerate(self.note_lines):
            _text(c, 840, note_start + index * note_pitch, line, _MUTED,
                  scale=self.note_scale)

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
                _text(c, end[0] + (7 if dx >= 0 else -17),
                      end[1] + (4 if dy >= 0 else -17), label, colour)
        if normal_axis is not None:
            direction = "TOWARD" if toward[normal_axis] > 0 else "AWAY"
            _text(c, 32, self.footer_top + 190, f"{'XYZ'[normal_axis]} {direction}", _MUTED)
        else:
            c.circle(37, self.footer_top + 197, 6, fill=_WHITE, outline=_MUTED)
            c.circle(37, self.footer_top + 197, 2, fill=_MUTED)
            _text(c, 49, self.footer_top + 190, "VIEW NORMAL", _MUTED)


def render_diagram(meshes, spec):
    """Return a 1600 x 1000 setup PNG without inventing physical dimensions.

    ``meshes`` contain numeric setup-frame XYZ triples, triangle index triples,
    RGB and optionally a removal-hatch flag. ``spec`` is the kernel's plain JSON
    diagram record; optional ``lathe_profiles`` contain exact [radius, Z] lines.
    """
    return _Diagram(meshes, spec).render()
