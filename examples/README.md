# PLAN rev 6 reference bundles

These are **hand-authored reference targets**, not certified CAD exports, checker
runs, toolpaths, approvals or first articles. Every traveler remains **PLANNED**.
No `src/` implementation was changed. The frozen input bundle for each part is
`plan.toml`, `features.toml`, and the three shared shop inputs. No STEP byte stream
is supplied: `step_sha256 = "unknown"` is a finding, not a fabricated digest.

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

Exit precedence is **3 > 2 > 4 > 0**: bad input prevents outputs; any error beats
required unknown/unsupported/warn; only clean required subjects permit exit 0.
These expected report exits are independently recomputed by the validator. The
validator itself exits **0** when these intentionally stopped bundles agree.
There is no deviation from the requested 4 / 2 / 2 fixture exits.

Each part directory contains `plan.toml`, `features.toml`,
`expected/report.json` and `expected/traveler.html`. Obsolete YAML policy copies
and all nine neutral CSVs are removed. Plans no longer request external
coordinate files: the machine-readable numbers are in the report and the bench
coordinates are on the sheet. No operative asset lies outside the bundle.

## Source facts, not the PLAN layout sketch

Consumer citations are relative to the read-only `C:/src/harmonic-analyzer`
repository (`harmonic-analyzer/cad/...` and `cad/...` identify the same root).
Named file:line citations were re-read against that tree before carry-over.
Current source values and corrected line ranges are recorded beside dimensions.
Old process proposals are not treated as measured facts: raw blank allowances,
roughing allowances, 0.08 mm paper and hand-picked RPMs became unknown.

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

Where the drawings actually adopt defaults, the bands use the exact
`cad/config/title_block.yaml:25–27` numeric inch values × 25.4:
0.762 / 0.508 / 0.127 mm. Rounded displayed values 0.8 / 0.51 / 0.13 are not
silently substituted. REF geometry receives no invented acceptance band.
Absent bracket drawing defaults are not borrowed from another part. The
configured `next_revision: v38` is not a certified STEP/drawing revision.

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
- `speeds_feeds`: every op, including not-applicable manual operations. No
  turning, spotting or unsourced tool-material row is invented.

The complete input unknown ledger below is exhaustive. Report unknown numbers
are the deterministic consequences of those inputs: unresolved speeds/feeds,
point/lead/tip endpoints, gauge capability, clearances, zero sign/jog/check and
retouch readings, contour/arc-table decisions and measured model binding. The
exact affected subjects and number paths are preserved in each report.

## DRO and print surfaces

