# Coordinates and DRO zero

Both rules produce one subject per setup. Nominal numeric recipes and tables can
remain useful while their status is unknown; they are not cleared toolpaths or
measured first-article evidence. Report numbers retain precision. Bench drawing
station/feature reference points use the dimension's declared drawing precision;
a known number without one prints its own value (six significant digits) rather
than `?`, which stays reserved for unknown values. Operation-derived rows,
computed tip targets, Z stations and contour cutter-centre tables always print
their own value, never rounded to a drawing dimension's display precision.
Contour tables use manifest geometry even when the M4 kernel rules run on the
same bundle; only feature location may read an already-present kernel result
(below), and these rules never start the kernel.

## `coordinates`

A feature-local point is transformed to model coordinates as
`model = feature_frame.origin + sum(local[j]*feature_frame.basis[j])`.
A setup coordinate is `(model - setup.origin) dot setup.basis[axis]`.
Feature frames always come from the exported manifest. The setup frame is the
exported manifest frame of that name, otherwise the plan-owned
[`frames`](plan.md#frames) entry; a plan frame may not reuse an exported name.
A plan-owned setup frame adds `plan.frames.<name>: author-declared setup frame`
and its own citations to the finding, and its stated `binding` decides whether
the transform is nominal or unbound exactly as for an exported frame.
Unknown components propagate only through nonzero coefficients. Tolerance-band
midpoints never define nominal geometry: explicit `*_nominal` values take
precedence, otherwise only scalar dimensions are usable as nominal geometry.

Worked holes (including threaded holes and counterbores), bosses, and features
used by point/hole operations are located by a numeric three-component `at`
reference point, found in this order (one shared locator,
`coordinates.located_by`, which [`travel`](rules-setup.md) uses too):

1. The feature's own `at`. An explicit `at` wins even when it is `"unknown"`,
   two-component or partially unknown; those keep the setup's `coordinates`
   status unknown, and two-component sketch locations do not imply Z = 0.
2. Without its own `at`, a child naming its parent hole (`hole`, else `parent`;
   a counterbore with `parent = "mount_west"`) takes that parent's `at`
   transformed from the parent's frame. The row records `located_by = <parent>`
   and the finding cites `features.features.<parent>.at` with the parent's `at`
   citations. A parent that does not exist, or has no numeric `at`, leaves the
   row unknown; nothing falls through to the kernel.
3. Without `at` or a parent, the kernel's faces of revolution about setup Z
   (below).

A known point still needs a usable model-to-setup frame transform. Bounds-only
face, rectangular profile and pocket features do not acquire an invented centre
requirement.

**Kernel revolved location, any setup.** The kernel request lists, per setup,
its located features with neither `at` nor a parent (`locate_revolved`); the
engine measures their finished faces of revolution about setup Z in every
setup (a setup with a turning-model operation measures every feature). Such a
feature is located on setup Z through X0 Y0 when the kernel measured every one
of its faces as an external surface of revolution about setup Z through
x = y = 0 ([turned profile](rules-lathe.md), kernel `revolved` facts): the
rows place it at setup `[0, 0, z]` for both ends of its kernel axial span, the
model point is that setup point transformed back through the setup frame, and
the finding cites `kernel: setups.<id>.revolved.<feature>`. On a lathe the rows
are `spindle axis, kernel span start` / `end` and also carry the nominal
diameter and X display; a lathe also tries this for a feature whose own `at`
is not numeric. Off a lathe the rows are `setup Z axis, kernel span start` /
`end`. The axis is never inferred from tolerance bands or model-frame
assumptions. The feature stays unknown when no kernel result is present, the
setup frame binding is unknown, the kernel reports any face not revolved about
setup Z through the origin (off-axis, a flat, a cross boss or hole), an
internal (bored) face, or its facts are malformed or missing; off a lathe that
unknown row carries the kernel's `reason`.

Feature reference centres are distinct from hole tool-tip endpoints (those
belong to `blind_depth`). Lathe rows carry drawing stations, authored operation
endpoints, nominal diameter and radius/diameter X display. An authored local Z
can substitute for an unknown model transform only in an unbound frame; the row
retains `local_from = {op, field, axis}`. This does not bind fitted shaft length
to nominal model geometry. Dome axial samples compute
`radius=sqrt(sphere_radius^2-(z-sphere_centre_z)^2)` at authored steps and include
the exact endpoint. Each row then gets the tool-nose compensation. The selected
tool must not be flagged uncertain, and its nose radius `rn` must be known and
≥ 0. The nose must also be what touches every row. Each row records its contact
normal `normal_deg`, measured from +X (radially outward) toward +Z. For a
right-hand tool feeding toward the chuck, the nose arc spans
`entering_angle_deg + insert_angle_deg − 180` to `entering_angle_deg`: the
trailing edge sets the lower bound and the major edge the upper. Both angles
must be accepted inventory facts. A normal outside that range is cut by an edge
or flank, not the nose, so no nose offset exists there.

When the nose meets every row, its centre lies `rn` out along the sphere's
surface normal `n`. Each row then adds `x_tool_mm = display·(r + rn·(n_r − 1))`
and `z_tool_mm = z + rn·(n_z − 1)`. These are the DRO readings of the imaginary
tool tip when the tool was touched off on an outside diameter (X) and on a +Z
end face (Z), the `zero_check` tool-touch convention, recorded as
`tool_reference`. Then `tool_nose_compensation_mm = rn`, and the sheet prints
tool columns beside the surface columns. The surface columns are never
relabelled as compensated.

Compensation stays unknown, the sheet STOP stays, and `coordinates` is unknown
when any of these holds:

- the nose radius is unknown or negative;
- the tool is uncertain;
- the dome apex faces the chuck, so it is not cut from the +Z touch-off side;
- the tool is not right-hand;
- an entering or insert angle is unknown or does not form an insert;
- any row's contact normal lies outside the nose arc. The reason names those
  rows' Z.

`tool_nose_compensation_reason` names which one applied.

For contours, cutter radius is selected diameter/2. An explicitly rough
operation produces its rough table at cutter radius plus `rough_allowance_mm`
or, if that field is absent, `stock_to_leave_mm`. A non-rough arc or linear
contour carrying `rough_allowance_mm` produces both rough and finish tables:
rough offset = cutter radius + allowance; finish offset = cutter radius. An
unknown authored allowance leaves the rough path unresolved rather than using
zero. Operations without an authored rough allowance keep their finish-only
table. Each profile, arc and exact line-join record names its `stage` (`rough`
or `finish`), so the report and traveler distinguish the two paths even when
they share one operation number. Axial dome samples remain nominal profiles,
not an allowance/tool-nose-compensated rough path.
`arc_table` uses explicit centres, nominal radii and known finite geometry:
a boss is a full circle, a declared upper semicircle is 0–180°, and finite
rocker arcs derive endpoint angles.
Internal/top arcs subtract offset; outside/bottom arcs add it. Samples include
exact endpoints and angular grid checkpoints. `start_deg`/`end_deg` are accepted
schema fields but the current rule derives bounds from geometry rather than
using those fields to override the arc. Finite arc records include exact offset
joins. Every feature linked through `top_edge_feature` contributes its upper
land's line-circle intersection: an outline and separately exported tip lands can
share that top arc. Mirrored −X/+X lands must agree after reflection; an
unknown or inconsistent linked join leaves the top table unknown. The lower
outline also supplies its line-line miter and bottom line-circle intersection,
with mirrored sides explicit. Degenerate joins do not become invented paths.

**Machine contouring.** A row reached by an arc or a diagonal move (both axes
at once) is cut the way the setup machine's inventory `contouring` says
([inventory](inventory.md)):

- `mdi`: each printed row carries the one MDI move that reaches it (`mdi`),
  printed beside the row with the op's `speeds_feeds` feed: `G1 X.. Y.. F..` to
  a table's first row, to and from a kernel clip point and along each join or
  outline edge; between arc rows `G2` (clockwise in the setup top view) or `G3`
  (counterclockwise) `X.. Y.. I.. J.. F..`, with I and J the arc centre less
  the previous printed row. Only an `mdi` full circle is called a continuous
  circle.
- `jog`: one handwheel axis per row. Arc rows add each angle at which the arc
  is tangent to a setup axis, so every step between rows is monotone, and a
  corner row (no angle) between two rows that differ on both axes turns one
  axis, then the other: `(b.x, a.y)` or `(a.x, b.y)`, whichever keeps both legs
  no nearer any wall than the cutter-centre offset (or than the rows it joins,
  if nearer) and lies farther from the walls; neither keeping clear leaves the
  stage unknown and unprinted. Each row names the axis moved to reach it
  (`jog`). The record's `stair_cusp_mm` is the most material a point of the
  stage's target surface (its allowance off a wall, never past a wall's end)
  keeps from the stepped cutter; a diagonal join steps once per printed point,
  so a long join leaves a large cusp. A finish stage holds its largest cusp,
  arc or join, to the arc feature's band on the material side
  (`stair_band_mm`): `dia` (halved) for a full circle, `bottom_radius` or
  `radius` otherwise, from nominal to the upper limit when the cutter runs
  outside the wall radius, else to the lower limit. More than the band is an
  error and withholds the stage's rows; no numeric band leaves it unknown. A
  rough stage's cusp is recorded but not held: its finish pass removes it.
  Single-axis stairs along a diagonal `linear_table` outline edge are not
  computed and stay unknown.
