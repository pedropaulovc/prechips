# prechips

prechips checks an authored manual-machining plan against a feature manifest, shop inventory, policy and cutting data. It writes a findings report and printable setup sheets with workholding, DRO-zero instructions, operations and inspection records.

Geometry checks use a local FreeCAD kernel. The checker does not generate toolpaths or certify a physical setup, finished part or machining process.

Start with the [quickstart](docs/manual/quickstart.md), or use the [documentation index](docs/README.md) to find a task or reference.

## Install and check

You need Python 3.12 or newer and [uv](https://docs.astral.sh/uv/). From a source checkout:

```sh
uv sync --locked
uv run prechips --help
```

The [quickstart](docs/manual/quickstart.md) covers FreeCAD discovery and your first result. The [development guide](docs/internals/development.md) covers tests, native fixtures, package validation and contributor review.

## Run the examples

From the repository root:

```sh
uv run prechips traveler examples/pivot-shaft/plan.toml --out out/docs-smoke/pivot-shaft
```

Read the [worked tutorial](docs/manual/tutorial.md) for the input-to-sheet workflow and the [input/output demonstration](docs/manual/demo.md) for actual excerpts. The [example guide](examples/README.md) owns each bundle's provenance, demonstration-value disclosures and expected exit. Outputs can still be written when the checker exits 2 or 4.

Example values exercise the rules; they are not measurements to copy into a real shop inventory. An exit-0 report is eligible for approval. Without a valid first-article approval record, the printable sheet remains PLANNED.

## CLI: five noninteractive verbs

| Command | Result |
| --- | --- |
| `prechips traveler` | Fresh report, printable HTML and available setup images. |
| `prechips check` | Fresh report without the printable sheet. |
| `prechips tools` | Inventory search or a plan-specific measurement-debt checklist. |
| `prechips compare` | Side-by-side findings for authored candidates. |
| `prechips explain` | Evidence from selected findings in a saved report. |

Use the [CLI catalog](docs/reference/cli.md) for arguments, flags, path precedence, output streams and exit codes. The [Python callable catalog](docs/reference/python-api.md) describes importable implementation functions and their support boundary.

## Formats, rules and readiness

The [documentation index](docs/README.md#look-up-an-interface) links the five input formats, rule families and output contracts. Use [troubleshooting](docs/manual/troubleshooting.md) to resolve an input error or unresolved finding, and the [FAQ](docs/manual/faq.md) for product capabilities and limits.

The literal `"unknown"` is unresolved debt. A source citation, vendor nominal, declared procedure or generated picture does not establish a physical measurement. Approval cannot waive rule errors or required unresolved findings. See [eligibility and approval](docs/report-and-telemetry.md#eligibility-and-approval).

## Geometry on the FreeCAD kernel

The [geometry reference](docs/rules-geometry.md) defines face identity, stock evolution, prescribed approach models, sampled workholding and collision screens, caches and renders. Its [limits](docs/rules-geometry.md#limits) explain what these measurements cannot establish. The [architecture guide](docs/internals/architecture.md) describes the host/native boundary.

A missing kernel leaves required geometry unresolved and produces exit 4. A valid explicit `FREECAD_CMD` can select an installation; an invalid override prevents fallback discovery. See [FreeCAD troubleshooting](docs/manual/troubleshooting.md).

## Machinist review of a traveler (dev tool)

The [development guide](docs/internals/development.md) describes the blind printed-page review, handbook references and contributor commands. This hosted-model review is separate from the offline product checks and from physical paper acceptance.

## Limits

Passing the checker does not prove a continuous cutter path, dynamic stability, real clamping, tool condition, operator execution or finished dimensions. Generated reports and PDFs do not establish physical paper rehearsal, first-article machining or parented live farm telemetry acceptance.

[PLAN.md](PLAN.md) records delivery and acceptance status. The [example guide](examples/README.md#print-and-native-acceptance-limits) records the limits of the bundled evidence. Internal proposals are separate from the shipped input and rule contracts.

## DRO reference

The [DRO and print references](examples/README.md#dro-and-print-surfaces) identify the EL400 manual and emulator relationship. The [zero-check reference](docs/rules-coordinates.md#zero_check) defines what prechips checks. A printed recipe does not certify the emulator or a physical touch-off.
