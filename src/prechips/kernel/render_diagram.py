"""Print-oriented setup diagrams from placed meshes and explicit shop-floor facts.

All millimetre measurements come from ``spec``. Outlined machine/table context is
screen-space symbolism, deliberately separate from the modelled fixture geometry.
"""

import math
import re
from collections import defaultdict
from dataclasses import dataclass, replace
from decimal import ROUND_HALF_UP, Context, Decimal

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
_BODY_SCALE = 5
_TITLE_SCALE = _BODY_SCALE + 1
_TEXT_HEIGHT = 7 * _BODY_SCALE
_LEADING = 9 * _BODY_SCALE
_BADGE_PAD = 2 * _BODY_SCALE
_BADGE_HEIGHT = _TEXT_HEIGHT + 2 * _BADGE_PAD
_BADGE_GAP = 2 * _BODY_SCALE
_BADGE_PITCH = _BADGE_HEIGHT + _BADGE_GAP
# At 7.5 inches wide this leaves room for the traveler's continuation header and caption.
_PANEL_MAX_HEIGHT = 1792
_FOOTER_TEXT_TOP = 88
_FOOTER_BOTTOM_PAD = 16
# Legend text starts at 380; reserve a 60 px inner gutter before notes at 960.
_FOOTER_LEGEND_WIDTH = 520
# Same deliberate outer margin as the full-width panel's left and right content.
_PROFILE_BOTTOM_PAD = 32
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
_KEY_ROOM_PX = 2 * _BADGE_HEIGHT
# Height of a lathe window shrunk to orientation so its crowded contour's detail has room.
_ORIENTATION_PX = 70
# The legend a path sketch prints once it has drawn a direction arrow.
_ARROWS = "ARROWS: POINT ORDER"
# A raster of at most this many passes draws and labels every pass; a longer one is a band
# with its first and last pass.
_EVERY_PASS = 8
# The least height a profile sketch's plot keeps between its key rows; a picture whose
# sketches cannot all keep it grows taller.
_SKETCH_PLOT_MIN = 30
# The legend a path sketch prints once it has drawn a raster's lifted return: the cycle
# is one way (feed a pass, lift, rapid back to the next pass's start).
_RETURNS = "DASHED: LIFTED RETURN"


def _lifted_returns(paths):
    """(from, to) XY of each rapid return between consecutive raster passes a sketch draws
    whole: the end of pass n to the start of pass n + 1 of the same op, when both run in a
    known direction. A band showing only its first and last pass draws none."""
    returns = []
    for op in dict.fromkeys(str(path.get("op", "")) for path in paths):
        raster = sorted(
            (p for p in paths if p.get("raster") and str(p.get("op", "")) == op),
            key=lambda p: p["raster"]["pass"],
        )
        keep_out = any(path["raster"].get("keep_out") for path in raster)
        if len(raster) > _EVERY_PASS and not keep_out:
            continue
        for before, after in zip(raster, raster[1:], strict=False):
            if (
                after["raster"]["pass"] == before["raster"]["pass"] + 1
                and before.get("directed") is True
                and after.get("directed") is True
            ):
                returns.append((before["xy"][-1], after["xy"][0]))
    return returns


def _labelled_passes(numbers):
    """The raster pass numbers a sketch labels: every one up to :data:`_EVERY_PASS`, else
    the first and the last."""
    numbers = sorted(numbers)
    return (
        numbers if len(numbers) <= _EVERY_PASS else list(dict.fromkeys(numbers[:1] + numbers[-1:]))
    )


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
# A setup picture whose view direction is within about 8 degrees of a guided file's
# guide axis already looks along it: it gets no second look down that axis.
_ALONG_COS = 0.99


@dataclass
class _Callout:
    label: str
    points: list
    colour: tuple = _INK
    # "line": a leader from the lane to the point; "keyed": the point carries its own
    # position badge, so the lane entry is the badge's key and draws no leader; "hidden":
    # a leader to an open ring on the dashed outline of a solid hidden in this view.
    leader: str = "line"
    # Mesh tags of the drawn solids the label names: its leader must end on one of them.
    targets: tuple = ()
    # A "hidden" callout's dashed outlines, one per point: each leader ends on its outline
    # where it faces the label.
    outlines: tuple = ()
    # Points of a drawn line the leader may end on instead (the finished outline's): it
    # ends on the one its lane reaches by the shortest clear run.
    along: tuple = ()
    # The label each point reads when it is keyed alone: a key naming several points
    # together ("BOTH ... RIMS") that is split to keep its leaders apart names each one.
    each: tuple = ()

    def part(self, indices):
        """This callout keyed at its points ``indices`` only."""
        alone = len(indices) == 1 and self.each
        return replace(
            self,
            label=self.each[indices[0]] if alone else self.label,
            points=[self.points[i] for i in indices],
            outlines=tuple(self.outlines[i] for i in indices) if self.outlines else (),
            each=tuple(self.each[i] for i in indices) if self.each else (),
        )


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


def decimal_text(value, places):
    """``value`` printed at ``places`` decimals as the shop rounds its written decimal: a
    half-way value rounds away from zero on the float's own shortest decimal, never on its
    binary expansion (2.8045 at three places is 2.805, not 2.804); zero prints unsigned.
    The one rounding of a printed decimal, in pictures and sheet tables alike."""
    exact = Decimal(repr(float(value)))
    step = Decimal(1).scaleb(-places)
    text = f"{exact.quantize(step, ROUND_HALF_UP, Context(prec=400)):f}"
    return text.removeprefix("-") if float(text) == 0 else text


def _mm(value):
    return decimal_text(value, 2).rstrip("0").rstrip(".")


def _dro(value, decimals):
    """A setup coordinate or clearance as the traveler's tables print it
    (``_Traveler.operative``): at the setup's DRO ``decimals`` when the spec names them,
    so a picture and its table never show one value rounded two ways; else :func:`_mm`."""
    if not isinstance(decimals, int) or isinstance(decimals, bool) or decimals < 0:
        return _mm(value)
    return decimal_text(value, decimals)


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


def _drawn_box(project, points):
    """The pixel box of a sketch's projected ``points``, 2 px out: what its keys clear."""
    xmin, ymin, xmax, ymax = _bounds([project(point) for point in points])
    return (xmin - 2, ymin - 2, xmax + 2, ymax + 2)


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


def dro_steps(value, step):
    """The whole DRO steps of ``step`` nearest ``value``, as the shop sets them: half a
    step rounds away from zero, and float noise in the quotient does not count. The one
    rounding of a printed DRO position, in pictures and fixture tables alike."""
    quotient = round(value / step, 6)
    return math.copysign(math.floor(abs(quotient) + 0.5), quotient)


def _code_ranges(codes):
    """Position codes as a drawing lists them: ``L1-L6, R1-R6``; a run of three or more
    consecutive numbers under one prefix is a range, others are listed."""
    groups = defaultdict(set)
    for code in codes:
        match = re.fullmatch(r"(.*?)(\d+)", code)
        prefix, number = (match[1], int(match[2])) if match else (code, None)
        groups[prefix].add(number)
    parts = []
    for prefix in sorted(groups):
        numbers = sorted(n for n in groups[prefix] if n is not None)
        if None in groups[prefix]:
            parts.append(prefix)
        runs = []
        for number in numbers:
            if runs and number == runs[-1][-1] + 1:
                runs[-1].append(number)
            else:
                runs.append([number])
        for run in runs:
            if len(run) >= 3:
                parts.append(f"{prefix}{run[0]}-{prefix}{run[-1]}")
            else:
                parts.extend(f"{prefix}{n}" for n in run)
    return ", ".join(parts)


def _dot3(a, b):
    return sum(x * y for x, y in zip(a, b, strict=True))


class _Measure:
    """Bitmap text widths before a canvas exists (a band's header sized up front)."""

    text_width = RenderCanvas.text_width


_MEASURE = _Measure()


def _wrap(canvas, text, width, scale=_BODY_SCALE):
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


def _leader_segments(path, reserved, radius):
    """Visible leader fragments outside text backing; round caps stay outside it too."""
    for a, b in zip(path, path[1:], strict=False):
        dx, dy = b[0] - a[0], b[1] - a[1]
        if dx == dy == 0:
            if not any(
                left - radius <= a[0] <= right + radius and top - radius <= a[1] <= bottom + radius
                for left, top, right, bottom in reserved
            ):
                yield a, b
            continue
        axis = 0 if abs(dx) >= abs(dy) else 1
        delta = (dx, dy)[axis]
        covered = []
        for left, top, right, bottom in reserved:
            clipped = _clip_segment(
                a, b, (left - radius, top - radius, right + radius, bottom + radius)
            )
            if clipped:
                covered.append(tuple((point[axis] - a[axis]) / delta for point in clipped))
        cursor = 0.0
        for low, high in sorted(covered):
            if low > cursor:
                yield (
                    (a[0] + cursor * dx, a[1] + cursor * dy),
                    (a[0] + low * dx, a[1] + low * dy),
                )
            cursor = max(cursor, high)
        if cursor < 1:
            yield (
                (a[0] + cursor * dx, a[1] + cursor * dy),
                b,
            )


def _badge_width(canvas, label, scale=_BODY_SCALE):
    return max(5 * scale + 2 * _BADGE_PAD, canvas.text_width(label, scale=scale) + 2 * _BADGE_PAD)


def _badge(canvas, point, label, colour=_BLUE, scale=_BODY_SCALE):
    width = _badge_width(canvas, label, scale)
    height = 7 * scale + 2 * _BADGE_PAD
    x, y = point[0] - width / 2, point[1] - height / 2
    canvas.rect(x, y, width, height, _WHITE)
    _outline(canvas, [(x, y), (x + width, y), (x + width, y + height), (x, y + height)], colour)
    _text(canvas, point[0], y + _BADGE_PAD, label, colour, scale=scale, align="centre")


def _rows_for(widths, span):
    """Fewest interleaved badge rows (every n-th badge per row) that fit ``span``."""
    for rows in range(1, len(widths) + 1):
        if all(
            sum(w + _BADGE_GAP for w in widths[row::rows]) - _BADGE_GAP <= span
            for row in range(rows)
        ):
            return rows
    return 0


def _row_positions(targets, widths, left, right):
    """Badge centres in one row, in the targets' order, with a type-sized gap, inside
    ``left``..``right`` and of least squared displacement from the targets."""
    offsets = [0.0]
    for first, second in zip(widths, widths[1:], strict=False):
        offsets.append(offsets[-1] + (first + second) / 2 + _BADGE_GAP)
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


def _band_sides(points, widths, span, capacity):
    """Each point's band, -1 above the geometry or 1 below it, and left-to-right order.
    Off-band points key on their own side; neighbours alternate, then rebalance to fit."""
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
        return _rows_for([widths[index] for index in order if sides[index] == side], span)

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
    return sides, order


def _band_rows(points, widths, span):
    """``(rows above, rows below)`` :func:`_band_cells` prints ``points`` in when each
    band has room for every row: what a sketch reserves before it scales its geometry."""
    if not points:
        return 0, 0
    room = {-1: len(points), 1: len(points)}
    sides, order = _band_sides(points, widths, span, room)
    return tuple(
        _rows_for([widths[index] for index in order if sides[index] == side], span)
        for side in (-1, 1)
    )


def _band_cells(points, widths, plot, exclusion):
    """Badge centres in rows wholly above and below ``exclusion``. Neighbouring points on
    the geometry's mid band alternate between the bands; each row keeps its points' left
    to right order directly above or below them, so the leaders fan out without crossing
    and every badge stays beside its own support, clamp or pickup."""
    left, top, right, bottom = plot
    height, pitch = _BADGE_HEIGHT, _BADGE_PITCH
    upper_bottom = min(bottom, exclusion[1] - _BADGE_GAP)
    lower_top = max(top, exclusion[3] + _BADGE_GAP)
    capacity = {
        -1: max(0, int((upper_bottom - top + _BADGE_GAP) / pitch)),
        1: max(0, int((bottom - lower_top + _BADGE_GAP) / pitch)),
    }
    sides, order = _band_sides(points, widths, right - left, capacity)
    centres = [None] * len(points)
    for side, edge in ((-1, upper_bottom), (1, lower_top)):
        members = [index for index in order if sides[index] == side]
        rows = _rows_for([widths[index] for index in members], right - left)
        if (members and rows == 0) or rows > capacity[side]:
            raise ValueError("position badges do not fit beside their geometry at print size")
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


