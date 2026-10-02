# prechips — plan (rev 3)

> Checks before chips. A deterministic checker that takes a certified part
> export (STEP + feature specification sidecar, produced together by the CAD
> side), a proposed process plan (YAML), a consumer-owned rule policy (YAML)
> and one specific shop's inventory (YAML), and reports what it can prove,
> what it refutes, and what it cannot know — before a traveler is printed and
> before a machinist review or a human sees it.

Status: plan only. No code beyond the package skeleton. Rev 3, 2026-10-02.
Rev 1 claimed a gate that "proves executability"; two rounds of adversarial
review (findings carried in the rev-2 and rev-3 commit messages) narrowed it
to what a checker can establish from declared inputs, with unknowns named as
unknowns, policy outside the plan author's hands, and geometry-heavy rules
behind a kernel spike.

## 1. Why this exists

The harmonic-analyzer CAD pipeline produces 103 part drawings and 8 assembly
drawings, each gated by a blind, image-only LLM machinist review
(`machinist_review.py` enforces that isolation). Process knowledge — stock,
setups, workholding, order of operations — exists only as prose
(`cad/config/parts/*.yaml` `process:` strings; `cad/docs/machining-dfm.md`,
itself stale: it discusses a brass knife-mount while the registry specifies
hardened O1). There is no traveler, and nothing checks a proposed plan against
the part's dimensions or against the shop that will run it.

prechips sits *beside* the blind drawing review, not inside it: the drawing
review stays image-only and answers "is this sheet makeable from what it
shows"; prechips answers "is this plan, on this shop, consistent with the
declared features" and its findings feed a separate, informed process review.
Two verdicts, never merged.

Two things shape the design:

- **The shop is manual-with-digital-positioning.** PM-30MV with a CNC
  conversion driven by cncjs, operated by hand through an XHC WHB04B-6 pendant
  and the EL400 DRO emulator (`pedropaulovc/el400`). Feeds are human; positions
  are read off a DRO. The lathe (PM-1127VF-LB) is manual. So the artefact to
  validate is a **per-setup coordinate table**, not a toolpath.
- **No CAM dependency.** Fusion is out (personal licence is non-commercial, the
  book/Kickstarter are commercial; GUI-bound; weak API signal). FreeCAD is the
  B-rep kernel, headless, behind a thin JSON adapter — and only once a spike on
  the consumer's real STEP exports shows it can do the job (§7, M2).

## 2. Findings, policy, exit codes

Every rule yields exactly one status per subject:

| status | meaning |
|---|---|
| `pass` | the declared inputs satisfy the rule |
| `fail` | the declared inputs violate the rule; severity `block` or `warn` |
| `unknown` | a required input is absent, or carries `verify: true` (directly or through a referenced entry — verification is inherited down `ref:` chains); the rule could not run |
| `not_applicable` | the rule's applicability predicate is false for this subject (e.g. `blind_thread_depth` on a through thread). An *unsupported* subject class is `unknown`, never `not_applicable` |

**Policy is a separate, consumer-owned input** (`policy.yaml`, versioned,
hashed into the report). It lists the required rules and per-rule severity.
A plan may *add* required rules; it cannot remove or downgrade one. A rule id
the checker does not know is a `schema` block. The default policy shipped in
`examples/policy/default.yaml` requires every rank-1 and rank-2 rule in §4
plus `envelope` and `holder_compat`, so an unverified machine or fixture
measurement can never produce a green exit — it produces a list of
measurements to take.

Exit codes: `2` if any rule is `fail/block`; else `4` ("not ready") if any
required rule is `unknown`; else `0`. `2` takes precedence over `4`.

A rule specification is testable or it does not ship: units, applicability
predicate, exact inequality with boundary behaviour, source (edition/page or
URL+date), uncertainty treatment, one valid and one invalid example. A bare
"see Machinery's Handbook" is not a citation. Rule specs live in
`docs/rules/<rule>.md` and are versioned together as `rules_version`.

## 3. Inputs and contracts

### 3.1 Certified export: `part.step` + `spec.yaml`, produced together

