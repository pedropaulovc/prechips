# Operation chain, order, depth and cutting starts

Reports expose exact evidence and citations; setup sheets render plain sentences
and computed endpoints. Array order is execution order. These rules never mutate
the bundle and do not infer a missing stock state or cutting-data value.

## `op_chain`

One subject per feature. Hole/thread/threaded-hole/counterbore routes need spot
and drill. Ream process needs ream; a thread needs tap; counterbore needs its
parent/hole drill. Tap-drill diameter must match the explicitly supplied
`tap_drill_mm` and verified selected drill geometry; the converted lengths are
equal within an absolute 1e-6 mm (no relative tolerance), so `3/8` in and
`9.525` mm agree. Nonholes are not applicable.
An explicitly unknown feature kind or hole-chain action gives unknown; unknown
process/thread specification also leaves the chain unresolved.

Templates:

- `{feature}: not a hole chain.`
- `{feature}: feature kind or hole-chain action is explicitly unknown.`
- `{feature}: hole prerequisites are present across the route.`
- `{feature}: thread tap-drill specification/measurement unresolved.`
- `{feature}: {errors}.`, with semicolon-joined clauses: `no drill operation`,
  `no spot operation`, `required ream operation absent`, `thread requires a tap
  operation`, `counterbore operation absent`, `counterbore has no parent hole
  drill`, `selected tap drill differs from thread specification`.

A contour/form op (a `contour` table, or `do` starting `form`/`profile`) whose
numeric `z_from` is a face an earlier op in the same setup leaves only within a
`to_z_band` is an `error` on its feature: `{sid} op {n} starts at Z {z}, which
op {m} leaves anywhere in {lo} to {hi}; an op must leave that face at a
deterministic to_z first`. The last earlier op whose `to_z` is that Z (or whose
band holds it) decides, so an unbanded facing op between them clears it. An
unknown band end prints as `an unknown Z`: it still makes the op's own `to_z`
a banded face (`error`). Whether it holds a different start is `unknown`
(`unknown_starts`: `…, which may hold it`), and the scan goes on to earlier ops:
an earlier band that holds the start makes it an `error` either way.

Evidence: feature kind, route operation ids and actions, expected/selected tap
 drill mm. Citations: PLAN §4.1 op chain, authored route, declared process/thread.

## `order`

One subject per setup. Across the route, ream/tap/counterbore must follow drill,
and a drill must not precede its feature's only spot (a spot already before the
drill is its spot); spots follow facing when that setup includes facing; rough
must not follow the same setup/feature's finish; release/part-off must follow all
remaining cutting in the same setup, while later setups may cut the released part.
A finishing hole op in another setup must have incoming `stock_in` or transfer
from an earlier setup. This is route order, not physical fixture continuity.
An unknown action in the setup makes its order unknown.

Templates:

- `{setup}: rough/finish, face/spot, hole and release order is consistent.`
- `{setup}: operation order cannot be established while an action is explicitly unknown.`
- `{setup}: {violations}.`, joining `op {n} {action} precedes its drill`,
  `op {n} drills before its spot`, `op {n} spots before facing`,
  `op {n} roughs after finishing {feature}`,
  `op {n} releases before the final cutting operation`, and
  `op {n} has no incoming route from the drilled setup`.

Evidence: authored sequence and violations. Citations: PLAN §4.1 and plan
setup/operation sequence plus `stock_in`/`zero.transfer`.

## Component-supplied touch planes (`zero_check`)

A bounds-free native face may be touched in a later setup without a new facing
operation when its exact STEP face is listed in `stock.as_is_faces` and its
own component root proves that it arrives as that surface. The global as-is
check validates the joined stock union only; it cannot credit a sleeve face to
a body branch. A component supply is an exact declared `stock.<component id>`
on the validated upstream route, consumed alone by its root setup. A joined
root, an undeclared stock-like name or a literal `stock` alongside components
is not component-local proof. Ordinary single-stock seeding is unchanged.

Component credit requires all of these existing facts:

- The root's `stock_state.top_feature` or `bottom_feature` names the touched
  feature. Its matching pre-cut native `stock_faces_mm` side (`up` or `down`)
  has finite `face_z` and `stock_z`, equal within the absolute physical length
  tolerance of **1e-6 mm**. A reason, missing height or stock-height mismatch is
  debt, not a supplied face.