[Electronica EL400 Operation Manual](https://www.dropros.com/documents/EL400%20OpManual.pdf):
Direction and Radial/Diametric §6.2 (p20), Axis Set in ABS §7.4 (p31), Preset
§8.1 (p37, distance-to-go, **never datum zero**), and lathe trial-cut/touch-off
§9.2.1 (p62). Every recipe gives touch → compensated Axis Set → jog without
retouch → expected/mirrored reading, with explicit `?` wherever a required
choice or measurement is unavailable. No unmeasured check-jog distance or paper
thickness was invented to make a numeric sign proof appear complete.

Travelers are Letter portrait: one header plus one page per setup. Their plain
before-start lines use ✗ / ! / ?; tables use drawing precision, not report
precision. The stock state, grip/stop/clamp, clearance, coolant, deburr, tool/
holder, speed/feed, direction, tip and requirement checks are present or named
as unknown. No rule ids, paths or full hashes belong on the bench sheet. No
geometry render is claimed before M4. A browser-rendered Letter PDF is a layout
smoke proof, **not** the physical printed paper rehearsal or a first article.

## Validation

```console
uv run python scripts/validate_examples.py
uv run ruff check scripts
```

The standard-library validator parses **every example TOML** with `tomllib`,
checks complete rule subjects, manifest/plan references, enumerated shop items,
named missing findings and requirement-keyed inspection, verifies orthonormal
frames and coordinate transforms, tip/exit, Axis Set/finder/paper/jog/mirror/
retouch and speed/feed arithmetic, hashes/canonical JSON/footer binding and exit
precedence. It rejects obsolete YAML/CSV fixtures. It validates these authored
contracts; it is not another machining checker and does not assert geometry,
material properties, gauge calibration, first-article evidence or telemetry.
The browser smoke rendered each traveler to exactly four Letter pages (612 × 792 pt);
actual print rasters were inspected for clipping. Throwaway mutation smoke rejected an
uncompensated finder touch, an entry mistaken for an exit face, an omitted inspection
subject and a stale report digest, and proved error/required-warning precedence.
The actual prechips CLI remains plan-only; do not mistake this validation run
for `prechips check` producing the expected files.

## PLAN rev 6 authoring gaps (listed, not fixed)

1. No complete TOML key/type/units schema is specified for inventory, reports,
   angle-plate holds or lathe stock state. These references document their keys;
   lathe end-station/OD fields cannot be mill top/bottom/thickness fields.
2. Scalar shop-policy number/cite/verify metadata has no TOML spelling. These
   files use `numbers_cite` and `numbers_verify` sibling tables.
3. `checks.position`/`checks.finish` in the example differ from exact manifest
   names `position_dia`/`finish_ra`; fixtures use exact requirement keys.
   Inspection also omits several real drawing dimension kinds from its short
   list. Cross-feature closure (journal length finished while doming) needs an
   explicit manual inspect op.
4. Stable rule ids, subject domains and report JSON layout/canonical byte
   encoding are not specified. The reference conventions above make them
   deterministic without pretending to be an implemented checker ABI.
5. “Top after an op” does not identify which surface. The rocker requires
   `stock_state.top_feature`; bracket entry planes require the explicit
   per-feature `stock_state.entry_z` subtable. An indicated bore pickup also has
   no finder-radius formula in the sketch.
6. Lathe DRO installation/polarity/radius-vs-diameter, per-tool touch-off and
   headroom are not covered by the M1 mill examples. Turning has no shipped cut
   row; milling flutes × chip load is not a turning feed model. Spotting/M42
   tooling and material-grade classification are also unspecified.
7. Numeric check jogs, paper, cut directions, exit allowances, prepared blank
   surfaces, clamp methods and profile/arc steps are author decisions with no
   sourced values here. The layout sketch is not an authority for filling them.
8. No rounding-tie/boundary policy is supplied for RPM rounded to 50, and no
   unambiguous contact-approach sign convention is supplied for reversed DRO
   directions. The references separate contact-side compensation from DRO jog
   sign and leave unmeasured direction unknown.
9. The complete dimension-count contract has no machine-readable form for a
   part with no drawing. Bracket nominal geometry does not prove drawing
   precision, defaults, datum tolerances or profile acceptance.
10. The report/bundle definition expects a STEP, while this assignment explicitly
    requires unknown STEP binding. These remain stopped reference targets, not
    successful bound runs. Approval format/location and first-article data are
    not authored here.
11. The milestone's shaft cross-hole/BS-0 example conflicts with the actual
    consumer shaft's “NO FLATS”/no-hole geometry. No feature was invented.
12. The rocker fixture/rail-release design is still open; retained rails are
    released only in the supported S3 route, never secretly in the vise. The
    175-long shaft supply state is not a separately produced intermediate state
    in the retained shop route. Neither gap is concealed by a pass.
13. Page overflow and continuation policy are not specified. The authored
    reference sheets were fitted to actual Letter pages rather than treating
    four HTML sections as four printed pages.

## Exhaustive `"unknown"` input ledger

Paths below use setup ids and op numbers as array labels, not array offsets.
Every literal `"unknown"` leaf in all nine TOML inputs is listed once, grouped by
its cause. `verify = true` values with known nominal numbers are additional
measurement debt, not missing numbers: notably the vendor machine/vise/support
geometry, edge finder, instrument capability, and bracket candidate jaw/grip
arithmetic. Clearing verification requires shop evidence, not an author edit.

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
holders.r8-collets-lms-4860.gauge_len
holders.r8-collets-lms-4860.grip_mm
holders.er-collets.gauge_len
holders.er-collets.grip_mm
holders.lathe-collets.gauge_len
holders.lathe-collets.grip_mm
holders.qctp-axa-lms-2280.gauge_len
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

### `pivot-bracket/plan.toml` — 71 unknown leaves

No certified export-bound drawing revision.

```text
drawing.revision
```

Raw blank/handling/supply datum or starting surface is unsourced or unmeasured; finished nominal geometry is not raw-stock measurement.

```text
stock.form
stock.section_mm
stock.length_mm
setups[S1].stock_state.top_z
setups[S1].stock_state.bottom_z
setups[S2].stock_state.top_z
```

Applicable cutting/edge-treatment choice is not sourced for this route or absent drawing.

```text
setups[S1].coolant
setups[S1].deburr_mm
setups[S2].coolant
setups[S2].deburr_mm
setups[S3].coolant
setups[S3].deburr_mm
```

Author has not supplied a confirmed grip, stop, clamp, support, protection or lubrication decision/measurement.

```text
setups[S1].hold.fixed_jaw
setups[S1].hold.stop
setups[S1].hold.clamp
setups[S2].hold.fixed_jaw
setups[S2].hold.stop
setups[S2].hold.clamp
setups[S3].hold.grip_mm
setups[S3].hold.stop
```

No sourced paper/jog/pickup/tool/transfer reading or method; compensation/check/retouch cannot be completed numerically.

```text
setups[S1].zero.x.edge_mm
setups[S1].zero.x.check_jog_mm
setups[S1].zero.y.edge_mm
setups[S1].zero.y.check_jog_mm
setups[S1].zero.z.paper_mm
setups[S1].zero.z.tool
setups[S1].zero.z.check_jog_mm
setups[S2].zero.x.check_jog_mm
setups[S2].zero.y.check_jog_mm
setups[S2].zero.z.paper_mm
setups[S2].zero.z.tool
setups[S2].zero.z.check_jog_mm
setups[S3].zero.x.check_jog_mm
setups[S3].zero.y.check_jog_mm
setups[S3].zero.z.paper_mm
setups[S3].zero.z.tool
setups[S3].zero.z.check_jog_mm
```

Operation direction, allowance, contour, command endpoint or spot/exit depth is not sourced; no process dimension is invented.

```text
setups[S1].ops[10].direction
setups[S1].ops[20].direction
setups[S1].ops[20].rough_allowance_mm
setups[S1].ops[20].contour
setups[S1].ops[30].direction
setups[S1].ops[30].contour
setups[S2].ops[10].to_z
setups[S2].ops[10].direction
setups[S2].ops[10].rough_allowance_mm
setups[S2].ops[20].direction
setups[S2].ops[30].direction
setups[S2].ops[40].to_z
setups[S2].ops[40].direction
setups[S2].ops[40].rough_allowance_mm
setups[S2].ops[40].contour
setups[S2].ops[50].direction
setups[S2].ops[50].contour
setups[S2].ops[60].depth_mm
setups[S2].ops[70].exit_mm
setups[S2].ops[80].depth_mm
setups[S2].ops[90].exit_mm
setups[S3].ops[10].to_z
setups[S3].ops[10].direction
setups[S3].ops[10].rough_allowance_mm
setups[S3].ops[10].contour
setups[S3].ops[20].direction
setups[S3].ops[20].contour
setups[S3].ops[30].depth_mm
setups[S3].ops[40].exit_mm
setups[S3].ops[50].exit_mm
```

No qualified gauge/method is selected for this requirement; named available gauges are not substituted for it.

```text
setups[S3].ops[20].checks.radius
setups[S3].ops[50].checks.dia
setups[S3].ops[50].checks.height
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

### `pivot-shaft/plan.toml` — 71 unknown leaves

No certified export-bound drawing revision.

```text
drawing.revision
```

Raw blank/handling/supply datum or starting surface is unsourced or unmeasured; finished nominal geometry is not raw-stock measurement.

```text
stock.length_mm
stock.north_allowance_mm
stock.south_grip_mm
setups[S1].stock_state.north_end_z
setups[S1].stock_state.south_end_z
setups[S2].stock_state.north_end_z
setups[S2].stock_state.south_end_z
setups[S3].stock_state.plain_end_z
setups[S3].stock_state.north_end_z
```

No lathe DRO installation, per-axis Direction or radius/diameter setting is confirmed.

```text
dro.controller
dro.radius_mode
dro.direction.x
dro.direction.z
```

Applicable cutting/edge-treatment choice is not sourced for this route or absent drawing.

```text
setups[S1].coolant
setups[S2].coolant
setups[S3].coolant
```

Author has not supplied a confirmed grip, stop, clamp, support, protection or lubrication decision/measurement.

```text
setups[S1].hold.grip_mm
setups[S1].hold.stop
setups[S1].hold.clamp
setups[S1].hold.centre_lubrication
setups[S1].hold.stickout_mm
setups[S2].hold.grip_mm
setups[S2].hold.stop
setups[S2].hold.clamp
setups[S2].hold.jaw_protection
setups[S2].hold.stickout_mm
setups[S3].hold.grip_mm
setups[S3].hold.stop
setups[S3].hold.clamp
setups[S3].hold.jaw_protection
setups[S3].hold.stickout_mm
```

No sourced paper/jog/pickup/tool/transfer reading or method; compensation/check/retouch cannot be completed numerically.

```text
setups[S1].zero.x.check_jog_mm
setups[S1].zero.z.check_jog_mm
setups[S2].zero.transfer.runout_limit_mm
setups[S2].zero.x.check_jog_mm
setups[S2].zero.z.check_jog_mm
setups[S3].zero.transfer.runout_limit_mm
setups[S3].zero.x.check_jog_mm
setups[S3].zero.z.method
setups[S3].zero.z.paper_mm
setups[S3].zero.z.check_jog_mm
```

Operation direction, allowance, contour, command endpoint or spot/exit depth is not sourced; no process dimension is invented.

```text
setups[S1].ops[10].direction
setups[S1].ops[20].rough_allowance_mm
setups[S1].ops[20].direction
setups[S1].ops[30].direction
setups[S1].ops[40].z_to
setups[S1].ops[40].rough_allowance_mm
setups[S1].ops[40].direction
setups[S1].ops[50].z_to
setups[S1].ops[50].direction
setups[S1].ops[60].direction
setups[S1].ops[70].direction
setups[S1].ops[80].direction
setups[S1].ops[90].direction
setups[S2].ops[10].direction
setups[S2].ops[20].direction
setups[S2].ops[20].contour
setups[S3].ops[10].to_z
setups[S3].ops[10].direction
setups[S3].ops[20].z_from
setups[S3].ops[20].z_to
setups[S3].ops[20].direction
setups[S3].ops[20].contour
```

No qualified gauge/method is selected for this requirement; named available gauges are not substituted for it.

```text
setups[S1].ops[30].checks.finish_ra
setups[S1].ops[50].checks.finish_ra
setups[S1].ops[60].checks.finish_ra
setups[S2].ops[20].checks.height
setups[S2].ops[30].checks.length
setups[S3].ops[10].checks.length
setups[S3].ops[20].checks.height
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

### `rocker-arm/plan.toml` — 85 unknown leaves

No certified export-bound drawing revision.

```text
drawing.revision
```

Raw blank/handling/supply datum or starting surface is unsourced or unmeasured; finished nominal geometry is not raw-stock measurement.

```text
stock.section_mm
stock.length_mm
setups[S1].stock_state.top_z
setups[S1].stock_state.bottom_z
setups[S1].stock_state.local_thickness.pivot_bore
setups[S2].stock_state.top_z
```

Applicable cutting/edge-treatment choice is not sourced for this route or absent drawing.

```text
setups[S1].coolant
setups[S2].coolant
setups[S3].coolant
```

Author has not supplied a confirmed grip, stop, clamp, support, protection or lubrication decision/measurement.

```text
setups[S1].hold.fixed_jaw
setups[S1].hold.grip_mm
setups[S1].hold.jaw_above_parallels_mm
setups[S1].hold.stop
setups[S1].hold.clamp
setups[S2].hold.fixed_jaw
setups[S2].hold.grip_mm
setups[S2].hold.jaw_above_parallels_mm
setups[S2].hold.stop
setups[S2].hold.clamp
setups[S3].hold.supports
setups[S3].hold.grip_mm
setups[S3].hold.stop
setups[S3].hold.clamp
```

No sourced paper/jog/pickup/tool/transfer reading or method; compensation/check/retouch cannot be completed numerically.

```text
setups[S1].zero.x.edge_mm
setups[S1].zero.x.check_jog_mm
setups[S1].zero.y.edge_mm
setups[S1].zero.y.check_jog_mm
setups[S1].zero.z.paper_mm
setups[S1].zero.z.check_jog_mm
setups[S2].zero.x.check_jog_mm
setups[S2].zero.y.check_jog_mm
setups[S2].zero.z.paper_mm
setups[S2].zero.z.check_jog_mm
setups[S3].zero.x.check_jog_mm
setups[S3].zero.y.check_jog_mm
setups[S3].zero.z.paper_mm
setups[S3].zero.z.check_jog_mm
```

Operation direction, allowance, contour, command endpoint or spot/exit depth is not sourced; no process dimension is invented.

```text
setups[S1].ops[10].direction
setups[S1].ops[20].to_z
setups[S1].ops[20].direction
setups[S1].ops[25].direction
setups[S1].ops[30].to_z
setups[S1].ops[30].stock_to_leave_mm
setups[S1].ops[30].direction
setups[S1].ops[40].to_z
setups[S1].ops[40].stock_to_leave_mm
setups[S1].ops[40].direction
setups[S1].ops[50].to_z
setups[S1].ops[50].stock_to_leave_mm
setups[S1].ops[50].direction
setups[S1].ops[60].depth_mm
setups[S1].ops[70].exit_mm
setups[S2].ops[10].direction
setups[S2].ops[20].direction
setups[S2].ops[30].direction
setups[S2].ops[40].to_z
setups[S2].ops[40].stock_to_leave_mm
setups[S2].ops[40].direction
setups[S2].ops[50].to_z
setups[S2].ops[50].stock_to_leave_mm
setups[S2].ops[50].direction
setups[S3].ops[10].direction
setups[S3].ops[20].exit_mm
setups[S3].ops[30].to_z
setups[S3].ops[30].direction
setups[S3].ops[30].contour
setups[S3].ops[40].exit_mm
setups[S3].ops[40].direction
setups[S3].ops[40].contour
setups[S3].ops[50].depth_mm
setups[S3].ops[60].exit_mm
```

No qualified gauge/method is selected for this requirement; named available gauges are not substituted for it.

```text
setups[S2].ops[30].checks.dia
setups[S3].ops[10].checks.dia
setups[S3].ops[20].checks.dia
setups[S3].ops[20].checks.finish_ra
setups[S3].ops[30].checks.height_above_pivot
setups[S3].ops[30].checks.radius
setups[S3].ops[30].checks.arc_len
setups[S3].ops[40].checks.bottom_radius
setups[S3].ops[40].checks.bottom_arc_len
setups[S3].ops[40].checks.tip_land
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
