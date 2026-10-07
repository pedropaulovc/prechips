# Plan format — `plan.toml`

`part`, `features`, and `setups` are required. The loader additionally requires
a nonempty setup list, known unique setup ids, a nonempty operation list per
setup and known unique operation numbers within each setup. A saw stock cut may
omit `feature`; every authored feature must be in the manifest or in plan-owned
`joint_features`, and inspection checks need a named feature. Plan and manifest
part names must agree; a known setup frame must name an exported manifest frame
or a plan-owned frame in [`frames`](#frames). A literal `"unknown"` setup frame
stays unresolved.
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
cut that changes the touched top; each serves the next tool. A known list does not
certify the schedule: `zero_check` derives a touch for every other tool change from
the setup's standing touched or faced surfaces, or reports it missing as an error
([coordinates and DRO zero](rules-coordinates.md#zero_check)). Z
`method = "measure_then_set"` (with `gauge`, `measure`, `offset_mm`; on a tool
touch `z_gauge`, `z_measure`, `z_offset_mm`) sets a measured edge, M + offset +
paper.

`checks` maps requirement names to inventory gauge references. Every key must
belong to the selected resolved feature's `requirements` list (exported or
plan-owned); otherwise loading raises `BadInput`, even if another feature owns that name.
A wholly unknown requirements list cannot establish membership and does not
authorize arbitrary checks. `inspection_methods` supplies the authored procedure
for datum/geometric checks and missing requirements. A missing check is different
from `checks.dia = "unknown"`.

An `inspection_methods.<requirement>` procedure and an op's `inspection_note`
are each either one string or a non-empty list of strings. A string prints as
before (blank-line paragraphs become `(1)…(2)…`). A list prints as numbered steps
in the INSPECTION NOTES, for procedures a machinist follows and records as they go:

```toml
inspection_methods.position_dia = [
  "Pin the rod hole with the 4.000 gauge pin; zero the indicator on datum A.",
  "Read X at the pin: {X1}",
  "Read Y at the pin: {Y1}",
  "Calculate: position Ø = 2 × √((X1 − 133.067)² + (Y1 + 8.456)²) = {result}",
]
```

`{name}` prints as a labelled blank to write the reading in. A step beginning
`Calculate:` prints apart from the numbered steps as the calculation line. A list
is known only when every step is a non-empty string other than `"unknown"`.

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
pockets and faces may declare `sweep_bounds`, `sweep_frame`, `open_side`, and
circular `keep_out` islands; their rasters need `step_mm`
(see [rules-coordinates](rules-coordinates.md)).

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
| `aims` | `dict[str, Aim]` | Optional |
| `joint_features` | `dict[str, JointFeature]` | Optional |
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

## Aims

`[aims.<feature>]` moves one located feature's DRO target off its drawing
nominal so that a height-like band it holds from its `height_from` reference
(`height_above_pivot`, `height` or `separation`) reads a stated value. It is a
process choice on the printed target, never a change to the STEP, the manifest,
a cutting claim or a kernel input.

| Field | Meaning |
|---|---|
| `requirement` | The height-like requirement the aim sets; it must be one of the feature's exported drawing requirements |
| `value_mm` | The value that requirement reads at the aimed target |
| `reason` | Known text; the bundled examples begin it with `AUTHOR'S CHOICE` |

The `<feature>` must be a manifest feature that exports `requirement`; anything
else is bad input. The [`coordinates`](rules-coordinates.md#coordinates) rule
moves the target along the band's measuring direction in every setup that
locates the feature. It then checks the DRO-rounded target against the printed
band and cites `plan.aims.<feature>`. The sheet's feature map prints the aimed
target together with the drawing nominal and the reason. An aim on a feature
without that band, or one whose distance cannot be measured, stays unknown.

## Joint features

`[joint_features.<id>]` declares transient component geometry, not a change to
the finished STEP or its feature manifest. Identities must not collide with
exported features. Every declaration requires:

| Field | Meaning |
|---|---|
| `kind` | `cylinder_bore` (socket) or `cylinder_spigot` |
| `component` | Exact declared stock component id |
| `at` | Starting-face centre in model coordinates |
| `axis` | Unit vector along positive depth |
| `dia` | Ordered positive diameter tolerance band `[low, high]` |
| `nominal_dia` | Authored cylinder diameter; never inferred from band midpoint |
| `depth` | Positive finite axial length, including when `thru = true` |
| `thru` | Boolean through/blind declaration |
| `cite` | Nonempty author/source citation |

Unsuffixed lengths use the manifest's model units; `axis` is dimensionless.
Known geometry must satisfy these constraints. Literal numeric `"unknown"`
remains debt and cannot create a solid, an inferred nominal, or a successful
assembly. Identity fields and citations are not numeric debt: missing/unknown
kinds, components and references are bad input. Optional `requirements` is a
subset of `["dia"]` and defaults to that list; depth is finite construction
geometry, not an invented depth tolerance. Optional `precision` and `note`
retain normal dimensional/display semantics.

Operations address these identities through the same resolved feature mapping
as exported dimensions (socket as hole, spigot as boss), but may prepare them
only on their own pre-assembly component ancestry. The original manifest and
STEP hashes remain unchanged. Findings cite `plan.joint_features.<id>` and the
author's citations, not invented exported faces. Completing a transient cut
earns no finished STEP coverage or final finish coverage by itself. A finishing
spigot turn earns both only for the exported faces the kernel measures it
leaves as its own turned surface, over their full area inside its finite
window (see [geometry rules](rules-geometry.md#face-identity)). A separate
pass on the exported feature is then unnecessary.
Inspection, fitting and other noncutting actions do not prepare or invalidate
a joint feature. Socket drill/ream/bore and spigot turning actions derive their
actual removal; spotting does not complete a socket. Transient `tap` and
`counterbore` operations leave named geometry debt until thread/step profiles
are supported. A rough cut's allowance must be removed by a valid finishing
cut before the selected branch can supply completed preparation to a join.

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
| `joint` | Tagged cylindrical or surface joint (required for array `stock_in`) |
| `note` | `str` |
| `deburr_mm` | `Number` |
| `deburr_cite` | `Citations` |
| `stock_state` | `StockState` |
| `hold` | `Hold` |
| `zero` | `Zero` |
| `ops` | `list[Operation]` |

For a manual joining, finishing or inspection station, declare the inventory
machine's `kind = "bench"` (or `"manual"`) and use only `fit`, `inspect`,
`deburr` and `coating` operations.
`zero_check`, `coordinates` and `headroom` are then `not_applicable`: the station
has no DRO, cutter-centre table, spindle stack or machine travel to check.
The joint's joining method does not create machine axes. Any cutting or
explicitly unknown action retains the normal screens; a bench declaration
cannot waive a machining operation. This does not waive physical joint,
holding, stock, frame or render requirements.

For component stock, an earlier setup's output, or a joint output, mill
headroom's X/Y travel screen uses the kernel's **setup-entry stock bounding
box**, before the current setup's cuts. It does not substitute the finished
part or the original raw blank. Missing entry stock remains a geometry debt.

`stock_in` names `"stock"` for a single supply, `"stock.<id>"` for a built-up
component, or any earlier setup's `id` (not necessarily the immediately previous
setup). An array requests assembly of exactly two disjoint branches and requires
an explicit `joint`; there is no generic Boolean-union fallback. Unknown or forward authored references are bad input
(exit 3), including authored `"unknown"` as a source. Omitted `stock_in`
remains stock debt; it does not infer a linear route. Every supply and setup output stays in the model frame:
joining references never applies an implicit assembly transform.
Array entries must have disjoint supply ancestry: repeated references or joining
a supply with its descendant (for example `["stock", "S1"]` when S1 consumes
stock) are bad input (exit 3), naming the shared supply ancestor. Separate route
alternatives may start from the same supply again, but cannot join that material
lineage twice.

### Assembly joints

Every array `stock_in` requires a singular tagged `joint` declaration and
exactly two disjoint input branches. Either input may be an already-joined
assembly if the other input is one single component. Thus `["body", "cone"]`
may produce `J1`, followed by `["J1", "crank"]` producing a three-component
assembly. Joining two existing assemblies, one-piece arrays and arrays with
more than two references are bad input (exit 3). Shared supply ancestry remains
forbidden at every step. Each interface identity is consumed only once.
Joint geometry is in the model frame, regardless of the assembly setup's frame.
A missing or malformed identity/reference is bad input; unknown numeric
geometry or retaining-compound process facts withhold the union as named debt.

A cylindrical joint declares `kind = "cylindrical"`, `socket` and `spigot`
(matching plan joint-feature kinds on the two distinct consumed component
branches), `fit`, the applicable diametral fit band, `method`, nonempty
`process` and `cite`. Clearance uses `fit = "clearance"` and `clearance_mm`,
with `method = "silver_braze"` or `"retaining_compound"`. Interference uses
`fit = "interference"`, `interference_mm` and `method = "press"`.
All tolerance extremes must satisfy the declared fit:

- Clearance interval: `[socket.low - spigot.high, socket.high - spigot.low]`.
- Interference interval: `[spigot.low - socket.high, spigot.high - socket.low]`.

The resulting interval must be nonnegative for clearance, strictly positive
for interference, and entirely inside the declared millimetre band; exact band
endpoints are accepted. A compatible nominal alone is insufficient. Axes must
be collinear with finite overlapping engagement.
Both preparation cuts must be completed on the actual selected ancestors,
remain intact, and have their target geometry verified at assembly. Declaring
a joint cannot turn untouched blanks into prepared components.

`method = "retaining_compound"` additionally requires `cure_time_min` (positive
minutes, or literal `"unknown"`) and `surface_prep` (nonempty instructions, or
literal `"unknown"`). `process` identifies the selected compound/application
process; `clearance_mm` remains the diametral clearance band in millimetres.
Missing process fields are bad input; explicitly unknown clearance, cure time
or prep remains debt and cannot produce assembled stock or a render.
`process` itself must be known text: the literal `"unknown"` is malformed,
not an alternative bond process. Known physical refusals remain errors even
when prep or cure is unknown; a later invalid join does not invalidate an
earlier independent, valid assembly.
The traveler prints the prep, cure time and **do not disturb until cured** before
later machining. The process does not model cure kinetics or certify a product:
cite the author's source/choice for the declared band and cure conditions.
These fields do not apply to `silver_braze` or `press`; their behavior is unchanged.
Use the canonical noncutting bench action `do = "fit"`, not an undeclared
`fit_up` or `bond` cutting action.

For example (illustrative process choices, not manufacturer specifications):

```toml
[[setups]]
id = "J2"
stock_in = ["J1", "crank_prepared"]
[setups.joint]
kind = "cylindrical"
socket = "crank_socket"
spigot = "crank_spigot"
fit = "clearance"
clearance_mm = [0.02, 0.06]
method = "retaining_compound"
process = "AUTHOR'S CHOICE: example Loctite 638-class retaining compound"
cure_time_min = 1440
surface_prep = "AUTHOR'S CHOICE: degrease and dry both mating surfaces"
cite = "AUTHOR'S CHOICE: example clearance band and 24-hour cure before machining"
[[setups.ops]]
op = 10
do = "fit"
```

A cylindrical cross-bore socket uses the existing `cylinder_bore` kind with
`thru = true` and a finite `depth` spanning both openings. The kernel verifies
both ends are open; this is not an unbounded hole or a blind socket with a
waived bottom. A sleeve exterior is a `cylinder_spigot`, not a new feature kind.
An intentional bore already present in the sleeve is permitted only where it
does not remove required finished material; joining fills the mating annulus,
not the sleeve's core. A subsequent finished bore operation still needs its
own preparation/finish coverage and must follow the declared cure.

A surface joint needs no transient feature. It declares `kind = "surface"`,
`method = "weld"` or `"silver_braze"`, nonempty `process`, `cite`, and a nonempty
`interfaces` list. Each rectangle has model-space centre `at`, unit orthogonal
`normal` and `x`, positive `size_mm = [width, height]`, and nonempty `cite`.
Both sizes are full side lengths in millimetres; `normal × x` is the height
direction. `at` uses manifest units. These are author-declared internal butt interfaces,
not STEP face references. `stock_in[0]` owns the negative-normal side;
`stock_in[1]` owns the positive-normal side. Both received pieces must contact
essentially the whole rectangle inside the final solid, with no overlapping bulk. Multiple
patches describe one two-input join, not additional component inputs in that step.
Separated material is not joined merely because a process was named.

The kernel protects component-owned finished material during preparation and
checks final material coverage again at assembly. Cylindrical fill is limited
to derived finite engagement; surface joins add no fill. Undeclared overlap,
a blocked straight-axis insertion, or lost finished material refuses the
assembly. See [in-process stock](rules-geometry.md#in-process-stock).


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
| `centre_hole_dia_mm` | `Number` (> 0): the work's centre-hole countersink mouth at its end face; the kernel cuts a seat of the dead centre's own point angle with that mouth on the face where the centre axis leaves the stock, and the centre must touch that seat (else a render debt) before it is checked against the setup-entry stock |
| `clamps` | `list[ClampPlacement]` |
| `clamp_order` | `list[positive int]` (1-based indices into `clamps`) |
| `preload_direction` | `"clockwise"` / `"counterclockwise"` |
| `stop_fixture` | `str` (inventory fixture with authored solids) |
| `stop_face` | `str` (feature id or `"stock_end"`: the face the stop seats on) |
| `stop_pose` | `Pose` |
| `grip_mm_verify` | `bool` |
| `jaw_above_parallels_mm_verify` | `bool` |
| `index` | `Index` |

`Pose` is `{origin_mm, x, z}`, each `[Number, Number, Number]` in setup-frame
mm: a fixture-local frame's origin and unit, orthogonal x and z axes. A
`ClampPlacement` is `{ref, note, pose, restraint, torque_nm}`: `ref` names a fixture or a
`kit/member` such as a clamping-kit strap, and its authored `solids` are
placed by `pose` (origin at the strap underside on the work). `restraint` is
`press` (it holds the work down along pose -z), `locate` (it only positions
the work) or `none`; undeclared is `none`. Only a press clamp can hold a stock
piece an op splits off, and only when the kernel proves the load path onto an
anchored support (rules-geometry, held split).

`clamp` is the clamping instruction, or a declared clamp fixture's name. An
explicit `clamp = "none"` or `"not_applicable"` with no `clamps` members
declares a hold with no clamping load (for example gravity in a cradle); prose
such as "gravity only", an omitted or `"unknown"` value is not that declaration.
Under only non-cutting ops such a posed-solids hold makes
`thin_wall_under_clamp` not applicable (rules-geometry).

`clamp_order` is the declared tightening-action sequence for drawing badges,
not an automatic interpretation of the `clamps` array. A locating pin may
belong to that array for its posed solids without being a tightening action;
omit its index from the order. `preload_direction` is viewed from above,
looking down setup -Z. These annotations do not certify clamp force or order.
HOLD and the picture share one label per `clamps` entry, by its 1-based index:
`C<i>` for a press clamp (or, with `restraint` undeclared, an index in
`clamp_order` or no order at all), `LOC<i>` for `locate`, `SUP<i>` otherwise.
HOLD prints the order as "seat against the locators (turning in
`preload_direction`), snug each in turn, then tighten each fully in the same
order", to the entry's optional declared `torque_nm` when given.

A physical stop uses `stop_fixture` plus `stop_pose`; its inventory solids
follow the same dimension/measurement/void trust rules as other fixture bodies.
The kernel places it, draws it and includes it in collision/interference checks.
An unresolved stop is a named fixture gap, not a guessed point from `stop` prose.

`stop_face` names the face the work seats on against the stop: a feature id or
`"stock_end"`. An unknown id is `BadInput`. `hold_fields` errors when the
arriving stock does not have that face yet: it must be `"stock_end"`, a face
the raw stock supplies (`stock.as_is_faces`), or a feature a cutting op in an
earlier setup of this setup's stock lineage made. A face the setup cuts itself,
or a later setup cuts, is not on the stock it receives. An earlier cut of
unknown action, or unknown as-is faces, leaves it unknown. When a setup in the
lineage omits `stock_in`, the routing is undeclared: an earlier setup's cut may
have made the face, so it is unknown, not an error. A cut in this or a later
setup is still an error: `stock_in` names only earlier setups.

M4 vise geometry consumes `fixture`, `parallels`, `fixed_jaw`, `jaws_along`,
`grip_mm` and `jaw_above_parallels_mm` to place the jaw solids in the setup
frame: `jaws_along` is the jaw length axis (`x` / `y`), `fixed_jaw` picks the
jaw on the negative or positive side of the other axis, `grip_mm` is the depth
of part inside the jaws and `jaw_above_parallels_mm` the jaw plate standing
above the stock seat (support tops, or the bed without a lifting support).
An explicit `parallels = "none"` or `"not_applicable"` means known zero parallel
lift and no parallel solids or parallel-position debt. Without another lifting
support the work seats on the bed. Omitted,
`"unknown"` or unresolved named parallels still need an accepted positive
height; a named zero-height parallel is not equivalent to explicit absence.
A `grip_mm_verify = true` or
`jaw_above_parallels_mm_verify = true` flag makes that number unknown to the
kernel; `jaw_above_parallels_mm = 0` is a known zero, any other nonpositive or
unknown value is debt. Together with the vise's explicit `jaw_height`,
`jaw_width`, `jaw_depth` and `opening` and the selected parallels' `height`
(or explicitly declared zero lift), these are the facts behind the jaw solids
and setup findings. When a required fact is missing, the setup's `vise` and
`thin_wall_under_clamp` findings stay `?` and the render, if any, is a part-only
view labelled as unresolved.

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
with exact jaws and, when selected, exact parallels is captioned as modeled.
Either field may be `"unknown"` (any unknown coordinate is a render debt, not
a guessed pose) and neither has a `_verify` flag: they are author coordinate
choices, while each parallel dimension has its own fact-local trust; the
inventory item's `verify` does not taint other numeric facts. Omitting the
optional poses does not block independent `vise` / `thin_wall_under_clamp`
facts. A selected parallel's missing height still leaves fixture dimensions unknown.

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
| `jaw_lead_mm` | `float` |
| `engage_at_z_mm` | `float`: follow rest only; the cut Z the tool passes before its jaws are set on the work, checked by `accessibility` against the kernel's clear Z ([geometry](rules-geometry.md#window-ends)) |
| `at_z_mm` | `float` |
| `jaw_side` | `str` (`turned` or `uncut`; follow rests only) |
| `ops` | `list[int]` |

A `hold.supports` table with `jaw_lead_mm` declares a follow rest riding that
far from the tool along Z; one with `at_z_mm` declares a steady rest at that
setup-frame Z. `ops` lists the operation ids it serves (omitted = every turning
op of the setup). A follow rest's `jaw_side` says which diameter its jaws ride:
`turned` (the default; trailing the tool on the diameter just cut) or `uncut`
(leading it on the diameter about to be cut). `ref` names an inventory
`follow_rest`/`steady_rest` fixture with measured `capacity_min`/`capacity_max`.
`turning_deflection` then uses the rest span instead of `stickout_mm`
(docs/rules-physics.md "Follow and steady rests"). The kernel also draws and
collision-checks the rest from that fixture's measured solid fields: a follow
rest's `jaw_width`, `jaw_height`, `jaw_depth` and `jaw_angles_deg`, a steady
rest's `body_dia` and `body_length` ([inventory](inventory.md),
[rules-geometry](rules-geometry.md#follow-and-steady-rests)). Example:
`supports = ["dead_centre_tailstock_mt3", { ref = "follow-rest", ops = [10, 30], jaw_lead_mm = 8.0, jaw_side = "turned" }]`.
The traveler's HOLD prints a follow rest's lead as a distance along the work,
never beside a Ø sign: `jaws 8.00 mm behind the tool, on the diameter just turned:
reset them on every pass once the tool passes Z 152.00` (trailing jaws ride each
pass's new diameter; `engage_at_z_mm`, when declared, is the Z), or `jaws … mm
ahead of the tool, on the uncut stock`.

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
| `measure` | `str` (`measure_then_set`: what M is) |
| `from` | `str` |
| `edge_mm` | `float` |
| `radius_mm` | `float` |
| `paper_mm` | `float` |
| `check_jog_mm` | `float` |
| `offset_mm` | `float` (`measure_then_set`: Axis Set M + offset + paper) |
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
| `z_gauge` | `str` (`measure_then_set`) |
| `z_measure` | `str` (`measure_then_set`: what M is) |
| `z_offset_mm` | `float` (`measure_then_set`: Axis Set Z = M + offset + paper) |
| `before_ops` | `list[int]` |
| `after_op` | `int` |

## Operation

| Field | Type (also accepts `"unknown"`) |
|---|---|
| `op` | `int` |
| `do` | `str` |
| `feature` | `str`; an `inspect` op may name a list of two or more distinct features |
| `faces` | `list[str]` |
| `tool` | `str` |
| `holder` | `str` |
| `direction` | `str` |
| `note` | `str` |
| `inspection_note` | `str \| list[str]` (numbered steps; see above) |
| `process` | `str \| list[str]` (`coating` only: a `services` or `consumables` id) |
| `process_holds` | `list[ProcessHold]` |
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
| `inspection_methods` | `dict[str, str \| list[str]]` |
| `to_z_band` | `Vector` |
| `contour` | `Contour` |
| `stock_removal_bounds` | `Bounds` |
| `approach` | `"rotary"` |
| `angle_window_deg` | `[Number, Number]` |
| `cut_plane` | `SawPlane` (saw cut-off only) |

An `inspect` op may name several features (`feature = ["a", "b"]`) when one
drawing limit is split across them: its `checks` and `inspection_methods` keys
are requirement names, valid when any named feature exports them, and apply to
every named feature that does. The inspection rule credits the op to each of
those features; the sheet prints one row per requirement naming every feature.
A list on any other action is `BadInput`.

**Finishing route.** `deburr` and `coating` are manual bench actions. A
`coating` op (black oxide, paint, oil) names its `process`: an outside
`[services.<id>]` item or in-house `[consumables.<id>]`. An absent process is
unknown in `tool_resolves`, and an unlisted one is an error. A drawing
`material.finish` with no `coating` op in the route is a job caution
(`finish_route`, [inspection rules](rules-inspection.md)).

A `ProcessHold` is `{ feature, requirement, band = [lo, hi], gauge, reason }`, all
required: a shop limit tighter than the drawing, held for a stated process reason
(a downstream fit, a pin that clocks a later setup). `requirement` must be one the
feature exports (else `BadInput`), and `band` is in the drawing's units. The
inspection rule errors when the band reaches outside the drawing band (limits
included, a scalar zone `v` read as [0, v]). The sheet prints it in the op's
inspection cell as `PROCESS HOLD — not a drawing limit: <reason>`, never as a
drawing limit.

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
A claimed hole cap also needs its feature's last drill/ream/bore/counterbore
setup to leave it clear of stock; a tap or pilot claim never stands in for that
(see [geometry](rules-geometry.md#finish_coverage)). No plan field selects that op.

**Complete explicit-face ownership.** An op owns a feature it does not name when
its explicit `faces` list is known and nonempty and contains every face of that
feature's known, nonempty declared `faces`. Ownership is per op: a partial
claim, an empty or `"unknown"` list (or one with an `"unknown"` member), a
feature whose own faces are unknown, and an op without explicit `faces` never
own; a label alone never owns another feature. A hole-family feature (`hole`,
`counterbore`, `thread`, `threaded_hole`) is owned only by a complete-form
action (`drill`, `ream`, `bore`, `counterbore`). Ownership adds the op to the
feature's finishing cuts for datum consistency and finishing coverage, under the
same final-cut filters as a named op (no rough, manual or nonfinishing action);
label-scoped facts (hole chains, sizing, inspection checks) still follow the
op's own `feature`.

`stock_removal_bounds` is an explicit setup-frame clearing box:
`{ x = [lo, hi], y = [lo, hi], z = [lo, hi] }`, all three intervals numeric
and strictly increasing. It declares the material outside the finished part
that this cutting operation clears inside that volume, leaving everything
outside it unchanged. Its faces still need valid cutting claims from this
setup. The box is the explicit cleared footprint, for example the envelope of
several roughing passes; it is not capped to the claimed faces' XY bounding box
dilated by the cutter radius. The cutter radius must still be known: if it is
unknown, the bounds are `?` with a reason naming the missing cutter radius, and
later stock stays unresolved. Removal is the box's intersection with the
setup-entry stock and never takes finished material or a protected rough leave.
Every claim must touch the box and every removed piece must border a claim on
that setup-entry stock, so an earlier op of the setup clearing the bridge
between a claim and the rest of its box never strands it; the pieces are then
cut from the current stock, which only removes material and never restores what
an earlier op cleared. Known future planned-hole columns, with their finite caps,
stay stock; and the removal must not split an original input solid. A violation is named stock
debt, not an error: later stock that depends on it stays unresolved (later ops
of the same setup keep only certain finished-material flute hits, with tool hits
unknown), while genuine collisions with finished material remain independent
errors. It shapes the stock later flutes of this setup and later setups meet,
and excludes this operation's own derivable allowance from its flute obstacles;
accessibility holder obstacles and holding facts still use setup-entry stock,
while reach, holder-wall and shank screens see it ([`reach`](rules-geometry.md#reach)). This is an
authored process/fixture volume, not a
measured toolpath or proof that the whole toolpath is safe. Without it, any claimed wall
whose interior still touches overstock above `to_z` (including a drafted wall)
needs a named stock-out debt; a contour checkpoint bbox is not a clearing volume.

`approach = "rotary"` mills on a horizontal dividing head: each sample of the
claimed faces' windowed portions is turned about the head axis to top dead
centre under the vertical spindle
(see [Approach models](rules-geometry.md#approach-models)). For such an op
`z_from`/`z_to` are positions along the head axis (the chuck `pose` z) from the
pose origin, and `angle_window_deg = [from, to]` is the head rotation in
degrees, right-handed about that axis (from < to; a span of 360 or more is
unbounded). Together they are a partial-face claim window: the op samples and
removes only the part of each claimed face inside it, and points outside are
excluded, not claim errors. A window holding no positive-area part of a
claimed face makes that face a claim error. Claims must be supported external
surfaces of revolution about the head axis (coaxial cylinders or planar
annuli normal to it). The setup's `hold.index` declares
`rotation = "continuous"` without `positions` or `angle_deg`, and its
`hold.pose`, `hold.chuck` and inventory solids establish the head/chuck
geometry, not an inferred fixture.

A face claimed through rotary windows is covered only when the exact union of
every rotary op's window portion of it covers the whole face: several ops,
cutters and setups may contribute (for example a larger cutter on the body
and a smaller one into a shoulder), and `finish_coverage` unions only the
finishing ops' portions. An uncovered remainder is a `coverage` /
`finish_coverage` error naming its area and spans; an undecided union stays
unknown. A whole-face non-rotary claim, or `stock.as_is_faces` for
`coverage` only, covers the face regardless. See
[`coverage`](rules-geometry.md#coverage).

Own-removal combines each claimed cylinder's radial sweep with the actual
vertical cutter columns at concave wall-tangent sample poses. Each volume is
clipped to the axial/angular window, the finished solid is subtracted, and the
volumes are cut from the stock one by one in order, never fused: finished
bosses/pads and material outside that derivable allowance remain obstacles.
The flute meets the stock left after this removal; an underivable removal
credits none of it. Accessibility holder obstacles retain setup-entry stock;
reach, holder-wall and shank screens meet the stock earlier ops leave. This is
one top-dead-centre pose per sample,
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
| `keep_out` | list of `{ at = [x, y], dia_mm = d }` circles |

`keep_out` centres use `sweep_frame`, defaulting to the feature's frame.
Positive `dia_mm` islands exclude the whole cutter: pass centres clear each
island radius plus cutter radius. Crossing passes split into independent,
positive-length pieces in feed order, each with its own feed/lift/rapid cycle;
each cut point lies on the DRO grid, rounded away from the island.
The raster record reports setup-frame circles in `raster.keep_out` and counts
pieces in `raster.passes`.

## Bounds

| Field | Type (also accepts `"unknown"`) |
|---|---|
| `x` | `Vector` |
| `y` | `Vector` |
| `z` | `Vector` |

## Saw cut-off

`do = "saw_cut"` and `do = "cut_off"` remove a sacrificial end/slab with a
`tools.<blade>` whose `kind = "bandsaw"`. The setup machine may be a `mill`,
`bench` or `bandsaw`; a lathe uses its separate `part_off` action, not this model.
The operation requires no spindle holder, direction or finished-face claim.
If a feature is authored it must resolve normally; checks cannot be attached to
an omitted feature.

```toml
[[setups.ops]]
op = 10
do = "saw_cut"
tool = "metal-blade"
cut_plane = { axis = "y", value = 87.75, keep = "below" }
```

`SawPlane` has `axis = "x" | "y" | "z"`, numeric `value` in the manifest/plan
units, and `keep = "below" | "above"` (each may be `"unknown"`). The plane is the
**blade centre**, in setup coordinates. The blade's inventory `kerf` straddles
it: below retains `coordinate <= value - kerf/2`; above retains
`coordinate >= value + kerf/2`. For a 1.5 mm kerf, the example retains Y ≤ 87 mm,
not Y ≤ 87.75 mm. The kernel removes the kerf and the discarded offcut, checks
that no finished target is removed, and hands the retained stock to later setups.

An all-saw setup (possibly with manual inspection/deburring) needs no `zero`
recipe or mill envelope; `zero_check`, `headroom`, `envelope` and `travel` state
why they are not applicable. Mixed setups still check their other machining ops.
Holding declarations, `stock_state.top_z/bottom_z`, the bound frame and routing
remain operative. Use an ordinary declared fixture (for example a saw vise with
the usual jaw/parallels fields) to obtain a modeled fixture; a bandsaw machine
identity does not invent integral-vise geometry.

The traveler prints blade-centre setting, retained edge in mm, blade speed in
sfm and descent feed in mm/min. These starting numbers come only from the cited
[`saw_cut` cutting-data row](cutting-data.md), never op-level RPM/feed overrides.
Blade-centre settings, retained edges and sourced blade speed/feed keep their
own numeric digits; a coarse drawing print class does not round machine settings.

