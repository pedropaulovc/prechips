"""Printable bench instructions from the validated bundle and fresh rule findings.

The traveler is the shop-floor copy: one setup per section, in shop language.
Operative targets print at DRO resolution; full precision, rule identities,
hashes and uncertainty records stay in report.json. Unresolved inputs are never
hidden: they print as plain STOP lines, op-row boxes or a "not verified" line.
"""

from __future__ import annotations

import math
import re
from html import escape

from .model import tolerance_requirements
from .rules.resolution import (
    MANUAL,
    SAW_OPS,
    WORKHOLDING_CATEGORIES,
    inventory_category,
    resolve,
    saw_setup,
    selected_references,
)
from .rules.resolution import record as _mapping

_CSS = """@page { size: Letter portrait; margin: .4in; }
* { box-sizing: border-box; }
body { margin: 0; color: #000; background: #fff; font: 8pt/1.25 Arial, sans-serif; }
.page { break-after: page; page-break-after: always; }
.page:last-child { break-after: auto; page-break-after: auto; }
h1 { margin: 0; font-size: 12pt; } h2 { font-size: 9pt; margin: 5pt 0 2pt; \
border-bottom: 1px solid #000; break-after: avoid; page-break-after: avoid; }
h3 { font-size: 8pt; margin: 4pt 0 1pt; break-after: avoid; page-break-after: avoid; }
p { margin: 2pt 0; } .meta { display: flex; justify-content: space-between; gap: 8pt; }
.banner { border: 2px solid #000; text-align: center; font-weight: bold; padding: 1pt; \
margin: 3pt 0; }
.stop { border: 2.5px solid #000; padding: 2pt 4pt; margin: 3pt 0; font-weight: bold; \
break-inside: avoid; }
.unverified, .caution { border: 1px dashed #000; padding: 2pt 4pt; margin: 3pt 0; \
break-inside: avoid; }
.caution { border-style: solid; }
.stop p, .unverified p, .caution p { margin: 1pt 0; }
ol, ul { margin: 2pt 0 2pt 1.6em; padding: 0; } li { margin: 0 0 1pt; }
table { width: 100%; border-collapse: collapse; margin: 2pt 0; table-layout: fixed; }
th, td { border: 1px solid #555; padding: 1pt 2pt; text-align: left; vertical-align: top; \
overflow-wrap: anywhere; }
th { background: #eee; } thead { display: table-header-group; }
tr, tbody { break-inside: avoid; page-break-inside: avoid; } .operations { font-size: 7.5pt; }
tr.warn td { border-top: 0; padding-left: 8pt; }
tr.warn .box { display: inline-block; margin: 0 4pt 1pt 0; }
td .box { display: block; border: 1.5px solid #000; font-weight: bold; padding: 0 2pt; \
margin-top: 1pt; }
.keep { break-inside: avoid; page-break-inside: avoid; }
.contours { columns: 3; column-gap: 8pt; font-size: 7pt; }
.contour { break-inside: avoid; page-break-inside: avoid; margin-bottom: 4pt; }
.contour h3 { font-size: 7.5pt; }
.fixture-render { margin: 4pt 0; break-inside: avoid; page-break-inside: avoid; }
.fixture-render img { display: block; width: 100%; max-height: 4.2in; object-fit: contain; \
border: 1px solid #999; }
.fixture-render figcaption { font-size: 7.5pt; }
.signoff { margin-top: 6pt; break-before: avoid; page-break-before: avoid; }
.foot { text-align: right; font-size: 6pt; margin-top: 3pt; color: #444; }
@media screen { body { max-width: 7.7in; margin: 12pt auto; } .page { margin-bottom: 24pt; } }
"""
# Operative targets print at DRO display resolution; report.json keeps every digit.
_DRO_DECIMALS = {"mm": 2, "in": 4}
# A planned tool path ending this close to jaws, a dead centre or the jaw tops is
# hand-feed territory: it is boxed on the op row instead of buried in clearance prose.
_CRASH_ZONE_MM = 3.0
_REQUIREMENT_NAMES = {
    "dia": "Ø",
    "position_dia": "position Ø",
    "angularity_dia": "angularity Ø",
    "coaxiality_dia": "coaxiality Ø",
    "finish_ra": "Ra",
    "height_above_pivot": "height over pivot",
    "radius": "R",
    "bottom_radius": "bottom R",
    "arc_len": "arc length",
    "bottom_arc_len": "bottom arc length",
    "land_angle_deg": "land angle °",
    "tip_land": "tip land",
}
# Plain topics for checks the planner could not complete (report.json keeps the detail).
_TOPICS = {
    "accessibility": "tool access",
    "reach": "tool reach",
    "internal_corner_radius": "corner radius vs cutter",
    "tool_resolves": "tool / holder fit",
    "headroom": "headroom and clearance",
    "envelope": "machine envelope",
    "travel": "axis travel",
    "fixture_interference": "holding clearance",
    "thin_wall_under_clamp": "thin walls under clamping",
    "vise": "vise grip",
    "stickout": "stickout",
    "stock_diameter": "chuck / collet size",
    "turned_profile": "turned profile",
    "turning_deflection": "deflection",
    "zero_check": "DRO zero check",
    "coordinates": "coordinates",
    "inspection": "inspection limits / gauges",
    "datum_consistency": "datum transfer",
    "blind_depth": "hole depths",
    "sizing": "finishing tool size",
    "speeds_feeds": "starting speeds / feeds",
    "coverage": "every drawn surface has an op",
    "indexing": "indexing",
    "hold_fields": "holding details",
    "order": "op order",
    "op_chain": "op sequence",
    "construction": "construction",
    "engagement": "cutter engagement",
    "saw_cut": "saw cut",
}
_DIRECTIONS = {
    "radially_inward": "face from OD to centre",
    "radially_outward": "face from centre outward",
    "toward_chuck": "toward chuck",
    "toward_shoulder": "toward shoulder",
    "plunge_radial": "plunge straight in",
    "apex_to_base": "apex to base",
    "conventional": "conventional",
    "climb": "climb",
}
# Shop names for inventory kinds whose records carry no name.
_KIND_NAMES = {
    "chuck_3jaw": "3-jaw chuck",
    "chuck_4jaw": "4-jaw chuck",
    "blocks_123": "1-2-3 blocks",
    "v_blocks": "V-blocks",
    "steady_rest": "steady rest",
    "follow_rest": "follow rest",
    "angle_plate": "angle plate",
    "clamping_kit": "clamping kit",
    "dividing_head": "dividing head",
}
# Zero-setting methods in bench words; the touched surface is implied by the method.
_METHODS = {
    "trial_cut_measure": "take a light trial cut, measure the diameter",
    "face_then_set": "face it, then set",
    "touch_then_set": "touch it, then set",
    "touch_then_set_after_face": "touch the faced end, then set",
}
_STOCK_FORMS = {
    "round_bar": "round bar",
    "rectangular_blank": "rectangular blank",
    "prepared_blank": "prepared blank",
}
# Stock / stock-state keys that place solids for the kernel; not bench instructions.
_PLACEMENT_KEYS = {"origin_mm", "axis", "section_axis", "as_is_faces", "id", "components"}


def _status(finding):
    status = finding.status
    return getattr(status, "value", status)


def _field(finding, name, default=None):
    return getattr(finding, "sentence" if name == "message" else name, default)


def _text(value):
    if value is None or value == "unknown":
        return "?"
    if value == "not_applicable":
        return "—"
    if isinstance(value, (list, tuple)):
        return ", ".join(map(_text, value))
    return str(value).replace("_", " ")