The consumer exports the STEP and generates the sidecar in **one step**
(harmonic-analyzer: a new `cad/scripts/export_process_spec.py` run after
`export_models.py`), so the sidecar's `step_sha256` always names the bytes it
describes. AP214 repeat-export byte determinism is unmeasured; the lifecycle
therefore is: every re-export regenerates the sidecar; a plan names the
`spec_sha256` it was written against; `step_binding` blocks a plan whose spec
hash no longer matches the certified pair. Rebinding a plan to a new export is
an explicit edit of `spec_sha256` (a diff a reviewer sees), never silent. A
semantic-equivalence policy ("only metadata changed, keep the attestation")
is a future open question (§9), not something the checker infers.

**No PMI is read from the STEP** (the consumer's export contract is AP214
colours, not semantic PMI). Everything dimensional comes from the sidecar.

### 3.2 `spec.yaml` — feature specification sidecar

```yaml
part: rocker-arm
step_sha256: "…"
drawing: {number: MHA-071, revision: v21, sheet: 1}
units: mm
decimal_precision: 2              # drawing's implied precision for untoleranced values
default_tolerances:               # from the title block; provenance for every untoleranced value
  linear: {source: "title block: ±0.1 unless noted"}
  angular: {source: "title block: ±0.5°"}
material: {spec: "1018 CRS", thickness: 9.525}    # stock-direction thickness for breakout checks
frames:
  model: {note: "STEP coordinate system"}
  A:
    parent: model
    transform: {origin: [0, 0, 0], x: [1,0,0], y: [0,1,0], z: [0,0,1]}   # A → model; validated right-handed, orthonormal
    note: "bottom face, left end, front edge"
features:
  - id: pivot_bore
    kind: hole                    # hole | bore | counterbore | shaft | slot | pocket | face | thread | fillet
    frame: A
    entry_face: top               # named face in the frame; depth is measured from it along -axis
    axis: [0, 0, -1]
    center: {x: 25.4, y: 12.7, tolerance: {position_dia: 0.1, source: "zone B3"}}
    diameter: {nominal: 6.5, upper: 0.03, lower: 0.0, source: "zone B3, explicit"}
    end: {condition: through}     # through | blind: {depth: <mm>, from: entry_face}
    finish: {kind: roughness, ra_um: 1.6, source: "zone B3"}   # kind: roughness | coating
    datum_refs: []
  - id: pivot_cbore
    kind: counterbore
    parent: pivot_bore            # a counterbore always names the hole it sits on, shares its axis/centre
    diameter: {nominal: 9.5, upper: 0.1, lower: 0.0, source: default}
    end: {condition: blind, depth: 2.0, from: entry_face}
  - id: rod_tap
    kind: thread
    frame: A
    entry_face: top
    axis: [0, 0, -1]
    center: {x: 50.8, y: 12.7, tolerance: {position_dia: 0.2, source: default}}
    thread: {designation: "1/4-20 UNC", class: "2B", standard: "ASME B1.1-2003", source: "zone C2"}
    end: {condition: blind, depth: 9.5, from: entry_face}   # full-thread depth
  - id: profile_outer
    kind: pocket                  # the outer profile, modelled as the complement: stock minus part
    frame: A
    tolerance: {profile: 0.1, source: default}
```

What a rule can rely on: typed kinds; one end-condition model for every
axial feature; explicit entry face and axis direction; position tolerance
with provenance; default-tolerance provenance for untoleranced values; thread
designation + class + standard; finish kind separated from coating; material
thickness along the feature axis for breakout checks; the drawing identity the
values were read from. Anything a generator cannot source from the consumer's
own spec modules (harmonic-analyzer: `rocker_arm_spec.py`, `_hole_spec.py`,
`_gtol_spec.py`, the title-block defaults) is left out, and the rule that
needs it reports `unknown`.

### 3.3 `plan.yaml` (author: machinist / agent; reviewed by the checker)

