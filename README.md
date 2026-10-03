# prechips

Checks before chips: a deterministic, offline checker and printable traveler for
an authored manual-machining plan. M1 loads five TOML inputs, evaluates twelve
rule families, writes a canonical findings report, and renders Letter-portrait
HTML with a header, setup pages and contour continuations. It checks declared
facts, not a CAD model's machinability. It does not generate CAM toolpaths.

The local M1 implementation is present. Physical paper rehearsal and live
farm/App Insights acceptance remain pending; neither is evidence supplied by the
reference fixtures. See [PLAN.md](PLAN.md) for the remaining milestones.

## Install and check

Python 3.12 or newer; use [uv](https://docs.astral.sh/uv/).

```sh
uv sync --locked
uv run pytest
uv run scripts/validate_examples.py
uv run ruff check .
uv run ruff format --check .
```

These are development commands, not claims that this documentation change ran
them. The example validator checks the authored fixture contract; it is not a
machining checker and its successful exit is 0 even when examples correctly
stop with 4 or 2.

## Run the examples

From the repository root (the plans name their shared inputs):

```sh
uv run prechips traveler examples/pivot-shaft/plan.toml --out out/pivot-shaft
uv run prechips traveler examples/rocker-arm/plan.toml --out out/rocker-arm
uv run prechips traveler examples/pivot-bracket/plan.toml --out out/pivot-bracket
```

Expected checker exits are **4, 2, 2**, respectively: the shaft has required
unknowns; the rocker lacks an R8 chuck, 6.5 H7 reamer and supported profile
fixture; the bracket lacks an angle plate, chuck and reamer. Outputs are still
written for exits 2 and 4. All example sheets remain **PLANNED**. They are
hand-authored references, not first articles or certified CAD exports. No STEP
bytes or verified cutting-table numbers are supplied; unknown RPM/feed cells
stay unknown. See [examples/README.md](examples/README.md) for source provenance
and reconciliation details.

## CLI: five noninteractive verbs

```text
prechips [--json] [--verbose] traveler PLAN [--inventory TOML] [--policy TOML]
    [--cutting-data TOML] [--out DIR] [--approval TOML] [--json] [--verbose]
prechips [--json] [--verbose] check PLAN [--inventory TOML] [--policy TOML]
    [--cutting-data TOML] [--out DIR] [--approval TOML] [--json] [--verbose]
prechips [--json] [--verbose] tools [QUERY] [--inventory TOML] [--json] [--verbose]
prechips [--json] [--verbose] compare PLAN [PLAN ...] [--inventory TOML]
    [--policy TOML] [--cutting-data TOML] [--out DIR] [--json] [--verbose]
prechips [--json] [--verbose] explain REPORT RULE[:SUBJECT] [--json] [--verbose]
```

`--help` is available globally and on each verb; global `--version` prints the
package version. `--json` and `--verbose` default off.

- **traveler** writes `report.json` and `traveler.html`.
- **check** writes `report.json` only; it does not merely read an existing report.
- **tools** lists inventory identities, supported set members and declared
  accessories. QUERY defaults to empty (all rows); quote a multiword query.
  Nonnumeric query words must all occur case-insensitively in the resolved row.
  A positive finite numeric token (optionally ending `mm`) requests a millimetre
  diameter; the last numeric token wins. Rows report nominal match/difference
  and verification debt, not an automatic tool choice. Human columns are ID,
  Kind, Diameter mm/in, Holder chain, Verification and Sizing; JSON emits rows.
  Inventory is mandatory through the flag or `PRECHIPS_INVENTORY`.
- **compare** writes `compare.json` and a table (JSON with `--json`): part, setup
  count, declared fixtures, finding counts and exit. `waste_ratio` is explicitly
  `"unknown"`; it does not calculate stock waste or choose a route.
- **explain** validates the stored report's canonical hash and prints matching
  findings' message, numbers and citations. A rule alone selects every subject;
  `rule:subject` selects that exact subject. JSON is an object for one match,
  otherwise an array. No matching finding is exit 3.

For bundle verbs, explicit shop-file flags override plan `[paths]`, then
`PRECHIPS_INVENTORY` / `PRECHIPS_POLICY`. There is **no cutting-data environment
fallback**: supply `--cutting-data` or `[paths].cutting_data`. An absent policy
uses the built-in required-rule set. CLI/environment paths are relative to the
working directory; plan declarations and `features` are relative to the plan.
Plan-declared shop files, manifest and STEP assets must stay inside the bundle
root; explicit CLI/environment shop files may be external.
`--out` defaults beside the first plan. `--approval` defaults absent and is
supported only by traveler/check. Normal traveler/check stdout is empty;
`--json` writes the fresh report there. Findings go to stderr with `✗`, `!`, `?`;
`--verbose` includes the full rule/subject table.

Exit precedence: **3 bad input/write failure > 2 any error > 4 required
unknown/unsupported/warn > 0 eligible report**. Compare returns the worst of
2/4/0 across its plans. Output preflight rejects input collisions (including
hard links), escaping output symlinks, and wrong file/directory types. Validation
and preflight happen before writes; an I/O failure during writing is not a
transactional rollback guarantee. Existing output files can be overwritten.

## Formats, rules and readiness

- Inputs: [plan](docs/plan.md), [features](docs/features.md),
  [inventory](docs/inventory.md), [shop policy](docs/policy.md),
  [cutting data](docs/cutting-data.md).
- Rules: [tools and sizing](docs/rules-tools.md),
  [operations and depth](docs/rules-operations.md),
  [coordinates and zero](docs/rules-coordinates.md),
  [setup and datum](docs/rules-setup.md), [inspection](docs/rules-inspection.md).
- [Reports, approval and telemetry](docs/report-and-telemetry.md).

The literal `"unknown"` never means zero, absence, approval or a pass. A
`verify = true` inventory entry is verification debt, not certified geometry.
No invented tool dimension, Handbook page, measurement or drawing tolerance
fills a gap. Sources are citations, never network fetches at check time. The
only optional network activity is explicitly configured OpenTelemetry export.

A report with exit 0 is eligible, but its traveler still needs a matching report
hash and nonblank first-article evidence to remove **PLANNED**. Approval cannot
waive errors or required unresolved findings.

## Limits

M2 lathe/profile/indexing feasibility rules are not implemented. Some authored
lathe coordinates, transfer declarations and hole arithmetic are displayed, but
lathe headroom is `unsupported`, trial-cut measurements remain unknown, and this
is not a claim of M2 acceptance. M3 automatic complete manifest export and M4
kernel geometry/workholding/accessibility/collision checks and fixture renders
are absent. Contour tables use explicit manifest geometry, not extracted STEP
faces. Holding completeness and nominal clearance arithmetic are not a physical
setup certification. No measured runtime target, printed-page rehearsal or live
farm trace is claimed here.

## DRO reference

The zero recipe uses the Electronica EL400 functions: Direction §6.2, ABS Axis
Set §7.4; Preset §8.1 is not a zero-setting command.

- [EL400 Operation Manual](https://www.dropros.com/documents/EL400%20OpManual.pdf)
- [Changing read direction](https://www.dropros.com/documents/400%20ScaleDirection.pdf)
- [Bolt-hole circle](https://www.dropros.com/documents/EL400BoltHole.pdf),
  [linear hole pattern](https://www.dropros.com/documents/EL400AngleHole.pdf),
  [arc](https://www.dropros.com/documents/EL400Arc.pdf)

Consumer: [harmonic-analyzer](https://github.com/pedropaulovc/harmonic-analyzer).
The shop uses the [el400 emulator](https://github.com/pedropaulovc/el400); printed
recipes do not certify the emulator's behavior.
