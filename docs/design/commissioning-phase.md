# Design: once-per-batch fixture commissioning phase

Status: **design agreed, not implemented.** Issue
[#270](https://github.com/pedropaulovc/prechips/issues/270). Nothing in this
document is shipped behaviour, and no schema, rule or traveler page described
here exists yet. The maintainer decided D1, D2 and D4–D6 on PR #275, and D3 is
deferred to #269 (section 7).

Motivating case: the oblique-trammel jig for the harmonic-analyzer rocker arm
([#269](https://github.com/pedropaulovc/prechips/issues/269)). Its guide is being
built as a third `guided_sweep` guide, alongside the `pivot` and `rail` guides of
PR #258/#267 (`feat/255-guided-sweep`, `feat/255-guide-pictures`). This design does
not assume #269's field names. Section 4.1 lists only what the phase needs a guide
to expose.

## 1. Problem

Some setup work happens once for each fixture installation, not once for each
part. For the trammel jig that work is:

1. zero both DRO axes on the spindle axis;
2. align each rail by reading a pin in its carriage at stations s = 50…400 mm
   against predicted DRO X/Y targets within 0.03 mm, then torque the studs;
3. drill and ream the part-locator hole (HUB) **in the fixture**, at the real apex
   of the cutter circle, so that rail-angle error is absorbed (0.1° moves the arc
   centre about 5 mm); then drill the Ø6 dowel tooling hole by DRO from HUB;
4. cut the jig's own support, a 6 mm acetal riser screwed to the carrier, on both
   pin pairs with a cutter 4 mm larger than the part cutter. Each riser edge then
   lies 2 mm inside the matching finished edge;
5. read the riser (sagitta over a 300 mm chord, width, hub-pin-to-edge distance)
   as the acceptance check before any part is loaded.

Per part, only the blank load, two passes and a pin-pair swap remain.

Today a plan has nowhere to put steps 1–5. They must either be repeated on every
part's traveler or left out of the plan. Leaving them out is worse: per-part
setups would then rely on fixture features (the HUB hole, the dowel hole, the
riser profile) that the checker treats as located by the fixture drawing's
nominal, which is exactly what the in-situ steps exist to avoid.

## 2. Schema

### 2.1 Where the phase lives

A new optional plan root record `commissioning`, holding its own setups. It is
not a flag on ordinary setups.

```toml
[commissioning]
fixture = "trammel-jig"            # the inventory fixtures item being installed
scope = "install"                  # "install" | "batch"
batch_qty = 20                     # parts one commissioning run covers
batch_qty_cite = "..."
renew_when = "rails unclamped or moved; carrier, pin or riser replaced; crash or dropped carrier"
record = "../records/trammel-jig.toml"   # optional: the shop's install record (§2.6)

[[commissioning.setups]]           # ordinary Setup records, ids unique across the plan
id = "C1"
...
```

Why a separate list rather than `Setup.phase = "commission" | "part"`:

- The phase's work is the **fixture**, not the part stock. A commissioning setup
  never takes `stock_in` from the plan's `stock` or from a part setup, and a part
  setup never takes `stock_in` from a commissioning setup. A separate list makes
  that boundary structural instead of something a validator has to enforce
  across one interleaved list.
- The traveler prints the list once, ahead of the part sheets (§5), in its own
  order.
- `stock_ancestry`, `stock_routes` and the joint validators keep their current
  meaning for `setups` unchanged.

Commissioning setups otherwise reuse `Setup` unchanged: `machine`, `frame`,
`hold`, `zero`, `stock_state`, `coolant`, `ops`. Every existing per-op rule
(speeds, feeds, tool resolution, Z column, guided sweep, accessibility) applies to
them as it does to part setups. Their stock comes from a new `stock_in` form
(§2.4).

`scope`:

- `install`: one run covers the fixture until a renewal trigger, for at most
  `batch_qty` parts. Normally `batch_qty = quantity`.
- `batch`: the phase repeats every `batch_qty` parts even without a trigger
  (for example, a riser that wears).

`renew_when` is printed text. prechips cannot observe a rail being unclamped, so
the text is the operator's instruction. The rules enforce only the triggers they
can see (§3.5).

### 2.2 New op actions

Commissioning ops are ordinary `Operation` records. Three new `do` actions join
the existing vocabulary. They are allowed **only** in `commissioning.setups`;
anywhere else they are an error.

| `do` | Purpose | Fields |
|---|---|---|
| `align` | read a guide element against predicted DRO targets | `readings` (a `ReadingSet`, §2.3), `gauge`, `tolerance_mm` / `tolerance_in`, `tolerance_cite` |
| `torque` | tighten named fasteners in a stated order | `torque` (`TorqueStep`) |
| `accept` | acceptance readings on a commissioned fixture feature | `readings` (a list of `Reading`), with `checks` naming the gauge per reading |

The existing `drill`, `ream`, `spot` and `finish_profile` actions are reused
**unchanged** for in-situ machining. They gain one field, `fixture_feature`,
which replaces `feature` (§2.4).

`TorqueStep`:

| Field | Type (also accepts `"unknown"`) |
|---|---|
| `fasteners` | `str`: the fastener group as the fixture names it (`"rail A T-slot studs"`) |
| `element` | `str`: the guide element those fasteners hold (`"rail_a.pin"`), for the read-after-tightening rule (§2.3) |
| `count` | `int`, at least 1: a step tightening no fastener is a schema error |
| `value_nm` / `value_in_lbf` | `float`, one spelling, strictly positive: 0 or a negative target is a schema error, because a step with no preload must never pass |
| `passes` | `list[float]`: fractions of `value`, ascending, ending at 1.0 (`[0.5, 1.0]`) |
| `sequence` | `str`: printed order (`"centre outward, alternating sides"`) |
| `wrench` | `str`: the inventory `gauges` item, `kind = "torque_wrench"`, with `range_nm` / `range_in_lbf` (a new torque-unit `[least, greatest]` range field, one spelling) |
| `cite` | `Citations` |

A torque value is a shop/vendor number, never a measured length. It needs a
citation, or the AGENTS.md example-value comment. Unknown → `?`.

Every pass value (`value × fraction`, so 20 and 40 N·m for `[0.5, 1.0]` of 40)
must lie inside the wrench's range. A pass value outside it is an error, for
example a 2–24 N·m wrench named for the 40 N·m step. A wrench with no range, or
one whose range carries no citation, leaves the step `?`. A trusted `steps`
entry never overrides either result.

An `align` tolerance is an authored limit, like `Hold.align`'s `limit_mm`, and it
needs `tolerance_cite`: the part band it protects, a vendor figure, or the
author's reasoning. An uncited tolerance leaves every reading of that op `?`
("alignment tolerance uncited"), never a pass against an invented threshold.

### 2.3 Readings: predicted values, never authored answers

A reading names *what* is read and *how far off* it may be. The **predicted**
value is always computed by the rules from the plan's geometry. It is never an
authored number. An author can add an optional `expect` as a cross-check only
(decision D6):

- if `expect` differs from the prediction by more than the reading's tolerance
  (the `align` op's `tolerance`, or the `accept` reading's band), the result is an
  error naming both values;
- the prediction is always what gets printed and what a recorded reading is
  judged against. `expect` is never the source of the value, and an `expect` on a
  reading whose prediction is unknown does not stand in for it: the reading
  stays `?`.

`ReadingSet` (for `align`):

| Field | Type |
|---|---|
| `element` | `str`: the guide element read, by the guide's own name (`"rail_a.pin"`) |
| `stations_mm` | `list[float]`: guide stations (s along the rail, for a trammel) |
| `role` | `"set"` (printed targets for adjusting the element; no record keys) or `"verify"` (the readings the record must hold) |

**Read after tightening.** Tightening can move a rail, so a reading taken before
the torque says nothing about where the guide ends up. A `TorqueStep` names the
guide `element` its fasteners hold. Both a torque and a `set` align can move
the element, so both count as **adjustments**. For every element that has any
adjustment, the validator requires a `verify` align op on that element after its
**last adjustment**, in the same setup. Any `set` or torque on the element after
its last `verify` is an error, because the `verify` would then describe a guide
that has since moved (torque → verify → set is rejected). A `set` op generates
no keys, so an adjustment is printed and never recorded as evidence.

**Enough stations.** A `verify` set must have at least two distinct stations,
and the two farthest apart must span at least half the element's travel in the
guide's sweep (`stations_mm` within that travel). One point cannot reveal a rail
rotated about it, and an empty list records nothing. An empty or single-station
`verify` set, or a span shorter than half the travel, is an error. The guide
(§4.1) supplies the travel; while it is unknown, the check is `?`. The sketch's
50…400 stations span 350 of a rail travel of about 350.

Each `verify` station becomes one reading, keyed `"<setup>:<op>/<element>@<station>"` (for
example `C1:40/rail_a.pin@400`). The prediction is a DRO X/Y pair in the plan's
`dro` sign convention: the pin centred under the spindle, with the DRO zeroed on
the spindle axis at the guide's crossing point. It is computed by the guide
(§4.1).

`Reading` (for `accept`, also reused by #11, §6.1):

| Field | Type (also accepts `"unknown"`) |
|---|---|
| `name` | `str`: key within the op (`"sagitta_outer"`) |
| `quantity` | `"sagitta"` / `"width"` / `"distance"` / `"size"` / `"dro_xy"` / `"z"` |
| `of` | the commissioned element read: one `str` for a single-subject quantity (`sagitta`, `size`, `z`); exactly two, `[reference, subject]`, for a relational quantity (`distance`, `width`, `dro_xy`). Any other count is an error |
| `claims` | `list[str]`: the in-situ claims this reading establishes (`"trammel-jig.dowel_hole.position"`, §3.3); empty for a reading that trusts nothing (#11) |
| `pin` | `str`: the inventory `pin_gauge` a `distance` to a hole is read over. Required for that case and refused for any other reading |
| `contact` | `"near"` or `"far"`: the side of the pin the gauge touches. Required with `pin`, refused without it |
| `chord_mm` / `chord_in` | `float` (`sagitta` only): the nominal chord the sheet prints. The prediction uses the gauge's **measured** chord, not this value (below). The nominal must lie within 1 % of the gauge's `chord_limits`, else it is an error naming both. The nominal must satisfy `0 < chord < 2R` for the edge's predicted radius `R`, else it is an error. Measured `chord_limits` that reach `2R` are uncertainty, not a plan error, and leave the reading `?` (below). An unknown `R` leaves both checks `?` |
| `band_mm` / `band_in` | `Vector` `[low, high]` relative to the prediction, or a symmetric `float` |
| `band_cite` | `Citations` |
| `expect` | optional authored cross-check (above) |

Each reading's key is `"<setup>:<op>/<name>"`.

The band is an authored acceptance limit, so it needs a citation: a part
tolerance it protects, or the author's reasoning. A band is not a measurement.
An uncited band leaves the reading `?`.

**Unique keys.** Every generated record key must be unique in the plan, because
one record entry must never answer two readings. The validator therefore
rejects:

- two readings with the same `name` in one `accept` op;
- a station listed twice in one `ReadingSet`;
- two `ReadingSet`s on the same `element` in one `align` op;
- two commissioning setups with the same `id` (setup ids are already unique
  across the plan, §2.1).

Each collision is an error naming the duplicated key.

**Gauges.** A reading's gauge (the `align` op's `gauge`, an `accept` op's
`checks`) must resolve to an inventory `gauges` item, as an inspection check's
gauge does. Its **kind must suit the quantity**, as in
[rules-inspection](../rules-inspection.md) ("Gauge kinds must suit the
requirement"). The kind names below are the inventory's existing ones, plus the
new kinds the commissioning PRs add:

| Quantity | Compatible gauge kinds |
|---|---|
| `align`, `dro_xy` (centring under the spindle) | `dial_test_indicator`, `coax_indicator` (new). An edge finder is a `tools` item, not a gauge, and cannot centre on a pin, so it is not accepted |
| `sagitta` | `sagitta_gauge` (new: a chord bar with an indicator). Its chord is a new inventory field, `chord_limits_mm` / `chord_limits_in` (one spelling), a fact-local `MeasuredLimits` `[least, greatest]` with its own `measured` record. The limits are the chord's measured uncertainty, so no resolution is invented. An unmeasured or flagged chord leaves the reading `?`. A bare indicator is not accepted, because nothing would fix the chord. The gauge is digested like any named gauge (§3.4) |
| `width`, `distance` | `caliper`, `micrometer`, `height_gauge`. A `distance` to a hole is read over a pin in it: the reading names the `pin` (an inventory `pin_gauge` with a measured diameter) and the `contact` side, `"near"` or `"far"`. The printed target moves the predicted centreline offset `o` by the pin radius `r` toward the reference for `near` and away from it for `far`. That is `o − sign(o)·r` (near) and `o + sign(o)·r` (far), so a hole inside the edge (negative `o`) gets `o + r` on its near side, not `o − r`. The sheet prints the target with its sign and names the side. The recorded value is the signed contact distance, and it is judged directly against that signed contact target; the rules never convert it back to a centreline value. Range coverage uses the **magnitude** of the contact interval, since a caliper reads distance, not side. A hole inside the edge, with a target of −3.2, needs a caliper that covers 3.2. An untrusted pin diameter leaves the reading `?`, and the pin is digested in `[planned]` |
| `size` of a hole | `pin_gauge_set`, `bore_gauge` (an external micrometer never measures a bore) |
| `z` | `height_gauge`, `dial_test_indicator` |
| torque `steps` | `torque_wrench` |

An incompatible kind is an error even when its range and resolution would do
(pin gauges named for a `sagitta`, calipers named as a centring gauge), and no
record entry can make such a reading pass. Then the gauge must span what it
measures, which depends on what produces the value:

- a **DRO coordinate** (`align`, and `dro_xy`): the machine's DRO gives the
  value, and the gauge, a coaxial or dial test indicator, only centres the
  element under the spindle. The predicted coordinate must lie inside the
  commissioning setup's machine travel, and the DRO resolution must be no
  coarser than the tolerance or band. `machines.<id>.envelope.travel` is a
  stop-to-stop stroke, not a coordinate bound, so the check is collective, and it
  is made in **one frame**. A relational reading's DRO value is relative to its
  reference (`hub_apex` from the apex pose, `dowel_position` from HUB), so the
  rules first place every position the setup visits in that setup's frame: the
  zero, each reference at its predicted position, and each subject at its
  reference plus the predicted offset. On each axis, the span from the least to
  the greatest of those absolute positions, check-jog positions included, must be
  no longer than that axis's stroke. Two ±100 moves from references 800 apart
  therefore need about 1000 of stroke, not 200. Where the zero sits in the
  stroke is the operator's choice, so the sheet prints the room the zero needs
  on each side ("zero X with at least 395.9 of travel toward −X"). A span longer
  than the stroke is an error, and an unmeasured stroke leaves the reading `?`. The gauge's
  resolution must be no coarser than the tolerance, and its range need only
  cover the centring deviation: the tolerance either side, plus one resolution
  step beyond each end, so a deviation past either limit still reads. So the
  −395.89 mm target of `rail_a.pin@400` is checked against the table's travel,
  not against the indicator;
- **every other quantity** (`sagitta`, `width`, `distance`, `size`, `z`): the
  gauge gives the value. Its range must cover the whole **acceptance
  interval**, `[predicted + low, predicted + high]`, plus one resolution step
  beyond each end, so that a value past either limit reads as past it rather
  than as the gauge's last step. Its resolution must be no coarser than the
  band. For a limit-style gauge (a pin set read as the largest pin that enters),
  the set must hold a pin at or below the low limit, a pin at or above the high
  limit, and one past each. A pin set ending at 8.000 therefore cannot judge
  HUB's `[8.000, 8.015]`: an oversized hole would still read 8.000.

An unresolved or untrusted gauge or machine fact leaves the reading `?`. A gauge
or DRO too coarse for the band, or a target outside the travel, is an error.

### 2.4 In-situ fixture features

A fixture solid declares where its location comes from, as an enum:

```toml
[[fixtures.trammel-jig.solids]]
name = "hub_hole"
shape = "cylinder"
void = true
dia_mm = 8.0                       # reamed size from the drawing
at_mm = [0.0, 0.0, 0.0]            # drawing nominal: where the SPOT goes
located_by = "in_situ"             # "drawing" (default) | "in_situ"
```

- `located_by = "drawing"` (the default) keeps today's behaviour exactly.
- `located_by = "in_situ"` means the drawing locates only the spot. The solid's
  `at_mm` is the spot position, and its finished location is wherever its
  commissioning route puts it.

**Route.** Each `in_situ` solid is made by a **route**: every commissioning op
that names it as `fixture_feature = "<fixture>.<solid>"` (or a named part of it,
`"<fixture>.<solid>.<edge>"`), in plan order. A hole's route is typically spot,
drill and ream, and the riser's is one sweep per edge. The validator requires:

- at least one op in the route; an `in_situ` solid with none is an error;
- exactly one `locate` per located element: on the first op of a hole's route,
  which later ops inherit (a later op with its own `locate` is an error); and on
  each edge's own sweep for a profile, which is located by its guide pose;
- every op of one hole's route in the same commissioning setup, so the hole is
  never re-located between ops. A riser's edges may be cut in one setup or two;
- the route's last op that sets size is the **terminal** op, and the route's
  earlier ops are roughing. The **declared** solid sets the target: its `dia`
  (8.0 for HUB) is what the `size` reading predicts, and the reading's band is
  relative to it. The terminal tool must suit that target: the tool's own size
  plus the band must fall within the declared size's band. A 9 mm reamer named
  for the 8 mm `hub_hole` is an error, not a 9 mm prediction. An unmeasured tool
  size leaves that check `?`. The kernel cuts the declared size.

A part setup that relies on an `in_situ` solid that the plan has no route for is
an error, not debt: the plan is incomplete.

The route's first op says where a hole goes with `locate`, also an enum union:

```toml
locate = { from = "guide", pose = "apex", offset_mm = [0.0, "computed"] }
# or
locate = { from = "trammel-jig.hub_hole", offset_mm = [-292.0, 0.0] }   # by DRO from a made feature
```

- `from = "guide"` asks the guide for a named pose (§4.1). An offset value of
  `"computed"` means the rules derive it: for HUB, the radial distance from the
  cutter's apex position to the hub centre, taken from `features.toml`. It is
  printed, never authored.
- `from = "<fixture>.<solid>"` chains from an earlier in-situ feature by DRO. The
  earlier feature must be made by an earlier commissioning op.

A commissioning op whose work is a fixture solid that the jig itself cuts (the
riser) uses a `guided_sweep` contour on the fixture's own guide. Each sweep names
the edge it cuts, and adds one riser-specific field:

```toml
do = "finish_profile"
fixture_feature = "trammel-jig.riser.inner_edge"   # one op per edge
inset_mm = 2.0       # each riser edge lies this far inside the part's finished edge
part_op = "S3:20"    # the part's finishing sweep on this pin pair
tool = "endmill-14"  # rules check dia == part cutter dia + 2 × inset
```

The riser's cutter is **derived, not hard-coded**:
`dia = part_cutter_dia + 2 × inset_mm`. The part cutter is the cutter of the
**finishing** `guided_sweep` that cuts the matching part edge on the same pin
pair. Each riser edge op names it, `part_op = "S3:20"`, so the binding is never
inferred. The validator rejects a `part_op` that is not a finishing sweep on the
same pin pair. If more than one finishing sweep cuts that part edge, they must all
resolve to the same cutter diameter; otherwise the result is an error naming
each. Rough sweeps leave stock and do not set the finished edge, so they are not
consulted. The named tool must match
within the DRO resolution, or the result is an error naming both diameters. An
unknown part cutter leaves the check `?`. This keeps the 4 mm figure honest if
the part cutter ever changes (and that change is a renewal trigger, §3.5).

New `stock_in` form for commissioning setups:

- `"fixture.<id>"`: the installed fixture's solids, posed by `hold.pose`;
- `"fixture.<id>.<solid>"`: one fixture solid as the work, for the riser blank.

These forms are refused in part setups.

### 2.5 Per-part setups referencing the phase

Part setups name nothing new. A part setup **depends on** commissioning when any
of the following holds:

- its `hold.fixture` (or `stop_fixture`) is `commissioning.fixture`;
- any solid it locates against, poses on or clears is an `in_situ` solid;
- it runs a `guided_sweep` whose `sweep.fixture` is the commissioned fixture.

Dependence is derived, so a part setup cannot escape the gate by leaving out a
reference. An optional explicit `hold.commissioning = "C"` is **not** proposed;
it would only be a second source of truth.

Batch quantity: `commissioning.batch_qty` relates to the existing
`plan.quantity` like this:

- `batch_qty` must be a positive integer: 0 or a negative value is a schema
  error, so the run count never divides by zero or prints a nonpositive number;
- `batch_qty` unknown → `?`;
- `batch_qty ≥ quantity` → one run;
- otherwise the traveler prints `runs = ceil(quantity / batch_qty)` and
  "re-commission every `batch_qty` parts", and the rule emits a `warn` (decision
  D5, §3.5).

prechips does not count parts made or runs taken. The part sheets' meta line prints
`qty 20 · after commissioning C (covers 20)`.

### 2.6 The install record (where readings live)

Readings live in a **shop-state record file**, not in the plan and not on the
inventory fixture item. It is named by `commissioning.record`, relative to the
plan, like `paths.inventory`.

```toml
# records/trammel-jig.toml: one file per installation; appended by the shop
fixture = "trammel-jig"
install = "PM-30MV table; rail A in T-slots 2/3, rail B in 3/4"

[planned]                           # one digest per planned input, §3.4; written by the checker
commissioning = "<sha256>"
"fixtures.trammel-jig" = "<sha256>"
dro = "<sha256>"
"frames.CT" = "<sha256>"         # the plan frame all four commissioning setups use
features = "<sha256>"
"tools.endmill-10" = "<sha256>"     # the part cutter that derives the riser cutter
"tools.endmill-14" = "<sha256>"     # the riser cutter
"tools.reamer-8h7" = "<sha256>"     # terminal reamers: checked against the declared sizes
"tools.reamer-6h7" = "<sha256>"
"machines.PM-30MV" = "<sha256>"
"gauges.coax-indicator" = "<sha256>"
"gauges.torque-wrench" = "<sha256>"
"gauges.sagitta-gauge-300" = "<sha256>"
"gauges.calipers" = "<sha256>"
"gauges.gauge-pins" = "<sha256>"
"gauges.pin-8" = "<sha256>"          # the HUB pin hub_pin_to_edge reads over

[readings."C1:40/rail_a.pin@400"]
value_mm = [-395.884, -57.203]
gauge = "coax-indicator"            # must equal the align op's gauge
machine = "PM-30MV"                 # DRO reading: must equal the setup's machine
measured = { status = "measured", by = "...", date = "2026-...", instrument = "coaxial indicator, gauges.coax" }

[steps."C1:30"]                     # a torque step: done, not a value
gauge = "torque-wrench"             # must equal the step's wrench
measured = { status = "measured", by = "...", date = "...", instrument = "gauges.torque-wrench" }
```

Why a separate file:

- **Plan.** The plan is the planned document and must not change when a reading
  is taken.
- **Inventory.** An installation is transient: the rails come off the table after
  the batch. Inventory facts describe the kit, which outlives an install.
  Readings on the fixture item would wrongly survive into the next install.
- **Approvals.** The record file is an input whose digest enters the report's
  input table, like the inventory. Re-commissioning therefore changes the report
  hash and stales a first-article approval
  ([report-and-telemetry](../report-and-telemetry.md)). **That is intended:** a
  first article approved under one installation says nothing about the next one.

Each entry reuses the existing `Measurement` record, so `_trust` in
`measurements.py` applies unchanged. Only `status = "measured"` with complete
`by`/`date`/`instrument` counts. `assumed`, `illustrative`, an omitted status,
or `verify = true` is debt. `by` is attribution and never affects trust.

`_trust` does not read `instrument` prose, so it cannot tell which gauge was
used. Each entry therefore also carries a structured `gauge`: the inventory id
of what took the reading (or of the wrench, for a `steps` entry). It must equal
the gauge the plan names for that key: the `align` op's `gauge`, the `accept`
op's `checks` entry, or the `TorqueStep`'s `wrench`. A reading read over a pin
also records its `pin` id, which must equal the reading's planned `pin`, because
the pin's diameter enters the prediction. A DRO-derived entry (`align`,
`dro_xy`) also records its `machine` id, which must equal the commissioning
setup's machine, because that machine's DRO resolution and travel enter the
judgement. A missing or different `pin` or `machine` leaves the entry `?`,
naming both. A missing or different
`gauge` leaves the entry `?`, naming both ids ("taken with calipers, planned
gauge-pins"). The capability checks of §2.3 therefore always describe the
gauge that actually took the reading. `instrument` stays attribution.

This is decision D1.

A missing `record` key, a missing file, or a key with no entry is the **normal
planned state**: every reading is `?`. The checker prints the current
`[planned]` table, in the report and on the commissioning sheet, for the shop to
copy into a new record. It never writes the record itself. A reading in the record whose key the plan
does not generate is an error (a typo would otherwise silently leave a real
reading unread).

## 3. Rules semantics

### 3.1 New rule `commissioning`

One finding per reading, per torque step and per in-situ op. A roll-up finding
covers each dependent part setup.

Per reading:

| Prediction | Record entry | Result |
|---|---|---|
| unknown (an input fact is missing or untrusted) | any | `?`: the prediction's own `measure:` debts, plus "reading cannot be judged" |
| known | absent, or an untrusted `Measurement` | `?`: `measure: <key> — <what>, predicted <value> ± <tol>` |
| known | trusted, deviation inside the band | pass |
| known | trusted, deviation outside the band | `✗`: names the reading, the prediction, the band and the excess |

The deviation is **signed**: `d = read − predicted`. A band is `[low, high]`
relative to the prediction, and the reading passes only when
`low ≤ d ≤ high`, both ends inclusive. A symmetric `float` band `b` means
`[−b, b]`, and an `align` tolerance `t` means `[−t, t]`. One-sided fit bands
keep their sign. With `hub_size`'s `[0.0, 0.015]` and a predicted 8.000, a
7.990 reading has `d = −0.010` and fails as undersize. A `dro_xy` or `align`
reading applies the band to each axis separately.

**Sagitta from the measured chord.** The predicted sagitta comes from the
gauge's measured chord, carried with its uncertainty: the chord interval is the
gauge's `chord_limits` `[least, greatest]` itself, and it maps through
`R − √(R² − (c/2)²)` to a predicted sagitta interval. The reading passes only
when its own gauge-step interval minus that whole predicted interval lies
inside the band. A chord interval that reaches `2R` leaves the reading `?`. Near
`c = 2R` the sagitta is very sensitive to the chord (for `R = 100`, chords of
200.00 and 199.99 differ by about 1 mm of sagitta), so propagating `u`, rather
than comparing chords within a resolution, keeps a correct edge from failing
and a wrong one from passing. The trammel's 300 mm chord on R ≈ 800 is far from
that region, so its interval stays narrow.

**Gauge step.** A recorded value only says the true value lies within one gauge
step of it, and the band check judges that whole interval, not the bare number:

- an indicating gauge of resolution `r`: `[read − r/2, read + r/2]`;
- a DRO coordinate (`align`, `dro_xy`): two devices contribute, so their
  half-steps add up. With DRO resolution `r_dro` and centring-gauge resolution
  `r_g`, the interval is `[read − (r_dro + r_g)/2, read + (r_dro + r_g)/2]`. Both
  can err in the same direction, so a reading near a limit is `?` rather than a
  pass;
- a limit-style pin set read as the largest pin that enters:
  `[read, next)`, where `next` is the next larger pin the set actually holds.
  That pin did not enter, so the hole is smaller than it. The recorded value
  must be one of the set's listed sizes, else the entry is an error. The set's
  largest pin has no next, so a reading of it leaves the upper end open and the
  reading `?`. In a set holding 8.000 and 8.020 but no pins between, a reading of
  8.000 means `[8.000, 8.020)`, which can be oversize for `[8.000, 8.015]`, so it
  is `?`, not a pass.

The reading passes when the whole interval lies inside the band, and fails when
the whole interval lies outside it. Otherwise it is `?`, "indeterminate at this
gauge step; re-read with a finer gauge". With the sketch's contiguous 0.01 mm pins
and HUB's `[8.000, 8.015]`, a reading of 8.000 passes, because the next pin is
8.010 and the hole is in `[8.000, 8.010)`. A reading of 8.01 is `?`, because the hole is in
`[8.010, 8.020)` and could be oversize (an 8.019 hole reads 8.01). A reading of
7.99 fails. A band narrower than one step can never pass, and the validator
reports it as an error.

A torque step passes only on a trusted `steps` entry. An in-situ drill or ream op
passes as an op by the ordinary rules. Its **location** is trusted only through
the acceptance readings that cover it (§3.3).

Nothing passes on a prediction alone. A prediction is printed on the sheet as the
target. It is never written into the record, never read back as a reading, and
never the value a finding judges against itself. This is AGENTS.md's rule that
unknown is never a pass, applied to predictions: a predicted reading is a planned
number, like a nominal, and only a recorded reading is evidence.

### 3.2 Gate on dependent part setups

Each dependent part setup gets one `commissioning` finding that rolls up the
whole phase:

- any commissioning finding `✗` → the part setup's finding is `✗`, and its sheet
  prints a STOP: "commissioning C failed: <keys>";
- else any `?` → the part setup's finding is `?`, with every outstanding key
  listed: "commissioning C not recorded: C1:40/rail_a.pin@50 … C4:10/width";
- else pass.

The part setup's other findings are **unchanged**. They still judge planned
geometry (§4). Only this roll-up carries the commissioning debt. That keeps one
missing reading from turning into dozens of duplicate `?` findings, while still
leaving every dependent part setup with visible debt.

`commissioning` joins `ALWAYS_REQUIRED` (`findings.py`; decision D2): no policy
can waive it. A missing, untrusted or stale reading therefore exits 4. A failed
reading, or an `expect` mismatch, exits 2. A plan with no `commissioning` record
emits no finding and keeps today's exit codes. The validator's expected exits for
an example change only when that example gains a `commissioning` block.

### 3.3 Which reading trusts which in-situ feature

Trust is granted per **claim**, never per feature as a whole. Naming a feature
in a reading's `of` trusts nothing by itself.

**Claims.** Each in-situ element has a fixed set of claims, derived from its
kind. They are not authored:

| In-situ element | Claims | Quantities that can establish each claim |
|---|---|---|
| hole (a `void` cylinder) | `size`, and `position` (split into `position.radial` and `position.tangential` when located from the guide, below) | `size`: `size`. `position`: `dro_xy` only. `position.radial`: a **signed** radial `distance` to a swept edge (positive away from the arc centre). `position.tangential`: `dro_xy` from the guide pose |
| swept edge (`<solid>.<edge>`) | `radius`, and `location` unless it is the root edge | `radius`: `sagitta`. `location`: `width` or `distance` |

**Root edge.** The first edge the guide cuts in route order is the **root**. It
is a cut path: it is cut by the guide on a pin pair the part is also cut on, and
it defines the frame the other claims are read in. It has only a `radius` claim.
Every other swept edge also has a `location` claim, relative to the root.

**Binding.** A reading may list only claims owned by an element it actually
measures:

- a single-subject quantity (`sagitta`, `size`, `z`) has one `of` entry, and may
  list only that element's claims;
- a relational quantity (`distance`, `width`, `dro_xy`) has exactly two `of`
  entries, `[reference, subject]`, because one value measures one relationship.
  It may list only the subject's claims, never the reference's. A reading with
  more entries is an error, so one scalar can never cover two holes;
- each listed claim must also accept the reading's quantity, per the table above.

So a `size` reading of `hub_hole` listing `dowel_hole.size` is an error, and so
is a `z` reading listing any position. Neither is ever a silent trust.

**Two-axis positions.** A hole's `position` is a 2D claim, and only a `dro_xy`
reading from a reference establishes it: one signed X/Y pair fixes both axes and
the side. Distances are not accepted for `position`. Two distances leave a
mirror image (a hole reflected across the line joining the references reads the
same), and a third reference only adds cases the validator would have to rule
out. A hole position listed by a `distance` is an error naming the claim.

A hole located from the guide (`locate.from = "guide"`, HUB) has its position
split into two claims, each read against what it must match:

- `position.radial`, HUB's distance from the arc centre relative to the cut
  edge, read as a signed `distance` to a swept edge. This ties HUB to the real
  arc, which is why HUB is drilled in situ;
- `position.tangential`, HUB's placement along the arc, read as a `dro_xy` from
  the guide's `apex` pose. With the carrier locked at the apex, the HUB pin is
  centred under the spindle and the DRO is read; the component along the arc's
  tangent at the apex is judged against the band. A HUB shifted along the arc,
  with the dowel shifted by the same amount, leaves the radial reading and the
  HUB-to-dowel reading unchanged. Its parts would still cut true radii, but each
  would sit off-centre in the carrier's sweep window (±6.5° for the trammel)
  and on its riser support. Only this reading catches that.

A guide pose (`"guide.apex"`) may be a relational reference, like the root
edge: the guide defines it. The dowel then fixes the part's rotation about HUB,
and its own position (two axes, from HUB) is a claim.

**Reference chain.** A relational claim's reference must itself be the root edge,
or an element whose relational claim is covered, so that the chain reaches the
root without a cycle. For the trammel:

- `width` puts the outer edge relative to the root (inner) edge;
- `hub_pin_to_edge` puts HUB's radial position relative to the outer edge, as
  a signed offset (inside or outside the edge), which is what the in-situ HUB
  exists to match;
- `dowel_position` puts the dowel hole relative to HUB, in both axes (`dro_xy`).

**Coverage.** The validator requires that every claim of every in-situ element a
dependent part setup consumes is listed by at least one compatible, bound
reading. A missing claim is an error ("in-situ claim trammel-jig.dowel_hole.size
has no acceptance reading"), because nothing would ever discharge its debt.

**Trust.** A claim is trusted only when every reading that lists it passes. A
dependent setup's roll-up (§3.2) is a pass only when every consumed claim is
trusted.

**Read after the last change.** An acceptance reading must describe the final
geometry. Each reading must come after the last commissioning op that can change
its subject or its reference: any op of the subject's route, a sweep of a swept
edge, or an adjustment of a guide element. Ordering is by setup order, then by
op number. A reading taken before such an op, for example `hub_size` after the
drill but before the terminal ream, is an error, and it can never trust the
claim.

The trammel's claims and readings (decision D4 adds the dowel's two):

| Claim | Reading |
|---|---|
| `riser.inner_edge.radius` (root), `riser.outer_edge.radius` | `sagitta_inner`, `sagitta_outer` |
| `riser.outer_edge.location` | `width`, from the inner edge |
| `hub_hole.position.radial` | `hub_pin_to_edge`, from the outer edge |
| `hub_hole.position.tangential` | `hub_apex`: `dro_xy` from the guide's apex pose, HUB pin centred under the spindle with the carrier locked at the apex |
| `hub_hole.size` | `hub_size` (largest gauge pin that enters) |
| `dowel_hole.position` | `dowel_position`: `dro_xy` from the HUB pin to the dowel hole, with a coaxial indicator on each |
| `dowel_hole.size` | `dowel_fit`: largest gauge pin that enters, predicted from the declared Ø6.0 and banded by the dowel's fit |

### 3.4 Staleness

The record's `[planned]` table holds **one SHA-256 per planned input**, like the
approval record's `[inputs]`. The inputs are:

- the `commissioning` block;
- the plan's `dro` block (station targets are in its sign convention);
- each `plan.frames` entry a commissioning setup uses (`frame = "CT"`): its
  origin, axes and binding place the guide poses, the in-situ locations and the
  DRO targets in setup coordinates. A frame exported from the STEP is covered by
  the features digest;
- the features file, when a prediction reads it (HUB's offset and the
  hub-pin-to-edge distance read the hub centre);
- every inventory item a prediction or a derived check consumes: the
  commissioned fixture, each terminal tool checked against its declared
  size, the riser cutter and the part cutter it is derived from;
- the equipment the readings are taken with: the machine of every
  commissioning setup (its DRO resolution sets the printed targets) and every
  gauge an `align`, `accept` or `torque` op names. The commissioning block holds
  only their ids, so their inventory records are digested too. A gauge replaced
  by a better one, or a machine whose resolution changed, therefore stales
  readings taken with the old equipment, rather than letting them start to
  pass.

The checker's printed table lists exactly these, so a record copied from it is
complete.

The checker computes the same table for the current plan and compares the two:

- a digest that differs names that input as changed;
- an input in the current table but missing from the record is named as new,
  because the record was taken without it. This differs from approvals, which
  skip an omitted input: a commissioning record must cover everything its
  predictions use;
- an input only in the record (no longer consumed) is ignored.

Any changed or new input makes **every record entry** stale: every reading
and every torque `steps` completion is `?`, with "install record no longer
matches the plan: <changed and new inputs> changed. Re-commission." A torque
completion recorded against a different planned value or wrench therefore no
longer passes. This mirrors
the approval record's stale warning. A record never certifies a plan it was not
taken against.

### 3.5 Renewal triggers the rules can see

- a planned digest changed (§3.4), which covers a part-cutter change, a moved
  rail angle or pin spacing, and a changed riser inset;
- `quantity > batch_qty`, for either scope: one run covers only `batch_qty`
  parts. The traveler prints `runs = ceil(quantity / batch_qty)`, and the rule
  emits a `warn` naming the run count (decision D5). prechips does not track runs
  or parts, so the warning stays while the condition holds; it is not debt, and
  it does not change the exit code;
- triggers it cannot see (`renew_when`) are printed only.

### 3.6 Interaction with existing rules

- `zero_recipe` and `travel`: commissioning setups are ordinary setups. A
  setup made only of `align` and `torque` ops has no cutting op, so it needs only
  the zero its readings use: both axes on the spindle axis, `zero.x`/`zero.y`
  with `edge = "spindle axis"`. That is a new `AxisZero` form, `method = "spindle"`,
  printed as "zero X and Y here; this is the crossing point".
- `guided_sweep` on the riser: the existing rule, with the trammel guide (#269).
  `headroom`/`travel` debts for the moving fixture apply as on part setups (#272).
- `inspection`: the `accept` readings are not part requirements, and they never
  satisfy a part requirement's `checks`. The first part is still a first article
  under the existing approval flow.

## 4. Kernel

### 4.1 What the phase needs from a guide (#269 interface)

The commissioning rules need four things from the trammel guide. For the
analytic predictions these are pure arithmetic in the rules, with no kernel run:

1. **Station targets:** for element `e` at station `s`, the predicted DRO X/Y of
   the element with the DRO zeroed at the crossing point. For a trammel whose rail
   lines cross at the spindle at ±α/2 about the guide axis, this is
   `s·(cos θ, sin θ)` with `θ = θ₀ ± α/2`.
2. **Named poses:** the carrier pose where the cutter centre sits at the arc apex
   (`"apex"`), as a transform from the carrier frame to the setup frame.
3. **Per pin pair:** the cutter-centre radius, `D / (2 sin α)`, and the arc centre
   in the carrier frame.
4. **Error budget:** the change in radius and arc centre per unit of each guide
   fact (pin clearance, rail angle), so that tolerances such as 0.03 mm can be
   checked against the part band. This is optional for v1.

The field names belong to #269. This design only requires that the guide exposes
these four things as functions of its declared, measured facts. Any input that is
unmeasured makes the dependent prediction unknown.

### 4.2 Geometry the kernel does need

The kernel builds **planned geometry only**. Recorded readings never enter
`engine_job`.

- **Fixture as stock, accumulated.** The kernel keeps one **fixture state** per
  commissioned fixture, a set of named solids. It starts as the posed inventory
  solids, built by the existing `_solids()` path, **except** every
  `located_by = "in_situ"` void, which is left out. Today `_solids()` emits each
  trusted void at its authored `at_mm` and subtracts it before any operation,
  which would leave a hole at the drawing's spot as well as the one the route
  cuts. An in-situ void exists only once its route has cut it, at the planned
  location. Until then the spot is only a mark, with no depth. Commissioning setups run in
  order, and each one reads and updates that state:
  - `stock_in = "fixture.<id>"` takes the whole current state as its work. Its
    result replaces the whole state, so C2's holes stay in it;
  - `stock_in = "fixture.<id>.<solid>"` takes only that solid from the current
    state. Its result replaces only that solid, and every other solid, C2's
    holes included, carries over unchanged. The cut riser goes back into the
    state where the blank was;
  - a setup that cuts nothing (C1, C4) leaves the state unchanged.

  The in-situ voids are cut at their **planned** location: the `locate` result
  in setup coordinates, not the spot `at_mm`. The riser is cut by the
  guided-sweep removal on the riser blank. In the sketch, C4 reads the state
  after C2 and C3, holes and cut riser together.
- **Commissioned fixture output.** A new job section,
  `commissioned[<fixture id>]`, holds the accumulated fixture state after the
  last commissioning setup. Part setups whose `hold.fixture` is that fixture take
  their fixture components from it instead of rebuilding the inventory
  primitives. Clash, contact and clearance checks then see the cut riser and the
  holes where the plan puts them.
- **Render and fixture verdicts.** Today a fixture is `modeled` only when every
  drawn component is exact and no debt remains. Add one enum value: a fixture
  whose only remaining debt is unrecorded commissioning is `predicted`, drawn
  with a "located by commissioning C — not yet recorded" callout. It is not
  `modeled`, and nothing reads `predicted` as a pass.

Recommended: chain from the commissioning output (above). The alternative
considered was to keep in-situ features as inventory primitives at a predicted
location, with their trust bound to the record. It was rejected because the
riser's profile is an arc band, not a primitive, and because two sources of
fixture geometry would drift apart.

**Dependency on #182.** Cutting the riser leaves offcut pieces on either side of
the arc band. `freecad_job._remove` keeps every piece above `STOCK_MM3`, so
without a way to discard pieces, the "riser" passed to part setups would still
include its offcuts, and every clash check would be wrong. The kernel half of
this design (P4 in §7) therefore waits for #182's keep/discard mechanism. Until
then the riser cannot be chained, and its part setups' fixture clearance stays
`?`.

### 4.3 Cache identities that change

- **Job content.** `engine_job` gains a `commissioning` setup list, `commissioned`
  and the new `stock_in` forms. Any plan with a `commissioning` block therefore
  gets new keys. Plans without one serialise exactly as today, as long as empty
  sections are omitted rather than emitted as `[]`. This must be tested (§8).
- **Engine digest.** `_engine_digest()` hashes `kernel/*.py`, so the kernel
  change invalidates every cached entry once, as any kernel change does. CI's
  persisted cache namespace already includes the engine source digest, so stale
  entries miss rather than mismatch.
- **Not in the key:** the install record. A reading changes no geometry, so
  recording, correcting or re-taking readings never invalidates a kernel cache
  entry. A test asserts this.
- **Kernel identity** (launcher path and SHA) and the STEP digest are unchanged.

## 5. Traveler

### 5.1 Placement

In `render()`, the commissioning section goes **after the job page and before
the first part setup**. It is printed once, whatever the quantity. The job page's
STOCK AND ROUTE gains one line: "Commissioning C (once per install, covers 20)
before the first part."

Commissioning pages differ from part pages:

- **Meta line:** prints `commissioning C · once per install · covers 20` instead
  of `qty 20`.
- **Sign-off:** each commissioning sheet ends with "Commissioned by ____ date
  ____. Readings entered in <record path>". This is not the job-level
  first-article sign-off, which stays on the part sheets.
- **Banner:** each sheet carries `PLANNED — NOT APPROVED` like every page.
  Commissioning is not approval.

### 5.2 Page layout

**Sheet C-1, front (one page):**

- Heading: `COMMISSIONING C — trammel-jig — once per install`.
- Renewal box: the `renew_when` text, plus "and whenever this sheet's planned
  values change".
- Status boxes (the existing `status_lines` style).
- A step list, one line per commissioning op, in order, each with its key range.

**Reading table**, one per `align` op. Rows are stations, and blanks are written
in by hand:

| Key | s (mm) | Predicted X | Predicted Y | ± | Read X | Read Y | ✓ |
|---|---|---|---|---|---|---|---|
| C1:40/rail_a.pin@50 | 50 | −49.49 | −7.15 | 0.03 | ______ | ______ | ☐ |
| … | | | | | | | |
| C1:40/rail_a.pin@400 | 400 | −395.89 | −57.19 | 0.03 | ______ | ______ | ☐ |

The predicted values shown come from the §9 example geometry. They print to the DRO
resolution. A `?` prediction prints `?` with
its `M#` instead of a number, never a guessed value.

**Torque table:**

| Key | Fasteners | Count | Pass 1 | Pass 2 | Order | Wrench | Done |
|---|---|---|---|---|---|---|---|
| C1:30 | rail A T-slot studs | 4 | 50 % (20 N·m) | 100 % (40 N·m) | centre outward | torque-wrench | ☐ initials |

**In-situ machining** reuses the existing op table and DRO block. HUB's row
prints the computed offset, and the location column reads "at apex, +Y <computed
offset>", never the drawing nominal.

**Riser sweep** reuses the guided-sweep sheet (`sheet_sweep.py`) unchanged, with
the derived cutter printed as "Ø14 = part cutter Ø10 + 2 × 2.0 inset".

**Acceptance table:**

| Key | Reading | Of | Gauge | Predicted | Band | Read | ✓ |
|---|---|---|---|---|---|---|---|
| C4:10/sagitta_outer | sagitta over 300 chord | riser outer edge | … | (computed) | ±0.10 | ______ | ☐ |
| C4:10/width | width | riser | … | (computed) | ±… | ______ | ☐ |
| C4:10/hub_pin_to_edge | distance | HUB pin → riser edge at apex | … | (computed) | ±… | ______ | ☐ |
| C4:10/hub_apex | DRO X/Y | apex pose → HUB pin | coaxial indicator, DRO | (computed X, Y) | ±… | ______ , ______ | ☐ |
| C4:10/hub_size | size | HUB hole | gauge pins | 8.000 (declared) | fit band | ______ | ☐ |
| C4:10/dowel_position | DRO X/Y | HUB pin → dowel hole | coaxial indicator, DRO | (computed X, Y) | ±… | ______ , ______ | ☐ |
| C4:10/dowel_fit | size | dowel hole | gauge pins | 6.000 (declared) | fit band | ______ | ☐ |

A closing box reads: "Do not load a part until every ☐ is ticked and entered in
<record path>."

### 5.3 Part sheets

Each dependent part setup's front sheet gains one status line from the roll-up
(§3.2):

- `? commissioning C not recorded (N readings)`, or
- `✗ STOP — commissioning C failed: …`.

Its holding picture shows in-situ features with the `predicted` callout.

### 5.4 Review gate

This changes printed content. The shipping PR for §5 must run the blind
machinist review (AGENTS.md) on the affected traveler. The new section has no
main-branch baseline, so it needs a blind `CLEAR` with no blocker, clutter or
clarity finding.

## 6. Interplay with related issues

### 6.1 #11 (predicted readings before cutting)

#11's per-setup "check before cutting" block uses the same primitive: a `Reading`
whose prediction is computed (stock top from the M5 stack, stand-out, sweep
equality) and printed with a band and a blank. Build `Reading`, the prediction
plumbing and the reading table **once**, here, as a shared module. #11 then adds
only its own predictions. The difference is lifetime: #11's readings belong to a
part setup and are taken on every part, and they are a traveler check, not a
record entry. Commissioning readings are taken once and recorded. The same table
renderer, with a `recorded: "install" | "per_part"` enum, covers both.

### 6.2 #134 (shop-made fixtures as their own parts)

The trammel jig is non-trivial (it locates and aligns the part), so under #134 it
becomes its own part (`MHA-071-TL-nn`) with a drawing, STEP and bundle. The split
is:

- **Fixture bundle:** makes the jig up to the **spot** state. Its drawing marks
  HUB and the dowel hole "SPOT ONLY — drill and ream in situ (commissioning)", and
  the riser as a 6 mm blank, "profile cut in situ".
- **Consumer (rocker) plan:** owns the commissioning. Its predictions depend on
  the part (the hub radius, the cutter) and on this install, neither of which the
  fixture bundle knows.

`located_by = "in_situ"` is how the consumer's inventory entry says the fixture
bundle left these features at spot. When #134 lets a parent reference a fixture
part instead of a make-table, that reference carries `located_by` unchanged.

Commissioning ops are **plan** ops, not inventory `make_ops`. `make_ops` are an
off-machine make route on a shop-made item: they require `shop_made`, are limited
to `_MADE_CATEGORIES`, and have no setup, zero or kernel removal. An in-situ
finish needs all three, and it happens on the production machine, in the
production install.

### 6.3 #182 (keep or discard pieces)

There are two uses:

- the riser cut must keep the band and discard both offcuts (§4.2);
- if a scrap-blank first article is ever used instead of the riser, its pieces
  are discarded whole.

This design consumes whatever form #182 settles on (`release.keep` or a
`stock_in` piece selector) and adds no keep syntax of its own.

## 7. Implementation plan

Line counts are estimates, excluding tests and docs.

| PR | Scope | Size | Depends on |
|---|---|---|---|
| P1 | Schema: `commissioning` root, new `do` actions and their fields, `TorqueStep`, `ReadingSet`/`Reading`, `located_by`, `fixture_feature`, `locate`, the `fixture.<id>` `stock_in` forms, record-file parse, cross-validators (§2.4 errors). Input-format docs. No rules beyond validation. | ~500 | — |
| P2 | Shared predicted-reading module (`Reading`, prediction protocol, band check), the `commissioning` rule, record trust and staleness, the dependent-setup roll-up, `ALWAYS_REQUIRED`. Analytic predictions for HUB offset, sagitta, width and hub-pin distance. Rule-family doc page. | ~700 | P1 |
| P3 | Traveler: commissioning section, reading, torque and acceptance tables, part-sheet status line, meta-line and sign-off changes. Blind machinist review. | ~450 | P2 |
| P4 | Kernel: fixture-as-stock, `commissioned` output chained into part holds, the `predicted` fixture verdict and callout, and empty-section omission for cache stability. Rules-geometry doc. | ~500 | P1, #182 |
| P5 | Trammel guide adapter: station targets, apex pose and pin-pair radii from #269's guide. Derived riser cutter check. | ~250 | P2, #269 |
| P6 | Rocker trammel example bundle (§9) with a demonstration record, expected outputs and validator exits. Blind review on its traveler. | data | P3–P5, HA plan |

P1–P3 can ship before #269 and #182 by using a stub guide in tests. Only P4 and
P5 wait on them.

### Decisions (maintainer, 2026-10-17, on PR #275)

- **D1, record location: decided.** A separate install-record file kept by the
  shop (§2.6). Re-commissioning stales the first-article approval, and that is
  intended.
- **D2, gate severity: decided.** `commissioning` is in `ALWAYS_REQUIRED`. A
  dependent setup with a missing, untrusted or stale reading exits 4 (§3.2).
  The example bundle exits 4 until its demonstration record exists.
- **D3, guide interface names: deferred to #269**, which owns the field names.
  §4.1 lists only what the phase needs; the example's `kind = "trammel"` and
  `pins = "inner"` are placeholders.
- **D4, dowel-hole acceptance: decided.** The in-situ Ø6 dowel hole has its own
  readings: position from HUB (`dowel_position`) and size/fit (`dowel_fit`),
  §3.3. HUB gets the matching `hub_size`, because the claim coverage of §3.3
  requires every claim to be read.
- **D5, batch accounting: decided.** The traveler prints
  `runs = ceil(quantity / batch_qty)` and the rule emits a `warn` (§3.5).
  prechips does not count parts or runs.
- **D6, authored `expect`: decided.** It is allowed only as an optional
  cross-check. The engine always computes the prediction, and an `expect` that
  disagrees beyond the reading's tolerance is an error (§2.3).

## 8. Test plan

Rule tests use a synthetic `bundle.kernel` where kernel facts are needed. CLI
tests use `SYNTHETIC_KERNEL`. All files are temporary.

**Schema (P1)**

- `do = "align"`/`"torque"`/`"accept"` in a part setup → error.
- Routes: a spot/drill/ream route on one hole and one sweep per riser edge are
  valid. An in-situ solid with no route → error. A second `locate` in one hole's
  route, or a hole route split across setups → error. The terminal op sets the
  finished size.
- `locate.from` naming a feature made later or not at all → error.
- Claims: a reading listing a claim its quantity cannot establish (a `z` reading
  claiming a position) → error. A reading listing a claim of an element it does
  not measure (a `size` of `hub_hole` listing `dowel_hole.size`), or of its own
  reference → error. A hole `position` listed by any `distance` → error (the
  mirror-image case); one `dro_xy` → covered; a guide-located hole needs
  `position.radial` (a signed `distance` to a swept edge) and
  `position.tangential` (a `dro_xy` from the guide pose). A relational reading with
  other than two `of` entries → error.
- A consumed claim no reading lists (drop `dowel_fit`) → error naming the
  claim. A reference cycle, or a relational claim whose chain never reaches the
  root edge → error.
- Duplicate generated keys (a repeated reading name, a repeated station) →
  error. An uncited `align` tolerance or `accept` band → `?`. A reading gauge
  coarser than its band → error; an unresolved gauge → `?`.
- `expect` beyond the tolerance → error; within it → no finding; `expect` on an
  unknown prediction → still `?`.
- A `fixture.<id>` `stock_in` in a part setup → error.
- A record key the plan does not generate → error.
- A plan without `commissioning` → byte-identical report to today. Freeze one
  shipped example.

**Rules (P2)**, one test per row of the §3.1 table:

- prediction unknown;
- record absent;
- `status = "assumed"`;
- `status = "illustrative"`;
- `verify = true`;
- incomplete `measured`;
- in band, exactly at each band edge, and outside the band on either side;
- an asymmetric band `[0.0, 0.015]`: an undersize reading (`d < 0`) fails even
  when `|d|` is within 0.015;
- a DRO target inside the machine travel with an indicator whose range is far
  smaller than the coordinate → no gauge error;
- travel span: targets at −400 and +400 on one axis against a 600 stroke →
  error, although each lies within ±600; the span includes 0;
- torque: a pass value outside the wrench's range → error; a wrench with no
  range → `?`;
- every worked commissioning setup names a machine. A setup without one leaves
  its machine-dependent findings `?`.

Also:

- Staleness, per input: one changed digest → all `?` naming only that input; an
  input absent from the record → named as new; an input only in the record →
  ignored. The table the checker prints for the §9 sketch lists every input of
  §3.4, and a record copied from it is not stale. Changing only a gauge's or
  the machine's inventory record stales the record.
- Claim trust: one failed reading leaves only the claims it lists untrusted.
  The roll-up names them.
- Roll-up: dependent setups get `?`/`✗`. A setup on a different fixture is
  unaffected.
- Dependence derived through each of the three paths in §2.5.
- Exit codes: no record → 4; one bad reading → 2; complete and in band → no
  commissioning contribution.
- Riser cutter: matching, mismatched, and unknown part cutter.
- `batch_qty = 0` or negative → schema error.
- Stations: a `verify` set with no station, one station, or a span shorter than
  half the element's travel → error.
- Read after tightening: an adjusted element (torque or `set`) with no later
  `verify` align → error; torque → verify → set, or a `verify` followed by
  another torque → error; `set` readings generate no record keys.
- HUB tangential: a HUB and dowel shifted together along the arc pass the radial
  and HUB-to-dowel readings but fail `hub_apex`; a plan without a tangential
  reading for a guide-located hole → uncovered claim, error.
- Gauge binding: a record entry with no `gauge`, or a different gauge from the
  plan's → `?` naming both.
- Signed radial: a HUB at the mirror radius `2·R_edge − ρ_hub` reads with the
  wrong sign → `✗`.
- Staleness: changing only a commissioning setup's `plan.frames` entry stales
  the record. A changed torque value or wrench stales the torque completion as
  well as the readings.
- Acceptance order: `hub_size` read between the drill and the ream → error; read
  after the ream → valid.
- Riser cutter binding: a riser edge op without `part_op`, or with a `part_op`
  that is a rough sweep or on another pin pair → error; two finishing sweeps on
  that edge with different cutters → error.
- Terminal tool: a 9 mm reamer on the 8 mm `hub_hole` → error; the `size`
  prediction is the declared 8.0, never the tool's size.
- Torque `value_nm = 0` or negative → schema error.
- Gauge kind: pin gauges for `sagitta`, or calipers as a centring gauge → error.
  A `sagitta_gauge` whose chord differs from `chord_mm` → error; with an
  unmeasured chord → `?`; a bare DTI for `sagitta` → error.
- Sagitta chord: `chord_mm = 0`, negative, or at least `2R` → error; a nominal
  more than 1 % off the gauge's measured chord → error; an unmeasured gauge
  chord → `?`; the prediction uses the measured chord limits, and for `R = 100`
  limits reaching 200 → `?`.
- Pin range: a caliper covering `[0, 150]` judges a −3.2 contact target (inside
  the edge); a target beyond its range in magnitude → error.
- Pin contact: a `distance` to a hole with no `pin` or `contact` → error; the
  near target is `o − sign(o)·r` and the far target `o + sign(o)·r`, tested for
  a hole outside the edge (positive `o`) and one inside it (negative `o`); an
  untrusted pin diameter → `?`; a record whose `pin` differs from the planned
  pin → `?` naming both. A DRO entry whose `machine` differs from the setup's
  machine, or is missing → `?`. `pin`/`contact` on a non-distance reading, or
  `contact` without `pin` → schema error.
- Torque `count = 0` or negative → schema error.
- DRO interval: a reading inside the band by less than `(r_dro + r_g)/2` → `?`;
  by more → pass.
- Pin gaps: a set with 8.000 and 8.020 only, reading 8.000 against
  `[8.000, 8.015]` → `?`; a recorded size not in the set → error; a reading of
  the set's largest pin → `?`.
- Chord limits: a `sagitta_gauge` without `chord_limits` → `?`; with them, the
  predicted sagitta interval spans the limits.
- Gauge step: 0.01 pins against `[8.000, 8.015]`: 8.000 → pass; 8.01 → `?`
  (an 8.019 hole reads 8.01); 7.99 → `✗`. A band narrower than the step → error.
- Travel frame: two ±100 relational moves from references 800 apart against a
  600 stroke → error.
- Gauge coverage: a pin set ending at the predicted size cannot judge a
  `[0.0, 0.015]` band → error; a set reaching one step past each limit → no
  error.
- Batch: `quantity > batch_qty` warns with the run count for both scopes, and
  the exit code is unchanged.

**Traveler (P3)**

- The commissioning section precedes the first part setup.
- Its meta line has no `qty`.
- `?` predictions print `?` plus `M#`, never a number.
- Part sheets carry the roll-up line.
- Print and PDF contracts pass with `PRECHIPS_REQUIRE_PRINT_BROWSER=1`.
- Blind machinist review.

**Kernel (P4)**, with the `freecad_kernel` fixture:

- HUB void cut at the planned apex location, not at the spot `at_mm`, and **no**
  void at the spot: the initial fixture state leaves in-situ voids out, so the
  commissioned fixture has exactly one HUB hole even when the spot and the
  planned location differ.
- The riser band is kept and the offcuts discarded (after #182).
- Part-setup clash checks see the cut riser **and** C2's holes: the state
  accumulates across C2 (whole fixture) and C3 (riser only), and C3's riser
  result replaces only the blank.
- The `predicted` verdict and callout.
- With the function-scoped `kernel_cache`: changing only the record file leaves
  the cache key unchanged and hits.
- A plan without `commissioning` keeps its existing key.

## 9. Worked example sketch: rocker trammel jig

**Labelling.** This is a design sketch, not a shipped bundle. Under the AGENTS.md
examples policy, every value below is example data:

- values from #269/#270 are cited to those issues;
- the remaining values are realistic example values, marked as such;
- the demonstration record uses the exact disclosure strings;
- nothing here is a shop measurement, and nothing may be copied into a real shop
  file.

The six real `fixtures.vise-pm-6` measurements are untouched.

### 9.1 Inventory (sketch)

```toml
[fixtures.trammel-jig]
kind = "trammel"                   # #269's kind; name is D3
shop_made = true
note = "Oblique trammel: two HGR15 rails, carrier on two pin pairs (#269)."
pin_spacing_mm = { value = 450.0, measured = { status = "measured", by = "example value (realistic, not a shop measurement)", date = "2026-10-11", instrument = "example fixture (no physical measurement)" } }   # #269: D = 450
rail_angle_deg = 16.44             # #269: alpha; non-length nominal, example value from #269

[[fixtures.trammel-jig.solids]]
name = "hub_hole"
shape = "cylinder"
void = true
dia_mm = 8.0                       # example value (realistic): reamed 8 H7 for the hub pin
length_mm = 12.0
axis = [0.0, 0.0, 1.0]
at_mm = [0.0, 0.0, -12.0]          # drawing SPOT position only
located_by = "in_situ"

[[fixtures.trammel-jig.solids]]
name = "dowel_hole"
shape = "cylinder"
void = true
dia_mm = 6.0                       # #270 comment: Ø6 dowel tooling hole
length_mm = 12.0
axis = [0.0, 0.0, 1.0]
at_mm = [-292.0, 0.0, -12.0]       # spot only; example value (realistic)
located_by = "in_situ"

[[fixtures.trammel-jig.solids]]
name = "riser"
shape = "box"
size_mm = [320.0, 40.0, 6.0]       # #270 comment: 6 mm acetal; plan size example value
at_mm = [-310.0, -20.0, 0.0]
located_by = "in_situ"             # profile cut by the jig itself (C3)
```

### 9.2 Plan (sketch)

```toml
[commissioning]
fixture = "trammel-jig"
scope = "install"
batch_qty = 20
batch_qty_cite = "harmonic-analyzer/cad/config/parts/rocker-arm.yaml:5"
renew_when = "rails unclamped or moved; carrier, pins or riser replaced; carrier dropped"
record = "../records/trammel-jig.toml"

[[commissioning.setups]]           # C1: zero and align both rails
id = "C1"
machine = "PM-30MV"
frame = "CT"
stock_in = "fixture.trammel-jig"
[commissioning.setups.zero.x]
method = "spindle"                 # new AxisZero form: zero on the spindle axis
[commissioning.setups.zero.y]
method = "spindle"

[[commissioning.setups.ops]]
op = 20
do = "align"                       # set: tap the rail to the printed targets; nothing recorded
readings = { element = "rail_a.pin", stations_mm = [50, 100, 150, 200, 250, 300, 350, 400], role = "set" }
gauge = "coax-indicator"
tolerance_mm = 0.03
tolerance_cite = "#270: rail pin within 0.03 of its predicted target"

[[commissioning.setups.ops]]
op = 30
do = "torque"
torque = { fasteners = "rail A T-slot studs", element = "rail_a.pin", count = 4, value_nm = 40.0, passes = [0.5, 1.0], sequence = "centre outward", wrench = "torque-wrench", cite = "example value (realistic, not a shop measurement)" }
# gauges.torque-wrench: range_nm = [10.0, 60.0], example value (realistic, not a shop measurement); 20 and 40 N·m lie inside it

[[commissioning.setups.ops]]
op = 40
do = "align"                       # verify after torque: these readings go in the record
readings = { element = "rail_a.pin", stations_mm = [50, 100, 150, 200, 250, 300, 350, 400], role = "verify" }
gauge = "coax-indicator"
tolerance_mm = 0.03
tolerance_cite = "#270: rail pin within 0.03 of its predicted target"
# predicted @400: (-395.890, -57.191) per #270; the rules compute it from the guide

# ops 50/60/70: rail B, likewise (set, torque, verify)

[[commissioning.setups]]           # C2: in-situ locator holes
id = "C2"
machine = "PM-30MV"                # every commissioning setup names its machine
frame = "CT"
stock_in = "fixture.trammel-jig"
# hold: carrier locked at the symmetric pose
[[commissioning.setups.ops]]
op = 10
do = "spot"
tool = "spot-drill-90"            # example inventory id
fixture_feature = "trammel-jig.hub_hole"
locate = { from = "guide", pose = "apex", offset_mm = [0.0, "computed"] }
[[commissioning.setups.ops]]
op = 20
do = "drill"
tool = "drill-7.8"                # example inventory id: 7.8 under the 8 H7 ream
fixture_feature = "trammel-jig.hub_hole"
[[commissioning.setups.ops]]
op = 30
do = "ream"
tool = "reamer-8h7"               # terminal: checked against the declared Ø8.0, which hub_size predicts
fixture_feature = "trammel-jig.hub_hole"
[[commissioning.setups.ops]]
op = 40
do = "spot"
tool = "spot-drill-90"
fixture_feature = "trammel-jig.dowel_hole"
locate = { from = "trammel-jig.hub_hole", offset_mm = [-292.0, 0.0] }   # example value (realistic)
[[commissioning.setups.ops]]
op = 50
do = "drill"
tool = "drill-5.8"                # example inventory id: 5.8 under the 6 H7 ream
fixture_feature = "trammel-jig.dowel_hole"
[[commissioning.setups.ops]]
op = 60
do = "ream"                        # terminal op: sets the Ø6 size
tool = "reamer-6h7"               # terminal: checked against the declared Ø6.0, which dowel_fit predicts
fixture_feature = "trammel-jig.dowel_hole"

[[commissioning.setups]]           # C3: the jig cuts its own riser
id = "C3"
machine = "PM-30MV"
frame = "CT"
stock_in = "fixture.trammel-jig.riser"
[[commissioning.setups.ops]]
op = 10
do = "finish_profile"
fixture_feature = "trammel-jig.riser.inner_edge"   # R802, on the R795 pin pair
inset_mm = 2.0                     # #270 comment: edges 2 mm inside each finished edge
part_op = "S3:20"                  # the part's finishing sweep on this pin pair (sketch id)
tool = "endmill-14"                # derived: part cutter Ø10 + 2 × 2.0
contour = { method = "guided_sweep", sweep = { guide = "trammel", fixture = "trammel-jig", pins = "inner" } }   # D3: names from #269
# op 20: fixture_feature = "trammel-jig.riser.outer_edge" (R814), pins = "outer", part_op = the outer finishing sweep

[[commissioning.setups]]           # C4: acceptance readings
id = "C4"
machine = "PM-30MV"                # dowel_position is a DRO reading: needs the travel and DRO resolution
frame = "CT"
stock_in = "fixture.trammel-jig"
[[commissioning.setups.ops]]
op = 10
do = "accept"
readings = [
  { name = "sagitta_outer", quantity = "sagitta", of = "trammel-jig.riser.outer_edge", chord_mm = 300.0, band_mm = 0.1, band_cite = "#270", claims = ["trammel-jig.riser.outer_edge.radius"] },
  { name = "sagitta_inner", quantity = "sagitta", of = "trammel-jig.riser.inner_edge", chord_mm = 300.0, band_mm = 0.1, band_cite = "#270", claims = ["trammel-jig.riser.inner_edge.radius"] },
  { name = "width", quantity = "width", of = ["trammel-jig.riser.inner_edge", "trammel-jig.riser.outer_edge"], band_mm = 0.1, band_cite = "example value (realistic, not a shop measurement)", claims = ["trammel-jig.riser.outer_edge.location"] },
  { name = "hub_pin_to_edge", quantity = "distance", of = ["trammel-jig.riser.outer_edge", "trammel-jig.hub_hole"], pin = "pin-8", contact = "near", band_mm = 0.05, band_cite = "example value (realistic, not a shop measurement)", claims = ["trammel-jig.hub_hole.position.radial"] },
  { name = "hub_apex", quantity = "dro_xy", of = ["guide.apex", "trammel-jig.hub_hole"], band_mm = 0.05, band_cite = "example value (realistic, not a shop measurement)", claims = ["trammel-jig.hub_hole.position.tangential"] },
  { name = "hub_size", quantity = "size", of = "trammel-jig.hub_hole", band_mm = [0.0, 0.015], band_cite = "example value (realistic, not a shop measurement): 8 H7 slip fit for the hub pin", claims = ["trammel-jig.hub_hole.size"] },
  # D4: the dowel hole's own readings
  { name = "dowel_position", quantity = "dro_xy", of = ["trammel-jig.hub_hole", "trammel-jig.dowel_hole"], band_mm = 0.03, band_cite = "example value (realistic, not a shop measurement)", claims = ["trammel-jig.dowel_hole.position"] },
  { name = "dowel_fit", quantity = "size", of = "trammel-jig.dowel_hole", band_mm = [0.0, 0.012], band_cite = "example value (realistic, not a shop measurement): 6 H7 for the Ø6 dowel", claims = ["trammel-jig.dowel_hole.size"] },
]
# gauge-pins: example metric set in 0.01 mm steps, finer than the 0.012 and 0.015 fit bands
# kinds: sagitta-gauge-300 = sagitta_gauge (new); calipers = caliper; coax-indicator = coax_indicator (new); gauge-pins = pin_gauge_set
checks = { sagitta_outer = "sagitta-gauge-300", sagitta_inner = "sagitta-gauge-300", width = "calipers", hub_pin_to_edge = "calipers", hub_apex = "coax-indicator", hub_size = "gauge-pins", dowel_position = "coax-indicator", dowel_fit = "gauge-pins" }
```

The rules compute the predictions. They are not authored:

- **Sagitta** of an edge of radius `R` over chord `c`: `R − √(R² − (c/2)²)`. With
  the example geometry, the riser edges are at R802 and R814 (R795 and R821 cutter
  paths with an Ø14 cutter). #270 quotes 14.12 ± 0.1 for an earlier variant. The
  engine's value replaces it.
- **Width:** `R_outer − R_inner` of the riser edges.
- **Hub-pin-to-edge:** read with calipers from the edge to the near side of
  the HUB pin (`pin = "pin-8"`, `contact = "near"`). The predicted centreline
  value is the **signed** radial offset `o = ρ_hub − R_edge`, and the printed
  target is the near-contact value `o − sign(o)·r` (§2.3). The shop records the
  signed caliper reading, which is judged against that target. `ρ_hub` is the
  hub centre's distance from the arc centre, taken from `features.toml`; `o` is
  positive when HUB lies outside the edge (away from the arc centre) and
  negative when it lies inside. The sheet prints which side is
  positive, and the shop records the value with its sign. A HUB on the wrong side
  of the edge therefore reads with the wrong sign and fails the band, instead of
  matching the mirror position `2·R_edge − ρ_hub`.
- **Dowel position:** the dowel route's `locate` offset as an X/Y pair
  (`[-292.0, 0.0]` in the sketch), read as the DRO X/Y move from the HUB pin to
  the dowel hole, each centred with the coaxial indicator.
- **Hub size and dowel fit:** the declared solid's `dia` (8.0 and 6.0). The
  band is the fit the pin or dowel needs. The terminal reamers (`reamer-8h7`,
  `reamer-6h7`) are checked against those declared sizes and bands, and an
  unmeasured reamer size leaves that check `?`.

Every claim of §3.3's table is listed by exactly the readings shown there, and
each reading lists only claims of the elements it measures, so the binding and
coverage checks pass. The reference chain runs from the root (inner) edge to the
outer edge through `width`, from the outer edge to HUB's radial position, from
the guide's apex pose to HUB's tangential position, and from HUB to the dowel in
both axes.

### 9.3 State A: record absent (the normal planned state)

`prechips check` reports:

- `commissioning C1:40/rail_a.pin@400: ? predicted (-395.89, -57.19) ± 0.03 —
  measure: C1:40/rail_a.pin@400`, and likewise for each row;
- for each dependent part setup (the setups holding on `trammel-jig`):
  `? commissioning C not recorded (N readings)`;
- exit 4.

The traveler prints C-1…C-4 with empty blanks, ahead of the part sheets.

### 9.4 State B: demonstration record

```toml
# examples/rocker-arm/records/trammel-jig.toml (demonstration fixture)
fixture = "trammel-jig"

[planned]                          # copied from the checker's printed table, §3.4
commissioning = "<sha256 printed by the checker>"
"fixtures.trammel-jig" = "<sha256 printed by the checker>"
dro = "<sha256 printed by the checker>"
"frames.CT" = "<sha256 printed by the checker>"
features = "<sha256 printed by the checker>"
"tools.endmill-10" = "<sha256 printed by the checker>"
"tools.endmill-14" = "<sha256 printed by the checker>"
"tools.reamer-8h7" = "<sha256 printed by the checker>"
"tools.reamer-6h7" = "<sha256 printed by the checker>"
"machines.PM-30MV" = "<sha256 printed by the checker>"
"gauges.coax-indicator" = "<sha256 printed by the checker>"
"gauges.torque-wrench" = "<sha256 printed by the checker>"
"gauges.sagitta-gauge-300" = "<sha256 printed by the checker>"
"gauges.calipers" = "<sha256 printed by the checker>"
"gauges.gauge-pins" = "<sha256 printed by the checker>"
"gauges.pin-8" = "<sha256 printed by the checker>"
# every input the checker's table lists for this plan; none missing, so not stale

[readings."C1:40/rail_a.pin@400"]
value_mm = [-395.884, -57.203]     # example value: inside the 0.03 band
gauge = "coax-indicator"
machine = "PM-30MV"
measured = { status = "measured", by = "example value (realistic, not a shop measurement)", date = "2026-10-11", instrument = "example fixture (no physical measurement)" }
# ... one entry per generated key ...
```

With every key present and in band, the `commissioning` findings pass, and the
part setups' roll-up passes. Their other findings are unchanged. As with every
demonstration fixture, this exercises the measured branch. It is disclosure, not
an observation.
