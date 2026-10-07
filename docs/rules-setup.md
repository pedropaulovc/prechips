# Holding, headroom and datum rules

These are declared-field and nominal-arithmetic checks, not measured workholding
certification or kernel collision proofs; the kernel-measured vise and thin-wall
rules are in [geometry rules](rules-geometry.md). Unknown measurement debt stays visible.

## `hold_fields`

One subject per setup. Requires fixture, stop, grip, clamp, coolant, deburr,
and holders for nonmanual machining ops (saw cut-off needs none). A vise/nonlathe
setup needs fixed-jaw declaration
unless explicitly not applicable. Lathe setups need OD, support, grip-on and a
known end station; mill setups need top/bottom Z. Authored supports, orientation,
parallels, jaws direction and locator are checked when supplied. Every nonmanual
cut needs `direction` (face, profile, pocket, turn, form and parting actions
included) except point/hole actions (`spot`, `drill`, `ream`, `tap`,
`counterbore`, `center`, `center_drill`) and saw cut-off (its `cut_plane` defines the setting);
an explicitly supplied point/hole direction is also checked, and
an explicitly unknown action without one is unknown. Missing/empty
fields are errors; explicit unknown values are unknown. It does not compare
all holding dimensions or certify the fixture was physically installed.

A declared `hold.stop_face` must be on the stock the setup receives:
`"stock_end"`, a raw-stock `as_is_faces` face, or a feature a cutting op in an
earlier setup of the setup's stock lineage made. A face first cut by this setup
or a later one is an error naming that op
(`{setup}: the hold stops on {face}, which the arriving stock does not have yet; it is first cut in {setup} op {op}.`);
an earlier cut of unknown action or unsettled as-is faces is unknown.

A mill setup (machine kind `mill`) whose fixture is a `vise` or `angle_plate` needs
`hold.align` where it mounts or turns that fixture: the first such setup on its
machine, or one whose fixture, vise `jaws_along` or plate `pose` differs from the
setup before it on that machine (a setup on another fixture between them took the vise
or plate off). Its `indicator` must be an inventory gauge of kind
`dial_test_indicator` or `dial_indicator`, `limit_mm` and `over_mm` must be
positive, and an angle plate's `face` must name one of the plate's solids; a missing
block or invalid value (a gauge not in the inventory, declared absent or of another
kind) is an error, an explicit unknown is unknown. So is `align = "unknown"` (each
member unknown) and an indicator whose kind, presence or verification is not
established (`kind = "unknown"`, `present = "unknown"`, `verify = true`); the
indicator is a selected inventory reference, so `tool_resolves` checks its identity
like any tool or fixture. The face runs
along the vise's `jaws_along`, or for an angle plate along the longer horizontal
side of the `face` box solid, carried into the setup frame by `pose`; a run that is
not X or Y is unknown (`hold.align.travel`). Evidence: `align_due` (`mounted`,
`jaws turned`, `plate moved` or `not_applicable`). The HOLD prints the squaring step
after the
mount line: sweep the named indicator along the fixed jaw or locating face over
`over_mm` of that travel and hold the reading change to `limit_mm`; any part not
established prints as a STOP.

Templates:

- `{setup}: holding declarations need {comma-separated missing/unknown fields}.`
- `{setup}: holding and cutting decisions are declared; this does not approve measured fixture clearance.`

Evidence: hold record, stock stations, coolant, deburr, cut directions and
missing fields. Citation: PLAN §4.1 hold fields. No invented grip or deburr
limit appears as a fallback.

## `centre_support`