def _known(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _amount(value):
    """A number, or the value of a measured ``{value = ...}`` record; else None."""
    if isinstance(value, dict):
        value = value.get("value")
    return value if _known(value) else None


def _number(value, precision=None):
    """Declared drawing precision fixes the decimals; any other known number prints its
    own value (six significant digits, float residue below 1e-6 dropped), never ``?``."""
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return _text(value)
    if not math.isfinite(value):
        return "?"
    result = f"{value:.{precision}f}" if isinstance(precision, int) else f"{round(value, 6):g}"
    return result.removeprefix("-") if float(result) == 0 else result


def _sentence(text):
    """Shouted drawing text (``LOW-CARBON STEEL``) reads as ordinary words."""
    text = str(text)
    return text[:1] + text[1:].lower() if text.isupper() else text


def _op_number(value):
    return value if isinstance(value, int) else int(value) if str(value).isdigit() else value


def _ops_label(ops, every=None):
    ops = list(dict.fromkeys(str(op) for op in ops if op not in (None, "")))
    if not ops:
        return ""
    if every and set(ops) == set(every) and len(ops) > 1:
        return "all ops"
    ordered = sorted(ops, key=lambda op: (not op.isdigit(), int(op) if op.isdigit() else 0, op))
    return ("op " if len(ordered) == 1 else "ops ") + ", ".join(ordered)


class _Box(str):
    """A table-cell line printed as a bold boxed warning."""


class _Row(tuple):
    """Table cells plus full-width warnings printed beneath the row."""

    def __new__(cls, cells, warnings=()):
        row = super().__new__(cls, cells)
        row.warnings = tuple(dict.fromkeys(warnings))
        return row


def _p(text, css=""):
    attribute = f' class="{css}"' if css else ""
    return f"<p{attribute}>{escape(str(text))}</p>"


def _cell_line(line):
    if isinstance(line, _Box):
        return f'<span class="box">{escape(str(line))}</span>'
    return escape(str(line))


def _table(headings, rows, css="", widths=None):
    columns = ""
    if widths:
        columns = (
            "<colgroup>" + "".join(f'<col style="width:{w}%">' for w in widths) + "</colgroup>"
        )
    attribute = f' class="{css}"' if css else ""
    result = [f"<table{attribute}>", columns, "<thead><tr>"]
    result.extend(f"<th>{escape(h)}</th>" for h in headings)
    result.append("</tr></thead>")
    for row in rows:
        # A row may carry full-width warning lines printed directly beneath it.
        warnings = list(row.warnings) if isinstance(row, _Row) else []
        result.append('<tbody class="op"><tr>' if warnings else "<tbody><tr>")
        for cell in row:
            lines = cell if isinstance(cell, (list, tuple)) else [cell]
            parts = []
            for line in lines:
                if parts and not isinstance(line, _Box):
                    parts.append("<br>")
                parts.append(_cell_line(line))
            result.append("<td>" + "".join(parts) + "</td>")
        result.append("</tr>")
        if warnings:
            result.append(
                f'<tr class="warn"><td colspan="{len(headings)}">'
                + "".join(_cell_line(_Box(w)) for w in warnings)
                + "</td></tr>"
            )
        result.append("</tbody>")
    result.append("</table>")
    return "".join(result)


def _list(items, ordered=True):
    tag = "ol" if ordered else "ul"
    return f"<{tag}>" + "".join(f"<li>{escape(str(i))}</li>" for i in items) + f"</{tag}>"


def _box(css, heading, lines):
    if not lines:
        return ""
    return f'<div class="{css}">' + _p(heading) + "".join(_p(line) for line in lines) + "</div>"


class _Traveler:
    def __init__(self, bundle, findings, report, approval):
        self.bundle = bundle
        self.plan = bundle.plan
        self.features = bundle.features.get("features", {})
        self.general_precision = bundle.features.get("precision")
        self.findings = sorted(
            findings, key=lambda f: (_field(f, "rule", ""), _field(f, "subject", ""))
        )
        self.records = {
            (_field(f, "rule"), _field(f, "subject")): _field(f, "numbers", {})
            for f in self.findings
        }
        self.report = report
        self.approval = approval or {}
        evidence = self.approval.get("first_article")
        current_hash = report.get("hash")
        self.checked = (
            report.get("verification") == "checked"
            and self.approval.get("approved") is True
            and isinstance(current_hash, str)
            and re.fullmatch(r"[0-9a-f]{64}", current_hash) is not None
            and self.approval.get("hash") == current_hash
            and isinstance(evidence, str)
            and bool(evidence.strip())
            and evidence.strip().lower() != "unknown"
            and not self.approval.get("warnings")
        )
        self.units = bundle.features.get("units", "unknown")
        self.decimals = _DRO_DECIMALS.get(self.units, 2)
        self.pages = []
        self.references = {}
        for reference in sorted(selected_references(self.plan)):
            if isinstance(reference, str) and reference not in ("unknown", "none"):
                self.references[reference] = self.reference(reference)
        self.faces = {
            face: name
            for name, feature in self.features.items()
            for face in (feature.get("faces") or [] if isinstance(feature, dict) else [])
            if isinstance(face, str)
        }
        self.frames = {}
        for setup in self.plan.get("setups", []):
            frame = setup.get("frame")
            if isinstance(frame, str) and frame != "unknown":
                self.frames.setdefault(frame, []).append(setup["id"])
        self.setup = None

    # ------------------------------------------------------------------ numbers
    def precision(self, feature=None, dimension=None):
        overrides = self.features.get(feature, {}).get("precision", {})
        if isinstance(overrides, dict):
            return overrides.get(dimension, self.general_precision)
        return overrides

    def value(self, value, feature=None, dimension=None, drawing=True):
        """Format with the dimension's declared drawing precision when one exists.

        ``drawing=False`` ignores drawing precision: a print class for a tolerance
        band is not the resolution of a computed machine target.
        """
        if dimension in {"op", "before_ops", "after_op", "retouch_after", "passes"}:
            return _text(value)
        if isinstance(value, dict):
            return (
                "; ".join(
                    f"{_text(k)}: {self.value(v, feature, k, drawing)}"
                    for k, v in value.items()
                    if not self.metadata(k)
                )
                or "—"
            )
        if isinstance(value, (list, tuple)):
            return " / ".join(self.value(v, feature, dimension, drawing) for v in value) or "—"
        if isinstance(value, bool):
            return "yes" if value else "no"
        return _number(value, self.precision(feature, dimension) if drawing else None)

    @staticmethod
    def angle(value):
        """Checkpoint angles: whole degrees print bare, others at 0.01°."""
        return _number(round(value, 2)) if _known(value) else _text(value)

    @staticmethod
    def direction(value):
        if value in _DIRECTIONS:
            return _DIRECTIONS[value]
        match = re.fullmatch(r"(positive|negative)_setup_([xyz])", str(value))
        if match:
            sign = "+" if match[1] == "positive" else "−"
            return f"toward {sign}{match[2].upper()}"
        return _text(value).replace("toward ", "→ ")

    def operative(self, value):
        """Machine targets (tips, stations, cutter centres) print at DRO resolution."""
        if isinstance(value, (list, tuple)):
            return " / ".join(self.operative(v) for v in value)
        if isinstance(value, dict) and "value" in value:
            value = value["value"]
        return _number(value, self.decimals)

    def band(self, value, feature, dimension):
        """A drawing acceptance band (``6.330–6.350``) at the drawing's own precision."""
        return self.value(value, feature, dimension).replace(" / ", "–")

    @staticmethod
    def metadata(key):
        return key in _METADATA or key.endswith(("_cite", "_verify")) or key == "verify"

    # ------------------------------------------------------------- vocabulary
    def reference(self, reference, category=None):
        if reference in (None, "unknown", "none", "not_applicable"):
            return _text(reference)
        if not isinstance(reference, str):
            return "?"
        identity_category = category
        if category == "fixtures":
            identity_category = (
                inventory_category(self.bundle, reference, WORKHOLDING_CATEGORIES) or category
            )
        item = resolve(self.bundle, identity_category, reference)
        root, _, member = reference.partition("/")
        raw = (
            _mapping(_mapping(self.bundle.inventory.get(identity_category)).get(root))
            if identity_category
            else {}
        )
        if not raw:
            raw_category = inventory_category(self.bundle, reference, tuple(self.bundle.inventory))
            raw = (
                _mapping(_mapping(self.bundle.inventory.get(raw_category)).get(root))
                if raw_category
                else {}
            )
        record = item or raw
        name = record.get("name", record.get("label"))
        if not name:
            if category == "machines" or root in _mapping(self.bundle.inventory.get("machines")):
                name = root
            else:
                kind = record.get("kind", "unknown")
                if kind in _KIND_NAMES:
                    name = _KIND_NAMES[kind]
                    size = _amount(record.get("diameter_in"))
                    if size is not None:
                        name = f"{size:g} in {name}"
                    if re.fullmatch(r"[A-Z]+-?\d+", root):
                        name = f"{root} {name}"
                elif kind in {"accessory", "unknown", "custom"}:
                    name = re.sub(r"\bmt(\d)\b", r"MT\1", root.replace("-", " ").replace("_", " "))
                else:
                    name = _text(kind)
                name = name.removesuffix(" set")
        if member:
            if record.get("kind") == "micrometer_set":
                member = member.removesuffix("in") + " in"
            elif record.get("kind") == "qctp_set":
                number, _, role = member.partition("-")
                name = "QCTP holder"
                member = f"#{number} {role.replace('-', '/')}" if number.isdigit() else member
            else:
                # "1-4in" is a 1/4 in size; "0-1in" is a 0–1 in range.
                member = re.sub(r"\b0-(\d+)in\b", r"0-\1 in", member)
                member = re.sub(r"\b([1-9]\d*)-(\d+)in\b", r"\1/\2 in", member)
                member = re.sub(r"^(\d+)in$", r"\1 in", member)
                member = re.sub(r"-(\d+)fl", r" \1-flute", member)
            if record.get("kind") == "center_drill_set" and member.isdigit():
                member = "#" + member
            name = f"{name} {member}" if record.get("kind") == "qctp_set" else f"{member} {name}"
        elif item:
            for field, unit in (("tip_in", "in"), ("dia_in", "in"), ("dia_mm", "mm")):
                size = record.get(field)
                if isinstance(size, (int, float)):
                    name = f"{size:g} {unit} {name}"
                    break
        if record.get("standard"):
            name = f"{record['standard']} {name}"
        return f"{name} (not in shop list)" if item is None else str(name)

    def short_reference(self, reference, category=None):
        label = self.reference(reference, category)
        for full, short in (
            ("4-flute", "4fl"),
            ("2-flute", "2fl"),
            ("endmill", "EM"),
            ("center drill", "CD"),
            ("drill index", "drill"),
            ("dial test indicator", "DTI"),
            ("dial indicator", "indicator"),
            ("micrometers", "mic"),
            ("micrometer", "mic"),
        ):
            label = label.replace(full, short)
        return label

    def tool_name(self, reference):
        """Short shop name for a cutting tool."""
        item = resolve(self.bundle, "tools", reference)
        if not item:
            return self.short_reference(reference, "tools")
        member = reference.partition("/")[2]
        kind = item.get("kind")
        if kind == "insert_holders":
            entering = _amount(item.get("entering_angle_deg"))
            if entering is None:
                return f"{member} insert holder"
            role = "profiling" if entering < 90 else "turning/facing"
            return f"{member} {role} holder"
        if kind == "parting_blade":
            width = _amount(item.get("blade_width_mm"))
            return (f"{self.operative(width)} mm " if width else "") + "parting blade"
        return self.short_reference(reference, "tools")

    def tool_detail(self, reference):
        item = resolve(self.bundle, "tools", reference)
        if not item:
            return ["not in the shop tool list"]
        detail = []
        if item.get("make"):
            detail.append(str(item["make"]))
        if item.get("hand") in ("right", "left"):
            detail.append(f"{item['hand']}-hand")
        if item.get("insert"):
            detail.append(f"{item['insert']} insert")
        nose = _amount(item.get("nose_radius_mm"))
        if nose is not None:
            detail.append(f"nose R{self.operative(nose)}")
        if item.get("size_in"):
            detail.append(f"{item['size_in']} in")
        for key, label in (("dia_mm", "Ø"), ("reach_mm", "reach ")):
            size = _amount(item.get(key))
            if size is not None:
                detail.append(f"{label}{self.operative(size)}")
        flutes = item.get("flutes")
        if isinstance(flutes, int) and item.get("kind") != "endmill_set":
            detail.append(f"{flutes} flutes")
        for key in ("material", "coating"):
            if isinstance(item.get(key), str) and item[key] != "unknown":
                detail.append(item[key])
        return detail

    def feature_name(self, key):
        if not isinstance(key, str) or key == "unknown":
            return "?"
        name = re.sub(r"_pos_([xyz])$", lambda m: f" (+{m[1].upper()} side)", key)
        name = re.sub(r"_neg_([xyz])$", lambda m: f" (−{m[1].upper()} side)", name)
        name = re.sub(r"_datum_([a-z])$", lambda m: f" (datum {m[1].upper()})", name)
        return name.replace("_", " ")

    def zero_name(self, setup):
        return f"Setup {setup['id']} zero"

    def bench(self, text, setup=None):
        """Plan / rule prose in shop words: no ids, files, hashes or long decimals."""
        setup = setup or self.setup
        text = str(text) if text is not None else "?"
        text = re.sub(r"(?i)\bAUTHOR'S CHOICE\b\s*:?\s*", "", text)
        text = re.sub(
            r"#\d+/ADVANCED_FACE\[\d+\]/\w+",
            lambda m: self.feature_name(self.faces[m[0]]) if m[0] in self.faces else "a face",
            text,
        )
        for reference, label in sorted(self.references.items(), key=lambda pair: -len(pair[0])):
            text = text.replace(reference, label)
        for key in sorted(self.features, key=len, reverse=True):
            if "_" in key:
                text = re.sub(rf"\b{re.escape(key)}\b", self.feature_name(key), text)
        for frame, users in self.frames.items():
            if setup is not None and setup.get("frame") == frame:
                text = re.sub(rf"\b{re.escape(frame)}\s*(?=[XYZ]\s?(?:=\s?)?[-+−]?\d)", "", text)
                text = re.sub(rf"\bframe {re.escape(frame)}\b", self.zero_name(setup), text)
            else:
                name = "Setup " + "/".join(users) + " zero"
                pattern = (
                    rf"\bframe {re.escape(frame)}\b"
                    rf"|\b{re.escape(frame)}(?=\s*[XYZ]\s?(?:=\s?)?[-+−]?\d)"
                )
                text = re.sub(pattern, name, text)
        text = re.sub(
            r"\b([A-Z][a-z]+(?:[A-Z][a-z]+)+)\b",
            lambda m: re.sub(r"(?<!^)(?=[A-Z])", " ", m[1]).lower(),
            text,
        )
        text = re.sub(r"\b[0-9a-fA-F]{32,64}\b", "", text)
        text = re.sub(
            r"https?://\S+|(?:[A-Za-z]:[\\/]|(?:\.?\.?/)?(?:cad|src|examples|harmonic-analyzer)/)\S+",
            "",
            text,
        )
        text = text.replace("PLAN.md", "approved plan")
        text = re.sub(
            r"(?<![\w.])(-?\d+\.\d{4,})(?![\w.])",
            lambda m: _number(float(m[1]), self.decimals),
            text,
        )
        for rule in {key[0] for key in self.records}:
            text = text.replace(rule, _text(rule))
        text = re.sub(r"(?<=[a-z])(?=\d+(?:\.\d+)?mm\b)|(?<=\d)(?=mm\b)", " ", text)
        return re.sub(r"\s{2,}", " ", _text(text)).strip()

    def paragraphs(self, mapping, formatter=None):
        parts = []
        for key, value in mapping.items():
            if self.metadata(key) or key in _PLACEMENT_KEYS:
                continue
            value = (formatter or self.value)(value, dimension=key)
            parts.append(f"{_text(key)}: {value}")
        return self.bench("; ".join(parts))

    def machine(self, setup):
        return _mapping(resolve(self.bundle, "machines", setup.get("machine")))

    def lathe(self, setup):
        return self.machine(setup).get("kind") == "lathe"

    def cutting_ops(self, setup):
        return [str(op["op"]) for op in setup.get("ops", []) if op.get("do") not in MANUAL]

    # ------------------------------------------------------------ status boxes
    def subject_label(self, subject, setup):
        sid, _, op = subject.partition(":")
        if setup and sid == setup["id"]:
            return ("op " + op) if op else ""
        if sid in self.features:
            requirement = _REQUIREMENT_NAMES.get(op, _text(op)) if op else ""
            return (self.feature_name(sid) + " " + requirement).strip()
        if any(sid == s["id"] for s in self.plan.get("setups", [])):
            return f"Setup {sid}" + (f" op {op}" if op else "")
        return ""

    def plain_error(self, rule, message, subject):
        message = str(message)
        for prefix in (subject + ":", subject.replace(":", " ") + ":"):
            if message.startswith(prefix):
                message = message[len(prefix) :].strip()
        if rule == "accessibility" and "occluded" in message:
            return "tool or holder hits the part or the holding"
        if "point away from the setup approach" in message:
            return "faces to cut point away from the tool; they cannot be cut in this setup"
        if rule == "fixture_interference":
            message = message.removeprefix(
                "fixture interpenetrates the work or another fixture:"
            ).strip()
            return "holding parts clash: " + self.bench(message)
        return self.bench(message)

    def status_lines(self, findings, setup=None, skip_ops=False):
        """Errors → STOP lines; warnings → CAUTION; unknowns → one 'not verified' line."""
        stops, cautions, unverified = {}, {}, {}
        every = self.cutting_ops(setup) if setup else None
        for finding in findings:
            status = _status(finding)
            rule = _field(finding, "rule")
            subject = _field(finding, "subject", "")
            label = self.subject_label(subject, setup)
            on_op = bool(setup) and label.startswith("op ")
            if status == "error":
                text = self.plain_error(rule, _field(finding, "message", "?"), subject)
                stops.setdefault(text, []).append(label)
            elif status == "warn":
                if skip_ops and on_op:
                    continue  # Printed in a box on that op's row.
                message = _field(finding, "message", "?")
                for prefix in (subject + ":", subject.replace(":", " ") + ":"):
                    message = message.removeprefix(prefix).strip()
                cautions.setdefault(self.bench(message), []).append(label)
            elif status in ("unknown", "unsupported"):
                unverified.setdefault(_TOPICS.get(rule, _text(rule)), []).append(label)

        def labelled(text, labels):
            ops = [label[3:] for label in labels if label.startswith("op ")]
            others = list(dict.fromkeys(label for label in labels if label and label[:3] != "op "))
            scope = ", ".join(filter(None, [_ops_label(ops, every), *others]))
            return (
                f"{scope[:1].upper() + scope[1:]} — {text}"
                if scope
                else text[:1].upper() + text[1:]
            )

        stop_lines = [labelled(text, labels) for text, labels in stops.items()]
        caution_lines = [labelled(text, labels) for text, labels in cautions.items()]
        topics = []
        for topic, labels in unverified.items():
            ops = [label[3:] for label in labels if label.startswith("op ")]
            scope = _ops_label(ops, every)
            topics.append(f"{topic} ({scope})" if scope else topic)
        return stop_lines, caution_lines, topics

    def status_boxes(self, stops, cautions, topics):
        html = _box("stop", "✗ STOP — do not run until resolved:", stops)
        html += _box("caution", "! CAUTION:", cautions)
        if topics:
            html += _box(
                "unverified",
                "? Not verified by the planner — confirm at the machine:",
                ["; ".join(topics) + "."],
            )
        return html

    # -------------------------------------------------------------- holding
    def hold(self, setup):
        hold = _mapping(setup.get("hold"))
        lathe = self.lathe(setup)
        steps = []

        def stated(key):
            value = hold.get(key)
            return value not in (None, "none", "not_applicable")

        fixture = hold.get("fixture", "unknown")
        if fixture == "unknown":
            steps.append("STOP: holding not chosen — do not run.")
        else:
            mount = "Mount the " + self.reference(fixture, "fixtures")
            if stated("chuck"):
                mount += " with the " + self.reference(hold["chuck"], "fixtures")
            if stated("jaws_along"):
                mount += f"; jaws along {_text(hold['jaws_along']).upper()}"
            if stated("fixed_jaw"):
                mount += f"; fixed jaw {_text(hold['fixed_jaw'])}"
            steps.append(mount + ".")
        if stated("parallels") and hold["parallels"] != "unknown":
            line = "Parallels: " + self.reference(hold["parallels"])
            if stated("riser"):
                line += ", standing on " + self.reference(hold["riser"])
            if stated("support_orientation"):
                line += f" ({_text(hold['support_orientation'])} up)"
            steps.append(line + ".")
        supports = hold.get("supports")
        if isinstance(supports, str) and supports not in ("none", "not_applicable", "unknown"):
            if not (stated("riser") and supports == hold.get("riser")):
                steps.append("Supports: " + self.reference(supports) + ".")
        for support in supports if isinstance(supports, list) else []:
            support = _mapping(support)
            line = "Support: " + self.bench(support.get("ref", "?"))
            if support.get("ops"):
                line += f" for {_ops_label(support['ops'])}"
            if _known(support.get("jaw_lead_mm")):
                line += f", jaws {self.operative(support['jaw_lead_mm'])} mm ahead of the tool"
            steps.append(line + ".")
        if stated("support"):
            label = "Tailstock: " if lathe else "Support: "
            if hold["support"] == "unknown":
                steps.append("STOP: support / restraint not chosen — do not run.")
            else:
                line = label + self.reference(hold["support"])
                if _known(hold.get("quill_extension_mm")):
                    line += f", quill out {self.operative(hold['quill_extension_mm'])} mm"
                steps.append(line + ".")
        for key, label in (
            ("locate", "Locate"),
            ("grip_on", "Grip on"),
            ("stop", "Stop"),
        ):
            if stated(key):
                steps.append(f"{label}: {self.bench(hold[key], setup)}.")
        if stated("clamp"):
            for step in str(hold["clamp"]).split(";"):
                step = self.bench(step, setup)
                if step:
                    steps.append(step[:1].upper() + step[1:] + ".")
        for index, clamp in enumerate(
            hold.get("clamps") if isinstance(hold.get("clamps"), list) else [], 1
        ):
            clamp = _mapping(clamp)
            line = f"Clamp {index}: {self.reference(clamp.get('ref'))}"
            if clamp.get("note"):
                line += " — " + self.bench(clamp["note"], setup)
            steps.append(line + ".")
        for key, label in (
            ("jaw_protection", "Jaw protection"),
            ("centre_lubrication", "Centre"),
            ("note", "Note"),
        ):
            if stated(key):
                steps.append(f"{label}: {self.bench(hold[key], setup)}.")
        steps = [re.sub(r"\.{2,}$", ".", step) for step in steps]
        html = "<h2>HOLD</h2>" + _list(steps)
        facts = self.hold_facts(setup, hold, lathe)
        if facts:
            html += _table([name for name, _ in facts], [[value for _, value in facts]])
        return html + self.indexing(setup)

    def hold_facts(self, setup, hold, lathe):
        o = self.operative
        facts = []
        if _known(hold.get("grip_mm")):
            facts.append(("grip length mm", o(hold["grip_mm"])))
        elif hold.get("grip_mm") == "unknown":
            facts.append(("grip length mm", "? not set"))
        if _known(hold.get("stickout_mm")):
            facts.append(("stickout mm", o(hold["stickout_mm"])))
        elif hold.get("stickout_mm") == "unknown":
            facts.append(("stickout mm", "? not set"))
        jaw = self.jaw_front_z(setup)
        if jaw is not None:
            facts.append(("jaw fronts at Z", o(jaw)))
        tip = hold.get("support_tip_mm")
        if isinstance(tip, list) and len(tip) == 3 and _known(tip[2]):
            facts.append(("centre tip at Z", o(tip[2])))
        if _known(hold.get("quill_extension_mm")):
            facts.append(("quill out mm", o(hold["quill_extension_mm"])))
        if _known(hold.get("jaw_above_parallels_mm")):
            facts.append(("jaw top above parallels mm", o(hold["jaw_above_parallels_mm"])))
        along = _text(hold.get("jaws_along")).upper()
        if _known(hold.get("jaw_center_along_mm")) and along in ("X", "Y"):
            facts.append((f"jaw centre at {along}", o(hold["jaw_center_along_mm"])))
        for key, label in (
            ("parallels_centres_mm", "parallels at (X, Y)"),
            ("riser_centres_mm", "risers at (X, Y)"),
        ):
            points = hold.get(key)
            if isinstance(points, list) and points and all(isinstance(p, list) for p in points):
                facts.append((label, "; ".join(f"({o(p[0])}, {o(p[1])})" for p in points)))
        clock = hold.get("jaw_clock_deg")
        if _known(clock) and clock and not lathe:
            facts.append(("jaw 1 clocked °", _number(clock)))
        return facts

    def jaw_front_z(self, setup):
        """A lathe chuck's pose origin is the jaw-face centre on the spindle axis."""
        if not self.lathe(setup):
            return None
        pose = _mapping(_mapping(setup.get("hold")).get("pose"))
        origin, axis = pose.get("origin_mm"), pose.get("z")
        if (
            isinstance(origin, list)
            and isinstance(axis, list)
            and len(origin) == 3
            and all(_known(v) for v in origin)
            and abs(origin[0]) < 1e-6
            and abs(origin[1]) < 1e-6
            and axis == [0.0, 0.0, 1.0]
        ):
            return origin[2]
        return None

    def indexing(self, setup):
        hold = _mapping(setup.get("hold"))
        if "index" not in hold:
            return ""
        finding = next(
            (
                finding
                for finding in self.findings
                if _field(finding, "rule") == "indexing"
                and _field(finding, "subject") == setup["id"]
            ),
            None,
        )
        if finding is None:
            return _p("Index: ? Plate arithmetic not computed.")
        numbers = _field(finding, "numbers", {})
        feature = numbers.get("feature")
        r = _number  # Dividing-head arithmetic keeps its own digits; it is not a DRO reading.
        requested = self.value(numbers.get("requested_angle_deg"), feature, "angle_deg")
        actual = self.value(numbers.get("actual_angle_deg"), feature, "angle_deg")
        glyph = {"error": "✗", "warn": "!", "unknown": "?", "unsupported": "?"}.get(
            _status(finding), ""
        )
        tentative = "Tentative — " if _status(finding) == "unknown" else ""
        positions = numbers.get("positions")
        count = "one angular setting" if positions == 1 else f"{r(positions)} positions"
        parts = [
            f"Index: {glyph} {tentative}{self.short_reference(numbers.get('fixture'))}; "
            f"requested {requested}°; {count}; actual step {actual}°."
        ]
        if numbers.get("method") in {"direct", "worm"}:
            kind = "spindle" if numbers["method"] == "direct" else "crank"
            direction = "Reverse: " if numbers.get("direction") == "reverse" else ""
            parts.append(
                f"{direction}plate {r(numbers.get('plate'))}, "
                f"circle {r(numbers.get('circle'))}: "
                f"{r(numbers.get('turns'))} {kind} turns + "
                f"{r(numbers.get('spaces'))} hole spaces (spaces, not holes counted)."
            )
            parts.append("Nominal exact step." if numbers.get("exact") is True else "Nearest step.")
        else:
            parts.append("Plate / circle / turns / hole spaces: ?")
        tolerance = numbers.get("tolerance_deg")
        landing = numbers.get("max_position_error_deg")
        parts.append(
            (
                f"Angular tolerance ±{r(tolerance)}°"
                if _known(tolerance)
                else "Angular tolerance not set on the drawing"
            )
            + (f"; maximum cumulative landing error {r(landing)}°." if _known(landing) else ".")
        )
        closure = numbers.get("closure")
        if closure == "not_applicable":
            parts.append(
                "Single setting: no cycle closure."
                if positions == 1
                else "Open pattern: no cycle closure."
            )
        elif isinstance(closure, dict):
            parts.append(
                f"Cycle closure: {r(closure.get('actual_angle_deg'))}° against "
                f"{r(closure.get('target_angle_deg'))}°; error {r(closure.get('error_deg'))}°."
            )
        else:
            parts.append("Cycle closure: ?")
        return _p(self.bench(" ".join(parts)))

    # ------------------------------------------------------------- clearance
    def clearance(self, setup):
        if saw_setup(setup):
            return "<h2>CLEARANCE</h2>" + _p("Saw cut-off: no spindle clearance applies.")
        numbers = self.records.get(("headroom", setup["id"]), {})
        o = self.operative
        lathe = self.lathe(setup)
        if not numbers:
            return "<h2>CLEARANCE</h2>" + _p("? Clearance not computed — check it at the machine.")

        def fits(need, have):
            if not (_known(need) and _known(have)):
                return "? not computed — check at the machine"
            return "fits" if need <= have else "DOES NOT FIT"

        lines = []
        if lathe:
            unknown = []
            checks = (
                (
                    "Chuck Ø{need} in swing over bed Ø{have}",
                    "chuck_body_dia_mm",
                    "swing_over_bed_mm",
                    "chuck vs swing over bed",
                ),
                (
                    "Work Ø{need} in swing over cross-slide Ø{have}",
                    "stock_od_mm",
                    "swing_over_cross_slide_mm",
                    "work vs swing over cross-slide",
                ),
                (
                    "Length needed from the spindle nose {need} of {have} between centres",
                    "required_length_mm",
                    "between_centres_mm",
                    "length between centres",
                ),
            )
            for template, need_key, have_key, topic in checks:
                need, have = numbers.get(need_key), numbers.get(have_key)
                if _known(need) and _known(have):
                    text = template.format(need=o(need), have=o(have))
                    lines.append(f"{text}: {fits(need, have)}.")
                elif need_key in numbers or have_key in numbers:
                    unknown.append(topic)
            if unknown:
                lines.append("? Not computed — check at the machine: " + "; ".join(unknown) + ".")
            quill = _mapping(setup.get("hold")).get("quill_extension_mm")
            if _known(quill):
                lines.append(f"Tailstock quill out {o(quill)} mm.")
            jaw = self.jaw_front_z(setup)
            approaches = self.lathe_approaches(setup)
            if jaw is not None:
                closest = min(approaches.values(), default=None)
                text = f"Jaw fronts at Z {o(jaw)}"
                if closest is not None:
                    text += f"; closest planned tool stop {o(closest)} mm from the jaws"
                lines.append(text + ".")
            if not lines:
                lines.append("? Lathe clearance not computed — check swing and tailstock room.")
            return "<h2>CLEARANCE — lathe</h2>" + "".join(_p(line) for line in lines)
        unknown = "? Not computed — check at the machine: "
        missing = []
        if "head_centre_height_mm" in numbers:
            need, have = numbers.get("sum_mm"), numbers.get("spindle_to_table_max_mm")
            if _known(need):
                lines.append(
                    f"Dividing head: centre height {o(numbers.get('head_centre_height_mm'))}, "
                    f"work top above table {o(numbers.get('work_top_above_table_mm'))}; "
                    f"tool needs {o(need)} of {o(have)} spindle-to-table: {fits(need, have)}."
                )
            else:
                missing.append("spindle-to-table room over the dividing head")
        elif "bed_height_mm" in numbers or "sum_mm" in numbers:
            need, have = numbers.get("sum_mm"), numbers.get("spindle_to_table_max_mm")
            stack = [
                ("vise / fixture", numbers.get("bed_height_mm")),
                ("risers", numbers.get("support_blocks_mm")),
                ("parallels", numbers.get("parallels_mm")),
                ("work", numbers.get("stock_height_mm")),
                ("tool in holder", numbers.get("insertion_mm")),
            ]
            if _known(need):
                parts = [f"{name} {o(v)}" for name, v in stack if _known(v) and v]
                lines.append(
                    "Spindle-to-table stack: "
                    + " + ".join(parts)
                    + f" = {o(need)} needed of {o(have)}: {fits(need, have)}."
                )
            else:
                missing.append("spindle-to-table room (holding height not known)")
        stacks = {}
        for stack in numbers.get("stacks", []):
            key = tuple(
                stack.get(k)
                for k in ("tool_projection_mm", "tool_oal_mm", "holder_gauge_len_mm", "margin_mm")
            )
            stacks.setdefault(key, []).append(_text(stack.get("op")))
        every = self.cutting_ops(setup)
        for (projection, oal, holder, margin), ops in stacks.items():
            label = _ops_label(ops, every)
            if not (_known(projection) and _known(margin)):
                missing.append(f"tool stickout and headroom ({label})")
                continue
            lines.append(
                f"{label[:1].upper() + label[1:]}: tool sticks out {o(projection)} "
                f"(overall {o(oal)}), holder {o(holder)}; {o(margin)} mm to spare above the work."
            )
        jaw = _mapping(numbers.get("jaw_obstruction"))
        if _known(jaw.get("jaw_top_z")):
            lines.append(
                f"Jaw tops at Z {o(jaw['jaw_top_z'])}; work top "
                f"{o(numbers.get('stock_top_above_jaws_mm'))} mm above the jaws. "
                "Tool tips near the jaw tops are boxed on the op rows."
            )
        travel = numbers.get("travel_checks", {})
        for axis in ("x", "y"):
            record = _mapping(travel.get(axis))
            if record and not _known(record.get("required_mm")):
                missing.append(f"{axis.upper()} travel")
            elif record:
                lines.append(
                    f"{axis.upper()} travel: needs {o(record.get('required_mm'))} of "
                    f"{o(record.get('travel_mm'))}: "
                    f"{fits(record.get('required_mm'), record.get('travel_mm'))}."
                )
        if missing:
            lines.append(unknown + "; ".join(missing) + ".")
        return "<h2>CLEARANCE — mill</h2>" + "".join(_p(line) for line in lines)

    def lathe_approaches(self, setup):
        """Distance from each op's last planned Z to the jaw fronts (exposed side +Z)."""
        jaw = self.jaw_front_z(setup)
        result = {}
        if jaw is None:
            return result
        for op in setup.get("ops", []):
            if op.get("do") in MANUAL:
                continue
            zs = [op[k] for k in ("z_from", "z_to", "to_z") if _known(op.get(k))]
            if zs:
                result[str(op["op"])] = min(zs) - jaw
        return result

    def crash_boxes(self, setup, op):
        boxes = []
        o = self.operative
        if self.lathe(setup):
            jaw = self.jaw_front_z(setup)
            gap = self.lathe_approaches(setup).get(str(op["op"]))
            if gap is not None and gap < 0:
                boxes.append(_Box(f"STOP: PATH ENDS {o(-gap)} INSIDE JAWS (Z {o(jaw)})"))
            elif gap is not None and gap <= _CRASH_ZONE_MM:
                boxes.append(_Box(f"JAWS Z {o(jaw)}: {o(gap)} clear — hand feed to a stop"))
            tip = _mapping(setup.get("hold")).get("support_tip_mm")
            zs = [op[k] for k in ("z_from", "z_to", "to_z") if _known(op.get(k))]
            if isinstance(tip, list) and len(tip) == 3 and _known(tip[2]) and zs:
                gap = tip[2] - max(zs)
                if gap <= _CRASH_ZONE_MM:
                    boxes.append(_Box(f"DEAD CENTRE Z {o(tip[2])}: start clear of it"))
            return boxes
        cuts = _mapping(
            self.records.get(("headroom", setup["id"]), {}).get("cut_tip_above_jaws_mm")
        )
        value = cuts.get(str(op["op"]), cuts.get(op["op"]))
        if _known(value) and value < 0:
            boxes.append(_Box(f"TIP {o(-value)} BELOW JAW TOP — STOP"))
        elif _known(value) and value <= _CRASH_ZONE_MM:
            boxes.append(_Box(f"TIP {o(value)} ABOVE JAW TOP — check before plunging"))
        return boxes

    # ------------------------------------------------------------------ DRO
    def dro(self, setup, tools):
        if saw_setup(setup):
            return "<h2>DRO ZERO</h2>" + _p(
                "Saw setting uses the stated cut plane; no spindle DRO zero applies."
            )
        numbers = self.records.get(("zero_check", setup["id"]), {})
        authored = _mapping(setup.get("zero"))
        settings = _mapping(self.plan.get("dro"))
        lathe = self.lathe(setup)
        o = self.operative
        mode = "linear"
        if lathe:
            mode = (
                "radius"
                if settings.get("radius_mode") is True
                else "diameter"
                if settings.get("radius_mode") is False
                else "? radius/diameter"
            )
        pieces = [
            f"<h2>DRO ZERO — {escape(self.zero_name(setup))}, {escape(_text(self.units))}, "
            f"{escape(mode)} mode</h2>"
        ]
        if setup.get("zero") == "unknown":
            pieces.append(_p("STOP: no zero recipe — touch, Axis Set and jog checks not planned."))
        directions = _mapping(settings.get("direction"))
        if directions:
            pieces.append(
                _p(
                    "Positive directions: "
                    + "; ".join(
                        f"{k.upper()}+ {self.bench(v)}"
                        for k, v in directions.items()
                        if not self.metadata(k)
                    )
                    + ". Set each axis with Axis Set (never Preset). Then jog the stated "
                    "distance without touching: the display must show 'must read'. If it shows "
                    "the 'if reversed' value, STOP: fix the axis direction and redo the zero."
                )
            )
        axes = numbers.get("axes", {})
        top_feature = setup.get("stock_state", {}).get("top_feature")
        rows = []
        for axis in ("x", "y", "z"):
            if axis not in authored and axis not in axes:
                continue
            computed = axes.get(axis, {})
            touch = dict(authored.get(axis, {}))
            for key in ("radius_mm", "paper_mm", "edge_mm", "method"):
                if key in computed:
                    touch[key] = computed[key]
            target = touch.get("edge", touch.get("face", touch.get("feature")))
            contact = [self.bench(target) if target else "? contact not set"]
            method = touch.get("method")
            if method == "indicate_axis" or touch.get("from") == "indicated":
                contact.append("indicate (no edge-finder offset)")
            elif method not in (None, "paper", "touch"):
                contact.append(_METHODS.get(method, _text(method)))
            if "tool" in touch:
                contact.append(
                    "? tool not chosen"
                    if touch["tool"] in (None, "unknown")
                    else tools.get(touch["tool"]) or self.short_reference(touch["tool"])
                )
            if "holder" in touch and touch.get("tool") not in tools:
                contact.append("in " + self.short_reference(touch["holder"], "holders"))
            if touch.get("from") not in (None, "indicated"):
                contact.append("from " + _text(touch["from"]).upper() + " side")
            edge = touch.get("edge_mm")
            measured = method in {"trial_cut_measure", "face_then_set"}
            if _known(edge) and touch.get("from") != "indicated" and not measured:
                contact.append(f"surface at {o(edge)}")
            radius = touch.get("radius_mm")
            if _known(radius) and radius and touch.get("from") != "indicated":
                contact.append(f"edge-finder radius {o(radius)}")
            paper = touch.get("paper_mm")
            if _known(paper):
                contact.append(f"paper {o(paper)}" if paper else "direct contact, no paper")
            if touch.get("after_op") not in (None, "unknown"):
                contact.append(f"after op {_text(touch['after_op'])}")
            if touch.get("gauge"):
                contact.append("measure with " + self.short_reference(touch["gauge"], "gauges"))
            expected = self.reading(computed.get("check_reading"), computed.get("check_expression"))
            mirrored = self.reading(
                computed.get("mirrored_reading"), computed.get("mirrored_expression")
            )
            jog = computed.get("jog_mm")
            jog_direction = "−" if _known(jog) and jog < 0 else "+"
            rows.append(
                (
                    axis.upper(),
                    "; ".join(contact),
                    self.reading(computed.get("axis_set")),
                    f"{jog_direction}{axis.upper()} {o(abs(jog)) if _known(jog) else '?'}",
                    expected,
                    mirrored,
                )
            )
        pieces.append(
            _table(
                [
                    "axis",
                    "touch / pick up",
                    "Axis Set",
                    "jog, no touch",
                    "must read",
                    "if reversed",
                ],
                rows,
                widths=[5, 45, 13, 11, 13, 13],
            )
        )
        transfer = _mapping(authored.get("transfer"))
        if transfer:
            indicate = transfer.get("indicate")
            features = ", ".join(
                self.feature_name(f)
                for f in (indicate if isinstance(indicate, list) else [indicate])
            )
            gauge = transfer.get("tool", transfer.get("gauge"))
            line = f"Before zeroing: indicate the {features}"
            if gauge not in (None, "unknown"):
                line += " with the " + self.reference(gauge)
            limit = transfer.get("runout_limit_mm")
            line += (
                # A limit is never rounded: 0.0254 printed as 0.03 would loosen it.
                f"; tap true to {_number(limit)} mm total indicator reading or less, then re-check"
                if _known(limit)
                else "; runout limit not set — ? confirm the allowed runout"
            )
            if transfer.get("reindicate_after"):
                line += (
                    f". After {_ops_label(transfer['reindicate_after'])}: re-indicate and redo X/Y"
                )
            pieces.append(_p(line + "."))
        retouches = {}
        for record in numbers.get("retouch", []):
            key = (o(record.get("top_z")), o(record.get("paper_mm")), o(record.get("axis_set")))
            retouches.setdefault(key, []).append(_text(record.get("op")))
        for (top, paper, axis_set), ops in retouches.items():
            pieces.append(
                _p(
                    f"After {_ops_label(ops)}, before each new tool: touch "
                    f"{self.feature_name(top_feature) if top_feature else 'the top'} "
                    f"(Z {top}) with {paper} paper → Axis Set Z {axis_set}."
                )
            )
        for touch in numbers.get("tool_touches", []):
            pieces.append(_p(self.tool_touch(touch, tools)))
        for record in axes.values():
            if record.get("note"):
                pieces.append(_p(self.bench(record["note"])))
        return "".join(pieces)

    def reading(self, value, expression=None):
        """DRO readings; a measured-diameter expression reads as plain arithmetic."""
        if _known(value):
            return self.operative(value)
        text = value if isinstance(value, str) and value != "unknown" else expression
        if not isinstance(text, str) or text == "unknown":
            return "?"
        match = re.fullmatch(r"D\s*([+-])\s*(\d+(?:\.\d+)?)", text.strip())
        if match:
            sign = "+" if match[1] == "+" else "−"
            return f"measured Ø {sign} {self.operative(float(match[2]))}"
        return "measured Ø" if text.strip() == "measured D" else self.bench(text)

    def tool_touch(self, touch, tools):
        reference = touch.get("tool")
        name = tools.get(reference) or self.short_reference(reference)
        before = touch.get("before_ops")
        when = f"Before {_ops_label(before if isinstance(before, list) else [before])}"
        if touch.get("after_op") not in (None, "unknown"):
            when += f" (after op {_text(touch['after_op'])})"
        parts = [f"{when}, touch off {name}:"]
        if touch.get("x_method"):
            gauge = touch.get("gauge")
            parts.append(
                "X — "
                + self.bench(touch["x_method"])
                + (f" ({self.short_reference(gauge, 'gauges')})" if gauge else "")
                + "."
            )
        z_face = touch.get("z_face")
        if z_face:
            paper = touch.get("paper_mm")
            method = re.sub(r";?\s*Axis Set Z\.?$", "", str(touch.get("method", "touch")))
            text = f"Z — on the {self.bench(z_face)}: {_METHODS.get(method, self.bench(method))}"
            if _known(paper):
                text += f", paper {self.operative(paper)}" if paper else ", no paper"
            text += f"; Axis Set Z {self.reading(touch.get('z_axis_set', touch.get('edge_mm')))}."
            parts.append(text)
        return " ".join(parts)

    # -------------------------------------------------------------- features
    def feature_map(self, setup):
        if saw_setup(setup):
            return ""
        numbers = self.records.get(("coordinates", setup["id"]), {})
        lathe = numbers.get("x_display") == "diameter" or self.lathe(setup)
        o = self.operative
        grouped = {}
        for record in numbers.get("rows", []):
            feature = record.get("feature")
            coordinates = record.get("setup")
            if not isinstance(coordinates, (list, tuple)) or len(coordinates) != 3:
                continue
            if lathe:
                x = record.get("x_target_mm")
                if not _known(x) or not _known(coordinates[2]):
                    continue
                entry = grouped.setdefault(feature, {"dia": x, "z": []})
                entry["z"].append(coordinates[2])
            elif all(_known(v) for v in coordinates):
                grouped.setdefault((feature, tuple(coordinates)), {})
        if not grouped:
            return ""
        if lathe:
            rows = [
                (
                    self.feature_name(feature),
                    "Ø" + self.value(entry["dia"], feature, "dia"),
                    o(max(entry["z"])),
                    o(min(entry["z"])),
                )
                for feature, entry in grouped.items()
            ]
            table = _table(
                ["feature", "Ø (drawing)", "Z from", "Z to"], rows, widths=[40, 20, 20, 20]
            )
            note = "X reads diameter. Z values are where each finished surface starts and ends."
        else:
            rows = [
                (self.feature_name(feature), o(c[0]), o(c[1]), o(c[2])) for (feature, c) in grouped
            ]
            table = _table(["feature", "X", "Y", "Z (feature centre)"], rows)
            note = "Feature locations, not tool tips; the op table gives the tool targets."
        return f"<h2>FEATURE MAP — {escape(self.zero_name(setup))}</h2>" + table + _p(note)

    # ------------------------------------------------------------------ tools
    def tool_table(self, setup):
        """T-numbers in first-use order, one per tool + holder pair."""
        numbers, rows = {}, []
        for op in setup.get("ops", []):
            reference = op.get("tool")
            if op.get("do") in MANUAL or reference in (None, "unknown"):
                continue
            key = (reference, op.get("holder"))
            if key not in numbers:
                numbers[key] = f"T{len(numbers) + 1}"
                holder = op.get("holder")
                rows.append(
                    [
                        numbers[key],
                        self.tool_name(reference),
                        ", ".join(self.tool_detail(reference)) or "—",
                        self.short_reference(holder, "holders")
                        if holder not in (None, "unknown", "not_applicable")
                        else "—",
                        [],
                    ]
                )
            rows[int(numbers[key][1:]) - 1][4].append(str(op["op"]))
        by_tool = {}
        for (reference, _), number in numbers.items():
            by_tool.setdefault(reference, f"{number} {self.tool_name(reference)}")
        html = ""
        if rows:
            html = "<h2>TOOLS FOR THIS SETUP — pull before starting</h2>" + _table(
                ["T", "tool", "insert / size / material", "holder / station", "ops"],
                [(t, n, d, h, ", ".join(ops)) for t, n, d, h, ops in rows],
                widths=[5, 22, 35, 26, 12],
            )
        return numbers, by_tool, html

    # ------------------------------------------------------------- operations
    def tip(self, setup, op):
        o = self.operative
        endpoint = self.endpoint(setup, op)
        if endpoint:
            parts = [f"Z {o(endpoint.get('entry_z'))} → {o(endpoint.get('tip_z'))}"]
            if endpoint.get("exit_face", "not_applicable") != "not_applicable":
                parts.append(f"breaks through at {o(endpoint.get('exit_face'))}")
            elif _known(endpoint.get("depth_mm")):
                parts.append(f"depth {o(endpoint['depth_mm'])}")
            if not _known(endpoint.get("tip_z")):
                parts[0] = f"Z {o(endpoint.get('entry_z'))} → depth not set"
                parts.append(_Box("STOP: drill point length unknown"))
            return parts
        parts = []
        if "z_from" in op and "z_to" in op:
            parts.append(f"Z {o(op['z_from'])} → {o(op['z_to'])}")
        elif "to_z" in op:
            parts.append(f"Z → {o(op['to_z'])}")
        if "depth_mm" in op:
            parts.append(f"depth {o(op['depth_mm'])}")
        if "exit_mm" in op:
            parts.append(f"exit {o(op['exit_mm'])}")
        if isinstance(op.get("to_z_band"), list):
            low, high = op["to_z_band"][0], op["to_z_band"][-1]
            parts.append(f"allowed {_number(low)} to {_number(high)}")
        for key in ("z_from", "z_to"):
            if key in op and not ("z_from" in op and "z_to" in op):
                parts.append(f"{'from' if key == 'z_from' else 'to'} Z {o(op[key])}")
        if any("?" in part for part in parts):
            parts.append(_Box("STOP: Z target not set"))
        return parts or (["—"] if op.get("do") in MANUAL else [_Box("STOP: Z target not set")])

    def endpoint(self, setup, op):
        numbers = self.records.get(("blind_depth", op.get("feature")), {})
        return next(
            (
                e
                for e in numbers.get("endpoints", [])
                if e.get("setup") == setup["id"] and str(e.get("op")) == str(op["op"])
            ),
            None,
        )

    def tip_note(self, setup, op):
        """The tip-depth derivation belongs in the op notes, not the target cell."""
        endpoint = self.endpoint(setup, op)
        if not endpoint or endpoint.get("exit_face", "not_applicable") == "not_applicable":
            return None
        o = self.operative
        if not _known(endpoint.get("tip_z")):
            return None
        allowance = "lead_mm" if "lead_mm" in endpoint else "point_mm"
        point = endpoint.get(allowance)
        through = f"exit face {o(endpoint.get('exit_face'))}"
        if _known(point) and point:
            through += f" − {'lead' if allowance == 'lead_mm' else 'drill point'} {o(point)}"
        tip, exit_mm = o(endpoint.get("tip_z")), o(endpoint.get("exit_mm"))
        return f"tip Z {tip} = {through} − break-through {exit_mm}."

    def inspection(self, op, notes):
        rows = ["? inspection checks not set"] if op.get("checks") == "unknown" else []
        feature = op.get("feature")
        definition = self.features.get(feature, {})
        missing = _mapping(op.get("missing_requirements"))
        methods = _mapping(op.get("inspection_methods"))
        for requirement, reference in (_mapping(op.get("checks")) | missing).items():
            finding = next(
                (
                    f
                    for f in self.findings
                    if _field(f, "rule") == "inspection"
                    and _field(f, "subject") == f"{feature}:{requirement}"
                ),
                None,
            )
            name = _REQUIREMENT_NAMES.get(requirement, _text(requirement))
            if requirement in missing:
                target = "(no drawing limit)"
            else:
                target = self.band(definition.get(requirement), feature, requirement)
            gauge = (
                "no gauge chosen"
                if reference in (None, "unknown")
                else self.short_reference(reference, "gauges")
            )
            unresolved = (
                requirement in missing
                or finding is None
                or _status(finding)
                in (
                    "unknown",
                    "unsupported",
                )
            )
            line = f"{'? ' if unresolved else ''}{name} {target}: {gauge}"
            datums = definition.get("position_datums") if requirement == "position_dia" else None
            if datums:
                line += " to " + "|".join(map(_text, datums))
            method = methods.get(requirement)
            if method and method != "unknown":
                notes.append(f"op {op['op']} {name}: {self.bench(method)}")
                line += f" [note {len(notes)}]"
            rows.append(line)
        if op.get("inspection_note"):
            notes.append(f"op {op['op']}: {self.bench(op['inspection_note'])}")
            rows.append(f"see note {len(notes)}")
        return rows or ["—"]

    def speeds(self, setup, op, saw_table):
        numbers = self.records.get(("speeds_feeds", f"{setup['id']}:{op['op']}"), {})
        if op.get("do") in MANUAL:
            return "—", "—", False
        if op.get("do") in SAW_OPS:
            speed = numbers.get("blade_speed_sfm")
            feed = numbers.get("feed_mm_min")
            return (
                (_number(speed) + " sfm") if _known(speed) else "STOP: no blade speed",
                (_number(feed) + " mm/min") if _known(feed) else "STOP: no feed",
                not (_known(speed) and _known(feed)),
            )
        rpm = numbers.get("rpm")
        speed = _number(rpm, 0) + (" rpm" if saw_table else "") if _known(rpm) else "STOP"
        per_rev, per_min = numbers.get("feed_mm_rev"), numbers.get("feed_mm_min")
        if "feed_mm_rev" in numbers:
            feed = (
                [f"{per_rev:.3f}".rstrip("0").rstrip(".") + " mm/rev"]
                if _known(per_rev)
                else ["STOP"]
            )
            if _known(per_rev) and per_rev * 100 == int(per_rev * 100):
                feed = [f"{per_rev:.2f} mm/rev"]
            if _known(per_min):
                feed.append(f"({_number(per_min, 0)} mm/min)")
        else:
            feed = _number(per_min, 0) + " mm/min" if _known(per_min) else "STOP"
        return speed, feed, not (_known(rpm) and (_known(per_rev) or _known(per_min)))

    def operations(self, setup, tool_numbers):
        ops = setup.get("ops", [])
        rows, notes, inspection_notes, stops = [], [], [], {}
        saw_table = any(op.get("do") in SAW_OPS for op in ops)
        lathe = self.lathe(setup)
        op_findings = {}
        for finding in self.findings:
            subject = _field(finding, "subject", "")
            if subject.startswith(setup["id"] + ":") and _status(finding) in ("error", "warn"):
                op_findings.setdefault(subject.split(":", 1)[1], []).append(finding)
        for op in ops:
            feature = op.get("feature")
            manual = op.get("do") in MANUAL
            saw = op.get("do") in SAW_OPS
            action = [_text(op.get("do"))]
            for key, label in (
                ("rough_allowance_mm", "leave"),
                ("stock_to_leave_mm", "leave"),
                ("passes", "passes"),
                ("doc_mm", "depth of cut"),
            ):
                if key in op and not (key == "stock_to_leave_mm" and op[key] == 0):
                    value = _text(op[key]) if key == "passes" else self.operative(op[key])
                    action.append(f"{label} {value}" + ("" if key == "passes" else " mm"))
            if saw:
                plane = _mapping(op.get("cut_plane"))
                action.append(
                    f"blade centre {_text(plane.get('axis')).upper()} "
                    f"{_number(plane.get('value'))} {self.bundle.features.get('units', '?')}"
                )
            reference = op.get("tool")
            if manual and reference is None:
                tool = "—"
            elif reference in (None, "unknown"):
                tool = _Box("STOP: no tool")
                stops.setdefault("tool not selected", []).append(str(op["op"]))
            else:
                number = tool_numbers.get((reference, op.get("holder")))
                tool = (
                    f"{number} {self.tool_name(reference)}" if number else self.tool_name(reference)
                )
                if resolve(self.bundle, "tools", reference) is None:
                    tool = [tool, _Box("STOP: tool not in the shop list")]
                    stops.setdefault("tool not in the shop list", []).append(str(op["op"]))
            speed, feed, missing = self.speeds(setup, op, saw_table)
            if missing:
                stops.setdefault("no starting speed / feed", []).append(str(op["op"]))
            direction = op.get(
                "direction",
                "not_applicable"
                if manual
                or op.get("do") in {"spot", "drill", "ream", "tap", "counterbore", "countersink"}
                else None,
            )
            direction = self.direction(direction)
            if saw:
                direction = "keep " + _text(_mapping(op.get("cut_plane")).get("keep"))
            saw_numbers = self.records.get(("saw_cut", f"{setup['id']}:{op['op']}"), {})
            if saw:
                target = [
                    "retained edge " + _number(saw_numbers.get("retained_boundary_mm")) + " mm"
                ]
            else:
                target = self.tip(setup, op)
            if any(isinstance(line, _Box) and "Z target" in line for line in target):
                stops.setdefault("no Z target", []).append(str(op["op"]))
            boxes = self.crash_boxes(setup, op)
            contours = self.records.get(("coordinates", setup["id"]), {}).get("contours", [])
            if any(
                isinstance(c, dict)
                and str(c.get("op")) == str(op["op"])
                and c.get("method") == "axial_table"
                and not _known(c.get("tool_nose_compensation_mm"))
                for c in (contours if isinstance(contours, list) else [])
            ):
                boxes.append(_Box("STOP: tool-nose offset not computed — see CONTOURS"))
                stops.setdefault("tool-nose offset for the profile not computed", []).append(
                    str(op["op"])
                )
            for finding in op_findings.get(str(op["op"]), []):
                subject = _field(finding, "subject", "")
                if _status(finding) == "error":
                    text = self.plain_error(
                        _field(finding, "rule"), _field(finding, "message", "?"), subject
                    )
                    boxes.append(_Box("STOP: " + text))
                else:
                    message = str(_field(finding, "message", "?"))
                    for prefix in (subject + ":", subject.replace(":", " ") + ":"):
                        message = message.removeprefix(prefix).strip()
                    boxes.append(_Box("CAUTION: " + self.bench(message)))
            # Crash and status warnings print full width under the op so the narrow
            # action column keeps its line height.
            note = op.get("note")
            derivation = self.tip_note(setup, op)
            if note or derivation:
                notes.append(
                    f"Op {op['op']}: "
                    + " ".join(
                        filter(None, [self.bench(note, setup) if note else None, derivation])
                    )
                )
            rows.append(
                _Row(
                    (
                        _text(op["op"]),
                        action,
                        self.feature_name(feature)
                        if feature is not None
                        else "stock"
                        if saw
                        else "?",
                        tool,
                        speed,
                        feed,
                        target,
                        direction,
                        self.inspection(op, inspection_notes),
                    ),
                    boxes,
                )
            )
        headings = [
            "op",
            "do",
            "feature",
            "tool (T#)",
            "speed" if saw_table else "rpm",
            "feed",
            "cut target" if saw_table else ("Z from → to" if lathe else "Z tip"),
            "direction",
            "inspection: limit, gauge",
        ]
        tail = ""
        if notes:
            tail += "<h3>Op notes</h3>" + _list(notes, ordered=False)
        if inspection_notes:
            tail += "<h3>Inspection notes</h3>" + _list(inspection_notes)
        # The table and its notes print as one block so a page never starts on notes.
        html = (
            '<div class="keep"><h2>OPERATIONS</h2>'
            + _table(headings, rows, "operations", [4, 17, 10, 12, 6, 9, 12, 9, 21])
            + tail
            + "</div>"
        )
        return html, stops

    # -------------------------------------------------------------- contours
    def waypoints(self, setup):
        render = _mapping(_mapping(self.report.get("renders")).get(setup["id"]))
        points = _mapping(render.get("scene")).get("waypoints")
        return [_mapping(p) for p in points] if isinstance(points, list) else []

    def waypoint(self, waypoints, op, point):
        for record in waypoints:
            xy = record.get("xy", record.get("xz"))
            if (
                str(record.get("op")) == str(op)
                and isinstance(xy, list)
                and len(xy) == 2
                and all(_known(v) for v in (*xy, *point))
                and math.dist(xy, point) <= 0.01
            ):
                return str(record.get("label", ""))
        return ""

    def contours(self, setup, tools):
        """One block per contour op; both sides of a symmetric profile print explicitly."""
        numbers = self.records.get(("coordinates", setup["id"]), {})
        o = self.operative
        waypoints = self.waypoints(setup)
        operations = {str(op["op"]): op for op in setup.get("ops", [])}
        blocks = {}

        def block(op):
            return blocks.setdefault(str(op), {"parts": [], "z": set()})

        for arc in (
            numbers.get("arc_table", []) if isinstance(numbers.get("arc_table"), list) else []
        ):
            entry = block(arc.get("op"))
            rows = []
            for record in arc.get("rows", []):
                xy = record.get("setup_xy", [record.get("x"), record.get("y")])
                z = record.get("tip_z", arc.get("tip_z"))
                entry["z"].add(o(z))
                rows.append(
                    [
                        self.waypoint(waypoints, arc.get("op"), xy),
                        self.angle(record.get("angle_deg")),
                        o(xy[0]),
                        o(xy[1]),
                        o(z),
                    ]
                )
            centre = arc.get("centre_setup_xy") or ["unknown", "unknown"]
            description = (
                f"Cutter-centre arc R{o(arc.get('cutter_centre_radius_mm', arc.get('radius_mm')))} "
                f"about X {o(centre[0])}, Y {o(centre[1])}"
            )
            if _known(arc.get("step_deg")):
                description += f"; checkpoints every {_number(arc['step_deg'])}°"
            if _known(arc.get("max_chord_sagitta_mm")):
                description += f", chord error ≤ {o(arc['max_chord_sagitta_mm'])}"
            if arc.get("interpolation"):
                description += "; " + self.bench(arc["interpolation"])
            entry["parts"].append((description, ["P", "angle °", "X", "Y", "Z"], rows))
        for line in numbers.get("line_table", []):
            entry = block(line.get("op"))
            rows = []
            for xy in line.get("setup_xy", []):
                entry["z"].add(o(line.get("tip_z")))
                rows.append(
                    [
                        self.waypoint(waypoints, line.get("op"), xy),
                        "",
                        o(xy[0]),
                        o(xy[1]),
                        o(line.get("tip_z")),
                    ]
                )
            side = _text(line.get("side"))
            description = f"Straight joins on the {side} side, in cutting order"
            entry["parts"].append((description, ["P", "", "X", "Y", "Z"], rows))
        arc_ops = {str(arc.get("op")) for arc in numbers.get("arc_table", []) or []}
        for profile in numbers.get("profiles", []):
            op = str(profile.get("op"))
            if op in arc_ops and _mapping(profile.get("contour")).get("method") == "arc_table":
                continue
            points = profile.get("cutter_centre")
            entry = block(op)
            if not isinstance(points, list) or not points:
                entry.setdefault("unresolved", True)
                continue
            z = o(profile.get("to_z"))
            entry["z"].add(z)
            rows = []
            headings = ["P", "angle °", "X", "Y", "Z"]
            for point in points:
                if isinstance(point, dict):
                    xy = [point.get("x"), point.get("y")]
                    rows.append(
                        [
                            self.waypoint(waypoints, op, xy),
                            self.angle(point.get("angle_deg")),
                            o(xy[0]),
                            o(xy[1]),
                            z,
                        ]
                    )
                elif len(point) == 2 and all(isinstance(p, list) for p in point):
                    headings = ["pass", "X from", "Y from", "X to", "Y to", "Z"]
                    rows.append([str(len(rows) + 1), *(o(v) for p in point for v in p), z])
                else:
                    rows.append(
                        [self.waypoint(waypoints, op, point[:2]), "", o(point[0]), o(point[1]), z]
                    )
            entry["parts"].append(("Cutter-centre checkpoints", headings, rows))
        for contour in numbers.get("contours", []):
            if not isinstance(contour, dict) or contour.get("method") != "axial_table":
                continue
            entry = block(contour.get("op"))
            rows = [
                [
                    self.waypoint(
                        waypoints, contour.get("op"), [r.get("x_target_mm"), r.get("z_mm")]
                    ),
                    o(r.get("x_target_mm")),
                    o(r.get("z_mm")),
                ]
                for r in contour.get("rows", [])
            ]
            description = (
                f"Sphere R{o(contour.get('sphere_radius_mm'))}: "
                f"apex Z {o(contour.get('apex_z_mm'))} → base Z {o(contour.get('base_z_mm'))}, "
                f"every {o(contour.get('step_mm'))} in Z"
            )
            compensation = contour.get("tool_nose_compensation_mm")
            operation = operations.get(str(contour.get("op")), {})
            nose = _amount(
                _mapping(resolve(self.bundle, "tools", operation.get("tool"))).get("nose_radius_mm")
            )
            if _known(compensation):
                description += f"; tool-nose compensation {o(compensation)} applied"
            else:
                description += (
                    ". Finished surface, X as diameter; the table is not offset for the "
                    + (f"R{o(nose)} tool nose" if nose is not None else "tool nose")
                    + ": STOP — compensation not computed; feed to these points only with "
                    "nose-radius compensation set at the machine"
                )
            entry["parts"].append((description, ["P", "X (Ø)", "Z"], rows))
        if not blocks:
            return ""
        html = []
        for op_id in sorted(blocks, key=lambda k: (not k.isdigit(), int(k) if k.isdigit() else 0)):
            entry = blocks[op_id]
            op = operations.get(op_id, {})
            title = f"Op {op_id} — {self.feature_name(op.get('feature'))}"
            tool = tools.get(op.get("tool"))
            if tool:
                title += f" · {tool}"
            if len(entry["z"]) == 1:
                title += f" · Z {next(iter(entry['z']))}"
            if op.get("direction"):
                title += f" · {self.direction(op['direction'])}"
            content = f"<h3>{escape(title)}</h3>"
            tool_missing = op.get("tool") in (None, "unknown") or not tools.get(op.get("tool"))
            if tool_missing:
                content += _p(
                    f"STOP: {self.feature_name(op.get('feature')).upper()} — tool not selected; "
                    "do not run.",
                    "stop",
                )
            elif not entry["parts"]:
                content += _p("STOP: contour points not computed — do not run.", "stop")
            else:
                for description, headings, rows in entry["parts"]:
                    columns = [
                        i
                        for i, h in enumerate(headings)
                        if any(row[i] for row in rows) and not (h == "Z" and len(entry["z"]) == 1)
                    ]
                    content += _p(self.bench(description) + ".") + _table(
                        [headings[i] for i in columns], [[row[i] for i in columns] for row in rows]
                    )
            html.append(f'<div class="contour">{content}</div>')
        heading = (
            f"<h2>CONTOURS — {escape(self.zero_name(setup))}; "
            + ("X is diameter" if self.lathe(setup) else "cutter-centre X / Y")
            + "</h2>"
        )
        if waypoints:
            heading += _p("P numbers match the labelled points in the setup picture.")
        return heading + '<div class="contours">' + "".join(html) + "</div>"

    # ---------------------------------------------------------------- picture
    def arrival(self, setup):
        source = setup.get("stock_in")
        sources = source if isinstance(source, list) else [source]
        names = []
        for ref in sources:
            if ref == "stock":
                names.append("the stock blank")
            elif isinstance(ref, str) and ref.startswith("stock."):
                names.append(f"the {ref.removeprefix('stock.')} blank")
            elif isinstance(ref, str) and ref != "unknown":
                names.append(f"Setup {ref}")
            else:
                names.append("? unknown stock")
        if len(names) > 1:
            return "parts from " + " and ".join(names) + " joined"
        name = names[0] if names else "? unknown stock"
        return name if not name.startswith("Setup") else f"part as it arrives from {name}"

    def fixture_render(self, setup):
        render = self.report.get("renders", {}).get(setup["id"])
        if not render:
            return _p(
                "NO PICTURE — the holding is not modelled; set up from the HOLD steps above.",
                "stop",
            )
        scene = _mapping(render.get("scene"))
        fixture = self.reference(_mapping(setup.get("hold")).get("fixture"), "fixtures")
        caption = [f"Setup {setup['id']} — {self.arrival(setup)}, held in the {fixture}."]
        shows = scene.get("shows")
        caption.append(
            "Picture shows: " + ", ".join(map(str, shows)) + "."
            if isinstance(shows, list) and shows
            else "Picture shows the holding only, not the cuts."
        )
        lines = []
        for debt in scene.get("debts") or []:
            text = re.sub(r"^(?:fixture )?not drawn:\s*", "", str(debt))
            text = re.sub(
                r"(?i)^fixture pose/dimensions unmeasured or unavailable:\s*(.+)$",
                r"\1 not measured, so the holding is drawn without it",
                text,
            )
            text = self.bench(text)
            text = re.sub(r"'([^']+)' has no fixture solid model", r"\1 (no 3D model)", text)
            lines.append("NOT SHOWN: " + text)
        lines.extend(str(debt) for debt in scene.get("render_debts") or [])
        if render.get("fixture") != "modeled" and not lines:
            lines.append("NOT SHOWN: part of the holding is not modelled.")
        return (
            '<figure class="fixture-render">'
            f'<img src="{escape(render["path"], quote=True)}" '
            f'alt="Setup {escape(setup["id"], quote=True)} holding picture">'
            f"<figcaption>{escape(' '.join(caption))}"
            + "".join(f"<br><b>{escape(line)}</b>" for line in lines)
            + "</figcaption></figure>"
        )

    # ------------------------------------------------------------------- route
    def setup_findings(self, setup):
        sid = setup["id"]
        features = {op.get("feature") for op in setup["ops"]}
        result = []
        for finding in self.findings:
            subject = _field(finding, "subject", "")
            rule = _field(finding, "rule")
            numbers = _field(finding, "numbers", {})
            if subject == sid or subject.startswith(sid + ":"):
                result.append(finding)
            elif subject.split(":")[0] in features and rule != "tool_resolves":
                endpoints = numbers.get("endpoints", [])
                checks = numbers.get("checks", [])
                owners = {str(c.get("op", "")).split(":")[0] for c in checks}
                if numbers.get("op"):
                    owners.add(str(numbers["op"]).split(":")[0])
                if endpoints:
                    owners.update(e.get("setup") for e in endpoints)
                if not owners or sid in owners:
                    result.append(finding)
        return result

    def stock_line(self, stock):
        stock = _mapping(stock)
        o = self.operative
        form = stock.get("form")
        parts = []
        dims = ""
        if _known(stock.get("dia_mm")):
            dims = f"Ø{o(stock['dia_mm'])}"
        section = stock.get("section_mm")
        if isinstance(section, list) and all(_known(v) for v in section):
            dims = " × ".join(o(v) for v in section)
        if _known(stock.get("length_mm")):
            dims = (dims + " × " if dims else "") + f"{o(stock['length_mm'])} long"
        elif stock.get("length_mm") == "unknown":
            dims += " × ? length not set"
        label = _STOCK_FORMS.get(form, _text(form) if form else "stock")
        parts.append(f"{label} {dims}".strip())
        # The material itself is printed once, in the job header's material line.
        if stock.get("material") == "unknown":
            parts.append("material grade ? not set — confirm before buying or cutting")
        line = ", ".join(parts) + "."
        extras = []
        for key, value in stock.items():
            if (
                self.metadata(key)
                or key in _PLACEMENT_KEYS
                or key
                in {"form", "material", "dia_mm", "section_mm", "length_mm", "drawing_material"}
                or value in ("unknown", "not_applicable")
            ):
                continue
            if key == "on_hand":
                if value is False:
                    extras.append("Not on hand: obtain before starting.")
                continue
            if key in {"note", "prerequisite"}:
                extras.append(
                    ("Before S1: " if key == "prerequisite" else "")
                    + self.bench(value).rstrip(".")
                    + "."
                )
                continue
            name = _text(key)
            unit = " mm" if name.endswith(" mm") else ""
            name = name.removesuffix(" mm")
            shown = self.operative(value) + unit if _known(value) else self.bench(value)
            extras.append(f"{name[:1].upper() + name[1:]}: {shown}.")
        return " ".join([line, *extras])

    def stock_state(self, setup):
        state = _mapping(setup.get("stock_state"))
        o = self.operative
        parts = []
        if _known(state.get("od_mm")):
            parts.append(f"Ø{o(state['od_mm'])}")
        for key, label in (
            ("top_z", "top"),
            ("bottom_z", "bottom"),
            ("north_end_z", "north end"),
            ("south_end_z", "south end"),
            ("plain_end_z", "plain end"),
            ("retained_rail_bottom_z", "rail bottoms"),
        ):
            if key not in state:
                continue
            value = state[key]
            name = label
            if key == "top_z" and state.get("top_feature"):
                name = f"top ({self.feature_name(state['top_feature'])})"
            parts.append(f"{name} at Z {o(value)}" if _known(value) else f"{name} Z ? not set")
        line = f"Starts from: {self.arrival(setup)}"
        if parts:
            line += " — " + ", ".join(parts)
        line += "."
        if state.get("note"):
            line += " " + self.bench(state["note"], setup).rstrip(".") + "."
        return _p(line)

    def speeds_source(self):
        cites = []
        for finding in self.findings:
            if _field(finding, "rule") != "speeds_feeds":
                continue
            row = _field(finding, "numbers", {}).get("cutting_data_row")
            for cite in row if isinstance(row, list) else [row]:
                if isinstance(cite, str) and cite != "unknown" and cite not in cites:
                    cites.append(cite)
        if not cites:
            return "Speeds / feeds: no cited source — every op without a speed is a STOP."
        illustrative = any("illustrative" in c or "example" in c for c in cites)
        return (
            "Speeds / feeds are starting points, not limits (source: shop cutting-data table, "
            "RPM rounded to 50 within the machine's range"
            + ("; the table holds illustrative example values" if illustrative else "")
            + ")."
        )

    def material(self):
        spec = _mapping(self.bundle.features.get("material"))
        names = []
        for key in ("spec", "name"):
            value = spec.get(key)
            if isinstance(value, str) and value != "unknown":
                text = _sentence(value)
                if text.lower() not in (n.lower() for n in names):
                    names.append(text)
        line = "Drawing material: " + (" / ".join(names) or "? not stated") + "."
        used = _mapping(self.plan.get("stock")).get("material")
        if (
            isinstance(used, str)
            and used != "unknown"
            and used.lower() not in (n.lower() for n in names)
        ):
            line += f" We use: {_sentence(used)}."
        finish = spec.get("finish")
        if isinstance(finish, str) and finish != "unknown":
            line += f" Finish: {finish}."
        return line

    def requirements(self):
        rows = []
        for feature, definition in self.features.items():
            values = [
                "? requirement not identified"
                if d == "unknown"
                else _REQUIREMENT_NAMES.get(d, _text(d))
                + " "
                + self.band(definition.get(d), feature, d)
                for d in dict.fromkeys(tolerance_requirements(definition))
            ]
            rows.append(
                (self.feature_name(feature), "; ".join(values) or "no toleranced requirement")
            )
        thickness = _mapping(self.bundle.features.get("material")).get("thickness")
        if _known(thickness):
            rows.append(("part", f"finished thickness {self.value(thickness)}"))
        return "<h2>DRAWING REQUIREMENTS</h2>" + _table(
            ["feature", "limits"], rows, widths=[30, 70]
        )

    def drawing_revision(self):
        revision = self.plan.get("drawing", {}).get("revision", "unknown")
        return revision if isinstance(revision, str) and revision != "unknown" else None

    def header(self, setups):
        routed = {id(f) for setup in setups for f in self.setup_findings(setup)}
        stops, cautions, topics = self.status_lines(
            [f for f in self.findings if id(f) not in routed]
        )
        if not self.drawing_revision():
            stops.insert(0, "Drawing revision not confirmed — match the print revision first.")
        if self.bundle.features.get("step_sha256", "unknown") == "unknown":
            topics.append("3D model / drawing pairing")
        cautions.extend(str(w) for w in self.approval.get("warnings", []))
        html = "<h2>JOB STATUS</h2>"
        html += self.status_boxes(stops, cautions, topics) or _p(
            "No stops, cautions or unverified checks for the job as a whole."
        )
        dro = _mapping(self.plan.get("dro"))
        lines = [self.material(), self.speeds_source()]
        if dro.get("manual") or dro.get("controller") not in (None, "unknown"):
            name = dro.get("manual") if isinstance(dro.get("manual"), str) else dro["controller"]
            lines.append(
                f"DRO: {self.bench(name)}, {_text(dro.get('mode')).upper()} mode; zero with "
                "Axis Set, never Preset."
            )
        html += "".join(_p(line) for line in lines)
        html += "<h2>STOCK AND ROUTE</h2>"
        stock = _mapping(self.plan.get("stock"))
        components = stock.get("components")
        if isinstance(components, list) and components:
            html += _list(
                [f"{_text(_mapping(c).get('id'))}: " + self.stock_line(c) for c in components],
                ordered=False,
            )
            stock = {k: v for k, v in stock.items() if k != "components"}
            if any(k not in {"form", "material"} for k in stock):
                html += _p(self.stock_line(stock))
        else:
            html += _p("Stock: " + self.stock_line(stock))
        html += _table(
            ["setup", "starts from", "machine", "holding"],
            [
                (
                    s["id"],
                    self.arrival(s),
                    self.reference(s.get("machine"), "machines"),
                    "STOP: not chosen"
                    if _mapping(s.get("hold")).get("fixture", "unknown") == "unknown"
                    else self.reference(s["hold"]["fixture"], "fixtures"),
                )
                for s in setups
            ],
            widths=[8, 32, 25, 35],
        )
        html += self.requirements()
        html += _p(
            "T# = tool number in that setup's TOOLS table. EM = endmill; CD = centre drill; "
            "DTI = test indicator; mic = micrometer. Keep the drawing at the bench."
        )
        return html

    # ------------------------------------------------------------------ setup
    def setup_section(self, setup):
        self.setup = setup
        machine = self.reference(setup.get("machine"), "machines")
        kind = self.machine(setup).get("kind")
        tool_numbers, tools, tool_html = self.tool_table(setup)
        ops_html, op_stops = self.operations(setup, tool_numbers)
        stops, cautions, topics = self.status_lines(
            self.setup_findings(setup), setup, skip_ops=True
        )
        every = self.cutting_ops(setup)
        for text, ops in op_stops.items():
            label = _ops_label(ops, every)
            stops.append(f"{label[:1].upper() + label[1:]} — {text}")
        title = f"SETUP {setup['id']} — {machine}" + (f" ({_text(kind)})" if kind else "")
        blocks = [f"<h2>{escape(title)}</h2>" + self.status_boxes(stops, cautions, topics)]
        if setup.get("note"):
            blocks[0] += _p(self.bench(setup["note"], setup))
        blocks[0] += self.stock_state(setup)
        blocks.append(self.hold(setup))
        blocks.append(self.fixture_render(setup))
        deburr = setup.get("deburr_mm")
        blocks.append(
            _p(
                f"Coolant: {self.bench(setup.get('coolant'))}. Break edges "
                + (f"{self.operative(deburr)} mm max." if _known(deburr) else "? limit not set.")
            )
        )
        blocks.append(self.clearance(setup))
        blocks.append(tool_html)
        blocks.append(self.dro(setup, tools))
        blocks.append(self.feature_map(setup))
        blocks.append(ops_html)
        blocks.append(self.contours(setup, tools))
        self.setup = None
        return [block for block in blocks if block]

    def render(self):
        setups = self.plan.get("setups", [])
        sections = [("Job", [self.header(setups)])]
        sections.extend((f"Setup {s['id']}", self.setup_section(s)) for s in setups)
        drawing = self.plan.get("drawing", {})
        part = _text(self.plan.get("part"))
        revision = self.drawing_revision()
        banner = (
            "CHECKED — HASH-MATCHED FIRST ARTICLE RECORDED"
            if self.checked
            else "PLANNED — NOT APPROVED FOR THIS INPUT BUNDLE"
        )
        result = [
            f'<!DOCTYPE html>\n<html lang="en"><head><meta charset="utf-8">'
            f"<title>{escape(part)} traveler"
            f"</title><style>{_CSS}</style></head><body>"
        ]
        footer = (
            f"prechips {self.report.get('prechips_version', '?')} · report "
            f"{str(self.report.get('hash', '?'))[:8]}"
        )
        signoff = _p(
            "Sign off: __________  First article / measured results: ____________________",
            "signoff",
        )
        for _, blocks in sections:
            result.append('<section class="page">')
            result.append(
                f'<div class="meta"><h1>{escape(part.upper())} · '
                f"{escape(_text(drawing.get('number')))} · "
                + (f"rev {escape(revision)}" if revision else "REV NOT CONFIRMED")
                + f"</h1><div>qty {escape(_text(self.plan.get('quantity')))}</div></div>"
            )
            result.append(f'<div class="banner">{banner}</div>')
            result.extend(blocks[:-1])
            # The sign-off travels with the section's last block: never alone on a page.
            result.append(f'<div class="keep">{blocks[-1]}{signoff}</div>')
            result.append(_p(footer, "foot"))
            result.append("</section>")
        result.append("</body></html>\n")
        return "\n".join(result)


_METADATA = {"cite", "source", "paths", "features", "step_sha256", "inspection_methods"}


def render_traveler(bundle, findings, report, approval=None) -> str:
    """Render fresh declared/computed instructions; approval never supplies numbers."""
    return _Traveler(bundle, findings, report, approval).render()


def tool_label(bundle, reference) -> str:
    """The traveler's short shop name for a tool reference (e.g. '1.60 mm parting blade')."""
    return _Traveler(bundle, [], {}, None).tool_name(reference)