- absent, `"unknown"` or `verify = true`: the rows are checkpoints only and
  the finding is unknown, never pass.

Rasters and outlines whose edges are all axis-parallel need no declared
contouring.

`linear_table` transforms explicit box bounds (or `sweep_bounds` in
`sweep_frame`). Exterior rectangular paths expand by offset. Pockets and faces
are rasters and need a positive `step_mm` no wider than the cutter; a pocket
also needs an explicit open side and enters wholly outside it, stepping
`step_mm` toward its far wall and stopping the offset short of it. A face
sweeps `sweep_bounds`, else its setup-frame `stock_removal_bounds`, with
passes evenly spaced no more than `step_mm` apart centre-on-edge to
centre-on-edge (one central pass when the area is no wider than the step),
stepping from `open_side`, else from the low side of the shorter span. Every
pass runs one cutter radius past both ends of the area. The cycle is one way:
feed the pass, lift to the op's retract Z (its entry stock top plus
`approach_mm`, unknown without it) and rapid back to the next pass's start.
Face ops without a contour print no raster: a box raster could cross retained
material inside the box. Tables are numeric nominal geometry, not cutter
accessibility, fixtures, wall thickness or collision proof; raster passes are
not kernel checkpoints. Unknown/unverified cutter or frame binding keeps status
unknown. M2 lathe feasibility remains unimplemented even where nominal
stations/dome tables are displayed.

