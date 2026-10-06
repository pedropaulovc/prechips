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

## `blind_depth` (tip endpoints)

One subject per feature, with an `endpoints` array for spot, drill, ream, tap,
counterbore and bore operations.
Stock-state facing/pocketing advances only the named or explicitly covered
same-frame entry surfaces. Profiles never move the touched top; `top_feature`
restricts which facing operation moves that top. Each record preserves entry
origin, setup/op, point/lead, thickness, allowance and tip endpoint.

Arithmetic in mm: stock-state top/entry coordinates and operation `depth_mm`
are machine millimetres even when the feature manifest uses inches. Feature
depth limits are converted from the manifest's units. A tap without an
operation depth uses the upper `thread_depth`, or `depth` if no thread-depth
field is present; an explicitly unknown operation depth does not fall back.

- Drill point `P = D / (2*tan(included_point_angle/2))`, requiring D > 0 and
  0 < angle < 180 degrees. Centre-seat angle is not drill point geometry.
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
(`inspect`, `deburr`, `coating`, `release`, `fit`, `scribe`). Tool chart citation
wins over table rows; otherwise match material alias, tool material, normalized
action and inclusive mm diameter range. Exactly one cited row is needed.
Ambiguous overlap or unknown range stays unresolved. No chart URL is fetched.

`D_in = D_mm/25.4`; `raw_RPM = 12*sfm/(pi*D_in)`. Round the raw RPM to nearest
50 with ties-to-even, then clamp to the actual machine limits (which need not
be multiples of 50). Mill feed in mm/min is
`RPM * flute_count * chip_load_mm_per_tooth`. Lathe nominal RPM can be computed
from explicit work diameter, but lathe feed remains unknown, so this rule does
not certify lathe starts. Verified material, tool and machine facts are needed.

Exact templates:

- `This manual operation has no cutting speed or feed.`
- `Starting RPM/feed cannot be certified: the selected row/chart, measured tool, material or machine range is missing or unverified.`
- `Starting RPM and feed are sourced; raw RPM is rounded to nearest 50, then clamped to the actual machine range.`

Evidence: material/class and verification, normalized operation, tool material,
diameter in inches, flute count, sfm/chip load, range, RPM/feed and selected
source. Citations carry PLAN §3.5's RPM/rounding equation, inventory spindle
range, cutting aliases/rows and the actual selected chart/row citation. No
verified example cutting numbers or Handbook page is implied by shipped rows.
