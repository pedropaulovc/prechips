# Hand-authored reference fixtures

These are concrete input/output targets for **PLAN.md rev 3**, not certified CAD exports, checker runs, toolpaths, first articles or permission to cut. Each directory contains a sidecar, an authored route, a byte-identical copy of `policy/default.yaml`, a canonical expected report, one neutral CSV per setup and a printable HTML traveler. All travelers remain **PLANNED — scoped checks only**.

The consumer is the read-only `harmonic-analyzer` repository. `source` and consumer citations name its files and line numbers; `cad/...` is relative to that repository, and the shaft's explicitly qualified `harmonic-analyzer/cad/...` citations name the same root. Numeric setup-frame choices carry cited geometry and their derivations. Stock allowances, retained gripping rails, quantities, paper compensation, RPM and roughing allowances in a **plan** are authored process choices, not new consumer dimensions or measured inventory facts.

## Fixtures and expected exits

| Fixture | Complexity / lot | Route and scope | Expected `prechips check` exit |
|---|---|---|---|
| `pivot-shaft` | Simple lathe / ×1 | Ø10 prepared bar, real journals, shoulder, both reliefs and both domes; three-jaw drive with tailstock dead-centre support, then explicit rechucks. Supply-long plain end is fitted only after the installed-ear span is measured. | **4 — not ready**: no fail/block; required unknowns remain. |
| `rocker-arm` | Medium mill / ×20 | Integral hub and thin curved strap from one flat-bar blank. Retain full-thickness rails during upper/lower vise machining, then support the part for hub, bore and final profile work. Real Ø6.50 +0.03/0 pivot bore and **#47 drilled rod hole**. | **2 — blocked**: missing reamer, mill drill chuck and supported profile fixture. |
| `pivot-bracket` | Hard mill / ×2 | Seat-up vise, foot-top-up vise, then side-on ear access on an explicitly absent angle plate. L-foot relief, arched ear, reamed cross-bore and two drilled hold-down holes. | **2 — blocked**: missing angle plate, mill drill chuck and metric reamer. |

The shaft's consumer process string says **between centres**. This primary shop control deliberately uses the confirmed three-jaw accessory for drive plus the listed tailstock dead centre and declared rechucks instead: the inventory does not establish a lathe dog/drive-plate system for a true between-centres route. Neither drive accessories nor a ball-turner are invented. The real shoulder, reliefs and **both-end** dome geometry is preserved; the stale DFM description of a plain Ø6.35 bar is not used.

The illustrative rocker `rod_tap`, 1/4-20 thread and pivot counterbore in PLAN.md are **not part features**. The real rod-pin feature is `ROD_HOLE_SPEC = HoleSpec('drilled_number', '#47')`; the bracket's screw threads belong to the receiving rail, not to either hold-down clearance hole. No blind thread has been fabricated to create a blind-depth example.

## What the rules establish

The shared policy requires all fourteen M1/M1b rules. `coverage` has severity `warn`; the other rules have severity `block`. A status is independent of its configured severity: `unknown/block` is not a failed block, but a required unknown prevents exit 0. Exit 2 takes precedence over exit 4.

- `schema`, `citations_present` and `policy_integrity` describe the declared reference input structure, supplied dimensional provenance and unchanged consumer policy. They do not certify exported geometry.
- `inventory_refs` has a finding for every selected reference. Enumerated set items resolve; candidate catalogues, empty size lists and an unlisted item do not. Listed accessories inherit their machine's verification state.
- `step_binding` is **unknown in all three**. The plan really binds the sidecar's bytes, but there is no STEP byte stream or paired certified export. `step_sha256` is exactly `<sha256 of cad/out/step/<part>.step>`. The report's `hash` is the literal `<computed>`; spec/plan/inventory/policy input hashes are real SHA-256 digests. Version fields deliberately say `reference-fixtures-rev3`, not an unimplemented checker version.
- `sizing_tool` is **not applicable** to shaft turning and non-axial feature kinds. It is **unknown** for the selected mill hole-finishing tools where geometry, a physical tool or acceptance limits are missing. The selected missing metric reamers produce real `inventory_refs fail/block` findings, not fabricated sizing failures.
- `hole_op_chain` and `op_order` validate the declared sequences: spot→drill for ordinary holes, spot→drill→ream for reamed holes, roughing before finishing. They do not prove contour access or cutter reach.
- `coordinate_table` reports frame/pickup consistency separately for each setup. Missing/unverified edge-finder geometry prevents a measured mill pickup claim. The shaft's final fit setup is unknown because its actual fitted length is absent. Blank CSV cells mean an uncommanded or unresolved coordinate, never zero by default. Profile centres are not invented or presented as toolpaths.
- `coverage` means every feature has operations and a declared inspection where required. It **does not** certify gauge capability, roughness measurement, geometric coverage or successful manufacture. Those limitations are named in the report/traveler.
- `envelope` and `holder_compat` retain unknowns for inherited `verify: true`, missing mounted-tool geometry and missing fixtures. Nominal support/jaw/clearance arithmetic is shown but is not promoted into a measured clearance proof.
- `blind_thread_depth` is **not applicable** to these three non-threaded parts: there is no honest full-thread depth, tap lead or blind-depth sum to compute. `index_representable` is **not applicable** because none of the declared feature routes uses indexing; the bracket uses an angle plate, not a made-up BS-0 adapter.

