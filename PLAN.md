# prechips — plan (rev 5)

> Checks before chips. prechips turns a part plus a short process plan into a
> **validated traveler a machinist can work from**: one page per setup saying
> how to hold it, where zero is, what the DRO should read for each feature,
> which tool, what speed and feed to start at, and what to measure. Every
> setup is validated for feasibility against the current shop inventory, the
> machines' operating ranges, the setup geometry, the workholding and the
> physics of the cut. What the checker found goes at the top of the sheet in
> plain words; everything else it computed goes to a machine-readable report
> no human has to read.

Status: plan only. Rev 5, 2026-10-03. Rev 1 was traveler-first but promised
geometric proofs it could not deliver. Revs 2–3 absorbed two adversarial
reviews and became correct but unusable: a 100 KB traveler of config ids,
hashes and 15-decimal numbers. Rev 4 restored the purpose and the rule
catalogue. Rev 5 folds the third adversarial round: the sheet now carries
every decision the machinist would otherwise have to invent, every rule
names where its inputs come from, and the kernel spike is reported for what
it measured.

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

Nothing on the sheet needs a computer to interpret. Numbers carry the
drawing's precision (0.01 mm or 0.001 in), never more.

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
  [render: part in vise, isometric, zero marked, DRO axes drawn]
  Fixed jaw: rear (+Y).  Stop: against the left end of the fixed jaw.
  Hold: 10 mm of both rails in the jaws, 3 mm of jaw above the parallels;
        strap sits on the parallels. Tighten by hand plus a quarter turn.
  Clear: 6.5 mm from the jaw top to the hub top; 3/8 EM holder clears by 4.
  Coolant: WD-40 brushed on, drilling and reaming.  Deburr: 0.2 max, file.

  DRO ZERO  (frame A = bottom face / left end / front edge, mm, ABS,
             X+ right, Y+ away from you, Z+ up — set in EL400 before S1)
    X  touch left end with 0.200 in finder from −X          → ABS, type −2.54
    Y  touch front edge, finder from −Y                      → ABS, type −2.54
    Z  0.05 paper on top face, 1/2 in EM (op 10)             → ABS, type  9.58
    Check move: jog +X 10.00 and touch the left end again from −X: DRO must
    read +7.46. A reading of −12.54 means X counts backwards — stop, fix the
    axis direction in the EL400, redo zero.
    Each tool: touch the top face with paper again, type 9.58 before its op.

  COORDINATES (mm, frame A, cutter centre)
    feature        X       Y      Z          note
    pivot bore    25.40   12.70   thru       Ø6.50 +0.03/0; drill to −2.0
    rod hole      85.12   18.23   thru       #47 (2.00 mm); drill to −1.5
    hub OD        25.40   12.70   0 → 9.53   Ø14.00 ±0.1; cutter R 4.76 outside

  OPERATIONS
    op  do        feature     tool / holder          rpm  feed       depth        dir   check
    10  face      top         1/2 4-fl EM, R8 1/2    700  140 mm/min 0.5          conv  —
    20  spot      pivot bore  #2 CD, R8 1/4          2000 hand       2.0          —     —
    30  drill     pivot bore  6.2 mm, R8 chuck       1400 hand       thru −2.0    —     —
    40  ream      pivot bore  6.5 H7, R8 1/4          450 hand       thru −2.0    —     6.50 go / 6.53 no-go
    50  spot+drl  rod hole    #2 CD, #47, R8 chuck   2000 hand       thru −1.5    —     2.00 pin
    60  profile   hub OD      3/8 4-fl EM, R8 3/8     900  180 mm/min 9.5, 2 pass climb 14.00 ±0.1 caliper
       60: rough to Ø14.6 then finish Ø14.0; DRO shows cutter centre at
       25.40 / 12.70 ± 11.76 on the four quadrants; walk the arc in 10° steps.
    70  release   rails       —                      —    —          —            —     —
       70: loosen, lift the part onto the fixture plate before cutting the
       rails free (S4). Do not cut the rails in the vise.
  RPM/feed: HSS, 1018 CRS, 90 sfm; 0.05 mm/tooth (Machinery's Handbook 31,
  Table 1 p. 1023; cutting-data.toml rev 1). Starting points, not limits.

  Sign off: ________  first article: ________  pivot bore reads ______
                                            prechips 0.1 · report 7f3a9c2e
