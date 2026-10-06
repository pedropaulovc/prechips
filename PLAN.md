# prechips — plan (rev 6)

> Checks before chips. prechips turns a part plus a short process plan into a
> **validated traveler a machinist can work from**: one page per setup saying
> how to hold it, where zero is, what the DRO should read for each feature,
> which tool, what speed and feed to start at, and what to measure. Every
> setup is validated for feasibility against the current shop inventory, the
> machines' operating ranges, the setup geometry, the workholding and the
> physics of the cut. What the checker found goes at the top of the sheet in
> plain words; everything else it computed goes to a machine-readable report
> no human has to read.

Status: M1 local implementation and PR #5 cross-family/CodeRabbit review
corrections completed; M2 declared-input implementation and all six PR #6
review corrections are locally verified. Physical paper rehearsal and live
parented farm/App Insights acceptance remain pending/unobserved. Rev 6, 2026-10-03.
Sections below retain design intent; README and docs describe the shipped
schema/CLI/rules. Rev 1 was traveler-first but promised geometric proofs
it could not deliver. Revs 2–3 absorbed two adversarial
reviews and became correct but unusable: a 100 KB traveler of config ids,
hashes and 15-decimal numbers. Rev 4 restored the purpose and the rule
catalogue. Rev 5 folded the third adversarial round. Rev 6 folds the fourth:
stock state per operation, the DRO recipe written against the EL400
manual, inspection per requirement, one `unknown` contract, the
error/warn/info vocabulary, and the telemetry requirements.

## 1. Who this is for

A hobby machinist (initially: one person, one shop) making 1–20 of a part on a
PM-30MV mill run by hand through a DRO (EL400 emulator over cncjs) and a manual
PM-1127VF-LB lathe. They already have the drawing. They need, per setup:

1. a picture of the part in the fixture,
2. a zero-setting recipe for the DRO, with a check move that proves the sign,
3. a coordinate list in the DRO's own frame and units,
4. an operation list with tool, holder, RPM, feed, depth, direction, coolant
   and the inspection that closes the feature,
5. a short "before you start" box listing what the checker could not confirm
   or found wrong.

Nothing on the sheet needs a computer to interpret. Drawing dimensions carry
the drawing's precision (0.01 mm or 0.001 in). Operative targets and computed
coordinates retain their own numeric precision, including when drawing
precision is absent; unrelated tolerance formatting must not change a cut target.

## 2. The traveler (the product)

Letter, portrait, printable; one header page plus one page per setup; HTML
with print CSS (PDF via the browser). Sketch for `rocker-arm`, setup S3 (mill,
finish the hub and profile on a prepared blank). **Layout sketch only: the
coordinates, revision and tool list below are placeholders, not the part's
geometry** (the real numbers live in `examples/rocker-arm/spec.yaml` and the
harmonic-analyzer build scripts; the rod hole is at ~146 mm, not 85). The
RPMs do follow from the cited 90 sfm (§2 rules).

```
ROCKER ARM  MHA-071  rev v21             qty 20    1018 CRS, black oxide
Traveler  2026-10-03                                        sheet 3 of 4

BEFORE YOU START
  ✗  No 6.50 mm reamer in the shop. Nearest: 0.2510 in (6.375 mm), 0.125 mm
     under the bore's low limit. Buy a 6.5 H7 reamer or re-dimension.
  ✗  No R8 drill chuck listed; ops 30 and 50 need one. Confirm or add.
  ?  Vise bed-to-table height not measured — spindle clearance not checked.
  ?  Travel limits not measured — part + vise assumed inside 23 × 8.75 in.

SETUP S3 — PM-30MV, PM 6 in vise, jaws along X, part on 3/4 in parallels
  Starts from: S2 blank, top face at 10.03 above the bottom (0.50 to face).
  Fixed jaw: rear (+Y).  Stop: against the left end of the fixed jaw.
  Hold: 10 mm of both rails in the jaws, 3 mm of jaw above the parallels;
        strap sits on the parallels. Tighten by hand plus a quarter turn.
  Clear: 7.0 mm from the jaw top to the blank top; 3/8 EM holder clears by 4.
  Coolant: WD-40 brushed on, drilling and reaming.  Deburr: 0.2 max, file.

  DRO ZERO  (frame A = bottom face / left end / front edge, mm, ABS,
             radius mode; X+ right, Y+ away from you, Z+ up. EL400 manual
             §6.2 Direction, §7.4 Axis Set — set before S1, same every sheet)
    X  touch left end with 0.200 in finder from −X     → ABS, Axis Set −2.54
       then, without touching again, jog +X 10.00: DRO must read +7.46.
       −12.54 means X counts backwards: stop, set Direction for X, redo.
    Y  touch front edge, finder from −Y                → ABS, Axis Set −2.54
       then jog +Y 10.00 without touching: DRO must read +7.46.
    Z  0.05 paper on the blank top, 1/2 in EM (op 10)  → ABS, Axis Set 10.08
       after op 10 the top is at 9.53: every later tool touches the FACED
       top with paper → Axis Set 9.58 before its op. Jog +Z 10.00 without
       touching after the first set: must read +20.08.

  COORDINATES (mm, frame A, cutter centre; Z is the tool tip)
    feature        X       Y      Z            note
    pivot bore    25.40   12.70   tip to −3.86  Ø6.50 +0.03/0; 6.2 drill point 1.86 + 2.0 exit
    rod hole      85.12   18.23   tip to −2.10  #47 (2.00 mm); point 0.60 + 1.5 exit
    hub OD        25.40   12.70   0 → 9.53      Ø14.00 ±0.1; cutter R 4.76 outside

  OPERATIONS
    op  do        feature     tool / holder          rpm  feed       Z (tip)          dir   check
    10  face      top         1/2 4-fl EM, R8 1/2    700  140 mm/min 10.03 → 9.53     conv  —
    20  spot      pivot bore  #2 CD, R8 1/4          2000 hand       9.53 → 7.5       —     —
    30  drill     pivot bore  6.2 mm, R8 chuck       1400 hand       → −3.86          —     —
    40  ream      pivot bore  6.5 H7, R8 1/4          450 hand       → −3.00 (lead 1) —     6.50 go / 6.53 no-go; position: see 50
    45  spot      rod hole    #2 CD, R8 1/4          2000 hand       9.53 → 7.5       —     —
    50  drill     rod hole    #47, R8 chuck          2000 hand       → −2.10          —     2.00 pin; position Ø0.20 to A|B: pin + height gauge from bore
    60  profile   hub OD      3/8 4-fl EM, R8 3/8     900  180 mm/min 9.53 → 0, 2 pass climb 14.00 ±0.1 caliper
       60: rough to Ø14.6 (centre at 25.40/12.70 ± 12.06), finish Ø14.0
       (± 11.76). Coordinates for every 10° of the arc are on sheet 3a.
    70  release   rails       —                      —    —          —                —     —
       70: loosen, lift the part onto the fixture plate before cutting the
       rails free (S4). Do not cut the rails in the vise.
  RPM/feed: HSS, 1018 CRS, 90 sfm; 0.05 mm/tooth — layout placeholders;
  the shipped cutting-data.toml rev 1 cites no page yet, so the real
  sheet prints `?` here until a row is transcribed. Starting points, not limits.

  Sign off: ________  first article: ________  pivot bore reads ______
                                            prechips 0.1 · report 7f3a9c2e
```

Rules for the sheet:

- **Plain words, drawing precision.** A finding is one or two sentences with
  the number that matters; no rule ids, no hashes, no file paths. The three
  glyphs are `✗` error, `!` warning, `?` could not check.
- **Everything the machinist would otherwise invent is on the page.** Fixed
  jaw side, stop, grip, clamp method, clearance under the holder, coolant,
  deburr limit, cut direction, what the setup starts from, the tip endpoint
  of every hole (point length or reamer lead + exit allowance), the Z the
  top is at after each op and the number to set after each tool touch,
  cutter-centre coordinates for a manual contour (the arc table on a
  continuation sheet), the step that releases a held feature. Each comes
  from a `plan.toml` field (§3.1) or a rule's computation; none is free text
  the generator makes up. A field the author left blank is a `?` line, not
  a blank cell.
- **The zero recipe proves its own sign, per axis, against the manual.**
  The DRO is described in the terms of the Electronica EL400 Operation
  Manual (linked in the README): `Direction Left/Right` per axis (§6.2),
  `Axis Set` in ABS (§7.4, "alters the datum"), radius/diameter (§6.2),
  `Preset` is distance-to-go and is never used for zero (§8.1). For every
  axis: touch, Axis Set the compensated value, then jog a stated distance
  **without touching again** and compare the reading; the sheet prints the
  expected reading and the mirrored one. The emulator is expected to match
  the manual; where it does not, that is an emulator bug, not a prechips
  input.
- **Speeds and feeds appear on the sheet**, computed from a shipped,
  versioned `cutting-data.toml` (§3.5), rounded to the nearest 50 rpm,
  then clamped to the machine's range, labelled as starting points. Source order:
  the tool vendor's chart when the inventory entry names one
  (`chart = "<url or doc>"`), otherwise Machinery's Handbook 31. The
  citation is one line per setup, not per cell.
- **Units: coordinates in the drawing's unit, tool sizes as bought.** The
  harmonic-analyzer drawings are mm; the DRO and the tooling are inch. Both
  appear only where they meet, on the sizing line ("0.2510 in (6.375 mm)").
- **Feature names, not balloon numbers.** The sheet says `pivot bore`, never
  "bore ③": balloon numbers are not stable across drawing revisions.
- **The DRO block is a recipe, not a file.** It says which edge, which
  finder, which direction, what to Axis Set. It uses only functions the
  manual documents (ABS/INC, radius/diameter, Axis Set, bolt-circle/linear
  patterns); prechips does not emit EL400 files until the emulator has an
  import path.
- **Footer**: `prechips <version> · report <8-char id>` so the sheet can be
  matched to its `report.json`. That is the only identifier on the page.

## 3. Inputs (what the author writes)

All inputs are **TOML**. Deeply nested YAML was the readability failure of
rev 3; TOML's `[[setups]]` / `[[setups.ops]]` tables keep each record flat and
self-labelled, and `tomllib` is in the standard library. The merged rev-3
fixtures under `examples/` are YAML and will be converted when M1 lands.
No text format carries decimal precision (TOML, YAML and JSON all read
`25.40` back as `25.4`), so a manifest states it: `precision = N` at file
level is the drawing's general class, and a feature with a tighter
dimension overrides it (`precision = { at = 3 }`), which is how the title block's
`linear_2pl` / `linear_3pl` classes attach to one dimension and not the
whole sheet.

### 3.1 `plan.toml` — short, per part

