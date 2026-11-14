# Prechips v0.10

Turn an authored manual-machining process into a printable HTML traveler. Choose a compact professional sheet or a hobby sheet with setup diagrams.

This prototype binds traveler dimensions to a selected CAD/drawing export. Process choices remain authored. The previous implementation is preserved on [`archive/pre-v0.10-2026-11-08`](https://github.com/pedropaulovc/prechips/tree/archive/pre-v0.10-2026-11-08); old code returns only when a useful milestone needs it.

Plans, CAD manifests and shop files are expected to be written by an AI agent, so they are expected to be comprehensive. Built-in profiles require every applicable setup and operation to declare the structured data each check reads, or an explicit opt-out value; nothing is skipped because a field was left out. Values in the inputs are used as written.

## Run

Python 3.12+ and [uv](https://docs.astral.sh/uv/):

```sh
uv sync --locked
uv run prechips traveler examples/base-bar.toml --profile pro --out out/base-bar-pro.html
uv run prechips traveler examples/base-bar.toml --profile hobby --out out/base-bar-hobby.html
uv run prechips traveler examples/end-bracket.toml --profile pro --out out/end-bracket-pro.html
uv run prechips traveler examples/end-bracket.toml --profile hobby --out out/end-bracket-hobby.html
uv run prechips traveler examples/feed-lever.toml --profile pro --out out/feed-lever-pro.html
uv run prechips traveler examples/feed-lever.toml --profile hobby --out out/feed-lever-hobby.html
uv run prechips traveler examples/riser.toml --profile pro --out out/riser-pro.html
uv run prechips traveler examples/riser.toml --profile hobby --out out/riser-hobby.html
uv run prechips traveler examples/leadscrew-kit.toml --profile hobby --out out/leadscrew-kit-hobby.html
uv run prechips traveler examples/carrier.toml --profile pro --out out/carrier-pro.html
uv run prechips traveler examples/carrier.toml --profile hobby --out out/carrier-hobby.html
uv run prechips traveler examples/comparison/pivot-shaft.toml --profile hobby --disable-check turning_deflection --disable-check lathe_holding --out out/pivot-shaft-hobby.html
```

The base-bar, end-bracket, feed-lever, riser, carrier and leadscrew-kit examples declare their milling beams and cuts and pass `milling_deflection` enforced (see [Milling deflection](#milling-deflection)).

Open the HTML in a browser. Print on Letter paper at 100% scale with browser headers and footers off. Files are standalone; hobby embeds its diagrams, so they need no server, internet connection or adjacent image files.
The output must be a different file from the input plan and every active input, including filesystem aliases and active turning configuration files.

The pro base-bar example stays within two Letter pages at 10.5pt. Hobby includes diagrams of all five setups. Dimensions come from the v50 CAD/drawing export (harmonic-analyzer #2739, farm run `20261114T042855752Z`), whose B1–B4 station bands sit on the printed millimetres (47.48 ±0.13 reads 1.8642–1.8744 in). Setup 3 faces both sides, squares both ends and mills both slots in one vise clamping, so Setups 2–3 run in the low belt range and Setup 4 in the high range. Tool selection, allowances, feeds and speeds remain process choices. Since v48 only bar 1 carries the four #12 counterbored bracket holes, and the rail-hole stations are REF only, not drill targets: each bar's own HGR15 rail is trimmed flush with both ends (angle grinder, harmonic-analyzer TL-00 steps 1D–1G), all eight hole centres are measured on it, the rail comes off, and each hole is drilled at its measured centre. The adapter therefore refuses a manifest that tolerances the rail stations. Both vise holds centre the finished bar: the adapter binds `cad.vise_centred_overhang_mm` = (length − `process.vise_jaw_width_mm`)/2. The Setup 4 jack centres stay authored; the adapter refuses one off the bar or inside a rail-hole, counterbore or slot outline. Setup 4's drill and counterbore operations split by end, each over its jack, because the jacks only carry drill thrust.

Drawing sheet 2 swaps bar 2's seats: its rail goes on the face that is up in Setup 4 (marked RAIL SIDE) and the opposite face seats on the mill table, while bar 1's rail goes opposite its C'BORE SIDE, so bar 1 is turned over from Setup 4 to sit C'BORE SIDE down. The v50 manifest describes bar 1 only, so that per-bar face text is authored from the two sheets, not bound. The 1/2 in end mill alone cuts both hold-down slots: with e = (slot width − cutter Ø)/2, the cutter centre traces a rectangle e either side of the arc-centre line and e past each arc centre, which makes the drawn width and overall length. Each end is then two cutter-radius corners, so the end radius departs outward from the drawn arc by e(√2 − 1) (about .006 in). The adapter computes the corners from the manifest and `half_cutter_dia_mm`, prints that cutter size in the operation, and refuses a cutter that is not under the slot width or whose end-radius departure exceeds the drawing's two-place linear tolerance (±.01) applied to the end radius. It also binds `slot_cutter_band_mm`, the slot width band less 2e; the slot operation's `tool_sizing` band checks the shop end mill's `diameter_mm` against it, so a cutter other than the one the offsets assume refuses. Position inspections are bound from the manifest bands: X on the mill DRO before unclamping, rows from ZERO EDGE with calipers.

The end-bracket example (TL-28) prints two pro pages or five hobby pages, one per setup. It follows the 2026-11-02 hand traveler's route and tools, but the v49 drawing wins: two shared-axis #8-32 holes at the KP08 stations, drilled #29 through (tip 1.06 below BAR SIDE, so the KP08-side exit is full size) and tapped plug-then-bottoming from both faces. The export states the thread zones and tip marks only in note text, so the adapter reads them with exact patterns and refuses reworded notes or an inch/mm disagreement. This is the single deliberate prose-parsing exception, kept until harmonic-analyzer exports structured `thread_zone`/`tip_mark` fields. Each face's taps carry one authored flag (`bar_tap_flag_in`, `kp08_tap_flag_in`) in the low half of its tip window, so the two bottoming taps never meet. The sheet names the KP08 face FRONT FACE and the base-bar face BACK FACE; the plan marks them KP08 SIDE and BAR SIDE and says so, and its final screw check runs a flagged screw only to its own face's full thread, short of the opposite face's out-of-phase thread. Unlike the hand sheet, both brackets share each vise clamping, one at each jaw end (each balances the other): every operation runs on both before the next tool, X0 sits on the left part's INNER END and XR on the right part's; the KP08-side tapping lines up on the drilled holes. Hobby pictures both blanks from the bar end the lever leaves, both two-up end-squaring holds, each tapping face as a vise top view of both parts with a section through H1 (thread zone and tap flag of the face being tapped), and the finished bracket.

The feed-lever example (TL-26) prints one pro page or three hobby pages from the 2026-11-02 hand traveler's route and the manifest exported after harmonic-analyzer's 2026-11-13 ruling: the 2X bolt holes are the 11/32 drill, Ø.3438 +.004/0 (the hand sheet's drill; v48/v49 printed the 5/16 normal-fit clearance Ø.344, whose minimum the drill was under), inspected with pin gauges. The manifest's `grip_corners` fillet gives the 2X R.2 grip-end corners and their one-place band; the adapter refuses a manifest without it. The saw cut at 11.85 is the finished grip end: the ZERO END clean-up leaves the length inside 11.8 ±.1, checked on the DRO, so there is no second vise setup. Hobby pictures the lever blank from the bar's squared end, the vise hold and the grip end upright at the end of the bench-vise jaws with its scribed lines and dashed inspection band; the corner operation stops the 45° flat short of the lines and rolls it into the arc.

The riser example (TL-24) prints three pro pages or six hobby pages and passes every check in both profiles, `milling_deflection` included. Its route follows the v49 manifest's process note: a 14.00 in blank of 1/4 × 1-3/4 in 6061 bar, calipered first and faced to .240 on the bare table only when it is over .250 (Stage A from three straps, Stage B from four on faced metal, so each cut bends between two straps no more than 6.75 in apart; Z0 the table), both long edges milled on edge on one 1 in parallel, the ends and the two #30 stop-pin holes P1/P2 cut flat in the vise with each end overhanging the jaws. The other seven holes (R1–R4, HUB, CL, CR) print X/Y LOC REF and are spotted from the carrier at harmonic-analyzer TL-00 step 11C, so Setup 5 drills each at its own mark in one of three vise holds and countersinks R1–R4 from the other face; its table prints the REF X/Y only to find the marks. The adapter refuses a toleranced station on a spotted hole, a spotted hole that no hold puts between the jaws clear of the parallels, and a stop hole that the Setup 4 overhang leaves over a jaw. P2 sits 13.51 from ZERO END, past the 6 in calipers, so its station is read on the DRO before unclamping.

The leadscrew-kit example (TL-VN-84, mm sheet) prints two pro pages or seven hobby pages (eight setup pictures): receive the purchased kit, saw the screw long, mill the cut end to length from the NEAR END, cut the five set-screw flats on the BS-0 dividing head (two per KP08 station at the sheet's 120° clocking; the handwheel flat, open through the cut end in two crossings, in its own 16 mm re-grip because at the cut-end KP08 flats' 42 mm stick-out it would bend about 0.09 mm against the 0.025 mm finish limit) and face the brass nut on the threaded offcut and countersink it. It declares its milling beams and cuts, so it renders with `milling_deflection` enforced. Its manifest has two members: the LeadScrew features bind the default STEP and the FeedNut features carry `configuration = "FeedNut"` with their own `member_steps` STEP; the adapter refuses any other member set. The nut runs on literal speeds because a plan has one `material_key` (the screw's).

The carrier example (TL-21) prints three pro pages or eight hobby pages from the v50 manifest (harmonic-analyzer#2744 farm run, owner rulings 2026-11-13) and passes every check, `milling_deflection` included: each milling setup declares the straps that hold the plate against the cutter's lift (end milling, facing and the ends all strap over the end blocks), and each hole group the two strapped blocks that bracket it. The plate is 20.5 in long, so every milling setup is on the table, vise off, on four 1-2-3 blocks under strap clamps; on edge in the vise the jaws would grip at most 44.9 mm of the 152.4 mm-tall bar, under the one-third rule. The adapter refuses a block under any hole, the HUB included, and a strap toe (`strap_toe_in`) that would land beyond the blocks. Hole coordinates print from the lower-left corner as sheet 2's table does, all from one DRO zero; note 2's relations (B1, A2, B2, CL, CR, R1-R4 from A1 in X and the A1-B1 line in Y) print as their own table and are inspected before tapping by centring the DTI on a pin in each hole, Y corrected for B1's tilt of the line. The .3760-.3770 reamed bores are checked .376 GO / .377 NO-GO with the shop's pin-gauge set. The bores' underside edges carry only the title block's edge break (no chamfer); the TL-VN-78 spacer's seat (`spacer_seat_dia_in`) is authored and the adapter refuses a broken edge that reaches it.

Both jig parts draw from their adapter values (length, section, hole stations and row, hole or tap-drill size, thread zones) and authored holding parameters (jaw width and height, parallel thickness, overhang, edge-finder touch station, kerf). Each saw picture shows only that sheet's blanks; the bar beyond them is an unlabelled stub, so neither plan carries the other part's lengths. Jaws, parallels, cutters, taps and soft jaws are schematic symbols.

The shaft prints two pro pages or four hobby pages, one per setup. Hobby shows its short hold, supported turning, reversal and fit-scribed finishing setup, distinguishing cuts from the kept part and parted waste. Both domes use the [LMS 2569 ball/radius attachment](https://littlemachineshop.com/products/ball-and-radius-turning-tool-small) with its supplied HSS bit; hobby substitutes the attachment method in place of the compact instruction.

The shaft currently exceeds the default finish-bending screen on the last few millimetres of kept body cut before the follower engages (see Turning deflection), and its fit-scribe hold exceeds the unsupported stick-out limit (see Lathe holding). The explicit opt-outs above render its authored process unchanged; they are not a physics pass or machining approval.

Radius, height and cap limits come from CAD; frame-edge-to-tip is radius + 4.7625 mm per the [manufacturer's manual, pp. 4–7](https://littlemachineshop.com/cdn/shop/files/SmallRadiustoolinstructions.pdf?v=15026407504268274368). Jaw positions are set back for the attachment, with a 5 mm full-sweep gap required at setup. The retained 1400 rpm is an authored starting speed, not a supplier recommendation. Pictures share the instructions' CAD/process values; fixture symbols are schematic, not physical attachment models or collision checks.

Setups are numbered in order; operations use unique numbers in increments of ten. Operation tables align work instructions with tooling and cutting settings. Coordinate and inspection tables keep related values together.

### Archived-part comparisons

`examples/comparison/` condenses the archived brass ring, magic tube, T-nuts, cone pivot post, pivot bracket, pivot shaft and rocker-arm plans into the compact format:

```sh
uv run prechips traveler examples/comparison/pivot-shaft.toml --profile examples/comparison/profile.toml --out out/pivot-shaft.html
```

These adaptations retain the archived process choices except the shaft's dome finishing, now using the LMS attachment rather than a stepped contour table. Source files are identified in each TOML header. The shaft, bracket and rocker bind dimensions to their adjacent feature-manifest snapshots; the remaining comparison plans use literal values. The comparison profile renders compact text only and explicitly omits stock-fit and turning-deflection enforcement. Archived longitudinal cuts without structured analysis data fail under built-in profiles rather than being silently accepted. The cone remains a built-up bonded-sleeve route, and the bracket retains the archive's illustrative dimensional intent.

At 10.5pt on Letter paper, the ring uses one page; the tube, T-nuts, bracket and shaft use two each. Pedro approved three pages for the cone and rocker so their remaining instructions stay readable. The cone's reusable fixture manufacture is a separate two-page `cone-pivot-post-fixtures.toml` job.

## CAD dimensions

The examples read feature manifests under `examples/cad/`. Point `cad.file` at the corresponding source file directly to avoid maintaining another copy. Paths are relative to the plan. No STEP reader, FreeCAD, network access or hash checking is involved.

| Adapter | Source | Bound values |
| --- | --- | --- |
| `harmonic_base_bar` | v50 export, HA PR #2739 | Dimensions, REF rail stations, holes, slots, one-cutter slot path, position bands, thread and finish callouts, centred vise overhang, jack-clearance refusal and setup-diagram geometry |
| `harmonic_pivot_shaft` | Archived v40 export | Diameters, reliefs, independent dome radii/heights, attachment projection, setup coordinates, limits and setup pictures |
| `harmonic_pivot_bracket` | Hand-authored example-v39 manifest | Foot/ear geometry, hole locations, arch and inspection limits |
| `harmonic_rocker_arm` | Patched v40 export | Pivot-relative coordinates, outline geometry and inspection limits |
| `harmonic_end_bracket` | Released v49 export | Length/section limits, both #8-32 hole stations and row, tap-drill band, full-thread zones, bottoming-tap tip marks by face and setup-picture geometry |
| `harmonic_feed_lever` | v50 export (2026-11-13 hole ruling; harmonic-analyzer#2739 farm run) | Length/section limits, both clearance-hole stations, row and diameter band, grip-corner radius and band, `overhang_mm` from the authored `overhang_in` and setup-picture geometry |
| `harmonic_riser` | Released v49 export | Length/width/thickness limits, P1/P2 station and row bands, REF X/Y of the seven spotted holes with their Setup 5 holds, hole and countersink bands, centred and end overhangs and setup-picture geometry |
| `harmonic_leadscrew_kit` | v50 export, HA PR #2740 (two members) | Cut length and supplied screw, five flat stations, across-flat/length/clock bands, flat cutter centres from either end, nut length/flange/body/hole limits, countersink mouth and cutter band, and setup-picture geometry |
| `harmonic_carrier` | v50 export (harmonic-analyzer#2744) | Plate envelope limits, the 12-hole table in the sheet's lower-left-corner frame, A1-relative station and row bands (note 2), pin ream band, tap threads and drill bands, HUB as assembly-only, 1-2-3 block stations clear of every hole, and the authored spacer seat around the broken underside edge |

```toml
[cad]
file = "cad/base-bar-v50.toml"
adapter = "harmonic_base_bar"

[parameters]
blank_length_in = 17.4375
blank_width_in = 6.0
blank_thickness_in = 0.5
quantity = 2
width_rough_allowance_in = 0.015
slot_breakthrough_in = 0.02
slot_step_in = 0.12
half_cutter_dia_mm = 12.7
vise_jaw_height_mm = 44.9453
parallel_height_mm = 34.925
```

All supplied parameters must be finite numbers. `blank_length_in`, `blank_width_in` and `blank_thickness_in`, when supplied, must be positive in every profile. The base-bar adapter requires `half_cutter_dia_mm`, the end mill that cuts the slots, and `vise_jaw_height_mm` and `parallel_height_mm`, which with the thicknesses give the bar's stand-out above the vise jaws; it refuses a finished bar top at or below the jaw tops. `quantity`, when supplied, must be a positive integer (not a fractional value, float or boolean) in every profile. Literal-only plans can omit parameters, including `quantity`; the saw diagram requires `quantity`.

Use named bindings such as `{{cad.length_in:.2f}}` and `{{process.blank_length_in:fraction}}` in text. `:.1dot` (any one-digit precision) prints fixed places in shop shorthand without the leading zero, as in `~{{process.overhang_in:.1dot}}` → `~.4`. A whole-field binding can supply structured data, as in `rows = "{{cad.hole_rows}}"`. Unknown names fail; bindings do not execute expressions. See `examples/base-bar.toml` for the complete recipe.

Each adapter applies the selected plan's setup frames and distinguishes model geometry from requirement limits. Named bindings update repeated dimensions and coordinate tables together. Conflicting machining targets and source acceptance limits are input errors. The shaft's reference span remains REF: its final length still follows the assembly fit. The rocker's hub-length aim is authored; its strap aim follows that aim and the bound face depths. Selected tools and gauges remain separate from source acceptance limits.

Changing CAD dimensions does not select new tools or redesign the machining process. Unsupported coordinate frames and conflicting cap geometry fail with an input error; general tool and gauge suitability is not checked. Literal-only plans work with a custom profile that omits `stock_fit`.

## Stock fit

Both built-in profiles enforce stock fit. Exact fits pass; an undersized or missing dimension stops the command with exit 2 before writing output. Successful checks add nothing to the sheet.

| Part | Declared stock | Required size |
| --- | --- | --- |
| Base bar | `blank_length_in`, `blank_width_in`, `blank_thickness_in` | CAD nominal envelope in matching axes |
| Pivot shaft | `stock_dia_mm`, `stock_length_mm` | Maximum nominal shaft diameter and authored sawn-blank demand |
| Pivot bracket | `raw_width_mm`, `raw_length_mm`, `sawn_height_mm` (mm) | CAD nominal envelope: model X across foot and ear, model Z outer face to foot free end, model Y seat to arch crown |
| Rocker arm | `stock_length`, `stock_width`, `stock_thickness` (mm) | CAD nominal envelope: model X between radial tip lands, model Y bottom-arc low point to top-edge ends, model Z between hub faces |
| End bracket | `blank_length_in`, `blank_thickness_in`, `blank_width_in` | CAD nominal envelope: model X length, model Y across the 1/2 in bar, model Z up the 1 in bar |
| Feed lever | `blank_length_in`, `blank_thickness_in`, `blank_width_in` | CAD nominal envelope: model X length, model Y through the 1/2 in thickness, model Z across the 1 in width |
| Riser | `blank_length_in`, `blank_width_in`, `blank_thickness_in` | CAD nominal envelope: model X length, model Y width, model Z thickness |
| Leadscrew kit | `screw_stock_length_mm` (must equal the manifest's supplied length) | Nominal cut length |
| Carrier | `blank_length_in`, `blank_width_in`, `blank_thickness_in` | CAD nominal envelope: model X length, model Z width, model Y thickness |

For the shaft, `stock_length_mm` is the available bar length. The header specifies the blank to saw from it, including the route's authored stub and facing allowances. The final length still follows fit-up and the scribe; the stock check does not convert the REF span into a finished-length acceptance limit.

For the bracket and rocker, the declared values are the sawn flat-bar blank, not the authored prepared (squared) blank. Their adapters already refuse raw stock smaller than the prepared blank (except the rocker's `stock_length`, which the adapter does not read), so that input error comes first unless the prepared size is also below the CAD envelope.

There is no automatic rotation, yield calculation, added allowance or workholding check.

## Turning deflection

Both built-in profiles enforce `turning_deflection`, a narrow static bending screen for declared longitudinal turning of solid round stock. Default limits are **0.10 mm rough** and **0.005 mm finish** on the estimated **radial** bending at the tool; the diameter error left behind is about twice that, so the finish default corresponds to roughly 0.010 mm on diameter. These are authored limits, not guaranteed diameter error or handbook tolerances. A predicted exceedance or missing applicable data exits 2 before creating or replacing output. Successful checks print nothing on the traveler.

Declare `machine_kind = "lathe"` or `"other"` on every setup. Each lathe operation declares `cut_kind = "longitudinal_turning"` or `"other"`; facing, parting, grooves, attachment domes and other unsupported cuts use `"other"` and are outside this model, not checked passes. Longitudinal cuts require root `turning_material`, setup `turning_support`, and nonempty operation `turning_cuts` with explicit numeric geometry, DOC and feed. Printed material names and feed prose are not parsed. Numeric fields can use existing CAD/process bindings.

For numeric analysis fields, use exact whole-field bindings without formatting, such as `start_z_mm = "{{cad.body_cut_start_z}}"`; these preserve the underlying number and precision. Formatted bindings such as `:g` remain text and are refused where analysis requires a number.

Supports are `chuck_only` (`chuck_z_mm`), `tailstock` (also `centre_z_mm`), or `follower` (also `engage_z_mm`, `offset_mm`, `pad_width_mm`). Follower credit requires a toward-chuck traverse and a whole pad band on already-turned continuous cylindrical land produced by the declared pass; before engagement the model uses chuck/centre supports. It checks the declared pad footprint and both sides of engagement, not STEP gaps, actual pad contact/capacity or machine compliance.

Each cut declares `name`, `phase = "rough" | "finish"`, `start_z_mm`, `end_z_mm` (the full tool traverse), `kept_start_z_mm`, `kept_end_z_mm` (the retained feature inside that traverse), `start_diameter_mm`, `end_diameter_mm`, `max_radial_doc_mm`, `feed_mm_rev`, and `minimum_diameter_mm` (the smallest existing section elsewhere). An optional `max_deflection_mm` may tighten, but not relax, that cut's configured phase limit. The model conservatively bounds the declared maximum radial DOC at the final diameter, using the smaller of that diameter and the declared minimum section for bending stiffness. It does not assume a particular rough-pass order.

The limit applies over the kept range only, so sacrificial stubs, run-in in waste and parted-off ends are traversed but not held to it. Both bounds are required and must lie inside the traverse; when the whole traverse is kept, bind them to the same values as `start_z_mm`/`end_z_mm`. The screen cannot tell what is waste on its own and deliberately assumes nothing, so bind the bounds from CAD/process values rather than typing them. Support validation (in-span, no chuck crossing, follower band on turned land) always covers the whole traverse, and a refusal reports both the kept maximum and the whole-traverse maximum.

The supplied shaft binds its journal cuts to the kept journal (`north_apex_z` to `north_shoulder_z`, so the Ø5.7-bounded stub beyond the apex is excluded) and its body cuts to the longest body the fit-scribe can keep (`body_kept_end_z` = follower pad band − waste margin + dome height). The journal passes. The body finish still refuses at **Op 60**: the kept body reaches about 4 mm past follower engagement at Z152, and immediately before engagement the model estimates about 0.009 mm radial (≈0.018 mm on diameter) against the 0.005 mm limit and the 6.33–6.35 bearing band. That is a finding about the plan, not about waste: the follower engages after the last few millimetres of kept body have been cut on chuck/centre support alone, and the pad band is then set on a land turned under that deflection. The example retains its authored feeds and support geometry rather than tuning them to pass; the explicit opt-out above renders it unchanged.

Packaged [`turning.toml`](src/prechips/turning.toml) holds editable coefficients and source notes. Unit power comes from *Machinery's Handbook*, printed pp. 1085–1086 (corpus PDF pages 1406–1407); feed and wear factors are on printed p. 1087 (PDF 1408). Default material keys deliberately encode proxies, not measured stock properties:

| Key | Unit-power condition | Elastic-modulus proxy | Drill `Kd` |
| --- | --- | --- | --- |
| `aluminum` | Rolled (hard) aluminum | Wrought 2014-T6, 73 GPa | 7,000, most aluminum alloys |
| `aluminum_6061` | Rolled (hard) aluminum, the closest row for 6061-T6/T6511 | 6061-T6, 70.3 GPa | 7,000, most aluminum alloys |
| `brass` | Medium brass | Naval brass, 103 GPa | 14,000, most brasses |
| `bronze` | Medium bronze | Phosphor bronze ASTM B159, 103 GPa | none (no handbook row) |
| `steel_1018` | Authored plain-carbon steel 160–180 HB proxy | SAE 1025, 207 GPa | 24,000, steel 200 Bhn |
| `steel_o1` | Authored **annealed** tool-steel 200–250 HB proxy; not hardened O1 | Steel-family proxy, 207 GPa | 31,000, steel 300 Bhn |
| `stainless_304` | Authored annealed type 304 proxy, stainless 175–200 HB | Stainless 18-8, 190.3 GPa | 35,000, austenitic (type 316) thrust |

Nonferrous modulus references are handbook printed p. 204 (PDF 525) and, for 6061-T6 and 18-8 stainless, p. 420 (PDF 741); steel references are printed p. 474 (PDF 795). Drill `Kd` values are Table 8, printed p. 1090 (PDF 1411); the table has no bronze row, so drilling bronze needs a configured `drill_kd`. Choose data appropriate to actual material condition. The default radial/tangential force ratio of 1.0 is an explicit authored assumption (small DOC on a nose radius pushes the radial component toward the tangential one), not a universal measured ratio. Only the radial component is compared with the limits; the tangential force is reported but moves the work along the cutting direction, a second-order diameter effect. The screen uses a circular minimum section and omits machine compliance, chatter, thermal effects, hollow stock and discontinuous/profiled cuts. It is a practical prototype, not a certificate or general machining-safety check.

Override only the values you need; a custom TOML merges partial tables over packaged defaults:

```toml
# shop-turning.toml
[limits]
finish_mm = 0.005

[materials.steel_1018]
elastic_modulus_gpa = 207.0
```

Use `--turning-config path/to/shop-turning.toml`, or set `turning_config = "shop-turning.toml"` in a custom profile (relative to that profile). The CLI file takes precedence, and the same file also overrides the `[milling]` and `[drilling]` sections (see [Milling deflection](#milling-deflection)). New material keys require both `unit_power_hp_min_per_in3` and `elastic_modulus_gpa`; `drill_kd` is optional and only drilling and plunging read it. Unknown configuration keys, invalid numbers and feeds outside the factor table fail rather than extrapolate.

For an explicit opt-out, use `--disable-check turning_deflection`, or omit it from a custom profile's `enforce` list. `--disable-check` is repeatable and also accepts `stock_fit` and `setup_diagrams`; CLI disables win over the selected profile. When turning and milling deflection are both disabled, the configuration is intentionally not read, even if a config path was supplied. Disabling a check adds no warning, checker status or certificate to the sheet.

## Milling deflection

Both built-in profiles enforce `milling_deflection` (`src/prechips/milling.py`), a static bending screen for every mill and drill-press cut, vise and table holds alike. Each setup declares how the part is held as a beam; each spindle operation declares its cuts. At every declared cut station the handbook cutting force bends that beam, and the worst station and bending axis of each cut is compared with its phase limit. A predicted exceedance or missing data exits 2 before creating or replacing output and names the setup, operation and cut, the estimated bending, the limit and the governing span. A pass prints nothing on the traveler. It runs with the declared-input checks (after `vise_holding`) and is disabled with `--disable-check milling_deflection`.

Default limits are **0.10 mm rough** and **0.025 mm finish**, authored, not handbook tolerances. The finish limit is one-tenth of the drawings' tightest general band (title-block .XXX ±.005 in, 0.254 mm wide), about .001 in. The rough limit matches turning and stays below the smallest authored finish allowance (.005 in, 0.127 mm), so the finish pass still cleans up. Per-cut `max_deflection_mm` may only tighten the phase limit.

Coverage, with no inference from prose:

- Every setup declares `machine_kind`. Lathe setups and their operations take neither `beam` nor `milling_cuts`; `turning_deflection` covers them.
- Every other setup declares `beam`: a table, or `"other"` only when none of its operations cuts with the spindle (saw, bench, hand tap, filing, inspection).
- Every operation with a `tool` declares `speed_kind`. A `speed_kind = "spindle"` operation declares `milling_cuts`: cut tables, or `"other"` only when the spindle removes no material (edge finder, indicator). Other operations take neither `milling_cuts` nor `beam`.
- A cutting operation may declare its own `beam`, which replaces the setup's table for its cuts: a re-grip, or a jack under a drill that a lifting end mill would not load.

```toml
beam = { axis = "x", hold = "cantilever", extent_mm = [0, "{{cad.blank_length_mm}}"], clamp_mm = "{{process.strap_x_mm}}", section_mm = { y = "{{cad.width_mm}}", z = "{{cad.blank_thickness_mm}}" } }
milling_cuts = [
  { name = "left end to ZERO END", kind = "side", phase = "finish", material = "aluminum_6061", cutter_dia_mm = 12.7, flutes = 2, axial_doc_mm = "{{cad.blank_thickness_mm}}", radial_woc_mm = 0.508, rpm = 1250, feed_mm_min = 152.4, stations_mm = 0 },
]
```

`axis` is the machine axis along the part; stations are millimetres along it in any frame the setup chooses, and `extent_mm` is the part's `[start, end]` in that frame. Holds:

- `cantilever`, with `clamp_mm` (a station or `[start, end]`: vise jaws, a strap pair, a chuck): a station inside the clamp does not bend; outside it is a cantilever from the nearer clamp edge, F·L³/(3EI).
- `between`, with `supports_mm = [a, b]`: two points that hold the part in the bending direction (straps, centres, a jack under a drill). Between them a pinned span, F·a²·b²/(3EI·l); beyond one, an overhang c, F·c²·(c + l)/(3EI). A block or jack only pushes; it is no support against a lifting end mill.
- `solid`, with `seat` (the rigid seat, stated) and `seat_mm`: a drill or plunge pushes straight down onto that seat (parallels under the hole, the table), no bending; a station off the seat refuses. A seat only takes a downward push, and every milling cut also loads the part across the spindle (side and slot cuts lift it too), so milling kinds refuse on a seat and need a cantilever or between beam. A hole between two parallels is not over a seat: it is a beam across them.

`section_mm` is the smallest section of the free span: the two sizes across the beam (`{ y, z }` for a beam along x; I = b·d³/12 with d along the bending axis), or `{ diameter }` for round work in a chuck or dividing head (I = π·D⁴/64). Solid holds take no section.

Each cut declares `name`; `kind` = `side` (periphery, `radial_woc_mm` below Ø), `slot` (full width, `radial_woc_mm` = Ø), `end` (end teeth produce a floor or face; width = stepover), `face` (face mill or fly cutter), `plunge` (centre-cutting end mill fed axially) or `drill`; `phase` = `finish` when the cut makes a surface or size the drawing holds (including drilled holes and tap drills), `rough` when a later cut removes it; `material`, a configured key (per cut, since one plan may cut several members of different materials); `cutter_dia_mm`; integer `flutes`; `feed_per_tooth_mm`, or `rpm` with `feed_mm_min` (feed per tooth = feed ÷ (rpm × flutes); hand-fed cuts declare the feed the operator applies; a cut `rpm` must equal the operation's numeric `rpm` when it has one, so a changed spindle setting refuses until the cut is updated); and where it cuts, either `stations_mm` (one or more points: holes, a cut across the beam) or `traverse_mm = [start, end]` (a pass that travels along the beam, judged at its ends and at mid-span of a pinned span inside it, which bound every point between). Milling kinds also declare `axial_doc_mm` and `radial_woc_mm`; drills and plunges take neither. The loaded axes are not declared: a milling cut bends the beam in both axes across it, a drill or plunge only along the spindle (z), and on a beam along z (a part upright, drilled or plunged on its end) that thrust compresses the part and does not bend it, so no thrust data is read. Numeric fields accept exact whole-field bindings.

The spindle is vertical (machine Z). Milling uses the handbook mean tangential force, unit power × removal rate ÷ cutting speed: Ft = 396000·Kp·C·W·w·d·ft·nt/(π·D) lbf in inches, where rpm cancels (printed pp. 1085–1088, PDF 1406–1409). C is the same feed-factor table as turning, read per tooth for milling; W is 1.10 for end and slab milling and 1.25 for `face` (the top of light and medium face milling). Along the spindle the force is Ft × `axial_ratio`, the helix lift of side and slot cuts or the end-tooth push of end and face cuts; across it the rotating resultant Ft·√(1 + `radial_ratio`²) is applied in each horizontal axis across the beam. Both ratios are authored at 1.0: tan 45° covers the 30–45° helices of general-purpose and aluminium end mills, and the radial ratio matches turning. Drills and plunges use the handbook thrust T = 2·Kd·Ff·FT·B·W + Kd·D²·J·W (printed pp. 1090–1092, PDF 1411–1413) with standard-drill chisel factors (c/d 0.18) and W 1.30; a plunging end mill reuses it as an authored proxy. Beam cases are printed pp. 261, 264 and 265; sections pp. 239 and 255.

This is a stiffness screen at the cut, not predicted dimensional error. It uses the mean force over a revolution (intermittent tooth peaks are higher), ideal clamps and pins, and a uniform minimum section, and omits chatter, clamp slip, one-sided supports, cutter and machine compliance, torsion and thermal effects.

The former base-bar Setup 3 refuses (`tests/test_milling.py` keeps it as the positive control). With the bar strapped only at blank mid-length, squaring the left end (finish .020 in passes, 1/2 in two-flute end mill at 1250 rpm and 6 in/min, the full .5 in engaged) is a 221.5 mm cantilever: 26.6 N axial force bends it an estimated **0.057 mm** along Z against the 0.025 mm finish limit, and the right end's .010 in passes 0.029 mm. Squaring in the vise clamping instead, with the blank centred in the 158.67 mm jaws and faced to .47 in, leaves 142.1 mm cantilevers: 0.017 mm and 0.009 mm, a pass, which is what `examples/base-bar.toml` Setup 3 now does. With `axial_ratio` = tan 30° (0.577) the strap value would still be 0.033 mm. Keep that refusal; do not tune ratios, limits or declarations to pass.

The `[milling]` section of packaged `turning.toml` holds the limits, ratios and wear factors; `[drilling]` the thrust tables (feed factors, diameter factors, chisel factors, wear). Override them like the turning values:

```toml
# shop-turning.toml
[milling]
finish_mm = 0.02
```

## Declared-input checks

v0.8 adds checks that read explicit structured plan fields and shared shop records. Both built-in profiles enforce every one after stock fit and turning deflection. A refusal exits 2 before output is created or replaced and names the check; a pass prints no checker text. Each key works with `--disable-check` and in a custom profile's `enforce` list.

Numeric fields are millimetres and accept exact whole-field bindings such as `"{{cad.bearing_dia}}"`. Setups name their machine with `machine_ref`, a key under `[machines]` in the shop file. Only shop records a plan references are validated; unknown fields in a referenced record are errors.

```toml
# In the shop file:
[machines.pm-30mv]
kind = "mill"                 # mill, lathe or dividing_head
rpm_ranges = [[50, 3000]]
travel_mm = { x = 584.2, y = 222.25, z = 355.6 }
spindle_to_table_mm = [60.96, 431.8]

[workholding.chuck-3jaw-6]
kind = "chuck"                # chuck or collet
grip_range_mm = [3.0, 140.0]  # or grip_sizes_mm = [...]
body_diameter_mm = 158.0
body_length_mm = 72.0

[gauges.micrometers]
range_mm = [0.0, 76.2]
resolution_mm = 0.00254

[limits]
stickout_ld_max = 4.0
tool_change_clearance_mm = 25.0
```

Lathes also take `swing_over_bed_mm`, `swing_over_cross_slide_mm` and `between_centres_mm`; dividing heads take `worm_ratio`, `plate_holes` and `direct_index_positions`.

### Cutting speeds

Key `cutting_speeds`. Every operation with a `tool` declares `speed_kind = "spindle"` or `"other"` (hand tapping, sawing, bench work). A `spindle` operation needs an rpm (authored, shared or calculated) inside one of its setup machine's `rpm_ranges`, inclusive; an `other` operation, or one without a tool, must not carry an rpm. Feeds, feed text and cutting performance are not checked.

Independently of enforcement, a shared setting may calculate its values. `sfm` replaces a literal `rpm` (never both): the operation supplies `cut_diameter_mm` and its setup a `machine_ref`; rpm = 12·sfm/(π·D_in), rounded to the nearest 50 with ties to even, clamped to the machine's lowest and highest speed, and dropped to the top of the range below when it falls in a gap. Instead of literal `feed`, declare `feed_mm_rev` (prints `0.05 mm/rev`) or `chip_load_mm_per_tooth` with `flutes` (feed = rpm × flutes × chip load, printed to whole `mm/min` or, with `feed_unit = "in/min"`, to 0.1 in/min). An authored operation `rpm` or `feed` still wins and is neither rounded nor clamped; a per-tooth feed uses the operation's resulting rpm.

```toml
[settings.shaft-finish-turn-hss-1018]  # shop file
tool = "shaft-hss"
material = "shaft-1018-cold-finished"
sfm = 110
feed_mm_rev = 0.05

[[setups.operations]]                  # plan; setup has machine_ref
speed_kind = "spindle"
tool = "hss"
settings = "shaft-finish-turn-hss-1018"
cut_diameter_mm = "{{cad.bearing_dia}}"  # 6.35 -> 1700 rpm
```

### Tool sizing

Key `tool_sizing`. Every operation with a `tool` declares `sizing`; an operation without a tool must not. Use `sizing = "other"` when no drawing size binds the cutter (saws, roughers, spot and pilot drills, taps, lathe tools), or a table:

```toml
sizing = { kind = "band", band_mm = "{{cad.bracket_dia_band_mm}}" }  # [low, high]
sizing = { kind = "tap_drill", tap = "tap" }                         # a plan tool id
```

A band passes when the operation tool's `diameter_mm` lies inside the inclusive band; a reversed band refuses. A tap drill passes when the operation tool's `diameter_mm` equals the named tap's `tap_drill_mm` within 1e-6 mm. Plan `[[tools]]` and shop `[tools.<ref>]` records take numeric `diameter_mm` and `tap_drill_mm` (never printed); shop values flow into the plan tool unless it sets its own. A missing diameter or tap drill, an unknown tap id or a missing `sizing` refuses. The base-bar adapter supplies each drawing limit as `<limit>_band_mm` (such as `bracket_dia_band_mm`, `counterbore_dia_band_mm`, `slot_width_band_mm`), plus `slot_cutter_band_mm` for its slot operation: the cutter cuts its Ø plus twice the adapter's path offset e, so the band is the slot width band less 2e, and a shop end mill other than the one the offsets assume refuses.

Only the selected tool is compared; no nearer tool is suggested. Thread designation, tap class, operation order, reaming allowance and actual cut size (runout, drill wander) are not checked.

### Indexing

Every setup declares `indexing`: `"none"`, or a dividing-head table naming a shop machine of kind `dividing_head`.

```toml
indexing = { head = "bs-0", tolerance_deg = 0.0795, angle_deg = 12.5182 }  # one setting
# indexing = { head = "bs-0", tolerance_deg = 0.05, angle_deg = 30, positions = 3 }  # open pattern
# indexing = { head = "bs-0", tolerance_deg = 0.05, positions = 7 }  # full circle, step 360/7
```

Candidates are direct indexing (`direct_index_positions`) and every `plate_holes` circle through `worm_ratio` (spaces = angle × ratio × holes / 360), in exact rational arithmetic on the authored decimals. An exact representation wins; otherwise the smallest one-step error, then direct, plate name and smaller circle. Each cumulative landing error, and for a full circle the closure against the nearest whole revolution, must be within `tolerance_deg`. The sheet prints the selection whenever a table is declared, independent of enforcement, as an `Index:` line such as `B 23-hole circle: 1 turn + 9 spaces; 12.5217° (target 12.5182°)`; an uncomputable table (unknown head, no plate data, neither angle nor `positions >= 2`) is an input error. Backlash, fixture tilt, locating the work and cutter access are not checked.

### Gauge capability

`gauge_capability` requires `gauge_checks` on every setup and operation that has `inspection` text, and refuses it where there is none. Use `gauge_checks = "other"` for non-dimensional acceptance (finish, fit-up, visual), or one entry per dimensional limit the inspection text states:

```toml
inspection = "Ø{{cad.bearing_dia_min:.3f}}–{{cad.bearing_dia_max:.3f}}; Ra ≤{{cad.bearing_finish:g}} µm."
gauge_checks = [{ gauge = "micrometers", band_mm = ["{{cad.bearing_dia_min}}", "{{cad.bearing_dia_max}}"] }]
```

`gauge` names a `[gauges]` record. Its `range_mm` must contain both ends of `band_mm`, and its `resolution_mm` must not exceed the band width (high − low); a one-sided MAX limit is the band `[0, max]`. Text that mixes dimensional and non-dimensional limits declares only the dimensional ones (the Ra above). Gauge kind, datum and reading method, check timing, GO/NO-GO pairs and roughness ranges are not checked, and the inspection text is not parsed.

### Lathe holding

`lathe_holding` checks each lathe setup's grip and unsupported stick-out. Every setup declares `machine_kind`; every lathe setup declares `lathe_hold`, either `"other"` (explicit opt-out, e.g. faceplate work) or:

```toml
lathe_hold = { chuck = "chuck-3jaw-6", grip_diameter_mm = 10.0, stock_diameter_mm = 10.0, stickout_mm = 15.0, minimum_diameter_mm = 10.0, support = "none" }
```

`chuck` names a `[workholding]` record with `kind = "chuck"` or `"collet"`; any other kind refuses. `grip_diameter_mm` must lie inside a chuck's inclusive `grip_range_mm`, or equal (within 1e-6 mm) one of a collet's `grip_sizes_mm`. `stock_diameter_mm` is the largest swung diameter and must be at least the grip and minimum diameters. With `support = "none"`, `stickout_mm` (jaw fronts to free end) must not exceed `limits.stickout_ld_max` × `minimum_diameter_mm`, the smallest diameter in the exposed span; equality passes. `support = "tailstock"` or `"steady_rest"` lifts that limit. A setup with `turning_support` must agree: `chuck_only` ↔ `none`, `tailstock`/`follower` → `tailstock`. Non-lathe setups must not carry `lathe_hold`. Not checked: jaw depth or clamping force, runout, supported bending, spindle-bore clearance, or whether the declared support is installed.

The shaft's first three setups pass (the reversed hold is 22 mm against 4 × Ø5.7 = 22.8 mm). The fit-scribe setup refuses: its stick-out follows the actual scribe, bound as the largest expected reading plus the 16 mm attachment-clearance jaw offset (`fit_stickout_max` = 17.33 + 16 = 33.33 mm), against 4 × Ø6.35 = 25.4 mm on the unsupported bearing. That is a finding about the plan; render it with `--disable-check lathe_holding`.

### Vise holding

`vise_holding` checks each milling-vise hold. Every non-lathe setup declares `vise_hold`: `"other"` (table clamps, saw, bench: no milling vise), a table, or an array of tables when the setup re-grips the part (refusals then name `hold N`). Lathe setups must not carry it.

```toml
vise_hold = { vise = "vise-pm-6", across_jaws_mm = 25.4, along_jaws_mm = 302.26, part_height_mm = 12.7, parallel_height_mm = 25.4, overhang_mm = [10.16, "rest"], jaw_offset = "centred", fixed_jaw_face = "as_bought", moving_jaw_face = "as_bought", moving_jaw_contact = "flat" }
```

`vise` names a `[workholding]` record with `kind = "vise"`, `jaw_width_mm`, `opening_mm` and `jaw_height_mm` (vise bed, where parallels sit, to jaw top); `bed_height_mm` (table to vise bed) is recorded but this check does not use it. `parallel_height_mm` is 0 for work on the bed. `overhang_mm` is `[left, right]` past the jaw sides; a negative value is the part end's inset inside the jaws. One side may be `"rest"`: along − jaw width − the other side. Two numbers must agree with jaw width and `along_jaws_mm` within 0.01 mm of authored rounding. `jaw_offset` is `"centred"` or `"balanced"`; a balanced hold adds `balance = "twin_part"` (an identical part mirrored at the other jaw end; the hold describes one of them) or `"spacer"` (a same-thickness block). Faces are `"machined"`, `"as_bought"` or `"sawn"`; `moving_jaw_contact` is `"flat"` or `"rod"`. Equalities pass, except that parallels must be strictly below the jaw top:

- `across_jaws_mm` ≤ `opening_mm`.
- `parallel_height_mm` < `jaw_height_mm`, strictly: parallels level with the jaw top leave nothing gripped, so equality refuses. Kurt: "select a size that keeps the bottom of the clamped part at or below the top of the movable and stationary jaws" ([DX6 manual](https://www.kurtworkholding.com/wp-content/uploads/2024/05/Kurt-DX6_Manual_2024-05-30.pdf), p. 5).
- Grip depth min(part height, jaw height − parallels) ≥ `limits.vise_grip_min_mm` and ≥ `limits.vise_grip_fraction_min` × part height.
- `"centred"` requires the midpoint of the gripped span along the jaws to lie within the middle third of the jaw width: |midpoint − jaw width / 2| ≤ `limits.vise_centre_fraction_max` × jaw width / 2. Otherwise declare `"balanced"`. The one-third is a house rule; no source publishes a number. "Whenever possible, the workpiece should be clamped in the center of the vise jaws. However, when necessary to mill a short workpiece which must be held at the end of the vise, a spacing block of the same thickness as the piece should be placed at the opposite end of the jaws." ([TC 9-524](https://armypubs.army.mil/epubs/DR_pubs/DR_a/pdf/web/tc9_524.pdf), p. 8-16; Kurt DX6 p. 5 agrees.) A `"twin_part"` must lie wholly on one side of the centre, or its mirrored twin would overlap it.
- Overhang geometry feeds the two rules above only: overhang rigidity is not judged. No handbook, vise maker or training text gives an overhang limit, and the texts treat overhang past the jaw end as normal practice (Krar Unit 62; *Introduction to Machining* §9.11).
- A machined fixed-jaw face against an unmachined moving-jaw face needs `moving_jaw_contact = "rod"`: Krar, *Technology of Machine Tools* 6th ed., Unit 62 ("Place round bar between side 4 and movable jaw"), and [*Introduction to Machining* §9.11](https://workforce.libretexts.org/Sandboxes/a072766d-16cb-4dbc-9dd2-2f3c784c59e6/Introduction_to_Machining/09%3A_Manual_Vertical_Milling_Machines/9.11%3A_Block_Squaring). A rod between two machined faces is allowed: Krar says "not required", §9.11 "Do not use a round bar", Anderson & Tatro's *Shop Theory* (p. 309) still uses it. A sawn face against the fixed jaw is refused; that is a house rule with no published source.

The example shop declares `vise_grip_min_mm = 6.0`, Pedro's house choice: no published minimum exists for smooth jaws (Mitee-Bite says only that they need "much more than .060"" clamped). `vise_grip_fraction_min = 0.3333` is a common rule of thumb, not a standard: "Hold at least one-third of the part’s height in the jaws (more for tall, thin parts), and cut only the part that sticks out." ([Engineer Underground, "Workholding and Fixturing"](https://engineerunderground.com/resources/makers-fabrication/cnc-machining/workholding-fixturing/)). Training texts are stricter: "The parallels selected for a job should provide no more than ⅛" of extra material above the jaw plates" beyond the cut ([*Introduction to Machining* §9.5](https://openwa.pressbooks.pub/intromachining1/chapter/wa9-5/)), and "These parallels should only be high enough to allow the required cut" (TC 9-524, p. 8-15). A shop that wants that guidance can raise the fraction. `vise_centre_fraction_max = 0.3333` is Pedro's house rule (TC 9-524 says only that work held at the end of the vise needs a spacing block); both fractions must be above 0 and at most 1. *Machinery's Handbook* (27th ed.) has no vise guidance. Not checked: clamping force, jaw lift, cutting loads, overhang rigidity or deflection, part stability on the parallels, matched widths of twin parts, soft jaws or jaw depth.

All three harmonic-analyzer examples pass `vise_holding`. The base bar and feed lever fill the jaw width, so their centred holds sit 0 mm off centre against 26.44 mm allowed. The end bracket holds both brackets at once, one at each jaw end, each balancing the other (its saw operation takes both blanks from the same bar, adjacent, so their as-bought widths match in the jaws); on edge on 1 in parallels it grips 19.55 of its 25.4 mm (≥ 8.47 mm). Envelopes and jig pictures still read jaw and bed sizes from plan parameters that repeat the shop vise record; plan bindings cannot read shop records.

### Machine capacity

`machine_capacity` screens each setup against its `machine_ref` machine. Lathe setups use their `lathe_hold` (opt out with `lathe_hold = "other"`) and the chuck's `body_diameter_mm`/`body_length_mm`: max(stock Ø, chuck body Ø) ≤ `swing_over_bed_mm`, stock Ø ≤ `swing_over_cross_slide_mm`, and `stickout_mm` + chuck body length ≤ `between_centres_mm`. Every other setup declares `envelope`: `"other"` (saw, bench, no machine) or a table checked against a mill:

```toml
envelope = { x_span_mm = 469.9, y_span_mm = [152.4, 12.7], work_top_mm = [25.4, 12.7], deepest_cut_mm = [25.4, -2.032], longest_tool_mm = [6.0, 50.0], shortest_tool_mm = [6.0, 41.0] }
```

Each value is a number or an array summed as a stack, so bindings can name the layers (block + stock, holder gauge + projection, support height + tip Z below the underside). Heights are measured from the table and tool lengths from spindle nose to tip. X/Y spans are the cutter-centre travel the table must make and must not exceed `travel_mm`. Tool change above the work needs `work_top_mm + longest_tool_mm + limits.tool_change_clearance_mm <= spindle_to_table_mm[1]`; reaching the deepest cut needs `deepest_cut_mm + shortest_tool_mm >= spindle_to_table_mm[0]`. Equalities pass. Pairing the deepest cut with the shortest tool is deliberately conservative. Not checked: Z travel, fixture or jaw obstruction, clamps, toolpaths, collisions or fixture footprint on the table.

The base bar binds its stacks from CAD/blank sizes and process parameters: the stated ~18.5 in edge travel, 1-2-3 blocks lying flat (1 in), 1-3/8 in parallels, and archived inventory facts for the vise bed height and R8 collet/drill chuck gauge lengths. Its 1/2 and 5/16 in end mills have no archived length, so the plan bounds them by the neighbouring archived sizes, and its drills by the archived 13/32 in jobber. All base-bar and shaft setups pass.

## Profiles

| Preset | Setup diagrams | Operation instructions | Enforcement |
| --- | --- | --- | --- |
| `pro` (default) | Omitted; diagram files are not opened | Compact `instruction` | Stock fits; turning and milling meet bending limits; every declared-input check passes |
| `hobby` | Included for every setup | `instruction_detailed` when present, otherwise `instruction` | As `pro`; every setup has a readable SVG diagram |

Enforcement is limited to the declared stock, setup-diagram, static longitudinal-turning, static milling/drilling-bending and declared-input contracts. It does not establish machining safety. The diagrams illustrate setups using CAD-derived part dimensions and authored fixture layouts; no FreeCAD is needed.

Use `--profile path/to/profile.toml` for a custom profile:

```toml
name = "illustrated"
features = ["setup_diagrams", "detailed_instructions"]
enforce = []  # Explicitly skip every check; allow missing diagrams.
```

Add `"setup_diagrams"` to `enforce` to require one for every setup; it must also appear in `features`. Add `"stock_fit"` to require CAD and fitting blank dimensions independently of diagrams; add `"turning_deflection"` to enforce the declared longitudinal-turning screen. These and the declared-input keys (`cutting_speeds`, `tool_sizing`, `indexing`, `gauge_capability`, `lathe_holding`, `vise_holding`, `milling_deflection`, `machine_capacity`) are the supported enforcement keys. Feature keys are `setup_diagrams` and `detailed_instructions`: custom profiles must explicitly enable the latter to select detailed operation text, regardless of profile name or diagram selection. Unknown keys are errors.

## Shared tools and cutting settings

Plans can reference one shop file. The base-bar, end-bracket, feed-lever, shaft, bracket and T-nut examples use `examples/shop.toml`; mixed-tool operations and unspecified settings remain inline.

```toml
# In the plan, before any tables:
shop = "../shop.toml"  # Relative to this plan.
material_key = "shaft-1018-cold-finished"

[[tools]]
id = "blade"
ref = "shaft-blade"
name = "Blade"  # Optional local override.

[[setups.operations]]
tool = "blade"
settings = "shaft-relief-1018"
instruction = "Plunge south relief to Ø5.70."
# rpm = 1050  # Overrides only rpm; shared feed remains.
```

```toml
# In the shop file:
[tools.shaft-blade]
description = "M2 square blade"

[settings.shaft-relief-1018]
tool = "shaft-blade"
material = "shaft-1018-cold-finished"
rpm = 1200
feed = "0.02 mm/rev"
```

Tool `name` and `description` overrides are independent, as are operation `rpm` and `feed` overrides. A referenced setting must match the tool's shared identity and the plan's `material_key`, even when both cutting fields are overridden. These identities are explicit; printed material descriptions are not parsed.

Shared strings are literal. Plan-owned overrides retain CAD/process bindings. Missing references, mismatched identities and invalid selected records fail before output. Inline-only plans remain supported, and the shared input file cannot be used as the output. This is an authored library, not tool selection; the only calculation is a setting's declared surface speed and feed rate (see [Cutting speeds](#cutting-speeds)).

## Process TOML

Dimensions and manual feed instructions are strings with explicit units; spindle speeds are positive integer rpm. Tool identifiers connect operations to descriptions and are not printed.

```toml
title = "Part setup sheet"
part = "drawing-part-name"
revision = "drawing revision"
material = "drawing material"
stock = "stock dimensions and quantity"
note = "Optional job-specific prerequisite"

[[tools]]
id = "cutter"
name = "Short tool name"
description = "Tool description and size"

[[setups]]
title = "Operation and setup"
machine = "Machine"
machine_kind = "other"  # Use "lathe" for lathe setups.
holding = "Workholding, orientation and necessary clearance"
datum = "Datum faces, axis directions and zero"
inspection = ["Setup-level inspection and acceptance limits"]
diagram = { file = "diagrams/setup.svg", alt = "Workholding and datum orientation" }

[[setups.operations]]
tool = "cutter"
instruction = "The cut, dimensions and coordinates"
# instruction_detailed = "Optional method detail, replacing the compact instruction"
# rpm = 1000              # Supply the actual authored spindle setting.
feed = "Authored feed with units, or a manual-feed instruction"
inspection = "Operation-specific inspection and acceptance limits"

[setups.operations.table]
columns = ["Feature", "X", "Y"]
rows = [["Feature name", "Authored X coordinate", "Authored Y coordinate"]]
```

Root `note`, tool `name`, setup `holding`, `datum`, `inspection`, and operation `tool`, `rpm`, `feed`, `inspection` and `table` are optional. Omit irrelevant setup fields rather than filling them with boilerplate. Omit `tool` for inspections or work requiring only ordinary shop equipment. Tool names provide short labels in operation tables; the tooling list retains full descriptions. Other shown fields are required; tools, setups and operations must be nonempty. Optional operation tables contain string `columns` and string-array `rows`, each matching the column count. Unknown fields and unresolved tool references produce an input error. Repeat tables in working order; each operation belongs to the most recent setup. Setup inspections print after its operations. Do not invent unknown machining values to fill a field.

An operation's optional `instruction_detailed` must be a nonempty string. With `detailed_instructions` enabled it replaces, never appends to, `instruction`; operations without it retain their ordinary instruction. Put a specific hobby method here rather than repeating the compact paragraph or adding generic tutorials. Both variants share tooling, settings and inspection limits.

`diagram` is optional in the process schema. Its `file` and `alt` strings are required when it is supplied. SVG paths are relative to the process TOML, regardless of the working directory. An enabled diagram must parse as SVG; it is embedded as an image, not executable page markup. In `pro`, unused diagram files are not opened.

## Development

```sh
uv run pytest
uv run ruff check .
uv run ruff format --check .
```

Keep tests to CLI smoke coverage and fragile behavior. Run both profiles and inspect their actual print layouts for sheet changes. No FreeCAD, integrity hashes or certificates in this milestone.

Pedro reviews each milestone. Work must not run more than three milestones ahead of his last review. v0.6 adds shared authored data; v0.7 adds shaft hobby pictures and the round-stock requirement; v0.8 adds declared-input checks; v0.9 moves the base bar to the v48 release and adds the harmonic-analyzer trammel-jig end bracket and feed lever, pro and hobby; v0.10 adds the `vise_holding` check; v0.11 adds the `milling_deflection` check.
