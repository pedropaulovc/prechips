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
  which is why the generator, not a hand, writes it (M3) and why the M1
  hand-written manifest is cross-checked against the drawing's dimension
  count.

Excerpt; the full source-backed manifest is
`examples/rocker-arm/features.toml` (every value cited to the consumer;
that file, not this excerpt, is what M1 mirrors):

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
faces = "unknown"                          # until the face-set export (M3)

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

**What the generator can and cannot source today** (rocker arm): nominal
centres and limits (`rocker_arm_spec.py:32–59,72,107`), #47 diameter and
its default band (`_hole_spec.py:82,104`, `title_block.yaml:66`), position
Ø0.20 to A|B (`rocker_arm_spec.py:124`), through-ness
(`rocker_arm_notes.py:60`), the datum scheme (`draw_rocker_arm.py:447–548`),
general tolerances (`title_block.yaml:19–27`), deburr limit
(`title_block.yaml:43–45`). It cannot source: a profile tolerance, the
built-up permission (no drawing note exists; `construction` defaults to
`one_piece`), and STEP face names until the export change below. Those are
`unknown` entries and `?` lines.

**Why not PMI in the STEP.** Semantic PMI needs AP242, and in SolidWorks that
export is the MBD add-in only (`IModelDocExtension.PublishSTEP242File2`,
`swPublishStep242_MBDLicenseNotAvailable`); the 2026 help says MBD "is not
part of any role" and needs a stand-alone licence, and the R2026x Makers
seat has no MBD add-in registered. Even licensed, AP242 carries DimXpert
annotations, and harmonic-analyzer deliberately authors plain gtols
(`_part_pmi.py`) with every size on the 2D drawing, so the export would hold
a few GD&T frames and no dimensions. The spec scripts are the authority; a
generated `features.toml` is the lossless route.

**What the STEP should carry instead: face ids, as sets.** AP214 with
`swStepExportFaceEdgeProps` (no MBD) names every face. A feature is a face
*set*, not one face: the v38 `rocker-arm.STEP` already holds the pivot bore
as two Ø6.5 cylinder patches of equal area (faces 1 and 16). The generator
must resolve each spec feature to its native SolidWorks faces (the
`CylinderFace`/`PlanarFace` matcher `_part_pmi.py:223–259` already uses) and
emit the exported names of all of them, bound to that STEP's digest, failing
loud on ambiguity. Tracked as a harmonic-analyzer issue (§8, M3).

### 3.3 `inventory.toml` — the shop (user-supplied; sample in `examples/inventory/`)

