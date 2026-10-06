# Shop inventory — `inventory.toml`

The root groups are `machines`, `tools`, `holders`, `fixtures`, `gauges`,
`services`, `consumables`, and `stock`; there are no legacy `workholding` or `measuring`
aliases. Category maps use authored identity keys. `members` is a recursively
modeled InventoryItem map. `source` may be a source string or Source record.
`services` are outside processes the shop sends work to (a coating vendor), not
shop-owned kit; a plan `coating` op's `process` names a `services` item or a
`consumables` entry. A `consumables` entry is an id mapping to the in-house
product names; an explicitly unknown product list leaves that process unresolved.
Named set members/coverage may resolve without pretending an unlisted member
was measured or purchased. Explicit `present = false` means missing;
an item-level `verify = true`, an unverified `source`, or explicitly unknown
presence makes that item's identity unresolved for the declared-input rules.
Whether a particular dimension is *measured* is decided only by that fact's
own record (see
[M5](#measured-envelopes-and-installed-tool-stacks-m5)), and whether a
nominal dimension enters M4 kernel geometry is decided the same fact-local
way (see [kernel geometry facts](#kernel-geometry-facts-m4)); neither reads
the item, set root, member container or source flags around the fact.

`name` is an optional display name an item or a set member may carry; the
traveler prints it whole in place of the name it would derive from the item's
kind or identity key (`name = "4x6 bandsaw"`, a kit member `name = "cap bridge
clamp"`). A member's name is its own: a named set does not name its members,
and an unnamed member still prints as its key words and its own kind
(`bracket bridge strap clamp`). No rule reads `name`.

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
A `follow_rest` / `steady_rest` fixture that a plan `hold.supports` table
selects (`{ ref, ops, jaw_lead_mm }` / `{ ref, ops, at_z_mm }`) declares its jaw
capacity as fact-local measured `capacity_min_mm` / `capacity_max_mm` (or
`_in`): the work diameters the rest can ride on, inclusive. `turning_deflection`
uses the rest span only for an op whose ridden diameter is inside that capacity;
an unmeasured or unverified capacity leaves deflection unknown and is listed in
the measurement checklist. The kernel draws the rest from its own measured
solid fields (below and [rules-geometry](rules-geometry.md#follow-and-steady-rests)).
Hold identities resolve through `fixtures`, `holders`, then `machines`, so a
machine-mounted dividing head is not an unresolved fixture. Its declared
`centre_height_in` locates the spindle axis above its mounting base for the
headroom screen; `hold.pose.origin_mm[2]` locates that axis in the setup frame.
`height` / `length` / `width` still describe the head body; `bed_height` is not
a substitute for the centre. A dividing head without declared gripping capacity
is `not_applicable` to the diameter screen; a machine or dividing head with
declared collet sizes or chuck ranges is checked.

For indexing, a dividing head can live in `machines` (the example is `BS-0`) or
`fixtures`. `worm_ratio`, `direct_index` and every `plate_holes` circle are
arithmetic inputs; `verify = true` keeps the chosen setting tentative. Hole
counts are positive integers. For engagement, the selected tool's
`projection_mm` / `projection_in` entry for the selected holder is the
projection whenever that entry exists: an entry that is `"unknown"` or
carries its own debt keeps the op unresolved rather than falling back, and
only an absent pair uses `oal - holder.grip`. Neither flute length nor holder
gauge length substitutes for projection.
Engagement uses only the resolved `endmill` / `endmill_set` family on cutting
operations with authored DOC. Long drills, reamers, taps and lathe tools do not
receive a milling DOC-halving recommendation.

## Bandsaw machines and blades

Both `machines.<saw>.kind` and `tools.<blade>.kind` may be `"bandsaw"`.
The machine declares `blade_speed_sfm = [min, max]`, positive ordered feet/minute
limits. The blade declares its `material` for cutting-data selection and a
positive `kerf_mm` or `kerf_in`, using the ordinary `MeasuredLength` form or
trusted nominal scalar. Declaring kerf in both units is rejected, and explicit
fact-local verification debt withholds geometry. Illustrative example
measurements must use the examples policy's plausible/not-measured label.

Saw operations need no spindle taper, holder, shank diameter, tool OAL or
projection. A mill/bench may host the saw operation but must also declare its
actual blade-speed range for a sourced speed recommendation. The hold resolves
an ordinary fixture; no machine identity silently supplies an integral vise.
See [plan saw cut-off](plan.md#saw-cut-off) for the plane and keep-side contract.


## Kernel geometry facts (M4)

M4 kernel geometry reads explicit-unit length facts through the same
fact-local lookup as the M5 screens, with shop measurement *not* required.
Every dimension the kernel consumes is a `MeasuredLength`: a plain nominal
number, or a `{ value, measured, verify }` record. It enters the FreeCAD job
when it resolves to a positive length through the single-spelling `_mm` /
`_in` lookup and its own record carries no debt — no `verify = true` or
`verify = "unknown"`, and no incomplete `measured` record. A nominal number
needs no `by`/`date`/`instrument`; a fact whose own record says
`verify = true` or whose `measured` is incomplete is debt for that dimension
only. An item's `verify`, `present` or `source` flags, a set root's or member
container's flags and `coverage` text are identity provenance for the
declared-input rules: they never withhold a numeric fact from the kernel, and
nothing is inherited from them. The M5 `envelope` and `travel` screens read
the same holder gauge/grip, tool OAL and projection facts with measurement
required (and `headroom` the envelope limits), so an operation can be
geometrically checked while its spindle stack is still M5 measurement debt.

A vise enters the job solely when `jaw_height`, `jaw_width`, `jaw_depth` and
`opening` all resolve that way; the parallels fixture needs a positive
`height`, and its optional `length` (along the jaws) and `width` (along the
clamp axis), resolved the same way, are what let the kernel draw the parallel
solids once the plan declares `parallels_centres_mm`. A `blocks_123` riser
item supplies `length`, `width` and `height` the same way. These are the vise
sources of fixture solids: `jaw_depth_mm` / `jaw_depth_in` is the physical
jaw-plate thickness along the gripping normal and is never synthesized from
jaw width, jaw height, bed height or any other dimension.

Other holding solids come from the same accepted-fact rule, never defaults:

- `chuck_3jaw` / `chuck_4jaw`: `body_dia`, `body_length`, `bore_dia` (bore
  smaller than body), `jaw_width` (tangential), `jaw_height` (radial, outward
  from the grip) and `jaw_depth` (axial, ahead of the body face). A
  `dividing_head` names its chuck from the plan (`hold.chuck`).
- `follow_rest`: `jaw_width` (tangential), `jaw_height` (radial, outward from
  the ridden diameter) and `jaw_depth` (axial), each fact-local measured, plus
  `jaw_angles_deg`: the jaw directions about the spindle axis in degrees from
  the cutting tool (e.g. `[90, 180]` for a top and a back jaw). Any one missing
  leaves the rest undrawn and the ops it serves `unknown`, naming the field.
- `steady_rest`: `body_dia` (the ring's outside diameter) and `body_length`
  (its axial length), each fact-local measured; otherwise the rest is an
  undrawn possible obstacle (a gap naming the field), so clear turning samples
  and `fixture_interference` stay `unknown`.
- `dead_centre` fixtures: `dia` (shank), `length` (tip to quill face) and
  `point_angle` (included cone angle, degrees); the quill is the machine's
  `tailstock.quill_dia` (a dividing head's own `tailstock` when it has one).
- Any item (angle plate, `dividing_head`, custom fixture, `clamping_kit`
  member such as a strap) may author `solids = [{name, shape, at_mm,
  size_mm}]` boxes or `{name, shape = "cylinder", at_mm, axis, dia_mm,
  length_mm}` cylinders in its own frame. Each primitive is trusted on its
  own: a primitive whose record carries `verify = true` / `"unknown"` or an
  incomplete `measured` is not drawn and is named as debt.
- A primitive with `void = true` (a bore, tapped or clearance hole, stud
  slot) is not drawn: it is cut from the same `solids` list's other
  primitives, or only from those it names in `cuts = ["<name>", …]`, and
  never from another item's or member's solids. An untrusted or malformed
  void withholds the solids it would cut (named debt) rather than draw them
  uncut. A strap member models its whole clamp assembly in one list: beam,
  slot void (`cuts = ["beam"]`), stud, heel, nut and washer (washer bore with
  `cuts = ["washer"]`). Primitives of one list are one part and never checked
  against each other; each posed clamp's list must touch the stock to bear.
- A trusted void in the holding fixture may carry an optional shop-caption
  `label = "Strap stud holes"`. The setup render places its leader at the void's
  centre after applying `hold.pose`, and records the label and posed centre in
  `scene.fixture_detail_labels`. The caption neither creates geometry nor
  overrides the void's measurement or verification debt.
- A shop-made item (`kind = "custom"`, or any item / member flagged
  `shop_made = true`) gets one SHOP-MADE FIXTURE table on sheet 2 of the first
  setup using it at those poses; later setups at the same poses point back to it.
  Each row is one made primitive (identical primitives group into one row,
  named by their shared `label` or the words their names share) with its size and
  setup-frame position (box X / Y / Z extents, cylinder axis), placed by
  `hold.pose`, the clamp entry's `pose` or `stop_pose`. A void is listed in the
  row of the made primitive it cuts (the first made name in `cuts`, else the one
  holding its centre) as "with N × <fastener or size>: positions"; a void that
  cuts only bought hardware is not listed. Per-primitive `supply` is `made`
  (default), `bought` (hardware: one "Bought hardware (not made)" line under the
  table, named by its `fastener` or its name and size) or `existing` (already in
  the shop, such as a machine's vise jaws drawn for clearance: not listed).
  Sizes and positions print at shop policy `numbers.fixture_make_decimals`; the
  fit of a primitive with `locates` (the bore cut in it, else the primitive
  itself) and shim nominals print at the drawing precision. Optional texts
  `locates = "<part face>"` and `fastener = "<thread / fastener>"` fill the
  Locates and Fastener columns; `shim = true` marks an adjustable shim stack
  whose drawn thickness HOLD prints as the nominal to fit with feeler gauges.
  An angle plate's (or posed shop-made fixture's) lowest made box is its base:
  HOLD prints its underside Z, an angle plate's working face (local y = 0,
  facing local -y) and the base's `fastener` as the hold-down. None of these
  texts creates geometry or trust.

For `approach = "rotary"`, the selected hold must resolve to a `dividing_head`;
its plan `hold.chuck` names a dimensioned chuck as above. The plan supplies
`hold.pose` (origin at the chuck jaw-face centre, pose +z out toward the work),
`jaw_clock_deg` and `grip_mm`. Pose z is the head axis and must be horizontal
in the setup, perpendicular to setup Z. The head's own authored `solids`, the
chuck body/jaws and any tailstock or clamps provide the modeled obstacles;
indexing ratios or a vendor photograph do not supply missing solids or poses.
The chuck rotates with the work; the head body, tailstock and clamps do not.
Continuous rotation uses the existing plan record
`hold.index = { fixture = "<head>", rotation = "continuous" }`, without
`positions` or `angle_deg`; it needs a verified dividing-head identity, not a
plate landing calculation.

Rotary cutting uses the same vertical mill cutter and holder facts below:
tool `dia`, `flute_len`, `oal`, holder `gauge_dia`, `gauge_len`, and the
selected tool/holder projection (or the permitted OAL-minus-grip fallback).
No lathe insert, toolpost or new rotary-specific inventory fields are implied.
Each rotary op's own cutter and holder apply to its window, so a face may be
covered by several ops with different cutters (for example a smaller endmill
windowed into a shoulder); the geometry rules union their window portions.
Missing or unresolved dimensions keep their dependent screens `?`; a modeled
sample pose does not establish head torque, locking or collision-free motion
between samples.

A tool enters an
op's geometry job when `dia`, `flute_len` and `oal` resolve and a holder when
`gauge_dia` and `gauge_len` resolve; the holder cylinder uses `gauge_dia`
(`gauge_dia_mm` / `gauge_dia_in`), not `shank` or collet capacity. The op's
projection is the selected pair's entry in `tools.<tool>.projection_mm` /
`projection_in` ([below](#measured-envelopes-and-installed-tool-stacks-m5));
only when that pair has no entry is it `oal` minus the selected holder's
`grip`, each from its own accepted fact. Any missing dimension or fact-local
debt is named in the job's reason text and the dependent geometry rules stay
`?`. The shipped example vise (`fixtures.vise-pm-6`) records shop-measured
`jaw_height_in`, `jaw_width_in`, `jaw_depth_in`, `opening_in` and
`bed_height_in` (2026-10-05, each with its own `measured` record and the
vendor nominal kept beside it as a comment), so a shipped vise setup with a
STEP and a complete pose draws jaw solids; its item-level `verify = true` is
identity debt elsewhere, not a geometry veto. The shipped parallels declare
no `width` and no shipped plan declares `parallels_centres_mm`, so no shipped
setup draws parallel solids. See
[geometry rules](rules-geometry.md).

For a spot or drill operation the kernel also consumes the selected tool's
existing `point_angle` (`MeasuredAngle`, degrees; no new schema field) as its
point profile. The fact is accepted the same fact-local way, nominal included;
a missing, `"unknown"` or debt-carrying angle reaches the job as unknown and is
never defaulted. It is required for a spot too, even though a spot's tip
endpoint formula uses only its depth: the kernel cuts with the real point cone
and body, so an unknown angle leaves that op's accessibility `?` and later
stock unresolved. See [geometry rules](rules-geometry.md#accessibility).

## Measured envelopes and installed tool stacks (M5)

`machines.<id>.envelope` is the one home for the mill limits that rules read:
usable X/Y/Z travel and spindle-nose-to-table maximum and minimum. M1
`headroom` and the M5 `envelope`/`travel` screens read this same block; a mill
carries no top-level `spindle_to_table_max_mm/in`, `travel_in`/`travel_mm` or
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
a `measured` record is not measurement either. Kernel geometry and engagement
read the same facts with measurement *not* required, so the readiness they
report is nominal-geometry readiness, not the physical measurement readiness
these screens report; both honour the fact's own `verify`/`measured` debt.

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
carries a holder-wide or tool-wide scalar projection: the schema rejects
`projection_mm`/`projection_in` outside `tools` and rejects a tool whose
projection is a bare number rather than a map. When the selected pair has an
entry, that entry alone decides: an `"unknown"` or debt-carrying entry keeps
every consumer unresolved and never falls through to another holder's number
or to OAL − grip. Only when the pair has no entry do the rules use the
selected tool's OAL minus the selected holder's grip — each measured for the
M5 screens, each an accepted nominal for kernel geometry and engagement — and
flute length never substitutes.

Fixture bed height (`bed_height_mm/in`) is the table-to-bed distance that every
vise stack uses; jaw height (`jaw_height_in`) is the jaw's height above the bed
for the separate jaw-obstruction check, never a stack layer. Parallels and
support blocks carry their own heights. `point_angle` accepts the same
`{ value, measured, verify }` record in degrees.

`prechips tools --measure [--plan PLAN ...]` lists the measurement debt behind
the current reports: every `numbers.measurements` entry that an unresolved
applicable finding emits for the given plans (default: the four pilot plans for
shaft, rocker, bracket and the sole built-up cone), sorted and deduplicated by
scoped report id, including set-member and
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

This evaluates the actual applicable rules and may need native in-process
stock facts. A successful debt-list command is not a machining-readiness pass;
unavailable physical facts remain unknown.

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
claim that a fact is measured. Every dimension kernel geometry consumes — tool
`dia` / `flute_len` / `oal`, holder `gauge_dia` / `gauge_len` / `grip`, the
projection map, vise `jaw_height` / `jaw_width` / `jaw_depth` / `opening` and
parallels `height` / `length` / `width` — is typed `MeasuredLength`, so a shop
can record a measurement on any of them; kernel geometry accepts the nominal
form, the M5 screens require the measured form.

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
| `services` | `dict[str, InventoryItem \| Unknown] \| Unknown` | Optional |
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
| `name` | `str` |
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
| `blade_speed_sfm` | `[Number, Number]` (machine blade-speed limits) |
| `kerf_mm` / `kerf_in` | `MeasuredLength` (selected bandsaw blade) |
| `flute_len` | `MeasuredLength` |
| `oal` | `MeasuredLength` |
| `head_in` | `float` |
| `max_offset_in` | `float` |
| `dial_in` | `float` |
| `length_in` | `MeasuredLength` |
| `min_bore_in` | `float` |
| `tip_in` | `float` |
| `jaw_width_in` | `MeasuredLength` |
| `jaw_width_mm` | `MeasuredLength` |
| `jaw_depth_in` | `MeasuredLength` |
| `jaw_depth_mm` | `MeasuredLength` |
| `opening_in` | `MeasuredLength` |
| `opening_mm` | `MeasuredLength` |
| `jaw_height_in` | `MeasuredLength` |
| `bed_height_mm` | `MeasuredLength` |
| `diameter_in` | `float` |
| `thickness_in` | `float` |
| `resolution_in` | `MeasuredLength` (on a machine, as `resolution_mm`) |
| `runout_max_in` | `float` |
| `grip_mm` | `MeasuredLength` |
| `max_shank_in` | `float` |
| `lead_mm` | `MeasuredLength` |
| `projection_mm` | `ProjectionMap` (tools only) |
| `sfm` | `float` |
| `chip_load_mm_per_tooth` | `float` |
| `feed_mm_rev` | `float` |
| `dia_mm` | `MeasuredLength` |
| `dia_in` | `MeasuredLength` |
| `shank_mm` | `float` |
| `flute_len_mm` | `MeasuredLength` |
| `flute_len_in` | `MeasuredLength` |
| `oal_mm` | `MeasuredLength` |
| `oal_in` | `MeasuredLength` |
| `gauge_len_mm` | `MeasuredLength` |
| `gauge_len_in` | `MeasuredLength` |
| `gauge_dia` | `MeasuredLength` |
| `gauge_dia_mm` | `MeasuredLength` |
| `gauge_dia_in` | `MeasuredLength` |
| `projection_in` | `ProjectionMap` (tools only) |
| `jaw_height_mm` | `MeasuredLength` |
| `height_mm` | `MeasuredLength` |
| `height_in` | `MeasuredLength` |
| `length_mm` | `MeasuredLength` |
| `width_mm` | `MeasuredLength` |
| `width_in` | `MeasuredLength` |
| `capacity_mm` | `float` |
| `capacity_min_mm` / `capacity_min_in` | `MeasuredLength` (follow/steady rest jaw capacity) |
| `capacity_max_mm` / `capacity_max_in` | `MeasuredLength` (follow/steady rest jaw capacity) |
| `jaw_angles_deg` | `list[Number]` (follow rest jaw directions about the spindle, degrees from the tool) |
| `body_dia_mm` / `body_dia_in` | `MeasuredLength` (chuck body; steady rest ring outside diameter) |
| `body_length_mm` / `body_length_in` | `MeasuredLength` (chuck body; steady rest ring axial length) |
| `blade_width_mm` / `blade_width_in` | `MeasuredLength` (grooving/parting blade front-edge width) |
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
| `ra_range` | `list[Number]` (two items, µm Ra; roughness gauges, read by inspection finish_ra) |
| `resolution_mm` | `MeasuredLength` (inspection trusts only the fact's own qualifiers: `verify = true`/`"unknown"` or an incomplete `measured` stays unknown, never pass or error; on a machine, its nominal value is the DRO grid every printed coordinate and depth rounds to the safe side on, else 0.001 plan units: [rules-coordinates](rules-coordinates.md)) |
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
| `rotation` | `"cw"` / `"ccw"` / `{value, measured, verify}` |

`rotation` is the spindle's cutting rotation viewed from above, looking down
setup -Z (a right-hand cutter runs `cw`, M03). It may be bare or a labelled
fact `{ value = "cw", measured = {by, date, instrument} }`; a labelled value
flagged `verify = true` counts as undeclared. With an op's `direction`
(`conventional`/`climb`) it fixes the cutting order of contour tables
(see [coordinates](rules-coordinates.md)); absent, that order stays unknown.

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