```toml
part = "rocker-arm"
drawing = { number = "MHA-071", revision = "v21" }
quantity = 20
features = "features.toml"                # the bundle the plan was written against

[stock]
form = "flat_bar"
material = "1018 CRS"
section_mm = [45, 16]
length_mm = 310

[dro]                                     # set once, in S1; printed on every sheet
controller = "el400"
manual = "Electronica EL400 Operation Manual"   # README links it; sections cited on the sheet
mode = "abs"
radius_mode = true
direction = { x = "right", y = "away", z = "up" }   # manual 6.2 Direction, as the sheet reads it

[[setups]]
id = "S3"
machine = "pm-30mv"
frame = "A"                               # named in features.toml
coolant = "wd40_brush"
deburr_mm = 0.2
stock_in = "S2"                           # what this setup starts from

[setups.stock_state]                      # surfaces as this setup receives them, frame A
top_z = 10.03                             # S2 leaves 0.50 to face
bottom_z = 0.0
local_thickness = { pivot_bore = 7.06, rod_hole = 2.5 }   # from features.toml faces; here hand-written

[setups.hold]
fixture = "vise-pm-6"
jaws_along = "x"
fixed_jaw = "rear"
parallels = "parallels-lms-6745/0.75in"
grip_mm = 10
jaw_above_parallels_mm = 3
stop = "left end against fixed jaw"
clamp = "hand plus quarter turn"

[setups.zero]
x = { edge = "left_end", from = "-x", tool = "edge-finder-0.200", check_jog_mm = 10.0 }
y = { edge = "front",    from = "-y", tool = "edge-finder-0.200", check_jog_mm = 10.0 }

[setups.zero.z]
face = "top"
method = "paper"
paper_mm = 0.05
tool = "em-1/2-4fl"
check_jog_mm = 10.0
retouch_after = [10]                      # ops that change the touched surface

[[setups.ops]]
op = 10
do = "face"
feature = "top"
tool = "em-1/2-4fl"
holder = "r8-1/2"
to_z = 9.53                               # the top after this op; stock_state advances
direction = "conventional"

[[setups.ops]]
op = 20
do = "spot"
feature = "pivot_bore"
tool = "cd-2"
holder = "r8-1/4"
depth_mm = 2.0

[[setups.ops]]
op = 30
do = "drill"
feature = "pivot_bore"
tool = "drill-6.2mm"
holder = "r8-chuck"
exit_mm = 2.0                             # full diameter this far past the exit face;
                                          # tip endpoint = exit face − point length − exit_mm

[[setups.ops]]
op = 40
do = "ream"
feature = "pivot_bore"
tool = "reamer-6.5-h7"
holder = "r8-1/4"
exit_mm = 2.0                             # tip endpoint = exit face − reamer lead − exit_mm
checks = { dia = "pin-gauge-6.50-6.53" }

[[setups.ops]]
op = 45
do = "spot"
feature = "rod_hole"
tool = "cd-2"
holder = "r8-1/4"
depth_mm = 2.0

[[setups.ops]]
op = 50
do = "drill"
feature = "rod_hole"
tool = "drill-47"
holder = "r8-chuck"
exit_mm = 1.5
checks = { dia = "pin-2.00", position = "pin-and-height-gauge-from-bore" }

[[setups.ops]]
op = 60
do = "profile"
feature = "hub_od"
tool = "em-3/8-4fl"
holder = "r8-3/8"
to_z = 0.0
direction = "climb"
rough_allowance_mm = 0.3
contour = { method = "arc_table", step_deg = 10 }
checks = { dia = "caliper" }

[[setups.ops]]
op = 70
do = "release"
feature = "rails"
note = "lift onto the fixture plate before S4 cuts the rails free"
```

The author writes the route and every holding/cutting decision above.
prechips fills in RPM/feed, tip endpoints (from the stock state, the tool's
point angle or reamer lead, and `exit_mm`), the Z of the top after each op
and the per-tool touch value, cutter-centre coordinates and the arc table,
holder clearance, and resolves tool, holder and fixture ids against the
shop. `checks` is keyed by requirement (`dia`, `position`, `finish`,
`depth`), one gauge per requirement, so a feature with two tolerances needs
two entries. Tool ids are short and human (`em-3/8-4fl`), set by the
inventory. A later setup declares how it re-finds zero
(`[setups.zero] transfer = { from = "S1", indicate = "pivot_bore" }`).

### 3.2 `features.toml` — the drawing, in numbers (generated by the CAD side)

Exported beside the STEP by the consumer (harmonic-analyzer: from
`rocker_arm_spec.py`, `_hole_spec.py`, `rocker_arm_notes.py`,
`draw_rocker_arm.py`'s datum scheme and `title_block.yaml`'s general
tolerances). prechips never reads PMI from the STEP and never invents a
tolerance. It is a **complete requirement manifest** under one `unknown`
contract:

- A requirement the drawing carries whose value the generator cannot source
  is the string `"unknown"` in that field (`dia = "unknown"`,
  `position_dia = "unknown"`). It is still a requirement: it enumerates a
  subject for every rule that reads that field, and each such rule returns
  `unknown` for it. The sheet prints a `?` line naming the feature and the
  field.
- A requirement the drawing does **not** carry is absent. Absence is known
  absence, and the generator asserts it: `requirements = ["dia", "thru"]`
  per feature lists exactly which fields are requirements, so a missing
  field that is not in the list is a generator error, not an unknown.
- An omitted *feature* is impossible to detect from the manifest alone,
  which is why the generator, not a hand, writes it (M3). The historical M1
  hand-written manifests were cross-checked against drawing dimension counts;
  the pivot-bracket remains hand-authored on the v39 STEP without a dimensioned
  drawing, so its example bands are illustrative rather than sourced limits.

**Historical design sketch, not the current manifest.** The excerpt below
predates M3: placeholder face names, inch-derived bands and material/profile
assumptions are not current exported facts. The verbatim source-backed manifest
is `examples/rocker-arm/features.toml`; that file is the operative input.

```toml
part = "rocker-arm"
units = "mm"
precision = 2                              # .XX general class; a feature may override
step_sha256 = "…"                          # the STEP this manifest was exported with
construction = "one_piece"                 # or "built_up_permitted" (drawing note)

[frames.model]
note = "SolidWorks part origin: pivot axis, mid-thickness"

[frames.A]                                 # numeric, in model coordinates
origin = [0.0, 8.0, 3.52825]
x = [1, 0, 0]
y = [0, 1, 0]
z = [0, 0, 1]
note = "bottom face / left end / front edge (draw_rocker_arm.py datums A=bore, B=broad face, C=tip)"

[material]
spec = "1018 CRS"
thickness = 16.0

[general_tolerances]                       # title_block.yaml value_in x 25.4
linear_2pl = 0.508
linear_3pl = 0.127
angular_deg = 1.0

[features.pivot_bore]
kind = "hole"
at = [0.0, 8.0]                            # model frame; the plan's frame A is derived
dia = [6.50, 6.53]
thru = true
faces = ["Face1", "Face16"]                # STEP face SET; a bore is two patches
datum = "A"

[features.rod_hole]
kind = "hole"
at = [133.06740213488345, 16.456064115939025] # on the R816 arc; BASIC from the pivot
drill = "#47"
dia = [1.994, 2.094]                       # #47 + drilled-hole general band +0.10/0
thru = true
position_dia = 0.20
precision = { dia = 2, position_dia = 2 }  # per dimension; `at` is BASIC, never gets a ± default
requirements = ["at", "dia", "thru", "position_dia"]
position_datums = ["A", "B", "C"]          # C clocks rotation about the pivot axis
faces = "unknown"                          # historical: before the M3 face-set export

[features.hub_od]
kind = "boss"
at = [0.0, 8.0]
dia = [9.692, 10.708]                      # HUB DIA 10.20 under the .XX general band
coaxiality_dia = 0.50
coaxial_to = "pivot_bore"
requirements = ["dia", "coaxiality_dia"]

[features.top]
kind = "face"
faces = ["Face15"]
finish_ra = 1.6

[features.profile_outer]
kind = "profile"
requirements = []                          # drawing carries no profile tolerance: known absence
faces = ["Face2", "Face3", "Face6"]
```

**Historical source assessment:** the original sketch combined rocker spec
geometry, hole defaults, notes, datum annotations and title-block tolerances.
The current export supplies the actual A|B|C position datum chain, rendered
metric general bands, material alternatives and all labelled face sets,
including separate strap datum B and both tip lands. Unknown tip-land angular
acceptance and setup binding remain unknown; no drawing note authorizes
built-up construction. The generated manifest and its per-fact citations,
not this sketch's field names or face ordinals, are authoritative.

**Why not PMI in the STEP.** Semantic PMI needs AP242, and in SolidWorks that
export is the MBD add-in only (`IModelDocExtension.PublishSTEP242File2`,
`swPublishStep242_MBDLicenseNotAvailable`); the 2026 help says MBD "is not
part of any role" and needs a stand-alone licence, and the R2026x Makers
seat has no MBD add-in registered. Even licensed, AP242 carries DimXpert
annotations, and harmonic-analyzer deliberately authors plain gtols
(`_part_pmi.py`) with every size on the 2D drawing, so the export would hold
a few GD&T frames and no dimensions. The spec scripts are the authority; a
generated `features.toml` is the lossless route.

**What the STEP carries instead: face ids, as sets.** The consumer exports
labelled AP214 faces without requiring semantic PMI. A feature is a face
*set*, not one face: even the historical v38 rocker spike held the pivot bore
as two cylindrical patches. M3 now supplies generated feature-to-face sets
bound to each adjacent STEP digest; prechips checks references before matching
imported geometry, never assuming imported face order. Delivery evidence is
recorded in `examples/README.md`; integration status is in §8 M3.

### 3.3 `inventory.toml` — the shop (user-supplied; sample in `examples/inventory/`)

