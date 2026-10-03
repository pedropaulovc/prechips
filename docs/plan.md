# Plan format — `plan.toml`

`part`, `features`, and `setups` are required. The loader additionally requires
a nonempty setup list, known unique setup ids, a nonempty operation list per
setup, known unique operation numbers within each setup, and every operation's
feature in the manifest. Plan and manifest part names must agree; a known setup
frame must exist in a known manifest frame map; an unknown frame map stays unresolved. Execution follows authored array order, not
numeric sorting of operation ids.

`features` is relative to the plan; it must stay inside the bundle root. The
root is the repository above `examples` or the first ancestor with
`pyproject.toml`, otherwise the plan's parent. Shared input precedence is CLI
override, then a known `[paths]` declaration, then `PRECHIPS_INVENTORY` or
`PRECHIPS_POLICY`; cutting data has no environment fallback. An omitted or
literal `"unknown"` declaration permits the environment fallback. Missing policy
uses the shipped required-rule vocabulary only when no known path is selected.
Plan-declared shared paths must stay inside
the bundle root; explicit CLI/environment shop paths may be external. STEP references are read and hashed, contained
inside the bundle, and checked against a known `step_sha256`; no kernel runs.

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

`checks` maps tolerance requirement names to inventory gauge references;
`inspection_methods` supplies a method for datum/geometric checks. A missing
check is different from `checks.dia = "unknown"`. `to_z` is an authored endpoint;
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
| `setups` | `list[Setup]` | Required |

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
| `as_is_faces` | `list[str]` |
| `components` | `list[StockComponent]` |
| `cite` | `Citations` |

For a built-up stock candidate, `components` lists the separately authored
blanks. Each `StockComponent` accepts `form`, `dia_mm`, `length_mm`,
`section_mm`, `note`, and `cite` with the same types as the stock fields above.
A round blank uses diameter and length; a rectangular blank uses two section
dimensions and length. These are authored purchase/process choices, not
confirmed on-hand inventory. Missing dimensions or citations keep comparison
waste unresolved; finished volume comes only from the manifest's explicitly
sourced `volume_mm3`, never a bounding-box estimate.

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
| `stock_in` | `str` |
| `note` | `str` |
| `deburr_mm` | `Number` |
| `deburr_cite` | `Citations` |
| `stock_state` | `StockState` |
| `hold` | `Hold` |
| `zero` | `Zero` |
| `ops` | `list[Operation]` |

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
| `grip_mm_verify` | `bool` |
| `jaw_above_parallels_mm_verify` | `bool` |
| `index` | `Index` |

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
| `to_z_cite` | `Citations` |
| `note_cite` | `Citations` |
| `checks` | `dict[str, str]` |
| `inspection_methods` | `dict[str, str]` |
| `to_z_band` | `Vector` |
| `contour` | `Contour` |

`doc_mm` enables the engagement screen only for an endmill-family cutter on a
cutting operation. Omitted DOC, noncutting actions and known drills, reamers,
taps or lathe tools are `not_applicable`; an authored unknown DOC on an eligible
operation remains unresolved, not an invented recommendation.

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
