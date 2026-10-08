# Geometry and workholding rules (M4, FreeCAD kernel)

The nine PLAN §4.2–4.3 kernel rules measure the bound finished STEP faces
against the material present at each authored setup, using FreeCAD's bundled
OpenCASCADE. They compare sampled intersections and B-rep measurements with
the selected tools, holders, fixture dimensions and declared pose. This is not
CAM, a simulation of the cut, or certification of the physical setup.
Everything the kernel cannot measure from explicit inputs stays `?` with a named reason;
nothing is guessed from a bounding box, a catalogue label or a length fact
that carries its own verification debt.

| rule | subject | catalogue row |
|---|---|---|
| `accessibility` | `setup:op` per cutting operation | PLAN §4.2 accessibility |
| `reach` | `setup:op` | PLAN §4.2 reach |
| `internal_corner_radius` | `setup:op` | PLAN §4.2 internal corner radius |
| `coverage` | the plan's `part` name | PLAN §4.2 coverage |
| `finish_coverage` | one subject per manifest feature | PLAN §4.2 finish coverage |
| `vise` | setup id | PLAN §4.3 vise |
| `thin_wall_under_clamp` | setup id | PLAN §4.3 thin wall under clamp |
| `fixture_interference` | setup id | PLAN §4.3 fixture interference |
| `saw_cut` | `setup:op` for saw cut-off | PLAN §4.2 saw cut-off |

The citation list of every geometry finding starts with that PLAN row, adds
`kernel: STEP SHA-256 <digest>; FreeCAD B-rep measurements` when the manifest
digest is known, then the feature (exported `features.<name>: faces and
requirements`, author-owned `plan.joint_features.<name>`, or
`plan.process_features.<name>: STOCK PREPARATION — plan only, not a drawing
dimension`, each plus its citations),
the setup (`plan.setups.<id>: frame and hold`, the resolved fixture/parallels
rows and their citations, the frame citation) and the operation
(`plan.setups.<id>.ops.<n>: selected
action/tool/holder`, the resolved tool/holder rows). `thin_wall_under_clamp`
also cites `shop-policy.numbers.thin_wall_floor_mm`. The kernel itself reports
measurements only; it never emits citations.

## One job, one kernel, no network