```

Rules for the sheet:

- **Plain words, drawing precision.** A finding is one or two sentences with
  the number that matters; no rule ids, no hashes, no file paths. The three
  glyphs are `✗` blocked, `!` warning, `?` could not check.
- **Everything the machinist would otherwise invent is on the page.** Fixed
  jaw side, stop, grip, clamp method, clearance under the holder, coolant,
  deburr limit, cut direction, breakthrough depth for through holes
  (point length + exit allowance, computed from the drill angle), per-tool Z
  touch, cutter-centre coordinates for a manual contour, the step that
  releases a held feature. Each comes from a `plan.toml` field (§3.1) or a
  rule's computation; none is free text the generator makes up. A field the
  author left blank is a `?` line, not a blank cell.
- **The zero recipe proves its own sign.** After zeroing, one check move
  with the expected reading and the reading that means the axis counts
  backwards. The EL400's axis directions, ABS/INC mode and radius/diameter
  mode are set once per part in S1 and stated on every sheet.
- **Speeds and feeds appear on the sheet**, computed from a shipped,
  versioned `cutting-data.toml` (§3.5) and clamped to the machine's range,
  rounded to the nearest 50 rpm, labelled as starting points. Source order:
  the tool vendor's chart when the inventory entry names one
  (`chart = "<url or doc>"`), otherwise Machinery's Handbook 31. The
  citation is one line per setup, not per cell.
- **Units: coordinates in the drawing's unit, tool sizes as bought.** The
  harmonic-analyzer drawings are mm; the DRO and the tooling are inch. Both
  appear only where they meet, on the sizing line ("0.2510 in (6.375 mm)").
- **Feature names, not balloon numbers.** The sheet says `pivot bore`, never
  "bore ③": balloon numbers are not stable across drawing revisions.
- **The DRO block is a recipe, not a file.** It says which edge, which
  finder, which direction, what to type. It is written for the EL400's actual
  functions (ABS/INC, radius/diameter, preset, bolt-circle/linear patterns);
  prechips does not emit EL400 files until the emulator has an import path.
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
dimension overrides it (`precision = 3`), which is how the title block's
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
mode = "abs"
radius_mode = true
axis_positive = { x = "right", y = "away", z = "up" }

[[setups]]
id = "S3"
machine = "pm-30mv"
frame = "A"                               # named in features.toml
coolant = "wd40_brush"
deburr_mm = 0.2
stock_in = "S2"                           # what this setup starts from

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
x = { edge = "left_end", from = "-x", tool = "edge-finder-0.200" }
y = { edge = "front",    from = "-y", tool = "edge-finder-0.200" }
z = { face = "top",      method = "paper", paper_mm = 0.05, tool = "em-1/2-4fl" }
check = { axis = "x", jog_mm = 10.0 }

[[setups.ops]]
op = 10
do = "face"
feature = "top"
tool = "em-1/2-4fl"
depth_mm = 0.5
direction = "conventional"

[[setups.ops]]
op = 20
do = "spot"
feature = "pivot_bore"
tool = "cd-2"
depth_mm = 2.0

[[setups.ops]]
op = 30
do = "drill"
feature = "pivot_bore"
tool = "drill-6.2mm"
exit_mm = 2.0                             # past the exit face, after point length

[[setups.ops]]
op = 40
do = "ream"
feature = "pivot_bore"
tool = "reamer-6.5-h7"
exit_mm = 2.0
check = "pin-gauge"

[[setups.ops]]
op = 50
do = "drill"
feature = "rod_hole"
tool = "drill-47"
exit_mm = 1.5

[[setups.ops]]
op = 60
do = "profile"
feature = "hub_od"
tool = "em-3/8-4fl"
depth_mm = 9.5
direction = "climb"
rough_allowance_mm = 0.3
contour = "quadrants_10deg"
check = "caliper"

[[setups.ops]]
op = 70
do = "release"
feature = "rails"
note = "lift onto the fixture plate before S4 cuts the rails free"
```

