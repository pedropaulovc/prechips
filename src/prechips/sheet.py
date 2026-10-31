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
from dataclasses import dataclass, replace
from decimal import Decimal
from html import escape
from importlib.resources import files
from typing import Literal

from . import trig
from ._sheet_pagination import JOB_PRINT_JS
from .clamp_labels import clamp_labels
from .findings import Status, is_required
from .joint_features import JOINT_PREP_LABEL
from .material_routes import (
    OUTPUT_PREFIX,
    MaterialGraph,
    input_refs,
    producer_setup,
    reference_frame,
    route_identities_known,
    setup_lineage,
)
from .measurements import angle_fact, length_debt, length_fact, measurement_entry, record_trusted
from .model import (
    LENGTH_REQUIREMENTS,
    TOLERANCE_REQUIREMENTS,
    TRAVELER_DETAILS,
    TravelerDetail,
    note_text,
    profiled,
    reference_only,
    tolerance_requirements,
)
from .rules._bench import hand_saw, manual_bench, unfixtured_handling
from .rules._envelope import measurement_item
from .rules.blank_credit import cited_tolerance
from .rules.coordinates import (
    CENTRE_OPS,
    OVERSHOOT_NOTE,
    dro_grid,
    dro_grid_debt,
    dro_grid_measurements,
    dro_z,
    faced_aim_claims,
    handwheel_readout,
    readout_kind,
    readout_units,
    readout_value,
    row_id,
)
from .rules.geometry_common import TURNING, approach, finite_saw_evidence
from .rules.hold_fields import align_indicator, align_travel
from .rules.inspection import ZONES, go_no_go_pair
from .rules.level_entry import in_air, stock_box
from .rules.resolution import (
    HAND_FED,
    HAND_FINISH,
    HAND_THREAD,
    LENGTH_TOLERANCE_MM,
    MAKE_OP_FIELDS,
    MANUAL,
    NAMED_REFERENCE,
    SAW_OPS,
    SLITTING_SAW_MODEL_REASON,
    TAP_OPS,
    UNKNOWN,
    UNRESOLVED_SAW_MODEL_REASON,
    WORKHOLDING_CATEGORIES,
    authored,
    authored_names,
    coating_process,
    drawing_precision,
    hand_fed,
    identity,
    jaw_top_z,
    length_mm,
    make_op_unknowns,
    make_ops,
    make_tool,
    named_item,
    op_check_targets,
    op_entries,
    op_entry,
    op_feature,
    op_features,
    operation_members,
    printed_band,
    projection_holder,
    resolve,
    saw_setup,
    select,
    setup_frame,
    setup_items,
    shop_made_item,
    slitting_saw,
    spindle_saw,
    tool_numbers,
    uncertain,
)
from .rules.resolution import record as _mapping
from .rules.swivel import STATED as SWIVEL_STATED
from .rules.swivel import setting as swivel_setting
from .rules.swivel import swivel_angle, swivelled
from .rules.tip_endpoints import (
    FACING,
    SAME_Z,
    arrival_zs,
    operative_z,
    stock_states,
    transfer,
)
from .rules.turned_profile import PROFILE_OPS
from .rules.zero_recipe.touch import DIRECTIONS as _SIGNS
from .rules.zero_recipe.touch import FACE_Z_TOL_MM

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
.meta > div { flex-shrink: 0; white-space: nowrap; }
.banner { border: var(--rule-warning) solid var(--color-ink); font-weight: bold;
padding: var(--space-xs) var(--space-sm); margin: var(--space-sm) 0; }
.stop { border: var(--rule-warning) solid var(--color-ink);
padding: var(--space-sm); margin: var(--space-sm) 0; font-weight: bold; break-inside: avoid; }
.unverified, .caution { border: var(--rule-thin) dashed var(--color-ink);
padding: var(--space-sm); margin: var(--space-sm) 0; break-inside: avoid; }
td .unverified { display: block; }
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
table.tools tbody, table.tools tr { break-inside: avoid; page-break-inside: avoid; }
table.handwheel-zero th:first-child {
padding-inline: var(--space-xs); white-space: nowrap; }
.measurement-ref { white-space: nowrap; overflow-wrap: normal; }
.measurement-stop { break-inside: auto; page-break-inside: auto; }
table.measurement-actions col.record-column {
width: calc(var(--writing-width) + 12mm + 2 * var(--space-sm)); }
table.measurement-actions .field { flex-direction: row; align-items: center;
margin: 0; white-space: nowrap; }
table.measurement-actions .field-label { min-width: 0; white-space: normal;
overflow-wrap: anywhere; }
table.measurement-actions .writing-blank { flex-shrink: 0; }
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
table.coords, table.zero { table-layout: auto; }
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
.paged table:not([data-job-print-split]) tr.repeat { display: none; }
table:not([data-job-print-split]) tr.table-context { display: none; }
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
.contour-row, .contour-row.tall, [data-job-print-stacked] { display: block; }
.contour-row > .contour { min-width: 0; }
@media screen {
  body { max-width: var(--page-content-width); margin: var(--space-md) auto;
  padding: 0 var(--space-sm); }
  .page { margin-bottom: var(--space-lg); }
  html:not(.print-measuring) table.coords { display: block; overflow-x: auto; }
}
@media print {
  html, body { width: var(--page-content-width); max-width: none;
  margin: 0; padding: 0; overflow: visible; }
  .page { margin: 0; }
}
@media screen and (max-width: 600px) {
  html:not(.print-measuring) .meta { display: block; }
  html:not(.print-measuring) .op-details { grid-template-columns: minmax(0, 1fr); }
  html:not(.print-measuring) table:not(.operations) {
  display: block; overflow-x: auto; table-layout: auto; }
}
body:is([data-detail="pro"], [data-detail="hobby"]) {
--text-running: var(--text-working); line-height: 1.18; }
body:is([data-detail="pro"], [data-detail="hobby"]) .cont-head { margin-bottom: 2pt; }
body:is([data-detail="pro"], [data-detail="hobby"]) .cont-count { display: inline; }
body:is([data-detail="pro"], [data-detail="hobby"]) h2 { font-size: var(--text-working);
margin: 7pt 0 3pt; line-height: 1.18; }
body:is([data-detail="pro"], [data-detail="hobby"]) h3 {
font-size: var(--text-working); line-height: 1.18; margin: 3pt 0 1pt; }
body:is([data-detail="pro"], [data-detail="hobby"]) .operation > tr > td { padding: 2pt 0; }
body:is([data-detail="pro"], [data-detail="hobby"]) .op-head,
body:is([data-detail="pro"], [data-detail="hobby"]) .op-head h3 { display: inline; }
body:is([data-detail="pro"], [data-detail="hobby"]) .op-details { display: inline; margin: 0; }
body:is([data-detail="pro"], [data-detail="hobby"]) .op-details > div { display: inline; }
body:is([data-detail="pro"], [data-detail="hobby"]) .op-details > div { margin-left: 8pt; }
body:is([data-detail="pro"], [data-detail="hobby"]) .op-details dt,
body:is([data-detail="pro"], [data-detail="hobby"]) .op-details dd { display: inline; }
body:is([data-detail="pro"], [data-detail="hobby"]) .op-details dt::after { content: ": "; }
body:is([data-detail="pro"], [data-detail="hobby"]) .op-note { margin: 1pt 0; }
body:is([data-detail="pro"], [data-detail="hobby"]) table:not(.operations) {
table-layout: auto; margin: 2pt 0; }
body:is([data-detail="pro"], [data-detail="hobby"]) table:not(.operations) :is(th, td) {
padding: 2pt 3pt; }
body:is([data-detail="pro"], [data-detail="hobby"]) table:not(.operations) p {
margin: 1pt 0; }
.setup-flow, .setup-family { min-width: 0; }
.setup-flow > h2, .setup-family > h2 { break-after: avoid; }
.variant-label { font-weight: bold; margin: 3pt 0 1pt;
break-after: avoid; page-break-after: avoid; }
.family-common { margin: 0; }
.inspection-method { margin: 2pt 0; min-width: 0; }
.checkpoint-results { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr));
gap: 3mm; break-inside: avoid; page-break-inside: avoid; margin: 2pt 0 5pt; }
.checkpoint-result { min-width: 0; }
.checkpoint-result .result-field { margin: 0; }
body:is([data-detail="pro"], [data-detail="hobby"]) .checkpoint-result .result-field { gap: 0; }
.checkpoint-result .writing-blank { min-width: 35mm; min-height: 20mm; width: auto; }
.checkpoint-results:has(> :only-child) { grid-template-columns: minmax(35mm, 1fr); }
.tool-settings { margin: 2pt 0; }
.tool-setting { margin: 1pt 0; }
.settings-key { table-layout: fixed; width: 100%; margin: 2pt 0; }
.settings-key th, .settings-key td { padding: 1pt 3pt; vertical-align: top; }
body:is([data-detail="pro"], [data-detail="hobby"]) .orientation-table :is(th, td):first-child {
width: 1%; white-space: nowrap; overflow-wrap: normal; }
body:is([data-detail="pro"], [data-detail="hobby"]) .setup-flow > h2,
body:is([data-detail="pro"], [data-detail="hobby"]) .setup-family > h2 {
border: 0; margin: 3pt 0 1pt; }
body:is([data-detail="pro"], [data-detail="hobby"]) .setup-variant,
body:is([data-detail="pro"], [data-detail="hobby"]) .family-common { display: contents; }
body:is([data-detail="pro"], [data-detail="hobby"]) .setup-variant > p,
body:is([data-detail="pro"], [data-detail="hobby"]) .family-common > p {
margin: 1pt 0; }
body:is([data-detail="pro"], [data-detail="hobby"]) .setup-variant > div[data-physical-ops] {
display: contents; }
.route-operation, .route-path p, .route-inspection p { margin: 1pt 0; }
.route-operation + .route-path { margin: 0 0 2pt; }
body:is([data-detail="pro"], [data-detail="hobby"]) .decision {
padding: 2pt 4pt; margin: 2pt 0; }
body:is([data-detail="pro"], [data-detail="hobby"]) .decision p { margin: 0; }
body[data-detail="pro"] span.decision { border: 0; padding: 0; margin: 0; font-weight: bold; }
body[data-detail="pro"] span.decision::after { content: "; "; }
body:is([data-detail="pro"], [data-detail="hobby"]) .setup-flow,
body:is([data-detail="pro"], [data-detail="hobby"]) .setup-family { margin: 3pt 0; }
.job-route { margin: 2pt 0; }
.picture-notice { border-left: var(--rule-thin) solid var(--color-ink);
padding-left: 5pt; }
/* Compact modes use the physically proven 12pt / 12.5pt print rhythm. */
body:is([data-detail="pro"], [data-detail="hobby"]) {
--line-working: 12.5pt; line-height: var(--line-working); }
body:is([data-detail="pro"], [data-detail="hobby"]) p,
body:is([data-detail="pro"], [data-detail="hobby"]) .setup-variant > p,
body:is([data-detail="pro"], [data-detail="hobby"]) .family-common > p,
body:is([data-detail="pro"], [data-detail="hobby"]) table:not(.operations) p { margin: 0; }
body:is([data-detail="pro"], [data-detail="hobby"]) h2,
body:is([data-detail="pro"], [data-detail="hobby"]) .setup-flow > h2,
body:is([data-detail="pro"], [data-detail="hobby"]) .setup-family > h2 {
line-height: var(--line-working); margin: 4pt 0 0; padding-top: 1pt; }
body:is([data-detail="pro"], [data-detail="hobby"])
:is(.setup-flow, .setup-family):has(> h2 + .route-prelude) > h2 {
display: inline; margin: 0; }
body:is([data-detail="pro"], [data-detail="hobby"])
:is(.setup-flow, .setup-family):has(> h2 + .route-prelude) > h2::after {
content: ": "; }
body:is([data-detail="pro"], [data-detail="hobby"]) h3 { line-height: var(--line-working); }
body:is([data-detail="pro"], [data-detail="hobby"]) table:not(.operations) :is(th, td) {
padding: 0 3pt; }
body:is([data-detail="pro"], [data-detail="hobby"]) .banner { padding: 2pt; margin: 0 0 4pt; }
body[data-detail="hobby"] h3 { margin: 4pt 0 0; padding-top: 1pt; }
body[data-detail="hobby"] .fixture-render { margin: 4pt 0; }
@media screen and (max-width: 600px) {
  html:not(.print-measuring) .checkpoint-results { grid-template-columns: minmax(0, 1fr); }
  html:not(.print-measuring) .checkpoint-result .writing-blank { min-width: 0; }
}
"""
)

# Console-style status marks kept on the dividing-head index line.
_GLYPHS = {"error": "✗", "warn": "!", "unknown": "?", "unsupported": "?"}
# A planned tool path ending this close to jaws, a dead centre or the jaw tops is
# hand-feed territory: it is boxed on the op row instead of buried in clearance prose.
_CRASH_ZONE_MM = 3.0
# One printed coordinate, e.g. "-155.000": a cell that must never wrap. Whole numbers
# (op and pass numbers) keep their plain cells, except in a coordinate table: its
# auto-sized columns would squeeze a move number to one digit a line.
_NUMBER = re.compile(r"[-−+]?\d+\.\d+")
_WHOLE = re.compile(r"\d+")
_READING_VALUE = r"[-−+±]?(?:(?:\d+\s+)?\d+/\d+|\d+(?:\.\d+)?|\.\d+)"
_READING_UNITS = r"(?:\s*(?:(?:mm|in)(?:/(?:rev|min))?|rpm|sfm|°)(?!\w))?"
_READING = re.compile(
    r"\?M\d+\b|"
    r"\b(?:cw|ccw)\b|"
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
    "joint_fit": "joint fit",
    "joint_assembly": "assembly geometry",
    "joint_thread": "threaded joint",
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
    "swivel": "vise swivel setting",
    "hold_fields": "holding details",
    "centre_support": "tailstock centre",
    "tooling_hole": "tooling hole / locating pin",
    "prepared_blank": "squared blank size",
    "parting_face": "parted end",
    "order": "op order",
    "op_chain": "op sequence",
    "construction": "construction",
    "engagement": "cutter engagement",
    "saw_cut": "saw cut",
    "saw_teeth": "saw teeth in the work",
    "keep_piece": "kept piece / offcut",
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
_MILL_SHORT_SENSE = {
    ("x", "+"): "tool right / table left",
    ("y", "+"): "tool away / table toward you",
    ("z", "+"): "tool up",
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
    "mounted_saw_side": "touch the flat blade-body side; Z reads the cutting-band midplane",
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
    "profiled_blank": "profiled blank",
}
# Stock / stock-state keys that place solids for the kernel; not bench instructions.
_PLACEMENT_KEYS = {"origin_mm", "axis", "section_axis", "as_is_faces", "id", "components"}
# A hand-fed cut's declared start end and end-of-cut support, as the HOLD prints them.
_FEED_ENDS = frozenset({"+X", "-X", "+Y", "-Y"})
# A coordinate in authored prose: an axis letter then a number or a +/- span, not the
# "x" of a "70 x 50" size (#335).
_PROSE_COORDINATE = re.compile(r"(?i)(?<!\d )(?<!\d)\b[xyz]\s*(?:\+/\s*-|±|[-+−]?\d)")
_END_SUPPORT = {
    "push_aid": "End of the cut: finish it with the push aid, never the hands.",
    "outfeed_table": "End of the cut: the outfeed table carries the work off the blade.",
}
# A ``hold.clamps`` label's role word in the HOLD text (see clamp_labels).
_CLAMP_ROLES = {"C": "clamp", "LOC": "locator", "SUP": "support"}
# Machine kinds whose top a shop-made fixture's base stands on, in shop words.
_FIXTURE_SURFACES = {"mill": "table", "drill_press": "table", "bench": "bench"}
# Ops a tool cuts along its own axis: no feed direction; on a lathe, a tailstock tool
# whose cutting hand (right- or left-hand cut) decides the spindle's turn.
_AXIAL_OPS = {"spot", "center_drill", "drill", "ream", "counterbore", "countersink"} | TAP_OPS
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


# Authored fixture dimensions are expected make-to-drawing settings, not observations.
EXAMPLE_MARK = "†"
EXAMPLE_LEGEND = (
    f"{EXAMPLE_MARK} Make-to-drawing expected settings; check the physical fixture as made "
    "before use. These settings do not clear installed-measurement STOPs."
)


def _example(record):
    """A primitive or length whose own provenance cannot certify a shop measurement."""
    measured = _mapping(record).get("measured")
    return isinstance(measured, dict) and measured.get("status", "assumed") != "measured"


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


def finding_decision(finding, bundle) -> Literal["block", "caution", "none"]:
    """Project the canonical readiness policy, never an instruction's wording."""
    status = _status(finding)
    if status == Status.ERROR or _mapping(_field(finding, "numbers")).get("kernel_unavailable"):
        return "block"
    if status in {Status.WARN, Status.UNKNOWN, Status.UNSUPPORTED}:
        return "block" if is_required(finding, bundle.policy, bundle) else "caution"
    return "none"


@dataclass(frozen=True)
class _Decision:
    source: str
    status: str
    scope: str | None
    kind: Literal["block", "caution", "none"]
    text: str
    notice_group: str = ""


# How a traveler names a joint's assembly action ("Joined by slip fit with ...").
_JOINED_BY = {"silver_braze": "silver braze", "slip": "slip fit", "press": "press fit"}


def _bonding_op(setup, op):
    """Whether ``op`` is the first ``fit`` op of a compound joint setup: the op that applies
    the compound, so its consumable cell names it and its note carries prep and cure."""
    joint = _mapping(setup.get("joint"))
    fits = [o for o in setup.get("ops", []) if o.get("do") == "fit"]
    return bool(_mapping(joint.get("compound"))) and bool(fits) and fits[0] is op


def _compound_lead(joint, fitted):
    """Opens a compound joint's "... not disturb until cured" sentence."""
    if joint["method"] == "press":
        return "Press in with the compound on the interface, then do"
    if fitted:
        return "Do"
    return "Apply the retaining compound, assemble, then do"


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


def _carried(row):
    """Whether a zero_check row's Axis Set is a carried setting: the rule already put the
    height plus paper on this setup's safe-down grid (``setting_residual_mm`` names the
    nonnegative physical residual it retains), so the sheet prints that setting as the report
    carries it and never moves it again. Any other row's setting still follows the
    surface as this setup's DRO shows it (:meth:`_Traveler.datum_z`)."""
    return isinstance(row, dict) and "setting_residual_mm" in row


def _touch_outside(row):
    """Where a credited Z touch may land (zero_check ``touch_exclusion_dia_mm``): the
    complete circular footprint about the faced surface's axis that its cut and every
    intervening axial plunge may have taken, cutter radius and aim shift included, as a
    diameter in physical mm whatever the plan's units. The diameter prints rounded
    outward to 0.001 mm (:func:`_outward_mm`) so the printed circle never admits a
    touch the rule excluded. An absent field, or a zero one (the face was cut before any
    bounded axial plunge: nothing to keep off), is no exclusion and prints nothing; a
    field that is present but not a non-negative length prints the constraint with its
    Ø unknown, never as a number."""
    if not isinstance(row, dict) or "touch_exclusion_dia_mm" not in row:
        return None
    dia = row["touch_exclusion_dia_mm"]
    if _known(dia) and dia == 0:
        return None
    if not (_known(dia) and dia > 0):
        return "touch the face outside its cut footprint (Ø ? mm)"
    return f"touch the face outside Ø{_outward_mm(dia)} mm"


def _outward_mm(value):
    """A known positive mm length as text on the 0.001 mm grid, rounded outward (up): the
    exact decimal ceiling of the number's own decimal spelling, in integer arithmetic
    (no float product, no decimal-context precision), so neither float residue
    (1.0000000001 → 1.001, not 1.000) nor significant-digit display (1234.5608 →
    1234.561, not 1234.56) brings it back inward, and an integer or huge value prints
    every digit unchanged; only trailing fractional zeros are trimmed (11.570 → 11.57,
    12.000 → 12)."""
    if isinstance(value, int):
        return str(value)
    _, digits, exponent = Decimal(repr(float(value))).as_tuple()
    coefficient = int("".join(map(str, digits)) or "0")
    shift = exponent + 3  # value = coefficient × 10**exponent; steps are 0.001 mm
    steps = coefficient * 10**shift if shift >= 0 else -(-coefficient // 10**-shift)
    whole, fraction = divmod(steps, 1000)
    return f"{whole}.{fraction:03d}".rstrip("0").rstrip(".")


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
    """Residual-stock verb phrase; its caption supplies the subject and punctuation."""
    left = _number(arc.get("stock_left_mm"), 3)
    recut = arc.get("recut_by")
    if isinstance(recut, str) and recut:
        return f"leaves at most {left} mm for {recut}"
    return f"leaves at most {left} mm for the file (cap {_number(arc.get('stock_cap_mm'))} mm)"


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


def _numbered_names(names, separator=", "):
    """Join names; three or more truly consecutive identities that differ only in one
    integer (``rail hole 1`` … ``rail hole 7``) print as one range. Gaps, other names and
    zero-padded numbers keep their own entries in order."""
    entries, run = [], []

    def flush():
        if len(run) >= 3:
            prefix, first, suffix, _ = run[0]
            entries.append(f"{prefix}{first}–{run[-1][1]}{suffix}")
        else:
            entries.extend(name for *_, name in run)
        run.clear()

    for name in names:
        match = re.fullmatch(r"(.*\D|)(\d+)(\D*)", str(name))
        number = int(match[2]) if match and str(int(match[2])) == match[2] else None
        if number is None:
            flush()
            entries.append(str(name))
            continue
        if run and (run[-1][0], run[-1][2], run[-1][1] + 1) != (match[1], match[3], number):
            flush()
        run.append((match[1], number, match[3], str(name)))
    flush()
    return separator.join(entries)


def _authored_rpm_stop(numbers):
    """The one operator STOP for an unresolved authored spindle-speed request."""
    requested = numbers.get("requested_rpm")
    speed = f"{_number(requested)} rpm requested" if _known(requested) else "requested RPM unknown"
    return f"STOP: {speed}. {numbers.get('rpm_reason')}"


# Compact zero_check projection: routine procedure sentences the datum block already
# teaches, and the recursive face-provenance sentence the report keeps (rules.zero_recipe).
_ZERO_ROUTINE = (
    "Touch, Axis Set the compensated value, then jog without retouching and compare "
    "expected versus mirrored readings.",
    " Each tool change is touched off on the last touched or faced surface still standing.",
)
_ZERO_UNVERIFIED = " Measured setup/tool or trial-cut verification remains unknown."
_ZERO_FACE_UNKNOWN = (
    (
        " A Z touch meets a face its op left at an unknown Z (",
        "A Z touch meets a face its op left at an unknown height",
    ),
    (
        " A Z touch cannot be certified on an unverified DRO grid (",
        "A Z touch cannot be certified on an unverified DRO grid",
    ),
)
_ZERO_FACE_TAIL = "): its Axis Set is not known."
# Producer zero facts that restate an unknown Axis Set the zero_check hold already lists.
_ZERO_SETTING = "zero-setting"


def _authoring_phrases(label):
    """``(exact instruction phrase, operator words)`` for the Z/XY geometry authoring
    debts of one op ``label`` (``plan.setups.<id>.ops.<op>``), as rules._envelope
    ``_z_extent`` and rules.travel write them; the field paths stay in report.json."""
    return (
        (
            f"Measure {label} current stock top from the setup datum with a height gauge or "
            "touch-off; record plan.setups.stock_state.top_z in mm",
            "stock top Z",
        ),
        (
            f"Author {label}.approach_mm >= 0 in mm above the current stock top "
            "from the intended safe Z approach; no approach is assumed",
            "safe approach height",
        ),
        *(
            (
                f"Measure {label}.{field} from the setup datum using the machine Z "
                "readout or depth gauge and record the commanded target in mm",
                f"{field} target",
            )
            for field in ("to_z", "z_from", "z_to")
        ),
        (
            f"Measure {label} hole entry and local thickness/depth with a depth gauge, "
            "drill point or reamer lead with an optical comparator, and exit allowance "
            "in mm; record stock_state.entry_z/local_thickness and operation depth_mm/exit_mm",
            "hole entry, local thickness and exit allowance",
        ),
        (
            f"Measure {label}.depth_mm and local entry using a depth gauge or machine "
            "Z readout; record a nonnegative depth and entry_z in mm",
            "depth and local entry",
        ),
        (
            f"Measure and declare {label} commanded to_z, z_from/z_to or depth_mm from "
            "the setup datum with a depth gauge or machine Z readout in mm",
            "commanded Z target",
        ),
        (
            f"Author {label}.do and setup-datum Z geometry with features.units = mm",
            "action and Z geometry in mm",
        ),
        (
            f"Measure and author {label}.stock_removal_bounds as the actual full "
            "removal footprint in the setup frame with calipers, a height gauge "
            "or CMM in mm. ",
            "removal footprint",
        ),
        (
            f"Declare {label} full cutter-centre X/Y path, including approach and "
            "exit, with a contour the traveler prints; the finished feature bounds "
            "and the material-removal box do not establish that path",
            "full cutter-centre X/Y path",
        ),
        (
            f"Author {label} feature.bounds x/y in its declared frame (or a "
            "contour the traveler prints as a cutter-centre path): the stock span "
            "is only a lower bound and does not include the cutter's approach and "
            "exit",
            "feature X/Y bounds or cutter-centre path",
        ),
        (
            f"Measure {label} full feature.bounds x/y/z or point-operation feature.at "
            "in its declared frame with calipers, a height gauge or CMM, in mm",
            "feature bounds or position",
        ),
        (
            "; for a broad cut record plan.stock.length_mm and "
            "section_mm/dia_mm with calipers instead of using a nominal feature width",
            "stock length and section",
        ),
    )


class _Box(str):
    """A producer-owned adverse fact, not a STOP inferred from printed prose."""

    def __new__(
        cls,
        text,
        *,
        source="producer",
        status="unknown",
        kind="block",
        scope="",
        decision_text=None,
        notice_group="",
    ):
        value = super().__new__(cls, text)
        value.source, value.status, value.kind = source, status, kind
        value.scope = scope
        value.decision_text = text if decision_text is None else decision_text
        value.notice_group = notice_group
        return value


class _Unverified(str):
    """One fact-local table value in the existing dashed Not verified style."""


class _FixtureFeature(str):
    """One unchanged fixture-feature identity and its complete location/depth clause."""


# Every lathe X reading is a radius or a diameter: unread, each number is half or twice
# the cut on the other display, so none prints.
_X_DISPLAY_STOP = "STOP: X display not set: X reads radius or diameter"


class _Plain(str):
    """A full-width line under a table row printed as plain text, not a warning box."""


class _Note(str):
    """An original note with repeatable identity and an optional requirement-owned sketch."""

    def __new__(cls, text, context=None, sketch=""):
        note = super().__new__(cls, text)
        note.context = context
        note.sketch = sketch
        return note


class _Criterion(str):
    """A complete displayed criterion with producer-owned parts for compact layout."""

    def __new__(
        cls, text, *, heading="", value=None, methods=(), context="", subjects=(), expanded=None
    ):
        criterion = super().__new__(cls, text)
        criterion.heading = heading
        criterion.value = value
        criterion.methods = methods
        criterion.context = context
        criterion.subjects = tuple(subjects)
        criterion.expanded = text if expanded is None else expanded
        return criterion


class _OperationNote(_Note):
    def __new__(cls, text, authored_note, derived):
        value = super().__new__(cls, text)
        value.authored_note, value.derived = authored_note, derived
        return value


@dataclass(frozen=True)
class _Inspection:
    """Authored criteria and their physical result owner, never an acceptance mark."""

    text: str
    features: tuple[str, ...]
    requirement: str
    unit: str = ""
    qualitative: bool = False
    methods: tuple = ()
    reading_owned: bool = False
    subjects: tuple[str, ...] = ()
    setup_id: str | None = ""
    op_id: int | None = None
    workpiece: str | None = None
    shared_check_id: str | None = None
    covered_workpieces: tuple[str, ...] = ()
    # Each tuple is (canonical gauge identity, display name, complete criterion).
    compact_criteria: tuple = ()


@dataclass(frozen=True)
class _CutDepths:
    """Operation facts only; audience formatting never parses authored prose."""

    verb: str
    rough_diameter_mm: float | None
    allowances: tuple
    passes: tuple
    doc: tuple | None


@dataclass(frozen=True)
class _Block:
    key: str
    html: str
    comparison: object = None
    records: tuple[_Inspection, ...] = ()
    setup_id: str | None = ""
    workpiece: str | None = None
    shared_html: str = ""
    op_id: int | None = None
    decisions: tuple[_Decision, ...] = ()
    layout: str = "block"


class _Row(tuple):
    """Table cells plus full-width warnings printed beneath the row."""

    def __new__(
        cls,
        cells,
        warnings=(),
        *,
        setup_id="",
        op_id=None,
        workpiece=None,
        decisions=(),
    ):
        row = super().__new__(cls, cells)
        row.warnings = tuple(dict.fromkeys(warnings))
        row.setup_id, row.op_id, row.workpiece = setup_id, op_id, workpiece
        row.decisions = tuple(decisions)
        return row


def _numeric_html(text):
    """Escape source text without splitting a signed numeric value from its units."""
    text = str(text)
    parts, end = [], 0
    for reading in _READING.finditer(text):
        parts.append(escape(text[end : reading.start()]))
        marker = reading.group()
        attribute = (
            f' class="measurement-ref" data-measurement-ref="{escape(marker[1:])}"'
            if marker.startswith("?M")
            else ' class="reading"'
        )
        parts.append(f"<span{attribute}>{escape(marker)}</span>")
        end = reading.end()
    parts.append(escape(text[end:]))
    return "".join(parts)


def _p(text, css=""):
    attribute = f' class="{css}"' if css else ""
    return f"<p{attribute}>{_numeric_html(text)}</p>"


def _cell_line(line):
    if isinstance(line, _Box):
        # Split raw text before escaping: entity terminators in generated HTML
        # are not source delimiters. Retain every delimiter and whitespace run.
        text, clauses, start = str(line), [], 0
        for delimiter in re.finditer(r";\s*(?=[^;\s])", text):
            if re.search(r"[^;\s]", text[start : delimiter.start()]):
                clauses.append(text[start : delimiter.end()])
                start = delimiter.end()
        clauses.append(text[start:])
        body = (
            _numeric_html(text)
            if len(clauses) == 1
            else "".join(
                f'<span class="warning-clause">{_numeric_html(clause)}</span>' for clause in clauses
            )
        )
        return f'<span class="box">{body}</span>'
    if isinstance(line, _FixtureFeature):
        return f'<span class="fixture-feature">{_numeric_html(line)}</span>'
    if isinstance(line, _Unverified):
        return f'<span class="unverified">{_numeric_html(line)}</span>'
    return _numeric_html(line)


def _writing_field(label, css="field", *, punctuation=""):
    label_html = (
        '<span class="reading">cw</span>/<wbr><span class="reading">ccw</span>'
        if label == "cw/ccw"
        else _numeric_html(label)
    )
    caption = f'<span class="field-label">{label_html}</span>' if label else ""
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


def _decision_groups(decisions, *, combine_notices=False):
    """Print the highest-severity notice once, retaining every original decision."""
    groups = {}
    for decision in dict.fromkeys(decisions):
        key = (
            ("notice", decision.scope, decision.notice_group)
            if combine_notices
            and decision.notice_group
            and decision.scope
            and decision.kind == "caution"
            and decision.status == "warn"
            else ("text", decision.text)
        )
        groups.setdefault(key, []).append(decision)
    kinds = {"none": 0, "caution": 1, "block": 2}
    statuses = {
        "pass": 0,
        "not_applicable": 0,
        "warn": 1,
        "unknown": 2,
        "unsupported": 2,
        "error": 3,
    }
    return [
        sorted(
            group,
            key=lambda fact: (kinds[fact.kind], statuses.get(fact.status, 2)),
            reverse=True,
        )
        for group in groups.values()
    ]


def _decision_evidence(decisions):
    return escape(
        json.dumps(
            [
                {
                    "source": fact.source,
                    "status": fact.status,
                    "scope": fact.scope,
                    "kind": fact.kind,
                }
                for fact in decisions
            ]
        )
    )


def _decision_text(decision, related=()):
    if decision.notice_group:
        return "; ".join(dict.fromkeys(fact.text for fact in (decision, *related)))
    return decision.text


def _decision_html(decision, related=(), *, setup_id=None, op_id=None, owners=(), layout="block"):
    return _decision_box(
        [(decision, *related)], setup_id=setup_id, op_id=op_id, owners=owners, layout=layout
    )


def _decision_box(groups, *, setup_id=None, op_id=None, owners=(), layout="block"):
    """One notice for decision groups of one owner and kind: each group's text is its own
    paragraph, an action label repeats no paragraph above it, and every fact is evidence."""
    decision = groups[0][0]
    if decision.kind == "none":
        return ""
    css = "stop" if decision.kind == "block" else "caution"
    owner = (
        f' data-setup-id="{escape(str(setup_id))}"'
        f' data-op="{escape(str(op_id)) if op_id is not None else ""}"'
        if setup_id is not None
        else ""
    )
    if owners:
        setup_ids = list(dict.fromkeys(item["setup_id"] for item in owners))
        op_ids = {item["op_id"] for item in owners}
        owner = (
            f' data-setup-id="{escape(str(setup_ids[0])) if len(setup_ids) == 1 else ""}"'
            f' data-setup-members="{escape(json.dumps(setup_ids))}"'
            f' data-op="{escape(str(next(iter(op_ids)))) if len(op_ids) == 1 else ""}"'
            f' data-physical-ops="{escape(json.dumps(owners))}"'
        )
    tag = "span" if layout == "inline" else "div"
    texts, labels = [], set()
    for group in groups:
        text = _decision_text(group[0], group[1:])
        label = re.match(r"(?:STOP|HOLD|CAUTION): ", text)
        if label and label[0] in labels:
            text = text[len(label[0]) :]
        elif label:
            labels.add(label[0])
        texts.append(text)
    facts = [fact for group in groups for fact in group]
    return (
        f'<{tag} class="decision {css}" data-decision="{decision.kind}" '
        f'data-source="{escape(decision.source)}" data-status="{escape(decision.status)}" '
        f'data-scope="{escape(decision.scope or "")}" '
        f'data-decision-evidence="{_decision_evidence(facts)}"{owner}>'
        + (
            _numeric_html(texts[0])
            if layout == "inline"
            else "".join(_p(text) for text in dict.fromkeys(texts))
        )
        + f"</{tag}>"
    )


def _typed_values(values, scope):
    for value in values:
        if isinstance(value, (list, tuple)):
            yield from _typed_values(value, scope)
        elif isinstance(value, _Box):
            yield _Decision(
                value.source,
                value.status,
                value.scope or scope,
                value.kind,
                value.decision_text,
                value.notice_group,
            )
        elif isinstance(value, _Unverified):
            yield _Decision("measurement", "unknown", scope, "block", str(value))


def _inspection_identity_attributes(subjects):
    return f'data-inspection-ids="{escape(json.dumps(subjects))}"'


def _inspection_gauge_groups(check):
    groups = {}
    for gauge_id, gauge, criterion in check.compact_criteria:
        groups.setdefault((gauge_id, gauge), []).append(criterion)
    return groups


def _inspection_criteria(checks, *, compact=False):
    """Keep criterion identity separate from physical recording-field ownership."""
    for check in checks:
        if isinstance(check, _Criterion):
            yield check
        elif isinstance(check, _Inspection):
            if check.compact_criteria:
                criteria = (
                    (
                        criterion
                        for group in _inspection_gauge_groups(check).values()
                        for criterion in group
                    )
                    if compact
                    else (criterion for _, _, criterion in check.compact_criteria)
                )
                for criterion in criteria:
                    yield (
                        criterion
                        if isinstance(criterion, _Criterion)
                        else _Criterion(criterion, subjects=check.subjects, expanded=check.text)
                    )
            else:
                yield _Criterion(check.text, subjects=check.subjects)


def _criterion_html(criterion, text=None, *, formatter=_numeric_html):
    return (
        '<span class="inspection-criterion" '
        + _inspection_identity_attributes(criterion.subjects)
        + ">"
        + formatter(str(criterion) if text is None else text)
        + "</span>"
    )


def _inspection_attributes(check):
    owner = (
        "Batch " + ", ".join(check.covered_workpieces)
        if check.shared_check_id
        else check.workpiece or ""
    )
    title = " ".join(filter(None, [owner, ", ".join(check.features), check.requirement]))
    return (
        f'data-feature="{escape(", ".join(check.features))}" '
        f'data-features="{escape(json.dumps(check.features))}" '
        f'data-requirement="{escape(check.requirement)}" '
        f"{_inspection_identity_attributes(check.subjects)} "
        f'data-setup-id="{escape(check.setup_id or "")}" '
        f'data-op-id="{escape(str(check.op_id) if check.op_id is not None else "")}" '
        f'data-workpiece="{escape(check.workpiece or "")}" '
        f'data-member="{escape(check.workpiece or "")}" '
        f'data-shared-check="{escape(check.shared_check_id or "")}" '
        f'data-covered-workpieces="{escape(json.dumps(check.covered_workpieces))}" '
        f'data-record-title="{escape(title)}"'
    )


def _inspection_method(method, *, layout="block", label="inline"):
    content = (
        _worksheet(method)
        if isinstance(method, _Steps) and _readings(method[1]) and len(method[2]) >= 2
        else _item(method)
    )
    context = method[0] if isinstance(method, _Steps) else getattr(method, "context", None)
    if (
        label == "criterion"
        and isinstance(method, _Note)
        and context
        and str(method).startswith(context)
        and not getattr(method, "sketch", "")
    ):
        content = _fields(str(method)[len(context) :])
    attribute = f' data-page-context="{escape(context)}"' if context else ""
    tag = (
        "span"
        if layout == "inline"
        and not isinstance(method, _Steps)
        and not getattr(method, "sketch", "")
        and not _FIELD.search(str(method))
        else "div"
    )
    return (
        f'<{tag} class="inspection-method"{attribute}>'
        + content
        + f"</{tag}>"
        + (" " if tag == "span" else "")
    )


def _inspection_html(check, *, result=True):
    return (
        '<div class="inspection-layout"><div class="inspection-requirement">'
        + "<p>"
        + "; ".join(
            _criterion_html(criterion, criterion.expanded)
            for criterion in _inspection_criteria((check,))
        )
        + "</p>"
        + "</div>"
        + "".join(_inspection_method(method) for method in check.methods)
        + (
            _writing_field("Result / observations", "result-field")
            if result and not check.reading_owned
            else ""
        )
        + "</div>"
    )


def _checkpoint_results(records):
    owners = [
        "Batch — " + ", ".join(check.covered_workpieces)
        if check.shared_check_id
        else check.workpiece or f"{check.setup_id} op {check.op_id}"
        for check in records
    ]
    cells = []
    for check, owner in zip(records, owners, strict=True):
        if check.reading_owned:
            continue
        if owners.count(owner) > 1:
            criterion = "; ".join(
                dict.fromkeys(
                    criterion.heading
                    for criterion in _inspection_criteria((check,))
                    if criterion.heading
                )
            ) or _REQUIREMENT_NAMES.get(check.requirement, _text(check.requirement))
            owner += " — " + criterion
        cells.append(
            f'<div class="checkpoint-result" {_inspection_attributes(check)}>'
            + _writing_field(owner, "result-field")
            + "</div>"
        )
    return "".join(
        '<div class="checkpoint-results">' + "".join(cells[start : start + 4]) + "</div>"
        for start in range(0, len(cells), 4)
    )


def _ledger_row(
    row, headings, *, detail="pedantic", show_settings=True, results=True, note_transform=None
):
    def authored_text(value):
        text = note_text(value, detail=detail)
        return note_transform(text) if note_transform is not None else text

    finishing = len(row) == 5
    if finishing:
        op, feature, consumable, action, checks = row
        fields, labels, values = ("feature", "consumable"), headings[1:3], (feature, consumable)
        if hasattr(row, "authored_note"):
            projected = " ".join(
                filter(
                    None,
                    [
                        row.instruction_before,
                        authored_text(row.authored_note),
                        row.instruction_after,
                    ],
                )
            )
            action = projected or row.instruction_fallback
    else:
        op, action = row[:2]
        checks = row[8]
        fields = ("feature", "tool", "speed", "feed", "target", "direction")
        labels, values = headings[2:8], row[2:8]
    sid, member = getattr(row, "setup_id", "") or "", getattr(row, "workpiece", None)
    context = f"Setup {sid} op {op}" if sid else f"Operation {op}"
    result = [
        f'<tbody class="operation" data-op="{escape(op)}" data-setup-id="{escape(sid)}" '
        f'data-workpiece="{escape(member or "")}" data-operation-context="{escape(context)}" '
        f'data-decision-evidence="{_decision_evidence(getattr(row, "decisions", ()))}">'
        '<tr class="operation-main"><td><div class="op-head">',
        (
            '<span class="performed-mark" role="img" '
            f'aria-label="Operation {escape(op)} performed mark"></span>'
            if detail == "pedantic"
            else ""
        ),
        f'<h3><span class="op-number">{"Step" if finishing else "Op"} {escape(op)}</span>'
        + (
            "</h3></div>" + f'<div class="op-action">{_action_body(action)}</div>'
            if finishing
            else f' — <span class="op-action">{_ledger_text(action)}</span></h3></div>'
        ),
        '<dl class="op-details">',
    ]
    for name, heading, value in zip(fields, labels, values, strict=True):
        if value in (None, "", "—", [], ()):
            continue
        if name in {"speed", "feed"} and not show_settings:
            continue
        if (
            name in {"tool", "consumable"}
            and detail != "pedantic"
            and getattr(row, "tool_label", None)
        ):
            value = row.tool_label
        result.append(
            f'<div class="op-{name}"><dt>{escape(heading)}</dt><dd>{_ledger_text(value)}</dd></div>'
        )
    result.append("</dl></td></tr>")
    for warning in row.warnings:
        if isinstance(warning, _OperationNote):
            text = " ".join(filter(None, [authored_text(warning.authored_note), warning.derived]))
            if not text:
                continue
            warning = _Note(text)
        result.append(f'<tr class="warn"><td>{_warning_line(warning)}</td></tr>')
    for check in checks:
        if isinstance(check, _Inspection):
            result.append(
                f'<tr class="inspection-record" {_inspection_attributes(check)} '
                f'data-page-context="{escape(context)}"><td>'
                + _inspection_html(check, result=results)
                + "</td></tr>"
            )
        elif isinstance(check, (_Note, _Steps)):
            result.append(
                f'<tr class="inspection-procedure" data-page-context="{escape(context)}"><td>'
                + _inspection_method(check)
                + "</td></tr>"
            )
        else:
            result.append(
                '<tr class="inspection-message"><td>'
                + (
                    _criterion_html(check, formatter=_ledger_text)
                    if isinstance(check, _Criterion)
                    else _ledger_text(check)
                )
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
                if parts and not isinstance(line, (_Box, _Unverified)):
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
    def __init__(self, bundle, findings, report, approval, *, detail: TravelerDetail = "pedantic"):
        if detail not in TRAVELER_DETAILS:
            raise ValueError("detail must be pro, hobby, or pedantic")
        self.detail = detail
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
        self.finding_statuses = {
            (_field(f, "rule"), _field(f, "subject")): _status(f) for f in self.findings
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
                self.frames.setdefault(frame, []).append(_text(setup["id"]))
        self.setup = None
        self.setup_stops = {}
        self._job_measurements = {}
        self.measurement_sources = {}
        self.setup_measurement_ids = {}
        self.setup_decisions = {}
        self.producer_decisions = {}
        self._rows_by_setup = {}
        self._blocks_by_setup = {}
        self._saw_cycle_homes = {}
        self._route_hold_steps = {}
        self._route_hold_facts = {}
        self._route_cycles = {}
        self._route_picture_setups = set()
        self._route_contours = {}
        self._route_facing_paths = {}
        self._route_datum_axes = {}
        self._route_cut_direction = {}
        self._route_shared_warnings = {}
        self._front_reference_layout = False
        self._front_dro_guide = ""
        self.settings_active = False
        self.route_tool_labels = {}
        for setup in self.plan.get("setups", []):
            for op in setup.get("ops", []):
                reference = op.get("tool")
                if reference in (None, "unknown"):
                    continue
                tool = _mapping(resolve(self.bundle, "tools", reference))
                if op.get("do") in MANUAL and not _known(_amount(tool.get("lead_mm"))):
                    continue
                key = identity(self.bundle, reference, "tools")
                self.route_tool_labels.setdefault(key, f"T{len(self.route_tool_labels) + 1}")

        # Ops of the current setup with a block on its contour sheet; set by contours().
        self.contour_ops = set()
        self.sweep_ops = set()  # those whose block is a guided sweep's recipe
        # (shop-made reference, its poses) -> first setup carrying its table.
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

    def record_decision(self, setup, *, source, status, scope, text, kind="block", notice_group=""):
        if not hasattr(self, "producer_decisions"):
            self.producer_decisions = {}
        decision = _Decision(source, status, scope, kind, text, notice_group)
        decisions = self.producer_decisions.setdefault(setup["id"], [])
        if decision not in decisions:
            decisions.append(decision)

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
        """How a joint setup joins its two received branches: method, compound, process and
        the declared fit band; with a compound, surface prep and the undisturbed cure too,
        unless a ``fit`` op does the join: then they print once, on that op
        (:meth:`compound_note`), and the arrival line never repeats them."""
        joint = _mapping(setup.get("joint"))
        if not joint:
            return ""
        if joint["kind"] == "threaded":
            return (
                f" Screw {self.feature_name(joint['spigot'])} into "
                f"{self.feature_name(joint['socket'])} as a removable threaded assembly "
                f"({self.bench(joint['process'], setup)}). No bonding or press fit is specified."
            )
        compound = _mapping(joint.get("compound"))
        method = _JOINED_BY.get(joint["method"]) or _text(joint["method"])
        text = f" Joined by {method}"
        if compound:
            text += f" with {self.compound_product(setup, compound)}"
        text += f" ({self.bench(joint['process'], setup)})"
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
        if compound and not fitted:
            text += " " + self.compound_text(setup, joint, fitted=False)
        return text

    def compound_product(self, setup, compound):
        """The compound's product name, an unknown one printed as unknown."""
        product = compound.get("product")
        if not isinstance(product, str) or not product.strip() or product == "unknown":
            return "compound ? UNKNOWN (not declared)"
        return self.bench(product, setup).rstrip(".")

    def compound_text(self, setup, joint, *, fitted):
        """A compound joint's surface prep and undisturbed cure, an unknown one printed as
        unknown. A press fit is pressed in with the compound on the interface; a slip fit
        is assembled with it by its ``fit`` op, else as this text says."""
        compound = _mapping(joint.get("compound"))
        prep, cure = compound.get("surface_prep"), compound.get("cure_time_min")
        known_prep = isinstance(prep, str) and prep.strip() and prep != "unknown"
        return (
            "Surface prep: "
            + (
                f"{self.bench(prep, setup).rstrip('.')}."
                if known_prep
                else "? UNKNOWN (not declared)."
            )
            + f" {_compound_lead(joint, fitted)} not disturb until cured: "
            + (
                f"cure time {_number(cure)} min."
                if _known(cure)
                else "cure time ? min UNKNOWN (not declared)."
            )
        )

    def keep_note(self, setup, op):
        """An op's ``keep``: which separated piece the operator keeps and that every other
        is scrap, with the count the kernel discarded when ``keep_piece`` passed."""
        feature = op.get("keep")
        if not feature:
            return None
        numbers = self.records.get(("keep_piece", f"{setup['id']}:{op['op']}"), {})
        discarded = numbers.get("discarded") if isinstance(numbers, dict) else None
        count = len(discarded) if isinstance(discarded, list) else 0
        scrap = (
            "discard the other piece"
            if count == 1
            else f"discard the other {count} pieces"
            if count
            else "discard every other piece"
        )
        return f"Keep the piece that carries {self.feature_name(feature)}; {scrap}."

    def compound_note(self, setup, op):
        """The first ``fit`` op of a compound joint setup carries the joint's surface prep
        and undisturbed cure (the arrival line then leaves them out)."""
        if not _bonding_op(setup, op):
            return None
        return self.compound_text(setup, setup["joint"], fitted=True)

    def joint_debt(self, setup):
        """The joint's own declared facts left unknown: the join is withheld, never assumed."""
        joint = _mapping(setup.get("joint"))
        if not joint:
            return ""
        if joint["kind"] == "threaded":
            return _Box(
                "STOP: actual thread fit, engagement, runout clearance and shoulder seating "
                "are not established by the nominal cylindrical model. The checker has no "
                "proved joined stock; downstream assembly machining remains on HOLD. "
                "Confirm the real thread and seating before assembly; no strength or "
                "retention certification is implied.",
                source="joint_stock",
                scope=setup["id"],
            )
        missing = []
        if joint["kind"] == "cylindrical" and joint.get(f"{joint['fit']}_mm") == "unknown":
            missing.append(f"{joint['fit']} band")
        compound = _mapping(joint.get("compound"))
        missing.extend(
            name
            for key, name in (
                ("product", "compound product"),
                ("surface_prep", "surface prep"),
                ("cure_time_min", "cure time"),
            )
            if compound.get(key) == "unknown"
        )
        if not missing:
            return ""
        return _Box(
            f"STOP: joint facts unknown — {', '.join(missing)}. The join is not checked; "
            "do not assemble until they are declared.",
            source="joint_stock",
            scope=setup["id"],
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
        if self.detail == "hobby" and not lathe:
            words = _MILL_SHORT_SENSE.get((axis, sign), words)
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
        """Machine targets and clearances round at the setup's DRO resolution (or
        ``decimals`` for another machine), omitting insignificant fractional zeroes."""
        if isinstance(value, (list, tuple)):
            return " / ".join(self.operative(v, decimals) for v in value)
        if isinstance(value, dict) and "value" in value:
            value = value["value"]
        precision = self.decimals if decimals is None else decimals
        if _known(value) and isinstance(precision, int):
            from prechips.kernel.render_diagram import operative_text

            return operative_text(value, precision)
        return _number(value, precision)

    def readout(self, value):
        """Nominal setup lengths in display units, never a physical dial zero.

        Digital same-unit bundles retain their established rounding and bytes. An
        explicitly different unit converts the number as well as its label. Mechanical
        nominals are not rounded onto an unverified dial graduation.
        """
        if isinstance(value, (list, tuple)):
            return " / ".join(self.readout(v) for v in value)
        if isinstance(value, dict) and "value" in value:
            value = value["value"]
        if readout_kind(self.bundle) == "digital" and readout_units(self.bundle) == self.units:
            return self.operative(value)
        return _number(readout_value(self.bundle, value))

    def physical(self, value):
        """A carried surface's physical height, in plan units, at its own decimals and at
        least the DRO's: off this grid it prints every digit (21.0055), never rounded to
        a grid line it does not stand on; unknown stays ``?``."""
        if not _known(value):
            return _text(value)
        return self.operative(value, max(self.decimals, _places(value)))

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

    def inspection_band(self, feature, requirement):
        """A compact linear criterion in the job's units, never rounded outward."""
        value = self.features.get(feature, {}).get(requirement)
        band = self.band(value, feature, requirement)
        unit = (
            "°"
            if requirement.endswith("_deg")
            else self.units
            if requirement in TOLERANCE_REQUIREMENTS - {"finish_ra", "land_angle_deg"}
            and self.units in ("mm", "in")
            else ""
        )
        display = readout_units(self.bundle)
        if (
            self.detail != "pedantic"
            and requirement in LENGTH_REQUIREMENTS
            and self.units in ("mm", "in")
            and display in ("mm", "in")
            and display != self.units
            and isinstance(value, (list, tuple))
            and len(value) == 2
            and all(map(_known, value))
        ):
            limits = printed_band(value, self.precision(feature, requirement))
            limits = value if limits is None else limits
            converted = [readout_value(self.bundle, limit) for limit in limits]
            scale = 25.4 if self.units == "in" else 1.0
            inward = _inward(
                limits[0] * scale,
                limits[1] * scale,
                display,
                max(_places(limit) for limit in converted),
            )
            if inward is not None:
                band, unit = "–".join(inward), display
        if self.detail != "pedantic" and unit:
            band += " " + unit
        return band, unit

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
        label = reference_label(self.bundle, reference, slot)
        if self.detail != "pedantic" and self.plan.get("purpose") == "demonstration":
            label = label.removeprefix("Example ").removesuffix(" (example selection)")
        if self.detail != "pedantic":
            label = label.removesuffix(" (in-house)")
        return label

    def short_reference(self, reference, slot=None):
        return (
            self.reference(reference, slot)
            if self.detail != "pedantic"
            else short_reference_label(self.bundle, reference, slot)
        )

    def tool_name(self, reference):
        return tool_label(self.bundle, reference)

    def route_tool_name(self, reference):
        """The authored display name, without repeating its resolved size prefix."""
        item = _mapping(resolve(self.bundle, "tools", reference))
        name = item.get("name", item.get("label"))
        name = name if isinstance(name, str) and name.strip() else self.tool_name(reference)
        if self.plan.get("purpose") == "demonstration":
            name = name.removeprefix("Example ").removesuffix(" (example selection)")
        return name

    def route_tool_label(self, reference):
        return self.route_tool_labels.get(
            identity(self.bundle, reference, "tools"), self.route_tool_name(reference)
        )

    def measurement_registry(self):
        """One job-wide map, bound to canonical facts and composite physical leaves."""
        if not hasattr(self, "_job_measurements"):
            self._job_measurements = {}
            self.measurement_sources = {}
            self.setup_measurement_ids = {}
        return self._job_measurements

    def measurement_quantities(self, entry):
        """Split an aggregate fact without changing its provenance or trust."""
        if not {"id", "category", "identity", "field"} <= entry.keys():
            return []
        parts = entry["field"]
        if parts[0] != "solids" or entry.get("physical_field"):
            return [entry]
        item = measurement_item(self.bundle, entry["category"], entry["identity"])
        solid = next((s for s in item.get("solids") or [] if s.get("name") == parts[1]), {})
        fields = []
        if solid.get("shape") == "box":
            fields.extend(
                (("size_mm", axis), f"{name} along local {axis.upper()}", "calipers")
                for axis, name in zip("xyz", ("length", "width", "height"), strict=True)
            )
        elif solid.get("shape") == "cylinder":
            fields.extend(
                [
                    (
                        ("dia_mm",),
                        "bore diameter" if solid.get("void") else "diameter",
                        "bore gauge" if solid.get("void") else "micrometer or calipers",
                    ),
                    (
                        ("length_mm",),
                        "depth" if solid.get("void") else "axial length",
                        "depth gauge" if solid.get("void") else "calipers",
                    ),
                ]
            )
        if isinstance(solid.get("at_mm"), list) and len(solid["at_mm"]) == 3:
            anchor = "minimum corner" if solid.get("shape") == "box" else "base centre"
            fields.extend(
                (
                    ("at_mm", axis),
                    f"{anchor} local {axis.upper()} position from the fixture-local origin",
                    "height gauge",
                )
                for axis in "xyz"
            )
        if not fields:
            return [entry]
        label = self.bench(solid.get("label") or _solid_name(parts[1]))
        made = (item.get("shop_made") is True or item.get("kind") == "custom") and solid.get(
            "supply", "made"
        ) == "made"
        return [
            {
                **entry,
                "id": entry["id"] + "#" + ".".join(field),
                "binding": entry["id"],
                "physical_field": list(field),
                "dimension": f"{label} {description}",
                "shop_instruction": (
                    f"measure: its {label} {description}"
                    + (" as made" if made else "")
                    + f", {instrument}, mm"
                ),
                "units": "mm",
            }
            for field, description, instrument in fields
        ]

    def register_measurements(self, entries, setup=None):
        registry = self.measurement_registry()
        setup = setup or getattr(self, "setup", None)
        sid = _mapping(setup).get("id")
        for entry in entries:
            for quantity in self.measurement_quantities(entry):
                registry.setdefault(quantity["id"], (f"M{len(registry) + 1}", quantity))
                if sid:
                    self.setup_measurement_ids.setdefault(sid, set()).add(quantity["id"])
                    self.measurement_sources.setdefault(quantity["id"], set()).add(sid)

    def finalize_measurements(self, sheets):
        """Number once after all consumers have rendered; rewrite their short refs once."""
        registry = self.measurement_registry()
        ordered = sorted(registry.items())
        renumber = {marker: f"M{index}" for index, (_, (marker, _)) in enumerate(ordered, 1)}
        self._job_measurements = {
            key: (renumber[marker], entry) for key, (marker, entry) in ordered
        }
        pattern = re.compile(r"(?<=\?)M\d+\b|(?<=data-measurement-ref=\")M\d+\b")
        return [
            [
                [pattern.sub(lambda m: renumber.get(m[0], m[0]), block) for block in blocks]
                for blocks in setup_sheets
            ]
            for setup_sheets in sheets
        ]

    def dro_controller_name(self):
        """Use the model's casing from its existing manual title, not the plan key."""
        dro = _mapping(self.plan.get("dro"))
        controller = dro.get("controller")
        if controller in (None, "unknown"):
            return "DRO"
        manual = dro.get("manual")
        match = (
            re.search(rf"(?<!\w){re.escape(controller)}(?!\w)", manual, re.I)
            if isinstance(controller, str) and isinstance(manual, str)
            else None
        )
        return self.bench(match[0] if match else controller)

    def measurement_subject(self, entry, *, setup=None, include_holder=True):
        category, key = entry["category"], entry["identity"]
        if category == "machines" and entry["field"] == ["resolution"]:
            return self.dro_controller_name()
        name = self.reference(f"{category}.{key}", category)
        if category == "tools":
            reference = f"{category}.{key}"
            marks = []
            if self.detail != "pedantic":
                number = self.route_tool_labels.get((category, key))
                if number:
                    marks.append(number)
            elif setup is not None:
                holder = (
                    identity(self.bundle, entry["field"][1], "holders")
                    if entry["field"][0] == "projection" and len(entry["field"]) > 1
                    else None
                )
                marks.extend(
                    number
                    for (tool, selected_holder), number in tool_numbers(self.bundle, setup).items()
                    if tool == (category, key) and (holder is None or selected_holder == holder)
                )
            if marks and setup is not None:
                marks.insert(0, _text(setup["id"]))
            name = " ".join([*marks, self.tool_name(reference)])
        if include_holder and entry["field"][0] == "projection" and len(entry["field"]) > 1:
            name += " in " + self.reference(entry["field"][1], "holders")
        return name

    def measurement_dimension(self, entry):
        """Short dimension labels, not a second measurement-instruction source."""
        if entry.get("dimension"):
            return entry["dimension"]
        parts = entry["field"]
        item = measurement_item(self.bundle, entry["category"], entry["identity"])
        centre = item.get("kind") in {"center_drill", "center_drill_set"}
        labels = {
            "dia": "pilot Ø" if centre else "cutter Ø",
            "shank": "body Ø" if centre else "shank Ø",
            "oal": "overall length",
            "flute_len": "usable flute length",
            "pilot_len": "pilot length",
            "point_angle": "point angle",
            "angle_deg": "countersink angle",
            "lead": "reamer lead length",
            "nose_radius": "nose radius",
            "reach": "plunge reach",
            "blade_width": "blade width",
            "projection": "installed projection",
            "gauge_len": "holder gauge length",
            "gauge_dia": "holder outside Ø",
            "grip": "insertion length",
            "bed_height": "work-support height",
            "resolution": "readout step",
            "tip": "contacting-tip Ø",
            "jaw_height": "jaw height",
            "jaw_width": "jaw width",
            "jaw_depth": "jaw depth",
        }
        if parts[:2] == ["envelope", "travel"]:
            return f"{parts[-1].upper()} usable travel"
        if parts == ["envelope", "spindle_to_table_max"]:
            return "maximum spindle-to-table room"
        if parts == ["envelope", "spindle_to_table_min"]:
            return "minimum spindle-to-table room"
        if parts[0] == "solids":
            solid = next((s for s in item.get("solids") or [] if s.get("name") == parts[1]), {})
            return (
                self.bench(solid.get("label") or _solid_name(parts[1])) + " dimensions / position"
            )
        if parts[0] == "envelope":
            return " ".join(_text(part).replace("_", " ") for part in parts[1:])
        return labels.get(parts[0], " ".join(_text(part).replace("_", " ") for part in parts))

    def measurement_reference(self, entry):
        registry = self.measurement_registry()
        return " ".join(
            "?" + registry[q["id"]][0]
            for q in self.measurement_quantities(entry)
            if q["id"] in registry
        )

    def measurement_marker(self, entry):
        self.register_measurements([entry])
        return self.measurement_reference(entry)

    def measurement_record(self, entry):
        """The physical input context shared by full actions and short references."""
        category, key, field = entry["category"], entry["identity"], tuple(entry["field"])
        # Installed projection belongs to its selected holder; the controller readout
        # is not the machine envelope. Human names never determine record identity.
        context = (
            identity(self.bundle, field[1], "holders")
            if field[0] == "projection" and len(field) > 1
            else "readout"
            if category == "machines" and field == ("resolution",)
            else None
        )
        return category, key, context

    def measurement_lines(self, entries, setup=None):
        physical = [
            quantity
            for entry in {entry["id"]: entry for entry in entries}.values()
            for quantity in self.measurement_quantities(entry)
        ]
        groups = {}
        for entry in physical:
            # Register in original input order before grouping interleaved records.
            dimension = self.measurement_dimension(entry) + " " + self.measurement_marker(entry)
            groups.setdefault(self.measurement_record(entry), []).append((entry, dimension))
        return [
            self.measurement_subject(values[0][0], setup=setup)
            + " "
            + "; ".join(dimension for _, dimension in values)
            for values in groups.values()
        ]

    def measurement_stop(self, op, number, entry):
        if not {"category", "identity", "field"} <= entry.keys():
            return "planned input not established; return traveler for reissue"
        subject = self.measurement_subject(entry, setup=self.setup)
        if number and (entry["category"], entry["identity"]) == identity(
            self.bundle, op.get("tool"), "tools"
        ):
            label = self.route_tool_label(op["tool"]) if self.detail != "pedantic" else number
            subject = f"{label} {self.tool_name(op.get('tool'))}"
            if entry["field"][0] == "projection" and len(entry["field"]) > 1:
                subject += " in " + self.reference(entry["field"][1], "holders")
        return f"{subject} {self.measurement_dimension(entry)} " + self.measurement_marker(entry)

    def stock_dependency(self, setup):
        """The exported entry-stock prerequisite, not its diagnostic measurement union."""
        unresolved = [f for f in self.setup_findings(setup) if _status(f) == "unknown"]
        if not unresolved:
            return None
        kernel = _mapping(self.bundle.kernel)
        detail = _mapping(_mapping(kernel.get("setups")).get(setup["id"]))
        reason = detail.get("stock_reason")
        missing_entry = any(
            _field(f, "rule") == "consistency"
            and "the kernel gave no setup-entry stock box for this setup"
            in _field(f, "numbers", {}).get("unchecked", [])
            for f in unresolved
        )
        if not reason and not missing_entry:
            return None
        if not reason:
            return {"reason": "setup-entry stock is not established", "source": None, "op": None}
        # The kernel exports the stopper's subject only as the leading token of
        # stock_out_reason, propagated unchanged as stock_reason. Validate it against
        # the actual route and source op; never infer a source from a diagnostic union.
        if not route_identities_known(self.plan, setup.get("id")):
            return {"reason": reason, "source": None, "op": None}
        routes = {s["id"]: s for s in self.plan.get("setups", [])}
        ancestors = setup_lineage(self.plan, setup["id"]) - {setup["id"]}
        match = re.match(r"([^:\s]+):(\d+)\b", str(reason))
        if match and match[1] in ancestors:
            source = routes[match[1]]
            source_detail = _mapping(_mapping(kernel.get("setups")).get(match[1]))
            output_reasons = [
                _mapping(
                    _mapping(source_detail.get("outputs")).get(ref.removeprefix(OUTPUT_PREFIX))
                ).get("reason")
                for sid in ancestors | {setup["id"]}
                for ref in input_refs(routes[sid])
                if ref.startswith(OUTPUT_PREFIX) and producer_setup(self.plan, ref) == match[1]
            ]
            op = next((op for op in source["ops"] if str(op["op"]) == match[2]), None)
            if (
                op
                and not source_detail.get("stock_reason")
                and reason in [source_detail.get("stock_out_reason"), *output_reasons]
            ):
                return {"reason": reason, "source": source, "op": op}
        return {"reason": reason, "source": None, "op": None}

    def causal_measurements(self, entries, reason, op=None):
        """Native input names in the exported causal reason bind exact physical facts."""
        if not entries or not reason:
            return []
        tool = identity(self.bundle, _mapping(op).get("tool"), "tools")
        holder = identity(self.bundle, _mapping(op).get("holder"), "holders")
        radius = (
            "nose_radius"
            if op and approach(self.bundle, self.setup_for_op(op), op) == TURNING
            else "dia"
        )
        fields = {
            "radius_mm": (tool, radius),
            "shank_radius_mm": (tool, "shank"),
            "flute_len_mm": (tool, "flute_len"),
            "oal_mm": (tool, "oal"),
            "projection_mm": (tool, "projection"),
            "holder_radius_mm": (holder, "gauge_dia"),
            "holder_gauge_len_mm": (holder, "gauge_len"),
            "point_angle_deg": (tool, "point_angle"),
            "lead_mm": (tool, "lead"),
        }
        consumed = {
            field
            for native, field in fields.items()
            if re.search(rf"(?<!\w){re.escape(native)}(?!\w)", str(reason))
        }
        return [
            entry
            for entry in entries
            if ((entry["category"], entry["identity"]), entry["field"][0]) in consumed
            or entry["id"] in str(reason)
        ]

    def setup_for_op(self, op):
        return next(s for s in self.plan.get("setups", []) if any(o is op for o in s["ops"]))

    def stock_source_measurements(self, dependency):
        source, op = dependency["source"], dependency["op"]
        if not source or not op:
            return []
        kernel = _mapping(self.bundle.kernel)
        subject = f"{source['id']}:{op['op']}"
        detail = _mapping(_mapping(kernel.get("ops")).get(subject))
        reason = _mapping(detail.get("reasons")).get("stock_removal_bounds")
        if (
            not isinstance(reason, str)
            or "radius_mm" not in reason
            or reason not in dependency["reason"]
        ):
            return []
        debts = _mapping(kernel.get("measurement_debts"))
        selected = identity(self.bundle, op.get("tool"), "tools")
        radius = "nose_radius" if approach(self.bundle, source, op) == TURNING else "dia"
        return [
            entry
            for entry in _mapping(debts.get("ops")).get(subject, [])
            if (entry["category"], entry["identity"]) == selected and entry["field"] == [radius]
        ]

    def upstream_stock_stop(self, setup):
        dependency = self.stock_dependency(setup)
        if not dependency:
            return None
        source, op = dependency["source"], dependency["op"]
        if source and op:
            entries = self.stock_source_measurements(dependency)
            self.register_measurements(entries, source)
            refs = " ".join(self.measurement_reference(entry) for entry in entries)
            return (
                f"Depends on Setup {source['id']} op {op['op']} — upstream stock not established"
                + (
                    " — "
                    + "; ".join(
                        self.measurement_dimension(entry) + " " + self.measurement_reference(entry)
                        for entry in entries
                    )
                    + " not established"
                    if refs
                    else " — " + self.bench(dependency["reason"])
                )
                + "; resolve that source stock decision"
                + (" after recording its JOB measurements" if refs else "")
                + " and reissue this traveler."
            )
        if route_identities_known(self.plan, setup.get("id")):
            material = MaterialGraph(self.plan).nodes.get(setup["id"], ())
            edges = [atom.path[-1] for atom in material if atom.path]
            partitions = {
                (atom.root, atom.path[:-1], atom.path[-1].split) for atom in material if atom.path
            }
            names = {edge.output for edge in edges}
            if len(material) == len(edges) == 2 and len(partitions) == 1 and len(names) == 2:
                _, _, split = next(iter(partitions))
                producer = next(s for s in self.plan["setups"] if s["id"] == split)
                parting = next(
                    (
                        op
                        for op in producer.get("ops", [])
                        if op.get("do") in {"part_off", "cut_off"}
                        and set(_mapping(op.get("outputs"))) == names
                    ),
                    None,
                )
                records = _mapping(
                    _mapping(_mapping(_mapping(self.bundle.kernel).get("setups")).get(split)).get(
                        "outputs"
                    )
                )
                if parting and any(
                    _mapping(records.get(name)).get("partition") != f"{split}:{parting['op']}"
                    or _mapping(records.get(name)).get("reason")
                    for name in names
                ):
                    pieces = " and ".join(map(_text, sorted(names)))
                    action = "part-off" if parting["do"] == "part_off" else "saw cut"
                    return (
                        "Setup-entry stock not established — "
                        f"confirm {action} in Setup {_text(split)} op {parting['op']} leaves both "
                        f"required pieces ({pieces}); establish the assembled workpiece before "
                        "cutting and reissue this traveler."
                    )
        return (
            "Setup-entry stock not established — "
            + self.bench(dependency["reason"])
            + "; resolve the upstream stock prerequisite and reissue this traveler."
        )

    def collect_measurements(self, setup):
        """Consumer-owned payloads only; native/prerequisite diagnostic unions are not inputs."""
        entries = {}
        kernel = _mapping(self.bundle.kernel)
        debts = _mapping(kernel.get("measurement_debts"))
        prerequisite = self.stock_dependency(setup)
        geometry = {
            "accessibility",
            "reach",
            "internal_corner_radius",
            "fixture_interference",
            "thin_wall_under_clamp",
            "vise",
        }

        def collect(values):
            for entry in values or []:
                if (
                    isinstance(entry, dict)
                    and {"id", "category", "identity", "field"} <= entry.keys()
                ):
                    entries.setdefault(entry["id"], entry)

        for finding in self.setup_findings(setup):
            if _status(finding) not in ("unknown", "error"):
                continue
            rule, subject = _field(finding, "rule"), _field(finding, "subject", "")
            numbers = _field(finding, "numbers", {})
            if rule == "coordinates":
                # coordinates owns this list: grid, cut order and actual generated path
                # inputs. It is not geometry_common's diagnostic prerequisite union.
                from prechips.rules.coordinates import dro_grid_source

                selected = {
                    (category, reference)
                    for category, reference, _ in setup_items(self.bundle, setup)
                }
                source = dro_grid_source(self.bundle, setup)
                selected.add(identity(self.bundle, source.get("machine"), "machines"))
                collect(
                    entry
                    for entry in numbers.get("measurements", [])
                    if (entry["category"], entry["identity"]) in selected
                )
                for records in numbers.values():
                    if isinstance(records, list):
                        for record in records:
                            if isinstance(record, dict) and any(
                                str(op["op"]) == str(record.get("op")) for op in setup["ops"]
                            ):
                                collect(
                                    entry
                                    for entry in record.get("measurements", [])
                                    if (entry["category"], entry["identity"]) in selected
                                )
            elif rule == "consistency":
                if not prerequisite and numbers.get("dro_grid_debt"):
                    collect(
                        entry
                        for entry in numbers.get("measurements", [])
                        if entry["category"] == "machines" and entry["field"] == ["resolution"]
                    )
            elif rule == "saw_cut":
                op = next((o for o in setup["ops"] if subject == f"{setup['id']}:{o['op']}"), None)
                selected = identity(self.bundle, _mapping(op).get("tool"), "tools")
                # The host saw decision reads its own blade kerf even when native stock
                # is blocked. The rest of this list may be an upstream diagnostic union.
                collect(
                    entry
                    for entry in numbers.get("measurements", [])
                    if (entry["category"], entry["identity"]) == selected
                    and entry["field"] == ["kerf"]
                )
            elif rule in geometry:
                if prerequisite and rule != "internal_corner_radius":
                    continue
                op_detail = _mapping(_mapping(kernel.get("ops")).get(subject))
                if op_detail.get("stock_reason") and rule != "internal_corner_radius":
                    continue
                if rule == "internal_corner_radius":
                    radii = numbers.get("corner_radii_mm")
                    if (
                        isinstance(radii, list)
                        and radii
                        and not _known(numbers.get("tool_radius_mm"))
                    ):
                        op = next(
                            (o for o in setup["ops"] if subject == f"{setup['id']}:{o['op']}"), None
                        )
                        selected = identity(self.bundle, _mapping(op).get("tool"), "tools")
                        collect(
                            entry
                            for entry in numbers.get("measurements", [])
                            if (entry["category"], entry["identity"]) == selected
                            and entry["field"] in [["dia"], ["nose_radius"]]
                        )
                    continue
                values = numbers.get("measurements", [])
                if ":" in subject:
                    op = next(
                        (o for o in setup["ops"] if subject == f"{setup['id']}:{o['op']}"), None
                    )
                    selected = {
                        identity(self.bundle, _mapping(op).get("tool"), "tools"),
                        identity(self.bundle, _mapping(op).get("holder"), "holders"),
                    }
                    values = [
                        entry
                        for entry in values
                        if (entry["category"], entry["identity"]) in selected
                    ]
                    depth, flute = numbers.get("reach_depth_mm"), numbers.get("flute_len_mm")
                    turning = op is not None and approach(self.bundle, setup, op) == TURNING
                    oal_consumed = (
                        rule == "reach"
                        and _status(finding) == "unknown"
                        and op is not None
                        and _known(depth)
                        and _known(flute)
                        and depth >= 0
                        and depth > flute
                        and numbers.get("holder_wall_hits") == 0
                        and (turning or numbers.get("shank_hits") == 0)
                        and any(entry["field"] == ["oal"] for entry in values)
                    )
                    if oal_consumed:
                        from prechips.kernel import op_inputs
                        from prechips.rules.geometry_common import TURNING_HOLDER_KEYS

                        # Reuse accepted input qualification, not eager debt membership.
                        # This reads host inputs only; it does not run the native kernel.
                        inputs = op_inputs(
                            self.bundle,
                            setup,
                            op,
                            tables=self.records.get(("coordinates", setup["id"]), {}),
                        )
                        holder_keys = (
                            (*TURNING_HOLDER_KEYS, "projection_mm", "shank_width_mm", "head_len_mm")
                            if turning
                            else ("holder_radius_mm", "holder_gauge_len_mm", "projection_mm")
                        )
                        oal_consumed = all(_known(inputs.get(key)) for key in holder_keys)
                    values = [
                        entry for entry in values if entry["field"] != ["oal"] or oal_consumed
                    ]
                else:
                    selected = {
                        identity(self.bundle, reference, category)
                        for category, reference, _ in setup_items(self.bundle, setup)
                        if category in WORKHOLDING_CATEGORIES
                    }
                    values = [
                        entry
                        for entry in values
                        if (entry["category"], entry["identity"]) in selected
                        and entry["field"] != ["opening"]
                        and not (
                            entry["category"] == "machines"
                            and entry["field"][0] in {"resolution", "spindle", "envelope"}
                        )
                    ]
                collect(values)
            elif rule not in {"blind_depth", "tool_resolves"}:
                collect(numbers.get("measurements"))
        for op in setup.get("ops", []):
            collect(self.endpoint_measurements(setup, op))
            subject = f"{setup['id']}:{op['op']}"
            detail = _mapping(_mapping(kernel.get("ops")).get(subject))
            stock_reason = detail.get("stock_reason") or _mapping(prerequisite).get("reason")
            reasons = []
            for value in _mapping(detail.get("reasons")).values():
                value = str(value)
                if stock_reason and stock_reason in value:
                    continue
                if (
                    "stock before this op is unknown" in value
                    or "in-process stock unknown:" in value
                ):
                    continue
                source = re.search(r"([^:\s]+):(\d+)\b", value)
                if source and f"{source[1]}:{source[2]}" != subject:
                    continue
                reasons.append(value)
            collect(
                self.causal_measurements(
                    _mapping(debts.get("ops")).get(subject, []), "; ".join(reasons), op
                )
            )
        return [entries[key] for key in sorted(entries)]

    def fixture_measurement_marks(self, setup, reference, field):
        selected = self.holding_identity(setup, reference)
        return " ".join(
            "?" + marker
            for marker, entry in self.measurement_registry().values()
            if entry["id"] in self.setup_measurement_ids.get(setup["id"], set())
            and (entry["category"], entry["identity"]) == selected
            and entry["field"][: len(field)] == list(field)
        )

    def measurement_actions(self):
        groups = []
        previous = None
        for marker, entry in self.measurement_registry().values():
            record = self.measurement_record(entry)
            if entry["field"][0] == "projection":
                record = (*record[:2], None)
            if record != previous:
                groups.append([])
                previous = record
            groups[-1].append((marker, entry))
        html = ""
        for entries in groups:
            subject = self.measurement_subject(entries[0][1], include_holder=False)
            sources = sorted(
                {
                    sid
                    for _, entry in entries
                    for sid in self.measurement_sources.get(entry["id"], ())
                }
            )
            if sources:
                subject += (
                    " — source Setup"
                    + ("s " if len(sources) > 1 else " ")
                    + ", ".join(map(_text, sources))
                )
            html += (
                '<table class="measurement-actions"><colgroup><col>'
                '<col class="record-column"></colgroup><thead><tr>'
                f'<th scope="col">{_numeric_html(subject)}</th>'
                '<th scope="col">Record</th></tr></thead>'
            )
            for marker, entry in entries:
                action = self.measurement_action(entry)
                units = "°" if action["units"] == "degrees" else action["units"]
                context = ""
                if entry["field"][0] == "projection" and len(entry["field"]) > 1:
                    context = "in " + self.reference(entry["field"][1], "holders") + ": "
                html += (
                    f'<tbody><tr data-measurement-id="{escape(entry["id"])}" '
                    f'data-measurement-binding="{escape(entry.get("binding", entry["id"]))}" '
                    f'data-measurement-label="{marker}"><td>'
                    + _numeric_html(f"{marker} — {context}{action['instruction']}.")
                    + "</td><td>"
                    + _writing_field(units)
                    + "</td></tr></tbody>"
                )
            html += "</table>"
        return html

    def measurement_action(self, entry):
        """Shop wording derives from the physical field, never a report phrase rewrite."""
        if entry.get("shop_instruction"):
            return {"instruction": entry["shop_instruction"], "units": entry["units"]}
        item = measurement_item(self.bundle, entry["category"], entry["identity"])
        action = measurement_entry(
            entry["category"], entry["identity"], tuple(entry["field"]), item=item, subject="its"
        )
        centre = item.get("kind") in {"center_drill", "center_drill_set"}
        field = entry["field"]
        descriptions = {
            "dia": ("centre drill pilot diameter", "micrometer or calipers"),
            "shank": ("centre drill countersink body diameter", "micrometer or calipers"),
            "pilot_len": ("centre drill pilot length, countersink start to point tip", "calipers"),
        }
        if centre and len(field) == 1 and field[0] in descriptions:
            description, instrument = descriptions[field[0]]
            action["instruction"] = f"measure: its {description}, {instrument}, mm"
        if (item.get("shop_made") is True or item.get("kind") == "custom") and field == [
            "bed_height"
        ]:
            action["instruction"] = (
                "measure: its as-made support height, table to work-support contact surface, "
                "calipers or height gauge, mm"
            )
        return action

    def job_measurement_box(self):
        actions = self.measurement_actions()
        if not actions:
            return ""
        return (
            '<h2>UNRESOLVED ACQUISITION INPUTS</h2><div class="stop measurement-stop">'
            + _p(
                "?M# marks an unverified decision input; check and record it below. "
                "Make-to-drawing expected settings are not installed measurements. "
                "Bare M is an authored measurement variable; follow its named measurement."
            )
            + actions
            + _p(
                "Record the measured values here and return this traveler for reissue. "
                "Measurement alone does not clear the STOP decisions named on the setup "
                "pages; do not run a blocked setup until the corrected traveler is issued."
            )
            + "</div>"
        )

    def endpoint_measurements(self, setup, op):
        """Only this endpoint's consumed tool facts, not another op on the same hole."""
        endpoint = self.endpoint(setup, op)
        if not endpoint:
            return []
        category, reference = identity(self.bundle, op.get("tool"), "tools")
        selected = (category, reference)
        fields = (
            None
            if endpoint.get("depth_scale") == "quill"
            else {"lead"}
            if op.get("do") == "ream"
            else {"dia", "point_angle"}
            if op.get("do") == "drill"
            else set()
        )
        entries = [
            entry
            for entry in self.records.get(("blind_depth", op_feature(op)), {}).get(
                "measurements", []
            )
            if (entry["category"], entry["identity"]) == selected
            and (fields is None or entry["field"] in [[field] for field in fields])
        ]
        tool = resolve(self.bundle, "tools", op.get("tool"))
        if tool and op.get("do") == "drill" and not _known(endpoint.get("point_mm")):
            debt = length_debt(tool, "dia", category, reference)
            if debt:
                entries.append(debt)
            fact = angle_fact(tool, "point_angle", require_measured=False)
            if not fact["verified"]:
                entry = measurement_entry(
                    category,
                    reference,
                    "point_angle",
                    status=fact["measurement_status"],
                    item=tool,
                )
                entries.append(
                    {
                        **entry,
                        "status": fact["measurement_status"],
                        "reason": fact["reason"],
                    }
                )
        if tool and op.get("do") == "ream" and not _known(endpoint.get("lead_mm")):
            debt = length_debt(tool, "lead", category, reference)
            if debt:
                entries.append(debt)
        return sorted(
            {entry["id"]: entry for entry in entries}.values(),
            key=lambda entry: (entry["field"] != ["point_angle"], entry["id"]),
        )

    def tool_detail(self, reference, holder=None, *, length_format=None):
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

        def dimension(field, label, suffix="", *, require_measured=False):
            fact = length_fact(item, field, require_measured=require_measured)
            if not _known(fact["value"]):
                return
            category, key = identity(self.bundle, reference, "tools")
            parts = list(field) if isinstance(field, tuple) else [field]
            consumed = next(
                (
                    entry
                    for _, entry in self.measurement_registry().values()
                    if (entry["category"], entry["identity"], entry["field"])
                    == (category, key, parts)
                ),
                None,
            )
            text = f"{label}{(length_format or self.operative)(fact['value'])}{suffix}"
            if fact["verified"] and not consumed:
                detail.append(text)
            else:
                marker = self.measurement_reference(consumed) if consumed else "? not verified"
                detail.append(_Unverified(f"{text} {marker}"))

        dimension("nose_radius", "nose R")
        if item.get("size_in"):
            detail.append(f"{item['size_in']} in")
        # A blade's reach is how deep it can plunge, not how far it sticks out.
        centre = item.get("kind") in {"center_drill", "center_drill_set"}
        dimension("dia", "pilot Ø" if centre else "Ø")
        dimension("reach", "max plunge depth ")
        blade = length_fact(item, "blade_width", require_measured=False)
        if _known(blade["value"]) and not blade["verified"]:
            dimension("blade_width", "blade width ")
        # A consumed installed shank debt overrides a bare catalogue allowance locally.
        shank = length_fact(item, "shank", require_measured=False)
        cutting = length_fact(item, "dia", require_measured=False)
        category, key = identity(self.bundle, reference, "tools")
        shank_debt = any(
            (entry["category"], entry["identity"], entry["field"]) == (category, key, ["shank"])
            for _, entry in self.measurement_registry().values()
        )
        if _known(shank["value"]) and (
            shank_debt
            or not shank["verified"]
            or (_known(cutting["value"]) and abs(shank["value"] - cutting["value"]) > 1e-3)
        ):
            dimension(
                "shank",
                "body Ø" if item.get("kind") in {"center_drill", "center_drill_set"} else "shank Ø",
            )
        dimension("flute_len", "cutting length " if centre else "flute ")
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
        if pair is not None and not conflict:
            dimension(
                ("projection", pair),
                "projection ",
                (
                    " (blade body midplane → holder gauge plane)"
                    if item.get("kind") == "slitting_saw"
                    else " from holder face"
                ),
                require_measured=True,
            )
        return detail

    def feature_names(self, features):
        """Several features' names; compact levels print consecutive numbered names as
        one range (:func:`_numbered_names`)."""
        names = [self.feature_name(feature) for feature in features]
        return ", ".join(names) if self.detail == "pedantic" else _numbered_names(names)

    def feature_name(self, key):
        if not isinstance(key, str) or key == "unknown":
            return "?"
        name = re.sub(r"_pos_([xyz])$", lambda m: f" (+{m[1].upper()} side)", key)
        name = re.sub(r"_neg_([xyz])$", lambda m: f" (−{m[1].upper()} side)", name)
        name = re.sub(r"_datum_([a-z])$", lambda m: f" (datum {m[1].upper()})", name)
        return name.replace("_", " ")

    def zero_name(self, setup):
        return f"Setup {_text(setup['id'])} zero"

    def frame_tag(self, setup=None):
        """`` (from Setup <id> zero)`` after an op row's setup-frame coordinates when the
        job page also prints model (STEP) coordinates, in the plan's stock note, so a
        reader never compares numbers from two frames unnamed (#335); "" otherwise."""
        setup = setup or self.setup
        note = _mapping(self.plan.get("stock")).get("note")
        if setup is None or not (isinstance(note, str) and _PROSE_COORDINATE.search(note)):
            return ""
        if re.search(r"(?i)\bsetup \S+ zero\b", note):
            # The note already names the setup frame its coordinates are in.
            return ""
        return f" (from {self.zero_name(setup)})"

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
            return f"Setup {_text(sid)}" + (f" op {op}" if op else "")
        return ""

    def plain_error(self, rule, message, subject):
        message = str(message)
        for prefix in (subject + ":", subject.replace(":", " ") + ":"):
            if message.startswith(prefix):
                message = message[len(prefix) :].strip()
        if rule == "accessibility" and "occluded" in message:
            return "tool or holder hits the part or the holding"
        if (
            self.detail != "pedantic"
            and rule == "accessibility"
            and message == "claimed face references are unknown or unmapped."
        ):
            sid, _, operation = subject.partition(":")
            if any(
                setup["id"] == sid and str(op.get("op")) == operation and op.get("do") == "hand_tap"
                for setup in self.plan.get("setups", [])
                for op in setup.get("ops", [])
            ):
                return "Hand-tap movement is not checked."
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
            evidence = _mapping(_field(finding, "numbers"))
            inspection_identity = evidence.get("identity") if rule == "inspection" else None
            if isinstance(inspection_identity, dict):
                sid, number = evidence.get("setup_id"), evidence.get("op_id")
                if setup and sid == setup["id"] and number is not None:
                    label = f"op {number}"
                elif sid is not None:
                    label = f"Setup {_text(sid)}" + (f" op {number}" if number is not None else "")
                else:
                    feature = inspection_identity.get("feature_owner")
                    requirement = inspection_identity.get("requirement", "")
                    label = " ".join(
                        filter(
                            None,
                            [
                                inspection_identity.get("workpiece"),
                                self.feature_name(feature) if feature is not None else "",
                                _REQUIREMENT_NAMES.get(requirement, _text(requirement)),
                            ],
                        )
                    )
            else:
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
                topic = _TOPICS.get(rule, _text(rule))
                if rule == "tool_resolves":
                    sid, _, operation = subject.partition(":")
                    if any(
                        candidate["id"] == sid
                        and str(op.get("op")) == operation
                        and op.get("do") == "coating"
                        for candidate in self.plan.get("setups", [])
                        for op in candidate.get("ops", [])
                    ):
                        topic = "coating product identity"
                if rule == "zero_check" and readout_kind(self.bundle) != "digital":
                    topic = (
                        "handwheel / scale zero"
                        if readout_kind(self.bundle) == "handwheel"
                        else "readout zero"
                    )
                unverified.setdefault(topic, []).append(label)

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

    def mount_key(self, setup):
        return (
            identity(self.bundle, setup.get("machine"), "machines"),
            identity(self.bundle, _mapping(setup.get("hold")).get("fixture"), "workholding"),
        )

    @functools.cached_property
    def common_mounts(self):
        groups = {}
        for setup in self.plan.get("setups", []):
            hold = _mapping(setup.get("hold"))
            if not resolve(self.bundle, "workholding", hold.get("fixture")):
                continue
            groups.setdefault(self.mount_key(setup), []).append(setup)
        common = {}
        for key, setups in groups.items():
            if len(setups) < 2:
                continue
            fields = {}
            for field in ("jaws_along", "fixed_jaw"):
                values = {_mapping(setup.get("hold")).get(field) for setup in setups}
                if len(values) == 1 and next(iter(values)) not in (
                    None,
                    "",
                    "unknown",
                    "none",
                    "not_applicable",
                ):
                    fields[field] = next(iter(values))
            common[key] = (setups, fields)
        return common

    @functools.cached_property
    def shared_stop_instructions(self):
        """Share an authored installation only for the same physical stop and mount."""
        candidates = {}
        for setup in self.plan.get("setups", []):
            hold = _mapping(setup.get("hold"))
            reference, text = hold.get("stop_fixture"), hold.get("stop")
            if (
                reference in (None, "", UNKNOWN)
                or not isinstance(text, str)
                or not text.strip()
                or _FIELD.search(text)
            ):
                continue
            key = (self.mount_key(setup), self.holding_identity(setup, reference), text)
            candidates.setdefault(key, []).append(setup)
        return {
            key: setups
            for key, setups in candidates.items()
            if len({setup.get("presentation_group", setup["id"]) for setup in setups}) > 1
        }

    def fixture_key(self):
        lines, mounts = [], {}
        for setups, fields in self.common_mounts.values():
            first = setups[0]
            reference = _mapping(first.get("hold")).get("fixture")
            name = self.reference(reference, "workholding")
            fixture = _mapping(resolve(self.bundle, "workholding", reference))
            if (
                fixture.get("kind") == "vise"
                and any(
                    _mapping(setup.get("hold")).get("parallels")
                    not in (None, "none", "not_applicable")
                    for setup in setups
                )
                and any(field in fixture for field in ("jaw_height_mm", "jaw_height_in"))
            ):
                fact = length_fact(fixture, "jaw_height", require_measured=False)
                selected = self.holding_identity(first, reference)
                consumed = next(
                    (
                        entry
                        for _, entry in self.measurement_registry().values()
                        if (entry["category"], entry["identity"]) == selected
                        and entry["field"] == ["jaw_height"]
                    ),
                    None,
                )
                height = f"jaw height {_number(fact['value'])} mm"
                if not fact["verified"] or consumed:
                    height += " " + (
                        self.measurement_reference(consumed) if consumed else "? not verified"
                    )
                name += f" ({height})"
            facts = []
            if "jaws_along" in fields:
                facts.append("jaws " + _text(fields["jaws_along"]).upper())
            if "fixed_jaw" in fields:
                facts.append("fixed jaw " + _text(fields["fixed_jaw"]))
            mounts.setdefault(tuple(facts), []).append(
                self.setup_span([setup["id"] for setup in setups]) + ": " + name
            )
        for facts, owners in mounts.items():
            shared = "both " if len(owners) == 2 else "all " if len(owners) > 2 else ""
            lines.append(
                "; ".join(owners) + (" (" + shared + ", ".join(facts) + ")" if facts else "")
            )
        for (_, _, text), setups in self.shared_stop_instructions.items():
            lines.append(
                self.setup_span([setup["id"] for setup in setups])
                + ": "
                + self.bench(text, setups[0])
            )
        return _p("Fixtures — " + "; ".join(lines) + ".") if lines else ""

    def hold(self, setup):
        hold = _mapping(setup.get("hold"))
        lathe = self.lathe(setup)
        compact = getattr(self, "detail", "pedantic") != "pedantic"
        evidence = []
        shared_steps = {}

        def reference(value, slot):
            rendered = self.reference(value, slot)
            if compact:
                evidence.append(rendered)
            return self.short_reference(value, slot) if compact else rendered

        # Executed order: a span the hold will cover is measured before the part goes in.
        steps = self.bench_measures(setup)

        def stated(key):
            value = hold.get(key)
            return value not in (None, "none", "not_applicable")

        fixture = hold.get("fixture", "unknown")
        uses = self.shop_made_uses(setup)
        scope, why = hand_fed(self.bundle, setup)
        handling = unfixtured_handling(manual_bench(self.bundle, setup), hold)
        if hold.get("kind") == HAND_FED and scope != "admitted":
            steps.append(
                _Box(
                    f"STOP: hand-fed holding not established ({why}) — do not run.",
                    source="hold_fields",
                )
            )
        elif hold.get("kind") == HAND_FED:
            # Nothing clamps the work: the operator feeds it into the blade on the table.
            lines = [
                self.saw_setting(op)
                for op in setup.get("ops", [])
                if op.get("do") in SAW_OPS and "follows" in op
            ]
            steps.append(
                "Fed by hand on the saw table, sawing "
                + " and ".join(dict.fromkeys(lines))
                + "; no vise or clamp holds the work."
            )
            steps.extend(self.feeding(hold, setup))
        elif handling:
            note = note_text(hold.get("note"))
            if note.strip() in ("", UNKNOWN, "none", "not_applicable"):
                steps.append(
                    _Box("STOP: bench handling not declared — do not run.", source="hold_fields")
                )
        elif fixture == "unknown":
            steps.append(_Box("STOP: holding not chosen — do not run.", source="hold_fields"))
        else:
            common = self.common_mounts.get(self.mount_key(setup)) if compact else None
            shared = common[1] if common else {}
            mount = "" if common else "Mount the " + reference(fixture, "workholding")
            pointer = self.shop_made_pointer(setup, fixture, uses)
            mount += pointer
            if stated("chuck"):
                mount += (" with the " if mount else "Chuck: ") + reference(
                    hold["chuck"], "fixtures"
                )
            if stated("jaws_along") and "jaws_along" not in shared:
                mount += f"; jaws along {_text(hold['jaws_along']).upper()}"
            angle = swivel_angle(hold)
            if angle:
                mount += (
                    f", swivelled {_number(abs(angle))}° "
                    + ("counterclockwise" if angle > 0 else "clockwise")
                    + " seen from above"
                    if _known(angle)
                    else ", swivelled by ? (angle unknown)"
                )
            if stated("fixed_jaw") and "fixed_jaw" not in shared:
                mount += f"; fixed jaw {_text(hold['fixed_jaw'])}"
            if mount:
                steps.append(mount.strip("; ") + ".")
            placement = self.fixture_setting(setup, hold, uses)
            alignment = self.align_step(setup, hold)
            steps.extend(placement + alignment)
        paired_grip = False
        if stated("parallels") and hold["parallels"] != "unknown":
            line = "Parallels: " + reference(hold["parallels"], "fixtures")
            parallel = _mapping(resolve(self.bundle, "fixtures", hold["parallels"]))
            height = _amount(parallel.get("height_mm"))
            if compact and parallel.get("kind") == "parallels" and _known(height):
                line = f"Parallels {_number(height)} mm"
                if _known(hold.get("grip_mm")):
                    line += f"; grip {_number(hold['grip_mm'])} mm"
                    paired_grip = True
            if stated("riser"):
                line += ", standing on " + reference(hold["riser"], "fixtures")
                line += self.shop_made_pointer(setup, hold["riser"], uses)
            if stated("support_orientation"):
                line += f" ({_text(hold['support_orientation'])} up)"
            steps.append(line + ".")
            if compact and paired_grip:
                shared_steps[
                    (
                        "parallels",
                        identity(self.bundle, hold["parallels"], "fixtures"),
                        height,
                        hold["grip_mm"],
                    )
                ] = line + "."
        if stated("jaw_bar") and hold["jaw_bar"] != "unknown":
            name = reference(hold["jaw_bar"], "fixtures")
            bar = _mapping(resolve(self.bundle, "fixtures", hold["jaw_bar"]))
            diameter = _amount(bar.get("dia_mm"))
            if compact and _known(diameter):
                name = f"Ø{_number(diameter)} mm round bar"
            steps.append(
                (
                    name + " at moving-jaw/work contact, centred; centre "
                    if compact
                    else "Round bar: "
                    + name
                    + " between the work and the moving jaw, centred in the jaws, its centre "
                )
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
                    + reference(supports, "fixtures")
                    + self.shop_made_pointer(setup, supports, uses)
                    + "."
                )
        for support in supports if isinstance(supports, list) else []:
            support = {"ref": support} if isinstance(support, str) else _mapping(support)
            if support.get("placement") == "posed":
                placed = self.placed_support(setup, support, uses)
                if compact:
                    evidence.append(placed)
                if compact:
                    borrowed = support.get("stock_ref")
                    source = (
                        _text(borrowed.removeprefix(OUTPUT_PREFIX)) + " retained piece"
                        if isinstance(borrowed, str) and borrowed != UNKNOWN
                        else reference(support.get("ref", UNKNOWN), "fixtures")
                    )
                    line = f"Support: {source}"
                    # Pose annotations are fixture construction, not handling actions.
                    # The full note remains in placed_support and checker evidence.
                    steps.append(line.rstrip(".") + ".")
                else:
                    steps.append(placed)
                continue
            line = "Support: " + reference(support.get("ref", UNKNOWN), "fixtures")
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
                steps.append(
                    _Box("STOP: support / restraint not chosen — do not run.", source="hold_fields")
                )
            else:
                line = label + reference(hold["support"], "fixtures")
                if _known(hold.get("quill_extension_mm")):
                    line += f", quill out {self.operative(hold['quill_extension_mm'])} mm"
                steps.append(line + ".")
        stop_pointer = self.shop_made_pointer(setup, hold.get("stop_fixture"), uses)
        if stop_pointer:
            steps.append(f"Work stop: {reference(hold['stop_fixture'], 'fixtures')}{stop_pointer}.")
        for key, label in (
            ("locate", "Locate"),
            ("grip_on", "Grip on"),
            ("stop", "Stop"),
        ):
            if stated(key):
                if (
                    compact
                    and key == "stop"
                    and any(
                        setup["id"] in {member["id"] for member in members}
                        for members in self.shared_stop_instructions.values()
                    )
                ):
                    continue
                prefix = "" if compact and key == "stop" and hold[key] != UNKNOWN else f"{label}: "
                steps.append(prefix + self.bench(hold[key], setup).rstrip(".") + ".")
        if stated("clamp"):
            for step in str(hold["clamp"]).split(";"):
                step = self.bench(step, setup)
                if step:
                    steps.append(step[:1].upper() + step[1:] + ".")
                    if compact and not _FIELD.search(step):
                        shared_steps[("clamp", step)] = steps[-1]
        clamps = hold.get("clamps") if isinstance(hold.get("clamps"), list) else []
        for label, clamp in zip(clamp_labels(hold), clamps, strict=True):
            clamp = _mapping(clamp)
            role = _CLAMP_ROLES[label.rstrip("0123456789")]
            line = f"{label} {role}: {reference(clamp.get('ref'), 'fixtures')}"
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
            value = (
                note_text(hold.get(key), detail=getattr(self, "detail", "pedantic"))
                if key == "note"
                else hold.get(key)
            )
            if stated(key) and value:
                prefix = "" if compact and key == "note" else f"{label}: "
                steps.append(prefix + self.bench(value, setup).rstrip(".") + ".")
        facts = self.hold_facts(setup, hold, lathe)
        adverse = list(_typed_values([steps, evidence, [value for _, value in facts]], setup["id"]))
        for fact in adverse:
            self.record_decision(
                setup,
                source=fact.source,
                status=fact.status,
                scope=fact.scope,
                text=fact.text,
                kind=fact.kind,
            )
        steps = [
            re.sub(r"\.{2,}$", ".", step)
            for step in steps
            if not compact or not isinstance(step, (_Box, _Unverified))
        ]
        if compact:
            # Inventory poses and successful alignment audits remain evaluated above;
            # the route prints settings, authored handling and adverse facts instead.
            if paired_grip:
                facts = [(name, value) for name, value in facts if name != "grip length mm"]
            facts = [
                ({"grip length mm": "Grip mm"}.get(name, name), value)
                for name, value in facts
                if name
                in (
                    "grip length mm",
                    "nominal stickout mm",
                    "set stickout",
                    "stickout mm",
                    "centre tip at Z",
                    "quill out mm",
                    "jaw 1 clocked °",
                )
                or "?" in str(value)
            ]
            if facts:
                steps.append("; ".join(f"{name}: {value}" for name, value in facts) + ".")
            self._route_hold_steps[setup["id"]] = tuple(steps)
            self._route_hold_facts[setup["id"]] = shared_steps
            return (
                "<p><strong>Hold.</strong> " + _fields(" ".join(steps)) + "</p>" if steps else "",
                self.indexing(setup),
            )
        below = (
            _table([name for name, _ in facts], [[value for _, value in facts]]) if facts else ""
        )
        return (
            "<h2>HOLD</h2>" + _list(steps),
            below + self.indexing(setup),
        )

    def feeding(self, hold, setup):
        """A hand-fed cut's declared feeding (``guide_above_mm``, ``push_aid``,
        ``feed_from``, ``end_support``), one step each; an undeclared one is a STOP."""
        from prechips.kernel import feed_from_ambiguity

        guide, push = hold.get("guide_above_mm"), hold.get("push_aid", UNKNOWN)
        start, end = hold.get("feed_from"), hold.get("end_support")
        ambiguity = feed_from_ambiguity(self.bundle, setup)
        return [
            f"Upper blade guide: {self.operative(guide)} mm above the top of the work."
            if _known(guide)
            else _Box(
                "STOP: upper blade-guide height not declared — do not run.", source="hold_fields"
            ),
            f"Push aid: {self.reference(push, 'fixtures')}."
            if push != UNKNOWN
            else _Box("STOP: push aid not declared — do not run.", source="hold_fields"),
            f"Start the cut at the {start} end of the line: feed the work toward {start} into "
            "the blade, its trailing end behind, as the arrows in the picture run."
            if start in _FEED_ENDS and not ambiguity
            else _Box(f"STOP: {ambiguity} — do not run.", source="hold_fields", status="error")
            if ambiguity
            else _Box(
                "STOP: end of the line the cut starts from not declared — do not run.",
                source="hold_fields",
            ),
            _END_SUPPORT[end]
            if end in _END_SUPPORT
            else _Box(
                "STOP: how the end of the cut is supported not declared — do not run.",
                source="hold_fields",
            ),
        ]

    def align_step(self, setup, hold):
        """The step that squares a vise's fixed jaw, or an angle plate's locating face, to
        the table travel where this setup mounts or turns one (hold_fields ``align_due``):
        its indicator, sweep length and limit come from ``hold.align``; any not established
        is a STOP."""
        due = _mapping(self.records.get(("hold_fields", setup["id"]))).get("align_due")
        if due in (None, "not_applicable"):
            return []
        if swivelled(self.bundle, setup):
            return self.swivel_step(setup, hold)
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
                _Box(
                    f"STOP: square {face} to the table travel — "
                    + ", ".join(missing)
                    + " not established; do not run.",
                    source="hold_fields",
                )
            ]
        if getattr(self, "detail", "pedantic") != "pedantic":
            return [
                f"Align {face} to {axis} travel with {self.short_reference(gauge, 'gauges')}: "
                f"≤{_declared(limit)} mm over {_number(over)} mm; tighten and recheck."
            ]
        thing = "vise" if vise else "plate"
        return [
            f"Square {face} to the {axis} travel: with the {self.reference(gauge, 'gauges')} "
            f"held from the spindle head on {face}, traverse {axis} {_number(over)} mm along "
            f"it; tap the {thing} round until the reading changes no more than "
            f"{_declared(limit)} mm ({_number(round(limit / 25.4, 5))} in) over that length, "
            f"tighten the {thing} to the table and sweep again."
        ]

    def swivel_step(self, setup, hold):
        """The step that sets a swivelled vise's jaw line where this setup mounts it or
        changes its swivel: ``indicate_jaw`` touches the indicator on the fixed jaw at two
        DRO points along the line; a stated method sets it by its own reference. It closes
        on the setting tolerance the swivel rule holds the cuts' angle bands against; any
        value not established is a STOP."""
        set_by = swivel_setting(self.bundle, setup)
        line, method, tolerance = set_by["line_deg"], set_by["method"], set_by["tolerance_deg"]
        gauge = _mapping(hold.get("align")).get("indicator", "unknown")
        fields = [("the swivel angle", _known(line)), ("the setting method", method != "unknown")]
        if method == "indicate_jaw":
            fields += [
                ("the indicator", align_indicator(self.bundle, gauge) not in (None, "unknown")),
                ("the DRO move", "over_mm" in set_by),
                ("the limit", "limit_mm" in set_by),
            ]
        fields.append(("the setting tolerance", _known(tolerance)))
        missing = [name for name, known in fields if not known]
        if missing:
            return [
                _Box(
                    "STOP: set the vise swivel — "
                    + ", ".join(missing)
                    + " not established; do not run.",
                    source="swivel",
                )
            ]
        sense = "counterclockwise" if line > 0 else "clockwise"
        turn = f"{_number(round(abs(line), 4))}° {sense} from the X travel, seen from above"
        held = f"Set this way the swivel is within ±{tolerance:.2g}°."
        if method in SWIVEL_STATED:
            how = {
                "graduations": "on the swivel base's graduations",
                "protractor": "with a bevel protractor between the fixed jaw and a straight "
                "edge indicated along the X travel",
                "sine_bar": "with the sine bar between the fixed jaw and a straight edge "
                "indicated along the X travel",
            }[method]
            return [
                f"Swivel the vise so the fixed jaw runs {turn}, set {how}; tighten the "
                f"swivel-base nuts and check the setting again the same way. {held}"
            ]
        decimals = dro_grid(self.bundle, setup)[1]
        over, limit = set_by["over_mm"], set_by["limit_mm"]
        # The rule's own move, on the DRO grid: the one its tolerance budgets for.
        dx, dy = set_by["move_dro"]
        start = (
            ("left" if dx > 0 else "right") if abs(dx) >= abs(dy) else "front" if dy > 0 else "back"
        )
        unit = self.units
        return [
            f"Swivel the vise so the fixed jaw runs {turn}: loosen the swivel-base nuts and "
            "rough it in on the base graduations.",
            f"Set it with the {self.reference(gauge, 'gauges')} held from the spindle head: "
            f"touch it on the fixed jaw near its {start} end, zero the dial and zero DRO X "
            "and Y there (this zero only sets the swivel; the work's zero is picked up "
            f"below). Raise the quill clear of the jaws, move to X {dx:.{decimals}f}, "
            f"Y {dy:.{decimals}f} {unit} ({_number(over)} mm along the jaw), lower the "
            "indicator onto the jaw and read; tap the vise round until both points read the "
            f"same within {_declared(limit)} mm ({_number(round(limit / 25.4, 5))} in), "
            f"tighten the swivel-base nuts and read both points again. {held}",
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
        if (
            receiver not in setups
            or producer_setup(self.plan, setups[receiver].get("stock_in")) != setup["id"]
        ):
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
            f"<h2>CHECK THE BLANK — before SETUP {escape(_text(receiver))}</h2>"
            + _p(
                "Process limits for the squared blank, not drawing limits: "
                f"SETUP {_text(receiver)} "
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
            debt = length_debt(
                item, key, *identity(self.bundle, reference, "fixtures"), require_measured=True
            )
            sizes.append(
                label
                + (
                    f"{self.operative(value)} mm"
                    if measured
                    else self.measurement_marker(debt)
                    if debt
                    else "? not measured"
                )
            )
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
        shown = self.operative if getattr(self, "detail", "pedantic") == "pedantic" else _number
        return f"{shown(min(jaw, (top - bottom) * scale) / 2)} mm above parallels"

    def hold_facts(self, setup, hold, lathe):
        o = self.operative if getattr(self, "detail", "pedantic") == "pedantic" else _number
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
        if _known(hold.get("jaw_above_parallels_mm")) and (
            getattr(self, "detail", "pedantic") == "pedantic"
            or self.machine(setup).get("kind") in ("mill", "drill_press")
        ):
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
            # A swivelled jaw line runs off the travel: its centre is along the jaws.
            where = "along the jaws" if swivel_angle(hold) else f"at {along}"
            facts.append((f"jaw centre {where}", o(hold["jaw_center_along_mm"])))
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

    def placed_support(self, setup, support, uses):
        """A posed auxiliary names its actual source, not a second stock purchase."""
        borrowed = support.get("stock_ref")
        if isinstance(borrowed, str) and borrowed != UNKNOWN:
            name = _text(borrowed.removeprefix(OUTPUT_PREFIX))
            source = f"temporarily use the {name} retained piece"
        else:
            reference = support.get("ref", UNKNOWN)
            source = self.reference(reference, "fixtures")
            source += self.shop_made_pointer(setup, reference, uses)
        line = f"Support {_text(support.get('id', UNKNOWN))}: {source}"
        axes = _pose_axes(support.get("pose"))
        if axes is None:
            line += "; STOP: support placement is unresolved"
            self.record_decision(
                setup,
                source="support_pose",
                status="unknown",
                scope=f"{setup['id']}/{support.get('id', UNKNOWN)}",
                text=line,
            )
        else:
            origin = ", ".join(
                f"{axis} {_number(value)}" for axis, value in zip("XYZ", axes[0], strict=True)
            )
            line += f"; local origin {origin} mm"
            for label, vector in (("X", axes[1]), ("Z", axes[3])):
                aligned = _setup_axis(vector)
                direction = (
                    ("+" if aligned[1] > 0 else "−") + "XYZ"[aligned[0]]
                    if aligned
                    else "(" + ", ".join(map(_number, vector)) + ")"
                )
                line += f"; local +{label} toward {direction}"
        if support.get("note"):
            line += ". " + self.bench(support["note"], setup)
        return line.rstrip(".") + "."

    def shop_made_uses(self, setup):
        """``{identity: (reference, [(label, pose)])}`` for each shop-made item the hold
        uses, keyed by the item its reference selects (:meth:`holding_identity`) with its
        first spelling for print, in HOLD
        order: the fixture at ``hold.pose``, each clamp entry at its own pose (labelled by
        :func:`clamp_labels`), the work stop at ``stop_pose``, and each tagged support at
        its own pose. Unposed built-in items (vise jaws, risers, legacy supports and jaw
        buttons) are :data:`LOOSE`; borrowed stock is not a shop-made inventory item."""
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
        placed += [(hold.get(key), None, LOOSE) for key in ("riser", "jaw_buttons")]
        supports = hold.get("supports")
        if isinstance(supports, str):
            placed.append((supports, None, LOOSE))
        for support in supports if isinstance(supports, list) else []:
            support = {"ref": support} if isinstance(support, str) else _mapping(support)
            if "stock_ref" in support:
                continue
            posed = support.get("placement") == "posed"
            placed.append(
                (
                    support.get("ref"),
                    support.get("id") if posed else None,
                    support.get("pose") if posed else LOOSE,
                )
            )
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
        """The setup carrying this item's table: its first use at these poses
        under these HOLD labels (a renumbered clamp gets its own table)."""
        return self.shop_made_homes.setdefault((key, repr(uses[key][1])), setup["id"])

    def shop_made_pointer(self, setup, reference, uses):
        """`` (shop-made: …)`` naming the setup with the item's table; empty otherwise."""
        key = self.holding_identity(setup, reference)
        if not isinstance(reference, str) or key not in uses:
            return ""
        home = self.shop_made_home(setup, key, uses)
        return f" (shop-made: SHOP-MADE FIXTURE table, Setup {_text(home)})"

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
                    f"({places}-place linear tolerance: {state}); put the fit on the grid in the "
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
        # A made base is a drawing placement, not an installed observation.
        if any(
            _supply(solid) != "made" and not record_trusted(solid, require_measured=False)[0]
            for solid, _ in boxes
        ):
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
        if _supply(base) == "made" and self.shop_made(setup, fixture):
            marks = self.fixture_measurement_marks(setup, fixture, ("solids", base.get("name")))
            line += " (Make-to-drawing placement" + (f" {marks}" if marks else "") + ")"
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
                    if _supply(solid) == "made" or record_trusted(solid, require_measured=False)[0]
                    else "? (not verified)"
                )
                marks = self.fixture_measurement_marks(
                    setup, reference, ("solids", solid.get("name"))
                )
                if marks:
                    nominal += f" {marks}"
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
        printed there only, and the first carrying its make table
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
                + _p(f"Make before Setup {_text(setup['id'])}.")
                + (
                    _p(f"Sizes and positions: SHOP-MADE FIXTURE table, Setup {_text(table)}.")
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
        bore cut in it (either may be the surface that locates). Made dimensions are
        expected drawing settings; bought/existing dimensions still require physical
        provenance. Showing a made setting never clears its installed-measurement debt."""
        item = self.shop_made(setup, reference)
        solids = [s for s in item.get("solids") or [] if isinstance(s, dict)]
        # Made solids, and existing parts (a bought angle plate) only for holes cut here.
        made = [s for s in solids if not s.get("void") and _supply(s) != "bought"]
        withheld = {}
        for solid in solids:
            if _supply(solid) != "made" and not record_trusted(solid, require_measured=False)[0]:
                status = _mapping(solid.get("measured")).get("status", "assumed")
                withheld[id(solid)] = (
                    f"{status} dimensions (not physically measured)"
                    if _example(solid)
                    else "unverified"
                )
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
                    withheld.setdefault(id(parent), f"its hole {name} is {withheld[id(void)]}")
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
            if any(map(_example, members)):
                component += f" {EXAMPLE_MARK}"
                self.example_marks = True
            fit = id(first) in fits
            marks = " ".join(
                filter(
                    None,
                    (
                        self.fixture_measurement_marks(
                            setup, reference, ("solids", solid.get("name"))
                        )
                        for solid in members
                    ),
                )
            )
            if id(first) in withheld:
                where = f"? not set: {withheld[id(first)]}; verify before making"
                rows.append([component, "?" + (f" {marks}" if marks else ""), [where], "—", "—"])
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
                    (
                        self.solid_size(first, fit) + (f" {marks}" if marks else "")
                        if _supply(first) == "made"
                        else "—"
                    ),
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
                " × ".join(
                    self.fixture_number(v)
                    + (
                        " " + mark
                        if (mark := self.fixture_measurement_marks(setup, reference, (edge,)))
                        else ""
                    )
                    for edge, v in zip(("length", "width", "height"), dims, strict=True)
                )
                if None not in dims
                else "? not declared"
            )
            body = "body"
            if any(_example(item.get(f"{edge}_mm")) for edge in ("length", "width", "height")):
                body += f" {EXAMPLE_MARK}"
                self.example_marks = True
            rows.append([body, size, [LOOSE_TEXT if loose else "? not posed"], "—", "—"])
        frame = f"its own frame ({LOOSE_TEXT})" if loose else f"Setup {_text(sid)}"
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
            f"Make before Setup {_text(first)}. Make-to-drawing expected dimensions and positions, "
            "not physical installed measurements. "
            + (
                f"Nothing poses it in the Setup {_text(sid)} frame: set it where the HOLD says. "
                "Positions are in the item's own frame"
                if loose
                else f"Positions are in the Setup {_text(sid)} frame"
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
                _p(f"Make operations: Setup {_text(first)}.")
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
    def _spindle_saw_op_debt(self, setup, op, check):
        if not spindle_saw(self.bundle, setup, op):
            return ""
        details = _mapping(_mapping(self.bundle.kernel).get("ops"))
        detail = _mapping(details.get(f"{setup['id']}:{op['op']}"))
        if isinstance(detail.get("saw"), dict):
            status, reasons, _ = finite_saw_evidence(detail, check)
            if status == "pass":
                return ""
            text = "; ".join(reasons) or f"Mounted-saw {check} evidence is incomplete"
        else:
            status = "unknown"
            text = (
                SLITTING_SAW_MODEL_REASON
                if slitting_saw(self.bundle, op)
                else UNRESOLVED_SAW_MODEL_REASON
            )
        scope = f"{setup['id']}:{op['op']}"
        self.record_decision(setup, source="finite_saw", status=status, scope=scope, text=text)
        return _Box(text, source="finite_saw", status=status, scope=scope)

    def spindle_saw_debt(self, setup, check="geometry"):
        """Keep each mounted-saw check's unresolved or failed evidence visible."""
        debts = [
            debt
            for op in setup.get("ops", [])
            if (debt := self._spindle_saw_op_debt(setup, op, check))
        ]
        if not debts:
            return ""
        return _Box(
            "; ".join(dict.fromkeys(debts)),
            source="finite_saw",
            status="error" if any(debt.status == "error" for debt in debts) else "unknown",
            scope=setup["id"],
        )

    def clearance(self, setup, tool_numbers=None):
        if saw_setup(self.bundle, setup):
            # A saw cut-off has no spindle stack or table travel: nothing to print.
            return None

        def decision(text, status="unknown", *, source="headroom", scope=None):
            self.record_decision(
                setup,
                source=source,
                status=status,
                scope=scope if scope is not None else setup["id"],
                text=text,
            )
            return text

        numbers = self.records.get(("headroom", setup["id"]), {})
        o = self.operative
        lathe = self.lathe(setup)
        spindle_debt = self.spindle_saw_debt(setup)
        if not numbers:
            return (
                "<h2>CLEARANCE</h2>"
                + (_p("STOP: " + spindle_debt + ".") if spindle_debt else "")
                + _p(decision("? Clearance not computed — check it at the machine."))
            )

        selected_machine = identity(self.bundle, setup.get("machine"), "machines")
        consumed = {entry["id"] for entry in self.collect_measurements(setup)}

        def machine_marks(field):
            return "".join(
                " " + self.measurement_marker(entry)
                for entry in numbers.get("measurements", [])
                if (entry.get("category"), entry.get("identity")) == selected_machine
                and entry.get("field") == list(field)
                and entry.get("id") in consumed
            )

        def fits(need, have, topic):
            if not (_known(need) and _known(have)):
                result = "? not computed — check at the machine"
                decision(f"{topic}: needs {o(need)} of {o(have)}: {result}.")
                return result
            if need > have:
                decision(f"{topic}: needs {o(need)} of {o(have)}: DOES NOT FIT.", "error")
                return "DOES NOT FIT"
            return "fits"

        lines = ["STOP: " + spindle_debt + "."] if spindle_debt else []
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
                    lines.append(f"{text}: {fits(need, have, topic)}.")
                elif need_key in numbers or have_key in numbers:
                    unknown.append(topic)
            if unknown:
                lines.append(
                    decision("? Not computed — check at the machine: " + "; ".join(unknown) + ".")
                )
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
                    decision(text + ".")
                elif gaps:
                    text += f"; closest planned tool stop {o(min(gaps))} mm from the jaws"
                lines.append(text + ".")
            if not lines:
                lines.append(
                    decision("? Lathe clearance not computed — check swing and tailstock room.")
                )
            body = "".join(_p(line) for line in lines)
            return f'<div class="keep"><h2>CLEARANCE — lathe</h2>{body}</div>'
        unknown = "? Not computed — check at the machine: "
        missing = []
        if "head_centre_height_mm" in numbers:
            need, have = numbers.get("sum_mm"), numbers.get("spindle_to_table_max_mm")
            if _known(need):
                lines.append(
                    f"Spindle-to-table over the dividing head: needs {o(need)} of {o(have)}"
                    f"{machine_marks(('envelope', 'spindle_to_table_max'))}: "
                    f"{fits(need, have, 'spindle-to-table room over the dividing head')}."
                )
            else:
                missing.append("spindle-to-table room over the dividing head")
        elif "bed_height_mm" in numbers or "sum_mm" in numbers:
            need, have = numbers.get("sum_mm"), numbers.get("spindle_to_table_max_mm")
            worst = next((s for s in numbers.get("stacks", []) if s.get("sum_mm") == need), {})
            if _known(need) and worst:
                lines.append(
                    f"Spindle-to-table, tallest stack (op {_text(worst.get('op'))}) with "
                    f"tool-change room: needs {o(need)} of {o(have)}"
                    f"{machine_marks(('envelope', 'spindle_to_table_max'))}: "
                    f"{fits(need, have, 'spindle-to-table room, tallest stack')}."
                )
            else:
                missing.append("spindle-to-table room")
        travel = numbers.get("travel_checks", {})
        for axis in ("x", "y"):
            record = _mapping(travel.get(axis))
            if (
                record
                and not _known(record.get("required_mm"))
                and record.get("basis") == "stock span"
            ):
                # A stock span is no cutter path: the cut's extent, approach and exit are
                # undeclared plan input, so no stroke is printed as the need (#297).
                lines.append(
                    decision(
                        f"{axis.upper()} travel{machine_marks(('envelope', 'travel', axis))}: "
                        "? not computed — the cut's X/Y extent, with the cutter's approach and "
                        "exit, is not declared."
                    )
                )
            elif record and not _known(record.get("required_mm")):
                missing.append(
                    f"{axis.upper()} travel{machine_marks(('envelope', 'travel', axis))}"
                )
            elif record and record.get("required_mm") == 0:
                continue  # No motion on this axis: no stroke to print.
            elif record:
                # Every printed need states what it is the stroke of (travel's basis).
                basis = record.get("basis")
                basis = f" ({basis})" if isinstance(basis, str) and basis != "unknown" else ""
                travel_fit = fits(
                    record.get("required_mm"), record.get("travel_mm"), axis.upper() + " travel"
                )
                lines.append(
                    f"{axis.upper()} travel: needs {o(record.get('required_mm'))}{basis} of "
                    f"{o(record.get('travel_mm'))}{machine_marks(('envelope', 'travel', axis))}: "
                    f"{travel_fit}."
                )
        rows = self.clearance_rows(setup, numbers, tool_numbers or {})
        if any(not _known(s.get("margin_mm")) for s in numbers.get("stacks", [])):
            missing.append("tool stickout and headroom")
        if missing:
            lines.append(decision(unknown + "; ".join(missing) + "."))
        # A guided sweep moves its fixture under the spindle: each fit above holds at the
        # setup pose only, so the sweep's own debt prints beside them, never a bare pass.
        lines.extend(
            decision(f"? Not proven over the sweep — {debt}.")
            for debt in numbers.get("guided_sweep_debts", [])
        )
        debts = [entry for entry in numbers.get("measurements", []) if entry.get("id") in consumed]
        if debts:
            lines.extend(decision(line) for line in self.measurement_lines(debts, setup))
            if any(entry.get("category") == "fixtures" for entry in debts):
                lines.append(
                    "Authored fixture coordinates are setup settings, not verified clearance."
                )
        html = "<h2>CLEARANCE — mill</h2>" + "".join(_p(line) for line in lines)
        if rows:
            common_action = rows[0][4]
            if common_action and all(row[4] == common_action for row in rows):
                html += _p("action for every clearance row: " + common_action)
            else:
                common_action = ""
            html += _table(
                ["op", "tool", "closest obstacle", "clearance mm"],
                [
                    _Row(row[:4], [_Plain("action: " + row[4])])
                    if row[4] and not common_action
                    else row[:4]
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
        o = self.operative if self.detail == "pedantic" else _number
        stacks = {str(s.get("op")): s for s in numbers.get("stacks", []) if isinstance(s, dict)}
        tips = _mapping(numbers.get("cut_tip_above_jaws_mm"))
        jaw = _mapping(numbers.get("jaw_obstruction")).get("jaw_top_z")
        merged = {}
        for op in setup.get("ops", []):
            name = str(op.get("op"))
            scope = f"{setup['id']}:{name}"
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
                        actions.append(
                            _Box(
                                "STOP: the tip goes below the jaw tops",
                                source="headroom",
                                status="error",
                                scope=scope,
                            )
                        )
                    elif planned <= _CRASH_ZONE_MM:
                        actions.append(
                            _Box(
                                f"TIP ABOVE {self.jaw_top_scope(setup)} {o(value)} mm — "
                                "check before plunging"
                                if self.detail != "pedantic"
                                else f"TIP {o(value)} ABOVE JAW TOP — check before plunging",
                                source="headroom",
                                status="warn",
                                kind="caution",
                                scope=scope,
                                notice_group="milling-clearance" if not self.lathe(setup) else "",
                            )
                        )
                self.reach_candidates(setup, op, candidates, actions)
            cut = self.cut_clearance(setup, op)
            if cut is not None:
                beside = f"{cut[1]} beside the cut"
                if not _known(cut[0]) or cut[0] < 0:
                    beside = _Box(
                        beside,
                        source="cut_clearance",
                        status="error" if _known(cut[0]) else "unknown",
                        scope=scope,
                    )
                if _known(cut[0]) and cut[0] < 0:
                    self.record_decision(
                        setup,
                        source="cut_clearance",
                        status="error",
                        scope=scope,
                        text="STOP: does not clear",
                    )
                candidates.append((cut[0], beside))
            known = [c for c in candidates if _known(c[0])]
            actions.extend(
                _Box(
                    f"{what}: not computed — check at the machine",
                    source=what.source if isinstance(what, _Box) else "headroom",
                    status="unknown",
                    scope=scope,
                )
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
                check = (
                    "STOP: does not clear; revise the setup before cutting"
                    if cut[0] <= 0
                    else "keep the file clear of it"
                    if hand
                    else "hand feed past it; check the cutter clears it"
                )
                text = (
                    f"{cut[1].upper()} SWEPT GAP {o(cut[0])} mm — {check}"
                    if self.detail != "pedantic" and not hand
                    else f"{cut[1].upper()} {o(cut[0])} mm FROM THE CUT — {check}"
                )
                actions.append(
                    _Box(
                        text,
                        source="cut_clearance",
                        status="error" if cut[0] <= 0 else "warn",
                        kind="block" if cut[0] <= 0 else "caution",
                        scope=scope,
                        notice_group=(
                            "milling-clearance"
                            if not hand and not self.lathe(setup) and cut[0] > 0
                            else ""
                        ),
                    )
                )
            if (
                _known(value)
                and value < 0
                and not any(
                    isinstance(action, _Box) and action.status == "error" and action.kind == "block"
                    for action in actions
                )
            ):
                actions.append(
                    _Box(
                        "STOP: does not clear",
                        source=what.source if isinstance(what, _Box) else "headroom",
                        status="error",
                        scope=scope,
                    )
                )
            for action in actions:
                if isinstance(action, _Box):
                    self.record_decision(
                        setup,
                        source=action.source,
                        status=action.status,
                        scope=scope,
                        text=str(action),
                        kind=action.kind,
                        notice_group=action.notice_group,
                    )
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
        if spindle_saw(self.bundle, setup, op):
            # Finite disks have sweep/capture evidence, not axial endmill projection.
            debt = self._spindle_saw_op_debt(setup, op, "reach")
            if debt:
                actions.append(debt)
            return
        record = _mapping(self.records.get(("reach", f"{setup['id']}:{op.get('op')}")))
        if not record:
            return
        scope = f"{setup['id']}:{op.get('op')}"

        def candidate(value, what):
            if value is not None and (not _known(value) or value < 0):
                status = "error" if _known(value) else "unknown"
                what = _Box(what, source="reach", status=status, scope=scope)
                text = (
                    "STOP: does not clear"
                    if status == "error"
                    else f"{what}: not computed — check at the machine"
                )
                self.record_decision(setup, source="reach", status=status, scope=scope, text=text)
            candidates.append((value, what))

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
            candidate(entry.get("mm", "unknown"), what)
        if top == "not_applicable":
            # No stock stands beside the tool above its tip.
            return
        if not (_known(reach) and _known(projection)):
            candidate("unknown", f"holder face to the {beside}")
            return
        above = projection - reach
        if above >= 0:
            candidate(above, f"holder face to the {beside}")
        elif hits == 0:
            candidate(
                None, f"holder goes {o(-above)} below the {beside}; checked clear of the walls"
            )
        else:
            candidate("unknown", f"holder {o(-above)} below the {beside}, to the walls")
        past = _known(flute) and reach > flute + SAME_Z
        if past and _known(hits) and hits > 0:
            text, status = "STOP: the holder hits a wall beside the cut", "error"
        elif past and not _known(hits):
            text, status = (
                "holder clearance of the walls not proven — check at the machine",
                "unknown",
            )
        else:
            return
        action = _Box(text, source="reach", status=status, scope=scope)
        actions.append(action)
        self.record_decision(
            setup, source=action.source, status=action.status, scope=scope, text=str(action)
        )

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
        return self.surface_z(setup, op.get(key), face=op_feature(op), done=done, path=True)

    @property
    def near_jaw_mm(self):
        """The shop's declared distance from spinning jaws inside which an op row carries
        its jaw clearance; without one, only the crash zone boxes a row."""
        near = _mapping(self.bundle.policy.get("numbers")).get("near_jaw_mm")
        return near if _known(near) else _CRASH_ZONE_MM

    def jaw_top_scope(self, setup):
        """The headroom rule uses the common top plane of a vise's two jaws."""
        fixture = resolve(self.bundle, "workholding", _mapping(setup.get("hold")).get("fixture"))
        return "BOTH JAW TOPS (VERTICAL)" if _mapping(fixture).get("kind") == "vise" else "JAW TOP"

    def crash_boxes(self, setup, op):
        boxes = []
        o = self.operative if self.detail == "pedantic" else _number
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
                boxes.append(
                    _Box(
                        f"JAWS Z {o(jaw)}: {o(gap)} clear — hand feed to a stop",
                        source="headroom",
                        status="warn",
                        kind="caution",
                    )
                )
            elif gap is not None and gap <= self.near_jaw_mm:
                boxes.append(
                    _Box(
                        f"JAWS Z {o(jaw)}: {o(gap)} clear — disengage the feed early, "
                        "hand feed to the end",
                        source="headroom",
                        status="warn",
                        kind="caution",
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
                    boxes.append(
                        _Box(
                            f"DEAD CENTRE Z {o(tip[2])}: start clear of it",
                            source="headroom",
                            status="warn",
                            kind="caution",
                        )
                    )
            return boxes
        cut = self.cut_clearance(setup, op)
        if cut is not None and _known(cut[0]) and cut[0] <= _CRASH_ZONE_MM:
            hand = op.get("do") in HAND_FINISH
            check = (
                "STOP: does not clear; revise the setup before cutting"
                if cut[0] <= 0
                else "keep the file clear of it"
                if hand
                else "hand feed past it; check the cutter clears it"
            )
            boxes.append(
                _Box(
                    f"{cut[1].upper()} SWEPT GAP {o(cut[0])} mm — {check}"
                    if self.detail != "pedantic" and not hand
                    else f"{cut[1].upper()} {o(cut[0])} mm FROM THE CUT — {check}",
                    source="cut_clearance",
                    status="error" if cut[0] <= 0 else "warn",
                    kind="block" if cut[0] <= 0 else "caution",
                    notice_group="milling-clearance" if not hand and cut[0] > 0 else "",
                )
            )
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
            boxes.append(
                _Box(
                    f"TIP ABOVE {self.jaw_top_scope(setup)} {o(value)} mm — check before plunging"
                    if self.detail != "pedantic"
                    else f"TIP {o(value)} ABOVE JAW TOP — check before plunging",
                    source="headroom",
                    status="warn",
                    kind="caution",
                    notice_group="milling-clearance",
                )
            )
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

    def handwheel_zero(self, setup, tools):
        settings = _mapping(self.plan.get("dro"))
        authored = _mapping(setup.get("zero"))
        facts = handwheel_readout(self.bundle)
        units = readout_units(self.bundle)

        def known(value):
            return isinstance(value, str) and value.strip() not in ("", "unknown")

        def unresolved(text, scope=None):
            self.record_decision(
                setup,
                source="zero_check",
                status="unknown",
                scope=scope if scope is not None else f"{setup['id']}:readout",
                text=text,
            )
            return text

        pieces = [
            f"<h2>HANDWHEEL / SCALE ZERO — {escape(self.zero_name(setup))}, "
            f"{escape(_text(units))}</h2>",
            _p(
                "Nominal model targets are not physical dial settings. Establish each pickup "
                "from the part and the source procedure; a model coordinate of zero does not "
                "establish a handwheel zero."
            ),
        ]
        for procedure in (settings.get("procedure"), authored.get("procedure")):
            if known(procedure):
                pieces.append(_p(self.bench(procedure, setup)))
        graduation = facts["graduation"]
        mode = facts["x_scale"]
        if _known(graduation):
            scale = f", X {mode} scale" if self.lathe(setup) and mode != "unknown" else ""
            line = f"Source graduation: {_number(graduation)} {_text(units)} per division{scale}"
            if self.lathe(setup) and mode == "diameter":
                line += f" ({_number(graduation / 2)} {_text(units)} radial travel)"
            pieces.append(_p(line + "; nominal source marking, not verified calibration."))
        else:
            pieces.append(_p(unresolved("STOP: mechanical scale graduation is unknown.")))
        for label, key in (("Calibration", "calibration"), ("Backlash take-up", "backlash")):
            value = settings.get(key)
            pieces.append(
                _p(f"{label}: {self.bench(value, setup)}.")
                if known(value)
                else _p(
                    unresolved(f"STOP: {label.lower()} is unknown; establish it before cutting.")
                )
            )
        if units not in ("mm", "in"):
            pieces.append(_p(unresolved("STOP: mechanical readout units are unknown.")))
        directions = _mapping(settings.get("direction"))
        axes = ("x", "z") if self.lathe(setup) else ("x", "y", "z")
        rows = []
        for axis in axes:
            scope = f"{setup['id']}:{axis}"
            touch = _mapping(authored.get(axis))
            procedure = touch.get("procedure")
            if not known(procedure):
                method = touch.get("method")
                procedure = _METHODS.get(method, method) if known(method) else "?"
                if not known(method):
                    unresolved("STOP: physical pickup procedure unknown", scope)
            target = touch.get("face", touch.get("edge", touch.get("feature")))
            if axis == "x" and touch.get("method") == "trial_cut_measure":
                contact = "trial-cut stock diameter; measure with spindle stopped"
            elif known(target):
                contact = self.bench(target, setup)
                if "face" not in touch and "edge" not in touch:
                    contact = "nominal reference: " + contact
            else:
                contact = unresolved("? physical contact not established", scope)
            direction = directions.get(axis)
            if known(direction):
                contact += "; positive: " + self.positive_direction(
                    axis, direction, self.lathe(setup)
                )
            else:
                contact += "; " + unresolved("STOP: positive direction unknown", scope)
            tool = touch.get("tool")
            if known(tool):
                contact += "; " + self.touched_tool(tool, tools, "spindle")
            gauge = touch.get("gauge")
            if known(gauge):
                contact += "; " + self.short_reference(gauge, "gauges")
            if touch.get("after_op") not in (None, "unknown"):
                contact += f"; after op {_text(touch['after_op'])}"
            setting = touch.get("dial_setting")
            physical = (
                f"{_number(setting)} {_text(units)} (authored physical reading)"
                if _known(setting) and units in ("mm", "in")
                else unresolved("STOP: physical dial setting unknown", scope)
            )
            rows.append((axis.upper(), contact, self.bench(procedure, setup), physical))
        pieces.append(
            _table(
                ["axis", "physical pickup", "pickup procedure", "physical dial setting"],
                rows,
                css="zero handwheel-zero",
                widths=[7, 28, 42, 23],
            )
        )
        touches = authored.get("tool_touches")
        for touch in touches if isinstance(touches, list) else []:
            name = self.touched_tool(touch.get("tool"), tools, "tools")
            methods = [touch.get("x_method"), touch.get("method")]
            words = "; ".join(
                self.bench(_METHODS.get(m, m).rstrip().rstrip(".;:!?").rstrip(), setup)
                for m in methods
                if known(m)
            )
            before = touch.get("before_ops")
            when = (
                "Before " + _ops_label(before) + ": " if isinstance(before, list) and before else ""
            )
            if touch.get("after_op") not in (None, "unknown"):
                when += f"after op {_text(touch['after_op'])}, "
            text = (
                f"{when}{name} — {words or 'STOP: physical pickup procedure unknown'}. "
                "STOP: establish its actual scale/dial reference and contact compensation; "
                "no physical tool-change setting is inferred from nominal geometry."
            )
            for scope in (
                [f"{setup['id']}:{op}" for op in before]
                if isinstance(before, list) and before
                else [setup["id"]]
            ):
                unresolved(text, scope)
            pieces.append(_p(text))
        if self.lathe(setup) and mode == "unknown":
            pieces.append(
                _p(unresolved("STOP: X scale reads radius or diameter — not established."))
            )
        pieces.append(_p("STOP: " + unresolved(facts["debt"]) + "."))
        return "".join(pieces)

    def contact_label(self, face):
        """A fixture-face reference as its shop item and touchable named face."""
        if isinstance(face, str) and face.startswith("fixture:"):
            reference, slash, surface = face.removeprefix("fixture:").partition("/")
            solid, colon, normal = surface.rpartition(":")
            if slash and colon and normal in ("+x", "-x", "+y", "-y", "+z", "-z"):
                return (
                    self.reference(reference, "fixtures")
                    + " "
                    + _text(solid)
                    + " "
                    + normal.upper()
                    + " face"
                )
        return self.bench(face)

    @functools.cached_property
    def mounted_datum_groups(self):
        """Identical proved recipes share only their common setting, never a touch."""
        groups = {}
        for setup in self.plan.get("setups", []):
            sid = setup["id"]
            if self.finding_statuses.get(("zero_check", sid)) != "pass":
                continue
            zero = _mapping(setup.get("zero"))
            axes = _mapping(self.records.get(("zero_check", sid), {}).get("axes"))
            saws = [op for op in setup.get("ops", []) if spindle_saw(self.bundle, setup, op)]
            if len(saws) != 1 or _mapping(axes.get("z")).get("method") != "mounted_saw_side":
                continue
            signature, heights = [], []
            for axis in ("x", "y", "z"):
                touch, record = _mapping(zero.get(axis)), _mapping(axes.get(axis))
                if (
                    record.get("axis_set_status") != "computed"
                    or not all(
                        _known(record.get(key))
                        for key in ("edge_mm", "axis_set", "check_reading", "mirrored_reading")
                    )
                    or any(touch.get(key) != record.get(key) for key in ("face", "method", "from"))
                    or any(
                        identity(self.bundle, touch.get(key), slot)
                        != identity(self.bundle, record.get(key), slot)
                        for key, slot in (("tool", "spindle"), ("holder", "holders"))
                    )
                ):
                    break
                common = {
                    key: record.get(key)
                    for key in (
                        "edge",
                        "face",
                        "method",
                        "from",
                        "edge_mm",
                        "radius_mm",
                        "paper_mm",
                        "axis_set",
                        "check_reading",
                        "mirrored_reading",
                        "check_jog_mm",
                        "jog_mm",
                        "mounted_saw_setting",
                        "mounted_saw",
                    )
                }
                common["tool"] = identity(self.bundle, touch.get("tool"), "spindle")
                common["holder"] = identity(self.bundle, touch.get("holder"), "holders")
                at = record.get("at_mm")
                if axis != "z":
                    proof = _mapping(record.get("pickup_proof"))
                    path = _mapping(proof.get("path"))
                    point, top = path.get("contact_mm"), path.get("stock_top_mm")
                    retract = path.get("retract_height_mm")
                    approach = _mapping(proof.get("request")).get("approach_mm")
                    if (
                        proof.get("status") != "pass"
                        or not isinstance(at, list)
                        or len(at) != 2
                        or not all(map(_known, at))
                        or not isinstance(point, list)
                        or len(point) != 3
                        or not all(_known(value) for value in (point[2], top, retract, approach))
                    ):
                        break
                    heights.append(at[1])
                    common["at_lateral_mm"] = at[0]
                    common["clearances_mm"] = [
                        _number(top - point[2]),
                        _number(approach),
                        _number(retract - top),
                    ]
                else:
                    common["at_mm"] = at
                signature.append(common)
            else:
                if signature[0]["clearances_mm"] != signature[1]["clearances_mm"]:
                    continue
                plane = _mapping(saws[0].get("cut_plane"))
                if plane.get("axis") != "z" or not _known(plane.get("value")):
                    continue
                key = (self.mount_key(setup)[0], json.dumps(signature, sort_keys=True))
                groups.setdefault(key, []).append((setup, axes, signature, heights, saws[0]))
        return {
            item[0]["id"]: group for group in groups.values() if len(group) > 1 for item in group
        }

    def mounted_saw_xy(self, record):
        """Distinct literal-mm body-contact and arbor positions from the zero record."""
        mounted = _mapping(record.get("mounted_saw"))
        scale = {"mm": 1.0, "in": 25.4}.get(self.units)
        positions = []
        for field, label, size in (
            ("point_mm", "Blade-body contact", 3),
            ("axis_xy_mm", "arbor axis", 2),
        ):
            values = mounted.get(field)
            if not isinstance(values, (list, tuple)) or len(values) != size:
                values = (None, None)
            coordinates = "/".join(
                axis + (self.readout(value / scale) if scale and _known(value) else "?")
                for axis, value in zip("XY", values[:2], strict=True)
            )
            positions.append(f"{label} {coordinates}")
        return "; ".join(positions)

    def mounted_datum_table(self, setup):
        group = self.mounted_datum_groups.get(setup["id"])
        if not group:
            return None
        if group[0][0]["id"] != setup["id"]:
            return ""
        _, axes, signature, _, _ = group[0]
        scale = {"mm": 1.0, "in": 25.4}.get(self.units)
        if scale is None:
            return None

        def mm(value):
            return self.readout(value / scale) if _known(value) else "?"

        def jog(record, axis):
            value = record.get("check_jog_mm", record.get("jog_mm"))
            if not _known(value):
                return f"{axis}?"
            return f"{'−' if value < 0 else '+'}{axis}{self.readout(abs(value))}"

        xy = []
        for axis, other, record, common in zip(
            "XY", "YX", (axes["x"], axes["y"]), signature[:2], strict=True
        ):
            xy.append(
                f"{record.get('edge', record.get('face'))} {axis}{self.readout(record['edge_mm'])}"
                + f" at {other}{mm(common['at_lateral_mm'])}"
                + f"; Axis Set {axis}{self.readout(record['axis_set'])}"
            )
            if self.detail == "hobby":
                xy[-1] += (
                    "; "
                    f"{jog(record, axis)} "
                    f"check {self.readout(record['check_reading'])}; "
                    f"{self.readout(record['mirrored_reading'])} reversed: STOP"
                )
        z = axes["z"]
        setting = _mapping(z.get("mounted_saw_setting"))
        side = {"minus_z": "lower", "plus_z": "upper"}.get(setting.get("blade_side"), "selected")
        clearance = signature[0]["clearances_mm"]
        text = "Saw datums: " + "; ".join(xy) + ". "
        text += (
            f"Finder before saw: tip {mm(abs(float(clearance[0])))} "
            + ("below" if float(clearance[0]) >= 0 else "above")
            + " current top, "
            f"stand-off {mm(float(clearance[1]))}, retract {mm(float(clearance[2]))} above. "
            f"Every cut: fresh stopped {side} body-side touch at "
            f"{self.contact_label(z.get('face'))} Z{self.readout(z['edge_mm'])}, "
            f"{self.mounted_saw_xy(z)}; "
            f"{mm(setting.get('paper_mm'))} paper; "
            f"Axis Set cutting midplane Z{self.readout(z['axis_set'])}."
        )
        if self.detail == "hobby":
            text += (
                f" Use {mm(setting.get('body_thickness_mm'))} body thickness/2, "
                f"plus {mm(setting.get('kerf_offset_mm'))} cutting-band offset; "
                "not kerf width or blade radius. "
                f"{jog(z, 'Z')} check "
                f"{self.readout(z['check_reading'])}; "
                f"{self.readout(z['mirrored_reading'])} reversed: STOP."
            )
        elif _known(setting.get("kerf_offset_mm")) and setting["kerf_offset_mm"] != 0:
            text += f" Cutting-band offset {mm(setting['kerf_offset_mm'])}."
        same_height = all(item[3][0] == item[3][1] for item in group)
        headings = (
            ["Setup", "Finder Z ref.", "Cut Z"]
            if same_height
            else ["Setup", "X finder Z ref.", "Y finder Z ref.", "Cut Z"]
        )
        rows = [
            [
                item[0]["id"],
                *([mm(item[3][0])] if same_height else map(mm, item[3])),
                self.readout(item[4]["cut_plane"]["value"]),
            ]
            for item in group
        ]
        widths = None
        if self.detail != "pedantic" and 1 < len(rows) <= 4:
            headings, rows = (
                ["Setting", *(row[0] for row in rows)],
                [
                    [heading, *(row[index] for row in rows)]
                    for index, heading in enumerate(headings[1:], 1)
                ],
            )
            widths = [18, *([82 / (len(headings) - 1)] * (len(headings) - 1))]
        return _p(text) + _table(headings, rows, css="mounted-datums", widths=widths)

    def dro_guide_id(self, setup):
        """A lathe lesson cannot stand in for the milling check-jog procedure."""
        return "dro-first-use-lathe" if self.lathe(setup) else "dro-first-use-mill"

    def dro(self, setup, tools, *, procedure="inline"):
        detail = getattr(self, "detail", "pedantic")
        separate_instructions = procedure == "separate"
        compact_rows = []
        compact_axes = {}
        pickup_recipes = {}
        compact_debts = []
        mounted_setup = any(spindle_saw(self.bundle, setup, op) for op in setup.get("ops", []))
        guide_id = self.dro_guide_id(setup)
        taught = getattr(self, "_dro_guides_seen", set())
        first_lesson = detail == "hobby" and guide_id not in taught

        def unresolved(text, scope, status="unknown", source="zero_check", notice_group=""):
            self.record_decision(
                setup,
                source=source,
                status=status,
                scope=scope,
                text=text,
                notice_group=notice_group,
            )
            compact_debts.append((scope, text))

        def mounted_lesson(record):
            mounted = _mapping(record.get("mounted_saw_setting"))
            if not mounted or detail == "pro":
                return ""
            signature = tuple(
                mounted.get(key) for key in ("blade_side", "body_thickness_mm", "kerf_offset_mm")
            )
            taught = getattr(self, "_mounted_saw_lessons", set())
            if signature in taught:
                return ""
            self._mounted_saw_lessons = taught | {signature}
            scale = {"mm": 1.0, "in": 25.4}.get(self.units)

            def shown(key):
                value = mounted.get(key)
                return self.readout(value / scale) if _known(value) and scale else "?"

            sense = {"minus_z": "+", "plus_z": "−"}.get(mounted.get("blade_side"), "?")
            return (
                f"body-side setting: {shown('edge_mm')} {sense} ({shown('paper_mm')} paper + "
                f"{shown('body_thickness_mm')} body / 2) + {shown('kerf_offset_mm')} "
                "cutting-band offset; use body thickness, not kerf width or blade radius"
            )

        if saw_setup(self.bundle, setup):
            # The saw cut is located by its cut plane in the op row: no zero to set.
            return None
        kind = readout_kind(self.bundle)
        if kind == "handwheel":
            unresolved(handwheel_readout(self.bundle)["debt"], f"{setup['id']}:readout")
            return self.handwheel_zero(setup, tools)
        if kind != "digital":
            unresolved(
                "Readout kind and physical pickup procedure are unknown.", f"{setup['id']}:readout"
            )
            return "<h2>READOUT ZERO</h2>" + _p(
                "STOP: readout kind is unknown; establish the instrument and physical pickup "
                "procedure before cutting. No digital or mechanical settings are inferred."
            )
        spindle_debt = self.spindle_saw_debt(setup, "zero")
        saw_warning = (
            "STOP: " + spindle_debt + "; mounted-blade zero setting "
            "is unresolved, not an axial endmill touch-off."
        )
        if spindle_debt:
            unresolved(saw_warning, f"{setup['id']}:mounted-saw")
        numbers = self.records.get(("zero_check", setup["id"]), {})
        authored = _mapping(setup.get("zero"))
        settings = _mapping(self.plan.get("dro"))
        lathe = self.lathe(setup)
        o = self.readout
        mode = "linear"
        if lathe:
            mode = (
                "radius"
                if settings.get("radius_mode") is True
                else "diameter"
                if settings.get("radius_mode") is False
                else "? radius/diameter"
            )
        pieces = (
            [
                f"<h2>DRO ZERO — {escape(self.zero_name(setup))}, "
                f"{escape(_text(readout_units(self.bundle)))}, {escape(mode)} mode</h2>"
            ]
            if detail == "pedantic"
            else []
        )
        if spindle_debt:
            pieces.append(_p(saw_warning))
        if setup.get("zero") == "unknown" or not authored:
            message = "STOP: no zero recipe — touch, Axis Set and jog checks not planned."
            pieces.append(_p(message))
            unresolved(message, f"{setup['id']}:zero")
        units = readout_units(self.bundle)
        if units not in ("mm", "in"):
            message = "STOP: digital readout units are unknown; no numeric settings are inferred."
            pieces.append(_p(message))
            unresolved(message, f"{setup['id']}:readout-units")
        if settings.get("mode") != "abs":
            message = "STOP: establish ABS mode before setting the datum."
            pieces.append(_p(message))
            unresolved(
                message,
                f"{setup['id']}:readout-mode",
                "unknown" if settings.get("mode") in (None, "unknown") else "error",
            )
        if lathe and mode == "? radius/diameter":
            message = "STOP: X display reads radius or diameter — not established."
            pieces.append(_p(message))
            unresolved(message, f"{setup['id']}:x-display")
        directions = _mapping(settings.get("direction"))
        direction_line = "; ".join(
            f"{axis.upper()}+ {self.positive_direction(axis, value, lathe)}"
            for axis, value in directions.items()
            if axis in ("x", "y", "z") and not (lathe and axis == "y")
        )
        if direction_line and detail == "pedantic":
            pieces.append(_p("Tool-relative positive directions: " + direction_line + "."))
        authored_procedure = authored.get("procedure")
        if (
            not separate_instructions
            and isinstance(authored_procedure, str)
            and authored_procedure not in ("", "unknown")
        ):
            pieces.append(_p(self.bench(authored_procedure, setup)))
        # Executed order: the part is indicated true (or aligned) before any tool touches it.
        transfer = _mapping(authored.get("transfer"))
        if transfer:
            pieces.append(_p(self.transfer_line(setup, transfer) + ".", "zero-transfer"))
        touch_set = _mapping(numbers.get("touch_set"))
        if touch_set.get("axes"):
            # A guided-sweep setup (#255): the touch-off on the master sets X and Y.
            named = " and ".join(str(axis).upper() for axis in touch_set["axes"])
            ops = ", ".join(f"op {op}" for op in touch_set.get("ops", []))
            how = (
                "puts the cutter where its rails' pin-lines cross: with the spindle on that "
                "crossing, lock them for the whole sweep and never move them"
                if touch_set.get("by") == "trammel"
                else "sets them by touching the cutter to its master, then locks them for "
                "the whole sweep"
            )
            pieces.append(
                _p(
                    f"{named}: no edge pickup. The guided sweep ({ops}) {how}; see its "
                    "contour sheet."
                )
            )
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
        lesson_examples = []
        # A swivelled vise stands the work's edges off the travel: an edge touch there sets
        # nothing, so it prints a STOP instead of a pick-up (zero_check, #300).
        slanted = set(numbers.get("swivel_unproven_axes") or [])
        for axis in ("x", "y", "z"):
            if axis not in authored and axis not in axes:
                continue
            if axis.upper() in slanted:
                unresolved(
                    f"{axis.upper()} edge pickup is unproved with the swivelled vise.",
                    f"{setup['id']}:{axis}",
                    "unsupported",
                )
                if detail == "pedantic":
                    pieces.append(
                        _p(
                            f"STOP: {axis.upper()} zero — the vise is swivelled, so a touch on the "
                            f"work's edge does not set {axis.upper()}; pick it up by indicating a "
                            "bore's centre. Do not run."
                        )
                    )
                continue
            computed = axes.get(axis, {})
            if computed.get("tool_setting_state") == "unsupported_spindle_saw":
                continue
            touch = dict(_mapping(authored.get(axis)))
            for key in ("radius_mm", "paper_mm", "edge_mm", "method"):
                if key in computed:
                    touch[key] = computed[key]
            scope = f"{setup['id']}:{axis}"
            sign = computed.get("sign")
            direction = directions.get(axis)
            positive, negative = _SIGNS.get(axis, (set(), set()))
            if sign == -1 or direction in negative:
                unresolved(
                    f"{axis.upper()} positive readout direction is reversed.", scope, "error"
                )
            elif sign not in (-1, 1) and direction not in positive:
                unresolved(f"{axis.upper()} positive readout direction is unknown.", scope)
            target = touch.get("edge", touch.get("face", touch.get("feature")))
            contact = [self.bench(target) if target else "? contact not set"]
            zero_surface = None
            method = touch.get("method")
            opposed = method == "opposed_edge_midpoint"
            indicate = method == "indicate_axis" or touch.get("from") == "indicated"
            tool = None
            if "tool" in touch:
                tool = (
                    "? tool not chosen"
                    if touch["tool"] in (None, "unknown")
                    else self.touched_tool(touch["tool"], tools, "spindle")
                )
            if opposed:
                contacts = computed.get("actual_contact_readings")
                move = computed.get("midpoint_move")
                if (
                    isinstance(contacts, list)
                    and len(contacts) == 2
                    and all(
                        isinstance(value, str) and value not in ("", "unknown")
                        for value in contacts
                    )
                    and isinstance(move, str)
                    and move not in ("", "unknown")
                    and computed.get("axis_set_at") == "measured_opposed_midpoint"
                ):
                    contact.append(
                        f"same finder: take actual −{axis.upper()} contact {contacts[0]} and "
                        f"+{axis.upper()} contact {contacts[1]} without resetting between them; "
                        f"move the spindle to {move}, then Axis Set {axis.upper()} "
                        f"{self.reading(computed.get('axis_set'))} at that actual midpoint, "
                        "not at either contact"
                    )
                    if computed.get("part_result") == "not_recorded":
                        contact.append("actual contact readings are required, not prefilled")
                else:
                    message = (
                        f"STOP: {axis.upper()} opposed-edge contact readings and midpoint "
                        "procedure are unresolved; no contact-position Axis Set is inferred."
                    )
                    contact.append(message)
                    unresolved(message, scope)
                midpoint_status = computed.get("midpoint_status", "unknown")
                if midpoint_status != "pass":
                    reasons = computed.get("midpoint_reasons")
                    reason_text = (
                        "; ".join(self.bench(reason, setup) for reason in reasons)
                        if isinstance(reasons, list) and reasons
                        else "same-finder opposed-edge midpoint procedure is unproved"
                    )
                    message = f"STOP: {axis.upper()} midpoint — {reason_text}."
                    contact.append(message)
                    unresolved(message, scope, midpoint_status)
            elif indicate:
                contact.append(self.indicate_recipe(setup, axis, target, authored, tool))
            elif method == "mounted_saw_side":
                contact.append(self.mounted_saw_contact(computed))
            elif method not in (None, "paper", "touch"):
                contact.append(_METHODS.get(method, _text(method)))
            pickup = self.pickup_contact(axis, computed)
            if pickup:
                contact.append(pickup)
                if isinstance(pickup, _Box):
                    self.record_decision(
                        setup,
                        source=pickup.source,
                        status=pickup.status,
                        kind=pickup.kind,
                        scope=scope,
                        text=str(pickup),
                    )
            procedure = touch.get("procedure")
            if isinstance(procedure, str) and procedure not in ("", "unknown"):
                contact.append(self.bench(procedure, setup))
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
            if (
                axis == "z"
                and _known(edge)
                and (_carried(computed) or method == "mounted_saw_side")
            ):
                # A carried height: the report's typed setting and jog readings print
                # as computed; the surface retains its separate physical height.
                shown_edge = (
                    self.physical(edge) if readout_units(self.bundle) == self.units else o(edge)
                )
            elif axis == "z" and _known(edge):
                # The touched surface as the DRO shows it; Axis Set and the jog readings
                # move with it.
                done = self.ops_done(setup, after=touch.get("after_op"))
                face = touch.get("face", touch.get("feature"))
                surface = self.datum_z(setup, face, edge, done)
                if not _known(surface) and self.fresh_top_setting(setup):
                    surface = edge
                readings = {
                    key: (value + surface - edge if _known(surface) else "unknown")
                    if _known(value)
                    else value
                    for key, value in readings.items()
                }
                edge = surface
                shown_edge = o(edge)
            else:
                if axis == "z" and method in (None, "paper", "touch"):
                    readings = {key: "unknown" for key in readings}
                shown_edge = o(edge)
            measured = opposed or method in {
                "trial_cut_measure",
                "face_then_set",
                "measure_then_set",
            }
            if _known(edge) and touch.get("from") != "indicated" and not measured:
                shown_surface = f"surface at {shown_edge}"
                start = len("; ".join(contact)) + 2
                if isinstance(target, str) and target not in ("", "unknown"):
                    zero_surface = (axis, target, start, start + len(shown_surface))
                contact.append(shown_surface)
            radius = touch.get("radius_mm")
            if (
                detail == "pedantic"
                and _known(radius)
                and radius
                and touch.get("from") != "indicated"
            ):
                contact.append(f"edge-finder radius {o(radius)}")
            finder = _mapping(computed.get("finder"))
            if finder and finder.get("status") != "pass":
                message = "STOP: finder speed/contact/offset is unresolved" + (
                    ": " + ", ".join(finder["missing"]) if finder.get("missing") else ""
                )
                contact.append(message)
                unresolved(
                    message,
                    f"{scope}:{touch.get('tool')}",
                    finder.get("status", "unknown"),
                    "finder",
                )
            paper = touch.get("paper_mm")
            if _known(paper):
                contact.append(f"paper {o(paper)}" if paper else "direct contact, no paper")
            if touch.get("after_op") not in (None, "unknown"):
                contact.append(f"after op {_text(touch['after_op'])}")
            outside = _touch_outside(computed)
            if outside:
                contact.append(outside)
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
            jog = computed.get("check_jog_mm", computed.get("jog_mm"))
            jog_direction = "−" if _known(jog) and jog < 0 else "+"
            setting = self.reading(readings["axis_set"])
            if setting == "?":
                location = "midpoint" if opposed else "contact"
                unresolved(
                    f"{axis.upper()} {location} Axis Set is unknown.",
                    scope,
                    notice_group=f"{_ZERO_SETTING}|{axis.upper()} {location} Axis Set|",
                )
            elif opposed:
                setting += " at actual midpoint"
            if not _known(jog):
                unresolved(f"{axis.upper()} check-jog distance is unknown.", scope)
            if _known(jog) and (
                readings["check_reading"] in (None, "unknown")
                or readings["mirrored_reading"] in (None, "unknown")
            ):
                unresolved(
                    f"{axis.upper()} check-jog reading is unknown.",
                    scope,
                    notice_group=f"{_ZERO_SETTING}|{axis.upper()} check-jog reading|",
                )
            if (
                _known(jog)
                and jog > 0
                and _known(readings["axis_set"])
                and _known(readings["check_reading"])
            ):
                lesson_examples.append(
                    (
                        0
                        if units == "in" and math.isclose(readout_value(self.bundle, jog), 0.25)
                        else 1,
                        f"From {axis.upper()} {setting}, jog +{axis.upper()} {o(jog)} {units}: "
                        + (
                            f"expect {expected}; {mirrored} = reversed — STOP, correct direction, "
                            "then re-establish the datum."
                            if detail == "hobby"
                            else f"it must read {expected}; {mirrored} means reversed — STOP and "
                            "correct the direction before re-establishing the datum."
                        ),
                    )
                )
            explanation = mounted_lesson(computed)
            if explanation:
                contact.append(explanation)
            if detail != "pedantic":
                # The full recipe above still produces every decision. Project its
                # datum and exceptional contact geometry, not an ordinary DRO worksheet.
                brief = [self.contact_label(target) if target else "? contact not set"]
                if opposed:
                    brief.append(
                        f"actual midpoint {axis.upper()}{self.reading(readings['axis_set'])}"
                    )
                    if computed.get("part_result") != "not_recorded":
                        brief.append(
                            "actual contacts "
                            + " / ".join(
                                str(value) for value in computed.get("actual_contact_readings", [])
                            )
                        )
                elif _known(edge):
                    brief.append(f"{axis.upper()}{shown_edge}")
                else:
                    brief.append(f"{axis.upper()}?")
                if (
                    indicate
                    or touch.get("measure")
                    or method in {"trial_cut_measure", "face_then_set", "measure_then_set"}
                ):
                    debts = {text for _, text in compact_debts}
                    brief = [
                        part for part in contact if not isinstance(part, _Box) and part not in debts
                    ]
                else:
                    if method not in (
                        None,
                        "paper",
                        "touch",
                        "opposed_edge_midpoint",
                        "mounted_saw_side",
                    ):
                        brief.append(self.bench(_METHODS.get(method, _text(method)), setup))
                    if method == "mounted_saw_side":
                        brief.append("fresh stopped " + self.mounted_saw_contact(computed))
                        brief.append(self.mounted_saw_xy(computed))
                    at = touch.get("at_mm")
                    scale = {"mm": 1.0, "in": 25.4}.get(self.units)

                    def physical_reading(value, scale=scale):
                        return o(value / scale) if _known(value) and scale else "?"

                    if (
                        isinstance(at, list)
                        and len(at) == 2
                        and (
                            method == "mounted_saw_side"
                            or detail == "hobby"
                            and axis != "z"
                            or mounted_setup
                            and axis != "z"
                        )
                    ):
                        labels = "XY" if axis == "z" else ("YZ" if axis == "x" else "XZ")
                        brief.append(
                            ("pickup reference at " if method == "mounted_saw_side" else "at ")
                            + "/".join(
                                label + physical_reading(value)
                                for label, value in zip(labels, at, strict=True)
                            )
                        )
                    proof = _mapping(computed.get("pickup_proof"))
                    path = _mapping(proof.get("path"))
                    point, top = path.get("contact_mm"), path.get("stock_top_mm")
                    retract = path.get("retract_height_mm")
                    approach = _mapping(proof.get("request")).get("approach_mm")
                    if (
                        (mounted_setup or first_lesson)
                        and axis in ("x", "y")
                        and (isinstance(point, list) and len(point) == 3)
                    ):
                        recipe = []
                        if _known(top) and _known(point[2]):
                            recipe.append(
                                f"tip {physical_reading(abs(top - point[2]))} "
                                + ("below" if top >= point[2] else "above")
                                + " current top"
                            )
                        if _known(approach):
                            recipe.append(f"stand-off {physical_reading(approach)}")
                        if _known(retract) and _known(top):
                            recipe.append(
                                f"retract {physical_reading(retract - top)} above current top"
                            )
                        if recipe:
                            pickup_recipes.setdefault(tuple(recipe), []).append(axis.upper())
                    if _known(paper) and (first_lesson or method == "mounted_saw_side"):
                        brief.append(f"{o(paper)} paper" if paper else "direct contact")
                    if touch.get("after_op") not in (None, "unknown"):
                        brief.append(f"after op {_text(touch['after_op'])}")
                    if outside:
                        brief.append(outside)
                    if explanation and (mounted_setup or detail == "hobby"):
                        brief.append(explanation)
                    if procedure and _FIELD.search(procedure):
                        brief.append(self.bench(procedure, setup))
                brief.append(f"Axis Set {axis.upper()}{setting}")
                if detail == "hobby" and mounted_setup and axis in ("x", "y"):
                    brief.append(
                        f"{jog_direction}{axis.upper()} "
                        f"{o(abs(jog)) if _known(jog) else '?'} jog "
                        f"reads {expected}; {mirrored} reversed: STOP"
                    )
                compact_rows.append("; ".join(brief))
                compact_axes[axis] = "; ".join(brief)
            row = _Row(
                (
                    axis.upper(),
                    "; ".join(contact),
                    setting,
                    f"{jog_direction}{axis.upper()} {o(abs(jog)) if _known(jog) else '?'}",
                    expected,
                    mirrored,
                )
            )
            row.zero_surface = zero_surface
            rows.append(row)
        first_use = detail != "pro" and bool(rows) and guide_id not in taught
        lesson = []
        if first_use:
            self._dro_guides_seen = taught | {guide_id}
            readout_unit_label = (
                "inches"
                if units == "in"
                else units
                if units == "mm"
                else "the established readout units"
            )
            lesson.append(
                _p(
                    (
                        f"ABS {readout_unit_label}. Coordinates are tool-relative; table motion "
                        "is opposite. Axis Set assigns the current position; Preset stores "
                        "a destination, not a datum."
                        if detail == "hobby"
                        else f"Use ABS mode in {readout_unit_label}. "
                        "Coordinates describe the tool relative to the work; the table moves the "
                        "opposite way. Axis Set assigns the current position's coordinate; Preset "
                        "stores a destination and does not establish this datum."
                    )
                    + (" " + direction_line + "." if direction_line and detail == "hobby" else "")
                )
            )
            if lathe:
                lesson.append(
                    _p(
                        "On a radius X display, X changes by the radial tool travel; on a "
                        "diameter display it changes by twice that travel. Use only the "
                        "established display mode and this job's calculated settings."
                    )
                )
            elif detail == "pedantic":
                lesson.append(
                    _p("For an opposed-edge datum, use the same finder for both actual edges:")
                    + _list(
                        [
                            "Pick up each actual edge and compensate its signed contact.",
                            "Use their actual midpoint (edge 1 + edge 2) / 2; set the stated "
                            "datum there, not at half an assumed stock width.",
                            "Before a check jog, raise Z only until the tip clears the work "
                            "and all clamps; return to the contact reading before lowering, "
                            "without another Axis Set.",
                        ]
                    )
                )
            else:
                lesson.append(
                    _p(
                        "Opposed edges: same finder, compensate both actual contacts; use "
                        "their midpoint (edge 1 + edge 2) / 2, never assumed stock width. "
                        "Clear vertically above the work and all clamps before a check jog; "
                        "return to the contact reading before lowering, without another Axis Set."
                    )
                )
            paper = next(
                (
                    record.get("paper_mm")
                    for record in axes.values()
                    if _known(record.get("paper_mm")) and record["paper_mm"] > 0
                ),
                None,
            )
            if paper is not None:
                lesson.append(
                    _p(
                        f"Paper {o(paper)} {units}: light drag; include actual thickness "
                        "with the contact-side sign in Axis Set."
                        if detail == "hobby"
                        else f"This setup's paper is {o(paper)} {units}: stop at light drag and "
                        "include that actual thickness with the contact-side sign in Axis Set."
                    )
                )
            if lesson_examples:
                lesson.append(_p(min(lesson_examples, key=lambda item: item[0])[1]))
            if not separate_instructions and not lathe:
                checked_axes = [axis.upper() for axis in ("x", "y") if axis in axes]
                if checked_axes:
                    lesson.append(
                        _inspection_method(
                            _Steps(
                                (
                                    " and ".join(checked_axes) + " check jog",
                                    (
                                        "raise Z only until the tool clears the work and clamps, "
                                        "without changing the axis under test.",
                                        "jog the table by the stated check-jog amount "
                                        "in the positive tool-relative direction; "
                                        "the display must read the listed value.",
                                        "jog back to the Axis Set value again, then lower; "
                                        "do not Axis Set again.",
                                    ),
                                    (),
                                )
                            )
                        )
                    )
        elif detail == "pedantic" and rows:
            reference = next(
                (
                    _mapping(authored.get(axis)).get("tool")
                    for axis in ("x", "y")
                    if _mapping(axes.get(axis)).get("finder")
                ),
                None,
            )
            pointer = (
                self.finder_pointer(setup, reference)
                if reference is not None
                else f'<a href="#{guide_id}">DRO first-use guide</a>'
            )
            pieces.append(
                '<p class="zero-guide">'
                + pointer
                + " — use the actual local contacts and settings below.</p>"
            )
        if rows and detail == "pedantic":
            pieces.append(
                _table(
                    ["axis", "touch / datum", "Axis Set", "check jog", "must read", "if reversed"],
                    rows,
                    css="zero",
                    widths=[7, 41, 13, 13, 13, 13],
                )
            )
        elif compact_rows:
            shared_mounted = self.mounted_datum_table(setup) if mounted_setup else None
            if shared_mounted is not None:
                pieces.append(shared_mounted)
            else:
                pickups = [
                    "/".join(axes) + " pickup: " + "; ".join(recipe)
                    for recipe, axes in pickup_recipes.items()
                ]
                if separate_instructions:
                    self._route_datum_axes[setup["id"]] = compact_axes
                    pieces.extend(_p(text + ".") for text in pickups)
                else:
                    pieces.append(
                        "<p><strong>Datums.</strong> "
                        + _fields(". ".join([*compact_rows, *pickups]))
                        + ".</p>"
                    )
        pieces.extend(measurements)
        machine, printed = setup.get("machine"), set()
        for axis in ("x", "y"):
            finder = _mapping(axes.get(axis)).get("finder")
            reference = _mapping(authored.get(axis)).get("tool")
            key = self.finder_key(reference, machine)
            if finder and key not in printed and self.finder_homes.get(key) == setup["id"]:
                printed.add(key)
                rendered = self.finder_box(reference, machine, finder)
                if first_use:
                    lesson.append(rendered)
                elif detail in ("pro", "pedantic") or finder.get("status") != "pass":
                    pieces.append(rendered)
        if first_use:
            lesson_html = "".join(lesson)
            if detail == "hobby":
                lesson_html = lesson_html.replace("</p><p>", " ")
            guide = (
                f'<div class="dro-guide" id="{guide_id}" '
                f'data-setup-id="{escape(setup.get("id") or "")}">'
                + "<h3>DRO FIRST USE"
                + (f" — {escape(_text(setup.get('id')))}" if self._front_reference_layout else "")
                + "</h3>"
                + lesson_html
                + "</div>"
            )
            if self._front_reference_layout and separate_instructions:
                self._front_dro_guide += guide
            else:
                pieces.insert(1, guide)
        correction = self.measured_top(setup)
        if correction:
            pieces.append(_p(correction))
        retouches = {}
        tops = {
            str(op["op"]): after["top_from"] for op, _, after in stock_states(self.bundle, setup)
        }
        surface = self.feature_name(top_feature) if top_feature else "the top"
        for record in numbers.get("retouch", []):
            if record.get("tool_setting_state") == "unsupported_spindle_saw":
                continue
            paper = record.get("paper_mm")
            if _carried(record):
                # A carried top: its physical height, and the setting as the report
                # computed it on this grid.
                top = (
                    self.physical(record.get("top_z"))
                    if readout_units(self.bundle) == self.units
                    else o(record.get("top_z"))
                )
                axis_set = o(record.get("axis_set"))
            else:
                # The top as the op that last faced it left it, else as the DRO shows it.
                top = self.surface_z(
                    setup, record.get("top_z"), tops.get(str(record.get("op"))), face="top"
                )
                if not _known(top) and self.fresh_top_setting(setup, record):
                    top, axis_set = record["top_z"], record.get("axis_set", "unknown")
                else:
                    axis_set = (
                        top + paper
                        if _known(top) and _known(paper) and _known(record.get("axis_set"))
                        else "unknown"
                    )
                if not _known(axis_set):
                    unresolved(
                        "Z RETOUCH SETTING NOT ESTABLISHED",
                        f"{setup['id']}:{record.get('op')}→{record.get('next_op')}",
                    )
                top, axis_set = o(top), o(axis_set)
            key = (top, o(paper), axis_set, _touch_outside(record))
            retouches.setdefault(key, []).append(record)
        for (top, paper, axis_set, outside), records in retouches.items():
            touch = f"touch {surface} (Z {top}) with {paper} paper → Axis Set Z {axis_set}"
            if detail == "pro":
                touch = f"retouch {surface} Z{top}"
            touch += (f"; {outside}" if outside else "") + "."
            changes = []
            for record in records:
                after, served = _text(record.get("op")), record.get("next_op")
                incoming = record.get("next_tool")
                name = (
                    self.route_tool_label(incoming)
                    if detail != "pedantic"
                    else self.touched_tool(incoming, tools, "tools")
                )
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
                if touch.get("tool_setting_state") == "unsupported_spindle_saw":
                    continue
                if (kind, index) in settings_at:
                    pieces.append(_p(self.tool_setting(settings_at[(kind, index)], tools)))
                slot = "spindle" if kind == "tool_touches" else "tools"
                rendered_touch = self.tool_touch(setup, touch, tools, slot)
                if (
                    detail != "pedantic"
                    and not lathe
                    and touch.get("method") in ("paper", "touch", "mounted_saw_side")
                    and touch.get("z_face")
                    and not touch.get("x_face")
                    and not touch.get("z_measure")
                    and "reference_corner" not in touch
                ):
                    edge, setting = touch.get("edge_mm"), touch.get("z_axis_set")
                    mounted = touch.get("method") == "mounted_saw_side"
                    if not mounted and not _carried(touch) and _known(edge) and _known(setting):
                        done = self.ops_done(setup, before=touch.get("before_ops"))
                        actual = self.datum_z(setup, touch["z_face"], edge, done)
                        setting = setting + actual - edge if _known(actual) else "unknown"
                        edge = actual
                    before = touch.get("before_ops")
                    before = before if isinstance(before, list) else [before]
                    name = self.route_tool_label(touch.get("tool"))
                    line = (
                        f"Before {_ops_label(before)}, install {name}; fresh "
                        + ("stopped body-side touch" if mounted else "cutter touch")
                        + f" on {self.bench(touch['z_face'])} Z{o(edge)}"
                    )
                    if detail != "pro" or mounted:
                        line += (
                            f", paper {o(touch.get('paper_mm'))}; Axis Set Z{self.reading(setting)}"
                        )
                    at = touch.get("at_mm")
                    if mounted and isinstance(at, list) and len(at) == 2:
                        line += f"; calibration X{o(at[0])}/Y{o(at[1])}"
                    outside = _touch_outside(touch)
                    if outside:
                        line += "; " + outside
                    pieces.append(_p(line + "."))
                else:
                    pieces.append(_p(rendered_touch))
                explanation = mounted_lesson(touch)
                if explanation:
                    pieces.append(_p(explanation + "."))
                for axis in ("x", "z"):
                    field = f"{axis}_axis_set"
                    if field in touch and self.reading(touch[field]) == "?":
                        name = self.touched_tool(touch.get("tool"), tools, slot)
                        before = touch.get("before_ops", touch.get("before_op"))
                        before = _ops_label(before if isinstance(before, list) else [before])
                        unresolved(
                            f"{name} {axis.upper()} tool-touch setting is unknown.",
                            f"{setup['id']}:{kind}:{index}:{axis}:{touch.get('tool')}",
                            notice_group=f"{_ZERO_SETTING}|{axis.upper()} tool-touch setting|"
                            + " before ".join(filter(None, (name, before))),
                        )
        for gap in numbers.get("missing_touches", []):
            if gap.get("tool_setting_state") == "unsupported_spindle_saw":
                continue
            name = self.touched_tool(gap.get("tool"), tools, "tools")
            missing = " and ".join(_text(axis).upper() for axis in gap.get("axes", []))
            unresolved(
                f"Before op {_text(gap.get('before_op'))}, {name} has no {missing} touch.",
                f"{setup['id']}:{gap.get('before_op')}:{gap.get('tool')}",
            )
            if detail == "pedantic":
                pieces.append(
                    _p(
                        f"STOP: before op {_text(gap.get('before_op'))}, {name} has no {missing} "
                        "touch — the DRO reads another tool. Plan a tool touch."
                    )
                )
        for record in axes.values():
            if record.get("note"):
                pieces.append(_p(self.bench(record["note"])))
        if detail != "pedantic":
            # The compact composer's decision blocks own these adverse facts.
            adverse_html = {_p(text) for _, text in compact_debts}
            pieces = [piece for piece in pieces if piece not in adverse_html]
        if detail != "pedantic" and separate_instructions and not compact_debts:
            pieces = [
                '<span class="datum-clause">' + piece[3:-4] + "</span> "
                if piece.startswith("<p>")
                and piece.endswith("</p>")
                and piece.count("<p>") == piece.count("</p>") == 1
                and 'class="writing-blank"' not in piece
                else piece
                for piece in pieces
            ]
        return "".join(pieces)

    def pickup_contact(self, axis, computed, *, axis_set=None):
        """Print a matching native top or transverse pickup path, never infer one."""
        evidence = _mapping(computed.get("pickup_proof"))
        key = evidence.get("key") or axis
        scope = f"{evidence['setup_id']}:{key}" if evidence.get("setup_id") else key
        if not evidence:
            if axis == "z" and "at_mm" in computed:
                return _Box(
                    "STOP: Z pickup path is unproved at the requested tool-axis position",
                    source="zero_check",
                    status="unknown",
                    scope=scope,
                )
            return None
        if evidence.get("status") != "pass":
            reasons = evidence.get("reasons") or ["physical pickup path is unproved"]
            return _Box(
                f"STOP: {axis.upper()} pickup — "
                + "; ".join(self.bench(reason) for reason in reasons),
                source="zero_check",
                status=evidence.get("status", "unknown"),
                scope=scope,
            )
        path = _mapping(evidence.get("path"))
        point = path.get("contact_mm")
        height = path.get("retract_height_mm")
        if axis == "z":
            start, jog = path.get("start_mm"), path.get("jog_mm")
            if not (
                isinstance(point, list)
                and len(point) == 3
                and isinstance(start, list)
                and len(start) == 3
                and all(_known(value) and math.isfinite(value) for value in [*point, *start])
                and _known(height)
                and math.isfinite(height)
                and _known(jog)
                and math.isfinite(jog)
            ):
                return _Box(
                    "STOP: Z pickup path is incomplete",
                    source="zero_check",
                    status="unknown",
                    scope=scope,
                )
            direction = "−" if jog < 0 else "+"
            setting = f"Axis Set Z {axis_set}; " if axis_set is not None else "after Axis Set, "
            return (
                f"at physical setup X {_declared(point[0])}, Y {_declared(point[1])} mm, "
                f"start the tool tip at Z {_declared(start[2])} mm; lower vertically "
                f"to the paper contact at Z {_declared(point[2])} mm; {setting}"
                f"check {direction}Z {_declared(abs(jog))} mm, then retract vertically "
                f"to Z {_declared(height)} mm"
            )
        top = path.get("stock_top_mm")
        approach = _mapping(evidence.get("request")).get("approach_mm")
        if not (
            isinstance(point, list)
            and len(point) == 3
            and all(_known(value) for value in point)
            and _known(height)
            and _known(top)
            and _known(approach)
        ):
            return _Box(
                f"STOP: {axis.upper()} pickup path is incomplete",
                source="zero_check",
                status="unknown",
                scope=scope,
            )
        clearance = height - top
        depth = top - point[2]
        lines = [
            f"start with the tip {_number(clearance)} mm above the current stock top, "
            f"{_number(approach)} mm back from contact"
        ]
        window = _mapping(evidence.get("window"))
        transverse = window.get("transverse_axis")
        intervals = window.get("intervals_mm")
        if transverse in ("x", "y") and isinstance(intervals, list):
            centre = point["xy".index(transverse)]
            span = next(
                (
                    pair
                    for pair in intervals
                    if isinstance(pair, list)
                    and len(pair) == 2
                    and all(_known(value) for value in pair)
                    and pair[0] <= centre <= pair[1]
                ),
                None,
            )
            if span:
                lines.append(
                    f"physical {transverse.upper()} contact span {_number(span[1] - span[0])} mm, "
                    f"finder centre {_number(centre - span[0])} mm "
                    f"from its −{transverse.upper()} end"
                )
        lines.append(
            f"lower the tip to {_number(abs(depth))} mm "
            f"{'below' if depth >= 0 else 'above'} the current top, then approach the face"
        )
        lines.append(
            f"after Axis Set, raise the tip back to {_number(clearance)} mm "
            "above the current top before the jog"
        )
        return "; ".join(lines)

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
        """Link to this machine family's DRO lesson and this finder/machine's actual data."""
        if getattr(self, "detail", "pedantic") == "pro":
            return ""
        key = self.finder_key(reference, setup.get("machine"))
        home = self.finder_homes.get(key, setup["id"])
        return (
            f'<a href="#{self.dro_guide_id(setup)}">DRO first-use guide</a>; '
            "finder settings in Setup " + escape(_text(home))
        )

    def finder_box(self, reference, machine, finder):
        """Project the authoritative finder facts; teach each contact type only once."""
        detail = getattr(self, "detail", "pedantic")
        units = readout_units(self.bundle)
        scale = {"mm": 1.0, "in": 25.4}.get(self.units)

        def o(value):
            return self.readout(value / scale) if _known(value) and scale else "?"

        kind = finder.get("finder_type")
        tip, radius = finder.get("tip_dia_mm"), finder.get("radius_mm")
        if detail == "pro" and finder.get("status") == "pass":
            return _p(
                f"Finder: {self.route_tool_name(reference)}; contact Ø{o(tip)} {units}.",
                "finder-identity",
            )
        lines = [_p(f"Tip Ø {o(tip)} {units}; radius {o(radius)} {units}.")]
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
            if not isinstance(value, list):
                return "?"
            return (
                " or ".join(
                    _number(pair[0]) if pair[0] == pair[1] else "–".join(_number(v) for v in pair)
                    for pair in value
                    if isinstance(pair, list) and len(pair) == 2
                )
                or "?"
            )

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
            if detail != "pedantic" and all(
                isinstance(pair, list)
                and len(pair) == 2
                and all(map(_known, pair))
                and pair[0] <= pair[1]
                for pair in rpm
            ):
                merged = []
                for low, high in sorted(rpm):
                    if merged and low <= merged[-1][1]:
                        merged[-1][1] = max(merged[-1][1], high)
                    else:
                        merged.append([low, high])
                rpm = merged
            speed = f"Speed: {bands(rpm)} rpm"
            if detail == "pedantic":
                speed += (
                    f" (finder {bands([band])}; mill {spindle}; use only the "
                    "intersecting spindle ranges)"
                )
            lines.append(_p(speed + "."))
        elif "rpm range" not in missing:
            lines.append(
                _p("STOP: the finder's or the mill's rpm range is not known — no speed.", "stop")
            )
        taught = getattr(self, "_finder_lesson_types", set())
        teach = detail != "pro" and kind not in taught
        if teach:
            self._finder_lesson_types = taught | {kind}
        if teach and kind == "mechanical":
            lines.append(
                _p(
                    "Offset tip while stopped; run at stated speed. Approach in small "
                    "handwheel steps until true then sideways kick; back off/repeat first kick."
                    if detail == "hobby"
                    else "Mechanical contact: offset the tip while stopped; run at the stated "
                    "speed. Approach in small handwheel steps until it runs true and kicks "
                    "sideways; back off and repeat the first kick to locate the edge."
                )
            )
        elif teach and kind == "electronic":
            lines.append(
                _p(
                    "Electronic contact: spindle stopped; approach in small handwheel "
                    "steps to the first light, back off and repeat."
                )
            )
        if teach and _known(radius):
            lines.append(
                _p(
                    "Finder-axis offset = half tip diameter. From − side "
                    f"(moving + onto edge): Axis Set edge − {o(radius)}; "
                    f"from + side: edge + {o(radius)}. "
                    "Use the local datum's signed Axis Set."
                    if detail == "hobby"
                    else "Offset: at the pick-up the spindle axis is half the tip Ø "
                    f"({o(tip)}) off the edge, r = {o(radius)}. Coming from the − side "
                    f"(moving + onto the edge): Axis Set edge − {o(radius)}. "
                    f"Coming from the + side: Axis Set edge + {o(radius)}. "
                    "Each DRO ZERO row prints its signed Axis Set."
                )
            )
        cite = finder.get("cite")
        cites = [cite] if isinstance(cite, str) and cite != "unknown" else cite
        if detail == "pedantic" and isinstance(cites, list) and cites:
            lines.append(_p("Finder data: " + "; ".join(str(c) for c in cites) + "."))
        title = f"EDGE FINDER — {self.reference(reference, 'spindle')}"
        finder_item = identity(self.bundle, reference, "spindle")
        if sum(key[0] == finder_item for key in self.finder_homes) > 1:
            title += f" on {self.reference(machine, 'machines')}"
        body = "".join(lines)
        if detail == "hobby":
            body = body.replace("</p><p>", " ")
        return f'<div class="keep"><h3>{escape(title)}</h3>{body}</div>'

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
            for check in item["checks"]:
                if check["status"] != "pass":
                    self.record_decision(
                        setup,
                        source="purchased_tooling",
                        status=check["status"],
                        scope=setup["id"],
                        text=f"{name}: {check['check']} — STOP: {check['reason']}",
                    )
            for stop in item.get("stops") or []:
                self.record_decision(
                    setup,
                    source="purchased_tooling",
                    status="unknown",
                    scope=setup["id"],
                    text=f"{name}: STOP: {stop} — do not use it until the shop list states it.",
                )
            home = self.receipt_homes.get(identity, setup["id"])
            if home != setup["id"]:
                html.append(
                    _p(
                        f"{name}: bought finished; receipt checks before first use: "
                        "PURCHASED TOOLING / "
                        f"RECEIPT CHECK table, Setup {_text(home)}."
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

        def unresolved(text):
            scope = f"{setup['id']}:z"
            self.record_decision(
                setup, source="zero_check", status="unknown", scope=scope, text=text
            )
            return _Box(text, source="zero_check", status="unknown", scope=scope)

        o = self.readout
        offset, top = touch.get("offset_mm"), _mapping(setup.get("stock_state")).get("top_z")
        if not (_known(offset) and _known(top)):
            return unresolved(
                "STOP: the measured top's Z is not set — Z offset or stock top unknown."
            )
        shown_offset = (
            _number(abs(offset)) if readout_units(self.bundle) == self.units else o(abs(offset))
        )
        measurement = self.reading("M")
        raw = (
            measurement
            if not offset
            else f"{measurement} {'−' if offset < 0 else '+'} {shown_offset}"
        )
        docs = [
            op["doc_mm"]
            for op in setup.get("ops", [])
            if _known(op.get("doc_mm")) and op["doc_mm"] > 0
        ]
        scale = {"mm": 1.0, "in": 25.4}.get(self.units)  # doc_mm is mm; levels are plan units
        least = self.mm_on_grid(setup, min(docs), up=False) if docs and scale else None
        cap_known = False
        if not docs:
            cap = "? per pass: no op sets doc_mm"
        elif scale is None:
            cap = "? per pass: plan units unknown"
        elif least <= 0:
            cap = f"? per pass: the least doc_mm {_number(min(docs))} is under one DRO step"
        else:
            cap = f"no more than {o(least)} per pass"
            cap_known = True
        text = (
            f"M puts the raw top at Z = {raw}; the ops' levels start from Z {o(top)}. If "
            f"{raw} is above Z {o(top)}, first face the top down to Z {o(top)}, {cap}."
        )
        return text if cap_known else unresolved(text)

    def reading(self, value, expression=None):
        """DRO readings; a measured-diameter expression reads as plain arithmetic."""
        if _known(value):
            return self.readout(value)
        text = value if isinstance(value, str) and value != "unknown" else expression
        if not isinstance(text, str) or text == "unknown":
            return "?"

        def measured_subject(symbol):
            subject = {"D": "measured Ø", "D/2": "measured Ø/2", "M": "M"}[symbol]
            units = readout_units(self.bundle)
            if units == self.units:
                return subject
            if self.units not in ("mm", "in") or units not in ("mm", "in"):
                return "?"
            subject = (
                f"measured Ø ({self.units})/2" if symbol == "D/2" else f"{subject} ({self.units})"
            )
            return f"({subject} {'/25.4' if self.units == 'mm' else '×25.4'})"

        match = re.fullmatch(r"(?:measured\s+)?(D/2|D|M)\s*([+-])\s*(\d+(?:\.\d+)?)", text.strip())
        if match:
            sign = "+" if match[2] == "+" else "−"
            subject = measured_subject(match[1])
            return f"{subject} {sign} {self.readout(float(match[3]))}"
        symbolic = re.fullmatch(r"(?:measured\s+)?(D/2|D|M)", text.strip())
        if symbolic and readout_units(self.bundle) != self.units:
            return measured_subject(symbolic[1])
        return "measured Ø" if text.strip() == "measured D" else self.bench(text)

    def touched_tool(self, reference, tools, slot):
        """A touched-off tool's name: the setup's own name for it (``tools``), else the
        shop name of the item ``slot`` selects (a zero's or tool touch's tool is a spindle
        slot, an op's a tool; never a same-key item of another category)."""
        if self.detail != "pedantic":
            label = self.route_tool_labels.get(identity(self.bundle, reference, slot))
            if label:
                return label
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

    def mounted_saw_contact(self, record):
        setting = _mapping(record.get("mounted_saw_setting"))
        side = {"minus_z": "lower", "plus_z": "upper"}.get(setting.get("blade_side"), "selected")
        return (
            f"touch the {side} flat blade-body side; "
            f"body {_number(setting.get('body_thickness_mm'))} mm, "
            f"cutting-band offset {_number(setting.get('kerf_offset_mm'))} mm; "
            "Z reads the cutting-band midplane"
        )

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
                    ("paper " + self.readout(paper) if paper else "no paper")
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
            if (_carried(touch) or touch.get("method") == "mounted_saw_side") and _known(edge):
                # A carried face: the report's setting prints as computed, the face at
                # its physical height.
                surface = edge
            elif _known(edge) and _known(axis_set):
                # The touched face as the DRO shows it when this tool comes in.
                done = self.ops_done(setup, before=touch.get("before_ops"))
                surface = self.datum_z(setup, z_face, edge, done)
                axis_set = axis_set + surface - edge if _known(surface) else "unknown"
            method = re.sub(r";?\s*Axis Set Z\.?$", "", str(touch.get("method", "touch")))
            # A blade's Z touch sets one corner (zero_check ``reference_corner``): named.
            corner = _CORNERS.get(touch.get("reference_corner"))
            blade = "reference_corner" in touch
            words = (
                self.mounted_saw_contact(touch)
                if method == "mounted_saw_side"
                else _METHODS.get(method, self.bench(method))
            )
            text = f"Z — on the {self.bench(z_face)}"
            if corner:
                text = f"Z — {corner} corner on the {self.bench(z_face)}"
                words = words.replace("this tool's Z-cutting edge", f"this blade's {corner} corner")
            if "repeats" in touch and _known(surface):
                shown = (
                    self.physical(surface)
                    if _carried(touch) and readout_units(self.bundle) == self.units
                    else self.readout(surface)
                )
                text += f" (Z {shown})"
            text += f": {words}"
            if touch.get("z_measure"):
                gauge = touch.get("z_gauge")
                text += f", M = {self.bench(touch['z_measure'])}" + (
                    f" ({self.short_reference(gauge, 'gauges')})" if gauge else ""
                )
            if _known(paper):
                text += f", paper {self.readout(paper)}" if paper else ", no paper"
            if "at_mm" in touch:
                at = touch.get("at_mm")
                xy = at if isinstance(at, list) and len(at) == 2 else ["unknown", "unknown"]
                text += (
                    f"; tool axis at setup X {self.physical(xy[0])}, "
                    f"Y {self.physical(xy[1])} {self.units}"
                )
                text += (
                    "; requested retract clearance "
                    f"{self.physical(touch.get('retract_clearance_mm'))} {self.units}"
                )
            pickup = self.pickup_contact("z", touch, axis_set=self.reading(axis_set))
            if pickup and not isinstance(pickup, _Box):
                text += f"; {pickup}"
            else:
                text += f"; Axis Set Z {self.reading(axis_set)}"
            if corner:
                text += f": Z now reads the {corner} corner"
            elif blade:
                text += ". STOP: which blade corner this touch sets is not known — plan it"
            outside = _touch_outside(touch)
            if outside:
                text += f"; {outside}"
            if isinstance(pickup, _Box):
                text += f"; {pickup}"
                self.record_decision(
                    setup,
                    source=pickup.source,
                    status=pickup.status,
                    kind=pickup.kind,
                    scope=pickup.scope,
                    text=str(pickup),
                )
            parts.append(text + ".")
        return " ".join(parts)

    # -------------------------------------------------------------- features
    def feature_map(self, setup):
        if saw_setup(self.bundle, setup):
            return ""
        numbers = self.records.get(("coordinates", setup["id"]), {})
        display = numbers.get("x_display")
        lathe = "x_display" in numbers or self.lathe(setup)
        # The size each surface turns to, as the DRO's X display reads it; unread, the
        # surface still lists with its drawing limits and Zs, its X withheld.
        turned = {"diameter": ("turn to Ø", "Ø"), "radius": ("turn to X (radius)", "")}
        heading, prefix = turned.get(display, ("turn to X", None))
        if lathe and readout_kind(self.bundle) == "handwheel" and display is None:
            radius = _mapping(self.plan.get("dro")).get("radius_mode")
            display = "radius" if radius is True else "diameter" if radius is False else None
            heading, prefix = turned.get(display, ("turn to X", None))
        surface_ops = {}
        surface_actions = PROFILE_OPS | {"bore"}
        for op in setup.get("ops", []):
            feature = op.get("feature")
            if isinstance(feature, str) and op.get("do") in surface_actions:
                surface_ops.setdefault(feature, []).append(op)
        staged = {
            feature: ops
            for feature, ops in surface_ops.items()
            if any("to_dia" in op for op in ops)
        }
        o = self.readout
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
                if feature not in cut or not _known(size):
                    continue
                # Its ends as its ops print them: cut before its first op (:meth:`op_z`).
                first = [
                    op.get("op") for op in setup.get("ops", []) if op.get("feature") == feature
                ]
                done = self.ops_done(setup, before=first)
                entry = grouped.setdefault(
                    feature,
                    {
                        "dia": x,
                        "nominal_dia": record.get("dia_nominal"),
                        "located": True,
                        "z": [],
                        "done": done,
                    },
                )
                if _known(coordinates[2]):
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
        if lathe:
            # A known diameter remains useful even when every authored cut end is
            # unknown. A feature point or finished/native span is not a cut window.
            for op in setup.get("ops", []):
                feature = op.get("feature")
                if not isinstance(feature, str) or feature not in cut or feature in grouped:
                    continue
                diameter = _mapping(self.features.get(feature)).get("dia_nominal")
                if not _known(diameter) and feature not in staged:
                    continue
                x = diameter / 2 if _known(diameter) and display == "radius" else diameter
                grouped[feature] = {
                    "dia": x,
                    "nominal_dia": diameter,
                    "located": False,
                    "z": [],
                    "done": self.ops_done(setup, before=op.get("op")),
                }
            targets = []
            for feature, entry in grouped.items():
                if feature not in staged:
                    targets.append((feature, entry))
                    continue
                # Coordinate rows reference finished-feature geometry, not an authored
                # stage. Once staged, an omitted target cannot imply a later finish cut.
                reference = entry.get("nominal_dia")
                stages = []
                for op in staged[feature]:
                    diameter = op.get("to_dia", "unknown")
                    if stages and diameter == stages[-1]["nominal_dia"]:
                        stages[-1]["ops"].append(op)
                        continue
                    located = entry["located"] and _known(entry["dia"]) and diameter == reference
                    nominal_only = readout_kind(self.bundle) != "handwheel" and not located
                    x = diameter / 2 if _known(diameter) and display == "radius" else diameter
                    stages.append(
                        {
                            "dia": entry["dia"] if located else x,
                            "nominal_dia": diameter,
                            "nominal_only": nominal_only,
                            "ops": [op],
                            "z": [],
                            "done": self.ops_done(setup, before=op.get("op")),
                        }
                    )
                targets.extend((feature, stage) for stage in stages)
        if not grouped:
            return ""
        if lathe:
            # Each surface's Z ends as the DRO shows them, as the op rows print them; the
            # drawing's own limits (a drawing feature only) apart from the size turned to.
            drawing = _mapping(self.bundle.features.get("features"))
            rows = []
            unknown_stage = nominal_stage = False
            for feature, entry in targets:
                band = _mapping(drawing.get(feature)).get("dia")
                drawn = "—"
                if isinstance(band, list) and len(band) == 2 and all(map(_known, band)):
                    drawn = "Ø" + self.band(band, feature, "dia")
                cutting = (
                    entry["ops"]
                    if "ops" in entry
                    else [
                        op
                        for op in setup.get("ops", [])
                        if op.get("feature") == feature and op.get("do") not in MANUAL
                    ]
                )
                complete = cutting and all(
                    _known(op.get(key)) for op in cutting for key in ("z_from", "z_to")
                )
                if complete and entry["z"]:
                    ends = max(entry["z"]), min(entry["z"])
                else:
                    # Preserve each independently authored endpoint. One feature.at
                    # (or a finished-solid span) supplies neither missing cut endpoint.
                    starts = [op.get("z_from") for op in cutting]
                    stops = [op.get("z_to", op.get("to_z")) for op in cutting]
                    ends = (
                        max(starts) if starts and all(map(_known, starts)) else "unknown",
                        min(stops) if stops and all(map(_known, stops)) else "unknown",
                    )
                label = self.feature_name(feature)
                if "ops" in entry:
                    owners = ", ".join(str(op["op"]) for op in cutting)
                    label += f" — {'op' if len(cutting) == 1 else 'ops'} {owners}"
                if "ops" in entry and not _known(entry["nominal_dia"]):
                    target = "?"
                    unknown_stage = True
                elif entry.get("nominal_only"):
                    target = f"Ø{o(entry['nominal_dia'])} nominal; X ?"
                    nominal_stage = True
                else:
                    target = (
                        "Ø" + o(entry["nominal_dia"])
                        if prefix is None and readout_kind(self.bundle) == "handwheel"
                        else "?"
                        if prefix is None
                        else prefix + o(entry["dia"])
                    )
                rows.append(
                    (
                        label,
                        drawn,
                        target,
                        *(
                            o(self.surface_z(setup, z, face=feature, done=entry["done"], path=True))
                            for z in ends
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
            if staged:
                note += " Named operations own each diameter stage and its cut limits."
            units = readout_units(self.bundle)
            if readout_kind(self.bundle) == "handwheel" or units != self.units:
                headings = [
                    "feature",
                    f"drawing Ø limits ({self.units})",
                    f"nominal {'radius' if display == 'radius' else 'Ø'} target ({_text(units)})",
                    f"nominal cut from Z ({_text(units)})",
                    f"nominal cut to Z ({_text(units)})",
                ]
                note += (
                    " Nominal model targets are not physical dial settings; establish the "
                    "actual pickup, scale meaning and backlash procedure before cutting."
                )
            if any("?" in cell for row in rows for cell in row[-2:]):
                note += " Unknown cut extents remain unknown; a feature point is not a cut window."
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
            if readout_units(self.bundle) != self.units:
                headings = [
                    "feature",
                    "reference point",
                    *(f"{axis} ({_text(readout_units(self.bundle))})" for axis in "XYZ"),
                ]
            widths = [26, 38, 12, 12, 12]
            note = "The op table gives the tool targets."
            note += "".join(f" {text}" for text in dict.fromkeys(filter(None, aims)))
        table = _table(headings, rows, css="feature-map", widths=widths, context=note)
        if lathe and unknown_stage:
            table += _p(
                "STOP: operation diameter target not set; the finished-feature diameter "
                "is not a substitute.",
                "stop",
            )
        if lathe and nominal_stage:
            table += _p(
                "STOP: nominal Ø is a size only, not an established DRO X setting for this "
                "stage. Establish the pickup and checked stage target before cutting.",
                "stop",
            )
        if lathe and prefix is None:
            table += _p(
                (
                    "STOP: X scale reads radius or diameter — not established"
                    if readout_kind(self.bundle) == "handwheel"
                    else _X_DISPLAY_STOP
                )
                + ".",
                "stop",
            )
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
        self.register_measurements(self.collect_measurements(setup), setup)
        rows, by_tool = {}, {}
        for op in setup.get("ops", []):
            reference = op.get("tool")
            if op.get("do") in MANUAL - HAND_THREAD or reference in (None, "unknown"):
                continue
            holder = op.get("holder")
            pair = self.tool_pair(reference, holder)
            if pair not in rows:
                detail = self.tool_detail(reference, holder)
                nominal = ", ".join(d for d in detail if not isinstance(d, _Unverified))
                dimensions = [d for d in detail if isinstance(d, _Unverified)]
                by_tool.setdefault(pair[0], f"{numbers[pair]} {self.tool_name(reference)}")
                rows[pair] = [
                    numbers[pair],
                    self.tool_name(reference),
                    ([nominal] if nominal else []) + dimensions if dimensions else nominal or "—",
                    self.short_reference(holder, "holders")
                    if holder not in (None, "unknown", "not_applicable")
                    else "—",
                    [],
                ]
            rows[pair][4].append(str(op["op"]))
        if not hasattr(self, "_tool_specs_by_setup"):
            self._tool_specs_by_setup = {}
        self._tool_specs_by_setup[setup["id"]] = {
            pair: tuple(row[1:4]) for pair, row in rows.items()
        }
        rows = sorted(rows.values(), key=lambda row: int(row[0][1:]))
        html = ""
        if rows:
            html = "<h2>TOOLS FOR THIS SETUP — pull before starting</h2>" + _table(
                ["T", "tool", "insert / size / material", "holder / station", "ops"],
                [(t, n, d, h, ", ".join(ops)) for t, n, d, h, ops in rows],
                css="tools",
                widths=[9, 21, 33, 25, 12],
            )
        return numbers, by_tool, html

    # ------------------------------------------------------------- operations
    def tip(self, setup, op):
        o = self.readout
        endpoint = self.endpoint(setup, op)
        if endpoint and endpoint.get("depth_scale") == "manual":
            depth = endpoint.get("depth_mm")
            if all(_known(endpoint.get(key)) for key in ("entry_z", "tip_z", "depth_mm")):
                return [
                    f"hand depth {o(depth)} below top"
                    if self.detail != "pedantic"
                    else f"hand depth {o(depth)} from touching the top"
                ]
            return [
                "hand depth not set",
                _Box(
                    "STOP: hand-fed penetration or touched entry is not established",
                    source="blind_depth",
                    status="unknown",
                    scope=f"{setup['id']}:{op.get('op')}",
                ),
            ]
        if endpoint and endpoint.get("depth_scale") == "quill":
            # A tailstock centre drill is fed by the quill: its depth is read on the quill
            # scale from touching the work, never as a carriage DRO Z.
            depth = endpoint.get("depth_mm")
            if not _known(depth):
                debts = self.endpoint_measurements(setup, op)
                number = tool_numbers(self.bundle, setup).get(
                    self.tool_pair(op.get("tool"), op.get("holder"))
                )
                detail = "; ".join(self.measurement_stop(op, number, debt) for debt in debts)
                return [
                    "quill depth not set",
                    _Box("STOP: centre depth unknown" + (f" — {detail}" if detail else "")),
                ]
            return [f"quill {o(depth)} past touching the end"]
        if endpoint:
            # Consume checked operative endpoints, including the actual carried Axis Set;
            # never re-round their raw native entry or exit face in the renderer.
            entry = endpoint.get("dro_entry_z")
            parts = [
                f"tip Z{o(endpoint.get('dro_tip_z'))}"
                if self.detail != "pedantic" and _known(entry) and entry == 0
                else f"Z {o(entry)} → {o(endpoint.get('dro_tip_z'))}"
            ]
            if endpoint.get("exit_face", "not_applicable") != "not_applicable":
                parts.append(f"breaks through at {o(endpoint.get('dro_exit_face'))}")
                left = endpoint.get("dro_exit_mm")
                if _known(left) and left < -SAME_Z:
                    # Rounded up, the DRO tip leaves the full diameter short of the exit.
                    parts.append(_Box("STOP: DRO tip stops short of break-through; raise exit"))
            elif _known(endpoint.get("depth_mm")):
                depth = endpoint.get("dro_depth_mm")
                if self.detail == "pedantic" or not _known(entry) or entry != 0:
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
                geometry = (
                    "establish hand-tap penetration, allowing for tap lead and bottom clearance"
                    if op.get("do") == "hand_tap"
                    else "reamer chamfer / lead length unknown"
                    if op.get("do") == "ream" and not _known(endpoint.get("lead_mm"))
                    else "drill point length unknown"
                    if op.get("do") != "ream"
                    else "reamer depth / entry not set"
                )
                debts = self.endpoint_measurements(setup, op)
                number = tool_numbers(self.bundle, setup).get(
                    self.tool_pair(op.get("tool"), op.get("holder"))
                )
                detail = "; ".join(self.measurement_stop(op, number, debt) for debt in debts)
                parts.append(_Box(f"STOP: {geometry}" + (f" — {detail}" if detail else "")))
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
            return [_Box("STOP: X endpoint diameter not set")]
        display = _mapping(self.records.get(("coordinates", setup["id"]))).get("x_display")
        half = {"radius": 0.5, "diameter": 1.0}.get(display)
        if half is None:
            return [
                _Box(
                    "STOP: X scale reads radius or diameter — not established"
                    if readout_kind(self.bundle) == "handwheel"
                    else _X_DISPLAY_STOP
                )
            ]
        scale = {"mm": 1.0, "in": 25.4}.get(self.units)
        depth = _mapping(self.records.get(("reach", f"{setup['id']}:{op.get('op')}"))).get(
            "reach_depth_mm"
        )
        o = self.readout
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
        o = self.readout
        return [
            f"X{o(x)}/Y{o(y)}{self.frame_tag(setup)}"
            if self.detail != "pedantic"
            else f"tool axis X {o(x)}, Y {o(y)}{self.frame_tag(setup)}"
        ]

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
        o = self.readout
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
            if readout_units(self.bundle) != self.units:
                low, high = (readout_value(self.bundle, value) for value in (low, high))
            return f"allowed {_declared(low)} to {_declared(high)}"
        corner = _CORNERS.get(blade.get("reading_corner"))
        band = blade.get("corner_dro_band")
        if corner is None or not isinstance(band, list):
            return "allowed ? (blade corner not set)"
        o = self.readout
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
        if isinstance(band, list) and scale and op_entry(op, "checks", feature, "dia") is None:
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

    def fresh_top_setting(self, setup, retouch=None):
        """A source-bound evaluated fresh top touch, not a guessed lineage height."""
        touch = _mapping(_mapping(setup.get("zero")).get("z"))
        axis = _mapping(
            _mapping(self.records.get(("zero_check", setup["id"]), {}).get("axes")).get("z")
        )
        if (
            touch.get("face") != "top"
            or touch.get("after_op") not in (None, "")
            or axis.get("after_op") not in (None, "")
            or self.lathe(setup)
            or touch.get("method") not in ("paper", "touch")
            or axis.get("face") != "top"
            or axis.get("method") != touch.get("method")
            or axis.get("axis_set_status") != "computed"
        ):
            return False
        for key, slot in (("tool", "spindle"), ("holder", "holders")):
            reference = touch.get(key)
            if reference in (None, "unknown") or axis.get(key) in (None, "unknown"):
                return False
            if identity(self.bundle, reference, slot) != identity(self.bundle, axis[key], slot):
                return False
        ops = setup.get("ops", [])
        cutting = [op for op in ops if op.get("do") not in MANUAL | SAW_OPS]
        if not cutting or any(
            identity(self.bundle, cutting[0].get(key), slot)
            != identity(self.bundle, touch.get(key), slot)
            for key, slot in (("tool", "spindle"), ("holder", "holders"))
        ):
            return False
        top = _mapping(setup.get("stock_state")).get("top_z")
        edge, paper = axis.get("edge_mm"), axis.get("paper_mm")
        if not (
            _known(top)
            and _known(edge)
            and _known(paper)
            and _known(axis.get("axis_set"))
            and math.isclose(top, edge, rel_tol=0, abs_tol=SAME_Z)
            and math.isclose(axis["axis_set"], edge + paper, rel_tol=0, abs_tol=SAME_Z)
        ):
            return False
        if retouch is None:
            return True
        before = next((op for op in ops if op.get("op") == retouch.get("op")), None)
        following = next((op for op in ops if op.get("op") == retouch.get("next_op")), None)
        if before is None or following is None or ops.index(before) >= ops.index(following):
            return False
        listed = touch.get("retouch_after")
        if not isinstance(listed, list) or before.get("op") not in listed:
            return False
        served = next((op for op in cutting if ops.index(op) > ops.index(before)), None)
        if following is not served:
            return False
        if before.get("do") in FACING or following.get("tool") in (None, "unknown"):
            return False
        return (
            identity(self.bundle, following["tool"], "spindle")
            == identity(self.bundle, retouch.get("next_tool"), "spindle")
            and identity(self.bundle, following.get("holder"), "holders")
            == identity(self.bundle, touch["holder"], "holders")
            and _known(retouch.get("top_z"))
            and _known(retouch.get("paper_mm"))
            and math.isclose(retouch["top_z"], top, rel_tol=0, abs_tol=SAME_Z)
            and math.isclose(retouch["paper_mm"], paper, rel_tol=0, abs_tol=SAME_Z)
        )

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
        if getattr(self, "detail", "pedantic") != "pedantic":
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
        # An ``ends`` layout scribes only the arc's two end marks (a guided sweep's stops):
        # no line for the rough to stay outside.
        scribed = feature and any(
            op.get("do") == "scribe" and op.get("layout") != "ends" and op.get("feature") == feature
            for op in earlier
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

    def inspection(self, setup, op):
        """Collect authored criteria and inline procedures at their physical checkpoint."""

        rows = ["? inspection checks not set"] if op.get("checks") == "unknown" else []
        names = op_features(op)
        missing = _mapping(op.get("missing_requirements"))
        method_scopes = {(scope, r) for scope, r, _ in op_entries(op, "inspection_methods")}
        checked = dict.fromkeys(r for _, r, _ in op_entries(op, "checks"))
        targets = op_check_targets(self.bundle, setup, op)
        placed = set()

        def flat_method(requirement, owners):
            return (None, requirement) in method_scopes and not any(
                (owner, requirement) in method_scopes for owner in owners if owner is not None
            )

        def method_note(requirement, owners, method, shared, *, label_owners=False):
            flat = flat_method(requirement, owners)
            key = (requirement, None if flat else tuple(owners))
            if key in placed:
                return (), False
            placed.add(key)
            name = _REQUIREMENT_NAMES.get(requirement, _text(requirement))
            if label_owners and not flat and owners:
                name += " — " + self.feature_names(owners)
            item = self.note(name, method)
            if flat:
                item.sketch = self.inspection_sketch(setup, op, requirement)
            has_fields = (
                any(_FIELD.search(step) for step in [*item[1], *item[2]])
                if isinstance(item, _Steps)
                else bool(_FIELD.search(str(item)))
            )
            return (item,), has_fields and not (flat and shared)

        def resolved(feature, requirement):
            """``(gauge, GO / NO-GO pair, method)`` the op reads ``feature``'s requirement
            with: its feature-scoped entries, else the flat ones."""
            reference = (
                missing[requirement]
                if requirement in missing
                else op_entry(op, "checks", feature, requirement)
            )
            pair = go_no_go_pair(op, feature, requirement)
            return reference, pair, op_entry(op, "inspection_methods", feature, requirement)

        for requirement in [*checked, *(r for r in missing if r not in checked)]:
            selected = [
                target for target in targets if target["identity"]["requirement"] == requirement
            ]
            if requirement in missing or not selected:
                # Authored debt is not a selector target and cannot acquire a fake result.
                owners = [
                    name
                    for name in names
                    if requirement in missing
                    or op_entry(op, "checks", name, requirement) is not None
                ]
                partitions = {}
                for owner in owners or [None]:
                    values = resolved(owner, requirement)
                    key = json.dumps([*values, flat_method(requirement, [owner])], sort_keys=True)
                    partitions.setdefault(key, []).append(owner)
                for group in partitions.values():
                    owners = [owner for owner in group if owner is not None]
                    reference, pair, method = resolved(group[0], requirement)
                    note = (
                        method_note(
                            requirement,
                            owners,
                            method,
                            len(partitions) > 1,
                            label_owners=True,
                        )
                        if method and method != "unknown"
                        else None
                    )
                    rows += self.inspection_rows(
                        requirement,
                        owners,
                        reference,
                        pair,
                        requirement in missing,
                        note,
                        [
                            target
                            for target in selected
                            if target["identity"]["feature_owner"] in group
                        ],
                        debt_subjects=tuple(
                            _field(finding, "subject")
                            for finding in self.findings
                            if _field(finding, "rule") == "inspection"
                            and (evidence := _mapping(_field(finding, "numbers"))).get(
                                "missing_requirement"
                            )
                            and evidence.get("setup_id") == setup["id"]
                            and evidence.get("op_id") == op["op"]
                            and _mapping(evidence.get("identity")).get("feature_owner") in group
                            and _mapping(evidence.get("identity")).get("requirement") == requirement
                        ),
                    )
                continue
            partitions = {}
            for target in selected:
                feature = target["identity"]["feature_owner"]
                key = json.dumps(
                    [
                        target["identity"]["workpiece"],
                        target["shared_check_id"],
                        target["covered_workpieces"],
                        target["kind"],
                        target["gauge"],
                        go_no_go_pair(op, feature, requirement),
                        target["method"],
                        flat_method(requirement, [feature]),
                    ],
                    sort_keys=True,
                )
                partitions.setdefault(key, []).append(target)
            for group in partitions.values():
                first = group[0]
                owners = [
                    target["identity"]["feature_owner"]
                    for target in group
                    if target["identity"]["feature_owner"] is not None
                ]
                method = first["method"]
                note = (
                    method_note(requirement, owners, method, len(partitions) > 1)
                    if method and method != "unknown"
                    else None
                )
                rows += self.inspection_rows(
                    requirement,
                    owners,
                    first["gauge"],
                    go_no_go_pair(op, owners[0] if owners else None, requirement),
                    False,
                    note,
                    group,
                )
        # Only explicit physical checkpoints share results; legacy bands stay separate.
        checkpoints, grouped = {}, []
        for row in rows:
            if not isinstance(row, _Inspection) or not (row.workpiece or row.shared_check_id):
                grouped.append(row)
                continue
            key = (
                row.setup_id,
                row.op_id,
                row.workpiece,
                row.shared_check_id,
                row.covered_workpieces,
            )
            if key not in checkpoints:
                checkpoints[key] = (len(grouped), [row.requirement])
                grouped.append(row)
                continue
            index, requirements = checkpoints[key]
            if row.requirement not in requirements:
                requirements.append(row.requirement)
            previous = grouped[index]
            grouped[index] = replace(
                previous,
                text=previous.text + "; " + row.text,
                features=tuple(dict.fromkeys((*previous.features, *row.features))),
                requirement=", ".join(requirements),
                unit=previous.unit if previous.unit == row.unit else "",
                qualitative=previous.qualitative or row.qualitative,
                subjects=(*previous.subjects, *row.subjects),
                methods=(*previous.methods, *row.methods),
                compact_criteria=(*previous.compact_criteria, *row.compact_criteria),
                reading_owned=previous.reading_owned and row.reading_owned,
            )
        rows = grouped
        for hold in op.get("process_holds", []):
            rows.append(self.process_hold(hold))
        note = op.get("inspection_note")
        if note:
            rows.append(self.note("Inspection", note))
        return rows

    def inspection_rows(
        self, requirement, owners, reference, pair, absent, note, targets, *, debt_subjects=()
    ):
        """Render selected numeric or part-owned criteria, retaining authored debt."""

        def finding_for(target):
            for finding in self.findings:
                if _field(finding, "rule") != "inspection":
                    continue
                evidence = _mapping(_field(finding, "numbers"))
                identity = evidence.get("identity")
                if identity is not None:
                    if (
                        identity == target["identity"]
                        and evidence.get("shared_check_id") == target["shared_check_id"]
                        and evidence.get("covered_workpieces", []) == target["covered_workpieces"]
                        and evidence.get("setup_id", target["setup_id"]) == target["setup_id"]
                        and evidence.get("op_id", target["op_id"]) == target["op_id"]
                    ):
                        return finding
                elif _field(finding, "subject") == target["subject"]:
                    return finding
            return None

        findings = [finding_for(target) for target in targets]
        first = targets[0] if targets else {}
        part_identity = _mapping(first.get("identity"))
        metadata = {
            "setup_id": first.get("setup_id", ""),
            "op_id": first.get("op_id"),
            "workpiece": part_identity.get("workpiece"),
            "shared_check_id": first.get("shared_check_id"),
            "covered_workpieces": tuple(first.get("covered_workpieces", [])),
        }
        name = _REQUIREMENT_NAMES.get(requirement, _text(requirement))
        criteria = {
            feature: self.inspection_band(feature, requirement)
            for feature in ([] if absent else owners)
        }
        bands = [criteria[feature][0] for feature in ([] if absent else owners)]
        target = (
            "(no drawing limit)"
            if absent
            else "?"
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
        unresolved = (
            absent
            or not targets
            or any(target["selection_status"] != "pass" for target in targets)
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
        methods, reading_owned = note or ((), False)
        if first.get("kind") == "manual":
            contract = _mapping(first.get("contract"))
            clauses = contract.get("accept")
            known = (
                contract.get("kind") == "manual"
                and isinstance(clauses, list)
                and bool(clauses)
                and all(
                    isinstance(clause, str) and clause.strip() and clause != "unknown"
                    for clause in clauses
                )
            )
            line = f"{'? ' if unresolved or not known else ''}{name}: {gauge}"
            line += " — " + (
                "; ".join(self.bench(clause) for clause in clauses)
                if known
                else "acceptance criteria not set"
            )
            if first.get("method") in (None, "unknown"):
                line += "; inspection method not set"
            if not known:
                return [
                    _Criterion(line, subjects=tuple(target["subject"] for target in targets)),
                    *methods,
                ]
            return [
                _Inspection(
                    line,
                    (),
                    requirement,
                    qualitative=True,
                    methods=methods,
                    reading_owned=reading_owned,
                    subjects=tuple(target["subject"] for target in targets),
                    compact_criteria=(
                        (
                            identity(self.bundle, reference, "gauges"),
                            gauge,
                            _Criterion(
                                f"{'? ' if unresolved else ''}{name}: "
                                + "; ".join(self.bench(clause) for clause in clauses)
                                + (
                                    "; inspection method not set"
                                    if first.get("method") in (None, "unknown")
                                    else ""
                                ),
                                heading=name,
                                methods=methods,
                                context=name + ":",
                                subjects=tuple(target["subject"] for target in targets),
                                expanded=line,
                            ),
                        ),
                    ),
                    **metadata,
                )
            ]
        if absent or requirement == "unknown" or not owners or not targets:
            if owners:
                line = self.feature_names(owners) + " — " + line
            return [
                _Criterion(
                    line,
                    subjects=tuple(target["subject"] for target in targets) or debt_subjects,
                ),
                *methods,
            ]
        # Equal bands retain the original read-once grouping. Distinct authored
        # bands get distinct result associations, without copying method obligations.
        groups = (
            [(owners, target)]
            if len(set(bands)) == 1
            else [([feature], band) for feature, band in zip(owners, bands, strict=True)]
        )
        rows = []
        for group, band in groups:
            values = [self.features.get(feature, {}).get(requirement) for feature in group]
            known = all(
                value is not None
                and value != []
                and all(
                    _known(item) or isinstance(item, str) and item.strip() not in ("", "unknown")
                    for item in (value if isinstance(value, (list, tuple)) else [value])
                )
                for value in values
            )
            unit = criteria[group[0]][1]
            text = self.feature_names(group)
            shown_band = (
                f"{band} {unit}"
                if self.detail == "pedantic"
                and unit
                and (part_identity.get("workpiece") or first.get("shared_check_id"))
                else band
            )
            text += " — " + line.replace(target, shown_band, 1)
            subjects = tuple(
                target["subject"]
                for target in targets
                if target["identity"]["feature_owner"] in group
            )
            if not known:
                rows.extend([_Criterion(text, subjects=subjects), *(methods if not rows else ())])
                continue
            feature_labels = [self.feature_name(feature) for feature in group]
            repeated_dimension = self.detail != "pedantic" and all(
                re.split(r"[-_\s]+", label.strip())[-1].casefold() == name.casefold()
                for label in feature_labels
            )
            heading = (
                ", ".join(feature_labels)
                if self.detail == "pedantic"
                else _numbered_names(feature_labels)
            ) + ("" if repeated_dimension else " " + name)
            rows.append(
                _Inspection(
                    text,
                    tuple(group),
                    requirement,
                    unit,
                    qualitative=bool(pair)
                    and pair != "unknown"
                    or any(isinstance(value, str) for value in values),
                    methods=methods if not rows else (),
                    reading_owned=reading_owned and len(groups) == 1,
                    subjects=subjects,
                    compact_criteria=(
                        (
                            identity(self.bundle, reference, "gauges"),
                            gauge,
                            _Criterion(
                                ("? " if unresolved else "")
                                + heading
                                + " "
                                + shown_band
                                + (
                                    ", GO / NO-GO sizes not set"
                                    if pair == "unknown"
                                    else self.go_no_go(pair, group[0], requirement, reference)
                                    if pair
                                    else ""
                                )
                                + (" to " + "|".join(map(_text, datums)) if datums else ""),
                                heading=heading,
                                value=(
                                    shown_band
                                    if not unresolved
                                    and not pair
                                    and not datums
                                    and not any(isinstance(value, str) for value in values)
                                    else None
                                ),
                                methods=methods if not rows else (),
                                context=name + ":",
                                subjects=subjects,
                                expanded=text,
                            ),
                        ),
                    ),
                    **metadata,
                )
            )
        return rows

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
        identity = f"Setup {_text(setup['id'])} op {op['op']} {requirement}"
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
                cells.append(
                    self.reference(reference, "consumables")
                    if self.detail != "pedantic"
                    else f"{shown} (in-house)"
                )
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

    def saw_setting(self, op):
        """Where a saw cut runs: a straight cut's blade-centre plane, or the scribed line
        that guides a cut (named by its layout op). Which side of it the saw takes is said
        once, in the cut's target (:meth:`saw_leave`)."""
        if "follows" in op:
            return "guided by the line scribed in " + _text(op["follows"]).replace(":", " op ")
        plane = _mapping(op.get("cut_plane"))
        return (
            f"blade centre {_text(plane.get('axis')).upper()} "
            f"{_number(plane.get('value'))} {self.bundle.features.get('units', '?')}"
        )

    def saw_leave(self, op, purpose=" for filing"):
        """The stock a saw that follows a scribed line leaves on its waste side: ``for
        filing`` at the bench, nothing more on a machine card (a trammel or file takes
        it). The one place a line-following cut names the waste side."""
        allowance = op.get("allowance_mm")
        if not _known(allowance):
            return _Box(f"STOP: stock to leave on the waste side{purpose} not established")
        # A minimum: the saw may leave more for the file, never less.
        return (
            f"leave at least {self.operative(allowance)} mm on the waste side of the scribed "
            f"line{purpose}"
        )

    def feed_direction(self, setup):
        """The way the work moves past a hand-fed blade: from its trailing end toward the
        ``feed_from`` end the cut starts at, as the HOLD and the picture's arrows say."""
        from prechips.kernel import feed_from_ambiguity

        start = _mapping(setup.get("hold")).get("feed_from")
        if start not in _FEED_ENDS:
            return _Box("STOP: feed direction not declared")
        ambiguity = feed_from_ambiguity(self.bundle, setup)
        if ambiguity:
            return _Box(f"STOP: {ambiguity}")
        trailing = ("-" if start[0] == "+" else "+") + start[1]
        return f"feed from {trailing} toward {start}"

    def saw_ends(self, setup, op):
        """Where a saw that follows a scribed line running to the blank's outline enters
        and leaves it (#335): where the cut, the line offset by the allowance into the
        waste, meets the outline (:func:`prechips.kernel.saw_crossings`), in the setup
        frame; "" when the line stays inside the blank or its crossings are unknown."""
        from prechips.kernel import saw_crossings

        if "follows" not in op:
            return ""
        crossings = saw_crossings(self.bundle, setup, op) or []
        if not crossings:
            return ""
        o, allowance = self.operative, self.operative(op["allowance_mm"])
        faces = list(dict.fromkeys(c["face"] for c in crossings))
        # Every number and face printed comes from the crossings themselves: the cut (the
        # line offset by the allowance into the waste) meeting the blank's outline.
        where = f"where the cut, {allowance} mm off the scribed line on the waste side, meets " + (
            "the " + faces[0] + " face" if len(faces) == 1 else "the blank's sides"
        )
        points = [
            f"X {o(c['xy'][0])}, Y {o(c['xy'][1])}" + ("" if len(faces) == 1 else f" ({c['face']})")
            for c in crossings
        ]
        on = f" on the {faces[0]} face" if len(faces) == 1 else ""
        frame = self.frame_tag(setup)
        from prechips.kernel import feed_from_ambiguity

        fed = _mapping(setup.get("hold")).get("feed_from") in _FEED_ENDS
        if len(points) == 2 and fed and not feed_from_ambiguity(self.bundle, setup):
            return f"Enter at {points[0]} and leave at {points[1]}{on}{frame}: {where}."
        return f"Cut through at {' and '.join(points)}{on}{frame}: {where}."

    def straight_saw_target(self, setup, op, numbers):
        """Project a proved straight cut from its retained stock end, not a model zero."""
        subject = f"{setup['id']}:{op['op']}"
        if (
            self.detail == "pedantic"
            or op.get("do") not in SAW_OPS
            or "follows" in op
            or spindle_saw(self.bundle, setup, op)
            or hand_saw(self.bundle, op)
            or self.finding_statuses.get(("saw_cut", subject)) != "pass"
        ):
            return None
        incoming = input_refs(setup)
        if len(incoming) != 1 or not route_identities_known(self.plan, setup.get("id")):
            return None
        graph = MaterialGraph(self.plan)
        material = graph.nodes.get(incoming[0], ())
        if len(material) != 1:
            return None
        root = material[0].root
        if (
            root not in graph.nodes
            or producer_setup(self.plan, root) is not None
            or root == "stock"
            and _mapping(self.plan.get("stock")).get("components")
        ):
            return None
        native = _mapping(_mapping(_mapping(self.bundle.kernel).get("ops")).get(subject))
        plane = _mapping(numbers.get("cut_plane"))
        box = native.get("stock_bbox_before_mm")
        edge = numbers.get("retained_boundary_mm")
        unit = readout_units(self.bundle)
        scale = {"mm": 1.0, "in": 25.4}.get(unit)
        if (
            native.get("saw_error")
            or native.get("saw_reason")
            or plane != native.get("cut_plane")
            or edge != native.get("retained_boundary_mm")
            or plane.get("axis") not in ("x", "y", "z")
            or plane.get("keep") not in ("below", "above")
            or not _known(plane.get("value"))
            or not _known(edge)
            or not isinstance(box, (list, tuple))
            or len(box) != 6
            or not all(_known(value) for value in box)
            or not all(box[index] < box[index + 3] for index in range(3))
            or scale is None
        ):
            return None
        axis = "xyz".index(plane["axis"])
        if not box[axis] < edge < box[axis + 3]:
            return None
        below = plane["keep"] == "below"
        end = box[axis if below else axis + 3]
        sign = 1 if below else -1
        span = sign * (edge - end)
        centre = sign * (plane["value"] - end)
        if centre <= span:
            return None
        side = "lower" if below else "higher"
        target = (
            f"from the {side}-{plane['axis'].upper()} stock end: retained span "
            f"{_number(span / scale)} {unit}; kerf centre {_number(centre / scale)} {unit}"
        )
        return target, "keep that stock end; kerf on the scrap side"

    def hand_saw_step(self, op, numbers, setup=None):
        """A bench hand-saw card: the straight cut's plane and the side kept, or "saw
        outside the scribed line, leave <allowance> for filing"."""
        if "follows" in op:
            separator = "; " if self.saw_leave(op).startswith("STOP") else ", "
            ends = self.saw_ends(setup, op) if setup else ""
            return f"Hand saw {self.saw_setting(op)}{separator}{self.saw_leave(op)}." + (
                " " + ends if ends else ""
            )
        plane = _mapping(op.get("cut_plane"))
        axis = _text(plane.get("axis")).upper()
        sides = {"above": ("+", "-"), "below": ("-", "+")}.get(plane.get("keep"))
        if sides is None:
            return "Hand saw: STOP: side to keep not established."
        length = numbers.get("retained_length_mm")
        kept = f" {_number(length)} mm long" if _known(length) else ""
        edge = numbers.get("retained_boundary_mm")
        retained = f", retained edge {axis} {_number(edge)} mm" if _known(edge) else ""
        return (
            f"Hand saw across the part, keeping the {sides[0]}{axis} piece{kept}; the kerf "
            f"falls on the {sides[1]}{axis} (waste) side (blade centre {axis} "
            f"{_number(plane.get('value'))} {self.bundle.features.get('units', '?')}{retained})."
        )

    def speeds(self, setup, op, saw_table):
        numbers = self.records.get(("speeds_feeds", f"{setup['id']}:{op['op']}"), {})

        def blocked(text, status="unknown"):
            return _Box(
                text,
                source="speeds_feeds",
                status=status,
                scope=f"{setup['id']}:{op['op']}",
            )

        if op.get("do") in MANUAL:
            return "—", "—", False
        if hand_saw(self.bundle, op):
            # A hand saw: no blade speed or machine feed applies.
            return "—", "—", False
        slitting = slitting_saw(self.bundle, op)
        if op.get("do") in SAW_OPS and not slitting and "follows" in op:
            # A vertical bandsaw following a scribed line: the work is fed by hand.
            speed = numbers.get("blade_speed_sfm")
            return (
                (_number(speed) + " sfm") if _known(speed) else blocked("STOP: no blade speed"),
                "by hand",
                not _known(speed),
            )
        if op.get("do") in SAW_OPS and not slitting:
            speed = numbers.get("blade_speed_sfm")
            feed = numbers.get("feed_mm_min")
            return (
                (_number(speed) + " sfm") if _known(speed) else blocked("STOP: no blade speed"),
                (_number(feed) + " mm/min") if _known(feed) else blocked("STOP: no feed"),
                not (_known(speed) and _known(feed)),
            )
        rpm = numbers.get("rpm")
        authored = numbers.get("rpm_basis") == "authored"
        rpm_stop = authored and numbers.get("rpm_status") != "pass"
        if authored:
            requested = numbers.get("requested_rpm")
            speed = (
                f"{_number(requested)} rpm requested"
                if _known(requested)
                else "requested RPM unknown"
            )
            if rpm_stop:
                speed = blocked(_authored_rpm_stop(numbers), numbers.get("rpm_status", "unknown"))
        if slitting:
            feed = numbers.get("feed_mm_min")
            return (
                speed
                if authored
                else (_number(rpm, 0) + " rpm")
                if _known(rpm)
                else blocked("STOP: no starting rpm"),
                (_number(feed, 0) + " mm/min")
                if _known(feed)
                else blocked("STOP: no starting feed"),
                rpm_stop or not (_known(rpm) and _known(feed)),
            )
        if not authored:
            speed = _number(rpm, 0) + " rpm" if _known(rpm) else blocked("STOP: no starting rpm")
        per_rev, per_min = numbers.get("feed_mm_rev"), numbers.get("feed_mm_min")
        if numbers.get("feed_direction") == "axial":
            axial = numbers.get("axial_feed_mm_rev")
            feed = (
                f"axial {_number(per_min, 0)} mm/min ({axial:.3f} mm/rev)"
                if _known(per_min) and _known(axial)
                else blocked("STOP: no starting feed")
            )
        elif "feed_mm_rev" in numbers:
            feed = (
                [f"{per_rev:.3f}".rstrip("0").rstrip(".") + " mm/rev"]
                if _known(per_rev)
                else [blocked("STOP: no starting feed")]
            )
            if _known(per_rev) and per_rev * 100 == int(per_rev * 100):
                feed = [f"{per_rev:.2f} mm/rev"]
            if _known(per_min):
                feed.append(f"({_number(per_min, 0)} mm/min)")
        else:
            feed = (
                _number(per_min, 0) + " mm/min"
                if _known(per_min)
                else blocked("STOP: no starting feed")
            )
        return speed, feed, rpm_stop or not (_known(rpm) and (_known(per_rev) or _known(per_min)))

    def unset_z(self, setup, op, target):
        """An op cut before a face-then-set Z zero exists cannot stop on a DRO number: its
        Z reads as a height above Z0 the machinist measures, and says when Z is set."""
        if readout_kind(self.bundle) != "digital":
            return target
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
        """Structured action, explicit allowances, passes and depth-of-cut basis."""
        do = str(op.get("do", ""))
        basis = "on the face" if do in FACING else "on Ø" if lathe else "per side"
        allowances = tuple(
            (key, op[key], basis)
            for key in ("rough_allowance_mm", "stock_to_leave_mm")
            if key in op
        )
        numbers = self.records.get(("speeds_feeds", f"{setup['id']}:{op['op']}"), {})
        rough = numbers.get("diameter_in")
        rough = rough * 25.4 if lathe and do == "rough_turn" and _known(rough) else None
        doc = None
        if "doc_mm" in op and do not in {"part_off", "cut_to_fit"}:
            kind = (
                "axial per pass"
                if not lathe
                else "axial per pass (facing)"
                if do in FACING
                else "radial, total plunge depth"
                if do == "form_relief"
                else "per pass, square to the dome"
                if do == "form_dome"
                else "radial per pass"
            )
            doc = (op["doc_mm"], kind)
        return _CutDepths(
            _text(do),
            rough if allowances else None,
            allowances,
            (op["passes"],) if "passes" in op else (),
            doc,
        )

    def cut_depth_text(self, facts, *, compact=False, omit_doc=False):
        """Keep ledger millimetres unchanged; compact clauses use the job readout."""
        scale = {"mm": 1.0, "in": 25.4}.get(self.units)
        display_units = readout_units(self.bundle)

        def length(value):
            if compact and scale and display_units in ("mm", "in"):
                value = _amount(value)
                return self.readout(value / scale) if _known(value) else "?"
            return self.operative(value)

        unit = "" if compact and scale and display_units in ("mm", "in") else " mm"
        parts = [facts.verb]
        for key, value, basis in facts.allowances:
            if not compact and key == "stock_to_leave_mm" and value == 0:
                continue
            if facts.rough_diameter_mm is not None and (not compact or len(parts) == 1):
                parts[0] += f" to Ø{length(facts.rough_diameter_mm)}"
            parts.append(f"leave {length(value)}{unit} {basis}")
        if facts.passes:
            parts.append(f"{_text(facts.passes[0])} passes")
        if facts.doc is not None and not omit_doc:
            value, kind = facts.doc
            parts.append(f"{length(value)}{unit} {kind}")
        return parts if not compact or len(parts) > 1 else []

    def manual_arc_lines(self, setup, op):
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
            lines.append(
                _Box(
                    "STOP: manual arc not proven"
                    + (f" — {'; '.join(reasons)}" if reasons else "")
                    + " — do not run."
                )
            )
        return lines

    def arc_end_marks(self, op, numbers):
        """A guided sweep's layout: mark A and mark B at the arc's two ends on the work
        top, each measured from the stock's own faces (manual_arc ``marks``); the sweep sets
        its stops on them. Unknown marks print no dimension (the op's STOP follows)."""
        marks = numbers.get("marks")
        unit = self.bundle.features.get("units", "")
        feature = self.feature_name(op.get("feature"))
        if not (isinstance(marks, list) and len(marks) == 2):
            return f"Layout: the ends of {feature} are not placed — no marks to scribe."
        decimals = 1 if unit == "mm" else 3
        placed = [
            f"mark {letter} at {mark['x']:.{decimals}f} {unit} from the {mark['x_face']} along "
            f"X and {mark['y']:.{decimals}f} {unit} from the {mark['y_face']} along Y, its "
            f"stroke at {mark['angle']:.1f}° to that edge"
            for letter, mark in zip("AB", marks, strict=True)
        ]
        return (
            f"Layout: blue the work top. At each end of the {feature}, prick a point with a "
            "rule and square and, with a protractor on the edge named, scribe through it a "
            f"short stroke toward the arc's centre: {placed[0]}; {placed[1]}. The guided "
            "sweep sets its stops on these strokes."
        )

    def manual_arc_steps(self, op, numbers, proven):
        """The layout or bench-filing line itself; ``proven`` says whether the rule passed it."""
        o = self.operative
        if op.get("do") == "scribe" and numbers.get("layout") == "ends":
            return [_Plain(self.arc_end_marks(op, numbers))]
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
                f"about the centre X {o(centre[0])}, Y {o(centre[1])}{self.frame_tag()}"
            )
            if axis:
                line += f", on the axis of {self.feature_name(axis)}"
            line += f", with {instrument}"
            ends = numbers.get("ends_setup_xy")
            if isinstance(ends, list) and len(ends) == 2:
                line += (
                    f"; arc ends X {o(ends[0][0])}, Y {o(ends[0][1])} and "
                    f"X {o(ends[1][0])}, Y {o(ends[1][1])}{self.frame_tag()}"
                )
            elif ends is None:
                line += "; scribe the full circle"
            return [_Plain(line + ".") if proven else _Box(line + ".", source="manual_arc")]
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
        return [_Plain(line + ".") if proven else _Box(line + ".", source="manual_arc")]

    def operation_rows(self, setup, tool_numbers):
        """One semantic operation collection, projected only when rendered."""
        ops = setup.get("ops", [])
        rows, instructions, fallbacks, prefixes = [], {}, {}, {}
        facts = {}
        where = {"contours": f"Setup {_text(setup['id'])} contour instructions"}
        saw_table = any(op.get("do") in SAW_OPS for op in ops)
        # A bench of hand steps, hand-saw cuts among them, runs no machine either.
        bench = manual_bench(self.bundle, setup) is not None
        finishing = bool(ops) and (bench or all(op.get("do") in MANUAL for op in ops))
        lathe = self.lathe(setup)
        # Each lathe op that runs the spindle turns it one way (:meth:`spindle_turn`). When
        # every one turns it the same known way, the heading says so once and the narrow
        # rpm cells carry the rpm alone; else each cell names its own turn.
        spins = {
            str(op["op"]): self.spindle_turn(op)
            for op in ops
            if lathe and op.get("do") not in MANUAL | SAW_OPS
        }
        op_findings = {}
        for finding in self.findings:
            if finding_decision(finding, self.bundle) == "none":
                continue
            evidence = _mapping(_field(finding, "numbers"))
            if _field(finding, "rule") == "inspection" and isinstance(
                evidence.get("identity"), dict
            ):
                if evidence.get("setup_id") == setup["id"] and evidence.get("op_id") is not None:
                    op_findings.setdefault(str(evidence["op_id"]), []).append(finding)
                continue
            subject = _field(finding, "subject", "")
            if subject.startswith(setup["id"] + ":"):
                op_findings.setdefault(subject.split(":", 1)[1], []).append(finding)
        for op in ops:
            feature = op.get("feature")
            number = tool_numbers.get(self.tool_pair(op.get("tool"), op.get("holder")))
            manual = op.get("do") in MANUAL
            saw = op.get("do") in SAW_OPS
            action = self.cut_depth_text(self.cut_depths(setup, op, lathe))
            if saw:
                action.append(self.saw_setting(op))
                if debt := self._spindle_saw_op_debt(setup, op, "geometry"):
                    action.append(
                        _Box(
                            "STOP: " + debt,
                            source=debt.source,
                            status=debt.status,
                            kind=debt.kind,
                            scope=debt.scope,
                        )
                    )
            reference = op.get("tool")
            if op.get("do") == "coating":
                tool = self.coating(op)
            elif manual and reference is None and _bonding_op(setup, op):
                tool = self.compound_product(setup, setup["joint"]["compound"])
            elif manual and reference is None:
                tool = "—"
            elif reference in (None, "unknown"):
                tool = _Box("STOP: no tool")
            else:
                number = tool_numbers.get(self.tool_pair(reference, op.get("holder")))
                # The TOOLS table above names the tool; the op row carries its T number.
                tool = number or self.tool_name(reference)
                if resolve(self.bundle, "tools", reference) is None:
                    tool = [tool, _Box("STOP: tool not in the shop list")]
            speed, feed, missing = self.speeds(setup, op, saw_table)
            if missing:
                debts = self.records.get(("speeds_feeds", f"{setup['id']}:{op['op']}"), {}).get(
                    "measurements", []
                )
                markers = " ".join(self.measurement_marker(debt) for debt in debts)

                def marked(values, label, markers=markers):
                    if isinstance(values, list):
                        return [marked(value, label, markers) for value in values]
                    if isinstance(values, _Box):
                        return _Box(
                            str(values) + (f" {markers}" if markers else ""),
                            source=values.source,
                            status=values.status,
                            kind=values.kind,
                            scope=values.scope,
                            decision_text=values.decision_text,
                            notice_group=values.notice_group,
                        )
                    return values

                speed, feed = marked(speed, "rpm"), marked(feed, "feed")
            turn = spins.get(str(op["op"]))
            if isinstance(turn, _Box):
                speed = [speed, turn]
            elif turn is not None:
                speed = [speed, turn]
            plunge = self.plunge_feed(setup, op)
            if isinstance(plunge, _Box):
                feed = [*(feed if isinstance(feed, list) else [feed]), plunge]
            elif plunge is not None:
                feed = [*(feed if isinstance(feed, list) else [feed]), f"plunge {plunge}"]
            direction = op.get(
                "direction",
                "not_applicable" if manual or op.get("do") in _AXIAL_OPS else None,
            )
            direction = self.direction(direction)
            scribed = saw and "follows" in op
            if saw:
                plane = _mapping(op.get("cut_plane"))
                side = {"below": "lower", "above": "higher"}.get(plane.get("keep"))
                direction = (
                    self.feed_direction(setup)
                    if scribed
                    else f"keep {side}-{_text(plane['axis']).upper()} side of blade-centre plane"
                    if side and plane.get("axis") in ("x", "y", "z")
                    else "keep " + _text(plane.get("keep"))
                )
            saw_numbers = self.records.get(("saw_cut", f"{setup['id']}:{op['op']}"), {})
            rest_cells, rest_lines = ([], []) if saw else self.rest_steps(setup, op)
            if scribed:
                target = [self.saw_leave(op, ""), self.saw_ends(setup, op)]
                target = [part for part in target if part]
            elif saw:
                target = [
                    "retained "
                    + _text(_mapping(op.get("cut_plane")).get("axis")).upper()
                    + " edge "
                    + _number(saw_numbers.get("retained_boundary_mm"))
                    + " mm"
                ]
                physical_target = self.straight_saw_target(setup, op, saw_numbers)
                if physical_target is not None:
                    target = [physical_target[0]]
                    direction = physical_target[1]
            else:
                target = (
                    self.hole_xy(setup, op)
                    + self.tip(setup, op)
                    + self.relief_plunges(setup, op)
                    + rest_cells
                )
            target_stops = [
                line for line in target if isinstance(line, _Box) and line.startswith("STOP:")
            ]
            if target_stops:
                endpoint = self.endpoint(setup, op)
                if (
                    endpoint
                    and endpoint.get("dro_grid_debt")
                    and any(line.startswith("STOP: DRO ") for line in target_stops)
                ):
                    markers = " ".join(
                        self.measurement_marker(debt)
                        for debt in dro_grid_measurements(self.bundle, setup)
                    )
                    target = [
                        _Box(f"{line} {markers}")
                        if isinstance(line, _Box) and line.startswith("STOP: DRO ")
                        else line
                        for line in target
                    ]
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
                category, key = identity(self.bundle, reference, "tools")
                item = resolve(self.bundle, "tools", reference) or {}
                debt = length_debt(item, "nose_radius", category, key)
                text = (
                    self.measurement_stop(op, number, debt)
                    if debt
                    else "tool-nose offset for the profile not computed"
                )
                boxes.append(
                    _Box(
                        "STOP: tool-nose offset not computed — "
                        + (f"{text} — " if debt else "")
                        + f"see {where['contours']}"
                    )
                )
            finding_facts = [
                self.finding_fact(finding) for finding in op_findings.get(str(op["op"]), [])
            ]
            for group in _decision_groups(finding_facts):
                fact = group[0]
                kind, text = fact.kind, fact.text
                boxes.append(
                    _Box(
                        (
                            ""
                            if text.startswith("STOP: ")
                            else "STOP: "
                            if kind == "block"
                            else "CAUTION: "
                        )
                        + text,
                        source=fact.source,
                        status=fact.status,
                        kind=kind,
                        scope=fact.scope,
                        decision_text=text,
                    )
                )
            boxes.extend(self.manual_arc_lines(setup, op))
            boxes.extend(rest_lines)
            # Crash and status warnings print full width under the op so the narrow
            # action column keeps its line height; the op's own note follows them there.
            note = op.get("note")
            derivation = self.tip_note(setup, op)
            derived = " ".join(
                filter(
                    None,
                    [
                        derivation,
                        self.compound_note(setup, op),
                        self.keep_note(setup, op),
                        self.faced_aim_note(setup, op),
                    ],
                )
            )
            instructions[str(op["op"])] = derived
            fallbacks[str(op["op"])] = ", ".join(action)
            instruction = " ".join(
                filter(
                    None,
                    [
                        self.bench(note_text(note), setup) if note else None,
                        derived,
                    ],
                )
            )
            if instruction and not finishing:
                boxes.append(_OperationNote(instruction, note, derived))
            if str(op["op"]) in self.contour_ops:
                what = "guided sweep" if str(op["op"]) in self.sweep_ops else "contour table"
                boxes.append(_Plain(f"See {what} on {where['contours']}"))
            for text, blocked in getattr(self, "contour_stop_rows", {}).items():
                if str(op["op"]) in blocked:
                    boxes.append(
                        _Box(
                            "STOP: " + text,
                            source=text.source if isinstance(text, _Box) else "producer",
                            status=text.status if isinstance(text, _Box) else "unknown",
                            kind=text.kind if isinstance(text, _Box) else "block",
                            scope=f"{setup['id']}:{op['op']}",
                        )
                    )
            features = (
                ", ".join(self.feature_label(f, marked=False) for f in op_features(op))
                if feature is not None
                else "stock"
                if saw
                else "?"
            )
            inspection = self.inspection(setup, op)
            facts[str(op["op"])] = tuple(
                dict.fromkeys(
                    [
                        *_typed_values(
                            [action, tool, speed, feed, target, direction, boxes],
                            f"{setup['id']}:{op['op']}",
                        ),
                        *finding_facts,
                    ]
                )
            )
            if finishing:
                step = instruction or ", ".join(action)
                if saw:
                    # A hand-saw card: where the blade runs and what it leaves, then the note.
                    prefixes[str(op["op"])] = self.hand_saw_step(op, saw_numbers, setup)
                    step = " ".join(
                        filter(None, [self.hand_saw_step(op, saw_numbers, setup), instruction])
                    )
                cells = (_text(op["op"]), features, tool, step)
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
        for row, op in zip(rows, ops, strict=True):
            members = operation_members(self.bundle, setup, op)
            row.setup_id, row.op_id = setup["id"], op["op"]
            row.workpiece = members[0] if members and len(members) == 1 else None
            row.authored_note = op.get("note")
            row.instruction_after = instructions[str(op["op"])]
            row.instruction_before = prefixes.get(str(op["op"]), "")
            row.instruction_fallback = fallbacks[str(op["op"])]
            row.tool_label = (
                self.tool_name(op["tool"]) if op.get("tool") not in (None, "unknown") else None
            )
            row.tool_spec = (
                getattr(self, "_tool_specs_by_setup", {})
                .get(setup["id"], {})
                .get(self.tool_pair(op.get("tool"), op.get("holder")), ())
            )
            row.spindle_turn = spins.get(str(op["op"]))
            row.decisions = facts[str(op["op"])]
        return rows

    def operation_table(self, setup, rows, *, results=True):
        if not rows:
            return ""
        headings = (
            ["step", "feature", "material / consumable", "action", "inspection"]
            if len(rows[0]) == 5
            else ["op", "do", "feature", "tool", "rpm", "feed", "target", "direction", "inspection"]
        )
        safety = ""
        if self.lathe(setup):
            turns = dict.fromkeys(
                getattr(row, "spindle_turn", None)
                for row in rows
                if getattr(row, "spindle_turn", None) in _SPINDLE_TURNS
            )
            safety += (
                _p("; ".join(f"Spindle {turn}: {_SPINDLE_TURNS[turn]}" for turn in turns))
                if turns
                else ""
            )
            if any(row[-1] for row in rows):
                safety += _p("Measure only with the spindle stopped and the tool withdrawn.")
        return (
            safety
            + '<table class="operations"><thead><tr class="repeat"><th>'
            + _numeric_html(f"Setup {setup['id']} — operations")
            + "</th></tr></thead>"
            + "".join(
                _ledger_row(
                    row,
                    headings,
                    detail=getattr(self, "detail", "pedantic"),
                    show_settings=not getattr(self, "settings_active", False),
                    results=results,
                    note_transform=lambda text: self.bench(text, setup),
                )
                for row in rows
            )
            + "</table>"
        )

    def operations(self, setup, tool_numbers):
        rows = self._rows_by_setup.get(setup["id"]) if hasattr(self, "_rows_by_setup") else None
        if rows is None:
            rows = self.operation_rows(setup, tool_numbers)
        return self.operation_table(setup, rows), [
            decision for row in rows for decision in row.decisions
        ]

    # -------------------------------------------------------------- contours
    def waypoints(self, setup):
        render = _mapping(_mapping(self.report.get("renders")).get(setup["id"]))
        points = _mapping(render.get("scene")).get("waypoints")
        return [_mapping(p) for p in points] if isinstance(points, list) else []

    def waypoint(self, waypoints, op, point, row=None):
        """The nearest same-op picture key at the actual DRO point, within length tolerance.

        Picture points are mm; table points are in plan units. Native clipped sketches
        can retain original row ids after holes disappear, so an id only breaks a tie
        between keys at the same point, never establishes a geometric match.
        """
        scale = {"mm": 1.0, "in": 25.4}.get(self.units)
        if (
            scale is None
            or not isinstance(point, (list, tuple))
            or len(point) != 2
            or not all(map(_known, point))
        ):
            return ""
        target = [value * scale for value in point]
        matches = []
        for record in waypoints:
            if str(record.get("op")) != str(op):
                continue
            xy = record.get("xy") if row is not None else record.get("xy", record.get("xz"))
            if isinstance(xy, (list, tuple)) and len(xy) == 2 and all(map(_known, xy)):
                distance = math.dist(xy, target)
                if distance <= LENGTH_TOLERANCE_MM:
                    matches.append(
                        (distance, row is None or row not in (record.get("rows") or []), record)
                    )
        if not matches:
            return ""
        return str(min(matches, key=lambda match: match[:2])[2].get("label", ""))

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
    def clip(table, markers, rows, label_column=0):
        """Name real clipped ends, not every generated hole that carries a clip marker.

        Whole-hole exclusions use ``dropped_ends``; a split chain's 1-based fragment
        identifies its internal break ends. Neither invents another drill position.
        A singleton names the stock drilling leaves, never a web breakout.
        These are sentence fragments: the coordinate caption owns the final period.
        """
        ends = []
        fragment = table.get("fragment")
        chain = table.get("method") == "chain_drill"
        if chain and rows:
            last = len(rows) - 1
            flags = [bool(markers and markers[0]), last < len(markers) and bool(markers[last])]
            dropped = table.get("dropped_ends")
            known_ends = (
                isinstance(dropped, list)
                and len(dropped) == 2
                and all(isinstance(end, bool) for end in dropped)
            )
            split = (
                isinstance(fragment, list)
                and len(fragment) == 2
                and all(
                    isinstance(value, int) and not isinstance(value, bool) for value in fragment
                )
                and 1 <= fragment[0] <= fragment[1]
                and fragment[1] > 1
            )
            if split:
                flags = [
                    fragment[0] > 1 or (dropped[0] if known_ends else flags[0]),
                    fragment[0] < fragment[1] or (dropped[1] if known_ends else flags[1]),
                ]
            elif known_ends:
                # Regenerated rows all carry provenance markers, not end-stop flags.
                flags = (
                    list(dropped)
                    if table.get("regeneration") == "true_curve"
                    else [flags[0] or dropped[0], flags[1] or dropped[1]]
                )
            for index, flag, verb in ((0, flags[0], "starts"), (last, flags[1], "stops")):
                if flag:
                    point = rows[index][label_column] or f"hole #{index + 1}"
                    ends.append(f"{verb} at {point}")
        elif not chain:
            for index, marker in enumerate(markers):
                if not marker or index >= len(rows):
                    continue
                point = rows[index][label_column] or f"row {index + 1}"
                ends.append(("starts at " if index == 0 else "stops at ") + point)
        text = ""
        if ends:
            if chain and len(rows) == 1:
                point = rows[0][label_column] or "#1"
                text = (
                    f"; retained hole {point}: stock beyond its bounded "
                    + ("end" if len(ends) == 1 else "ends")
                    + " is outside this op's area and not cleared by drilling"
                )
            elif chain:
                text = (
                    f"; {' and '.join(ends)}: stock beyond "
                    + ("it" if len(ends) == 1 else "them")
                    + " is outside this op's area, not for this breakout"
                )
            else:
                text = (
                    f"; {' and '.join(ends)}: the stock past "
                    + ("it" if len(ends) == 1 else "them")
                    + " is outside this op's area"
                )
        if isinstance(fragment, list) and len(fragment) == 2:
            text += (
                f"; piece {fragment[0]} of {fragment[1]}: no cut links the pieces, so the "
                "stock between them is not cleared by this op"
            )
        return text

    def raster_clearance(self, setup, profile):
        """Proven air around the actual setup-entry stock box, never a removal allowance.

        Named run-axis ends and the open-side entry need positive clearance on that side.
        The every-pass claim instead checks each full finite cutter disk, so a diagonal
        corner gap can prove clearance even when neither axis alone does. Tangency proves
        neither air claim. A keep-out's inner piece ends must each be proven too.
        """
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
        box = stock_box(self.bundle, setup)
        scale = {"mm": 1.0, "in": 25.4}.get(self.units)
        if box is None or scale is None or not _known(radius) or run is None:
            return ""
        radius_mm = radius * scale

        def clear_side(axis, centre, side):
            # Project onto this side: a gap on the other axis cannot certify it.
            point = [box[0] / scale, box[1] / scale]
            point[axis] = centre
            outside = centre * scale < box[axis] if side < 0 else centre * scale > box[axis + 3]
            return outside and in_air(box, point, radius_mm, scale)

        # The outer ends are every piece's ends only when no keep-out split a pass.
        whole = bool(points) and all(min(abs(p[run] - end) for end in ends) <= 1e-9 for p in points)
        low, high = sorted(ends)
        air = [s for v, s in ((low, -1), (high, 1)) if clear_side(run, v, s)]
        every = bool(points) and all(in_air(box, point, radius_mm, scale) for point in points)
        text = ""
        if air:
            text += "; " + self._raster_air_ends(pieces if points else [], run, axis, air, whole)
            text += ", clear of stock"
        if every and air:
            text += " — every pass runs in and out clear"
        elif every:
            text += "; every pass runs in and out clear of stock"
        elif air and not whole:
            text += (
                "; a keep-out splits passes into pieces that also start and stop between,"
                " not proven clear"
            )
        entry, side = raster.get("entry_pass"), str(raster.get("open_side", "")).upper()
        across = 1 - run
        if (
            _known(entry)
            and side in ("-X", "+X", "-Y", "+Y")
            and "XY".index(side[1]) == across
            and clear_side(across, entry, -1 if side[0] == "-" else 1)
        ):
            text += f"; pass 1 enters from air, clear of stock on the open {side} side"
        area_ends = raster.get("area_ends")
        if (
            text
            and isinstance(area_ends, list)
            and len(area_ends) == 2
            and all(map(_known, area_ends))
            and min(area_ends) - low >= radius - 1e-9
            and high - max(area_ends) >= radius - 1e-9
        ):
            text += "; cutter centres extend at least a radius beyond the planned cut area"
        return text

    @staticmethod
    def _raster_air_ends(pieces, run, axis, air, whole):
        """The in-air ``air`` ends (-1 low, +1 high along the ``run`` axis) named by their
        role in the printed pass direction: every emitted piece of a one-way raster runs the
        same way, so the end it starts from is where each pass enters and the other where it
        leaves. A keep-out splits passes into pieces the table numbers as passes, some of
        which start or stop at the keep-out, so a split raster names only its outer ends,
        by the side the feed enters or leaves. Pieces with no single direction name the ends
        by their side only."""
        senses = {(b[run] > a[run]) - (b[run] < a[run]) for a, b in pieces}
        if len(senses) != 1 or 0 in senses:
            if len(air) == 2:
                return "pass ends both in air"
            return f"the {'-' if air[0] < 0 else '+'}{axis} pass end is in air"
        (start,) = senses
        start = -start  # a pass running toward +axis enters from the -axis end
        sign = {-1: "-", 1: "+"}
        if not whole:
            roles = {start: "enters", -start: "leaves"}
            if len(air) == 2:
                return (
                    f"the outer {sign[start]}{axis} and {sign[-start]}{axis} ends, where the "
                    "feed enters and leaves, are in air"
                )
            return f"the outer {sign[air[0]]}{axis} end, where the feed {roles[air[0]]}, is in air"
        roles = []
        if start in air:
            roles.append(f"each pass enters from air at {sign[start]}{axis}")
        if -start in air:
            leaves = f"leaves into air at {sign[-start]}{axis}"
            roles.append(leaves if roles else "each pass " + leaves)
        return " and ".join(roles)

    def outline_clearance(self, setup, profile, part):
        """Name only rows whose whole finite cutter clears the actual entry stock box.
        A diagonal corner gap can prove air; tangent contact and missing stock cannot.
        """
        box, radius = stock_box(self.bundle, setup), profile.get("cutter_radius_mm")
        scale = {"mm": 1.0, "in": 25.4}.get(self.units)
        points = profile.get("cutter_centre")
        if box is None or scale is None or not _known(radius) or not isinstance(points, list):
            return part
        rank, description, headings, rows, after = part
        named = sorted(
            {
                row[0] or f"row {index}"
                for index, (row, point) in enumerate(zip(rows, points, strict=False), start=1)
                if isinstance(point, list)
                and len(point) >= 2
                and all(map(_known, point[:2]))
                and in_air(box, point, radius, scale)
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
        return _Box(
            "STOP: plunge feed not set" + (f" — {why}" if why else ""), source="coordinates"
        )

    def level_entries(self, setup, op, waypoints):
        """How the path goes down and returns at each depth, as ``level_paths`` proved.
        Explicit tangent contact lowers at the stock edge, never in air or at a fabricated
        plunge feed. Unresolved starts retain their plunge obligation.
        """
        o = self.operative if self.detail == "pedantic" else self.readout
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
                if any(down.get("contact") == "tangent" for down in downs):
                    groups = {}
                    for down in downs:
                        kind = (
                            "tangent"
                            if down.get("contact") == "tangent"
                            else "air"
                            if down.get("air")
                            else "cutting"
                        )
                        groups.setdefault(kind, []).append(down)
                    instructions = []
                    for kind, starts in groups.items():
                        if len(starts) == len(downs):
                            lead = "at each pass start"
                        elif len(starts) == 1:
                            lead = "at the pass starting " + where(starts[0])
                        else:
                            lead = "at the passes starting " + " and ".join(map(where, starts))
                        if kind == "tangent":
                            lead += ", at the stock edge (tangent contact)"
                        elif kind == "air":
                            lead += ", clear of the stock"
                        action = lower if lowered or kind != "cutting" else plunge
                        instructions.append(f"{lead}: {action}")
                    return "; ".join(instructions)
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
                if down.get("contact") == "tangent":
                    steps.append(
                        f"{lead}{where(down)}, at the stock edge (tangent contact): {lower}"
                    )
                elif lowered:
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

    def compact_facing_path(self, entry, path, depths):
        """One-way raster facts, only when the existing entry/return proof is complete."""
        profiles = entry.get("raster_profiles", [])
        if len(profiles) != 1 or len(depths) != 1:
            return None
        profile = profiles[0]
        raster = profile["raster"]
        segments = profile.get("cutter_centre")
        lift = raster.get("lift_z")
        if (
            raster.get("cycle") != "one_way"
            or raster.get("run_axis") != "x"
            or not isinstance(segments, list)
            or not segments
            or raster.get("passes") != len(segments)
            or not _known(lift)
            or path.get("raise_z") != lift
            or path.get("raise_clear") is not True
            or profile.get("dro_to_z", profile.get("to_z")) != depths[0]
            or not all(
                isinstance(segment, list)
                and len(segment) == 2
                and all(
                    isinstance(point, list) and len(point) == 2 and all(map(_known, point))
                    for point in segment
                )
                for segment in segments
            )
        ):
            return None
        start, end = segments[0][0][0], segments[0][1][0]
        entries = path.get("entries", [])
        entry_kinds = {
            "air"
            if down.get("air") is True and down.get("contact") in (None, "air")
            else "tangent"
            if down.get("air") is False and down.get("contact") == "tangent"
            else None
            for down in entries
        }
        if len(entries) != len(segments) or any(
            segment[0][0] != start
            or segment[1][0] != end
            or segment[0][1] != segment[1][1]
            or down.get("xy") != segment[0]
            or len(entry_kinds) != 1
            or None in entry_kinds
            for segment, down in zip(segments, entries, strict=True)
        ):
            return None
        return (
            self.readout(depths[0]),
            self.readout(lift),
            self.readout(start),
            self.readout(end),
            ", ".join(self.readout(segment[0][1]) for segment in segments),
            next(iter(entry_kinds)),
        )

    def route_contour_parts(self, setup, tools, blocks, stops):
        """Compact canonical coordinate rows, retaining order, depth and lift/return."""
        paths = {}
        for op_id, entry in blocks.items():
            op = next(op for op in setup.get("ops", []) if str(op["op"]) == op_id)
            if op.get("tool") in (None, "unknown") or not self.setup_tool(tools, op.get("tool")):
                if stops is not None:
                    text = _Box(
                        f"{self.feature_name(op.get('feature')).upper()} — tool not selected; "
                        "do not run.",
                        source="tool_resolves",
                    )
                    stops.setdefault(text, []).append(op_id)
                    if not entry["parts"] and entry["stops"]:
                        reasons = " — ".join(dict.fromkeys(entry["stops"]))
                        stops.setdefault(_Box(reasons, source="coordinates"), []).append(op_id)
                continue
            levels = self.z_levels(setup, op) or {}
            path = self.level_path(setup, op.get("op"))
            depths = levels.get("levels", path.get("levels"))
            depth_line = (
                "Depths: " + ", then ".join("Z" + self.readout(z) for z in depths) + "."
                if isinstance(depths, list) and depths
                else ""
            )
            pieces = [(depth_line, "")] if depth_line else []
            entries = path.get("entries")
            ordinary_entry = (
                isinstance(entries, list)
                and entries
                and all(down.get("air") or down.get("contact") == "tangent" for down in entries)
            )
            if (
                op.get("do") in FACING
                and entry.get("raster")
                and len(entry["parts"]) == 1
                and not entry["stops"]
                and not entry.get("unresolved")
                and ordinary_entry
                and isinstance(depths, list)
                and depths
                and all(map(_known, depths))
                and _known(entry.get("raster_step"))
            ):
                facing = self.compact_facing_path(entry, path, depths)
                if facing is not None:
                    self._route_facing_paths[(setup["id"], op_id)] = facing
                    text = "Face Z" + " → ".join(self.readout(z) for z in depths)
                    text += "; maximum stepover " + self.readout(entry["raster_step"]) + "."
                    paths[op_id] = (text, "")
                    continue
            if not ordinary_entry:
                if entry_note := self.level_entries(setup, op, self.waypoints(setup)):
                    pieces.append(("", entry_note))
            if not entry["parts"]:
                reasons = list(dict.fromkeys(entry["stops"]))
                text = "contour points not computed" + "".join(" — " + reason for reason in reasons)
                if stops is not None:
                    stops.setdefault(text, []).append(op_id)
            for _, description, headings, rows, after in sorted(
                entry["parts"], key=lambda part: part[0]
            ):
                if isinstance(description, list):
                    pieces.append(("", _list(description)))
                    continue
                if headings == ["pass", "X from", "Y from", "X to", "Y to", "Z"] and rows:
                    # Consecutive passes along one axis over the same span and Z share their
                    # instruction, never their results; any other pass prints whole.
                    runs = []
                    for row in rows:
                        run = (
                            ("X", row[1], row[3], row[5], "Y")
                            if row[2] == row[4]
                            else ("Y", row[2], row[4], row[5], "X")
                            if row[1] == row[3]
                            else None
                        )
                        across = row[2] if row[2] == row[4] else row[1]
                        if run and runs and runs[-1][0] == run:
                            runs[-1][1].append(across)
                        else:
                            runs.append((run, [across], row))
                    lines = []
                    for run, across, row in runs:
                        if run:
                            lines.append(
                                f"{run[0]} {run[1]} → {run[2]} at {run[4]} "
                                + ", ".join(across)
                                + (f"; Z{run[3]}" if not depth_line else "")
                            )
                        else:
                            lines.append(
                                f"(X{row[1]}, Y{row[2]}) → (X{row[3]}, Y{row[4]})"
                                + (f"; Z{row[5]}" if not depth_line else "")
                            )
                    pieces.append(("Centre: " + "; ".join(lines) + ".", ""))
                    if entry.get("raster_lifts"):
                        pieces.append(
                            (
                                "Lift Z "
                                + " / ".join(dict.fromkeys(entry["raster_lifts"]))
                                + " between passes; return at lift height.",
                                "",
                            )
                        )
                    else:
                        pieces.append((description + "; return at lift height.", ""))
                elif headings == ["P", "angle °", "X", "Y", "Z", "handwheel axis"] and rows:
                    points, previous = [], None
                    for row in rows:
                        xy = row[2:4]
                        changed = [
                            axis + value
                            for index, (axis, value) in enumerate(zip("XY", xy, strict=True))
                            if previous is None or previous[index] != value
                        ]
                        points.append("/".join(changed) or "same point")
                        previous = xy
                    pieces.append(("Centre: " + " → ".join(points) + ".", ""))
                    if any(row[5] for row in rows):
                        pieces.append(
                            ("Handwheel axes: " + " → ".join(row[5] or "?" for row in rows), "")
                        )
                else:
                    pieces.append((description, ""))
                    if rows:
                        pieces.append(("", _table(headings, rows, css="coords")))
                if after:
                    pieces.append((after, ""))
            paths[op_id] = (
                (" ".join(text for text, _ in pieces), "")
                if all(not html for _, html in pieces)
                else (
                    "",
                    '<div class="route-path">'
                    + "".join(_p(text) if text else html for text, html in pieces)
                    + "</div>",
                )
            )
        return paths

    def contours(self, setup, tools, stops=None):
        """One block per contour op; both sides of a symmetric profile print explicitly."""
        numbers = self.records.get(("coordinates", setup["id"]), {})
        o = self.operative if self.detail == "pedantic" else self.readout
        waypoints = self.waypoints(setup)
        operations = {str(op["op"]): op for op in setup.get("ops", [])}
        blocks = {}
        stages = {"rough": 0, "finish": 1}
        numbers_by_pair = tool_numbers(self.bundle, setup)

        def block(op):
            return blocks.setdefault(
                str(op), {"parts": [], "z": set(), "stops": [], "measurements": []}
            )

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
                labels.append(self.waypoint(waypoints, arc.get("op"), points[-1], key))
            centre = arc.get("centre_setup_xy") or ["unknown", "unknown"]
            description = (
                f"Cutter-centre arc R{o(arc.get('cutter_centre_radius_mm'))} "
                f"about X {o(centre[0])}, Y {o(centre[1])}{self.frame_tag(setup)}"
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
                    "one handwheel axis per row; this " + _leftover(arc)
                )
            elif method == "chain_drill":
                headings = ["hole #", "P", "X", "Y"]
                rows = [
                    [str(index), label, o(xy[0]), o(xy[1])]
                    for index, (label, xy) in enumerate(zip(labels, points, strict=True), 1)
                ]
                if len(rows) == 1:
                    description = (
                        f"Single retained hole: drill Ø{_number(arc.get('drill_dia_mm'))} mm; "
                        "hole outside " + self.arc_line(setup, arc.get("op"))
                    )
                    after = "Drilling " + _leftover(arc) + "."
                else:
                    description = (
                        f"Chain drill: drill Ø{_number(arc.get('drill_dia_mm'))} mm, "
                        f"pitch {_number(arc.get('pitch_mm'))} mm; every hole outside "
                        + self.arc_line(setup, arc.get("op"))
                    )
                    after = (
                        f"After drilling, {_text(arc.get('break_out'))}; this "
                        + _leftover(arc)
                        + "."
                    )
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
            elif method == "guided_sweep":
                from prechips.sheet_sweep import established
                from prechips.sheet_sweep import steps as sweep_steps

                roughs = [
                    t
                    for t in numbers.get("arc_table", [])
                    if t.get("op") == arc.get("op") and t.get("stage") == "rough"
                ]
                rough = bool(roughs)
                finishes = [
                    t
                    for t in numbers.get("arc_table", [])
                    if t.get("op") == arc.get("op") and t.get("stage") == "finish"
                ]
                ends = (labels[0], labels[-1]) if labels else ("", "")
                feed = self.records.get(("speeds_feeds", subject), {}).get("feed_mm_min")
                # An op stepping down in axial levels sweeps once per level the heading
                # lists; an unknown level list stops the recipe.
                swept = operations.get(str(arc.get("op")))
                z_levels = self.z_levels(setup, swept) if swept else None
                depths = z_levels.get("levels") if z_levels else None
                if isinstance(depths, list) and len(depths) <= 1:
                    depths = None
                # A rough leaves the spindle running only for a finish that prints runnable
                # after it; a withheld finish leaves the rough the op's last sweep.
                finish_follows = (
                    arc.get("stage") == "rough"
                    and bool(finishes)
                    and all(established(t, depths) for t in finishes)
                )
                # A finish runs on from its rough's touch-off and stops: when the op leaves
                # stock for a rough sweep that is not printed runnable (rejected, or stopped),
                # the finish would return to a touch never made or take the whole leave.
                leave = (swept or {}).get("rough_allowance_mm")
                # An authored leave that is not a known amount is unresolved, never absent:
                # the finish would cut through stock nobody measured.
                wants_rough = leave is not None and not (_known(leave) and leave <= 0)
                rough_ready = rough and all(established(t, depths) for t in roughs)
                if arc.get("stage") == "finish" and wants_rough and not rough_ready:
                    description = [
                        "STOP: guided sweep not established (its rough sweep is not "
                        "established) — do not run."
                    ]
                else:
                    description = sweep_steps(
                        arc,
                        o,
                        *ends,
                        after_rough=rough,
                        feed=feed,
                        final=not finish_follows,
                        levels=depths,
                    )
                # A finish after the op's rough sweep continues the rough's numbered steps.
                previous = entry.get("sweep_steps")
                if rough and arc.get("stage") == "finish" and previous is not None:
                    previous.extend(description)
                    continue
                entry["sweep_steps"] = description
                entry["parts"].append((order(entry, arc), description, [], [], None))
                continue
            else:
                entry["stops"].append("manual arc method not established")
                continue
            description += self.cut_order(arc) + self.clip(
                arc,
                [row.get("clipped_at") for row in samples],
                rows,
                label_column=1 if method == "chain_drill" else 0,
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
                        self.waypoint(waypoints, line.get("op"), dro, key),
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
            after = None
            if line.get("method") == "chain_drill":
                if len(rows) == 1:
                    description = (
                        f"Single retained hole on the {side} join: "
                        f"drill Ø{_number(line.get('drill_dia_mm'))} mm; hole outside "
                        + self.arc_line(setup, line.get("op"))
                    )
                    after = "Drilling " + _leftover(line) + "."
                else:
                    description = (
                        f"Chain drill straight joins on the {side} side: "
                        f"drill Ø{_number(line.get('drill_dia_mm'))} mm, "
                        f"pitch {_number(line.get('pitch_mm'))} mm; every hole outside "
                        + self.arc_line(setup, line.get("op"))
                    )
                    after = (
                        f"After drilling, {_text(line.get('break_out'))}; this "
                        + _leftover(line)
                        + "."
                    )
                description += self.cut_order(line) + self.clip(
                    line, line.get("clipped_at") or [], rows
                )
                rows = [[str(index), *row[:-1]] for index, row in enumerate(rows, 1)]
                headings = ["hole #", "P", "", "X", "Y", "Z"]
            elif axes:
                description += "; one handwheel axis per row"
                if _known(line.get("stair_cusp_mm")):
                    # A bound: rounded up onto the DRO grid, never printed finer than it.
                    step = dro_grid(self.bundle, setup)[0]
                    cusp = math.ceil(round(line["stair_cusp_mm"] / step, 6)) * step
                    description += f", the stair leaves ≤ {o(cusp)}"
            if line.get("method") != "chain_drill":
                headings = ["P", "", "X", "Y", "Z", "handwheel axis"]
            entry["parts"].append((order(entry, line), description, headings, rows, after))
        table_ops = {
            str(table.get("op"))
            for kind in ("arc_table", "line_table")
            for table in numbers.get(kind, []) or []
        }
        raster_stages = {}
        for profile in numbers.get("profiles", []):
            if isinstance(profile, dict) and isinstance(profile.get("raster"), dict):
                raster_stages.setdefault(str(profile.get("op")), set()).add(profile.get("stage"))
        for profile in numbers.get("profiles", []):
            op = str(profile.get("op"))
            if op in table_ops:
                continue
            points = profile.get("cutter_centre")
            entry = block(op)
            if not isinstance(points, list) or not points:
                entry.setdefault("unresolved", True)
                entry["measurements"].extend(profile.get("measurements", []))
                for reason in ("clip_reason", "stair_reason", "allowance_reason", "raster_reason"):
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
                entry.setdefault("raster_profiles", []).append(profile)
                entry.setdefault("raster_lifts", []).append(o(raster.get("lift_z")))
                entry["raster_step"] = raster.get("step_mm")
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
        # Ops whose block is a guided sweep's recipe: no cutter-centre table (#255).
        self.sweep_ops = {
            str(arc.get("op"))
            for arc in numbers.get("arc_table", []) or []
            if arc.get("method") == "guided_sweep"
        }
        if not blocks:
            return ""
        if self.detail != "pedantic":
            self._route_contours[setup["id"]] = self.route_contour_parts(
                setup, tools, blocks, stops
            )
            return ""
        html = []
        for op_id in sorted(blocks, key=lambda k: (not k.isdigit(), int(k) if k.isdigit() else 0)):
            entry = blocks[op_id]
            op = operations.get(op_id, {})
            # Each block names its setup: a contour sheet that runs onto a second page
            # still says which setup it belongs to.
            title = f"{_text(setup['id'])} op {op_id} — {self.feature_name(op.get('feature'))}"
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
                debts = entry["measurements"]
                number = numbers_by_pair.get(self.tool_pair(op.get("tool"), op.get("holder")))
                reasons = (
                    [
                        self.measurement_stop(op, number, debt)
                        for debt in {debt["id"]: debt for debt in debts}.values()
                    ]
                    if debts
                    else list(dict.fromkeys(entry["stops"]))
                )
                text = "contour points not computed" + "".join(f" — {reason}" for reason in reasons)
                content += _p(f"STOP: {text} — do not run.", "stop")
                if stops is not None:
                    stops.setdefault(text, []).append(op_id)
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
                else "guided sweep: X / Y locked, the fixture moves the work"
                if set(blocks) <= self.sweep_ops
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
        if not route_identities_known(self.plan, setup.get("id")):
            return "? unknown stock route; setup identity unresolved"
        source = setup.get("stock_in")
        sources = source if isinstance(source, list) else [source]
        graph = MaterialGraph(self.plan)
        supplies = {ref: graph.roots(ref) for ref in sources}
        if self.detail != "pedantic" and len(sources) == 1:
            ref = sources[0]
            atoms = graph.nodes.get(ref, ())
            producer = producer_setup(self.plan, ref)
            if (
                len(atoms) == 1
                and atoms[0].path
                and supplies[ref] == {"stock"}
                and producer is not None
            ):
                partition = atoms[0].path[-1]
                name = f"retained {_text(partition.output)} from Setup {producer}"
                if partition.split != producer:
                    name += f" (parted in Setup {partition.split})"
                return name
        if any(atom.path for ref in sources for atom in graph.nodes.get(ref, ())):
            names = []
            for ref in sources:
                atoms = graph.nodes.get(ref, ())
                pieces = sorted({atom.path[-1].output for atom in atoms if atom.path})
                splits = sorted({atom.path[-1].split for atom in atoms if atom.path})
                if pieces:
                    name = "the " + " + ".join(map(_text, pieces))
                    name += " retained piece" if len(pieces) == 1 else " retained-piece assembly"
                    producer = producer_setup(self.plan, ref)
                    if producer not in splits:
                        name += f" from Setup {producer}"
                    name += " (parted in Setup " + " + ".join(splits) + ")"
                    names.append(name)
                elif ref == "stock" or isinstance(ref, str) and ref.startswith("stock."):
                    names.append("the " + _supply_name(ref))
                else:
                    names.append(f"part as it arrives from Setup {ref}")
            roots = sorted({root for values in supplies.values() for root in values})
            original = " + ".join(
                _STOCK_FORMS.get(self.plan.get("stock", {}).get("form"), "stock blank")
                if root == "stock"
                else _supply_name(root)
                for root in roots
            )
            if len(names) > 1:
                shared = len(roots) == 1 and all(
                    supplies[ref] == supplies[sources[0]] for ref in sources
                )
                origin = (
                    f"both from the same original {original}"
                    if shared and len(names) == 2
                    else f"from the original {original}"
                )
                return " and ".join(names) + f", joined here; {origin}"
            return names[0] + f", from the original {original}"
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
        """Validate the complete canonical image before selecting whole panel groups."""
        sid = setup["id"]
        detail = getattr(self, "detail", "pedantic")
        requested = setup.get("picture_panels")
        render = self.report.get("renders", {}).get(sid)
        if not render:
            if detail != "pro" and (requested is None or requested == "unknown" or requested):
                return _p(
                    f"Setup {sid}: NO PICTURE — requested holding geometry is unavailable.",
                    "picture-notice",
                )
            return ""
        scene = _mapping(render.get("scene"))
        width, height = scene.get("width_px"), scene.get("height_px")
        panels = scene.get("print_panels")
        if (
            not all(type(value) is int and value > 0 for value in (width, height))
            or not isinstance(panels, list)
            or not panels
        ):
            raise ValueError(f"Setup {sid} has no complete printable image geometry")
        next_top, ids, groups, occurrences, setup_continuation = 0, set(), set(), {}, True
        for ordinal, raw in enumerate(panels):
            panel = _mapping(raw)
            top, extent = panel.get("top_px"), panel.get("height_px")
            role, label = panel.get("role"), panel.get("label")
            if (
                type(top) is not int
                or top != next_top
                or type(extent) is not int
                or extent <= 0
                or top + extent > height
                or not isinstance(role, str)
                or not role.strip()
                or not isinstance(label, str)
                or not label.strip()
            ):
                raise ValueError(f"Setup {sid} printable panels omit or repeat image content")
            next_top += extent
            if ordinal == 0:
                expected_id = "setup"
                if role != "setup":
                    raise ValueError(f"Setup {sid} first printable panel is not the setup view")
            else:
                occurrences[role] = occurrences.get(role, 0) + 1
                expected_id = f"{role}:{occurrences[role]}"
                setup_continuation = setup_continuation and role == "setup"
            expected_group = "setup" if setup_continuation else expected_id
            annotations = panel.get("annotations")
            if (
                panel.get("id") != expected_id
                or expected_id in ids
                or panel.get("selection_group") != expected_group
                or not isinstance(annotations, list)
                or any(not isinstance(value, str) or not value.strip() for value in annotations)
                or len(annotations) != len(set(annotations))
            ):
                raise ValueError(
                    f"Setup {sid} has invalid printable panel identity {panel.get('id')!r}"
                )
            ids.add(expected_id)
            groups.add(expected_group)
        if next_top != height:
            raise ValueError(f"Setup {sid} printable panels omit image content")
        if requested not in (None, "unknown"):
            if (
                not isinstance(requested, list)
                or any(not isinstance(value, str) or not value.strip() for value in requested)
                or len(requested) != len(set(requested))
            ):
                raise ValueError(f"Setup {sid} has invalid picture_panels")
            for selected in requested:
                if selected not in groups:
                    raise ValueError(f"Setup {sid} has no selectable picture panel {selected!r}")
        notice = (
            _p(f"Setup {sid}: picture panel selection is unknown.", "picture-notice")
            if requested == "unknown"
            else ""
        )
        if detail == "pro":
            return notice
        if detail == "hobby" and requested == "unknown":
            return notice
        selected = groups if detail == "pedantic" or requested is None else set(requested)
        chosen = [panel for panel in panels if panel["selection_group"] in selected]
        if not chosen:
            return ""
        if isinstance(requested, list):
            self._route_picture_setups.add(sid)
        path = escape(render["path"], quote=True)
        context = f"Setup {sid}"
        revision = self.drawing_revision()
        if detail == "pedantic":
            context = f"{_text(self.plan.get('part'))} · {context}"
            if revision:
                context += f" · rev {revision}"
        result = [notice] if notice else []
        stock_caption = "Stock: " + self.arrival(setup)
        fixture = _mapping(setup.get("hold")).get("fixture")
        if fixture not in (None, "", "none", "not_applicable"):
            stock_caption += "; fixture: " + self.reference(fixture, "workholding")
        for panel in chosen:
            top, extent = panel["top_px"], panel["height_px"]
            label = f"{context} — {panel['label']}"
            result.append(
                f'<figure class="fixture-render" data-panel-id="{escape(panel["id"])}" '
                f'data-selection-group="{escape(panel["selection_group"])}" '
                f'data-panel-role="{escape(panel["role"])}" data-panel-top="{top}" '
                f'data-panel-height="{extent}" data-page-context="Setup {escape(_text(sid))}">'
                + (f"<figcaption>{escape(label)}</figcaption>" if detail == "pedantic" else "")
                + (_p(stock_caption, "stock-fixture-caption") if panel is chosen[0] else "")
                + f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 {top} {width} {extent}" '
                f'width="{width}" height="{extent}" role="img" aria-label="{escape(label)}">'
                f"<title>{escape(label)}</title>"
                f'<image href="{path}" x="0" y="0" width="{width}" height="{height}" '
                'preserveAspectRatio="none"></image></svg></figure>'
            )
        unheld = hand_fed(self.bundle, setup)[0] == "admitted" or unfixtured_handling(
            manual_bench(self.bundle, setup), _mapping(setup.get("hold"))
        )
        debts = [
            str(debt)
            for debt in scene.get("debts") or []
            if not (unheld and str(debt).startswith("fixture not drawn:"))
        ]
        debts.extend(str(debt) for debt in scene.get("render_debts") or [])
        if render.get("fixture") != "modeled" and not debts and not unheld:
            debts.append("Part of the holding is not modelled.")
        result.extend(
            _p(
                "NOT SHOWN: " + self.bench(debt.removeprefix("NOT SHOWN:").lstrip()),
                "render-debt",
            )
            for debt in debts
        )
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
            if rule == "inspection" and isinstance(numbers.get("identity"), dict):
                if numbers.get("setup_id") is not None:
                    if numbers["setup_id"] == sid:
                        result.append(finding)
                    continue
                identity = numbers["identity"]
                feature, member = identity.get("feature_owner"), identity.get("workpiece")
                if member is not None:
                    if any(
                        (
                            feature in op_features(op)
                            or feature is None
                            and op.get("do") == "inspect"
                        )
                        and (
                            member in (operation_members(self.bundle, setup, op) or ())
                            or isinstance(op.get("inspect_workpieces"), list)
                            and member in op["inspect_workpieces"]
                        )
                        for op in setup["ops"]
                    ):
                        result.append(finding)
                elif feature in features:
                    result.append(finding)
                continue
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
        """Declared mm stock sizes in explicit job units, with supply notes unchanged."""
        stock = _mapping(stock)
        decimals = dro_grid(self.bundle, self.receiving_setup(ref) or {})[1]
        unit = readout_units(self.bundle) if self.detail != "pedantic" else "mm"
        unit = unit if unit in ("mm", "in") else "mm"

        def o(value):
            if self.detail != "pedantic":
                return _number(value / 25.4 if unit == "in" else value)
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
            dims = (dims + " × " if dims else "") + f"{o(stock['length_mm'])} {unit} long"
        elif stock.get("length_mm") == "unknown":
            dims += f" {unit} × ? length not set" if dims else "? length not set"
        elif dims:
            dims += " " + unit
        label = _STOCK_FORMS.get(form, _text(form) if form else "stock")
        if profiled(stock):
            # A bought profiled blank is sized by its cut file, not by bar dimensions: the
            # receiving check is the kernel's box of that blank's own solid. The file
            # itself is bound in the report, never printed for the bench; an unknown blank
            # or an uncited tolerance prints as debt, never as a vendor fact.
            blank = _mapping(stock.get("blank"))
            tolerance, step = cited_tolerance(blank), blank.get("step")
            box = _mapping(_mapping(self.bundle.kernel).get("blank_bbox_mm")).get(ref)
            dims = (
                " × ".join(o(box[i + 3] - box[i]) for i in range(3)) + f" {unit} overall, "
                if isinstance(box, list) and len(box) == 6
                else ""
            )
            dims += (
                "bought already cut to outline"
                if isinstance(step, str) and step != "unknown"
                else "bought already cut to outline, ? cut file not set"
            )
            dims += (
                f", vendor cut tolerance ±{tolerance:g} mm"
                if _known(tolerance)
                else ", ? vendor cut tolerance not set or not cited"
            )
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
                in {
                    "form",
                    "material",
                    "dia_mm",
                    "section_mm",
                    "length_mm",
                    "drawing_material",
                    "blank",
                }
                or value in ("unknown", "not_applicable")
            ):
                continue
            if key in {"on_hand", "prerequisite"}:
                continue  # Printed with the job-level prerequisites.
            if key == "prepared":
                continue  # Printed as CHECK THE BLANK before the setup that receives it.
            if key == "note":
                extras.append(self.bench(value).rstrip(".") + ".")
                continue
            name = _text(key)
            dimensional = name.endswith(" mm")
            suffix = " " + unit if dimensional else ""
            name = name.removesuffix(" mm")
            shown = (
                (o(value) if dimensional else _number(value)) + suffix
                if _known(value)
                else self.bench(value)
            )
            extras.append(f"{name[:1].upper() + name[1:]}: {shown}.")
        return " ".join([line, *extras])

    def flip(self, setup):
        """The part turns over between setups when this setup's Z points against the arriving
        setup's Z in the model; say so first, with which face goes up and which X end stays."""
        source = producer_setup(self.plan, setup.get("stock_in"))
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
        here = setup_frame(self.bundle, setup)
        there = reference_frame(
            self.plan, setup.get("stock_in"), setup_frame(self.bundle, previous)
        )
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
        if debt:
            self.record_decision(
                setup,
                source=debt.source,
                status=debt.status,
                scope=debt.scope,
                text=str(debt),
                kind=debt.kind,
            )
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
            return "Speeds / feeds: no cited source — resolve speed/feed STOPs before powered cuts."
        return (
            "Starting speeds/feeds."
            if self.detail != "pedantic"
            else ("Speeds and feeds are starting points, not limits.")
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
        if isinstance(finish, str) and finish != "unknown" and self.detail == "pedantic":
            line += f" Finish: {finish}."
        return line

    def requirements(self):
        rows, joint_prep, same = [], [], {}
        selected = (
            {
                (target["identity"]["feature_owner"], target["identity"]["requirement"])
                for setup in self.plan.get("setups", [])
                for op in setup.get("ops", [])
                for target in op_check_targets(self.bundle, setup, op)
            }
            if self.detail != "pedantic"
            else set()
        )
        for feature, definition in self.features.items():
            requirements = dict.fromkeys(tolerance_requirements(definition))
            values = [
                "? requirement not identified"
                if requirement == "unknown"
                else _REQUIREMENT_NAMES.get(requirement, _text(requirement))
                + " "
                + self.inspection_band(feature, requirement)[0]
                for requirement in requirements
                if self.detail == "pedantic" or (feature, requirement) not in selected
            ]
            if _mapping(definition.get("preparation")):
                # Plan stock preparation (a faced end, a centre): the route makes it, the
                # drawing never asks for it, so it is no acceptance row.
                continue
            if not values:
                continue
            if _mapping(definition.get("joint")):
                # Plan-authored preparation, never drawing acceptance.
                joint_prep.append(
                    (
                        self.feature_label(feature, marked=False),
                        "; ".join(values),
                    )
                )
                continue
            limits = "; ".join(values)
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
        nominal = ""
        if _known(thickness) and not limited:
            value = self.readout(thickness) if self.detail != "pedantic" else self.value(thickness)
            unit = readout_units(self.bundle) if self.detail != "pedantic" else self.units
            thickness_text = f"finished thickness {value} {_text(unit)}"
            if self.detail != "pedantic":
                nominal = _p(thickness_text[:1].upper() + thickness_text[1:])
            else:
                rows.append(("part", thickness_text))
        if self.detail != "pedantic":
            html = nominal + "".join(
                _p(f"Inspection requirement not assigned — {feature}: {limits}")
                for feature, limits in rows
            )
            html += _p("All edges: " + self.edge_break())
        else:
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
                    where = f"{_text(setup['id'])} op {op['op']}"
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
        cite = setup.get("deburr_cite")
        cites = cite if isinstance(cite, list) else [cite]
        reasons = []
        for citation in cites:
            if not isinstance(citation, str):
                continue
            # A citation prefix is provenance; its following human reason still matters.
            reason = re.sub(
                r"^(?:https?://\S+|(?:[A-Za-z]:[\\/])?[\w./\\-]+"
                r"\.(?:md|toml|json|ya?ml|txt|pdf|py)(?:#[^\s:]+)?"
                r"(?::\d+(?:-\d+)?(?:,\s*\d+(?:-\d+)?)*)?)(?::\s*|\s+|$)",
                "",
                citation.strip(),
                flags=re.IGNORECASE,
            ).strip()
            if reason and reason != "unknown":
                reasons.append(self.bench(reason).rstrip("."))
        text = f"Break edges {self.operative(deburr)} mm max in this setup"
        text += f", not the drawing's {self.cap(min(drawing))}" if drawing else ""
        return _p(text + (": " + "; ".join(reasons) if reasons else "") + ".")

    def drawing_revision(self):
        revision = self.plan.get("drawing", {}).get("revision", "unknown")
        return revision if isinstance(revision, str) and revision != "unknown" else None

    def dro_resolution(self, setups):
        """Each routed machine's DRO step, once per machine however setups spell it: the
        grid every printed DRO target is on."""
        kind = readout_kind(self.bundle)
        if kind == "handwheel":
            facts = handwheel_readout(self.bundle)
            graduation = facts["graduation"]
            step = (
                f"{_number(graduation)} {_text(facts['units'])} per division"
                if _known(graduation)
                else "graduation unknown"
            )
            mode = facts["x_scale"]
            if mode != "unknown":
                step += f" (X {mode} scale)"
            return (
                f"Mechanical readout: {step}; calibration and physical dial zero are "
                "unverified. Nominal targets are not physical dial settings."
            )
        if kind != "digital":
            return "STOP: readout kind is unknown; no instrument or physical settings are inferred."
        grids = {}
        not_used = {"step": "not used", "decimals": "not used"}
        used = {
            identity(self.bundle, setup.get("machine"), "machines")
            for setup in setups
            if _mapping(self.records.get(("coordinates", setup["id"]))).get("dro_grid")
            not in (None, not_used)
        }
        has_targets = False
        for setup in setups:
            reference = setup.get("machine")
            key = identity(self.bundle, reference, "machines")
            if key in grids or manual_bench(self.bundle, setup):
                continue
            coordinates = _mapping(self.records.get(("coordinates", setup["id"])))
            no_targets = coordinates.get("dro_grid") == not_used and key not in used
            if saw_setup(self.bundle, setup) and not coordinates:
                continue
            machine = self.machine(setup)
            fact = length_fact(machine, "resolution")
            if no_targets and (not _known(fact["value"]) or fact["value"] <= 0):
                grids[key] = f"{self.reference(reference, 'machines')} — no coordinate targets"
                continue
            step, decimals = dro_grid(self.bundle, setup)
            units = readout_units(self.bundle)
            shown = f"{step:.{decimals}f}" if units == self.units else self.readout(step)
            grid = f"{shown} {_text(units)}"
            if self.detail == "pedantic":
                grid = self.dro_controller_name() + " " + grid
            else:
                grid = self.reference(reference, "machines") + " " + grid
            if not _known(fact["value"]) or fact["value"] <= 0:
                grid += " (resolution absent/unknown: provisional default grid)"
            elif dro_grid_debt(self.bundle, setup):
                name = self.dro_controller_name()
                refs = [
                    "?" + marker
                    for marker, entry in self.measurement_registry().values()
                    if (entry["category"], entry["identity"]) == key
                    and entry["field"] == ["resolution"]
                ]
                grid += f" (grid not verified; {name} installed readout step"
                grid += " " + (refs[0] if refs else "— not consumed by a stopped decision") + ")"
            if machine.get("kind") == "lathe":
                radius = _mapping(self.plan.get("dro")).get("radius_mode")
                grid += (
                    " (X reads radius)"
                    if radius is True
                    else " (X reads diameter)"
                    if radius is False
                    else " (X: ? radius or diameter)"
                )
            if no_targets:
                grid += " — no coordinate targets"
            grids[key] = grid
            has_targets |= not no_targets
        if not grids:
            return None
        suffix = (
            ". DRO targets print on this grid."
            if self.detail == "pedantic" and has_targets
            else "."
        )
        label = (
            "Example DRO resolution: "
            if self.detail != "pedantic" and self.plan.get("purpose") == "demonstration"
            else "DRO resolution: "
        )
        return label + "; ".join(grids.values()) + suffix

    @staticmethod
    def setup_groups(setups):
        groups = []
        for setup in setups:
            label = setup.get("presentation_group")
            if label and groups and groups[-1][0].get("presentation_group") == label:
                groups[-1].append(setup)
            else:
                groups.append([setup])
        return groups

    def route_groups(self, setups):
        """Compact adjacent repeated work; authored groups remain the authority."""
        if self.detail == "pedantic":
            return self.setup_groups(setups)

        def key(setup):
            if setup.get("presentation_group"):
                return None
            operations = setup.get("ops", [])
            cutting = [op for op in operations if op.get("do") not in MANUAL]
            if cutting and all(op.get("do") in FACING for op in cutting):
                return (
                    "facing",
                    self.mount_key(setup),
                    tuple(
                        (op.get("do"), identity(self.bundle, op.get("tool"), "tools"))
                        for op in operations
                    ),
                )
            mounted = self.mounted_datum_groups.get(setup["id"])
            if mounted:
                return ("mounted-saw", mounted[0][0]["id"])
            return None

        groups = []
        for group in self.setup_groups(setups):
            shared = key(group[0]) if len(group) == 1 else None
            if (
                shared is not None
                and groups
                and key(groups[-1][0]) == shared
                and not groups[-1][0].get("presentation_group")
            ):
                groups[-1].extend(group)
            else:
                groups.append(list(group))
        return groups

    def finding_fact(self, finding):
        rule, subject = _field(finding, "rule"), _field(finding, "subject", "")
        message, text = _field(finding, "message", "?"), None
        if self.detail != "pedantic":
            text, message = self.compact_finding(finding)
        return _Decision(
            _field(finding, "rule", "finding"),
            _status(finding),
            subject,
            finding_decision(finding, self.bundle),
            text if text is not None else self.plain_error(rule, message, subject),
        )

    def compact_finding(self, finding):
        """``(text, message)``: a compact level's operator wording for one finding. ``text``
        is final when the finding restates a producer box (it groups with that box);
        otherwise ``message`` still goes through :meth:`plain_error`. Status, scope and
        decision never change, and report.json keeps the full sentence."""
        rule, message = _field(finding, "rule"), str(_field(finding, "message", "?"))
        numbers = _mapping(_field(finding, "numbers"))
        if (
            rule == "speeds_feeds"
            and numbers.get("rpm_basis") == "authored"
            and numbers.get("rpm_status") != "pass"
            and message == f"Authored RPM request: {numbers.get('rpm_reason')}"
        ):
            return _authored_rpm_stop(numbers), message
        if rule == "zero_check" and _status(finding) != "pass":
            message = self.compact_zero_message(message)
        if rule == "coordinates" and _status(finding) != "pass":
            message = self.compact_coordinates(message, numbers)
        message = self.compact_refused(message, numbers, _field(finding, "subject", ""))
        return None, self.compact_authoring(message, numbers)

    @staticmethod
    def compact_coordinates(message, numbers):
        """Drop the pass-case basis sentence and print the pass-plan unknowns each op row
        already stops on as one scoped list; any other pass-plan item prints as it is."""
        lead = (
            "Feature targets use the declared model-to-setup basis; cutter tables use explicit "
            "nominal geometry and authored allowance."
        )
        if message.startswith(lead + " "):
            message = message[len(lead) + 1 :]
        known = {}
        for entry in numbers.get("operations") or ():
            levels = _mapping(_mapping(entry).get("z_levels"))
            if levels.get("levels") == UNKNOWN and levels.get("reason"):
                op = _mapping(entry).get("op")
                known[f"op {op} axial levels: {levels['reason']}"] = (op, "depth levels")
        for profile in map(_mapping, numbers.get("profiles") or ()):
            for stage in ("rough", "finish") if profile.get("lift_reason") else ():
                text = f"op {profile.get('op')} {stage}: {profile['lift_reason']}"
                known[text] = (profile.get("op"), "lift Z")
        for path in map(_mapping, numbers.get("level_paths") or ()):
            op = path.get("op")
            known[
                f"op {op} returns to its entry but its raise Z is unknown: it needs "
                "approach_mm above a known top"
            ] = (op, "raise Z")
            if path.get("plunge_reason"):
                known[
                    f"op {op} plunges into the stock but its plunge feed is unknown: "
                    f"{path['plunge_reason']}"
                ] = (op, "plunge feed")
        marker = "Pass plan unknown: "
        start = message.find(marker)
        if start < 0 or start > 0 and message[start - 1] != " ":
            return message
        start += len(marker)
        end = message.find(". ", start)
        end = end if end >= 0 else len(message.rstrip(".")) if message.endswith(".") else -1
        if end < 0:
            return message
        needs, kept = {}, []
        for item in message[start:end].split("; "):
            if item in known:
                op, need = known[item]
                needs.setdefault(op, [])
                if need not in needs[op]:
                    needs[op].append(need)
            else:
                kept.append(item)
        if not needs:
            return message
        scoped = {}
        for op, items in needs.items():
            scoped.setdefault(tuple(items), []).append(op)
        clauses = [f"{_ops_label(ops)}: {', '.join(items)}" for items, ops in scoped.items()]
        return message[:start] + "; ".join([*clauses, *kept]) + message[end:]

    def compact_refused(self, message, numbers, subject):
        """Drop the refused-input diagnosis only when this setup prints every listed
        measurement separately; an upstream-stock hold cannot replace a tooling debt."""
        entries = [entry for entry in numbers.get("measurements") or () if isinstance(entry, dict)]
        if not entries or not all("id" in entry for entry in entries):
            return message
        diagnosis = "; ".join(
            f"{entry['id']} ({entry.get('status', UNKNOWN)}): {entry['reason'].rstrip('.')}"
            if entry.get("reason")
            else f"{entry['id']} ({entry.get('status', UNKNOWN)})"
            for entry in entries
        )
        suffix = f" Refused kernel facts: {diagnosis}."
        if not message.endswith(suffix):
            return message
        sid = str(subject).partition(":")[0]
        printed = self.setup_measurement_ids.get(sid, set())
        covered = all(
            quantities and all(quantity["id"] in printed for quantity in quantities)
            for quantities in map(self.measurement_quantities, entries)
        )
        if covered:
            return message[: -len(suffix)]
        return message

    @staticmethod
    def compact_zero_message(message):
        """Drop the routine touch procedure and the recursive face provenance; every other
        sentence (an independent failure) stays verbatim. :meth:`fold_zero_settings` adds
        the unknown settings the datum block itself found."""
        text = message
        for routine in _ZERO_ROUTINE:
            text = text.replace(routine, "", 1)
        face = ""
        for marker, summary in _ZERO_FACE_UNKNOWN:
            start = text.find(marker)
            if start < 0:
                continue
            depth, end = 0, None
            for index in range(start + len(marker) - 1, len(text)):
                depth += {"(": 1, ")": -1}.get(text[index], 0)
                if depth == 0:
                    end = index
                    break
            if end is not None and text.startswith(_ZERO_FACE_TAIL, end):
                text = text[:start] + text[end + len(_ZERO_FACE_TAIL) :]
                face = summary + "."
        if face:
            text = text.replace(_ZERO_UNVERIFIED, "", 1)
        return " ".join(filter(None, (text.strip(), face))) or message

    @staticmethod
    def compact_authoring(message, numbers):
        """Replace each Z/XY geometry authoring debt the finding lists with its operation
        scope and the values it still needs; the field paths and authoring steps stay in
        report.json. A debt holding any phrase this does not recognise prints whole."""
        scoped = {}
        for entry in numbers.get("measurements") or ():
            entry = _mapping(entry)
            instruction = entry.get("instruction")
            debt = re.fullmatch(
                r"(plan\.setups\.[^.]+\.ops\.([^.]+))\.(?:z|xy)_geometry", str(entry.get("id"))
            )
            if not (
                isinstance(instruction, str)
                and instruction.startswith("author: ")
                and debt
                and instruction in message
            ):
                continue
            rest, needs = instruction.removeprefix("author: "), []
            phrases = _authoring_phrases(debt[1])
            while rest:
                match = next(((p, w) for p, w in phrases if rest.startswith(p)), None)
                if match is None and rest.startswith("; "):
                    rest = rest[2:]
                    continue
                if match is None:
                    break
                needs.append(match[1])
                rest = rest[len(match[0]) :]
            if rest or not needs:
                continue
            message = message.replace(instruction, "\0")
            scoped.setdefault(tuple(dict.fromkeys(needs)), []).append(debt[2])
        if not scoped:
            return message
        message = re.sub(r";\s*\0", "", re.sub(r"\0;\s*", "", message)).replace("\0", "")
        message = re.sub(r"\.\s*\.$", ".", message.strip()).rstrip(". ")
        clauses = [
            f"{_ops_label(ops)}: {', '.join(needs)} not established"
            for needs, ops in scoped.items()
        ]
        return message + ". " + "; ".join(clauses) + "."

    @staticmethod
    def fold_zero_settings(groups, sid):
        """One datum hold per setup: unknown Axis Set facts the datum block found join the
        setup's adverse zero_check notice as a list, retaining every decision as evidence.
        Without that notice (or with a weaker one) they keep their own boxes."""
        lead = next(
            (
                group
                for group in groups
                if group[0].source == "zero_check"
                and group[0].scope == sid
                and group[0].kind != "none"
                and not group[0].notice_group
            ),
            None,
        )
        folded = [
            group
            for group in groups
            if lead is not None
            and group is not lead
            and all(
                fact.notice_group.startswith(_ZERO_SETTING + "|")
                and (fact.kind == lead[0].kind or lead[0].kind == "block")
                for fact in group
            )
        ]
        if not folded:
            return groups
        settings = {}
        for fact in (fact for group in folded for fact in group):
            _, setting, item = fact.notice_group.split("|", 2)
            settings.setdefault(setting, [])
            if item:
                settings[setting].append(item)
        listed = "; ".join(
            setting + (" for " + ", ".join(dict.fromkeys(items)) if items else "")
            for setting, items in settings.items()
        )
        text = lead[0].text.rstrip(".") + ". Unknown: " + listed + "."
        merged = [replace(lead[0], text=text), *lead[1:], *(f for g in folded for f in g)]
        return [
            merged if group is lead else group
            for group in groups
            if not any(group is other for other in folded)
        ]

    def settings_key(self):
        """One job key for operative settings; manual tools stay at their operation."""
        settings, coolants, projections = {}, {}, {}
        unit = readout_units(self.bundle)

        def millimetres(value):
            return _number(value / 25.4 if unit == "in" else value)

        for setup in self.plan.get("setups", []):
            coolant = setup.get("coolant")
            if coolant not in (None, "none", "not_applicable"):
                coolants.setdefault(coolant, []).append(setup["id"])
            for row, op in zip(
                self._rows_by_setup.get(setup["id"], []), setup.get("ops", []), strict=True
            ):
                reference = op.get("tool")
                if reference in (None, "unknown"):
                    continue
                item = _mapping(resolve(self.bundle, "tools", reference))
                if len(row) != 9 and not _known(_amount(item.get("lead_mm"))):
                    continue
                values = tuple(
                    str(value)
                    for cell in (row[4:6] if len(row) == 9 else ())
                    for value in (cell if isinstance(cell, (list, tuple)) else [cell])
                    if value not in ("", "—", None)
                    and not isinstance(value, _Box)
                    and not (isinstance(value, str) and value in _SPINDLE_TURNS)
                )
                evidence = self.records.get(("speeds_feeds", f"{setup['id']}:{op['op']}"), {})
                if _known(evidence.get("rpm")) and _known(evidence.get("feed_mm_rev")):
                    feed = millimetres(evidence["feed_mm_rev"]) + f" {unit}/rev"
                    if evidence.get("feed_direction") == "axial":
                        feed = "axial " + feed
                    if _known(evidence.get("feed_mm_min")):
                        feed += f" ({millimetres(evidence['feed_mm_min'])} {unit}/min)"
                    values = (_number(evidence["rpm"]), feed)
                elif (
                    "feed_mm_rev" not in evidence
                    and _known(evidence.get("rpm"))
                    and _known(evidence.get("feed_mm_min"))
                ):
                    values = (
                        _number(evidence["rpm"]),
                        millimetres(evidence["feed_mm_min"]),
                    )
                elif _known(evidence.get("blade_speed_sfm")) and _known(
                    evidence.get("feed_mm_min")
                ):
                    values = (
                        _number(evidence["blade_speed_sfm"]) + " sfm",
                        "descent " + millimetres(evidence["feed_mm_min"]) + f" {unit}/min",
                    )
                manual_unset = not values and op.get("do") in MANUAL
                facts = []
                if item.get("kind") == "slitting_saw" and _known(item.get("flutes")):
                    facts.append(f"{_number(item['flutes'])}T")
                if (
                    item.get("kind") == "endmill"
                    and type(flutes := item.get("flutes")) is int
                    and flutes > 0
                ):
                    facts.append(f"{flutes} flutes")
                for key, label in (
                    ("lead_mm", "chamfer/lead length" if item.get("kind") == "tap" else "lead"),
                    ("kerf_mm", "kerf"),
                    ("thickness_mm", "body"),
                ):
                    if _known(value := _amount(item.get(key))):
                        facts.append(f"{label} {millimetres(value)}")
                reach_status = self.finding_statuses.get(("reach", f"{setup['id']}:{op['op']}"))
                if (
                    _known(_amount(item.get("lead_mm")))
                    or reach_status in ("error", "unknown", "unsupported", "warn")
                ) and _known(length := _amount(item.get("flute_len_mm"))):
                    label = "threaded cutting length" if item.get("kind") == "tap" else "cutting"
                    facts.append(f"{label} {millimetres(length)}")
                if manual_unset and not facts:
                    continue
                holder = op.get("holder")
                pair_key = (reference, holder)
                if pair_key not in projections:
                    projections[pair_key] = tuple(
                        str(part)
                        for part in self.tool_detail(
                            reference,
                            holder,
                            length_format=lambda value: f"{_number(value)} mm",
                        )
                        if str(part).startswith("projection ")
                    )
                    if (
                        not projections[pair_key]
                        and holder not in (None, "unknown", "not_applicable")
                        and any(
                            isinstance(item.get(field), dict)
                            for field in ("projection_mm", "projection_in")
                        )
                    ):
                        projections[pair_key] = (
                            "projection ? (not recorded for the selected holder)",
                        )
                facts.extend(projections[pair_key])
                key = (
                    reference,
                    self.reference(holder, "holders")
                    if holder not in (None, "unknown", "not_applicable")
                    else "",
                    values,
                    tuple(facts),
                )
                settings.setdefault(key, []).append(f"{setup['id']}:{row[0]}")
        rows = []
        variants = {}
        for reference, _holder, _values, _facts in settings:
            variants[reference] = variants.get(reference, 0) + 1
        grouped = {}
        for (reference, holder, values, facts), owners in settings.items():
            description = self.route_tool_name(reference)
            label = self.route_tool_label(reference)
            kind = _mapping(resolve(self.bundle, "tools", reference)).get("kind")
            if kind == "endmill" and not re.search(r"\bend[\s-]?mills?\b", description, re.I):
                description += " endmill"
            if holder:
                description += f"; {holder}"
            if variants[reference] > 1:
                description += " — " + ", ".join(owners)
            packed_kind = "drilling" if kind in ("center_drill", "drill") else kind
            packable = (
                variants[reference] == 1
                and packed_kind in ("endmill", "drilling")
                and values
                and all(_NUMBER.fullmatch(value) or _WHOLE.fullmatch(value) for value in values)
            )
            key = (packed_kind,) if packable else (reference, holder, values, facts)
            setting = "; ".join(
                part for part in (" / ".join(values) or "hand", "; ".join(facts)) if part
            )
            grouped.setdefault(key, []).append((label, description, setting, owners))
        for entries in grouped.values():
            labels = [label for label, _, _, _ in entries]
            numbers = [re.fullmatch(r"T(\d+)", label) for label in labels]
            if len(labels) > 1 and all(numbers):
                positions = [int(number[1]) for number in numbers]
                label = (
                    labels[0] + "–" + labels[-1]
                    if positions == list(range(positions[0], positions[-1] + 1))
                    else ", ".join(labels)
                )
            else:
                label = ", ".join(labels)
            clauses = []
            for tool, description, setting, members in entries:
                clauses.append(
                    '<span class="tool-setting-entry" '
                    + f'data-physical-ops="{escape(json.dumps(members))}">'
                    + ("<strong>" + _numeric_html(tool) + ":</strong> " if len(entries) > 1 else "")
                    + _numeric_html(description + " " + setting)
                    + ".</span>"
                )
            rows.append(
                '<tr><th scope="row">'
                + _numeric_html(label)
                + "</th><td>"
                + " ".join(clauses)
                + "</td></tr>"
            )
        table = (
            '<table class="settings-key"><colgroup><col style="width:10%">'
            '<col style="width:90%"></colgroup>'
            "<tbody>" + "".join(rows) + "</tbody></table>"
            if rows
            else ""
        )
        coolant_lines = [
            self.reference(coolant, "consumables") + ": " + self.setup_span(owners)
            for coolant, owners in coolants.items()
        ]
        direction = ""
        if self._route_cut_direction:
            owners = [{"setup_id": sid, "op_id": op} for sid, op in self._route_cut_direction]
            value = next(iter(self._route_cut_direction.values()))
            direction = (
                f'<span data-physical-ops="{escape(json.dumps(owners))}">'
                + escape(self.direction(value).capitalize())
                + " milling.</span>"
            )
        return (
            '<div class="tool-settings"><h2>Tools / settings'
            + (
                f" — RPM / feed ({escape(unit)}/min unless marked); lengths ({escape(unit)})"
                if rows
                else ""
            )
            + "</h2>"
            + table
            + (
                "<p>"
                + _numeric_html("Coolant — " + "; ".join(coolant_lines) + ". ")
                + direction
                + "</p>"
                if coolant_lines
                else "<p>" + direction + "</p>"
                if direction
                else ""
            )
            + self.fixture_key()
            + "</div>"
        )

    def family_label(self, group):
        """Use an authored group name only when it identifies this complete family."""
        name = group[0].get("presentation_group")
        if not isinstance(name, str) or not name.strip() or len(group) < 2:
            return None
        members = [
            setup["id"]
            for setup in self.plan.get("setups", [])
            if setup.get("presentation_group") == name
        ]
        return name if members == [setup["id"] for setup in group] else None

    def setup_span(self, owners):
        """Collapse only adjacent members of an authored presentation group."""
        selected = set(owners)
        labels = []
        for group in self.route_groups(self.plan.get("setups", [])):
            members = [setup["id"] for setup in group if setup["id"] in selected]
            if not members:
                continue
            displayed = [_text(member) or "?" for member in members]
            labels.append(
                self.family_label(group) or displayed[0] + "–" + displayed[-1]
                if len(members) == len(group) and len(members) > 1
                else ", ".join(displayed)
            )
        return ", ".join(labels)

    def header(self, setups):
        routed = {id(finding) for setup in setups for finding in self.setup_findings(setup)}
        decisions = [
            self.finding_fact(finding) for finding in self.findings if id(finding) not in routed
        ]
        if not self.drawing_revision():
            decisions.append(
                _Decision(
                    "drawing_revision",
                    "unknown",
                    "drawing",
                    "block",
                    "Drawing revision not confirmed — match the drawing before execution.",
                )
            )
        decisions.extend(
            _Decision("approval", "warn", "approval", "caution", str(warning))
            for warning in self.approval.get("warnings", [])
        )
        html = "".join(_decision_html(group[0], group[1:]) for group in _decision_groups(decisions))
        stopped = [sid for sid, count in self.setup_stops.items() if count]
        if stopped:
            html += _p(
                "Blocked setups: "
                + ", ".join(_text(sid) or "?" for sid in stopped)
                + ". Resolve their stated prerequisites before execution."
            )
        summary = [self.material()]
        stock = _mapping(self.plan.get("stock"))
        components = stock.get("components")

        def stock_label(piece, reference="stock"):
            source = (
                piece
                if self.detail == "pedantic"
                else {key: value for key, value in _mapping(piece).items() if key != "note"}
            )
            return self.stock_line(source, reference)

        if isinstance(components, list) and components:
            summary.append(
                "Stock: "
                + "; ".join(
                    f"{_text(_mapping(component).get('id'))}: "
                    + stock_label(component, f"stock.{_text(_mapping(component).get('id'))}")
                    for component in components
                )
            )
        else:
            summary.append("Stock: " + stock_label(stock))
        if self.detail == "pedantic":
            html += "".join(_p(line) for line in summary)
            summary = []
        first = (_text(setups[0]["id"]) or "?") if setups else "the first setup"
        pieces = [("stock", stock)]
        if isinstance(components, list):
            pieces.extend(
                (f"stock.{_text(_mapping(component).get('id'))}", _mapping(component))
                for component in components
            )
        for piece_identity, piece in pieces:
            if piece.get("on_hand") is False:
                html += _decision_html(
                    _Decision(
                        "stock",
                        "unknown",
                        piece_identity,
                        "block",
                        f"Before {first}: obtain {piece_identity} — not on hand.",
                    )
                )
            prerequisite = piece.get("prerequisite")
            if isinstance(prerequisite, str) and prerequisite not in ("unknown", ""):
                html += _p(f"Before {first}: {self.bench(prerequisite).rstrip('.')}.")
        routes = []
        for group in self.setup_groups(setups):
            label = _text(group[0]["id"]) or "?"
            if len(group) > 1:
                label += "–" + (_text(group[-1]["id"]) or "?")
            routes.append(label)
        if routes and self.detail == "pedantic":
            html += '<p class="job-route">' + _numeric_html("Route: " + " → ".join(routes)) + "</p>"
        elif setups:
            machines = dict.fromkeys(setup.get("machine") for setup in setups)
            summary.append(
                "; ".join(self.reference(machine, "machines") for machine in machines)
                + ". "
                + {"in": "Inches", "mm": "Millimetres"}.get(
                    readout_units(self.bundle), _text(readout_units(self.bundle))
                )
                + " unless marked."
            )
        if source := self.speeds_source():
            summary.append(source)
        if self.detail == "pedantic":
            if resolution := self.dro_resolution(setups):
                summary.append(resolution)
            if self.example_marks:
                summary.append(EXAMPLE_LEGEND)
            html += "".join(_p(line) for line in summary)
        else:
            if resolution := self.dro_resolution(setups):
                summary.append(resolution)
            if self.plan.get("purpose", "shop") == "demonstration":
                summary.append("Demonstration fixtures/settings, not shop measurements.")
            html += _p(" ".join(summary), "job-summary")
        html += self.requirements()
        html += self.process_holds(setups)
        if self.detail != "pedantic":
            html += self.settings_key()
        if self.detail == "pedantic":
            keys = self.abbreviations(html)
            html += _p(" ".join(keys)) if keys else ""
        return html

    def abbreviations(self, page=""):
        printed = getattr(self, "sheet_text", "") + " " + re.sub(r"<[^>]+>", " ", page)
        return [meaning for pattern, meaning in _ABBREVIATIONS if re.search(pattern, printed)]

    def saw_cycle(self, setup, op):
        """Share an identical ordered trajectory using its structured cut-plane slot."""
        if not spindle_saw(self.bundle, setup, op):
            return None
        trajectory = _mapping(op.get("saw_trajectory"))
        start, moves = trajectory.get("start_mm"), trajectory.get("moves")
        plane = _mapping(op.get("cut_plane"))
        cut = plane.get("value")
        scale = {"mm": 1.0, "in": 25.4}.get(self.units)
        if (
            plane.get("axis") != "z"
            or not _known(cut)
            or scale is None
            or not isinstance(start, list)
            or len(start) != 3
            or not all(map(_known, start))
            or not isinstance(moves, list)
            or not moves
        ):
            return None
        previous, steps, signature = start, [], []
        previous_mode = None
        for move in moves:
            point = _mapping(move).get("to_mm")
            if not isinstance(point, list) or len(point) != 3 or not all(map(_known, point)):
                return None
            changed = [index for index in range(3) if point[index] != previous[index]]
            if len(changed) != 1:
                return None
            axis = changed[0]
            value = point[axis]
            slot = axis == 2 and math.isclose(value, cut * scale, rel_tol=0, abs_tol=SAME_Z)
            mode = move.get("mode")
            if mode not in ("clear", "cut"):
                return None
            if previous_mode == "cut" and mode == "clear":
                steps.append("STOP fully; capture remains clamped")
            steps.append(
                ("cut " if mode == "cut" else "")
                + "XYZ"[axis]
                + ("cut" if slot else self.readout(value / scale))
            )
            signature.append((axis, "cut-plane" if slot else value, mode))
            previous = point
            previous_mode = mode
        if previous_mode == "cut":
            steps.append("STOP fully; capture remains clamped")
        key = (
            identity(self.bundle, op.get("tool"), "tools"),
            identity(self.bundle, op.get("holder"), "holders"),
            tuple(start),
            tuple(signature),
        )
        owner = f"{setup['id']}:{op['op']}"
        home = self._saw_cycle_homes.setdefault(key, owner)
        if home != owner:
            if any(
                setup["id"] in {member["id"] for member in group}
                and home.partition(":")[0] in {member["id"] for member in group}
                for group in self.route_groups(self.plan.get("setups", []))
                if len(group) > 1
            ):
                return ""
            return _p(f"Repeat saw cycle {home}, Zcut={self.readout(cut)}.", "route-cycle")
        origin = "/".join(
            axis + self.readout(value / scale) for axis, value in zip("XYZ", start, strict=True)
        )
        mounted = self.mounted_datum_groups.get(setup["id"], ())
        heading = (
            "Saw cycle, Zcut from table."
            if mounted and mounted[0][0]["id"] == setup["id"]
            else f"Saw cycle {owner}, Zcut={self.readout(cut)}."
        )
        return _p(
            f"{heading} From {origin}, single-axis: "
            + " → ".join(steps)
            + ". Capture stays clamped through the full return; only then release/retrieve.",
            "route-cycle",
        )

    def shared_procedure_runs(self, setup, rows):
        """``{op id: run}`` for consecutive ops of one setup and workpiece that repeat one
        authored procedure with the same action, tool, holder and adverse decisions. Any
        other op between them, or a STOP/caution one op has and another lacks, ends the
        run; ops owning inspections, readings, contours or saw cycles never join one."""
        ops = {op["op"]: op for op in setup.get("ops", [])}
        contours = getattr(self, "_route_contours", {}).get(setup["id"], {})

        def signature(row):
            op = ops[row.op_id]
            note = note_text(row.authored_note, detail=self.detail)
            if (
                not note
                or note == UNKNOWN
                or _FIELD.search(note)
                or row[-1]
                or str(row.op_id) in contours
                or spindle_saw(self.bundle, setup, op)
                or op.get("tool") in (None, "unknown")
            ):
                return None
            holds = frozenset(
                (fact.source, fact.status, fact.kind, fact.text)
                for fact in row.decisions
                if fact.kind != "none"
            )
            return (row.workpiece, op.get("do"), op.get("tool"), op.get("holder"), note, holds)

        runs, run, previous = {}, [], None
        for row in [*rows, None]:
            key = signature(row) if row is not None else None
            if key is not None and key == previous:
                run.append(row)
                continue
            if len(run) > 1:
                runs.update((member.op_id, tuple(run)) for member in run)
            run, previous = ([row], key) if key is not None else ([], None)
        return runs

    def route_operation(
        self, setup, row, *, layout="block", lead_in="", keep_together=False, shared=None
    ):
        """Project one canonical row without duplicating its ledger and contour prose.
        ``shared`` is the row's run from :meth:`shared_procedure_runs`: its first row
        prints the common tool and authored procedure once; every row keeps its own
        number, feature, operative values and derived instructions."""
        op = next(op for op in setup.get("ops", []) if op["op"] == row.op_id)
        authored = note_text(row.authored_note, detail=self.detail)
        authored = self.bench(authored, setup) if authored else ""
        cycle_html = self.saw_cycle(setup, op)
        cycle = cycle_html is not None
        self._route_cycles[(setup["id"], row.op_id)] = cycle_html
        contour_owned = str(row.op_id) in getattr(self, "_route_contours", {}).get(setup["id"], {})
        path_owned = contour_owned and self.z_levels(setup, op) is not None
        canonical = ", ".join(
            self.cut_depth_text(
                self.cut_depths(setup, op, self.lathe(setup)),
                compact=True,
                omit_doc=contour_owned,
            )
        )
        parts = [
            canonical,
            row.instruction_before,
            None if shared else authored,
            row.instruction_after,
        ]
        action = " ".join(dict.fromkeys(part for part in parts if part)) or (
            "" if shared else _text(op.get("do"))
        )
        if len(row) == 5:
            consumable = row[2]
            tool = (
                self.route_tool_label(op["tool"])
                if op.get("tool") not in (None, "unknown")
                else consumable
                if consumable not in ("", "—", None)
                else ""
            )
            target = ""
        else:
            tool = (
                self.route_tool_label(op["tool"]) if op.get("tool") not in (None, "unknown") else ""
            )
            # The path owns its checked Z ladder; the target retains all other facts.
            values = row[6] if isinstance(row[6], (tuple, list)) else [row[6]]
            depth_target = self.z_target(setup, op) if path_owned else None
            target = (
                ""
                if cycle
                else "; ".join(
                    str(value)
                    for value in values
                    if value not in ("", "—", None, depth_target) and not isinstance(value, _Box)
                )
            )
            direction = self.direction(op["direction"]) if cycle and "direction" in op else row[7]
            if (
                self._route_cut_direction.get((setup["id"], row.op_id)) == op.get("direction")
                and (setup["id"], row.op_id) in self._route_cut_direction
                and direction == self.direction(op["direction"])
            ):
                direction = ""
            if direction not in ("", "—", None, "not applicable") and not isinstance(
                direction, _Box
            ):
                target = "; ".join(filter(None, (target, str(direction))))
            turn = getattr(row, "spindle_turn", None)
            turns = {
                getattr(other, "spindle_turn", None)
                for other in self._rows_by_setup.get(setup["id"], ())
                if getattr(other, "spindle_turn", None) in _SPINDLE_TURNS
            }
            if turn in _SPINDLE_TURNS and (
                len(turns) > 1 or self.detail == "pro" and turn == "REVERSE"
            ):
                sense = "spindle " + turn
                if self.detail == "hobby":
                    sense += ": " + _SPINDLE_TURNS[turn]
                target = "; ".join(filter(None, (target, sense)))
        if (
            op.get("do") in HAND_THREAD
            and not _known(
                _amount(_mapping(resolve(self.bundle, "tools", op.get("tool"))).get("lead_mm"))
            )
            and op.get("holder") not in (None, "unknown", "not_applicable")
        ):
            tool = "; ".join(filter(None, (tool, self.reference(op["holder"], "holders"))))
        if op.get("do") == "coating":
            tool = self.coating(op)
        feature_ids = op_features(op)
        labels = []
        for feature_id in feature_ids:
            definition = _mapping(self.features.get(feature_id))
            authored_label = definition.get("label", definition.get("name"))
            label = (
                authored_label
                if isinstance(authored_label, str) and authored_label.strip()
                else self.feature_name(feature_id)
            )
            if label != feature_id or not action:
                labels.append(label)
        feature = "; ".join(labels) if self.detail == "pedantic" else _numbered_names(labels, "; ")
        path_text, path_block = (
            getattr(self, "_route_contours", {}).get(setup["id"], {}).get(str(row.op_id), ("", ""))
        )
        zero = self.records.get(("zero_check", setup["id"]), {})
        numbered = (
            self.detail != "pedantic"
            or any(
                zero.get(key)
                for key in ("retouch", "tool_touches", "derived_touches", "missing_touches")
            )
            or any(
                re.search(r"\bop(?:s|erations?)?\b", str(text), re.IGNORECASE)
                for text in [
                    note_text(setup.get("note"), detail=self.detail),
                    _mapping(setup.get("zero")).get("procedure", ""),
                    *(
                        note_text(item.get("note"), detail=self.detail)
                        for item in setup.get("ops", [])
                    ),
                ]
            )
        )
        tag = "span" if layout == "inline" else "p"
        shared_lead = ""
        if shared:
            if row is shared[0]:
                owners = [
                    {"setup_id": setup["id"], "op_id": member.op_id, "workpiece": member.workpiece}
                    for member in shared
                ]
                shared_lead = (
                    f'<{tag} class="route-operation shared-procedure" '
                    f'data-physical-ops="{escape(json.dumps(owners))}">'
                    + f"<b>{escape(str(shared[0].op_id))}–{escape(str(shared[-1].op_id))}.</b> "
                    + f"<strong>{escape(tool)}:</strong> "
                    + _fields(authored)
                    + f"</{tag}>"
                )
            tool = ""
        content = (
            f'<{tag} class="route-operation{" keep" if keep_together else ""}" '
            f'data-features="{escape(json.dumps(feature_ids))}">'
            + lead_in
            + (f"<b>{escape(str(row.op_id))}.</b> " if numbered else "")
            + (
                f"<strong>{escape(tool)}"
                + (f" · {escape(feature)}" if feature else "")
                + ":</strong> "
                if tool
                else f"<strong>{escape(feature)}:</strong> "
                if feature
                else ""
            )
            + _fields(action)
            + ((" " if action else "") + _numeric_html(target) if target else "")
            + (" " + _fields(path_text) if path_text else "")
            + f"</{tag}>"
        )
        if shared_lead:
            # The paginator moves a keep box whole: the procedure never ends a page
            # apart from its first op.
            content = '<div class="keep">' + shared_lead + content + "</div>"
        for warning in row.warnings:
            # Decisions are rendered once at their actual owner, below. A contour pointer
            # is replaced by the concrete path in this same operation, not printed twice.
            pointer = (
                f"See {'guided sweep' if str(row.op_id) in self.sweep_ops else 'contour table'} "
                f"on Setup {_text(setup['id'])} contour instructions"
            )
            if isinstance(warning, (_Box, _OperationNote)) or warning == pointer:
                continue
            if warning in self._route_shared_warnings.get(setup["id"], {}):
                continue
            content += _warning_line(warning)
        for check in row[-1]:
            if not isinstance(check, _Inspection):
                content += (
                    _inspection_method(check)
                    if isinstance(check, (_Note, _Steps))
                    else "<p>" + _criterion_html(check) + "</p>"
                    if isinstance(check, _Criterion)
                    else _p(check)
                )
                continue
            reading_owner = check.reading_owned or any(
                _FIELD.search(str(method)) for method in check.methods
            )
            attributes = " " + _inspection_attributes(check) if reading_owner else ""
            inspection_start = len(content)
            content += f'<div class="route-inspection"{attributes}>'
            gauges, placed_methods = _inspection_gauge_groups(check), set()
            if not gauges:
                content += "<p>" + _criterion_html(next(_inspection_criteria((check,)))) + "</p>"
            for (_, gauge), criteria in gauges.items():
                bands = (
                    not reading_owner
                    and 2 <= len(criteria) <= 5
                    and all(
                        isinstance(criterion, _Criterion) and criterion.value is not None
                        for criterion in criteria
                    )
                )
                unit = readout_units(self.bundle)
                shared_unit = bands and all(
                    criterion.value.endswith(" " + unit) for criterion in criteria
                )
                gauge_label = gauge + (f" ({unit})" if shared_unit else "")
                for index, criterion in enumerate(criteria):
                    if not isinstance(criterion, _Criterion):
                        criterion = _Criterion(criterion, subjects=check.subjects)
                    methods = tuple(
                        method
                        for method in getattr(criterion, "methods", ())
                        if id(method) not in placed_methods
                    )
                    placed_methods.update(id(method) for method in methods)
                    inline = not reading_owner and all(
                        not isinstance(method, _Steps)
                        and not getattr(method, "sketch", "")
                        and not _FIELD.search(str(method))
                        for method in methods
                    )
                    method_html = " ".join(
                        _inspection_method(
                            method,
                            layout="inline" if inline else "block",
                            label=(
                                "criterion"
                                if getattr(method, "context", None)
                                == getattr(criterion, "context", "")
                                else "inline"
                            ),
                        )
                        for method in methods
                    )
                    shown = criterion
                    if bands:
                        value = (
                            criterion.value.removesuffix(" " + unit)
                            if shared_unit
                            else criterion.value
                        )
                        shown = criterion.heading + " " + value + "."
                    elif (
                        len(criteria) == 1
                        and inline
                        and gauge not in ("", UNKNOWN)
                        and not gauge.startswith("?")
                        and isinstance(criterion, _Criterion)
                        and criterion.context
                        and criterion.startswith(criterion.context)
                    ):
                        # The unique gauge owns this entire manual criterion. Keep
                        # its semantic identity without printing a second title.
                        shown = criterion[len(criterion.context) :].lstrip()
                    gauge_prefix = gauge_label + ": " if index == 0 or methods else ""
                    if inline:
                        if method_html:
                            shown = str(shown).rstrip(".") + " —"
                        content += (
                            "<p>"
                            + _criterion_html(criterion, gauge_prefix + shown)
                            + (" " + method_html if method_html else "")
                            + "</p>"
                        )
                    else:
                        content += (
                            "<p>" + _criterion_html(criterion, gauge_prefix + criterion) + "</p>"
                        )
                        content += method_html
            content += "".join(
                _inspection_method(method)
                for method in check.methods
                if id(method) not in placed_methods
            )
            content += "</div>"
            if not reading_owner and all(
                not isinstance(method, _Steps) and not getattr(method, "sketch", "")
                for method in check.methods
            ):
                content = content[:inspection_start] + content[inspection_start:].replace(
                    "</p><p>", " "
                )
        content += path_block
        return content

    def setup_blocks(self, setup):
        """Stable semantic keys; physical result records never become instructions."""
        sid = setup["id"]
        if sid in self._blocks_by_setup:
            return self._blocks_by_setup[sid]
        self.setup = setup
        self.register_measurements(self.collect_measurements(setup), setup)
        numbers, tools, tool_html = self.tool_table(setup)
        contour_stops = {}
        contours = self.contours(setup, tools, contour_stops)
        self.contour_stop_rows = contour_stops
        bench = manual_bench(self.bundle, setup)
        fixture_tables = self.shop_made_tables(setup)
        feature_html = self.feature_map(setup)
        steps, hold_below = self.hold(setup)
        dro_html = (
            None
            if bench
            else self.dro(
                setup, tools, procedure="inline" if self.detail == "pedantic" else "separate"
            )
        )
        clearance = None if bench else self.clearance(setup, numbers)
        purchased = self.purchased_tooling(setup)
        pictures = self.fixture_render(setup)
        self.settings_active = self.detail != "pedantic"
        rows = self.operation_rows(setup, numbers)
        self._rows_by_setup[sid] = rows
        warnings = {}
        for row in rows:
            pointer = (
                f"See {'guided sweep' if str(row.op_id) in self.sweep_ops else 'contour table'} "
                f"on Setup {_text(sid)} contour instructions"
            )
            for warning in row.warnings:
                if (
                    isinstance(warning, str)
                    and not isinstance(warning, (_Box, _OperationNote))
                    and not _FIELD.search(warning)
                    and warning != pointer
                ):
                    warnings.setdefault(warning, []).append(row)
        self._route_shared_warnings[sid] = {
            warning: owners for warning, owners in warnings.items() if len(owners) > 1
        }
        members = {row.workpiece for row in rows}
        member = next(iter(members)) if len(members) == 1 else None
        blocks = []

        def add(
            key,
            html,
            *,
            comparison=None,
            records=(),
            shared_html="",
            op_id=None,
            decisions=(),
            layout="block",
        ):
            if html:
                if comparison is None:
                    comparison = (sid, html) if 'class="writing-blank"' in html else html
                blocks.append(
                    _Block(
                        key,
                        html,
                        comparison,
                        tuple(records),
                        sid,
                        member,
                        shared_html,
                        op_id,
                        tuple(decisions),
                        layout,
                    )
                )

        selected_note = note_text(setup.get("note"), detail=self.detail)
        add(
            "note",
            "<p>" + _fields(self.bench(selected_note, setup)) + "</p>" if selected_note else "",
        )
        if self.detail == "pedantic":
            add("stock", self.stock_state(setup))
        add("holding", steps + hold_below)
        if self.detail == "pedantic":
            coolant = "" if bench else _p(f"Coolant: {self.bench(setup.get('coolant'))}.")
            add("coolant", coolant)
        add("purchased", purchased)
        add("edge-break", self.setup_edge_break(setup))
        if self.detail == "pedantic":
            add("tools", tool_html)
        add("fixture", fixture_tables)
        if self.detail == "pedantic":
            add("features", feature_html)
        if self.detail != "pedantic" and not bench:
            procedure = _mapping(setup.get("zero")).get("procedure")
            if isinstance(procedure, str) and procedure not in ("", "unknown"):
                tag = "p" if _FIELD.search(procedure) else "span"
                add(
                    "datum-procedure",
                    f"<{tag}>" + _fields(self.bench(procedure, setup)) + f"</{tag}> ",
                    layout="block" if tag == "p" else "inline",
                )
        datum_axes = self._route_datum_axes.get(sid, {})
        if datum_axes:
            add(
                "datum-references",
                "<p>"
                + _fields("; ".join(text.rstrip(".") for text in datum_axes.values()) + ".")
                + "</p>",
                comparison=(
                    sid if any(_FIELD.search(text) for text in datum_axes.values()) else None,
                    tuple(datum_axes.items()),
                ),
            )
        add("datum", dro_html)
        if self.detail == "pedantic":
            add("clearance", clearance)
        elif self.detail == "hobby":
            powered = [row for row in rows if getattr(row, "spindle_turn", None) in _SPINDLE_TURNS]
            turns = {row.spindle_turn for row in powered}
            if len(turns) == 1:
                turn = next(iter(turns))
                owners = [
                    {"setup_id": sid, "op_id": row.op_id, "workpiece": row.workpiece}
                    for row in powered
                ]
                add(
                    "spindle",
                    f'<p data-physical-ops="{escape(json.dumps(owners))}">'
                    + escape(f"Spindle {turn}: {_SPINDLE_TURNS[turn]}.")
                    + "</p>",
                )
        runs = self.shared_procedure_runs(setup, rows) if self.detail != "pedantic" else {}
        grouped = self.detail != "pedantic" and any(
            len(group) > 1 and sid in {member["id"] for member in group}
            for group in self.route_groups(self.plan.get("setups", []))
        )
        for row in rows:
            op = next(op for op in setup.get("ops", []) if op["op"] == row.op_id)
            records = tuple(check for check in row[-1] if isinstance(check, _Inspection))
            if self.detail != "pedantic":
                what = "guided sweep" if str(row.op_id) in self.sweep_ops else "contour table"
                pointer = f"See {what} on Setup {_text(sid)} contour instructions"
                inline = (
                    not row[-1]
                    and op.get("do") in MANUAL
                    and all(
                        isinstance(warning, (_Box, _OperationNote))
                        or warning == pointer
                        or warning in self._route_shared_warnings[sid]
                        for warning in row.warnings
                    )
                    and not any(fact.kind == "block" for fact in row.decisions)
                    and not self._route_contours.get(sid, {}).get(str(row.op_id), ("", ""))[1]
                    and not any(
                        _FIELD.search(str(value))
                        for value in [
                            *row[:-1],
                            note_text(row.authored_note, detail=self.detail),
                        ]
                    )
                )
                run = runs.get(row.op_id)
                keep_together = inline and op.get("do") == "deburr" and not run
                layout = "inline" if inline and not keep_together and not run else "block"
                instruction = self.route_operation(
                    setup, row, layout=layout, keep_together=keep_together, shared=run
                )
                comparison_instruction = instruction
                for criterion in _inspection_criteria(row[-1]):
                    comparison_instruction = comparison_instruction.replace(
                        '<span class="inspection-criterion" '
                        + _inspection_identity_attributes(criterion.subjects)
                        + ">",
                        '<span class="inspection-criterion" '
                        + _inspection_identity_attributes(())
                        + ">",
                    )
                methods = tuple(
                    (
                        type(method).__name__,
                        tuple(method) if isinstance(method, _Steps) else str(method),
                        getattr(method, "sketch", ""),
                    )
                    for check in records
                    for method in check.methods
                )
                reading_owned = any(
                    _FIELD.search(str(value)) for value in [*row[:-1], *row.warnings]
                ) or any(
                    check.reading_owned
                    or any(_FIELD.search(str(method)) for method in check.methods)
                    for check in records
                )
                add(
                    f"operation:{row.op_id}",
                    instruction,
                    comparison=(
                        comparison_instruction,
                        tuple(row[4:6]) if len(row) == 9 else (),
                        row.tool_spec,
                        methods,
                        tuple(
                            op_features(
                                next(op for op in setup.get("ops", []) if op["op"] == row.op_id)
                            )
                        ),
                        sid if reading_owned else None,
                    ),
                    records=records,
                    op_id=row.op_id,
                    layout=layout,
                )
                add(
                    f"saw-cycle:{row.op_id}",
                    self._route_cycles.get((sid, row.op_id)),
                    op_id=row.op_id,
                )
                for index, (warning, owners) in enumerate(self._route_shared_warnings[sid].items()):
                    if owners[0].op_id != row.op_id:
                        continue
                    identities = [
                        {"setup_id": sid, "op_id": owner.op_id, "workpiece": owner.workpiece}
                        for owner in owners
                    ]
                    add(
                        f"shared-warning:{index}",
                        '<div class="operation-caution" '
                        f'data-physical-ops="{escape(json.dumps(identities))}">'
                        + _warning_line(warning)
                        + "</div>",
                        comparison=(warning, tuple(owner.op_id for owner in owners)),
                    )
                boxes = {}
                for index, group in enumerate(
                    _decision_groups(row.decisions, combine_notices=True)
                ):
                    signature = tuple(
                        (fact.source, fact.status, fact.kind, fact.text) for fact in group
                    )
                    matches = [
                        (other, other_group)
                        for other in rows
                        for other_group in _decision_groups(other.decisions, combine_notices=True)
                        if tuple(
                            (fact.source, fact.status, fact.kind, fact.text) for fact in other_group
                        )
                        == signature
                        and (other is row or not any(_FIELD.search(fact.text) for fact in group))
                    ]
                    if matches[0][0] is not row:
                        continue
                    identities = [
                        {"setup_id": sid, "op_id": other.op_id, "workpiece": other.workpiece}
                        for other, _ in matches
                    ]
                    facts = tuple(fact for _, matched in matches for fact in matched)
                    decision_layout = (
                        "inline"
                        if self.detail == "pro"
                        and all(
                            fact.kind == "caution"
                            and fact.status == "warn"
                            and fact.source in ("headroom", "cut_clearance")
                            and not _FIELD.search(fact.text)
                            for fact in facts
                        )
                        else "block"
                    )
                    # One box per owner set and kind; a route-grouped setup keeps one box
                    # per notice so its members still share what they have in common.
                    owner_key = (
                        json.dumps(identities),
                        facts[0].kind,
                        decision_layout,
                        index if grouped or decision_layout == "inline" else None,
                    )
                    box = boxes.setdefault(owner_key, (index, identities, [], []))
                    box[2].append(facts)
                    box[3].append(signature)
                for key, (index, identities, groups, signatures) in boxes.items():
                    add(
                        f"operation-decision:{row.op_id}:{index}",
                        _decision_box(groups, owners=identities, layout=key[2]),
                        comparison=signatures[0] if len(signatures) == 1 else tuple(signatures),
                        op_id=row.op_id,
                        decisions=tuple(fact for facts in groups for fact in facts),
                        layout=key[2],
                    )
                continue
            criteria, common_checks = [], []
            reading_owned = any(_FIELD.search(str(value)) for value in [*row[:-1], *row.warnings])
            for check in row[-1]:
                if isinstance(check, _Inspection):
                    methods = tuple(
                        (
                            type(method).__name__,
                            tuple(method) if isinstance(method, _Steps) else str(method),
                            getattr(method, "sketch", ""),
                        )
                        for method in check.methods
                    )
                    criteria.append(
                        (
                            check.text,
                            check.features,
                            check.requirement,
                            check.unit,
                            check.qualitative,
                            methods,
                            check.reading_owned,
                        )
                    )
                    reading_owned |= check.reading_owned or any(
                        _FIELD.search(str(method)) for method in check.methods
                    )
                    common_checks.append(
                        replace(
                            check,
                            subjects=(),
                            setup_id="",
                            workpiece=None,
                            shared_check_id=None,
                            covered_workpieces=(),
                        )
                    )
                else:
                    criteria.append((type(check).__name__, check))
                    reading_owned |= bool(_FIELD.search(str(check)))
                    common_checks.append(check)
            common = _Row(
                (*row[:-1], common_checks), row.warnings, op_id=row.op_id, decisions=row.decisions
            )
            for name in (
                "authored_note",
                "instruction_after",
                "instruction_before",
                "instruction_fallback",
                "tool_label",
            ):
                setattr(common, name, getattr(row, name))
            headings = (
                ["step", "feature", "material / consumable", "action", "inspection"]
                if len(row) == 5
                else [
                    "op",
                    "do",
                    "feature",
                    "tool",
                    "rpm",
                    "feed",
                    "target",
                    "direction",
                    "inspection",
                ]
            )
            safety = (
                _p("Measure only with the spindle stopped and the tool withdrawn.")
                if self.lathe(setup) and row[-1]
                else ""
            )
            shared = (
                safety
                + '<table class="operations">'
                + _ledger_row(
                    common,
                    headings,
                    detail=self.detail,
                    show_settings=not self.settings_active,
                    results=False,
                    note_transform=lambda text: self.bench(text, setup),
                )
                + "</table>"
            )
            comparison = (
                tuple(row[:-1]),
                row.warnings,
                criteria,
                row.tool_spec,
                row.decisions,
                sid if reading_owned else None,
            )
            add(
                f"operation:{row.op_id}",
                self.operation_table(setup, [row], results=False),
                comparison=comparison,
                records=records,
                shared_html=shared,
                op_id=row.op_id,
            )
        if self.detail == "pedantic":
            add("contours", contours)
        add("pictures", pictures)
        add("blank-check", self.blank_checks(setup))
        decisions = [self.finding_fact(finding) for finding in self.setup_findings(setup)]
        decisions.extend(fact for row in rows for fact in row.decisions)
        decisions.extend(self.producer_decisions.get(sid, []))
        if upstream := self.upstream_stock_stop(setup):
            decisions.append(_Decision("stock_dependency", "unknown", sid, "block", upstream))
        local = [
            entry
            for key, (_, entry) in self.measurement_registry().items()
            if key in self.setup_measurement_ids.get(sid, set())
        ]
        # A compact level prints a measurement another setup notice already states once:
        # the same text groups both decisions into one notice.
        on_rows = {fact for row in rows for fact in row.decisions}
        stated = (
            {fact.text for fact in decisions if fact not in on_rows}
            if self.detail != "pedantic"
            else set()
        )
        decisions.extend(
            _Decision(
                "measurement",
                "unknown",
                sid,
                "block",
                line if line in stated else "Unverified decision input — " + line,
            )
            for line in self.measurement_lines(local, setup)
        )
        decisions = list(dict.fromkeys(decisions))
        self.setup_decisions[sid] = decisions
        self.setup_stops[sid] = sum(fact.kind == "block" for fact in decisions)
        displayed = {fact for row in rows for fact in row.decisions}
        pending = [decision for decision in decisions if decision not in displayed]
        groups = _decision_groups(pending, combine_notices=self.detail != "pedantic")
        if self.detail != "pedantic":
            groups = self.fold_zero_settings(groups, sid)
        # A compact setup prints one box per kind, each notice its own paragraph; a
        # route-grouped setup keeps one box per notice so members share what they share.
        merge = self.detail != "pedantic" and not grouped
        boxes = {}
        for index, group in enumerate(groups):
            if group[0].kind != "none":
                boxes.setdefault(group[0].kind if merge else index, (index, []))[1].append(group)
        for position, (index, members) in enumerate(boxes.values()):
            decision = members[0][0]
            signatures = tuple(
                tuple((fact.source, fact.status, fact.kind, fact.text) for fact in group)
                for group in members
            )
            blocks.insert(
                position if merge else index,
                _Block(
                    f"decision:{decision.source}:{index}",
                    _decision_box(members, setup_id=sid),
                    signatures[0] if len(signatures) == 1 else signatures,
                    (),
                    sid,
                    member,
                    decisions=tuple(fact for group in members for fact in group),
                ),
            )
        self._blocks_by_setup[sid] = blocks
        self.setup = None
        return blocks

    @staticmethod
    def block_html(block):
        html = block.html + _checkpoint_results(block.records)
        if block.op_id is None:
            return html
        owners = [{"setup_id": block.setup_id, "op_id": block.op_id, "workpiece": block.workpiece}]
        tag = "span" if block.layout == "inline" else "div"
        return (
            f'<{tag} data-setup-id="{escape(block.setup_id or "")}" '
            f'data-op="{escape(str(block.op_id))}" '
            f'data-physical-ops="{escape(json.dumps(owners))}">' + html + f"</{tag}> "
        )

    def setup_section(self, setup):
        return [[self.block_html(block) for block in self.setup_blocks(setup)]]

    def shared_route_facts(self, setups, blocks_by_setup):
        """Print exact, proved local references once with explicit setup ownership."""
        if self.detail == "pedantic":
            return ""

        def has_field(value):
            if isinstance(value, str):
                return bool(_FIELD.search(value))
            if isinstance(value, dict):
                return any(has_field(item) for item in value.values())
            if isinstance(value, (list, tuple)):
                return any(has_field(item) for item in value)
            return False

        candidates = {}
        families = {
            setup["id"]: index
            for index, group in enumerate(self.route_groups(setups))
            for setup in group
        }
        for setup in setups:
            sid = setup["id"]
            frame = setup_frame(self.bundle, setup)
            if (
                not isinstance(frame, dict)
                or not frame
                or setup.get("frame") in (None, "", UNKNOWN)
                or any(
                    not isinstance(frame.get(axis), list)
                    or len(frame[axis]) != 3
                    or not all(_known(value) for value in frame[axis])
                    for axis in ("origin", "x", "y", "z")
                )
                or not resolve(self.bundle, "machines", setup.get("machine"))
                or not resolve(
                    self.bundle, "workholding", _mapping(setup.get("hold")).get("fixture")
                )
                or self.indexing(setup)
                or self.setup_measurement_ids.get(sid)
                or any(
                    _FIELD.search(note_text(value, detail=self.detail))
                    for value in (setup.get("note"), _mapping(setup.get("hold")).get("note"))
                )
            ):
                continue
            context = (
                self.mount_key(setup),
                setup["frame"],
                json.dumps(frame, sort_keys=True),
            )
            note = note_text(setup.get("note"), detail=self.detail)
            if note and note != UNKNOWN:
                text = self.bench(note, setup)
                candidates.setdefault(("orientation", context, note, text), []).append((sid, text))
            if self.finding_statuses.get(("zero_check", sid)) == "pass":
                zero = _mapping(setup.get("zero"))
                computed = _mapping(self.records.get(("zero_check", sid), {}).get("axes"))
                for axis, text in self._route_datum_axes.get(sid, {}).items():
                    touch = _mapping(zero.get(axis))
                    record = _mapping(computed.get(axis))
                    if (
                        not touch
                        or touch.get("method")
                        not in (None, "paper", "touch", "opposed_edge_midpoint")
                        or touch.get("measure")
                        or touch.get("after_op") is not None
                        or (
                            record.get("actual_contact_readings")
                            and not (
                                record.get("part_result") == "not_recorded"
                                and record["actual_contact_readings"] == ["C−", "C+"]
                                and not touch.get("actual_contact_readings")
                                and not touch.get("part_result")
                            )
                        )
                        or has_field(touch)
                        or _FIELD.search(text)
                        or not _known(record.get("axis_set"))
                    ):
                        continue
                    signature = (
                        json.dumps(touch, sort_keys=True),
                        json.dumps(
                            {
                                key: record.get(key)
                                for key in (
                                    "edge_mm",
                                    "axis_set",
                                    "method",
                                    "sign",
                                    "paper_mm",
                                    "radius_mm",
                                    "part_result",
                                    "actual_contact_readings",
                                )
                            },
                            sort_keys=True,
                        ),
                    )
                    key = ("datum", context, axis, signature, text)
                    candidates.setdefault(key, []).append((sid, axis))
            if any(
                fact.kind != "none" and fact.source in ("hold_fields", "measurement", "alignment")
                for fact in self.setup_decisions.get(sid, ())
            ):
                continue
            for signature, text in self._route_hold_facts.get(sid, {}).items():
                key = ("holding", context, signature, text)
                candidates.setdefault(key, []).append((sid, text))
        shared = {}
        changed = set()
        shared_notes = set()
        for key, owners in candidates.items():
            # Existing family composition already shares identical local facts.
            if len({families[sid] for sid, _ in owners}) < 2:
                continue
            kind, text = key[0], key[-1]
            ids = [sid for sid, _ in owners]
            shared.setdefault((kind, tuple(ids)), []).append(text.rstrip("."))
            for sid, item in owners:
                changed.add(sid)
                if kind == "datum":
                    self._route_datum_axes[sid].pop(item)
                elif kind == "orientation":
                    shared_notes.add(sid)
                else:
                    self._route_hold_steps[sid] = tuple(
                        step for step in self._route_hold_steps[sid] if step != item
                    )
        for sid in changed:
            blocks = []
            for block in blocks_by_setup[sid]:
                if block.key == "note" and sid in shared_notes:
                    continue
                if block.key == "datum-references":
                    axes = self._route_datum_axes[sid]
                    if axes:
                        blocks.append(
                            replace(
                                block,
                                html="<p>"
                                + _fields(
                                    "; ".join(text.rstrip(".") for text in axes.values()) + "."
                                )
                                + "</p>",
                                comparison=(
                                    sid
                                    if any(_FIELD.search(text) for text in axes.values())
                                    else None,
                                    tuple(axes.items()),
                                ),
                            )
                        )
                elif block.key == "holding":
                    steps = self._route_hold_steps[sid]
                    if steps:
                        html = _p(" ".join(steps))
                        blocks.append(replace(block, html=html, comparison=html))
                else:
                    blocks.append(block)
            blocks_by_setup[sid] = blocks
        scopes = {}
        for (kind, ids), texts in shared.items():
            scopes.setdefault(ids, []).append(
                f'<span data-setup-members="{escape(json.dumps(ids))}" '
                f'data-reference-kind="{kind}">' + _numeric_html("; ".join(texts)) + "</span>"
            )
        lines = [
            "<strong>" + escape(self.setup_span(ids)) + ":</strong> " + "; ".join(facts)
            for ids, facts in scopes.items()
        ]
        return (
            '<p class="route-references"><strong>Shared references.</strong> '
            + "; ".join(lines)
            + ".</p>"
            if lines
            else ""
        )

    def shared_criterion_identities(self, variant, html):
        """Union only corresponding criteria of already-equal member instructions."""
        if not all(block.key.startswith("operation:") for block in variant):
            return html
        criteria = []
        for block in variant:
            row = next(
                (
                    row
                    for row in self._rows_by_setup.get(block.setup_id, ())
                    if row.op_id == block.op_id
                ),
                None,
            )
            if row is None:
                return html
            criteria.append(tuple(_inspection_criteria(row[-1], compact=self.detail != "pedantic")))
        opening = '<span class="inspection-criterion" '
        parts = html.split(opening)
        for index, corresponding in enumerate(zip(*criteria, strict=True), 1):
            subjects = tuple(
                dict.fromkeys(
                    subject for criterion in corresponding for subject in criterion.subjects
                )
            )
            _, closing, body = parts[index].partition(">")
            parts[index] = _inspection_identity_attributes(subjects) + closing + body
        return opening.join(parts)

    def family_html(self, group, blocks_by_setup, *, heading_note=""):
        ids = [setup["id"] for setup in group]
        displayed_ids = [_text(sid) for sid in ids]
        title = (
            (f"SETUP {displayed_ids[0]}" if len(ids) == 1 else "SETUPS " + ", ".join(displayed_ids))
            + " — "
            + self.reference(group[0].get("machine"), "machines")
        )
        if self.detail != "pedantic":
            title = (
                displayed_ids[0] if len(ids) == 1 else displayed_ids[0] + "–" + displayed_ids[-1]
            )
        heading = title
        if self.detail != "pedantic" and (label := self.family_label(group)):
            heading = f"{label} ({title})"
        if heading_note:
            title += " — " + heading_note
            heading += " — " + heading_note
        owners = {block.workpiece for setup in group for block in blocks_by_setup[setup["id"]]}
        members = list(owners) if len(owners) == 1 and None not in owners else []
        result = [
            f'<section class="{"setup-flow" if len(group) == 1 else "setup-family"}" '
            f'data-setup-title="{escape(title)}" '
            f'data-setup-id="{escape(ids[0] or "") if len(ids) == 1 else ""}" '
            f'data-setup-members="{escape(json.dumps(ids))}" '
            f'data-workpiece="{escape(members[0]) if len(members) == 1 else ""}">'
            f"<h2>{escape(heading)}</h2>"
        ]
        maps = [{block.key: block for block in blocks_by_setup[sid]} for sid in ids]
        if (
            self.detail == "hobby"
            and len(group) == 1
            and group[0]["id"] in self._route_picture_setups
            and any(op.get("do") in ("rough_profile", "profile") for op in group[0].get("ops", []))
        ):
            result.append(
                _p(
                    f"Setup {ids[0]} view follows op {group[0]['ops'][-1]['op']}.",
                    "setup-view-reference",
                )
            )
        facing, facing_levels = {}, {}
        for setup in group:
            for op in setup.get("ops", []):
                row = self._route_facing_paths.get((setup["id"], str(op["op"])))
                if row is None:
                    continue
                z, lift, start, end, ys, entry_kind = row
                facing.setdefault(setup["id"], []).append(
                    f'<span class="facing-path" data-op-id="{escape(str(op["op"]))}">'
                    + _numeric_html(f"X {start} → {end}; Y {ys}.")
                    + "</span>"
                )
                facing_levels.setdefault((z, lift, entry_kind), []).append(
                    f"{setup['id']}:{op['op']}"
                )
        facing_rules = [
            _p(
                (
                    ", ".join(owners) + ": "
                    if len(facing_levels) > 1 or len(facing) != len(group)
                    else ""
                )
                + f"Each Y: lower to Z{z} "
                + ("in air at start" if entry_kind == "air" else "at tangent start")
                + "; feed X start→end one-way; "
                + f"lift Z{lift} before return/reposition.",
                "facing-cycle",
            )
            for (z, lift, entry_kind), owners in facing_levels.items()
        ]
        facing_embedded = False
        prelude_html, prelude_operation = "", None
        saw_cycles = [
            self._route_cycles.get((setup["id"], op["op"]))
            for setup in group
            for op in setup.get("ops", [])
            if spindle_saw(self.bundle, setup, op)
        ]
        inferred = (
            self.detail != "pedantic" and len(group) > 1 and not group[0].get("presentation_group")
        )
        if inferred:
            # Match operation roles, not incidental local numbering. Metadata below
            # still carries every original setup/op and member identity.
            for index, (setup, mapping) in enumerate(zip(group, maps, strict=True)):
                counts, aliases = {}, {}
                for op in setup.get("ops", []):
                    role = op.get("do")
                    counts[role] = counts.get(role, 0) + 1
                    aliases[f"operation:{op['op']}"] = f"role:{role}:{counts[role]}"
                maps[index] = {aliases.get(key, key): block for key, block in mapping.items()}
            holds = [self._route_hold_steps.get(sid, ()) for sid in ids]
            common = [
                step
                for step in holds[0]
                if all(step in steps for steps in holds[1:]) and not _FIELD.search(step)
            ]
            # An indexing instruction or authored reading is not a table annotation.
            table_safe = all(
                not _FIELD.search(" ".join(steps))
                and not _FIELD.search(note_text(setup.get("note"), detail=self.detail))
                and not any(
                    _FIELD.search(text)
                    for text in self._route_datum_axes.get(setup["id"], {}).values()
                )
                and not self.indexing(setup)
                for setup, steps in zip(group, holds, strict=True)
            )
            if table_safe:
                orientation_rows = {}
                axes_by_setup = [self._route_datum_axes.get(setup["id"], {}) for setup in group]
                common_axes = {
                    axis: text
                    for axis, text in axes_by_setup[0].items()
                    if all(axes.get(axis) == text for axes in axes_by_setup[1:])
                    and not _FIELD.search(text)
                }
                if "z" not in common_axes:
                    # The surface and its coordinate can be shared even when the
                    # first-use paper/Axis Set instructions are local to one row.
                    z_parts = [axes.get("z", "").split("; ", 2) for axes in axes_by_setup]
                    if all(len(parts) >= 2 for parts in z_parts) and all(
                        parts[:2] == z_parts[0][:2] for parts in z_parts[1:]
                    ):
                        common_axes["z"] = "; ".join(z_parts[0][:2])
                common_text = " ".join(common)
                if common_axes:
                    common_text += (" " if common_text else "") + "Common datums: "
                    common_text += "; ".join(text.rstrip(".") for text in common_axes.values())
                    common_text += "."
                if common_text:
                    result.append(_p(common_text))
                grip_labels = {
                    setup["id"]: {
                        text: f"Parallels {_number(fact[2])} mm; grip {_number(fact[3])} mm."
                        for fact, text in self._route_hold_facts.get(setup["id"], {}).items()
                        if fact[0] == "parallels"
                        and text not in common
                        and text in self._route_hold_steps.get(setup["id"], ())
                    }
                    for setup in group
                }
                if not all(len(labels) == 1 for labels in grip_labels.values()):
                    grip_labels = {}
                for setup, mapping, steps in zip(group, maps, holds, strict=True):
                    note = mapping.pop("note", None)
                    mapping.pop("holding", None)
                    local = " ".join(
                        grip_labels.get(setup["id"], {}).get(step, step)
                        for step in steps
                        if step not in common
                    )
                    note_text_ = note_text(setup.get("note"), detail=self.detail) if note else ""
                    html = _fields(
                        " ".join(
                            filter(
                                None, (self.bench(note_text_, setup) if note_text_ else "", local)
                            )
                        )
                    )
                    mapping.pop("datum-references", None)
                    local_datums = []
                    for axis, text in self._route_datum_axes.get(setup["id"], {}).items():
                        shared = common_axes.get(axis)
                        if text == shared:
                            continue
                        if shared and text.startswith(shared + "; "):
                            text = text[len(shared) + 2 :]
                        local_datums.append(text.rstrip("."))
                    datums = "; ".join(local_datums)
                    if setup["id"] in facing:
                        html += " " + _fields(datums) if datums else ""
                        html += (". " if datums else " ") + " ".join(facing[setup["id"]])
                        datums = ""
                        # This is vertical tip/jaw height, independent of the native minimum.
                        headroom = _mapping(self.records.get(("headroom", setup["id"])))
                        cuts = _mapping(headroom.get("cut_tip_above_jaws_mm"))
                        jaw = _mapping(headroom.get("jaw_obstruction")).get("jaw_top_z")
                        for op in setup.get("ops", []):
                            op_id = str(op["op"])
                            if (setup["id"], op_id) not in self._route_facing_paths:
                                continue
                            planned = cuts.get(op_id, cuts.get(op["op"]))
                            tip = self.dro_to_z(setup, op)
                            value = tip - jaw if _known(tip) and _known(jaw) else planned
                            if (
                                self.detail == "hobby"
                                and _known(planned)
                                and _known(value)
                                and min(planned, value) > _CRASH_ZONE_MM
                            ):
                                owners = [{"setup_id": setup["id"], "op_id": op["op"]}]
                                html += (
                                    f' <span data-physical-ops="{escape(json.dumps(owners))}">'
                                    + _numeric_html(
                                        f"Tip above {self.jaw_top_scope(setup).lower()} "
                                        f"≈{value:.1f} mm."
                                    )
                                    + "</span>"
                                )
                            decision_keys = [
                                key
                                for key in mapping
                                if key.startswith(f"operation-decision:{op_id}:")
                            ]
                            for key in decision_keys:
                                html += " " + self.block_html(mapping.pop(key))
                        if self.detail == "hobby" and setup["id"] in self._route_picture_setups:
                            html += (
                                ' <span class="setup-view-reference">'
                                + escape(
                                    f"Setup {setup['id']} view follows the common facing cycle."
                                )
                                + "</span>"
                            )
                    orientation_rows.setdefault((html, datums), []).append(setup["id"])
                table_rows = []
                for (html, datums), owners in orientation_rows.items():
                    table_rows.append(
                        f'<tr data-setup-id="{escape(owners[0]) if len(owners) == 1 else ""}" '
                        f'data-setup-members="{escape(json.dumps(owners))}">'
                        f'<th scope="row">{escape(", ".join(owners))}</th><td>'
                        + html
                        + (" " + _fields(datums) if datums else "")
                        + "</td></tr>"
                    )
                if self.detail != "pedantic" and all(
                    any(spindle_saw(self.bundle, setup, op) for op in setup.get("ops", []))
                    for setup in group
                ):
                    result.extend(
                        f'<p data-setup-members="{escape(json.dumps(owners))}">'
                        + "<strong>"
                        + escape(", ".join(owners))
                        + ":</strong> "
                        + html
                        + (" " + _fields(datums) if datums else "")
                        + "</p>"
                        for (html, datums), owners in orientation_rows.items()
                    )
                else:
                    result.extend(facing_rules)
                    facing_embedded = bool(facing)
                    result.append(
                        '<table class="orientation-table'
                        + (" facing-paths" if facing else "")
                        + '" aria-label="Orientation / holding / datums / facing centres"><tbody>'
                        + "".join(table_rows)
                        + "</tbody></table>"
                    )
        elif self.detail != "pedantic":
            prelude_keys = ("note", "holding", "datum-references")
            preludes = []
            for setup, mapping in zip(group, maps, strict=True):
                note = note_text(setup.get("note"), detail=self.detail) if "note" in mapping else ""
                holding = (
                    self._route_hold_steps.get(setup["id"], ()) if "holding" in mapping else ()
                )
                datums = (
                    self._route_datum_axes.get(setup["id"], {})
                    if "datum-references" in mapping
                    else {}
                )
                text = " ".join(
                    filter(
                        None,
                        (
                            self.bench(note, setup) if note else "",
                            " ".join(holding) if holding else "",
                            "; ".join(value.rstrip(".") for value in datums.values()) + "."
                            if datums
                            else "",
                        ),
                    )
                )
                signature = tuple(
                    (key, mapping[key].comparison) for key in prelude_keys if key in mapping
                )
                preludes.append((text, signature))
            if (
                preludes[0][0]
                and all(prelude == preludes[0] for prelude in preludes)
                and not _FIELD.search(preludes[0][0])
                and not any(self.indexing(setup) for setup in group)
            ):
                prelude_html = (
                    f'<span class="route-prelude" data-setup-members="{escape(json.dumps(ids))}">'
                    + _fields(preludes[0][0])
                    + "</span> "
                )
                inspection_blocks = [
                    mapping.get(f"operation:{setup['ops'][0]['op']}")
                    if manual_bench(self.bundle, setup)
                    and len(setup.get("ops", [])) == 1
                    and setup["ops"][0].get("do") == "inspect"
                    else None
                    for setup, mapping in zip(group, maps, strict=True)
                ]
                if all(
                    block is not None
                    and block.records
                    and block.comparison == inspection_blocks[0].comparison
                    and not any(record.reading_owned for record in block.records)
                    and 'class="writing-blank"' not in block.html
                    for block in inspection_blocks
                ) and not any(
                    fact.kind == "block"
                    for mapping in maps
                    for block in mapping.values()
                    for fact in block.decisions
                ):
                    prelude_operation = inspection_blocks[0].key
                else:
                    result.append(prelude_html)
                    prelude_html = ""
                for mapping in maps:
                    for key in prelude_keys:
                        mapping.pop(key, None)
        if facing and not facing_embedded:
            result.extend(facing_rules)
            result.append(
                '<table class="facing-paths" aria-label="Facing cutter centres"><tbody>'
                + "".join(
                    f'<tr data-setup-id="{escape(sid)}"><th scope="row">{escape(sid)}</th>'
                    + "<td>"
                    + " ".join(paths)
                    + "</td></tr>"
                    for sid, paths in facing.items()
                )
                + "</tbody></table>"
            )
        keys = list(dict.fromkeys(key for mapping in maps for key in mapping))
        # Keep a later member's complete datum prerequisite group in source order,
        # before any cuts; first-appearance union order may put only some keys late.
        first_operation = next(
            (index for index, key in enumerate(keys) if key.startswith(("operation:", "role:"))),
            len(keys),
        )
        datum_keys = [
            key for key in ("datum-procedure", "datum-references", "datum") if key in keys
        ]
        if datum_keys:
            start = min(first_operation, *(keys.index(key) for key in datum_keys))
            keys[start:] = datum_keys + [key for key in keys[start:] if key not in datum_keys]
        last_inline_owners = None
        last_visible_owners = tuple(ids)
        for key in keys:
            available = [mapping[key] for mapping in maps if key in mapping]
            variants = []
            for block in available:
                match = next(
                    (variant for variant in variants if variant[0].comparison == block.comparison),
                    None,
                )
                if match is None:
                    variants.append([block])
                else:
                    match.append(block)
            for variant in variants:
                if prelude_html and key == prelude_operation:
                    block = variant[0]
                    setup = next(setup for setup in group if setup["id"] == block.setup_id)
                    row = next(
                        row
                        for row in self._rows_by_setup[block.setup_id]
                        if row.op_id == block.op_id
                    )
                    variant[0] = replace(
                        block,
                        html=self.route_operation(
                            setup, row, layout=block.layout, lead_in=prelude_html
                        ),
                    )
                    prelude_html = ""
                if len(variant) > 1:
                    identities = [
                        {
                            "setup_id": block.setup_id,
                            "op_id": block.op_id,
                            "workpiece": block.workpiece,
                        }
                        for block in variant
                    ]
                    shared = variant[0].shared_html or variant[0].html
                    shared = self.shared_criterion_identities(variant, shared)
                    if variant[0].decisions:
                        facts = tuple(fact for block in variant for fact in block.decisions)
                        shared = _decision_html(
                            facts[0], facts[1:], owners=identities, layout=variant[0].layout
                        )
                    inline_owners = tuple(block.setup_id for block in variant)
                    label = (
                        _p(", ".join(block.setup_id for block in variant), "variant-label")
                        if len(variant) != len(group)
                        or self.detail != "pedantic"
                        and last_visible_owners != inline_owners
                        else ""
                    )
                    tag = "span" if variant[0].layout == "inline" else "div"
                    if tag == "span" and label:
                        label = (
                            '<span class="variant-label">'
                            + escape(", ".join(inline_owners))
                            + ": </span>"
                            if inline_owners != last_inline_owners
                            else ""
                        )
                    last_inline_owners = inline_owners if tag == "span" else None
                    last_visible_owners = inline_owners
                    result.append(
                        f'<{tag} class="family-common" '
                        f'data-physical-ops="{escape(json.dumps(identities))}">'
                        + label
                        + shared
                        + _checkpoint_results(
                            tuple(record for block in variant for record in block.records)
                        )
                        + f"</{tag}> "
                    )
                else:
                    block = variant[0]
                    label = f"Setup {block.setup_id}" + (
                        f" — {block.workpiece}" if block.workpiece else ""
                    )
                    display_label = (
                        label if self.detail == "pedantic" else label.removeprefix("Setup ")
                    )
                    if heading_note:
                        label += " — " + heading_note
                    tag = "span" if block.layout == "inline" else "div"
                    common_definition = (
                        inferred
                        and key == "datum"
                        and {
                            item[0]["id"]
                            for item in self.mounted_datum_groups.get(block.setup_id, ())
                        }
                        == set(ids)
                    ) or (
                        inferred
                        and key.startswith("saw-cycle:")
                        and len(saw_cycles) == len(group)
                        and all(cycle is not None for cycle in saw_cycles)
                        and sum(bool(cycle) for cycle in saw_cycles) == 1
                    )
                    visible_label = ""
                    if len(group) > 1 and not common_definition:
                        visible_label = (
                            '<span class="variant-label">' + escape(display_label) + ": </span>"
                            if tag == "span" and last_inline_owners != (block.setup_id,)
                            else _p(display_label, "variant-label")
                            if tag != "span"
                            else ""
                        )
                    last_inline_owners = (block.setup_id,) if tag == "span" else None
                    last_visible_owners = tuple(ids) if common_definition else (block.setup_id,)
                    result.append(
                        f'<{tag} class="setup-variant" data-setup-title="{escape(label)}" '
                        f'data-setup-id="{escape(block.setup_id or "")}" '
                        f'data-workpiece="{escape(block.workpiece or "")}">'
                        + visible_label
                        + self.block_html(block)
                        + f"</{tag}> "
                    )
        result.append("</section>")
        return "".join(result)

    def render(self):
        setups = self.plan.get("setups", [])
        self._front_reference_layout = self.detail == "hobby"
        cutting = [
            (setup["id"], op)
            for setup in setups
            for op in setup.get("ops", [])
            if op.get("do") in ("face", "profile", "rough_profile")
            or spindle_saw(self.bundle, setup, op)
        ]
        directions = {op.get("direction") for _, op in cutting}
        if (
            self.detail != "pedantic"
            and len(cutting) > 1
            and directions
            in (
                {"conventional"},
                {"climb"},
            )
        ):
            self._route_cut_direction = {(sid, op["op"]): op["direction"] for sid, op in cutting}
        blocks_by_setup = {}
        for setup in setups:
            sections = self.setup_section(setup)
            blocks_by_setup[setup["id"]] = self._blocks_by_setup.get(setup["id"]) or [
                _Block(f"section:{index}", block, block, (), setup["id"])
                for index, block in enumerate(block for section in sections for block in section)
                if block
            ]
        groups = self.route_groups(setups)
        final = groups[-1] if self.detail == "hobby" and len(groups) > 1 else []
        final_blocks = [block for setup in final for block in blocks_by_setup[setup["id"]]]
        final_records = [record for block in final_blocks for record in block.records]
        deferred_final = (
            final
            and final_records
            and all(
                manual_bench(self.bundle, setup)
                and setup.get("ops")
                and all(op.get("do") == "inspect" for op in setup["ops"])
                and not self.indexing(setup)
                for setup in final
            )
            and not any(record.reading_owned for record in final_records)
            and not any(
                block.key == "pictures"
                or 'class="writing-blank"' in block.html
                or any(fact.kind == "block" for fact in block.decisions)
                for block in final_blocks
            )
        )
        after = [setup["id"] for setup in groups[-2]] if deferred_final else []
        saved_axes = {sid: dict(axes) for sid, axes in self._route_datum_axes.items()}
        saved_holding = dict(self._route_hold_steps)
        try:
            references = self.shared_route_facts(setups, blocks_by_setup)
            flow = [
                self.family_html(
                    group,
                    blocks_by_setup,
                    heading_note=(
                        "final inspection: Complete ONLY AFTER " + self.setup_span(after)
                        if deferred_final and group is final
                        else ""
                    ),
                )
                for group in groups
            ]
        finally:
            self._route_datum_axes = saved_axes
            self._route_hold_steps = saved_holding
        self.sheet_text = " ".join(re.sub(r"<[^>]+>", " ", block) for block in flow)
        header = self.header(setups) + references
        if self.detail == "hobby":
            header += self._front_dro_guide
            if deferred_final:
                final_ids = [setup["id"] for setup in final]
                route = " → ".join(
                    self.setup_span([setup["id"] for setup in group]) for group in groups
                )
                final_html = flow.pop()
                header += (
                    _p("Execution order: " + route + ".")
                    + '<section id="final-inspection-reference" class="final-reference" '
                    + 'data-reference-only="true" data-page-reference="final-inspection" '
                    + f'data-execute-after="{escape(json.dumps(after))}">'
                    + final_html
                    + "</section>"
                )
                flow.append(
                    '<p class="final-reference-return">After '
                    + escape(self.setup_span(after))
                    + ', complete <a href="#final-inspection-reference">'
                    + escape(self.setup_span(final_ids))
                    + " final inspection/results at the front of this job</a>.</p>"
                )
        appendix = self.job_measurement_box() if self.detail == "pedantic" else ""
        content = self.finalize_measurements([[[header, *flow, appendix]]])[0][0]
        if self.detail != "pedantic":
            content = [
                re.sub(r' data-measurement-ref="M\d+"', "", re.sub(r"\?M\d+\b", "?", block))
                for block in content
            ]
        drawing = _mapping(self.plan.get("drawing"))
        part, revision = _text(self.plan.get("part")), self.drawing_revision()
        title = (
            f"{part.upper()} · {_text(drawing.get('number'))} · "
            + (f"rev {revision}" if revision else "REV NOT CONFIRMED")
            if self.detail == "pedantic"
            else part.replace("_", " ").replace("-", " ").title()
        )
        quantity = escape(_text(self.plan.get("quantity")))
        identity_html = (
            f'<div class="meta"><h1>{escape(title)}</h1>'
            f"<div>qty {quantity} · {self.detail}</div></div>"
            if self.detail == "pedantic"
            else f'<p class="job-identity"><strong>{escape(title)}</strong> · qty {quantity} · '
            f"{escape(_text(drawing.get('number')))} · "
            + escape(f"rev {revision}" if revision else "REV NOT CONFIRMED")
            + '<span class="cont-count first-page-count"> · page 1 of '
            '<span class="cont-page-total"></span></span></p>'
        )
        banner = "CHECKED — FIRST ARTICLE RECORDED" if self.checked else "PLANNED — NOT APPROVED"
        demonstration = self.plan.get("purpose", "shop") == "demonstration"
        if demonstration:
            banner = "EXAMPLE ONLY — NOT FOR EXECUTION IN A REAL ENVIRONMENT · " + banner
        disclosure = (
            ' data-example-only="true" data-continuation-label="EXAMPLE ONLY"'
            if demonstration
            else ""
        )
        result = [
            '<!DOCTYPE html>\n<html lang="en"><head><meta charset="utf-8">',
            '<meta name="prechips-version" '
            f'content="{escape(_text(self.report.get("prechips_version")))}">',
            f'<meta name="prechips-report" content="{escape(_text(self.report.get("hash")))}">',
            f'<meta name="prechips-detail" content="{self.detail}">',
            f"<title>{escape(part)} traveler</title><style>{_CSS}</style>"
            f'<script>{JOB_PRINT_JS}</script></head><body data-detail="{self.detail}">',
            f'<section class="page" data-sheet="job" data-title="JOB" data-part="{escape(part)}" '
            f'data-job-title="{escape(title)}" '
            f'data-quantity="{escape(_text(self.plan.get("quantity")))}" '
            f'data-drawing="{escape(_text(drawing.get("number")))}" '
            f'data-revision="{escape(revision or "")}"{disclosure}>',
            identity_html,
            f'<div class="banner">{escape(banner)}</div>',
            *content,
            "</section></body></html>\n",
        ]
        return "\n".join(result)


_METADATA = {"cite", "source", "paths", "features", "step_sha256", "inspection_methods"}


def render_traveler(
    bundle, findings, report, approval=None, *, detail: TravelerDetail = "hobby"
) -> str:
    """Render fresh declared/computed instructions; detail never changes evaluation."""
    if detail not in TRAVELER_DETAILS:
        raise ValueError("detail must be pro, hobby, or pedantic")
    return _Traveler(bundle, findings, report, approval, detail=detail).render()


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
                if (
                    category != "tools"
                    or length_fact(record, field, require_measured=False)["verified"]
                ):
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
        width = length_mm(item, "blade_width")
        return (f"{_number(width)} mm " if _known(width) and width else "") + "parting blade"
    return short_reference_label(bundle, reference, "tools")
