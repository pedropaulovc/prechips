# Prechips prototype

Prechips is starting over at **v0.10**. It is a prototype until Pedro finds it useful, not a machining certification system.

## Scope and milestones

- Develop in small, usable milestones. Pedro approves each milestone. Never work more than three milestones ahead of his last review.
- v0.10: a machine-readable manual-manufacturing process in TOML and a simple CLI producing printable traveler HTML for harmonic-analyzer's `ch_rocker_arm_tl_oblique_base_bar`.
- Print only what an experienced operator needs: tools, setups, feeds, speeds and inspections, with the dimensions and instructions necessary to perform them. No tutorials, repeated warnings, checker reports or internal identifiers.
- The base-bar traveler must print on no more than two Letter pages at readable type size. Use operator shorthand, not tutorials. Do not print process-status notes such as "untried", "unverified" or certification commentary; state tooling, work instructions and inspection requirements directly.
- The previous implementation is preserved on `archive/pre-v0.10-2026-11-08`. Pull old code, data-schema ideas or FreeCAD logic only when a concrete approved milestone needs them. Do not migrate the old architecture wholesale.

## Keep it small

- No integrity checks, SHA-256 machinery, validation certificates, attestation systems, evidence bundles or speculative infrastructure.
- No checker/rule framework, geometry engine, telemetry, inventory database, verbosity tiers or compatibility layer unless an approved milestone demonstrates a real need.
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