def _sketch_keys(paths, waypoints):
    """The profile sketch's keys for one operation's ``paths`` and ``waypoints``, as
    ``[(label, xy)]`` in sketch XY: each point's P key and each labelled raster pass's
    (:meth:`_Diagram._raster_band`), where the sketch prints them."""
    keys = []
    for item in waypoints:
        label = _plain(item["label"])
        keys.append((label if label.upper().startswith("P") else "P" + label, item["xy"]))
    raster = [path for path in paths if path.get("raster")]
    numbers = _labelled_passes([path["raster"]["pass"] for path in raster])
    for path in sorted(raster, key=lambda p: p["raster"]["pass"]):
        number = path["raster"]["pass"]
        if number in numbers:
            keys.append(
                (f"PASS {number}", _pass_anchor(path["xy"], numbers.index(number), numbers))
            )
    return keys


def _pass_anchor(xy, rank, numbers):
    """Where a labelled raster pass's key leads: ``(rank + 1) / (len(numbers) + 1)`` along
    the pass, so stacked passes' leaders reach them at staggered points, never one
    leader running through the next pass's anchor."""
    a, b = xy[0], xy[-1]
    t = (rank + 1) / (len(numbers) + 1)
    return (a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t)


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
        (first[1] + second[1]) / 2 - _TEXT_HEIGHT - 8,
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


def _dash_segments(polylines, project, clip=None):
    """Clipped on-dash fragments, retaining phase across tessellated chords of an edge."""
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
                        yield segment
                distance += run
                phase = (phase + run) % 14


def _dashed(canvas, polylines, project, colour, clip=None, halo_width=0):
    """Paint every halo before any ink, without filling the hidden edge's dash gaps."""
    segments = _dash_segments(polylines, project, clip)
    if halo_width:
        segments = list(segments)
        for segment in segments:
            canvas.line(*segment, _WHITE, width=halo_width)
    for segment in segments:
        canvas.line(*segment, colour, width=2)


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


