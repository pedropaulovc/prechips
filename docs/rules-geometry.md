# Geometry and workholding rules (M4, FreeCAD kernel)

The seven PLAN §4.2–4.3 kernel rules measure the authored STEP B-rep with
FreeCAD's bundled OpenCASCADE and compare the measurements with the selected
tools, holders, fixture dimensions and declared pose. They are sampled solid
intersections and B-rep measurements, not CAM toolpaths, a simulation of the
cut, or a certification that the physical setup matches the plan. Everything
the kernel cannot measure from explicit inputs stays `?` with a named reason;
nothing is guessed from a bounding box, a catalogue label or an unverified
inventory row.

| rule | subject | catalogue row |
|---|---|---|
| `accessibility` | `setup:op` per cutting operation | PLAN §4.2 accessibility |
| `reach` | `setup:op` | PLAN §4.2 reach |
| `internal_corner_radius` | `setup:op` | PLAN §4.2 internal corner radius |
| `coverage` | the plan's `part` name | PLAN §4.2 coverage |
| `finish_coverage` | one subject per manifest feature | PLAN §4.2 finish coverage |
| `vise` | setup id | PLAN §4.3 vise |
| `thin_wall_under_clamp` | setup id | PLAN §4.3 thin wall under clamp |

The citation list of every geometry finding starts with that PLAN row, adds
`kernel: STEP SHA-256 <digest>; FreeCAD B-rep measurements` when the manifest
digest is known, then the manifest feature (`features.<name>: faces and
requirements` plus its citations), the setup (`plan.setups.<id>: frame and
hold`, the resolved fixture/parallels rows and their citations, the frame
citation) and the operation (`plan.setups.<id>.ops.<n>: selected
action/tool/holder`, the resolved tool/holder rows). `thin_wall_under_clamp`
also cites `shop-policy.numbers.thin_wall_floor_mm`. The kernel itself reports
measurements only; it never emits citations.

## One job, one kernel, no network

