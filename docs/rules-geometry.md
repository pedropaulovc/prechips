# Geometry and workholding rules (M4, FreeCAD kernel)

The eight PLAN §4.2–4.3 kernel rules measure the bound finished STEP faces
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

The citation list of every geometry finding starts with that PLAN row, adds
`kernel: STEP SHA-256 <digest>; FreeCAD B-rep measurements` when the manifest
digest is known, then the feature (exported `features.<name>: faces and
requirements` or author-owned `plan.joint_features.<name>` plus its citations),
the setup (`plan.setups.<id>: frame and hold`, the resolved fixture/parallels
rows and their citations, the frame citation) and the operation
(`plan.setups.<id>.ops.<n>: selected
action/tool/holder`, the resolved tool/holder rows). `thin_wall_under_clamp`
also cites `shop-policy.numbers.thin_wall_floor_mm`. The kernel itself reports
measurements only; it never emits citations.

## One job, one kernel, no network

A run evaluates geometry at most once per bundle. The CLI builds a canonical
JSON job per candidate (STEP path/digest, feature and explicit op face claims,
authored stock envelope and `stock.as_is_faces`, normalized transient joint
primitives and assembly declarations, setup order/frames/stock chain,
hold geometry and cutting dimensions/endpoints), sends every job that is
not already cached to **one** `freecadcmd.exe <freecad_job.py> -- INPUT_JSON
OUTPUT_JSON` subprocess as a batch (`compare` therefore spawns one process for
all its candidates), and memoizes each result on its bundle so the eight rules
read the same facts. The subprocess has a 300 s limit, reads its input file,
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

Plan-owned joint cylinders are separate analytic targets, labelled with their
`plan.joint_features.<id>` provenance. They are never assigned synthetic STEP
entity references and never enter final face, source, as-is, coverage or corner
mappings. Dimensional and operation consumers use the resolved feature mapping;
final `coverage` and `finish_coverage` still iterate only the original manifest.
Neither transient completion nor joint filler proves a final surface was cut.


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
toolpost body (holder `body_depth` radially, `body_width` along Z). Claimed
faces must be surfaces of revolution about setup Z on the outside; other faces
are claim errors; internal (bore) claims stay `unknown`. Samples on the
claimed meridians are checked against the held stock minus this op's own
turned removal plus modeled fixture obstacles, including the rotating
envelopes of placed chuck jaws.
Reach is the material radius within the nose's axial band; corners are concave toroid or
sphere profile radii (a sharp shoulder is 0) compared with the nose radius.
Removal is revolved: `to_z` faces a band from the innermost claimed radius to
the stock OD; profile ops close each claimed meridian to the OD within the
declared `z_from`/`z_to` span, then cut the finished part back out. That
in-process stock is inverse-transformed back into model coordinates and can
feed any later setup that explicitly selects it through `stock_in`, not only
the immediately following setup. Removal checks each input solid separately:
splitting any one input piece into multiple retained pieces leaves the output
unresolved. Separate supplies do not authorize an unconnected assembly.

The turning model is a deterministic radial sampled necessary-condition screen.
It does not prove tool paths, chip flow, insert clearance angles below centre height, boring bars or
internal features, grooving/part-off blade geometry, or chatter. Every turning
input must be measured and accepted; otherwise the row is `unknown`.

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
  neither is an engine input. Accessibility does not require OAL when the
  selected projection is known.
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
two disjoint material branches whose combined ancestry contains exactly two
physical supply components. Joining a two-component subassembly to another
component is bad input even though its array has only two references.
There is no unconditional Boolean-union path, and more-than-two-piece joint
graphs are not implemented. Unknown or forward authored references
are bad input (exit 3), including authored `"unknown"` as a source. Omitted
`stock_in` remains named stock debt, never an inferred linear route. Supplies and outputs all stay in the
model frame; assembly does not implicitly transform a reference.
Joined references must have disjoint supply ancestry. Duplicate entries or
`["stock", "S1"]` when S1 consumes stock are bad input (exit 3), naming the
shared supply ancestor. Independent forks may start from the same supply again
as route alternatives, but cannot join that material lineage twice.
Each setup output subtracts only that setup's derivable claimed removals from
its selected input. Current-setup removals do not change current holding facts,
image, reach or holder obstacles. The flute alone excludes the current op's own
derivable allowance above the sampled finished face within its claimed clearing
footprint: that material is being cut, not an obstacle. No other op's removal is
borrowed. Finished face indices stay bound to the original STEP even when
booleans change the stock's face order.

Mill headroom's X/Y travel screen consumes
`kernel.setups.<id>.stock_bbox_mm` for component stock, an earlier setup's
output, and a joined pair. That box is the actual stock placed in the setup
frame **at entry**; it is neither the finished-part box nor a sum of raw supply
boxes. A missing or withheld entry box leaves travel unresolved. Equality
with a measured travel limit passes; exceeding it fails.

A machine with inventory `kind = "bench"` or `"manual"` whose non-empty
operation list contains only `fit` and `inspect` needs no DRO or spindle
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
only operations naming a transient feature. Overlapping spigot ownership is
refused rather than resolved by ordering. Ordinary `stock_removal_bounds`
cannot grant permission to remove protected finished material.

