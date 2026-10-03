# PLAN rev 6 reference bundles

These are **hand-authored input bundles** with CLI-generated reference-output
contracts, not certified CAD exports, toolpaths, approvals or first articles.
Every example traveler remains **PLANNED**. Each candidate consumes its plan,
`features.toml`, and the three shared shop inputs. Shaft, bracket and cone
supply no STEP byte stream: `step_sha256 = "unknown"` is a finding, not a
fabricated digest, and under M4 it keeps all seven geometry rules `?` (the
`STEP bytes and their manifest SHA-256 are required for FreeCAD geometry.`
reason, or on a machine without FreeCAD the one kernel-unavailable line, which
forces exit 4 unless an error already yields 2). `rocker-arm/` binds the
consumer's labelled export `rocker-arm.STEP` by digest (`19070131…`, the
bytes delivered under `C:/src/dt-logs/features-bundles/rocker_arm/`, kept
byte-for-byte via `.gitattributes -text`; SolidWorks inches,
`HAF_<FEATURE>__P<nn>` face labels) and preserves the exported manifest face
sets. The S1 strap operations explicitly claim the +Z datum-B face `#492`;
`strap_faces` truthfully remains the exported bottom face. The tip lands stay
unclaimed. The numeric rectangular supply is the S1 stock view. Its later
rail-and-ear/profile removals have no authored numeric lateral footprint,
so S2/S3 incoming stock is `?` naming that debt and emits no fictitious
finished-part renders. Fixture dimensions remain unresolved. Its exit stays 2
for the absent tools and supported profile fixture. The cone M2 fixture has two
authored candidates for the same part,
not two inventory parts. The M4 geometry fixtures, which do carry STEP bytes,
live under [`geometry/`](geometry/README.md) with their own inventory and policy.

The frozen bytes describe an available-kernel run. Without FreeCAD, traveler
and comparison outputs must still repeat byte-for-byte across runs, but every
geometry family is unknown and no kernel render exists; those outputs do not
match the installed-kernel goldens. Comparison still retains both candidates,
the cited stock-volume arithmetic and error-before-unknown exits **4 / 2**.

## Files and expected exits

Shared inputs:

- `inventory/pedro-shop.toml`: every original inventory item, source URL and
  verification flag retained; YAML null becomes the string `"unknown"`. The
  category cutover is `workholding` → `fixtures`, `measuring` → `gauges`, and
  collet/QCTP sets → `holders`. No missing chuck, reamer or fixture was purchased
  on paper. Rule-readable tool geometry and holder lengths are explicitly unknown
  where the old inventory did not supply them. The centre-drill's 60° centre-seat
  angle is **not** a drill-point angle.
- `shop-policy.toml`: shop-owned, not copied into plans. The default requires
  `tool_resolves`, `sizing`, `op_chain`, `blind_depth`, `inspection`, `coordinates`
  and `zero_check` on `"*"`. Re-fixture, thin-wall and stick-out numbers and their
  citations are unknown and `numbers_verify` remains true.
- `cutting-data.toml`: four HSS / low-carbon-steel rows (face, profile, drill,
  ream), plus the material-force/modulus row. No Machinery's Handbook **31** page
  was verified: the layout sketch is not evidence. Diameter ranges, sfm, chip
  loads, K_c, E and citations are unknown. All dependent RPM/feed cells are `?`.
  The generic `Plain Carbon Steel` alias is a candidate classification, not a
  sourced grade or measured carbon content; no material-property claim follows.

| Part | What it demonstrates | Expected exit |
|---|---|---|
| `pivot-shaft` | Three-jaw drive with a tailstock dead centre, journals/shoulder/both reliefs/both domes, then indicated rechucks and assembly-dependent plain-end fitting. No final hole, flat or indexing. | **4**: no errors; required unknowns remain. |
| `rocker-arm` | The complete three-setup route, integral hub, retained rails/ears and supported final profiling. The real rod-pin centre, bore fit, local thickness and A\|B\|C position requirement replace the layout sketch. | **2**: absent R8 chuck, 6.5 H7 reamer and supported profile fixture. |
| `pivot-bracket` | Seat-up, foot-top-up and side-on ear setups; L-foot relief, arched ear, reamed cross-bore and two hold-down holes. Missing drawing contract stays explicit. | **2**: absent angle plate, R8 chuck and 6.5 mm reamer. |
| `cone-pivot-post/plan.toml` | Four setups from an encompassing one-piece round blank; finish foot B, retain both integral bosses, drill mounting pattern, set the horizontal cone-journal yaw on BS-0, then transfer finished A/B to the crank bore. | **4**: required unknowns, not an approved route. |
| `cone-pivot-post/built-up.toml` | Five setups for a body block plus separately turned, proposed pressed crank boss. Leaf blanks support informational stock-volume comparison. | **2**: drawing permits one-piece only; no note authorizes a pressed joint. |

Exit precedence is **3 > 2 > 4 > 0**: bad input prevents outputs; any error beats
required unknown/unsupported/warn; only clean required subjects permit exit 0.
These expected report exits are independently recomputed by the validator. The
validator itself exits **0** when these intentionally stopped bundles agree.
The pilot candidate exits remain 4 / 2 / 2 / 4 / 2. The combined catalogue
includes seven sampled geometry families, unknown when STEP bytes, stock,
claims, normals or required fixture dimensions are unavailable. Gate and
regeneration evidence is recorded in PLAN §8.

| Plan literal `"unknown"` leaves | Before restoration | After restoration |
|---|---:|---:|
| `pivot-shaft/plan.toml` | 71 | 10 |
| `rocker-arm/plan.toml` | 85 | 12 |
| `pivot-bracket/plan.toml` | 71 | 5 |

Restored fields include stock/blank dimensions and placement, stock-state/edge
offsets, grip/jaw projection/fixed jaw/stop/clamp, coolant, DRO direction and mode,
check jogs and paper, cut directions, rough/finish Z and stock allowances,
spot/exit depths, contour methods/steps and available-gauge inspection methods.
Cutting-data-dependent RPM/feed, unmeasured tooling/holding facts, missing gauges,
STEP/drawing binding and the shaft's actual fitted span remain unresolved.

