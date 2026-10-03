# prechips — plan (rev 4)

> Checks before chips. prechips turns a part plus a short process plan into a
> **validated traveler a machinist can work from**: one page per setup saying
> how to hold it, where zero is, what the DRO should read for each feature,
> which tool, what speed and feed to start at, and what to measure. Every
> setup is validated for feasibility against the current shop inventory, the
> machines' operating ranges, the setup geometry, the workholding and the
> physics of the cut. What the checker found goes at the top of the sheet in
> plain words; everything else it computed goes to a machine-readable report
> no human has to read.

Status: plan only. Rev 4, 2026-10-03. Rev 1 was traveler-first but promised
geometric proofs it could not deliver. Revs 2–3 absorbed two adversarial
reviews and became correct but unusable: a 100 KB traveler of config ids,
hashes and 15-decimal numbers. Rev 4 restores the original purpose, brings
back rev 1's full rule catalogue, and keeps the reviews' good ideas where they
cost the machinist nothing.

## 1. Who this is for

A hobby machinist (initially: one person, one shop) making 1–20 of a part on a
PM-30MV mill run by hand through a DRO (EL400 emulator over cncjs) and a manual
PM-1127VF-LB lathe. They already have the drawing. They need, per setup:

1. a picture of the part in the fixture,
2. a zero-setting recipe for the DRO,
3. a coordinate list in the DRO's own frame and units,
4. an operation list with tool, holder, RPM, feed, depth and the inspection
   that closes the feature,
5. a short "before you start" box listing what the checker could not confirm
   or found wrong.

Nothing on the sheet needs a computer to interpret. Numbers carry the
drawing's precision (0.01 mm or 0.001 in), never more.

## 2. The traveler (the product)

Letter, portrait, printable; one header page plus one page per setup; HTML
with print CSS (PDF via the browser). Sketch for `rocker-arm`, setup S3 (mill,
finish the hub and profile on a prepared blank). **Layout sketch only: the
coordinates, revision, RPMs and tool list below are placeholders, not the
part's geometry** (the real numbers live in `examples/rocker-arm/spec.yaml`
and the harmonic-analyzer build scripts; the rod hole is at ~146 mm, not 85):

```
ROCKER ARM  MHA-071  rev v21             qty 20    1018 CRS, black oxide
Traveler  2026-10-03  prechips 0.1   plan rocker-arm/plan.toml  sheet 3 of 4

BEFORE YOU START
  ✗  No 6.50 mm reamer in the shop. Nearest: 0.2510 in (6.375 mm), 0.125 mm
     under the bore's low limit. Buy a 6.5 H7 reamer or re-dimension.
  ✗  No R8 drill chuck listed; ops 60–80 drill from a collet. Confirm or add.
  !  Op 60 profiles the 2.5 mm strap with 3 mm standing above the jaws;
     expected deflection 0.04 mm against ±0.1. Take the last pass at 0.2 mm.
  ?  Vise bed-to-table height not measured — spindle clearance not checked.
  ?  Travel limits not measured — part + vise assumed inside 23 × 8.75 in.

SETUP S3 — PM-30MV, 6 in vise, jaws along X, part on 3/4 in parallels
  [render: part in vise, isometric, zero marked, DRO axes drawn]
  Locate: bottom face on parallels; left end against the fixed-jaw stop.
  Hold: ≥ 10 mm of the rails in the jaws; strap stays supported.

  DRO ZERO  (frame A = bottom face / left end / front edge, mm, ABS)
    X  touch left end with 0.200 in edge finder from −X   → set X = −2.54
    Y  touch front edge, finder from −Y                    → set Y = −2.54
    Z  paper on top face, 3/8 in end mill                  → set Z =  9.53
    EL400: ABS, mm, radius mode.  Verify: top-left corner reads 0 / 0 / 9.53.

  COORDINATES (mm, frame A)
    feature        X       Y      Z        note
    pivot bore    25.40   12.70   thru     Ø6.50 +0.03/0
    rod hole      85.12   18.23   thru     #47 drill (2.00 mm)
    hub OD         25.40   12.70   0 … 9.53  Ø14.00 ±0.1, profile cut

  OPERATIONS
    op  do          feature      tool / holder                 rpm  feed      depth     check
    10  face        top          1/2 in 4-fl EM, R8 1/2        1200 150 mm/min 0.5      —
    20  spot        pivot bore   #2 centre drill, R8 1/4       2000 hand      2.0       —
    30  drill       pivot bore   6.2 mm, R8 drill chuck        1500 hand      thru      —
    40  ream        pivot bore   6.5 H7 reamer, R8 1/4          500 hand      thru      6.50 go / 6.53 no-go
    50  spot+drill  rod hole     #2 CD, #47 drill              2500 hand      thru      2.00 pin
    60  profile     hub + strap  3/8 in 4-fl EM, R8 3/8        1800 200 mm/min 2 passes  14.00 ±0.1 caliper
  RPM/feed: HSS, 1018 CRS, 90 sfm (Machinery's Handbook 31, Table 1 p.1023),
  clamped to the PM-30MV's 50–3000 rpm. Starting points, not limits.

  Sign off: ________  first article: ________  pivot bore reads ______
```

