# Coordinates and DRO zero

Both rules produce one subject per setup. Nominal numeric recipes and tables can
remain useful while their status is unknown; they are not cleared toolpaths or
measured first-article evidence. Report numbers retain precision. Their sines,
cosines and arctangents come from `prechips.trig` (fdlibm's algorithms in IEEE
double arithmetic alone) and their squares are products, not the platform libm's
`sin`, `cos`, `atan2` or `pow`, whose last bit differs between the Windows CRT
and glibc: the same inputs give the same tables to the last bit on every
platform, and nothing is rounded for print. Bench drawing
station/feature reference points use the dimension's declared drawing precision;
a known number without one prints its own value (six significant digits) rather
than `?`, which stays reserved for unknown values. Operation-derived rows,
computed tip targets, Z stations and contour cutter-centre tables always print
their own value, never rounded to a drawing dimension's display precision.
Contour tables use manifest geometry even when the M4 kernel rules run on the
same bundle; only feature location may read an already-present kernel result
(below), and these rules never start the kernel.

## `coordinates`

**DRO grid consumption.** The machine's `resolution` becomes coordinate-rule
measurement debt only when an operation authors or emits at least one coordinate
rounded to, or printed on, that machine's DRO grid. An authored `to_z`, `z_from`
or `z_to`, a requested feature location, a nonempty lathe drawing-station list,
or a contour requesting cutter-coordinate targets consumes the grid even when
unknown geometry or binding prevents computing its rows. An explicit
`contour = "unknown"` also authors a target request; an omitted or empty contour
does not. Empty outputs do not erase an authored target's debt. A missing or
untrusted (including `assumed`)
consumed grid keeps the finding unknown with `dro_grid_debt` and the named
`machines.<id>.resolution` measurement instruction; its declared step still
places provisional targets, otherwise `DRO_DEFAULT_STEP` does. A trusted
consumed grid retains the same rounding and geometric judgments.

Machine selection, stock-state metadata and an unlocated feature name alone
consume no DRO coordinate. A bare `saw_cut` with no feature location, contour,
Z target or coordinate table therefore reports
`dro_grid = { step = "not used", decimals = "not used" }`, visibly as **no coordinate
targets** on the traveler, and has no coordinate-rule resolution debt or
fabricated numeric saw grid. This does not claim that the machine's grid is
unused by stock dimensions, pictures, touch-off recipes or tip-endpoint displays;
those consumers retain their own rounding and debt. Its coordinate finding
remains pass when no independent geometry, frame or operation debt/error exists;
**no coordinate targets** clears none of those other checks.

