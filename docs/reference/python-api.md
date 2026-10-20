# Python interface reference

Prechips exposes importable implementation functions for loading inputs, evaluating rules and building outputs. It does not promise a stable Python SDK. The package root exports `__version__`; it does not re-export a `check`, `validate` or report API. Pin the package version and review these module-level interfaces when upgrading.

[Documentation](../README.md) | [CLI reference](cli.md) | [Architecture](../internals/architecture.md)

## Interface boundary

The installed application entry point is `prechips.cli:main`. The [CLI](cli.md) and documented file formats define the application contract. Functions below are useful implementation seams, not compatibility guarantees. Names beginning with `_`, kernel result dictionaries and renderer internals are not a supported extension API. There is no plugin-registration contract.

The signatures below retain the source annotations. Where a function has no annotation, its return value is described separately. Loading a valid bundle does not run all checks. Calling one rule or constructing a report does not reproduce the full CLI evaluation: the CLI also prepares shared kernel inputs, evaluates the complete registry, adds bundle binding, adds missing required coverage, handles approval and commits outputs.

## Load inputs

Source: [`prechips.inputs`](../../src/prechips/inputs.py). Field contracts: [plan](../plan.md), [feature manifest](../features.md), [inventory](../inventory.md), [policy](../policy.md), [cutting data](../cutting-data.md).

### `load_bundle`

```text
from prechips.inputs import load_bundle

load_bundle(
    plan_path: str | Path,
    inventory: str | Path | None = None,
    policy: str | Path | None = None,
    cutting_data: str | Path | None = None,
) -> Bundle
```