Rules for the sheet:

- **Plain words, drawing precision.** A finding is one or two sentences with
  the number that matters; no rule ids, no hashes, no file paths. The three
  glyphs are `✗` blocked, `!` warning, `?` could not check.
- **Everything a machinist needs is on the setup page**: fixture, zero
  recipe, coordinates, ops, speeds/feeds, inspections. Nothing else.
- **Speeds and feeds appear on the sheet**, computed from a cited SFM/chip-load
  table for the material/tool pair and clamped to the machine's range, labelled
  as starting points. Source order: the tool vendor's chart when the
  inventory entry names one (`chart = "<url or doc>"`), otherwise Machinery's
  Handbook 31. The citation is one line per setup, not per cell.
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

### 3.1 `plan.toml` — short, per part

```toml
part = "rocker-arm"
drawing = { number = "MHA-071", revision = "v21" }
quantity = 20

[stock]
form = "flat_bar"
material = "1018 CRS"
section_mm = [45, 16]
length_mm = 310

[[setups]]
id = "S3"
machine = "pm-30mv"
frame = "A"                               # named in features.toml
hold = { vise = "vise-6in", jaws_along = "x", parallels = "3/4in", grip_mm = 10 }

[setups.zero]
x = { edge = "left_end", from = "-x", tool = "edge-finder-0.200" }
y = { edge = "front",    from = "-y", tool = "edge-finder-0.200" }
z = { face = "top",      method = "paper", tool = "em-3/8-4fl" }

[[setups.ops]]
op = 10
do = "face"
feature = "top"
tool = "em-1/2-4fl"

[[setups.ops]]
op = 20
do = "spot"
feature = "pivot_bore"
tool = "cd-2"

[[setups.ops]]
op = 30
do = "drill"
feature = "pivot_bore"
tool = "drill-6.2mm"

[[setups.ops]]
op = 40
do = "ream"
feature = "pivot_bore"
tool = "reamer-6.5-h7"
check = "pin-gauge"

[[setups.ops]]
op = 50
do = "drill"
feature = "rod_hole"
tool = "drill-47"

[[setups.ops]]
op = 60
do = "profile"
feature = "hub_od"
tool = "em-3/8-4fl"
passes = 2
check = "caliper"
```

The author writes the route. prechips fills in RPM/feed from tables, derives
coordinates from the feature file, and resolves tool names against the shop.
Tool ids are short and human (`em-3/8-4fl`), set by the inventory.

### 3.2 `features.toml` — the drawing, in numbers (generated by the CAD side)

Exported beside the STEP by the consumer (harmonic-analyzer: from
`rocker_arm_spec.py`, `_hole_spec.py` and the title-block defaults). prechips
never reads PMI from the STEP and never invents a tolerance. Per feature:
kind, frame, centre/axis, size with limits, through/blind depth, inspection
hint, the STEP face it is, and where on the drawing it came from:

