# prechips documentation

Use prechips to check an authored manual-machining plan against its feature manifest, shop inventory, policy and cutting data, then produce a findings report or printable setup sheets. Geometry checks use a local FreeCAD kernel. Passing the checker does not certify a physical setup or a machining process.

## Start with a task

| You want to | Read |
| --- | --- |
| Install from a checkout and produce your first setup sheet | [Quickstart](manual/quickstart.md) |
| Understand how a plan becomes findings and setup sheets | [Work through a plan](manual/tutorial.md) |
| Compare real demonstration input with its output | [Input and output demonstration](manual/demo.md) |
| Diagnose an error, unresolved finding or missing output | [Troubleshooting](manual/troubleshooting.md) |
| Check product capabilities and limits | [FAQ](manual/faq.md) |

The [shipped example guide](../examples/README.md) owns bundle provenance, demonstration-value disclosures and expected exits. Example values are not instructions to certify a real shop's measurements. The [project plan](../PLAN.md) records delivery status and acceptance work.

## Look up an interface

The manual above explains workflows. These catalogs define command and file contracts.

### Commands and Python

- [CLI catalog](reference/cli.md): the five commands, flags, path precedence, output streams and exits.
- [Python callable catalog](reference/python-api.md): actual importable entry points and their stability boundary.
- [Reports, approval, output safety and telemetry](report-and-telemetry.md): saved evidence, eligibility, printable output and exporter configuration.

### Input files

| File | Purpose |
| --- | --- |
| [Plan](plan.md) | Authored stock, frames, setups, operations and inspection choices. |
| [Feature manifest](features.md) | Part identity, source geometry, drawing requirements and acceptance bands. |
| [Inventory](inventory.md) | Machines, tooling, fixtures, gauges, stock and fact-local provenance. |
| [Shop policy](policy.md) | Required rules and shop-owned limits. |
| [Cutting data](cutting-data.md) | Cited material/tool/operation starting data and interpolation. |

### Rules

| Domain | Reference |
| --- | --- |
| Tool identities, assemblies and sizes | [Tools and sizing](rules-tools.md) |
| Operation chains, order, depth and cutting starts | [Operations](rules-operations.md) |
| Coordinates, manual arcs and DRO zero | [Coordinates](rules-coordinates.md) |
| Holding, headroom, measured travel, datums and consistency | [Setup](rules-setup.md) |
| Gauges, requirement coverage, process holds and finishing | [Inspection](rules-inspection.md) |
| Turned profiles, support and chuck/collet capacity | [Lathe](rules-lathe.md) |
| Dividing-head settings and cumulative error | [Indexing](rules-indexing.md) |
| Declared deflection, engagement and cutting-force models | [Physics](rules-physics.md) |
| Construction and authored-candidate comparison | [Comparison](rules-comparison.md) |
| Native geometry, stock evolution, workholding and renders | [Geometry](rules-geometry.md) |

A rule's reference explains what it consumes, how it decides and what it cannot establish. Report rule identifiers belong in these references; operator-facing setup sheets use shop language.

## Understand or change the implementation

- [Architecture](internals/architecture.md): data flow and module responsibilities.
- [Development](internals/development.md): environment, tests, native fixtures, packaging and review.
- [Module-split design and tooling](module-split.md): internal decomposition, evidence and constraints.
- [Fixture commissioning design](design/commissioning-phase.md): design status and once-per-installation work.
- [Area-hold design](design/area-hold.md): typed adhesive holding, force/capacity decisions and implementation status.
- [Documentation style guide](style-guide.md): page structures, writing conventions, examples and verification.

Internal designs may contain proposals or remaining work. Use the input and rule references for the shipped contract. Physical paper rehearsal, first-article machining and parented live farm telemetry each require their own observed acceptance evidence.