**Z levels.** A milling pocket, face or profile op that authors `doc_mm` (mm)
carries `z_levels` on its `operations` entry: levels on the DRO grid, each no
more than `doc_mm` below the one before (the first rounded up from the start
less `doc_mm`, the rest a whole number of grid steps no deeper than `doc_mm`),
ending at its `dro_to_z`. A wall-finishing op (`pocket`, `finish_pocket`,
`profile`, `finish_profile`) starts at its feature's declared setup
`entry_z`, never one an earlier op's floor advanced, else the current top,
since its flank engages the whole wall; any other op starts at its feature's
current entry, else the current top. The traveler prints `Z start → depth in
N levels of doc max`.

**Cutting order.** Arc rows, each join fragment and a closed `linear_table`
outline are listed in the real traverse, judged in the setup top view (setup
XY after the model-to-setup transform, so a part turned over between setups
swaps which mirrored side runs which way). With `n` the cutter-side wall
normal (from the cut wall toward the cutter centre: outward for a convex arc
or outside outline, inward for a concave arc, the offset side of a land) and
`t` the travel, a clockwise spindle (machine `spindle.rotation = "cw"`, viewed
from above looking down setup -Z) cuts `conventional` when `(n × t)·Z > 0`
and `climb` when it is negative; `ccw` inverts both. Each table is reversed
when its geometric order disagrees with the op's `direction`, so the −X join
fragment, the bottom arc and the +X fragment chain end to start. Each record
carries `cut_order` (the authored direction) and `spindle_rotation`. An op
`direction` other than `conventional`/`climb`, an undeclared spindle rotation,
unknown setup points or a degenerate witness set `cut_order = "unknown"` with
`cut_order_reason`, keep the geometric order, and make the setup's
coordinates finding `unknown` with
`Cutting order is unknown: <reasons>.` appended to its message. The traveler
says "rows in cutting order (<direction>, <rotation> spindle)" only for a known
order and otherwise "rows NOT in an established cutting order: <reason>"; the
setup picture draws travel arrows only on such directed paths. Each raster
pass's wall normal is its open side's unit vector (the uncut stock lies ahead of
the stepping cutter), so every pass is reversed when needed to cut the op's
`direction`, and its record carries the same order fields.