- The exact geometry-matched source native plane resolves the selected STEP
  face, its source-frame Z and outward normal. Its Z agrees with the pre-cut
  face height within that same physical tolerance. A model AABB or generic
  revolved geometry alone proves no entering component material.
- The same component root's `render_scene` contains the exact named datum for
  that feature, with a finite coplanar outline and the matching outward normal
  and Z. Native datum emission requires the named surface to be on that
  component's material. This additional proof is necessary:
  `stock_faces_mm` intentionally retains a same-Z height even when the stock
  carries a face only in part.
- The component root has no entering or retained-stock debt. The plane then
  survives the existing stock-DAG operation and bounded-touch-area checks.

The render datum describes the root's material after its operations; it never
bootstraps an as-is supply when the pre-cut proof is absent or mismatched.
A datum on a later joined or receiving solid cannot replace either root proof.
Unrelated roots that do not name the target remain unseeded, not declared
geometrically absent; they do not poison a separately proven supplier. A named
candidate with missing proof remains unknown. With no proven supplier, the
unknown names the component and face instead of silently treating it as absent.

The supplied plane is carried through the normal rigid-frame rules, not reset
to a model-box height or a later cut's nominal Z. A source `down` face may
become receiving +Z after a rigid flip; credit still requires a finite +Z
outward plane and a known above/+Z touch in the receiving setup. Subsequent
cuts retain the same preservation, bounded exclusion and tool-change touch
rules as an upstream-prepared face. Missing component proof prints no credited
face or numeric contact setting.

## Carried multi-plane touch selection (`zero_check`)

A bounds-free named face may contain STEP planes at several Z heights. The
authored contact edge selects the native plane group; it is not automatically
the highest member of the feature's bounding box. The rule traces every group
internally, but only the uniquely selected group's exact raw STEP refs receive
credit. An unprepared upper member does not prevent contact on a separately
prepared lower +Z member, and selecting a prepared maximum member keeps the
same behavior.

Each group has its exact raw native height in the receiving frame. Flat
geometry-matched native boxes can provide that height; an oblique world box
cannot. An oblique plane instead requires its exact source native plane or
named stock-proven source datum, rigidly transformed into the receiving frame.
Missing or inconsistent native height proof is unknown, never a maximum-box
or nearest-plane fallback.

An authored edge matches a group within the absolute physical length
tolerance of **1e-6 mm**, in either millimetre or inch manifests, at either:

- its exact transformed native height; or
- its traced, eligible producer's actual as-cut height after the source DRO
  grid and rigid frame transform.

These are two ways to identify the same group, not two separate groups. In
contrast, distinct native planes are not merged merely because their heights
are within the matching tolerance. Exactly coplanar numerical planes may
share one group and credit all its refs. If two distinct groups match through
any combination of native and eligible as-cut heights, the contact is
**unknown**; the checker never picks the nearest one or the one that happens
to have a producer.

With complete plane/eligible-height proof, no matching group on a multi-plane
face is an **error** naming the authored edge and known candidate heights.
There is no invented numeric Axis Set and no borrowed credited face. Missing
eligible physical-height proof stays **unknown**, not proof that the plane is
absent or that the no-match comparison is complete. An eligible whole-plane
producer with an unknown formed height carries that height debt; a later
genuinely proved whole producer may replace it without clearing any prior
unknown cut-area debt.

An independently proved non-+Z member is known ineligibility, not missing
physical proof, and does not poison another uniquely selected valid +Z group.
It still participates in raw native matching and ambiguity; if selected, its
normal is rejected by the existing +Z contact rule. Unknown intersecting cut
or touch-area debt on the selected group remains unresolved.

Selection does not establish stock presence, +Z orientation, touch side or
surviving touch land. The chosen group still needs the normal existing
producer/supply, lineage, rigid-frame, bounded-area and above-touch proofs,
including the component-root facts described above. A matched but unfaced or
wrong-facing member remains unknown. A single native plane retains its
existing physical/native edge contradiction check and its proved physical
standing height.

## Usable carried touch land after a plunge (`zero_check`)

A bounded axial plunge that intersects a carried face does not preserve a
usable touch merely because its radial reach is smaller than a reported outer
radius. A nonempty annulus can be too thin for the paper/tool contact. More
fundamentally, the existing native `revolved` radius extrema and outward-plane
normal do not prove circular or annular topology: horizontal noncircular
patches can have the same facts. Sampled datum outlines and a model AABB are
not substitutes for that proof, nor do they rule out the face's original hole.

