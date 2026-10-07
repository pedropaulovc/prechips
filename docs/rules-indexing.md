# Indexing

`indexing` implements the declared-input arithmetic in [PLAN §4.3](../PLAN.md#43-workholding-geometry--inventory--needs-the-kernel-for-the-solids). It does not certify backlash, fixture tilt calibration, locating the work, or cutter access.

## Inputs and subject

One finding belongs to each setup. A known hold with no `hold.index` is `not_applicable`; an explicitly unknown hold or index is `unknown`, not a waiver.

```toml
[setups.hold.index]
fixture = "BS-0"
feature = "journal_bore"
angle_deg = 12.5182
positions = 1
```

This angle is the cone example's authored inclination, not a default for another part. `fixture` resolves the declared identity in inventory `fixtures` or `machines` (so `machines.BS-0` is supported). If the same identity exists in both, the fixture entry wins. A known missing/non-present fixture or a known non-dividing-head fixture is an `error`; an unknown identity/category/kind remains `unknown`.

`feature` is optional and selects the manifest feature's `angle_tol_deg`. No feature is inferred from operations. With an **omitted** selector, or with a selected non-BASIC feature that omits `angle_tol_deg`, the rule uses `features.general_tolerances.angular_deg`. A selected `dimension_type = "basic"` feature must supply its own angular acceptance tolerance: an omitted `angle_tol_deg` remains unknown, never inherited from the general class or inferred from a diametral GD&T zone. Explicit numeric and unknown feature tolerances retain precedence. Explicit `feature = "unknown"` leaves the controlling feature and its tolerance unresolved; it must not inherit a general class that could be looser than the unknown feature's requirement. A selector naming no manifest feature is an `error`. The report cites the input field and any authored feature/title-block citation.

`positions` must be a positive integer. For `positions >= 2`, **omitting** `angle_deg` requests a complete evenly spaced pattern: the requested step is the exact rational `360 / positions`, as specified by PLAN §4.3, and only this full pattern is held to cycle closure. An **authored** `angle_deg` with `positions >= 2` declares an open pattern (an arc of repeated steps), whether or not `positions × angle_deg` happens to reach a whole number of revolutions; closure is never inferred from a near-full or exactly-full authored product. Explicit `angle_deg = "unknown"` never requests the derivation and is likewise not a closed pattern. A single setting must supply its angle or remain unknown. There is no separate "closed" input field.

## Exact-first selection

The rule considers the direct plate and every declared worm plate/circle, using rational arithmetic on the numeric TOML value's decimal spelling. A tolerance is never used to call a step exact.

- Direct indexing: the requested angle divided by `direct_index.step_deg` must be an integer. An authored direct position count can supply the step through `360 / count`; an authored step can supply the count through `360 / step`. If both are given, their product must be exactly `360°` and the count must be a positive integer.
- Worm indexing: on circle `h`, the requested number of hole spaces is `angle_deg × worm_ratio × h / 360`. An integer is exact. Full crank turns and remaining spaces are the quotient and remainder after division by `h`.
- If any representation is exact, it wins over every approximation. Otherwise choose the smallest absolute one-step angular error **across all candidates**, including the direct plate.
- Equal errors prefer direct indexing, then lexical plate identity, then the smaller circle. An exact halfway count chooses the lower signed count. Inventory table/list order does not affect the choice.

An omitted `direct_index` declares no direct option. An explicitly unknown direct declaration, unknown plate mapping/circle list/hole count, or unknown worm ratio needed by listed circles cannot silently certify this search. A known candidate can still be reported as tentative, with `selection_complete = false` and an `unknown` finding. An empty known plate mapping declares no worm circles. Nonpositive/nonintegral hole counts and inconsistent known direct-plate geometry are errors, not ignored candidates.

The constant `360°` and the formulas above come from PLAN §4.3, not an inventory assumption or Handbook table. Ratios, counts and candidate dimensions are read only from the inventory. Decimal `51.43°` is therefore not made exact merely because a seven-position pattern is close to it; an omitted seven-position step is the exact rational `360/7`.

## Landing and closure acceptance

For requested step `a`, selected actual step `b`, and `N` positions, each cumulative landing `i = 1 … N` has signed error `i × (b − a)`. Every absolute landing error must be at most the selected angular tolerance. The comparison is rational and inclusive at the tolerance boundary, without an invented floating-point epsilon.

For a **full pattern** (`N >= 2` with an omitted `angle_deg`), the actual total `N × b` is also compared to the nearest integral revolution `360 × k`. Equal-distance revolutions choose the lower signed `k`. The absolute closure error must fit the same tolerance, inclusively. Because the requested total is exactly `360°`, the closure error of a full pattern equals its last landing error; the closure object still reports the revolution and totals the operator will see.

An **open pattern** (`N >= 2` with an authored `angle_deg`) checks every accumulated landing `1 … N` against the tolerance and nothing else: `closure = "not_applicable"`, and three exact 30° holes are not refused because 90° is not a revolution. Exact individual steps never waive a failed landing.

**`positions = 1` is one angular setting, not a cycle.** Only the landing tolerance applies, and `closure = "not_applicable"`. In particular, a cone's single inclination must not be rejected because that angle is not a full revolution.

Inventory `verify = true` permits tentative arithmetic but always yields `unknown`, even if the nominal arithmetic appears to pass or fail. Unknown candidate choices or tolerance likewise prevent approval. Known invalid declarations are errors. With fully known, verified inputs, an out-of-tolerance landing or closure is `error`; otherwise the finding is `pass`. The rule emits no heuristic `warn` or `info` verdicts.

Required indexing unknowns keep the exit at `4`; any known error takes precedence with exit `2`. Bad schema/TOML remains the shared loader's exit `3` before rule evaluation. A complete pass/not-applicable result can exit `0`, subject to other required rules (PLAN §4 and §5.1).

## Report and traveler

Stable `Finding.numbers` fields:

| Field | Meaning |
|---|---|
| `fixture`, `feature`, `positions` | Declared fixture/selector/count; absent selector is `"unknown"`. |
| `requested_angle_deg` | Numeric requested step, or `"unknown"`. |
| `requested_angle_fraction` | Exact rational requested value as a string. |
| `requested_angle_source` | `"declared"` or `"360/positions"`. |
| `actual_angle_deg` | Numeric selected nominal step, or `"unknown"`. |
| `step_error_deg` | Signed selected step minus requested step (the residual of one step), or `"unknown"`. |
| `method`, `plate`, `circle` | `"direct"`/`"worm"`, plate identity (`"direct"` for a direct plate), integer hole count. |
| `turns`, `spaces`, `direction` | Nonnegative full turns and remaining **hole spaces**; `"forward"`/`"reverse"`. Turns are spindle turns for direct indexing and crank turns for worm indexing. |
| `exact` | Whether the selected nominal candidate exactly represents the requested value; not an approval when inputs are unresolved. |
| `selection_complete`, `verified` | Whether the candidate search inputs are complete and the selected fixture is verified. |
| `tolerance_deg`, `tolerance_source` | Acceptance tolerance and manifest input field used; both are `"unknown"` when an explicit unknown selector prevents selecting the controlling tolerance. |
| `position_errors_deg`, `max_position_error_deg` | Signed cumulative errors for steps `1 … N`, and largest absolute error. |
| `closure` | `"not_applicable"` for one setting or an open authored pattern; an object for a full derived pattern once computed, otherwise `"unknown"`. |
| `unresolved`, `invalid`, `failed` | Sorted unresolved/invalid input descriptions and failed landing/closure labels. |

A closure object carries `revolutions`, `target_angle_deg`, `actual_angle_deg`, signed `error_deg`, and `within_tolerance` (boolean or `"unknown"`). Missing arithmetic fields are explicitly `"unknown"`; missing per-position calculations have an empty error list, not invented zeros.

The traveler's Index line prints plate, circle, full turns and hole **spaces**, also for pass findings, and then the one angle that setting executes: `This setting turns the work <actual>°, <residual>° off the planned <requested>° (allowed ±<tolerance>°).` (`Each step …` for several positions, adding `; landing <n> ends <error>° off` for the worst cumulative landing, which for a full pattern is the return to the start). An exact selection prints `… is exactly the planned <requested>°.` (`exactly 1/<positions> turn` for a derived full pattern). Out of tolerance it ends `: OUTSIDE the ±<tolerance>° allowed.` and the finding is an error; an unknown tolerance prints `(allowance ? — not known)`. Angles print at four decimals (two significant digits below 0.001°); the report retains the full computed values. An indexed hold does not also print its planned `jaw_clock_deg` as a hold fact: the Index line is the single executable angle, so plan text must not restate a different one. Unknown rows are visibly `? Tentative`; report-only exactness cannot promote them.

Accepted traveler declarations `zero = "unknown"` and operation `checks = "unknown"` likewise print explicit unresolved `?` instructions. They are not treated as known empty recipes, and must not prevent an otherwise stopped plan from writing its traveler and reporting the original rule-error exit.

For the declared BS-0 circles in [the shop inventory](../examples/inventory/pedro-shop.toml), the cone's authored `12.5182°` single setting selects plate B, circle 23, **1 crank turn + 9 spaces**. Its nominal angle is `288/23°` (12.5217°), with signed landing error `407/115000°` (0.0035°), inside the crank bore's `angle_tol_deg` of 0.0795°; the S5 and S9 Index lines print exactly that. These are computations from the inventory's `worm_ratio = 40` and circle 23, not evidence that the head is verified. The cone remains unknown when inventory verification or its angular acceptance is unknown.

Typical finding sentences:

- `S3: Indexing landings fit the angular tolerance; one angular setting has no cycle closure.`
- `S1: Indexing landings fit the angular tolerance; the open pattern has no cycle closure.`
- `S1: Indexing landings fit the angular tolerance; the full pattern closes within tolerance.`
- `S1: Indexing exceeds the angular tolerance at landing 4, landing 5, landing 6, landing 7.`
- `S1: Indexing exceeds the angular tolerance at landing 7, cycle closure.`
- `S3: Indexing remains tentative: features.features.crank_bore.angle_tol_deg, inventory.machines.BS-0.verify.`

The isolated tests in `tests/test_indexing_m2.py` cover later exact circles, direct indexing, global nearest selection, accumulated errors, inclusive tolerance boundaries, full-pattern closure, open authored patterns, absent versus explicitly unknown angles, a single cone inclination, unknown/verified inventory, deterministic ties and readiness precedence. Integration validation and example golden regeneration belong to the parent M2 acceptance run.
