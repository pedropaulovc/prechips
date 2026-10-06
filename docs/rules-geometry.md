# Geometry and workholding rules (M4, FreeCAD kernel)

The seven PLAN §4.2–4.3 kernel rules measure the bound finished STEP faces
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
JSON job per candidate (STEP path/digest, feature and explicit op face claims,
authored stock envelope and `stock.as_is_faces`, setup order/frames/stock chain,
hold geometry and cutting dimensions/endpoints), sends every job that is
not already cached to **one** `freecadcmd.exe <freecad_job.py> -- INPUT_JSON
OUTPUT_JSON` subprocess as a batch (`compare` therefore spawns one process for
all its candidates), and memoizes each result on its bundle so the seven rules
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
every row). The report keeps all seven rows. Checked readiness therefore needs
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
therefore misses; moving the bundle does not. Host-only action/finishing metadata,
tool OAL after projection is resolved, protective hold-method text, and the
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

## Milling-only approach model

The engine's directional claims and prescribed cutter/holder poses approach
along −setup Z. This is a milling model, not a radial turning approach. An
operation whose resolved machine kind is `lathe`, or whose action is explicitly
`turn`, `rough_turn`, `finish_turn`, `profile_turn`, `form_dome`, `form_relief`,
`part_off` or `cut_to_fit`, has `unsupported` approach-dependent rows, with
the reason exactly:

`lathe approach model not implemented (engine approaches along -Z only)`

Invalid STEP face references remain `error` before this boundary; missing or
unmapped claimed references remain `unknown`. Otherwise `accessibility`,
`reach` and `internal_corner_radius` do not use the raw engine's lathe
direction, collision, reach, stock-removal or corner verdicts. A raw lathe
`claimed_indices` array never establishes cutting or finishing coverage.
Supported milling claims and explicit as-stock faces can still establish
coverage independently; a lathe-only claim cannot produce either a pass or a
false far-side failure. A radial lathe approach model is a prechips follow-up,
not harmonic-analyzer export debt.

The shared `profile`, `form`, `groove`, `rough_groove` and `finish_groove`
actions do not alone identify turning: a resolved mill receives the normal
milling direction verdict, not an unsupported exemption. With an unresolved
machine kind they conservatively remain unsupported; a resolved lathe is
always unsupported. Explicit turning actions listed above retain the boundary
even on a missing or nonlathe machine.

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
  Any other
  holding kind carries `Fixture solids are not declared for this holding
  kind.`: no chuck, collet, fixture-plate or clamp solid exists in M4.

Tool axis is the setup frame's +Z. The part is transformed into the declared
setup frame; the frame is the author's declaration, not a measured setup.

## In-process stock

Each setup's checks and image use the material explicitly selected by `stock_in`.
`"stock"` selects a single supply; `"stock.<id>"` selects a built-up component;
any earlier setup id selects that setup's output, even when it is not the
immediately previous setup. A nonempty array joins the selected solids by
Boolean union in model coordinates. Unknown or forward authored references
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
known future planned-hole columns, with their finite caps, stay stock; and
the removal must not split an original input solid. A violation is not an
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
so they never enter hit counts; they exist for the picture and for the
`declared parallel centred at [x, y] intersects the <side> jaw` debt. With
any of those inputs missing the scene records `parallels not drawn: … undeclared`.

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
interior floor samples have no XY offset. The tip is at the sample's Z,
except as the rough leave below moves it.

