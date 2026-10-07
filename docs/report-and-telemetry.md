# Report binding, approval, output safety and telemetry

## Canonical report

`report.json` contains `expected_exit`, `findings`, `inputs`,
`prechips_version`, `rules_version`, `step_sha256`, `verification`, `hash`,
and, only when the kernel returned a setup render, `renders`.
Findings sort lexicographically by `(rule, subject)` and contain `rule`,
`subject`, `status`, `numbers`, `cite`, `message` (not `sentence` or a separate
severity). No clock timestamp enters the report.
The current catalogue is `rules_version = "m5-rev9"`: the M5 review cutover
(bed-height vise stack, per-pair tool projection, approach/floor-aware envelope,
spindle-nose Z travel, unpadded hole centres, one `envelope` machine block,
fact-local trust, no `holder_stack` rule), dividing-head/child-centre fixes and
nine M4 kernel geometry rules including native saw cut-off with hash-bound setup
renders. Changing the operative catalogue changes the bound report and
invalidates prior approvals; reports from earlier catalogues, including
`m5-rev8`, must be regenerated and reapproved.
A finding's `numbers.measurements` lists the exact fact ids (set member or
tool/holder pair included) whose measurement would resolve it; `tools --measure`
is the sorted, deduplicated union of those lists over the current plans.

Canonical bytes are UTF-8 JSON, sorted keys, two-space indentation,
`ensure_ascii=False`, finite numbers only, and **one final LF**. `hash` is the
SHA-256 of that same canonical serialization after removing **only** the root
`hash` member, including the final LF. Every read operative TOML/STEP asset has
its exact file-byte SHA-256. Input record keys are `plan`, `features`,
`inventory`, `shop_policy`, `cutting_data` plus referenced assets such as `step`.
Paths are root-relative POSIX labels; external explicit shop files use stable
`external/{kind}/{filename}` labels instead of machine-specific absolute roots.
The manifest STEP digest is also recorded separately; unknown does not become a
fabricated digest. An absent policy fallback has no file-byte digest.

Citations are evidence pointers, not operative assets loaded at runtime. HTML
and approval records are not inputs to their own report hash. A content/format
change to an input resets its digest even when it seems semantically identical.
`explain` verifies report integrity before selecting rows, then validates every
matching finding before emitting any finding logs or output. Selected findings
require string `rule`, `subject`, and `message`, a supported `status`, an object
`numbers`, and a list of strings `cite`. Missing or malformed selected fields
exit 3 with `Cannot explain report`, even when the report hash is valid.
A matching hash is not proof of machining safety or source truth.
The CLI also emits `bundle_binding:inputs`: unknown when the manifest STEP
digest is unknown, otherwise pass, with the full input records as evidence.
Its exact messages are `The part model is not bound to verified STEP bytes.`
and `The part model and every operative input are bound to the report.`
Citation: PLAN §5 input-bundle binding. This is digest bookkeeping, not kernel
verification or proof that an author-supplied digest came from a certified CAD
export. It blocks eligibility only if policy requires it.

## Kernel renders

