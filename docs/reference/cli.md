# CLI reference

The installed `prechips` command has five noninteractive verbs. Each bundle command evaluates the current inputs; it does not reuse a saved report as its answer. For an ordered workflow, use the [quickstart](../manual/quickstart.md) or [tutorial](../manual/tutorial.md).

[Documentation](../README.md) | [Python interfaces](python-api.md) | [Report, approval and telemetry](../report-and-telemetry.md)

## Invocation

```text
prechips [--json] [--verbose] traveler PLAN [--inventory TOML] [--policy TOML]
    [--cutting-data TOML] [--out DIR] [--approval TOML] [--json] [--verbose]
prechips [--json] [--verbose] check PLAN [--inventory TOML] [--policy TOML]
    [--cutting-data TOML] [--out DIR] [--approval TOML] [--json] [--verbose]
prechips [--json] [--verbose] tools [QUERY] [--inventory TOML]
    [--measure [--plan TOML ...]] [--json] [--verbose]
prechips [--json] [--verbose] compare PLAN [PLAN ...] [--inventory TOML]
    [--policy TOML] [--cutting-data TOML] [--out DIR] [--json] [--verbose]
prechips [--json] [--verbose] explain REPORT RULE[:SUBJECT] [--json] [--verbose]
```

In a source checkout, prefix these commands with `uv run`. `uv run python -m prechips.cli` invokes the same entry point. There is no `python -m prechips` entry point.

| Option | Scope | Behavior |
| --- | --- | --- |
| `-h`, `--help` | Root command or any verb | Write usage/help to stdout and exit 0 without evaluating a plan. |
| `--version` | Before the verb, or on its own | Write `prechips VERSION` to stdout and exit 0. |
| `--json` | Before or after the verb | Default off. Write that verb's result as canonical JSON to stdout. Files still get written where the verb specifies them. Errors remain stderr diagnostics, not JSON error objects. |
| `--verbose` | Before or after the verb | Default off. Include debug messages and the full rule/subject/status/finding table on stderr. It does not change findings, report bytes or readiness. |

The parser requires one verb. Unknown options, missing arguments and invalid combinations described below return exit 3. Parser errors also print usage to stderr.

| Option | `traveler` | `check` | `tools` | `compare` | `explain` |
| --- | --- | --- | --- | --- | --- |
| `--json`, `--verbose` | Yes | Yes | Yes | Yes | Yes |
| `--inventory` | Yes | Yes | Yes | Yes | No |
| `--policy`, `--cutting-data`, `--out` | Yes | Yes | No | Yes | No |
| `--approval` | Yes | Yes | No | No | No |
| `--measure`, repeatable `--plan` | No | No | Yes | No | No |

## Bundle paths and overrides

`traveler`, `check` and `compare` accept these options. `PLAN` is a plan TOML file, not a directory.

