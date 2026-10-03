# Report binding, approval, output safety and telemetry

## Canonical report

`report.json` contains `expected_exit`, `findings`, `inputs`,
`prechips_version`, `rules_version`, `step_sha256`, `verification`, `hash`,
and, only when the kernel returned a setup render, `renders`.
Findings sort lexicographically by `(rule, subject)` and contain `rule`,
`subject`, `status`, `numbers`, `cite`, `message` (not `sentence` or a separate
severity). No clock timestamp enters the report.
The current catalogue is `rules_version = "m4-rev6"`; changing the operative
rule catalogue changes the bound report and invalidates prior approvals. Every
report produced from the M2 catalogue (`m2-rev6`) therefore has a stale hash.

Canonical bytes are UTF-8 JSON, sorted keys, two-space indentation,
`ensure_ascii=False`, finite numbers only, and **one final LF**. `hash` is the
SHA-256 of that same canonical serialization after removing **only** the root
`hash` member, including the final LF. Every read operative TOML/STEP asset has
its exact file-byte SHA-256. Input record keys are `plan`, `features`,
`inventory`, `shop_policy`, `cutting_data` plus referenced assets such as `step`.
Paths are root-relative POSIX labels; external explicit shop files use stable
`external/{kind}/{filename}` labels instead of machine-specific absolute roots.
The manifest STEP digest is also recorded separately; unknown does not become a
fabricated digest. An absent policy fallback has no file-byte digest.

Citations are evidence pointers, not operative assets loaded at runtime. HTML
and approval records are not inputs to their own report hash. A content/format
change to an input resets its digest even when it seems semantically identical.
`explain` verifies report integrity before selecting rows, then validates every
matching finding before emitting any finding logs or output. Selected findings
require string `rule`, `subject`, and `message`, a supported `status`, an object
`numbers`, and a list of strings `cite`. Missing or malformed selected fields
exit 3 with `Cannot explain report`, even when the report hash is valid.
A matching hash is not proof of machining safety or source truth.
The CLI also emits `bundle_binding:inputs`: unknown when the manifest STEP
digest is unknown, otherwise pass, with the full input records as evidence.
Its exact messages are `The part model is not bound to verified STEP bytes.`
and `The part model and every operative input are bound to the report.`
Citation: PLAN §5 input-bundle binding. This is digest bookkeeping, not kernel
verification or proof that an author-supplied digest came from a certified CAD
export. It blocks eligibility only if policy requires it.

## Kernel renders