A feature-local point is transformed to model coordinates as
`model = feature_frame.origin + sum(local[j]*feature_frame.basis[j])`.
A setup coordinate is `(model - setup.origin) dot setup.basis[axis]`.
Feature frames always come from the exported manifest. The setup frame is the
exported manifest frame of that name, otherwise the plan-owned
[`frames`](plan.md#frames) entry; a plan frame may not reuse an exported name.
A plan-owned setup frame adds `plan.frames.<name>: author-declared setup frame`
and its own citations to the finding, and its stated `binding` decides whether
the transform is nominal or unbound exactly as for an exported frame.
Unknown components propagate only through nonzero coefficients. Loading checks
the basis of a fully known frame only, so in a frame with an unknown axis each
numeric axis counts only if it is finite and, within `1e-9`, unit and orthogonal
to the frame's other numeric axes; otherwise it is unknown, and so is every
coordinate along it and every direction compared with it. Tolerance-band
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

**Mill DRO targets, aims and printed bands.** Off a lathe, a located row with a
known setup point — an `at` or parent row, or each end of a kernel span (below) —
also carries `dro`: that point at the nearest step of the setup machine's DRO grid
(`dro_grid`), at most half a step away (exactly half a step rounds away from zero,
as the fixture tables and holding details round: `render_diagram.dro_steps`),
which the sheet's feature map prints and a
hole op dials (`dro_xy`). When the feature declares a height-like band
(`height_above_pivot`, `height` or `separation`, the first one present) from a
`height_from` reference, the row's `band_check` measures where the feature stands
from where that reference stands. A feature this setup machines (a centre op —
a hole op or `center` — names it) stands at its DRO target; one it only inspects
or otherwise works without dialling it, or machines through a child or in
another setup, stands at its planned point (its aimed model point, unrounded),
whatever its row prints. The distance runs along a reference plane's normal,
otherwise from the located reference along the common normal of both measuring
axes, square to the one axis, else point to point when neither has one. A
feature without its own `axis` that names a parent hole (`hole`, else `parent`)
or is drawn `coaxial_to` another takes that feature's axis, in that feature's
frame, whether or not it has its own `at`. An axis that is `"unknown"` (or whose
frame is), or that comes from an undeclared feature, leaves the distance
unmeasured; a kernel span's two ends must stand at one distance, else the band
names neither. The band is the one the sheet prints, rounded inward at its
drawing precision. A target outside it is
an error (`Located target band error: …`, value in mm). A distance that cannot be
measured, a band that is not two numbers, feature units other than mm or in, or a
DRO grid that is not the machine's own trusted `resolution` — the fact unknown
(so `DRO_DEFAULT_STEP` stands in) or declared but not qualified by its own
`status = "measured"` record (its declared step still rounds the printed
targets, never a finer fallback) — keeps the setup
unknown with that resolution in its measurement debt; the grid still places
the printed targets. A plan
[`aims`](plan.md#aims) entry moves the feature's own target along that same
direction so its band reads `value_mm`, converted to the manifest units, on every
setup that locates it. The row keeps the unaimed point as `nominal_setup`, records
the `aim` (owner `feature`, requirement, value in mm and in manifest units, reason,
source, printed band, nominal value and shift in mm), and the finding cites
`plan.aims.<name>`; the feature map adds a sentence that gives the aimed target,
the drawing nominal and the reason. A child located by its parent's `at` dials its
parent's target, aimed or not, and carries the parent's `aim`; an aim of the
child's own would take it off that axis: it is refused (unknown, reason in
`refused_aim.why`, cited too) and moves nothing. Such a target aim never
changes geometry, a claim, a kernel input or another feature's target. A faced
aim (one naming a `face`) moves no target here; the kernel cuts the part it
makes ([plan aims](plan.md#aims)). A
`value_mm` outside its printed band is refused before any rounding: bad input on
load, an error in the rule, and the target stays nominal. An aim whose feature
no mill setup's centre op names (only inspected, faced or profiled, cut through a
child or drilled on a lathe, so no cut stands at the aimed target), whose feature
holds no such band, whose band or units are unknown, or whose distance cannot be
measured stays unknown with the reason in `aim.why` and the target stays nominal.

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
zero. A negative leave (`rough_allowance_mm`, or a rough op's `stock_to_leave_mm`)
on any operation, contour or not, is an error (`allowance_errors`): its rough
would cut into the finished part, so no stage of that op is offset, printed or
proven (the traveler prints a STOP), and the kernel, travel, joint and speeds
rules read it as unknown or an error, never as a shifted band or cut. Operations
without an authored rough allowance keep their finish-only
table. Each profile, arc and exact line-join record names its `stage` (`rough`
or `finish`), so the report and traveler distinguish the two paths even when
they share one operation number. Axial dome samples remain nominal profiles,
not an allowance/tool-nose-compensated rough path.
Arc contours use explicit centres, nominal radii and known finite geometry:
a boss is a full circle, a declared upper semicircle is 0–180°, and finite
rocker arcs derive endpoint angles.
Internal/top arcs subtract offset; outside/bottom arcs add it. Rows include
exact endpoints. `start_deg`/`end_deg` are accepted
schema fields but the current rule derives bounds from geometry rather than
using those fields to override the arc. Finite arc records include exact offset
joins. Every feature linked through `top_edge_feature` contributes its upper
land's line-circle intersection: an outline and separately exported tip lands can
share that top arc. Mirrored −X/+X lands must agree after reflection; an
unknown or inconsistent linked join leaves the top table unknown. The lower
outline also supplies its line-line miter and bottom line-circle intersection,
with mirrored sides explicit. Degenerate joins do not become invented paths.

**Manual arcs.** The mill is manual: one handwheel moves at a time, so no
printed move turns two axes together (no MDI, no G-code, no continuous
circle). An arc is cut by one of five `contour.method`s
([plan](plan.md#manual-arcs)); authoring the former `arc_table` is an error
naming them. Each table is recorded under `arc_table` (its joins under
`line_table`) with its `method`.

- `stairs` (rough only; spaced by `cusp_mm`): rows include each angle at which
  the arc is tangent to a setup axis, so every step between rows is monotone,
  and are spaced as far apart as keeps the material the stepped cutter leaves
  on the wall within `cusp_mm` (beside a concave arc's tangent dip, without
  the leg into the dip, which the merged move stops short of), measured on the
  printed DRO values: when rounding to the DRO grid leaves more, the rows are
  respaced closer, by at least enough to move a row (a stair still over
  `cusp_mm` is unknown). A corner row (no angle) between two rows
  that differ on both axes turns one axis, then the other: `(b.x, a.y)` or
  `(a.x, b.y)`, whichever keeps both legs no nearer any wall than the
  cutter-centre offset (or than the rows it joins, if nearer) and lies farther
  from the walls. Consecutive legs on one axis are one move, so each move turns
  the other handwheel and no handwheel reverses inside a move: a tangent row in
  the middle of a move (a concave arc's lowest point, which the move then stops
  short of) is not printed. Each row names the axis moved to reach it (`jog`).
  Straight joins are split so their stairs keep the same cusp. The record
  carries `stair_cusp_mm` (the most material the stepped cutter's swept legs
  leave along any wall normal, measured from the wall out to the first leg the
  normal meets; a normal that meets none is unknown), `line_clear_mm` (the
  least gap from the stepped cutter's edge to the finished line) and
  `stock_left_mm` (allowance + cusp). No corner that keeps outside the line,
  or a `line_clear_mm` below zero, is an error and withholds the stage's rows.
  The traveler prints the cusp rounded up onto the DRO grid, and says the
  stairs (or a chain's holes) stay outside the scribed line only when a
  `scribe` op on the feature runs before them, else outside the finished outline.
- `chain_drill` (rough only; holes no more than `pitch_mm` apart along the
  rough path, drilled with the op's drill): every hole's full diameter must stay
  outside the line (`hole_clear_mm` ≥ 0) and neighbours must leave a web
  (centres more than a drill diameter apart); either failure is an error.
  Host DRO selection and kernel regeneration/actual-hole validation use one
  shared pure finite-boundary clearance predicate. For an actual closed
  finished loop (including a joined bottom outline or full circle), its sign
  comes from point-in-region and its magnitude from the nearest finite
  boundary: negative in kept material. Unordered exact lines and arcs are
  connected by their real endpoints, with authored scrap normals determining
  the kept side; arc sweeps are not tessellated or extended.
  True open arcs and the current top-plus-land wall packets lack a complete
  finished loop in the packet: no closure edge is invented. Linked taper and
  bottom-arc facts can exist in the host model without being carried in that
  partial top packet; fuller actual closed-boundary transport is tracked in
  [#212](https://github.com/pedropaulovc/prechips/issues/212).
  Their fallback uses oriented finite projections
  and real free-end cap distances; shared concave vertices classify the actual
  nearest-vertex sector, rather than treating a kept-side corner as a positive
  cap. Distance ties are conservative, not a global AND of distant supporting
  half-planes. Missing, ambiguous or unsupported region geometry is unknown,
  never an unsigned-distance pass. With no admissible grid point, the stage is
  unknown and its cut tables are withheld. Every actual cylinder still needs
  web, bounds and native collision checks; the open fallback is not a proof
  of the whole finished part.
  The webs are broken out along the hole centres (`break_out`): every
  centre-to-centre segment must stay outside kept material. For closed loops,
  the same predicate checks entry against the whole finite boundary, not just
  the join's own line; an entry is an error. The
  file meets `stock_left_mm` = the maximum of allowance + drill radius, the
  radial depth left by the actual printed arc centre-to-centre break-outs, and
  the greatest distance from the retained printed join centre-to-centre
  break-out polyline to the nearest finite finished wall (nearest-wall
  distance, not one wall's normal, so a concave neighbour wall does not
  over-report corner runout). Straight joins use the
  same drill-radius + allowance offset as the arc. Each finite straight leg
  keeps its exact join endpoints/miter, and its nominal holes divide the leg
  into equal intervals no longer than `pitch_mm`; snapping each hole onto the
  DRO grid can move the printed spacing off that bound. Holes are repositioning
  checkpoints, not handwheel cutting moves, and the kernel credits an unbounded
  chain with removing only its actual drilled cylinders: the webs between
  them, and the stock between them and the claimed wall, stay in stock until
  a later known removal (no drill-radius sweep between centres, no cutter
  corridor, no +Z claim sweep), so retained webs beside a claimed wall are
  named stock debt pointing at `stock_removal_bounds`; declaring that box on
  the chain op is the author's certification of the actual break-out/chisel
  footprint, not a demonstrated toolpath
  ([rules-geometry](rules-geometry.md#in-process-stock); explicit break-out
  phase tracked in [#213](https://github.com/pedropaulovc/prechips/issues/213)).
  Join tables print hole numbers,
  checkpoint P, X/Y and Z, drill size, pitch, break-out instructions and the
  reported stock/cap or `recut_by`; a table left with a single hole prints no
  pitch or break-out sentence (there is no neighbour to break through to).
  Each P label names the printed DRO X/Y
  point it stands on (matched within 1e-6 mm), never a hole index that a clip
  or respacing could shift. Arc and join records share the worst residual of
  their rough stage. Method, stage, full-hole-outside-the-line and requested
  no-web errors (an authored `pitch_mm` no greater than the selected drill's
  diameter can leave no web at any spacing) are preconditions found on the
  authored tables before any clip, and stay errors even for holes a clip would
  exclude; a clip's single-hole or dropped-end result never hides them.
  The authored arc radial/full-hole invariant remains a pre-clip check in
  addition to the shared finite-boundary predicate. It is intentionally not
  imposed on regenerated endpoints: a physically safe finite-cap hole beyond
  the actual sweep may lie inside the authored supporting circle.
  A bounded chain (`stock_removal_bounds`)
  is clipped by the kernel at drill granularity: it intersects the
  drill-centre offset arc and join lines with the bounds eroded by the full
  drill radius (a closed arc's fragments across its seam are one span), then
  regenerates each retained arc or straight leg on its own with equal nominal
  intervals along that curve, choosing the hole count so the nominal spacing
  is no longer than `pitch_mm` and still leaves a web (centres more than a
  drill diameter apart); that web is judged on the actual snapped DRO centres,
  not the nominal span alone: for a retained span longer than the length
  tolerance, the pitch-required count is always tried at its snapped
  positions, even when it exceeds the nominal-length web bound, and any higher
  nominally feasible count is also tried before the span is shortened (a span
  within that tolerance, whether an isolated point or a tiny retained arc or
  leg between two shared junctions, keeps exactly one hole, never a duplicate
  row at the same centre); exact
  junctions stay shared. A span whose snapped
  placement leaves no positive web at any such count omits its clipped end
  hole (reported as a dropped end, never as
  a fabricated no-web error). Every actual hole then snaps onto the DRO grid
  inside the bound and passes the same shared predicate: its centre must be
  in scrap with finite-boundary clearance for the whole drill and allowance.
  Closed loops use region membership even beyond an individual wall's
  projection; genuine open packets use the finite-projection/free-end and
  concave-shared-vertex fallback above. Bounds never waive that test.
  The nominal-distance/offset guards remain additional placement constraints,
  not independent unsigned side acceptance. All holes search the symmetric
  square within three
  grid steps on each axis and choose the nearest safe point by Euclidean
  distance, with a deterministic coordinate tie-break. A diagonal is not
  rejected merely for lying outside a one-step circle. Ends and junctions may
  back off inward along the true curve; a clipped end is therefore not promised
  within one step of the true bound crossing. A hole with no such grid
  candidate after its full search and back-off leaves the whole clip unknown,
  never a hole in finished material. Every actual
  hole cylinder is judged; the printed spacing is the DRO spacing, which can
  differ from the nominal interval. A raw swept-chord
  intersection never becomes an extra hole. The web/break-out checks and the
  single T6 `numbers.max_filing_stock_mm` cap enforcement run on the actual
  regenerated residual. Unsigned nearest-wall distances intentionally remain
  the stock/residual measurements, not scrap-side proof. Its table names
  only genuine dropped ends and piece breaks where stock beyond is not cleared
  or part of the chiselled chain; an intact arc/join junction continues into
  the adjacent table. Omitted joins add no join debt while an arc
  or other table remains; a stage the clip excludes entirely, or retained
  pieces that no longer connect, keeps the existing clip debt.
  When a chain error withholds cut tables, profile facts still report
  `stock_left_mm` and `stock_cap_mm` where the residual was computed (a
  precondition error may prevent it), for diagnosis, not permission to cut.
- `chords` (finish; `count` straight chords): the chord ends sit on the edge
  radius that centres each chord's sagitta `c²/8R` in the feature's radial band
  (`dia` halved for a full circle, `bottom_radius` or `radius` otherwise); a
  sagitta wider than the band is an error, and so is a full circle cut in fewer
  than three chords or two neighbouring chords that run parallel. Each chord is
  fed along one table axis: as it lies when it is square to X or Y, else with the
  work indexed square to X on the setup's rotary table (`index_deg`, rounded to
  the dial's resolution); a slanted chord with no rotary table is an error. Each `cut`
  locks one axis `at` a DRO-grid value on the scrap side and feeds the other
  `from`/`to` grid values; the rule rebuilds every chord face from those printed
  cuts and holds its nearest and farthest points (`face_radius_mm`) inside the
  band, else an error. A rotary table flagged to verify is unknown.
- `rotary_table` (finish; rows every `step_deg`): the setup holds the work on
  an inventory `rotary_table` fixture (`hold.fixture`), with the arc centre on
  the table axis at setup X0 Y0, located by a pin through (`centre_by = "pin"`)
  or by indicating (`"indicate"`) `contour.centre_feature`, a hole on that axis
  an earlier drill, ream or bore makes. A pin is the hole's smallest diameter: it
  must enter the table's centre bore (`bore_dia`, else unknown), else an error.
  The spindle locks at X = the cutter-centre radius on the DRO grid in plan
  units, off the line, Y0 (`offset_axis`, `offset_x`; `offset_mm` the same in
  mm). That printed offset's cut radius (`cut_radius_mm`), widened for a pin by
  the centre's play (half each bore's clearance over the pin,
  `centre_play_mm`), must lie inside the feature's radial band (a rough stage's
  band moved off the line by its allowance), else an error, however the centre
  is found; an unknown band is unknown. The table turns
  the work against the cutter from the `start_deg` to the `stop_deg` dial
  reading, both rounded inward along the turn to the vernier (else graduation)
  resolution: an arc too short to keep a reading inside it is an error. Consecutive
  rows must lie under half a turn apart (always so with `step_deg` under 180°;
  a wider step on an arc shorter than half a turn leaves only its two ends):
  wider rows read as the short way round, so neither their cutting order nor the
  table's turn follows the cut's sense, an error. The
  setup-entry stock (kernel `stock_bbox_mm`) must swing inside the table's
  `max_work`. Off-axis centres, no table, no earlier centre hole or a swing over
  `max_work` are errors; unknown dial, centre or swing facts, a table
  flagged to verify, or a `max_work`/`bore_dia` whose own record is not
  trusted are unknown, the untrusted fact named in `numbers.measurements`.
- `guided_sweep` (finish; rows every `step_deg` over the whole sweep,
  `rules/guided_sweep.py`): the work rides the setup's `hold.fixture`, named by
  `contour.sweep.fixture`, which holds it to rotation about the arc centre on a
  `pivot` (`kind = "swing_arm"`) or a `rail` (`kind = "arc_sled"`, two rollers at
  `rollers_deg`, the rail's ends at `rail_deg`). The stationary cutter is touched
  to `contour.sweep.master` (a `setting_bar` on the pivot pin or a `master_arc` on
  the fixture) feeding along `touch_axis` from the scrap side (`touch_feed`), and
  X and Y are locked (`locked_axes`; `moves = "fixture"`): the cutter's own size
  never enters the cut radius. The worst-case cut (`cut_radius_mm`) is the master's
  measured `radius_limits` (`master_radius_mm`), moved off the line by a rough
  stage's back-off (`back_off_mm`: the allowance rounded off the line onto the DRO
  grid, `back_off_dro` the signed move on the touch axis from the DRO reading the
  operator writes down at the touch; the setup's DRO zero is never reset),
  widened by `centre_error_mm`: the swing arm's measured `pivot_play` (doubled
  for a master arc on the arm, which moves with the beam at the touch-off too), or
  `2 × roller_gain × (rail_form_error + roller_runout / 2)` with
  `roller_gain = (|sin a| + |sin b|) / |sin(a − b)|` for rollers at `a`, `b`
  degrees from the cutter's radial line: each contact errs at the touch-off and
  again at the cut, and the sled's centre translates by both through the rollers'
  geometry. Both are finite bounds, not the linear terms alone: each centre shift
  `d` adds `d² / (2 (ρ − d))` where a radius `ρ` turns it (the cutter's shortest
  reach, `worst_reach_mm`: the master's radius limits at the touch, less a rough's
  back-off toward the centre, never the nominal path; and for a
  rail the roller centres' least orbit `roller_orbit_mm`: the rail radius for rollers
  outside it, `rail_side = "outer"`, the rail radius less half the measured
  `roller_dia` for rollers inside it; an undeclared side, or an inside roller
  unmeasured or as wide as the rail's diameter, is unknown), solved as a
  fixed point (`rules/guided_sweep.py` `rail_cut_shift`); one that does not converge
  inside half of either radius leaves the cut unknown. Every geometric proof of the
  sweep then carries one explicit safety margin, `margin_mm`, the machine's DRO
  resolution (one display step): the cut is widened by it, and so is the start's
  clearance, which also places both stops past the arc's ends. A bound term provably
  smaller than the margin is absorbed rather than modelled: a setting bar touched up
  to one step beside its line moves the cut by at most `hypot(reach, step) − reach`,
  and a touch axis leaning within its one-step tolerance shortens a back-off `b` by
  `b (1 − cos)`, both under one step for any cutter-centre reach of two steps or more
  ([#272](https://github.com/pedropaulovc/prechips/issues/272)). A DRO resolution the
  machine does not state as a measured fact, or a reach under two steps, leaves the
  margin unproven: debt. It must lie inside the radial band (`band_mm`; a rough stage's moved
  off the line by its allowance), else an error. `sweep_deg`, centred on the arc,
  must reach both arc ends (`span_deg`, the cutter-centre span) to within one DRO
  step of cutter travel and stay under a full turn, else an error; a full circle is
  an error too (a sweep of a full turn starts and ends at one fixture pose, so no
  pair of stop blocks bounds it; cut it on a `rotary_table`). `step_deg` must be
  under 180°, else an error: the chord between rows half a turn or more apart reads
  as the short way round, so neither their cutting order nor the fixture's turn can
  be told. The rows run `overrun_mm` past each end
  (`path_mm` of cutter travel along the work), the arc's own ends kept as rows, and
  the kernel judges every one ([rules-geometry](rules-geometry.md)). The rows stay
  on the nominal cutter-centre arc: the kernel judges that path against the nominal
  part, as for every manual-arc method, and the band check above judges where the
  master actually sets the cut (rows moved to the master's radius would make any
  in-band master past nominal a part hit). The fixture
  turns the work `rotation` (viewed from above) against the cutter's travel along
  the rows in cutting order. `ends_setup_xy` are the arc's ends on the work (setup
  XY, the sweep's start end first, reference geometry). The traveler sets the stops
  on the arc-end marks an earlier `scribe` op with `layout = "ends"` lays out in the
  same setup (`marks`: that op and which mark, A or B, each stop sits on, the start
  first); no such op, marks it cannot place, or any op between that layout and the sweep
  that may cut (an earlier sweep cuts through the arc's ends: rough and finish in one op,
  whose stops are set once) is unknown. The setup
  frame is the work at the sweep's middle pose: `touch_axis` must run from the arc
  centre to the arc's middle (`arc_mid_setup_xy`), the cutter's radial line, to
  within one DRO step of cutter travel (`touch_axis_off_deg`), else an error, since
  a touch or back-off along any other axis is not radial. On a rail,
  `roller_contacts_mm` are where each roller bears on the rail, as setup X/Y offsets
  from the spindle axis at the touch. On a rail, both rollers must bear on the rail through
  the travel the printed stops set (`stop_travel_deg`: the arc's span plus, at each end,
  the printed overrun and the stop's placement slop `stop_slop_mm` on the shortest
  touch reach, so a sweep short of the arc within its tolerance still travels the whole
  span; each roller within `rail_deg` narrowed at both ends by half that travel and by
  its placement slack `roller_slack_deg`, its printed contact's 0.1 mm X/Y rounding plus
  the sled's own shift through the rollers, over the rail radius;
  the rail is the shorter arc between its ends, across the ±180° line too, and ends
  half a turn apart leave its side unknown) and must not lie on one line through the
  centre, else an error; the traveler prints the sweep only once `rail_coverage` is
  `proven`. A guide fixture
  that is not the hold's or not the guide's kind, a master that is not a setting
  bar or master arc, a setting bar on a rail, or a setup on a machine other than a
  `mill` (the sweep locks a mill table's X and Y; an unknown kind is unknown) is an
  error, and so is a setup that
  runs any other spindle op beside a guided sweep: the fixture turns the work off
  the setup frame and nothing holds it at that pose for the other op, before the
  sweep or after it (manual ops aside). The cutter is put on the arc's radial line
  before the touch so a rough's one-axis back-off is radial (`transverse`):
  `bar_centred` (a setting bar centred between its two sides) or `rollers_set` (a
  rail's rollers set from the locked spindle); a rough's cut is widened by how far a
  back-off then misses its radial move (`transverse_residual_mm`, taken at the worse
  of the cutter-centre reaches the master's radius limits give at the touch, not the
  nominal path) with the cutter axis
  beside the line by up to `transverse_offset_mm`: one DRO step plus the pivot play
  (bar), or, on a rail, the sled centre's sideways shift `(|cos a| + |cos b|) / |sin(a
  − b)|` times each contact's error, finite as the cut's own bound: its roller set to
  a contact printed to 0.1 mm on X and on Y (the diagonal of two half-steps) plus the
  rail's form error and half its roller's runout. Rollers close in angle amplify it; a
  bound that does not converge is unknown. A master arc on a swing arm gives no radial line: it is
  unknown and prints only a STOP, a finish too
  ([#288](https://github.com/pedropaulovc/prechips/issues/288) would lift it with a
  feeler touch). An unknown guide,
  fixture, master, axis, sweep, rollers or rail ends, a fixture or master flagged
  to verify as a whole (as the shop list states it, its source provenance and a
  selected set member's own flags
  included; a flag on a fact the sweep does not read, a picture-only dimension say,
  does not count), and a `pivot_play`, `rail_form_error`, `roller_runout` or
  `radius_limits` without its own complete `measured` record (`rail_radius` is
  read as declared) are unknown, each untrusted fact named in
  `numbers.measurements` with a `measure:` instruction: an undeclared form error
  is never a perfect rail. The cutter goes down at the sweep's first row (its start
  stop) at every level: `start` is `air` only when the cutter there stands wholly
  outside the stock box the setup receives (`level_entry.in_air`, as any entry is
  proven), at the pose the first stop block sets (`start_xy`: the printed overrun
  `stop_overrun_mm`, 0.1 mm rounded down, measured on the touch path where every
  stage's stops are set, before any rough back-off), the cutter widened by the most the master-set
  cut (`cut_radius_mm`) stands off the nominal wall the rows assume, and by the arc
  that radius range turns the measured overrun through (it is measured along the real
  path), by the mark's placement rounding (its X and Y each up to half a step off,
  the diagonal of the two) and by the stop's shift when the stroke's
  printed angle is off by half its 0.1° step across a cutter radius plus that spread,
  and by the DRO-step margin (`start_reach_mm`), else `unproven` and unknown, since nothing
  checks a plunge for a sweep. The traveler prints the recipe only with a known band
  (`band_mm`), a proven cut and a start in air; any unproven cut is debt, whatever
  left it so (a pivot play or rail error too large to bound included). The stage
  records every error and debt it left in `open_debts`, and the traveler prints the
  recipe only when that is known empty, so a debt no printed value shows still stops
  it.

Every manual-arc table is cut in the plan's feature units (`mm` or `in`, else
unknown) and records its millimetre facts (`*_mm`) in millimetres: the cutter,
drill, cusp, band and stock values are converted, never mixed.

A rough stage's leftover (`stock_left_mm`) goes to the file
(`rules/manual_arc.py`, `file_to_line`) and must not exceed the shop policy
`numbers.max_filing_stock_mm` (`stock_cap_mm`), else an error. The cap is
unknown, never zero or a pass, when absent, negative, uncited or not marked
`numbers_verify.max_filing_stock_mm = false`. A rough whose claimed faces a
later `stairs`/`chain_drill`/`chords`/`rotary_table`/`guided_sweep` op cuts again before any
file reaches them leaves its stock to the last such op, the one that hands the
faces to the file (`recut_by`), instead of the cap. The claim test does not
compare depth: an op between them may cut the same faces from the other side.
Rough methods on a finish stage are an error (`file_to_line` finishes them);
finish methods cannot be clipped by `stock_removal_bounds` (unknown); methods
other than `stairs` and `chain_drill` along straight joins are unknown. A diagonal edge on a
`linear_table` outline is unknown: single-axis stairs along an outline are not
computed. Rasters and outlines whose edges are all axis-parallel need no
manual-arc method.

`linear_table` transforms explicit box bounds (or `sweep_bounds` in
`sweep_frame`). Exterior rectangular paths expand by offset. Pockets and faces
are rasters and need a positive `step_mm` no wider than the cutter; a pocket
also needs an explicit open side and enters wholly outside it, stepping
`step_mm` toward its far wall and stopping the offset short of it. A profile
(`profile`, `rough_profile`, `finish_profile`) with a declared `open_side` is a
one-sided side-mill, such as a blank end overhanging the vise: it is rastered as
a pocket over `sweep_bounds`, else its setup-frame `stock_removal_bounds`, so its
last pass leaves the cutter flank on the retained wall. A face
sweeps `sweep_bounds`, else its setup-frame `stock_removal_bounds`, with
passes evenly spaced no more than `step_mm` apart centre-on-edge to
centre-on-edge (one central pass when the area is no wider than the step),
stepping from `open_side`, else from the low side of the shorter span. Every
pass runs one cutter radius past both ends of the area. `step_mm` and the
cutter radius are millimetres, converted to plan units before the passes are
placed. The cycle is one way: feed the pass, lift to the op's retract Z (its
entry stock top plus `approach_mm`) and rapid back to the next pass's start; a
raster with no known lift Z keeps status unknown.
Every raster value sits on the DRO grid on the safe side: pass ends and a
face's edge passes round outward; a pocket's first pass rounds further outside
its open side and its last away from the far wall, and the material that rounding
leaves on the far wall is the profile's `grid_residual_mm`; passes between step a
whole number of grid steps no larger than `step_mm` (a `step_mm` finer than one
grid step is unknown). The raster record carries `run_axis`, `area_ends`, the
pass `ends`, `clearance_mm` (the cutter radius they run past the area) and a
pocket's `entry_pass`. The traveler prints the pass ends in the raster table; the
note above it says to lift to the raster's lift Z after each pass and names an end
(by its side), or the entry pass on its open side, in air only when it stands a cutter
radius outside the stock the kernel modelled entering the setup (its
`stock_bbox_mm`, which holds every op's stock); the op's `stock_removal_bounds`
is what it may remove, not where stock ends, so it proves neither air nor
material and an unproven end carries no claim. A `keep_out` splits passes into
pieces that also start and stop between the outer `ends`; the note then names
those as the outer ends and says every pass runs in and out clear only
when each emitted piece's start and end is proven so, stage by stage. A closed
outline's rows are on the grid too: each vertex is the nearest grid point at
least its offset outside
both wall lines it joins (a corner of its grid cell, else up to two steps out);
`grid_residual_mm` is the most any vertex stands further off a wall than its
offset. The traveler likewise names outline rows whose cutter stands wholly
outside that entry stock as cutter clearance.
A finish raster or outline whose `grid_residual_mm` exceeds its feature's
narrowest numeric tolerance band, or that has no safe grid point, is an error
(`dro_xy_residual_errors`).
Optional `contour.keep_out = [{ at = [x, y], dia_mm = d }]` declares circular
islands in `sweep_frame` (default: the feature's frame), with positive diameter
in millimetres.
The whole cutter stays outside them: centre clearance is island radius plus
cutter radius. After feed direction is established, crossing passes split into
pieces in cutting order. Each cut point lies on the setup machine's DRO grid,
rounded away from the island, so a printed piece never reaches nearer than that
clearance; pieces no longer than 1e-9 mm are dropped. Each piece
is a separate `cutter_centre` entry with the same feed/lift/rapid cycle.
`raster.keep_out` records the circles in setup XY and `raster.passes` counts
pieces. `raster.keep_out_skipped` lists the parts of the island-free passes the
circles removed, each from its entry cut point to its exit cut point (or to the
pass end where no piece is left there, wholly removed passes included), so the
printed pieces and those parts make up every pass.
Diagrams draw these pieces separately, not as a continuous swept band.
The kernel receives the same setup-frame circles and both lists: the op removes
no stock inside an island nor any its printed pieces do not sweep round it (the
cusps between piece ends), and its sampled floor poses keep outside it
([rules-geometry.md](rules-geometry.md)); an op whose raster record carries no
mapped circles or split passes leaves its cut and accessibility unknown.
Invalid circles leave the raster unknown with a reason.
Face ops without a contour print no raster: a box raster could cross retained
material inside the box. Tables are numeric nominal geometry, not cutter
accessibility, fixtures, wall thickness or collision proof; raster passes are
not kernel checkpoints. Unknown/unverified cutter or frame binding keeps status
unknown. A lathe setup with an unknown DRO controller, or a turning tool whose
nose radius is unknown, is unknown; a tailstock tool on the spindle axis
(`spot`, `drill`, `ream`, `tap`, `center`, `center_drill`) has no nose to
compensate and is exempt. M2 lathe feasibility remains unimplemented even where nominal
stations/dome tables are displayed.

**Z levels.** A milling pocket, face or profile op that authors `doc_mm` (mm)
carries `z_levels` on its `operations` entry: levels on the DRO grid, each no
more than `doc_mm` below the one before (the first rounded up from the start
less `doc_mm`, the rest a whole number of grid steps no deeper than `doc_mm`),
ending at its `dro_to_z`. Each starts at its feature's declared setup
`entry_z`, else the current top. A wall-finishing op (`pocket`,
`finish_pocket`, `profile`, `finish_profile`) keeps that start, since its flank
engages the whole wall; any other op starts lower only on the floor of an
earlier face or pocket op whose setup-frame X/Y `stock_removal_bounds` hold all
of its own and that produced its surface (its feature, or a feature whose X/Y
`bounds` hold its feature's whole footprint). Levels that cannot be placed (an
unknown start or a `doc_mm` finer than one DRO step) keep status unknown. The
traveler prints `Z start → depth in N levels of doc max` on the op row, or
`Z → depth` when the levels are one pass that starts at the depth; levels left
unknown print `?` for their count and the row's STOP stands. The
contour block heading lists every level and says to run the complete path at
the first and repeat it at each level in order.

**Hole targets.** Each located mill row (`rows`) carries `dro_xy`, its setup
X/Y at the nearest DRO grid point (a hole axis has no safe side; half a step
rounds away from zero, as `dro` does). A centre,
spot, drill, ream, tap, counterbore or bore op whose feature has exactly one
located row prints that tool-axis X/Y on its op row; an unknown one prints a STOP.

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
`direction` other than `conventional`/`climb`, an undeclared or untrusted spindle rotation
(listed in the finding's `numbers.measurements`),
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
`resolution` (`resolution_mm` or `resolution_in`, a positive length: 0 or less is
refused at load), else 0.001 plan units
(`DRO_DEFAULT_STEP`), printed at the decimals of one step (`dro_grid`). A
declared resolution whose own record is `assumed`/`illustrative` (or omitted
status) is still the step instructions round on, but every rule that judges a
value on that grid (`zero_check`, `blind_depth`, `tip_endpoints`,
`consistency`, `coordinates`) is unknown naming that resolution as debt, and
the sheet prints the declared step with its status rather than the default
grid. Every arc row and join point carries `dro_xy`, the nearest grid point no
nearer each finite wall than the exact point or the authored cutter-centre
offset, whichever is less (a corner of its grid cell, else up to two steps out,
else unknown). For chain drilling, the nearest finite finished-wall side guard
above also applies; unsigned distance alone cannot admit a finished-side point.
A table end and the join it meets print one value. Every table carries
`dro_tip_z`, and each profile and operation
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
or entry, or the op that last cut the face proven to be the one read: for
`top`, a facing op on `top_feature`; for a feature (a zero face, an op's own
feature for its start and end Z, a feature map row), an op on that feature that
leaves its face at its `to_z` (`forms_face`), or a facing or pocketing op whose
feature's X/Y `bounds` hold its whole footprint (its own `bounds`, else a Z-axis
round feature's `at` ± half its largest `dia`); overlap is not cover. An op
leaves its feature's face at `to_z` when it is a facing or pocketing op, or a
lathe turning op the kernel poses on its numeric `to_z` plane (`faced_side`: its
claimed faces all face one way along Z, as a face, part-off, cut-to-fit, groove
wall or turned shoulder does). An op leaves none only where that is known: a
manual or transfer step cuts nothing; a saw face is located by its `cut_plane`,
never a DRO Z; off the turning approach only a facing or pocketing op leaves a
Z face (a hole's `to_z` is its tip, a milled wall's its foot); and a turning op
the kernel sampled, at its numeric `to_z` or over its `z_from` to `z_to`
window, over claimed faces that are all cylinders leaves a diameter alone.
Any other op on the face is a producer whose face stands at an unknown Z, never
raw stock: one whose action is unknown; a facing, pocketing, part-off or
cut-to-fit op without `to_z`; a turning op with an unknown `to_z` (the kernel
poses no plane without a number, so its samples prove no face absent), one the
kernel has not sampled, or one whose sampled claims it posed on no one side yet
are not all cylinders (they face both ways, or their kind is unknown); a
turning window op (no `to_z`) claiming any face that is not a cylinder (the
kernel cuts a claimed shoulder or groove wall out to its window end, yet poses
it on no Z plane); and a lathe action off a lathe. An equal Z alone is never
proof, and with no footprint to prove it there is no producer.
A bounded op's coverage of the surface (for `top`,
`top_feature`, else its own feature) is whole, partial or unknown. Its
setup-frame X/Y `stock_removal_bounds` are compared with the surface's whole
footprint. The footprint comes from the feature's own `bounds` (Z from `at` when
they omit it), else from a round feature's `at` ± half its largest `dia` (else
± its `radius`) across its principal `axis`, which must be a unit vector within
`1e-6`: a scaled or zero `axis` has no known footprint. Only its `plane` value
can supply an omitted axis. A `kind = "face"` feature with no `bounds` key takes
its footprint from its `faces` list instead. Every listed ref must resolve
first: each ref's geometry-matched STEP face in an already-present successful
kernel result (`mapping` to `faces[].bbox_mm`, model-space mm), converted to
manifest units and posed in the setup frame. A bounded op covers only the
eligible faces: those whose posed box has both its lowest and highest setup Z
at the op's `to_z`, within the kernel length tolerance (`LENGTH_TOLERANCE_MM`,
1e-6 mm, in manifest units), and whose kernel `kind` is `Plane` or not known.
A listed face at another Z, such as an underside or a step, or a known
non-planar face (a `Cylinder` whose box is thinner than that tolerance) is
neither faced nor credited by that op. A feature with no eligible
face leaves coverage unknown, with debt naming the feature (no eligible face at
`to_z`), never whole. The kernel record carries no face orientation, so a
downward-facing plane lying exactly at `to_z` cannot be told from the faced one
by its box. This is an accepted limitation: a facing op cuts down from above,
so the plane it leaves at `to_z` faces +Z.
Each eligible face is judged by its own posed box. Coverage is whole only when
every eligible box lies inside the bounds by more than that tolerance on each
side, and the op's `stock_removal_bounds.z` is a finite ascending span containing
`to_z` (within `SAME_Z`); a missing, malformed or non-reaching Z span leaves it
unknown, never credited. A face edge within the tolerance of a bound may lie on either side of it,
so it is unknown (kernel bbox boundary uncertainty), never partial. Partial is
claimed only where it is known: an eligible box lies clear of the bounds, or the
setup frame turns the model axes by a signed permutation (each setup axis along
± one model axis), so the posed box is the face's exact box and bounds cutting
across it miss part of the face. Under any other turn the posed box
over-approximates the face: turned 45°, a square's box holds twice its area. Bounds
holding that box still hold the face, but bounds crossing it may hold all of a
diagonal strip, so they are unknown (rebound over-approximation debt).
A whole cover credits its eligible faces, and only them: the raw `faces` refs it
credited are reported on the touch rows that read that producer
(`credited_faces`, under Touched faces below). Authored `bounds` that are unknown,
empty, malformed or missing an axis are never replaced by the kernel boxes. When
the bounds hold the footprint, coverage is whole. When they
miss part of it, coverage is partial: the op neither advances that top or entry
nor produces the surface, which keeps the uncut height its last whole producer
left. When the bounds or the footprint are unknown, omitted, empty or malformed,
coverage is unknown: that top or entry, its producer and its operative Z stay
unknown and are never credited. A missing kernel result, unlisted `faces`, an
unmatched ref, a face record without `bbox_mm`, unknown manifest units or an
unknown setup frame leaves a bounds-free face's footprint unknown; `zero_check`
names the touched feature and that missing input. The rule never starts the
kernel. A faced surface therefore needs its footprint authored or matched.
An op whose `contour.keep_out` islands reach the surface did not cut all of it,
bounded or not. The whole cutter stays outside each island, so the land within
one cutter radius of an island stands uncut. Each circle is mapped to setup XY
as the raster maps it (`raster.keep_out`) and grown by the cutter radius. A grown
circle meeting the footprint makes coverage partial, or unknown where a matched
face's box over-approximates the face (above). An unknown cutter radius, or a
circle whose centre, diameter, units or mapping is unknown, leaves coverage
unknown, with `contour.keep_out` debt. Otherwise an op
without `stock_removal_bounds` cuts its whole feature. For another
surface, containment is proven in that feature's own frame, where its box is
exact: the setup Z must run along one of the frame's axes, and the box enclosing
the surface there must lie within the feature's spans on the other two. Overlap
or a held `at` point is partial, never whole; a setup Z oblique to the feature's
frame, or not a known unit axis (above), leaves coverage unknown. A setup-frame box
enclosing a turned feature is never taken as its cut.
An op's own start and end Z and a feature map row are path ends, not touched
faces: they pass over a turning window op on their feature. It places no face
on a `to_z` they could print, so as their producer it could only blank them. A
Z zero, a tool touch and a hole entry keep it as their producer.
A known producer counts only if it cut that face to that Z. Its
value is its `dro_to_z` on its own setup's grid (for a grooving/parting blade, the
`formed_z` its rounded corner reading leaves), re-rounded to the safe side on
the consumer's grid, so a coarser producer's −2.270 stays −2.270. That value is
unknown, never the nominal `to_z`, when the blade's reading corner, kernel side
or width is unknown, when whether the op leaves a face at `to_z` is unknown, or
when the Z touch the producer cut on has an unknown edge
or paper stand-off or meets a face standing at an unknown Z (`reads_unknown`);
the surface then prints `?`. A touch on a produced face standing off the
consumer's grid is refused under `zero_check` (Touched faces, below). A setup
that receives the part from one earlier setup (its `stock_in` names that setup;
`tip_endpoints.transfer`) prints the surfaces it receives carried over, so the two
sheets agree on their printed grid: the transfer's frames put every surface at
`Z = ±Z_before + offset` (`−` when the part turns over; Zs along another axis, a
joint or a supply carry nothing), and each `stock_state` Z it receives (`top_z`,
`bottom_z`, the end Zs, `retained_rail_bottom_z`) that links to a surface the
earlier sheet printed (its producer's printed Z, else its own arrival print)
prints at `±` that printed Z plus one shift. The shift is the least value at or
above the offset that lands those Zs on this setup's grid (the offset rounded
once, up, when they are on it already); where that would print a top the setup's
Z zero does not touch (no `top` zero, or one after an op) below its stated Z, the
shift rises to the least that lands it on the grid at or above, so a tool clear
of the printed top clears the stock. A top the Z zero touches prints carried
even below its stated Z: the touch sets the DRO to read that number there. Zs
the earlier sheet printed that are not whole steps of this grid apart (a finer
DRO before a coarser one) no one shift lands on it, and rounding each alone
would move them apart: that transfer carries none, each Z prints on the grid by
itself, and the "Starts from" line says no one shift carries them. Otherwise it
prints every carried Z and names the one transform, at every place it holds
(for example `top and rail bottoms Z = −7.080 − its Setup S1 Z`, a flip printing its
shift first so the minus cannot read as covering it), when the
shift is not the exact offset or a carried Z prints other than its stated Z
would on the grid alone. With no producer, `operative_z` reads a carried Z only
for the received surface itself: `top` or the `top_feature` at `top_z` (the Z
zero's surface, a level start on the top, a raster lift and a path's raise
above it), the `bottom_feature` at `bottom_z`; an equal Z on another face is no
proof. Any other surface Z prints on the grid by `dro_z`. Hole endpoints
carry `dro_entry_z`, `dro_exit_face` and `dro_tip_z`, the tip worked from the
printed entry (through: exit face) and rounded up again, and the `dro_depth_mm`
or `dro_exit_mm` that leaves; a through tip short of the exit face prints a
STOP. The traveler's breakthrough note gives as the run-out the lower of
`dro_exit_mm` and the same past `dro_exit_face`, cut down to the DRO decimals,
and claims none when it is unknown or negative (the op row's Z column prints the
tip and the exit face; the note repeats neither). Every row that prints a
rounded depth carries `depth_floor_mm`: the lower
end of the feature's `depth` band, or for a tap its `thread_depth` (else `depth`)
band. Any other kind of row, and a bare `depth` (an upper limit only), has an
unknown floor. A `dro_depth_mm` below its floor prints a STOP, and so does a depth
the rounding changed when the floor is unknown. A final forming cut whose `to_z`
ends on its finished face (no `exit_mm`)
and whose `dro_to_z` (rounded-up depth; a blade's `formed_z`) leaves more skin
than its feature's narrowest
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

For a regenerated chain table (`regeneration = "true_curve"`), row clip markers
record provenance, not where the chain stops. The traveler names only its
`dropped_ends` and genuine breaks between retained pieces. A retained arc/join
junction carries the chain on into the adjacent table; it never gets a note
excluding that next leg from the breakout.

Exact message:

`Feature targets use the declared model-to-setup basis; cutter tables use explicit nominal geometry and authored allowance.`

When unresolved it appends:

` Missing geometry or unverified tool/frame binding prevents a cleared toolpath.`

A bounded op's path left in pieces or none, or whose kernel clip is unknown,
appends:

` Stock-removal clip debt: op {op} {stage}: {reason}.` (`;`-joined per pass)

A finish depth the DRO leaves above its face past the feature's band appends:

` DRO depth rounding error: op {op} prints Z {dro} for to_z {to_z}: … .`

A closed `linear_table` outline with a diagonal edge appends (unknown):

` Moves between rows are unproven: op {op} {stage} needs diagonal moves: … .`

A negative rough leave on any op appends (error; every stage of that op is
withheld, numbers `allowance_errors`):

` Rough allowance error: op {op}: {rough_allowance_mm|stock_to_leave_mm} {value} is negative: the rough would cut {-value} mm into the finished part.` (`;`-joined)

A manual arc that cuts into the part or cannot be cut (a stair or hole inside the
line, leftover over the filing cap, a sagitta or chord face outside the band, a
slanted chord without a rotary table, a rotary-table recipe off its axis, a
guided sweep whose worst-case cut leaves the band or whose sweep, guide, rollers or
master cannot cut it, or an authored `arc_table`) appends (error; the stage's rows are withheld, numbers
`arc_errors`):

` Manual arc error: op {op} {stage}: … .` (`;`-joined)

Unknown manual-arc inputs (cutter, cusp/pitch/count/step, filing cap, rotary
dial, centre or swing, a guided sweep's guide, master or sweep facts) append (unknown; numbers `arc_debts`):

` Manual arc debt: op {op} {stage}: … .` (`;`-joined)

**Depth levels: entry and return (`level_paths`).** For every mill setup, each op
with a printed cutter path (stair and chord arc tables, join tables, outlines,
raster passes; rotary-table and chain-drill tables are no end-mill path) gets one
`level_paths` record: `op`, `levels` (each depth level's DRO Z, top first; one
level for a single-depth op; `unknown` when coordinates could not compute the
levels or the depth, never one level at the op's depth), `from_z` (level 1's start
Z), `entries` (each place
the cutter goes down, in the order the sheet prints the path: `xy`, `air`, `pass`
for a raster pass), `raster` and `closed` (one piece that ends where it starts).
An entry is in `air` only when the cutter stands a radius plus the kernel's 1e-3
mm tolerance outside the setup-entry `stock_bbox_mm` in X or Y; anything else
plunges into material, level `k` from level `k-1`'s Z, which the same path cut
at that spot. A raster, a path in several pieces or an open path in several
levels returns to an entry (an unknown level count claims no return between levels):
`raise_z` is `approach_mm` above the current top on
the DRO grid (a raster's lift), and `raise_clear` is true only when the stock box
proves it above the stock (unknown without a box; the sheet then claims nothing
about it). An op with any plunge carries `plunge_mm_rev` (the cited `[[plunge]]`
feed, see [cutting data](cutting-data.md#plunge), which only a tool declared
`center_cutting = true` has) and, when unknown, `plunge_reason`. Fixture and clamp
heights are not in the box: a raise Z is never
claimed clear of them.
A single-level op whose level Z is the Z it starts from carries `lowered = "top"`
only when the setup-entry `stock_bbox_mm` puts that level at or above the stock top
(within the kernel's 1e-3 mm tolerance): nothing stands above it at any entry, so
the cutter is lowered to that Z, never plunged, and needs no plunge feed. An equal
start Z alone proves nothing at the entry: a feature's declared `entry_z` or an
earlier op's cleared floor is not the stock height where the cutter goes down, so
that entry plunges (with its feed, or as debt without one).

Each of these is pass-plan debt (unknown), appended as ` Pass plan unknown: … .`
(`;`-joined with the other pass-plan debts):

- `op {op} plunges into the stock but its plunge feed is unknown: {reason}` (also
  for a tool not declared centre-cutting);
- `op {op} returns to its entry but its raise Z is unknown: it needs approach_mm
  above a known top` (not a raster, whose unknown lift is its own debt);
- `op {op} returns to its entry at Z {z}, not above the stock it receives`.

The setup sheet prints each path's record above its table: a single level as
`Enter at P1: plunge Z a → b at F mm/min.` (`plunge to Z b at F mm/min` when it starts
at b; `lower to Z b, the top of the stock this op meets` when `lowered`; or `clear of
the stock: lower to Z`);
several levels, whose Zs the block heading lists, as one statement of how each
level gets down (`plunge from the level above (level 1 from Z a) at F mm/min`)
and how it gets back between levels (`raise to Z R (above the stock), move back
to P1`, `stay at P1: the path ends where it starts`, or a raster's `lift to Z R,
rapid back to pass 1`). Unknown levels print no statement: the block keeps its
`? Depth levels not computed` line. The op row's feed cell adds `plunge F mm/min`; a
plunge without one is `STOP: plunge feed not set — {plunge_reason}`, and the
statement's plunge carries the same STOP instead of a feed. The contour heading and its
raster line print on the page of the first block, never alone.

A bench setup (machine `kind` bench or manual, no declared `resolution`) has no DRO
of its own: `dro_grid` gives it the grid of the nearest machine setup in its
`stock_in` lineage, so a surface arriving from that setup prints the same Z.

Blade grooves: a `form_*`/groove op whose tool is a grooving/parting blade gets
`plunges` numbers: the corner the DRO reads (`reading_corner`, the corner the Z
touch in effect when the op cuts set; see `zero_check` blade corners, never the
blade's `hand`) at each plunge, flush with the chuck-side
wall and stepping evenly, never more than a blade width, until the last plunge
is flush with the far wall; the diameter each stops at; and the groove they
leave (`max(span, blade_width)`). A groove outside the feature's `width` band
is an `error` (`op {n} plunges leave a groove {w} wide, outside the drawing
width {lo} to {hi}`); an unknown blade width or reading corner is `unknown`,
and the sheet stops the op ("plunge positions not set").

Blade `to_z` ops (a part-off or cut-to-fit with a grooving/parting blade): the
operation entry gets `blade` = {`reading_corner`, `forming_corner`,
`blade_width_mm`, `corner_dro_z`, `formed_z`}. `to_z` stays the face the op
leaves; the blade stands on that face's outward side (kernel op `faced_side`), so
a face toward the free end is formed by the chuck-side corner and one toward the
chuck by the tailstock-side corner. When the corner the DRO reads is the other
one, its reading is a blade width beyond `to_z`:
`corner_dro_z = dro_z(to_z - w)` for a chuck-side reading forming a face toward
the chuck, `dro_z(to_z + w)` for a tailstock-side reading forming one toward the
free end, else `dro_z(to_z)`. `formed_z` is the face that rounded reading
leaves, `corner_dro_z ± w` back toward `to_z` (never below it; off the DRO grid
when `w` is), and it is the op's `dro_to_z`: the face the residual check, the
`to_z_band` check and every later Z read off that face (a touch on it, a surface
it produced) use. A `to_z_band` is in face coordinates too: `corner_dro_band` is
that band as readings of the reading corner, each end shifted like `to_z` and
rounded inward on the grid (low up, high down), an unknown end kept unknown. A
`formed_z` outside the op's numeric `to_z_band` is an `error`
(`blade_band_errors`: `op {n} prints Z {corner_dro_z} for its {corner} corner,
which forms its face at {formed_z}, outside its allowed {lo} to {hi}`). The
sheet's op row prints `Z → {corner_dro_z} ({corner} corner)` and the band as
`allowed {lo} to {hi} ({corner} corner)` from `corner_dro_band`. A part-off or
cut-to-fit row also prints its X: `X {start} → {end} ({r} radial)`, the end the
authored `to_dia` (the axis, Ø0, unless authored) and the start that plus twice
the reach finding's `reach_depth_mm`, in the setup's X display (diameter or
radius); an unknown depth prints `X → {end} (radial plunge unknown)` and an
unknown `to_dia` or X display (`dro.radius_mode` omitted or unknown) a STOP with
no X. An unknown
reading corner, kernel side or blade width leaves `corner_dro_z` unknown with its
`reason` and the setup `unknown` (exit 4); the sheet prints "blade corner not set"
for the target and the band and stops, and the face it leaves stands at an
unknown Z for every later read (`formed_z` unknown), never at its nominal `to_z`.

Dome roughing: the rough stage of an `axial_table` op (a `form_*` op with
`rough_allowance_mm`, or a `rough_*` op) is a `stair_tables` entry, not the
finished table. Each row faces in at a finish-table Z below the apex to the X
where the sphere grown by half the diametral allowance crosses it, so every
stair corner (the imaginary-tip reading) stays that far off the dome; rows at or
past the base radius are dropped. An apex toward the chuck, or a window whose
base the sphere cannot reach (cap taller than its diameter), has no stair
(`unknown`). The finish table prints its row-to-row order for an apex-to-base
convex dome: X out to the next row first, then Z toward the chuck.

Lathe X readings: every lathe row's `x_target_mm` (feature rows, kernel span ends,
dome and stair rows, `setup_xz`, a dome's tool `x_tool_mm`) is the radius on a
radius display (`dro.radius_mode = true`) and twice it on a diameter one
(`false`). An omitted or unknown `radius_mode` leaves each of them unknown, never a
default display, and the setup `unknown` (`dro.radius_mode not stated`); the
sheet's feature map, part-off X and dome/stair tables then print no X and a STOP.

Evidence groups: frame/binding, reference rows, operation targets, profiles,
arc/line/axial tables and advanced entry surfaces. Citations: PLAN §4.1,
manifest frames/nominal geometry, plan-owned setup frames, authored contour
steps/targets/allowances,
and selected inventory cutter nominal diameter; with any manual arc, docs/plan.md
Manual arcs and, when a rough leaves stock to the file, the policy
`numbers.max_filing_stock_mm`.

## `manual_arc`

One finding per `scribe` or `file_to_line` op on an arc feature (a boss, a
radiused end or a declared semicircle), subject `S<n>:<op>`; always required
([plan](plan.md#manual-arcs)). It reads the arc's layout in the op's setup:
`centre_setup_xy`, `centre_on` (the hole whose axis is the centre), nominal
`radius_mm`, `radius_band_mm`, `convex` and `ends_setup_xy` (none for a full
circle). Unknown geometry is unknown. `radius_band_mm` is the drawing's radial
band (a full circle's diameter band halved), or for a BASIC radius or diameter a
surface profile governs the band the zone derives
([features](features.md#surface-profiles), harmonic-analyzer #1544), pointwise
from the DRF-located centre: a t = U = 0.2 zone `"increases"` a BASIC Ø20 boss to
Ø[20.0, 20.4], R[10.0, 10.2]. An ungoverned BASIC value or an unresolved profile
leaves it unknown. The `coordinates` arc tables still read the drawing band only.

- `scribe`: `layout` must be `dividers`, `trammel`, `template` or `ends` (else
  unknown); a template (`guide.template`) must be an inventory radius or profile
  gauge whose `range_mm` covers R (a range miss or another kind is an error; an
  unknown range or `verify = true` is unknown). `ends` lays out only the arc's two
  ends, for a guided sweep's stops (its centre is too far off the part to scribe
  about): `marks` A and B, each a point measured from the nearer end face along X and
  the nearer side face along Y of the stock box the setup receives, at 0.1 mm (0.005
  in), and a short stroke through it toward the arc's centre at `angle` degrees
  (0.1°) to that side face; the sweep sets each stop where its stroke, extended, runs
  through the cutter's axis, whatever its direction there.
  It needs a rectangular bar (`flat_bar`, `square_bar`, `plate`) that the setup
  receives as the plan's raw stock, its faces (`axis`, `section_axis`) square to the
  setup's X, Y and Z, a modelled stock box and both ends on the stock, and no op
  before it in the setup but another `scribe` or an `inspect` (anything else may cut
  the faces the marks are measured from); else unknown,
  since no face of the bar's own would place the marks. An `ends` layout draws no
  line: no `file_to_line`, rough or saw that follows a scribed line counts it.
- `file_to_line`: `guide.buttons` names an inventory `fixtures` kit of
  `kind = "filing_buttons"` that the setup holds (`hold.fixture` or a clamp
  `ref`), pinned through `guide.bore`. The bore must be the hole on the arc's
  axis, sized by a drill, ream or bore op before the filing; the buttons only
  guide a convex arc. The guide record carries every element's declared limits
  in mm: `button_dia_mm`, `button_bore_mm` and `pin_dia_mm` (the kit's
  `*_limits` pairs), `button_runout_mm` and the bore's drawing `bore_dia_mm`.
  The pin's largest size must enter the smallest bore and button bore. The rim
  centre then shifts off the bore axis by at most `centre_shift_mm`:
  `pin_in_bore = (bore_max − pin_min)/2`, `button_on_pin = (button_bore_max −
  pin_min)/2` and `runout = runout/2`, so the buttons file worst case from
  `button_min/2 − shift` to `button_max/2 + shift` (`files_to_mm`), which must
  sit inside the radial band. Any of those failing is an error; a kit missing
  from the inventory, not held, flagged to verify (itself or any fact), or any
  element limit unknown (absent, not two positive ordered numbers, a negative
  runout, a bore `dia` that is not a known pair of numbers) is unknown, and so
  is an unknown radius band. The traveler prints every element's limits and the
  worst-case band rounded outward to 0.001 mm (the shift basis stays in the
  report's `centre_shift_mm`), marked `not proven` unless the finding passes, or
  a STOP when the band itself is not established.
  `guide.template` instead files to a line an earlier `scribe` op laid out
  (`layout_op`; none is
  unknown). `guide.gauge` must be a radius or profile gauge covering R (no gauge
  is unknown). `rough_op` names the earlier `stairs`/`chain_drill` roughs that
  leave their stock to this file (none is unknown); `stock_cap_mm` is the policy
  `numbers.max_filing_stock_mm` (unknown unless cited, nonnegative and
  `numbers_verify` false).

`scribe` and `file_to_line` are manual actions: they need no tool, count as hand
finishing (a `file_to_line` is a finishing cut for coverage and inspection), and
a bench setup holding only manual ops is `not_applicable` for `coordinates`. The
kernel removes the filed stock within the cap from the setup's stock model: the
stock within the cap of each claimed face, of each convex edge two claimed faces
share, and, past a straight claimed-face edge that no other claimed face shares
and along which the face's tangent plane is constant, the quarter the stroke runs
on into beyond the edge and outside that plane. The last takes the corner nib
between faces filed in different ops; the finished part is never filed.

On the traveler, a `manual_arc` finding left unknown stops its op: the op's row
prints a STOP with the finding's reasons (`debts`), and the setup's STOP list
names the op, so no unproven layout or filing reads as an established step. An
error stops it the same way through the op's error box.

## `zero_check`

A dedicated saw setup (all nonmanual ops are `saw_cut` / `cut_off`, at least one
saw) is `not_applicable`: its setting is an authored blade-centre `cut_plane`,
not a spindle XYZ zero. A mixed setup still checks its other machining zero
recipes; an unknown action cannot establish the saw-only exemption.

- A `guided_sweep` on a `trammel` guide ([#269](https://github.com/pedropaulovc/prechips/issues/269), `rules/trammel.py`)
  records `guide = "trammel"`, `feed = "lever"` and `locked_axes` X, Y and Z. Its
  rows stay on the nominal cutter-centre arc, as every guided sweep's do
  (`exact_arc` hands that circle to the kernel; each row's `dro_xy` is its exact
  XY, since the DRO sets nothing); the pins put the real cutter centre on
  `pin_radius_mm = D / (2 sin α)`, judged against the band. The exact carrier pose
  on the pin circle (it turns `−ψ/2` while the cutter runs `ψ` on it) gives `carrier_turn_deg`, `rails_dir`, each
  pin's `stations_mm` at the sweep's start and end in cutting order and its exact
  `station_ranges_mm`, and `swept_mm`, the exact table-frame footprint of the pins
  and the kernel's stock box about the spindle axis. `error_terms_mm` holds the
  budget (`radius_below` and `radius_above`: the pin radius at the corners of the
  measured rail angle and spacing errors, exact since `R` is monotone in both, with
  `radius_per_deg_mm` and `radius_per_spacing` the first-order slopes for reference;
  `pin_lines`: `line_gain × (pin_clearance + rail_offset)`, `line_gain` the
  worst `|g₁| + |g₂|`, exact over the sweep's poses and taken over the crossing
  angle's measured error too, at its ends and 64 angles each way); `centre_error_mm` is the larger side, and
  `cut_radius_mm` is the wall a cutter radius off the pin circle, widened below and
  above by each side's sum, and must lie inside `band_mm`. A master or touch axis, a
  rough stage, a nonpositive pin spacing, pins that do not subtend `α`, a pin inside
  the swept window, tolerances that leave no acute crossing, and a
  carriage that may leave its `rail_travel` on the fixture at its measured tolerances
  (`station_envelope_mm`), a stop that set off its station could hold the carrier short of
  an arc end (`stops`), and a
  setup shared with another spindle op, or a machine not a mill, are errors; a start not proven clear of the
  stock at every pose the first stop can hold (`start`, proven exactly over that band from
  the arc's true X and Y extremes) and any unmeasured fixture
  fact are unknown, with a `measure:` entry for each fact.

As on every guided sweep ([#258](https://github.com/pedropaulovc/prechips/pull/258)),
each of the trammel's geometric proofs carries one DRO step of margin (`margin_mm`): the
cut's widening below and above, the stops' setting error and the start's clearance; an
unmeasured DRO resolution leaves the margin unproven, as debt. Any error or debt the rule
records (`open_debts`) stops the card even when no printed value shows it.

The stops, the start and the rails' travel are proven on the fixture at its measured
tolerances, not the nominal one: for every corner of the rail angle and pin spacing errors
and each pin-line off by its pin clearance plus rail offset either way, with each stop set
at its printed 0.1 mm station off by half a millimetre of rule plus one DRO step either
way, the carrier's pose is solved exactly from its two pin-on-line constraints
(`stop_bands_deg`, the cutter's angle about the arc centre at each stop; `stop_radial_mm`,
how far it stands off the nominal path there; `stop_stations_mm`, each pin's station).

#### Trammel operator sequence

What the operator does with a trammel card ([#289](https://github.com/pedropaulovc/prechips/issues/289)),
what each printed number is measured from, which physical reference sets it, and how
its error reaches the cut. Every value printed here is in the card's one gate
(`sheet_sweep.TRAMMEL_PRINTED`): an unproven one prints only a STOP.

| Step | Printed | Measured from / set by | Its error reaches the cut as | Bounded by |
|---|---|---|---|---|
| 0. Rails aligned (once per install, [#270](https://github.com/pedropaulovc/prechips/issues/270)) | rail angle `α` (information) | the commissioning readings that put both pin-lines through the spindle axis | the rails' crossing angle: radius `R(D, α)`; a pin-line off the spindle axis: about 1:1 | the measured `rail_angle_error` at its corners; `rail_offset` through `line_gain` |
| 1. Seat the pin pair | pair name, spacing `D` (information) | the carrier's drilled pin holes | spacing: radius `R(D, α)`; a pin's play in its carriage: about 1:1 | `pin_spacing_error` at its corners; `pin_clearance` through `line_gain` |
| 2. Lock X and Y on the rails' crossing | none (no X/Y pickup, no DRO sign) | the spindle left where step 0 aligned the rails | moving X/Y offsets both pin-lines: radial about 1:1 | the card forbids moving them; the zero owes no X/Y |
| 3. Clamp the stops on rail 1 | each end's pin station, 0.1 mm, from the spindle axis and along the rail from the carriage's near end stop (`rail_travel` near limit) | a steel rule from that end-stop position | a stop off by up to 0.55 mm holds the carrier at another pose (`stop_bands_deg`, the exact inverse of the station); it never moves the radius | an error unless the worst stop, on the fixture at its tolerances, still holds past its arc end; debt unless the cutter goes down in air at every pose the first stop can hold |
| 4. Check rail 2's stations | the other pin's stations at both stops | the same rule on rail 2 | a mismatch means the rails or pins are not as set | the card says STOP on a mismatch |
| 5. Dry pass | none | — | clamps or holder in the path | `headroom` owes this check at every pose |
| 6. Start the spindle, set and lock Z | spindle direction; Z at DRO resolution (each level when stepped) | the setup's Z zero | one DRO step of Z moves the depth only, never the radius | the tip rules; not the trammel's |
| 7. Lever stop to stop | the carrier's turn, sweep angle, cutter travel, pace (information) | the stops | the carrier must keep both pins seated: a pin lifting out of its carriage is outside every bound | the card's instruction |

The rule's `cut_radius_mm` bound encloses every wall an independent model of the
perturbed fixture finds: the rail angle and spacing at either tolerance limit, each
pin-line off by its clearance plus offset either way, and both stops 0.55 mm off
either way (tests/test_trammel.py). The radius terms bound `R` itself, while
the work sits on the pins, so the wall moves far less than `R` does: the bound is
conservative.

A setup whose every spindle op (one with a `tool`) is a `guided_sweep` needs no X
or Y recipe ([#255](https://github.com/pedropaulovc/prechips/issues/255)): the
sweep's touch-off against its master sets them and X/Y stay locked, so an omitted
`zero.x`/`zero.y` there is not a gap. The finding names those axes and ops in
`touch_set`, and the DRO ZERO sheet prints that X and Y take no edge pickup; Z
keeps its recipe. The touch feed and a rough back-off still move those axes by
their DRO sign, so a reversed `dro.direction` for them is the same error, and an
undeclared one the same debt, as under an edge pickup. Any other spindle op in the
setup still needs both. When every such op is a trammel, nothing moves X or Y at
all (the rails' crossing fixes the cutter), so no X/Y DRO sign is consumed, and an
authored `zero.x` or `zero.y` is an error (its pickup would move the table off the
crossing);
`touch_set.by` is `"trammel"` (else `"touch"`) and the DRO ZERO sheet says the
rails' pin-lines cross on the spindle.

EL400 ABS Axis Set, not Preset. Approach side is independent of jog polarity.
For edge finding, `contact=edge + side*finder_radius`, side -1 from negative
axis and +1 from positive axis; indicated pickup uses radius 0. Paper Z uses
`contact=edge + side*paper`, where side is the side of the face the tool meets
it from (see "Paper side" below); touching `top` takes the received/advanced
stock top.
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

An X/Y pick-up with an `edge_finder` tool (not `from = "indicated"`) records the
finder's procedure facts on its row as `finder`: `finder_type`, `tip_dia_mm`
(`tip_in`; a tip absent altogether reads the catalogue `dia`, a tip declared
`"unknown"` stays unknown), `radius_mm`, the finder's `finder_rpm_range`,
the setup machine's spindle bands `machine_rpm` (`[[lo, hi], …]`: `ranges_rpm`,
each clipped to a stated `rpm_min`/`rpm_max`, else `[[rpm_min, rpm_max]]`) and
`rpm`, the bands it runs at (the finder's band intersected with each spindle
band; a gap between bands is never filled; an electronic finder runs with the
spindle stopped, `not_applicable`). A missing type, tip or mechanical rpm
range, or any unknown endpoint of either band, leaves the zero unknown; a
finder band no spindle band turns is an error. The traveler prints these once
per finder and mill as the EDGE FINDER box ([inventory](inventory.md#edge-finder)).

For each authored Z `retouch_after`, the new set value is advanced top + paper.
A profile does not move the touched top. A listed retouch sets Z for the next
cutting tool only: each `retouch` row carries `next_op`, `next_tool` and
`tool_change` (true when that tool is not the one in the spindle, unknown when either
tool is unknown; past the last cut `next_op`/`next_tool` are `not_applicable` and
`tool_change` false). The sheet tells the operator to
install the incoming tool, then touch the top and Axis Set Z; with no change, the tool
stays in and only re-touches.

X `method = "trial_cut_measure"` cuts a diameter, measures it at the machine
with the declared `gauge` and Axis Sets that reading. Like paper thickness the
reading is a bench value, so the recipe is complete when `tool` and `gauge`
resolve without a verify flag, `check_jog_mm` is numeric and the lathe
`radius_mode` is known. The rows show bench expressions: diameter mode
`measured D`, check `D +2j`, mirror `D -2j`; radius mode `measured D/2`,
`D/2 ±j`. A target diameter is never used as the measurement.

Z `method = "measure_then_set"` touches a face whose position is measured at
the machine (M, read with `gauge` as the stated `measure`) and Axis Sets
`M + offset_mm + side*paper_mm`; check/mirror are `M ±j` on the same base. Like a
trial cut it is complete when `gauge` resolves unflagged, `measure` is stated
(`"unknown"` states nothing) and `offset_mm`, `paper_mm` and the jog are
numeric; the rows show `M -9`, `M +1`. The same holds for a tool touch's
`z_measure`.

Each `[[setups.zero.tool_touches]]` entry is complete when its `tool` and X
`gauge` resolve without a verify flag and `edge_mm` and `paper_mm` are numeric:
`x_axis_set` is the measured-diameter expression plus the X paper
(`x_paper_mm`, once on the radius: `measured D + 2p` on a diameter display,
`measured D/2 + p` on radius; a `trial_cut_measure` touch makes its own
diameter and takes none; unknown paper is unknown) and `z_axis_set` is
`edge_mm + side*paper_mm`. A mill touch sets Z only (`x_axis_set = "not_applicable"`):
the mill X/Y read the spindle axis whatever the tool. A touch with
`method = "measure_then_set"` sets `M + z_offset_mm + side*paper_mm`, M read with
`z_gauge` as `z_measure`. Missing tools, unverified finder/gauge facts, missing
recipes and unknown frame binding preserve unknown. A lathe does not require a
Y zero recipe.

A lathe X touch is set on the diameter actually touched (D2), so `x_face_status`
checks it stands where the touch is made. A `trial_cut_measure` touch passes.
`x_face = "x_zero"` (this setup's X-zero trial-cut land) is an error when the X
zero is no trial cut or comes after the touch, and `unknown` once a cutting op
runs after the zero (the land is no feature the rule can follow). Any other
`x_face` must be a plan feature (else error) whose latest naming op before the
touch, in this setup then back through the earlier setups of its `stock_in`
lineage, turns it (`turn`, `rough_turn`, `finish_turn`): an op that cuts it
otherwise is an error, an op naming no feature `unknown`; never turned and not
supplied as-is (`stock.as_is_faces`) is an error, or `unknown` when the lineage
omits `stock_in`. No `x_face` names no surface: `unknown`. The traveler prints the
touch's contact whatever its `x_method` words say: the surface (`on the {x_face}
Ø, measured`) and the paper the Axis Set counts (`paper {x_paper_mm}`, `no paper`,
or `paper ?` when unknown; a `trial_cut_measure` touch is its own surface and
takes none), then the words, its Axis Set X and, for an error or unknown, a STOP.
A derived X re-touch is a direct touch on the measured diameter (`x_paper_mm = 0`).

A datum `transfer` with `keep_clamped = true` cannot be tapped true: a sweep over
its `runout_limit_mm` needs the plan's `recovery`. Without a stated `recovery`
(missing, blank or `"unknown"`) the finding is `unknown` (`state
transfer.recovery`), and the traveler prints a STOP in place of the transfer.

Paper side: paper lies between the tool and the face, on the side the tool meets
the face from, so a Z touch through `paper_mm` of paper (the zero, a tool touch or
a derived re-touch, which repeats its source's paper from the same side) stands
the tool `side*paper_mm` off its edge. Off a lathe the tool comes down on its
face: +1. On a lathe the side is the touched face's outward normal along setup Z
(as for blade corners below); without one, a grooving/parting blade meets the
face on the side of the corner it sets (its authored `corner`: chuck-side +1,
tailstock-side -1) and any other tool from +Z. A blade touch through nonzero paper
whose side is unknown has an unknown Axis Set; with no paper the side does not
matter. `paper_mm` itself is always printed as the positive thickness. A listed
top `retouch_after` is `top + paper`.

Blade corners: a Z touch (zero, tool touch or derived re-touch) by a
grooving/parting blade sets one of its two corners. `reference_corner` comes
from the touched face's outward normal along setup Z, read from the kernel's
`revolved.<face>.end_faces` at the touch's `edge_mm` (all end faces when none is
at that Z and they agree): a face toward the free end (+1) gives
`chuck_side`, one toward the chuck (-1) `tailstock_side` (`corner_from = "face
normal"`). Without a measured normal (a scribe, a stock end) the touch's
authored `corner` is used (`corner_from = "authored"`), else the corner stays
`unknown`; its Axis Set is still complete, while every blade op that reads it is
`unknown` under `coordinates`. An authored `corner`, or a corner its `method`
text names ("chuck-side corner", "tailstock-side corner"), that the face's
normal contradicts, or a touch naming both, is `corner_error`: the corner stays
unknown and the finding is an `error` (`A blade's Z touch names a corner its face
cannot give (...)`). The sheet names the corner in the touch ("Z — chuck-side
corner on the ...; Axis Set Z ...: Z now reads the chuck-side corner"), in the
zero row and in a re-touch, and stops a blade touch whose corner is unknown.

Tool setting: on a lathe, `tool_setting` lists one record per toolpost tool (a
tool some non-axial op of the setup cuts with) at its first touch-off in the
setup, in op order: the zero (`touch = "zero"`, `axis`), else its first
`tool_touches` or `derived_touches` entry (`index`). Each carries
`centre_height` and, for a grooving/parting blade, `square_blade` (otherwise
`not_applicable`): the setup machine's `toolpost` words, else the requirement
alone ("set its cutting edge on spindle centre height", "square the blade to the
spindle axis"). The sheet prints "Before touching off {tool}: ..." before the
zero table for the zero's tool and before each other tool's first touch. Cited
to Moltrecht, *Machining for Hobbyists: Getting Started* (2015) ch. 6 p136
Fig. 6-7 and p147 Fig. 6-20, plus the toolpost's own `cite`.

One DRO per setup: the DRO reads the tool that last set it, by the zero, a tool
touch (made before the first of its `before_ops`, else after its `after_op`) or
a listed retouch. Ops before the Z zero's `after_op` run before any tool set Z,
and an axis with no zero recipe has no tool's Axis Set to change (the missing
zero is unknown). Every cutting op whose tool did not make the latest Axis Set
is touched off first (`derived_touches`, printed "re-touch" at that op). The
source's recipe names its own tool's edge, so the re-touch is tool-neutral:
`edge_then_set` on a lathe (Z-cutting edge to the surface, withdraw along X),
`touch_then_set` on a mill:

- Z on the latest touched or faced surface proven to stand at a known plan Z:
  the zero face, a tool-touch face, a listed retouch's top or a face/pocket op's
  `to_z` (faced surfaces take the zero's paper). The rule tracks each surface
  across the ops since it was made, using each op's coverage of it
  (`cut_coverage`: whole, partial or unknown). A surface ends when an op cuts all
  of it (the top: faces the stock's `top_feature`, or any face op when there is
  none) to another Z or to no stated Z (`to_z` omitted or `"unknown"`), or cuts it
  other than by facing/pocketing. Ops that each cut only part of it leave it at
  its uncut Z only while a land of it lies outside all of their
  `stock_removal_bounds`: a square `TOUCH_LAND_MM` (0.5 mm) on a side, AUTHOR'S
  CHOICE. A paper touch needs a patch the operator can see, set the tool end over
  and slide paper under; a narrower sliver may hold no flat surface once the burrs
  of the cuts beside it are counted, and whether it is there at all can rest on
  geometry no operator can check. The value is illustrative, not measured; a
  larger one only leaves more Z unknown, and a narrower land is unknown, never
  pass. The land must lie on surface shown to be there: the kernel's one STEP
  face for the feature (`faces`) is a plane that fills its own box (`fills_bbox`:
  one wire, each edge a straight segment within the kernel's 1e-6 mm side
  tolerance of a side of the box, more area than that band), flat in setup Z,
  with each box corner on a corner of its setup X/Y box, which is the footprint.
  Within `FILL_MARGIN_MM` (1.5e-6 mm: that side tolerance plus the 5e-7 mm the
  record's 6-decimal rounding may move each side) and the 1e-6 corner tolerance of
  a side of the box, a notch may still run, so no land counts there. Without a
  kernel result, or for a round, holed, notched or L-shaped face or one turned
  against the setup axes, the box's corners may hold no surface, however little
  of its area the face lacks: a 0.005 mm hole can be the only part of the box
  every cut spares. A touch on a surface, whether a zero, a tool touch or a
  listed retouch, is a paper touch at
  a nominal Z. It does not show what the ops since the surface was made left of
  it, so it carries their partial cuts and any doubt about them. A touch on a
  surface an op in the setup made is proven only at the Z that op made, and a
  touch on the top only at the tracked top's Z. Only a whole cut makes a new
  surface. The top a zero `after_op`, a listed retouch or a tool touch touches is
  the top so tracked, so a face that states no depth leaves it unknown. A surface
  is not proven while:
  - it is unnamed (a zero with no `face`);
  - an op on a feature the plan does not name has run since it was made, or a
    face op while the stock's `top_feature` is unresolved (the top);
  - an op's coverage of it is unknown (a footprint missing an input names the
    touched feature and that input, such as the kernel result, an unmatched
    `faces` ref or its `bbox_mm`), it may be gone, or a touch on it disagrees
    with (or cannot be checked against) the Z its op made or the tracked top's;
  - partial cuts together leave no land of it, or it is not shown to fill its
    footprint.

  With no proven surface, the latest one not shown gone is repeated with Z and
  Axis Set unknown (unknown). A measured Z (`trial_cut_measure`,
  `measure_then_set`) is no plan number to repeat.
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

Touched faces: every non-measured Z touch (the zero, a tool touch, a derived
re-touch or a listed top retouch) sets its Axis Set from the known face height
in this setup's frame. When an op cut that face under a set Z DRO in this
setup before the touch (the producer `operative_z` finds: any op that leaves
the face at its `to_z`, `forms_face`, a facing op or a blade part-off alike;
ops before the setup's Z zero do not count: the zero places their faces),
the face stands at that op's `formed_z` (`face_stands`), and the
touch sets that standing Z, not its authored edge. The row's numeric `edge_mm`
(a retouch's `top_z`) is that standing Z, and its Axis Set, check and mirrored
readings follow from it. The DRO stops a cut at its `to_z` rounded up onto the
grid, so an authored edge whose own DRO reading (`dro_z(edge)` on this setup's
grid) is the standing Z is that rounding and passes silently. On a 0.005 grid
with 0.05 paper, a floor and edge of 5.21875 stand at 5.220 and set 5.270; 7.497
stands at 7.500 and sets 7.550. An edge read on any other step contradicts the
face: an `error` naming the edge, its reading and the standing Z, with no
numeric tolerance. A face
standing off this DRO's grid (a blade's off-grid width, a finer producer grid)
is set where it is not, so every Z the tool then cuts to lands off by the
difference: an `error`
(`{who} sets {face} as Z {shown}, which stands at {formed_z}`), whatever cut
reads the touch next. An earlier setup's native credited plane uses the
carried-face rule below, not this frame's one-sided cut rounding.
A face standing at an unknown Z (`formed_z` unknown, including an op that
may have left it, `forms_face` unknown) is `unknown`, and
the sheet prints its Axis Set as `?`. A measured touch reads its face and is
not checked; a face no op produced (the stock, or a face only a saw, a manual
step or a cut proven to leave none, such as a diameter alone, touched) stands
where the touch sets it. A bounds-free `kind = "face"` feature named only by its
matched STEP faces needs a whole eligible producer or the traced carry below:
unfaced, partly faced, beside a `keep_out` island, or unknown coverage leaves
its Z unknown, never the authored edge or the raw stock height. Only the
genuine raw `top` stands where the touch sets it.
Owning a native face is not itself plane evidence: a new touch surface needs a
native plane at the cut's raw `to_z`. A known cylinder remains ineligible even
when its enclosing Z span happens to fit the length tolerance.
A touch whose producer was credited from matched kernel planes reads them only
from above: off a lathe a tool touch comes down on its face, and a zero or
listed retouch must come `from = "+z"`. An unknown or other side may meet
another face, so it is `unknown` and takes no credit. Each zero-check row that
reads such a producer (`axes.z`, `tool_touches`, `derived_touches`, `retouch`)
lists the raw STEP refs credited in `credited_faces`, absent when none. The
report JSON retains those proof refs for validation; the operator traveler names
the face and any required contact constraint, without raw native entity IDs.

A whole credited face may carry through the traced `stock_in` lineage into
a bonded or remounted setup. An intervening cut that can lower that face, or
whose effect is unknown for it, breaks the credit; an untraceable stock link
also leaves it unknown. The new physical height carries the producer's AS-CUT
`formed_z`, not the native CAD nominal. The source native plane establishes
identity, orientation and raw nominal Z; its point is displaced by
`formed_z - native_z` along source setup Z, then that displaced point and the
normal pass through the recorded source and receiving rigid frames.
A transformed native box
proves the height only when its setup-Z span is flat within length tolerance.
An enclosing box whose oblique turn loses the plane's coordinate correlation
cannot prove it. Exact existing native plane evidence can: a source setup's
`revolved` fact with `kinds = ["Plane"]`, a flat native `end_faces` plane and
its outward `normal_z`, bound to the face its cut produced. Both its point
and normal are transformed through the recorded source and receiving rigid
frames; the receiving normal must be +Z within the native direction guard
of 0.000001 degrees (also used for plunge parallelism). Frames must have finite
unit, orthogonal bases.
Alternatively, a bound setup-local scene datum needs that normal and an outline whose Z span
lies at the touched height within length tolerance. Native datum facts are
emitted only after the native stock carries their surface. Missing facts stay
unknown; an unrelated datum or the enclosing oblique box is never a substitute.
No kernel run or new native fields are added for this.

An overlapping axial drill, ream, spot or counterbore preserves usable touch
land only when a single native `Plane` with `fills_bbox = true` proves an
axis-aligned rectangle retaining a 0.5 mm square outside the cumulative
bounded footprint. The worst-case radial footprint includes its cutter and
aim shift. Radius extrema alone prove neither circular topology nor usable
land; round, holed and missing-shape faces stay unknown after an overlapping
plunge, pending [native topology evidence #208](https://github.com/pedropaulovc/prechips/issues/208).
For a resolved `center_drill_set` member, engagement no deeper than its pilot
length uses the pilot radius; deeper engagement uses
`pilot_radius + (depth - pilot_length) * tan(countersink_half_angle)`,
bounded by the body radius. Missing member geometry leaves the footprint
unknown; the pilot alone cannot prove clearance after the countersink engages.
The credited touch then carries
`touch_exclusion_dia_mm` in physical millimetres (zero before any relevant
plunge); the card requires `touch the face outside Ø… mm` when it is positive,
with that diameter rounded outward to the sheet's millimetre precision. A
footprint covering the face, an oblique plunge, a lateral sweep that could
lower it or any unbounded effect leaves the carry unknown, never a guessed Z.

A carried face was not cut onto this frame's grid. Its authored edge must
agree with the transformed physical height or the exact raw native plane
within the existing length tolerance, else an error names the mismatch.
An authored nominal edge matching that raw plane does not contradict a
proven producer's rounded AS-CUT height. An unknown producer cut cannot
invent an AS-CUT height: it stays unknown unless the existing native-fallback
rule explicitly proves the fallback.
From above, its Axis Set rounds physical height plus paper **down** to the
receiving DRO grid, unlike the upward rounding of a cut endpoint. The finding
records `setting_residual_mm` (physical height plus paper minus typed setting,
in mm), nonnegative and at most one receiving step. With no paper, a physical
21.0075 face on a 0.005 grid sets 21.005, retaining +0.0025 mm; it must not set
21.010 and make later authored tips cut deeper. S2's raw nominal 21.0055
faces to 21.01 on its lathe's 0.01 grid; carried unchanged into S9 it is
physical 21.010 and sets 21.010, residual zero.
For a unit-converted grid with a recurring decimal step, contact equality uses
the actual printed grid-line value at the grid's display precision, not an
ideal step quotient. Only binary roundoff may meet that line from below;
the native length tolerance never permits rounding a genuinely lower contact
up onto it.
For an imported hole entry, `stock_state.entry_z.<feature>` (or `top_z`
when it supplies that entry) must remain the transformed **native nominal**
within the physical length tolerance of 0.000001 mm, in the manifest's units.
Only the touch's authored edge may alternatively name the proven AS-CUT height.
Entering that AS-CUT height in both fields would apply the producer offset
twice: it is a deterministic `error` naming the authored stock-state field,
with no numeric operative entry, tip or through exit offered. Unknown native
evidence or an unknown entry stays unknown, not a mismatch. An entry advanced
by a cut in this same setup already belongs to its own DRO and keeps that
local producer's endpoint rather than being shifted as imported stock.
Every later operation's operative entry, depth, exit and breakthrough uses
the actual typed Axis Set; physical face height remains separate evidence.
Cut endpoints still use ordinary upward `dro_z` and retain their depth guards.
For a through hole, `physical_exit_bound_z` is physical entry minus the
declared `local_thickness`: a dimension-derived worst-case exit boundary,
not evidence of an independently identified native exit plane. Its operative
`dro_exit_face`, tip and breakthrough margin remain conservatively anchored
to the typed entry. A longest allowed thickness does not establish the
actual opposite face's AS-CUT height.

Templates:

- `DRO direction or mode disagrees with the setup convention; stop and correct it before the check jog.`
- `Touch, Axis Set the compensated value, then jog without retouching and compare expected versus mirrored readings.`
- The latter appends, when touches were derived:
  ` Each tool change is touched off on the last touched or faced surface still standing.`
- when a touch is missing:
  ` A tool cuts on a DRO another tool set and no standing plan surface is known to touch it off on: plan a tool touch before op {op}, ….`
- when unknown:
  ` Measured setup/tool or trial-cut verification remains unknown.`
- then (after any blade-corner sentence), when a touch sets its DRO off its face:
  ` A Z touch sets its DRO off where its face stands ({who} sets {face} as Z {shown}, which stands at {formed_z}; …): every Z the tool then cuts to lands off by the difference. Plan the face onto this DRO's grid, or set Z from a measured reading of it.`
  An authored edge on another DRO step is listed there as
  `{who} on {face} uses edge {edge} (DRO Z {dro_z(edge)}); the face stands at {stands}`.
- when a touch meets a face standing at an unknown Z:
  ` A Z touch meets a face its op left at an unknown Z ({who} on {face}; …): its Axis Set is not known.`
  Missing eligible native-plane evidence is listed as
  `{who} on {face} ({face} has no eligible native plane at raw to_z)`;
  failed carry provenance or surviving-area proof as
  `{who} on {face} (no surviving credited stock plane with a bounded touch area for {face})`;
  and a credited plane met from no known side above as
  `{who} on {face} (native-plane credit requires a known +Z/above touch)`.

Evidence: per-axis contact/set/check/mirror/sign, source edge, finder radius,
paper, jog and DRO direction, retouch list, per-tool touches, derived and
missing tool-change touches and transfer.
Citations: PLAN §4.1 and Electronica EL400 Operation Manual §6.2 p20, §7.4 p31,
§8.1 p37, §9.2.1 p62; plan zero/stock-state and inventory finder nominal size.
The recipe says **jog without retouching**. Physical emulator direction and
actual check readings must be exercised by the operator; local computation does
not prove the paper/emulator acceptance control.