Machines with ranges and (when measured) envelopes; holders with gauge
length and grip; tools by short id with diameter, flutes, flute length, OAL, shank,
material, point angle for drills, an optional `chart` and, once measured, a
projection per holder; gauges; fixtures
with the dimensions the rules read (vise: jaw width, opening, bed height
above the table, jaw height above the bed; parallels: heights; collet set: sizes; chuck: range; dividing
head: `worm_ratio`, `direct_index.positions`, `plate_holes` per plate —
the sample's BS-0 carries all three, circles `verify = true`). A value copied from a vendor page is
`verify = true` and anything that depends on it is a `?` on the sheet, never
a silent pass. The sample inventory carries the PM 6 in vise with
shop-measured `jaw_height_in`, `jaw_width_in`, `jaw_depth_in`, `opening_in`
and `bed_height_in` (2026-10-05; item-level `verify = true` kept as identity
debt) and the PM-30MV envelope (`envelope.travel_in`,
`envelope.spindle_to_table_max_in`), still `verify = true`.

M5's shipped inventory shape makes `machines.<id>.envelope` the only home for
the mill limits any rule reads: X/Y/Z travel and spindle-nose-to-table max/min.
There is no top-level `spindle_to_table_max_in`/`travel_in`/`table_in` copy,
and no table size, T-slot pitch, spindle taper or spindle-stack entries,
because no rule consumes them. A length is one fact,
`{ value, measured = { by, date, instrument }, verify }`, and only that fact's
own record qualifies it: no block, item-root or source `measured`/`verify`
inheritance, no coverage heuristics. Holders carry mounted gauge
(`gauge_len_mm`/`_in`, one spelling) and grip; a tool's projection is a map
keyed by the full holder reference it was measured in
(`tools.<tool>.projection_mm.<holder>`), never a holder-wide or tool-wide
scalar, with measured OAL − selected holder grip as the only fallback. Missing
values stay `"unknown"`; vendor copies remain `verify = true`. See
[inventory schema](docs/inventory.md).

### 3.4 `shop-policy.toml` — what must be confirmed (user-supplied, optional)

Which `(rule, subject)` pairs must come back clean before a sheet is
**checked**, plus the shop's own numbers that rules read:

```toml
[required]                      # rule = subjects; "*" = every feature/setup/op
tool_resolves = "*"
sizing = "toleranced_features"
op_chain = "holes"
blind_depth = "holes"
inspection = "toleranced_features"
coordinates = "*"
zero_check = "setups"

[numbers]
refixture_budget_mm = 0.05      # what a re-indicated pickup repeats to; measured, else verify
thin_wall_floor_mm = 2.0        # below this under a jaw, name a method
stickout_ld_max = 3.0           # collet/chuck without support (cite)
```

Subjects are enumerated from `features.toml` (`requirements` lists) and
`plan.toml`, not from what the plan happens to mention: a required rule with
no subject in a non-empty manifest is `unknown`, and a plan with no setups
or no ops, or a manifest with no features, is rejected before any rule runs.
A required rule whose result is `warn` keeps the sheet `PLANNED` and exits
4, the same as a required `unknown`: "required" means the shop wants a
clean answer, and a warning is not one. `unsupported` (prechips has no rule
for this feature kind yet) and `not_applicable` (the rule has nothing to
say about this subject) are distinct statuses; only `not_applicable` is a
pass. Lives with the inventory, not in the plan, so a plan cannot waive it.
The shipped default requires the first seven rules on `*`.
M5 additionally supports shop-required `envelope = "*"` / `travel = "*"`;
it does not change the default required set, and there is no `holder_stack`
rule to require.

### 3.5 `cutting-data.toml` — shipped with prechips, versioned

The only numeric table prechips ships. Two tables. `[[cut]]` keyed
`(material_class, tool_material, operation, diameter_range)` →
`sfm`, `chip_load_mm_per_tooth`, `cite`. `[[material]]` keyed
`material_class` → `kc_n_per_mm2` (specific cutting force at 1 mm chip),
`e_gpa`, `cite` — the only source the §4.4 proxies may read. `material_class` maps from the
inventory/plan material string through a small alias table (`"1018 CRS"` →
`low_carbon_steel`). RPM = 12·sfm / (π·D_in), rounded to the nearest 50,
then clamped to the machine's range (so a 70 rpm floor never prints 50);
feed = rpm·flutes·chip_load. An inventory tool with `chart = …`
overrides the row with its own `sfm`/`chip_load`, citing the chart. A
missing row is a `?` line, never a guessed number. Content grows with the
routes that ship: rev 1 carries only the rows M1's rocker setup selects
(HSS × low-carbon steel × face/profile/drill/ream), each transcribed and
page-cited from Machinery's Handbook 31 Table 1 or left `"unknown"`; a row
is added when a shipped route first needs it.

## 4. What the checker validates (the rule catalogue)

Every rule is deterministic: same inputs, same verdict. Each produces one
status per `(rule, subject)`: `pass`, `error`, `warn`, `info`, `unknown`
(an input missing or `verify = true`), `unsupported` or `not_applicable`.
The sheet shows `error` (`✗`), `warn` (`!`) and `unknown` (`?`) as
sentences; `info` goes to the report and the log only. Exit precedence:
3 (bad input, nothing written) > 2 (any `error`) > 4 (a required `unknown`,
`unsupported` or `warn`) > 0 — so the consumer can wrap it as a doit gate.
Every numeric threshold carries a `cite`; an uncited number is a lint error
in this repo.

Unexpected implementation failures are outside this readiness precedence: they
propagate a traceback and exit 1, never masquerading as bad input. Generated
outputs are staged before replacement and prior files are restored on ordinary
write/replacement failure; crash/concurrent-writer atomicity is not promised.
Malformed optional OTLP protocol/timeout settings warn once and disable export,
leaving the checker's report and exit unchanged.

Each row names **where its inputs come from** (`plan`, `features`,
`inventory`, `policy`, `cutting-data`, `kernel`) and its tier: **M1** ships
in the first slice, **M4** needs the kernel, **deferred** is kept as intent
with no code until a pilot needs it. A row whose inputs are not in §3 does
not exist.

### 4.1 Plan lint (declared inputs only)

| rule | inputs | tier | on the sheet it reads like |
|---|---|---|---|
| tool resolves; holder's taper = machine spindle; shank fits holder | plan.ops.tool, inventory.tools/holders/machines | M1 | "No R8 drill chuck listed." |
| sizing: selected finishing tool's size within the feature's limits; unit mismatch reported, never converted | plan.ops.tool, features.dia, inventory.tools.dia | M1 | "Nearest reamer 6.375 mm, 0.125 under the low limit." |
| op chain per feature kind: hole = spot→drill→(ream\|tap); counterbore after its hole; tap drill from thread spec | plan.ops, features.kind/thread | M1 | "Pivot bore is reamed without a drill op." |
| order: rough→finish, drill→ream/tap, face→spot, release last | plan.ops | M1 | "Op 40 reams before op 30 drills." |
| tip endpoints from stock state: the setup's `stock_state` advances per op (`to_z`); a through hole's tip endpoint = exit face − point length (`point_angle`, D) − `exit_mm`, reamer: − `lead_mm` − `exit_mm`; blind: depth + point ≤ `features.depth`; tap flute ≥ thread depth; exit face from `local_thickness[feature]`, never the stock section | plan.setups.stock_state, plan.ops.exit_mm/depth_mm/to_z, features.thru/depth, inventory.tools.point_angle/lead_mm/flute_len | M1 | fills the Z column; "6.2 drill to −2.0 leaves 0.14 of cone in the bore; go to −3.86." |
| speeds/feeds from cutting-data, rounded, then clamped | plan.ops, inventory.tools (material, flutes, chart), machine rpm range, cutting-data | M1 | fills the columns; "? no row for O1 hardened" |
| zero recipe: for each axis, contact reading = (edge coordinate in frame A) + side·(finder radius), side = −1 when the finder approaches from the negative side of the edge, +1 from the positive side; paper: edge + paper; the Axis Set value is that reading; the check reading = Axis Set value + sign·`check_jog_mm` where sign = +1 if `dro.direction` agrees with the frame axis, else −1; the mirrored reading = Axis Set value − sign·jog; the retouch value after each `retouch_after` op from the advanced stock state | plan.dro, plan.setups.zero (edge, approach side), plan.setups.stock_state, features.frames, inventory.tools (finder dia) | M1 | fills the DRO block; "Y direction is set 'toward' but frame A's Y points away: the sheet would mirror every Y." |
| coordinates: feature centre → setup frame → cutter centre (tool radius for profiles; rough and finish offsets both; the arc table for `contour.method = "arc_table"`) | features.at/frames, plan.setups.frame, plan.ops.contour, inventory.tools.dia | M1 | silent when right; prints sheet 3a |
| inspection per requirement: every entry in a feature's `requirements` that is a tolerance (any `*_dia`, `dia`, `finish_ra`, `depth`, `coaxiality_dia` — every requirement that carries a band, not a fixed list) has a `checks.<requirement>` on the op that finishes it, and the named gauge exists and spans the band | features.requirements, plan.ops.checks, inventory.gauges | M1 | "Rod hole position Ø0.20 has no check; the 2.00 pin proves size only." |
| hold fields complete: fixed jaw, stop, grip, clamp, coolant, deburr, direction per cutting op, holder per op, stock state per setup | plan.setups.hold/coolant/deburr_mm/stock_state, plan.ops.direction/holder | M1 | "S3 does not say which jaw is fixed." |
| headroom: bed-to-table height + parallels + stock height (`top_z − bottom_z` of the supported stock, never a coordinate) + tool projection + holder gauge length + 25 mm insertion ≤ spindle-to-table at full quill retract; jaw height is a separate obstruction check against the tool path, not a layer in the stack; part + fixture ≤ travel | inventory (vise bed height and jaw height, parallels, tool OAL/projection, holder gauge length, `machine.envelope` max and X/Y travel — unmeasured → `?`), plan.stock_state, plan.stock section | M1 | "Vise bed height not measured." |
| envelope: per-op spindle-nose stack `bed height + parallels/supports + physical stock height + holder gauge + tool projection`, raised by the op's highest commanded Z above the stock top (authored approach) against measured spindle-to-table max, lowered to its deepest floor against measured min; optional successful already-present STEP bbox, otherwise authored stock/state extents | plan.stock/stock_state/setup frame, plan.ops approach/targets/depth, inventory fixture bed height + parallels/supports, measured holder gauge and tool/holder projection (or OAL − grip), machine.envelope max/min | M5 | "? measure: PM-30MV spindle nose to table at full Z-down, steel rule, mm"; measured over-tall stack or unreachable floor is a stop |
| travel: union of operation feature extents/centres (hole centres unpadded; cutter radius only on outside-profile extents), commanded tip targets and explicit safe approach fits measured X/Y travel; Z unions per-op spindle-nose positions `tip + gauge + projection` against measured Z travel | features bounds/at/frame, plan stock/op target/depth/exit/approach_mm, inventory selected tool radius, holder gauge, tool projection and machine.envelope travel | M5 | "? measure: PM-30MV usable X travel between safe stops, steel rule, mm"; measured overtravel is a stop |
| datum consistency: a feature toleranced to a datum cut in another setup needs tolerance ≥ `refixture_budget_mm` or a `transfer` indicating that datum | features.position_datums, plan.setups (which op cuts which feature), policy.numbers | M1 | "Rod hole is Ø0.20 to A but S2 re-chucks without indicating the bore; budget 0.05." |
| turned profile monotone from the chuck unless a grooving op | plan.ops (lathe), features (diameters along Z) | M2 | "Ø8 groove at Z−30 needs a grooving tool." |
| stick-out: declared stick-out ≤ `stickout_ld_max`·D unless tailstock/steady listed; D is the smallest finished diameter in the unsupported length, from feature diameters along setup Z, not the bar held in the jaws. Unknown exposed profile remains unresolved | plan.setups.hold.stickout_mm, features (diameters along Z), policy.numbers, inventory | M2 | "Ø6 × 40 past the chuck: add the tailstock centre." |

### 4.2 Setup geometry (on the B-rep — needs the kernel)

| rule | inputs | tier | on the sheet |
|---|---|---|---|
| accessibility: sample each claimed face with the prescribed cutter/holder pose below. Obstacles are stock minus a 0.001 mm inward shell of this sampled face (an own matched point cap uses unmodified stock instead), plus fixture solids: holders see setup-entry stock; a milling or hole flute sees the stock left by the setup's earlier derived cuts (never a later cut's) and excludes this op's derivable outside-finished allowance or own hole cutter volume (spot/drill: point cone and body). After an underivable earlier cut, a flute keeps only certain finished-material hits and its tool hits are unknown. Other finished faces and holder obstacles remain. A hit means this prescribed pose is occluded, not that no pose cuts the point. Missing pose/stock/inputs prevent passes, but observed certain hits remain errors; far-side claims error by name, and invalid clearing removals are named stock debt | STEP faces, stock/setup order/op face claims, five cutter/holder dimensions (not OAL), spot/drill `point_angle`, rough `rough_allowance_mm`, fixture dimensions and pose, authored op depth/entry/through extent | M4 | "Ø10 cutter intersects the opposite wall of a 6 mm groove." |
| reach: floor depth below the face the tool enters ≤ flute length, else ≤ OAL with the holder cylinder clear of walls | features.faces, inventory.tools (flute_len, OAL, holder dia) | M4 | "Pocket floor is 28 mm down; 3/8 EM has 19 mm of flute." |
| internal corner radius: concave edges ⟂ tool axis between faces one op claims: r ≥ r_tool | features.faces, plan.ops.tool | M4 | "Slot corners are sharp; a 1/4 EM leaves R3.2." |
| coverage: ⋃ direction-valid faces claimed by ops ∪ faces declared as-stock = all faces; optional op `faces` explicitly overrides the feature default | features.faces, plan.ops.faces, plan.stock.as_is_faces | M4 | "Face 23 (the ear's back) is machined by no valid op." |
| finish coverage: every `finish_ra` face is claimed by a direction-valid finishing cut (nonrough/nonmanual; drill → ream/bore/tap precedence); a claimed hole cap counts only once its complete-form cut's setup leaves it clear of stock | features.finish_ra/faces, plan.ops.faces | M4 | "Ra 1.6 on the bore; no finishing op touches it." |

**Accessibility pose decision — user, 2026-10-05.** Ordinary wall samples
keep the cutter-radius offset along the horizontal outward normal. A floor
sample on or within one cutter radius of any concave floor/rising-wall edge,
straight or curved (pocket walls and boss feet alike), moves its axis along
the wall's in-plane normal at the nearest edge point until the cutter is
tangent; every such edge bounds the axis at once, so a two-wall concave floor
corner and samples near it stand tangent to both walls. A concave circle at
least the cutter's radius bounds it exactly; the smallest move is one of
finitely many analytic candidates, never a search, and a concave edge the
shifted axis comes within a radius of, or crosses as its nearest edge, joins
the bounds once (a finite constraint closure). A cutter wider than its
gap or circle keeps the sample's own axis and reports the real hit. Convex
edges and farther interior samples are unchanged. Past an edge's end, only the
wall/wall edge rising there classifies the corner: a concave one bounds by the
wall's line; a sharp convex island corner bounds only a sample past the end of
every wall meeting there, which moves straight away from the corner (its
nearest boundary point) until tangent; a sample in front of or behind a wall's
interior is bounded by that wall alone, and convex vertices get no corner
pose. This is per sample for floors that keep their samples.
**Whole-face floor pose (literal face-inside-cutter):** a
+Z planar floor whose entire face fits inside the actual cutter disc gets
exactly one pose and no samples or corners: the area centroid of the convex
set of covering axes (exact for line and Z-circle outer edges, emptiness
proved over finitely many analytic candidates, no `STOCK_TOL` widening), the
certified minimal enclosing centre when that set is one point, or a concave
rising Z-circle wall's centre that meets every such wall's own tangent-circle
floor bound and covers the face. A rough leave or any other rising wall keeps
the samples, as does a face larger than the cutter: reverse containment (the
Rocker OD10.2 annulus against D9.525) is not this rule. Other outer curves
are decided only by an exact-point no-fit; otherwise, like a failed native
locus, the floor's own poses drop and the op's measured facts are unknown
while other faces' certain hits stay.
Tangency is not corner-radius certification. Floor-only claims do not certify
a wall/wall corner: `internal_corner_radius` retains its existing scope and
checks a sharp wall/wall corner when the op claims both walls. No adjacent
finished wall is removed to manufacture clearance; undercut and leaning walls
remain obstacles.