```toml
part = "rocker-arm"
units = "mm"

[frames.A]
origin = "bottom face / left end / front edge"
note = "drawing datum scheme"

[material]
spec = "1018 CRS"
thickness = 16.0

[features.pivot_bore]
kind = "hole"
frame = "A"
at = [25.40, 12.70]
dia = [6.50, 6.53]
thru = true
face = "Face12"
zone = "B3"

[features.rod_hole]
kind = "hole"
frame = "A"
at = [85.12, 18.23]
drill = "#47"
thru = true
face = "Face19"
zone = "C2"

[features.hub_od]
kind = "boss"
frame = "A"
at = [25.40, 12.70]
dia = [13.90, 14.10]
height = 9.53
face = "Face7"
zone = "B2"

[features.top]
kind = "face"
frame = "A"
face = "Face3"
```

A feature the generator cannot source is left out, and whatever needed it
shows up on the sheet as `?`.

**Why not PMI in the STEP.** Semantic PMI needs AP242, and in SolidWorks that
export is the MBD add-in only (`IModelDocExtension.PublishSTEP242File2`,
`swPublishStep242_MBDLicenseNotAvailable`); the 2026 help says MBD "is not
part of any role" and needs a stand-alone licence, and the R2026x Makers
seat has no MBD add-in registered. Even licensed, AP242 carries DimXpert
annotations, and harmonic-analyzer deliberately authors plain gtols
(`_part_pmi.py`) with every size on the 2D drawing, so the export would hold
a few GD&T frames and no dimensions. The spec scripts are the authority; a
generated `features.toml` is the lossless route. **What the STEP should
carry instead: face/edge ids** — AP214 with `swStepExportFaceEdgeProps` (no
MBD) names every face, so the generator fills `face = "<name>"` per feature
and the kernel resolves a feature to one B-rep face by id, not by matching
geometric descriptors.

### 3.3 `inventory.toml` — the shop (user-supplied; sample in `examples/inventory/`)

Machines with ranges and (when measured) envelopes; holders; tools by short
id with diameter, flutes, flute length, OAL, shank, material; gauges;
fixtures (vise jaw width/opening/depth, parallels, collet set, chuck range,
dividing-head plates). A value copied from a vendor page is `verify = true`
and anything that depends on it is a `?` on the sheet, never a silent pass.

### 3.4 `shop-policy.toml` — what must be confirmed (user-supplied, optional)

Which checks must come back clean before the sheet drops its `PLANNED` banner.
Lives with the inventory, not in the plan, so a plan cannot waive it. Default
shipped: tool sizing, op order, blind-hole depth, spindle clearance, fit in
travel, every toleranced feature has a check.

## 4. What the checker validates (the rule catalogue)

Every rule is deterministic: same inputs, same verdict. Each produces `pass`,
`fail` (`block` or `warn`) or `unknown` (an input missing or `verify = true`)
per feature/setup; the sheet shows only fails and unknowns, as a sentence.
Exit: 2 on any block, 4 on a required unknown, else 0 — so the consumer can
wrap it as a doit gate. Every numeric threshold carries a `cite`; an uncited
number is a lint error in this repo.

Rules are grouped by what they need. 4.1 runs on the declared inputs alone
and is the whole of M1. 4.2–4.3 need the kernel (§6); until it exists they
report `?` and the sheet is still complete.

### 4.1 Plan lint (declared inputs only)

| rule | on the sheet it reads like |
|---|---|
| tool exists; holder fits the machine's spindle taper | "No R8 drill chuck listed." |
| selected finishing tool makes the size; unit mismatch reported, never converted | "Nearest reamer 6.375 mm, 0.125 under the low limit." |
| op chain per feature kind (spot→drill→ream/tap; counterbore after its hole; tap drill from the thread spec) | "Pivot bore is reamed without a drill op." |
| order: rough→finish, drill→ream/tap, face→centre-drill, part-off last | "Op 40 reams before op 30 drills." |
| blind depth: drill depth + point ≤ material; tap flute ≥ thread depth | "Drill to 12.5 in 9.5 stock breaks through." |
| RPM from the cited SFM table, clamped to the machine's range; feed/DOC within the cited table | fills the columns; "? no table entry for O1 hardened" when absent |
| part + fixture inside travel and under the spindle (needs measured inventory) | "Vise bed height not measured." |
| turned profiles monotone from the chuck end unless a grooving op exists | "Ø8 groove at Z−30 needs a grooving tool; none listed." |
| parting length within the collet-stop range | "42 mm stick-out exceeds the 5C stop's 38 mm." |
| every toleranced feature has a check | "Hub OD ±0.1 has no measurement." |
| coordinates: feature → DRO frame through the zero recipe; edge-finder radius and paper thickness applied | silent when right; "Y zero direction contradicts frame A" when wrong |
| datum/setup consistency: a setup's locating faces machined earlier or stock; a feature toleranced to a datum cut in another setup flags unless the tolerance ≥ the re-fixture budget | "Rod hole is ±0.05 to the pivot bore but cut in S2 after a re-chuck; budget 0.1." |

