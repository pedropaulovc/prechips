# Working in prechips

## Environment and dependencies

Use **uv only** for Python environments, commands and dependency changes. Use
`uv sync --locked`, `uv run ...`, `uv add PACKAGE`, or `uv add --dev PACKAGE`;
commit `pyproject.toml` and `uv.lock` together for dependency changes. Do not use
pip, manually edit the lock, or add a parallel dependency-management convention.
Python is 3.12+. CLI entry point: `src/prechips/cli.py`; strict schema:
`src/prechips/model.py`; pure rules: `src/prechips/rules/`; report, sheet and
telemetry live beside them.

## Sources and fixtures

Never invent a tool measurement, tolerance, cutting number, source page, drawing
revision, STEP digest or first-article claim. Use the literal `"unknown"`; it is
not zero or a pass. `verify = true` means measurement/identity debt. Absence
from a known feature `requirements` list means known absence; an unknown list
or identity cannot establish absence. An unknown listed dimension still needs
an inspection method; unknown requirement identities remain unresolved rather
than inventing a gauge. Preserve source citations
next to the facts they support; author's process choices are not measured facts.
M5 physical dimensions (machine `envelope` limits, fixture bed height, holder
gauge/grip, tool OAL and tool/holder projection) require a fact-local
`{ value, measured = { by, date, instrument } }`; `verify = false` alone, a
block/root/source record, a date or a citation is not evidence, and a vendor
nominal is evidence in `numbers`, never a certificate. The mill's limits live
only in `machines.<id>.envelope`; projection is a per-holder map on the tool,
never a holder or tool scalar; the vise stack uses bed height, never jaw
height. Keep fixture vendor flags and existing OAL facts intact. M5 rules
consume only an already-present successful kernel bbox; they never start a
kernel. Missing approach/extent is plan-input debt and missing measurements
retain concrete `measure:` instructions keyed by the exact fact consumed; an
unresolved holder asks to be added or resolved, not measured.

The shipped reference bundles are under `examples/`, with authored plans and
shared inventory, policy and cutting data. `rocker-arm`, `pivot-shaft` and
`cone-pivot-post` consume verbatim consumer-generated `features.toml` and their
exact adjacent STEP files; never hand-edit those exports or add local provenance
keys. Record delivery provenance only in [examples/README.md](examples/README.md).
`pivot-bracket` remains hand-authored: no registered consumer drawing or STEP
is supplied. Python citations use `file:line` (or line ranges); YAML citations
use `file:dotted.key.path`, not unstable line numbers. Consumer citations point
to the read-only harmonic-analyzer tree; they do not cause the checker to read
that tree or fetch a URL. Runtime must generate reports/sheets from inputs,
never load `expected/` as an answer. Reconcile expected fixtures only from
justified actual rule output and source evidence, never by weakening stops,
rewriting exported facts or certifying unknowns. Keep fixture LF endings,
raw STEP bytes and canonical report hashes.

Checks must perform **no network activity except explicitly configured OTel
export**. Inventory chart/source URLs are citations, not downloads. The only
external process is the M4 FreeCAD kernel: one `freecadcmd.exe` job per
check/traveler run on the bundle's own STEP, resolved through `FREECAD_CMD`,
the installed FreeCAD 1.1, then `PATH`, with results cached under
`PRECHIPS_KERNEL_CACHE`. A missing kernel is `?` plus exit 4, never a pass; a
kernel failure is `✗`. No CAM, geometry certification or fixture solid is
implied by a declared input/display field: fixture solids exist only for a
vise, riser, chuck, dividing head, dead centre, angle plate, clamp or custom
fixture whose own dimensions (or authored `solids` primitives) are explicit
and not `verify = true`, plus a declared pose; a fixture is `modeled` only
when every drawn component is exact and no debt remains, and face identity comes only from a
geometry-matched STEP `ADVANCED_FACE` reference, never from import order or
the nearest face. M2 rules evaluate declared profile, holding, indexing and
physics inputs; unknown K_c/E, shop limits, `thin_wall_floor_mm` and verified
capacity remain debt. Unit tests that need kernel facts must inject a synthetic
`bundle.kernel` result. Real geometry integration tests must request the shared
`freecad_kernel` session fixture, use an isolated `PRECHIPS_KERNEL_CACHE`, and
skip with `FreeCAD kernel not found` if discovery finds no executable.
Absent-kernel tests must explicitly set `FREECAD_CMD` to a nonexistent path,
never rely on the host lacking FreeCAD. Preserve discovery order and the
product's unknown/exit-4 behavior.
No physical rehearsal or live farm evidence is recorded merely because exporter tests pass.

## Local validation

From the repository root:

```sh
uv sync --locked
uv run pytest
uv run scripts/validate_examples.py
uv run ruff check .
uv run ruff format --check .
```

