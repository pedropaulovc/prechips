# Design: once-per-batch fixture commissioning phase

This internal design specifies a once-per-installation or once-per-batch phase
for making and accepting fixture features before part setups use them. The new
plan-root phase is agreed but not implemented. Current `Plan` has no
`commissioning` root; its `align`, `torque` and `accept` actions, install-record
parser, dependent-setup rule, native fixture-state chain and commissioning pages
remain proposed.

The shipped trammel guided-sweep support has a different boundary. Inventory
`commissioning_record` names an external install record, and measured
`dowel_reading` supplies commissioning evidence. The trammel rule and setup
sheet require the guide to be built and commissioned outside the traveler.
Those fields do not implement this phase, parse its per-reading record or
provide its proposed claim-level acceptance.

The proposal belongs to
[#270](https://github.com/pedropaulovc/prechips/issues/270). The maintainer decided
D1, D2 and D4 through D6 on PR #275 and deferred guide interface names (D3)
to [#269](https://github.com/pedropaulovc/prechips/issues/269).

The motivating fixture is the harmonic-analyzer rocker arm's oblique-trammel
jig. The proposal originally treated it as a third `guided_sweep` guide beside
the `pivot` and `rail` guides of PR #258/#267 (`feat/255-guided-sweep`,
`feat/255-guide-pictures`). Section 4.1 retains the required guide capabilities
without imposing those historical placeholder field names.

## Current status and navigation

The sections below are a design specification. Statements about schema errors,
findings, exits, generated geometry and printed pages describe intended behavior,
not current checks or observed outputs.

- [Schema](#2-schema) defines the proposed phase, actions, readings and record.
- [Rules semantics](#3-rules-semantics) defines claim trust, dependency scope and staleness.
- [Kernel](#4-kernel) separates planned geometry from recorded evidence.
- [Traveler](#5-traveler) defines the proposed one-time pages and part-sheet stop.
- [Implementation plan](#7-implementation-plan) and [Test plan](#8-test-plan) retain delivery constraints.
- [Worked example](#9-worked-example-sketch-rocker-trammel-jig) is schematic, not a runnable bundle.
- [Open review notes](#10-open-review-notes) lists unresolved design findings.

Current implementation owners are [`model.py`](../../src/prechips/model.py),
[`rules/trammel.py`](../../src/prechips/rules/trammel.py) and
[`sheet_sweep.py`](../../src/prechips/sheet_sweep.py).
Use [architecture](../internals/architecture.md) for their roles and
[development](../internals/development.md) for contributor checks. For supported
user tasks, start with the [quickstart](../manual/quickstart.md) or
[tutorial](../manual/tutorial.md); the [CLI catalog](../reference/cli.md) and
[Python catalog](../reference/python-api.md) describe current interfaces.

## 1. Problem

Some fixture work is needed once per installation, not once per part. The
motivating trammel procedure requires:

1. zero both DRO axes on the spindle axis;
2. align each rail by reading a pin in its carriage at stations s = 50…400 mm
   against predicted DRO X/Y targets within 0.03 mm, then torque the studs;
3. drill and ream the part-locator hole (HUB) in the fixture at the real apex of
   the cutter circle, absorbing rail-angle error (0.1° moves the arc centre
   about 5 mm); then drill the Ø6 dowel tooling hole by DRO from HUB;
4. cut the jig's own support, a 6 mm acetal riser screwed to the carrier, on both
   pin pairs with a cutter 4 mm larger than the part cutter. Each riser edge then
   lies 2 mm inside the matching finished edge;
5. read the riser (sagitta over a 300 mm chord, width, hub-pin-to-edge distance)
   as the acceptance check before any part is loaded.

Per part, only the blank load, two passes and a pin-pair swap remain.

The current plan cannot own steps 1 through 5 as a separate phase. Repeating
them on every part sheet obscures their installation lifetime; omitting them
leaves the plan relying on nominal fixture-drawing locations for HUB, the
dowel and the riser. The in-situ steps exist because those finished locations
must follow the installed guide, not the drawing nominal.

## 2. Schema

### 2.1 Where the phase lives

The proposal adds optional root `commissioning` with its own setup list.
It does not add a flag to ordinary setups. This schematic TOML fragment
contains `...` and is not runnable:

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

The alternative `Setup.phase = "commission" | "part"` was rejected. It is not
an accepted input field or an extension proposed here. A separate list keeps
three boundaries explicit:

- Commissioning works on the fixture, not part stock. Its setups never take
  `stock_in` from plan `stock` or part setups; part setups never take it from
  commissioning setups. A separate list makes this separation structural.
- The phase prints once before part sheets, in its own authored order (§5).
- `stock_ancestry`, `stock_routes` and joint validation retain their existing
  meaning for part `setups`.

Commissioning otherwise reuses `Setup`: `machine`, `frame`, `hold`, `zero`,
`stock_state`, `coolant` and `ops`. Every commissioning setup must name a
`machine`; omission is a schema error.
Every `align` and `dro_xy` reading is judged against that machine's DRO
resolution and travel (§2.3), and the block's single installation is on that
machine. The literal `"unknown"` is accepted and leaves every machine-dependent
finding `?`. Every existing per-op rule
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

The proposed actions extend ordinary `Operation` records. They are valid only
inside `commissioning.setups`; using them in part setups is an error.

| `do` | Purpose | Fields |
|---|---|---|
| `align` | read one guide element against predicted DRO targets | `readings` (exactly one `ReadingSet`, §2.3; a second element is a second `align` op), `gauge`, `tolerance_mm` / `tolerance_in`, `tolerance_cite` |
| `torque` | tighten named fasteners in a stated order | `torque` (`TorqueStep`) |
| `accept` | acceptance readings on a commissioned fixture feature | `readings` (a list of `Reading`), with `checks` naming the gauge per reading |

In-situ machining reuses existing `drill`, `ream`, `spot` and `finish_profile`
actions. The proposed `fixture_feature` field replaces `feature` for those
operations (§2.4).

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

A torque target is a shop/vendor number, not a measured length. It requires
a citation or the AGENTS.md example-value disclosure. Unknown remains `?`.

Every pass value (`value × fraction`, so 20 and 40 N·m for `[0.5, 1.0]` of 40)
must lie inside the wrench's range. A pass value outside it is an error, for
example a 2 to 24 N·m wrench named for the 40 N·m step. A wrench with no range, or
one whose range carries no citation, leaves the step `?`. A trusted `steps`
entry cannot override a range failure or missing evidence.

An `align` tolerance is an authored limit, like `Hold.align`'s `limit_mm`. It
must be strictly positive (0 or negative is a schema error), and it needs
`tolerance_cite`: the part band it protects, a vendor figure, or the
author's reasoning. An uncited tolerance leaves every reading of that op `?`
("alignment tolerance uncited"), never a pass against an invented threshold.

### 2.3 Readings: predicted values, never authored answers

Rules must compute predicted readings from geometry. The author specifies what
to read and its permitted deviation, never the prediction itself. D6 permits
optional `expect` only as a cross-check:

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

Tightening can move a rail. Both torque and a `role = "set"` alignment count as
adjustments to the named guide `element`. Each adjusted element must have a
`verify` alignment after its last adjustment in the same setup. A later `set`
or torque invalidates that verification, so torque → verify → set is an
error. A `set` operation prints adjustment targets but generates no record keys.
The [open review notes](#10-open-review-notes) also require verification for
used guide elements when no adjustment was authored.

A `verify` set needs at least two distinct stations within the element's sweep
travel, spanning at least half of that travel. One station cannot detect a
rail rotated about it. Empty, single-station and shorter-span sets are errors.
Until the guide exposes its travel (§4.1), the result is `?`. The sketch's
50…400 mm stations span 350 mm of about 350 mm travel.

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
| `pin` | `str`: the inventory `pin_gauge` a `distance` to a hole is read over. Required for that case and refused for any other reading. A `dro_xy` to a hole centres the indicator on the bore itself, never on a pin, so a pin's fit never enters a position reading |
| `contact` | `"near"` or `"far"`: the side of the pin the gauge touches. Required with `pin`, refused without it |
| `chord_mm` / `chord_in` | `float` (`sagitta` only): nominal chord printed on the sheet. Compute the prediction from the gauge's measured chord instead. Nominal must be within 1 % of `chord_limits` and satisfy `0 < chord < 2R`, otherwise error naming the values. Measured limits reaching `2R` are uncertainty, leaving `?`, not a plan error. Unknown `R` leaves both checks `?`. |
| `band_mm` / `band_in` | `Vector` `[low, high]` relative to the prediction, with `low < high` and `low ≤ 0 ≤ high` (the prediction itself is acceptable), or a symmetric `float` greater than 0. Anything else is a schema error |
| `band_cite` | `Citations` |
| `expect_mm` / `expect_in` | optional authored cross-check (above), one spelling. It takes the same shape and unit as the recorded value: a `float` for scalar quantities, `[x, y]` for `dro_xy`. The mismatch test uses the reading's own comparison: the distance from `expect` to the predicted interval (sagitta's included), measured on the component the reading judges (the tangential component for `hub_apex`), must not exceed the tolerance |

Each reading's key is `"<setup>:<op>/<name>"`.

The band is an authored acceptance limit, not a measurement. Cite the protected
part tolerance or the author's reasoning; an uncited band leaves `?`.

Every generated record key must be unique. One entry must not answer two
readings, so validation rejects:

- two readings with the same `name` in one `accept` op;
- a station listed twice in one `ReadingSet`;
- two commissioning setups with the same `id` (setup ids are already unique
  across the plan, §2.1).

Each collision is an error naming the duplicated key.

A reading must name a compatible inventory `gauges` item, through the `align`
operation's `gauge` or the `accept` operation's `checks`. The
[inspection rules](../rules-inspection.md) use the same quantity/kind principle.
The proposed mapping includes existing kinds and the new kinds named below:

| Quantity | Compatible gauge kinds |
|---|---|
| `align`, `dro_xy` (centring under the spindle) | `dial_test_indicator`, `coax_indicator` (new). An edge finder is a `tools` item, not a gauge, and cannot centre on a pin, so it is not accepted |
| `sagitta` | `sagitta_gauge` (new: a chord bar with an indicator). Its chord is a new inventory field, `chord_limits_mm` / `chord_limits_in` (one spelling), a fact-local `MeasuredLimits` `[least, greatest]` with its own `measured` record. The limits are the chord's measured uncertainty, so no resolution is invented. An unmeasured or flagged chord leaves the reading `?`. A bare indicator is not accepted, because nothing would fix the chord. The gauge is digested like any named gauge (§3.4) |
| `width`, `distance` | `caliper`, `micrometer`, `height_gauge`. For a hole distance, require measured inventory `pin_gauge` as `pin` and `contact = "near"` or `"far"`. Other readings must not name them. The signed contact and pin-clearance requirements below apply. |
| `size` of a hole | `pin_gauge_set`, `bore_gauge` (an external micrometer never measures a bore) |
| `z` | `height_gauge`, `dial_test_indicator` |
| torque `steps` | `torque_wrench` |

#### Pin contact and clearance

For a hole distance, move the predicted centreline offset `o` toward the
reference by pin radius `r` for the near contact, or away for far contact:
`o − sign(o)·r` and `o + sign(o)·r`. A hole inside the edge has negative `o`,
so its near target is `o + r`, not `o − r`.

The pin can move within the bore by radial play `p = (bore − pin)/2`.
Use the upper end of the trusted hole-size interval for bore size and the
measured pin diameter; widen the reading interval by `± p`. The pin must fit
every accepted bore: its greatest measured diameter must not exceed the size
interval's lower end. A bore accepted as `[8.000, 8.010)` with an 8.005 pin is
a plan error. Untrusted hole size, or a size reading later in authored order,
leaves `p` unknown and the distance reading `?`.

The pin must lie wholly on one side of the edge over the accepted range:
every `o + band`, widened by reading uncertainty, must satisfy `|offset| > r`.
At `o = 4.01`, `r = 4.00` and a ±0.05 band, the range reaches 3.96, so the
plan is invalid. Where `|offset| ≤ r`, including `o = 0`, near and far are
undefined; use `dro_xy` instead.

Print the signed target and contact side. The record holds that signed contact
distance, judged directly against the target, with no conversion back to
centreline. Gauge range covers the magnitude: a −3.2 target needs a caliper
covering 3.2. An untrusted pin diameter leaves `?`; include the pin in
`[planned]` digests.

#### Gauge and machine range

An incompatible kind is an error even if range and resolution are sufficient.
Pin gauges cannot measure sagitta, and calipers cannot centre a bore. No record
entry can override that error. Range requirements then depend on which device
produces the value:

- For a DRO coordinate (`align`, `dro_xy`), the machine supplies the value.
  The coaxial or dial test indicator centres the element under the spindle.
  The predicted coordinate must lie inside the
  commissioning setup's machine travel, and the DRO resolution must be no
  coarser than the tolerance or band. `machines.<id>.envelope.travel` is a
  stop-to-stop stroke, not a coordinate bound, so the check is collective, and it
  is made in one frame. A relational reading's DRO value is relative to its
  reference (`hub_apex` from the apex pose, `dowel_position` from HUB), so the
  rules first place every position visited in one frame: the
  zero, each reference across its full accepted position set, and each
  subject at its reference's accepted set plus its own offset, composed along
  the chain. A dowel ±0.03 from a HUB that may sit ±0.05 out spans ±0.08.
  Collect positions across all commissioning setups in one installation.
  C1 at X −400 and C4 at X +400 need 800 of stroke even though each setup alone
  spans 400. Every setup in the block must name the same machine and
  resolve to the same fixture installation transform (the composed
  `frame` and `hold.pose` for the installed base); a different machine or
  installation transform is a schema error. Carrier motion along the guide is
  not a moved installation: it is modelled by the guide's named poses on top of
  that one transform. Moving the fixture to another machine is
  a new installation, with its own `commissioning` block and record. Each visited
  position counts at its outer extent: its prediction interval widened by
  its acceptance band. Nominal endpoints at −400 and +400 with a 0.02 band need
  800.04, which an 800 stroke does not have. On each axis, the span from the least to
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
- For every other quantity (`sagitta`, `width`, `distance`, `size`, `z`), the
  gauge supplies the value. Its range must cover the complete acceptance
  interval, `[predicted + low, predicted + high]`, plus one resolution step
  beyond each end, so that a value past either limit reads as past it rather
  than as the gauge's last step. Its resolution must be no coarser than the
  band. For a limit-style gauge (a pin set read as the largest pin that enters),
  the set must hold a pin at or below the low limit, a pin at or above the high
  limit, and one past each. A pin set ending at 8.000 therefore cannot judge
  HUB's `[8.000, 8.015]`: an oversized hole would still read 8.000.

Validate the combined measurement and prediction interval as well. Measurement
uncertainty is `(r_dro + r_g)/2` either side for `align`, or `r_g + r_dro` for
relational `dro_xy`. Add prediction half-width from the guide budget, chord
limits and pin terms. A passing residual can exist only when
`high − low ≥ 2·(u_measure + u_predict)`. It need not be centred on nominal:
`[0.000, 0.015]` with ±0.005 is feasible, and +0.0075 passes. An infeasibly
narrow band is a schema error, not permanent `?`. A 0.05 band with both
resolutions at 0.03 gives ±0.06 and is rejected, as is a ±0.05 band with
±0.03 prediction uncertainty and ±0.03 measurement uncertainty.

An unresolved or untrusted gauge or machine fact leaves the reading `?`. A gauge
or DRO too coarse for the band, or a target outside the travel, is an error.

### 2.4 In-situ fixture features

The proposed solid field `located_by` distinguishes drawing and in-situ location.
This inventory fragment is proposed schema, not currently accepted syntax:

```toml
[[fixtures.trammel-jig.solids]]
name = "hub_hole"
shape = "cylinder"
void = true
dia_mm = 8.0                       # reamed size from the drawing
at_mm = [0.0, 0.0, 0.0]            # drawing nominal: where the SPOT goes
located_by = "in_situ"             # "drawing" (default) | "in_situ"
```

- `located_by = "drawing"` (default) preserves ordinary drawing-based location.
- `located_by = "in_situ"` makes `at_mm` the drawing's spot position only.
  The commissioning route determines the planned finished location.

An in-situ solid's route comprises every commissioning operation naming
`fixture_feature = "<fixture>.<solid>"` or
`"<fixture>.<solid>.<edge>"`, in authored order. A hole usually has spot,
drill and ream; the riser has a sweep for each edge. Require:

- at least one op in the route; an `in_situ` solid with none is an error;
- exactly one `locate` per located element: on the first op of a hole's route,
  which later ops inherit (a later op with its own `locate` is an error); and on
  each edge's own sweep for a profile, which is located by its guide pose;
- every op of one hole's route in the same commissioning setup, so the hole is
  never re-located between ops. A riser's edges may be cut in one setup or two;
- the last size-setting operation is terminal; earlier operations are roughing.
  The declared solid remains the target. HUB's `dia = 8.0` supplies its `size`
  prediction, with the reading band applied once. The terminal tool's measured
  size interval must fit `declared diameter + band` (8.000 to 8.015 for
  HUB). A measured 8.005 reamer passes; the band is not applied a second time. A 9 mm reamer named
  for the 8 mm `hub_hole` is an error, not a 9 mm prediction. An unmeasured tool
  size leaves that check `?`. The kernel cuts the declared size.

A part setup that relies on an `in_situ` solid that the plan has no route for is
an error, not debt: the plan is incomplete.

The first hole-route operation uses the proposed `locate` union. These are
alternative schematic fragments, not one runnable TOML document: the duplicate
key intentionally shows both forms.

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

Derive the riser cutter as `dia = part_cutter_dia + 2 × inset_mm`. Its
`part_op = "S3:20"` binds it explicitly to the finishing `guided_sweep` on the
same pin pair and matching part edge; do not infer that binding. Reject a
rough sweep or a different pin pair. If several finishing sweeps set the same
edge, all must resolve to one cutter diameter, otherwise report each conflict.
Rough sweeps do not determine the finished edge and are excluded. The named
tool must match
within the DRO resolution, or the result is an error naming both diameters. An
unknown part cutter leaves the check `?`. This keeps the 4 mm figure honest if
the part cutter ever changes (and that change is a renewal trigger, §3.5).

New `stock_in` form for commissioning setups:

- `"fixture.<id>"`: the installed fixture's solids, posed by `hold.pose`;
- `"fixture.<id>.<solid>"`: one fixture solid as the work, for the riser blank.

These forms are refused in part setups.

### 2.5 Per-part setups referencing the phase

The proposed dependency is derived; part setups add no new field. A setup
depends on commissioning when:

- its `hold.fixture` (or `stop_fixture`) is `commissioning.fixture`;
- any solid it locates against, poses on or clears is an `in_situ` solid;
- it runs a `guided_sweep` whose `sweep.fixture` is the commissioned fixture.

A setup cannot avoid the check by omitting a reference. The proposal deliberately
has no optional `hold.commissioning = "C"` because it would duplicate that
dependency as a second source of truth.

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

The shop keeps readings in a separate installation-state record, named by
`commissioning.record` relative to the plan, like `paths.inventory`. This
proposed record fragment contains placeholder identities and evidence:

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

A separate file preserves these lifetimes and identities:

- Taking a reading must not change the authored plan.
- Inventory describes reusable kit; installation readings must not survive into
  the next installation after the rails come off the table.
- The record is an input whose digest enters the report's input table.
  Re-commissioning therefore changes report identity and stales a first-article
  approval ([approval contract](../report-and-telemetry.md)). Approval of one
  installation says nothing about its replacement.

A `readings` entry uses one spelling, `value_mm` or `value_in`, matching the
reading's band (`band_mm` requires `value_mm`). Other combinations are schema
errors. Its shape follows the quantity:

- a `float` for `sagitta`, `width`, `distance` (the signed contact value), `size`
  and `z`;
- `[x, y]` for `align` and `dro_xy`.

A `steps` entry (torque) holds no value. Both kinds carry `gauge`, and where
§2.3 requires them, `machine`, `pin` and `contact`, plus `measured`.

Entries reuse `Measurement` and the trust rules in `measurements.py`.
Only `status = "measured"` with complete `by`, `date` and `instrument` qualifies.
`assumed`, `illustrative`, omitted status or `verify = true` is debt.
`by` records attribution and does not alter trust.

`_trust` does not read `instrument` prose, so it cannot tell which gauge was
used. Each entry therefore also carries a structured `gauge`: the inventory id
of what took the reading (or of the wrench, for a `steps` entry). It must equal
the gauge the plan names for that key: the `align` op's `gauge`, the `accept`
op's `checks` entry, or the `TorqueStep`'s `wrench`. A reading read over a pin
also records its `pin` id and its `contact` side, which must equal the
reading's planned `pin` and `contact`, because both enter the prediction. On the
wrong side, a hole at `o − 2r` reads the planned near target from the far side. A DRO-derived entry (`align`,
`dro_xy`) also records its `machine` id, which must equal the commissioning
setup's machine, because that machine's DRO resolution and travel enter the
judgement. A missing or different `pin`, `contact` or `machine` leaves the entry `?`,
naming both. A missing or different
`gauge` leaves the entry `?`, naming both ids ("taken with calipers, planned
gauge-pins"). The capability checks of §2.3 therefore always describe the
gauge that actually took the reading. `instrument` stays attribution.

D1 selects this separate record and equipment binding.

Missing `record`, a missing file or an absent entry is the normal planned
state: each reading remains `?`. The proposed checker prints the current
`[planned]` digest table in the report and commissioning sheet for the shop
to copy. It must never write the shop record. A key not generated by the plan
is an error, so a typo cannot silently leave the intended reading unanswered.

## 3. Rules semantics

### 3.1 New rule `commissioning`

The proposed rule emits one finding per reading, torque step and in-situ
operation, plus a roll-up for each dependent part setup. Reading outcomes are:

| Prediction | Record entry | Result |
|---|---|---|
| unknown (an input fact is missing or untrusted) | any | `?`: the prediction's own `measure:` debts, plus "reading cannot be judged" |
| known | absent, or an untrusted `Measurement` | `?`: `measure: <key> — <what>, predicted <value> ± <tol>` |
| known | trusted, deviation inside the band | pass |
| known | trusted, deviation outside the band | `✗`: names the reading, the prediction, the band and the excess |

Compare signed deviation `d = read − predicted` with `[low, high]`, inclusive.
A symmetric float `b` means `[−b, b]`; an alignment tolerance `t` means
`[−t, t]`. Preserve one-sided fit signs: for `hub_size`, a 7.990 reading
against 8.000 with band `[0.0, 0.015]` is undersize (`d = −0.010`) and fails.
For ordinary `dro_xy` and `align`, judge each axis. The exception is a
guide-located `position.tangential` (`hub_apex`), whose residual must be
projected onto the guide frame and judged tangentially (§3.3).

The gauge's measured chord interval `chord_limits = [least, greatest]` maps
through `R − √(R² − (c/2)²)` to a sagitta prediction interval. Subtract that
whole interval from the gauge-step reading interval and require the result
inside the band. A chord interval reaching `2R` leaves `?`. Near `c = 2R`,
sensitivity is high: at `R = 100`, chords 200.00 and 199.99 differ by about
1 mm of sagitta. Propagating uncertainty avoids treating those chords as
equivalent. The example's 300 mm chord on R ≈ 800 is far from this region.

Judge each recorded value over its measurement interval, not as an exact number:

- an indicating gauge of resolution `r`: `[read − r/2, read + r/2]`;
- a DRO coordinate read from the zero (`align`): two devices contribute, so
  their half-steps add up. With DRO resolution `r_dro` and centring-gauge
  resolution `r_g`, the interval is `[read − (r_dro + r_g)/2, read + (r_dro + r_g)/2]`;
- a relational DRO displacement (`dro_xy` from a reference): the reading is
  the difference of two positions, each centred and each read on the DRO. Both
  ends contribute, so the interval is `read ± (r_g + r_dro)`. Both
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

Torque passes only with a trusted `steps` entry. Ordinary rules judge drilling
and reaming, but acceptance readings alone can establish their in-situ
location (§3.3).

A prediction is a planned target, never measurement evidence. Print it on the
sheet, but never write it into the shop record, read it back as a reading or
judge a value against itself. Missing evidence cannot become a pass.

### 3.2 Gate on dependent part setups

Each dependent part setup gets one finding covering:

- the setup's consumed claims (§3.3), each through the readings that list it,
  plus the claims and readings of each one's reference chain back to the root;
- the guide prerequisites for the guide elements the setup uses: the `align`
  readings and torque steps of each element its sweeps ride, or that locate an
  in-situ claim it consumes. On the trammel every sweep rides both rails, so
  every rail reading applies. On a fixture with independent guide elements, an
  element the setup never uses is outside its scope;
- the riser cut and its readings, when the setup holds on the riser.

Readings of claims the setup does not consume are outside its scope. A missing
dowel reading therefore does not block a setup that never locates on the dowel.
Within that scope:

- any finding in scope `✗` → the part setup's finding is `✗`, and its sheet
  prints a STOP: "commissioning C failed: <keys>";
- else any `?` in scope → the part setup's finding is `?`, with every outstanding key
  listed: "commissioning C not recorded: C1:40/rail_a.pin@50 … C4:10/width";
- else pass.

Other part-setup findings continue to judge planned geometry (§4). The roll-up
alone carries commissioning debt, avoiding duplicate unknowns for one missing
reading while retaining a visible stop on each dependent setup.

D2 requires the future `commissioning` rule in `ALWAYS_REQUIRED`
(`findings.py`), so policy cannot waive it. Missing, untrusted or stale readings
would exit 4; failed readings or `expect` mismatches would exit 2. A plan
without a `commissioning` block must retain its findings and exits. Example
validator exits change only when that example gains the block. The current
registry has no such rule.

### 3.3 Which reading trusts which in-situ feature

Trust belongs to a claim, not an entire feature. Listing a feature in `of`
does not itself establish anything. Element kind determines a fixed claim set:

| In-situ element | Claims | Quantities that can establish each claim |
|---|---|---|
| hole (a `void` cylinder) | `size`, and `position` (split into `position.radial` and `position.tangential` when guide-located) | `size`: `size`. `position`: `dro_xy` only. `position.radial`: signed radial `distance` to a swept edge, positive away from arc centre. `position.tangential`: `dro_xy` from the guide pose. |
| swept edge (`<solid>.<edge>`) | `radius`, and `location` unless it is the root edge | `radius`: `sagitta`. `location`: `width` or `distance` |

The first edge cut in route order is the root edge. The guide cuts it on a
pin pair also used for the part, and it defines the reference frame for other
claims. It has only `radius`; every other swept edge also has `location`
relative to that root.

A reading may claim only properties of the element it actually measures:

- a single-subject quantity (`sagitta`, `size`, `z`) has one `of` entry, and may
  list only that element's claims;
- a relational quantity (`distance`, `width`, `dro_xy`) has exactly two `of`
  entries, `[reference, subject]`, because one value measures one relationship.
  It may list only the subject's claims, never the reference's. A reading with
  more entries is an error, so one scalar can never cover two holes;
- each listed claim must also accept the reading's quantity, per the table above.

A `size` reading of `hub_hole` cannot claim `dowel_hole.size`, and `z` cannot
claim position; both are errors.

Hole `position` is two-dimensional. Only a referenced `dro_xy` pair fixes
both axes and the side. Distances cannot establish it: two distances admit a
mirror image across the reference line. Adding a third reference would add
ambiguities for validation to resolve. A position claim listed by `distance`
is an error naming that claim.

A hole located from the guide (`locate.from = "guide"`, HUB) has its position
split into two claims, each read against what it must match:

- `position.radial`, HUB's distance from the arc centre relative to the cut
  edge, read as a signed `distance` to a swept edge. This ties HUB to the real
  arc, which is why HUB is drilled in situ;
- `position.tangential`, HUB's placement along the arc, read as a `dro_xy` from
  the guide's `apex` pose. With the carrier locked at the apex, the coaxial
  indicator is swept around the HUB bore itself, with no pin in it, until
  it is centred under the spindle, and the DRO is read. The residual
  `read − predicted` (and its uncertainty interval) is projected onto the
  guide's radial/tangential frame at the apex, and only the tangential
  component is judged against the band. The X and Y components are never judged
  separately, because the tangent is generally rotated from the setup axes (at
  45°, a tangential error of 1.2 × band shows as about 0.85 × band on each
  axis). The radial component is left to `hub_pin_to_edge`. A HUB shifted along the arc,
  with the dowel shifted by the same amount, leaves the radial reading and the
  HUB-to-dowel reading unchanged. Its parts would still cut true radii, but each
  would sit off-centre in the carrier's sweep window (±6.5° for the trammel)
  and on its riser support. Only this reading catches that.

A guide pose (`"guide.apex"`) may be a relational reference, like the root
edge: the guide defines it. The dowel then fixes the part's rotation about HUB,
and its own position (two axes, from HUB) is a claim.

A relational reference must be the root edge or an element with covered
relational claims. Its chain must reach the root without a cycle. For the trammel:

- `width` puts the outer edge relative to the root (inner) edge;
- `hub_pin_to_edge` puts HUB's radial position relative to the outer edge, as
  a signed offset (inside or outside the edge), which is what the in-situ HUB
  exists to match;
- `dowel_position` puts the dowel hole relative to HUB, in both axes (`dro_xy`).

Every consumed claim needs at least one compatible, correctly bound acceptance
reading. Missing coverage is an error, such as "in-situ claim
trammel-jig.dowel_hole.size has no acceptance reading", because no future
record could clear it.

Trust requires every listed reading to pass and, for relational claims, the
reference's claims to be trusted recursively back to the root. The roll-up
includes both consumed claims and their full reference chains. A setup that
locates only on the dowel is still blocked by missing HUB position evidence.

Readings must describe final geometry. Within one `accept` operation, use
`readings` array order; a pin reading must follow its hole-size reading.
Every reading must also follow the last operation that can alter its subject
or reference, including route operations, swept-edge cuts and guide
adjustments. Order is setup order, then authored position in `ops`, never
numeric `op` id ([execution order](../plan.md)). Apply that order to routes
and adjustments too. `hub_size` after drilling but before terminal reaming
is an error and cannot establish a claim.

The trammel's claims and readings (decision D4 adds the dowel's two):

| Claim | Reading |
|---|---|
| `riser.inner_edge.radius` (root), `riser.outer_edge.radius` | `sagitta_inner`, `sagitta_outer` |
| `riser.outer_edge.location` | `width`, from the inner edge |
| `hub_hole.position.radial` | `hub_pin_to_edge`, from the outer edge |
| `hub_hole.position.tangential` | `hub_apex`: `dro_xy` from the guide's apex pose, HUB bore centred under the spindle with a coaxial indicator, carrier locked at the apex |
| `hub_hole.size` | `hub_size` (largest gauge pin that enters) |
| `dowel_hole.position` | `dowel_position`: `dro_xy` from the HUB bore to the dowel bore, each centred with a coaxial indicator |
| `dowel_hole.size` | `dowel_fit`: largest gauge pin that enters, predicted from the declared Ø6.0 and banded by the dowel's fit |

### 3.4 Staleness

The proposed `[planned]` table has one SHA-256 per consumed planned input,
following the approval record's `[inputs]` pattern:

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

The checker must print exactly that input set and compare it with the record:

- a digest that differs names that input as changed;
- an input in the current table but missing from the record is named as new,
  because the record was taken without it. This differs from approvals, which
  skip an omitted input: a commissioning record must cover everything its
  predictions use;
- an input only in the record (no longer consumed) is ignored.

A changed or new input makes every entry stale, including torque completion.
Report `?` with "install record no longer matches the plan: <changed and new
inputs> changed. Re-commission." Changing a torque target or wrench must not
leave old completion trusted. As with stale approval, the record cannot
establish evidence for a plan it was not taken against.

### 3.5 Renewal triggers the rules can see

The proposed rule can detect planned-input changes and batch limits, but cannot
observe physical renewal events:

- a planned digest changed (§3.4), which covers a part-cutter change, a moved
  rail angle or pin spacing, and a changed riser inset;
- `quantity > batch_qty`, for either scope: one run covers only `batch_qty`
  parts. The traveler prints `runs = ceil(quantity / batch_qty)`, and the rule
  emits a `warn` naming the run count (decision D5). prechips does not track runs
  or parts, so the warning stays while the condition holds; it is not debt, and
  it does not change the exit code;
- triggers it cannot see (`renew_when`) are printed only.

### 3.6 Interaction with existing rules

The proposed checks are assigned as follows. Implementation must also resolve
the cutting/sweep travel extent finding in [open review notes](#10-open-review-notes).

| Check | Against | Where | Failure |
|---|---|---|---|
| Every visited DRO position (`align` targets, `dro_xy` subjects with their composed reference chains, zero and check-jogs), at outer extent | the commissioning machine's per-axis stroke, collectively across all setups of the installation | §2.3 DRO coordinate | span longer than the stroke → error; unmeasured stroke → `?` |
| DRO resolution | the tolerance or band | §2.3 | too coarse → error |
| Torque pass values (`value × fraction`) | the named wrench's `range_nm` / `range_in_lbf` | §2.2 `torque` | outside → error; no range or uncited range → `?` |
| Gauge-read quantities | the gauge's range over the acceptance interval plus one step each side | §2.3 | not covered → error |
| Machine identity | one `machine` per block, named on every setup | §2.1, §2.3 | omitted or two machines → schema error |

- `zero_recipe` and `travel`: commissioning setups are ordinary setups. A
  setup made only of `align` and `torque` ops has no cutting op, so it needs only
  the zero its readings use: both axes on the spindle axis. That is a new
  `AxisZero` form, `zero.x = { method = "spindle" }` (and the same for `y`). It
  replaces the edge-finding fields: `edge`, `edge_mm`, `from` and `tool` are
  refused with it, and no other field is required. It is printed as "zero X and
  Y here; this is the crossing point".
- `guided_sweep` on the riser: the existing rule, with the trammel guide (#269).
  `headroom`/`travel` debts for the moving fixture apply as on part setups (#272).
- `inspection`: the `accept` readings are not part requirements, and they never
  satisfy a part requirement's `checks`. The first part is still a first article
  under the existing approval flow.

## 4. Kernel

### 4.1 What the phase needs from a guide (#269 interface)

The phase requires four guide capabilities. Analytic predictions belong in
ordinary rule arithmetic and do not require a native kernel run:

1. Station targets: predicted DRO X/Y for element `e` at station `s`, with
   the DRO zeroed at the crossing point. For a trammel whose rail
   lines cross at the spindle at ±α/2 about the guide axis, this is
   `s·(cos θ, sin θ)` with `θ = θ₀ ± α/2`.
2. Named poses: carrier pose with the cutter centre at the arc apex
   (`"apex"`), as a transform from the carrier frame to the setup frame.
3. Pin-pair geometry: cutter-centre radius `D / (2 sin α)` and arc centre
   in the carrier frame.
4. Required error budget: change in each predicted target, radius
   and arc centre per unit of each guide fact (carriage-pin clearance, rail
   angle, pin spacing), with each fact's measured uncertainty. An `align`
   reading's interval widens by the target uncertainty this budget gives, so a
   pin centre inside the 0.03 band cannot pass while the guide geometry is
   outside it. The same budget feeds every prediction derived from the
   guide: the sagitta, width and hub-pin-to-edge predictions widen to intervals
   by the radius and arc-centre uncertainty it gives, alongside their own chord
   and pin terms. Any guide fact the budget needs that is missing or unmeasured
   leaves the dependent readings `?`. It is never treated as zero.

The guide owns its field names. The adapter must expose these capabilities as
functions of declared, measured facts. An unmeasured required input makes
the dependent prediction unknown; it is never zero uncertainty.

### 4.2 Geometry the kernel does need

The proposed kernel must build planned geometry only. Recorded readings must
never enter `engine_job`.

- Keep one accumulated fixture state, a set of named solids, for the
  commissioned fixture. Start with posed inventory solids through `_solids()`,
  but omit all `located_by = "in_situ"` voids. Subtracting them at authored
  `at_mm` before the route runs would create both a drawing-spot hole and a
  route-cut hole. Until the route cuts it, an in-situ void is only a spot mark
  without depth. Each commissioning setup reads and updates the same state:
  - `stock_in = "fixture.<id>"` takes the whole current state as its work. Its
    result replaces the whole state, so C2's holes stay in it;
  - `stock_in = "fixture.<id>.<solid>"` takes only that solid from the current
    state. Its result replaces only that solid, and every other solid, C2's
    holes included, carries over unchanged. The cut riser goes back into the
    state where the blank was;
  - a setup that cuts nothing (C1, C4) leaves the state unchanged.

  Cut in-situ voids at the planned location: the `locate` result
  in setup coordinates, not the spot `at_mm`. The riser is cut by the
  guided-sweep removal on the riser blank. In the sketch, C4 reads the state
  after C2 and C3, holes and cut riser together.
- Add job output `commissioned[<fixture id>]` for the accumulated fixture state
  after the final commissioning setup. Part setups using `hold.fixture`
  take components from that state rather than rebuilding inventory primitives.
  Clash, contact and clearance must see both the cut riser and planned holes.
  Resolving `hold.stop_fixture` through this state is also required by the
  [open review finding](#10-open-review-notes).
- Use accepted geometry envelopes for clash and clearance. An in-situ component
  can pass anywhere within its acceptance band and must not be treated as exact
  nominal geometry.
  - For swept edges, a sagitta band is not a radial offset. At `c = 300`,
    `R = 802`, a ±0.10 sagitta band allows roughly −5.5/+5.6 mm of radius, so
    the envelope never treats it as a radial offset. The edge is pinned at the
    apex by its location readings (`hub_pin_to_edge`, `width`). The accepted
    sagitta interval is inverted through the sagitta formula, with the
    chord limits, gauge interval and guide budget included, to radius bounds
    `[R_min, R_max]`. The envelope is the region swept by every arc of radius in
    that range that passes through the apex location band, evaluated exactly over
    the edge's whole length. No quadratic approximation is used, and the bound
    stays conservative far beyond the measured chord. At 600 mm from the apex on
    R802 with c = 300, a ±0.10 sagitta moves the edge about 2.8 mm. The envelope
    is offset toward the part, the worst case for clearance;
  - For holes, keep worst-case material: intersect all accepted voids. Shrink
    the void to the size band's lower end, then by the absolute accepted
    position set. Never grow it for a clearance check. Compose the set
    recursively along the reference chain, including reference rotation.
    With HUB within ±0.05 and the dowel within ±0.03 of HUB, shrink by at least
    0.08, not 0.03. An accepted Ø8.000 to Ø8.015
    hole is modelled as Ø8.000 less its position band, so a Ø8.010 object in it
    is never reported clear.

  Contact needs the opposite, guaranteed-material envelope: material present
  in every accepted placement, with edges offset away from the part and holes
  grown. The clearance envelope alone could show contact for only some
  placements. Prove contact only when the guaranteed envelope touches;
  otherwise keep contact `?`.

  The envelope depends only on the plan, never on the record, so cache keys stay
  record-independent (§4.3). A riser edge 0.05 from a cutter path with a ±0.10
  band therefore reads as a clash, not as clear.
- Add fixture verdicts without treating them as exact `modeled` geometry.
  A fixture is `modeled` only when drawn components are exact and no debt
  remains; in-situ components cannot satisfy that condition. Proposed values:
  - `predicted`: commissioning not yet recorded, drawn with a "located by
    commissioning C — not yet recorded" callout;
  - `commissioned`: every consumed claim trusted, with clearance judged on the
    accepted envelope.

  Neither is read as `modeled`. A pass on clearance comes from the envelope
  check, never from the verdict name.

Chain part holds from this single commissioning output. Keeping separate
inventory primitives at predicted positions was rejected: the riser is an
arc band, not a primitive, and two geometry sources could diverge.

The original #182 dependency was the need to retain the riser band while
discarding both offcuts. In `freecad_job.py`, `_remove` retains result solids
above `STOCK_MM3`; it refuses a multi-piece split unless all pieces are held,
and only an explicit `keep` drops a piece. Carrying retained offcuts into the
commissioned riser would create false clashes and invalidate clearance checks.

Generic part-stock selection now exists through an operation's `keep` and the
[`keep_piece` rule](../../src/prechips/rules/keep_piece.py), which identifies
the kept piece by a finished part feature. That does not implement fixture-as-stock
or select a commissioning riser. P4 must adapt it to the fixture state, carry
only the riser band forward and prove both offcuts absent. Until then, the
proposed part setups' fixture clearance stays `?`.

### 4.3 Cache identities that change

- Job content gains the commissioning setup list, `commissioned` output and
  fixture `stock_in` forms. Plans with the block need new keys; plans without
  it must retain current serialization by omitting empty sections, not emitting
  `[]`. Section 8 requires a regression test.
- Engine identity uses the explicit `ENGINE_SOURCES` list, not a `kernel/*.py`
  glob. Editing an engine source changes `_engine_digest()` and the persisted
  CI cache namespace; host-only changes do not directly change it. Add new
  native engine modules to the list. The
  [module split constraints](../module-split.md#2-every-engine-source-file-stays-in-both-digests)
  describe this shipped boundary.
- Exclude the install record from geometry identity. Taking or correcting a
  reading must not invalidate cached geometry. This needs a test.
- Kernel launcher path/SHA identity and STEP digest retain their roles.

## 5. Traveler

### 5.1 Placement

The proposed renderer places commissioning once after the job page and before
the first part setup, regardless of quantity. Add to STOCK AND ROUTE:
"Commissioning C (once per install, covers 20) before the first part."

The commissioning pages have:

- meta line `commissioning C · once per install · covers 20`, not `qty 20`;
- closing sign-off "Commissioned by ____ date ____. Readings entered in
  <record path>", separate from part-sheet first-article sign-off;
- the same `PLANNED — NOT APPROVED` banner as other pages. Commissioning
  never grants approval.

### 5.2 Page layout

The proposed C-1 front page contains:

- Heading: `COMMISSIONING C — trammel-jig — once per install`.
- Renewal box: the `renew_when` text, plus "and whenever this sheet's planned
  values change".
- Status boxes (the existing `status_lines` style).
- A step list, one line per commissioning op, in order, each with its key range.

Each `align` operation has a station table with handwritten reading blanks:

| Key | s (mm) | Predicted X | Predicted Y | ± | Read X | Read Y | ✓ |
|---|---|---|---|---|---|---|---|
| C1:40/rail_a.pin@50 | 50 | −49.49 | −7.15 | 0.03 | ______ | ______ | ☐ |
| … | | | | | | | |
| C1:40/rail_a.pin@400 | 400 | −395.89 | −57.19 | 0.03 | ______ | ______ | ☐ |

These mock-up targets use §9's example geometry and print to DRO resolution.
An unresolved prediction must print `?` and its `M#`, never a guessed value.

The torque table records completion. Its 20 and 40 N·m values are mock-up
example values, not shop measurements, vendor limits or torque recommendations:

| Key | Fasteners | Count | Pass 1 | Pass 2 | Order | Wrench | Done |
|---|---|---|---|---|---|---|---|
| C1:30 | rail A T-slot studs | 4 | 50 % (20 N·m) | 100 % (40 N·m) | centre outward | torque-wrench | ☐ initials |

In-situ machining reuses the operation table and DRO block. HUB prints its
computed offset, with location "at apex, +Y <computed offset>", not drawing
nominal.

The riser sweep reuses `sheet_sweep.py` with the derived cutter displayed as
"Ø14 = part cutter Ø10 + 2 × 2.0 inset".

The acceptance table is also a mock-up. Its ±0.10 band is an example limit,
not a measured result or a recommended acceptance tolerance:

| Key | Reading | Of | Gauge | Predicted | Band | Read | ✓ |
|---|---|---|---|---|---|---|---|
| C4:10/sagitta_outer | sagitta over 300 chord | riser outer edge | … | (computed) | ±0.10 | ______ | ☐ |
| C4:10/width | width | riser | … | (computed) | ±… | ______ | ☐ |
| C4:10/hub_pin_to_edge | distance | HUB pin → riser edge at apex | … | (computed) | ±… | ______ | ☐ |
| C4:10/hub_apex | DRO X/Y (tangential judged) | apex pose → HUB bore (no pin) | coaxial indicator, DRO | (computed X, Y) | ±… | ______ , ______ | ☐ |
| C4:10/hub_size | size | HUB hole | gauge pins | 8.000 (declared) | fit band | ______ | ☐ |
| C4:10/dowel_position | DRO X/Y | HUB bore → dowel bore (no pins) | coaxial indicator, DRO | (computed X, Y) | ±… | ______ , ______ | ☐ |
| C4:10/dowel_fit | size | dowel hole | gauge pins | 6.000 (declared) | fit band | ______ | ☐ |

A closing box reads: "Do not load a part until every ☐ is ticked and entered in
<record path>."

### 5.3 Part sheets

Each dependent setup's front sheet must receive the roll-up status (§3.2):

- `? commissioning C not recorded (N readings)`, or
- `✗ STOP — commissioning C failed: …`.

Its holding picture must label unrecorded in-situ features `predicted`.

### 5.4 Review gate

The shipping renderer PR must run blind machinist review under AGENTS.md.
The new section has no main-branch baseline and requires `CLEAR` with zero
blocker, clutter or clarity findings. This design record is not that review,
a rendered-page acceptance result or physical shop acceptance.

## 6. Interplay with related issues

### 6.1 #11 (predicted readings before cutting)

The proposed #11 per-part "check before cutting" block also needs computed
readings, such as stock top from the M5 stack, stand-out and sweep equality,
printed with a band and blank. Share `Reading`, prediction plumbing and table
rendering instead of implementing them twice. #11 adds predictions for readings
taken on each part; they remain traveler checks, not install-record entries.
Commissioning readings have installation lifetime and are recorded. The proposed
renderer uses `recorded: "install" | "per_part"` to distinguish them.

### 6.2 #134 (shop-made fixtures as their own parts)

Under the #134 proposal, the locating/alignment trammel becomes its own
`MHA-071-TL-nn` part with drawing, STEP and bundle:

- The fixture bundle makes it only to the spot state. The drawing labels HUB
  and dowel "SPOT ONLY — drill and ream in situ (commissioning)" and the
  6 mm riser blank "profile cut in situ".
- The consumer rocker plan owns commissioning because predictions depend on
  the part's hub radius, cutter and this installation, which the fixture
  bundle does not know.

`located_by = "in_situ"` is how the consumer's inventory entry says the fixture
bundle left these features at spot. When #134 lets a parent reference a fixture
part instead of a make-table, that reference carries `located_by` unchanged.

Commissioning must use plan operations. Inventory `make_ops` describe an
off-machine route for a `shop_made` item in `_MADE_CATEGORIES`; they have no
setup, zero or kernel removal. In-situ finishing needs all three on the
production machine in its production installation.

### 6.3 #182 (keep or discard pieces)

The original #182 dependency covered two discard cases:

- the riser cut must keep the band and discard both offcuts (§4.2);
- if a scrap-blank first article is ever used instead of the riser, its pieces
  are discarded whole.

Current part-stock `keep` does not supply a fixture-state route. Reuse and adapt
that mechanism for the riser instead of inventing a second keep syntax; the
fixture integration remains unfinished (§4.2).

## 7. Implementation plan

All rows remain proposed. Original line-count estimates exclude tests and docs;
they are not current size measurements or delivery commitments.

| PR | Scope | Size | Depends on |
|---|---|---|---|
| P1 | Schema: `commissioning` root, new `do` actions and their fields, `TorqueStep`, `ReadingSet`/`Reading`, `located_by`, `fixture_feature`, `locate`, the `fixture.<id>` `stock_in` forms, record-file parse, cross-validators (§2.4 errors). Input-format docs. No rules beyond validation. | ~500 | none |
| P2 | Shared predicted-reading module (`Reading`, prediction protocol, band check), the `commissioning` rule, record trust and staleness, the dependent-setup roll-up, `ALWAYS_REQUIRED`. Analytic predictions for HUB offset, sagitta, width and hub-pin distance. Rule-family doc page. | ~700 | P1 |
| P3 | Traveler: commissioning section, reading, torque and acceptance tables, part-sheet status line, meta-line and sign-off changes. Blind machinist review. | ~450 | P2 |
| P4 | Kernel: fixture-as-stock, `commissioned` output chained into part holds, the `predicted` fixture verdict and callout, and empty-section omission for cache stability. Rules-geometry doc. | ~500 | P1, #182 |
| P5 | Trammel guide adapter: station targets, apex pose and pin-pair radii from #269's guide. Derived riser cutter check. | ~250 | P2, #269 |
| P6 | Rocker trammel example bundle (§9) with a demonstration record, expected outputs and validator exits. Blind review on its traveler. | data | P3 through P5, HA plan |

The original sequence allowed P1 through P3 before #269/#182 integration by
using a test-only guide double. P4 still needs fixture-state piece selection;
P5 needs the actual guide adapter. Test doubles are not shipped implementations.

### Decisions (maintainer, 2026-10-17, on PR #275)

- D1, record location: separate shop-kept install-record file (§2.6).
  Re-commissioning intentionally stales first-article approval.
- D2, severity: require the proposed rule in `ALWAYS_REQUIRED`. Missing,
  untrusted or stale dependent evidence must exit 4 (§3.2); the proposed
  example stays at 4 until it has its demonstration record.
- D3 originally deferred guide field names to #269. The guide has since shipped:
  fixture `kind = "trammel"`, sweep `guide = "trammel"` and inventory
  `pin_clearance_mm` match current syntax. A current sweep selects `pin_pair`,
  not the sketch's `pins`. Current inventory uses `rail_angle_deg` with
  `rail_angle_error_deg`, and `pin_spacing_mm` (a map keyed by pin pair) with
  `pin_spacing_error_mm`; it does not use the sketch's `rail_angle_limits_deg`
  or `pin_spacing_limits_mm`. The original fences retain those historical
  spellings as non-runnable design fragments. Section 4.1's commissioning guide
  adapter and implementation phase P5 remain unimplemented.
- D4, dowel acceptance: the Ø6 hole needs `dowel_position` from HUB and
  `dowel_fit`. HUB also needs `hub_size`, as every claim needs coverage (§3.3).
- D5, batch accounting: print `runs = ceil(quantity / batch_qty)` and warn
  (§3.5). Do not imply that prechips counts parts or runs.
- D6, `expect`: optional cross-check only. Compute predictions independently;
  mismatch beyond the reading's tolerance is an error (§2.3). The unresolved
  signed/asymmetric-band refinement remains in §10.

## 8. Test plan

This is an acceptance matrix for the proposed phase, not a list of tests run
or passed. Rule tests should use synthetic `bundle.kernel` facts where needed,
CLI tests should use `SYNTHETIC_KERNEL`, and all files should be temporary.

### Schema (P1)

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
- Record entry shape: a scalar `value_mm` for a `dro_xy` key, `[x, y]` for a
  `size` key, or `value_in` where the reading uses `band_mm` → schema error.
- Duplicate generated keys (a repeated reading name, a repeated station) →
  error. An uncited `align` tolerance or `accept` band → `?`. A reading gauge
  coarser than its band → error; an unresolved gauge → `?`.
- `expect` beyond the tolerance → error; within it → no finding; `expect` on an
  unknown prediction → still `?`.
- A `fixture.<id>` `stock_in` in a part setup → error.
- A record key the plan does not generate → error.
- A plan without `commissioning` → byte-identical report to today. Freeze one
  shipped example.

### Rules (P2)

Require one case per §3.1 outcome, including:

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
- every worked commissioning setup (C1 through C4) names a machine. Omitting `machine`
  on a commissioning setup is a schema error; `machine = "unknown"` leaves its
  machine-dependent findings `?`.

Additional rule cases:

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
- Tangential projection: a tangent at 45° to the setup axes with a tangential
  error of 1.2 × band → `✗`, although X and Y are each within the band; a radial
  residual alone does not fail `hub_apex`.
- Reference chains: a passing `dowel_position` with a failed or missing HUB
  position reading leaves the dowel untrusted, and a dowel-only setup blocked.
- Chain envelopes: the dowel's void shrinks by HUB's ±0.05 plus its own ±0.03.
- Pin fit: an 8.005 pin with a bore trusted as `[8.000, 8.010)` → plan error.
- Pin clearance: a pin reading widens by the radial play from the hole's
  trusted `size` interval; an untrusted or later size reading → `?`.
- Roll-up scope: a missing `dowel_fit` leaves a setup that locates only on HUB
  unblocked; a missing `align` reading on a rail the setup rides blocks it; one
  on a guide element it never uses does not.
- Bands: `band_mm = -0.1`, `[0.1, -0.1]` or `[0.005, 0.02]` (excludes 0) → schema
  error.
- Pin at zero offset: a pin reading with `|o| ≤ r` → plan error; `o = 4.01`,
  `r = 4.00`, ±0.05 band → plan error (accepted range reaches 3.96).
- Authored order: an `accept` op numbered 100 authored before a ream numbered 20
  → the reading precedes the ream → error.
- `expect_mm` shapes: a scalar for scalar quantities and `[x, y]` for `dro_xy`;
  any other shape → schema error.
- Spindle zero: `method = "spindle"` with `edge` or `tool` → schema error; alone
  → valid.
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
- Terminal tool interval: a measured 8.005 reamer for an 8.000 `[0.000, 0.015]`
  hole → valid; 8.020 → error.
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
- DRO interval: an `align` reading inside the band by less than
  `(r_dro + r_g)/2` → `?`, by more → pass; a relational `dro_xy` reading uses
  `r_g + r_dro`.
- Contact binding: a record whose `contact` differs from the plan's, or is
  missing → `?`.
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

### Traveler (P3)

- The commissioning section precedes the first part setup.
- Its meta line has no `qty`.
- `?` predictions print `?` plus `M#`, never a number.
- Part sheets carry the roll-up line.
- Print and PDF contracts pass with `PRECHIPS_REQUIRE_PRINT_BROWSER=1`.
- Blind machinist review.

### Kernel (P4)

Use the shared `freecad_kernel` fixture for the proposed native cases:

- HUB void cut at the planned apex location, not at the spot `at_mm`, with no
  void at the spot: the initial fixture state leaves in-situ voids out, so the
  commissioned fixture has exactly one HUB hole even when the spot and the
  planned location differ.
- The riser band is kept and offcuts discarded through fixture-state integration.
- Edge envelope: built from the arcs at the inverted `[R_min, R_max]` through
  the apex location band, evaluated over the whole edge; at 600 mm from the
  apex (R802, c 300, ±0.10 sagitta) the envelope is at least 2.8 mm; holes use the shrunk (intersected) void, so a
  Ø8.010 object in an accepted Ø8.000 to Ø8.015 hole → not clear.
- Guide budget: a rail-angle uncertainty widens the sagitta and width
  predictions; a missing budget fact → those readings `?`.
- Contact proof: a riser edge with a ±0.10 band that touches only in the grown
  envelope → contact `?`; touching in the guaranteed envelope → contact holds.
- Feasibility: `[0.000, 0.015]` with ±0.005 → feasible; with ±0.008 → schema
  error. `tolerance_mm = 0` or negative → schema error.
- Chain travel: a dowel ±0.03 from HUB ±0.05 counts ±0.08 in the span.
- Installation pose: two commissioning setups with different installation
  transforms → schema error; carrier poses along the guide → valid.
- Reading order: `hub_pin_to_edge` listed before `hub_size` → its pin play is
  unknown → `?`; the sketch lists `hub_size` first.
- Installation travel: C1 at X −400 and C4 at X +400 on a 600 stroke → error,
  although each setup alone fits; endpoints at ±400 with a 0.02 band on an 800
  stroke → error; two machines in one commissioning block → schema error.
- Feasibility with prediction uncertainty: ±0.05 band, ±0.03 prediction, ±0.03
  measurement → schema error.
- Combined DRO interval: a 0.05 band with `r_g = r_dro = 0.03` on a relational
  `dro_xy` → schema error.
- Envelope: a riser edge 0.05 from a cutter path with a ±0.10 band → clash;
  the envelope changes no cache key when only the record changes.
- Guide error budget: an `align` reading inside the band whose target
  uncertainty from the budget reaches past it → `?`; a missing budget fact →
  `?`.
- Part-setup clash checks see both the cut riser and C2's holes: the state
  accumulates across C2 (whole fixture) and C3 (riser only), and C3's riser
  result replaces only the blank.
- The `predicted` verdict and callout.
- With the function-scoped `kernel_cache`: changing only the record file leaves
  the cache key unchanged and hits.
- A plan without `commissioning` keeps its existing key.

## 9. Worked example sketch: rocker trammel jig

This is a non-runnable design sketch, not a shipped bundle. Every value below
is example data under AGENTS.md:

- values from #269/#270 are cited to those issues;
- the remaining values are realistic example values, marked as such;
- the demonstration record uses the exact disclosure strings;
- nothing here is a shop measurement, and nothing may be copied into a real shop
  file.

The proposal leaves the six real `fixtures.vise-pm-6` measurements untouched.

### 9.1 Inventory (sketch)

This inventory fragment mixes current names with historical proposed fields.
The D3 decision above identifies their current spellings; the fragment is not
a current inventory example. Its synthetic disclosure is not shop evidence.

```toml
[fixtures.trammel-jig]
kind = "trammel"                   # #269's kind; name is D3
shop_made = true
note = "Oblique trammel: two HGR15 rails, carrier on two pin pairs (#269)."
pin_spacing_limits_mm = { value = [449.995, 450.005], measured = { status = "measured", by = "example value (realistic, not a shop measurement)", date = "2026-10-11", instrument = "example fixture (no physical measurement)" } }   # #269: D = 450; limits give the budget its spacing uncertainty
rail_angle_deg = 16.44             # #269: alpha; non-length nominal, example value from #269
# guide error budget facts (§4.1); field names are #269's (D3), shown here as placeholders
rail_angle_limits_deg = { value = [16.435, 16.445], measured = { status = "measured", by = "example value (realistic, not a shop measurement)", date = "2026-10-11", instrument = "example fixture (no physical measurement)" } }
pin_clearance_mm = { value = 0.005, measured = { status = "measured", by = "example value (realistic, not a shop measurement)", date = "2026-10-11", instrument = "example fixture (no physical measurement)" } }

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

This partial plan uses the proposed root and actions. Omitted rail-B operations,
hold details and the second riser sweep mean it is not a complete plan.

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
  { name = "hub_size", quantity = "size", of = "trammel-jig.hub_hole", band_mm = [0.0, 0.015], band_cite = "example value (realistic, not a shop measurement): 8 H7 slip fit for the hub pin", claims = ["trammel-jig.hub_hole.size"] },
  { name = "hub_pin_to_edge", quantity = "distance", of = ["trammel-jig.riser.outer_edge", "trammel-jig.hub_hole"], pin = "pin-8", contact = "near", band_mm = 0.05, band_cite = "example value (realistic, not a shop measurement)", claims = ["trammel-jig.hub_hole.position.radial"] },
  { name = "hub_apex", quantity = "dro_xy", of = ["guide.apex", "trammel-jig.hub_hole"], band_mm = 0.05, band_cite = "example value (realistic, not a shop measurement)", claims = ["trammel-jig.hub_hole.position.tangential"] },
  # D4: the dowel hole's own readings
  { name = "dowel_position", quantity = "dro_xy", of = ["trammel-jig.hub_hole", "trammel-jig.dowel_hole"], band_mm = 0.03, band_cite = "example value (realistic, not a shop measurement)", claims = ["trammel-jig.dowel_hole.position"] },
  { name = "dowel_fit", quantity = "size", of = "trammel-jig.dowel_hole", band_mm = [0.0, 0.012], band_cite = "example value (realistic, not a shop measurement): 6 H7 for the Ø6 dowel", claims = ["trammel-jig.dowel_hole.size"] },
]
# gauge-pins: example metric set in 0.01 mm steps, finer than the 0.012 and 0.015 fit bands
# kinds: sagitta-gauge-300 = sagitta_gauge (new); calipers = caliper; coax-indicator = coax_indicator (new); gauge-pins = pin_gauge_set
checks = { sagitta_outer = "sagitta-gauge-300", sagitta_inner = "sagitta-gauge-300", width = "calipers", hub_pin_to_edge = "calipers", hub_apex = "coax-indicator", hub_size = "gauge-pins", dowel_position = "coax-indicator", dowel_fit = "gauge-pins" }
```

The proposed rules must derive these targets independently:

- For sagitta, use `R − √(R² − (c/2)²)`. The sketch's edges are R802 and R814,
  from R795/R821 cutter paths and an Ø14 cutter. #270's 14.12 ± 0.1 described an
  earlier variant; the computed prediction must replace that authored figure.
- Width is `R_outer − R_inner`.
- Hub-pin-to-edge uses calipers against the HUB pin's near side
  (`pin = "pin-8"`, `contact = "near"`). The centreline target is signed
  radial offset `o = ρ_hub − R_edge`, and the printed
  target is the near-contact value `o − sign(o)·r` (§2.3). The shop records the
  signed caliper reading, which is judged against that target. `ρ_hub` is the
  hub centre's distance from the arc centre, taken from `features.toml`; `o` is
  positive when HUB lies outside the edge (away from the arc centre) and
  negative when it lies inside. The sheet prints which side is
  positive, and the shop records the value with its sign. A HUB on the wrong side
  of the edge therefore reads with the wrong sign and fails the band, instead of
  matching the mirror position `2·R_edge − ρ_hub`.
- Dowel position is the route's `locate` offset as an X/Y pair
  (`[-292.0, 0.0]` in the sketch), read as the DRO X/Y move from the HUB bore to
  the dowel bore, each centred directly with the coaxial indicator (no pins).
- Hub size and dowel fit use the declared solid's `dia` (8.0 and 6.0). The
  band is the fit the pin or dowel needs. The terminal reamers (`reamer-8h7`,
  `reamer-6h7`) are checked against those declared sizes and bands, and an
  unmeasured reamer size leaves that check `?`.

The sketch assigns each §3.3 claim to the corresponding reading and measures
only that reading's subjects. Its intended reference chain runs from inner
root edge through `width` to the outer edge, from there to HUB's radial
position, from guide apex to HUB's tangential position, and from HUB to the
dowel in both axes. This is a design mapping, not a passed validation result.

### 9.3 State A: record absent (the normal planned state)

The proposed `prechips check` output would include the following. This is an
expected-output sketch, not an observed transcript from the current command:

- `commissioning C1:40/rail_a.pin@400: ? predicted (-395.89, -57.19) ± 0.03 —
  measure: C1:40/rail_a.pin@400`, and likewise for each row;
- for each dependent part setup (the setups holding on `trammel-jig`):
  `? commissioning C not recorded (N readings)`;
- exit 4.

The proposed traveler would print C-1 through C-4, with empty blanks, before
the part sheets.

### 9.4 State B: demonstration record

This proposed-record fragment includes only one reading and placeholder hashes.
It is not a complete record, a current fixture file or physical installation evidence.

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

Under the proposed rules, a complete record with every required key trusted
and in band would clear the commissioning findings and dependent roll-ups,
leaving other findings unchanged. Synthetic demonstration data would exercise
the measured branch only; it would not be an observation or physical acceptance.
The current implementation cannot produce this phase's verdict.

## 10. Open review notes

PR #275's Codex review stopped with these findings unresolved. They remain
implementation requirements, even where the body now calls attention to them:

- §4.2 kernel: resolve `hold.stop_fixture`, like `hold.fixture`, through
  `commissioned[fixture id]`, so stop-fixture setups see the commissioned state
  ([r4301068266](https://github.com/pedropaulovc/prechips/pull/275#discussion_r4301068266)).
- §2.3 `expect` cross-check: compare the signed expect-minus-prediction interval
  against `[low, high]` rather than an unsigned distance, so asymmetric bands
  keep their direction
  ([r4301068269](https://github.com/pedropaulovc/prechips/pull/275#discussion_r4301068269)).
- §2.3 `align` verify sets: require at least one qualifying `verify` set for every guide
  element a dependent sweep uses, even when no `set` or torque op was authored
  ([r4303120941](https://github.com/pedropaulovc/prechips/pull/275#discussion_r4303120941)).
- §2.3 and §3.6 installation travel: include commissioning cutting and sweep
  tool extents (and relevant stock bounds) in the installation-wide travel
  union, not only DRO readings, zero and check-jogs
  ([r4303120943](https://github.com/pedropaulovc/prechips/pull/275#discussion_r4303120943)).
