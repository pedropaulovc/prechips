# Coordinates and DRO zero

These rules check setup coordinates, manual arc layout and filing, and digital
or mechanical readout zero recipes. `coordinates` and `zero_check` produce one
finding per setup. `manual_arc` produces a finding per applicable operation,
with a subject such as `S1:40`.

Nominal numeric recipes and tables can remain useful while their status is
unknown. They are not cleared toolpaths or measured first-article evidence.
Nominal contour geometry comes from the manifest. Existing kernel results
also supply facts used by these checks, including feature locations,
bounded contour clips, blade-face side (`faced_side`) and setup-entry stock
boxes (`stock_bbox_mm`) for swing and entry checks. `zero_check` can consume
native-plane evidence, including `revolved.end_faces` for touch-side and
blade-corner selection. These rules never start the kernel. A bounded table
without a matching, known kernel clip is withheld.

Use this reference to interpret a finding. For a worked run, see the
[demonstration](manual/demo.md). For procedures and recovery, see the
[quickstart](manual/quickstart.md), [tutorial](manual/tutorial.md),
[troubleshooting](manual/troubleshooting.md) and [FAQ](manual/faq.md).
Command syntax is in the [CLI reference](reference/cli.md); importable interfaces
are in the [Python reference](reference/python-api.md). Implementation ownership
and contributor checks are in [architecture](internals/architecture.md) and
[development](internals/development.md).

