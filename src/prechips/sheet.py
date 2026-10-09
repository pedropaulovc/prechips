"""Printable bench instructions from the validated bundle and fresh rule findings.

The traveler is the shop-floor copy: one setup per section, in shop language.
Operative targets print at DRO resolution; full precision, rule identities,
hashes and uncertainty records stay in report.json. Unresolved inputs are never
hidden: they print as plain STOP lines, op-row boxes or a "not verified" line.
"""

from __future__ import annotations

import functools
import json
import math
import re
from dataclasses import dataclass
from html import escape
from importlib.resources import files

from . import trig
from .clamp_labels import clamp_labels
from .joint_features import JOINT_PREP_LABEL, setup_ancestry
from .measurements import length_fact, record_trusted
from .model import TOLERANCE_REQUIREMENTS, reference_only, tolerance_requirements
from .rules._bench import manual_bench
from .rules._envelope import measurement_item
from .rules.coordinates import (
    CENTRE_OPS,
    OVERSHOOT_NOTE,
    dro_grid,
    dro_z,
    faced_aim_claims,
    row_id,
)
from .rules.geometry_common import TURNING, approach
from .rules.hold_fields import align_indicator, align_travel
from .rules.inspection import ZONES, go_no_go_pair
from .rules.resolution import (
    HAND_FINISH,
    MAKE_OP_FIELDS,
    MANUAL,
    NAMED_REFERENCE,
    SAW_OPS,
    UNKNOWN,
    WORKHOLDING_CATEGORIES,
    authored,
    authored_names,
    coating_process,
    drawing_precision,
    identity,
    jaw_top_z,
    length_mm,
    make_op_unknowns,
    make_ops,
    make_tool,
    named_item,
    op_feature,
    op_features,
    printed_band,
    projection_holder,
    resolve,
    saw_setup,
    select,
    setup_frame,
    setup_items,
    shop_made_item,
    tool_numbers,
    uncertain,
)
from .rules.resolution import record as _mapping
from .rules.tip_endpoints import (
    FACING,
    SAME_Z,
    arrival_zs,
    operative_z,
    stock_states,
    transfer,
)
from .rules.zero_recipe import DIRECTIONS as _SIGNS
from .rules.zero_recipe import FACE_Z_TOL_MM

