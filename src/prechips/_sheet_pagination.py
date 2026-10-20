"""Measured pagination for the single continuous job traveler.

Integration contract: embed ``JOB_PRINT_JS`` once in the document head. Supply one
``section.page[data-sheet="job"]`` with human ``data-job-title`` and unchanged outer
``data-part``, ``data-drawing`` and ``data-revision``. Compact running titles identify
only the job; measured running ranges summarize retained physical source owners,
including whether the first owner continues from an earlier page. Local operation
context remains separate from that physical range. Setup/family
wrappers carry ``data-setup-title``; physical setup, member and workpiece owners
retain ``data-setup-id``, ``data-member`` and ``data-workpiece``. Nested inspection/
contour owners keep ``data-page-context`` and their direct ``.page-context`` heading.
Hoisted final-reference wrappers use ``data-page-reference="final-inspection"``;
their records retain ownership/local context but do not establish physical route ranges.
Original fields use ``.field``,
``.result-field`` or ``.authored-blank`` with ``.field-label/.writing-blank``.

CSS keeps the existing offline Arial/12pt working tokens, Letter/.5in margins,
``--page-content-width/height`` and ``--page-rounding``. Retain the measured table,
reading, figure, running-header and fixed-locator styles; their generated selectors
are ``data-job-print[-split|-stacked|-fragment]``. ``.cont-head`` starts a physical
page; setup wrappers do not force page breaks. ``.checkpoint-results`` is one
horizontal, break-inside-avoid row. Each direct ``.checkpoint-result`` contains a
labelled original blank with >=35mm interior width and >=20mm interior height.
Running totals reserve measured source-bound digit envelopes in every detail mode
before source fitting. Mixed containers with direct prose fragment as ordered
content; element-only worksheet and step containers retain child/table pagination.
No generated context owns a writing destination, diagram, or machining decision.
"""