Read, validate, resolve and hash the complete operative bundle. `plan_path` is a plan file. Optional shop-file arguments override known plan declarations, then the inventory/policy environment fallbacks apply. A missing policy uses the built-in required-rule set. Inventory and cutting data must resolve to files. Path bases, containment and environment choices are the same as the [CLI loader contract](cli.md#bundle-paths-and-overrides).

Returns a `Bundle` with validated sparse dictionaries, resolved paths, exact source-byte SHA-256 digests and an operative feature mapping. Validation includes part identity, setup/operation identities, feature and frame references, plan-owned feature restrictions, referenced assets and known STEP digest binding. The loader preserves meaningful authored optional-field presence; it does not turn omitted facts into measured defaults.

Expected input failures raise `BadInput`, including unreadable/non-UTF-8 files, invalid TOML/schema data, inconsistent references, path escapes and digest mismatches. It does not translate exceptions into an exit code for library callers. It reads files and environment variables, caches resolved feature definitions on the returned bundle, and emits input spans only if a telemetry session already exists. It does not start FreeCAD, write reports or create a telemetry root.

### `load_inventory`

```text
from prechips.inputs import load_inventory

load_inventory(path: str | Path) -> dict
```

Read one inventory TOML file, validate it and return its sparse dictionary representation. A relative path uses the working directory. File, encoding, TOML and schema failures raise `BadInput`. The function reads the file but does not return its digest, resolve a plan or write output. As with bundle loading, an existing telemetry session may receive an input span.

### `Bundle`

```python
from prechips.inputs import Bundle
```

`Bundle` is a frozen dataclass. Prefer `load_bundle` to direct construction: the constructor itself does not perform the loader's cross-file checks.

| Attribute | Type | Meaning |
| --- | --- | --- |
| `plan`, `features`, `inventory`, `policy`, `cutting_data` | `dict` | Validated input documents. `features` remains the original exported/authored manifest, separate from plan-owned resolved definitions. |
| `paths` | `dict[str, Path]` | Resolved operative input paths. Policy uses the key `shop_policy`; referenced STEP/blank assets add entries. |
| `hashes` | `dict[str, str]` | Exact byte digests keyed to `paths`. A built-in policy fallback has no file record. |
| `root` | `Path` | Containment and report-label root. |
| `kernel` | `dict \| None`, default `None` | Non-operative memo populated by geometry execution. Excluded from dataclass comparison. |
| `input_records` | Property returning `dict[str, dict[str, str]]` | Fresh `{kind: {"path": label, "sha256": digest}}` records. Labels are root-relative POSIX paths or `external/{kind}/{filename}`. No file is reread. |
| `feature_definitions` | Cached property returning `dict[str, dict]` | Manifest definitions plus resolved plan joint/process features. This mapping is not a rewrite of the manifest file. |

Frozen attributes do not make nested dictionaries immutable. Do not change operative dictionaries after loading or reuse an already evaluated bundle after changing its inputs: cached definitions and geometry can then describe different state. Load a fresh bundle instead.

### `BadInput`

```python
from prechips.inputs import BadInput
```

`BadInput` subclasses `Exception`. It identifies handled invalid input/output conditions. The CLI logs it and returns 3. Lower-level callers must catch it themselves; unexpected implementation exceptions remain distinct.

## Findings and readiness

Source: [`prechips.findings`](../../src/prechips/findings.py). Required subjects and non-waivable rules are defined by the [policy reference](../policy.md).

### `Status` and `Finding`

```text
from prechips.findings import Finding, Status

Finding(
    rule: str,
    subject: str,
    status: Status | str,
    numbers: dict[str, Any],
    cite: list[str],
    sentence: str,
)

Finding.to_dict(self) -> dict[str, Any]
```

`Status` is a `StrEnum` with values `pass`, `error`, `warn`, `info`, `unknown`, `unsupported` and `not_applicable`. `Finding` is a frozen dataclass. Construction converts the status to `Status` and raises `ValueError` for an unsupported status. It does not perform general schema validation of the other fields or deep-freeze their contents.

`to_dict()` returns the report row with keys `rule`, `subject`, `status`, `numbers`, `cite` and `message`. The constructor's `sentence` becomes `message`. `numbers` and `cite` remain shared nested objects, not deep copies. Construction/serialization does not read files, write files or log the finding.

### `is_required` and `exit_code`

```text
from prechips.findings import exit_code, is_required

is_required(finding: Finding, policy: dict, bundle: Bundle | None = None) -> bool
exit_code(findings: list[Finding], policy: dict, bundle: Bundle | None = None) -> int
```

`is_required` applies the shop selector and the always-required rule set. Supply the bundle for setup, hole and toleranced-feature selectors; without it, some subject-specific decisions cannot use actual feature definitions. Inputs are expected to have passed normal loading.

`exit_code` returns:

- 2 if any finding is an error, whether required or optional.
- Otherwise 4 if any finding declares `kernel_unavailable`, required policy is unresolved, a required row is warning/unknown/unsupported, or a required rule is absent entirely.
- Otherwise 0.

It does not load inputs, execute rules, add missing subject rows, parse approvals or return 3. A `not_applicable` row does not block eligibility. The function cannot establish that the supplied findings form a complete evaluation; use the CLI for the application pipeline. Neither function writes files or logs results.

## Rule evaluation

Source: [`prechips.rules`](../../src/prechips/rules/__init__.py).

```text
from prechips.rules import RULES, Rule, required_coverage

Rule(name: str, evaluate: Callable[[Bundle], list[Finding]])
required_coverage(bundle: Bundle, findings: list[Finding]) -> list[Finding]
```

`RULES` is the ordered list the CLI evaluates. Each `Rule` pairs a name with its evaluator. The list includes both host and geometry consumers; it is not a plugin registry or a list of independently side-effect-free functions. Individual evaluators return findings for the loaded bundle. Geometry consumers may populate its kernel memo, start FreeCAD and use the cache through the geometry host. Do not run the entire registry when you intend a host-only utility.

`required_coverage` returns additional unknown findings for required rules or selected subjects that are absent from the existing rows. It does not evaluate the missing checks or mutate the supplied list. Call it after the intended rule evaluation. As with `exit_code`, a hand-built partial list is not evidence of a complete check. Unexpected errors from evaluators propagate to their caller.

## Geometry execution

Source: [`prechips.kernel`](../../src/prechips/kernel/__init__.py). These functions expose the implementation's native-job protocol; its dictionaries are version-specific. See [geometry rules](../rules-geometry.md) for measurement models and limits.

```text
from prechips.kernel import build_job, discover_kernel, run_geometries, run_geometry

discover_kernel()
build_job(bundle)
run_geometries(bundles, jobs=None)
run_geometry(bundle)
```

| Callable | Result | Side effects and failure behavior |
| --- | --- | --- |
| `discover_kernel()` | `Path`, executable-path string, or `None` | Inspect `FREECAD_CMD`, the per-user FreeCAD 1.1 installation and `PATH` in the [documented order](cli.md#output-safety-and-environment). No subprocess is started. An unavailable explicit override returns `None` without another installation fallback. |
| `build_job(bundle)` | Version-1 job `dict` | Resolve current authored inputs into the millimetre native request, including explicit unresolved values and measurement debts. Uses pre-kernel coordinates; does not execute FreeCAD or read/write its cache. Operative files were validated by the loader. Unexpected invalid-state errors propagate. |
| `run_geometries(bundles, jobs=None)` | List of result dictionaries in bundle order | Materialize the iterable, prepare pending bundles and batch uncached work in one FreeCAD invocation. When any bundle lacks a kernel memo, optional `jobs` must correspond one-for-one to all bundles; a length mismatch then raises `ValueError`. If every bundle already has a non-`None` memo, return those memos without examining `jobs`. Pending work can read environment/assets/cache, create temporary job files, write successful cache entries and populate each bundle's memo, including unavailable results. |
| `run_geometry(bundle)` | One kernel result `dict` | Call `run_geometries([bundle])[0]`; the same memo, file, subprocess and cache behavior applies. |

Missing FreeCAD is returned as `status: "unknown"` with `kernel_unavailable: true`. Missing/unverified geometry facts remain unresolved. Handled native execution/identification failures become `status: "error"` result dictionaries with a reason rather than a `BadInput` exception or a checker exit integer. Rule evaluation interprets those results. Other implementation errors can still propagate.

Only `status: "ok"` results are reused from disk. Cache keys bind the job recipe, native engine sources and executable identity. A result dictionary is not a `Finding`, report, safety certificate or proof of continuous motion clearance. Do not insert a fabricated successful result into `Bundle.kernel` to bypass native evaluation.

## Report and sheet construction

Source: [`prechips.report`](../../src/prechips/report.py) and [`prechips.sheet`](../../src/prechips/sheet.py). The [report reference](../report-and-telemetry.md) owns the saved format, render metadata, approval and output-safety contracts.

### Serialization and hashing

```text
from prechips.report import canonical_bytes, report_hash

canonical_bytes(data: Any) -> bytes
report_hash(report: dict) -> str
```

`canonical_bytes` serializes JSON-compatible data as UTF-8 with sorted keys, two-space indentation, non-ASCII text preserved and one final LF. Nonfinite numbers raise `ValueError`; unsupported JSON values or keys can raise `TypeError`, with ordinary JSON/UTF-8 serialization errors otherwise propagated. It writes no file.

`report_hash` returns the lowercase SHA-256 hex digest of canonical report content after removing only the root `hash` key. It does not mutate the dictionary, validate report structure, verify an existing hash or authenticate evidence. Serialization errors propagate. Nested fields named `hash` remain part of the digest.

### Assets and report assembly

```text
from prechips.report import build_report, render_assets

render_assets(bundle: Bundle) -> dict[str, bytes]
build_report(
    bundle: Bundle,
    findings: list[Finding],
    *,
    assets: dict[str, bytes] | None = None,
) -> dict
```

`render_assets` decodes the current kernel memo's returned setup and inspection PNGs into filename-to-bytes entries. It does not run geometry, create a missing image or write a file. Invalid base64/PNG data, missing inspection ownership or invalid panel metadata is refused, normally with `ValueError`; malformed implementation-state types can also raise ordinary Python exceptions.

`build_report` computes readiness from the supplied findings, sorts them by `(rule, subject)`, records input identities, binds returned image digests and adds the canonical report hash. `verification` is `"checked"` only for exit 0 and `"planned"` otherwise. If `assets` is omitted, it calls `render_assets`. Provided assets must match the current inspection images and their parent PNG; mismatches raise `ValueError`.

Both functions read the in-memory bundle/memo and allocate returned objects; they do not write output files or launch native work. `build_report` does not evaluate rules, add bundle binding or missing coverage, or read an approval record. Supplying incomplete or invented findings can produce a misleading report; it is the caller's responsibility to supply a complete actual evaluation.

### HTML rendering

```text
from prechips.sheet import render_traveler

render_traveler(
    bundle, findings, report, approval=None, *, detail: TravelerDetail = "hobby"
) -> str
```

Return fresh setup-sheet HTML from the actual bundle, findings and report. `approval` is the CLI's normalized approval dictionary, not a path to TOML. Approval can change release presentation but never supplies machining numbers or replaces findings. See [eligibility and approval](../report-and-telemetry.md#eligibility-and-approval) before calling the renderer directly.

`TravelerDetail` is defined in `prechips.model` as
`Literal["pro", "hobby", "pedantic"]`. The keyword-only `detail` selects
[printed content](../report-and-telemetry.md#traveler-detail-modes), defaulting to
`"hobby"`. An unsupported value raises `ValueError`. It does not evaluate rules
or change supplied findings, report identity or approval requirements.

The function returns a string without writing HTML, PNGs or PDF files and without starting a browser. Its module loads the packaged `tokens.css` resource on import. Invalid printable image geometry or incomplete panel coverage raises `ValueError`; other unexpected state errors propagate. Use the CLI when you need approval parsing, collision checks and transactional output replacement.

## Application entry points

```text
from prechips.cli import build_parser, main

build_parser() -> argparse.ArgumentParser
main(argv: list[str] | None = None) -> int
```

`build_parser` constructs the CLI parser. Its `parse_args` reports usage errors with `BadInput` after printing usage to stderr; help/version use `SystemExit(0)`. Parser construction alone does not configure telemetry or evaluate inputs.

`main` receives argument strings without the executable name. `None` uses `sys.argv[1:]`. It runs the actual five-verb application and returns the [documented status](cli.md#streams-and-errors), including 3 after logging `BadInput`. Help/version raise `SystemExit(0)` instead of returning. Unexpected exceptions propagate; an installed console invocation then normally exits 1 with a traceback.

Side effects depend on the verb: file loading, native execution/cache, stdout/stderr, approval reading and generated-output replacement/removal are possible. It configures the `prechips` logger and OpenTelemetry session, inherits OTLP environment settings, then flushes and closes the session on exit. It is not an in-memory checker wrapper or a concurrency-safe library service.

## Host-only example

From the repository root, create `out/docs-smoke/` if it does not exist and save the following code as `out/docs-smoke/show-inputs.py`. The script loads the shipped shaft bundle and prints its operative file identities as canonical JSON. Running it writes no files and does not discover or execute FreeCAD.

```python
from pathlib import Path

from prechips.inputs import load_bundle
from prechips.report import canonical_bytes

bundle = load_bundle(Path("examples/pivot-shaft/plan.toml"))
print(canonical_bytes(bundle.input_records).decode("utf-8"), end="")
```

Run it from the repository root:

```sh
uv run python out/docs-smoke/show-inputs.py
```

The output contains actual paths and digests from the files read on that run. It contains no kernel result or readiness verdict. Inventory/policy environment fallbacks still follow loader precedence. With missing or inconsistent inputs the example raises `BadInput`; do not replace those failures with invented records. Use the [quickstart](../manual/quickstart.md) for a complete check and the [CLI reference](cli.md) for output and exit handling.
