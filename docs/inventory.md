# Shop inventory — `inventory.toml`

The root groups are `machines`, `tools`, `holders`, `fixtures`, `gauges`,
`consumables`, and `stock`; there are no legacy `workholding` or `measuring`
aliases. Category maps use authored identity keys. `members` is a recursively
modeled InventoryItem map. `source` may be a source string or Source record.
Named set members/coverage may resolve without pretending an unlisted member
was measured or purchased. Explicit `present = false` means missing;
an item-level `verify = true`, an unverified `source`, or explicitly unknown
presence makes that item's identity unresolved. Whether a particular
dimension is *measured* is decided only by that fact's own record (see
[M5](#measured-envelopes-and-installed-tool-stacks-m5)).

A consumed single-length fact is authored once per stem: an explicit `_mm`
key, an `_in` key converted with exactly 25.4 mm/in, or a bare key with explicit
`units = "mm"`, `"in"`, or `"inch"`; two spellings of that fact are rejected
rather than ranked. Collection/coverage fields such as `sizes_mm`/`sizes_in`,
`range_mm`/`range_in` and `width_mm`/`width_in` are not duplicate single-length
facts; mixed metric/inch sets may declare both. Do not manufacture nominal diameters from a catalog label unless
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
counts are positive integers. For engagement, the selected tool's
`projection_mm` entry for the selected holder takes precedence over
`oal_mm - holder.grip_mm`. Neither flute length nor holder gauge length
substitutes for projection.
Engagement uses only the resolved `endmill` / `endmill_set` family on cutting
operations with authored DOC. Long drills, reamers, taps and lathe tools do not
receive a milling DOC-halving recommendation.

M4 kernel geometry reads explicit-unit dimensions only. A vise enters the
FreeCAD job solely when `jaw_height`, `jaw_width`, `jaw_depth` and `opening`
resolve to positive lengths through the same single-spelling `_mm` / `_in`
lookup as every other rule and the fixture is not `verify = true` /
unknown-presence; the parallels fixture needs a positive `height_mm` /
`height_in`, and its optional `length` (along the jaws) and `width` (along the
clamp axis), resolved the same way, are what let the kernel draw the parallel
solids once the plan declares `parallels_centres_mm`. These
are the only sources of fixture solids: `jaw_depth_mm` / `jaw_depth_in` is the
physical jaw-plate thickness along the gripping normal and is never synthesized
from jaw width, jaw height, bed height or any other dimension. A tool enters an
op's geometry job when `dia`, `flute_len` and `oal` resolve and a holder when
`gauge_dia` and `gauge_len` resolve; the holder cylinder uses `gauge_dia`
(`gauge_dia_mm` / `gauge_dia_in`), not `shank` or collet capacity. Any missing or
unverified dimension is named in the job's reason text and the dependent
geometry rules stay `?`. The shipped example vise is `verify = true` without
`jaw_depth`, and its parallels declare `thickness_in` rather than `height`, so
the shipped examples cannot produce a modeled fixture solid; see
[geometry rules](rules-geometry.md).

## Measured envelopes and installed tool stacks (M5)

`machines.<id>.envelope` is the one home for the mill limits that rules read:
usable X/Y/Z travel and spindle-nose-to-table maximum and minimum. M1
`headroom` and the M5 `envelope`/`travel` screens read this same block; a mill
carries no top-level `spindle_to_table_max_in`, `travel_in`/`travel_mm` or
`table_in` copy, and the schema rejects one. Table length/width, T-slot pitch,
spindle taper and R8/ER-collet-chuck/drill-chuck stack heights are not envelope
fields: no rule reads them, so nothing asks the shop to measure them. The
spindle taper stays vendor identity under `machines.<id>.spindle`.

```toml
[machines.my_mill.envelope]
spindle_to_table_max_mm = "unknown"
spindle_to_table_min_mm = "unknown"

[machines.my_mill.envelope.travel_mm]
x = "unknown"
y = "unknown"
z = "unknown"

[holders.my_holder]
gauge_len_mm = "unknown"
grip_mm = "unknown"

[tools.my_endmill]
oal_mm = "unknown"

[tools.my_endmill.projection_mm]
my_holder = "unknown"
```

For a measured fact replace the unknown with
`{ value = <actual measurement>, measured = { by = "<operator>", date = "YYYY-MM-DD", instrument = "<actual instrument>" } }`.
`by`, `date` and `instrument` must be nonblank known strings. Do not put these
template placeholders into operative inventory. A vendor copy instead carries
`{ value = <nominal>, verify = true }`.

Trust is fact-local. A physical dimension an M5 rule reads (envelope limits,
fixture bed/parallel/support heights, holder gauge and grip, tool OAL, the
tool/holder projection, cutter diameter, drill point angle, reamer lead) counts
as measured only when that fact's own record carries a complete
`measured = { by, date, instrument }` and no `verify = true` or `"unknown"`. Nothing is
inherited or inferred: `measured` on an envelope block, an item root or a
`source` record is rejected by the schema; `source.verify`, `coverage` text,
`present`, a date or a citation is provenance, not measurement; an explicit
fact-local `verify = true` leaves the fact unresolved even beside a complete
`measured`. A scalar vendor nominal (`spindle_to_table_max_in = 17` or
`{ value = 17, verify = true }`) stays in the finding's `numbers` as evidence
and yields `?`, never a pass or a measured overrun. Clearing `verify` without
a `measured` record is not measurement either.

Each length stem has one authored unit key: `gauge_len_mm` or `gauge_len_in`,
`oal_mm` or `oal_in`, `projection_mm` or `projection_in`, `bed_height_mm` or
`bed_height_in`. A suffixless `gauge_len`, or a second unit spelling beside the
first, is rejected, so a measured `_in` fact can never be shadowed by an
unmeasured `_mm` one. `travel_mm` / `travel_in` use `x`, `y`, `z`. Inch facts
convert by exactly 25.4.

Gauge is **mounted spindle nose to holder exit face** and already includes the
spindle/chuck stack, so no separate stack height is recorded or added.
Projection is **holder exit face to installed tool tip** and belongs to one
(tool, holder, insertion) triple: it lives on the tool as
`tools.<tool>.projection_mm` (or `_in`), a map keyed by the full exact holder
reference the operation selects (for example `"r8-collets-lms-4860/3-8in"`).
A holder, fixture, machine or gauge never carries projection, and a tool never
carries a holder-wide or tool-wide scalar projection. When the selected pair
has no entry, the rules use measured tool OAL minus the selected holder's
measured grip; an `"unknown"` pair entry does not fall through to another
holder's number, and flute length never substitutes.

Fixture bed height (`bed_height_mm/in`) is the table-to-bed distance that every
vise stack uses; jaw height (`jaw_height_in`) is the jaw's height above the bed
for the separate jaw-obstruction check, never a stack layer. Parallels and
support blocks carry their own heights. `point_angle` accepts the same
`{ value, measured, verify }` record in degrees.

`prechips tools --measure [--plan PLAN ...]` lists the measurement debt behind
the current reports: every `numbers.measurements` entry that an unresolved
applicable finding emits for the given plans (default: the five shipped example
plans), sorted and deduplicated by scoped report id, including set-member and
tool/holder-pair ids such as `holders.r8-collets-lms-4860/3-8in.gauge_len` and
`tools.endmills-lms-6784/3-8in-4fl.projection.r8-collets-lms-4860/3-8in`. An
`"unknown"` fact a rule needs is listed even without `verify` debt. It is not a
reflection over every declared field: items and fields no rule consumes do not
appear, and it invents no set members or purchases. `--inventory` (or
`PRECHIPS_INVENTORY`) overrides the plans' declared inventory; without it each
plan's own inventory applies. Plan-input ids and instructions are prefixed with
the plan path. When multiple effective inventories apply, inventory ids and
instructions are qualified by their source path so equal item names cannot
merge unrelated facts; plans sharing an inventory still share its measurement
debt. Every other `tools` display still requires `--inventory` or
`PRECHIPS_INVENTORY`. JSON emits the same entries with ids,
instructions, units and citations: lengths use mm, point angles use degrees,
and add/resolve instructions use identity units. Normal `tools` prints the envelope and
marks each limit measured or unmeasured. Applicable M5 `?` sheet sentences also
state what to measure and how; unresolved tools, holders, fixtures and supports
are told to add or resolve an owned identity, not to measure an item the shop
does not own.

### Measurement records

| Record | Fields |
|---|---|
| `Measurement` | Required strings `by`, ISO calendar `date` (`YYYY-MM-DD`), `instrument`; none may be blank or `"unknown"` |
| `LengthMeasurement` | Required `value: Number`; optional `measured: Measurement`, `verify: bool` (each may be `"unknown"`); no `cite` |
| `MeasuredLength` / `MeasuredAngle` | `Number` or `LengthMeasurement` (mm/in, or degrees for `point_angle`) |
| `EnvelopeTravel` | `x`, `y`, `z: MeasuredLength`; no block metadata |
| `MachineEnvelope` | `travel_mm` or `travel_in: EnvelopeTravel`; `spindle_to_table_max_mm/in`, `spindle_to_table_min_mm/in: MeasuredLength`; no block metadata |
| `ProjectionMap` | `dict[full holder reference, MeasuredLength]`; tools only |

All envelope/travel fields are optional and accept `"unknown"`; their absence
remains measurement debt. A date or a citation is provenance, not an automatic
claim that a fact is measured.

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
| `taper` | `str` |
| `sku` | `str \| int` |
| `verify` | `bool` |
| `present` | `bool` |
| `center_cutting` | `bool` |
| `swivel_base` | `bool` |
| `scroll` | `bool` |
| `independent` | `bool` |
| `envelope` | `MachineEnvelope` |
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
| `point_angle` | `MeasuredAngle` |
| `flute_len` | `float` |
| `oal` | `MeasuredLength` |
| `head_in` | `float` |
| `max_offset_in` | `float` |
| `dial_in` | `float` |
| `length_in` | `float` |
| `min_bore_in` | `float` |
| `tip_in` | `float` |
| `jaw_width_in` | `float` |
| `jaw_width_mm` | `float` |
| `jaw_depth_in` | `float` |
| `jaw_depth_mm` | `float` |
| `opening_in` | `float` |
| `opening_mm` | `float` |
| `jaw_height_in` | `float` |
| `bed_height_mm` | `MeasuredLength` |
| `diameter_in` | `float` |
| `thickness_in` | `float` |
| `resolution_in` | `float` |
| `runout_max_in` | `float` |
| `grip_mm` | `MeasuredLength` |
| `max_shank_in` | `float` |
| `lead_mm` | `MeasuredLength` |
| `projection_mm` | `ProjectionMap` (tools only) |
| `sfm` | `float` |
| `chip_load_mm_per_tooth` | `float` |
| `dia_mm` | `MeasuredLength` |
| `dia_in` | `MeasuredLength` |
| `shank_mm` | `float` |
| `flute_len_mm` | `float` |
| `flute_len_in` | `float` |
| `oal_mm` | `MeasuredLength` |
| `oal_in` | `MeasuredLength` |
| `gauge_len_mm` | `MeasuredLength` |
| `gauge_len_in` | `MeasuredLength` |
| `gauge_dia` | `float` |
| `gauge_dia_mm` | `float` |
| `gauge_dia_in` | `float` |
| `projection_in` | `ProjectionMap` (tools only) |
| `jaw_height_mm` | `float` |
| `height_mm` | `MeasuredLength` |
| `height_in` | `MeasuredLength` |
| `length_mm` | `float` |
| `width_mm` | `float` |
| `width_in` | `float` |
| `capacity_mm` | `float` |
| `bed_height_in` | `MeasuredLength` |
| `nose_radius_mm` | `float` |
| `reach_mm` | `float` |
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

## Length and angle facts

There are no `Travel` or `Table` records: travel and spindle-to-table limits
live only under `envelope` (see [measurement records](#measurement-records)),
and the former `table_in` length/width/`t_slot` block is not modeled. The
`t_slot_in` text on a clamping kit is an identity label, not a measured pitch.
Inventory loading rejects a `measured` record on an item root, an envelope
block, a `source` or a member; the only measurement evidence is the
`LengthMeasurement`/`MeasuredAngle` record on the fact itself.

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