When `prechips traveler` runs and the FreeCAD job returns `render_png_base64`
for a setup, the decoded bytes are written as `setup-S<n>.png` beside
`traveler.html` (`n` is the setup's 1-based authored position, not its id),
`report.json` gains `renders.<setup id> = {path, sha256, fixture, scene}` and
the same `{path, sha256}` record is added to `inputs` under `render:<setup id>`.
The render is therefore part of the hashed bundle: a different PNG changes
the report hash and stales any approval, exactly like an edited TOML.
`fixture` is `"modeled"` when the kernel reports `fixture_rendered = true`
for that setup (fixture placed, every drawn component exact, no debts) and
`"unresolved"` otherwise; `scene` is the kernel's `render_scene` object
verbatim — `fixture_kind` (the inventory holding kind), `jaws` (`absent` /
`exact` / `lateral_undeclared` / `not_applicable`), `parallels` (`absent` /
`exact` / `not_modelled`), `components` (`{name, role, exact}` per drawn
solid) and `debts` (a list of sentences naming what the picture does not
establish), empty `{}` when the kernel returned none.
Bytes that are not a PNG signature are
a prechips failure (exit 1), not bad input. `check` records the same
`renders` / `render:<setup id>` entries (its report hash matches the
traveler's) but writes only `report.json`; the PNG file appears only with
`traveler`. The PNG filenames are preflighted with
the other outputs: an input at `setup-S1.png` is a collision (exit 3).
Both verbs remove prior setup images not returned by the current run, including
images from a longer route or an unavailable kernel. `check` also removes a
same-named PNG unless its bytes match the current render, and removes any
prior `traveler.html` so no old sheet accompanies the new report. It does not
create PNGs or a sheet. Replacement and removal share the report transaction;
a refusal restores every prior output, even if a stale target has already
disappeared. No stale fixture image survives a successful run.
The render is a deterministic software drawing of kernel geometry, 1600 pixels
wide and 1000 tall plus any holding detail bands below (`scene.height_px`),
with an engine-bundled bitmap font and the engine's own PNG encoder. No host
font, clock, image service or machine-specific metadata participates in the
bytes. Lathe views put the headstock/chuck on the left, the tailstock on the
right and setup +Z along the spindle to the right; mills use setup-frame
isometric views, and custom plates use a plan view. Labels identify the setup
axes, Z0, named datums, jaws, supports and selected cutter approach. The amber
hatch is **entry stock minus this setup's derived exit stock**, not a finished
part substituted for arriving material or a simulated toolpath. If the exit
stock or a cutter cannot be established, a plain `render_debts` sentence says
what is not shown; that display debt never changes a rule verdict.
Lathe material is drawn in meridian section so the removed annulus cannot
conceal the retained core; the jaw-end detail magnifies nearby shoulders and
reliefs without hiding the full stock length in the main view. Mill/custom
views overlay a dashed **nominal part outline**, including behind arriving
stock, solely to locate the drawing relative to pads, pins and coordinate keys.
That outline is never a claim that the supply already has the finished shape.
Selected cutters use the traveler's short human tool names. A separate feed
arrow, when the plan declares its direction, is a direction symbol, not a path.
An unresolved saw cut plane produces a plain STOP annotation and retains its
downstream stock debt; it never prevents other geometry facts being returned.
The final PNG layout checks every normalized bitmap-text line, including axes,
coordinate badges, inset headings, dimensions, legends and setup notes. Rounded
line bounds must stay 8 pixels inside the canvas and at least 4 pixels apart,
and every line prints at body size (bitmap scale 3: 21-pixel caps, about 7 pt on
Letter); any collision, clipping or undersized text raises a render error.
Callout lanes rebalance between sides and tighten their leading rather than
shrinking type; footers grow to hold their notes. A lane leader whose
horizontal elbow would run along an axis through another callout's point is
drawn straight instead, and an end label stays in the lane on its own end's
side. Footer height is reserved before fitting the setup view, so dense legends
never compress into overlapping rows. These checks do not alter geometry or
turn unresolved machining facts into passes. A checked, posed chuck front not
parallel to setup Z has no single jaw-front Z; `scene.jaw_front_oblique`
records that geometric distinction without a printed note or a missing-datum
warning.
Setup notes derive from every declared op, including bench ones the kernel does
not cut: a setup with no machine-cutting action lists its actions (`No machine
cutting: op 10 deburr, op 20 coating, op 30 inspect.`). "No material removed in
this setup." prints only when the kernel derives no removed volume and no op
deburrs. The notes never repeat the selected tool and op: the tool and op tables
name them and the picture labels the primary tool; a setup with no notes prints
no SETUP NOTES heading.


`scene` additionally records `view`, `width_px`, `height_px`, plain-language
`shows` / `legend`, `render_debts`, `primary_op`, and sparse `waypoints`.
Mill keys are `{label, op, xy}` in setup mm; axial lathe keys use `xz`, whose
X is the declared radius/diameter DRO target and whose Z is the table station.
The same `P1`, `P2`, … keys annotate the profile inset and traveler coordinate
rows. Both mirrored sides remain explicit. Dense mill sketches use separate
operation panels so repeated corners keep every coordinate key legible.
Shallow contour panels label their Y-only graphic magnification (`Y EXAG X…`);
the declared coordinate values, waypoint identities and setup-view axes do not
change. The faint nominal underlay uses that same labelled panel scale.
Direction arrows are spaced along the drawn path, including subpixel chords,
rather than disappearing when an arc is sampled finely.
Lathe inset paths and their keys locate the nominal finished surface; they
are not compensated tool-tip feed targets. If the contour table also gives
tool X/Z columns, those columns control the feed, not the drawn surface line.
Numbered custom-clamp badges follow authored `hold.clamp_order`, not an order
inferred from prose; an explicit empty list means no accessory tightening
actions. Setups without a cutting op show no invented cutter.
Fixture construction primitives remain visible as geometry and individually
named in `scene.components`; printed callouts group body/support hardware so
bolt and shim details do not force the pad, pin and clamp labels into tiny text.
Custom-fixture badge boxes remain outside the projected stock, fixture plate,
other fixture components and nominal part outline, in rows above and below it in
the points' x order so their leaders never cross; leaders return to the
unchanged physical component centres. A badged clamp or pad group's lane entry
is the badges' key and draws no leader of its own. A trusted, explicitly labelled fixture
void gets a shop-caption leader at its posed centre, with `{name, label, role,
center_mm}` recorded separately in `scene.fixture_detail_labels`. These
annotations do not create solids, change geometry checks or resolve measurement
debt.

Exact posed fixture solids remain the only basis for `fixture = "modeled"`.
Dashed table, vise-body and machine-context outlines are clearly marked
schematic and do not enter geometry checks. A stop is drawn from a selected
inventory fixture and declared `stop_pose`, never guessed from a holding note.
Lathe views also show the right-side tailstock context when no centre is drawn;
that symbol does not claim a selected or verified support.
Unknown incoming stock produces no figure. See
[geometry rules](rules-geometry.md#renders).


## Eligibility and approval

Any error wins (exit 2). Required warn/unknown/unsupported or a missing required
rule/subject yields 4; an explicitly unknown required policy also yields 4.
Otherwise the report has exit 0 and `verification = "checked"`.
The implemented gate does not block required `info` or `not_applicable`. Without
approval the traveler still prints `PLANNED — NOT APPROVED`.
No hash prints on the sheet. `traveler.html` carries the full report hash and the
prechips version in `<meta name="prechips-report">` / `<meta name="prechips-version">`
for tools; they are a lookup, never the approval's binding.
The renderer additionally requires the normalized approval `approved = true`,
no approval warnings, a lowercase 64-hex report hash, and first-article text
other than literal `unknown` (case-insensitive). These are renderer guards, not
extra keys to write in the TOML approval record.


Supply `--approval approvals.toml`. A normalized record permits only `hash`,
`first_article`, and optional `inputs`:

```toml
hash = "<full current report hash>"
first_article = "<actual logbook/evidence reference from the cut first article>"

[inputs]
plan = "<prior SHA-256>"
features = { sha256 = "<prior SHA-256>" }
```

Alternatively use a history of array tables:

```toml
[[approvals]]
hash = "<full report hash>"
first_article = "<actual evidence reference>"

[approvals.inputs]
plan = "<prior SHA-256>"
```

These placeholder strings illustrate shape, not supplied approval evidence.
`inputs` can contain digest strings or tables carrying `sha256` (report-style
path metadata may accompany a digest table). The parser selects the first
record with the exact current hash; if none match it uses the last record to
explain changed inputs. `hash` and `first_article` must be strings. Only a full
hash match, a **nonblank** first-article string, and an eligible report remove
PLANNED. Neither a matching short id nor a stale record nor an empty evidence
string suffices. Approval parsing does not authenticate evidence or perform
the first article; the shop owns its truth.

Stale record warning: `Approval no longer matches: {changed input names} changed.
Repeat the first article.` Only input names declared in the prior record and
present in the current report are compared; an omitted prior input is never
named as changed. Digest strings and digest tables follow the same comparison.
The warning names `the operative bundle` when prior `inputs` is absent or
empty, there are no input names in common, or all compared digests are unchanged
despite the stale report hash. A matching record for an ineligible report warns:
`The report still has unresolved shop-required checks; approval cannot waive them.`
Approval never changes the checker exit. `check` also parses/warns on approval,
but does not produce a sheet.

## Output safety

All input bundles and output targets are preflighted before evaluation/writing.
Manifest, plan-declared shop files and STEP assets must stay inside the bundle
root. Explicit CLI/environment shop paths may be external. `--out` may be an
authored directory anywhere; every
fixed output filename must resolve inside it. No output can alias an input by
resolved path or hard link, escape by symlink, or name a directory. The output
root cannot name a file. Approval files are included in collision protection.
Existing regular output files are replaced. Each output is first written in
full to a hidden temporary beside its target (`.<name>.<random>.tmp`), and no
target is replaced or removed until every write is staged. The prior bytes of
any earlier changed target are kept until the last change lands. If the
filesystem refuses the directory, staged write, replacement or stale-image
removal, the run exits 3. Temporaries are removed and every changed target
gets its prior bytes back,
or is removed if it is new. A failed run therefore never leaves a new
`report.json` next to an old `traveler.html`. An output directory created for
the run may remain, empty. This does not cover a process kill between the two
replacements, or a failure of the restoring rename itself. That second error
exits 1, and the prior bytes stay in the temporary backup.

Exit 3 covers bad input, output preflight and output-file writes. Any other
exception is a prechips bug, not bad input: for example, a rule that raises or
that returns duplicate subjects. It is outside the 0/2/3/4 exit contract and
gives Python's ordinary traceback and exit 1. Telemetry still flushes. Generation
finishes before any output is staged, and a staged write rolls back on any
exception, so such a failure writes no output. A failure writing stdout after
the files are in place is also exit 1.
No verb reads expected fixtures as runtime answers.

## Generated traveler

The traveler is the shop-floor product: Letter portrait, written for a machinist
at the machine. A job page opens with the part, drawing number, revision (or
`REV NOT CONFIRMED`, which is also a STOP line) and the `PLANNED` banner, then
**JOB STATUS** (STOP / CAUTION / not-verified boxes; a setup with its own STOP
items is named here too, so the job page never says "no stops" over a stopped
setup; then a `Not ready to run` line when the plan check has not passed, or the
count of checks not verified — the checker's own pass is not printed — then,
always, the approval state matching the banner in shop words — `NOT APPROVED:`
with what the approval record holds: no first article recorded, one made to a
different plan or drawing (both: the first part made is the first article), or
one recorded for this plan while it still has open items, which approval cannot
waive — and each `Before S1:` stock prerequisite, such as `obtain the stock —
not on hand`), the drawing material and finish, a one-line speeds/feeds source,
the legend `† example fixture dimensions (plausible, not measured): confirm
before making` when a SHOP-MADE FIXTURE row carries the mark, the DRO manual
named once, the `DRO resolution:` of each routed machine (its inventory
`resolution`, or the default grid said as such; a lathe adds whether X reads
diameter or radius), **STOCK AND ROUTE** (stock size at the DRO resolution of
the setup that receives that stock, supply notes and a setup → machine → holding
table, machines by display name: an inventory `name`, a maker's model number,
or else the machine kind, never an inventory slug) and **DRAWING
REQUIREMENTS** (feature → limits, ending with the drawing's edge break printed
once for the job as `all edges`; two features carrying the same cited drawing
dimension, band and nominal alike, print it once on one row naming both,
`strap faces / strap (datum B)`; a stock thickness prints only when no feature
carries a thickness limit). Authored values keep their digits (a 1.9875 mm
pin, a 0.0254 mm runout limit); only computed numbers are cut to DRO
resolution.

Each setup then prints as one **front sheet** to run the setup from, followed
by attached sheets the front sheet points to. Every sheet starts on a new
page and its heading repeats the setup id and `sheet N of M`. All text is at
least 8 pt.

The front sheet is one physical sheet. When the op table does not fit on the
front page it ends with `Operations continue on reverse, op 50` and continues
on the back under the op column headings; a setup with few ops has a
single-page front sheet.

Print the whole file double-sided. A small inline script in `traveler.html`
(the same bytes every run; it changes only the page in the browser) lays out
every sheet on load and again just before printing. It measures the sheet at the
printed width, places each page break itself (headings and a table's caption
stay with what follows, also when the heading opens a sheet and its first block
is a row of contours; the sign-off stays with the last op row; a table that
runs over is split into a copy with the same column headings, leaving at least
three rows on each page: rows carry over to the next page, and a table too short
for that moves whole with its heading, never shrinking the type; a table other
than the op table whose last page would hold under half its rows splits at its
middle instead when the rest then fits on one page, so its closing rows never
stand alone; a heading's lead-in line stays with the block it introduces),
opens every page after a sheet's first with `SETUP S2 — sheet 3 (continued) ·
page 2 of 3`, and
adds a `This side intentionally blank — SETUP S2 sheet 1 back` page after any
sheet with an odd page count, the job page included. Every sheet therefore
starts on a front side, and a single-page front sheet has a blank back. Contour
blocks print in rows of three under the script and in three newspaper columns
without it; a side-by-side row too tall for one page (contours, a lathe op's
rough and finish tables, the hold picture beside its steps) is stacked before
it is split, so every page it runs over is counted. With scripts disabled the
same content prints without padding (sheets may then start on a back side, so
print single-sided) and a running
op table repeats `SETUP S2 — sheet 1 (continued): operations` with its column
headings.

Front sheet (sheet 1), in this order:

1. Title and status boxes. *STOP — do not run until resolved* lists one plain
   line per real problem with the ops it applies to (`Op 20 — tool or holder
   hits the part or the holding`); repeats are collapsed. *Not verified by the
   planner — confirm at the machine* names the unproved topics with their ops.
   Errors never print as `?`; unknowns never read as passes.
2. **HOLD**: a numbered clamping sequence (mount, supports, grip, stop,
   tighten, then the authored notes) at full width; the holding picture is on
   sheet 2 at a readable size. Without a render the front sheet prints `NO
   PICTURE — the holding is not modelled; set up from the HOLD steps.` Below
   it, a small table of grip length, stickout, jaw-front Z and, on a lathe,
   centre tip Z and quill extension. Pose vectors and planner field names are
   not printed.
3. Coolant (not on bench setups). The drawing's edge break prints once on the
   job page; a setup whose `deburr_mm` differs from it prints its own limit
   with the author's reason (`Break edges 0.100 mm max in this setup, not the
   drawing's 0.25: small socket edge break keeps the bonded length.`). Then a
   **PURCHASED TOOLING / RECEIPT CHECK** table for each bought-finished item
   with receipt checks ([inventory](inventory.md#purchased-tooling)) that this
   setup is the first to use: what is bought, then check, gauge and accept
   limit per row (an unresolved row prints `STOP:` and why); later setups using
   it print one line naming that table's sheet.
4. **TOOLS FOR THIS SETUP**: `T#`, tool, insert / size / material (with the
   shank, `shank Ø12.700`, when it differs from the cutting diameter), holder or
   QCTP station and the ops that use it. Op rows carry only the `T#`.
5. **DRO ZERO** (not on bench setups — a machine of kind `bench` or `manual`
   running only fit and inspect ops has no spindle, DRO or axes — nor on a saw
   cut-off setup, located by the cut plane in its op row): positive
   directions, then one row per axis — what to touch
   or pick up (tool, side, paper or edge-finder radius), the Axis Set value, a
   check jog, the value the display must read and the value it would read if
   the axis were reversed — plus re-indicate and tool-change touch-offs (several
   changes to one touch print once, naming their ops: `Tool changes before ops
   20, 30 and 40: install the op's tool (the T number in its row), then …`; the
   tools themselves stay in the TOOLS table and the op rows). On a
   mill, an X or Y check jog from a side pickup would carry the finder over the
   work, so the sheet prints the check as steps: raise Z only, until the finder
   or indicator clears the work and everything clamped to it (checked by eye
   across the top); jog the table the printed distance and read it; jog back
   until the display shows the Axis Set value again, then lower. The picked-up
   value is never set again. The steps' lead-in line never ends a page without
   them. A lathe check jogs away from the work and has no raise step. A lathe X
   set from a trial cut (the zero's or a tool change's) reads `take a light trial
   cut, withdraw along Z without moving X, stop the spindle, measure the
   diameter`. An edge-finder pick-up row names the **EDGE FINDER** box, which
   prints once per finder and mill, in the DRO ZERO of the first setup picking
   up with it on that mill ([inventory](inventory.md#edge-finder)): the speed
   bands where the mill's ranges turn the finder (never a speed between them),
   how the contact shows, and the offset — half the tip Ø, Axis Set edge − r
   from the − side and edge + r from the + side; a later setup on the same mill
   names `EDGE FINDER box, Setup S1 sheet 1`. A missing or unknown finder or
   spindle fact prints `STOP:`.
6. **OPERATIONS**: op, action with depth of cut, feature, `T#` tool, rpm, feed,
   Z target, cut direction and `limit: gauge` inspection. A lathe table with any
   op measured in the chuck adds to its heading `measure only with the spindle
   stopped and the tool withdrawn`. Lathe feed prints as
   `mm/rev` with the resulting `mm/min` in brackets; mill and saw feeds print in
   `mm/min`. Crash-relevant numbers (jaw front within 3 mm of a tool stop, dead
   centre at the work end, tool tip within 3 mm of the jaw top) and per-op STOP
   or CAUTION findings print as boxed lines under the op row, followed by the
   op's own note (and the tip-depth derivation) on its own line and, for a
   contour op, `See contour table on S2 sheet 3`. A blade relief's Z cell gives
   each plunge's corner Z and the diameter it plunges to; the groove's extent
   prints only where it differs from the row's own Z window, and the diameter's
   drawing limits only when the inspection cell does not carry them. A number
   printed at fewer decimals than it holds rounds half-way values up (3.175 at
   two places is 3.18). An inspection procedure is
   cited as `[S2 sheet 2 note 1]`. An op row with its boxed lines and note
   never splits across the front and back. A setup whose ops are all bench
   steps (`inspect`, `deburr`, `coating`, `fit`, `scribe`, `release`, hand
   finishing) prints **ASSEMBLY / FINISHING** instead: step, feature, material /
   consumable (a coating's in-house consumable or outside service), action (the
   op's own instruction, else its action) and inspection, with no empty
   machining columns.
7. The sign-off line, after the last op row (on the back when the ops run
   over).

Sheet 2, titled by what it carries (*holding picture, clearance, feature map
and inspection notes*):

1. The holding picture at full page width with its caption (`Setup S2 — part
   as it arrives from Setup S1, held in the 6 in 3-jaw chuck.`; the key is
   drawn in the picture) and its `NOT SHOWN:` lines. The image is referenced by
   relative filename.
2. **CLEARANCE** (not on bench or saw cut-off setups), machine specific. A lathe shows chuck
   Ø against swing, work Ø against swing over the cross-slide, length against
   between-centres, quill extension and the jaw-front distance to the closest
   tool stop. A mill shows one line for the tallest spindle-to-table stack
   (with the 25 mm tool-change room) against the room available, one for X/Y
   table travel, one `Not computed — check at the machine` line for uncomputed
   items, then a table: op, tool, closest obstacle, clearance mm, action. Each
   cutting op's row takes the smallest known of its headroom margin, its DRO tip
   over the jaw tops, the holder face above the highest stock beside the tool
   (`projection_mm` less the reach from that stock's DRO surface Z to the op's
   printed tip) and every `clearances` entry of its reach finding. A negative
   clearance or a holder past the flute that hits a wall is a STOP; an unknown one
   or an unproven holder wall clearance is a check-at-the-machine action; a jaw
   clearance within 3 mm asks for a hand-fed approach. Ops with the same tool,
   obstacle, clearance and action share a row.
3. **FEATURE MAP**. Lathe: each surface the setup cuts (one it only inspects,
   such as an as-supplied diameter, has no size to turn to and is left off):
   feature, the drawing's Ø limits (`—` for a process
   size such as a joint spigot), the X turned to as the DRO displays it (`turn to
   Ø` on a diameter display, `turn to X (radius)` on a radius one; `?` and a STOP
   when `dro.radius_mode` is not stated), and the Z the setup's cuts start
   and end at. Mill: feature, the reference point the X/Y/Z stand on (hole or boss
   axis, arc centre, face; at the entry or exit face, or on the Z0 surface), then
   X / Y / Z. A face square to setup Z is left off (its centre is no DRO stop and
   its Z is the op row's) unless it carries an aim; a map with no row left is not
   printed. An aimed target adds one line: where to machine it, its offset from
   the drawing nominal and the band to inspect it to. Feature locations, not tool
   tips.
4. **INSPECTION NOTES**: numbered inspection procedures, each starting with its
   setup and op (`S2 op 30: …`). A procedure that works its readings through two
   or more calculation lines is not a note but a worksheet on a sheet of its own
   (see below).

Sheet 3, *contours* (only when the setup has contour ops): **CONTOURS**, one
block per contour op titled with its setup, op, tool and direction (`S2 op 50
— top edge · T2 …`), the table at DRO precision and, when the render supplies
`scene.waypoints`, a `P` column keyed to the labels drawn in the picture. A
missing tool prints `STOP … tool not selected; do not run` instead of a table;
a lathe dome table prints the imaginary-tip `tool X (Ø)` / `tool Z` columns,
read on the same X display as `surface X (Ø)` (`radius` in radius mode), when
the nose compensation is known; otherwise it says the nose radius compensation
is not computed. A table the kernel clipped at the op's stock-removal bounds
names the printed point it starts or stops at (`stops at P7: the stock past it
is outside this op's area`). Long contour tables may run onto more pages
("paper is cheap"); every block still names its setup. A move number and each
depth level's completion box with its `level k of N` print whole on one line,
however narrow the block.

Worksheets, one sheet each after the contours (`SETUP S11 — sheet 4 of 4:
worksheet, S11 op 110 angularity Ø`): the numbered steps, each naming the reading
it takes (`[rJ1]`), a READINGS table (step, reading, a blank value cell) and the
calculation lines with their blanks.

The job page and each front sheet end with the sign-off line. Setup
coordinates, Z targets and DRO values print at the DRO's display
precision (2 decimals in mm, 4 in inches); drawing limits keep the drawing's
precision. Plan text is cleaned for the bench: author's-choice tags, face ids,
inventory slugs, frame names and hashes are dropped, and frame `T1` reads as
`Setup S1 zero`. Rule ids, source paths, uncertainty detail and hashes
stay in `report.json` (and the page's machine-readable meta tags). Print CSS is
not a physical dry run, and presentation never changes PLANNED readiness.

The printed result can be given a blind senior-machinist review with
`scripts/machinist_review.py` (see README, "Machinist review of a traveler").
That script prints this HTML to Letter pages with headless Chrome, so the
duplex padding above runs, and asks a reviewer from the other model family to
judge every page against two tests: no questions, and nothing the operator
doesn't need. Speeds, feeds, depths of cut, tap drills and reamer allowances
are compared with Machinery's Handbook pages that the script embeds in the
prompt from a local, never-vendored handbook corpus (`--handbook` or
`PRECHIPS_HANDBOOK_DIR`; page numbers in `scripts/prompts/handbook_refs.toml`),
and findings cite the table and printed page. Without a handbook the review
runs from memory and records that. It is a developer tool that calls a hosted
model. It is not part of `prechips check` or `traveler`, and it does not change
their offline contract.


## Telemetry and console

The OpenTelemetry API, SDK and OTLP HTTP/gRPC exporters require `>=1.39.1`.
The API is a direct dependency because this module imports its tracing and log
record types. Logs use the API `LogRecord` form of `Logger.emit`, with exception
details carried as standard attributes, rather than a newer `exception` keyword.
The telemetry suite passes with all four packages pinned to `1.39.1`, including
local HTTP and gRPC export with correlated finding context.

Every invocation has a `prechips.<verb>` root span (initial usage may be named
`prechips.usage` when a global flag comes first). Inputs use `input.load`, outputs
`output.write`, evaluations `rule.<name>` and finding records child spans. The
FreeCAD batch execution and per-job cache lookup run under one `kernel.geometry`
span. Native timing is diagnostic only: it never enters normalized job/cache-key
inputs, findings, reports, report hashes or render bytes. The host requests it
with `{"jobs": [...], "timing": true}`; native requests without that opt-in retain
their untimed output contract.

The native batch response has `timing = {wall_ms, cpu_ms}`. Each job result has
its own top-level `timing = {wall_ms, cpu_ms, setups}`, where `setups` maps setup
ids to `{wall_ms, cpu_ms, phases, ops}`. `phases` holds measured `fixture`,
`chuck_walls` (radial clamp-wall sampling), `stock_states` (the one op-order
pass deriving each op's before-op stock), `render` and `stock_output` (final
wall/cap checks on the end stock) intervals when those paths run; `ops` maps operation subjects to
`{wall_ms, cpu_ms}`. All measurements are milliseconds rounded to six decimal
places: elapsed time uses a monotonic clock, while CPU time uses the FreeCAD
process CPU clock, not host CPU or machine-wide utilization. Setup totals include
their phases and operations; do not add those nested measurements to the totals.
Batch measurements include orchestration and are not a sum of job measurements.

The host exports `kernel.setup` spans with `setup_id`, and nested `kernel.op`
spans with both `setup_id` and `subject`. Freshly executed work carries measured
`kernel.wall_ms` / `kernel.cpu_ms`, `kernel.timing_source = "execution"` and
`kernel.executed = true`. Setup phases use `kernel.<phase>.wall_ms` /
`kernel.<phase>.cpu_ms`. These short host-side spans export native facts after
the response arrives: their span timestamps are not backdated and their OTel
durations do not stand in for native execution time.

Successful cache entries retain the original job timing facts unchanged. On a
disk-cache hit, setup/operation spans instead carry `kernel.original_wall_ms` /
`kernel.original_cpu_ms`, `kernel.timing_source = "cache"` and
`kernel.executed = false`; phase attributes likewise use
`kernel.<phase>.original_wall_ms` / `original_cpu_ms`. They report the original
computation, **not CPU spent replaying the cache**. Old entries without timing
emit no setup/operation timing spans. Identical jobs within a batch emit facts
once, not once per consuming bundle; an already-populated bundle memo emits no
new geometry span.

`kernel.geometry` records unique `kernel.executed_jobs` / `kernel.cached_jobs`
counts and provenance (`kernel.timing_source` is `execution`, `cache`, `mixed`,
or `none` for identified-kernel requests with no usable jobs). `kernel.executed`
indicates whether a native batch was invoked. Actual fresh batch measurements
are `kernel.batch.wall_ms` / `kernel.batch.cpu_ms`; a cache-only call has no such
attributes. The geometry span's own elapsed duration includes host cache lookup
and subprocess overhead, not just the measured native work.

Collision sampling reuses only exact, immutable query recipes; it does not round
poses or stop after the first hit. Every placed sample still contributes to the
full hit count. Finished-face references are a per-operation, per-tool-kind set
union: once a label is proven, later poses need not rediscover it. Partial new
reference sets stay local to that monotonically growing union; a stock-region
cache shared by operations stores only complete reference sets. Pointed cutters
keep their actual cone/body geometry in stock and fixture intersections.
A cylinder touching no stock-face bound has constant material membership. Its
midpoint can be rejected beyond the tolerance-grown stock envelope; all other
midpoints retain the native material classifier and the existing shape type.
A part-hit count may also skip the boolean when an interior ball is certified:
the native classifier puts its centre inside the stock, rigorous lower bounds
clear it of every boundary face, and it lies strictly inside the exact query
cylinder, so its volume exceeds the hit threshold. The certificate only counts
hits: it substitutes no shape and never proves a miss, and every unsupported
proof falls back to the native boolean. A skipped boolean cannot raise, but every
boolean still run keeps its original errors, never caught or suppressed. Pointed
cutters never use it and their solid queries stay uncached; a hit skips the
intersection only when no finished face outside the known reference union has
positive contact area with that query cylinder.

When no kernel is found, every geometry finding carries
`numbers.kernel_unavailable = true`; the console prints that identical
kernel-naming `?` sentence once per run unless `--verbose` shows the full
table, while the report and the OTel records keep every finding.
Records carry rule, subject, status, numbers and citations. The same Python
logging records feed OTel and Rich stderr, so console and exported facts agree.
`--verbose` renders the full finding table; ordinary stderr renders unresolved
and error glyphs. Non-TTY/`NO_COLOR` disables color, not the glyphs.

Resource identity: `service.name=prechips`, package `service.version`, optional
`service.namespace` from `OTEL_SERVICE_NAMESPACE`. Valid W3C `TRACEPARENT` and
optional `TRACESTATE` continue the parent context. No endpoint means no exporter,
collector discovery, network request or missing-endpoint warning.
Each configure-after-flush invocation starts a fresh root/span pipeline; a live
session is reused only until its idempotent flush closes it. A known STEP digest
cannot replace the actual referenced bytes: the loader requires and hashes them.

Standard `OTEL_EXPORTER_OTLP_ENDPOINT`/`PROTOCOL` configure both signals;
signal-specific `OTEL_EXPORTER_OTLP_TRACES_*` and `OTEL_EXPORTER_OTLP_LOGS_*`
override them. Protocol is `http/protobuf` (default) or `grpc`; SDK headers/TLS
follow standard exporter environment variables. Timeout is milliseconds in the
environment, converted to exporter seconds. Batch processors flush/shut down on
exit, including bad input. Export is optional. If
the protocol is unsupported, or the timeout is not a positive number of
milliseconds, export is disabled for both signals in that invocation. Stderr gets
one `! OTLP export disabled: …` warning naming the variable. The exit, report and
sheet are those of an unconfigured run.

See [AGENTS.md](../AGENTS.md) for local collector and farm acceptance procedures.
Local exporter tests do not substitute for a real parented farm run observed in
App Insights by `operation_Id`. That live acceptance and physical print/dry-run
rehearsal remain **unobserved/pending**.
