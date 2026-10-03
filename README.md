# prechips

Checks before chips: a deterministic, offline checker and printable traveler for
an authored manual-machining plan. M1/M2 load five TOML inputs, evaluate declared
plan, workholding, indexing and physics rule families, write a canonical findings
report, and render Letter-portrait HTML with setup pages and contour continuations.
M4 adds seven geometry and workholding rules measured on the bundle's STEP by a
local FreeCAD kernel, plus a deterministic setup render on the sheet. M5 adds
measured machine/holder inventory, envelope/travel screens and a machine
measurement checklist. It checks declared facts and sampled B-rep measurements,
not a CAM simulation or a CAD model's machinability, and does not generate
toolpaths.

The local M1 implementation, PR #5 review corrections, M2 declared-input
feasibility rules, M4 kernel rules and M5 measured-inventory screens are
present. Physical paper rehearsal and live farm/App Insights acceptance remain
pending; neither is evidence supplied by the reference fixtures.
See [PLAN.md](PLAN.md) for milestone status and unobserved acceptance work.

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
uv run prechips traveler examples/cone-pivot-post/plan.toml --out out/cone-pivot-post
uv run prechips compare examples/cone-pivot-post/plan.toml examples/cone-pivot-post/built-up.toml --out out/cone-comparison
```

Observed reference exits are **shaft 4 / rocker 2 / bracket 2 / cone one-piece 4 /
cone built-up 2**. The shaft and one-piece cone retain required unknowns; the
rocker and bracket lack named tooling/fixtures; the built-up cone is explicitly
unauthorized by the drawing. Outputs are still written for exits 2 and 4.
All example sheets remain **PLANNED**. They are
hand-authored references, not first articles or certified CAD exports. No STEP
bytes or verified cutting-table numbers are supplied; unknown RPM/feed cells
stay unknown, and without STEP bytes every geometry rule row is `?`. See
[examples/README.md](examples/README.md) for source provenance and
reconciliation details and for the geometry fixtures that do carry STEP bytes.

The cone candidates are authored **full-envelope one-piece blank** and **block
plus pressed boss** alternatives, not route generation or a recommendation. The
built-up route is marked `✗ drawing permits one-piece only`: no drawing note
permits assembly. Its single 12.5182° journal setting prints BS-0 plate/circle,
turns and spaces; inventory verification remains due. No shaft cross-hole is
invented. Cutting-data K_c/E remains `"unknown"`, so deflection is not a
numerical machining claim. Waste uses the specification's cited analytic
finished volume and each authored stock envelope, not a guessed CAD measurement.

## CLI: five noninteractive verbs

```text
prechips [--json] [--verbose] traveler PLAN [--inventory TOML] [--policy TOML]
    [--cutting-data TOML] [--out DIR] [--approval TOML] [--json] [--verbose]
prechips [--json] [--verbose] check PLAN [--inventory TOML] [--policy TOML]
    [--cutting-data TOML] [--out DIR] [--approval TOML] [--json] [--verbose]
prechips [--json] [--verbose] tools [QUERY] [--inventory TOML] [--measure [--plan TOML ...]] [--json] [--verbose]
prechips [--json] [--verbose] compare PLAN [PLAN ...] [--inventory TOML]
    [--policy TOML] [--cutting-data TOML] [--out DIR] [--json] [--verbose]