Each part directory contains `plan.toml`, `features.toml` and parent-regenerated
`expected/report.json` / `expected/traveler.html`. The cone also has
`built-up.toml`, `expected/built-up/report.json`,
`expected/built-up/traveler.html`, and `expected/compare.json`. Comparison rows
retain `part = "cone-pivot-post"` and distinguish `plan.toml` from `built-up.toml`;
there is no generated plan-text file. Plans do not request external coordinate
files: machine-readable numbers are in the report and bench coordinates are on
the sheet. No operative asset lies outside the bundle.

### M5 inventory and output reconciliation

The original shared shop inventory numbers and `verify = true` flags are
unchanged in value. The PM-30MV's spindle-to-table maximum (17 in) and X/Y/Z
travel (23 / 8.75 / 14 in) now live only in `machines.PM-30MV.envelope`
(`inventory/pedro-shop.toml:21–28`) as `{ value, verify = true }` vendor-copy
debt; the former top-level `spindle_to_table_max_in`, `[travel_in]` and
`[table_in]` copies are deleted rather than kept as a second, differently
trusted source, and the unread table size, T-slot pitch, spindle taper and
spindle-stack entries are not modeled at all (the taper remains vendor
identity under `[machines.PM-30MV.spindle]`). Minimum spindle clearance
(`spindle_to_table_min_mm`) and the vise `bed_height_mm` are `"unknown"`.
Every holder carries `gauge_len_mm = "unknown"` and `grip_mm = "unknown"`
(one spelling each; the suffixless `gauge_len` and the holder-level
`projection_mm` keys are gone), and no tool carries a `projection_mm` map yet:
a projection is recorded per (tool, holder) pair on the tool once it is
measured. No measured operator/date/instrument record is fabricated anywhere.