_CSS = (
    files("prechips").joinpath("tokens.css").read_text(encoding="utf-8")
    + """
@page { size: Letter portrait; margin: var(--page-margin); }
* { box-sizing: border-box; }
html, body { overflow-x: clip; }
body { margin: 0; color: var(--color-ink); background: var(--color-paper);
font: var(--text-working)/var(--line-working) var(--font-working);
font-variant-numeric: tabular-nums; overflow-wrap: anywhere; }
.page { break-after: page; page-break-after: always; min-width: 0; }
.page:last-child { break-after: auto; page-break-after: auto; }
h1, h2, h3, h4 { font-style: normal; line-height: 1.35; overflow-wrap: anywhere; }
h1 { margin: 0; font-size: var(--text-title); }
h2 { font-size: var(--text-section); margin: var(--space-lg) 0 var(--space-sm);
border-bottom: var(--rule-thin) solid var(--color-ink);
break-after: avoid; page-break-after: avoid; }
h3, h4 { font-size: var(--text-operation); margin: var(--space-md) 0 var(--space-xs);
break-after: avoid; page-break-after: avoid; }
p { margin: var(--space-xs) 0; }
.meta { display: flex; justify-content: space-between; gap: var(--space-sm);
align-items: flex-start; font-size: var(--text-running); }
.meta > * { min-width: 0; }
.banner { border: var(--rule-warning) solid var(--color-ink); font-weight: bold;
padding: var(--space-xs) var(--space-sm); margin: var(--space-sm) 0; }
.stop { border: var(--rule-warning) solid var(--color-ink);
padding: var(--space-sm); margin: var(--space-sm) 0; font-weight: bold; break-inside: avoid; }
.unverified, .caution { border: var(--rule-thin) dashed var(--color-ink);
padding: var(--space-sm); margin: var(--space-sm) 0; break-inside: avoid; }
.caution { border-style: solid; }
.stop p, .unverified p, .caution p { margin: var(--space-xs) 0; }
ol, ul { margin: var(--space-xs) 0 var(--space-xs) 1.6em; padding: 0; }
li { margin: 0 0 var(--space-xs); }
ol.steps { list-style: decimal; }
.tick { display: inline-block; width: var(--performed-size); height: var(--performed-size);
border: var(--rule-thin) solid var(--color-ink); background: var(--color-paper);
vertical-align: middle; margin-right: var(--space-xs); }
.reading { white-space: nowrap; }
.field, .result-field, .authored-blank { display: inline-flex; flex-direction: column;
gap: var(--space-xs);
max-width: 100%; vertical-align: top; break-inside: avoid; page-break-inside: avoid; }
.writing-blank { display: block; box-sizing: content-box; min-width: var(--writing-width);
min-height: var(--writing-height); padding: 0; border: var(--rule-thin) solid var(--color-ink);
background: var(--color-paper); }
.field { margin: var(--space-xs) var(--space-xs) var(--space-xs) 0; }
.field.prose-field { display: flex; width: fit-content; }
.result-field, .authored-blank { display: flex; width: 100%; margin-top: var(--space-sm); }
.result-field .writing-blank, .authored-blank .writing-blank {
min-height: var(--writing-result-height); }
table.readings .field { display: flex; }
.calc { margin: var(--space-sm) 0; font-weight: bold; }
.calc { break-inside: avoid; page-break-inside: avoid; }
.calc .field { display: flex; width: fit-content; }
table { width: 100%; border-collapse: collapse; margin: var(--space-sm) 0; table-layout: fixed; }
th, td { border: var(--rule-thin) solid var(--color-rule); padding: var(--space-xs) var(--space-sm);
text-align: left; vertical-align: top; overflow-wrap: anywhere; }
th { background: var(--color-header); }
.table-context th { font-weight: normal; background: var(--color-paper); }
thead { display: table-header-group; }
tr, tbody { break-inside: avoid; page-break-inside: avoid; }
tr.warn td { border-top: 0; }
tr.warn .box { display: block; margin: 0 0 var(--space-xs); }
.box { display: block; border: var(--rule-warning) solid var(--color-ink); font-weight: bold;
padding: var(--space-xs) var(--space-sm); margin-top: var(--space-xs); }
.keep { break-inside: avoid; page-break-inside: avoid; }
.contours, .contours.wide { columns: auto; }
.contour { break-inside: avoid; page-break-inside: avoid; margin-bottom: var(--space-md); }
.contour.wide { column-span: all; }
.stages { display: block; }
.stages > div { min-width: 0; }
table.coords { table-layout: auto; }
table.coords th { overflow-wrap: normal; }
table.coords td.num { white-space: nowrap; overflow-wrap: normal; }
.tick { display: inline-block; width: 7pt; height: 7pt; border: 1px solid var(--color-ink); \
margin: 0 2pt -1pt 6pt; } .levels .level:first-child .tick { margin-left: 2pt; }
.levels .level { white-space: nowrap; }
.reading, td.num { white-space: nowrap; overflow-wrap: normal; }
table.fixture, table.blank-check { table-layout: auto; }
table.fixture th, table.fixture td, table.blank-check th, table.blank-check td {
min-width: 12ch; overflow-wrap: anywhere; word-break: normal; hyphens: none; }
table.fixture td[data-label="Fastener"] { min-width: 14ch; }
.fixture-feature { display: inline-block; max-width: 100%;
break-inside: avoid; page-break-inside: avoid; }
@media screen and (max-width: 640px) {
html:not(.print-measuring) table.fixture,
html:not(.print-measuring) table.blank-check { table-layout: fixed; }
html:not(.print-measuring) table.fixture thead tr:not(.repeat):not(.table-context),
html:not(.print-measuring) table.blank-check thead tr:not(.repeat):not(.table-context),
html:not(.print-measuring) table.fixture colgroup,
html:not(.print-measuring) table.blank-check colgroup { display: none; }
html:not(.print-measuring) table.fixture tbody,
html:not(.print-measuring) table.blank-check tbody,
html:not(.print-measuring) table.fixture tbody tr,
html:not(.print-measuring) table.blank-check tbody tr { display: block; }
html:not(.print-measuring) table.fixture td,
html:not(.print-measuring) table.blank-check td { display: block; width: 100%; }
html:not(.print-measuring) table.fixture td::before,
html:not(.print-measuring) table.blank-check td::before {
content: attr(data-label); display: block; font-weight: bold; }
}
th.read, td.read { font-weight: bold; }
th.read { background: var(--color-reading-header); }
tr.repeat th { background: var(--color-paper); font-weight: bold; }
.paged table:not([data-duplex-split]) tr.repeat { display: none; }
table:not([data-duplex-split]) tr.table-context { display: none; }
.paged table thead tr.table-context[data-context-suppressed="same-page"] { display: none; }
.paged table thead [data-title-repeat][data-title-suppressed] { display: none; }
.hold-row { display: block; }
.hold-steps { min-width: 0; }
.fixture-render { margin: var(--space-sm) 0; break-inside: avoid; page-break-inside: avoid; }
.fixture-render svg { display: block; width: 100%; height: auto;
border: var(--rule-thin) solid var(--color-rule); }
.fixture-render { margin-left: 0; margin-right: 0; }
.fixture-render figcaption { margin-bottom: var(--space-xs); }
.see { display: block; }
.op-note { margin: var(--space-xs) 0; }
.cont-head, .compact-sheet-head { font-size: var(--text-running); font-weight: bold;
margin: 0 0 var(--space-sm);
border-bottom: var(--rule-thin) solid var(--color-ink); }
.cont-count { display: block; white-space: nowrap; }
.cont-context { display: block; font-size: var(--text-working); overflow-wrap: normal; }
/* Counter reservations need equal digit advances even when a font kerns digit pairs. */
.fixed-locator-digit { font-kerning: none; }
.more { margin: var(--space-xs) 0 0; font-weight: bold; }
table.operations { margin-top: 0; }
table.operations > thead th { background: var(--color-paper); }
tr.continued th { background: var(--color-paper); font-size: var(--text-running); }
.paged tr.continued { display: none; }
.paged h2:has(+ table.operations) { position: static; height: auto;
margin: var(--space-lg) 0 var(--space-sm); display: block; }
.operation > tr > td { padding: var(--space-sm); border-left: 0; border-right: 0; }
.op-head { display: flex; align-items: flex-start; gap: var(--space-sm); }
.op-head h3 { margin: 0; min-width: 0; }
.performed-mark { flex: 0 0 var(--performed-size); width: var(--performed-size);
height: var(--performed-size); border: var(--rule-thin) solid var(--color-ink);
background: var(--color-paper); margin-top: var(--space-xs); }
.op-details { display: grid; grid-template-columns: minmax(0, 1fr) minmax(0, 1fr);
gap: var(--space-xs) var(--space-md); margin: var(--space-sm) 0 0; }
.op-details > div { min-width: 0; }
.op-details dt { font-weight: bold; }
.op-details dd { margin: 0; }
.inspection-layout { display: block; }
.inspection-requirement { min-width: 0; }
.inspection-requirement p { margin: 0; }
.inspection-record > td { border-top-style: solid; }
.operation-continuation .op-number { font-weight: bold; }
.record-continuation { display: block; }
.signoff { margin-top: var(--space-lg); break-before: avoid; page-break-before: avoid;
display: flex; flex-wrap: wrap; gap: var(--space-md); }
.signoff .field { flex: 1 1 52mm; }
.signoff p { flex: 1 1 52mm; margin: 0; }
.signoff .writing-blank { width: auto; }
.contour-row, .contour-row.tall, [data-duplex-stacked] { display: block; }
.contour-row > .contour { min-width: 0; }
.blank-side { min-height: 1px; }
@media screen {
  body { max-width: var(--page-content-width); margin: var(--space-md) auto;
  padding: 0 var(--space-sm); }
  .page { margin-bottom: var(--space-lg); }
  .blank-side { display: none; }
  html:not(.print-measuring) table.coords { display: block; overflow-x: auto; }
}
@media screen and (max-width: 600px) {
  html:not(.print-measuring) .meta { display: block; }
  html:not(.print-measuring) .op-details { grid-template-columns: minmax(0, 1fr); }
  html:not(.print-measuring) table:not(.operations) {
  display: block; overflow-x: auto; table-layout: auto; }
}
"""
)
# Duplex padding, run in the browser on load and before printing. Every sheet must end
# on an even page so the next sheet starts on a front side when the whole file prints
# double-sided. The script places the page breaks itself: it measures the sheet at the
# printed width and starts a new page wherever the next block would cross it, keeping
# headings (and a table's caption) with what follows, the sign-off with the last op row.
# A table that runs over is split into a copy with the same column headings; an op table
# says on its page which op it continues with. Every page after a sheet's first opens
# with part, setup/sheet identity and its page number. An odd count gets a truly blank
# back. Without scripts the browser paginates the same content on its own, unpadded.
_DUPLEX_JS = r"""(() => {
  // The fewest original ordinary-table row groups on either side of a feasible break.
  const KEEP = 3;
  const ADDED = "data-duplex", SPLIT = "data-duplex-split", STACKED = "data-duplex-stacked";
  const CONTEXT_ROLE = "data-context-role";
  const originals = new Map();
  let CAP;
  const heading = (el) => el && /^H[1-6]$/.test(el.tagName);
  function box(el) {
    const r = el.getBoundingClientRect(), s = getComputedStyle(el);
    return { top: r.top - parseFloat(s.marginTop), bottom: r.bottom + parseFloat(s.marginBottom) };
  }
  const LOCATOR_TARGET = "data-locator-target", LOCATOR_REF = "data-locator-ref";
  let locatorPass;
  const locatorNodes = (root, selector) => [...root.querySelectorAll(selector)];
  const locatorRect = (node) => {
    const r = node.getBoundingClientRect();
    return [r.left, r.top, r.right, r.bottom, r.width, r.height];
  };
  const locatorLines = (range) => [...range.getClientRects()].map(
    (r) => [r.left, r.top, r.right, r.bottom, r.width, r.height]
  );
  function locatorVisible(node) {
    for (let owner = node; owner; owner = owner.parentElement) {
      const style = getComputedStyle(owner);
      if (style.display === "none" || style.visibility === "hidden"
          || style.visibility === "collapse") return false;
    }
    return node.getClientRects().length > 0;
  }
  const locatorStarts = (section) => [section, ...locatorNodes(section, ".cont-head")].map(
    (node, index) => ({ node, page: index + 1, top: box(node).top })
  );
  function locatorPage(node) {
    const section = node.closest("section.page[data-sheet]");
    if (!section) throw new Error("A recording destination has no logical sheet.");
    const start = locatorStarts(section).filter(
      (entry) => entry.node === section || entry.node === node
        || entry.node.compareDocumentPosition(node) & Node.DOCUMENT_POSITION_FOLLOWING
    ).at(-1);
    const bounds = section.getBoundingClientRect();
    return { sheet: section.dataset.sheet, identity: section.dataset.title || section.dataset.sheet,
      page: start.page, top: start.top, bottom: start.top + CAP,
      left: bounds.left, right: bounds.right };
  }
  const locatorWithin = (rect, bounds) => rect[0] >= bounds.left
    && rect[2] <= bounds.right && rect[1] >= bounds.top && rect[3] <= bounds.bottom;
  function cleanLocatorCopy(copy) {
    for (const node of [copy, ...locatorNodes(copy, "*")]) {
      node.removeAttribute(LOCATOR_TARGET);
      node.removeAttribute("data-locator-group");
    }
    return copy;
  }
  function locatorReference(meta, instruction) {
    const ref = document.createElement("span");
    ref.setAttribute(LOCATOR_REF, meta.key);
    ref.className = "fixed-locator-reference";
    ref.append(instruction + " — " + meta.identity + ", page ");
    const slot = document.createElement("span"), ink = document.createElement("span");
    slot.className = "fixed-locator-digit";
    slot.setAttribute("aria-readonly", "true");
    ink.className = "fixed-locator-ink";
    slot.append(ink);
    ref.append(slot);
    return ref;
  }
  function measureLocator(ref) {
    const slot = ref.querySelector(".fixed-locator-digit"), style = getComputedStyle(slot);
    const line = parseFloat(style.lineHeight);
    if (!Number.isFinite(line) || line <= 0) {
      throw new Error("A recording locator has no measured inherited line height.");
    }
    const probe = document.createElement("span");
    probe.style.cssText = "position:absolute;visibility:hidden;white-space:nowrap;"
      + "display:inline-block;padding:0;margin:0;border:0";
    for (const property of ["font-family", "font-size", "font-weight", "font-style",
      "font-stretch", "font-variant-numeric", "font-feature-settings",
      "font-variation-settings", "font-kerning", "font-optical-sizing",
      "letter-spacing", "word-spacing", "line-height"]) {
      probe.style.setProperty(property, style.getPropertyValue(property));
    }
    document.body.append(probe);
    let width;
    try {
      for (let digit = 0; digit <= 9; digit++) {
        probe.textContent = String(digit).repeat(locatorPass.digits);
        const measured = probe.getBoundingClientRect().width;
        if (!Number.isFinite(measured) || measured <= 0
            || !style.fontVariantNumeric.includes("tabular-nums")
            || (width !== undefined && measured !== width)) {
          throw new Error("A recording locator lacks measured tabular digit metrics.");
        }
        width = measured;
      }
    } finally { probe.remove(); }
    // Empty reserved counters take exactly the same line box as the final ink.
    slot.style.cssText = `display:inline-block;position:relative;width:${width}px;`
      + `min-width:${width}px;max-width:${width}px;height:${line}px;min-height:${line}px;`
      + `max-height:${line}px;line-height:${line}px;vertical-align:bottom;white-space:nowrap;`
      + `flex:0 0 ${width}px;padding:0;margin:0;border:0`;
    slot.firstElementChild.style.cssText = "position:absolute;left:0;top:0;display:block;"
      + "white-space:nowrap;line-height:inherit;padding:0;margin:0;border:0";
  }
  function prepareLocators() {
    locatorPass = { expected: new Map(), reservations: new Map() };
    const sections = locatorNodes(document, "section.page[data-sheet]");
    let units = 1n;
    for (const section of sections) {
      const walker = document.createTreeWalker(section, NodeFilter.SHOW_TEXT);
      let node;
      while ((node = walker.nextNode())) {
        if (!node.parentElement.closest("script,style")) units += BigInt(node.length);
      }
      units += BigInt(locatorNodes(section,
        "figure,.writing-blank,.tick,.performed-mark,input,select,textarea,button").length);
      for (const owner of [section, ...locatorNodes(section, "*")]) {
        for (const attribute of owner.attributes) {
          if (attribute.name === "data-worksheet-title"
              || attribute.name === "data-reading-context") units += BigInt(attribute.value.length);
        }
      }
    }
    if (units < 1n || units > BigInt(Number.MAX_SAFE_INTEGER)) {
      throw new Error("The pristine recording-locator source bound is not integer-safe.");
    }
    locatorPass.bound = Number(units);
    locatorPass.digits = String(locatorPass.bound).length;
    for (const [sectionIndex, section] of sections.entries()) {
      const identity = section.dataset.title || section.dataset.sheet;
      if (!identity) throw new Error("A recording locator has no logical sheet identity.");
      for (const [ordinal, blank] of locatorNodes(section, ".writing-blank").entries()) {
        const field = blank.closest(".field,.result-field,.authored-blank");
        if (!field) throw new Error("An original writing area has no structural owner.");
        const name = field.querySelector(".field-label")?.textContent ?? "";
        const key = JSON.stringify([section.dataset.sheet, sectionIndex, "field", ordinal, name]);
        blank.setAttribute(LOCATOR_TARGET, key);
        field.setAttribute("data-locator-field-key", key);
        locatorPass.expected.set(key, { key, identity, section: section.dataset.sheet, name,
          authored: field.classList.contains("authored-blank"), ordinal });
      }
      for (const [ordinal, group] of locatorNodes(section, ".path-progress").entries()) {
        const children = locatorNodes(group, ".writing-blank");
        if (children.length !== 2) {
          throw new Error("A progress record must retain its level and last completed # together.");
        }
        const members = children.map((node) => node.getAttribute(LOCATOR_TARGET));
        const key = JSON.stringify([section.dataset.sheet, sectionIndex, "progress pair", ordinal]);
        const meta = { key, identity, section: section.dataset.sheet, members };
        children.forEach((node) => node.setAttribute("data-locator-group", key));
        locatorPass.expected.set(key, meta);
        for (const locator of locatorNodes(group.closest(".contour"),
          "[data-continuation-locator]")) {
          const instruction = [...locator.childNodes].map((node) => node.cloneNode(true));
          const ref = locatorReference(meta, "");
          ref.firstChild.replaceWith(...instruction,
            document.createTextNode(" — " + identity + ", page "));
          locator.replaceChildren(ref);
        }
      }
      for (const owner of locatorNodes(section, "[data-page-context]")) {
        if (owner.matches(".contour")) continue;
        const context = owner.querySelector(":scope > .page-context");
        if (!context) continue;
        for (const blank of locatorNodes(owner, ".writing-blank").filter(
          (node) => node.closest("[data-page-context]") === owner
        )) {
          const meta = locatorPass.expected.get(blank.getAttribute(LOCATOR_TARGET));
          const ref = locatorReference(meta, locatorInstruction(meta));
          ref.prepend(" · ");
          context.append(ref);
        }
      }
      for (const note of locatorNodes(section, ".op-note,.op-action")) {
        if (note.closest("[data-page-context]")) continue;
        for (const blank of locatorNodes(note, ".writing-blank").filter(
          (node) => node.closest(".op-note,.op-action") === note
        )) {
          const meta = locatorPass.expected.get(blank.getAttribute(LOCATOR_TARGET));
          const ref = locatorReference(meta, locatorInstruction(meta));
          ref.prepend(" · ");
          note.append(ref);
        }
      }
    }
    locatorNodes(document, "[" + LOCATOR_REF + "]").forEach(measureLocator);
    for (const meta of locatorPass.expected.values()) {
      if (meta.members) continue;
      const blank = locatorNodes(document, "[" + LOCATOR_TARGET + "]").find(
        (node) => node.getAttribute(LOCATOR_TARGET) === meta.key
      );
      const ref = locatorReference(meta, locatorInstruction(meta));
      ref.style.cssText = "position:absolute;visibility:hidden";
      blank.parentElement.append(ref);
      measureLocator(ref);
      ref.remove();
      ref.removeAttribute("style");
      locatorPass.reservations.set(meta.key, ref);
    }
  }
  const locatorInstruction = (meta) => meta.authored
    ? "Original authored blank " + (meta.ordinal + 1) : "Original " + meta.name;
  function locatorRegistry() {
    for (const section of locatorNodes(document, "section.page[data-sheet]")) {
      const actual = locatorStarts(section).length;
      if (!Number.isSafeInteger(actual) || actual < 1 || actual > locatorPass.bound
          || actual !== Number(section.dataset.pages)) {
        throw new Error(
          "Recording-locator local pages exceed or disagree with their source bound.");
      }
    }
    const targets = locatorNodes(document, "[" + LOCATOR_TARGET + "]");
    if (targets.some((node) => node.closest("[" + ADDED + "]"))) {
      throw new Error("Generated context cannot own an original recording destination.");
    }
    const registry = [];
    for (const meta of locatorPass.expected.values()) {
      const places = [];
      for (const member of meta.members ?? [meta.key]) {
        const matches = targets.filter((node) => node.getAttribute(LOCATOR_TARGET) === member);
        if (matches.length !== 1) {
          throw new Error("An original recording destination is missing or duplicated.");
        }
        const blank = matches[0], page = locatorPage(blank),
          field = blank.closest(".field,.result-field,.authored-blank");
        if (!locatorVisible(blank) || !Number.isSafeInteger(page.page)
            || page.page > locatorPass.bound || !locatorWithin(locatorRect(field), page)
            || !locatorWithin(locatorRect(blank), page)) {
          throw new Error("An original writing destination does not fit wholly on its local page.");
        }
        places.push({ member, page: page.page, sheet: page.sheet, identity: page.identity,
          field: locatorRect(field), blank: locatorRect(blank),
          top: page.top, bottom: page.bottom });
      }
      if (places.some((place) => place.sheet !== meta.section || place.identity !== meta.identity)
          || (meta.members && new Set(places.map((place) => place.page)).size !== 1)) {
        throw new Error(
          "An original recording destination changed owner or split its progress pair.");
      }
      registry.push({ key: meta.key, page: places[0].page, places });
    }
    if (targets.some((node) => !locatorPass.expected.has(node.getAttribute(LOCATOR_TARGET)))) {
      throw new Error("An original recording destination has an unknown identity.");
    }
    return registry;
  }
  function locatorLayout(registry) {
    const nodes = locatorNodes(document, "section.page[data-sheet],section.page[data-sheet] *")
      .filter((node) => locatorVisible(node)
        && !node.matches(".fixed-locator-ink") && !node.closest(".fixed-locator-ink"));
    const geometry = nodes.map((node) => [locatorRect(node), locatorLines(node)]);
    const text = [], walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
    // Range boundaries stay live until GC; reuse a local cursor and copy each result.
    const range = document.createRange();
    let node;
    while ((node = walker.nextNode())) {
      if (node.parentElement.closest("script,style,.fixed-locator-ink")
          || !locatorVisible(node.parentElement)) continue;
      range.selectNodeContents(node);
      text.push([node.textContent, locatorLines(range)]);
    }
    const starts = locatorNodes(document, "section.page[data-sheet]").map(
      (section) => [section.dataset.sheet, Number(section.dataset.pages),
        locatorStarts(section).map((start) => [start.page, start.top]), locatorRect(section)]
    );
    return JSON.stringify([geometry, text, registry, CAP,
      Number(document.documentElement.dataset.printWidth), starts]);
  }
  function finishLocators() {
    const refs = locatorNodes(document, "[" + LOCATOR_REF + "]").filter(locatorVisible);
    for (const ref of refs) {
      const slot = ref.querySelector(".fixed-locator-digit"), style = slot.getAttribute("style");
      // Re-read live inherited CSS, not the line box pinned by the reservation.
      slot.removeAttribute("style");
      measureLocator(ref);
      if (slot.getAttribute("style") !== style) {
        throw new Error("A recording locator changed its inherited reserved typography.");
      }
    }
    const registry = locatorRegistry(), before = locatorLayout(registry),
      byKey = new Map(registry.map((entry) => [entry.key, entry]));
    for (const ref of refs) {
      const target = byKey.get(ref.getAttribute(LOCATOR_REF));
      const ink = ref.querySelector(".fixed-locator-digit")?.firstElementChild;
      if (!target || !ink || ink.textContent !== "") {
        throw new Error("A recording locator has no resolved original destination or empty slot.");
      }
      const value = String(target.page);
      if (value.length > locatorPass.digits) {
        throw new Error("A recording locator exceeds its source-bound digit reservation.");
      }
      ink.textContent = value;
    }
    if (before !== locatorLayout(locatorRegistry())) {
      throw new Error("Recording-locator fill changed layout or the final destination registry.");
    }
    for (const ref of refs) {
      const slot = ref.querySelector(".fixed-locator-digit"), ink = slot.firstElementChild,
        page = locatorPage(ref), owner = ref.closest("tr,.cont-head,li,p,.op-action")
          ?? ref.parentElement;
      const ownerRect = locatorRect(owner), ownerBounds = { left: ownerRect[0],
        top: ownerRect[1], right: ownerRect[2], bottom: ownerRect[3] },
        refRects = locatorLines(ref), slotRect = locatorRect(slot);
      if (!locatorWithin(slotRect, ownerBounds) || !locatorWithin(slotRect, page)) {
        throw new Error("A recording-locator reservation escapes its owner or local print page.");
      }
      const walker = document.createTreeWalker(ref, NodeFilter.SHOW_TEXT);
      const range = document.createRange();
      let node;
      while ((node = walker.nextNode())) {
        for (let offset = 0; offset < node.length; offset++) {
          range.setStart(node, offset);
          range.setEnd(node, offset + 1);
          for (const rect of locatorLines(range)) {
            if (!rect[4] || !rect[5]) continue;
            const containers = node.parentElement === ink ? [slotRect] : refRects;
            if (!containers.some((bounds) => locatorWithin(rect,
              { left: bounds[0], top: bounds[1], right: bounds[2], bottom: bounds[3] }))
                || !locatorWithin(rect, ownerBounds) || !locatorWithin(rect, page)) {
              throw new Error("A recording-locator glyph escapes its reservation or print owner.");
            }
          }
        }
      }
    }
  }
  function locatorFieldContext(field) {
    const meta = locatorPass.expected.get(field.getAttribute("data-locator-field-key"));
    const nodes = [...(field.querySelector(".field-label")?.childNodes || [])];
    if (!meta || locatorNodes(field.closest(".op-note,.op-action") ?? field,
      "[" + LOCATOR_REF + "]").some((ref) => ref.getAttribute(LOCATOR_REF) === meta.key)) {
      return nodes;
    }
    const ref = locatorPass.reservations.get(meta.key)?.cloneNode(true);
    if (!ref) throw new Error("A recording reference lacks its pristine measured reservation.");
    ref.prepend(" · ");
    return [...nodes, ref];
  }
  function paginate(section) {
    // Recompute roles at this print width; source continuations inherit them only
    // within this pass, never from an earlier pagination measurement.
    section.querySelectorAll(".page-context").forEach((context) => {
      context.removeAttribute(CONTEXT_ROLE);
    });
    const statusContents = [...(section.querySelector(":scope > .banner")?.childNodes || [])]
      .map((node) => node.cloneNode(true));
    const title = [section.dataset.part, section.dataset.drawing,
      section.dataset.revision ? "rev " + section.dataset.revision : "REV NOT CONFIRMED",
      section.dataset.title || section.dataset.sheet].filter(Boolean).join(" · ");
    const titleOwners = new Map();
    for (const source of section.querySelectorAll("h3.page-context > [data-title-source]")) {
      const key = source.dataset.titleSource, units = new Map();
      const walker = document.createTreeWalker(source, NodeFilter.SHOW_TEXT), nodes = [];
      while (walker.nextNode()) nodes.push(walker.currentNode);
      nodes.forEach((node, ordinal) => {
        const identity = key + ":text:" + ordinal, span = document.createElement("span");
        span.dataset.titleUnit = identity;
        units.set(identity, node.length);
        node.replaceWith(span);
        span.append(node);
      });
      // DOM text lengths and Range offsets are UTF-16 units, including non-BMP titles.
      titleOwners.set(key, { length: source.textContent.length, units });
    }
    for (const repeat of section.querySelectorAll("[data-title-repeat]")) {
      const key = repeat.dataset.titleRepeat;
      if (!titleOwners.has(key)) continue;
      const walker = document.createTreeWalker(repeat, NodeFilter.SHOW_TEXT), nodes = [];
      while (walker.nextNode()) nodes.push(walker.currentNode);
      nodes.forEach((node, ordinal) => {
        const span = document.createElement("span");
        span.dataset.titleUnit = key + ":text:" + ordinal;
        node.replaceWith(span);
        span.append(node);
      });
    }
    function fullTitleCanonicalOnPage(key) {
      const owner = titleOwners.get(key);
      if (!owner?.units.size) return false;
      const left = section.getBoundingClientRect().left,
        right = left + Number(document.documentElement.dataset.printWidth);
      const within = (r) => r.left >= left - .01 && r.right <= right + .01
        && r.top >= pageTop - .01 && r.bottom <= pageTop + CAP + .01;
      for (const span of section.querySelectorAll("[data-title-source]")) {
        if (span.dataset.titleSource !== key) continue;
        const running = span.closest(".cont-context"), original = span.closest("h3.page-context");
        if (!running && (!original || span.closest("[" + ADDED + "]"))) continue;
        if (span.textContent.length !== owner.length) continue;
        const units = [...span.querySelectorAll("[data-title-unit]")];
        if (units.length !== owner.units.size || units.some((node) =>
          !owner.units.has(node.dataset.titleUnit)
            || node.textContent.length !== owner.units.get(node.dataset.titleUnit))) continue;
        if (!span.getClientRects().length || !within(span.getBoundingClientRect())
            || [...span.querySelectorAll("*")].some((node) =>
              [...node.getClientRects()].some((rect) => !within(rect)))) continue;
        const range = document.createRange();
        if (units.some((node) => {
          range.selectNodeContents(node);
          return [...range.getClientRects()].some((rect) => !within(rect));
        })) continue;
        return true;
      }
      return false;
    }
    function refreshTitleCopies(t) {
      for (const span of t.tHead?.querySelectorAll("[data-title-repeat]") || []) {
        const key = span.dataset.titleRepeat, owner = titleOwners.get(key),
          units = [...span.querySelectorAll("[data-title-unit]")];
        const whole = owner && span.textContent.length === owner.length
          && units.length === owner.units.size && units.every((node) =>
            owner.units.has(node.dataset.titleUnit)
              && node.textContent.length === owner.units.get(node.dataset.titleUnit));
        span.toggleAttribute("data-title-suppressed", !!whole && fullTitleCanonicalOnPage(key));
      }
    }
    const contextHeads = new Map(
      [...section.querySelectorAll("[data-page-context]")].map((owner) => [
        owner.dataset.pageContext, owner.querySelector(":scope > .page-context")?.cloneNode(true)
      ])
    );
    const operationHeads = new Map(
      [...section.querySelectorAll("tbody.operation")].map((body) => [
        body.dataset.op, [...body.rows].filter(
          (row) => row.classList.contains("operation-main") || row.querySelector(".op-note")
        ).map((row) => row.cloneNode(true))
      ])
    );
    const instructionOwners = new Map();
    function registerInstructionOwner(t, index) {
      const intro = t.previousElementSibling,
        mirror = t.tHead?.querySelector(":scope > tr.table-context");
      if (!intro?.matches("p.table-intro") || !mirror
          || intro.querySelector("figure,.field,.result-field,.authored-blank,"
            + ".tick,.performed-mark,input")) return;
      const key = "table:" + index + ":instruction", units = new Map();
      intro.dataset.instructionSource = key;
      mirror.dataset.instructionRef = key;
      const walker = document.createTreeWalker(intro, NodeFilter.SHOW_TEXT), nodes = [];
      while (walker.nextNode()) nodes.push(walker.currentNode);
      nodes.forEach((node, ordinal) => {
        const identity = key + ":text:" + ordinal, span = document.createElement("span");
        span.dataset.instructionUnit = identity;
        units.set(identity, node.length);
        node.replaceWith(span);
        span.append(node);
      });
      instructionOwners.set(key, units);
    }
    function fullInstructionOnPage(key) {
      const units = instructionOwners.get(key);
      if (!units?.size) return false;
      const totals = new Map(), left = section.getBoundingClientRect().left,
        right = left + Number(document.documentElement.dataset.printWidth);
      const contained = (rect) => rect.left >= left - .01 && rect.right <= right + .01
        && rect.top >= pageTop - .01 && rect.bottom <= pageTop + CAP + .01;
      const fragments = [...section.querySelectorAll("[data-instruction-source]")].filter(
        (node) => node.dataset.instructionSource === key && !node.closest("[" + ADDED + "]")
      );
      for (const fragment of fragments) {
        const bounds = box(fragment);
        if (bounds.top < pageTop - .01 || bounds.bottom > pageTop + CAP + .01
            || !contained(fragment.getBoundingClientRect())
            || [...fragment.querySelectorAll("*")].some((node) =>
              !node.closest("[" + ADDED + "]")
                && [...node.getClientRects()].some((rect) => !contained(rect)))) continue;
        const range = document.createRange();
        for (const unit of fragment.querySelectorAll("[data-instruction-unit]")) {
          if (unit.closest("[" + ADDED + "]")) continue;
          const identity = unit.dataset.instructionUnit;
          if (!units.has(identity)) return false;
          range.selectNodeContents(unit);
          if ([...range.getClientRects()].some((rect) => !contained(rect))) continue;
          totals.set(identity, (totals.get(identity) || 0) + unit.textContent.length);
        }
      }
      return [...units].every(([identity, length]) => totals.get(identity) === length);
    }
    function refreshInstructionMirrors(t) {
      for (const row of t.tHead?.querySelectorAll("[data-instruction-ref]") || []) {
        if (fullInstructionOnPage(row.dataset.instructionRef)) {
          row.dataset.contextSuppressed = "same-page";
        } else row.removeAttribute("data-context-suppressed");
      }
    }
    const ORDINARY_EXCLUSIONS = "figure,figcaption,.field,.result-field,.authored-blank,"
      + ".writing-blank,.field-label,.tick,.performed-mark,input,textarea,select,button,svg,img,"
      + ".record-continuation,.row-continuation,.page-context,.op-number,.op-details,"
      + ".cont-head,[data-continuation-locator],.fixed-locator-reference,[" + ADDED + "]";
    function ordinaryWholeCell(cell) {
      if (cell?.nodeType !== Node.ELEMENT_NODE || !cell.matches("td,th")
          || cell.closest("table.operations,[" + ADDED + "]")) return false;
      const row = cell.parentElement;
      if (row.matches(".operation-main,.inspection-record,.warn,.process-observations")
          || cell.matches(ORDINARY_EXCLUSIONS) || cell.querySelector(ORDINARY_EXCLUSIONS)) {
        return false;
      }
      if (cell.closest("table.fixture") && [...row.cells].indexOf(cell) < 2) return false;
      for (const node of cell.querySelectorAll("*")) {
        if (!/^(SPAN|BR|STRONG|B|EM|I)$/.test(node.tagName)
            || [...node.classList].some(
              (name) => !["reading", "fixture-feature"].includes(name)
            )) return false;
      }
      const prose = cell.cloneNode(true);
      prose.querySelectorAll(".reading").forEach((node) => node.remove());
      return /\p{L}/u.test(prose.textContent);
    }
    function wholeCellPoints(el, points) {
      if (el.tagName !== "TR" || el.closest("table.operations")) return points;
      for (const cell of el.cells) {
        if (ordinaryWholeCell(cell)) points.push([cell, cell.childNodes.length]);
      }
      const left = document.createRange(), right = document.createRange();
      return points.sort((a, b) => {
        left.setStart(...a);
        left.collapse(true);
        right.setStart(...b);
        right.collapse(true);
        return left.compareBoundaryPoints(Range.START_TO_START, right);
      });
    }
    function residualSourcePayload(contents) {
      const copy = contents.cloneNode(true);
      copy.querySelectorAll("[" + ADDED + "],.record-continuation,.row-continuation,"
        + ".fixed-locator-reference").forEach((node) => node.remove());
      // Presence is not progress: whitespace and excluded original controls remain source.
      return copy.textContent.length !== 0 || !!copy.querySelector(ORDINARY_EXCLUSIONS);
    }
    function cellColumnContains(cell) {
      const rect = cell.getBoundingClientRect(), style = getComputedStyle(cell),
        border = getComputedStyle(cell.closest("table")).borderCollapse === "collapse" ? .5 : 1;
      const bounds = { left: rect.left + border * parseFloat(style.borderLeftWidth)
          + parseFloat(style.paddingLeft),
        right: rect.right - border * parseFloat(style.borderRightWidth)
          - parseFloat(style.paddingRight),
        top: rect.top + border * parseFloat(style.borderTopWidth) + parseFloat(style.paddingTop),
        bottom: rect.bottom - border * parseFloat(style.borderBottomWidth)
          - parseFloat(style.paddingBottom) };
      const contained = (r) => r.left >= bounds.left - .1 && r.right <= bounds.right + .1
        && r.top >= bounds.top - .1 && r.bottom <= bounds.bottom + .1;
      const walker = document.createTreeWalker(cell, NodeFilter.SHOW_TEXT);
      const range = document.createRange();
      while (walker.nextNode()) {
        const node = walker.currentNode;
        if (!node.textContent.trim() || node.parentElement.closest("[" + ADDED + "]")) continue;
        range.selectNodeContents(node);
        if ([...range.getClientRects()].some(
          (r) => r.width > 0 && r.height > 0 && !contained(r)
        )) return false;
      }
      return [...cell.querySelectorAll(".reading,.fixture-feature")].every(
        (node) => contained(node.getBoundingClientRect())
      );
    }
    function admitWholeCells(el, point) {
      let first = contentsAt(el, point), remaining = contentsAt(el, point, true);
      const retained = [];
      if (el.tagName === "TR" && ordinaryWholeCell(point[0])
          && point[1] === point[0].childNodes.length) {
        const slot = [...el.cells].indexOf(point[0]),
          candidate = prefixBottom(el.closest("table"), el, first, [slot]);
        if (!fits(candidate.bottom) || !candidate.contained) {
          return { first, remaining, prefixCredit: false, tailCredit: originalText(remaining),
            complete: false };
        }
        retained.push(slot);
      }
      if (el.tagName === "TR" && !el.closest("table.operations")) {
        const original = [...el.cells];
        for (let slot = 0; slot < original.length; slot++) {
          if (first.children[slot].childNodes.length
              || !remaining.children[slot].childNodes.length
              || !ordinaryWholeCell(original[slot])) continue;
          const contents = first.cloneNode(true);
          contents.children[slot].replaceWith(original[slot].cloneNode(true));
          const candidate = prefixBottom(el.closest("table"), el, contents, [...retained, slot]);
          if (!fits(candidate.bottom) || !candidate.contained) continue;
          first = contents;
          remaining.children[slot].replaceChildren();
          retained.push(slot);
        }
      }
      const prefixCredit = originalText(first), tailCredit = originalText(remaining);
      return { first, remaining, prefixCredit, tailCredit,
        complete: prefixCredit && !residualSourcePayload(remaining) };
    }
    const tableHeads = new Map(), fixtureRows = new Map();
    [...section.querySelectorAll("table")].forEach((t, index) => {
      t.dataset.tableContext = String(index);
      registerInstructionOwner(t, index);
      const sources = [...t.querySelectorAll("thead > tr.repeat, "
        + "thead > tr.table-context")].map((row) => row.cloneNode(true));
      const candidate = (contents, css = "table-context") => {
        const row = document.createElement("tr"), cell = document.createElement("th");
        row.className = css;
        row.dataset.optionalContext = "";
        cell.colSpan = t.tHead.rows[t.tHead.rows.length - 1].cells.length;
        cell.append(contents);
        row.append(cell);
        return row;
      };
      const op = t.closest(".contour")?.querySelector(":scope > .contour-context");
      if (op) {
        const copy = op.cloneNode(true);
        const before = sources.findIndex((row) => row.classList.contains("table-context"));
        sources.splice(before < 0 ? sources.length : before, 0, candidate(copy));
      }
      const worksheet = t.classList.contains("readings") ? t.closest(".worksheet") : null;
      if (worksheet) {
        for (const [html, css] of [
          [worksheet.dataset.worksheetTitle, "repeat"],
          ...JSON.parse(worksheet.dataset.readingContext).map((html) => [html, "table-context"])
        ]) {
          const contents = document.createElement("span");
          contents.innerHTML = html;
          sources.push(candidate(contents, css));
        }
      }
      tableHeads.set(String(index), sources);
      if (t.classList.contains("fixture")) {
        [...t.tBodies].flatMap((body) => [...body.rows]).forEach((row, slot) => {
          row.dataset.rowContext = index + ":" + slot;
          fixtureRows.set(row.dataset.rowContext,
            [...row.cells].slice(0, 2).map((cell) => cell.cloneNode(true)));
        });
      }
    });
    // Each print pass starts from pristine children. Only repeated logical-sheet
    // identity may use the running-header hierarchy to keep its first figure whole.
    if (section.dataset.sheetRole === "continuation") {
      const [meta, banner, heading, figure] = [...section.children];
      if (meta?.matches(".meta") && banner?.matches(".banner")
          && heading?.tagName === "H2" && figure?.tagName === "FIGURE") {
        const required = box(figure).bottom - box(section).top;
        if (required > CAP) {
          const head = document.createElement("div");
          head.className = "compact-sheet-head lead-in";
          const identity = document.createElement("span"), title = document.createElement("span");
          identity.className = title.className = "cont-title";
          for (const item of [...meta.children, banner]) {
            if (identity.childNodes.length) {
              const separator = document.createElement("span");
              separator.className = "compact-identity-separator";
              separator.textContent = " · ";
              identity.append(separator);
            }
            identity.append(...[...item.childNodes]);
          }
          title.append(...[...heading.childNodes]);
          head.append(identity, document.createElement("br"), title);
          meta.before(head);
          meta.remove(); banner.remove(); heading.remove();
          // The unchanged figure/caption must still fit with this measured header.
        }
      }
    }
    let pageTop = box(section).top, pages = 1;
    let pageStart = [...section.children].find(
      (el) => !el.classList.contains("meta") && !el.classList.contains("banner")
    );
    const fits = (bottom) => bottom - pageTop <= CAP;
    function prefixBottom(t, end, contents = null, inspectSlots = null) {
      refreshInstructionMirrors(t);
      refreshTitleCopies(t);
      // Measure the actual retained table, including its closing rule and margin.
      // A same-slot probe preserves its columns, context and inherited typography.
      const probe = t.cloneNode(false), range = document.createRange();
      range.selectNodeContents(t);
      if (contents) range.setEndBefore(end.parentElement);
      else range.setEndAfter(end);
      probe.append(range.cloneContents());
      if (contents) {
        const body = end.parentElement.cloneNode(false);
        for (const row of end.parentElement.rows) {
          const copy = row.cloneNode(row !== end);
          if (row === end) copy.append(contents.cloneNode(true));
          body.append(copy);
          if (row === end) break;
        }
        probe.append(body);
      }
      t.before(probe);
      try {
        const bottom = box(probe).bottom;
        if (inspectSlots === null) return bottom;
        const row = [...probe.tBodies[probe.tBodies.length - 1].rows].at(-1),
          bounds = probe.getBoundingClientRect(), left = section.getBoundingClientRect().left;
        return { bottom, contained: [...new Set(inspectSlots)].every(
          (slot) => cellColumnContains(row.cells[slot])
        ) && bounds.left >= left - .1
          && bounds.right <= left + Number(document.documentElement.dataset.printWidth) + .1 };
      }
      finally { probe.remove(); }
    }
    function textBottom(el, contents) {
      const probe = el.cloneNode(false);
      probe.append(contents.cloneNode(true));
      el.before(probe);
      try { return box(probe).bottom; }
      finally { probe.remove(); }
    }
    function sourceBottom(el, point) {
      const contents = contentsAt(el, point);
      return el.tagName === "TR"
        ? prefixBottom(el.closest("table"), el, contents) : textBottom(el, contents);
    }
    function pageProgress(el, relax = true) {
      if (el.tagName === "TABLE") {
        const progress = sourceProgress(el, el.tBodies[0]);
        return progress ? () => prefixBottom(el, progress.row, progress.contents) : null;
      }
      for (const point of pointsIn(el)) {
        const contents = contentsAt(el, point);
        if (originalText(contents) && fits(textBottom(el, contents))) {
          return () => textBottom(el, contents);
        }
      }
      if (originalText(el) && fits(box(el).bottom)) return () => box(el).bottom;
      return relax && prepareFields(el) ? pageProgress(el, false) : null;
    }
    function compactContext(el, suffix = "") {
      const references = locatorNodes(el, "[" + LOCATOR_REF + "]")
        .map((ref) => ref.cloneNode(true));
      const identity = /^.*?\bop\s+\d+\b/.exec(el.textContent);
      if (!identity) return false;
      const range = document.createRange(),
        walker = document.createTreeWalker(el, NodeFilter.SHOW_TEXT);
      range.selectNodeContents(el);
      let remaining = identity[0].length, node;
      while ((node = walker.nextNode())) {
        if (remaining <= node.length) {
          range.setEnd(node, remaining);
          el.replaceChildren(range.cloneContents(), suffix, ...references);
          return true;
        }
        remaining -= node.length;
      }
      return false;
    }
    function breakAt(el) {
      pages += 1;
      const head = document.createElement("p");
      head.className = "cont-head";
      head.setAttribute(ADDED, "");
      const running = document.createElement("span");
      running.className = "cont-title";
      running.textContent = title + " (continued)";
      if (statusContents.length) {
        running.append(" · ", ...statusContents.map((node) => node.cloneNode(true)));
      }
      const count = document.createElement("span");
      count.className = "cont-count";
      count.append(" · page " + pages + " of ");
      const total = document.createElement("span");
      total.className = "cont-page-total";
      total.textContent = "?";
      count.append(total);
      // The count line is present during every fit/progress measurement. Its final
      // digits cannot change the title wrapping or the preserved working context.
      head.append(running, "\n", count);
      const owner = el.closest("[data-page-context]");
      el.before(head);
      head.style.breakBefore = "page";
      pageTop = box(head).top;
      pageStart = el;
      const source = owner && contextHeads.get(owner.dataset.pageContext);
      if (source) {
        let progress = pageProgress(el);
        if (!progress) {
          // A repeated long note title is not original progress. Keep its stable
          // setup/op identity when the full repeat blocks the original remainder.
          for (const repeated of el.querySelectorAll(".record-continuation")) {
            compactContext(repeated, " (continued)");
          }
          progress = pageProgress(el);
        }
        if (!progress) return;
        const context = document.createElement("span");
        context.className = "cont-context";
        context.append(...[...source.childNodes].map((node) => node.cloneNode(true)));
        cleanLocatorCopy(context);
        head.append("\n", context);
        if (!fits(progress())) {
          if (!compactContext(context)) context.replaceChildren();
          if (!context.textContent || !fits(progress())) context.remove();
        }
      }
    }
    // What must start a page with `el`: the headings (and a table's caption) right above
    // it, a heading's lead-in line, and, when `el` opens its parent, what must start a
    // page with the parent.
    function lead(el) {
      let start = el;
      for (;;) {
        const prev = start.previousElementSibling;
        const caption = prev && prev.tagName === "P"
          && /^(TABLE|OL|UL)$/.test(start.tagName) && !prev.hasAttribute(ADDED);
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
      const operations = el.matches("table.operations") ? el
        : heading(el) && el.nextElementSibling?.matches("table.operations")
          ? el.nextElementSibling : null;
      if (operations && operations.tBodies.length) {
        more = document.createElement("p");
        more.className = "more";
        more.setAttribute(ADDED, "");
        start.before(more);
        const op = operations.tBodies[0].dataset.op
          || operations.tBodies[0].rows[0].cells[0].textContent;
        more.textContent = "Operations continue on reverse, op " + op;
        if (!fits(box(more).bottom)) {
          more.remove();
          more = null;
        }
      }
      breakAt(start);
      const movedTable = el.tagName === "TABLE" ? el
        : (heading(el) || el.classList.contains("table-intro"))
          && el.nextElementSibling?.tagName === "TABLE" ? el.nextElementSibling : null;
      if (movedTable && (tableHeads.get(movedTable.dataset.tableContext) || []).some(
            (row) => row.hasAttribute("data-optional-context")
          )) {
        const progress = sourceProgress(movedTable, movedTable.tBodies[0]);
        if (progress) {
          movedTable.setAttribute(SPLIT, "");
          tableContext(movedTable, progress, true);
        }
      }
      if (more && pages % 2 === 1) {
        more.textContent = more.textContent.replace("on reverse", "on the next sheet");
      }
      return true;
    }
    function pointsIn(el) {
      const points = [], atomicContexts = new Map();
      const walker = document.createTreeWalker(el, NodeFilter.SHOW_ELEMENT | NodeFilter.SHOW_TEXT, {
        acceptNode(node) {
          // A whole canonical view is source, but none of its SVG, title, caption
          // or text descendants is a legal pagination boundary.
          if (node.parentElement?.closest("figure, [" + ADDED + "]")) {
            return NodeFilter.FILTER_REJECT;
          }
          return node.nodeType === Node.TEXT_NODE || node.matches("figure")
            ? NodeFilter.FILTER_ACCEPT : NodeFilter.FILTER_SKIP;
        }
      });
      let node;
      while ((node = walker.nextNode())) {
        if (node.nodeType === Node.ELEMENT_NODE) {
          const parent = node.parentNode, slot = [...parent.childNodes].indexOf(node);
          points.push([parent, slot], [parent, slot + 1]);
          continue;
        }
        if (node.parentElement.closest(
          ".field, .result-field, .authored-blank, .performed-mark, .reading, "
            + ".record-continuation, .fixed-locator-reference, .op-details dt, [" + ADDED + "]"
        )) continue;
        const feature = node.parentElement.closest(".fixture-feature");
        if (feature) {
          if (!atomicContexts.has(feature)) {
            const parent = feature.parentNode,
              slot = [...parent.childNodes].indexOf(feature),
              before = [parent, slot], after = [parent, slot + 1];
            const prefix = originalText(contentsAt(el, before));
            // First continue before a complete feature clause, never between its
            // identity and coordinates. Only a clause that still cannot fit with
            // no earlier original source may use the ordinary measured fallback.
            const atomic = fits(sourceBottom(el, after)) || prefix;
            atomicContexts.set(feature, atomic);
            if (prefix) points.push(before);
            if (atomic) points.push(after);
          }
          if (atomicContexts.get(feature)) continue;
        }
        const context = node.parentElement.closest(".page-context");
        if (context) {
          if (!atomicContexts.has(context)) {
            const atomic = fits(sourceBottom(el, [context, context.childNodes.length]));
            atomicContexts.set(context, atomic);
            // A non-fitting original title must advance as source, not disappear
            // from the progress test merely because its identity can be repeated.
            if (!atomic) context.setAttribute(CONTEXT_ROLE, "source");
          }
          if (atomicContexts.get(context)) continue;
        }
        const text = node.textContent, matches = [...text.matchAll(/[ \t\r\n]+/g)];
        for (const match of matches) points.push([node, match.index + match[0].length]);
        if (!matches.length && text.length > 100) {
          for (let offset = 1; offset < text.length; offset++) points.push([node, offset]);
        }
      }
      return wholeCellPoints(el, points);
    }
    function rowContents(el, point, tail) {
      // A Range across a row omits cells outside the range. Clone every slot,
      // including empty ones, so later text stays beneath its original heading.
      const index = [...el.cells].findIndex((cell) => cell.contains(point[0]));
      const contents = document.createDocumentFragment();
      for (const [slot, original] of [...el.cells].entries()) {
        const copy = original.cloneNode(tail ? slot > index : slot < index);
        if (slot === index) {
          const part = document.createRange();
          part.selectNodeContents(original);
          if (tail) part.setStart(...point);
          else part.setEnd(...point);
          copy.append(part.cloneContents());
        }
        contents.append(copy);
      }
      return contents;
    }
    function contentsAt(el, point, tail = false) {
      if (el.tagName === "TR") return rowContents(el, point, tail);
      const range = document.createRange();
      range.selectNodeContents(el);
      if (tail) range.setStart(...point);
      else range.setEnd(...point);
      return range.cloneContents();
    }
    function originalText(contents) {
      // Retained whole figures and over-page original context advance source;
      // short repeatable identities and recording marks never do so alone.
      const copy = contents.cloneNode(true),
        identityOnly = '.page-context:not([' + CONTEXT_ROLE + '="source"])';
      if (copy.matches?.(identityOnly
        + ", .record-continuation, .fixed-locator-reference, [" + ADDED + "]")) return false;
      copy.querySelectorAll(".performed-mark, .writing-blank, .record-continuation, "
        + ".fixed-locator-reference, .op-number, " + identityOnly + ", [" + ADDED + "]")
        .forEach((node) => node.remove());
      return !!copy.matches?.("figure") || !!copy.querySelector("figure")
        || /[\p{L}\p{N}]/u.test(copy.textContent);
    }
    function sourceProgress(t, body, relax = true) {
      const row = [...body.rows].find((source) => !source.hasAttribute(ADDED));
      if (!row) return null;
      for (const point of pointsIn(row)) {
        const contents = contentsAt(row, point);
        if (!originalText(contents)) continue;
        if (fits(prefixBottom(t, row, contents))) return { row, point, contents };
      }
      if (originalText(row) && fits(prefixBottom(t, row))) {
        return { row, point: null, contents: null };
      }
      return relax && prepareFields(row) ? sourceProgress(t, body, false) : null;
    }
    function progressBottom(t, progress) {
      return prefixBottom(t, progress.row,
        progress.point ? contentsAt(progress.row, progress.point) : progress.contents);
    }
    function contextBudget(t, progress) {
      if (!t.classList.contains("operations")) {
        const original = [...t.tBodies].filter(
          (body) => !body.hasAttribute("data-duplex-fragment")
        );
        if (original.length >= KEEP && fits(prefixBottom(t, original[KEEP - 1]))) {
          return () => prefixBottom(t, original[KEEP - 1]);
        }
      }
      return () => progressBottom(t, progress);
    }
    function prepareFields(el) {
      const selector = ".field, .result-field, .authored-blank";
      const fields = el.matches(selector) ? [el] : [...el.querySelectorAll(selector)];
      let changed = false;
      for (const field of fields) {
        if (field.closest("[" + ADDED + "]")
            || fits(sourceBottom(el, [field, field.childNodes.length]))) continue;
        const label = field.querySelector(".field-label");
        if (!label) continue;
        const range = document.createRange();
        range.selectNodeContents(label);
        const last = [...range.getClientRects()].filter((rect) => rect.width > 0).pop();
        if (!last) continue;
        const walker = document.createTreeWalker(label, NodeFilter.SHOW_TEXT);
        let node, start = null;
        while (!start && (node = walker.nextNode())) {
          const offsets = [0];
          if (!node.parentElement.closest(".reading")) {
            for (const match of node.textContent.matchAll(/[ \t\r\n]+/g)) {
              offsets.push(match.index + match[0].length);
            }
          }
          for (const offset of offsets) {
            if (offset >= node.textContent.length) continue;
            range.setStart(node, offset);
            range.setEnd(node, offset + 1);
            if (range.getBoundingClientRect().top >= last.top) {
              start = [node, offset]; break;
            }
          }
        }
        if (!start) continue;
        range.selectNodeContents(label);
        range.setEnd(...start);
        const prose = document.createElement("span");
        prose.className = "authored-label";
        prose.append(range.cloneContents());
        // Fitting short labels stay atomic; an empty prefix cannot advance source.
        if (!/[\p{L}\p{N}]/u.test(prose.textContent)) continue;
        range.selectNodeContents(label);
        range.setStart(...start);
        const caption = range.cloneContents();
        field.before(prose);
        label.replaceChildren(caption);
        changed = true;
      }
      return changed;
    }
    // Only original source is fragmented. Repeated context is admitted whole,
    // and the writing box stays with the final measured source caption line.
    function fragment(el, relax = true) {
      if (el.hasAttribute(ADDED) || el.matches(".record-continuation")) return null;
      const points = pointsIn(el);
      // A glyph Range is not the final line box or table row. Prove the cloned
      // prefix's real formatting footprint before accepting the split point.
      function bottomAt(point) {
        return sourceBottom(el, point);
      }
      let low = 0, high = points.length - 1, best = -1;
      while (low <= high) {
        const middle = Math.floor((low + high) / 2);
        if (bottomAt(points[middle]) <= pageTop + CAP) {
          best = middle; low = middle + 1;
        } else high = middle - 1;
      }
      for (; best >= 0; best--) {
        const candidate = admitWholeCells(el, points[best]);
        if (!candidate.prefixCredit) continue;
        const first = candidate.first, remaining = candidate.remaining;
        if (candidate.complete && el.tagName === "TR") {
          el.replaceChildren(first);
          return el;
        }
        if (!candidate.tailCredit) continue;
        const rest = el.cloneNode(false);
        rest.append(remaining);
        if (rest.dataset.rowContext) rest.dataset.rowContinuation = "";
        el.replaceChildren(first);
        el.after(rest);
        for (const field of rest.querySelectorAll(".op-details > div")) {
          if (!field.querySelector("dd") || field.querySelector("dt")) continue;
          const source = el.querySelector(".op-details > ." + field.className + " > dt");
          if (source) {
            const label = source.cloneNode(true);
            label.setAttribute(ADDED, "");
            field.prepend(label);
          }
        }
        if (rest.classList.contains("inspection-record")) {
          const identity = document.createElement("p");
          identity.className = "record-continuation";
          identity.textContent = rest.dataset.recordTitle + " (continued)";
          rest.querySelector(".inspection-requirement").prepend(identity);
        }
        if (rest.tagName === "LI" && rest.dataset.pageContext) {
          const identity = document.createElement("span");
          identity.className = "record-continuation";
          identity.textContent = rest.dataset.pageContext + " (continued)";
          rest.prepend(identity);
        }
        const warning = rest.querySelector(".box")
          || (rest.matches(".stop, .caution") ? rest : null);
        if (warning) {
          const word = /\b(STOP|HOLD|CAUTION)\b/.exec(el.textContent);
          if (word) warning.prepend(word[1] + " (continued): ");
        }
        return rest;
      }
      if (relax && prepareFields(el)) return fragment(el, false);
      for (const figure of el.querySelectorAll("figure")) {
        const parent = figure.parentNode, slot = [...parent.childNodes].indexOf(figure);
        if (!originalText(contentsAt(el, [parent, slot]))
            && !fits(sourceBottom(el, [parent, slot + 1]))) {
          refuseFigure(figure, sourceBottom(el, [parent, slot + 1]) - pageTop);
        }
      }
      return null;
    }
    function contextRow(source) {
      const row = cleanLocatorCopy(source.cloneNode(true));
      row.classList.add("operation-continuation");
      row.setAttribute(ADDED, "");
      row.querySelectorAll(".performed-mark, .writing-blank, figure")
        .forEach((mark) => mark.remove());
      row.querySelectorAll(".field, .result-field, .authored-blank").forEach((field) => {
        field.replaceWith(...locatorFieldContext(field));
      });
      const number = row.querySelector(".op-number");
      if (number) number.append(" (continued)");
      return row;
    }
    function operationContext(t, body, progress) {
      const sources = operationHeads.get(body.dataset.op);
      if (!sources || !body.hasAttribute("data-operation-continuation")) return;
      const full = contextRow(sources[0]), identity = full.cloneNode(true);
      identity.querySelector(".op-action").remove();
      identity.querySelector(".op-head h3").replaceChildren(identity.querySelector(".op-number"));
      identity.querySelector(".op-details").remove();
      body.prepend(identity);
      const accepted = () => fits(prefixBottom(t, progress.row, progress.contents));
      if (!accepted()) {
        identity.remove();
        throw new Error("An operation identity cannot share a page with original source progress.");
      }
      identity.replaceWith(full);
      if (!accepted()) {
        full.replaceWith(identity);
        const compact = full.querySelector(".op-details").cloneNode(true);
        [...compact.children].forEach((field) => {
          if (!field.matches(".op-tool, .op-target, .op-direction")) field.remove();
        });
        identity.cells[0].append(compact);
        if (!accepted()) compact.remove();
      }
      const notes = sources.slice(1).map(contextRow);
      const head = [...body.rows].find((row) => row.hasAttribute(ADDED));
      head.after(...notes);
      if (!accepted()) notes.forEach((row) => row.remove());
    }
    function tableContext(t, progress, optionalOnly = false) {
      if (!t.hasAttribute(SPLIT)) return;
      refreshInstructionMirrors(t);
      refreshTitleCopies(t);
      const budget = contextBudget(t, progress);
      for (const source of tableHeads.get(t.dataset.tableContext) || []) {
        if (optionalOnly && !source.hasAttribute("data-optional-context")) continue;
        if (source.dataset.instructionRef && fullInstructionOnPage(source.dataset.instructionRef)) {
          continue;
        }
        const row = cleanLocatorCopy(source.cloneNode(true));
        row.setAttribute(ADDED, "");
        row.querySelectorAll(".performed-mark, .writing-blank, .tick, figure")
          .forEach((mark) => mark.remove());
        row.querySelectorAll(".field, .result-field, .authored-blank").forEach((field) => {
          field.replaceWith(...locatorFieldContext(field));
        });
        const columns = t.tHead.querySelector("tr:not(.repeat):not(.table-context)");
        const followingContext = optionalOnly && row.classList.contains("table-context")
          ? t.tHead.querySelector(`tr.table-context:not([${ADDED}])`) : null;
        (followingContext || columns).before(row);
        refreshTitleCopies(t);
        if (fits(budget())) continue;
        if (row.hasAttribute("data-optional-context")) {
          row.remove();
          continue;
        }
        const cell = row.cells[0];
        const locator = cell.querySelector("[data-continuation-locator]")?.cloneNode(true);
        const titleCell = cell.cloneNode(true);
        titleCell.querySelectorAll("[data-continuation-locator]").forEach((node) => node.remove());
        const text = titleCell.textContent;
        const boundary = text.search(/[;.!?]\s/);
        const identity = /^.*?\bop\s+\d+\b/.exec(text)
          || /\([^()]*\)(?=\s+\(continued\)$)/.exec(text);
        if (row.classList.contains("repeat")) {
          cell.replaceChildren();
          if (identity) cell.append(identity[0]);
          if (locator) {
            if (cell.textContent) cell.append(" · ");
            cell.append(locator);
          }
        } else if (boundary >= 0) {
          const range = document.createRange(), walker = document.createTreeWalker(
            cell, NodeFilter.SHOW_TEXT
          );
          let remaining = boundary + 1, node;
          range.selectNodeContents(cell);
          while ((node = walker.nextNode())) {
            if (remaining <= node.textContent.length) {
              range.setEnd(node, remaining); break;
            }
            remaining -= node.textContent.length;
          }
          cell.replaceChildren(range.cloneContents());
        } else cell.replaceChildren();
        if (!cell.textContent || !fits(budget())) {
          if (locator) {
            throw new Error("A contour progress locator cannot share a page "
              + "with original source progress.");
          }
          row.remove();
        }
      }
    }
    function fixtureContext(t, progress) {
      const row = progress.row, source = fixtureRows.get(row.dataset.rowContext);
      if (!source || !row.hasAttribute("data-row-continuation")) return;
      const budget = contextBudget(t, progress), copies = [];
      source.forEach((cell, slot) => {
        if (originalText(row.cells[slot])) return;
        const copy = document.createElement("span");
        copy.className = "row-continuation";
        copy.setAttribute(ADDED, "");
        copy.append(...[...cell.childNodes].map((node) => node.cloneNode(true)));
        copy.querySelectorAll(".performed-mark, .writing-blank, .tick")
          .forEach((mark) => mark.remove());
        if (slot === 0) copy.append(" (continued)");
        row.cells[slot].prepend(copy);
        copies.push(copy);
      });
      if (!fits(budget())) copies.forEach((copy) => copy.remove());
    }
    function splitBody(t, body) {
      const rows = [...body.rows];
      const ending = box(t).bottom - box(t.tBodies[t.tBodies.length - 1]).bottom;
      let index = rows.findIndex((row) => !fits(box(row).bottom + ending));
      while (index > 0 && !fits(prefixBottom(t, rows[index - 1]))) index -= 1;
      if (index < 0) return false;
      if (rows[index].hasAttribute(ADDED)) return false;
      if (rows.slice(0, index).every((row) => row.hasAttribute(ADDED))) {
        // No authored row fits beside the repeated heading: continue the oversized
        // row itself, never emit a page containing only a continuation label.
        const tail = fragment(rows[index]);
        if (!tail) return false;
        const completed = tail === rows[index];
        index += 1;
        // A complete original row has no fragment tail; following canonical rows still move.
        if (completed && index >= body.rows.length) return true;
      }
      const rest = body.cloneNode(false);
      if (!t.classList.contains("operations")) rest.setAttribute("data-duplex-fragment", "");
      rest.append(...[...body.rows].slice(index));
      body.after(rest);
      if (rest.classList.contains("operation")) {
        rest.setAttribute("data-operation-continuation", "");
      }
      return true;
    }
    function startTablePage(t) {
      t.setAttribute(SPLIT, "");
      t.tHead.querySelectorAll("tr.continued, tr.repeat, tr.table-context")
        .forEach((row) => row.remove());
      breakAt(t);
      const progress = sourceProgress(t, t.tBodies[0]);
      if (!progress) throw new Error("A continuation cannot advance its original source.");
      operationContext(t, t.tBodies[0], progress);
      tableContext(t, progress);
      fixtureContext(t, progress);
    }
    // Bodies from j onward go to a copy with the same headings, on the next page.
    function cut(t, j) {
      const rest = t.cloneNode(false);
      rest.setAttribute(SPLIT, "");
      for (const part of [...t.children]) {
        if (part.tagName !== "COLGROUP" && part.tagName !== "THEAD") continue;
        const copy = part.cloneNode(true);
        copy.querySelectorAll("tr.continued").forEach((row) => row.remove());
        copy.querySelectorAll("tr.repeat, tr.table-context").forEach((row) => row.remove());
        rest.append(copy);
      }
      rest.append(...[...t.tBodies].slice(j));
      t.after(rest);
      let more = null;
      const pointer = (side) => {
        const body = rest.tBodies[0];
        const op = body.dataset.op || body.rows[0].cells[0].textContent;
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
          // As in the base, move the table with its heading if even one group and
          // the pointer cannot fit. At a page top, keep the group and omit the pointer.
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
      startTablePage(rest);
      if (more) pointer(pages % 2 === 0 ? "on reverse" : "on the next sheet");
      table(rest);
    }
    function table(t) {
      const over = () => {
        refreshInstructionMirrors(t);
        refreshTitleCopies(t);
        const bodies = [...t.tBodies];
        if (!bodies.length) return -1;
        const ending = box(t).bottom - box(bodies[bodies.length - 1]).bottom;
        let index = bodies.findIndex((body) => !fits(box(body).bottom + ending));
        while (index > 0 && !fits(prefixBottom(t, bodies[index - 1]))) index -= 1;
        return index;
      };
      let j = over();
      if (j === 0 && move(t)) j = over();
      if (!t.classList.contains("operations")) {
        const bodies = [...t.tBodies];
        const authored = bodies.filter((body) => !body.hasAttribute("data-duplex-fragment"));
        const countBefore = (index) => bodies.slice(0, index).filter(
          (body) => !body.hasAttribute("data-duplex-fragment")
        ).length;
        // Only original ordinary-table groups count toward KEEP, never fragments
        // or added context. Feasibility includes the retained table's closing geometry.
        const tail = authored.length >= 2 * KEEP
          ? bodies.indexOf(authored[authored.length - KEEP]) : -1;
        if (j > 0 && j < bodies.length) {
          const before = countBefore(j), after = authored.length - before;
          if (before < KEEP || after < KEEP) {
            if (before >= KEEP && tail > 0 && fits(prefixBottom(t, bodies[tail - 1]))) {
              j = tail;
            } else if (move(t)) {
              j = over();
              if (j > 0 && countBefore(j) >= KEEP && tail > 0
                  && fits(prefixBottom(t, bodies[tail - 1]))) j = tail;
            }
          }
        }
      }
      // An authored caption may fit alone but not share even the first original row.
      // Keep its words there, then admit bounded context beside real source progress.
      if (j === 0 && t !== pageStart && !sourceProgress(t, t.tBodies[0])) {
        startTablePage(t);
        j = over();
      }
      if (j === 0) {
        if (!splitBody(t, t.tBodies[0])) {
          throw new Error(
            "An over-page table record could not be continued without losing content."
          );
        }
        j = 1;
      }
      if (j > 0 && j < t.tBodies.length) cut(t, j);
    }
    function refuseFigure(figure, required = box(figure).bottom - pageTop) {
      const height = box(figure).bottom - box(figure).top;
      const label = figure.querySelector("figcaption")?.textContent
        || figure.getAttribute("aria-label") || "Untitled figure";
      throw new Error(
        `A complete figure cannot fit on a print page: ${label} `
        + `(${height.toFixed(1)}px high; ${required.toFixed(1)}px required; `
        + `${CAP.toFixed(1)}px page capacity).`
      );
    }
    function walk(parent) {
      for (const el of [...parent.children]) {
        if (!el.isConnected || el.hasAttribute(ADDED)) continue;
        const b = box(el);
        if (fits(b.bottom)) continue;
        if (el.tagName === "TABLE") {
          table(el);
        } else if (el.classList.contains("signoff")) {
          const prev = el.previousElementSibling;
          if (prev && prev.tagName === "TABLE") {
            // Reuse the table splitter with space reserved for the existing signoff,
            // so even a one-operation continuation cannot leave it on a page alone.
            const capacity = CAP;
            CAP -= Math.max(b.bottom - box(prev).bottom, b.bottom - b.top);
            try { table(prev); } finally { CAP = capacity; }
          } else move(el);
        } else if (el.tagName === "FIGURE") {
          move(el);
          if (!fits(box(el).bottom)) refuseFigure(el);
        } else if (b.bottom - b.top <= CAP && move(el) && fits(box(el).bottom)) {
          continue;
        } else if (el.children.length
            && !el.matches("p, li, .page-context, .stop, .caution, .unverified")) {
          const s = getComputedStyle(el);
          if (s.display.endsWith("flex") && !s.flexDirection.startsWith("column")) {
            el.setAttribute(STACKED, "");
          }
          walk(el);
        } else {
          move(el);
          let current = el;
          while (!fits(box(current).bottom)) {
            const rest = fragment(current);
            if (!rest) throw new Error(
              "An over-page text block could not be continued without losing content."
            );
            breakAt(rest);
            current = rest;
          }
        }
      }
    }
    walk(section);
    section.querySelectorAll(".cont-head").forEach((head) => {
      head.querySelector(".cont-page-total").textContent = String(pages);
    });
    section.dataset.pages = pages;
    return pages;
  }
  function reset() {
    document.querySelectorAll(".blank-side, [" + ADDED + "]").forEach((el) => el.remove());
    // Restore the source DOM, not a second, partly split pagination layout. This also
    // restores text fragments, stacked blocks and authored list numbering before print.
    for (const [section, { source, images }] of originals) {
      const restored = source.cloneNode(true);
      [...restored.querySelectorAll("img, svg image")].forEach((copy, index) => {
        const image = images[index];
        // A fresh image clone cannot paint until after beforeprint returns. Keep the
        // loaded canonical leaf while restoring its pristine attributes and wrapper.
        for (const attribute of [...image.attributes]) {
          if (!copy.hasAttributeNS(attribute.namespaceURI, attribute.localName))
            image.removeAttributeNS(attribute.namespaceURI, attribute.localName);
        }
        for (const attribute of copy.attributes) {
          if (image.getAttributeNS(attribute.namespaceURI, attribute.localName) !== attribute.value)
            image.setAttributeNS(attribute.namespaceURI, attribute.name, attribute.value);
        }
        image.replaceChildren(...copy.childNodes);
        copy.replaceWith(image);
      });
      section.replaceChildren(...restored.childNodes);
      delete section.dataset.pages;
    }
  }
  function run() {
    const body = document.body, root = document.documentElement, saved = body.getAttribute("style");
    for (const section of document.querySelectorAll("section.page[data-sheet]")) {
      if (!originals.has(section)) originals.set(section, {
        source: section.cloneNode(true),
        images: [...section.querySelectorAll("img, svg image")]
      });
    }
    try {
      reset();
      delete root.dataset.paginationError;
      root.classList.add("paged", "print-measuring");
      body.style.cssText = "max-width:none;width:var(--page-content-width);margin:0;padding:0";
      const measure = document.createElement("div");
      measure.style.cssText = "position:absolute;visibility:hidden;pointer-events:none;"
        + "width:var(--page-content-width);height:var(--page-content-height)";
      body.append(measure);
      CAP = measure.getBoundingClientRect().height
        - parseFloat(getComputedStyle(root).getPropertyValue("--page-rounding"));
      root.dataset.pageCapacity = CAP;
      root.dataset.printWidth = measure.getBoundingClientRect().width;
      measure.remove();
      prepareLocators();
      document.querySelectorAll("ol").forEach((list) => {
        [...list.children].filter((item) => item.tagName === "LI").forEach((item, index) => {
          item.value = list.start + index;
        });
      });
      for (const section of [...document.querySelectorAll("section.page[data-sheet]")]) {
        if (paginate(section) % 2 === 0) continue;
        const blank = document.createElement("section");
        blank.className = "page blank-side";
        blank.setAttribute("aria-hidden", "true");
        section.after(blank);
      }
      finishLocators();
    } catch (error) {
      reset();
      root.classList.remove("paged");
      root.dataset.paginationError = error.message;
      console.error("Traveler print pagination:", error);
      const warning = document.createElement("p");
      warning.className = "caution";
      warning.setAttribute(ADDED, "");
      warning.textContent = "PRINT LAYOUT ERROR — " + error.message;
      body.prepend(warning);
    } finally {
      locatorPass = null;
      root.classList.remove("print-measuring");
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
# (op and pass numbers) keep their plain cells, except in a coordinate table: its
# auto-sized columns would squeeze a move number to one digit a line.
_NUMBER = re.compile(r"[-−+]?\d+\.\d+")
_WHOLE = re.compile(r"\d+")
_READING_VALUE = r"[-−+±]?(?:(?:\d+\s+)?\d+/\d+|\d+(?:\.\d+)?|\.\d+)"
_READING_UNITS = r"(?:\s*(?:(?:mm|in)(?:/(?:rev|min))?|rpm|sfm|°)(?!\w))?"
_READING = re.compile(
    rf"(?<![\w.])[-−+][XYZ] (?:{_READING_VALUE}{_READING_UNITS}|\?)(?!\w|\.\d)"
    rf"|(?<![\w.])(?:M\d+(?:\.\d+)?(?:\s*[x×]\s*\d+(?:\.\d+)?)?"
    rf"|#\d+-\d+|\d+/\d+-\d+)"
    rf"(?:\s*[x×]\s*{_READING_VALUE}{_READING_UNITS})?(?!\w|\.\d)"
    rf"|(?<![\w.])(?:[XYZØRD]\s*(?:[→=]\s*)?)?{_READING_VALUE}"
    rf"(?:\s*(?:[-–…±×]|\.\.\.)\s*(?:[ØRD]\s*)?{_READING_VALUE})*"
    rf"{_READING_UNITS}(?!\w|\.\d)"
    rf"|(?<![\d.])[-−+±]?(?:\d+\.\d+|\.\d+){_READING_UNITS}(?!\w|\.\d)"
)
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
    "purchased_tooling": "purchased tooling receipt check",
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
    "trial_cut_measure": (
        "take a light trial cut, withdraw along Z without moving X, stop the spindle, "
        "measure the diameter"
    ),
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


# A shop-made item the HOLD places (no pose places its solids): its make table gives
# positions in the item's own frame, and where it goes is the HOLD's to say.
LOOSE = "loose"
LOOSE_TEXT = "loose: placed as the HOLD says"
_ITEM_FRAME = ([0.0, 0.0, 0.0], [1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0])


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


# A make operation's fields as a STOP names them (:meth:`_Traveler.make_lines`).
_MAKE_OP_WORDS = {
    "hold": "hold",
    "tool": "tool",
    "rpm": "speed",
    "feed": "feed",
    "doc_mm": "depth of cut",
    "cite": "cutting-data source",
}


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


def _inward(low, high, unit="mm", places=None):
    """``(low, high)`` texts of a band given in mm, in ``unit`` (``mm`` to 0.001, ``in`` to
    0.0001, or to ``places`` decimals, a drawing's precision), rounded inward (low up, high
    down): never looser. A band too narrow for those decimals takes more until it is not
    reversed, and a cap ``(0, high)`` until it is not rounded to nothing. Three decimals
    past that a mm band prints exactly as declared; an inch band that cannot be stated
    inward is None (the mm band stands alone)."""
    scale, default = {"mm": (1.0, 3), "in": (25.4, 4)}[unit]
    places = default if places is None else places
    for decimals in range(places, places + 4):
        steps = 10**decimals
        lo = math.ceil(round(low / scale * steps, 6)) / steps
        hi = math.floor(round(high / scale * steps, 6)) / steps
        if lo <= hi and (hi > 0 or high <= 0):
            return f"{lo:.{decimals}f}", f"{hi:.{decimals}f}"
    return (repr(float(low)), repr(float(high))) if unit == "mm" else None


def _declared(value, places=0):
    """A declared limit as written: at least ``places`` decimals and every digit it holds,
    never rounded (:func:`_inward` states the one-point band ``[value, value]`` only
    exactly); ``?`` while unknown."""
    if not _known(value):
        return _text(value)
    return _inward(value, value, places=max(places, _places(value)))[0]


def _stated(value):
    """A text the shop can act on: not blank and not the unknown sentinel."""
    return isinstance(value, str) and value.strip() not in ("", "unknown")


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
    """Declared decimals fix the places, a half-way value rounding up (away from zero) as
    the shop rounds its written decimal, not its binary float (3.175 at two places is
    3.18); any other known number prints its own value (six significant digits, float
    residue below 1e-6 dropped), never ``?``. An acceptance limit never takes this rounding
    to fewer places than its own: :meth:`_Traveler.band` and :meth:`_Traveler.cap` round
    it inward."""
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return _text(value)
    if not math.isfinite(value):
        return "?"
    if isinstance(precision, int):
        # The pictures' own rounding: a picture and its table never print one value two ways.
        from prechips.kernel.render_diagram import decimal_text

        return decimal_text(value, precision)
    result = f"{round(value, 6):g}"
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


class _FixtureFeature(str):
    """One unchanged fixture-feature identity and its complete location/depth clause."""


# Every lathe X reading is a radius or a diameter: unread, each number is half or twice
# the cut on the other display, so none prints.
_X_DISPLAY_STOP = "STOP: X display not set (dro.radius_mode): X reads radius or diameter"


class _Plain(str):
    """A full-width line under a table row printed as plain text, not a warning box."""


class _Note(str):
    """An original note with repeatable identity and an optional requirement-owned sketch."""

    def __new__(cls, text, context=None, sketch=""):
        note = super().__new__(cls, text)
        note.context = context
        note.sketch = sketch
        return note


@dataclass(frozen=True)
class _Inspection:
    """One authored requirement and its associated result, never an acceptance mark."""

    text: str
    features: tuple[str, ...]
    requirement: str
    unit: str = ""
    qualitative: bool = False
    recording_at: str = ""


class _Row(tuple):
    """Table cells plus full-width warnings printed beneath the row."""

    def __new__(cls, cells, warnings=(), optional_observations=False):
        row = super().__new__(cls, cells)
        row.warnings = tuple(dict.fromkeys(warnings))
        row.optional_observations = optional_observations
        return row


def _numeric_html(text):
    """Escape source text without splitting a signed numeric value from its units."""
    text = str(text)
    parts, end = [], 0
    for reading in _READING.finditer(text):
        parts.append(escape(text[end : reading.start()]))
        parts.append(f'<span class="reading">{escape(reading.group())}</span>')
        end = reading.end()
    parts.append(escape(text[end:]))
    return "".join(parts)


def _p(text, css=""):
    attribute = f' class="{css}"' if css else ""
    return f"<p{attribute}>{_numeric_html(text)}</p>"


def _cell_line(line):
    if isinstance(line, _Box):
        return f'<span class="box">{_numeric_html(line)}</span>'
    if isinstance(line, _FixtureFeature):
        return f'<span class="fixture-feature">{_numeric_html(line)}</span>'
    return _numeric_html(line)


def _writing_field(label, css="field", *, punctuation=""):
    caption = f'<span class="field-label">{_numeric_html(label)}</span>' if label else ""
    if punctuation:
        caption = f'<span class="field-caption">{caption}{_numeric_html(punctuation)}</span>'
    return (
        f'<span class="{css}">{caption}'
        '<span class="writing-blank" aria-hidden="true"></span></span>'
    )


def _ledger_text(value):
    lines = value if isinstance(value, (list, tuple)) else [value]
    return "<br>".join(
        _cell_line(line) if isinstance(line, _Box) else _fields(line) for line in lines
    )


def _warning_line(warning):
    if isinstance(warning, _Note):
        return f'<div class="op-note">{_fields(warning)}</div>'
    if isinstance(warning, _Plain):
        return f'<span class="see">{_numeric_html(warning)}</span>'
    return _cell_line(_Box(warning))


def _action_body(value):
    lines = value if isinstance(value, (list, tuple)) else [value]
    parts = []
    for line in lines:
        if isinstance(line, _Box):
            parts.append(_cell_line(line))
            continue
        text, start = str(line), 0
        fields = list(_FIELD.finditer(text))
        for boundary in re.finditer(r"[.!?;]\s+(?=[A-Z])", text):
            end = boundary.end()
            if any(field.start() <= boundary.start() < field.end() for field in fields):
                continue
            parts.append(f"<p>{_fields(text[start:end])}</p>")
            start = end
        if start < len(text):
            parts.append(f"<p>{_fields(text[start:])}</p>")
    return "".join(parts)


def _ledger_row(row, headings):
    finishing = len(row) == 5
    if finishing:
        op, feature, consumable, action, checks = row
        fields = ("feature", "consumable")
        labels = headings[1:3]
        values = (feature, consumable)
    else:
        op, action = row[:2]
        checks = row[8]
        fields = ("feature", "tool", "speed", "feed", "target", "direction")
        labels, values = headings[2:8], row[2:8]
    result = [
        f'<tbody class="operation" data-op="{escape(op)}"><tr class="operation-main"><td>',
        '<div class="op-head">',
        '<span class="performed-mark" role="img" '
        f'aria-label="Operation {escape(op)} performed mark"></span>',
        f'<h3><span class="op-number">{"Step" if finishing else "Op"} {escape(op)}</span>'
        + (
            "</h3></div>" + f'<div class="op-action">{_action_body(action)}</div>'
            if finishing
            else f' — <span class="op-action">{_ledger_text(action)}</span></h3></div>'
        ),
        '<dl class="op-details">',
    ]
    for name, heading, value in zip(fields, labels, values, strict=True):
        result.append(
            f'<div class="op-{name}"><dt>{escape(heading)}</dt><dd>{_ledger_text(value)}</dd></div>'
        )
    result.append("</dl></td></tr>")
    for warning in row.warnings:
        result.append(f'<tr class="warn"><td>{_warning_line(warning)}</td></tr>')
    for check in checks:
        if not isinstance(check, _Inspection):
            result.append(f'<tr class="inspection-message"><td>{_ledger_text(check)}</td></tr>')
            continue
        features = ", ".join(check.features)
        label = "Readings / observations"
        if check.unit and not check.qualitative:
            label += f" ({check.unit})"
        label += " — feature / location when applicable"
        result.append(
            f'<tr class="inspection-record" data-feature="{escape(features)}" '
            f'data-features="{escape(json.dumps(check.features))}" '
            f'data-requirement="{escape(check.requirement)}" '
            f'data-record-title="{escape(features + " " + check.requirement)}"><td>'
            '<div class="inspection-layout"><div class="inspection-requirement">'
            + _p(check.text)
            + "</div>"
            + (
                _p(f"Record in {check.recording_at}.")
                if check.recording_at
                else _writing_field(label, "result-field")
            )
            + "</div></td></tr>"
        )
    if (
        row.optional_observations
        and not any(isinstance(check, _Inspection) for check in checks)
        and not _FIELD.search(str(action))
        and not any(_FIELD.search(str(warning)) for warning in row.warnings)
    ):
        result.append(
            '<tr class="process-observations" data-process="coating"><td>'
            + _writing_field("Additional writing space (optional)", "result-field")
            + "</td></tr>"
        )
    result.append("</tbody>")
    return "".join(result)


def _table(
    headings,
    rows,
    css="",
    widths=None,
    continued=None,
    repeat=None,
    strong=(),
    context=None,
    repeat_locator=None,
    repeat_owner=None,
):
    """Repeat the table's context on continuations. Each body is one keep-together group;
    operations use full-width ledger rows instead of compressed columns. ``strong``
    columns are the ones the operator reads from; a cell holding one number never wraps."""
    ledger = css == "operations"
    count = 1 if ledger else len(headings)
    columns = ""
    if widths and not ledger:
        columns = (
            "<colgroup>" + "".join(f'<col style="width:{w}%">' for w in widths) + "</colgroup>"
        )
    attribute = f' class="{css}"' if css else ""
    result = [_p(context, "table-intro")] if context else []
    result.extend((f"<table{attribute}>", columns, "<thead>"))
    for kind, title in (("continued", continued), ("repeat", repeat)):
        if title:
            locator = (
                '<span data-continuation-locator="progress">'
                + _numeric_html(repeat_locator)
                + "</span>"
                if kind == "repeat" and repeat_locator
                else ""
            )
            rendered_title = _numeric_html(title)
            if kind == "repeat" and repeat_owner:
                rendered_title = (
                    f'<span data-title-repeat="{escape(repeat_owner)}">'
                    + rendered_title
                    + "</span>"
                )
            result.append(
                f'<tr class="{kind}"><th colspan="{count}">{rendered_title}'
                + (" · " + locator if locator else "")
                + "</th></tr>"
            )
    if context:
        result.append(
            f'<tr class="table-context"><th colspan="{count}">{_numeric_html(context)}</th></tr>'
        )
    if ledger:
        result.append(
            "<tr><th>Performed mark: operation performed only — "
            "not inspection acceptance or clearance to proceed.</th></tr>"
        )
    else:
        result.append("<tr>")
        result.extend(
            f'<th class="read">{escape(h)}</th>' if i in strong else f"<th>{escape(h)}</th>"
            for i, h in enumerate(headings)
        )
        result.append("</tr>")
    result.append("</thead>")
    for row in rows:
        if ledger:
            result.append(_ledger_row(row, headings))
            continue
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
            if css == "zero" and index == 1 and getattr(row, "zero_surface", None):
                axis, face, start, end = row.zero_surface
                parts = [
                    _numeric_html(cell[:start])
                    + f'<span data-zero-axis="{escape(axis)}" data-zero-face="{escape(face)}">'
                    + _numeric_html(cell[start:end])
                    + "</span>"
                    + _numeric_html(cell[end:])
                ]
            if css == "readings" and index == 2:
                parts = [_writing_field(str(cell))]
            names = ["read"] if index in strong else []
            if isinstance(cell, str) and (
                _NUMBER.fullmatch(cell) or (css == "coords" and _WHOLE.fullmatch(cell))
            ):
                names.append("num")
            attributes = f' class="{" ".join(names)}"' if names else ""
            if css in ("fixture", "blank-check"):
                attributes += f' data-label="{escape(str(headings[index]))}"'
            result.append(f"<td{attributes}>" + "".join(parts) + "</td>")
        result.append("</tr>")
        if warnings:
            result.append(
                f'<tr class="warn"><td colspan="{len(headings)}">'
                + "".join(_warning_line(w) for w in warnings)
                + "</td></tr>"
            )
        result.append("</tbody>")
    result.append("</table>")
    return "".join(result)


def _levels(count):
    """A contour's depth-level tick boxes, one per level its whole path runs at; each box
    and its "level k of N" stay together on one line."""
    return (
        '<p class="levels">Done: '
        + " ".join(
            f'<span class="level"><span class="tick"></span>level {k} of {count}</span>'
            for k in range(1, count + 1)
        )
        + "</p>"
    )


class _Steps(tuple):
    """An inspection note authored as a list of steps: (heading, steps, calculations).
    ``sketch`` is the set-up sketch figure printed with it, if any."""

    sketch = ""


# Discovery is brace-only: underscore prompts never become named worksheet readings.
_NAMED_FIELD = re.compile(r"\{([^{}]+)\}")
# Presentation also gives standalone authored underscore prompts real pen room.
_FIELD = re.compile(r"\{([^{}]+)\}|(?<!\w)_{3,}(?!\w)")
# A step starting with this prints apart from the numbered steps, as the calculation line.
CALCULATION = "Calculate:"


def _fields(text, *, prose=True):
    text = str(text)
    parts, end = [], 0
    for field in _FIELD.finditer(text):
        prefix = text[end : field.start()]
        # A following decimal stays with its numeric token, not the field caption.
        following = re.match(r"[.,;:!?]+(?![\d.,;:!?])", text[field.end() :])
        punctuation = following.group() if following else ""
        if field[1] is not None:
            css = "field prose-field" if prose else "field"
            parts.extend(
                (_numeric_html(prefix), _writing_field(field[1], css, punctuation=punctuation))
            )
        else:
            # Keep the authored sentence/calculation caption with its sole box.
            boundaries = list(re.finditer(r"[.!?;]\s+", prefix))
            start = boundaries[-1].end() if boundaries else 0
            parts.extend(
                (
                    _numeric_html(prefix[:start]),
                    _writing_field(prefix[start:], "authored-blank", punctuation=punctuation),
                )
            )
        end = field.end() + len(punctuation)
    parts.append(_numeric_html(text[end:]))
    return "".join(parts)


def _readings(steps):
    """The ``(step number, field)`` readings a stepwise procedure's steps record."""
    return [(n, m.group(1)) for n, step in enumerate(steps, 1) for m in _NAMED_FIELD.finditer(step)]