A run evaluates geometry at most once per bundle. The CLI builds a canonical
JSON job per candidate (STEP path and manifest digest, every feature's `faces`
list, `stock.as_is_faces`, and per setup the numeric frame, the hold inputs
and the cutting operations' tool/holder dimensions), sends every job that is
not already cached to **one** `freecadcmd.exe <freecad_job.py> -- INPUT_JSON
OUTPUT_JSON` subprocess as a batch (`compare` therefore spawns one process for
all its candidates), and memoizes each result on its bundle so the seven rules
read the same facts. The subprocess has a 300 s limit, reads its input file,
writes its output file and prints nothing. No network activity is involved;
the STEP is the bundle's own file.

Kernel resolution: `FREECAD_CMD` when set (an override that does not exist is
an unavailable kernel, not a fallback), otherwise the installed
`FreeCAD 1.1/bin/freecadcmd.exe` under the user's local programs, otherwise
`freecadcmd.exe` / `FreeCADCmd` / `freecadcmd` on `PATH`.

Without a kernel every geometry row — including rows that would otherwise be
`not_applicable`, such as a lathe setup's `vise` — is `unknown` with the
message `FreeCAD kernel unavailable; install FreeCAD or set FREECAD_CMD.`,
`numbers.kernel_status = "unknown"` and `numbers.kernel_unavailable = true`.
That flag alone forces exit 4 even when no policy requires a geometry rule, and
the console collapses the repeated sentence to one `?` line (`--verbose` shows
every row). The report keeps all seven rows. Checked readiness therefore needs
a kernel; absence is unresolved, never a pass.

The STEP must be bound before the kernel is called: an unknown `step_sha256`,
no `step` asset, or bytes whose SHA-256 differs from the manifest value give
`unknown` rows with `STEP bytes and their manifest SHA-256 are required for
FreeCAD geometry.` or `STEP bytes do not match the manifest SHA-256; face
identity is unresolved.` Three reference bundles have no STEP bytes, so
every geometry row of theirs is `?` for this reason even with a kernel
installed. `examples/rocker-arm` binds the consumer's labelled export
(`HAF_<FEATURE>__P<nn>` labels; a periodic surface arrives as several
`ADVANCED_FACE` patches under one feature label, each bound by its own
entity/ordinal) with each feature's `faces` copied from that export; the
export's extra features (`strap_datum_b`, the two tip lands) have no
manifest counterpart and are deliberately left unclaimed rather than
invented. Its frozen report has the kernel measuring the bound faces
(`internal_corner_radius` passes where tool dimensions resolve) while
`coverage` stays `?` because the stock's as-stock faces are unknown and
every fixture-dependent row stays `?` on the `verify = true` vise.

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
Changing any input dimension, the STEP, the engine or the FreeCAD build
therefore misses; moving the bundle does not. `unknown` and `error` results
are never cached, and a cache that cannot be written changes nothing. A hit
reproduces the same facts and the same render bytes as the run that produced
it. The cache is a local convenience, not an input: it is not part of the
hashed bundle.

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

## Inputs the job accepts

Numeric fields reach the kernel only when they resolve to a positive explicit
length from an inventory row that is not `verify = true` (`present`/`verify`
unknown rows count as unverified); see [inventory](inventory.md). Missing
fields are listed in the job's reason text and the dependent rules are `?`.

- Per cutting op (noncutting actions are `not_applicable`; an unknown `do` is
  `unknown`): `radius_mm` (tool `dia` / 2), `flute_len_mm`, `oal_mm`,
  `holder_radius_mm` (holder `gauge_dia` / 2), `holder_gauge_len_mm`,
  `projection_mm` (tool `projection`, else `oal − holder grip`, the same
  convention as the engagement rule), and whether the op is a finishing cut
  (the same final-cut semantics as the datum rule: a feature's last cutting
  op, with drill → ream / bore / tap).
- Per setup: the numeric frame from the manifest (`origin` converted from
  inches when `units = "in"`; an unknown frame keeps every op row `unknown`
  with `numeric setup frame is unknown`), and for a `kind = "vise"` fixture
  the hold inputs listed under [plan hold](plan.md#hold): `fixed_jaw`,
  `jaws_along`, `grip_mm`, `jaw_above_parallels_mm`, the vise `jaw_height`,
  `jaw_width`, `jaw_depth`, `opening`, and the parallels `height`. Two
  optional authored pose fields pass through when numeric and are otherwise
  absent, never defaulted: `jaw_center_along_mm` (jaw centre along
  `jaws_along`, setup-frame coordinate) and `parallels_centres_mm` (exactly
  two `[x, y]` setup-frame centres); the parallels `length` (along the jaws)
  and `width` (along the clamp axis) also pass when measured. Any other
  holding kind carries `Fixture solids are not declared for this holding
  kind.`: no chuck, collet, fixture-plate or clamp solid exists in M4.

Tool axis is the setup frame's +Z. The part is transformed into the declared
setup frame; the frame is the author's declaration, not a measured setup.

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
and the selected parallels row measures `height`, `length` and `width`: two
boxes `length` along `jaws_along` × `width` along the clamp axis × `height`
down, tops at the part seat. They lie below every tool and holder cylinder,
so they never enter hit counts; they exist for the picture and for the
`declared parallel centred at [x, y] intersects the <side> jaw` debt. With
any of those inputs missing the scene records `parallels not drawn: … undeclared`.

## `accessibility`

Needs the six tool/holder dimensions (radius, flute length, OAL, projection,
holder radius, holder gauge length) and a vise without input debt; otherwise `unknown`
(`selected tool/holder dimensions are unmeasured or unavailable` or the
fixture reason). On the claimed face set the kernel samples a cell-centred
5×5 UV grid per face plus 2–12 points along every boundary edge and gives
each sample one prescribed tool pose (the PLAN §4.2 convention, confirmed
with the user): the cutter cylinder (radius, flute length) stands with its
tip at the sample's Z and its axis offset from the sample by the cutter
radius along the in-plane (XY) component of the outward normal, so a wall
sample gets a cylinder touching the wall and a horizontal floor sample gets
no XY offset (a cutter stands on a floor; shifting it along the full 3-D
normal would float it a radius above the floor). The holder cylinder (gauge
diameter, gauge length) starts `projection_mm` above the tip. Both are
intersected with the part minus the op's own region plus the jaw boxes. The
own region is the material within one radius of the op's claimed faces and,
around every sharp concave edge shared by two of them, the radius cylinder
minus the open-corner air wedge in front of both faces (a full cylinder
there used to carve away a neighbouring pin near the corner and hide a real
hit). Downward-facing samples count as occluded. The engine's own tests
(`tests/test_kernel_geometry.py`, FreeCAD required) pin the discriminations:
a boss beside a claimed plate top is a hit naming the boss's cylinder face
while the boss's own side wall is not; a wall claimed together with its
floor is excluded, the same wall claimed by another feature occludes; the
dimensioned jaws occlude the holder only when they stand high enough.
Numbers: `sample_count`, `tool_hits`, `holder_hits`, the six inputs, and
`certain_tool_hits` / `certain_holder_hits` when the engine reports the samples
that hit regardless of the undeclared jaw overhang.

- `{subject}: selected cutter or holder is certainly occluded by part/fixture material.` (error: any hit; also raised from `certain_*_hits` while the aggregate counts are unknown because other samples fall in the undeclared jaw overhang)
- `{subject}: sampled claimed faces clear the selected cutter and holder cylinders.` (pass)
- `{subject}: offset-cylinder sampling is unresolved.` or the kernel's per-fact reason (unknown; includes samples in the undeclared jaw overhang with no certain hit, an own-region boolean that failed, or a sample without a defined normal)

Both verdicts are about the prescribed poses only: the rule stands one
cylinder per sample at the normal-offset position and asks whether that pose
is blocked. An error says those poses are blocked, not that the face is
unreachable by any approach; a pass says those poses clear, not that a
toolpath exists or that every pose along it clears. Neither is a swept-volume
or search-based reachability proof.

## `reach`

Needs `flute_len_mm`. The kernel measures, for each upward-facing sample, the
highest part material within the cutter radius + 0.05 mm of the offset tool
axis, and reports the largest such height above a sample as
`reach_depth_mm`; `holder_wall_hits` counts samples whose holder cylinder
(starting `projection_mm` above the tip) intersects the part, and needs the
holder radius, gauge length and projection. Numbers: `reach_depth_mm`,
`flute_len_mm`, `oal_mm`, `holder_wall_hits`.

- depth ≤ flute: `entry-to-floor depth is within the selected flute length.` (pass)
- depth > OAL: `entry-to-floor depth exceeds the selected tool OAL.` (error)
- depth > flute with holder wall hits: `depth exceeds flute length and the holder intersects walls.` (error)
- depth > flute, ≤ OAL, zero holder hits and both holder dimensions known:
  `depth exceeds flute length but fits OAL with the holder cylinder clear of walls.` (pass)
- otherwise `entry-to-floor depth or holder wall clearance is unresolved.` (unknown)

The long-tool rescue therefore requires a measured holder; an unknown holder
never passes a beyond-flute depth.

## `internal_corner_radius`

Needs `radius_mm`. The measured quantity is concavity in the section
transverse to the tool axis, which is what limits a cutter of that radius:
a concave cylindrical claimed face whose axis is parallel to +Z contributes
its radius, and a sharp concave edge between two claimed faces that runs
parallel to +Z contributes 0. Horizontal concave edges (a pocket floor
meeting its wall) are not corners for this rule: a flat endmill cuts them.
A concave cylinder with an off-axis axis, an oblique concave edge, or any
other concave curved claimed surface cannot be reduced to one radius and
makes the row `unknown` with that face/edge named. Numbers:
`corner_radii_mm` (sorted), `tool_radius_mm`, `minimum_corner_radius_mm`.

- no such corners: `claimed faces have no concave edges perpendicular to the tool axis.` (not_applicable)
- `concave corner radii admit the selected cutter.` (pass)
- `a claimed internal corner is smaller than the selected cutter radius.` (error)
- `concave edge radii are unresolved.` or the kernel's reason (unknown)

The rule does not certify a floor fillet or bottom radius against the cutter.

## `coverage`

One row for the whole part. Every imported face must be in the union of the
face sets claimed by cutting operations and `stock.as_is_faces`. Numbers:
`face_count`, `claimed_face_count`, `unclaimed_faces` (their references, or
`imported face index <n>` when no reference names them), and
`mapping_errors` when present.

- `invalid STEP face reference(s): …` (error)
- `cutting claims or as-stock face references are unknown or unmapped.` (unknown: any unknown action, unmapped feature or unknown/omitted `as_is_faces`)
- `faces have no cutting op or as-stock claim: …` (error)
- `every imported face is claimed by a cutting op or declared as-stock.` (pass)
- `Imported STEP face inventory is unresolved.` (unknown)

## `finish_coverage`

One row per feature. A feature with a known `requirements` list that neither
lists nor declares `finish_ra` is `not_applicable` (`drawing declares no finish
requirement`); an unknown/omitted requirement list or an unknown `finish_ra`
value is `unknown`. Otherwise every face of the feature must be claimed by a
finishing cut. Numbers: `finish_ra`, `required_faces`, `uncovered_faces`.

- `finish-required faces lack a finishing cut.` (error)
- `every finish-required face is claimed by a finishing cut.` (pass)
- `finish face references or finishing operation claims are unresolved.` (unknown)

## `vise`

One row per setup. Non-vise holding (`kind` ≠ `vise`) is `not_applicable`
(`{setup}: vise has no vise grip-zone facts for {kind} holding.`); unknown
holding identity or any missing pose/dimension is `unknown` with the job's
reason. With the jaws placed the kernel reports `width_mm` (part extent
between the inner jaw planes), `contact_grip_mm` (per jaw, the merged length
of planar part faces lying in that jaw plane within the zone; a line contact
is measured when no planar face touches), `parallel_pair` (both jaw planes
have planar contact faces) and `claimed_in_jaws` (claimed faces sharing area
with a jaw box). Numbers: those plus `opening_mm`, `required_grip_mm`,
`parallels_height_mm`. Errors join with `; `:

- `gripped faces are not a parallel pair`
- `part width exceeds vise opening`
- `both jaws do not provide the declared grip`
- `claimed faces enter jaw solids: <refs>`
- pass: `parallel gripped faces, opening, both-jaw grip and claimed-face exclusion fit declared parallels.`
- unknown: `vise contact geometry is unresolved.` or the kernel's reason

Declared parallels are an existence/height input; the rule does not confirm the
parallels were installed, the part was seated, or the vise torqued.

## `thin_wall_under_clamp`

One row per setup. Non-vise holding is `unsupported`
(`{setup}: thin_wall_under_clamp has no vise grip-zone facts for {kind}
holding.`). Inside the jaw zone the kernel runs clamp-direction lines through
the part on six Z levels and 8–64 columns along the jaws (about 1 mm pitch),
keeps only lines that meet material at both jaw planes (a loaded wall), and
reports the thinnest material interval among them as `min_wall_mm`; no loaded
line is a named debt. The rule compares that with
`shop-policy.numbers.thin_wall_floor_mm`; a `numbers_verify` flag that is
true or unknown makes the floor unknown. Numbers: `min_wall_mm`,
`thin_wall_floor_mm`, `method`.

- wall ≥ floor: `minimum wall inside the grip zone meets the shop floor.` (pass)
- wall < floor and `hold.method` is one of `soft_jaws` / `soft jaws` / `mandrel` / `tape` / `wax` (case-insensitive): `wall is below the shop floor with a named protective holding method.` (pass)
- wall < floor, unknown method: `wall is below the shop floor and protective holding method is unknown.` (unknown)
- wall < floor, other method: `wall is below the shop floor; name soft jaws, mandrel, tape or wax.` (error)
- otherwise `grip-zone wall thickness or shop thin-wall floor is unmeasured.` (unknown)

The shipped policy keeps `thin_wall_floor_mm = "unknown"` with
`numbers_verify = true`, so this rule stays `?` until the shop measures a floor.

## Renders

For each setup with a numeric frame the kernel returns a 640×480 PNG: an
orthographic, z-buffered, flat-shaded software rasterization of its own
tessellation of the transformed part (grey, claimed faces blue), the certain
fixed and moving jaw boxes (two browns), the possible-jaw strips when the
lateral centre is undeclared (two pale tints) and the parallels when drawn
(grey-green). It is written by the engine's own PNG encoder with no
timestamp, text, font or machine-specific metadata, so the bytes are
reproducible across runs and cache hits. Alongside the image the engine
returns `render_scene = {jaws, parallels, debts}`: `jaws` is `absent`
(unplaced; debt `jaws not drawn: <fixture reason>`), `exact` or
`lateral_undeclared` (debt `jaw position along <axis> is undeclared (no
jaw_center_along_mm): dark jaws span only the part's <e> mm grip-zone
extent; light strips show where the other <w−e> mm of each <w> mm jaw may
lie`); `parallels` is `absent` (no usable hold inputs: non-vise holding or
a vise with dimension/pose debt, as in the shipped rocker whose
`verify = true` vise yields `jaws not drawn: Fixture pose/dimensions
unmeasured or unavailable: …`), `exact` or
`not_modelled`. `fixture_rendered` is true only when the jaws are placed and
the debt list is empty, i.e. exact jaws and exact parallels. Everything else
is a partial picture with its debts spelled out; a part-only or envelope
picture is not a holding proof. How the file is named, hashed into the
report and captioned is in
[report binding](report-and-telemetry.md#kernel-renders).

## Limits

- Lathe setups: no chuck/collet solid exists; `vise` is `not_applicable`,
  `thin_wall_under_clamp` is `unsupported`, and `accessibility` needs placed
  jaws so lathe cutting ops stay `?`. `reach` and `internal_corner_radius`
  still measure the B-rep along the declared frame's +Z when the tool
  dimensions are known; that axis is the frame's, not a lathe spindle model.
  Lathe headroom stays `unsupported` as before.
- Only a vise with explicit `jaw_height` / `jaw_width` / `jaw_depth` /
  `opening` and `verify` absent/false is modeled, seated at the part's
  lowest Z. The exact jaw pose along the jaws and the parallel solids exist
  only when the plan authors `jaw_center_along_mm` and
  `parallels_centres_mm` and the parallels row measures height, length and
  width; otherwise the render is an envelope or part-only view with named
  debts. The shipped example vise is `verify = true` and has no `jaw_depth`,
  and the shipped parallels have no length/width; those are debts to
  measure, not values to invent.
- Accessibility and reach are sampled/projected measurements with a fixed
  grid, not full swept toolpath simulation; a feature narrower than the
  sampling can be missed between samples. Chatter, clamp deformation and the
  PLAN §4.6 residue remain outside every rule.
- A `verify = true` tool, holder or fixture, an unknown frame, or an unknown
  `thin_wall_floor_mm` keeps the corresponding rows `?`; no row is `pass`
  without every input it names.
