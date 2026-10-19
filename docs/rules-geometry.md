# Geometry and workholding rules (M4, FreeCAD kernel)

Geometry rules compare the finished STEP faces with the material present at
each authored setup, using FreeCAD's bundled OpenCASCADE. Use this reference to
interpret geometry findings, identify the inputs they need, and understand the
limits of a pass. The rules compare sampled intersections and B-rep
measurements with the selected tools, holders, fixture dimensions and declared
pose. They do not simulate a cut, generate a toolpath or certify a physical
setup.

Facts the kernel cannot measure from explicit inputs stay `?` with a named
reason. A bounding box, catalogue label or length fact carrying verification
debt cannot substitute for the required geometry.

## Find a geometry contract

- For execution, missing FreeCAD and reuse of results, see
  [kernel execution](#one-job-one-kernel-no-network), [errors](#kernel-errors)
  and [cache identity](#cache).
- For face references and tool poses, see [face identity](#face-identity),
  [approach models](#approach-models) and [accepted inputs](#inputs-the-job-accepts).
- For stock routes, assemblies and waste removal, see
  [in-process stock](#in-process-stock),
  [joint preparation and assembly](#transient-joint-preparation-and-assembly),
  [retained part-off outputs](#retained-part-off-outputs),
  [saw cuts](#saw-cut-off) and [piece selection](#keep-piece).
- For cutting findings, see [accessibility](#accessibility), [reach](#reach),
  [corner radii](#internal_corner_radius), [face coverage](#coverage),
  [blank credit](#blank_credit) and [finish coverage](#finish_coverage).
- For holding and pictures, see [vise contact](#vise),
  [loaded wall thickness](#thin_wall_under_clamp),
  [fixture interference](#fixture_interference), [renders](#renders) and
  [model limits](#limits).

For a command to run, use the [quickstart](manual/quickstart.md). The
[tutorial](manual/tutorial.md) explains the input files, and the
[demonstration](manual/demo.md) pairs a shipped bundle with observed output.
Use [troubleshooting](manual/troubleshooting.md) for failures, the
[FAQ](manual/faq.md) for product boundaries, and the [CLI catalog](reference/cli.md)
or [Python catalog](reference/python-api.md) for interfaces. Implementation
structure belongs in [architecture](internals/architecture.md) and
[development](internals/development.md).

## Rule catalog

The [rule registry](../src/prechips/rules/__init__.py) contains 13 geometry
rules. Findings are conditional: a rule can emit one row per operation, setup
or feature, or no rows when its subject is absent. `joint_fit` and
`joint_thread` are separate declared-input rules, not two of these 13.

| Rule | Subject | Contract |
|---|---|---|
| `accessibility` | `setup:op` per cutting operation | [PLAN §4.2 accessibility](#accessibility) |
| `reach` | `setup:op` | [PLAN §4.2 reach](#reach) |
| `internal_corner_radius` | `setup:op` | [PLAN §4.2 internal corner radius](#internal_corner_radius) |
| `coverage` | the plan's `part` name | [PLAN §4.2 coverage](#coverage) |
| `blank_credit` | each feature owning an as-is face of a profiled blank, or the face reference when no feature owns it | [PLAN §4.2 blank_credit](#blank_credit) |
| `finish_coverage` | one subject per manifest feature | [PLAN §4.2 finish coverage](#finish_coverage) |
| `vise` | setup id | [PLAN §4.3 vise](#vise) |
| `thin_wall_under_clamp` | setup id | [PLAN §4.3 thin wall under clamp](#thin_wall_under_clamp) |
| `fixture_interference` | setup id | [PLAN §4.3 fixture interference](#fixture_interference) |
| `saw_cut` | `setup:op` for a straight or scribed-line saw cut | [Saw cut-off](#saw-cut-off) and [scribed-line cuts](#saw-to-a-scribed-line) |
| `saw_teeth` | `setup:op` for each saw cut | [Saw teeth in the work](#saw-teeth-in-the-work) |
| `keep_piece` | `setup:op` for each authored `keep` | [Keep piece](#keep-piece) |
| `joint_assembly` | each setup with array `stock_in` | [Joint assembly findings](#joint_assembly-findings) |

## Finding evidence

Rules using the shared provenance builder start their citation list with the
corresponding PLAN §4.2 or §4.3 rule row. When the manifest digest is known,
they add `kernel: STEP SHA-256 <digest>; FreeCAD B-rep measurements`, followed
by the relevant owners:

- The feature: exported `features.<name>: faces and requirements`,
  author-owned `plan.joint_features.<id>: analytic transient cylinder`, or
  `plan.process_features.<name>: STOCK PREPARATION — plan only, not a drawing
  dimension`, with its citations.
- The setup: `plan.setups.<id>: frame and hold`, resolved fixture and
  parallels rows with their citations, and the frame citation.
- The operation: `plan.setups.<id>.ops.<n>: selected action/tool/holder`
  and resolved tool and holder rows.

`thin_wall_under_clamp` also cites
`shop-policy.numbers.thin_wall_floor_mm`. `joint_assembly` adds its joint
declaration and citations. The keep and saw rules use narrower evidence lists:

- `keep_piece` cites the operation's `.keep`, its feature and
  `docs/rules-geometry.md: keep piece`.
- `saw_cut` cites the cut-plane and kerf facts with
  `docs/rules-geometry.md: saw cut-off`, or the scribed-line declaration with
  `docs/rules-geometry.md: saw to a scribed line`.
- `saw_teeth` cites blade pitch, the policy minimum and
  `docs/rules-geometry.md: saw teeth in the work`.

The kernel reports measurements only. The host constructs citations.

Drill-kind `rough_profile` / `chain_drill` operations use drilling starting
data without changing their geometric face claims or kernel removal contract.
Deep-hole speed derating consumes the canonical before-stock feature entry
(else stock top), not a previous chain endpoint; see
[cutting data](cutting-data.md) for this depth and axial-feed contract.

## One job, one kernel, no network

The host evaluates geometry at most once per bundle. It builds a canonical JSON
job for each candidate from the STEP path and digest, feature and explicit
operation face claims, faces that [faced aims](plan.md#aims) move, authored
stock envelope and `stock.as_is_faces`, normalized joint primitives and
assembly declarations, setup order, frames, stock chain, holding geometry and
cutting dimensions and endpoints.

Uncached jobs go to one `freecadcmd.exe <freecad_job.py> -- INPUT_JSON
OUTPUT_JSON` subprocess as a batch. `compare` batches all its candidates in
that process. Each bundle memoizes its result, so dependent rules read the
same facts. The subprocess has a 1200 s runaway guard
(`kernel.RUNAWAY_GUARD_S`), reads its input file, writes its output file and
prints nothing. It uses the bundle's own STEP file and makes no network requests.

No process in the run outlives the process that `FREECAD_CMD` starts. That
process can be a launcher that runs `freecadcmd` as its child, such as a Linux
AppImage's `AppRun` shell. On POSIX the run has its own session. When the
process ends, the guard expires or the host is interrupted, the host kills the
run's process group, including the launcher, engine and pool workers, before
reaping the process. This prevents reuse of the group id before cleanup.

### Kernel discovery and availability

The host resolves FreeCAD in this order:

1. A nonempty `FREECAD_CMD`, resolved as a file path or command on `PATH`.
   This override is authoritative. An unavailable override does not fall back.
2. `%LOCALAPPDATA%/Programs/FreeCAD 1.1/bin/freecadcmd.exe`, when that file exists.
3. `freecadcmd.exe`, `FreeCADCmd`, then `freecadcmd` on `PATH`.

Without a kernel, findings that need kernel facts become `unknown` with
`FreeCAD kernel unavailable; install FreeCAD or set FREECAD_CMD.`,
`numbers.kernel_status = "unknown"` and `numbers.kernel_unavailable = true`.
Availability can be checked before ordinary applicability, so a lathe setup's
`vise` row can be unknown rather than `not_applicable`.

Some scope decisions precede availability. For nonspindle bandsaw and hand-saw
operations, `accessibility`, `reach` and `internal_corner_radius` stay
`not_applicable` because their tool-cylinder model never applies to a blade.
For a mill-mounted `slitting_saw`, physical accessibility and reach instead
stay unknown: the planar cut does not model a finite disk or its assembly.
Rules with no applicable subject can emit no findings, and an invalid `keep`
can name its feature debt without calling the kernel. `saw_cut` checks known station
mismatches, a verified nonpositive kerf on a straight cut and any reported
native `saw_error` before accepting a kernel-unavailable finding. Those
certain errors remain `error` even when kernel facts are unavailable.

An emitted `kernel_unavailable` flag forces exit 4 unless an error already
requires exit 2. This applies even when policy does not require the rule. The
console combines the repeated availability sentence into one `?` line;
`--verbose` shows each row, and the report retains each emitted finding.
Missing kernel facts remain unresolved, never a pass.

### STEP binding and import

The STEP must be bound before the kernel is called: an unknown `step_sha256`,
no `step` asset, or bytes whose SHA-256 differs from the manifest value give
`unknown` rows with `STEP bytes and their manifest SHA-256 are required for
FreeCAD geometry.` or `STEP bytes do not match the manifest SHA-256; face
identity is unresolved.` All four reference bundles bind adjacent consumer STEP
exports. The bracket keeps a hand-authored manifest on the v39 STEP without
feature labels; its illustrative acceptance bands are not drawing limits.
`examples/rocker-arm`, `examples/pivot-shaft` and `examples/cone-pivot-post`
bind the consumer's labelled exports
(`HAF_<FEATURE>__P<nn>` labels; a periodic surface arrives as several
`ADVANCED_FACE` patches under one feature label, each bound by its own
entity/ordinal) with each feature's `faces` copied from that export. In the
rocker export, `strap_faces` names only the −Z broad face. S1's upper strap operations
explicitly claim the exported `strap_datum_b` face in the plan; they do not
rewrite the manifest's face identity. The outline profile operations in S1, S2
and S3 explicitly claim both exported tip lands (`tip_land_pos_x`,
`tip_land_neg_x`) together with `profile_outer`, so the rocker reports no
unclaimed faces. Unmeasured stock/fixture inputs remain named geometry debts, not
finished-solid clearance passes.

An ordinary monolithic import still needs one valid finished solid. A
multi-solid STEP is supported only with an explicit
[named finished-solid map](features.md#named-finished-solids) naming every source
`MANIFOLD_SOLID_BREP` by its exact entity, source ordinal and label. The host
checks the complete source identities; the native kernel independently
associates each named source shell's bound faces with exactly one imported
solid. The association must be bijective. Import order, nearest shape and
bounding-box proximity never break a tie.

The engine returns `unknown` for an import with no finished solids, faces
outside the finished solids, or an invalid B-rep. A missing/incomplete native
named-solid map or unresolved source-face association withholds the affected
solid's ownership proof, never substitutes an empty protected solid. A
malformed or incomplete authored `features.solids` source map is bad input
before the native job. The nominal overall geometry may be a compound; that
does not make disconnected material a joined assembly.

Faced aims on multiple finished solids remain `unknown`; naming the solids
does not extend the one-solid [faced-aim model](plan.md#faced-aims).

An unparseable STEP, a digest mismatch detected inside the engine, or an
exception in a job produces `error`. Exceptions name their location as
`<Type>: <message> at freecad_job.py:<line> in <function>`.

### Kernel errors

Every `error` result names a specific, non-empty `reason`; the host fills one in
for an engine error that names none (`FreeCAD kernel reported job <n> as an
error without a reason`). A batch that ends without a usable result yields
`error` rows for each of its jobs naming how it ended:

* `FreeCAD kernel exceeded the <s> s runaway guard and was killed`
  (`kernel.RUNAWAY_GUARD_S`);
* `FreeCAD kernel exited <code>`, with `: killed by <SIGNAL>` when a negative
  code or a launcher shell's `128 + N` names a signal (SIGKILL is often the
  host's out-of-memory killer);
* `FreeCAD kernel exited 0 without writing its result file`, `… wrote an empty
  result file`, `… did not return valid JSON: …`, `… returned an invalid batch
  result contract`;
* `kernel batch failed: …` or `kernel result is not strict JSON: …`, written by
  the engine itself when its batch raises or its result holds a NaN.

Each reason identifies the engine phase and includes the last 2000 characters
of stderr, or stdout when stderr is empty, or `no stderr or stdout output`.
The phase comes from the engine's progress trail: every timed span
(`batch`, `job <n>`, the job's `step_import`, `face_binding`, `stock_prep` and
`cross_setup` phases, each setup, its phases and ops) appends a flushed
enter/exit line to `<output>.trail` beside the result file, so a killed engine
still leaves it. The error's `timing` holds `host_wall_ms` and `trail = {open,
finished, last_mark_ms}` (open spans, deepest last, and the last 20 finished
ones, in engine-clock milliseconds). `FreeCAD kernel batch returned the wrong
number of results.`, `FreeCAD kernel job failed: …` (the launch itself failed)
and `Cannot identify FreeCAD kernel: …` remain. Errors are exit 2 like any
other error and are never cached: an operational kernel failure is not an
unknown measurement.

### Cache

Successful (`status = "ok"`) results are cached as JSON under
`PRECHIPS_KERNEL_CACHE`, else `%LOCALAPPDATA%\prechips\geometry` (or
`~/.cache/prechips/geometry` without `LOCALAPPDATA`). The key is the SHA-256
of the canonical job without its `step_path` (the STEP digest and every
numeric input are inside), the digest of the engine sources `freecadcmd`
executes (`kernel.ENGINE_SOURCES`: `freecad_job.py` and its transitive local
imports, never host-only `kernel/__init__.py` or `render_inputs.py`), and the
kernel executable's resolved path and freshly read byte SHA-256.

#### Inputs that change the cache key

Changing a consumed geometry input, the STEP, the engine or the kernel
executable bytes therefore misses; moving the bundle does not. A
[profiled blank](plan.md#profiled-blank) enters the job as its declared
`step_sha256` without its absolute path: the host re-reads the blank's bytes
before keying, so new bytes under a new digest miss and bytes changed under a
stale digest are refused (`unknown`, never a hit on the old key). Its vendor
tolerance and citation are host-only and never key geometry.
Host-only action and finishing metadata that transient preparation does not
consume, tool OAL after projection resolves, protective hold-method text, and
item-level `verify` / `present` / `source` flags around a consumed fact do
not enter the engine job and do not invalidate geometry.
`unknown` and `error` results are never cached. A cache that cannot be written
leaves the returned facts
unchanged. A hit returns the stored facts and render bytes of the run that
produced it. Fresh native runs are not proven bit-repeatable; see the
[print and native acceptance limits](../examples/README.md#print-and-native-acceptance-limits).
The cache is not part of the hashed bundle.
Host-side kernel code stays out of the engine digest because whatever it
changes in the job the engine receives already changes the key: the batch sent
to `freecadcmd` is exactly the keyed job. Tests derive the engine's import
closure from `freecad_job.py` and fail when `ENGINE_SOURCES` misses or adds a
module.
Native collision fixes change that engine-source digest and require new
geometry results under the new key. Existing cache entries remain evidence
of their original worker source; they are never relabelled or copied to the
new key.

#### External CI cache

CI persists this local result-cache directory in a separate external cache.
Its namespace includes runner OS/architecture, the pinned FreeCAD AppImage
SHA-256, cache epoch and the same engine source digest, printed by
`prechips.kernel._engine_digest()`. Each save key adds the test shard's
index, then the unique workflow run ID and attempt; a shard restores its own
latest entry first, then any entry under the shared namespace prefix. Each
shard saves only after it succeeds
([CI cache policy](../.github/workflows/ci.yml)).

### Worker processes

Booleans whose operands are known before the loop that needs them (each printed
checkpoint row's removal, rough-leave and stock booleans; each culled reach column
and tool or holder pose cylinder against its stock) may run in extra `freecadcmd`
worker processes. `PRECHIPS_KERNEL_WORKERS` sets how many: unset or empty, one per
spare CPU (CPU count − 1), at most 8; `0`, or anything but a whole number, runs
none and keeps every boolean in the engine. Workers exist only when the engine
itself runs under `freecadcmd`, start with the first loop that shares operands and
stop when the job ends. A loop hands its booleans to the workers in the order it
takes them and takes each answer where it would compute it; caches, cache caps and
control flow are those of the engine alone, and a loop's calls it never takes are
cancelled when it ends.

No worker outlives the engine, however it ends, including when the host's
runaway guard kills it (on POSIX with the rest of the run's process
group) while a worker is inside a boolean. On Windows
the engine puts itself in a job object set to kill every process in it when its
only handle closes, which happens as the engine ends, and starts its workers in it;
on Linux each worker asks the kernel to kill it when the engine dies and serves
nothing if the engine is already gone. Where neither binding holds (Windows refuses
the job, or another system), no worker starts. The workers' operand files live in a
directory inside the host's job directory, beside the job's input and output, which
the host removes after every run, a killed one included.

A worker runs the engine's function on OCC binary B-rep copies of the operands.
The copies preserve doubles, tolerances, locations and shared sub-shapes within
one call. Operands with triangulation stay in the engine because booleans can
read it and binary B-rep drops it. A row removal sharing a face or edge with its
stock is recomputed in the engine because a later render mesh could reach it.
The engine computes any call whose worker has not started, failed, raised or
been lost; native errors still propagate. Facts do not depend on the worker
count, which is not part of the cache key. Batch timing records worker answers
as the non-operative `pool_answers`.

`PRECHIPS_KERNEL_POOL_WAIT=1` is the deterministic test mode: the engine waits for
a worker's answer to every call it handed out while any worker can still answer,
instead of computing a call no worker has started, so which booleans workers
answer does not depend on timing. Tests and audits use it; checks and travelers
leave it unset.

## Face identity

Feature `faces` and `stock.as_is_faces` use STEP references in the consumer's
export form. This reference-format fragment defines the three components:

```text
#<entity>/ADVANCED_FACE[<ordinal>]/<label>
```

where `entity` is the STEP instance id, `ordinal` the 1-based position of that
record among the file's simple `ADVANCED_FACE` records, and `label` the
record's raw name string (the consumer's labelled export writes
`HAF_<FEATURE>__P<nn>`, one label per feature patch; a plain SolidWorks
export writes `NONE`, and FreeCAD writes an empty string). The label is matched,
never interpreted. A shared label does not merge records: each patch keeps its
own entity/ordinal reference. All three components must agree with the exact STEP bytes: a
malformed string, an id that is not an `ADVANCED_FACE`, a wrong ordinal or a
wrong label is an error naming the reference (`… STEP has no instance #n`,
`… is ADVANCED_FACE ordinal 3, not 2`, `… carries label 'a', not 'b'`).

### Imported-face binding

A reference is bound to an imported face by geometry, never by position: the
engine rewrites the STEP so a reader transfers only that one `ADVANCED_FACE`
(same representation chain and units), takes its surface kind, area and
optimal bounding box and outward orientation, and looks for exactly one face
of the full import with the same signature (area within the kernel's
1e-6 relative/absolute mm² tolerance and bbox within 1e-4 mm). Oppositely
oriented coincident faces can therefore retain distinct material-side
identities. Zero matches, several same-signature matches, or two source faces
that both match one imported face are mapping errors. Shell/solid membership
then binds the source faces to the named finished solid; sharing a surface or
edge does not transfer ownership. Genuinely ambiguous same-orientation faces
remain ambiguous, not resolved by import order or guessing. In the
report, every rule that needs the feature is `error` with
`numbers.mapping_errors` and `<subject>: invalid STEP face reference(s):
<refs>.` A feature whose `faces` is omitted, `"unknown"` or empty keeps its
rows `unknown` (`feature face references are unknown or unmapped`). Imported
faces that no reference names are labelled `imported face index <n>`
(0-based) wherever the kernel has to name them, for example in `coverage`.
Each imported face's record in `faces` gives its `index`, `ref`, surface
`kind`, `area_mm2`, `bbox_mm` and `fills_bbox`: true only for a plane with one
wire whose every edge is a straight segment within the kernel's 1e-6 mm side
tolerance of a side of its flat box, and with more area than that band along the
sides, so the face is that whole rectangle but for the band; a hole of any size,
or a notch reaching further in, however little area it takes, makes it false, as
does a face lying wholly in the band (a rim along three sides).

### Joint targets and final-face credit

Plan-owned joint cylinders are separate analytic targets with
`plan.joint_features.<id>: analytic transient cylinder` provenance. They are
never assigned synthetic STEP entity references and never enter final face,
source, as-is, coverage or corner
mappings. Dimensional and operation consumers use the resolved feature mapping;
final `coverage` and `finish_coverage` still iterate only the original manifest.
Neither transient completion nor joint filler proves a final surface was cut.
A joint op's analytic claims never credit an imported face. The one exception
is measured: a finishing spigot turn whose cut the stock builder accepted
certifies (`certified_indices`) each imported face it leaves as its own turned
surface. The face must be an outward cylinder face lying on the turned cylinder
itself: its radius and axis match the turned diameter and spigot axis within
1e-6 mm over the face's whole extent, so a cut that leaves stock even below the
0.001 mm stock tolerance earns nothing. Its full area must lie inside the op's
finite cut window, inside that component's owned finished material and on the
accepted after-op stock.

A fit's band need not hold the model's basic size. An r6 land
(`dia = [10.223, 10.234]`) is turned over a hub OD the model draws at basic Ø10.20,
whose own band is `[9.69, 10.71]`. The size is then judged by the declared bands,
not by the model's radius. A face on the spigot axis at another radius is
certified when every exported feature naming it has a known `dia` band (a `dia`
requirement and known units) that holds both the spigot's declared `dia` band and
the face's own diameter. The axis and the cylinder shape still match within
1e-6 mm. The face's full area must lie inside the cut window at its own radius and
inside the owned finished material. The face carried radially onto the turned
radius must lie on the accepted after-op stock. A land whose band runs past the
exported band, even by 0.0001 mm, certifies nothing, and neither does a face no
exported feature with a known `dia` band names. The rule runs both ways. A clearance land
turned below a boss drawn at basic (`dia = [9.7, 9.8]` under Ø9.8) certifies the
face the same way, with the turned surface inside the owned finished material.
The join's backstop does not count the skin it takes as lost: the finished
material under such a face, down to the land's MIN radius and within the spigot's
axial span. Material under the MIN is still protected and still lost. Only those faces earn `coverage`, and
`finish_coverage` too when the op is a finishing cut. A rough, unknown,
stopped or rejected cut, a face outside or only partly inside the window, a
face at another diameter its exported band does not admit, a face about another
axis and any transient index earn nothing. Earning
nothing leaves the face's coverage and finishing obligations open. It does not
turn those obligations into debt or `not_applicable`.

The other exception is a face the join itself forms. A joint's `forms` lists
exported features whose faces no op cuts because the join leaves them, such as a
hub-to-strap root fillet `R0.2 MAX` (`radius = [0, 0.2]`) that the press leaves
sharp. `coverage` credits that feature's faces to the joint only when three things
hold:

1. The join assembles, with known joined stock.
2. The kernel admits the joined corner inside the feature's own band (see the
   [assembly backstop](#transient-joint-preparation-and-assembly)).
3. The last op that names the feature and checks its `radius` band, in a setup
   downstream of the joint or in the joint's own setup after its first `fit` (the op
   that joins; a setup with none joins on entry), passes that check under
   [inspection's](rules-inspection.md) gauge capability rule. A leaf at or under
   the `[0, r]` limit is enough when the gauge declares no leaf tolerance (or zero).
   With a positive tolerance the check is unknown until the traveler names the safe
   leaf. A check on an op naming another
   feature reads that feature, not this one.

If the inspection is missing or not a pass, or the join is unresolved, the credit
is debt (`?`), never a pass. Those faces are then left out of `unclaimed_faces`,
but any other unclaimed face is still an error. A refused join credits nothing.

### Process targets and preparation cuts

Plan [process features](plan.md#process-features) (a faced `end_face`, a
`centre_hole`, a `tooling_hole`) are analytic stock preparation labelled
`plan.process_features.<id>`. The kernel adds them as transient faces after
the STEP faces (an end face is the disc through `at` normal to `axis`,
intersected with the stock; a centre is its reversed countersink cone and pilot
cylinder), so they are never STEP indices and never enter final face, source,
as-is, corner, `coverage` or `finish_coverage` mappings. A process op credits
no imported face, even when its cut lies on a drawing plane, and is never
claim debt. Facing an end face uses the turning model with the disc as its
claim. A milled end face removes only the stock its op's generated cutter-centre
passes ([coordinates](rules-coordinates.md) profiles, setup frame) sweep, as the
cutter's radius about each pass from the op's `to_z` up over the stock; a pass
stopped short, misplaced or cut in air leaves its slab on the stock, and passes
coordinates cannot generate leave the op unknown. A `center_drill` op removes the
analytic centre (countersink of
`countersink_angle_deg` to `mouth_dia_mm`, pilot of `drill_dia_mm` and
`drill_length_mm`, point cone from the tool's verified `point_angle`) led 1 mm
out of the face, minus protected finished material, along setup -Z through the
spindle axis. It removes only the centre the selected tool cuts: the sizes and
point must be that tool's own accepted Table 6 D, C, angle, body and
`point_angle`, on a tool record that is confirmed, by the same check as the
[`blind_depth`](rules-operations.md#blind_depth-tip-endpoints) centre row. It then
measures the whole combined drill and countersink (point, pilot, countersink
opening on to the body diameter, body up to the holder's projection) and the
holder. An unknown or unaccepted tool fact or point angle, an unconfirmed tool
record, sizes the selected tool does not cut, a centre
not wholly inside the stock, a mouth with stock over it within the 1 mm lead
(not on the exposed surface of the stock the op meets after this setup's
earlier cuts, where the quill is touched), or a feed off setup -Z or the
spindle axis is a reason, not a removal. Accessibility, reach and later stock
states then see the cut centre, and a later setup's hold `centre_hole` seats its
dead centre in that countersink instead of cutting a seat from
`centre_hole_dia_mm`.

### Parting face

A lathe `part_off` onto a process `end_face` parts that disc off with the
turning model's revolved removal (see [Approach models](#approach-models)): it
sweeps from `to_dia`/2, the axis when omitted, to the stock OD from `to_z` to the
stock end the disc's outward normal (`-axis`) faces. The kept piece is the side
the end face's `axis` points into; the remainder, chuck side included, leaves
the stock, so a later setup receives only the parted piece (with a nonzero
`to_dia`, the core inside it stays, as for any part-off). The part-off separates
stock only: a disc that cuts into the finished part (parted short) is a kernel
reason naming the finished volume it would take, never a cut trimmed round the
part. Like every process
op it earns no coverage and no finishing credit. The host first checks the plane
(`parting_face`, one row per such part-off): mapped into the setup frame, the
end face's `axis` must lie along setup Z and point to +Z (the exposed end, the
part the blade separates from the bar), and its `at` must lie on setup Z `to_z`
within 1e-6 mm. A contradiction is an `error` and an unknown machine kind
(not known to be a lathe), frame, `at`, `axis`, `to_z` or manifest units is
`?`. Either is the op's kernel `process_cut` reason, so the kernel cuts nothing
and the stock after it, and every later setup's stock, is unknown with that
reason. A `pass` logs the parted plane. A part-off that names a finished drawing
face gets no `parting_face` row and keeps the ordinary finished-face checks.
`cut_to_fit` does not prepare an end face: it keeps the chuck side and drops
the free end, as in pivot-shaft S3, the opposite of a part-off. A part-off
leaves one piece, so a
[`keep`](#keep-piece) after it has only that piece to keep.

### Tooling holes

A `tooling_hole`'s transient claim is its reversed wall at the band's largest
diameter, over its `depth` or, through, the stock's extent along its axis. Its
`drill` or `ream` op removes the selected tool's own accepted diameter (a drill
also its accepted `point_angle`) from 1 mm above the mouth along the hole axis
(a `spot` only its pointed tip, down to its own `depth_mm`, through hole or not),
which must be setup -Z: a blind hole to the op's full-diameter `depth_mm` (the
feature's `depth` bounds it, as in
[`blind_depth`](rules-operations.md#blind_depth-tip-endpoints)), a through hole
to the setup's `stock_state.local_thickness.<id>` plus the op's `exit_mm`, a
drill's point cone below either, minus protected finished material; through
the stock, a reamer's accepted `lead` runs on below its full diameter for the tool
and holder checks (in a blind hole it is not drawn, since a flat full-radius end
would hit the stock left below `depth_mm`; `blind_depth` bounds depth plus lead). A
through plan that stops short of the far side of the stock near the hole's axis
is not a through hole: its cut stays unknown. A blind hole
must lie wholly inside the stock. Either way the mouth may have no stock over it
within the lead, and the 0.5 mm ring just outside the tool, from the mouth to
0.5 mm below it, must be whole stock (a mouth floating above the surface, or a
surface cut lower than `at`, leaves air there). An unknown tool diameter, point angle or reamer lead,
an unknown op `depth_mm` in a blind hole, or an unknown `exit_mm` or
`local_thickness` through the stock, is a refused input and leaves the cut unknown. The
op then measures the plain axial tool and holder like any drill or reamer.

Every setup's facts carry `tooling_holes`, each hole's state on the stock entering
that setup, but only when the plan declares one. The probe runs in the setup
frame over the hole's span: `undrilled` while stock fills its core (half its
smallest radius) in the first 1 mm below the mouth (a blind hole's ops may stop
short of `depth`), `gone` once no stock stands within 0.5 mm of its largest wall,
`present` when its core is clear and that ring is whole stock, else `partial`; an
unplaceable hole is unknown with a reason. A saw cut or any other waste cut that
takes the hole's material takes the hole: a later setup sees it `gone`. The
[`tooling_hole`](rules-setup.md#tooling_hole) rule reads these states. A locating
pin in the hole is also checked by the geometric locator proof below
(`thin_wall_under_clamp`) when its clamp is a `restraint = "locate"` clamp: the
drawn pin against the bore the kernel cut.


## Approach models

### Manual threading

`hand_tap` and `die_thread` use the hand material-cutting approach, not the
powered axial `tap` model or the lathe turning model. Their real tap/die and
manual holder identities are checked by
[`tool_resolves`](rules-tools.md#manual-tapping); their preparation follows
[`op_chain`](rules-operations.md#op_chain).

The native job carries an explicit manual-thread geometry debt. The engine
returns unresolved operation geometry and stops stock derivation after the
manual cut because helical thread removal is unmodelled. It does not
subtract a nominal major-diameter cylinder, turn a prior drill's void into
proof of finished threads, or derive a powered cutter/holder clearance.
Accepted earlier drilling and other independent preparation facts remain
distinct from that missing removal proof.

A [manual-thread-only setup](rules-coordinates.md#manual-thread-only-applicability)
can have no DRO zero or coordinate table to check. That applicability decision
does not resolve the native thread cut or waive physical holding, preparation
or downstream stock debt.

There is no RPM recommendation, spindle/toolpost assembly or axial
tool-setting requirement for either hand action. A known nonzero authored
RPM is instead a `tool_resolves` error. The manual tap's relative depth and
flute-length check does not establish native helical geometry, absolute
machine Z or a physical tapping result. See the
[manual-threading input contract](plan.md#manual-threading) and
[removable-joint boundary](#removable-threaded-assembly).

### Axial milling

Directional claims and prescribed cutter and holder poses approach along
−setup Z. The same model applies to spindle-axis lathe actions
(`spot`, `drill`, `ream`, `tap`, `center`, `center_drill`).

### Turning

On a resolved `lathe`, every other cutting action uses the turning model. The
spindle is setup Z through x = y = 0 and the work revolves, so the tool is drawn
as a section in the XZ half-plane at centre height and revolved 360° about Z.
The section is the insert (nose radius `nose_radius`,
major edge at `entering_angle_deg`, minor edge closing `insert_angle_deg`, both
`edge_len` long, feed direction from `hand`: right → −Z, left → +Z), the head
(hull of the insert to `head_len`), the radial shank (`shank_width`, back face
`functional_width` from the nose centre, out to the tool projection) and the
toolpost body (holder `body_depth` radially, `body_width` along Z). A tool
whose kind is `parting_blade` or `grooving_blade` is a blade instead: two
`nose_radius` corners on a square front edge `blade_width` wide (inventory
`blade_width_mm`/`blade_width_in`; job op `corners = 2`, `blade_width_mm`),
entering angle 90°, sides running straight back to `head_len`; an unmeasured
`blade_width` leaves the row `unknown`. A tool set out of its holder by less
than its `head_len` (projection shorter than the head) leaves the holder unposed:
every turning rule on the op is `unknown` naming the setting ("set projection_mm
at least head_len_mm"), never a crash or an "unmeasured" head. That
invalid-setting conclusion is drawn only from trusted `projection` and
`head_len` facts: an `assumed`/`illustrative`/omitted-status projection or
head is unmeasured debt naming that fact, never compared and never a pass;
unknown tool or nose extents beside trusted ones still leave the op
`unknown`; and unrelated setup debt (parallel length/width, the DRO grid,
optional reach facts) is not consumed by, and not attached to, this
conclusion.

#### Turning claims and prescribed poses

Claimed faces must be external surfaces of revolution about setup Z. Other
faces are claim errors, and internal bore claims stay `unknown`.
Samples on the claimed meridians include a dome's pole. For an op with `to_z`,
samples move onto the plane it leaves. They are checked against the profile
after that op: held stock minus the setup's turning removals through this op,
plus modeled fixture obstacles, including the rotating
envelopes of placed chuck jaws. For a stopping cut, only the tool's part-material
hit test uses known before-stock; its original profile still controls pose sections,
radial reach, rest placement and holders. Positive part observations inside
the op's derived-but-unaccepted candidate removal remain uncertain; observations
on protected or finished material outside that volume retain their numeric
certain minimum. A trailing (`turned`-side) follow-rest pose depends on the
uncredited removal and remains uncertain; independently posed `uncut`-side rests,
chuck and other fixtures retain certainty. Holder minima are unchanged. Unknown
upstream stock retains the blanket tool-minimum cap. Each pose is chosen on that
original profile's
meridian section: an insert's nose is tangent at the sample; a blade's front
edge lies on a floor sample anywhere along it that keeps the blade clear, so
it sits inside its groove and floor spans narrower than the blade are swept by
that plunge, and a wall sample is cut by the nearest corner. Where that nose or
blade meets the profile at an exposed sample, it moves to the nearest clear
pose within twice the corner radius. At a concave corner the pose is tangent
to both segments, offset from the wall by the nose radius. A corner sharper
than the nose is judged by the corner-radius fact below; flank, head and holder
hits remain collisions.
Reach is the material radius within the nose's or blade's axial extent; corners are concave toroid or
sphere profile radii (a sharp shoulder is 0) compared with the nose radius.

#### Turning removal

Removal is revolved. `to_z` faces a band from the innermost claimed radius to
the stock OD. A facing op, `part_off` or `cut_to_fit` with `to_dia` sweeps from
`to_dia`/2 to the stock OD and stock end; a `part_off` without `to_dia` starts
at the axis. It never leaves a core for a bore the finished part receives
later. Profile ops close each claimed meridian to the OD within the declared
`z_from`/`z_to` span, then cut the finished part back out. Meridian
samples lie on the claimed face's own surface. A boundary sample from an edge
curve is moved onto that surface when it lies within the face's BRep precision,
which is its largest edge or vertex tolerance. An exporter's approximated
(spline) split edges may stray tenths of a micron off a cylinder. Snapping
them keeps every face of one analytic surface on the same radius, so the faces'
revolved regions and a later spring pass over them stay coincident instead of
leaving jagged slivers or invalid booleans. Analytic cylinder and cone meridians
are straight: they need no chord-sag compensation, so their revolved profiles
meet the nominal end-radius extensions without an artificial inward step.
Genuinely curved meridians retain conservative sag compensation. Revolved
regions are unified before the window, stock and component-protection booleans,
and exact component-owned protection still clips the sweep. A removal piece
whose mean thickness is within the claimed faces' or protected material's BRep
precision is a coincidence remnant of an earlier pass, not removal; every
surviving solid must remain valid. That in-process stock is inverse-transformed
back into model coordinates and can
feed any later setup that explicitly selects it through `stock_in`, not only
the immediately following setup. Removal checks each input solid separately:
splitting any one input piece into multiple retained pieces leaves the output
unresolved unless the supported held-split or
[named terminal part-off](#retained-part-off-outputs) proof accepts it.
Separate supplies do not authorize an unconnected assembly.

#### Turning scope and unresolved approaches

The turning model is a deterministic radial sampled necessary-condition
screen. It poses the tool only at sampled meridian points, with one final-pass
profile per op. It does not prove tool paths or roughing passes, chip flow,
insert or blade clearance below centre height, blade side clearance or
thickness, boring bars or internal features, cutting load, or chatter.
Required inputs must resolve under [fact-local numeric trust](#fact-local-numeric-trust);
missing or refused facts leave the dependent row `unknown`.

An explicit turning action (`turn`, `rough_turn`, `finish_turn`,
`profile_turn`, `form_dome`, `form_relief`, `part_off`, `cut_to_fit`) off a
resolved lathe has `unsupported` approach-dependent rows, with the reason
exactly:

`turning action has no approach model off a lathe (the turning model needs a lathe spindle on setup Z)`

The shared `profile`, `form`, `groove`, `rough_groove` and `finish_groove`
actions use milling on a resolved mill, turning on a resolved lathe, and stay
`unsupported` with an unresolved machine kind. Invalid STEP face references
remain `error` before this boundary; missing or unmapped claimed references
remain `unknown`. Raw −Z facts never establish a lathe result: kernel facts
without `approach = "turning"` leave a lathe row `unknown` (`kernel facts for
this lathe op are not turning-model facts.`) and credit no coverage.

### Rotary milling

A mill op with `approach = "rotary"` on a setup held in a `dividing_head`
turns the work about the head axis under the vertical spindle. The axis is the
placed chuck's pose z, pointing out of the jaws. The head axis must be
perpendicular to setup Z (|z·Z| ≤ 1e-6); any other head pose, or a hold that is
not a dividing head, is `unsupported` with the engine's reason. Claimed faces
must be external surfaces of revolution about the head axis (coaxial
cylinders, plus planar annuli normal to the axis); other faces are claim
errors. The optional window is a partial-face claim window: `z_from`/`z_to`
are positions along the head axis from the chuck pose origin (plan units) and
`angle_window_deg = [from, to]` is the head rotation, right-handed about the
head axis; a span of 360° or more is unbounded, and an op without a window
claims whole faces. The op samples and removes only the intersection of each
claimed face with its window; points outside the window are excluded, not
claim errors. A window containing no positive-area portion of a claimed face
makes that face a claim error, and invalid, away or unresolved geometry stays
an error or debt, never a pass. A rotary op's `claimed_indices` therefore name
faces it may cut only in part.

#### Rotary window coverage

Coverage of a rotary-claimed face is decided by the job-level
`rotary_coverage` facts, never by one op's claim. For each face with a valid
rotary portion the kernel transforms every claiming op's window portion from
its setup's head frame into model coordinates and subtracts the portions in
turn from the original model-frame face: exact B-rep face subtraction up to
the kernel's geometric tolerance, not a sample set or scalar min/max spans, so
the actual face's holes and trims count and portions from different cutters,
ops and setups add up. An op without a window contributes the whole face.
`cut` unions all rotary cutting ops; `finish` unions only finishing ops. Each
lists `complete_indices`; `gaps`, each with `index`, `ref`, the uncovered
`area_mm2` and `spans` (per contributing setup, the remaining portion's
`z_mm` bounds along that head axis, exact B-rep projection bounds, and its
`angle_deg` bounds, which may be conservative enclosing bounds and never
decide coverage); and `unknown` faces with their `reason`. See
[`coverage`](#coverage) and [`finish_coverage`](#finish_coverage).

#### Rotary poses and removal

Each sample is turned about the head axis to top dead centre and receives the
vertical-cutter pose there: the cutter end touches the presented sample
(cylinder samples include their edge vertices). At any concave floor/wall
edge, straight or curved (a round pad's or boss's perimeter included), a
sample on that edge or within one cutter radius of it is shifted away from
the wall along the wall's in-plane normal at the nearest edge point until the
cutter is tangent to the wall. A continuous floor surface exported as several
STEP faces shares one nearest concave-wall boundary across its patches: an
export seam is not a physical wall or floor end, so a point on either side of
it gets the same offset. True convex corners keep their existing convention.
This is one deterministic pose per sample, not a height-aware tangency or pose
search, and it is the rotary rule only: axial milling keeps the
incident-wall floor-edge convention under [`accessibility`](#accessibility).
Cutter and holder cylinders and the reach column are then turned back by the
sample's angle. Cutter and holder obstacles exclude only the sampled face's
thin inward shell. The flute meets the stock its setup's one op-order pass
accepts after this op, like any milling flute (see
[In-process stock](#in-process-stock)): a rotary removal that cannot be
derived stops that pass. Its own flute meets its known before-op stock, but
part observations inside its own candidate removal remain uncertain. Independent
observations outside that volume and placed fixture hits retain a numeric certain
minimum. Later flutes keep only finished-material obstacles, with tool certainty
unknown.
The holder obstacles retain
setup-entry stock; reach, holder-wall and shank screens use the stock the op
meets (see [`reach`](#reach)).
Chuck jaws and body turn with the work; the head body, tailstock and clamps
stay put and are checked at the presented pose.

Own-removal combines a radial sweep of each claimed coaxial cylinder out to
the stock's outer radius (extended at the cylinder's radius to the axial
window ends) with the actual vertical cutter columns at concave wall-offset
poses on those cylinders. Each column starts at its presented cutter tip,
extends to the stock's outer top and is rotated back into the work's frame.
These wall-tangent columns account for material a vertical cutter clears that
a radial sweep alone leaves beside a concave wall. Each volume is clipped to
the op's axial/angular window, then cut against the finished solid; the
volumes stay independent and are cut from the stock one by one in order, never
fused. This is derivable own-removal, not merely counting intersections with
finished faces: finished bosses and pads remain intact, stock outside the
allowance stays an obstacle, and holder/fixture obstacles are not excused.
Planar annuli sweep no removal of their own. Corners: a concave edge in a plane
through the head axis is 0; other concave edges are unresolved.

The rotary model is one static pose per sample. It does not prove a swept
toolpath, helical or simultaneous rotary-plus-linear motion, rotation between
samples, chip flow, the head's torque or locking, or interference while the
head is turning. Setups that turn the head freely declare
`hold.index = { fixture = "<head>", rotation = "continuous" }` (no `positions`
or `angle_deg`); `indexing` then passes on a verified dividing head with no
landings to check, errors on any other fixture kind or when positions/angles
are also declared, and is `unknown` while the head is unverified.

### Window ends

A single-point turning op with numeric `z_from`/`z_to` is also posed where it
starts and stops: the nose's leading extreme at that Z (the DRO reading after a
+Z end-face touch) on the turned diameter of the claimed cylinder sample
nearest it, or on a claimed end face at exactly that Z (a shoulder the op faces)
where the nose first reaches it. It is checked exactly there: nothing displaces
it, so a stop past a finished shoulder, however low, hits the part. Those poses count in `tool_hits`/`holder_hits`, so an air start
into the dead centre or an overtravel into the chuck jaws is an accessibility
error. `window_poses` records each end's Z, diameter, what it meets and the
nearest placed fixture component with its clearance; at `z_from` it adds
`max_start_z_mm`, the furthest start back against the feed before the tool or
holder touches that component (stepped out by the clearance until within
0.001 mm; none when nothing is met within 250 mm). The traveler boxes a start
within 3 mm of a component with both numbers, converted to plan units on the
setup's DRO grid (clearance rounded down, the furthest start toward the planned
one). The start prints where the DRO shows it; rounded out against the feed, the
clearance loses that offset, and a printed start at or past the limit, or with
no clearance left, is a STOP box instead. Served follow rests are not set
at a window end: when their jaws, set on the work with the tool at `z_from`,
would meet a fixture component, `rest_engagement` gives the cut Z from which
they clear it. The plan's `hold.supports[].engage_at_z_mm` (millimetres, the Z
the tool passes before the jaws go on) passes when it is at or past that Z along
the feed and inside the op window (its plan-unit `z_to` scaled to mm), is an
`error` before it or after `z_to`, and is `unknown` when undeclared, when no
clear Z was computed, or when the plan units are unknown. The traveler prints it
on the DRO grid rounded along the feed (the clear side) and rechecks the printed
Z against the clear Z and `z_to`; with no such grid position it prints a STOP
box. The Z sits in the op's coordinate cell; the per-pass set-on and pass-end
release sequence prints once, full width ([plan](plan.md#reference)). Every
turning op's `tool_z_mm` is its whole tool's axial extent (insert or blade,
head, shank and toolpost body, at their true outline) over every pose it stands
at: the nose posed on the profile, each window end, a blade's both faces;
`nose_z_mm` is its nose's (a blade's both corner arcs') over the same poses,
which the rest of the outline stands rigidly about. The traveler's jaw distance
uses the tool's chuck-side extent (in plan units, rounded toward the jaws), not
only the Z its op names, in the op's jaw box and the CLEARANCE section alike;
a nose posed within the kernel's 0.001 mm hit-test inset past the op's own Z (it
stands against that face up to that far into it), and itself the tool's lowest
point, is at that Z; any other part's reach past the Z (a shank, a blade's far
face) is the tool's own.
An op fed to the imaginary-tip readings of a dome table and its rough stair
([coordinates](rules-coordinates.md#coordinates)) stands where those readings
put the nose's lowest point, not on the drawn profile (a cut-to-fit end forms
the dome elsewhere than drawn); its outline goes with it, reaching below the
lowest reading by `nose_z_mm` less `tool_z_mm` at their chuck-side ends. It is
`unknown` (the jaw distance `not computed`, never the named Z) when the tool is
not posed whole: a holder, tool dimension or claimed face the kernel cannot
pose, a claim it cannot sample, or an op the kernel stops before posing at all
(a turning op with no extent is unknown, never absent); or when the op's dome
table prints no tool readings. A
facing/parting op posed at its `to_z`
also records `faced_side`, the claimed faces' outward axial normal (+1 toward the
free end, -1 toward the chuck): the blade stands on that side of `to_z`, so a
+1 face is formed by a blade's chuck-side corner and a -1 face by its
tailstock-side corner ([coordinates](rules-coordinates.md#coordinates) blade
`to_z` ops).

### Follow and steady rests

A plan `hold.supports` rest table ([plan](plan.md#reference)) puts the rest
into the turning model when its inventory fixture declares measured solid
fields ([inventory](inventory.md)). Both are posed in the setup frame with the
spindle on setup Z.

#### Follow rest

A follow rest's jaws ride the carriage. They are posed with the tool at every
cutting sample of each served op (`ops`; omitted = every turning op), never as
a static solid. Each jaw is a box `jaw_height` radially
outward from the work diameter it rides, `jaw_width` tangentially and
`jaw_depth` axially, centred `jaw_lead_mm` from the cutting point along Z and
turned `jaw_angles_deg` about Z from the tool (0° = the tool's side, +90° = above
the rake face). With `jaw_side = "turned"` (default) the jaws trail the tool on
the diameter just turned, at the profile after the op; with `"uncut"` they lead
it on the profile before the op. The rest and tool ride together, so the tool
is not revolved against the jaws: the insert, head and shank are prisms from
centre height down to `TOOL_DROP_MM` (1000 mm) below it, and the toolpost body
spans that distance on both sides of centre height. A jaw sharing more than
0.001 mm³ with one of them is a `follow rest <name>` tool or holder obstacle;
flush contact is allowed. A jaw riding its set diameter is contact; larger
work under the jaws, or a jaw meeting a placed fixture component, is a
`fixture_interference` clash. A rest missing a measured jaw dimension, its
angles, a positive `jaw_lead_mm` or a valid `jaw_side` is not drawn: the ops it
serves stay `unknown` with the missing fields named, and it is a scene and
interference debt. An op the rest does not serve sees it parked off the work.

#### Steady rest

A steady rest is a static ring at `at_z_mm`, `body_length` long, from the entry
stock's largest radius under it, where its jaws ride, out to `body_dia`/2. It
obstructs the tool and holder only for served ops and is drawn and
interference-checked like any fixture component (role `rest`).
Missing `body_dia`/`body_length`, an unresolved `at_z_mm`, no work under the
ring or a `body_dia` inside the work leaves it an undrawn gap naming why.

Rests are a necessary-condition screen at the sampled cutting points: no jaw
adjustment travel, jaw wear, carriage stroke or arm/bracket outside the jaws
is modelled.

## Inputs the job accepts

### Fact-local numeric trust

A numeric dimension reaches the kernel when the fact-local lookup resolves
it to a positive explicit-unit length. This lookup does not require a shop
measurement: it accepts a plain nominal number, or a `{ value, measured, verify }`
record whose own `verify` is absent or false and whose `measured`, when
present, is complete with `status = "measured"`. A fact whose own `verify` is
`true`/`"unknown"`, whose measurement record is incomplete, or whose
`measured.status` is `assumed` or `illustrative` (omitted means `assumed`) is
debt for that dimension only. An item-level `verify`,
`present` or `source` flag, a set root's or member container's flags and
`coverage` text are identity provenance for the declared-input rules; they
never withhold a numeric fact from the kernel, and nothing is inherited from
them. Shop measurement metadata (`by`, `date`, `instrument`) is not required
here: the M5 `envelope` / `travel` screens impose that stricter readiness on
the same holder gauge/grip, tool OAL and projection facts (and `headroom` on
the envelope limits) separately, so an op can be geometrically checked while
its spindle stack is still M5 measurement debt. See
[inventory](inventory.md#kernel-geometry-facts-m4). Missing
fields are listed in the job's reason text and the dependent rules are `?`;
each refused fact is also a `numbers.measurements` entry on those findings,
naming the field and the status of the record it refused (stock provenance
included), so `tools --measure` sees kernel-side debt without a kernel run.
The engine job and its cache key carry only the stable ids of the refused
fields, never status, attribution or reason text. Applicability is decided
before unrelated trust: a rule that does not apply to an op (a concave edge
with no cutter radius to check, an op with no stock loaded) is
`not_applicable` rather than debt on a fact it would never read.

### Cutting-operation inputs

- Per cutting op (noncutting actions are `not_applicable`; an unknown `do` is
  `unknown`): `radius_mm` (tool `dia` / 2), `flute_len_mm`,
  `holder_radius_mm` (holder `gauge_dia` / 2), `holder_gauge_len_mm`,
  `projection_mm`. The projection is the selected pair's entry in
  `tools.<tool>.projection_mm` / `projection_in`, keyed by the full holder
  reference the op names; when that entry exists it alone decides, so an
  `"unknown"` or debt-carrying entry keeps the op `?` and never falls through
  to another holder's number or to OAL − grip. Only an absent pair uses tool
  `oal` minus the selected holder's `grip`, each from its own accepted fact.
  This is the `tool_projection` convention shared by engagement and the M5
  screens. There is no scalar tool-wide projection. OAL stays host-side
  for `reach`, and finishing-cut decisions stay host-side for `finish_coverage`;
  neither is an engine input (the per-feature `complete_form` hole owner below
  is). Accessibility does not require OAL when the
  selected projection is known.
  [Engagement](rules-physics.md#engagement) uses that installed projection and
  the tool diameter for its L/D verdict; its `tool_oal_mm` and `holder_grip_mm`
  diagnostics read `"not used"` when an explicit pair projection is authored.
  Those unused lengths are not read or claimed as numeric facts, and their
  assumed, illustrative, status-less, incomplete or missing measurement records
  cannot change this verdict or add engagement length debt. Selected tool/holder
  verification is still required: the existing inventory identity contract treats
  a nested `verify = true` or `"unknown"` as item verification debt, even on an
  unused length. That leaves engagement `unknown` with the exact selected item's
  `.verify` debt, separately from length provenance. Only the OAL-minus-grip fallback
  consumes those two lengths and reports their numeric values or `"unknown"`,
  with exact selected-fact debt when either is refused. A complete fact-local
  `status = "measured"` record qualifies a consumed length; a bare explicit-unit
  nominal retains engagement's existing nominal allowance. Unrelated holder
  facts and unselected set members are not engagement measurement debt.
  These diagnostic labels do not change installed projection, native admission
  or geometry cache identity.
- Per spot or drill op on a hole feature: `point_angle_deg`, the selected
  tool's included `point_angle`, always sent. A plain nominal or accepted
  fact passes its number; a missing, `"unknown"` or debt-carrying angle is
  sent as `unknown`, never omitted or defaulted.
- Per hole op on a hole feature: `complete_form` inside `hole`, true only for
  the feature's last drill, ream, bore or counterbore in setup then op order
  (a thread's last drill), false for every other hole op (pilots, a
  counterbore's drill, spots, taps). It is an engine input and keys the cache;
  the public plan schema is unchanged.

### Setup and fixture inputs

Cutter inputs use millimetres. Frames and holding fields enter the job as follows.

- Per setup: the numeric frame from the manifest (`origin` converted from
  inches when `units = "in"`; an unknown frame keeps every op row `unknown`
  with `numeric setup frame is unknown`), and for a `kind = "vise"` fixture
  the hold geometry listed under [plan hold](plan.md#hold): `fixed_jaw`,
  `jaws_along`, `jaw_above_parallels_mm`, vise `jaw_height`,
  `jaw_width`, `jaw_depth` and parallels `height`. `grip_mm`, `opening` and
  protective `method` stay host-side. Two optional authored pose fields
  pass through when numeric and are otherwise
  absent, never defaulted: `jaw_center_along_mm` (jaw centre along
  `jaws_along`, setup-frame coordinate) and `parallels_centres_mm` (exactly
  two `[x, y]` setup-frame centres); the parallels `length` (along the jaws)
  and `width` (along the clamp axis) also pass when their facts are accepted.
  A vise may also stand its parallels on risers: `hold.riser` (or a
  `blocks_123` `supports` item) with its accepted `length`/`width`/`height`,
  `riser_up`, `riser_along` and `riser_centres_mm`.
- Per setup, other holding kinds (every pose is a unit-x/unit-z right-handed
  `{origin_mm, x, z}` in the setup frame; a non-orthogonal or non-unit pose
  is not accepted):
  - `chuck_3jaw` / `chuck_4jaw`: the chuck's accepted `body_dia`,
    `body_length`, `bore_dia`, `jaw_width`, `jaw_height`, `jaw_depth`, the
    plan `pose` (origin at the jaw-face centre, +z toward the work),
    `jaw_clock_deg` (jaw 1 from pose x) and `grip_mm`. The jaws close on the
    entry stock inside the grip zone; a scroll (3-jaw) chuck whose contact
    radii differ is a debt.
  - `dividing_head`: the same chuck inputs from the item `hold.chuck`
    names, plus the head's own authored `solids`, hung behind the chuck body.
  - A `dead_centre` `support` (chuck or head): its `dia`, `length` and
    `point_angle`, the tailstock `quill_dia` (the machine's, or the dividing
    head's own `tailstock`), the plan's `support_tip_mm` and
    `quill_extension_mm`.
  - Any kind whose inventory item authors `solids` (angle plate, custom
    fixture, clamping-kit member): each `box` (`at_mm` min corner,
    `size_mm`) or `cylinder` (`at_mm`, unit `axis`, `dia_mm`, `length_mm`)
    in the item frame, placed by `hold.pose`; `clamps = [{ref, pose}]` place
    clamp members the same way. A `void = true` primitive is cut from the
    same list's other primitives (or those named in its `cuts`), never drawn.
    A primitive with its own `verify = true` or an unmeasured dimension is not
    drawn and becomes a debt; an unresolved void withholds what it cuts.
  - Any other kind (collet, a support without a `dead_centre` model) carries
    `Fixture solids are not declared for this holding kind.` or, for an
    undrawn support beside drawn solids, a gap: clear samples stay `unknown`
    with `undrawn fixture components (...)`.
  Every drawn solid is an accessibility, reach-holder and holder obstacle.

The tool axis is the setup frame's +Z. The engine transforms the part into the
declared setup frame. That frame is an authored placement, not a measured setup.

## In-process stock

### Stock routes and operation order

Each setup's checks and image use the material explicitly selected by
[`stock_in`](plan.md#stock-lineage). `"stock"` selects a single supply;
`"stock.<id>"` selects a built-up component; an earlier setup id selects its
single output, even when it is not the immediately previous setup.
`"stock_out.<name>"` selects one named retained part-off piece. A named split's
producer id is not a combined output.

Every array requires a tagged `joint` and exactly two material-disjoint input
branches. One may be an existing assembly when the other contains one single
physical component, so body+cone followed by assembly+crank is supported. Two
existing assemblies cannot be joined. There is no unconditional Boolean-union
path. Unknown or forward authored references are bad input (exit 3), including
authored `"unknown"` as a source. Omitted `stock_in` remains named stock debt,
never an inferred linear route. An assembly reference applies no implicit
transform; a named output's explicit pose registers it in model coordinates.

Setup outputs and named outputs are single-consumption references. Raw supply
declarations may seed alternative routes, but overlapping ancestry cannot be
recombined. Shared roots are accepted only for different children of the same
partition, with distinct identities and a native split proof. Parent plus
descendant, a repeated child, unproved sibling partition geometry or actual
material overlap cannot produce joined stock. No second independent stock
component is manufactured for a derived child. The canonical host identity
resolver is [`material_routes.py`](../src/prechips/material_routes.py);
declared identities do not replace native containment or non-overlap proof.

Each setup output subtracts only that setup's derivable claimed removals from
its selected input. Current-setup removals do not change current holding facts,
image or accessibility holder obstacles; the reach, holder-wall, shank and
clearance facts of [`reach`](#reach) do see them. A milling or hole flute meets the
stock its setup's earlier ops leave: before any op is measured, one pass in op
order derives each op's before-op stock and the stock it accepts after that
op's cut, so a flute never meets material an earlier derived cut removed and is
never credited with a later cut. A flute meets that accepted after-op stock,
not a separate replay of its cut: the current op's own derivable allowance
above the sampled finished face within its claimed clearing footprint (a hole
op's own cutter volume) is being cut, not an obstacle. A milling op claiming a
face away from the approach is credited no removal and meets its before-op
stock. If an earlier cut cannot be derived (unresolved claims or `to_z`, an
underivable leave or clearing box, a split or emptied stock piece, a failed
boolean), that op keeps its known before-op stock and its flute meets all of
it, never credited with the clearance that failed. A positive part observation
inside the op's own derived-but-unaccepted candidate removal is uncertain, not
a certain collision with stock that the cut might remove. Protected or finished
material outside that candidate remains a certain observation. The full hit count
may be `unknown` while `min_hits.tool` retains those independent hits; any positive
certain minimum still makes `accessibility` an `error`, not an unknown verdict.
Finished-face approach/orientation errors and independently placed fixture hits
remain certain; rejected own removal cannot resolve either.
A zero observed tool hit on that known before-stock remains a valid numeric
zero: removal can only reduce that stock. Holder counts and minima are unchanged.
Every later op's flute meets only finished material, less its independently
accepted own hole cut when its claims, tool axis, radius and depth resolve
without upstream stock. No unknown earlier removal or later cut is credited.
Both the full tool-hit count and `min_hits.tool` stay `unknown` on unknown
stock, naming the stopping op; positive observed counts are uncertain
diagnostics, never numeric certain tool minima. Trusted-stock tool hits,
genuine holder minima and finished-solid corner radii retain their certainty.
Final profile-wall overstock and complete-form cap debts are judged once on
the setup's end stock and never change an earlier op's before-op stock.
Turning keeps its original turned-profile model for poses, reach, rests and
holders; only its stopping tool's part-material test uses known before-stock.
Finished face indices
stay bound to the original STEP even when booleans change the stock's face
order.

### Named-solid material protection

For a multi-solid finished model, the source face map identifies each
feature's named-solid owner without using imported solid indices. A feature
whose faces span solids, or whose faces are unresolved, has no unique owner.
Such a feature may describe a multi-solid inspection. A known mixed-solid
retained selector or thread interface is bad input; unknown face identities
withhold its ownership proof.

Before a raw bar has a proved registration to its finished solids, its
finished-material protection is unknown. The kernel may derive nominal
removal or independent stock facts, but cannot pass a finished-material safety
guard by treating the protected shape as empty. It reports
`finished_material_reason` when that registration/ownership proof is absent.

After a named output passes the partition and whole-solid containment proof,
that child's carried finished solid becomes its protected material. Subsequent
removal, rough leave, future-hole reservations and checkpoint guards use the
owned material, not every other finished solid in the nominal compound.
Original face indices remain available for source identity; they do not grant
the child ownership of another solid's faces. Unknown mapping or pose remains
debt, including for `keep`'s decision that a discarded piece is genuine scrap.

### Entry-stock size and machine screens

Mill headroom's X/Y travel screen consumes
`kernel.setups.<id>.stock_bbox_mm` for component stock, an earlier setup's
output, and a joined pair. That box is the actual stock placed in the setup
frame at entry. It is neither the finished-part box nor a sum of raw supply
boxes. A missing or withheld entry box leaves travel unresolved. Equality
with a measured travel limit passes; exceeding it fails.

A machine with inventory `kind = "bench"` or `"manual"` whose non-empty
operation list contains only `fit`, `inspect`, `deburr`, `coating`, `scribe`,
`file_to_line` and saw cuts whose tool resolves to a `hand_saw` needs no DRO or
spindle screen: `zero_check`, `coordinates` and `headroom` are `not_applicable`.
Joint geometry and modeled holding still apply. Adding any other cutting or
unknown operation, or a saw with a powered or unresolved blade, reinstates the
normal machine screens.

### Supply geometry and as-is contact

The supply needs the positive dimensions and model-frame placement described
under [plan stock](plan.md#stock), or a [profiled blank](plan.md#profiled-blank)'s
own STEP: the kernel verifies its digest, imports it in model coordinates and
accepts exactly one closed, valid, positive-volume solid as the supply, and
reports each such blank's own box (`blank_bbox_mm`, keyed `stock` or
`stock.<id>`), the size the traveler prints for receiving it. As-is
face references do not define a stock volume: when supplied, they must map and
lie on that envelope. With a profiled blank among the supplies the kernel
instead measures each as-is face against the joined raw supply's boundary
(`as_is_contact`: `on_supply` within `STOCK_TOL` = 1e-3 mm, else `off_supply`;
`max_gap_mm`, its farthest sample's distance; and `supplies`, every raw supply
sharing a positive area of the face, from the exact face/solid common above
1e-6 mm², so a face spanning adjacent components counts and answers to each of
them however narrow its share, while a neighbour meeting it only along an edge
does not; a failed common leaves the contact `unknown`); a face off the supply is left uncredited by
[`blank_credit`](#blank_credit) instead of voiding the stock, including a face
meant for a bar component of a mixed built-up supply. Unknown
dimensions/placement, incompatible as-is faces, unresolved earlier claims,
or an unrepresentable removal are named stock debt. Stock-dependent geometry
for that setup is `?`. Tool hits sampled against this unknown-stock branch
cannot establish an error: their full count and `min_hits.tool` stay
`unknown`, even when an obstacle is observed. Known holder collisions and
finished-solid corner radii still establish errors (exit 2 takes precedence
over required unknowns' exit 4). No stock picture is drawn.
`stock_state` values name local received/touched surfaces; retained rails can extend beyond them, so
they are not silently treated as the stock's global bounding-box extrema.
Each built-up component has its own required id and model-frame pose and must
contain only its own piece, not the full finished STEP. Missing component
geometry remains debt for that component; another known supply cannot fill it.
Component ids are known, nonempty and unique exact identifiers, with no ASCII
character whitelist. Independently known branches remain usable while another
component's geometry is missing. When all component envelopes are known, their
full union must contain the finished STEP; otherwise all component references
carry geometry debt.
A nonempty root `as_is_faces` declaration checks the full joined supply exterior,
requiring every component envelope to be known; it can therefore withhold an
otherwise-known branch. Empty or omitted declarations add no cross-component
dependency. Removal fragmentation is checked per input solid: deleting one
assembly piece cannot mask splitting another.

### Transient joint preparation and assembly

The [joint declarations](plan.md#joint-features) supply real analytic finite
socket/spigot cylinders. The host converts model-unit lengths once to
millimetres; an authored `nominal_dia` defines the cylinder, never a midpoint
guessed from a tolerance band. Unknown numeric geometry withholds downstream
stock as debt. Malformed kinds, missing references and component ancestry
mismatches are bad input.

#### `joint_assembly` findings

`joint_assembly` emits one setup-scoped finding for each array `stock_in`.
It emits no rows when the plan has no assembly setup. `joint_assembly` and
the applicable declared-input `joint_fit` or `joint_thread` rule are always
required; leaving them out of policy cannot waive an incompatible or
unresolved joint.

| Result | Condition |
|---|---|
| `error` | The kernel job returns `status = "error"`; the row carries that failure reason. |
| `error` | Usable kernel facts contain `assembly_error`: `join refused: …`. |
| `unknown` | Kernel facts have any other non-`ok` status, such as missing FreeCAD or an unbound STEP. |
| `unknown` | Usable kernel facts contain `stock_reason` (`joined stock unknown: …`) or no joined `stock_bbox_mm` (`the kernel derived no joined stock`). |
| `pass` | A supported cylindrical or surface join derives joined stock from prepared branches and its modelled fit/contact and declared fill. A threaded joint never takes this branch. |

With usable kernel facts, the row reports `joint`, `stock_in`,
`completed_joint_features` and, when the
joint declares them, `forms`. Correct the named preparation, fit, insertion,
ownership or process fact before relying on a downstream stock route. A
passing supported join does not establish chemical cure, mechanical capacity
or physical assembly acceptance. The host mapping is in
[joint findings](../src/prechips/rules/joints.py).

#### Removable threaded assembly

[`kind = "threaded"`](plan.md#threaded-joints) declares a removable joint
between exported internal and external thread features. The
[`joint_thread` rule](rules-tools.md#joint_thread) checks supported nominal
thread facts, directed finite envelopes, declared seat facts and retained
branch ownership. Known contradictions are errors; a missing measurement
never becomes zero engagement or inferred shoulder contact.

Nominal major-diameter cylinders are not helical flanks. The current native
engine does not model helical engagement, lead/runout, the actual die/tap cut
or prepared shoulder seating. Even complete, agreeing authored facts leave
`joint_thread` unknown and withhold native joined stock. `joint_assembly`
reports an error for a known refusal or otherwise remains unknown. Downstream
checks retain the missing-stock debt rather than infer assembled material or
a clearance pass. No bonded annular fill, press-fused union or filler
substitutes for the missing threaded geometry.

This boundary does not prevent source-authored assembly, disassembly or
inspection instructions from printing. It also grants no physical joint-fit,
thread strength, retention, torque or first-article acceptance claim.

#### Preparation and component ownership


Socket preparation derives actual tool-profile removal from its component;
spigot preparation removes the exterior annulus within its declared axial
interval. A blind drill includes the cone below its cylindrical depth, and
that cone must not intrude into protected finished material. Drill/spot point
geometry needs an accepted included angle, not a fabricated flat bottom.
An accepted finite angle whose point slope underflows or point rise overflows
also leaves action-named geometry and stock debt for either drill or spot;
no substitute profile is built.
Socket spotting uses its pointed tool profile and does not complete the
full cylinder. Tapping and counterboring on transient joint features remain
named stock debt until actual thread and pilot/step geometry is supported;
they are not approximated by a full-diameter cylindrical void. This limit
does not change operations on exported features.
Unsupported or unknown cutting actions leave named stock debt.

Spigot shoulder/corner checks use the accumulated branch after all preceding
turning operations, including a prior facing cut, not the original blank.
Turning removal is limited to material still present at that operation; a
repeat finishing pass with no remaining removal does not invalidate known stock.

Rough allowances remain real material; a preparation is complete only after an
applicable valid size-setting finishing cut and target-geometry verification.
Completion follows the selected stock route, not chronological proximity,
and is invalidated by subsequent damaging cuts. Noncutting operations such as
inspection, fitting and deburring do not cut, damage or complete joint geometry.
Assembly rechecks actual received target geometry.

For cylindrical preparation on component blanks, finished-material protection
is component-owned before joining. The spigot's
share is the final solid inside its full cylinder; the socket's share excludes
that spigot-owned region. Neither share holds the corner a later joint
[forms](plan.md#assembly-joints). That corner is the finished solid less the same
solid with the formed feature's faces removed and their neighbours extended
(defeaturing). It is withheld only when the feature is known, mapped and its band
starts at 0, the sharp solid adds no material, and every sampled point of the
corner lies within the band's MAX of the feature's faces. An earlier join on either
branch withholds it from its backstop too. A strap faced or reamed before the press
therefore takes the R0.2 root's ring like any other stock and arrives with a plain
face, and the join judges the real lost corner as below. A raw boss may overlap the body's final coordinates:
its sacrificial turning annulus is not yet body material. Conversely, socket
removal into socket-owned finished material outside derived finite engagement
is forbidden. This protection applies to every cut on those branches, not
only operations naming a transient feature. Overlapping spigot ownership or
invalid surface ownership is localized to the involved components/joint;
unrelated known component branches remain usable. Ordinary
`stock_removal_bounds` cannot grant permission to remove protected finished material.

#### Cylindrical engagement and joining process

For a cylindrical joint the kernel verifies every extreme of the declared
diametral clearance/interference bands, collinearity, finite engagement and
branch-specific completed preparation. Incompatible known bands are certain
errors, not unknown stock. Fill is derived only from engagement and the
declared joining process, never an arbitrary authored allowance. Actual branch
overlap is forbidden except for a press-fit interference annulus. A
straight-axis insertion sweep must be free of socket-stock obstruction;
a captive or shouldered fit does not pass merely because its final pose fits.

A `cylinder_bore` with `thru = true` has a finite declared axial span and must
be open at both ends on the actual received branch. It can receive a sleeve
through a cross-bore; a blocked far end is not accepted merely because the
authored declaration says through. Spigot verification checks the cylindrical
exterior interface and required component-owned finished material. A sleeve's
intentional finished bore need not contain fabricated solid core, and clearance
fill occupies only the mating annulus. It does not refill that bore.

Sequential joins preserve all material ancestry and branch-specific preparation.
The next unused interface is rechecked on the actual received assembly; prior
socket/spigot identities are consumed and cannot be joined again. Completed
consumed preparation remains historical provenance, not permission to cut
through the assembled interface. Shared ancestry still refuses the join, and
upstream unknown stock cannot become known by adding another component.

A joint `compound` (required on a `slip` clearance fit, optional on a `press`
interference fit, refused on `silver_braze`) names its `product`, declares
`surface_prep` instructions and a positive `cure_time_min`, the wait before
disturbing the joint or machining it. `joint_fit` reports the fit band with the
compound's `product`, `cure_time_min` and `surface_prep` whenever one is declared,
on either fit. Explicit unknown band, product, prep or cure time remains debt and
withholds union/render; absent or malformed required compound facts are bad input.
These are authored process facts, not a chemical cure simulation or manufacturer
certification, and the compound adds no geometry: a bonded press fit joins the
same stock as a bare one. For a press fit, the setup sheet prints "press in with
the compound on the interface", followed by "do not disturb until cured".
A known geometric refusal (missing preparation, blocked insertion, overlap or
lost required material) remains an error even when cure or surface prep is
unknown. Only a geometrically derivable join becomes process debt; it still
produces no stock output. An unused or unrelated spigot declaration cannot
exclude required material from the assembly backstop.

#### Surface joints and final-material backstop

Surface joints use finite analytic rectangle `interfaces`, not finished STEP
face references. Both authored sizes are full independent side lengths. Each
must lie inside the final solid, with essentially full rectangle contact from
both pieces and no bulk overlap. Plane-side ownership
protects each component's final share during preparation: the first `stock_in`
reference owns the negative-normal side, the second the positive-normal side.
Several contact patches describe one two-input join, not permission to consume
more component inputs at that step. Weld or silver-braze process text alone cannot connect separated pieces,
and surface joining adds no filler solid.

At assembly a final-material backstop checks the portion of finished geometry
inside the consumed raw envelopes against the actual branch outputs plus
authorized derived fill. A failed fit, lost material, missing preparation or
blocked insertion withholds stock output. A later finished bore must really
remove the joined material/fill; earlier socket cutting earns no final bore
coverage. Original exported geometry and its hash remain the provenance anchor.
The spigot's final material outside its declared cylinder is not protected as
spigot-owned preparation stock; if a cut loses material that neither received
branch nor authorized fill supplies, the assembly backstop refuses the join.
This late check is not permission to discard a shoulder or other finished
material.

#### Joint-formed corners

The backstop does not count corner material that a joint's `forms` feature
admits as lost. The kernel checks each formed feature on the actual joined
branches:

- Every one of its STEP faces bounds lost finished material. If a received
  branch already carries a face, or never meets it, the join does not form it.
- Each lost piece touching those faces is bounded only by formed faces and the
  untrimmed surfaces of their neighbouring finished faces, so the joined corner is
  the sharp corner where those neighbours meet. Features that share one lost piece
  are judged together.
- The socket's mouth breaks are included; the spigot runs through the corner with no
  edge there. A cylindrical joint's socket mouths carry its declared `edge_break`,
  cut into the received socket before the join. The mouths are the `at` end, and the
  far end too when `thru`. A radius or chamfer mouth leaves a groove round the
  spigot that no neighbour surface bounds, so the join is refused (`the socket's
  <kind> <size> mouth break leaves a groove, not a fillet or a sharp corner`). A break
  is placed only on a flat socket face square to the axis: the material it leaves in
  its annulus must be present inside the mouth plane, and nothing may lie outside it.
  A mouth the received socket already shows broken therefore places. The break is
  cut only after the join's certain checks (fit, overlap, insertion, fill process).
  A mouth that cannot be placed, such as an authored end in air (a thru socket
  authored past its material) or a saddle on a curved face, makes the joined corner
  undecided. While it stands, a carried face, a corner that is not sharp (a groove at
  the other, placed mouth included) and a single component are debt. Loss beyond the
  band's MAX and a band not starting at 0 stay certain refusals. An undeclared or
  unknown break is debt.
- No lost point, sampled faces and vertices included, lies farther than the band's
  MAX from the faces of the formed features its piece touches. Material missing
  beyond the band stays lost. Another formed feature's face that the piece never
  meets, and that face's neighbours, neither shorten that distance nor bound the
  piece.
- The corner shares area with both received branches. A corner that one branch
  alone bounds belongs to a single component, which the join did not form.
- A sharp corner is radius 0, so the band's lower end must be 0. A `[0.1, 0.2]`
  band refuses it.

Each of these failures refuses the join with its message. An unknown band, units
or mouth break makes a formed feature debt. So does a known feature whose lost
material is shared with an undecided one, transitively and whatever the order of
`forms`. Its other pieces are still held to loss beyond its MAX and to a band not
starting at 0. Otherwise all its lost pieces are excused with it, and so is any lost
piece touching them. Lost material left at an undecided
feature's faces, or at a deferred feature's lost pieces, then withholds the joined
stock instead of refusing it. Lost material elsewhere is still a certain refusal. Two cases withhold the stock for any
leftover loss: a feature whose faces are unknown, since nothing says where its corner
is, and a lost piece that touches an undecided corner, which is excused as a whole
because no known band bounds it. With no lost material at all, the join assembles
and the undecided feature's row stays unknown. The joined setup
reports `forms.<feature>` with `status = "formed"`, `indices`, `corner = "sharp"`,
`radius_mm`, `admitted_mm3` and `reach_mm` (the farthest lost point from the
faces). Later joins keep the admitted material admitted. A joint without `forms`
runs the backstop unchanged.

### Derivable milling removal

For a derivable face footprint, removal is clipped to the authored `to_z`
endpoint and to material outside the finished solid.
Facing uses the planar face's outer-wire sweep to clear raw caps over hole
mouths while preserving finished islands. Generic bounded clearing preserves
known, unclaimed planned-hole columns for their own future hole operations;
this is not a blanket reservation of every concave cylindrical face.
Each reserved column has the bore's radius and spans the matched bore's
exact axial extent plus any adjacent cap, with numerical lift at either end,
not the full entry-stock height. A cap is a concave cone or sphere that shares
an edge with the bore, lies coaxial on its axis line, and whose largest
radial reach is no more than the bore radius; its exact axial span (including
a contained cone apex or sphere pole) extends the column. A wider back
countersink is therefore not reserved, and a blind hole's column stops at its
actual cap rather than running on as an unbounded rod; pins or rods outside
that span are not reserved hole stock.
In a built-up plan a column is reserved only inside the ownership regions of the
components on the op's branch, the regions that divide finished material between
them (a spigot's full joint cylinder, its socket's space outside that cylinder, a
surface joint's side): before joining, a bore in another component's region is
that component's future hole, so the branch's cutters remove the raw stock over it
and none of it stands as an island or obstacle. A one-piece part, a stock root no
joint divides and an assembly holding every owner keep each column whole.

#### Profile corridors and chain-drilled webs

A milling profile op (`profile`, `rough_profile`, `finish_profile`) with no
`stock_removal_bounds` clears its cutter corridor beside its vertical claimed
walls and the sweep of the cutter-centre paths the traveler prints for it,
never the stock past both. The walls' level sections are chained;
the cutter centre path is each chain offset by the cutter radius r to the side
away from the finished part (side probed 0.01 mm off the wall), with arcs about
convex joins and trimmed at concave ones; the corridor is every point within r
of that path: 2r beside each wall, a 2r tube about each convex join and an r
disc at each open path end. It stands from `to_z` (else the walls' foot) to
above the setup-entry stock. A concave claim (for example an R800 edge) gets
the same corridor, not its whole circle, so an unclaimed web wider than 2r, a
clamped rail or an ear beyond it stays stock until an op that really cuts it.
The operator really drives the printed milling path, corner miters (two linear
moves past a convex corner) and run-outs included, so every point within r of
each printed milling table (its displayed `dro_xy` rows as chords, from its
displayed tip up) is credited removal too. A `chain_drill` table is not a
driven path: its rows are repositioning checkpoints at which the operator
drills one discrete cylinder each, then chisels the webs. An unbounded profile
op whose every non-empty printed path is a `chain_drill` chain (the authoritative
method is each path's own `method`) therefore removes only each actual hole
cylinder, at the full drill radius from its actual tip Z: no corridor beside
its walls, no +Z sweep of its non-vertical claims, no lineage band and no
drill-radius sweep along the chords between hole centres. The positive webs
between neighbouring holes, the stock between the holes and the claimed wall
and any rail or ear beyond them stay in stock until an op that really cuts
them, bounded or milling, in this or a later setup; the printed break-out
instruction is not credited removal. A path with an unknown, empty or missing
method never counts as a chain. In an op that prints both kinds, each chain
path keeps only its holes and each milling path keeps its sweep. An explicit
`stock_removal_bounds` on the chain op is the author's certification of the
actual drilled-and-chiselled footprint under the same bounded-box rules
below (finite numbers, setup-entry stock intersection, finished and
protected-leave material never taken): the box is then its removal, as for
any bounded op. This declaration does not demonstrate a toolpath or measured
execution. An explicit break-out/chisel phase or schema is not modeled; its
scope is tracked in [#213](https://github.com/pedropaulovc/prechips/issues/213).

#### Guided sweeps and exact trammel arcs

A `guided_sweep` table ([coordinate rules](rules-coordinates.md)) is a driven
path in the work's frame. The setup frame rides the work on its swing arm or
sled, so the locked cutter traces the printed cutter-centre arc in it. The kernel credits
and checks it exactly like any milling table (corridor beside the claimed wall,
the rows as chords, a cutter cylinder at every row). Its rows span the whole
declared sweep, so the cutter's run past each arc end is judged too: a run into
finished material (a tip wall rising at a concave end) is a rule A′ hit the
coordinates rule cannot see. The carrier's own `solids` (posed by `hold.pose`)
move with the work and are checked in the same frame. The pivot post or the
rollers fixed to the table move relative to the work, so they are never
fixture components: an arc sled's rollers are drawn render-only at the setup's
mid-sweep pose (see [Renders](#renders)), and no checkpoint, clash, contact or
clearance reads them. No removal or hit code in `freecad_job.py` knows the
method. A trammel's table is the same driven path in the carrier's frame, with
rows on the nominal arc, except that all rows lie on one exact circle. Its
checkpoint path carries `exact_arc_mm` (setup centre and radius). The run-out
and tool envelope sweep the cutter, shank and holder along the true arc through
the rows, an annular sector with round ends, rather than their chords. The
removal is exact. A sweep of only two rows takes the circle's intervening point
as its middle. A clipped piece drops the arc. The implementation origins are
[#255](https://github.com/pedropaulovc/prechips/issues/255) and
[#269](https://github.com/pedropaulovc/prechips/issues/269).

#### Printed-row guards and later holding

Rule A′ limits every printed table, row by row. A row is an accessibility error
naming that row when its cutter meets the finished
part or the op's rough leave (its guard), a fixture component, stock outside a
bounded op's box, or stock a later setup bears on. A row's scrap is what it
removes past its op's design (the corridor and claim sweeps, or a bounded op's
box; an unbounded chain op has no implicit design sweep, so all that each of
its holes removes is scrap and is screened). Retained scrap may be nicked unless a later setup (one whose stock
descends from this setup) contacts it: where the scrap still borders that
setup's entry stock and lies within 0.01 mm in front of a flat face of one of
its jaws, clamps (press, locate or support), locators, rests, parallels, risers
or fixture bodies over more than 1e-6 mm², the row is an error naming the later
setup, the contact and the component. A later setup whose frame, entry stock
or holding is unresolved, or that has undrawn components, leaves the rows
`unknown`, as does scrap meeting a curved component face, a possible jaw
extension or, with undrawn supports, the later seat; unknown never passes.
Fixtures are never stock, so a cutter that meets them stays an accessibility
hit. An unknown cutter radius, an ambiguous wall side, an unknown printed row or
a corridor or run-out OCC cannot build makes the cut underivable (named stock
debt, never a guessed removal). Non-vertical claims of a milling profile op
still sweep along +Z.

#### Final wall and hole-cap completion

Every claimed face with a horizontal normal component is checked for
remaining overstock above `to_z`,
including drafted walls whose +Z sweep is nonzero. Exact face contact catches
small retained ears; nearest-contact probes inset from the face boundary
distinguish a drafted sliver from legitimately retained neighbours. The webs
an unbounded `chain_drill` op leaves beside a claimed wall are such overstock:
the op is named stock debt (`overstock still touches claimed wall(s) … above
its to_z; its unbounded chain_drill holes certify only drilling, so the webs
between them stay stock; declare stock_removal_bounds on the op to certify
the actual break-out/chisel removal`), and every later setup whose
stock descends from it stays unresolved through the ordinary unknown
propagation above. The remedy is a later op that really clears the webs, or
a `stock_removal_bounds` box on the chain op that certifies the actual
break-out/chisel footprint; neither the stock nor the reported filing cap
changes to hide the debt. This is a per-wall contact test, not a rule that
every unbounded chain fails: a chain whose webs the same setup's later
milling clears, or whose claimed wall no web touches, is not debt.
A `complete_form` hole op's own claimed caps are then checked against the
setup's final stock with the same contact test, without the `to_z` clip (see
[accessibility](#accessibility)); a touched cap is named output-stock debt.

#### Bounded clearing and protected leave

An operation can declare numeric `stock_removal_bounds` (one setup-frame box)
to clear only outside-finished material inside that volume. The box is the
explicit cleared footprint the author declares, for example the envelope of
several roughing passes or, on a `chain_drill` op, the drilled-and-chiselled
break-out footprint; it is not capped to the claimed faces' XY bounding
box dilated by the cutter radius, and it is not a proof that a whole toolpath
exists or clears. The remaining guards all hold: the cutter radius must be
known (an unknown radius leaves the bounds `?` with a reason naming the
missing cutter radius, never a zero-radius result, and later stock stays
unresolved); the bounds are finite numbers; removal is the box's intersection
with the setup-entry stock, never finished material or a protected rough leave;
each claim must touch the box and every removed piece must border a claim on
that setup-entry stock (an earlier op clearing the bridge between a claim and
the rest of its box never strands it), and the pieces are then cut from the
current stock, so removal never restores material an earlier op cleared;
known future planned-hole columns, with their finite caps, stay stock (one
exception: a facing op, `face`/`rough_face`/`finish_face`, removes a column
whose bore opens on one of its own claimed +Z planar faces, sharing a real
native edge with it and having material outside the bore's nominal cylinder (an
exact native cut against that finite cylinder, radius never widened; a planar
blind bottom, annular or slightly tilted, lying wholly inside it is a closed cap
and never opens the bore, and an invalid cut is named stock debt), but only
above that face's cut height `max(face z + a, to_z)` without lift, the highest
such claim's for a column several share, and
only inside its box, guard window and own outer-loop sweep; the column below,
other bores, and the core outside that scope stay reserved, while the flute and
holder checks still meet them); and
the removal must not split an original input solid. Before a claimed planar wall
the protected leave is flat: wherever stock outside the box or a reserved column
stands behind the wall's plane, a skin `a` thick stays in front of the plane across
the claimed face's own width (along the spindle axis, through the box's whole
depth), over the finished face's holes and edges too. Past each end of that
width, where such stock also stands behind the plane, the op's own cutter of
radius r steps from the plane up onto the skin and leaves the cusp of that step:
before a vertical wall, at each height, what lies in front of the plane past the
end that no disc of radius r covers whose centre clears, at once, everything the
op keeps at and above that height (the stock behind the plane, the skin, the
guard's `a` rounding of the wall's own convex edge and reserved columns). Beside
that rounding the cusp reaches `sqrt((r + a)² − r²)` past the end, where the
cutter touches the plane and the rounding; above the wall, where no guard stands,
the skin's sharp outer corner alone bounds it, `sqrt(r² − (r − min(a, r))²)`.
Heights where the kept shape is not upright are taken in slabs at most 0.25 mm
deep, each keeping what that shape just above its foot leaves (the widest over
the slab, since the shadow takes in all that stands above); a slab thinner than
0.01 mm joins the one below. Each height's section is taken with a level face
wider than the shape. Both growths by r
are exact unions of the shape, the band beside each of its edges and one disc
about each edge end (a free-form section edge is fitted with arcs within 1e-4 mm
and reached that much farther, erring towards keeping stock); each is cut in one
Boolean and checked after it: a legal centre nearer the kept shape than r, a disc
overlapping it, a band whose covered and uncovered shares do not add up to it, or
a failed Boolean makes the stock unknown. No other op,
earlier or later, is credited with clearing it. A flat-bottomed cutter steps
square onto a floor's skin and leaves no cusp; a step past the end of an inclined
planar claim's skin, or a claim on a surface neither planar nor curved analytic,
makes the leave, and so the stock, unknown. A violation is not an
error verdict: it is named stock debt (the stock reason names the failed
guard), so stock-dependent results for that setup and later setups selecting
its output stay `unknown`, never clearance. Flute hits on that unknown stock
also stay uncertain; trusted-stock tool collisions, genuine holder collisions
and known finished-solid corner-radius violations remain errors. Synthetic geometry fixtures
author these preparation volumes and numeric supply allowances; their target
setup checks the derived material. Preparation tool/fixture debt stays visible,
and the fixture policy explicitly requires the target, not fabricated roughing
clearance.

The current [rocker plan](../examples/rocker-arm/plan.toml) starts with an
authored 345 × 76.2 × 19.05 mm supply. P1 through P5 prepare the declared
340 × 65 × 16 mm blank, and S1 consumes P5's output. S1 and S2 declare bounded
face and profile removals that retain rails, end ears and a 0.42 mm web.
S2 consumes S1, and S3 consumes S2. These are authored example inputs, not
physical measurements or fresh acceptance evidence. In any plan, a known
current setup remains checkable and drawable even when its output stock is
unresolved for a later setup.

### Facing footprints and later touches

The coordinate/stock-surface tracker can prove that a bounded facing op covered
a `kind = "face"` feature without authored `bounds` using the already-present
kernel's geometry-matched STEP face `bbox_mm` records. Every listed face must
resolve, and only the planes whose posed box lies at the op's `to_z` within
`LENGTH_TOLERANCE_MM` are eligible and credited. The record has no face
orientation, so a downward plane exactly at `to_z` is indistinguishable by its
box: an accepted limitation, since a facing op cuts from above. Each eligible
box, converted from mm and posed in the setup frame, must lie inside the bounds
beyond that tolerance; an edge within it is unknown. A posed box is exact only
under a signed-permutation setup turn; under another turn it over-approximates
the face, so bounds crossing it are unknown, never partial. A `contour.keep_out`
island grown by the cutter radius that meets the face leaves it partly faced.
Containment establishes the faced surface's Z for later touches; overlap or a
disjoint patch does not. Missing face identities, boxes, units, cutter radius
or setup-frame inputs remain named footprint debt. This starts no additional
kernel job and does not enlarge an unbounded cut or certify a toolpath
([coverage and touched Z](rules-coordinates.md#coordinates)).

### Saw cut-off

A straight `saw_cut` or `cut_off` uses an authored setup-axis blade-centre
`cut_plane` and the selected blade's positive explicit inventory kerf
(`bandsaw`, `hand_saw` or mill-only `slitting_saw`). Below retains the
halfspace at or below `plane - kerf/2`; above retains the halfspace at or above
`plane + kerf/2`. The native Boolean removes the kerf plus the discarded planar
slab from the current operation stock, including earlier removals in that
setup. Its retained result is available through normal `stock_in` routing.

For a slitting saw, this Boolean is ideal removal only, not the swept volume
of a finite disk. Disk OD must be explicit `dia_mm` / `dia_in`, with separate
`kerf_mm` / `kerf_in` (never inferred from thickness), and `flutes` denotes
tooth count. Neither these facts nor the optional arbor identity and selected
holder supply a finite-disk reach or assembly model.
Only straight `cut_plane` cuts receive this bounded slitting recognition.
A `slitting_saw` with `follows` stays unknown: host
`scribed_profile.reason` debt prevents known stock routing, without changing
the native kernel. Scribed-region removal cannot stand in for disk geometry.

The `saw_cut` finding reports the normalized plane, kerf, retained boundary and
before/after, kerf, offcut and removed volumes in mm/mm³. A cut into the finished
target, an empty retained piece or an off-stock/no-op blade is an error, never
clipped back to the target to fabricate a pass. Tangent contact with no target
volume removed is permitted. A known saw-station mismatch, including a
scribed bandsaw without vertical mode, or a verified kerf ≤ 0 on a straight
cut is an `error` even without FreeCAD. Any reported native `saw_error` also
takes precedence over unavailable kernel facts. Otherwise a missing or
unverified kerf, cut-plane or upstream stock remains named `?`, and missing
FreeCAD remains kernel debt.
Splitting one connected input stock solid into several retained pieces is also
an error: detached pieces are not silently routed as held stock, including tiny
retained slivers. Independently supplied components already disconnected before
the saw may remain disconnected; the check is per input solid, not the total
retained count. Target-loss and volume facts are computed before this refusal.

For nonspindle bandsaw and hand-saw operations, `accessibility`, `reach` and
`internal_corner_radius` are `not_applicable`: the axial/turning tool-cylinder
model does not model their blades. This is a model boundary, not certified
blade/fixture clearance. A `slitting_saw` is not granted that nonspindle
waiver: `saw_cut`, assembled `tool_resolves`, `accessibility`, `reach` and
`saw_teeth` stay unknown for its unmodelled physical cut. Finite disk reach,
mount/axis, arbor assembly, spindle/tool/fixture clearance and engagement/
teeth in the work are not modelled by the planar kerf cut. Known station or
removal errors still cannot become passes. Ideal stock removal may be routed
without establishing physical cutter reach or clearance.

No saw cut provides finished-face or surface-finish coverage credit. A setup
containing a raw `slitting_saw` identity, even with verification or dimension
debt, cannot take dedicated-nonspindle-saw or manual-bench waivers. Its setup
zero and clearance rows (`zero_check`, `headroom`, `envelope`, `travel`) remain
unknown where the rotating-disk model is missing, never a safety certification.
Mixed setups still assess their ordinary operations while retaining slitting
debt. DRO touch-off cannot waive this debt. Holding, selected holder/arbor and
fixture inputs remain owed.
For nonspindle saws, holding, fixture solids and fixture-interference screens
remain in effect, including on a dedicated bandsaw setup, except under an
admitted [hand-fed hold](plan.md#hand-fed-on-the-saw-table). A hand-fed cut's
`hold_fields` row instead reads the kernel's setup-entry stock box against the
policy's `min_hand_feed_mm`, at blade positions along the scribed arc within the op's
`stock_removal_bounds`; it never starts the kernel, and without that box the
minimum stays `?` ([rules-setup](rules-setup.md#hold_fields)).

### Saw to a scribed line

A saw that `follows` an earlier scribe op's line has no plane: it removes only
its declared `stock_removal_bounds` box (clipped to the current operation stock,
plan units scaled to mm) and reads no blade kerf. When the scribed feature is an
arc, the host sends its layout in the saw setup's frame (`scribed_profile`: centre,
radius in mm, and which side of the circle the saw takes) and the kernel clips the
box with a Z-axis cylinder offset by `allowance_mm`: it removes outside `R + a` when
the part lies inside the circle, inside `R - a` when it lies outside. An arc whose
layout is unknown, or an arc with an unknown allowance, removes nothing and is a
`saw_reason`. A straight scribed line keeps the box alone. The kernel does not
model break-out or chisel removal (#213).
An omitted or unknown box removes nothing: the saw's `saw_reason` reads "declare
stock_removal_bounds for <setup:op> …", the `saw_cut` finding is `?`, and the
stock after it stays unknown for later ops and setups. A box that misses the stock
is a no-op error; one that removes finished target, leaves no stock or splits one
input solid into loose pieces is an error, as for a straight cut. The retained
material between the removed stock and the finished target is reported as
`retained_to_target_mm` (the minimum distance between the two solids); below the
op's `allowance_mm` it is an error naming both. An unknown allowance on a straight
line keeps the box removal but leaves the finding `?`; an empty finished target in that setup leaves
`retained_to_target_mm` unknown. The finding reports `follows`, the declared box,
`allowance_mm`, `retained_to_target_mm` and the before/after and removed volumes;
it has no kerf or offcut volume. Every saw op's kernel facts also carry
`stock_bbox_before_mm`, the setup-frame box of the stock that op cuts after any
earlier cut ([#347](https://github.com/pedropaulovc/prechips/issues/347)).

### Saw teeth in the work

A bandsaw or hand-saw blade with too few teeth in the work straddles it: the
teeth strip and the blade grabs, and a hand-fed cut is held only by hand. Each
saw cut gets a `saw_teeth` row. A slitting saw's row remains unknown: total
tooth count (`flutes`) cannot establish engagement or teeth in the work
without finite-disk geometry. For bandsaw and hand-saw blades, the thickness
the blade crosses times the blade's coarsest pitch
(`tools.<blade>.tpi`, the low end of a variable `[coarse, fine]` range) is the
teeth in the work, and fewer than the shop policy's `saw_min_teeth_in_work` is an
error naming the coarsest pitch the cut allows (`minimum × 25.4 / thickness` TPI,
rounded up to 0.1 so the printed pitch is enough).
The comparison is plain `≥`: exactly the minimum passes.

The kernel reports the thickness the blade crosses as `cut_thickness_mm`. A cut
that `follows` a scribed line runs its blade along setup Z (a vertical bandsaw or
a bench saw), so it crosses the Z span of the stock inside its removed region. A
straight cut's blade travel within its plane is not modelled, so it crosses the
section's thinnest in-plane extent (`cut_thickness_axis`), the worst case. Both
are bounding-box extents, so they are reported only where the box is the
material: a straight cut's section at the kerf face must be one piece, with no
hole, and convex (its area within 1% of its convex hull's), and a scribed cut's
removed stock must be one uniform Z thickness (its top area times its Z span
within 1% of its volume). A hollow, open or split section (tube, angle, channel,
stepped plate) leaves the thickness unknown with that reason, never the box's
span.

An unknown or uncited pitch, an absent, uncited or flagged policy minimum, or a
thickness the kernel could not derive (no stock, a refused or unresolved cut)
leaves the row `?` with that reason, never a pass. A cut the `saw_cut` row
refuses or leaves unresolved never passes on its pitch alone; too few teeth on it
are still an error. A missing kernel leaves this row as kernel debt.
The row reports `tpi` as declared, `tpi_coarse`, `cut_thickness_mm`,
`cut_thickness_axis`, `teeth_in_work` and `saw_min_teeth_in_work`.

### Keep piece

A held split keeps every piece. A frame filed or cut free of the part remains
in the in-process stock until an op declares which piece leaves the setup.
Use `keep = "<feature>"` on that op. The host sends the setup's `keep` entries
(`{subject, feature, after}`) only when they exist, so a keep changes the
geometry cache key and its absence adds no engine input.
`after` is the last op sent to the kernel at or before the keep op in the
setup's route. A `release` or other manual op is never sent, so its keep acts
on the stock that the cut before it leaves. With no such cut it acts on the
entering stock.

After that op, the stock pass keeps the one piece that carries every face of
the feature. A piece carries a face when no more of the face than the
face-signature area tolerance (1e-6 mm² or 1e-6 of its area, whichever is
larger) lies off it. Every other piece is discarded. The before-op stock of
later ops in the setup (what their flutes, reach and shank checks meet),
`stock_out`, the next setups' entry stock (`stock_bbox_mm`, `stock_faces_mm`)
and so their `stock_state` checks see only the kept piece. Within the keep's
own setup, holder obstacles, holding and the picture keep the setup-entry
stock, as they do for every earlier cut, so a dropped offcut can still meet a
later op's holder there; key the keep to the setup's last cut, usually by
placing it on the `release`, to avoid that. A keep never
changes the held-split proof: each piece must still be held while the split
stands. The kept and discarded pieces are recorded under the setup's `keeps`,
keyed by the keep op, each with its number, volume (mm³) and bbox (setup frame,
mm). A one-piece stock keeps that piece and discards nothing.

The keep is never a guess. Each of these leaves no carrier, makes the stock
after the keep op unknown (`<op>: <reason>`), and leaves every later setup's
stock unknown. The op's own cut stays credited:

- `keep` is `"unknown"`, or names a feature the part does not have;
- the feature's faces are unresolved;
- no piece carries the whole feature;
- the feature spans two or more pieces;
- two pieces each carry it.

A keep never scraps finished material. If a discarded piece would hold more than
1e-3 mm³ of any received component's finished share (its component-owned
finished material; `stock` for a single supply), the keep is an `error` naming
the piece, component and volume, and stock after it is unknown. Scrap such as
a frame round the part holds no finished share and can be discarded.

Each reason names what to change. The `keep_piece` finding of the keep op (always
required, so its `?` blocks whatever the policy lists) logs
the result: `pass` with the kept piece and each discarded piece's volume and
bbox, `✗` when a discarded piece would scrap finished material, or `?` with the
reason. A keep that names no feature is `?` even without
the kernel. With no kernel, or with stock already unknown before the keep, the
row is `?` for that reason.
The traveler prints the keep on its op's row: "Keep the piece that carries
<feature>; discard the other piece" (the count of pieces the kernel discarded
when `keep_piece` passed, else "discard every other piece").

### Retained part-off outputs

The [plan's `outputs` contract](plan.md#retained-part-off-outputs) names both
pieces that continue after one terminal `part_off`. It is not `keep`, which
discards all but one selected piece, and not permission to fork the same
unpartitioned material into two purchases.

A named lathe part-off removes a finite blade-width kerf, unlike the ordinary
part-off model's free-end sweep. It requires known `to_z`, an accepted positive
`blade_width_mm` or `blade_width_in` on the selected two-cornered parting blade,
and claimed axial faces that all identify the same outward side. The kerf
runs from `to_z` one blade width in that side's direction, radially through
the spindle axis. Omitted `to_dia` means the axis as for ordinary parting;
unknown `to_dia` or a residual core cannot establish a split. If `z_from` or
`z_to` is authored, both must be numeric and their span must contain the full
blade-width kerf. Missing or ambiguous cut facts, a no-op/invalid kerf,
protected-material loss or a failed Boolean leaves the outputs unresolved.
These are consumed tool and operation facts, not new `outputs` fields.

The native proof accepts only one incoming solid and exactly two valid,
positive-volume retained solids after a real nonzero cut. The result may add
no material outside the input, and the two original pieces must not overlap.
Nested named partitions are unsupported.

The existing [held-split proof](#held-splits) is independent and still
required: both pieces need press-clamp contact with a load path to an
anchored support. A missing modelled witness refuses the cut/output before
the carrier proof. Naming an output invents neither a catch nor support for a
loose offcut, even when the kerf and poses are numeric.

For each output, the carried exported feature must have one source-owned
named finished solid. The engine applies the output's forward
[`PlanFrame` registration](plan.md#retained-part-off-outputs) to each candidate
piece and requires exactly one candidate to contain the whole finished solid,
using the kernel's 1e-3 mm³ stock tolerance. It does not select by a feature
point, one face or a nearest bounding box. The two outputs must select
different original physical pieces and different named finished solids, and
their owners must account for every named finished solid. The posed outputs'
actual material must also remain non-overlapping.

Only after the complete proof succeeds are both `stock_out.<name>` references
registered. Setup facts record each output's `carries`, `finished_solid`,
`partition` operation, `volume_mm3` and model-frame `bbox_mm`. Unknown cut
geometry, source ownership or pose, no unique whole-solid carrier, a duplicate
selection, unaccounted finished material, overlap or a failed Boolean leaves
the outputs with a `reason` and downstream stock unresolved. Declared route
identities remain present so an unresolved proof cannot erase their material
history or authorize reuse.

At a later join, the native engine independently checks that shared-root
branches are distinct children of one proved partition and that their actual
material does not overlap. A source declaration or supported named-solid
Boolean proof is not certification of a physical cut, holding arrangement or
threaded join.

### Jaw placement

The engine seats the part at its lowest Z in the frame and models two jaw
boxes. The jaw zone is `[seat, seat + jaw_above_parallels_mm]`, limited along
`jaws_along` to the declared jaw span when `jaw_center_along_mm` is given;
the inner jaw planes sit at the extremes of the part material inside that
zone along the clamp axis; each box extends `jaw_depth` outward from its
plane and `jaw_height` down from the jaw top. `jaws_along = "x"` takes
`fixed_jaw` `rear` / `back` (+Y) or `front` (−Y); `jaws_along = "y"` takes
`right` (+X) or `left` (−X); anything else is a named debt. Zero material in
the zone (`jaw_above_parallels_mm = 0`, or a declared centre with no part
between the jaws) leaves the jaws unplaced with a reason.

A swivelled vise (`jaws_angle_deg`) is placed in its jaw frame: the stock (and its
faces) turned back by the swivel about setup Z, where the rules above apply unchanged,
then the jaws, jaw bar, jaw buttons, parallels and risers are turned forward into the
setup frame. A tool is a vertical cylinder, unchanged by a turn about Z, so every
clearance is judged on the turned solids; they carry no exact box, so each hit falls to
the solid test, and a possible-jaw region keeps its setup-frame bounding box (a superset)
for the box tests while the picture draws the turned strip. The jaw-opening check of
[`fixture_interference`](#fixture_interference) reads each accessory's jaw-frame box;
`wall_map` lines are jaw-frame lines and carry the angle. The setup facts add
`jaws_angle_deg` and `jaw_frame_stock_bbox_mm`. A stated-unknown angle leaves the jaws
unplaced; the angle is part of the job's hold, so of its cache key.

Along the jaws the engine distinguishes an exact pose from a conservative
envelope. With `jaw_center_along_mm`, each box spans the full `jaw_width`
centred on that value. Without it, the dark, certain boxes span only the zone
material's extent along `jaws_along`. The remaining `jaw_width − extent` on
either end of each jaw is a possible jaw region: a
cutter or holder sample clear of the part and the certain boxes but inside
that overhang is "uncertain", and the op's hit counts stay `?` (with the
reason `<n> sample(s) clear of the part and placed jaws reach the undeclared
jaw extension along <axis>; <m> sample(s) certainly hit`) rather than
passing; samples that hit anyway are still reported as certain hits. Part
material longer than `jaw_width` with no declared centre is `part spans …
more than jaw_width_mm …; the jaw position along <axis> is undeclared, so
jaws are not placed`. The engine never guesses a lateral centre.

### Parallels

The parallels add solids only when the hold declares `parallels_centres_mm`
and the selected parallels row's `height`, `length` and `width` facts are accepted: two
boxes `length` along `jaws_along` × `width` along the clamp axis × `height`
down, tops at the part seat. They lie below every tool and holder cylinder,
so they never enter hit counts; they exist for the picture, for the
`declared parallel centred at [x, y] intersects the <side> jaw` debt and for
the jaw-opening check of [`fixture_interference`](#fixture_interference). With
any of those inputs missing for selected parallels, the scene records
`parallels not drawn: … undeclared`. A vise hold with explicit
`parallels = "none"` or `"not_applicable"` instead uses known zero parallel lift:
no parallel boxes are drawn and their absent dimensions/centres do not create
fixture debt. Without another lifting support the stock seats on the bed.
Missing/unknown selections and
unresolved named parallels remain debt, as do nonpositive/unverified named heights.

## `accessibility`

### Scope, inputs and certain hits

Each cutting-operation row uses the five tool and holder dimensions: radius,
flute length, projection, holder radius and holder gauge length. A pass also
needs resolved fixture inputs for the selected holding model. For a vise this
includes the jaw geometry and pose. Within the supported milling domain,
missing inputs normally yield `unknown`.
Positive observed minimum hits still error despite unresolved fixture or
dimensions when those minima are certain. Unknown stock cannot produce a
numeric certain tool minimum: both `tool_hits` and `min_hits.tool` remain
`unknown`; independently known holder minima are unchanged. On the stopping
op, positive part hits may be its uncredited own removal. Independent approach
orientation errors, placed fixtures, chuck and uncut-side rests retain numeric
tool minima and error. Tool hits on turned-side rests whose pose depends on the
rejected own removal are uncertain; holder minima are unchanged.
Trusted-stock tool collisions still error. Invalid face claims remain errors first; an
invalid clearing removal is named stock debt, not an error.

### Claimed-face samples

On the claimed face set the kernel samples a cell-centred
5×5 UV grid per face plus 2 to 12 points along every boundary edge and gives
each sample one prescribed tool pose (PLAN §4.2). Ordinary wall samples use
the cutter-radius offset along the in-plane (XY) outward normal; ordinary
planar floor samples take their nearest legal centre below. The tip is at the sample's Z,
except as the rough leave below moves it.

### Bounded-operation samples

A bounded op removes nothing outside its `stock_removal_bounds` box, so its cutter
never stands where it would meet its before-op stock outside the box, the
finished part not counted. That is the same contact that clips its printed
paths (rule A′ below): the cutter cylinder, radius less 0.001 mm, from the
sample's tip up above the stock, common volume above 1e-6 mm³. A claimed-face
sample posed there is not this op's to reach. It is neither judged nor counted
as a hit. Beyond the box a cutter may still pass over air or the finished part,
and its hits on that part stay hits. A cutter whose axis lies inside the
authored box eroded by its radius stays in the box's XY column, so it is
checked only when stock stands above or below the box. The kernel reports the
unreached samples as `bounds_unreached`: their `sample_count` and the face
`indices`. `sample_count` keeps only the judged samples. If every sample is
unreached, `sample_count` is unknown with that reason. When the stock outside
the box is unknown, every sample is judged; unknown stock already
leaves the tool hits unknown. Hole and joint cuts keep their own poses.

The rule carries those faces as debt. A later op that cuts (a rough cut
included) or files to the line, never a saw or a coating, whose kernel claim
holds the face discharges it and is judged on it in turn. The finding's `bounds_unreached` evidence lists `faces` and,
for each face, the later ops it is `carried_to`. If no later op claims the face,
the finding is an error: no op makes that part of it. An earlier claim never
discharges it. If a later op names the face, or has unknown refs, and its
claim is unknown, or an op of unknown action claims it, the debt stays unknown. Certain hits at the reached
samples still fail the op. The debt is judged even when a missing tool or
holder dimension, or other unresolved context, leaves the op's own hits
unknown: with no later claim of the face it is still an error.

### Printed checkpoints and rule A′

For an op whose coordinate tables print cutter-centre rows
([coordinate rules](rules-coordinates.md)), the kernel stands the op's cutter
cylinder (radius less 0.001 mm) at every printed row's
displayed setup XY from its displayed tip up above the setup-entry stock; a
`chain_drill` row stands its drill cylinder at its full radius from its
actual tip Z, since each hole is a real drilled cylinder, not a lifted sweep.
Host DRO selection and kernel regeneration/actual-hole acceptance share one
pure finite-boundary clearance predicate for all chain arc and join holes,
bounded or unbounded. Actual closed finished loops, including joined bottom
outlines and full circles, use point-in-region plus nearest finite-boundary
distance, signed negative in kept material. Unordered exact lines and finite
arcs are connected by real endpoints and interpreted using authored scrap
normals; neither tessellation nor invented closure supplies missing geometry.
True open arcs and the current partial top-plus-land wall packets use oriented
finite projections. The top packet does not carry the tapers and bottom arc,
even when those linked facts exist in the host model; fuller actual
closed-boundary transport is tracked in
[#212](https://github.com/pedropaulovc/prechips/issues/212), not supplied by
inventing closure. The open fallback uses
real free-end caps and shared-concave-vertex sector classification instead:
a kept-side shared corner is not an unsigned cap pass. Ties are conservative,
not a global AND of distant supporting half-planes. Missing, ambiguous,
inconsistent or unsupported region geometry is unknown; no admissible grid
point leaves cut tables withheld. Closed-loop break-out centre segments are
checked for kept-region entry against the whole finite boundary, not merely
their own join lines. The open fallback is not full-part region proof.
This declared profile guard does not certify the whole STEP or replace the
existing 3D cylinder/accessibility backstop, bounds, rough-leave, fixture and
later-setup collision checks below.

#### Clipping driven paths

A bounded op's tables arrive whole and are clipped first: the kernel sweeps
that cylinder along each printed path and ends it where its common volume with
the op's before-op stock outside its `stock_removal_bounds` box, less the
finished part, first exceeds 1e-6 mm³, located by bisection to
`CLIP_PRECISION_MM` (1e-4 mm) along the chord and printed on the setup's DRO
grid (`dro`) at the nearest point on the legal side, no nearer the walls, from
which the cutter still sweeps clear. A path that leaves and re-enters that
stock is several pieces, never reconnected (a closed path's pieces across its
seam are one); one with no legal part has none. Facts: `checkpoint_clips`
(`clipped_at`, `precision_mm`, and per printed path its first row id `table`,
`rows`, `pieces` of `row` indices and clip points `after` a row at fraction `t`
with `exact_xy` and `dro_xy` in plan units, `dropped_rows`, `clip_points`), or
its `reason` when the clip is unknown: the frame, cutter radius, DRO grid,
before-op stock or a boolean is unresolved, and then no row remains.

#### Regenerating bounded chains
A bounded `chain_drill` path is not swept: the kernel intersects its true
drill-centre offset curves (`chain_geometry`: the arc and finite join lines,
their walls, pitch and offset in the setup frame) with the bounds box eroded
by the full drill radius, to `PLANE_TOL`. A closed arc's retained fragments
across its seam are one span; an exact tangent contact keeps its one real
hole. Each retained arc or straight-leg span is regenerated on its own with
equal nominal intervals along that curve (not one uniform respacing across a
miter): the hole count is chosen so the nominal spacing is no longer than the
pitch and still leaves a web (centres more than a drill diameter apart). That
web is judged on the actual snapped DRO centres, not on the nominal span
alone: for a retained span longer than the length tolerance, the
pitch-required count is always tried at its snapped positions, even when it
exceeds the nominal-length web bound, and any higher nominally feasible count
is also tried before the span is shortened; a span within that tolerance (an
isolated point such as an exact tangent contact, or a tiny retained arc or leg
between two shared junctions) keeps exactly one real hole, never a duplicate
row at the same centre.
Exact junctions between legs are kept and shared across tables. A span whose
snapped placement leaves no positive web at any such count omits its clipped
end hole (a junction's shared point stays unless the short tail is the chain's
own end) and records that in
`dropped_ends`; clipping alone does not fabricate a no-web error. Every actual
hole snaps onto the DRO grid inside the eroded box and passes the shared
finite-boundary predicate with clearance for the whole drill and allowance.
Closed loops require scrap-region membership, including beyond a particular
wall's finite projection; true open packets use the finite-projection,
free-end-cap and shared-concave-vertex fallback above. Bounds never waive
this test. Nominal-distance/offset guards remain additional placement
constraints, not separate unsigned side acceptance. The authored radial
whole-hole precondition is intentionally preserved before clipping, but is
not imposed on regenerated finite-cap holes beyond the actual sweep: such
a hole may lie inside the authored supporting circle when physically safe.
Unsigned finite-wall distances still measure stock/residual and collision
or nearest-search geometry, not kept-region membership. The T6
`numbers.max_filing_stock_mm` cap is enforced on the actual regenerated
residual. Every
hole searches the symmetric square within three grid steps on each axis;
the nearest safe point wins by Euclidean distance with a deterministic
coordinate tie-break. A diagonal is not rejected by a one-step circular
cutoff. Ends and junctions may back off inward along the true curve until a
safe grid point exists; a junction's shared point is one fixed DRO point
across its tables. A backed-off end hole has no one-step distance guarantee
from the true bound intersection. A hole with no grid candidate after its full
search and back-off is never placed in finished material; it leaves the clip
unknown, as below. A fractional
swept-chord intersection never becomes a hole. The chain's `checkpoint_clips`
entry carries `regeneration = "true_curve"`, `pieces` of `generated` points
(`exact_xy`, the nominal point on the true offset curve the hole was generated
at, after any back-off; `dro_xy`, the actual centre; `model_xy` in the feature
plane; an arc hole's `angle_deg`, continuous across a closed arc's seam; and `overshoot` at an exact miter),
`dropped_ends` (whether the chain's first or last nominal end was lost to the
clip or to a short tail), the authored `dropped_rows`, and empty
`clip_points`; `clipped_at` records regeneration against the true offset curve
at the eroded bounds, not a separate end stop at every marked row, and
`precision_mm` is `PLANE_TOL`. Unknown or disconnected chain geometry, a
box too small for one full drill, any retained interval with no safe grid
point after its full search and back-off (an end or junction included), or
no surviving centre leaves the entire
clip unknown, even when another piece survives: never a partial table.
Deliberately shortening a free end to preserve a positive web remains allowed.
Internal `chain_geometry.walls` carry line scrap normals and arc outward
signs for this shared predicate, not new user schema or policy. The pure
`kernel/chain_boundary.py` helper is an engine source (`freecad_job.py`
imports it), so it participates in the engine source digest and changing it
re-keys every kernel job, not just chain jobs.

#### Checkpoint evidence and verdict

The kept
rows, renamed per piece with the coordinates row-id formats, are the only rows
the row check and the setup picture's waypoints use; a bounded op's removal
stays its box, and an unbounded chain's its discrete holes, never a printed run-out. Each
row is an error naming it when that cylinder meets the finished part, the op's
rough leave (its guard less the finished part, inside what the row removes),
a fixture component, or, for a bounded op, before-op stock outside its
`stock_removal_bounds` box, each over 1e-6 mm³; or when what the row removes
past its op's design is stock a later setup bears on (the profile-corridor
paragraph under [In-process stock](#in-process-stock)). Facts:
`checkpoint_count`, `checkpoint_hits` (rows with an error, or `unknown`),
`checkpoint_errors` (`row`, `obstacle`, and `volume_mm3` or `later_setup`,
`contact`, `area_mm2`), `checkpoint_reason` and `checkpoint_overshoot_ok`
(corner-miter rows proven clear, empty while any row is unknown). Any error
makes the op an accessibility error listing the first three (and how many
more); an unknown check makes the op `unknown`, never a pass.

### Rough leave and retained stock

A rough milling op's scalar `rough_allowance_mm` (a) is a leave in millimetres
normal to the finished surface. Each rough sample first moves `a` along the
face's unit outward normal, then takes the ordinary cutter-radius `r` shift
along the in-plane (XY) normal; planar
floor samples below need legal clearance `rho = r + a`. The
derived output stock protects the finished solid offset outward by `a`, which
retains the radial and axial leave, drafted faces included, and a later
finishing op that claims those faces removes the leave as its own derivable
allowance. An explicit `to_z` caps the endpoint rather than adding to the
leave: the tip is the higher of `to_z` and the floor plus its leave, so a
`to_z` already at the rough floor plus a 0.2 mm leave is that endpoint, not
0.4 mm above the floor. The tip never goes below the retained leave, and
numerical lift still separates it from the finished face. A finishing op's
numeric `to_z` above the sampled face is likewise its actual tip: a spring
pass to 0.1 mm above the floor samples there, matching its own cut, so the
skin it leaves is stock below the tip rather than a hit, and a later
full-depth pass removes that skin as its own cut. An unknown
authored leave makes the op's accessibility `unknown` and later stock that
depends on it debt. The protected solid is built by offsetting the finished
solid outward by the leave. Where that offset's arc join cannot be built (a
blind cone can make it fail), an intersection-join offset may be used
instead, but only if it is valid, contains the finished solid and keeps the
same solid count. It is conservative and leaves extra material at convex
corners, never less than the leave, and there is never a fallback to the
nominal finished solid or a zero leave.

#### Local offset construction

When both whole-part offset constructions fail, the op's guard is built
exactly in each box where a consumer subtracts it. A zero-height land tangent
to a cylinder, such as the cone pivot post's journal pads, can make OCC fail at
any leave. The boxes cover its claimed
faces grown by its wall-check reach (`max(a, carried) + 0.01` mm, also
covering its band and pose contacts), and its clearing box above `to_z` or
its whole unclipped +Z claim sweep or profile corridor. In each box the finished part's offset
equals the arc-join offset of the finished part within the box grown by
`2a`, cropped to the box. Every positive-volume source and cropped component
is kept, each piece must offset to one valid solid containing it, and the
crop must contain the finished material in the box. Every Boolean in the
construction must be valid; one that meets nothing is empty, but faces
without a solid are debt, never taken as empty. Only arc joins qualify, and
each consumer subtracts only inside its own box.

The lineage band of a lower-leave op needs no whole-part offset by the carried
leave. Its candidates are the carried-leave skin of the claimed faces: each face
thickened, plus on each convex edge two claimed faces share a tube (an arc
pipe must have volume πr²L) with a ball on each of its vertices. An edge's
kind is decided only where it is exact along the whole edge: a line both
faces are invariant along (planes, cylinders with a parallel axis, cones
through their apex) or a circle both are invariant around (coaxial planes,
cylinders, cones, tori, spheres). Tangent and concave shared edges add
nothing, and any other shared edge is debt. Each candidate is cut on its
own, and every positive band fragment, however small, is kept, grouped by
contact, never fused; the band is the groups that border a claimed lateral
face. No piece may overlap the finished part or an unclaimed neighbour slab
by more than 1e-3 mm³. The op's own clearance is cut first, then each band
group in turn. A group is skipped only if none of it is in the stock piece,
or if the cuts before it took all but at most 1e-6 mm³ of a group that held
more, because cutting material that is already gone only adds OCC
coincident-face artefacts. A tiny group still whole, or one whose remainder
is not valid topology, is cut. Only the end of the op's cuts is judged, so a
fragment one piece splits off may still go with a later piece. No more than
1e-3 mm³ of the band may survive in each input stock piece the op leaves, and
each piece it leaves must be valid.

#### Held splits

One input stock piece may leave several pieces above 1e-3 mm³ only as a held
split. Every piece must be pressed onto an anchored support, or the whole split
is refused and no piece is dropped. A
piece is held when a clamp declared `restraint = "press"` has a flat face
whose outward normal is its force (pose -z, within 1e-6) within 1e-3 mm of
the piece, and from one cell-centred sample of that face (the strap-wall grid)
the first material run through the piece along the force starts within 1e-3
mm of the sample and ends where the point 0.01 mm beyond lies inside an
anchored fixture component: a fixture body, jaw, parallel, riser, chuck jaw or
body, dividing head or centre, never a clamp, rest or other stock piece. The
holding must be placed. `locate`, `none` and an undeclared restraint never
hold. The op's `split_hold` lists each piece (number, volume, bbox, `held`,
and the clamp, sample, exit point and support that hold it). A held split keeps
every piece until a `keep` drops them ([keep piece](#keep-piece)). Otherwise the
stock reason names the removal that broke the stock ("its own clearance" or
"lineage band group N"), or the split and each piece with "no press-clamp
load path to an anchored support", and the op that stopped the stock pass is
credited none of its clearance. If any construction fails, the result is
named offset debt.
Every offset and pipe is built on a deep copy of the solid, face or edge it
starts from. OCC's offset rewrites the edge tolerances and pcurves of the
shape it runs on, so offsetting a face shared with the finished part would
change that part, and every later Boolean against it, by call order.

### Nearest legal centre

Every sample of an ordinary claimed +Z planar face of a milling op, excluding
hole and joint ops, keeps its own surface sample and stands on its nearest
legal centre. This includes concave corner samples. The tip height comes first
and is the pose's actual height: `z =
max(face z + a, to_z) + LIFT`. Clearance and the move limit are both `rho`:
the cutter radius `r` for a finishing op and `r + a` for a rough op, so a rough
cutter is never asked to finish a wall foot its leave keeps. An axis `c` is
legal when it lies outside this branch's certain material (current components
within their raw supply, without permitted unjoined sockets) and the section
of that material at `z` is at least `rho` from `c`. A legal sample keeps its
own axis. Otherwise the pose is the legal axis nearest the sample within
`rho`; equally near axes (one fixed `PLANAR_EQUAL_MM` = 1e-7 mm, never scaled
by a radius or widened by `STOCK_TOL`, and never growing material) go to the
one nearest the face's area centroid, then the least `(x, y)` in the setup
frame. With no legal axis within `rho` the sample keeps its own axis and the
native check reports its genuine hit: a sharp concave corner an R2 cutter
cannot reach is a hit, not a cleared pose 2.83 mm away.
The axis is derived, never searched. Only section edges within `2 rho` of the
sample can bound an axis within `rho`; each line yields its two parallels at
`rho` and end-vertex circles, each Z circle its concentric circles `R + rho`
and `R - rho` (a point when `R = rho`, so an exact cutter-sized circle is one
axis and an exact `2r` strip one line). Candidates are the nearest point of
each such primitive to the sample and the meeting points of every pair, ranked
by distance and certified in that order against the whole native section and
solids (containment, then `distToShape >= rho - 1e-7`), never an area offset
or a bounding box. Only the section at `z` steers the axis: overhangs above,
leave below `z`, future hole cores and unclaimed raw stock do not, but the
full flute against the accepted after-op stock and the holder against
setup-entry stock still meet them at the chosen axis.

#### Native nearest-bound certificates

Another curve within `2 rho` of an illegal sample (a B-spline or ellipse wall)
has no exact offset, so that sample needs a native nearest-bound certificate.
Its domain is the whole native section at `z`, every edge included (the
approximating B-splines `slice` returns among them), and every certain solid:
nothing new is approximated or ignored, and nothing beyond the native model's
precision is claimed about the physical surface. Let `q` be the section's
native closest point (exactly one pair, or bit-identical duplicates; never a
tolerance cluster or an average) and `d = |p - q|`, from the coordinates.
Every axis at least `rho` from the material point `q` is at least `rho - d`
from `p` (triangle inequality), and `c = q + rho (p - q) / d` attains that
bound, so a `c` with exact clearance `rho` is the unique nominal nearest axis.
Native acceptance is the fixed 1e-7 mm comparison above, so a legal `c` proves
only that no accepted axis is more than 1e-7 mm nearer; no uniqueness among
accepted axes is claimed. `c` therefore joins the supported candidates in the
unchanged ranking: the nearest enumerated distance `best` lies in
`[d_c - 1e-7, d_c]`, where `d_c = |c - p|`; the selected distance is at most
`best + 1e-7`, hence at most `d_c + 1e-7`. Centroid and least-`(x, y)` ties
use the same ranking. Two cases certify. Outside: the sample is outside every certain solid (boundary
counts as inside), `1e-7 < d < rho`, and every native Edge reported at `q`
resolves to exactly one section edge. On a straight line: `d <= 1e-7`, the
sample is strictly inside no certain solid, the only section edge within
1e-7 mm of it is one native line whose foot `q` lies more than 1e-7 mm inside
both ends, and exactly one of `q ± rho n` (`n` the line's unit normal) is
legal. The precision policy is conservative and fixed: a closest point reported
on an unsupported curve (even at its end parameter) refuses when that edge's
native `getTolerance(1)` exceeds 1e-7 mm, which in practice refuses every
projection inside a sliced B-spline (they carry about 4e-5 mm), while lines,
circles and vertices count at the native model's precision; neither `rho` nor
1e-7 mm ever grows. The boundary case is line-only scope, not a claim that a
smooth spline normal is wrong: a spline, circle, seam, corner or vertex
boundary stays uncertified.
For context only, an accepted axis within `d_c + eps` of the sample (`eps` =
1e-7 mm) lies within `R(d) = sqrt(eps^2 + 4 rho eps (rho - d) / d)` of `c`
(about 0.0015 mm at `rho = 3`, `d = 1`, growing as `d` nears `eps`); on a line
the analogue is `R_B = sqrt(eps^2 + 4 rho eps)` (about 0.0011 mm) while the
foot stays at least that far from the ends, though the fixed end margin is only
1e-7 mm and band competitors keep the ordinary ranking. These describe the
numeric tie band, never a radius allowance or an eligibility gate.

#### Undefined floor poses

An uncertified sample (a contradictory classification, an illegal `c`, two or
no legal normals, or any refusal above; a farther legal supported axis never
stands in for it), an ambiguous section (a certain face starting or ending
within 1e-7 mm of `z`, an open or invalid section wire), missing raw supply or
a failed native construction leaves that floor's pose undefined: its own poses
drop, certain hits on the op's other faces stay in `min_hits`, `hit_refs` and
`obstacles`, and the op's measured facts become `unknown` with `<face>: floor
tool pose is undefined (...)`. Farther curves never make a pose undefined.
Concave floor corners add their own samples; convex island corners get none.
A legal centre selects a pose, not a corner-radius certification. Floor-only
claims do not certify wall/wall
corner radii: `internal_corner_radius` still checks a sharp wall/wall corner
only when the op claims both walls, with its existing scope unchanged.
Adjacent finished walls are not removed to manufacture clearance, and
undercut or leaning walls remain obstacles.

### Tool and holder obstacles

The holder cylinder uses gauge diameter and gauge length and starts
`projection_mm` above the tip. Both cylinders are intersected with material
minus a thin inward offset shell of that sampled face only, plus the jaw boxes. The
holder meets actual setup-entry material. The flute meets the stock the
setup's earlier derived cuts leave (see [in-process stock](#in-process-stock)), less this op's
own derivable outside-finished allowance; the holder still sees both. The
shell removes numerical self-contact, not a cutter-radius slab and not another
finished face of the same feature. A cutter wider than a claimed groove
therefore still intersects the opposite claimed wall. Holding, rendering and
accessibility holder obstacles use actual setup-entry stock, and no flute is
credited with a later op's removal.

### Hole caps and own-cut exclusions

Claimed concave cone or sphere point caps are not blanket-exempt. Only a hole
op's own known matched cap is: a cap (as defined for planned-hole columns)
that shares a real edge with a claimed concave cylindrical bore parallel to
setup Z and lies wholly below that bore, closing the end away from the tool.
An upward-facing cap is not matched. For an op whose hole cut resolves, a
sample on that cap uses the unmodified stock (the flute's stock before this op,
less its own cut) instead of the own-face offset shell, which cannot be built
at a cone apex; the on-axis cutter's numerical-lift shrink already removes
self-contact, and the holder also sees the full entry stock. The cap's actual
collision is still checked:
a wrong point angle, a point deeper than the finished cap, or a flat-bottomed
tool against a matched cone or sphere hits. A wider countersink and tilted or
unrelated caps keep their offset shell, unknowns and real hits, and no other
op borrows this exemption.

#### Complete-form caps

A `complete_form` op must also form its own matched claimed caps. After the
setup's cuts and the profile-wall check, the cumulative stock minus the
finished solid must not touch any of those caps, under the same exact and
inset interior-contact test as walls. The test has no `to_z` clip, leave or
tolerance. Stock below a flat finishing floor therefore still leaves a cone
unformed, as does a flatter or smaller point. A cut that removes nothing is
judged too. The op's `cap_completion` fact names `caps` and `unformed`
(finished-face indices). A touched cap makes the setup's output stock debt,
which it names; it is not a collision, and accessibility facts are unchanged.
When the completion cannot be measured (unknown stock, a hole-cut debt or a
failed boolean), `unformed` is `unknown` with a `reason`. Only matched caps
are judged: no other cone or sphere is waived or added. A counterbore op whose
explicit `faces` omit the small bore does not judge that bore's cone.

#### Hole cutter volume

For drill, spot, ream, bore, tap and counterbore operations, the flute stock
obstacles exclude only the op's own actual cutter volume, to its declared
depth or explicit through extent. Hole centres and axes derive
from geometry-matched concave cylindrical faces aligned to setup Z, not a
guessed face centre. An independently accepted own hole cut is excluded even
when upstream stock is unknown: reamer flutes inside the very bore they cut
are cutting material, including their accepted own-bore wall allowance out
to the operation radius. This does not certify a diameter or stock lineage.
The same accepted-cut claim/depth gates and geometry-located cutter are used;
an unknown or invalid own cut receives no exclusion, no default envelope,
and no other operation's cut. Unrelated finished material remains an obstacle,
but tool hits on unknown stock remain uncertain rather than certain errors.
Own-cut subtraction supports geometry diagnostics and the witness-mutation
keeper; the blanket unknown-stock minimum cap means it is not itself a
verdict-level guarantee.
This exclusion does not clear holder obstacles: the holder cylinder is
unchanged and meets the full actual setup-entry stock. Missing depth or entry
facts and explicitly unknown through facts remain debt; an omitted `thru`
uses the existing blind-hole default, not an assumption of through
clearance. No removal extent is invented.

### Point geometry and depth endpoints

A spot or drill cuts with its actual point: a cone with its apex at the tip,
widening by tan(`point_angle_deg` / 2) per millimetre of rise to the tool
radius, then a full-radius body. The numeric included angle is mandatory for
both. An `unknown` angle, or one not strictly between 0 and 180 degrees, is
named debt (`<action> point_angle_deg is unknown; its point cone is unknown`):
the op's accessibility is `unknown`, and its removal is not derivable, so a
later setup selecting that output carries stock debt. No flat-bottomed
cylinder or default angle substitutes. The flute check uses the same cone and
body, shrunk by numerical lift, against part and modeled fixture solids; the gross
cylinder only culls. Ream, bore, tap and counterbore remain flat-bottomed
operation-diameter cylinders.

Depths follow [tip endpoints](rules-operations.md#blind_depth-tip-endpoints).
A spot's `depth_mm` is its apex tip depth below the entry. A drill's
`depth_mm` is its full-diameter depth; its tip lies a further point length
`r / tan(point_angle_deg / 2)` deeper. An op `to_z` is the absolute actual tip,
with nothing added. A through drill's full diameter exits each matched bore's
actual axial bottom, so its tip is one point length (plus numerical lift)
below that; other through actions end at the bore bottom plus numerical lift,
not the raw-stock bounding-box bottom. A planned exit governs instead, never
deepened to the CAD: the received exit face
(`entry_z - local_thickness[feature]`) less the op's `exit_mm`, both numeric and
`exit_mm >= 0`, is where the tool's full diameter stops on every matched bore. Below
a bore's end it cuts the stock carried past it (a cap left proud by a part-off),
so no skin stays over the bore's mouth. More than 1e-4 mm above a bore's end the
plan contradicts the finished through bore: the tool still stops at the planned
exit (no lift, so the bore keeps its unfinished floor), and the op's
`stock_removal_error` names the planned exit Z and each bore end it stops short
of, so its [`accessibility`](#accessibility), [`reach`](#reach) and
[`internal_corner_radius`](#internal_corner_radius) rows are errors.
Spot and tap operations honor an explicit depth even when the feature declares
`thru = true`; that feature fact does not extend their local removal past the
authored endpoint. `stock_state.top_z` and `entry_z` are machine-frame
millimetres, and operation `depth_mm` is millimetres even when feature units
are inches. Tap fallback feature-depth bands are converted to millimetres.
For a spot, the sampled cutter tips and holder poses likewise stay above that
authored endpoint: a 2 mm spot at the mouth of a 74 or 86 mm through bore has
2 mm reach, not the full bore depth. This is action semantics (`do = "spot"`),
including a centre-drill selected as its tool; the tool's name or kind does
not turn the operation into a through drill. A following through drill
retains its actual deep poses and any genuine deep chuck/fixture collision.

When the op radius exceeds a matched bore's radius, every hole action except
a spot also removes that bore's own wall out to the op radius. No fixed radial
cap limits that excess; the sizing rule owns the drill or reamer diameter. A
failed own-wall offset is named debt. A spot never widens its own bore, so a
spot cone reaching past the finished bore mouth still meets finished material.

### Native hit certificates

Generic-cylinder part-hit counts may avoid a redundant stock Boolean using an
exact positive material certificate (P6). The native classifier must place a
candidate centre inside valid closed positive-volume stock; rigorous lower
bounds must clear a 0.01 mm ball from every stock boundary, and the ball must
lie strictly inside the unchanged query cylinder. Its volume exceeds the
1e-6 mm³ hit threshold. Plane/cylinder bounds use their supporting surfaces and
tolerance-grown face boxes; positive-weight spline surfaces use their pole
hulls. Unsupported or failed proofs fall back to the original native Boolean.
The bounds trust the native face enclosure and inside classifier, and native
Boolean completeness remains a checked assumption.
The cylinder-query and prefetch paths allow bounding-box exclusions only for
proven finite, positive-volume material. Those paths preserve the native Boolean
answer for unsound stock, including reversed solids whose occupied material is
the complement of their face bounds.
Degenerated edges at cone apices or sphere poles still permit bounded occupancy
classification, but disable the stricter ball-hit proof.

A mathematically proven hit skips its redundant stock Boolean, even if that
solve would otherwise have raised. A Boolean that still runs is never caught or
suppressed by this optimization. Certificates
only count hits: they never prove a miss or replace a native shape, and actual
pointed cutters bypass them. A count-only hit skips the intersection only when
no finished face outside the already-proven reference union can add a hit
reference; partial reference sets never enter shared full-set caches. Every
authored sample still contributes to the full hit count, and input or stock
debt retains its existing unknown/error precedence.

### Claim direction and keep-out islands

For milling, a far-side face (outward normal opposing setup +Z by more than
90°) is an invalid cutting claim, reported as an error naming the face before
tool-dimension debt can hide it.

A face raster's `contour.keep_out` islands reach the kernel as the setup-frame
circles the coordinates rule mapped (`raster.keep_out`), with the passes it split:
the printed cutter-centre pieces and the parts of the island-free passes the
circles removed (`raster.keep_out_skipped`). Its passes keep the whole cutter
outside each circle, and each piece's round cutter end leaves a cusp between
adjacent piece ends, so the op takes only what its printed pieces sweep there:
no stock inside an island, and none within one cutter radius of a skipped part
that is farther than one cutter radius from every printed piece. Away from the
skipped parts the pieces sweep what the whole passes would. That kept stock
stays whatever else the op would remove there, its clearing box or claim sweep
and the lineage leave band it cuts off claimed walls alike; a later op (a hub's
stairs) or the bench must clear it. A claimed-face sample inside or on a circle,
or in that kept stock, is not that op's and is not posed, and a floor sample's
legal centre nearer a circle than one cutter radius beyond it moves straight out
from the circle's centre until the cutter edge touches it. The stock an island
keeps (a later op's rough leave on a boss) still meets the flute and holder at
every other pose. An op that authors `keep_out` without mapped circles or split
passes, or without a cutter radius, leaves its cut and accessibility unknown.
The [keep-out regression tests](../tests/test_kernel_keep_out.py) cover a
rough and finish face raster at a cutter-diameter step around an authored
boss. Both retain the island and the cusps between their piece ends over the
boss height, with zero tool hits at their poses. The expected retained volume
comes from an independent strip integration of what the printed pieces miss,
not from the kernel's removal calculation. A finish pocket that also claims
the boss wall inside its keep-out leaves the same rough allowance as a
floor-only claim. Unmapped circles or passes leave the cut and accessibility
unknown in those test cases.

### Boundary cases and reported evidence

Kernel regression tests cover these fixture-specific distinctions:

- In the [boss and jaw cases](../tests/test_kernel_geometry.py), a plate-top
  sample within a cutter radius of the boss uses its nearest legal centre and
  clears. Dimensioned jaws occlude the holder only when they stand high enough.
- The [curved-floor cases](../tests/test_kernel_curved_floor_poses.py) cover an
  R10 circular pocket, an exactly cutter-sized circle and a groove exactly two
  cutter radii wide. They clear at their prescribed poses. Sharp arc/chord and
  arc/arc corners that have no covering legal centre report wall hits, as do
  cutters wider than their circle or groove. A sample past both walls of a
  square island's convex corner moves straight away from that corner and clears.
- The [planar legal-centre cases](../tests/test_kernel_planar_legal_centres.py)
  include a fillet corner equal to the cutter radius that clears, a sharp
  concave corner without a legal centre within `rho` that hits, and equal
  candidates that use the face centroid.
- In that file's spline cases, an outside sample whose native closest point is a
  vertex and a sample on a straight edge are accepted through their certified bounds.
  A spline boundary, strictly interior sample, vertex boundary, projection
  inside a spline whose native tolerance exceeds 1e-7 mm, or bound blocked by
  a second obstacle leaves that floor's pose undefined. A farther clear
  supported axis does not replace the bound, and another face's certain hits
  remain.
- The [face-local cutter cases](../tests/test_kernel_region_geometry.py)
  require a cutter tangent to its claimed side wall to clear. This guards
  against a sample-centred cutter mutation in place of the normal-offset
  pose. A Ø10 cutter in the authored 6 mm through-groove hits the opposite wall.

These tests distinguish the prescribed poses without establishing clearance
for arbitrary geometry. The legal-centre convention changes the pose, not the
obstacle solid. There is no pose search, and unresolved pose or exclusion facts
remain debt rather than clearance.
Numbers: `sample_count`, `tool_hits`, `holder_hits`, the five inputs, and
`certain_tool_hits` / `certain_holder_hits` when observed hits are definite
despite unresolved inputs, poses or undeclared jaw overhang. Unknown stock
leaves `certain_tool_hits` unknown rather than a certain collision; holder
minima retain their entry-material evidence. In a built-up plan any hit adds
`hit_owners`: per hit kind, `part` names the branch's components (their stock
was hit), each finished face ref bounding a hit names every component whose
finished share holds a positive area of it, and a fixture label names itself. A stopping op's known before-stock
can establish a zero upper hit bound and independent fixture hits, but not
certainty for its unresolved own part-material removal.

### Findings and limits

- `{subject}: selected cutter or holder is certainly occluded by part/fixture material.` (error: any hit; also raised from positive `certain_*_hits` while aggregate counts or other inputs are unknown)
- `{subject}: sampled claimed faces clear the selected cutter and holder cylinders.` (pass)
- `{subject}: offset-cylinder sampling is unresolved.` or the kernel's per-fact reason (unknown; includes samples in the undeclared jaw overhang with no certain hit, an own-region boolean that failed, or a sample without a defined normal)

Both verdicts are about the prescribed poses only: the rule stands one
cylinder per sample at the prescribed position and asks whether that pose
is blocked. An error says those poses are blocked, not that the face is
unreachable by any approach; a pass says those poses clear, not that a
toolpath exists or that every pose along it clears. Neither is a swept-volume
or search-based reachability proof.

## `reach`

### Reach depth and holder walls

The rule needs `flute_len_mm`. The kernel measures reach on the stock the op
meets: setup-entry stock less every earlier op's accepted cut in that setup
(see [in-process stock](#in-process-stock)). For each upward-facing sample it takes
the highest such material within the cutter radius + 0.05 mm of the offset tool
axis, and reports the largest such height above a sample as `reach_depth_mm`.
`holder_wall_hits` counts samples whose holder cylinder (starting
`projection_mm` above the tip) intersects that same stock, and needs the holder
radius, gauge length and projection. A stock the builder cannot derive leaves
all three unknown with its reason, never measured on the setup-entry stock.

### Shank and countersink seat

The tool past its flutes is the shank: `shank_mm`/`shank_in` from the
inventory (a `{ value, measured }` record, halved to the engine's
`shank_radius_mm`) running from `shank_from_mm` above the tip to the holder
face. `shank_from_mm` is the flute length, or for a combined drill and
countersink (`angle_deg`) the flute plus its seat cone out to the shank
diameter. That seat cone, from the flute radius at the flute end to the shank
radius at `shank_from_mm`, is cutting body, not shank: it is part of the tool
solid whose hits `accessibility` counts, and a spot or drill removes it with
its own cut: the cone at its final pose and, above it, the shank-diameter bore
its widest edge sweeps on the way down. So a spot deeper than its pilot
countersinks its own mouth, one deeper than the whole cone bores it out to the
shank diameter, and finished material in that path (a retained shoulder
inside the cone, a narrower finished bore) stays a tool hit. `shank_hits`
counts the samples whose shank cylinder meets the stock the op leaves: the
shank trails the flutes through the op's own cut (down its bore, or pass by
pass down a milled wall), so the finished bore or wall counts and the op's own
allowance does not. An unknown shank diameter or start leaves `shank_hits`
unknown. Reach draws the recorded shank as given; whether that shank fits its
collet (the ISO 286 h6 band below a single nominal capacity) is
[`tool_resolves`](rules-tools.md#tool_resolves)'s check, not reach's.

### Clearances and reported evidence

On a hole op's own axis the kernel also reports four clearances, each the
least over its axes, measured within the holder radius:

- `body_clear_mm`: the flute body's radial gap above its own cut's mouth to the
  stock the op leaves (a crown, ear or wall beside the spot);
- `seat_clear_mm`: the seat cone's radial gap to that stock (at each height,
  the stock's distance from the axis less the cone's radius there). A cone
  that meets no stock is measured above the countersink it cuts itself, as
  the body is above its mouth; one that meets it reports the interference
  from the flute end up, exact down to minus the pilot radius and unknown
  deeper; `"not_applicable"` for a tool without a seat cone, and unknown, as
  the shank, when the shank radius is: only that radius tells a seat cone from
  none;
- `shank_clear_mm`: the shank's radial gap to that stock (the finished bore wall
  for a reamer past its flutes);
- `holder_clear_mm`: the holder face's height above the highest stock the op
  meets under the holder, at `holder_clear_top_z_mm`.

Each is `"not_applicable"` when no such stock stands beside that part of the
tool, negative when the part is inside the stock, and unknown with the
reason when an input is missing. They are reported numbers, not limits: no
minimum clearance is enforced beyond the hit counts.

Numbers: `reach_depth_mm`, `flute_len_mm`, `oal_mm`, `projection_mm`,
`holder_wall_hits`, on a milling or axial joint sample `reach_top_z_mm` (the
setup Z of that highest material, the reach reference; `"not_applicable"` when
no material stands beside the tool), and off the turning model `shank_dia_mm`,
`shank_from_mm`, `shank_hits`, any of `body_clear_mm`, `seat_clear_mm`,
`shank_clear_mm`, `holder_clear_mm` the kernel reported and `clearances`: one
`{ part, obstacle, mm }` per reported clearance other than
`"not_applicable"`, with `part` `tool body`, `seat cone`, `tool shank` or
`holder face`;
`obstacle` `the Ø<d> bore this op cuts` when the gap is the op's own bore,
`stock <r> from the tool axis`, `stock under the holder` or, when
unmeasured, `stock beside the tool`. The holder face's entry also carries
`z_mm`, the kernel's `holder_clear_top_z_mm`, when that Z is measured.

### Clearance on the setup sheet

The traveler's mill CLEARANCE table takes the reach finding's holder clearance:
the holder face's height above the highest stock beside the tool, `projection_mm`
less the reach from `reach_top_z_mm` (as that surface's DRO Z) down to the op
row's printed tip. A holder face below that stock prints its depth below it, with
the wall verdict; past the flute, holder wall hits are a STOP and unknown hits a
check-at-the-machine action. Each `clearances` entry (`part`, `obstacle`, `mm`)
competes for the op's closest obstacle; a negative one is a STOP; an entry with
`z_mm` names that stock's Z. Every kernel Z the table prints (`reach_top_z_mm`,
`z_mm`) is that surface's one DRO Z: a value within the kernel's as-is face
tolerance (1e-3 mm, `FACE_Z_TOL_MM`) of a DRO grid line is that line, kernel
noise; any other value rounds up on the grid as every surface does, so the
same stock top prints the same Z in the table, the op rows and the zero recipe.
Reach is never printed as a cut depth.

### Verdict boundaries

- depth > OAL: `entry-to-floor depth exceeds the selected tool OAL.` (error)
- shank hits: `the tool shank past its flutes meets the retained stock.`
  (error, at any depth)
- depth ≤ flute with zero shank hits (turning: no shank check):
  `entry-to-floor depth is within the selected flute length.` (pass)
- depth > flute with holder wall hits: `depth exceeds flute length and the holder intersects walls.` (error)
- the shank unknown, at any depth: the kernel's `shank_hits` reason, or
  `the shank past the flutes is unresolved against the retained stock.`
  (unknown). A shallow cut does not prove the shank clear: a spot 0.5 mm deep
  still sinks the shank beside a retained wall the flutes never reach.
- depth > flute, ≤ OAL, zero holder and shank hits and every holder dimension
  known: `depth exceeds flute length but fits OAL with the shank and holder clear
  of the retained stock.` (pass; turning: `… with the holder cylinder clear of
  walls.`)
- otherwise `entry-to-floor depth or holder wall clearance is unresolved.` (unknown)

A beyond-flute pass requires accepted holder gauge-diameter, gauge-length and
projection facts and, outside the turning model, a measured shank clear of the
retained stock. An unknown holder or shank cannot establish that pass.

### Turning reach and missing normals

On the turning model, `reach_depth_mm` is the radial height of material beside the
nose or blade, within its axial extent, above each sample. A single-point tool that
faces to `to_z` (`face`, `part_off`, `cut_to_fit`) feeds radially through stock it
has just faced. That depth is therefore measured on the profile left after the op,
so only a shoulder beyond the faced plane counts, and the stock radius never does.
If that profile cannot be derived, the depth is unknown. A two-cornered blade
plunges between the part and the slug, so its depth is measured in setup-entry
stock and reaches the bar radius. Turning and profile ops also use setup-entry
stock.

A sample without an evaluable surface normal makes the sampled face's
accessibility and reach unresolved, with the face and missing-normal count
named. It is never silently dropped to produce a clearance or reach pass.
Definite observed accessibility hits can still establish an error.

## `internal_corner_radius`

### Corner scope

The rule needs `radius_mm`. It measures concavity in the section transverse
to the tool axis, which limits a cutter of that radius.
A concave cylindrical claimed face whose axis is parallel to +Z contributes
its radius, and a sharp concave edge between two claimed faces that runs
parallel to +Z contributes 0. Horizontal concave edges (a pocket floor
meeting its wall) are not corners for this rule: a flat endmill cuts them.
For a hole operation, its own bore radius is a diameter-sizing question,
not an `internal_corner_radius` limit. Likewise its own known matched point
cap (see accessibility) is its actual tool shape, not an internal corner;
any other claimed concave cone or sphere, including a wider countersink or an
unrelated cap, remains the unreduced curved surface below.
Floor-only claims do not certify a wall/wall corner radius. A sharp wall/wall
corner is checked when the op claims both walls; legal-centre floor poses do not
expand this rule's claimed-face scope.
A concave cylinder with an off-axis axis, an oblique concave edge, or any
other concave curved claimed surface cannot be reduced to one radius and
makes the row `unknown` with that face/edge named. A refused preparation
radius (an untrusted cutter or stock-prep fact) does not erase what the
kernel did compute: valid corner claims it already judged keep their result,
an op with no concave corner at all stays `not_applicable` rather than
becoming debt on a fact it never needed, and only the stock and hits that
depend on the refused fact are `unknown`, naming it. Numbers:
`corner_radii_mm` (sorted), `tool_radius_mm`, `minimum_corner_radius_mm`,
`cad_sharp_corners` and `corner_radius_max_design_mm`.
These are finished-solid facts, independent of unknown in-process stock;
a known sharp corner remains an error even when reach cannot be measured.

### Numeric tolerance and drawing permission

The comparison uses a 0.005 mm numeric tolerance: a concave radius admits the
cutter when it is at least `tool_radius_mm - 0.005`. STEP coordinates commonly
write only 5 to 6 significant digits, so sub-tolerance import/kernel rounding
must not turn a nominally equal radius into an error. This is numeric tolerance,
not a machining allowance: a 0.004 mm deficit passes; a 0.006 mm deficit errors,
and a genuinely sharp corner still fails.

A CAD-sharp corner (modelled radius below 0.005 mm) is drawn sharp, but the
drawing may permit a radius there. Only the operation feature's own
`corner_radius_max_design` (explicit feature `units`; inch × 25.4) states that
permission: the cutter is admitted when `tool_radius_mm ≤
corner_radius_max_design` (equality passes; 0.25 admits a 0.25 mm nose, not
0.26). A modelled non-sharp corner smaller than the cutter is never rescued by
the allowance, and a title-block `edge_break`/`general_tolerances.edge_break_r`
is never borrowed. Without the feature field the sharp-corner error stays, and
the sentence names the missing `corner_radius_max_design`.

### Findings and limit

- no such corners: `claimed faces have no concave edges perpendicular to the tool axis.` (not_applicable)
- `concave corner radii admit the selected cutter.` (pass)
- `a claimed internal corner is smaller than the selected cutter radius.` (error)
- `concave edge radii are unresolved.` or the kernel's reason (unknown)

The rule does not certify a floor fillet or bottom radius against the cutter.

## `coverage`

### Credited faces

The rule emits one row for the whole part. Every imported face must be in the
union of cutting-operation claims, `stock.as_is_faces` and the faces of features
that a checked joint forms ([joint-formed faces](#face-identity)). A face
claimed through rotary windows counts only when the union of those windows
covers it. Numbers: `face_count`, `claimed_face_count`, `unclaimed_faces`
(their references, `null` for an unnamed face) with `unclaimed_indices`,
`mapping_errors` when present, and `rotary_gaps` / `rotary_unresolved` when
a rotary-claimed face is not covered (below). Sentences label an unnamed face
`imported face index <n>`.

### Findings and precedence

- `invalid STEP face reference(s): …` (error)
- `cutting claims are unknown, unmapped or undecided, or as-stock refs are unknown.` (unknown: any unknown action, unmapped feature, unresolved claim direction or unknown/omitted `as_is_faces`)
- `<joint> forms <feature>, but no check after the join reads its radius band`, `… but its radius check is not a pass (<inspection message>)` or `… but its joined corner is unresolved (<reason>)` (unknown; joined to any claim debt with `; `). `joint_formed` lists each formed feature's `joint`, `feature`, `kernel` status, `credit` and, when checked, `check` and `check_status`.
- `rotary window coverage is unresolved for <face> (<reason>); …` (unknown)
- `faces have no cutting op or as-stock claim: …` (error)
- `rotary windows leave part of a claimed face uncut: <face> (<area> mm² at <setup> z <lo>..<hi> mm, angle <lo>..<hi>°); …` (error; joined to the previous error with `; ` when both apply)
- `every imported face is claimed by a cutting op or declared as-stock.` (pass), or `every imported face is claimed by a cutting op, declared as-stock or formed by a checked joint.` when a joint's credit is used
- `Imported STEP face inventory is unresolved.` (unknown)

Only supported, direction-valid claims earn credit. When every remaining face
has a mapped cutting claim whose turning approach is unsupported on that
machine, the row is `unsupported` with the
[off-lathe turning reason](#turning-scope-and-unresolved-approaches).
Known missing claims and rotary gaps outside that set still error. Invalid
references take precedence. Unresolved claims or as-stock references, followed
by unresolved rotary unions, produce `unknown` ahead of `unsupported` and
missing-coverage errors.

### Rotary union evidence

A rotary op's direction-valid `claimed_indices` name faces its window only
intersects, so they never credit a face by themselves. For each face that
rotary ops claim and no whole-face claim covers, the rule consumes the
kernel's `rotary_coverage.cut` union (see [Approach models](#approach-models)):
a face in `complete_indices` is credited; a face in `gaps` is an error naming
its uncovered area and, per contributing setup, its axial span and enclosing
angular span. An `unknown` union, or a rotary-claimed face the kernel reports
nothing for, stays `unknown` with the face and reason; it never earns whole-face
credit. A whole-face non-rotary claim or an `as_is_faces` declaration of the
same face supersedes its rotary gap or unknown. A gap face is not an
unclaimed face: `unclaimed_faces` keeps only faces with no claim at all, and
`rotary_gaps` (`index`, `ref`, `area_mm2`, `spans`) / `rotary_unresolved`
(`index`, `ref`, `reason`) list the rest.

In a mixed error, `unclaimed_faces` and `rotary_gaps` name only faces with
genuinely missing claims or known gaps, while `unsupported_faces` /
`unsupported_indices` separately name possible lathe-model coverage. An
unsupported-only row's remaining-face list means coverage is not proved; it is
not an absence-of-operation diagnosis.

### Profiled-blank credit

With a [profiled blank](plan.md#profiled-blank), an `as_is_faces` face is
credited only when [`blank_credit`](#blank_credit) credits it. A face it
refuses (off the blank, or a band the vendor tolerance cannot hold) is listed
in `as_is_withheld` and stays unclaimed unless an op claims it (the
`blank_credit` row prints why). An
undecided credit is `unknown`, never a credit. The cite list then adds
`blank_credit: profiled-blank as-is faces on the blank and within bands`.

## `blank_credit`

### Applicability and face ownership

The rule applies only when the plan's stock or a component is a
[profiled blank](plan.md#profiled-blank), identified by its `form` or a `blank`
table. An unknown `blank` keeps the rule, with every credit `unknown`.
It emits one row per exported feature owning an
`as_is_faces` face of a profiled supply, with `faces`: one entry per such face
(`ref`, the kernel's `contact`, `max_gap_mm` and `supplies`, its `owners`, the
`profile_tolerance_mm` it answers to, each band check in `requirements`, and
its `verdict`). A face no exported feature owns is its own row, subject the
face reference. Ownership is identity, never proximity: a feature owns a face
when one of its `faces` references maps to the same imported STEP face. A face
of a bar component in a mixed built-up supply keeps the bar's as-is credit and
has no row. The cite list adds the kernel contact tolerance, each blank's STEP,
digest and tolerance, and the blank's citations.

### Contact and tolerance checks

A face is credited when both checks hold:

1. The kernel's `as_is_contact` puts every sample of the
   finished face on the blank's boundary within `STOCK_TOL` (1e-3 mm), never
   within the vendor tolerance: the vendor cuts the blank STEP's surface, so a
   finished face the blank buries (a chamfer the blank leaves square) is not
   supplied as cut. `max_gap_mm` shows how far off it lies.
2. Every exported requirement of every owning feature
   holds the vendor's ± t (`profile_tolerance_mm`, in the manifest's units)
   about the nominal the blank carries. The tolerance counts only with a usable
   `blank.cite`: an uncited number is no vendor fact, so every credit it would
   decide stays `unknown`. The tolerance is read as vendors post
   it: any cut dimension along X or Y lands within ± t of its nominal.
   - A two-limit length band `[low, high]` with an exported nominal
     (`<requirement>_nominal` or `nominal_<requirement>`, as inspection reads
     it) holds when `low ≤ nominal − t` and `nominal + t ≤ high`; the numbers
     give `low_margin` and `high_margin`. A one-sided band whose nominal is a
     limit, such as +0.50/0, never holds, because the cut may land t past that
     limit: 8.0 ± 0.127 leaves the 8.0 to 8.5 band by 0.127 below. Only a blank whose
     profile (and the finished nominal) sits at least t inside each limit is
     credited.
   - Without an exported nominal only a band narrower than 2t is decided
     (`exceeds`: no centring fits); a wider one stays `unknown`.
   - A BASIC scalar a surface profile governs reads the band every governing
     profile gives it about its BASIC value (their intersection, with each
     profile's disposition, sense and obliquity, as
     [inspection](rules-inspection.md) reads it), checked as a drawn band; a
     looser profile never hides a tighter one.
   - Zones on the face itself combine the X and Y errors into a circle of
     radius t√2. A `position_dia` zone must be at least 2√2·t wide
     (`needed_zone`). A `surface_profile` zone w with U on the material-added
     side (w/2 unstated) must take t√2 on each side: `t√2 ≤ U` and
     `t√2 ≤ w − U` (`added_margin`, `removed_margin`); an unknown U is `unknown`.
   - An angle (`*_deg`), `finish_ra`, `coaxiality_dia`, `angularity_dia`, an
     unrecognised band name, a band with an unknown limit and a scalar with no
     limits stay `unknown`: a length tolerance does not bound them.
   - Every other listed requirement is judged too, never dropped: a `process`,
     `mirror_symmetric` or any value the manifest leaves `"unknown"` is not
     established by a cut tolerance and stays `unknown`; `thru` and an `at` its
     own `position_dia` governs add nothing; a `<name>_ref` reference dimension
     states no limit.
   - A known-empty `requirements` list has nothing to hold; an unknown list or
     identity stays `unknown`.

The check does not add the location error of a machined feature a dimension is
measured from; `inspection` still requires every band to be inspected.

### Findings and remedy

Each distinct verdict is stated once: for the whole feature (`its face …`,
`each of its <n> faces …`) when its as-is faces share it, else after the face
references it applies to.

- `<feature>: its face is supplied as cut.` (pass)
- `… lies <gap> mm off the supplied blank: it is buried in stock, not supplied as cut. Not credited as supplied: cut each refused face with an op, from a blank that leaves machining allowance on it.` (error, check 1)
- `… is not held by the cut: <feature> <requirement>, cut to <nominal> ±<t>, may measure <lo>-<hi>, outside its <low>-<high> band by <m> below[ and <m> above]` (the supply range the tolerance permits, never a claim about one blank; or `… band <low>-<high> is narrower than the <2t> a ±<t> cut may spread`, `… zone <w> is narrower than the <w'> a ±<t> cut needs`, `… surface_profile <w> (U <u>) leaves <room> on its material-added|removed side …`), then the same `Not credited` sentence (error, check 2)

An op cannot restore an undersize face: a face refused here needs machining
allowance on the blank (which then buries it, failing check 1 by design) and an
op that cuts it.
- `… has undecided credit (<reason>).` (unknown: an unknown vendor tolerance, no measured contact, a requirement the tolerance cannot bound, a band without its nominal, or an exported feature whose faces are unresolved and so might own the face)

A face failing either check is not credited: [`coverage`](#coverage) leaves it
uncovered until an op cuts it. Supporting a blank deliberately aimed off the
finished nominal (a one-sided band cut to its middle) needs an authored offset
and a matching check-1 distance; it is tracked in
[#256](https://github.com/pedropaulovc/prechips/issues/256).

## `finish_coverage`

### Applicability and finishing ownership

The rule emits one row per feature. A feature with a known `requirements`
list that neither lists nor declares `finish_ra` is `not_applicable`
(`drawing declares no finish requirement`). An unknown or omitted list, or
an unknown `finish_ra`, is `unknown`. Otherwise every face must be claimed by a
finishing cut. Numbers: `finish_ra`, `required_faces`, `uncovered_faces`,
`rotary_gaps` / `rotary_unresolved` as in `coverage`, and `unformed_caps` when
present.

A claimed hole cap is credited only when its `complete_form` op's
`cap_completion` measured it clear (see [accessibility](#accessibility)). This
holds for the last setup and for any output no setup consumes. A cap that
still touches stock stays uncovered and is listed in `unformed_caps`. An
unmeasured cap makes the row `unknown` unless another face already errors.
A tap's claim never credits a cap its thread's drill left unformed.

### Findings and precedence

- `finish-required faces lack a finishing cut.` (error)
- `rotary finishing windows leave part of a finish-required face unfinished: <face> (<area> mm² at <setup> z <lo>..<hi> mm, angle <lo>..<hi>°); …` (error; joined to the previous error with `; ` when both apply)
- `finish-required hole cap(s) still touch stock after their complete-form cut's setup.` (error)
- `every finish-required face is claimed by a finishing cut.` (pass)
- `finish face references or finishing operation claims are unresolved.` (unknown)
- `rotary finishing window coverage is unresolved for <face> (<reason>); …` (unknown)
- `hole cap completion is unknown: {reason}.` (unknown)
- `turning action has no approach model off a lathe (the turning model needs a lathe spindle on setup Z)` (unsupported)

Unsupported turning finish cuts name possible coverage only: their raw engine
indices never credit a finishing approach. A feature is `unsupported` when all
of its uncovered faces have mapped turning finish claims. A genuinely unclaimed
face still errors, and a complete set of supported milling finish claims still
passes even when other lathe operations exist. Invalid/missing face mappings
retain their error/unknown precedence, and an unresolved rotary finishing
union is `unknown` ahead of `unsupported` and errors. Measurement debt on a
finishing claim is bounded to the faces that claim leaves unresolved: a
feature whose other faces are covered by trusted claims keeps that coverage,
while a reference the kernel cannot bound at all (an unmapped or unbounded
face set) remains a global `unknown`.

### Rotary finishing and as-is faces

Rotary finishing claims credit a face only through
`rotary_coverage.finish`, the union of the finishing rotary ops' window
portions; a rough rotary op contributes to `coverage` only. A whole-face
non-rotary finishing claim supersedes a finishing gap or unknown on that
face. `as_is_faces` never finishes a face, so an as-stock declaration that
settles `coverage` leaves a finishing gap an error.

In a mixed error, `uncovered_faces` names only genuinely missing finishing
claims (a rotary gap face is listed under `rotary_gaps`, not there) and
`unsupported_faces` lists the model-dependent finishing candidates
separately. The error sentence never labels those candidates as having no cut.

## `vise`

### Scope and contact facts

The rule emits one row per setup. With usable kernel facts, a refused join
(`assembly_error`) produces an `error` naming that refusal before holding
applicability is considered. Otherwise non-vise holding (`kind` ≠ `vise`) is
`not_applicable` (`{setup}: vise has no vise grip-zone facts for {kind} holding.`).
An admitted [hand-fed hold](plan.md#hand-fed-on-the-saw-table) is also
`not_applicable` (`hold.kind = "hand_fed"`: the work is fed by hand on the saw
table, and no fixture holds it). Unknown
holding identity or any missing pose/dimension is `unknown` with the job's
reason. With the jaws placed the kernel reports `width_mm` (part extent
between the inner jaw planes), `jaw_separation_mm` (how far the jaws stand apart
closed on it: `width_mm` plus a `jaw_bar` round bar's Ø, plus twice a
`jaw_buttons` button's thickness), `contact_grip_mm` (per
jaw, the merged length of planar part faces lying in that jaw plane within the
zone; where `jaw_buttons` stand between, only the area those faces share with
the button's face, within the jaw's height, measured from the shared area itself
rather than the faces' extents; a line contact is measured when no planar face
lies in that plane), `parallel_pair`
(both jaw planes have planar contact faces) and `claimed_in_jaws` (claimed faces
sharing area with a jaw box). A `jaw_bar` that bears on no jaw-held work along its
length leaves the jaws unplaced. Each `jaw_buttons` button is centred on the one
bore of the work that opens on its jaw face at least as wide as its spigot, its
spigot in that bore; no such bore (or several), a spigot the bore does not take
whole, a button meeting the work beyond the face, a jaw that misses the button,
or a button that bears on no jaw-held work within the jaw's height (a face no
wider than the bore's mouth shares no area with the work round it; touching only
the mouth's edge is not bearing) leaves the jaws unplaced. Numbers: those plus `opening_mm`,
`required_grip_mm`, `parallels_height_mm`. Errors join with `; `:

### Findings and limit

- `gripped faces are not a parallel pair`
- `jaw separation (part width plus any round bar or jaw buttons) exceeds vise opening`
- `both jaws do not provide the declared grip`
- `claimed faces enter jaw solids: <refs>`
- pass: `parallel gripped faces, opening, both-jaw grip and claimed-face exclusion fit the declared vise hold.`
- unknown: `vise contact geometry is unresolved.` or the kernel's reason

Declared parallels are an existence/height input; the rule does not confirm the
parallels were installed, the part was seated, or the vise torqued.

## `thin_wall_under_clamp`

### Applicability

The rule emits one row per setup. With usable kernel facts, a refused join
(`assembly_error`) produces an `error` naming that refusal before holding
applicability is considered. Otherwise an admitted
[hand-fed hold](plan.md#hand-fed-on-the-saw-table) clamps nothing, so it is
`not_applicable` (`{setup}: the work is fed by hand on the saw table; no fixture,
jaw or clamp holds it.`). Holding other than a vise, a chuck (a lathe `chuck_3jaw` /
`chuck_4jaw`, or a `dividing_head` that names its `hold.chuck`) or a
posed-solids fixture with `clamps` is `unsupported` (`{setup}:
thin_wall_under_clamp has no vise grip-zone facts for {kind} holding.`), as
is a dividing head that names no chuck. The exception is a posed-solids fixture
whose `hold.clamp` is `"none"` / `"not_applicable"`, with no clamp members or
debts, in a setup whose every op is explicitly non-cutting (`inspect`, `fit`,
`deburr`, `coating`, `release`, `scribe`, `file_to_line`, `transfer`): it is `not_applicable`,
never `pass`. This applies only after the kernel facts, assembly, holding
identity, numeric frame, in-process stock and fixture pose resolve; each
otherwise keeps its unknown/error row. Clamp prose (even "gravity only"), a
named clamp, an omitted or unknown `clamp` / `clamps`, or any cutting or unknown
action keeps the `unsupported` row. Vise, chuck, dividing-head and drawn/owed
strap loads are not exempted by non-cutting operations.

### Loaded material under jaws and straps

Inside the jaw zone the kernel runs clamp-direction lines through the part on
six Z levels and 8 to 64 columns along the jaws (about 1 mm pitch),
keeps only lines that meet material at both jaw planes (a loaded wall), and
reports the thinnest material interval among them as `min_wall_mm`; no loaded
line is a named debt.

For an angle plate, custom fixture or any other posed-solids hold that
declares `clamps`, each drawn strap loads the stock along its pose's −z. The
kernel takes every flat strap face that faces that force and touches the
setup-entry stock, samples a cell-centred grid on it (4 to 16 per side, about
1 mm pitch), runs a line along the force from each sample and records the
first material interval at the contact as that sample's run; samples over air
are not loaded. `min_wall_mm` is the thinnest loaded run over all straps. A
clamp that is unlisted, unposed or has an unverified/unmeasured solid, and a
drawn strap with no loaded sample, is a named `strap_wall_debts` entry: with
no loaded strap the wall stays unknown with `strap walls unresolved: …`; a
drawn strap's certainly thin run still decides `error`/protective `pass`, but
a run that meets the floor is `unknown` (`drawn straps meet the shop floor but
other clamps are unresolved: …`) while any debt remains.

### Locator-bearing proof

A clamp declared `restraint = "locate"` carries no clamping load. It has no
footprint run and adds nothing to `min_wall_mm`. A pin whose `locates` names a
plan tooling hole also gets a band fit check; see
[tooling holes](#tooling-holes). Each of its drawn solids that
declares `locates` must instead bear on the setup-entry stock the way its
`bears` declares, and only that way: neither proof stands in for the other.
`bears = "bore"` is a radial pin. A convex cylinder of the solid stands in a
concave cylinder of the stock when their axes are parallel, its axis lies inside
the bore and the two overlap along it by more than 1e-3 mm. It bears in a bore
whose full circle contains it and whose actual wall it comes within 1e-3 mm of,
so the drawn contact cylinder has clearance but touches. It may pass clear
through a larger section of the same hole (a counterbore) on the way. Running
past a bore's full circle is not a fault by itself, because that part of the
circle may be a neighbouring relief hole and not stock. Interference is
measured as the stock the solid occupies (below), and the debt names each bore
wall that this stock meets. Its end faces prove nothing: a loose pin resting on
the floor of a blind bore, or a pin standing on the work beside or over its
bore, is not located. `bears = "face"` is a flat locator. It needs a flat face
within 1e-3 mm of the stock whose 0.01 mm slab, swept along its outward normal,
meets more than 1e-6 mm² of it. Either way the solid shares no more than
1e-3 mm³ with the stock. Another member touching the stock (a collar on the
work) proves nothing. The kernel lists each proof under `locator_bearings`: the
clamp, the solid and `bears`. A `bore` proof records the pin and bore
diameters, the axis offset, the gap and the engaged length; a `face` proof
records the face's area. Each of the following is a named `strap_wall_debts`
entry, like a non-bearing strap:

- a locator with no declared `bears`;
- a pin that stands in no bore, or stands clear of every bore it stands in;
- a flat locator with no bearing face;
- a locator that shares more than 1e-3 mm³ with the stock (an oversize pin, or
  one off its bore's axis that runs into the wall);
- a locate clamp that draws no `locates` solid (an unmeasured locating solid is
  not drawn).

### Exact batched line queries

Separated parallel footprint lines from one clamp may meet the entry stock in
one exact native compound intersection. Their segments and Boolean operand order
are unchanged, with no fuzzy tolerance. Supporting lines must be more than
`4 × PLANE_TOL` apart. The returned shape must be valid and its maximum native
tolerance, including vertices, strictly below `PLANE_TOL` (1e-6 mm); every
straight returned edge must belong to exactly one original finite segment within
that precision. Every sample, raw interval, loaded/air row and minimum remains
individual. This partitions native edges, not an approximate material model.

A near/coincident line, unsupported or ambiguous edge, invalid result or failed
optional batch makes that whole clamp run its original queries serially in their
original order. Serial query errors are never caught. If gathering a footprint
fails after prior points, those prior queries run first, preserving the earlier
native error's precedence. The per-piece press-clamp load-path queries remain
individual. P6 accepts a successful exact batch where an individual solve might
have raised; numeric equivalence is checked against native scalar intervals,
not inferred from the partition gates alone.

### Policy floor and findings

The rule compares the wall with `shop-policy.numbers.thin_wall_floor_mm`.
A `numbers_verify` flag that is true or unknown leaves the floor unknown.
Numbers: `min_wall_mm`, `thin_wall_floor_mm`, `method` and, when present,
`strap_wall_debts`.

- wall ≥ floor: `minimum wall inside the grip zone meets the shop floor.`
  (`under the strap footprints` for strap holds) (pass)
- wall < floor and `hold.method` is one of `soft_jaws` / `soft jaws` / `mandrel` / `wax` (case-insensitive): `wall is below the shop floor with a named protective holding method.` (pass). Tape is a typed area hold (`hold.area`, [plan](plan.md#hold)); `method = "tape"` is bad input.
- wall < floor, unknown method: `wall is below the shop floor and protective holding method is unknown.` (unknown)
- wall < floor, other method: `wall is below the shop floor; name soft jaws, mandrel or wax, or hold it by area (hold.area).` (error)
- otherwise `grip-zone wall thickness or shop thin-wall floor is unmeasured.` (unknown)

The [example policy](../examples/shop-policy.toml) declares
`thin_wall_floor_mm = 1.5` with its `numbers_verify` entry false. Its citation
identifies this as an illustrative value, not a shop measurement. An omitted,
unknown or flagged floor in your policy remains unresolved.

## `fixture_interference`

### Scope and collision tests

The rule emits one row per setup for holding kinds the kernel draws: vise,
chucks, dividing head, dead centre, angle plate, custom fixture and clamps.
With usable kernel facts, a refused join (`assembly_error`) produces an
`error` naming that refusal before holding applicability is considered.
Otherwise an admitted [hand-fed hold](plan.md#hand-fed-on-the-saw-table) draws
nothing and is `not_applicable`. An unresolved hand-fed scope keeps the
unknown holding row. With fixture components placed on setup-entry stock,
the kernel checks:

1. every drawn component against the entry stock;
2. every pair of drawn components from different owners. An owner is one
   authored `solids` list (a fixture's, a clamp member's, a dividing head's,
   with its `void`s cut away), the generated chuck (jaws and body), the
   tailstock (centre and quill), each vise jaw, each parallel and each riser
   block. Vise jaws against parallels and risers are left to check 3;
3. for a vise, each parallel and riser block lies inside the jaw opening
   closed on the stock (the gripped extent along the clamp axis, within
   0.001 mm).

Contact is allowed: a clash in checks 1 and 2 is common volume above
0.001 mm³, so a part on its parallels, blocks on parallels, a strap on the
stock and on its heel, or a stud in a modelled clearance or tapped-hole
void stays a contact. A stud with no hole drawn in the plate it enters is a
clash; model the hole as a `void`. Numbers: `clashes` and `undrawn`.

### Findings and limits

- any clash: `fixture interpenetrates the work or another fixture: <clashes>.`
  (error, even with undrawn components). Each clash names
  `<a> interpenetrates the setup-entry stock (<v> mm^3)`,
  `<a> interpenetrates <b> (<v> mm^3)` or `<accessory> spans <axis> <lo>..<hi>
  mm, outside the jaw opening <axis> <lo>..<hi> mm closed on the stock`.
- no clash but an undrawn component (an unposed or unverified clamp,
  unmeasured solids or supports, undrawn parallels or riser blocks, an
  unplaced holding or vise jaws, a component reaching a possible-jaw strip):
  `drawn fixture components only touch; unresolved: <debts>.` (unknown)
- otherwise `every fixture component only touches the stock and the other
  components.` (pass)

Unknown in-process stock, frame or hold inputs stay `?` as for `vise`. The
rule checks declared geometry only: it does not prove the clamp sequence,
torque, or that the shop's real fixture matches its record.

## Renders

### Camera, image size and repeatability

For each setup with a numeric frame and derivable incoming stock, the kernel
returns a PNG 1600 pixels wide. Its height depends on the semantic print panels.
The camera uses setup axes:

| Setup | View |
|---|---|
| Lathe | Elevation with +Z right, radial +X up and +Y away; headstock and chuck left, tailstock right. |
| Mill | Front-right isometric. |
| Custom plate | Plan view down setup -Z. |
| Custom fixture on a bench or saw | Elevation section across the stock's longer horizontal side, through the middle of the holding that touches the work, or the stock centre when none does. Buttons, saddles and pins are sectioned to show contact. `render_scene.section` records `axis` and `at_mm`. |

The engine's orthographic z-buffer rasterizer, bundled bitmap font and PNG
encoder use no installed fonts, timestamps or machine-specific metadata.
The rasterizer is deterministic for its render inputs, and a cache hit
returns the stored render bytes. This does not establish byte-for-byte
repeatability of independently recomputed native geometry or render facts;
see [cache limits](#cache).

### Render-only saw guides

A hand-fed cut's saw side is drawn as render-only context. The host sends
`guides.boxes`, each a `name`, a
`label`, a `colour` (`saw_table`, `saw_blade` or `push_aid`) and either `box_mm` (a
setup-frame box) or `stock_mm` (per axis, two `[anchor, offset]` ends, `anchor` the
`min`, `mid` or `max` of the setup-entry stock box). The kernel draws each as a box with
its own callout, lists it in `render_scene.components` with role `scene`, and never
hit-tests it; a malformed box, or a stock-anchored one without entry stock, is a
picture debt only. The op's profile sketch prints a waypoint marked `plain` as written
(SCRIBED LINE, WASTE, KEEP) instead of a P number, and names the arrows of a `feed`
path "ARROWS: WORK FEED INTO THE BLADE": they run the way the work moves, from its
trailing end toward where the blade enters. A path with a `waste_xy`
point is a line that cuts waste off the setup-entry blank: the sketch draws the
blank's XY outline (`stock_box`) as a thin line, the path as the one heavier line, and
shades the part of the blank the path cuts off on `waste_xy`'s side, its run inside the
blank closed by the blank's outline. A path that does not cross the blank from edge to
edge, or a `waste_xy` in neither part, shades nothing. The blank, the line and every
other sketch item go through the panel's one XY transform from their setup-frame
coordinates: nothing is fitted to the box. A path marked `arrows_only` draws only its
direction arrows, clipped to the blank's outline, never a line: the hand-fed sketch
puts its feed arrows 3 mm into the waste beside the scribed line. A `hidden` path is not
drawn; with `ends` (two labels) the sketch keys where it enters and leaves the blank's
outline (its own end points where it starts or stops inside), drawn with its
`end_marker` (`square` or `cross`; a dot when absent): the hand-fed sketch keys its saw
path's crossings ENTER and LEAVE with crosses and the scribed line's own ends LINE END
with hollow squares. The hand-fed sketch draws only the scribed line this way (no
separate saw path: the 0.45 mm leave is not visible on a 290 mm arc), keyed SCRIBED
LINE, "WASTE: SAW HERE, 0.450 MM MIN OFF THE LINE" and KEEP; a `feed_from` that is
undeclared or names no end of the line draws no arrows, ENTER or LEAVE.

### Render-only guided-sweep hardware

Guided-sweep table-side elements are drawn for the operator but do not model
holding. The host sends an arc sled's rollers in the
setup's render annotation (`guides.rollers`: setup XY axis `at_mm`, `dia_mm` and
`z_mm` from the table to the roller top), each at the rail radius plus or minus its
radius (`rail_side`) about the arc centre, at its `rollers_deg` from the cutter's
radial line, the table at the work's seated bottom (`retained_rail_bottom_z` when
below `bottom_z`, as `headroom` reads it; an authored but unknown one leaves it
unknown) less the parallels or support blocks under the work (the height the
`headroom` stack counts) and the fixture's `bed_height`. The
kernel draws them as cylinders in the guide colour with one `GUIDE ROLLERS
(TABLE)` callout per op (`GUIDE ROLLERS (TABLE, OP n)` when more than one op in the
setup has rollers) and lists them in `render_scene.components` with role
`guide_roller`; they never join the fixture components, so no checkpoint, clash,
contact, clearance or `fixture_rendered` verdict reads them, and a malformed roller is
a picture debt only. The isometric view widens to frame each op's rollers within one
stock size of the work along each of X, Y and Z; rollers farther off would shrink the
work unreadably, so they are not drawn in the picture or its holding details and a
`NOT SHOWN` note gives the setup X/Y/Z span
they stand in, and
another op's nearby rollers stay framed. A
roller fact that is missing or not measured, a sled flagged to verify, a negative bed
height, an inner roller as wide as the rail's diameter (no inner tangency exists), or
a support with a negative height, or one
under the work that is unknown or flagged to verify (item or height, as `headroom`
leaves that stack unresolved), leaves the rollers undrawn with a `NOT SHOWN` note
naming each gap (a measured fact with its `measure:` instruction). A swing arm's pivot post stands at the arc centre, far
off the part, so a note names where it stands instead of drawing it. A trammel's
rails (`guides.rails`: `from_mm`/`to_mm` along each rail's centre line from the
spindle axis over its measured `rail_travel`, `width_mm`, `z_mm` table to rail top)
and carrier pins (`guides.pins`, cylinders at their places on the carrier from the
rail tops to the work's seat) are drawn the same way, render-only, with `TRAMMEL
RAILS (TABLE)` and `CARRIER PINS` callouts (per op, as the rollers') and roles `guide_rail` and `guide_pin`;
a missing or unmeasured `pin_dia`, `rail_width`, `rail_height`, `bed_height` or
`rail_travel`, or an unknown support height, leaves them undrawn with a `NOT SHOWN` note.
The carrier plate (`guides.carriers`, a box centred on its pins' chord, `carrier_length`
along it and `carrier_width` across, from `carrier_thickness` below the work's seat up
to it) is drawn the same way with a `TRAMMEL CARRIER` callout and role `guide_carrier`;
a missing or unmeasured carrier fact, a plate shorter than its pins' chord or one too
thick to clear the rail tops leaves only the carrier undrawn, with its own note.

### Stock, removal and fixture annotations

Blue-grey is material retained after the setup; amber hatch is the Boolean
difference between actual entry and derived exit stock. When exit stock is
unresolved, only the arriving stock is drawn and the missing cuts are named
plainly. Fixture role colours, labels, setup X/Y/Z, Z0, named datum ends,
jaw-front Z, stickout and a selected-tool approach illustration accompany the
geometry. The footer sizes the arriving stock: round stock (a solid of
revolution about setup Z on a lathe, else about a box axis with a square
cross-section, checked at six meridians) prints `STOCK Ø` its largest diameter,
its length left to the stock dimension; only other stock prints `STOCK BOX: X / Y
/ Z`. A stickout from a measured fit-up (`hold.stickout_fit` with a stated
reading) is dimensioned `NOM STICKOUT … mm` and the setup notes say it is set as
the measured fit-up + N mm. When no jaw-front stickout dimension is drawn, its
annotation uses the upper dimension-label row, clearing the stock-length label
at full body size; it does not use a dimension-line coordinate as its text top.
Steady rest
rings are drawn as fixture solids; each follow rest's
jaws are drawn and labelled posed for the first cutting sample of the first
op it serves. An exposed-end detail makes short lathe stickouts legible; when
its point keys would sit closer than their badges need (a jaw-end dome), it is
enlarged until they stand apart, as in the shaft's S2 and S3. Contour
sketches show both sides and share `P` waypoint keys with the coordinate
tables. Custom plates show pads, locators and authored clamp-action order.

### Finished-outline painting and geometric bounds

For every profile operation with a positive XY span, the separate paint-only
finished-outline stream requests model-space deflection at most `0.5 / S` mm. Here
`S = min(4W / max(sx, e), H / max(sy, e/4))`, `W = 1464` px is the full-width
plot, `H = 1792` px bounds its print band, and `e = 1e-9` mm is the renderer's
numerical span denominator. This covers the largest possible sketch scale,
including fourfold Y exaggeration: even when `0 < sy < e`, the stretched scale
is bounded by both `4H/e` and `H/sy`. Across operations the largest `S` supplies
the bound. There is no fixed physical deflection floor or small-positive-span
exception; only coincident points (or no finite points) supply no sketch bound.
An unrepresentable span from finite coordinates is refused, not treated as
coincident. The guide-axis detail bound still limits the request to `0.5 / 324`
mm, including when no profile sketch supplies a bound. The native adapter sends
the smaller of these bounds and its ordinary rendering tolerance directly to
`edge.discretize(Deflection=...)` for the fine painting stream; it never retries
with a coarser tolerance.
A native discretization exception propagates out of setup rendering to
`run_job`, which returns `status: "error"` and its reason, without a PNG or a
successful cache entry. These are bounds on the requested deflection, not an
independent geometric certification of the vendor's returned polyline. Extremely
small spans can demand precision the native kernel cannot support; that native
acceptance remains separate from the mathematical scale bound.
The render spec captures two streams from the same finished-face edges in the
same insertion order. `nominal_outline_mm` retains the ordinary
`Deflection=tolerance` samples as the sole nominal input to viewport fitting,
bounds, layout, badges and leader selection. `nominal_render_outline_mm`
uses `min(tolerance, _nominal_outline_deflection(sketch, waypoints))` and is used
only to paint the outline in setup/isometric/section views, guide-axis details
and profile plots. A spec with nominal geometry must provide the fine field;
missing fine data is an error, never a fallback to legacy drawing data. A spec
without nominal geometry remains legitimate.
In each painted plane, duplicate and collinear-overlapping fine chords are split
and de-duplicated before dashing, preserving phase along the unique contour.
The spatial index retains the deterministic topology without an all-vertex
quadratic scan.
Leader placement uses ordinary-tolerance nominal geometry: the original
primary nominal point assigns its lane, and the ordinary vertices supply the
finished-outline leader candidates. This includes the guide view's original
projected vertices and primary point, even when they lie outside its viewport.
Fine samples never feed layout or anchors, although their chord geometry and
dash phase can differ. There is no native-only selector, crossing filter,
interior fallback or new landing debt. Tessellation accuracy and leader
placement remain separate concerns; the leader work tracked in
[#211](https://github.com/pedropaulovc/prechips/issues/211) is not implemented
or waived by the painting stream.
Table/vise-body/headstock/tailstock context outlines are marked schematic;
they never add fabricated solids or authorize a cut. Inventory stop solids
require `hold.stop_fixture` and a numeric `hold.stop_pose`.

### Text size and complete print bands

Every label is at least bitmap body scale 5 (35-pixel cap height, approximately
11.8 pt at 1600 pixels across 7.5 inches); this is not a CSS font size or physical
printer certification. The renderer refuses smaller text. Setup notes come from the setup's declared ops,
bench actions included, so a deburr/coating/inspect setup says it has no
machine cutting rather than "no material removed".
Existing sketch captions wrap within their measured owner width at the same
body type size, with line-height space reserved for every caption line. This
changes layout only, not caption wording, coordinates, units or schema.
The complete setup view, dimensions, leaders and setup-axes key remain together
in the first band. If the measured key or setup-note rows exceed that band's
remaining height, its fitting prefix stays there and the remaining rows continue
in measured full-width bands owned by the same `setup` role, explicitly labelled
`KEY + NOTES (CONTINUED)`. Legend text reserves a measured 60-pixel inner gutter
before the notes column; body type, row order and key/sample associations are
retained, with no row dropped, duplicated or cropped.
These text-only continuations precede the independent sketches, holding and guide
bands and share their 1792-pixel limit and exact-once canonical-image coverage.
They do not invent another geometric view or repeat the first figure's stock
caption. Setup geometry and label lanes that themselves exceed the printable
bound are still refused truthfully.
Band boundaries keep logical legend entries and notes whole whenever one entry
fits a full text band. An entry longer than a whole band alone is continued at
complete wrapped rows, identified by the source-entry ordinal (`LEGEND ENTRY 01`
or `NOTE 01`, with `(CONTINUED)` on later fragments). These are layout identities,
not new physical drawing keys. Their headers wrap with measured space reserved;
substantive text still appears exactly once.
The constructor measures a setup-specific continuation header only when the
footer actually overflows. Primitive sketch callers whose text already fits keep
their existing no-setup-identity construction contract; rendering a complete
setup still requires its declared setup identity.

#### Setup-band fitting

Ordinary fitting setup bands keep their existing axes reservation and layout.
Only when that conservative reservation would refuse a label-lane growth does
the renderer paint the same complete axes key into its primitive-extent measuring
canvas, retaining stroke/arrowhead/circle extents and full body cells plus the
existing bottom padding. This measures space, not geometry or a smaller font.
If the next growth estimate exceeds the resulting real paper budget, the original
scene is laid out once at that maximum budget: moving its existing obstacles can
make the earlier estimate non-minimal. Acceptance requires actual zero lane
overflow and complete body-text bounds; a still-overflowing maximum attempt
refuses immediately, without cropping or reusing a partial candidate. The same
leader algorithm remains in use, although its resulting routes can move with the
existing obstacles. A refusal names the private layout owner/setup/view and its
forecast, attempted/maximum budgets, measured axes minimum, remaining overflow
and pixel height/cap; these diagnostics are not physical facts or a public schema.

#### Annotation-detail fitting

Main-picture lane fitting and annotation-detail fitting have separate owners.
An annotation detail measures its own rendered inset and callout overflow, grows
that band within the 1792-pixel bound and retains the fallback from a two-op band
to complete single-op bands. It never grows the main picture to fit detached
annotations. An oversized complete single-op band is refused. Final composition
adds fitted annotation, holding and guide bands once, preserving `CUT` keys and
settled rendering debt.

### Visible leaders and hidden datums

A leader that names a drawn solid (the stock, a jaw, a parallel, a clamp, a
numbered clamp or pad badge) ends on that solid's own visible pixels, never on
its bounding box or on whatever lies in front of it. When no pixel of the named
solid is visible the leader is not drawn and the picture carries the render
debt `NOT SHOWN: <label> is hidden in this view, so it has no leader.`, printed
in its own notes; a hidden numbered clamp or pad, or a hidden vise jaw (a bar
held on edge stands above its jaws and hides the rear jaw from the isometric
camera), with a known box is instead drawn as a dashed outline of that box, its
leader ending on the outline at an open ring, so its position still shows
without pointing at the solid in front. A hidden parallel stays a render debt.
An isometric view calls out the holding that touches the stock; a vise jaw
that presses the work through it (the moving jaw behind a `jaw_bar` round bar,
called out as `ROUND BAR`) is holding too, as are `jaw_buttons` (called out as
`JAW BUTTONS`), each between the work and a jaw.
Triangles that share an edge cover every pixel centre on it exactly
once, so a solid wholly behind another never shows through its seams. A datum's
authored face name keeps its words but its axis words are restated in the
setup's axes through the setup placement (the rocker's model "+Z broad strap
face" is "-Z broad strap face" in a setup that turns the part over; an axis
that lies along no setup axis is dropped). A datum face whose normal points
setup -Z is labelled `UNDERSIDE`; one turned away from the camera is labelled
`HIDDEN` and drawn as a dashed outline with a dashed diamond marker, never as
the face in front.

### Holding contacts and detail views

When holding touches the stock and the main picture draws the stock's narrower
side under 200 pixels, a holding-detail band is printed below the picture.
The kernel computes contacts from the exact solids: each holding
solid within the stock tolerance of the work gives the outline of the shared
face (or the section edges, else the nearest point). Where several points are
equally near (a diamond pin is as near its hole along each land's edges), OCC
lists them in an order a boolean's last bits change between runs, so the kernel
keeps the highest, then least Y, then least X, rounded to six places; the closest
cut's end points are chosen and rounded the same way. Its plane is measured on
that whole contact before a section view cuts it: the outline is cut where it
crosses the section plane and only the kept side is drawn, still keyed at the
contact's own plane (a contact that is a point or a straight line names no
plane). `closest_cut` is the least of the setup's `cut_clearances` (below) and,
on a saw setup, the blade's path. The detail frames the stock, the contacts and that
distance; it outlines each contact (solid where seen, dashed where hidden),
keys it with its holding name and the setup coordinate of its plane (a support
whose solids lie on different planes, such as the rocker's hub stand and rail
shims, is keyed plane by plane, and same-named solids share a key only on one
plane). A numbered support (a coded clamp such as `SUP1`, or a pad) on one plane
keeps its position badge; one whose solids seat the work on several planes keys
each solid with its code, its own name and its plane, led to its own contact,
and pad keys at several heights name the pads each keys. It dimensions the
closest cut in amber (`render_scene.closest_cut`: `mm`, the holding `tag`, the
two end points and the `op` whose cut it is), the same value the CLEARANCE table
prints for that op, keyed `CUT <mm> mm FROM <holder> (OP <op>)`: never from the
falling offcut of a saw setup, whose blade path is each saw op's kerf slab on its
cut plane, across the stock and holding (`blade: true`, its saw op named, else
keyed `(SAW BLADE)`). A cut whose op is unknown or absent names no op (and its
consistency check is unknown).

### Cut clearances

A mill or bench picture also carries `render_scene.cut_clearances`, one
`{op, mm, tag}` per op, which the
CLEARANCE table prints op by op and each op's crash box checks within 3 mm (a file
to keep clear of the solid, a cutter to hand feed past it). A machine op's is the
nearer of two distances to the nearest holding solid. One is its whole tool (the
cutter to its flute length, a body at the larger of the cutter and shank radius to
the shank's start, the shank to the projection and the holder over its gauge
length) swept over every move it is commanded through: each pass or outline of
its coordinates tables (`tool_paths`) at every Z level, over the whole span it
covers (a path doubling back along its line reaches its far point, not just its
ends), each end standing up to the op's start Z (its level plan's start, else the
entry surface its profile names on the DRO grid; never its own depth) or a
raster's lift Z, a one-way raster's rapids at the lift Z, each printed arc-table
checkpoint path at every level, and each hole, drill/spot/ream joint or
centre-drill plunge from above the stock to its tip (a pointed tool's cone, a
centre drill's own profile at its true outline, not the inset one that tests its
cut). The other is what the op takes off (its
before-op stock less its after stock): the cutter goes wherever that material is,
whether or not a printed path leads it there. A bench file's is what it takes off
to the nearest holding solid but its own guide stops; a file that takes nothing
carries no row. `mm` and `tag` are `unknown` for a move or tool dimension the
kernel is not told (an arc table that reaches it as no checkpoints, a raster or arc
reason, a start Z the tables do not give, an unmeasured shank), for the cut that
stopped the stock builder and every
later one, for a guided file that reaches a kit solid it may stop on when the kit's
rim band is unknown (below), and for every op while the holding is not drawn whole (any
`render_scene.debts`: an unresolved fixture, an undrawn component, an undeclared
jaw extent), since what is not drawn may stand nearer than anything drawn;
`closest_cut` is then None, so the picture never dimensions a value the table calls
unknown, and the table says to check at the machine.

### Raster sketches and detail scale

A path sketch draws every pass of a raster of
at most eight passes, labelled `PASS 1` … `PASS n` as the pass table numbers
them (a longer raster is a band with its first and last pass), each with a
direction arrow when the table gives a cutting sense; its `ARROWS: POINT ORDER`
legend prints only when an arrow is drawn. The raster cycle is one way, so
each lift and rapid back from a drawn pass's end to the next pass's start is
dashed in the op's colour under `DASHED: LIFTED RETURN`, and a return never
reads as a cut; a band showing only its first and last pass draws none. An
isometric or elevation view is detailed only when the band draws the stock at
least 1.5 times larger; when framing the whole stock cannot, the band is a
window on the holding that touches it (its contacts and the whole of each
component making one: both of the rocker's hub buttons and the stud the vise
grips), titled with the stretch of the work it shows (`SETUP X a TO b`), and is
drawn when that reaches 1.5 times. A lathe's meridian section gets no holding detail. A
plan view always gets the detail, drawn from 30° above the side so contact
heights read, and long work is split along its length into at most two bands,
each keying only the contacts in its share. Bands grow taller rather than
shrink or drop a key; the scene's `height_px` is the delivered PNG's height.

### Waypoint keys and number rounding

A path sketch keys its waypoints and passes in badge rows above and below the
plotted geometry, never over a path: each row keeps its points' left-to-right
order directly over or under them, so the short leaders fan out without crossing,
and neighbouring points on the geometry's middle band alternate between the
rows. A plot under 24 pixels deep at the scale its width allows is stretched in Y
by a whole step, x2 to x4, and says so (`Y EXAG x2`). The picture grows to give
the rows and panels their room rather than shrink a key or drop one. A key
lane's leader to a fixture ends at that solid's visible edge nearest the lane,
crossing as little of the work as it can and no other key's point; lane leaders
run square, in their keys' order. A named void at numbered positions (a slot
under each pad) is keyed by the position badges, `PAD SLOTS AT L1-L6`, and gets
no second leader into a badged point. A split key names each point it leads to.

Holding-detail keys print a contact's plane on the setup's DRO grid
(`dro_step_mm`, the step the fixture tables print positions at), rounded as the
tables round (half a step away from zero, float noise in the quotient not
counting; one shared rounding), so a key reads as the DRO is set and as the table
prints it. Closest-cut and clearance distances are measured values and never snap
to the grid; `closest_cut.mm` and its end points are rounded as the CLEARANCE rows
are (six places).
Every decimal a picture prints (DRO values, clearances, sizes, a band's gain) and
every fixed-decimal number on the sheet goes through one rounding,
`render_diagram.decimal_text`: the float's written decimal, a half-way value
rounded away from zero (2.8045 at three places prints 2.805, never 2.804), so a
picture and its table never print one value two ways.

### Guided-file stops and guide-axis views

A guided bench file (a hand op whose `guide.buttons` kit is held in the setup,
its solids named to the kernel by `guide_owner`, the diameter band the kit's rims
stand at by `guide_rim_dia_mm`) is not a cut to clear. That band is twice the radius
band the buttons file to worst case over the kit's declared stack ([rules-coordinates
filing buttons](rules-coordinates.md): the button OD limits widened by the rim
centre's shift off the bore axis), the band the traveler prints, proven exactly as the
manual-arc rule proves it; a button drawn at its nominal OD is in it even when its
bought OD band (a fit class such as g6) excludes the nominal.

Guide selection compares resolved kit identities, so a fully qualified
`fixtures.<kit>` reference and its short identity select the same held kit.
The emitted `guide_owner` retains the actual held fixture or clamp label;
identity normalization does not rename the scene's component owners.

A kit solid is a stop
only when it is a button of that band (an external rim: a convex cylindrical face
within the band, widened by the stock tolerance; a bore of the band, as in a nut, is
no rim), its cut reaches it, it is seated on
the filed face (within the stock tolerance of the stock the file leaves, without
biting into it), and that rim sets the filed boundary: the rim's cylinder, run along
its axis, touches the cut where the cut meets the stock the file leaves and nowhere
enters the cut. A button of the band whose rim stands over the unfiled wall is no
stop. Stops are classified per file: one file's stop never decides another's. Each
file's stops are left out of its own `cut_clearances` row only; the picture keys every
file's stops once, named in `render_scene.guide_stops`, and `closest_cut` is the least
of the rows: no `CUT 0.000 mm
FROM` a filing button prints. Any other kit solid the cut reaches (a stud, a tab
touching the unfiled wall, a square block, a nut whose bore stands on the filed face, a
cylinder outside the band) is holding to clear and keeps its real `CUT` dimension.
When the band is unknown (the kit or any stack fact flagged to verify, any stack
element unknown, or a pin that may not enter its seats), a kit solid that would be a
stop but for the band, or whose seat test fails its boolean, may be the file's stop:
whether the file bears on it is unknown, so that file's row is `unknown` and
`closest_cut` None, never a pass and never 0 mm to a button, even when an earlier file
of known band stops on the same button. The detail keys
them in green: `FILE STOPS ON BOTH BUTTON RIMS` for a matched pair, or one key
per rim, `FILE STOPS ON UPPER BUTTON RIM`, when they lie apart. A real clearance
to the rest of the kit (its stud) is still dimensioned: in the holding detail when
one is drawn and keys it, else on the setup picture itself, so a picture never
drops its `CUT` dimension because the detail band is not drawn. When the stops are turned
solids on one axis that the setup picture does not already look along (within
cos 0.99), a guide-view band below the detail looks down that axis, enlarged
(`VIEW ALONG THE BUTTON AXIS X14.6`, with the setup axes it draws right and up).
It outlines the rims in green with their stop key, hatches `STOCK TO FILE OFF`
inside the `FINISHED OUTLINE`, draws `FILE AT ITS STOP` flat on the rims, and
draws a `FILE APPROACH` arrow coming in square from beyond them. It keys the kit
as the setup picture names it (`render_scene.guide_axis_mm`: a point on the axis
and its direction). When the stops lie at different heights along the axis, the
kernel sections the view between them, half way unless that plane would miss most
of the stock to file off, so the near button does not hide the work and the cut
face shows what the file takes; the band notes `SECTION BETWEEN THE RIMS`.

### Inspection views

An inspect op's `inspection_views` ([plan](plan.md)) are drawn as one setup
sketch per requirement, a band per view, on the stock as the setup's route stands
at that inspect op: after the last op before it that the kernel cuts (the job's
inspection `after`, that op's subject, or the arriving stock when none precedes
it), never the stock later ops leave. Only the pieces of it that hold the part
are drawn: scrap a cut before the inspection released, such as a rail frame, is
off the part when it is inspected. It is drawn in the
part model's own axes: `up` up the page, seen from `toward`. The bands are
returned as `inspection_pngs_base64` keyed `<op>:<requirement>`, apart from the
setup picture. Each band titles its view, wrapping a title too long for one line
and moving the band down under it, and draws a hatched `SURFACE PLATE` line
under the lowest solid. It keys every aid by name, on the aid's own visible
pixels (each aid is drawn under its own tag, so an aid named like the work never
borrows the work's pixels), and every mark at its point. A `reads` mark is green with a `+` arrow up
the page, the way that orientation's height reading rises, under the note
`+ ARROW: THE WAY A READING RISES (A HIGHER CONTACT READS +)`; other marks are
red contacts. What a sketch cannot show is a render debt on the setup's
`render_debts` (`op <op> <requirement> sketch: NOT SHOWN: …`): an aid hidden in a
view, or the whole sketch when the stock at its place in the route is unresolved.
Each complete authored inspection view remains one 1600-pixel-wide band, at most
1792 pixels high. Native `inspection_scenes` carries its canonical PNG's actual
`width_px`, positive `height_px` and `print_panels` under the same exact
`<op>:<requirement>` key. Each ordered panel records `top_px`, `height_px`,
`role = "inspection"`, the exact authored title as `label` and its 1-based
`view_ordinal`. Panels cover the PNG contiguously and retain all authored views.
The traveler moves each view as a whole figure attached once to its original
note or worksheet; it does not infer view boundaries from pixels.

### Render scene and report binding

Alongside the image the engine returns `render_scene` with `fixture_kind`,
`jaws`, `parallels`, `components`, `debts`, camera and resolution, plain-language
`shows` / `legend`, annotation-only `render_debts` and shared `waypoints`.
Actual PNG dimensions are `width_px` and `height_px`. Ordered `print_panels`
records `{top_px, height_px, role, label}` partition that canonical image into
full-width contiguous bands covering every pixel exactly once. Roles are
`setup`, `profile_detail`, `path_detail` and `holding_detail`. The traveler uses
these semantic windows at a common print scale, with panel/setup identity;
there is no arbitrary whole-image crop, fit or downscale fallback. Panel
presentation preserves coordinate units, geometry and visible rendering debt.
`fixture_kind` is the inventory holding kind; `components` lists every drawn
solid as `{name, role, exact}` (`exact = false` only for the vise's
lateral-undeclared jaw extents; a follow rest adds role `follow_rest` and the
`pose` it is drawn at, and a rest no served op posed is a debt). For a vise, `jaws` is `absent`
(unplaced; debt `jaws not drawn: <fixture reason>`), `exact` or
`lateral_undeclared` (debt `jaw position along <axis> is undeclared (no
jaw_center_along_mm): dark jaws span only the part's <e> mm grip-zone
extent; light strips show where the other <w−e> mm of each <w> mm jaw may
lie`); `parallels` is `absent` (no usable hold inputs: unresolved holding
or a vise with dimension/pose debt, debt `jaws not drawn: <fixture
reason>`), `exact` or `not_modelled` when selected parallels lack accepted
dimensions or numeric centres. For example, missing width and centres produce
`parallels not drawn: parallels_width_mm, parallels_centres_mm undeclared`.
The current rocker plan declares centres, and its selected shared parallels
record declares `width_in = 0.125`; that missing-input example does not describe
the current rocker configuration. These authored example inputs do not
establish physical installation. For a chuck or
dividing head `jaws` is `exact` once placed; jawless kinds report
`not_applicable`; an unplaced non-vise fixture is `absent` with debt
`fixture not drawn: <reason>`. Further debts name an undrawn possible
obstacle (`not drawn: …`), a strap that does not bear on the stock top, a
fixture body that touches neither the stock nor a clamp member joined to the
stock through touching members, a solid that intersects the entry stock, or
unequal scroll-chuck contact
radii. `fixture_rendered` is true only when the fixture is placed, at least
one component is drawn, every component is exact and the debt list is
empty. Everything else
is a partial picture with its debts spelled out; a stock-only or envelope
picture is not a holding proof. Non-derivable stock produces no figure. How
the file is named, hashed into the
report and captioned is in
[report binding](report-and-telemetry.md#kernel-renders).

## Limits

### Holding and machine scope

- Lathe setups: `vise` is `not_applicable`. For every placed chuck, on a
  lathe or carried by a dividing head on any axis, `thin_wall_under_clamp`
  samples, in the chuck's own pose frame, the shortest inward material run
  under each jaw through the grip zone (`min_wall_mm`): a solid bar's run
  crosses the full diameter, whereas a tube's run measures its wall. Collets
  supply no jaw solids.
  Turning rows follow the sampled necessary-condition model above; it proves
  no tool path. Lathe `headroom` checks stock OD and chuck body diameter against
  measured swing over the bed, stock OD against swing over the cross slide,
  and stick-out (else declared stock length) plus chuck body length against
  distance between centres; no carriage stroke or tailstock extension is checked.
- A vise grip and opening verdict needs `jaw_height`, `jaw_width`,
  `jaw_depth` and `opening` facts without their own debt. Jaw placement seats
  the work at its lowest Z. An exact along-jaw pose requires
  `jaw_center_along_mm`; parallel solids require `parallels_centres_mm` and
  accepted height, length and width facts. Missing pose inputs leave an
  envelope or part-only render with named debts.
  The example vise records jaw dimensions and opening in measurement
  records. The shared example parallels declare width, and the rocker
  preparation setups, S1 and S2 declare their centres.
  See [example provenance](../examples/README.md) before treating any such
  record as a shop measurement. Chucks, heads, centres, clamps and authored
  solids use the same fact-local trust rule: required dimensions and poses
  must resolve, never default. Collets, soft-jaw profiles and toe clamps
  without authored `solids` are not drawn.

### Sampling, completion and measurement limits

- Accessibility and reach are sampled/projected measurements with a fixed
  grid, not full swept toolpath simulation; a feature narrower than the
  sampling can be missed between samples. Chatter, clamp deformation and the
  PLAN §4.6 residue remain outside every rule.
- Cap completion compares the modelled final hole cutter with the CAD cap
  exactly. A final tool radius smaller than the CAD bore, an inch/metric
  nominal mismatch, or CAD modelled at a thread's major diameter leaves a rim
  or apex residue, and that residue is named stock debt and uncredited finish.
  This is symmetric with the existing oversize-point collision; there is no
  tolerance band.
- A length fact carrying its own `verify = true` / `"unknown"` or an
  incomplete `measured` record, a missing dimension, an unknown frame, or an
  unknown `thin_wall_floor_mm` keeps the corresponding rows `?`; an
  item-level `verify = true` on a tool, holder or fixture does not. No row is
  `pass` without every input it names, and no geometry pass is an M5
  measurement claim.
