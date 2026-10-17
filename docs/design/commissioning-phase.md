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
| `align` | read a guide element against predicted DRO targets | `readings` (a `ReadingSet`, §2.3), `gauge`, `tolerance_mm` / `tolerance_in` |
| `torque` | tighten named fasteners in a stated order | `torque` (`TorqueStep`) |
| `accept` | acceptance readings on a commissioned fixture feature | `readings` (a list of `Reading`), with `checks` naming the gauge per reading |

The existing `drill`, `ream`, `spot` and `finish_profile` actions are reused
**unchanged** for in-situ machining. They gain one field, `fixture_feature`,
which replaces `feature` (§2.4).

`TorqueStep`:

| Field | Type (also accepts `"unknown"`) |
|---|---|
| `fasteners` | `str`: the fastener group as the fixture names it (`"rail A T-slot studs"`) |
| `count` | `int` |
| `value_nm` / `value_in_lbf` | `float`, one spelling |
| `passes` | `list[float]`: fractions of `value`, ascending, ending at 1.0 (`[0.5, 1.0]`) |
| `sequence` | `str`: printed order (`"centre outward, alternating sides"`) |
| `wrench` | `str`: the inventory `gauges` item, `kind = "torque_wrench"` |
| `cite` | `Citations` |

A torque value is a shop/vendor number, never a measured length. It needs a
citation, or the AGENTS.md example-value comment. Unknown → `?`.

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

Each station becomes one reading, keyed `"<setup>:<op>/<element>@<station>"` (for
example `C1:20/rail_a.pin@400`). The prediction is a DRO X/Y pair in the plan's
`dro` sign convention: the pin centred under the spindle, with the DRO zeroed on
the spindle axis at the guide's crossing point. It is computed by the guide
(§4.1).