### 4.2 Setup geometry (exact, on the B-rep — needs the kernel)

| rule | method | on the sheet |
|---|---|---|
| accessibility | sample each face claimed machined in a setup; cast rays along −tool axis; hit on part or fixture ⇒ occluded | "Underside of the ear is behind the vise jaw in S2." |
| reach | floor depth below the setup's highest surface ≤ flute length, else ≤ OAL with a holder-clearance ray against walls | "Pocket floor is 28 mm down; 3/8 EM has 19 mm of flute." |
| internal corner radius | concave edges between walls ⟂ tool axis: r ≥ r_tool of the op's tool; r = 0 impossible unless an EDM/broach/file op is present | "Slot corners are sharp; a 1/4 EM leaves R3.2." |
| coverage | ⋃ claimed faces ∪ declared as-stock faces = all faces | "Face 23 (the ear's back) is machined by no op." |
| finish coverage | every face with a finish callout ∈ some machined set | "Ra 1.6 on the bore but op 40 is the last op touching it: reamed, OK" / "...no op touches it." |
| hole/thread table | each cylindrical feature has drill → (ream/tap); tap drill from the thread spec; blind depth ≤ flute | "M4 tap drill is 3.3; op 30 drills 3.5." |

### 4.3 Workholding (geometry + inventory — needs the kernel for the solids)

- **Vise**: gripped faces are a parallel pair; width ≤ opening; grip height
  ≥ minimum on both jaws; nothing claimed machined below the jaw top; tool
  envelope ∩ jaw solids = ∅; parallels exist in inventory.
- **Collet/chuck**: stock Ø in the collet set or chuck range; stick-out ≤ 3Ø
  unless tailstock/steady listed; finished slender section L/D vs listed
  support.
- **Dividing head / rotary**: index angle representable (plate holes / dial
  resolution) within the feature's angular tolerance.
- **Thin wall under clamp**: ray-pair thickness map; wall < policy floor
  inside the grip zone ⇒ must name an approved method (mandrel, soft jaws,
  tape, wax).
- **Tiny parts**: part-off-last ordering for anything below the collet
  minimum; profile ops below a footprint threshold must declare tabs or a
  fixture plate.

Sheet sentences: "Strap is 2.5 mm under the jaw with a 4 mm floor; use soft
jaws or the fixture plate." / "Ø6 × 40 between the chuck and nothing: add the
tailstock centre or a steady."

### 4.4 Physics proxies (cited, `!` lines — never a block unless policy says)

- **Turning/boring deflection**: δ = F·L³/(3EI) cantilever, F·L³/(48EI)
  supported; F from specific cutting force K_c·a_p·f (Sandvik / Machinery's
  Handbook); compare δ to the diameter tolerance. Sheet: "Expected deflection
  0.04 mm against ±0.1; take the last pass at 0.2 mm."
- **Tool life**: cumulative cut length per tool over the lot vs cited life.
  Sheet: "Change the #47 drill after 12 parts."
- **Engagement**: stick-out L/D ≤ 3–4 unless DOC reduced; radial engagement
  cap per strategy. Sheet: "3/8 EM at 4.5×D stick-out; halve the DOC or use
  the 1/2 holder."

### 4.5 Stock-form comparison (authored candidates, counted by prechips)

