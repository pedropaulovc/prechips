# PLAN rev 6 reference bundles

The **plans remain authored** and every example traveler remains **PLANNED**.
`rocker-arm/`, `pivot-shaft/` and `cone-pivot-post/` consume harmonic-analyzer
`features.toml` exports and their exact adjacent STEP files; the patched keys
listed under "Example divergences" below mean those manifests are no longer
verbatim exports. Each candidate also consumes the three shared shop inputs.
`pivot-bracket/` is hand-authored against the v39 consumer STEP
(`pivot-bracket.STEP`, sha256 `6cd4ab60f57b1c9771cec083fbbd0ef1f94171f1d95f9485a135a4dec0b2dabc`)
and isometric reference, with geometry-matched `#id/ADVANCED_FACE[n]/NONE` face refs.
There is **no dimensioned bracket drawing**: its acceptance bands are plausible
example design intent, individually cited as such, not measured drawing facts.
Neither export delivery nor a CAD face identity is a tooling measurement,
clearance proof, approved route or first article.

### Examples policy: plausible, labelled values

The examples are illustrative. Shop facts the checker needs but nobody has
measured (tool, holder, gauge, machine and fixture dimensions) carry plausible
values labelled `measured = { by = "example (plausible, not measured)", ... }`;
Pedro's real `vise-pm-6` measurements are the only true measurements. Cutting
rows and policy floors cite `example (plausible)`. Unknown semantics are
unchanged: anything still `unknown` keeps its finding unknown.

### Example divergences from consumer exports

