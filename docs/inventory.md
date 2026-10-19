<a id="shop-inventory--inventorytoml"></a>

# Shop inventory: `inventory.toml`

`inventory.toml` declares the machines, tooling, workholding, gauges, processes
and stock available to a plan. This reference defines their identities, field
types, units and trust requirements. A declared item or nominal dimension does
not establish that the shop owns it or has measured it.

Use the [quickstart](manual/quickstart.md), [tutorial](manual/tutorial.md) or
[worked demonstration](manual/demo.md) to run a bundle. For command options, see
the [CLI catalog](reference/cli.md); for callable interfaces, see the
[Python API catalog](reference/python-api.md). The
[troubleshooting guide](manual/troubleshooting.md) covers input errors and
measurement debt, and the [FAQ](manual/faq.md) explains the product's limits.

On this page:

- [Identity, units and tool geometry](#identity-and-display-names)
- [Manual dies and die stocks](#manual-dies-and-die-stocks)
- [Manual taps and wrenches](#manual-taps-and-wrenches)
- [Bandsaws, hand saws and slitting saws](#bandsaw-machines-and-blades),
  [manual-arc equipment](#manual-arc-kit) and [edge finders](#edge-finder)
- [Purchased tooling and receipt checks](#purchased-tooling)
- [Kernel geometry facts](#kernel-geometry-facts-m4) and
  [measured machine limits and installed stacks](#measured-envelopes-and-installed-tool-stacks-m5)
- [Root fields](#root-fields), [area-hold consumables](#area-holds),
  [stock](#stock) and [item field catalog](#inventoryitem)
- [Spindle](#spindle) and other [nested machine records](#leadscrew)
- [Mechanical dial source facts](#mechanical-dial-source-facts)

## Inventory identity and units

### File selection and schema

A plan's `inventory` path resolves relative to the plan file and must stay
inside its bundle. An explicit inventory override takes precedence; if neither
the override nor the plan supplies a path, `PRECHIPS_INVENTORY` is the fallback.
Override and environment paths resolve from the current working directory.
See the [CLI catalog](reference/cli.md) for the commands that accept overrides.

See [shared input conventions](plan.md#input-conventions) for TOML validation,
`Number`, `Vector`, `Citations`, omitted fields and literal `"unknown"`.
Inventory-specific field definitions are in
[`model.py`](../src/prechips/model.py).

Inventory category/member maps and declared dictionaries such as
`nominal_dia_mm`, `candidates`, `holders` and `plate_holes` accept authored
keys. Missing inventory facts do not establish known absence or a pass;
the applicable rule decides which facts it needs.

### Identity and display names

The root groups are `machines`, `tools`, `holders`, `fixtures`, `gauges`,
`services`, `consumables` and `stock`. There are no `workholding` or `measuring`
aliases. Category maps use authored identity keys; `members` recursively maps
member keys to `InventoryItem` records. `source` accepts a source string or a
[Source record](#source).

Named set members or declared coverage can resolve an identity without
claiming that an unlisted member was measured or purchased. Explicit
`present = false` means missing. Item-level `verify = true`, an unverified
source or explicitly unknown presence leaves the identity unresolved for the
declared-input rules.

Dimension trust is separate. [M5](#measured-envelopes-and-installed-tool-stacks-m5)
requires a fact's own measurement record;
[M4](#kernel-geometry-facts-m4) accepts trusted nominal geometry. Neither
inherits dimension qualifiers from the item, set root, member container or
source.

An item's optional `name` is its display name. The setup sheet prints it whole
instead of deriving a name from the kind or key, for example
`name = "4x6 bandsaw"` or a kit member's `name = "cap bridge clamp"`.
Members own their names: a named set does not name its members. An unnamed
member prints its own key words and kind, such as `bracket bridge strap clamp`.
No rule reads `name`.

`services` are outside processes, such as a coating vendor, rather than
shop-owned equipment. A coating operation's `process` names a service or an
untyped consumable. Their product and display-name behavior is defined under
[Root fields](#root-fields).

### Units and set members

Author each consumed single-length fact once, using a supported `_mm` key,
`_in` key or bare key with explicit `units = "mm"`, `"in"` or `"inch"`.
Supported bare keys still depend on the field schema. Inch values convert by
exactly 25.4 mm/in. Two spellings of one fact are rejected, not ranked.
Collection fields such as `sizes_mm` / `sizes_in`, `range_mm` / `range_in`
and `width_mm` / `width_in` when used as coverage are not duplicate
single-length facts; mixed metric/inch coverage may declare both.

Do not derive nominal diameters from catalog labels unless supported
identity/coverage resolution or an explicit `nominal_dia_mm` map establishes
them. Nominal identity is not measured size. Inventory tool units can be
converted explicitly; drawing units are not silently converted.

Set `sizes_in` accepts a flat list or named groups. Every group's sizes are
declared choices; the group name is a label. `flutes` accepts one count or a
list. An `endmill_set` member `<size>in-<n>fl` resolves when the size appears in
any group and `n` is a declared flute count.

### Tool geometry and holders

Mill holder compatibility uses spindle taper. Lathe cutting-tool holders use
toolpost series; spindle-axis lathe tools use the tailstock-quill taper.
Collet capacity, range and maximum-shank checks are separate. A holder's
single nominal capacity accepts a tool shank from `capacity - IT6` through
`capacity`, the ISO 286 h6 band. IT6 comes from ISO 286-1:2010 Table 1. For a
3/8 in collet the band is 9.516-9.525 mm, so a measured shank below nominal can
fit. See [`tool_resolves`](rules-tools.md#tool_resolves).

Drill point angle, reamer lead, flute length, projection, holder gauge length
and fixture bed height are operative geometry. Do not infer them from unrelated
angles or overall dimensions. A centre drill's centre-seat angle is not its
drill-point angle.

A `center_drill_set` member used to drill a plan centre must carry its own
accepted Table 6 geometry:

- pilot `dia` (D);
- `pilot_len`, drill length C from countersink start to point tip, including
  the point;
- countersink `angle_deg`, inherited from the set's centre-seat angle unless
  the member overrides it;
- body `shank` (A);
- pilot `point_angle`.

These facts must carry no verification or unknown debt. The plan centre must
match them, and the point must be shorter than `pilot_len`. Reach still uses
`flute_len` as the cutting length.

`chart` is a source citation, never a chart downloaded at runtime. Resolved
`drill`, `drill_index` and `drill_set` tools used for `rough_profile` /
`chain_drill` select drilling cutting data, not an end-mill profile row. A cited
per-tool chart takes precedence over the shop row. Keep a chart that records a
deliberately lower feed; do not add one to work around row selection.
Mill drilling's axial mm/rev is chip load times resolved flute count. Missing
or nonpositive flutes leave it unresolved. See [cutting data](cutting-data.md).

Limit-gauge sets list the sizes physically held in `sizes_mm`:
`pin_gauge`, `pin_gauge_set` or `plug_gauge` for holes, and `ring_gauge` or
`snap_gauge` for a boss or shaft. A GO / NO-GO pair can name only listed sizes.
An unlisted size is an inspection error; absent `sizes_mm` leaves the pair
unknown. `range_mm` remains the span used for ordinary span/resolution checks.
See [GO / NO-GO limit checks](rules-inspection.md#go--no-go-limit-checks).

Printed inspection labels retain item/member identities and source ownership.
A writing area does not create a gauge or certify its presence, size or
capability. Unresolved inventory still needs the existing add/resolve or
measurement instruction; there is no separate inventory field for the blank.

### Manual dies and die stocks

A manual `die_thread` operation selects a real die through the existing tool
identity rules. For a `die_set` or `tap_die_set`, declare the selected die in
`members` and name it as `tools.<set>/<member>` in `op.tool`. A whole set is not
a selected die, and a size written only in a name or coverage note does not
declare that member. An explicit member inherits the set record, with its own
fields overriding the set's. Grouping one observed die under a set identity
does not establish ownership of the rest of that physical set. A resolved
individual `kind = "die"` is also accepted.

The selected die needs explicit `thread`, `thread_hand` and `thread_class`
facts matching the exported `external_thread` feature. `thread` is the nominal
size/pitch designation, not the member's display name; `thread_hand` is
`"right"`, `"left"` or `"unknown"`, separate from a turning tool's `hand`;
`thread_class` is the die's class designation. Missing or unsupported thread
facts remain unresolved.

The operation's `holder` selects `kind = "die_stock"`. A bare holder reference
looks in `holders`; a category-qualified reference such as
`tools.<die-stock>` can select an existing tool-category item. Its `fits` must
name the exact selected die identity, including the member, rather than just
the set or an assumed diameter. Bare and category-qualified spellings of the
same resolved identity are equivalent. Unknown fit remains debt; a known
different identity is a mismatch.

This hand assembly is not a spindle or toolpost stack. It supplies no powered
RPM or electronic tool-touch recipe. Tool/holder contradictions and missing
facts are checked by [manual die threading](rules-tools.md#manual-die-threading);
prior male blank and shoulder preparation remain separate operation-chain requirements.

### Manual taps and wrenches

A spindle-stopped `hand_tap` selects `kind = "tap"` or an explicitly declared
member of a `tap_set` / `tap_die_set` in `op.tool`. Whole-set selection and
member inheritance follow the [die identity rules](#manual-dies-and-die-stocks).
The selected tap's explicit `thread`, `thread_hand` and `thread_class` must
match the exported internal `thread` / `threaded_hole` feature.

Its `op.holder` selects a real `tap_wrench` or `tap_follower`. A bare reference
uses `holders`; a category-qualified `tools.<wrench-or-follower>` can select
an item already declared in `tools`. Fit can be established in either of
these ways:

- `fits` names the exact selected tap identity, including any member, using
  the same bare/qualified identity equivalence as a die stock.
- Explicit nominal tap-size capacity contains the tap's declared
  `dia_mm` / `dia_in` (or supported bare `dia` with units). A positive ordered
  pair in `range_mm` / `range_in` gives inclusive lower and upper limits; a
  scalar gives an upper limit. When no range key is declared, `capacity_mm` /
  `capacity_in` supplies the upper limit, or an accepted `capacity_in` pair
  supplies both limits. These are nominal tap sizes, not collet-shank fits.

A declared range takes precedence over capacity, including when the range
is `"unknown"`; an unknown range does not fall back to capacity. Without
resolved exact fit or usable capacity and tap diameter, fit remains unknown.
A known incompatible `fits` or out-of-capacity tap is an error even when
another declared fit fact agrees. A designation or member name alone does
not supply the tap diameter for this comparison.

The manual tap and holder require no spindle shank, taper, chuck or toolpost
assignment and create no digital tool-change retouch. A known nonzero
operation `rpm` is prohibited for both `hand_tap` and `die_thread`. See
[manual tapping](rules-tools.md#manual-tapping) for tool checks and
[manual threading](plan.md#manual-threading) for the operation contract.

### Holding capacity and indexing

M2 holding checks compare stock diameter with explicit `sizes_mm` / `sizes_in`
or a two-ended `range_mm` / `range_in`. A six-inch chuck body
(`diameter_in`) does not state jaw capacity. Tailstock and steady-support
exceptions must resolve to inventory or a named machine accessory. An
unconfirmed accessory cannot certify support.

A support is a centre support when its kind contains a whole `centre` /
`center` word or is a `tailstock`. A machine accessory has no record, so its
name supplies that distinction; `tailstock_drill_chuck` is not a centre
support. An unknown support, unknown kind or missing identity cannot prove
that no centre is used. A known non-centre kind remains non-centre even when
its record has verification or measurement debt.

A selected `follow_rest` / `steady_rest` in `hold.supports` uses
`{ ref, ops, jaw_lead_mm }` / `{ ref, ops, at_z_mm }`. The fixture declares
fact-local measured `capacity_min_mm` / `capacity_max_mm` (or `_in`), inclusive
limits on the work diameters its jaws can ride. `turning_deflection` credits
the rest span only for an operation whose ridden diameter lies inside that
capacity. Unmeasured or unverified capacity leaves deflection unknown and
enters the measurement checklist. The rest's drawn geometry uses its own
[solid fields](#holding-solids), not those capacity limits.

Hold identities resolve through `fixtures`, `holders`, then `machines`.
A machine-mounted dividing head can therefore resolve as workholding. Its
`centre_height_in` locates the spindle axis above the mounting base for
headroom; `hold.pose.origin_mm[2]` locates that axis in the setup frame.
Body `height` / `length` / `width` and `bed_height` do not replace centre
height. A dividing head with no gripping capacity is `not_applicable` to the
diameter screen. Machines and dividing heads with collet sizes or chuck ranges
are checked.

For indexing, a dividing head may be in `machines` (the shipped example is
`BS-0`) or `fixtures`. `worm_ratio`, `direct_index` and each `plate_holes`
circle are arithmetic inputs. Hole counts must be positive integers;
`verify = true` keeps the chosen setting tentative.

### Projection and engagement

Installed projection belongs to the tool/holder pair in inventory, with no
per-job or per-setup override. An explicit unknown or debt-carrying pair entry
blocks fallback; only an absent entry permits `oal - holder.grip`.
Flute length and holder gauge length never substitute. See
[projection ownership and precedence](#projection-ownership-and-precedence)
for reference matching, duplicate keys and measurement requirements.

Engagement applies to resolved `endmill` / `endmill_set` tools on cutting
operations. Missing, unknown or nonpositive authored DOC leaves an eligible
operation unknown. Long drills, reamers, taps and lathe tools do not receive a
milling DOC-halving recommendation.

## Bandsaw machines and blades

Both `machines.<saw>.kind` and `tools.<blade>.kind` may be `"bandsaw"`.
The machine's `blade_speed_sfm = [min, max]` is a positive, ordered speed range
in feet/minute. The blade declares `material` for cutting-data selection and a
positive `kerf_mm` or `kerf_in`, either a `MeasuredLength` record or a trusted
nominal scalar. Declaring kerf in both units is rejected. Fact-local
verification debt withholds geometry.

Example blade values follow the [examples policy](../examples/README.md):
they are demonstration-fixture records or cited catalog values, not fabricated
shop measurements.

Bandsaw and hand-saw blades declare tooth pitch as
`tpi = { value, cite, measured, verify }`. Use one number for constant pitch or
`[coarse, fine]` for variable pitch; a 4/6 TPI blade is `[4, 6]`.
`pitch_mm` is rejected. As with `helix_deg`, a cited catalog value is enough.
A bare number is bad input. Missing, uncited or flagged pitch is debt, leaving
the [teeth-in-the-work check](rules-geometry.md#saw-teeth-in-the-work) `?`.
Variable pitch is judged at the coarse end, where the fewest teeth engage.

A bandsaw can declare `saw_modes = ["horizontal", "vertical"]`, with either or
both modes. Only vertical mode supports following a scribed line with the work
fed by hand on the table. Undeclared modes leave that cut `?`; a straight cut
needs no mode declaration.

A hacksaw or junior hacksaw uses `tools.<saw>.kind = "hand_saw"` and cuts only
on a `bench` or `manual` machine. It needs neither `blade_speed_sfm` nor a
cutting-data row. Straight cuts use the same kerf fields as a bandsaw blade;
scribed-line cuts use the operation's removal box and consume no kerf.

Verification debt on a saw, including kerf debt, remains unresolved for its
consumers; unresolved geometry cannot route known stock. Only a resolved,
verified `hand_saw` retains the manual-bench waiver for a bench setup;
unresolved, unverified and powered blades do not. A raw `slitting_saw` identity
never earns a nonspindle-saw waiver, even while dimensions or verification are
unknown.

The following is a schematic fragment. Replace the ellipses, including the
non-ISO placeholder date, with real measurement metadata before loading it.
The stated kerf is an example, not a shop measurement.

```toml
[tools.junior-hacksaw]
kind = "hand_saw"
name = "junior hacksaw, 32 TPI blade"
kerf_mm = { value = 0.6, measured = { status = "measured", by = "...", date = "...", instrument = "..." } }
tpi = { value = 32, cite = "blade maker's catalogue: 32 TPI" }
```

Nonspindle bandsaw and hand-saw operations need no spindle taper, holder, shank
diameter, tool OAL or projection. A mill or bench hosting a bandsaw blade must
declare its actual blade-speed range for a sourced speed recommendation. The
hold resolves an ordinary fixture; a machine identity never supplies an
integral vise. The only fixture-free hold is a scribed-line cut fed by hand on
a vertical bandsaw table, `hold.kind = "hand_fed"`. See
[hand-fed on the saw table](plan.md#hand-fed-on-the-saw-table) and
[saw cut-off](plan.md#saw-cut-off) for the plane and keep-side contract.

A real mill-mounted slitting disk uses `tools.<disk>.kind = "slitting_saw"`,
not `"bandsaw"`, and is recognized only on a `mill` for `saw_cut` / `cut_off`.
Inventory `kind` remains an arbitrary string; recognition adds no schema fields.
Declare disk OD explicitly as `dia_mm` or `dia_in`, and kerf separately as
`kerf_mm` or `kerf_in`: neither OD nor kerf is inferred from `thickness`.
Use existing `flutes` for total tooth count, not TPI. The existing optional
`arbor` field can name the arbor identity, and the operation's `holder` selects
its holder. Unknown dimensions or arbor facts remain debt; these identity
fields do not prove mounting, axis, arbor assembly or clearance.

Slitting recommendations use rotating-tool `operation = "slitting_saw"` data
and spindle limits, never bandsaw descent rows or `blade_speed_sfm`. The
planar kerf model can describe ideal stock removal only: finite disk reach,
arbor/spindle/tool/fixture clearance and engagement/tooth count are unmodelled.
It cannot certify physical slitting safety or finished-face coverage.


## Manual-arc kit

Manual arcs use layout, filing and indexing equipment. No machine field
declares MDI, G-code or contouring. The operation sequence is defined in
[Manual arcs](plan.md#manual-arcs).

### Benches, buttons and rotary tables

A fitting bench is `machines.<id>.kind = "bench"`. Its setups contain only
manual operations, such as `scribe`, `file_to_line`, `deburr` and `inspect`.
Workholding, including a bench vise or filing buttons, is drawn like any
other fixture.

Filing buttons use `fixtures.<id>.kind = "filing_buttons"` with these
`[least, greatest]` limits:

| Field | Physical limit |
|---|---|
| `button_dia_limits_mm` | Button OD |
| `button_bore_limits_mm` | Button bore |
| `pin_dia_limits_mm` | Pin through the button bores and part bore |

Each accepts a plain pair or `{ value = [least, greatest], measured, verify }`,
or its `_in` spelling, never both. `button_runout_mm` is the button OD's TIR
about its own bore. `solids` draws the buttons, nut and stud. The part bore's
limits come from the drawing. The plan names the kit in `guide.buttons` and
holds it through `hold.fixture` or a clamp `ref`. Unknown limits leave the
filed radius unproven.

A rotary table uses `fixtures.<id>.kind = "rotary_table"`. Its fields are
`graduation_deg`, `vernier_deg`, `dial_increases`, `t_slots`, `max_work`,
`t_slot_width` and centre `bore_dia`, plus `solids` for the table, slots and
worm housing. A `centre_by = "pin"` pin must fit that bore; unknown bore
diameter leaves the pin unproven. `max_work` and `bore_dia` are fact-local
lengths. An untrusted record leaves its contour unknown and names the fact in
the measurement checklist. A rotary-table contour or indexed chord reads the
table from `hold.fixture`.

### Templates, masters and readouts

Radius templates and gauges use `gauges.<id>.kind = "radius_gauge"` or
`"profile_gauge"`, with `range_mm` stating the radii they read.
`leaf_tolerance_mm` is the maker's ± tolerance on each leaf radius and is a
fact-local length. An `R MAX` inspection needs a leaf at or below the limit
less that tolerance. The setup sheet does not yet name that leaf, so positive
tolerance leaves the check unknown at best. Omitted tolerance is zero; declared
unknown or untrusted tolerance leaves the limit check unknown. See
[inspection rules](rules-inspection.md).

A guided sweep's master is a gauge with `kind = "setting_bar"` or
`"master_arc"`. A setting bar seats on a swing-arm pivot pin and is for pivot
guides only. A master arc is a template edge pinned on the arm or sled.
Its measured `radius_limits_mm` or `_in` gives the `[least, greatest]` radius
the seated touch face sets about the guide centre: the pin axis for a setting
bar, or the rail centre for a master arc on a sled.

A machine axis readout used as a gauge is `gauges.<id>.kind = "dro_scale"`,
with `resolution_mm` and axis-travel `range_mm`. It can read `length`,
`depth`, `height`, `thickness`, `station` or reference-only `length_ref`,
such as a lathe tool touched through paper on a scribe and then a faced end.
It does not read diameter or form.

### Guided-sweep fixtures

A guided sweep uses the fixture named by `hold.fixture`. A swing arm
(`kind = "swing_arm"`) turns on a pin at the arc centre and declares
`pivot_play`, the greatest displacement of its beam axis from the pin axis.
An arc sled (`kind = "arc_sled"`) runs a filed rail against two rollers in
the T-slots and declares:

- `rail_radius`, the rail radius about its centre, printed for roller setting;
- `rail_form_error`, the greatest departure of the filed rail from a true arc;
- `roller_runout`, the guide rollers' OD runout, TIR.

These lengths use `_mm` or `_in`, never both. `pivot_play`,
`rail_form_error` and `roller_runout` each need their own complete
`measured` record with `status = "measured"`. Bare, assumed, flagged or missing
values remain debt with a `measure:` instruction; they do not describe a
perfect guide.

`solids` and `hold.pose` draw the fixture. An arc sled also declares
`rail_side`: `"outer"` for rollers bearing from outside the arc, or `"inner"`
for rollers on the centre side. Inside rollers need measured `roller_dia`.
The rail bound depends on the rollers' centre orbit: at least the rail radius
for outside rollers, or rail radius less half the roller diameter for inside
rollers. Undeclared side or unmeasured inside-roller diameter is debt.

For the picture, the sled also needs measured `roller_dia`, measured
`roller_height` (roller top above the table) and `bed_height`. The rollers are
render-only; missing facts get picture notes with their `measure:`
instructions. A swing arm's remote pivot post is located by a note rather
than drawn. See [renders](rules-geometry.md#renders).

### Oblique trammels

An oblique trammel is `fixtures.<id>.kind = "trammel"`: a carrier with one pin
in a carriage on each of two straight rails clamped to the table
([#269](https://github.com/pedropaulovc/prechips/issues/269)).

| Field | Meaning |
|---|---|
| `rail_angle_deg` | Angle at which the rails' pin-lines cross |
| `rail_angle_error_deg` | Greatest permitted error in that angle |
| `pin_spacing_mm` / `_in` | Map from pin-pair name to its spacing, for example `pin_spacing_mm = { inner = { value, measured } }` |
| `pin_spacing_error` | Greatest error in a pair's spacing |
| `pin_clearance` | Pin radial play in its carriage |
| `rail_offset` | Greatest offset of either rail's pin-line from the aligned spindle axis |
| `rail_travel` | `[nearest, farthest]` pin stations from the spindle axis, at carriage end stops |

Each fact needs its own complete measured record. Bare, assumed or missing
values remain debt with a `measure:` line. Lengths use `_mm` or `_in`.
Rails are aligned once per installation, not per part, and an operation
depends on that commissioning
([#270](https://github.com/pedropaulovc/prechips/issues/270)).

The trammel is built and commissioned outside the setup sheet:

- `make_document = { id, revision, cite }` names the drawing or document used
  to build and set it.
- `commissioning_record` points to the installation record.
- Measured `dowel_reading` is the largest miss between predicted station
  targets and a carriage dowel reading along each rail.

Any missing entry, including any part of `make_document`, is debt and the
card prints only a STOP. Otherwise the card prints those pointers; it never
prints the trammel build.

For the setup picture, measured `pin_dia`, `rail_width`, `rail_height` and
`bed_height` draw render-only rails and pins. A missing fact gets its own
picture note. Measured `carrier_length` (along the pin chord), `carrier_width`
and `carrier_thickness` draw the plate carrying the work. No fact offsets it
from the pin chord, so it is centred on that chord with its top at the work
seat. A missing carrier dimension leaves only the carrier undrawn, with a
separate note.

## Edge finder

An edge finder used for mill X or Y zero (`zero.x/y.tool`, except
`from = "indicated"`) is `tools.<id>.kind = "edge_finder"`. It declares:

- `finder_type = "mechanical"` for a spinning finder or `"electronic"` for
  one used with the spindle stopped;
- tip diameter `tip_in`, a plain number, or catalog `dia` only when `tip_in`
  is absent;
- for a mechanical finder, maker speed band `rpm_range` and a `cite`.

Explicit `tip_in = "unknown"` never falls back to body diameter.
The digital [zero check](rules-coordinates.md#zero_check) records `finder` on each pickup row:
tip radius and the usable speed bands. Those bands are the intersection of
the finder range with each machine spindle band (`ranges_rpm`, otherwise
`rpm_min` to `rpm_max`). Speeds between separate spindle bands are not offered.
A missing fact or unknown endpoint leaves zero unknown; no overlap with any
spindle band is an error.

For a digital readout, the setup sheet prints one EDGE FINDER box per finder
and mill in the DRO ZERO block of the first setup that uses that pair. It states speed, contact
signal and offset. A mechanical tip runs true then kicks sideways; an
electronic finder lights. Axis Set is edge − r when approaching from the −
side, or edge + r from the + side. Every X/Y row names the box.

## Purchased tooling

A bought-finished item in any category can declare `purchase`, the item
bought, and `acceptance`, a nonempty list of receipt-check tables. Shop-made
items cannot carry receipt checks.

| Field | Meaning |
|---|---|
| `check` | Required nonblank text naming what is checked (`"each button OD"`); `"unknown"` remains unresolved |
| `gauge` | Required nonblank `gauges.<id>` (or member path), or `"none"` for a hand/eye check; `"unknown"` remains unresolved |
| `how` | optional: how the gauge is used (`"button on the GO pin in a V-block, one turn"`) |
| `limits` | the name of a `[least, greatest]` limits field or single-length field on the same item (`"button_dia_limits_mm"`, `"button_runout_mm"`, printed low to high or ≤ value) |
| `limits_mm` | or the `[least, greatest]` limits in mm, inline |
| `accept` | the criterion in words (`"the nut runs on by hand"`); required where there is no numeric limit |

Each check states at most one numeric limit and must supply a limit or
`accept`. A `"none"` gauge is for a hand/eye check and takes no numeric limit.
Missing or blank `check` / `gauge` is bad input (exit 3). A fully numeric
`limits_mm` pair must satisfy `0 ≤ low ≤ high`; negative or reversed pairs
are also rejected at load with exit 3. A pair with an unknown endpoint can
load but remains unresolved.

### Item selection and receipt-check scope

The always-required `purchased_tooling` rule reads a selected item's receipt
checks whenever a setup uses it. Its scope includes:

- all hold slots: fixture, chuck, parallels, riser, jaw bar, buttons, support,
  clamps, stop, supports and alignment indicator;
- zero tools, holders and gauges; a tool touch's `z_gauge`; transfer tools
  and gauges;
- an operation's filing guide or guide gauge, tool, holder, inspection gauge
  or process-hold gauge;
- items named in setup prose, and in notes or record blanks on selected
  shop-made items. Job-page prose belongs to the first setup for this purpose.

Selection fixes both category and key before any consumer reads the item.
A qualified reference such as `gauges.pins` selects only that category.
Unqualified slots use these category orders:

| Slot | Categories read, in order |
|---|---|
| Hold fixture or dividing head | `fixtures`, `holders`, `machines` |
| Chuck, parallels, riser, jaw bar, buttons, supports, clamps, stop or support blocks | `fixtures` |
| Zero tool, tool-touch tool or transfer tool | `tools`, then `gauges` |
| Indicator, inspection, process-hold or guide gauge | `gauges` |
| Operation tool | `tools` |
| Holder | `holders` |
| Setup machine | `machines` |
| Bare key in prose with no slot | `machines`, `tools`, `holders`, `fixtures`, `gauges` |

The first category listing the key, or declared `"unknown"` as a whole, is
final. Selection never borrows a same-key record from a later category.
Thus `fixtures.pins` and `gauges.pins` are separate items with separate checks,
tables and first-use setups.

All later consumers use the selected item: receipt checks, `tool_resolves`,
shop-made notes and record blanks, printed names, member size or capacity,
projection ownership, citations and measurement requests. For example,
`holders.collets/1/4` grips only 1/4 in. A category-qualified spelling and the
key it selects refer to the same item.

A bare prose key is replaced with a slot-selected shop name only when every
slot using it selects that same item and bare-key lookup also selects it.
Otherwise it remains as written; qualify it as `<category>.<key>`.
An item declared `"unknown"` or `{}`, or a whole unknown category, remains
unknown to every rule and prints `? <category>.<key>`. It never borrows another
item's name or record.

### Unresolved checks and printed limits

The setup stays unknown and prints `STOP:` when any required receipt fact is
unresolved: unknown `acceptance`, `purchase` or `check`; blank or unknown
`how` / `accept`; an unknown, unlisted or unverified gauge; a `limits_mm`
pair with an unknown endpoint; or `limits` naming a field without known
lengths. These unresolved facts differ from the malformed checks rejected
at load.

The first setup using an item gets one PURCHASED TOOLING / RECEIPT CHECK
table on its front sheet. Later setups point back to it. Limits round inward
to 0.001 mm; inch gauges also get inward-rounded 0.0001 in limits.
A band too narrow for those decimals, or a cap that would round to zero,
uses up to three more decimals. If still too narrow, the mm band prints
exactly as declared and the inch band is omitted. Rounding never prints an
empty or reversed band.

## Kernel geometry facts (M4)

M4 kernel geometry accepts trusted nominal dimensions; it does not require a
shop measurement for every fact. It uses the same fact-local length lookup as
M5, but M5 requires physical measurement for its screens.

A consumed `MeasuredLength` is a plain nominal number or a
`{ value, measured, verify }` record. It enters the FreeCAD job when it resolves
to a positive length through its single supported unit spelling and its own
record has no debt. A bare or catalog number needs no measurement metadata
where measurement is not required. A record is refused if it has
`verify = true` / `"unknown"`, incomplete `measured` metadata, or a measurement
status other than `measured`. Omitted status means `assumed`.

Debt belongs to that dimension. An untrusted fact cannot be replaced by an
alias or inferred fallback for the same physical fact, such as OAL − grip
beside an illustrative pair projection. Unrelated facts on the item remain
usable. Item `verify`, `present` and `source`, set-root/member-container flags
and coverage text establish identity provenance for declared-input rules;
they do not qualify numeric facts for the kernel.

The M5 `envelope` and `travel` screens require measurements of holder
gauge/grip, tool OAL and projection; `headroom` also requires measured machine
limits. Geometry can therefore be checked while the installed stack still
has M5 measurement debt.

Resolved tool, holder and fixture dimensions and solids set the modeled scene
extents used for [picture scale](rules-geometry.md#renders).
[Outline overlays](report-and-telemetry.md#kernel-renders) use a separate
bounded painting stream. They do not change layout/leader inputs, add inventory
fields or change dimension trust.

### Holding solids

A vise needs accepted `jaw_height`, `jaw_width`, `jaw_depth` and `opening`.
`jaw_depth_mm` / `jaw_depth_in` is the physical jaw-plate thickness along the
gripping normal. It is never derived from jaw width, jaw height, bed height or
another dimension.

Parallels need positive `height`. Optional `length` along the jaws and `width`
along the clamp axis allow parallel solids to be drawn when the plan also
declares `parallels_centres_mm`. A `blocks_123` riser supplies accepted
`length`, `width` and `height`.

Vise jaw accessories require measured facts:

- A `round_bar` selected by `hold.jaw_bar` needs `dia` and `length`. Its
  diameter holds the moving jaw off the work. Without both facts, the jaws
  remain unplaced.
- `jaw_buttons` selected by `hold.jaw_buttons` need face `dia`, `thickness`,
  `spigot_dia` and `spigot_length`. All four are required to place the jaws.

Other holding solids use these fields, with no default dimensions:

| Kind | Required geometry and unresolved behavior |
|---|---|
| `chuck_3jaw`, `chuck_4jaw` | `body_dia`, `body_length`, `bore_dia` smaller than the body, tangential `jaw_width`, radial `jaw_height` outward from the grip, and axial `jaw_depth` ahead of the body face. A dividing-head setup selects the chuck through `hold.chuck` |
| `follow_rest` | Measured tangential `jaw_width`, radial `jaw_height` outward from the ridden diameter, and axial `jaw_depth`; `jaw_angles_deg` gives jaw directions about the spindle in degrees from the tool, for example `[90, 180]` for top/back jaws. A missing fact leaves the rest undrawn and its served operations unknown, naming the field |
| `steady_rest` | Measured `body_dia` for the ring OD and `body_length` for axial length. Without them it remains an undrawn possible obstacle with a named gap; clear turning samples and `fixture_interference` remain unknown |
| `dead_centre` | Shank `dia`, tip-to-quill-face `length` and included cone `point_angle` in degrees. Quill diameter comes from machine `tailstock.quill_dia`, or the dividing head's own tailstock |

### Authored primitives and voids

Any item, including an angle plate, dividing head, custom fixture or clamping-kit
member, may declare local-frame solids. Box fragments use
`solids = [{name, shape, at_mm, size_mm}]`; cylinder fragments use
`{name, shape = "cylinder", at_mm, axis, dia_mm, length_mm}`.
Each primitive owns its trust. A primitive with `verify = true` / `"unknown"`,
incomplete measurement metadata or non-`measured` status is not drawn and is
named as debt.

A `void = true` primitive is cut from the same list's other primitives.
`cuts = ["<name>", …]` restricts it to named primitives. It never cuts another
item's or member's solids. An untrusted or malformed void withholds the solids
it would cut, with named debt, instead of drawing them uncut.

A strap member models its whole assembly in one list: beam, slot void
(`cuts = ["beam"]`), stud, heel, nut and washer, with washer bore
`cuts = ["washer"]`. Primitives in one list are one part and are not checked
against each other. Each posed clamp list must touch the stock to bear.
The holding fixture's solids must touch stock or a bearing clamp member through
a connected chain of members, such as a bench vise gripping the stud of filing
buttons on the work. A member separated by air from that chain carries no load.

A trusted holding-fixture void may declare a shop caption such as
`label = "Strap stud holes"`. The render places its leader at the void centre
after `hold.pose`, and records the caption and posed centre in
`scene.fixture_detail_labels`. A caption does not create geometry or override
measurement/verification debt.

### Shop-made fixtures

An item or member is shop-made when `kind = "custom"` or `shop_made = true`.
If it has something to make, the first setup using it at a given pose and HOLD
label gets a SHOP-MADE FIXTURE table on sheet 2. Later uses at the same poses
and labels point back. Moving it or changing its label, such as C1 to C2,
produces another table. An item with only bought/existing primitives and no
holes made in them gets neither table nor pointer.

Each row gives one made primitive's size and position: box X/Y/Z extents or
cylinder axis. Identical primitives within one `supply` group share a row
named by their shared `label` or common name words. Positions use `hold.pose`,
a clamp `pose` or `stop_pose`. A posed slot without its pose prints
"? not posed".

Items placed by HOLD facts rather than a pose are loose, such as shop-made
vise jaws, `hold.riser`, `hold.supports` and `hold.jaw_buttons`. Their positions
use the item's own drawn frame under "loose: placed as the HOLD says"; the
HOLD step points to that table.

A void appears as "with N × <fastener or size>: positions" on every made or
existing primitive it cuts. Explicit `cuts` controls the selection; otherwise
overlap does. Overlap is exact for boxes, parallel cylinders and axis-aligned
cylinders against boxes. A possible oblique-hole intersection remains
"? not set: oblique hole … may cross it; name it in cuts" until named in
`cuts`. A void cutting only bought hardware is not listed.

Make-table sizes and positions are expected make-to-drawing settings, not
observations of the installed fixture. Unresolved authored dimensions print
"? not set". Bought/existing primitives retain any refused physical provenance
independently of drawing targets for holes made in them. Native geometry stays
unresolved until its required physical inputs are established.

A primitive or hole with a measurement status other than `measured` gets `†`
after its component name. Attribution prose does not decide this. The job page
prints this legend once:
`† Make-to-drawing expected settings; check the physical fixture as made
before use. These settings do not clear installed-measurement STOPs.`

Per-primitive `supply` is:

- `made` (default): made here;
- `bought`: hardware, listed once under "Bought hardware (not made)" by
  `fastener` or name and size. Touching/overlapping primitives with the same
  fastener text, such as a screw head and shank, count as one part;
- `existing`: already in the shop, so not listed unless holes are made in it.
  Such a row says "(existing part: make the holes only)" and its size is "—".

#### Make-table precision and notes

Sizes and positions use the DRO grid on which they are made: the shop mill
grid when all machines of kind `mill` share one grid, otherwise the setup
machine grid. Ordinary dimensions use policy `numbers.fixture_make_decimals`.
A primitive with `locates`, every bore cut in it and shim nominals use drawing
precision, or grid-step precision if drawing precision is missing, finer than
the grid or off-grid. Either a primitive or its bore may be the locating
surface.

A position coincident with a fit on the same sheet uses the fit value, such as
a pin's hole or a bolt hole above a locating pad. If grid rounding moves a fit
beyond `general_tolerances.linear_<n>pl`, or that tolerance is undeclared, the
table prints `?` and a reason. It never silently moves the hole.

`locates = "<part face>"` and `fastener = "<thread / fastener>"` populate the
Locates and Fastener columns. `shim = true` marks an adjustable shim stack.
HOLD prints its drawn thickness as the nominal to fit with feeler gauges,
once per shim primitive per item placement.

A made primitive's `note`, such as material, heat treatment or finish, prints
once per row under "Make:". Different notes prevent row grouping. A made
hole's note joins those entries under its label or name. A bought/existing
primitive's note prints under "Notes:" for its purchased state or surfaces to
leave alone. This allows a bought shell with windows made here to state its
whole route.

#### Make operations

`make_ops = [{ hold, tool, rpm, feed, doc_mm, cite }]` declares cutting
operations on a shop-made item, made primitive or made hole:

| Field | Contract |
|---|---|
| `hold` | Text describing how the piece is held |
| `tool` | Key in `tools`, not another category or a machine accessory |
| `rpm` | Speed > 0 or ordered `[low, high]` range |
| `feed` | Number or `low-high` range with `mm/rev`, `mm/min`, `mm/tooth`, `in/rev`, `in/min` or `in/tooth`; a bare number is refused |
| `doc_mm` | Depth of cut per pass > 0 |
| `cite` | Cutting-data source, such as `MH 31st Table 17 p.1061` |

Every entry states all six fields. Use `"unknown"` for an unresolved fact,
never omission or blank text. Under "Make operations, in order:", item
operations print first, then primitive operations in `solids` order after
their row names. Primitives sharing a label print a shared list once. A printed
line has this form:
`1. hold: vise on parallels; T: <tool's shop name>; 600 rpm; 0.05 mm/rev; 0.5 mm/pass; MH 31st Table 17 p.1061`.

`hold` and `cite` print as written, including links and paths, except inventory
references print their shop names. Unknown facts print `?`; an unlisted tool
prints `? <key>`; a listed but unverified tool prints `? <tool's shop name>`.
The line ends with a STOP naming unresolved facts. `make_ops = "unknown"`
prints one STOP line. Tool selection also invokes `tool_resolves` and the
setup's purchased-tooling receipt checks.

Make operations print once, before the first setup using the item through any
hold slot. They appear in that setup's make table, or under a separate
SHOP-MADE FIXTURE heading on sheet 2 when that use has no table. That heading
points to a later table when needed. Chucks, parallels, jaw bars, single
supports, operation holders and guide buttons can have such a first use.
A later table says "Make before" the first setup and points back to the
operations.

Declared operations must have somewhere to print. They are rejected on bought
items, bought/existing primitives, items with only bought/existing solids,
set members with their own operations, or items outside `fixtures`, `holders`
and `machines`. A member inheriting set operations is also rejected if its
own keys make it non-shop-made or leave nothing made here.

#### Measurement record blanks

`records = [{ check, gauge, how, max_mm, goal_mm, over_mm }]` on a primitive
declares values to measure and record when it is made or received, such as
head-to-shoulder TIR or squareness by reversal. Under "Measure and record before
first use:", each entry prints the check, gauge shop name, method,
`accept ≤ max_mm`, `goal ≤ goal_mm`, `measured ________ mm`, and
`over over_mm mm` when given. Max and goal round down.

`check` is required. `how` and `gauge`, when supplied, must be stated.
`records` must be a list, not `"unknown"`, so the sheet has something to fill
in. Supplied lengths must be known and ≥ 0, except `over_mm` must be > 0.
Goal must lie inside max. Without `max_mm`, a record characterises the item
without judging it. Gauge keys resolve in `gauges`; an unlisted gauge prints
`? <key>`.

### Inventory references in prose

Notes, record checks/methods, make-operation `hold` / `cite` and plan notes
can name an item as `<category>.<key>[/<member>]`. Categories are `machines`,
`tools`, `holders`, `fixtures`, `gauges` and `services`. Examples are
`gauges.granite-surface-plate`, `tools.drills/#61`, `tools.drills/1/4` and
`tools.reamers-metric/6.49mm`.

A member reference runs through its last letter, digit or `#`, excluding a
sentence's final full stop. It resolves whole, as a slot does: a missing member
does not select its parent item. The setup sheet substitutes the shop name,
or `? <key>` if unlisted. `tool_resolves` checks it and `purchased_tooling`
reads its receipt checks.

References also work beside punctuation or quotes, including
`fixtures.a,gauges.dti` and `` `gauges.dti` ``. They are not read inside URLs
(`scheme://…`) or drive-letter (`C:\…`), UNC (`\\server\…`), relative
(`./…`, `../…`) or rooted (`/srv/…/…`) paths up to the next space.
Registered bare names match whole tokens, never letters inside ordinary words
or parts of qualified/member references.

### Locating and bearing surfaces

For an angle plate or posed shop-made fixture, the lowest non-bought box is
the base. HOLD prints its underside Z, the angle plate working face
(local y = 0, facing local -y) and base `fastener` as the hold-down.
If any such box is untrusted, HOLD prints no setting line. These texts
establish neither geometry nor trust.

For a clamp with `restraint = "locate"`, the drawn solid's `locates` names
the surface it must prove it bears on. `bears = "bore" | "face"` selects
contact-cylinder-in-bore or flat-face proof. Missing `bears` leaves it
unproven under `thin_wall_under_clamp`. A cylinder whose `locates` names a
plan [`tooling_hole`](plan.md#process-features) is a pin in that hole;
`tooling_hole` compares its `dia_mm` with the hole band.

### Rotary workholding

For `approach = "rotary"`, the hold must resolve to a `dividing_head`, and
`hold.chuck` must name a dimensioned chuck. The plan supplies `hold.pose`,
`jaw_clock_deg` and `grip_mm`. Pose origin is the chuck jaw-face centre;
pose +z points toward the work along the horizontal head axis, perpendicular
to setup Z.

The head's authored solids, chuck body/jaws, tailstock and clamps supply
modeled obstacles. Indexing ratios and vendor photographs do not supply
missing solids or poses. The chuck rotates with the work; the head body,
tailstock and clamps remain fixed.

Continuous rotation uses
`hold.index = { fixture = "<head>", rotation = "continuous" }`, without
`positions` or `angle_deg`. It needs a verified dividing-head identity, not
a plate-landing calculation.

Rotary operations use ordinary vertical-mill cutter/holder facts: tool
`dia`, `flute_len`, `oal`; holder `gauge_dia`, `gauge_len`; and selected
projection or permitted OAL-minus-grip fallback. They introduce no lathe
insert, toolpost or rotary-specific inventory fields. Each operation's
cutter and holder apply to its window. Several windows, including a smaller
endmill at a shoulder, can cover one face; geometry unions their portions.
Missing dimensions keep dependent screens `?`. Sample poses do not establish
head torque, locking or collision-free motion between samples.

### Tool and holder solids

A tool needs accepted `dia`, `flute_len` and `oal`; a holder needs accepted
`gauge_dia` and `gauge_len`. Holder cylinders use `gauge_dia_mm` /
`gauge_dia_in`, not shank or collet capacity. Projection follows the
[pair-entry precedence](#projection-ownership-and-precedence); only an absent
entry permits tool OAL minus selected-holder grip, each from its own accepted
fact. Missing dimensions or fact-local debt appear in the job reason and keep
dependent geometry rules `?`.

The shipped `fixtures.vise-pm-6` has shop-measured `jaw_height_in`,
`jaw_width_in`, `jaw_depth_in`, `opening_in` and `bed_height_in`, each recorded
on 2026-10-05 with its own measurement metadata and vendor nominal in a
comment. With STEP and a complete pose, its setup draws jaw solids.
Item-level `verify = true` remains identity debt elsewhere, not a geometry
veto. Shipped parallels have no `width`, and shipped plans have no
`parallels_centres_mm`, so shipped setups do not draw parallel solids.
See [geometry rules](rules-geometry.md).

Spot and drill operations also consume `point_angle` (`MeasuredAngle`,
degrees) for the real point cone and body. Trusted nominal angles are
accepted; missing, unknown or debt-carrying angles are never defaulted.
Spots require the angle even though their tip-endpoint formula uses only
depth. Unknown angle leaves accessibility `?` and later stock unresolved.
See [accessibility](rules-geometry.md#accessibility).

## Measured envelopes and installed tool stacks (M5)

`machines.<id>.envelope` contains the machine limits read by `headroom`,
`envelope` and `travel`. The fields differ by machine:

| Machine | Nested envelope facts |
|---|---|
| Mill | `travel_mm` or `travel_in` with `x`, `y`, `z`; `spindle_to_table_max_mm` / `_in`; `spindle_to_table_min_mm` / `_in` |
| Lathe | `swing_over_bed_mm` / `_in`; `swing_over_cross_slide_mm` / `_in`; `between_centres_mm` / `_in` |

Each limit is a fact-local `MeasuredLength`. Lathe headroom compares stock OD
and chuck body diameter with bed swing, stock OD with cross-slide swing, and
exposed length plus chuck body length with distance between centres.
Exposed length is numeric `hold.stickout_mm` when available. Otherwise it is
the setup's `stock_state.north_end_z - stock_state.south_end_z`, converted
from manifest units to mm, not the root stock's declared length. Missing
endpoints or unknown manifest units leave that span unresolved.

An unresolved machine or holding fixture/chuck, verification debt on the
fixture/chuck, or unresolved dimensions or measured limits prevents a pass.
A known overrun takes error precedence; otherwise the decision stays unknown.
This screen checks no tool path, carriage stroke or tailstock extension.
Top-level item fields `swing_over_bed_in` and `between_centres_in` are accepted
descriptive numbers, but do not supply these measured nested limits.

Mill top-level copies of `spindle_to_table_max_mm/in`, `travel_in` /
`travel_mm` or `table_in` are rejected. Table length/width, T-slot pitch and
separate R8/ER-collet-chuck/drill-chuck stack heights are not envelope inputs
and generate no envelope measurement requests. Spindle taper remains vendor
identity under `machines.<id>.spindle`, used for holder compatibility.

This schema fragment declares unknown mill limits and stack facts. Other
machine, holder and tool fields must describe the actual selected equipment.

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

### Measurement status and provenance

For a measured fact, replace `"unknown"` with the following record fragment:
`{ value = <actual measurement>, measured = { status = "measured", by = "<operator>", date = "YYYY-MM-DD", instrument = "<actual instrument>" } }`.
Do not load the placeholders as operative inventory. A copied vendor nominal
can instead use `{ value = <nominal>, verify = true }`.

Set `status = "measured"` only after that physical fact has been measured,
with who, when and instrument recorded. An authorised but unmeasured
placeholder is `assumed`, also the default when status is omitted.
`illustrative` identifies a deliberately made-up value.

`by` is attribution, not a trust switch. For example,
`{ by = "example (plausible, not measured)" }` without measured status remains
assumed. With `status = "measured"`, the engine trusts a complete record
regardless of those words. No bundle or policy opt-in changes that behavior.

The [worked examples](../examples/README.md) deliberately exercise the
measured branch with `status = "measured"` and
`by = "example value (realistic, not a shop measurement)"`. The engine does
not inspect that marker. It discloses demonstration fixtures, not physical
shop observations. Do not copy those records into real shop inventory as
measurements. Actual shop measurements, such as the separately identified vise
facts above, retain their own provenance.

### Fact-local M5 trust

An M5 dimension qualifies only through its own complete
`measured = { status = "measured", by, date, instrument }`, with no
`verify = true` / `"unknown"`. This includes applicable envelope limits,
bed/parallel/support heights, holder gauge/grip, OAL, pair projection, cutter
diameter, drill point angle and reamer lead.

Assumed, illustrative or status-less records leave the row `?`; it names the
refused record's status and `by`. Item-root, envelope-block, source and member
`measured` metadata are rejected. `source.verify`, coverage, presence, dates
and citations do not replace fact-local measurement.

Explicit fact-local verification debt still refuses a complete measurement.
A scalar vendor nominal such as `spindle_to_table_max_in = 17`, or
`{ value = 17, verify = true }`, remains in finding `numbers` as evidence but
yields `?`, not a pass or measured overrun. Clearing `verify` without adding
a measurement does not establish one.

Kernel geometry and engagement accept trusted nominal facts, while honoring
the same fact-local verification and measurement-status debt. Their
nominal-geometry readiness does not clear M5 physical-measurement debt.

Use one unit key per length stem: `gauge_len_mm` or `gauge_len_in`, `oal_mm`
or `oal_in`, `projection_mm` or `projection_in`, `bed_height_mm` or
`bed_height_in`. Suffixless `gauge_len` is rejected, as is a second unit
spelling. A measured inch fact therefore cannot be shadowed by an unmeasured
mm alias. `travel_mm` / `travel_in` contain `x`, `y`, `z`; inch conversion is
exactly 25.4.

### Projection ownership and precedence

Holder gauge length runs from mounted spindle nose to holder exit face. It
already includes the spindle/chuck stack, so no separate stack height is
recorded or added.

Projection runs from holder exit face to installed tool tip. It represents
one tool, holder and insertion setting, authored on the tool as
`tools.<tool>.projection_mm` or `_in`. The map key is the full selected
holder reference, such as `"r8-collets-lms-4860/3-8in"`. Qualified and
unqualified spellings match when they select the same holder.

Two map keys selecting the same holder, such as `holder` and
`holders.holder`, duplicate the projection. It becomes unknown with both
keys named, regardless of values or order. Neither value is read and there is
no OAL − grip fallback. State the pair once.

Only tools can carry projection maps. The schema rejects projection on a
holder, fixture, machine or gauge, and rejects a tool-wide scalar instead of
a map. The selected pair entry has precedence:

1. If present, that entry alone decides. Unknown or debt-carrying entries
   leave every consumer unresolved. Another holder's value cannot substitute.
2. Only if absent, use selected-tool OAL minus selected-holder grip.
   Both facts must be measured for M5, or accepted nominal facts for kernel
   geometry and engagement.

Flute length never substitutes for projection.

Projection has no plan-level or setup-level override. Its trust and
measurement debt belong to the inventory pair. Envelope, headroom,
engagement, accessibility, kernel tool stacks and the setup-sheet tool table
all read that setting. A partial override would let the sheet and checks use
different settings.

If a blade is set farther out for a job, update and measure its inventory
setting. Every job is then checked at that setting, including deflection and
clearance; insufficient reach remains a finding naming it. A tool kept at two
projections is two inventory tools.

### Fixture stack dimensions

`bed_height_mm/in` is the table-to-vise-bed distance. Jaw height is above the
bed for the separate jaw-obstruction check; it is not another stack layer.
Parallels and support blocks have their own heights.
`point_angle` uses `{ value, measured, verify }` in degrees.

### Measurement register and setup-sheet references

The TOOLS table marks each refused displayed dimension while retaining its
authored value. A fact consumed by a refused decision gets a short `?M1`-style
reference to the job-wide measurement register. Unconsumed catalog information
can be marked unverified without creating a STOP or recording item. Trusted
nominal/measured sibling facts remain plain; attribution prose does not qualify
a dimension. TOOLS rows stay together in print.

The JOB section gives each physical quantity one full instruction and one
35 × 10 mm recording blank. Canonical record/field identity, including
installed holder/configuration, determines reuse across setups, not the display
name. Composite fixture records keep their canonical binding with separate
dimensional and position leaves:

- boxes have separate local-axis length, width and height entries;
- cylinders have diameter and axial length/depth entries;
- each authored local X/Y/Z position has its own entry. A box position is its
  minimum corner; a cylinder position is its base centre, both fixture-local.
  These are not generic mounting measurements.

Register numbers and display order are ascending and deterministic. Source
setup groups and tool numbers identify where facts are consumed. Setup
summaries keep each operation's actual STOP kind. Record measurements in JOB
and return the setup sheet for reissue; writing a measurement does not
recompute blocked decisions. Bare M is an authored measurement variable, not
necessarily a touch-off reading.

CLEARANCE lists only unresolved inputs consumed by that headroom decision,
such as riser dimensions, gauge length, installed projection and envelope
limits, using the same JOB item references. Instructions follow the fixture
kind: a riser has no vise bed, parallels or jaw height to measure.
Make-to-drawing dimensions and authored fixture coordinates remain setup
targets. They do not certify as-made dimensions or clearance.

An aggregate diagnostic debt list does not prove local consumption. If entry
stock cannot be derived, the setup remains STOPped by the actual upstream
stock decision, pointing to the source setup/operation and existing JOB
items. It does not gain unrelated local fixture/machine blanks. An unresolved
stock prerequisite with no attributable dimensional consumer keeps its real
STOP reason without an invented measurement.

When assembled stock depends on two retained siblings whose split is still
unproven, the operator STOP names the producing part-off, both required pieces
and the assembled workpiece to establish before cutting. It does not expose
the partition-proof diagnostic as a machining instruction. Native/report
reasons and finding statuses remain unchanged. Successful producer partition
records do not relabel an independent joining failure as a missing split.

Eligibility is per decision. Independently evaluated engagement, speeds/feeds,
cutting direction or saw kerf keep the facts they consumed even if stock is
blocked. A native refusal list alone does not prove a local consumer.
A manual bench setup with no unresolved consumed decision has no measurement
STOP or JOB stopped-setup entry solely because selected inventory is assumed.

For a digital readout, the JOB line names the installed DRO controller, such
as EL400, not the machine model, and reuses one global readout-step reference.
Mechanical dials do not receive that digital resolution measurement request.

Centre-drill instructions name pilot and countersink body directly, without referring to
an absent table. Shop-made support height is measured as made from table to
work-support contact surface. Drill point-length STOP references name point
angle before cutter diameter.

A declared positive digital DRO step rounds printed instructions even if its grid is
labelled "not verified". Missing step uses the disclosed provisional default.
"No coordinate targets" means coordinates did not consume the grid; other
printed settings may still use it.

### Measurement-debt listing

`prechips tools --measure [--plan PLAN ...]` evaluates applicable findings and
lists their unresolved `numbers.measurements`, including host-only facts
refused by the kernel job. It defaults to the four pilot plans for shaft,
rocker, bracket and the sole built-up cone. It may need native in-process
stock facts. See the [CLI catalog](reference/cli.md) for invocation and output
options.

Entries sort and deduplicate by scoped report id, including set-member and
pair identities such as `holders.r8-collets-lms-4860/3-8in.gauge_len` and
`tools.endmills-lms-6784/3-8in-4fl.projection.r8-collets-lms-4860/3-8in`.
A needed `"unknown"` fact is listed even without an explicit verification
flag. Unconsumed inventory fields do not appear. The command creates neither
set members nor purchases.

For this listing, `--inventory` or `PRECHIPS_INVENTORY` overrides plan-declared
inventory; otherwise each plan uses its own inventory. Plan-input ids and
instructions carry the plan path. When several effective inventories apply,
inventory ids and instructions carry source paths so equal names cannot merge
unrelated facts. Plans sharing an inventory share its debt. Other `tools`
displays still require `--inventory` or `PRECHIPS_INVENTORY`.

JSON returns the same ids, instructions, units and citations, with structured
category, identity and field parts. Decimal points in member names are not
parsed as field separators. Lengths use mm, point angles degrees and
add/resolve instructions identity units.

Instructions follow record kind: centre-drill `dia` is pilot diameter and
`shank` is countersink-body diameter, measured with a micrometer or calipers.
Measure usable machine travel with a calibrated readout or indicator, not a
steel rule. Normal `tools` output prints the envelope and marks limits measured
or unmeasured. Applicable M5 `?` sheet sentences point to setup measurement
items. An unresolved tool, holder, fixture or support instead needs an owned
identity added or resolved; do not instruct the shop to measure an item it
does not own.

A successful debt listing is not a machining-readiness pass. Unavailable
physical facts remain unknown.

### Measurement records

| Record | Fields |
|---|---|
| `Measurement` | `status`: `"measured"`, `"assumed"` or `"illustrative"` (default `"assumed"` when omitted); required strings `by`, ISO calendar `date` (`YYYY-MM-DD`), `instrument` for every status; none may be blank or `"unknown"`. A record missing or blanking any of them is a schema error (exit 3), and a raw reader that meets one anyway treats the fact as unknown. Only `status = "measured"` with all three qualifies a fact |
| `LengthMeasurement` | Required `value: Number`; optional `measured: Measurement`, `verify: bool` (each may be `"unknown"`); no `cite` |
| `MeasuredLength` / `MeasuredAngle` | `Number` or `LengthMeasurement` (mm/in, or degrees for `point_angle`) |
| `LimitsMeasurement` | Required `value: [Number, Number]` (`[least, greatest]`); optional `measured: Measurement`, `verify: bool` (each may be `"unknown"`); no `cite` |
| `MeasuredLimits` | `[Number, Number]` or `LimitsMeasurement` (mm/in) |
| `EnvelopeTravel` | `x`, `y`, `z: MeasuredLength`; no block metadata |
| `MachineEnvelope` | `travel_mm` or `travel_in: EnvelopeTravel`; `spindle_to_table_max_mm/in`, `spindle_to_table_min_mm/in`, `swing_over_bed_mm/in`, `swing_over_cross_slide_mm/in`, `between_centres_mm/in: MeasuredLength`; no block metadata |
| `ProjectionMap` | `dict[full holder reference, MeasuredLength]`; tools only |

Envelope/travel fields are optional and accept `"unknown"`. An applicable
screen still needs its own limits; absent limits remain measurement debt.
Dates, citations and attribution do not establish measured status.

Tool `dia` / `flute_len` / `oal`, holder `gauge_dia` / `gauge_len` / `grip`,
projection entries, vise `jaw_height` / `jaw_width` / `jaw_depth` / `opening`,
and parallels `height` / `length` / `width` accept `MeasuredLength`, allowing
physical measurements to be recorded on those facts. M4 can accept nominal
forms; the applicable M5 screens require measurements.

All inventory categories use the same `InventoryItem` field set. Rules
determine category-specific usefulness; separate category subclasses do not.
See [file selection and schema](#file-selection-and-schema) for omitted,
unknown and dictionary-key conventions.

## Root fields

All root fields are optional. Category maps and their individual entries can
be `"unknown"`; that is unresolved inventory, not an empty shop.

| Field | Type | Presence |
|---|---|---|
| `machines` | `dict[str, InventoryItem \| Unknown] \| Unknown` | Optional |
| `tools` | `dict[str, InventoryItem \| Unknown] \| Unknown` | Optional |
| `holders` | `dict[str, InventoryItem \| Unknown] \| Unknown` | Optional |
| `fixtures` | `dict[str, InventoryItem \| Unknown] \| Unknown` | Optional |
| `gauges` | `dict[str, InventoryItem \| Unknown] \| Unknown` | Optional |
| `services` | `dict[str, InventoryItem \| Unknown] \| Unknown` | Optional |
| `consumables` | `dict[str, Consumable \| AdhesiveTape \| Unknown] \| Unknown` | Optional |
| `stock` | `list[Stock] \| Unknown` | Optional |

An untyped `Consumable` has optional `name: str` and `products: list[str]`,
each also accepting `"unknown"`. `products` lists in-house product names.
An unknown/empty list, blank product or `"unknown"` product leaves a coating
process unresolved.

A coating operation's `process` can select an untyped consumable or a service.
The setup sheet uses its `name` in the coating tool cell, such as
`outside: black-oxide finisher (hot black oxide, matte)`. Without a name, it
prints the identity key rather than inventing a description.

Declaring a consumable `kind` selects a typed record. The only supported kind
is `adhesive_tape`; a coating process never resolves to a typed consumable.

## Area holds

Double-sided tape uses a typed `consumables` record referenced by plan
[`hold.area`](plan.md#hold). The shipped implementation validates the input
shape and identities: `area.ref` must resolve to `adhesive_tape`, and
`area.on` must name exactly one non-void solid of the selected holding fixture.
Literal unknown identities remain unresolved. The former `hold.method = "tape"`
spelling is rejected.

No current rule qualifies tape capacity or its Z stack-up. Accepted strength,
thickness, dwell and seat facts do not establish a safe hold. The separate
Kienzle milling-force helper does not combine them into a tape decision.
[Area-hold design](design/area-hold.md) defines the proposed capacity and
stack checks. Vacuum holds remain outside the shipped schema; their proposal
is tracked in [#309](https://github.com/pedropaulovc/prechips/issues/309).

### Cited tape facts and intended consumers

`CitedFact` is a `{ value, cite, measured, verify }` record whose `value` must
be > 0 or `"unknown"`. Bare numbers are not accepted in its place.
The design's fact-local trust contract requires a known citation or complete
`status = "measured"` record, with verification neither true nor unknown.
Blank/unknown citations and assumed, illustrative or status-less measurements
remain debt. A citation cannot override a refused measurement. Item-level
`cite`, `source` and `verify` do not qualify the fact.

Strengths add `test`, the test-method name, and `pairs`, a nonempty list of
`{ work, seat }` cutting-data material classes with both roles named.
The proposed consumer treats missing, blank or unknown `test` as debt and
prints it without parsing it. It applies a strength only to a listed pair
with roles preserved. Steel work on aluminium does not establish steel on
steel.

A fixture solid can declare `flatness_mm` (`MeasuredLength`) for its whole
top face and `material` for its contact surface. In the proposed stack model,
the `on` solid needs measured flatness; its material supplies the seat side of
the strength pair. These are inputs for that design, not an implemented stack
proof.

For `consumables.<id>` with `kind = "adhesive_tape"`, `kind` is required and
the remaining fields are optional and accept `"unknown"`:

| Field | Type | Meaning and planned use |
|---|---|---|
| `name` | `str` | Display name |
| `products` | `list[str]` | Products on the shelf |
| `width_mm` | `MeasuredLength`, > 0 when known | Roll width. The proposed coverage model credits one seamless length, so a wider footprint cannot be credited; trusted catalog nominal width is enough for that model |
| `thickness_mm` | `MeasuredLimits` | Applied layer thickness, with known pair `0 < least ≤ greatest`. The design requires a measured sample from the lot on hand; datasheet limits remain debt rather than clear the thickness band |
| `shear_n_per_cm2` | `StrengthFact` (`CitedFact` + `test` + `pairs`) | Shear strength per cm² of contact |
| `peel_n_per_cm` | `StrengthFact` (`CitedFact` + `test` + `pairs`) | Peel resistance per cm of peel front |
| `dwell_min` | `CitedFact` | Minimum time from applying work to cutting at which both strengths hold; unmet dwell is a planned STOP condition, not a current capacity check |
| `surface_prep`, `apply` | `str` | Application instructions for the proposed sheet output |
| `release` | `{ method = "solvent" \| "heat", agent, temp_c, wait_min, cite }` | Solvent release names `agent` and cannot state `temp_c`; heat names `temp_c` and cannot state `agent`. Known `wait_min` and `temp_c` must be > 0. The design prints release instructions only with a known citation |

This schematic fragment preserves example values and placeholder attribution,
test methods and citations. It is not measured shop inventory or a qualified
tape recipe. Replace them with supported records before using the input.

```toml
[consumables.tape-film]
kind = "adhesive_tape"
name = "double-coated PET film tape"
width_mm = 50.0
thickness_mm = { value = [0.090, 0.110], measured = { status = "measured", by = "...", date = "2026-10-11", instrument = "0-25 mm micrometer" } }
shear_n_per_cm2 = { value = 3.0, test = "...", pairs = [{ work = "low_carbon_steel", seat = "aluminium" }], cite = "..." }
peel_n_per_cm = { value = 4.0, test = "...", pairs = [{ work = "low_carbon_steel", seat = "aluminium" }], cite = "..." }
dwell_min = { value = 20, cite = "..." }
release = { method = "solvent", agent = "isopropyl alcohol", wait_min = 5, cite = "..." }
```

## Stock

Inventory stock describes candidate blanks. Listing one does not establish
that it is on hand; use the authored presence and provenance fields.

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
| `origin_mm` | `Vector`; model-frame envelope origin, as defined in [plan stock](plan.md#stock) |
| `axis` | `Vector`; envelope length direction |
| `section_axis` | `Vector`; rectangular section direction |
| `as_is_faces` | `list[str]` |
| `components` | `list[StockComponent]` |
| `prepared` | `PreparedBlank`; [prepared-blank record](plan.md#prepared-blank) |
| `cite` | `Citations` |

### Stock components

`components` lists separate authored blanks. Each `StockComponent` requires a
known, nonblank `id`. The remaining fields are optional and accept `"unknown"`.
Placement uses the same model-frame semantics as
[plan stock](plan.md#stock): rectangular origins are corners, round origins
are starting-face centres, `axis` is the length direction and `section_axis`
orients a rectangular section.

| Field | Type | Presence |
|---|---|---|
| `id` | `str`, not blank or `"unknown"` | Required |
| `form` | `str` | Optional |
| `note` | `str` | Optional |
| `dia_mm` | `Number` | Optional |
| `length_mm` | `Number` | Optional |
| `section_mm` | `Vector` | Optional |
| `origin_mm` | `Vector` | Optional |
| `axis` | `Vector` | Optional |
| `section_axis` | `Vector` | Optional |
| `cite` | `Citations` | Optional |

### Plan-only profiled blanks

The shared `Stock` and `StockComponent` models also define
`blank: ProfiledBlank`, but inventory rejects any declared `blank` key,
including `blank = "unknown"`, and any `form = "profiled_blank"` on stock or
a component (exit 3). It is not an accepted inventory field.
A [profiled blank](plan.md#profiled-blank) is part-specific supply bound to
STEP in that part's bundle. Declare it as plan stock instead.

## Source

`source` can be a string or this provenance record. It can qualify identity
resolution, but never supplies a dimension's measurement record or inherits
trust into dimensions.

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

Every category and set member uses this shared record. A field being accepted
here does not make it relevant to every kind of item. Rules determine
applicability, and [dimension trust](#fact-local-m5-trust) remains separate from
identity provenance. All fields are optional and accept `"unknown"`.

### Identity, provenance and membership fields

| Field | Type or meaning |
|---|---|
| `name` | `str`, display name |
| `kind` | `str`, item family used by consumers |
| `make` | `str` |
| `control` | `str` |
| `operation_mode` | `str` |
| `note` | `str` |
| `coating` | `str` |
| `material` | `str` |
| `coverage` | `str` |
| `by` | `str` |
| `standards` | `str` |
| `standard` | `str` |
| `sku` | `str \| int` |
| `units` | `str`; supported length units are `mm`, `in`, `inch` |
| `verify` | `bool`, identity verification flag |
| `present` | `bool`, explicit ownership/presence |
| `shop_made` | `bool`; also implied by `kind = "custom"` |
| `source` | `str \| Source` |
| `cite` | `Citations` |
| `purchase` | `str`, bought-finished item description |
| `acceptance` | Nonempty `list[AcceptanceCheck]`; [receipt checks](#purchased-tooling) |
| `members` | `dict[str, InventoryItem \| Unknown]` |
| `standard_accessories` | `list[str]` |
| `included` | `list[str]` |
| `candidates` | `dict[str, str]` |
| `holders` | `dict[str, int \| Unknown]` |
| `make_ops` | Nonempty `list[MakeOp]`; [make operations](#make-operations) |
| `solids` | `list[FixtureSolid]`; [primitive fields](#fixture-solid-fields) |

### Compatibility and construction labels

These text fields describe identity or compatibility; their names do not
establish measured geometry.

| Field | Type |
|---|---|
| `shank` | `str` |
| `drawbar` | `str` |
| `insert` | `str` |
| `arbor` | `str` |
| `jaw_bolt` | `str` |
| `mount` | `str` |
| `fits` | `str` |
| `stud` | `str` |
| `t_slot_in` | `str` |
| `series` | `str` |
| `taper` | `str` |
| `thread` | `str`, explicit nominal size/pitch designation for a tap or die |
| `thread_hand` | `"right"` / `"left"` / `"unknown"`, thread handedness |
| `thread_class` | `str`, explicit thread class or `"unknown"` |

### Machine and indexing fields

| Field | Type or meaning |
|---|---|
| `envelope` | `MachineEnvelope`; [measured limits](#measured-envelopes-and-installed-tool-stacks-m5) |
| `headstock_tilt_deg` | `float` |
| `swing_over_bed_in` | `float`, top-level descriptive value, not the nested headroom limit |
| `between_centres_in` | `float`, top-level descriptive value, not the nested headroom limit |
| `cross_slide_travel_in` | `float` |
| `compound_travel_in` | `float` |
| `weight_lb` | `float` |
| `worm_ratio` | `float` |
| `centre_height_in` | `float` |
| `swing_in` | `float` |
| `plates` | `float` |
| `pieces` | `float` |
| `swivel_base` | `bool` |
| `scroll` | `bool` |
| `independent` | `bool` |
| `spindle` | [Spindle](#spindle) |
| `leadscrew` | [LeadScrew](#leadscrew) |
| `capacity_in` | `float \| list[Number] \| Capacity`; [nested capacities](#capacity) |
| `tailstock` | [Tailstock](#tailstock) |
| `threads` | [Threads](#threads) |
| `toolpost` | [Toolpost](#toolpost) |
| `direct_index` | [DirectIndex](#directindex) |
| `tilt_deg` | [Tilt](#tilt) |
| `plate_holes` | `dict[str, Vector]` |
| `bars` | [Bars](#bars) |

### Cutting-tool and installed-stack fields

Only the listed spellings are modeled. A stem shown with alternatives still
permits one authored spelling, not simultaneous copies.

| Field | Type or meaning |
|---|---|
| `hand` | `str`, cutting hand; separate from `helix_hand` |
| `center_cutting` | `bool`; see [plunge data](cutting-data.md#plunge) for the supported end-mill use and known gap in tool-kind enforcement |
| `chart` | `str`, cutting-data citation |
| `angle_deg` | `float`, including centre-seat angle |
| `point_angle` | `MeasuredAngle`, drill-point included angle |
| `dia` / `dia_mm` / `dia_in` | `MeasuredLength` |
| `flute_len` / `flute_len_mm` / `flute_len_in` | `MeasuredLength` |
| `pilot_len` / `pilot_len_mm` / `pilot_len_in` | `MeasuredLength`, combined drill/countersink Table 6 drill length C from countersink start to point tip |
| `oal` / `oal_mm` / `oal_in` | `MeasuredLength` |
| `shank_mm` | `MeasuredLength`, tool body past its flutes; [`reach`](rules-geometry.md#reach) checks it against retained stock |
| `shank_in` | `MeasuredLength \| str \| dict[str, list[str]]`; tool shank as above, or set label/size map |
| `flutes` | `int \| list[int]` |
| `helix_deg` | `{ value, cite, measured, verify }`, end-mill helix angle 0 ≤ β < 90; cited vendor nominal is enough, bare numbers are bad input, uncited/flagged records remain debt |
| `helix_hand` | `"right"` / `"left"`, flute hand |
| `grip_mm` | `MeasuredLength` |
| `gauge_len_mm` / `gauge_len_in` | `MeasuredLength` |
| `gauge_dia` / `gauge_dia_mm` / `gauge_dia_in` | `MeasuredLength` |
| `projection_mm` / `projection_in` | `ProjectionMap`, tools only; [pair ownership and precedence](#projection-ownership-and-precedence) |
| `lead_mm` | `MeasuredLength`, reamer lead |
| `max_shank_in` | `float` |
| `capacity_mm` | `float`, nominal collet size with ISO 286 h6 shank band, or manual tap-wrench/follower upper nominal tap size; [manual taps](#manual-taps-and-wrenches) |
| `head_in` | `float` |
| `max_offset_in` | `float` |
| `dial_in` | `float` |
| `min_bore_in` | `float` |
| `sfm` | `float` |
| `chip_load_mm_per_tooth` | `float` |
| `feed_mm_rev` | `float` |

Turning tools and toolpost bodies also accept these fact-local dimensions.
See [lathe rules](rules-lathe.md) for their geometric use.

| Field | Type |
|---|---|
| `nose_radius_mm` / `nose_radius_in` | `MeasuredLength` |
| `reach_mm` / `reach_in` | `MeasuredLength` |
| `edge_len_mm` / `edge_len_in` | `MeasuredLength` |
| `head_len_mm` / `head_len_in` | `MeasuredLength` |
| `shank_width_mm` / `shank_width_in` | `MeasuredLength` |
| `functional_width_mm` / `functional_width_in` | `MeasuredLength` |
| `body_width_mm` / `body_width_in` | `MeasuredLength` |
| `body_depth_mm` / `body_depth_in` | `MeasuredLength` |
| `insert_angle_deg` | `MeasuredAngle` |
| `entering_angle_deg` | `MeasuredAngle` |
| `blade_width_mm` / `blade_width_in` | `MeasuredLength`, grooving/parting blade front-edge width |

### Saw and edge-finder fields

| Field | Type or meaning |
|---|---|
| `blade_speed_sfm` | `[Number, Number]`, machine blade-speed limits |
| `saw_modes` | Nonempty `["horizontal" \| "vertical", ...]` |
| `kerf_mm` / `kerf_in` | `MeasuredLength`, selected powered or hand-saw blade |
| `tpi` | `{ value, cite, measured, verify }`, blade teeth per inch: one positive number or positive `[coarse, fine]` with coarse < fine; bare numbers are bad input, uncited/flagged records remain debt |
| `finder_type` | `"mechanical"` / `"electronic"`; [edge finder](#edge-finder) |
| `tip_in` | `float`, finder tip diameter |
| `rpm_range` | `[Number, Number]`, maker spindle-speed band; known endpoints satisfy 0 < low ≤ high |

### Workholding dimensions

| Field | Type or meaning |
|---|---|
| `jaw_width_mm` / `jaw_width_in` | `MeasuredLength` |
| `jaw_depth_mm` / `jaw_depth_in` | `MeasuredLength` |
| `jaw_height_mm` / `jaw_height_in` | `MeasuredLength` |
| `opening_mm` / `opening_in` | `MeasuredLength` |
| `bed_height_mm` / `bed_height_in` | `MeasuredLength` |
| `height_mm` / `height_in` | `MeasuredLength` |
| `length_mm` / `length_in` | `MeasuredLength` |
| `width_mm` / `width_in` | `MeasuredLength` |
| `diameter_in` | `float`, not a chuck jaw-capacity range |
| `thickness_in` | `float` |
| `thickness_mm` | `MeasuredLength`, including jaw-button thickness |
| `spigot_dia_mm` / `spigot_dia_in` | `MeasuredLength` |
| `spigot_length_mm` / `spigot_length_in` | `MeasuredLength` |
| `capacity_min_mm` / `capacity_min_in` | `MeasuredLength`, follow/steady-rest minimum jaw capacity |
| `capacity_max_mm` / `capacity_max_in` | `MeasuredLength`, follow/steady-rest maximum jaw capacity |
| `jaw_angles_deg` | `list[Number]`, follow-rest directions about the spindle, degrees from the tool |
| `body_dia_mm` / `body_dia_in` | `MeasuredLength`, chuck body or steady-rest ring OD |
| `body_length_mm` / `body_length_in` | `MeasuredLength`, chuck body or steady-rest ring axial length |
| `bore_dia_mm` / `bore_dia_in` | `MeasuredLength`, chuck or rotary-table bore |

### Set coverage and gauge fields

| Field | Type or meaning |
|---|---|
| `sizes` | `list[str \| int \| float]` |
| `sizes_in` | `list[str \| float] \| dict[str, list[str]]` |
| `sizes_mm` | `Vector` |
| `styles` | `list[str]` |
| `heights_in` | `list[str \| float]` |
| `shims_in` | `list[str \| float]` |
| `ranges_in` | `list[str]` |
| `range_in` | `float \| list[Number]` |
| `range_mm` | `float \| list[Number]` |
| `size_in` | `str \| list[Number]` |
| `nominal_dia_mm` | `dict[str, Number]` |
| `nominal_dia_cite` | `dict[str, Citations]` |
| `ra_range` | Two-item `list[Number]`, µm Ra; roughness gauge capability read by inspection `finish_ra` |
| `resolution_mm` / `resolution_in` | `MeasuredLength`, > 0 when known; gauge resolution or machine DRO step |
| `leaf_tolerance_mm` / `leaf_tolerance_in` | `MeasuredLength`, radius/profile leaf ± tolerance consumed by `R MAX` |
| `runout_max_in` | `float` |

A zero or negative resolution is rejected at load; it cannot be used to read
every band or zone. Inspection trusts only the resolution fact's own
qualifiers. Verification debt, incomplete measurement or non-`measured`
status leaves it unknown rather than establishing pass or error.

With the plan's digital readout, a declared positive machine resolution is
the DRO grid used to round printed coordinates and depths to the safe side.
Missing resolution uses the disclosed provisional 0.001 plan-unit step.
Rules judging on that grid still remain unknown when the declared step is
not measured and name resolution as debt. See
[DRO grid consumption](rules-coordinates.md#dro-grid-consumption).

### Mechanical dial source facts

Readout identity belongs to the plan's [`dro`](plan.md#dro), not an inventory
machine's `control`, `name` or other descriptive text. An omitted `dro.kind`
retains the digital behavior. Explicit `"handwheel"` selects mechanical dials;
explicit `"unknown"` does not establish a digital readout.

Mechanical `dro.graduation` is a nominal division in the declared `dro.units`,
which can be `"in"` even when CAD lengths are in mm. It is not the machine's
measured `resolution_mm` or `resolution_in`. On a lathe, `radius_mode = false`
makes the X marking a diameter change, so radial travel is half that marking;
`true` makes it radial. An unknown scale meaning remains debt.

Source-authored pickup, calibration and backlash procedures do not prove
physical accuracy or register a dial to the part datum. Keep unavailable
physical settings and graduation/backlash facts unknown. The checker retains
that debt without asking for a digital DRO measurement or inferring an
electronic setting. See
[mechanical dials and unknown readouts](rules-coordinates.md#mechanical-dials-and-unknown-readouts)
for findings and printed instructions.

### Manual-arc fields

The detailed use and measurement requirements are under
[Manual-arc kit](#manual-arc-kit). These fields complete its shared item
schema.

| Field | Type or meaning |
|---|---|
| `graduation_deg` / `vernier_deg` | `float`, rotary-table dial graduation/vernier; printed readings round to vernier, otherwise graduation |
| `dial_increases` | `str`, `"clockwise"` / `"counterclockwise"` table turn that increases the dial reading |
| `t_slots` | `float`, rotary-table slot count |
| `max_work_mm` / `max_work_in` | `MeasuredLength`, largest work diameter that must contain the stock swing |
| `t_slot_width_mm` / `t_slot_width_in` | `MeasuredLength` |
| `button_dia_limits_mm` / `button_dia_limits_in` | `MeasuredLimits`, filing-button OD |
| `button_bore_limits_mm` / `button_bore_limits_in` | `MeasuredLimits`, button bore on the pin |
| `pin_dia_limits_mm` / `pin_dia_limits_in` | `MeasuredLimits`, pin through button and part bores |
| `button_runout_mm` / `button_runout_in` | `MeasuredLength`, button OD TIR about its bore |
| `pivot_play_mm` / `pivot_play_in` | `MeasuredLength`, swing-arm beam-axis displacement from pivot axis; measured |
| `rail_radius_mm` / `rail_radius_in` | `MeasuredLength`, arc-sled rail radius about its centre |
| `rail_form_error_mm` / `rail_form_error_in` | `MeasuredLength`, greatest filed-rail arc-form departure; measured |
| `roller_runout_mm` / `roller_runout_in` | `MeasuredLength`, guide-roller OD TIR; measured |
| `rail_side` | `"outer"` / `"inner"`, roller contact from outside the rail arc or centre side |
| `roller_dia_mm` / `roller_dia_in` | `MeasuredLength`, guide-roller OD; measured, required for inside rollers |
| `radius_limits_mm` / `radius_limits_in` | `MeasuredLimits`, seated setting-bar/master-arc touch radius about guide centre; measured |
| `roller_height_mm` / `roller_height_in` | `MeasuredLength`, guide-roller top above table; measured, picture only |
| `rail_angle_deg` / `rail_angle_error_deg` | `MeasuredAngle`, trammel pin-line crossing angle and greatest angle error; measured |
| `pin_spacing_mm` / `pin_spacing_in` | Map from pin-pair name to `MeasuredLength`; measured |
| `pin_spacing_error_mm` / `pin_spacing_error_in` | `MeasuredLength`, greatest pair-spacing error; measured |
| `pin_clearance_mm` / `pin_clearance_in` | `MeasuredLength`, pin radial carriage play; measured |
| `rail_offset_mm` / `rail_offset_in` | `MeasuredLength`, greatest aligned rail pin-line offset from spindle axis; measured |
| `rail_travel_mm` / `rail_travel_in` | `MeasuredLimits`, nearest/farthest pin stations from spindle axis; measured |
| `pin_dia_mm` / `pin_dia_in`, `rail_width_mm` / `rail_width_in`, `rail_height_mm` / `rail_height_in` | `MeasuredLength`, trammel picture only; measured |
| `carrier_length_mm` / `carrier_length_in`, `carrier_width_mm` / `carrier_width_in`, `carrier_thickness_mm` / `carrier_thickness_in` | `MeasuredLength`, trammel carrier-plate picture only; measured |
| `make_document` | `{ id, revision, cite }`, document used to build and commission the trammel outside the setup sheet |
| `commissioning_record` | `str`, location of rail-alignment installation record |
| `dowel_reading_mm` / `dowel_reading_in` | `MeasuredLength`, largest commissioning miss from predicted carriage-dowel stations; measured |

### Fixture solid fields

`solids` contains `FixtureSolid` records in the item's local frame. Their
geometry, void and trust behavior is defined under
[authored primitives and voids](#authored-primitives-and-voids).
`Point3` below means exactly three Numbers. Each field is optional and accepts
`"unknown"`; a drawable primitive still needs its shape's actual geometry.

| Field | Type or meaning |
|---|---|
| `name`, `shape`, `note`, `label`, `locates`, `fastener` | `str` |
| `at_mm` | `Point3`, box minimum corner or cylinder base centre |
| `size_mm` | `Point3`, box dimensions |
| `axis` | `Point3`, cylinder axis |
| `dia_mm`, `length_mm` | `Number`, cylinder diameter/length |
| `void` | `bool` |
| `cuts` | `list[str]`, same-list primitive names |
| `shim` | `bool` |
| `supply` | `"made"` / `"bought"` / `"existing"` |
| `bears` | `"bore"` / `"face"` |
| `records` | `list[RecordBlank]`; [measurement record blanks](#measurement-record-blanks) |
| `make_ops` | Nonempty `list[MakeOp]`; [make operations](#make-operations) |
| `measured` | `Measurement`, primitive-local evidence |
| `verify` | `bool`, primitive-local verification flag |
| `flatness_mm` | `MeasuredLength`, top-face flatness for the proposed area-hold stack |
| `material` | `str`, contact-face material for the proposed area-hold strength interface |

## Spindle

`machines.<id>.spindle` declares machine spindle identity, speed bands and mill
cutting rotation. Holder matching consumes its taper; speed selection and
edge-finder pickup consume its available speed bands.

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

### Mill rotation and contour order

`rotation` is viewed from above, looking down setup -Z. A right-hand cutter
runs `cw` (M03). It can be bare or a record such as
`{ value = "cw", measured = {status, by, date, instrument} }`.
A labelled value with verification debt or non-`measured` status counts as
undeclared and enters the coordinates measurement checklist.

Together with operation `direction` (`conventional` / `climb`), rotation
determines contour-table cutting order. Without it, that order remains
unknown. See [coordinates](rules-coordinates.md).
A reamer's `lead` uses the same fact-local trust: an untrusted lead leaves
`tip_endpoints` unknown and is listed as debt.

### Lathe spindle instructions

Lathe turn comes from the operation's tool, not machine `rotation`.
Turning, facing, grooving and boring tools with either `hand = "right"` or
`"left"` are posed edge-up and use FORWARD: the top of the work turns toward
the operator. A tailstock centre drill, drill, reamer or tap uses FORWARD for
a right-hand cut and REVERSE for a left-hand cut. Undeclared tool hand
produces a STOP.

When all spindle operations in a setup use the same known turn, the operation
heading states it once (`spindle FORWARD whenever it runs: …`) and rpm cells
give only speed. Mixed turns print the word in each rpm cell, with the
heading defining the words once.

## Length and angle facts

Machine travel and spindle-to-table limits live under `envelope`, using
`EnvelopeTravel` and `MachineEnvelope`. There are no separate `Travel` or
`Table` records, and `table_in` length/width/`t_slot` blocks are rejected.
A clamping kit's `t_slot_in` text is an identity label, not measured pitch.

Measurement evidence belongs to the fact, not the item, member, source or
envelope block. Lengths and angles use the fact records in
[Measurement records](#measurement-records); fixture primitives carry their
own measurement metadata. The [unit rules](#units-and-set-members) prohibit
duplicate single-length spellings.

## LeadScrew

The `leadscrew` record declares screw pitch, dial increment and cross-feed
choices. `tpi` here is a machine-screw value, not the blade `tpi` record.
These inventory descriptions do not supply the plan's mechanical
`dro.graduation`, calibration or physical datum registration.

| Field | Type (also accepts `"unknown"`) |
|---|---|
| `tpi` | `float` |
| `dial_in` | `float` |
| `cross_feed_ipr` | `Vector` |

## Capacity

The nested form of `capacity_in` records nominal drilling, end-milling and
face-milling capacities in inches. It does not replace measured
[machine envelope limits](#measured-envelopes-and-installed-tool-stacks-m5).

| Field | Type (also accepts `"unknown"`) |
|---|---|
| `drill` | `float` |
| `end_mill` | `float` |
| `face_mill` | `float` |

## Tailstock

`tailstock` declares quill identity and travel. Its quill diameter supplies
the modeled obstacle behind a dead-centre fixture.

| Field | Type (also accepts `"unknown"`) |
|---|---|
| `taper` | `str` |
| `quill_travel_in` | `Number` |
| `quill_dia_mm` / `quill_dia_in` | `MeasuredLength` |

## Threads

`threads` lists the lathe's available inch TPI and metric pitches.

| Field | Type (also accepts `"unknown"`) |
|---|---|
| `inch_tpi` | `Vector` |
| `metric_pitch_mm` | `Vector` |

## Toolpost

`toolpost` declares holder-series compatibility and the printed instructions
for setting a lathe tool on centre and squaring a grooving/parting blade.

| Field | Type (also accepts `"unknown"`) |
|---|---|
| `series` | `str` |
| `type` | `str` |
| `note` | `str` |
| `holders` | `int` |
| `included` | `bool` |
| `centre_height` | `str`: how a tool is set on spindle centre height before its first touch-off in a lathe setup (printed as that step; without it the sheet states the requirement alone) |
| `square_blade` | `str`: how a grooving/parting blade is squared to the spindle axis in the same step |
| `cite` | `Citations` for those words |

## DirectIndex

`direct_index` declares the direct-index position count and angular step.
See [indexing rules](rules-indexing.md) for setting checks.

| Field | Type (also accepts `"unknown"`) |
|---|---|
| `positions` | `float` |
| `step_deg` | `float` |

## Tilt

The `tilt_deg` record declares downward and upward tilt limits in degrees.

| Field | Type (also accepts `"unknown"`) |
|---|---|
| `down` | `float` |
| `up` | `float` |

## Bars

`bars` describes boring-bar count, type and available shank, minimum-bore and
depth sizes. Its fields are declarations, not installed reach measurements.

| Field | Type (also accepts `"unknown"`) |
|---|---|
| `count` | `int` |
| `type` | `str` |
| `shank_in` | `Number` |
| `min_bore_in` | `Vector` |
| `depth_in` | `Vector` |
