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

## `datum_consistency`

One subject per feature. Drawing datum names map to actual feature finishing
cuts, not setup-frame labels. Relationships include position datums, coaxial
feature and height-from feature. Reamed/bored/tapped datum finishing cuts replace
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
