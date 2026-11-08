# Reference bundles

The **plans remain authored** and every example traveler remains **PLANNED**.
The shaft, rocker and cone are being reconciled to current harmonic-analyzer
CAD drawings and exact v47 release exports, not older example routes. CAD
defines the part; an authored plan is not a source of design requirements.
Each candidate also consumes the shared shop inputs.
`pivot-bracket/` is hand-authored against the v39 consumer STEP
(`pivot-bracket.STEP`, sha256 `6cd4ab60f57b1c9771cec083fbbd0ef1f94171f1d95f9485a135a4dec0b2dabc`)
and isometric reference, with geometry-matched `#id/ADVANCED_FACE[n]/NONE` face refs.
There is **no dimensioned bracket drawing**: its acceptance bands are plausible
example design intent, individually cited as such, not measured drawing facts.
Neither export delivery nor a CAD face identity is a tooling measurement,
clearance proof, approved route or first article.

## Standalone video examples

### T-nuts

**EXAMPLE ONLY — NOT FOR EXECUTION IN A REAL ENVIRONMENT**

[`blondihacks-t-nuts/`](blondihacks-t-nuts/README.md) is an authored plan for
four 1018-steel T-nuts, inspired by the
[Blondihacks video](https://www.youtube.com/watch?v=TL0OsfFkBL8). Its geometry
combines the video's 1 in length, 1/4 in flange and 3/8-16 thread with selected
[Carr Lane CL-0-TN catalog](https://www.carrlane.com/product/clamping-hardware/studs-bolts-t-nuts/t-nuts)
stem width (0.495 in), base width (0.875 in) and total height (0.5 in).
This is an **adapted catalog-based design**, not an exact video reconstruction
or a commercial-part replica. The bundle README owns dimension-by-dimension
provenance, authored demonstration acceptance and the physical-use boundary.

The plan, inventory, shop policy and cutting data are local to this bundle;
the manifest binds the adjacent authored STEP by digest and actual face
identities. It is not a harmonic-analyzer consumer export. Catalog dimensions
are design inputs, not evidence that the machine slots, stock, tools or fixtures
were measured. The current **29-setup, four-member demonstration** supplies
explicitly disclosed example commissioning values, including installed
tool/holder/fixture dimensions, rather than claiming missing video facts were
recovered. Five **author-selected ±0.002-in size bands** and final-only per-nut
inspections are example design decisions, not source tolerances. The provenance
ledger owns the exact dimensions, citations and measurement-marker convention.
Its sheets remain **PLANNED**, with initially blank inspection results.
Sources are cited offline; generation and validation do not fetch the video,
vendor pages or reference corpus, and downloaded media is not in the repository.

The bundle [README](blondihacks-t-nuts/README.md) and
[provenance ledger](blondihacks-t-nuts/geometry-provenance.md) own B0's source-backed
example band-speed choice, adopted stock/blade conditions and applicability limits.

Generate the report and sheets with **hobby** detail by default, or select a
presentation explicitly:

```sh
uv run prechips traveler examples/blondihacks-t-nuts/plan.toml --out out/blondihacks-t-nuts
uv run prechips traveler examples/blondihacks-t-nuts/plan.toml --detail pro --out out/tnut-detail-pro
uv run prechips traveler examples/blondihacks-t-nuts/plan.toml --detail hobby --out out/tnut-detail-hobby
uv run prechips traveler examples/blondihacks-t-nuts/plan.toml --detail pedantic --out out/tnut-detail-pedantic
```

The current expected checker exit is **0** for the disclosed demonstration
inputs, independently of detail. This is not evidence of physical measurements,
completed inspection, safe execution or release approval. It is a standalone
authored example, not one of the consumer-export targets below.

`scripts/validate_examples.py` validates its strict input schemas, local paths,
adjacent STEP binding, authored face identities, feature/finding coverage,
report and render hashes, sheet binding and expected exit. The frozen-example
tests regenerate the output twice and compare report, sheet and PNG bytes.
These checks do not establish physical readiness or first-article acceptance.

### Brass ring

[`blondihacks-brass-ring/`](blondihacks-brass-ring/README.md) follows
[Metal Lathe Tutorial 16: Your First Project](https://www.youtube.com/watch?v=t9NGty1CVII):
a **360-brass ring**, using the source-identified **PM-1022V** lathe.
The local bundle README distinguishes source observations, authored design
choices and missing physical measurements. It does not inherit the shared
demonstration-measurement inventory or claim consumer-export provenance.
Its expected exit is **4** and the traveler remains **PLANNED**; source-known
material and machine identity do not establish measured tooling, holding or
first-article acceptance.

### Magic Tube

[`blondihacks-magic-tube/`](blondihacks-magic-tube/README.md) follows
[Metal Lathe Tutorial 18: Your Second Project!](https://www.youtube.com/watch?v=-dyO4PEkEkc):
a two-piece storage tube with a removable **1/2-20 right-hand screw cap**.
The nine-setup route retains the source's one-bar parting split, cap from the
remnant, return to the long body blank, stopped-spindle die/tap work, cap
facing, repeated joint-OD turning and final part-off. It does not substitute
two unrelated raw supplies or a bonded one-piece model.

This is an explicitly adapted design. The older author article supplies
selected dimensions and **12L14 steel** as design inputs; the catalog supplies
a selected nominal round-bar size, not a finished-tube specification. The
2019 video identifies its actual material only as scrap. Its alloy and all
recipient-stock/tool/holding measurements remain unknown. The bundle README
separates those sources from the author's body-length reallocation and other
design choices; none is a measured tolerance or physical certification.

Its STEP contains two separate named finished solids. Named retained outputs
preserve their one-bar route identities, while pose, ownership and whole-solid
carriage require actual native proof. The removable threaded-joint declaration
does not prove helical geometry, usable engagement, seating, strength or a
safe assembled cutting load path. Missing facts remain unresolved rather than
an empty protected shape or automatic clearance pass. Expected exit is **4**;
the source-complete route remains **PLANNED/HOLD**, not an approved process.
Local inputs and frozen outputs use the same standalone validation lane as the
other video examples. No video, catalog or article fetch is needed at runtime.

### Historical frozen standalone evidence — 2026-10-19

The coordinated 2026-10-19 regeneration captured the actual CLI child exit,
not a shell wrapper's status. Each standalone route produced report and
traveler outputs twice, with byte-identical pairs. All three child processes
exited **4** with **no error findings**; the required unknowns remain visible.

| Bundle | Pass | Unknown | Not applicable | Checker exit |
| --- | ---: | ---: | ---: | ---: |
| `blondihacks-t-nuts` | 48 | 191 | 273 | 4 |
| `blondihacks-brass-ring` | 23 | 76 | 108 | 4 |
| `blondihacks-magic-tube` | 31 | 226 | 182 | 4 |

The frozen `expected/report.json` file SHA-256 values are:

| Bundle | SHA-256 |
| --- | --- |
| `blondihacks-t-nuts` | `c3162113996b71cf653b1c00cac9c9a527d4906b548e75c4ef1e6874341b388f` |
| `blondihacks-brass-ring` | `4fbdc4627ad2df69d04ac5b0db99b8a3be0afc5370ae8581a89cf7908317e887` |
| `blondihacks-magic-tube` | `5ad097ceb0cf92339e43c8fde53921471ae8ca00feb38b3e570bbd91b412fb4e` |

These are historical generated-output integrity and repeatability records, not
source measurements, full-suite or full-validator acceptance, independent blind
approval, physical paper rehearsal or first-article machining evidence. In
particular, the T-nut row records the earlier unknown-input route, **not** the
current complete demonstration. Its exit and hash must not be relabeled as a
new run. Frozen artifacts require coordinated regeneration against current
inputs and the default hobby presentation before current-tree comparison.
Finding counts and hashes change with operative inputs or engine changes;
the bundle READMEs continue to own the source and adaptation provenance.

## Consumer bundles and shared shop inputs

### Examples policy: plausible, labelled values

These are realistic demonstration fixtures, not shop observations or released
process plans. Existing catalogue, vendor and standard citations remain attached
to their values. Otherwise the worked inventory exercises the measured branch
with this exact, deliberately nonphysical metadata:

```toml
measured = { status = "measured", by = "example value (realistic, not a shop measurement)", date = "2026-10-11", instrument = "example fixture (no physical measurement)" }
```

`inventory/pedro-shop.toml` has **815** such measured demonstration records,
**two** deliberately assumed lead records, and **six** unchanged actual Pedro
records. The marker does not claim that someone measured the example geometry,
and it is never a recipe for clearing a real shop's measurement debt.
An `assumed`, `illustrative` or missing measurement status remains untrusted;
the engine does not recognize the `by` wording as a trust exception.

The inventory retains deliberately assumed reamer lead facts. Their use in an
operative plan remains measurement debt, not a physical measurement or a
promise about a particular finding count.

Their diameters, flute lengths, projections and shanks remain measured-branch
demonstration facts. Lead debt is not a reason to demote a different tool fact,
the machine grid or an upstream stock lineage.

The **34** plain capability fields on **30** items retain existing P3-9
bare-nominal handling: `range_mm`, `range_in`, `ra_range`, `sizes_mm` and
`blade_speed_sfm` do not gain invented measurement wrappers or automatic
`verify = true` demotions. A fact-local source comment carries the exact demo
marker and a realistic basis when the value is not grounded in a catalogue.
Those comments are disclosure only, never engine trust inputs. For the Acro
lap, the [cited vendor page](https://www.penntoolco.com/acro-lap-mfg-1-4-th-barrel-1-4-bl-005/)
gives a 1/4 in barrel and “about 15%” expansion. The unchanged `[6.35, 7.3]`
mm example range uses a conservative rounded endpoint
(`6.35 × 1.15 = 7.3025` mm); **7.3 mm is not a manufacturer-rated maximum**.

Cutting rows and policy floors keep their existing example/cite semantics;
cutting-data rows carry no measurement `status`. Anything still `"unknown"`
keeps its finding unknown.

### Consumer provenance and reconciliation

The CAD source for this reconciliation is harmonic-analyzer commit
`441290434f34f62faba176ef576af6879189c5e7`; use the exact v47 release source
and adjacent STEP and manifest identities rather than older example dimensions.
The plans are authored manufacturing proposals, not CAD authority.

The earlier M3 delivery from HA commit `b11124ecf` and its v40 example-only
patches, including permission for a built-up cone, are historical and do not
define these current parts. Its detailed provenance remains in repository
history. M4 fixtures under [`geometry/`](geometry/README.md) are independent
historical fixtures, not necessarily current production exports. Export delivery
and CAD face identities do not establish physical machining or approval.

The reference validator accepts a nominal-less dome only when its diameter
matches the base fixed by declared `base_radius` or `sphere_radius` and scalar
height, its kernel span is cited, coverage is complete and it fits held stock.
Other missing, explicitly unknown or contradictory diameter nominals stay
unresolved; a repeated numeric report field is not independent geometry evidence.

## Files and expected exits

Shared inputs:

- `inventory/pedro-shop.toml`: inventory items retain their source URLs and
  pre-existing identity verification flags. It includes tools, holders, machines,
  fixtures and gauges; unavailable facts use the string `"unknown"`.
  The 815 measured-branch demo records and two deliberate assumed leads follow
  the [examples policy](#examples-policy-plausible-labelled-values), not a claim
  of physical measurements. The centre-drill's 60° centre-seat angle is **not**
  a drill-point angle. Only the PM 6 in vise carries actual shop
  measurements: on 2026-10-05 Pedro Paulo Vezza Campos measured its jaw
  height (1.7695 in), jaw width (6.247 in), jaw-plate depth (0.7005 / 0.7010 in;
  the larger is recorded, which jaw gave which reading was not noted), maximum
  opening (6.135 in) and table-to-bed height without the swivel base
  (2.886 in). Each of those five values (and the soft-jaw item's copied bed
  reading, the same physical vise bed) carries its own
  `measured = { status = "measured", ... }` record; the vendor
  nominals stay beside it as comments, and the item's `verify = true`
  identity flag is kept. The rocker and bracket plans' jaw-overlap arithmetic
  uses the measured jaw height. Bracket S1/S2/S3 use 19.5453 / 10.3703 /
  3.6703 mm engagement on the 1 in set pair and the 1-1/8 in and 1-5/8 in
  tall narrow pairs, labelled as measured-branch demonstration fixtures.
  A 50.8 mm-wide 1-2-3 block cannot fit between jaws closed on a 16 mm foot.
- `shop-policy.toml`: shop-owned, not copied into plans. The default requires
  `tool_resolves`, `sizing`, `op_chain`, `blind_depth`, `inspection`, `coordinates`
  and `zero_check` on `"*"`. Re-fixture, thin-wall, stick-out and other policy
  numbers are labelled illustrative example values with `numbers_verify = false`.
- `cutting-data.toml`: illustrative example rows for low-carbon steel (HSS, M2,
  M42 and carbide tools; face, profile, spot, drill, ream, counterbore, bore,
  turning, dome, relief, part-off and cut-to-fit, plus saw cut-off), the
  material-force/modulus row and one deep-hole
  drill derate. Every row is labelled `example (plausible, not measured)` and its
  citation names the Machinery's Handbook 27th edition table, printed page and
  range the value sits inside (revision 5, which adds the M42 HSS lathe face,
  turning and dome rows the pivot-shaft's 3/8 in HSS tool bit uses: carbide's
  Table 1 floor is out of reach at the lathe's 2000 rpm top speed on a Ø6.35
  shaft); tool-maker, saw-maker and university
  charts appear only as secondary citations. Reamer pre-drills leave radial
  stock inside the handbook's p.1133 reamer depth of cut (.003-.004 in for holes
  1/8 in or less, .004-.008 in over). These are starting values, not shop
  measurements. The generic `Plain Carbon Steel` alias is a candidate
  classification, not a sourced grade or measured carbon content.

Existing inspection choices follow the exported feature
owners, using separate inspection steps where needed, without changing gauges or
inventing methods. Local regeneration evidence and remaining acceptance
are recorded in [PLAN §8 M3](../PLAN.md#8-milestones).

### Consumer routes and holds

Former frozen exit targets describe older inputs, not results for the
reconciled routes. Consult the actual generated report and current validation
contracts after reconciliation; no new exit or approval is asserted here.

* **Pivot shaft:** a plain shaft with two aligned same-side flats and domed
  ends. The authored route faces and centre-drills waste, turns with support,
  finishes each end, then mills the flats and inspects. It has no shoulder,
  reliefs or assembly cut-to-fit. The owner selected allocated 3/8-inch stock
  from the shop inventory despite the CAD stock note. Holding, tooling, DRO and
  surface-finish inspection still need shop evidence.
* **Cone pivot post:** integral solid-stock construction, not bonded sleeves.
  The proposed route preserves the integral bosses during turning, then
  profiles, bores and inspects them. Its material, holding, tooling and
  metrology remain unresolved. The finish instruction is held for an owner
  ruling; an old built-up paint interpretation cannot resolve it.
* **Rocker arm:** the current CAD detail drawings specify a built-up hub and
  strap. One combined route manufactures both components and declares the
  press joint from the CAD details, using the exact assembled v47 STEP; it
  does not require separate component bundles. Pressing, tooling and stock
  availability still need resolution. The old one-piece route is not authority.
* **Pivot bracket:** the independent v39 illustrative example remains
  hand-authored without a dimensioned drawing.

These are planning descriptions, not verified setups or permission to machine.

Exit precedence is **3 > 2 > 4 > 0**: bad input prevents outputs; any error beats
required unknown/unsupported/warn; only clean required subjects permit exit 0.
The validator recomputes report exits and itself exits **0** when the bundles,
stopped or clean, agree with their expectations. The combined catalogue includes
seven sampled geometry families, unknown when STEP bytes, stock, claims,
normals or required fixture dimensions are unavailable. Local regeneration
evidence and remaining acceptance are recorded in [PLAN §8 M3](../PLAN.md#8-milestones).

Plans supply stock placement, holding, coolant, DRO settings, check jogs,
paper, cut/exit allowances and inspection methods as author choices. Labelled
plausible values for unmeasured shop facts do not establish real measurements
or the assembly's actual fitted span.

The shaft and bracket plans are `plan.toml`; the cone route is
`cone-pivot-post/integral.toml`. Generated outputs and prior frozen artifacts
must not be confused with proof for changed inputs.

### Inventory provenance and measurement debt

The PM-30MV vendor nominals are spindle-to-table maximum 17 in and X/Y/Z
travel 23 / 8.75 / 14 in, recorded in `machines.PM-30MV.envelope`.
Duplicate travel/table/envelope fields are not a second source. Table size,
T-slot pitch and spindle-stack entries are not modeled; taper remains vendor
identity under `machines.PM-30MV.spindle`. Fact-local measurement requirements
are in [the inventory format](../docs/inventory.md). The measured vise bed
height is documented under shared inputs. Unmeasured worked-example dimensions
follow the [demo-fixture policy](#examples-policy-plausible-labelled-values):
explicit measured status exercises that branch without claiming a physical
observation. The two recorded assumed reamer leads remain untrusted. Real shop
inventories must supply their own measurements and provenance; copying an
example marker is not evidence.

`verify = true` with a known nominal number is measurement debt. Vendor
machine/vise/support geometry, edge-finder dimensions, instrument capability and
jaw/grip arithmetic need shop evidence where verification is required.
Changing an author choice does not clear that evidence requirement. Items
outside the selected routes retain their own unknown/verification debt.

Tool projection belongs to the selected tool/holder pair on the tool. Short
and qualified holder spellings select the same identity; duplicate entries for
that identity, including entries in both unit maps, leave projection unknown.
See [installed tool stacks](../docs/inventory.md#measured-envelopes-and-installed-tool-stacks-m5).
Holder-wide projections and suffixless legacy gauge fields are not accepted.
The [engagement screen](../docs/rules-physics.md#engagement) requires positive
authored DOC on eligible endmill cutting operations; omitted or nonpositive
DOC leaves the operation unknown.

The `envelope` and `travel` findings add concrete `measure:` instructions to
the before-you-start lines, keyed by the exact fact consumed (set member or
tool/holder pair). The vise stack uses the vise bed height, never jaw
height; Z travel is the per-op spindle-nose span (`tip + gauge + projection`),
so it also waits on holder gauges and tool projections; hole and point
centres carry no cutter-radius padding. Mill travel/envelope additionally
need explicit safe `approach_mm` and complete feature/stock extents. Missing
inputs remain debt; the examples supply labelled authored approaches and
plausible dimensions. Lathe mill-envelope/travel rows are `not_applicable`,
and no lathe operation is asked for a toolpost gauge length: there is no
`holder_stack` rule. A named holder absent from inventory must be added or
resolved before its dimensions can be measured.
Use `uv run prechips tools --measure` for the sorted, deduplicated list of
exactly the `numbers.measurements` debt behind these four consumer reports (add
`--plan` to scope it, `--inventory` to override the plans' inventory).

A shop that requires `envelope` or `travel` on `"*"` obtains exit 4 for
unresolved measured feasibility unless an existing error takes precedence.
Illustrative feasibility inputs do not establish a machine measurement,
physical rehearsal or first article.

### M4 geometry fixtures (`geometry/`)

[`geometry/README.md`](geometry/README.md) documents the discriminating
bundles and their observed FreeCAD behavior. Their inventory contains
authored nominal test tools, collets, vises and parallels, not shop
measurements. Every candidate supplies a numerically placed blank with
allowance and earlier preparation setups with bounded removals. Preparation
tooling and holding debt remains visible; local policies focus the required
geometry rows on the target operation/setup while retaining part-wide
coverage and finish requirements. Errors anywhere still stop the candidate.
Only target scenes have fully authored jaw and parallel poses.
Clearing bounds are restricted to the claimed XY footprint plus known cutter
radius. With unknown preparation tools, the synthetic rocker supply/clearance
uses the STEP global XY bbox and retains only its authored 1 mm Z allowances.

| bundle | STEP | rule it discriminates |
|---|---|---|
| `rocker-jaw-occluded/plan.toml` | real `rocker-arm.STEP`, a separately bound consumer export (the v38 `NONE`-label spike export was the initial discriminator) | `accessibility`: offset cutter cylinder beside the strap face hits the jaw and the hub boss; `vise` passes |
| `pocket-reach/plan.toml` / `long-reach.toml` | synthetic `pocket-block.STEP` | `reach`: 45 mm floor against a 19 mm flute fails; the 100 mm OAL candidate passes with the holder clear |
| `sharp-corner/plan.toml` | synthetic `slot-block.STEP` | `internal_corner_radius`: sharp vertical pocket corners against a 1/4 in cutter |
| `unclaimed-face/plan.toml` | synthetic `step-block.STEP` | `coverage`: one face cut by no op and not declared as-stock |
| `profiled-blank/plan.toml` / `machined-ends.toml` | synthetic `strap-plate.STEP` and its profiled blank `strap-blank.STEP` | `blank_credit`: the arc, edge and broad faces are supplied as cut; the 60 ±0.1 ends cannot hold the vendor's ±0.127 mm and need an op |

The first five installed-kernel candidate exits are **2 / 2 / 0 / 2 / 2**; the
profiled-blank pair exits **2 / 0**.
Block targets are S2; the rocker uses opposed preparation before its S3
upright target. Each known entry-stock render is bound to its own
`setup-S<n>.png`; preparation pictures show the raw/intermediate stock,
not a pre-cleared final part. The long-reach target is clear; the short
cutter hits its holder, the rocker hits jaw/boss material, the sharp
corner fails cutter radius (and sampled accessibility), and the uncovered
step end remains unclaimed. The project gate is recorded per PR.
Each bundle's `features.toml` binds its STEP by `step_sha256`; `author_solids.py` is
provenance for the three synthetic solids and is not a build step (its STEP
header carries a timestamp).

## Source facts, not the PLAN layout sketch

Consumer citations are relative to the read-only [pedropaulovc/harmonic-analyzer](https://github.com/pedropaulovc/harmonic-analyzer)
repository (`harmonic-analyzer/cad/...` and `cad/...` identify the same root).
The generated manifests retain Python `file:line`/line-range citations and YAML
`file:dotted.key.path` citations. Use their per-fact citations as the current
authority.
`plan.toml` is the plan author's document: blank size/placement, holding, coolant,
direction, jogs/paper, cut/exit allowances, contour steps and capable-gauge methods
are **author's choices** with plan citations and require checker validation.
Except for the documented vise measurements, the examples use
labelled plausible shop values; these do not establish measured setup binding
or shop-verified cutting data. Exported drawing/STEP identities are present.

### Current CAD source

Use the current v47 manifests and their per-fact CAD citations for dimensions,
requirements and face identities. The shaft's release pair binds
`ch-pivot-shaft.STEP` to its manifest; the current part is plain with two flats.
The rocker uses the hub and strap detail drawings, and the cone is integral.
Setup frames, blank placement, tooling and inspection methods remain authored
process choices, not evidence of measured shop capability.

The former v40 shaft fit-up, cone sleeve and one-piece rocker descriptions are
not current design authority.

The bracket's ten hand-authored features map all 16 v39 STEP faces.
`outer_face` owns the shared ear-outer/foot-near-end plane. STEP/spec nominals
are a 16 mm foot width, 24.2 mm foot run, 6 mm foot height/ear thickness,
14 mm ear width, R7 crown, 4.572 mm hold-down holes and a 6.50 mm reamed
cross-bore 25.2 mm above the seat. Acceptance bands are individually cited
illustrative design choices in
[`pivot-bracket/features.toml`](pivot-bracket/features.toml); nominal STEP
geometry is not a dimensioned drawing.

The immutable
[`dfcee1b4` example guide](https://github.com/pedropaulovc/prechips/blob/dfcee1b4432dfa04c371620765bbc884754941a6/examples/README.md)
retains earlier source readings and retired manufacturing candidates.

## Report binding and reference vocabulary

All five input paths are repository-relative POSIX paths with real SHA-256s of
file bytes. `step_sha256` is separately recorded at the report root. Reports are
UTF-8, sorted-key JSON with two-space indentation, `ensure_ascii=False`, finite
numbers only and one final LF. Findings are sorted lexicographically by
`(rule, subject)`. To compute `hash`, remove only the `hash` member, serialize the
remaining object **with the same canonical form including its final LF**, and
SHA-256 those bytes. The HTML carries the full report hash in
`<meta name="prechips-report">`; no hash prints on the sheet.
HTML is an output, not an input to its own report.
`.gitattributes` pins fixture line endings to LF.
The implemented rule vocabulary is `m5-rev12` (the combined M4 geometry and M5
measured-inventory catalogue with fail-closed measurement status), as emitted by `report.py`. Regeneration and gate
evidence belongs to [PLAN §8 M3](../PLAN.md#8-milestones).
The report retains the reference ABI's `message` and `expected_exit` names.
Finite floats use the JSON encoder's shortest round-trip representation, not drawing-format rounding. Drawing precision
is applied only to the traveler.


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
  Lathe headroom is unsupported by the mill-only rule. Known nominal frames
  do not certify measured setup binding. `stock_state.top_feature` disambiguates
  the rocker's touched hub face: machining a strap face does not move that top.
  A coordinate row's `local_from = { op, field, axis }` binds a local Z target
  to an authored operation endpoint when its model transform remains unknown;
  it does not bind the fitted shaft length to the nominal reference model.
- `speeds_feeds`: every op, including not-applicable manual operations. No
  turning, spotting or unsourced tool-material row is invented.

Report unknown numbers follow missing operative facts: speeds/feeds, tip
endpoints, gauge capability,
clearances, measured trial-cut readings and setup binding. Nominal zero recipes
and contour offsets do not claim measured readiness.

## DRO and print surfaces

The consumer worked fixtures use the
[Electronica EL400 Operation Manual](https://www.dropros.com/documents/EL400%20OpManual.pdf):
Direction and Radial/Diametric §6.2 (p20), Axis Set in ABS §7.4 (p31), Preset
§8.1 (p37, distance-to-go, **never datum zero**), and lathe trial-cut/touch-off
§9.2.1 (p62). Their digital recipes give touch → compensated Axis Set → jog
without retouch → expected/mirrored reading. Physical check jogs are 10 mm;
paper touches use 0.05 mm. Lathe trial-cut X readings and installation stay
unknown; an authored diametric X mode doubles a physical jog's displayed
increment, not its distance.

The standalone lathe examples use source-authored mechanical handwheel
procedures in inches. Their `dro.kind = "handwheel"` does not assert a digital
display, Axis Set or Preset capability. Nominal dial targets and touch/backlash
instructions do not clear missing graduation, backlash or datum measurements.
See the [readout reference](../docs/rules-coordinates.md#zero_check).

Travelers are Letter portrait with variable physical pagination. Operation
ledgers, inspection writing areas and semantic diagram panels flow onto
continuations; duplex padding preserves front-side setup starts. Footers flow
after instructions.

Before-start lines use ✗ / ! / ?. Tables apply explicit drawing precision;
known operative/manual targets retain their supplied numeric form when drawing
precision is absent, without inventing an acceptance band. Actual unknown
numbers remain `?`. Stock state, grip/stop/clamp, clearance, coolant, deburr,
tool/holder, speed/feed, direction, tip and requirement checks are present or
named unknown. No rule ids, paths or full hashes belong on the bench sheet.
Under M4 each setup page carries a kernel figure or the explicit
`? Kernel fixture render unavailable; holding geometry is not confirmed.`
paragraph when a kernel render cannot be produced. The bracket carries
the digest-bound v39 STEP and explicit setup-entry stock routing. Its S1/S2/S3
vises include posed parallel pairs; S4 includes the angle plate, a load-bearing
foot-end ledge and a two-stud bridge strap pressing the foot toward the seat datum.
A browser-rendered Letter PDF is a layout smoke proof; physical printed paper
rehearsal and first-article acceptance remain separate requirements.

### Print and native acceptance limits

Page counts depend on the current route, generated content and browser layout.
The immutable
[`dfcee1b4` print record](https://github.com/pedropaulovc/prechips/blob/dfcee1b4432dfa04c371620765bbc884754941a6/examples/README.md#dro-and-print-surfaces)
retains the dated readability baselines, their exact commits/page counts and
native controls. Local regeneration evidence and remaining physical/live acceptance
belong to [PLAN §8 M3](../PLAN.md#8-milestones).

A cache hit returns the stored facts of the run that produced it. Fresh native
bit-repeatability is unproven: the recorded bracket controls differed in six
stock-cylinder highest-Z values by 0.000001 under unchanged source-input and
STEP identities. A fresh frozen-baseline control reproduced those differences
while all six render PNG hashes matched. Their ultimate native cause and
harmlessness remain unproven; these observations do not authorize changing
values or tolerances.

Report repeatability and layout smoke proofs do not establish painter
equivalence, final print acceptance or a physical printer/pen/operator trial.

## Validation

```console
uv run python scripts/validate_examples.py
uv run ruff check scripts
```

The standard-library validator parses **every example TOML** with `tomllib`,
rejects `"unknown"` in its explicit author-choice field set (including nested
direction/contour values), checks complete rule subjects, manifest/plan references,
enumerated shop items, named missing findings and requirement-keyed inspection,
verifies orthonormal frames and coordinate transforms, tip/exit, speed/feed
arithmetic, hashes/canonical JSON/metadata binding and exit precedence. It
compares Axis Set/finder/paper/jog/mirror/retouch fields using the helper
boundaries below. It rejects obsolete YAML/CSV fixtures and checks authored
contracts without asserting geometry, material properties, gauge calibration,
first-article evidence or telemetry.
The cone checks signed landing arithmetic and full-pattern-only closure,
smallest finished exposed diameter/verified-ratio arithmetic separately from
held OD, and explicit construction permission. Unbound or incomplete finished
profiles stay unknown.
The validator recomputes clipped spindle RPM bands and slower gap endpoints,
ordinary coordinate targets and complete lathe stations from authored inputs.
It exhaustively enumerates indexing settings, including continuous/unknown
modes, and compares stick-out fit-up arithmetic and debt with the plan.
Support state, item resolution, tool compatibility, zero recipes and geometry
reuse production helpers: `stickout.support_state`, resolution,
`tool_resolves`, `zero_recipe` and `run_geometry`. Zero-recipe reuse includes
lathe setup, touch side, X touch set, tool changes/setting and verdict evaluation.
These comparisons are consistency checks, not independent oracles. They reject
inconsistent report claims without authenticating measurements or certifying machining.
Endpoint arithmetic distinguishes spot/tap depth, blind tip depth and its drawing
guard, and through breakthrough allowance. Reamers use sourced axial lead,
drills use the point cone, and boring/counterboring uses zero drill-cone length;
blind counterbores never acquire a through exit allowance.
Historical regeneration and scoped mutation evidence are retained in
[`examples/README.md`, "Validation", at `dfcee1b4`](https://github.com/pedropaulovc/prechips/blob/dfcee1b4432dfa04c371620765bbc884754941a6/examples/README.md#validation).
Local regeneration evidence and remaining acceptance belong to [PLAN §8 M3](../PLAN.md#8-milestones).

## Authoring contracts

1. `src/prechips/model.py` and the five input-format pages under `docs/` define
   the strict TOML schema. Unknown keys are bad input; literal `"unknown"` remains
   unresolved, including nested records. Lathe end stations are not mill heights.
2. Policy metadata uses `numbers_cite` and `numbers_verify` sibling tables.
   Missing policy uses the shop-required seven-rule vocabulary, never plan waivers.
3. Inspection uses exact requirement keys (`position_dia`, `finish_ra`, etc.)
   and all manifest dimension requirements, including explicit manual inspection
   for dimensions completed by another feature's operation.
4. Reports use the rule ids, subjects and canonical report ABI above.
   An absent required rule or subject is unknown, not silently checked.
5. `top_feature` identifies the touched surface; `entry_z` advances separate
   local entry surfaces. Indicated bore pickup has zero finder radius. Unknown
   frame binding never substitutes reference geometry for an actual fit.
6. Lathe diametric X doubles the displayed increment of a physical jog; per-tool
   touches are explicit. Mill headroom remains unsupported on a lathe. No
   turning, spotting or unsourced material cutting row is invented.
7. Raw RPM is rounded ties-to-even at 50 rpm **before** clamping once to the
   measured machine range. A non-50 machine boundary is never exceeded and is
   not rounded again. Contact-side compensation and DRO jog polarity are
   independent; reversed directions exchange expected and mirrored readings.
8. Missing bracket drawing bands are not consumer drawing facts. The illustrative
   example adopts plausible bands and labels every feature's design provenance.
9. Unknown STEP binding is permitted as a named unresolved finding. A known
   digest requires actual matching STEP bytes. Approval is separate evidence,
   outside the operative report inputs: one root record must match the full
   report hash and carry nonblank first-article evidence, and the report must
   be eligible (`verification = "checked"`). Optional `[inputs]` digests help
   identify changes; approval cannot waive required findings. See
   [eligibility and approval](../docs/report-and-telemetry.md#eligibility-and-approval).
10. The current shaft drawing requires two aligned same-side flats; the plan
    must preserve those requirements.
11. The built-up rocker route and its component branches are described under
    [Consumer routes and holds](#consumer-routes-and-holds). Its geometry
    is not measured inventory or physical fixture certification.
12. The renderer uses row-safe natural overflow and bounded per-setup contour
    continuations rather than fixed-height clipping. Logical HTML sections are
    not claims about physical printed pages. Paper rehearsal remains outstanding.

## Generated outputs and fixture contracts

The implementation does not read `expected/` at runtime. Reports and HTML
are generated from operative inputs; older frozen outputs are evidence only
for the inputs that produced them. Runtime does not fetch source media.
Standalone bundle READMEs own their source and adaptation records.

Bracket stock placement, hold orientation and free-run bounds are plan-author
choices, not additions to the CAD manifest. The validator derives named Z
edges from the plan, never from a report's own answer. Nominal stations do not
create a positional/datum tolerance. S2 ear-side profile entry is Z 27.2;
the free-run floor Z 0.3 is a separate surface.

Reports bind their entire contents, so computed findings and input identities
affect their hashes. Missing tool geometry, gauge capability, cutting data,
measurements or STEP binding remain unresolved when the operative inputs do
not supply them. A selected missing reference owns its error; dependent
compatibility and sizing computations remain unknown. Manual no-tool
operations do not acquire tool-compatibility subjects.

Traveler drawing dimensions retain declared precision, or their own digits
when it is absent. Operative targets print computed values; only genuine
unknowns print `?`. Transfer indication lists print as bench-readable text.
HTML metadata binds each traveler to its report; content is escaped and rows use
natural overflow. These output contracts do not establish
measured inventory, physical holding safety or first-article acceptance.

The bracket's authored route saws 38 mm from 19.05 × 31.75 mm
(3/4 × 1-1/4 in) flat bar, then squares an 18 × 26.2 × 34.2 mm blank through
P1-P6. The stock is not on hand. Each prepared face is 1 mm beyond the finished
part; size tolerances are ±0.1 / ±0.02 / ±0.02 mm. Micrometers check size and
the DTI checks flatness, squareness and parallelism to authored 0.02 mm form
limits. The six blank faces are plan-owned `process_features`, not drawing
coverage features. See [`pivot-bracket/plan.toml`](pivot-bracket/plan.toml),
stock preparation and P1-P6.

S1 faces the full raw top and preserves upper-ear stock. S2 roughs the free run
and separate side strips only to Z +16, 5.63 mm above its jaw tops. S3 finishes
the L relief, ear width and foot top before drilling the hold-down holes. All
three vise holds use no longitudinal stop. S2 picks up the surviving raw side
and free end at Z +20; S3 sets preliminary Z from the crown and picks up those
raw faces at Z +8, below the retained +16 step and 10.3 mm above its jaw tops.
The plan requires traverses above Z +32 between pickups. Grip dimensions and
parallel heights are listed under shared inputs; S3's shallow foot grip leaves
only 2.33 mm between the jaws and foot top.

S4 seats the finished seat against the angle-plate upright, outer face up.
The two-stud bridge presses the foot toward the seat; the bolted foot-end
ledge carries downward cutting load. The transfer indicates `foot_profile`,
`foot_top` and `seat_face`; X is picked up from the finished left foot face and
Y from the plate front beside the part. Alignment and transfer limits are
authored 0.001 in (0.0254 mm) TIR targets, not observed readings.

The illustrative shop-made bridge has a 63.5 × 12.7 × 9.525 mm 1018
cold-rolled beam and 3/8-16 hardware. The illustrative angle-plate casting is
drilled/tapped for the bridge and its 22.6 × 6 × 17.9 mm 1018 ledge. The ledge
is set on a 2 in 1-2-3 block while its screws are tightened, putting its top
68.7 mm above the table, then swept with the DTI. The fixture records in
[`inventory/pedro-shop.toml`](inventory/pedro-shop.toml) cite HA prints
MHA-CH-008-TL-01/02 at HA main `d4b977a58`. Their Make notes specify materials,
stock, hole positions from named edges and workholding. Drill sizes cite
Machinery's Handbook 27th ed. Table 4, p.1934; speeds cite Tables 17/20,
pp.1061/1068, feeds p.1060 and dry cast-iron drilling/tapping p.1147.
These are authored fabrication instructions and example geometry, not
measured fixture capability.

After facing the outer face, S4 checks final 6 mm ear thickness. Its R7 arch
is roughed in manual single-axis stairs with 0.3 mm leave and 0.15 mm cusp;
the 0.45 mm total is inside the illustrative 0.5 mm filing cap. S4F files to
14 g6 OD / 6.5 H7 bore buttons centered by the reamed cross-bore and checks
with the radius gauge. The buttons are illustrative bought tooling, not
measured or shop-fabricated fixtures. The bore uses 6.500 mm GO / 6.530 mm
NO-GO pins. After release, datum A rests on the surface plate; the height
gauge reads the GO-pin top minus half its diameter against the illustrative
25.1-25.3 mm bore-height band. The plan and manifest bind `example-v39`, a
local illustrative contract, not a certified dimensioned drawing revision.
All setup frames are nominal.

The original input-debt ledger, before/after counts and fixture reconciliation
remain in the immutable
[`dfcee1b4` example guide](https://github.com/pedropaulovc/prechips/blob/dfcee1b4432dfa04c371620765bbc884754941a6/examples/README.md).
Current debt comes from operative inputs and generated findings.

