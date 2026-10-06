# Plan format — `plan.toml`

`part`, `features`, and `setups` are required. The loader additionally requires
a nonempty setup list, known unique setup ids, a nonempty operation list per
setup, known unique operation numbers within each setup, and every operation's
feature in the manifest. Plan and manifest part names must agree; a known setup
frame must name an exported manifest frame or a plan-owned frame in
[`frames`](#frames). A literal `"unknown"` setup frame stays unresolved.
Execution follows authored array order, not numeric sorting of operation ids.

`features` is relative to the plan; it must stay inside the bundle root. The
root is the repository above `examples` or the first ancestor with
`pyproject.toml`, otherwise the plan's parent. Shared input precedence is CLI
override, then a known `[paths]` declaration, then `PRECHIPS_INVENTORY` or
`PRECHIPS_POLICY`; cutting data has no environment fallback. An omitted or
literal `"unknown"` declaration permits the environment fallback. Missing policy
uses the shipped required-rule vocabulary only when no known path is selected.
Plan-declared shared paths must stay inside
the bundle root; explicit CLI/environment shop paths may be external. STEP references are read and hashed, contained
inside the bundle, and checked against a known `step_sha256`. M4 geometry rules
hand that STEP, once its bytes match the manifest digest, to one FreeCAD job per
run; an unknown digest, a missing `step`, or mismatched bytes keeps all eight
geometry rules `?`. See [geometry rules](rules-geometry.md).

Use `[[setups]]` and `[[setups.ops]]`. `stock_state` records received surfaces in
the setup frame; `local_thickness` is per hole, not the whole bar thickness.
`top_feature` identifies the touched face that facing advances. `entry_z` permits
a separate local entry surface. `zero.transfer` describes a pickup from another
setup, and `tool_touches` explicitly records tool changes. Neither invents a
measured trial-cut diameter.
Every zero recipe's `edge_mm` is the authored pickup coordinate in the setup
frame. A Z recipe with `face = "top"` uses the stock state's top; other named
faces require their own explicit `edge_mm`, not the stock top or a value copied
from report output. X/Y raw-overhang pickups likewise use their authored edges.
The Z pickup's `retouch_after` may declare a known operation list or `"unknown"`.
Omission and literal `"unknown"` leave the schedule unresolved, so a required
`zero_check` cannot pass merely because no rows were declared. An explicit
`retouch_after = []` means a known empty schedule; a known nonempty list produces
retouch rows using the stock top after each listed operation, including a face
cut that changes the touched top. A known list does not certify that the authored
schedule is physically sufficient.

`checks` maps exported requirement names to inventory gauge references.
Every key must belong to the selected feature's exported `requirements` list;
otherwise loading raises `BadInput`, even if another feature exports that name.
A wholly unknown requirements list cannot establish membership and does not
authorize arbitrary checks. `inspection_methods` supplies the authored procedure
for datum/geometric checks and missing requirements. A missing check is different
from `checks.dia = "unknown"`.

When an inspection requirement has no exported owner/band, an explicit operation
may declare `missing_requirements = { length = "calipers" }` and
`inspection_methods.length`. This uses the same gauge-reference mapping type as
`checks`, but produces a named unknown inspection row with
`missing_requirement = true`, not an acceptance band or a dimensional pass.
The sheet prints `?`, the exact missing requirement identity and the authored
procedure; reference-only dimensions such as `length_ref` are not substitutes.
A name already in that feature's exported requirements is `BadInput` in
`missing_requirements`; use `checks` so actual requirements cannot be bypassed.

`to_z` is an authored endpoint;
`to_z_band` is a range, not a substitute for measured setup binding. An
`arc_table` contour needs explicit nominal geometry and positive angular steps;
finite bounds come from that geometry, not an invented full circle. Linear
pockets may declare `sweep_bounds`, `sweep_frame`, and `open_side`.

All five inputs are UTF-8 TOML, parsed by `tomllib` and strict Pydantic 2
models in `src/prechips/model.py`. Unknown keys are forbidden at every modeled
record (`extra="forbid"`); arbitrary keys are allowed only in explicitly declared
dictionaries (for example feature identities or `checks`). Floats must be finite;
booleans are not numeric substitutes. `Number` means a numeric float or the literal
`"unknown"`; `Vector` means a list of Numbers or `"unknown"`; `Citations` means
a string or a list of strings. Text fields also accept `"unknown"`.

Every `record()` field below is optional and accepts `"unknown"` in addition to
the displayed type. The schema defaults omitted `Setup.machine` and
`Operation.do` to `"unknown"` and retains those keys in the loaded bundle so
rules can report unresolved identity/applicability rather than crash. Other
omitted fields stay absent: `zero_check` reads an omitted `retouch_after` as
unknown rather than an empty list, and other rules retain optional-field
applicability semantics.
Root fields marked required must be present. A model accepting a value is not proof
of geometric validity; rules perform the applicable checks.

## Root fields

| Field | Type | Presence |
|---|---|---|
| `part` | `str` | Required |
| `features` | `str` | Required |
| `construction` | `Literal['one_piece', 'built_up'] \| Unknown` | Optional |
| `step` | `str \| Unknown` | Optional |
| `quantity` | `int \| Unknown` | Optional |
| `quantity_cite` | `Citations` | Optional |
| `drawing` | `Drawing \| Unknown` | Optional |
| `paths` | `Paths \| Unknown` | Optional |
| `stock` | `Stock \| Unknown` | Optional |
| `dro` | `Dro \| Unknown` | Optional |
| `frames` | `dict[str, PlanFrame] \| Unknown` | Optional |
| `setups` | `list[Setup]` | Required |

## Frames

`[frames.<name>]` declares an author-owned setup frame for a setup transform the
CAD export does not carry. Its fields are the manifest
[`Frame`](features.md#frame) fields, with the same three-component,
orthonormal, right-handed basis checks: `origin` and `x/y/z` are in the model
frame. Two fields that the manifest may omit are required here, because the
plan, not the CAD export, owns the choice:

- `binding` must be stated, if only as `"unknown"`. `"nominal"` lets the
  transform place model geometry in setup coordinates; `"unknown"` keeps the
  numeric transform for display while operation Z endpoints stay setup-local.
- `cite` must be non-empty. The bundled examples begin it, and the `note`, with
  `AUTHOR'S CHOICE` before the drawing/model citations the transform rests on.

A setup's `frame` resolves to the exported manifest frame of that name, otherwise
to the plan frame. A plan frame whose name is already exported (including an
exported `"unknown"` frame such as `setup`) is bad input, so a plan can never
shadow CAD-owned geometry. Feature `frame` references and `sweep_frame` stay
manifest-only. Plan frames are never merged into the manifest or its hash; rule
citations carry `plan.frames.<name>: author-declared setup frame` followed by
the frame's own `cite`, while exported setup frames keep their manifest
provenance.

## Drawing

| Field | Type (also accepts `"unknown"`) |
|---|---|
| `number` | `str` |
| `revision` | `str` |
| `cite` | `Citations` |

## Paths

| Field | Type (also accepts `"unknown"`) |
|---|---|
| `inventory` | `str` |
| `policy` | `str` |
| `cutting_data` | `str` |
| `step` | `str` |

## Stock

| Field | Type (also accepts `"unknown"`) |
|---|---|
| `form` | `str` |
| `material` | `str` |
| `drawing_material` | `str` |
| `note` | `str` |
| `supply_datum` | `str` |
| `prerequisite` | `str` |
| `dia_mm` | `float` |
| `length_mm` | `float` |
| `north_allowance_mm` | `float` |
| `south_grip_mm` | `float` |
| `supply_length_mm` | `float` |
| `material_verify` | `bool` |
| `form_verify` | `bool` |
| `on_hand` | `bool` |
| `material_cite` | `Citations` |
| `section_mm` | `Vector` |
| `origin_mm` | `Vector` |
| `axis` | `Vector` |
| `section_axis` | `Vector` |
| `as_is_faces` | `list[str]` |
| `components` | `list[StockComponent]` |
| `cite` | `Citations` |

For a built-up stock candidate, `components` lists the separately authored
blanks. Each `StockComponent` requires a known, nonempty, unique `id`;
references match the exact id, with no ASCII character whitelist. It accepts `form`,
`dia_mm`, `length_mm`, `section_mm`, `origin_mm`, `axis`, `section_axis`, `note`,
and `cite` with the same types and model-frame pose semantics as root stock.
A round blank uses diameter and length; a rectangular blank uses two section
dimensions and length. These are authored purchase/process choices, not
confirmed on-hand inventory. Missing dimensions or citations keep comparison
waste unresolved; finished volume comes only from the manifest's explicitly
sourced `volume_mm3`, never a bounding-box estimate.

M4 requires an explicitly placed envelope, not a finished-part bounding-box
substitute. `origin_mm` is in the model frame: the rectangular blank's corner
or the round blank's starting-face centre. `axis` is the unit length direction.
For a rectangular blank `section_axis` is the perpendicular unit direction
of `section_mm[0]`; `axis × section_axis` carries `section_mm[1]`. The box is
the product of those three positive intervals; a round blank is the declared
diameter cylinder along `axis`. Dimensions/placement describe authored material,
not measured stock on hand. Each built-up component must contain only its own
piece, not the full finished STEP. Missing component dimensions or placement
remain individual stock debt; a known component does not resolve another one.
Known component branches remain usable when another component's geometry is
missing. When every component envelope is known, their full union must contain
the finished STEP; failure leaves all component references with geometry debt.
A nonempty root `as_is_faces` declaration applies to the full joined supply
exterior and therefore requires every component envelope to be known; this
global declaration can withhold otherwise-known branches. Empty or omitted
`as_is_faces` adds no such cross-component dependency.
Incompatible as-is surfaces also keep stock-dependent geometry `?` with a reason.
`as_is_faces` never creates a stock solid by itself.

`as_is_faces` lists STEP face references (same forms as a feature's `faces`)
that stay as supplied stock; the M4 `coverage` rule unites them with the faces
claimed by cutting operations. An omitted list is unknown, not empty.

Root `construction` declares the candidate route, independently of the
drawing-side manifest permission. `built_up` is refused unless
`features.construction = "built_up_permitted"`: unknown or omitted drawing
permission does not lift the one-piece-only restriction. An explicit `one_piece`
candidate needs no such permission. Omitting the **plan's** candidate construction
is unknown rather than an implicit one-piece declaration.
See [stock-form comparison](rules-comparison.md).

## Dro

| Field | Type (also accepts `"unknown"`) |
|---|---|
| `controller` | `str` |
| `manual` | `str` |
| `manual_url` | `str` |
| `mode` | `str` |
| `units` | `str` |
| `radius_mode` | `bool` |
| `direction` | `Direction` |

`radius_mode` selects the lathe X display convention: radial physical X jogs
read once in radius mode and twice in diameter mode. It does not change a known
mill's linear axes. In a mixed-machine route, the traveler labels the actual
setup machine's display convention rather than applying the lathe label to all
setups. Unknown controller/install facts remain unresolved independently.

## Direction

| Field | Type (also accepts `"unknown"`) |
|---|---|
| `x` | `str` |
| `y` | `str` |
| `z` | `str` |

## Setup

| Field | Type (also accepts `"unknown"`) |
|---|---|
| `id` | `str` |
| `machine` | `str` |
| `frame` | `str` |
| `coolant` | `str` |
| `stock_in` | `str \| list[str]` |
| `note` | `str` |
| `deburr_mm` | `Number` |
| `deburr_cite` | `Citations` |
| `stock_state` | `StockState` |
| `hold` | `Hold` |
| `zero` | `Zero` |
| `ops` | `list[Operation]` |

`stock_in` names `"stock"` for a single supply, `"stock.<id>"` for a built-up
component, or any earlier setup's `id` (not necessarily the immediately previous
setup). A nonempty array of these references joins their solids by Boolean union
in model coordinates. Unknown or forward authored references are bad input
(exit 3), including authored `"unknown"` as a source. Omitted `stock_in`
remains stock debt; it does not infer a linear route. Every supply and setup output stays in the model frame:
joining references never applies an implicit assembly transform.
Array entries must have disjoint supply ancestry: repeated references or joining
a supply with its descendant (for example `["stock", "S1"]` when S1 consumes
stock) are bad input (exit 3), naming the shared supply ancestor. Separate route
alternatives may start from the same supply again, but cannot join that material
lineage twice.

## StockState

| Field | Type (also accepts `"unknown"`) |
|---|---|
| `top_feature` | `str` |
| `note` | `str` |
| `top_z` | `float` |
| `bottom_z` | `float` |
| `retained_rail_bottom_z` | `float` |
| `od_mm` | `float` |
| `north_end_z` | `float` |
| `south_end_z` | `float` |
| `plain_end_z` | `float` |
| `bottom_z_cite` | `Citations` |
| `local_thickness` | `dict[str, Number]` |
| `local_thickness_cite` | `dict[str, Citations]` |
| `entry_z` | `dict[str, Number]` |

For lathe stick-out, `north_end_z` / `south_end_z` and `hold.stickout_mm` bound
the unsupported span. Its D is the smallest finished feature diameter in that
span after transformation into setup Z; `od_mm` remains the held-stock diameter
for collet/chuck capacity, not the unsupported-section diameter.

## Hold

| Field | Type (also accepts `"unknown"`) |
|---|---|
| `fixture` | `str` |
| `jaws_along` | `str` |
| `fixed_jaw` | `str` |
| `parallels` | `str` |
| `supports` | `str \| list[str \| Reference]` |
| `support` | `str` |
| `support_orientation` | `str` |
| `grip_on` | `str` |
| `stop` | `str` |
| `clamp` | `str` |
| `note` | `str` |
| `centre_lubrication` | `str` |
| `riser` | `str` |
| `method` | `str` |
| `orientation` | `str` |
| `locator` | `str` |
| `release` | `str` |
| `jaw_protection` | `str` |
| `locate` | `str` |
| `grip_mm` | `Number \| Literal['not_applicable']` |
| `jaw_above_parallels_mm` | `Number \| Literal['not_applicable']` |
| `stickout_mm` | `Number` |
| `jaw_center_along_mm` | `Number` |
| `parallels_centres_mm` | `list[[Number, Number]]` (exactly two) |
| `parallels_along` | `str` (`x` / `y`; parallels under a non-vise hold) |
| `riser_up` | `str` (riser dimension standing vertical: `length` / `width` / `height`) |
| `riser_along` | `str` (riser dimension along `jaws_along`) |
| `riser_centres_mm` | `list[[Number, Number]]` (at least one) |
| `chuck` | `str` (the chuck a `dividing_head` carries) |
| `pose` | `Pose` |
| `jaw_clock_deg` | `Number` |
| `support_tip_mm` | `[Number, Number, Number]` |
| `quill_extension_mm` | `Number` |
| `clamps` | `list[ClampPlacement]` |
| `grip_mm_verify` | `bool` |
| `jaw_above_parallels_mm_verify` | `bool` |
| `index` | `Index` |

`Pose` is `{origin_mm, x, z}`, each `[Number, Number, Number]` in setup-frame
mm: a fixture-local frame's origin and unit, orthogonal x and z axes. A
`ClampPlacement` is `{ref, note, pose}`: `ref` names a fixture or a
`kit/member` such as a clamping-kit strap, and its authored `solids` are
placed by `pose` (origin at the strap underside on the work).

M4 vise geometry consumes `fixture`, `parallels`, `fixed_jaw`, `jaws_along`,
`grip_mm` and `jaw_above_parallels_mm` to place the jaw solids in the setup
frame: `jaws_along` is the jaw length axis (`x` / `y`), `fixed_jaw` picks the
jaw on the negative or positive side of the other axis, `grip_mm` is the depth
of part inside the jaws and `jaw_above_parallels_mm` the jaw plate standing
above the parallels. A `grip_mm_verify = true` or
`jaw_above_parallels_mm_verify = true` flag makes that number unknown to the
kernel; `jaw_above_parallels_mm = 0` is a known zero, any other nonpositive or
unknown value is debt. Together with the vise's explicit `jaw_height`,
`jaw_width`, `jaw_depth` and `opening` and the parallels' `height`, these are
the facts behind the jaw solids and the setup findings. When any is
missing, the setup's `vise` and `thin_wall_under_clamp` findings stay `?`
and the render, if any, is a part-only view labelled as unresolved.

Two optional authored pose fields complete the picture. `jaw_center_along_mm`
is the centre of the jaw plates along `jaws_along` in setup-frame
coordinates; without it the kernel draws only the jaw material certainly over
the gripped part and a pale envelope for where the rest of each jaw may lie,
and cutter samples inside that envelope stay `?`. `parallels_centres_mm` is
exactly two `[x, y]` setup-frame centres of the parallels; together with the
parallels row's fact-local `height`, `length` (along the jaws) and `width`
(along the clamp axis) they place two parallel solids with tops at the stock
seat. Nominal numbers are usable for geometry, not evidence of a measured
shop setup. Both poses are declarations the author must measure at the bench; the
kernel never infers a jaw centre or a parallel position, and only a setup
with both exact jaws and exact parallels is captioned as a modeled fixture.
Either field may be `"unknown"` (any unknown coordinate is a render debt, not
a guessed pose) and neither has a `_verify` flag: they are author coordinate
choices, while each parallel dimension has its own fact-local trust; the
inventory item's `verify` does not taint other numeric facts. Omitting the
optional poses does not block independent `vise` / `thin_wall_under_clamp`
facts. Missing parallel height still leaves the fixture dimensions unknown.

Other holding kinds are drawn from their own declarations, never defaulted.
A `chuck_3jaw` / `chuck_4jaw` (and the chuck a `dividing_head` names with
`chuck`) is placed by `pose` (origin at the jaw-face centre, +z toward the
work) with jaw 1 at `jaw_clock_deg` from pose x; its jaws close on the
setup-entry stock inside `grip_mm` behind the jaw face. A `dead_centre`
`support` is drawn from its tip at `support_tip_mm`, its quill
`quill_extension_mm` beyond the centre shank. An angle plate, custom fixture
or dividing head draws its inventory `solids` placed by `pose`, and each
`clamps` entry draws its member's `solids` at its own pose; a strap must bear
on the stock top. `riser`, `riser_up`, `riser_along` and `riser_centres_mm`
stand a vise's parallels on riser blocks (a `blocks_123` `supports` item is
the riser when `riser` is absent). Non-vise holds that declare no jaws set
`fixed_jaw = "not_applicable"`; one without a gripped depth also sets
`grip_mm = "not_applicable"`.

## Index

The `hold.index` record is strict: only the fields below are accepted.
Each field is optional and also accepts literal `"unknown"`; arbitrary keys
are bad input (exit 3 before output).

| Field | Type (also accepts `"unknown"`) | Meaning |
|---|---|---|
| `fixture` | `str` | Selected dividing-head identity in inventory. |
| `feature` | `str` | Feature owning the angular landing allowance. |
| `angle_deg` | `Number` | Authored step declares an open pattern with no closure; omitted with `positions >= 2` declares a full pattern at exact `360 / positions`. Explicit `"unknown"` stays unresolved. |
| `positions` | `int` | Number of checked landings; `1` is a single setting. Closure requires both `positions >= 2` and omitted `angle_deg`. |
| `rotation` | `"continuous"` | The head turns freely under rotary ops (`approach = "rotary"`); declares no `positions` or `angle_deg`, so there are no plate landings. |

`feature` selects the journal/pattern's angular tolerance. An omitted selector
or absent feature allowance falls back to `general_tolerances.angular_deg`;
an explicitly unknown selector or allowance stays unresolved. Angles are degrees
and `positions` counts angular settings, not drilled holes inferred from a part
name. Exactness uses the authored TOML angle value, not rounded sheet text.
For a full pattern (`positions >= 2` with `angle_deg` omitted), the step is
exactly `360 / positions`, and both every landing and cycle closure are checked.
An authored `angle_deg` with `positions >= 2` declares an **open pattern**:
every position is checked against `angle_tol_deg`, but closure is not applicable,
even when the authored steps happen to total a whole revolution. Explicit
`"unknown"` is not omission. `positions = 1` is one explicit angular setting
with no closure. The traveler prints plate, circle, turns and hole **spaces**,
with angles at the drawing's declared angular precision.

For rotary milling, use
`hold.index = { fixture = "<head>", rotation = "continuous" }` instead of a
landing pattern. A verified `dividing_head` passes indexing with no landings;
another fixture kind or simultaneous `positions`/`angle_deg` is an error,
and an unverified head remains unknown. This declares how the head is used,
not proof that its rotation is collision-free or its torque/locking adequate.

## Reference

| Field | Type (also accepts `"unknown"`) |
|---|---|
| `ref` | `str` |
| `orientation` | `str` |
| `note` | `str` |
| `height_mm` | `float` |

## Zero

| Field | Type (also accepts `"unknown"`) |
|---|---|
| `x` | `AxisZero` |
| `y` | `AxisZero` |
| `z` | `AxisZero` |
| `transfer` | `Transfer` |
| `tool_touches` | `list[ToolTouch]` |

## AxisZero

| Field | Type (also accepts `"unknown"`) |
|---|---|
| `edge` | `str` |
| `feature` | `str` |
| `face` | `str` |
| `method` | `str` |
| `tool` | `str` |
| `holder` | `str` |
| `gauge` | `str` |
| `from` | `str` |
| `edge_mm` | `float` |
| `radius_mm` | `float` |
| `paper_mm` | `float` |
| `check_jog_mm` | `float` |
| `retouch_after` | `list[int]` |
| `after_op` | `int` |

## Transfer

| Field | Type (also accepts `"unknown"`) |
|---|---|
| `from` | `str` |
| `indicate` | `str \| list[str]` |
| `tool` | `str` |
| `gauge` | `str` |
| `runout_limit_mm` | `Number` |
| `reindicate_after` | `list[int]` |

## ToolTouch

| Field | Type (also accepts `"unknown"`) |
|---|---|
| `tool` | `str` |
| `x_method` | `str` |
| `gauge` | `str` |
| `z_face` | `str` |
| `method` | `str` |
| `edge_mm` | `float` |
| `paper_mm` | `float` |
| `before_ops` | `list[int]` |
| `after_op` | `int` |

## Operation

| Field | Type (also accepts `"unknown"`) |
|---|---|
| `op` | `int` |
| `do` | `str` |
| `feature` | `str` |
| `faces` | `list[str]` |
| `tool` | `str` |
| `holder` | `str` |
| `direction` | `str` |
| `note` | `str` |
| `inspection_note` | `str` |
| `to_z` | `float` |
| `depth_mm` | `float` |
| `exit_mm` | `float` |
| `rough_allowance_mm` | `float` |
| `stock_to_leave_mm` | `float` |
| `z_from` | `float` |
| `z_to` | `float` |
| `to_dia` | `float` |
| `rpm` | `float` |
| `feed_mm_min` | `float` |
| `doc_mm` | `float` |
| `feed_mm_rev` | `float` |
| `approach_mm` | `float` |
| `to_z_cite` | `Citations` |
| `note_cite` | `Citations` |
| `checks` | `dict[str, str]` |
| `missing_requirements` | `dict[str, str]` |
| `inspection_methods` | `dict[str, str]` |
| `to_z_band` | `Vector` |
| `contour` | `Contour` |
| `stock_removal_bounds` | `Bounds` |
| `approach` | `"rotary"` |
| `angle_window_deg` | `[Number, Number]` |

`faces` explicitly declares this operation's cutting claims using bound STEP
references. Omission uses the feature's default `faces`; `"unknown"` means
unresolved claims; a known explicit list must be nonempty. Explicit refs need
not be the feature's default refs: a drawing feature may require two broad surfaces even
when its exported label names only one. The plan can claim the other exported
surface without rewriting the manifest. Invalid/unmapped refs are geometry
errors. Under the axial milling model, a far-side face whose outward normal
opposes the setup's +Z approach by more than 90° is an error naming the face
and earns no coverage credit. Complementary setups can explicitly claim
opposite sides; finishing coverage credits each face only to the
approach-valid finishing cuts that claim it.

`stock_removal_bounds` is an explicit setup-frame clearing box:
`{ x = [lo, hi], y = [lo, hi], z = [lo, hi] }`, all three intervals numeric
and strictly increasing. It declares the material outside the finished part
that this cutting operation clears inside that volume, leaving everything
outside it unchanged. Its faces still need valid cutting claims from this
setup. If the cutter radius is known, the box's XY extent cannot exceed the union
XY bounding box of its direction-valid claimed faces dilated by that radius;
an excess is a named geometry error and leaves later stock unresolved. If the
radius is unknown, the extent check is `?` with a reason naming the missing cutter
radius, and later stock stays unresolved. Every claim must touch the box and
every removed piece must border a claim.
It shapes stock passed to later setups and excludes only this operation's own
derivable allowance from its flute obstacles; holder, reach and holding facts
still use setup-entry stock. This is an authored process/fixture volume, not a
measured toolpath or proof that roughing is safe. Without it, any claimed wall
whose interior still touches overstock above `to_z` (including a drafted wall)
needs a named stock-out debt; a contour checkpoint bbox is not a clearing volume.

`approach = "rotary"` mills on a horizontal dividing head: every claimed sample
is turned about the head axis to top dead centre under the vertical spindle
(see [Approach models](rules-geometry.md#approach-models)). For such an op
`z_from`/`z_to` are positions along the head axis (the chuck `pose` z) from the
pose origin, and `angle_window_deg = [from, to]` is the head rotation in
degrees, right-handed about that axis (from < to; a span of 360 or more is
unbounded). Both bound the op's removal; a claimed sample outside them is a
claim error. Claims must be supported external surfaces of revolution about
the head axis (coaxial cylinders or planar annuli normal to it). The setup's
`hold.index` declares `rotation = "continuous"` without `positions` or
`angle_deg`, and its `hold.pose`, `hold.chuck` and inventory solids establish
the head/chuck geometry, not an inferred fixture.

Own-removal combines each claimed cylinder's radial sweep with the actual
vertical cutter columns at concave wall-tangent sample poses. Their union is
clipped to the axial/angular window, then the finished solid is subtracted:
finished bosses/pads and material outside that derivable allowance remain
obstacles. Only the flute excludes its own allowance; holder and reach
screens retain setup-entry stock. This is one top-dead-centre pose per sample,
not a continuous toolpath or proof of clearance while rotating between poses.

`doc_mm` enables the engagement screen only for an endmill-family cutter on a
cutting operation. Omitted DOC, noncutting actions and known drills, reamers,
taps or lathe tools are `not_applicable`; an authored unknown DOC on an eligible
operation remains unresolved, not an invented recommendation.

`approach_mm` is the authored nonnegative safe approach/retract distance along
setup Z for M5's travel screen. There is no invented default: absence or
`"unknown"` leaves that operation's Z travel unresolved and the sheet says how
to measure/author it. It does not itself command a machine move or assert XY
collision clearance. Feature extents/centres and commanded tip targets supply
the other spans; see [M5 measured setup screens](rules-setup.md#m5-measured-inventory-screens).

## Contour

| Field | Type (also accepts `"unknown"`) |
|---|---|
| `method` | `str` |
| `sweep_frame` | `str` |
| `open_side` | `str` |
| `step_deg` | `float` |
| `step_mm` | `float` |
| `start_deg` | `float` |
| `end_deg` | `float` |
| `sweep_bounds` | `Bounds` |

## Bounds

| Field | Type (also accepts `"unknown"`) |
|---|---|
| `x` | `Vector` |
| `y` | `Vector` |
| `z` | `Vector` |