A run evaluates geometry at most once per bundle. The CLI builds a canonical
JSON job per candidate (STEP path/digest, feature and explicit op face claims,
the faces plan faced aims move ([plan aims](plan.md#aims)),
authored stock envelope and `stock.as_is_faces`, normalized transient joint
primitives and assembly declarations, setup order/frames/stock chain,
hold geometry and cutting dimensions/endpoints), sends every job that is
not already cached to **one** `freecadcmd.exe <freecad_job.py> -- INPUT_JSON
OUTPUT_JSON` subprocess as a batch (`compare` therefore spawns one process for
all its candidates), and memoizes each result on its bundle so the eight rules
read the same facts. The subprocess has a 600 s limit, reads its input file,
writes its output file and prints nothing. No network activity is involved;
the STEP is the bundle's own file.

Kernel resolution: `FREECAD_CMD` when set (an override that does not exist is
an unavailable kernel, not a fallback), otherwise
`%LOCALAPPDATA%/Programs/FreeCAD 1.1/bin/freecadcmd.exe` when `LOCALAPPDATA`
is set, otherwise `freecadcmd.exe` / `FreeCADCmd` / `freecadcmd` on `PATH`.

Without a kernel every geometry row — including rows that would otherwise be
`not_applicable`, such as a lathe setup's `vise` — is `unknown` with the
message `FreeCAD kernel unavailable; install FreeCAD or set FREECAD_CMD.`,
`numbers.kernel_status = "unknown"` and `numbers.kernel_unavailable = true`.
That flag alone forces exit 4 even when no policy requires a geometry rule, and
the console collapses the repeated sentence to one `?` line (`--verbose` shows
every row). The report keeps all eight rows. Checked readiness therefore needs
a kernel; absence is unresolved, never a pass.

The STEP must be bound before the kernel is called: an unknown `step_sha256`,
no `step` asset, or bytes whose SHA-256 differs from the manifest value give
`unknown` rows with `STEP bytes and their manifest SHA-256 are required for
FreeCAD geometry.` or `STEP bytes do not match the manifest SHA-256; face
identity is unresolved.` Only the hand-authored `examples/pivot-bracket` bundle
has no STEP bytes, so every one of its geometry rows is `?` for this reason even
with a kernel installed. `examples/rocker-arm`, `examples/pivot-shaft` and
`examples/cone-pivot-post` bind the consumer's labelled exports
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

The engine itself answers `unknown` for a STEP that imports as anything but
exactly one valid solid (`STEP import yields <n> solids; the kernel measures
exactly one part solid.`, `imported solid is not a valid B-rep; booleans on
it would be unreliable.`), and `error` for an unparseable STEP, a digest
mismatch it detects itself, or any exception inside a job. A kernel that exits
nonzero, returns invalid JSON, or returns a result outside the contract yields
`error` rows naming the failure (`FreeCAD kernel exited <code>: …`,
`FreeCAD kernel did not return valid JSON: …`, `FreeCAD kernel returned an
invalid batch result contract.`, `FreeCAD kernel batch returned the wrong
number of results.`, `FreeCAD kernel job failed: …`, `Cannot identify FreeCAD
kernel: …`). Those are exit 2 like any other error: an operational kernel
failure is not an unknown measurement.

### Cache

Successful (`status = "ok"`) results are cached as JSON under
`PRECHIPS_KERNEL_CACHE`, else `%LOCALAPPDATA%\prechips\geometry` (or
`~/.cache/prechips/geometry` without `LOCALAPPDATA`). The key is the SHA-256
of the canonical job without its `step_path` (the STEP digest and every
numeric input are inside), the digest of the engine's own `kernel/*.py`
sources, and the kernel executable's resolved path, SHA-256, size and mtime.
Changing a consumed geometry input, the STEP, the engine or the FreeCAD build
therefore misses; moving the bundle does not. Host-only action/finishing metadata
that is not consumed by transient preparation, tool OAL after projection is resolved, protective hold-method text, and the
item-level `verify` / `present` / `source` flags around a consumed fact (which
never enter the job) do not invalidate geometry. `unknown` and `error` results
are never cached, and a cache that cannot be written changes nothing. A hit
reproduces the same facts and the same render bytes as the run that produced
it. The cache is a local convenience, not an input: it is not part of the
hashed bundle.

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

A worker runs the engine's own function on OCC binary B-rep copies of the
operands, which keep every double, tolerance and location and the sub-shapes the
operands of one call share, so its answer is the engine's. Operands carrying a
triangulation (a boolean reads it, and binary B-rep drops it) are never sent, and
a row removal sharing a face or edge with its stock (a later render's mesh would
reach it) is recomputed in the engine. A call no worker has started yet, or whose
worker failed, raised or was lost, is computed by the engine itself, raising as
before. Facts therefore do not depend on the worker count, which is not part of
the cache key; batch timing reports the answers workers gave as the non-operative
`pool_answers`.

`PRECHIPS_KERNEL_POOL_WAIT=1` is the deterministic test mode: the engine waits for
a worker's answer to every call it handed out while any worker can still answer,
instead of computing a call no worker has started, so which booleans workers
answer does not depend on timing. Tests and audits use it; checks and travelers
leave it unset.

## Face identity

Feature `faces` and `stock.as_is_faces` are STEP face references in the
consumer's export form

```text
#<entity>/ADVANCED_FACE[<ordinal>]/<label>
```

where `entity` is the STEP instance id, `ordinal` the 1-based position of that
record among the file's simple `ADVANCED_FACE` records, and `label` the
record's raw name string (the consumer's labelled export writes
`HAF_<FEATURE>__P<nn>`, one label per feature patch; a plain SolidWorks
export writes `NONE`, FreeCAD an empty string — the label is matched, never
interpreted, and a shared label does not merge records: each patch keeps
its own entity/ordinal reference). All three must agree with the exact STEP bytes: a
malformed string, an id that is not an `ADVANCED_FACE`, a wrong ordinal or a
wrong label is an error naming the reference (`… STEP has no instance #n`,
`… is ADVANCED_FACE ordinal 3, not 2`, `… carries label 'a', not 'b'`).

A reference is bound to an imported face by geometry, never by position: the
engine rewrites the STEP so a reader transfers only that one `ADVANCED_FACE`
(same representation chain and units), takes its surface kind, area and
optimal bounding box, and looks for exactly one face of the full import with
the same signature (area within 1e-6 relative/absolute mm², bbox within
1e-4 mm). Zero matches (`no imported face matches its … surface, area …`),
several matches (`ambiguous; imported faces … share its surface kind, area and
bounding box`), or two STEP faces that both match one imported face
(`ambiguous; ADVANCED_FACEs … all match imported face n`) are mapping errors.
Symmetric parts with congruent faces at the same bbox can therefore be
ambiguous by construction; that is reported, not resolved by guessing. In the
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

Plan-owned joint cylinders are separate analytic targets, labelled with their
`plan.joint_features.<id>` provenance. They are never assigned synthetic STEP
entity references and never enter final face, source, as-is, coverage or corner
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
accepted after-op stock. Only those faces earn `coverage`, and
`finish_coverage` too when the op is a finishing cut. A rough, unknown,
stopped or rejected cut, a face outside or only partly inside the window, a
face at another diameter or about another axis and any transient index earn
nothing. Earning
nothing leaves the face's obligations open; it is never debt or
`not_applicable`.

Plan [process features](plan.md#process-features) (a faced `end_face`, a
`centre_hole`) are analytic stock preparation labelled
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


## Approach models

**Milling (axial).** Directional claims and prescribed cutter/holder poses
approach along −setup Z. This also applies to spindle-axis lathe actions
(`spot`, `drill`, `ream`, `tap`, `center`, `center_drill`) on a lathe.

**Turning.** On a resolved `lathe`, every other cutting action uses the
turning model: the spindle is setup Z through x = y = 0 and the work revolves,
so the tool is drawn as a section in the XZ half-plane at centre height and
revolved 360° about Z. The section is the insert (nose radius `nose_radius`,
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
at least head_len_mm"), never a crash or an "unmeasured" head. Claimed
faces must be surfaces of revolution about setup Z on the outside; other faces
are claim errors; internal (bore) claims stay `unknown`. Samples on the
claimed meridians (a dome's pole included; a `to_z` op's samples moved onto
the `to_z` plane it leaves) are checked against the profile after the op —
the held stock minus the turned removals of the setup's turning ops up to and
including this one — plus modeled fixture obstacles, including the rotating
envelopes of placed chuck jaws. Each pose is chosen on that profile's
meridian section: an insert's nose is tangent at the sample; a blade's front
edge lies on a floor sample anywhere along it that keeps the blade clear, so
it sits inside its groove and floor spans narrower than the blade are swept by
that plunge, and a wall sample is cut by the nearest corner. Where that nose or
blade meets the profile at an exposed sample it moves to the nearest clear
pose within twice the corner radius — tangent to both segments of a concave
corner, offset from the wall by the nose radius
— so a corner sharper than the nose is the corner-radius fact below, not a
collision. Flank, head and holder hits stay hits.
Reach is the material radius within the nose's or blade's axial extent; corners are concave toroid or
sphere profile radii (a sharp shoulder is 0) compared with the nose radius.
Removal is revolved: `to_z` faces a band from the innermost claimed radius to
the stock OD; a facing op, `part_off` or `cut_to_fit` given `to_dia` sweeps
from `to_dia`/2 — the axis when a `part_off` omits it — to the stock OD and the
stock end, never leaving a core for a bore the finished part only receives
later; profile ops close each claimed meridian to the OD within the
declared `z_from`/`z_to` span, then cut the finished part back out. Meridian
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
unresolved. Separate supplies do not authorize an unconnected assembly.

The turning model is a deterministic radial sampled necessary-condition screen:
it poses the tool at sampled meridian points only, one final-pass profile per
op. It does not prove tool paths or roughing passes, chip flow, insert or blade
clearance below centre height, blade side clearance or thickness, boring bars
or internal features, cutting load, or chatter. Every turning input must be
measured and accepted; otherwise the row is `unknown`.

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

**Rotary (dividing head).** A mill op with `approach = "rotary"` on a setup held
in a `dividing_head` turns the work about the head axis (the placed chuck's pose
z, pointing out of the jaws) under the vertical spindle. The head axis must be
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
derived stops that pass, so its own flute meets all of its before-op stock and
later flutes keep only their certain finished hits. The holder obstacles retain
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
release sequence prints once, full width ([plan](plan.md#reference)). A blade's
`blade_z_mm` is its axial extent over its cutting poses; the
traveler's jaw distance uses its chuck-side face (in plan units, rounded toward
the jaws), not only the Z its op names. A facing/parting op posed at its `to_z`
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

**Follow rest.** Its jaws ride the carriage, so they are posed with the tool
at every cutting sample of each op the rest serves (`ops`; omitted = every
turning op), never as a static solid. Each jaw is a box `jaw_height` radially
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

**Steady rest.** A static ring at `at_z_mm`, `body_length` long, from the
entry stock's largest radius under it (where its jaws ride) out to
`body_dia`/2. It obstructs the tool and holder only for the ops it serves and
is drawn and interference-checked like any fixture component (role `rest`).
Missing `body_dia`/`body_length`, an unresolved `at_z_mm`, no work under the
ring or a `body_dia` inside the work leaves it an undrawn gap naming why.

Rests are a necessary-condition screen at the sampled cutting points: no jaw
adjustment travel, jaw wear, carriage stroke or arm/bracket outside the jaws
is modelled.

## Inputs the job accepts

Numeric fields reach the kernel only when they resolve to a positive
explicit-unit length through the M5 fact-local lookup with measurement *not*
required: a plain nominal number, or a `{ value, measured, verify }` record
whose own `verify` is absent/false and whose `measured`, when present, is
complete. A fact whose own `verify` is `true`/`"unknown"` or whose `measured`
record is incomplete is debt for that dimension only. An item-level `verify`,
`present` or `source` flag, a set root's or member container's flags and
`coverage` text are identity provenance for the declared-input rules; they
never withhold a numeric fact from the kernel, and nothing is inherited from
them. Shop measurement metadata (`by`, `date`, `instrument`) is not required
here: the M5 `envelope` / `travel` screens impose that stricter readiness on
the same holder gauge/grip, tool OAL and projection facts (and `headroom` on
the envelope limits) separately, so an op can be geometrically checked while
its spindle stack is still M5 measurement debt. See
[inventory](inventory.md#kernel-geometry-facts-m4). Missing
fields are listed in the job's reason text and the dependent rules are `?`.

- Per cutting op (noncutting actions are `not_applicable`; an unknown `do` is
  `unknown`): `radius_mm` (tool `dia` / 2), `flute_len_mm`,
  `holder_radius_mm` (holder `gauge_dia` / 2), `holder_gauge_len_mm`,
  `projection_mm`. The projection is the selected pair's entry in
  `tools.<tool>.projection_mm` / `projection_in`, keyed by the full holder
  reference the op names; when that entry exists it alone decides, so an
  `"unknown"` or debt-carrying entry keeps the op `?` and never falls through
  to another holder's number or to OAL − grip. Only an absent pair uses tool
  `oal` minus the selected holder's `grip`, each from its own accepted fact —
  the same `tool_projection` convention the engagement rule and the M5
  screens share. There is no scalar tool-wide projection. OAL stays host-side
  for `reach`, and finishing-cut decisions stay host-side for `finish_coverage`;
  neither is an engine input (the per-feature `complete_form` hole owner below
  is). Accessibility does not require OAL when the
  selected projection is known.
- Per spot or drill op on a hole feature: `point_angle_deg`, the selected
  tool's included `point_angle`, always sent. A plain nominal or accepted
  fact passes its number; a missing, `"unknown"` or debt-carrying angle is
  sent as `unknown`, never omitted or defaulted.
- Per hole op on a hole feature: `complete_form` inside `hole`, true only for
  the feature's last drill, ream, bore or counterbore in setup then op order
  (a thread's last drill), false for every other hole op (pilots, a
  counterbore's drill, spots, taps). It is an engine input and keys the cache;
  the public plan schema is unchanged.
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

Tool axis is the setup frame's +Z. The part is transformed into the declared
setup frame; the frame is the author's declaration, not a measured setup.

## In-process stock

Each setup's checks and image use the material explicitly selected by `stock_in`.
`"stock"` selects a single supply; `"stock.<id>"` selects a built-up component;
any earlier setup id selects that setup's output, even when it is not the
immediately previous setup. Every array requires a tagged `joint` and exactly
two disjoint input branches. One may be an existing assembly when the other
contains one single physical component, so body+cone followed by assembly+crank
is supported. Two existing assemblies cannot be joined. There is no
unconditional Boolean-union path. Unknown or forward authored references
are bad input (exit 3), including authored `"unknown"` as a source. Omitted
`stock_in` remains named stock debt, never an inferred linear route. Supplies and outputs all stay in the
model frame; assembly does not implicitly transform a reference.
Joined references must have disjoint supply ancestry. Duplicate entries or
`["stock", "S1"]` when S1 consumes stock are bad input (exit 3), naming the
shared supply ancestor. Independent forks may start from the same supply again
as route alternatives, but cannot join that material lineage twice.
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
boolean), that op keeps its own known before-op stock and its flute meets all
of it, never credited with the clearance that failed, but every later op's
flute meets only finished material: its certain finished hits stay certain
(`min_hits`) and its tool hits become unknown, naming the stopping op. This is
a deliberate regression
for such later ops, which on entry stock would otherwise have read clear or
blocked from material that may already be gone. Final profile-wall overstock
and complete-form cap debts are judged once on the setup's end stock and never
change an earlier op's before-op stock. Turning keeps its own turned-profile
obstacle model, unchanged and independent of this pass. Finished face indices
stay bound to the original STEP even when booleans change the stock's face
order.

Mill headroom's X/Y travel screen consumes
`kernel.setups.<id>.stock_bbox_mm` for component stock, an earlier setup's
output, and a joined pair. That box is the actual stock placed in the setup
frame **at entry**; it is neither the finished-part box nor a sum of raw supply
boxes. A missing or withheld entry box leaves travel unresolved. Equality
with a measured travel limit passes; exceeding it fails.

A machine with inventory `kind = "bench"` or `"manual"` whose non-empty
operation list contains only `fit`, `inspect`, `deburr` and `coating` needs no DRO or spindle
screen: `zero_check`, `coordinates` and `headroom` are `not_applicable`.
Joint geometry and modeled holding still apply. Adding any cutting or unknown
operation reinstates the normal machine screens.

The supply needs the positive dimensions and model-frame placement described
under [plan stock](plan.md#stock). As-is face references do not define a stock
volume: when supplied, they must map and lie on that envelope. Unknown
dimensions/placement, incompatible as-is faces, unresolved earlier claims,
or an unrepresentable removal are named stock debt. Stock-dependent geometry
for that setup is `?`, but observed finished-material collisions and known
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

Socket preparation derives actual tool-profile removal from its component;
spigot preparation removes the exterior annulus within its declared axial
interval. A blind drill includes the cone below its cylindrical depth, and
that cone must not intrude into protected finished material. Drill/spot point
geometry needs an accepted included angle, not a fabricated flat bottom.
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

Finished-material protection is component-owned before joining. The spigot's
share is the final solid inside its full cylinder; the socket's share excludes
that spigot-owned region. A raw boss may overlap the body's final coordinates:
its sacrificial turning annulus is not yet body material. Conversely, socket
removal into socket-owned finished material outside derived finite engagement
is forbidden. This protection applies to every cut on those branches, not
only operations naming a transient feature. Overlapping spigot ownership or
invalid surface ownership is localized to the involved components/joint;
unrelated known component branches remain usable. Ordinary
`stock_removal_bounds` cannot grant permission to remove protected finished material.

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

For `retaining_compound`, `clearance_mm` is the declared diametral band,
`process` identifies the selected application, `surface_prep` declares preparation
instructions, and positive `cure_time_min` declares the wait before disturbing
the joint or machining it. Explicit unknown clearance, prep or cure time remains
debt and withholds union/render; absent or malformed required process facts are
bad input. These are authored process facts, not a chemical cure simulation or
manufacturer certification. Travelers print **do not disturb until cured**.
Existing silver-braze and press behavior is unchanged.
A known geometric refusal (missing preparation, blocked insertion, overlap or
lost required material) remains an error even when cure or surface prep is
unknown. Only a geometrically derivable join becomes process debt; it still
produces no stock output. An unused or unrelated spigot declaration cannot
exclude required material from the assembly backstop.

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
A profile op (`profile`, `rough_profile`, `finish_profile`) with no
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
The operator really drives the printed path, corner miters (two linear moves
past a convex corner) and run-outs included, so every point within r of each
printed table (its displayed `dro_xy` rows as chords, from its displayed tip up)
is credited removal too. **Rule A′** limits that path, row by row: a printed
row is an accessibility error naming the row when its cutter meets the finished
part or the op's rough leave (its guard), a fixture component, stock outside a
bounded op's box, or stock a later setup bears on. A row's scrap is what it
removes past its op's design (the corridor and claim sweeps, or a bounded op's
box). Retained scrap may be nicked unless a later setup (one whose stock
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
debt, never a guessed removal). Non-vertical claims of a profile op still sweep
along +Z.
Every claimed face with a horizontal normal component is checked for
remaining overstock above `to_z`,
including drafted walls whose +Z sweep is nonzero. Exact face contact catches
small retained ears; nearest-contact probes inset from the face boundary
distinguish a drafted sliver from legitimately retained neighbours.
A `complete_form` hole op's own claimed caps are then checked against the
setup's final stock with the same contact test, without the `to_z` clip (see
[accessibility](#accessibility)); a touched cap is named output-stock debt.
An operation can declare numeric `stock_removal_bounds` (one setup-frame box)
to clear only outside-finished material inside that volume. The box is the
explicit cleared footprint the author declares, for example the envelope of
several roughing passes; it is not capped to the claimed faces' XY bounding
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
its output stay `unknown`, never clearance. Genuine collisions with finished
material remain independent errors. Synthetic geometry fixtures
author these preparation volumes and numeric supply allowances; their target
setup checks the derived material. Preparation tool/fixture debt stays visible,
and the fixture policy explicitly requires the target, not fabricated roughing
clearance. The reference rocker declares its raw 310 × 45 × 16 mm S1 supply explicitly, so S1 is drawn
as that blank. Its rough-profile notes retain rails, ears and a 0.40 mm web,
but provide no numeric lateral interruption mask. S2/S3 therefore name the
unresolved S1 profile removal rather than drawing the finished arm or
inventing rail dimensions. A known current setup remains checkable/drawable
even when its output stock is unresolved for the next setup.

### Saw cut-off

`saw_cut` and `cut_off` use an authored setup-axis blade-centre `cut_plane`
and the selected bandsaw blade's positive inventory kerf. Below retains the
halfspace at or below `plane - kerf/2`; above retains the halfspace at or above
`plane + kerf/2`. The native Boolean removes the kerf plus the discarded planar
slab from the **current operation stock**, including earlier removals in that
setup. Its retained result is available through normal `stock_in` routing.

The `saw_cut` finding reports the normalized plane, kerf, retained boundary and
before/after, kerf, offcut and removed volumes in mm/mm³. A cut into the finished
target, an empty retained piece or an off-stock/no-op blade is an error, never
clipped back to the target to fabricate a pass. Tangent contact with no target
volume removed is permitted. Missing/unverified kerf, cut-plane or upstream
stock remains named `?`; absence of FreeCAD remains kernel debt.
Splitting one connected input stock solid into several retained pieces is also
an error: detached pieces are not silently routed as held stock, including tiny
retained slivers. Independently supplied components already disconnected before
the saw may remain disconnected; the check is per input solid, not the total
retained count. Target-loss and volume facts are computed before this refusal.

`accessibility`, `reach` and `internal_corner_radius` are `not_applicable` to a
saw operation: its blade is located by the cut plane/kerf, and the axial/turning
tool-cylinder model does not model a saw blade. This states a model boundary,
not certified blade/fixture clearance. Saw cuts provide no finished-face or
surface-finish coverage credit. Holding, fixture solids and fixture-interference
screens remain in effect, including on a dedicated bandsaw setup.

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

Along the jaws the engine distinguishes an *exact* pose from a conservative
envelope. With `jaw_center_along_mm` each box spans the full `jaw_width`
centred on that value. Without it the dark (certain) boxes span only the
zone material's extent along `jaws_along`, and the remaining `jaw_width −
extent` on either end of each jaw is tracked as a *possible* jaw region: a
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

Needs the five tool/holder dimensions (radius, flute length, projection,
holder radius, holder gauge length) and a vise without input debt for a pass.
Within the supported milling domain, missing inputs normally yield `unknown`,
but positive observed minimum tool or holder hits still error despite unknown
stock, fixture or dimensions. Invalid face claims remain errors first; an
invalid clearing removal is named stock debt, not an error.
On the claimed face set the kernel samples a cell-centred
5×5 UV grid per face plus 2–12 points along every boundary edge and gives
each sample one prescribed tool pose (PLAN §4.2). Ordinary wall samples use
the cutter-radius offset along the in-plane (XY) outward normal; ordinary
planar floor samples take their nearest legal centre below. The tip is at the sample's Z,
except as the rough leave below moves it.

**Printed checkpoints (rule A′).** For an op whose coordinates tables print
cutter-centre rows ([rules-coordinates](rules-coordinates.md)), the kernel
stands the op's cutter cylinder (radius less 0.001 mm) at every printed row's
displayed setup XY from its displayed tip up above the setup-entry stock.
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
before-op stock or a boolean is unresolved, and then no row remains. The kept
rows, renamed per piece with the coordinates row-id formats, are the only rows
the row check and the setup picture's waypoints use; a bounded op's removal
stays its box, never a printed run-out. Each
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

A rough milling op's scalar `rough_allowance_mm` (a) is consumed by the
engine as a leave in millimetres normal to the finished surface. Each rough
sample point first moves `a` along the face's unit outward normal, then takes
the ordinary cutter-radius `r` shift along the in-plane (XY) normal; planar
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
nominal finished solid or a zero leave. Where both whole-part constructions
fail (a zero-height land tangent to a cylinder, as on the cone pivot post's
journal pads, makes OCC fail at any leave), the op's guard is built
exactly in each box where one of its consumers subtracts it: its claimed
faces grown by its wall-check reach (`max(a, carried) + 0.01` mm, also
covering its band and pose contacts), and its clearing box above `to_z` or
its whole unclipped +Z claim sweep or profile corridor. In each box the finished part's offset
equals the arc-join offset of the finished part within the box grown by
`2a`, cropped to the box. Every positive-volume source and cropped component
is kept, each piece must offset to one valid solid containing it, and the
crop must contain the finished material in the box. Every Boolean in the
construction must be valid; one that meets nothing is empty, but faces
without a solid are debt, never taken as empty. Only arc joins qualify, and
each consumer subtracts only inside its own box. The lineage band of a
lower-leave op then needs no whole-part offset by the carried leave. Its
candidates are the carried-leave skin of the claimed faces: each face
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
each piece it leaves must be valid. One input piece may leave several pieces
above 1e-3 mm³ only as a **held split**: every piece must be pressed onto an
anchored support, or the whole split is refused and no piece is dropped. A
piece is held when a clamp declared `restraint = "press"` has a flat face
whose outward normal is its force (pose -z, within 1e-6) within 1e-3 mm of
the piece, and from one cell-centred sample of that face (the strap-wall grid)
the first material run through the piece along the force starts within 1e-3
mm of the sample and ends where the point 0.01 mm beyond lies inside an
anchored fixture component: a fixture body, jaw, parallel, riser, chuck jaw or
body, dividing head or centre, never a clamp, rest or other stock piece. The
holding must be placed. `locate`, `none` and an undeclared restraint never
hold. The op's `split_hold` lists each piece (number, volume, bbox, `held`,
and the clamp, sample, exit point and support that hold it). Otherwise the
stock reason names the removal that broke the stock ("its own clearance" or
"lineage band group N"), or the split and each piece with "no press-clamp
load path to an anchored support", and the op that stopped the stock pass is
credited none of its clearance. If any construction fails, the result is
named offset debt.
Every offset and pipe is built on a deep copy of the solid, face or edge it
starts from. OCC's offset rewrites the edge tolerances and pcurves of the
shape it runs on, so offsetting a face shared with the finished part would
change that part, and every later Boolean against it, by call order.

**Nearest legal centre (supersedes the 2026-10-05 wall-tangency closure and
the whole-face-centroid floor pose):** every sample of an ordinary claimed +Z
planar face of a milling (non-hole, non-joint) op, its concave corner samples
included, keeps its own surface samples and stands on its nearest legal
centre. The tip height comes first and is the pose's actual height: `z =
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
apply as before. Two cases certify. Outside: the sample is outside every certain solid (boundary
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

The holder cylinder (gauge diameter, gauge length) starts `projection_mm`
above the tip. Both cylinders are intersected with material minus a thin
inward offset shell of **that sampled face only**, plus the jaw boxes. The
holder meets actual setup-entry material. The flute meets the stock the
setup's earlier derived cuts leave (see [in-process stock](#in-process-stock)), less this op's
own derivable outside-finished allowance; the holder still sees both. The
shell removes numerical self-contact, not a cutter-radius slab and not another
finished face of the same feature. A cutter wider than a claimed groove
therefore still intersects the opposite claimed wall. Holding, rendering and
accessibility holder obstacles use actual setup-entry stock, and no flute is
credited with a later op's removal.

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

For drill, spot, ream, bore, tap and counterbore operations, the flute stock
obstacles exclude only the op's own actual cutter volume, to its declared
depth or explicit through extent. Hole centres and axes derive
from geometry-matched concave cylindrical faces aligned to setup Z, not a
guessed face centre. Unrelated finished material remains an obstacle, and
this exclusion does not clear holder obstacles: the holder cylinder is
unchanged and meets the full actual setup-entry stock. Missing depth or entry
facts and explicitly unknown through facts remain debt; an omitted `thru`
uses the existing blind-hole default, not an assumption of through
clearance. No removal extent is invented.

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

P6 explicitly accepts skipping a stock Boolean once the hit is mathematically
proven, even if the avoided solve might otherwise have raised. A Boolean that
still runs is never caught or suppressed by this optimization. Certificates
only count hits: they never prove a miss or replace a native shape, and actual
pointed cutters bypass them. A count-only hit skips the intersection only when
no finished face outside the already-proven reference union can add a hit
reference; partial reference sets never enter shared full-set caches. Every
authored sample still contributes to the full hit count, and input or stock
debt retains its existing unknown/error precedence.

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
The kernel tests pin it: a rough and a finish face raster at a cutter-diameter
step round a boss keep the island and the cusps between their piece ends over
the boss height, the volume an independent strip integration of what the
printed pieces miss gives, and clear it at every pose; a finish pocket claiming
the boss wall inside its keep-out leaves the rough's leave on it, as one
claiming only the floor does; and the finisher with unmapped circles or passes
leaves its cut and accessibility unknown.

The kernel tests pin the discriminations: a plate-top sample within a cutter
radius of a boss stands at its nearest legal centre and clears, as do samples
near an R10 or exactly cutter-sized circular pocket wall, an arc/chord corner,
a fillet corner of the cutter's radius and the walls of a groove exactly two
radii wide, while a cutter wider than its circle or groove, or a sharp
concave corner sample with no legal centre within `rho`, reports the real wall
hit; a plate sample past both walls of a square island's convex corner moves
straight away from the corner and clears; equal candidates break to the face
centroid; beside a B-spline wall, an outside sample whose native closest point
is a vertex and a sample on a straight edge take their certified bounds, while
a spline boundary, a strictly interior sample, a vertex boundary, a projection
inside a spline whose native tolerance exceeds 1e-7 mm and a bound blocked by
a second obstacle (a farther clear supported axis notwithstanding) leave only
that floor's pose undefined and keep another face's certain hits; an offset
cutter tangent to
its claimed side wall clears while the sample-centred mutant intersects the
wall; a Ø10 cutter
in a 6 mm through-groove hits the opposite wall; dimensioned jaws occlude the
holder only when they stand high enough. The legal-centre convention
above changes the prescribed pose, not the obstacle solid. There is no pose
search, and unresolved pose or exclusion facts remain debt rather than clearance.
Numbers: `sample_count`, `tool_hits`, `holder_hits`, the five inputs, and
`certain_tool_hits` / `certain_holder_hits` when observed hits are definite
despite unresolved stock, inputs, poses or undeclared jaw overhang.

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

Needs `flute_len_mm`. The kernel measures reach on the stock the op meets: the
setup-entry stock less every earlier op's accepted cut in that setup (see
[in-process stock](#in-process-stock)). For each upward-facing sample it takes
the highest such material within the cutter radius + 0.05 mm of the offset tool
axis, and reports the largest such height above a sample as `reach_depth_mm`.
`holder_wall_hits` counts samples whose holder cylinder (starting
`projection_mm` above the tip) intersects that same stock, and needs the holder
radius, gauge length and projection. A stock the builder cannot derive leaves
all three unknown with its reason, never measured on the setup-entry stock.

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
unknown.

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

The long-tool rescue therefore requires accepted holder gauge-diameter,
gauge-length and projection facts and, off the turning model, a measured shank
clear of the retained stock; an unknown holder or shank never passes a
beyond-flute depth.

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

Needs `radius_mm`. The measured quantity is concavity in the section
transverse to the tool axis, which is what limits a cutter of that radius:
a concave cylindrical claimed face whose axis is parallel to +Z contributes
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
makes the row `unknown` with that face/edge named. Numbers:
`corner_radii_mm` (sorted), `tool_radius_mm`, `minimum_corner_radius_mm`,
`cad_sharp_corners` and `corner_radius_max_design_mm`.
These are finished-solid facts, independent of unknown in-process stock;
a known sharp corner remains an error even when reach cannot be measured.
The comparison uses a 0.005 mm numeric tolerance: a concave radius admits the
cutter when it is at least `tool_radius_mm - 0.005`. STEP coordinates commonly
write only 5–6 significant digits, so sub-tolerance import/kernel rounding
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

- no such corners: `claimed faces have no concave edges perpendicular to the tool axis.` (not_applicable)
- `concave corner radii admit the selected cutter.` (pass)
- `a claimed internal corner is smaller than the selected cutter radius.` (error)
- `concave edge radii are unresolved.` or the kernel's reason (unknown)

The rule does not certify a floor fillet or bottom radius against the cutter.

## `coverage`

One row for the whole part. Every imported face must be in the union of the
face sets claimed by cutting operations and `stock.as_is_faces`, where a face
claimed through rotary windows counts only when the union of those windows
covers it. Numbers: `face_count`, `claimed_face_count`, `unclaimed_faces`
(their references, `null` for an unnamed face) with `unclaimed_indices`,
`mapping_errors` when present, and `rotary_gaps` / `rotary_unresolved` when
a rotary-claimed face is not covered (below). Sentences label an unnamed face
`imported face index <n>`.

- `invalid STEP face reference(s): …` (error)
- `cutting claims are unknown, unmapped or undecided, or as-stock refs are unknown.` (unknown: any unknown action, unmapped feature, unresolved claim direction or unknown/omitted `as_is_faces`)
- `rotary window coverage is unresolved for <face> (<reason>); …` (unknown)
- `faces have no cutting op or as-stock claim: …` (error)
- `rotary windows leave part of a claimed face uncut: <face> (<area> mm² at <setup> z <lo>..<hi> mm, angle <lo>..<hi>°); …` (error; joined to the previous error with `; ` when both apply)
- `every imported face is claimed by a cutting op or declared as-stock.` (pass)
- `Imported STEP face inventory is unresolved.` (unknown)

Only supported, direction-valid claims are credited. If every remaining
face has a mapped cutting claim but needs the unsupported lathe approach model,
the row is `unsupported` with the milling-only-model reason above. Known missing
claims and rotary gaps outside that unsupported set still error. Invalid
references outrank everything; unresolved claims/as-stock references, and then
unresolved rotary unions, are `unknown` ahead of `unsupported` and errors.

A rotary op's direction-valid `claimed_indices` name faces its window only
intersects, so they never credit a face by themselves. For each face that
rotary ops claim and no whole-face claim covers, the rule consumes the
kernel's `rotary_coverage.cut` union (see [Approach models](#approach-models)):
a face in `complete_indices` is credited; a face in `gaps` is an error naming
its uncovered area and, per contributing setup, its axial span and enclosing
angular span; an `unknown` union, or a rotary-claimed face the kernel reports
nothing for, is `unknown` naming the face and reason — never whole-face
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

## `finish_coverage`

One row per feature. A feature with a known `requirements` list that neither
lists nor declares `finish_ra` is `not_applicable` (`drawing declares no finish
requirement`); an unknown/omitted requirement list or an unknown `finish_ra`
value is `unknown`. Otherwise every face of the feature must be claimed by a
finishing cut. Numbers: `finish_ra`, `required_faces`, `uncovered_faces`,
`rotary_gaps` / `rotary_unresolved` as in `coverage`, and `unformed_caps` when
present.

A claimed hole cap is credited only when its `complete_form` op's
`cap_completion` measured it clear (see [accessibility](#accessibility)). This
holds for the last setup and for any output no setup consumes. A cap that
still touches stock stays uncovered and is listed in `unformed_caps`. An
unmeasured cap makes the row `unknown` unless another face already errors.
A tap's claim never credits a cap its thread's drill left unformed.

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
union is `unknown` ahead of `unsupported` and errors.

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

One row per setup. Non-vise holding (`kind` ≠ `vise`) is `not_applicable`
(`{setup}: vise has no vise grip-zone facts for {kind} holding.`); unknown
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

- `gripped faces are not a parallel pair`
- `jaw separation (part width plus any round bar or jaw buttons) exceeds vise opening`
- `both jaws do not provide the declared grip`
- `claimed faces enter jaw solids: <refs>`
- pass: `parallel gripped faces, opening, both-jaw grip and claimed-face exclusion fit declared parallels.`
- unknown: `vise contact geometry is unresolved.` or the kernel's reason

Declared parallels are an existence/height input; the rule does not confirm the
parallels were installed, the part was seated, or the vise torqued.

## `thin_wall_under_clamp`

One row per setup. Holding other than a vise, a chuck (a lathe `chuck_3jaw` /
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

Inside the jaw zone the kernel runs clamp-direction lines through
the part on six Z levels and 8–64 columns along the jaws (about 1 mm pitch),
keeps only lines that meet material at both jaw planes (a loaded wall), and
reports the thinnest material interval among them as `min_wall_mm`; no loaded
line is a named debt.

For an angle plate, custom fixture or any other posed-solids hold that
declares `clamps`, each drawn strap loads the stock along its pose's −z. The
kernel takes every flat strap face that faces that force and touches the
setup-entry stock, samples a cell-centred grid on it (4–16 per side, about
1 mm pitch), runs a line along the force from each sample and records the
first material interval at the contact as that sample's run; samples over air
are not loaded. `min_wall_mm` is the thinnest loaded run over all straps. A
clamp that is unlisted, unposed or has an unverified/unmeasured solid, and a
drawn strap with no loaded sample, is a named `strap_wall_debts` entry: with
no loaded strap the wall stays unknown with `strap walls unresolved: …`; a
drawn strap's certainly thin run still decides `error`/protective `pass`, but
a run that meets the floor is `unknown` (`drawn straps meet the shop floor but
other clamps are unresolved: …`) while any debt remains.

A clamp declared `restraint = "locate"` carries no clamping load, so it has no
footprint run and adds nothing to `min_wall_mm`. Each of its drawn solids that
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

The rule compares the wall with
`shop-policy.numbers.thin_wall_floor_mm`; a `numbers_verify` flag that is
true or unknown makes the floor unknown. Numbers: `min_wall_mm`,
`thin_wall_floor_mm`, `method` (plus `strap_wall_debts` when present).

- wall ≥ floor: `minimum wall inside the grip zone meets the shop floor.`
  (`under the strap footprints` for strap holds) (pass)
- wall < floor and `hold.method` is one of `soft_jaws` / `soft jaws` / `mandrel` / `tape` / `wax` (case-insensitive): `wall is below the shop floor with a named protective holding method.` (pass)
- wall < floor, unknown method: `wall is below the shop floor and protective holding method is unknown.` (unknown)
- wall < floor, other method: `wall is below the shop floor; name soft jaws, mandrel, tape or wax.` (error)
- otherwise `grip-zone wall thickness or shop thin-wall floor is unmeasured.` (unknown)

The shipped policy keeps `thin_wall_floor_mm = "unknown"` with
`numbers_verify = true`, so this rule stays `?` until the shop measures a floor.

## `fixture_interference`

One row per setup, for every holding kind the kernel draws (vise, chucks,
dividing head, dead centre, angle plate, custom fixture, clamps). With the
fixture's components placed on the setup-entry stock, the kernel checks:

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

For each setup with a numeric frame and derivable incoming stock the kernel
returns a PNG 1600 pixels wide and 1000 tall (taller with holding detail bands,
below) suitable for a wide printed setup figure. The camera
uses setup axes: a lathe elevation has +Z to the right, radial +X up and +Y
away, with headstock/chuck left and tailstock right; a mill uses a front-right
isometric view; a custom plate uses a plan view down setup -Z, and a custom
fixture on a bench or saw an elevation section across the stock's longer
horizontal side, on the plane through the middle of the holding that touches
the work (else the stock's centre), so the buttons, saddles and pins holding it
are cut and their contacts show (`render_scene.section`: `axis`, `at_mm`). The engine's
own orthographic z-buffer rasterizer, bundled bitmap font and PNG encoder
use no installed fonts, timestamps or machine-specific metadata. Fresh runs
and cache hits give identical bytes.

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
the measured fit-up + N mm. Steady rest
rings are drawn as fixture solids; each follow rest's
jaws are drawn and labelled posed for the first cutting sample of the first
op it serves. An exposed-end detail makes short lathe stickouts legible; when
its point keys would sit closer than their badges need (a jaw-end dome), it is
enlarged until they stand apart, as in the shaft's S2 and S3. Contour
sketches show both sides and share `P` waypoint keys with the coordinate
tables. Custom plates show pads, locators and authored clamp-action order.
Table/vise-body/headstock/tailstock context outlines are marked schematic;
they never add fabricated solids or authorize a cut. Inventory stop solids
require `hold.stop_fixture` and a numeric `hold.stop_pose`.
Every label prints at body size (21-pixel caps, about 7 pt on Letter); the
renderer refuses smaller text. Setup notes come from the setup's declared ops,
bench actions included, so a deburr/coating/inspect setup says it has no
machine cutting rather than "no material removed".

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

When something touches the stock and the main picture draws the stock's
narrower side under 200 pixels, a **holding detail** band is printed below the
picture. The kernel computes the contacts from the exact solids: each holding
solid within the stock tolerance of the work gives the outline of the shared
face (or the section edges, else the nearest point). Its plane is measured on
that whole contact before a section view cuts it: the outline is cut where it
crosses the section plane and only the kept side is drawn, still keyed at the
contact's own plane (a contact that is a point or a straight line names no
plane). `closest_cut` is the smallest distance from this setup's
removal to a holding solid; a setup that both files and machines measures it from
its machine cuts only, the cuts the CLEARANCE table lists, so the picture's
dimension is one of that table's rows. The detail frames the stock, the contacts and that
distance; it outlines each contact (solid where seen, dashed where hidden),
keys it with its holding name and the setup coordinate of its plane (a support
whose solids lie on different planes, such as the rocker's hub stand and rail
shims, is keyed plane by plane, and same-named solids share a key only on one
plane). A numbered support (a coded clamp such as `SUP1`, or a pad) on one plane
keeps its position badge; one whose solids seat the work on several planes keys
each solid with its code, its own name and its plane, led to its own contact,
and pad keys at several heights name the pads each keys. It dimensions the
closest cut in amber (`render_scene.closest_cut`: `mm`, the holding `tag`, the
two end points): from this setup's removal, or on a saw setup from the blade's
path (each saw op's kerf slab on its cut plane, across the stock and holding),
never from the falling offcut. A mill picture also carries
`render_scene.cut_clearances`, one `{op, mm, tag}` per op the stock builder cut
(the material it takes away to the nearest holding solid), which the CLEARANCE
table prints op by op. `mm` and `tag` are `unknown` for the op whose cut stopped
the stock builder and every later one, and for every op that removes material
while the holding is not drawn whole (any `render_scene.debts`: an unresolved
fixture, an undrawn component, an undeclared jaw extent), since what is not drawn
may stand nearer than anything drawn; the table then says to check at the machine.
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
to the grid; `closest_cut.mm` is rounded as the CLEARANCE rows are (six places).
Every decimal a picture prints (DRO values, clearances, sizes, a band's gain) and
every fixed-decimal number on the sheet goes through one rounding,
`render_diagram.decimal_text`: the float's written decimal, a half-way value
rounded away from zero (2.8045 at three places prints 2.805, never 2.804), so a
picture and its table never print one value two ways.

A guided bench file (a hand op whose `guide.buttons` kit is held in the setup,
its solids named to the kernel by `guide_owner`, the kit's declared button OD by
`guide_rim_dia_mm`) is not a cut to clear. A kit solid is a stop only when it is a
button of that declared OD (a cylindrical face within the OD limits, widened by the
stock tolerance), its cut reaches it, it is seated on the filed face (within the
stock tolerance of the stock the file leaves, without biting into it), and that
rim sets the filed boundary: the rim's cylinder, run along its axis, touches the
cut where the cut meets the stock the file leaves and nowhere enters the cut. A
button of the right OD whose rim stands over the unfiled wall is no stop. Those stops
are named in `render_scene.guide_stops`, and the kernel leaves them out of
`closest_cut`, so no `CUT 0.000 mm FROM` a filing button prints. Any other kit
solid the cut reaches (a stud, a tab touching the unfiled wall, a square block) is
holding to clear and keeps its real `CUT` dimension. The detail keys
them in green: `FILE STOPS ON BOTH BUTTON RIMS` for a matched pair, or one key
per rim, `FILE STOPS ON UPPER BUTTON RIM`, when they lie apart. A real clearance
to the rest of the kit (its stud) is still dimensioned: in the holding detail when
one is drawn and keys it, else on the setup picture itself, so a picture never
drops its `CUT` dimension because the detail band is not drawn. When the stops are turned
solids on one axis that the setup picture does not already look along (within
cos 0.99), a **guide view** band below the detail looks down that axis, enlarged
(`VIEW ALONG THE BUTTON AXIS X14.6`, with the setup axes it draws right and up).
It outlines the rims in green with their stop key, hatches `STOCK TO FILE OFF`
inside the `FINISHED OUTLINE`, draws `FILE AT ITS STOP` flat on the rims, and
draws a `FILE APPROACH` arrow coming in square from beyond them. It keys the kit
as the setup picture names it (`render_scene.guide_axis_mm`: a point on the axis
and its direction). When the stops lie at different heights along the axis, the
kernel sections the view between them, half way unless that plane would miss most
of the stock to file off, so the near button does not hide the work and the cut
face shows what the file takes; the band notes `SECTION BETWEEN THE RIMS`.

An inspect op's `inspection_views` ([plan](plan.md)) are drawn as one set-up
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

Alongside the image the engine returns `render_scene` with `fixture_kind`,
`jaws`, `parallels`, `components`, `debts`, camera/resolution, plain-language
`shows` / `legend`, annotation-only `render_debts` and shared `waypoints`.
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
reason>`), `exact` or `not_modelled` (as in the shipped rocker S1, whose
measured vise and declared `jaw_center_along_mm` give exact jaws while the
parallels lack `width` and `parallels_centres_mm`: debt `parallels not
drawn: parallels_width_mm, parallels_centres_mm undeclared`). For a chuck or
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
- A vise is modeled only when its `jaw_height` / `jaw_width` / `jaw_depth` /
  `opening` facts each resolve without their own debt, seated at the part's
  lowest Z. The exact jaw pose along the jaws and the parallel solids exist
  only when the plan authors `jaw_center_along_mm` and
  `parallels_centres_mm` and the parallels row's height, length and width
  facts are accepted; otherwise the render is an envelope or part-only view
  with named debts. The shipped example vise records measured
  `jaw_height` / `jaw_width` / `jaw_depth` / `opening` (its item-level
  `verify = true` is identity debt for the declared-input rules, not a
  geometry veto), while the shipped parallels declare no `width` and no
  shipped plan declares `parallels_centres_mm`; those are debts to declare,
  not values to invent. Chucks, heads, centres, clamps and authored solids
  follow the same trust rule: each dimension and pose is authored and
  accepted, never defaulted. Collets, soft-jaw profiles and toe clamps
  without authored `solids` are not drawn.
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