`Reading` (for `accept`, also reused by #11, §6.1):

| Field | Type (also accepts `"unknown"`) |
|---|---|
| `name` | `str`: key within the op (`"sagitta_outer"`) |
| `quantity` | `"sagitta"` / `"width"` / `"distance"` / `"size"` / `"dro_xy"` / `"z"` |
| `of` | `str` or `list[str]`: the commissioned features or fixture solids read (`"trammel-jig.riser.outer_edge"`); for a relative reading, the first entry is the reference |
| `claims` | `list[str]`: the in-situ claims this reading establishes (`"trammel-jig.dowel_hole.position"`, §3.3); empty for a reading that trusts nothing (#11) |
| `chord_mm` / `chord_in` | `float` (`sagitta` only) |
| `band_mm` / `band_in` | `Vector` `[low, high]` relative to the prediction, or a symmetric `float` |
| `band_cite` | `Citations` |
| `expect` | optional authored cross-check (above) |

Each reading's key is `"<setup>:<op>/<name>"`.

The band is an authored acceptance limit, so it needs a citation: a part
tolerance it protects, or the author's reasoning. A band is not a measurement.

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
- the route's last op that sets size is the **terminal** op. Its tool sets the
  finished size the kernel cuts and the `size` reading predicts (a reamer's size,
  for HUB), and the route's earlier ops are roughing.

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
tool = "endmill-14"  # rules check dia == part cutter dia + 2 × inset
```

The riser's cutter is **derived, not hard-coded**:
`dia = part_cutter_dia + 2 × inset_mm`, where the part cutter is the cutter of
the part setup's `guided_sweep` on the same pin pair. The named tool must match
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
"tools.endmill-10" = "<sha256>"     # the part cutter that derives the riser cutter

[readings."C1:20/rail_a.pin@400"]
value_mm = [-395.884, -57.203]
measured = { status = "measured", by = "...", date = "2026-...", instrument = "coaxial indicator, gauges.coax" }

[steps."C1:30"]                     # a torque step: done, not a value
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
| known | trusted, `|read − predicted|` within the band | pass |
| known | trusted, outside the band | `✗`: names the reading, the prediction, the band and the excess |

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
  listed: "commissioning C not recorded: C1:20/rail_a.pin@50 … C4:10/width";
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
| hole (a `void` cylinder) | `size`, and `position` (`position.radial` when located from the guide, below) | `size`: `size`. `position`: `dro_xy`, or `distance` (one direction per reading; see below) |
| swept edge (`<solid>.<edge>`) | `radius`, and `location` unless it is the root edge | `radius`: `sagitta`. `location`: `width` or `distance` |

**Root edge.** The first edge the guide cuts in route order is the **root**. It
is a cut path: it is cut by the guide on a pin pair the part is also cut on, and
it defines the frame the other claims are read in. It has only a `radius` claim.
Every other swept edge also has a `location` claim, relative to the root.

**Binding.** A reading may list only claims owned by an element it actually
measures:

- a single-subject quantity (`sagitta`, `size`, `z`) has one `of` entry, and may
  list only that element's claims;
- a relational quantity (`distance`, `width`, `dro_xy`) lists its reference first
  in `of`. It may list only claims owned by the other entries, never the
  reference's;
- each listed claim must also accept the reading's quantity, per the table above.

So a `size` reading of `hub_hole` listing `dowel_hole.size` is an error, and so
is a `z` reading listing any position. Neither is ever a silent trust.

**Two-axis positions.** A hole's `position` is a 2D claim. One `dro_xy` reading
from a reference covers both axes. A `distance` covers only the direction from
its reference to the hole, so a hole whose position rests on distances needs
two, from references whose directions to the hole differ by at least 30°.
Otherwise the claim is uncovered, an error naming it.

There is one exception: a hole located from the guide (`locate.from = "guide"`,
HUB). Its claim is `position.radial`: the distance from the arc centre, read as
a `distance` to a swept edge. Its placement along the arc is not a claim,
because:

- the cut path is a circle, so the arc constrains no tangential position;
- each part's sweep stops are set on the part's own cutter path by the guided
  sweep's measured stop-setting procedure (#255), not from HUB.

The part's rotation about HUB is fixed by the dowel, whose own position (two
axes, from HUB) is a claim.

**Reference chain.** A relational claim's reference must itself be the root edge,
or an element whose relational claim is covered, so that the chain reaches the
root without a cycle. For the trammel:

- `width` puts the outer edge relative to the root (inner) edge;
- `hub_pin_to_edge` puts HUB's radial position relative to the outer edge,
  which is what the in-situ HUB exists to match;
- `dowel_position` puts the dowel hole relative to HUB, in both axes (`dro_xy`).

**Coverage.** The validator requires that every claim of every in-situ element a
dependent part setup consumes is listed by at least one compatible, bound
reading. A missing claim is an error ("in-situ claim trammel-jig.dowel_hole.size
has no acceptance reading"), because nothing would ever discharge its debt.

**Trust.** A claim is trusted only when every reading that lists it passes. A
dependent setup's roll-up (§3.2) is a pass only when every consumed claim is
trusted.

The trammel's claims and readings (decision D4 adds the dowel's two):

| Claim | Reading |
|---|---|
| `riser.inner_edge.radius` (root), `riser.outer_edge.radius` | `sagitta_inner`, `sagitta_outer` |
| `riser.outer_edge.location` | `width`, from the inner edge |
| `hub_hole.position.radial` | `hub_pin_to_edge`, from the outer edge |
| `hub_hole.size` | `hub_size` (largest gauge pin that enters) |
| `dowel_hole.position` | `dowel_position`: `dro_xy` from the HUB pin to the dowel hole, with a coaxial indicator on each |
| `dowel_hole.size` | `dowel_fit`: largest gauge pin that enters, predicted from the terminal reamer and banded by the dowel's fit |

### 3.4 Staleness

The record's `[planned]` table holds **one SHA-256 per planned input**, like the
approval record's `[inputs]`. The inputs are:

- the `commissioning` block;
- the commissioned fixture's inventory item;
- every other inventory item a prediction consumes;
- every part cutter that derives a riser cutter.

The checker computes the same table for the current plan and compares the two:

- a digest that differs names that input as changed;
- an input in the current table but missing from the record is named as new,
  because the record was taken without it. This differs from approvals, which
  skip an omitted input: a commissioning record must cover everything its
  predictions use;
- an input only in the record (no longer consumed) is ignored.

Any changed or new input makes every reading `?` with: "install record no longer
matches the plan: <changed and new inputs> changed. Re-commission." This mirrors
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

- **Fixture as stock.** A commissioning setup with `stock_in = "fixture.<id>"`
  or `"fixture.<id>.<solid>"` takes the posed fixture solids (from the existing
  `_solids()` path) as its work. The in-situ voids are cut at their **planned**
  location: the `locate` result in setup coordinates, not the spot `at_mm`. The
  riser is cut by the guided-sweep removal on the riser blank.
- **Commissioned fixture output.** A new job section,
  `commissioned[<fixture id>]`, holds the fixture shape after the last
  commissioning setup. Part setups whose `hold.fixture` is that fixture take
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
| C1:20/rail_a.pin@50 | 50 | −49.49 | −7.15 | 0.03 | ______ | ______ | ☐ |
| … | | | | | | | |
| C1:20/rail_a.pin@400 | 400 | −395.89 | −57.19 | 0.03 | ______ | ______ | ☐ |

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
| C4:10/hub_size | size | HUB hole | gauge pins | (reamer size) | fit band | ______ | ☐ |
| C4:10/dowel_position | DRO X/Y | HUB pin → dowel hole | coaxial indicator, DRO | (computed X, Y) | ±… | ______ , ______ | ☐ |
| C4:10/dowel_fit | size | dowel hole | gauge pins | (reamer size) | fit band | ______ | ☐ |

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
  reference → error. A hole position resting on one `distance` → uncovered; two
  distances from references at least 30° apart, or one `dro_xy` → covered; a
  guide-located hole needs only `position.radial`.
- A consumed claim no reading lists (drop `dowel_fit`) → error naming the
  claim. A reference cycle, or a relational claim whose chain never reaches the
  root edge → error.
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
- in band, exactly at the band edge, and outside the band.

Also:

- Staleness, per input: one changed digest → all `?` naming only that input; an
  input absent from the record → named as new; an input only in the record →
  ignored.
- Claim trust: one failed reading leaves only the claims it lists untrusted.
  The roll-up names them.
- Roll-up: dependent setups get `?`/`✗`. A setup on a different fixture is
  unaffected.
- Dependence derived through each of the three paths in §2.5.
- Exit codes: no record → 4; one bad reading → 2; complete and in band → no
  commissioning contribution.
- Riser cutter: matching, mismatched, and unknown part cutter.
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

- HUB void cut at the planned apex location, not at the spot `at_mm`.
- The riser band is kept and the offcuts discarded (after #182).
- Part-setup clash checks see the cut riser.
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
do = "align"
readings = { element = "rail_a.pin", stations_mm = [50, 100, 150, 200, 250, 300, 350, 400] }
gauge = "coax-indicator"
tolerance_mm = 0.03                # #270
# predicted @400: (-395.890, -57.191) per #270; the rules compute it from the guide

[[commissioning.setups.ops]]
op = 30
do = "torque"
torque = { fasteners = "rail A T-slot studs", count = 4, value_nm = 40.0, passes = [0.5, 1.0], sequence = "centre outward", wrench = "torque-wrench", cite = "example value (realistic, not a shop measurement)" }

# ops 40/50: rail B, likewise

[[commissioning.setups]]           # C2: in-situ locator holes
id = "C2"
stock_in = "fixture.trammel-jig"
# hold: carrier locked at the symmetric pose
[[commissioning.setups.ops]]
op = 10
do = "spot"
fixture_feature = "trammel-jig.hub_hole"
locate = { from = "guide", pose = "apex", offset_mm = [0.0, "computed"] }
[[commissioning.setups.ops]]
op = 20
do = "drill"
fixture_feature = "trammel-jig.hub_hole"
[[commissioning.setups.ops]]
op = 30
do = "ream"
fixture_feature = "trammel-jig.hub_hole"
[[commissioning.setups.ops]]
op = 40
do = "spot"
fixture_feature = "trammel-jig.dowel_hole"
locate = { from = "trammel-jig.hub_hole", offset_mm = [-292.0, 0.0] }   # example value (realistic)
[[commissioning.setups.ops]]
op = 50
do = "drill"
fixture_feature = "trammel-jig.dowel_hole"
[[commissioning.setups.ops]]
op = 60
do = "ream"                        # terminal op: sets the Ø6 size
fixture_feature = "trammel-jig.dowel_hole"

[[commissioning.setups]]           # C3: the jig cuts its own riser
id = "C3"
stock_in = "fixture.trammel-jig.riser"
[[commissioning.setups.ops]]
op = 10
do = "finish_profile"
fixture_feature = "trammel-jig.riser.inner_edge"   # R802, on the R795 pin pair
inset_mm = 2.0                     # #270 comment: edges 2 mm inside each finished edge
tool = "endmill-14"                # derived: part cutter Ø10 + 2 × 2.0
contour = { method = "guided_sweep", sweep = { guide = "trammel", fixture = "trammel-jig", pins = "inner" } }   # D3: names from #269
# op 20: fixture_feature = "trammel-jig.riser.outer_edge" (R814), pins = "outer"

[[commissioning.setups]]           # C4: acceptance readings
id = "C4"
[[commissioning.setups.ops]]
op = 10
do = "accept"
readings = [
  { name = "sagitta_outer", quantity = "sagitta", of = "trammel-jig.riser.outer_edge", chord_mm = 300.0, band_mm = 0.1, band_cite = "#270", claims = ["trammel-jig.riser.outer_edge.radius"] },
  { name = "sagitta_inner", quantity = "sagitta", of = "trammel-jig.riser.inner_edge", chord_mm = 300.0, band_mm = 0.1, band_cite = "#270", claims = ["trammel-jig.riser.inner_edge.radius"] },
  { name = "width", quantity = "width", of = ["trammel-jig.riser.inner_edge", "trammel-jig.riser.outer_edge"], band_mm = 0.1, band_cite = "example value (realistic, not a shop measurement)", claims = ["trammel-jig.riser.outer_edge.location"] },
  { name = "hub_pin_to_edge", quantity = "distance", of = ["trammel-jig.riser.outer_edge", "trammel-jig.hub_hole"], band_mm = 0.05, band_cite = "example value (realistic, not a shop measurement)", claims = ["trammel-jig.hub_hole.position.radial"] },
  { name = "hub_size", quantity = "size", of = "trammel-jig.hub_hole", band_mm = [0.0, 0.015], band_cite = "example value (realistic, not a shop measurement): 8 H7 slip fit for the hub pin", claims = ["trammel-jig.hub_hole.size"] },
  # D4: the dowel hole's own readings
  { name = "dowel_position", quantity = "dro_xy", of = ["trammel-jig.hub_hole", "trammel-jig.dowel_hole"], band_mm = 0.03, band_cite = "example value (realistic, not a shop measurement)", claims = ["trammel-jig.dowel_hole.position"] },
  { name = "dowel_fit", quantity = "size", of = "trammel-jig.dowel_hole", band_mm = [0.0, 0.012], band_cite = "example value (realistic, not a shop measurement): 6 H7 for the Ø6 dowel", claims = ["trammel-jig.dowel_hole.size"] },
]
checks = { sagitta_outer = "sagitta-gauge-300", sagitta_inner = "sagitta-gauge-300", width = "calipers", hub_pin_to_edge = "calipers", hub_size = "gauge-pins", dowel_position = "coax-indicator", dowel_fit = "gauge-pins" }
```

The rules compute the predictions. They are not authored:

- **Sagitta** of an edge of radius `R` over chord `c`: `R − √(R² − (c/2)²)`. With
  the example geometry, the riser edges are at R802 and R814 (R795 and R821 cutter
  paths with an Ø14 cutter). #270 quotes 14.12 ± 0.1 for an earlier variant. The
  engine's value replaces it.
- **Width:** `R_outer − R_inner` of the riser edges.
- **Hub-pin-to-edge:** `|R_edge − ρ_hub|`, where `ρ_hub` is the hub centre's
  distance from the arc centre, taken from `features.toml`.
- **Dowel position:** the dowel route's `locate` offset as an X/Y pair
  (`[-292.0, 0.0]` in the sketch), read as the DRO X/Y move from the HUB pin to
  the dowel hole, each centred with the coaxial indicator.
- **Hub size and dowel fit:** the terminal reamer's size from the inventory. The
  band is the fit the pin or dowel needs. An unmeasured reamer size leaves the
  prediction `?`.

Every claim of §3.3's table is listed by exactly the readings shown there, and
each reading lists only claims of the elements it measures, so the binding and
coverage checks pass. The reference chain runs from the root (inner) edge to the
outer edge through `width`, from the outer edge to HUB's radial position, and
from HUB to the dowel in both axes.

### 9.3 State A: record absent (the normal planned state)

`prechips check` reports:

- `commissioning C1:20/rail_a.pin@400: ? predicted (-395.89, -57.19) ± 0.03 —
  measure: C1:20/rail_a.pin@400`, and likewise for each row;
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
"tools.endmill-10" = "<sha256 printed by the checker>"

[readings."C1:20/rail_a.pin@400"]
value_mm = [-395.884, -57.203]     # example value: inside the 0.03 band
measured = { status = "measured", by = "example value (realistic, not a shop measurement)", date = "2026-10-11", instrument = "example fixture (no physical measurement)" }
# ... one entry per generated key ...
```

With every key present and in band, the `commissioning` findings pass, and the
part setups' roll-up passes. Their other findings are unchanged. As with every
demonstration fixture, this exercises the measured branch. It is disclosure, not
an observation.
