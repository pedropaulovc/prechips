# Prechips v0.8

Turn an authored manual-machining process into a printable HTML traveler. Choose a compact professional sheet or a hobby sheet with setup diagrams.

This prototype binds traveler dimensions to a selected CAD/drawing export. Process choices remain authored. The previous implementation is preserved on [`archive/pre-v0.10-2026-11-08`](https://github.com/pedropaulovc/prechips/tree/archive/pre-v0.10-2026-11-08); old code returns only when a useful milestone needs it.

Plans, CAD manifests and shop files are expected to be written by an AI agent, so they are expected to be comprehensive. Built-in profiles require every applicable setup and operation to declare the structured data each check reads, or an explicit opt-out value; nothing is skipped because a field was left out. Values in the inputs are used as written.

## Run

Python 3.12+ and [uv](https://docs.astral.sh/uv/):

```sh
uv sync --locked
uv run prechips traveler examples/base-bar.toml --profile pro --out out/base-bar-pro.html
uv run prechips traveler examples/base-bar.toml --profile hobby --out out/base-bar-hobby.html
uv run prechips traveler examples/comparison/pivot-shaft.toml --profile hobby --disable-check turning_deflection --out out/pivot-shaft-hobby.html
```

Open the HTML in a browser. Print on Letter paper at 100% scale with browser headers and footers off. Files are standalone; hobby embeds its diagrams, so they need no server, internet connection or adjacent image files.
The output must be a different file from the input plan and every active input, including filesystem aliases and active turning configuration files.

The pro base-bar example stays within two Letter pages at 10.5pt. Hobby includes diagrams of all six setups. Dimensions come from the released v47 CAD/drawing export; the November 7 discussion supplies the table-clamped squaring sequence. Tool selection, allowances, feeds and speeds remain process choices.

The shaft prints two pro pages or four hobby pages, one per setup. Hobby shows its short hold, supported turning, reversal and fit-scribed finishing setup, distinguishing cuts from the kept part and parted waste. Both domes use the [LMS 2569 ball/radius attachment](https://littlemachineshop.com/products/ball-and-radius-turning-tool-small) with its supplied HSS bit; hobby substitutes the attachment method in place of the compact instruction.

The shaft currently exceeds the default finish-bending screen on the last few millimetres of kept body cut before the follower engages (see Turning deflection). The explicit opt-out above renders its authored process unchanged; it is not a physics pass or machining approval.

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
| `harmonic_base_bar` | Released v47 export | Dimensions, holes, slots and setup-diagram geometry |
| `harmonic_pivot_shaft` | Archived v40 export | Diameters, reliefs, independent dome radii/heights, attachment projection, setup coordinates, limits and setup pictures |
| `harmonic_pivot_bracket` | Hand-authored example-v39 manifest | Foot/ear geometry, hole locations, arch and inspection limits |
| `harmonic_rocker_arm` | Patched v40 export | Pivot-relative coordinates, outline geometry and inspection limits |

```toml
[cad]
file = "cad/base-bar-v47.toml"
adapter = "harmonic_base_bar"

[parameters]
blank_length_in = 17.4375
blank_width_in = 6.0
blank_thickness_in = 0.5
quantity = 2
width_rough_allowance_in = 0.015
slot_breakthrough_in = 0.02
slot_step_in = 0.12
slot_finish_diameter_in = 0.53125
```

All supplied parameters must be finite numbers. `blank_length_in`, `blank_width_in`, `blank_thickness_in` and `slot_finish_diameter_in`, when supplied, must be positive in every profile. `quantity`, when supplied, must be a positive integer (not a fractional value, float or boolean) in every profile. Literal-only plans can omit parameters, including `quantity`; the saw diagram requires `quantity`.

Use named bindings such as `{{cad.length_in:.2f}}` and `{{process.blank_length_in:fraction}}` in text. A whole-field binding can supply structured data, as in `rows = "{{cad.hole_rows}}"`. Unknown names fail; bindings do not execute expressions. See `examples/base-bar.toml` for the complete recipe.

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

| Key | Unit-power condition | Elastic-modulus proxy |
| --- | --- | --- |
| `aluminum` | Rolled (hard) aluminum | Wrought 2014-T6, 73 GPa |
| `brass` | Medium brass | Naval brass, 103 GPa |
| `bronze` | Medium bronze | Phosphor bronze ASTM B159, 103 GPa |
| `steel_1018` | Authored plain-carbon steel 160–180 HB proxy | SAE 1025, 207 GPa |
| `steel_o1` | Authored **annealed** tool-steel 200–250 HB proxy; not hardened O1 | Steel-family proxy, 207 GPa |

Nonferrous modulus references are handbook printed p. 204 (PDF 525); steel references are printed p. 474 (PDF 795). Choose data appropriate to actual material condition. The default radial/tangential force ratio of 1.0 is an explicit authored assumption (small DOC on a nose radius pushes the radial component toward the tangential one), not a universal measured ratio. Only the radial component is compared with the limits; the tangential force is reported but moves the work along the cutting direction, a second-order diameter effect. The screen uses a circular minimum section and omits machine compliance, chatter, thermal effects, hollow stock and discontinuous/profiled cuts. It is a practical prototype, not a certificate or general machining-safety check.

Override only the values you need; a custom TOML merges partial tables over packaged defaults:

```toml
# shop-turning.toml
[limits]
finish_mm = 0.005

[materials.steel_1018]
elastic_modulus_gpa = 207.0
```

Use `--turning-config path/to/shop-turning.toml`, or set `turning_config = "shop-turning.toml"` in a custom profile (relative to that profile). The CLI file takes precedence. New material keys require both `unit_power_hp_min_per_in3` and `elastic_modulus_gpa`; unknown configuration keys, invalid numbers and feeds outside the factor table fail rather than extrapolate.

For an explicit opt-out, use `--disable-check turning_deflection`, or omit it from a custom profile's `enforce` list. `--disable-check` is repeatable and also accepts `stock_fit` and `setup_diagrams`; CLI disables win over the selected profile. When turning is disabled, its configuration is intentionally not read, even if a config path was supplied. Disabling a check adds no warning, checker status or certificate to the sheet.


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

A band passes when the operation tool's `diameter_mm` lies inside the inclusive band; a reversed band refuses. A tap drill passes when the operation tool's `diameter_mm` equals the named tap's `tap_drill_mm` within 1e-6 mm. Plan `[[tools]]` and shop `[tools.<ref>]` records take numeric `diameter_mm` and `tap_drill_mm` (never printed); shop values flow into the plan tool unless it sets its own. A missing diameter or tap drill, an unknown tap id or a missing `sizing` refuses. The base-bar adapter supplies each drawing limit as `<limit>_band_mm` (such as `bracket_dia_band_mm`, `counterbore_dia_band_mm`, `slot_width_band_mm`) and `slot_finish_diameter_mm` from the process parameter.

Only the selected tool is compared; no nearer tool is suggested. Thread designation, tap class, operation order, reaming allowance and actual cut size (runout, drill wander) are not checked.
## Profiles

| Preset | Setup diagrams | Operation instructions | Enforcement |
| --- | --- | --- | --- |
| `pro` (default) | Omitted; diagram files are not opened | Compact `instruction` | Stock fits; applicable longitudinal turning meets bending limits |
| `hobby` | Included for every setup | `instruction_detailed` when present, otherwise `instruction` | Stock fits; turning meets bending limits; every setup has a readable SVG diagram |

Enforcement is limited to the declared stock, setup-diagram and static longitudinal-turning contracts. It does not establish machining safety. The diagrams illustrate setups using CAD-derived part dimensions and authored fixture layouts; no FreeCAD is needed.

Use `--profile path/to/profile.toml` for a custom profile:

```toml
name = "illustrated"
features = ["setup_diagrams", "detailed_instructions"]
enforce = []  # Explicitly skip stock/turning checks; allow missing diagrams.
```

Add `"setup_diagrams"` to `enforce` to require one for every setup; it must also appear in `features`. Add `"stock_fit"` to require CAD and fitting blank dimensions independently of diagrams; add `"turning_deflection"` to enforce the declared longitudinal-turning screen. These are the supported enforcement keys. Feature keys are `setup_diagrams` and `detailed_instructions`: custom profiles must explicitly enable the latter to select detailed operation text, regardless of profile name or diagram selection. Unknown keys are errors.

## Shared tools and cutting settings

Plans can reference one shop file. The base-bar, shaft, bracket and T-nut examples use `examples/shop.toml`; mixed-tool operations and unspecified settings remain inline.

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

Pedro reviews each milestone. Work must not run more than three milestones ahead of his last review. v0.6 adds shared authored data; v0.7 adds shaft hobby pictures and the round-stock requirement; v0.8 adds declared-input checks.
