# Troubleshoot a check or setup sheet

Start with the error on stderr and the findings in the current `report.json`. A nonzero exit can still produce a report and a setup sheet. Do not use a sheet left from an earlier run as evidence that the current command succeeded. See the [CLI reference](../reference/cli.md) for command syntax and the [report reference](../report-and-telemetry.md) for output and approval rules.

The commands below run from the repository root in a locked source checkout. File-producing commands use separate scratch directories under the ignored `out/docs-smoke/` tree. Example inputs contain demonstration values, not measurements of your shop. See [example provenance](../../examples/README.md).

## The command reports `Bad input` or exits 3

The loader could not read or validate an input, or the command refused an unsafe output destination. Input errors include malformed TOML, unsupported fields, missing files, inconsistent part names and references to features or frames that do not exist. These are different from rule findings about a valid plan.

1. Read the complete error, including the input kind and field path. Correct that file using the [plan](../plan.md), [feature manifest](../features.md), [inventory](../inventory.md), [policy](../policy.md) or [cutting-data](../cutting-data.md) reference.
2. Check [how the selected path resolves](../reference/cli.md#bundle-paths-and-overrides). Plan-declared paths resolve from the plan's directory. Explicit inventory, policy and cutting-data options resolve from the current working directory. Inventory and policy environment variables are fallbacks after explicit options and plan declarations.
3. Rerun with a separate output directory:

   ```console
   uv run prechips check examples/pivot-shaft/plan.toml --out out/docs-smoke/support-check
   ```

Verify that the input error is gone and that the new report describes the intended inputs. Exit 2 or 4 means you have reached rule evaluation but still have findings to resolve. An old report in the output directory does not prove recovery from exit 3.

## A path escapes the bundle, or the STEP digest does not match

Feature manifests, plan-declared shop files and referenced STEP assets must stay inside the resolved bundle root. The loader uses the enclosing project root, or the directory above `examples`, when present; otherwise it uses the plan directory. Resolved paths, including symbolic links, must satisfy confinement. A known manifest STEP digest must match the file bytes.

Keep the manifest and geometry assets within that root and correct their relative paths. For a deliberately external shop inventory, policy or cutting-data file, use the corresponding explicit CLI option. That does not exempt STEP assets or the feature manifest from confinement. If the STEP changed, obtain the matching manifest and face identities from the intended export; do not replace a digest just to silence the error.

Rerun and inspect the report's input records and `bundle_binding:inputs` finding. A matching digest establishes which bytes were checked. It does not establish that the export or authored geometry is correct. See [feature identity](../features.md) and [report binding](../report-and-telemetry.md#canonical-bytes-and-input-binding).

## FreeCAD is installed, but geometry says the kernel is unavailable

A nonempty `FREECAD_CMD` is authoritative. An invalid override prevents fallback to another installed executable. Without it, discovery checks `%LOCALAPPDATA%/Programs/FreeCAD 1.1/bin/freecadcmd.exe`, then the names `freecadcmd.exe`, `FreeCADCmd` and `freecadcmd` on `PATH`. It does not automatically search Program Files.

Point `FREECAD_CMD` at the actual command executable, or remove an obsolete override and make the executable discoverable. For example, this PowerShell assignment selects the supported per-user installation location if it exists:

```powershell
$hadFreecadOverride = Test-Path Env:FREECAD_CMD
$previousFreecad = $env:FREECAD_CMD
try {
    $env:FREECAD_CMD = "$env:LOCALAPPDATA/Programs/FreeCAD 1.1/bin/freecadcmd.exe"
    uv run prechips check examples/pivot-shaft/plan.toml --out out/docs-smoke/support-freecad
    $freecadCheckExit = $LASTEXITCODE
}
finally {
    if ($hadFreecadOverride) {
        $env:FREECAD_CMD = $previousFreecad
    }
    else {
        Remove-Item Env:FREECAD_CMD -ErrorAction SilentlyContinue
    }
}
```

Use your actual installation path if it differs. The block restores the previous override, or removes it if it was initially unset. Inspect `$freecadCheckExit` and verify that the new findings no longer report `kernel_unavailable`. Missing FreeCAD forces exit 4 unless an error finding takes precedence with exit 2. A working executable can still leave geometry unresolved because an input fact is missing.

## Geometry remains unknown, or a repeat run is much faster

Geometry needs available STEP bytes, a known matching manifest SHA-256 and the facts consumed by the particular check. Installing FreeCAD does not supply missing tool dimensions, fixture placement or measured machine limits. A native execution failure can also leave a reason describing the launcher, output or last geometry phase.

Read the affected finding's message and numbers. Resolve its stated input debt using the relevant [geometry rule](../rules-geometry.md) and [inventory](../inventory.md) reference. Keep native failure details when reporting a problem; repeated runs without an input or environment change do not establish recovery.

A fast repeat run can be a cache hit. The geometry cache keys the geometry job, engine sources and executable identity; only successful native results are reused. Missing-kernel discovery is handled before cache lookup, so a cache cannot substitute for an unavailable executable. Cache read or write failures do not change machining findings.

If you need a fresh native run for diagnosis, select a new, empty cache directory instead of deleting shared cached results. In PowerShell:

```powershell
$hadCacheOverride = Test-Path Env:PRECHIPS_KERNEL_CACHE
$previousCache = $env:PRECHIPS_KERNEL_CACHE
$diagnosticCache = Join-Path 'out/docs-smoke' ('support-kernel-cache-' + [guid]::NewGuid().ToString('N'))
try {
    $env:PRECHIPS_KERNEL_CACHE = $diagnosticCache
    uv run prechips check examples/pivot-shaft/plan.toml --out out/docs-smoke/support-fresh-geometry
    $freshGeometryExit = $LASTEXITCODE
}
finally {
    if ($hadCacheOverride) {
        $env:PRECHIPS_KERNEL_CACHE = $previousCache
    }
    else {
        Remove-Item Env:PRECHIPS_KERNEL_CACHE -ErrorAction SilentlyContinue
    }
}
```

The block selects a new cache path on every invocation and restores the previous environment setting afterward. It leaves `$diagnosticCache` available for inspection. Inspect `$freshGeometryExit` and verify recovery from the new findings, not elapsed time alone. Cache location and geometry evidence are described in [execution and cache provenance](../report-and-telemetry.md#execution-and-cache-provenance).

## A listed tool still needs verification or a measured fact

A catalog match does not establish a physical measurement. Tool identity, nominal dimensions and installed dimensions have different requirements. A measured fact must carry its own complete measurement record: `status = "measured"`, who measured it, an ISO date and the instrument. An `assumed` or `illustrative` record, an incomplete record, or a fact marked for verification remains debt. A measurement on a parent item does not qualify all of its dimensions.

Use `tools --measure` with `--plan` set to your plan to list the current plan's consumed measurement debt. This command prints a checklist to stdout and does not run FreeCAD or write report files. The [measurement checklist reference](../reference/cli.md#measurement-checklist) gives its syntax. An ordinary `tools` search likewise lists candidates; its successful exit does not establish plan eligibility.

Measure the named facts on the actual tool, holder, fixture or machine and record the real provenance according to the [inventory reference](../inventory.md). Installed tool projection may be specific to the tool and holder pair. Do not copy example measurements, remove verification flags without evidence, or mark nominal data as measured.

Regenerate the report in a scratch output directory. Verify that the exact debt has cleared and check for remaining findings. An empty measurement checklist does not prove that every rule passed, every tool is available or the plan is approved.

## The report is `checked`, but the sheet is still `PLANNED`

A report becomes `checked` when its readiness result is exit 0. Approval is separate. Without an approval record, the sheet remains planned even when the report is checked.

For approval, supply a TOML record through `--approval` that names this report's hash and actual first-article evidence. The record must match the current report, contain nonblank evidence other than `unknown`, and refer to a checked report. See the [approval contract](../report-and-telemetry.md#eligibility-and-approval) for the record format and workflow. Do not invent evidence for an example run.

Regenerate the sheet with the record and a scratch output directory. Inspect approval warnings and the sheet status. Changes to operative input bytes, rule/version binding or bound render bytes can stale the approval. A stale record calls for the appropriate repeated first article, not an edited hash to retain the old approval.

## Approval does not clear warnings or exit 4

Readiness fails when required checks remain unresolved. Required warnings, unknowns and unsupported results can produce exit 4; some rules are always required. Any error finding produces exit 2. Policy can select required checks, but approval cannot waive them.

Resolve the finding at its source. Check the [shop policy](../policy.md) and the rule linked from the report before deciding whether the plan supplies the required evidence. Do not weaken policy to make an example appear ready.

Rerun and verify the report's `expected_exit`, `verification` and individual findings. Exit 0 can coexist with nonrequired unresolved findings, so inspect the report rather than treating the exit alone as a complete assessment. Neither readiness nor approval certifies physical machining safety.

## The output destination is refused, or a previous sheet disappears

The CLI refuses outputs that escape the output directory, collide with an input, name a directory where a file is needed, or use a file as the output directory. The input collision check includes resolved aliases and existing hard links. Writes and removals are staged together, with rollback on a failed replacement.

Choose a dedicated scratch directory that contains no inputs. Do not work around a collision by deleting an input. A normal run can replace previous generated outputs in its destination. `check` writes a report but does not create a setup sheet or PNGs; it removes an old sheet and incompatible generated images. `traveler` also removes generated images absent from the current run. Use separate destinations when you need to keep older results.

Verify the artifacts appropriate to the command and current run. Use `traveler` when you want a new printable sheet:

```console
uv run prechips traveler examples/pivot-shaft/plan.toml --out out/docs-smoke/support-traveler
```

Inspect `report.json`, `traveler.html` and the images actually returned by the kernel. See [output safety](../report-and-telemetry.md#output-safety) for the full replacement contract.

## A report or sheet exists even though the command exited nonzero

Rule results do not prevent report generation. Exit 2 means at least one error finding. Exit 4 means unresolved readiness, including unavailable FreeCAD; an error takes precedence. Exit 3 identifies bad input or a handled output error, including invalid kernel render output rejected during report preparation. Unhandled failures can exit 1. The [CLI exit reference](../reference/cli.md#streams-and-errors) defines the command-specific behavior.

Read stderr, then inspect the current report when the run produced one. For exits 2 and 4, resolve the findings instead of assuming file creation means success. For an input or execution failure, do not rely on files retained from a previous run.

Verify both the process exit and report contents on the next run. Printable output from a failed readiness check is for planning and diagnosis, not an approval to machine.

## `explain` refuses a saved report or finds no matching row

`explain` checks the report's canonical content hash before selecting findings. It also validates the selected rows. Editing a value can invalidate the hash; a valid hash alone does not make malformed findings usable. The selector must match an actual `rule` and, if supplied, the exact `subject`.

Keep the original report unchanged. Regenerate it from its source bundle if it was edited or damaged. Copy the selector from its findings. For example, after the earlier check:

```console
uv run prechips explain out/docs-smoke/support-check/report.json construction:pivot-shaft
```

This command reads the saved report and prints the selected evidence; it does not regenerate geometry or write output files. Verify that the returned rule and subject match the intended finding. A successful explanation validates the saved content for this operation, not the truth of its input facts. See [saved-report validation](../report-and-telemetry.md#explaining-a-saved-report).

## OTLP export is disabled, or the collector receives nothing

Checking works without a collector. Exporters are created only when an OTLP endpoint is configured. Trace and log settings are separate; signal-specific protocol and timeout settings take precedence over common settings. Supported protocols are `http/protobuf` (the default) and `grpc`. Timeouts must be finite positive milliseconds.

For `OTLP export disabled`, correct the named environment variable. When an OTLP endpoint is configured, a malformed protocol or timeout disables both exporters for that invocation and emits a warning; it does not change machining findings. Without an endpoint, those settings are not validated and produce no such warning. For missing records without that warning, check the selected endpoint, transport, collector availability, headers and TLS settings. The OpenTelemetry exporter handles transport configuration. Use the [telemetry reference](../report-and-telemetry.md#telemetry-and-console) for variable names and signal endpoint behavior.

To return to an offline run, remove the common and signal-specific OTLP endpoint settings from the invoking environment. To verify export, rerun a check with a scratch output directory and inspect both trace and log receipt at the intended collector. A successful local check does not prove telemetry delivery, and exporter diagnostics do not resolve machining findings.
