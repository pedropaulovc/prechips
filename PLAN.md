# prechips — plan

> Checks before chips. A deterministic gate that takes a part (STEP), a proposed
> process plan (YAML) and a description of one specific shop (YAML) and proves —
> or refutes — that the plan is executable on that shop, before a traveler sheet
> is printed and before an LLM machinist review or a human sees it.

Status: plan only. No code yet. Dated 2026-10-02.

## 1. Why this exists

The harmonic-analyzer CAD pipeline produces 103 part drawings and 8 assembly
drawings, each gated by a blind LLM machinist review. Process knowledge — stock,
setups, workholding, order of operations, speeds/feeds — exists only as prose
(`cad/config/parts/*.yaml` `process:` strings, `cad/docs/machining-dfm.md`).
There is no traveler, and nothing checks a proposed plan against geometry or
against the shop that will run it.

The LLM review is the *last* layer of defense. It should receive a plan that a
deterministic checker has already run, with findings attached, so it judges
craft rather than catching arithmetic.

Two things shape the design:

- **The shop is manual-with-digital-positioning.** PM-30MV with a CNC
  conversion driven by cncjs, but operated by hand through an XHC WHB04B-6
  pendant and the EL400 DRO emulator (`pedropaulovc/el400`,
  `pedropaulovc/whb04b-6`, `pedropaulovc/cncjs-pendant-whb04b-6`). Feeds are
  human; positions are exact and scriptable. The lathe (PM-1127VF-LB) is manual.
  So the artefact to validate is a **DRO plan** per setup, not a toolpath.
- **No CAM dependency in the gate.** Fusion is out (licence: personal-use is
  non-commercial, the book/Kickstarter are commercial; GUI-bound; weak API
  signal). FreeCAD is used headless as the B-rep kernel. CAM/G-code simulation
  is an optional later module for the few CNC-repeat families, if ever.

## 2. Scope

In:

- Plan schema and lint (inventory references, envelope, op order, hole/thread table).
- B-rep setup analysis on STEP: face census, accessibility, reach, internal
  corner radius, coverage, PMI-face coverage, datum/setup consistency.
- Fixture modelling (vise, parallels, collet/chuck, tailstock, steady, dividing
  head, angle plate) as parametric solids; collision and grip rules.
- Physics proxies with cited thresholds: beam deflection vs tolerance for
  slender turning/boring, cumulative cut length vs tool life for lots,
  radial-engagement/stick-out caps, thin-wall-in-grip.
- Stock-form comparison per part: candidate stock forms × setup count × waste ×
  fixture needs (the "is this 4-axis?" question answered numerically).
- DRO plan per setup: datum touch-off sequence, sub-datums, EL400 pattern
  parameters (bolt circle / linear / grid / arc contour), feature coordinates
  in the setup frame, cross-checked against drawing dimensions; emitted as
  EL400 presets / cncjs macros.
- Setup renders and traveler PDF with the DRO blocks inline.
- Machine-readable report with per-rule citations.
- Mutation controls: a known-bad plan per rule that must fire.

Out:

- Toolpath authoring quality; turning toolpaths (lathe is manual).
- FEA, chatter stability lobes (hook left for a measured FRF).
- Writing logbook entries, inventing speeds/feeds without a citation.
- Anything that needs the SolidWorks seat.

## 3. Deterministic checks (the rule catalogue)

### 3.1 Setup geometry (exact, on the B-rep)

| rule | method | finding |
|---|---|---|
| accessibility | sample each face claimed machined in a setup; cast rays along −tool axis; hit on part or fixture ⇒ occluded | `unreachable_face(face, blocker)` |
| reach | floor depth below the setup's highest surface ≤ flute length, else ≤ OAL with holder-clearance ray against walls | `tool_too_short` |
| internal corner radius | concave edges between walls ⟂ tool axis: r ≥ r_tool of the op's tool; r = 0 impossible unless EDM/broach/file op present | `corner_unmachinable` |
| coverage | ⋃ claimed faces ∪ declared as-stock faces = all faces | `unmachined_face` |
| PMI coverage | every surface-finish PMI face ∈ some machined set | `finish_without_op` |
| datum/setup consistency | a setup's locating faces machined earlier or stock; datum-referenced feature in a different setup than its datum ⇒ flag unless tolerance ≥ re-fixture budget | `refixture_risk` |
| hole/thread table | each cylindrical feature has drill → (ream/tap); tap drill from thread spec; blind depth ≤ flute | `hole_ops_missing` |

### 3.2 Workholding (geometry + inventory)