def _worksheet(item):
    """Keep source step references, one value field per named reading, and authored calculations."""
    head, steps, calculations = item
    unit_sentence = re.compile(
        r"\bWrite (?:every|each|all) readings?\b(?:[^.!?]|\.(?=\d))*[.!?]?", re.I
    )
    units = list(
        dict.fromkeys(
            match.group() for step in steps for match in unit_sentence.finditer(str(step))
        )
    )
    metadata = (
        f' data-worksheet-title="{escape(_numeric_html(head.rstrip(":")))}"'
        f' data-reading-context="{escape(json.dumps([_numeric_html(unit) for unit in units]))}"'
    )

    def named(text):
        text = str(text)
        parts, end = [], 0
        for field in _NAMED_FIELD.finditer(text):
            # Named readings refer to their sole table-owned box; all other
            # source segments still receive the existing underscore pen space.
            parts.append(_fields(text[end : field.start()]))
            parts.append(f'<b class="reading">[{escape(field[1])}]</b>')
            end = field.end()
        parts.append(_fields(text[end:]))
        return "".join(parts)

    return (
        f'<div class="worksheet"{metadata}>'
        + _p("Take each reading at its step and write it in the READINGS table.")
        + item.sketch
        + '<ol class="steps">'
        + "".join(f"<li>{named(step)}</li>" for step in steps)
        + "</ol><h2>READINGS</h2>"
        + _table(
            ["step", "reading", "value"],
            [(str(n), f"[{name}]", name) for n, name in _readings(steps)],
            "readings",
            widths=[10, 30, 60],
        )
        + "".join(f'<p class="calc">{_fields(line, prose=False)}</p>' for line in calculations)
        + "</div>"
    )