| File | Key | Export value → example value | Why |
|---|---|---|---|
| `cone-pivot-post/features.toml` | `construction` | `"one_piece"` → `"built_up_permitted"` | user-approved: treat the drawing as permitting built-up so `built-up.toml` is not refused |
| `cone-pivot-post/features.toml` | `features.mount_west.station_nominal` | `-12.98` → `12.98` | sign bug, [HA #1214](https://github.com/pedropaulovc/harmonic-analyzer/issues/1214) |
| `rocker-arm/features.toml` | `features.tip_land_pos_x.land_angle_deg`, `features.tip_land_neg_x.land_angle_deg` | `"unknown"` → `[89.0, 91.0]` | nominal 90° with the title-block angular ±1° (`title_block.yaml angular.value_deg`); export left the limit unknown |
| `rocker-arm/features.toml` | `precision.land_angle_deg` (both lands) | `"unknown"` → `0` | matches the ±1° whole-degree display |
| `rocker-arm/features.toml` | `material.thickness` | `"unknown"` → `2.5` | drawing manufacturing note 2 states `STRAP 2.50 THICK`; this is the nominal strap, not the integral hub length or supplied blank thickness |
| `rocker-arm/plan.toml` | `drawing.revision` | `"unknown"` → `"v40"` | bind the authored illustrative plan to the source manifest's `drawing.revision`; this does not release or approve the plan |
| `pivot-bracket/features.toml` | all feature bands, general tolerances and precision | no dimensioned drawing → hand-authored plausible example limits | v39 STEP defines nominal geometry only; every feature cites `example (plausible, no dimensioned drawing)` |
| `pivot-shaft/features.toml` | `features.north_relief.corner_radius_max_design`, `features.south_relief.corner_radius_max_design` | absent → `0.25` | design intent `pivot_shaft_spec.py:55-73` (`CORNER_RADIUS_MAX`, the title block's R0.25 MAX corner left by the grooving tool); the export omits the groove sizing limit |

### M3 export delivery provenance

The consumer exporter [HA PR #1208](https://github.com/pedropaulovc/harmonic-analyzer/pull/1208)
merged as `4ae1971db`. These bundles were produced from HA commit `b11124ecf`,
farm run `20261003T164312663Z-bd50248ef1a5451390eb66d157fcfe33`, and copied
from `C:/src/dt-logs/features-bundles/`:

| Source directory | Destination | Adjacent STEP | Exported `step_sha256` |
|---|---|---|---|
| `rocker_arm/` | `examples/rocker-arm/` | `rocker-arm.STEP` | `e5707bbb540b32280712423635a3d5ebd5c1f1cfb6265615b18dfe3453772e9e` |
| `pivot_shaft/` | `examples/pivot-shaft/` | `pivot-shaft.STEP` | `cc8d57b5c73d5de8f7cbcbd53e1fbee1f2a196e69267ecb19d5a23fe2c42d7bc` |
| `cone_pivot_post/` | `examples/cone-pivot-post/` | `cone-pivot-post.STEP` | `5719f3f9ec779ae255f9c880a59c5eba338526576279b4f94a8c22e675e4aa1b` |

Both files in each pair are consumer artifacts, not locally reconstructed
manifests or re-exported solids. Preserve the raw STEP bytes (`.gitattributes
-text`) and generated manifests, including their citations and unknowns.
Delivery metadata belongs here, never in locally added manifest keys.
All three exports declare drawing revision `v40`, `construction = "one_piece"`,
model coordinates in mm, and labelled `HAF_<FEATURE>__P<nn>` face references
with STEP entity and ordinal identities. Revision metadata is not physical
inspection or first-article evidence.

The rocker now exports 10 features, the shaft 9 and the cone 14. The rocker's
`strap_datum_b` maps to `#118/ADVANCED_FACE[5]/HAF_STRAP_DATUM_B__P01`;
`strap_faces` is the separate bottom face. Explicit operation face claims must
follow this STEP, not the old `#492` identity. The old rocker digest
`19070131…` and face identities are historical, not aliases for this export.
The S1 rectangular supply remains a plan choice; an exported finished solid
does not supply the interrupted rail/ear footprints needed for later stock.
The two cone routes still describe one part, not two inventory parts.

The M4 geometry fixtures live under [`geometry/`](geometry/README.md) with
their own inventory, policy and bound STEP files; they are separate fixtures,
not necessarily byte-identical to the current production export. Without
FreeCAD, geometry is unknown and no kernel render exists. With FreeCAD,
exported face sets enable evaluation, not automatic passes. Current M3
regeneration, repeatability and gate evidence belongs in PLAN §8 M3; historical
available-kernel goldens are not proof of the new export-consumption results.

## Files and expected exits

Shared inputs:

- `inventory/pedro-shop.toml`: every original inventory item, source URL and
  verification flag retained; YAML null becomes the string `"unknown"`. The
  category cutover is `workholding` → `fixtures`, `measuring` → `gauges`, and
  collet/QCTP sets → `holders`. No missing chuck, reamer or fixture was purchased
  on paper. Rule-readable tool geometry and holder lengths are explicitly unknown
  where the old inventory did not supply them. The centre-drill's 60° centre-seat
  angle is **not** a drill-point angle. Only the PM 6 in vise carries shop
  measurements: on 2026-10-05 Pedro Paulo Vezza Campos measured its jaw
  height (1.7695 in), jaw width (6.247 in), jaw-plate depth (0.7005 / 0.7010 in;
  the larger is recorded, which jaw gave which reading was not noted), maximum
  opening (6.135 in) and table-to-bed height without the swivel base
  (2.886 in). Each value carries its own `measured` record; the vendor
  nominals stay beside it as comments, and the item's `verify = true`
  identity flag is kept. The rocker and bracket plans' jaw-overlap arithmetic
  now uses the measured jaw height. Bracket S1/S2 use 19.5453 / 3.6703 mm
  engagement with labelled illustrative parallels and no stale verify flags.
  The bracket's S2 tall narrow pair replaces the former 1-2-3-block stack:
  a 50.8 mm-wide block cannot fit between jaws closed on a 16 mm foot.
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

Current expected consumer CLI exits are **0 / 2 / 2 / 2 / 2** for shaft,
rocker, bracket, cone one-piece and cone built-up respectively. The one-piece cone
moved from 4 to 2 because the export's `mount_west` station nominal conflicts
with its band and restored milling frames expose far-side boss claims.
Existing inspection choices follow the exported feature
owners, using separate inspection steps where needed, without changing gauges or
inventing methods. The earlier split-feature inspection errors were migration
regressions, not legitimate new debt; they are corrected. Regenerated CLI
outputs, the cone comparison exit and combined gate evidence are recorded in
PLAN §8 M3.

| Part | What it demonstrates | Current exit |
|---|---|---|
| `pivot-shaft` | Three-jaw drive with a tailstock dead centre and follow rest, journals/shoulder/both reliefs/both domes, then indicated rechucks and assembly-dependent plain-end fitting. No final hole, flat or indexing. | **0**: every required subject passes; all three setups render with their fixtures modeled. |
| `rocker-arm` | Four setups: retained rail frame with a modeled magnetic end stop, permanent rod-hole pin and supported hub ream, then shoulder-screw profiling with independently held scrap. | **2 (legacy proof)**: `940cb9d` artifacts are stale. Legal cutter-centre/occluder handling and physical-stop rendering await current-source exit-0/all-scene proof. |
| `pivot-bracket` | Seat-up, foot-top-up and side-on ear setups; L-foot relief, arched ear, reamed cross-bore and two hold-down holes. The v39 STEP is bound; bands remain explicitly illustrative without a dimensioned drawing. | **2**: physical inventory and authored setup data are complete; all three native fixture scenes are modeled without debts. Legal planar cutter poses, the finish-floor cut plane and preceding-operation stock clearance remain engine-owned accessibility stops. |
| `cone-pivot-post/plan.toml` | Four setups from an encompassing one-piece blank; integral bosses, mounting pattern, BS-0 journal yaw and A/B transfer. | **2**: exported `mount_west` nominal is outside its band, and S2:40/50 boss-face claims include faces pointing away from the milling approach; required unknowns also remain. |
| `cone-pivot-post/built-up.toml` | Five authored setups for a block plus proposed pressed boss; finished volume and waste remain unknown. | **2**: one-piece-only construction, the `mount_west` nominal conflict, and S2:50 far-side cone-boss claims. |

### Rocker-arm supported route

The illustrative rocker plan binds the exported `v40` drawing revision and
uses drawing note 2's nominal 2.50 mm strap thickness. Neither this binding nor
a clean checker exit is released-plan approval or a measured first article.

The checked-in rocker artifacts are a **stale legacy baseline** from
`940cb9d`, not verification of the current engine or the revised physical
holding below. The native distance and setup-entry removal-mask fixes are now
integrated; StockRoutes' legal cutter-centre/occluder correction and
SetupRender's physical-stop rendering are still being completed. Fresh
exit-0/all-scene output, not the historical baseline, is the acceptance proof.

The four holding states are explicit, rather than pretending a clamp can move
halfway through a fixed setup:

- **S1/S2 — retained rail frame in the vise.** A **340 × 65 × 16 mm** example
  blank puts the full-thickness rails and end ears outside the entire 9.525 mm
  roughing-cutter sweep, not just its centreline. Opposed roughing retains a
  0.40 mm connecting web. The 1/2 in parallels sit entirely beneath the rails
  on matched **76.2 × 64 × 25.4 mm** ground riser bars, with 0.5 mm clearance
  to each closed jaw and 6.8453 mm nominal vertical jaw engagement. A modeled
  magnetic end stop touches the left blank end for positioning only; it carries
  no cutting load and does not modify Pedro's vise. S2 adds adjustable passive
  jacks under the S1-finished strap, set to just contact without lifting the
  rails. The rod hole is spotted, drilled 1.90 mm and reamed 2.00 mm before the
  outside pockets leave only the web.
- **S3 — supported upper hub and ream.** Stepped padded straps press over the
  fixture pads; their studs are outside the whole blank and their bridges
  clear the retained rails. Indicate the empty plate bore first, lower the blank
  straight down onto the permanent rod-hole diamond pin and pads, confirm the
  pilot is within 0.20 mm radial of the plate axis, and then indicate the pilot
  as working A. Stop for a rod-hole/pilot-spacing mismatch; do not force it over
  the pin. The 8 mm stand relief gives the 6.512 mm reamer clearance. Match
  rail-rest shims after seating the finished strap on the pads; no fixed spacer
  is allowed to lift it. No profile cut crosses these straps.
- **S4 — pinned, shoulder-screw profile fixture.** Remove the S3 straps while
  leaving the part seated on the permanent diamond pin and support pads; fit the shoulder screw and bored washer
  through the reamed pivot bore. The pin is the positive tangential clocking
  stop. Preload counterclockwise viewed from above (looking down setup -Z)
  before tightening, then indicate the screw head ground coaxial with its shoulder.
  The screw prevents lift and the twelve pads carry Z, not cutting torque.
  Separate toe clamps retain the scrap rails on matched shimmed rests, so
  neither the part nor the scrap becomes loose when the final web releases.

Final inspection checks both hub patches against the reamed datum, and rod
position against A|B|C with face B seated and the finished rod-side land C
squared. Fixture dimensions and primitive solids in the rocker additions
block carry `example (plausible, not measured)` labels; these are authored
example clearances, not approved CAM toolpaths or actual shop measurements.
The letter-D pilot leaves about 0.264 mm diametral reaming stock. Custom metric
GO/NO-GO plugs verify the 6.500..6.530 bore. The rod's process GO 2.000 /
NO-GO 2.010 plugs control a reamed hole, not an unrealistically close twist
drill; the 1.9875 mm stop has 0.0125..0.0225 mm diametral clearance.
A 1 µm test indicator records pivot pilot-to-ream centre shift against the
0.020 mm radial process limit, and final rod position uses a 1 µm digital
height gauge. The pin takes tangential finish loads but no clamp or lift load.


Exit precedence is **3 > 2 > 4 > 0**: bad input prevents outputs; any error beats
required unknown/unsupported/warn; only clean required subjects permit exit 0.
The validator independently recomputes report exits and itself exits **0**
when the intentionally stopped bundles agree. The historical pilot exits
were 4 / 2 / 2 / 4 / 2. The combined catalogue includes seven sampled geometry
families, unknown when STEP bytes, stock, claims, normals or required fixture
dimensions are unavailable. Current gate and regeneration evidence is recorded
in PLAN §8 M3; do not preserve a historical exit by suppressing new findings.

| Historical plan literal `"unknown"` leaves | Before restoration | After restoration |
|---|---:|---:|
| `pivot-shaft/plan.toml` | 71 | 10 |
| `rocker-arm/plan.toml` | 85 | 12 |
| `pivot-bracket/plan.toml` | 71 | 5 |

Restored fields include stock/blank dimensions and placement, stock-state/edge
offsets, grip/jaw projection/fixed jaw/stop/clamp, coolant, DRO direction and mode,
check jogs and paper, cut directions, rough/finish Z and stock allowances,
spot/exit depths, contour methods/steps and available-gauge inspection methods.
Cutting-data-dependent RPM/feed, unmeasured tooling/holding facts, missing gauges,
measured setup binding and the shaft's actual fitted span remain unresolved.

Each part directory contains `plan.toml`, `features.toml` and parent-regenerated
`expected/report.json` / `expected/traveler.html`. The cone also has
`built-up.toml`, `expected/built-up/report.json`,
`expected/built-up/traveler.html`, and `expected/compare.json`. Comparison rows
retain `part = "cone-pivot-post"` and distinguish `plan.toml` from `built-up.toml`;
there is no generated plan-text file. Plans do not request external coordinate
files: machine-readable numbers are in the report and bench coordinates are on
the sheet. No operative asset lies outside the bundle.

### Historical M5 inventory and output reconciliation

The original shared shop inventory numbers and `verify = true` flags are
unchanged in value. The PM-30MV's spindle-to-table maximum (17 in) and X/Y/Z
travel (23 / 8.75 / 14 in) now live only in `machines.PM-30MV.envelope`
(`inventory/pedro-shop.toml:21–28`) as `{ value, verify = true }` vendor-copy
debt; the former top-level `spindle_to_table_max_in`, `[travel_in]` and
`[table_in]` copies are deleted rather than kept as a second, differently
trusted source, and the unread table size, T-slot pitch, spindle taper and
spindle-stack entries are not modeled at all (the taper remains vendor
identity under `[machines.PM-30MV.spindle]`). Minimum spindle clearance
(`spindle_to_table_min_mm`) and, at that cutover, the vise `bed_height_mm`
were `"unknown"`; the vise bed height is now the measured `bed_height_in`
described under shared inputs above.
Every holder carries `gauge_len_mm = "unknown"` and `grip_mm = "unknown"`
(one spelling each; the suffixless `gauge_len` and the holder-level
`projection_mm` keys are gone), and no tool carries a `projection_mm` map yet:
a projection is recorded per (tool, holder) pair on the tool once it is
measured. No measured operator/date/instrument record is fabricated anywhere.

The `envelope` and `travel` findings add concrete `measure:` instructions to
the before-you-start lines, keyed by the exact fact consumed (set member or
tool/holder pair). The vise stack uses the vise bed height, never jaw
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

At the M5 cutover, all five report/traveler goldens and the cone comparison
golden were regenerated because the operative inventory digest, M5 catalogue
(`m5-rev7`) and new unresolved findings changed their bound hashes/output.
That historical gate retained exits **4 / 2 / 2 / 4 / 2**: the default required
policy was unchanged; optional M5 `?` findings did not introduce a new gate.
A shop that requires `envelope` or `travel` on `"*"` obtains exit 4 for
unresolved measured feasibility unless an existing error takes precedence.
This was output reconciliation, not evidence of a machine measurement,
physical rehearsal or first article, and not the M3 consumption gate.

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
Clearing bounds are restricted to the claimed XY footprint plus known cutter
radius. With unknown preparation tools, the synthetic rocker supply/clearance
uses the STEP global XY bbox and retains only its authored 1 mm Z allowances;
it no longer invents an unclaimed extra XY footprint.

| bundle | STEP | rule it discriminates |
|---|---|---|
| `rocker-jaw-occluded/plan.toml` | real `rocker-arm.STEP`, a separately bound consumer export (the v38 `NONE`-label spike export was the initial discriminator) | `accessibility`: offset cutter cylinder beside the strap face hits the jaw and the hub boss; `vise` passes |
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
The generated manifests retain Python `file:line`/line-range citations and YAML
`file:dotted.key.path` citations. Use their per-fact citations as the current
authority; older line references below document the historical reconciliation.
`plan.toml` is the plan author's document: blank size/placement, holding, coolant,
direction, jogs/paper, cut/exit allowances, contour steps and capable-gauge methods
are **author's choices**, not facts requiring a source. Restored choices come from
the rev-3 route or are marked `# author's choice`; they still require checker
validation. Measurements, measured setup binding and cutting-data speeds remain
unknown until evidence exists; exported drawing/STEP identities are now present.

### Current export contract changes

All three exports use the rendered metric general bands **0.8 / 0.51 /
0.13 mm**, cited to `cad/config/title_block.yaml:linear_1pl.display`,
`:linear_2pl.display` and `:linear_3pl.display`. The shaft and rocker no longer
use the handwritten inch-conversion bands. The rocker and cone preserve the
material choice `LOW-CARBON STEEL OR GRAY IRON`; the shaft specifies AISI 1018
cold-finished Ø10 bar. No family label selects a verified cutting-data row.

The rocker adds explicit `strap_datum_b`, `tip_land_pos_x` and `tip_land_neg_x`
requirements to the former seven-feature map; the tip-land angular acceptance
remains unknown. The shaft separates the shoulder's north and thrust faces and
both relief/dome face sets. The cone exports `journal_bore`, separate mount
holes/counterbores and both boss end faces. Its journal-bore requirements include
an explicit `"unknown"` identity, while its crank bore carries `separation`,
`angularity_dia` and `angularity_datums`. Current exported height limits are
33.118–33.618 and separation limits 39.332–39.702 mm. Preserve these facts
verbatim rather than rebasing them onto an older rounded handwritten target.

The cone export has **no `volume_mm3` or `volume_cite`**. Finished volume and
waste therefore remain unknown in current comparisons. The older analytic
volume below is historical context, not permission to modify the export.
Setup bindings, missing inventory, material choice, inspection methods and
physical readiness remain separate debt.

The shaft and cone exports carry `frames.setup = "unknown"`. Their plans restore
the former shaft T1/T2/T3 and cone/built-up lathe and M2/J3/C4 transforms as
plan-authored `[frames.<name>]` tables. These are **author's choices** with plan
citations, not CAD facts. The shaft's T3 binding is `nominal`: the example
assumes the fit-up scribe landed at the REF span 156.67, so the S3 plain-end and
north-end stations and stick-out are numeric.

The shaft route (example plan) is: S1 grips the north stub in the three-jaw
chuck, with the MT3 dead centre in the centre-drilled plain end and the follow rest
riding the 26:1 body on the turned side, 8 mm behind the tool (example jaw
sizes 12 × 40 × 10 mm at 90° and 180°). It roughs and finishes the bearing toward the chuck,
faces the thrust shoulder, mics the Ø10 shoulder left as cold-finished bar and
plunges the south DIN 509 relief with the 1/16 in HSS parting blade. S2 reverses
onto the finished body with the thrust face seated on the jaw fronts to turn the
journal, face the shoulder's north face, plunge the north relief and form the
north dome with the 93° AR tool (the 60° E gouges near the apex). S3 grips 8 mm
north of the scribe, parts the plain end to the 1.5–2.0 past-scribe band with
the blade and forms the south dome on the parted face with the AR tool.

The shaft export's `pivot_bearing` has only the `CUT TO FIT` note and
`length_ref = 156.67`, with no cut-to-fit length requirement. The plan therefore
checks the cut-to-fit band through S3 op 10's `inspection_note` (caliper depth
rod from the actual scribe) and does not claim a `pivot_bearing:length`
inspection.

The cone's indexing feature is now `crank_bore`, which owns
`land_angle_nominal_deg = 12.5182` and the BASIC relationship. Its omitted
`angle_tol_deg` remains unresolved. The consumer does not apply the title-block
±1° to a BASIC angle, and it does not convert the Ø0.10 angularity zone into
degrees itself. HA does derive `CRANK_BORE_ANGLE_LIMIT_DEG` ≈ 0.0795°
(`cad/scripts/cone_pivot_post_spec.py:373`), but it does not export that value.
The exported `mount_west.station_nominal = -12.98` is signed, while its
`station` band [12.47, 13.49] is absolute (`cad/scripts/export_features.py:566`).
The consumer's generic nominal-within-band check reports `mount_west:station`
as an `error`, so the one-piece cone exits 2. This is an HA export follow-up.
Prechips does not flip the sign or drop the field.

The restored milling frames also expose genuine far-side face claims on
one-piece S2:40/50 and built-up S2:50. These remain errors and need an authored
route/claim correction, not an HA sign fix. By contrast, the engine's −Z-only
approach model does not cover radial lathe cuts: their directional geometry
and dependent finish coverage are `unsupported`, not false failures or passes.
The radial lathe approach model is a separate prechips follow-up in PLAN §8 M3.

These gaps and the missing HA `check:traveler_pivot_shaft` /
`check:traveler_cone_pivot_post` tasks are listed as open HA items in PLAN §8 M3.
Only the consumer side of M3 is done.

### Historical M1 source reconciliation

The following shaft/rocker/bracket notes record the source readings used for
the original authored manifests. They are not a current feature-count or
citation map for the generated exports. The bracket remains authored.

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
- **Bracket**: ten hand-authored features map all 16 v39 STEP faces; the added
  `outer_face` owns the single plane shared by the ear outer face and foot near
  end. There is no registered dimensioned bracket drawing. Plausible example
  limits are individually cited, not consumer acceptance claims. Nominal
  geometry follows the STEP/spec: 16 mm foot width, 24.2 mm foot run, 6 mm foot
  height/ear thickness, 14 mm ear width, R7 crown, 4.572 mm hold-down holes and
  6.50 mm reamed cross-bore at 25.2 mm above the seat. The #15 drill and
  1/4 in predrill have labelled illustrative dimensions in the inventory.

**Historical handwritten/general-band reconciliation:** the shaft/rocker M1
bundles used title-block numeric inch rows ×25.4: 0.762 / 0.508 / 0.127 mm.
The M2 cone used rendered metric rows 0.8 / 0.51 / 0.13 mm. That difference was
preserved at the time rather than rewriting earlier fixtures. M3 now consumes
the exported metric bands for all three drawn parts. REF geometry still
receives no invented acceptance band in consumer exports. Bracket bands are
instead explicit illustrative design choices under the examples policy.
Exported revision metadata is not a physical verification claim.

### Historical cone M2 source map and authored route

These source readings describe the former hand-authored manifest, not the
current exported field names or acceptance bands. Current facts come from the
verbatim export above; the authored stock/route choices below remain distinct.

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
- `cad/config/parts/cone-pivot-post.yaml` (historical metadata reading) and `spec:349–355`: MHA-016,
  quantity 1, ferrous_noncritical family, specified paint/masking/oiling, and
  “machined from solid stock or casting.” No note permits built-up construction.
  A stock grade is therefore unknown; a family name is not an AISI/ASTM grade.
- `spec:108–129`: **112300.8902 mm³** was the sourced analytic feature sum
  used by both historical M2 comparison candidates. It is not a measured net
  volume, and the current exported manifest does not carry it.
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
unknown, and no drawing note authorizes it. A lower historical computed waste
ratio cannot override the construction stop; current waste is unknown without
an exported finished volume. Neither blank is on hand (`inventory stock=[]`).

The BS-0 lives under inventory **machines**, with worm 40, direct 24×15° and all
18 listed worm circles (`inventory/pedro-shop.toml:88–117`). The independent
validator searches every circle and direct setting: nearest for 12.5182° is
**plate B /23, one crank turn +9 hole spaces**, actual 12.5217391304°,
signed error +0.0035391304°. One setting means **no cycle closure**. Plate
counts remain unverified and BASIC landing acceptance remains unknown, so the
traveler must show a tentative `?`, not an approval.

The STEP/drawing revision metadata and exported face sets are now supplied.
Measured setup binding, actual blank grade, appropriate milling nests/adapters,
cutter/holder reach, bore/height/roughness inspection and A/B angularity
inspection methods remain unresolved. Existing lathe tool/chuck identities
retain their verification debt; unknown mill/bore tools and holders remain
unknown, not fictitious inventory. RPM/feed derivation, K_c/E and Machinery's
Handbook 31 evidence are not supplied. The authored process makes **no physical
machining, first-article or clearance-completion claim**. The producing CAD
farm run is not the separate prechips parented farm-telemetry acceptance.

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
measured-inventory catalogue). The integrating parent regenerated `expected/`
from actual CLI outputs; a report still stamped `m2-rev6`, `m4-rev6` or
`m5-rev7` has a stale hash. The report retains the reference ABI's `message`
and `expected_exit` names. Finite floats use the JSON encoder's
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

The historical M1 input-unknown ledger below records that reconciliation,
not an exhaustive list for today's generated exports. Current report unknown
numbers follow missing facts: speeds/feeds, tip endpoints, gauge capability,
clearances, measured trial-cut readings and setup binding. Nominal zero recipes
and contour offsets do not claim measured readiness.

## DRO and print surfaces

[Electronica EL400 Operation Manual](https://www.dropros.com/documents/EL400%20OpManual.pdf):
Direction and Radial/Diametric §6.2 (p20), Axis Set in ABS §7.4 (p31), Preset
§8.1 (p37, distance-to-go, **never datum zero**), and lathe trial-cut/touch-off
§9.2.1 (p62). Every recipe gives touch → compensated Axis Set → jog without
retouch → expected/mirrored reading. Physical check jogs are 10 mm; paper touches
use 0.05 mm. Lathe trial-cut X readings and installation stay unknown; an authored
diametric X mode doubles a physical jog's displayed increment, not its distance.

Travelers are Letter portrait: one header plus one page per setup, followed by
coordinate/arc continuation sheets where needed. Historically, CLI outputs
rendered in Chromium after the main-line pickup correction had 7 physical
pages for shaft, 10 for rocker and 10 for bracket, matching logical sections.
Those counts are not a new M3 layout observation. Footers flow after instructions.
Before-start lines use ✗ / ! / ?. Tables apply explicit drawing precision;
known operative/manual targets retain their supplied numeric form when drawing
precision is absent, without inventing an acceptance band. Actual unknown
numbers remain `?`. Stock state, grip/stop/clamp, clearance, coolant, deburr,
tool/holder, speed/feed, direction, tip and requirement checks are present or
named unknown. No rule ids, paths or full hashes belong on the bench sheet.
Under M4 each setup page carries a kernel figure or the explicit
`? Kernel fixture render unavailable; holding geometry is not confirmed.`
paragraph when a kernel render cannot be produced. The bracket now carries
the digest-bound v39 STEP and explicit setup-entry stock routing. Its S1/S2
vises include posed parallel pairs; S3 includes the angle plate, a load-bearing
foot-end ledge and a two-stud bridge strap pressing the foot toward the seat datum.
Historical rocker pictures and
repeatability observations do not establish current outputs; see PLAN
§8 M3 for the parent gate. A browser-rendered Letter PDF is a layout smoke
proof, **not** the physical printed paper rehearsal or a first article.

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
Historically, the PR #6 review corrections regenerated only changed output:
stick-out evidence, endmill-with-DOC engagement eligibility and machine-listed
BS-0 hold resolution. That gate retained candidate exits 4 / 2 / 2 / 4 / 2 and
comparison exit 2; it is not M3 export-consumption evidence.
Endpoint arithmetic distinguishes spot/tap depth, blind tip depth and its drawing
guard, and through breakthrough allowance. Reamers use sourced axial lead,
drills use the point cone, and boring/counterboring uses zero drill-cone length;
blind counterbores never acquire a through exit allowance.
The integrating parent regenerated current report/HTML pairs, renders and
comparison from the combined implementation. PLAN §8 M3 records the evidence;
documentation work did not run builds, lint, tests, formatting or golden generation.
Historical M1 sheets rendered to four Letter pages for shaft/bracket and five
for rocker before generated continuations. Historical scoped mutation smoke
rejected all 26 named author-choice fields and nested direction/contour/section
unknowns, while allowing RPM, drawing, installation and missing-gauge unknowns;
it also rejected a radius-sized jog in lathe diametric X. Local-target smoke
rejected a wrong endpoint, missing operation provenance and replacement of a
known model transform with an authored local target. The historical M1 CLI
rehearsal observed exits 4/2/2 and byte-identical reports/HTML on repeat runs;
the numerical validator remains an independent arithmetic gate.

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
8. Missing bracket drawing bands are not consumer drawing facts. The illustrative
   example adopts plausible bands and labels every feature's design provenance.
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

## Historical M1 fixture reconciliation

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

### `pivot-bracket/` — completed-data provenance

The former 43-leaf missing-feature ledger is superseded by the v39 STEP-bound,
hand-authored manifest. No dimensioned drawing was found, so bands are plausible
example design intent rather than imported drawing acceptance limits.

S1 faces the seat and profiles only the foot-depth region, with explicit bounded
clearance retaining the upper-ear stock for S2/S3. S2 stands the foot on one
41.275 mm tall narrow parallel pair (not wide blocks under closed jaws).
Both vise holds use no longitudinal end stop: each blank is clamped, then
edge-found against the raw faces for its own DRO zero. No unmodeled stop is
claimed. The S2 foot's 3.6703 mm jaw engagement leaves its top 2.3297 mm above
the jaws; tool exits remain between the narrow parallels.
The open relief clears the raw free-run overhang, not merely the finished-face
footprint. The early relief operations claim only the retained inner wall, not
the whole floor. Separate outside-in left/right side-slot rasters retain the
rectangular crown; the 31.75 mm long-flute cutter reaches the 26.2 mm inner wall
with 37 mm projection. All wall finish passes stop at Z +0.1, keeping a common
floor skin. Only after the side strips are open does S2:56 claim and skim the
whole foot-top floor, including its narrow side ledges, to Z0. Both hold-down
holes then drill over an open central exit gap.
A stiff 3/8 in 120-degree spotter projects 31 mm from the chuck, keeping its nose
above the uncut ear; a 0.6 mm tip depth makes a 2.08 mm spot.

S3 uses the angle plate's bolted foot-end ledge to resist downward cutting loads,
with a 63.5 × 12.7 × 9.525 mm bridge strap bearing on the free foot top.
Its two 3/8-16 studs, front/rear washers and nuts are modeled; scoped bores
keep the studs clear of the beam and pass through the angle-plate upright.
The strap force points toward the seat, and the foot-end ledge takes the
downward tool load rather than relying only on clamp friction.
The indicated transfer includes the actual `seat_face` height datum; the Y
edge-finder pickup uses the plate front beside the part, not the thin seat lip.
Datum A is labelled "finished seat face" at the bench, not by a CAD-frame coordinate.
The two setup transfers use an authored 0.001 in (0.0254 mm) TIR limit, two
divisions of the existing 0.0005 in test indicator; this is an alignment target,
not a claim that the setup has already been measured.
After the shared outer face is finished, S3:11 checks the final 6 mm ear thickness
(the S2 in-process ear was still 7 mm). The R7 arch gets a radius-gauge check.
The crown's explicit S3 clearance box removes the retained cap without using
the earlier straight side slots to fabricate an arched form from above.
The reamed bore uses paired metric 6.500 mm go / 6.530 mm no-go pins rather than
inch-increment pins; after release, the seat rests on the surface plate and a
height gauge reads the go-pin top minus half its diameter for the bore height.

The plan and manifest use revision `example-v39` for this local illustrative
contract, explicitly **not** a certified dimensioned drawing revision. All setup
frames are nominal, not physical alignments already performed.


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

### `pivot-shaft/plan.toml` — 1 unknown leaf (was 10, originally 71)

No certified drawing/export revision:

```text
drawing.revision
```

The other nine leaves now hold example values (examples policy). These are the
EL400 lathe DRO, which is noted on `machines.PM-1127VF-LB.control`; the
roughness-comparator `finish_ra` checks; 0.02 mm transfer runout limits; and the
nominal-scribe S3 stations and stick-out.

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
