# Coordinates and DRO zero

Both rules produce one subject per setup. Nominal numeric recipes and tables can
remain useful while their status is unknown; they are not cleared toolpaths or
measured first-article evidence. Report numbers retain precision; bench tables
use drawing precision. No STEP extraction/kernel geometry is performed.

## `coordinates`

A feature-local point is transformed to model coordinates as
`model = feature_frame.origin + sum(local[j]*feature_frame.basis[j])`.
A setup coordinate is `(model - setup.origin) dot setup.basis[axis]`.
Unknown components propagate only through nonzero coefficients. Tolerance-band
midpoints never define nominal geometry: explicit `*_nominal` values take
precedence, otherwise only scalar dimensions are usable as nominal geometry.

Feature reference centres are distinct from hole tool-tip endpoints (those
belong to `blind_depth`). Lathe rows carry drawing stations, authored operation
endpoints, nominal diameter and radius/diameter X display. An authored local Z
can substitute for an unknown model transform only in an unbound frame; the row
retains `local_from = {op, field, axis}`. This does not bind fitted shaft length
to nominal model geometry. Dome axial samples compute
`radius=sqrt(sphere_radius^2-(z-sphere_centre_z)^2)` at authored steps and include
the exact endpoint. Tool-nose compensation remains unknown.

For contours, cutter radius is selected diameter/2; rough offset adds authored
`rough_allowance_mm` or `stock_to_leave_mm`. `arc_table` uses explicit centres,
nominal radii and known finite geometry: a boss is a full circle, a declared
upper semicircle is 0–180°, and finite rocker arcs derive endpoint angles.
Internal/top arcs subtract offset; outside/bottom arcs add it. Samples include
exact endpoints and angular grid checkpoints. `start_deg`/`end_deg` are accepted
schema fields but the current rule derives bounds from geometry rather than
using those fields to override the arc. A full circle needs continuous
interpolation; its checkpoints are not straight-chord cuts. Finite arc records
include sagitta `R*(1-cos(min(step,span)/2))` and exact offset joins. Linked
`top_edge_feature` geometry supplies line-circle intersections and a line-line
miter; mirrored sides are explicit. Degenerate/unknown joins do not become
invented paths.

`linear_table` transforms explicit box bounds (or `sweep_bounds` in
`sweep_frame`). Exterior rectangular paths expand by offset; pockets require an
explicit open side and positive `step_mm`, with outside entry and finite raster
passes. Tables are numeric nominal geometry, not cutter accessibility, fixtures,
wall thickness or collision proof. Unknown/unverified cutter or frame binding
keeps status unknown. M2 lathe feasibility remains unimplemented even where
nominal stations/dome tables are displayed.

Exact message:

`Feature targets use the declared model-to-setup basis; cutter tables use explicit nominal geometry and authored allowance.`

When unresolved it appends:

` Missing geometry or unverified tool/frame binding prevents a cleared toolpath.`

Evidence groups: frame/binding, reference rows, operation targets, profiles,
arc/line/axial tables and advanced entry surfaces. Citations: PLAN §4.1,
manifest frames/nominal geometry, authored contour steps/targets/allowances,
and selected inventory cutter nominal diameter.

## `zero_check`

EL400 ABS Axis Set, not Preset. Approach side is independent of jog polarity.
For edge finding, `contact=edge + side*finder_radius`, side -1 from negative
axis and +1 from positive axis; indicated pickup uses radius 0. Paper Z uses
`contact=edge + paper`; touching `top` takes the received/advanced stock top.
Physical positive-axis jog gives `check=contact + sign*scale*jog` and
`mirror=contact - sign*scale*jog`. The sign comes from authored DRO direction;
lathe diameter-mode X uses scale 2 for the physical X jog, otherwise scale 1.
Direction `right/away/up` (or lathe `away_from_spindle_axis/toward_exposed_end`)
is positive. Reversed direction or a non-ABS known mode is an error.
`edge_mm` explicitly locates a named pickup in the setup frame. Only Z
`face = "top"` substitutes the received stock top. Another named face (such as
an ear's inner face) uses its own authored edge; stock top is not its fallback.

For each authored Z `retouch_after`, the new set value is advanced top + paper.
A profile does not move the touched top. A trial-cut method cannot take a target
diameter as a measurement; the current input schema has no measured-diameter
field and the resulting Axis Set remains unknown. Per-tool touch X stays
unknown; known authored Z edge/paper can be displayed without certifying it.
Missing tools, unverified finder/gauge facts, missing recipes and unknown frame
binding preserve unknown. A lathe does not require a Y zero recipe.

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