```yaml
part: rocker-arm
spec_sha256: "…"                  # the certified pair this plan was written against
policy: policy.yaml
stock:
  state: prepared_blank           # raw_bar | prepared_blank — what the plan starts from
  material_spec: "1018 CRS"
  section_mm: {w: 25.4, t: 9.525}
  length_mm: 60
setups:
  - id: S1
    machine: PM-30MV
    workholding:
      kind: vise
      ref: vise-pm-6
      orientation: jaws_along_x
      parallels: {ref: parallels-lms-6745, item: "3/4in"}
      part_top_above_jaws_mm: 4.0
    frame: A
    pickup:                         # structured, so the sign/offset check is computable
      x: {feature: left_end, side: -x, tool: edge-finder-lms-1853, tool_dia_mm: 5.08, sets: 0.0}
      y: {feature: front_edge, side: -y, tool: edge-finder-lms-1853, tool_dia_mm: 5.08, sets: 0.0}
      z: {feature: top, side: +z, method: paper, paper_mm: 0.08, sets: 9.525}   # Z0 is A's origin (bottom face)
    holders:
      - {ref: r8-collets-lms-4860, item: "1/4in"}
      - {ref: r8-collets-lms-4860, item: "3/8in"}
    features: [pivot_bore, pivot_cbore, rod_tap, profile_outer]
    operations:
      - {op: 10, do: spot,  feature: pivot_bore, tool: center-drills-lms-4859/2, holder: r8-collets-lms-4860/1-4in}
      - {op: 20, do: drill, feature: pivot_bore, tool: drill-index-115/6.2mm, holder: r8-collets-lms-4860/1-4in, rpm: 1500}
      - {op: 30, do: ream,  feature: pivot_bore, tool: reamers-metric/6.5-H7, holder: r8-collets-lms-4860/1-4in, rpm: 500,
         inspect: {method: pin_gauge, gauge: pin-gauges-metric/6.50-6.53, go: 6.50, nogo: 6.53}}
      - {op: 40, do: spot,  feature: rod_tap,    tool: center-drills-lms-4859/2}
      - {op: 50, do: drill, feature: rod_tap,    tool: drill-index-115/13-64, depth_mm: 12.5}
      - {op: 60, do: tap,   feature: rod_tap,    tool: taps/1-4-20-unc-2b-plug, method: hand_tap_guide}
      - {op: 70, do: counterbore, feature: pivot_cbore, tool: endmills-lms-6784/3-8in-2fl, holder: r8-collets-lms-4860/3-8in, depth_mm: 2.0}
      - {op: 80, do: profile, feature: profile_outer, tool: endmills-lms-6784/3-8in-4fl, holder: r8-collets-lms-4860/3-8in, rpm: 1800}
```

Tool references are `set/item`, resolving to one physical tool with its own
flute length, OAL, shank. `sizing_tool` checks the tool the operation
*selects*, not whether any suitable tool exists somewhere in the inventory.
Permitted chains are enumerated per kind (`hole`: spot→drill, spot→drill→ream,
spot→drill→bore; `bore`: drill→bore; `thread`: spot→drill→tap) — a chain
outside the list is a `fail`, not an inferred alternative.

The example is a *valid control*: every referenced feature exists, every
feature has operations, the selected reamer matches the 6.50–6.53 band, the
pickup's Z offset equals the material thickness so A's bottom-face origin is
consistent with touching the top. `examples/rocker-arm/` will also carry the
invalid controls (§7).

### 3.4 `policy.yaml` (consumer-owned)

```yaml
policy_version: 1
required: [schema, inventory_refs, citations_present, step_binding, sizing_tool,
           hole_op_chain, op_order, blind_thread_depth, coverage, envelope, holder_compat]
severity: {sizing_tool: block, envelope: block, coverage: warn}
```

### 3.5 `inventory.yaml` (user-supplied; sample in `examples/inventory/`)

Per-tool entries, not only sets. A set entry (`endmills-lms-6784`) expands to
items with per-item geometry (`diameter`, `flute_length`, `oal`, `shank`,
`flutes`, `center_cutting`) — vendor-page values flagged `verify: true` until
measured. `present: null` is `unknown`, not absent.

Fields the `envelope` rule needs that the current sample lacks (each a
measurement to take before the rule leaves `unknown`):
`machine.travel_measured_in` (soft-limit extents), `machine.spindle_nose_to_table_max_in`,
`vise.bed_above_table_in` (not jaw height), `parallels[].height_in`,
`holder.gauge_length_in` and `holder.insertion_in` (so OAL is not
double-counted), `tool.projection_in` once mounted, `chuck.jaw_swing_dia_in`,
`parting_blade.reach_in`, `tailstock.quill_in`.

Unit handling: comparisons normalize to mm with the delta reported in both
units; substitution never happens. Example: spec Ø6.500 +0.03/0 vs selected
inch reamer 0.2510 in = 6.3754 mm → `sizing_tool(pivot_bore, selected: reamers/0.2510, delta: −0.125 mm, outside: [6.50, 6.53])` at `block`.

### 3.6 `attestation.yaml` — bench verification, separate from the plan

