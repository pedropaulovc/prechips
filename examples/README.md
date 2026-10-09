# Reference bundles

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
| `cone-pivot-post/features.toml` | `features.journal_bore.requirements` | `[..., "unknown"]` → `["dia", "thru", "finish_ra", "height"]` | the export's `"unknown"` entry is the RIMS BREAK 0.1 MAX callout (`cone_gear_shaft_spec.py:113`, `draw_cone_pivot_post.py:264`); the plan carries it as `deburr_mm = 0.1` on the journal setups |
| `cone-pivot-post/features.toml` | `features.crank_bore.angle_tol_deg` | absent → `0.0795` | HA's derived limit `CRANK_BORE_ANGLE_LIMIT_DEG = atan(0.10 / 72.0344)` (`cone_pivot_post_spec.py:373-375`) for the BASIC 12.5182° angle; not an independent ± band, and the validator pins it to the FCF arithmetic |
| `cone-pivot-post/features.toml` | `features.body.corner_radius_max_design` | absent → `0.25` | the CAD body/head step corner is sharp and the cone spec states no step-corner limit; the example applies the title-block `R0.25 MAX` edge break HA uses for step corners elsewhere (`pivot_shaft_spec.py:73`, `crankshaft_spec.py:110`), so the bonded route's turned shoulder has a limit to check ([HA #1215](https://github.com/pedropaulovc/harmonic-analyzer/issues/1215)) |
| `cone-pivot-post/features.toml` | `features.cone_boss_south_face.length`, `length_nominal`, `precision.length` | absent → `[41.5, 42.52]`, `42.011`, `2` | the export attaches the 42.011 cap-to-cap length band only to the north cap; the example copies the same band onto the south cap that terminates it, without adding a requirement ([HA #1215](https://github.com/pedropaulovc/harmonic-analyzer/issues/1215)) |
| `cone-pivot-post/features.toml` | `features.foot_seat.height`, `height_nominal`, `precision.height` | absent → `[85.2, 86.8]`, `86.0`, `1` | the export attaches the 86.0 foot-to-top band only to `body`; the example copies the same band onto datum face B that terminates it, without adding a requirement ([HA #1215](https://github.com/pedropaulovc/harmonic-analyzer/issues/1215)) |
| `cone-pivot-post/features.toml` | `material.finish` | `"...; 50-75 um DFT; MASK MACHINED FACES; OIL BARE FACES ISO VG 32"` → `"...; 50-75 um DFT; built-up variant: paint RAL 6005 on non-functional turned ODs; mask bores, faces and joint surfaces; OIL BARE FACES ISO VG 32"` | binding author decision: the built-up post is turned all over, so masking every machined face would leave nothing to paint; `built-up.toml` S12 paints the body, shoulder, head and projecting crank-sleeve ODs and masks the bores, faces and joint surfaces by name ([HA #1215 comment](https://github.com/pedropaulovc/harmonic-analyzer/issues/1215#issuecomment-6030603028)) |
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

The delivered pairs were consumer artifacts, not locally reconstructed
manifests or re-exported solids. Their raw STEP bytes remain unchanged
(`.gitattributes -text`). The current manifests contain the labelled example
divergences listed above and the example-derived cone volume described below;
preserve other source facts, citations and unknowns. Delivery metadata belongs
here, never in locally added manifest keys.
All three exports declare drawing revision `v40`, `construction = "one_piece"`,
model coordinates in mm, and labelled `HAF_<FEATURE>__P<nn>` face references
with STEP entity and ordinal identities. Revision metadata is not physical
inspection or first-article evidence.

The rocker exports 10 features, the shaft 9 and the cone 14. The rocker's
`strap_datum_b` maps to `#118/ADVANCED_FACE[5]/HAF_STRAP_DATUM_B__P01`;
`strap_faces` is the separate bottom face. Explicit operation face claims must
follow the bound STEP entity and ordinal identities.
The S1 rectangular supply remains a plan choice; an exported finished solid
does not supply the interrupted rail/ear footprints needed for later stock.
The built-up cone route describes one inventory part with plan-owned joints.

The M4 geometry fixtures live under [`geometry/`](geometry/README.md) with
their own inventory, policy and bound STEP files; they are separate fixtures,
not necessarily byte-identical to the current production export. Without
FreeCAD, geometry is unknown and no kernel render exists. With FreeCAD,
exported face sets enable evaluation, not automatic passes. Local regeneration,
repeatability evidence and remaining acceptance belong in PLAN §8 M3.

The reference validator accepts a nominal-less dome only when its diameter
matches the base fixed by declared `base_radius` or `sphere_radius` and scalar
height, its kernel span is cited, coverage is complete and it fits held stock.
Other missing, explicitly unknown or contradictory diameter nominals stay
unresolved; a repeated numeric report field is not independent geometry evidence.

## Files and expected exits

Shared inputs:

- `inventory/pedro-shop.toml`: inventory items retain their source URLs and
  verification flags. Categories are `fixtures`, `gauges` and `holders`;
  unavailable facts use the string `"unknown"`. Tool and holder dimensions
  supplied for the illustrative routes carry plausible example values labelled
  not measured. The centre-drill's 60° centre-seat
  angle is **not** a drill-point angle. Only the PM 6 in vise carries shop
  measurements: on 2026-10-05 Pedro Paulo Vezza Campos measured its jaw
  height (1.7695 in), jaw width (6.247 in), jaw-plate depth (0.7005 / 0.7010 in;
  the larger is recorded, which jaw gave which reading was not noted), maximum
  opening (6.135 in) and table-to-bed height without the swivel base
  (2.886 in). Each value carries its own `measured` record; the vendor
  nominals stay beside it as comments, and the item's `verify = true`
  identity flag is kept. The rocker and bracket plans' jaw-overlap arithmetic
  uses the measured jaw height. Bracket S1/S2/S3 use 19.5453 / 10.3703 /
  3.6703 mm engagement on the 1 in set pair and the labelled illustrative
  1-1/8 in and 1-5/8 in tall narrow pairs. A 50.8 mm-wide 1-2-3 block
  cannot fit between jaws closed on a 16 mm foot.
- `shop-policy.toml`: shop-owned, not copied into plans. The default requires
  `tool_resolves`, `sizing`, `op_chain`, `blind_depth`, `inspection`, `coordinates`
  and `zero_check` on `"*"`. Re-fixture, thin-wall, stick-out and other policy
  numbers are labelled illustrative example values with `numbers_verify = false`.
- `cutting-data.toml`: illustrative example rows for low-carbon steel (HSS, M2,
  M42 and carbide tools; face, profile, spot, drill, ream, counterbore, bore,
  turning, dome, relief, part-off and cut-to-fit, plus saw cut-off), the
  material-force/modulus row and one deep-hole
  drill derate. Every row is labelled `example (plausible, not measured)` and its
  citation names the Machinery's Handbook 27th edition table, printed page and
  range the value sits inside (revision 5, which adds the M42 HSS lathe face,
  turning and dome rows the pivot-shaft's 3/8 in HSS tool bit uses: carbide's
  Table 1 floor is out of reach at the lathe's 2000 rpm top speed on a Ø6.35
  shaft); tool-maker, saw-maker and university
  charts appear only as secondary citations. Reamer pre-drills leave radial
  stock inside the handbook's p.1133 reamer depth of cut (.003-.004 in for holes
  1/8 in or less, .004-.008 in over). These are starting values, not shop
  measurements. The generic `Plain Carbon Steel` alias is a candidate
  classification, not a sourced grade or measured carbon content.

Existing inspection choices follow the exported feature
owners, using separate inspection steps where needed, without changing gauges or
inventing methods. Local regeneration evidence and remaining acceptance
are recorded in [PLAN §8 M3](../PLAN.md#8-milestones).

### Expected consumer CLI exits

The operative expectations are in [`tests/test_examples.py`](../tests/test_examples.py).
The table describes the authored fixture contract. Integration proof and
remaining acceptance are tracked in [PLAN §8 M3](../PLAN.md#8-milestones).

| Part | What it demonstrates | Expected exit |
|---|---|---|
| `pivot-shaft` | A short-gripped prep setup (S0) faces the plain end and #2 centre-drills it from the tailstock; then three-jaw drive with the tailstock dead centre in that centre and a follow rest, journals/shoulder/both reliefs/both domes, then indicated rechucks and assembly-dependent plain-end fitting. No final hole, flat or indexing. | **0** |
| `rocker-arm` | Bounded rough/finish facing inside a retained rail frame, modeled magnetic end stop, permanent rod-hole pin and supported hub ream, the hub filed round to buttons on the pivot bore at the bench (S3F), then shoulder-screw profiling roughed in single-axis stairs and filed to a scribed template, with independently held scrap. | **0** |
| `pivot-bracket` | Seat-up, foot-top-up and side-on ear setups; full raw-top facing, walls-first/floor-last L-foot relief, arched ear (single-axis stairs, then filed to buttons on the cross bore at the bench), reamed cross-bore and two hold-down holes. The v39 STEP is bound; bands remain explicitly illustrative without a dimensioned drawing. | **0** |
| `cone-pivot-post/built-up.toml` | Twelve setups: a turned body and head plus cone and crank sleeves bonded into reamed sockets, with dividing-head, bench-cradle, saw-cradle and soft-jaw holds. | **0** |

### Rocker-arm supported route

The illustrative rocker plan binds the exported `v40` drawing revision and
uses drawing note 2's nominal 2.50 mm strap thickness. Neither this binding nor
a clean checker exit is released-plan approval or a measured first article.

The checked-in [`report.json`](rocker-arm/expected/report.json) and
[`traveler.html`](rocker-arm/expected/traveler.html) hold the generated findings
and rendered traveler. Finding counts change with the rule catalogue and route;
the expected exit is listed above. Integration regeneration and native proof
belong to [PLAN §8 M3](../PLAN.md#8-milestones).

**Manual arcs (D1).** The mill is manual, so the hub and outline arcs use the
1898 method ([plan Manual arcs](../docs/plan.md#manual-arcs)), each choice cited
`AUTHOR'S CHOICE: <method> because <reason>` in the plan. S1/S2 rough the hub,
top edge and outline in single-axis stairs. Bench setup S3F files the hub to Ø10.20 hardened buttons
on a ground stud through the reamed pivot bore and checks it with the radius
gauge. S4 scribes the R800 top edge and R816 outline from the toolroom outline
template (ops 10/20), re-roughs them in stairs at cusp 0.25 mm (ops 25/27)
and files both to the line (ops 30/40), checked on
the profile template. Every rough leaves at most the shop policy's
`max_filing_stock_mm` (0.5 mm, example value) where the file takes over.

| Setup | Native fixture scene | Exact components | Fixture debts | Render debts |
|---|---|---:|---|---|
| S1 | Vise jaws, parallels, risers and magnetic positioning stop | 11 / 11 | none | none |
| S2 | The retained-rail vise hold plus two passive support jacks | 19 / 19 | none | none |
| S3 | Profile plate, support pads, hub stand, rail rests, stepped straps and permanent clocking pin | 43 / 43 | none | none |
| S4 | The same plate and supports, shoulder screw/washer, clocking pin and four independent scrap-rail clamps | 53 / 53 | none | none |

Every printed contour checkpoint uses the same three-decimal DRO target in
the operation row and contour header, with tip Z rounded upward. Native
cutter checks protect finished material and the declared leave, fixtures,
stock outside the operation's clearing authority, and stock needed by later
holding. Material-aware clips end a fragment at first protected-stock contact;
separate fragments are never silently reconnected. Join captions print the
actual 0.200 mm rough leave, and traversal follows the CW spindle and each
setup's local outward normal. S4's cut-state picture includes the legal
separation of the independently held part and scrap frame, not arriving stock
with an unresolved split.

The four holding states are explicit, rather than pretending a clamp can move
halfway through a fixed setup:

- **S1/S2 — retained rail frame in the vise.** A **340 × 65 × 16 mm** example
  blank puts the full-thickness rails and end ears outside the entire 9.525 mm
  roughing-cutter sweep, not just its centreline.
  Both sides rough-face only the bounded internal field using the two-flute
  cutter in axial steps no greater than 1.5 mm, leaving 0.20 mm for a separate
  four-flute finishing pass. The rails and ears are never faced; later rests and
  clamps use their retained raw 16 mm thickness. After the first rough face,
  the top is +0.20 mm and the 0.05 mm paper pickup is set to +0.25 mm.
  The rocker-only rougher is inserted to a 38.0 mm projection, below the
  four-diameter engagement limit; the shared finish cutter retains 38.5 mm.
  The emitted clipped joins themselves open the authorized tip-turnover
  corridor; there is no separate unlisted pocket. Follow the numbered tables
  in local cutting order: **-X join → bottom arc → +X join** in S1/S4 and
  **+X join → arc → -X join** in rolled S2. Ramp in from scrap at the first
  waypoint, make the listed single conventional pass, and retract clear of
  stock and fixturing before repositioning between disconnected fragments.
  Native bounded-removal proof preserves both raw rails, both ears, the normal
  0.20 mm allowance and the opposed 0.40 mm web; opening this corridor does not
  change the setup's final stock.
  Opposed roughing retains a 0.40 mm connecting web. The 1/2 in parallels sit
  entirely beneath the rails
  on matched **76.2 × 64 × 25.4 mm** ground riser bars, with 0.5 mm clearance
  to each closed jaw and 6.8453 mm nominal vertical jaw engagement. A modeled
  magnetic end stop touches the left blank end for positioning only; it carries
  no cutting load and does not modify Pedro's vise. S2 adds adjustable passive
  jacks under the S1-finished strap, set to just contact without lifting the
  rails. The rod hole is spotted, drilled 1.85 mm and reamed 2.00 mm before the
  outside pockets leave only the web. The visible process HOLD uses GO 2.000 /
  NO-GO 2.010; the wider drawing band alone does not authorize loading the pin.
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
  Separate toe clamps retain the scrap rails on matched shimmed rests. Op 30
  opens the web; op 40 finishes the actual complete outline, including both
  tip lands and tapers. Both cuts use light conventional feed to keep positive
  pin contact. Keep all four scrap clamps in place until op 40 is complete.
  The shoulder screw and four rail clamps declare `restraint = "press"`; the
  diamond pin declares `"locate"` and receives no lift-restraint credit.
  A separate native contact probe of the final cut found a clamp-bearing →
  stock → anchored-support witness for each of the two released solids:
  washer to hub stand for the part, and rail beams to matched shims for the
  connected scrap frame. This is a necessary holding-geometry screen, not a
  certification of thread engagement, tightening torque, friction or capacity.

Final inspection checks both hub patches against the reamed datum. The rod
position check keeps the finished C land on a fixed ground bar on the
`rocker-inspection-box`; the strap B contacts its front face and the hub clears
the top. The whole clamped box tips onto its ground right side without
re-squaring the tiny land. Largest freely passing calibrated metric pins,
near-face probing and the A-pin slope check control datum-fitting errors.
The CAD-derived centre-height differences are **132.3912 / 15.8429 mm** in
these two fixed-C views, not the milling setup XY coordinates. The drawing
remains **Ø0.20 RFS**; the **Ø0.16** shop HOLD is an illustrative guardband.
The tipped-view reseating check holds the part if either reading shifts by
more than 0.002 mm. Native proof at A offsets -5 / 0 / +5 mm found full C
contact, both clamps bearing, no part/fixture penetration and clear granite
in both views. Fixture dimensions and primitive solids carry
`example (plausible, not measured)` labels, not actual calibration or
first-article certification.
The letter-D pilot leaves about 0.264 mm diametral reaming stock. Custom metric
GO/NO-GO plugs verify the 6.500..6.530 bore. The rod's process GO 2.000 /
NO-GO 2.010 plugs control a reamed hole, not an unrealistically close twist
drill; the 1.9875 mm stop has 0.0125..0.0225 mm diametral clearance.
A 1 µm test indicator records pivot pilot-to-ream centre shift against the
0.020 mm radial process limit. For rod position, the digital height gauge is
only a carrier for that indicator: zero on known calibrated gauge-block
stacks near each pin top and read the local deviation. A 1 µm display is not
an accuracy claim across 132 mm. The pin takes tangential finish loads but
no clamp or lift load.
The authored transfer limits are 0.02 mm TIR at each drilled pivot-pilot pickup
and 0.01 mm TIR at the ground shoulder-screw head; these are example acceptance
criteria, not invented measured runout readings.


Exit precedence is **3 > 2 > 4 > 0**: bad input prevents outputs; any error beats
required unknown/unsupported/warn; only clean required subjects permit exit 0.
The validator recomputes report exits and itself exits **0** when the bundles,
stopped or clean, agree with their expectations. The combined catalogue includes
seven sampled geometry families, unknown when STEP bytes, stock, claims,
normals or required fixture dimensions are unavailable. Local regeneration
evidence and remaining acceptance are recorded in [PLAN §8 M3](../PLAN.md#8-milestones).

Plans supply stock placement, holding, coolant, DRO settings, check jogs,
paper, cut/exit allowances and inspection methods as author choices. Labelled
plausible values for unmeasured shop facts do not establish real measurements
or the assembly's actual fitted span.

Each part directory contains `plan.toml`, `features.toml` and parent-regenerated
`expected/report.json` / `expected/traveler.html`. The cone instead has
`built-up.toml`, `expected/built-up/report.json` and
`expected/built-up/traveler.html`;
there is no generated plan-text file. Plans do not request external coordinate
files: machine-readable numbers are in the report and bench coordinates are on
the sheet. No operative asset lies outside the bundle.

### Built-up cone route provenance

`cone-pivot-post/built-up.toml` is an authored manufacturing alternative, not a
second consumer export. It uses the same v40 cone STEP and the example-only
construction permission above. Its twelve setups turn the body and head in one
piece from 44.45 mm (1-3/4 in) 1018 round bar, turn the cone sleeve
(Ø17.2 × 42.011) from 19.05 mm bar and the crank sleeve (Ø21.93 × 72.0344) from
25 mm bar, and bond both sleeves into reamed cross-sockets with retaining
compound. No saddle, pad or boss is milled. These are illustrative purchase and
process choices, not stock-on-hand or first-article evidence.

| Setup | Machine / holding | Work |
|---|---|---|
| S1 | lathe, 3-jaw on the raw tail | face foot B; rough and finish head Ø42.7506 and body to the Ø41.99–42.03 process hold; r0.1 parting-blade corner pass leaves the body/head step at R0.25 max |
| S2 | lathe, 3-jaw on a 25 mm grip | cone sleeve: face the north cap, turn the Ø17.194–17.206 spigot, spring pass, part off 0.045 long to the 42.04–42.08 process hold |
| S3 | lathe, 3-jaw on a 25 mm grip | crank sleeve: face, turn the Ø21.924–21.936 spigot, spring pass, part off |
| S4 | mill, BS-0 dividing head along table X, 4-jaw on the tail | spot, drill and ream the Ø22.000–22.020 crank socket through the head |
| S5 | same chucking, indexed 12.5182° | spot, drill and ream the Ø17.250–17.270 cone socket through the body |
| S6 | bench, modeled `cone-bond-cradle` | bond the cone sleeve; 24 h cure |
| S7 | bench, same cradle | bond the crank sleeve; 24 h cure |
| S8 | mill, BS-0 along table X, tail re-chucked | spot, drill and ream crank bore Ø11.413–11.443 through the bonded sleeve, aimed at 39.517 separation (plan `aims`) |
| S9 | same chucking, indexed 12.5182° | spot, drill and ream journal bore A through the bonded cone sleeve |
| S10 | 4 × 6 bandsaw, shop-made `cone-saw-cradle` in the saw vise, `cone-cap-bridge` strap on the south cap | saw the tail off 1 mm above the head top |
| S11 | mill, PM 6 in vise with tall aluminium soft jaws on the two cone caps, foot B on parallels | Z from the measured sawn top; face the head top to Z86 with a 3/4 in end mill; spot, drill and counterbore both mounting holes; break the edges by hand; inspect |
| S12 | bench, modeled `cone-bond-cradle` | paint the non-functional turned surfaces RAL 6005, mask and oil the functional faces |

The sleeve chuckings grip 25 mm of sacrificial bar. The crank sleeve leaves
85 mm exposed, below the 87.72 mm four-diameter limit at its finished 21.930 mm
OD, and parts off 6.9656 mm ahead of the jaw fronts; the cone sleeve leaves
50 mm exposed and parts off 6.989 mm ahead of them.

The dividing-head setups put the BS-0 spindle along the PM-30MV's 23 in table
X travel, head at the left end; along the 8.75 in Y travel the ~350 mm head,
chuck and post stack would overhang the table. The head's illustrative
160 × 150 mm base footprint matches its drawn solids. The raw tail seats on the
four-jaw body face, so no stock is drawn inside the chuck body. S1 rough- and
finish-turns the body to the head shoulder, so the claimed body face is turned
over its whole length, and the parting-blade pass clears the R0.4 nose fillet.
A plain vise on round stock has no parallel planar grip pair: S10 lays the post
in a shop-made saw cradle under a cap bridge whose load runs down the cone
sleeve onto a cap pad, and S11 grips the two cone-sleeve caps in tall soft
jaws. Two process holds inside the drawing bands make those holds work for
every accepted part. S1 turns the body to Ø41.99–42.03 around the printed
Ø42.01, which keeps the body axis within 0.022 of the height the Ø42.011
cradle saddles, pins and pad are set for. S2 parts the cone sleeve 0.045 longer
than the CAD 42.011 and holds it to 42.04–42.08, so both caps sit flush to
0.09 proud of the body; the S10 bridge pose rises by that 0.045. All cradle,
bridge and soft-jaw dimensions are illustrative.

The CAD stations give a crank-to-journal separation of 72.700 − 33.368 =
39.332, just under the printed 39.34–39.70. The plan's `aims.crank_bore`
therefore moves the crank bore's DRO target to 39.517, near mid-band and on
the 0.005 grid. The crank sleeve and its socket stay at the CAD station, so the
bore sits 0.185 off the sleeve centre. The dividing-head setups zero X on foot B
(Axis Set ± the edge-finder radius) and Y on the body crest. Both bore axes
cross the post axis. S4 aligns the head to table X by sweeping the top and
side of the turned body, and S8 re-checks that alignment. S11 sets Z from the
sawn top's measured high spot, not from a nominal 87.0.

The pre-bond sockets and spigots are plan-owned joint features, not invented
STEP faces. The cone joint gives 0.044–0.076 mm diametral clearance inside its
declared 0.04–0.08 mm band, and the crank joint 0.064–0.096 mm inside 0.06–0.10 mm.
Each joint declares `method = "retaining_compound"`, an example Loctite 638-class
anaerobic compound, solvent surface preparation and a 1440 min room-temperature
cure. The sleeves seat on the cradle's locating pins under gravity, with no
clamping force on a curing joint. Both running bores are reamed only after cure,
from datum A/foot B re-indicated on the dividing head. The compound, band and
cure are illustrative process choices, not a product datasheet claim or a
structural-joint certification.

Every declared holding item remains part of its setup scene, including the
bonding cradle and the saw vise. The socket bore gauge keeps its fact-local
illustrative measurement label; its 0.001 mm resolution is not flattened into
an unlabeled number to get past the inventory schema. S11 op 110 checks the
crank separation and its Ø0.10 angularity on the surface plate with the DTI on
the height gauge. The angularity check reads bore slopes over 1-2-3 block steps
in two orientations and combines them into one zone deviation. It is an
illustrative hobby-gauge method, not certification.
Generated built-up artifacts live in `cone-pivot-post/expected/built-up/`.
Generated findings and scene debts, not the authorship of this section,
determine readiness.

### Inventory provenance and measurement debt

The PM-30MV vendor nominals are spindle-to-table maximum 17 in and X/Y/Z
travel 23 / 8.75 / 14 in, recorded in `machines.PM-30MV.envelope`.
Duplicate travel/table/envelope fields are not a second source. Table size,
T-slot pitch and spindle-stack entries are not modeled; taper remains vendor
identity under `machines.PM-30MV.spindle`. Fact-local measurement requirements
are in [the inventory format](../docs/inventory.md). The measured vise bed
height is documented under shared inputs; unmeasured dimensions follow the
[examples policy](#examples-policy-plausible-labelled-values). Plausible records
do not establish real operator/date/instrument measurements.

`verify = true` with a known nominal number is measurement debt. Vendor
machine/vise/support geometry, edge-finder dimensions, instrument capability and
jaw/grip arithmetic need shop evidence where verification is required.
Changing an author choice does not clear that evidence requirement. Items
outside the selected routes retain their own unknown/verification debt.

Tool projection belongs to the selected tool/holder pair on the tool. Short
and qualified holder spellings select the same identity; duplicate entries for
that identity, including entries in both unit maps, leave projection unknown.
See [installed tool stacks](../docs/inventory.md#measured-envelopes-and-installed-tool-stacks-m5).
Holder-wide projections and suffixless legacy gauge fields are not accepted.
The [engagement screen](../docs/rules-physics.md#engagement) requires positive
authored DOC on eligible endmill cutting operations; omitted or nonpositive
DOC leaves the operation unknown.

The `envelope` and `travel` findings add concrete `measure:` instructions to
the before-you-start lines, keyed by the exact fact consumed (set member or
tool/holder pair). The vise stack uses the vise bed height, never jaw
height; Z travel is the per-op spindle-nose span (`tip + gauge + projection`),
so it also waits on holder gauges and tool projections; hole and point
centres carry no cutter-radius padding. Mill travel/envelope additionally
need explicit safe `approach_mm` and complete feature/stock extents. Missing
inputs remain debt; the examples supply labelled authored approaches and
plausible dimensions. Lathe mill-envelope/travel rows are `not_applicable`,
and no lathe operation is asked for a toolpost gauge length: there is no
`holder_stack` rule. A named holder absent from inventory must be added or
resolved before its dimensions can be measured.
Use `uv run prechips tools --measure` for the sorted, deduplicated list of
exactly the `numbers.measurements` debt behind these four consumer reports (add
`--plan` to scope it, `--inventory` to override the plans' inventory).

A shop that requires `envelope` or `travel` on `"*"` obtains exit 4 for
unresolved measured feasibility unless an existing error takes precedence.
Illustrative feasibility inputs do not establish a machine measurement,
physical rehearsal or first article.

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
uses the STEP global XY bbox and retains only its authored 1 mm Z allowances.

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
authority.
`plan.toml` is the plan author's document: blank size/placement, holding, coolant,
direction, jogs/paper, cut/exit allowances, contour steps and capable-gauge methods
are **author's choices** with plan citations and require checker validation.
Except for the documented vise measurements, the examples use
labelled plausible shop values; these do not establish measured setup binding
or shop-verified cutting data. Exported drawing/STEP identities are present.

### Current export contract changes

All three exports use the rendered metric general bands **0.8 / 0.51 /
0.13 mm**, cited to `cad/config/title_block.yaml:linear_1pl.display`,
`:linear_2pl.display` and `:linear_3pl.display`. The rocker and cone preserve the
material choice `LOW-CARBON STEEL OR GRAY IRON`; the shaft specifies AISI 1018
cold-finished Ø10 bar. No family label selects a verified cutting-data row.

The rocker export has explicit `strap_datum_b`, `tip_land_pos_x` and
`tip_land_neg_x` requirements. Its exported
tip-land angular acceptance is unknown; the example's labelled title-block
divergence supplies the band. The shaft separates the shoulder's north and
thrust faces and both relief/dome face sets. The cone export has `journal_bore`,
separate mount holes/counterbores and both boss end faces, with an explicit
unknown journal-bore requirement identity. The example records how the rim
deburr requirement is handled. Its crank bore carries `separation`,
`angularity_dia` and `angularity_datums`. Exported height limits are
33.118–33.618 and separation limits 39.332–39.702 mm; these remain unchanged.

The upstream cone export has no `volume_mm3` or `volume_cite`. The current
example manifest supplies a STEP-derived volume of 112300.96039973569 mm³:
its citation records FreeCAD 1.1.4 `Part.read(...).Volume` of the adjacent
digest-bound STEP's one valid solid. This is example-derived geometry, not an
upstream export field or a physical measurement; the analytic source feature
sum is not its authority. See
[`cone-pivot-post/features.toml`](cone-pivot-post/features.toml).
The examples' authored setup bindings, illustrative inventory and inspection
methods do not establish actual material grade or physical readiness.

The shaft and cone exports carry `frames.setup = "unknown"`. Their plans supply
shaft T1/T2/T3 and cone/built-up lathe and M2/J3/C4 transforms as
plan-authored `[frames.<name>]` tables. These are **author's choices** with plan
citations, not CAD facts. The shaft's T3 binding is `nominal`: the example
assumes the fit-up scribe landed at the REF span 156.67, so the S3 plain-end and
north-end stations and stick-out are numeric.

The shaft route (example plan) is: S1 grips the north stub in the three-jaw
chuck, with the MT3 dead centre in the centre-drilled plain end (Ø3.0 countersink,
so the turning tool starts about 0.5 clear of the centre's cone) and the follow rest
riding the 26:1 body on the turned side, 8 mm behind the tool (example jaw
sizes 12 × 40 × 10 mm at 90° and 180°), its jaws reset with the spindle stopped
on each newly turned diameter. It roughs and finishes the bearing toward the chuck,
faces the thrust shoulder, mics the Ø10 shoulder left as cold-finished bar and
plunges the south DIN 509 relief with the 1/16 in HSS parting blade. S2 reverses
onto the finished body with the thrust face seated on the jaw fronts to turn the
journal, face the shoulder's north face, plunge the north relief and form the
north dome with the 93° AR tool (the 60° E gouges near the apex). S3 grips 8 mm
north of the scribe, parts the plain end to the 1.5–2.0 past-scribe band with
the blade and forms the south dome on the parted face with the AR tool. Each
setup ends with a hand deburr (spindle stopped, needle file and slip stone) of
the edges it made, checked to the drawing's R0.25 / 0.25 chamfer maximum under
the example 10x measuring loupe (`gauges.measuring-loupe`), so every edge is
broken before S3 op 40 oils the part.

The shaft manifest requires Ra 1.6 µm on `pivot_bearing`, `pivot_journal` and
`shoulder_thrust`; the plan selects `roughness-comparator` checks. Its
0.1-12.5 µm inventory range is illustrative, not calibrated capability.
The S2-to-S3 transfer indicates `pivot_bearing` to an authored 0.02 mm TIR
limit; this is an alignment target, not a measured runout reading. See
[`pivot-shaft/features.toml`](pivot-shaft/features.toml) and
[`pivot-shaft/plan.toml`](pivot-shaft/plan.toml).

The shaft export's `pivot_bearing` has only the `CUT TO FIT` note and
`length_ref = 156.67`, with no cut-to-fit length requirement. The 1.5–2.0
past-scribe band comes from the channel assembly drawing's fit-up note
(`cad/scripts/draw_channel_assembly.py:82,101-110`), not the shaft drawing, so the
plan prints it as a labelled fit-up hold in S3 op 20's `inspection_note`: the
DRO, with the T1 tool point re-sighted on the scribe, measures the scribe-to-end
distance. The plan does not claim a `pivot_bearing:length` inspection.

The cone's indexing feature `crank_bore` owns
`land_angle_nominal_deg = 12.5182` and the BASIC relationship. The source
export omits `angle_tol_deg`; the example supplies the labelled 0.0795° bound
from HA's `CRANK_BORE_ANGLE_LIMIT_DEG`
(`cad/scripts/cone_pivot_post_spec.py:373`). This is not title-block ±1° or a
conversion invented by the consumer. The source export's signed
`mount_west.station_nominal = -12.98` conflicts with its absolute
`station` band [12.47, 13.49] (`cad/scripts/export_features.py:566`).
The example's documented sign correction addresses that inconsistency;
the checker does not flip signs or drop fields to manufacture a pass.

The current bonded route turns both sleeves on the lathe with the radial
turning approach and mills no cone-boss faces.

Consumer integration requirements and remaining acceptance are tracked in
[PLAN §8 M3](../PLAN.md#8-milestones); this guide does not establish current
upstream HA task availability.

The shaft's REF span 156.67 is stack arithmetic
(`cad/scripts/rocker_bank_layout.py:63–107`); actual installed fit needs the
ear/scribe measurement. The assembly drawing calls for a cut 1.5-2.0 mm past
the scribe and a 1.5 mm dome
(`cad/scripts/draw_channel_assembly.py:77–82,101–110`). The source specifies
"between centres"; the example uses chuck drive because no lathe dog/drive-plate
system is confirmed. REF geometry receives no invented drawing acceptance band.

The rocker's rod centre is (133.06740213488345, 16.456064115939025) in model
XY, derived from `cad/scripts/rocker_arm_spec.py:33–34,57–59` and
`cad/scripts/cone_pivot_post_installation.py:19`. Source dimensions are hub
OD 10.20 mm, hub length 7.0565 +0.05/0 mm, pivot bore 6.50-6.53 mm and #47
rod hole 1.994-2.094 mm (`rocker_arm_spec.py:107–126`, `_hole_spec.py:82`,
`cad/config/title_block.yaml:66`). Drawing position is Ø0.20 to A|B|C;
setup frames A/B are not drawing datums A/B/C. Current feature identities and
citations come from [`rocker-arm/features.toml`](rocker-arm/features.toml).

The bracket's ten hand-authored features map all 16 v39 STEP faces.
`outer_face` owns the shared ear-outer/foot-near-end plane. STEP/spec nominals
are a 16 mm foot width, 24.2 mm foot run, 6 mm foot height/ear thickness,
14 mm ear width, R7 crown, 4.572 mm hold-down holes and a 6.50 mm reamed
cross-bore 25.2 mm above the seat. Acceptance bands are individually cited
illustrative design choices in
[`pivot-bracket/features.toml`](pivot-bracket/features.toml); nominal STEP
geometry is not a dimensioned drawing.

The cone's 12.5182° BASIC value is the horizontal plan angle between the
crank and journal bore axes, not bore tilt
(`cad/scripts/cone_pivot_post_spec.py:59–67,238–245,268–279,327,387`;
`cad/scripts/draw_cone_pivot_post.py:254–268,1137–1138`). Datum A is the finished
journal bore and B the finished foot. Crank-bore Ø0.10 angularity to A|B is a
separate requirement; construction setup frames are not drawing datums.

Running fit limits remain crank 11.413-11.443 mm and journal
12.2558-12.2858 mm (`cone_pivot_post_spec.py:132–168`). Re-centering the
journal limits on the three-place printed 12.281 would shift them 0.0002 mm.
Height and separation are separate requirements; crank height 72.70 is REF
(`draw_cone_pivot_post.py:188–190,1134–1135`). Mounting stations are derived
12.98 mm each side (25.96 mm pitch), with 7.14248 mm through holes under the
drilled +0.10/0 row and 11.51 × 6.02 mm counterbores under two-place ±0.51
bands (`cone_pivot_post_spec.py:79–104,175–176,318`).
Foot Ra3.2 and running-bore/north-cone-face Ra1.6 requirements cite
`_surface_finish.py:48–54`. The cone-rim exception is RIMS BREAK 0.1 MAX
(`draw_cone_pivot_post.py:254–264`, `cone_gear_shaft_spec.py:79–97,111–113`).

The current bonded route and its three illustrative blanks are described under
[Built-up cone route provenance](#built-up-cone-route-provenance). The blank
grade, indexing/landing accuracy and actual setup alignment need shop evidence;
plate arithmetic and checker results do not measure them. Labelled Handbook
27th-edition starting data, authored fixture geometry and the
[export divergences](#example-divergences-from-consumer-exports) do not establish
physical machining, first-article or clearance-completion acceptance. The
producing CAD farm run is separate from prechips parented farm-telemetry
acceptance. The immutable
[`dfcee1b4` example guide](https://github.com/pedropaulovc/prechips/blob/dfcee1b4432dfa04c371620765bbc884754941a6/examples/README.md)
retains the earlier source readings and retired manufacturing candidates.

## Report binding and reference vocabulary

All five input paths are repository-relative POSIX paths with real SHA-256s of
file bytes. `step_sha256` is separately recorded at the report root. Reports are
UTF-8, sorted-key JSON with two-space indentation, `ensure_ascii=False`, finite
numbers only and one final LF. Findings are sorted lexicographically by
`(rule, subject)`. To compute `hash`, remove only the `hash` member, serialize the
remaining object **with the same canonical form including its final LF**, and
SHA-256 those bytes. The HTML carries the full report hash in
`<meta name="prechips-report">`; no hash prints on the sheet.
HTML is an output, not an input to its own report.
`.gitattributes` pins fixture line endings to LF.
The implemented rule vocabulary is `m5-rev9` (the combined M4 geometry and M5
measured-inventory catalogue), as emitted by `report.py`. Regeneration and gate
evidence belongs to [PLAN §8 M3](../PLAN.md#8-milestones).
The report retains the reference ABI's `message` and `expected_exit` names.
Finite floats use the JSON encoder's shortest round-trip representation, not drawing-format rounding. Drawing precision
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
  Lathe headroom is unsupported by the mill-only rule. Known nominal frames
  do not certify measured setup binding. `stock_state.top_feature` disambiguates
  the rocker's touched hub face: machining a strap face does not move that top.
  A coordinate row's `local_from = { op, field, axis }` binds a local Z target
  to an authored operation endpoint when its model transform remains unknown;
  it does not bind the fitted shaft length to the nominal reference model.
- `speeds_feeds`: every op, including not-applicable manual operations. No
  turning, spotting or unsourced tool-material row is invented.

Report unknown numbers follow missing operative facts: speeds/feeds, tip
endpoints, gauge capability,
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

Travelers are Letter portrait with variable physical pagination. Operation
ledgers, inspection writing areas and semantic diagram panels flow onto
continuations; duplex padding preserves front-side setup starts. Footers flow
after instructions.

Before-start lines use ✗ / ! / ?. Tables apply explicit drawing precision;
known operative/manual targets retain their supplied numeric form when drawing
precision is absent, without inventing an acceptance band. Actual unknown
numbers remain `?`. Stock state, grip/stop/clamp, clearance, coolant, deburr,
tool/holder, speed/feed, direction, tip and requirement checks are present or
named unknown. No rule ids, paths or full hashes belong on the bench sheet.
Under M4 each setup page carries a kernel figure or the explicit
`? Kernel fixture render unavailable; holding geometry is not confirmed.`
paragraph when a kernel render cannot be produced. The bracket carries
the digest-bound v39 STEP and explicit setup-entry stock routing. Its S1/S2/S3
vises include posed parallel pairs; S4 includes the angle plate, a load-bearing
foot-end ledge and a two-stud bridge strap pressing the foot toward the seat datum.
A browser-rendered Letter PDF is a layout smoke proof; physical printed paper
rehearsal and first-article acceptance remain separate requirements.

### Print and native acceptance limits

Page counts depend on the current route, generated content and browser layout.
The immutable
[`dfcee1b4` print record](https://github.com/pedropaulovc/prechips/blob/dfcee1b4432dfa04c371620765bbc884754941a6/examples/README.md#dro-and-print-surfaces)
retains the dated readability baselines, their exact commits/page counts and
native controls. Local regeneration evidence and remaining physical/live acceptance
belong to [PLAN §8 M3](../PLAN.md#8-milestones).

A cache hit returns the stored facts of the run that produced it. Fresh native
bit-repeatability is unproven: the recorded bracket controls differed in six
stock-cylinder highest-Z values by 0.000001 under unchanged source-input and
STEP identities. A fresh frozen-baseline control reproduced those differences
while all six render PNG hashes matched. Their ultimate native cause and
harmlessness remain unproven; these observations do not authorize changing
values or tolerances.

Report repeatability and layout smoke proofs do not establish painter
equivalence, final print acceptance or a physical printer/pen/operator trial.

## Validation

```console
uv run python scripts/validate_examples.py
uv run ruff check scripts
```

The standard-library validator parses **every example TOML** with `tomllib`,
rejects `"unknown"` in its explicit author-choice field set (including nested
direction/contour values), checks complete rule subjects, manifest/plan references,
enumerated shop items, named missing findings and requirement-keyed inspection,
verifies orthonormal frames and coordinate transforms, tip/exit, speed/feed
arithmetic, hashes/canonical JSON/metadata binding and exit precedence. It
compares Axis Set/finder/paper/jog/mirror/retouch fields using the helper
boundaries below. It rejects obsolete YAML/CSV fixtures and checks authored
contracts without asserting geometry, material properties, gauge calibration,
first-article evidence or telemetry.
The cone checks signed landing arithmetic and full-pattern-only closure,
smallest finished exposed diameter/verified-ratio arithmetic separately from
held OD, and explicit construction permission. Unbound or incomplete finished
profiles stay unknown.
The validator recomputes clipped spindle RPM bands and slower gap endpoints,
ordinary coordinate targets and complete lathe stations from authored inputs.
It exhaustively enumerates indexing settings, including continuous/unknown
modes, and compares stick-out fit-up arithmetic and debt with the plan.
Support state, item resolution, tool compatibility, zero recipes and geometry
reuse production helpers: `stickout.support_state`, resolution,
`tool_resolves`, `zero_recipe` and `run_geometry`. Zero-recipe reuse includes
lathe setup, touch side, X touch set, tool changes/setting and verdict evaluation.
These comparisons are consistency checks, not independent oracles. They reject
inconsistent report claims without authenticating measurements or certifying machining.
Endpoint arithmetic distinguishes spot/tap depth, blind tip depth and its drawing
guard, and through breakthrough allowance. Reamers use sourced axial lead,
drills use the point cone, and boring/counterboring uses zero drill-cone length;
blind counterbores never acquire a through exit allowance.
Historical regeneration and scoped mutation evidence are retained in
[`examples/README.md`, "Validation", at `dfcee1b4`](https://github.com/pedropaulovc/prechips/blob/dfcee1b4432dfa04c371620765bbc884754941a6/examples/README.md#validation).
Local regeneration evidence and remaining acceptance belong to [PLAN §8 M3](../PLAN.md#8-milestones).

## Authoring contracts

1. `src/prechips/model.py` and the five input-format pages under `docs/` define
   the strict TOML schema. Unknown keys are bad input; literal `"unknown"` remains
   unresolved, including nested records. Lathe end stations are not mill heights.
2. Policy metadata uses `numbers_cite` and `numbers_verify` sibling tables.
   Missing policy uses the shop-required seven-rule vocabulary, never plan waivers.
3. Inspection uses exact requirement keys (`position_dia`, `finish_ra`, etc.)
   and all manifest dimension requirements, including explicit manual inspection
   for dimensions completed by another feature's operation.
4. Reports use the rule ids, subjects and canonical report ABI above.
   An absent required rule or subject is unknown, not silently checked.
5. `top_feature` identifies the touched surface; `entry_z` advances separate
   local entry surfaces. Indicated bore pickup has zero finder radius. Unknown
   frame binding never substitutes reference geometry for an actual fit.
6. Lathe diametric X doubles the displayed increment of a physical jog; per-tool
   touches are explicit. Mill headroom remains unsupported on a lathe. No
   turning, spotting or unsourced material cutting row is invented.
7. Raw RPM is rounded ties-to-even at 50 rpm **before** clamping once to the
   measured machine range. A non-50 machine boundary is never exceeded and is
   not rounded again. Contact-side compensation and DRO jog polarity are
   independent; reversed directions exchange expected and mirrored readings.
8. Missing bracket drawing bands are not consumer drawing facts. The illustrative
   example adopts plausible bands and labels every feature's design provenance.
9. Unknown STEP binding is permitted as a named unresolved finding. A known
   digest requires actual matching STEP bytes. Approval is separate evidence,
   outside the operative report inputs: one root record must match the full
   report hash and carry nonblank first-article evidence, and the report must
   be eligible (`verification = "checked"`). Optional `[inputs]` digests help
   identify changes; approval cannot waive required findings. See
   [eligibility and approval](../docs/report-and-telemetry.md#eligibility-and-approval).
10. The source shaft has no flat/cross-hole; the plan does not add either.
11. The illustrative rocker holding route is described under
    [Rocker-arm supported route](#rocker-arm-supported-route).
    Its geometry is not measured inventory or physical fixture certification.
12. The renderer uses row-safe natural overflow and bounded per-setup contour
    continuations rather than fixed-height clipping. Logical HTML sections are
    not claims about physical printed pages. Paper rehearsal remains outstanding.

## Generated outputs and fixture contracts

The implementation does not read `expected/` at runtime.
The four current plans are the shaft, rocker, bracket and built-up cone routes
listed under [expected consumer CLI exits](#expected-consumer-cli-exits).
Their report/HTML pairs are generated by `prechips traveler` from operative
inputs. Regeneration evidence belongs to [PLAN §8 M3](../PLAN.md#8-milestones).

The rocker manifest supplies authored toolpath nominals separately from
tolerance bands: `hub_od.dia_nominal = 10.20`,
`top_edge.radius_nominal = 800`, `profile_outer.bottom_radius_nominal = 816`,
`profile_outer.arc_centre = [0, 816, 0]`, and
`top_edge_feature = "top_edge"`. A tolerance-band midpoint is not an authored
toolpath nominal. The original source readings are
`rocker_arm_spec.py:26-27,42-54,112`; the current exported manifest carries
per-fact citations.

Bracket stock placement, hold orientation and free-run bounds are plan-author
choices, not additions to the CAD manifest. The validator derives named Z
edges from the plan, never from a report's own answer. Nominal stations do not
create a positional/datum tolerance. S2 ear-side profile entry is Z 27.2;
the free-run floor Z 0.3 is a separate surface.

Reports bind their entire contents, so computed findings and input identities
affect their hashes. Missing tool geometry, gauge capability, cutting data,
measurements or STEP binding remain unresolved when the operative inputs do
not supply them. A selected missing reference owns its error; dependent
compatibility and sizing computations remain unknown. Manual no-tool
operations do not acquire tool-compatibility subjects.

Traveler drawing dimensions retain declared precision, or their own digits
when it is absent. Operative targets print computed values; only genuine
unknowns print `?`. Contour DRO targets follow the rounding contract under
[Rocker-arm supported route](#rocker-arm-supported-route). Transfer indication
lists print as bench-readable text. HTML metadata binds each traveler to its
report; content is escaped and rows use natural overflow. These output contracts do not establish
measured inventory, physical holding safety or first-article acceptance.

The bracket's authored route saws 38 mm from 19.05 × 31.75 mm
(3/4 × 1-1/4 in) flat bar, then squares an 18 × 26.2 × 34.2 mm blank through
P1-P6. The stock is not on hand. Each prepared face is 1 mm beyond the finished
part; size tolerances are ±0.1 / ±0.02 / ±0.02 mm. Micrometers check size and
the DTI checks flatness, squareness and parallelism to authored 0.02 mm form
limits. The six blank faces are plan-owned `process_features`, not drawing
coverage features. See [`pivot-bracket/plan.toml`](pivot-bracket/plan.toml),
stock preparation and P1-P6.

S1 faces the full raw top and preserves upper-ear stock. S2 roughs the free run
and separate side strips only to Z +16, 5.63 mm above its jaw tops. S3 finishes
the L relief, ear width and foot top before drilling the hold-down holes. All
three vise holds use no longitudinal stop. S2 picks up the surviving raw side
and free end at Z +20; S3 sets preliminary Z from the crown and picks up those
raw faces at Z +8, below the retained +16 step and 10.3 mm above its jaw tops.
The plan requires traverses above Z +32 between pickups. Grip dimensions and
parallel heights are listed under shared inputs; S3's shallow foot grip leaves
only 2.33 mm between the jaws and foot top.

S4 seats the finished seat against the angle-plate upright, outer face up.
The two-stud bridge presses the foot toward the seat; the bolted foot-end
ledge carries downward cutting load. The transfer indicates `foot_profile`,
`foot_top` and `seat_face`; X is picked up from the finished left foot face and
Y from the plate front beside the part. Alignment and transfer limits are
authored 0.001 in (0.0254 mm) TIR targets, not observed readings.

The illustrative shop-made bridge has a 63.5 × 12.7 × 9.525 mm 1018
cold-rolled beam and 3/8-16 hardware. The illustrative angle-plate casting is
drilled/tapped for the bridge and its 22.6 × 6 × 17.9 mm 1018 ledge. The ledge
is set on a 2 in 1-2-3 block while its screws are tightened, putting its top
68.7 mm above the table, then swept with the DTI. The fixture records in
[`inventory/pedro-shop.toml`](inventory/pedro-shop.toml) cite HA prints
MHA-CH-008-TL-01/02 at HA main `d4b977a58`. Their Make notes specify materials,
stock, hole positions from named edges and workholding. Drill sizes cite
Machinery's Handbook 27th ed. Table 4, p.1934; speeds cite Tables 17/20,
pp.1061/1068, feeds p.1060 and dry cast-iron drilling/tapping p.1147.
These are authored fabrication instructions and example geometry, not
measured fixture capability.

After facing the outer face, S4 checks final 6 mm ear thickness. Its R7 arch
is roughed in manual single-axis stairs with 0.3 mm leave and 0.15 mm cusp;
the 0.45 mm total is inside the illustrative 0.5 mm filing cap. S4F files to
14 g6 OD / 6.5 H7 bore buttons centered by the reamed cross-bore and checks
with the radius gauge. The buttons are illustrative bought tooling, not
measured or shop-fabricated fixtures. The bore uses 6.500 mm GO / 6.530 mm
NO-GO pins. After release, datum A rests on the surface plate; the height
gauge reads the GO-pin top minus half its diameter against the illustrative
25.1-25.3 mm bore-height band. The plan and manifest bind `example-v39`, a
local illustrative contract, not a certified dimensioned drawing revision.
All setup frames are nominal.

The original input-debt ledger, before/after counts and fixture reconciliation
remain in the immutable
[`dfcee1b4` example guide](https://github.com/pedropaulovc/prechips/blob/dfcee1b4432dfa04c371620765bbc884754941a6/examples/README.md).
Current debt comes from operative inputs and generated findings.

