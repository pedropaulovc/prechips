# Holding, headroom and datum rules

These are declared-field and nominal-arithmetic checks, not measured workholding
certification or kernel collision proofs. Unknown measurement debt stays visible.

## `hold_fields`

One subject per setup. Requires fixture, stop, grip, clamp, coolant, deburr,
and holders for nonmanual ops. A vise/nonlathe setup needs fixed-jaw declaration
unless explicitly not applicable. Lathe setups need OD, support, grip-on and a
known end station; mill setups need top/bottom Z. Authored supports, orientation,
parallels, jaws direction and locator are checked when supplied. Every nonmanual
cut needs `direction` (face, profile, pocket, turn, form and parting actions
included) except point/hole actions (`spot`, `drill`, `ream`, `tap`,
`counterbore`, `center`); an explicitly supplied direction is also checked, and
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

One subject per setup. Lathe is explicitly unsupported. Mill stack in mm is
`fixture bed + parallels + support blocks + physical stock height + tool
projection + holder gauge length + 25 mm insertion`. Physical stock height
(`stock_height_mm`) is `top_z - retained_rail_bottom_z` if authored, otherwise
`top_z - bottom_z`.
Projection is explicit, or `tool OAL - holder grip` when both are known.
The 25 mm insertion allowance is from PLAN §4.1, not holder grip. Support-block
orientation must explicitly identify a listed height; do not pick an arbitrary
block dimension. Per-op margin is `spindle_to_table_max - stack`.

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

Templates:

- `Lathe headroom is outside the mill-only M1 envelope rule.`
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
`holder_stack = "*"` may likewise require every operation's selected holder
gauge. Errors remain exit 2 whether required or not. These three declared-input
rules do not invoke FreeCAD or certify collisions. Lathe setups are
`not_applicable` to the mill envelope/travel checks; lathe holder gauge debt
remains visible in `holder_stack`.

| Rule / subject | Inputs and tier | Sheet sentence |
|---|---|---|
| `envelope` / setup | M5: authored stock and setup stock-state/frame; already-present successful kernel bbox only; fixture jaw height plus parallels/supports; measured holder gauge and installed tool projection; measured spindle-to-table min/max | `S1: op 10 setup stack … mm exceeds spindle-to-table maximum … mm by … mm.` or `? S1: spindle envelope remains unmeasured or unresolved. measure: PM-30MV spindle nose to table at full Z-down, steel rule, mm.` |
| `travel` / setup | M5: transformed operation feature extents/centres or conservative authored stock span; selected cutter radius; commanded tip targets and advanced hole entry/exit; authored `approach_mm`; measured X/Y/Z travel | `S1: … exceeds measured X travel …` or a `?` naming the usable axis travel, feature extent or safe approach to measure and author. |
| `holder_stack` / setup:op | M5: each selected cutting holder's gauge length and measurement metadata | `? S1 op 10: holder … gauge length is unmeasured. measure: … mounted holder gauge length …, steel rule, mm.` |

`envelope` compares each **individual** operation's
`supported stock height + fixture jaw height + parallels/supports + mounted holder gauge + tool projection`
with both measured spindle-to-table limits. It never combines the longest tool
from one operation with the longest holder from another. Equality passes.
The M5 conservative envelope includes jaw height; M1 `headroom` retains its
different physical bed-height plus insertion calculation above. An already
successful `bundle.kernel.bbox_mm` is transformed from model to setup axes;
otherwise authored stock or complete feature extents are used. On every path
an authored setup `stock_state` height overrides finished-model Z: the received
blank, not a shorter finished part, occupies the fixture. A STEP filename or
digest does not cause this rule to launch a kernel or invent a bbox.

`travel` unions positioned operation extents, not just their individual maximum
widths: widely separated holes need the distance between them as well as cutter
radius on both sides. Broad face/profile/pocket operations without complete
extents use a conservative stock-span screen without inventing a stock origin.
`approach_mm` is an explicitly authored nonnegative safe Z approach distance;
missing approach remains unresolved. Z uses commanded targets and the existing
advanced-stock-state hole tip calculation, including drill point/exit allowance,
not merely the finished hole depth.
The manifest must explicitly declare millimetres for this screen. Unknown or
inch feature/frame coordinates are not silently read as mm or converted into a
travel pass; declare a correctly unit-bound millimetre manifest instead.

Each M5 finding cites the input fields and retains nominal vendor numbers only
as evidence. A missing value stays `"unknown"`. Limits and holder geometry
require complete `measured = { by, date, instrument }`; `verify = true` cannot
establish a pass or a measured overrun. A known verified axis/stack violation
still stops if other measurements remain unknown. Every unresolved applicable
row carries concrete `measure:` instructions. `numbers.measurements` carries
stable checklist entries; `tools --measure` provides one sorted, deduplicated
inventory-wide checklist to take to the machine.

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
