# Shop inventory — `inventory.toml`

The root groups are `machines`, `tools`, `holders`, `fixtures`, `gauges`,
`consumables`, and `stock`; there are no legacy `workholding` or `measuring`
aliases. Category maps use authored identity keys. `members` is a recursively
modeled InventoryItem map. `source` may be a source string or Source record.
Named set members/coverage may resolve without pretending an unlisted member
was measured or purchased. Explicit `present = false` means missing;
`verify = true`, unverified inherited source facts, or explicitly unknown presence make
results unresolved.

For length lookups explicit `_mm` fields take precedence, then `_in` converted
with exactly 25.4 mm/in; bare lengths require explicit `units = "mm"`, `"in"`, or `"inch"`. Do not manufacture nominal diameters from a catalog label unless
the resolver's supported identity/coverage or explicit `nominal_dia_mm` map
establishes them. Nominal identity is not measured size. Inventory tool units
may be converted explicitly; drawing units are not silently converted.

Mill holder compatibility uses spindle taper; lathe compatibility uses toolpost
series. Collet capacity, range and maximum shank checks are separate. Drill point
angle, reamer lead, flute length, projection, holder gauge length and fixture bed
height are operative geometry, not values to infer from unrelated angles or
overall dimensions. A centre drill's centre-seat angle is not its drill-point
angle. `chart` is a source citation, never a downloaded chart.

All InventoryItems share the declared field set below, regardless of category;
category-specific usefulness is enforced by rules, not separate subclass schemas.
Nested dictionaries such as `nominal_dia_mm`, `candidates`, `holders`,
`plate_holes`, and category/member identities have arbitrary declared keys.

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
| `machines` | `dict[str, InventoryItem \| Unknown] \| Unknown` | Optional |
| `tools` | `dict[str, InventoryItem \| Unknown] \| Unknown` | Optional |
| `holders` | `dict[str, InventoryItem \| Unknown] \| Unknown` | Optional |
| `fixtures` | `dict[str, InventoryItem \| Unknown] \| Unknown` | Optional |
| `gauges` | `dict[str, InventoryItem \| Unknown] \| Unknown` | Optional |
| `consumables` | `dict[str, list[str] \| Unknown] \| Unknown` | Optional |
| `stock` | `list[Stock] \| Unknown` | Optional |

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

## Source

| Field | Type (also accepts `"unknown"`) |
|---|---|
| `vendor` | `str` |
| `by` | `str` |
| `url` | `str` |
| `note` | `str` |
| `cite` | `str` |
| `sku` | `str \| int` |
| `verify` | `bool` |

## InventoryItem