- Vise: gripped faces are a parallel pair; width ≤ opening; grip height ≥ min
  on both jaws; nothing claimed machined below jaw top; tool envelope ∩ jaw
  solids = ∅; parallels exist in inventory.
- Collet/chuck: stock Ø in the collet set or chuck range; stick-out ≤ 3Ø unless
  tailstock/steady listed; finished slender section L/D vs listed support.
- Dividing head / rotary: index angle representable (plate holes / dial
  resolution) within the feature's angular tolerance.
- Thin wall under clamp: ray-pair thickness map; wall < policy floor inside the
  grip zone ⇒ must name an approved method (mandrel, soft jaws, tape, wax).
- Tiny parts: part-off-last ordering for anything below collet minimum;
  profile ops below a footprint threshold must declare tabs or a fixture plate.

### 3.3 Physics proxies (cited)

- Turning/boring deflection: δ = F·L³/(3EI) cantilever, F·L³/(48EI) supported;
  F from specific cutting force K_c·a_p·f (Sandvik / Machinery's Handbook);
  compare δ to the diameter tolerance.
- Tool life: cumulative cut length per tool over the lot vs cited life ⇒ "change after N parts".
- Engagement: stick-out L/D ≤ 3–4 unless DOC reduced; radial engagement cap per strategy.

### 3.4 Plan lint

Schema; every tool exists in inventory; RPM from SFM table clamped to machine
range; feed/DOC within the cited table; part + fixture inside travel/swing;
turned profiles monotone from the chuck end unless a grooving op exists;
parting length within collet-stop range; rough before finish, drill before
ream/tap, face before centre-drill.

### 3.5 Stock-form comparison

For each part, enumerate candidate stock forms (bar, plate, casting, built-up
from N pieces) and emit setups, waste ratio, fixtures required and the rules
each candidate trips. First test case: `cone-pivot-post` — Ø42×86 body with a
Ø22 boss standing 30 mm proud; candidates: hog from Ø75 bar, offset-turn on a
faceplate, built-up (brazed boss), outsourced casting.

### 3.6 Non-deterministic residue, named

Chatter, clamp deformation, whip, tiny-part gripping, cutter wear. Handled by
the proxies and fixturing rules above; the plan's `verification.status` stays
`planned` until a first-article cut and a logbook entry flips it to
`bench-verified`. No rule in this project claims to replace that cut.

## 4. Architecture

```
uv venv (orchestrator)                       FreeCADCmd subprocess (kernel)
---------------------------------            ------------------------------
plan.yaml + inventory.yaml ──► lint          STEP load, face census,
          │                                  face matcher (plane/cylinder descriptors),
          ▼                                  accessibility rays, fixture solids,
     orchestrator ── JSON job ─────────────► collision, feature coordinates
          ▲                                  in the setup frame
          └──── JSON facts ◄────────────────
          │
          ├─► physics proxies
          ├─► DRO plan + EL400/cncjs presets
          ├─► report.json (findings, severities, rule cites)
          ├─► setup renders (pyrender / Blender)
          └─► traveler.pdf (Jinja → HTML → PDF)
```

Decisions:

- **FreeCAD's bundled OCC is the only CAD kernel.** The uv side never imports
  one; it talks JSON to `FreeCADCmd`. No OCP/CadQuery dependency.
- **Face selection by geometric descriptor**, the same vocabulary the
  harmonic-analyzer PMI uses (`PlanarFace(normal, offset)`,
  `CylinderFace(axis, r)`), so PMI faces and plan faces resolve through one matcher.
- **Everything deterministic:** fixed ray sampling, fixed mesh tolerances,
  versioned rule set; same inputs ⇒ same report hash. That is what lets the
  report be a doit stamp in the consuming repo.
- **Booleans stay local; state crosses boundaries as enums**
  (`verification.status`, `workholding.kind`, `machine`).

## 5. Contracts

Inputs:

- `part.step`, `part.stl` (harmonic-analyzer `cad/out/step/`, `cad/out/stl/`).
- `plan.yaml`:

```yaml
part: pivot-bushing
stock: {form: round_bar, material_spec: C36000, size_mm: "Ø12 × 60", pieces_per_bar: 10, cut_allowance_mm: 1.0}
setups:
  - id: S1
    machine: PM-1127VF-LB          # enum from inventory
    workholding: {kind: collet, ref: er32-12, stop: true}
    datum: {axis: A, face: B}
    faces: [cylinder(axis=A, r=5.0), plane(normal=+Z, offset=4.5565)]
    operations:
      - {op: 10, do: face, tool: hss-rh-turning, rpm: 1200, doc_mm: 0.5}
      - {op: 20, do: drill, tool: drill-6.4, rpm: 1800}
      - {op: 30, do: ream, tool: reamer-6.5-h7, rpm: 600, check: "Ø6.5 +0.015/0 pin gauge"}
      - {op: 40, do: part_off, tool: parting-2mm, rpm: 800, check: "4.56 ±0.02 micrometer"}
verification: {status: planned}    # planned | cam-verified | bench-verified(entry: …)
```

- `inventory.yaml` — **supplied by the user, per shop.** prechips ships no
  default inventory; `examples/inventory/pedro-shop.yaml` is a sample showing
  the schema and the `verify`/`source` conventions. A rule that depends on a
  `verify: true` value reports `warn`, never `block`.

Unit mismatch is a finding, not a conversion. A metric H7 bore with only inch
reamers in the inventory is `no_sizing_tool(feature, nearest: 0.2510 in,
delta: +0.13 mm)` at `block`; prechips never substitutes the nearest size.
(Expected on harmonic-analyzer today: its bores are metric, the sample
inventory is inch. The consumer decides whether to re-dimension or buy tools.)

Outputs:

- `report.json`: `{findings: [{id, rule, severity: block|warn|info, setup, faces, evidence, cite}], hash}`.
- `setup-<n>.png`, `traveler.pdf`, `dro/<setup>.el400.json`, optional `<setup>.cncjs.macro`.
- Exit 0 only with zero `block`.

## 6. Repository layout (target)

```
prechips/
  PLAN.md  README.md  pyproject.toml  uv.lock
  examples/inventory/pedro-shop.yaml   # sample inventory only; users bring their own
  prechips/
    schema/      plan.py inventory.py (pydantic)
    lint/
    kernel/      freecad_job.py (runs under FreeCADCmd), client.py
    rules/       one module per rule, each with a `cite`
    physics/     deflection.py toollife.py engagement.py thinwall.py
    dro/         el400.py cncjs.py coordinates.py
    render/      setups.py traveler.html.j2
    report/
    cli.py       prechips check|traveler|compare <plan>
  controls/      known-bad plans, one per rule
  tests/
  examples/      the four pilot parts from harmonic-analyzer
```

## 7. Milestones

Each milestone ends with its mutation controls firing and a smoke run on the
pilot parts: `pivot-bushing` (collet turning, ×19), `rocker-arm` (flat profile,
×20), `cone-gear-shaft` (slender between centres), `knife-mount` (prismatic,
bore + blind tap), plus `cone-pivot-post` for the stock-form comparison.

1. **Schema + inventory + lint + traveler render.** Travelers for the pilots
   with `status: planned`. Inventory file validated.
2. **Kernel.** FreeCADCmd adapter: STEP census, descriptor matcher,
   accessibility, reach, corner radius, coverage/PMI/datum rules.
3. **Fixtures + physics.** Vise/collet/chuck/parallels/tailstock/steady/dividing
   head solids; collision; grip rules; thin-wall map; deflection and tool-life.
4. **DRO plan.** Feature coordinates per setup, EL400 presets, cncjs macros,
   drawing cross-check; stock-form comparison for `cone-pivot-post`.
5. **harmonic-analyzer integration.** `cad/config/process/<part>.yaml`,
   `check:process:<stem>` doit gate (SolidWorks-free, parallel with `check:*`),
   traveler in the release bundle, machinist-review prompt reads `report.json`.
6. *(optional)* **CAM sim** for CNC-repeat families: FreeCAD Job → grbl post →
   2.5D swept-volume sim (manifold3d) → mesh diff. Only if a profile ever runs
   under G-code on the PM-30MV.

## 8. Risks

- FreeCAD headless API churn (Path→CAM rename in 1.0; OCC wrappers). Pin the
  version; keep the kernel a thin JSON adapter with integration tests on the pilots.
- Descriptor matching on fillet-heavy castings (summing-lever): organic faces
  default to as-cast and flag if claimed machined.
- Rules are only as good as the inventory and the cited tables. Every threshold
  carries a `cite`; an uncited number is a lint error in this repo.
- The DRO plan assumes the EL400 emulator's function set; keep the preset
  format versioned against `pedropaulovc/el400`.

## 9. Open items

- Sample inventory refinement (fields marked `verify`).
- Drawing-side permission for built-up construction where the comparison
  recommends it (a permission note is a requirement, so it passes
  harmonic-analyzer's drawing-simplicity rule 6).
- Whether the traveler ships in the harmonic-analyzer release zip.