Machines with ranges and (when measured) envelopes; holders with gauge
length; tools by short id with diameter, flutes, flute length, OAL, shank,
material, point angle for drills, and an optional `chart`; gauges; fixtures
with the dimensions the rules read (vise: jaw width, opening, jaw height
above the bed; parallels: heights; collet set: sizes; chuck: range; dividing
head: `worm_ratio`, `direct_index.positions`, `plate_holes` per plate —
the sample's BS-0 carries all three, circles `verify = true`). A value copied from a vendor page is
`verify = true` and anything that depends on it is a `?` on the sheet, never
a silent pass. The sample inventory already carries the PM 6 in vise
(`jaw_height_in = 1.825`, `opening_in = 6`) and the PM-30MV envelope
(`travel_in`, `spindle_to_table_max_in`), all `verify = true`.

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
| headroom: bed-to-table height + parallels + stock height (`top_z − bottom_z` of the supported stock, never a coordinate) + tool projection + holder gauge length + 25 mm insertion ≤ spindle-to-table at full quill retract; jaw height is a separate obstruction check against the tool path, not a layer in the stack; part + fixture ≤ travel | inventory (vise bed height and jaw height, parallels, tool OAL, holder gauge length, machine envelope — `verify` → `?`), plan.stock_state, plan.stock section | M1 | "Vise bed height not measured." |
| datum consistency: a feature toleranced to a datum cut in another setup needs tolerance ≥ `refixture_budget_mm` or a `transfer` indicating that datum | features.position_datums, plan.setups (which op cuts which feature), policy.numbers | M1 | "Rod hole is Ø0.20 to A but S2 re-chucks without indicating the bore; budget 0.05." |
| turned profile monotone from the chuck unless a grooving op | plan.ops (lathe), features (diameters along Z) | M2 | "Ø8 groove at Z−30 needs a grooving tool." |
| stick-out: declared stick-out ≤ `stickout_ld_max`·D unless tailstock/steady listed; D is the smallest finished diameter in the unsupported length, from feature diameters along setup Z, not the bar held in the jaws. Unknown exposed profile remains unresolved | plan.setups.hold.stickout_mm, features (diameters along Z), policy.numbers, inventory | M2 | "Ø6 × 40 past the chuck: add the tailstock centre." |

### 4.2 Setup geometry (on the B-rep — needs the kernel)

| rule | inputs | tier | on the sheet |
|---|---|---|---|
| accessibility: for each face an op claims, sample points; at each, stand the op's **tool cylinder** (radius, flute length) and its holder cylinder (gauge dia, gauge length) with the tool tip at the sample's Z and the tool axis offset from the sample by the cutter radius along the in-plane (XY) component of the face's outward normal — a horizontal floor sample gets no XY offset, since a cutter stands on a floor rather than beside it (so the cylinder touches a wall rather than sitting in it, and does not float a radius above a floor); intersect with (part − the op's own region: material within r of its claimed faces, and around each sharp concave edge shared by two claimed faces the r-cylinder minus the open-corner wedge) ∪ fixture solids; any hit = that prescribed pose is occluded, not that no path reaches the face. A zero-radius ray misses jaw-adjacent faces (measured, §6) and a cylinder centred on the sample hits the part itself on a side face, which is why the offset exists | features.faces, plan.ops (tool, holder), inventory.tools/holders, fixture solids from inventory dims + plan.hold | M4 | "Rail top within 4.8 mm of the rear jaw is unreachable with the 3/8 EM in S3." |
| reach: floor depth below the face the tool enters ≤ flute length, else ≤ OAL with the holder cylinder clear of walls | features.faces, inventory.tools (flute_len, OAL, holder dia) | M4 | "Pocket floor is 28 mm down; 3/8 EM has 19 mm of flute." |
| internal corner radius: concave edges ⟂ tool axis between faces one op claims: r ≥ r_tool | features.faces, plan.ops.tool | M4 | "Slot corners are sharp; a 1/4 EM leaves R3.2." |
| coverage: ⋃ faces claimed by ops ∪ faces declared as-stock = all faces | features.faces, plan.ops, plan.stock.as_is_faces | M4 | "Face 23 (the ear's back) is machined by no op." |
| finish coverage: every `finish_ra` face is claimed by a finishing op | features.finish_ra/faces, plan.ops | M4 | "Ra 1.6 on the bore; no op touches it." |

### 4.3 Workholding (geometry + inventory — needs the kernel for the solids)

| rule | inputs | tier | on the sheet |
|---|---|---|---|
| vise: gripped faces are a parallel pair; width ≤ opening; grip ≥ `grip_mm` on both jaws; no claimed face inside a jaw solid; parallels exist | plan.hold, inventory.fixtures.vise (jaw_height, opening, width), parallels, STEP | M4 | "Strap is 2.5 mm under the jaw with a 4 mm floor; use the fixture plate." |
| collet/chuck: stock Ø in the set or range; stick-out (4.1) | plan.hold, inventory | M2 | "No ER collet set confirmed." |
| thin wall under clamp: wall thickness inside the grip zone < `thin_wall_floor_mm` ⇒ `hold.method` must name soft jaws / mandrel / tape / wax | STEP thickness map, plan.hold, policy.numbers | M4 | "1.2 mm wall under the jaw; name soft jaws or a mandrel." |
| indexing: for `hold.index = { fixture, angle_deg, positions }` and the feature's `angle_tol_deg` (default: the general angular class): prefer an **exact** representation (direct plate step, or a circle `h` with `angle_deg·R·h/360` an integer, R = `worm_ratio`); otherwise the nearest, and check every position against `angle_tol_deg`. Closure is checked **only for a full pattern**, `positions ≥ 2` with `angle_deg` omitted (step exactly 360/positions; positions × actual step vs 360·k). An authored `angle_deg` with `positions ≥ 2` is an open pattern: every landing is checked, no closure. `positions = 1` is one angular setting without closure; the sheet prints plate, circle, turns and hole *spaces* | plan.hold.index, features.angle_tol_deg / general_tolerances.angular_deg, inventory dividing_head (`worm_ratio`, `direct_index`, `plate_holes`) | M2 | "51.43° × 7: plate B, circle 21, 5 turns + 15 spaces (exact); plate circles not confirmed (?)" |
| tiny parts: part-off last below the collet minimum; profile below footprint threshold declares tabs or a plate | plan.ops, inventory, policy | deferred | — |