One subject per setup. Always required wherever a centre carries the work: no
shop-policy entry is needed and none can waive it (`findings.ALWAYS_REQUIRED`,
like `joint_fit`/`joint_assembly`). A centre is a `support` or any `supports`
entry whose inventory `kind` has a whole `centre` / `center` word (`dead_centre`,
`live_center`, `tailstock_centre`, `pipe_center`) or is `tailstock` (a
tailstock carries work only on its centre), a machine standard accessory whose
name has such a word (`dead_centre_headstock`), or a hold that declares
`centre_hole` / `centre_hole_dia_mm`. The word `tailstock` in an accessory name
is not a centre (`tailstock_drill_chuck`, `tailstock_quill`), nor is a kind
such as `self_centering_steady_rest`. A support of a known non-centre kind stays
one whatever `verify` or measurement debt its record carries; that debt is its
own checks' (`stickout`, `turning_deflection`). A hold with no centre is not
applicable and never blocks.
The hold's `centre_hole` must name a plan
[process feature](plan.md#process-features) `centre_hole`; a `center_drill`
op of an earlier setup in this setup's `stock_in` lineage must drill it, that
op's own [`blind_depth`](rules-operations.md#blind_depth-tip-endpoints) centre
row must pass (the same verdict, so the two never disagree: the selected tool's
own centre, every tool fact the kernel cuts it from accepted, its mouth on the
touched entry surface and, on a lathe, on the spindle axis), and its
`mouth_dia_mm` must equal `centre_hole_dia_mm`.

- **error:** the lineage is fully declared and no earlier setup in it drills
  the centre (none does, or only this setup or a later one does), the maker's
  `blind_depth` row is an error (a centre size its selected tool does not cut,
  a tool point no shorter than its pilot, or a mouth off the surface or axis
  its quill is touched on and fed along), or the hold's seat and the drilled
  mouth differ. An error stands whatever else is unresolved;
- **unknown:** `centre_hole` is undeclared; any setup in the lineage (this one
  or one upstream) lacks `stock_in`; the maker's `blind_depth` row is unknown (a
  centre size, a selected-tool fact such as its point angle, the tool's record
  being unconfirmed, or the touched entry surface); the seat or mouth diameter
  is unknown; a support's identity is unresolved (the reference is unknown, not
  in the inventory, declared `"unknown"`, or of unknown kind), with or without a
  known centre beside it, since it may be one; or
  the work rides on more than one centre, since a hold names one `centre_hole`
  and each other centre's seat is unchecked. A wholly undeclared hold names no
  support: its debt is `hold_fields`', and this rule is not applicable;
- **pass:** otherwise, naming the setup and op that drilled it.

Evidence: support, the centres found, the centre, the ops that drill it before
and after, whether the lineage is routed, each maker's preparation status,
mouth and seat diameters, and the Table 6 depth arithmetic (`drill_length_mm`,
`countersink_depth_mm`, `depth_mm`). The kernel separately seats the centre in
the cut countersink and checks it against the setup-entry stock; that check is
a fixture render debt, not this rule. Its unknown blocks (exit 4) under any
shop policy; an error always exits 2.

## `prepared_blank`