| Option | Default and precedence |
| --- | --- |
| `--inventory TOML` | Explicit flag, then known `[paths].inventory` in that plan, then `PRECHIPS_INVENTORY`. Required after these choices. |
| `--policy TOML` | Explicit flag, then known `[paths].policy`, then `PRECHIPS_POLICY`, then the built-in required-rule set. |
| `--cutting-data TOML` | Explicit flag, then known `[paths].cutting_data`. Required. There is no cutting-data environment fallback. |
| `--out DIR` | Directory containing the first plan argument. Existing generated files can be overwritten or removed as described below. |
| `--approval TOML` | Absent. Accepted only by `traveler` and `check`; see [approval records](../report-and-telemetry.md#eligibility-and-approval). |

A plan-declared literal `"unknown"` is treated as absent when choosing a shop-file path, so it does not hide the environment fallback. Relative CLI and environment paths resolve against the working directory. Relative plan declarations and the plan's `features` path resolve against the plan directory. A STEP path in the feature manifest resolves against the manifest directory.

The loader determines a bundle root by walking the plan's parents: an `examples` directory uses its parent; otherwise a parent containing `pyproject.toml` is the root; otherwise the plan directory is the root. Plan-declared shop files, the manifest and referenced STEP assets must remain within that root after path resolution. Explicit CLI/environment shop files may be outside it. The loader reads and hashes operative files and checks a known manifest STEP digest against the referenced bytes. Citations are evidence pointers, not files fetched at runtime.

For `compare`, a shared override applies to every candidate. Without an override, each plan resolves its own declarations and environment fallback. See the [plan](../plan.md), [inventory](../inventory.md), [policy](../policy.md) and [cutting-data](../cutting-data.md) references for file contracts.

## `traveler`

```text
prechips traveler PLAN [bundle options] [--approval TOML] [--json] [--verbose]
```

Evaluate the bundle and write the report plus printable setup-sheet HTML. The command does not create a PDF or print on a device.

| Result | Behavior |
| --- | --- |
| `report.json` | Always written after a successful evaluation/output transaction, including exits 2 and 4. Contains the fresh canonical report. |
| `traveler.html` | Written from the current plan, findings, report and optional approval. It remains planned unless the current report and first-article record meet the approval requirements. |
| `setup-S<n>.png` | Written only when the current kernel result supplies that setup render. `<n>` is the setup's 1-based authored position, not its setup id. |
| `setup-S<n>-op<op>-<requirement>.png` | Written for returned inspection sketches requested by the plan. |
| stdout | Empty by default; the complete report with `--json`. |
| stderr | Findings and other diagnostics under the stream rules below. |
| Exit | 0, 2 or 4 from evaluation; 3 for handled bad input/output errors. Unexpected failures propagate. |

The report binds returned images by digest. Missing geometry stays unresolved; the command does not invent an image. A successful run removes previously generated setup/inspection PNGs that the current run did not return, including images from a longer route. It leaves unrelated files alone. See [kernel renders](../report-and-telemetry.md#kernel-renders).

`--approval` reads one root TOML record containing string `hash`, string `first_article` and optional `[inputs]` digest strings. Unknown root keys, malformed fields and unreadable files return 3. A stale hash or missing first-article evidence produces a warning and keeps the sheet planned; neither changes checker findings or waives unresolved required checks. Approval does not become an input to its own report hash.

## `check`

```text
prechips check PLAN [bundle options] [--approval TOML] [--json] [--verbose]
```

Run the same loader, kernel and rule pipeline as `traveler`, then write `report.json` without creating setup-sheet HTML or PNG files. Its report includes the same returned render metadata and image digests, so it can match the equivalent `traveler` report even though `check` does not write the images.

`check` removes any previous `traveler.html` in the output directory. It removes an existing generated setup/inspection PNG unless that file's bytes match the current returned asset, and removes stale generated PNGs not returned at all. These removals share the report's output transaction. Use a separate `--out` directory when you need to retain an earlier sheet.

Stdout is empty by default and contains the complete report with `--json`. Findings go to stderr. Evaluation exits are 0, 2 and 4. Handled bad input/output failures return 3. `--approval` is parsed and checked as for `traveler`, but `check` does not produce an approved sheet.

## `tools`

### Inventory query

```text
prechips tools [QUERY] [--inventory TOML] [--json] [--verbose]
```

List resolved inventory identities, supported set members and declared accessories. Supply the inventory with `--inventory` or `PRECHIPS_INVENTORY`; ordinary queries do not read a plan or its `[paths]` table. The flag takes precedence and relative paths use the working directory.

`QUERY` defaults to an empty string, which lists all candidates. Quote a query containing spaces. All nonnumeric words must occur case-insensitively in the resolved row's serialized identity and fields. A numeric token, optionally ending in `mm`, requests a millimetre diameter. The last numeric token wins and must be finite and positive. The search does not interpret an inch suffix as an inch diameter request.

Human stdout has columns for ID, kind, size in mm/in, holder chain, verification and sizing. Mill machine rows also show measured/unmeasured envelope facts. With `--json`, stdout is an array of resolved rows with size, diameter and verification fields; a numeric request adds `requested_dia_mm`, `sizing` and `reason`.

Sizing compares the nominal diameter with the request. A listed match is not a tool recommendation, and unresolved verification stays `unknown`. Query mismatches, unresolved rows and an empty result array do not change the command's successful exit 0. Invalid inventory/query input returns 3. The command writes no result files and does not start FreeCAD.

### Measurement checklist

```text
prechips tools --measure [--plan TOML ...] [--inventory TOML] [--json] [--verbose]
```

Repeat `--plan TOML` for each plan to include. Without `--plan`, the command looks for these four paths relative to the source checkout containing the CLI:

- `examples/pivot-shaft/plan.toml`
- `examples/rocker-arm/plan.toml`
- `examples/pivot-bracket/plan.toml`
- `examples/cone-pivot-post/built-up.toml`

Those defaults are a source-checkout convenience. An installation without the example tree needs explicit `--plan` arguments; missing default files are bad input, not an empty checklist.

The inventory flag or `PRECHIPS_INVENTORY`, when present, overrides each plan's inventory. Otherwise the normal bundle loader can use each plan's declaration. The loader still needs each plan's cutting-data path and applies its policy/default rules; this verb accepts no `--policy` or `--cutting-data` override. Referenced files and STEP hashes are still validated.

The command prepares kernel inputs and evaluates every registered rule on the host with an explicit `geometry was not requested` unresolved result. It does not discover FreeCAD, execute geometry or read/write the kernel cache. The checklist combines finding measurement entries with facts refused by kernel input preparation, then sorts and deduplicates them. This is consumed-plan measurement debt, not every potentially measurable inventory field. It adds no purchases or undeclared set members.

The checklist's completeness contract covers recorded-provenance debt for the requested plans: measuring every listed fact should clear that debt. A recorded-provenance unknown that the checklist fails to name is a checklist defect. This does not promise that measurements will clear unrelated unsupported geometry, missing process instructions or actual rule errors.

Human stdout contains `[ ]` instructions followed by citations. `--json` emits the checklist array, including fact identities, instructions, instruments, units and citations. Plan-owned identities are scoped by plan; inventory identities gain an inventory-path prefix when the requested plans use different inventories. No result files are written. Success returns 0 even when debt exists. Invalid input returns 3. A positional `QUERY`, if supplied with `--measure`, is not used. `--plan` without `--measure` returns 3.

## `compare`

```text
prechips compare PLAN [PLAN ...] [bundle options] [--json] [--verbose]
```

Evaluate one or more candidates and write `compare.json`. The command does not choose a route, create individual `report.json` files or write setup sheets/images.

Human stdout contains a candidate summary followed by side-by-side rule/subject findings. With `--json`, stdout contains the same canonical candidate array written to `compare.json`. Each row includes:

- The plan label, part, construction declaration, authored setup count and required fixture identities.
- Authored stock volume, sourced manifest net volume, waste ratio and their evidence.
- Finding-status counts, complete rule findings, input records and that candidate's evaluation exit.

Plan labels are relative to the candidates' common plan-directory root. Cross-volume Windows paths use absolute POSIX-form labels when there is no common root.

Waste is `(stock_volume_mm3 - net_volume_mm3) / stock_volume_mm3`. Only explicitly shaped round or rectangular blanks with adequate dimensions contribute known stock volume. Component stock must be nonempty to be counted. A profiled blank's volume is unresolved here. Net volume needs both a numeric manifest value and its citation. Missing evidence remains `"unknown"`; the command does not estimate a finished part from a bounding box. Invalid/nonpositive stock dimensions, invalid net volume or net volume greater than stock are bad input (exit 3). See the [comparison rules](../rules-comparison.md).

Construction permission is evaluated by the rules, including the drawing's explicit permission for a built-up route. Missing or unknown permission is not permission. The returned status is 2 if any candidate has a rule error, otherwise 4 if any candidate is unresolved, otherwise 0. Bad input/output errors return 3 and prevent a new comparison from being committed.

## `explain`

```text
prechips explain REPORT RULE[:SUBJECT] [--json] [--verbose]
```

Read a saved JSON report, verify its canonical hash and select findings. `REPORT` resolves against the working directory. `RULE` selects every subject for that rule. `RULE:SUBJECT` selects that exact subject, splitting at the first colon so a subject may itself contain colons.

The command validates every selected row before emitting findings. Selected rows need string rule, subject and message fields, a supported status, an object `numbers` and a string-list `cite`. An unreadable/malformed report, hash mismatch, malformed selected finding or no match returns 3. A matching hash establishes content integrity, not the truth of an input or machining safety.

Human stdout contains each selected `rule:subject` and status, formatted numbers and citations. Messages use the stderr finding logger; use `--verbose` to see the full table, including passing findings. `--json` emits one finding object for exactly one match and an array for multiple matches. No files are written, no input bundle is reloaded and no kernel is started. Successful explanation returns 0 even when a saved finding has error or unresolved status.

## Streams and errors

JSON stdout uses UTF-8, sorted keys, two-space indentation, finite numbers and one final LF. It contains the verb's result only. Do not merge stderr into stdout when another program consumes the JSON.

Normal stderr shows error (`✗`), warning (`!`), unknown (`?`) and unsupported (`?`) findings. Passing, informational and not-applicable findings are omitted from the normal finding display. Repeated kernel-unavailable messages are grouped in the normal display; `--verbose` shows the complete table. Color is used only for a terminal unless `NO_COLOR` is set. Diagnostics, including approval and optional exporter warnings, also use stderr.

| Exit | Meaning |
| --- | --- |
| `0` | A bundle report is eligible under the implemented readiness gate, or `tools`/`explain` completed successfully. Eligibility is not physical approval or a safety certificate. |
| `2` | At least one rule finding is `error`, including errors outside the shop-required subset. Report/comparison artifacts are still produced if output succeeds. |
| `3` | Handled bad input, argument error, approval-format error or output-path/write refusal. This takes precedence over an evaluation result. |
| `4` | No rule error, but required warning/unknown/unsupported findings, missing required coverage, unresolved required policy or a missing FreeCAD kernel prevents eligibility. Report/comparison artifacts are still produced if output succeeds. |
| `1` | An unexpected implementation exception propagates as a traceback under the installed command. It is not converted into bad input. |

The evaluation precedence is 2 before 4 before 0. A later handled output/approval error returns 3 instead. Help/version exit 0 without a report. A warning for an optional rule need not force exit 4. See [policy](../policy.md) for required subjects and checks that cannot be waived by omitting them from policy.

If report/asset construction rejects returned render data with `ValueError`, the CLI reports `Invalid kernel render output` as bad input (exit 3). This conversion does not cover every later renderer or implementation exception; unexpected failures still propagate instead of being relabeled as ordinary rule findings.

## Output safety and environment

Before evaluation, bundle verbs reject an output directory that names a file, target files that name directories, resolved output paths that escape the output directory, and targets that collide with an operative input or approval file, including hard links. A run stages its writes and removals before replacing targets; handled filesystem failures restore prior generated output where rollback succeeds. This is not a crash-recovery or concurrent-writer guarantee. Use separate output directories for concurrent runs. The [output-safety contract](../report-and-telemetry.md#output-safety) defines the limits.

Geometry discovery uses, in order:

1. Nonempty `FREECAD_CMD`, as a file path or command name. This choice is authoritative; an unavailable override does not fall through to another installation.
2. `%LOCALAPPDATA%/Programs/FreeCAD 1.1/bin/freecadcmd.exe`, when present.
3. `freecadcmd.exe`, `FreeCADCmd`, then `freecadcmd` on `PATH`.

`PRECHIPS_KERNEL_CACHE` selects the geometry-cache directory. Otherwise it is `prechips/geometry` under `LOCALAPPDATA`, or under `~/.cache` when `LOCALAPPDATA` is absent. These environment paths are interpreted by the host process; relative paths use its working directory. Cache results are memoized per bundle, and only successful geometry results are stored for reuse. The [geometry reference](../rules-geometry.md) describes native limits and worker settings.

Checks make no collector connection unless an explicit standard OTLP endpoint enables export. `OTEL_EXPORTER_OTLP_ENDPOINT` and per-signal `OTEL_EXPORTER_OTLP_TRACES_ENDPOINT`/`OTEL_EXPORTER_OTLP_LOGS_ENDPOINT` configure that optional output. Signal-specific protocol/timeout settings override common ones. A malformed protocol or timeout warns once and disables exporters without changing the report or checker exit. See [telemetry configuration](../report-and-telemetry.md#telemetry-and-console) for transport, headers, context and acceptance details.

Implementation: [parser and command orchestration](../../src/prechips/cli.py), [bundle loader](../../src/prechips/inputs.py), [readiness gate](../../src/prechips/findings.py), [kernel host](../../src/prechips/kernel/__init__.py).