For a cylindrical joint the kernel verifies every extreme of the declared
diametral clearance/interference bands, collinearity, finite engagement and
branch-specific completed preparation. Incompatible known bands are certain
errors, not unknown stock. Fill is derived only from engagement and the
declared joining process, never an arbitrary authored allowance. Actual branch
overlap is forbidden except for a press-fit interference annulus. A
straight-axis insertion sweep must be free of socket-stock obstruction;
a captive or shouldered fit does not pass merely because its final pose fits.

Surface joints use finite analytic rectangle `interfaces`, not finished STEP
face references. Each must lie inside the final solid, with essentially full
rectangle contact from both pieces and no bulk overlap. Plane-side ownership
protects each component's final share during preparation: the first `stock_in`
reference owns the negative-normal side, the second the positive-normal side.
Several contact
patches may describe the same two pieces; they do not support a multi-piece
graph. Weld or silver-braze process text alone cannot connect separated pieces,
and surface joining adds no filler solid.

At assembly a final-material backstop checks the portion of finished geometry
inside the consumed raw envelopes against the actual branch outputs plus
authorized derived fill. A failed fit, lost material, missing preparation or
blocked insertion withholds stock output. A later finished bore must really
remove the joined material/fill; earlier socket cutting earns no final bore
coverage. Original exported geometry and its hash remain the provenance anchor.


For a derivable face footprint, removal is clipped to the authored `to_z`
endpoint and to material outside the finished solid. Every claimed face with
a horizontal normal component is checked for remaining overstock above `to_z`,
including drafted walls whose +Z sweep is nonzero. Exact face contact catches
small retained ears; nearest-contact probes inset from the face boundary
distinguish a drafted sliver from legitimately retained neighbours.
An operation can declare numeric `stock_removal_bounds` (one setup-frame box)
to clear only outside-finished material inside that volume. With a known cutter
radius, its XY extent must fit the union XY bounding box of its direction-valid
claimed faces dilated by that radius. Excess is a named `stock_removal_error`,
not clearance for a later setup. An unknown radius leaves the extent check `?`
with a reason naming the missing cutter radius, never a zero-radius error;
later stock stays unresolved. Each claim must touch the box and every removed
piece must border a claim. Synthetic geometry fixtures
author these preparation volumes and numeric supply allowances; their target
setup checks the derived material. Preparation tool/fixture debt stays visible,
and the fixture policy explicitly requires the target, not fabricated roughing
clearance. The reference rocker declares its raw 310 × 45 × 16 mm S1 supply explicitly, so S1 is drawn
as that blank. Its rough-profile notes retain rails, ears and a 0.40 mm web,
but provide no numeric lateral interruption mask. S2/S3 therefore name the
unresolved S1 profile removal rather than drawing the finished arm or
inventing rail dimensions. A known current setup remains checkable/drawable
even when its output stock is unresolved for the next setup.

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
any of those inputs missing the scene records `parallels not drawn: … undeclared`.

## `accessibility`

Needs the five tool/holder dimensions (radius, flute length, projection,
holder radius, holder gauge length) and a vise without input debt for a pass.
Within the supported milling domain, missing inputs normally yield `unknown`,
but positive observed minimum tool or holder hits still error despite unknown
stock, fixture or dimensions. Invalid face claims and rejected clearing bounds
remain errors first.
On the claimed face set the kernel samples a cell-centred
5×5 UV grid per face plus 2–12 points along every boundary edge and gives
each sample one prescribed tool pose (the PLAN §4.2 convention, confirmed
with the user): the cutter cylinder (radius, flute length) stands with its
tip at the sample's Z and its axis offset from the sample by the cutter
radius along the in-plane (XY) component of the outward normal, so a wall
sample gets a cylinder touching the wall and a horizontal floor sample gets
no XY offset (a cutter stands on a floor; shifting it along the full 3-D
normal would float it a radius above the floor). The holder cylinder (gauge
diameter, gauge length) starts `projection_mm` above the tip. Both are
intersected with the setup's material minus a thin inward offset shell of
**that sampled face only**, plus the jaw boxes. The flute also excludes only
this op's derivable outside-finished allowance; the holder still sees it.
The shell removes numerical self-contact, not a cutter-radius slab and not
another finished face of the same feature. A cutter wider than a claimed
groove therefore still intersects the opposite claimed wall. For milling, a
far-side face (outward normal opposing setup +Z by more than 90°) is an invalid
cutting claim, reported as an error naming the face before tool-dimension debt
can hide it.

The kernel tests pin the discriminations: a boss beside a claimed plate top
is a hit naming the boss face; an offset cutter tangent to its claimed side
wall clears while the sample-centred mutant intersects the wall; a Ø10 cutter
in a 6 mm through-groove hits the opposite wall; dimensioned jaws occlude the
holder only when they stand high enough. Floor poses remain centred on their
samples, including boundary samples: a wall can block such a prescribed pose
even when some other cutter centre could cut that point. There is no pose search.
Numbers: `sample_count`, `tool_hits`, `holder_hits`, the five inputs, and
`certain_tool_hits` / `certain_holder_hits` when observed hits are definite
despite unresolved stock, inputs, poses or undeclared jaw overhang.

