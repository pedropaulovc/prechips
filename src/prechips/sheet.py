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

from .joint_features import JOINT_PREP_LABEL, setup_ancestry
from .model import tolerance_requirements
from .rules.coordinates import OVERSHOOT_NOTE, dro_grid, dro_z, row_id
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
from .rules.tip_endpoints import FACING, POCKETING, stock_states

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
tr, tbody { break-inside: avoid; page-break-inside: avoid; }
tr.warn td { border-top: 0; padding-left: 8pt; }
tr.warn .box { display: inline-block; margin: 0 4pt 1pt 0; }
td .box { display: block; border: 1.5px solid #000; font-weight: bold; padding: 0 2pt; \
margin-top: 1pt; }
.keep { break-inside: avoid; page-break-inside: avoid; }
.contours { columns: 3; column-gap: 8pt; }
.contour { break-inside: avoid; page-break-inside: avoid; margin-bottom: 4pt; }
.hold-row { display: flex; gap: 8pt; align-items: flex-start; }
.hold-steps { flex: 1 1 70%; min-width: 0; }
.fixture-render { margin: 4pt 0; break-inside: avoid; page-break-inside: avoid; }
.hold-row > .fixture-render, .hold-row > .stop { flex: 0 0 30%; margin: 4pt 0 0; }
.fixture-render img { display: block; width: 100%; object-fit: contain; border: 1px solid #999; }
.see { font-style: italic; }
table.operations { margin-top: 0; }
tr.continued th { height: 14pt; padding: 0 0 1pt; font-size: 9pt; background: #fff; \
border: 0; border-bottom: 1px solid #000; vertical-align: bottom; }
h2:has(+ table.operations) { position: relative; z-index: 1; height: 14pt; \
margin: 5pt 0 -14pt; background: #fff; display: flex; align-items: flex-end; }
.signoff { margin-top: 6pt; break-before: avoid; page-break-before: avoid; }
.contour-row { display: flex; gap: 8pt; align-items: flex-start; }
.contour-row > .contour { flex: 0 0 calc((100% - 16pt) / 3); min-width: 0; }
.contour-row.tall { display: block; }
.blank-side { padding-top: 4in; text-align: center; font-weight: bold; }
@media screen { body { max-width: 7.7in; margin: 12pt auto; } .page { margin-bottom: 24pt; } \
.blank-side { display: none; } }
"""
# Duplex padding, run in the browser on load and before printing. Every sheet must end
# on an even page so the next sheet starts on a front side when the whole file prints
# double-sided. The script places the page breaks itself: it measures the sheet at the
# printed width, forces a break wherever the next block would cross the page (keeping
# headings with what follows, the sign-off with the last op row, and repeating table
# headings), then adds an "intentionally blank" page after any sheet with an odd count.
# Without scripts the browser paginates the same content on its own, unpadded.
_DUPLEX_JS = """(() => {
  // Letter 11 in less .4 in margins = 979 px at 96 px/in. The sheet is measured by the
  // same engine at the printed width, so a small band covers rounding only.
  const CAP = 975;
  const MARK = "data-duplex";
  const heading = (el) => el && /^H[1-6]$/.test(el.tagName);
  function box(el) {
    const r = el.getBoundingClientRect(), s = getComputedStyle(el);
    return { top: r.top - parseFloat(s.marginTop), bottom: r.bottom + parseFloat(s.marginBottom) };
  }
  function paginate(section) {
    let pageTop = box(section).top, pages = 1;
    const fits = (bottom) => bottom - pageTop <= CAP;
    const breakAt = (el, top) => {
      el.style.breakBefore = "page";
      el.setAttribute(MARK, "");
      pageTop = top;
      pages += 1;
    };
    const headOf = (table) => (table.tHead ? table.tHead.getBoundingClientRect().height : 0);
    // Move `el` to a new page, taking a heading right above it along.
    function move(el) {
      const prev = el.previousElementSibling;
      const start = heading(prev) && box(prev).top > pageTop ? prev : el;
      if (box(start).top > pageTop) breakAt(start, box(start).top);
    }
    function table(t) {
      const bodies = [...t.tBodies];
      bodies.forEach((tb, j) => {
        const b = box(tb);
        if (fits(b.bottom)) return;
        if (j === 0) {
          move(t);
          if (fits(b.bottom)) return;
        }
        breakAt(tb, b.top - headOf(t));
      });
    }
    function walk(parent) {
      for (const el of [...parent.children]) {
        const b = box(el);
        if (fits(b.bottom)) continue;
        if (el.tagName === "TABLE") {
          table(el);
        } else if (el.classList.contains("signoff")) {
          // The sign-off never stands alone: take the last op row with it.
          const prev = el.previousElementSibling;
          const last = prev && prev.tagName === "TABLE" ? prev.tBodies[prev.tBodies.length - 1]
            : null;
          if (last) breakAt(last, box(last).top - headOf(prev));
          else move(el);
        } else if (b.bottom - b.top <= CAP) {
          move(el);
        } else if (el.children.length) {
          walk(el);
        } else {
          // One unbreakable block taller than a page: the browser splits it.
          const over = b.bottom - pageTop;
          pages += Math.floor(over / CAP);
          pageTop = b.bottom - (over % CAP);
        }
      }
    }
    walk(section);
    return pages;
  }
  function run() {
    const body = document.body, saved = body.getAttribute("style");
    try {
      document.querySelectorAll(".blank-side").forEach((el) => el.remove());
      document.querySelectorAll("[" + MARK + "]").forEach((el) => {
        el.style.breakBefore = "";
        el.removeAttribute(MARK);
      });
      // Contour blocks go in rows of three so each row is one measurable block.
      document.querySelectorAll(".contours:not([data-rows])").forEach((c) => {
        c.setAttribute("data-rows", "");
        c.style.columns = "auto";
        const blocks = [...c.children];
        for (let i = 0; i < blocks.length; i += 3) {
          const row = document.createElement("div");
          row.className = "contour-row";
          row.append(...blocks.slice(i, i + 3));
          c.append(row);
        }
      });
      // Measure at the printed width whatever the window size.
      body.style.cssText = "max-width:none;width:7.7in;margin:0";
      document.querySelectorAll(".contour-row").forEach((row) => {
        row.classList.toggle("tall", row.getBoundingClientRect().height > CAP);
      });
      for (const section of [...document.querySelectorAll("section.page[data-sheet]")]) {
        if (paginate(section) % 2 === 0) continue;
        const blank = document.createElement("section");
        blank.className = "page blank-side";
        blank.textContent =
          "This side intentionally blank \\u2014 " + section.getAttribute("data-sheet") + " back";
        section.after(blank);
      }
    } catch (error) {
      document.querySelectorAll(".blank-side").forEach((el) => el.remove());
      document.querySelectorAll("[" + MARK + "]").forEach((el) => (el.style.breakBefore = ""));
    } finally {
      if (saved === null) body.removeAttribute("style");
      else body.setAttribute("style", saved);
    }
  }
  addEventListener("load", run);
  addEventListener("beforeprint", run);
})();
"""
# Console-style status marks kept on the dividing-head index line.
_GLYPHS = {"error": "✗", "warn": "!", "unknown": "?", "unsupported": "?"}
# A planned tool path ending this close to jaws, a dead centre or the jaw tops is
# hand-feed territory: it is boxed on the op row instead of buried in clearance prose.
_CRASH_ZONE_MM = 3.0
# Plan units within which a touched datum's nominal Z is the to_z of the op that cut it.
_SAME_Z = 1e-9
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


def _supply_name(root):
    """A root supply (``stock.<component>``, ``stock`` or an unrouted setup) in shop words."""
    if root == "stock":
        return "stock blank"
    if isinstance(root, str) and root.startswith("stock."):
        return root.removeprefix("stock.")
    return f"Setup {_text(root)} material"


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


class _Plain(str):
    """A full-width line under a table row printed as plain text, not a warning box."""


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


def _table(headings, rows, css="", widths=None, continued=None):
    """``continued`` is a heading row repeated with the column headings on every page the
    table runs onto; on its first page the section heading is drawn over it."""
    columns = ""
    if widths:
        columns = (
            "<colgroup>" + "".join(f'<col style="width:{w}%">' for w in widths) + "</colgroup>"
        )
    attribute = f' class="{css}"' if css else ""
    result = [f"<table{attribute}>", columns, "<thead>"]
    if continued:
        result.append(
            f'<tr class="continued"><th colspan="{len(headings)}">{escape(continued)}</th></tr>'
        )
    result.append("<tr>")
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
                + "".join(
                    f'<span class="see">{escape(w)}</span>'
                    if isinstance(w, _Plain)
                    else _cell_line(_Box(w))
                    for w in warnings
                )
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
        # Operative features: the exported manifest plus resolved plan joint features.
        self.features = bundle.feature_definitions
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
        self.setup_stops = {}
        # Ops of the current setup with a block on its contour sheet; set by contours().
        self.contour_ops = set()

    # ------------------------------------------------------------------ numbers
    def precision(self, feature=None, dimension=None):
        overrides = self.features.get(feature, {}).get("precision", {})
        if isinstance(overrides, dict):
            return overrides.get(dimension, self.general_precision)
        return overrides

    def feature_label(self, feature, marked=True):
        """An exported feature prints its shop name; a plan joint feature is marked as joint
        preparation (unless a heading already says so). A through bore is a through-socket;
        a spigot is its component's exterior."""
        definition = self.features.get(feature, {})
        joint = _mapping(definition.get("joint"))
        if not joint:
            return self.feature_name(feature)
        if joint["kind"] == "cylinder_spigot":
            kind = "spigot exterior"
        else:
            kind = "through-socket bore" if definition.get("thru") is True else "socket bore"
        name = f"{self.feature_name(feature)} ({kind} on {_text(joint['component'])})"
        return f"{name}: {JOINT_PREP_LABEL}" if marked else name

    def joint_text(self, setup):
        """How a joint setup joins its two received branches: method, process, the declared
        fit band and, for retaining compound, surface prep and the undisturbed cure."""
        joint = _mapping(setup.get("joint"))
        if not joint:
            return ""
        text = f" Joined by {_text(joint['method'])} ({_text(joint['process'])})"
        if joint["kind"] == "cylindrical":
            band = joint.get(f"{joint['fit']}_mm")
            limits = " to ".join(map(_number, band)) if isinstance(band, list) else _text(band)
            socket = joint["socket"]
            through = _mapping(self.features.get(socket)).get("thru") is True
            text += (
                f": spigot {self.feature_name(joint['spigot'])} "
                + ("into through-socket " if through else "into socket ")
                + f"{self.feature_name(socket)}, {joint['fit']} {limits} mm diametral"
            )
        else:
            text += f" at {len(joint['interfaces'])} declared interface(s)"
        text += "."
        if joint["method"] == "retaining_compound":
            prep, cure = joint.get("surface_prep"), joint.get("cure_time_min")
            known_prep = isinstance(prep, str) and prep.strip() and prep != "unknown"
            text += (
                " Surface prep: "
                + (f"{_text(prep).rstrip('.')}." if known_prep else "? UNKNOWN (not declared).")
                + " Apply the retaining compound, assemble, then do not disturb until cured: "
                + (
                    f"cure time {_number(cure)} min."
                    if _known(cure)
                    else "cure time ? min UNKNOWN (not declared)."
                )
            )
        return text

    def joint_debt(self, setup):
        """The joint's own declared facts left unknown: the join is withheld, never assumed."""
        joint = _mapping(setup.get("joint"))
        if not joint:
            return ""
        missing = []
        if joint["kind"] == "cylindrical" and joint.get(f"{joint['fit']}_mm") == "unknown":
            missing.append(f"{joint['fit']} band")
        if joint["method"] == "retaining_compound":
            missing.extend(
                name
                for key, name in (("surface_prep", "surface prep"), ("cure_time_min", "cure time"))
                if joint.get(key) == "unknown"
            )
        if not missing:
            return ""
        return (
            f"STOP: joint facts unknown — {', '.join(missing)}. The join is not checked; "
            "do not assemble until they are declared."
        )

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

    @property
    def decimals(self):
        """The DRO decimals of the setup being written (:func:`dro_grid`): its machine's
        declared resolution, else the default grid."""
        return dro_grid(self.bundle, self.setup or {})[1]

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
        return reference_label(self.bundle, reference, category)

    def short_reference(self, reference, category=None):
        return short_reference_label(self.bundle, reference, category)

    def tool_name(self, reference):
        return tool_label(self.bundle, reference)

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
        # Computed residue (0.470333, -2.07825) prints at DRO resolution; an authored
        # value of up to four decimals (a 1.9875 pin, a 0.0254 limit) is a fact, kept as is.
        text = re.sub(
            r"(?<![\w.])(-?\d+\.\d{5,})(?![\w.])",
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
        facts = self.hold_facts(setup, hold, lathe)
        # The steps sit beside the picture; the facts table and indexing run full width.
        below = (
            _table([name for name, _ in facts], [[value for _, value in facts]]) if facts else ""
        )
        return "<h2>HOLD</h2>" + _list(steps), below + self.indexing(setup)

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
        if "rotation" in numbers:
            glyph = _GLYPHS.get(_status(finding), "")
            tentative = "Tentative — " if _status(finding) == "unknown" else ""
            return _p(
                self.bench(
                    f"Index: {glyph} {tentative}"
                    f"{self.short_reference(numbers.get('fixture'))}; continuous rotation "
                    "turned by the rotary ops; no plate landings."
                )
            )
        feature = numbers.get("feature")
        r = _number  # Dividing-head arithmetic keeps its own digits; it is not a DRO reading.
        requested = self.value(numbers.get("requested_angle_deg"), feature, "angle_deg")
        actual = self.value(numbers.get("actual_angle_deg"), feature, "angle_deg")
        glyph = _GLYPHS.get(_status(finding), "")
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
            # The needed height is the tallest op's stack, so its stickout and holder are
            # printed with it and the shown terms add up to the total.
            worst = next((s for s in numbers.get("stacks", []) if s.get("sum_mm") == need), {})
            stack = [
                ("vise / fixture", numbers.get("bed_height_mm")),
                ("risers", numbers.get("support_blocks_mm")),
                ("parallels", numbers.get("parallels_mm")),
                ("work", numbers.get("stock_height_mm")),
                ("tool stickout", worst.get("tool_projection_mm")),
                ("holder", worst.get("holder_gauge_len_mm")),
                ("tool-change room", numbers.get("insertion_mm")),
            ]
            if _known(need) and worst:
                parts = [f"{name} {o(v)}" for name, v in stack if _known(v) and v]
                lines.append(
                    f"Spindle-to-table, tallest stack (op {_text(worst.get('op'))}): "
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
            # The work top as its DRO surface, so the gap adds up with the printed Zs.
            top = self.surface_z(setup, _mapping(setup.get("stock_state")).get("top_z"))
            above = top - jaw["jaw_top_z"] if _known(top) else "unknown"
            lines.append(
                f"Jaw tops at Z {o(jaw['jaw_top_z'])}; work top {o(above)} mm above the jaws. "
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
            zs = self.path_zs(setup, op)
            if zs:
                result[str(op["op"])] = min(zs) - jaw
        return result

    def path_zs(self, setup, op):
        """The Z ends of an op's path as its op row prints them."""
        zs = [self.surface_z(setup, op[k]) for k in ("z_from", "z_to") if _known(op.get(k))]
        if _known(op.get("to_z")):
            zs.append(self.dro_to_z(setup, op))
        return [z for z in zs if _known(z)]

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
            zs = self.path_zs(setup, op)
            if isinstance(tip, list) and len(tip) == 3 and _known(tip[2]) and zs:
                gap = tip[2] - max(zs)
                if gap <= _CRASH_ZONE_MM:
                    boxes.append(_Box(f"DEAD CENTRE Z {o(tip[2])}: start clear of it"))
            return boxes
        numbers = self.records.get(("headroom", setup["id"]), {})
        cuts = _mapping(numbers.get("cut_tip_above_jaws_mm"))
        planned = cuts.get(str(op["op"]), cuts.get(op["op"]))
        if not _known(planned):
            return boxes
        # The box prints the DRO tip over the measured jaw tops; the planned tip still
        # decides the box, so rounding up never lifts a tip out of a warning.
        tip = self.dro_to_z(setup, op)
        jaw = _mapping(numbers.get("jaw_obstruction")).get("jaw_top_z")
        value = tip - jaw if _known(tip) and _known(jaw) else planned
        if min(planned, value) < 0:
            side = "BELOW" if value < 0 else "ABOVE"
            boxes.append(_Box(f"TIP {o(abs(value))} {side} JAW TOP — STOP"))
        elif planned <= _CRASH_ZONE_MM:
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
                    + ". Axis Set each axis (never Preset), then jog without touching: the "
                    "display must show 'must read'; 'if reversed' means STOP, fix the axis "
                    "direction and redo the zero."
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
            readings = {
                key: computed.get(key) for key in ("axis_set", "check_reading", "mirrored_reading")
            }
            if axis == "z" and _known(edge):
                # The touched surface as the DRO shows it; Axis Set and the jog readings
                # move with it.
                done = self.ops_done(setup, after=touch.get("after_op"))
                face = touch.get("face", touch.get("feature"))
                surface = self.datum_z(setup, face, edge, done)
                readings = {
                    key: (value + surface - edge if _known(surface) else "unknown")
                    if _known(value)
                    else value
                    for key, value in readings.items()
                }
                edge = surface
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
            expected = self.reading(readings["check_reading"], computed.get("check_expression"))
            mirrored = self.reading(
                readings["mirrored_reading"], computed.get("mirrored_expression")
            )
            jog = computed.get("jog_mm")
            jog_direction = "−" if _known(jog) and jog < 0 else "+"
            rows.append(
                (
                    axis.upper(),
                    "; ".join(contact),
                    self.reading(readings["axis_set"]),
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
            # A lathe part is tapped true in the chuck; on a mill the indicator is swept
            # in the spindle and the table is moved to centre on the feature.
            correct = "tap true to" if self.lathe(setup) else "move the table until the sweep reads"
            line += (
                # A limit is never rounded: 0.0254 printed as 0.03 would loosen it.
                f"; {correct} {_number(limit)} mm total indicator reading or less, then re-check"
                if _known(limit)
                else "; runout limit not set — ? confirm the allowed runout"
            )
            if transfer.get("reindicate_after"):
                line += (
                    f". After {_ops_label(transfer['reindicate_after'])}: re-indicate and redo X/Y"
                )
            pieces.append(_p(line + "."))
        retouches = {}
        tops = {
            str(op["op"]): after["top_from"] for op, _, after in stock_states(setup, self.features)
        }
        for record in numbers.get("retouch", []):
            # The top as the op that last faced it left it, else as the DRO shows it.
            top = self.surface_z(setup, record.get("top_z"), tops.get(str(record.get("op"))))
            paper = record.get("paper_mm")
            axis_set = top + paper if _known(top) and _known(paper) else "unknown"
            key = (o(top), o(paper), o(axis_set))
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
            pieces.append(_p(self.tool_touch(setup, touch, tools)))
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

    def tool_touch(self, setup, touch, tools):
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
            edge = touch.get("edge_mm")
            axis_set = touch.get("z_axis_set", edge)
            if _known(edge) and _known(axis_set):
                # The touched face as the DRO shows it when this tool comes in.
                done = self.ops_done(setup, before=touch.get("before_ops"))
                surface = self.datum_z(setup, z_face, edge, done)
                axis_set = axis_set + surface - edge if _known(surface) else "unknown"
            text += f"; Axis Set Z {self.reading(axis_set)}."
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
            # Each surface's Z ends as the DRO shows them, as the op rows print them.
            rows = [
                (
                    self.feature_name(feature),
                    "Ø" + self.value(entry["dia"], feature, "dia"),
                    o(self.surface_z(setup, max(entry["z"]))),
                    o(self.surface_z(setup, min(entry["z"]))),
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
            # A hole op prints its endpoint as the DRO shows it (blind_depth's dro_* values).
            entry = endpoint.get("dro_entry_z")
            parts = [f"Z {o(entry)} → {o(endpoint.get('dro_tip_z'))}"]
            if endpoint.get("exit_face", "not_applicable") != "not_applicable":
                parts.append(f"breaks through at {o(endpoint.get('dro_exit_face'))}")
                left = endpoint.get("dro_exit_mm")
                if _known(left) and left < -_SAME_Z:
                    # Rounded up, the DRO tip leaves the full diameter short of the exit.
                    parts.append(_Box("STOP: DRO tip stops short of break-through; raise exit"))
            elif _known(endpoint.get("depth_mm")):
                depth = endpoint.get("dro_depth_mm")
                parts.append(f"depth {o(depth if _known(depth) else endpoint['depth_mm'])}")
            if not _known(endpoint.get("tip_z")):
                parts[0] = f"Z {o(entry)} → depth not set"
                parts.append(_Box("STOP: drill point length unknown"))
            return parts
        parts = []
        start, end = (self.surface_z(setup, op.get(key)) for key in ("z_from", "z_to"))
        if "z_from" in op and "z_to" in op:
            parts.append(f"Z {o(start)} → {o(end)}")
        elif "to_z" in op:
            parts.append(f"Z → {o(self.dro_to_z(setup, op))}")
        if "depth_mm" in op:
            parts.append(f"depth {o(op['depth_mm'])}")
        if "exit_mm" in op:
            parts.append(f"exit {o(op['exit_mm'])}")
        if isinstance(op.get("to_z_band"), list):
            low, high = op["to_z_band"][0], op["to_z_band"][-1]
            parts.append(f"allowed {_number(low)} to {_number(high)}")
        for key, value in (("z_from", start), ("z_to", end)):
            if key in op and not ("z_from" in op and "z_to" in op):
                parts.append(f"{'from' if key == 'z_from' else 'to'} Z {o(value)}")
        if any("?" in part for part in parts):
            parts.append(_Box("STOP: Z target not set"))
        return parts or (["—"] if op.get("do") in MANUAL else [_Box("STOP: Z target not set")])

    def dro_to_z(self, setup, op):
        """The depth the DRO shows for ``op``: the ``dro_to_z`` coordinates checked (rounded
        up, never deeper than ``to_z``), the same Z its contour tables print."""
        numbers = self.records.get(("coordinates", setup["id"]), {})
        operations = numbers.get("operations") if isinstance(numbers, dict) else None
        for entry in operations if isinstance(operations, list) else []:
            if isinstance(entry, dict) and str(entry.get("op")) == str(op.get("op")):
                return entry.get("dro_to_z", "unknown")
        return dro_z(op.get("to_z", "unknown"), dro_grid(self.bundle, setup))

    def surface_z(self, setup, value, source=None):
        """One surface, one printed Z: the checked :meth:`dro_to_z` of the op ``source``
        names (``"S2 op 20 to_z"``, :func:`stock_states`), else ``value`` as the DRO shows
        any Z (``dro_z``: on the setup's grid, rounded up); an unknown stays unknown."""
        match = re.fullmatch(r"(\S+) op (\S+) to_z", source) if isinstance(source, str) else None
        if match and match[1] == setup["id"]:
            for op in setup.get("ops", []):
                if str(op.get("op")) == match[2]:
                    return self.dro_to_z(setup, op)
        return dro_z(value, dro_grid(self.bundle, setup)) if _known(value) else value

    def datum_z(self, setup, face, edge, done=0):
        """A touched Z datum at nominal ``edge`` as the DRO shows it, once ``setup``'s
        first ``done`` ops have run: the checked :meth:`dro_to_z` of the facing or pocketing
        op that last cut ``face`` (``top``: the stock top feature), here, else in an earlier
        setup of the same frame, when it cut it to ``edge``, on this setup's grid; else
        ``edge`` as any surface (:meth:`surface_z`)."""
        if face == "top":
            face = _mapping(setup.get("stock_state")).get("top_feature")
        setups = self.plan.get("setups", [])
        index = next((i for i, s in enumerate(setups) if s.get("id") == setup["id"]), 0)
        frame = setup.get("frame")
        cuts = [
            (earlier, op)
            for earlier in setups[:index]
            if frame not in (None, "unknown") and earlier.get("frame") == frame
            for op in earlier.get("ops", [])
        ] + [(setup, op) for op in setup.get("ops", [])[:done]]
        last = next(
            (
                (cut_setup, op)
                for cut_setup, op in reversed(cuts)
                if face is not None
                and op.get("feature") == face
                and op.get("do") in FACING | POCKETING
                and _known(op.get("to_z"))
            ),
            None,
        )
        if last and abs(last[1]["to_z"] - edge) <= _SAME_Z:
            return dro_z(self.dro_to_z(*last), dro_grid(self.bundle, setup))
        return self.surface_z(setup, edge)

    @staticmethod
    def ops_done(setup, after=None, before=None):
        """How many of ``setup``'s ops have run at a touch made after op ``after``, or
        before the first of ops ``before``; none when neither names one of its ops."""
        ops = [str(op.get("op")) for op in setup.get("ops", [])]
        if str(after) in ops:
            return ops.index(str(after)) + 1
        named = before if isinstance(before, list) else [before]
        return min((ops.index(str(b)) for b in named if str(b) in ops), default=0)

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
        """The tip-depth derivation belongs in the op notes, not the target cell: worked
        from the exit face the DRO shows, then the DRO tip when the grid rounds it up."""
        endpoint = self.endpoint(setup, op)
        if not endpoint or endpoint.get("exit_face", "not_applicable") == "not_applicable":
            return None
        o = self.operative
        if not _known(endpoint.get("tip_z")):
            return None
        allowance = "lead_mm" if "lead_mm" in endpoint else "point_mm"
        point, exit_mm = endpoint.get(allowance), endpoint.get("exit_mm")
        exit_face, tip = endpoint.get("dro_exit_face"), endpoint.get("dro_tip_z")
        through = f"exit face {o(exit_face)}"
        if _known(point) and point:
            through += f" − {'lead' if allowance == 'lead_mm' else 'drill point'} {o(point)}"
        values = (exit_face, point, exit_mm)
        exact = exit_face - point - exit_mm if all(_known(v) for v in values) else "unknown"
        note = f"tip Z {o(exact)} = {through} − break-through {o(exit_mm)}"
        if _known(exact) and o(tip) != o(exact):
            step = _number(dro_grid(self.bundle, setup)[0])
            note += f"; DRO tip {o(tip)}, rounded up on the {step} grid, never deeper"
        return note + "."

    def inspection(self, op, notes, sheet):
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
                notes.append(f"{self.setup['id']} op {op['op']} {name}: {self.bench(method)}")
                line += f" [{sheet} note {len(notes)}]"
            rows.append(line)
        if op.get("inspection_note"):
            notes.append(f"{self.setup['id']} op {op['op']}: {self.bench(op['inspection_note'])}")
            rows.append(f"see {sheet} note {len(notes)}")
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

    def operations(self, setup, tool_numbers, sheets):
        """The op table for the front sheet and the op/inspection notes for sheet 2.

        ``sheets`` maps "notes" and "contours" to the attached sheet numbers that carry
        them; an op row names the sheet so the front sheet never hides a note.
        """
        ops = setup.get("ops", [])
        rows, notes, inspection_notes, stops = [], [], [], {}
        where = {kind: f"{setup['id']} sheet {number}" for kind, number in sheets.items() if number}
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
                # The TOOLS table above names the tool; the op row carries its T number.
                tool = number or self.tool_name(reference)
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
                boxes.append(_Box(f"STOP: tool-nose offset not computed — see {where['contours']}"))
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
                    f"{setup['id']} op {op['op']}: "
                    + " ".join(
                        filter(None, [self.bench(note, setup) if note else None, derivation])
                    )
                )
            pointers = []
            if note or derivation:
                pointers.append(f"note on {where['notes']}")
            if str(op["op"]) in self.contour_ops:
                pointers.append(f"contour table on {where['contours']}")
            if pointers:
                boxes.append(_Plain("See " + " · ".join(pointers)))
            rows.append(
                _Row(
                    (
                        _text(op["op"]),
                        ", ".join(action),
                        self.feature_label(feature)
                        if feature is not None
                        else "stock"
                        if saw
                        else "?",
                        tool,
                        speed,
                        feed,
                        target,
                        direction,
                        self.inspection(op, inspection_notes, where["notes"]),
                    ),
                    boxes,
                )
            )
        headings = [
            "op",
            "do",
            "feature",
            "tool",
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
        # A long table runs onto the back of the front sheet; the repeated heading row
        # names it there, and on the front the OPERATIONS heading is drawn over it.
        table = "<h2>OPERATIONS</h2>" + _table(
            headings,
            rows,
            "operations",
            [4, 16, 12, 7, 6, 9, 11, 9, 26],
            continued=f"SETUP {setup['id']} — sheet 1, back: operations continued",
        )
        notes_html = (
            f'<div class="keep"><h2>OP AND INSPECTION NOTES</h2>{tail}</div>' if tail else ""
        )
        return table, notes_html, stops

    # -------------------------------------------------------------- contours
    def waypoints(self, setup):
        render = _mapping(_mapping(self.report.get("renders")).get(setup["id"]))
        points = _mapping(render.get("scene")).get("waypoints")
        return [_mapping(p) for p in points] if isinstance(points, list) else []

    def waypoint(self, waypoints, op, point, row=None):
        """A table row's picture label: the waypoint listing its row id ``row`` (an arc or
        join table row, keyed by the same printed rows as the picture), else the waypoint at
        its ``point`` (any other table)."""
        for record in waypoints:
            if str(record.get("op")) != str(op):
                continue
            if row is not None:
                if row in (record.get("rows") or []):
                    return str(record.get("label", ""))
                continue
            xy = record.get("xy", record.get("xz"))
            if (
                isinstance(xy, list)
                and len(xy) == 2
                and all(_known(v) for v in (*xy, *point))
                and math.dist(xy, point) <= 0.01
            ):
                return str(record.get("label", ""))
        return ""

    def cut_order(self, table):
        """Stage, then a cutting order only where coordinates established one."""
        stage = table.get("stage")
        text = ""
        if stage == "rough":
            allowance = table.get("allowance_mm", table.get("rough_allowance_mm"))
            text = f"; stage: rough, leaves {self.operative(allowance)} mm for finish"
        elif stage == "finish":
            text = "; stage: finish"
        order = table.get("cut_order")
        if order in ("conventional", "climb"):
            rotation = {"cw": "clockwise", "ccw": "counterclockwise"}.get(
                table.get("spindle_rotation"), "unknown"
            )
            return text + f"; rows in cutting order ({order}, {rotation} spindle)"
        if order is None:
            return text
        reason = table.get("cut_order_reason", "not established")
        return text + f"; rows NOT in an established cutting order: {reason}"

    @staticmethod
    def clip(table, markers):
        """Where the kernel clipped this table at its op's stock_removal_bounds (the cutter's
        first contact with stock outside them), and the debt of a piece no cut links."""
        clipped = list(dict.fromkeys(_text(marker) for marker in markers if marker))
        text = ""
        if clipped:
            text = "; path clipped at the cutter's " + ", ".join(clipped)
            text += " (points past it are not cut by this op)"
        fragment = table.get("fragment")
        if isinstance(fragment, list) and len(fragment) == 2:
            text += (
                f"; separate piece {fragment[0]} of {fragment[1]}, not linked by a cut: "
                "debt, the stock between the pieces is not cleared by this op"
            )
        return text

    def contours(self, setup, tools):
        """One block per contour op; both sides of a symmetric profile print explicitly."""
        numbers = self.records.get(("coordinates", setup["id"]), {})
        o = self.operative
        waypoints = self.waypoints(setup)
        operations = {str(op["op"]): op for op in setup.get("ops", [])}
        blocks = {}
        stages = {"rough": 0, "finish": 1}

        def block(op):
            return blocks.setdefault(str(op), {"parts": [], "z": set(), "stops": []})

        def order(entry, table=None):
            """Rough before finish, then the cut sequence coordinates proved, else listed."""
            if table is None:
                return (len(stages), -1, len(entry["parts"]))
            stage = stages.get(table.get("stage"), len(stages))
            sequence = table.get("sequence")
            return (stage, sequence if isinstance(sequence, int) else -1, len(entry["parts"]))

        for arc in (
            numbers.get("arc_table", []) if isinstance(numbers.get("arc_table"), list) else []
        ):
            entry = block(arc.get("op"))
            rows = []
            subject = f"{setup['id']}:{arc.get('op')}"
            for index, record in enumerate(arc.get("rows", [])):
                printed = record.get("dro_xy") or ["unknown", "unknown"]
                z = record.get("dro_tip_z", arc.get("dro_tip_z"))
                entry["z"].add(o(z))
                key = row_id(subject, "arc_table", arc, index)
                rows.append(
                    [
                        self.waypoint(waypoints, arc.get("op"), None, key),
                        self.angle(record.get("angle_deg")),
                        o(printed[0]),
                        o(printed[1]),
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
            description += self.cut_order(arc) + self.clip(
                arc, [row.get("clipped_at") for row in arc.get("rows", [])]
            )
            headings = ["P", "angle °", "X", "Y", "Z"]
            entry["parts"].append((order(entry, arc), description, headings, rows))
        for line in numbers.get("line_table", []):
            entry = block(line.get("op"))
            rows = []
            subject = f"{setup['id']}:{line.get('op')}"
            proven = self.records.get(("accessibility", subject), {})
            proven = proven.get("checkpoint_overshoot_ok") if isinstance(proven, dict) else None
            proven = set(proven) if isinstance(proven, list) else set()
            printed, flags = line.get("dro_xy") or [], line.get("overshoot") or []
            for index in range(len(line.get("setup_xy", []))):
                dro = printed[index] if index < len(printed) else ["unknown", "unknown"]
                key = row_id(subject, "line_table", line, index)
                ok = index < len(flags) and flags[index] is True and key in proven
                entry["z"].add(o(line.get("dro_tip_z")))
                rows.append(
                    [
                        self.waypoint(waypoints, line.get("op"), None, key),
                        OVERSHOOT_NOTE if ok else "",
                        o(dro[0]),
                        o(dro[1]),
                        o(line.get("dro_tip_z")),
                    ]
                )
            side = _text(line.get("side"))
            description = f"Straight joins on the {side} side" + self.cut_order(line)
            description += self.clip(line, line.get("clipped_at") or [])
            entry["parts"].append((order(entry, line), description, ["P", "", "X", "Y", "Z"], rows))
        arc_ops = {str(arc.get("op")) for arc in numbers.get("arc_table", []) or []}
        for profile in numbers.get("profiles", []):
            op = str(profile.get("op"))
            if op in arc_ops and _mapping(profile.get("contour")).get("method") == "arc_table":
                continue
            points = profile.get("cutter_centre")
            entry = block(op)
            if not isinstance(points, list) or not points:
                entry.setdefault("unresolved", True)
                if profile.get("clip_reason"):
                    entry["stops"].append(_text(profile["clip_reason"]))
                continue
            z = o(profile.get("dro_to_z", profile.get("to_z")))
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
            description = "Cutter-centre checkpoints" + self.cut_order(profile)
            entry["parts"].append((order(entry), description, headings, rows))
        for contour in numbers.get("contours", []):
            if not isinstance(contour, dict) or contour.get("method") != "axial_table":
                continue
            entry = block(contour.get("op"))
            compensation = contour.get("tool_nose_compensation_mm")
            compensated = _known(compensation)
            rows = [
                [
                    self.waypoint(
                        waypoints, contour.get("op"), [r.get("x_target_mm"), r.get("z_mm")]
                    ),
                    o(r.get("x_target_mm")),
                    o(r.get("z_mm")),
                    *((o(r.get("x_tool_mm")), o(r.get("z_tool_mm"))) if compensated else ()),
                ]
                for r in contour.get("rows", [])
            ]
            description = (
                f"Sphere R{o(contour.get('sphere_radius_mm'))}: "
                f"apex Z {o(contour.get('apex_z_mm'))} → base Z {o(contour.get('base_z_mm'))}, "
                f"every {o(contour.get('step_mm'))} in Z"
            )
            operation = operations.get(str(contour.get("op")), {})
            nose = _amount(
                _mapping(resolve(self.bundle, "tools", operation.get("tool"))).get("nose_radius_mm")
            )
            # Surface and tool X both read on the lathe DRO's X display.
            x_unit = "radius" if _mapping(self.plan.get("dro")).get("radius_mode") is True else "Ø"
            if compensated:
                description += (
                    f". Surface X ({x_unit}) / Z are the finished dome; tool X ({x_unit}) / Z "
                    f"are the DRO readings of the R{o(compensation)} nose's imaginary tip, "
                    "touched off on an outside diameter and a +Z end face; feed to the tool "
                    "columns"
                )
                headings = [
                    "P",
                    f"surface X ({x_unit})",
                    "surface Z",
                    f"tool X ({x_unit})",
                    "tool Z",
                ]
            else:
                description += (
                    f". Finished surface, X as {'radius' if x_unit == 'radius' else 'diameter'}; "
                    "the table is not offset for the "
                    + (f"R{o(nose)} tool nose" if nose is not None else "tool nose")
                    + ": STOP — compensation not computed; feed to these points only with "
                    "nose-radius compensation set at the machine"
                )
                headings = ["P", f"X ({x_unit})", "Z"]
            entry["parts"].append((order(entry), description, headings, rows))
        # The op rows on the front sheet point at these blocks.
        self.contour_ops = set(blocks)
        if not blocks:
            return ""
        html = []
        for op_id in sorted(blocks, key=lambda k: (not k.isdigit(), int(k) if k.isdigit() else 0)):
            entry = blocks[op_id]
            op = operations.get(op_id, {})
            # Each block names its setup: a contour sheet that runs onto a second page
            # still says which setup it belongs to.
            title = f"{setup['id']} op {op_id} — {self.feature_name(op.get('feature'))}"
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
                reasons = "".join(f" — {reason}" for reason in entry["stops"])
                content += _p(f"STOP: contour points not computed{reasons} — do not run.", "stop")
            else:
                for _, description, headings, rows in sorted(entry["parts"], key=lambda p: p[0]):
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
        ancestry = setup_ancestry(self.plan) if len(sources) > 1 else {}
        supplies = {ref: ancestry.get(ref, frozenset((ref,))) for ref in sources}
        # A sequential join receives one already-joined assembly plus one single component.
        assembled = len(sources) > 1 and any(len(roots) > 1 for roots in supplies.values())
        names, added = [], None
        for ref in sources:
            roots = supplies[ref]
            if assembled and len(roots) > 1:
                parts = " + ".join(sorted(_supply_name(root) for root in roots))
                names.append(f"the {parts} assembly (joined in Setup {ref})")
                continue
            if assembled:
                added = _supply_name(next(iter(roots)))
            if ref == "stock":
                names.append("the stock blank")
            elif isinstance(ref, str) and ref.startswith("stock."):
                names.append(f"the {ref.removeprefix('stock.')} blank")
            elif isinstance(ref, str) and ref != "unknown":
                names.append(f"the {added} from Setup {ref}" if assembled else f"Setup {ref}")
            else:
                names.append("? unknown stock")
        if assembled:
            return " and ".join(names) + f", joined here (adds the {added} to that assembly)"
        if len(names) > 1:
            return "parts from " + " and ".join(names) + " joined"
        name = names[0] if names else "? unknown stock"
        return name if not name.startswith("Setup") else f"part as it arrives from {name}"

    def fixture_render(self, setup, full_size_on=None):
        """The holding picture with its caption and NOT SHOWN lines.

        ``full_size_on`` names the attached sheet with the full-width copy: the front
        sheet's half-width overview is too small to read the picture's labels and key.
        """
        render = self.report.get("renders", {}).get(setup["id"])
        if not render:
            if full_size_on:
                return _p(
                    "NO PICTURE — the holding is not modelled; set up from the HOLD steps.",
                    "stop",
                )
            return ""
        scene = _mapping(render.get("scene"))
        fixture = self.reference(_mapping(setup.get("hold")).get("fixture"), "fixtures")
        caption = [f"Setup {setup['id']} — {self.arrival(setup)}, held in the {fixture}."]
        if full_size_on:
            caption = [
                f"Setup {setup['id']} overview — labels and key are readable on the "
                f"full-size picture, {full_size_on}."
            ]
        shows = scene.get("shows")
        if not full_size_on:
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
            f'<figure class="fixture-render{" overview" if full_size_on else ""}">'
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
            # Each arriving surface as the DRO shows it, as every other line prints it.
            value = self.surface_z(setup, value)
            parts.append(f"{name} at Z {o(value)}" if _known(value) else f"{name} Z ? not set")
        line = f"Starts from: {self.arrival(setup)}"
        if parts:
            line += " — " + ", ".join(parts)
        line += "." + self.joint_text(setup)
        if state.get("note"):
            line += " " + self.bench(state["note"], setup).rstrip(".") + "."
        debt = self.joint_debt(setup)
        return _p(line) + (_p(debt, "stop") if debt else "")

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
        rows, joint_prep = [], []
        for feature, definition in self.features.items():
            values = [
                "? requirement not identified"
                if d == "unknown"
                else _REQUIREMENT_NAMES.get(d, _text(d))
                + " "
                + self.band(definition.get(d), feature, d)
                for d in dict.fromkeys(tolerance_requirements(definition))
            ]
            if _mapping(definition.get("joint")):
                # Plan-authored preparation, never drawing acceptance.
                joint_prep.append(
                    (
                        self.feature_label(feature, marked=False),
                        "; ".join(values) or "No preparation requirements declared.",
                    )
                )
                continue
            rows.append(
                (self.feature_name(feature), "; ".join(values) or "no toleranced requirement")
            )
        thickness = _mapping(self.bundle.features.get("material")).get("thickness")
        if _known(thickness):
            rows.append(("part", f"finished thickness {self.value(thickness)}"))
        html = "<h2>DRAWING REQUIREMENTS</h2>" + _table(
            ["feature", "limits"], rows, widths=[30, 70]
        )
        if joint_prep:
            html += f"<h2>{escape(JOINT_PREP_LABEL)}</h2>" + _table(
                ["plan feature", "limits"], joint_prep, widths=[30, 70]
            )
        return html

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
        stopped = [sid for sid, count in self.setup_stops.items() if count]
        if stopped:
            stops.append(
                f"Setup{'s' if len(stopped) > 1 else ''} {', '.join(stopped)}: STOP items on "
                "the setup page — do not run a setup until its STOPs are cleared."
            )
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
        """One front sheet to run the setup from, then attached sheets it points to.

        Front: status, HOLD beside the picture, tools, DRO zero and the op table.
        Sheet 2: clearance, feature map, op and inspection notes. Sheet 3: contours.
        """
        self.setup = setup
        sid = setup["id"]
        machine = self.reference(setup.get("machine"), "machines")
        kind = self.machine(setup).get("kind")
        tool_numbers, tools, tool_html = self.tool_table(setup)
        contours = self.contours(setup, tools)
        sheets = {"notes": 2, "contours": 3 if contours else None}
        ops_html, notes_html, op_stops = self.operations(setup, tool_numbers, sheets)
        stops, cautions, topics = self.status_lines(
            self.setup_findings(setup), setup, skip_ops=True
        )
        every = self.cutting_ops(setup)
        for text, ops in op_stops.items():
            label = _ops_label(ops, every)
            stops.append(f"{label[:1].upper() + label[1:]} — {text}")
        count = 3 if contours else 2
        title = (
            f"SETUP {sid} — {machine}"
            + (f" ({_text(kind)})" if kind else "")
            + f" · sheet 1 of {count}"
        )
        self.setup_stops[sid] = len(stops)
        status = f"<h2>{escape(title)}</h2>" + self.status_boxes(stops, cautions, topics)
        if setup.get("note"):
            status += _p(self.bench(setup["note"], setup))
        status += self.stock_state(setup)
        steps, hold_below = self.hold(setup)
        deburr = setup.get("deburr_mm")
        coolant = _p(
            f"Coolant: {self.bench(setup.get('coolant'))}. Break edges "
            + (f"{self.operative(deburr)} mm max." if _known(deburr) else "? limit not set.")
        )
        front = [
            status,
            f'<div class="hold-row"><div class="hold-steps">{steps}</div>'
            f"{self.fixture_render(setup, f'{sid} sheet 2')}</div>{hold_below}{coolant}",
            tool_html,
            self.dro(setup, tools),
            ops_html,
        ]

        def attached(number, subject, blocks):
            heading = f"<h2>SETUP {escape(sid)} — sheet {number} of {count}: {subject}</h2>"
            return [heading + blocks[0], *blocks[1:]]

        details = [
            self.fixture_render(setup),
            self.clearance(setup),
            self.feature_map(setup),
            notes_html,
        ]
        result = [
            [block for block in front if block],
            attached(
                2, "full-size picture, clearance, feature map and notes", [b for b in details if b]
            ),
        ]
        if contours:
            result.append(attached(3, "contours", [contours]))
        self.setup = None
        return result

    def render(self):
        setups = self.plan.get("setups", [])
        # Setup pages are built first so the job status can name every stopped setup.
        sheets = [self.setup_section(s) for s in setups]
        # (label, blocks, takes sign-off): the job page and each front sheet are signed.
        pages = [("job page", [self.header(setups)], True)]
        for setup, setup_sheets in zip(setups, sheets, strict=True):
            pages.extend(
                (f"SETUP {setup['id']} sheet {index + 1}", blocks, index == 0)
                for index, blocks in enumerate(setup_sheets)
            )
        drawing = self.plan.get("drawing", {})
        part = _text(self.plan.get("part"))
        revision = self.drawing_revision()
        banner = (
            "CHECKED — HASH-MATCHED FIRST ARTICLE RECORDED"
            if self.checked
            else "PLANNED — NOT APPROVED FOR THIS INPUT BUNDLE"
        )
        # The report binding is machine-readable only: hashes stay off the paper.
        result = [
            f'<!DOCTYPE html>\n<html lang="en"><head><meta charset="utf-8">'
            f'<meta name="prechips-version" '
            f'content="{escape(_text(self.report.get("prechips_version")))}">'
            f'<meta name="prechips-report" content="{escape(_text(self.report.get("hash")))}">'
            f"<title>{escape(part)} traveler"
            f"</title><style>{_CSS}</style><script>{_DUPLEX_JS}</script></head><body>"
        ]
        signoff = _p(
            "Sign off: __________  First article / measured results: ____________________",
            "signoff",
        )
        for label, blocks, signed in pages:
            result.append(f'<section class="page" data-sheet="{escape(label)}">')
            result.append(
                f'<div class="meta"><h1>{escape(part.upper())} · '
                f"{escape(_text(drawing.get('number')))} · "
                + (f"rev {escape(revision)}" if revision else "REV NOT CONFIRMED")
                + f"</h1><div>qty {escape(_text(self.plan.get('quantity')))}</div></div>"
            )
            result.append(f'<div class="banner">{banner}</div>')
            result.extend(blocks)
            if signed:
                result.append(signoff)
            result.append("</section>")
        result.append("</body></html>\n")
        return "\n".join(result)


_METADATA = {"cite", "source", "paths", "features", "step_sha256", "inspection_methods"}


def render_traveler(bundle, findings, report, approval=None) -> str:
    """Render fresh declared/computed instructions; approval never supplies numbers."""
    return _Traveler(bundle, findings, report, approval).render()


# The shop-name helpers read only the bundle's inventory (and its units for a blade
# width), so the render host can label tools without building a traveler.
def reference_label(bundle, reference, category=None) -> str:
    """Shop name for an inventory reference; '(not in shop list)' when it does not resolve."""
    if reference in (None, "unknown", "none", "not_applicable"):
        return _text(reference)
    if not isinstance(reference, str):
        return "?"
    identity_category = category
    if category == "fixtures":
        identity_category = (
            inventory_category(bundle, reference, WORKHOLDING_CATEGORIES) or category
        )
    item = resolve(bundle, identity_category, reference)
    root, _, member = reference.partition("/")
    raw = (
        _mapping(_mapping(bundle.inventory.get(identity_category)).get(root))
        if identity_category
        else {}
    )
    if not raw:
        raw_category = inventory_category(bundle, reference, tuple(bundle.inventory))
        raw = (
            _mapping(_mapping(bundle.inventory.get(raw_category)).get(root)) if raw_category else {}
        )
    record = item or raw
    name = record.get("name", record.get("label"))
    if not name:
        if category == "machines" or root in _mapping(bundle.inventory.get("machines")):
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
            size = _amount(record.get(field))
            if size is not None:
                name = f"{size:g} {unit} {name}"
                break
    if record.get("standard"):
        name = f"{record['standard']} {name}"
    return f"{name} (not in shop list)" if item is None else str(name)


def short_reference_label(bundle, reference, category=None) -> str:
    """`reference_label` with the long tool words cut for table cells."""
    label = reference_label(bundle, reference, category)
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


def tool_label(bundle, reference) -> str:
    """The traveler's short shop name for a tool reference (e.g. '1.6 mm parting blade')."""
    item = resolve(bundle, "tools", reference)
    if not item:
        return short_reference_label(bundle, reference, "tools")
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
        return (f"{_number(width)} mm " if width else "") + "parting blade"
    return short_reference_label(bundle, reference, "tools")