The cutter tip is at sampled face Z except that a rough milling op's scalar
`rough_allowance_mm` (a) is an engine-consumed leave in millimetres normal to
the finished surface: each rough sample point moves `a` along the face's unit
normal, then takes the ordinary cutter-radius XY shift `r`; concave floor-edge
and corner constraints use radius `r + a`. Derived stock protects the finished
solid offset outward by `a`, keeping radial and axial leave on drafted faces
too, and later finishing ops remove it as their own allowance. An explicit
`to_z` caps that endpoint (the tip is the higher of `to_z` and floor plus
leave), so a `to_z` already at the rough floor plus a 0.2 mm leave is not
raised by a second leave. A finishing op's numeric `to_z` above its face is
likewise its actual tip (a 0.1 mm spring pass samples there, matching its
own cut). An unknown leave is accessibility and later-stock
debt. If the arc-join outward offset fails, a valid intersection-join offset
that contains the finished solid with the same solid count may be used
instead (conservative, extra leave at convex corners), never the nominal
solid; if both fail, the result is named offset debt.
Drill, spot, ream, bore, tap and counterbore flute stock obstacles exclude only
that op's own actual cutter volume to declared depth or explicit through
extent. Hole centres and axes derive from geometry-matched concave cylindrical
faces aligned to setup Z. Missing depth or entry facts and explicitly unknown
through facts remain debt; absent `thru` retains the existing blind-hole
default.
Spot and drill cut with their actual point: a cone with its apex at the tip,
widening at tan(point_angle/2), then a full-radius body. The tool's numeric
included `point_angle` is mandatory; an unknown one is named debt that makes
accessibility `unknown` and leaves later stock unresolved, never a flat
cylinder or a default angle. The flute check uses that cone and body against
part and all modeled fixture solids; holders retain full setup-entry stock. Spot
`depth_mm` is the apex tip depth; drill `depth_mm` is the full-diameter depth
and its tip is a point length `r / tan(point_angle/2)` deeper; an op `to_z`
is the absolute actual tip. A through drill exits each matched bore's actual
axial bottom plus its point; other through actions end at that bore bottom,
not the raw-stock bounding-box bottom. Ream, bore, tap and counterbore remain
flat-bottomed operation-diameter cylinders. A hole op wider than its matched
bore removes its own bore wall to the op radius with no fixed radial cap; the
sizing rule owns the drill or reamer diameter. A spot never widens its bore.
Spot and tap honor explicit operation depth even on a `thru = true` feature.
An own hole bore radius is diameter-sizing, not `internal_corner_radius`.
Claimed point caps are not blanket-exempt. Only a hole op's own known matched
cap, a concave cone or sphere lying wholly below and sharing a real edge with
its claimed concave Z-parallel bore, coaxial and no wider than it, is sampled
against unmodified stock instead of an own-face offset shell that
cannot be built at a cone apex, and is not an internal corner. Its actual
collision is still checked (wrong angle, deeper point or flat tool hits);
wider countersinks and tilted or unrelated caps keep their unknowns and hits,
and no other op borrows the exemption.
Exactly one op per feature is `complete_form`: its last drill, ream, bore or
counterbore in setup then op order (a thread's last drill; never a pilot,
spot or tap). After all of that setup's cuts, its own matched claimed caps
must be clear of the cumulative stock, using the same interior-contact test as
walls and no `to_z` clip, leave or tolerance. A touched cap is named in the
op's `cap_completion`, is output-stock debt rather than a collision, and is
uncredited by `finish_coverage` even when no setup consumes the output. An
unmeasurable completion leaves that credit unknown.
`stock_state.top_z` and `entry_z` are machine-frame millimetres; `depth_mm`
is millimetres even for inch-unit features, and tap fallback feature-depth
bands are converted to millimetres.
Unrelated finished material and holder obstacles are not cleared. Holding,
rendering, reach and holder obstacles still use actual setup-entry stock; a
flute meets only material the setup's earlier derived cuts leave, and no op is
credited with a later op's removal.