| Field | Type (also accepts `"unknown"`) |
|---|---|
| `kind` | `str` |
| `make` | `str` |
| `control` | `str` |
| `operation_mode` | `str` |
| `note` | `str` |
| `coating` | `str` |
| `material` | `str` |
| `coverage` | `str` |
| `by` | `str` |
| `standards` | `str` |
| `shank` | `str` |
| `drawbar` | `str` |
| `insert` | `str` |
| `arbor` | `str` |
| `jaw_bolt` | `str` |
| `mount` | `str` |
| `fits` | `str` |
| `stud` | `str` |
| `t_slot_in` | `str` |
| `standard` | `str` |
| `series` | `str` |
| `chart` | `str` |
| `units` | `str` |
| `sku` | `str \| int` |
| `verify` | `bool` |
| `present` | `bool` |
| `center_cutting` | `bool` |
| `swivel_base` | `bool` |
| `scroll` | `bool` |
| `independent` | `bool` |
| `spindle_to_table_max_in` | `float` |
| `headstock_tilt_deg` | `float` |
| `swing_over_bed_in` | `float` |
| `between_centres_in` | `float` |
| `cross_slide_travel_in` | `float` |
| `compound_travel_in` | `float` |
| `weight_lb` | `float` |
| `worm_ratio` | `float` |
| `centre_height_in` | `float` |
| `swing_in` | `float` |
| `plates` | `float` |
| `pieces` | `float` |
| `angle_deg` | `float` |
| `point_angle` | `float` |
| `flute_len` | `float` |
| `oal` | `float` |
| `head_in` | `float` |
| `max_offset_in` | `float` |
| `dial_in` | `float` |
| `length_in` | `float` |
| `min_bore_in` | `float` |
| `tip_in` | `float` |
| `jaw_width_in` | `float` |
| `opening_in` | `float` |
| `jaw_height_in` | `float` |
| `bed_height_mm` | `float` |
| `diameter_in` | `float` |
| `thickness_in` | `float` |
| `resolution_in` | `float` |
| `runout_max_in` | `float` |
| `gauge_len` | `float` |
| `grip_mm` | `float` |
| `max_shank_in` | `float` |
| `lead_mm` | `float` |
| `projection_mm` | `float` |
| `sfm` | `float` |
| `chip_load_mm_per_tooth` | `float` |
| `dia_mm` | `float` |
| `dia_in` | `float` |
| `shank_mm` | `float` |
| `flute_len_mm` | `float` |
| `flute_len_in` | `float` |
| `oal_mm` | `float` |
| `oal_in` | `float` |
| `gauge_len_mm` | `float` |
| `gauge_len_in` | `float` |
| `projection_in` | `float` |
| `spindle_to_table_max_mm` | `float` |
| `jaw_height_mm` | `float` |
| `height_mm` | `float` |
| `height_in` | `float` |
| `length_mm` | `float` |
| `width_mm` | `float` |
| `width_in` | `float` |
| `capacity_mm` | `float` |
| `bed_height_in` | `float` |
| `nose_radius_mm` | `float` |
| `reach_mm` | `float` |
| `dia` | `Number` |
| `shank_in` | `float \| str \| dict[str, list[str]]` |
| `flutes` | `int \| list[int]` |
| `source` | `str \| Source` |
| `cite` | `Citations` |
| `sizes` | `list[str \| int \| float]` |
| `sizes_in` | `list[str \| float] \| dict[str, list[str]]` |
| `sizes_mm` | `Vector` |
| `styles` | `list[str]` |
| `heights_in` | `list[str \| float]` |
| `shims_in` | `list[str \| float]` |
| `ranges_in` | `list[str]` |
| `range_in` | `float \| list[Number]` |
| `range_mm` | `float \| list[Number]` |
| `resolution_mm` | `Number` |
| `size_in` | `str \| list[Number]` |
| `nominal_dia_mm` | `dict[str, Number]` |
| `nominal_dia_cite` | `dict[str, Citations]` |
| `candidates` | `dict[str, str]` |
| `holders` | `dict[str, int \| Unknown]` |
| `standard_accessories` | `list[str]` |
| `included` | `list[str]` |
| `spindle` | `Spindle` |
| `travel_in` | `Travel` |
| `travel_mm` | `Travel` |
| `table_in` | `Table` |
| `leadscrew` | `LeadScrew` |
| `capacity_in` | `float \| list[Number] \| Capacity` |
| `tailstock` | `Tailstock` |
| `threads` | `Threads` |
| `toolpost` | `Toolpost` |
| `direct_index` | `DirectIndex` |
| `tilt_deg` | `Tilt` |
| `plate_holes` | `dict[str, Vector]` |
| `bars` | `Bars` |
| `members` | `dict[str, 'InventoryItem \| Unknown']` |

## Spindle

| Field | Type (also accepts `"unknown"`) |
|---|---|
| `taper` | `str` |
| `drawbar` | `str` |
| `drive` | `str` |
| `mount` | `str` |
| `rpm_min` | `float` |
| `rpm_max` | `float` |
| `hp` | `float` |
| `bore_in` | `float` |
| `runout_in` | `float` |
| `two_ranges` | `bool` |
| `ranges_rpm` | `list[list[Number]]` |

## Travel

| Field | Type (also accepts `"unknown"`) |
|---|---|
| `x` | `float` |
| `y` | `float` |
| `z` | `float` |
| `quill` | `float` |

## Table

| Field | Type (also accepts `"unknown"`) |
|---|---|
| `length` | `float` |
| `width` | `float` |
| `t_slot` | `str` |

## LeadScrew

| Field | Type (also accepts `"unknown"`) |
|---|---|
| `tpi` | `float` |
| `dial_in` | `float` |
| `cross_feed_ipr` | `Vector` |

## Capacity

| Field | Type (also accepts `"unknown"`) |
|---|---|
| `drill` | `float` |
| `end_mill` | `float` |
| `face_mill` | `float` |

## Tailstock

| Field | Type (also accepts `"unknown"`) |
|---|---|
| `taper` | `str` |
| `quill_travel_in` | `Number` |

## Threads

| Field | Type (also accepts `"unknown"`) |
|---|---|
| `inch_tpi` | `Vector` |
| `metric_pitch_mm` | `Vector` |

## Toolpost

| Field | Type (also accepts `"unknown"`) |
|---|---|
| `series` | `str` |
| `type` | `str` |
| `note` | `str` |
| `holders` | `int` |
| `included` | `bool` |

## DirectIndex

| Field | Type (also accepts `"unknown"`) |
|---|---|
| `positions` | `float` |
| `step_deg` | `float` |

## Tilt

| Field | Type (also accepts `"unknown"`) |
|---|---|
| `down` | `float` |
| `up` | `float` |

## Bars

| Field | Type (also accepts `"unknown"`) |
|---|---|
| `count` | `int` |
| `type` | `str` |
| `shank_in` | `Number` |
| `min_bore_in` | `Vector` |
| `depth_in` | `Vector` |
