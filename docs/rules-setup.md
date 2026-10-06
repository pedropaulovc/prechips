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
`counterbore`, `center`) and saw cut-off (its `cut_plane` defines the setting);
an explicitly supplied point/hole direction is also checked, and
an explicitly unknown action without one is unknown. Missing/empty
fields are errors; explicit unknown values are unknown. It does not compare
all holding dimensions or certify the fixture was physically installed.

Templates:

- `{setup}: holding declarations need {comma-separated missing/unknown fields}.`
- `{setup}: holding and cutting decisions are declared; this does not approve measured fixture clearance.`

Evidence: hold record, stock stations, coolant, deburr, cut directions and
missing fields. Citation: PLAN §4.1 hold fields. No invented grip or deburr
limit appears as a fallback.

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
(parallels + supports)`; cut clearance is `to_z - jaw_top_z`. Below-jaw cuts
require geometric path checks and therefore remain unknown rather than being
invented collision errors. Travel uses transformed stock box extents
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
face/pocket declared extents are used as authored.
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
cuts, not setup-frame labels. Relationships include position and angularity
datums, coaxial feature and height-from feature. Reamed/bored/tapped datum finishing cuts replace
pilots; rough/nonfinishing actions do not establish a final datum. Every feature
finishing-cut/datum-cut pair is evaluated. Same setup passes; an indicated
transfer passes only when it names that feature/datum and originates at or
after the datum finishing setup and before the current setup. Otherwise compare
tolerance to measured `refixture_budget_mm`; tolerance below budget is error,
unknown/unverified budget or unresolved cuts are unknown. Height-band tolerance
is high minus low. Policy citation travels with a known budget.

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
**spaces**, even when that arithmetic remains tentative because inventory
confirmation is missing.
