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
using those fields to override the arc. A full circle needs continuous
interpolation; its checkpoints are not straight-chord cuts. Finite arc records
include sagitta `R*(1-cos(min(step,span)/2))` and exact offset joins. Every
feature linked through `top_edge_feature` contributes its upper land's
line-circle intersection: an outline and separately exported tip lands can
share that top arc. Mirrored −X/+X lands must agree after reflection; an
unknown or inconsistent linked join leaves the top table unknown. The lower
outline also supplies its line-line miter and bottom line-circle intersection,
with mirrored sides explicit. Degenerate joins do not become invented paths.

`linear_table` transforms explicit box bounds (or `sweep_bounds` in
`sweep_frame`). Exterior rectangular paths expand by offset; pockets require an
explicit open side and positive `step_mm`, with outside entry and finite raster
passes. Tables are numeric nominal geometry, not cutter accessibility, fixtures,
wall thickness or collision proof. Unknown/unverified cutter or frame binding
keeps status unknown. M2 lathe feasibility remains unimplemented even where
nominal stations/dome tables are displayed.

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
setup picture draws travel arrows only on such directed paths. Raster pocket
passes are independent cuts and claim no travel direction.

**Bounds clip.** An op with `stock_removal_bounds` may remove stock only inside
that box, so its cutter centre must stay r inside each XY bound. The inset box
(`lo + r`, `hi − r`, each rounded inward to the DRO grid) clips the printed
arc rows and join points in cutting order: where the path crosses an inset
bound, an exact point on the arc or join is added and marked `clipped_at` with
the bound it meets (`stock_removal_bounds y 31.7 − r`); points past it are
dropped (`dropped_rows`, `dropped_points`). An end point inside the inset box is
kept, one outside it is clipped, with no tolerance beyond 1e-9 plan units.
Tables that share an end stay one path where that end is kept. A path the box
splits leaves each table piece as a `fragment` `[k, n]` and is debt: no credited
cut links the pieces, so the setup's coordinates finding is `unknown`. A path
wholly outside the inset box prints nothing and is debt too ("its cutter-centre
path lies wholly outside its bounds inset by r"). The traveler notes "path
clipped where the cutter meets …" and "separate piece k of n".

**Printed values.** The operator cuts what the DRO shows: 2 decimals in mm,
4 in inches (`DRO_DECIMALS`). Every arc row and join point carries `dro_xy`, the
nearest grid point that, for each of the feature's walls (its arcs between their
ends, its lands and tapers, a top arc's linked lands), is no nearer that wall
than the exact point or the authored cutter-centre offset, whichever is less,
and stays inside the DRO-rounded inset box (a corner of its grid cell, else up
to two steps out, else unknown); a table end and the join it meets print one
value. Every table carries `dro_tip_z`, and each profile `dro_to_z`: the
authored depth rounded up, never deeper (−2.07825 prints −2.07), leaving under
one display step of skin. The traveler prints these values; the kernel checks
them and credits their sweep, so nothing between the sheet and the stock model
is rounded twice.

**Row ids and native check.** Each printed row has an id:
`S1:40 rough arc row 3` for an arc row and `S1:40 rough line +X[0]` for a join
point, with ` fragment k` after the table name for a clipped piece. The kernel
stands the op's cutter at every printed row from its printed tip up and applies
rule A′ ([rules-geometry](rules-geometry.md#accessibility)): a row whose cutter
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

A clipped path left in pieces or none (and unclippable bounds) appends:

` Stock-removal clip debt: op {op} {stage}: {reason}.` (`;`-joined per pass)

Evidence groups: frame/binding, reference rows, operation targets, profiles,
arc/line/axial tables and advanced entry surfaces. Citations: PLAN §4.1,
manifest frames/nominal geometry, plan-owned setup frames, authored contour
steps/targets/allowances,
and selected inventory cutter nominal diameter.

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
A profile does not move the touched top.

X `method = "trial_cut_measure"` cuts a diameter, measures it at the machine
with the declared `gauge` and Axis Sets that reading. Like paper thickness the
reading is a bench value, so the recipe is complete when `tool` and `gauge`
resolve without a verify flag, `check_jog_mm` is numeric and the lathe
`radius_mode` is known. The rows show bench expressions: diameter mode
`measured D`, check `D +2j`, mirror `D -2j`; radius mode `measured D/2`,
`D/2 ±j`. A target diameter is never used as the measurement.

Each `[[setups.zero.tool_touches]]` entry is complete when its `tool` and X
`gauge` resolve without a verify flag and `edge_mm` and `paper_mm` are numeric:
`x_axis_set` is the same measured-diameter expression and `z_axis_set` is
`edge_mm + paper_mm`. Missing tools, unverified finder/gauge facts, missing
recipes and unknown frame binding preserve unknown. A lathe does not require a
Y zero recipe.

Templates:

- `DRO direction or mode disagrees with the setup convention; stop and correct it before the check jog.`
- `Touch, Axis Set the compensated value, then jog without retouching and compare expected versus mirrored readings.`
- The latter appends, when unknown:
  ` Measured setup/tool or trial-cut verification remains unknown.`

Evidence: per-axis contact/set/check/mirror/sign, source edge, finder radius,
paper, jog and DRO direction, retouch list, per-tool touches and transfer.
Citations: PLAN §4.1 and Electronica EL400 Operation Manual §6.2 p20, §7.4 p31,
§8.1 p37, §9.2.1 p62; plan zero/stock-state and inventory finder nominal size.
The recipe says **jog without retouching**. Physical emulator direction and
actual check readings must be exercised by the operator; local computation does
not prove the paper/emulator acceptance control.