One subject, `stock.prepared`; not applicable without a
[`[stock.prepared]`](plan.md#prepared-blank), and `unknown` when it is declared
`"unknown"` (a blank is prepared, and nothing says which). The receiving setup's
box is first the root stock box trimmed, plane by plane, by every plan process
`end_face` made by an op in an earlier setup of its `stock_in` lineage
(analytic). Each declared size (section 0, section 1, length) must lie within
its ± `tolerance_mm` of that box, at the declared `origin_mm`.

The planes say only where the route means to face. What its generated passes cut
is the kernel's stock handed on by the receiving setup's `stock_in` setup
(`stock_out_bbox_mm`, `stock_out_volume_mm3`): read along the blank's axes, that
box must lie within the same bands, and the stock must fill it (relative 1e-6), so a
shallow, partial or missed face (its slab stays) or a pass cut inside the blank is an
error. Without that stock (no kernel, or its stock unknown) the blank is unknown; a
blank taken as supplied (`stock_in = "stock"`) is the root stock itself.

Each blank check resolves too: `length`, `section_0` and `section_1` through the
[inspection](rules-inspection.md) gauge capability against the size ± tolerance
band (`limits_mm`); `flat`, `square` and `parallel` need a dial indicator, dial
test indicator, height gauge or CMM from inventory, a written `methods`
procedure, a positive `form_mm` limit and a verified gauge resolution no coarser
than that limit. The worse of the cut and the checks stands.

- **error:** a blank face is made outside the receiving setup's lineage or after
  it, a received or cut size is outside its band, the cut stock does not fill its
  box, a check's gauge is missing from inventory or cannot measure the band, or a
  form gauge's resolution is coarser than its limit;
- **unknown:** the blank is declared `"unknown"`, a lineage setup lacks `stock_in`,
  a size, origin, tolerance or root-stock fact is unknown, the kernel's cut stock
  is unknown, or a check, method, form limit or gauge resolution is undeclared or
  unverified;
- **pass:** otherwise, naming the ops that made each face.

Evidence: received, declared and cut boxes, the cut volume, the received sizes, the
ops that made each face, faces made outside the lineage, and one `checks` row per
check (a form row with its `limit_mm` and `resolution_mm`). A process face never
earns drawing coverage, so the blank is checked here, not by a drawing requirement.
Its unknown blocks (exit 4) like every always-required rule; an error exits 2.

## `headroom`

One subject per setup. Mill stack in mm is
`fixture bed + parallels + support blocks + physical stock height + tool
projection + holder gauge length + 25 mm insertion`. Physical stock height
(`stock_height_mm`) is `top_z - retained_rail_bottom_z` if authored, otherwise
`top_z - bottom_z`.
Projection is the selected tool's `projection_mm` entry for the selected holder,
or `tool OAL - holder grip` when both are known.
The 25 mm insertion allowance is from PLAN §4.1, not holder grip. Support-block
orientation must explicitly identify a listed height; do not pick an arbitrary
block dimension. Per-op margin is `spindle_to_table_max - stack`. The
spindle-to-table maximum and X/Y travel are read from the machine's
`envelope` block, the same facts `envelope`/`travel` read, with the same
fact-local trust: a limit without its own `measured` record (a vendor nominal
with `verify = true`, say) is evidence in `numbers`, adds a
`numbers.measurements` entry and keeps the row `?`. There is no top-level
`spindle_to_table_max_in`/`travel_in` copy to fall back on.

For a `dividing_head`, the work top above the table is the head's declared
centre height plus `stock_state.top_z - hold.pose.origin_mm[2]`, plus any declared
parallel/support lift: the pose origin locates the chuck axis in setup
coordinates. Headroom adds the installed tool projection, holder gauge and
25 mm insertion allowance to this work top,
instead of treating the head's bed/body height plus full stock height as a
vise stack. Translating stock and axis Z together leaves the result unchanged.
Missing centre/axis facts or verification debt remain unknown; tilting the
declared head axis does not by itself replace a known axis-origin Z with debt.
The report/traveler expose centre height, axis Z and work-top height separately.

Jaw height is not a stack layer: `jaw_top_z = bottom + jaw_height -
(parallels + supports)`; cut clearance is `to_z - jaw_top_z`. A below-jaw cut is
clear of the jaws only when its cutter (printed cutter-centre path, else
`stock_removal_bounds`, widened by the cutter radius) stays more than 3 mm
inside both jaw faces along the clamp axis, or more than 3 mm beyond the jaws'
ends along the axis they run (the declared `jaw_center_along_mm` ± half the
vise's accepted `jaw_width`: a blank end overhanging the vise). Other below-jaw
cuts require geometric path checks and therefore remain unknown rather than
being invented collision errors. Travel uses transformed stock box extents
(`stock_extent_x_mm`/`stock_extent_y_mm`)
`sum(abs(setup_axis[i])*stock_extent[i])`, and per axis `travel_checks` requires
`max(stock_extent, fixture_extent) <= machine_travel`; no separate radial tip
envelope is computed. Inch inventory lengths
convert explicitly by 25.4; no STEP bbox is extracted. Unverified dimensions
cannot establish a verified stack/travel pass or measured clearance violation.

For a lathe, `headroom` instead compares stock OD and chuck `body_dia` with
`envelope.swing_over_bed`, stock OD with `envelope.swing_over_cross_slide`,
and `hold.stickout_mm + body_length` with `envelope.between_centres`.
When stick-out is not numeric, the declared stock length from
`stock_state.north_end_z - south_end_z` (converted from manifest units) is used.
All three machine limits require their own accepted measurement records;
missing or unverified inputs remain unknown, while established overruns error.
Evidence includes stock OD/length, stick-out, chuck body diameter/length,
the three limits, required length and measurement debt. This is only a
necessary-condition screen: it checks no tool path, carriage stroke or
tailstock quill extension and adds no mill table/toolpost-gauge requirement.

Templates:

- `{setup}: lathe swing, chuck body or between-centres length remains unmeasured or unresolved.`
- `{setup}: stock and chuck fit the measured swing and between-centres length.`
- `{setup}: headroom, travel or jaw-path geometry remains unmeasured or unresolved.`
- `{setup}: measured spindle stack and part/fixture travels fit.`
- `{setup}: {violations}.`, joining `supported stock height is not positive`,
  `op {n} exceeds spindle clearance by {overrun:g} mm`, and
  `part/fixture envelope exceeds {X|Y} travel`.

Evidence: per-op stacks, projection, OAL, gauge length, margin/verification,
`stock_height_mm`, stock/support dimensions, maximum full stack, jaw obstruction,
stock extents and per-axis `travel_checks`. Citations: PLAN §4.1 headroom;
inventory machine/fixture/support/tool/
holder dimensions; plan stock-state/setup frame. Raw rail height is not a
coordinate and fixture height is not silently assumed to be bed height.

## M5 measured inventory screens

The default policy is unchanged. A shop can add `envelope = "*"` and
`travel = "*"` under `[required]`; unmeasured applicable setups then keep exit 4.
Errors remain exit 2 whether required or not. These two declared-input rules do
not invoke FreeCAD or certify collisions. Lathe setups are `not_applicable` to
both. There is no separate `holder_stack` rule: a selected holder's gauge debt
is carried by `envelope` and `travel` where it is actually consumed, and a
lathe operation is never asked for a fictitious toolpost gauge length.

| Rule / subject | Inputs and tier | Sheet sentence |
|---|---|---|
| `envelope` / setup | M5: authored stock and setup stock-state/frame; already-present successful kernel bbox only; fixture bed height plus parallels/supports; measured holder gauge and tool/holder projection; each operation's authored `approach_mm` and commanded Z band; measured spindle-to-table min/max | `S1: op 10 … exceeds spindle-to-table maximum … mm by … mm.` or `? S1: spindle envelope remains unmeasured or unresolved. measure: PM-30MV spindle nose to table at full Z-down, steel rule, mm.` |
| `travel` / setup | M5: transformed operation feature extents/centres or conservative authored stock span; selected cutter radius for profile extents only; commanded tip targets and advanced hole entry/exit; authored `approach_mm`; per-op holder gauge and projection; measured X/Y/Z travel | `S1: … exceeds measured X travel …` or a `?` naming the usable axis travel, feature extent, holder/tool length or safe approach to measure and author. |

Child `counterbore` and other point operations with no `at` inherit the named
`parent` (or `hole`) location in that source frame. An explicit child `at` wins,
including explicit `"unknown"` debt; a missing parent/point stays unknown.
The inheritance changes the cutter centre only, not child bounds/dimensions.

Dedicated all-saw setups (manual inspection/deburring allowed) have no spindle
headroom, envelope or XYZ tool travel, and those rows state `not_applicable`.
In mixed setups saw ops contribute no fictitious holder/spindle stack while
the other machine cuts still receive their normal checks. Holding and the
native `saw_cut` stock-preservation check are not exempted.

`envelope` stacks, for each **individual** operation,
`fixture bed height + parallels/supports + physical stock height + mounted holder gauge + tool projection`
to place the spindle nose with the tool tip at the stock top. A vise contributes
its measured `bed_height`, never its jaw height: the jaws sit above the bed and
their obstruction of the tool path is `headroom`'s separate jaw check. Against
the measured maximum the rule raises that nose by the operation's highest
commanded Z above the top (the authored `approach_mm` at least); against the
measured minimum it lowers it by the deepest floor the operation reaches
(`to_z`, `depth_mm`, drill tip/exit). The nose must fit between the limits on
both ends; equality passes. An operation whose Z band is unknown (no authored
approach, unknown target) is unknown, not passed at zero clearance. Missing
authored approach is plan-input debt, not a shop measurement. Each missing-geometry
authoring instruction is printed once. Unresolved tools, fixtures and supports
ask to add or resolve an owned identity, not to measure an unowned item's
height, drill point angle or reamer lead. It never combines the longest tool
from one operation with the longest holder from another. An
already successful `bundle.kernel.bbox_mm` is transformed from model to setup
axes; otherwise authored stock or complete feature extents are used. On every
path an authored setup `stock_state` height overrides finished-model Z: the
received blank, not a shorter finished part, occupies the fixture. A STEP
filename or digest does not cause this rule to launch a kernel or invent a bbox.

`travel` unions positioned operation extents, not just their individual maximum
widths: widely separated holes need the distance between their centres. Point
and hole operations (`spot`, `drill`, `ream`, `tap`, `counterbore`, `center`)
are their centres with no cutter-radius padding, because the spindle sits on
the hole; only outside-profile extents carry the selected cutter radius;
face/pocket declared extents are used as authored. A rough stage pads each side
by the stock it leaves: an explicit `rough_*` op by its `rough_allowance_mm`
(else `stock_to_leave_mm`), and a contour finish by the `rough_allowance_mm` of
the rough stage the coordinates rule prints with it; a finish without a contour
cuts at the line. An unknown leave a rough stage needs is debt; a negative leave
on any operation is an error (it would cut into the finished part).
Broad face/profile/pocket operations without complete extents use a
conservative stock-span screen without inventing a stock origin. Z is the
union of each operation's **spindle-nose** positions, `tip + holder gauge +
tool projection`, not the cutter-tip span: a long facing tool and a short
pocketing tool in one setup need the stroke between their nose extremes, and
the row is unknown while any operation's gauge or projection is unmeasured.
`approach_mm` is an explicitly authored nonnegative safe Z approach distance;
missing approach remains unresolved. Tip Z uses commanded targets and the
existing advanced-stock-state hole tip calculation, including drill point/exit
allowance, not merely the finished hole depth.
The manifest must explicitly declare millimetres for this screen. Unknown or
inch feature/frame coordinates are not silently read as mm or converted into a
travel pass; declare a correctly unit-bound millimetre manifest instead.

Each M5 finding cites the input fields and retains nominal vendor numbers only
as evidence. A missing value stays `"unknown"`. Limits, fixture heights, holder
gauge/grip, tool OAL/projection and cutter geometry require a complete
fact-local `measured = { by, date, instrument }`; `verify = true`, a block or
root record, a source flag or a citation cannot establish a pass or a measured
overrun. A known verified axis/stack violation still stops if other
measurements remain unknown. Every unresolved applicable row carries concrete
`measure:` instructions, keyed by the exact fact consumed (set member or
tool/holder pair included); an operation whose holder does not resolve is told
to add or resolve the holder, not to measure an unowned item.
`numbers.measurements` carries those entries; `tools --measure` lists exactly
the entries behind the current reports, sorted and deduplicated by id.

## `datum_consistency`

One subject per feature. Drawing datum names map to actual feature finishing
cuts, not setup-frame labels. A feature's cuts are the ops that name it plus
every op that owns it by complete explicit-face ownership (see
[plan operations](plan.md#operation)): an op whose known, nonempty explicit
`faces` contain all of the feature's known, nonempty declared faces, e.g. a
finish profile whose end joins cut an exported tip land. Relationships include
position and angularity datums, coaxial feature and height-from feature.
Reamed/bored/tapped datum finishing cuts replace pilots, including across that
merged label/owner set; rough, manual (`inspect`, `deburr`, `coating`, `release`,
`fit`, `scribe`) and other nonfinishing actions (`spot`, `transfer`, saw) never
establish a final datum, whether named or owning; a bench `file_to_line` is a
finishing cut and does. A datum name that
maps to no feature has no cuts. Every feature
finishing-cut/datum-cut pair is evaluated. Same setup passes; an indicated
transfer passes only when it names that feature/datum and originates at or
after the datum finishing setup and before the current setup. Otherwise compare
tolerance to measured `refixture_budget_mm`; tolerance below budget is error,
unknown/unverified budget or unresolved cuts are unknown. Height-band tolerance
is high minus low of the band measured from `height_from`: the first of
`height_above_pivot`, `height` or `separation` the feature declares (none =
unknown). Policy citation travels with a known budget.

Exact templates:

- `No tolerance on this feature refers to another datum.`
- `Re-fixtured datum tolerance is below the measured shop budget: {sorted unique datum names}.`
- `Datum cuts or the re-fixture acceptance budget remain unresolved.`
- `Datum relationships share a setup, have an indicated transfer, or fit the measured shop re-fixture budget.`

Evidence: feature/datum operation ids, per-pair same-setup/indicated-transfer
booleans and status, tolerance, budget and transfer record. Citations: PLAN §4.1,
manifest datum/tolerance references, finishing cuts and transfer, plus shop
budget citation. A nominal frame or a pickup of an earlier pilot never proves
a later finished drawing datum.

## `consistency`

One fact, one source. Where the traveler prints a fact from a plan field or the
kernel, the author's free text must leave it to that source, and two surfaces
that print one fact must print one value. A fact that can be
derived is derived: the TOOLS table's `T<n>` numbers come from one function
(`resolution.tool_numbers`: first use in plan order, a lathe pair keeping its
number across that machine's setups), a clamp's tightening from its `tighten` /
`torque_nm` ([plan](plan.md#hold)), the DRO ZERO's kept clamping from
`zero.transfer.keep_clamped`, the jaw tops and HOLD's `work top above jaw tops
mm` from `resolution.jaw_top_z` (the seated bottom, `retained_rail_bottom_z` when
lower, plus `jaw_above_parallels_mm`, from the inputs the kernel accepts for its
vise), a SHOP-MADE FIXTURE row's Size mm from its solid at the make decimals, and
each op's cut beside the holding from the kernel's `cut_clearances`. One subject
per setup (hold, clamp notes, setup and stock notes, zero texts, stock heights,
the make notes of the SHOP-MADE FIXTURE tables its sheet prints, its picture's
cut) and one `{setup}:{op}` subject per op whose text the rule reads (note,
`inspection_note`, `layout`, `inspection_methods`).

The rule reads exactly the token patterns below; any other wording makes no
claim, so it is never an error and never a pass.

**Restated** facts are an `error` wherever the pattern occurs. Negation, time,
tolerance and subject do not matter: the fact has one source, and the text may
only leave it there.

- `same chucking` in a setup's hold, clamp, stock, setup or zero text: the HOLD
  prints the work holding, and the DRO ZERO whether the work stays clamped from
  the transfer's setup (`zero.transfer.keep_clamped`).
- `hand tight`, `hand-tighten[ed | ing]`, `tighten[ed | ing] by hand` or `finger
  tight` in the note of a clamp listed in `clamp_order`: the HOLD prints its
  tightening.
- `N mm` or `N in` `above` or `below the [vise] jaw[s]` or `jaw top[s]`, in the
  setup or op text of a hold that sets `jaw_above_parallels_mm`: the jaw tops are
  derived, so other heights are given as Z values.
- A made row's whole size in a make note it prints with, on a SHOP-MADE FIXTURE
  table (read on the setup whose sheet prints the table): the row's Size mm prints
  it. The note names the row (`the <row>`, by its solid's name or its `label`) and
  gives every edge the row prints: `the <row> to A x B x C` for a box (a cut-out
  too), and `the <row> to D x L` or `the <row> [to] Ø D x L` for a cylinder. An
  edge is a number in digits, `?` or `unknown`, perhaps with a unit (`mm`, `in`,
  `inch`, `inches`, `"`, `″`), then `wide`, `high`, `thick`, `long` or `deep` and
  a parenthesis. The size ends where no further `x` edge, digit or angle (`°`,
  `deg`) follows. Each row the name denotes is its own restatement, rows sharing
  a label or a note included, and a withheld row (`?`) as well. A size before a
  later finishing step is still the row's size, so it is given as an allowance
  over the printed size (`0.01 over`), not as a second size.

**Compared** forms are an `error` when they disagree with the field. A `T<n>` in a
setup's or op's text names that setup's TOOLS row.

- A `T<n>` word (not inside a name such as `6061-T6`, not before a decimal point
  or hyphen, not a plan frame's name) is not in this setup's TOOLS table.
- A flute count in digits (any integer), bound to exactly one tool number as
  `2-flute T1`, `T1 (2-flute …)` or `T1, the 2fl …`, differs from that tool's
  inventory `flutes`.
- On an op checked by a GO / NO-GO pair, an un-negated clause of its inspection
  text sends the NO-GO through. Sentences split at `;`, `!`, `?` and full stops
  (never a decimal point), and clauses at `,` and `:` too. Parenthesised text is
  dropped. "Negated" means `not`, `never`, `no` (not `NO-GO`), `cannot`,
  `without`, `unlike`, `instead` or `-n't` in the clause. The clause starts with
  `push`, `pass`, `run` or `slide` (after `and`, `then`, `now`, `next`, `finally`,
  `so` or `but`) and sends `the NO-GO [plug]`, `the GO and NO-GO plugs`, `each`,
  `every`, `both` or `all [the] plug(s)`, or `the plugs` through.

Three checks need no prose:

- A `tighten = "hand"` clamp also declares `torque_nm`.
- The setup picture's `CUT <mm> mm FROM <holder>` (the kernel's `closest_cut`)
  must be one op's CLEARANCE row beside the same holding solid (the kernel's
  `cut_clearances`), each printed as its own surface rounds it at the setup's
  DRO decimals. A picture cut beside a solid no CLEARANCE row names (a file's or
  a saw's cut, which carries no row, or the other solid of a tie) restates
  nothing.
- `stock_state` heights are checked against the kernel's setup-entry stock,
  beyond its 0.001 mm stock tolerance. Each height is judged by the one evidence
  source its declaration names, and no other source stands in for it.
  - A `top_z` whose `top_feature` names a feature, or a `bottom_z` whose
    `bottom_feature` does, is that feature's +Z (or -Z) face, judged by the
    kernel's height of that face alone. The kernel gives
    (`setups.<id>.stock_faces_mm`) the face's finished Z and the entering stock's
    highest point over its footprint (lowest under it). While stock stands over
    the face, the height must be that stock's. Once the face is cut, the height
    may sit off the face's CAD Z only as far as the feature's band allows. The
    band counts only when the feature has one requirement with a `[low, high]`
    band and a `_nominal`, and the kernel puts its +Z and -Z faces that nominal
    apart. A thicker feature then moves the face outward, the other face held at
    its CAD Z. With both faces of one feature cut, `top_z - bottom_z` must lie in
    the band, and each face may move at most the band's span.
  - Otherwise the box gives only the stock's highest and lowest points. `top_z`
    is the highest point; under an `"unknown"` `top_feature` it is wrong only
    above the whole stock.
  - The lower of an unnamed `bottom_z` and `retained_rail_bottom_z` is the lowest
    point. When both are set, that lower one (both, when they tie) is wrong
    whenever it differs from the box bottom. A named seat never exempts a rail:
    the rail keeps its own comparison.
  - A named seat proves only its own face. When it is the lowest authored point
    and the kernel measures the stock under that face above the box bottom,
    other stock hangs below it that nothing authored reaches, which is wrong.
    When the face is the box bottom, its face verdict alone judges the seat, so
    a displacement its band permits passes.
  - A rail with no `bottom_z` is wrong only below the box bottom, since the seat
    may be the stock's lowest point.

A compared fact that cannot be proved is `unknown`, never `pass`:

- a `T<n>` beyond a TOOLS table that still has an op with no tool chosen;
- a flute count for a tool with no inventory `flutes`;
- a picture cut that no computed CLEARANCE row of its holder prints, while
  another op's row is not computed (that op's cut may be the picture's);
- any authored stock height that is unknown, unknown plan units, or no kernel
  stock box;
- a `top_z` below the box top under an `"unknown"` `top_feature`;
- a `top_z` or `bottom_z` whose named face the kernel did not measure (no
  horizontal face on that side, finished material beyond it, or a face the
  entering stock does not carry), whatever the box shows, stock below it
  included;
- a cut named face off its CAD Z whose feature has no band proved to be its
  faces' separation;
- an unnamed `bottom_z` or a rail above the lowest authored point;
- a rail with no `bottom_z` that is not below the box bottom.

An unknown rail, a jaw height that is negative, not a number or flagged
`jaw_above_parallels_mm_verify` (anything but `false`), or parallels other than
`"none"` / `"not_applicable"` that do not resolve, are uncertain or have no
accepted positive `height` leave the jaw tops unknown, as they leave the kernel's
vise unplaced. HOLD then prints `work top above jaw tops mm` as `?`. A subject the
rule reads nothing in is `not_applicable`. An op
subject is emitted only when its text is read. Evidence: `claims`,
`contradictions` and `unchecked`.

Not covered (never read, so never an error):

- kept chucking in any other wording (`do not loosen the jaws`, `never loosen it`,
  `without loosening`, `stays clamped`, `same chuck`), and `same chucking` in op
  text;
- hand tightening in any other wording, or in hold text rather than a clamp's own
  note, or in the note of a clamp outside `clamp_order`;
- a torque restated in text;
- heights from the jaws in other wording (`within 18 mm of the jaw tops`, `proud
  of the jaws`), or in a hold without `jaw_above_parallels_mm`;
- flute counts in words (`four-flute`), or not bound to one tool number;
- inspection text that sends a plug through in any other wording (`gently push
  …`, `the NO-GO goes through`);
- make-note sizes that do not name the row (`sawn and milled to 11 x 10 x
  65.2`, `turned Ø16 x 9.05`), a part of a solid (`the thread portion Ø4.80 x
  7.2`, a counterbore), only some of a row's edges (`the arm to 11 x 10`), a
  hole's Ø, fractions and hyphen ranges, a bought or existing part's note, and a
  shop-made item's positions, fits and fasteners restated in text;
- picture labels other than the cut (contact coordinates, stock sizes, jaw and
  Z labels), the picture's holder name against the CLEARANCE row's, and a
  clearance restated in op text.

## M2 declared workholding and indexing

The [lathe rules](rules-lathe.md) check a turned profile from the actual chuck
end, supported stick-out using the smallest finished diameter in the unsupported
length, and held-stock diameter against a listed collet set or chuck capacity.
The bar in the jaws is not the stick-out D. A chuck's outside diameter is not
its grip capacity. Unknown exposed geometry, inventory and policy values stay `?`.

The [indexing rule](rules-indexing.md) considers direct steps and every authored
worm plate circle, preferring exact arithmetic before nearest alternatives.
Each of the declared positions must land within its sourced angular tolerance.
Closure against a whole revolution is checked **only for a full pattern**:
`positions >= 2` with `angle_deg` omitted, deriving the step exactly as
`360 / positions`. An authored `angle_deg` with `positions >= 2` is an open
pattern: every position is checked against `angle_tol_deg`, with no closure.
`positions = 1` is one angular setting, such as the cone journal's 12.5182°
inclination, with no closure. The traveler prints plate, circle, turns and hole
**spaces**, then the angle that setting actually turns, its difference from the
planned angle and the allowance, even when that arithmetic remains tentative
because inventory confirmation is missing.