**Bounds clip.** `stock_removal_bounds` is a material footprint: an op may
remove stock only inside that box, but its cutter may run past the box through
air. Only the kernel knows where the cutter first meets the op's before-op stock
outside the box, so the coordinates pass prints a bounded op's tables whole
into the kernel request (`kernel_clip`) and prints, after the kernel run, the
kernel's clip of them (`checkpoint_clips`; see
[rules-geometry](rules-geometry.md#accessibility)). The kernel sweeps the
cutter along each printed path in cutting order and bisects each chord whose
sweep meets that stock to `CLIP_PRECISION_MM` (1e-4 mm); the finished part is
its own obstacle there, never stock, as in the row check. The clip point is
added and marked `clipped_at` ("first contact with stock outside
stock_removal_bounds") and printed at the nearest DRO grid point on the legal
side of its chord from which the cutter still sweeps clear; rows past it are
dropped (`dropped_rows`, `dropped_points`). A path that never meets such stock
prints whole. Tables that share an end stay one path where that end is kept. A
path that leaves and re-enters legality leaves each piece as a `fragment`
`[k, n]` and is debt: no credited cut links the pieces and none is
reconnected, so the setup's coordinates finding is `unknown`. A path with no
legal part, no kernel result, a kernel clip that is unknown or a clip that does
not match the printed table prints nothing and is unknown, never the unclipped
path. The traveler names the printed point a clipped table starts or stops at
("stops at P7: the stock past it is outside this op's area") and "piece k of
n: no cut links the pieces, so the stock between them is not cleared by this
op". The sheet's
tables, this check, the kernel's row check and the setup picture's waypoints
all use these clipped rows and their ids; the op's removal stays its box.

**Printed values.** The operator cuts what the DRO shows. One rule serves
every axis: the DRO grid is the setup machine's declared inventory
`resolution` (`resolution_mm` or `resolution_in`), else 0.001 plan units
(`DRO_DEFAULT_STEP`), printed at the decimals of one step (`dro_grid`). Every
arc row and join point carries `dro_xy`, the nearest grid point that, for each
of the feature's walls (its arcs between their ends, its lands and tapers, a top
arc's linked lands), is no nearer that wall than the exact point or the authored
cutter-centre offset, whichever is less (a corner of its grid cell, else up to
two steps out, else unknown); a table end and the join it meets print one
value. Every table carries `dro_tip_z`, and each profile and operation
`dro_to_z`: the authored depth rounded up, never deeper (−2.07825 prints −2.078
on the default grid). The op rows and contour table headers print the same
value, and so does every later Z printed for that face: a start Z, a Z zero and
its Axis Set and jog readings, a hole entry, a feature map end, a tip's height
over the jaw tops.
One provenance source (`tip_endpoints.operative_z`) picks the op that produced
that face. It looks first among the setup's own ops scheduled before the reading.
For a Z zero's `top`, those are the ops up to and including its `after_op`,
never a later recut. It then walks the selected stock ancestry: the setup's
`stock_in` chain, the same one the kernel builds, joint branches included, and
same-frame setups only. A setup outside that chain never counts, even if it cut
the same nominal face. The producer is the op that advanced a stock-state top
or entry, or the facing or pocketing op that last cut the face proven to be the
one read: for `top`, a facing op on `top_feature`; for a feature (a zero face, an
op's own feature for its start and end Z, a feature map row), an op on that
feature or one whose feature's X/Y `bounds` hold its whole footprint (its own
`bounds`, else a Z-axis round feature's `at` ± half its largest `dia`); overlap
is not cover. An equal Z alone is never proof, and with no footprint to prove it
there is no producer.
It counts only if it cut that face to that Z. Its
value is its `dro_to_z` on its own setup's grid, re-rounded to the safe side on
the consumer's grid, so a coarser producer's −2.270 stays −2.270. Any other
surface Z prints on the grid by `dro_z`. Hole endpoints
carry `dro_entry_z`, `dro_exit_face` and `dro_tip_z`, the tip worked from the
printed entry (through: exit face) and rounded up again, and the `dro_depth_mm`
or `dro_exit_mm` that leaves; a through tip short of the exit face prints a
STOP. Every row that prints a rounded depth carries `depth_floor_mm`: the lower
end of the feature's `depth` band, or for a tap its `thread_depth` (else `depth`)
band. Any other kind of row, and a bare `depth` (an upper limit only), has an
unknown floor. A `dro_depth_mm` below its floor prints a STOP, and so does a depth
the rounding changed when the floor is unknown. A final forming cut whose `to_z`
ends on its finished face (no `exit_mm`)
and whose rounded-up depth leaves more skin than its feature's narrowest
numeric tolerance band is an error (`dro_z_residual_errors`). Every join record
carries its `stage`, `allowance_mm` (the rough leave, 0 for finish) and
`offset_mm` (cutter radius plus allowance). The traveler prints these values;
the kernel clips, checks and credits them, so nothing between the sheet and the
stock model is rounded twice.

**Row ids and native check.** Each printed row has an id:
`S1:40 rough arc row 3` for an arc row and `S1:40 rough line +X[0]` for a join
point, with ` fragment k` after the table name for a clipped piece; the kernel
names the rows of the pieces it clips with the same formats (`ROW_FORMAT`,
`FRAGMENT_FORMAT`). The kernel stands the op's cutter at every printed row
from its printed tip up and applies rule A′
([rules-geometry](rules-geometry.md#accessibility)): a row whose cutter
meets the finished part, the op's rough leave, a fixture, stock outside a
bounded op's box, or stock a later setup grips, presses, locates, rests or
supports on is an accessibility error naming the row; an unresolved check is
`unknown`. A join's middle point is its corner miter, flagged `overshoot`: the
run-out past the land and taper walls into scrap. The traveler prints
"corner overshoot into scrap — OK" on that row only when the kernel proved the
op's rows clear; a row with an error keeps its error and prints no note.

Exact message:

`Feature targets use the declared model-to-setup basis; cutter tables use explicit nominal geometry and authored allowance.`

When unresolved it appends:

` Missing geometry or unverified tool/frame binding prevents a cleared toolpath.`

A bounded op's path left in pieces or none, or whose kernel clip is unknown,
appends:

` Stock-removal clip debt: op {op} {stage}: {reason}.` (`;`-joined per pass)

A finish depth the DRO leaves above its face past the feature's band appends:

` DRO depth rounding error: op {op} prints Z {dro} for to_z {to_z}: … .`

An arc stage, or a closed outline with a diagonal edge, on a machine whose
`contouring` is not proven (or a diagonal outline on a `jog` machine), a `jog`
arc whose rows cannot be stepped, or a `jog` finish stair with no numeric band
appends (unknown):

` Moves between rows are unproven: op {op} {stage} {reason}.` (`;`-joined)

A `jog` finish stair that leaves more than the feature's band appends (error;
the stage's rows are withheld and its `stair_reason` prints as the contour
STOP):

` Single-axis stair error: op {op} finish: single-axis steps leave {cusp} on {feature}, more than its {band} band.`

Blade grooves: a `form_*`/groove op whose tool is a grooving/parting blade gets
`plunges` numbers: the corner the DRO reads (a right-hand blade's chuck-side
corner, a left-hand blade's +Z corner) at each plunge, flush with the chuck-side
wall and stepping evenly, never more than a blade width, until the last plunge
is flush with the far wall; the diameter each stops at; and the groove they
leave (`max(span, blade_width)`). A groove outside the feature's `width` band
is an `error` (`op {n} plunges leave a groove {w} wide, outside the drawing
width {lo} to {hi}`); an unknown blade width or hand is `unknown`.

Dome roughing: the rough stage of an `axial_table` op (a `form_*` op with
`rough_allowance_mm`, or a `rough_*` op) is a `stair_tables` entry, not the
finished table. Each row faces in at a finish-table Z below the apex to the X
where the sphere grown by half the diametral allowance crosses it, so every
stair corner (the imaginary-tip reading) stays that far off the dome; rows at or
past the base radius are dropped. An apex toward the chuck has no stair
(`unknown`). The finish table prints its row-to-row order for an apex-to-base
convex dome: X out to the next row first, then Z toward the chuck.

Evidence groups: frame/binding, reference rows, operation targets, profiles,
arc/line/axial tables and advanced entry surfaces. Citations: PLAN §4.1,
manifest frames/nominal geometry, plan-owned setup frames, authored contour
steps/targets/allowances,
and selected inventory cutter nominal diameter; with any arc or diagonal
contour, the inventory machine's `contouring`.

## `zero_check`

A dedicated saw setup (all nonmanual ops are `saw_cut` / `cut_off`, at least one
saw) is `not_applicable`: its setting is an authored blade-centre `cut_plane`,
not a spindle XYZ zero. A mixed setup still checks its other machining zero
recipes; an unknown action cannot establish the saw-only exemption.

EL400 ABS Axis Set, not Preset. Approach side is independent of jog polarity.
For edge finding, `contact=edge + side*finder_radius`, side -1 from negative
axis and +1 from positive axis; indicated pickup uses radius 0. Paper Z uses
`contact=edge + paper`; touching `top` takes the received/advanced stock top.
Physical positive-axis jog gives `check=shown + sign*scale*jog` and
`mirror=shown - sign*scale*jog`, where `shown=scale*contact` is the displayed
Axis Set. The sign comes from authored DRO direction; lathe diameter-mode X
uses scale 2 (a `+x` touch on a 6.35 mm gauge at the axis sets 6.35, not its
3.175 radius) and radius mode scale 1; an omitted or unknown lathe
`radius_mode` leaves the X readings unknown. Other axes use scale 1.
Direction `right/away/up` (or lathe `away_from_spindle_axis/toward_exposed_end`)
is positive. Reversed direction or a non-ABS known mode is an error.
`edge_mm` explicitly locates a named pickup in the setup frame. Only Z
`face = "top"` substitutes the received stock top. Another named face (such as
an ear's inner face) uses its own authored edge; stock top is not its fallback.

For each authored Z `retouch_after`, the new set value is advanced top + paper.
A profile does not move the touched top. A listed retouch sets Z for the next
cutting tool only.

X `method = "trial_cut_measure"` cuts a diameter, measures it at the machine
with the declared `gauge` and Axis Sets that reading. Like paper thickness the
reading is a bench value, so the recipe is complete when `tool` and `gauge`
resolve without a verify flag, `check_jog_mm` is numeric and the lathe
`radius_mode` is known. The rows show bench expressions: diameter mode
`measured D`, check `D +2j`, mirror `D -2j`; radius mode `measured D/2`,
`D/2 ±j`. A target diameter is never used as the measurement.

Z `method = "measure_then_set"` touches a face whose position is measured at
the machine (M, read with `gauge` as the stated `measure`) and Axis Sets
`M + offset_mm + paper_mm`; check/mirror are `M ±j` on the same base. Like a
trial cut it is complete when `gauge` resolves unflagged, `measure` is stated
(`"unknown"` states nothing) and `offset_mm`, `paper_mm` and the jog are
numeric; the rows show `M -9`, `M +1`. The same holds for a tool touch's
`z_measure`.

Each `[[setups.zero.tool_touches]]` entry is complete when its `tool` and X
`gauge` resolve without a verify flag and `edge_mm` and `paper_mm` are numeric:
`x_axis_set` is the same measured-diameter expression and `z_axis_set` is
`edge_mm + paper_mm`. A mill touch sets Z only (`x_axis_set = "not_applicable"`):
the mill X/Y read the spindle axis whatever the tool. A touch with
`method = "measure_then_set"` sets `M + z_offset_mm + paper_mm`, M read with
`z_gauge` as `z_measure`. Missing tools, unverified finder/gauge facts, missing
recipes and unknown frame binding preserve unknown. A lathe does not require a
Y zero recipe.

One DRO per setup: the DRO reads the tool that last set it, by the zero, a tool
touch (made before the first of its `before_ops`, else after its `after_op`) or
a listed retouch. Ops before the Z zero's `after_op` run before any tool set Z.
Every cutting op whose tool did not make the latest Axis Set
is touched off first (`derived_touches`, printed "re-touch" at that op). The
source's recipe names its own tool's edge, so the re-touch is tool-neutral:
`edge_then_set` on a lathe (Z-cutting edge to the surface, withdraw along X),
`touch_then_set` on a mill:

- Z on the latest touched or faced surface still standing at a known plan Z:
  the zero face, a tool-touch face, a listed retouch's top or a face/pocket op's
  `to_z` (faced surfaces take the zero's paper). A surface stands until an op
  cuts that feature (the top: moves the top) to another or an unknown Z, or cuts
  it other than by facing/pocketing; a face or pocket op on an unnamed feature
  ends every surface. With no standing surface at a known Z, the latest standing
  one whose Z is unknown is repeated with an unknown Axis Set (unknown). A
  measured Z (`trial_cut_measure`, `measure_then_set`) is no plan number to
  repeat.
- On a lathe, X on the latest diameter turned in the setup (`turn`,
  `rough_turn`, `finish_turn`) that still stands, measured with the latest X
  gauge, Axis Set the measured diameter. A turned diameter stands until an op
  cuts that feature other than by turning it (a dome formed on it) or cuts an
  unnamed feature. A touch's own `x_method` surface is prose the rule cannot
  follow past a cut, so it is never repeated. Tailstock tools (axial actions) do
  not read the carriage DRO.
- A cutting op whose tool is unknown leaves the setter unknown (unknown); an
  incoming tool that does not resolve, or carries a verify flag, keeps its
  derived touch unknown, as it keeps an authored touch.

An axis with nothing to derive from is a `missing_touches` row
(`before_op`, `tool`, `axes`, `dro_set_by`) and an error: a tool cutting on
another tool's Axis Set scraps the part. An authored tool touch for that tool
before the op replaces the derivation.

Templates:

- `DRO direction or mode disagrees with the setup convention; stop and correct it before the check jog.`
- `Touch, Axis Set the compensated value, then jog without retouching and compare expected versus mirrored readings.`
- The latter appends, when touches were derived:
  ` Each tool change is touched off on the last touched or faced surface still standing.`
- when a touch is missing:
  ` A tool cuts on a DRO another tool set and no standing plan surface is known to touch it off on: plan a tool touch before op {op}, ….`
- and when unknown:
  ` Measured setup/tool or trial-cut verification remains unknown.`

Evidence: per-axis contact/set/check/mirror/sign, source edge, finder radius,
paper, jog and DRO direction, retouch list, per-tool touches, derived and
missing tool-change touches and transfer.
Citations: PLAN §4.1 and Electronica EL400 Operation Manual §6.2 p20, §7.4 p31,
§8.1 p37, §9.2.1 p62; plan zero/stock-state and inventory finder nominal size.
The recipe says **jog without retouching**. Physical emulator direction and
actual check readings must be exercised by the operator; local computation does
not prove the paper/emulator acceptance control.