Bench verification is a first-article cut, not prose. It is recorded outside
the plan, by a human, as a file the checker only *reads*:

```yaml
part: rocker-arm
first_article: {logbook_entry: "logbook/entries/2026-10-14.md", measured: {pivot_bore: 6.512}}
bound_to: {spec_sha256: "…", plan_sha256: "…", inventory_sha256: "…", policy_sha256: "…"}
```

`plan_sha256` is the digest of the plan file itself (the plan carries no
verification field, so the digest is not self-referential). Any input hash
that no longer matches makes the attestation stale: the report says
`verification: planned` and names which hash moved. A stateless checker can
enforce exactly this and nothing more; "re-approval after an equivalent
re-export" is consumer workflow (§9).

### 3.7 Outputs

- `report.json`: canonical JSON — sorted object keys; findings sorted by
  `(rule, subject)`; evidence arrays in declaration order; floats as shortest
  round-trip repr, no NaN/Inf; no timestamps. Shape:
  `{inputs: {step_sha256, spec_sha256, plan_sha256, inventory_sha256, policy_sha256, rules_version, tables_version, prechips_version}, verification, findings: [{rule, subject, status, severity, evidence, cite}], hash}`.
  `hash` is SHA-256 of the canonical JSON with the `hash` member omitted;
  rendered bytes are excluded.
- `coordinates/<setup>.csv`: per-setup coordinate table — header row names
  the frame and units (`frame=A, units=mm, mode=absolute, diameter`), rows
  `feature, op, x, y, z`. Derived from the sidecar through the setup's pickup
  transform, so a reversed pickup side or wrong Z offset moves the numbers and
  is caught by `coordinate_table` against the sidecar's own values. **No
  EL400 preset format** (EL400 mirrors cncjs position state and discards SDM
  sessions on exit; it has no import contract). An adapter is added only after
  a neutral table has been used at the machine.