JOB_PRINT_JS = r"""(() => {
  // The fewest original ordinary-table row groups on either side of a feasible break.
  const KEEP = 3;
  const ADDED = "data-job-print", SPLIT = "data-job-print-split",
    STACKED = "data-job-print-stacked";
  const CONTEXT_ROLE = "data-context-role";
  const JOB = 'section.page[data-sheet="job"]';
  const RESULTS = ".checkpoint-results";
  function physicalOwner(node) {
    const setup = node.closest("[data-setup-title]"),
      physical = node.closest("[data-setup-id]"),
      member = node.closest("[data-member]"), workpiece = node.closest("[data-workpiece]");
    const title = setup?.dataset.setupTitle || "", id = physical?.dataset.setupId || "",
      tokens = title.split(/[\s·:,()—]+/);
    const values = [title, ...[id, member?.dataset.member, workpiece?.dataset.workpiece]
      .filter((value) => value && !tokens.includes(value))].filter(Boolean);
    return { identity: [...new Set(values)].join(" · ") || "Job",
      setup: physical?.dataset.setupId || "", member: member?.dataset.member || "",
      workpiece: workpiece?.dataset.workpiece || "", title: setup?.dataset.setupTitle || "" };
  }
  const originals = new Map();
  let CAP;
  const heading = (el) => el && /^H[1-6]$/.test(el.tagName);
  function box(el) {
    const s = getComputedStyle(el);
    if (s.display === "contents") {
      const bounds = [...el.childNodes].flatMap((child) => {
        if (child.nodeType === Node.ELEMENT_NODE) {
          return getComputedStyle(child).display === "none" ? [] : [box(child)];
        }
        if (child.nodeType !== Node.TEXT_NODE || !child.textContent.trim()) return [];
        const range = document.createRange();
        range.selectNode(child);
        return [...range.getClientRects()].filter((rect) => rect.width && rect.height);
      });
      return bounds.length
        ? { top: Math.min(...bounds.map((r) => r.top)),
          bottom: Math.max(...bounds.map((r) => r.bottom)) }
        : { top: 0, bottom: 0 };
    }
    const r = el.getBoundingClientRect();
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
    const section = node.closest(JOB);
    if (!section) throw new Error("A recording destination has no logical sheet.");
    const start = locatorStarts(section).filter(
      (entry) => entry.node === section || entry.node === node
        || entry.node.compareDocumentPosition(node) & Node.DOCUMENT_POSITION_FOLLOWING
    ).at(-1);
    const bounds = section.getBoundingClientRect();
    return { sheet: section.dataset.sheet, ...physicalOwner(node),
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
  const TYPOGRAPHY = ["font-family", "font-size", "font-weight", "font-style",
    "font-stretch", "font-variant-numeric", "font-feature-settings",
    "font-variation-settings", "font-kerning", "font-optical-sizing",
    "letter-spacing", "word-spacing", "line-height"];
  function measureLocator(ref) {
    const slot = ref.querySelector(".fixed-locator-digit"), style = getComputedStyle(slot);
    const line = parseFloat(style.lineHeight);
    if (!Number.isFinite(line) || line <= 0) {
      throw new Error("A recording locator has no measured inherited line height.");
    }
    const probe = document.createElement("span");
    probe.style.cssText = "position:absolute;visibility:hidden;white-space:nowrap;"
      + "display:inline-block;left:0;top:0;padding:0;margin:0;border:0";
    for (const property of TYPOGRAPHY) {
      probe.style.setProperty(property, style.getPropertyValue(property));
    }
    document.body.append(probe);
    const range = document.createRange();
    let width, top = 0, bottom = line;
    try {
      for (let digit = 0; digit <= 9; digit++) {
        probe.textContent = String(digit).repeat(locatorPass.digits);
        const bounds = probe.getBoundingClientRect(), measured = bounds.width;
        if (!Number.isFinite(measured) || measured <= 0
            || !style.fontVariantNumeric.includes("tabular-nums")
            || (width !== undefined && measured !== width)) {
          throw new Error("A recording locator lacks measured tabular digit metrics.");
        }
        width = measured;
        range.selectNodeContents(probe);
        const glyph = range.getBoundingClientRect();
        if (!Number.isFinite(glyph.height) || glyph.height <= 0) {
          throw new Error("A recording locator has no measured digit glyph height.");
        }
        top = Math.min(top, glyph.top - bounds.top);
        bottom = Math.max(bottom, glyph.bottom - bounds.top);
      }
    } finally { probe.remove(); }
    // Retain the measured baseline: increasing line-height after probing moves
    // the glyph origin. The reservation covers the original line box and every
    // digit's measured top/bottom, with ink offset into that same envelope.
    const height = bottom - top;
    slot.style.cssText = `display:inline-block;position:relative;width:${width}px;`
      + `min-width:${width}px;max-width:${width}px;height:${height}px;min-height:${height}px;`
      + `max-height:${height}px;line-height:${line}px;vertical-align:bottom;white-space:nowrap;`
      + `flex:0 0 ${width}px;padding:0;margin:0;border:0`;
    slot.firstElementChild.style.cssText = `position:absolute;left:0;top:${-top}px;display:block;`
      + "white-space:nowrap;line-height:inherit;padding:0;margin:0;border:0";
    // Reference prose has its own glyph overhang under tight body leading.
    // Give this complete locator a local formatting box and reserve its actual
    // top/bottom overhang, rather than borrowing a larger owner or weakening fit.
    ref.style.display = "inline-block";
    ref.style.maxWidth = "100%";
    ref.style.verticalAlign = "bottom";
    ref.style.paddingTop = "0";
    ref.style.paddingBottom = "0";
    const bounds = ref.getBoundingClientRect();
    range.selectNodeContents(ref);
    const glyphs = locatorLines(range).filter((rect) => rect[4] && rect[5]);
    if (glyphs.length) {
      ref.style.paddingTop =
        Math.max(0, bounds.top - Math.min(...glyphs.map((rect) => rect[1]))) + "px";
      ref.style.paddingBottom =
        Math.max(0, Math.max(...glyphs.map((rect) => rect[3])) - bounds.bottom) + "px";
    }
  }
  function prepareLocators() {
    locatorPass = { expected: new Map(), reservations: new Map() };
    const sections = locatorNodes(document, JOB);
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
      if (section.dataset.sheet !== "job") {
        throw new Error("Recording destinations require one continuous job flow.");
      }
      for (const [ordinal, blank] of locatorNodes(section, ".writing-blank").entries()) {
        const field = blank.closest(".field,.result-field,.authored-blank");
        if (!field) throw new Error("An original writing area has no structural owner.");
        const name = field.querySelector(".field-label")?.textContent ?? "",
          owner = physicalOwner(blank);
        const key = JSON.stringify([section.dataset.sheet, sectionIndex, "field", ordinal, name]);
        blank.setAttribute(LOCATOR_TARGET, key);
        field.setAttribute("data-locator-field-key", key);
        locatorPass.expected.set(key, { key, ...owner, section: section.dataset.sheet, name,
          authored: field.classList.contains("authored-blank"), ordinal });
      }
      for (const [ordinal, group] of locatorNodes(section, ".path-progress").entries()) {
        const children = locatorNodes(group, ".writing-blank");
        if (children.length !== 2) {
          throw new Error("A progress record must retain its level and last completed # together.");
        }
        const members = children.map((node) => node.getAttribute(LOCATOR_TARGET));
        const key = JSON.stringify([section.dataset.sheet, sectionIndex, "progress pair", ordinal]);
        const meta = { key, ...physicalOwner(group), section: section.dataset.sheet, members };
        children.forEach((node) => node.setAttribute("data-locator-group", key));
        locatorPass.expected.set(key, meta);
        for (const locator of locatorNodes(group.closest(".contour"),
          "[data-continuation-locator]")) {
          const instruction = [...locator.childNodes].map((node) => node.cloneNode(true));
          const ref = locatorReference(meta, "");
          ref.firstChild.replaceWith(...instruction,
            document.createTextNode(" — " + meta.identity + ", page "));
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
      ref.style.removeProperty("position");
      ref.style.removeProperty("visibility");
      locatorPass.reservations.set(meta.key, ref);
    }
  }
  const locatorInstruction = (meta) => meta.authored
    ? "Original authored blank " + (meta.ordinal + 1) : "Original " + meta.name;
  function locatorRegistry() {
    for (const section of locatorNodes(document, JOB)) {
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
          setup: page.setup, workpiece: page.workpiece,
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
    const nodes = locatorNodes(document, JOB + "," + JOB + " *")
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
    const starts = locatorNodes(document, JOB).map(
      (section) => [section.dataset.sheet, Number(section.dataset.pages),
        locatorStarts(section).map((start) => [start.page, start.top]), locatorRect(section)]
    );
    return JSON.stringify([geometry, text, registry, CAP,
      Number(document.documentElement.dataset.printWidth), starts]);
  }
  function finishLocators() {
    const allRefs = locatorNodes(document, "[" + LOCATOR_REF + "]");
    const refs = allRefs.filter(locatorVisible);
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
    // Hidden original repeat rows still retain valid addresses when their
    // continuation copies print. Only visible references participate in geometry.
    for (const ref of allRefs) {
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
        // An inline method label's glyph box omits the line-height leading used
        // by its reserved counter. Its method block owns the complete line box.
        page = locatorPage(ref),
        owner = ref.closest("tr,.cont-head,li,p,.op-action,.inspection-method")
          ?? ref.parentElement;
      const ownerRect = locatorRect(owner), ownerBounds = { left: ownerRect[0],
        top: ownerRect[1], right: ownerRect[2], bottom: ownerRect[3] },
        refRects = locatorLines(ref), slotRect = locatorRect(slot);
      if (!locatorWithin(slotRect, ownerBounds) || !locatorWithin(slotRect, page)) {
        throw new Error("A recording-locator reservation escapes its owner or local print page. "
          + JSON.stringify({ key: ref.getAttribute(LOCATOR_REF),
            owner: { tag: owner.tagName, id: owner.id, class: owner.getAttribute("class"),
              bounds: ownerBounds },
            slot: { left: slotRect[0], top: slotRect[1], right: slotRect[2], bottom: slotRect[3] },
            page: { number: page.page, left: page.left, top: page.top,
              right: page.right, bottom: page.bottom } }));
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
              const style = getComputedStyle(node.parentElement);
              throw new Error("A recording-locator glyph escapes its reservation or print owner. "
                + JSON.stringify({ key: ref.getAttribute(LOCATOR_REF),
                  character: node.textContent.slice(offset, offset + 1),
                  ink: node.parentElement === ink,
                  glyph: { left: rect[0], top: rect[1], right: rect[2], bottom: rect[3] },
                  containers, slot: slotRect, reference: refRects,
                  owner: { tag: owner.tagName, class: owner.getAttribute("class"),
                    bounds: ownerBounds },
                  page: { number: page.page, left: page.left, top: page.top,
                    right: page.right, bottom: page.bottom },
                  typography: { family: style.fontFamily, size: style.fontSize,
                    weight: style.fontWeight, lineHeight: style.lineHeight,
                    slotLineHeight: getComputedStyle(slot).lineHeight,
                    inkLineHeight: getComputedStyle(ink).lineHeight } }));
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
  function prepareTableColumns() {
    for (const table of document.querySelectorAll(JOB + " table")) {
      if (table.querySelector(":scope > colgroup")
          || getComputedStyle(table).tableLayout !== "auto") continue;
      const rows = [...table.rows].filter((row) =>
        [...row.cells].every((cell) => cell.colSpan === 1 && cell.rowSpan === 1));
      const count = Math.max(0, ...rows.map((row) => row.cells.length));
      const row = rows.find((candidate) => candidate.cells.length === count);
      if (!row || count === 0) continue;
      const firstColumn = rows.filter((candidate) => candidate.cells.length === count)
        .map((candidate) => candidate.cells[0]);
      if (firstColumn.every((cell) => cell.textContent.trim().replace(/\s+/g, " ").length <= 20
          && !cell.querySelector("figure,.field,.result-field,.authored-blank"))) {
        // Short keys are labels, not prose. Their min-content width must include
        // the complete key/header instead of a single character from anywhere-wrap.
        for (const cell of firstColumn) {
          cell.style.whiteSpace = "nowrap";
          cell.style.overflowWrap = "normal";
        }
      }
      // Let the browser allocate content-sized columns once at the print width.
      // Continuation fragments retain those measured widths, not equal shares or
      // a new allocation based only on the few rows left in that fragment.
      const columns = document.createElement("colgroup");
      columns.setAttribute(ADDED, "");
      for (const cell of row.cells) {
        const column = document.createElement("col");
        column.style.width = cell.getBoundingClientRect().width + "px";
        columns.append(column);
      }
      table.prepend(columns);
      table.style.tableLayout = "fixed";
    }
  }
  function paginate(section) {
    // Recompute original/context distinctions at this width, never from a previous pass.
    section.querySelectorAll(".page-context").forEach((context) => {
      context.removeAttribute(CONTEXT_ROLE);
    });
    const statusContents = [...(section.querySelector(":scope > .banner")?.childNodes || [])]
      .map((node) => node.cloneNode(true));
    const compactRunning = ["pro", "hobby"].includes(document.body.dataset.detail);
    const compactTitle = section.dataset.jobTitle || section.dataset.part;
    const quantity = section.dataset.quantity ? "qty " + section.dataset.quantity : "";
    const title = [section.dataset.part, section.dataset.drawing,
      section.dataset.revision ? "rev " + section.dataset.revision : "REV NOT CONFIRMED",
      quantity]
      .filter(Boolean).join(" · ");
    const titleOwners = new Map(
      [...section.querySelectorAll("h3.page-context > [data-title-source]")]
        .map((source) => [source.dataset.titleSource, source.textContent])
    );
    function fullTitleCanonicalOnPage(key, originalOnly = false) {
      const text = titleOwners.get(key);
      if (!text) return false;
      const left = section.getBoundingClientRect().left,
        right = left + Number(document.documentElement.dataset.printWidth);
      const within = (r) => r.left >= left - .01 && r.right <= right + .01
        && r.top >= pageTop - .01 && r.bottom <= pageTop + CAP + .01;
      for (const span of section.querySelectorAll("[data-title-source]")) {
        if (span.dataset.titleSource !== key || span.textContent !== text) continue;
        const running = span.closest(".cont-context"), original = span.closest("h3.page-context");
        if (running ? originalOnly : !original || span.closest("[" + ADDED + "]")) continue;
        if (!span.getClientRects().length || !within(span.getBoundingClientRect())) continue;
        // A single Range measures every retained title run, including nested numeric
        // spans. Per-word wrappers and repeated subtree queries made a long depth
        // list quadratic during prefix fitting without proving anything stronger.
        const range = document.createRange();
        range.selectNodeContents(span);
        const rects = [...range.getClientRects()].filter((rect) => rect.width && rect.height);
        if (rects.length && rects.every(within)) return true;
      }
      return false;
    }
    function refreshTitleCopies(t) {
      for (const span of t.tHead?.querySelectorAll("[data-title-repeat]") || []) {
        const key = span.dataset.titleRepeat;
        span.toggleAttribute("data-title-suppressed",
          span.textContent === titleOwners.get(key) && fullTitleCanonicalOnPage(key));
      }
    }
    const contextHeads = new Map();
    [...section.querySelectorAll("[data-page-context]")].forEach((owner, index) => {
      // Stable within a pass and inherited by source fragments; identical titles in
      // different physical setups never select each other's heading.
      owner.dataset.printContext = String(index);
      const original = owner.querySelector(":scope > .page-context");
      if (!original) return;
      const style = getComputedStyle(original);
      contextHeads.set(String(index), {
        heading: original.cloneNode(true),
        typography: TYPOGRAPHY.map((property) => [property, style.getPropertyValue(property)])
      });
    });
    const operationHeads = new Map();
    [...section.querySelectorAll("tbody.operation")].forEach((body, index) => {
      body.dataset.printOperation = String(index);
      operationHeads.set(String(index), [...body.rows].filter(
        (row) => row.classList.contains("operation-main") || row.querySelector(".op-note")
      ).map((row) => row.cloneNode(true)));
    });
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
      + ".cont-head,.checkpoint-results,.checkpoint-result,[data-continuation-locator],"
      + ".fixed-locator-reference,[" + ADDED + "]";
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
    function pageProgress(el, relax = true, firstPrefixOnly = false) {
      // A full repeated heading can already exhaust the page. No original
      // prefix can fit below that start; compact context before cloning words.
      if (box(el).top >= pageTop + CAP) return null;
      if (el.tagName === "TABLE") {
        const progress = sourceProgress(el, el.tBodies[0]);
        return progress ? () => prefixBottom(el, progress.row, progress.contents) : null;
      }
      for (const point of pointsIn(el)) {
        const contents = contentsAt(el, point);
        if (!originalText(contents)) continue;
        if (fits(textBottom(el, contents))) return () => textBottom(el, contents);
        // The first pass is only an admission trial for full repeated context.
        // A conservative rejection can shorten that copy, never refuse source:
        // after compaction the complete mixed-block prefix search runs below.
        if (firstPrefixOnly) break;
      }
      if (originalText(el) && fits(box(el).bottom)) return () => box(el).bottom;
      return relax && prepareFields(el) ? pageProgress(el, false, firstPrefixOnly) : null;
    }
    function compactContext(el, suffix = "", operationOnly = false) {
      const references = locatorNodes(el, "[" + LOCATOR_REF + "]")
        .map((ref) => ref.cloneNode(true));
      const identity = /^.*?\bop\s+\d+\b/.exec(el.textContent);
      if (!identity) return false;
      const authored = el.dataset.pageContext?.split(/\s+[—·]\s+/, 1)[0].trim(),
        label = !operationOnly && authored && el.textContent.startsWith(authored)
          ? authored : identity[0];
      const range = document.createRange(),
        walker = document.createTreeWalker(el, NodeFilter.SHOW_TEXT);
      range.selectNodeContents(el);
      let remaining = label.length, node;
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
    const sharedOwners = new Map();
    function sharedPhysicalOwners(raw) {
      if (!sharedOwners.has(raw)) {
        let values;
        try { values = JSON.parse(raw); } catch { values = null; }
        sharedOwners.set(raw, Array.isArray(values) && values.length
          && values.every((value) => value && typeof value.setup_id === "string"
            && value.setup_id.trim() && (value.workpiece == null
              || typeof value.workpiece === "string"))
          ? values.map((value) => ({ setup: value.setup_id,
            member: "", workpiece: value.workpiece || "" })) : []);
      }
      return sharedOwners.get(raw);
    }
    const PAGE_REFERENCE = '[data-page-reference="final-inspection"]',
      routeOrder = new Map();
    function registerRoute(scope, setup) {
      const key = JSON.stringify([scope, setup]);
      if (setup && !routeOrder.has(key)) routeOrder.set(key, routeOrder.size);
      return routeOrder.get(key);
    }
    // Register original route scopes before fragmentation; their token survives
    // splitting. Separate fresh wrappers remain separate even with identical labels.
    const routeScopes = [...section.querySelectorAll("[data-setup-title]")].filter(
      (node) => !node.closest(PAGE_REFERENCE)
        && !node.parentElement.closest("[data-setup-title]"));
    routeScopes.forEach((scope, index) => {
      scope.dataset.printOwnerScope = String(index);
      let members;
      try { members = JSON.parse(scope.dataset.setupMembers || "[]"); }
      catch { members = []; }
      if (Array.isArray(members)) members.filter(
        (value) => typeof value === "string" && value.trim()
      ).forEach((setup) => registerRoute(String(index), setup));
      registerRoute(String(index), physicalOwner(scope).setup);
      // Shared operation lists retain authored route order even when a selected
      // picture for a later member precedes the common operation in the DOM.
      for (const node of scope.querySelectorAll("[data-physical-ops]")) {
        if (node.closest(PAGE_REFERENCE)) continue;
        sharedPhysicalOwners(node.dataset.physicalOps).forEach(
          (owner) => registerRoute(String(index), owner.setup));
      }
      for (const node of scope.querySelectorAll("[data-setup-id]")) {
        if (node.closest(PAGE_REFERENCE)) continue;
        registerRoute(String(index), physicalOwner(node).setup);
      }
    });
    function sourcePhysicalOwners(element) {
      if (element.closest(PAGE_REFERENCE)) return [];
      const source = element.closest("[data-setup-id],[data-physical-ops]");
      if (!source) return [];
      const scope = source.closest("[data-print-owner-scope]")?.dataset.printOwnerScope,
        owners = source.hasAttribute("data-physical-ops")
          ? sharedPhysicalOwners(source.dataset.physicalOps)
          : [physicalOwner(element)].filter((owner) => owner.setup);
      return owners.map((owner) => {
        const member = owner.member === owner.workpiece ? "" : owner.member,
          key = JSON.stringify([scope ?? null, owner.setup, member, owner.workpiece]);
        return { ...owner, member, scope, key,
          order: registerRoute(scope ?? null, owner.setup) };
      });
    }
    const physicalLabels = [...new Set([...section.querySelectorAll(
      "[data-setup-id],[data-physical-ops]")].flatMap(
      (node) => sourcePhysicalOwners(node).map((owner) => owner.setup)))];
    function reserveRunningSlot(slot, candidates) {
      // Measure in place at the inherited typography, before fitting source.
      // Both deferred totals and owner ranges retain this envelope when filled.
      slot.style.display = "inline-block";
      slot.style.whiteSpace = "nowrap";
      slot.style.verticalAlign = "bottom";
      const range = document.createRange();
      let width = 0, height = 0, above = 0, below = 0;
      for (const candidate of candidates) {
        slot.textContent = candidate;
        const bounds = slot.getBoundingClientRect();
        range.selectNodeContents(slot);
        const ink = range.getBoundingClientRect();
        width = Math.max(width, bounds.width);
        height = Math.max(height, bounds.height);
        above = Math.max(above, bounds.top - ink.top);
        below = Math.max(below, ink.bottom - bounds.bottom);
      }
      // Tight working leading can be shorter than the glyph envelope. Preserve
      // its baseline and reserve the actual overhang, as for recording locators.
      slot.style.paddingTop = above + "px";
      slot.style.paddingBottom = below + "px";
      slot.style.width = width + "px";
      slot.style.height = height + above + below + "px";
      slot.textContent = "";
    }
    function finishPageOwners() {
      if (!compactRunning) return;
      const starts = [section, ...section.querySelectorAll(".cont-head")],
        owners = starts.map(() => []), seenSetups = new Set(),
        setupKey = (owner) => JSON.stringify([owner.scope, owner.setup]);
      const walker = document.createTreeWalker(section,
        NodeFilter.SHOW_ELEMENT | NodeFilter.SHOW_TEXT);
      while (walker.nextNode()) {
        const node = walker.currentNode, element = node.nodeType === Node.TEXT_NODE
          ? node.parentElement : node;
        if (node.nodeType === Node.TEXT_NODE ? !node.textContent.trim()
            : !element.matches("img,svg")) continue;
        if (element.closest("[" + ADDED + "],.record-continuation,.fixed-locator-reference")
            || !locatorVisible(element)) continue;
        const sourceOwners = sourcePhysicalOwners(element);
        if (!sourceOwners.length) continue;
        const range = document.createRange();
        range.selectNode(node);
        if (![...range.getClientRects()].some((rect) => rect.width && rect.height)) continue;
        // Retained DOM boundaries, not page-number guesses or interior headings,
        // decide membership. Fragments inherit the original physical metadata.
        const start = starts.findLastIndex((head) => head === element
          || !!(head.compareDocumentPosition(node) & Node.DOCUMENT_POSITION_FOLLOWING));
        for (const owner of sourceOwners) {
          if (start >= 0 && !owners[start].some((entry) => entry.key === owner.key)) {
            owners[start].push(owner);
          }
        }
      }
      owners.forEach((entries, index) => {
        entries.sort((left, right) => left.order - right.order);
        const head = starts[index], first = entries[0],
          continued = !!first && first.scope !== undefined && seenSetups.has(setupKey(first));
        // The qualifier describes a setup, not an individual member's record.
        // Preserve full member identities above, but resume the scoped setup even
        // when this page opens on its first workpiece-specific inspection record.
        entries.filter((entry) => entry.scope !== undefined)
          .forEach((entry) => seenSetups.add(setupKey(entry)));
        if (!index) return;
        head.dataset.pageOwners = JSON.stringify(entries.map(
          ({ setup, member, workpiece }) => ({ setup, member, workpiece })));
        head.dataset.ownerRangeStart = first?.setup || "";
        head.dataset.ownerRangeEnd = entries.at(-1)?.setup || "";
        head.dataset.ownerContinued = String(continued);
        const slot = head.querySelector(".cont-page-owners");
        if (!slot || !first) return;
        const setups = [...new Set(entries.map((entry) => entry.setup))];
        slot.textContent = " · Setups " + first.setup + (continued ? " (continued)" : "")
          + (setups.length > 1 ? " → " + entries.at(-1).setup : "");
        if (slot.scrollWidth > slot.clientWidth + 1) throw new Error(
          "A physical owner range exceeds its measured running-header reservation.");
      });
    }
    function physicalOwnerWrapper(origin) {
      let wrapper = origin.closest("[data-setup-id],[data-setup-title]");
      if (!wrapper) return null;
      const id = wrapper.dataset.setupId || "", title = wrapper.dataset.setupTitle || "";
      if (!id && !title) return null;
      for (let parent = wrapper.parentElement; parent && parent !== section;
          parent = parent.parentElement) {
        if (id ? parent.dataset.setupId === id
            : !parent.dataset.setupId && parent.dataset.setupTitle === title) wrapper = parent;
      }
      return wrapper;
    }
    function openingOwnerHeadingVisible(wrapper) {
      // Only the owner's direct original opening heading can supply its identity.
      // An inner READINGS/HOLD/etc. heading cannot make a continued tail fresh.
      const first = [...wrapper.children].find((node) => !node.hasAttribute(ADDED));
      const selector = wrapper.matches(".setup-variant") ? ".variant-label" : "h2";
      if (!first?.matches(selector) || first.closest("[" + ADDED + "]")
          || !locatorVisible(first)) return false;
      for (let node = wrapper.firstChild; node !== first; node = node.nextSibling) {
        if (node.nodeType === Node.TEXT_NODE && node.textContent.trim()) return false;
      }
      const left = section.getBoundingClientRect().left,
        right = left + Number(document.documentElement.dataset.printWidth),
        within = (rect) => rect.left >= left - .01 && rect.right <= right + .01
          && rect.top >= pageTop - .01 && rect.bottom <= pageTop + CAP + .01;
      const range = document.createRange();
      range.selectNodeContents(first);
      const rects = [...range.getClientRects()].filter((rect) => rect.width && rect.height);
      return rects.length > 0 && rects.every(within);
    }
    function breakAt(el, origin = el) {
      pages += 1;
      const head = document.createElement("p");
      head.className = "cont-head";
      head.setAttribute(ADDED, "");
      const running = document.createElement("span");
      running.className = "cont-title";
      const setup = physicalOwner(origin), owner = origin.closest("[data-page-context]");
      running.textContent = (compactRunning
        ? [compactTitle || title, compactTitle ? quantity : ""]
        : [title, setup.identity === "Job" ? "" : setup.identity])
        .filter(Boolean).join(" · ") + (compactRunning ? "" : " (continued)");
      for (const [key, value] of Object.entries({ setupTitle: setup.title,
        setupId: setup.setup, member: setup.member, workpiece: setup.workpiece })) {
        if (value) head.dataset[key] = value;
      }
      if (owner) head.dataset.pageContext = owner.dataset.pageContext;
      if (compactRunning) {
        const status = statusContents.map((node) => node.textContent).join("")
          .replace("EXAMPLE ONLY — NOT FOR EXECUTION IN A REAL ENVIRONMENT", "EXAMPLE ONLY");
        if (section.dataset.continuationLabel &&
            !status.includes(section.dataset.continuationLabel)) {
          running.append(" · " + section.dataset.continuationLabel);
        }
        if (status) running.append(" · " + status);
      } else {
        if (section.dataset.continuationLabel) {
          running.append(" · " + section.dataset.continuationLabel);
        }
        if (statusContents.length) {
          running.append(" · ", ...statusContents.map((node) => node.cloneNode(true)));
        }
      }
      const count = document.createElement("span");
      count.className = "cont-count";
      count.append(" · page " + pages + " of ");
      const total = document.createElement("span");
      total.className = "cont-page-total";
      total.style.fontKerning = "none";
      count.append(total);
      // The count line is present during every fit/progress measurement. Its final
      // digits cannot change the title wrapping or the preserved working context.
      head.append(running, "\n", count);
      el.before(head);
      reserveRunningSlot(total, Array.from({ length: 10 },
        (_, digit) => String(digit).repeat(locatorPass.digits)));
      if (compactRunning && physicalLabels.length) {
        const owners = document.createElement("span");
        owners.className = "cont-page-owners";
        count.append(owners);
        reserveRunningSlot(owners, physicalLabels.map(
          (label) => " · Setups " + label + " (continued) → " + label));
      }
      head.style.breakBefore = "page";
      pageTop = box(head).top;
      pageStart = el;
      const source = owner && contextHeads.get(owner.dataset.printContext);
      const wrapper = compactRunning && !owner ? physicalOwnerWrapper(origin) : null,
        freshOwner = wrapper && (el === wrapper || el.contains(wrapper));
      const localOwner = compactRunning && !owner && setup.identity !== "Job"
        && (!freshOwner || !openingOwnerHeadingVisible(wrapper));
      if (owner || localOwner) {
        const context = document.createElement("span");
        context.className = "cont-context";
        if (owner) context.dataset.pageContext = owner.dataset.pageContext;
        if (source) {
          context.append(...[...source.heading.childNodes].map((node) => node.cloneNode(true)));
          // The copied destination counters were reserved in the original heading.
          // Preserve that context's typography before fitting the running header,
          // rather than discovering a different inherited line box after pagination.
          for (const [property, value] of source.typography) {
            context.style.setProperty(property, value);
          }
        } else context.textContent = owner
          ? owner.dataset.pageContext
          : setup.identity + (freshOwner ? "" : " (continued)");
        cleanLocatorCopy(context);
        head.append("\n", context);
        const titleKey = source?.heading.querySelector("[data-title-source]")?.dataset.titleSource;
        if (titleKey) {
          // Prefer the complete authored heading when it opens this page. A full
          // running copy above the same heading wastes space and presents it twice.
          // Trial only the repeated identity; restore it when the complete original
          // is absent, fragmented or cannot fit at its retained working typography.
          const full = context.cloneNode(true);
          if (compactContext(context) && !fullTitleCanonicalOnPage(titleKey, true)) {
            context.replaceChildren(...full.childNodes);
          }
        }
        if (!pageProgress(el, true, true)) {
          // Only repeated context may compact. The complete authored title and
          // every original instruction remain source and must advance finitely.
          for (const repeated of el.querySelectorAll(".record-continuation")) {
            compactContext(repeated, " (continued)");
          }
          if (!compactContext(context)) context.textContent = owner
            ? owner.dataset.pageContext : setup.identity + " (continued)";
          // Authored context may itself be a complete over-page instruction.
          // If its preferred prefix still blocks source, repeat only the scoped
          // operation identity; keep the complete original heading as source.
          if (!pageProgress(el)
              && (!compactContext(context, "", true) || !pageProgress(el))) throw new Error(
            "A continuation owner cannot share a page with original source progress.");
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
        if (heading(prev) || caption || prev?.matches(".lead-in,.variant-label")) {
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
        more.textContent = "Operations continue on the next page, op " + op;
        if (!fits(box(more).bottom)) {
          more.remove();
          more = null;
        }
      }
      breakAt(start, el);
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
      return true;
    }
    function pointsIn(el) {
      const points = [], atomicContexts = new Map();
      const walker = document.createTreeWalker(el, NodeFilter.SHOW_ELEMENT | NodeFilter.SHOW_TEXT, {
        acceptNode(node) {
          // A whole canonical view is source, but none of its SVG, title, caption
          // or text descendants is a legal pagination boundary.
          if (node.parentElement?.closest("figure,.checkpoint-results,[" + ADDED + "]")) {
            return NodeFilter.FILTER_REJECT;
          }
          // An enclosing worksheet row may span many pages. Its nested table
          // advances at complete source groups, never within a row or field.
          const table = node.parentElement?.closest("table");
          if (table && el.contains(table)) return NodeFilter.FILTER_REJECT;
          return node.nodeType === Node.TEXT_NODE || node.matches("table,figure," + RESULTS)
            ? NodeFilter.FILTER_ACCEPT : NodeFilter.FILTER_SKIP;
        }
      });
      let node;
      while ((node = walker.nextNode())) {
        if (node.nodeType === Node.ELEMENT_NODE) {
          const parent = node.parentNode, slot = [...parent.childNodes].indexOf(node);
          points.push([parent, slot]);
          if (node.tagName === "TABLE") {
            const bodies = [...node.tBodies];
            for (const [index, body] of bodies.entries()) {
              const rows = [...body.rows];
              // Authored tables normally group rows in separate bodies. Also
              // support a conventional single-body READINGS table, provided no
              // merged cell binds one complete reading row to the next.
              if (bodies.length === 1 && node.classList.contains("readings")
                  && rows.every((row) => [...row.cells].every((cell) => cell.rowSpan === 1))) {
                for (const row of rows.slice(0, -1)) {
                  points.push([body, [...body.childNodes].indexOf(row) + 1]);
                }
              }
              if (index < bodies.length - 1) {
                points.push([node, [...node.childNodes].indexOf(body) + 1]);
              }
            }
          }
          // Outside-table endpoints leave no empty header-only table shell.
          points.push([parent, slot + 1]);
          continue;
        }
        if (node.parentElement.closest(
          ".field, .result-field, .authored-blank, .performed-mark, .reading, .measurement-ref, "
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
      let contents;
      if (el.tagName === "TR") contents = rowContents(el, point, tail);
      else {
        const range = document.createRange();
        range.selectNodeContents(el);
        if (tail) range.setStart(...point);
        else range.setEnd(...point);
        contents = range.cloneContents();
      }
      const boundary = point[0],
        table = boundary.nodeType === Node.ELEMENT_NODE
          && boundary.matches("table,tbody") ? boundary.closest("table") : null;
      if (!tail || !table || !el.contains(table)) return contents;
      const copy = [...contents.querySelectorAll("table")].find(
        (node) => node.dataset.tableContext === table.dataset.tableContext
      );
      if (!copy) throw new Error("A nested table continuation lost its source owner.");
      // Range cloning from a body boundary omits the measured columns and head.
      // Restore only this table's skeleton and registered repeatable context;
      // recording destinations and canonical figures remain sole original atoms.
      const skeleton = [...table.children].filter(
        (part) => part.tagName === "COLGROUP" || part.tagName === "THEAD"
      ).map((part) => {
        const repeated = part.cloneNode(true);
        repeated.querySelectorAll("tr.continued, tr.repeat, tr.table-context")
          .forEach((row) => row.remove());
        return repeated;
      });
      copy.prepend(...skeleton);
      copy.setAttribute(SPLIT, "");
      const head = copy.tHead || copy.createTHead(),
        columns = head.querySelector("tr:not(.repeat):not(.table-context)");
      for (const source of tableHeads.get(table.dataset.tableContext) || []) {
        const row = repeatTableRow(source);
        if (columns) columns.before(row);
        else head.append(row);
      }
      return contents;
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
      if (!row || box(row).top >= pageTop + CAP) return null;
      if (t.classList.contains("measurement-actions")) {
        return originalText(row) && fits(prefixBottom(t, row))
          ? { row, point: null, contents: null } : null;
      }
      for (const point of pointsIn(row)) {
        const contents = contentsAt(row, point);
        if (!originalText(contents)) continue;
        if (fits(prefixBottom(t, row, contents))) return { row, point, contents };
        // Fixed measured columns make later source prefixes no smaller. A full
        // scan cannot recover space below an already non-fitting first prefix.
        break;
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
          (body) => !body.hasAttribute("data-job-print-fragment")
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
    function retainSourceAtoms(el, fragments) {
      const selector = "figure,.field,.result-field,.authored-blank," + RESULTS;
      const atoms = (root) => [...root.querySelectorAll(selector)].filter((node) => {
        const owner = node.parentElement?.closest(selector);
        return !owner || !root.contains(owner);
      });
      const originals = atoms(el), copies = fragments.flatMap(atoms);
      if (originals.length !== copies.length
          || originals.some((node, index) => !node.isEqualNode(copies[index]))) {
        throw new Error("A source figure or recording destination was split, lost, or reordered.");
      }
      // Measurement uses disposable clones; the accepted partition must retain
      // the loaded canonical images and sole live recording destinations.
      copies.forEach((copy, index) => copy.replaceWith(originals[index]));
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
          retainSourceAtoms(el, [first]);
          el.replaceChildren(first);
          return el;
        }
        if (!candidate.tailCredit) continue;
        retainSourceAtoms(el, [first, remaining]);
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
          const owner = rest.querySelector(".inspection-requirement")
            || rest.querySelector(".inspection-layout") || rest.cells[0];
          // A valid tail may begin in a method after the complete requirement
          // printed on the previous page. Keep identity with that retained method.
          owner.prepend(identity);
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
      const sources = operationHeads.get(body.dataset.printOperation);
      if (!sources?.length || !body.hasAttribute("data-operation-continuation")) return;
      const full = contextRow(sources[0]), identity = full.cloneNode(true);
      identity.querySelector(".op-action")?.remove();
      const number = identity.querySelector(".op-number"),
        heading = identity.querySelector(".op-head h3");
      if (number && heading) heading.replaceChildren(number);
      identity.querySelector(".op-details")?.remove();
      body.prepend(identity);
      const accepted = () => fits(prefixBottom(t, progress.row, progress.contents));
      if (!accepted()) {
        identity.remove();
        throw new Error("An operation identity cannot share a page with original source progress.");
      }
      identity.replaceWith(full);
      if (!accepted()) {
        full.replaceWith(identity);
        const compact = full.querySelector(".op-details")?.cloneNode(true);
        if (compact) {
          [...compact.children].forEach((field) => {
            if (!field.matches(".op-tool, .op-target, .op-direction")) field.remove();
          });
          identity.cells[0].append(compact);
          if (!accepted()) compact.remove();
        }
      }
      const notes = sources.slice(1).map(contextRow);
      const head = [...body.rows].find((row) => row.hasAttribute(ADDED));
      head.after(...notes);
      if (!accepted()) notes.forEach((row) => row.remove());
    }
    function repeatTableRow(source) {
      const row = cleanLocatorCopy(source.cloneNode(true));
      row.setAttribute(ADDED, "");
      row.querySelectorAll(".performed-mark, .writing-blank, .tick, figure")
        .forEach((mark) => mark.remove());
      row.querySelectorAll(".field, .result-field, .authored-blank").forEach((field) => {
        field.replaceWith(...locatorFieldContext(field));
      });
      return row;
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
        const row = repeatTableRow(source);
        const head = t.tHead || t.createTHead();
        const columns = head.querySelector("tr:not(.repeat):not(.table-context)");
        const followingContext = optionalOnly && row.classList.contains("table-context")
          ? head.querySelector(`tr.table-context:not([${ADDED}])`) : null;
        const anchor = followingContext || columns;
        if (anchor) anchor.before(row);
        else head.append(row);
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
      // Pull-list records and measurement actions stay whole, including their blanks.
      if (t.matches("table.tools, table.measurement-actions")) return false;
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
      if (!t.classList.contains("operations")) rest.setAttribute("data-job-print-fragment", "");
      rest.append(...[...body.rows].slice(index));
      body.after(rest);
      if (rest.classList.contains("operation")) {
        rest.setAttribute("data-operation-continuation", "");
      }
      return true;
    }
    function startTablePage(t) {
      t.setAttribute(SPLIT, "");
      t.tHead?.querySelectorAll("tr.continued, tr.repeat, tr.table-context")
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
        pointer("on the next page");
        while (t.tBodies.length > 1 && !fits(box(more).bottom)) {
          rest.insertBefore(t.tBodies[t.tBodies.length - 1], rest.tBodies[0]);
          pointer("on the next page");
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
      if (more) pointer("on the next page");
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
      if (j === 0 && (t.matches("table.tools, table.measurement-actions")
          || !sourceProgress(t, t.tBodies[0])) && move(t)) j = over();
      if (!t.classList.contains("operations")) {
        const bodies = [...t.tBodies];
        const authored = bodies.filter((body) => !body.hasAttribute("data-job-print-fragment"));
        const countBefore = (index) => bodies.slice(0, index).filter(
          (body) => !body.hasAttribute("data-job-print-fragment")
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
            t.classList.contains("tools")
              ? "A complete TOOLS row cannot fit on a print page."
              : t.classList.contains("measurement-actions")
                ? "A complete measurement action cannot fit on a print page."
                : "An over-page table record could not be continued without losing content."
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
        const style = getComputedStyle(el);
        if (style.display === "none") continue;
        if (style.display === "contents") {
          walk(el);
          continue;
        }
        if (["page", "always"].includes(style.breakBefore)) {
          // Honor an authored page boundary without retaining a second native
          // break after the measured running header. Reset restores the source.
          el.style.breakBefore = "auto";
          el.style.pageBreakBefore = "auto";
          if (el !== pageStart && box(el).top > pageTop) breakAt(el);
        }
        const b = box(el);
        if (fits(b.bottom)) continue;
        if (el.matches(RESULTS)) {
          move(el);
          if (!fits(box(el).bottom)) throw new Error(
            "A complete checkpoint result row cannot fit on a print page.");
        } else if (el.tagName === "TABLE") {
          table(el);
        } else if (el.tagName === "FIGURE") {
          move(el);
          if (!fits(box(el).bottom)) refuseFigure(el);
        } else if (el.children.length && style.display !== "inline"
            && ![...el.childNodes].some(
              (node) => node.nodeType === Node.TEXT_NODE && node.textContent.trim())
            && !el.matches("p, li, .page-context, .stop:not(.measurement-stop), "
              + ".caution, .unverified")) {
          // Ordinary flow containers may share a page and fragment between their
          // children. Only an explicit keep-together box moves as a whole.
          if (["avoid", "avoid-page"].includes(style.breakInside)
              && b.bottom - b.top <= CAP && move(el) && fits(box(el).bottom)) continue;
          const s = getComputedStyle(el);
          if (s.display.endsWith("flex") && !s.flexDirection.startsWith("column")) {
            el.setAttribute(STACKED, "");
          }
          // The container's own bottom padding and border print after its last child:
          // a child that fits only without them would push the box onto an unplanned
          // page the count never sees (#307).
          const capacity = CAP;
          CAP -= parseFloat(s.paddingBottom) + parseFloat(s.borderBottomWidth);
          try { walk(el); } finally { CAP = capacity; }
        } else {
          // Inline prose shares lines with its siblings. Fragment its complete
          // ordered content here: visiting only element children misses direct
          // text between/after readings, which can escape onto an uncounted page.
          if (style.display !== "inline") move(el);
          let current = el;
          while (!fits(box(current).bottom)) {
            const rest = fragment(current);
            if (!rest) {
              // Atomic inline readings have no legal word boundary. Move that
              // complete item only when no original prefix fits this page.
              if (style.display === "inline" && move(current)
                  && fits(box(current).bottom)) break;
              throw new Error(
                "An over-page text block could not be continued without losing content."
              );
            }
            breakAt(rest);
            current = rest;
          }
        }
      }
    }
    for (const figure of section.querySelectorAll("figure")) {
      const bounds = box(figure), height = bounds.bottom - bounds.top;
      if (height > CAP) refuseFigure(figure, height);
    }
    walk(section);
    finishPageOwners();
    section.querySelectorAll(".cont-head").forEach((head) => {
      const total = head.querySelector(".cont-page-total"), value = String(pages);
      if (value.length > locatorPass.digits) throw new Error(
        "A running page total exceeds its source-bound digit reservation.");
      total.textContent = value;
      const bounds = total.getBoundingClientRect(), range = document.createRange();
      range.selectNodeContents(total);
      const ink = range.getBoundingClientRect();
      if (ink.left < bounds.left - .01 || ink.right > bounds.right + .01
          || ink.top < bounds.top - .01 || ink.bottom > bounds.bottom + .01) throw new Error(
        "A running page total exceeds its measured reservation.");
    });
    for (const grid of section.querySelectorAll(RESULTS)) {
      const cells = [...grid.querySelectorAll(":scope > .checkpoint-result")];
      const first = cells[0]?.getBoundingClientRect();
      if (!first || cells.some((cell) => {
        const bounds = cell.getBoundingClientRect(), blank = cell.querySelector(".writing-blank");
        if (!blank || Math.abs(bounds.top - first.top) > .1) return true;
        const rect = blank.getBoundingClientRect(), style = getComputedStyle(blank);
        const width = rect.width - parseFloat(style.borderLeftWidth)
          - parseFloat(style.borderRightWidth);
        const height = rect.height - parseFloat(style.borderTopWidth)
          - parseFloat(style.borderBottomWidth);
        return width + .1 < 35 * 96 / 25.4 || height + .1 < 20 * 96 / 25.4;
      })) throw new Error(
        "Checkpoint results require one horizontal row of full-size writing cells.");
    }
    section.dataset.pages = pages;
    return pages;
  }
  function reset() {
    document.querySelectorAll("[" + ADDED + "]").forEach((el) => el.remove());
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
    for (const section of document.querySelectorAll(JOB)) {
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
      prepareTableColumns();
      prepareLocators();
      document.querySelectorAll("ol").forEach((list) => {
        [...list.children].filter((item) => item.tagName === "LI").forEach((item, index) => {
          item.value = list.start + index;
        });
      });
      const jobs = [...document.querySelectorAll(JOB)];
      if (jobs.length !== 1 || document.querySelectorAll("section.page[data-sheet]").length !== 1) {
        throw new Error("Print pagination requires one continuous job page.");
      }
      paginate(jobs[0]);
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
