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

The shipped hand-authored reference bundles are under `examples/`, with shared
inventory, policy and cutting data. Read [examples/README.md](examples/README.md)
for current source file/line provenance and drawing coverage. Consumer source
citations point to the read-only harmonic-analyzer tree; they do not cause the
checker to read that tree or fetch a URL. Runtime must generate reports/sheets
from inputs, never load `expected/` as an answer. Reconcile expected fixtures
only from justified actual rule output and source evidence, never by weakening
stops or certifying unknowns. Keep fixture LF endings and canonical report hash.

Checks must perform **no network activity except explicitly configured OTel
export**. Inventory chart/source URLs are citations, not downloads. No CAD kernel,
fixture renderer, CAM, geometry-certification or M2 rule should be implied by an
M1 input/display field. No physical rehearsal or live farm evidence is recorded
merely because exporter tests pass.

## Local validation

From the repository root:

```sh
uv sync --locked
uv run pytest
uv run scripts/validate_examples.py
uv run ruff check .
uv run ruff format --check .
```

The validator validates authored fixture contracts and expected report integrity;
it does not certify machining. Its successful exit is 0, while actual example
checker/traveler exits are shaft 4, rocker 2, bracket 2. Use the CLI examples in
[README.md](README.md) and isolated output directories to exercise behavior.
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

Update README, the five input-format pages, affected rule-family pages and PLAN
M1 status lines when shipped behavior changes. Follow actual schema/rule
sentences, not PLAN sketches' obsolete placeholder dimensions. Physical printed
Letter clipping checks, operator dry-run and independent hand oracle remain
separate acceptance work. Do not claim them complete without observation.
