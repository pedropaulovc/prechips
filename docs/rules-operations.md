# Operation chain, order, depth and cutting starts

Use these rules to interpret findings about prerequisite cuts, execution order,
hole endpoints and sourced starting speeds. Array order is execution order.
The rules do not mutate the bundle or infer missing stock state or cutting data.
Reports retain evidence and citations; setup sheets print plain-language
findings and the endpoints that can be established.

On this page:

- Route checks: [`op_chain`](#op_chain) and [`order`](#order).
- Native touch-plane extensions to [`zero_check`](rules-coordinates.md#zero_check):
  [component supplies](#component-supplied-touch-planes-zero_check),
  [multi-plane selection](#carried-multi-plane-touch-selection-zero_check),
  [same-setup survival](#same-setup-native-producer-survival-zero_check) and
  [touch land after a plunge](#usable-native-touch-land-after-a-plunge-zero_check).
- Cutting targets: [`blind_depth`](#blind_depth-tip-endpoints) and
  [`speeds_feeds`](#speeds_feeds).

For field definitions, use the [plan](plan.md), [features](features.md),
[inventory](inventory.md) and [cutting-data](cutting-data.md) references.
The [tutorial](manual/tutorial.md) and [demonstration](manual/demo.md) show how
to read a complete report. [Troubleshooting](manual/troubleshooting.md) covers
unresolved facts, and the [FAQ](manual/faq.md) explains why a checked plan is
not physical machining acceptance.

## `op_chain`

The rule produces one finding per feature. It checks route-wide prerequisites
for holes, threads, threaded holes and counterbores, including operations in
later setups. It also checks deterministic starts for contour/form operations,
including nonhole features.

### Hole prerequisites

A hole/thread/threaded-hole/counterbore route needs spot and drill operations.
A `process = "ream"` feature needs reaming; a thread needs tapping. A
counterbore needs its own counterbore operation and a drill on its named
`parent` or `hole` feature.

When the route taps, the selected drill diameter must match the explicitly
supplied `tap_drill_mm` thread specification, using verified selected-tool
geometry. Converted lengths are equal within absolute 1e-6 mm, with no
relative tolerance: `3/8` in and `9.525` mm agree. Unknown process or thread
specification leaves the chain unresolved. An explicitly unknown feature kind
or route action makes the finding unknown, even when `banded_starts` records
a known start error.

With known kind/actions, a complete applicable route passes. Missing
prerequisite operations or a known tap-drill mismatch are errors. A nonhole
with no contour-start issue is `not_applicable`; nonholes can receive the
start errors or unknowns described below, including unknown from
`unknown_starts` alone.

Typical sentences are:

- `{feature}: not a hole chain.`
- `{feature}: feature kind or hole-chain action is explicitly unknown.`
- `{feature}: hole prerequisites are present across the route.`
- `{feature}: thread tap-drill specification/measurement unresolved.`
- `{feature}: {errors}.`, with clauses such as `no drill operation`,
  `no spot operation`, `required ream operation absent`,
  `thread requires a tap operation`, `counterbore operation absent`,
  `counterbore has no parent hole drill` or
  `selected tap drill differs from thread specification`.

### Deterministic contour starts

A contour/form operation means one with a `contour` table or `do` starting
`form` or `profile`. The rule flags a numeric `z_from` that an earlier
operation in the same setup leaves only within a `to_z_band`:

`{sid} op {n} starts at Z {z}, which op {m} leaves anywhere in {lo} to {hi}; an op must leave that face at a deterministic to_z first`

The last earlier operation whose numeric `to_z` equals the start within
absolute 1e-6 mm, or whose band contains it, decides. Any intervening operation
with an equal deterministic `to_z` and no band ends the scan; this is not
limited to facing. An earlier operation with nonnumeric `to_z` is skipped,
even if it declares a band. A start with no earlier producer is outside this
check; absence of a banded-start finding does not prove that a starting face
exists.

An unknown band end prints `an unknown Z`; the operation's own numeric
`to_z` is still a banded face, so a start there records an error. Whether that
band contains a different start is unknown and appears under `unknown_starts`
as `…, which may hold it`. The scan continues through earlier operations:
an earlier band known to contain the start records an error even when a
later unknown band may also contain it. The explicit-unknown kind/action
precedence above still determines the finding's status.

Resolve missing prerequisite operations in the authored route, select the
specified measured tap drill, or add the actual deterministic face cut that
the later table requires. An acceptable dimensional band alone does not
supply a single Z origin for a table measured from that face.

Evidence includes feature kind, route operation ids/actions, expected and
selected tap-drill mm, `banded_starts` and `unknown_starts` when present.
Citations include PLAN §4.1 op chain, authored route and declared
process/thread. Implementation: [`op_chain.py`](../src/prechips/rules/op_chain.py).

## `order`

The rule produces one finding per setup. It evaluates the authored route
sequence, not numeric sorting of operation ids. The required relationships
are:

| Operation or route | Required order |
| --- | --- |
| Ream, tap or counterbore | Follow the prerequisite drill, using the parent/hole feature for a counterbore. |
| Drill and spot | A drill must not precede its only spot. An earlier spot already satisfies this relationship even if another spot follows. |
| Spot and facing | A spot follows facing when its setup contains `face` or `finish_face`. |
| Rough and finish | A `rough_*` operation must not follow the matching `finish_*` for that feature in the same setup. |
| Release or part-off | Follow all remaining cutting in the same setup. A later setup may cut the released part; later manual work in this setup does not violate the relationship. |

A finishing hole operation (`ream`, `tap` or `counterbore`) in another setup
must receive stock from the earlier drilled setup through its `stock_in`
ancestry. Legacy input with no `stock_in` may use a `zero.transfer.from`
that names an earlier drilled setup. Once `stock_in` is explicit, a datum
transfer from another blank cannot substitute for that material route.
This check establishes route order, not physical fixture continuity.

An unknown action in the current setup makes its order unknown. Otherwise
any violation is an error and a route with none passes. Correct the array
sequence or stock ancestry that the finding names; renumbering operation
ids without changing their array order does not change execution order.

The standard sentences are:

- `{setup}: rough/finish, face/spot, hole and release order is consistent.`
- `{setup}: operation order cannot be established while an action is explicitly unknown.`
- `{setup}: {violations}.`, with clauses such as
  `op {n} {action} precedes its drill`, `op {n} drills before its spot`,
  `op {n} spots before facing`, `op {n} roughs after finishing {feature}`,
  `op {n} releases before the final cutting operation` and
  `op {n} has no incoming route from the drilled setup`.

Evidence contains the authored sequence and violations. Citations include
PLAN §4.1, setup/operation sequence and `stock_in`/`zero.transfer`.
Implementation: [`op_order.py`](../src/prechips/rules/op_order.py).

## Component-supplied touch planes (`zero_check`)

This and the next three sections extend the canonical
[`zero_check` contract](rules-coordinates.md#zero_check); they do not create
separate rule ids. They explain when an exact native face can supply a
numeric contact setting and `credited_faces`. Plane selection, stock
presence, orientation, operation timing and usable contact area must all be
proved. A known nominal height alone does not supply touch credit.

### Component-local supply proof

A bounds-free native face can be touched in a later setup without a new
facing operation if its exact STEP face is in `stock.as_is_faces` and its
own component root proves that the surface arrives on that component.
The global as-is check validates the joined stock union only; a sleeve's
face cannot be credited to the body's branch from that union.

The supply must be an exact declared `stock.<component id>` on the validated
upstream route, consumed alone by its root setup. A joined root, undeclared
stock-like name, or literal `stock` alongside components is not
component-local proof. Ordinary single-stock seeding is unchanged.

All of these facts are required:

1. The root's `stock_state.top_feature` or `bottom_feature` names the touched
   feature. The corresponding pre-cut native `stock_faces_mm` side (`up` or
   `down`) has finite `face_z` and `stock_z`, equal within absolute 1e-6 mm.
   A reason, missing height or stock-height mismatch is unresolved debt.
2. Exact geometry-matched source native-plane facts resolve the selected
   STEP face, its source-frame Z and outward normal. That Z agrees with the
   pre-cut face height within the same physical tolerance. A model AABB or
   generic revolved geometry alone proves no arriving component material.
3. The same root's `render_scene` contains the exact named datum for the
   feature, with finite coplanar outline, matching outward normal and Z.
   Native datum emission requires the surface to be on that component's
   material. This separate proof is necessary because `stock_faces_mm` can
   retain a same-Z height when stock carries only part of the face.
4. The root has no entering- or retained-stock debt. The supplied plane
   must then pass the normal stock-DAG preservation and bounded-touch-area
   checks.

### Carrying the plane into the receiving setup

The render datum describes the root's material after its operations. It
cannot create an as-is supply when pre-cut proof is missing or mismatched.
A later joined or receiving solid's datum replaces neither root proof.
Unrelated roots that do not name the target remain unseeded, not proved
geometrically absent; they do not invalidate a separately proven supplier.
A named candidate lacking proof stays unknown. With no proven supplier,
the finding names the component and face as unknown instead of silently
treating the face as absent.

Rigid-frame rules carry the supplied plane. It is not reset to model-box
height or a later cut's nominal Z. A source `down` face can become receiving
+Z after a rigid flip, but credit still requires a finite +Z outward plane
and a known above/+Z touch in that receiving setup. Later cuts use the same
preservation, bounded exclusion and tool-change-touch rules as an
upstream-prepared face. Missing component proof produces neither a credited
face nor a numeric contact setting.

Resolve the component root, exact source face and stock proof named in the
finding. If the route actually prepares a new touch surface, author that
preparation rather than declaring an unsupported supplied face.
Implementation: [`zero_recipe/native.py`](../src/prechips/rules/zero_recipe/native.py).

## Carried multi-plane touch selection (`zero_check`)

A bounds-free named feature can include STEP planes at several Z heights.
The authored contact edge selects the native plane group; it does not
automatically select the feature box's highest member. The rule traces all
groups internally but credits only the uniquely selected group's exact raw
STEP references. An unprepared upper member does not prevent contact with
a separately prepared lower +Z member. A prepared maximum member remains
eligible under the same rules.

### Native and as-cut heights

Each group needs its exact raw native height in the receiving frame. Flat,
geometry-matched native boxes can supply that height; an oblique world box
cannot. An oblique plane needs its exact source native plane or named
stock-proven source datum rigidly transformed into the receiving frame.
Missing or inconsistent native-height proof remains unknown, without a
maximum-box or nearest-plane fallback.

An authored edge matches a group within absolute 1e-6 mm, for either
millimetre or inch manifests, at either:

- The exact transformed native height.
- Its traced eligible producer's actual as-cut height after source DRO-grid
  rounding and rigid-frame transformation.

These identify the same group, not two groups. Distinct native planes are
not merged merely because their heights are within the matching tolerance.
Exactly coplanar numerical planes can form one group and credit all its
references. If two distinct groups match through any combination of native
and eligible as-cut heights, selection is unknown. The rule never chooses
the nearest group or the one that happens to have a producer.

### Error and unresolved cases

With complete plane and eligible-height proof, no matching group on a
multi-plane feature is an error naming the authored edge and known candidate
heights. No numeric Axis Set is invented and no credited face is borrowed.
Missing eligible physical-height proof stays unknown; it does not prove
absence or complete the no-match comparison. An eligible whole-plane
producer with unknown formed height keeps that debt. A later genuinely
proved whole producer can replace its height proof but cannot erase earlier
unknown cut-area debt.

An independently proved non-+Z member is known ineligibility, not missing
physical proof, so it does not invalidate another uniquely selected valid
+Z group. It still participates in raw native matching and ambiguity. If
selected, its normal is rejected by the existing +Z contact rule. Unknown
intersecting cuts or touch-area debt on the selected group remain unresolved.

Selection alone establishes no stock presence, +Z orientation, touch side
or surviving land. The selected group still needs producer/supply, lineage,
rigid-frame, bounded-area and above-touch proofs, including component-root
facts where applicable. A matched but unfaced or wrong-facing member stays
unknown. A single native plane keeps its physical/native-edge contradiction
check and proved physical standing height.

Resolve the exact contact edge and the selected plane's preparation/survival
evidence. Do not replace an unknown edge with the box maximum or a rounded
nearby plane. For same-setup cuts, continue with the
[survival checks](#same-setup-native-producer-survival-zero_check).
Implementation: [`zero_recipe/native.py`](../src/prechips/rules/zero_recipe/native.py).

## Same-setup native producer survival (`zero_check`)

A whole-face producer proves a prepared plane at its cut, not survival until
a later contact. A framed producer in the touching setup, cut under that
setup's Z zero and with its own native plane, uses the same cut-by-cut
survival ledger as a carried producer.

### Contact operation boundary

The ledger runs from the producer through the contact's exact boundary:
`before_ops` excludes its first named operation; `after_op` includes the
named operation. Explicit tool touches, listed retouches and derived
tool-change touches all need survival proof before the sheet receives a
numeric contact or `credited_faces`.

An unresolved touch boundary is unknown. This includes empty or partly
unknown `before_ops`, unknown `after_op` and the primary `zero.z.after_op`.
The rule never silently reads such a contact against the plane before the
setup's first operation.

Invalid claims, unknown cutting actions or cut depths, ambiguous removal
bounds and unresolved plunge footprints leave contact unknown. Provably
disjoint cuts preserve the plane. An overlapping bounded plunge preserves
only the filled-rectangle land described in the
[next section](#usable-native-touch-land-after-a-plunge-zero_check).

A current producer retains its exact DRO-step/formed-Z comparison. Only a
nonzero local keep-off diameter is reported. It does not receive carried
safe-down rounding, native-entry remapping or a physical-setting residual.

### Window-limited turning cuts

A finite `z_from`/`z_to` turning window can prove that a cut cannot reach a
plane when all these conditions hold:

- It is a lathe turn with no `to_z`, not facing, pocketing, axial drilling,
  parting, cut-to-fit, transfer, saw or manual work.
- Setup Z is coaxial with the plane normal.
- The entire window is on the plane's open outward side within
  `LENGTH_TOLERANCE_MM`.

The kernel restricts removal to that window. The comparison uses both raw
ends and dialled ends rounded up on the setup DRO grid, whichever is worse.
A grooving/parting blade or unknown tool kind also needs known blade width:
the groove extends its full width upward from the dialled chuck-side end,
as the plunge model places it. Tilted frames, a window crossing the plane,
unknown width and other cut kinds still need the existing radial proof.

### Contradictions, recovery and limits

An authored-edge contradiction cannot re-fetch the original producer and
restore an invalidated contact. Recovery repeats survival proof and is
skipped while survival debt remains. Established contradictions retain
error precedence; missing survival remains unknown. An unproved plane may
be gone, so its old producer height neither credits nor contradicts a
reading.

Resolve the contact boundary, intervening cut definitions and surviving
land that the finding names. Reusing a producer's nominal Z does not prove
that the tool can still touch it. Pre-zero producers, latest-re-face area
debt and authored/non-native fallback surfaces retain their existing
behavior; their separate coverage boundary is recorded in
[issue #227](https://github.com/pedropaulovc/prechips/issues/227).
Implementation: [`zero_recipe/native.py`](../src/prechips/rules/zero_recipe/native.py).

## Usable native touch land after a plunge (`zero_check`)

A bounded axial plunge intersecting a current or carried face does not
preserve usable contact merely because its reach is smaller than an outer
radius. A remaining annulus can be too thin for paper/tool contact. Native
`revolved` radius extrema and an outward-plane normal also do not establish
circular or annular topology: a horizontal noncircular patch can have the
same facts. Sampled datum outlines and a model AABB do not supply that proof
or rule out an original hole.

### Supported rectangular witness

An overlapping plunge can preserve contact only through the existing exact
rectangular witness:

1. The selected native face is a single `Plane` with `fills_bbox = true`.
   This proves a filled, one-wire, straight-sided rectangle. Round, holed,
   notched and L-shaped faces do not qualify.
2. Its transformed box is flat in setup Z and axis-aligned in setup X/Y.
   `FILL_MARGIN_MM` and corner-tolerance shrink keep the witness inside the
   area proved filled.
3. The author-chosen `TOUCH_LAND_MM` code constant requires a 0.5 mm by
   0.5 mm square outside the bounded plunge exclusion. This is an
   illustrative checker limit, not a measured limit or shop-policy entry;
   its provenance is recorded in
   [`zero_recipe/touch.py`](../src/prechips/rules/zero_recipe/touch.py).
   The exclusion includes conservative engagement, location/aim and
   DRO-grid envelope, not nominal diameter alone.
4. Prior and current exclusions remain cumulative. A conservative square
   envelope about the rigidly carried source-plane centre encloses all
   removed radial regions. Its reach is the maximum of prior reach and
   current plunge radius plus centre offset. The `_uncut` witness must lie
   outside that entire envelope, not just the latest smaller cut.

Re-facing does not erase earlier unknown cut-area debt. The exclusion stays
about its own plane centre. A re-face with a different centre axis leaves the
earlier exclusion extent unknown if normals are nonparallel or origins
differ across the axis by more than `LENGTH_TOLERANCE_MM`; the rule does not
re-centre the old exclusion on a new face.

### Unresolved land and output

A missing filled-rectangle witness or no remaining 0.5-mm square leaves the
subsequent contact unknown. The usable-land debt names setup/operation and
contact face. A round or holed face remains unknown after an overlapping
plunge even with a large reported radius. Exact circle/annulus topology and
original-inner-hole proof are outside this supported path; see
[issue #208](https://github.com/pedropaulovc/prechips/issues/208). The rule
neither invents those facts nor adds a native schema field.

Initial contact before the plunge remains eligible when plane, stock
presence, outward normal, lineage and touch side are proved. Disjoint cuts
keep their existing preservation path. Supported rectangular contacts
report cumulative exclusion diameter, and the sheet rounds its exclusion
note outward. Unsupported contacts get neither a credited face nor a numeric
Axis Set.

Resolve the actual preparation/contact sequence or use a contact surface
whose required land can be proved. This result is a checker limitation and
stop, not a claim that no physical patch exists. A radius value or a note
asserting usable contact cannot replace the required witness.
Implementation: [`zero_recipe/native.py`](../src/prechips/rules/zero_recipe/native.py).

## `blind_depth` (tip endpoints)

The rule produces one finding per feature, with an `endpoints` array for
`spot`, `drill`, `ream`, `tap`, `counterbore` and `bore` operations, and for
`center_drill` on a plan [process](plan.md#process-features) `centre_hole`.
Nonhole features are `not_applicable`. An applicable feature without endpoint
rows remains unknown.

### Local entry and stock-state advancement

Facing and pocketing advance only named or explicitly covered same-frame
entry surfaces. Profiles never move the touched top, and `top_feature`
restricts which facing operation moves that top. A seeded local entry can
name the eventual hole-entry face rather than the raw boundary; another
feature's touched `top_z` does not replace it. Omitting local `entry_z`
retains the stock-state top fallback. Partial coverage keeps uncut entry;
unresolved coverage remains debt.

A known setup-frame `stock_removal_bounds` containing a target's whole X/Y
footprint can advance its seeded local entry without a duplicate bounds box
on the cutting operation's feature. For bounds-free `kind = "face"`, the
footprint is each listed plane at the operation's `to_z`, using its own
matched kernel `bbox_mm`. See [coordinates](rules-coordinates.md#coordinates).

Native face `at`/`dia`, axis or plane metadata is incidental geometry, not a
declared footprint. A smaller disc described by those fields cannot stand
in for the face even if it fits inside the cut. The complete face list must
resolve before a bounded cut selects its planes at `to_z`. Missing or
ambiguous mappings, invalid native boxes, unknown units or unresolved setup
frames leave coverage unknown and earn no face credit.

Explicit authored face `bounds` and true round non-face features keep their
declared-footprint behavior. Authored empty or whole-record unknown face
`bounds` is debt, not permission to use a disc or native-box fallback.
Malformed explicit bounds stay debt when containment cannot be established.

### Whole producers and bounded coverage

Unbounded cuts of their own feature keep declared-whole semantics. Their
keep-out checks use actual native boxes for bounds-free faces. For
cross-feature unbounded native faces without explicit target bounds,
containment leaves the producer unknown; it never creates a disc-based whole
producer. This does not advance a seeded local entry: the unboxed
entry-selection path still skips when it has no declared footprint candidate,
keeping the seed height and origin.

Bounded cross-feature facing/pocketing uses native coverage even if the
cutting feature has no authored footprint. Empty/unknown authored target
footprints also remain guarded producer candidates. Unresolved coverage
cannot become a skipped operation followed by an accepted numeric contact
edge. An explicit local-operation source must prove whole native coverage;
partial or unknown coverage cannot supply the face. A later bounded cut
with complete native boxes that are XY-disjoint is non-producing even at a
different floor, so it does not hide an earlier proved producer.

For an operation with `stock_removal_bounds`, its Z interval must contain
both current entry and `to_z`. A boxed cut cannot numerically raise entry.
A higher floor outside `SAME_Z` (1e-9 plan units), or a box wholly above/below
entry, leaves height and source unchanged. Unknown removal Z or entry stays
debt: X/Y coverage alone cannot establish entry height. An equal-Z boxed cut,
including float residue within `SAME_Z`, establishes its operation as producer
while keeping the lower numeric value of entry and `to_z`. These boxed
conditions do not change unboxed own-feature/explicit-footprint transitions.

Each endpoint retains entry origin, setup/operation, point/lead, thickness,
allowance and tip target. The effective native touch must survive to its own
contact boundary. If that touch has unknown physical edge or typed setting,
a known local-entry producer cannot recover numeric DRO/physical entry,
exit or endpoint values. The local-entry no-double-shift exception applies
only to a surviving numeric touch reading. Nominal stock-state dimensions
do not replace touch proof.

### Units and selected-tool geometry

Arithmetic is in mm. Stock-state top/entry coordinates and operation
`depth_mm` are machine millimetres even with an inch feature manifest.
Feature depth limits convert from manifest units. A tap without operation
depth uses the upper `thread_depth`, or `depth` only if no thread-depth field
exists. Explicitly unknown operation depth never falls back.

Drill-point length is:

`P = D / (2*tan(included_point_angle/2))`

It requires D > 0, 0 < angle < 180 degrees and finite cone length. An
underflowed zero tangent or nonfinite cone leaves point length unknown,
never a zero-length tip. A centre-seat angle is not drill-point geometry.

When a resolved centre-drill member is used to spot, carried-face touch
exclusion uses the endpoint's explicit operation `depth_mm`. Its pilot
radius expands by
`max(0, depth_mm - pilot_len_mm) * tan(angle_deg / 2)`, capped at
`shank_mm / 2`. Feature-only spot depth is not operation depth and leaves
preservation unknown. Missing, unknown or unverified engagement facts
remain debt. Located aim and DRO-grid shifts still enlarge the exclusion.

### Endpoint equations and depth guards

| Action | Endpoint and guard |
| --- | --- |
| Spot | `tip_z = entry_z - depth_mm`. Point length is recorded, not added to spot depth. |
| Through drill | `exit_face = advanced entry_z - local_thickness[feature]`; `tip_z = exit_face - P - exit_mm`. |
| Through ream | `tip_z = exit_face - lead_mm - exit_mm`. |
| Through bore/counterbore | `tip_z = exit_face - exit_mm`, with no drill-point or reamer-lead addition. Named-cutter tool-zero and reach still need verification; this is a nominal axial target, not certified cutter geometry. |
| Blind drill/ream/bore/counterbore | `total_depth = depth_mm + point_or_lead`; `tip_z = entry_z - total_depth`. Total must not exceed the feature's upper depth limit. Bore/counterbore add no point or lead. Unknown through/depth/tool geometry stays unknown. |
| Tap | `tip_z = entry_z - depth`; verified flute length must cover thread depth. |

A negative through `exit_mm` is an error, including for through reaming, and
that endpoint's `tip_z` is `unknown`: the tool would stop short of breakthrough,
so no stop is offered. The same through-endpoint path applies this guard to
bore/counterbore exits. Whole-bar thickness never substitutes for local hole
thickness.

### Centre-hole quill depth

For `center_drill` on a process `centre_hole`:

`depth_mm = drill_length_mm + (mouth_dia_mm - drill_dia_mm) / 2 / tan(countersink_angle_deg / 2)`

This is Table 6 drill length C, including the point, plus countersink depth
to the declared mouth. `tip_z = entry_z - depth_mm`; evidence includes
`countersink_depth_mm`, `drill_length_mm` and `depth_scale = "quill"`.
The tailstock quill feeds this cut, so the sheet prints depth past touching
the end on the quill scale, not carriage DRO Z.

Only the selected tool's own centre geometry can supply that depth.
`tool_centre` records the accepted facts used to construct the kernel cut:

- `drill_dia_mm` equals tool `dia` (Table 6 D).
- `drill_length_mm` equals tool `pilot_len` (Table 6 C, countersink start to
  point tip).
- `countersink_angle_deg` equals tool `angle_deg`, a centre-drill set's
  centre-seat angle that a member may override.
- Those comparisons use 1e-6 mm / 1e-9°.
- `mouth_dia_mm` does not exceed body `shank` (Table 6 A).
- The pilot's included `point_angle` produces finite
  `dia / 2 / tan(point_angle / 2)` shorter than `pilot_len`.

An underflowed zero tangent or nonfinite pilot point, countersink depth or
combined centre depth stays unknown. It authorizes neither native cutting
nor centre support. Finite Table 6 drill length C remains visible as its
own fact; it cannot replace unresolved countersink geometry.

The mouth must lie where the quill touches and feeds:

- `at`, transformed into the setup frame, lies on `entry_z` within 1e-6 mm.
- `axis` follows setup -Z feed.
- On a lathe, setup X = Y = 0 within 1e-6 mm puts the mouth on the spindle
  axis followed by the tailstock quill. Evidence records `mouth_z`.

A mismatch is an error. Unknown/unaccepted size, tool fact, mouth or entry
surface stays unknown with its measurement debt. The same applies to a tool
absent from inventory or an unconfirmed record (`verify` or an unknown flag
anywhere on it, as for other endpoints). Either nonpassing result leaves
`depth_mm` and `tip_z` unknown: the sheet prints no quill depth and the kernel
cuts no centre. [`centre_support`](rules-setup.md#centre_support) reads this
same preparation verdict for the maker.

### Kernel agreement and limits

The kernel uses the same spot/drill depth meanings. Spot depth is apex tip
depth. Drill depth is full-diameter depth, with its tip one point length
(`r / tan(angle/2)`) deeper. A spot endpoint here does not add its point,
but its included `point_angle` remains mandatory for the kernel cone.
Unknown angle creates accessibility and later-stock debt there; see
[accessibility](rules-geometry.md#accessibility).

These endpoint equations do not prove that a cap is formed. The kernel
separately requires the feature's last drill, ream, bore or counterbore to
leave claimed caps clear of setup stock. A flatter point, smaller pilot or
flat finishing floor above a modelled cone can therefore create named stock
debt. A spot on a through feature still uses its mouth depth, never the
through bore exit. These targets bound kernel reach and cutter/holder poses
as well as the sheet's endpoint column.

### Findings and remedy

Exact sentence alternatives include:

- `Not a hole; no tip endpoint applies.`
- `A through exit allowance is negative; exit_mm must be >= 0.`
- `The blind tip or tap flute length exceeds the declared depth guard.`
- `The centre is not the one its selected tool cuts from the touched entry surface: {reasons}.`
- `Bad input: {reasons}.`
- `Hole endpoints need the missing or unverified entry, tool geometry or depth inputs.`
- `Hole tip endpoints and blind-depth guards are computed from the advanced local entry surfaces.`

All applicable error explanations are joined, including both depth/exit
sentences when both apply. An established endpoint error takes precedence
over missing facts; otherwise unresolved endpoints stay unknown.

A finding with unresolved DRO-grid facts also appends
` DRO grid debt: {semicolon-separated debts}`. A row with `dro_grid_debt`
or unknown `dro_tip_z` is unresolved; grid debt does not turn an established
error into a pass or erase its explanation.

Correct the local entry/preparation, depth/exit declaration or selected-tool
geometry named in the finding. Preserve the drawing's limit when changing
the process. A nominal numeric tip beside an unknown verdict is not a
verified cut instruction.

Citations include PLAN §4.1 tip endpoints, manifest hole geometry,
stock-state, operation depth/exit and selected inventory tool geometry.
Implementation: [`tip_endpoints.py`](../src/prechips/rules/tip_endpoints.py).

## `speeds_feeds`

The rule produces one finding per `setup:op`. Manual actions (`inspect`,
`deburr`, `coating`, `release`, `fit`, `scribe`, `file_to_line`) receive
explicit `not_applicable` findings. Supported verified hand-saw cuts are
also exempt as described below. Spindle and powered-saw calculations pass
when their consumed facts are sourced and resolved; missing or ambiguous
facts produce unknown. A sourced starting value does not establish actual
cutting performance or physical acceptance.

### Source selection and RPM

For spindle cuts, a tool chart citation takes precedence over table rows.
Otherwise selection matches material alias, tool material, normalized
action and inclusive mm diameter range. Exactly one cited row is required.
Overlapping matches or unknown ranges remain unresolved. No chart URL is
fetched. Use the [cutting-data reference](cutting-data.md) for row fields and
citation requirements.

The RPM equations are:

- `D_in = D_mm/25.4`.
- `raw_RPM = 12*sfm/(pi*D_in)`.

Round raw RPM to nearest 50 with ties-to-even, then clamp to actual machine
limits, even if a limit is not a multiple of 50. Spindle `ranges_rpm` bands,
each clipped to stated `rpm_min`/`rpm_max`, define selectable speeds. A
rounded RPM in a gap drops to the top of the band below, never to an
unselectable speed. Any unknown band endpoint leaves RPM unknown.

Verified material, tool and machine facts are required. Missing/unverified
source rows, charts, geometry or machine ranges cannot be replaced by a
remembered cutting value.

### Deep-hole derating

A `[[deep_hole]]` row names a normalized action. Every row naming that action
must have a positive `depth_over_dia`, `0 < sfm_factor <= 1` and a usable
citation, including rows that would not govern or whose threshold is not
exceeded. Any malformed or uncited matching row leaves RPM and feed unknown.

Depth is `blind_depth` local thickness for a through hole or blind
`depth_mm`. A row applies only when depth/diameter is strictly greater than
its threshold. Before RPM calculation, multiply sfm by `sfm_factor` from the
deepest exceeded threshold. Unknown depth, tied governing thresholds or an
unverified governing row also leave RPM and feed unknown. With valid rows
and no exceeded threshold, the factor is 1 and `deep_hole_row` is
`not_applicable`.

For `chain_drill`, penetration is the feature's before-state `entry_z`, else
before-state stock `top_z`, minus authored `to_z`, converted from manifest
units to mm. Earlier facing/pocketing advances the state only with its
normal coverage proof. Earlier chain drilling does not become the next
start. Approach air, drill-point extensions and exit leads are excluded.
Missing or nonpositive penetration leaves a named derate unresolved.

### Mill and lathe feeds

Mill feed in mm/min is `RPM * flute_count * chip_load_mm_per_tooth`.
A mill operation has no feed override.

Lathe feed in mm/min is `RPM * feed_mm_rev`. A declared operation
`feed_mm_rev` wins; this is the same planned feed loaded by
`turning_deflection`. Explicit `"unknown"` stays unknown. With no operation
feed, use the same cited `[[cut]]` row or tool `chart` as sfm, under the same
citation/verification rules as mill chip load. Whichever source supplies it,
the finding's evaluated `feed_mm_rev` is the value printed on the sheet.

Turning diameter comes from feature `dia_nominal`. For `rough_turn`, add
`rough_allowance_mm`, else `stock_to_leave_mm`; negative leave makes the
diameter unknown. A dome uses its widest base diameter, in this order:

1. `2 * base_radius`.
2. `2 * sqrt(h (2R - h))` from `sphere_radius` R and nominal height h, using
   2R once h exceeds R.
3. Kernel-measured base from `turned_profile.feature_span`.

Facing, cut-to-fit or parting without feature diameter uses setup
`stock_state.od_mm`. Otherwise diameter stays unknown. Spindle-axis lathe
tailstock actions (`spot`, `drill`, `ream`, `tap`, `center`, `center_drill`)
use their own tool diameter, as on a mill. A centre drill uses pilot drill
diameter, matching Machinery's Handbook 27th ed. p.1132 centre-drill feeds
by drill size.

### Chain drilling and axial feed

A `rough_profile` with `contour.method = "chain_drill"` and a `drill` or
`drill_index`/`drill_set` member normalizes to cutting action `drill`, not
`profile`. It selects the drilling `[[cut]]` row or drill chart, without
requiring chart overrides or an end-mill row.

Its `feed_mm_min` is axial feed. The sheet labels it `axial` and prints feed
per revolution beside mm/min for hand feeding the quill. A drill on this
chain-drill action is centre-cutting by kind: `plunge_mm_rev` is drilling
chip load times flutes and `plunge_mm_min` equals axial feed. End-mill
`[[plunge]]` rows and `center_cutting` declarations do not govern that action.
Other contour methods keep their declared centre-cutting/plunge semantics.

Ordinary drills also report `feed_direction = "axial"` and
`axial_feed_mm_rev`: chip load × flutes on a mill, evaluated per-revolution
feed on a lathe. The printed form is, for example,
`axial 52 mm/min (0.025 mm/rev)`. That is a formatting example, not a
recommended cutting value. Unresolved feed prints `STOP`, never `axial STOP`.

### End-mill contour plunge feed

A non-lathe end-mill contour operation also reports `plunge_mm_rev` from the
one matching cited `[[plunge]]` row, selected by material class, tool material
and tool diameter. It needs `center_cutting = true`; another declaration
supplies no plunge feed. `plunge_mm_min = RPM * plunge_mm_rev`, with
`plunge_reason` when unknown. See [plunge data](cutting-data.md#plunge) for
the supported tool kinds and the known gap in kind enforcement.

This extra feed does not change the `speeds_feeds` verdict. The coordinates
rule's `level_paths` decides whether the operation plunges, and makes a
plunge without known feed unresolved debt. A passing RPM/feed row alone
therefore does not authorize an unresolved contour entry.

### Powered saws and hand saws

Saw cut-off uses a cited canonical `operation = "saw_cut"` row for either
`saw_cut` or `cut_off`, keyed by material class and blade material without
a diameter filter. Positive sfm is linear blade speed, clamped to machine
`blade_speed_sfm`; `feed_mm_min` is descent feed. There is no spindle RPM,
tooth-count calculation, tool-chart precedence or operation override.
Missing, overlapping or uncited data, and machine/blade/material debt,
remain unknown.

A verified `kind = "hand_saw"` has no blade speed or machine feed. Its
finding is `not_applicable`, citing tool kind. This is selected-tool scope
per operation, not action-wide scope: a hand saw beside a powered cut still
has no machine feed; a bandsaw blade or unresolved/unverified tool retains
the blade-speed screen. See [hand saw on the bench](plan.md#hand-saw-on-the-bench-straight-or-to-a-scribed-line).

A vertical-mode bandsaw cut that `follows` a scribed line keeps sourced,
clamped blade speed but no descent feed. Hand feeding makes `feed_mm_min`
`not_applicable`; its absence creates no feed debt. Native stock preservation
is covered separately by [saw geometry](rules-geometry.md#saw-cut-off).

### Findings, evidence and remedy

Exact spindle, manual and hand-saw sentence templates include:

- `This manual operation has no cutting speed or feed.`
- `A hand saw has no blade speed or machine feed.`
- `Starting RPM/feed cannot be certified: the selected row/chart, measured tool, material or machine range is missing or unverified.`
- `Starting RPM/feed cannot be certified: the hole depth or its governing deep-hole row is missing, ambiguous or unverified.`
- `Starting RPM and feed are sourced; raw RPM is rounded to nearest 50, then clamped to the actual machine range.`

Resolve the selected row/chart, material, diameter, tool verification,
spindle range or deep-hole fact named in the finding. If no supported source
exists, the starting value stays unknown. The shipped example rows are
labelled illustrative values, not shop measurements.

Evidence includes material/class and verification, normalized action, tool
material, diameter in inches, flute count, sfm/chip load, range, RPM/feed and
selected source. A named deep-hole action adds `depth_over_dia`,
`deep_hole_row` (governing citation or `not_applicable`) and
`deep_hole_sfm_factor`. Citations include PLAN §3.5 RPM/rounding, inventory
spindle range, cutting aliases/rows, the selected chart/row and any governing
deep-hole row. Implementation:
[`speeds_feeds.py`](../src/prechips/rules/speeds_feeds.py).