### Principal findings

| Fixture | Five findings to read first |
|---|---|
| Shaft | `step_binding(certified_export)` unknown; `coordinate_table(S3)` unknown fitted span; `envelope(S1)` unknown supported turning stack; `holder_compat(S1:80)` unknown Warner E/QCTP fit; `envelope(S2)` unknown rechuck clearance. |
| Rocker | `inventory_refs(reamers-metric/6.5-H7)` fail/block; `inventory_refs(drill-chuck-r8)` fail/block; `inventory_refs(rocker-profile-fixture)` fail/block; `sizing_tool(pivot_bore)` unknown; `envelope(S1)` unknown (S2/S3 separately reported too). |
| Bracket | `inventory_refs(reamers-metric/6.5mm)` fail/block; `inventory_refs(drill-chuck-r8)` fail/block; `inventory_refs(angle-plate)` fail/block; `sizing_tool(cross_bore)` unknown; `envelope(S2)` unknown packing/reach. |

The inch/metric mismatch is real, not a substitution opportunity: the candidate 0.2510 in reamer is `0.2510 × 25.4 = 6.3754 mm`. Against the rocker's `[6.50, 6.53] mm` band its lower-limit delta is **−0.1246 mm = −0.004905511811... in**, so it is outside the band. However, the sample inventory has `reamers.sizes_in: []`, only candidate sets and `verify: true`. It does **not** establish that physical selected reamer or measured diameter. The expected report therefore preserves sizing as unknown and blocks the absent selected metric item. Inventing an inch reamer, clearing verification or substituting another tool to manufacture a sizing verdict would be dishonest.

## Consumer values that could not be sourced

These omissions are intentional. Relevant dependent findings are unknown; inapplicable predicates remain not applicable rather than being populated with arbitrary dimensions.

### All three

- Actual STEP bytes/digest, joint certified STEP/spec export binding and a drawing revision matched to those bytes; no export-bound attestation exists. The consumer's configured next revision **v38** is known (`cad/config/release.yaml:3`), but is not evidence of a recovered certified pair. The rocker records that configured identity explicitly; the other sidecars omit an export-bound revision.

### Pivot shaft

- **Measured installed-ear span**, the **chosen fitted cylinder length**, and the resulting actual south-end/model-to-T3 axial location (`cad/scripts/pivot_shaft_spec.py:13-16,50-52`; `cad/scripts/rocker_bank_layout.py:107,112-115`). The nominal 156.67 mm span is a cited reference derivation, not the fitted value. The final cut coordinate stays blank.
- An **independent dome sphere-radius tolerance**. The radius is derived from the sourced shaft diameter and cap height; it is not assigned another invented tolerance.
- Numeric roughness requirements for crowns, reliefs and other non-running faces. The real **Ra1.6** requirements are retained only on the body, north journal and shoulder south thrust face (`cad/scripts/pivot_shaft_spec.py:104-127`).

### Rocker arm