The `envelope` and `travel` findings add concrete `measure:` instructions to
the before-you-start lines, keyed by the exact fact consumed (set member or
tool/holder pair). The vise stack uses the unmeasured bed height, never jaw
height; Z travel is the per-op spindle-nose span (`tip + gauge + projection`),
so it also waits on holder gauges and tool projections; hole and point
centres carry no cutter-radius padding. Mill travel/envelope additionally
need explicit safe `approach_mm` and complete feature/stock extents, which are
plan-input debt; no approach is chosen on the operator's behalf. Lathe
mill-envelope/travel rows are `not_applicable`, and no lathe operation is
asked for a toolpost gauge length: there is no `holder_stack` rule. An
operation naming a holder the inventory lacks (the bracket's and rocker's
`drill-chuck-r8`) is told to add or resolve that holder, not to measure it.
Use `uv run prechips tools --measure` for the sorted, deduplicated list of
exactly the `numbers.measurements` debt behind these five reports (add
`--plan` to scope it, `--inventory` to override the plans' inventory).

All five report/traveler goldens and the cone comparison golden are regenerated
because the operative inventory digest, M5 rule catalogue (`m5-rev7`) and
correct new unresolved findings change their bound hashes/output. Existing
exits remain **4 / 2 / 2 / 4 / 2**: the default required policy is unchanged;
optional M5 `?` findings do not introduce a new gate. A shop that requires
`envelope` or `travel` on `"*"` obtains exit 4 for unresolved measured
feasibility unless an existing error takes precedence. This is output
reconciliation, not evidence of a machine measurement, physical rehearsal or
first article.

### M4 geometry fixtures (`geometry/`)

[`geometry/README.md`](geometry/README.md) documents the discriminating
bundles and their observed FreeCAD behavior. Their inventory contains
authored nominal test tools, collets, vises and parallels, not shop
measurements. Every candidate supplies a numerically placed blank with
allowance and earlier preparation setups with bounded removals. Preparation
tooling and holding debt remains visible; local policies focus the required
geometry rows on the target operation/setup while retaining part-wide
coverage and finish requirements. Errors anywhere still stop the candidate.
Only target scenes have fully authored jaw and parallel poses.

| bundle | STEP | rule it discriminates |
|---|---|---|
| `rocker-jaw-occluded/plan.toml` | real `rocker-arm.STEP`, the consumer's labelled export (same bytes as `../rocker-arm/`; the v38 `NONE`-label spike export was the initial discriminator) | `accessibility`: offset cutter cylinder beside the strap face hits the jaw and the hub boss; `vise` passes |
| `pocket-reach/plan.toml` / `long-reach.toml` | synthetic `pocket-block.STEP` | `reach`: 45 mm floor against a 19 mm flute fails; the 100 mm OAL candidate passes with the holder clear |
| `sharp-corner/plan.toml` | synthetic `slot-block.STEP` | `internal_corner_radius`: sharp vertical pocket corners against a 1/4 in cutter |
| `unclaimed-face/plan.toml` | synthetic `step-block.STEP` | `coverage`: one face cut by no op and not declared as-stock |

The five installed-kernel candidate exits are **2 / 2 / 0 / 2 / 2**.
Block targets are S2; the rocker uses opposed preparation before its S3
upright target. Each known entry-stock render is bound to its own
`setup-S<n>.png`; preparation pictures show the raw/intermediate stock,
not a pre-cleared final part. The long-reach target is clear; the short
cutter hits its holder, the rocker hits jaw/boss material, the sharp
corner fails cutter radius (and sampled accessibility), and the uncovered
step end remains unclaimed. The project gate is recorded per PR.
Each bundle's `features.toml` binds its STEP by `step_sha256`; `author_solids.py` is
provenance for the three synthetic solids and is not a build step (its STEP
header carries a timestamp).

## Source facts, not the PLAN layout sketch

Consumer citations are relative to the read-only [pedropaulovc/harmonic-analyzer](https://github.com/pedropaulovc/harmonic-analyzer)
repository (`harmonic-analyzer/cad/...` and `cad/...` identify the same root).
Named file:line citations were re-read against that tree before carry-over.
Current source values and corrected line ranges are recorded beside dimensions.
`plan.toml` is the plan author's document: blank size/placement, holding, coolant,
direction, jogs/paper, cut/exit allowances, contour steps and capable-gauge methods
are **author's choices**, not facts requiring a source. Restored choices come from
the rev-3 route or are marked `# author's choice`; they still require checker
validation. Measurements, drawing/STEP binding and cutting-data speeds remain
unknown until evidence exists.

- **Shaft**: `cad/scripts/pivot_shaft_spec.py:132–161` defines eight drawing
  dimensions and their precision. All eight are mapped, including the REF
  length, BOTH ENDS dome height and BOTH SHOULDER FACES relief callouts; all three
  Ra 1.6 controls are retained (`:104–127`). The actual span is not 156.67 by
  decree: that value is reference stack arithmetic
  (`cad/scripts/rocker_bank_layout.py:63–107`). The current fit-up instruction
  scribes the south ear's outer face, cuts 1.5–2.0 past the scribe and domes 1.5
  (`cad/scripts/draw_channel_assembly.py:77–82,101–110`). Actual fit binding stays
  unknown. The consumer says “between centres”; this shop route deliberately uses
  a chuck for drive because no lathe dog/drive-plate system is confirmed.
- **Rocker**: all seven existing features survive. The manifest cross-check maps
  the five marked model dimensions, three kept imported dimensions, hole
  callout/BASIC locations, datum/position/finish annotations, and the numbered
  notes (`cad/scripts/rocker_arm_notes.py:41–78`;
  `cad/scripts/draw_rocker_arm.py:269–284,476–549`;
  `cad/scripts/build_rocker_arm.py:570–586`). The rod centre is
  **(133.06740213488345, 16.456064115939025)** in model XY, derived from
  `cad/scripts/rocker_arm_spec.py:33–34,57–59` and
  `cad/scripts/cone_pivot_post_installation.py:19`; not the PLAN sketch's 85 or
  approximate 146. The hub OD is **10.20**, not 14; hub length is
  **7.0565 +0.05/0**, pivot bore **6.50–6.53**, and the #47 hole is
  **1.994–2.094** (`rocker_arm_spec.py:107–126`, `_hole_spec.py:82`,
  `cad/config/title_block.yaml:66`). Position is Ø0.20 to **A|B|C**, not A|B.
  Setup frames A/B are not drawing datums A/B/C.
- **Bracket**: all nine real spec/build features survive. Nominals are sourced
  from `cad/scripts/pivot_bracket_spec.py:21–43,82–102` and the model build. There
  is no registered bracket drawing (`cad/scripts/_drawing_registry.py`,
  `DRAWINGS`); its drawing dimension count, precision and tolerance adoption are
  unknown, not “zero requirements”. The #8-close hole nominal is **4.572** at
  `_hole_spec.py:57`. The selected #15 nominal came from the cited rev-3 route;
  #15 is **not** pinned in the consumer's numbered-drill dictionary. It remains
  a coverage-based, unverified tool identity, not a measured size. The consumer's
  stale “Ø4.2 / ×24” description is not substituted for the current 4.572 / 24.2.

**Handwritten/general-band reconciliation:** the historical shaft/rocker M1
bundles used the title-block numeric inch rows ×25.4: 0.762 / 0.508 / 0.127 mm.
The new cone manifest instead follows its actual rendered metric drawing rows
0.8 / 0.51 / 0.13 mm (`cad/config/title_block.yaml:25–27`), as the cone spec
explicitly adopts them (`cone_pivot_post_spec.py:301–310`). This difference is
recorded, not hidden by changing the three existing fixture contracts. General
cone bands are anchored to their printed dimensions; original CAD nominals
remain separate. REF geometry receives no invented acceptance band. The bracket
does not borrow drawing defaults from another part, and a configured next
revision is not a certified STEP/drawing revision.

### Cone M2 source map and remaining stops

Sources were read from the read-only harmonic-analyzer tree:

- `cad/scripts/cone_pivot_post_spec.py:29–33,49–81`: body Ø42.011×86,
  head Ø42.7506×26.6, crank boss Ø21.93×72.0344 (the corrected 2.8360 in),
  crank bore Ø11.438, cone boss Ø17.2×42.011 and cone bore Ø12.2808. Crank
  north face is model Z−21.3753; far end is Z+50.6591.
- `:59–67,238–245,268–279,327,387` and
  `cad/scripts/draw_cone_pivot_post.py:254–268,1137–1138`: **12.5182° BASIC**
  is the horizontal plan angle between cone/crank bore axes, not bore tilt.
  The fixture preserves four places and explicitly unknown `angle_tol_deg`;
  neither general ±1° nor a conversion of the FCF becomes its landing allowance.
- `spec:132–168`: exact running fit limits are crank 11.413–11.443 and
  cone 12.2558–12.2858. The cone nominal prints 12.281 at three places; re-anchoring
  its limits on that rounded number would shift them 0.0002 mm. This hand-authored
  fixture retains the explicit source fit limits and records that reconciliation,
  rather than silently manufacturing a new fit. Printed height 33.37±0.25 and
  spacing 39.33+0.37/0 are separate requirements; crank height 72.70 is REF
  (`draw:188–190,1134–1135`).
- `spec:79–104,175–176,318`: the mounting station is **derived** 12.98 each
  side (25.96 pitch), not a guessed literal. Through holes retain sourced
  7.14248 with the drilled +0.10/0 row; counterbores print 11.51×6.02 with
  rendered two-place ±0.51 bands.
- `spec:248–280,369–387`: datum A is the finished cone journal bore, B the
  finished foot; **Ø0.10 angularity to A|B belongs to the crank bore** and has
  its own requirement/check. Ra3.2 foot and Ra1.6 running bores/north cone face
  come from `_surface_finish.py:48–54`. Construction setup frames are not extra
  drawing datums. S4 indicates finished A/B from S3, not an earlier pilot.
- `cad/config/parts/cone-pivot-post.yaml:2–7` and `spec:349–355`: MHA-016,
  quantity 1, ferrous_noncritical family, specified paint/masking/oiling, and
  “machined from solid stock or casting.” No note permits built-up construction.
  A stock grade is therefore unknown; a family name is not an AISI/ASTM grade.
- `spec:108–129`: **112300.8902 mm³** is a genuinely sourced analytic feature
  sum and its explicit authority, not an estimated or measured net volume.
  Both comparison candidates use this volume and its citation.
- `draw:254–264` imports the cone-rim exception from
  `cone_gear_shaft_spec.py:79–97,111–113`: **RIMS BREAK 0.1 MAX**, not the
  title block's otherwise applicable 0.25 edge break.

The one-piece **Ø110×120 round** is an **AUTHOR'S CHOICE**, not an inventory
claim. With bar axis along body Y, the crank far-face radial corner is
`hypot(50.6591,21.93/2)=51.8322 mm`, within radius 55. Axial blank length is
86 body +6 foot-facing allowance +28 sacrificial grip. The cone-pad plan
half-extent is 22.3702mm, also within that round. A body-only Ø45 blank would
exclude the integral crank boss and is deliberately **not** asserted. S1's
declared stick-out is 92/110; lower-body turning stops at Y24.5 before the cone
pad's lowest Y24.768. Remaining profiles preserve both integral bosses.

The separate built-up candidate declares two **AUTHOR'S CHOICE** leaf blanks:
46×50×92 rectangular body and Ø25×100 boss. Its lathe declared stick-out is
80/25; a preliminary foot setup adds the fifth setup. The proposed pressed
joint's interface, interference, engagement, press/arbor and strength are
unknown, and no drawing note authorizes it. A lower computed waste ratio cannot
override the construction stop. Neither blank is on hand (`inventory stock=[]`).

The BS-0 lives under inventory **machines**, with worm 40, direct 24×15° and all
18 listed worm circles (`inventory/pedro-shop.toml:88–117`). The independent
validator searches every circle and direct setting: nearest for 12.5182° is
**plate B /23, one crank turn +9 hole spaces**, actual 12.5217391304°,
signed error +0.0035391304°. One setting means **no cycle closure**. Plate
counts remain unverified and BASIC landing acceptance remains unknown, so the
traveler must show a tentative `?`, not an approval.

STEP/drawing revision, exported face sets, setup binding, actual blank grade,
appropriate milling nests/adapters, cutter/holder reach, bore/height/roughness
inspection and A/B angularity inspection method remain unresolved. Existing
lathe tool/chuck identities are retained with their verification debt; unknown
mill/bore tools and holders are explicitly unknown, not fictitious inventory.
RPM/feed derivation, K_c/E and Machinery's Handbook 31 evidence are not supplied.
The fixture is only an authored process/arithmetical contract: it makes **no
physical machining, farm-build, first-article or clearance-completion claim**.

## Report binding and reference vocabulary

All five input paths are repository-relative POSIX paths with real SHA-256s of
file bytes. `step_sha256` is separately recorded at the report root. Reports are
UTF-8, sorted-key JSON with two-space indentation, `ensure_ascii=False`, finite
numbers only and one final LF. Findings are sorted lexicographically by
`(rule, subject)`. To compute `hash`, remove only the `hash` member, serialize the
remaining object **with the same canonical form including its final LF**, and
SHA-256 those bytes. The traveler footer uses the first eight characters:
`prechips 0.1 · report <id>`. HTML is an output, not an input to its own report.
`.gitattributes` pins fixture line endings to LF.
The implemented rule vocabulary is `m5-rev8` (the combined M4 geometry and M5
measured-inventory catalogue; the `expected/` files are regenerated by the
parent after the combined code lands, and a report still stamped `m2-rev6`,
`m4-rev6` or `m5-rev7` has a stale hash); the report retains the reference
ABI's `message` and `expected_exit` names. Finite floats use the JSON encoder's
shortest round-trip representation, not drawing-format rounding. Drawing precision
is applied only to the traveler.


Every finding carries status, numbers, citations and a plain sentence. There
are no rev-3 `fail`, `block` or separate severity fields. Subject domains are:

- `tool_resolves`: each selected reference, plus each cutting op's tool/holder/
  machine compatibility (`S1:10`). A named missing item is an error. Listed
  accessories and set members inherit source/presence verification; unknown
  geometry never becomes a silent fit pass.
- `sizing`, `op_chain`, `blind_depth`, `datum_consistency`: every manifest
  feature, including explicit not-applicable rows. Through-tip records live in
  `blind_depth.numbers.endpoints`; a spot uses depth, a drill uses point length,
  a reamer uses lead. Exit faces come from **local** thickness and advanced
  entry surfaces, never whole stock thickness. Unknown point/lead/exit means
  unknown tip. Non-hole kinds have no hole chain, so are not applicable.
- `inspection`: every feature/tolerance requirement (`feature:requirement`),
  including length/width/height/radius/note-carried dimensions in these complete
  manifests. A `checks.<requirement> = "unknown"` is an unresolved method, not a
  fictional gauge. Missing entries need an error; an available micrometer does
  not prove roughness or a positional tolerance. A feature with no tolerance
  gets an explicit not-applicable subject.
- `order`, `hold_fields`, `headroom`, `zero_check`, `coordinates`: every setup.
  Lathe headroom is unsupported by the mill-only M1 rule. Known nominal frames
  do not certify measured setup binding. `stock_state.top_feature` disambiguates
  the rocker's touched hub face: machining a strap face does not move that top.
  A coordinate row's `local_from = { op, field, axis }` binds a local Z target
  to an authored operation endpoint when its model transform remains unknown;
  it does not bind the fitted shaft length to the nominal reference model.
- `speeds_feeds`: every op, including not-applicable manual operations. No
  turning, spotting or unsourced tool-material row is invented.

The complete input unknown ledger below is exhaustive. Report unknown numbers
are the deterministic consequences of genuinely missing facts: unresolved
speeds/feeds, point/lead/tip endpoints, gauge capability, clearances, measured
trial-cut readings and model binding. Nominal zero recipes and contour offsets
are computed from the authored choices without claiming measured readiness.

## DRO and print surfaces

[Electronica EL400 Operation Manual](https://www.dropros.com/documents/EL400%20OpManual.pdf):
Direction and Radial/Diametric §6.2 (p20), Axis Set in ABS §7.4 (p31), Preset
§8.1 (p37, distance-to-go, **never datum zero**), and lathe trial-cut/touch-off
§9.2.1 (p62). Every recipe gives touch → compensated Axis Set → jog without
retouch → expected/mirrored reading. Physical check jogs are 10 mm; paper touches
use 0.05 mm. Lathe trial-cut X readings and installation stay unknown; an authored
diametric X mode doubles a physical jog's displayed increment, not its distance.

Travelers are Letter portrait: one header plus one page per setup, followed by
coordinate/arc continuation sheets where needed. Fresh CLI outputs rendered in
Chromium after the main-line pickup correction have 7 physical pages for the
shaft, 10 for the rocker and 10 for the bracket; physical pages match the logical
sections. Footers flow after the instructions rather than covering them.
Before-start lines use ✗ / ! / ?. Tables apply explicit drawing precision;
known operative/manual targets retain their supplied numeric form when drawing
precision is absent, without inventing an acceptance band. Actual unknown
numbers remain `?`. Stock state, grip/stop/clamp, clearance, coolant, deburr,
tool/holder, speed/feed, direction, tip and requirement checks are present or
named unknown. No rule ids, paths or full hashes belong on the bench sheet.
Under M4 each setup page carries one kernel figure or the explicit
`? Kernel fixture render unavailable; holding geometry is not confirmed.`
paragraph; the three STEP-less bundles always show the latter, and the
rocker, whose STEP is bound but whose vise is `verify = true`, shows a
part-only view captioned as unresolved on each of its three setup pages
(regenerated `expected/` with three `setup-S<n>.png`, all five files
byte-identical on the integrating agent's repeat run). A browser-rendered
Letter PDF is a layout smoke proof, **not** the physical printed paper rehearsal
or a first article.

## Validation

```console
uv run python scripts/validate_examples.py
uv run ruff check scripts
```

The standard-library validator parses **every example TOML** with `tomllib`,
rejects `"unknown"` in its explicit author-choice field set (including nested
direction/contour values), checks complete rule subjects, manifest/plan references,
enumerated shop items, named missing findings and requirement-keyed inspection,
verifies orthonormal frames and coordinate transforms, tip/exit, Axis Set/finder/
paper/jog/mirror/retouch and speed/feed arithmetic, hashes/canonical JSON/footer
binding and exit precedence. It rejects obsolete YAML/CSV fixtures. It validates
these authored contracts; it is not another machining checker and does not assert
geometry, material properties, gauge calibration, first-article evidence or telemetry.
The cone extension also independently enumerates all inventory indexing settings,
checks signed landing arithmetic and full-pattern-only closure, smallest finished
exposed diameter/verified-ratio arithmetic separately from held OD, explicit
construction permission, and leaf-blank stock/net/waste arithmetic in
`expected/compare.json`. Unbound or incomplete finished profiles stay unknown.
The PR #6 review corrections regenerated only changed output: stick-out evidence,
endmill-with-DOC engagement eligibility and machine-listed BS-0 hold resolution.
All five candidate exits remain 4 / 2 / 2 / 4 / 2; comparison remains 2.
Endpoint arithmetic distinguishes spot/tap depth, blind tip depth and its drawing
guard, and through breakthrough allowance. Reamers use sourced axial lead,
drills use the point cone, and boring/counterboring uses zero drill-cone length;
blind counterbores never acquire a through exit allowance.
The two cone report/HTML pairs and comparison are regenerated only by the parent after
the shared implementation lands; no mid-flight builds, lint, tests, formatting
or golden generation belong to fixture authoring.
The earlier hand-authored sheets rendered to four Letter pages for shaft/bracket
and five for rocker. Those counts do not describe the new generated continuations.
Scoped mutation smoke rejected all 26 named author-choice fields and nested
direction/contour/section unknowns, while allowing RPM, drawing, installation and
missing-gauge unknowns; it also rejected a radius-sized jog in lathe diametric X.
Local-target smoke also rejected a wrong endpoint, missing operation provenance
and an attempt to replace a known model transform with an authored local target.
The M1 CLI now produces these expected files from the five TOML inputs. Its
fixture rehearsal observed exits 4/2/2 and byte-identical reports and HTML on
repeat runs; the numerical validator remains an independent arithmetic gate.

## PLAN rev 6 authoring contracts resolved in M1

1. `src/prechips/model.py` and the five input-format pages under `docs/` define
   the strict TOML schema. Unknown keys are bad input; literal `"unknown"` remains
   unresolved, including nested records. Lathe end stations are not mill heights.
2. Policy metadata uses `numbers_cite` and `numbers_verify` sibling tables.
   Missing policy uses the shop-required seven-rule vocabulary, never plan waivers.
3. Inspection uses exact requirement keys (`position_dia`, `finish_ra`, etc.)
   and all manifest dimension requirements, including explicit manual inspection
   for dimensions completed by another feature's operation.
4. The rule ids, subjects and canonical report ABI above are implemented.
   An absent required rule or subject is unknown, not silently checked.
5. `top_feature` identifies the touched surface; `entry_z` advances separate
   local entry surfaces. Indicated bore pickup has zero finder radius. Unknown
   frame binding never substitutes reference geometry for an actual fit.
6. Lathe diametric X doubles the displayed increment of a physical jog; per-tool
   touches are explicit. M1 mill headroom remains unsupported on a lathe. No
   turning, spotting or unsourced material cutting row is invented.
7. Raw RPM is rounded ties-to-even at 50 rpm **before** clamping once to the
   measured machine range. A non-50 machine boundary is never exceeded and is
   not rounded again. Contact-side compensation and DRO jog polarity are
   independent; reversed directions exchange expected and mirrored readings.
8. Missing bracket drawing bands/precision remain unknown, not adopted from
   another part. Its nominal geometry does not certify drawing acceptance.
9. Unknown STEP binding is permitted as a named unresolved finding. A known
   digest requires actual matching STEP bytes. Approval is separate evidence,
   not an operative input to its own report hash; it needs a matching hash and
   nonblank first-article evidence, and cannot waive required findings.
10. The source shaft has no flat/cross-hole; none is invented to satisfy M2's
    obsolete pilot description.
11. The rocker fixture remains absent/unvalidated. Rails release only under the
    supported S3 route. The proposed stock and support state remains the author's,
    not measured inventory or certified geometry.
12. The renderer uses row-safe natural overflow and bounded per-setup contour
    continuations rather than fixed-height clipping. Logical HTML sections are
    not claims about physical printed pages. Paper rehearsal remains outstanding.

## M1 fixture reconciliation

The implementation does not read `expected/` at runtime. All three report/HTML
pairs were regenerated by `prechips traveler` only after comparing the original
targets with fresh computations and the contracts above.

- **`rocker-arm/features.toml`**: add `hub_od.dia_nominal = 10.20`,
  `top_edge.radius_nominal = 800`, `profile_outer.bottom_radius_nominal = 816`,
  `profile_outer.arc_centre = [0, 816, 0]`, and the explicit
  `top_edge_feature = "top_edge"` relationship. These are the existing source
  facts at `rocker_arm_spec.py:26-27,42-54,112`, re-read during implementation.
  A tolerance-band midpoint is not an authored toolpath nominal.
- **`pivot-bracket/plan.toml`**: promote the existing 1 in riser orientation to
  `support_orientation = "1 in height"`. For S2 ops 10/20, state the open
  free-run sweep's model frame and raw-blank bounds X −9..9, Y 6..33.2,
  Z 3..22.2, opening toward setup −Y. The original stock placement/hold prose
  already supplies these author choices; they are not added to the CAD manifest.
  The approved main-line pickup correction is retained: S2 touches the accessible
  unfinished upper-stock overhang at X −9 / Y −22.2, producing nominal Axis Set
  −11.54 / −24.74 rather than touching the obscured finished foot. S3 explicitly
  declares `zero.z.edge_mm = 0` for the named ear-inner face; its raised stock top
  at 18.2 is not that touch surface. The validator derives named Z edges from
  the plan, never from a report's own answer.
- **Historical M1 `expected/report.json` files**: originally used `rules_version = "m1-rev6"`,
  current input SHA-256s, generic rule sentence/citation templates and fully
  computed evidence records. Hashes change because they bind the entire report.
  All unknown tool geometry, gauges, cutting data, measurements and STEP binding
  remain unknown. Shaft verdicts are unchanged. Duplicate missing-item errors
  are removed from dependent compatibility/sizing rows: the selected missing
  reference owns the error; computations depending on it are unknown.
- **Rocker verdict corrections**: `sizing:pivot_bore` and compatibility
  subjects S1:60, S1:70, S3:20, S3:50 and S3:60 change error → unknown;
  the three missing references remain errors. Manual S3:70/S3:80 no-tool
  compatibility rows are removed, matching the documented subject domain.
- **Bracket verdict corrections**: compatibility subjects S2:60/S2:70/S2:80/
  S2:90 and S3:30/S3:40/S3:50 change error → unknown, leaving the three
  absent references as errors. Datum consistency for foot_top, ear_relief,
  ear_sides, ear_arch, cross_bore and both hold-down holes becomes
  not-applicable: no adopted drawing datum relationship is declared. Nominal
  stations do not create a positional/datum tolerance. S2 ear-side profile
  entry remains Z 27.2, rather than borrowing the free-run floor Z 0.3.
- **All three `expected/traveler.html` files**: regenerate from computed
  evidence, including the PR #5 CodeRabbit precision corrections. Drawing
  dimensions retain declared precision, or their own digits when it is absent;
  operative tip targets, operation-derived coordinate rows, axial Z stations
  and contour cutter-centre tables always print their own numeric values (six
  significant digits). Only genuine unknowns print `?`. Transfer indication lists
  print as bench-readable text rather than Python lists. Footer ids still bind
  the reports; escaped content and row-safe overflow replace hand-curated HTML.

No inventory, policy, cutting-data number, tolerance band, feature or tool
purchase was changed. Expected exits remain **4 / 2 / 2**. The generated reports
contain 103 / 117 / 116 findings respectively; rocker and bracket each emit
exactly three `✗` missing-reference lines.

## Historical M1 `"unknown"` input ledger

Paths below use setup ids and op numbers as array labels, not array offsets.
This is the original M1 nine-TOML restoration ledger, not an exhaustive current
M2 count. The cone's added evidence gaps are listed in its source map above.
`verify = true` with known nominal numbers is additional measurement debt,
not missing numbers: notably vendor machine/vise/support geometry, edge finder,
instrument capability and candidate jaw/grip arithmetic. Clearing verification
requires shop evidence, not an author edit. Historical restoration removed
process-choice omissions without converting measurements into authored facts.

### `cutting-data.toml` — 19 unknown leaves

No verified Handbook 31 table/page or material-property source; no numeric transcription or range guessed.

```text
cut[0].diameter_range
cut[0].sfm
cut[0].chip_load_mm_per_tooth
cut[0].cite
cut[1].diameter_range
cut[1].sfm
cut[1].chip_load_mm_per_tooth
cut[1].cite
cut[2].diameter_range
cut[2].sfm
cut[2].chip_load_mm_per_tooth
cut[2].cite
cut[3].diameter_range
cut[3].sfm
cut[3].chip_load_mm_per_tooth
cut[3].cite
material[0].kc_n_per_mm2
material[0].e_gpa
material[0].cite
```

### `inventory/pedro-shop.toml` — 135 unknown leaves

Rule-readable geometry not recorded; existing inch dimensions are retained, not promoted into measured geometry.

```text
tools.endmills-lms-6784.point_angle
tools.endmills-lms-6784.flute_len
tools.endmills-lms-6784.oal
tools.endmills-lms-6784.dia
tools.endmills-lms-6784.shank
tools.endmills-tin-10pc.point_angle
tools.endmills-tin-10pc.flute_len
tools.endmills-tin-10pc.oal
tools.endmills-tin-10pc.dia
tools.endmills-tin-10pc.shank
tools.center-drills-lms-4859.point_angle
tools.center-drills-lms-4859.flute_len
tools.center-drills-lms-4859.oal
tools.center-drills-lms-4859.flutes
tools.center-drills-lms-4859.dia
tools.center-drills-lms-4859.shank
tools.drill-index-115.point_angle
tools.drill-index-115.flute_len
tools.drill-index-115.oal
tools.drill-index-115.flutes
tools.drill-index-115.dia
tools.drill-index-115.shank
tools.drills-metric.point_angle
tools.drills-metric.flute_len
tools.drills-metric.oal
tools.drills-metric.flutes
tools.drills-metric.dia
tools.drills-metric.shank
tools.tap-die-set-40.point_angle
tools.tap-die-set-40.flute_len
tools.tap-die-set-40.oal
tools.tap-die-set-40.flutes
tools.tap-die-set-40.dia
tools.tap-die-set-40.shank
tools.taps-metric-set.point_angle
tools.taps-metric-set.flute_len
tools.taps-metric-set.oal
tools.taps-metric-set.flutes
tools.taps-metric-set.dia
tools.taps-metric-set.shank
tools.reamers.point_angle
tools.reamers.flute_len
tools.reamers.oal
tools.reamers.flutes
tools.reamers.dia
tools.reamers.shank
tools.countersinks.point_angle
tools.countersinks.flute_len
tools.countersinks.oal
tools.countersinks.flutes
tools.countersinks.dia
tools.countersinks.shank
tools.boring-head-lms-3662.point_angle
tools.boring-head-lms-3662.flute_len
tools.boring-head-lms-3662.oal
tools.boring-head-lms-3662.flutes
tools.boring-head-lms-3662.dia
tools.edge-finder.point_angle
tools.edge-finder.flute_len
tools.edge-finder.oal
tools.edge-finder.flutes
tools.edge-finder.dia
tools.edge-finder.shank
tools.turning-tools-warner-lms-4132.point_angle
tools.turning-tools-warner-lms-4132.flute_len
tools.turning-tools-warner-lms-4132.oal
tools.turning-tools-warner-lms-4132.flutes
tools.turning-tools-warner-lms-4132.dia
tools.turning-tools-warner-lms-4132.shank
tools.boring-bar-warner-lms-1721.point_angle
tools.boring-bar-warner-lms-1721.flute_len
tools.boring-bar-warner-lms-1721.oal
tools.boring-bar-warner-lms-1721.flutes
tools.boring-bar-warner-lms-1721.dia
tools.boring-bar-warner-lms-1721.shank
tools.parting-blade-lms-1728.point_angle
tools.parting-blade-lms-1728.flute_len
tools.parting-blade-lms-1728.oal
tools.parting-blade-lms-1728.flutes
tools.parting-blade-lms-1728.dia
tools.parting-blade-lms-1728.shank
tools.drill-chuck-tailstock-lms-1660.point_angle
tools.drill-chuck-tailstock-lms-1660.flute_len
tools.drill-chuck-tailstock-lms-1660.oal
tools.drill-chuck-tailstock-lms-1660.flutes
tools.drill-chuck-tailstock-lms-1660.dia
tools.drill-chuck-tailstock-lms-1660.shank
tools.hss-lathe-bits.point_angle
tools.hss-lathe-bits.flute_len
tools.hss-lathe-bits.oal
tools.hss-lathe-bits.flutes
tools.hss-lathe-bits.dia
tools.hss-lathe-bits.shank
tools.knurler.point_angle
tools.knurler.flute_len
tools.knurler.oal
tools.knurler.flutes
tools.knurler.dia
tools.knurler.shank
tools.slitting-saws.point_angle
tools.slitting-saws.flute_len
tools.slitting-saws.oal
tools.slitting-saws.flutes
tools.slitting-saws.dia
tools.slitting-saws.shank
fixtures.vise-pm-6.bed_height_mm
holders.r8-collets-lms-4860.gauge_len_mm
holders.r8-collets-lms-4860.grip_mm
holders.er-collets.gauge_len_mm
holders.er-collets.grip_mm
holders.lathe-collets.gauge_len_mm
holders.lathe-collets.grip_mm
holders.qctp-axa-lms-2280.gauge_len_mm
holders.qctp-axa-lms-2280.grip_mm
```

Original YAML null: make, presence, size, capacity, standard or instrument range/resolution was not confirmed.

```text
tools.drills-metric.present
tools.tap-die-set-40.standards
tools.edge-finder.make
tools.edge-finder.present
tools.turning-tools-warner-lms-4132.shank_in
tools.boring-bar-warner-lms-1721.present
tools.parting-blade-lms-1728.present
tools.drill-chuck-tailstock-lms-1660.present
tools.hss-lathe-bits.shank_in
tools.knurler.present
tools.slitting-saws.arbor
fixtures.faceplate-d1-4.diameter_in
fixtures.steady_rest.capacity_in
fixtures.clamping-kit-lms-1144.present
fixtures.drill-press-vise.jaw_width_in
gauges.dial-indicator.range_in
gauges.dti.resolution_in
holders.er-collets.standard
holders.er-collets.present
holders.lathe-collets.standard
holders.lathe-collets.present
```

### `pivot-bracket/features.toml` — 43 unknown leaves

No registered bracket drawing adopts a numeric band, precision or title-block default; sourced nominals are kept separately.

```text
precision
general_tolerances.linear_1pl
general_tolerances.linear_2pl
general_tolerances.linear_3pl
general_tolerances.angular_deg
general_tolerances.drilled_hole
features.foot_profile.width
features.foot_profile.length
features.foot_profile.precision.width
features.foot_profile.precision.length
features.foot_top.height
features.foot_top.precision.height
features.ear_relief.thickness
features.ear_relief.precision.thickness
features.ear_sides.width
features.ear_sides.precision.width
features.hold_down_a.dia
features.hold_down_a.station
features.hold_down_a.precision.dia
features.hold_down_a.precision.station
features.hold_down_b.dia
features.hold_down_b.station
features.hold_down_b.precision.dia
features.hold_down_b.precision.station
features.ear_arch.radius
features.ear_arch.precision.radius
features.cross_bore.dia
features.cross_bore.height
features.cross_bore.precision.dia
features.cross_bore.precision.height
```

No certified STEP bytes / matched drawing export supplied.

```text
step_sha256
```

Nominal numeric frame exists; actual measured part/setup or fitted-span binding does not.

```text
frames.A.binding
frames.B.binding
frames.C.binding
```

Export face-set names and digest-bound feature mapping are not available yet.

```text
features.seat_face.faces
features.foot_profile.faces
features.foot_top.faces
features.ear_relief.faces
features.ear_sides.faces
features.hold_down_a.faces
features.hold_down_b.faces
features.ear_arch.faces
features.cross_bore.faces
```

### `pivot-bracket/plan.toml` — 5 unknown leaves (was 71)

No certified drawing/export revision or adopted drawing edge-break limit:

```text
drawing.revision
setups[S1].deburr_mm
setups[S2].deburr_mm
setups[S3].deburr_mm
```

No radius/profile gauge is listed. Calipers are selected for nominal bore
diameter and height only; absent bracket drawing tolerances remain in the manifest:

```text
setups[S3].ops[20].checks.radius
```

### `pivot-shaft/features.toml` — 16 unknown leaves

No authoritative file-wide class or explicit precision for this particular annotation; other dimensions retain sourced overrides.

```text
precision
```

No certified STEP bytes / matched drawing export supplied.

```text
step_sha256
drawing.revision
```

Nominal numeric frame exists; actual measured part/setup or fitted-span binding does not.

```text
frames.T3.binding
```

Export face-set names and digest-bound feature mapping are not available yet.

```text
features.north_journal.faces
features.shoulder.faces
features.shoulder_thrust.faces
features.body.faces
features.north_relief.faces
features.south_relief.faces
features.north_dome.faces
features.south_dome.faces
features.plain_end.faces
```

Cut-to-fit end depends on actual installed-ear/scribe measurement and chosen final fit; reference geometry is not an as-built value.

```text
features.body.z_mm[0]
features.south_dome.at
features.plain_end.length
```

### `pivot-shaft/plan.toml` — 10 unknown leaves (was 71)

No certified drawing/export revision or confirmed lathe DRO installation:

```text
drawing.revision
dro.controller
```

No roughness comparator in the inventory; no drawing runout limit to borrow:

```text
setups[S1].ops[30].checks.finish_ra
setups[S1].ops[50].checks.finish_ra
setups[S1].ops[60].checks.finish_ra
setups[S2].zero.transfer.runout_limit_mm
setups[S3].zero.transfer.runout_limit_mm
```

Actual scribe/installed-ear binding is unmeasured. Local cut and dome targets
are chosen, but incoming end stations and stick-out cannot be inferred:

```text
setups[S3].stock_state.plain_end_z
setups[S3].stock_state.north_end_z
setups[S3].hold.stickout_mm
```

### `rocker-arm/features.toml` — 16 unknown leaves

No certified STEP bytes / matched drawing export supplied.

```text
step_sha256
drawing.revision
```

Nominal numeric frame exists; actual measured part/setup or fitted-span binding does not.

```text
frames.A.binding
frames.B.binding
```

Broad-face datum is sourced, but which symmetric face is not identified.

```text
datums.B.surface
```

Export face-set names and digest-bound feature mapping are not available yet.

```text
features.pivot_bore.faces
features.rod_hole.faces
features.hub_od.faces
features.hub_faces.faces
features.strap_faces.faces
features.top_edge.faces
features.profile_outer.faces
```

No authoritative file-wide class or explicit precision for this particular annotation; other dimensions retain sourced overrides.

```text
features.pivot_bore.precision.finish_ra
features.rod_hole.precision.at
features.profile_outer.precision.land_angle_deg
```

Radial-land relationship exists, but no numeric angular acceptance band is sourced.

```text
features.profile_outer.land_angle_deg
```

### `rocker-arm/plan.toml` — 12 unknown leaves (was 85)

No certified drawing/export revision or measured/available S3 support geometry:

```text
drawing.revision
setups[S3].hold.supports
```

The shop lacks requirement-capable bore/position, roughness, height, radius,
arc-length and angular gauges/methods. The selected micrometer/caliper methods
for hub diameter, hub length, strap thickness and tip land remain unverified,
but no longer masquerade as missing author decisions:

```text
setups[S3].ops[20].checks.dia
setups[S3].ops[20].checks.finish_ra
setups[S3].ops[30].checks.height_above_pivot
setups[S3].ops[30].checks.radius
setups[S3].ops[30].checks.arc_len
setups[S3].ops[40].checks.bottom_radius
setups[S3].ops[40].checks.bottom_arc_len
setups[S3].ops[40].checks.land_angle_deg
setups[S3].ops[60].checks.dia
setups[S3].ops[60].checks.position_dia
```

### `shop-policy.toml` — 6 unknown leaves

No shop measurement/logbook or authoritative threshold citation supplied.

```text
numbers.refixture_budget_mm
numbers.thin_wall_floor_mm
numbers.stickout_ld_max
numbers_cite.refixture_budget_mm
numbers_cite.thin_wall_floor_mm
numbers_cite.stickout_ld_max
```