A rough milling op's scalar `rough_allowance_mm` (a) is consumed by the
engine as a leave in millimetres normal to the finished surface. Each rough
sample point first moves `a` along the face's unit outward normal, then takes
the ordinary cutter-radius `r` shift along the in-plane (XY) normal; the
concave floor-edge and corner constraints below use radius `r + a`. The
derived output stock protects the finished solid offset outward by `a`, which
retains the radial and axial leave, drafted faces included, and a later
finishing op that claims those faces removes the leave as its own derivable
allowance. An explicit `to_z` caps the endpoint rather than adding to the
leave: the tip is the higher of `to_z` and the floor plus its leave, so a
`to_z` already at the rough floor plus a 0.2 mm leave is that endpoint, not
0.4 mm above the floor. The tip never goes below the retained leave, and
numerical lift still separates it from the finished face. An unknown
authored leave makes the op's accessibility `unknown` and later stock that
depends on it debt. The protected solid is built by offsetting the finished
solid outward by the leave. Where that offset's arc join cannot be built (a
blind cone can make it fail), an intersection-join offset may be used
instead, but only if it is valid, contains the finished solid and keeps the
same solid count. It is conservative and leaves extra material at convex
corners, never less than the leave, and there is never a fallback to the
nominal finished solid or a zero leave. If both constructions fail, the
result is named offset debt.

**User decision, 2026-10-05:** at a concave edge shared by a floor and a
rising wall, the floor-sample cutter axis shifts one cutter radius into the
floor, away from the wall. At a two-wall concave floor corner the pose is
tangent to both walls; nearby concave-corner edge samples also use both-wall
tangency when the second wall lies within a cutter radius. This replaces the
former boundary-centred floor pose; convex edges and ordinary interior
samples are unchanged. Convex wall/wall island vertices retain their legacy
samples without an added corner pose. Tangency selects a pose, not a
corner-radius certification. Floor-only claims do not certify wall/wall
corner radii: `internal_corner_radius` still checks a sharp wall/wall corner
only when the op claims both walls, with its existing scope unchanged.
Adjacent finished walls are not removed to manufacture clearance, and
undercut or leaning walls remain obstacles.

The holder cylinder (gauge diameter, gauge length) starts `projection_mm`
above the tip. Both cylinders are intersected with actual setup-entry
material minus a thin inward offset shell of **that sampled face only**,
plus the jaw boxes. The flute also excludes only this op's derivable
outside-finished allowance; the holder still sees it. The shell removes
numerical self-contact, not a cutter-radius slab and not another finished
face of the same feature. A cutter wider than a claimed groove therefore
still intersects the opposite claimed wall. Holding, rendering and holder
obstacles use actual setup-entry stock; no pose borrows another op's removal.

Claimed concave cone or sphere point caps are not blanket-exempt. Only a hole
op's own known matched cap is: a cap (as defined for planned-hole columns)
that shares a real edge with a claimed concave cylindrical bore parallel to
setup Z and lies wholly below that bore, closing the end away from the tool.
An upward-facing cap is not matched. For an op whose hole cut resolves, a
sample on that cap uses the unmodified actual setup-entry stock instead of the
own-face offset shell, which cannot be built at a cone apex; the on-axis
cutter's numerical-lift shrink already removes self-contact, and the holder
also sees the full entry stock. The cap's actual collision is still checked:
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
body, shrunk by numerical lift, against part and jaws alike; the gross
cylinder only culls. Ream, bore, tap and counterbore remain flat-bottomed
operation-diameter cylinders.