When `prechips traveler` runs and the FreeCAD job returns `render_png_base64`
for a setup, the decoded bytes are written as `setup-S<n>.png` beside
`traveler.html` (`n` is the setup's 1-based authored position, not its id),
`report.json` gains `renders.<setup id> = {path, sha256, fixture, scene}` and
the same `{path, sha256}` record is added to `inputs` under `render:<setup id>`.
The render is therefore part of the hashed bundle: a different PNG changes
the report hash and stales any approval, exactly like an edited TOML.
`fixture` is `"modeled"` when the kernel reports `fixture_rendered = true`
for that setup (exact jaws, exact parallels, no debts) and `"unresolved"`
otherwise; `scene` is the kernel's `render_scene` object verbatim —
`jaws` (`absent` / `exact` / `lateral_undeclared`), `parallels` (`absent` /
`exact` / `not_modelled`) and `debts` (a list of sentences naming what the
picture does not establish), empty `{}` when the kernel returned none.
Bytes that are not a PNG signature are
a prechips failure (exit 1), not bad input. `check` records the same
`renders` / `render:<setup id>` entries (its report hash matches the
traveler's) but writes only `report.json`; the PNG file appears only with
`traveler`. The PNG filenames are preflighted with
the other outputs: an input at `setup-S1.png` is a collision (exit 3) and a
refused image replacement rolls back the report, sheet and prior image.
The render is a deterministic software rasterization of the kernel's
tessellation, so a cache hit and a fresh FreeCAD run give identical bytes; it
is a view of the part plus only the fixture solids built from explicit
inventory dimensions and the declared pose, never a toolpath or a CAM
simulation. See [geometry rules](rules-geometry.md#renders).


## Eligibility and approval

Any error wins (exit 2). Required warn/unknown/unsupported or a missing required
rule/subject yields 4; an explicitly unknown required policy also yields 4.
Otherwise the report has exit 0 and `verification = "checked"`.
The implemented gate does not block required `info` or `not_applicable`. Without
approval the traveler still prints `PLANNED — NOT APPROVED FOR THIS INPUT BUNDLE`.
The footer text is `prechips <version> · report <first 8 hash chars>`.
That short id is only a paper lookup aid, never the approval's full binding.
The renderer additionally requires the normalized approval `approved = true`,
no approval warnings, a lowercase 64-hex report hash, and first-article text
other than literal `unknown` (case-insensitive). These are renderer guards, not
extra keys to write in the TOML approval record.


Supply `--approval approvals.toml`. A normalized record permits only `hash`,
`first_article`, and optional `inputs`:

```toml
hash = "<full current report hash>"
first_article = "<actual logbook/evidence reference from the cut first article>"

[inputs]
plan = "<prior SHA-256>"
features = { sha256 = "<prior SHA-256>" }
```

Alternatively use a history of array tables:

```toml
[[approvals]]
hash = "<full report hash>"
first_article = "<actual evidence reference>"

[approvals.inputs]
plan = "<prior SHA-256>"
```

These placeholder strings illustrate shape, not supplied approval evidence.
`inputs` can contain digest strings or tables carrying `sha256` (report-style
path metadata may accompany a digest table). The parser selects the first
record with the exact current hash; if none match it uses the last record to
explain changed inputs. `hash` and `first_article` must be strings. Only a full
hash match, a **nonblank** first-article string, and an eligible report remove
PLANNED. Neither a matching short id nor a stale record nor an empty evidence
string suffices. Approval parsing does not authenticate evidence or perform
the first article; the shop owns its truth.

Stale record warning: `Approval no longer matches: {changed input names} changed.
Repeat the first article.` Only input names declared in the prior record and
present in the current report are compared; an omitted prior input is never
named as changed. Digest strings and digest tables follow the same comparison.
The warning names `the operative bundle` when prior `inputs` is absent or
empty, there are no input names in common, or all compared digests are unchanged
despite the stale report hash. A matching record for an ineligible report warns:
`The report still has unresolved shop-required checks; approval cannot waive them.`
Approval never changes the checker exit. `check` also parses/warns on approval,
but does not produce a sheet.

## Output safety

All input bundles and output targets are preflighted before evaluation/writing.
Manifest, plan-declared shop files and STEP assets must stay inside the bundle
root. Explicit CLI/environment shop paths may be external. `--out` may be an
authored directory anywhere; every
fixed output filename must resolve inside it. No output can alias an input by
resolved path or hard link, escape by symlink, or name a directory. The output
root cannot name a file. Approval files are included in collision protection.
Existing regular output files are replaced. Each output is first written in
full to a hidden temporary beside its target (`.<name>.<random>.tmp`), and no
target is replaced until every output is staged. The prior bytes of any earlier
target are kept until the last replacement lands. If the filesystem refuses the
directory, a staged write or a replacement, the run exits 3. The temporaries are
removed and every target that was already replaced gets its prior bytes back,
or is removed if it is new. A failed run therefore never leaves a new
`report.json` next to an old `traveler.html`. An output directory created for
the run may remain, empty. This does not cover a process kill between the two
replacements, or a failure of the restoring rename itself. That second error
exits 1, and the prior bytes stay in the temporary backup.

Exit 3 covers bad input, output preflight and output-file writes. Any other
exception is a prechips bug, not bad input: for example, a rule that raises or
that returns duplicate subjects. It is outside the 0/2/3/4 exit contract and
gives Python's ordinary traceback and exit 1. Telemetry still flushes. Generation
finishes before any output is staged, and a staged write rolls back on any
exception, so such a failure writes no output. A failure writing stdout after
the files are in place is also exit 1.
No verb reads expected fixtures as runtime answers.

## Generated traveler

The bench document uses Letter portrait print CSS, a header, each authored
setup, and per-setup contour continuations. Logical continuation groups are
not a count or proof of physical printed pages. Reflection compression is used
only when the fresh computed table contains every counterpart checkpoint, not
from presumed symmetry.
Footers are in normal document flow, not fixed over bench content. Identical
station positions may be grouped while retaining all provenance; diameter-mode
lathe station tables omit nonoperative Y. Unresolved checks are grouped for
compact bench presentation, not hidden or waived.
Each setup page carries one figure after the Hold block. The caption follows
the render record: `modeled` → `Kernel view: part and declared jaws /
parallels; sampled checks are not a toolpath.`; unresolved with
`scene.jaws = "lateral_undeclared"` → `? Kernel view: part, certain jaw
material and a conservative possible-jaw envelope; exact fixture pose is
unresolved.`; unresolved with `scene.jaws = "exact"` (parallels not modelled
or another debt) → `? Kernel view: part and declared jaws; the fixture scene
is incomplete.`; otherwise `? Kernel part view only; fixture dimensions or
jaw pose remain unresolved.` Every `scene.debts` sentence is appended to the
caption. With no render the paragraph `? Kernel fixture render unavailable;
holding geometry is not confirmed.` prints instead. The header legend states
`Kernel geometry findings use sampled tool / holder solids, not CAM
toolpaths. An unresolved fixture is not a rendered holding proof.` The image
is referenced by relative filename, so the HTML shows it only beside its own
`setup-S<n>.png`.
Unknown drawing dimensions remain explicit. Declared dimension precision controls
drawing values, manual settings, DRO-zero values and genuine feature points when
available; without it, every known finite number still prints its own digits.
Operation-derived coordinate rows, tip/Z targets, computed stations and
contour/cutter-centre targets always retain their own numeric digits: six
significant digits, with floating residue below `1e-6` dropped. Unrelated drawing
precision never rounds or hides these operative targets. Actual unknown numeric
values remain `?`. No acceptance band or drawing precision is invented, and
numeric presentation never changes PLANNED readiness.
Bench text excludes rule ids, source paths and full hashes; the footer short id
is the report lookup. Generated logical sections and print CSS are not physical
clipping/dry-run proof. The paper acceptance remains pending.


## Telemetry and console

The OpenTelemetry API, SDK and OTLP HTTP/gRPC exporters require `>=1.39.1`.
The API is a direct dependency because this module imports its tracing and log
record types. Logs use the API `LogRecord` form of `Logger.emit`, with exception
details carried as standard attributes, rather than a newer `exception` keyword.
The telemetry suite passes with all four packages pinned to `1.39.1`, including
local HTTP and gRPC export with correlated finding context.

Every invocation has a `prechips.<verb>` root span (initial usage may be named
`prechips.usage` when a global flag comes first). Inputs use `input.load`, outputs
`output.write`, evaluations `rule.<name>` and finding records child spans. The
single FreeCAD job of a run, including its cache lookup, runs under one
`kernel.geometry` span opened by whichever geometry rule evaluates first.
When no kernel is found, every geometry finding carries
`numbers.kernel_unavailable = true`; the console prints that identical
kernel-naming `?` sentence once per run unless `--verbose` shows the full
table, while the report and the OTel records keep every finding.
Records carry rule, subject, status, numbers and citations. The same Python
logging records feed OTel and Rich stderr, so console and exported facts agree.
`--verbose` renders the full finding table; ordinary stderr renders unresolved
and error glyphs. Non-TTY/`NO_COLOR` disables color, not the glyphs.

Resource identity: `service.name=prechips`, package `service.version`, optional
`service.namespace` from `OTEL_SERVICE_NAMESPACE`. Valid W3C `TRACEPARENT` and
optional `TRACESTATE` continue the parent context. No endpoint means no exporter,
collector discovery, network request or missing-endpoint warning.
Each configure-after-flush invocation starts a fresh root/span pipeline; a live
session is reused only until its idempotent flush closes it. A known STEP digest
cannot replace the actual referenced bytes: the loader requires and hashes them.

Standard `OTEL_EXPORTER_OTLP_ENDPOINT`/`PROTOCOL` configure both signals;
signal-specific `OTEL_EXPORTER_OTLP_TRACES_*` and `OTEL_EXPORTER_OTLP_LOGS_*`
override them. Protocol is `http/protobuf` (default) or `grpc`; SDK headers/TLS
follow standard exporter environment variables. Timeout is milliseconds in the
environment, converted to exporter seconds. Batch processors flush/shut down on
exit, including bad input. Export is optional. If
the protocol is unsupported, or the timeout is not a positive number of
milliseconds, export is disabled for both signals in that invocation. Stderr gets
one `! OTLP export disabled: …` warning naming the variable. The exit, report and
sheet are those of an unconfigured run.

See [AGENTS.md](../AGENTS.md) for local collector and farm acceptance procedures.
Local exporter tests do not substitute for a real parented farm run observed in
App Insights by `operation_Id`. That live acceptance and physical print/dry-run
rehearsal remain **unobserved/pending**.
