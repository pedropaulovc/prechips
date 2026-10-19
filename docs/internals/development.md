# Develop and verify prechips

Use the locked `uv` environment to change prechips, run the relevant contracts and build the distribution. Native geometry, browser printing, blind review and physical shop acceptance are separate checks with different prerequisites.

[Documentation](../README.md) | [Architecture](architecture.md) | [Style guide](../style-guide.md) | [Contributor rules](../../AGENTS.md) | [Delivery status](../../PLAN.md#8-milestones)

## Set up the environment

Work from the repository root with Python 3.12 or newer and [uv](https://docs.astral.sh/uv/):

```sh
uv sync --locked
```

[`pyproject.toml`](../../pyproject.toml) defines a `src/` package built by `uv_build`. Runtime dependencies are Pydantic, Rich and the OpenTelemetry API/SDK plus HTTP/gRPC exporters. The development group supplies pytest, its selection/parallelism plugins, Ruff, Pillow and pypdfium2. Use `uv` for project environments and commands; do not add a separate pip-managed environment.

Install [FreeCAD 1.x](https://github.com/FreeCAD/FreeCAD/releases) for native geometry contracts. FreeCAD runs in a separate process with its own bundled Python environment, not inside the project interpreter. Set `FREECAD_CMD` when needed. These are explicit override examples, not automatic install locations:

```sh
# POSIX shell, if this is your installed executable:
export FREECAD_CMD=/opt/freecad/bin/freecadcmd
```

```powershell
# PowerShell, if this is your installed executable:
$env:FREECAD_CMD = 'C:\Program Files\FreeCAD 1.1\bin\freecadcmd.exe'
```

Without an override, automatic Windows discovery checks `%LOCALAPPDATA%/Programs/FreeCAD 1.1/bin/freecadcmd.exe` before `PATH`. A nonempty invalid override is authoritative and does not fall through to another installation. The [CLI environment reference](../reference/cli.md#output-safety-and-environment) owns the complete order and cache defaults.

Set `PRECHIPS_KERNEL_CACHE` to a persistent directory for repeated local runs. For example, in PowerShell:

```powershell
$env:PRECHIPS_KERNEL_CACHE = Join-Path $HOME '.cache/prechips/kernel'
```

The test session otherwise supplies a private temporary cache, so separate sessions start cold. Content-keyed atomic cache writes let worktrees and pytest workers share a persistent directory; cold/invalidation tests deliberately use private caches. A native engine-source edit changes the engine digest and makes the affected geometry cold regardless of test selection. A shared geometry cache is not permission to run concurrent product commands into the same output directory.

Install a launchable Chrome or Edge for print contracts. Browser discovery uses `PRECHIPS_CHROME`, standard Windows Chrome/Edge installs, then `PATH`; an invalid explicit override is an error. PDF raster checks also use the development dependencies installed above. See [print and review](#check-the-printed-output).

## Select tests for a change

After the implementation is ready, use the committed affected-test map for a local selection:

```sh
uv run scripts/affected_tests.py --base main --dry-run
uv run scripts/affected_tests.py --base main
uv run ruff check .
uv run ruff format --check .
```

`--dry-run` prints the selected modules and reasons without running pytest. `--base main` compares with that ref's merge base and includes staged, unstaged and untracked changes. Confirm that `main` is the intended base before interpreting the selection. Extra pytest arguments go after `--`:

```sh
uv run scripts/affected_tests.py --base main -- -x -k sheet
```

The selector uses [`tests/affected_tests.toml`](../../tests/affected_tests.toml) and [`scripts/affected_tests.py`](../../scripts/affected_tests.py):

- Changed test modules bring in their importing test modules transitively.
- `[sources]` maps changed package sources to test modules measured as executing them, including Python subprocess coverage.
- `[consumers]` covers subprocess seams that coverage cannot attribute normally. Native engine sources select every `freecad_kernel` consumer; `cli.py` selects every `run_cli` consumer.
- `[paths]` covers non-Python inputs such as examples, goldens, fixture data and scripts.
- Golden-example keepers and test modules not yet named by the map run for non-ignored changes.
- A full trigger, such as conftest, project metadata, the lock or package version, selects the full suite. So does an uncovered changed file; a new source must not silently select nothing.

Selected tests run with `-n 2 --dist loadscope`, with `PRECHIPS_KERNEL_WORKERS=1` unless that environment variable is already set. A docs-only ignored change may select nothing. Neither that outcome nor a passing local selection is a full-suite pass.

When a new source is added, name its exercising tests in `[sources]` or regenerate the map. Add a `[paths]` entry when tests start reading a new non-Python input. Map completeness is protected by `tests/test_affected_tests.py`.

```sh
uv run scripts/affected_tests.py --rebuild-map
```

This is a full testmon measurement run, including supported Python subprocess coverage. It replaces `[sources]` only after a green run. `--testmondata PATH` with `--rebuild-map` can reuse an existing testmon database. Do not rebuild the map merely to hide an uncovered source or a failing test.

## Understand native and browser coverage

[`tests/conftest.py`](../../tests/conftest.py) controls optional versus required dependencies:

| Setting | Test behavior |
| --- | --- |
| No discovered FreeCAD, default settings | Tests using `freecad_kernel` skip with `FreeCAD kernel not found`. Host and explicit absent-kernel contracts still run. |
| `PRECHIPS_REQUIRE_KERNEL=1` | Missing FreeCAD is a pytest session error, not a successful geometry skip. |
| No discovered print browser, default settings | Optional browser-print tests can skip. |
| `PRECHIPS_REQUIRE_PRINT_BROWSER=1` | A missing or unlaunchable print browser fails the session. |

For an intentionally kernel-free check, the existing override contract supports this POSIX-shell command:

```sh
FREECAD_CMD=/nonexistent uv run pytest -q
```

This exercises absent-kernel handling with native skips. It does not prove native behavior and fails at session start if you also require a kernel. The product itself reports unresolved geometry without FreeCAD; a test skip does not change that product behavior.

Native fixtures are not mock clearance results:

- [`tests/test_kernel_geometry.py`](../../tests/test_kernel_geometry.py) authors solids in FreeCAD, exports STEP and checks the engine's JSON measurements. It also uses byte-preserved consumer exports with provenance recorded in that module.
- [`tests/test_fixture_solids.py`](../../tests/test_fixture_solids.py) covers chuck, centre, dividing-head, custom fixture and clamp solids, alongside host-side input propagation.
- [`tests/data/kernel/`](../../tests/data/kernel/) contains bound STEP/BREP/JSON and manifest fixtures. [`tests/data/render/`](../../tests/data/render/) and [`tests/data/print/`](../../tests/data/print/) support raster and print regressions.
- [`examples/geometry/README.md`](../../examples/geometry/README.md) explains the separate synthetic geometry control bundles. They are not interchangeable with the current consumer examples.

Preserve original asset bytes, digests, face identities and provenance when changing a test. A fixture that exercises a measured branch is not evidence that a physical measurement occurred. The [example policy](../../examples/README.md#examples-policy-plausible-labelled-values) owns those disclosures.

## Validate examples and package outputs

Run the prescribed full validation/package gate when the change requires it:

```sh
uv sync --locked
uv run pytest
uv run scripts/validate_examples.py
uv run ruff check .
uv run ruff format --check .
```

The example validator must also run locally when examples, goldens or printed setup-sheet content change. Its exit 0 means the authored fixture contracts were satisfied; the checker commands it runs can correctly return 2 or 4. It checks actual bundle/report/native/render/sheet behavior and does not certify machining. Current expected candidate exits belong to [expected consumer CLI exits](../../examples/README.md#expected-consumer-cli-exits), not to a contributor's recollection of an older run.

[`tests/test_examples.py`](../../tests/test_examples.py) regenerates the pilot outputs twice, compares those runs byte-for-byte and compares them with the stored report/HTML/PNG artifacts. Other geometry controls are also byte-compared. Runtime code must never load `expected/` as its answer. Preserve source bytes, artifacts, manifests, provenance and contractual outputs. Do not replace goldens simply because a check failed; establish the intended behavior change and its review basis first. Ruff formatting of native engine code can change the source digest, cache identity and frozen evidence, so run it before freezing affected outputs.

To inspect a current sheet without overwriting an example directory, use an explicit scratch destination:

```sh
uv run prechips traveler examples/pivot-shaft/plan.toml --out out/development/pivot-shaft
```

Inspect the report's actual exit/verification, generated HTML and every returned PNG. Expected nonzero evaluation exits still produce usable outputs. Do not change authored measurements, policy or checks to manufacture exit 0. Remove incidental working reports rather than committing scratch output. Follow [output safety](../report-and-telemetry.md#output-safety) when retaining or regenerating sheets.

Then run `uv build` to produce a wheel and source distribution under `dist/`. Repository imports alone do not show that these artifacts contain the required package resources or entry points. The CI build job exercises each artifact outside the checkout with `tests/test_cli.py::test_installed_artifact_console_script_matches_module`. For a local artifact check, set `PRECHIPS_INSTALLED_ARTIFACT` to the absolute path of the built artifact, then run:

```sh
uv run pytest tests/test_cli.py::test_installed_artifact_console_script_matches_module
```

Repeat for both wheel and sdist. Without that environment variable the test skips, which is not package validation. The test uses an isolated `uv` consumer, confirms the imports/console script come from the installed artifact, compares `prechips` with `python -m prechips.cli`, and exercises actual traveler/report output with an intentionally unavailable kernel. See the [CI workflow](../../.github/workflows/ci.yml) and [test implementation](../../tests/test_cli.py).

## Check the printed output

HTML structure and screenshots do not establish what a browser put in the PDF. [`tests/test_sheet_print.py`](../../tests/test_sheet_print.py) prints through a real browser and inspects PDF text/pixels, page labels, blank backs, setup front starts and related layout contracts. Test the public print behavior, including image presence, rather than relying only on DOM state or print-media emulation.

After changing layout, wording, pictures or tables, review every affected example's rendered pages with the blind machinist-review tool. For render-only changes, compare the base and proposed documents under the same rubric. The [generated-sheet reference](../report-and-telemetry.md#generated-traveler) owns typography, pagination, semantic picture bands and operator content.

### Blind machinist review

[`scripts/machinist_review.py`](../../scripts/machinist_review.py) is a developer tool that calls a hosted model through `codex exec` or `claude -p`. It is separate from offline `prechips check`. It copies page images into a neutral temporary directory under the [calibrated prompt](../../scripts/prompts/machinist_review_traveler.md), without repository context. Missing and unneeded content both count as defects: the operator should have no unanswered questions and no material they do not need to run the job.

Choose a different model family from the author or last editor of the plan or sheet code. Claude-authored work uses `--reviewer codex`; Codex/GPT-authored work uses `--reviewer claude`. A same-family `CLEAR` is not the gate. The reviewer CLI must be available and authenticated. Defaults are `gpt-6-astra` at low effort for Codex and `claude-fable-5-1` at medium effort for Claude; `--model` and `--effort` override them.

Use the input form you have. These are alternatives. The `--traveler` example uses the output from [Run the examples](../../README.md#run-the-examples); PDF/PNG filenames refer to already prepared input pages. Reports default to `out/machinist-review/`; `--report-dir DIR` selects another destination.

```sh
uv run scripts/machinist_review.py --reviewer codex --traveler out/pivot-shaft
uv run scripts/machinist_review.py --reviewer claude --bundle examples/rocker-arm/plan.toml
uv run scripts/machinist_review.py --reviewer codex --pdf printed-traveler.pdf
uv run scripts/machinist_review.py --reviewer codex --png page-1.png --png page-2.png
```

`--traveler` accepts a folder or HTML file. It prints to Letter PDF with headless Chrome/Edge, allows the duplex-padding script to run and rasterizes every page at 300 dpi with pypdfium2. Generated traveler/bundle reviews reject odd page counts. `--bundle` first runs the real traveler command in a staging directory, inheriting `FREECAD_CMD` and `PRECHIPS_KERNEL_CACHE`, then prints that result. Input options repeat; `--jobs` controls parallel package reviews, while printing is prepared serially.

The script records `review.json`, `review.md`, reviewer events, per-attempt artifacts with resume commands and page PNGs under the report directory's package subdirectories. Traveler/bundle reviews also retain the printed PDF and generated output as applicable. `index.md` summarizes packages. Provenance records page SHA-256 values, source PDF hashes where present, and HTML/report/PDF identities for generated sheets. The event stream enforces blindness: unauthorized tool/path access fails the review; Claude must read every supplied page.

A nonzero reviewer exit remains a failed review, not a machining verdict. Its report includes a bounded diagnostic from stderr, or an explicit structured provider error when stderr is empty; unrelated page/tool payloads are not used as diagnostics. The retained stdout, stderr and events remain available for investigation.

A review exits 0 only when every package remains blind, the verdict is `CLEAR` and there are no blocker, clutter or clarity findings. Minor findings are recorded but do not gate. The reviewer judges speeds, feeds, depths of cut, stickouts and tool choices against the material, tool and machine, including values labeled as examples. Tool-breaking, machine-exceeding or part-scrapping values are blockers. Substantially inaccurate but survivable values, or an important value without an established reference range, are clarity findings. The summary must identify the comparison basis.

### Handbook references

Use `--handbook DIR` or `PRECHIPS_HANDBOOK_DIR` to name the `machinerys-handbook` folder containing `corpus/README.md` and the page-level `corpus/`. The handbook is not vendored. [`scripts/prompts/handbook_refs.toml`](../../scripts/prompts/handbook_refs.toml) records only page/source identities for Machinery's Handbook, 27th edition: 1018 turning, end milling, drilling and reaming with adjustment factors; reamer stock allowance; centre drills; band-saw speeds; automatic-screw-machine cutoff/form tools; and inch/metric tap drills.

The manifest's `corpus/pages/NNNN.md` files are embedded as text in both reviewers' prompts. Findings cite the table and printed page. Claude may also read the permitted corpus and linked handbook PDF; Codex receives the embedded pages only, since shell lookups would break the blind contract. Reference pages are not traveler pages to be reviewed for clutter.

An explicitly named missing corpus, absent manifest page, mismatching PDF/printed-page header or source-PDF identity mismatch is an input error (exit 2), not permission to fall back to memory. With no handbook named, the tool warns, reviews from memory and records `handbook: null`. That limitation must remain visible. Review provenance records hashes of the corpus README, manifest and embedded pages, and the extra handbook files/pages Claude actually reads.

## Understand CI and release gates

CI runs the full suite, not the local affected selection. The current [workflow](../../.github/workflows/ci.yml) uses six duration-balanced shards from committed `.test_durations`, with two pytest workers and load-scope scheduling per shard, and caps each engine's extra native workers at one. It requires both a kernel and a launchable print browser.

The official FreeCAD 1.1.0 Linux AppImage is version/SHA-256 pinned, cached and extracted without FUSE. Its bundled Python settings stay in the kernel process. Geometry-cache namespaces include runner OS/architecture, the AppImage digest, cache epoch and engine-source digest. Immutable save keys also include shard/run/attempt identity. Each shard restores its own latest compatible entry, then the shared prefix; only successful shards publish their geometry cache.

Shard logs and JUnit results are retained even on failure. The required `test` check demands successful shards and uses `scripts/ci_shards.py check` to compare their JUnit cases with the full collection exactly once. Rebuild `.test_durations` from measured green-run JUnit evidence with `scripts/ci_shards.py durations`, not guessed times. A count match alone does not establish the correctness of a new test oracle or complete coverage of a changed safety boundary.

The build job separately builds and exercises wheel/sdist consumers. Release is defined in [release.yml](../../.github/workflows/release.yml): a `v*` tag must match `uv version --short`; the workflow builds and publishes to PyPI through OIDC in the `pypi` environment. Update package metadata and obtain the required reviews/validation before releasing. Do not merge a PR or enable auto-merge without Pedro's explicit confirmation.

## Check local telemetry

Use a separately running local collector to check trace/log export and correlation. This procedure does not install or deploy a collector, and it is guidance rather than a recorded live result. If you use the consumer's Aspire dashboard, `http://127.0.0.1:18890` is its UI address, not an OTLP endpoint.

1. Obtain the collector's actual trace and log OTLP addresses, supported protocols and any required authentication/TLS configuration. Use the collector configuration, not its dashboard URL, to get these values.
2. Open a fresh PowerShell session in the repository root. Keep the following environment changes in that session and close it when finished. If a real launcher task supplies `TRACEPARENT` and optional `TRACESTATE`, inherit them unchanged. Do not invent a parent value or trace id as evidence. A standalone run without inherited task context can check local export, but cannot demonstrate launcher parentage.
3. Enter the actual configuration when prompted. Each protocol must be `grpc` or `http/protobuf`. Do not continue with empty values or unresolved example placeholders.

   ```powershell
   $env:OTEL_SERVICE_NAMESPACE = Read-Host 'Service namespace for this local run'
   $env:OTEL_EXPORTER_OTLP_TRACES_ENDPOINT = Read-Host 'Actual collector traces OTLP endpoint'
   $env:OTEL_EXPORTER_OTLP_LOGS_ENDPOINT = Read-Host 'Actual collector logs OTLP endpoint'
   $env:OTEL_EXPORTER_OTLP_TRACES_PROTOCOL = Read-Host 'Traces protocol: grpc or http/protobuf'
   $env:OTEL_EXPORTER_OTLP_LOGS_PROTOCOL = Read-Host 'Logs protocol: grpc or http/protobuf'
   ```

   The exporter also uses standard OTLP header/TLS variables. Use actual collector credentials only when required, and do not copy them into shared command transcripts. Signal-specific endpoint/protocol/timeout settings override common settings; timeout values are milliseconds. Confirm that inherited header/TLS/timeout settings match this collector. The [telemetry variable contract](../report-and-telemetry.md#telemetry-and-console) defines the complete precedence and supported transports. Without an endpoint, that signal has no exporter or missing-collector warning.

4. Run a real check into a scratch directory and record its actual exit:

   ```powershell
   uv run prechips check examples/rocker-arm/plan.toml --out out/development/telemetry-local
   $checkExit = $LASTEXITCODE
   $checkExit
   ```

   A completed evaluation can return 0, 2 or 4 and still write a report. Do not alter inputs to force a preferred exit. Inspect the report and the collector, rather than treating the command's exit as proof of export.

5. In the collector/dashboard, find this invocation's `prechips.check` root span. If the launcher supplied real context, verify that it continues that trace and names the actual task span as its parent. Without inherited context, expect an unparented application root and make no launcher-correlation claim. Inspect child `input.load`, `rule.<name>.evaluate`, per-finding `rule.<name>` and `output.write` spans. Finding spans/log records should carry `rule`, `subject`, `status`, `numbers` and `cite`; the corresponding finding logs must share their trace/span context. After the process returns, confirm that the root has ended and its trace and log records reached the collector.
6. Check the handled error path by deliberately omitting the required plan argument:

   ```powershell
   uv run prechips check --out out/development/telemetry-local-bad-input
   $badInputExit = $LASTEXITCODE
   $badInputExit
   ```

   Expect exit 3, usage and a `Bad input` diagnostic. This parser-error run does not load a bundle or write report artifacts, so it should not have input/rule/output work spans. Confirm instead that its `prechips.check` root ends and its correlated error log arrives after the process returns. The CLI flushes trace and log providers in its exit cleanup on both completed evaluations and handled bad input; collector delivery must still be observed.
7. Close the dedicated PowerShell session so its local endpoint/protocol settings cannot leak into later work. Record the actual command exits, observed span/log identities and collector evidence without credentials.

Local export/correlation checks do not establish the [pending live farm acceptance](#report-acceptance-honestly). That requires the authorized consumer subprocess, real inherited farm task context and the existing Azure Monitor Agent/App Insights path.

## Report acceptance honestly

Tests, byte-identical goldens, browser PDFs and a blind `CLEAR` cover software/document contracts. They do not establish physical printer clipping, pen usability, an operator rehearsal, independent hand calculations, first-article machining or real fixture/tool measurements. Those acceptance activities remain separate and must not be marked complete without observations. The current example setup sheets remain planned without matching physical first-article evidence, even when their report is checked.

Live farm telemetry acceptance also remains pending/unobserved here. Coordinate an authorized harmonic-analyzer subprocess run with the farm owner; do not provision or disrupt workers from a documentation procedure. The run must inherit the real task `TRACEPARENT`/`TRACESTATE`, namespace and existing worker OTLP configuration through the consumer's Azure Monitor Agent path. App Insights evidence must show `prechips.check` under the real task in the same `operation_Id`, with correlated findings and input/rule/output spans. Record the worker, invocation, exit and trace/task evidence. A local exporter test, synthetic parent or dashboard screenshot does not substitute for that path.

Keep current acceptance evidence in [PLAN](../../PLAN.md#8-milestones), example provenance and limits in [examples/README.md](../../examples/README.md), and the observability contract in [report and telemetry](../report-and-telemetry.md#telemetry-and-console). When shipped behavior changes, update the affected manual/reference pages, root navigation and PLAN status. Record only commands/results actually observed as validation evidence; distinguish a prescribed procedure from an executed pass.