def _shoulder(z, small, large, decimals=None):
    return (
        f"SHOULDER Z {_dro(z, decimals)}: "
        f"DIA {_dro(2 * small, decimals)} / DIA {_dro(2 * large, decimals)}"
    )


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
    grows_to_fit = True
    splits_sides = True
    keyed_cut = False  # whether this picture keyed ``closest_cut`` (:meth:`_closest_cut`)

    def _dro(self, value):
        """``value`` as the traveler's tables print it (:func:`_dro`)."""
        return _dro(value, self.spec.get("decimals"))

    def __init__(self, meshes, spec, extra=0):
        """``extra`` grows only the main label lanes and moves their footer; the scene
        keeps its size and place. Independent sketches own their separate band growth."""
        self.spec = spec
        self.input_meshes = list(meshes)
        self.extra = extra
        self._measured_axes_height = None
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
        # Direction arrows drawn so far: a legend claims "ARROWS" only once one is drawn.
        self.arrows_drawn = 0
        self.returns_drawn = 0
        self.inset_overflow = 0
        self.width_overflow = 0
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
        self.meshes = list(self.input_meshes)
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
        # The complete setup and axes stay in one full-width print panel. Text-only
        # footer overflow gets complete continuation bands, never a smaller scene.
        self.footer_top = 1060 + extra
        self.scene_bottom = 740
        self.note_lines = self._notes()
        self.legend_rows = self._legend()
        self.axes_height = _FOOTER_TEXT_TOP + 320 + _FOOTER_BOTTOM_PAD
        height = self.footer_top + self.axes_height
        if height > _PANEL_MAX_HEIGHT:
            # Only the conservative reservation is being replaced, not any axes
            # primitive or body cell. Ordinary already-fitting frames stay unchanged.
            self.axes_height = self._axes_minimum()
            height = self.footer_top + self.axes_height
            if height > _PANEL_MAX_HEIGHT:
                maximum = _PANEL_MAX_HEIGHT - (self.footer_top - extra) - self.axes_height
                raise _setup_height_refusal(self, extra, maximum, None, height)
        capacity = _footer_capacity(self.footer_top)
        self.footer_legend_rows = len(self.legend_rows)
        self.footer_note_rows = len(self.note_lines)
        if max(self.footer_legend_rows, self.footer_note_rows) > capacity:
            # Primitive sketch callers need no setup identity; only actual setup-text
            # continuation needs the measured, setup-specific owner header.
            _, continuation_top = _footer_header(spec)
            whole_capacity = _footer_capacity(continuation_top)
            self.footer_legend_rows = _footer_end(self.legend_ends, 0, capacity, whole_capacity)
            self.footer_note_rows = _footer_end(self.note_ends, 0, capacity, whole_capacity)
        self.footer_rows = max(self.footer_legend_rows, self.footer_note_rows)
        height = self.footer_top + max(self.axes_height, _footer_height(self.footer_rows))
        self.dimension_y = self.footer_top - 146
        self.lanes = (290, self.footer_top - 140)
        self.lane_specs = ((32, 360, 410), (1208, 360, 1190))
        self.lane_split = 800
        viewport = (440, 380, 1160, self.scene_bottom)
        if self.view in ("plan", "elevation") and (
            any(component.get("code") for component in self.components)
            or any(_role(component) == "pad" for component in self.components)
        ):
            # Two real exterior badge bands, sized from the larger glyph cells.
            viewport = (440, 430, 1160, 630)
        self.viewport = viewport
        self.canvas = RenderCanvas(self.meshes, self.camera, viewport, height=height, fit=fit)
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

    def _lane_anchor(self, point, side, blocked):
        """A leader end moved, on the solid it lands on, to that solid's visible pixel
        nearest lane ``side`` whose run to the lane crosses the least of the work and no
        other key's point (``blocked``): a fixture's leader stops at its near edge instead
        of running over the work to its middle. ``point`` when it is no drawn solid's."""
        c = self.canvas
        tag = _tag_at(c, *point)
        if tag is None or self._owned is None:
            return point
        rows = {}
        for x, y in self._owned.get(tag, ()):
            near = rows.get(y)
            if near is None or (x < near if side == 0 else x > near):
                rows[y] = x
        bend = self.lane_specs[side][2] + (14 if side == 0 else -14)
        work = {"part", "removal"} - {tag}
        inward = 4 if side == 0 else -4
        steps = ((4, 0), (-4, 0), (0, 4), (0, -4))
        width, owner, tags = c.width, c.owner, c.tags

        def crossed(x, y):
            low, high = sorted((int(x), int(bend)))
            row = y * width
            return sum(
                1
                for column in range(max(low, 0), min(high, width))
                if owner[row + column] >= 0 and tags[owner[row + column]] in work
            )

        candidates = []
        for y, x in rows.items():
            spot = (x + inward + 0.5, y + 0.5)
            if all(_tag_at(c, spot[0] + dx, spot[1] + dy) == tag for dx, dy in steps):
                candidates.append(spot)
        candidates.sort(key=lambda p: (abs(bend - p[0]), abs(p[1] - point[1])))
        best = None
        for spot in candidates:
            if blocked(spot):
                continue
            score = crossed(*map(int, spot))
            if best is None or score < best[0]:
                best = (score, spot)
            if score == 0:
                break
        if best is None:
            return point
        # The point stays only when its own run is clear and crosses less of the work.
        if not blocked(point) and crossed(*map(int, point)) < best[0]:
            return point
        return best[1]

    def _hidden(self, label):
        self.render_debts.append(f"NOT SHOWN: {label} is hidden in this view, so it has no leader.")

    def _in_lathe_window(self, z):
        """Whether the jaw-end profile inset draws station ``z``."""
        return self.lathe_window is not None and self.lathe_window[0] <= z <= self.lathe_window[1]

    def _framed(self):
        """Components the view is scaled to. An isometric view frames the stock and the
        holding that touches it, at most 1.5x the stock's largest size: a vise or table
        many times the part's size is cropped, not allowed to shrink the work. A vise jaw
        that presses the work through touching holding (a round bar between the work and
        the moving jaw) is holding too."""
        if self.view != "isometric" or self.stock is None:
            return list(self.components)
        size = max(self.stock[i + 3] - self.stock[i] for i in range(3))
        pad = 0.25 * size
        frame = [self.stock[i] - pad for i in range(3)] + [
            self.stock[i + 3] + pad for i in range(3)
        ]

        def touches(box, other):
            return not any(
                box[i] > other[i + 3] + 1.0 or box[i + 3] < other[i] - 1.0 for i in range(3)
            )

        touching = [
            c["box_mm"]
            for c in self.components
            if c.get("box_mm") and touches(c["box_mm"], self.stock)
        ]
        framed = []
        for component in self.components:
            box = component.get("box_mm")
            if box is None:
                framed.append(component)
                continue
            pressing = _role(component) in ("fixed_jaw", "moving_jaw") and any(
                touches(box, other) for other in touching
            )
            if not touches(box, self.stock) and not pressing:
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
        # The tool and op tables name the selected tool; the picture labels it, so the
        # notes do not repeat it on every setup.
        notes = [_plain(note) for note in self.spec.get("notes", [])]
        if self.spec.get("zero_mm") is None:
            notes.append("Z0: not declared")
        if "datums" not in self.spec:
            notes.append("Datums: not declared")
        if self.is_chuck and self.spec.get("stickout_mm") is None:
            notes.append("Stickout: not declared")
        add = self.spec.get("stickout_add_mm")
        if self.spec.get("stickout_mm") is not None and add is not None:
            # Set from a measured fit-up: the dimension is the nominal; the note, in the
            # wrapping footer, says how it is set.
            notes.append(
                f"Stickout {self._dro(self.spec['stickout_mm'])} mm is nominal: "
                f"set it as the measured fit-up + {self._dro(add)} mm."
            )
        lines, self.note_ends = [], []
        for note in notes:
            lines.extend(_wrap(self.canvas, note, 608))
            self.note_ends.append(len(lines))
        return lines

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
                rows.append((text, "text"))
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
        wrapped, self.legend_ends = [], []
        for label, kind in rows:
            wrapped.extend((line, kind) for line in _wrap(self.canvas, label, _FOOTER_LEGEND_WIDTH))
            self.legend_ends.append(len(wrapped))
        return wrapped

    def render(self):
        self._header()
        self._context()
        if self.nominal:
            self._nominal_overlay(self.canvas.project)
            self.callouts.append(
                _Callout(
                    "FINISHED OUTLINE",
                    [self.canvas.project(self.nominal[0][0])],
                    _BLUE,
                    along=tuple(self.canvas.project(p) for line in self.nominal for p in line),
                )
            )
        self._components()
        self._origin_datums_tool()
        first_measurement = len(self.canvas.text_boxes)
        self._measurements()
        self.obstacles.extend(
            (left - 4, top - 4, right + 4, bottom + 4)
            for _, left, top, right, bottom in self.canvas.text_boxes[first_measurement:]
        )
        for z, small, large in self.shoulders:
            # A step too small to see at print scale is named with both diameters; the
            # jaw-end profile names the steps inside its window beside its own tick.
            if (large - small) * self.canvas.scale >= 3 or self._in_lathe_window(z):
                continue
            point = self.canvas.project((large, 0, z))
            label = _shoulder(z, small, large, self.spec.get("decimals"))
            self.callouts.append(_Callout(label, [point], _INK))
        if self.spec.get("key_closest_cut"):
            self._closest_cut()
        self._labels()
        if self.lane_overflow > 0:
            return self.canvas.png()
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
                (440, 280, 1160, self.footer_top - 210),
                prefix="",
                colour=_FIXTURE,
                exclusion=exclusion,
            )
        for x, y, label, scale in self.context_labels:
            _text(self.canvas, x, y, label, _MUTED, scale=scale, align="centre", backing=True)
        self._footer()
        self.canvas.assert_text_layout(min_scale=_BODY_SCALE)
        self.print_panels = [
            {"top_px": 0, "height_px": self.canvas.height, "role": "setup", "label": self._title()}
        ]
        self.annotation_details = []
        return self.canvas.png()

    def _title(self):
        return f"SETUP {self.spec['setup_id']}  /  {self.view.upper()} VIEW"

    def _header(self):
        c = self.canvas
        _text(c, 32, 27, self._title(), scale=_TITLE_SCALE)
        # The isometric orientation is its axes key, so it has no generator subtitle.
        subtitles = {
            "lathe": "SPINDLE Z TO RIGHT  /  RADIAL X UP  /  FULL ARRIVING STOCK",
            "plan": "SETUP X TO RIGHT  /  Y UP  /  VIEW FROM +Z",
            "elevation": self.spec.get("view_note", "SETUP Z UP"),
        }
        if self.view in subtitles:
            for index, line in enumerate(_wrap(c, subtitles[self.view], 1020)):
                _text(c, 34, 92 + index * _LEADING, line, _MUTED)
        _text(c, 1565, 92, "DIMENSIONS IN mm", _MUTED, align="right")
        c.line((32, 196), (1568, 196), _INK, width=2)
        _text(c, 32, 220, "PLACED STOCK + WORKHOLDING", _INK)
        if self.spec.get("preload") == "counterclockwise":
            center = (1055, 220 + _TEXT_HEIGHT / 2)
            arc = [
                (center[0] + 13 * math.cos(a), center[1] - 13 * math.sin(a))
                for a in (i * math.pi / 12 for i in range(2, 23))
            ]
            for a, b in zip(arc, arc[1:], strict=False):
                c.line(a, b, _FIXTURE, width=2)
            c.arrow(arc[-2], arc[-1], _FIXTURE, width=2)
            _text(c, 1568, 220, "CCW PRELOAD / +Z", _FIXTURE, align="right")

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
                self.obstacles.append((x - 100, y - _TEXT_HEIGHT - 16, x + 200, y + 130))
                self.context_labels.append(
                    (x + 47, y - _TEXT_HEIGHT - 10, "HEADSTOCK", _BODY_SCALE)
                )
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
                self.obstacles.append((x - 100, y - _TEXT_HEIGHT - 16, x + 200, y + 110))
                self.context_labels.append(
                    (x + 41, y - _TEXT_HEIGHT - 10, "TAILSTOCK", _BODY_SCALE)
                )

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
            if not points and all(
                _role(item) in ("fixed_jaw", "moving_jaw") and item.get("box_mm")
                for item in components
            ):
                # A vise jaw hidden behind the work is still the face the work seats on:
                # its box is drawn as a dashed hidden-position outline, its leader
                # stopping there, never on the work in front of it.
                outlines = tuple(self._box_outline(item) for item in components)
                points = [
                    _nearest_on_outline(outline, c.project(item["center_mm"]))
                    for outline, item in zip(outlines, components, strict=True)
                ]
                self.callouts.append(
                    _Callout(label.upper(), points, _FIXTURE, leader="hidden", outlines=outlines)
                )
                continue
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
        # A named void at numbered positions (a slot under each pad) is keyed by their
        # badges: its lane entry names them, and no second leader runs into a badged point.
        badged = [(badge["xy"], badge["label"]) for badge in self.position_badges]
        for index, callout in enumerate(self.callouts):
            if callout.leader != "line" or callout.targets or not badged:
                continue
            codes = [
                next((code for xy, code in badged if math.dist(xy, point) <= 3), None)
                for point in callout.points
            ]
            if None not in codes:
                self.callouts[index] = _Callout(
                    f"{callout.label} AT {_code_ranges(codes)}",
                    callout.points[:1],
                    callout.colour,
                    leader="keyed",
                )
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

    def _in_tile(self, point):
        """Whether a setup point lies inside this picture's viewport."""
        left, top, right, bottom = self.viewport
        x, y = self.canvas.project(point)
        return left <= x <= right and top <= y <= bottom

    def _closest_cut(self):
        """``closest_cut`` dimensioned and keyed ``CUT <mm> FROM <holder> (OP <op>)`` when its
        middle is this picture's to key (:meth:`_in_tile`); ``keyed_cut`` records that it
        was. The key names the op whose cut it is (a saw's blade path ``(SAW BLADE)`` when
        its op has no number); one the kernel did not name names no op."""
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
        label = f"CUT {self._dro(cut['mm'])} mm FROM {holder.upper()}"
        op = cut.get("op")
        if op not in (None, "", "unknown"):
            label += f" (OP {_plain(op).upper()})"
        elif cut.get("blade"):
            label += " (SAW BLADE)"
        self.callouts.append(_Callout(label, [middle], _AMBER))
        self.keyed_cut = True

    def _measurements(self):
        c = self.canvas
        y = self.dimension_y
        if self.stock is None:
            _text(c, 440, y - _TEXT_HEIGHT - 8, "STOCK EXTENTS: NOT DECLARED", _MUTED)
            return
        box = self.stock
        sizes = [box[i + 3] - box[i] for i in range(3)]
        # Round stock is its diameter (the stock dimension gives its length); a bounding box
        # describes only prismatic stock.
        round_dia = self.spec.get("stock_round_dia_mm")
        stock_text = (
            f"STOCK Ø {_mm(round_dia)} mm"
            if round_dia is not None
            else f"STOCK BOX: X {_mm(sizes[0])}  /  Y {_mm(sizes[1])}  /  Z {_mm(sizes[2])} mm"
        )
        summary = _wrap(c, stock_text, 1536)
        for index, line in enumerate(summary):
            _text(
                c,
                32,
                self.footer_top - 16 - _TEXT_HEIGHT - (len(summary) - 1 - index) * _LEADING,
                line,
            )
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
        dimensions = [(label, (a[0], y), (b[0], y), _INK)]
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
            self.callouts.append(_Callout(f"JAW FRONT Z {self._dro(jaw)} mm", [anchor], _BLUE))
        stickout = self.spec.get("stickout_mm")
        if stickout is not None:
            stickout_label = f"STICKOUT {self._dro(stickout)} mm"
            if self.spec.get("stickout_add_mm") is not None:
                # Set from a measured fit-up: the drawn value is the nominal (see notes).
                stickout_label = f"NOM {stickout_label}"
            if jaw_marker is not None and self.view == "lathe":
                # The declared distance runs from the jaw-front marker itself, on its own
                # row, never from the stock-length extension line.
                a = jaw_marker
                b = c.project((box[0], box[1], box[5]))
                dim_y = y - _LEADING - 16
                c.line(a, (a[0], dim_y), _BLUE, width=2, dashed=True)
                c.line(b, (b[0], dim_y), _BLUE, width=2, dashed=True)
                dimensions.append((stickout_label, (a[0], dim_y), (b[0], dim_y), _BLUE))
        # Extension lines from either row may run through the other row's lettering.
        # Finish every extension first, then mask and paint the complete text boxes.
        for label, first, second, colour in dimensions:
            _dimension(c, first, second, label, colour)
            self.dimensions[label] = (first, second)
        if stickout is not None and (jaw_marker is None or self.view != "lathe"):
            _text(c, 1568, y - _LEADING - 16, stickout_label, _BLUE, align="right", backing=True)

    def _labels(self):
        """Two lanes of print-size keys. Type never shrinks: lanes rebalance, then tighten
        their leading; a leader never runs along the axis through another callout."""
        c = self.canvas
        reserved = [
            (left - 4, top - 3, right + 4, bottom + 3)
            for _, left, top, right, bottom in c.text_boxes
        ]
        # A leader naming a drawn solid must end on that solid's visible pixels; one that
        # cannot is a render debt, never a printed leader to the wrong thing.
        kept = []
        for callout in self.callouts:
            if callout.leader == "line" and callout.targets:
                landed = [
                    index
                    for index, point in enumerate(callout.points)
                    if _lands_on(c, point, callout.targets)
                ]
                if not landed:
                    self._hidden(callout.label)
                    continue
                if len(landed) < len(callout.points):
                    callout = callout.part(landed)
            kept.append(callout)
        # A label naming points on both sides of the picture is keyed once in each lane,
        # each copy leading to its own side's points: no leader fans across the work. A
        # holding detail keys each contact once, so it keeps one key.
        self.callouts = []
        for callout in kept:
            sides = [[], []]
            for index, point in enumerate(callout.points):
                sides[0 if point[0] < self.lane_split else 1].append(index)
            if callout.leader == "keyed" or not all(sides) or not self.splits_sides:
                self.callouts.append(callout)
                continue
            for indices in sides:
                self.callouts.append(callout.part(indices))
        lane_specs = self.lane_specs
        limit = self.lanes[1]
        anchors = [(callout, point) for callout in self.callouts for point in callout.points]
        wrapped = {
            (id(item), side): _wrap(c, item.label, lane_specs[side][1])
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
                span = max(c.text_width(line, scale=_BODY_SCALE) for line in lines) + 8
                left, right = (
                    (x - 4, x - 4 + span) if side == 0 else (x + width + 4 - span, x + width + 4)
                )
                height = (len(lines) - 1) * pitch + _TEXT_HEIGHT + 6
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

        runs = {}

        def ordered(items):
            def height(item):
                ys = [y for y in runs.get(id(item), ()) if y is not None]
                ys = ys or [point[1] for point in item.points]
                return sum(ys) / len(ys)

            return sorted(items, key=height)

        def overflow(items, side):
            return pack(ordered(items), side, _LEADING, 8)[1] - limit

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

        # Each leader takes the shortest clear way to its lane. One naming a drawn solid
        # ends on that solid's pixels nearest the lane a clear run reaches, never across
        # the work; a run that would pass another key's point steps square off it; and a
        # key whose points lie either side of another key's run is keyed once per group of
        # its points, so no leader fans across another.
        def clear(item, point, side):
            # Its own run passes no other key's point, nor does it sit on another's run.
            bend = lane_specs[side][2] + (14 if side == 0 else -14)
            return not blocked(item, point, side) and not any(
                abs(other[1] - point[1]) < 6
                and min(other[0], bend) < point[0] < max(other[0], bend)
                and abs(other[0] - point[0]) > 1
                for owner in lanes[side]
                if owner is not item
                for other in owner.points
            )

        for side, items in enumerate(lanes):
            for item in items:
                if item.leader == "line" and item.targets:
                    item.points = [
                        self._lane_anchor(point, side, lambda p, i=item, s=side: not clear(i, p, s))
                        for point in item.points
                    ]
                elif item.leader == "line" and item.along and len(item.points) == 1:
                    bend = lane_specs[side][2] + (14 if side == 0 else -14)
                    here = item.points[0]
                    item.points = [
                        min(
                            item.along,
                            key=lambda p, i=item, s=side: (
                                not clear(i, p, s),
                                abs(bend - p[0]),
                                abs(p[1] - here[1]),
                            ),
                        )
                    ]
        anchors = [(callout, point) for callout in self.callouts for point in callout.points]

        def square_run(item, point, side):
            # The run's height: the point's own, or the nearest clear one a short square
            # step reaches; None when none does (the leader then runs straight).
            if not blocked(item, point, side):
                return point[1]
            for step in range(8, 81, 2):
                for y in (point[1] - step, point[1] + step):
                    # The step passes no other key's point on its way to the run.
                    near, far = (point[1] - 1, y - 6) if y < point[1] else (point[1] + 1, y + 6)
                    low, high = sorted((near, far))
                    if blocked(item, (point[0], y), side) or any(
                        abs(other[0] - point[0]) < 6
                        and low < other[1] < high
                        and math.dist(other, point) > 1
                        for owner, other in anchors
                        if owner is not item
                    ):
                        continue
                    return y
            return None

        for side, items in enumerate(lanes):
            for item in items:
                if item.leader == "line":
                    runs[id(item)] = [square_run(item, point, side) for point in item.points]
            for item in list(items):
                heights = runs.get(id(item))
                if not heights or len(heights) < 2 or None in heights:
                    continue
                others = [
                    y for other in items if other is not item for y in runs.get(id(other), ())
                ]
                order = sorted(range(len(heights)), key=lambda i: heights[i])
                groups = [[order[0]]]
                for previous, index in zip(order, order[1:], strict=False):
                    if any(heights[previous] < y < heights[index] for y in others if y):
                        groups.append([])
                    groups[-1].append(index)
                if len(groups) == 1:
                    continue
                items.remove(item)
                for group in groups:
                    part = item.part(group)
                    runs[id(part)] = [heights[i] for i in group]
                    wrapped[(id(part), side)] = _wrap(c, part.label, lane_specs[side][1])
                    items.append(part)
        # A band that can grow (the holding detail) is redrawn taller instead of
        # printing keys past its edge.
        self.lane_overflow = max(
            pack(ordered(items), side, _TEXT_HEIGHT + 5, 0)[1] - limit
            for side, items in enumerate(lanes)
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
                    for pitch, floor in (
                        (_LEADING, 8),
                        (_TEXT_HEIGHT + 5, 8),
                        (_TEXT_HEIGHT + 5, 0),
                    )
                    if pack(callouts, side, pitch, floor)[1] <= limit
                ),
                (_TEXT_HEIGHT + 5, 0),
            )
            lo, hi = float(floor), 60.0
            for _ in range(12):
                gap = (lo + hi) / 2
                if pack(callouts, side, pitch, gap)[1] <= limit:
                    lo = gap
                else:
                    hi = gap
            rows, _ = pack(callouts, side, pitch, lo)
            # Rows on whole pixels, so a wrapped key's lines stay one pitch apart once printed.
            rows = [math.floor(row_y) for row_y in rows]
            for item, row_y in zip(callouts, rows, strict=True):
                lines = wrapped[(id(item), side)]
                target_y = row_y + ((len(lines) - 1) * pitch + _TEXT_HEIGHT) / 2
                drawn = item.points if item.leader in ("line", "hidden") else []
                outlines = item.outlines or (None,) * len(drawn)
                heights = runs.get(id(item), [None] * len(drawn))
                for point, outline, height in zip(drawn, outlines, heights, strict=True):
                    end = (edge, target_y)
                    bend_x = edge + (14 if side == 0 else -14)
                    path = [point, end]
                    if outline:
                        # The ring sits where the hidden outline faces its label.
                        point = _nearest_on_outline(outline, end)
                        path = [point, end]
                        if not blocked(item, point, side):
                            path = [point, (bend_x, point[1]), end]
                    elif height is not None:
                        step = [(point[0], height)] if height != point[1] else []
                        path = [point, *step, (bend_x, height), end]
                    segments = list(
                        _leader_segments(path, reserved, 3 if item.colour == _CONTACT else 1)
                    )
                    if item.colour == _CONTACT:
                        for a, b in segments:
                            c.line(a, b, _WHITE, width=6)
                        c.circle(*point, 5, fill=_WHITE)
                    for a, b in segments:
                        c.line(a, b, item.colour, width=2)
                    if item.leader == "hidden":
                        c.circle(*point, 4, fill=_WHITE, outline=item.colour)
                        self.hidden_leaders.append((item.label, path))
                        continue
                    c.circle(*point, 3, fill=item.colour)
                    self.leaders.append((item.label, path))
                for index, line in enumerate(lines):
                    _text(
                        c,
                        x + width if side else x,
                        row_y + index * pitch,
                        line,
                        item.colour,
                        scale=_BODY_SCALE,
                        align="right" if side else "left",
                        backing=True,
                    )

    def _lathe_detail(self, left, right, profiles):
        c = self.canvas
        _text(c, left, 22, "JAW-END PROFILE", scale=_TITLE_SCALE)
        _text(c, left, 84, "Z RIGHT / RADIAL UP", _MUTED)
        _text(
            c,
            right,
            84,
            f"SETUP {self.spec['setup_id']} / DIMENSIONS IN mm",
            _MUTED,
            align="right",
        )
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
            _text(c, left, 129, "PROFILE NOT DECLARED", _MUTED)
            return 129 + _LEADING
        if not self.lathe_window:
            zmin, zmax = min(p[1] for p in points), max(p[1] for p in points)
        rmin, rmax = min(p[0] for p in points), max(p[0] for p in points)
        window_label = f"Z {_mm(zmin)} TO {_mm(zmax)} MM"
        _text(c, left, 129, window_label, _MUTED)
        scale = min(
            (right - left - 2 * _BADGE_PITCH) / max(zmax - zmin, 1e-9), 320 / max(rmax - rmin, 1e-9)
        )
        cy = 390
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
                cy = 200 + (rmax - rmin) * scale / 2
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
        arrows_before = self.arrows_drawn
        for profile in profiles:
            colour = tuple(profile.get("colour", _INK))
            dashed = profile["label"] == "arriving stock"
            for line in profile["lines"]:
                for a, b in zip(line, line[1:], strict=False):
                    c.line(project(a), project(b), colour, width=3, dashed=dashed)
            for index, line in enumerate(_wrap(c, profile["label"].upper(), right - left - 34)):
                rows.append((line, _INK, (colour, dashed) if index == 0 else None, 34))
        for z, small, large in self.shoulders:
            step = large - small
            # The main view names no step inside this window; every step either view
            # cannot show is named here.
            if not zmin <= z <= zmax or min(step * scale, step * self.canvas.scale) >= 3:
                continue
            point = project((large, z))
            c.line((point[0], point[1] - 12), (point[0], point[1] + 12), _INK, width=2)
            shoulder = _shoulder(z, small, large, self.spec.get("decimals"))
            for line in _wrap(c, shoulder, right - left):
                rows.append((line, _INK, None, 0))
        for path, _ in paths:
            for line in _wrap(c, f"OP {path['op']} SURFACE", right - left - 34):
                rows.append((line, _GREEN, (_GREEN, False), 34))
        if paths:
            rows.append((_ARROWS, _MUTED, None, 0))
        if closed:
            for line in _wrap(c, "TINT: PROFILE DIFFERENCE", right - left):
                rows.append((line, _AMBER, None, 0))
        if self.off_window_keys:
            for line in _wrap(c, "OFF-WINDOW P KEYS: FULL VIEW", right - left):
                rows.append((line, _MUTED, None, 0))
        row = 690
        if local is not None:
            # Complete local geometry and its large point keys remain above their own key.
            row = max(row, self.footer_top - 17 - _LEADING * len(rows))
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
            plot = (box[0] + 8, box[1] + _TEXT_HEIGHT + 18, box[2] - 8, box[3] - 6)
            # Keys go above and below a wide contour, or beside a tall one.
            cell = max((_badge_width(c, _plain(p["label"])) for p in waypoints), default=0)
            detail = max(
                min(
                    (plot[2] - plot[0] - 40) / (zhi - zlo),
                    max(20, plot[3] - plot[1] - 2 * _BADGE_PITCH) / (rhi - rlo),
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
            window = (project((0, zmin))[0], 190, project((0, zmax))[0], 575)
            if local is None:
                self._ordered_path([project(p) for p in points], _GREEN, clip=window)
            else:
                pixels = [project(p) for p in points]
                for a, b in zip(pixels, pixels[1:], strict=False):
                    segment = _clip_segment(a, b, window)
                    if segment:
                        c.line(*segment, _GREEN, width=3)
        if local is None:
            self._waypoint_badges(waypoints, project, (left, 180, right, 620))
        for line, colour, sample, indent in rows:
            if line == _ARROWS and self.arrows_drawn == arrows_before:
                continue
            if sample is not None:
                c.line(
                    (left, row + 10), (left + 25, row + 10), sample[0], width=3, dashed=sample[1]
                )
            _text(c, left + indent, row, line, colour)
            row += _LEADING
        return row

    def _path_inset(self, left, right, top, bottom):
        c = self.canvas
        paths = self.spec.get("paths", [])
        waypoints = [p for p in self.spec.get("waypoints", []) if "xy" in p]
        ops = list(dict.fromkeys(str(p.get("op", "")) for p in paths + waypoints))
        _text(c, left, top, "PROFILE SKETCH / XY", scale=_TITLE_SCALE)
        caption = _wrap(c, f"SETUP {self.spec['setup_id']} / DIMENSIONS IN mm", right - left)
        for index, line in enumerate(caption):
            _text(
                c,
                right,
                top + _LEADING + 8 + index * _LEADING,
                line,
                _MUTED,
                align="right",
            )
        before = self.arrows_drawn
        legend = _LEADING if _lifted_returns(paths) else 0
        self._operation_panels(
            left,
            right,
            top + (1 + len(caption)) * _LEADING + 28,
            bottom - 2 * _LEADING - legend,
            ops,
            paths,
            waypoints,
        )
        if self.inset_overflow > 0 or self.width_overflow > 0:
            return
        self._sketch_legend(left, bottom - _TEXT_HEIGHT, before)
        if self.nominal:
            _text(
                c,
                right,
                bottom - _TEXT_HEIGHT,
                "FINISHED OUTLINE, THIS SETUP",
                _BLUE,
                align="right",
            )

    def _sketch_bands(self, width, points, keys):
        """A ``width``-wide sketch's vertical budget: ``(exaggeration lines, key rows
        above, key rows below)``. Its keys print in badge rows above and below the plotted
        geometry (:func:`_band_cells`), never over a path; a shallow plot, under 24 px at
        the scale its width allows, declares the Y exaggeration it is drawn at."""
        xmin, ymin, xmax, ymax = _bounds(points)
        span_x, span_y = xmax - xmin, ymax - ymin
        factor = (width - 72) / max(span_x, 1e-9)
        lines = 0
        if 0 < span_y * factor < 24 and span_x * factor >= 60:
            lines = len(_wrap(self.canvas, "Y EXAG x4", width - 16))
        widths = [_badge_width(self.canvas, label) for label, _ in keys]
        up, down = _band_rows([(x, -y) for _, (x, y) in keys], widths, width - 12)
        return lines, up, down

    def _sketch_need(self, width, points, keys):
        """The least height of a sketch laid out by :meth:`_sketch_plot`."""
        widest = max((_badge_width(self.canvas, label) for label, _ in keys), default=0)
        self.width_overflow = max(self.width_overflow, widest - (width - 12))
        if self.width_overflow > 0:
            return _SKETCH_PLOT_MIN
        lines, up, down = self._sketch_bands(width, points, keys)
        return _LEADING * lines + _BADGE_PITCH * (up + down) + 12 + _SKETCH_PLOT_MIN

    def _sketch_plot(self, box, points, keys, indent=8):
        """Lay one sketch out in ``box`` ``(left, top, right, bottom)``, at least
        :meth:`_sketch_need` tall: its declared Y exaggeration (x2 to x4, whole steps) at
        the top, then its keys' upper badge rows, the plot and the lower rows. Returns
        ``(project, plot, badges)``: the XY projector, the plot's pixel box and the box its
        keys print in."""
        left, top, right, bottom = box
        width = right - left
        lines, up, down = self._sketch_bands(width, points, keys)
        bounds = _bounds(points)
        xmin, ymin, xmax, ymax = bounds
        span_x, span_y = xmax - xmin, ymax - ymin
        band_top = top + _LEADING * lines
        plot_top = band_top + _BADGE_PITCH * up + 6
        plot_bottom = bottom - _BADGE_PITCH * down - 6
        room = max(plot_bottom - plot_top, _SKETCH_PLOT_MIN)
        factor = min((width - 72) / max(span_x, 1e-9), room / max(span_y, 1e-9))
        factor_y = factor
        if lines:
            # Limit graphic distortion even when the key bands leave ample space.
            stretch = math.floor(min(room / (span_y * factor), 4))
            if stretch > 1:
                factor_y = factor * stretch
                exaggeration = f"Y EXAG x{_mm(stretch)}"
                wrapped = _wrap(self.canvas, exaggeration, width - 16)
                for index, line in enumerate(wrapped):
                    _text(self.canvas, left + indent, top + _LEADING * index, line, _MUTED)
        centre = ((left + right) / 2, (plot_top + plot_bottom) / 2)
        project = _xy_projector(bounds, centre, (factor, factor_y))
        return (
            project,
            (left + 7, plot_top, right - 7, plot_bottom),
            (left + 6, band_top, right - 6, bottom),
        )

    def _sketch_legend(self, left, top, arrows_before):
        """Name only the direction arrows and lifted returns actually drawn."""
        row = top
        if self.arrows_drawn > arrows_before:
            _text(self.canvas, left, row, _ARROWS, _MUTED)
            row -= _LEADING
        if self.returns_drawn:
            _text(self.canvas, left, row, _RETURNS, _MUTED)

    def _operation_panels(self, left, right, top, bottom, ops, paths, waypoints):
        """Separate authored operations, not every raster pass or curve record."""
        c = self.canvas
        columns = 2 if len(ops) > 1 else 1
        rows = math.ceil(len(ops) / columns)
        width = (right - left - 12 * (columns - 1)) / columns
        heights = self._panel_heights(ops, paths, waypoints, width, bottom - top, columns)
        if self.inset_overflow > 0 or self.width_overflow > 0:
            return
        tops = [top + sum(heights[:row]) + 12 * row for row in range(rows)]
        palette = (_BLUE, _GREEN, _AMBER, (113, 65, 137))
        for index, op in enumerate(ops):
            x = left + (index % columns) * (width + 12)
            y = tops[index // columns]
            height = heights[index // columns]
            colour = getattr(self, "operation_colours", {}).get(op, palette[index % len(palette)])
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
            project, plot, badges = self._sketch_plot(
                (x, y + _TEXT_HEIGHT + 22, x + width, y + height),
                points,
                _sketch_keys(op_paths, op_waypoints),
            )
            if self.nominal:
                self._nominal_overlay(project, plot, faint=True)
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
                badges,
                colour=colour,
                exclusion=_drawn_box(project, points),
            )

    def _panel_heights(self, ops, paths, waypoints, width, span, columns):
        """Each panel row's height: equal rows when every panel fits one, else each row's
        tallest need (its title band over :meth:`_sketch_need`) with the spare shared.
        Rows that need more than ``span`` ask the picture to grow (``inset_overflow``)."""
        rows = math.ceil(len(ops) / columns)
        total = span - 12 * (rows - 1)
        title_band = _TEXT_HEIGHT + 22
        needs = [title_band + _SKETCH_PLOT_MIN + 12] * rows
        for index, op in enumerate(ops):
            op_paths = [p for p in paths if str(p.get("op", "")) == op]
            op_waypoints = [p for p in waypoints if str(p.get("op", "")) == op]
            points = [p for path in op_paths for p in path["xy"]]
            points.extend(p["xy"] for p in op_waypoints)
            if not points:
                continue
            need = title_band + self._sketch_need(
                width, points, _sketch_keys(op_paths, op_waypoints)
            )
            needs[index // columns] = max(needs[index // columns], need)
        self.inset_overflow = max(self.inset_overflow, sum(needs) - total)
        equal = total / rows
        if all(need <= equal for need in needs):
            return [equal] * rows
        spare = max(0.0, total - sum(needs)) / rows
        return [need + spare for need in needs]

    def _raster_band(self, paths, project, colour, labels):
        """Draw ordinary rasters as a band, but keep-out rasters as independent lines.

        Up to :data:`_EVERY_PASS` passes each draw and label (PASS 1 ... PASS n, the
        table's numbers), with a direction arrow when the table gives the cutting
        direction; more draw the band with the first and last pass. A filled band must
        never claim that the clearance between split passes is swept. Return non-raster
        paths for the caller to draw separately.
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
            shown = raster if len(raster) <= _EVERY_PASS else [first, last]
        else:
            shown = raster
        for path in shown:
            self._ordered_path(
                [project(path["xy"][0]), project(path["xy"][-1])],
                colour,
                arrows=path.get("directed") is True,
            )
        # The cycle is one way: each pass's lift and rapid back to the next pass's start is
        # dashed, never drawn as a cut.
        for start, end in _lifted_returns(raster):
            _dashed(c, [[start, end]], project, colour)
            self.returns_drawn += 1
        labels.extend({"label": label, "xy": xy} for label, xy in _sketch_keys(raster, []))
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
                self.arrows_drawn += 1

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
        if getattr(self, "inset_overflow", 0) > 0 or getattr(self, "width_overflow", 0) > 0:
            return []
        placed = []
        for item, label, point, cell in zip(waypoints, labels, points, cells, strict=True):
            badge, outline = available[cell], item.get("outline")
            end = _nearest_on_outline(outline, badge) if outline else point
            placed.append((badge, label, end, item.get("colour", colour), bool(outline)))
        for badge, label, point, point_colour, hidden in placed:
            if point_colour == _CONTACT:
                c.line(point, badge, _WHITE, width=6)
                c.circle(*point, 6 if hidden else 5, fill=_WHITE)
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
        cell_height = _BADGE_HEIGHT
        columns = max(1, int((span_x + _BADGE_GAP) / (cell_width + _BADGE_GAP)))
        if perimeter:
            columns = min(columns, math.ceil(math.sqrt(len(labels))))
        required_rows = math.ceil(len(labels) / columns)
        rows = (
            max(required_rows, 2 if 2 * cell_height + _BADGE_GAP <= span_y else 1)
            if perimeter
            else max(required_rows, int((span_y + _BADGE_GAP) / _BADGE_PITCH))
        )
        if cell_width > span_x:
            if isinstance(self, _AnnotationDetail):
                self.width_overflow = max(self.width_overflow, cell_width - span_x)
                return [], []
            raise ValueError("point keys exceed their complete geometry panel at print size")
        overflow = rows * cell_height + (rows - 1) * _BADGE_GAP - span_y
        if overflow > 0:
            if isinstance(self, _AnnotationDetail):
                self.inset_overflow = max(self.inset_overflow, overflow)
                return [], []
            raise ValueError("point keys exceed their complete geometry panel at print size")
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
        self._triad(c, self.footer_top)
        _footer_text(
            c,
            self.footer_top,
            self.legend_rows[: self.footer_legend_rows],
            self.note_lines[: self.footer_note_rows],
            _footer_label(self.legend_ends, 0, self.footer_legend_rows, "KEY", "LEGEND ENTRY"),
            _footer_label(self.note_ends, 0, self.footer_note_rows, "SETUP NOTES", "NOTE"),
        )

    def _axes_minimum(self):
        """Actual unscaled axes primitives and full body cells, with the footer margin."""
        if self._measured_axes_height is None:
            measured = _ProfileCanvas(self.camera)
            self._triad(measured, 0)
            measured.assert_text_layout(min_scale=_BODY_SCALE)
            bottom = max(
                measured.drawn_bottom,
                max((box[4] for box in measured.text_boxes), default=0),
            )
            self._measured_axes_height = bottom + _FOOTER_BOTTOM_PAD
        return self._measured_axes_height

    def _triad(self, c, footer_top):
        x, y = 140, footer_top + 185
        _text(c, 32, footer_top + 23, "SETUP AXES")
        right, up, toward = self.camera
        normal_axis = None
        label_boxes = []
        for index, label in enumerate("XYZ"):
            dx, dy = right[index] * 80, -up[index] * 80
            colour = _AXIS_COLOURS[index]
            if math.hypot(dx, dy) < 1e-9:
                normal_axis = index
                c.circle(x, y, 8, fill=_WHITE, outline=colour)
                if toward[index] > 0:
                    c.circle(x, y, 3, fill=colour)
                else:
                    c.line((x - 5, y - 5), (x + 5, y + 5), colour, width=2)
                    c.line((x - 5, y + 5), (x + 5, y - 5), colour, width=2)
                end = (x, y)
                left, top = x - _TEXT_HEIGHT / 2, y + _LEADING
            else:
                end = (x + dx, y + dy)
                c.arrow((x, y), end, colour, width=3)
                left = end[0] + (12 if dx >= 0 else -_TEXT_HEIGHT)
                top = end[1] + (6 if dy >= 0 else -_TEXT_HEIGHT)
            width = c.text_width(label, scale=_BODY_SCALE)
            while any(
                left < right_edge + 4
                and old_left < left + width + 4
                and top < bottom + 4
                and old_top < top + _TEXT_HEIGHT + 4
                for old_left, old_top, right_edge, bottom in label_boxes
            ):
                left += _TEXT_HEIGHT + 8
            label_boxes.append((left, top, left + width, top + _TEXT_HEIGHT))
            _text(c, left, top, label, colour)
        if normal_axis is not None:
            direction = "TOWARD" if toward[normal_axis] > 0 else "AWAY"
            _text(c, 32, footer_top + 290, f"{'XYZ'[normal_axis]} {direction}", _MUTED)
        else:
            c.circle(37, footer_top + 307, 6, fill=_WHITE, outline=_MUTED)
            c.circle(37, footer_top + 307, 2, fill=_MUTED)
            # Keep the complete phrase inside the axes column, with a real gutter
            # before the adjacent legend's samples (not only its text boxes).
            for index, line in enumerate(_wrap(c, "VIEW NORMAL", 270)):
                _text(c, 49, footer_top + 290 + index * _LEADING, line, _MUTED)


def _footer_capacity(top, text_top=_FOOTER_TEXT_TOP):
    """Complete body-size rows that fit below this footer's headers and bottom margin."""
    return (_PANEL_MAX_HEIGHT - top - text_top - _TEXT_HEIGHT - _FOOTER_BOTTOM_PAD) // _LEADING + 1


def _footer_height(rows, text_top=_FOOTER_TEXT_TOP):
    return text_top + max(0, rows - 1) * _LEADING + _TEXT_HEIGHT + _FOOTER_BOTTOM_PAD


def _footer_title(spec):
    return f"SETUP {spec['setup_id']} / KEY + NOTES (CONTINUED)"


def _footer_header(spec):
    lines = _wrap(_MEASURE, _footer_title(spec), 1536, _TITLE_SCALE)
    return lines, 22 + len(lines) * 9 * _TITLE_SCALE + 10


def _footer_end(ends, first, capacity, whole_capacity):
    """Keep entries whole when possible; only an oversized single entry is continued."""
    if not ends or first >= ends[-1]:
        return first
    index = next(index for index, end in enumerate(ends) if end > first)
    start = ends[index - 1] if index else 0
    if first > start:
        # A continuation's header names this entry alone, not the next whole entry.
        return min(ends[index], first + capacity)
    last = max((end for end in ends[index:] if end <= first + capacity), default=first)
    if last > first:
        return last
    if ends[index] - first <= whole_capacity and capacity < whole_capacity:
        return first  # This whole entry belongs in the next, full-height text band.
    return min(ends[index], first + capacity)


def _footer_label(ends, first, last, normal, entry):
    if first == last:
        return normal
    index = next(index for index, end in enumerate(ends) if end > first)
    start = ends[index - 1] if index else 0
    if first > start or last < ends[index]:
        continued = " (CONTINUED)" if first > start else ""
        return f"{entry} {index + 1:02d}{continued}"
    return normal


def _footer_text_top(key_label, note_label):
    rows = max(
        len(_wrap(_MEASURE, key_label, _FOOTER_LEGEND_WIDTH)),
        len(_wrap(_MEASURE, note_label, 608)),
    )
    return 23 + rows * _LEADING + 20


def _footer_text(c, top, legend_rows, note_lines, key_label="KEY", note_label="SETUP NOTES"):
    """Paint measured key/note rows with the setup footer's unchanged sample associations."""
    text_top = _footer_text_top(key_label, note_label)
    if legend_rows:
        for index, line in enumerate(_wrap(c, key_label, _FOOTER_LEGEND_WIDTH)):
            _text(c, 380, top + 23 + index * _LEADING, line)
    for index, (label, kind) in enumerate(legend_rows):
        y = top + text_top + index * _LEADING
        if kind == "stock":
            c.rect(350, y + 8, 24, 24, (160, 174, 184), outline=_INK)
        elif kind == "fixture":
            c.rect(350, y + 8, 24, 24, _FIXTURE, outline=_INK)
        elif kind == "removal":
            c.rect(350, y + 8, 24, 24, _AMBER_LIGHT, outline=_AMBER)
            for dx in (0, 7, 14):
                c.line((352 + dx, y + 30), (358 + dx, y + 10), _AMBER, width=2)
        elif kind == "tool":
            c.arrow((350, y + _TEXT_HEIGHT / 2), (374, y + _TEXT_HEIGHT / 2), _GREEN, width=3)
        elif kind in ("context", "nominal"):
            c.line(
                (350, y + _TEXT_HEIGHT / 2),
                (374, y + _TEXT_HEIGHT / 2),
                _BLUE if kind == "nominal" else _MUTED,
                width=2,
                dashed=True,
            )
        _text(c, 380, y, label, _MUTED if kind == "text" else _INK)
    if note_lines:
        for index, line in enumerate(_wrap(c, note_label, 608)):
            _text(c, 960, top + 23 + index * _LEADING, line)
    for index, line in enumerate(note_lines):
        _text(c, 960, top + text_top + index * _LEADING, line, _MUTED)


class _FooterDetail:
    """Text-only continuation owned by its original setup, without a new geometric view."""

    role = "setup"

    def __init__(self, diagram, legend_first, note_first):
        self.spec = diagram.spec
        title_lines, self.footer_top = _footer_header(self.spec)
        key_label = _footer_label(
            diagram.legend_ends, legend_first, len(diagram.legend_rows), "KEY", "LEGEND ENTRY"
        )
        note_label = _footer_label(
            diagram.note_ends, note_first, len(diagram.note_lines), "SETUP NOTES", "NOTE"
        )
        self.text_top = _footer_text_top(key_label, note_label)
        capacity = _footer_capacity(self.footer_top, self.text_top)
        whole_capacity = _footer_capacity(self.footer_top)
        legend_last = _footer_end(diagram.legend_ends, legend_first, capacity, whole_capacity)
        note_last = _footer_end(diagram.note_ends, note_first, capacity, whole_capacity)
        self.legend_range = (legend_first, legend_last)
        self.note_range = (note_first, note_last)
        self.legend_rows = diagram.legend_rows[legend_first:legend_last]
        self.note_lines = diagram.note_lines[note_first:note_last]
        rows = max(len(self.legend_rows), len(self.note_lines))
        self.canvas = RenderCanvas(
            [],
            diagram.camera,
            (0, 0, 1, 1),
            height=self.footer_top + _footer_height(rows, self.text_top),
        )
        self.leaders = []
        self.hidden_leaders = []
        for index, line in enumerate(title_lines):
            _text(self.canvas, 32, 22 + index * 9 * _TITLE_SCALE, line, scale=_TITLE_SCALE)
        self.canvas.line((32, self.footer_top), (1568, self.footer_top), _INK, width=2)
        _footer_text(
            self.canvas,
            self.footer_top,
            self.legend_rows,
            self.note_lines,
            _footer_label(diagram.legend_ends, legend_first, legend_last, "KEY", "LEGEND ENTRY"),
            _footer_label(diagram.note_ends, note_first, note_last, "SETUP NOTES", "NOTE"),
        )
        self.canvas.assert_text_layout(min_scale=_BODY_SCALE)

    def _title(self):
        return _footer_title(self.spec)


def _footer_details(diagram):
    details = []
    legend_first, note_first = diagram.footer_legend_rows, diagram.footer_note_rows
    while legend_first < len(diagram.legend_rows) or note_first < len(diagram.note_lines):
        detail = _FooterDetail(diagram, legend_first, note_first)
        details.append(detail)
        legend_first, note_first = detail.legend_range[1], detail.note_range[1]
    return details


def _append_panel(diagram, detail, role, label):
    """Append a complete independently laid-out canvas; metadata uses its actual extent."""
    canvas, source = diagram.canvas, detail.canvas
    if any(
        getattr(detail, name, 0) > 0
        for name in ("lane_overflow", "inset_overflow", "width_overflow")
    ):
        raise ValueError("an overflowing diagram band cannot be appended")
    if source.width != canvas.width or not 0 < source.height <= _PANEL_MAX_HEIGHT:
        raise ValueError("complete diagram band exceeds its printable width or height")
    top = canvas.height
    canvas.grow(source.height)
    canvas.paste(source, 0, top)
    canvas.text_boxes.extend(
        (text, left, y + top, right, bottom + top)
        for text, left, y, right, bottom in source.text_boxes
    )
    for target, leaders in (
        (diagram.leaders, detail.leaders),
        (diagram.hidden_leaders, detail.hidden_leaders),
    ):
        target.extend((text, [(x, y + top) for x, y in path]) for text, path in leaders)
    diagram.print_panels.append(
        {"top_px": top, "height_px": source.height, "role": role, "label": label}
    )


class _ProfileCanvas(RenderCanvas):
    """Measure all painted profile primitives, including leaders and arrowheads."""

    def __init__(self, camera):
        self.drawn_bottom = 0
        super().__init__([], camera, (0, 0, 1, 1), height=_PANEL_MAX_HEIGHT)

    def _span(self, row, first, last, pixel):
        if row >= 0 and max(0, first) <= min(self.width - 1, last):
            self.drawn_bottom = max(self.drawn_bottom, row + 1)
        super()._span(row, first, last, pixel)


class _AnnotationDetail(_Diagram):
    """An existing independent sketch, promoted out of the small third column."""

    def __init__(self, spec, role, main_scale, height):
        super().__init__([], spec)
        self.role = role
        self.layout_height = height
        self.lane_overflow = 0
        # Keep the established profile layout reference independent of bitmap height:
        # shortening its unused tail must never refit/recentre the window or local detail.
        self.footer_top = height - 16
        self.canvas = (
            _ProfileCanvas(self.camera)
            if role == "profile_detail"
            else RenderCanvas([], self.camera, (0, 0, 1, 1), height=height)
        )
        # Shoulder visibility is judged at the main picture's geometry scale.
        self.canvas.scale = main_scale

    def _title(self):
        return "JAW-END PROFILE" if self.role == "profile_detail" else "PROFILE SKETCH / XY"

    def render(self):
        if self.role == "profile_detail":
            self._lathe_detail(32, 1568, self.spec.get("lathe_profiles", []))
            if self.width_overflow > 0:
                return
            # Span coverage includes geometry, tint, samples, circles, backing rectangles,
            # leaders and arrow wings; text boxes also reserve complete character cells.
            content_bottom = max(
                self.canvas.drawn_bottom,
                max((box[4] for box in self.canvas.text_boxes), default=0),
            )
            needed = content_bottom + _PROFILE_BOTTOM_PAD
            self.inset_overflow = max(self.inset_overflow, needed - self.layout_height)
            if self.inset_overflow > 0:
                return
            scale = self.canvas.scale
            self.canvas = RenderCanvas([], self.camera, (0, 0, 1, 1), height=needed)
            self.canvas.scale = scale
            self.leaders.clear()
            self.hidden_leaders.clear()
            # Paint a new, correctly sized canvas with the identical layout/projection;
            # never slice a previous PNG or refit geometry to its reduced height.
            self._lathe_detail(32, 1568, self.spec.get("lathe_profiles", []))
        else:
            self._path_inset(32, 1568, 22, self.canvas.height - 24)
        if self.inset_overflow > 0 or self.width_overflow > 0 or self.lane_overflow > 0:
            return
        self.canvas.assert_text_layout(min_scale=_BODY_SCALE)


def _annotation_detail(spec, role, main_scale, height, colours=None):
    """Settle the actual detail's measured layout; None means its whole band cannot fit."""
    while height <= _PANEL_MAX_HEIGHT:
        detail = _AnnotationDetail(spec, role, main_scale, height)
        if colours is not None:
            detail.operation_colours = colours
        detail.render()
        if detail.width_overflow > 0:
            return None
        overflow = max(detail.inset_overflow, detail.lane_overflow)
        if overflow <= 0:
            return detail
        height += math.ceil(overflow)
    return None


def _annotation_details(spec, main_scale):
    details = []
    if spec["view"] == "lathe" and (
        spec.get("lathe_profiles")
        or spec.get("axial_paths")
        or any("xz" in p for p in spec.get("waypoints", []))
    ):
        detail = _annotation_detail(spec, "profile_detail", main_scale, 1460)
        if detail is None:
            raise ValueError("complete jaw-end profile and key exceed the printable band")
        details.append(detail)
    paths = spec.get("paths", [])
    waypoints = [p for p in spec.get("waypoints", []) if "xy" in p]
    ops = list(dict.fromkeys(str(p.get("op", "")) for p in paths + waypoints))
    palette = (_BLUE, _GREEN, _AMBER, (113, 65, 137))
    colours = {op: palette[index % len(palette)] for index, op in enumerate(ops)}
    # Every authored operation retains its entire geometry, waypoints and local key.
    # Two side-by-side operation panels form a complete full-width printable band.
    batches = [ops[index : index + 2] for index in range(0, len(ops), 2)]
    while batches:
        selected = batches.pop(0)
        local = {
            **spec,
            "paths": [p for p in paths if str(p.get("op", "")) in selected],
            "waypoints": [p for p in waypoints if str(p.get("op", "")) in selected],
        }
        detail = _annotation_detail(local, "path_detail", main_scale, 980, colours)
        if detail is None:
            if len(selected) == 2:
                batches[:0] = [[selected[0]], [selected[1]]]
                continue
            raise ValueError(
                "one complete authored operation exceeds its printable band at body size"
            )
        details.append(detail)
    return details


def render_diagram(meshes, spec):
    """Return ``(png, debts, print_panels)``: the complete deterministic 1600 px wide PNG,
    its truthful NOT SHOWN debts, and ordered full-width independently printable bands.
    Bands cover the final PNG exactly once; no picture, leader or local key is cropped
    away to meet the print height. Debts also appear in the picture's own notes.

    ``meshes`` contain numeric setup-frame XYZ triples, triangle index triples,
    RGB, optionally a removal-hatch flag and the tag of the solid each draws. ``spec``
    is the kernel's plain JSON diagram record; optional ``lathe_profiles`` contain
    exact [radius, Z] lines, and an optional ``guide_view`` the guide axis
    (``axis_mm``: [point, direction]), the meshes drawn along it and, when they are cut
    between the rims so the near stop does not hide the work, a point on that plane
    (``section_mm``).
    """
    debts, details, here = [], [], False
    # A debt found while laying out is printed in the notes, which can move the layout:
    # redraw until the printed notes are exactly the debts of the picture they sit in. A
    # clearance no detail band keys (none drawn, or none holds it) is keyed on the setup
    # picture itself: a picture never drops its CUT dimension.
    for attempt in range(5):
        notes = list(spec.get("notes", [])) + debts
        diagram, png = _main_diagram(meshes, {**spec, "notes": notes, "key_closest_cut": here})
        if attempt == 0:
            details = _holding_details(meshes, spec, diagram)
            guide = _guide_view(spec, diagram)
            if guide is not None:
                details.append(guide)
            here = bool(spec.get("closest_cut")) and not any(d.keyed_cut for d in details)
            if here:
                continue
        found = [debt for detail in details for debt in detail.render_debts]
        found += diagram.render_debts
        if found != debts:
            debts = found
            continue
        diagram, png = _compose_diagram(diagram, details)
        return png, debts, diagram.print_panels
    raise ValueError(f"setup picture debts do not settle: {debts}")


def _compose_diagram(diagram, holding_details):
    """Return ``(diagram, png)`` for a settled main stage with all final print bands.

    Setup-footer continuations precede annotation and measured holding bands.
    The object retains the independent details and their original specs; its text boxes
    and leaders include their shifted copies in the one canonical final canvas.
    """
    if diagram.lane_overflow > 0:
        raise ValueError("a setup stage with overflowing label lanes cannot be composed")
    if hasattr(diagram, "holding_details"):
        raise ValueError("the setup stage has already been composed")
    diagram.footer_details = _footer_details(diagram)
    diagram.annotation_details = _annotation_details(diagram.spec, diagram.canvas.scale)
    diagram.holding_details = [d for d in holding_details if not isinstance(d, _GuideView)]
    diagram.guide_details = [d for d in holding_details if isinstance(d, _GuideView)]
    for detail in diagram.footer_details:
        _append_panel(diagram, detail, detail.role, detail._title())
    for detail in diagram.annotation_details:
        _append_panel(diagram, detail, detail.role, detail._title())
    for detail in diagram.holding_details:
        _append_panel(diagram, detail, "holding_detail", detail._title())
    for detail in diagram.guide_details:
        _append_panel(diagram, detail, "guide_axis", detail._title())
    diagram.render_debts = [
        debt
        for detail in diagram.holding_details + diagram.guide_details
        for debt in detail.render_debts
    ] + diagram.render_debts
    diagram.canvas.assert_text_layout(min_scale=_BODY_SCALE)
    return diagram, diagram.canvas.png()


def _setup_height_refusal(diagram, forecast, maximum, overflow, height):
    """Private layout diagnostics, never physical facts or a substitute render result."""
    axes_minimum = diagram._axes_minimum()
    return ValueError(
        "complete setup panel exceeds the printable Letter height at body size"
        f" (owner={type(diagram).__name__}, role=setup,"
        f" setup_id={diagram.spec.get('setup_id')!r}, view={diagram.view!r},"
        f" forecast_extra_px={forecast}, attempted_extra_px={diagram.extra},"
        f" max_extra_px={maximum}, footer_top_px={diagram.footer_top},"
        f" axes_min_px={axes_minimum},"
        f" first_band_min_px={diagram.footer_top + axes_minimum},"
        f" remaining_overflow_px={overflow!r}, height_px={height}, cap_px={_PANEL_MAX_HEIGHT})"
    )


def _main_diagram(meshes, spec):
    """Return ``(diagram, png)`` with only the main label lanes measured to fit.
    Text-footer continuations and independent sketches never grow the setup's geometry."""
    extra = forecast = 0
    maximum = None
    attempting_maximum = False
    while True:
        diagram = _Diagram(meshes, spec, extra)
        png = diagram.render()
        if diagram.lane_overflow <= 0:
            return diagram, png
        if attempting_maximum:
            raise _setup_height_refusal(
                diagram, forecast, maximum, diagram.lane_overflow, diagram.canvas.height
            )
        forecast = extra + math.ceil(diagram.lane_overflow)
        base = diagram.footer_top - extra
        if maximum is None and base + forecast + diagram.axes_height > _PANEL_MAX_HEIGHT:
            maximum = _PANEL_MAX_HEIGHT - base - diagram._axes_minimum()
            if maximum < 0:
                raise _setup_height_refusal(
                    diagram, forecast, maximum, diagram.lane_overflow, diagram.canvas.height
                )
        if maximum is not None and forecast >= maximum:
            if extra >= maximum:
                raise _setup_height_refusal(
                    diagram, forecast, maximum, diagram.lane_overflow, diagram.canvas.height
                )
            # The forecast can overestimate a repack after its obstacles move.
            # Try the complete measured budget once; never clip a painted candidate.
            extra = maximum
            attempting_maximum = True
        else:
            extra = forecast


def _holding_details(meshes, spec, diagram):
    """The rendered holding detail bands for a setup picture, else []. They are drawn only
    when something touches the stock and ``diagram`` draws the stock's narrower side under
    ``_DETAIL_MIN_PX`` (small beside its holding). One band is drawn when it draws that
    side at least ``_DETAIL_GAIN`` times larger. A plan view, which cannot show contact
    heights, always gets the detail's raised view, split along the work's length into the
    fewest bands (at most ``_DETAIL_TILES``) that reach the gain, else the most. Any other
    view whose whole work cannot reach the gain is windowed on the holding that touches
    it (:func:`_detail_frame`), when that reaches the gain."""
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
            tiles = [_detail_frame(spec, window=True)]
            scale = _fit_scale(_corners(tiles[0]), camera, _detail_viewport(tiles[0], camera))
            if scale * across < _DETAIL_GAIN * drawn:
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
            detail.gain = detail.canvas.scale / diagram.canvas.scale
            detail.render()
            if detail.lane_overflow <= 0:
                break
            extra += math.ceil(detail.lane_overflow)
        details.append(detail)
    return details


def _guide_view(spec, diagram):
    """The look along a guided file's guide axis printed below the holding detail, else
    None: drawn when the kernel names the axis (``guide_view``) and the setup picture does
    not already look along it. An edge-on section of a button sandwich shows neither the
    rims the file rides on nor the way it comes in to them."""
    guide = spec.get("guide_view")
    if not guide or not spec.get("guide_stops"):
        return None
    camera = _axis_camera(guide["axis_mm"][1])
    if abs(_dot3(diagram.camera[2], camera[2])) >= _ALONG_COS:
        return None
    extra = 0
    while True:
        view = _GuideView(spec, camera, diagram.canvas.scale, extra)
        view.render()
        if view.lane_overflow <= 0:
            return view
        extra += math.ceil(view.lane_overflow)


def _axis_camera(direction):
    """A camera looking down ``direction`` from its + end: right is the setup axis most
    square to it (X first), up completes the right-handed frame."""
    length = math.sqrt(_dot3(direction, direction))
    toward = tuple(v / length for v in direction)
    index = min(range(3), key=lambda i: abs(toward[i]))
    right = [(1.0 if i == index else 0.0) - toward[index] * toward[i] for i in range(3)]
    norm = math.sqrt(_dot3(right, right))
    right = tuple(v / norm for v in right)
    up = (
        toward[1] * right[2] - toward[2] * right[1],
        toward[2] * right[0] - toward[0] * right[2],
        toward[0] * right[1] - toward[1] * right[0],
    )
    return (right, up, toward)


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


def _detail_viewport(frame, camera, extra=0, top=100):
    """The detail band's viewport: full width, and only as tall as the framed geometry
    needs at that width, between the room its keys need and the full band, plus
    ``extra`` rows the keys turned out to need; ``top`` below the band's header."""
    left, right = 440, 1160
    top = max(top, 200 + _BADGE_PITCH)
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


def _detail_frame(spec, window=False):
    """The box a holding detail frames: the stock, its contact outlines and the closest
    cut's ends, padded; None when nothing touches the stock. A ``window`` frames instead
    the holding that touches the stock: its contact outlines and the whole of each
    component making one (both buttons and the stud they hang on, a jaw and its grip)."""
    stock = spec.get("stock_box")
    contacts = spec.get("contacts") or []
    if stock is None or not contacts:
        return None
    points = [p for contact in contacts for line in contact["lines_mm"] for p in line]
    if window:
        tags = {contact["tag"] for contact in contacts}
        for component in spec.get("components", []):
            if tags.intersection(component.get("meshes", ())) and component.get("box_mm"):
                points += _corners(component["box_mm"])
    else:
        points += _corners(stock)
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


def _nearest_on_segment(point, a, b):
    """The point of segment ``a``-``b`` (setup mm) nearest ``point``."""
    d = [b[i] - a[i] for i in range(3)]
    span = _dot3(d, d)
    t = 0.0 if span == 0 else _dot3([point[i] - a[i] for i in range(3)], d) / span
    t = max(0.0, min(1.0, t))
    return [a[i] + t * d[i] for i in range(3)]


def _stop_key(names):
    """The key of the rims a guided file stops on, by their solids' printed names."""
    nouns = {name.rsplit(" ", 1)[-1] for name in names}
    if len(names) == 2 and len(nouns) == 1:
        return f"FILE STOPS ON BOTH {nouns.pop()} RIMS"
    return f"FILE STOPS ON {' AND '.join(names)} RIM{'S' if len(names) > 1 else ''}"


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
    splits_sides = False

    def __init__(self, meshes, spec, frame, camera, gain, tile=(1, 1), extra=0, top=100):
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
        title_rows = len(_wrap(_MEASURE, self._title(), 1536, _TITLE_SCALE))
        top = max(top, 22 + title_rows * 9 * _TITLE_SCALE + 10 + _LEADING + _BADGE_PITCH)
        self.viewport = _detail_viewport(frame, camera, extra, top)
        self.footer_top = math.ceil(self.viewport[3]) + _BADGE_PITCH + 28
        if self.footer_top > _PANEL_MAX_HEIGHT:
            raise ValueError("complete holding geometry and contact keys exceed the printable band")
        self.lanes = (self.viewport[1] - _BADGE_PITCH, self.footer_top - 16)
        self.lane_specs = ((32, 360, 410), (1208, 360, 1190))
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
        title += f" X{decimal_text(self.gain, 1)}"
        zero = self.spec.get("zero_mm")
        axis = max(range(3), key=lambda i: abs(self.camera[0][i]))
        # A band or a window on the holding shows only a stretch of the work: say which.
        whole = (
            self.frame[axis] <= self.stock[axis] and self.stock[axis + 3] <= self.frame[axis + 3]
        )
        if (count == 1 and whole) or zero is None:
            return title
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
        title_lines = _wrap(c, self._title(), 1536, scale=_TITLE_SCALE)
        for index, line in enumerate(title_lines):
            _text(c, 32, 22 + index * 9 * _TITLE_SCALE, line, scale=_TITLE_SCALE)
        note_y = 22 + len(title_lines) * 9 * _TITLE_SCALE + 10
        _text(c, 34, note_y, "CONTACT FACES: SOLID WHERE SEEN, DASHED WHERE HIDDEN", _CONTACT)
        groups = self._contact_groups()
        self._contact_outline(
            [line for _, _, members in groups for _, _, lines in members for line in lines]
        )
        keyed = []
        for label, plane, members in groups:
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
        self._guide_stops()
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
                (self.viewport[0], top - _BADGE_PITCH, self.viewport[2], bottom + _BADGE_PITCH),
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
        strokes, points = [], []
        for line in lines:
            if len(line) == 1:
                points.append((c.project(line[0]), self._seen(line[0])))
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
                    # The halo uses exactly the on-dash fragments, never a solid trace.
                    strokes.extend(
                        (segment, 4, 2)
                        for segment in _dash_segments([run], c.project, self.viewport)
                    )
                    continue
                for a, b in zip(run, run[1:], strict=False):
                    segment = _clip_segment(c.project(a), c.project(b), self.viewport)
                    if segment:
                        strokes.append((segment, 7, 3))
        # All contacts share one underlay pass: a later chord or neighbouring outline
        # must not erase contact ink already painted at their joint.
        for segment, halo_width, _ in strokes:
            c.line(*segment, _WHITE, width=halo_width)
        for point, _ in points:
            c.circle(*point, 8, fill=_WHITE)
        for segment, _, width in strokes:
            c.line(*segment, _CONTACT, width=width)
        for point, seen in points:
            c.circle(*point, 6, fill=_CONTACT if seen else None, outline=_CONTACT)

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
        return super()._in_tile(point)

    def _plane_text(self, plane):
        zero = self.spec.get("zero_mm")
        if zero is None or plane is None:
            return ""
        axis, value = plane
        return f" AT {'XYZ'[axis]} {self._dro(self._on_grid(value - zero[axis]))}"

    def _on_grid(self, value):
        """A setup coordinate at the setup's nearest DRO step (``dro_step_mm``), rounded
        as the fixture tables round their positions (:func:`dro_steps`); unchanged when the
        spec names no step."""
        step = self.spec.get("dro_step_mm")
        if not isinstance(step, (int, float)) or isinstance(step, bool) or step <= 0:
            return value
        return dro_steps(value, step) * step

    def _guide_stops(self):
        """Where a guided file stops: each guide solid (a filing button) its cut reaches is
        the rim the file rides on, keyed once with a leader to each rim (each rim by its
        own name when the leaders must be keyed apart), never dimensioned as a zero
        clearance (the kernel leaves it out of ``closest_cut``)."""
        stops = [
            stop for stop in self.spec.get("guide_stops") or [] if self._in_tile(stop["at_mm"])
        ]
        if not stops:
            return
        names = [_solid_name(stop["tag"]) for stop in stops]
        points = [self.canvas.project(stop["at_mm"]) for stop in stops]
        each = tuple(_stop_key([name]) for name in names)
        self.callouts.append(_Callout(_stop_key(names), points, _GREEN, each=each))


class _GuideView(_HoldingDetail):
    """A look down a guided file's guide axis (a filing-button kit's stud), printed below
    the holding detail: the rims the file rides on outlined, the stock it files off
    hatched inside the finished outline, the file drawn flat at its stop and an arrow the
    way it comes in, from beyond the rims toward the axis. Framed on the guide solids the
    file stops on, that stock and the approach."""

    def __init__(self, spec, camera, main_scale, extra=0):
        guide = spec["guide_view"]
        stops = spec["guide_stops"]
        self.names = [_solid_name(stop["tag"]) for stop in stops]
        self.rims = [[run for run in stop.get("rim_mm") or ()] for stop in stops]
        runs = [run for runs in self.rims for run in runs]
        rim = [p for run in runs for p in run] or [stop["at_mm"] for stop in stops]
        middle = [sum(p[i] for p in rim) / len(rim) for i in range(3)]
        # Where the file is drawn at its stop: the rim's point nearest the rim's middle.
        nearest = [
            _nearest_on_segment(middle, a, b)
            for run in runs
            for a, b in zip(run, run[1:], strict=False)
        ]
        self.stop = min(nearest or rim, key=lambda p: math.dist(p, middle))
        # The way in: square to the axis, from the axis out through the stop.
        centre, toward = guide["axis_mm"][0], camera[2]
        out = [self.stop[i] - centre[i] for i in range(3)]
        depth = _dot3(out, toward)
        out = [out[i] - depth * toward[i] for i in range(3)]
        self.radius = math.sqrt(_dot3(out, out))
        self.out = tuple(v / self.radius for v in out) if self.radius > 1e-6 else None
        tags = {stop["tag"] for stop in stops} | {"removal"}
        points = [p for mesh in guide["meshes"] if mesh[4] in tags for p in mesh[0]] + rim
        self.tail = None
        if self.out is not None:
            # The approach starts beyond the stock the file takes off, coming in square.
            removal = [p for mesh in guide["meshes"] if mesh[4] == "removal" for p in mesh[0]]
            reach = max(
                [_dot3([p[i] - self.stop[i] for i in range(3)], self.out) for p in removal] + [0.0]
            )
            run = reach + 0.35 * self.radius
            self.tail = [self.stop[i] + run * self.out[i] for i in range(3)]
            points.append(self.tail)
        low = [min(p[i] for p in points) for i in range(3)]
        high = [max(p[i] for p in points) for i in range(3)]
        pads = [0.05 * (high[i] - low[i]) + 1.0 for i in range(3)]
        frame = [low[i] - pads[i] for i in range(3)] + [high[i] + pads[i] for i in range(3)]
        meshes = [tuple(mesh) for mesh in guide["meshes"]]
        # Header space belongs to this view, not to the setup's label lanes.
        gain = (
            _fit_scale(_corners(frame), camera, _detail_viewport(frame, camera, extra)) / main_scale
        )
        self.camera, self.gain = camera, gain
        self.title_lines = _wrap(_MEASURE, self._title(), 1536, _TITLE_SCALE)
        facing = self._facing()
        if guide.get("section_mm"):
            facing = "  /  ".join(filter(None, ("SECTION BETWEEN THE RIMS", facing)))
        self.note_lines = _wrap(_MEASURE, facing, 1534) if facing else []
        self.note_y = 22 + len(self.title_lines) * 9 * _TITLE_SCALE + 10
        top = self.note_y + len(self.note_lines) * _LEADING + _BADGE_PITCH + 10
        super().__init__(meshes, spec, frame, camera, gain, (1, 1), extra, top)
        self.gain = self.canvas.scale / main_scale
        self.nominal = [line for line in spec.get("nominal_outline_mm", []) if len(line) >= 2]

    def _title(self):
        nouns = {name.rsplit(" ", 1)[-1] for name in self.names}
        noun = nouns.pop() if len(nouns) == 1 else "GUIDE"
        return f"VIEW ALONG THE {noun} AXIS X{decimal_text(self.gain, 1)}"

    def _facing(self):
        """Where this view looks from and which setup axes it draws right and up, as the
        section note prints them; empty when the axis is not a setup axis."""
        names = []
        for vector in self.camera:
            index = max(range(3), key=lambda i: abs(vector[i]))
            if abs(vector[index]) < 0.999:
                return ""
            names.append(("-" if vector[index] < 0 else "+") + "XYZ"[index])
        right, up, toward = names
        return f"VIEW FROM SETUP {toward}  /  {right.lstrip('+')} RIGHT, {up.lstrip('+')} UP"

    def render(self):
        c = self.canvas
        c.line((32, 8), (1568, 8), _INK, width=2)
        for index, line in enumerate(self.title_lines):
            _text(c, 32, 22 + index * 9 * _TITLE_SCALE, line, scale=_TITLE_SCALE)
        for index, line in enumerate(self.note_lines):
            _text(c, 34, self.note_y + index * _LEADING, line, _MUTED)
        self._nominal_overlay(c.project, clip=self.viewport)
        if self.nominal:
            self.callouts.append(
                _Callout(
                    "FINISHED OUTLINE",
                    [c.project(self.nominal[0][0])],
                    _BLUE,
                    along=tuple(c.project(p) for line in self.nominal for p in line),
                )
            )
        self._file()
        self._rims()
        self._holding()
        removal = [p for mesh in self.meshes if mesh[4] == "removal" for p in mesh[0]]
        if removal:
            middle = [sum(p[i] for p in removal) / len(removal) for i in range(3)]
            point = self._anchor(("removal",), c.project(middle))
            if point is None:
                self._hidden("STOCK TO FILE OFF")
            else:
                self.callouts.append(
                    _Callout("STOCK TO FILE OFF", [point], _INK, targets=("removal",))
                )
        self._labels()
        if self.lane_overflow > 0:
            return
        c.assert_text_layout(min_scale=_BODY_SCALE)

    def _rims(self):
        """Each stop's rim outlined; one key when the rims lie one over the other along
        the axis (a button pair), else a key per rim."""
        c = self.canvas
        ends, along = [], []
        for runs, stop in zip(self.rims, self.spec["guide_stops"], strict=True):
            pixels = []
            for run in runs:
                drawn = [c.project(p) for p in run]
                pixels += drawn
                if len(drawn) == 1:
                    c.circle(*drawn[0], 5, fill=_GREEN)
                for a, b in zip(drawn, drawn[1:], strict=False):
                    segment = _clip_segment(a, b, self.viewport)
                    if segment:
                        c.line(*segment, _GREEN, width=5)
            pixels = pixels or [c.project(stop["at_mm"])]
            here = c.project(self.stop)
            ends.append(min(pixels, key=lambda p: math.dist(p, here)))
            along += pixels
        if all(math.dist(end, ends[0]) <= 3 for end in ends):
            self.callouts.append(
                _Callout(_stop_key(self.names), ends[:1], _GREEN, along=tuple(along))
            )
            return
        each = tuple(_stop_key([name]) for name in self.names)
        self.callouts.append(_Callout(_stop_key(self.names), ends, _GREEN, each=each))

    def _file(self):
        """The file flat on the rims at its stop, and an arrow from beyond them in."""
        if self.out is None:
            return
        c = self.canvas
        stop = c.project(self.stop)
        beyond = c.project([self.stop[i] + self.out[i] for i in range(3)])
        length = math.dist(stop, beyond)
        o = ((beyond[0] - stop[0]) / length, (beyond[1] - stop[1]) / length)
        t = (-o[1], o[0])
        half = 0.7 * self.radius * c.scale
        face = (stop[0] + 4 * o[0], stop[1] + 4 * o[1])
        back = (face[0] + 10 * o[0], face[1] + 10 * o[1])
        c.polygon(
            [
                (face[0] - half * t[0], face[1] - half * t[1]),
                (face[0] + half * t[0], face[1] + half * t[1]),
                (back[0] + half * t[0], back[1] + half * t[1]),
                (back[0] - half * t[0], back[1] - half * t[1]),
            ],
            _RULE,
            outline=_INK,
        )
        tail = c.project(self.tail)
        c.arrow(tail, (back[0] + 3 * o[0], back[1] + 3 * o[1]), _GREEN, width=3)
        self.callouts.append(_Callout("FILE APPROACH", [tail], _GREEN))
        end = (face[0] + half * 0.8 * t[0] + 5 * o[0], face[1] + half * 0.8 * t[1] + 5 * o[1])
        self.callouts.append(_Callout("FILE AT ITS STOP", [end], _INK))

    def _holding(self):
        """The guide kit, keyed as the setup picture names it."""
        c = self.canvas
        tags = {stop["tag"] for stop in self.spec["guide_stops"]}
        for component in self.components:
            meshes = tuple(component.get("meshes", ()))
            if not tags.intersection(meshes):
                continue
            near = c.project(self.spec["guide_view"]["axis_mm"][0])
            point = self._anchor(meshes, near)
            label = self._component_label(component)
            if point is None:
                self._hidden(label)
                continue
            self.callouts.append(_Callout(label, [point], _FIXTURE, targets=meshes))


def render_inspection(views):
    """``(png, debts, print_panels)``: an inspection's labelled set-up sketches as one
    canonical PNG 1600 px wide, with a complete authored-view band per print panel and
    the NOT SHOWN lines for what a band could not key truthfully.

    Each view has a ``title`` (wrapped, the band moved down under it); a ``camera``
    [right, up, toward] in the part model's axes, ``up`` pointing up off the surface
    plate; ``meshes`` as :func:`render_diagram` takes them, tagged ``part`` or with the
    tag of the aid (gauge, block, holding) each draws; ``aids``, ``[tag, name]`` pairs,
    each keyed by its name on its own tag's pixels; and ``marks`` (``label``, ``at_mm``,
    ``reads``). The plate is drawn under the lowest solid. Every mark is keyed with a
    leader; a reading mark carries an arrow up off the plate with a + at its head, the
    way a higher contact reads +. Nothing is drawn that the views do not state."""
    bands = []
    for view in views:
        extra = 0
        while True:
            band = _InspectionSketch(view, extra)
            band.render()
            if band.lane_overflow <= 0:
                break
            extra += math.ceil(band.lane_overflow)
        bands.append(band)
    if not bands:
        raise ValueError("an inspection requires at least one complete authored view")
    diagram = bands[0]
    diagram.print_panels = [
        {
            "top_px": 0,
            "height_px": diagram.canvas.height,
            "role": "inspection",
            "label": diagram._title(),
            "view_ordinal": 1,
        }
    ]
    for ordinal, band in enumerate(bands[1:], 2):
        _append_panel(diagram, band, "inspection", band._title())
        diagram.print_panels[-1]["view_ordinal"] = ordinal
    diagram.canvas.assert_text_layout(min_scale=_BODY_SCALE)
    return (
        diagram.canvas.png(),
        [debt for band in bands for debt in band.render_debts],
        diagram.print_panels,
    )


class _InspectionSketch(_HoldingDetail):
    """One labelled look at the part set up on the surface plate for an inspection
    (:func:`render_inspection`): framed on everything the view draws and marks."""

    # A reading mark's arrow: its length up off the mark, and the + beside its head.
    ARROW_PX = 48
    PLUS_PX = 7

    # The title and reading hint reserve their actual wrapped height at the type floors.
    TITLE_PITCH = 9 * _TITLE_SCALE

    def __init__(self, view, extra=0):
        self.sketch = view
        self.title_lines = _wrap(_MEASURE, view["title"], 1536, _TITLE_SCALE)
        note = "+ ARROW: THE WAY A READING RISES (A HIGHER CONTACT READS +)"
        reads = any(mark.get("reads") for mark in view["marks"])
        self.note_lines = _wrap(_MEASURE, note, 1534) if reads else []
        self.note_y = 22 + len(self.title_lines) * self.TITLE_PITCH + 10
        top = self.note_y + len(self.note_lines) * _LEADING + _BADGE_PITCH + 10
        camera = tuple(tuple(axis) for axis in view["camera"])
        points = [p for mesh in view["meshes"] for p in mesh[0]]
        points += [mark["at_mm"] for mark in view["marks"]]
        low = [min(p[i] for p in points) for i in range(3)]
        high = [max(p[i] for p in points) for i in range(3)]
        pads = [0.08 * (high[i] - low[i]) + 1.0 for i in range(3)]
        frame = [low[i] - pads[i] for i in range(3)] + [high[i] + pads[i] for i in range(3)]
        spec = {"view": "elevation", "components": [], "stock_box": frame, "contacts": []}
        super().__init__(view["meshes"], spec, frame, camera, 1.0, (1, 1), extra, top)

    def _title(self):
        return self.sketch["title"]

    def render(self):
        c = self.canvas
        c.line((32, 8), (1568, 8), _INK, width=2)
        for index, line in enumerate(self.title_lines):
            _text(c, 32, 22 + index * self.TITLE_PITCH, line, scale=_TITLE_SCALE)
        for index, line in enumerate(self.note_lines):
            _text(c, 34, self.note_y + index * _LEADING, line, _MUTED)
        self._plate()
        for tag, name in self.sketch["aids"]:
            pixels = [c.project(p) for mesh in self.meshes if mesh[4] == tag for p in mesh[0]]
            near = (
                sum(p[0] for p in pixels) / len(pixels),
                sum(p[1] for p in pixels) / len(pixels),
            )
            point = self._anchor((tag,), near)
            if point is None:
                self._hidden(_plain(name))
                continue
            self.callouts.append(_Callout(_plain(name), [point], _FIXTURE, targets=(tag,)))
        for mark in self.sketch["marks"]:
            x, y = c.project(mark["at_mm"])
            colour = _GREEN if mark.get("reads") else _CONTACT
            c.circle(x, y, 6, fill=colour, outline=_WHITE)
            if mark.get("reads"):
                head = (x, y - self.ARROW_PX)
                c.arrow((x, y - 8), head, _GREEN, width=3)
                plus, arm = (x + 14, head[1] + 10), self.PLUS_PX
                c.line((plus[0] - arm, plus[1]), (plus[0] + arm, plus[1]), _GREEN, width=3)
                c.line((plus[0], plus[1] - arm), (plus[0], plus[1] + arm), _GREEN, width=3)
            self.callouts.append(_Callout(_plain(mark["label"]), [(x, y)], colour))
        self._labels()
        if self.lane_overflow > 0:
            return
        c.assert_text_layout(min_scale=_BODY_SCALE)

    def _plate(self):
        """The surface plate: a hatched line under the lowest solid, the full drawing wide."""
        c = self.canvas
        up = self.camera[1]
        lowest = min((p for mesh in self.meshes for p in mesh[0]), key=lambda p: _dot3(p, up))
        y = c.project(lowest)[1] + 1
        left, _, right, _ = self.viewport
        c.line((left, y), (right, y), _INK, width=3)
        for x in range(int(left) + 12, int(right), 18):
            c.line((x, y + 2), (x - 9, y + 11), _INK, width=1)
        self.callouts.append(_Callout("SURFACE PLATE", [(right - 24, y)], _INK))