prechips [--json] [--verbose] explain REPORT RULE[:SUBJECT] [--json] [--verbose]
```

`--help` is available globally and on each verb; global `--version` prints the
package version. `--json` and `--verbose` default off.

- **traveler** writes `report.json`, `traveler.html` and, for each setup whose
  kernel job returned a render, `setup-S<n>.png`.
- **check** writes `report.json` only; it does not merely read an existing report.
- **tools** lists inventory identities, supported set members and declared
  accessories. QUERY defaults to empty (all rows); quote a multiword query.
  Nonnumeric query words must all occur case-insensitively in the resolved row.
  A positive finite numeric token (optionally ending `mm`) requests a millimetre
  diameter; the last numeric token wins. Rows report nominal match/difference
  and verification debt, not an automatic tool choice. Human columns are ID,
  Kind, Diameter mm/in, Holder chain, Verification and Sizing; JSON emits rows.
  Inventory is mandatory through the flag or `PRECHIPS_INVENTORY`, except for
  `--measure`, which may fall back to each plan's declared inventory.
  Machine rows also show the envelope with measured/unmeasured markers.
  **tools --measure** lists the measurement debt behind the current reports:
  every `numbers.measurements` entry an unresolved finding emits for the given
  `--plan` files (default: the five shipped example plans), sorted and
  deduplicated by exact report id, set members and tool/holder pairs included,
  each with what to measure, instrument, units and citation. It is not an
  inventory-wide field walk: nothing no rule reads is listed, and it adds no
  tool purchases or unlisted set members. `--plan` is only valid with
  `--measure`.
- **compare** writes `compare.json` and a side-by-side table (JSON with `--json`):
  candidate identity, part, setup count, required fixtures, waste ratio, findings
  and construction permission. Waste is `(stock volume - finished volume) /
  stock volume`, only when the authored stock dimensions and sourced manifest
  volume are known. Unknown finished volume stays `"unknown"`; no route is chosen.
  Built-up construction is refused unless the drawing explicitly says
  `built_up_permitted`; unknown or missing drawing permission is not permission.
- **explain** validates the stored report's canonical hash and selected finding
  records, then prints their message, numbers and citations. A rule alone selects
  every subject; `rule:subject` selects that exact subject. JSON is an object for
  one match, otherwise an array. Malformed selected findings or no match are exit 3.

For bundle verbs, explicit shop-file flags override known plan `[paths]`, then
`PRECHIPS_INVENTORY` / `PRECHIPS_POLICY`; a plan-declared `"unknown"` does not
hide the environment fallback. There is **no cutting-data environment
fallback**: supply `--cutting-data` or `[paths].cutting_data`. An absent policy
uses the built-in required-rule set. CLI/environment paths are relative to the
working directory; plan declarations and `features` are relative to the plan.
Plan-declared shop files, manifest and STEP assets must stay inside the bundle
root; explicit CLI/environment shop files may be external.
`--out` defaults beside the first plan. `--approval` defaults absent and is
supported only by traveler/check. Normal traveler/check stdout is empty;
`--json` writes the fresh report there. Findings go to stderr with `✗`, `!`, `?`;
`--verbose` includes the full rule/subject table.

Exit precedence: **3 bad input/output I/O failure > 2 any rule error > 4 required
unknown/unsupported/warn or missing FreeCAD kernel > 0 eligible report**. Compare
returns the worst of 2/4/0 across its plans. Unexpected implementation failures
instead propagate a traceback with exit 1; they are not bad input. Output
preflight rejects input collisions (including hard links), escaping output
symlinks, and wrong file/directory types. Generated files are staged before
replacement, and a failed write/replacement restores prior outputs. Rollback is
not a crash or concurrent writer guarantee; see
[output safety](docs/report-and-telemetry.md#output-safety).
Existing output files can be overwritten. Malformed OTLP protocol/timeout settings
warn once and disable exporters without changing the report or checker exit.

## Formats, rules and readiness

- Inputs: [plan](docs/plan.md), [features](docs/features.md),
  [inventory](docs/inventory.md), [shop policy](docs/policy.md),
  [cutting data](docs/cutting-data.md).
- Rules: [tools and sizing](docs/rules-tools.md),
  [operations and depth](docs/rules-operations.md),
  [coordinates and zero](docs/rules-coordinates.md),
  [setup and datum](docs/rules-setup.md), [inspection](docs/rules-inspection.md),
  [lathe feasibility](docs/rules-lathe.md), [indexing](docs/rules-indexing.md),
  [physics proxies](docs/rules-physics.md), [comparison](docs/rules-comparison.md),
  [geometry and workholding on the kernel](docs/rules-geometry.md).
- [Reports, approval, renders and telemetry](docs/report-and-telemetry.md).

The literal `"unknown"` never means zero, absence, approval or a pass. A
`verify = true` inventory entry is verification debt, not certified geometry.
No invented tool dimension, Handbook page, measurement or drawing tolerance
fills a gap. Sources are citations, never network fetches at check time. The
only optional network activity is explicitly configured OpenTelemetry export.
An existing policy without `[required]`, a feature without `requirements`, or a
Z recipe without `retouch_after` is unresolved, not a known-empty declaration.
Explicit empty tables/lists remain known empty; no policy file still selects the
built-in required-rule set.

M5 machine envelope limits, fixture bed height, holder gauge/grip, tool OAL
and tool/holder projection need a fact-local
`measured = { by, date, instrument }`; clearing `verify` alone is not
measurement, and nothing is inherited from a block, item root or source. The
mill's limits live only in `machines.PM-30MV.envelope` (travel X/Y/Z,
spindle-to-table max/min), read by `headroom`, `envelope` and `travel` alike;
the vendor nominals remain unchanged and `verify = true`, minimum clearance,
vise bed height and every holder gauge/grip stay `"unknown"`, and no tool
carries a projection yet. A tool's projection is a per-holder map
(`tools.<tool>.projection_mm.<full holder ref>`), never a holder-wide or
tool-wide number. Run `uv run prechips tools --measure` for the checklist of
exactly what the current example reports are waiting on. A policy may add
`envelope = "*"` and `travel = "*"` under `[required]`; the default required
set is unchanged and there is no `holder_stack` rule. Mill envelope/travel
remain `?` until limits, bed/parallel heights, installed gauges/projections,
feature/stock spans and each operation's safe `approach_mm` are known; the
vise stack uses bed height, never jaw height, and Z travel is the spindle-nose
span, not the tool-tip span. Lathe setups do not acquire a fictitious mill
table or a toolpost gauge demand.
Omitted setup `machine`, operation `do`, and feature `kind` are normalized to
`"unknown"` by their schemas, so missing identities stay unresolved rather than
crashing the checker.

Worked located features need a complete numeric three-component centre; absent,
unknown or two-component coordinates never clear the coordinate check. A nonrough
mill contour carrying `rough_allowance_mm` prints distinct rough and finish cutter
tables, with the rough allowance added to the cutter radius.
Drawing dimensions retain their declared precision; when no precision is
declared, known values still print their own digits rather than `?`. Operative
targets, including operation-derived coordinate rows, and computed contours
retain their own numeric precision even when an unrelated drawing dimension
declares fewer decimals. A lathe X zero check remains unresolved until the DRO
radius/diameter display mode is known.

Authored bench instructions retain slash-separated text such as
`top/bottom/sides`, `S1/S2/S3` and `1/4/20`; only recognizable repository,
drive-path and URL citations are removed from the sheet. Headroom evidence uses
one `stock_height_mm` value and compares the transformed stock/fixture envelope
with machine travel, not an unused nominal profile extent.

A report with exit 0 is eligible, but its traveler still needs a matching report
hash and nonblank first-article evidence to remove **PLANNED**. Approval cannot
waive errors or required unresolved findings.

Indexing checks every landing; only a full pattern (`positions >= 2` and omitted
`angle_deg`, step exactly `360 / positions`) has a closure check. Authored angles
declare open patterns, even when their steps total a whole revolution.
The engagement screen is for endmill-family cutting operations with an authored
DOC; drills, reamers, taps, lathe tools and noncutting operations are not applicable.
Stick-out uses the smallest finished diameter along setup Z in the unsupported
length, not held bar OD; unknown exposed geometry remains unresolved.

## Geometry on the FreeCAD kernel

`accessibility`, `reach`, `internal_corner_radius`, `coverage`,
`finish_coverage`, `vise` and `thin_wall_under_clamp` run one
`freecadcmd.exe` job per check/traveler run on the bundle's STEP, found through
`FREECAD_CMD`, the installed FreeCAD 1.1, then `PATH`. No kernel means all seven
rows are `?` with one kernel-naming sentence on the console and exit 4; a
kernel failure is `✗`. Successful facts are cached locally under
`PRECHIPS_KERNEL_CACHE` (default `%LOCALAPPDATA%\prechips\geometry`) keyed by
the STEP digest, consumed geometry inputs, engine source and kernel binary.
Feature and explicit per-op `faces` are matched by each STEP `ADVANCED_FACE`'s
own geometry, never import order; invalid or far-side cutting claims are `✗`.
Fixture solids come only from a vise's explicit `jaw_height` / `jaw_width` /
`jaw_depth` / `opening`, the parallels' `height` (plus `length` / `width` for
their solids) and the plan's `fixed_jaw` / `jaws_along` / `grip_mm` /
`jaw_above_parallels_mm`, with optional authored `jaw_center_along_mm` and
`parallels_centres_mm` for the exact pose. A `verify = true` row or a missing
`jaw_depth` is debt and the setup picture is a labelled part-only view; an
undeclared jaw centre draws only the certain jaw material plus a pale
possible-jaw envelope and keeps samples inside it `?`. The render is a
deterministic rasterization of the kernel tessellation, hashed into
`report.json` with its scene record so an approval binds to it.
Each setup is checked and drawn on its authored stock envelope after earlier
setups' claimed removals, not silently on the finished solid. Non-derivable
stock is named `?` and produces no misleading setup image. Cutter exclusion is
only a thin shell of the sampled face; another claimed groove wall remains an
obstacle. Missing surface normals never become clearance or reach passes.
Kernel-absent runs remove stale setup PNGs in the same output transaction.
Nothing here is a toolpath or a certification of the physical setup. See
[docs/rules-geometry.md](docs/rules-geometry.md).

## Limits

M2 checks declared profile, stock holding, indexing and physics arithmetic;
they do not confirm a measured setup. Lathe headroom remains `unsupported`,
trial-cut measurements and example cutting data remain unknown. The
consumer's labelled face-set export exists for three parts and is bound
for the rocker; the M3 consumer-side integration (automatic manifest
export, live farm/trace rehearsal) is a separate milestone and nothing here
claims it. M4 geometry is sampled B-rep measurement
with a vise as the only modeled fixture: lathe setups have no chuck/collet
solid (`vise` not applicable, `thin_wall_under_clamp` unsupported,
accessibility unresolved). Shaft, bracket and cone reference bundles carry
no STEP bytes; the rocker binds the consumer's labelled export
(`HAF_<FEATURE>__P<nn>` face labels, kept byte-for-byte) with each
feature's default `faces` taken from that export. S1's upper strap operations
explicitly claim exported datum face B in the plan; the two tip lands remain
unclaimed. All four keep a `verify = true` vise without `jaw_depth` and an unknown
`thin_wall_floor_mm`, so their setup rows are `?`. Contour tables use
explicit manifest geometry, not extracted STEP faces. Holding completeness and
nominal clearance arithmetic are not a physical setup certification. No
measured runtime target, printed-page rehearsal or live farm trace is claimed
here.

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
