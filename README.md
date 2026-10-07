# prechips

Checks before chips: a deterministic, offline checker and printable traveler for
an authored manual-machining plan. M1/M2 load five TOML inputs, evaluate declared
plan, workholding, indexing and physics rule families, write a canonical findings
report, and render a Letter-portrait shop traveler: per setup, one front sheet
(STOP box, holding steps beside the picture, tools, DRO zero and operations with
speeds/feeds and inspection, ops continuing on its back when long) plus attached
sheets for the full-size picture, clearance, notes and contour tables; print it
double-sided, and blank backs keep every sheet starting on a front side (see
docs/report-and-telemetry.md, "Generated traveler").
M4 adds eight geometry and workholding rules measured on the bundle's STEP by a
local FreeCAD kernel, plus a deterministic setup render on the sheet. M5 adds
measured machine/holder inventory, envelope/travel screens and a machine
measurement checklist. It checks declared facts and sampled B-rep measurements,
not a CAM simulation or a CAD model's machinability, and does not generate
toolpaths.

The local M1 implementation, PR #5 review corrections, M2 declared-input
feasibility rules, M3 consumer-export bundles, M4 kernel rules and M5
measured-inventory screens are present. M4 also delivers `approach = "rotary"`:
horizontal dividing-head samples presented at top dead centre to a vertical
cutter, with window-bounded radial and wall-tangent cutter-column removal
outside the finished part. Op windows may claim part of a face; coverage and
finish coverage need the exact union of the claiming windows to cover the
whole face. This is sampled geometry, not continuous toolpath
proof. The combined integration gate remains unobserved for this delivery;
physical paper rehearsal and live prechips farm/App Insights acceptance remain
pending. Exported CAD inputs are not evidence of those gates.
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