- `traveler.html` (PDF via the browser's print, no PDF dependency in M1):
  setups, operations, coordinate tables, findings inline, headed
  "PLANNED — scoped checks only" until an attestation binds.
- `setup-<n>.png`: optional, M3+.

CLI: `prechips check <plan.yaml> --inventory <inv> [--policy <p>] [--attestation <a>] --out <dir>`
(exit per §2); `prechips render <report.json>` (traveler); `prechips rules`
(lists rule ids, versions, citations). The consumer enrolls `report.json` +
`traveler.html` in its release bundle (`cut_release.py:stage_*`), M4.

## 4. Rule catalogue, ranked by expected signal

Ranks are engineering judgment for lots of 1–20, to be re-measured on the
pilot plans. Column *needs* names the inputs; a rule whose inputs include a
field the sidecar cannot source reports `unknown`.

| rank | rule | needs | status |
|---|---|---|---|
| 1 | `schema`, `inventory_refs`, `citations_present`, `step_binding`, `policy_integrity` (plan adds, never subtracts) | plan, inventory, spec, policy | M1 |
| 1 | `sizing_tool` — the *selected* finishing tool for every toleranced hole/bore/thread produces a size inside the band; unit mismatch reported, never converted | spec, inventory, plan | M1 |
| 2 | `hole_op_chain` — per kind, one of the enumerated permitted chains; counterbore after its parent, tool ≥ its diameter | spec, plan | M1 |
| 2 | `op_order` — rough before finish, drill before ream/tap, spot before drill | plan | M1 |
| 2 | `coordinate_table` — sidecar centre → setup frame through the structured pickup; checks pickup side/offset consistency with the frame definition and material thickness | spec, plan | M1 |
| 2 | `coverage` — every sidecar feature has ≥1 operation and every toleranced feature has an `inspect` entry; this is requirement-to-operation coverage, not geometric proof | spec, plan | M1 |
| 2 | `blind_thread_depth` — drill depth ≥ full-thread depth + tap chamfer lead (plug/bottoming from the tap item) + drill-point allowance (118°/135° from the drill item); tap flute ≥ full-thread depth; drill depth + point < `material.thickness` unless `through` | spec (`end`, `material.thickness`), inventory (tap/drill geometry), plan | M1b: `unknown` until the tap/drill items carry geometry |
| 3 | `envelope` — assembled stack against reference planes: table → vise bed → parallels → part top; spindle nose → holder gauge length → tool projection; `≤ spindle_nose_to_table_max` with clearance for insertion/retract; drill depth ≤ quill stroke or declared head move; chuck jaw swing vs swing-over-bed; bar stick-out behind headstock; parting reach ≥ stock radius; tailstock quill vs declared reach | plan, inventory fields of §3.5, spec | M1b: `unknown` until measured |
| 3 | `holder_compat` — each operation's tool shank fits its declared holder, and the holder fits the machine (R8 collet sizes, QCTP shank cap, MT3 sleeve for the 2MT chuck) | plan, inventory | M1 |
| 3 | `index_representable` — angle reachable with the listed plates within the feature's angular tolerance; needs `angle` + `tolerance.angular` on the feature | spec (angular fields), inventory | M1b |
| 5 | `tool_reach`, `fixture_collision`, `internal_corner_radius` — restricted to named milling operation classes with measured cutter/holder envelopes and explicit intermediate stock | STEP + kernel | M3 |
| 6 | `grip`, `thin_wall_in_grip`, `part_off_last`, `tiny_part_method`, `slender_support` — advisory | STEP + kernel, plan | M3 |
| 7 | `rpm_from_sfm`, `stickout_ld`, `engagement` — advisory with cited tables; RPM clamped to machine range | plan, inventory, tables | M3 |
| 8 | `axial_accessibility`, geometric coverage — advisory; "as-stock" waiver must name faces | STEP + kernel | M3, maybe never |
| — | datum/re-fixture budget | semantic datum scheme | dropped (the drawing policy removes most formal datums) |
| — | deflection-vs-tolerance gate, tool-life counter, stock "winner" | calibrated force/clamp models | dropped as gates; see §5 |

Mutation controls: for each shipped rule, one known-bad plan that must `fail`
*and* the valid control that must `pass`.

## 5. What stays advisory or deferred, and why

- **Physics proxies.** The rev-1 `F·L³/(3EI)` / `F·L³/(48EI)` forms assume a
  prismatic beam with an end/central load; `cone-gear-shaft` is stepped, the
  tool load moves, the tailstock is compliant, and Sandvik's specific cutting
  force is the tangential component, not the radial one that sets diameter
  error (and a radial deflection doubles diametrally). No clamping-force
  input exists. Kept only as an advisory estimate with a stated model and its
  assumptions, never a gate. Chatter/FRF: out.
- **Stock-form comparison.** Geometry can compute a declared blank's waste; it
  cannot synthesize setup routes, casting allowances, brazing acceptance or
  procurement cost. Replaced by an *authored* candidate table: the plan author
  lists candidate routes with their setups and fixtures; prechips reports waste
  volume, setup count, findings and unknowns per candidate as an unweighted
  table. No winner is declared; "indexed on a BS-0" is 3+1 indexing, never
  "4-axis". A built-up construction (brazed boss) is a design change needing
  CAD-side approval, not a drawing note.
- **FreeCAD kernel.** Candidate APIs: `Part.Shape.read`, `Face.Surface`
  descriptors, `distToShape`/`common` against placed fixture solids, `section`
  against finite ray edges. OCC documents tangency/tolerance failures on
  booleans; face ordering is not stable across versions. The M2 spike's
  acceptance cases: invalid/unhealed shape → `unknown` with the OCC check
  result; ambiguous descriptor match (two faces fit) → `unknown`, never
  first-match; split/seam faces on cylinders resolved to one feature; a
  re-export of the same model resolves every sidecar feature to the same
  geometry; bounding boxes agree with the sidecar's `material` extents. If
  the spike fails, M3 is cut and prechips stays a declared-input checker.
- **Determinism.** Pinned: FreeCAD version *and bundled OCC*, importer
  settings, sampling algorithm and seed, numerical tolerances, `rules_version`,
  `tables_version` (cited speed/feed/tap-drill tables), canonical JSON per
  §3.7. Feature identity comes from sidecar ids, never OCC object hashes.
- **CAM simulation, EL400 adapter, cncjs macros, every fixture family.**
  After a neutral traveler has been used at the machine.

## 6. Architecture

```
uv venv (prechips)                                FreeCADCmd (M2+, optional)
---------------------------------------           ------------------------------
spec.yaml + plan.yaml + policy.yaml               STEP load, face descriptors,
+ inventory.yaml [+ attestation.yaml]             bounding boxes, fixture solids,
      │                                            distance & collision
      ├─► schema / policy / rank 1–3 rules    ◄──► JSON job / JSON facts
      ├─► coordinate tables (csv)
      ├─► report.json (canonical, hashed)
      └─► traveler.html (not hashed)
```

- The uv side never imports a CAD kernel; it shells to `FreeCADCmd` with a
  JSON job and reads JSON facts. Absent kernel ⇒ kernel-backed rules are
  `unknown`, the rest run.
- Booleans stay local; state crosses boundaries as enums (`status`,
  `workholding.kind`, `end.condition`, `verification`).

## 7. Milestones

Pilots (current revisions; the rev-1 `pivot-bushing` was retired 2026-09-02
when the rocker and lever got integral hubs):

- `rocker-arm` — ×20, 1018, integral hub with Ø6.5 +0.03/0 pivot bore
  (`rocker_arm_spec.py`), profile from flat bar (mill).
- `amplitude-bar` — ×20, steel bar with slide features (mill).
- `cone-gear-shaft` — ×1, stepped shaft between centres (lathe).
- `knife-mount` — ×2, O1 hardened 58–60 HRC: machine soft → heat-treat →
  finish; the plan must sequence the heat-treat and name the post-HT ops.

1. **M1 — vertical slice: rocker-arm pivot-bore setup.** One pilot, one
   setup (the pivot-bore finishing on a prepared blank), one real consumer
   exporter (`cad/scripts/export_process_spec.py` emitting `spec.yaml` from
   `rocker_arm_spec.py`/`_hole_spec.py`/title-block defaults beside the STEP —
   no stub, no hard-coded values). Rules: rank 1, `hole_op_chain`,
   `op_order`, `coordinate_table`, `coverage`, `holder_compat`. Files:
   `src/prechips/{cli,schema,rules/*,report,render}.py`,
   `examples/rocker-arm/{spec,plan,policy}.yaml`, `examples/policy/default.yaml`,
   a measured pilot inventory. Controls: wrong selected reamer size, missing
   tool, unverified tool (`unknown`), policy subtraction attempt, stale
   `spec_sha256`, reversed pickup side, feature without operation, toleranced
   feature without inspection. Acceptance: one `prechips check` produces the
   canonical report, the CSV and the traveler; exit precedence verified;
   two runs give byte-identical reports; CSV coordinates compared by hand
   against the drawing.
2. **M1b — measured-input rules.** `blind_thread_depth`, `envelope`,
   `index_representable` once the inventory carries the §3.5 fields and the
   tap/drill items carry geometry; then the remaining three pilots and the
   warning-burden measurement.
3. **M2 — kernel spike** per §5's acceptance cases. Go/no-go for M3.
4. **M3 — fixtures + restricted geometry rules** (rank 5–7), only if M2 passes.
5. **M4 — harmonic-analyzer integration.** Process files under `cad/process/`
   (outside the `_buildgraph` whole-config fallback, so no `check:*` re-runs);
   a flat `check:process_<stem>` doit task with `file_dep` on spec, plan,
   policy, inventory, cited tables and the prechips version; report +
   traveler enrolled in the release bundle; a second, informed machinist
   review that receives the report, separate from the blind drawing review.
6. **M5 — advisory physics and adapters**, each behind its own citation.

## 8. Risks

- Sidecar generation is consumer work and must source from the consumer's
  spec modules; the fields it cannot source leave rules `unknown`. Without
  any sidecar, prechips runs only `schema`/`inventory_refs`/`holder_compat`/
  `op_order` — honest but thin.
- Inventory measurement debt: every `verify: true` is an `unknown` until
  measured; the first run's output is a measuring list, not a verdict.
- FreeCAD/OCC behaviour on SolidWorks AP214 exports is unproven here (M2).
- Byte-bound attestation means every re-export invalidates bench status until
  a human rebinds; this is the conservative choice until §9 decides an
  equivalence policy.

## 9. Open questions

- Who owns `policy.yaml` and the human approval step in harmonic-analyzer?
- Which fields does `export_process_spec.py` treat as authoritative for
  default tolerances, thread class and roughness — registry, `_gtol_spec`,
  or the drawing script?
- Should a re-export that changes only STEP metadata bytes keep the
  attestation (equivalence review), or always require a rebind?
- Which inventory measurements must be taken before the first pilot run
  (mill soft limits, vise bed height, actual flute/holder lengths)?