### 4.4 Physics proxies (`!` lines only; policy may promote)

| rule | inputs | tier | on the sheet |
|---|---|---|---|
| turning deflection: δ = F·L³/(3EI) (cantilever) or /(48EI) (supported), F = K_c·a_p·f, K_c and E from `cutting-data.[[material]]` | plan.hold.stickout_mm, plan.ops (DOC, feed), features.dia, cutting-data.material | M2 | "Expected deflection 0.04 against ±0.1; take the last pass at 0.2." |
| engagement: only milling cutters (endmill families) on cutting operations with an authored DOC; tool projection from the holder (inventory `projection_mm` per tool+holder, else OAL − holder grip) / D ≤ 4 else halve DOC. Drills, reamers, taps and lathe tools are not applicable | inventory.tools (kind, OAL), inventory.holders (grip_mm), plan.ops (holder, DOC) | M2 | "3/8 EM at 4.5×D; halve the DOC or use the 1/2 holder." |
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

prechips tools [--inventory <toml>] [<query>]
    The inventory as prechips resolved it: ids, sizes in both units,
    holder chain, what is verify = true. With a query ("reamer 6.5",
    "R8") the candidates the sizing rule would consider and why each
    passes or fails.

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

Consequences, now in the rules: accessibility uses the tool cylinder offset
by its radius from the face, plus the holder cylinder, against (part −
the claimed feature) ∪ fixture — the round-2 script intersected the
cylinder with the jaws only, at a fixed 40 mm height, with no holder, so it
proved jaw proximity and nothing more (§4.2); features carry face *sets*
(§3.2); face names still need the consumer's `swStepExportFaceEdgeProps`
export and a tested mapping (§3.2, §8 M3) — order stability across exports
is observed once, not relied on. Not yet tested, and required before any
§4.2/4.3 verdict ships: the offset-cylinder predicate against a part boss
(must occlude) and against the claimed face's own side wall (must not),
holder cylinders against real jaw geometry, booleans on the filleted parts
(`summing-lever`), the thin-wall thickness map. Those are M4's first
fixtures. Kernel scripts and runs: `C:/src/dt-logs/prechips-spike/` (not
committed; they become `prechips/kernel/freecad_job.py` and its tests in
M4).

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
   **Observed local acceptance after PR #6 review corrections:** Ruff check and
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
   sourced K_c/E and a sourced BASIC-angle landing allowance, printed traveler/operator
   rehearsal, independent hand oracle, live farm telemetry and M3/M4 geometry
   binding. Unknown inputs remain `?`, not a numerical machining approval.
3. **M3 — consumer export.** harmonic-analyzer issue (filed with this rev):
   `cad/scripts/export_features.py` emitting `features.toml` beside the
   STEP as a complete manifest with provenance; `swStepExportFaceEdgeProps`
   on in `export_models.py`; a tested spec-feature → exported-face-set
   mapping bound to the STEP digest, failing on ambiguity; a drawing-note
   contract for `construction`; `check:traveler_<stem>` doit task under
   `cad/process/`. Replaces the hand-written manifests.