Depths follow [tip endpoints](rules-operations.md#blind_depth-tip-endpoints).
A spot's `depth_mm` is its apex tip depth below the entry. A drill's
`depth_mm` is its full-diameter depth; its tip lies a further point length
`r / tan(point_angle_deg / 2)` deeper. An op `to_z` is the absolute actual tip,
with nothing added. A through drill's full diameter exits each matched bore's
actual axial bottom, so its tip is one point length (plus numerical lift)
below that; other through actions end at the bore bottom plus numerical lift,
not the raw-stock bounding-box bottom.
Spot and tap operations honor an explicit depth even when the feature declares
`thru = true`; that feature fact does not extend their local removal past the
authored endpoint. `stock_state.top_z` and `entry_z` are machine-frame
millimetres, and operation `depth_mm` is millimetres even when feature units
are inches. Tap fallback feature-depth bands are converted to millimetres.

When the op radius exceeds a matched bore's radius, every hole action except
a spot also removes that bore's own wall out to the op radius. No fixed radial
cap limits that excess; the sizing rule owns the drill or reamer diameter. A
failed own-wall offset is named debt. A spot never widens its own bore, so a
spot cone reaching past the finished bore mouth still meets finished material.

For milling, a far-side face (outward normal opposing setup +Z by more than
90°) is an invalid cutting claim, reported as an error naming the face before
tool-dimension debt can hide it.

The kernel tests pin the discriminations: a boss beside a claimed plate top
is a hit naming the boss face; an offset cutter tangent to its claimed side
wall clears while the sample-centred mutant intersects the wall; a Ø10 cutter
in a 6 mm through-groove hits the opposite wall; dimensioned jaws occlude the
holder only when they stand high enough. The concave floor-edge convention
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
For a hole operation, its own bore radius is a diameter-sizing question,
not an `internal_corner_radius` limit. Likewise its own known matched point
cap (see accessibility) is its actual tool shape, not an internal corner;
any other claimed concave cone or sphere, including a wider countersink or an
unrelated cap, remains the unreduced curved surface below.
Floor-only claims do not certify a wall/wall corner radius. A sharp wall/wall
corner is checked when the op claims both walls; tangent floor poses do not
expand this rule's claimed-face scope.
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
finishing cut. Numbers: `finish_ra`, `required_faces`, `uncovered_faces`, and
`unformed_caps` when present.

A claimed hole cap is credited only when its `complete_form` op's
`cap_completion` measured it clear (see [accessibility](#accessibility)). This
holds for the last setup and for any output no setup consumes. A cap that
still touches stock stays uncovered and is listed in `unformed_caps`. An
unmeasured cap makes the row `unknown` unless another face already errors.
A tap's claim never credits a cap its thread's drill left unformed.

- `finish-required faces lack a finishing cut.` (error)
- `finish-required hole cap(s) still touch stock after their complete-form cut's setup.` (error)
- `every finish-required face is claimed by a finishing cut.` (pass)
- `finish face references or finishing operation claims are unresolved.` (unknown)
- `hole cap completion is unknown: {reason}.` (unknown)
- `lathe approach model not implemented (engine approaches along -Z only)` (unsupported)

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

For each setup with a numeric frame and derivable incoming stock the kernel
returns a 640×480 PNG: an orthographic, z-buffered, flat-shaded software
rasterization of that stock (grey, exposed claimed surfaces blue), the certain
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
a vise with dimension/pose debt, debt `jaws not drawn: <fixture reason>`),
`exact` or `not_modelled` (as in the shipped rocker S1, whose measured vise
and declared `jaw_center_along_mm` give exact jaws while the parallels lack
`width` and `parallels_centres_mm`: debt `parallels not drawn:
parallels_width_mm, parallels_centres_mm undeclared`). `fixture_rendered` is
true only when the jaws are placed and
the debt list is empty, i.e. exact jaws and exact parallels. Everything else
is a partial picture with its debts spelled out; a stock-only or envelope
picture is not a holding proof. Non-derivable stock produces no figure. How
the file is named, hashed into the
report and captioned is in
[report binding](report-and-telemetry.md#kernel-renders).

## Limits

- Lathe setups: no chuck/collet solid exists; `vise` is `not_applicable`,
  `thin_wall_under_clamp` is `unsupported`, and directional `accessibility`,
  `reach` and `internal_corner_radius` are `unsupported` under the milling-only
  approach model. A numeric frame or tool dimension cannot turn the axial
  engine verdict into a radial lathe proof. Lathe headroom stays `unsupported`
  as before.
- Only a vise whose `jaw_height` / `jaw_width` / `jaw_depth` / `opening`
  facts each resolve without their own debt is modeled, seated at the part's
  lowest Z. The exact jaw pose along the jaws and the parallel solids exist
  only when the plan authors `jaw_center_along_mm` and
  `parallels_centres_mm` and the parallels row's height, length and width
  facts are accepted; otherwise the render is an envelope or part-only view
  with named debts. The shipped example vise records measured
  `jaw_height` / `jaw_width` / `jaw_depth` / `opening` (its item-level
  `verify = true` is identity debt for the declared-input rules, not a
  geometry veto), while the shipped parallels declare no `width` and no
  shipped plan declares `parallels_centres_mm`; those are debts to declare,
  not values to invent.
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