- `{subject}: selected cutter or holder is certainly occluded by part/fixture material.` (error: any hit; also raised from positive `certain_*_hits` while aggregate counts or other inputs are unknown)
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

The long-tool rescue therefore requires accepted holder gauge-diameter,
gauge-length and projection facts; an unknown holder never passes a
beyond-flute depth.

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
A concave cylinder with an off-axis axis, an oblique concave edge, or any
other concave curved claimed surface cannot be reduced to one radius and
makes the row `unknown` with that face/edge named. Numbers:
`corner_radii_mm` (sorted), `tool_radius_mm`, `minimum_corner_radius_mm`.
These are finished-solid facts, independent of unknown in-process stock;
a known sharp corner remains an error even when reach cannot be measured.
The comparison uses a 0.005 mm numeric tolerance: a concave radius admits the
cutter when it is at least `tool_radius_mm - 0.005`. STEP coordinates commonly
write only 5–6 significant digits, so sub-tolerance import/kernel rounding
must not turn a nominally equal radius into an error. This is numeric tolerance,
not a machining allowance: a 0.004 mm deficit passes; a 0.006 mm deficit errors,
and a genuinely sharp corner still fails.

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

Only supported, direction-valid milling claims are credited. If every remaining
face has a mapped cutting claim but needs the unsupported lathe approach model,
the row is `unsupported` with the milling-only-model reason above. Known missing
claims outside that unsupported set still error. Invalid references outrank
unsupported; unresolved claims/as-stock references remain `unknown`.

In a mixed error, `unclaimed_faces` names only faces with genuinely missing
claims, while `unsupported_faces` / `unsupported_indices` separately name
possible lathe-model coverage. An unsupported-only row's remaining-face list
means coverage is not proved; it is not an absence-of-operation diagnosis.

## `finish_coverage`

One row per feature. A feature with a known `requirements` list that neither
lists nor declares `finish_ra` is `not_applicable` (`drawing declares no finish
requirement`); an unknown/omitted requirement list or an unknown `finish_ra`
value is `unknown`. Otherwise every face of the feature must be claimed by a
finishing cut. Numbers: `finish_ra`, `required_faces`, `uncovered_faces`.

- `finish-required faces lack a finishing cut.` (error)
- `every finish-required face is claimed by a finishing cut.` (pass)
- `finish face references or finishing operation claims are unresolved.` (unknown)
- `turning action has no approach model off a lathe (the turning model needs a lathe spindle on setup Z)` (unsupported)

Unsupported turning finish cuts name possible coverage only: their raw engine
indices never credit a finishing approach. A feature is `unsupported` when all
of its uncovered faces have mapped turning finish claims. A genuinely unclaimed
face still errors, and a complete set of supported milling finish claims still
passes even when other lathe operations exist. Invalid/missing face mappings
retain their error/unknown precedence.

In a mixed error, `uncovered_faces` names only genuinely missing finishing
claims and `unsupported_faces` lists the model-dependent finishing candidates
separately. The error sentence never labels those candidates as having no cut.

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

One row per setup. Holding other than a vise, a chuck (a lathe `chuck_3jaw` /
`chuck_4jaw`, or a `dividing_head` that names its `hold.chuck`) or a
posed-solids fixture with `clamps` is `unsupported` (`{setup}:
thin_wall_under_clamp has no vise grip-zone facts for {kind} holding.`), as
is a dividing head that names no chuck. Inside the jaw zone the kernel runs clamp-direction lines through
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
returns a 640×480 PNG: an orthographic, z-buffered, flat-shaded software
rasterization of that stock (grey, exposed claimed surfaces blue), the certain
fixed and moving jaw boxes (two browns), the possible-jaw strips when the
lateral centre is undeclared (two pale tints), the parallels when drawn
(grey-green) and every other drawn fixture solid in its role colour (risers,
chuck jaws and body, dividing head, centre and quill, authored fixture
solids, clamps). It is written by the engine's own PNG encoder with no
timestamp, text, font or machine-specific metadata, so the bytes are
reproducible across runs and cache hits. Alongside the image the engine
returns `render_scene = {fixture_kind, jaws, parallels, components, debts}`.
`fixture_kind` is the inventory holding kind; `components` lists every drawn
solid as `{name, role, exact}` (`exact = false` only for the vise's
lateral-undeclared jaw extents). For a vise, `jaws` is `absent`
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
solid that intersects the entry stock, or unequal scroll-chuck contact
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
- A length fact carrying its own `verify = true` / `"unknown"` or an
  incomplete `measured` record, a missing dimension, an unknown frame, or an
  unknown `thin_wall_floor_mm` keeps the corresponding rows `?`; an
  item-level `verify = true` on a tool, holder or fixture does not. No row is
  `pass` without every input it names, and no geometry pass is an M5
  measurement claim.