| Finding or task | Reference |
| --- | --- |
| Locate a feature or choose its aimed target | [Frames and feature locations](#frames-and-feature-locations), [mill targets and aims](#mill-targets-and-aims) |
| Interpret manual cutter-coordinate tables | [Contour stages and joins](#contour-stages-and-joins), [manual arc methods](#manual-arc-methods), [linear paths and rasters](#linear-paths-and-rasters) |
| Check printed coordinates, depth and entry | [Printed values and surface provenance](#printed-values-and-surface-provenance), [depth entry and return](#depth-entry-and-return-level_paths) |
| Interpret a lathe table | [Lathe stations and nose compensation](#lathe-stations-and-nose-compensation), [blade and dome targets](#blade-and-dome-targets) |
| Resolve manual layout or filing debt | [`manual_arc`](#manual_arc) |
| Resolve a zero or tool-touch finding | [`zero_check`](#zero_check) |
| Interpret inch handwheel targets or unresolved physical pickups | [Mechanical dials and unknown readouts](#mechanical-dials-and-unknown-readouts) |

## Numeric precision

Report numbers retain precision. Sines, cosines and arctangents come from
`prechips.trig` (fdlibm's algorithms in IEEE double arithmetic alone), and
squares are products. They do not use the platform libm's `sin`, `cos`, `atan2`
or `pow`, whose last bit differs between the Windows CRT and glibc. The same
inputs therefore give the same tables to the last bit on every platform;
report values are not rounded for print.

Bench drawing station and feature reference points use the dimension's
declared drawing precision. A known number without one prints its own value
(six significant digits), not `?`, which is reserved for unknown values.
Operation-derived rows, computed tip targets, Z stations and contour
cutter-centre tables always print their own value, never a value rounded to a
drawing dimension's display precision.

## `coordinates`

### Manual-bench applicability

`coordinates` is `not_applicable` for manual bench work with no DRO target
or cutter-centre table. The exemption requires all of these facts:

- The selected machine resolves to `kind = "bench"` or `"manual"`.
- The setup has at least one operation.
- Every operation is `fit`, `inspect`, `deburr`, `coating`, `scribe`,
  `file_to_line`, `hand_tap` or `die_thread`, or is a `saw_cut`/`cut_off` whose
  selected tool resolves to a verified `hand_saw`.

The machine kind alone waives nothing. Another or unknown action, a powered
saw blade or an unresolved saw tool leaves the machine checks in force.
`zero_check` uses this same predicate for its no-DRO-zero exemption.

### Manual-thread-only applicability

Both `coordinates` and `zero_check` are `not_applicable` for a manual-thread
setup when all these facts hold:

- The selected machine resolves to kind `bench`, `manual`, `lathe`, `mill`
  or `drill_press`.
- At least one operation is `hand_tap` or `die_thread`.
- Every operation is a manual action: `inspect`, `deburr`, `coating`, `release`,
  `fit`, `scribe`, `file_to_line`, `hand_tap` or `die_thread`.

A powered cut, a saw operation, an unknown action or an unknown machine kind
cannot use this separate exemption. A bench may still qualify under its
existing verified-hand-saw predicate above. The manual-thread finding records
`manual_thread = true`; it requires no digital pickup or coordinate table.
This does not waive tool/holder resolution, stopped-spindle enforcement,
physical workholding, thread preparation or unmodeled native thread geometry.
The shared predicate is `manual_thread_setup` in
[`rules/_bench.py`](../src/prechips/rules/_bench.py).

### DRO grid consumption

For a digital readout (`dro.kind = "digital"`, or omitted), the machine's
`resolution` becomes coordinate-rule measurement debt only when an operation
authors or emits at least one coordinate rounded to, or printed on, that
machine's DRO grid. These requests consume the grid even when unknown geometry
or binding prevents computing their rows:

- An authored `to_z`, `z_from` or `z_to`.
- A requested feature location.
- A nonempty lathe drawing-station list.
- A contour requesting cutter-coordinate targets.
- An explicit `contour = "unknown"`.

An omitted or empty contour makes no target request. Empty outputs do not erase
an authored target's debt. A missing or untrusted consumed grid, including an
`assumed` grid, keeps the finding unknown with `dro_grid_debt` and the named
`machines.<id>.resolution` measurement instruction. Its declared step still
places provisional targets; otherwise `DRO_DEFAULT_STEP` does. A trusted
consumed grid retains the same rounding and geometric judgments.

The same target requests on `dro.kind = "handwheel"` or explicit `"unknown"`
retain readout debt instead of requesting a digital machine-resolution
measurement. Their finite internal grid is provisional nominal arithmetic,
not a measured dial increment or a calibrated physical target. See
[mechanical dials and unknown readouts](#mechanical-dials-and-unknown-readouts).

Machine selection, stock-state metadata and an unlocated feature name alone
consume no DRO coordinate. A bare `saw_cut` with no feature location, contour,
Z target or coordinate table therefore reports
`dro_grid = { step = "not used", decimals = "not used" }`. The setup sheet shows
"no coordinate targets". It has no coordinate-rule resolution debt or
fabricated numeric saw grid.

Stock dimensions, pictures, touch-off recipes and tip-endpoint displays retain
their own rounding and debt. The coordinate finding remains pass when no
independent geometry, frame or operation debt/error exists. "No coordinate
targets" clears none of those other checks.

### Frames and feature locations

A feature-local point is transformed to model coordinates as
`model = feature_frame.origin + sum(local[j]*feature_frame.basis[j])`.
A setup coordinate is `(model - setup.origin) dot setup.basis[axis]`.
Feature frames always come from the exported manifest. The setup frame is the
exported manifest frame of that name, otherwise the plan-owned
[`frames`](plan.md#frames) entry; a plan frame may not reuse an exported name.
A plan-owned setup frame adds `plan.frames.<name>: author-declared setup frame`
and its own citations to the finding, and its stated `binding` decides whether
the transform is nominal or unbound exactly as for an exported frame.
A frame whose `x`, `y` and `z` are all numeric must be orthonormal and
right-handed. Within `1e-9`, every pairwise dot product must be 1 for the same
axis and 0 for different axes, and each component of `x × y` must equal `z`.
Loading rejects a basis that fails either check. This applies to exported
manifest frames and plan-owned frames; the origin does not affect the basis
check. A plan-owned frame must also state `binding` explicitly and provide
nonempty `cite`, even when binding is unknown. See [plan frames](plan.md#frames).

Unknown components propagate only through nonzero coefficients. Loading checks
the basis only when it is fully known. In a frame with an unknown axis, each
numeric axis counts only if it is finite and, within `1e-9`, unit and orthogonal
to the frame's other numeric axes. Otherwise it is unknown, as is every
coordinate along it and every direction compared with it.

Tolerance-band midpoints never define nominal geometry: explicit `*_nominal`
values take precedence; otherwise only scalar dimensions are usable as nominal
geometry.

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

### Mill targets and aims

Off a lathe, a located row with a known setup point also carries `dro`. This
applies to an `at` or parent row and to each end of a kernel span. `dro` is the
point at the nearest step of the setup machine's DRO grid (`dro_grid`), at most
half a step away. Exactly half a step rounds away from zero, as fixture tables
and holding details do (`render_diagram.dro_steps`). The sheet's feature map
prints this target, and a hole op dials it (`dro_xy`).

#### Located-target band checks

When the feature declares a height-like band (`height_above_pivot`, `height` or
`separation`, the first one present) from a `height_from` reference, the row's
`band_check` measures where the feature stands from where that reference stands.
A feature this setup machines stands at its DRO target when a centre op (a
hole op or `center`) names it. A feature stands at its planned point when this
setup only inspects it or works without dialling it, or when machining occurs
through a child or in another setup. That point is its aimed model point,
unrounded, whatever its row prints. The distance runs along a reference plane's normal,
otherwise from the located reference along the common normal of both measuring
axes, square to the one axis, else point to point when neither has one. A
feature without its own `axis` that names a parent hole (`hole`, else `parent`)
or is drawn `coaxial_to` another takes that feature's axis, in that feature's
frame, whether or not it has its own `at`. An axis that is `"unknown"` (or whose
frame is), or that comes from an undeclared feature, leaves the distance
unmeasured; a kernel span's two ends must stand at one distance, else the band
names neither. The band is the one the sheet prints, rounded inward at its
drawing precision. A target outside it is an error
(`Located target band error: …`, value in mm).

The setup remains unknown when the distance cannot be measured, the band is
not two numbers, feature units are neither mm nor in, or the DRO grid is not
the machine's own trusted `resolution`. Every unknown or untrusted resolution
is named in measurement debt. An unknown resolution uses `DRO_DEFAULT_STEP`.
A declared resolution without its own `status = "measured"` record still
rounds the printed targets, never a finer fallback.

#### Aimed targets

A plan [`aims`](plan.md#aims) entry moves the feature's own target along that
same direction so its band reads `value_mm`, converted to manifest units, on
every setup that locates it. The row keeps the unaimed point as `nominal_setup`
and records the `aim`: owner `feature`, requirement, value in mm and manifest
units, reason, source, printed band, nominal value and shift in mm. The finding
cites `plan.aims.<name>`. The feature map gives the aimed target, drawing nominal
and reason.

A child located by its parent's `at` dials its parent's target, aimed or not,
and carries the parent's `aim`. An aim of the child's own would take it off
that axis. It is refused as unknown, with the reason in `refused_aim.why` and
in citations, and moves nothing. A target aim never changes geometry, a claim,
a kernel input or another feature's target. A faced aim (one naming a `face`)
moves no target here; the kernel cuts the part it makes
([plan aims](plan.md#aims)). A
`value_mm` outside its printed band is refused before any rounding: bad input on
load, an error in the rule, and the target stays nominal. An aim whose feature
no mill setup's centre op names (only inspected, faced or profiled, cut through a
child or drilled on a lathe, so no cut stands at the aimed target), whose feature
holds no such band, whose band or units are unknown, or whose distance cannot be
measured stays unknown with the reason in `aim.why` and the target stays nominal.

### Kernel revolved locations

The kernel request lists each setup's located features with neither `at` nor
a parent (`locate_revolved`). The engine measures their finished faces of
revolution about setup Z in every setup; a setup with a turning-model operation
measures every feature.

A feature is located on setup Z through X0 Y0 only when the kernel measured
every one of its faces as an external surface of revolution about setup Z
through x = y = 0 ([turned profile](rules-lathe.md), kernel `revolved` facts).
Rows place it at setup `[0, 0, z]` at both ends of its kernel axial span. The
model point is that setup point transformed back through the setup frame.
The finding cites `kernel: setups.<id>.revolved.<feature>`.

On a lathe, the rows are `spindle axis, kernel span start` / `end` and also
carry nominal diameter and X display. A lathe also tries this for a feature
whose own `at` is not numeric. Off a lathe, the rows are
`setup Z axis, kernel span start` / `end`.

The axis is never inferred from tolerance bands or model-frame assumptions.
The feature stays unknown if the kernel result is absent, setup frame binding
is unknown, facts are malformed or missing, or the kernel reports an internal
(bored) face or any face not revolved about setup Z through the origin
(off-axis, a flat, a cross boss or hole). Off a lathe, the unknown row carries
the kernel's `reason`.

### Lathe stations and nose compensation

Feature reference centres are distinct from hole tool-tip endpoints (those
belong to `blind_depth`). Lathe reference rows carry drawing stations, authored
operation endpoints and the finished feature's nominal diameter, expressed as
radius/diameter `x_target_mm`. That diameter is a geometry reference, not a
current-setup turning instruction: an operation's `to_dia` may describe an
earlier size or remain explicitly unknown. The sheet resolves those stages
separately; it does not change these reference records into stage commands.
An authored local Z can substitute for an unknown model transform only in an
unbound frame; the row retains `local_from = {op, field, axis}`. This does not
bind fitted shaft length to nominal model geometry. Dome axial samples compute
`radius=sqrt(sphere_radius^2-(z-sphere_centre_z)^2)` at authored steps and include
the exact endpoint.

The lathe feature map's cut-start and cut-stop columns describe this setup's
process window, not the finished feature's extent. A missing authored start
or stop remains unknown; a feature's `at`, a drawing station or a native
finished span does not fill the missing endpoint. An independently known
endpoint and nominal diameter can still print without inventing a
zero-length cut.

For a feature with an explicit `to_dia` on a profile/turning or boring operation,
the feature map names the operations owning each diameter stage. Consecutive
same-target operations can share a row; different targets keep separate rows
and their own cut windows in authored order. Explicitly unknown targets stay
unknown, even without reference rows or with a known finished diameter. An
omitted target in this staged branch also stays unknown rather than implying a
finish cut. Facing and part-off radial endpoints and manual threading do not
replace a surface's turning target. A feature with no authored diameter stage
retains its legacy reference-derived map.

A digital stage retains a located X, including its established aim, only when
its diameter matches that reference row. A changed or unlocated stage prints
its authored diameter as `nominal; X ?` and a STOP, not a newly invented DRO
setting. A handwheel map continues to convert nominal diameter/radius into the
declared readout units without implying a physical dial setting.

Each row then gets tool-nose compensation. The selected tool must not be
flagged uncertain, and its nose radius `rn` must be known and ≥ 0. The nose must
be what touches every row. Each row records `normal_deg`, the contact normal
measured from +X (radially outward) toward +Z.

For a right-hand tool feeding toward the chuck, the nose arc spans
`entering_angle_deg + insert_angle_deg − 180` to `entering_angle_deg`: the
trailing edge sets the lower bound and the major edge the upper. Both angles
must be accepted inventory facts. A normal outside that range is cut by an
edge or flank, so no nose offset exists there.

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

### Contour stages and joins

For contours, cutter radius is selected diameter/2. Stage offsets depend on the
operation and authored allowance:

| Operation | Tables and offsets |
| --- | --- |
| Explicitly rough | Rough at cutter radius + `rough_allowance_mm`; if that field is absent, use `stock_to_leave_mm` |
| Non-rough arc or linear contour with `rough_allowance_mm` | Rough at cutter radius + allowance; finish at cutter radius |
| Non-rough op without `rough_allowance_mm` | Finish only |

An unknown authored allowance leaves the rough path unresolved; it does not
mean zero. A negative leave (`rough_allowance_mm`, or a rough op's
`stock_to_leave_mm`) on any operation, contour or not, is an error
(`allowance_errors`). It would cut into the finished part. No stage of that op
is offset, printed or proven, and the setup sheet prints a STOP. The kernel,
travel, joint and speeds rules read it as unknown or an error, never as a
shifted band or cut.

Each profile, arc and exact line-join record names its `stage` (`rough` or
`finish`), so the report and setup sheet distinguish the paths even when they
share one operation number. Axial dome samples remain nominal profiles, not
an allowance/tool-nose-compensated rough path.

#### Arc bounds and linked joins

Arc contours use explicit centres, nominal radii and known finite geometry:
a boss is a full circle, a declared upper semicircle runs from 0 to 180°, and
finite rocker arcs derive endpoint angles.
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

### Manual arc methods

The mill is manual: one handwheel moves at a time. No printed move turns two
axes together, and there is no MDI, G-code or continuous circle. An arc uses one
of five `contour.method`s ([plan](plan.md#manual-arcs)). The former authoring
name `arc_table` is rejected with an error naming the supported methods. The
output record is still `arc_table` (joins use `line_table`), with its `method`.

- [`stairs`](#stairs): rough single-axis steps.
- [`chain_drill`](#chain_drill): rough holes and break-outs.
- [`chords`](#chords): straight finishing cuts, with indexing when needed.
- [`rotary_table`](#rotary_table): rotate the work about the arc centre.
- [`guided_sweep`](#guided_sweep): move the work on a pivot or rail guide.

The [trammel guide contract](#trammel-guided-sweep) covers its pin-and-rail
variant. [Shared arc limits](#shared-arc-limits) apply to all methods.

#### `stairs`

`stairs` is rough only, spaced by `cusp_mm`. Rows include every angle where the
arc is tangent to a setup axis, so each step between rows is monotone. Spacing
is as wide as possible while the stepped cutter leaves no more than `cusp_mm`
on the wall, measured on printed DRO values. Beside a concave arc's tangent
dip, the cusp is measured without the leg into the dip, which the merged move
stops short of.

When grid rounding leaves more material, rows are respaced closer by at least
enough to move a row. A stair still over `cusp_mm` is unknown. Between two rows
that differ on both axes, a corner row (no angle) turns one axis, then the
other: `(b.x, a.y)` or `(a.x, b.y)`. The rule chooses the one farther from the
walls whose two legs stay no nearer any wall than the cutter-centre offset,
or than the joined rows if nearer.

Consecutive legs on one axis form one move. Each move therefore turns the
other handwheel, with no reversal inside a move. A tangent row in the middle
of a move, such as a concave arc's lowest point that the move stops short of,
is not printed. Each row names the axis moved to reach it (`jog`). Straight
joins are split so their stairs keep the same cusp.

The record carries:

- `stair_cusp_mm`: the most material the swept legs leave along any wall
  normal, measured from the wall to the first leg that normal meets. A normal
  meeting no leg is unknown.
- `line_clear_mm`: the least gap from the stepped cutter's edge to the
  finished line.
- `stock_left_mm`: allowance + cusp.

If no corner stays outside the line, or `line_clear_mm` is below zero, the
stage is an error and its rows are withheld. The setup sheet prints cusp
rounded up onto the DRO grid. It says the stairs, or a chain's holes, stay
outside the scribed line only when an earlier `scribe` op on the feature
exists; otherwise it says outside the finished outline.

#### `chain_drill`

`chain_drill` is rough only. Holes are drilled with the op's drill, no more
than `pitch_mm` apart along the nominal rough path. Every hole's full diameter
must stay outside the line (`hole_clear_mm` ≥ 0), and neighbours must leave
a web: centres more than a drill diameter apart. Either failure is an error.

##### Scrap-side clearance

Host DRO selection, kernel regeneration and actual-hole validation use one
shared pure finite-boundary clearance predicate. For an actual closed finished
loop, including a joined bottom outline or full circle, its sign comes from
point-in-region and its magnitude from the nearest finite boundary. It is
negative in kept material. Unordered exact lines and arcs connect at their real
endpoints; authored scrap normals determine the kept side. Arc sweeps are not
tessellated or extended.

True open arcs and current top-plus-land wall packets lack a complete finished
loop in the packet, so no closure edge is invented. Linked taper and bottom-arc
facts can exist in the host model without being carried in that partial top
packet. See the [closed-boundary transport discussion
(#212)](https://github.com/pedropaulovc/prechips/issues/212).

The open fallback uses oriented finite projections and real free-end cap
distances. Shared concave vertices classify the actual nearest-vertex sector;
they do not treat a kept-side corner as a positive cap. Distance ties are
conservative, not a global AND of distant supporting half-planes. Missing,
ambiguous or unsupported region geometry is unknown, never an unsigned-distance
pass. With no admissible grid point, the stage is unknown and its cut tables
are withheld. Every actual cylinder still needs web, bounds and native
collision checks. The open fallback does not prove the whole finished part.

##### Break-outs and filing stock

Webs break out along hole centres (`break_out`). Every centre-to-centre segment
must stay outside kept material. For closed loops, the same predicate checks
entry against the whole finite boundary, not just the join's own line; an
entry into kept material is an error.

`stock_left_mm` is the maximum of:

- Allowance + drill radius.
- The radial depth left by actual printed arc centre-to-centre break-outs.
- The greatest distance from the retained printed join centre-to-centre
  break-out polyline to the nearest finite finished wall. This is nearest-wall
  distance, not one wall's normal, so a concave neighbour wall does not
  over-report corner runout.

Straight joins use the same drill-radius + allowance offset as the arc. Each
finite straight leg keeps its exact join endpoints/miter. Nominal holes divide
the leg into equal intervals no longer than `pitch_mm`; DRO snapping can move
the printed spacing off that bound.

Holes are repositioning checkpoints, not handwheel cutting moves. For an
unbounded chain, the kernel credits only actual drilled cylinders. Webs and
stock between cylinders and the claimed wall remain until a later known
removal. There is no drill-radius sweep between centres, cutter corridor or
+Z claim sweep. Retained webs beside a claimed wall are named stock debt
pointing at `stock_removal_bounds`. Declaring that box on the chain op is
the author's certification of the actual break-out/chisel footprint; it
does not demonstrate a toolpath.
See [in-process stock](rules-geometry.md#in-process-stock) and the
[explicit break-out phase discussion
(#213)](https://github.com/pedropaulovc/prechips/issues/213).

##### Printed chain tables and preconditions

Join tables print hole numbers, checkpoint P, X/Y and Z, drill size, pitch,
break-out instructions and reported stock/cap or `recut_by`. A single-hole
table prints no pitch or break-out sentence because it has no neighbour.
Each P label names the printed DRO X/Y point it stands on, matched within
1e-6 mm, never an index that clipping or respacing could shift. Arc and join
records share the worst residual of their rough stage.

Method, stage, full-hole-outside-the-line and requested no-web errors are
preconditions checked on authored tables before clipping. An authored
`pitch_mm` no greater than the drill diameter can leave no web at any spacing.
These stay errors even for holes a clip excludes; a single-hole or dropped-end
result cannot hide them.

The authored arc radial/full-hole invariant is an additional pre-clip check.
It is not imposed on regenerated endpoints: a physically safe finite-cap hole
beyond the actual sweep may lie inside the authored supporting circle.

##### Bounded chain regeneration

The kernel clips a bounded chain (`stock_removal_bounds`) at drill granularity.
It intersects the drill-centre offset arc and join lines with bounds eroded by
the full drill radius. A closed arc's fragments across its seam form one span.
Each retained arc or straight leg is regenerated separately with equal nominal
intervals along its true curve.

The hole count must give nominal spacing no longer than `pitch_mm` and leave
a web (centres more than a drill diameter apart). The web is judged on actual
snapped DRO centres, not nominal span alone:

- For a span longer than the length tolerance, the pitch-required count is
  always tried at snapped positions, even if it exceeds the nominal-length web
  bound. Any higher nominally feasible count is tried before shortening the span.
- A span within that tolerance keeps exactly one hole, whether it is an
  isolated point or a tiny arc or leg between shared junctions. No duplicate
  row is emitted at the same centre.
- Exact junctions remain shared.
- If no such count leaves positive web at snapped positions, the clipped end
  hole is omitted and reported as a dropped end, never a fabricated no-web error.

Every actual hole snaps onto the grid inside the bound and passes the shared
predicate: its centre must be in scrap with clearance for the whole drill and
allowance. Closed loops use region membership even beyond an individual wall's
projection. Genuine open packets use the finite-projection/free-end and
concave-shared-vertex fallback. Bounds never waive this test.

Nominal-distance/offset guards are additional placement constraints, not
independent unsigned side acceptance. Every hole searches the symmetric square
within three grid steps on each axis and chooses the nearest safe point by
Euclidean distance, with a deterministic coordinate tie-break. A diagonal is
not rejected just because it lies outside a one-step circle.

Ends and junctions may back off inward along the true curve. A clipped end is
therefore not promised within one step of the true bound crossing. If a hole
has no grid candidate after the full search and back-off, the whole clip is
unknown; it never admits a hole in finished material. Every actual hole
cylinder is judged. Printed spacing is DRO spacing and can differ from the
nominal interval. A raw swept-chord intersection never becomes an extra hole.

Web/break-out checks and the single T6 `numbers.max_filing_stock_mm` cap
enforcement use the actual regenerated residual. Unsigned nearest-wall
distances remain stock/residual measurements, not scrap-side proof. Tables
name only genuine dropped ends and piece breaks where stock beyond is neither
cleared nor part of the chiselled chain. An intact arc/join junction continues
into the adjacent table.

Omitted joins add no join debt while an arc or other table remains. A stage
excluded entirely by the clip, or retained pieces that no longer connect,
keeps clip debt. When a chain error withholds cut tables, profile facts still
report `stock_left_mm` and `stock_cap_mm` wherever the residual was computed.
A precondition error may prevent that computation. Those values aid diagnosis;
they do not give permission to cut.

#### `chords`

`chords` finishes with `count` straight chords. Chord ends sit on the edge
radius that centres each chord's sagitta `c²/8R` in the feature's radial band:
`dia` halved for a full circle, otherwise `bottom_radius` or `radius`.

These conditions are errors:

- Sagitta wider than the band.
- A full circle cut in fewer than three chords.
- Two neighbouring chords that run parallel.
- A slanted chord with no rotary table.

Each chord feeds along one table axis. If it is square to X or Y, it cuts as
it lies. Otherwise the work is indexed square to X on the setup's rotary
table (`index_deg`, rounded to dial resolution). Each `cut` locks one axis
`at` a grid value on the scrap side and feeds the other through `from`/`to`
grid values. The rule rebuilds each chord face from those printed cuts.
Its nearest and farthest points (`face_radius_mm`) must stay inside the band,
or the result is an error. A rotary table flagged to verify is unknown.

#### `rotary_table`

`rotary_table` finishes with rows every `step_deg`. The setup holds the work on
an inventory `rotary_table` fixture (`hold.fixture`), with the arc centre on
the table axis at setup X0 Y0. It locates `contour.centre_feature` by a pin
through it (`centre_by = "pin"`) or by indicating it (`"indicate"`). That feature
must be a hole on the axis made by an earlier drill, ream or bore.

A pin is the hole's smallest diameter. It must enter the table's centre bore
(`bore_dia`, else unknown), or the result is an error. The spindle locks at
X = cutter-centre radius on the DRO grid in plan units, off the line, Y0
(`offset_axis`, `offset_x`; `offset_mm` is the same in mm).

The printed offset's cut radius (`cut_radius_mm`) must lie inside the radial
band, however the centre is found. A rough stage moves the band off the line
by its allowance. For a pin, the cut radius is widened by centre play
(`centre_play_mm`): half each bore's clearance over the pin. A cut outside the
band is an error; an unknown band is unknown.

The table turns the work against the cutter from `start_deg` to `stop_deg`.
Both dial readings round inward along the turn to vernier resolution, else
graduation resolution. An arc too short to keep a reading inside it is an
error. Consecutive rows must be less than half a turn apart. `step_deg` under
180° ensures this; a wider step on an arc shorter than half a turn leaves only
the two ends. Wider rows read as the short way round, so cutting order and
table turn no longer follow the cut's sense: an error.

Setup-entry stock (kernel `stock_bbox_mm`) must swing inside `max_work`.
Off-axis centres, no table, no earlier centre hole or swing over `max_work`
are errors. Unknown dial, centre or swing facts, a table flagged to verify,
or an untrusted `max_work`/`bore_dia` record are unknown. Each untrusted fact
is named in `numbers.measurements`.

#### `guided_sweep`

`guided_sweep` finishes with rows every `step_deg` over the whole sweep. Its
[implementation](../src/prechips/rules/guided_sweep.py) supports these guides
on the setup's `hold.fixture`, named by `contour.sweep.fixture`:

- `pivot`: a `kind = "swing_arm"` fixture.
- `rail`: a `kind = "arc_sled"` fixture, with two rollers at `rollers_deg`
  and rail ends at `rail_deg`.
- `trammel`: a `kind = "trammel"` pin carrier on two straight rails. Its
  [separate recipe](#trammel-guided-sweep) has no master touch-off.

Each guide holds the work to rotation about the arc centre. For pivot and rail
guides, the stationary
cutter touches `contour.sweep.master`, a `setting_bar` on the pivot pin or
`master_arc` on the fixture. It feeds along `touch_axis` from the scrap side
(`touch_feed`). X and Y lock (`locked_axes`; `moves = "fixture"`). The cutter's
own size never enters the cut radius.

##### Cut-radius error budget

The worst-case cut (`cut_radius_mm`) starts with the master's measured
`radius_limits` (`master_radius_mm`). A rough stage moves it off the line by
`back_off_mm`, the allowance rounded off the line onto the DRO grid.
`back_off_dro` is the signed move on the touch axis from the DRO reading the
operator writes down at the touch. The setup's DRO zero is never reset.

The cut is widened by `centre_error_mm`:

- For a swing arm, use measured `pivot_play`. Double it for a master arc on
  the arm, which also moves with the beam at touch-off.
- For a rail, use `2 × roller_gain × (rail_form_error + roller_runout / 2)`,
  where `roller_gain = (|sin a| + |sin b|) / |sin(a − b)|` for rollers at `a`,
  `b` degrees from the cutter's radial line. Each contact errs at touch-off and
  again at the cut; roller geometry translates both errors to the sled centre.

Both are finite bounds, not linear terms alone. Each centre shift `d` adds
`d² / (2 (ρ − d))` where a radius `ρ` turns it. The relevant radii are:

- `worst_reach_mm`, the shortest cutter reach: master radius limits at touch
  less a rough's back-off toward the centre, never the nominal path.
- For a rail, `roller_orbit_mm`, the roller centres' least orbit. It is the
  rail radius for outside rollers (`rail_side = "outer"`), or rail radius less
  half the measured `roller_dia` for inside rollers. An undeclared side, an
  unmeasured inside roller or one as wide as the rail diameter is unknown.

The rule solves a fixed point (`rail_cut_shift` in the guided-sweep
implementation). A solution that does not converge inside half of either
radius leaves the cut unknown.

Every geometric proof carries `margin_mm`, one machine DRO display step.
It widens the cut and start clearance and places both stops past the arc ends.
A bound term provably smaller than the margin is absorbed:

- A setting bar touched up to one step beside its line moves the cut by at
  most `hypot(reach, step) − reach`.
- A touch axis leaning within its one-step tolerance shortens back-off `b` by
  `b (1 − cos)`.

Both terms stay under one step for cutter-centre reach of at least two steps
([margin analysis #272](https://github.com/pedropaulovc/prechips/issues/272)).
An unmeasured DRO resolution or reach under two steps leaves the margin
unproven as debt.

The worst-case cut must lie inside `band_mm`, moved off the line by allowance
for a rough stage, or the result is an error.

##### Sweep span, rows and stops

`sweep_deg`, centred on the arc, must reach both arc ends (`span_deg`, the
cutter-centre span) to within one DRO step of cutter travel and stay under a
full turn. Failure is an error. A full circle is also an error: it starts and
ends at one fixture pose, so two stop blocks cannot bound it. Use
`rotary_table` for that case.

`step_deg` must be under 180°. At half a turn or more, the chord between rows
reads as the short way round; neither cutting order nor fixture turn can be
established, so the result is an error.

Rows run `overrun_mm` past each end (`path_mm` of cutter travel along the work).
The arc's own ends remain rows, and the kernel judges every row
([geometry rules](rules-geometry.md)). Rows stay on the nominal cutter-centre
arc for the kernel check against the nominal part. The band check separately
judges where the master sets the real cut. Moving rows to the master's radius
would make an in-band master past nominal appear to hit the part.

`rotation`, viewed from above, turns the work against cutter travel along rows
in cutting order. `ends_setup_xy` gives the arc ends on the work in setup XY,
start end first, as reference geometry.

Stops use the arc-end marks from an earlier same-setup `scribe` op with
`layout = "ends"`. `marks` records that op and mark A or B for each stop,
start first. Missing layout, unplaceable marks or an intervening op that may
cut leaves the recipe unknown. An earlier sweep cuts through the arc ends;
rough and finish therefore stay in one op, with stops set once.

##### Touch-axis and rail coverage

The setup frame describes the work at the sweep's middle pose. `touch_axis`
must follow the radial line from arc centre to arc middle
(`arc_mid_setup_xy`) within one DRO step of cutter travel
(`touch_axis_off_deg`). Otherwise the touch or back-off is not radial: an error.

For a rail, `roller_contacts_mm` gives each contact as setup X/Y offsets from
the spindle axis at touch. Both rollers must bear on the rail throughout the
travel the printed stops set. `stop_travel_deg` includes the arc span plus,
at each end, printed overrun and `stop_slop_mm` on the shortest touch reach.
This covers the whole span even when a sweep falls short within its tolerance.

Each roller must lie within `rail_deg` narrowed at both ends by half that
travel and by `roller_slack_deg`. Placement slack includes the contact's
printed 0.1 mm X/Y rounding and the sled's shift through the rollers, over
rail radius. The rail is the shorter arc between its ends, including across
the ±180° line. Ends half a turn apart leave its side unknown.

Rollers on one line through the centre, or rollers that fail coverage, are
errors. The setup sheet prints the sweep only when `rail_coverage` is `proven`.

##### Fixture compatibility and radial placement

These are errors:

- The guide fixture is not the held fixture or has the wrong guide kind.
- The master is neither a setting bar nor master arc.
- A rail uses a setting bar.
- The machine is not a `mill`; an unknown kind is unknown. The sweep depends
  on locking a mill table's X and Y.
- Another spindle op shares the setup, before or after the sweep. The guide
  turns work off its setup frame and nothing holds it at that pose for the
  other op. Manual ops are exempt.

The cutter must be on the radial line before touch so a rough's one-axis
back-off is radial (`transverse`): `bar_centred` centres a setting bar between
its sides; `rollers_set` sets rail rollers from the locked spindle.

A rough cut is widened by the missed radial move (`transverse_residual_mm`).
It uses the worse cutter-centre reach from master radius limits at touch,
never the nominal path. The cutter axis may stand beside the line by
`transverse_offset_mm`: one DRO step + pivot play for a bar; for a rail, the
sled's sideways shift is `(|cos a| + |cos b|) / |sin(a
− b)|` times each contact error.

That rail bound is finite, as is the cut's own bound. Each contact error
includes the diagonal of two half-steps from printing X and Y to 0.1 mm, rail
form error and half roller runout. Nearby roller angles amplify it. A
nonconverging bound is unknown.

A master arc on a swing arm supplies no radial line, so even a finish stays
unknown and prints only a STOP. A feeler-touch extension is discussed in
[#288](https://github.com/pedropaulovc/prechips/issues/288); it is not part of
this recipe.

##### Measurements, entry and recipe release

An unknown guide, fixture, master, axis, sweep, rollers or rail ends leaves
the recipe unknown. A fixture or master flagged to verify as a whole also
does so, including its source provenance and a selected set member's own
flags. A flag on an unread fact, such as a picture-only dimension, does not.

`pivot_play`, `rail_form_error`, `roller_runout` and `radius_limits` each need
their own complete `measured` record. `rail_radius` is read as declared.
Each untrusted fact is named in `numbers.measurements` with a `measure:`
instruction. An undeclared form error never means a perfect rail.

At every level the cutter goes down at the first row, the start stop. `start`
is `air` only if the whole cutter is outside the received stock box
(`level_entry.in_air`) at the first stop's pose. `start_xy` uses printed
`stop_overrun_mm`, rounded down to 0.1 mm, measured on the touch path where
all stage stops are set before rough back-off.

The entry bound widens the cutter for:

- The greatest difference between the master-set `cut_radius_mm` and nominal
  wall assumed by the rows.
- The arc through which that radius range turns measured overrun, which is
  measured along the real path.
- Mark placement rounding, the diagonal of up to half a step in both X and Y.
- Stop shift from half the stroke angle's 0.1° printed step, across cutter
  radius plus the preceding spread.
- The DRO-step margin.

This is `start_reach_mm`. Otherwise start is `unproven` and unknown, because
no plunge is checked for a sweep.

The setup sheet releases the recipe only with known `band_mm`, a proven cut
and a start in air. Any unproven cut is debt, including pivot play or rail
error too large to bound. Every error and debt is retained in `open_debts`.
The recipe prints only when that list is known empty, even if no individual
printed value shows the remaining debt.

##### Trammel guided sweep

A `guided_sweep` on a `trammel` guide records `guide = "trammel"`,
`feed = "lever"` and `locked_axes` X, Y and Z. The `coordinates` rule
evaluates this recipe through `guided_sweep`; its errors and measurement
debt belong to the setup's `coordinates` finding. The related X/Y zero
exemptions are part of [`zero_check`](#zero_check).

For input fields, see [oblique trammel](plan.md#oblique-trammel). See also the
[trammel implementation](../src/prechips/rules/trammel.py) and
[design discussion (#269)](https://github.com/pedropaulovc/prechips/issues/269).

As for every guided sweep, rows stay on the nominal cutter-centre arc.
`exact_arc` hands that circle to the kernel. Each row's `dro_xy` is exact
XY because the DRO sets nothing. The pins put the real cutter centre on
`pin_radius_mm = D / (2 sin α)`, which is judged against the band.

The exact carrier pose on the pin circle turns `−ψ/2` while the cutter
runs `ψ`. It gives `carrier_turn_deg`, `rails_dir`, each pin's `stations_mm`
at start and end in cutting order, exact `station_ranges_mm` and `swept_mm`.
The last is the exact table-frame footprint of the pins and kernel stock
box about the spindle axis.

###### Trammel radius and pin-line error budget

`error_terms_mm` records:

- `radius_below` and `radius_above`: pin radius at the measured rail-angle
  and spacing error corners, exact because `R` is monotone in both.
  `radius_per_deg_mm` and `radius_per_spacing` are first-order reference slopes.
- `pin_lines`: `line_gain × (pin_clearance + rail_offset)`, where `line_gain`
  is the worst `|g₁| + |g₂|`, exact over sweep poses and also taken over
  crossing-angle measured error at its ends and 64 angles each way.
- `pin_lines_second`: offset-line crossing also slides along the cutter path
  by up to `tangent_gain × offset`. It lengthens radius by at most
  `x_t² / (2 (R − x_r))`, added above.

`centre_error_mm` is the larger side. `cut_radius_mm` is the wall one cutter
radius off the pin circle, widened below and above by each side's sum.
It must lie inside `band_mm`.

###### Trammel errors and measurement debt

These conditions are errors:

- A master or touch axis, a rough stage or a positive allowance on any stage.
- A rail angle outside the strict range `0° < α < 90°`.
- Nonpositive pin spacing, pins not subtending `α`, or a pin inside the swept
  window.
- Tolerances leaving no acute crossing.
- Rail 1's controlling station turning back within the sweep, where its pin
  circle's diameter is reached inside it. A stop would then hold two poses.
- A carriage that may leave fixture `rail_travel` at measured tolerances
  (`station_envelope_mm`).
- A mis-set stop that could hold the carrier short of an arc end (`stops`).
- Another spindle op sharing the setup, or a machine that is not a mill.

`start` must prove clearance from stock at every pose the first stop can hold,
using the true arc's X/Y extremes exactly over that band. An unproven start
or any unmeasured fixture fact is unknown, with a `measure:` entry for each fact.

A trammel without commissioning is also unknown
([commissioning discussion
#270](https://github.com/pedropaulovc/prechips/issues/270)). It needs a known
`make_document` id, revision and cite identifying the drawing used for building
and commissioning outside the setup sheet, a known `commissioning_record`
and measured `dowel_reading` for the rails' alignment used by this op.
A negative reading is an error.

Each geometric proof carries one DRO step of `margin_mm`, as for every
guided sweep ([margin change
#258](https://github.com/pedropaulovc/prechips/pull/258)). It widens the cut
below and above, stop-setting error and start clearance. An unmeasured DRO
resolution leaves the margin unproven as debt. Any recorded error or
`open_debts` entry stops the card even when no printed value shows it.

###### Stop poses and rail travel

Stop, start and rail-travel proofs use measured fixture tolerances, not
nominal geometry alone. The exact two pin-on-line constraints solve carrier
pose for every corner of rail-angle and pin-spacing error and each pin-line
off by pin clearance + rail offset either way. Each stop uses its printed
0.1 mm station, with half a millimetre of rule error + one DRO step + pin play
along its rail (`pin_clearance`) either way.

The results are `stop_bands_deg` (cutter angle about arc centre at each stop),
`stop_radial_mm` (distance off the nominal path there) and
`stop_stations_mm` (each pin's station).

###### Trammel operator sequence

The trammel card relates each printed setting to a physical reference and
the error bound used for its cut
([card design discussion
#289](https://github.com/pedropaulovc/prechips/issues/289)). Every printed value
must satisfy `sheet_sweep.TRAMMEL_PRINTED`; an unproven one prints only a STOP.

| Step | Printed | Measured from / set by | Its error reaches the cut as | Bounded by |
|---|---|---|---|---|
| 0. Rails aligned (once per install, [#270](https://github.com/pedropaulovc/prechips/issues/270)) | rail angle `α` (information); the make document's id and revision it is built and commissioned to; where the install record is kept (`commissioning_record`) and its dowel reading against the predicted stations, as the card's pointer; a STOP to recommission if the rails moved | the commissioning readings that put both pin-lines through the spindle axis | the rails' crossing angle: radius `R(D, α)`; a pin-line off the spindle axis: about 1:1 | the measured `rail_angle_error` at its corners; `rail_offset` through `line_gain` |
| 1. Seat the pin pair | pair name, spacing `D` (information) | the carrier's drilled pin holes | spacing: radius `R(D, α)`; a pin's play in its carriage: about 1:1 | `pin_spacing_error` at its corners; `pin_clearance` through `line_gain` |
| 2. Lock X and Y on the rails' crossing | none (no X/Y pickup, no DRO sign) | the spindle left where step 0 aligned the rails | moving X/Y offsets both pin-lines: radial about 1:1 | the card forbids moving them; the zero owes no X/Y |
| 3. Clamp the stops on rail 1 | each end's pin station, 0.1 mm, from the spindle axis and along the rail from the carriage's near end stop (`rail_travel` near limit) | a steel rule from that end-stop position | a stop off by up to 0.55 mm holds the carrier at another pose (`stop_bands_deg`, the exact inverse of the station); it never moves the radius | an error unless the worst stop, on the fixture at its tolerances, still holds past its arc end; debt unless the cutter goes down in air at every pose the first stop can hold |
| 4. Check rail 2's stations | the other pin's stations at both stops | the same rule on rail 2 | a mismatch means the rails or pins are not as set | the card says STOP on a mismatch |
| 5. Dry pass | none | No setting reference | clamps or holder in the path | `headroom` owes this check at every pose |
| 6. Start the spindle, set and lock Z | spindle direction; Z at DRO resolution (each level when stepped) | the setup's Z zero | one DRO step of Z moves the depth only, never the radius | the tip rules; not the trammel's |
| 7. Lever stop to stop | the cutter's sweep angle about the arc centre and its travel along the work; the carrier's own turn in all and each side of the sweep's middle; pace (information) | the stops | the carrier must keep both pins seated: a pin lifting out of its carriage is outside every bound | the card's instruction |

For the software fixtures in
[`tests/test_trammel.py`](../tests/test_trammel.py), `cut_radius_mm` must
enclose every wall found by the independent perturbed-fixture model:
rail angle and spacing at either tolerance limit, each pin-line off by
clearance + offset either way, and both stops 0.55 mm off either way.
The tests assert that enclosure, including the exact second-order term for
large pin-line offsets. The radius terms bound `R` itself, while work sits
on the pins and its wall moves much less than `R`, so the bound is
conservative. This is a software-fixture bound, not physical commissioning
or machining acceptance.

#### Shared arc limits

Every manual-arc table is cut in the plan's feature units (`mm` or `in`, else
unknown) and records its millimetre facts (`*_mm`) in millimetres: the cutter,
drill, cusp, band and stock values are converted, never mixed.

A rough stage's `stock_left_mm` that reaches `file_to_line`
([implementation](../src/prechips/rules/manual_arc.py)) must not exceed
policy `numbers.max_filing_stock_mm` (`stock_cap_mm`), or the result is an
error. The cap is unknown, never zero or a pass, if absent, negative, uncited
or not marked `numbers_verify.max_filing_stock_mm = false`.

If a later `stairs`/`chain_drill`/`chords`/`rotary_table`/`guided_sweep` op
recuts the claimed faces before filing, the rough leaves stock to the last
such op (`recut_by`) instead of the cap. That last op hands the faces to the
file. The claim test does not compare depth: an intervening op may cut the
same faces from the other side.

Unresolved registered recut ownership remains `arc_debts` and `unknown`,
never a pass or a known `recut_by` producer. Arc, join and profile metadata
retain `stock_cap_mm` and the measured residual; an over-cap comparison is
conditional debt until ownership establishes whether that stock reaches
the file. Known gouges and break-out crossings remain errors regardless
of recut uncertainty.

Rough methods on a finish stage are errors; `file_to_line` finishes them.
Finish methods cannot be clipped by `stock_removal_bounds` and stay unknown
when bounded. Straight joins support only `stairs` and `chain_drill`; other
methods stay unknown. A diagonal edge on a `linear_table` outline is unknown
because single-axis outline stairs are not computed. Rasters and outlines
with only axis-parallel edges need no manual-arc method.

### Linear paths and rasters

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

For a profile with explicit `contour.sweep_bounds` and no broad
`stock_removal_bounds`, these complete printed `linear_table` paths also
govern native stock removal. No nominal wall corridor fills the gaps between
separate finished members, and the checker does not credit an unprinted pass.
The whole sweep must preserve finished material and the leave normal to its
claimed planar faces; see [explicit guided profiles](rules-geometry.md#explicit-guided-profiles).

An explicitly authored `sweep_bounds` must resolve; an unknown or malformed
guide never falls back to a nominal feature box. Canonical checkpoints give
linear profiles their own `linear_table` kind and `linear path N final depth
point i` row identities, not straight-join `line_table` identities. They use
the actual printed profile `dro_to_z` in both cold and warm requests, with
`material_scope = "final_depth"`, just as arc/join tables model material at
their printed final tip. The native arriving stock supplies the upper sweep
extent. Complete closed outlines and independent raster passes stay intact;
rapid returns and lift moves are not substituted for cutting paths.

This material model does not establish an unknown start height or axial pass
schedule. Those remain separate coordinate/tool-path debts. Multiple axial
levels do not duplicate the final-depth checkpoint identities or the drawn
outline, and an unresolved final tip or any unresolved cutting path keeps
the complete native checkpoint request unknown.

#### Safe-side raster and outline rounding

Every raster value sits on the DRO grid on the safe side:

- Pass ends and a face's edge passes round outward.
- A pocket's first pass rounds farther outside its open side; its last rounds
  away from the far wall. The material left on that wall is
  `grid_residual_mm`.
- Intermediate passes step a whole number of grid steps no larger than
  `step_mm`. A `step_mm` finer than one grid step is unknown.

The raster record carries `run_axis`, `area_ends`, pass `ends`,
`clearance_mm` (the cutter radius run past the area) and a pocket's
`entry_pass`. The setup sheet prints pass ends and directs a lift to raster
lift Z after every pass.

An end, or the open-side entry pass, is described as in air only when the
finite circular cutter clears setup-entry kernel `stock_bbox_mm` by the
positive stock tolerance. This includes diagonal clearance beyond a box
corner; mere boundary tangency is not positive air clearance. That box
holds every op's stock. The note identifies the end by its role in printed
feed direction, such as "each pass enters from air at -X" or "leaves into air
at +X". `stock_removal_bounds` states what the op may remove, not where stock
ends. It proves neither air nor material; an unproven end carries no claim.

A `keep_out` splits passes into pieces that also start and stop between the
outer `ends`. The table numbers every piece as a pass. Its note names only
the outer ends by feed role, such as "the outer -X end, where the feed
enters, is in air", and says pieces start and stop between them. It says
every pass runs in and out clear only if every emitted piece's start and
end is proven so, stage by stage.

A closed outline's vertices are also on the grid. Each is the nearest grid
point at least its offset outside both joined wall lines: a grid-cell corner,
else up to two steps out. `grid_residual_mm` is the greatest extra distance
any vertex stands off a wall. The sheet names an outline row as cutter
clearance only when the cutter stands wholly outside entry stock.

A finish raster or outline is an error (`dro_xy_residual_errors`) if its
`grid_residual_mm` exceeds the feature's narrowest numeric tolerance band,
or if no safe grid point exists.

#### Circular keep-outs

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

#### Table limits and unresolved inputs

Face ops without a contour print no raster: a box raster could cross retained
material inside the box. Tables describe numeric nominal geometry. They do
not establish cutter accessibility, fixture clearance, wall thickness or
collision freedom. Raster passes are not kernel checkpoints.

An unknown or unverified cutter or frame binding keeps status unknown. A
lathe setup with an unknown DRO controller, or a turning tool with an unknown
nose radius, is unknown. A tailstock tool on the spindle axis (`spot`,
`drill`, `ream`, `tap`, `center`, `center_drill`) has no nose to compensate
and is exempt.

Nominal stations and dome tables do not establish complete lathe feasibility.
The implemented [`turned_profile`, `stickout` and `stock_diameter`
checks](rules-lathe.md) and
[`turning_deflection` proxy](rules-physics.md#turning_deflection) cover
specific conditions. They do not prove a complete toolpath, clearance,
absence of whip or freedom from chatter.

### Z levels

A milling pocket, face or profile op that authors `doc_mm` (mm) carries
`z_levels` on its `operations` entry: levels on the DRO grid, each no
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

### Hole targets

Each located mill row (`rows`) carries `dro_xy`, its setup
X/Y at the nearest DRO grid point (a hole axis has no safe side; half a step
rounds away from zero, as `dro` does). A centre,
spot, drill, ream, tap, counterbore or bore op whose feature has exactly one
located row prints that tool-axis X/Y on its op row; an unknown one prints a STOP.

### Cutting order

Arc rows, each join fragment and a closed `linear_table`
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

### Bounds clipping

`stock_removal_bounds` is a material footprint: an op may
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

### Printed values and surface provenance

The operator cuts what the DRO shows. Every axis uses the setup machine's
declared inventory `resolution` (`resolution_mm` or `resolution_in`), a
positive length. Loading refuses 0 or less. Without one, the grid is 0.001
plan units (`DRO_DEFAULT_STEP`), printed at one step's decimals (`dro_grid`). A
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

#### Selecting the producing operation

One provenance source (`tip_endpoints.operative_z`) picks the op that produced
that face. It looks first among the setup's own ops scheduled before the reading.
For a Z zero's `top`, those are the ops up to and including its `after_op`,
never a later recut. It then walks the selected stock ancestry: the setup's
`stock_in` chain, the same one the kernel builds, joint branches included, and
same-frame setups only. A setup outside that chain never counts, even if it cut
the same nominal face.

The producer is the op that advanced a stock-state top or entry, or last cut
the face proven to be read:

- For `top`, a facing op on `top_feature`.
- For a feature (zero face, an op's feature for start/end Z, or a feature-map
  row), either:
  - An op on that feature that leaves a face at `to_z` (`forms_face`), or
  - A facing or pocketing op whose feature's X/Y `bounds` hold the whole
    footprint: its own `bounds`, else a Z-axis round feature's `at` ± half its
    largest `dia`. Overlap is not cover.

Facing and pocketing leave the feature's face at `to_z`. A lathe turning op
does too when the kernel poses it on its numeric `to_z` plane (`faced_side`):
all claimed faces face one way along Z, as a face, part-off, cut-to-fit,
groove wall or turned shoulder does.

An op is known to leave no Z face only in these cases:

- A manual or transfer step cuts nothing.
- A nonspindle saw locates its face by `cut_plane`, never a DRO Z.
  A mounted slitting saw uses its proved cutting-midplane Z setting.
- Off the turning approach, only facing or pocketing leaves a Z face.
  A hole's `to_z` is its tip; a milled wall's is its foot.
- A turning op sampled by the kernel at numeric `to_z`, or over its
  `z_from` to `z_to` window, claims only cylinders and leaves a diameter alone.

Other ops on the face are producers at unknown Z, never raw stock:

- Unknown action.
- Facing, pocketing, part-off or cut-to-fit without `to_z`.
- Turning with unknown `to_z`; no number means no posed plane, so samples
  prove no face absent.
- Turning not sampled by the kernel.
- Turning whose sampled claims lie on no one side and are not all cylinders,
  because they face both ways or their kind is unknown.
- A turning window op without `to_z` claiming a non-cylinder. The kernel
  cuts a shoulder or groove wall to its window end but poses it on no Z plane.
- A lathe action off a lathe.

Equal Z alone is never proof. Without a footprint to prove coverage, there
is no producer.

#### Whole, partial and unknown surface coverage

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
(`credited_faces`; see [touched faces](#touched-faces-and-same-setup-rounding)).
Authored `bounds` that are unknown,
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

#### Keep-outs and unbounded coverage

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

#### Producer-grid values

A known producer counts only if it cut that face to that Z. Its
value is its `dro_to_z` on its own setup's grid (for a grooving/parting blade, the
`formed_z` its rounded corner reading leaves), re-rounded to the safe side on
the consumer's grid, so a coarser producer's −2.270 stays −2.270. That value is
unknown, never the nominal `to_z`, when the blade's reading corner, kernel side
or width is unknown, when whether the op leaves a face at `to_z` is unknown, or
when the Z touch the producer cut on has an unknown edge
or paper stand-off or meets a face standing at an unknown Z (`reads_unknown`);
the surface then prints `?`. A touch on a produced face standing off the
consumer's grid is refused under `zero_check`
([touched faces](#touched-faces-and-same-setup-rounding)).

#### Carrying printed Z between setups

A setup receiving the part from one earlier setup, named by `stock_in`
(`tip_endpoints.transfer`), carries received surfaces so both sheets agree
on their printed grid. Transfer frames put every surface at
`Z = ±Z_before + offset`, with `−` when the part turns over. Zs along
another axis, a joint or a supply carry nothing.

Each received `stock_state` Z (`top_z`, `bottom_z`, end Zs,
`retained_rail_bottom_z`) that links to a previously printed surface uses
`±` that printed Z plus one shift. The earlier value is its producer's
printed Z, else its own arrival print.

The shift is the least value at or above the offset that lands all those Zs
on this grid. If they already land on it, the offset rounds once, upward.
If that would put an untouched top below its stated Z, the shift rises to
the least grid-compatible value at or above it. This applies when there is
no `top` zero, or the zero is after an op: a tool clearing the printed top
must clear stock. A top touched by the Z zero carries even below its stated
Z, because that touch sets the DRO to read the carried number there.

If earlier printed Zs are not whole steps of this grid apart, as with a finer
DRO before a coarser one, no single shift can land them all. Rounding each
alone would move them apart. That transfer carries none; each Z prints on
the grid separately, and "Starts from" says no one shift carries them.

Otherwise, when the shift differs from the exact offset or a carried Z
differs from its separately rounded stated Z, the sheet prints every carried
Z and names the one transform everywhere it holds. For example,
`top and rail bottoms Z = −7.080 − its Setup S1 Z` prints a flip's shift first,
so the minus cannot read as covering the shift.

With no producer, `operative_z` reads a carried Z only for the received
surface itself: `top` or `top_feature` at `top_z`, or `bottom_feature` at
`bottom_z`. The top covers the Z-zero surface, a level start on top, raster
lift and a path's raise above it. Equal Z on another face is no proof.
Other surface Zs print on the grid by `dro_z`.

#### Hole depth and final-face rounding guards

Hole endpoints carry `dro_entry_z`, `dro_exit_face` and `dro_tip_z`.
The tip is worked from the printed entry, or exit face for a through hole,
then rounded up again, leaving `dro_depth_mm` or `dro_exit_mm`. A through
tip short of its exit face prints a STOP.

The breakthrough note reports the lower of `dro_exit_mm` and the same
run-out past `dro_exit_face`, cut down to DRO decimals. It claims no
run-out when unknown or negative. The op row prints the tip and exit face;
the note repeats neither.

Every rounded-depth row carries `depth_floor_mm`, the feature `depth` band's
lower end, or for a tap its `thread_depth` band, else `depth` band. Other
rows, and a bare `depth` that is only an upper limit, have an unknown floor.
`dro_depth_mm` below the floor prints a STOP. So does a depth changed by
rounding when its floor is unknown.

A final forming cut whose `to_z` ends on its finished face (no `exit_mm`)
is an error (`dro_z_residual_errors`) if `dro_to_z` leaves more skin than
the narrowest numeric tolerance band. This is the rounded-up depth, or a
blade's `formed_z`.

Every join record carries `stage`, `allowance_mm` (rough leave, 0 for finish)
and `offset_mm` (cutter radius + allowance). The sheet prints these values;
the kernel clips, checks and credits them. Nothing between sheet and stock
model is rounded twice.

### Row IDs and native checks

Each printed row has an id:
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

#### Coordinate finding messages

The base message is:

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

### Depth entry and return (`level_paths`)

For every mill setup, an op with a printed cutter path gets one `level_paths`
record. Paths include stair/chord arc tables, join tables, outlines and raster
passes. Rotary-table and chain-drill tables are not end-mill paths.

| Field | Meaning |
| --- | --- |
| `op` | Operation number |
| `levels` | DRO Z at each depth, top first; one level for a single-depth op. It is `unknown` if coordinates could not compute levels or depth, never a fabricated single level at the op's depth. |
| `from_z` | Level 1's start Z |
| `entries` | Places the cutter goes down, in printed path order: `xy`, positive-clearance `air`, and `pass` for a raster pass; exact boundary contact also carries `contact = "tangent"` |
| `raster` | Whether the path is a raster |
| `closed` | Whether one piece ends where it starts |

An entry is in `air` only when the finite circular cutter clears the actual
setup-entry `stock_bbox_mm` by the kernel's 1e-3 mm positive margin. The distance
is to the nearest point of the box in XY, so a cutter beyond a corner can be
clear even when its own XY bounding box overlaps the stock box.

Exact tangency is different: `air` stays false, but `contact = "tangent"`
records no positive stock intrusion, using only the existing 1e-6 mm physical
equality tolerance for native-coordinate serialization. The cutter lowers at
the stock edge without a material-cutting plunge feed; it is not described as
clear of the stock. This does not relax the positive air margin. Unknown,
malformed or nonfinite geometry, positive intrusion beyond that equality
tolerance, and an otherwise unproven entry retain the plunge requirement.

A cutting plunge reaches level `k` from level `k-1`'s Z, which the same path
cut at that spot. A raster, a path in several pieces or an open path in several
levels returns to an entry (an unknown level count claims no return between levels):
`raise_z` is `approach_mm` above the current top on
the DRO grid (a raster's lift), and `raise_clear` is true only when the stock box
proves it above the stock (unknown without a box; the sheet then claims nothing
about it). An op with any plunge carries `plunge_mm_rev` (the cited `[[plunge]]`
feed) and, when unknown, `plunge_reason`. Outside drilling operations, plunges
are supported only for centre-cutting end mills with `center_cutting = true`; see
[cutting data](cutting-data.md#plunge) for selection and the known gap in tool-kind
enforcement. Fixture and clamp
heights are not in the box: a raise Z is never
claimed clear of them.

#### Lowering to the stock top

A single-level op whose level Z is the Z it starts from carries `lowered = "top"`
only when the setup-entry `stock_bbox_mm` puts that level at or above the stock top
(within the kernel's 1e-3 mm tolerance): nothing stands above it at any entry, so
the cutter is lowered to that Z, never plunged, and needs no plunge feed. An equal
start Z alone proves nothing at the entry: a feature's declared `entry_z` or an
earlier op's cleared floor is not the stock height where the cutter goes down, so
that entry plunges (with its feed, or as debt without one).

#### Pass-plan debt and printed instructions

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

### Bench grid inheritance

A bench setup (machine `kind` bench or manual, no declared `resolution`) has no DRO
of its own: `dro_grid` gives it the grid of the nearest machine setup in its
`stock_in` lineage, so a surface arriving from that setup prints the same Z.

### Blade and dome targets

#### Groove plunge positions

A `form_*`/groove op whose tool is a grooving/parting blade gets
`plunges` numbers: the corner the DRO reads (`reading_corner`, the corner the Z
touch in effect when the op cuts set; see `zero_check` blade corners, never the
blade's `hand`) at each plunge, flush with the chuck-side
wall and stepping evenly, never more than a blade width, until the last plunge
is flush with the far wall; the diameter each stops at; and the groove they
leave (`max(span, blade_width)`). A groove outside the feature's `width` band
is an `error` (`op {n} plunges leave a groove {w} wide, outside the drawing
width {lo} to {hi}`); an unknown blade width or reading corner is `unknown`,
and the sheet stops the op ("plunge positions not set").

#### Blade face targets and bands

For a blade `to_z` op (part-off or cut-to-fit with a grooving/parting blade),
the operation entry gets `blade` = {`reading_corner`, `forming_corner`,
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

Mounted-saw trajectory or body-side setting errors instead use
`mounted_saw_errors` and the “Mounted saw trajectory/zero error” diagnostic;
they remain errors and retain `mounted_saw_trajectory` evidence.

#### Dome roughing and finishing order

The rough stage of an `axial_table` op (a `form_*` op with
`rough_allowance_mm`, or a `rough_*` op) is a `stair_tables` entry, not the
finished table. Each row faces in at a finish-table Z below the apex to the X
where the sphere grown by half the diametral allowance crosses it, so every
stair corner (the imaginary-tip reading) stays that far off the dome; rows at or
past the base radius are dropped. An apex toward the chuck, or a window whose
base the sphere cannot reach (cap taller than its diameter), has no stair
(`unknown`). The finish table prints its row-to-row order for an apex-to-base
convex dome: X out to the next row first, then Z toward the chuck.

#### Lathe X display mode

Every lathe row's `x_target_mm` (feature rows, kernel span ends,
dome and stair rows, `setup_xz`, a dome's tool `x_tool_mm`) is the radius on a
radius display (`dro.radius_mode = true`) and twice it on a diameter one
(`false`). An omitted or unknown `radius_mode` leaves each of them unknown, never a
default display, and the setup `unknown` (`dro.radius_mode not stated`); the
sheet's feature map, part-off X and dome/stair tables then print no X and a STOP.

### Coordinate evidence and sources

Evidence groups cover frame/binding, reference rows, operation targets,
profiles, arc/line/axial tables and advanced entry surfaces.

Citations include PLAN §4.1, manifest frames and nominal geometry,
plan-owned setup frames, authored contour steps/targets/allowances and
selected inventory cutter nominal diameter. Manual arcs also cite
[plan manual arcs](plan.md#manual-arcs); roughs leaving stock to the file
cite policy `numbers.max_filing_stock_mm`.

## `manual_arc`

### Scope and radius band

`manual_arc` produces one finding per `scribe` or `file_to_line` op on an arc
feature: a boss, radiused end or declared semicircle. The subject is
`S<n>:<op>`, and the finding is always required
([plan manual arcs](plan.md#manual-arcs)).

It reads the arc layout in the op's setup: `centre_setup_xy`, `centre_on`
(the hole whose axis is the centre), nominal `radius_mm`, `radius_band_mm`,
`convex` and `ends_setup_xy` (absent for a full circle). Unknown geometry
leaves the finding unknown.

`radius_band_mm` is the drawing radial band, with a full circle's diameter
band halved. For a BASIC radius or diameter governed by a surface profile,
the zone derives the band pointwise from the DRF-located centre
([surface profiles](features.md#surface-profiles), harmonic-analyzer #1544).
A t = U = 0.2 zone `"increases"` a BASIC Ø20 boss to Ø[20.0, 20.4],
R[10.0, 10.2]. An ungoverned BASIC value or unresolved profile leaves it
unknown. `coordinates` arc tables still read only the drawing band.

### Scribe layout

For `scribe`, `layout` must be `dividers`, `trammel`, `template` or `ends`;
other values are unknown. A template (`guide.template`) must be an inventory
radius or profile gauge whose `range_mm` covers R. A range miss or wrong kind
is an error; unknown range or `verify = true` is unknown.

#### Arc-end marks for guided sweeps

`ends` lays out only the two arc ends for guided-sweep stops, where the centre
is too far off the part to scribe about. Marks A and B each have:

- A point measured from the nearer end face along X and nearer side face
  along Y of the received stock box, at 0.1 mm (0.005 in).
- A short stroke toward the arc centre at `angle` degrees (0.1°) to that side
  face. Each stop sits where its extended stroke runs through the cutter
  axis, whatever the stroke's direction there.

The layout needs a rectangular bar (`flat_bar`, `square_bar`, `plate`)
received as plan raw stock, faces (`axis`, `section_axis`) square to setup
X, Y and Z, a modelled stock box and both arc ends on stock. Only another
`scribe` or `inspect` may precede it in that setup. Anything else may cut
the reference faces. If any condition is missing, the result is unknown
because the bar's own faces cannot place the marks.

An `ends` layout draws no line. It cannot satisfy a later `file_to_line`,
rough or saw step that follows a scribed line.

### Filing buttons

For `file_to_line`, `guide.buttons` names an inventory `fixtures` kit of
`kind = "filing_buttons"`, held by `hold.fixture` or a clamp `ref` and pinned
through `guide.bore`. The bore must be on the arc axis and sized by a drill,
ream or bore before filing. Buttons guide only convex arcs.

The guide record carries all declared element limits in mm:
`button_dia_mm`, `button_bore_mm`, `pin_dia_mm` (the kit's `*_limits`
pairs), `button_runout_mm` and drawing `bore_dia_mm`.
The largest pin must enter the smallest bore and button bore. Maximum rim
centre shift from the bore axis is `centre_shift_mm`, comprising:

- `pin_in_bore = (bore_max − pin_min)/2`.
- `button_on_pin = (button_bore_max −
  pin_min)/2`.
- `runout = runout/2`.

The worst-case filed radius is `button_min/2 − shift` to
`button_max/2 + shift` (`files_to_mm`), which must sit inside the radial
band. Fit or band failure is an error.

A missing kit, an unheld kit, a kit or any fact flagged to verify, unknown
element limits or unknown radius band leaves the finding unknown. Invalid
limits include absent values, values other than two positive ordered numbers,
negative runout, or bore `dia` other than a known pair of numbers.

The sheet prints every element limit and worst-case band rounded outward to
0.001 mm. The shift basis remains in report `centre_shift_mm`. It marks the
band `not proven` unless the finding passes, or prints a STOP when the band
itself is not established.

### Template-guided filing and rough stock

`guide.template` instead files to a line laid out by an earlier `scribe`
(`layout_op`); no layout op is unknown. `guide.gauge` must name a radius or
profile gauge covering R; no gauge is unknown.

`rough_op` names earlier `stairs`/`chain_drill` roughs leaving stock to this
file. No such rough is unknown. Policy `numbers.max_filing_stock_mm` supplies
`stock_cap_mm`; it is unknown unless cited, nonnegative and `numbers_verify`
false.

### Manual-action and stock-model limits

`scribe` and `file_to_line` need no tool and count as hand finishing.
`file_to_line` is a finishing cut for coverage and inspection. A setup meeting
the [manual-bench predicate](#manual-bench-applicability) is
`not_applicable` for `coordinates`.

The kernel removes filed stock within the cap of each claimed face and each
convex edge shared by two claimed faces. It also removes the quarter the
stroke runs into beyond a straight claimed-face edge and outside its tangent
plane, when no other claimed face shares that edge and the tangent plane is
constant along it. This removes the corner nib between faces filed in
different ops. The finished part is never filed.

An unknown `manual_arc` finding stops its op. The op row prints a STOP with
the finding's `debts`, and the setup STOP list names the op. An unproven layout
or filing therefore cannot read as an established step. An error stops it
through the op's error box.

## `zero_check`

This is the base contract for a setup's zero and tool-touch finding. It
consumes the [plan zero recipes](plan.md#zero), readout settings and inventory
tools. Unknown recipes or unresolved physical references remain debt.
In the digital branch, contradictory direction, mode or surface settings
are errors.

Native-face details also have four operation-rule extensions:

- [Component-supplied touch planes](rules-operations.md#component-supplied-touch-planes-zero_check).
- [Carried multi-plane touch selection](rules-operations.md#carried-multi-plane-touch-selection-zero_check).
- [Same-setup native producer survival](rules-operations.md#same-setup-native-producer-survival-zero_check).
- [Usable native touch land after a plunge](rules-operations.md#usable-native-touch-land-after-a-plunge-zero_check).

### Applicability

A dedicated nonspindle saw setup (all nonmanual ops are `saw_cut` /
`cut_off`, at least one saw, no confirmed or possible spindle saw) is
`not_applicable`: its setting is `cut_plane`, not a spindle XYZ zero.
An unknown action cannot establish that exemption. A mounted slitting saw
requires the [mounted body-side setting](plan.md#mounted-saw-z-setting).
`zero_check` consumes its independent native `saw.zero` evidence, not the
geometry or engagement status. It proves stopped-spindle contact on the
exposed flat annulus and a clear axial approach. Missing evidence stays
unknown; a running touch or wrong body/plane side errors.

Body thickness and signed kerf offset determine the setting, never blade
radius or kerf width. New/reinstalled tool-holder pairs need matching touches.
Mixed setups preserve ordinary X/Y/Z recipes and known-error precedence;
ordinary touch evidence cannot be transferred to a mounted saw or vice versa.

A setup satisfying the [manual-bench predicate](#manual-bench-applicability)
is also `not_applicable`: it has no DRO zero to set. This is the same
machine-kind, nonempty-operation and verified-hand-saw test used by
`coordinates`; a bench machine name alone does not establish the exemption.

Manual `hand_tap` and `die_thread` operations do not assign a spindle or
toolpost cutting tool or generate a digital tool-change retouch. They are
hand operations, not native axial-cutter setting recipes. Listing their
actual tap/die and wrench/stock identities does not change that boundary.
A setup meeting the [manual-thread-only predicate](#manual-thread-only-applicability)
needs no zero recipe. A mixed setup outside that predicate retains the zero
and coordinate debt of its other work.

### Mechanical dials and unknown readouts

The plan's [`dro.kind`](plan.md#dro) selects the readout contract. Omission
keeps the existing digital branch. Explicit `"handwheel"` selects mechanical
dials; explicit `"unknown"` establishes neither a digital grid nor a
mechanical setting. Controller names and machine prose do not override that
selection.

Nominal target lengths convert once from manifest units to `dro.units`, which
is independent of CAD units. Omitted units retain manifest units; explicitly
unknown or unsupported units do not acquire a display-unit fallback. A metric
model can therefore produce inch nominal targets for `dro.units = "in"` while
the drawing's limits retain their own units.

`dro.graduation` records a positive nominal source division, not a calibrated
digital resolution. Lathe `radius_mode = false` means X divisions indicate
diameter change; `true` means radial change. For example, a source division
of 0.002 in on a diameter scale represents 0.0508 mm of diameter change and
0.0254 mm of radial travel. This conversion establishes no physical accuracy.
An unknown radius/diameter convention leaves X scale meaning unresolved.

The sheet prints the authored readout and setup procedures, per-axis pickup
procedure or method, contact and direction, source graduation, calibration
and backlash text. It keeps the [axis `dial_setting`](plan.md#axiszero) in
declared readout units separate from `edge_mm`, the nominal CAD datum. A
model coordinate of zero never supplies a physical dial zero. Missing
physical readings remain `STOP: physical dial setting unknown`, and missing
graduation, calibration, backlash or direction stays visible as debt.
Tool-change touches retain their authored method but require the actual
scale reference and contact compensation; none is inferred from nominal
geometry. This branch generates no electronic Axis Set or Preset instruction.

After the [applicability exemptions](#applicability), mechanical and unknown
readouts produce an unknown `zero_check`. The finding retains `readout`,
authored `axes`, `physical_setting_debt` and `tool_touches`. Even fully
populated source procedures and readings cannot establish measured dial
accuracy or dial-to-part registration in the current model. The nominal
graduation and calibration prose do not clear that HOLD. Consumed coordinate
targets likewise keep `coordinates` unknown through `dro_grid_debt`, unless
an independent error takes precedence. Neither readout kind creates an
installed-digital-DRO measurement task.

Establish the actual instrument, datum pickup, graduation/scale meaning and
backlash behavior at the machine; do not substitute a drawing target for
those facts. The current checker does not convert that physical work into a
mechanical-readout pass. Local rendering or arithmetic is not physical
acceptance evidence.

Readout conversion and coordinate debt are implemented in
[`rules/coordinates.py`](../src/prechips/rules/coordinates.py); the mechanical
zero finding is in
[`zero_recipe/rule.py`](../src/prechips/rules/zero_recipe/rule.py).

The remaining zero-recipe subsections describe the digital branch.

### Guided-sweep X/Y exemptions

A setup whose every spindle op (one with a `tool`) is a `guided_sweep` needs
no X or Y recipe. Master touch-off sets those axes and X/Y stay locked, so
omitted `zero.x`/`zero.y` are not gaps. `touch_set` names the axes and ops,
and the DRO ZERO sheet says X and Y take no edge pickup. Z keeps its recipe.
This exemption's rationale is recorded in
[#255](https://github.com/pedropaulovc/prechips/issues/255).

Touch feed and rough back-off still use X/Y DRO signs. A reversed
`dro.direction` is an error and an undeclared one is debt, as for edge pickup.
Any other spindle op still needs both recipes.

When every spindle op uses a trammel, X and Y never move: the rail crossing
fixes the cutter. No X/Y DRO sign is consumed. Authored `zero.x` or `zero.y`
is an error because pickup would move the table off the crossing.
`touch_set.by` is `"trammel"` (otherwise `"touch"`), and the DRO ZERO sheet
says the rails' pin-lines cross on the spindle.

### Axis Set, contact and check jog

Use EL400 ABS Axis Set, not Preset. Approach side is independent of jog
polarity. For edge finding, `contact=edge + side*finder_radius`, side -1 from negative
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

### Edge-finder procedure facts

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

### Listed retouches

For each authored Z `retouch_after`, the new set value is advanced top + paper.
A profile does not move the touched top. A listed retouch sets Z for the next
cutting tool only: each `retouch` row carries `next_op`, `next_tool` and
`tool_change` (true when that tool is not the one in the spindle, unknown when either
tool is unknown; past the last cut `next_op`/`next_tool` are `not_applicable` and
`tool_change` false). The sheet tells the operator to
install the incoming tool, then touch the top and Axis Set Z; with no change, the tool
stays in and only re-touches.

### Measured-setting methods

#### Trial-cut X measurement

X `method = "trial_cut_measure"` cuts a diameter, measures it at the machine
with the declared `gauge` and Axis Sets that reading. Like paper thickness the
reading is a bench value, so the recipe is complete when `tool` and `gauge`
resolve without a verify flag, `check_jog_mm` is numeric and the lathe
`radius_mode` is known. The rows show bench expressions: diameter mode
`measured D`, check `D +2j`, mirror `D -2j`; radius mode `measured D/2`,
`D/2 ±j`. A target diameter is never used as the measurement.

#### Measured Z position

Z `method = "measure_then_set"` touches a face whose position is measured at
the machine (M, read with `gauge` as the stated `measure`) and Axis Sets
`M + offset_mm + side*paper_mm`; check/mirror are `M ±j` on the same base. Like a
trial cut it is complete when `gauge` resolves unflagged, `measure` is stated
(`"unknown"` states nothing) and `offset_mm`, `paper_mm` and the jog are
numeric; the rows show `M -9`, `M +1`. The same holds for a tool touch's
`z_measure`.

### Authored tool touches

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

#### Lathe X touch surfaces

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

### Clamped datum transfers

A datum `transfer` with `keep_clamped = true` cannot be tapped true: a sweep over
its `runout_limit_mm` needs the plan's `recovery`. Without a stated `recovery`
(missing, blank or `"unknown"`) the finding is `unknown` (`state
transfer.recovery`), and the traveler prints a STOP in place of the transfer.

### Paper side

Paper lies between tool and face, on the side from which the tool meets the
face. A Z touch through `paper_mm` of paper (the zero, a tool touch or
a derived re-touch, which repeats its source's paper from the same side) stands
the tool `side*paper_mm` off its edge. Off a lathe the tool comes down on its
face: +1. On a lathe the side is the touched face's outward normal along setup Z
(as for blade corners below); without one, a grooving/parting blade meets the
face on the side of the corner it sets (its authored `corner`: chuck-side +1,
tailstock-side -1) and any other tool from +Z. A blade touch through nonzero paper
whose side is unknown has an unknown Axis Set; with no paper the side does not
matter. `paper_mm` itself is always printed as the positive thickness. A listed
top `retouch_after` is `top + paper`.

### Blade touch corners

A Z touch (zero, tool touch or derived re-touch) by a
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

### Lathe tool setting

On a lathe, `tool_setting` has one record per toolpost tool, meaning a tool used
by a non-axial op other than `hand_tap` or `die_thread`. Records follow op order
at each tool's first touch-off: the zero (`touch = "zero"`, `axis`), else its
first `tool_touches` or `derived_touches` entry (`index`).

Each record carries `centre_height` and, for a grooving/parting blade,
`square_blade` (otherwise `not_applicable`). It uses machine `toolpost` words,
else the requirement alone: "set its cutting edge on spindle centre height"
or "square the blade to the spindle axis". The sheet prints
"Before touching off {tool}: ..." before the zero table for its tool and
before every other tool's first touch.

Sources are Moltrecht, *Machining for Hobbyists: Getting Started* (2015)
ch. 6 p136 Fig. 6-7 and p147 Fig. 6-20, plus the toolpost's own `cite`.

### One DRO and tool-change retouches

The DRO reads the tool that last set it, through the zero, an authored tool
touch or a listed retouch. A tool touch occurs before the first of its
`before_ops`, else after its `after_op`. Ops before the Z zero's `after_op`
run before any tool set Z. An axis without a zero recipe has no tool Axis Set
to change; that missing zero is unknown.

`hand_tap` and `die_thread` do not change the spindle tool or become the latest
digital setter, so they generate no derived retouch or toolpost-setting
instruction. Their real tool numbers identify the manual assemblies only.

Each eligible powered cutting op whose tool did not make the latest Axis Set gets a prior
touch (`derived_touches`, printed "re-touch"). The source recipe names its
own tool edge, so the derived recipe is tool-neutral: `edge_then_set` on a
lathe (Z-cutting edge to surface, withdraw along X) or `touch_then_set` on a
mill.

#### Standing Z surfaces

The derived Z touch uses the latest touched or faced surface proven to stand
at a known plan Z: the zero face, a tool-touch face, a listed retouch's top
or a face/pocket op's `to_z`. Faced surfaces take the zero's paper.

The rule follows each surface through later ops using `cut_coverage`
(`whole`, `partial` or `unknown`). A surface ends when an op cuts all of it
to another Z, cuts it to an unstated Z (`to_z` omitted or `"unknown"`), or
cuts it other than by facing/pocketing. For the top, that means facing the
stock's `top_feature`, or any face op if it has none.

Partial cuts preserve the uncut Z only while a land remains outside all
their `stock_removal_bounds`: a square `TOUCH_LAND_MM` of 0.5 mm on a side.
This is an author-chosen illustrative value, not a measurement. Paper touch
needs a patch the operator can see, put the tool end over and slide paper
under. A narrower sliver may lack flat surface after adjacent burrs are
counted, or depend on geometry the operator cannot check. A larger threshold
leaves more Z unknown; a narrower land is unknown, never pass.

#### Native rectangular land proof

Land must lie on proven surface. The feature's one STEP face (`faces`) must
be a plane filling its own box (`fills_bbox`):

- One wire.
- Each edge a straight segment within the kernel's 1e-6 mm side tolerance
  of a box side.
- Face area greater than the area of that tolerance band along the box sides.
- Flat in setup Z.
- Each box corner on a corner of its setup X/Y footprint box.

No land counts within `FILL_MARGIN_MM` of a box side (1.5e-6 mm: side
tolerance plus the 5e-7 mm that 6-decimal record rounding may move each side),
or within the 1e-6 corner tolerance. A notch may still occupy those margins.

Without a kernel result, or for a round, holed, notched, L-shaped or
setup-axis-turned face, box corners may hold no surface. Missing area can
be small: a 0.005 mm hole could be the only part spared by every cut.

A zero, tool touch or listed retouch at nominal Z does not prove what later
ops left. It retains their partial cuts and uncertainty. A same-setup
produced surface is proven only at its producing Z, and the top only at its
tracked Z. Only a whole cut creates a new surface. A zero `after_op`,
listed retouch or tool touch uses that tracked top; facing with no depth
leaves it unknown.

A surface remains unproven when:

- It is unnamed, such as a zero without `face`.
- An op on a feature the plan does not name ran after the surface was made,
  or a face op ran while the top's `top_feature` was unresolved.
- Coverage is unknown, the surface may be gone, or its touch disagrees with
  or cannot be checked against the producing Z or tracked top. Missing
  footprint inputs name the touched feature and input, such as kernel
  result, unmatched `faces` ref or missing `bbox_mm`.
- Cumulative partial cuts leave no land, or the face is not proven to fill
  its footprint.

Without a proven surface, the latest one not shown gone repeats with unknown
Z and Axis Set. A measured Z (`trial_cut_measure`, `measure_then_set`) is
not a plan number that can be repeated.

#### Lathe diameter retouches and missing touches

On a lathe, derived X uses the latest still-standing diameter turned in this
setup (`turn`, `rough_turn`, `finish_turn`), measured with the latest X gauge.
Axis Set uses that measurement. A turned diameter stands until an op cuts
that feature other than by turning, such as forming a dome, or cuts an unnamed
feature. A touch's `x_method` surface is prose the rule cannot follow past a
cut, so it never repeats it. Tailstock tools (axial actions) do not read
the carriage DRO.

An unknown cutting tool leaves the setter unknown. An incoming tool that
does not resolve or has a verify flag keeps a derived touch unknown, just
as for an authored touch.

An axis with no derivation source produces a `missing_touches` row with
`before_op`, `tool`, `axes` and `dro_set_by`, and an error: cutting on
another tool's Axis Set scraps the part. An authored touch for that tool
before the op replaces derivation.

### Swivelled-vise pickup

Under `jaws_angle_deg`, work edges stand off table travel. An X/Y pickup
other than `from = "indicated"` (an indicated bore centre) is unknown and
listed in `swivel_unproven_axes`. See [swivelled vise](plan.md#swivelled-vise).

### Touched faces and same-setup rounding

Every non-measured Z touch (zero, tool touch, derived re-touch or listed top
retouch) sets its Axis Set from known face height in this setup's frame.
When an op cut that face under a set Z DRO in this
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

#### Unknown heights and native-plane eligibility

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

### Explicit actual-stock top contact

A paper Z zero with `face = "top"`, an explicit tool-axis `at_mm = [X, Y]`
and no named `stock_state.top_feature` requests native proof on the actual
arriving stock. A paper `ToolTouch` with `z_face = "top"` can request the same
proof at its own explicit `after_op` / `before_ops` boundary by declaring its
own `at_mm` and `retract_clearance_mm`. These coordinates and lengths follow
manifest units despite their `_mm` names. A later touch never inherits the
initial touch's pose or surviving contact land.

The selected end mill needs an explicitly qualified flat end (measured nose
radius zero), cutting diameter and length, shank, verified tool-holder
projection and complete holder envelope. The native model requires an actual
+Z planar patch at the requested height. A 0.5 mm square centred at the
authored tool-axis point must lie inside both that patch and the flat-end
projection. The cutter disk may overhang the face; its entire circumference
need not fit. The finite land must lie wholly inside one connected positive-area
component of the actual disk/top contact. Coplanar fragments connect through
positive-area overlap or a shared boundary segment, not an isolated touch point
or proximity. The native check uses the face common for area and the B-rep
section for shared edges and points; the selected patch is their actual fused
area, with overlap counted once. Other separate contact components may exist;
their area cannot repair a missing land on the selected component.
The report's selected patch bounds and area describe that component, while
total contact and uncovered areas account for the complete disk. No enclosing
box or union of disconnected areas substitutes for the selected land. This is
the qualified flat-end projection model, not a claim about individual flute
phase or the cutter's exact cutting-edge B-rep.

The complete occupied tip, shank and holder must clear actual stock and
fixtures during descent from above the occupied scene, the signed check jog
**from the paper-contact Axis Set**, and retract. The native result separately
retains the actual stock's upper bound; an enclosing box by itself proves
neither a planar zero surface nor a touchable land. Negative check jogs that
intrude into stock are errors, not clearance.

The setup sheet prints the selected tool-axis XY, the proved safe start and
retract height, paper-contact height, Axis Set and signed check jog in that
physical order. A staged touch stays beside its declared tool change. A
missing or failed requested proof leaves a STOP; native recipe hashes, model
names and face identifiers stay in the report rather than the operator steps.

Proof is bound to the exact current recipe, selected tool and holder,
normalized frame, stock route and raw operation boundary. Each dependent
operation is gated on that same proof before native material or motion
credit. Cold coordinate normalization may compile the declared command
plane under this gate; it does not establish that plane as physical evidence.
The rule consumes only the matching actual native plane afterward. A missing
pose, unknown qualification, unsupported bench effect, incomplete path or
absent/stale proof stays unknown. Known contradictions and collisions remain
errors even when other facts are unknown. A named native top keeps the
existing face-identity and survival rules below.

### Carried native faces

A whole credited face may carry through the traced `stock_in` lineage into
a bonded or remounted setup. An intervening cut that can lower that face, or
whose effect is unknown for it, breaks the credit; an untraceable stock link
also leaves it unknown. The new physical height carries the producer's AS-CUT
`formed_z`, not the native CAD nominal. The source native plane establishes
identity, orientation and raw nominal Z; its point is displaced by
`formed_z - native_z` along source setup Z, then that displaced point and the
normal pass through the recorded source and receiving rigid frames.

#### Transformed-plane evidence

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

#### Surviving touch land after a plunge

An overlapping axial drill, ream, spot or counterbore preserves usable touch
land only when a single native `Plane` with `fills_bbox = true` proves an
axis-aligned rectangle retaining a 0.5 mm square outside the cumulative
bounded footprint. The worst-case radial footprint includes its cutter and
aim shift. Radius extrema alone prove neither circular topology nor usable
land; round, holed and missing-shape faces stay unknown after an overlapping
plunge. See the [native topology evidence discussion
(#208)](https://github.com/pedropaulovc/prechips/issues/208).

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

#### Carried-face settings and receiving-grid rounding

A carried face was not cut onto this frame's grid. Its authored edge must
agree with the transformed physical height or the exact raw native plane
within the existing length tolerance, else an error names the mismatch.
An authored nominal edge matching that raw plane does not contradict a
proven producer's rounded AS-CUT height. An unknown producer cut cannot
invent an AS-CUT height: it stays unknown unless the existing native-fallback
rule explicitly proves the fallback.

From above, its Axis Set rounds physical height plus paper down to the
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

#### Imported hole entries and physical exit bounds

For an imported hole entry, `stock_state.entry_z.<feature>` (or `top_z`
when it supplies that entry) must remain the transformed native nominal
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

### Zero-check finding messages

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

### Zero-check evidence and operator acceptance

Digital evidence: per-axis contact/set/check/mirror/sign, source edge, finder radius,
paper, jog and DRO direction, retouch list, per-tool touches, derived and
missing tool-change touches and transfer.
Citations: PLAN §4.1 and Electronica EL400 Operation Manual §6.2 p20, §7.4 p31,
§8.1 p37, §9.2.1 p62; plan zero/stock-state and inventory finder nominal size.

The digital recipe requires a jog without retouching. The operator must exercise
physical emulator direction and actual check readings. Local computation does
not prove the paper/emulator acceptance control.

The base finding is implemented in
[`zero_recipe/rule.py`](../src/prechips/rules/zero_recipe/rule.py).

