# prechips

prechips checks an authored manual-machining plan against a feature manifest, shop inventory, policy and cutting data. It writes a findings report and printable setup sheets with workholding, DRO-zero instructions, operations and inspection records.

Geometry checks use a local FreeCAD kernel. The checker does not generate toolpaths or certify a physical setup, finished part or machining process.

Start with the [quickstart](https://github.com/pedropaulovc/prechips/blob/main/docs/manual/quickstart.md), or use the [documentation index](https://github.com/pedropaulovc/prechips/blob/main/docs/README.md) to find a task or reference.

## Install and check

You need Python 3.12 or newer and [uv](https://docs.astral.sh/uv/). From a source checkout:

```sh
uv sync --locked
uv run prechips --help
```

The [quickstart](https://github.com/pedropaulovc/prechips/blob/main/docs/manual/quickstart.md) covers FreeCAD discovery and your first result. The [development guide](https://github.com/pedropaulovc/prechips/blob/main/docs/internals/development.md) covers tests, native fixtures, package validation and contributor review.

## Run the examples

From the repository root:

```sh
uv run prechips traveler examples/pivot-shaft/plan.toml --out out/pivot-shaft
uv run prechips traveler examples/rocker-arm/plan.toml --out out/rocker-arm
uv run prechips traveler examples/pivot-bracket/plan.toml --out out/pivot-bracket
uv run prechips traveler examples/cone-pivot-post/built-up.toml --out out/cone-pivot-post
uv run prechips traveler examples/blondihacks-t-nuts/plan.toml --out out/blondihacks-t-nuts
uv run prechips traveler examples/blondihacks-brass-ring/plan.toml --out out/blondihacks-brass-ring
```

Read the [worked tutorial](https://github.com/pedropaulovc/prechips/blob/main/docs/manual/tutorial.md) for the input-to-sheet workflow and the [input/output demonstration](https://github.com/pedropaulovc/prechips/blob/main/docs/manual/demo.md) for actual excerpts. The [example guide](https://github.com/pedropaulovc/prechips/blob/main/examples/README.md) owns each bundle's provenance, demonstration-value disclosures and expected exit. Outputs can still be written when the checker exits 2 or 4.

Example values exercise the rules; they are not measurements to copy into a real shop inventory. An exit-0 report is eligible for approval. Without a valid first-article approval record, the printable sheet remains PLANNED.

The standalone [Blondihacks T-nuts example](https://github.com/pedropaulovc/prechips/blob/main/examples/blondihacks-t-nuts/README.md) adapts a video process with explicitly selected catalog dimensions. It uses local shop inputs, not harmonic-analyzer exports or the shared demonstration-measurement inventory. Source observations, catalog design choices and missing real measurements remain distinct; the sheet stays PLANNED.

The standalone [brass-ring example](https://github.com/pedropaulovc/prechips/blob/main/examples/blondihacks-brass-ring/README.md) follows [Metal Lathe Tutorial 16: Your First Project](https://www.youtube.com/watch?v=t9NGty1CVII), with source-known 360 brass and a PM-1022V lathe. Its local inventory retains real measurement debt; expected exit 4 does not release the PLANNED traveler.

Slitting-saw recognition is limited to mill-mounted tooling; it does not establish full physical support. Finite disk/arbor clearance, the mounted assembly, engagement and mounted-zero evidence remain unresolved. See the [tool rules](https://github.com/pedropaulovc/prechips/blob/main/docs/rules-tools.md) for the supported checks and limits.

## CLI: five noninteractive verbs

| Command | Result |
| --- | --- |
| `prechips traveler` | Fresh report, printable HTML and available setup images. |
| `prechips check` | Fresh report without the printable sheet. |
| `prechips tools` | Inventory search or a plan-specific measurement-debt checklist. |
| `prechips compare` | Side-by-side findings for authored candidates. |
| `prechips explain` | Evidence from selected findings in a saved report. |

Use the [CLI catalog](https://github.com/pedropaulovc/prechips/blob/main/docs/reference/cli.md) for arguments, flags, path precedence, output streams and exit codes. The [Python callable catalog](https://github.com/pedropaulovc/prechips/blob/main/docs/reference/python-api.md) describes importable implementation functions and their support boundary.

## Formats, rules and readiness

The [documentation index](https://github.com/pedropaulovc/prechips/blob/main/docs/README.md#look-up-an-interface) links the five input formats, rule families and output contracts. Use [troubleshooting](https://github.com/pedropaulovc/prechips/blob/main/docs/manual/troubleshooting.md) to resolve an input error or unresolved finding, and the [FAQ](https://github.com/pedropaulovc/prechips/blob/main/docs/manual/faq.md) for product capabilities and limits.

The literal `"unknown"` is unresolved debt. A source citation, vendor nominal, declared procedure or generated picture does not establish a physical measurement. Approval cannot waive rule errors or required unresolved findings. See [eligibility and approval](https://github.com/pedropaulovc/prechips/blob/main/docs/report-and-telemetry.md#eligibility-and-approval).

An authored `op.rpm` is a requested speed, not a verified recommendation. The requested value takes precedence over calculation, including an explicit `"unknown"` request with no computed fallback. Known machine-limit violations are errors; unresolved safety inputs keep a visible STOP. See [requested RPM](https://github.com/pedropaulovc/prechips/blob/main/docs/cutting-data.md#authored-rpm).

## Geometry on the FreeCAD kernel

The [geometry reference](https://github.com/pedropaulovc/prechips/blob/main/docs/rules-geometry.md) defines face identity, stock evolution, prescribed approach models, sampled workholding and collision screens, caches and renders. Its [limits](https://github.com/pedropaulovc/prechips/blob/main/docs/rules-geometry.md#limits) explain what these measurements cannot establish. The [architecture guide](https://github.com/pedropaulovc/prechips/blob/main/docs/internals/architecture.md) describes the host/native boundary.

Named finished solids, retained part-off outputs and removable threaded assembly routes require explicit identities and material ownership. A nominal thread match is not proof of engagement, seating, strength or a collision-free assembled cut. The [plan reference](https://github.com/pedropaulovc/prechips/blob/main/docs/plan.md) defines retained outputs and threaded joints; unresolved registration and physical engagement remain debt.

A missing kernel leaves applicable geometry unresolved and produces exit 4 unless a rule error takes precedence with exit 2. A valid explicit `FREECAD_CMD` can select an installation; an invalid override prevents fallback discovery. See [FreeCAD troubleshooting](https://github.com/pedropaulovc/prechips/blob/main/docs/manual/troubleshooting.md#freecad-is-installed-but-geometry-says-the-kernel-is-unavailable).

## Machinist review of a traveler (dev tool)

The [development guide](https://github.com/pedropaulovc/prechips/blob/main/docs/internals/development.md) describes the blind printed-page review, handbook references and contributor commands. This hosted-model review is separate from the offline product checks and from physical paper acceptance.

## Limits

Passing the checker does not prove a continuous cutter path, dynamic stability, real clamping, tool condition, operator execution or finished dimensions. Generated reports and PDFs do not establish physical paper rehearsal, first-article machining or parented live farm telemetry acceptance.

[PLAN.md](https://github.com/pedropaulovc/prechips/blob/main/PLAN.md) records delivery and acceptance status. The [example guide](https://github.com/pedropaulovc/prechips/blob/main/examples/README.md#print-and-native-acceptance-limits) records the limits of the bundled evidence. Internal proposals are separate from the shipped input and rule contracts.

## DRO reference

For digital readouts, the zero recipe uses the Electronica EL400 Direction §6.2 and ABS Axis Set §7.4 functions. Preset §8.1 is not a zero-setting command. Mechanical handwheels instead use `dro.kind = "handwheel"` and their declared units and procedures; they do not acquire digital Axis Set or Preset instructions. Missing graduation, backlash or physical datum evidence remains unresolved. See the [readout contract](https://github.com/pedropaulovc/prechips/blob/main/docs/rules-coordinates.md#zero_check).

- [EL400 Operation Manual](https://www.dropros.com/documents/EL400%20OpManual.pdf)
- [Changing read direction](https://www.dropros.com/documents/400%20ScaleDirection.pdf)
- [Bolt-hole circle](https://www.dropros.com/documents/EL400BoltHole.pdf), [linear hole pattern](https://www.dropros.com/documents/EL400AngleHole.pdf) and [arc](https://www.dropros.com/documents/EL400Arc.pdf)

The consumer is [harmonic-analyzer](https://github.com/pedropaulovc/harmonic-analyzer). The shop uses the [el400 emulator](https://github.com/pedropaulovc/el400). A printed recipe does not certify the emulator or a physical touch-off. See the [DRO and print surfaces](https://github.com/pedropaulovc/prechips/blob/main/examples/README.md#dro-and-print-surfaces) and the [zero-check reference](https://github.com/pedropaulovc/prechips/blob/main/docs/rules-coordinates.md#zero_check) for the checker and printing boundaries.
