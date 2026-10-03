# prechips — plan (rev 4)

> Checks before chips. prechips turns a part plus a short process plan into a
> **traveler a machinist can work from**: one page per setup saying how to hold
> it, where zero is, what the DRO should read for each feature, which tool,
> what speed and feed to start at, and what to measure. A deterministic checker
> runs first and puts anything it found at the top of the sheet, in plain
> words. Everything else it computed goes to a machine-readable report that no
> human has to read.

Status: plan only. Rev 4, 2026-10-03. Rev 1 was traveler-first but promised
geometric proofs it could not deliver. Revs 2–3 absorbed two adversarial
reviews and became correct but unusable: a 100 KB traveler of YAML ids, hashes
and 15-decimal numbers. Rev 4 restores the original purpose and keeps the
review's good ideas where they cost the machinist nothing.

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
Traveler  2026-10-03  prechips 0.1   plan rocker-arm/plan.yaml  sheet 3 of 4

BEFORE YOU START
  ✗  No 6.50 mm reamer in the shop. Nearest: 0.2510 in (6.375 mm), 0.125 mm
     under the bore's low limit. Buy a 6.5 H7 reamer or re-dimension.
  ✗  No R8 drill chuck listed; ops 60–80 drill from a collet. Confirm or add.
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
  as starting points. The citation is one line per setup, not per cell.
- **The DRO block is a recipe, not a file.** It says which edge, which
  finder, which direction, what to type. It is written for the EL400's actual
  functions (ABS/INC, radius/diameter, preset, bolt-circle/linear patterns);
  prechips does not emit EL400 files until the emulator has an import path.
- **Footer**: `prechips <version> · report <8-char id>` so the sheet can be
  matched to its `report.json`. That is the only identifier on the page.

## 3. Inputs (what the author writes)

### 3.1 `plan.yaml` — short, per part

```yaml
part: rocker-arm
drawing: {number: MHA-071, revision: v21}
quantity: 20
stock: {form: flat_bar, material: "1018 CRS", section_mm: [45, 16], length_mm: 310}
setups:
  - id: S3
    machine: pm-30mv
    hold: {vise: vise-6in, jaws_along: x, parallels: 3/4in, grip_mm: 10}
    frame: A                            # named in features.yaml
    zero:
      x: {edge: left_end,  from: -x, tool: edge-finder-0.200}
      y: {edge: front,     from: -y, tool: edge-finder-0.200}
      z: {face: top,       method: paper, tool: em-3/8-4fl}
    ops:
      - {op: 10, do: face,   feature: top,        tool: em-1/2-4fl}
      - {op: 20, do: spot,   feature: pivot_bore, tool: cd-2}
      - {op: 30, do: drill,  feature: pivot_bore, tool: drill-6.2mm}
      - {op: 40, do: ream,   feature: pivot_bore, tool: reamer-6.5-h7, check: pin-gauge}
      - {op: 50, do: drill,  feature: rod_hole,   tool: drill-47}
      - {op: 60, do: profile, feature: hub_od,    tool: em-3/8-4fl, passes: 2, check: caliper}
```

The author writes the route. prechips fills in RPM/feed from tables, derives
coordinates from the feature file, and resolves tool names against the shop.
Tool ids are short and human (`em-3/8-4fl`), set by the inventory.

### 3.2 `features.yaml` — the drawing, in numbers (generated by the CAD side)

Exported beside the STEP by the consumer (harmonic-analyzer: from
`rocker_arm_spec.py`, `_hole_spec.py` and the title-block defaults). prechips
never reads PMI from the STEP — there is none in the AP214 export — and never
invents a tolerance. Per feature: kind, frame, centre/axis, size with limits,
through/blind depth, inspection hint, and where on the drawing it came from:

```yaml
part: rocker-arm
units: mm
frames:
  A: {origin: "bottom face / left end / front edge", note: "drawing datum scheme"}
material: {spec: "1018 CRS", thickness: 16.0}
features:
  pivot_bore: {kind: hole, frame: A, at: [25.40, 12.70], dia: [6.50, 6.53], thru: true, zone: B3}
  rod_hole:   {kind: hole, frame: A, at: [85.12, 18.23], drill: "#47", thru: true, zone: C2}
  hub_od:     {kind: boss, frame: A, at: [25.40, 12.70], dia: [13.90, 14.10], height: 9.53, zone: B2}
  top:        {kind: face, frame: A}
```

A feature the generator cannot source is left out, and whatever needed it
shows up on the sheet as `?`.

### 3.3 `inventory.yaml` — the shop (user-supplied; sample in `examples/inventory/`)

Machines with ranges and (when measured) envelopes; holders; tools by short
id with diameter, flutes, flute length, OAL, shank, material; gauges. A value
copied from a vendor page is `verify: true` and anything that depends on it
is a `?` on the sheet, never a silent pass.

### 3.4 `shop-policy.yaml` — what must be confirmed (user-supplied, optional)

Which checks must come back clean before the sheet drops its `PLANNED` banner.
Lives with the inventory, not in the plan, so a plan cannot waive it. Default
shipped: tool sizing, op order, blind-hole depth, spindle clearance, fit in
travel, every toleranced feature has a check.

## 4. What the checker does (quietly)

Deterministic, declared-input checks. Each produces `pass`, `fail` (block or
warn) or `unknown` (an input missing or unverified) per feature/setup; the
sheet shows only fails and unknowns, in words. Exit: 2 on any block, 4 on a
required unknown, else 0 — so the consumer can wrap it as a doit gate.