The −setup-Z approach model applies to milling and spindle-axis lathe actions
(`spot`, `drill`, `ream`, `tap`, `center`, `center_drill`). Other cutting
actions on a resolved lathe use a radial sampled turning screen: revolved
insert/head/shank/toolpost sections are checked against entry stock minus the
op's own removal and modeled fixture obstacles, including rotating chuck-jaw
envelopes. Turning-model facts, not raw axial direction arrays, establish
turning coverage. Invalid STEP references still error first; missing/unmapped
references and unresolved inputs remain unknown. Explicit turning actions off
a resolved lathe remain unsupported; shared profile/form/groove actions follow
resolved machine kind. Grooving/part-off blades are two-cornered sections of
measured `blade_width`, posed on the profile after the op. This
necessary-condition screen proves no toolpath, internal boring, chip flow,
chatter or rest-jaw clearance. See
[geometry rules](docs/rules-geometry.md#approach-models) for the exact boundary.


### 4.3 Workholding (geometry + inventory — needs the kernel for the solids)

| rule | inputs | tier | on the sheet |
|---|---|---|---|
| vise: gripped faces are a parallel pair; width ≤ opening; grip ≥ `grip_mm` on both jaws; no claimed face inside a jaw solid; parallels exist | plan.hold, inventory.fixtures.vise (jaw_height, opening, width), parallels, STEP | M4 | "Strap is 2.5 mm under the jaw with a 4 mm floor; use the fixture plate." |
| collet/chuck: stock Ø in the set or range; stick-out (4.1) | plan.hold, inventory | M2 | "No ER collet set confirmed." |
| thin wall under clamp: wall thickness inside the grip zone < `thin_wall_floor_mm` ⇒ `hold.method` must name soft jaws / mandrel / tape / wax | STEP thickness map, plan.hold, policy.numbers | M4 | "1.2 mm wall under the jaw; name soft jaws or a mandrel." |
| fixture interference: drawn fixture components (jaws, parallels, riser blocks, chuck, head, centre, angle plate / custom solids with `void` bores, clamp straps with studs and heels) never interpenetrate the setup-entry stock or each other beyond contact; vise parallels and riser blocks fit inside the jaw opening closed on the stock | plan.hold (pose, clamps, parallels, riser), inventory fixture `solids`, STEP | M4 | "Riser blocks span 50.8 mm across a 45 mm jaw opening; use narrower blocks." |
| indexing: for `hold.index = { fixture, angle_deg, positions }` and the feature's `angle_tol_deg` (default: the general angular class): prefer an **exact** representation (direct plate step, or a circle `h` with `angle_deg·R·h/360` an integer, R = `worm_ratio`); otherwise the nearest, and check every position against `angle_tol_deg`. Closure is checked **only for a full pattern**, `positions ≥ 2` with `angle_deg` omitted (step exactly 360/positions; positions × actual step vs 360·k). An authored `angle_deg` with `positions ≥ 2` is an open pattern: every landing is checked, no closure. `positions = 1` is one angular setting without closure; the sheet prints plate, circle, turns and hole *spaces* | plan.hold.index, features.angle_tol_deg / general_tolerances.angular_deg, inventory dividing_head (`worm_ratio`, `direct_index`, `plate_holes`) | M2 | "51.43° × 7: plate B, circle 21, 5 turns + 15 spaces (exact); plate circles not confirmed (?)" |
| tiny parts: part-off last below the collet minimum; profile below footprint threshold declares tabs or a plate | plan.ops, inventory, policy | deferred | — |

### 4.4 Physics proxies (`!` lines only; policy may promote)

| rule | inputs | tier | on the sheet |
|---|---|---|---|
| turning deflection: δ = F·L³/(3EI) (cantilever) or /(48EI) (supported), F = K_c·a_p·f, K_c and E from `cutting-data.[[material]]` | plan.hold.stickout_mm, plan.ops (DOC, feed), features.dia, cutting-data.material | M2 | "Expected deflection 0.04 against ±0.1; take the last pass at 0.2." |
| engagement: only milling cutters (endmill families) on cutting operations with an authored DOC; tool projection from the holder (the tool's `projection_mm` entry for the selected holder, else OAL − holder grip) / D ≤ 4 else halve DOC. Drills, reamers, taps and lathe tools are not applicable | inventory.tools (kind, OAL, projection map), inventory.holders (grip_mm), plan.ops (holder, DOC) | M2 | "3/8 EM at 4.5×D; halve the DOC or use the 1/2 holder." |
| tool life | needs a calibrated life table nobody ships | deferred | — |

### 4.5 Stock-form comparison (authored candidates, counted by prechips)

The author lists candidate stock forms as alternative plans; prechips emits
setups, waste ratio, fixtures required and the rules each candidate trips,
side by side. It does not pick a winner, and a built-up candidate is marked
`✗ drawing permits one-piece only` unless `features.construction =
"built_up_permitted"`. First case: `cone-pivot-post`. Tier: M2.

### 4.6 Non-deterministic residue, named

Chatter, clamp deformation, whip, tiny-part gripping, cutter wear. No rule
in this project claims to decide these, and the reason is not effort: each
depends on a quantity the inputs do not declare or measure. Geometric
interference and reach are not on this list; they are §4.2–4.3.

| residue | what decides it | why prechips cannot compute it |
|---|---|---|
| chatter | the tool–holder–spindle–part–fixture stiffness and damping at the cutting frequency | a modal property of the assembled stack; needs a tap test or a cut on *this* machine, not a catalogue number — a stability lobe diagram is per spindle, per holder, per overhang |
| clamp deformation | vise torque, jaw and part contact geometry, part wall stiffness | the torque is uncalibrated ("hand plus a quarter turn"); the contact is a frictional, nonlinear problem the thin-wall proxy only screens |
| whip (turning) | stick-out, speed, stock straightness, bar residual stress | the deflection proxy gives static sag; whip is dynamic and depends on how straight the bar was when bought |
| tiny-part gripping | surface condition, burr, oil, operator's hand | not a geometric property |
| cutter wear | cumulative cut length, coating, coolant, workpiece batch hardness | needs a life model calibrated on this shop's tools and steel; no vendor table ships one for HSS hobby tooling |

The proxies (§4.4) and the fixturing rules (§4.3) screen the cases that
are decidable from geometry; the first-article cut and the logbook entry
are the evidence for the rest. If a residue turns out to be a repeat
offender on one part, the fix is a shop-policy number measured on that
part (`numbers.max_stickout_mm_for_6mm = …`, cited to the logbook entry),
not a general model.

## 5. Outputs, binding and readiness

- `traveler.html` — §2. The product.
- `report.json` — every `(rule, subject)` with status, numbers and citation;
  sorted, canonical, hashed (hash excludes itself); carries the SHA-256 of
  each input file (`plan`, `features`, `inventory`, `shop-policy`,
  `cutting-data`) and the STEP digest the manifest names. For doit stamps
  and for the informed machinist review, never for humans at the bench.
- `setup-S<n>.png` — the fixture render, once M4 exists; until then the
  "Hold" text is the whole description. (A hand-drawn sketch referenced
  from the plan was dropped: it would be operative content outside the
  hashed bundle.)

The hashed bundle is every file the run read: the five inputs, the STEP
named by the manifest, and any asset a plan field references. A path in
the plan that is not in the bundle is a bad input (exit 3).

**Readiness has two halves and both bind to the report hash.** A sheet is
*checked* when every required `(rule, subject)` is `pass` or
`not_applicable`. It drops the `PLANNED` banner only when a first-article
line in the logbook names the report hash it was cut from. **Approval and
first-article evidence bind to the report's full input-bundle digest; any
operative change resets readiness.** `prechips traveler` refuses to print a
`CHECKED` sheet whose report hash differs from the approval record it is
given (`--approval approvals.toml`), and prints `PLANNED` with a `!` line
naming which input changed. The paper copy carries only the short id; the
binding is enforced where the files are.

### 5.1 CLI shape

One executable, five verbs. Every verb reads the same inputs, resolves
them the same way, and prints the same finding sentences; the verbs differ
in what they write. No verb, or an unknown one, prints usage and exits 3
without writing anything.

```
prechips traveler <plan.toml> [--inventory <toml>] [--policy <toml>]
                  [--approval <toml>] [--out <dir>]
    Writes traveler.html, report.json (and setup-S<n>.png once M4
    exists) under --out (default: beside the plan). Prints the "before
    you start" lines to stderr. Exit 3 bad input (unparsable TOML, unknown
    key, plan feature not in the manifest, empty plan, an output path that
    is also an input, --out escaping its directory) > 2 any error >
    4 required unknown / unsupported / warn > 0 checked.

prechips check <plan.toml> [...]
    Same as traveler without writing the sheet; the doit-gate form.

prechips tools [--inventory <toml>] [--measure [--plan <plan.toml>]...] [<query>]
    The inventory as prechips resolved it: ids, sizes in both units,
    holder chain, what is verify = true. With a query ("reamer 6.5",
    "R8") the candidates the sizing rule would consider and why each
    passes or fails. Also prints each machine envelope limit as measured
    or unmeasured. --measure lists the measurement debt behind the
    current reports: the numbers.measurements entries of every unresolved
    finding for the --plan files (default: the five shipped example
    plans), sorted and deduplicated by exact report id, set members and
    tool/holder pairs included, with instrument and units. It walks no
    inventory field a rule does not read; --inventory (or
    PRECHIPS_INVENTORY) overrides the plans' declared inventory.

prechips compare <plan.toml>... [--inventory ...] [--policy ...]
    §4.5: one row per candidate plan — setups, waste ratio, fixtures
    required, findings — to stdout as a table and <out>/compare.json.

prechips explain <report.json> <rule>[:<subject>]
    The numbers behind one finding, for the informed review: inputs,
    citation, the computation. Never on the sheet.
```

Conventions: inventory and policy default from `[paths]` in the plan or
from `PRECHIPS_INVENTORY` / `PRECHIPS_POLICY`; `--out` never writes
outside itself and never over an input (a `report.json` that is also the
inventory path is exit 3 before any write); nothing is interactive; stdout
is the human table, `--json` switches it to the machine form; stderr
carries findings and `?` lines. Determinism is a CLI contract: same inputs,
byte-identical `report.json`, checked in CI by running twice.

### 5.2 Non-functional requirements

- **Telemetry is OpenTelemetry, from M1.** Every verb runs under a root
  span (`prechips.<verb>`), each rule evaluation is a child span
  (`rule.<name>`, attributes: subject, status, the numbers it compared),
  each input load and each output write is a span, and every finding is a
  log record correlated to its span. Resource: `service.name = prechips`,
  `service.version` = the package version, `service.namespace` from
  `OTEL_SERVICE_NAMESPACE` when set (harmonic-analyzer sets
  `harmonic-analyzer`), so prechips rows sit beside the consumer's in the
  same App Insights workspace.
- **Exporters by the standard environment, nothing else.** OTLP over
  HTTP/protobuf and gRPC, selected and pointed by the stock
  `OTEL_EXPORTER_OTLP_*` variables (`_ENDPOINT`, `_PROTOCOL`,
  `_TRACES_ENDPOINT`, `_LOGS_ENDPOINT`, `_HEADERS`, `_TIMEOUT`); batch
  processors; flush on exit including the exit-3 path. No endpoint
  configured means no exporter and no warning. `TRACEPARENT` in the
  environment is honoured, so a `check:traveler_<stem>` leaf launched by
  harmonic-analyzer's `dodo._exec` continues the doit task's trace.
- **M1 acceptance for telemetry: the farm path.** The consumer's farm
  workers export through the Azure Monitor Agent's local OTLP/gRPC endpoint
  (`OTEL_EXPORTER_OTLP_PROTOCOL=grpc` plus the signal endpoints the farm
  already sets for the build). M1 is not done until a `prechips check` run
  as a doit subprocess on a farm worker shows its `prechips.check` span and
  its finding log records in the same App Insights instance as the
  harmonic-analyzer build that launched it, parented to that build's task
  span, queried by `operation_Id`. Locally, the same run against the Aspire
  dashboard on `127.0.0.1:18890` shows the same tree.
- **Rich console.** stderr is a `rich` console: the "before you start"
  lines with their glyphs, the rule table on `--verbose` (one row per
  `(rule, subject)`, status-coloured), tracebacks with locals on a crash,
  progress only when a kernel job runs. Plain text when stderr is not a
  TTY or `NO_COLOR` is set; the glyphs survive both. Console output is a
  rendering of the same records the OTel logger receives, never a second
  channel of facts.
- **Determinism and speed.** `report.json` byte-identical across runs and
  machines for the same bundle; a kernel-free `check` on the rocker-arm
  bundle under one second; the kernel job, when used, is the only process
  prechips spawns and its JSON result is cached by bundle hash.
- **No network at check time** except telemetry export; the inventory's
  `chart` URLs are citations, not fetches.
- **Docs are part of the milestone.** A milestone is not done until
  `README.md` (what prechips does today, the CLI as it actually behaves,
  how to run the examples), `AGENTS.md` (how an agent works in this repo:
  uv, the no-invented-numbers rule, where fixtures and cites live, how to
  run the validator and the telemetry check) and the feature docs under
  `docs/` (one page per input file format and one per rule family,
  matching the shipped schema and statuses, with the sheet sentences each
  rule prints) describe the shipped state. A PR that closes a milestone
  and leaves any of them describing the previous one is not mergeable;
  the examples README and this plan's milestone list are updated in the
  same PR.

## 6. The kernel: what the spike measured

§4.2–4.3 need a B-rep. FreeCAD's bundled OCC is the only candidate (Fusion
rejected; no OCP/CadQuery dependency), driven as a `freecadcmd.exe`
subprocess that takes a JSON job and returns JSON facts.

**Round 1 (API smoke test, 2026-10-03, FreeCAD 1.1.4 via winget, v38 release
STEPs).** `rocker-arm`, `pivot-shaft`, `pivot-bracket` load as one valid
solid each (18/18/16 faces); bbox and volume read; a −Z ray returns the
first face; a box boolean returns a volume; two runs are byte-identical
JSON. This proves the API works, not any §4 verdict: the ray went through
the bbox centre, not the bore, and the jaw test's "0 above the grip" was
true by construction.

**Round 2 (discriminating tests, same day, `rocker-arm`).**

| test | result |
|---|---|
| bore as a face set | Ø6.5 cylinder patches: faces 1 and 16, equal area 72.05 mm² — a feature is a set |
| ray down the bore axis (0, 8); ray at r − 0.1 | no hit (through bore), both |
| ray at r + 0.1 | hub top (face 15) at t = 10.0, then hub bottom (face 12) at t = 17.06 = 10 + 7.06 ✓ |
| PM 6 in vise from inventory (jaw height 1.825 in), jaws flush with the rails, grip 3 mm vs 20 mm | strap top face (52 samples): zero-radius +Z ray occluded **0 / 0**; 3/8 in end-mill cylinder occluded **0 / 4** — the ray test cannot see a jaw standing beside a face, the tool-cylinder test can |
| face order across independent exports | v37 vs v38 `rocker-arm.STEP` (different bytes): 18 faces, same order, same (type, area, bbox) list — one data point, not a guarantee |
| determinism | two runs byte-identical (`7df25936…`) |

Consequences, now in the rules: accessibility uses prescribed cutter poses
and the holder against actual setup material and fixtures. A thin shell of
the sampled face removes self-contact; only flute stock obstacles additionally
exclude the op's own derivable allowance or actual hole cutter volume (§4.2).
Other finished faces and holder obstacles remain. The round-2 script
intersected the cylinder with the jaws only, at a fixed 40 mm height, with no holder, so it
proved jaw proximity and nothing more (§4.2); features carry face *sets*
(§3.2). At the time of the spike, consumer face export was still pending;
M3 now supplies it (§8). The once-observed export order stability is not
relied on. The original required §4.2/4.3 discriminators were:
the cylinder against a boss (must occlude), the claimed side wall
(offset must clear; removing the offset must fail), an oversized cutter in
a through-groove (opposing claimed wall must occlude), holder versus jaws,
filleted-part booleans (`summing-lever`), and the thin-wall map. The M4
regressions and their observed evidence are recorded in §8. Historical
spike scripts stay out of tree at `C:/src/dt-logs/prechips-spike/`.

## 7. Kept from the reviews, and why

- **Unknown is not a pass.** Unmeasured inventory shows as `?`, and a required
  `?` keeps the `PLANNED` banner and exits 4.
- **The drawing's numbers come from a generated, complete manifest**, not
  PMI, not a hand-typed file, with explicit unknowns.
- **Policy lives with the shop, not in the plan**, and names its subjects.
- **Selected tool, not "some tool".** The sizing check reads the op's tool.
- **Readiness binds to the report hash** (§5). The one line restored from
  rev 3; the machinist sees only the short id.
- **Physics as `!` lines, not gates**, and only where every input is
  declared (K_c and E from the shipped table, stick-out from the plan).
- **No EL400 file format.** A DRO recipe on the sheet, with a check move.
- **Stock-form comparison lists, it does not choose.**
- **Pilots**: `pivot-shaft` (lathe, simple), `rocker-arm` (mill, medium),
  `pivot-bracket` (mill, 3 setups, hard), `cone-pivot-post` (stock-form
  comparison); the rev-1 `pivot-bushing` is retired.

Dropped from revs 2–3: hashes on the sheet, rule ids on the sheet, per-finding
citations on the sheet, 15-decimal evidence strings, `attestation.yaml` as a
separate file (the approval record and the logbook line are the
attestation), the 14-rule policy vocabulary. Dropped from rev 4: the
"expected deflection" line on a mill sheet (no inputs for it), tool-life
scheduling, the one-feature-one-face assumption, the plan pathname on the
sheet.

## 8. Milestones

0. **M0 — kernel spike** (§6). Done 2026-10-03, two rounds.
1. **M1 — local implementation deliverable completed.** Five strict TOML
   formats, all twelve §4.1 M1 rules, five CLI verbs, canonical bound reports,
   approval gating and generated Letter HTML are implemented for the authored
   reference routes (including their setup pages and contour continuations).
   Examples remain PLANNED with expected exits shaft 4 / rocker 2 / bracket 2;
   M1 alone does not complete M2 feasibility, M3 export or M4 kernel geometry.
   Local telemetry/exporter checks are not live farm evidence. **Physical
   `rocker-paper-rehearsal` and §5.2 parented farm telemetry acceptance remain
   pending/unobserved.** The original acceptance criteria remain:
   **Acceptance test
   `rocker-paper-rehearsal`:** a frozen bundle → CLI → printed Letter page
   (printed, to catch clipping); someone who has not read the plan
   dry-runs the setup on the PM-30MV from the page and the drawing alone
   (hold, zero + check moves, tool changes, depths, inspections) and writes
   down every instruction they had to invent — the list must be empty —
   **and** an independently worked oracle (by hand, from the drawing and
   the manual: every Axis Set value, the retouch value after facing, every
   tip endpoint, the four quadrant offsets) matches the page to the
   drawing's precision. Controls, each a committed bad bundle that must
   produce the prescribed stop, not merely different output: removing the
   reamer or chuck from the inventory → `✗`; the EL400 Direction for X
   actually reversed on the emulator (not the plan edited) → the printed
   check move reads the mirrored value and the operator stops; removing
   `checks.position` while leaving the pin → `✗` for the rod hole; a
   manifest with one `"unknown"` tolerance among known ones → `?` and exit
   4; editing `features.toml` after approval → `PLANNED` naming the input;
   an empty ops list → exit 3; the report byte-repeatable.
2. **M2 — local declared-input implementation completed 2026-10-03.**
   Turned-profile monotonicity,
   supported stick-out, collet/chuck diameter capacity, exact-first indexing,
   turning-deflection and engagement proxies, and gated stock-form comparison
   are implemented. Lathe Z/spindle, diameter-mode X and cross-setup `transfer`
   conventions remain the existing shaft route's; no cross-hole is added.
   The original “shaft's cross-hole” indexing bullet is **superseded**: rev 6
   declares no such feature. The first BS-0 case is the cone-pivot-post's
   12.5182° cone-journal inclination (`positions = 1`, no repeated-pattern closure),
   with authored full-envelope one-piece and block-plus-pressed-boss alternatives.
   The drawing is one-piece only; the built-up candidate is refused.
   **Historical local acceptance after PR #6 review corrections:** Ruff check and
   format check (67 Python files); 575 pytest cases; all 12 TOML inputs / five
   candidate goldens validated. Actual CLI travelers preserve exits
   4 / 2 / 2 / 4 / 2 and cone comparison exits 2, with canonical golden parity.
   The corrections use finished exposed stick-out D, explicit built-up permission,
   full-pattern-only closure, endmill-with-DOC engagement, machine hold resolution
   and one shared citation collector. All six findings were reproduced before
   their fixes. Only changed rule output regenerated goldens (#1, #4 and #5).
   Chromium showed the synthetic 30° × 3 open pattern's exact landings and
   “Open pattern: no cycle closure.” This is not physical print evidence.
   **Unobserved/pending:** measured chuck capacities/support/BS-0 inventory,
   sourced K_c/E and a BASIC-angle landing allowance (now an HA export
   follow-up, M3 item 7), printed traveler/operator rehearsal, independent hand
   oracle and live prechips farm telemetry. The
   then-pending M3/M4 binding is superseded by the delivered exports and kernel
   work below. Unknown inputs remain `?`, not a numerical machining approval.
3. **M3 — consumer export: consumer side done 2026-10-03; HA traveler tasks
   and export fields remain open (listed below).**
   `examples/rocker-arm/`, `examples/pivot-shaft/` and
   `examples/cone-pivot-post/` now contain verbatim generated `features.toml`
   and their exact adjacent STEP files. Each manifest names that STEP, binds
   its SHA-256, declares drawing revision and one-piece construction, preserves
   sourced requirement/precision/citation records, and carries labelled
   entity/ordinal face sets. These are actual exported inputs, not the former
   hand-authored substitutes. Export delivery provenance and exact digests are
   recorded only in [examples/README.md](examples/README.md#m3-export-delivery-provenance).
   Python citations remain `file:line`; YAML citations are `file:dotted.key.path`.
   All plans remain authored and PLANNED. The pivot-bracket keeps hand-authored
   `features.toml` on the consumer v39 STEP
   (`6cd4ab60f57b1c9771cec083fbbd0ef1f94171f1d95f9485a135a4dec0b2dabc`).
   No dimensioned bracket drawing is supplied, so its bands are illustrative
   example design intent rather than measured or exported drawing limits.

   The exported contracts include expanded rocker datum/tip features, shaft
   face splits, the cone journal's unknown requirement identity, and rendered
   metric general bands. Current expected pilot exits are 4 / 2 / 2 / 2 / 2
   (shaft / rocker / bracket / cone one-piece / cone built-up). The one-piece cone
   moved from 4 to 2 because its exported `mount_west` nominal conflicts with its
   band and restored milling frames expose far-side boss-face claims.
   Existing inspection choices follow the split exported feature owners with
   unchanged gauges. Unknown requirement identities, measurements and methods
   remain unresolved, not invented. Consumer handling of the export as delivered:

   - **Rocker top edge.** The export sets `top_edge_feature = "top_edge"` on
     `profile_outer`, `tip_land_pos_x` and `tip_land_neg_x`. The coordinate rule
     examines every linked feature instead of giving up when more than one
     links, so the R800 top-edge cutter-centre tables are back in S1 op 40,
     S2 op 40 and S3 op 30.
   - **Shaft/cone setup frames.** Both exports carry `frames.setup = "unknown"`.
     The former shaft T1/T2/T3 and cone/built-up lathe and M2/J3/C4 transforms
     are again plan-authored `[frames.<name>]` tables (existing Frame schema,
     with author's-choice notes and plan citations), and the setups name them. They
     are process-plan choices, not CAD facts; the verbatim exports are
     unchanged. They restore coordinate/DRO, turned-profile, stick-out and
     envelope numbers only where the exported geometry supports them. The exports
     have no turned-feature axial extents (`z_mm`), so turned-profile and stick-out
     segments that need them stay unknown. Neither dome exports a `base_radius`,
     so shaft S2:20/S3:20 `speeds_feeds` `diameter_in` stays unknown.
   - **Shaft cut-to-fit length.** The export's `pivot_bearing` carries only
     `note = "CUT TO FIT: SPAN OVER BOTH MHA-123 EARS"` and `length_ref = 156.67`.
     It has no length requirement or end-past-scribe band. The former `plain_end:length`
     inspection is not dropped: the plan declares the calipers check as
     `missing_requirements = { length = "calipers" }` on the `pivot_bearing`
     inspect op S3:15, between the cut and doming so the cut face can still be
     checked/reworked; the existing post-doming verification stays a forward
     instruction. The report keeps an unknown `pivot_bearing:length` row with
     `missing_requirement = true`. A `checks` entry for a requirement the feature
     does not export is bad input, so a check can no longer be silently unread.
   - **Cone volume.** The export has no `volume_mm3`/`volume_cite`, so comparison
     keeps net volume and waste unknown. The historical handwritten analytic value
     is not imported.
   - **BASIC indexing angle.** `crank_bore` exports a BASIC angle
     (`dimension_type`, cited to `BASIC_DIMENSIONS`) and no `angle_tol_deg`.
     The consumer does not let a BASIC angle inherit the title-block ±1°, and it
     does not turn the Ø0.10 angularity zone into degrees itself. So cone S3
     `indexing` stays unknown. A source does exist in HA: it derives
     `CRANK_BORE_ANGLE_LIMIT_DEG = degrees(atan(0.10 / CRANK_BOSS_LENGTH))`
     ≈ 0.0795° (`cad/scripts/cone_pivot_post_spec.py:373`). That value is used
     at `crank_mesh_stack.py:80` and tested at `test_cone_pivot_post_drawing.py:439`,
     but it is not exported.
   - **`mount_west` sign.** The export has `station_nominal = -12.98` (signed X)
     but `station = [12.47, 13.49]` (built from `abs(ATTACHMENT_X)`). The
     consumer's generic nominal-within-band input check reports
     `mount_west:station` as an `error`, so the one-piece cone exits 2. This is an
     honest stop on an exported inconsistency. Prechips does not flip the sign or
     drop the field.

   **Open M3 items owned by harmonic-analyzer**, cited at `b11124ecf`. Each one
   blocks claiming full HA integration:

   1. Add `check:traveler_pivot_shaft` and `check:traveler_cone_pivot_post` doit
      tasks. Only `check:traveler_rocker_arm` exists (`dodo.py:3521-3538`), and
      no run of it has been observed.
   2. Setup frames: the shaft/cone exports have `frames.setup = "unknown"`. The
      prechips plan frames are author's choices. Either HA exports setup frames
      the way the rocker exports `frames.A/B` (`rocker_arm_spec.py:72,117`), or
      the plan frames stay the authority.
   3. Export axial extents (`z_mm`) for the shaft/cone turned features.
   4. Export `base_radius` for the shaft's `north_dome`/`south_dome`.
   5. Export cone `volume_mm3` with `volume_cite`.
   6. Export the shaft cut-to-fit length requirement: the owning feature and an
      end-past-scribe acceptance band. The former hand-authored manifest carried
      `cut_past_scribe = [1.5, 2.0]` and `end_past_scribe = [0.0, 0.5]`; those
      are historical, not imported. Until HA exports the requirement, the
      `pivot_bearing:length` inspection stays unknown.
   7. Export `crank_bore.angle_tol_deg` from `CRANK_BORE_ANGLE_LIMIT_DEG`
      (≈ 0.0795°, `cone_pivot_post_spec.py:373`) with its citation, or record in
      HA why that bound is not an indexing landing allowance. The general ±1°
      is not that allowance.
   8. Make `mount_west.station_nominal` (−12.98) and its `station` band
      [12.47, 13.49] use the same sign (`cad/scripts/export_features.py:566`).
      This clears the cone's `mount_west:station` error.

   **Prechips integration status (separate from the HA export list):** the
   radial sampled turning approach is implemented, including modeled chuck
   obstacles and jaw thin-wall facts. Lathe headroom checks measured swing and
   between-centres limits. Derived turning and milling stock outputs stay in
   model coordinates and can feed explicitly selected nonprevious setups;
   fragmentation is checked per input piece. These are necessary-condition
   screens, not physical setup or toolpath certification; unresolved inputs
   remain unknown. The dated gate evidence below predates this integration.
   Restored cone milling frames also expose real directional claim errors:
   one-piece S2:40 (`crank_boss`) and S2:50 (`cone_boss`), and built-up S2:50
   (`cone_boss`), claim entire cylindrical face sets including faces pointing
   away from the milling approach. These remain directional-claim `error`
   findings. Resolving the authored milling route/face claims is
   a separate prechips planning follow-up; fixing HA's station sign alone
   does not clear these machining stops.

   **Post-review consumer gate, observed 2026-10-03:** on implementation
   `68aef8f`, `uv run ruff check . && uv run ruff format --check . &&
   uv run pytest -q && uv run python scripts/validate_examples.py` exited 0
   with `FREECAD_CMD=C:/Users/pedro/AppData/Local/Programs/FreeCAD 1.1/bin/freecadcmd.exe`
   and `PRECHIPS_REQUIRE_KERNEL=1`: Ruff passed, **100 Python files** were
   formatted, **1282 tests passed** (534.59 s), and all **24 TOML inputs** and
   rev-6 reference bundles validated. Actual CLI regeneration and the final
   frozen-output tests cover all five travelers and the cone comparison.
   Traveler exits are **4 / 2 / 2 / 2 / 2**; comparison exits 2, with both
   candidate exits 2 and cone net volume/waste still unknown.

   **Legitimate golden changes from `7616f0a`:**
   - Rocker `coordinates` S1/S2 op 40 and S3 op 30 regain the R800 top-edge
     tables, **23 rows each**, with cutter-centre radii 795.0375 / 795.0375 /
     795.2375 mm. Every linked profile/tip-land supplies and agrees on its
     join; no link is ignored to manufacture the table.
   - Shaft `inspection:pivot_bearing:length` is an explicit `unknown` at
     S3:15, between cut op 10 and dome op 20. Its calipers gauge and original
     procedure remain visible; zero/order findings do not change. Directional
     rows for lathe cuts and their dependent finish rows now say `unsupported`,
     not an invented axial-engine pass or failure.
   - Shaft/cone setup coordinates and envelope facts regain plan-authored
     transforms and their original citations; numeric facts are still nominal,
     not measured setup bindings. Turned-profile axial segment arrays and the
     diameter-in/stick-out facts needing missing `z_mm` / dome `base_radius`
     remain explicitly unresolved (HA items 3–4 above), rather than invented.
   - Cone `inspection:mount_west:station` changes from `unknown` to `error`
     because exported −12.98 is outside [12.47, 13.49]. Restored milling
     frames also expose the named, genuine far-side claims above; these stops
     outrank the remaining unknown volume/allowance facts. The one-piece exit
     therefore changes 4 → 2 and the comparison candidate exit follows it.
   - Pivot-bracket finding content is unchanged. All six delivered STEP/feature
     assets remain byte-identical to the original exports; goldens do not patch
     or normalize the upstream data.

   **Independent revision review:** the original seven findings and four
   follow-up timing/diagnostic/domain/nominal-contract findings are resolved.
   The read-only Opus review approved `68aef8f` with **zero open findings**;
   it confirmed byte-identical exports, preserved zero/order findings, distinct
   unsupported versus genuinely unclaimed faces, and no golden pass → nonpass
   or error → pass transition. Chromium inspection of the regenerated shaft
   shows cut / `? length ?` inspect / dome in order 10 / 15 / 20, with the
   exact missing requirement and original procedure; the rocker displays all
   three numeric top-edge cutter tables.

   **Historical pre-review consumer gate, observed 2026-10-03:** on implementation
   `5f51a2c` (before the seven findings above), `uv run ruff check . && uv run ruff format --check . &&
   uv run pytest -q && uv run python scripts/validate_examples.py` exited 0
   with `FREECAD_CMD=C:/Users/pedro/AppData/Local/Programs/FreeCAD 1.1/bin/freecadcmd.exe`
   and `PRECHIPS_REQUIRE_KERNEL=1`: Ruff passed, 99 Python files were formatted,
   **1042 tests passed** (519.14 s), and all 24 TOML inputs and reference bundles
   validated. Actual CLI regeneration wrote all five report/traveler goldens,
   the rocker S1 render and cone comparison; exits remain **4 / 2 / 2 / 4 / 2**
   and comparison 2, with unknown cone net volume/waste. The suite reproduced
   the frozen CLI bytes twice. FreeCAD mapped all exported references without
   errors: rocker **18/18**, shaft **18/18**, cone **36/36**.
   An extracted `git archive` implementation copy preserved all six delivered
   assets byte-for-byte with matching adjacent STEP digests; its actual rocker
   traveler exited 2 without invalid face references or inspection errors.
   The first review confirmed the export byte/face binding, but the later Opus
   review found seven numeric-content, inspection and disclosure regressions;
   passing the old goldens did not detect those regressions.
   Prior M1/M2/M4/M5 results below are historical, not the post-review gate.
   The CAD-producing farm run is not a parented `prechips check` farm trace.
   HA's existing `check:traveler_rocker_arm` invocation and §5.2 live telemetry
   acceptance require their own observed evidence; the shaft/cone task names
   are absent (open item 1 above). Physical paper rehearsal, independent hand
   oracle and first-article approval remain separate.
4. **M4 — geometry and workholding local deliverable** (§4.2–4.3).
   Seven sampled B-rep rules execute in a separate FreeCAD process. STEP
   byte identity and entity/ordinal/label references are checked before
   mapping by surface/area/bbox, never by imported face ordinal. An absent
   kernel yields one console `?` line and unknown geometry, not fabricated
   passes; named mapping and directional-claim errors remain errors.

   **Saw cut-off shipped (2026-10-06, `m5-rev9`):** `saw_cut` / `cut_off`
   on mill, bench or bandsaw removes a setup-plane slab including the selected
   blade's kerf, preserving the finished target and routing the retained stock.
   Cited canonical `saw_cut` rows supply linear blade sfm and descent feed,
   never spindle RPM. Axial/turning-cylinder accessibility is explicitly
   not applicable; saw cuts earn no finished-face coverage. Fixture modeling
   and input debt semantics remain operative.

   Geometry checks and rasterized pictures use **setup-entry stock** selected
   explicitly by `stock_in`: `"stock"` for one supply, `"stock.<id>"` for a
   built-up component, any earlier setup id (not just the previous setup), or a
   nonempty array joined by Boolean union. Supplies and setup outputs stay in
   model coordinates; joining applies no implicit assembly transform. Components
   require known, nonempty, unique ids matched exactly, with no ASCII whitelist,
   and accept `origin_mm`, `axis` and `section_axis` with root-stock pose semantics. Each contains only
   its own piece, not the full finished STEP. Missing component geometry remains
   individual debt. Unknown or forward authored references are bad input
   (exit 3), including `"unknown"`; omitted `stock_in` is debt, never auto-linear.
   Array entries must have disjoint supply ancestry; duplicates or joining a
   supply with its descendant are exit 3, naming the shared ancestor. Independent
   forks may restart from the same supply as alternatives, not join that material
   lineage twice. Known branches remain usable when another component's geometry
   is missing. With all component envelopes known, their full union must contain
   the finished STEP; otherwise all component references carry geometry debt.
   Nonempty root `as_is_faces` checks the full joined supply exterior and needs
   every component envelope known, potentially withholding known branches;
   empty or omitted declarations add no cross-component dependency. Removal
   fragmentation is checked per input solid, so deleting one assembly piece
   cannot mask splitting another.
   Each output subtracts its setup's derivable removals from its selected input.
   Facing's planar outer-wire sweep clears raw caps over hole mouths while
   preserving finished islands. Generic bounded clearing preserves known
   unclaimed planned-hole columns for their own future hole operations, not
   every concave cylindrical face.
   Reserved columns use the matched bore's exact axial span plus any adjacent
   coaxial concave cone/sphere cap no wider than the bore, with numerical
   lift at either end, not entry-stock height; wider back countersinks are
   not reserved, blind columns stop at their caps, and pins/rods outside the
   hole remain material.
   Current-setup cuts shape output stock and, in op order, the stock each
   later milling or hole flute of the setup meets (never a later cut's); the
   flute also excludes its own op's derivable allowance; holder, reach,
   holding and image facts still use setup-entry stock. After an underivable
   earlier cut, later flutes keep only certain finished hits and their tool
   hits are unknown; final wall/cap debts never change a before-op stock.
   `stock_removal_bounds` is the
   authored cleared footprint (possibly several passes), not capped to the
   claimed faces' XY bbox plus cutter radius and not a whole-toolpath proof.
   A known cutter radius, finite bounds, intersection with the selected stock,
   protection of finished material and rough leave, exact claim/piece contact,
   future planned-hole columns and no split of an original solid still apply;
   a violation is named stock debt, not an error, while genuine finished
   collisions remain errors. An unknown radius leaves the bounds `?` with a
   missing-cutter-radius reason; neither case can certify the next setup.
   Interior contact with retained
   overstock is checked for every claimed lateral face, including drafted walls.
   Invalid supply, unbound as-stock faces or a non-derivable retained
   rail/profile mask yields a named unknown and no stock picture.

   The 2026-10-05 user decision replaces boundary-centred floor poses: a
   floor sample on or within a cutter radius of any concave floor/rising-wall
   edge, curved ones and boss feet included, shifts along the wall's in-plane
   normal at the nearest edge point to tangency with every such wall (exact
   for concave circles at least the cutter's radius); a cutter wider than its
   gap keeps its own axis and reports the real hit. Convex edges and farther
   interior samples are unchanged; a sample past both walls of a sharp convex
   island corner moves straight away from that corner to tangency (classified
   by the wall/wall edge rising there, not another edge the walls share), and
   convex vertices add no corner pose. A +Z planar floor that fits wholly inside the
   cutter disc instead stands on one derived pose (centroid of the covering
   axes, a certified single axis, or its R-arc walls' shared centre); an
   undecidable one drops only its own poses and leaves the op's facts unknown.
   Tangency does not
   certify corner radii, and floor-only claims do not certify wall/wall corners.
   `internal_corner_radius` retains its existing claimed-face scope:
   a sharp wall/wall corner is checked when the op claims both walls.
   Only a 0.001 mm inward shell of the sampled finished face is excluded.
   Own outside-finished allowance and own actual hole cutter volumes
   (drill/spot/ream/bore/tap/counterbore, to declared depth or explicit through
   extent) are excluded from flute stock obstacles only. Spot and drill cut
   with a point cone and full-radius body; their numeric `point_angle` is
   mandatory, and unknown is accessibility and later-stock debt. Spot depth is
   the apex tip depth; drill depth is full-diameter depth with the tip
   `r / tan(point_angle/2)` deeper; `to_z` is the absolute actual tip.
   Ream/bore/tap/counterbore remain flat cylinders. Hole axes/centres
   come from matched concave cylinders aligned to setup Z; through endpoints
   use each bore's actual axial exit (plus a drill's point), not the raw-stock
   bounding-box bottom. A hole op wider than its bore removes its own wall
   with no fixed radial cap; sizing owns the diameter.
   Missing depth/entry and explicitly unknown through facts remain debt;
   absent `thru` retains the existing blind-hole default.
   Spot and tap honor explicit depth even when the feature is through.
   An own hole bore radius is diameter-sizing, not `internal_corner_radius`;
   an own known matched point cap is its tool shape, checked against
   unmodified entry stock without an offset shell. Other claimed caps are not
   blanket-exempt. Each feature's last drill/ream/bore/counterbore (a thread's
   last drill) must leave its own claimed caps clear of its setup's final
   stock; otherwise they are output-stock debt and uncredited finish faces,
   never collisions.
   Stock-state `top_z`/`entry_z` and op `depth_mm` are millimetres even for
   inch-unit features; tap fallback feature-depth bands convert to millimetres.
   No full-feature union, cutter-radius slab or sharp-edge air wedge removes
   neighbouring finished walls;
   undercut/leaning walls and unrelated material remain obstacles.
   Rough milling leaves its `rough_allowance_mm` normal to the finished
   surface (`r + a` floor-edge constraints); an explicit `to_z` caps the
   endpoint without a second leave, and any milling op's numeric `to_z`
   above its face is its actual tip.
   Holder obstacles, reach, holding and rendering keep actual setup-entry
   stock; no flute is credited with a later op's removal.
   OpenCASCADE distance extrema that fail with `StdFail_NotDone` retry with
   the operands swapped: this measures the same geometric distance rather than
   suppressing the failed guard. Other native exceptions still propagate.
   Explicit nonempty `op.faces` overrides the feature face set. A far-side
   face errors by reference and never credits coverage/finish; missing
   normals leave the face unknown. Certain observed collisions error even with
   unknown stock/fixture/dimensions, and finished corner radii survive stock
   debt; exit 2 beats 4. Accessibility needs projection, not unused OAL.
   Prescribed tangent/normal-offset poses screen collisions, not alternate
   machinable poses or a toolpath; unresolved pose facts do not become passes.
   Corner comparisons allow 0.005 mm numeric STEP/kernel round-off, not a
   shop machining allowance: a 0.004 mm radius deficit passes, 0.006 mm errors.
   The rocker's 0.99695 mm corner against a 0.997 mm cutter therefore passes.

   Fixture pictures use only numeric jaw/parallels dimensions and declared
   poses; a certain/possible jaw envelope is labelled unresolved. Vise
   risers, 3-/4-jaw chucks (jaws closed on the entry stock's grip zone), the
   dividing head with its chuck, dead centres with their tailstock quill,
   angle plates, clamping-kit straps and custom fixtures are drawn the same
   way from explicit inventory dimensions or authored `solids` primitives
   and plan poses; every drawn solid is an accessibility/holder obstacle and
   an undrawn possible obstacle keeps clear samples `?`. The report scene
   names `fixture_kind` and every component; `modeled` requires all of them
   exact and no debt (`examples/geometry/fixture-holds` holds one synthetic
   puck all six ways, observed 2026-10-05 with FreeCAD 1.1). Posed straps on
   angle-plate/custom holds also resolve `thin_wall_under_clamp`: the
   thinnest material run under each bearing strap footprint along its pose
   −z; unposed/unverified clamps stay `?` with named debts. Raster
   PNGs are bound by hash and preserved by `*.png binary`; STEP files retain
   `-text`. Successful `traveler`/`check` runs transactionally remove
   unreferenced old setup images, including absent-kernel runs. `check` also
   removes same-named PNGs whose bytes differ and any prior traveler sheet;
   matching images may stay. A refusal restores every prior output even after
   an absent deletion. Kernel discovery checks the current user's LOCALAPPDATA,
   never a developer's hard-coded home. The cache hashes only engine inputs,
   not host-only finishing, resolved-projection OAL, wording or grip policy.

   The combined catalogue is `m5-rev9`. Geometry reuses M5 fact-local length
   lookup with nominal facts allowed: only that dimension's own verification
   or incomplete measurement record withholds it. Item/source/container
   flags never taint other dimensions. Projection maps use the full selected
   holder reference; an explicitly unknown selected pair stays unknown,
   without an OAL−grip fallback. M5 physical stack/envelope readiness still
   requires its separately qualified shop measurements.

   Historically, the pre-M3 production rocker S1 strap operations explicitly
   claimed the then-exported +Z datum-B face `#492`. The current M3 export uses
   its own `strap_datum_b` face identity; old entity numbers are not portable.
   The S1 supply is still authored rectangular stock; later unprovided
   rail/ear footprints remain debt, not a finished-STEP substitute.
   Synthetic fixtures author numeric supply allowances and earlier clearing
   setups. The synthetic rocker supply/clearance now fits the STEP global XY
   bbox, retaining its 1 mm Z allowances, so unknown preparation tooling does
   not invent a cutter-dilated footprint. Preparation tooling/holding debt stays
   visible; target checks remain required and all errors remain fatal.

   **Historical scoped M4 evidence (before the M3 consumption cutover):**
   archived PNG signatures and STEP/report digests passed after binary
   restaging. A Ø10 cutter in a 6 mm through-groove
   reports 135 tool hits. The claimed-sidewall normal-offset test passes on
   the offset engine and fails its hand-written no-offset mutant with 45
   own-wall hits. Undefined normals yield named unknowns on clear faces,
   while a definite wall collision retains an accessibility error.
   A two-setup bounded clearing test jointly claims wall and floor and keeps
   5 mm side rails: entry volume 66000 mm³, prepared volume 51600 mm³.
   Opposing finished walls/retained rails remain obstacles after own-allowance
   exclusion. Complementary finishing claims pass; swapped far-side claims fail.
   Actual geometry-fixture CLI exits remain 2 / 2 / 0 / 2 / 2:
   rocker target S3:10 has 56/65 jaw/boss hits; short pocket target S2:10
   has 45 mm reach and 104 holder hits, while long-reach clears; sharp corners
   fail the cutter radius; the step's +X end remains deliberately unclaimed.
   Numeric preparation tests verify raw/intermediate/target material volumes,
   exact target fixture scenes and bound render bytes.
   Review regressions rejected a clearing box 27 mm outside its claimed
   footprint; the following setup retained unknown reach/holding. A 1° drafted
   wall (including a 200 mm-wide face) and a small retained ear named stock
   debt. A fully specified facing operation reported 0 tool/holder hits,
   5 mm entry-stock reach and 65 samples; reducing projection still hit the
   holder. Certain collisions and a finished sharp corner remained errors
   under unknown stock; explicit projection with unknown OAL still allowed
   accessibility to pass while reach stayed unknown.
   All ten actual travelers repeated byte-identically through independent
   fresh cache roots before the corrected outputs were frozen. Regeneration
   changed only rocker report/sheet, all five geometry report/sheets and the
   synthetic rocker's three stock PNGs; other pilot bytes stayed unchanged.
   Installed-kernel pilot exits stay 4 / 2 / 2 / 4 / 2. Seeded obsolete S1,
   S2 and S99 images disappeared under both absent-kernel `traveler` and
   `check`. Browser-served production S1 showed the raw grey rectangular bar,
   a named missing jaw-depth caption and no later stock images. The long-
   reach target showed its prepared pocket, exact jaws/parallels and the
   setup-entry-stock caption; both 640 × 480 images loaded successfully.
   **Historical project-wide acceptance after Opus r2 / CodeRabbit r1 fixes:**
   `uv run ruff check . && uv run ruff format --check . && uv run pytest -q
   && uv run python scripts/validate_examples.py` exited 0: 99 Python files
   formatted, 1033 tests passed and all 24 TOML inputs plus frozen
   report/sheet/render contracts validated. The first review gate exposed one
   obsolete test requiring unknown stock to suppress certain hits; that test
   and the obsolete stock-dependent corner parameter were removed, not re-pinned.
   The new stock-debt/finished-fact regressions cover their correct precedence.
   Corrected goldens retain pilot exits 4 / 2 / 2 / 4 / 2 and geometry exits
   2 / 2 / 0 / 2 / 2 under `m5-rev8`.

   These are local sampled-solid checks, not CAM simulation, a measured
   production fixture, physical operator/setup verification or approval.
5. **M5 — measured inventory**: spindle stack, travel limits, holder gauge
   lengths; envelope checks leave `?`. **Implemented (PR #7 review cutover,
   `m5-rev7`); shop measurements pending.** `machines.<id>.envelope` is the
   single machine block (`travel` x/y/z, `spindle_to_table_max`/`min`) read by
   `headroom`, `envelope` and `travel`; the mill's top-level
   `spindle_to_table_max_in`/`travel_in`/`table_in` copies and the unread
   table size, T-slot pitch, spindle taper and spindle-stack fields are gone.

   **Rule gaps closed (2026-10-06):** dividing-head headroom uses centre height
   plus the stock-top/posed-axis offset; child point-feature travel inherits
   a missing `at` from its named parent/hole without shadowing explicit input.
   Boundary regressions cover exact-limit pass, exceeded-limit error and
   missing/unverified facts as debt. Shared example goldens/full validation
   remain the integration owner's gate after all programme branches land.
   Trust is fact-local `{ value, measured = { by, date, instrument }, verify }`,
   with no block/root/source inheritance, coverage heuristics or legacy-field
   redirect; a vendor nominal is evidence, never a certificate. The vise
   stack is `bed_height + parallels/supports + physical part height + holder
   gauge + tool projection`, never jaw height (jaw obstruction stays
   `headroom`'s separate check). Projection is a per-pair fact on the tool,
   `tools.<tool>.projection_mm.<full holder reference>`, else measured OAL −
   selected holder grip; holders carry only `gauge_len_mm/in` (one spelling)
   and `grip_mm`. `envelope` raises each op's nose by its highest authored
   approach/commanded Z against the maximum and lowers it to its deepest floor
   against the minimum; `travel` Z unions per-op spindle-nose positions
   (`tip + gauge + projection`), and XY pads hole/point centres by nothing and
   profile extents by the cutter radius; pocket/face extents are unpadded.
   `holder_stack` is deleted; unresolved tools, holders, fixtures and supports
   yield add/resolve instructions, not measurements of unowned items. Geometry
   authoring instructions print once. Explicit unknown pair projections stay
   unknown; only absent pair entries permit OAL − grip fallback.
   `tools --measure [--plan …]` lists exactly the `numbers.measurements` debt
   behind the current reports (default: the five example plans), sorted and
   deduplicated by scoped report id: plan inputs identify their plan, and
   separate inventories cannot collapse identical item/fact ids.
   Pending in the shop, none invented: PM-30MV usable X/Y/Z travel and spindle
   nose to table at full Z-up and Z-down with `measured` records; each
   selected holder's mounted gauge length and grip; parallels and 1-2-3
   block heights; each
   selected tool's OAL and its projection in the holder it is used in (or
   OAL/grip); cutter diameters, drill point angles and reamer leads the
   examples select. Per-operation safe `approach_mm` and incomplete authored
   extents remain plan-input debt, not shop measurements. Until those land,
   envelope/travel rows stay `?` with measure/how instructions. The default
   policy is unchanged; shops may require envelope/travel on `"*"`.

   **First shop measurements, recorded 2026-10-05.** Pedro Paulo Vezza Campos
   measured the PM 6 in vise (`fixtures.vise-pm-6`): jaw height 1.7695 in,
   jaw width 6.247 in, jaw depth 0.7005 / 0.7010 in (larger kept; jaw
   attribution not recorded), opening 6.135 in and bed height 2.886 in without
   the swivel base. Each is a fact-local `measured` record; vendor nominals
   stay as comments and the item's identity `verify = true` is kept. The
   rocker S1/S2 and bracket S1/S2 jaw-overlap arithmetic now uses the measured
   jaw height, and rocker S1/S2 author `jaw_center_along_mm = 0.0` (jaws
   centred on the 310 mm blank). Regenerated with
   `PRECHIPS_REQUIRE_KERNEL=1`, an isolated `PRECHIPS_KERNEL_CACHE` and
   FreeCAD 1.1 via the README `prechips traveler` / `compare` commands: exits
   stay **4 / 2 / 2 / 2 / 2**, comparison 2. Rocker S1 `vise` changes `?` →
   pass (opening 155.829 mm vs 45 mm width, contact 6.8453 mm on both jaws vs
   6.0 mm grip); its render scene changes from `jaws: absent` (missing
   `jaw_depth_mm`) to `jaws: exact`, parallels still `not_modelled`
   (no width or `parallels_centres_mm`). S1 `thin_wall_under_clamp` now
   reaches the unknown shop floor (min wall 45 mm) and S1 `accessibility`
   stops on unmeasured tool/holder dimensions instead of jaw depth. Rocker
   and bracket `headroom` now carry bed 73.3044 mm and jaw 44.9453 mm (rocker
   jaw top Z −4.68295, so no cut ends below the jaws); they stay `?` on other
   debt. `fixtures.vise-pm-6.bed_height` leaves `tools --measure`. Shaft and
   cone changed only their inventory digest. Gate on this change: `uv sync
   --locked`, `uv run ruff check .`, `uv run ruff format --check .`,
   `uv run pytest -q` (**1282 passed**, 644 s) and
   `uv run python scripts/validate_examples.py` (24 TOML files, all bundles
   validate) exited 0 with `FREECAD_CMD` set to FreeCAD 1.1. Parallels,
   blocks, holders, tools and the PM-30MV envelope remain unmeasured.

## 9. Decisions from review

**2026-10-03, rev 4 questions.** §2 density as sketched, ops and coordinates
separate tables. Units: drawing unit for coordinates, as-bought for tools,
both on the sizing line. No balloon numbers. Vendor chart first, Machinery's
Handbook 31 otherwise. Built-up construction needs a drawing-side permission
note, carried as `features.construction` and enforced by `prechips compare`.

**2026-10-03, third adversarial round (GPT-6 Astra), disposition.** Folded:
sheet carries hold/stop/clamp/clearance/coolant/deburr/direction/
breakthrough/per-tool Z/contour/release (1); DRO settings recorded, check
move printed, sign derived not assumed (2); approval and first article bind
to the report hash (3); policy names subjects, empty plans rejected,
`unsupported` ≠ `not_applicable`, block before unknown (5); explicit
`precision`, numeric frames, real TOML for `construction` (9);
`cutting-data.toml` shipped with its key and rounding, sketch RPMs
recomputed (10); every catalogue row names its inputs and tier, rows
without inputs are deferred, hole/thread row merged into chain + depth, tool
life deferred (6); spike reported as smoke test + round-2 discriminating
tests, accessibility switched to tool cylinder, features carry face sets
(7). Routed to harmonic-analyzer as an issue: complete manifest export with
provenance and the face-set mapping (4, 8).

Where the inputs Astra asked about come from (6): commanded depths →
`plan.ops.depth_mm/exit_mm` plus computed point length; placed extents →
`plan.hold` + inventory fixture dimensions + the STEP bbox (stock section
until M4); K_c and E → `cutting-data.toml`, cited; re-fixture budget and
thin-wall floor → `shop-policy.numbers`, measured or `verify`; jaw pose →
`plan.hold.fixed_jaw/jaws_along/grip_mm/jaw_above_parallels_mm` with the
vise's `jaw_height`; tool life → nobody ships a calibrated table, so the
rule is deferred rather than faked.

**2026-10-03, fourth adversarial round (GPT-6 Astra on rev 5),
disposition.** Folded: the DRO recipe written against the EL400 Operation
Manual's own functions (Direction §6.2, Axis Set §7.4, Preset §8.1 never
used for zero) with an unretouched check jog per axis and the sign
equation in the rule (1 — the plan does not pin an emulator commit; an
emulator that disagrees with the manual is an emulator bug); stock state
per setup advanced per op, tip endpoints from point length / reamer lead +
exit, local thickness per feature, sketch Z and depths recomputed (2);
`checks` keyed by requirement, inspection rule per requirement (3); the
referenced sketch removed and the bundle defined as every file read (4);
one `unknown` contract — the string `"unknown"` in a field, `requirements`
lists for known absence (5); round 2 of the spike reported as jaw
proximity, the accessibility predicate rewritten with the radius offset
and the part/holder obstruction, M4 fixtures named (6); per-dimension
`precision`, BASIC never gets a ± default (7); indexing exact-first with
closure over all positions, hole spaces (8); `[[material]]` table for
K_c/E, holder per op, projection from inventory, headroom sum completed
(9); exit precedence 3 > 2 > 4 > 0, required `warn` exits 4, output/input
collision and missing verb are exit 3 (10); rough offset 12.06, op 45
spot added, arc table on a continuation sheet, §4.6 "does not declare or
measure". Vocabulary: `error` / `warn` / `info` replaces `block`. Added
§5.2 non-functional requirements (OpenTelemetry with OTLP exporters by
standard env, farm-path App Insights acceptance at M1, rich console).

**2026-10-04, fifth adversarial round (GPT-6 Astra on rev 6 + the
regenerated fixtures), disposition.** Four findings, all folded: the zero
rule's contact-side sign separated from the jog polarity (`from` gives the
side; the sketch's reversed X reading is −12.54); headroom uses the stock's
physical height (`top_z − bottom_z`), jaw height is an obstruction check,
not a stack layer; the §3 manifest excerpt re-pointed at
`examples/rocker-arm/features.toml` with its cited values (rod hole on the
R816 arc, hub Ø10.20 under the .XX band, datums A|B|C); the cutting-data
pilot matrix cut to the rows M1 selects. Verdict after folding: approved
for implementation.

Open: who authors the rocker finishing fixture and the rail-release method
(the plan author, as an S4 with its own sheet — before M1 ships the S3
sheet names it); which measured prepared-blank surfaces define the M1
fixture (S2's `stock_state`, measured on the first blank and written into
the plan); where the approval record lives (`approvals.toml` beside the
plan, one line per report hash, written by hand after the first article).