The author lists candidate stock forms (bar, plate, casting, built-up from N
pieces) as alternative plans; prechips emits setups, waste ratio, fixtures
required and the rules each candidate trips, side by side. It does not pick
a winner. First case: `cone-pivot-post` — Ø42×86 body with a Ø22 boss
standing 30 mm proud; candidates: hog from Ø75 bar, offset-turn on a
faceplate, built-up (brazed boss), outsourced casting.

### 4.6 Non-deterministic residue, named

Chatter, clamp deformation, whip, tiny-part gripping, cutter wear. Handled by
the proxies and fixturing rules above; the sheet's `PLANNED` banner stays
until a first-article cut and a logbook entry flip it. No rule in this
project claims to replace that cut.

## 5. Outputs

- `traveler.html` — §2. The product.
- `report.json` — every check with status, numbers and citation; sorted,
  canonical, hashed (hash excludes itself). For doit stamps and for the
  informed machinist review, never for humans at the bench.
- `setup-S<n>.png` — the fixture render, once the kernel exists; until then a
  placeholder box on the sheet with the "Locate / Hold" text.

CLI: `prechips traveler <plan.toml>` (writes both; exit per §4),
`prechips tools` (lists the inventory as prechips resolved it),
`prechips compare <plan.toml>...` (§4.5).

## 6. The kernel, and the spike that decides it

4.2–4.3 need a B-rep: load the STEP, resolve each `features.*.face` to one
face, cast rays, intersect fixture solids. FreeCAD's bundled OCC is the only
candidate (Fusion rejected; no OCP/CadQuery dependency), driven as a
`FreeCADCmd` subprocess that takes a JSON job and returns JSON facts. The
spike runs **before M1 is designed around its absence**, on the v38 release
STEP files:

1. `FreeCADCmd` loads `rocker-arm.STEP`, `pivot-shaft.STEP`,
   `pivot-bracket.STEP`; reports solid count, face count, bounding box.
2. Face names survive: the export carries `swStepExportFaceEdgeProps` names
   (`ADVANCED_FACE('Face12', …)`) and FreeCAD exposes them (`Part` labels or
   the raw STEP entity names).
3. One ray cast: from above the pivot bore, along −Z, first hit is that
   bore's entry face.
4. One boolean: a 6 in vise jaw pair as two boxes, `common` with the part is
   non-empty at the grip and empty elsewhere.
5. Determinism: run twice, byte-identical JSON.

Pass → §4.2/4.3 are built on it in M4. Fail on 2 → the generator cannot name
faces and the matcher from rev 1 (`PlanarFace(normal, offset)`,
`CylinderFace(axis, r)`) comes back as the fallback. Fail on 1 or 3–5 →
prechips stays declared-input only (4.1 + 4.4), which is still the whole §2
sheet with `?` on the geometry lines.

**Result (2026-10-03, FreeCAD 1.1.4 `freecadcmd.exe` via winget, v38 release
STEPs).** 1, 3, 4, 5 pass; 2 fails on the current export.

| step | rocker-arm | pivot-shaft | pivot-bracket |
|---|---|---|---|
| load: solids / faces / valid | 1 / 18 / true | 1 / 18 / true | 1 / 16 / true |
| bbox (mm) | ±146.25 × 0–29.29 × ±3.53 | Ø10 × 159.7 | 16 × 32.2 × 24.2 |
| face names | `ADVANCED_FACE('NONE', …)` ×18 | same ×18 | same ×16 |
| −Z ray from above bbox centre | hits face 10 at z = 1.25 | face 1 at z = 1.5 | face 11 at z = 3.0 |
| jaw boolean (two boxes biting 1 mm, 10 mm grip) | 148.8 mm³ in grip, 0 above | 0 at Ø6.35 body for a bbox-derived (Ø10 head) jaw; 15.8 mm³ with the jaw at the body — correct, test bug | 186.3 mm³ in grip, 0 above |
| determinism | two runs, byte-identical JSON (`a82fa638…`) | | |

The schema is `AUTOMOTIVE_DESIGN` (AP214) and every face is named `NONE`, so
the consumer must turn on `swStepExportFaceEdgeProps` (M3) before
`features.toml` can carry `face = "<name>"`; descriptor matching stays the
fallback until then. Load, bbox, ray and boolean are enough for 4.2/4.3, and
the kernel is one 80-line script, so M4 is on. Kernel script and runs:
`C:/src/dt-logs/prechips-spike/` (not committed; it becomes
`prechips/kernel/freecad_job.py` in M4).