4. **M4 — geometry and workholding local deliverable completed** (§4.2–4.3).
   The seven rules
   (`accessibility`, `reach`, `internal_corner_radius`, `coverage`,
   `finish_coverage`, `vise`, `thin_wall_under_clamp`) are registered and run
   on one `freecadcmd.exe` job per check/traveler, memoized per bundle and
   cached locally by STEP digest + canonical job + engine source + kernel
   binary identity; a missing kernel is one `?` sentence on the console and
   exit 4, a kernel failure `✗`. Feature `faces` are matched by the referenced
   `ADVANCED_FACE`'s own surface kind/area/bbox against the imported solid,
   never by import ordinal; a missing or ambiguous reference is a mapping
   error. Fixture solids come only from a vise's explicit `jaw_height`,
   `jaw_width`, `jaw_depth` (new inventory field, never synthesized) and
   `opening`, the parallels' `height` (and `length` / `width` for drawn
   parallels) and the plan's `fixed_jaw` / `jaws_along` / `grip_mm` /
   `jaw_above_parallels_mm`, with optional authored `jaw_center_along_mm`
   and `parallels_centres_mm`; without them the render is a conservative
   certain-plus-possible jaw envelope with named debts, never a guessed
   pose, and only exact jaws plus exact parallels count as a modeled
   fixture. Other holding kinds
   have no solid (`vise` not applicable, `thin_wall_under_clamp`
   unsupported, accessibility unresolved on lathe setups). `traveler` writes
   a deterministic `setup-S<n>.png` rasterized from the kernel tessellation
   and binds it into the report hash; a part-only picture from an unresolved
   fixture is labelled as such on the sheet. `rules_version` is `m4-rev6`.
   Three reference bundles keep no STEP bytes; `examples/rocker-arm` binds
   the consumer's labelled export (delivered under
   `C:/src/dt-logs/features-bundles/rocker_arm/`, SHA-256 `19070131…`, kept
   byte-for-byte with `.gitattributes -text`; `HAF_<FEATURE>__P<nn>` labels,
   periodic surfaces split into patches under one label) with each
   feature's `faces` taken from that export, and the export's extra
   features without a manifest counterpart left unclaimed by design. The
   v38 spike export (`f2408c33…`, `NONE` labels) was the initial
   discriminator and has been cut over in both the production bundle and
   `examples/geometry/rocker-jaw-occluded`. All reference bundles keep a
   `verify = true` vise without
   `jaw_depth` and an unknown `thin_wall_floor_mm`, so their setup-level
   geometry rows (`vise`, `thin_wall_under_clamp`, fixture-dependent
   accessibility) are `?`; the discriminating fixtures of §6 live under `examples/geometry/`
   (its README and frozen `expected/report.json` files carry exits
   2 / 2 / 0 / 2 / 2 for rocker-jaw-occluded, pocket-reach, long-reach,
   sharp-corner and unclaimed-face with byte-identical repeat runs recorded by
   the fixture author; not re-observed here). **Observed by the integrating
   agent (scoped, pre-gate):** the five pilot candidates regenerated under
   `m4-rev6` keep exits 4 / 2 / 2 / 4 / 2. The labelled-export rocker
   (`examples/rocker-arm`, `19070131…`) regenerated with `traveler` twice:
   exit 2 both times with all five output files byte-identical, the only
   errors the three pre-existing tool/fixture absences; its frozen report
   shows the kernel measuring the bound faces (three `internal_corner_radius`
   passes, one `finish_coverage` pass) while fixture-dependent rows stay
   `?` on the `verify = true` vise, `coverage` is `?` because the stock's
   as-stock faces are unknown, and all three setup renders are part-only
   with `jaws absent` debts. The kernel engine's own suite
   (`tests/test_kernel_geometry.py`, 28 tests, FreeCAD required) passed for
   the engine author, covering every-face mapping of all three labelled
   consumer bundles with periodic splits, rejection of ordinal mapping under
   a reversed `CLOSED_SHELL`, boss/own-wall, the air-wedge pin case, holder
   vs jaws, the real 93-face summing-lever booleans, rotated-puck grip and
   thin wall. For the geometry fixtures the
   agent opened `pocket-reach/expected/long-reach/setup-S1.png` and the
   browser-served traveler: grey pocket part, full brown jaws, green
   parallels, 640 × 480, complete-scene caption. Earlier: `check` on
   `pivot-shaft` with `FREECAD_CMD` naming a nonexistent executable exited 4
   with all seven geometry families unknown, exactly one `? FreeCAD kernel
   unavailable` console line and empty stdout; `tests/test_kernel_outputs.py`
   (3) and the telemetry kernel-absence test (1) passed in isolation.
   **Project-wide acceptance observed:** `uv run ruff check . && uv run ruff
   format --check . && uv run pytest -q && uv run python
   scripts/validate_examples.py` exited 0; 700 tests passed and all 23 TOML
   fixture inputs plus their frozen outputs validated, with pilot exits
   4 / 2 / 2 / 4 / 2 and geometry exits 2 / 2 / 0 / 2 / 2.
   The cone comparison also passed with default and forced-absent kernels
   (2 scoped cases); all seven original example cases passed with
   `FREECAD_CMD` naming a nonexistent executable, preserving deterministic
   unknown geometry and candidate exit precedence without assuming that
   kernel-absent bytes equal the installed-kernel goldens.
   **Outside this M4 acceptance:** M3 consumer-side live integration and
   farm/trace rehearsal; measured production vise/parallel dimensions and
   a sourced thin-wall floor; and physical operator/setup checks. None is
   certified by the synthetic fixtures or by this local gate.
   The rules remain sampled B-rep screens, not toolpath simulation or a
   certification that the shop's setup matches the plan.
5. **M5 — measured inventory**: spindle stack, travel limits, holder gauge
   lengths; envelope checks leave `?`.

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
