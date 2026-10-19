# Report binding, approval, output safety and telemetry

Use this reference to interpret `report.json`, its generated images, approval
records, printable setup sheets and diagnostic output. A checked report records
the implemented checks against one input bundle. It does not certify machining
safety, source truth, physical setup or first-article acceptance.

For a first run, use the [quickstart](manual/quickstart.md),
[tutorial](manual/tutorial.md) or [worked demonstration](manual/demo.md). For
command syntax and recovery, use the [CLI catalog](reference/cli.md),
[troubleshooting guide](manual/troubleshooting.md) and [FAQ](manual/faq.md).
The [Python catalog](reference/python-api.md) describes callable implementation
interfaces and their support boundary. Module ownership and contributor workflows
belong in [architecture](internals/architecture.md) and
[development](internals/development.md).

On this page:

- [Canonical report](#canonical-report)
- [Kernel renders](#kernel-renders)
- [Eligibility and approval](#eligibility-and-approval)
- [Output safety](#output-safety)
- [Generated traveler](#generated-traveler)
- [Telemetry and console](#telemetry-and-console)

## Canonical report

### Fields and findings

`report.json` contains these root fields:

| Field | Contract |
| --- | --- |
| `expected_exit` | The checker readiness result: 0, 2 or 4. See [eligibility](#eligibility-and-approval). |
| `findings` | Findings sorted lexicographically by `(rule, subject)`. |
| `inputs` | Path labels and exact file-byte SHA-256 digests for operative inputs and generated render assets. |
| `prechips_version` | The package version. |
| `rules_version` | The operative rule catalogue, currently `"m5-rev12"`. |
| `step_sha256` | The manifest's STEP digest, or `"unknown"`. |
| `verification` | `"checked"` when `expected_exit` is 0; `"planned"` otherwise. |
| `hash` | The canonical report digest described below. |
| `renders` | Present only when the kernel returned a setup render. |

Each finding has `rule`, `subject`, `status`, `numbers`, `cite` and `message`.
The serialized field is `message`, not `sentence`; there is no separate severity
field. No clock timestamp enters the report.

A finding's `numbers.measurements` identifies the exact facts whose measurement
would resolve it, including a set member or tool/holder pair where applicable.
Entries carry structured category, identity and canonical field parts.
`tools --measure` returns their sorted, deduplicated union plus host job
measurement debts over plans selected with `--plan`, or its fixed default
example set. Plan-local entries carry a plan prefix; inventory entries carry
an inventory-path prefix when multiple inventories are selected. This host-only
checklist does not run FreeCAD. See the [CLI catalog](reference/cli.md) for the
default plans and scoping rules.

The current catalogue requires fact-local measurement provenance: a fact is
measured only when its own `measured.status = "measured"` has complete
`by`/`date`/`instrument` metadata. `assumed`, `illustrative` and omitted status
remain debt. The checker never infers trust from the text of `by`.

The catalogue also includes the M5 bed-height vise stack, per-pair tool
projection, approach/floor-aware envelope, spindle-nose Z travel, unpadded hole
centres, one `envelope` machine block and fact-local trust, with no
`holder_stack` rule. It includes dividing-head/child-centre fixes, native saw
cut-off and hash-bound setup renders. The nine M4 geometry rules are a historical
catalogue grouping; the [geometry reference](rules-geometry.md) lists the current
rules. The examples-complete contracts include identity-keyed tool selection,
shop-made make operations, face aims, whole-tool clearance with guide stops and
op-named picture cuts, and one-fact consistency across tables and pictures.

Changing the operative catalogue changes the bound report and invalidates prior
approvals. Reports from earlier catalogues, including `m5-rev10` and `m5-rev11`,
need regeneration and approval against the current report before reuse.

### Canonical bytes and input binding

Canonical bytes are UTF-8 JSON with sorted keys, two-space indentation,
`ensure_ascii=False`, finite numbers only and one final LF. `hash` is the SHA-256
of that same canonical serialization after removing only the root `hash` member,
including the final LF.

Every operative TOML/STEP asset read by the run has its exact file-byte SHA-256.
Input keys include `plan`, `features`, `inventory`, `shop_policy`, `cutting_data`
and referenced assets such as `step`. Paths are root-relative POSIX labels.
Explicit external shop files use stable `external/{kind}/{filename}` labels
instead of machine-specific absolute roots. The manifest STEP digest is also
recorded separately; unknown does not become a fabricated digest. An absent
policy fallback has no file-byte digest.

Citations point to evidence; they are not operative assets fetched at runtime.
HTML and approval records are not inputs to their own report hash. Any input
content or format change resets its digest, even if it appears semantically
identical. A known STEP digest cannot replace the actual referenced bytes: the
loader requires and hashes them.

The CLI adds `bundle_binding:inputs`, with the full input records as evidence.
It is unknown when the manifest STEP digest is unknown and pass otherwise. Its
exact messages are `The part model is not bound to verified STEP bytes.` and
`The part model and every operative input are bound to the report.` The citation
is PLAN §5 input-bundle binding. This is digest bookkeeping, not kernel
verification or proof that an author-supplied digest came from a certified CAD
export. This finding blocks eligibility only when policy requires it.

### Explaining a saved report

`explain` verifies report integrity before selecting rows, then validates every
matching finding before emitting any finding logs or output. Selected findings
need string `rule`, `subject` and `message` fields, a supported `status`, an object
`numbers` and a list of strings `cite`. Missing or malformed selected fields exit
3 with `Cannot explain report`, even when the report hash is valid. A matching
hash does not prove machining safety or source truth.

The canonical encoder, asset validation and report builder are in
[`report.py`](../src/prechips/report.py). See the
[CLI catalog](reference/cli.md) for selection and output syntax.

## Kernel renders

### Asset names and approval binding

When the FreeCAD job returns `render_png_base64` for a setup, `traveler` decodes
it to `setup-S<n>.png` beside `traveler.html`. Here `n` is the setup's 1-based
authored position, not its id. The report gains
`renders.<setup id> = {path, sha256, fixture, scene}`, and `inputs` gains the same
`{path, sha256}` record under `render:<setup id>`. A changed PNG changes the
report hash and stales approval, just as an edited TOML does.

`fixture` is `"modeled"` only when the kernel reports `fixture_rendered = true`:
the fixture is placed, every drawn component is exact and there are no fixture
debts. Otherwise it is `"unresolved"`. `scene` contains the kernel's
`render_scene` object verbatim, or `{}` if none was returned. Its fixture facts
include:

| Field | Meaning |
| --- | --- |
| `fixture_kind` | The inventory holding kind. |
| `jaws` | `absent`, `exact`, `lateral_undeclared` or `not_applicable`. |
| `parallels` | `absent`, `exact` or `not_modelled`. |
| `components` | `{name, role, exact}` for each drawn solid. |
| `debts` | Sentences naming what the fixture picture does not establish. |

`check` records the same `renders` and `render:<setup id>` entries, so its report
hash matches `traveler` for the same evaluated bundle. It writes only
`report.json`; it does not create a PNG or a sheet.

### Inspection sketches

An inspect operation's set-up sketches, declared through
[`inspection_views`](plan.md), return as `inspection_pngs_base64` keyed
`<op>:<requirement>`. Their filenames are
`setup-S<n>-op<op>-<requirement>.png`.
`renders.<setup id>.inspections` maps each key to `{path, sha256, scene}`.
The corresponding `inputs` entry, `render:<setup id>:<op>:<requirement>`, remains
`{path, sha256}`. Each sketch therefore binds to approval like the setup picture.

Native `inspection_scenes` has exactly the same keys as `inspection_pngs_base64`.
Each scene supplies the actual `width_px`, `height_px` and ordered `print_panels`.
Each inspection panel has `{top_px, height_px, role, label, view_ordinal}`:

- `role` is `inspection`.
- `label` is the exact authored view title.
- `view_ordinal` is the view's 1-based list position.

The 1600-pixel-wide bands cover the positive PNG height once, contiguously and
in full authored order. Each complete view is at most 1792 pixels high. These
are visual output metadata, not new input fields or physical measurements.

The traveler attaches each complete view figure once to its original
requirement's worksheet or inspection note. Pagination moves figures whole,
without splitting pictures, titles or captions. A returned PNG with missing or
malformed panel metadata is refused. A declared sketch not returned by the run
prints `NOT SHOWN: the set-up sketches for this check could not be drawn.`
The CLI converts `ValueError` raised during render asset validation or report
construction, including bytes without a PNG signature, to `BadInput` with exit
3 before output staging. This conversion does not cover every malformed payload
type or later traveler-scene refusal; see [failure classification](#failure-classification).

### Replacement and stale-image removal

PNG filenames receive the same collision checks as other outputs. An input at
`setup-S1.png` is a collision and exits 3. Both `check` and `traveler` remove
prior generated setup images and inspection sketches that the current run did
not return, including images from a longer route or an unavailable kernel.

`check` also removes a same-named PNG unless its bytes match the current render,
and always removes any prior `traveler.html`. It does not leave an old sheet
beside a new report. Replacement and removal share the
[output transaction](#output-safety). A refusal restores every prior output,
even if a stale target has already disappeared. A successful run leaves no
stale fixture image.

### Scene and panel metadata

The deterministic software drawing is 1600 pixels wide with panel-dependent
height. `scene.width_px` and `scene.height_px` record its actual dimensions.
The engine uses its bundled bitmap font and its own PNG encoder. No host font,
clock, image service or machine-specific metadata enters the bytes.

`scene` also records `view`, plain-language `shows` and `legend`, `render_debts`,
`primary_op` and sparse `waypoints`. Ordered `scene.print_panels` records
`{top_px, height_px, role, label}` describe full-width, contiguous bands covering
the canonical PNG's actual height exactly once. Roles are `setup`,
`profile_detail`, `path_detail` and `holding_detail`.

The traveler consumes these semantic windows at a common print scale, preserving
geometry, annotation units and visible debt. Each window retains setup, part,
revision and panel-order context. There is no arbitrary whole-image crop, fit or
downscale fallback.

Long setup keys and notes keep their setup ownership. The complete geometric
view, dimensions, leaders and axes stay in the first band. Original text entries
that do not fit continue in measured, full-width `setup` bands labelled
`KEY + NOTES (CONTINUED)`. An entry stays whole when it fits a continuation band;
an individually oversized entry has an explicit source-entry continuation
header, not a new physical drawing key. Each original row is painted once at
the same readable scale. Only the first figure receives the stock caption.

The main picture fits its measured callout lanes separately from annotation
details. Each annotation detail renders and measures its own content, then grows
within the whole-band bound or changes from a two-operation band to separate
single-operation bands. A complete single-operation band that still cannot fit
is refused. Annotation, holding and guide bands are composed once after fitting.
Cut-clearance keys and rendering debt stay attached to their actual owner.

### View orientation and stock meaning

Lathe views put the headstock/chuck on the left, the tailstock on the right and
setup +Z along the spindle to the right. Mills use setup-frame isometric views;
custom plates use a plan view. Labels identify setup axes, Z0, named datums,
jaws, supports and the selected cutter approach.

The amber hatch is entry stock minus this setup's derived exit stock. It is
neither a finished part substituted for arriving material nor a simulated
toolpath. If exit stock or a cutter cannot be established, a plain
`render_debts` sentence says what is not shown. Display debt never changes a
rule verdict.

Lathe material is drawn in meridian section so the removed annulus cannot hide
the retained core. A jaw-end detail magnifies nearby shoulders and reliefs while
the main view retains the full stock length. Mill/custom views overlay a dashed
nominal part outline, including behind arriving stock, to locate the drawing
relative to pads, pins and coordinate keys. That outline does not claim the
supply already has the finished shape.

Selected cutters use the traveler's short human tool names. A separately drawn
feed arrow requires an authored direction and is a direction symbol, not a path.
An unresolved saw cut plane produces a plain STOP annotation and preserves its
downstream stock debt. It never prevents other geometry facts from being
returned. A setup without a cutting operation has no invented cutter.

Unknown incoming stock produces no figure. Exact posed fixture solids are the
only basis for `fixture = "modeled"`. Dashed table, vise-body and machine-context
outlines are labelled schematic and do not enter geometry checks. A stop comes
from a selected inventory fixture and declared `stop_pose`, never a holding note.
Lathe views draw right-side tailstock context only where a centre component
actually supports the work. The schematic machine-context outline does not
independently verify that support. See [render geometry](rules-geometry.md#renders).

### Outline precision and callout placement

For every positive-span profile sketch, the paint-only finished-outline stream
requests at most `0.5 / S` mm at the conservative maximum render scale `S`,
including the plot's `1e-9` mm numerical denominator and maximum fourfold Y
exaggeration. There is no physical deflection floor or tiny-positive-span
exemption. Only coincident points or no finite points lack a sketch bound; an
unrepresentable span is refused. The request also retains the `0.5 / 324` mm
guide-axis detail bound when no sketch supplies one. The formula is in the
[rendering scale contract](rules-geometry.md#renders).

The native adapter first captures `nominal_outline_mm` with the ordinary
`Deflection=tolerance` samples and edge order, then captures
`nominal_render_outline_mm` with the bounded `Deflection`, without a coarser
retry. A native precision exception escapes setup rendering and becomes
`run_job`'s `status: "error"` with its reason, not a PNG or successful cache
entry. The mathematical request bound does not independently certify the
vendor's returned polyline; native support for very fine tolerances is separate.

Projected outline coincidences retain 0.01-pixel quantization and the canonical
minimum floating coordinate in each cell. One two-dimensional, one-pixel-bin
index contains every cell, including collapsed source edges. A chord queries
only its intersected strip, conservatively padded by one quantized cell, then
uses the exact along/cross-product test before sorting cuts and walking paths.
Index construction is O(V). Candidate discovery costs the number of strip bins
visited plus their stored cells, not all vertices in an X range or a diagonal's
bounding rectangle. Cut and path ordering remain deterministic.

The two outline streams have distinct consumers:

- `nominal_outline_mm` alone supplies nominal viewport fitting, bounds, layout,
  badges and every leader choice.
- `nominal_render_outline_mm` supplies only outline painting in setup,
  isometric and section views, guide-axis details and profile plots.

A specification with nominal geometry requires the explicit fine field. A
missing field is an error, with no silent legacy painting fallback. Absence of
nominal geometry remains legitimate.

Finished-outline callouts preserve the accepted placement and selection
algorithm: the original primary point assigns the lane, and every original
ordinary-tolerance vertex remains eligible. The guide view likewise retains the
original projected primary point and all legacy vertices, including offscreen
inputs. Only painting is clipped to its panel. There is no native-only anchor
selection, foreign-dash crossing filter, fallback pool or new landing debt.
Fine geometry and dash phase can change without changing leader endpoints or
layout. Guide-rim callouts also retain their placement. PR #198's scope was
tessellation accuracy; separate leader work is tracked in
[#211](https://github.com/pedropaulovc/prechips/issues/211), without a fix or
waiver in that change.

### Text fit, keys and fixture annotations

The final PNG layout checks every normalized bitmap-text line, including axes,
coordinate badges, inset headings, dimensions, legends and setup notes. Rounded
line bounds must stay 8 pixels inside the canvas and at least 4 pixels apart.
Every line is at least bitmap body scale 5: a 35-pixel cap height, approximately
11.8 pt at 1600 pixels across 7.5 inches. Cap height is not a CSS font size.
Collision, clipping or undersized text raises a render error. This does not
certify a physical printer or pen.

Callout lanes rebalance between sides and tighten leading instead of shrinking
type. Footers grow to hold notes, and their height is reserved before fitting
the setup view so dense legends cannot compress into overlapping rows. If a
lane leader's horizontal elbow would run along an axis through another
callout's point, it is drawn straight. An end label stays in the lane on its
own end's side. These checks do not alter geometry or turn unresolved machining
facts into passes.

A checked, posed chuck front not parallel to setup Z has no single jaw-front Z.
`scene.jaw_front_oblique` records that distinction without a printed note or a
missing-datum warning.

Setup notes derive from every declared operation, including bench actions the
kernel does not cut. A setup with no machine-cutting action lists its actions,
for example `No machine cutting: op 10 deburr, op 20 coating, op 30 inspect.`
`No material removed in this setup.` prints only when the kernel derives no
removed volume and no operation deburrs. Notes do not repeat the selected tool
and operation: those are in the tables and the primary tool's picture label.
A setup without notes has no SETUP NOTES heading.

Mill keys are `{label, op, xy}` in setup mm. Axial lathe keys use `xz`, whose X
is the declared radius/diameter DRO target and whose Z is the table station.
The same `P1`, `P2`, … keys annotate the profile inset and traveler coordinate
rows. Both mirrored sides remain explicit. Dense mill sketches use separate
operation panels so repeated corners retain legible coordinate keys.

Shallow contour panels label Y-only graphic magnification with `Y EXAG X…`.
Coordinate values, waypoint identities and setup-view axes do not change. The
faint nominal underlay uses the same labelled panel scale. Direction arrows
are spaced along the drawn path, including subpixel chords, so fine arc
sampling does not remove them.

Lathe inset paths and keys locate the nominal finished surface; they are not
compensated tool-tip feed targets. When the contour table also gives tool X/Z
columns, those columns control the feed, not the drawn surface line.

Numbered custom-clamp badges follow authored `hold.clamp_order`, not an order
inferred from prose. An explicit empty list means no accessory tightening
actions. Fixture construction primitives remain visible as geometry and are
individually named in `scene.components`. Printed callouts group body/support
hardware so bolt and shim details do not force pad, pin and clamp labels into
tiny text.

Custom-fixture badge boxes remain outside projected stock, the fixture plate,
other fixture components and the nominal part outline. They sit in rows above
and below it, in the points' x order, so their leaders do not cross. Leaders
return to the unchanged physical component centres. A badged clamp or pad group's
lane entry is the badges' key and has no separate leader. A trusted, explicitly
labelled fixture void gets a shop-caption leader at its posed centre and a
separate `{name, label, role, center_mm}` entry in `scene.fixture_detail_labels`.
These annotations neither create solids nor change geometry checks or resolve
measurement debt.

## Eligibility and approval

### Checker result and printed state

The checker applies these decisions in order:

| Condition | Exit and report state |
| --- | --- |
| Any error finding | 2, `verification = "planned"`. |
| Any finding with `numbers.kernel_unavailable = true` | 4, `verification = "planned"`, regardless of policy selection. |
| Unknown required policy, required warn/unknown/unsupported, or missing required rule/subject | 4, `verification = "planned"`. |
| None of the above | 0, `verification = "checked"`. |

Required `info` and `not_applicable` do not block eligibility. Policy selection
and always-required rules are described in the [policy reference](policy.md).

A report can be checked while its sheet remains `PLANNED — NOT APPROVED`.
Removing PLANNED requires an eligible report and a matching approval record
with resolved first-article evidence. Approval never changes the checker exit
or waives unresolved shop-required checks. `check` parses and warns on an
approval record but produces no sheet.

No hash prints on the sheet. `traveler.html` contains the full report hash and
prechips version in `<meta name="prechips-report">` and
`<meta name="prechips-version">`. These tags are a lookup, never the approval's
binding.

### Approval record

Supply `--approval approvals.toml` with one root record containing `hash`,
`first_article` and optional `[inputs]` digest strings. This example shows the
record shape; its placeholder strings are not supplied approval evidence.

```toml
hash = "<full current report hash>"
first_article = "<actual logbook/evidence reference from the cut first article>"

[inputs]
plan = "<prior SHA-256>"
features = "<prior SHA-256>"
```

Approval histories (`[[approvals]]`) and report-style digest tables are not
accepted. The only root keys are `hash`, `first_article` and `inputs`.
`hash` and `first_article` must be strings, and every declared input digest must
be a string. Neither a matching short id nor a stale record suffices.

Whitespace-only evidence or literal `unknown`, case-insensitive after trimming,
is unresolved. A matching record then warns that no first-article evidence is
recorded. Parsing does not authenticate evidence or perform the first article;
the shop owns its truth.

The renderer also requires normalized approval `approved = true`, no approval
warnings, a lowercase 64-hex report hash matching the approval and first-article
text other than literal `unknown`. These are renderer guards, not extra keys to
write in the TOML record. A fully accepted record prints
`CHECKED — FIRST ARTICLE RECORDED`.

### Stale and ineligible approvals

A stale record warns:
`Approval no longer matches: {changed input names} changed. Repeat the first article.`
Only input names declared in the prior record and present in the current report
are compared. An omitted prior input is never named as changed. Printed names
replace underscores with spaces, so `shop_policy` appears as `shop policy`.

The warning names `the operative bundle` when prior `inputs` is absent or empty,
there are no names in common, or all compared digests are unchanged despite a
stale report hash. A matching record for an ineligible report warns:
`The report still has unresolved shop-required checks; approval cannot waive them.`

Approval parsing and normalization are in [`cli.py`](../src/prechips/cli.py);
printed-state guards are in [`sheet.py`](../src/prechips/sheet.py).

## Output safety

### Files and output streams

For bundle commands, the default output directory is the plan's parent, or the
first plan's parent for `compare`. `--out` selects another directory.

| Command | Files | Standard output |
| --- | --- | --- |
| `check` | `report.json`; removes obsolete sheet/images as described above. | Empty by default; canonical report JSON with `--json`. |
| `traveler` | `report.json`, `traveler.html` and returned setup/inspection PNGs. | Empty by default; canonical report JSON with `--json`. |
| `compare` | `compare.json`. | Comparison tables, or the same comparison data as canonical JSON with `--json`. |
| `tools` | None. | Tool table or measurement-debt list; JSON with `--json`. |
| `explain` | None. | Selected finding details; JSON with `--json`. |

Findings, approval warnings and diagnostics go to standard error. `--json` does
not redirect or suppress that stream. `--verbose` changes the standard-error
finding display, not report contents. A nonzero readiness result can still
produce the report and requested traveler. The
[CLI catalog](reference/cli.md) defines each command's full output shape and exits.

### Path checks

Input bundles and output targets are checked before evaluation or writing.
Manifest files, plan-declared shop files and STEP assets must stay inside the
bundle root. Explicit CLI/environment shop paths may be external. `--out` may
name an authored directory anywhere, but every fixed output filename must
resolve inside it.

No output may alias an input by resolved path or hard link, escape through a
symlink, or name a directory. The output root cannot name a file. Approval
files receive the same collision protection as other inputs. Existing regular
output files are replaced.

### Staging and rollback

Each output is first written in full to a hidden temporary beside its target,
`.<name>.<random>.tmp`. No target is replaced or removed until every write is
staged. Prior bytes of earlier changed targets remain available until the last
change lands.

If the filesystem refuses directory creation, a staged write, replacement or
stale-image removal, the run exits 3. Temporaries are removed and every changed
target receives its prior bytes, or is removed if new. A handled failure cannot
leave a new `report.json` beside an old `traveler.html`. An output directory
created for the run may remain empty.

This transaction does not cover a process kill at any point, a concurrent writer
or failure of a restoring rename. A kill can leave hidden staging files even
before replacement begins. A restoring-rename failure exits 1. Only the target
whose restore failed keeps its prior bytes in a hidden `.<name>.<random>.tmp`
backup. Targets not yet restored keep their changed state, including deletions,
and their backups are removed; the output set can be mixed. This is not crash
recovery and does not guard against concurrent writers.

### Failure classification

Exit 3 covers bad input, output-path checks and output-file writes. The CLI also
converts `ValueError` from render asset validation or report construction to
`BadInput`, reported as `Invalid kernel render output`, with exit 3.

Other unhandled exceptions are prechips failures outside the 0/2/3/4 contract.
Examples include a rule that raises or returns duplicate subjects, an uncaught
`TypeError` while decoding a setup-only PNG, or a scene-validation `ValueError`
raised later by `render_traveler`. These give Python's ordinary traceback and
exit 1. Telemetry still flushes. Generation finishes before staging, and staged
writes attempt rollback on exceptions, so a generation failure writes no output.
A failure writing standard output after files are in place is also exit 1;
those files have already been committed.

No command reads expected fixtures as runtime answers. Output path checks and
the transaction are implemented in [`cli.py`](../src/prechips/cli.py).

## Generated traveler

`traveler.html` is the machinist-facing setup sheet. It uses Letter portrait
pages and keeps report internals off the paper. Its content and layout contracts
below describe the existing renderer; they do not change machining facts,
findings or approval.

### Job section

The job page opens with part, drawing number, revision and the approval banner.
An unconfirmed revision prints `REV NOT CONFIRMED` and a STOP line.

The job section includes:

- `JOB STATUS`: STOP, CAUTION and not-verified boxes. A setup with its own STOP
  items is named here so the job page cannot say there are no stops over a
  stopped setup. The page prints `Not ready to run` when the plan check has not
  passed, or the count of checks not verified. The checker's own pass is not
  printed.
- The approval state in shop words, matching the banner. `NOT APPROVED:` says
  whether no first article is recorded, the first part was made to a different
  plan or drawing, or one is recorded for this plan while open items remain.
  Approval cannot waive those items. The wording identifies the first part made
  as the first article.
- Each `Before S1:` stock prerequisite, such as `obtain the stock — not on hand`,
  plus drawing material, finish and a one-line speeds/feeds source.
- The legend `† Make-to-drawing expected settings; check the physical fixture as
  made before use. These settings do not clear installed-measurement STOPs.`
  when a SHOP-MADE FIXTURE row has the mark. A dimension or primitive receives
  it when its own measurement record's status is not `measured`.
- The DRO manual, named once, and each routed machine's `DRO resolution:`. This
  is its inventory `resolution`, linked to its setup measurement item when not
  verified, or a provisional default grid identified as such. A lathe also says
  whether X reads diameter or radius.
- `STOCK AND ROUTE`: stock size at the receiving setup's DRO resolution, supply
  notes and a setup-to-machine-to-holding table. Machine names use inventory
  `name`, a maker's model number or the machine kind, never an inventory slug.
- `DRAWING REQUIREMENTS`: feature and limits, with the drawing edge break once
  as `all edges`. A stock thickness prints only when no feature carries a
  thickness limit.

Two features on the same model faces with the same known limits and nominal
share one drawing-requirements row naming both, such as
`strap faces / strap (datum B)`. A shared citation or equal numbers alone does
not merge rows. Unknown limits, or a band with unknown/omitted nominal, do not
merge either.

### Numerical precision and typography

Authored values keep their digits, including a 1.9875 mm pin, a 0.0254 mm
runout limit or `allowed -1234.5675 to -1234.5671`. For plan units `mm` or `in`,
computed machine targets, setup coordinates, Z targets and DRO values print at
the decimal places needed to show one step of the setup machine's declared
resolution exactly, after conversion to those units. This formatting does not
snap values to multiples of the step; endpoint-specific checked rounding is
separate. If no positive resolution is declared, or plan units are neither `mm`
nor `in`, the provisional default is 0.001 in plan units, with its measurement
debt retained. A positive but unverified declaration still determines the
decimal places and retains its debt. A bench without a positive declared step
inherits the nearest upstream non-bench machine setup's grid and debt in its
stock lineage.

Computed numbers printed at fewer decimals round half-way values up, away from
zero: 3.175 at two places is 3.18. Drawing limits instead round inward so printing
never loosens them: a band's low limit rounds up and high limit down; a zone or
maximum, such as position, coaxiality, angularity, Ra or edge break, rounds down.
`position Ø 0.045` at two places prints 0.04. The renderer uses more places
instead of rounding a positive limit to nothing.

If a band is too narrow for its drawing precision or one limit is unknown, each
known limit prints exactly as declared, with every digit: `?–1234.567` at three
places, never `?–1234.57`. Physical carried-face heights retain the digits needed
to show a surface off the receiving DRO grid; they are not rounded onto a grid
line the surface does not occupy.

Each setup has an overview/operations section followed by picture, clearance,
notes and contour sections where applicable. Content determines physical page
count; no setup overview is promised to fit one physical page. Letter portrait
uses 0.5-inch margins, 12 pt working text and at least 10 pt metadata in offline
Arial/Helvetica/sans-serif type. Drawing limits and operative values retain
units and their applicable precision.

Ordinary read-only tables have 4 pt vertical and 8 pt horizontal cell padding,
12 pt text and 1.4 line height. Operation and handwriting areas retain their
larger task-specific spacing. Thread designations, ranges, fractions and units
stay together without splitting neighboring words. Fixture/check tables wrap
at word boundaries and give identified long cells more room without changing
dimensions or instructions.

### Duplex printing and layout refusal

Print the whole file double-sided with scripts enabled. The inline script
measures content at print width on load and before printing, places page breaks,
repeats continuation context and table headings, and pads odd-length logical
sections with a blank back. The job section and each setup section start on a
front side. Blank backs contain no instructions or ink. Without scripts, the
same content prints without duplex padding; print single-sided in that case.

Before each print pass, the script restores original text and wrappers while
retaining loaded image elements, including SVG images. It does not reload
unchanged sources. Printed panels use the same canonical native source-pose
image shown on screen. Operation groups and inspection records retain their
association through continuation context. Supported oversized content continues
instead of being compressed into smaller type.

A print-layout refusal restores source content and displays
`PRINT LAYOUT ERROR — ` followed by the reason. It does not establish a printable,
accepted layout. HTML generation and a successful checker exit alone do not
prove the browser's eventual pagination or physical print result.

### Continuation context and source progress

Headings, captions and authored lead-ins stay with the following content; the
sign-off stays with the last operation. Ordinary read-only tables keep the
three-row widow/orphan policy when those original row groups fit on both sides
of a break. Over-tall side-by-side blocks stack before splitting.

Continuation headings name the part, drawing/revision and logical section,
repeat the exact original printed status as a read-only reminder, and show the
local page number and total within that logical section. They do not recompute
approval or certify a new state. Moved or split operations leave a pointer to
the next physical page.

A continuation retains its applicable original operation, table or worksheet
title and units when these fit beside original content advancing onto the page.
Split fixture tables retain original component/size context in existing columns,
without adding assembly instructions.

Repeated context has explicit ownership:

- When a table's original instruction paragraph is complete and entirely
  visible on the current page, its structurally paired repeat is omitted on
  that page. Partial, off-page, unpaired or overflowing originals keep the
  measured continuation-context policy. Prose similarity never determines
  ownership or removes an independent instruction.
- The contour title has explicit ownership in its original heading and repeated
  table-title prefix. A complete original heading or uncompacted running title
  entirely on the same page removes only the duplicate title prefix. The
  repeat row, progress locator, procedure, depths and local instruction remain.
  Partial, compact, unpaired or overflowing canonical titles do not qualify.
  Measured repeat compaction does not promise a full title on every crowded page.

Long ordinary table cells may continue without withholding a later complete
prose cell that fits its own column beside that original row fragment. Admission
measures the composed row and every retained whole cell. An overflowing trial
leaves continuation behavior unchanged. Each cell keeps its original content,
whitespace, order and column. Writing fields and controls are neither copied
nor treated as whole-cell completion candidates.

An original note title that cannot fit its continuation body may continue as
authored source text, in order and at working size. Short titles stay atomic.
Repeated identity alone never counts as source progress; this fallback does
not split complete figures or duplicate recording fields.

A figure-bearing logical continuation keeps its complete first figure and stock
caption together. If the full repeated identity makes that group too tall, the
same part, drawing, revision, quantity, status and complete logical heading use
the 10 pt running-metadata hierarchy. True setup fronts keep full headers.
Working text, source captions and images do not shrink. A group that still
exceeds measured capacity is refused. Every print pass restores the full header
and recomputes the decision, so resizing or printing again cannot reuse stale
compacted content.

### Recording areas and performed marks

Operations retain authored order. A square beside an operation ID means
operation performed only, not inspection acceptance, approval or clearance to
proceed. It adds no schema field.

A genuine inspection requirement without its own authored recording destination
gets one full-width white readings/observations area below it, with at least
20 mm clear interior depth excluding labels, padding and borders. If that exact
read-once feature/requirement group already has named or underscore fields in
its referenced procedure, those are the sole destination; no fallback box is
duplicated elsewhere. Distinct requirements and separately banded result groups
retain separate destinations.

Known owners, authored band, gauge, method reference, existing units and nearby
authored context stay associated. Feature/location is identified when needed.
The renderer infers no positions, reading counts, statistics or acceptance
obligations. A true shared across-faces shoulder dimension remains one record;
equal printed bands alone do not prove shared physical identity.

Specifically named `{name}` procedure fields remain distinct and have a
35 × 10 mm clear interior floor. In prose, each named blank has its own line.
Worksheets and calculations retain their sole value fields. Standalone authored
underscore prompts become full-width white fields at least 20 mm deep without
changing surrounding instructions. A typed coating operation without a genuine
inspection record or recording prompt may have
`Additional writing space (optional)`. It adds no requirement identity, target,
mandatory check or acceptance obligation.

Titles, source words, numbers, methods, GO / NO-GO meaning and gauge/source
ownership are unchanged. Unknown requirement identities, bands and other debt
remain visible, without fabricated result data or invented gauges.

The sign-off has its own signature field. Its first-article reading reminder is
a read-only pointer to labelled inspection fields or worksheets, not a second
unqualified measured-results blank. Neither signing nor a performed mark changes
findings or approval. Approval, first-article evidence and all authored recording
fields are unchanged.

An actual `measure_then_set` DRO acquisition with known setup, axis and plan
units has one setup/axis-qualified empty `M` writing area. When a before-HOLD
measurement field already exists for that acquisition, it is the sole
destination and the DRO recipe points to it. Gauge, timing, span, offsets and
set arithmetic remain authored. The renderer does not infer
`measure_before_hold`, an inspection requirement or a missing unit.

Terminal punctuation stays with a field caption rather than on an orphan line
after the box. Calculation fields align at the left below their unchanged
equation/instruction text. These groups preserve authored characters and order,
labels and clear writing interiors.

### Contour progress and recording-area locators

A numbered contour operation with multiple known depth levels may have one
optional progress-only current-level / last-completed-`#` pair beside its
whole-level Done marks. Continuations point to that operation-owned area
without repeating writable fields. Single-level, raster, unknown-depth,
empty/list-only and stopped-tool cases get no pair.

These notes are not inspection acceptance, another Done record, a mandatory
measurement or clearance/instructions to resume. Original depth levels, table
rows, numbering and operation order do not change. The read-only progress
locator is separate from the full repeated contour title and stays visible when
crowded context uses a compact setup/op identity. Both candidates are measured
with original source progress. If even the compact identity and locator do not
fit, printing refuses instead of dropping the locator, duplicating fields or
shrinking type.

Recording-area pointers name the actual printed setup/logical sheet and local
page holding the sole original destination. Named procedure fields and unnamed
recording areas remain distinct; progress pairs stay together.

Before layout, the paginator reserves an empty, measured read-only page counter
using a conservative digit bound from pristine source, not a guessed page.
Counter digits disable pair kerning. Repeated digit strings are measured in the
counter's inherited typography and must have equal, positive widths. After
placing all original content, the paginator resolves destinations, fills actual
counters and verifies unchanged layout and complete containment. Missing or
duplicated destinations, split progress pairs, changed reservations or escaped
pointer text cause a print-layout refusal. Every load/before-print pass restores
pristine source and rebuilds pointers. Generated context neither owns writing
areas nor counts as source progress.

### Setup overview and operation order

Each setup overview/operations section follows this order:

1. Title, status boxes and applicable measurement references.
2. `HOLD`, then grip/stickout and related holding dimensions.
3. Coolant, any setup-specific edge break, and applicable purchased-tooling
   receipt checks.
4. `TOOLS FOR THIS SETUP`.
5. `DRO ZERO` where applicable.
6. `OPERATIONS`, or `ASSEMBLY / FINISHING` for an all-bench sequence.
7. The existing sign-off and its writing area.

The following contracts define the content in those positions.

#### Stops and the job-wide measurement register

`STOP — do not run until resolved` includes every STOP kind carried by a setup's
operations, affected operations and clearing actions. Measurement-backed
speed/feed, contour and depth stops remain visible beside their measurement
references.

Only untrusted facts actually consumed by a refused decision enter the job-wide
measurement register, printed once in the JOB section. Selection of an inventory
item or a prerequisite finding's diagnostic measurement union does not prove
local consumption. A prerequisite-only UNKNOWN setup remains stopped by its
true upstream cause, naming the source setup/op and JOB measurement refs,
without unrelated local Record rows. A bench setup without an unresolved
consumed decision has no measurement STOP and is absent from the JOB's stopped
setup list.

Canonical record/field identity, physical subfield and installed
holder/configuration define one physical quantity. Setups reuse its global
`?M1` marker. Numbering and display order are deterministic and ascending. The
full instruction, instrument and 35 × 10 mm blank print once per physical
quantity, with source setup groups and tool numbers in shop language.

Composite fixture solids have separate dimensional and position rows bound to
the original canonical record, each with its own blank. Measuring them does not
promote the original fact's trust. Dimensions follow the actual shape: box
length/width/height, cylinder diameter and axial length or depth. Local X/Y/Z
placement quantities have separate rows. Position rows identify the minimum
corner for boxes and base centre for cylinders, relative to fixture-local origin.

TOOLS, operations and CLEARANCE use only short refs. The JOB readout line names the
controller and its single global step ref. Bare M means the authored measurement
variable, not necessarily a touch-off reading. TOOLS and individual recording
rows stay whole. Continuation context retains the input name. Direction units
break at the slash in `cw/ccw`, never inside either abbreviation or by shrinking
the blank.

Operators record values and return the traveler for reissue. Measurement alone
does not clear actual STOP decisions on setup pages. Reissue wording names those
decisions, without irrelevant generic speeds/depths/contours. Independent
engagement, speed/feed, cut-order and saw-kerf decisions keep their consumed
facts even when another stock-dependent decision is blocked. Eager native
refusal lists alone do not establish consumption. Planner-unresolved topics
remain named with their operations.

Errors never print as `?`; unknowns never read as passes. This renderer
projection does not alter report finding statuses, full payloads or cache
identities.

Pre-clamping acquisition requires explicit `measure_before_hold = true` and an
authored `measure`. The original HOLD step gets a 35 × 10 mm clear writing field
and the zero row refers back to it. There is no separate MEASURED ZERO INPUTS
section. Absent/false declarations keep measurement at the machine.

#### Holding, coolant and receipt checks

`HOLD` is a full-width numbered clamping sequence: mount, supports, grip, stop,
tighten and authored notes. Semantic picture panels follow in the attached
picture section. Without a render the overview says
`NO PICTURE — the holding is not modelled; set up from the HOLD steps.` A small
table gives grip length, stickout and jaw-front Z; a lathe also has centre tip Z
and quill extension. Pose vectors and planner field names do not print.

Coolant does not print for bench setups. The drawing edge break appears once
on the job page. A setup with a different `deburr_mm` prints that limit and the
author's reason, for example
`Break edges 0.100 mm max in this setup, not the drawing's 0.25: small socket edge break keeps the bonded length.`

`PURCHASED TOOLING / RECEIPT CHECK` prints for each bought-finished item with
[receipt checks](inventory.md#purchased-tooling) in its first using setup. Each
row identifies what is bought, the check, gauge and acceptance limit. An
unresolved row says `STOP:` and why. Later setups print a line naming that
table's sheet.

#### Tool identities

`TOOLS FOR THIS SETUP` has `T#`, tool, insert/size/material, holder or QCTP station
and using operations. The shank prints when it differs from cutting diameter,
for example `shank Ø12.700`. Operation rows carry only `T#`.

One tool/holder pair gets one `T#`, based on selected identity: `tools.drill` and
`drill` name one drill; `holders.er20` and `er20` name one holder. A lathe pair
keeps its number across all setups on that machine regardless of reference
spelling.

Spindle-stopped `die_thread` and `hand_tap` selections also appear in this
pull list with their selected die stock, tap wrench or follower. Their
operation rows use the same `T#`. A nominal thread designation does not
supply a physical cutting diameter, projection or powered-tool touch-off.

#### DRO zero and acquisition

`DRO ZERO` does not print on bench setups: a `bench` or `manual` machine running
only fit and inspect operations has no spindle, DRO or axes. Saw cut-off setups
use the cut plane in the operation row instead of a zero recipe.

The recipe gives positive directions, then one row per axis: pickup tool/side,
paper or edge-finder radius, Axis Set value, check jog, expected display and the
reading a reversed axis would give. Re-indication and tool-change touch-offs
follow. Changes to one touch print once with their operations, for example
`Tool changes before ops 20, 30 and 40: install the op's tool (the T number in its row), then …`.
Tools remain in the TOOLS table and operation rows. Authored indicating/transfer
prerequisites precede the zero table without changing words, methods or limits.

For a mill X/Y side pickup, the check jog would take the finder over the work.
The printed sequence therefore raises Z only until the finder/indicator clears
the work and everything clamped to it, checked by eye across the top; jogs the
table the printed distance and reads it; jogs back to the Axis Set value; then
lowers. The picked-up value is never set again. The lead-in stays with these
steps. A lathe check jogs away from the work without a raise step.

A lathe X trial-cut pickup, for zero or tool change, says
`take a light trial cut, withdraw along Z without moving X, stop the spindle, measure the diameter`.
An edge-finder pickup names the `EDGE FINDER` box. It prints once per finder and
mill, in the first setup's DRO ZERO on that mill. The box gives speed bands where
the mill's spindle ranges overlap the finder's rated rpm, never a speed between
the mill's ranges. A finder rpm range outside the mill's prints `STOP:`. An
electronic finder uses the spindle stopped. The box also gives contact indication
and offset: half the tip Ø, Axis Set edge − r from the − side and edge + r from
the + side. Later setups name `EDGE FINDER box, Setup S1 sheet 1`. Missing or
unknown finder/spindle facts print `STOP:`. See [edge finders](inventory.md#edge-finder).

For a proven carried planar Z contact, physical face height prints separately
from the report's typed Axis Set. The producer's AS-CUT height travels through
recorded rigid frames. The +Z contact setting rounds down to the receiving
grid, retaining a nonnegative residual of at most one step. The renderer does
not re-round either face or setting. On a unit-converted recurring-decimal grid,
contact equality uses the printed grid-line value. Only binary roundoff may
meet it from below, never native length tolerance.

Subsequent entry, depth, exit and breakthrough prose consumes checked operative
endpoint rows using that actual Axis Set. General prose substitution does not
rewrite authored dimensional notes.

Imported `stock_state.entry_z.<feature>`, or entry supplied by `top_z`, is the
transformed native nominal, not the carried AS-CUT height. Equality uses the
physical 0.000001 mm length tolerance in manifest units. An AS-CUT touch edge is
allowed, but an entry differing from native is a named bad-input ERROR with
unknown operative stops, never a second application of the carry offset.
Unknown inputs remain unknown. A same-setup producer's entry retains its local
DRO endpoint. The independent endpoint oracle rejects mismatched authored entry
even if forged output repeats the double shift.

A through endpoint's dimension-derived exit boundary is conservative, not native
exit-plane credit. `physical_exit_bound_z` records physical entry minus
`local_thickness`. Printed breakthrough target and margin use the checked
operative boundary without claiming the independently cut opposite face stands
at that bound.

#### Operations and manual steps

Full-width operation groups name operation/action, depth of cut, feature, `T#`,
rpm, feed, Z target and cut direction, followed by associated inspection records.
There is no empty placeholder row when no inspection exists. Actual checks,
messages and recording fields remain.

A lathe table containing an operation measured in the chuck adds
`measure only with the spindle stopped and the tool withdrawn` to its heading.
Turning feed prints in `mm/rev` with resulting `mm/min` in brackets. Drill feed
prints axial `mm/min` with `mm/rev` for hand feeding. Other mill and saw feeds
print in `mm/min`. Unknown feed cells start with `STOP`.

Crash-relevant values stay with the operation: jaw front within 3 mm of nearest
tool approach, dead centre at the work end, tool tip within 3 mm of jaw top,
and holding within 3 mm of the tool sweep or material a file removes. Per-op
STOP/CAUTION findings, notes and tip-depth derivation stay there too. Contour
and inspection-note references name their attached logical section, not a
promised physical page number.

A blade relief's Z field gives each plunge's corner Z and plunge diameter. The
groove extent prints only when it differs from the operation's Z window; the
diameter's drawing limits print there only when absent from the inspection
record.

A setup whose operations are all bench steps, including `inspect`, `deburr`,
`coating`, `fit`, `scribe`, `release` and hand finishing, prints
`ASSEMBLY / FINISHING`. Its five cells are step, feature, material/consumable,
action and inspection. Coating names the in-house consumable or outside service.
Action uses the operation's own instruction, else its action. Empty machining
fields do not print. Mixed machining/manual setups retain the machining ledger;
manual-only groups keep these five authored cells without invented speeds,
targets or checks. Manual finishing has a short Step heading and the unchanged
action in normal working text grouped into sentences.

### Attached pictures, clearance and feature maps

Complete semantic picture windows carry setup/part/revision identity, panel
order and caption, followed by `NOT SHOWN:` debt. They reference the canonical
PNG by relative filename. `scene.print_panels` supplies exact windows rather
than fitting a composite image onto one page.

#### Clearance

`CLEARANCE` does not print for bench or saw cut-off setups. A lathe shows chuck
Ø against swing, work Ø against swing over the cross-slide, length against
between-centres, quill extension and jaw-front distance to closest tool approach.
That distance is the least of each operation's planned Zs and its whole tool's
chuck-side extent over every kernel pose: accessibility `tool_z_mm`, or the
outline carried to the dome table's nose readings, `nose_z_mm`. It is the same
value as the operation's jaw box. An unposed or incompletely posed turning tool,
or a dome table without tool readings, makes it
`not computed — check at the machine`.

A mill shows the tallest spindle-to-table stack, including 25 mm tool-change
room, against available room; X/Y table travel; and one
`Not computed — check at the machine` line for uncomputed items. Its table has
operation, tool, closest obstacle, clearance mm and action.

For each cutting operation, the row takes the smallest known value among:

- Headroom margin.
- DRO tip height over jaw tops.
- Holder face above the highest stock beside the tool: `projection_mm` minus
  reach from that stock's DRO surface Z to the printed tip.
- Every `clearances` entry in the reach finding.
- Holding nearest the whole tool over its commanded sweep or removed material,
  whichever is nearer, from `render_scene.cut_clearances`. The holding picture
  dimensions the same value.

A bench file in a machine setup has its own row without a tool, using holding
nearest the material it removes. Negative clearance or a holder past the flute
hitting a wall is a STOP. Unknown clearance or unproven holder wall clearance
requires a check at the machine. Jaw clearance within 3 mm asks for a hand-fed
approach. Holding within 3 mm of a cutter says `hand feed past the …`; near a
file it says `keep the file clear of the …`.

Operations with the same tool, obstacle, clearance and action share a row. An
identical nonempty action for every row prints once above the table, explicitly
scoped to all rows. Otherwise the complete action occupies its associated
full-width row without wording changes.

#### Feature map

A lathe `FEATURE MAP` lists surfaces the setup cuts. Inspection-only surfaces,
such as an as-supplied diameter, have no turning target and are omitted. Rows
give feature, drawing Ø limits (`—` for a process size such as a joint spigot),
X as the DRO displays it, and the start/end Z of the setup's cuts. X says
`turn to Ø` for diameter display or `turn to X (radius)` for radius display.
Unstated `dro.radius_mode` prints `?` and a STOP.

An authored turning/profile or boring `to_dia` belongs to that operation's
stage, not automatically to the finished feature. Staged rows name their
operations and use only those operations' cut limits. Equal consecutive
targets may share a row. Unknown targets remain `?`; a later or finished
diameter never fills them, and a facing/part-off endpoint does not replace the
turning size. Missing targets in a staged feature also remain unresolved.
Unstaged legacy feature maps retain their reference-derived targets.

The coordinate report's feature-row nominal diameter and `x_target_mm` remain
finished-feature geometry references. An unchanged digital stage can retain
the located reference X, including its aim. A different or unlocated stage
shows the authored diameter as `nominal; X ?` with a STOP until its pickup and
checked X target are established. Mechanical-scale values remain nominal
diameter/radius targets, converted to the declared readout units, not physical
dial settings. Drawing limits remain separate from every process-stage size.

A mill map gives feature, the reference point X/Y/Z stand on, and X/Y/Z values.
The point may be a hole/boss axis, arc centre or face, at entry, exit or Z0.
A face square to setup Z is omitted unless it carries an aim: its centre is no
DRO stop and its Z is already in the operation row. An empty map is not printed.
An aim adds where to machine it, offset from drawing nominal and inspection
band. These are feature locations, not tool tips. The qualification repeats in
the table header on continuation pages.

### Inspection notes, contours and worksheets

`INSPECTION NOTES` numbers procedures, each beginning with setup and operation,
for example `S2 op 30: …`. Complete original operation context repeats when it
fits beside original source progress on a continuation. Inspection view figures
belong only to that original note or worksheet. Continuations do not copy
figures, reading boxes or calculation/result fields. A figure-only continuation
still carries original source content.

The contours section appears only for contour operations. Each operation has a
block titled with setup, operation, tool and direction, for example
`S2 op 50 — top edge · T2 …`. Tables use DRO precision and add a `P` column when
`scene.waypoints` supplies picture keys. A missing tool prints
`STOP … tool not selected; do not run` instead of a table.

A lathe dome table prints imaginary-tip `tool X (Ø)` / `tool Z` columns when
nose compensation is known, on the same X display as `surface X (Ø)`; radius
mode uses `radius`. Otherwise it says nose radius compensation is not computed.
A table clipped at the operation's stock-removal bounds names its start/stop
point, for example `stops at P7: the stock past it is outside this op's area`.
Long contour tables may use more pages, with setup identity on every block.
Each move number and each depth level's completion box with `level k of N`
remain whole on one line, however narrow the block. Continuations admit complete
original context only when it fits beside source progress; added context is
never fragmented.

A procedure becomes a worksheet only when it has an authored step list, named
`{name}` readings in those steps and at least two calculation lines. Each
worksheet has its own logical sheet after contours, for example
`SETUP S11 — sheet 4 of 4: worksheet, S11 op 110 angularity Ø`. Steps keep their
original numbers and refer to readings with identifiers such as `[rJ1]`, without
duplicate value boxes. READINGS has one box per named reading at its source
step. Original equations and calculation fields print once after the readings.
Underscore prompts alone do not make a worksheet.

### Shop-facing wording and review limits

The job and setup overview/operations sections end with their existing sign-off.
The renderer removes author's-choice tags, face ids, inventory slugs, frame
names and hashes from shop-facing prose. Frame `T1` reads as `Setup S1 zero`.
Rule ids, source paths, uncertainty detail and hashes stay in `report.json`;
report/version lookup remains in HTML meta tags. Presentation never changes
PLANNED readiness.

The layout targets use guidance on proximity, readable type and writing space:
[NN/g proximity](https://www.nngroup.com/articles/gestalt-proximity/),
[Centre for Civic Design print forms](https://civicdesign.org/tools/pdf-forms/best-practices/)
and [Universal Design document guidance](https://universaldesign.ie/communications-digital/customer-communications-toolkit-a-universal-design-approach/customer-communications-toolkit-a-universal-design-approach-navigation/written-communication-2/document-design).
They do not certify machining usability. Physical printer, pen and operator
rehearsal remains pending. Intermediate CLI/PDF observations in
[examples](../examples/README.md) are not final pagination acceptance.

The developer tool `scripts/machinist_review.py` prints the HTML to Letter with
headless Chrome or Edge, including duplex padding, and asks a reviewer from the
other model family to inspect every page: no questions and nothing the operator
does not need. It compares speeds, feeds, depths of cut, tap drills and reamer
allowances with local Machinery's Handbook pages supplied by `--handbook` or
`PRECHIPS_HANDBOOK_DIR`. Page selections are in
`scripts/prompts/handbook_refs.toml`; findings cite table and printed page.
The handbook corpus is not vendored. With no handbook named, the review runs
from memory and records that limitation. An explicitly named missing or invalid
corpus is an input error, not permission to fall back to memory.

That tool calls a hosted model. It is not part of `prechips check` or
`traveler` and does not change their offline contract. The
[development guide](internals/development.md) owns review procedures and
acceptance evidence. Print CSS, generated PDFs and model review do not replace
a physical dry run or machining acceptance.

## Telemetry and console

### Console records

The same Python logging records feed OpenTelemetry and Rich standard error, so
console and exported facts agree. Finding records carry rule, subject, status,
numbers and citations. Structured evidence is retained in exported attributes.

| Finding status | Ordinary standard-error display |
| --- | --- |
| `error` | `✗` and message. |
| `warn` | `!` and message. |
| `unknown`, `unsupported` | `?` and message. |
| `pass`, `info`, `not_applicable` | No ordinary finding row. |

`--verbose` renders the full finding table. Non-TTY output and `NO_COLOR`
disable color, not glyphs. When no kernel is available, every geometry finding
has `numbers.kernel_unavailable = true`. Ordinary console output groups their
identical kernel-naming `?` sentence once per run. Verbose output, the report
and OpenTelemetry retain every finding.

### Export configuration and environment

The OpenTelemetry API, SDK and OTLP HTTP/gRPC exporters require `>=1.39.1`.
The API is a direct dependency because telemetry imports its tracing and log
record types. Logs use the API `LogRecord` form of `Logger.emit`, with exception
details in standard attributes, not a newer `exception` keyword. Transport tests
exercise local HTTP and gRPC export with correlated finding context. These tests
do not establish a run with all dependencies pinned to their lower bound or live
collector acceptance.

Export is opt-in. With no configured endpoint there is no exporter, collector
discovery, network request or missing-endpoint warning. These settings govern
traces and logs independently unless a shared fallback is used:

| Variable | Contract |
| --- | --- |
| `OTEL_EXPORTER_OTLP_ENDPOINT` | Shared endpoint fallback for both signals. |
| `OTEL_EXPORTER_OTLP_TRACES_ENDPOINT`, `OTEL_EXPORTER_OTLP_LOGS_ENDPOINT` | Signal-specific endpoint instead of the shared endpoint. An empty signal-specific endpoint disables that signal. |
| `OTEL_EXPORTER_OTLP_PROTOCOL` | Shared transport: `http/protobuf` by default, or `grpc`. |
| `OTEL_EXPORTER_OTLP_TRACES_PROTOCOL`, `OTEL_EXPORTER_OTLP_LOGS_PROTOCOL` | Nonempty signal-specific transport overrides the shared value. |
| `OTEL_EXPORTER_OTLP_TIMEOUT` | Shared positive finite timeout in milliseconds, converted to exporter seconds. |
| `OTEL_EXPORTER_OTLP_TRACES_TIMEOUT`, `OTEL_EXPORTER_OTLP_LOGS_TIMEOUT` | Nonempty signal-specific timeout overrides the shared value. |
| Standard exporter endpoint/header/TLS variables | Endpoint URL, headers and TLS are resolved by the selected SDK exporter. |
| `OTEL_SERVICE_NAMESPACE` | Optional `service.namespace`. |
| `TRACEPARENT`, `TRACESTATE` | Valid W3C parent context continued by the invocation. |
| `NO_COLOR` | Disables console color without removing finding glyphs. |

Resource identity is `service.name=prechips` and package `service.version`, with
optional namespace. These are generic OpenTelemetry OTLP exporters, not an
Azure Monitor distro or automatic Azure integration.

Protocol and timeout are validated only for signals with a configured endpoint.
For those signals, an unsupported protocol or a timeout that is not a positive
finite number of milliseconds disables both signals for that invocation.
Standard error gets one `! OTLP export disabled: …` warning naming the variable.
Exit, report and sheet remain those of an unconfigured run. Batch processors
flush and shut down on exit, including bad input. Flush is idempotent.
Configuration reuses a live session only until flush closes it; configuration
after flush creates a fresh root and pipeline.

### Invocation and evaluation spans

Each invocation starts a `prechips.<verb>` root span. Before parsing, the CLI
uses the first argument token equal to a recognized verb, including after global
flags; without one it uses `prechips.usage`. A rejected command line can
therefore still carry a verb-named root.

| Work | Span |
| --- | --- |
| Input loading | `input.load`. |
| Output staging | `output.write`. |
| Registered rule evaluation | `rule.<name>.evaluate`. |
| Registered rule finding record | `rule.<name>`, with finding context. |
| Synthesized bundle binding | `rule.bundle_binding`, with subject `inputs`; no `.evaluate` span. |
| Synthesized required-coverage finding | `rule.<finding.rule>`, with its subject; no `.evaluate` span. |
| Host job construction | `kernel.build_job`. |
| FreeCAD batch execution and job-cache lookup | One `kernel.geometry` span. |

Native timing is diagnostic only. It never enters normalized job/cache-key
inputs, findings, reports, report hashes or render bytes. The host requests it
with `{"jobs": [...], "timing": true}`. Native requests without that opt-in keep
their untimed output contract.

### Native timing fields

The native batch response has `timing = {wall_ms, cpu_ms}`. Each job result has
top-level `timing = {wall_ms, cpu_ms, phases, setups}`. A job's `phases` records
work before the first setup and cross-setup work after the last:

| Phase | Work |
| --- | --- |
| `step_import` | STEP reading/digesting, parsing and import of its one valid solid. |
| `face_binding` | Face signatures, STEP face references, declared features, faced aims and result face facts. |
| `stock_prep` | Stock supplies, blank boxes, joints, process model and stock facts. |
| `cross_setup` | Between-setup checks, including printed checkpoints against later contacts and rotary coverage. |

A phase is present once it starts. Each setup total covers all its work: holding
stock, running the setup and recording results. Job phases and setup totals
together cover all of the job's work. `setups` maps setup ids to
`{wall_ms, cpu_ms, phases, ops}`. Its `phases` includes measured `fixture`,
`chuck_walls` for radial clamp-wall sampling, `stock_states` for the single
op-order pass deriving before-op stock, `render`, `stock_output` for final
wall/cap checks, and `inspection_sketches`, when those paths run. `ops` maps
operation subjects to `{wall_ms, cpu_ms}`.

Native measurements are milliseconds rounded to six decimal places. Elapsed time uses
a monotonic clock; CPU time uses the FreeCAD process CPU clock, not host CPU or
machine-wide utilization. Job and setup totals include their phases and
operations. Do not add nested measurements to the totals. Batch measurements
include orchestration and are not a sum of job measurements.

### Execution and cache provenance

The host exports `kernel.setup` spans with `setup_id`, and nested `kernel.op`
spans with both `setup_id` and `subject`. Fresh work carries
`kernel.wall_ms`, `kernel.cpu_ms`, `kernel.timing_source = "execution"` and
`kernel.executed = true`. Setup phases use `kernel.<phase>.wall_ms` and
`kernel.<phase>.cpu_ms`.

These short host spans export native facts after the response arrives. Their
timestamps are not backdated, and their OpenTelemetry durations do not represent
native execution time.

Successful cache entries retain original job timing unchanged. Disk-cache hits
instead carry `kernel.original_wall_ms`, `kernel.original_cpu_ms`,
`kernel.timing_source = "cache"` and `kernel.executed = false`. Phase attributes
use `kernel.<phase>.original_wall_ms` and `kernel.<phase>.original_cpu_ms`.
These describe the original computation, not CPU spent replaying cache. Old
entries without timing emit no setup/operation timing spans. Identical jobs in
one batch emit facts once, not once per consuming bundle. An already-populated
bundle memo emits no new geometry span.

`kernel.geometry` records unique `kernel.executed_jobs` and `kernel.cached_jobs`
counts. Its `kernel.timing_source` is `execution`, `cache`, `mixed` or `none` for
identified-kernel requests with no usable jobs. `kernel.executed` says whether
a native batch was invoked. Fresh batch measurements are
`kernel.batch.wall_ms` and `kernel.batch.cpu_ms`; a cache-only call has neither.
`kernel.batch.host_wall_ms` is host elapsed launch time, rounded to three decimal
places in milliseconds. Its excess over `kernel.batch.wall_ms` accounts for
FreeCAD start-up and result I/O.

A failed batch adds `kernel.batch.error` with its reason. If the engine progress
trail shows an open phase, it also adds `kernel.batch.open_phase`, for example
`batch/job 0/S2/stock_states`. See [kernel errors](rules-geometry.md#kernel-errors).
The geometry span's own elapsed duration includes host cache lookup and
subprocess overhead, not only measured native work.

### Host measurement debt

The host geometry result carries `measurement_debts =
{ setups: { <setup id>: [entries] }, ops: { "<setup>:<op>": [entries] } }`.
These are facts the job builder refused for that setup or operation. Each is a
`numbers.measurements` entry with `id`, `instruction`, `units` and `cite`, plus
the record's current `status` and `reason`.

A whole authored solid is identified as
`fixtures.<selected inventory member>.solids.<name>`, the declaring item, not
the clamp it is drawn under. This metadata is host-only and rebuilt on every
call, including cache hits, fresh runs and unavailable kernels. It is never
written to native cache. Native job/cache identity sees refused inputs only as
a sorted list of stable field ids, without attribution or reason text.
Host-only comparisons, such as OAL under explicit projection and vise opening,
are not native inputs.

Geometry findings that depend on a refused fact, including
`fixture_interference`, thin-wall and `vise`, attach those entries to their
unknown result even if setup context succeeded. They name exact ids, current
status and reason, including upstream stock lineage.

### Geometry-query reuse boundaries

Collision sampling reuses only exact immutable query recipes. It neither
rounds poses nor stops after the first hit; every placed sample contributes to
the full hit count. Finished-face references form a per-operation,
per-tool-kind set union. Once a label is proven, later poses need not rediscover
it. Partial new sets stay local to that growing union; an operation-shared
stock-region cache stores only complete reference sets. Pointed cutters retain
actual cone/body geometry in stock and fixture intersections.

A cylinder touching no stock-face bound has constant material membership. Its
midpoint may be rejected beyond the tolerance-grown stock envelope. Other
midpoints keep the native material classifier and existing shape type.

A part-hit count can skip a boolean when an interior ball is certified: the
native classifier puts its centre inside stock, rigorous lower bounds clear
all boundary faces, and the ball lies strictly inside the exact query cylinder
with volume above the hit threshold. This certificate counts hits only. It
substitutes no shape and never proves a miss. Unsupported proofs fall back to
the native boolean. Skipping a boolean cannot raise its errors; every boolean
still run retains its original errors without catching or suppressing them.
Pointed cutters never use this certificate and their solid queries stay
uncached. A hit skips intersection only when no finished face outside the known
reference union has positive contact area with the query cylinder.

### Acceptance limits and implementation

[`telemetry.py`](../src/prechips/telemetry.py) owns console records, resource
identity and exporter lifecycle. The host timing/cache adapter is in
[`kernel/__init__.py`](../src/prechips/kernel/__init__.py). See
[architecture](internals/architecture.md) for module responsibilities,
[local telemetry checks](internals/development.md#check-local-telemetry) for a
collector procedure, and [acceptance reporting](internals/development.md#report-acceptance-honestly)
for the separate live farm requirements.

Local exporter tests do not replace a real parented farm run observed in App
Insights by `operation_Id`. That live acceptance and physical print/dry-run
rehearsal remain unobserved and pending.