## 7. Kept from the reviews, and why

- **Unknown is not a pass.** Unmeasured inventory shows as `?`, and a required
  `?` keeps the `PLANNED` banner and exits 4. This is the one review idea that
  changes what the machinist sees, and it should: "not checked" is useful.
- **The drawing's numbers come from a generated feature file**, not PMI, not a
  hand-typed file. Keeps prechips honest and the consumer in charge.
- **Policy lives with the shop, not in the plan.** Cheap, closes a hole.
- **Selected tool, not "some tool".** The sizing check reads the op's tool.
- **Physics as `!` lines, not gates.** The deflection/tool-life/engagement
  proxies are cited formulas that print a number and a suggestion; a shop
  policy can promote one to `block`, the default never does.
- **No EL400 file format.** A DRO recipe on the sheet until the emulator has
  an import path.
- **Stock-form comparison lists, it does not choose.**
- **Pilots**: `pivot-shaft` (lathe, simple), `rocker-arm` (mill, medium),
  `pivot-bracket` (mill, 3 setups, hard), `cone-pivot-post` (stock-form
  comparison); the rev-1 `pivot-bushing` is retired.

Dropped from revs 2–3: hashes on the sheet, rule ids on the sheet, per-finding
citations on the sheet, 15-decimal evidence strings, `spec_sha256` binding
edits as a human workflow (the report records input hashes; the sheet does
not), `attestation.yaml` as a separate file (a first-article line on the sheet
and a logbook entry is the attestation), the 14-rule policy vocabulary.

## 8. Milestones

0. **M0 — kernel spike** (§6). Done 2026-10-03: FreeCAD passes; face names
   need the consumer's export change.
1. **M1 — the sheet, for `rocker-arm`.** `plan.toml`, `features.toml` (hand-
   written for now, mirroring what the generator will emit), inventory,
   policy → `traveler.html` + `report.json`. All of §4.1 plus the §4.4
   proxies. Acceptance: print it; a machinist reads it start to finish and
   knows what to do; the `BEFORE YOU START` box names the missing reamer and
   drill chuck. Controls: one bad plan per rule that must produce its
   sentence on the sheet.
2. **M2 — `pivot-shaft` and `pivot-bracket`** sheets (lathe frame conventions:
   Z along the spindle, X as diameter; multi-setup transfer of zero;
   `prechips compare` on `cone-pivot-post`).
3. **M3 — consumer feature export.** `cad/scripts/export_features.py` in
   harmonic-analyzer, emitting `features.toml` beside the STEP, with
   `swStepExportFaceEdgeProps` on in `export_models.py`; replace the
   hand-written files; `check:traveler_<stem>` doit task under `cad/process/`.
4. **M4 — geometry and workholding** (§4.2–4.3) on the kernel; fixture
   renders on the sheet.
5. **M5 — measured inventory**: spindle stack, travel limits, holder lengths;
   envelope checks leave `?`.

## 9. Decisions from review (2026-10-03)

- §2 density: as sketched; ops and coordinates stay separate tables.
- Units: drawing unit for coordinates, as-bought for tools, both on the
  sizing line (§2 rules).
- No balloon numbers in `features.toml` or on the sheet (§2 rules).
- Speeds/feeds: vendor chart first, Machinery's Handbook 31 otherwise (§2
  rules).
- **Built-up construction needs drawing-side permission.** Where §4.5 shows a
  built-up candidate (brazed boss, pressed pin, bolted block) cheaper than
  hogging, the plan may use it only if the drawing carries a permission note
  ("MAY BE BUILT UP FROM N PIECES, BRAZED"); a permission note is a
  requirement, so it passes the drawing-simplicity rule 6. `prechips compare`
  prints the candidate either way and marks it `✗ drawing permits one-piece
  only` until the note exists; the note is a `features.toml` field
  (`construction = "one_piece" | "built_up_permitted"`) the consumer
  generator fills from the drawing notes.