The author writes the route and every holding/cutting decision above.
prechips fills in RPM/feed, point-length and breakthrough depths,
cutter-centre coordinates, holder clearance, and resolves tool and fixture
ids against the shop. Tool ids are short and human (`em-3/8-4fl`), set by the
inventory. A later setup declares how it re-finds zero
(`[setups.zero] transfer = { from = "S1", indicate = "pivot_bore" }`).

### 3.2 `features.toml` — the drawing, in numbers (generated by the CAD side)

Exported beside the STEP by the consumer (harmonic-analyzer: from
`rocker_arm_spec.py`, `_hole_spec.py`, `rocker_arm_notes.py`,
`draw_rocker_arm.py`'s datum scheme and `title_block.yaml`'s general
tolerances). prechips never reads PMI from the STEP and never invents a
tolerance. It is a **complete requirement manifest**: every toleranced
feature the drawing carries is listed, and a value the generator cannot
source is an explicit `unknown` entry, never an omission — an omitted feature
would silently pass the inspection-coverage rule.

```toml
part = "rocker-arm"
units = "mm"
precision = 2                              # .XX general class; a feature may override
step_sha256 = "…"                          # the STEP this manifest was exported with
construction = "one_piece"                 # or "built_up_permitted" (drawing note)

[frames.model]
note = "SolidWorks part origin: pivot axis, mid-thickness"

[frames.A]                                 # numeric, in model coordinates
origin = [-146.25, 0.0, -3.53]
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
at = [146.25, 5.53]
drill = "#47"
dia = [2.00, 2.10]                         # _hole_spec default +0.10/0
thru = true
position_dia = 0.20
precision = 3                              # .XXX: this hole's position class, not the sheet's
position_datums = ["A", "B"]
faces = ["Face9"]

[features.hub_od]
kind = "boss"
at = [0.0, 8.0]
dia = [13.90, 14.10]
height = 9.53
faces = ["Face4", "Face5"]

[features.top]
kind = "face"
faces = ["Face15"]
finish_ra = 1.6

[features.profile_outer]
kind = "profile"
unknown = ["tolerance"]                    # drawing carries no profile tolerance
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
head: plate hole counts). A value copied from a vendor page is
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

Subjects are enumerated from `features.toml` and `plan.toml`, not from what
the plan happens to mention: a required rule with no subject in a non-empty
manifest is `unknown`, and a plan with no setups or no ops, or a manifest
with no features, is rejected before any rule runs. `unsupported` (prechips
has no rule for this feature kind yet) and `not_applicable` (the rule has
nothing to say about this subject) are distinct statuses; only
`not_applicable` is a pass. Lives with the inventory, not in the plan, so a
plan cannot waive it. The shipped default requires the first seven rules on
`*`.

### 3.5 `cutting-data.toml` — shipped with prechips, versioned

The only numeric table prechips ships. Key:
`(material_class, tool_material, operation, diameter_range)` →
`sfm`, `chip_load_mm_per_tooth`, `cite`. `material_class` maps from the
inventory/plan material string through a small alias table (`"1018 CRS"` →
`low_carbon_steel`). RPM = 12·sfm / (π·D_in), clamped to the machine, rounded
to 50; feed = rpm·flutes·chip_load. An inventory tool with `chart = …`
overrides the row with its own `sfm`/`chip_load`, citing the chart. A
missing row is a `?` line, never a guessed number. Pilot content: HSS and
carbide × low-carbon steel, 360 brass, 6061, O1 annealed × face/profile/
drill/ream/tap, from Machinery's Handbook 31 Table 1, p. 1023 ff. (to be
transcribed and page-cited at M1).

## 4. What the checker validates (the rule catalogue)

Every rule is deterministic: same inputs, same verdict. Each produces `pass`,
`fail` (`block` or `warn`), `unknown` (an input missing or `verify = true`),
`unsupported` or `not_applicable` per `(rule, subject)`; the sheet shows only
fails and unknowns, as a sentence. Exit: 2 on any block, else 4 on a required
unknown or unsupported, else 0 — so the consumer can wrap it as a doit gate.
Every numeric threshold carries a `cite`; an uncited number is a lint error in
this repo.

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
| breakthrough / blind depth: drill tip travel = thickness + point (from `point_angle`, D) + `exit_mm`; blind: depth + point ≤ `features.depth`; tap flute ≥ thread depth | plan.ops.exit_mm/depth_mm, features.thru/depth, material.thickness, inventory.tools.point_angle/flute_len | M1 | "Drill to 12.5 in 9.5 stock breaks through." / fills the depth column |
| speeds/feeds from cutting-data, clamped, rounded | plan.ops, inventory.tools (material, flutes, chart), machine rpm range, cutting-data | M1 | fills the columns; "? no row for O1 hardened" |
| zero recipe: finder radius and paper applied; per-axis sign from `dro.axis_positive` and frame axes; the check-move reading printed | plan.dro, plan.setups.zero, features.frames, inventory.tools (finder dia) | M1 | "Y zero direction contradicts frame A." / fills the DRO block |
| coordinates: feature centre → setup frame → cutter centre (tool radius for profiles) | features.at/frames, plan.setups.frame, inventory.tools.dia | M1 | silent when right |
| every toleranced feature has a check whose gauge exists | features (dia/position/finish present), plan.ops.check, inventory.gauges | M1 | "Hub OD ±0.1 has no measurement." |
| hold fields complete: fixed jaw, stop, grip, clamp, coolant, deburr, direction per cutting op | plan.setups.hold/coolant/deburr_mm, plan.ops.direction | M1 | "S3 does not say which jaw is fixed." |
| headroom: parallels + part height + tool + holder gauge length ≤ spindle-to-table; part + fixture ≤ travel | inventory (vise jaw height, parallels, holder gauge, machine envelope — `verify` → `?`), features bbox (from STEP, kernel) or plan.stock | M1 (bbox from stock), M4 (from STEP) | "Vise bed height not measured." |
| datum consistency: a feature toleranced to a datum cut in another setup needs tolerance ≥ `refixture_budget_mm` or a `transfer` indicating that datum | features.position_datums, plan.setups (which op cuts which feature), policy.numbers | M1 | "Rod hole is Ø0.20 to A but S2 re-chucks without indicating the bore; budget 0.05." |
| turned profile monotone from the chuck unless a grooving op | plan.ops (lathe), features (diameters along Z) | M2 | "Ø8 groove at Z−30 needs a grooving tool." |
| stick-out: declared stick-out ≤ `stickout_ld_max`·D unless tailstock/steady listed | plan.setups.hold.stickout_mm, policy.numbers, inventory | M2 | "Ø6 × 40 past the chuck: add the tailstock centre." |

### 4.2 Setup geometry (on the B-rep — needs the kernel)

| rule | inputs | tier | on the sheet |
|---|---|---|---|
| accessibility: for each face an op claims, sample points, stand the op's **tool cylinder** (radius, flute length) on each, intersect with part ∪ fixture solids; any hit = occluded (a zero-radius ray misses jaw-adjacent faces — measured, §6) | features.faces, plan.ops, inventory.tools, fixture solids from inventory dims + plan.hold | M4 | "Rail top within 4.8 mm of the rear jaw is unreachable with the 3/8 EM in S3." |
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
| indexing: angle representable on the named plate/dial within the feature's angular tolerance | plan.hold.index, inventory.fixtures.dividing_head, features.angle_tol | deferred | — |
| tiny parts: part-off last below the collet minimum; profile below footprint threshold declares tabs or a plate | plan.ops, inventory, policy | deferred | — |

### 4.4 Physics proxies (`!` lines only; policy may promote)

| rule | inputs | tier | on the sheet |
|---|---|---|---|
| turning deflection: δ = F·L³/(3EI) (cantilever) or /(48EI) (supported), F = K_c·a_p·f with K_c from cutting-data per material class | plan.hold.stickout_mm, plan.ops (DOC, feed), features.dia, cutting-data.kc, material E | M2 | "Expected deflection 0.04 against ±0.1; take the last pass at 0.2." |
| engagement: holder stick-out / D ≤ 4 else halve DOC | inventory.tools (stickout), plan.ops | M2 | "3/8 EM at 4.5×D; halve the DOC or use the 1/2 holder." |
| tool life | needs a calibrated life table nobody ships | deferred | — |

### 4.5 Stock-form comparison (authored candidates, counted by prechips)

The author lists candidate stock forms as alternative plans; prechips emits
setups, waste ratio, fixtures required and the rules each candidate trips,
side by side. It does not pick a winner, and a built-up candidate is marked
`✗ drawing permits one-piece only` unless `features.construction =
"built_up_permitted"`. First case: `cone-pivot-post`. Tier: M2.

### 4.6 Non-deterministic residue, named

Chatter, clamp deformation, whip, tiny-part gripping, cutter wear. Handled by
the proxies and fixturing rules above. No rule in this project claims to
replace the first-article cut.

## 5. Outputs, binding and readiness

- `traveler.html` — §2. The product.
- `report.json` — every `(rule, subject)` with status, numbers and citation;
  sorted, canonical, hashed (hash excludes itself); carries the SHA-256 of
  each input file (`plan`, `features`, `inventory`, `shop-policy`,
  `cutting-data`) and the STEP digest the manifest names. For doit stamps
  and for the informed machinist review, never for humans at the bench.
- `setup-S<n>.png` — the fixture render, once M4 exists; until then the
  author's sketch (`plan.setups.sketch = "S3.png"`) or the "Hold" text.

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

CLI: `prechips traveler <plan.toml> [--approval …]` (writes both; exit per
§4), `prechips tools` (lists the inventory as prechips resolved it),
`prechips compare <plan.toml>...` (§4.5).

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

Consequences, now in the rules: accessibility uses the tool cylinder, not a
ray (§4.2); features carry face *sets* (§3.2); face names still need the
consumer's `swStepExportFaceEdgeProps` export and a tested mapping (§3.2,
§8 M3) — order stability across exports is observed once, not relied on.
Not yet tested, and required before any §4.2/4.3 verdict ships: booleans on
the filleted parts (`summing-lever`), the thin-wall thickness map, holder
cylinders against real jaw geometry. Those are M4's first fixtures. Kernel
scripts and runs: `C:/src/dt-logs/prechips-spike/` (not committed; they
become `prechips/kernel/freecad_job.py` and its tests in M4).

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
1. **M1 — the sheet, for one `rocker-arm` finishing setup** on a prepared
   blank (S3 of the rev-3 fixture; S1/S2/S4 are out of scope and the sheet
   says so). `plan.toml`, a hand-written `features.toml` mirroring what the
   generator will emit (real values and real unknowns from the sources in
   §3.2), inventory, policy, `cutting-data.toml` rev 1 → `traveler.html` +
   `report.json`. All §4.1 rows marked M1. **Acceptance test
   `rocker-paper-rehearsal`:** a frozen bundle → CLI → printed setup page;
   someone who has not read the plan dry-runs the setup on the PM-30MV from
   the page and the drawing alone (hold, zero + check move, tool changes,
   depths, inspections) and writes down every instruction they had to
   invent — the list must be empty. Controls, each a committed bad plan:
   removing the reamer or chuck from the inventory blocks; flipping
   `dro.axis_positive.x` changes the printed check-move reading; editing
   `features.toml` after approval prints `PLANNED` with the input named;
   an empty ops list is rejected; the report is byte-repeatable.
2. **M2 — `pivot-shaft` and `pivot-bracket`** (lathe frame conventions: Z
   along the spindle, X as diameter; `transfer` zero across setups; the M2
   rows; `prechips compare` on `cone-pivot-post`).
3. **M3 — consumer export.** harmonic-analyzer issue (filed with this rev):
   `cad/scripts/export_features.py` emitting `features.toml` beside the
   STEP as a complete manifest with provenance; `swStepExportFaceEdgeProps`
   on in `export_models.py`; a tested spec-feature → exported-face-set
   mapping bound to the STEP digest, failing on ambiguity; a drawing-note
   contract for `construction`; `check:traveler_<stem>` doit task under
   `cad/process/`. Replaces the hand-written manifests.
4. **M4 — geometry and workholding** (§4.2–4.3) on the kernel, starting with
   the discriminating fixtures §6 lists; fixture renders on the sheet.
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

Open: who authors the rocker finishing fixture and the rail-release method
(the plan author, as an S4 with its own sheet — before M1 ships the S3
sheet names it); which EL400 revision defines the pickup contract (pin
`pedropaulovc/el400` at a commit in `inventory.toml` `controllers.el400.rev`);
where the approval record lives (`approvals.toml` beside the plan, one line
per report hash, written by hand after the first article).
