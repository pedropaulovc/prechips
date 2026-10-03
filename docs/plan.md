# Plan format — `plan.toml`

`part`, `features`, and `setups` are required. The loader additionally requires
a nonempty setup list, known unique setup ids, a nonempty operation list per
setup, known unique operation numbers within each setup, and every operation's
feature in the manifest. Plan and manifest part names must agree; a known setup
frame must exist in a known manifest frame map; an unknown frame map stays unresolved. Execution follows authored array order, not
numeric sorting of operation ids.

`features` is relative to the plan; it must stay inside the bundle root. The
root is the repository above `examples` or the first ancestor with
`pyproject.toml`, otherwise the plan's parent. `[paths]` selects shared inventory,
policy and cutting data, with CLI flags taking precedence; only inventory and
policy have environment fallbacks. Plan-declared shared paths must stay inside
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
the displayed type. Omitted fields are not filled into the loaded bundle; rules
decide whether missing information is an error, unknown or not applicable. Root
fields marked required must be present. A model accepting a value is not proof
of geometric validity; rules perform the applicable checks.

## Root fields

| Field | Type | Presence |
|---|---|---|
| `part` | `str` | Required |
| `features` | `str` | Required |
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
| `index` | `dict[str, Any]` |

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
