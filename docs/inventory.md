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
Set `sizes_in` may be a flat list or a mapping of named groups; every group's
sizes are declared choices (the group name is a label). `flutes` may be one count
or a list. An `endmill_set` member `<size>in-<n>fl` resolves when the size is in
any group and `n` is a declared flute count.

Mill holder compatibility uses spindle taper; lathe compatibility uses toolpost
series. Collet capacity, range and maximum shank checks are separate. Drill point
angle, reamer lead, flute length, projection, holder gauge length and fixture bed
height are operative geometry, not values to infer from unrelated angles or
overall dimensions. A centre drill's centre-seat angle is not its drill-point
angle. `chart` is a source citation, never a downloaded chart.

M2 holding checks use explicitly declared `sizes_mm` / `sizes_in` or a two-ended
`range_mm` / `range_in` for the held stock diameter. A six-inch chuck body
(`diameter_in`) says nothing about jaw capacity. Tailstock/steady exceptions
must resolve to actual inventory or a named machine accessory; an unconfirmed
accessory does not certify support.
Hold identities resolve through `fixtures`, `holders`, then `machines`, so a
machine-mounted dividing head is not an unresolved fixture. A dividing head
without declared gripping capacity is `not_applicable` to the diameter screen;
a machine or dividing head with declared collet sizes or chuck ranges is checked.

For indexing, a dividing head can live in `machines` (the example is `BS-0`) or
`fixtures`. `worm_ratio`, `direct_index` and every `plate_holes` circle are
arithmetic inputs; `verify = true` keeps the chosen setting tentative. Hole
counts are positive integers. For engagement, `projection_mm` on the selected
tool/holder assembly takes precedence over `oal_mm - holder.grip_mm`. Neither
flute length nor holder gauge length substitutes for projection.
Engagement uses only the resolved `endmill` / `endmill_set` family on cutting
operations with authored DOC. Long drills, reamers, taps and lathe tools do not
receive a milling DOC-halving recommendation.

## Measured envelopes and installed tool stacks (M5)

`machines.<id>.envelope` records the usable mill envelope, independently of
vendor identity data. Lengths may be a scalar Number qualified by a surrounding
`measured` record, or a fact record:

```toml
[machines.my_mill.envelope]
spindle_to_table_max_mm = "unknown"
spindle_to_table_min_mm = "unknown"
table_length_mm = "unknown"
table_width_mm = "unknown"
t_slot_pitch_mm = "unknown"
spindle_taper = "unknown"

[machines.my_mill.envelope.travel_mm]
x = "unknown"
y = "unknown"
z = "unknown"

[machines.my_mill.envelope.spindle_stack_mm]
r8 = "unknown"
er_collet_chuck = "unknown"
drill_chuck = "unknown"

[holders.my_holder]
gauge_len_mm = "unknown"
projection_mm = "unknown"
```

For a measured fact replace the unknown with
`{ value = <actual measurement>, measured = { by = "<operator>", date = "YYYY-MM-DD", instrument = "<actual instrument>" } }`.
`by`, `date` and `instrument` must be nonblank known strings. Do not put these
template placeholders into operative inventory. A vendor copy instead carries
`verify = true`, either on that fact or its enclosing block. Complete fact-local
measurement evidence qualifies only that dimension; an explicit fact-local
`verify = true` still leaves it unresolved. Clearing `verify` without measurement
evidence cannot certify a new envelope limit or holder gauge/projection.

Envelope `travel_mm` / `travel_in` use `x`, `y`, `z`. Max/min, table length/width,
and T-slot pitch accept `_mm` or `_in`. `spindle_stack_mm` records installed R8,
ER-collet-chuck and drill-chuck heights. Envelope/block metadata are `measured`,
`verify`, and `cite`. `measured` may also qualify inventory item scalar lengths.
Gauge length retains the existing `gauge_len_mm/in` spelling. Gauge is
**mounted spindle nose to holder exit face**;
projection is **holder exit face to the installed tool tip**. A holder projection
belongs to that installed assembly, not every interchangeable tool. A selected
tool's explicit projection takes precedence over a holder projection; otherwise
measured tool OAL minus measured holder grip is permitted. Unknown OAL, grip,
or projection is never replaced with flute length. Explicit tool projection
`"unknown"` does not fall through to a different assembly's number.

The M5 envelope screen uses the conservative jaw-height/parallel/support
envelope, distinct from M1's bed-height plus tool-change allowance. Mounted gauge
already includes spindle/chuck stack height, so the recorded spindle-stack
height is not added again. Table size, T-slot pitch and taper/stack are visible
inventory measurements, not a new collision or mounting-certification rule.
The original PM-30MV vendor max/travel/table values remain unchanged and
`verify = true`; missing minimum, T-slot pitch and stack heights remain unknown.