Install [FreeCAD 1.x](https://github.com/FreeCAD/FreeCAD/releases) for real
geometry checks. Discovery uses `FREECAD_CMD` first, the installed Windows
FreeCAD 1.1 path next, then `FreeCADCmd`/`freecadcmd` on `PATH`. For example,
set `FREECAD_CMD=/opt/freecad/bin/freecadcmd` on Linux or
`$env:FREECAD_CMD = 'C:\Program Files\FreeCAD 1.1\bin\freecadcmd.exe'` in
PowerShell. An explicit nonexistent override disables discovery rather than
falling back to the host installation.

Without a kernel, geometry-dependent tests skip with `FreeCAD kernel not found`;
the remaining tests still run, including explicit absent-kernel contracts.
Set `PRECHIPS_REQUIRE_KERNEL=1` to make a missing kernel a test-session error.
CI requires it and caches the official FreeCAD 1.1.0 Linux AppImage, pinned by
version and SHA-256 and extracted without FUSE. The product still reports
unknown geometry (`?`, exit 4) without FreeCAD; skips do not change that behavior.

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
uv run prechips traveler examples/cone-pivot-post/built-up.toml --out out/cone-pivot-post
```

Current expected consumer CLI exits are **shaft 0 / rocker 2 / bracket 2 / cone
built-up 0**. Inspection choices follow the exported feature owners. Missing
tooling, holding and inspection capability keep their stops. The cone example
carries explicitly labelled construction, signed-station, step-corner and copied
length/height-band divergences from the upstream export; these are not claims
that the original drawing or export was corrected.
Lathe geometry uses a radial sampled turning screen with modeled chuck obstacles;
spindle-axis drilling actions retain the axial approach. Neither proves a toolpath.
Only the consumer side of M3 is done; the HA follow-ups and the combined gate
evidence are in PLAN §8 M3. Outputs are still written for exits 2 and 4.
All example plans remain **authored** and their sheets **PLANNED**. The shaft
and rocker consume harmonic-analyzer `features.toml` exports; the cone records
its example divergences beside the affected fields. Each keeps its adjacent
STEP file. The pivot-bracket manifest remains hand-authored.
Exported geometry does not certify the route, tooling, setup or first article.
No verified cutting-table numbers are supplied; unknown RPM/feed cells stay
unknown. See [examples/README.md](examples/README.md) for export provenance,
source-contract changes and the separate synthetic geometry fixtures.

The cone keeps a single authored **built-up** candidate; the one-piece plan and
its example comparison are retired by the 2026-10-06 user decision. It is a
**bonded-sleeve** route, not route generation or a recommendation: a turned body
and head, a cone sleeve bonded in a cross-bore and a crank sleeve bonded in a
head socket with retaining compound, both running bores reamed after cure.
Drawing permission alone does not prepare or assemble material: plan-only
socket/spigot features, each joint's clearance band and cure, and assembly
remain checked. Its 12.5182° settings print BS-0 plate/circle, turns and
spaces. No shaft cross-hole is invented, and unknown physical or cutting facts
are never numerical machining claims.

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
  tool purchases or unlisted set members. It evaluates only the host-side
  measurement rules (headroom, envelope and travel) and never launches FreeCAD;
  referenced inputs and STEP hashes are still validated.
  `--plan` is only valid with `--measure`.
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

Native [saw cut-off](docs/plan.md#saw-cut-off) supports `saw_cut` / `cut_off` on
mill, bench and bandsaw setups: an explicit blade-centre plane plus inventory
kerf removes only the discarded stock side. The traveler shows cited blade sfm
and descent feed, not spindle RPM; cylinder-based accessibility explicitly does
not apply. Dividing-head headroom uses centre height and the posed axis offset,
and child hole operations inherit a missing travel centre from their named
parent/hole while explicit unknown locations remain debt.

The literal `"unknown"` never means zero, absence, approval or a pass. A
`verify = true` inventory entry is verification debt, not certified geometry:
on an item it leaves that identity unresolved for the declared-input rules,
on one length fact it leaves only that fact unresolved.
No invented tool dimension, Handbook page, measurement or drawing tolerance
fills a gap. Sources are citations, never network fetches at check time. The
only optional network activity is explicitly configured OpenTelemetry export.
An unknown cutter radius leaves `stock_removal_bounds` `?` with a
missing-radius reason and later stock unresolved; it never substitutes zero.
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
tool-wide number; when the selected pair has an entry that entry alone
decides, so an `"unknown"` entry never falls back to OAL − grip, and only an
absent pair uses tool OAL minus the selected holder's grip. Run `uv run
prechips tools --measure` for the checklist of
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
unknown or two-component coordinates never clear the coordinate check. A mill
feature map prints each located target on the DRO grid. A target holding a
height-like band from its `height_from` reference must stand inside the printed
band at that grid point, or the setup's coordinates are `✗`. A plan `aims` entry
may move the target within the band for a stated process reason (the cone
aims its crank bore at mid-band separation). It never moves geometry. A nonrough
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
`finish_coverage`, `vise`, `thin_wall_under_clamp` and `fixture_interference`
run one `freecadcmd.exe` job per check/traveler run on the bundle's STEP, found
through `FREECAD_CMD`, the installed FreeCAD 1.1, then `PATH`. No kernel means all eight
rows are `?` with one kernel-naming sentence on the console and exit 4; a
kernel failure is `✗`. Successful facts are cached locally under
`PRECHIPS_KERNEL_CACHE` (default `%LOCALAPPDATA%\prechips\geometry`) keyed by
the STEP digest, consumed geometry inputs, engine source and kernel binary.
Feature and explicit per-op `faces` are matched by each STEP `ADVANCED_FACE`'s
own geometry, never import order; invalid or approach-invalid cutting claims are `✗`.
Fixture solids come only from explicit inventory dimensions and plan poses:
a vise's `jaw_height` / `jaw_width` / `jaw_depth` / `opening`, the parallels'
`height` (plus `length` / `width` for their solids) and riser blocks, with the
plan's `fixed_jaw` / `jaws_along` / `grip_mm` / `jaw_above_parallels_mm` and
optional authored `jaw_center_along_mm` and `parallels_centres_mm`; a 3- or
4-jaw chuck's body/bore/jaw dimensions with `hold.pose` and `jaw_clock_deg`
(a dividing head adds its own authored `solids` and the chuck `hold.chuck`
names); a dead centre with its tailstock quill; and authored `solids` boxes
and cylinders for angle plates, custom fixtures and clamping-kit straps placed
by `hold.pose` / `hold.clamps`. Every drawn solid is an accessibility and
holder obstacle, and the report's scene lists each component and its
`fixture_kind`. Those fixture dimensions, the
tool `dia` / `flute_len` / `oal`, the holder `gauge_dia` / `gauge_len` /
`grip` and the tool/holder projection are read as M5 fact-local length
facts with measurement not required: a plain nominal number is accepted
geometry without `by`/`date`/`instrument`, a fact whose own record carries
`verify = true` or an incomplete `measured` is debt for that dimension only,
and an item-level `verify` / `present` / `source` flag never withholds that
item's numbers from the kernel. The M5 `envelope` / `travel` screens
separately require complete shop measurements of the same holder gauge/grip,
tool OAL and projection facts (and `headroom` of the envelope limits), so a
geometrically checked op can still be M5 measurement debt. A
missing `jaw_depth` or a debt-carrying jaw fact is debt and the setup picture
is a labelled part-only view; an
undeclared jaw centre draws only the certain jaw material plus a pale
possible-jaw envelope and keeps samples inside it `?`. Setup diagrams are
1600×1000 deterministic PNGs with an engine-bundled bitmap font: lathe side
elevations, mill isometric views and custom-plate plan views, with labelled
axes, Z0, datums, holding, stickout and the selected tool's approach. Amber
hatching shows this setup's derived material removal (entry minus exit stock);
profile sketches share waypoint keys with the traveler tables. Authored clamp
order and posed inventory stops are shown explicitly. Dashed machine-context
outlines are schematic, not measured fixture geometry, and unresolved drawing
items remain plain-language warnings. The image is hashed into `report.json`
with its scene record so an approval binds to it; it is not a toolpath.
Before encoding, every setup diagram checks its rounded bitmap-text bounds:
labels must keep an 8-pixel canvas margin and a 4-pixel gap from other labels,
and no label may print below body size (21-pixel cap height, about 7 pt on
Letter). Dense callout lanes rebalance and tighten their leading instead of
shrinking type. An overlap, clipped or undersized annotation refuses the render
rather than shipping an unreadable picture. Footer space is reserved for every
legend and note row. A posed chuck front that is tilted relative to setup Z
draws no single jaw-front Z; `scene.jaw_front_oblique` records it, and the
picture prints no commentary about it.
Setup notes come from the declared ops: a setup without a machine-cutting op
lists its bench actions (for example deburr, coating, inspect), and a deburr
setup is never labelled "no material removed".
Shallow contour insets explicitly label Y-only graphic magnification; their
coordinate tables and the setup view remain unchanged. Custom-fixture pad and
clamp badges sit outside the projected fixture and part outline, in x order with
uncrossed leaders to their actual positions; a badged clamp or pad group's lane
entry is its key and draws no second leader. A lane leader's elbow never runs
along an axis through another callout's point. Optional authored void labels
identify mounting holes.
The lathe's filled meridian section keeps the retained core visible inside the
removed annulus; its jaw-end inset magnifies nearby shoulders and reliefs.
Dashed nominal part outlines locate mill/custom-fixture targets without
pretending that incoming stock already has the finished shape. Cutter captions
reuse the traveler's human tool names, with a separate declared feed-direction
arrow when available. Missing saw-plane data stays a STOP/stock debt, not a
renderer crash.
A tailstock context symbol without a drawn centre is not a selected or verified
support.
Every cutter-centre contour row and every hole op's tool-axis X/Y prints on the
setup DRO grid; contour rows round to the side that leaves material, and a
finish row with no safe grid point inside its feature's band is an error. Raster
and outline rows that run past the stock are labelled cutter clearance; a
raster's pass ends are called clear air when they stand a cutter radius past the
op's stock box, or walled (plunge in material) when inside it. A contour cut in
several depth levels lists every level once, in its heading. Contour tables
repeat their op, tool and Z on a continued page and never wrap a coordinate.
The mill CLEARANCE section prints a short stack/travel verdict and a per-op table
of the closest obstacle (headroom, jaw tops, holder face above the stock beside
the tool, or a reach finding's declared clearances) with the clearance and the
action; an unknown clearance is a check-at-the-machine action, a negative one a
STOP. The FEATURE MAP names what each mill row stands on (hole axis, arc centre,
face) and gives a lathe row's drawing Ø limits apart from the size turned to. A
surface-alignment sweep tells the operator to tap the work, not move the table;
the job page's abbreviation key lists only abbreviations the sheets print.
Inspection procedures may be authored as step lists that print
numbered, with recording blanks and a separate calculation line
([plan format](docs/plan.md)).
Each setup is checked and drawn on the input explicitly selected by `stock_in`:
`"stock"` for one supply, `"stock.<id>"` for a built-up component, or any earlier
setup id, not only the previous one. Every two-reference assembly array requires
a cited `joint`: either a fitted cylindrical socket/spigot pair or a surface
joint with authored finite butt interfaces. A bare Boolean union is not a
physical joining process. All supplies and outputs remain model-frame;
assembly adds no implicit transform. Components require known, nonempty, unique
ids matched exactly, with no ASCII character whitelist, and their own
`origin_mm`, `axis` and `section_axis` pose facts, with root-stock semantics. Each contains
only its own piece, not the whole finished STEP; missing component geometry
remains individual debt. Setup outputs subtract their own derivable removals.
Known branches remain usable while another component's geometry is missing.
When all component envelopes are known, their union must contain the finished
STEP; otherwise all component references carry geometry debt.
A nonempty root `as_is_faces` declaration needs the full joined supply exterior
and every component envelope known, so it can withhold otherwise-known branches.
Empty or omitted declarations add no cross-component dependency. Removal
fragmentation is checked per input solid; deleting one piece cannot mask
splitting another.
Unknown or forward authored references, including `"unknown"`, are bad input
(exit 3); omitted `stock_in` remains debt, never auto-linear. Non-derivable stock is named
`?` and produces no misleading setup image.
Joined references must have disjoint supply ancestry: duplicate entries and
joining a supply with its descendant are bad input (exit 3), naming the shared
ancestor. Independent route alternatives may restart from the same supply but
cannot join that material lineage twice.
Plan-owned `joint_features` describe cylindrical sockets and spigots prepared on
component stock for a joint, separately from the exported finished-part manifest;
the traveler prints them as plan-only joint preparation, not drawing dimensions.
Their operations participate in sizing, inspection and geometric clearance.
They earn finished STEP-face coverage only where the kernel measures that an
accepted finishing spigot turn leaves an exported face as its own surface,
over the face's full area. Declared fit bands must cover the
worst-case mating diameters, prepared geometry must reach the join along the
selected stock lineage, and the kernel refuses interference outside the
permitted fit or missing component-owned finished material at the join.
Unknown joint dimensions or retaining-compound process facts withhold the union
and its render, rather than assuming a fit or cure. Each assembly step joins
exactly two disjoint inputs: an existing assembly may receive one new component.
Finite both-open cylindrical sockets accept turned sleeves; clearance joining
fills the mating annulus, not a sleeve's intentional bore. Retaining-compound
travelers state surface prep, cure time and do not disturb until cured.
See [the plan format](docs/plan.md) for the authored fields.

Cutter self-contact exclusion is only a thin shell of the sampled face;
another claimed groove wall remains an obstacle. Every sample of an ordinary
+Z planar face (transient joint faces and hole ops keep their own poses),
concave floor corners included, stands on its nearest legal centre. The tip
height comes first: `max(face z + leave, to_z) + LIFT`. A centre is legal when
it lies outside the branch's certain material (current components within their
raw supply, without permitted unjoined sockets) and at least ρ from its section
at that height, where ρ is the cutter radius `r` for finishing and `r + a`
for roughing; the axis may move at most ρ, so a rough cutter is not asked to
finish a wall foot its leave keeps. A legal sample keeps its axis. Otherwise
the nearest legal centre within ρ wins; equally near ones (within one fixed
1e-7 mm, never a radius or `STOCK_TOL`) go to the one nearest the face's area
centroid, then the least (x, y). With none within ρ the sample keeps its axis
and the native check reports the genuine hit, so a sharp corner the cutter
cannot reach is a hit, not a cleared pose. Candidates are exact offsets of the
nearby line and Z-circle section edges (exact single axes and 2r strips
included), certified against the whole native section. Only the section at the
tip height steers the axis: overhangs, leave below it, future hole cores and
unclaimed raw do not, but the full flute against the accepted after-op stock
and the holder against setup-entry stock still meet them there. Another curve
near an illegal sample has no exact offset, so the sample needs a native
nearest-bound certificate over the whole native section (every edge, the
approximating B-splines the native slice returns included, and every certain
solid; nothing newly approximated or ignored). With q the section's one native
closest point and d = |p − q|, every axis at least ρ from q is at least ρ − d
from p, so c = q + ρ(p − q)/d with exact clearance ρ is the unique nominal
nearest axis. Native acceptance uses the fixed 1e-7 mm, so a legal c only
proves no accepted axis is more than 1e-7 mm nearer (no uniqueness among
accepted axes is claimed): c joins the supported candidates and the unchanged
ranking: the nearest enumerated distance `best` lies in [d_c − 1e-7, d_c],
where d_c = |c − p|; the selected distance is at most `best + 1e-7`, and
therefore at most `d_c + 1e-7`. It certifies a sample outside every certain
solid (1e-7 < d < ρ) or one on
exactly one native straight line (d ≤ 1e-7, not strictly inside, foot more
than 1e-7 mm inside both ends, exactly one legal normal).
Precision policy is conservative: a closest point on an unsupported curve whose
native tolerance exceeds 1e-7 mm refuses, and neither ρ nor 1e-7 mm grows;
spline, circle, seam, corner and vertex boundaries stay uncertified by scope.
The tie-band radii R(d) = √(ε² + 4ρε(ρ − d)/d) and R_B = √(ε² + 4ρε) (ε =
1e-7 mm; about 0.0015 mm at ρ = 3, d = 1) are numeric context, never a radius
allowance or an eligibility gate. An uncertified sample (a farther legal axis
never substitutes), an ambiguous section (a face starting or ending at that
height, an open wire) or missing raw supply leaves that floor's pose undefined:
it drops only its own poses, other faces' certain hits stay and the op's
measured facts are `unknown`.
A legal centre does not certify
corner radii. Floor-only claims do not certify wall/wall corners;
`internal_corner_radius` retains its existing scope and checks a sharp
wall/wall corner when the operation claims both walls.
Adjacent finished walls, including undercut/leaning walls, are not removed
to manufacture clearance.

A milling or hole flute meets the stock its setup's earlier derived cuts
leave (one pass in op order before measuring; a later cut is never credited)
and alone excludes its op's own accepted cut: its derivable outside-finished
allowance or, for drill/spot/ream/bore/tap/counterbore, its own actual cutter
volume to declared depth or explicit through extent. The op whose cut stops
that pass is credited none of its failed clearance. After an underivable
earlier cut, later flutes keep only certain finished-material hits and their
tool hits are unknown, deliberately, even where entry stock would read clear.
Final wall
and cap debts never change a before-op stock. Turning keeps its own
turned-profile obstacle model.
Hole axes/centres derive from geometry-matched concave cylindrical faces
aligned to setup Z. Missing depth/entry and explicitly unknown through facts
remain debt; absent `thru` keeps the existing blind-hole default.
Spot and drill cut with a point cone (apex at the tip) and full-radius body;
the tool's numeric included `point_angle` is mandatory, and an unknown angle
is named accessibility debt and leaves later stock unresolved, never a flat
cylinder or default angle. The flute check uses that cone and body against
part and all modeled fixture solids; holders retain full setup-entry stock. Spot
`depth_mm` is the apex tip depth; drill `depth_mm` is full-diameter depth, its
tip a point length `r / tan(angle/2)` deeper; an op `to_z` is the absolute
actual tip. A through drill exits each matched bore's actual axial bottom plus
its point; other through actions end at that bore bottom, never the raw-stock
bounding-box bottom. Ream, bore, tap and counterbore remain flat-bottomed
cylinders. A hole op wider than its matched bore removes its own bore wall to
the op radius with no fixed radial cap; the sizing rule owns drill/reamer
diameter. A spot never widens its own bore.
Spot and tap honor explicit depth even on a through feature. A hole
operation's own bore radius is diameter-sizing, not an `internal_corner_radius` limit.
Claimed point caps are not blanket-exempt: only an op's own known matched
cone/sphere cap, below and sharing an edge with its claimed Z-parallel bore,
is checked against unmodified stock instead of an impossible
offset shell, and is not an internal corner. Its actual collision still
counts; wider countersinks and unrelated caps keep their unknowns and hits.
Each feature's last drill, ream, bore or counterbore (setup then op order; a
thread's last drill, never a pilot, spot or tap) must also form its own
claimed caps: they must be clear of that setup's final stock, judged without
a `to_z` clip, leave or tolerance. A touched cap is not a collision; it is
output-stock debt and a `finish_coverage` error, even when no later setup
consumes that stock. An unmeasurable completion makes that credit unknown.
Stock-state `top_z`/`entry_z` and op `depth_mm` are millimetres even for
inch-unit features; tap fallback feature-depth bands convert to millimetres.
Unrelated finished material and holder obstacles remain. A rough milling op's
scalar `rough_allowance_mm` (a) is an engine-consumed leave normal to the
finished surface: each sample moves `a` along the unit normal before the
cutter-radius XY shift, planar floor samples need legal clearance `r + a`, derived
stock protects the finished solid offset outward by `a` (drafted faces
included), and later finishing ops remove it. An explicit `to_z` caps the endpoint rather
than adding a second leave; a finishing op's numeric `to_z` above its face is
likewise its actual tip (a 0.1 mm spring pass samples there, not at the
floor). An unknown leave is accessibility and later-stock
debt. A failed arc-join offset may use a validated, conservative
intersection-join offset (extra leave at convex corners), never the nominal
solid. If both fail on the whole part, each consumer of the guard uses the
exact arc-join offset of the finished part within its own box (that box
grown by `2a`, then cropped), and lineage bands use exact claimed-face
skin primitives that are cut one by one. Any failure is named offset debt.
Holding, rendering, reach and holder obstacles still use actual setup-entry
stock; a flute is never credited with a later op's removal. Missing surface
normals or unresolved pose facts never become
clearance or reach passes.
Facing uses a planar outer-wire sweep to clear raw caps over hole mouths
while preserving finished islands. `stock_removal_bounds` is an authored
cleared footprint (possibly several passes), not capped to the claims' XY
bounding box plus cutter radius and not a toolpath proof; known radius,
finite bounds, stock intersection, finished protection, exact claim/piece
contact, future hole columns and no split of an original solid still apply.
Generic bounded clearing preserves known
unclaimed planned-hole columns for their own future hole operations, not all
concave cylindrical faces.
Those reserved columns span the actual matched bore plus any adjacent coaxial
concave cone/sphere cap no wider than the bore, using exact axial spans and
numerical lift at either end, not the entry-stock height. Wider back
countersinks are not reserved, blind columns stop at their caps, and
pins/rods outside that span remain. One exception: a bounded facing op
(`face`, `rough_face`, `finish_face`) releases a column whose bore opens on one
of its claimed +Z planar faces (a shared native edge, with face material outside
the bore's nominal cylinder; a planar blind bottom, annular or slightly tilted,
lying wholly inside it is a closed cap, not an opening) above that face's cut
height `max(face z + a, to_z)` (the highest such claim's, no lift), and only
inside its box, guard window and own outer-loop sweep: facing removes that
core there. The column below that height, other bores and any core outside
that scope stay reserved, and the flute and holder still meet them.
Kernel-absent runs remove stale setup PNGs in the same output transaction.
Nothing here is a toolpath or a certification of the physical setup. See
[docs/rules-geometry.md](docs/rules-geometry.md).

## Machinist review of a traveler (dev tool)

`scripts/machinist_review.py` gives a printed traveler to a blind senior
machinist: `codex exec` or `claude -p` in a neutral temp directory, with no repo
context, reading only the page images, under the calibrated prompt in
`scripts/prompts/machinist_review_traveler.md`. It is ported from
harmonic-analyzer's drawing review and its drawing simplicity policy. Missing
and unneeded content both count as defects. The two tests are **no questions**
and **nothing the operator doesn't need to run the job**. This is a developer
tool that calls a hosted model. It is not part of `prechips check`, so the
offline, no-network rule for checks is unchanged.

The reviewer also judges whether speeds, feeds, depths of cut, stickouts and
tool choices are realistic for the material, tool and machine, even when they
are example values. A value that would break the tool, exceed the machine or
scrap the part is a blocker; one far outside the usual range but survivable is
a clarity finding, and so is a value that matters for which the reviewer can
establish no reference range. The summary names the comparison basis.

Cutting data is checked against Machinery's Handbook (27th edition). Point
`--handbook DIR` or `PRECHIPS_HANDBOOK_DIR` at the `machinerys-handbook` folder
that holds the page-level `corpus/` (harmonic-analyzer's references repo). The
handbook is never vendored: `scripts/prompts/handbook_refs.toml` lists only
PDF and printed page numbers for the pilot operations (1018 turning, end
milling, drilling and reaming with their adjustment factors, the reamer
stock-allowance prose, centre drills, band-saw speeds, automatic-screw-machine
cutoff and form tools, and inch and metric tap drills). Those `corpus/pages`
files are embedded as text in both reviewers' prompts, and findings cite the
table and printed page. Claude may also Read anything under `corpus/` and the
handbook PDF (linked into its neutral directory) to look up other values; Codex
gets only the embedded pages, because a shell lookup would break blindness. A
named handbook without `corpus/README.md`, a manifest page missing from the
corpus, a page whose header names another printed page, or a corpus built from
another PDF is an error (exit 2). With no handbook named, the run warns, judges
from memory, and records `handbook: null`.

```sh
uv run scripts/machinist_review.py --reviewer codex --traveler out/pivot-shaft
uv run scripts/machinist_review.py --reviewer claude --bundle examples/rocker-arm/plan.toml
uv run scripts/machinist_review.py --reviewer codex --pdf printed-traveler.pdf
uv run scripts/machinist_review.py --reviewer codex --png page-1.png --png page-2.png
```

`--reviewer` is required. It must be the other model family from whoever wrote
or last edited the traveler code or plan: Claude-authored work gets `codex`,
Codex/GPT-authored work gets `claude`. Defaults are `gpt-6-astra` at low effort
and `claude-fable-5-1` at medium (`--model`, `--effort`). `--traveler DIR_OR_HTML`
prints `traveler.html` to a Letter PDF with headless Chrome or Edge, giving the
duplex-padding script time to run, then renders every page at 300 dpi with
pypdfium2. The browser comes from `PRECHIPS_CHROME`, then the standard Windows
Chrome/Edge installs, then `PATH`. An invalid `PRECHIPS_CHROME` is an error.
`--bundle PLAN` runs `uv run prechips traveler` into a temp directory first, with
the caller's `FREECAD_CMD` and `PRECHIPS_KERNEL_CACHE`. Options repeat, and
`--jobs` reviews travelers in parallel.

Each traveler's report goes to `out/machinist-review/<part>/`: `review.json`,
`review.md`, the reviewer event stream, per-attempt output with a
`codex resume` / `claude --resume` command and the page PNGs. `--traveler` and
`--bundle` reviews also include the printed PDF.
`out/machinist-review/index.md` lists every traveler. The JSON records the
SHA-256 of every page. `--traveler` and `--bundle` reviews also record hashes
for `traveler.html` and the printed PDF, plus the `report.json` hash from the
traveler's `prechips-report` meta tag; `--pdf` reviews record the input PDF
hash. Its `handbook` entry records the handbook directory, the SHA-256 of the
corpus README, the manifest and every embedded page, and for Claude the
handbook files and PDF pages it read. Exit is 0 only when every
traveler passes: the review stayed blind (any tool use beyond reading the copied
pages and the handbook fails it, and Claude must still read every page), the
verdict is `CLEAR`, and there is no blocker, clutter or clarity finding. Minor
findings are recorded but do not gate.

## Limits

M2 checks declared profile, stock holding, indexing and physics arithmetic;
they do not confirm a measured setup. Lathe headroom checks stock/chuck swing
and between-centres length; trial-cut measurements remain unknown and the example cutting data are labelled illustrative values, not shop measurements. The
consumer's labelled manifests and adjacent STEP exports are consumed for all
three drawn pilot parts (M3); pivot-bracket remains authored. Export delivery
does not establish live prechips farm/trace acceptance or physical readiness.
M4 geometry is sampled B-rep measurement
with vise, chuck, dividing-head, centre, angle-plate, clamp and custom
fixture solids drawn only from explicit dimensions and poses; collets have no
solid. Lathe setups keep `vise` not applicable; `thin_wall_under_clamp` samples
material under modeled chuck jaws. Turning accessibility is a radial sampled
necessary-condition screen, not a toolpath, carriage-stroke or chatter proof.
Rotary milling uses `approach = "rotary"` with
`hold.index.rotation = "continuous"` on a horizontal dividing head.
`z_from`/`z_to` run along the head axis from the chuck pose origin;
`angle_window_deg` bounds the head rotation. The window is a partial-face
claim: only the part of each claimed face inside it is sampled and removed,
and a window holding none of a claimed face is a claim error. Each sample is
checked at top dead centre, including wall-tangent cutter poses at concave
edges, curved pad perimeters included. Own-removal
combines radial sweep with those vertical cutter columns, clipped to the
window and cut against the finished solid; finished bosses/pads, retained
stock and holder/fixture obstacles are not waived. A face counts for
`coverage` (or, from finishing ops only, `finish_coverage`) when the exact
B-rep union of its window portions, across cutters, ops and setups, covers it;
a remaining gap is an error naming its spans, an undecided union stays `?`,
and a whole-face milling claim or (for `coverage` only) as-stock declaration
still covers the face. This does not prove motion
between samples or safe continuous rotation. Undrawn obstacles and unresolved
inputs retain unknowns. Only the authored bracket lacks STEP bytes.
Shaft, rocker and cone preserve their consumer-exported face sets and exact
adjacent STEP files; exported face identities do not establish operation
coverage. The rocker's S1 upper strap operations explicitly claim the exported
datum-B face in the plan. Its whole-outline operations S1:50, S2:50 and S3:40
explicitly claim `profile_outer` plus both separately exported radial-land
faces, preserving the authored whole-outline intent. The shipped vise records
measured jaw height/width/depth, opening and bed height (its item-level
`verify = true` no longer withholds those jaw dimensions from the kernel), and
the rocker plan centres its jaws on the blank, so rocker S1 draws exact jaws
and its `vise` row passes on nominal geometry; parallels stay undrawn and the
unknown `thin_wall_floor_mm` keeps `thin_wall_under_clamp` `?`. Contour tables use
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