def _item(item):
    if not isinstance(item, _Steps):
        context = getattr(item, "context", None)
        if context:
            return (
                f'<span class="page-context">{_numeric_html(context)}</span>'
                + _fields(str(item)[len(context) :])
                + getattr(item, "sketch", "")
            )
        return _fields(item) + getattr(item, "sketch", "")
    head, steps, calculations = item
    return (
        f'<span class="page-context">{_numeric_html(head)}</span>'
        + item.sketch
        + '<ol class="steps">'
        + "".join(f"<li>{_fields(step)}</li>" for step in steps)
        + "</ol>"
        + "".join(f'<p class="calc">{_fields(line, prose=False)}</p>' for line in calculations)
    )


def _list(items, ordered=True):
    tag = "ol" if ordered else "ul"
    rendered = []
    for item in items:
        context = item[0] if isinstance(item, _Steps) else getattr(item, "context", None)
        attribute = f' data-page-context="{escape(context)}"' if context else ""
        rendered.append(f"<li{attribute}>{_item(item)}</li>")
    return f"<{tag}>" + "".join(rendered) + f"</{tag}>"


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
        # A bare plan key in prose prints as the shop name of the one item it names: the
        # item every slot using it selects (:func:`setup_items`), when a bare reference
        # (:func:`select` with no slot) selects that item too, or nothing at all. Otherwise
        # the key names no one item (prose names it ``<category>.<key>``) and stays as is.
        slots = {}
        for setup in self.plan.get("setups") or []:
            for category, reference, _ in setup_items(bundle, _mapping(setup)):
                slots.setdefault(reference, set()).add(category)
        for reference, categories in sorted(slots.items()):
            if len(categories) == 1 and select(bundle, reference)[0] in categories | {None}:
                self.references[reference] = self.reference(reference, *categories)
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
            standing = self.along_setup_z(setup, definition)
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

    def along_setup_z(self, setup, definition):
        """Whether a feature's declared ``axis`` (in its own frame) lies along the setup
        frame's Z; None when either is not known."""
        declared = definition.get("axis")
        if not (isinstance(declared, list) and len(declared) == 3 and all(map(_known, declared))):
            return None
        frames = _mapping(self.bundle.features.get("frames"))
        source = _mapping(frames.get(definition.get("frame", "model")))
        basis = [source.get(k) for k in ("x", "y", "z")]
        if all(isinstance(b, list) and len(b) == 3 for b in basis):
            declared = [sum(declared[j] * basis[j][i] for j in range(3)) for i in range(3)]
        z = _mapping(setup_frame(self.bundle, setup)).get("z")
        if not (isinstance(z, list) and len(z) == 3 and all(map(_known, z))):
            return None
        norm = math.sqrt(sum(v * v for v in declared)) or 1.0
        return abs(sum(a * b for a, b in zip(declared, z, strict=True))) / norm > 0.999

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
        too narrow for that precision, or with a limit unknown, prints each limit exactly as
        declared (:func:`_declared`). A zone or maximum (``position_dia = 0.045``) prints as
        its :meth:`cap`."""
        precision = self.precision(feature, dimension)
        printed = printed_band(value, precision)
        if printed is not None:
            return "–".join(_number(limit, precision) for limit in printed)
        pair = isinstance(value, (list, tuple)) and len(value) == 2
        if pair and all(_known(limit) or limit == "unknown" for limit in value):
            places = precision if isinstance(precision, int) else 0
            return "–".join(_declared(limit, places) for limit in value)
        if dimension in ZONES:
            return self.cap(value, feature, dimension)
        return self.value(value, feature, dimension).replace(" / ", "–")

    def cap(self, value, feature=None, dimension=None):
        """A drawing maximum (a zone, an edge break), the band [0, value], at the drawing's
        precision rounded down so printing never loosens it, taking more decimals rather
        than printing nothing (:func:`_inward`); exactly as declared when that precision is
        not stated."""
        precision = self.precision(feature, dimension)
        if _known(value) and value > 0 and isinstance(precision, int):
            return _inward(0, value, places=precision)[1]
        return _declared(value)

    @staticmethod
    def metadata(key):
        return key in _METADATA or key.endswith(("_cite", "_verify")) or key == "verify"

    # ------------------------------------------------------------- vocabulary
    def reference(self, reference, slot=None):
        return reference_label(self.bundle, reference, slot)

    def short_reference(self, reference, slot=None):
        return short_reference_label(self.bundle, reference, slot)

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
        pair, conflict = projection_holder(self.bundle, item, holder)
        if conflict:
            detail.append("projection ? (stated twice in the shop list)")
        for field, scale in (("projection_mm", 1.0), ("projection_in", 25.4)):
            projection = _amount(_mapping(item.get(field)).get(pair))
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
        """Plan / rule prose in shop words: no ids, files, hashes or long decimals.
        Registered bare names replace whole reference tokens, never a word's substring."""
        setup = setup or self.setup
        text = str(text) if text is not None else "?"
        text = re.sub(r"(?i)\bAUTHOR'S CHOICE\b\s*:?\s*", "", text)
        text = re.sub(
            r"#\d+/ADVANCED_FACE\[\d+\]/\w+",
            lambda m: self.feature_name(self.faces[m[0]]) if m[0] in self.faces else "a face",
            text,
        )
        registered = "|".join(
            re.escape(reference) for reference in sorted(self.references, key=len, reverse=True)
        )
        # Consume qualified references whole in the same pass: their printed unknown
        # label must not be rewritten again as a registered bare key.
        pattern = NAMED_REFERENCE.pattern + (
            rf"|(?<![\w./-])(?:{registered})(?![\w/-]|\.[\w#])" if registered else ""
        )
        text = re.sub(
            pattern,
            lambda match: self.shop_names(match[0]) if match[1] else self.references[match[0]],
            text,
        )
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

    def shop_names(self, text):
        """``text`` with each inventory item it names (``gauges.dti``) as its shop name, read
        in the category it names; one that category does not have prints ``? <key>``
        (tool_resolves reports it unknown), and one it states unknown ``? <category>.<key>``."""
        return NAMED_REFERENCE.sub(
            lambda m: (
                reference_label(self.bundle, m[0]).removesuffix(" (not in shop list)")
                if named_item(self.bundle, m[0]) is not None
                else f"? {m[2]}"
            ),
            text,
        )

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
            mount = "Mount the " + self.reference(fixture, "workholding")
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
            line = "Parallels: " + self.reference(hold["parallels"], "fixtures")
            if stated("riser"):
                line += ", standing on " + self.reference(hold["riser"], "fixtures")
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
            pointer = self.shop_made_pointer(setup, hold["jaw_buttons"], uses)
            steps.append(self.jaw_buttons(hold["jaw_buttons"], pointer))
        supports = hold.get("supports")
        if isinstance(supports, str) and supports not in ("none", "not_applicable", "unknown"):
            riser = hold.get("riser")
            if not (
                stated("riser")
                and identity(self.bundle, supports, "fixtures")
                == identity(self.bundle, riser, "fixtures")
            ):
                steps.append(
                    "Supports: "
                    + self.reference(supports, "fixtures")
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
                line = label + self.reference(hold["support"], "fixtures")
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
            line = f"{label} {role}: {self.reference(clamp.get('ref'), 'fixtures')}"
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
        return (
            "<h2>HOLD</h2>" + _list(steps),
            below + self.indexing(setup),
        )

    def align_step(self, setup, hold):
        """The step that squares a vise's fixed jaw, or an angle plate's locating face, to
        the table travel where this setup mounts or turns one (hold_fields ``align_due``):
        its indicator, sweep length and limit come from ``hold.align``; any not established
        is a STOP."""
        due = _mapping(self.records.get(("hold_fields", setup["id"]))).get("align_due")
        if due in (None, "not_applicable"):
            return []
        ref = hold.get("fixture")
        kind = _mapping(resolve(self.bundle, "workholding", ref))
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
            f"{_declared(limit)} mm ({_number(round(limit / 25.4, 5))} in) over that length, "
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
            steps.append(line + "; write it down for the DRO table. " + "{" + axis.upper() + " M}")
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
            + _table(
                ["check", "limit and method", "gauge"],
                rows,
                css="blank-check",
                widths=[14, 61, 25],
            )
        )

    def jaw_buttons(self, reference, pointer=""):
        """The jaw-button step with the sizes the jaws close on, each a measured fact as the
        kernel places them: a size without a measurement prints as not measured, never as
        a nominal. ``pointer`` (where the buttons are made) follows the reference."""
        item = measurement_item(self.bundle, "fixtures", reference)
        sizes = []
        for key, label in (
            ("dia", "face Ø"),
            ("thickness", "thickness "),
            ("spigot_dia", "spigot Ø"),
            ("spigot_length", "spigot length "),
        ):
            fact = length_fact(item, key, require_measured=True)
            value = fact["value"] if fact["verified"] else None
            measured = _known(value) and value > 0
            sizes.append(label + (f"{self.operative(value)} mm" if measured else "? not measured"))
        name = self.reference(reference, "fixtures") + pointer
        return (
            f"Jaw buttons: {name} ({', '.join(sizes)}), one between each jaw and the work, its "
            "spigot in the work's bore."
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
            # The work's height above the jaw tops, from the same fields: the one source, so
            # plan text must not restate it (consistency), and an unknown or unverified input
            # prints "?".
            scale = {"mm": 1.0, "in": 25.4}.get(self.units)
            jaw_top = jaw_top_z(self.bundle, setup, hold, scale)
            top = _mapping(setup.get("stock_state")).get("top_z")
            if jaw_top is not None and _known(top):
                above = (top - jaw_top) * scale
                facts.append(
                    ("work top above jaw tops mm", o(above))
                    if above >= 0
                    else ("work top below jaw tops mm", o(-above))
                )
            else:
                facts.append(
                    (
                        "work top above jaw tops mm",
                        "? jaw height, parallels, seat or stock top unknown or unverified",
                    )
                )
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
    def shop_made(self, setup, reference):
        """The shop-made holding item with something to make (:func:`shop_made_item`), the
        one the setup's hold selects (:func:`_holding_slot`)."""
        return shop_made_item(self.bundle, reference, _holding_slot(setup, reference))

    def shop_made_uses(self, setup):
        """``{identity: (reference, [(label, pose)])}`` for each shop-made item the hold
        uses, keyed by the item its reference selects (:meth:`holding_identity`) with its
        first spelling for print, in HOLD
        order: the fixture at ``hold.pose``, each clamp entry at its own pose (labelled by
        :func:`clamp_labels`), the work stop at ``stop_pose``. An item whose solids nothing
        poses, because the HOLD places it (a vise's own jaw plates, the riser, supports,
        jaw buttons: the kernel builds those from their facts), is :data:`LOOSE`."""
        hold = _mapping(setup.get("hold"))
        clamps = hold.get("clamps") if isinstance(hold.get("clamps"), list) else []
        fixture = hold.get("fixture")
        vise = _mapping(self.shop_made(setup, fixture)).get("kind") == "vise"
        placed = [(fixture, None, LOOSE if vise else hold.get("pose"))]
        placed += [
            (_mapping(clamp).get("ref"), label, _mapping(clamp).get("pose"))
            for label, clamp in zip(clamp_labels(hold), clamps, strict=True)
        ]
        placed.append((hold.get("stop_fixture"), "stop", hold.get("stop_pose")))
        placed += [(hold.get(key), None, LOOSE) for key in ("riser", "supports", "jaw_buttons")]
        uses = {}
        for reference, label, pose in placed:
            key = self.holding_identity(setup, reference)
            if self.shop_made(setup, reference) is None or (pose in (None, LOOSE) and key in uses):
                continue
            uses.setdefault(key, (reference, []))[1].append((label, pose))
        return uses

    def holding_identity(self, setup, reference):
        """The item a hold reference selects (:func:`identity`) in its slot
        (:func:`_holding_slot`): ``plate`` and ``fixtures.plate`` are one item."""
        return identity(self.bundle, reference, _holding_slot(setup, reference))

    def shop_made_name(self, setup, reference):
        """The shop name of a hold reference's item in its slot (:func:`_holding_slot`),
        as its SHOP-MADE FIXTURE table titles it."""
        return self.reference(reference, _holding_slot(setup, reference))

    def shop_made_home(self, setup, key, uses):
        """The setup whose sheet 2 prints this item's table: its first use at these poses
        under these HOLD labels (a renumbered clamp gets its own table)."""
        return self.shop_made_homes.setdefault((key, repr(uses[key][1])), setup["id"])

    def shop_made_pointer(self, setup, reference, uses):
        """`` (shop-made: …)`` naming the setup with the item's table; empty otherwise."""
        key = self.holding_identity(setup, reference)
        if not isinstance(reference, str) or key not in uses:
            return ""
        home = self.shop_made_home(setup, key, uses)
        return f" (shop-made: SHOP-MADE FIXTURE table, Setup {home})"

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
        item = _mapping(resolve(self.bundle, "workholding", fixture))
        angle_plate = item.get("kind") == "angle_plate"
        axes = _pose_axes(hold.get("pose"))
        solids = item.get("solids") if isinstance(item.get("solids"), list) else []
        if axes is None or not (angle_plate or self.holding_identity(setup, fixture) in uses):
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
        name = "Angle plate" if angle_plate else self.reference(fixture, "workholding")
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
        for reference, placements in uses.values():
            tags = [label if len(placements) > 1 else None for label, _ in placements]
            for solid in self.shop_made(setup, reference).get("solids") or []:
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
        part on its locators (and its declared preload), with any declared torque; a clamp
        declared ``tighten = "hand"`` is tightened by hand only."""
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
        hand = [labels[i - 1] for i in steps if _mapping(clamps[i - 1]).get("tighten") == "hand"]
        if len(steps) == 1:
            text = (
                f"Tighten {named} by hand only, no wrench"
                if hand
                else f"Tighten {named}: snug it, then tighten fully"
            )
        elif len(hand) == len(steps):
            text = (
                f"Tighten in order {named} by hand only, no wrench: snug each in turn, then "
                "tighten each by hand in the same order"
            )
        else:
            text = (
                f"Tighten in order {named}: snug each in turn, then tighten each fully "
                "in the same order"
            )
            if hand:
                text += f"; {', '.join(hand)} by hand only, no wrench"
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

    def shop_made_sizes(self, setup, reference):
        """``[(solids, size)]`` for each made SHOP-MADE FIXTURE row (:meth:`shop_made_rows`):
        its solids and Size mm cell, ``?`` for a row :meth:`shop_made_parts` withholds."""
        _, made, withheld, _, drilled, fits = self.shop_made_parts(setup, reference)
        sizes = []
        for members in self.shop_made_rows(made, withheld, drilled):
            first = members[0]
            if _supply(first) != "made":
                continue
            size = "?" if id(first) in withheld else self.solid_size(first, id(first) in fits)
            sizes.append((members, size))
        return sizes

    @staticmethod
    def shop_made_rows(made, withheld, drilled):
        """The SHOP-MADE FIXTURE table's rows, each its solids: identical ``made`` solids
        share one (a withheld solid is its own); an existing solid is a row only when holes
        are cut in it (``drilled``)."""
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
        return list(groups.values())

    def solid_position(self, solid, axes, fit=False):
        """Setup-frame position (or item-frame, for an item the HOLD places): a box's X/Y/Z
        extents, a cylinder's axis."""
        if axes == LOOSE:
            return LOOSE_TEXT
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
        at one of them prints the same value in every table. Then the make operations of
        each item this setup is the first to hold with and no table here carries
        (:meth:`make_operation_lists`)."""
        uses = self.shop_made_uses(setup)
        self.fit_places = {}
        for reference, placements in uses.values():
            solids, _, withheld, _, _, fits = self.shop_made_parts(setup, reference)
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
            for key, (reference, placements) in uses.items()
            if self.shop_made_home(setup, key, uses) == setup["id"]
        )
        self.fit_places = {}
        return tables + self.make_operation_lists(setup, uses)

    @functools.cached_property
    def make_homes(self):
        """``(first_use, first_table)``, each ``{(category, reference): setup id}`` keyed by
        the item selected (:func:`identity`): the first setup that holds with the item
        through any slot (:func:`setup_items`), its make operations made before it and
        printed there only, and the first whose sheet 2 prints its make table
        (:meth:`shop_made_uses`)."""
        first_use, first_table = {}, {}
        for setup in self.bundle.plan.get("setups") or []:
            for category, reference, *_ in setup_items(self.bundle, setup):
                first_use.setdefault((category, reference), setup.get("id"))
            for key in self.shop_made_uses(setup):
                first_table.setdefault(key, setup.get("id"))
        return first_use, first_table

    def make_operation_lists(self, setup, uses):
        """The make operations (:meth:`make_lines`) of each shop-made item this setup is the
        first to hold with, through any slot, when no make table on this sheet carries them
        (``uses``: this setup's :meth:`shop_made_uses`), under the item's name and a
        pointer to its later make table, if any: a declared operation prints once, before
        the item is first needed."""
        first_use, first_table = self.make_homes
        html = ""
        for category, reference, *_ in setup_items(self.bundle, setup):
            key = (category, reference)
            if category not in WORKHOLDING_CATEGORIES or first_use.get(key) != setup["id"]:
                continue
            if key in uses:
                continue
            lines = self.make_lines(shop_made_item(self.bundle, reference, category), {})
            if not lines:
                continue
            table = first_table.get(key)
            title = f"SHOP-MADE FIXTURE — {self.reference(reference, category)}"
            html += (
                f"<h2>{escape(title)}</h2>"
                + _p(f"Make before Setup {setup['id']}.")
                + (
                    _p(f"Sizes and positions: SHOP-MADE FIXTURE table, Setup {table} sheet 2.")
                    if table
                    else ""
                )
                + _p("Make operations, in order:")
                + "".join(_p(line) for line in lines)
            )
        return html

    def shop_made_parts(self, setup, reference):
        """The item's solids, made solids, withheld solids (id -> why), holes per parent
        solid id, drilled parent ids and fit ids: a locating solid is a fit, and so is every
        bore cut in it (either may be the surface that locates). Like the kernel, an
        unverified primitive gives no numbers, and an unverified hole withholds the solids it
        would cut."""
        item = self.shop_made(setup, reference)
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
        made row's or made hole's ``note`` (material, heat treatment, finish, how it is
        cut) one "Make:" entry under that, then its ``make_ops`` one cutting-data line
        each (:meth:`make_lines`) when this setup is the first to hold with it (else where
        they print: :meth:`make_homes`); solids already in the shop (``supply =
        "existing"``, such as machine vise jaws drawn for clearance) are not rows. A
        bought or existing part's note prints on a "Notes:" line after the Make entries,
        and every solid's ``records`` print as fill-ins (:meth:`record_blank`) under
        "Measure and record before first use:". A fit position printed ``?`` says why
        under the table. An item only the HOLD places (:data:`LOOSE`) gives its positions
        in its own frame, the one its solids are drawn in."""
        sid = setup["id"]
        item = self.shop_made(setup, reference)
        loose = all(pose == LOOSE for _, pose in placements)
        placed = [
            (label, _ITEM_FRAME if loose else LOOSE if pose == LOOSE else _pose_axes(pose))
            for label, pose in placements
        ]
        solids, made, withheld, holes, drilled, fits = self.shop_made_parts(setup, reference)
        self.fixture_unknowns = set()

        def prefixed(tag, name, count, where):
            parts = (tag if len(placed) > 1 else None, name if count > 1 else None)
            prefix = " ".join(part for part in parts if part)
            return f"{prefix}: {where}" if prefix else where

        rows, notes, components = [], {}, {}
        groups = self.shop_made_rows(made, withheld, drilled)
        for members in groups:
            label = members[0].get("label")
            names = [_solid_name(solid.get("name", "?")) for solid in members]
            stem, tags = _name_group(names)
            component = f"{stem} ×{len(members)}" if stem else " / ".join(names)
            component = self.bench(label) if label else component
            components.update(dict.fromkeys(map(id, members), component))
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
                positions.append(_FixtureFeature(f"with {count} × {what}: {spots}"))
            rows.append(
                [
                    component,
                    self.solid_size(first, fit) if _supply(first) == "made" else "—",
                    positions,
                    self.bench(first["locates"]) if first.get("locates") else "—",
                    self.bench(first["fastener"]) if first.get("fastener") else "—",
                ]
            )
        # A made hole's note (how it is cut) is a Make entry; a bought or existing part's
        # note (its state as bought, what to leave alone) prints apart, as Notes.
        listed = {id(s) for members in groups for s in members}
        others = {}
        for solid in solids:
            note = solid.get("note")
            name = self.bench(solid.get("label") or _solid_name(solid.get("name", "?")))
            if not note or id(solid) in listed:
                continue
            made_hole = solid.get("void") and _supply(solid) == "made"
            entry = (notes if made_hole else others).setdefault(self.bench(note).rstrip("."), [])
            if name not in entry:
                entry.append(name)
        records = [
            self.record_blank(solid, blank)
            for solid in solids
            for blank in solid.get("records") or []
            if isinstance(blank, dict)
        ]
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
            rows.append([body, size, [LOOSE_TEXT if loose else "? not posed"], "—", "—"])
        frame = f"its own frame ({LOOSE_TEXT})" if loose else f"Setup {sid}"
        headings = [
            "Component",
            "Size mm",
            f"Position, {frame} X / Y / Z mm",
            "Locates",
            "Fastener",
        ]
        widths = [17, 15, 40, 14, 14]
        keep = [0, 1, 2] + [c for c in (3, 4) if any(row[c] != "—" for row in rows)]
        spare = sum(w for c, w in enumerate(widths) if c not in keep)
        widths = [widths[c] + (spare if c == 2 else 0) for c in keep]
        users = [label for label, _ in placements if label and label != "stop"]
        title = f"SHOP-MADE FIXTURE — {self.shop_made_name(setup, reference)}"
        title += f" ({', '.join(users)})" if users else ""
        # Its make operations print once, before the first setup holding with it (whichever
        # slot): a later table names that setup and points back to them.
        first = self.make_homes[0].get(self.holding_identity(setup, reference))
        first = first if first and make_ops(item) else sid
        intro = (
            f"Make before Setup {first}. "
            + (
                f"Nothing poses it in the Setup {sid} frame: set it where the HOLD says. "
                "Positions are in the item's own frame"
                if loose
                else f"Positions are in the Setup {sid} frame"
            )
            + ": boxes give their X / Y / Z extents, cylinders their axis."
        )
        hardware = self.hardware(
            [s for s in solids if not s.get("void") and _supply(s) == "bought"], len(placed)
        )
        operations = self.make_lines(item, components) if first == sid else []
        return (
            f"<h2>{escape(title)}</h2>"
            + _p(intro)
            + (
                _table(
                    [headings[c] for c in keep],
                    [[row[c] for c in keep] for row in rows],
                    css="fixture",
                    widths=widths,
                    repeat=title + " (continued)",
                )
                if rows
                else ""
            )
            + (_p(f"Bought hardware (not made): {hardware}.") if hardware else "")
            + (_p(f"Make: {_make_notes(notes)}.") if notes else "")
            + (_p("Make operations, in order:") if operations else "")
            + "".join(_p(line) for line in operations)
            + (
                _p(f"Make operations: Setup {first} sheet 2.")
                if first != sid and make_ops(item)
                else ""
            )
            + (_p(f"Notes: {_make_notes(others)}.") if others else "")
            + (_p("Measure and record before first use:") if records else "")
            + "".join(_p(line) for line in records)
            + "".join(_p(reason) for reason in sorted(self.fixture_unknowns))
        )

    def make_lines(self, item, components):
        """The item's make operations (:func:`make_ops`), one numbered line each in the
        order they are run: ``1. hold: …; T: <tool>; 600 rpm; 0.05 mm/rev; 0.5 mm/pass;
        <source>``, a primitive's own after its make-table component. A field not known
        prints ``?`` (a tool the shop's tools do not list, ``? <key>``; one still to verify,
        ``? <tool>``) and the line ends in a STOP naming it: never left out. The hold and
        the source print as written, an item they name as its shop name."""
        lines = []
        for index, (solid, op) in enumerate(make_ops(item), 1):
            head = f"{index}. "
            if solid is not None:
                name = solid.get("label") or _solid_name(solid.get("name", "?"))
                head += f"{components.get(id(solid)) or self.bench(name)} — "
            if not isinstance(op, dict):
                lines.append(head + "? — STOP: make operations not established; do not make it.")
                continue
            tool, rpm = op.get("tool"), op.get("rpm")
            missing = set(make_op_unknowns(op))
            # The tools item only (:func:`make_tool`): one the tools do not list, or stated
            # unknown, is not established; one still to verify prints its name, unknown.
            found = None if "tool" in missing else make_tool(self.bundle, tool)
            if found is None or found.get("kind") == "unknown":
                missing.add("tool")
            unverified = "tool" not in missing and uncertain(found)
            texts = {
                "hold": f"hold: {self.authored(op.get('hold'))}",
                "tool": f"T: {'? ' if unverified else ''}{self.tool_name(tool)}",
                "rpm": "–".join(map(_declared, rpm if isinstance(rpm, list) else [rpm])) + " rpm",
                "feed": str(op.get("feed")).strip(),
                "doc_mm": f"{_declared(op.get('doc_mm'))} mm/pass",
                "cite": self.authored(op.get("cite")),
            }
            blanks = {
                "hold": "hold: ?",
                "tool": f"T: ? {tool}" if _stated(tool) else "T: ?",
                "rpm": "? rpm",
                "feed": "? feed",
                "doc_mm": "? mm/pass",
                "cite": "? cutting-data source",
            }
            line = head + "; ".join(
                blanks[key] if key in missing else texts[key] for key in MAKE_OP_FIELDS
            )
            named = [
                _MAKE_OP_WORDS[key] if key in missing else "tool verification"
                for key in MAKE_OP_FIELDS
                if key in missing or (key == "tool" and unverified)
            ]
            if named:
                line += f" — STOP: {', '.join(named)} not established; do not run it."
            lines.append(line)
        return lines

    def authored(self, text):
        """Authored text whole, as written (a link or path in it too), each inventory item it
        names outside its links and paths (:func:`authored_names`) as its shop name."""
        text = " ".join(str(text).split())
        printed, last = "", 0
        for start, end, _ in authored_names(text):
            printed += text[last:start] + self.shop_names(text[start:end])
            last = end
        return printed + text[last:]

    def record_blank(self, solid, blank):
        """One record blank as a fill-in: ``head: head-to-shoulder TIR — 0.0005 in test
        indicator, rolled in the V-block: accept ≤ 0.010 mm, goal ≤ 0.003 mm; measured
        ________ mm``. The spec and goal print rounded down (never looser); a gauge the
        shop list does not have prints ``? <key>``; no spec is recorded, not judged."""
        component = self.bench(solid.get("label") or _solid_name(solid.get("name", "?")))
        line = f"{component}: {self.bench(blank['check'])}"
        tools = []
        gauge = blank.get("gauge")
        if isinstance(gauge, str) and gauge not in ("none", "not_applicable"):
            present = named_item(self.bundle, f"gauges.{gauge}") is not None
            tools.append(self.reference(gauge, "gauges") if present else f"? {gauge}")
        if _stated(blank.get("how")):
            tools.append(self.bench(blank["how"]))
        if tools:
            line += " — " + ", ".join(tools)
        limits = [
            f"{word}≤ {_inward(0, blank[key])[1]} mm"
            for key, word in (("max_mm", "accept "), ("goal_mm", "goal "))
            if _known(blank.get(key))
        ]
        if limits:
            line += ": " + ", ".join(limits)
        over = blank.get("over_mm")
        span = f" over {over:g} mm" if _known(over) else ""
        return f"{line}; measured ________ mm{span}"

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
                    f"{self.short_reference(numbers.get('fixture'), 'workholding')}; continuous "
                    "rotation turned by the rotary ops; no plate landings."
                )
            )
        r = _number  # Dividing-head arithmetic keeps its own digits; it is not a DRO reading.
        glyph = _GLYPHS.get(_status(finding), "")
        tentative = "Tentative — " if _status(finding) == "unknown" else ""
        fixture = self.short_reference(numbers.get("fixture"), "workholding")
        head = f"Index: {glyph} {tentative}{fixture}: "
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
                gaps = [gap for gap in approaches.values() if _known(gap)]
                text = f"Jaw fronts at Z {o(jaw)}"
                if len(gaps) < len(approaches):
                    # A tool whose reach is unknown may stand nearer than any known one.
                    text += "; closest tool approach not computed — check at the machine"
                elif gaps:
                    text += f"; closest planned tool stop {o(min(gaps))} mm from the jaws"
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
                ["op", "tool", "closest obstacle", "clearance mm"],
                [
                    _Row(row[:4], [_Plain("action: " + row[4])]) if row[4] else row[:4]
                    for row in rows
                ],
                css="clearance",
                widths=[12, 12, 55, 21],
            )
        # One block: the pagination moves the whole section rather than leave its travel
        # lines on one page and its table on the next.
        return f'<div class="keep">{html}</div>'

    def clearance_rows(self, setup, numbers, tool_numbers):
        """One row per cutting op (ops sharing a tool, obstacle, clearance and action share
        a row): the smallest known clearance among the head travel left above the work
        (headroom ``margin_mm``), the jaw tops (``cut_tip_above_jaws_mm``, as the op row's
        box measures it), the holder face above the highest stock beside the tool, any
        reach ``clearances`` entry and the holding solid nearest the op's tool sweep
        (:meth:`cut_clearance`, a hand-feed check within the crash zone); an unknown one or
        an unproven wall clearance is the action. A bench file (``HAND_FINISH``) has no
        tool, head or jaws: its row is the holding nearest the material it files, a check to
        keep the file clear within the crash zone. Every Z printed is the surface's one DRO
        Z (:meth:`surface_z`)."""
        o = self.operative
        stacks = {str(s.get("op")): s for s in numbers.get("stacks", []) if isinstance(s, dict)}
        tips = _mapping(numbers.get("cut_tip_above_jaws_mm"))
        jaw = _mapping(numbers.get("jaw_obstruction")).get("jaw_top_z")
        merged = {}
        for op in setup.get("ops", []):
            name = str(op.get("op"))
            hand = op.get("do") in HAND_FINISH
            if not hand and (op.get("do") in MANUAL or op.get("tool") in (None, "unknown")):
                continue
            candidates, actions = [], []
            if not hand:
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
                actions.append(
                    f"keep the file clear of the {near}"
                    if hand
                    else f"hand feed past the {near}; check the cutter clears it"
                )
            if _known(value) and value < 0 and not any(a.startswith("STOP") for a in actions):
                actions.append("STOP: does not clear")
            pair = self.tool_pair(op.get("tool"), op.get("holder"))
            tool = "" if hand else tool_numbers.get(pair, "")
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
        """Distance from each op's nearest approach to the jaw fronts (exposed side +Z): the
        least of its planned Zs and, for a turning op, the chuck-side extent of its whole
        tool (accessibility ``tool_z_mm``: insert or blade, head, shank and body), not just
        the Z its op names; ``"unknown"`` when the kernel could not pose the whole tool or
        reported no extent for it.

        The kernel stands the tool on the drawn profile. An op fed to the imaginary-tip
        readings of its contour tables (:meth:`contour_tips`) stands where those put its
        nose instead, its whole outline carried there rigidly (``tool_z_mm`` reaching
        below ``nose_z_mm`` by as much as at every kernel pose): a profile the plan forms
        elsewhere than drawn (a cut-to-fit end) moves the tool with it. An op whose
        table prints no tool readings has an unknown approach."""
        jaw = self.jaw_front_z(setup)
        result = {}
        if jaw is None:
            return result
        scale = {"mm": 1.0, "in": 25.4}.get(self.units)
        for op in setup.get("ops", []):
            if op.get("do") in MANUAL:
                continue
            zs = self.path_zs(setup, op)
            if not zs:
                continue
            if approach(self.bundle, setup, op) == TURNING:
                key = ("accessibility", f"{setup['id']}:{op['op']}")
                numbers = _mapping(self.records.get(key))
                tool, nose = numbers.get("tool_z_mm", "unknown"), numbers.get("nose_z_mm")
                known = isinstance(tool, list) and tool and all(_known(z) for z in tool)
                posed = isinstance(nose, list) and nose and all(_known(z) for z in nose)
                lowest = min(tool) if known else "unknown"
                tips = self.contour_tips(setup, op)
                named = min(zs) * scale if scale else None
                if tips is not None:
                    lowest = (
                        min(tips) * scale - (nose[0] - tool[0])
                        if known and posed and tips != "unknown" and scale
                        else "unknown"
                    )
                elif (
                    known
                    and posed
                    and named is not None
                    and tool[0] == nose[0]
                    and 0 <= named - nose[0] <= FACE_Z_TOL_MM
                ):
                    # The kernel poses the nose against the face at the op's named Z only to
                    # its hit-test inset (LIFT, the 0.001 mm of FACE_Z_TOL_MM): a nose that
                    # far past that Z, and the tool's lowest point, stands at it. Any other
                    # part's reach past it (a shank, a blade's far face) is the tool's own.
                    lowest = named
                # Millimetres; down-rounded so the jaw gap is never overstated.
                face = self.mm_on_grid(setup, lowest, up=False)
                if not _known(face):
                    result[str(op["op"])] = "unknown"
                    continue
                zs = [*zs, face]
            result[str(op["op"])] = min(zs) - jaw
        return result

    def contour_tips(self, setup, op):
        """The imaginary-tip Zs (plan units) ``op``'s contour tables feed its tool to: every
        row of its dome finish tables and their rough stairs, each touched off on a +Z end
        face and so placing the nose's lowest point. None when the op has no finish table;
        ``"unknown"`` when one prints no tool readings (only the surface, which the nose
        does not stand on) or any reading is unknown."""
        numbers = _mapping(self.records.get(("coordinates", setup["id"])))

        def mine(key):
            return [
                table
                for table in numbers.get(key) or []
                if isinstance(table, dict) and str(table.get("op")) == str(op.get("op"))
            ]

        finish = [table for table in mine("contours") if table.get("method") == "axial_table"]
        if not finish:
            return None
        if not all(_known(table.get("tool_nose_compensation_mm")) for table in finish):
            return "unknown"
        rows = [(row, "z_tool_mm") for table in finish for row in table.get("rows", [])]
        rows += [(row, "z_mm") for table in mine("stair_tables") for row in table.get("rows", [])]
        tips = [_mapping(row).get(key) for row, key in rows]
        return tips if tips and all(_known(z) for z in tips) else "unknown"

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
            if resolve(self.bundle, _holding_slot(setup, ref), ref):
                name = "the " + self.short_reference(ref, _holding_slot(setup, ref))
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

        # Each rest is the item its reference selects, however the kernel entry or the
        # support spells it; the support's own spelling prints.
        def rest_key(reference):
            return identity(self.bundle, reference, "fixtures")

        engagements = {}
        for entry in map(_mapping, numbers.get("rest_engagement") or []):
            if _known(entry.get("declared_z_mm")):
                engagements.setdefault(rest_key(entry.get("rest")), (entry.get("rest"), entry))
        # The op's own follow-rest entries (a steady rest stands at ``at_z_mm``): one rest
        # may ride a different side in another op.
        applicable = [
            support
            for support in map(_mapping, supports if isinstance(supports, list) else [])
            if "at_z_mm" not in support
            and (
                {"jaw_lead_mm", "jaw_side", "engage_at_z_mm"} & support.keys()
                or rest_key(support.get("ref")) in engagements
            )
            and (not isinstance(support.get("ops"), list) or op.get("op") in support["ops"])
        ]
        rests = [(support.get("ref"), support) for support in applicable]
        named = {rest_key(rest) for rest, _ in rests}
        rests += [(rest, {}) for key, (rest, _) in engagements.items() if key not in named]
        cells, lines = [], []
        for rest, support in rests:
            side = support.get("jaw_side", "turned")
            lead = support.get("jaw_lead_mm") if support else None
            ridden = "uncut stock ahead of the tool" if side == "uncut" else "diameter just turned"
            entry = engagements.get(rest_key(rest), (None, None))[1]
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
            if gap is not None and not _known(gap):
                boxes.append(
                    _Box(f"JAWS Z {o(jaw)}: tool clearance not computed — hand feed to a stop")
                )
            elif gap is not None and gap < 0:
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
            hand = op.get("do") in HAND_FINISH
            check = "keep the file clear of it" if hand else "hand feed past it"
            boxes.append(_Box(f"{cut[1].upper()} {o(cut[0])} mm FROM THE CUT — {check}"))
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
        """``(mm, name)``: how near ``op`` comes to the holding, from the kernel's setup
        picture (its ``cut_clearances``: a machine op's whole tool, cutter to holder, over
        its commanded sweep, a bench file's removal; the picture dimensions the least of the
        setup's), and the holding solid it is, as the HOLD names it (:meth:`holding_name`);
        ``unknown`` where the kernel could not derive the tool, its sweep or the cut, or the
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
        reading = f"{_declared(limit)} mm total indicator reading"
        slot = "spindle" if "tool" in transfer else "gauges"
        with_gauge = (
            " with the " + self.reference(gauge, slot) if gauge not in (None, "unknown") else ""
        )
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
            pieces.append(_p(self.transfer_line(setup, transfer) + ".", "zero-transfer"))
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
        measurements = []
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
            zero_surface = None
            method = touch.get("method")
            indicate = method == "indicate_axis" or touch.get("from") == "indicated"
            tool = None
            if "tool" in touch:
                tool = (
                    "? tool not chosen"
                    if touch["tool"] in (None, "unknown")
                    else self.touched_tool(touch["tool"], tools, "spindle")
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
            if "holder" in touch and self.setup_tool(tools, touch.get("tool"), "spindle") is None:
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
                shown_surface = f"surface at {o(edge)}"
                start = len("; ".join(contact)) + 2
                if isinstance(target, str) and target not in ("", "unknown"):
                    zero_surface = (axis, target, start, start + len(shown_surface))
                contact.append(shown_surface)
            radius = touch.get("radius_mm")
            if _known(radius) and radius and touch.get("from") != "indicated":
                contact.append(f"edge-finder radius {o(radius)}")
            if computed.get("finder"):
                contact.append(
                    "speed, kick-out and offset: " + self.finder_pointer(setup, touch.get("tool"))
                )
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
            if method == "measure_then_set" and setup.get("id") not in (None, "", "unknown"):
                owner = f"{setup['id']} {axis.upper()} M"
                if before_hold:
                    contact.append(f"{owner}: use the {axis.upper()} M field in HOLD")
                else:
                    unit = f" ({self.units})" if self.units in ("mm", "in") else ""
                    measurements.append(
                        '<p class="setup-measurement">' + _writing_field(owner + unit) + "</p>"
                    )
            expected = self.reading(readings["check_reading"], computed.get("check_expression"))
            mirrored = self.reading(
                readings["mirrored_reading"], computed.get("mirrored_expression")
            )
            jog = computed.get("jog_mm")
            jog_direction = "−" if _known(jog) and jog < 0 else "+"
            row = _Row(
                (
                    axis.upper(),
                    "; ".join(contact),
                    self.reading(readings["axis_set"]),
                    f"{jog_direction}{axis.upper()} {o(abs(jog)) if _known(jog) else '?'}",
                    expected,
                    mirrored,
                )
            )
            row.zero_surface = zero_surface
            rows.append(row)
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
                css="zero",
                widths=[9, 38, 13, 14, 13, 13],
            )
        )
        pieces.extend(measurements)
        if not lathe and any(row[0] in ("X", "Y") for row in rows):
            # From a side pickup, +X / +Y runs the finder over the work at pickup height.
            # Its line leads in the steps: the pagination keeps it with them.
            pieces.append(
                _p("X and Y check jog, after each Axis Set:", "lead-in")
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
        machine, printed = setup.get("machine"), set()
        for axis in ("x", "y"):
            finder = _mapping(axes.get(axis)).get("finder")
            reference = _mapping(authored.get(axis)).get("tool")
            key = self.finder_key(reference, machine)
            if finder and key not in printed and self.finder_homes.get(key) == setup["id"]:
                printed.add(key)
                pieces.append(self.finder_box(reference, machine, finder))
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
                name = self.touched_tool(incoming, tools, "tools")
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
                # The op rows carry each op's T number and the TOOLS table names it: the
                # paragraph says where the changes fall, not the tools a second time.
                served = [s for _, _, s in changes]
                listed = ", ".join(served[:-1]) + " and " + served[-1]
                pieces.append(
                    _p(
                        f"Tool changes before ops {listed}: install the op's tool (the T number "
                        f"in its row), then {touch}"
                    )
                )
        for kind in ("tool_touches", "derived_touches"):
            for index, touch in enumerate(numbers.get(kind, [])):
                if (kind, index) in settings_at:
                    pieces.append(_p(self.tool_setting(settings_at[(kind, index)], tools)))
                slot = "spindle" if kind == "tool_touches" else "tools"
                pieces.append(_p(self.tool_touch(setup, touch, tools, slot)))
        for gap in numbers.get("missing_touches", []):
            name = self.touched_tool(gap.get("tool"), tools, "tools")
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

    @functools.cached_property
    def finder_homes(self):
        """``{(edge finder, machine): setup id}`` (:meth:`finder_key`): the first setup whose
        DRO zero picks up with that finder on that mill prints its EDGE FINDER box. The
        speed is the mill's, so each mill the finder is used on gets its own box."""
        homes = {}
        for setup in self.plan.get("setups", []):
            axes = _mapping(self.records.get(("zero_check", setup["id"]))).get("axes")
            zero = _mapping(setup.get("zero"))
            for axis in ("x", "y"):
                if _mapping(_mapping(axes).get(axis)).get("finder"):
                    key = self.finder_key(
                        _mapping(zero.get(axis)).get("tool"), setup.get("machine")
                    )
                    homes.setdefault(key, setup["id"])
        return homes

    def finder_key(self, reference, machine):
        """The edge finder and mill a pick-up names, as the items they select
        (:func:`identity`): ``finder`` and ``tools.finder`` are one finder."""
        return (
            identity(self.bundle, reference, "spindle"),
            identity(self.bundle, machine, "machines"),
        )

    def finder_pointer(self, setup, reference):
        """``EDGE FINDER box`` with the sheet that prints it when another setup's does."""
        key = self.finder_key(reference, setup.get("machine"))
        home = self.finder_homes.get(key, setup["id"])
        return "EDGE FINDER box" + ("" if home == setup["id"] else f", Setup {home} sheet 1")

    def finder_box(self, reference, machine, finder):
        """The one edge-finding procedure every X/Y pick-up with ``reference`` on
        ``machine`` follows: the speed it runs at on that mill, how its contact shows and
        how half its tip Ø is applied by the side it comes from
        (``zero_recipe.finder_procedure`` facts)."""
        o = self.operative
        kind = finder.get("finder_type")
        lines = []
        names = {"finder_type": "type", "tip_in / tip_mm": "tip Ø", "rpm_range": "rpm range"}
        missing = [names.get(name, name) for name in finder.get("missing") or []]
        if missing:
            lines.append(
                _p(
                    f"STOP: the shop list gives no {' or '.join(missing)} for this finder — "
                    "its speed, contact and offset are not known. Do not pick up with it.",
                    "stop",
                )
            )

        def bands(value):
            return " or ".join("–".join(_number(v) for v in pair) for pair in value)

        rpm, band, spindle = finder.get("rpm"), finder.get("finder_rpm_range"), None
        if isinstance(finder.get("machine_rpm"), list):
            spindle = bands(finder["machine_rpm"])
        if kind == "electronic":
            lines.append(_p("Speed: spindle stopped — the finder does not turn."))
        elif finder.get("status") == "error":
            lines.append(
                _p(
                    f"STOP: the finder's {bands([band])} rpm lies outside the mill's "
                    f"{spindle} rpm.",
                    "stop",
                )
            )
        elif isinstance(rpm, list) and rpm:
            lines.append(
                _p(
                    f"Speed: {bands(rpm)} rpm, where a spindle range turns it (finder "
                    f"{bands([band])} rpm; mill {spindle} rpm). Never a speed between the "
                    "mill's ranges."
                    if len(rpm) > 1
                    else f"Speed: {bands(rpm)} rpm, in the spindle range that covers it "
                    f"(finder {bands([band])} rpm; mill {spindle} rpm)."
                )
            )
        elif "rpm range" not in missing:
            lines.append(
                _p("STOP: the finder's or the mill's rpm range is not known — no speed.", "stop")
            )
        if kind == "mechanical":
            lines.append(
                _p(
                    "Kick-out: spindle stopped, push the tip a little off centre by hand. Run "
                    "the spindle: the tip wobbles. Feed toward the edge by handwheel, in the "
                    "smallest steps once close: the tip touches and runs true with the body, "
                    "and at the next small step it kicks sharply sideways. Stop at the kick. "
                    "Back off, re-approach in the smallest steps and stop at the first kick "
                    "again: that position is the pick-up."
                )
            )
        elif kind == "electronic":
            lines.append(
                _p(
                    "Contact: the finder's light comes on the moment the tip touches the "
                    "work. Feed in the smallest steps once close and stop at the first light; "
                    "back off and re-approach once: that position is the pick-up."
                )
            )
        tip, radius = finder.get("tip_dia_mm"), finder.get("radius_mm")
        if _known(radius):
            lines.append(
                _p(
                    f"Offset: at the pick-up the spindle axis is half the tip Ø ({o(tip)}) off "
                    f"the edge, r = {o(radius)}. Coming from the − side (moving + onto the "
                    f"edge): Axis Set edge − {o(radius)}. Coming from the + side: Axis Set edge "
                    f"+ {o(radius)}. Each DRO ZERO row prints its signed Axis Set."
                )
            )
        cite = finder.get("cite")
        cites = [cite] if isinstance(cite, str) and cite != "unknown" else cite
        if isinstance(cites, list) and cites:
            lines.append(_p("Finder data: " + "; ".join(str(c) for c in cites) + "."))
        title = f"EDGE FINDER — {self.reference(reference, 'spindle')}"
        finder_item = identity(self.bundle, reference, "spindle")
        if sum(key[0] == finder_item for key in self.finder_homes) > 1:
            title += f" on {self.reference(machine, 'machines')}"
        return f'<div class="keep"><h3>{escape(title)}</h3>{"".join(lines)}</div>'

    @functools.cached_property
    def receipt_homes(self):
        """``{(category, bought item reference): setup id}``: the first setup using an item
        with receipt checks prints its PURCHASED TOOLING / RECEIPT CHECK table. A
        ``fixtures.pins`` and a ``gauges.pins`` are two items, each with its own table."""
        homes = {}
        for setup in self.plan.get("setups", []):
            numbers = _mapping(self.records.get(("purchased_tooling", setup["id"])))
            for item in numbers.get("items", []):
                homes.setdefault((item.get("category"), item["ref"]), setup["id"])
        return homes

    def purchased_tooling(self, setup):
        """Each bought-finished item the setup uses that carries receipt checks: its
        table where first used, a pointer to that table after."""
        numbers = _mapping(self.records.get(("purchased_tooling", setup["id"])))
        html = []
        for item in numbers.get("items", []):
            identity = (item.get("category"), item["ref"])
            name = self.reference(item["ref"], item.get("category"))
            home = self.receipt_homes.get(identity, setup["id"])
            if home != setup["id"]:
                html.append(
                    _p(
                        f"{name}: bought finished, accepted on receipt — PURCHASED TOOLING / "
                        f"RECEIPT CHECK table, Setup {home} sheet 1."
                    )
                )
                continue
            rows = []
            for check in item["checks"]:
                gauge = check["gauge"]
                tool = "by hand / eye" if gauge == "none" else self.short_reference(gauge, "gauges")
                if _stated(check["how"]) and check["how"] != "not_applicable":
                    tool += f"; {check['how']}"
                accept = []
                limits, most = check.get("limits_mm"), check.get("max_mm")
                # Limits print rounded inward (the low limit up, the high one down), in mm
                # and, for an inch gauge, in inches: never looser than declared, and never
                # reversed or rounded to nothing (`_inward` keeps the decimals that needs).
                reads = _mapping(resolve(self.bundle, "gauges", gauge))
                inch = any(key.endswith("_in") for key in reads)
                if isinstance(limits, list) and all(_known(v) for v in limits):
                    text = "{}–{} mm".format(*_inward(*limits))
                    inches = _inward(*limits, "in") if inch else None
                    accept.append(text + (" ({}–{} in)".format(*inches) if inches else ""))
                elif _known(most):
                    inches = _inward(0, most, "in") if inch else None
                    text = f"≤ {_inward(0, most)[1]} mm"
                    accept.append(text + (f" (≤ {inches[1]} in)" if inches else ""))
                if _stated(check["accept"]) and check["accept"] != "not_applicable":
                    accept.append(check["accept"])
                if check["status"] != "pass":
                    accept.append(f"STOP: {check['reason']}")
                rows.append([check["check"], tool, "; ".join(accept)])
            purchase = item.get("purchase")
            stops = item.get("stops") or []
            html.append(
                f'<div class="keep"><h3>PURCHASED TOOLING / RECEIPT CHECK — {escape(name)}</h3>'
                + "".join(
                    _p(f"STOP: {stop} — do not use it until the shop list states it.", "stop")
                    for stop in stops
                )
                + (_p(f"Bought finished: {purchase}.") if _stated(purchase) else "")
                + _p("Check on receipt, before first use; return the item if any check fails.")
                + (_table(["check", "gauge", "accept"], rows, widths=[30, 35, 35]) if rows else "")
                + "</div>"
            )
        return "".join(html)

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

    def touched_tool(self, reference, tools, slot):
        """A touched-off tool's name: the setup's own name for it (``tools``), else the
        shop name of the item ``slot`` selects (a zero's or tool touch's tool is a spindle
        slot, an op's a tool; never a same-key item of another category)."""
        return self.setup_tool(tools, reference, slot) or self.short_reference(reference, slot)

    def tool_setting(self, record, tools):
        """The step that sets a toolpost tool before its first touch-off (zero_check
        ``tool_setting``): on centre height, and a blade squared to the spindle axis."""
        name = self.touched_tool(record.get("tool"), tools, "tools")
        text = f"Before touching off {name}: {self.bench(record.get('centre_height'))}"
        square = record.get("square_blade")
        if square not in (None, "not_applicable"):
            text += f"; then {self.bench(square)}"
        return text + "."

    def tool_touch(self, setup, touch, tools, slot):
        reference = touch.get("tool")
        name = self.touched_tool(reference, tools, slot)
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
            how = (_METHODS.get(words) or self.bench(words)) if words else None
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
                # A face square to setup Z is located only by its centre: no X / Y the DRO
                # stops at, and its Z is the op row's. Its row stays only to carry an aim.
                aim = self.aim_note(record)
                definition = _mapping(self.features.get(feature))
                square = "face" in str(definition.get("kind", "")) and self.along_setup_z(
                    setup, definition
                )
                if square and not aim:
                    continue
                grouped.setdefault((feature, tuple(coordinates)), {})
                aims.append(aim)
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
            headings = ["feature", "drawing Ø limits", heading, "cut from Z", "cut to Z"]
            widths = [32, 17, 17, 17, 17]
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
            headings = ["feature", "reference point", "X", "Y", "Z"]
            widths = [26, 38, 12, 12, 12]
            note = "The op table gives the tool targets."
            note += "".join(f" {text}" for text in dict.fromkeys(filter(None, aims)))
        table = _table(headings, rows, css="feature-map", widths=widths, context=note)
        if lathe and prefix is None:
            table += _p(_X_DISPLAY_STOP + ".", "stop")
        return f"<h2>FEATURE MAP — {escape(self.zero_name(setup))}</h2>" + table

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

    def faced_aim_note(self, setup, op):
        """Each faced aim (plan ``aims`` naming a ``face``) once, at the last facing op that
        claims its face (:func:`~.rules.coordinates.faced_aim_claims`): the length it faces
        to, at no fewer places than the drawing's, the band that holds it and the aim's
        reason. Empty at any other op."""
        scale = {"mm": 1.0, "in": 25.4}.get(self.units)
        notes = []
        for name, aim in _mapping(self.plan.get("aims")).items():
            face = _mapping(aim).get("face")
            claims = faced_aim_claims(self.plan, name, face) if face is not None else []
            if not (scale and claims and claims[-1] is op):
                continue
            requirement = aim["requirement"]
            value, places = aim["value_mm"] / scale, self.precision(name, requirement)
            shown = _number(value)
            if isinstance(places, int) and len(shown.partition(".")[2]) < places:
                shown = _number(value, places)
            band = _mapping(self.bundle.feature_definitions.get(name)).get(requirement, "unknown")
            reason = self.bench(aim["reason"], setup).rstrip(".")
            notes.append(
                f"{self.feature_name(name).capitalize()} "
                f"{_REQUIREMENT_NAMES.get(requirement, requirement)} faced to {shown} "
                f"(band {self.band(band, name, requirement)}): {reason}."
            )
        return " ".join(notes) or None

    # ------------------------------------------------------------------ tools
    def tool_pair(self, tool, holder):
        """A tool + holder pair as the items they select (:func:`identity`): ``tools.drill``
        and ``drill`` are one drill, ``holders.er20`` and ``er20`` one collet chuck. The
        key of a setup's T-numbers."""
        return identity(self.bundle, tool, "tools"), identity(self.bundle, holder, "holders")

    def setup_tool(self, tools, reference, slot="tools"):
        """The setup's name for the tool ``reference`` selects in ``slot`` (a zero's or tool
        touch's tool is a spindle slot), from ``tools`` keyed by :func:`identity`; else None."""
        return tools.get(identity(self.bundle, reference, slot))

    def tool_table(self, setup):
        """T-numbers as :func:`tool_numbers` numbers them (the one numbering free text is
        checked against), one per tool + holder pair (:meth:`tool_pair`). Returns the numbers
        by pair, the setup's names by tool (:func:`identity`) and the TOOLS table."""
        numbers = tool_numbers(self.bundle, setup)
        rows, by_tool = {}, {}
        for op in setup.get("ops", []):
            reference = op.get("tool")
            if op.get("do") in MANUAL or reference in (None, "unknown"):
                continue
            holder = op.get("holder")
            pair = self.tool_pair(reference, holder)
            if pair not in rows:
                by_tool.setdefault(pair[0], f"{numbers[pair]} {self.tool_name(reference)}")
                rows[pair] = [
                    numbers[pair],
                    self.tool_name(reference),
                    ", ".join(self.tool_detail(reference, holder)) or "—",
                    self.short_reference(holder, "holders")
                    if holder not in (None, "unknown", "not_applicable")
                    else "—",
                    [],
                ]
            rows[pair][4].append(str(op["op"]))
        rows = sorted(rows.values(), key=lambda row: int(row[0][1:]))
        html = ""
        if rows:
            html = "<h2>TOOLS FOR THIS SETUP — pull before starting</h2>" + _table(
                ["T", "tool", "insert / size / material", "holder / station", "ops"],
                [(t, n, d, h, ", ".join(ops)) for t, n, d, h, ops in rows],
                widths=[9, 21, 33, 25, 12],
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
        down in: ``Z start → depth in N levels of doc max``; levels coordinates established
        as one pass starting at the depth (an earlier op left the floor there) print as
        that pass, ``Z → depth``, while levels it could not establish keep their ``?``. A
        grooving/parting blade's target is the DRO reading of the corner its Z touch set
        (coordinates ``blade``), named."""
        o = self.operative
        levels = self.z_levels(setup, op)
        if levels is not None:
            start, end = levels.get("dro_start_z"), levels.get("dro_to_z")
            one_pass = isinstance(levels.get("levels"), list) and levels.get("count") == 1
            if one_pass and _known(start) and _known(end) and start == end:
                return f"Z → {o(end)}"
            count = levels.get("count")
            return (
                f"Z {o(start)} → {o(end)} in "
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
            return f"allowed {_declared(low)} to {_declared(high)}"
        corner = _CORNERS.get(blade.get("reading_corner"))
        band = blade.get("corner_dro_band")
        if corner is None or not isinstance(band, list):
            return "allowed ? (blade corner not set)"
        o = self.operative
        return f"allowed {o(band[0])} to {o(band[1])} ({corner} corner)"

    def relief_plunges(self, setup, op):
        """A blade groove's plunges (coordinates ``plunges``): the reading corner's Z for
        each, the diameter every plunge stops at and the groove they leave. The diameter's
        drawing band prints here only when the op's inspection cell does not carry it, and
        the groove only when it is not the op's own Z window the row already prints."""
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
        if isinstance(band, list) and scale and "dia" not in _mapping(op.get("checks")):
            size += f" ({self.band([v / scale for v in band], feature, 'dia')})"
        parts.append(("each to " if len(corners) > 1 else "to ") + size)
        low, high = plunges.get("groove_z_mm", [None, None])
        groove = sorted([o(low), o(high)])
        window = [self.op_z(setup, op, key) for key in ("z_from", "z_to")]
        if not all(map(_known, window)) or sorted(map(self.operative, window)) != groove:
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
            return _Note(f"{head}: {self.steps(procedure)}", head + ":")
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
                    "?"
                    if not bands
                    else bands[0]
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
            elif pair and owners:
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
            recording_at = ""
            if method and method != "unknown":
                head = f"{sid} op {op['op']} {name}"
                item = self.note(head, method)
                sketch = self.inspection_sketch(setup, op, requirement)
                if sketch:
                    item.sketch = sketch
                destination = place(item)
                line += f" [{destination}]"
                has_fields = (
                    any(_FIELD.search(step) for step in item[1])
                    or any(_FIELD.search(step) for step in item[2])
                    if isinstance(item, _Steps)
                    else _FIELD.search(str(item))
                )
                if has_fields:
                    recording_at = destination
            if requirement in missing or requirement == "unknown" or not owners:
                rows.append(line)
                continue
            # Equal bands retain the original read-once grouping. Distinct authored
            # bands get distinct result associations, without copying method obligations.
            groups = (
                [(owners, target)]
                if len(set(bands)) == 1
                else [([feature], band) for feature, band in zip(owners, bands, strict=True)]
            )
            for group, band in groups:
                values = [self.features.get(feature, {}).get(requirement) for feature in group]
                known = all(
                    value is not None
                    and value != []
                    and all(
                        _known(item)
                        or isinstance(item, str)
                        and item.strip() not in ("", "unknown")
                        for item in (value if isinstance(value, (list, tuple)) else [value])
                    )
                    for value in values
                )
                text = ", ".join(self.feature_name(feature) for feature in group)
                text += " — " + line.replace(target, band, 1)
                if not known:
                    rows.append(text)
                    continue
                unit = ""
                if requirement.endswith("_deg"):
                    unit = "°"
                elif requirement in TOLERANCE_REQUIREMENTS - {"finish_ra", "land_angle_deg"}:
                    unit = self.units if self.units in ("mm", "in") else ""
                rows.append(
                    _Inspection(
                        text,
                        tuple(group),
                        requirement,
                        unit,
                        qualitative=bool(pair)
                        and pair != "unknown"
                        or any(isinstance(value, str) for value in values),
                        # A method owns only its exact read-once requirement group;
                        # unrelated or separately banded results keep their own box.
                        recording_at=recording_at if len(groups) == 1 else "",
                    )
                )
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
        """One indivisible original-PNG window per complete authored inspection view."""
        if requirement not in _mapping(op.get("inspection_views")):
            return ""
        render = _mapping(self.report.get("renders", {}).get(setup["id"]))
        sketch = _mapping(render.get("inspections")).get(f"{op['op']}:{requirement}")
        if not sketch:
            return _p("NOT SHOWN: the set-up sketches for this check could not be drawn.")
        scene = _mapping(sketch.get("scene"))
        width, height = scene.get("width_px"), scene.get("height_px")
        panels = scene.get("print_panels")
        identity = f"Setup {setup['id']} op {op['op']} {requirement}"
        if (
            width != 1600
            or type(width) is not int
            or type(height) is not int
            or height <= 0
            or not isinstance(panels, list)
            or not panels
        ):
            raise ValueError(f"{identity} has no complete printable inspection geometry")
        path = escape(sketch["path"], quote=True)
        result, next_top = [], 0
        for ordinal, panel in enumerate(panels, start=1):
            panel = _mapping(panel)
            top, panel_height = panel.get("top_px"), panel.get("height_px")
            label = panel.get("label")
            if type(panel_height) is int and panel_height > 1792:
                raise ValueError(
                    f"{identity} inspection view {ordinal} is {panel_height}px high; "
                    "a complete view must fit within 1792px"
                )
            if (
                panel.get("role") != "inspection"
                or type(panel.get("view_ordinal")) is not int
                or panel["view_ordinal"] != ordinal
                or not isinstance(label, str)
                or not label.strip()
                or type(top) is not int
                or top != next_top
                or type(panel_height) is not int
                or not 0 < panel_height <= 1792
                or top + panel_height > height
            ):
                raise ValueError(f"{identity} inspection panels omit or repeat complete views")
            next_top += panel_height
            caption = f"{identity} · view {ordinal} of {len(panels)} — {label}"
            result.append(
                f'<figure class="fixture-render inspection-sketch" data-panel="{ordinal}" '
                f'data-panel-role="inspection" data-view-ordinal="{ordinal}" '
                f'data-panel-top="{top}" data-panel-height="{panel_height}">'
                f"<figcaption>{escape(caption)}</figcaption>"
                f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 {top} {width} {panel_height}" '
                f'width="{width}" height="{panel_height}" role="img" '
                f'aria-label="{escape(caption)}">'
                f"<title>{escape(caption)}</title>"
                f'<image href="{path}" x="0" y="0" width="{width}" height="{height}" '
                'preserveAspectRatio="none"></image></svg></figure>'
            )
        if next_top != height:
            raise ValueError(f"{identity} inspection panels omit image content")
        return "".join(result)

    def process_hold(self, hold):
        """A shop limit inside the drawing band, printed apart from the drawing's own; a hold
        on a reference-only span also names the REF it sets, since the drawing has no limit.
        Why it holds prints once, in the job page's PROCESS HOLDS table this row points to."""
        reading, gauge, drawing, reference = self.process_hold_parts(hold)
        return (
            f"PROCESS HOLD — not a drawing limit (why: see job page): {reading}"
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
        rows, inspection_notes, worksheets, stops = [], [], [], {}
        where = {kind: f"{setup['id']} sheet {number}" for kind, number in sheets.items() if number}
        saw_table = any(op.get("do") in SAW_OPS for op in ops)
        finishing = bool(ops) and all(op.get("do") in MANUAL for op in ops)
        lathe = self.lathe(setup)
        # Each lathe op that runs the spindle turns it one way (:meth:`spindle_turn`). When
        # every one turns it the same known way, the heading says so once and the narrow
        # rpm cells carry the rpm alone; else each cell names its own turn.
        spins = {
            str(op["op"]): self.spindle_turn(op)
            for op in ops
            if lathe and op.get("do") not in MANUAL | SAW_OPS
        }
        turns = [turn for turn in _SPINDLE_TURNS if turn in spins.values()]
        one_way = len(turns) == 1 and all(not isinstance(t, _Box) for t in spins.values())
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
                number = tool_numbers.get(self.tool_pair(reference, op.get("holder")))
                # The TOOLS table above names the tool; the op row carries its T number.
                tool = number or self.tool_name(reference)
                if resolve(self.bundle, "tools", reference) is None:
                    tool = [tool, _Box("STOP: tool not in the shop list")]
                    stops.setdefault("tool not in the shop list", []).append(str(op["op"]))
            speed, feed, missing = self.speeds(setup, op, saw_table)
            if missing:
                stops.setdefault("no starting speed / feed", []).append(str(op["op"]))
            turn = spins.get(str(op["op"]))
            if isinstance(turn, _Box):
                speed = [speed, turn]
                stops.setdefault("spindle direction not known", []).append(str(op["op"]))
            elif turn is not None and not one_way:
                speed = [speed, turn]
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
                        self.faced_aim_note(setup, op),
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
                rows.append(
                    _Row(
                        (*cells, inspection), boxes, optional_observations=op.get("do") == "coating"
                    )
                )
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
                    optional_observations=op.get("do") == "coating",
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
            if turns and not one_way:
                # An rpm cell naming its turn: the column fits the word on one line.
                widths = [4, 16, 12, 7, 9, 9, 11, 9, 23]
        # A long table runs onto the back of the front sheet; the repeated heading row
        # names it there, and on the front the section heading is drawn over it.
        # The heading says once what each turn word means (a line of its own would part the
        # heading from its table); one turn for every op is said there alone. A lathe op
        # measured in the chuck is measured stopped: said there once too.
        if one_way:
            keys = [f"spindle {turns[0]} whenever it runs: {_SPINDLE_TURNS[turns[0]]}"]
        else:
            keys = [f"spindle {turn}: {_SPINDLE_TURNS[turn]}" for turn in turns]
        ops_checked = (_mapping(op.get("checks")) or op.get("process_holds") for op in ops)
        if lathe and not finishing and any(ops_checked):
            keys.append("measure only with the spindle stopped and the tool withdrawn")
        key = "; ".join(keys)
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
            return _p(
                ((text[:1].upper() + text[1:]) if raster else "Enter at " + text) + ".",
                "contour-context",
            )
        first = where(downs[0])
        if raster:
            after = f"lift to Z {o(raised)}{above}, rapid back to pass 1"
        elif record.get("closed") is True:
            after = f"stay at {first}: the path ends where it starts"
        else:
            after = f"raise to Z {o(raised)}{above}, move back to {first}"
        return _p(
            f"{len(depths)} depth levels, top first, at the Zs in the heading: run the whole "
            f"path below at each. Get down {text}. Between levels, {after}.",
            "contour-context",
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
                centre = record.get("radius_mm", 0.0) + compensation * trig.cos(normal)
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
            tool = self.setup_tool(tools, op.get("tool"))
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
            title_owner = f"contour:{op_id}"
            content = (
                '<h3 class="page-context">'
                f'<span data-title-source="{escape(title_owner)}">{_numeric_html(title)}</span>'
                "</h3>"
            )
            note = self.level_entries(setup, op, waypoints) if op else ""
            if note:
                content += note
            elif stepped:
                # The heading lists the levels; the note says how to run them, once per op.
                content += _p(
                    f"{len(depths)} depth levels: run the complete path below at each Z in the "
                    "heading, in order, top level first.",
                    "contour-context",
                )
            elif levels and levels.get("count") == "unknown":
                content += _p(
                    "? Depth levels not computed — " + _text(levels.get("reason")) + ".",
                    "contour-context",
                )
            if stepped and entry["parts"]:
                # The whole path runs once per level: a box to tick as each level is done.
                content += _levels(len(depths))
            progress = (
                stepped
                and all(_known(z) for z in depths)
                and setup.get("id") not in (None, "", "unknown")
                and op.get("op") not in (None, "", "unknown")
                and op.get("tool") not in (None, "unknown")
                and bool(tool)
                and any(
                    not isinstance(description, list) and headings[:1] == ["P"] and rows
                    for _, description, headings, rows, _ in entry["parts"]
                )
            )
            progress_owner = f"{setup['id']} op {op_id} progress beside Done"
            if progress:
                content += (
                    '<p class="path-progress">'
                    + _numeric_html(
                        f"{setup['id']} op {op_id} — Optional progress only; "
                        "not level Done, inspection acceptance or clearance to resume: "
                    )
                    + _writing_field(f"{setup['id']} op {op_id} level")
                    + " "
                    + _writing_field(f"{setup['id']} op {op_id} last completed #")
                    + "</p>"
                )
            tool_missing = op.get("tool") in (None, "unknown") or not tool
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
                        + _table(
                            shown,
                            cells,
                            css="coords",
                            repeat=title,
                            repeat_owner=title_owner,
                            repeat_locator=(
                                f"Optional progress only: see {progress_owner}"
                                if progress
                                else None
                            ),
                            context=self.bench(description) + ".",
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
            html.append(f'<div class="{css}" data-page-context="{escape(title)}">{content}</div>')
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
        """Complete semantic windows of the canonical picture, with context and debts."""
        render = self.report.get("renders", {}).get(setup["id"])
        if not render:
            return ""
        scene = _mapping(render.get("scene"))
        fixture = self.reference(_mapping(setup.get("hold")).get("fixture"), "workholding")
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
        width, height = scene["width_px"], scene["height_px"]
        panels = scene["print_panels"]
        if not panels or not all(type(value) is int and value > 0 for value in (width, height)):
            raise ValueError(f"Setup {setup['id']} has no complete printable image geometry")
        path = escape(render["path"], quote=True)
        part = _text(self.plan.get("part"))
        revision = self.drawing_revision()
        context = f"{part} · Setup {setup['id']}" + (f" · rev {revision}" if revision else "")
        result = []
        next_top = 0
        for index, panel in enumerate(panels, start=1):
            top, panel_height = panel["top_px"], panel["height_px"]
            if (
                type(top) is not int
                or type(panel_height) is not int
                or top != next_top
                or panel_height <= 0
                or top + panel_height > height
            ):
                raise ValueError(
                    f"Setup {setup['id']} printable panels omit or repeat image content"
                )
            next_top += panel_height
            label = (
                f"{context} · {panel['role'].replace('_', ' ')} · panel {index} of {len(panels)}"
                f" — {panel['label']}"
            )
            stock_caption = _p(" ".join(caption)) if index == 1 else ""
            result.append(
                f'<figure class="fixture-render" data-panel="{index}" '
                f'data-panel-role="{escape(panel["role"])}" data-panel-top="{top}" '
                f'data-panel-height="{panel_height}">'
                f"<figcaption>{stock_caption}{escape(label)}</figcaption>"
                f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 {top} {width} {panel_height}" '
                f'width="{width}" height="{panel_height}" role="img" aria-label="{escape(label)}">'
                f"<title>{escape(label)}</title>"
                f'<image href="{path}" x="0" y="0" width="{width}" height="{height}" '
                'preserveAspectRatio="none"></image></svg></figure>'
            )
        if next_top != height:
            raise ValueError(f"Setup {setup['id']} printable panels omit image content")
        result.extend(_p(line, "render-debt") for line in lines)
        return "".join(result)

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
            parts.append(_numeric_html(f"held on Ø{o(state['od_mm'])}"))
        # Each arriving surface as the DRO shows it, as every other line prints it; the Zs
        # carried over from the setup it arrives from, and that one transform.
        arrival = arrival_zs(self.bundle, setup)
        move = transfer(self.bundle, setup)
        carried = move["carried"] if move else {}
        stated, derived, derived_keys = [], [], []
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
            name = label
            if key == "top_z" and state.get("top_feature"):
                name = f"top ({self.feature_name(state['top_feature'])})"
            stated.append(label)
            printed = arrival[key][1] if key in arrival else state[key]
            if key in carried and printed == carried[key][1]:
                derived.append(label)
                derived_keys.append(key)
            surface = f"{name} at Z {o(printed)}" if _known(printed) else f"{name} Z ? not set"
            parts.append(
                f'<span data-stock-surface="{key}" '
                f'data-stock-state="{"known" if _known(printed) else "unknown"}">'
                + _numeric_html(surface)
                + "</span>"
            )
        line = _numeric_html(self.flip(setup) + f"Starts from: {self.arrival(setup)}")
        if parts:
            line += " — " + ", ".join(parts)
        grid = dro_grid(self.bundle, setup)
        if derived and (
            abs(move["shift"] - move["offset"]) > SAME_Z
            or any(z != dro_z(exact, grid) for exact, z in carried.values())
        ):
            # The transfer rounded its offset, or carried the sheet before's rounding: show
            # the one transform every carried Z took, at every place it holds.
            who = "each Z" if derived == stated else " and ".join(derived) + " Z"
            before = _numeric_html(f"its Setup {move['before']['id']} Z")
            shift = o(abs(move["shift"]), max(self.decimals, _places(abs(move["shift"]))))
            if move["sign"] < 0:
                # A flip: the shift first, so no reader takes the minus as covering it.
                shown_shift = ("−" if move["shift"] < 0 else "") + shift
                term = f"<span data-transfer-shift>{_numeric_html(shown_shift)}</span> − {before}"
            else:
                shown_shift = ("−" if move["shift"] < 0 else "+") + " " + shift
                term = f"{before} <span data-transfer-shift>{_numeric_html(shown_shift)}</span>"
            line += (
                f' <span data-transfer-state="linked" '
                f'data-transfer-before="{escape(str(move["before"]["id"]))}" '
                f'data-transfer-surfaces="{escape(json.dumps(derived_keys))}">'
                f"({_numeric_html(who)} = {term})</span>"
            )
        elif move and move["shift"] is None:
            # The Zs the sheet before printed are not whole steps of this DRO apart: say so,
            # rather than name a transform rounding each alone would break.
            refusal = (
                f"each Z on this DRO's {o(grid[0])} steps by itself: Setup "
                f"{move['before']['id']}'s Zs are not whole steps apart, so no one shift "
                "carries them"
            )
            line += (
                f' <span data-transfer-state="refused" '
                f'data-transfer-before="{escape(str(move["before"]["id"]))}">'
                f"({_numeric_html(refusal)})</span>"
            )
        line += "." + _numeric_html(self.joint_text(setup))
        if state.get("note"):
            line += " " + _numeric_html(self.bench(state["note"], setup).rstrip(".") + ".")
        debt = self.joint_debt(setup)
        return f'<p class="stock-state">{line}</p>' + (_p(debt, "stop") if debt else "")

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
        rows, joint_prep, same = [], [], {}
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
            limits = "; ".join(values) or "no toleranced requirement"
            # Two features on the same model faces with the same known limits (one dimension
            # exported twice) print as one row naming both.
            key = self.drawing_dimensions(definition, limits)
            if key in same:
                index = same[key]
                rows[index] = (f"{rows[index][0]} / {self.feature_name(feature)}", limits)
                continue
            if key is not None:
                same[key] = len(rows)
            rows.append((self.feature_name(feature), limits))
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

    @staticmethod
    def drawing_dimensions(definition, limits):
        """What proves a feature's requirement row is another feature's: the same model
        faces carrying the same printed limits, each requirement's band and the nominal it
        is drawn to known numbers (a maximum has no nominal; one stated must be known). None
        when the faces are not declared or a requirement, band or nominal is not known (an
        omitted nominal no more than an ``unknown`` one): a shared citation or equal numbers
        never show two features are one dimension, as one drawing sheet carries many alike."""
        faces = definition.get("faces")
        if not (isinstance(faces, list) and faces and all(map(_stated, faces))):
            return None
        key = [limits, tuple(sorted(set(faces)))]
        for requirement in dict.fromkeys(tolerance_requirements(definition)):
            band = definition.get(requirement)
            fields = (f"{requirement}_nominal", f"nominal_{requirement}")
            nominals = [definition[field] for field in fields if field in definition]
            pair = isinstance(band, list) and len(band) == 2 and all(map(_known, band))
            if requirement == "unknown" or not (pair or _known(band)):
                return None
            if not all(map(_known, nominals)) or (pair and not nominals):
                return None
            key.append((requirement, repr(band), repr(nominals)))
        return tuple(key) if len(key) > 2 else None

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
        limits = ([f"break sharp edges R{self.cap(radius)} max"] if _known(radius) else []) + (
            [f"chamfer {self.cap(chamfer)} max"] if _known(chamfer) else []
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
        text += f", not the drawing's {self.cap(min(drawing))}" if drawing else ""
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
        """Each routed machine's DRO step, once per machine however setups spell it: the
        grid every printed DRO target is on."""
        grids = {}
        for setup in setups:
            reference = setup.get("machine")
            key = identity(self.bundle, reference, "machines")
            if key in grids or saw_setup(setup) or manual_bench(self.bundle, setup):
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
            grids[key] = grid
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
                    else self.reference(s["hold"]["fixture"], "workholding"),
                )
                for s in setups
            ],
            widths=[12, 30, 25, 33],
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
            self.purchased_tooling(setup),
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
        signoff = (
            '<div class="signoff">'
            + _writing_field("Sign off")
            + "<p>First article: enter measured results in their labeled inspection fields "
            "or worksheets.</p>" + "</div>"
        )
        for label, blocks, signed in pages:
            # Continuation pages open with the sheet's name: "SETUP S2 — sheet 3".
            title = label.upper() if label == "job page" else label.replace(" sheet ", " — sheet ")
            result.append(
                f'<section class="page" data-sheet="{escape(label)}" data-title="{escape(title)}" '
                f'data-part="{escape(part)}" data-drawing="{escape(_text(drawing.get("number")))}" '
                f'data-revision="{escape(revision or "")}" '
                f'data-sheet-role="{"front" if signed else "continuation"}">'
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


def _holding_slot(setup, reference):
    """The slot a hold item is selected in (:func:`setup_items`): the hold's fixture is
    workholding, any other hold item a fixture."""
    fixture = _mapping(setup.get("hold")).get("fixture")
    return "workholding" if reference == fixture else "fixtures"


# The shop-name helpers read only the bundle's inventory (and its units for a blade
# width), so the render host can label tools without building a traveler.
def reference_label(bundle, reference, slot=None) -> str:
    """Shop name for an inventory reference; '(not in shop list)' when it does not resolve.
    The item is the one the rules read: the one :func:`select` selects for ``reference`` in
    ``slot`` (a slot kind or one category; a ``<category>.<key>`` reference names its own).
    An item, member or category stated unknown, or an item listed with nothing about it
    (``{}``), prints ``? <category>.<key>``; a same-key item in another category never
    names it."""
    if reference in (None, "unknown", "none", "not_applicable"):
        return _text(reference)
    if not isinstance(reference, str):
        return "?"
    category, key, selected = select(bundle, reference, slot)
    if selected == UNKNOWN:
        return f"? {category}.{key}"
    root, _, member = key.partition("/")
    raw = authored(bundle, category, key)
    item = resolve(bundle, slot, reference)
    record = item or raw
    # A member's display name is its own: a named kit does not name each of its pieces.
    own = _mapping(_mapping(raw.get("members")).get(member)) if member else {}
    named_member = bool(own.get("name") or own.get("label"))
    named = own if member else raw or record
    name = named.get("name", named.get("label"))
    if not name:
        if category == "machines":
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


def short_reference_label(bundle, reference, slot=None) -> str:
    """`reference_label` with the long tool words cut for table cells. An unknown item's
    ``? <category>.<key>`` is its inventory identity and is printed whole."""
    label = reference_label(bundle, reference, slot)
    if isinstance(reference, str) and select(bundle, reference, slot)[2] == UNKNOWN:
        return label
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
    member = select(bundle, reference, "tools")[1].partition("/")[2]
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