| check | on the sheet it reads like |
|---|---|
| tool exists / holder fits machine | "No R8 drill chuck listed." |
| selected finishing tool makes the size (unit mismatch reported, never converted) | "Nearest reamer 6.375 mm, 0.125 under the low limit." |
| op chain per feature kind (spot→drill→ream/tap; counterbore after its hole) | "Pivot bore is reamed without a drill op." |
| order (rough→finish, drill→ream/tap) | "Op 40 reams before op 30 drills." |
| blind depth: drill depth + point ≤ material; tap flute ≥ thread depth | "Drill to 12.5 in 9.5 stock breaks through." |
| spindle-to-table stack and travel (needs measured inventory) | "Vise bed height not measured." |
| every toleranced feature has a check | "Hub OD ±0.1 has no measurement." |
| coordinates: feature → DRO frame through the zero recipe; edge-finder radius and paper thickness applied | (silent when right; "Y zero direction contradicts frame A" when wrong) |
| speeds/feeds from cited tables, clamped to the machine | (fills the columns; "? no table entry for O1 hardened" when absent) |

Geometry on the STEP (reach, collision, accessibility) is **not** in this
list. It needs a kernel spike (§6) and even then only adds `?`/`!` lines; the
sheet is complete without it.

## 5. Outputs

- `traveler.html` — §2. The product.
- `report.json` — every check with status, numbers and citation; sorted,
  canonical, hashed (hash excludes itself). For doit stamps and for the
  informed machinist review, never for humans at the bench.
- `setup-S<n>.png` — the fixture render, once the kernel exists; until then a
  placeholder box on the sheet with the "Locate / Hold" text.

CLI: `prechips traveler <plan.yaml>` (writes both; exit per §4),
`prechips tools` (lists the inventory as prechips resolved it).

## 6. Kept from the reviews, and why

- **Unknown is not a pass.** Unmeasured inventory shows as `?`, and a required
  `?` keeps the `PLANNED` banner and exits 4. This is the one review idea that
  changes what the machinist sees, and it should: "not checked" is useful.
- **The drawing's numbers come from a generated feature file**, not PMI, not a
  hand-typed YAML. Keeps prechips honest and the consumer in charge.
- **Policy lives with the shop, not in the plan.** Cheap, closes a hole.
- **Selected tool, not "some tool".** The sizing check reads the op's tool.
- **No EL400 file format, no physics gates, no stock-form optimizer.** Speeds
  and feeds are table lookups printed on the sheet, not deflection models. A
  stock-form comparison is an authored table the author fills in; prechips
  only counts setups and waste.
- **Kernel spike before any geometry rule.** `FreeCADCmd` on the real STEP
  exports: load, bounding box, resolve each feature id to one face. Pass →
  fixture renders and reach/collision as `!` lines. Fail → prechips stays
  declared-input only, which is still the whole §2 sheet.
- **Pilots**: `pivot-shaft` (lathe, simple), `rocker-arm` (mill, medium),
  `pivot-bracket` (mill, 3 setups, hard); the rev-1 `pivot-bushing` is retired.

Dropped from revs 2–3: hashes on the sheet, rule ids on the sheet, per-finding
citations on the sheet, 15-decimal evidence strings, `spec_sha256` binding
edits as a human workflow (the report records input hashes; the sheet does
not), `attestation.yaml` as a separate file (a first-article line on the sheet
and a logbook entry is the attestation), the 14-rule policy vocabulary.

## 7. Milestones

1. **M1 — the sheet, for `rocker-arm`.** `plan.yaml`, `features.yaml` (hand-
   written for now, mirroring what the generator will emit), inventory,
   policy → `traveler.html` + `report.json`. Checks: tool/holder, sizing, op
   chain, order, blind depth, coverage, coordinates, speeds/feeds. Acceptance:
   print it; a machinist reads it start to finish and knows what to do; the
   `BEFORE YOU START` box names the missing reamer and drill chuck. Controls:
   one bad plan per check that must produce its sentence on the sheet.
2. **M2 — `pivot-shaft` and `pivot-bracket`** sheets (lathe frame conventions:
   Z along the spindle, X as diameter; multi-setup transfer of zero).
3. **M3 — consumer feature export.** `cad/scripts/export_features.py` in
   harmonic-analyzer, emitting `features.yaml` beside the STEP; replace the
   hand-written files; `check:traveler_<stem>` doit task under `cad/process/`.
4. **M4 — kernel spike** and, if it passes, fixture renders and reach/collision
   as sheet lines.
5. **M5 — measured inventory**: spindle stack, travel limits, holder lengths;
   envelope checks leave `?`.

## 8. Open questions for review

- Is the §2 sketch the right density, or should ops and coordinates merge into
  one table?
- Inch or mm on the sheet for harmonic-analyzer parts? The drawings are mm;
  the DRO and the tooling are inch. Proposal: coordinates in the drawing's
  unit, tool sizes as bought, both shown where they meet (the sizing line).
- Should `features.yaml` carry the drawing's balloon numbers so the sheet can
  say "bore ③" instead of `pivot_bore`?
- Which speeds/feeds source to cite first: Machinery's Handbook 31, or the
  tool vendor's chart (LMS publishes none; Harvey/Lakeshore do)?
