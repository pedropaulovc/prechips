# Prechips prototype

Prechips restarted at **v0.10**. The current milestone is **v0.7**: pivot-shaft hobby setup pictures and narrow round-stock support. It remains a prototype until Pedro finds it useful, not a machining certification system.

## Scope and milestones

- Develop in small, usable milestones. Pedro approves each milestone. Never work more than three milestones ahead of his last review.
- v0.10: a machine-readable manual-manufacturing process in TOML and a simple CLI producing printable traveler HTML for harmonic-analyzer's `ch_rocker_arm_tl_oblique_base_bar`.
- v0.2: `pro` and `hobby` presets plus custom TOML profiles. Enforcement is limited to setup-rendering completeness. Hobby includes practical authored SVG setup diagrams and selects optional operation `instruction_detailed` in place of `instruction`; custom profiles opt in with `detailed_instructions`. No CAD/FreeCAD requirement. Pro is the default.
- v0.3: bind dimensions, drawing identity and diagram feature geometry to the selected CAD/drawing export. Keep process choices explicit. Prefer released data over importing CAD code or reconstructing dimensions from drawings.
- v0.4: both built-in profiles compare declared rectangular blank dimensions with the CAD nominal envelope in explicit length/width/thickness correspondence; custom profiles may omit `stock_fit`. No automatic stock rotation, parent-bar yield, machining allowance or machining simulation. Successful checks add nothing to the sheet.
- v0.5: explicit part adapters bind finished dimensions, setup coordinates and inspection limits from the selected feature manifests. Keep source geometry and requirements separate from authored tooling, allowances, fit-to-assembly choices and gauges. The bracket manifest remains illustrative example intent, not a released dimensioned drawing. These adapters do not imply stock-fit support or generated setup pictures.
- v0.6: plans may explicitly reference one shared shop TOML for tool descriptions and named material/tool cutting settings. Local fields override shared fields individually. Do not infer identities, calculate recommendations or parse settings out of operation prose.
- v0.7: built-in hobby supports the pivot shaft's four CAD-manifest-driven setup elevations. Keep arriving material, active cuts, datums and support orientation consistent with the plan; fixture symbols are schematic. Round-stock diameter covers nominal shaft geometry, and available length covers the authored sawn-blank demand, not a fixed fit-to-assembly finish length. No native CAD engine or general setup simulation.
- Pro prints only what an experienced operator needs: tools, setups, feeds, speeds and inspections, with the dimensions and instructions necessary to perform them. No tutorials, repeated warnings, checker reports or internal identifiers. Omit routine technique and generic safety reminders ("lock head", "short stickout", "power off", stopping/retracting, cleaning/reseating); retain part-specific workholding, datums and cutting requirements.
- For a requested hobby method, author concise, actionable, part-specific `instruction_detailed` in the operation itself. It replaces the pro instruction, never follows or repeats it; retain shared settings and inspection limits. Explain unfamiliar attachment setup once, then reference that method with each later operation's own dimensions.
- Specify datum locations and acceptance dimensions, not generic measuring-tool technique. Pro omits edge-finder speeds, hand-feed instructions, tip-radius offsets and compensated inspection readings; hobby may explain a source-backed attachment measurement needed to carry out the job.
- The pro base-bar traveler must print on no more than two Letter pages at readable type size. Hobby may use extra pages for readable setup diagrams and requested specific methods. Use operator shorthand in pro; keep hobby detail nonduplicated and actionable. Do not print process-status notes such as "untried", "unverified" or certification commentary; state tooling, work instructions and inspection requirements directly.
- Number setups and operations. Use aligned tables for work instructions, cutting settings, coordinates and inspection criteria; keep full tool specifications in the tooling list and short labels in operations.
- Assume normal shop equipment (collets, drill chuck, calipers, micrometer, rule, indicator, marker, dead-blow). Omit it from the tool list; list specified cutting tools and job-specific equipment instead.
- The previous implementation is preserved on `archive/pre-v0.10-2026-11-08`. Pull old code, data-schema ideas or FreeCAD logic only when a concrete approved milestone needs them. Do not migrate the old architecture wholesale.

## Keep it small

- No integrity checks, SHA-256 machinery, validation certificates, attestation systems, evidence bundles or speculative infrastructure.
- No general checker/rule framework, geometry engine, telemetry or inventory database unless an approved milestone needs it. Profiles select implemented features only; CAD bindings and the targeted stock-fit comparison do not justify restoring the legacy checker.
- Basic input errors and HTML escaping are ordinary functionality, not a validation subsystem.
- Do not invent machining dimensions, feeds, speeds, stock, tooling availability or inspection results. Use source-backed instructions; mark missing operating facts plainly and locally. A rendered sheet is not machining approval.
- Prefer the standard library and straightforward code. Keep the authored process readable without knowing the implementation.

## Development

- Use Python 3.12+ and uv only for environments, dependency changes and execution. Keep `pyproject.toml` and `uv.lock` together.
- Tests: bare-minimum end-to-end smoke coverage, plus focused tests only for particularly fragile or complex logic. No golden-output bureaucracy, source-text assertions, exhaustive combinatorics or heavyweight validation suites.
- Run the real CLI and inspect the actual print layout before delivering a milestone. Do not confuse automated tests with physical shop verification.
- Update the short README and schema documentation when their public contract changes. Do not grow a documentation hierarchy for this prototype.
- Preserve unrelated user files and local outputs. Archive source history before removing superseded tracked files.
- Publish changes in a PR; do not merge a milestone before Pedro approves it.