Install FreeCAD 1.x and set `FREECAD_CMD` to its command executable if it is
not discovered on `PATH` or at the installed Windows FreeCAD 1.1 location
(for example `/opt/freecad/bin/freecadcmd` or
`C:\Program Files\FreeCAD 1.1\bin\freecadcmd.exe`). An explicit invalid override
is authoritative. `FREECAD_CMD=/nonexistent uv run pytest -q` exercises the
kernel-free suite with geometry skips. `PRECHIPS_REQUIRE_KERNEL=1` turns a
missing kernel into an error; CI sets it and installs the pinned, cached official
FreeCAD 1.1.0 Linux AppImage so geometry tests cannot silently skip.

The validator validates bundle contracts and expected report integrity; it does
not certify machining. Its successful exit is 0 even when checker/traveler
outputs correctly stop with 2 or 4. Current expected M3 CLI exits are
4 / 2 / 2 / 2 / 2 (shaft / rocker / bracket / cone one-piece / cone built-up).
The one-piece cone stops on the exported `mount_west` nominal lying outside its
band; never flip or drop exported facts to recover an exit. Migrate existing
inspection choices to the exact exported feature owners rather than dropping
checks, inventing methods or changing gauges to force an exit. A check whose
requirement the export lacks stays visible as an explicit `missing_requirements`
unknown. Only the consumer side of M3 is done. Consult PLAN §8 M3 for the open
HA items and the combined gate.
Use the CLI examples in [README.md](README.md) and isolated output directories
to exercise behavior.
The cone's one-piece and built-up candidates also remain PLANNED; comparison
must refuse built-up construction unless the drawing manifest explicitly permits
it. Indexing uses one angular setting for the inclined journal, never a fictional
shaft cross-hole. Closure is checked only for a full pattern: `positions >= 2`
with `angle_deg` omitted (step exactly `360 / positions`). Authored angles are
open patterns: every landing is checked, with no closure. One setting also has
no closure.
Keep regression tests about consumer-visible boundaries, not exact incidental
prose or copied wiring. Tests must use temporary files and local telemetry
collectors, not real shop state or production services. During parallel work,
coordinate project-wide validation with the parent; do not run suites against
siblings' half-finished code. Document the exact commands actually observed,
not an inferred pass.

## Local telemetry check (manual procedure, not recorded live evidence)

Start a collector/dashboard separately. If using the consumer's Aspire dashboard,
open `http://127.0.0.1:18890`; that is a UI address, **not** an OTLP endpoint.
Use the collector's actual trace/log OTLP addresses. Configure, for example, in
PowerShell:

```powershell
$env:OTEL_SERVICE_NAMESPACE = 'harmonic-analyzer'
$env:OTEL_EXPORTER_OTLP_PROTOCOL = 'grpc'
$env:OTEL_EXPORTER_OTLP_TRACES_ENDPOINT = '<actual collector traces endpoint>'
$env:OTEL_EXPORTER_OTLP_LOGS_ENDPOINT = '<actual collector logs endpoint>'
# Inherit the real launcher task's W3C context; do not fabricate it as evidence.
$env:TRACEPARENT = '<parent task traceparent>'
uv run prechips check examples/rocker-arm/plan.toml --out out/telemetry-local
```

Optional `TRACESTATE` also propagates. HTTP/protobuf is supported via standard
OTLP variables; signal-specific endpoint/protocol/timeout settings override
common settings. Timeouts are milliseconds. No endpoint means no exporter or
missing-collector warning. Verify the `prechips.check` root is parented to the
launcher task, child input/rule/finding/output spans appear, findings carry
rule/subject/status/numbers/cite, and log records share the trace/span context.
Confirm flush on ordinary and exit-3 paths. Local collector tests can check
export/correlation, but cannot establish farm acceptance.

## Farm telemetry acceptance (pending live observation)

Do not provision, disrupt or silently run farm machinery from this documentation
procedure. Coordinate with the consumer/farm owner. Launch an actual
`prechips check` as the harmonic-analyzer doit subprocess on an authorized farm
worker, inheriting the task's **real** `TRACEPARENT` (and `TRACESTATE` if present),
`OTEL_SERVICE_NAMESPACE`, existing worker OTLP/gRPC trace/log endpoints and
headers. The consumer's Azure Monitor Agent path, not a separately invented
endpoint, must carry the records.

In the shared App Insights instance, query the build's `operation_Id`. Verify
`prechips.check` continues that trace and has the build task as its parent;
inspect correlated finding logs and input/rule/output spans. Record worker,
invocation, exit, trace/task identifiers and queried evidence. No local test,
synthetic traceparent, expected fixture or dashboard screenshot substitutes for
this parented live farm path. This acceptance is unobserved/pending here.

## Documentation and scope

Update README, the five input-format pages, affected rule-family pages
(including [docs/rules-geometry.md](docs/rules-geometry.md)) and PLAN
milestone status lines when shipped behavior changes. Follow actual schema/rule
sentences, not PLAN sketches' obsolete placeholder dimensions. Physical printed
Letter clipping checks, operator dry-run and independent hand oracle remain
separate acceptance work. Do not claim them complete without observation.
