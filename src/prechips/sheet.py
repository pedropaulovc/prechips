"""Printable bench instructions from the validated bundle and fresh rule findings.

The traveler is the shop-floor copy: one setup per section, in shop language.
Operative targets print at DRO resolution; full precision, rule identities,
hashes and uncertainty records stay in report.json. Unresolved inputs are never
hidden: they print as plain STOP lines, op-row boxes or a "not verified" line.
"""

from __future__ import annotations

import functools
import math
import re
from html import escape

from .clamp_labels import clamp_labels
from .joint_features import JOINT_PREP_LABEL, setup_ancestry
from .measurements import record_trusted
from .model import reference_only, tolerance_requirements
from .rules._bench import manual_bench
from .rules.coordinates import CENTRE_OPS, OVERSHOOT_NOTE, dro_grid, dro_z, row_id
from .rules.hold_fields import align_indicator, align_travel
from .rules.inspection import go_no_go_pair
from .rules.resolution import (
    MANUAL,
    SAW_OPS,
    WORKHOLDING_CATEGORIES,
    coating_process,
    drawing_precision,
    inventory_category,
    length_mm,
    op_feature,
    op_features,
    printed_band,
    resolve,
    saw_setup,
    selected_references,
    setup_frame,
    workholding_category,
)
from .rules.resolution import record as _mapping
from .rules.tip_endpoints import FACING, SAME_Z, operative_z, stock_states
from .rules.zero_recipe import DIRECTIONS as _SIGNS
from .rules.zero_recipe import FACE_Z_TOL_MM

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
ol.steps { list-style: decimal; } .field, .reading { white-space: nowrap; } \
.calc { margin: 1pt 0; font-weight: bold; } table.readings td { height: 16pt; }
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
.contours.wide { columns: auto; }
.contour { break-inside: avoid; page-break-inside: avoid; margin-bottom: 4pt; }
.contour.wide { column-span: all; }
h4 { font-size: 8pt; margin: 3pt 0 1pt; break-after: avoid; page-break-after: avoid; }
.stages { display: flex; gap: 8pt; align-items: flex-start; }
.stages > div { flex: 1 1 0; min-width: 0; }
table.coords { table-layout: auto; }
table.coords th { overflow-wrap: normal; }
table.coords td.num { white-space: nowrap; overflow-wrap: normal; }
.tick { display: inline-block; width: 7pt; height: 7pt; border: 1px solid #000; \
margin: 0 2pt -1pt 6pt; } .levels .tick:first-child { margin-left: 2pt; }
th.read, td.read { font-weight: bold; } th.read { background: #ccc; }
tr.repeat th { background: #fff; font-weight: bold; }
.paged table:not([data-duplex-split]) tr.repeat { display: none; }
.hold-row { display: flex; gap: 8pt; align-items: flex-start; }
.hold-steps { flex: 1 1 70%; min-width: 0; }
.fixture-render { margin: 4pt 0; break-inside: avoid; page-break-inside: avoid; }
.hold-row > .stop { flex: 0 0 30%; margin: 4pt 0 0; }
.fixture-render img { display: block; width: auto; max-width: 100%; max-height: 8.9in; \
margin: 0 auto; border: 1px solid #999; }
.see { font-style: italic; }
.op-note { margin: 1pt 0; }
.cont-head { font-size: 9pt; font-weight: bold; margin: 0 0 2pt; border-bottom: 1px solid #000; }
.more { margin: 2pt 0 0; text-align: right; font-weight: bold; }
table.operations { margin-top: 0; }
tr.continued th { height: 14pt; padding: 0 0 1pt; font-size: 9pt; background: #fff; \
border: 0; border-bottom: 1px solid #000; vertical-align: bottom; }
h2:has(+ table.operations) { position: relative; z-index: 1; height: 14pt; \
margin: 5pt 0 -14pt; background: #fff; display: flex; align-items: flex-end; }
.paged tr.continued { display: none; }
.paged h2:has(+ table.operations) { position: static; height: auto; margin: 5pt 0 2pt; \
display: block; }
.signoff { margin-top: 6pt; break-before: avoid; page-break-before: avoid; }
.contour-row { display: flex; gap: 8pt; align-items: flex-start; }
.contour-row > .contour { flex: 0 0 calc((100% - 16pt) / 3); min-width: 0; }
.contour-row > .contour.wide { flex: 1 1 100%; }
.contour-row.tall, [data-duplex-stacked] { display: block; }
.contours.wide .contour-row { display: block; }
.blank-side { padding-top: 4in; text-align: center; font-weight: bold; }
@media screen { body { max-width: 7.7in; margin: 12pt auto; } .page { margin-bottom: 24pt; } \
.blank-side { display: none; } }
"""
# Duplex padding, run in the browser on load and before printing. Every sheet must end
# on an even page so the next sheet starts on a front side when the whole file prints
# double-sided. The script places the page breaks itself: it measures the sheet at the
# printed width and starts a new page wherever the next block would cross it, keeping
# headings (and a table's caption) with what follows, the sign-off with the last op row.
# A table that runs over is split into a copy with the same column headings; an op table
# says on its page which op it continues with. Every page after a sheet's first opens
# with the sheet's name and its page number. An odd count gets an "intentionally blank"
# page. Without scripts the browser paginates the same content on its own, unpadded.
_DUPLEX_JS = """(() => {
  // Letter 11 in less .4 in margins = 979 px at 96 px/in. The sheet is measured by the
  // same engine at the printed width, so a small band covers rounding only.
  const CAP = 975;
  // The fewest table rows a page break leaves on either side of it.
  const KEEP = 3;
  const ADDED = "data-duplex";
  const SPLIT = "data-duplex-split";
  const STACKED = "data-duplex-stacked";
  const heading = (el) => el && /^H[1-6]$/.test(el.tagName);
  function box(el) {
    const r = el.getBoundingClientRect(), s = getComputedStyle(el);
    return { top: r.top - parseFloat(s.marginTop), bottom: r.bottom + parseFloat(s.marginBottom) };
  }
  function paginate(section) {
    const title = section.getAttribute("data-title") || section.getAttribute("data-sheet");
    let pageTop = box(section).top, pages = 1;
    let pageStart = [...section.children].find(
      (el) => !el.classList.contains("meta") && !el.classList.contains("banner")
    );
    const fits = (bottom) => bottom - pageTop <= CAP;
    function breakAt(el) {
      pages += 1;
      const head = document.createElement("p");
      head.className = "cont-head";
      head.setAttribute(ADDED, "");
      head.textContent = title + " (continued) \\u00b7 page " + pages;
      el.before(head);
      head.style.breakBefore = "page";
      pageTop = box(head).top;
      pageStart = el;
    }
    // What must start a page with `el`: the headings (and a table's caption) right above
    // it, a heading's lead-in line, and, when `el` opens its parent, what must start a
    // page with the parent.
    function lead(el) {
      let start = el;
      for (;;) {
        const prev = start.previousElementSibling;
        const caption = prev && prev.tagName === "P" && start.tagName === "TABLE";
        if (heading(prev) || caption || (prev && prev.classList.contains("lead-in"))) {
          start = prev;
        } else if (!prev && start.parentElement !== section) {
          start = start.parentElement;
        } else {
          return start;
        }
      }
    }
    // Start a new page at `el` with its lead; false when that gains nothing because the
    // lead already opens this page. An op table moved whole leaves a pointer where it
    // would have started, so the page it leaves says where the operations went.
    function move(el) {
      const start = lead(el);
      if (start === pageStart || start.contains(pageStart) || box(start).top <= pageTop) {
        return false;
      }
      let more = null;
      if (el.tagName === "TABLE" && el.classList.contains("operations") && el.tBodies.length) {
        more = document.createElement("p");
        more.className = "more";
        more.setAttribute(ADDED, "");
        start.before(more);
        const op = el.tBodies[0].rows[0].cells[0].textContent;
        more.textContent = "Operations continue on reverse, op " + op;
        if (!fits(box(more).bottom)) {
          more.remove();
          more = null;
        }
      }
      breakAt(start);
      if (more && pages % 2 === 1) {
        more.textContent = more.textContent.replace("on reverse", "on the next sheet");
      }
      return true;
    }
    // Rows from body `j` on go to a copy of `t` that starts the next page.
    function cut(t, j) {
      const rest = t.cloneNode(false);
      rest.setAttribute(SPLIT, "");
      for (const part of [...t.children]) {
        if (part.tagName !== "COLGROUP" && part.tagName !== "THEAD") continue;
        const copy = part.cloneNode(true);
        copy.querySelectorAll("tr.continued").forEach((row) => row.remove());
        rest.append(copy);
      }
      rest.append(...[...t.tBodies].slice(j));
      t.after(rest);
      let more = null;
      const pointer = (side) => {
        const op = rest.tBodies[0].rows[0].cells[0].textContent;
        more.textContent = "Operations continue " + side + ", op " + op;
      };
      if (t.classList.contains("operations")) {
        more = document.createElement("p");
        more.className = "more";
        more.setAttribute(ADDED, "");
        t.after(more);
        pointer("on reverse");
        while (t.tBodies.length > 1 && !fits(box(more).bottom)) {
          rest.insertBefore(t.tBodies[t.tBodies.length - 1], rest.tBodies[0]);
          pointer("on reverse");
        }
        if (!fits(box(more).bottom)) {
          // One row and the pointer overflow: undo the split and start the table, with
          // its heading, on the next page; at a page top already, drop the pointer.
          t.append(...[...rest.tBodies]);
          rest.remove();
          more.remove();
          if (move(t)) {
            table(t);
            return;
          }
          t.after(rest);
          rest.append(...[...t.tBodies].slice(1));
          more = null;
        }
      }
      breakAt(rest);
      if (more) pointer(pages % 2 === 0 ? "on reverse" : "on the next sheet");
      table(rest);
    }
    function table(t) {
      const over = () => [...t.tBodies].findIndex((tb) => !fits(box(tb).bottom));
      let j = over();
      if (j === 0 && move(t)) j = over();
      // A first row taller than the page stays with the table head: the browser splits it.
      if (j === 0) j = 1;
      const n = t.tBodies.length;
      // Widow and orphan control: a split leaves at least KEEP rows on each page. Rows
      // carry over to the next page; a table too short for KEEP on both sides moves
      // whole with its heading (where moving gains a page top).
      if (j > 0 && j < n && (j < KEEP || n - j < KEEP)) {
        if (j >= KEEP && n - KEEP >= KEEP) {
          j = n - KEEP;
        } else if (move(t)) {
          j = over();
          if (j === 0) j = 1;
          if (j > 0 && j < n && n - j < KEEP && n - KEEP >= KEEP) j = n - KEEP;
        }
      }
      if (j > 0 && j < n) cut(t, j);
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
          if (prev && prev.tagName === "TABLE" && prev.tBodies.length > 1) {
            cut(prev, prev.tBodies.length - 1);
          } else {
            move(el);
          }
        } else if (b.bottom - b.top <= CAP && move(el) && fits(box(el).bottom)) {
          continue;
        } else if (el.children.length) {
          // Too tall to move whole: break inside it. Blocks standing side by side (a
          // flex row: contour blocks, rough and finish stages) stack first, so the walk
          // meets them one below another, each measured from where the last one ends.
          const s = getComputedStyle(el);
          if (s.display.endsWith("flex") && !s.flexDirection.startsWith("column")) {
            el.setAttribute(STACKED, "");
          }
          walk(el);
        } else {
          // One unbreakable block taller than a page: the browser splits it.
          const c = box(el), over = c.bottom - pageTop;
          pages += Math.floor(over / CAP);
          pageTop = c.bottom - (over % CAP);
        }
      }
    }
    walk(section);
    section.querySelectorAll(".cont-head").forEach((head) => {
      head.textContent += " of " + pages;
    });
    return pages;
  }
  function reset() {
    document.querySelectorAll(".blank-side, [" + ADDED + "]").forEach((el) => el.remove());
    document.querySelectorAll("[" + STACKED + "]").forEach((el) => el.removeAttribute(STACKED));
    // Re-join split tables, last piece first.
    [...document.querySelectorAll("table[" + SPLIT + "]")].reverse().forEach((rest) => {
      rest.previousElementSibling.append(...[...rest.tBodies]);
      rest.remove();
    });
  }
  function run() {
    const body = document.body, saved = body.getAttribute("style");
    try {
      reset();
      // The script heads every page itself: the no-script repeated op heading goes.
      document.documentElement.classList.add("paged");
      // Contour blocks go in rows of three so each row is one measurable block; a wide
      // block (a lathe profile) takes a row of its own.
      document.querySelectorAll(".contours:not([data-rows])").forEach((c) => {
        c.setAttribute("data-rows", "");
        c.style.columns = "auto";
        let row = null;
        for (const block of [...c.children]) {
          const wide = block.classList.contains("wide");
          if (!row || wide || row.children.length === 3 || row.classList.contains("solo")) {
            row = document.createElement("div");
            row.className = wide ? "contour-row solo" : "contour-row";
            c.append(row);
          }
          row.append(block);
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
      reset();
      document.documentElement.classList.remove("paged");
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
# A cutter counts as wholly outside the kernel's setup-entry stock box only past it by
# this much: the kernel's as-is face tolerance (its STOCK_TOL), so box rounding never
# turns a grazing cutter into one in air.
_STOCK_BOX_TOL_MM = 1e-3
# One printed coordinate, e.g. "-155.000": a cell that must never wrap. Whole numbers
# (op and pass numbers) are short and keep their plain cells.
_NUMBER = re.compile(r"[-−+]?\d+\.\d+")
# The job page's abbreviation key: (printed form, meaning); a key prints only when used.
_ABBREVIATIONS = (
    (r"\bT\d+\b", "T# = tool number in that setup's TOOLS table."),
    (r"\bEM\b", "EM = endmill."),
    (r"\bCD\b", "CD = centre drill."),
    (r"\bDTI\b", "DTI = test indicator."),
    (r"\bmic\b", "mic = micrometer."),
)
PROCESS_HOLDS_LABEL = "PROCESS HOLDS — in-process limits, not drawing limits"
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
    "centre_support": "tailstock centre",
    "prepared_blank": "squared blank size",
    "order": "op order",
    "op_chain": "op sequence",
    "construction": "construction",
    "engagement": "cutter engagement",
    "saw_cut": "saw cut",
}
_DIRECTIONS = {
    "radially_inward": "face from OD to centre",
    "radially_outward": "face outward from the inner corner to the OD",
    "toward_chuck": "toward chuck",
    "toward_shoulder": "toward shoulder",
    "plunge_radial": "plunge straight in",
    "apex_to_base": "apex to base",
    "conventional": "conventional",
    "climb": "climb",
}
# A DRO axis' positive sense (``zero_recipe.DIRECTIONS`` sign class) in each machine's words.
_MILL_SENSE = {
    ("x", "+"): "tool moves right relative to the work (table moves left)",
    ("y", "+"): "tool moves away from you relative to the work (table moves toward you)",
    ("z", "+"): "tool moves up",
}
_LATHE_SENSE = {
    ("x", "+"): "away from the spindle axis",
    ("z", "+"): "toward the exposed end, away from the chuck",
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
    "measure_then_set": "touch it, then set from the measured M",
    "edge_then_set": (
        "spindle stopped; bring this tool's Z-cutting edge to it, "
        "withdraw along X without moving Z, then set"
    ),
}
# The grooving/parting blade corner a Z touch sets (zero_check ``reference_corner``).
_CORNERS = {"chuck_side": "chuck-side", "tailstock_side": "tailstock-side"}
_STOCK_FORMS = {
    "round_bar": "round bar",
    "flat_bar": "flat bar",
    "rectangular_blank": "rectangular blank",
    "prepared_blank": "prepared blank",
}
# Stock / stock-state keys that place solids for the kernel; not bench instructions.
_PLACEMENT_KEYS = {"origin_mm", "axis", "section_axis", "as_is_faces", "id", "components"}
# A ``hold.clamps`` label's role word in the HOLD text (see clamp_labels).
_CLAMP_ROLES = {"C": "clamp", "LOC": "locator", "SUP": "support"}
# Machine kinds whose top a shop-made fixture's base stands on, in shop words.
_FIXTURE_SURFACES = {"mill": "table", "drill_press": "table", "bench": "bench"}
# Ops a tool cuts along its own axis: no feed direction; on a lathe, a tailstock tool
# whose cutting hand (right- or left-hand cut) decides the spindle's turn.
_AXIAL_OPS = {"spot", "center_drill", "drill", "ream", "tap", "counterbore", "countersink"}
# A lathe spindle's turn as its switch names it, and what the operator sees.
_SPINDLE_TURNS = {
    "FORWARD": "the top of the work turns toward you",
    "REVERSE": "the top of the work turns away from you",
}


def _pose_axes(pose):
    """(origin, x, y, z) of a declared orthonormal fixture pose (y = z × x), else None."""
    pose = _mapping(pose)
    vectors = [pose.get(key) for key in ("origin_mm", "x", "z")]
    if not all(isinstance(v, list) and len(v) == 3 and all(_known(c) for c in v) for v in vectors):
        return None
    origin, x, z = vectors
    if (
        abs(math.hypot(*x) - 1) > 1e-6
        or abs(math.hypot(*z) - 1) > 1e-6
        or abs(sum(a * b for a, b in zip(x, z, strict=True))) > 1e-6
    ):
        return None
    y = [z[1] * x[2] - z[2] * x[1], z[2] * x[0] - z[0] * x[2], z[0] * x[1] - z[1] * x[0]]
    return origin, x, y, z


def _place(axes, point, translate=True):
    """A fixture-local point (or, untranslated, a direction) in the setup frame."""
    origin, x, y, z = axes
    return [
        (origin[i] if translate else 0.0) + point[0] * x[i] + point[1] * y[i] + point[2] * z[i]
        for i in range(3)
    ]


def _setup_axis(direction):
    """``(index, sign)`` of the setup axis a unit direction lies along, else None."""
    for index, component in enumerate(direction):
        if abs(abs(component) - 1) <= 1e-6:
            return index, 1 if component > 0 else -1
    return None


def _solid_extents(solid, axes):
    """Setup-frame (low, high) corners of a box solid, or a cylinder's (start, end) axis
    points; None for a malformed primitive."""
    at = solid.get("at_mm")
    if not (isinstance(at, list) and len(at) == 3 and all(_known(v) for v in at)):
        return None
    if solid.get("shape") == "box":
        size = solid.get("size_mm")
        if not (isinstance(size, list) and len(size) == 3 and all(_known(v) for v in size)):
            return None
        corners = [
            _place(axes, [at[i] + (size[i] if (corner >> i) & 1 else 0.0) for i in range(3)])
            for corner in range(8)
        ]
        return (
            [min(c[i] for c in corners) for i in range(3)],
            [max(c[i] for c in corners) for i in range(3)],
        )
    if solid.get("shape") == "cylinder":
        axis, length = solid.get("axis"), solid.get("length_mm")
        if not (isinstance(axis, list) and len(axis) == 3 and all(_known(v) for v in axis)):
            return None
        if not _known(length):
            return None
        start = _place(axes, at)
        direction = _place(axes, axis, translate=False)
        return start, [start[i] + direction[i] * length for i in range(3)]
    return None


def _solid_name(name):
    """A solid's slug in words; short side codes (``r1``, ``ll``) print as capitals."""
    words = re.split(r"[-_\s]+", str(name).strip())
    return " ".join(
        w.upper() if len(w) <= 2 or re.fullmatch(r"[a-z]\d+", w) else w for w in words if w
    )


def _name_group(names):
    """``(stem, tags)``: names differing in exactly one word ("pad R1" / "pad L1", "left
    front nut" / "right front nut") share the stem ("pad") and are tagged by that word;
    otherwise the stem is None and each name is its own tag."""
    words = [name.split() for name in names]
    if len(names) > 1 and len({len(w) for w in words}) == 1 and len(words[0]) > 1:
        varying = [i for i in range(len(words[0])) if len({w[i] for w in words}) > 1]
        if len(varying) == 1:
            stem = " ".join(w for i, w in enumerate(words[0]) if i != varying[0])
            return stem, [w[varying[0]] for w in words]
    return None, list(names)


def _supply(solid):
    """A fixture primitive is ``made`` with its fixture unless declared ``bought``
    (hardware) or ``existing`` (already in the shop, such as a machine's vise jaw)."""
    return solid.get("supply", "made")


def _make_notes(notes):
    """``upper button, lower button: O1, hardened; stud: drill rod`` from ``{note:
    [component, ...]}``: rows sharing one make note are named together before it."""
    return "; ".join(f"{', '.join(components)}: {note}" for note, components in notes.items())


# A shop-made fixture value authored as an example: the job page explains the mark once.
EXAMPLE_MARK = "†"
EXAMPLE_LEGEND = (
    f"{EXAMPLE_MARK} example fixture dimensions (plausible, not measured): confirm before making."
)


def _example(record):
    """A primitive or length whose own measurement is labelled as an example value."""
    by = _mapping(_mapping(record).get("measured")).get("by", "")
    return isinstance(by, str) and by.startswith("example")


def _void_parents(void, solids, made):
    """``(parents, unresolved)``: the solids a hole is cut in (made, or existing parts
    machined here), as the kernel cuts it: every such solid its ``cuts`` names, else
    every such solid it overlaps; ``unresolved`` are those an oblique hole may cross,
    which only ``cuts`` can settle. A hole cut only in bought hardware (a nut's thread)
    has no parent and is not listed."""
    cuts = void.get("cuts")
    if isinstance(cuts, list) and cuts:
        named = {solid.get("name"): solid for solid in solids}
        return [named[n] for n in dict.fromkeys(cuts) if n in named and named[n] in made], []
    meets = [(solid, _meet(void, solid, contact=False)) for solid in made]
    return [s for s, m in meets if m is True], [s for s, m in meets if m is None]


def _primitive(solid):
    """``("box", low, high)`` or ``("cylinder", start, unit axis, length, radius)`` in
    the owner frame; None for a malformed primitive."""
    at = solid.get("at_mm")
    if not (isinstance(at, list) and len(at) == 3 and all(_known(v) for v in at)):
        return None
    size, axis = solid.get("size_mm"), solid.get("axis")
    if solid.get("shape") == "box" and isinstance(size, list) and len(size) == 3:
        if not all(_known(v) for v in size):
            return None
        far = [at[i] + size[i] for i in range(3)]
        return "box", [min(at[i], far[i]) for i in range(3)], [max(at[i], far[i]) for i in range(3)]
    dia, length = solid.get("dia_mm"), solid.get("length_mm")
    if solid.get("shape") == "cylinder" and isinstance(axis, list) and len(axis) == 3:
        norm = math.hypot(*axis) if all(_known(v) for v in axis) else 0.0
        if not (_known(dia) and _known(length) and dia > 0 and length > 0 and norm > 0):
            return None
        return "cylinder", list(at), [v / norm for v in axis], length, dia / 2
    return None


def _overlap(low_a, high_a, low_b, high_b, contact):
    """Whether two intervals share a length (or, for ``contact``, at least a point)."""
    if contact:
        return low_a <= high_b + 1e-6 and low_b <= high_a + 1e-6
    return low_a < high_b - 1e-6 and low_b < high_a - 1e-6


def _meet(a, b, contact):
    """Whether two box/cylinder primitives share volume (``contact``: touch or share
    volume). Decided exactly for boxes, parallel cylinders and axis-aligned cylinders
    against boxes, and for any pair whose bounding boxes are apart; otherwise None."""
    pa, pb = _primitive(a), _primitive(b)
    if pa is None or pb is None:
        return False
    if pa[0] == "cylinder" and pb[0] == "box":
        pa, pb = pb, pa
    if pa[0] == "box" and pb[0] == "box":
        return all(_overlap(pa[1][k], pa[2][k], pb[1][k], pb[2][k], contact) for k in range(3))
    edge = (lambda d, r: d <= r + 1e-6) if contact else (lambda d, r: d < r - 1e-6)
    if pa[0] == "box":
        _, low, high = pa
        _, start, axis, length, radius = pb
        k = next((k for k in range(3) if abs(abs(axis[k]) - 1) <= 1e-9), None)
        if k is not None:
            ends = sorted((start[k], start[k] + axis[k] * length))
            off = [max(low[i] - start[i], 0, start[i] - high[i]) for i in range(3) if i != k]
            return _overlap(low[k], high[k], *ends, contact) and edge(math.hypot(*off), radius)
    else:
        _, start_a, axis_a, length_a, radius_a = pa
        _, start_b, axis_b, length_b, radius_b = pb
        dot = sum(axis_a[i] * axis_b[i] for i in range(3))
        if abs(abs(dot) - 1) <= 1e-9:
            rel = [start_b[i] - start_a[i] for i in range(3)]
            along = sum(rel[i] * axis_a[i] for i in range(3))
            ends = sorted((along, along + dot * length_b))
            radial = math.dist(rel, [along * axis_a[i] for i in range(3)])
            return _overlap(0, length_a, *ends, contact) and edge(radial, radius_a + radius_b)
    box_a, box_b = _bounds(pa), _bounds(pb)
    if not all(
        _overlap(box_a[0][k], box_a[1][k], box_b[0][k], box_b[1][k], True) for k in range(3)
    ):
        return False
    return None


def _bounds(primitive):
    """Owner-frame ``(low, high)`` box enclosing a :func:`_primitive`."""
    if primitive[0] == "box":
        return primitive[1], primitive[2]
    _, start, axis, length, radius = primitive
    end = [start[k] + axis[k] * length for k in range(3)]
    pad = [radius * math.sqrt(max(0.0, 1 - axis[k] ** 2)) for k in range(3)]
    return (
        [min(start[k], end[k]) - pad[k] for k in range(3)],
        [max(start[k], end[k]) + pad[k] for k in range(3)],
    )


def _touching_groups(solids):
    """How many connected sets the solids form, joining primitives that touch or share
    volume (a screw's head on its shank); separate or malformed primitives stay apart."""
    parent = list(range(len(solids)))

    def root(i):
        while parent[i] != i:
            i = parent[i]
        return i

    for i, a in enumerate(solids):
        for j in range(i):
            if _meet(a, solids[j], contact=True) is True:
                parent[root(i)] = root(j)
    return len({root(i) for i in range(len(solids))})


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
    # A run of three or more underscores is a reading blank to write in; one is an id joint.
    return re.sub(r"_{3,}|_", lambda m: m[0] if len(m[0]) > 2 else " ", str(value))


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


def _leftover(arc):
    """Where a manual-arc rough's leftover stock goes: a later rough, else the file."""
    left = _number(arc.get("stock_left_mm"), 3)
    recut = arc.get("recut_by")
    if isinstance(recut, str) and recut:
        return f"leaving at most {left} mm for {recut}"
    return f"leaving at most {left} mm for the file (cap {_number(arc.get('stock_cap_mm'))} mm)"


def _places(value):
    """The fewest decimals (0–6) that print ``value`` exactly."""
    return next((d for d in range(7) if abs(round(value, d) - value) < 1e-9), 6)


def _limits(value):
    """A declared ``[least, greatest]`` pair as ``19.99–20``, else None."""
    if isinstance(value, list) and len(value) == 2 and all(map(_known, value)):
        return "–".join(_number(v) for v in value)
    return None


def _buttons_text(guide, bore, proven):
    """Filing buttons on the traveler: every stack element's receipt limits, then the
    radius they file worst case (rounded outward to 0.001, so printing never narrows it),
    which reads as an established result only when the rule ``proven`` it inside the
    drawing band; else a STOP naming the unknown elements."""
    runout = guide.get("button_runout_mm")
    stack = [
        ("button OD", "buttons Ø{} mm", _limits(guide.get("button_dia_mm"))),
        ("button bore", "bored Ø{} mm", _limits(guide.get("button_bore_mm"))),
        ("button runout", "OD runout {} mm TIR", _number(runout) if _known(runout) else None),
        ("pin", "on a Ø{} mm pin", _limits(guide.get("pin_dia_mm"))),
        (bore, f"through {bore} Ø{{}} mm", _limits(guide.get("bore_dia_mm"))),
    ]
    text = ", ".join(form.format(value) for _, form, value in stack if value is not None)
    reach = guide.get("files_to_mm")
    missing = [name for name, _, value in stack if value is None]
    if missing or _limits(reach) is None:
        unknown = f"{', '.join(missing)} limits unknown; " if missing else ""
        return f"{text}; STOP: {unknown}worst-case filing radius not established"
    low = math.floor(round(reach[0] * 1000, 6)) / 1000
    high = math.ceil(round(reach[1] * 1000, 6)) / 1000
    if not proven:
        return f"{text}; not proven: worst case they would file R{low:.3f} to R{high:.3f} mm"
    return f"{text}; worst case they file R{low:.3f} to R{high:.3f} mm"


def _angle(value):
    """A dividing-head angle: four decimals, or two significant digits below 0.001°."""
    small = value and abs(value) < 1e-3
    return _number(value, 1 - math.floor(math.log10(abs(value))) if small else 4)


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


# Every lathe X reading is a radius or a diameter: unread, each number is half or twice
# the cut on the other display, so none prints.
_X_DISPLAY_STOP = "STOP: X display not set (dro.radius_mode): X reads radius or diameter"


class _Plain(str):
    """A full-width line under a table row printed as plain text, not a warning box."""


class _Note(str):
    """An op's own note, printed on its own line directly under the op's row."""


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


def _table(headings, rows, css="", widths=None, continued=None, repeat=None, strong=()):
    """``continued`` is a heading row repeated with the column headings on every page the
    table runs onto; on its first page the section heading is drawn over it. ``repeat``
    is a heading row printed only on the pages the table continues onto (its block's own
    heading names the first). ``strong`` columns are the ones the operator reads from;
    a cell holding one number never wraps."""
    columns = ""
    if widths:
        columns = (
            "<colgroup>" + "".join(f'<col style="width:{w}%">' for w in widths) + "</colgroup>"
        )
    attribute = f' class="{css}"' if css else ""
    result = [f"<table{attribute}>", columns, "<thead>"]
    for kind, title in (("continued", continued), ("repeat", repeat)):
        if title:
            result.append(
                f'<tr class="{kind}"><th colspan="{len(headings)}">{escape(title)}</th></tr>'
            )
    result.append("<tr>")
    result.extend(
        f'<th class="read">{escape(h)}</th>' if i in strong else f"<th>{escape(h)}</th>"
        for i, h in enumerate(headings)
    )
    result.append("</tr></thead>")
    for row in rows:
        # A row may carry full-width warning lines printed directly beneath it.
        warnings = list(row.warnings) if isinstance(row, _Row) else []
        result.append('<tbody class="op"><tr>' if warnings else "<tbody><tr>")
        for index, cell in enumerate(row):
            lines = cell if isinstance(cell, (list, tuple)) else [cell]
            parts = []
            for line in lines:
                if parts and not isinstance(line, _Box):
                    parts.append("<br>")
                parts.append(_cell_line(line))
            names = ["read"] if index in strong else []
            if isinstance(cell, str) and _NUMBER.fullmatch(cell):
                names.append("num")
            attribute = f' class="{" ".join(names)}"' if names else ""
            result.append(f"<td{attribute}>" + "".join(parts) + "</td>")
        result.append("</tr>")
        if warnings:
            result.append(
                f'<tr class="warn"><td colspan="{len(headings)}">'
                + "".join(
                    f'<div class="op-note">{escape(w)}</div>'
                    if isinstance(w, _Note)
                    else f'<span class="see">{escape(w)}</span>'
                    if isinstance(w, _Plain)
                    else _cell_line(_Box(w))
                    for w in warnings
                )
                + "</td></tr>"
            )
        result.append("</tbody>")
    result.append("</table>")
    return "".join(result)


class _Steps(tuple):
    """An inspection note authored as a list of steps: (heading, steps, calculations).
    ``sketch`` is the set-up sketch figure printed with it, if any."""

    sketch = ""


class _Note(str):
    """An inspection note authored as one text, printed with its set-up ``sketch``."""

    sketch = ""


# A step's ``{name}`` recording field: printed as a labelled blank to write the reading in.
_FIELD = re.compile(r"\{([^{}]+)\}")
# A step starting with this prints apart from the numbered steps, as the calculation line.
CALCULATION = "Calculate:"


def _fields(text):
    return _FIELD.sub(
        lambda m: f'<span class="field">{m.group(1)} ____________</span>', escape(str(text))
    )


def _readings(steps):
    """The ``(step number, field)`` readings a stepwise procedure's steps record."""
    return [(n, m.group(1)) for n, step in enumerate(steps, 1) for m in _FIELD.finditer(step)]


def _worksheet(item):
    """A stepwise procedure that records readings, laid out as its own worksheet (the sheet
    heading names it): the numbered steps name each reading where it is taken, the
    READINGS table has a line to write each in (with the step that takes it), and the
    calculation lines work them."""
    _, steps, calculations = item

    def named(text):
        return _FIELD.sub(lambda m: f'<b class="reading">[{m.group(1)}]</b>', escape(str(text)))

    return (
        _p("Take each reading at its step and write it in the READINGS table.")
        + item.sketch
        + '<ol class="steps">'
        + "".join(f"<li>{named(step)}</li>" for step in steps)
        + "</ol><h2>READINGS</h2>"
        + _table(
            ["step", "reading", "value"],
            [(str(n), f"[{name}]", "") for n, name in _readings(steps)],
            "readings",
            widths=[10, 30, 60],
        )
        + "".join(f'<p class="calc">{_fields(line)}</p>' for line in calculations)
    )


def _item(item):
    if not isinstance(item, _Steps):
        return escape(str(item)) + getattr(item, "sketch", "")
    head, steps, calculations = item
    return (
        escape(head)
        + item.sketch
        + '<ol class="steps">'
        + "".join(f"<li>{_fields(step)}</li>" for step in steps)
        + "</ol>"
        + "".join(f'<p class="calc">{_fields(line)}</p>' for line in calculations)
    )


def _list(items, ordered=True):
    tag = "ol" if ordered else "ul"
    return f"<{tag}>" + "".join(f"<li>{_item(i)}</li>" for i in items) + f"</{tag}>"


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
        # Set while the setup sheets are written: a SHOP-MADE FIXTURE row printed example
        # values, so the job page prints the one legend for its mark.
        self.example_marks = False
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
        # (shop-made reference, its poses) -> the setup whose sheet 2 prints its table.
        self.shop_made_homes = {}
        # Setup-frame places (axis -> values) of the fits on the shop-made tables being
        # written: a position at one of them prints as that fit (shop_made_tables).
        self.fit_places = {}
        # Why a fit position printed ``?`` on the shop-made table being written.
        self.fixture_unknowns = set()
        # Shop policy decimals for making and setting fixtures; a verify flag withholds it.
        decimals = _mapping(bundle.policy.get("numbers")).get("fixture_make_decimals")
        verify = bundle.policy.get("numbers_verify", False)
        if isinstance(verify, dict):
            verify = verify.get("fixture_make_decimals", False)
        self.make_decimals = (
            int(decimals)
            if verify is False and _known(decimals) and decimals >= 0 and decimals == int(decimals)
            else None
        )

    # ------------------------------------------------------------------ numbers
    def precision(self, feature=None, dimension=None):
        return drawing_precision(self.bundle, feature, dimension)

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
        """How a joint setup joins its two received branches: method, process and the
        declared fit band; for retaining compound, surface prep and the undisturbed cure
        too, unless a ``fit`` op does the join: then they print once, on that op
        (:meth:`compound_note`), and the arrival line never repeats them."""
        joint = _mapping(setup.get("joint"))
        if not joint:
            return ""
        text = f" Joined by {_text(joint['method'])} ({self.bench(joint['process'], setup)})"
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
        fitted = any(op.get("do") == "fit" for op in setup.get("ops", []))
        if joint["method"] == "retaining_compound" and not fitted:
            text += " " + self.compound_text(
                setup, joint, "Apply the retaining compound, assemble, then do"
            )
        return text

    def compound_text(self, setup, joint, lead):
        """A retaining-compound joint's surface prep and undisturbed cure, an unknown one
        printed as unknown; ``lead`` opens the cure sentence ("… not disturb until cured")."""
        prep, cure = joint.get("surface_prep"), joint.get("cure_time_min")
        known_prep = isinstance(prep, str) and prep.strip() and prep != "unknown"
        return (
            "Surface prep: "
            + (
                f"{self.bench(prep, setup).rstrip('.')}."
                if known_prep
                else "? UNKNOWN (not declared)."
            )
            + f" {lead} not disturb until cured: "
            + (
                f"cure time {_number(cure)} min."
                if _known(cure)
                else "cure time ? min UNKNOWN (not declared)."
            )
        )

    def compound_note(self, setup, op):
        """The first ``fit`` op of a retaining-compound joint setup carries the joint's
        surface prep and undisturbed cure (the arrival line then leaves them out)."""
        joint = _mapping(setup.get("joint"))
        fits = [o for o in setup.get("ops", []) if o.get("do") == "fit"]
        if (
            not joint
            or joint.get("method") != "retaining_compound"
            or not fits
            or fits[0] is not op
        ):
            return None
        return self.compound_text(setup, joint, "Do")

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

    def positive_direction(self, axis, value, lathe):
        """A DRO axis' declared positive sense in the setup machine's own words: the plan
        states one machine-aligned sign per axis (``zero_recipe.DIRECTIONS``), which reads
        right/away/up on a mill and radial/exposed-end on a lathe."""
        positive, negative = _SIGNS.get(axis, (set(), set()))
        sign = "+" if value in positive else "-" if value in negative else None
        words = (_LATHE_SENSE if lathe else _MILL_SENSE).get((axis, sign))
        return words or self.bench(value)

    def indicate_recipe(self, setup, axis, feature, authored, tool=None):
        """How to centre on an indicated cylinder: swept all round when it stands along
        setup Z (its declared axis, or both X and Y picked up on it), over its crest when
        it lies along the table (its declared axis, or a part held on a dividing head);
        then Axis Set."""
        name = re.sub(r" axis$", "", self.feature_name(feature)) if feature else "feature"
        letter = axis.upper()
        definition = self.features.get(feature, {}) if isinstance(feature, str) else {}
        declared = definition.get("axis")
        standing = None

        def indicated(recipe):
            recipe = _mapping(recipe)
            on = recipe.get("feature", recipe.get("edge"))
            picked = recipe.get("method") == "indicate_axis" or recipe.get("from") == "indicated"
            return picked and on == feature

        if isinstance(declared, list) and len(declared) == 3 and all(map(_known, declared)):
            frames = _mapping(self.bundle.features.get("frames"))
            source = _mapping(frames.get(definition.get("frame", "model")))
            basis = [source.get(k) for k in ("x", "y", "z")]
            if all(isinstance(b, list) and len(b) == 3 for b in basis):
                declared = [sum(declared[j] * basis[j][i] for j in range(3)) for i in range(3)]
            z = _mapping(setup_frame(self.bundle, setup)).get("z")
            if isinstance(z, list) and len(z) == 3 and all(map(_known, z)):
                norm = math.sqrt(sum(v * v for v in declared)) or 1.0
                standing = abs(sum(a * b for a, b in zip(declared, z, strict=True))) / norm > 0.999
        elif all(indicated(authored.get(a)) for a in ("x", "y")):
            standing = True
        elif "index" in _mapping(setup.get("hold")):
            standing = False
        tool = tool or "DTI"
        sweep_round = (
            f"{tool} in the spindle; turn the spindle by hand to sweep the {name} all round and "
            "move the table until the reading is the same all round"
        )
        sweep_crest = (
            f"{tool} in the spindle; sweep across the {name} in {letter} and move the table "
            "until the highest reading (the crest) is under the spindle"
        )
        if standing is True:
            recipe = sweep_round
        elif standing is False:
            recipe = sweep_crest
        else:
            recipe = f"standing up: {sweep_round}; lying along the table: {sweep_crest}"
        return f"indicate: {recipe}; then Axis Set {letter}"

    @property
    def decimals(self):
        """The DRO decimals of the setup being written (:func:`dro_grid`): its machine's
        declared resolution, else the default grid."""
        return dro_grid(self.bundle, self.setup or {})[1]

    def operative(self, value, decimals=None):
        """Machine targets (tips, stations, cutter centres) print at DRO resolution: the
        setup being written's, unless ``decimals`` names another machine's grid."""
        if isinstance(value, (list, tuple)):
            return " / ".join(self.operative(v, decimals) for v in value)
        if isinstance(value, dict) and "value" in value:
            value = value["value"]
        return _number(value, self.decimals if decimals is None else decimals)

    def band(self, value, feature, dimension):
        """A drawing acceptance band (``6.330–6.350``) at the drawing's own precision,
        rounded inward (low limit up, high limit down) so printing never loosens it; a band
        too narrow for that precision prints its limits as declared."""
        precision = self.precision(feature, dimension)
        printed = printed_band(value, precision)
        if printed is not None:
            return "–".join(_number(limit, precision) for limit in printed)
        known = isinstance(value, (list, tuple)) and len(value) == 2 and all(map(_known, value))
        if known and isinstance(precision, int):
            return f"{_number(value[0])}–{_number(value[1])}"
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

    def tool_detail(self, reference, holder=None):
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
        # A blade's reach is how deep it can plunge, not how far it sticks out.
        for key, label in (("dia_mm", "Ø"), ("reach_mm", "max plunge depth ")):
            size = _amount(item.get(key))
            if size is not None:
                detail.append(f"{label}{self.operative(size)}")
        # A reduced or stepped shank is what the holder grips: print it where it differs.
        shank, cutting = length_mm(item, "shank"), length_mm(item, "dia")
        if _known(shank) and _known(cutting) and abs(shank - cutting) > 1e-3:
            detail.append(f"shank Ø{self.operative(shank)}")
        flute = length_mm(item, "flute_len")
        if _known(flute):
            detail.append(f"flute {self.operative(flute)}")
        flutes = item.get("flutes")
        if isinstance(flutes, int) and item.get("kind") != "endmill_set":
            detail.append(f"{flutes} flutes")
        for key in ("material", "coating"):
            if isinstance(item.get(key), str) and item[key] != "unknown":
                detail.append(item[key])
        # Installed projection of this exact tool/holder pair, as the inventory measured it.
        for field, scale in (("projection_mm", 1.0), ("projection_in", 25.4)):
            projection = _amount(_mapping(item.get(field)).get(holder))
            if projection is not None:
                detail.append(f"projection {self.operative(projection * scale)} from holder face")
                break
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
        # Executed order: a span the hold will cover is measured before the part goes in.
        steps = self.bench_measures(setup)

        def stated(key):
            value = hold.get(key)
            return value not in (None, "none", "not_applicable")

        fixture = hold.get("fixture", "unknown")
        uses = self.shop_made_uses(setup)
        if fixture == "unknown":
            steps.append("STOP: holding not chosen — do not run.")
        else:
            mount = "Mount the " + self.reference(fixture, "fixtures")
            mount += self.shop_made_pointer(setup, fixture, uses)
            if stated("chuck"):
                mount += " with the " + self.reference(hold["chuck"], "fixtures")
            if stated("jaws_along"):
                mount += f"; jaws along {_text(hold['jaws_along']).upper()}"
            if stated("fixed_jaw"):
                mount += f"; fixed jaw {_text(hold['fixed_jaw'])}"
            steps.append(mount + ".")
            steps.extend(self.fixture_setting(setup, hold, uses))
            steps.extend(self.align_step(setup, hold))
        if stated("parallels") and hold["parallels"] != "unknown":
            line = "Parallels: " + self.reference(hold["parallels"])
            if stated("riser"):
                line += ", standing on " + self.reference(hold["riser"])
                line += self.shop_made_pointer(setup, hold["riser"], uses)
            if stated("support_orientation"):
                line += f" ({_text(hold['support_orientation'])} up)"
            steps.append(line + ".")
        if stated("jaw_bar") and hold["jaw_bar"] != "unknown":
            steps.append(
                "Round bar: "
                + self.reference(hold["jaw_bar"], "fixtures")
                + " between the work and the moving jaw, centred in the jaws, its centre "
                + self.jaw_bar_height(setup, hold)
                + "."
            )
        if stated("jaw_buttons") and hold["jaw_buttons"] != "unknown":
            steps.append(
                "Jaw buttons: "
                + self.reference(hold["jaw_buttons"], "fixtures")
                + ", one between each jaw and the work, its spigot in the work's bore."
            )
        supports = hold.get("supports")
        if isinstance(supports, str) and supports not in ("none", "not_applicable", "unknown"):
            if not (stated("riser") and supports == hold.get("riser")):
                steps.append(
                    "Supports: "
                    + self.reference(supports)
                    + self.shop_made_pointer(setup, supports, uses)
                    + "."
                )
        for support in supports if isinstance(supports, list) else []:
            support = _mapping(support)
            line = "Support: " + self.bench(support.get("ref", "?"))
            if support.get("ops"):
                line += f" for {_ops_label(support['ops'])}"
            if _known(support.get("jaw_lead_mm")):
                lead = self.operative(support["jaw_lead_mm"])
                # A follow rest's jaws ride the Ø just cut ("turned", the default) or the
                # uncut stock ahead of the tool ("uncut"). The lead is a distance along the
                # work, never printed beside a Ø sign where it would read as a diameter.
                if support.get("jaw_side", "turned") == "uncut":
                    line += f", jaws {lead} mm ahead of the tool, on the uncut stock"
                else:
                    # Each pass turns a new diameter: trailing jaws go on and come off every
                    # pass, in the sequence printed under each op (:meth:`rest_steps`).
                    line += f", jaws {lead} mm behind the tool, on the diameter just turned;"
                    line += " set on and backed off every pass as printed under each op"
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
        stop_pointer = self.shop_made_pointer(setup, hold.get("stop_fixture"), uses)
        if stop_pointer:
            steps.append(
                f"Work stop: {self.reference(hold['stop_fixture'], 'fixtures')}{stop_pointer}."
            )
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
        clamps = hold.get("clamps") if isinstance(hold.get("clamps"), list) else []
        for label, clamp in zip(clamp_labels(hold), clamps, strict=True):
            clamp = _mapping(clamp)
            role = _CLAMP_ROLES[label.rstrip("0123456789")]
            line = f"{label} {role}: {self.reference(clamp.get('ref'))}"
            line += self.shop_made_pointer(setup, clamp.get("ref"), uses)
            if clamp.get("note"):
                line += " — " + self.bench(clamp["note"], setup)
            steps.append(line + ".")
        steps.extend(self.shim_steps(setup, uses))
        tighten = self.tightening(hold)
        if tighten:
            steps.append(tighten)
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

    def align_step(self, setup, hold):
        """The step that squares a vise's fixed jaw, or an angle plate's locating face, to
        the table travel where this setup mounts or turns one (hold_fields ``align_due``):
        its indicator, sweep length and limit come from ``hold.align``; any not established
        is a STOP."""
        due = _mapping(self.records.get(("hold_fields", setup["id"]))).get("align_due")
        if due in (None, "not_applicable"):
            return []
        ref = hold.get("fixture")
        kind = _mapping(resolve(self.bundle, workholding_category(self.bundle, ref), ref))
        vise = kind.get("kind") == "vise"
        align = _mapping(hold.get("align"))
        named = align.get("face") not in (None, "unknown")
        face = (
            "the fixed jaw"
            if vise
            else f"the plate's {_text(align['face'])} face"
            if named
            else "the plate's locating face"
        )
        axis = align_travel(self.bundle, hold)
        gauge = align.get("indicator", "unknown")
        limit, over = align.get("limit_mm", "unknown"), align.get("over_mm", "unknown")
        missing = [
            name
            for name, known in (
                ("the travel it runs along", axis in ("X", "Y")),
                ("the indicator", align_indicator(self.bundle, gauge) not in (None, "unknown")),
                ("the sweep length", _known(over)),
                ("the limit", _known(limit)),
            )
            if not known
        ]
        if missing:
            return [
                f"STOP: square {face} to the table travel — "
                + ", ".join(missing)
                + " not established; do not run."
            ]
        thing = "vise" if vise else "plate"
        return [
            f"Square {face} to the {axis} travel: with the {self.reference(gauge, 'gauges')} "
            f"held from the spindle head on {face}, traverse {axis} {_number(over)} mm along "
            f"it; tap the {thing} round until the reading changes no more than "
            f"{_number(limit)} mm ({_number(round(limit / 25.4, 5))} in) over that length, "
            f"tighten the {thing} to the table and sweep again."
        ]

    def bench_measures(self, setup):
        """HOLD steps for each ``measure_then_set`` M the plan reads before the part is
        held: the span the hold covers is measured first, and the zero row refers back."""
        zero = _mapping(setup.get("zero"))
        steps = []
        for axis in ("x", "y", "z"):
            touch = _mapping(zero.get(axis))
            if touch.get("measure_before_hold") is not True or not touch.get("measure"):
                continue
            gauge = touch.get("gauge")
            line = f"Before clamping, measure {axis.upper()} M = " + self.bench(
                touch["measure"], setup
            )
            if gauge not in (None, "unknown"):
                line += " with the " + self.short_reference(gauge, "gauges")
            steps.append(line + "; write it down for the DRO table.")
        return steps

    def blank_checks(self, setup):
        """The squared blank's checks, on the sheet of the setup that hands it on."""
        prepared = _mapping(_mapping(self.plan.get("stock")).get("prepared"))
        receiver = prepared.get("setup")
        setups = {s["id"]: s for s in self.plan.get("setups", [])}
        if receiver not in setups or setups[receiver].get("stock_in") != setup["id"]:
            return ""
        checks, methods = _mapping(prepared.get("checks")), _mapping(prepared.get("methods"))
        limits = _mapping(prepared.get("form_mm"))
        section = prepared.get("section_mm")
        section = section if isinstance(section, list) and len(section) == 2 else [None] * 2
        sizes = [prepared.get("length_mm"), *section]
        tolerance = prepared.get("tolerance_mm")
        tolerance = tolerance if isinstance(tolerance, list) and len(tolerance) == 3 else []
        allowed = [tolerance[2], tolerance[0], tolerance[1]] if tolerance else [None] * 3

        def gauge(key):
            ref = checks.get(key, "unknown")
            return "? not chosen" if ref == "unknown" else self.reference(ref, "gauges")

        rows = []
        for key, size, tol in zip(
            ("length", "section_0", "section_1"), sizes, allowed, strict=True
        ):
            limit = f"{size:g} ±{tol:g} mm" if _known(size) and _known(tol) else "? not set"
            rows.append(("size", limit, gauge(key)))
        for key in ("flat", "square", "parallel"):
            method, limit = methods.get(key), limits.get(key)
            limit = f"within {limit:g} mm" if _known(limit) else "? limit not set"
            method = self.bench(method, setup) if method else "? not written"
            rows.append((key, f"{limit}: {method}", gauge(key)))
        return (
            f"<h2>CHECK THE BLANK — before SETUP {escape(receiver)}</h2>"
            + _p(
                f"Process limits for the squared blank, not drawing limits: SETUP {receiver} "
                "locates on these faces. File the edge burrs off and wipe the blank first."
            )
            + _table(["check", "limit and method", "gauge"], rows, widths=[10, 65, 25])
        )

    def jaw_bar_height(self, setup, hold):
        """Where the vise's round bar sits, as the kernel models it, in mm like the other
        holding facts: its centre halfway up the work the jaws hold,
        ``min(jaw_above_parallels_mm, top_z - bottom_z) / 2`` above the parallels (the
        work's middle only when the jaws cover all of it). The stock heights are plan-unit
        setup-frame values, so the work's height is unknown without the plan units."""
        state = _mapping(setup.get("stock_state"))
        top, bottom = state.get("top_z"), state.get("bottom_z")
        jaw = hold.get("jaw_above_parallels_mm")
        scale = {"mm": 1.0, "in": 25.4}.get(self.units)
        if not (_known(top) and _known(bottom) and _known(jaw) and scale):
            return "? height not set (jaw height, stock top/bottom or plan units unknown)"
        return f"{self.operative(min(jaw, (top - bottom) * scale) / 2)} mm above the parallels"

    def hold_facts(self, setup, hold, lathe):
        o = self.operative
        facts = []
        if _known(hold.get("grip_mm")):
            facts.append(("grip length mm", o(hold["grip_mm"])))
        elif hold.get("grip_mm") == "unknown":
            facts.append(("grip length mm", "? not set"))
        fit = _mapping(hold.get("stickout_fit"))
        if fit and _known(hold.get("stickout_mm")):
            # A stickout from a measured fit-up: the number is the nominal, and the
            # operator sets the measured reading plus the allowance.
            facts.append(("nominal stickout mm", o(hold["stickout_mm"])))
            measure, add = fit.get("measure"), fit.get("add_mm")
            stated = isinstance(measure, str) and measure.strip() and measure != "unknown"
            facts.append(
                (
                    "set stickout",
                    f"measured {self.bench(measure, setup)} + {o(add)}"
                    if stated and _known(add)
                    else "? fit-up reading or allowance not stated",
                )
            )
        elif _known(hold.get("stickout_mm")):
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
        # An indexed hold's jaw clock is whatever its Index line's plate setting turns: that
        # line prints the angle it gives against the planned one, so no second angle here.
        indexed = _known(_mapping(hold.get("index")).get("angle_deg"))
        if _known(clock) and clock and not lathe and not indexed:
            facts.append(("jaw 1 clocked °", _number(clock)))
        return facts

    # ------------------------------------------------------------ shop-made
    def shop_made(self, reference):
        """The inventory record of a shop-made holding item (``kind = "custom"`` or flagged
        ``shop_made``) with something to make, else None: an item whose every solid is
        bought or existing (a plain ground plate) has no make table."""
        if not isinstance(reference, str) or reference in ("unknown", "none", "not_applicable"):
            return None
        category = inventory_category(self.bundle, reference, WORKHOLDING_CATEGORIES)
        item = _mapping(resolve(self.bundle, category or "fixtures", reference))
        if not (item.get("kind") == "custom" or item.get("shop_made") is True):
            return None
        solids = [s for s in item.get("solids") or [] if isinstance(s, dict)]
        if solids and not any(_supply(s) == "made" for s in solids):
            return None
        return item

    def shop_made_uses(self, setup):
        """``{reference: [(label, pose)]}`` for each shop-made item the hold uses, in HOLD
        order: the fixture at ``hold.pose``, each clamp entry at its own pose (labelled by
        :func:`clamp_labels`), the work stop at ``stop_pose``; risers and supports carry
        no pose."""
        hold = _mapping(setup.get("hold"))
        clamps = hold.get("clamps") if isinstance(hold.get("clamps"), list) else []
        placed = [(hold.get("fixture"), None, hold.get("pose"))]
        placed += [
            (_mapping(clamp).get("ref"), label, _mapping(clamp).get("pose"))
            for label, clamp in zip(clamp_labels(hold), clamps, strict=True)
        ]
        placed.append((hold.get("stop_fixture"), "stop", hold.get("stop_pose")))
        placed += [(hold.get(key), None, None) for key in ("riser", "supports")]
        uses = {}
        for reference, label, pose in placed:
            if self.shop_made(reference) is None or (pose is None and reference in uses):
                continue
            uses.setdefault(reference, []).append((label, pose))
        return uses

    def shop_made_home(self, setup, reference, uses):
        """The setup whose sheet 2 prints this item's table: its first use at these poses
        under these HOLD labels (a renumbered clamp gets its own table)."""
        key = (reference, repr(uses[reference]))
        return self.shop_made_homes.setdefault(key, setup["id"])

    def shop_made_pointer(self, setup, reference, uses):
        """`` (shop-made: …)`` naming the sheet with the item's table; empty otherwise."""
        if not isinstance(reference, str) or reference not in uses:
            return ""
        home = self.shop_made_home(setup, reference, uses)
        where = "sheet 2" if home == setup["id"] else f"Setup {home} sheet 2"
        return f" (shop-made: SHOP-MADE FIXTURE table, {where})"

    @functools.cached_property
    def mill_grid(self):
        """(step, decimals) of the shop's mill DRO (:func:`dro_grid`) when every inventory
        machine of kind ``mill`` reads on one grid, else None."""
        machines = _mapping(self.bundle.inventory.get("machines"))
        grids = {
            dro_grid(self.bundle, {"machine": name})
            for name, machine in machines.items()
            if _mapping(machine).get("kind") == "mill"
        }
        return next(iter(grids)) if len(grids) == 1 else None

    def fixture_number(self, value, fit=False, axis=None):
        """A shop-made fixture size or position on the DRO grid it is made and set on (the
        shop's mill, :attr:`mill_grid`, else the setup's own): at the shop policy's make
        precision (``numbers.fixture_make_decimals``), a fit that locates the part at the
        drawing's precision, and either undeclared, finer than the grid or off it at the
        grid step. A position on ``axis`` at the place of a fit on this sheet
        (:attr:`fit_places`) prints as that fit: one place, one value. A fit the grid moves
        beyond the drawing's general tolerance at its precision, or with that tolerance
        undeclared, prints ``?``: the hole is never moved silently. No trailing zeros: a
        make sheet."""
        if not _known(value):
            return "?"
        if not fit and axis is not None:
            fit = any(abs(value - place) <= 1e-6 for place in self.fit_places.get(axis, ()))
        step, decimals = self.mill_grid or dro_grid(self.bundle, self.setup or {})
        places = self.general_precision if fit else self.make_decimals
        declared = isinstance(places, int) and not isinstance(places, bool) and places >= 0
        wanted = 10.0**-places if declared else None
        coarser = declared and abs(wanted / step - round(wanted / step)) <= 1e-9 * wanted / step
        if coarser and wanted >= step * (1 - 1e-9):
            step, decimals = wanted, places
        from prechips.kernel.render_diagram import dro_steps

        steps = dro_steps(value, step)
        printed = round(steps * step, decimals)
        moved = abs(printed - value)
        if fit and declared and step != wanted and moved > 1e-9:
            key = f"linear_{places}pl"
            tolerance = _mapping(self.bundle.features.get("general_tolerances")).get(key)
            known = isinstance(tolerance, (int, float)) and not isinstance(tolerance, bool)
            if not (known and moved <= tolerance):
                state = f"{_number(tolerance)} mm" if known else "not declared"
                self.fixture_unknowns.add(
                    f"? — the {_number(step)} mm grid it is made on cannot hold a fit drawn "
                    f"to {places} places within the drawing's general tolerance "
                    f"(general_tolerances.{key}: {state}); put the fit on the grid in the "
                    "fixture design or declare the tolerance."
                )
                return "?"
        return _number(printed)

    def fixture_setting(self, setup, hold, uses):
        """Placement of a posed angle plate or shop-made fixture body: the base on the
        table/bench, an angle plate's working face (its local y = 0 face, facing local
        -y) and the hold-down the base solid declares."""
        fixture = hold.get("fixture")
        if not isinstance(fixture, str):
            return []
        category = inventory_category(self.bundle, fixture, WORKHOLDING_CATEGORIES)
        item = _mapping(resolve(self.bundle, category or "fixtures", fixture))
        angle_plate = item.get("kind") == "angle_plate"
        axes = _pose_axes(hold.get("pose"))
        solids = item.get("solids") if isinstance(item.get("solids"), list) else []
        if axes is None or not (angle_plate or fixture in uses):
            return []
        boxes = [
            (solid, _solid_extents(solid, axes))
            for solid in solids
            if isinstance(solid, dict)
            and solid.get("shape") == "box"
            and not solid.get("void")
            and _supply(solid) != "bought"
        ]
        # An unverified base gives no placement numbers.
        if any(not record_trusted(solid, require_measured=False)[0] for solid, _ in boxes):
            boxes = []
        boxes = [(solid, extents) for solid, extents in boxes if extents]
        if not boxes:
            return []
        f = self.fixture_number
        base, (low, _) = min(boxes, key=lambda pair: pair[1][0][2])
        surface = _FIXTURE_SURFACES.get(self.machine(setup).get("kind"))
        level = _setup_axis(_place(axes, [0.0, 0.0, 1.0], translate=False)) == (2, 1)
        name = "Angle plate" if angle_plate else self.reference(fixture, "fixtures")
        name = name[:1].upper() + name[1:]
        line = (
            f"{name}: base flat on the {surface}, underside at Z {f(low[2])}"
            if surface and level
            else f"{name}: base underside at Z {f(low[2])}"
        )
        if angle_plate:
            face = _setup_axis(_place(axes, [0.0, -1.0, 0.0], translate=False))
            if face:
                axis, sign = face
                line += (
                    f"; upright working face at {'XYZ'[axis]} {f(axes[0][axis])}, "
                    f"facing {'+' if sign > 0 else '−'}{'XYZ'[axis]}"
                )
        if base.get("fastener"):
            line += f"; hold the base down with {self.bench(base['fastener'], setup)}"
        return [line + "."]

    def shim_steps(self, setup, uses):
        """Adjustable shim stacks of the shop-made items in use, at their nominal size:
        one stack per shim solid per placement of its item."""
        stacks = {}
        for reference, placements in uses.items():
            tags = [label if len(placements) > 1 else None for label, _ in placements]
            for solid in self.shop_made(reference).get("solids") or []:
                solid = _mapping(solid)
                if solid.get("shim") is not True:
                    continue
                size = solid.get("size_mm")
                thickness = (
                    size[2]
                    if solid.get("shape") == "box" and isinstance(size, list) and len(size) == 3
                    else solid.get("length_mm")
                )
                nominal = (
                    self.fixture_number(thickness, fit=True)
                    if record_trusted(solid, require_measured=False)[0]
                    else "? (not verified)"
                )
                key = (nominal, solid.get("locates"))
                name = _solid_name(solid.get("name", "?"))
                stacks.setdefault(key, []).extend(f"{tag} {name}" if tag else name for tag in tags)
        steps = []
        for (thickness, locates), names in stacks.items():
            under = f" under the {self.bench(locates, setup)}" if locates else ""
            count = f"{len(names)} shim stacks" if len(names) > 1 else "Shim stack"
            steps.append(
                f"{count}{under} ({', '.join(names)}): {thickness} mm nominal; build each "
                "to fit its actual gap with feeler gauges, without lifting the part."
            )
        return steps

    def tightening(self, hold):
        """The declared ``clamp_order`` as a two-pass tightening step, after seating the
        part on its locators (and its declared preload), with any declared torque."""
        order = hold.get("clamp_order")
        clamps = hold.get("clamps") if isinstance(hold.get("clamps"), list) else []
        labels = clamp_labels(hold)
        steps = [
            i
            for i in (order if isinstance(order, list) else [])
            if isinstance(i, int) and 1 <= i <= len(clamps)
        ]
        if not steps:
            return ""
        named = ", ".join(labels[i - 1] for i in steps)
        if len(steps) == 1:
            text = f"Tighten {named}: snug it, then tighten fully"
        else:
            text = (
                f"Tighten in order {named}: snug each in turn, then tighten each fully "
                "in the same order"
            )
        torques = {
            labels[i - 1]: _mapping(clamps[i - 1]).get("torque_nm")
            for i in steps
            if _known(_mapping(clamps[i - 1]).get("torque_nm"))
        }
        if torques and len(torques) == len(steps) and len(set(torques.values())) == 1:
            text += f" to {_number(next(iter(torques.values())))} N·m"
        elif torques:
            text += "; torque " + ", ".join(f"{k} {_number(v)} N·m" for k, v in torques.items())
        locators = [label for label in labels if label.startswith("LOC")]
        if locators:
            seat = f"Seat the part against {', '.join(locators)}"
            preload = hold.get("preload_direction")
            if preload in ("clockwise", "counterclockwise"):
                seat += f", turning it {preload} (viewed from above) to take up the clearance"
            text = f"{seat}; then {text[:1].lower()}{text[1:]}"
        return text + "."

    def solid_size(self, solid, fit=False):
        f = functools.partial(self.fixture_number, fit=fit)
        void = solid.get("void") is True
        if solid.get("shape") == "box" and isinstance(solid.get("size_mm"), list):
            size = " × ".join(f(v) for v in solid["size_mm"])
            return f"cut-out {size}" if void else size
        if solid.get("shape") == "cylinder":
            if void:
                return f"Ø{f(solid.get('dia_mm'))} hole"
            return f"Ø{f(solid.get('dia_mm'))} × {f(solid.get('length_mm'))}"
        return "?"

    def solid_position(self, solid, axes, fit=False):
        """Setup-frame position: a box's X/Y/Z extents, a cylinder's axis."""
        extents = _solid_extents(solid, axes) if axes else None
        if extents is None:
            return "? not posed"

        def f(value, axis):
            return self.fixture_number(value, fit=fit, axis=axis)

        first, second = extents
        if solid.get("shape") == "box":
            return ", ".join(f"{a} {f(first[i], i)}…{f(second[i], i)}" for i, a in enumerate("XYZ"))
        direction = _place(axes, solid["axis"], translate=False)
        along = _setup_axis(direction)
        if along:
            i = along[0]
            j, k = (n for n in range(3) if n != i)
            low, high = sorted((first[i], second[i]))
            return (
                f"axis at {'XYZ'[j]} {f(first[j], j)}, {'XYZ'[k]} {f(first[k], k)}; "
                f"{'XYZ'[i]} {f(low, i)}…{f(high, i)}"
            )
        nearest = max(range(3), key=lambda n: abs(direction[n]))
        tilt = math.degrees(math.acos(min(1.0, abs(direction[nearest]))))
        sign = "+" if direction[nearest] > 0 else "−"
        return (
            f"axis from ({', '.join(f(v, n) for n, v in enumerate(first))}) to "
            f"({', '.join(f(v, n) for n, v in enumerate(second))}), "
            f"{self.angle(tilt)}° off {sign}{'XYZ'[nearest]}"
        )

    def shop_made_tables(self, setup):
        """One SHOP-MADE FIXTURE table per shop-made item first used (at these poses) in
        this setup; a later setup using it at the same poses points back here. Every fit
        on the sheet's items marks its setup-frame places first, so a hole or mating part
        at one of them prints the same value in every table."""
        uses = self.shop_made_uses(setup)
        self.fit_places = {}
        for reference, placements in uses.items():
            solids, _, withheld, _, _, fits = self.shop_made_parts(reference)
            for solid in solids:
                if id(solid) not in fits or id(solid) in withheld:
                    continue
                for _, pose in placements:
                    axes = _pose_axes(pose)
                    for point in (_solid_extents(solid, axes) if axes else None) or ():
                        for axis, value in enumerate(point):
                            if _known(value):
                                self.fit_places.setdefault(axis, set()).add(value)
        tables = "".join(
            self.shop_made_table(setup, reference, placements)
            for reference, placements in uses.items()
            if self.shop_made_home(setup, reference, uses) == setup["id"]
        )
        self.fit_places = {}
        return tables

    def shop_made_parts(self, reference):
        """The item's solids, made solids, withheld solids (id -> why), holes per parent
        solid id, drilled parent ids and fit ids: a locating solid is a fit, and so is every
        bore cut in it (either may be the surface that locates). Like the kernel, an
        unverified primitive gives no numbers, and an unverified hole withholds the solids it
        would cut."""
        item = self.shop_made(reference)
        solids = [s for s in item.get("solids") or [] if isinstance(s, dict)]
        # Made solids, and existing parts (a bought angle plate) only for holes cut here.
        made = [s for s in solids if not s.get("void") and _supply(s) != "bought"]
        withheld = {
            id(s): "unverified" for s in solids if not record_trusted(s, require_measured=False)[0]
        }
        holes, drilled = {}, set()
        for void in (s for s in solids if s.get("void") and _supply(s) == "made"):
            name = void.get("name", "?")
            parents, unresolved = _void_parents(void, solids, made)
            for parent in unresolved:
                drilled.add(id(parent))
                withheld.setdefault(
                    id(parent), f"oblique hole {name} may cross it; name it in cuts"
                )
            for parent in parents:
                drilled.add(id(parent))
                if id(void) in withheld:
                    withheld.setdefault(id(parent), f"its hole {name} is unverified")
                else:
                    holes.setdefault(id(parent), []).append(void)
        fits = set()
        for solid in (s for s in made if s.get("locates")):
            fits.update([id(solid), *(id(v) for v in holes.get(id(solid), []))])
        return solids, made, withheld, holes, drilled, fits

    def shop_made_table(self, setup, reference, placements):
        """The item's made solids as make-and-set rows; identical solids share a row (an
        authored ``label`` names the group), each row lists every setup-frame position
        and the holes cut in it. Bought hardware is one line under the table, and each
        made row's ``note`` (material, heat treatment, finish) one "Make:" entry under
        that; solids already in the shop (``supply = "existing"``, such as machine vise
        jaws drawn for clearance) are not listed. A fit position printed ``?`` says why
        under the table."""
        sid = setup["id"]
        item = self.shop_made(reference)
        placed = [(label, _pose_axes(pose)) for label, pose in placements]
        solids, made, withheld, holes, drilled, fits = self.shop_made_parts(reference)
        self.fixture_unknowns = set()
        groups = {}
        for solid in made:
            if _supply(solid) == "existing" and id(solid) not in drilled:
                continue
            key = (
                solid.get("label"),
                _supply(solid),
                id(solid) if id(solid) in withheld else None,
                solid.get("shape"),
                repr(solid.get("size_mm")),
                solid.get("dia_mm"),
                solid.get("length_mm"),
                solid.get("locates"),
                solid.get("fastener"),
                solid.get("note"),
            )
            groups.setdefault(key, []).append(solid)

        def prefixed(tag, name, count, where):
            parts = (tag if len(placed) > 1 else None, name if count > 1 else None)
            prefix = " ".join(part for part in parts if part)
            return f"{prefix}: {where}" if prefix else where

        rows, notes = [], {}
        for (label, *_), members in groups.items():
            names = [_solid_name(solid.get("name", "?")) for solid in members]
            stem, tags = _name_group(names)
            component = f"{stem} ×{len(members)}" if stem else " / ".join(names)
            component = self.bench(label) if label else component
            if _supply(members[0]) == "existing":
                component += " (existing part: make the holes only)"
            first = members[0]
            if first.get("note"):
                notes.setdefault(self.bench(first["note"]).rstrip("."), []).append(component)
            fit = id(first) in fits
            if id(first) in withheld:
                where = f"? not set: {withheld[id(first)]}; verify before making"
                rows.append([component, "?", [where], "—", "—"])
                continue
            positions = [
                prefixed(tag, name, len(members), self.solid_position(solid, axes, fit))
                for solid, name in zip(members, tags, strict=True)
                for tag, axes in placed
            ]
            cut = [
                (void, name)
                for solid, name in zip(members, tags, strict=True)
                for void in holes.get(id(solid), [])
            ]
            if any(map(_example, members)) or any(_example(void) for void, _ in cut):
                component += f" {EXAMPLE_MARK}"
                self.example_marks = True
            kinds = {}
            for void, name in cut:
                key = (
                    void.get("fastener"),
                    void.get("shape"),
                    void.get("dia_mm"),
                    repr(void.get("size_mm")),
                )
                kinds.setdefault(key, []).append((void, name))
            for (fastener, *_), voids in kinds.items():
                void_fit = id(voids[0][0]) in fits
                what = self.bench(fastener) if fastener else self.solid_size(voids[0][0], void_fit)
                count = len(voids) * len(placed)
                spots = "; ".join(
                    prefixed(tag, name, len(members), self.solid_position(void, axes, void_fit))
                    for void, name in voids
                    for tag, axes in placed
                )
                positions.append(f"with {count} × {what}: {spots}")
            rows.append(
                [
                    component,
                    self.solid_size(first, fit) if _supply(first) == "made" else "—",
                    positions,
                    self.bench(first["locates"]) if first.get("locates") else "—",
                    self.bench(first["fastener"]) if first.get("fastener") else "—",
                ]
            )
        if not solids:
            dims = [_amount(item.get(f"{edge}_mm")) for edge in ("length", "width", "height")]
            size = (
                " × ".join(self.fixture_number(v) for v in dims)
                if None not in dims
                else "? not declared"
            )
            body = "body"
            if any(_example(item.get(f"{edge}_mm")) for edge in ("length", "width", "height")):
                body += f" {EXAMPLE_MARK}"
                self.example_marks = True
            rows.append([body, size, ["? not posed"], "—", "—"])
        headings = [
            "Component",
            "Size mm",
            f"Position, Setup {sid} X / Y / Z mm",
            "Locates",
            "Fastener",
        ]
        widths = [17, 15, 40, 14, 14]
        keep = [0, 1, 2] + [c for c in (3, 4) if any(row[c] != "—" for row in rows)]
        spare = sum(w for c, w in enumerate(widths) if c not in keep)
        widths = [widths[c] + (spare if c == 2 else 0) for c in keep]
        users = [label for label, _ in placements if label and label != "stop"]
        title = f"SHOP-MADE FIXTURE — {self.reference(reference, 'fixtures')}"
        title += f" ({', '.join(users)})" if users else ""
        intro = (
            f"Make before Setup {sid}. Positions are in the Setup {sid} frame: boxes give "
            "their X / Y / Z extents, cylinders their axis."
        )
        hardware = self.hardware(
            [s for s in solids if not s.get("void") and _supply(s) == "bought"], len(placed)
        )
        return (
            f"<h2>{escape(title)}</h2>"
            + _p(intro)
            + (
                _table(
                    [headings[c] for c in keep],
                    [[row[c] for c in keep] for row in rows],
                    widths=widths,
                )
                if rows
                else ""
            )
            + (_p(f"Bought hardware (not made): {hardware}.") if hardware else "")
            + (_p(f"Make: {_make_notes(notes)}.") if notes else "")
            + "".join(_p(reason) for reason in sorted(self.fixture_unknowns))
        )

    def hardware(self, solids, uses):
        """Bought solids as ``2 × 3/8-16 stud; 2 × washer Ø20.6 × 1.6``: the declared
        ``fastener`` names a part, else its name and size do. A part drawn as several
        touching primitives with one ``fastener`` text (an SHCS head on its shank) counts
        once; separate primitives are separate parts."""
        groups = {}
        for solid in solids:
            fastener = solid.get("fastener")
            key = (
                (fastener,)
                if fastener
                else (
                    None,
                    solid.get("shape"),
                    repr(solid.get("size_mm")),
                    solid.get("dia_mm"),
                    solid.get("length_mm"),
                )
            )
            groups.setdefault(key, []).append(solid)
        parts = []
        for (fastener, *_), members in groups.items():
            if fastener:
                count, what = _touching_groups(members), self.bench(fastener)
            else:
                names = [_solid_name(solid.get("name", "?")) for solid in members]
                stem, _ = _name_group(names)
                count = len(members)
                what = f"{stem or ' / '.join(dict.fromkeys(names))} {self.solid_size(members[0])}"
            parts.append(f"{count * uses} × {what}")
        return "; ".join(parts)

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
        r = _number  # Dividing-head arithmetic keeps its own digits; it is not a DRO reading.
        glyph = _GLYPHS.get(_status(finding), "")
        tentative = "Tentative — " if _status(finding) == "unknown" else ""
        head = f"Index: {glyph} {tentative}{self.short_reference(numbers.get('fixture'))}: "
        positions = numbers.get("positions")
        lock = "Lock the spindle before cutting."
        if numbers.get("requested_angle_deg") == 0 and positions == 1:
            return _p(self.bench(f"{head}index pin in the zero hole. {lock}"))
        if numbers.get("method") not in {"direct", "worm"}:
            return _p(self.bench(f"{head}plate / circle / turns / hole spaces: ? {lock}"))
        kind = "spindle turn" if numbers["method"] == "direct" else "crank turn"
        turns = numbers.get("turns")
        kind += "" if turns == 1 else "s"
        sense = self.index_sense(hold)
        parts = [
            f"{head}{'reverse: ' if numbers.get('direction') == 'reverse' else ''}"
            f"plate {r(numbers.get('plate'))}, {r(numbers.get('circle'))}-hole circle: "
            f"{r(turns)} {kind} + {r(numbers.get('spaces'))} hole spaces "
            f"(count spaces, not holes), turning the work {sense}"
            + ("" if positions == 1 else f"; repeat for each of the {r(positions)} positions")
            + "."
        ]
        parts.append(self.index_angle(numbers))
        if numbers["method"] == "worm":
            parts.append(
                "Take up the worm backlash: always crank so the work turns that same way; if "
                "the pin overshoots the hole, back off past it and come again the same way."
            )
        parts.append(lock)
        return _p(self.bench(" ".join(parts)))

    @staticmethod
    def index_angle(numbers):
        """The angle the printed plate setting actually turns, against the planned angle and
        the allowance: one executable value, with its difference from the plan stated."""
        planned, actual = numbers.get("requested_angle_deg"), numbers.get("actual_angle_deg")
        error = numbers.get("step_error_deg")
        if not (_known(planned) and _known(actual) and _known(error)):
            return "Angle this setting gives: ? (not computed)."
        step = "Each step" if numbers.get("positions") != 1 else "This setting"
        planned = _number(planned) if _places(planned) <= 4 else _angle(planned)
        if (
            numbers.get("exact") is True
            and numbers.get("requested_angle_source") == "360/positions"
        ):
            return f"{step} is exactly 1/{numbers.get('positions')} turn."
        if numbers.get("exact") is True:
            return f"{step} is exactly the planned {planned}°."
        text = (
            f"{step} turns the work {_angle(actual)}°, {_angle(abs(error))}° off the planned "
            f"{planned}°"
        )
        worst = numbers.get("max_position_error_deg")
        errors = numbers.get("position_errors_deg") or []
        if len(errors) > 1 and _known(worst):
            landing = 1 + max(range(len(errors)), key=lambda i: abs(errors[i]))
            text += f"; landing {landing} ends {_angle(worst)}° off"
        tolerance = numbers.get("tolerance_deg")
        if not _known(tolerance):
            return text + " (allowance ? — not known)."
        if numbers.get("failed"):
            return text + f": OUTSIDE the ±{_number(tolerance)}° allowed."
        return text + f" (allowed ±{_number(tolerance)}°)."

    @staticmethod
    def index_sense(hold):
        """The way the work turns, from the jaw clock's sign (right-handed about the chuck's
        +z, which points out of the jaws to the work's free end): seen from the free end, a
        positive clock turns counterclockwise."""
        clock = hold.get("jaw_clock_deg")
        z = _mapping(hold.get("pose")).get("z")
        if not _known(clock) or not clock:
            return "? way (no jaw clock angle)"
        sense = "counterclockwise" if clock > 0 else "clockwise"
        where = "viewed from the free end of the work"
        if isinstance(z, list) and len(z) == 3 and all(map(_known, z)):
            axis = max(range(3), key=lambda i: abs(z[i]))
            where += (
                f" (from setup {'+' if z[axis] > 0 else '−'}{'XYZ'[axis]}, looking at the chuck)"
            )
        return f"{sense} {where}"

    # ------------------------------------------------------------- clearance
    def clearance(self, setup, tool_numbers=None):
        if saw_setup(setup):
            # A saw cut-off has no spindle stack or table travel: nothing to print.
            return None
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
            body = "".join(_p(line) for line in lines)
            return f'<div class="keep"><h2>CLEARANCE — lathe</h2>{body}</div>'
        unknown = "? Not computed — check at the machine: "
        missing = []
        if "head_centre_height_mm" in numbers:
            need, have = numbers.get("sum_mm"), numbers.get("spindle_to_table_max_mm")
            if _known(need):
                lines.append(
                    f"Spindle-to-table over the dividing head: needs {o(need)} of {o(have)}: "
                    f"{fits(need, have)}."
                )
            else:
                missing.append("spindle-to-table room over the dividing head")
        elif "bed_height_mm" in numbers or "sum_mm" in numbers:
            need, have = numbers.get("sum_mm"), numbers.get("spindle_to_table_max_mm")
            worst = next((s for s in numbers.get("stacks", []) if s.get("sum_mm") == need), {})
            if _known(need) and worst:
                lines.append(
                    f"Spindle-to-table, tallest stack (op {_text(worst.get('op'))}) with "
                    f"tool-change room: needs {o(need)} of {o(have)}: {fits(need, have)}."
                )
            else:
                missing.append("spindle-to-table room (holding height not known)")
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
        rows = self.clearance_rows(setup, numbers, tool_numbers or {})
        if any(not _known(s.get("margin_mm")) for s in numbers.get("stacks", [])):
            missing.append("tool stickout and headroom")
        if missing:
            lines.append(unknown + "; ".join(missing) + ".")
        html = "<h2>CLEARANCE — mill</h2>" + "".join(_p(line) for line in lines)
        if rows:
            html += _table(
                ["op", "tool", "closest obstacle", "clearance mm", "action"],
                rows,
                css="clearance",
                widths=[9, 6, 45, 11, 29],
            )
        # One block: the pagination moves the whole section rather than leave its travel
        # lines on one page and its table on the next.
        return f'<div class="keep">{html}</div>'

    def clearance_rows(self, setup, numbers, tool_numbers):
        """One row per cutting op (ops sharing a tool, obstacle, clearance and action share
        a row): the smallest known clearance among the head travel left above the work
        (headroom ``margin_mm``), the jaw tops (``cut_tip_above_jaws_mm``, as the op row's
        box measures it), the holder face above the highest stock beside the tool, any
        reach ``clearances`` entry and the holding solid nearest the op's cut
        (:meth:`cut_clearance`, a hand-feed check within the crash zone); an unknown one or
        an unproven wall clearance is the action. Every Z printed is the surface's one DRO
        Z (:meth:`surface_z`)."""
        o = self.operative
        stacks = {str(s.get("op")): s for s in numbers.get("stacks", []) if isinstance(s, dict)}
        tips = _mapping(numbers.get("cut_tip_above_jaws_mm"))
        jaw = _mapping(numbers.get("jaw_obstruction")).get("jaw_top_z")
        merged = {}
        for op in setup.get("ops", []):
            name = str(op.get("op"))
            if op.get("do") in MANUAL or op.get("tool") in (None, "unknown"):
                continue
            candidates, actions = [], []
            margin = _mapping(stacks.get(name)).get("margin_mm")
            if _known(margin):
                candidates.append((margin, "spindle-to-table room spare, tool change allowed"))
            planned = tips.get(name, tips.get(op.get("op")))
            if _known(planned):
                # The op row's own jaw box number: its DRO tip over the jaw tops.
                tip = self.dro_to_z(setup, op)
                value = tip - jaw if _known(tip) and _known(jaw) else planned
                candidates.append((value, "jaw tops below the tool tip"))
                if min(planned, value) < 0:
                    actions.append("STOP: the tip goes below the jaw tops")
                elif planned <= _CRASH_ZONE_MM:
                    actions.append("hand feed; check the tip clears the jaws before plunging")
            self.reach_candidates(setup, op, candidates, actions)
            cut = self.cut_clearance(setup, op)
            if cut is not None:
                beside = f"{cut[1]} beside the cut"
                candidates.append((cut[0], beside))
            known = [c for c in candidates if _known(c[0])]
            actions.extend(
                f"{what}: not computed — check at the machine"
                for value, what in candidates
                if value is not None and not _known(value)
            )
            noted = [what for value, what in candidates if value is None]
            if known:
                value, what = min(known, key=lambda c: c[0])
            elif noted:
                value, what = "—", noted[0]
            elif actions:
                value, what = "?", "—"
            else:
                continue
            if cut is not None and _known(cut[0]) and cut[0] <= _CRASH_ZONE_MM:
                # Named with its distance when another obstacle is the row's closest.
                near = cut[1] if what == beside else f"{cut[1]} ({o(cut[0])} mm)"
                actions.append(f"hand feed past the {near}; check the cutter clears it")
            if _known(value) and value < 0 and not any(a.startswith("STOP") for a in actions):
                actions.append("STOP: does not clear")
            tool = tool_numbers.get((op.get("tool"), op.get("holder")), "")
            printed = o(value) if _known(value) else value
            key = (tool, what, printed, "; ".join(dict.fromkeys(actions)))
            merged.setdefault(key, []).append(name)
        return [
            (", ".join(ops), tool, what, value, action)
            for (tool, what, value, action), ops in merged.items()
        ]

    def reach_candidates(self, setup, op, candidates, actions):
        """The reach finding's clearances for ``op``: the holder face above the highest stock
        beside the tool (the kernel's ``reach_top_z_mm`` as its DRO surface Z, down to the
        op row's printed tip, against the tool's projection), a holder whose face goes below
        that stock with its wall clearance proven or not, and every declared ``clearances``
        entry (``part``, ``obstacle``, ``mm``)."""
        o = self.operative
        record = _mapping(self.records.get(("reach", f"{setup['id']}:{op.get('op')}")))
        if not record:
            return
        _, tip = self.cut_span(setup, op)
        top = record.get("reach_top_z_mm")
        if _known(top):
            top = self.kernel_z(setup, top)
        # The printed Zs are plan units; projection and flute length are millimetres.
        scale = {"mm": 1.0, "in": 25.4}.get(self.units)
        reach = (
            (top - tip) * scale
            if _known(top) and _known(tip) and scale
            else record.get("reach_depth_mm")
        )
        projection, hits = record.get("projection_mm"), record.get("holder_wall_hits")
        flute = record.get("flute_len_mm")
        beside = (
            f"stock top beside the tool (Z {o(top)})" if _known(top) else "stock beside the tool"
        )
        for entry in record.get("clearances") or []:
            entry = _mapping(entry)
            what = f"{self.bench(entry.get('part', 'tool'))} to {self.bench(entry.get('obstacle'))}"
            if _known(entry.get("z_mm")):
                what += f" at Z {o(self.kernel_z(setup, entry['z_mm']))}"
            candidates.append((entry.get("mm", "unknown"), what))
        if top == "not_applicable":
            # No stock stands beside the tool above its tip.
            return
        if not (_known(reach) and _known(projection)):
            candidates.append(("unknown", f"holder face to the {beside}"))
            return
        above = projection - reach
        if above >= 0:
            candidates.append((above, f"holder face to the {beside}"))
        elif hits == 0:
            candidates.append(
                (None, f"holder goes {o(-above)} below the {beside}; checked clear of the walls")
            )
        else:
            candidates.append(("unknown", f"holder {o(-above)} below the {beside}, to the walls"))
        past = _known(flute) and reach > flute + SAME_Z
        if past and _known(hits) and hits > 0:
            actions.append("STOP: the holder hits a wall beside the cut")
        elif past and not _known(hits):
            actions.append("holder clearance of the walls not proven — check at the machine")

    def cut_span(self, setup, op):
        """(start Z, tip Z) of ``op`` as its op row prints them (:meth:`tip`); a start the
        row does not print is None, an unknown stays unknown."""
        endpoint = self.endpoint(setup, op)
        if endpoint:
            return endpoint.get("dro_entry_z", "unknown"), endpoint.get("dro_tip_z", "unknown")
        levels = self.z_levels(setup, op)
        if levels is not None:
            return levels.get("dro_start_z", "unknown"), levels.get("dro_to_z", "unknown")
        if "z_from" in op and "z_to" in op:
            return self.op_z(setup, op, "z_from"), self.op_z(setup, op, "z_to")
        if "to_z" in op:
            return None, self.dro_to_z(setup, op)
        return None, "unknown"

    def lathe_approaches(self, setup):
        """Distance from each op's last planned Z to the jaw fronts (exposed side +Z); a
        blade's own chuck-side face (accessibility ``blade_z_mm``) counts, not just the
        Z its op names."""
        jaw = self.jaw_front_z(setup)
        result = {}
        if jaw is None:
            return result
        for op in setup.get("ops", []):
            if op.get("do") in MANUAL:
                continue
            zs = self.path_zs(setup, op)
            numbers = _mapping(self.records.get(("accessibility", f"{setup['id']}:{op['op']}")))
            blade = numbers.get("blade_z_mm")
            if zs and isinstance(blade, list) and blade and all(_known(z) for z in blade):
                # Millimetre kernel fact; down-rounded so the jaw gap is never overstated.
                face = self.mm_on_grid(setup, min(blade), up=False)
                zs = [*zs, face] if _known(face) else zs
            if zs:
                result[str(op["op"])] = min(zs) - jaw
        return result

    def posed_start(self, setup, op):
        """The kernel's pose of a turning op at its start (accessibility ``window_poses``)
        when a fixture component is within the crash zone of it: the clearance, and how
        far out the start may go when that was found; None otherwise. The start prints as
        the DRO shows it (:meth:`surface_z`), off the posed one by the grid rounding: the
        clearance loses that offset when it is outward (back against the feed), and a
        printed start at or past the checked limit, or with no clearance left, is a STOP."""
        numbers = _mapping(self.records.get(("accessibility", f"{setup['id']}:{op['op']}")))
        o = self.operative
        scale = {"mm": 1.0, "in": 25.4}.get(self.units)
        for pose in numbers.get("window_poses") or []:
            pose = _mapping(pose)
            clear, z = pose.get("clearance_mm"), op.get("z_from")
            if pose.get("end") != "z_from" or not _known(clear) or clear > _CRASH_ZONE_MM:
                continue
            # The kernel names a placed component "<role> <inventory ref>"; print the shop
            # name of the ref when it is one, else the component as named.
            name = str(pose.get("nearest_fixture"))
            ref = name.rsplit(" ", 1)[-1]
            if resolve(self.bundle, "fixtures", ref):
                name = "the " + self.short_reference(ref, "fixtures")
            planned, posed = self.surface_z(setup, z), pose.get("z_mm")
            start, feed = pose.get("max_start_z_mm"), numbers.get("feed_z")
            out = -feed if feed in (-1, 1) else None
            if out is None and _known(start) and _known(posed) and start != posed:
                out = 1 if start > posed else -1
            moved = planned * scale - posed if _known(planned) and scale and _known(posed) else 0
            clear -= max(0.0, moved * out if out else abs(moved))
            limit = "unknown"
            if _known(start) and _known(z):
                # Toward the planned start: never further out than the found limit.
                limit = self.mm_on_grid(setup, start, up=start < pose.get("z_mm", start))
            past = _known(limit) and out and (planned * scale - start) * out > -1e-9
            if clear <= 0 or past:
                stop = f"STOP: START Z {o(planned)} is not checked clear of {name}"
                if _known(limit):
                    stop += f": the checked start is no further out than Z {o(limit)}"
                return _Box(stop)
            gap = self.mm_on_grid(setup, clear, up=False)
            text = f"START Z {o(planned)}: {o(gap)} CLEAR OF {name}"
            if _known(limit):
                text += f" — start no further out than Z {o(limit)}"
            return _Box(text)
        return None

    def mm_on_grid(self, setup, value, up):
        """A millimetre kernel fact in plan units on the setup's DRO grid, rounded up (True)
        or down (False); unknown when the value or the plan units are."""
        scale = {"mm": 1.0, "in": 25.4}.get(self.units)
        if scale is None or not _known(value):
            return "unknown"
        step, decimals = dro_grid(self.bundle, setup)
        steps = (math.ceil if up else math.floor)(value / scale / step + (-1e-6 if up else 1e-6))
        return round(steps * step, decimals)

    def rest_steps(self, setup, op):
        """(coordinate cells, full-width lines) for each follow rest serving the op.

        Where the op's start would foul a rest (``engage_at_z_mm``), its cell prints that Z
        on the DRO grid toward the clear side (along the feed), rechecked as printed: past
        the Z where the jaws clear the fixture and not past the op's end; a declared Z with
        no clearance check is a STOP, never the lead. The pass sequence
        prints once, full width: hands set the jaws only once the feed and then the spindle
        have stopped, and the spindle runs again before the feed resumes. Trailing jaws (on
        the diameter just turned) are backed off at every pass end before the tool withdraws
        and the carriage returns, since the return carries them back past the pass start by
        their lead onto stock the pass never cut; leading jaws return over the smaller cut
        diameter. A rest whose side or lead is not known prints a STOP, never a return."""
        numbers = _mapping(self.records.get(("accessibility", f"{setup['id']}:{op['op']}")))
        feed, end = numbers.get("feed_z"), op.get("z_to")
        scale = {"mm": 1.0, "in": 25.4}.get(self.units)
        supports = _mapping(setup.get("hold")).get("supports")
        engagements = {}
        for entry in map(_mapping, numbers.get("rest_engagement") or []):
            if _known(entry.get("declared_z_mm")):
                engagements.setdefault(entry.get("rest"), entry)
        # The op's own follow-rest entries (a steady rest stands at ``at_z_mm``): one rest
        # may ride a different side in another op.
        applicable = [
            support
            for support in map(_mapping, supports if isinstance(supports, list) else [])
            if "at_z_mm" not in support
            and (
                {"jaw_lead_mm", "jaw_side", "engage_at_z_mm"} & support.keys()
                or support.get("ref") in engagements
            )
            and (not isinstance(support.get("ops"), list) or op.get("op") in support["ops"])
        ]
        rests = [(support.get("ref"), support) for support in applicable]
        named = {rest for rest, _ in rests}
        rests += [(rest, {}) for rest in engagements if rest not in named]
        cells, lines = [], []
        for rest, support in rests:
            side = support.get("jaw_side", "turned")
            lead = support.get("jaw_lead_mm") if support else None
            ridden = "uncut stock ahead of the tool" if side == "uncut" else "diameter just turned"
            entry = engagements.get(rest)
            on = None
            if entry is None and _known(support.get("engage_at_z_mm")):
                # A declared engage Z with no clearance check: the lead would contradict it.
                entry = {"declared_z_mm": support["engage_at_z_mm"]}
            if entry is not None:
                declared, clear = entry["declared_z_mm"], entry.get("engage_z_mm")
                printed = self.mm_on_grid(setup, declared, up=feed == 1)
                fits = (
                    feed in (-1, 1)
                    and _known(printed)
                    and _known(clear)
                    and (printed - clear / scale) * feed >= -1e-9
                    and (not _known(end) or (printed - end) * feed <= 1e-9)
                )
                if not fits:
                    cells.append(
                        _Box("STOP: no follow-rest position on the DRO grid is checked clear")
                    )
                    continue
                on = self.operative(printed)
                cells.append(f"follow rest on: Z {on}")
            if support and (side not in ("turned", "uncut") or not (_known(lead) and lead > 0)):
                lines.append(
                    _Box(
                        "STOP: the follow rest's jaw side or lead is not known — where its "
                        "jaws go on and come off each pass is not checked"
                    )
                )
                continue
            setting = (
                f"set the follow-rest jaws on the {ridden} and lock them; restart the "
                "spindle, then resume the feed"
            )
            if on is not None:
                line = (
                    "Follow rest, each pass: start with the jaws backed off; at Z "
                    f"{on}: stop the feed, then the spindle; {setting}."
                )
            elif side == "turned":
                line = (
                    "Follow rest, each pass: start with the jaws backed off; once the tool has "
                    f"turned {self.operative(lead)} mm, stop the feed, then the spindle; "
                    f"{setting}."
                )
            else:
                line = ""
            if side == "turned":
                line += (
                    " Pass end: stop the feed, then the spindle; back the follow-rest jaws off; "
                    "withdraw the tool along X; return the carriage to the pass start."
                )
            if line:
                lines.append(_Plain(line.strip()))
        return cells, lines

    def path_zs(self, setup, op):
        """The Z ends of an op's path as its op row prints them."""
        zs = [self.op_z(setup, op, k) for k in ("z_from", "z_to") if _known(op.get(k))]
        if _known(op.get("to_z")):
            zs.append(self.dro_to_z(setup, op))
        return [z for z in zs if _known(z)]

    def op_z(self, setup, op, key):
        """``op``'s ``key`` Z (``z_from``/``z_to``) on its feature's surface as the op that
        cut that feature before it left it (:meth:`surface_z`), read as a path end: a
        turning window cut before it never blanks it (:func:`operative_z` ``path``)."""
        done = self.ops_done(setup, before=op.get("op"))
        return self.surface_z(setup, op.get(key), face=op.get("feature"), done=done, path=True)

    @property
    def near_jaw_mm(self):
        """The shop's declared distance from spinning jaws inside which an op row carries
        its jaw clearance; without one, only the crash zone boxes a row."""
        near = _mapping(self.bundle.policy.get("numbers")).get("near_jaw_mm")
        return near if _known(near) else _CRASH_ZONE_MM

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
            elif gap is not None and gap <= self.near_jaw_mm:
                boxes.append(
                    _Box(
                        f"JAWS Z {o(jaw)}: {o(gap)} clear — disengage the feed early, "
                        "hand feed to the end"
                    )
                )
            tip = _mapping(setup.get("hold")).get("support_tip_mm")
            zs = self.path_zs(setup, op)
            start = self.posed_start(setup, op)
            if start is not None:
                boxes.append(start)
            elif isinstance(tip, list) and len(tip) == 3 and _known(tip[2]) and zs:
                gap = tip[2] - max(zs)
                if gap <= _CRASH_ZONE_MM:
                    boxes.append(_Box(f"DEAD CENTRE Z {o(tip[2])}: start clear of it"))
            return boxes
        cut = self.cut_clearance(setup, op)
        if cut is not None and _known(cut[0]) and cut[0] <= _CRASH_ZONE_MM:
            boxes.append(_Box(f"{cut[1].upper()} {o(cut[0])} mm FROM THE CUT — hand feed past it"))
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

    def cut_clearance(self, setup, op):
        """``(mm, name)``: how near the material ``op`` cuts comes to the holding, from the
        kernel's setup picture (its ``cut_clearances``; the picture dimensions the least of
        the setup's), and the holding solid it is, as the HOLD names it
        (:meth:`holding_name`); ``unknown`` where the kernel could not derive the cut or the
        holding is not drawn whole; None when the kernel measured nothing for the op (no
        picture, or no cut)."""
        render = _mapping(_mapping(self.report.get("renders")).get(setup["id"]))
        for row in _mapping(render.get("scene")).get("cut_clearances") or []:
            row = _mapping(row)
            if str(row.get("op")) == str(op.get("op")):
                tag = row.get("tag")
                known = isinstance(tag, str) and tag != "unknown"
                name = self.holding_name(setup, tag) if known else "holding"
                return row.get("mm", "unknown"), name
        return None

    def holding_name(self, setup, tag):
        """A kernel holding solid's tag (``"<owner>:<solid>"``) as the HOLD names it: a
        ``hold.clamps`` entry ``clamp <i> <ref>`` by its label and solid (``LOC2 collar``),
        any other by its solid's own name."""
        owner, _, solid = str(tag).rpartition(":")
        solid = solid.replace("-", " ").replace("_", " ")
        match = re.fullmatch(r"clamp (\d+) .+", owner)
        labels = clamp_labels(_mapping(setup.get("hold")))
        if match and 0 < int(match.group(1)) <= len(labels):
            return f"{labels[int(match.group(1)) - 1]} {solid}"
        return solid

    # ------------------------------------------------------------------ DRO
    def transfer_line(self, setup, transfer):
        """The datum transfer before zeroing: a lathe part tapped true; one round feature
        centred on by moving the table; surfaces aligned by moving the work. A hold that
        must stay clamped (``keep_clamped``) is never loosened or tapped: a sweep over the
        limit follows the plan's ``recovery``, and without one the transfer is a STOP."""
        indicate = transfer.get("indicate")
        items = indicate if isinstance(indicate, list) else [indicate]
        features = ", ".join(self.feature_name(f) for f in items)
        gauge = transfer.get("tool", transfer.get("gauge"))
        limit = transfer.get("runout_limit_mm")
        # A limit is never rounded: 0.0254 printed as 0.03 would loosen it.
        reading = f"{_number(limit)} mm total indicator reading"
        with_gauge = " with the " + self.reference(gauge) if gauge not in (None, "unknown") else ""
        recovery = transfer.get("recovery")
        recovery = recovery.strip() if isinstance(recovery, str) and recovery != "unknown" else ""
        clamped = transfer.get("keep_clamped") is True
        centring = not self.lathe(setup) and self.centring(items)
        if not _known(limit):
            line = (
                f"Before zeroing: indicate the {features}{with_gauge}; runout limit not set "
                "— ? confirm the allowed runout"
            )
        elif clamped and not recovery:
            line = (
                f"STOP: the {features} must read {reading} or less with the work left "
                "clamped, and no recovery is planned for a sweep that reads more"
            )
        elif clamped and centring:
            # Centring moves the table, never the work; the recovery is for a sweep that
            # no table move brings within the limit.
            line = (
                f"Before zeroing: centre on the {features}{with_gauge}, swept all round; move "
                f"the table until the sweep reads {reading} or less, then re-check. Do not "
                f"loosen the work; if no table move brings it within that: "
                f"{self.bench(recovery, setup)}"
            )
        elif clamped:
            line = (
                f"Before zeroing: check the work on the {features}{with_gauge}"
                + (
                    ""
                    if self.lathe(setup)
                    else ": run the indicator along the length of each surface by table travel"
                )
                + f"; it must read {reading} or less. Do not loosen the work to correct it; "
                f"if it reads more: {self.bench(recovery, setup)}"
            )
        elif self.lathe(setup):
            line = f"Before zeroing: indicate the {features}{with_gauge}; tap true to {reading}"
            line += " or less"
        elif centring:
            # One round feature: the table is moved to put the spindle on its axis.
            line = (
                f"Before zeroing: centre on the {features}{with_gauge}, swept all round; move "
                f"the table until the sweep reads {reading} or less, then re-check"
            )
        else:
            # Surfaces: the sweep checks the work's alignment; the work moves, not the table.
            line = (
                f"Before zeroing: align the work on the {features}{with_gauge}: run the "
                f"indicator along the length of each surface by table travel; while it reads "
                f"more than {reading}, loosen the clamping, tap the high end of the work toward "
                "the low reading, re-clamp and sweep again"
            )
        if transfer.get("reindicate_after"):
            line += f". After {_ops_label(transfer['reindicate_after'])}: re-indicate and redo X/Y"
        return re.sub(r"\.+$", "", line)

    def centring(self, items):
        """True when a transfer indicates one round feature (a hole, bore or boss, or a
        named non-feature such as a pin head): the sweep goes all round it and the table
        centres on it. Surfaces, or several features, are an alignment instead."""
        if len(items) != 1:
            return False
        definition = self.features.get(items[0])
        if not isinstance(definition, dict):
            return True
        kind = str(definition.get("kind", ""))
        return kind == "hole" or "bore" in kind or kind in ("boss", "cylinder_spigot")

    def dro(self, setup, tools):
        if saw_setup(setup):
            # The saw cut is located by its cut plane in the op row: no zero to set.
            return None
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
                        f"{k.upper()}+ {self.positive_direction(k, v, lathe)}"
                        for k, v in directions.items()
                        if not self.metadata(k) and not (lathe and k == "y")
                    )
                    + ". Axis Set each axis (never Preset), then "
                    + ("jog without touching" if lathe else "make the check jog")
                    + ": the display must show 'must read'; 'if reversed' means STOP, fix "
                    "the axis direction and redo the zero."
                )
            )
        # Executed order: the part is indicated true (or aligned) before any tool touches it.
        transfer = _mapping(authored.get("transfer"))
        if transfer:
            pieces.append(_p(self.transfer_line(setup, transfer) + "."))
        axes = numbers.get("axes", {})
        # Each toolpost tool is set on centre (a blade also squared) before its first
        # touch-off in the setup: the zero's tools before the zero, the rest before theirs.
        settings_at = {
            (record.get("touch"), record.get("axis", record.get("index"))): record
            for record in numbers.get("tool_setting", [])
            if isinstance(record, dict)
        }
        for axis in ("x", "z"):
            if ("zero", axis) in settings_at:
                pieces.append(_p(self.tool_setting(settings_at[("zero", axis)], tools)))
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
            indicate = method == "indicate_axis" or touch.get("from") == "indicated"
            tool = None
            if "tool" in touch:
                tool = (
                    "? tool not chosen"
                    if touch["tool"] in (None, "unknown")
                    else tools.get(touch["tool"]) or self.short_reference(touch["tool"])
                )
            if indicate:
                contact.append(self.indicate_recipe(setup, axis, target, authored, tool))
            elif method not in (None, "paper", "touch"):
                contact.append(_METHODS.get(method, _text(method)))
            if tool and not indicate:
                contact.append(tool)
            if _CORNERS.get(computed.get("reference_corner")):
                corner = _CORNERS[computed["reference_corner"]]
                contact.append(f"{corner} corner — Z reads it")
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
            measured = method in {"trial_cut_measure", "face_then_set", "measure_then_set"}
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
            before_hold = touch.get("measure_before_hold") is True and touch.get("measure")
            if touch.get("gauge") and not before_hold:
                contact.append("measure with " + self.short_reference(touch["gauge"], "gauges"))
            if before_hold:
                # The HOLD measured M before clamping (:meth:`bench_measures`).
                contact.append("M measured before clamping (HOLD)")
            elif touch.get("measure"):
                contact.append("M = " + self.bench(touch["measure"]))
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
                    "check jog",
                    "must read",
                    "if reversed",
                ],
                rows,
                widths=[5, 45, 13, 11, 13, 13],
            )
        )
        if not lathe and any(row[0] in ("X", "Y") for row in rows):
            # From a side pickup, +X / +Y runs the finder over the work at pickup height.
            pieces.append(
                _p("X and Y check jog, after each Axis Set:")
                + _list(
                    [
                        "raise Z only (X and Y stay put) until the edge finder or indicator tip "
                        "is above the work and everything clamped to it — look across the top "
                        "for daylight under the tip;",
                        "jog the table the check-jog distance and read 'must read';",
                        "jog back until the display shows the Axis Set value again, then lower; "
                        "do not Axis Set again: the picked-up value stays.",
                    ],
                    ordered=True,
                )
            )
        correction = self.measured_top(setup)
        if correction:
            pieces.append(_p(correction))
        retouches = {}
        tops = {
            str(op["op"]): after["top_from"] for op, _, after in stock_states(self.bundle, setup)
        }
        surface = self.feature_name(top_feature) if top_feature else "the top"
        for record in numbers.get("retouch", []):
            # The top as the op that last faced it left it, else as the DRO shows it.
            top = self.surface_z(
                setup, record.get("top_z"), tops.get(str(record.get("op"))), face="top"
            )
            paper = record.get("paper_mm")
            axis_set = top + paper if _known(top) and _known(paper) else "unknown"
            key = (o(top), o(paper), o(axis_set))
            retouches.setdefault(key, []).append(record)
        for (top, paper, axis_set), records in retouches.items():
            touch = f"touch {surface} (Z {top}) with {paper} paper → Axis Set Z {axis_set}."
            changes = []
            for record in records:
                after, served = _text(record.get("op")), record.get("next_op")
                incoming = record.get("next_tool")
                name = tools.get(incoming) or self.short_reference(incoming)
                if record.get("tool_change") is True:
                    changes.append((after, name, _text(served)))
                elif record.get("tool_change") is False and _known(served):
                    # The tool that cut stays in: no tool change, only the touch.
                    pieces.append(
                        _p(f"After op {after}, {name} stays in for op {_text(served)}: re-{touch}")
                    )
                elif _known(served):
                    pieces.append(
                        _p(
                            f"After op {after}, install the op {_text(served)} tool (not known), "
                            f"then {touch}"
                        )
                    )
                else:
                    pieces.append(_p(f"After op {after}: {touch}"))
            if len(changes) == 1:
                after, name, served = changes[0]
                pieces.append(_p(f"After op {after}, install {name} for op {served}, then {touch}"))
            elif changes:
                pieces.append(
                    _p(
                        "Tool changes: after each op below, install the tool it names, "
                        f"then {touch}"
                    )
                    + _list(
                        [f"after op {a}: install {n} for op {s}" for a, n, s in changes],
                        ordered=False,
                    )
                )
        for kind in ("tool_touches", "derived_touches"):
            for index, touch in enumerate(numbers.get(kind, [])):
                if (kind, index) in settings_at:
                    pieces.append(_p(self.tool_setting(settings_at[(kind, index)], tools)))
                pieces.append(_p(self.tool_touch(setup, touch, tools)))
        for gap in numbers.get("missing_touches", []):
            name = tools.get(gap.get("tool")) or self.short_reference(gap.get("tool"))
            missing = " and ".join(_text(axis).upper() for axis in gap.get("axes", []))
            pieces.append(
                _p(
                    f"STOP: before op {_text(gap.get('before_op'))}, {name} has no {missing} "
                    "touch — the DRO reads another tool. Plan a tool touch."
                )
            )
        for record in axes.values():
            if record.get("note"):
                pieces.append(_p(self.bench(record["note"])))
        return "".join(pieces)

    def measured_top(self, setup):
        """A mill Z zero set from a bench-measured M on the raw top (``measure_then_set`` on
        face ``top``) puts that top at Z = M + offset, while the ops' levels start from the
        declared stock top. A higher top is faced down to the declared top first, never
        deeper per pass than the setup's shallowest declared ``doc_mm``: the cap is the
        plan's, not prose, in plan units rounded down onto the DRO grid so the printed cap
        never exceeds it. Empty for any other zero."""
        touch = _mapping(_mapping(setup.get("zero")).get("z"))
        if self.lathe(setup) or touch.get("method") != "measure_then_set":
            return ""
        if touch.get("face") != "top":
            return ""
        o = self.operative
        offset, top = touch.get("offset_mm"), _mapping(setup.get("stock_state")).get("top_z")
        if not (_known(offset) and _known(top)):
            return "STOP: the measured top's Z is not set — offset_mm or stock top unknown."
        raw = "M" if not offset else f"M {'−' if offset < 0 else '+'} {_number(abs(offset))}"
        docs = [
            op["doc_mm"]
            for op in setup.get("ops", [])
            if _known(op.get("doc_mm")) and op["doc_mm"] > 0
        ]
        scale = {"mm": 1.0, "in": 25.4}.get(self.units)  # doc_mm is mm; levels are plan units
        least = self.mm_on_grid(setup, min(docs), up=False) if docs and scale else None
        if not docs:
            cap = "? per pass: no op sets doc_mm"
        elif scale is None:
            cap = "? per pass: plan units unknown"
        elif least <= 0:
            cap = f"? per pass: the least doc_mm {_number(min(docs))} is under one DRO step"
        else:
            cap = f"no more than {o(least)} per pass"
        return (
            f"M puts the raw top at Z = {raw}; the ops' levels start from Z {o(top)}. If "
            f"{raw} is above Z {o(top)}, first face the top down to Z {o(top)}, {cap}."
        )

    def reading(self, value, expression=None):
        """DRO readings; a measured-diameter expression reads as plain arithmetic."""
        if _known(value):
            return self.operative(value)
        text = value if isinstance(value, str) and value != "unknown" else expression
        if not isinstance(text, str) or text == "unknown":
            return "?"
        match = re.fullmatch(r"(?:measured\s+)?(D/2|D|M)\s*([+-])\s*(\d+(?:\.\d+)?)", text.strip())
        if match:
            sign = "+" if match[2] == "+" else "−"
            subject = {"D": "measured Ø", "D/2": "measured Ø/2", "M": "M"}[match[1]]
            return f"{subject} {sign} {self.operative(float(match[3]))}"
        return "measured Ø" if text.strip() == "measured D" else self.bench(text)

    def tool_setting(self, record, tools):
        """The step that sets a toolpost tool before its first touch-off (zero_check
        ``tool_setting``): on centre height, and a blade squared to the spindle axis."""
        reference = record.get("tool")
        name = tools.get(reference) or self.short_reference(reference)
        text = f"Before touching off {name}: {self.bench(record.get('centre_height'))}"
        square = record.get("square_blade")
        if square not in (None, "not_applicable"):
            text += f"; then {self.bench(square)}"
        return text + "."

    def tool_touch(self, setup, touch, tools):
        reference = touch.get("tool")
        name = tools.get(reference) or self.short_reference(reference)
        before = touch.get("before_ops")
        when = f"Before {_ops_label(before if isinstance(before, list) else [before])}"
        if touch.get("after_op") not in (None, "unknown"):
            when += f" (after op {_text(touch['after_op'])})"
        # A derived touch repeats one the setup already made, for the tool coming in. A
        # mill spindle holds one tool: the incoming one goes in before it touches.
        verb = "re-touch" if "repeats" in touch else "touch off"
        if self.lathe(setup):
            parts = [f"{when}, {verb} {name}:"]
        else:
            parts = [f"{when}, install {name}, then {verb} it:"]
        if touch.get("x_method") or touch.get("x_face"):
            gauge = touch.get("gauge")
            x_face = touch.get("x_face")
            surface = (
                "the X-zero trial-cut land"
                if x_face == "x_zero"
                else f"the {self.feature_name(x_face)} Ø"
            )
            # The contact the Axis Set counts always prints, whatever the author's words
            # say: the surface, measured, and the paper between (a trial cut is its own
            # surface and takes none). A repeat drops the words its source was made with.
            words = touch.get("x_method") if "repeats" not in touch else None
            how = self.bench(words) if words else None
            paper = touch.get("x_paper_mm")
            contact = f"on {surface}, measured"
            if words != "trial_cut_measure":
                contact += ", " + (
                    ("paper " + self.operative(paper) if paper else "no paper")
                    if _known(paper) and paper >= 0
                    else "paper ?"
                )
            elif x_face is None:
                contact = None
            gauge_words = f" ({self.short_reference(gauge, 'gauges')})" if gauge else ""
            if contact is None:
                text = f"X — {how}{gauge_words}"
            else:
                text = f"X — {contact}{gauge_words}" + (f": {how}" if how else "")
            if touch.get("x_axis_set", "not_applicable") != "not_applicable":
                text += f"; Axis Set X {self.reading(touch.get('x_axis_set'))}"
            if touch.get("x_face_status") in ("error", "unknown"):
                # zero_check x_face_status: D2, the zero is set on the diameter touched.
                text += (
                    ". STOP: the diameter this X touch measures is not shown standing here "
                    "— plan the touch on one that is"
                )
            parts.append(text + ".")
        z_face = touch.get("z_face")
        if z_face:
            paper = touch.get("paper_mm")
            edge = touch.get("edge_mm")
            axis_set = touch.get("z_axis_set", edge)
            surface = "unknown"
            if _known(edge) and _known(axis_set):
                # The touched face as the DRO shows it when this tool comes in.
                done = self.ops_done(setup, before=touch.get("before_ops"))
                surface = self.datum_z(setup, z_face, edge, done)
                axis_set = axis_set + surface - edge if _known(surface) else "unknown"
            method = re.sub(r";?\s*Axis Set Z\.?$", "", str(touch.get("method", "touch")))
            # A blade's Z touch sets one corner (zero_check ``reference_corner``): named.
            corner = _CORNERS.get(touch.get("reference_corner"))
            blade = "reference_corner" in touch
            words = _METHODS.get(method, self.bench(method))
            text = f"Z — on the {self.bench(z_face)}"
            if corner:
                text = f"Z — {corner} corner on the {self.bench(z_face)}"
                words = words.replace("this tool's Z-cutting edge", f"this blade's {corner} corner")
            if "repeats" in touch and _known(surface):
                text += f" (Z {self.operative(surface)})"
            text += f": {words}"
            if touch.get("z_measure"):
                gauge = touch.get("z_gauge")
                text += f", M = {self.bench(touch['z_measure'])}" + (
                    f" ({self.short_reference(gauge, 'gauges')})" if gauge else ""
                )
            if _known(paper):
                text += f", paper {self.operative(paper)}" if paper else ", no paper"
            text += f"; Axis Set Z {self.reading(axis_set)}"
            if corner:
                text += f": Z now reads the {corner} corner"
            elif blade:
                text += ". STOP: which blade corner this touch sets is not known — plan it"
            parts.append(text + ".")
        return " ".join(parts)

    # -------------------------------------------------------------- features
    def feature_map(self, setup):
        if saw_setup(setup):
            return ""
        numbers = self.records.get(("coordinates", setup["id"]), {})
        display = numbers.get("x_display")
        lathe = "x_display" in numbers or self.lathe(setup)
        # The size each surface turns to, as the DRO's X display reads it; unread, the
        # surface still lists with its drawing limits and Zs, its X withheld.
        turned = {"diameter": ("turn to Ø", "Ø"), "radius": ("turn to X (radius)", "")}
        heading, prefix = turned.get(display, ("turn to X", None))
        o = self.operative
        grouped = {}
        aims = []
        # A lathe map gives the size each surface is turned to and the Zs its cuts run
        # between: a surface this setup only inspects (an as-supplied diameter) has none.
        cut = {op.get("feature") for op in setup.get("ops", []) if op.get("do") not in MANUAL}
        for record in numbers.get("rows", []):
            feature = record.get("feature")
            # A mill target prints where the DRO stops: on its grid, aims applied.
            coordinates = record.get("dro", record.get("setup"))
            if not isinstance(coordinates, (list, tuple)) or len(coordinates) != 3:
                continue
            if lathe:
                x = record.get("x_target_mm")
                size = x if prefix is not None else record.get("dia_nominal")
                if feature not in cut or not _known(size) or not _known(coordinates[2]):
                    continue
                # Its ends as its ops print them: cut before its first op (:meth:`op_z`).
                first = [
                    op.get("op") for op in setup.get("ops", []) if op.get("feature") == feature
                ]
                done = self.ops_done(setup, before=first)
                entry = grouped.setdefault(feature, {"dia": x, "z": [], "done": done})
                entry["z"].append(coordinates[2])
            elif all(_known(v) for v in coordinates):
                grouped.setdefault((feature, tuple(coordinates)), {})
                aims.append(self.aim_note(record))
        if not grouped:
            return ""
        if lathe:
            # Each surface's Z ends as the DRO shows them, as the op rows print them; the
            # drawing's own limits (a drawing feature only) apart from the size turned to.
            drawing = _mapping(self.bundle.features.get("features"))
            rows = []
            for feature, entry in grouped.items():
                band = _mapping(drawing.get(feature)).get("dia")
                drawn = "—"
                if isinstance(band, list) and len(band) == 2 and all(map(_known, band)):
                    drawn = "Ø" + self.band(band, feature, "dia")
                rows.append(
                    (
                        self.feature_name(feature),
                        drawn,
                        "?" if prefix is None else prefix + o(entry["dia"]),
                        *(
                            o(self.surface_z(setup, z, face=feature, done=entry["done"], path=True))
                            for z in (max(entry["z"]), min(entry["z"]))
                        ),
                    )
                )
            table = _table(
                ["feature", "drawing Ø limits", heading, "cut from Z", "cut to Z"],
                rows,
                widths=[32, 17, 17, 17, 17],
            )
            if prefix is None:
                table += _p(_X_DISPLAY_STOP + ".", "stop")
            note = (
                {"diameter": "X reads diameter. ", "radius": "X reads radius. "}.get(display, "")
                + "Z values are where this setup's cuts on each surface start "
                "and end, not the finished extent: a later cut (relief, part-off, next setup) "
                "may shorten the surface."
            )
            if any(row[1] == "—" for row in rows):
                note += " A dash in the drawing column: a process size the drawing does not give."
        else:
            rows = [
                (
                    self.feature_name(feature),
                    self.reference_point(setup, feature, c[2]),
                    o(c[0]),
                    o(c[1]),
                    o(c[2]),
                )
                for (feature, c) in grouped
            ]
            table = _table(
                ["feature", "reference point", "X", "Y", "Z"], rows, widths=[26, 38, 12, 12, 12]
            )
            note = "The op table gives the tool targets."
            note += "".join(f" {text}" for text in dict.fromkeys(filter(None, aims)))
        return f"<h2>FEATURE MAP — {escape(self.zero_name(setup))}</h2>" + table + _p(note)

    def reference_point(self, setup, feature, z):
        """What a feature-map row's X / Y / Z stand on, from the feature's own kind: an arc
        centre, a hole or boss axis, a face; on a hole, the entry or exit face its op rows
        print at that Z, or the Z0 surface."""
        definition = _mapping(self.features.get(feature))
        kind = str(definition.get("kind", ""))
        if definition.get("arc"):
            name = "arc centre"
        elif "bore" in kind or kind == "hole":
            name = "hole axis"
        elif kind in ("boss", "cylinder_spigot"):
            name = "boss axis"
        elif kind == "face":
            name = "face"
        else:
            name = kind.replace("_", " ") or "point"
        o = self.operative
        for op in setup.get("ops", []):
            if op.get("feature") != feature:
                continue
            endpoint = self.endpoint(setup, op) or {}
            for key, face in (("dro_entry_z", "entry face"), ("dro_exit_face", "exit face")):
                if _known(endpoint.get(key)) and o(endpoint[key]) == o(z):
                    return f"{name} at the {face}"
        if _known(z) and o(z) == o(0.0):
            return f"{name} on the Z0 surface"
        return name

    def aim_note(self, record):
        """A located target moved off its drawing nominal (plan ``aims``): the target, the
        intentional offset and the dimension to inspect; empty for an unaimed target. The
        aim's authored reason stays in the plan."""
        aim = record.get("aim") or {}
        nominal = record.get("nominal_setup")
        if "shift_mm" not in aim or not isinstance(nominal, list):
            return ""
        # An inherited aim is the parent's: name it, and its value in manifest units.
        feature, source = aim["feature"], aim["source"]
        requirement = aim["requirement"]
        o = self.operative
        moved = ", ".join(
            f"{axis} {o(target)}, {o(abs(target - drawn))} off the drawing nominal {o(drawn)}"
            for axis, target, drawn in zip("XYZ", record["dro"], nominal, strict=True)
            if o(target) != o(drawn)
        )
        return (
            f"{self.feature_name(feature).capitalize()}: machine at {moved} — intentional; "
            f"inspect its {_REQUIREMENT_NAMES.get(requirement, requirement)} from the "
            f"{self.feature_name(source)} to {self.band(aim['printed_band'], feature, requirement)}"
            f" (aimed at {_number(aim['value'])})."
        )

    # ------------------------------------------------------------------ tools
    def tool_table(self, setup):
        """T-numbers in first-use order, one per tool + holder pair. A lathe's holders stay
        on its toolpost between setups, so there a pair keeps one number on every setup
        that machine runs (first use over the plan)."""
        setups = (
            [s for s in self.plan.get("setups", []) if s.get("machine") == setup.get("machine")]
            if self.lathe(setup)
            else [setup]
        )
        fixed = {}
        for each in setups:
            for op in each.get("ops", []):
                if op.get("do") in MANUAL or op.get("tool") in (None, "unknown"):
                    continue
                fixed.setdefault((op["tool"], op.get("holder")), f"T{len(fixed) + 1}")
        numbers, rows = {}, {}
        for op in setup.get("ops", []):
            reference = op.get("tool")
            if op.get("do") in MANUAL or reference in (None, "unknown"):
                continue
            key = (reference, op.get("holder"))
            if key not in numbers:
                numbers[key] = fixed[key]
                holder = op.get("holder")
                rows[key] = [
                    numbers[key],
                    self.tool_name(reference),
                    ", ".join(self.tool_detail(reference, holder)) or "—",
                    self.short_reference(holder, "holders")
                    if holder not in (None, "unknown", "not_applicable")
                    else "—",
                    [],
                ]
            rows[key][4].append(str(op["op"]))
        rows = sorted(rows.values(), key=lambda row: int(row[0][1:]))
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
        if endpoint and endpoint.get("depth_scale") == "quill":
            # A tailstock centre drill is fed by the quill: its depth is read on the quill
            # scale from touching the work, never as a carriage DRO Z.
            depth = endpoint.get("depth_mm")
            if not _known(depth):
                return ["quill depth not set", _Box("STOP: centre depth unknown")]
            return [f"quill {o(depth)} past touching the end"]
        if endpoint:
            # A hole op prints its endpoint as the DRO shows it (blind_depth's dro_* values).
            entry = endpoint.get("dro_entry_z")
            parts = [f"Z {o(entry)} → {o(endpoint.get('dro_tip_z'))}"]
            if endpoint.get("exit_face", "not_applicable") != "not_applicable":
                parts.append(f"breaks through at {o(endpoint.get('dro_exit_face'))}")
                left = endpoint.get("dro_exit_mm")
                if _known(left) and left < -SAME_Z:
                    # Rounded up, the DRO tip leaves the full diameter short of the exit.
                    parts.append(_Box("STOP: DRO tip stops short of break-through; raise exit"))
            elif _known(endpoint.get("depth_mm")):
                depth = endpoint.get("dro_depth_mm")
                parts.append(f"depth {o(depth if _known(depth) else endpoint['depth_mm'])}")
                floor = endpoint.get("depth_floor_mm", "unknown")
                if _known(depth) and _known(floor) and depth < floor - SAME_Z:
                    # Rounded up, the DRO tip leaves the hole shallower than its depth band.
                    parts.append(_Box("STOP: DRO depth is below the feature's depth band"))
                elif (
                    _known(depth)
                    and not _known(floor)
                    and abs(depth - endpoint["depth_mm"]) > SAME_Z
                ):
                    parts.append(_Box("STOP: DRO depth rounded; feature depth band unknown"))
            if not _known(endpoint.get("tip_z")):
                parts[0] = f"Z {o(entry)} → depth not set"
                parts.append(_Box("STOP: drill point length unknown"))
            return parts
        parts = []
        start, end = (self.op_z(setup, op, key) for key in ("z_from", "z_to"))
        if "z_from" in op and "z_to" in op:
            parts.append(f"Z {o(start)} → {o(end)}")
        elif "to_z" in op:
            parts.append(self.z_target(setup, op))
        if "depth_mm" in op:
            parts.append(f"depth {o(op['depth_mm'])}")
        if "exit_mm" in op:
            parts.append(f"exit {o(op['exit_mm'])}")
        if isinstance(op.get("to_z_band"), list):
            parts.append(self.allowed(setup, op))
        for key, value in (("z_from", start), ("z_to", end)):
            if key in op and not ("z_from" in op and "z_to" in op):
                parts.append(f"{'from' if key == 'z_from' else 'to'} Z {o(value)}")
        parts.extend(self.plunge_x(setup, op))
        if any("?" in part for part in parts):
            parts.append(_Box("STOP: Z target not set"))
        return parts or (["—"] if op.get("do") in MANUAL else [_Box("STOP: Z target not set")])

    def plunge_x(self, setup, op):
        """A lathe part-off / cut-to-fit row's X: the diameter the blade plunges to
        (``to_dia``, the axis unless authored) as the DRO reads it, from the diameter it
        starts on, and the total radial plunge between them (the reach finding's depth, in
        mm). An unknown endpoint or X display (radius or diameter) is a STOP; an unknown
        plunge prints the endpoint alone."""
        if op.get("do") not in {"part_off", "cut_to_fit"} or not self.lathe(setup):
            return []
        to_dia = op.get("to_dia", 0.0)
        if not (_known(to_dia) and to_dia >= 0):
            return [_Box("STOP: X endpoint (to_dia) not set")]
        display = _mapping(self.records.get(("coordinates", setup["id"]))).get("x_display")
        half = {"radius": 0.5, "diameter": 1.0}.get(display)
        if half is None:
            return [_Box(_X_DISPLAY_STOP)]
        scale = {"mm": 1.0, "in": 25.4}.get(self.units)
        depth = _mapping(self.records.get(("reach", f"{setup['id']}:{op.get('op')}"))).get(
            "reach_depth_mm"
        )
        o = self.operative
        if not (_known(depth) and scale):
            return [f"X → {o(to_dia * half)} (radial plunge unknown)"]
        radial = depth / scale
        start = (to_dia + 2 * radial) * half
        return [f"X {o(start)} → {o(to_dia * half)} ({o(radial)} radial)"]

    def hole_xy(self, setup, op):
        """A mill hole op's tool-axis X/Y as the DRO dials it: its feature's located row's
        ``dro_xy`` (coordinates, the nearest DRO grid point). A feature placed at several
        X/Y prints none here: the feature map lists them."""
        if op.get("do") not in CENTRE_OPS or self.lathe(setup):
            return []
        numbers = _mapping(self.records.get(("coordinates", setup["id"])))
        points = {
            tuple(row["dro_xy"])
            for row in numbers.get("rows", [])
            if isinstance(row, dict)
            and row.get("feature") == op.get("feature")
            and isinstance(row.get("dro_xy"), list)
        }
        if len(points) != 1:
            return []
        x, y = next(iter(points))
        if not (_known(x) and _known(y)):
            return [_Box("STOP: hole X/Y not set")]
        o = self.operative
        return [f"tool axis X {o(x)}, Y {o(y)}"]

    def dro_to_z(self, setup, op):
        """The depth the DRO shows for ``op``: the ``dro_to_z`` coordinates checked (rounded
        up, never deeper than ``to_z``), the same Z its contour tables print."""
        numbers = self.records.get(("coordinates", setup["id"]), {})
        operations = numbers.get("operations") if isinstance(numbers, dict) else None
        for entry in operations if isinstance(operations, list) else []:
            if isinstance(entry, dict) and str(entry.get("op")) == str(op.get("op")):
                return entry.get("dro_to_z", "unknown")
        return dro_z(op.get("to_z", "unknown"), dro_grid(self.bundle, setup))

    def coordinates_entry(self, setup, op):
        """``op``'s entry in its setup's coordinates ``operations``, else an empty mapping."""
        numbers = _mapping(self.records.get(("coordinates", setup["id"])))
        operations = numbers.get("operations")
        for entry in operations if isinstance(operations, list) else []:
            if isinstance(entry, dict) and str(entry.get("op")) == str(op.get("op")):
                return entry
        return {}

    def z_levels(self, setup, op):
        """The axial levels coordinates stepped an op authoring ``doc_mm`` down in, or None."""
        levels = self.coordinates_entry(setup, op).get("z_levels")
        return levels if isinstance(levels, dict) else None

    def z_target(self, setup, op):
        """``Z → depth``, or the axial levels coordinates stepped an op authoring ``doc_mm``
        down in: ``Z start → depth in N levels of doc max``. A grooving/parting blade's
        target is the DRO reading of the corner its Z touch set (coordinates ``blade``),
        named."""
        o = self.operative
        levels = self.z_levels(setup, op)
        if levels is not None:
            count = levels.get("count")
            return (
                f"Z {o(levels.get('dro_start_z'))} → {o(levels.get('dro_to_z'))} in "
                f"{_text(count)} level{'' if count == 1 else 's'} of "
                f"{o(levels.get('doc_mm'))} max"
            )
        blade = _mapping(self.coordinates_entry(setup, op).get("blade"))
        if blade:
            corner = _CORNERS.get(blade.get("reading_corner"))
            if corner is None or not _known(blade.get("corner_dro_z")):
                return "Z → ? (blade corner not set)"
            return f"Z → {o(blade['corner_dro_z'])} ({corner} corner)"
        return f"Z → {o(self.dro_to_z(setup, op))}"

    def allowed(self, setup, op):
        """An op's ``to_z_band`` as ``allowed low to high``, in the terms of its Z target: a
        grooving/parting blade's as readings of the corner its target reads (coordinates
        ``blade`` ``corner_dro_band``, rounded inward on the DRO grid), named, and ``?``
        while that corner or band is unknown; any other op's as authored."""
        blade = _mapping(self.coordinates_entry(setup, op).get("blade"))
        if not blade:
            low, high = op["to_z_band"][0], op["to_z_band"][-1]
            return f"allowed {_number(low)} to {_number(high)}"
        corner = _CORNERS.get(blade.get("reading_corner"))
        band = blade.get("corner_dro_band")
        if corner is None or not isinstance(band, list):
            return "allowed ? (blade corner not set)"
        o = self.operative
        return f"allowed {o(band[0])} to {o(band[1])} ({corner} corner)"

    def relief_plunges(self, setup, op):
        """A blade groove's plunges (coordinates ``plunges``): the reading corner's Z for
        each, the diameter every plunge stops at and the groove they leave."""
        numbers = self.records.get(("coordinates", setup["id"]), {})
        plunges = next(
            (
                entry
                for entry in _mapping(numbers).get("plunges", [])
                if str(_mapping(entry).get("op")) == str(op.get("op"))
            ),
            None,
        )
        if plunges is None:
            return []
        scale = {"mm": 1.0, "in": 25.4}.get(self.units)

        def o(value):
            """A millimetre plunge fact as the DRO shows it, in plan units."""
            return self.operative(value / scale if scale and _known(value) else "unknown")

        corners = plunges.get("corner_z_mm")
        corner = _CORNERS.get(plunges.get("reading_corner"))
        if corner is None:
            return [_Box("STOP: plunge positions not set — blade corner unknown")]
        if not isinstance(corners, list):
            return [_Box("STOP: plunge positions not set — blade width unknown")]
        parts = [f"plunge {index} {corner} corner Z {o(z)}" for index, z in enumerate(corners, 1)]
        feature = op.get("feature")
        size = f"Ø {o(plunges.get('diameter_mm'))}"
        band = plunges.get("dia_band_mm")
        if isinstance(band, list) and scale:
            size += f" ({self.band([v / scale for v in band], feature, 'dia')})"
        parts.append(("each to " if len(corners) > 1 else "to ") + size)
        low, high = plunges.get("groove_z_mm", [None, None])
        parts.append(f"groove Z {o(low)} to {o(high)}")
        return parts

    def surface_z(self, setup, value, source=None, face=None, done=0, path=False):
        """One surface, one printed Z (:func:`operative_z`): the checked depth of the op
        that produced it, on its own setup's grid, as this setup's DRO shows it; else
        ``value`` on this grid, rounded up. An unknown stays unknown. ``path``: an op's
        own path end, not a touched face."""
        return operative_z(self.bundle, setup, value, face, done, source, path)

    def kernel_z(self, setup, value_mm):
        """A Z the geometry kernel measured (mm) as the surface's one printed DRO Z
        (:meth:`surface_z`). A value within the kernel's as-is face tolerance
        (``FACE_Z_TOL_MM``) of a DRO grid line is that line: kernel noise, never a reason
        to round up a step. Anything farther off the grid rounds as any surface does."""
        scale = {"mm": 1.0, "in": 25.4}.get(self.units)
        if not (_known(value_mm) and scale):
            return value_mm
        value = value_mm / scale
        step, decimals = dro_grid(self.bundle, setup)
        line = round(round(value / step) * step, decimals)
        if abs(value - line) * scale <= FACE_Z_TOL_MM:
            value = line
        return self.surface_z(setup, value)

    def datum_z(self, setup, face, edge, done=0):
        """A touched Z datum at nominal ``edge`` once ``setup``'s first ``done`` ops have
        run, as the op that last cut ``face`` (``top``: the stock top) left it, through
        this setup and its stock lineage (:meth:`surface_z`)."""
        return self.surface_z(setup, edge, face=face, done=done)

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
        numbers = self.records.get(("blind_depth", op_feature(op)), {})
        return next(
            (
                e
                for e in numbers.get("endpoints", [])
                if e.get("setup") == setup["id"] and str(e.get("op")) == str(op["op"])
            ),
            None,
        )

    def tip_note(self, setup, op):
        """A through op's breakthrough note: how far past the exit face the full diameter
        runs at the DRO tip. The op row's Z column already prints that tip and the exit face
        (:meth:`tip`), so the note never repeats a Z. That run-out is what the printed tip
        leaves, never the authored ``exit_mm``: the lower of ``dro_exit_mm`` (past the
        nominal face) and the same past the printed face, cut down to the DRO decimals so it
        is never overstated. An unknown or negative run-out claims none (a negative one is
        the tip's STOP); the depth arithmetic stays in the report."""
        endpoint = self.endpoint(setup, op)
        if not endpoint or endpoint.get("exit_face", "not_applicable") == "not_applicable":
            return None
        exit_face, tip = endpoint.get("dro_exit_face"), endpoint.get("dro_tip_z")
        if not (_known(endpoint.get("tip_z")) and _known(tip) and _known(exit_face)):
            return None
        lead, left = endpoint.get("lead_mm", endpoint.get("point_mm")), endpoint.get("dro_exit_mm")
        run_out = min(left, exit_face - lead - tip) if _known(left) and _known(lead) else None
        if run_out is None or run_out < -SAME_Z:
            return None
        scale = 10 ** dro_grid(self.bundle, setup)[1]
        run_out = math.floor(round(run_out * scale, 6)) / scale
        if run_out <= 0:
            return "Break through: the full diameter just reaches the exit face."
        return (
            f"Break through: the full diameter runs at least {self.operative(run_out)} past "
            "the exit face."
        )

    def arc_line(self, setup, op_id):
        """The line a manual-arc rough stays outside: the scribed line once a ``scribe`` op
        has laid out that op's feature (in an earlier setup or before it in this one), else
        the finished outline, since laying out is optional."""
        ops = setup.get("ops", [])
        index = next((i for i, op in enumerate(ops) if str(op.get("op")) == str(op_id)), None)
        feature = ops[index].get("feature") if index is not None else None
        earlier = []
        for other in self.plan.get("setups", []):
            if other is setup:
                break
            earlier.extend(other.get("ops", []))
        earlier.extend(ops[: index or 0])
        scribed = feature and any(
            op.get("do") == "scribe" and op.get("feature") == feature for op in earlier
        )
        return "the scribed line" if scribed else "the finished outline"

    def steps(self, text):
        """A procedure written as blank-line paragraphs prints as numbered steps; single
        line breaks inside a paragraph are just wrapping."""
        paragraphs = [
            " ".join(part.split()) for part in re.split(r"\n\s*\n", str(text)) if part.strip()
        ]
        if len(paragraphs) < 2:
            return self.bench(text)
        return " ".join(
            f"({number}) {self.bench(paragraph)}"
            for number, paragraph in enumerate(paragraphs, start=1)
        )

    def note(self, head, procedure):
        """One INSPECTION NOTES entry: ``head`` then the procedure. A list of steps prints
        each step numbered, its ``{name}`` fields as recording blanks and its
        ``Calculate:`` steps apart as the calculation lines; a string prints as before
        (:meth:`steps`)."""
        if not isinstance(procedure, list):
            return f"{head}: {self.steps(procedure)}"
        steps = [self.bench(step) for step in procedure]
        return _Steps(
            (
                head + ":",
                [step for step in steps if not step.startswith(CALCULATION)],
                [step for step in steps if step.startswith(CALCULATION)],
            )
        )

    def inspection(self, setup, op, notes, worksheets, sheets):
        """The op row's inspection cell. A procedure goes on the attached sheets: one that
        works its readings (``{name}`` fields) through two or more calculation lines on a
        worksheet of its own, numbered from ``sheets["worksheets"]``, any other as a
        numbered INSPECTION NOTE on ``sheets["notes"]``; the cell names where."""
        sid = setup["id"]

        def place(item):
            if isinstance(item, _Steps) and _readings(item[1]) and len(item[2]) >= 2:
                worksheets.append(item)
                first = sheets.get("worksheets")
                return f"{sid} sheet {first + len(worksheets) - 1 if first else '?'} worksheet"
            notes.append(item)
            return f"{sid} sheet {sheets['notes']} note {len(notes)}"

        rows = ["? inspection checks not set"] if op.get("checks") == "unknown" else []
        names = op_features(op)
        missing = _mapping(op.get("missing_requirements"))
        methods = _mapping(op.get("inspection_methods"))
        for requirement, reference in (_mapping(op.get("checks")) | missing).items():
            # One drawing limit split across several features is read once, on one row.
            owners = [n for n in names if requirement in self.features.get(n, {})] or names
            findings = [
                next(
                    (
                        f
                        for f in self.findings
                        if _field(f, "rule") == "inspection"
                        and _field(f, "subject") == f"{feature}:{requirement}"
                    ),
                    None,
                )
                for feature in owners
            ]
            name = _REQUIREMENT_NAMES.get(requirement, _text(requirement))
            if requirement in missing:
                target = "(no drawing limit)"
            else:
                bands = [
                    self.band(self.features.get(feature, {}).get(requirement), feature, requirement)
                    for feature in owners
                ]
                target = (
                    bands[0]
                    if len(set(bands)) == 1
                    else " / ".join(
                        f"{self.feature_name(feature)} {band}"
                        for feature, band in zip(owners, bands, strict=True)
                    )
                )
            gauge = (
                "no gauge chosen"
                if reference in (None, "unknown")
                else self.short_reference(reference, "gauges")
            )
            pair = go_no_go_pair(op, requirement)
            unresolved = (
                requirement in missing
                or pair == "unknown"
                or any(
                    finding is None or _status(finding) in ("unknown", "unsupported")
                    for finding in findings
                )
            )
            line = f"{'? ' if unresolved else ''}{name} {target}: {gauge}"
            if pair == "unknown":
                line += ", GO / NO-GO sizes not set"
            elif pair:
                line += self.go_no_go(pair, owners[0], requirement, reference)
            datums = [
                self.features.get(feature, {}).get("position_datums")
                for feature in owners
                if requirement == "position_dia"
            ]
            datums = next(filter(None, datums), None)
            if datums:
                line += " to " + "|".join(map(_text, datums))
            method = methods.get(requirement)
            if method and method != "unknown":
                head = f"{sid} op {op['op']} {name}"
                item = self.note(head, method)
                sketch = self.inspection_sketch(setup, op, requirement)
                if sketch:
                    item = item if isinstance(item, _Steps) else _Note(item)
                    item.sketch = sketch
                line += f" [{place(item)}]"
            rows.append(line)
        for hold in op.get("process_holds", []):
            rows.append(self.process_hold(hold))
        note = op.get("inspection_note")
        if note:
            head = f"{sid} op {op['op']}"
            item = (
                self.note(head, note) if isinstance(note, list) else f"{head}: {self.bench(note)}"
            )
            rows.append(f"see {place(item)}")
        return rows or ["—"]

    def inspection_sketch(self, setup, op, requirement):
        """The figure of the set-up sketches an inspect op declares for ``requirement``
        (``inspection_views``), drawn by the kernel; a NOT SHOWN line when declared but not
        drawn; else empty."""
        if requirement not in _mapping(op.get("inspection_views")):
            return ""
        render = _mapping(self.report.get("renders", {}).get(setup["id"]))
        sketch = _mapping(render.get("inspections")).get(f"{op['op']}:{requirement}")
        if not sketch:
            return _p("NOT SHOWN: the set-up sketches for this check could not be drawn.")
        alt = f"Setup {setup['id']} op {op['op']} {requirement} set-up sketches"
        return (
            '<figure class="fixture-render inspection-sketch">'
            f'<img src="{escape(sketch["path"], quote=True)}" alt="{escape(alt, quote=True)}">'
            "</figure>"
        )

    def process_hold(self, hold):
        """A shop limit inside the drawing band, printed apart from the drawing's own; a hold
        on a reference-only span also names the REF it sets, since the drawing has no limit."""
        reading, gauge, drawing, reference = self.process_hold_parts(hold)
        return (
            f"PROCESS HOLD — not a drawing limit: {self.bench(hold['reason'])} — {reading}"
            + (f" (drawing: {drawing})" if reference else "")
            + f": {gauge}"
        )

    def process_hold_parts(self, hold):
        """``(reading, gauge, drawing, reference)`` of one process hold: what the gauge reads
        at the hold band, the gauge (with its GO / NO-GO sizes), the drawing's own limit, and
        whether that is a reference-only span. Such a hold reads its stated ``measure``; the
        drawing gives the span only as REF, with no limit."""
        feature, requirement = hold["feature"], hold["requirement"]
        definition = _mapping(self.features.get(feature))
        reference = reference_only(definition, requirement)
        places = self.gauge_places(hold["band"], feature, requirement, hold["gauge"])
        if reference:
            name = self.bench(hold["measure"])
            base = requirement.removesuffix("_ref")
            drawing = (
                f"{_REQUIREMENT_NAMES.get(base, _text(base))} "
                f"REF {_number(definition[requirement])}, no limit"
            )
        else:
            name = _REQUIREMENT_NAMES.get(requirement, _text(requirement))
            drawing = f"{name} {self.band(definition.get(requirement), feature, requirement)}"
        band = "–".join(_number(limit, places) for limit in hold["band"])
        gauge = self.short_reference(hold["gauge"], "gauges")
        if hold.get("go_no_go"):
            gauge += self.go_no_go(hold["go_no_go"], feature, requirement, hold["gauge"])
        return f"{self.feature_name(feature)} {name} {band}", gauge, drawing, reference

    def gauge_places(self, sizes, feature, requirement, reference):
        """Decimals a gauge reading prints at: the sizes' own digits, one gauge step and the
        drawing precision, whichever is finest. A reference-only span has no drawing limit,
        so no drawing precision applies to it."""
        gauge = resolve(self.bundle, "gauges", reference) or {}
        resolution = length_mm(gauge, "resolution")
        definition = _mapping(self.features.get(feature))
        precision = (
            None
            if reference_only(definition, requirement)
            else self.precision(feature, requirement)
        )
        # The decimals that show one gauge step: 0.001 mm reads 3, and 0.0001 in (0.00254 mm)
        # also reads 3, not the five places of its mm conversion.
        step = 0
        if _known(resolution) and resolution > 0:
            step = math.ceil(-math.log10(resolution) - 1e-9)
        return max(
            *(_places(size) for size in sizes),
            min(max(step, 0), 6),
            precision if isinstance(precision, int) else 0,
        )

    def go_no_go(self, pair, feature, requirement, reference):
        """A limit check's two sizes and what each must do: plugs enter a hole, rings pass
        over a boss or shaft."""
        sizes = [pair["go"], pair["no_go"]]
        go, no_go = (
            _number(size, self.gauge_places(sizes, feature, requirement, reference))
            for size in sizes
        )
        kind = self.features.get(feature, {}).get("kind")
        verb = "passes over" if kind in ("boss", "shaft") else "enters"
        return f", GO {go} {verb}, NO-GO {no_go} does not"

    def coating(self, op):
        """A coating op's tool cell: its outside service or in-house consumables."""
        process = op.get("process", "unknown")
        cells = []
        for reference in process if isinstance(process, list) else [process]:
            category, item = coating_process(self.bundle, reference)
            # The shop's display name; an unnamed entry keeps its identity visible.
            name = _mapping(item).get("name")
            name = name if isinstance(name, str) and name.strip() not in ("", "unknown") else None
            shown = name or _text(reference)
            if reference == "unknown":
                cells.append("? coating process not set")
            elif category == "services":
                # Name what is sent out and to whom: the service and the coating it applies.
                applied = _mapping(item).get("coating")
                cells.append(
                    f"outside: {shown}"
                    + (f" ({_text(applied)})" if applied not in (None, "unknown") else "")
                )
            elif category == "consumables":
                cells.append(f"{shown} (in-house)")
            else:
                cells.append(f"{_text(reference)} (not in shop list)")
        return ", ".join(cells)

    def spindle_turn(self, op):
        """The way a lathe op turns the spindle, from its tool's declared ``hand``: a turning,
        facing, grooving or boring tool of either hand is set edge up (as the turning model
        poses it), so the work turns down onto its edge: FORWARD; a tailstock tool
        (:data:`_AXIAL_OPS`) turns FORWARD under a right-hand cut and REVERSE under a
        left-hand one. A hand not declared is a STOP, never assumed."""
        hand = _mapping(resolve(self.bundle, "tools", op.get("tool"))).get("hand")
        if hand not in ("right", "left"):
            return _Box("STOP: spindle direction not known — the tool's hand is not declared")
        return "REVERSE" if op.get("do") in _AXIAL_OPS and hand == "left" else "FORWARD"

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

    def unset_z(self, setup, op, target):
        """An op cut before a face-then-set Z zero exists cannot stop on a DRO number: its
        Z reads as a height above Z0 the machinist measures, and says when Z is set."""
        touch = _mapping(_mapping(setup.get("zero")).get("z"))
        after = touch.get("after_op")
        order = [str(item.get("op")) for item in setup.get("ops", [])]
        if (
            touch.get("method") != "face_then_set"
            or str(after) not in order
            or str(op.get("op")) not in order
            or order.index(str(op["op"])) > order.index(str(after))
        ):
            return target
        unset = f"(DRO Z not set until after op {after})"
        # A lathe face cut before Z exists only cleans up the face Z is then set on; a
        # mill face cut before Z exists sets the part height, which must be measured.
        lathe = self.lathe(setup)
        lines = []
        for line in target:
            if isinstance(line, str) and line.startswith("Z → ") and lathe:
                line = f"face to clean up; Axis Set Z {line.removeprefix('Z → ')} on it {unset}"
            elif isinstance(line, str) and line.startswith("Z → "):
                line = f"face to measured height {line.removeprefix('Z → ')} above Z0 {unset}"
            elif isinstance(line, str) and line.startswith("Z "):
                line = f"measured height {line.removeprefix('Z ')} above Z0 {unset}"
            lines.append(line)
        return lines

    def cut_depths(self, setup, op, lathe):
        """The op's action with its allowance, passes and depth of cut in words that say
        what they measure: a lathe allowance is on Ø (roughing names its Ø target), a face's
        is on the face, a mill wall's per side; a depth of cut is radial or axial per pass, a
        plunge's total. A part-off or cut-to-fit plunges to the centre: no DOC prints."""
        do = str(op.get("do", ""))
        o = self.operative
        parts = [_text(do)]
        for key in ("rough_allowance_mm", "stock_to_leave_mm"):
            if key not in op or (key == "stock_to_leave_mm" and op[key] == 0):
                continue
            leave = f"leave {o(op[key])} mm"
            if do in FACING:
                parts.append(f"{leave} on the face")
            elif lathe:
                numbers = self.records.get(("speeds_feeds", f"{setup['id']}:{op['op']}"), {})
                rough = numbers.get("diameter_in")
                if do == "rough_turn" and _known(rough):
                    parts[0] += f" to Ø{o(rough * 25.4)}"
                parts.append(f"{leave} on Ø")
            else:
                parts.append(f"{leave} per side")
        if "passes" in op:
            parts.append(f"{_text(op['passes'])} passes")
        if "doc_mm" in op and do not in {"part_off", "cut_to_fit"}:
            depth = f"{o(op['doc_mm'])} mm"
            if not lathe:
                parts.append(f"{depth} axial per pass")
            elif do in FACING:
                parts.append(f"{depth} axial per pass (facing)")
            elif do == "form_relief":
                parts.append(f"{depth} radial, total plunge depth")
            elif do == "form_dome":
                parts.append(f"{depth} per pass, square to the dome")
            else:
                parts.append(f"{depth} radial per pass")
        return parts

    def manual_arc_lines(self, setup, op, stops):
        """Layout and bench-filing instructions computed for this manual operation. A
        finding the rule leaves unknown stops the op, in its row and in the setup's STOP
        list, with the rule's reasons: no unproven layout or filing reads as established."""
        subject = f"{setup['id']}:{op['op']}"
        finding = next(
            (
                f
                for f in self.findings
                if _field(f, "rule") == "manual_arc" and _field(f, "subject") == subject
            ),
            None,
        )
        numbers = _mapping(_field(finding, "numbers", {})) if finding is not None else {}
        if not numbers:
            return []
        status = _status(finding)
        lines = self.manual_arc_steps(op, numbers, status == "pass")
        if lines and status in ("unknown", "unsupported"):
            debts = numbers.get("debts")
            reasons = [self.bench(debt) for debt in debts] if isinstance(debts, list) else []
            lines.append(_Box(f"STOP: {'; '.join(reasons) or 'not proven'} — do not run."))
            stops.setdefault("manual arc not proven", []).append(str(op["op"]))
        return lines

    def manual_arc_steps(self, op, numbers, proven):
        """The layout or bench-filing line itself; ``proven`` says whether the rule passed it."""
        o = self.operative
        if op.get("do") == "scribe":
            centre = numbers.get("centre_setup_xy") or ["unknown", "unknown"]
            axis = numbers.get("centre_on")
            layout = numbers.get("layout")
            instrument = (
                self.reference(numbers.get("template"), "gauges")
                if layout == "template"
                else _text(layout)
            )
            line = (
                f"Layout: blue the part; scribe R{_number(numbers.get('radius_mm'))} mm "
                f"about the centre X {o(centre[0])}, Y {o(centre[1])}"
            )
            if axis:
                line += f", on the axis of {self.feature_name(axis)}"
            line += f", with {instrument}"
            ends = numbers.get("ends_setup_xy")
            if isinstance(ends, list) and len(ends) == 2:
                line += (
                    f"; arc ends X {o(ends[0][0])}, Y {o(ends[0][1])} and "
                    f"X {o(ends[1][0])}, Y {o(ends[1][1])}"
                )
            elif ends is None:
                line += "; scribe the full circle"
            return [_Plain(line + ".")]
        if op.get("do") != "file_to_line":
            return []
        guide = _mapping(numbers.get("guide"))
        target = "file to the scribed line"
        if guide.get("kind") == "buttons":
            target = "file down to the hardened button rims"
            guide_text = (
                f"{self.reference(guide.get('kit'), 'fixtures')} "
                f"({_buttons_text(guide, self.feature_name(guide.get('bore')), proven)})"
            )
        elif guide.get("kind") == "template":
            guide_text = self.reference(guide.get("kit"), "gauges")
            layout = numbers.get("layout_op")
            if isinstance(layout, str) and layout:
                target += f" laid out in {layout.replace(':', ' op ')}"
        else:
            guide_text = "STOP: filing guide not established"
        gauge = _mapping(numbers.get("gauge"))
        line = (
            f"Bench filing: {target}; guide: "
            + guide_text
            + "; check with "
            + self.reference(gauge.get("ref"), "gauges")
        )
        rough = numbers.get("rough_op")
        cap = numbers.get("stock_cap_mm")
        if isinstance(rough, str) and rough not in ("", "unknown"):
            line += f"; file off the stock left by {rough}"
            if _known(cap):
                line += f" (at most {_number(cap)} mm)"
            else:
                line += "; STOP: filing stock limit not established"
        else:
            line += "; STOP: roughing operation not established"
        return [_Plain(line + ".")]

    def operations(self, setup, tool_numbers, sheets):
        """The op table for the front sheet, the inspection notes for sheet 2 and the
        worksheets, one ``(head, html)`` per procedure that records readings.

        ``sheets`` maps "notes", "contours" and "worksheets" (the first worksheet's) to the
        attached sheet numbers that carry them; an op's own note prints under its row, and
        the row names the sheet that carries its inspection procedure or contour table. A
        setup of bench steps only (no op cuts) prints an ASSEMBLY / FINISHING table
        instead: step, feature, material / consumable, action (the op's own instruction)
        and inspection, with no machining columns left empty.
        """
        ops = setup.get("ops", [])
        rows, inspection_notes, worksheets, stops, turns = [], [], [], {}, set()
        where = {kind: f"{setup['id']} sheet {number}" for kind, number in sheets.items() if number}
        saw_table = any(op.get("do") in SAW_OPS for op in ops)
        finishing = bool(ops) and all(op.get("do") in MANUAL for op in ops)
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
            action = self.cut_depths(setup, op, lathe)
            if saw:
                plane = _mapping(op.get("cut_plane"))
                action.append(
                    f"blade centre {_text(plane.get('axis')).upper()} "
                    f"{_number(plane.get('value'))} {self.bundle.features.get('units', '?')}"
                )
            reference = op.get("tool")
            if op.get("do") == "coating":
                tool = self.coating(op)
            elif manual and reference is None:
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
            if lathe and not (manual or saw):
                turn = self.spindle_turn(op)
                speed = [speed, turn]
                if isinstance(turn, _Box):
                    stops.setdefault("spindle direction not known", []).append(str(op["op"]))
                else:
                    turns.add(turn)
            plunge = self.plunge_feed(setup, op)
            if plunge is not None and plunge.startswith("STOP"):
                feed = [*(feed if isinstance(feed, list) else [feed]), _Box(plunge)]
                stops.setdefault("no plunge feed", []).append(str(op["op"]))
            elif plunge is not None:
                feed = [*(feed if isinstance(feed, list) else [feed]), f"plunge {plunge}"]
            direction = op.get(
                "direction",
                "not_applicable" if manual or op.get("do") in _AXIAL_OPS else None,
            )
            direction = self.direction(direction)
            if saw:
                direction = "keep " + _text(_mapping(op.get("cut_plane")).get("keep"))
            saw_numbers = self.records.get(("saw_cut", f"{setup['id']}:{op['op']}"), {})
            rest_cells, rest_lines = ([], []) if saw else self.rest_steps(setup, op)
            if saw:
                target = [
                    "retained edge " + _number(saw_numbers.get("retained_boundary_mm")) + " mm"
                ]
            else:
                target = (
                    self.hole_xy(setup, op)
                    + self.tip(setup, op)
                    + self.relief_plunges(setup, op)
                    + rest_cells
                )
            if any(isinstance(line, _Box) and "Z target" in line for line in target):
                stops.setdefault("no Z target", []).append(str(op["op"]))
            target = self.unset_z(setup, op, target)
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
            boxes.extend(self.manual_arc_lines(setup, op, stops))
            boxes.extend(rest_lines)
            # Crash and status warnings print full width under the op so the narrow
            # action column keeps its line height; the op's own note follows them there.
            note = op.get("note")
            derivation = self.tip_note(setup, op)
            instruction = " ".join(
                filter(
                    None,
                    [
                        self.bench(note, setup) if note else None,
                        derivation,
                        self.compound_note(setup, op),
                    ],
                )
            )
            if instruction and not finishing:
                boxes.append(_Note(instruction))
            if str(op["op"]) in self.contour_ops:
                boxes.append(_Plain(f"See contour table on {where['contours']}"))
            features = (
                ", ".join(self.feature_label(f, marked=False) for f in op_features(op))
                if feature is not None
                else "stock"
                if saw
                else "?"
            )
            inspection = self.inspection(setup, op, inspection_notes, worksheets, sheets)
            if finishing:
                cells = (_text(op["op"]), features, tool, instruction or ", ".join(action))
                rows.append(_Row((*cells, inspection), boxes))
                continue
            rows.append(
                _Row(
                    (
                        _text(op["op"]),
                        ", ".join(action),
                        features,
                        tool,
                        speed,
                        feed,
                        target,
                        direction,
                        inspection,
                    ),
                    boxes,
                )
            )
        if finishing:
            title = "assembly / finishing"
            headings = ["step", "feature", "material / consumable", "action"]
            widths = [5, 12, 20, 41, 22]
        else:
            title = "operations"
            headings = [
                "op",
                "do",
                "feature",
                "tool",
                "speed" if saw_table else "rpm",
                "feed",
                "cut target" if saw_table else ("Z from → to" if lathe else "Z tip"),
                "direction",
            ]
            widths = [4, 16, 12, 7, 6, 9, 11, 9, 26]
        # A long table runs onto the back of the front sheet; the repeated heading row
        # names it there, and on the front the section heading is drawn over it.
        turns = [turn for turn in _SPINDLE_TURNS if turn in turns]
        # Each turning op's rpm cell names its spindle turn; the heading says once what
        # the word means (a line of its own would part the heading from its table).
        key = "; ".join(f"spindle {turn}: {_SPINDLE_TURNS[turn]}" for turn in turns)
        table = f"<h2>{title.upper()}{' — ' + key if key else ''}</h2>"
        table += _table(
            [*headings, "inspection: limit, gauge"],
            rows,
            "operations",
            widths,
            continued=f"SETUP {setup['id']} — sheet 1 (continued): {title}",
        )
        notes_html = (
            f'<div class="keep"><h2>INSPECTION NOTES</h2>{_list(inspection_notes)}</div>'
            if inspection_notes
            else ""
        )
        return table, notes_html, [(w[0].rstrip(":"), _worksheet(w)) for w in worksheets], stops

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

    def cut_order(self, table, narrate=True):
        """Stage, then a cutting order only where coordinates established one. With
        ``narrate`` False (a raster, whose table shows its passes in order and whose op row
        gives the stage) only a cutting order NOT established prints: the operator must act
        on that one."""
        stage = table.get("stage")
        text = ""
        if stage == "rough" and narrate:
            allowance = table.get("allowance_mm", table.get("rough_allowance_mm"))
            text = f"; stage: rough, leaves {self.operative(allowance)} mm for finish"
        elif stage == "finish" and narrate:
            text = "; stage: finish"
        order = table.get("cut_order")
        if order in ("conventional", "climb"):
            rotation = {"cw": "clockwise", "ccw": "counterclockwise"}.get(
                table.get("spindle_rotation"), "unknown"
            )
            return text + (f"; rows in cutting order ({order}, {rotation} spindle)" * narrate)
        if order is None:
            return text
        reason = table.get("cut_order_reason", "not established")
        return text + f"; rows NOT in an established cutting order: {reason}"

    @staticmethod
    def clip(table, markers, rows):
        """Where the kernel clipped this table at its op's stock_removal_bounds, named by
        the printed row the cutter starts or stops at, and the piece no cut links."""
        ends = []
        for index, marker in enumerate(markers):
            if not marker or index >= len(rows):
                continue
            point = rows[index][0] or f"row {index + 1}"
            ends.append(("starts at " if index == 0 else "stops at ") + point)
        text = ""
        if ends:
            text = (
                f"; {' and '.join(ends)}: the stock past "
                + ("it" if len(ends) == 1 else "them")
                + " is outside this op's area"
            )
        fragment = table.get("fragment")
        if isinstance(fragment, list) and len(fragment) == 2:
            text += (
                f"; piece {fragment[0]} of {fragment[1]}: no cut links the pieces, so the "
                "stock between them is not cleared by this op"
            )
        return text

    def stock_clear(self, setup):
        """A test of whether a cutter stands wholly outside the stock ``setup`` receives as
        the kernel modelled it (its setup-frame ``stock_bbox_mm``), or None unless the kernel
        ran and modelled that stock. Every op's stock lies within that box, since cuts only
        remove material; an op's ``stock_removal_bounds`` is only what it may remove, never
        where the stock ends. The test takes a setup axis (0 X, 1 Y), the cutter centre on
        it in plan units, the cutter radius in mm and the side: -1 below the box, +1 above
        it, 0 either; it must clear the box by _STOCK_BOX_TOL_MM."""
        kernel = getattr(self.bundle, "kernel", None)
        scale = {"mm": 1.0, "in": 25.4}.get(self.units)
        if not isinstance(kernel, dict) or kernel.get("status") != "ok" or scale is None:
            return None
        box = _mapping(_mapping(kernel.get("setups")).get(setup.get("id"))).get("stock_bbox_mm")
        if not (isinstance(box, list) and len(box) == 6 and all(map(_known, box))):
            return None

        def clear(axis, centre, radius, side=0):
            below = centre * scale + radius <= box[axis] - _STOCK_BOX_TOL_MM
            above = centre * scale - radius >= box[axis + 3] + _STOCK_BOX_TOL_MM
            return below if side < 0 else above if side > 0 else below or above

        return clear

    def raster_clearance(self, setup, profile):
        """What of a raster profile's pass ends along the run axis is proven in air, for the
        operator entering and leaving each pass: a cutter a radius past the stock the setup
        receives (:meth:`stock_clear`) meets none. Nothing else proves an end clear or in
        material, so an end inside that box, or any end without it, carries no claim either
        way. The table prints the ends; this names an end by its side only. The passes run in
        and out clear only when every emitted piece's start and end is proven so: a keep-out
        splits passes into pieces that also start and stop between the outer ends. A pocket's
        first pass enters from air only when it stands a radius outside that box on the open
        side."""
        raster = profile["raster"]
        axis = str(raster.get("run_axis", "")).upper()
        ends, radius = raster.get("ends"), raster.get("clearance_mm")
        if not (isinstance(ends, list) and len(ends) == 2 and all(map(_known, ends))):
            return ""
        # Every emitted piece's start and end, or none when any is malformed or unknown.
        pieces = profile.get("cutter_centre")
        points = (
            [point for piece in pieces for point in piece]
            if isinstance(pieces, list)
            and all(isinstance(piece, list) and len(piece) == 2 for piece in pieces)
            else []
        )
        if not all(isinstance(p, list) and len(p) >= 2 and all(map(_known, p[:2])) for p in points):
            points = []
        run = "XY".index(axis) if axis in ("X", "Y") else None
        clear = self.stock_clear(setup)
        if clear is None or not _known(radius) or run is None:
            return ""
        # The outer ends are every piece's ends only when no keep-out split a pass.
        whole = bool(points) and all(min(abs(p[run] - end) for end in ends) <= 1e-9 for p in points)
        ends_name = "pass ends" if whole else "outer pass ends"
        low, high = sorted(ends)
        air = [s for v, s in ((low, -1), (high, 1)) if clear(run, v, radius, s)]
        every = bool(points) and all(any(clear(i, p[i], radius) for i in range(2)) for p in points)
        text = ""
        if len(air) == 2:
            text += f"; {ends_name} both in air, a cutter radius past the stock"
        elif air:
            side = "-" if air[0] < 0 else "+"
            text += f"; the {side}{axis} {ends_name[:-1]} is in air, a cutter radius past the stock"
        if every and air:
            text += " — every pass runs in and out clear"
        elif every:
            text += "; every pass runs in and out clear, a cutter radius past the stock"
        elif air and not whole:
            text += "; split passes also start and stop between them, not proven clear"
        entry, side = raster.get("entry_pass"), str(raster.get("open_side", "")).upper()
        across = 1 - run
        if (
            _known(entry)
            and side in ("-X", "+X", "-Y", "+Y")
            and "XY".index(side[1]) == across
            and clear(across, entry, radius, -1 if side[0] == "-" else 1)
        ):
            text += (
                "; pass 1 enters from air, a cutter radius outside the stock on the open "
                f"{side} side"
            )
        return text

    def outline_clearance(self, setup, profile, part):
        """A cutter-centre outline's rows whose cutter stands wholly outside the stock the
        setup receives (:meth:`stock_clear`) named as cutter clearance; without that box no
        row is."""
        clear, radius = self.stock_clear(setup), profile.get("cutter_radius_mm")
        points = profile.get("cutter_centre")
        if clear is None or not _known(radius) or not isinstance(points, list):
            return part
        rank, description, headings, rows, after = part
        named = sorted(
            {
                row[0] or f"row {index}"
                for index, (row, point) in enumerate(zip(rows, points, strict=False), start=1)
                if isinstance(point, list)
                and len(point) >= 2
                and all(map(_known, point[:2]))
                and any(clear(i, point[i], radius) for i in range(2))
            }
        )
        if named:
            description += (
                f"; {', '.join(named)} stand wholly clear of the stock: intentional cutter "
                "clearance for entry, exit and overtravel, not material"
            )
        return rank, description, headings, rows, after

    def level_path(self, setup, op_id):
        """The coordinates level-entry record of op ``op_id`` (rules/level_entry.py), or {}."""
        numbers = self.records.get(("coordinates", setup["id"]), {})
        for record in numbers.get("level_paths") or []:
            if str(_mapping(record).get("op")) == str(op_id):
                return record
        return {}

    def plunge_feed(self, setup, op):
        """The op's plunge feed in mm/min, or a STOP, with coordinates' reason, when it
        plunges without a known one (a tool not proven centre-cutting has none); None when
        nothing in its path plunges into the stock."""
        record = self.level_path(setup, op.get("op"))
        if "plunge_mm_rev" not in record:
            return None
        numbers = self.records.get(("speeds_feeds", f"{setup['id']}:{op['op']}"), {})
        feed = numbers.get("plunge_mm_min")
        if _known(record["plunge_mm_rev"]) and _known(feed):
            return f"{_number(feed, 0)} mm/min"
        why = record.get("plunge_reason")
        return "STOP: plunge feed not set" + (f" — {why}" if why else "")

    def level_entries(self, setup, op, waypoints):
        """One paragraph: how the op's path goes down at each depth level and gets back for
        the next, as coordinates proved it (``level_paths``); ``""`` without a record. The
        heading lists every level's Z, so several levels state the procedure once."""
        o = self.operative
        record = self.level_path(setup, op.get("op"))
        downs, depths = record.get("entries"), record.get("levels")
        if not (isinstance(downs, list) and downs and isinstance(depths, list) and depths):
            return ""
        feed = self.plunge_feed(setup, op)
        raised, raster = record.get("raise_z"), record.get("raster") is True
        above = " (above the stock)" if record.get("raise_clear") is True else ""
        at = f" at {feed}"
        if feed is None or feed.startswith("STOP"):
            at = f" — {feed}" if feed else ""
        start, several = record.get("from_z"), len(depths) > 1
        plunge = f"plunge Z {o(start)} → {o(depths[0])}{at}"
        if o(start) == o(depths[0]):
            # The op starts at its only level, but nothing proves that entry clear: fed
            # down to it, never "plunge Z a → a".
            plunge = f"plunge to Z {o(depths[0])}{at}"
        lower = f"lower to Z {o(depths[0])}"
        if several:
            plunge = f"plunge from the level above (level 1 from Z {o(start)}){at}"
            lower = "lower to the level's Z"
        # The op starts at its only level and the stock box puts that level at or above
        # the stock top: the cutter lowers to it at every entry, above nothing, and only
        # the path cuts.
        lowered = record.get("lowered") == "top" and not several
        if lowered:
            lower = f"lower to Z {o(depths[0])}, the top of the stock this op meets; the path "
            lower += "then cuts the stock left along it"

        def where(down):
            xy = down.get("xy") or ["unknown", "unknown"]
            label = self.waypoint(waypoints, op.get("op"), xy)
            return label or f"X {o(xy[0])}, Y {o(xy[1])}"

        def get_down():
            if raster:
                plunged = [d for d in downs if not d.get("air")]
                if lowered:
                    return f"at each pass start: {lower}"
                if not plunged:
                    return f"at each pass start, clear of the stock: {lower}"
                if len(plunged) == len(downs):
                    return "at each pass start: " + plunge
                return (
                    "at the pass starting "
                    + "; at the pass starting ".join(where(d) for d in plunged)
                    + f": {plunge}; at every other pass start, clear of the stock: {lower}"
                )
            steps = []
            for index, down in enumerate(downs):
                lead = "" if index == 0 else f"raise to Z {o(raised)}{above}, move to "
                if lowered:
                    steps.append(f"{lead}{where(down)}: {lower}")
                elif down.get("air"):
                    steps.append(f"{lead}{where(down)}, clear of the stock: {lower}")
                else:
                    steps.append(f"{lead}{where(down)}: {plunge}")
            return "; then ".join(steps)

        text = get_down()
        if not several:
            return _p(((text[:1].upper() + text[1:]) if raster else "Enter at " + text) + ".")
        first = where(downs[0])
        if raster:
            after = f"lift to Z {o(raised)}{above}, rapid back to pass 1"
        elif record.get("closed") is True:
            after = f"stay at {first}: the path ends where it starts"
        else:
            after = f"raise to Z {o(raised)}{above}, move back to {first}"
        return _p(
            f"{len(depths)} depth levels, top first, at the Zs in the heading: run the whole "
            f"path below at each. Get down {text}. Between levels, {after}."
        )

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
            method = arc.get("method")
            samples = arc.get("rows", [])
            subject = f"{setup['id']}:{arc.get('op')}"
            points, labels = [], []
            for index, record in enumerate(samples):
                points.append(record.get("dro_xy") or ["unknown", "unknown"])
                entry["z"].add(o(record.get("dro_tip_z", arc.get("dro_tip_z"))))
                key = row_id(subject, "arc_table", arc, index)
                labels.append(self.waypoint(waypoints, arc.get("op"), None, key))
            centre = arc.get("centre_setup_xy") or ["unknown", "unknown"]
            description = (
                f"Cutter-centre arc R{o(arc.get('cutter_centre_radius_mm'))} "
                f"about X {o(centre[0])}, Y {o(centre[1])}"
            )
            rows = []
            after = None
            if method == "stairs":
                headings = ["P", "X", "Y", "Z", "handwheel axis"]
                for label, xy, record in zip(labels, points, samples, strict=True):
                    if record.get("corner"):
                        label = f"{label} (corner)" if label else "corner"
                    rows.append(
                        [
                            label,
                            o(xy[0]),
                            o(xy[1]),
                            o(record.get("dro_tip_z", arc.get("dro_tip_z"))),
                            _text(record["jog"]) if record.get("jog") in ("X", "Y") else "",
                        ]
                    )
                description += (
                    f"; rough stairs kept outside {self.arc_line(setup, arc.get('op'))}, "
                    "one handwheel axis per row, " + _leftover(arc)
                )
            elif method == "chain_drill":
                headings = ["hole #", "P", "X", "Y"]
                rows = [
                    [str(index), label, o(xy[0]), o(xy[1])]
                    for index, (label, xy) in enumerate(zip(labels, points, strict=True), 1)
                ]
                description = (
                    f"Chain drill: drill Ø{_number(arc.get('drill_dia_mm'))} mm, "
                    f"pitch {_number(arc.get('pitch_mm'))} mm; every hole outside "
                    + self.arc_line(setup, arc.get("op"))
                )
                after = f"After drilling, {_text(arc.get('break_out'))}; " + _leftover(arc) + "."
            elif method == "chords":
                headings = [
                    "chord #",
                    "from P",
                    "from X",
                    "from Y",
                    "to P",
                    "to X",
                    "to Y",
                    "length mm",
                    "sagitta mm",
                    "index °",
                    "handwheel cut",
                ]
                for index, chord in enumerate(arc.get("chords", []), 1):
                    start, stop = chord["from"], chord["to"]
                    cut = _mapping(chord.get("cut"))
                    index_angle = cut.get("index_deg")
                    along = cut.get("along")
                    if (
                        along in ("X", "Y")
                        and all(_known(cut.get(key)) for key in ("at", "from", "to"))
                        and (index_angle is None or _known(index_angle))
                    ):
                        fixed = "Y" if along == "X" else "X"
                        handwheel = [
                            f"lock {fixed} at {o(cut['at'])}",
                            f"feed {along} {o(cut['from'])} → {o(cut['to'])}",
                        ]
                    else:
                        handwheel = _Box("STOP: chord handwheel cut not established")
                    rows.append(
                        [
                            str(index),
                            labels[start],
                            o(points[start][0]),
                            o(points[start][1]),
                            labels[stop],
                            o(points[stop][0]),
                            o(points[stop][1]),
                            _number(chord.get("length_mm")),
                            _number(chord.get("sagitta_mm")),
                            _number(index_angle) if index_angle is not None else "",
                            handwheel,
                        ]
                    )
                band = arc.get("band_mm") or ["unknown", "unknown"]
                description += (
                    f"; straight chords: chord ends sit on R {_number(arc.get('edge_radius_mm'))} "
                    f"mm and every chord stays inside R {_number(band[0])}–{_number(band[1])} mm"
                    "; index the table to the listed angle where present; lock the fixed "
                    "axis and feed only the listed handwheel"
                )
            elif method == "rotary_table":
                rotary = _mapping(arc.get("rotary"))
                feature = self.feature_name(rotary.get("centre_feature"))
                if rotary.get("centre_by") == "pin":
                    locate = (
                        f"a pin of Ø{_number(rotary.get('pin_dia_mm'))} mm through {feature} "
                        f"into the table's Ø{_number(rotary.get('table_bore_dia_mm'))} mm centre "
                        f"bore (the centre may shift up to {_number(rotary.get('centre_play_mm'))}"
                        " mm)"
                    )
                elif rotary.get("centre_by") == "indicate":
                    locate = f"indicate {feature}"
                else:
                    locate = "STOP: arc-centre location method not established"
                if rotary.get("convex") is True:
                    side, sign = "convex", "plus"
                elif rotary.get("convex") is False:
                    side, sign = "concave", "minus"
                else:
                    side, sign = "? unknown cutter side", "?"
                description = [
                    f"{_text(rotary.get('table_name'))}: centre the table under the spindle "
                    "by indicating its centre bore, then set DRO X0 Y0.",
                    f"Put the arc centre on the table axis: {locate}.",
                    f"For this {side} arc, offset the table to "
                    f"X {o(rotary.get('offset_x'))} "
                    f"(R {_number(rotary.get('cut_radius_mm'))} mm {sign} cutter radius "
                    f"{_number(rotary.get('cutter_radius_mm'))} mm).",
                    f"Lock X and Y; set Z {o(arc.get('dro_tip_z'))}; turn the table "
                    f"{_text(rotary.get('rotation'))} from {_number(rotary.get('start_deg'))}° "
                    f"to {_number(rotary.get('stop_deg'))}° (sweep "
                    f"{_number(rotary.get('sweep_deg'))}°), reading the dial to "
                    f"{_number(rotary.get('resolution_deg'))}°; this is the conventional-cut "
                    "direction, viewed from above.",
                ]
                entry["parts"].append((order(entry, arc), description, [], [], None))
                continue
            else:
                entry["stops"].append("manual arc method not established")
                continue
            description += self.cut_order(arc) + self.clip(
                arc, [row.get("clipped_at") for row in samples], rows
            )
            entry["parts"].append((order(entry, arc), description, headings, rows, after))
        for line in numbers.get("line_table", []):
            entry = block(line.get("op"))
            rows = []
            subject = f"{setup['id']}:{line.get('op')}"
            proven = self.records.get(("accessibility", subject), {})
            proven = proven.get("checkpoint_overshoot_ok") if isinstance(proven, dict) else None
            proven = set(proven) if isinstance(proven, list) else set()
            printed, flags = line.get("dro_xy") or [], line.get("overshoot") or []
            axes = line.get("jog") or []
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
                        _text(axes[index])
                        if index < len(axes) and axes[index] in ("X", "Y")
                        else "",
                    ]
                )
            side = _text(line.get("side"))
            description = f"Straight joins on the {side} side" + self.cut_order(line)
            description += self.clip(line, line.get("clipped_at") or [], rows)
            if axes:
                description += "; one handwheel axis per row"
                if _known(line.get("stair_cusp_mm")):
                    # A bound: rounded up onto the DRO grid, never printed finer than it.
                    step = dro_grid(self.bundle, setup)[0]
                    cusp = math.ceil(round(line["stair_cusp_mm"] / step, 6)) * step
                    description += f", the stair leaves ≤ {o(cusp)}"
            headings = ["P", "", "X", "Y", "Z", "handwheel axis"]
            entry["parts"].append((order(entry, line), description, headings, rows, None))
        arc_ops = {str(arc.get("op")) for arc in numbers.get("arc_table", []) or []}
        raster_stages = {}
        for profile in numbers.get("profiles", []):
            if isinstance(profile, dict) and isinstance(profile.get("raster"), dict):
                raster_stages.setdefault(str(profile.get("op")), set()).add(profile.get("stage"))
        for profile in numbers.get("profiles", []):
            op = str(profile.get("op"))
            if op in arc_ops:
                continue
            points = profile.get("cutter_centre")
            entry = block(op)
            if not isinstance(points, list) or not points:
                entry.setdefault("unresolved", True)
                for reason in ("clip_reason", "stair_reason", "allowance_reason"):
                    stop = _text(profile.get(reason)) if profile.get(reason) else None
                    if stop and stop not in entry["stops"]:
                        entry["stops"].append(stop)
                continue
            z = o(profile.get("dro_to_z", profile.get("to_z")))
            entry["z"].add(z)
            rows = []
            headings = ["P", "angle °", "X", "Y", "Z", "handwheel axis"]
            axes = profile.get("jog") or []
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
                            _text(point["jog"]) if point.get("jog") in ("X", "Y") else "",
                        ]
                    )
                elif len(point) == 2 and all(isinstance(p, list) for p in point):
                    headings = ["pass", "X from", "Y from", "X to", "Y to", "Z"]
                    rows.append([str(len(rows) + 1), *(o(v) for p in point for v in p), z])
                else:
                    index = len(rows)
                    rows.append(
                        [
                            self.waypoint(waypoints, op, point[:2]),
                            "",
                            o(point[0]),
                            o(point[1]),
                            z,
                            _text(axes[index])
                            if index < len(axes) and axes[index] in ("X", "Y")
                            else "",
                        ]
                    )
            description = "Cutter-centre checkpoints" + self.cut_order(profile)
            raster = profile.get("raster")
            if isinstance(raster, dict):
                entry["raster"] = True
                # The table gives the passes, their ends and order, the op row the stage, the
                # level note the entry: this says how each pass ends and what is proven in air.
                # An op rastered in both stages names each table's.
                stage = profile.get("stage")
                description = f"Lift to Z {o(raster.get('lift_z'))} after each pass"
                if len(raster_stages.get(op, ())) > 1:
                    description = f"{_text(stage).capitalize()}: l" + description[1:]
                description += self.cut_order(profile, narrate=False)
                # One clearance note per op while its pieces prove the same; a stage whose
                # pieces prove otherwise prints its own.
                note = self.raster_clearance(setup, profile)
                if note != entry.get("ends"):
                    entry["ends"] = note
                    description += note
            entry["parts"].append((order(entry), description, headings, rows, None))
            if not isinstance(raster, dict):
                entry["parts"][-1] = self.outline_clearance(setup, profile, entry["parts"][-1])
        # Surface, tool and stair X all read on the lathe DRO's X display; unread, the
        # dome's blocks stop rather than print a radius as a diameter or the reverse.
        x_unit = {"radius": "radius", "diameter": "Ø"}.get(numbers.get("x_display"))
        unread = _X_DISPLAY_STOP.removeprefix("STOP: ")
        for contour in numbers.get("contours", []):
            if not isinstance(contour, dict) or contour.get("method") != "axial_table":
                continue
            entry = block(contour.get("op"))
            if x_unit is None:
                entry["stops"].append(unread)
                continue
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
            if _known(contour.get("apex_z_mm")) and _known(contour.get("base_z_mm")):
                if contour["apex_z_mm"] > contour["base_z_mm"] and rows:
                    first = rows[0][0] or f"the Z {rows[0][2]} row"
                    last = rows[-1][0] or f"the Z {rows[-1][2]} row"
                    description += (
                        ". Row to row: move X out to the next row first, then Z toward the "
                        "chuck (Z first gouges the dome). Enter at "
                        f"{first} from +Z; leave radially, X out, at {last}"
                    )
            for row, record in zip(rows, contour.get("rows", []), strict=True):
                tip_x = record.get("x_tool_mm")
                if not (compensated and _known(tip_x) and tip_x < 0):
                    continue
                normal = math.radians(record.get("normal_deg", 0.0))
                centre = record.get("radius_mm", 0.0) + compensation * math.cos(normal)
                where = "on the axis" if abs(centre) < 1e-6 else f"at radius {o(centre)}"
                description += (
                    f". {row[0] or 'Z ' + row[2]} tool X {o(tip_x)} {x_unit} is intentional: "
                    f"the R{o(compensation)} nose centre is {where} there (imaginary tip "
                    "past centre)"
                )
            # The finished surface: the finish pass after any rough stair of its op.
            entry["parts"].append(
                (order(entry, {"stage": "finish"}), description, headings, rows, None)
            )
        for stair in numbers.get("stair_tables", []):
            entry = block(stair.get("op"))
            if x_unit is None:
                entry["stops"].append(unread)
                continue
            rows = [
                [str(index), o(r.get("z_mm")), o(r.get("x_target_mm"))]
                for index, r in enumerate(stair.get("rows", []), 1)
            ]
            description = (
                f"Rough stair, leaves {o(stair.get('allowance_mm'))} mm on diameter for the "
                "finish table: for each row, from outside the work at the row's Z, face in to "
                f"X, then back out radially. X ({x_unit}) / Z are the DRO readings of the "
                "imaginary tip, touched off on an outside diameter and a +Z end face"
            )
            if not rows:
                description += "; no row cuts: the allowance already covers the work"
            entry["parts"].append(
                (order(entry, stair), description, ["row", "Z", f"in to X ({x_unit})"], rows, None)
            )
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
            levels = self.z_levels(setup, op) if op else None
            depths = levels.get("levels") if levels else None
            stepped = isinstance(depths, list) and len(depths) > 1
            if stepped:
                title += " · Z " + ", ".join(o(z) for z in depths)
            elif len(entry["z"]) == 1:
                title += f" · Z {next(iter(entry['z']))}"
            if op.get("direction"):
                title += f" · {self.direction(op['direction'])}"
            content = f"<h3>{escape(title)}</h3>"
            note = self.level_entries(setup, op, waypoints) if op else ""
            if note:
                content += note
            elif stepped:
                # The heading lists the levels; the note says how to run them, once per op.
                content += _p(
                    f"{len(depths)} depth levels: run the complete path below at each Z in the "
                    "heading, in order, top level first."
                )
            elif levels and levels.get("count") == "unknown":
                content += _p("? Depth levels not computed — " + _text(levels.get("reason")) + ".")
            if stepped and entry["parts"]:
                # The whole path runs once per level: a box to tick as each level is done.
                count = len(depths)
                content += (
                    '<p class="levels">Done: '
                    + " ".join(
                        f'<span class="tick"></span>level {k} of {count}'
                        for k in range(1, count + 1)
                    )
                    + "</p>"
                )
            tool_missing = op.get("tool") in (None, "unknown") or not tools.get(op.get("tool"))
            wide = self.lathe(setup)
            if tool_missing:
                content += _p(
                    f"STOP: {self.feature_name(op.get('feature')).upper()} — tool not selected; "
                    "do not run.",
                    "stop",
                )
            elif not entry["parts"]:
                reasons = "".join(f" — {reason}" for reason in dict.fromkeys(entry["stops"]))
                content += _p(f"STOP: contour points not computed{reasons} — do not run.", "stop")
            else:
                pieces = []
                # The moves are numbered on through the op's tables: a table whose rows are
                # picture points gets a leading # column that carries on from the last.
                moves = 0
                for rank, description, headings, rows, after in sorted(
                    entry["parts"], key=lambda p: p[0]
                ):
                    if isinstance(description, list):
                        pieces.append(_list(description))
                        continue
                    # One Z for every row prints once, in the heading (and the heading each
                    # continued page repeats); under several depth levels each level's Z is
                    # in the heading, so no path row prints one Z for every level.
                    single = len(entry["z"]) == 1
                    columns = [
                        i
                        for i, h in enumerate(headings)
                        if any(row[i] for row in rows) and not (h == "Z" and (single or stepped))
                    ]
                    shown = [headings[i] for i in columns]
                    cells = [[row[i] for i in columns] for row in rows]
                    if headings[:1] == ["P"]:
                        shown = ["#", *shown]
                        cells = [[str(moves + n), *row] for n, row in enumerate(cells, 1)]
                        moves += len(cells)
                    # Side by side on a wide block, each table names its stage.
                    label = {0: "ROUGH", 1: "FINISH"}.get(rank[0]) if wide else None
                    pieces.append(
                        (f"<h4>{label}</h4>" if label else "")
                        + _p(self.bench(description) + ".")
                        + _table(
                            shown,
                            cells,
                            css="coords",
                            repeat=title,
                            strong=[i for i, h in enumerate(shown) if h.startswith("tool ")],
                        )
                        + (_p(after) if after else "")
                    )
                if wide and len(pieces) > 1:
                    content += (
                        '<div class="stages">'
                        + "".join(f"<div>{piece}</div>" for piece in pieces)
                        + "</div>"
                    )
                else:
                    content += "".join(pieces)
            css = "contour wide" if wide else "contour"
            html.append(f'<div class="{css}">{content}</div>')
        heading = (
            f"<h2>CONTOURS — {escape(self.zero_name(setup))}; "
            + (
                {"diameter": "X is diameter", "radius": "X is radius"}.get(
                    numbers.get("x_display"), "X: ? radius or diameter"
                )
                if self.lathe(setup)
                else "cutter-centre X / Y"
            )
            + "</h2>"
        )
        if any(entry.get("raster") for entry in blocks.values()):
            # A lead-in: the pagination keeps it, and its heading, with the first block.
            heading += _p(
                "Rasters: feed each pass from → to, lift to the op's lift Z, rapid back to the "
                "next pass's start.",
                "lead-in",
            )
        wide = any(arc.get("method") == "chords" for arc in numbers.get("arc_table", []) or [])
        css = "contours wide" if wide else "contours"
        return heading + f'<div class="{css}">' + "".join(html) + "</div>"

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

    def fixture_render(self, setup):
        """The holding picture with its caption and NOT SHOWN lines."""
        render = self.report.get("renders", {}).get(setup["id"])
        if not render:
            return ""
        scene = _mapping(render.get("scene"))
        fixture = self.reference(_mapping(setup.get("hold")).get("fixture"), "fixtures")
        caption = [f"Setup {setup['id']} — {self.arrival(setup)}, held in the {fixture}."]
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
        features = {name for op in setup["ops"] for name in op_features(op)}
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

    def receiving_setup(self, ref):
        """The first setup the stock ``ref`` (``stock`` or ``stock.<id>``) arrives in."""
        for setup in self.plan.get("setups", []):
            source = setup.get("stock_in")
            if ref in (source if isinstance(source, list) else [source]):
                return setup
        return None

    def stock_line(self, stock, ref="stock"):
        """Stock size and supply notes on the DRO grid of the machine it first goes to."""
        stock = _mapping(stock)
        decimals = dro_grid(self.bundle, self.receiving_setup(ref) or {})[1]

        def o(value):
            return self.operative(value, decimals)

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
            if key in {"on_hand", "prerequisite"}:
                continue  # Outstanding before the first setup: printed in JOB STATUS.
            if key == "prepared":
                continue  # Printed as CHECK THE BLANK before the setup that receives it.
            if key == "note":
                extras.append(self.bench(value).rstrip(".") + ".")
                continue
            name = _text(key)
            unit = " mm" if name.endswith(" mm") else ""
            name = name.removesuffix(" mm")
            shown = o(value) + unit if _known(value) else self.bench(value)
            extras.append(f"{name[:1].upper() + name[1:]}: {shown}.")
        return " ".join([line, *extras])

    def flip(self, setup):
        """The part turns over between setups when this setup's Z points against the arriving
        setup's Z in the model; say so first, with which face goes up and which X end stays."""
        source = setup.get("stock_in")
        previous = next(
            (
                s
                for s in self.plan.get("setups", [])
                if isinstance(source, str) and s["id"] == source
            ),
            None,
        )
        if previous is None:
            return ""
        here, there = setup_frame(self.bundle, setup), setup_frame(self.bundle, previous)
        vectors = [_mapping(frame).get(k) for frame in (here, there) for k in ("z", "x")]
        if not all(isinstance(v, list) and len(v) == 3 and all(map(_known, v)) for v in vectors):
            return ""
        z, x, z_before, x_before = vectors
        if sum(a * b for a, b in zip(z, z_before, strict=True)) > -0.5:
            return ""
        if self.lathe(setup):
            return "Turn the part end for end. "
        top = _mapping(setup.get("stock_state")).get("top_feature")
        up = f"{self.feature_name(top)} up" if top else "the other face up"
        # Where the old +X end lands in this setup's frame: along X, or (turned a quarter
        # turn as well) along Y = Z × X. A unit X in the XY plane is within 45° of one.
        y = [z[1] * x[2] - z[2] * x[1], z[2] * x[0] - z[0] * x[2], z[0] * x[1] - z[1] * x[0]]
        along_x = sum(a * b for a, b in zip(x, x_before, strict=True))
        along_y = sum(a * b for a, b in zip(y, x_before, strict=True))
        if abs(along_x) >= abs(along_y):
            ends = "the +X end stays at +X" if along_x > 0 else "the +X end moves to −X"
        else:
            ends = f"the +X end moves to {'+' if along_y > 0 else '−'}Y"
        return f"Turn the part over: {up}, {ends}. "

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
            value = self.surface_z(setup, value, face="top" if key == "top_z" else None)
            parts.append(f"{name} at Z {o(value)}" if _known(value) else f"{name} Z ? not set")
        line = self.flip(setup) + f"Starts from: {self.arrival(setup)}"
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
        return "Speeds and feeds are starting points, not limits."

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
            if _mapping(definition.get("preparation")):
                # Plan stock preparation (a faced end, a centre): the route makes it, the
                # drawing never asks for it, so it is no acceptance row.
                continue
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
        # A nominal stock thickness is no limit: print it only when no feature carries one.
        limited = any(
            "thickness" in tolerance_requirements(definition)
            for definition in self.features.values()
        )
        if _known(thickness) and not limited:
            rows.append(("part", f"finished thickness {self.value(thickness)}"))
        rows.append(("all edges", self.edge_break()))
        html = "<h2>DRAWING REQUIREMENTS</h2>" + _table(
            ["feature", "limits"], rows, widths=[30, 70]
        )
        if joint_prep:
            html += f"<h2>{escape(JOINT_PREP_LABEL)}</h2>" + _table(
                ["plan feature", "limits"], joint_prep, widths=[30, 70]
            )
        return html

    def process_holds(self, setups):
        """Every op's in-process holds, gathered on the job page under their own heading so
        they are never read as drawing limits: where, what the gauge reads at the hold band,
        the gauge, the drawing's own limit (REF for a reference-only span) and why."""
        rows = []
        for setup in setups:
            for op in setup.get("ops", []):
                for hold in op.get("process_holds", []):
                    reading, gauge, drawing, _ = self.process_hold_parts(hold)
                    where = f"{setup['id']} op {op['op']}"
                    rows.append((where, reading, gauge, drawing, self.bench(hold["reason"])))
        if not rows:
            return ""
        return f"<h2>{escape(PROCESS_HOLDS_LABEL)}</h2>" + _table(
            ["setup / op", "hold", "gauge", "drawing", "why"],
            rows,
            widths=[10, 26, 18, 18, 28],
        )

    def edge_break(self):
        """The drawing's edge break, printed once for the whole job."""
        note = _mapping(self.bundle.features.get("notes")).get("edge_break")
        if isinstance(note, str) and note.strip() and note != "unknown":
            return note
        general = _mapping(self.bundle.features.get("general_tolerances"))
        radius, chamfer = general.get("edge_break_r"), general.get("chamfer_max")
        limits = ([f"break sharp edges R{self.value(radius)} max"] if _known(radius) else []) + (
            [f"chamfer {self.value(chamfer)} max"] if _known(chamfer) else []
        )
        if limits:
            return "Remove burrs; " + " or ".join(limits) + "."
        planned = sorted(
            {
                self.operative(setup["deburr_mm"])
                for setup in self.plan.get("setups", [])
                if _known(setup.get("deburr_mm"))
            }
        )
        return "? edge break not on the drawing" + (
            f"; plan breaks edges {' / '.join(planned)} mm max" if planned else ""
        )

    def setup_edge_break(self, setup):
        """A setup's own edge-break limit, when it is not the drawing's: the job page
        carries the drawing's once, so only a different (tighter) setup limit prints."""
        deburr = setup.get("deburr_mm")
        if not _known(deburr) or float(deburr) <= 0:
            return ""
        general = _mapping(self.bundle.features.get("general_tolerances"))
        drawing = [general.get("edge_break_r"), general.get("chamfer_max")]
        drawing = [float(v) for v in drawing if _known(v) and float(v) > 0]
        if drawing and abs(float(deburr) - min(drawing)) < 1e-9:
            return ""
        # The author's reason reads at the machine; a source-file cite does not.
        cite = setup.get("deburr_cite")
        cites = cite if isinstance(cite, list) else [cite]
        why = "; ".join(self.bench(c) for c in cites if isinstance(c, str) and " " in c.strip())
        text = f"Break edges {self.operative(deburr)} mm max in this setup"
        text += f", not the drawing's {self.value(min(drawing))}" if drawing else ""
        return _p(text + (f": {why.rstrip('.')}" if why.strip() else "") + ".")

    def drawing_revision(self):
        revision = self.plan.get("drawing", {}).get("revision", "unknown")
        return revision if isinstance(revision, str) and revision != "unknown" else None

    def job_state(self, topics):
        """What still stands in the way of running, the release state the banner shows, and
        what must be in hand before the first setup: the job page never reads clear beside
        NOT APPROVED. The checker's own result is not shop information."""
        state = []
        if self.report.get("verification") != "checked":
            state.append("Not ready to run: clear the items above first.")
        elif topics:
            state.append(f"{len(topics)} check(s) not verified, listed above.")
        evidence = self.approval.get("first_article")
        recorded = isinstance(evidence, str) and evidence.strip().lower() not in ("", "unknown")
        this_plan = bool(self.approval) and self.approval.get("hash") == self.report.get("hash")
        if self.checked:
            state.append("Approved: the first article is recorded against this exact plan.")
        elif recorded and this_plan:
            state.append(
                "NOT APPROVED: a first article is recorded for this plan, but the plan has "
                "open items above and approval cannot waive them."
            )
        else:
            state.append(
                "NOT APPROVED: "
                + (
                    "the recorded first article was made to a different plan or drawing"
                    if recorded
                    else "no first article is recorded"
                )
                + "; the first part made is the first article — sign it off below."
            )
        stock = _mapping(self.plan.get("stock"))
        components = stock.get("components")
        pieces = [("stock", stock)] + [
            (f"stock {_text(_mapping(c).get('id'))}", _mapping(c))
            for c in (components if isinstance(components, list) else [])
        ]
        first = _text(_mapping((self.plan.get("setups") or [{}])[0]).get("id"))
        for name, piece in pieces:
            if piece.get("on_hand") is False:
                state.append(f"Before {first}: obtain the {name} — not on hand.")
            prerequisite = piece.get("prerequisite")
            if isinstance(prerequisite, str) and prerequisite not in ("unknown", ""):
                state.append(f"Before {first}: {self.bench(prerequisite).rstrip('.')}.")
        return state

    def dro_resolution(self, setups):
        """Each routed machine's DRO step: the grid every printed DRO target is on."""
        grids = {}
        for setup in setups:
            reference = setup.get("machine")
            if reference in grids or saw_setup(setup) or manual_bench(self.bundle, setup):
                continue
            machine = self.machine(setup)
            step, decimals = dro_grid(self.bundle, setup)
            grid = f"{self.reference(reference, 'machines')} {step:.{decimals}f} {self.units}"
            if not _known(length_mm(machine, "resolution")):
                grid += " (resolution not in the shop list: default grid)"
            if machine.get("kind") == "lathe":
                radius = _mapping(self.plan.get("dro")).get("radius_mode")
                grid += (
                    " (X reads radius)"
                    if radius is True
                    else " (X reads diameter)"
                    if radius is False
                    else " (X: ? radius or diameter)"
                )
            grids[reference] = grid
        if not grids:
            return None
        return "DRO resolution: " + "; ".join(grids.values()) + ". DRO targets print on this grid."

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
        html += self.status_boxes(stops, cautions, topics)
        html += _list(self.job_state(topics), ordered=False)
        dro = _mapping(self.plan.get("dro"))
        lines = [self.material(), self.speeds_source()]
        # The setup sheets are written first: a marked fixture row puts its legend here.
        lines.append(EXAMPLE_LEGEND if self.example_marks else None)
        if dro.get("manual") or dro.get("controller") not in (None, "unknown"):
            name = dro.get("manual") if isinstance(dro.get("manual"), str) else dro["controller"]
            lines.append(
                f"DRO: {self.bench(name)}, {_text(dro.get('mode')).upper()} mode; zero with "
                "Axis Set, never Preset."
            )
        lines.append(self.dro_resolution(setups))
        html += "".join(_p(line) for line in lines if line)
        html += "<h2>STOCK AND ROUTE</h2>"
        stock = _mapping(self.plan.get("stock"))
        components = stock.get("components")
        if isinstance(components, list) and components:
            html += _list(
                [
                    f"{_text(_mapping(c).get('id'))}: "
                    + self.stock_line(c, f"stock.{_text(_mapping(c).get('id'))}")
                    for c in components
                ],
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
        html += self.process_holds(setups)
        keys = self.abbreviations(html)
        html += _p(" ".join(keys)) if keys else ""
        return html

    def abbreviations(self, page=""):
        """The key to the abbreviations ``page`` and the setup sheets actually print."""
        printed = getattr(self, "sheet_text", "") + " " + re.sub(r"<[^>]+>", " ", page)
        return [meaning for pattern, meaning in _ABBREVIATIONS if re.search(pattern, printed)]

    # ------------------------------------------------------------------ setup
    def setup_section(self, setup):
        """One front sheet to run the setup from, then attached sheets it points to.

        Front: status, HOLD, tools, DRO zero and the op table. Sheet 2: picture,
        clearance, feature map and inspection notes, when any. Then contours, then one
        worksheet per procedure that records readings.
        """
        self.setup = setup
        sid = setup["id"]
        machine = self.reference(setup.get("machine"), "machines")
        kind = self.machine(setup).get("kind")
        tool_numbers, tools, tool_html = self.tool_table(setup)
        contours = self.contours(setup, tools)
        # Bench work has no spindle, DRO or cutting axes: no zero and no machine clearance.
        bench = manual_bench(self.bundle, setup)
        details = {
            "holding picture": self.fixture_render(setup),
            "shop-made fixture": self.shop_made_tables(setup),
            "clearance": None if bench else self.clearance(setup, tool_numbers),
            "feature map": self.feature_map(setup),
        }
        # Worksheets follow the contours, one sheet each.
        sheets = {"notes": 2, "contours": 3 if contours else None}
        sheets["worksheets"] = (sheets["contours"] or 2) + 1
        ops_html, notes_html, worksheets, op_stops = self.operations(setup, tool_numbers, sheets)
        details["inspection notes"] = notes_html
        details["blank check"] = self.blank_checks(setup)
        details = {subject: block for subject, block in details.items() if block}
        if not details and (contours or worksheets):
            # Nothing for sheet 2: the contours, else the first worksheet, are sheet 2.
            sheets["contours"] = 2 if contours else None
            sheets["worksheets"] = (sheets["contours"] or 1) + 1
            ops_html, notes_html, worksheets, op_stops = self.operations(
                setup, tool_numbers, sheets
            )
        stops, cautions, topics = self.status_lines(
            self.setup_findings(setup), setup, skip_ops=True
        )
        every = self.cutting_ops(setup)
        for text, ops in op_stops.items():
            label = _ops_label(ops, every)
            stops.append(f"{label[:1].upper() + label[1:]} — {text}")
        count = 1 + bool(details) + bool(contours) + len(worksheets)
        title = (
            f"SETUP {sid} — {machine}"
            + (f" ({_text(kind)})" if kind and _text(kind) not in machine else "")
            + f" · sheet 1 of {count}"
        )
        self.setup_stops[sid] = len(stops)
        status = f"<h2>{escape(title)}</h2>" + self.status_boxes(stops, cautions, topics)
        if setup.get("note"):
            status += _p(self.bench(setup["note"], setup))
        status += self.stock_state(setup)
        steps, hold_below = self.hold(setup)
        coolant = "" if bench else _p(f"Coolant: {self.bench(setup.get('coolant'))}.")
        coolant += self.setup_edge_break(setup)
        # The full-size picture is on sheet 2; the front sheet keeps the HOLD steps wide.
        unpictured = (
            ""
            if self.report.get("renders", {}).get(sid)
            else _p("NO PICTURE — the holding is not modelled; set up from the HOLD steps.", "stop")
        )
        front = [
            status,
            f'<div class="hold-row"><div class="hold-steps">{steps}</div>'
            f"{unpictured}</div>{hold_below}{coolant}",
            tool_html,
            None if bench else self.dro(setup, tools),
            ops_html,
        ]

        def attached(number, subject, blocks):
            heading = f"<h2>SETUP {escape(sid)} — sheet {number} of {count}: {subject}</h2>"
            return [heading + blocks[0], *blocks[1:]]

        result = [[block for block in front if block]]
        if details:
            subjects = list(details)
            subject = ", ".join(subjects[:-1]) + (" and " if len(subjects) > 1 else "")
            result.append(attached(2, subject + subjects[-1], list(details.values())))
        if contours:
            result.append(attached(len(result) + 1, "contours", [contours]))
        for head, worksheet in worksheets:
            result.append(attached(len(result) + 1, f"worksheet, {escape(head)}", [worksheet]))
        self.setup = None
        return result

    def render(self):
        setups = self.plan.get("setups", [])
        # Setup pages are built first so the job status can name every stopped setup.
        sheets = [self.setup_section(s) for s in setups]
        # The job page's abbreviation key names only what these sheets print.
        self.sheet_text = " ".join(
            re.sub(r"<[^>]+>", " ", block)
            for setup_sheets in sheets
            for blocks in setup_sheets
            for block in blocks
            if block
        )
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
        banner = "CHECKED — FIRST ARTICLE RECORDED" if self.checked else "PLANNED — NOT APPROVED"
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
            # Continuation pages open with the sheet's name: "SETUP S2 — sheet 3".
            title = label.upper() if label == "job page" else label.replace(" sheet ", " — sheet ")
            result.append(
                f'<section class="page" data-sheet="{escape(label)}" data-title="{escape(title)}">'
            )
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
    # A member's display name is its own: a named kit does not name each of its pieces.
    own = _mapping(_mapping(raw.get("members")).get(member)) if member else {}
    named_member = bool(own.get("name") or own.get("label"))
    named = own if member else raw or record
    name = named.get("name", named.get("label"))
    if not name:
        if category == "machines" or root in _mapping(bundle.inventory.get("machines")):
            # A maker's model number (PM-30MV) is the machine's name; any other identity
            # is an inventory slug, so the operator reads the machine's kind instead.
            model = re.fullmatch(r"[A-Z0-9]+(?:-[A-Z0-9]+)*", root) and re.search(r"\d", root)
            name = root if model else _text(record.get("kind", "machine"))
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
    if member and not named_member:
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
            member = re.sub(r"^(\d+(?:\.\d+)?)(in|mm)$", r"\1 \2", member)
            member = re.sub(r"-(\d+)fl", r" \1-flute", member)
            # Remaining word-to-word hyphens are slug separators, not part of a size.
            member = re.sub(r"(?<=[a-z])-(?=[a-z])", " ", member)
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
