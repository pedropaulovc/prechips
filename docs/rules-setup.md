# Holding, headroom and datum rules

Use these rules to interpret findings about holding declarations, machine space,
prepared stock and drawing datums. Most checks compare declared fields and nominal
arithmetic. They do not certify measured workholding or prove a collision-free
setup. The kernel-measured vise and thin-wall checks are in
[geometry rules](rules-geometry.md). Missing measurements remain unresolved debt.

On this page:

- Holding and locating: [`hold_fields`](#hold_fields), [`swivel`](#swivel),
  [`centre_support`](#centre_support) and [`tooling_hole`](#tooling_hole).
- Stock preparation and machine space: [`prepared_blank`](#prepared_blank),
  [`headroom`](#headroom) and [measured inventory screens](#m5-measured-inventory-screens).
- Agreement between sources: [`datum_consistency`](#datum_consistency) and
  [`consistency`](#consistency).
- Related checks: [declared workholding and indexing](#m2-declared-workholding-and-indexing).

Field definitions belong in the [plan](plan.md), [inventory](inventory.md) and
[policy](policy.md) references. For a worked report, use the
[tutorial](manual/tutorial.md) or [demonstration](manual/demo.md). For unresolved
findings, use [troubleshooting](manual/troubleshooting.md). The
[FAQ](manual/faq.md) explains the limits of a passing plan.

## `hold_fields`

The rule produces one finding per setup. It checks that holding and cutting
choices are declared; it does not compare every holding dimension or establish
that the fixture was installed as written.

### Required declarations

A fixture-held setup needs a fixture, stop, grip and clamp declaration, plus
coolant and deburr decisions. A vise or nonlathe setup needs `fixed_jaw` unless
that field is explicitly `not_applicable`. Lathe setups also need stock OD,
support, grip-on and at least one known end station. Other setups need stock
`top_z` and `bottom_z`. When you supply supports, support orientation, parallels,
jaw direction, locator or stop-face fields, the rule checks those declarations
too.

Every nonmanual machining operation needs a holder; saw cut-off needs none.
Every nonmanual cut needs `direction`, including face, profile, pocket, turn,
form and parting actions, with these exceptions:

- Point and hole actions: `spot`, `drill`, `ream`, `tap`, `counterbore`, `center`
  and `center_drill`. A direction supplied for one of these is still checked.
- Saw cut-off, whose `cut_plane` defines the setting.

An explicitly unknown action without a direction leaves that requirement
unknown. Missing or empty required fields are errors. Explicit `"unknown"`
values remain unknown. There is no fallback grip or deburr limit.

### Hand-fed saw holding

A hand-fed hold (`hold.kind = "hand_fed"`) applies to a vertical bandsaw cutting
along a scribed line. See [hand-fed work on the saw table](plan.md#hand-fed-on-the-saw-table).
It needs no fixture, stop, grip, clamp or fixed-jaw field. Coolant, deburr and
stock top/bottom Z remain required, as do all four feeding declarations:
`hold.guide_above_mm`, `hold.push_aid`, `hold.feed_from` and `hold.end_support`.
Each undeclared feeding field appears as missing and unknown. A `feed_from`
that does not identify an end of the line also remains unresolved.

If the blade, machine or `saw_modes` is unresolved, the hold is unknown and
lists `hand_fed_scope` with the reason. It lists `hold.kind` instead when the
kind itself is stated `"unknown"`. A setup outside the supported hand-fed scope
is rejected while loading, with exit 3. For an admitted hand-fed hold,
`stock_diameter`, `vise`, `thin_wall_under_clamp` and `fixture_interference` are
`not_applicable`.

The work must reach the shop policy's `min_hand_feed_mm` finger-to-blade
clearance at every position along each cut's scribed arc. The check uses the
stock box for that cut: the kernel's `stock_bbox_before_mm`, or the setup-entry
box for the first cut. Work that cannot reach the minimum produces `✗` naming
the cut. The result is `?` if the box is too loose to decide, the minimum is
absent, nonpositive, uncited or flagged, the kernel did not box that cut's
stock, or the path is unplaced. The minimum needs a usable citation and
`numbers_verify = false` for that fact. Resolve the feeding choice, policy
fact or cut-specific geometry named in the finding; declaring a hand-fed
hold does not waive this clearance.

### Stop-face availability

A declared `hold.stop_face` must exist on the arriving stock. It may name
`"stock_end"`, a raw-stock `as_is_faces` face, or a feature cut by an earlier
setup in this setup's stock lineage. A face first cut in this setup or a later
one is an error naming the operation:

`{setup}: the hold stops on {face}, which the arriving stock does not have yet; it is first cut in {setup} op {op}.`

Without an earlier maker or supplied as-is face, an error requires settled
as-is evidence and no pending possible cut. A pending cut includes an
earlier lineage operation with unknown action, or a possible upstream
operation outside a route whose lineage omits `stock_in`. Unsettled as-is
faces also leave availability unknown. When nothing cuts the face and those
possibilities are settled, the emitted sentence ends `no operation cuts it.`
Correct the stop to a surface the received stock has, or correct the
preparation route that establishes it.

### Fixture alignment

A mill setup using a vise or angle plate needs `hold.align` when it mounts or
turns that fixture. Alignment is due at the first such setup on the machine,
or when any of these changes from the previous setup on that machine:

- Fixture identity.
- A vise's `jaws_along` or `jaws_angle_deg`.
- An angle plate's `pose`.

An intervening setup on another fixture counts as removal of the vise or
plate. References are compared by inventory identity, not just their spelling.

For square alignment, `indicator` must select an inventory gauge of kind
`dial_test_indicator` or `dial_indicator`, and `limit_mm` and `over_mm` must be
positive. An angle plate's `face` must name one of its solids. A missing block,
invalid value, absent inventory gauge or wrong gauge kind is an error. An
explicit unknown remains unknown, including `align = "unknown"`, which leaves
each member unknown. Unknown gauge kind or presence, or `verify = true`, also
leaves the indicator unresolved. `tool_resolves` checks this selected inventory
reference like a tool or fixture.

The sweep runs along the vise's `jaws_along`. For an angle plate it follows
the longer horizontal side of the named box solid, transformed by `pose` into
the setup frame. A run that cannot be identified as X or Y is unknown under
`hold.align.travel`. Evidence records `align_due` as `mounted`, `jaws turned`,
`jaws swivelled`, `plate moved` or `not_applicable`.

The setup sheet's HOLD section prints the alignment after the mount line:
sweep the named indicator along the fixed jaw or locating face over `over_mm`
of the named travel and keep the reading change within `limit_mm`. Any
unestablished part prints as a STOP.

A swivelled vise (`hold.jaws_angle_deg`) uses `hold.align.method` instead of a
square sweep along a travel. `indicate_jaw` needs the indicator, `limit_mm` and
`over_mm`; a stated method needs positive `tolerance_deg` and `cite`. There is
no `hold.align.travel` for this setting. Supplying `jaws_angle_deg` for a
non-vise fixture, or `align.method` for a hold with no swivel, is an error in
`numbers.misdeclared`. The sheet prints the swivel on the mount line and its
setting step. An unresolved angle, method, indicator, DRO move, limit or
setting tolerance prints a STOP. See [swivelled vise](plan.md#swivelled-vise).

### Findings and evidence

The standard declaration sentences are:

- `{setup}: holding declarations need {comma-separated missing/unknown fields}.`
- `{setup}: holding and cutting decisions are declared; this does not approve measured fixture clearance.`

Evidence includes the hold record, stock stations, coolant, deburr, cut
directions, missing fields and alignment reason. The rule cites PLAN §4.1
hold fields. Supply the missing authored choices and resolve the selected
inventory identities; use the separate geometry rules for fixture clearance.
Implementation: [`hold_fields.py`](../src/prechips/rules/hold_fields.py).

## `swivel`

The rule produces one finding for each setup holding work in a mill vise with
a nonzero `jaws_angle_deg`. Other setups have no row. Explicit
`jaws_angle_deg = 0` means square jaws: there is no swivel finding and HOLD
prints no swivel.

### Setting tolerance

The setting tolerance δθ comes from `hold.align`, as defined under
[swivelled vise](plan.md#swivelled-vise):

- For `indicate_jaw`, it is the dialled DRO-grid move's angle off the jaw line
  plus asin((`limit_mm` + √2·step/2) / L). L is that move's length; step is the
  machine's measured DRO resolution.
- For a stated method (`graduations`, `protractor` or `sine_bar`), it is the
  cited `tolerance_deg`.

If alignment is not due because the setup keeps the earlier vise setting on
the same machine, the rule inherits that setting's `hold.align` and records
`set_in`. This applies even if the later setup declares an alignment of its
own: the sheet prints a setting step only where one is due, and that is the
setting used to judge subsequent cuts.

### Cut-angle and displacement checks

The setting tolerance applies to a cut edge only when the work turns with
the jaws. The kernel must prove flat work faces seated on both jaw planes
(`parallel_pair`, reported as `work_registered`). Otherwise the work's angle
to the jaws is unknown, and no edge receives a proved setting tolerance.

Every walled machining cut is compared with its feature's ± angle band.
Facing, point/hole actions, saws and manual work are exempt from that angle
comparison. The band is `angle_tol_deg`; if absent, a BASIC angle supplies no
band, while other angles use `general_tolerances.angular_deg`, as described by
[indexing](rules-indexing.md). A band narrower than δθ is an error. Unknown
setting tolerance, angle or band stays unknown. Invalid setting declarations
or a negative angle band are errors. An established failed band or invalid
declaration keeps error precedence even when other inputs remain unresolved.

Point/hole actions and walled cuts also report:

- `reach_mm`: the farthest printed cutter-centre path point from DRO zero,
  using `stock_removal_bounds` when no printed path is available.
- `shift_mm` = reach·sin δθ: the displacement due to the setting error at that
  reach, for inspection to read.

A horizontal face is unchanged by rotation about Z. Reporting the shift does
not establish a positional acceptance test for a point operation.

### Findings and remedy

Typical sentences are:

- `{setup}: the swivel set to ±{δθ}° holds every walled cut's angle band.`
- `{setup}: the swivel set to ±{δθ}° does not hold op {op} ({feature}: ±{band}°).`
- `{setup}: whether the swivel holds its cuts' angle bands is unresolved: {inputs}.`
- `{setup}: swivel setting declarations are invalid: {reasons}.`

A setup with no walled cuts can report that the setting widens no angle band.
Resolve the setting method, measured DRO grid, work registration or sourced
angle band named in the finding. If the setting is too coarse, revise the
actual setting method or process; changing an explanatory note does not
change δθ.

Evidence includes `jaws_angle_deg`, `line_deg` (jaw line from setup X),
`set_in`, `method`, `tolerance_deg`, derived `limit_mm`/`over_mm`/`dro_step_mm`,
`cuts`, `unresolved` and `invalid`.
Implementation: [`swivel.py`](../src/prechips/rules/swivel.py).

## `centre_support`

The rule produces one finding per setup and is always required wherever a
centre carries the work. No shop-policy entry is needed, and none can waive
it (`findings.ALWAYS_REQUIRED`, like `joint_fit` and `joint_assembly`).

### Applicability and centre identity

A centre is any of these:

- A `support` or `supports` entry whose inventory `kind` contains a whole
  `centre` or `center` word, such as `dead_centre`, `live_center`,
  `tailstock_centre` or `pipe_center`.
- A support of kind `tailstock`, which carries work on its centre.
- A machine standard accessory whose name contains that word, such as
  `dead_centre_headstock`.
- A hold declaring `centre_hole` or `centre_hole_dia_mm`.

The word `tailstock` in an accessory name alone is insufficient:
`tailstock_drill_chuck` and `tailstock_quill` are not centres. Neither is a kind
such as `self_centering_steady_rest`. A known non-centre kind stays non-centre
regardless of its verification or measurement debt; checks such as `stickout`
and `turning_deflection` own that debt.

Inventory identity also prevents double-counting: `support = "x"` with
`supports = ["fixtures.x"]` names one centre. A hold with no centre or possible
centre is `not_applicable` and does not block. A wholly undeclared hold names
no support for this rule to check; `hold_fields` owns that omission.

### Preparation and seat agreement

The hold's `centre_hole` must select a plan
[process feature](plan.md#process-features) of kind `centre_hole`. A
`center_drill` operation in an earlier setup of this setup's `stock_in`
lineage must have drilled it. The maker's own
[`blind_depth`](rules-operations.md#blind_depth-tip-endpoints) centre verdict
must pass. That verdict proves the declared centre is the selected tool's
own cut, accepts all tool facts used by the kernel, and checks that its mouth
is on the touched entry surface and, on a lathe, on the spindle axis. The
process `mouth_dia_mm` must equal the hold's `centre_hole_dia_mm`.

| Result | Conditions |
| --- | --- |
| `error` | A fully routed lineage has no earlier maker, including a hole made only in this setup or later; a maker's `blind_depth` verdict is an error; or the seat and drilled mouth differ. Established errors take precedence over unresolved facts. |
| `unknown` | `centre_hole` is undeclared; any setup in the lineage lacks `stock_in`; preparation is unknown; seat or mouth diameter is unknown; a support's identity or kind is unresolved; or more than one centre carries the work while the hold names only one seat. |
| `pass` | The earlier maker and its preparation pass, the route is declared, the seat agrees and no further centre remains unchecked. The finding names the maker setup and operation. |

Unresolved support identity includes an unknown reference, a reference absent
from inventory, an item declared `"unknown"` or an unknown kind. It remains
unknown even beside a known centre because that support may be another one.
Preparation debt includes a centre size, point angle, unconfirmed tool record
or touched entry surface. Preparation errors include a size the tool cannot
cut, a tool point no shorter than its pilot, or a mouth off the surface or
axis used by the quill.

Resolve the upstream route, selected centre-drill facts and seat declaration
at their source. A centre made during the current holding cannot justify
support that was already needed when the stock arrived.

### Evidence and limits

Evidence includes supports, distinct centres, the named hole, makers before
and after this setup, route completeness, each maker's preparation status,
mouth/seat diameters, and Table 6 arithmetic (`drill_length_mm`,
`countersink_depth_mm`, `depth_mm`).

The kernel separately seats the centre in the cut countersink and checks it
against setup-entry stock. That is fixture-render debt, outside this rule's
preparation verdict. An unknown `centre_support` blocks with exit 4 under any
shop policy; an error exits 2.
Implementation: [`centre_support.py`](../src/prechips/rules/centre_support.py).

## `tooling_hole`

The rule produces a `<setup>:<hole>` finding for each plan
[`tooling_hole`](plan.md#process-features) that a setup works or locates on.
An operation naming the hole counts as working it. Locating means that a drawn
solid of `hold.fixture` or a `hold.clamps` member names the hole in inventory
`locates`. Setups doing neither have no row; a plan with no tooling holes has
none. The rule is always required and cannot be waived by policy.

### Entry state and pin fit

The rule reads the kernel's `tooling_holes` state on the stock entering the
setup. See [tooling-hole geometry](rules-geometry.md#tooling-holes). Its fit
comparison uses the hole's `dia` band `[lo, hi]`, converted to mm, and the pin
solid's own accepted `dia_mm` under its `measured`/`verify` record:

`clearance range = [lo - pin, hi - pin] mm`

| Result | Conditions |
| --- | --- |
| `error` | A named hole is `gone`; a locating pin has no earlier drilled hole in a fully routed lineage or the entry state is still `undrilled`; the sizing operation has not run before location; or the pin exceeds the hole's smallest size `lo`. |
| `unknown` | Entry state is `partial` or unknown; the kernel is unavailable; routing or the diameter band is unknown; or a pin is noncylindrical or has an unaccepted size (unknown, `verify`, or incomplete measurement record). |
| `pass` | Each pin fits the completed hole band, with its clearance range reported. For a setup that only works the hole, the entry stock still carries it where the operations cut. |

The sizing operation is the ream when the hole has one, otherwise the drill,
as selected by `sizing`. A locator between rough drilling and a later ream
sees a drill-size hole, so it cannot use the final reamed band. Restore the
correct upstream preparation and routing, or resolve the measured pin size
and hole band named in the finding.

The band-based check and the kernel's drawn-pin/bore geometric check are
separate. The latter is part of `thin_wall_under_clamp`; neither substitutes
for the other.

### Informational clocking

For each locator, `clocking` considers every other locating cylinder placed
by a posed fixture or clamp solid, such as a HUB pin in the part's bore. When
that cylinder's posed axis is parallel to the tooling-hole axis, it reports:

- `L`: setup-frame distance between the two axes.
- `angle_rad = (hi - pin) / L`: largest diametral clearance divided by that
  distance, describing the work's possible turn about the other pin.
- `max_shift_mm`: the greatest resulting movement of a corner of the entering
  stock's bounding box.

A nonparallel axis leaves the turn unknown with a reason. Unknown clearance,
pose or stock box leaves the number unknown. These values never change the
finding's status. They are available to an error budget, such as the trammel
budget associated with issue #278; this rule does not judge that budget.

Evidence includes the hole, setup operations, entry state, makers, locators,
pin/hole diameters, clearance ranges and clocking. A tooling hole earns no
drawing coverage or finishing credit, and `inspection` requires no check on
it. Implementation: [`tooling_hole.py`](../src/prechips/rules/tooling_hole.py).

## `prepared_blank`

This always-required rule has one subject, `stock.prepared`. Without
[`[stock.prepared]`](plan.md#prepared-blank), it is `not_applicable`. An explicit
`"unknown"` declaration is unknown: the plan says the blank is prepared but
does not establish which blank the next setup receives.

### Received and cut stock

The analytic receiving box starts with the root stock. Earlier operations
in the receiving setup's `stock_in` lineage trim it plane by plane through
plan process `end_face` features. Each declared dimension (section 0, section
1 and length), placed at `origin_mm` on the blank's axes, must lie within its
± `tolerance_mm` of that box. A made face must also be square to those axes.
A face made outside the lineage or after receipt cannot prepare this blank.

The plane establishes intended facing, not the material actually removed.
The kernel's handed-on `stock_out_bbox_mm`, read along the blank's axes,
must fit the same bands, and `stock_out_volume_mm3` must fill that box
(relative 1e-6). A shallow, partial or missed face leaves a slab; a pass
inside the blank removes required material. Either is an error. If the
model-frame box cannot be read along the declared blank axes, that proof
remains unknown. A supplied blank (`stock_in = "stock"`) is the root stock
itself. Without known kernel stock, this part of the verdict is unknown.

### Blank inspection checks

The rule resolves all declared blank checks:

- `length`, `section_0` and `section_1` use
  [inspection gauge capability](rules-inspection.md) against the size ±
  tolerance band (`limits_mm`).
- `flat`, `square` and `parallel` need an inventory dial indicator, dial test
  indicator, height gauge or CMM, a written `methods` procedure, a positive
  `form_mm` limit and a verified positive gauge resolution no coarser than the
  limit.

A missing inventory gauge, a gauge that cannot measure the size band or form
being checked, or a resolution too coarse for the limit is an error. An
undeclared check, unwritten method, unknown form limit or unverified
resolution is unknown. The worse of stock preparation and inspection
capability determines the result.

### Findings and remedy

An error identifies an out-of-lineage or late face, nonsquare preparation,
received/cut size outside its band, unfilled cut-stock box or incapable gauge.
Unknown inputs include routing, size, origin, tolerance, root stock, units,
kernel stock and inspection facts. Otherwise the rule passes and names the
operations that made each face.

Correct the actual upstream cuts and blank declaration, then resolve each
check with a capable inventory gauge and written method. A process face
earns no drawing coverage; it is checked here, not by a drawing requirement.
An unknown blocks with exit 4 under any policy; an error exits 2.

Evidence includes received, declared and cut boxes, cut volume, received
sizes, face makers, faces made outside the lineage and one `checks` row per
check. Form rows include `limit_mm` and `resolution_mm`.
Implementation: [`prepared_blank.py`](../src/prechips/rules/prepared_blank.py).

## `headroom`

The rule produces one finding per setup. On a mill it screens the tool-change
stack, jaw obstruction and declared travel. On a lathe it screens swing and
length. Manual bench work within the scope below and dedicated all-saw setups
are `not_applicable`. In a mixed setup, saw operations add no fictitious
holder or spindle stack.

### Manual bench and saw scope

The manual-bench exemption requires a resolved machine of kind `bench` or
`manual`, at least one operation, and every operation to be one of `fit`,
`inspect`, `deburr`, `coating`, `scribe` or `file_to_line`, or a
`saw_cut`/`cut_off` using a resolved, verified `hand_saw`. A `fit` uses its
declared `joint.method`, such as silver braze, slip fit, press fit or weld.
The machine's bench/manual kind alone waives nothing. Another or unknown
action, or a powered/unresolved saw tool, does not establish this manual
exemption; the applicable machine screens remain in force.

A dedicated all-saw setup has saw cuts and no other nonmanual operations.
Manual inspection/deburring can accompany those cuts. Its saw-specific
exemption is separate from the manual-bench predicate.
Implementation: [`_bench.py`](../src/prechips/rules/_bench.py).

### Mill stack

The stack, in mm, is:

`fixture bed + parallels + support blocks + physical stock height + tool projection + holder gauge length + 25 mm insertion`

Physical stock height (`stock_height_mm`) is
`top_z - retained_rail_bottom_z` when a retained rail is authored, otherwise
`top_z - bottom_z`. Support-block orientation must explicitly select a listed
height; the rule does not choose an arbitrary block dimension.

Tool projection comes from the selected tool's `projection_mm` entry for the
selected holder. Only an absent pair entry permits `tool OAL - holder grip`
when both facts are known. An explicit unknown projection, or conflicting
entries that spell the same holder identity twice, stays unknown instead of
falling back to OAL minus grip. The 25 mm insertion allowance comes from
PLAN §4.1; it is not holder grip. Per-operation margin is
`spindle_to_table_max - stack`.

Machine spindle-to-table maximum and X/Y travel come from the machine's
`envelope` block, shared with `envelope` and `travel`. Each limit needs its own
accepted measurement. An unmeasured vendor nominal, for example one with
`verify = true`, remains evidence in `numbers`, adds
`numbers.measurements` debt and keeps the result `?`. There is no top-level
`spindle_to_table_max_in`/`travel_in` fallback.

A dividing head carries the work at its axis. Its work top above the table is
its declared centre height plus
`stock_state.top_z - hold.pose.origin_mm[2]`, plus any parallel/support lift.
The pose origin locates the chuck axis in setup coordinates. The tool
projection, holder gauge and 25 mm insertion are added to that work top;
head body/bed height plus full stock height is not a vise-like substitute.
Translating stock Z and axis Z together leaves the result unchanged. Missing
centre/axis facts or verification debt remain unknown. A tilted declared
head axis does not by itself invalidate a known axis-origin Z. The report
and sheet show centre height, axis Z and work-top height separately.

### Jaw obstruction

Jaw height is an obstruction, not a stack layer:

- `jaw_top_z = bottom + jaw_height - (parallels + supports)`.
- Cut clearance is `to_z - jaw_top_z`.

A below-jaw cut is clear only when its cutter stays more than 3 mm inside
both jaw faces along the clamp axis, or more than 3 mm beyond the jaw ends
along their run. Jaw ends are `jaw_center_along_mm` ± half the vise's accepted
`jaw_width`, allowing a blank end to overhang the vise. The cutter footprint
is the printed cutter-centre path, otherwise `stock_removal_bounds`, widened
by the cutter radius.

For a swivelled vise, jaw faces come from the kernel's
`jaw_frame_stock_bbox_mm`; paths are transformed into that frame, using box
corners for `stock_removal_bounds`. An unknown swivel establishes no faces.
Other below-jaw cuts require geometric path checks and remain unknown;
they are not invented collision errors.

### Setup-entry stock and table travel

When an already successful kernel result exists, `stock_extent_x_mm` and
`stock_extent_y_mm` describe its setup-entry `stock_bbox_mm`, already in setup
axes. This applies to raw boxes, round bars, profiled/prepared blanks,
components, joined stock and earlier setup output.

Without that box, only a raw single supply (`stock_in` absent or `"stock"`,
with no components or profiled blank) can use authored stock placement:
`length_mm` follows stock `axis`; a box's `section_mm` follows `section_axis`
and `axis × section_axis`; a round bar's `dia_mm` spans across its axis.
Missing `axis` or `section_axis` leaves placement unknown. The bar is never
assumed to lie along model X. Other stock routes remain unknown without the
entry box; neither the finished part nor raw supply replaces them.
`headroom` never starts the kernel. This stock-placement contract is also
recorded in [issue #297](https://github.com/pedropaulovc/prechips/issues/297).

Per-axis `travel_checks` uses the [`travel`](#m5-measured-inventory-screens)
rule's own setup cutter-centre span (`required_mm`) against measured travel,
with entry stock as `part_mm`. A fixture wider than travel is not itself an
error: the required table reach is not the fixture footprint. Fixture-on-table
coverage is outside this check; see
[issue #349](https://github.com/pedropaulovc/prechips/issues/349).

The sheet's CLEARANCE `X/Y travel: needs … (basis)` gives the span and its
basis: `cutter-centre path`, `declared cut extent`, or both. A printed path
includes approach and exit; declared extents use feature bounds or centres,
with cutter radius on profiles. Stock span alone is a lower bound, so no
computed stroke is printed:

`X travel: ? not computed — the cut's X/Y extent, with the cutter's approach and exit, is not declared.`

An axis with no motion, where every operation is at one X/Y position, has no
travel line. Unresolved spans are `?`. An established span or lower bound
exceeding measured travel errors on both rules. No separate radial tip
envelope is computed. Inch inventory lengths convert explicitly by 25.4.
Unverified dimensions establish neither a verified stack/travel pass nor a
measured clearance violation.

### Guided motion and trammels

A `guided_sweep` moves the fixture while the table stays still. Neither
`headroom` nor `travel` models that motion, so neither can pass a setup
containing one. The shipped pose checks leave these motion checks unresolved:

- `headroom` judges stack and fixture clearance only at the setup pose. It
  still needs proof that a dry pass from stop to stop clears the spindle
  nose, holder and column at every pose.
- `travel` still needs proof that the swept footprint clears the column,
  table ends and way covers. That footprint includes a swing arm's pivot
  post at the arc centre, whether on the table or an extension, or a sled's
  rollers throughout their T-slot sweep.

X and Y stay locked while the fixture moves the work. The arc span is no
table stroke: the operation's `xy_cutter_bounds_mm` is `not_applicable` and
`travel` counts only its Z. Each finding retains `guided_sweep_debts` and a
sentence of the form `op {n} guided sweep: … check: …`. An established error
still wins; otherwise the result stays `?`. CLEARANCE prints each headroom
debt as `? Not proven over the sweep — …` beside the setup-pose checks.
The feature lineage and remaining motion boundary are recorded in
[issue #255](https://github.com/pedropaulovc/prechips/issues/255) and
[issue #272](https://github.com/pedropaulovc/prechips/issues/272).

A trammel owes the same two checks, labelled
`op {n} guided sweep (trammel): …`. Its debt quotes pose-derived values:
work/pin X/Y sweep about the spindle axis, pin travel along the rails, carrier
turn and carriage proximity to the spindle axis. Table extents and column
geometry are not modelled, so both results stay `?`. See the trammel lineage
in [issue #269](https://github.com/pedropaulovc/prechips/issues/269) and the
[trammel operator sequence](rules-coordinates.md#trammel-operator-sequence).
Declaring a dry-pass instruction does not make this modelled-motion debt pass.

### Lathe swing and length

For a lathe, the necessary comparisons are:

- Stock OD and chuck `body_dia` against `envelope.swing_over_bed`.
- Stock OD against `envelope.swing_over_cross_slide`.
- `hold.stickout_mm + body_length` against `envelope.between_centres`.

If stick-out is not numeric, the declared stock length
`stock_state.north_end_z - south_end_z`, converted from manifest units, is
used. All three machine limits need their own accepted measurements.
Missing or unverified inputs stay unknown; established overruns are errors.
Evidence includes stock OD/length, stick-out, chuck body diameter/length,
limits, required length and measurement debt.

This is a necessary-condition screen only. It checks no tool path, carriage
stroke or tailstock quill extension. It adds no mill-table or fictitious
toolpost-gauge requirement.

### Findings and remedy

The standard sentences include:

- `{setup}: lathe swing, chuck body or between-centres length remains unmeasured or unresolved.`
- `{setup}: stock and chuck fit the measured swing and between-centres length.`
- `{setup}: headroom, travel or jaw-path geometry remains unmeasured or unresolved.`
- `{setup}: measured spindle stack and setup-entry stock travels fit.`
- `{setup}: {violations}.`, with clauses such as
  `supported stock height is not positive`,
  `op {n} exceeds spindle clearance by {overrun:g} mm`,
  `cutter-centre span exceeds {X|Y} travel`,
  `stock OD exceeds the swing over the bed`,
  `chuck body diameter exceeds the swing over the bed`,
  `stock OD exceeds the swing over the cross slide`, or
  `stick-out plus chuck body exceeds the distance between centres`.

Resolve the named stock placement, selected assembly dimensions, measured
machine limit or authored cutter extent. Use a process with sufficient
clearance when a verified overrun is established. A positive nominal margin
does not resolve an unmodelled jaw path or guided motion.

Evidence includes per-operation stacks, projection, OAL, gauge length,
margin/verification, `stock_height_mm`, stock/support dimensions, maximum
full stack, jaw obstruction, stock extents and per-axis `travel_checks`.
Citations include PLAN §4.1 headroom, consumed inventory dimensions and the
plan stock-state/setup frame. Raw rail height is not a coordinate; fixture
height is not silently treated as bed height.
Implementation: [`headroom.py`](../src/prechips/rules/headroom.py).

## M5 measured inventory screens

`envelope` and `travel` each produce a setup finding. Neither is in the
no-policy-file fallback's required-rule list. A shop can require them with
`envelope = "*"` and `travel = "*"` under `[required]`. An applicable unknown
from either screen forces exit 4 only when that screen is required; these
are not automatic M5 approval gates. Errors exit 2 whether required or not.
Other required findings can still prevent exit 0. See [policy](policy.md)
for the complete requiredness and exit contract.

These declared-input rules do not invoke FreeCAD or certify collisions.
Lathe setups are `not_applicable` to both. Setups with no nonmanual,
nonsaw cutting assembly also have no applicable stack/travel calculation,
including the [manual-bench work described above](#manual-bench-and-saw-scope).
Dedicated all-saw setups are exempt; manual inspection/deburring does not
remove that exemption. In mixed setups, the other mill cuts retain their
checks. Holding and native `saw_cut` stock preservation remain required by
their own rules.

There is no separate `holder_stack` rule. Selected-holder gauge debt belongs
to `envelope` or `travel` where consumed; lathe cuts are not asked for a
fictitious toolpost gauge length.

### `envelope`: spindle position between table limits

Inputs are stock and setup stock-state/frame, fixture bed height,
parallels/supports, selected holder gauge, tool/holder projection, authored
`approach_mm`, commanded operation Z bands and measured spindle-to-table
minimum/maximum. An already successful kernel bbox can contribute existing
geometry; a STEP filename or digest never starts a kernel.

For each individual operation, the stack at stock top is:

`fixture bed height + parallels/supports + physical stock height + mounted holder gauge + tool projection`

A vise contributes measured `bed_height`, never jaw height. Jaw obstruction
belongs to `headroom`. To check the maximum, the rule raises the spindle nose
by the operation's highest commanded Z above stock top, at least its authored
`approach_mm`. To check the minimum, it lowers the nose to the deepest floor
(`to_z`, `depth_mm`, drill tip/exit). Both ends must fit; equality passes. A
negative measured stack dimension is an error. The rule never combines one
operation's longest tool with another operation's longest holder.

An unknown Z band, missing authored approach or unknown target remains
unknown, not zero clearance. Approach is authored plan debt, not a shop
measurement. Missing geometry gets one authoring instruction. An unresolved
tool, fixture or support asks you to add or resolve the owned identity,
not measure an unowned item's height, point angle or reamer lead.

An existing successful `bundle.kernel.bbox_mm` is transformed from model to
setup axes; otherwise authored stock or complete feature extents are used.
On every path, authored setup `stock_state` height overrides finished-model
Z because the received blank occupies the fixture.

Findings name the operation and limit, for example
`S1: op 10 … exceeds spindle-to-table maximum … mm by … mm.` An unresolved
example is `? S1: spindle envelope remains unmeasured or unresolved — ? M1`,
linked to the named input and full action in the setup STOP box. Correct the
stock/assembly placement or authored Z band, then measure the exact consumed
limits and dimensions.
Implementation: [`envelope.py`](../src/prechips/rules/envelope.py).

### `travel`: required table and spindle stroke

The rule unions positioned operation extents. It does not take only the
largest individual width: separated holes need the distance between centres.
A child counterbore or other point feature without `at` inherits its named
`parent` or `hole` location in that parent's frame, but inherits no bounds or
dimensions. Explicit child `at` wins, including explicit `"unknown"`; absent
parent/location facts stay unknown.

For X/Y:

- Point/hole actions (`spot`, `drill`, `ream`, `tap`, `counterbore`, `center`)
  use centres without cutter-radius padding because the spindle sits on
  the hole.
- Outside-profile extents include selected cutter radius. Face/pocket
  extents remain as authored.
- A rough stage pads each side by the stock it leaves. An explicit
  `rough_*` operation uses `rough_allowance_mm`, else `stock_to_leave_mm`.
  A contour finish uses the `rough_allowance_mm` of the rough stage printed
  with it by `coordinates`; a finish without a contour cuts at the line.
  Unknown required leave is debt. Negative leave on any operation is an
  error because it cuts into the finished part.
- When the sheet prints cutter-centre X/Y, that path replaces declared
  extents, including approach and exit. This covers arc rows, join lines,
  linear-table outlines and face raster passes (`printed_xy_bounds_mm`).
  Its cutter diameter must be a verified measurement to complete the axis;
  otherwise the path is only a lower bound with diameter `measure:` debt.

A broad face/profile/pocket without complete extents uses conservative
setup-entry stock span without inventing stock origin. It uses the same
entry stock as `headroom`: kernel entry box, else raw blank placed by its own
`axis`/`section_axis`. Routed stock without an entry box is unknown, never
replaced by the raw blank. Stock span is a lower bound because approach and
exit past the stock are undeclared. The axis stays unknown with an `author:`
debt naming the operation's `feature.bounds`; an exceeded lower bound still
errors. Each X/Y check records its `basis` as `cutter-centre path`,
`declared cut extent`, both, or `stock span`.

Z is the union of spindle-nose positions:

`tip + holder gauge + tool projection`

It is not just cutter-tip span. A long facing tool and short pocketing tool
may require the stroke between their nose extremes. Any operation's
unmeasured gauge or projection leaves the result unknown. `approach_mm` is
an authored nonnegative safe Z approach distance; omission stays unresolved.
Tip Z uses commanded targets and advanced-stock-state hole endpoints,
including drill point and exit allowance, not finished hole depth alone.

The manifest must explicitly declare millimetres. Unknown or inch
feature/frame coordinates are not silently read as mm or converted into a
travel pass; author a correctly unit-bound millimetre manifest instead.
An overrun uses the template
`{setup}: declared X operation span {N} mm exceeds measured travel {T} mm by {M} mm.`
For an exceeded lower bound, it prints
`{setup}: declared X operation span at least {N} mm exceeds measured travel {T} mm by {M} mm.`
The same forms name Y or Z for those axes. Unknown findings name usable axis
travel, feature extent, selected holder/tool length or safe approach to resolve.
Implementation: [`travel.py`](../src/prechips/rules/travel.py).

### Measurement trust and resolving debt

Both rules cite the consumed fields and retain nominal vendor numbers as
evidence only. Missing values stay `"unknown"`. Limits, fixture heights,
holder gauge/grip, tool OAL/projection and cutter geometry require a complete
fact-local `measured = { status = "measured", by, date, instrument }` record.
None of these substitutes establishes a measured pass or overrun:

- `verify = true`.
- A block-level or root measurement record.
- A source flag or citation alone.
- Status `assumed`, `illustrative` or omitted.

The finding remains `?`, naming the status and `by`. A known verified
violation still stops when other measurements are unknown.

Applicable unresolved findings carry concrete `measure:` instructions keyed
to the exact consumed fact, including a set member or tool/holder pair.
Fixture instructions use only dimensions consumed for that fixture kind;
a riser is not asked for vise jaw height. A missing holder identity calls for
adding or resolving the holder, not measuring an unowned item. Absent derived
geometry remains unresolved without inventing a shop measurement for a
stock box.

The sheet prints each full instruction once in the setup STOP box and uses
short numbered references elsewhere. Record the measured values in their
source inputs and re-issue the sheet. `numbers.measurements` contains these
entries. [`tools --measure`](reference/cli.md) lists current plans' debt,
sorted and deduplicated by id, without starting a kernel. See the
[troubleshooting guide](manual/troubleshooting.md) for unresolved input and
measurement findings.

## `datum_consistency`

The rule produces one finding per drawing feature. It maps drawing datum
names to actual finishing cuts, never to setup-frame labels. A nominal frame
or pickup of an earlier pilot cannot establish a later finished drawing datum.

### Cuts and datum relationships

A feature's cuts include operations naming it and operations that own it by
complete explicit-face ownership: a known, nonempty operation `faces` list
contains all the feature's known, nonempty declared faces. A finish profile
can therefore own an exported tip land through its end joins. See
[plan operations](plan.md#operation).

Reaming, boring or tapping replaces pilot drilling in the finishing-cut set,
including across merged feature labels and face owners. Rough work, manual
`inspect`, `deburr`, `coating`, `release`, `fit` and `scribe`, plus
nonfinishing `spot`, `transfer` and saw operations do not establish final
datums. A bench `file_to_line` does. A datum name mapping to no feature has
no cuts; it never borrows every operation.

Relationships include position datums, angularity datums, surface-profile
datums, a coaxial feature and a `height_from` feature. Each
`surface_profile_datums` datum is compared at zone t in mm. Manifest
`units = "in"` converts by × 25.4; unknown units leave that value unknown.
A datum-free profile controls form only and relates no datum. A profile zone
with datum declarations omitted is unknown. Its evidence includes
`surface_profile_datums`.

For height-from relationships, tolerance is the high-minus-low span of the
first declared band among `height_above_pivot`, `height` and `separation`.
Without one it is unknown. A BASIC height governed by a surface profile uses
the zone-derived band described in [surface profiles](features.md#surface-profiles),
with the corresponding conversion to mm; unresolved derivation stays unknown.

### Pairwise verdict

Every feature finishing-cut/datum-cut pair is evaluated:

1. Cuts in the same setup pass.
2. An indicated transfer passes only if it names the feature/datum and its
   source is at or after the datum finishing setup and before the current
   feature setup.
3. Otherwise tolerance is compared with the measured `refixture_budget_mm`.
   Tolerance below the budget is an error. Unknown/unverified budget,
   tolerance or unresolved cuts leave the comparison unknown.

A known budget carries its policy citation. A feature with no related datum
and resolved relationship declarations is `not_applicable`. Resolve the
actual finishing operations, transfer source/indicated datum or shop budget
named in the finding. Merely renaming a setup frame does not repair a datum
relationship.

Exact sentences are:

- `No tolerance on this feature refers to another datum.`
- `Re-fixtured datum tolerance is below the measured shop budget: {sorted unique datum names}.`
- `Datum cuts or the re-fixture acceptance budget remain unresolved.`
- `Datum relationships share a setup, have an indicated transfer, or fit the measured shop re-fixture budget.`

Evidence contains feature/datum operation ids, every pair's same-setup and
indicated-transfer flags/status, tolerance, budget and transfer record.
Citations include PLAN §4.1, manifest datum/tolerance references, finishing
cuts, transfers and shop-budget citation.
Implementation: [`datum_consistency.py`](../src/prechips/rules/datum_consistency.py).

## `consistency`

The rule checks agreement between structured facts and the limited free-text
forms it recognizes. A fact printed from plan fields or the kernel has one
source; free text must not restate facts that the rule reserves to that
source. Two output surfaces printing the same fact must agree.

### Sources and subjects

Derived values use these sources:

- TOOLS `T<n>` numbers: `resolution.tool_numbers`, assigned by first use in
  plan order; a lathe pair keeps its number across that machine's setups.
- Clamp tightening: `tighten` / `torque_nm` ([hold fields](plan.md#hold)).
- DRO ZERO kept clamping: `zero.transfer.keep_clamped`.
- Jaw tops and HOLD `work top above jaw tops mm`: `resolution.jaw_top_z`,
  using the seated bottom (`retained_rail_bottom_z` when lower) plus
  `jaw_above_parallels_mm`, from the kernel's accepted vise inputs.
- SHOP-MADE FIXTURE Size mm: the solid at the make decimals.
- Operation cut clearance beside the holding: kernel `cut_clearances`.

There is one setup subject for hold/clamp notes, setup and stock notes,
zero text, stock heights, make notes in the sheet's SHOP-MADE FIXTURE tables
and the picture's cut. The rule examines operation `note`, `inspection_note`,
`layout` and `inspection_methods`, but emits a `{setup}:{op}` subject only
when a check recognizes a claim, contradiction or unresolved comparison.
Text that matches none of the checks produces no operation finding, not an
operation-level `not_applicable` row.

The patterns below define the entire recognized text coverage. Other wording
makes no checked claim, so it establishes neither an error nor a pass.

### Restated facts

A recognized restatement is an `error` wherever the pattern occurs. Negation,
time, tolerance and subject do not change that result. Leave the fact in its
structured field and let the sheet print it:

- `same chucking` in setup hold, clamp, stock, setup or zero text. HOLD prints
  holding; DRO ZERO prints whether work stays clamped from the transfer's
  setup through `zero.transfer.keep_clamped`.
- `hand tight`, `hand-tighten[ed | ing]`, `tighten[ed | ing] by hand` or
  `finger tight` in a `clamp_order` clamp's own note. HOLD prints tightening.
- `N mm` or `N in` `above` or `below the [vise] jaw[s]` or `jaw top[s]` in
  setup/operation text when the hold sets `jaw_above_parallels_mm`. Use Z
  values for other heights because jaw tops are derived.
- A made row's whole size restated in its printed SHOP-MADE FIXTURE make
  note. The Size mm column owns that fact. Only an unambiguous statement in
  the closed grammar below counts.

### Made-size grammar

Make notes are NFKC-normalised, except fraction glyphs and superscript or
subscript digits that NFKC would turn into other digits, and marks it would
erase as angles. Thus `½` stays a fraction, `8²` does not become `82`, and
`º` and `˚` remain angle marks. Other superscripts/subscripts such as `ª`,
`⁺`, `⁽` and `™` fold. Whitespace collapses; `x`, `X`, `×` and `*` become one
separator. Numbers split from units and glued separators, including
`65.2x11x10`, `4mmx8` and `Øunknown`.

  ```text
  statement  = "the" row ["to"] ["Ø"] edge "x" edge ["x" edge] terminator
  edge       = (number | "?" | "unknown") [unit ["."]] [edge word] {parenthesis}
  terminator = the note's end | a word | a mark
  ```

The row name must match its solid name or `label` word for word. The statement
must give every printed edge: three for a box, including a cut-out, or Ø and
length for a cylinder. Each row denoted by the name gets its own finding,
including shared labels/notes and withheld rows (`?`). A size before a later
finishing step is still a restated size; give an allowance over the printed
size, such as `0.01 over`, instead of another whole size.

The grammar accepts these elements:

| Element | Recognition boundary |
| --- | --- |
| Number | Digits. Fractions (`1/2`, `1 / 2`, `½`, `1⁄2`) and ranges (`8-10`, `8–10`, `8 - 10`) are not numbers. |
| Unit | `mm`, `in`, `inch`, `inches`, `"`, `″`, `'` or `′`; a point such as `mm.` is accepted when the size continues after it. |
| Edge word | `wide`, `high`, `thick`, `long` or `deep`. |
| Parenthesis | A closed parenthesis consumes through its `)`, whatever it contains, as in `4 (rough; finish later) x 8`. An unclosed one ends at its own `;`. |
| Terminator | Note end, word or mark, excluding a number, fraction, range, name (`M6`), `x`, unit, or a comma/point glued to a digit (`8,5`). |

The governing text is the statement's clause. Clauses split at `,`, `:`, `;`,
`!`, and a full stop before a capital or note end, never inside a closed
parenthesis. If the clause has no verb before `the <row>`, as in
`Drill, with care, the stud …`, the whole sentence governs it.

A statement is ambiguous and unread when its governing text contains any of
these, anywhere:

- A feature verb: `drill`, `bore`, `ream`, `tap`, `counterbore`,
  `countersink`, `spot`, `spotface`, `chamfer`, `bevel`, `thread`, `knurl`,
  `groove`, `slot`, `pocket`, `notch`, `recess` or `undercut`. Inflections and
  `c'bore` / `csk` count. Hyphenated compounds are read split (`spot-drill`)
  and joined (`counter-sink`). A word directly before a tool/stock noun,
  with or without a hyphen (`drill rod`, `drill-rod`, `boring bar`,
  `tap wrench`), names that tool/stock and is not a verb.
- An angle unit: `°`, `º`, `˚`, `deg`, `degs`, `degree` or `degrees`.
- A fraction or a glyph kept by normalisation, such as `¹/₂` or `8²`.

The row's own name is excluded from governing text, so rows named `thread`
or `slot` can still be read by name.

### Compared facts

Recognized comparisons are errors only when they disagree with the source:

- A `T<n>` word must name a TOOLS row in that setup. Tokens inside a name
  such as `6061-T6`, before a decimal point or hyphen, or naming a plan frame
  are excluded.
- A digit flute count, any integer, bound to exactly one tool number must
  match inventory `flutes`. Recognized forms include `2-flute T1`,
  `T1 (2-flute …)` and `T1, the 2fl …`.
- Inspection text for an operation checked by a GO / NO-GO pair must not
  send the NO-GO through in an un-negated recognized clause.

For the plug check, sentences split at `;`, `!`, `?` and full stops, excluding
decimal points; clauses also split at `,` and `:`. Parenthesised text is
dropped. A clause is negated by `not`, `never`, `no` (except `NO-GO`),
`cannot`, `without`, `unlike`, `instead` or `-n't`. The recognized instruction
starts with `push`, `pass`, `run` or `slide`, optionally after `and`, `then`,
`now`, `next`, `finally`, `so` or `but`. It sends one of these through:
`the NO-GO [plug]`, `the GO and NO-GO plugs`, `each`, `every`, `both` or
`all [the] plug(s)`, or `the plugs`.

### Structured and picture comparisons

Three checks do not require prose:

1. A `tighten = "hand"` clamp must not also declare `torque_nm`.
2. The picture's `CUT <mm> mm FROM <holder> (OP <op>)`, from kernel
   `closest_cut`, must agree with that named operation's CLEARANCE row and
   holding solid from `cut_clearances`. Each surface uses its own rounding
   at the setup's DRO decimals. Another operation with the same value does
   not substitute. A missing/uncomputed named row, or a picture with
   unknown/empty/absent operation identity, leaves the comparison unknown.
   Uncomputed `cut_clearances` with no `closest_cut` also leave an unknown
   naming those operations. A saw blade path has no such row and restates
   none.
3. `stock_state` heights are compared with kernel setup-entry stock beyond
   its 0.001 mm stock tolerance. Each declaration is judged by its named
   evidence source; a different source cannot replace it.

The stock-height cases are:

- A `top_z` with a named `top_feature`, or `bottom_z` with a named
  `bottom_feature`, uses that feature's +Z or -Z face alone. Kernel
  `setups.<id>.stock_faces_mm` gives the finished face Z and the entry
  stock's highest point over its footprint, or lowest below it. While stock
  stands over the face, the declaration must use that stock height.
- Once cut, a named face can depart from CAD Z only within its feature band.
  The band counts only when the feature has one `[low, high]` requirement
  with a `_nominal`, and the kernel places its +Z and -Z faces that nominal
  apart. A thicker feature moves the face outward while the opposite face
  stays at CAD Z. If both faces are cut, `top_z - bottom_z` must lie in the
  band and each face may move by no more than the band's span.
- Without a named face, the box supplies only highest/lowest stock points.
  `top_z` is the highest point. Under `top_feature = "unknown"`, it is proved
  wrong only when above the whole stock.
- The lower of unnamed `bottom_z` and `retained_rail_bottom_z` is the lowest
  point. That lower value, or both if tied, is wrong whenever it differs
  from box bottom. A named seat does not exempt a rail from comparison.
- A named seat proves only its face. If it is the lowest authored point but
  the kernel measures stock below that face and above box bottom, unauthored
  stock hangs below it and the declaration is wrong. If the face is box
  bottom, only the face verdict judges the seat, including displacement
  permitted by its band.
- A rail without `bottom_z` is proved wrong only below box bottom, because
  the seat may be the stock's lowest point.

### Unknown comparisons

A recognized fact that cannot be proved is `unknown`, never `pass`. Cases
include:

- A `T<n>` beyond the current TOOLS table while an operation still has no
  chosen tool, or a flute count whose inventory tool has no `flutes`.
- A picture cut matching no computed row of its holder while another
  operation's row is uncomputed and could be its source.
- Unknown authored stock height, unknown plan units or no kernel stock box.
- `top_z` below box top under `top_feature = "unknown"`.
- A named top/bottom face not measured by the kernel, regardless of the box:
  no horizontal face on that side, finished material beyond it, or an entry
  stock that does not carry it.
- A cut named face off CAD Z without a band proved to describe its face
  separation.
- An unnamed `bottom_z` or rail above the lowest authored point.
- A rail without `bottom_z` that is not below box bottom.

An unknown rail, negative/nonnumeric jaw height, or
`jaw_above_parallels_mm_verify` other than `false` leaves jaw tops unknown.
So do parallels other than `"none"` / `"not_applicable"` that do not resolve,
are uncertain or lack accepted positive `height`. These are also the inputs
that leave the kernel's vise unplaced. HOLD prints
`work top above jaw tops mm` as `?`.

### Coverage limits and remedy

These forms are not read and therefore never produce an error through the
corresponding text check:

- Other kept-chucking wording: `do not loosen the jaws`, `never loosen it`,
  `without loosening`, `stays clamped`, `same chuck`; or `same chucking` in
  operation text.
- Other hand-tightening wording, tightening in hold text instead of the
  clamp's own note, or notes for clamps outside `clamp_order`.
- Torque restated in prose.
- Other jaw-height wording (`within 18 mm of the jaw tops`, `proud of the jaws`),
  or any such text in a hold without `jaw_above_parallels_mm`.
- Flute counts in words (`four-flute`) or not bound to one tool number.
- Other plug-through wording (`gently push …`, `the NO-GO goes through`).
- Make-note sizes outside the grammar: unnamed rows (`sawn and milled to
  11 x 10 x 65.2`, `turned Ø16 x 9.05`, `drill Ø4 x 8 deep in the stud`);
  part of a solid (`the thread portion Ø4.80 x 7.2`, `the arm's nose`);
  incomplete edges (`the arm to 11 x 10`); a hole's Ø; fractions, ranges,
  words or another separator (`✕`); unclosed/bracket annotations
  (`4 [rough] x 8`, `4 (rough; x 8`); bought/existing part notes.
- Ambiguous governing text, including a feature verb, angle unit, fraction
  or kept glyph before/after the size or inside parentheses. Examples are
  `drill and tap the stud to Ø4 x 8 deep`, `Drill (use the mill) the stud …`,
  `turn the stud to Ø4 x 8 and drill it`, `0.5 x 45 (nominal) (deg)`,
  `from ½ in rod`, `from ¹/₂ in rod` and `4 x 8 mm²`. A clause with no verb
  of its own uses its sentence's verb. Instructions joined by `then` or a
  full stop before a lower-case word remain one clause; a feature verb in
  either leaves the other unread.
- Shop-made positions, fits and fasteners restated in text.
- Picture labels other than the cut: contact coordinates, stock size, jaw/Z
  labels; the picture holder name against CLEARANCE; clearance restated in
  operation text.

Do not reword a contradiction to evade recognition. Correct the field, text
or engine output that disagrees, and leave derived facts with their source.
A setup subject with no recognized claims is `not_applicable`; unread
operation text produces no operation subject. A recognized, comparable claim
that agrees can pass, but unread prose has not been checked. Evidence records
`claims`, `contradictions` and `unchecked`.
Implementation: [`consistency.py`](../src/prechips/rules/consistency.py).

## M2 declared workholding and indexing

The [lathe rules](rules-lathe.md) implement partial feasibility checks:
turned profile from the actual chuck end, supported stick-out using the
smallest finished diameter in the unsupported length, and held-stock diameter
against a listed collet set or chuck capacity. The bar in the jaws is not
the stick-out D, and chuck outside diameter is not grip capacity. Unknown
exposed geometry, inventory and policy values remain `?`. These checks do
not establish complete toolpath clearance, whip or chatter behavior.

The [indexing rule](rules-indexing.md) considers direct steps and every
authored worm-plate circle, preferring exact arithmetic before nearest
alternatives. Every declared position must meet its sourced angular tolerance.
Closure against a whole revolution applies only to a full pattern:
`positions >= 2` with `angle_deg` omitted, deriving the exact step as
`360 / positions`. Explicit `angle_deg` with `positions >= 2` is an open
pattern: each position is checked against `angle_tol_deg`, without closure.
`positions = 1` is one setting, such as the cone journal's 12.5182° inclination,
also without closure.

The sheet prints plate, circle, turns and hole spaces, then the actual angle,
its difference from the planned angle and its allowance. Tentative arithmetic
remains visible when inventory confirmation is missing; it does not resolve
that debt or constitute physical acceptance.