- An explicit **geometric profile tolerance** for the curved outline, bottom arc, radial lands and tapered ends. A linear default is not silently turned into a profile tolerance.
- Explicit **flatness/parallelism** tolerances for the hub and broad strap faces.
- Roughness requirements for hub OD/faces, strap faces and profile. Only the pivot bore's Ra1.6 is specified (`cad/scripts/rocker_arm_spec.py:37-39`).
- A single blanket **decimal_precision**. Consumer annotations use different precision; sourced individual/default provenance is retained instead.
- An exact **1018 alloy requirement**. The material-family expansion is `LOW-CARBON STEEL OR GRAY IRON` (`cad/config/parts/_defaults.yaml:25-27`); 1018 is an explicitly authored low-carbon-steel choice in the route, not a new source requirement.

### Pivot bracket

- **Drawing sheet identity, displayed precision and applicable default-tolerance provenance**. There is no `draw_pivot_bracket.py` or bracket `DrawingSpec` in the current drawing registry; the MHA-123 identifier/configured release metadata does not supply that missing drawing contract.
- **Cross-bore diameter upper/lower deviations**, and diameter deviations for each hold-down hole. Nominal 6.5 and 4.572 mm are sourced. The spec's internal ligament-design bands and generic drilled-hole title-block row are not asserted to be an absent bracket drawing's acceptance limits.
- **Position tolerance** for the cross-bore and both hold-down holes.
- **Foot/ear profile acceptance bands**, seat/foot-face **flatness**, and numeric **roughness** requirements.
- A **material grade/standard** beyond `Plain Carbon Steel`.
- **Black-oxide recipe/acceptance, dimensional effect and bore masking**. The black-oxide finish itself is known and retained (`cad/config/parts/pivot-bracket.yaml:4`); a coating description is not an invented numeric surface finish.

### Consumer open items

Untoleranced dimensions use one authority: exact numeric `title_block.yaml value_in × 25.4` (0.03 in→0.762 mm, 0.02 in→0.508 mm, 0.005 in→0.127 mm). The consumer currently displays rounded metric values **0.8 / 0.51 / 0.13 mm** (`cad/config/title_block.yaml:19-27`), and some consumer design calculations use those displayed bands. That numeric/display discrepancy needs a consumer decision; these fixtures do not change consumer files or pretend the values are equal. Explicit feature bands, such as shaft +0/−0.020 and rocker bore +0.03/0, remain authoritative.

## Shop measurement and availability debt

This is separate from missing **consumer** dimensions. The sample inventory's old comment about verification warnings is superseded by PLAN rev 3: `verify: true` and `present: null` mean **unknown**, inherited through references. They never authorize clearing an unknown to pass.

Before any envelope/holder result can become measured, obtain applicable machine soft-limit travel, spindle-nose-to-table maximum, vise bed height, actual support heights/jaw engagement, holder gauge length/insertion, tool projection/flute/OAL/shank geometry, chuck jaw swing/grip, tailstock usable reach and actual centre-seat geometry. The rocker fixture and angle-plate/clamp arrangements also need physical design and measurement. Existing mill cutting tools, drills and measuring instruments are not upgraded to qualified bore/roughness gauges by an `inspect` entry. Stock is procurement/preparation, not an assertion that the empty stock inventory has been replenished.

## Validate and read the outputs

```console
uv run scripts/validate_examples.py
```

The PEP 723 script uses PyYAML, parses every example YAML, rejects duplicate YAML keys, checks feature references and operation coverage, resolves enumerated inventory items and enforces inherited verification/presence uncertainty, checks structured Z pickup/frame conventions, verifies the real file hashes, checks canonical report bytes and complete finding subjects, and checks every CSV's setup/operation rows. It is not a second machining checker.

Missing references must exactly match the expected report's `inventory_refs fail/block` findings. The successful validator prints these **expected misses** and exits **0**:

```text
rocker-arm: drill-chuck-r8
rocker-arm: reamers-metric/6.5-H7
rocker-arm: rocker-profile-fixture
pivot-bracket: angle-plate
pivot-bracket: drill-chuck-r8
pivot-bracket: reamers-metric/6.5mm
```

`expected/report.json` is sorted-key UTF-8/LF JSON; findings are sorted by `(rule, subject)` with evidence kept in declaration order. `.gitattributes` pins fixture input/output line endings to LF so file digests survive Windows/Linux checkouts. Rendered HTML bytes are not report inputs. Open each `expected/traveler.html` and print on Letter; there is no JavaScript or PDF dependency. CSVs are neutral absolute mm setup tables, with diameter-mode X for the lathe, not EL400 presets or a cutter-compensated contour program.