`prechips tools --inventory inventory.toml --measure` produces one sorted,
deduplicated shop checklist. It includes missing M5 envelope/holder dimensions
and authored unknown/vendor-copy dimensions, with the instrument and units for
each measurement. JSON emits the same entries with stable ids and citations.
This inventory-wide list includes unused declared items; it invents no set
members or purchases. Normal `tools` prints the envelope and marks unmeasured
facts. Applicable M5 `?` sheet sentences also state what to measure and how.

### Measurement records

| Record | Fields |
|---|---|
| `Measurement` | Required strings `by`, ISO calendar `date` (`YYYY-MM-DD`), `instrument`; none may be blank or `"unknown"` |
| `LengthMeasurement` | Required `value: Number`; optional `measured: Measurement`, `verify: bool`, `cite: Citations` (each may be `"unknown"`) |
| `MeasuredLength` | `Number` or `LengthMeasurement` |
| `EnvelopeTravel` | `x`, `y`, `z: MeasuredLength`; optional `measured`, `verify`, `cite` |
| `SpindleStack` | `r8`, `er_collet_chuck`, `drill_chuck: MeasuredLength`; optional `measured`, `verify`, `cite` |
| `MachineEnvelope` | `travel_mm/in: EnvelopeTravel`; `spindle_to_table_max_mm/in`, `spindle_to_table_min_mm/in`, `table_length_mm/in`, `table_width_mm/in`, `t_slot_pitch_mm/in: MeasuredLength`; `spindle_taper: str`; `spindle_stack_mm: SpindleStack`; optional `measured`, `verify`, `cite` |

All envelope/stack/travel fields are optional and accept `"unknown"`; their
absence remains measurement debt. A date or a citation is provenance, not an
automatic claim that the whole item is measured.


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
decide whether missing information is an error, unknown or not applicable.
Missing facts needed by an applicable check cannot establish known absence or a
pass. Root fields marked required must be present. A model accepting a value is
not proof of geometric validity; rules perform the applicable checks.

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
| `components` | `list[StockComponent]` |
| `cite` | `Citations` |

`StockComponent` is a separate authored blank with `form`, `dia_mm`,
`length_mm`, `section_mm`, `note`, and `cite`; see [plan stock](plan.md#stock).
Shared inventory accepting this shape does not assert an authored candidate is
on hand.

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
| `measured` | `Measurement` |
| `envelope` | `MachineEnvelope` |
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
| `flute_len` | `MeasuredLength` |
| `oal` | `MeasuredLength` |
| `head_in` | `float` |
| `max_offset_in` | `float` |
| `dial_in` | `float` |
| `length_in` | `MeasuredLength` |
| `min_bore_in` | `float` |
| `tip_in` | `float` |
| `jaw_width_in` | `float` |
| `opening_in` | `float` |
| `jaw_height_in` | `MeasuredLength` |
| `bed_height_mm` | `MeasuredLength` |
| `diameter_in` | `float` |
| `thickness_in` | `float` |
| `resolution_in` | `float` |
| `runout_max_in` | `float` |
| `gauge_len` | `MeasuredLength` |
| `grip_mm` | `MeasuredLength` |
| `max_shank_in` | `float` |
| `lead_mm` | `float` |
| `projection_mm` | `MeasuredLength` |
| `sfm` | `float` |
| `chip_load_mm_per_tooth` | `float` |
| `dia_mm` | `MeasuredLength` |
| `dia_in` | `MeasuredLength` |
| `shank_mm` | `MeasuredLength` |
| `flute_len_mm` | `MeasuredLength` |
| `flute_len_in` | `MeasuredLength` |
| `oal_mm` | `MeasuredLength` |
| `oal_in` | `MeasuredLength` |
| `gauge_len_mm` | `MeasuredLength` |
| `gauge_len_in` | `MeasuredLength` |
| `projection_in` | `MeasuredLength` |
| `spindle_to_table_max_mm` | `float` |
| `jaw_height_mm` | `MeasuredLength` |
| `height_mm` | `MeasuredLength` |
| `height_in` | `MeasuredLength` |
| `length_mm` | `MeasuredLength` |
| `width_mm` | `MeasuredLength` |
| `width_in` | `MeasuredLength` |
| `capacity_mm` | `float` |
| `bed_height_in` | `MeasuredLength` |
| `nose_radius_mm` | `float` |
| `reach_mm` | `MeasuredLength` |
| `dia` | `MeasuredLength` |
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