The supported overlapping-plunge preservation path is the existing exact
rectangular witness:

- The selected native face is a single `Plane` with `fills_bbox = true`.
  This native fact requires a filled, one-wire, straight-sided rectangle;
  round, holed, notched and L-shaped faces do not qualify.
- Its transformed box is flat in setup Z and axis-aligned in setup X/Y. The
  existing `FILL_MARGIN_MM` and corner-tolerance shrink keeps the witness
  inside the area actually proved filled.
- The existing `TOUCH_LAND_MM` policy requires a **0.5 mm by 0.5 mm square**
  outside the bounded plunge exclusion. The plunge's conservative engagement,
  location/aim and DRO-grid envelope are still used, not the nominal tool
  diameter alone.
- Prior and current exclusions remain cumulative. A conservative square
  envelope about the rigidly carried source-plane centre encloses all the
  removed radial regions; its reach is the maximum of the prior reach and
  the current plunge's radius plus centre offset. The existing `_uncut`
  witness must lie outside that whole envelope, not merely outside the last
  smaller cut. Re-facing does not erase prior unknown cut-area debt.

A missing filled-rectangle witness or no remaining 0.5-mm square leaves the
subsequent contact **unknown**, with the setup/op and named contact face in
the usable-land debt. Even an ample reported radius on a round or holed face
remains unknown after an overlapping plunge. Exact native circle/annulus
topology and original-inner-hole evidence are tracked in
[issue #208](https://github.com/pedropaulovc/prechips/issues/208); this rule
does not invent those facts or add a native schema field.

The initial contact before the plunge remains eligible when its plane,
presence, outward normal, lineage and touch side are proved. Proven disjoint
cuts retain the existing preservation path. Supported rectangular contacts
still report their cumulative exclusion diameter, and the traveler keeps its
outward-rounded exclusion note; unsupported contacts print no credited face
or numeric Axis Set. This is a checker limitation/stop, not a claim that no
physical touch patch exists.

## `blind_depth` (tip endpoints)

One subject per feature, with an `endpoints` array for spot, drill, ream, tap,
counterbore and bore operations, and for `center_drill` on a plan
[process](plan.md#process-features) `centre_hole`.
Stock-state facing/pocketing advances only the named or explicitly covered
same-frame entry surfaces. A known setup-frame `stock_removal_bounds` that
contains a feature's whole X/Y footprint (its declared one, or for a bounds-free
`kind = "face"` each listed plane at the op's `to_z` by its own matched kernel
`bbox_mm`; see [coordinates](rules-coordinates.md)) can advance its seeded local
entry without requiring a redundant bounds box on the cutting op's own feature.
A native face's incidental `at`/`dia`, axis or plane metadata is never a declared
extent, even if it describes a smaller disc wholly inside the cut. The complete
face list must resolve before a bounded cut selects the planes at `to_z`.
Missing or ambiguous mappings, invalid native boxes, or unresolved units/setup frames
leave native coverage unknown and earn no face credit; they never fall back to that
disc. Explicit authored face `bounds` and true round non-face features retain
declared-footprint behavior. An authored empty or whole-record unknown face `bounds`
is debt, not permission to use a disc or native-box fallback. Malformed explicit
bounds also remain debt when their containment cannot be established.
Unbounded cuts of their own feature retain the existing declared-whole semantics;
their keep-out checks use actual native boxes for bounds-free faces. Cross-feature
unbounded native-face containment without explicit target bounds leaves its producer
unknown, not a disc-based whole producer. This does not advance a seeded local entry:
the unboxed entry-selection path retains its existing skip behavior when there is
no declared footprint candidate, keeping the seed and its origin unchanged.
Bounded cross-feature facing/pocketing producers
are decided by native coverage even when the cutting feature has no authored
footprint. An authored empty/unknown target face footprint is also a guarded producer
candidate: unresolved coverage cannot silently become a skipped op and an accepted
numeric contact edge. An explicit local operation source must still prove whole native
coverage; partial or unknown coverage cannot supply that face. A later bounded cut whose
complete native boxes are XY-disjoint is non-producing even at another floor, so it
does not hide an earlier proved producer. For an operation
with `stock_removal_bounds`, the box's Z interval must contain both the current entry
and `to_z`. That boxed cut cannot numerically raise the entry; a higher floor outside
the same-plane float tolerance (`SAME_Z`, 1e-9 plan units), or a box wholly above or
below the entry, leaves its height and source unchanged. Unknown removal Z or an
unknown entry remains debt for these boxed cuts, never a known entry inferred from
X/Y coverage alone. A valid equal-Z boxed cut, including float residue within
`SAME_Z`, still establishes its operation as the producer while keeping the lower
numeric value of the current entry and `to_z`. These boxed constraints do not change
the existing unboxed own-feature/explicit-footprint transitions.
A seed can name the eventual hole-entry face, not the raw material
boundary: the touched `top_z` of another feature does not replace that local entry.
Partial coverage retains the uncut entry; unresolved coverage remains debt.
Profiles never move the touched top; `top_feature` restricts which facing
operation moves that top. An omitted local `entry_z` retains the existing
stock-state top fallback. Each record preserves entry origin, setup/op,
point/lead, thickness, allowance and tip endpoint.

Arithmetic in mm: stock-state top/entry coordinates and operation `depth_mm`
are machine millimetres even when the feature manifest uses inches. Feature
depth limits are converted from the manifest's units. A tap without an
operation depth uses the upper `thread_depth`, or `depth` if no thread-depth
field is present; an explicitly unknown operation depth does not fall back.
For a resolved centre-drill member used to spot, carried-face touch exclusion
uses the same explicit operation `depth_mm` as the tip endpoint: the pilot
radius expands by `max(0, depth_mm - pilot_len_mm) * tan(angle_deg / 2)`,
capped at the body's `shank_mm / 2`. A feature-only spot depth is not an
operation depth and leaves preservation unknown. Missing, unknown or unverified
engagement facts also remain debt; located aim and DRO-grid shifts still enlarge
the exclusion.

- Drill point `P = D / (2*tan(included_point_angle/2))`, requiring D > 0 and
  0 < angle < 180 degrees and a finite cone length. An underflowed zero
  tangent or nonfinite cone leaves the point length unknown; it never supplies
  a zero-length tip. Centre-seat angle is not drill point geometry.
- Spot: `tip_z = entry_z - depth_mm` (point is recorded, not added to spot depth).
- Through drill: `exit_face = advanced entry_z - local_thickness[feature]`;
  `tip_z = exit_face - P - exit_mm`. A negative `exit_mm` (through ream too) is
  an error and that endpoint's `tip_z` is `unknown`: the tool would not break
  through, so no stop is offered.
- Through ream: `tip_z = exit_face - lead_mm - exit_mm`.
- Through bore/counterbore: `tip_z = exit_face - exit_mm`, with no drill-point
  or reamer-lead addition. The named cutter's tool-zero and reach still require
  verification; this is a nominal axial target, not certified cutter geometry.
- Blind drill/ream/bore/counterbore: `total_depth = depth_mm + point_or_lead`;
  `tip_z = entry_z - total_depth`; total must not exceed the feature's upper
  depth limit. Unknown thru/depth/tool geometry stays unknown.
- Tap: `tip_z = entry_z - depth`; verified flute length must cover thread depth.
- Centre hole (`center_drill` on a process `centre_hole`): `depth_mm =
  drill_length_mm + (mouth_dia_mm - drill_dia_mm) / 2 / tan(countersink_angle_deg / 2)`,
  the Table 6 drill length C (point included) plus the countersink that opens to
  the mouth; `tip_z = entry_z - depth_mm`, with `countersink_depth_mm` and
  `drill_length_mm` recorded and `depth_scale = "quill"`. The tailstock quill
  feeds it, so the sheet prints the depth past touching the end on the quill
  scale, not a carriage DRO Z. The depth is only ever the selected tool's own
  centre, built from every fact the kernel cuts it from (`tool_centre` records
  the accepted ones): `drill_dia_mm` must equal the tool's `dia` (Table 6 D),
  `drill_length_mm` its `pilot_len` (Table 6 C, countersink start to point tip)
  and `countersink_angle_deg` its `angle_deg` (a centre-drill set's centre-seat
  angle, which a member may override), within 1e-6 mm / 1e-9°; `mouth_dia_mm`
  must not exceed its body (`shank`, Table 6 A); and its pilot `point_angle`
  must be an included angle whose finite point
  (`dia / 2 / tan(point_angle / 2)`) is shorter than `pilot_len`.
  An underflowed zero tangent or nonfinite pilot point, countersink depth or
  combined centre depth remains unknown and cannot authorize native cutting
  or centre support. The finite Table 6 drill length C stays visible as its
  own fact; it cannot substitute for unresolved countersink geometry.
  The mouth must also be where the quill is touched:
  `at`, transformed into the setup frame, must lie on the entry surface `entry_z`
  (1e-6 mm), `axis` must be the setup -Z feed and, on a lathe, the mouth must
  sit on the spindle axis (setup X = Y = 0, 1e-6 mm) the tailstock quill feeds
  along (`mouth_z` is recorded). A mismatch is an error; an unknown or
  unaccepted size, tool fact, mouth or entry surface is unknown (its
  measurement debt is listed), as is a tool that is not in the inventory or
  whose record is unconfirmed (`verify` or an unknown flag anywhere on it, as
  for every endpoint). Either leaves `depth_mm` and `tip_z` unknown, so the
  sheet prints no quill depth, and the kernel cuts no centre. This row's verdict
  is the one [`centre_support`](rules-setup.md#centre_support) reads for the
  centre's maker.

The geometry kernel's spot and drill cutters use the same depth semantics:
spot depth is the apex tip depth, and drill depth is the full-diameter depth
with the tip one point length (`r / tan(angle/2)`) deeper. A spot's endpoint
here does not add its point, but its included `point_angle` is still mandatory
for the kernel's point cone; an unknown angle is accessibility and later-stock
debt there (see [geometry](rules-geometry.md#accessibility)). Endpoints
here do not prove a cap is formed. The kernel separately requires each
feature's last drill, ream, bore or counterbore to leave its claimed caps clear
of that setup's stock, so a flatter point, a smaller pilot or a flat finishing
floor above a modelled cone is named stock debt.
A spot on a through feature still uses its authored mouth depth; it does not
inherit the through bore's exit. This also bounds the kernel's reach and
cutter/holder poses, not just the traveler endpoint column.

Exact sentence alternatives:

- `Not a hole; no tip endpoint applies.`
- `A through exit allowance is negative; exit_mm must be >= 0.`
- `The blind tip or tap flute length exceeds the declared depth guard.` (both
  error sentences are joined when both apply)
- `Hole endpoints need the missing or unverified entry, tool geometry or depth inputs.`
- `Hole tip endpoints and blind-depth guards are computed from the advanced local entry surfaces.`

Citations: PLAN §4.1 tip endpoints, manifest hole geometry, stock-state and
operation depth/exit, selected inventory tool geometry. Whole-bar thickness is
never substituted for local hole thickness. A numeric nominal tip alongside
an unknown status is not a verified cut instruction.

## `speeds_feeds`

One subject per `setup:op`, including explicit not-applicable manual operations
(`inspect`, `deburr`, `coating`, `release`, `fit`, `scribe`, `file_to_line`). For spindle cuts,
tool chart citation wins over table rows; otherwise match material alias, tool
material, normalized action and inclusive mm diameter range. Exactly one cited
row is needed. Ambiguous overlap or unknown range stays unresolved. No chart
URL is fetched.

`D_in = D_mm/25.4`; `raw_RPM = 12*sfm/(pi*D_in)`. When a cited
`[[deep_hole]]` row names the operation and the hole's depth (the `blind_depth`
through-hole local thickness or blind `depth_mm`) is strictly more than its
`depth_over_dia` diameters, `sfm` is first multiplied by that row's
`sfm_factor`; the deepest exceeded threshold governs. An unknown depth or an
invalid, uncited or tied governing row leaves the RPM and feed unknown (see
[cutting data](cutting-data.md)). Round the raw RPM to nearest
50 with ties-to-even, then clamp to the actual machine limits (which need not
be multiples of 50). A spindle's `ranges_rpm` bands (each clipped to a stated
`rpm_min`/`rpm_max`) give those limits; an RPM in a gap between two bands
drops to the top of the band below, never a speed the spindle cannot select,
and any unknown band endpoint leaves the RPM unknown.

For `chain_drill`, depth is its feature's before-state `entry_z` (else the
before-state stock `top_z`) minus its authored `to_z`, converted from manifest
units to mm. Earlier face/pocket cuts advance that stock state only on their
normal coverage proof; a preceding chain drill never becomes the next start.
Approach air, drill-point extensions and exit leads are not added. Missing or
nonpositive penetration keeps a named deep-hole derate unresolved.

Mill feed in mm/min is `RPM * flute_count * chip_load_mm_per_tooth`. Lathe
feed in mm/min is `RPM * feed_mm_rev`: the op's planned `feed_mm_rev` when
declared (the feed `turning_deflection` loads the cut with; a planned
`"unknown"` stays unknown), else the one from the same
cited `[[cut]]` row (or the tool's cited `chart`) as `sfm`, under the same
citation/verify rules as the mill chip load; the lathe diameter is the turned
feature's `dia_nominal` (plus, for `rough_turn`, its `rough_allowance_mm`, else
`stock_to_leave_mm`; a negative leave makes the diameter unknown). A dome
uses its widest (base) diameter: `2 * base_radius`, else `2 * sqrt(h (2R - h))`
from its declared `sphere_radius` R and nominal height h (2R once h exceeds R),
else the kernel-measured base from `turned_profile.feature_span`. A face, cut to
fit or part off without a feature diameter uses the setup's `stock_state.od_mm`;
otherwise the diameter stays unknown. A spindle-axis tailstock action on a lathe
(`spot`, `drill`, `ream`, `tap`, `center`, `center_drill`) cuts at its own tool
diameter, as on a mill; a centre drill's is its pilot drill, matching the
Machinery's Handbook 27th ed. p.1132 centre-drill feeds by drill size. A mill op has no feed override. Lathe rows
report the `feed_mm_rev` evaluated, the one the sheet prints. Verified material,
tool and machine facts are needed.

For a `rough_profile` with `contour.method = "chain_drill"` and a tool whose
kind is `drill` or a `drill_index`/`drill_set` member, the normalized cutting
action is `drill`, not `profile`.
It selects the drilling `[[cut]]` row (or the drill's cited chart), without
requiring chart overrides or disguised end-mill rows. Its `feed_mm_min` is
axial feed; the traveler labels it **axial** and prints the feed per revolution
beside mm/min for hand feeding the quill. A drill on this `chain_drill` action
is centre-cutting by kind: its `plunge_mm_rev` is that same drilling chip load
times flute count, and `plunge_mm_min` equals its axial feed. End-mill
`[[plunge]]` rows and `center_cutting` declarations do not govern this action.
Other contour methods retain their declared centre-cutting/plunge semantics.

Every ordinary drill operation also reports `feed_direction = "axial"` and
`axial_feed_mm_rev` (chip load × flutes on a mill; the evaluated per-revolution
feed on a lathe). Its feed cell prints `axial 52 mm/min (0.025 mm/rev)`, for
example. An unresolved feed still prints `STOP`, never `axial STOP`.

A non-lathe end-mill op that cuts a `contour` also reports its plunge feed: `plunge_mm_rev`
from the one matching cited `[[plunge]]` row (material class, tool material, tool
diameter; see [cutting data](cutting-data.md#plunge)) for a tool declared
`center_cutting = true` (any other has none), `plunge_mm_min = RPM *
plunge_mm_rev`, and `plunge_reason` when it is unknown. It does not change the
finding's status: whether the op plunges at all is the coordinates rule's
`level_paths`, which makes a plunge without a known feed debt.

Saw cut-off uses only a cited canonical `operation = "saw_cut"` row (for either
`saw_cut` or `cut_off`), keyed by material class and blade material without a
diameter filter. Positive row `sfm` is linear blade speed, clamped to the
machine's `blade_speed_sfm`; row `feed_mm_min` is descent feed. It has no
spindle RPM, tooth-count calculation, tool-chart precedence or op override.
Missing/ambiguous/uncited data and machine/blade/material debt remain unknown.
See [cutting data](cutting-data.md) and [native saw geometry](rules-geometry.md#saw-cut-off).

Exact templates:

- `This manual operation has no cutting speed or feed.`
- `Starting RPM/feed cannot be certified: the selected row/chart, measured tool, material or machine range is missing or unverified.`
- `Starting RPM/feed cannot be certified: the hole depth or its governing deep-hole row is missing, ambiguous or unverified.`
- `Starting RPM and feed are sourced; raw RPM is rounded to nearest 50, then clamped to the actual machine range.`

Evidence: material/class and verification, normalized operation, tool material,
diameter in inches, flute count, sfm/chip load, range, RPM/feed and selected
source; an operation a deep-hole row names adds `depth_over_dia`,
`deep_hole_row` (the governing row's citation, or `not_applicable`) and
`deep_hole_sfm_factor`. Citations carry PLAN §3.5's RPM/rounding equation,
inventory spindle range, cutting aliases/rows, the actual selected chart/row
citation and any governing deep-hole row. The shipped example rows are
labelled illustrative example values, not shop measurements.
