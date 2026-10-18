# Design: typed area hold (adhesive tape)

This internal design defines adhesive-tape holding capacity, tape-layer geometry
and Z-stack checks. It is partly implemented. The typed tape schema, `hold.area`
identity and migration checks have shipped, as has the reusable end-mill force
helper. The kernel tape layer, per-island capacity calculation, `hold_capacity`,
`area_hold_stack` and the area-hold setup-sheet rows have not shipped. A valid
`hold.area` record does not prove a hold's capacity or thickness band.

The design belongs to [#295](https://github.com/pedropaulovc/prechips/issues/295)
and shares its force model with
[#158](https://github.com/pedropaulovc/prechips/issues/158). It follows
[#289](https://github.com/pedropaulovc/prechips/issues/289): define the operator's
sequence, each printed number's physical reference, and error propagation before
adding the consuming rule or sheet row.

Vacuum chucks are outside this design. The owner deferred them on 2026-10-17
(D11), because a seal circuit cannot be derived from the work outline without
recorded groove geometry. [#309](https://github.com/pedropaulovc/prechips/issues/309)
retains the vacuum model. Section 11 records the maintainer's D1 to D10 decisions
on PR #296 (2026-10-17), followed by the owner's D11.

Motivating case: harmonic-analyzer #1577, rocker route v3, setups S0A/S0B (the
same strap setups as [#294](https://github.com/pedropaulovc/prechips/issues/294)).
The owner ruled on 2026-10-17 that the 350 × 40 × 3.0 1018 strap blank is faced
first, both sides, to 2.5 ±0.025, on a double-sided-tape hold, with no clamp
over the cut face. The shop record is harmonic-analyzer PR #1594: 3M 444 PET
film tape (0.10 mm) on a skimmed MIC-6 sub-plate.

Values quoted from #295 or the shop record are marked *(shop record)*. All other
numbers, including kc1, mc, radial-force ratio, helix angle, peel and tape lot
limits, are illustrative arithmetic for the equations. They are not datasheet
figures, measurements or recommendations and must not be copied into an inventory.

## Current status and navigation

| Capability | Status | Implementation or remaining work |
|---|---|---|
| Tape consumable, typed facts, `hold.area`, reference validation and migration | Shipped | [`model.py`](../../src/prechips/model.py), [`inputs.py`](../../src/prechips/inputs.py); current field contracts are in [inventory](../inventory.md) and [plan](../plan.md). |
| End-mill side-entry Kienzle force helper | Shipped as a reusable helper | [`_cutting_force.py`](../../src/prechips/rules/_cutting_force.py); no registered area-capacity rule consumes it. |
| Tape layer, seat check and contact islands | Proposed | [Schema geometry](#24-what-replaces-the-box-solid) and [capacity model](#3-capacity-model). |
| Hold capacity, pull tests and required-rule behavior | Proposed | [Capacity](#3-capacity-model) and [margin policy](#43-margin-policy). |
| Z-stack evaluation and area-hold sheet output | Proposed | [Z stack-up](#5-z-stack-up) and [Traveler](#6-traveler). |

Except where marked shipped, the rules, verdicts and printed rows below specify
the target behavior. They do not describe checks the current release performs.
The [phase table](#9-phased-implementation-plan) separates the delivered
prerequisites from the unfinished consumers.

For supported workflows, use the [quickstart](../manual/quickstart.md),
[tutorial](../manual/tutorial.md) or [demonstration](../manual/demo.md).
The [CLI catalog](../reference/cli.md), [Python catalog](../reference/python-api.md)
and [architecture](../internals/architecture.md) describe current interfaces and
implementation boundaries.

## 1. Problem

Typed tape identity now exists, but prechips still has no rule that compares
area-hold capacity with cutting demand. Before the schema migration, a consumer
could describe tape only through:

- `hold.method = "tape"`, free text that `thin_wall_under_clamp._PROTECTED`
  treated as thin-wall protection; and
- a `custom` fixture box with `locates = "work underside"` and `bears = "face"`.

The legacy `method` spelling is now bad input, and tape has been removed from
`_PROTECTED`. The former box model still explains the geometry problem. It
represented a layer without checking the following:

1. Tape shear times contact area against lateral cutting force, and lift
   resistance against the helix's axial pull.
2. Product, thickness and dwell as typed inventory facts. This identity work is
   shipped, but the future rules still need to consume it.
3. Tape thickness and its measured spread in the Z stack between the locating
   plate and work, evaluated against the thickness band.
4. A printed release step: heat or solvent, then roll the work off; never pry
   thin work. Bonded-joint compound prep and cure provide the printing precedent.

The original consumer saw
`? S0A: thin_wall_under_clamp has no vise grip-zone facts for custom holding.`
That historical finding is motivation, not a current capacity verdict.

## 2. Schema

### 2.1 Where the facts live

The shipped schema places tape under `consumables`, because it is used per setup:

| Hold | Inventory root | `kind` | Why there |
|---|---|---|---|
| Double-sided tape | `consumables.<id>` | `adhesive_tape` | Bought by the roll and used per setup. `ConsumableEntry` accepts a plain `{ name, products }` record or the typed tape record. |

Each capacity or stack input uses a fact-local record, following the existing
`LengthMeasurement` / `LimitsMeasurement` pattern:

```text
{ value, cite = "..." }                         # a datasheet or handbook value
{ value, measured = { status, by, date, instrument } }   # a shop measurement
```

The shipped `CitedFact` record carries `value`, `cite`, `measured` and `verify`
for non-length facts such as shear, peel and dwell. It is trusted only with a
nonblank citation or a complete measurement whose `status` is `"measured"`,
and no `verify = true` or `"unknown"`. A bare number, blank or `"unknown"` cite,
omitted status (`assumed`), `assumed`, `illustrative` or `verify = true` leaves
that fact as debt, as with M5 facts. A citation supports a datasheet property;
it is never treated as a measurement. The resolver does not parse `by` or
`instrument` prose.

Tape thickness is a stack dimension, like vise bed height, represented by a
`LimitsMeasurement` pair `[least, greatest]`. D4 requires the proposed stack
check to use a measured pair from a micrometer sample of the lot on hand. A
cited datasheet thickness or tolerance may print, but must remain `?` for
clearing the band.

Each strength also has `test` text naming its test method (D6), such as
`"PSTC-107 static shear, 1 kg, 23 °C"` or `"ASTM D1002 overlap shear"`.
The check requires known, nonblank text and does not parse it. Blank or
`"unknown"` text is debt, like an empty citation. The proposed sheet must print
the method beside capacity so the operator can identify the property being used.

### 2.2 Tape record

This schema fragment retains illustrative values and placeholder evidence. It
is not a complete trusted tape record or a recommendation:

```toml
[consumables.tape-3m-444]
kind = "adhesive_tape"
name = "3M 444 double-coated PET film tape"
products = ["3M 444, 50 mm roll"]
width_mm = 50.0                                    # roll width (illustrative nominal)
# [least, greatest] over a mic'd sample of the lot on hand (illustrative values).
thickness_mm = { value = [0.090, 0.110], measured = { status = "measured", by = "...", date = "...", instrument = "0-25 mm micrometer, 0.001" } }
shear_n_per_cm2 = { value = 3.0, test = "...", pairs = [{ work = "low_carbon_steel", seat = "aluminium" }], cite = "shop record harmonic-analyzer PR #1594" }   # value (shop record)
peel_n_per_cm = { value = 4.0, test = "...", pairs = [{ work = "low_carbon_steel", seat = "aluminium" }], cite = "..." }      # illustrative value
dwell_min = { value = 20, cite = "..." }           # the dwell the shear and peel are quoted at
surface_prep = "Clean both faces with isopropyl alcohol; dry; no oil film or chips."
apply = "Roll firmly end to end with a hand roller."
release = { method = "solvent", agent = "isopropyl alcohol", wait_min = 5, cite = "..." }
# or release = { method = "heat", temp_c = 70, wait_min = 2, cite = "..." }
```

| Field | Type | Meaning | Unknown or untrusted |
|---|---|---|---|
| `width_mm` | `MeasuredLength` (a catalogue nominal is enough) | Roll width. The proposed footprint is one seamless length, so its least width (short side of its minimum-area bounding rectangle) must not exceed `width_mm` | capacity `?` ("footprint 60.0 wide, roll 50.0: lay strips", a follow-up under D7) |
| `thickness_mm` | `LimitsMeasurement` | Applied layer thickness, least to greatest | proposed stack check `?`; draw the layer at the midpoint only for a known pair, otherwise report render debt without drawing it |
| `shear_n_per_cm2` | `CitedFact` + `test` + `pairs` | shear strength used as lateral and yaw capacity per cm² of contact, for the exact work/seat pairs it was established on (section 2.6) | capacity `?` |
| `peel_n_per_cm` | `CitedFact` + `test` + `pairs` | peel resistance per cm of peel front, for the exact work/seat pairs it was established on | lift `?` |
| `dwell_min` | `CitedFact` | minimum time between applying the work and cutting, at which the two strengths hold. A hard gate (D6): no build-up curve, and nothing is claimed for a shorter dwell | capacity `?`; the traveler prints a STOP in place of the dwell row |
| `surface_prep`, `apply` | text | printed in the apply step | STOP row in the apply step |
| `release` | `{ method = "solvent" \| "heat", agent \| temp_c, wait_min, cite }` | printed release step | STOP row in the release step |

### 2.3 How the hold references them

The shipped `Hold` schema has the optional `area` record. This plan fragment
shows its reference and pose, not a kernel-generated tape layer:

```toml
[setups.hold]
fixture = "thin-part-tape-subplate"     # the sub-plate (no tape solid any more)
area = { ref = "tape-3m-444", on = "plate" }
pose = { origin_mm = [0.0, 6.0, -0.100], x = [1.0, 0.0, 0.0], z = [0.0, 0.0, 1.0] }
```

- `ref` names a `consumables` `adhesive_tape` item; anything else is bad input.
- `on` names exactly one non-void solid of the holding fixture whose posed +z
  face is intended to carry the layer. A known missing or ambiguous name is bad
  input. Literal unknown identities or an unresolved solids list stay unresolved;
  a named but undrawable seat still needs the future seat check.
- The proposed coverage is one seamless tape length, trimmed to the work's
  footprint on that face. If the footprint exceeds `width_mm`, capacity remains
  `?`; seams must not earn unbonded area. D7 limits the initial capacity model
  to footprint coverage. Authored strips are a follow-up, not shipped coverage.

`hold.area` now carries tape identity; `hold.method` does not. Its kind is the
referenced consumable's `kind`.

The issue's `[setups.hold] kind = "custom"` is invalid: `Hold` has no `kind`
field and forbids extras. The fixture kind comes from `hold.fixture`; the
migration fragment below removes the invalid field.

### 2.4 What replaces the box solid

The proposed kernel layer will replace the authored tape box. This geometry is
not implemented:

- Shape: section the setup-entry stock at the seat plane, project that footprint
  onto the selected `on` face, then intersect it with the face.
- Thickness: draw the midpoint of `thickness_mm`, the nominal used by the pose.
  Exclude this compliant contact layer from `fixture_interference` against the
  stock it carries, but not against other fixtures, clamps or the cutter.
- Seat check: the gap from the posed `on` face to the setup-entry stock bottom
  must lie inside the `[least, greatest]` thickness pair. Outside it, report
  an error ("the work does not sit on the tape: gap 0.25, tape
  0.090 to 0.110"); an unknown pair gives `?`. This is intended to replace
  #294's interpenetration findings against the box and catch poses written for
  a different tape.

### 2.5 Migration (no compatibility shim)

The first migration row is shipped. The layer replacement and grip-zone outcome
remain requirements for the later kernel and rule work.

| Earlier form | Target form | Result for an unmigrated plan |
|---|---|---|
| `hold.method = "tape"` (any case, surrounding whitespace ignored) | `hold.area = { ref, on }` | Shipped bad input (exit 3), naming the new form, like retired `method = "retaining_compound"` in the `Joint` validator. |
| Tape box with `locates = "work underside"` in fixture `solids` | Delete it when the typed kernel layer ships | Shape cannot identify tape, and the engine never parses `locates`. The proposed phase 3 seat check must catch the wrong gap or interpenetration with the drawn layer. |
| `"tape"` in `thin_wall_under_clamp._PROTECTED` | Removal shipped; target area hold with no work clamps is `not_applicable` (no grip zone) | `method = "tape"` is already bad input. Plate-to-table clamps must not be treated as clamps on the work. This target outcome is not a capacity pass. |
| `"wax"`, `"soft_jaws"`, `"mandrel"` in `_PROTECTED` | Unchanged | Wax and CA area-hold support remains deferred under D9. |

The original migration review found no tape holds in the shipped examples; its
text search found only "taper" and "tapered". The named consumer migration was
harmonic-analyzer PR #1594's inventory and PR #1595's S0A/S0B holds. This is a
before/after comparison, not one valid TOML document: the tables repeat and the
replacement record is deliberately abbreviated.

```toml
# before (PR #1594 / #1595, abridged)
[fixtures.thin-part-tape-subplate]
kind = "custom"
solids = [
  { name = "plate", supply = "bought", shape = "box", at_mm = [-304.8, -76.2, -9.625], size_mm = [609.6, 152.4, 9.525] },
  { name = "tape", supply = "bought", shape = "box", at_mm = [-175.0, -20.0, -0.1], size_mm = [350.0, 40.0, 0.1], locates = "work underside", bears = "face" },
]
[setups.hold]
kind = "custom"            # bad input today
fixture = "thin-part-tape-subplate"
method = "tape"
pose = { origin_mm = [0.0, 6.0, 0.0], x = [1.0, 0.0, 0.0], z = [0.0, 0.0, 1.0] }

# after
[fixtures.thin-part-tape-subplate]
kind = "custom"
solids = [
  { name = "plate", supply = "bought", shape = "box", at_mm = [-304.8, -76.2, -9.525], size_mm = [609.6, 152.4, 9.525] },  # top at local z 0
]
[consumables.tape-3m-444]
kind = "adhesive_tape"
# ... as in section 2.2
[setups.hold]
fixture = "thin-part-tape-subplate"
area = { ref = "tape-3m-444", on = "plate" }
pose = { origin_mm = [0.0, 6.0, -0.100], x = [1.0, 0.0, 0.0], z = [0.0, 0.0, 1.0] }  # plate top at -t_nom
```

### 2.6 Every uncertainty and coefficient has a source

The proposed capacity and stack rules must obtain each coefficient and error
bound from a trusted source. Missing evidence leaves the finding `?`:

| Term | Source | Trusted when |
|---|---|---|
| tape shear, peel | tape `shear_n_per_cm2`, `peel_n_per_cm` | cited or measured, `test` named, and `pairs` contains the exact pair `{ work = <the stock material's class through cutting-data aliases>, seat = <the `on` solid's own `material` class through the same aliases> }`. The seat is the selected solid, never the fixture item: a steel fixture with an aluminium pad seats on aluminium. An `on` solid with no `material` leaves the pair `?` |
| plate flatness f | Shipped `flatness_mm` (`MeasuredLength`) on the `on` solid, covering its whole top face, footprint and touch area alike | measured (D4); the proposed recipe-A touch point must lie on that face (section 5.2) |
| touch error e | Proposed policy number `touch_error_mm`, with `numbers_cite`; not yet shipped | cited and not flagged by `numbers_verify` |
| mic error m | (recipe B only, out of scope under an area hold) the gauge's `accuracy_mm` plus half its `resolution_mm` | not consumed |
| DRO step r | the setup machine's existing `resolution_mm` (the DRO grid) | measured, as the coordinates rules already require |

A strength or coefficient applies only to the exact interfaces it was
established on. `pairs` records each one as `{ work, seat }`, with roles: a value
for steel work on an aluminium seat never stands for steel on steel, or for
aluminium work on a steel seat, even though the same classes appear. A setup
whose pair is not listed leaves the capacity `?` and names the pair. A tape
datasheet value usually comes from one test panel bonded on both faces (for
example `{ work = "stainless_steel", seat = "stainless_steel" }`), and it then
qualifies only that pair. Surface condition (finish, oxide, residual oil) has no fact in the
schema. It is gated instead by the printed `surface_prep` step, which is a STOP
when missing, and named as residue.

### 2.7 Input domains

Each consumed number has a domain. Before calculation, a rule must report an
out-of-domain value as debt (`?`), name the fact and domain, and never clamp it.
Section 8 requires one parameterized test per row. Schema failures stay bad input.

| Input | Domain | Outside it |
|---|---|---|
| `helix_deg` | finite, `0 ≤ β < 90`; the hand is `helix_hand`, never a sign | `?` (a signed or ≥ 90° value would flip or blow up `tan β`) |
| `D`, `z`, `fz`, `ap`, `ae` | `D > 0`, integer `z ≥ 1`, `fz > 0`, `ap > 0`, `0 < ae ≤ D` | `?` |
| `kc1`, `mc`, `radial_ratio` | `kc1 > 0`, `0 ≤ mc < 1`, `radial_ratio ≥ 0` | `?` |
| shear, peel, `dwell_min` | `> 0` (schema) | bad input |
| tape `thickness_mm` pair | `0 < t_lo ≤ t_hi` (schema) | bad input |
| `flatness_mm`, `touch_error_mm` | `≥ 0` | `?` |
| pull test `lift_n`, `front_mm`, `thickness_mm`, `dwell_min` | each `> 0` | the test does not qualify (model A) |
| recipe-A touch disc | the `zero.z` tool's resolved radius `> 0`, or a gauge block's half-width | `?` |
| tape `release.wait_min`, `temp_c` | `> 0` (schema) | bad input |
| `k` (`hold_capacity_factor_min`) | `≥ 1` | `?` |

## 3. Capacity model

This section specifies the unfinished area provider. The shipped force helper
does not compute contact area, capacity, moments or pull-test credit.

### 3.1 Contact area

The kernel, not the plan author, must derive contact area.

For each operation, section the in-process stock before and after the cut at
the seat plane (layer top), then split each section into connected islands.
The tape is laid once at setup entry and trimmed to the entry footprint
(D7: footprint coverage only).

```text
tape    A_i = island_i ∩ layer         holes the stock already has are absent from the section;
                                       a hole drilled later leaves tape behind, but no work bears on it
```

For each island, use the smaller before/after capacity for operation *k*.
Material-removal-only operations use the after-op value. Apply the operation's
whole force to the island being cut; distributing it among other islands would
credit support the cutter may not be loading.

A cutting operation on a kept island with `A = 0` is an error even when force
is unknown: zero capacity cannot meet positive demand. An offcut without
contact produces a loose-offcut `warn`.

### 3.2 Force capacities

```text
tape    lateral  C_xy,i = shear_n_per_cm2 × A_i / 100              (A in mm², 100 mm²/cm²)
tape    lift     C_z,i  = peel_n_per_cm × L_i / 10                 (model A, section 3.4; L_i in mm)
                 L_i    = min(D, w_i)                           (w_i: the island's local width at the cut:
                                                                  the least width of island_i within the disc of
                                                                  radius D about each of op k's cut positions on
                                                                  it, worst position; a 2 mm neck gives 2)
```

Ignoring weight is valid only when it helps hold the work down: the posed
`on` normal must be setup +Z on a vertical-spindle mill (`machine.kind = "mill"`,
setup +Z up). A horizontal spindle, angle plate, or seat facing down or sideways
leaves capacity `?` ("area hold orientation not proven: weight may load the
tape"). The inputs have no density fact from which to add gravity load.

### 3.3 Moment capacities

A cutter offset from an island's centroid loads the hold in yaw and overturning.
A force-only `shear × area` comparison could pass a long, narrow island that
cannot resist that moment. The proposed provider must check moments about the
traction region's centroid and about the seat edge:

```text
T_i      the traction region, the island's contact area A_i. Every lever below is
         measured from its centroid, the same origin the traction capacity is integrated about.
c_i      centroid of T_i
r_k      the farthest distance from c_i to op k's cut on that island
         (the kernel's removed volume of op k, intersected with the island's column)
h_k      the highest point the cutting force can act above the seat: the before-op stock
         top over the island's column minus the seat Z — the lever of F_xy. Never the deepest
         cut Z, which is zero for a cut to the seat while the flutes engage above it
J_i      ∫ |ρ| dA over T_i about c_i            (polar first moment, mm³)

yaw demand            M_yaw  = F_xy · r_k
tape yaw capacity     C_yaw  = shear_n_per_cm2 / 100 × J_i          (fully developed shear about c_i)
tape overturning      folded into lift: F_z,eff = F_z + F_xy · h_k / L_i, checked against C_z,i
```

Force and yaw share traction and must combine linearly:
`F_xy / C_xy + M_yaw / C_yaw ≤ 1 / hold_capacity_factor_min`. This bound
forgoes any benefit from an interaction curve. Unknown `r_k`, `h_k` or island
geometry, including unavailable kernel or removed-volume facts, leaves `?`.

Model A places axial load at the nearest free edge, its most eccentric position.
Moving the cutter toward the centroid can only relieve that load. The tape
overturning fold therefore adds only the lateral couple. Its lever is the
local peel front, capped by island width as in D2; no greater overturning
capacity follows from datasheet facts. A qualifying pull test (section 3.4)
replaces `C_z` for both direct lift and the folded term.

### 3.4 Lift: peel against the helix's axial pull (D2)

A right-hand-helix, right-hand-cut end mill lifts chips; its reaction pulls the
work toward the spindle. Tape resists through peel starting at a free edge.

D2 selects model A: a cutter-diameter peel front at the nearest footprint edge,
capped by local island width,
`C_z = peel_n_per_cm × min(D, w_i) / 10`. A narrow tab contributes only its own
width. Greater credit requires a measured pull test on the real setup. The
following proposed-schema fragment uses `{ ... }` placeholders and is not
runnable TOML:

```toml
[consumables.tape-3m-444.pull_tests.thin-part-tape-subplate]   # keyed by the fixture it was tested on
on = "plate"                                   # the seat solid the test was taped to
material_class = "low_carbon_steel"            # the pulled work's cutting-data material class
front_mm = { value = 40.0, measured = { ... } }       # the pulled work's width across the peel front
thickness_mm = { value = 2.75, measured = { ... } }   # the pulled work's thickness at the pulled end
lift_n = { value = 60.0, measured = { ... } }         # illustrative: the force that started the peel
dwell_min = { value = 20, measured = { ... } }   # the dwell before the pull, recorded with the test
work = "strap 40 x 2.75 1018, datum-B face down, pulled vertically at one end"   # printed; never parsed
```

The proposed protocol tapes the work as the HOLD specifies, waits the dwell,
then pulls vertically at one end until peel starts. Credit for island *i* at
operation *k* requires every machine-checkable match:

| Check | Pass when |
|---|---|
| fixture and seat | the key is the setup's `hold.fixture`, and `on` equals `hold.area.on` |
| tape | the test sits under the tape `hold.area.ref` names |
| material | `material_class` equals the setup stock's class (through cutting-data `aliases`) |
| width | the island's least width (the short side of its minimum-area bounding rectangle) is at least `front_mm` |
| thickness | the island's least work thickness over the seat (kernel section) is at least `thickness_mm` |
| footprint | the island is still the setup-entry footprint: no op so far has reduced or split it |
| dwell | `dwell_min` is at least the tape's `dwell_min`. A credited test also raises the setup's dwell gate to the test's `dwell_min`: the HOLD prints "cut no earlier than" from the test's dwell, so the work is never cut sooner than the bond the test measured |
| trust | `lift_n`, `front_mm`, `thickness_mm` and `dwell_min` are trusted measured facts; a bare, assumed or cited test dwell does not qualify, since the dwell gate is set from it |

Then the test sets the peel resistance per unit of front, `lift_n / front_mm`,
and the credit is that resistance over the cutter's own local front:
`C_z = lift_n × min(1, L_i / front_mm)` with `L_i = min(D, w_i)` from model A. A
40 mm end pull therefore credits a Ø9.525 cutter with 9.525/40 of its force,
never the whole end's force, and never more than the pull itself. Any failed
check leaves model A in force, and the finding names the check that failed; a
test never scales up to a longer front. What no field can carry (surface condition beyond the tape's printed
prep, a different pull location) stays residue, and the HOLD prints the test's
`work` text so the operator sees what was pulled. The pull-test schema lands in phase 4
(section 9), not phase 1. Until the shop pull-tests, the rocker strap stays
failing or `?`.

Rejected model B used the whole footprint width as the peel front. It required
a stiffness criterion that the inputs do not carry.

The axial sense comes from the tool's helix and its cutting hand together,
never from the cutting hand alone: a helix of the same hand as the cut (right
helix with right-hand cut, or left with left) evacuates chips up and lifts the
work; opposite hands push it down. The helix hand is its own tool fact,
`helix_hand`, separate from the cutting `hand` that selects spindle rotation.
Either one unknown is evaluated as a lift. That is a bound, not a default: a
result that passes as a lift also passes as a push.

## 4. Force model, shared with #158

### 4.1 One model, one place

The shipped private helper is
[`src/prechips/rules/_cutting_force.py`](../../src/prechips/rules/_cutting_force.py),
following `_envelope.py`, `_profile.py` and `_bench.py`. Its actual signature is
`milling_force(bundle, op, entry) -> CuttingForce`, with
`entry: "side" | "plunge" | "unknown"` supplied by the caller. `entry_of(path)`
classifies a coordinates level-path record. `CuttingForce` includes `status`
(`"computed"`, `"unknown"` or `"not_applicable"`), force components, axial sense,
inputs, debts and citations.

The original proposed interface below is retained as a schematic fragment. It
is not the current callable signature:

```python
milling_force(bundle, setup, op) -> CuttingForce
# CuttingForce: lateral_n, axial_n, axial_sense ("lift" | "push"),
#               inputs {name: value}, debts [reason], cite [source]
```

The future area provider and #158's clamp friction/preload provider must share
this helper. The proposed `hold_capacity` rule has one finding per `(setup:op)`
and selects its provider from the hold; neither provider is registered today.
`turning_deflection` keeps its separate constant-K_c static proxy (D5).

The shipped helper covers endmill-family tools (`endmill`, `endmill_set`, as in
`engagement`) on facing, pocketing and profile actions. Drill-family drilling,
reaming, tapping and counterboring load the work through thrust and torque;
their depth cannot stand in for peripheral `ap`. They return an unknown force,
with the unsupported-model reason. End-mill hole operations, including an
end-mill counterbore, also return unknown because axial entry is outside scope.
Noncutting actions (`fit`, `inspect`, `release`) are `not_applicable`.

Under the proposed always-required area rule (D3), unsupported force would reach
exit 4 until a thrust/torque or axial-entry model exists. That rule is not
implemented, so the helper alone does not impose this exit. The future
zero-capacity check must still error without force when a kept piece is cut free.

Peripheral force equations require side entry. They do not bound the end-cutting
thrust and torque of a plunge or helical ramp. The helper computes only when its
caller supplies proven side entry, reusing coordinates' plunge decision
([plunge rows](../cutting-data.md#plunge)). A path entering from outside stock or
into an open region qualifies; a plunge or unproven entry returns unknown with
"no axial-entry force model". A plunging pocket, slot, closed profile or
end-mill counterbore needs a separate future model.

### 4.2 Equations (Kienzle, peripheral milling)

```text
D, z, β          tool Ø, flutes, helix angle         (inventory tool/member)
fz               chip load, mm/tooth                 (the cited cutting-data row or tool chart the op already resolves)
ap               axial depth per pass = op doc_mm
ae               radial width of cut = op ae_mm, else D (bound: full slot)
kc1, mc          specific cutting force at h = 1 mm, and its exponent   (cutting-data [[material]])
k_r              radial / tangential force ratio                         (cutting-data [[material]])

φ_e    = arccos(1 − 2·ae/D)              engagement angle (π at ae = D)
h_max  = fz · sin φ_e  if φ_e ≤ π/2, else fz
n_e    = ceil(z · φ_e / 2π)              most teeth in the cut at once
F_t    = n_e · kc1 · ap · h_max^(1 − mc) every engaged tooth at h_max: an upper bound
F_xy   = F_t · sqrt(1 + k_r²)            lateral, in the seat plane
F_z    = F_t · tan β                     axial: lift when helix_hand equals the cutting hand,
                                         push when they differ, lift when either is unknown
```

The equations deliberately bound force by putting every engaged tooth at
maximum chip load. Missing inputs remain debt. Radial engagement is the sole
bounded exception: omitted or explicit `"unknown"` `ae_mm` uses full-slot
`ae = D`, recorded as `ae_basis = "bound_full_slot"`.

| Input | Source | Missing |
|---|---|---|
| `D`, `z` | resolved tool/member (`dia_mm`, `flutes`) | `?` |
| `β` | Shipped tool/member `helix_deg` (`CitedNumber`: a cited vendor nominal is enough, including 0). The helper enforces `0 ≤ β < 90`; positive-only `CitedFact` would reject the valid zero-helix case. | `?` |
| helix hand | Shipped tool/member `helix_hand`: `"right"` / `"left"`, separate from cutting `hand` | evaluated as lift (bound) |
| cutting hand | existing `hand`: `"right"` / `"left"` | evaluated as lift (bound) |
| `fz` | the op's resolved `chip_load_mm_per_tooth` (`speeds_feeds` resolution, unchanged) | `?` |
| `ap` | op `doc_mm` (> 0) | `?` |
| `ae` | Shipped op `ae_mm` (0 < ae ≤ D), else D | omitted or explicit unknown uses bound D |
| `kc1`, `mc`, `k_r` | Shipped `[[material]]` fields `kc1_n_per_mm2`, `mc`, `radial_ratio`, under the row's existing `cite` | `?` |

`contour.step_mm` is a raster step, not a width of cut: the first pass of a
raster can be a full slot, so it is not read as ae.

### 4.3 Margin policy

```text
k        = hold_capacity_factor_min
use_xy   = F_xy / C_xy,i + M_yaw / C_yaw,i
use_z    = F_z,eff / C_z,i                                (F_z,eff of section 3.3)
use      = use_xy + use_z                                 (shear and peel share one bond)
         (each over every island under op k, worst op of the setup reported)
pass     use ≤ 1 / k
error    use > 1 / k   with every input known and trusted, or zero capacity under a cutting op
?        any input unknown or untrusted, or k unknown or flagged
```

The proposed provider must add shear and peel usage because both load the same
bond. Separate comparisons would pass two uses of 0.49 at k = 2 while leaving
barely 1× combined margin. The proposed sheet prints the factor `1 / use`.

The planned `shop-policy.numbers.hold_capacity_factor_min` uses `numbers_cite`
and `numbers_verify` and starts at `"unknown"`. A true or unknown verify flag
keeps it unknown. D10 selects one factor for tape, future vacuum (#309) and
#158's clamps. A per-provider override would need a later use case.

D1 makes insufficient margin a hard `error`, like `vise` and
`fixture_interference`, based on declared workholding facts (PLAN §4.3).
Loss of hold can throw the part; PLAN §4.4's "lines only" dimensional proxies
are not the precedent. Unknown inputs remain `?`.

D3 requires `hold_capacity` for every area hold, regardless of `[required]`,
as with `centre_support`. Its unknown result would reach exit 4 because a
clampless hold has no fallback. #158's clamp provider would follow `[required]`
unless its design changes that decision. These exit and policy effects are
requirements for the unfinished rule, not current area-hold behavior.

### 4.4 Named residue (not modelled)

The future capacity finding must name these uncomputed PLAN §4.6 limits:
adhesive creep and Z compression under cutting load, heat- or coolant-softened
tape, trapped chips or burrs, free-state bow after release, entry/exit impact
peaks above the steady bound, and feeding a manual mill faster than the printed
feed. The planned `hold_capacity_factor_min` is the shop's allowance for them.

## 5. Z stack-up

### 5.1 The stack

The bonded underside cannot be touched to set Z. A frame may put Z0 there
(S0A: "Z0 on the raw strap underside"), but the zero recipe must reference a
reachable surface. The proposed Axis Set value follows this physical stack:

```text
plate top (the `on` face)    Z_p      posed; skimmed in place, flatness f over the footprint (measured)
tape layer                   t ∈ [t_lo, t_hi], nominal t_nom = (t_lo + t_hi) / 2
work underside               Z_p + t(x, y)
cut plane                    to_z, from Z0
```

The proposed `area_hold_stack` rule applies per area-hold setup when an
operation's thickness band runs from the seated face to the cut face. It must
add signed `[lo, hi]` terms in mm to the nominal cut using interval arithmetic,
then compare both endpoints with the feature's `[low, high]` band. Comparing
width alone could pass a narrow stack displaced beyond one band limit.

### 5.2 Which recipe carries which terms

Let P be the point where the zero is touched. For any point x under the cut,
each term is a signed interval added to the nominal thickness `to_z`:

Recipe A touches the plate top beside the work, using paper or a gauge block,
and prints `Axis Set Z = −t_nom + paper_mm`. The shipped schema field
`zero.z.at_mm = [x, y]` records point P in the setup frame. The future rule must
require it under an area hold and print it in HOLD ("touch the plate at X …,
Y …"). Kernel validation must project P onto the posed `on` face and check
the whole touch disc: the `zero.z` tool's resolved radius, or the gauge block's
half-width for a block touch. That disc must fit entirely on the top face
covered by `flatness_mm` and clear the work footprint and tape. Missing
`at_mm` or radius leaves `?`. Overhanging the plate, touching another solid or
overlapping the footprint is an error. The rule must never infer P from prose.

```text
thickness(x) = to_z + (t_nom − t(x)) + (Z_p(P) − Z_p(x)) + e_touch + e_dro
terms:         tape  [t_nom − t_hi, t_nom − t_lo]
               plate [−f, +f]        (f: the `on` solid's measured `flatness_mm`)
               touch [−e, +e]        (e: policy `numbers.touch_error_mm`, cited, unflagged)
               DRO   [−r/2, +r/2]    (r: the setup machine's measured `resolution_mm`, the DRO grid)
```

Recipe B (`measure_then_set`) measures the work at P before bonding, then
touches the top at P and prints `Axis Set Z = M + paper_mm`. It is outside the
initial area-hold stack model and must remain `?` ("zero Z from the seat face
(recipe A) under an area hold"). Proving that recipe would require a micrometer
that reaches across both faces at that same P before bonding. The schema has
no instrument-envelope facts for throat or jaw reach. The arithmetic below
retains the error propagation for a possible follow-up; its tape term is also
worse than recipe A's.

```text
thickness(x) = to_z + (t(P) − t(x)) + (Z_p(P) − Z_p(x)) + e_mic + e_touch + e_dro
terms:         tape  [t_lo − t_hi, t_hi − t_lo]   plate [−f, +f]   mic [−m, +m]
               touch [−e, +e]                     DRO [−r/2, +r/2]
               (m: the micrometer gauge's trusted `accuracy_mm` plus half its `resolution_mm`)
```

Recipe B carries the tape spread twice: it samples thickness at P and applies
that value elsewhere. Recipe A carries it once, with measured plate flatness.
The proposed rule must evaluate the authored recipe, not choose a different one
silently; the signed-term table explains the difference.

### 5.3 Outcomes

```text
T = to_z + Σ terms = [T_lo, T_hi]           (interval sum)
band [low, high]   = the feature's acceptance band between the seated and the cut face

low ≤ T_lo and T_hi ≤ high, all known       pass
T_lo < low or T_hi > high, all known        error  ("thickness 2.470–2.530 is outside 2.475–2.525:
                                                     tape ±0.010, plate ±0.005, touch ±0.010, DRO ±0.005")
any term unknown or untrusted               ?      (its measure: line names the fact)
```

Both endpoints are compared, never the width alone. A 0.040-wide stack about
`to_z = 2.520` is narrower than the 0.050 band, but it reaches 2.540 and is an
error.

Tape spread alone can make the band unprovable. Recipe A cannot fit when
`t_hi − t_lo` exceeds band width for any `to_z`; recipe B cannot fit when
`2(t_hi − t_lo)` does. Exact equality passes only with every other term zero
and `to_z` at band centre, so both endpoints meet the inclusive limits.
Changing the zero recipe cannot recover a spread that exceeds these bounds.
The remedy is a tighter measured lot, a different hold or a looser band.

### 5.4 Interaction with S0A/S0B (#294)

- S0B governs final thickness (2.5 ±0.025). S0A's faced side sits on
  fresh tape, and the thin strap is pressed into the layer, so the S0B
  thickness at x is `cut_B − Z_p(x) − t_B(x)`. That does not depend on S0A's
  errors, provided the strap conforms to the tape.
- S0A's errors affect S0B through clean-up. S0A's actual thickness is
  `T_A = [T_A,lo, T_A,hi]` from its own stack about 2.75. S0B's depth of cut
  must stay positive everywhere, or S0B leaves an uncut patch of S0A's face.
  The existing stock and coverage rules see only nominal stock. The proposed
  stack rule must add `T_A,lo − T_B,hi > 0` (the least S0A thickness above the
  highest S0B cut), and report `?` when either interval is unknown.
- S0A's raw-face clean-up needs `raw_min − T_A,hi > 0`, where
  `raw_min` is the least raw thickness (a stock fact; unknown is `?`) and
  `T_A,hi = 2.75 + (S0A width)/2` for a symmetric stack.
- Conformity remains an assumption. If the strap is too stiff or bows beyond
  what the tape can take up, it bridges: contact area drops and the stack stops
  following `t(x)`. Name this residue (section 4.4) and print the apply check
  "press flat; no daylight under the ends".
- The original #294 report identified a separate 0.25 Ø6.5 island over the hub
  footprint. That defect is outside this design. With flat entry stock, the
  proposed seat check replaces the tape-box interpenetration findings.

## 6. Traveler

### 6.1 Placement

These setup-sheet additions are proposed, not shipped. Apply and dwell belong
once per hold, following the bonded-joint prep/cure precedent:

- Apply rows and the dwell gate print in HOLD. D6 requires "if the dwell is not
  met: STOP, do not cut", with no shortened-dwell allowance.
- Capacity (lateral with yaw, lift with overturning) and Z stack print below the
  apply rows, naming the governing operation and the strength's `test`.
- The release step prints after the setup's last op, before "Ends with",
  as a numbered noncutting step: the tape's `release` (solvent or heat, then
  roll off, never pry thin work), runnable only with a known, cited record;
- each unknown prints its STOP form in place of the runnable row. It never
  prints a runnable row with `?` in it (#289 proposal 2). A computed margin
  below the policy factor is an error, so it prints the STOP line the sheet
  prints for any error.

### 6.2 Mock-up: S0B, tape on the sub-plate (recipe A)

The stop and touch positions, and every number other than the shop record's
133 cm² and 3.0 N/cm², are illustrative.

```text
HOLD — tape on sub-plate thin-part-tape-subplate (3M 444, lot thickness 0.090–0.110 measured)
  1  Clean the plate top and the strap's datum-B face with isopropyl alcohol; let dry.
     No oil film, no chips.
  2  Lay one length of 3M 444 (50 mm roll) along the strap footprint 350 × 40 on the
     plate; trim to the outline. No seams, wrinkles or overlaps under the strap.
  3  Peel the liner. Set the strap datum-B face DOWN on the tape against the end stop
     at X −175.0. Roll firmly end to end. Press flat: no daylight under the ends.
  4  Applied at ____:____.   Cut no earlier than ____:____ (dwell ≥ 20 min).
     If the dwell is not met: STOP — do not cut.
  HOLD CAPACITY  op 10 governs · shear 3.0 N/cm² (<test>) · peel 4.0 N/cm (<test>)
     lateral + yaw  85 N / 399 N + 15 040 N·mm / 37 340 N·mm = 1.6×  (policy ≥ 2.0×)
                    — STOP: hold not proven (cutter 175 mm from the strap centre)
     lift (model A) 46 N + 85 N × 2.75 / 9.525 = 70 N  vs  peel 4.0 N/cm × 0.95 cm = 3.8 N
                    — STOP: lift not proven; a pull test on this setup is the only way to claim more
  Z STACK  plate top Z −0.100 · tape 0.090–0.110 · strap underside Z −0.010 … +0.010
           thickness 2.470–2.530 vs band 2.475–2.525
           (tape ±0.010, plate ±0.005, touch ±0.010, DRO ±0.005)
           — STOP: band cannot be held with this tape lot

DRO ZERO
  Z  Touch the plate top beside the strap at X −190, Y 20 on paper 0.05.
     Axis Set Z = −0.100 + 0.050 = −0.050   (−0.100 = tape nominal, from the measured lot)

…ops 10, 20…

RELEASE — after op 20
  1  Flood the tape edge with isopropyl alcohol; wait 5 min.
  2  Lift one end by hand and roll the strap off the tape along its length.
     Never pry with a blade or screwdriver: thin work bends.
  3  Remove the residue from the strap and the plate with isopropyl alcohol.
```

The illustrative arithmetic requires the STOP lines shown. Clearing them would
need a qualifying measured pull test, enough yaw margin for the policy factor,
and a measured tape-lot spread whose full stack stays within both band limits.
The mock-up is not generated output, a machining instruction or acceptance evidence.

### 6.3 STOP forms (one per printed value)

These are requirements for the future renderer. No current area-hold row
implements this source-to-STOP table.

| Printed value | Source | STOP when |
|---|---|---|
| tape product, prep, apply text | tape record | missing or `"unknown"` |
| dwell minutes and the dwell gate | `dwell_min` | untrusted; and printed as a STOP condition when not met |
| shear and its test | `shear_n_per_cm2`, `test` | untrusted, or `test` missing |
| peel and its test | `peel_n_per_cm`, `test` | untrusted, or `test` missing |
| island area, yaw moment, polar moment | kernel sections, op removed volume | no kernel, or unresolved removed volume |
| lateral force, axial force | `milling_force` | any input untrusted, or an unsupported tool or action (drill family) |
| lateral + yaw factor, lift factor | section 4.3 | any of the above |
| pull-test lift and its work text | `pull_tests.<fixture>` | untrusted or not qualified (model A is printed instead, naming the failed check) |
| roll width vs footprint | `width_mm`, kernel footprint | width unknown, or footprint wider than the roll |
| policy factor | `hold_capacity_factor_min` | unknown or flagged |
| plate top Z, tape pair, underside range | pose, `thickness_mm` (measured) | pair unmeasured |
| stack terms and thickness interval | section 5 terms | any term unknown |
| Axis Set Z | recipe and `t_nom` | `t_nom` unknown |
| release method, agent or temperature, wait | tape `release` | missing, or its `cite` blank or `"unknown"`: a temperature or solvent is never printed without its source |

## 7. Operator step sequence and error propagation

This proposed sequence traces operator errors into the modeled quantities and
the explicitly unmodeled residue. It is not a supported shop procedure.

| # | Operator does | Physical reference | Printed number from | Error source | How the error reaches the cut or the hold |
|---|---|---|---|---|---|
| 1 | Skims the plate, or checks the skimmed plate (once per install) | table travel | none (fixture fact) | plate flatness f | stack term ±f (both recipes) |
| 2 | Cleans the plate and the work | none specified | prep text | residual oil or chips | contact area and shear (residue); chips also add to t(x) |
| 3 | Lays the tape over the footprint | plate top, work outline | outline 350 × 40 (manifest footprint) | seams, wrinkles, short coverage | area below the derived A (residue); thickness locally outside the pair |
| 4 | Seats the work and rolls it | end stop, plate top | stop X from the pose | work bridges instead of conforming | area loss; the stack stops following t(x) (residue; printed "no daylight") |
| 5 | Waits the dwell, writing both clock times | the clock | `dwell_min` | dwell cut short | strengths below the cited values; the printed gate is a STOP, so a short dwell is a stopped setup, not a reduced margin (D6) |
| 6 | Sets Z (recipe A: plate + paper) | plate top at P | `−t_nom + paper` | paper, touch feel, DRO step | touch and DRO terms; the tape mean enters as `t_nom − t(x)` |
| 7 | Cuts each op at the printed feed | none specified | feed from cutting data | feeds faster by hand | F_xy and F_z scale with fz^(1−mc) (residue; covered by the factor) |
| 8 | Releases (solvent or heat, roll off) | none specified | release text | prying | bends thin work: the free-state bow is residue, and prying is forbidden in print |

## 8. Test plan

The design requires #289's three checks: a resolver for each printed value,
one parameterized test per printed field, and operator perturbations.
[`test_area_hold_schema.py`](../../tests/test_area_hold_schema.py) covers shipped
schema and migration; [`test_cutting_force.py`](../../tests/test_cutting_force.py)
covers the shipped helper. Their existence is not a claim that tests ran for this
documentation change or that the remaining design passed.

Future capacity/stack unit tests should inject synthetic `bundle.kernel` island
sections; native geometry tests should use the shared `freecad_kernel` fixture.
The cases below retain the acceptance requirements for each phase.

### Schema and migration (phase 1)

- `adhesive_tape` records parse; unknown keys are rejected; each
  `CitedFact` trust state (cited, measured, bare, assumed, illustrative,
  `verify = true`, blank cite, blank or unknown `test`) resolves to trusted or
  debt as section 2.1 says. `thickness_mm` is trusted only as a measured pair.
- `static_shear_n_per_cm2` (the pre-decision name) is rejected as an unknown key.
- The legacy tape method is exit 3, naming `hold.area`; `"vacuum"` remains plain
  untyped text until #309. A nonexistent or wrong-category `ref`, or a known
  `on` with no single non-void seat, is exit 3. Literal unknown identities stay
  unresolved, as shipped input validation requires. The future phase 3 seat
  check must catch a leftover box without parsing `locates`.
- `"wax"` keeps its `thin_wall_under_clamp` pass (D9).

### Force model (`_cutting_force.py`)

- Hand-computed cases: ae = D and ae < D/2 (`h_max = fz·sin φ_e`), z = 2/3/4,
  the `n_e` ceiling exactly at a tooth boundary, β = 0 (no axial force); every
  `(helix_hand, hand)` pair: right/right and left/left lift, right/left and
  left/right push, and either unknown lifts.
- Each missing input leaves the result `?` naming that input; the ae bound is
  applied and reported as `ae_basis = "bound_full_slot"`.
- Drill, reamer and tap tools are `?` ("no thrust/torque force model");
  noncutting actions are `not_applicable`.
- Entry: a face sweep entering from outside the stock is computed; a pocket
  whose path plunges, an endmill counterbore, and an op whose entry the
  coordinates rule leaves unproven are `?` ("no axial-entry force model").

### Capacity and margin (`hold_capacity`, proposed)

- `use` exactly `1/k` (pass), just above (error), and `k`
  unknown or flagged (`?`).
- Moments: the same island and force pass with the cutter at the centroid and
  fail with it at the far end of a long, narrow island (yaw). A tall cut at a
  narrow island's edge raises the folded lift `F_z,eff`.
- Peel front: a 5 mm tab cut with a Ø10 cutter gets `L = 5`; a dumbbell island
  with 50 mm ends and a 2 mm neck, cut at the neck, gets `L = 2`. A cut to the seat
  keeps `h_k` at the before-op stock height, not zero.
- Seat material: the pair's seat comes from the `on` solid's `material`. A
  steel-bodied fixture with an aluminium `on` pad seats on aluminium; an `on`
  solid with no `material` leaves capacity `?`.
- Pairs: a value listed for `{ work = steel, seat = aluminium }` qualifies that
  setup, but not steel on steel or aluminium on steel; those leave capacity `?`,
  naming the pair.
- Stack sources: each of `flatness_mm`, `touch_error_mm` and the machine's
  `resolution_mm` missing or untrusted leaves the stack `?`, naming that fact.
- Combined loads: tape with `use_xy` and `use_z` each at 0.3 at k = 2 fails
  (sum 0.6 > 0.5), though each alone would pass.
- Pull test: a qualifying test raises `C_z` to `lift_n × min(1, L_i / front_mm)` (a
  40 mm end pull credits a Ø9.525 cutter 9.525/40 of it) and the printed dwell
  gate to the test's `dwell_min`; each failed check in
  the section 3.4 table (another fixture or seat, material class, a narrower or
  thinner island, a reduced footprint, a shorter dwell, an unmeasured field)
  falls back to model A and names that check.
- Coverage: a footprint whose least width equals the roll width passes; 0.1 mm
  wider leaves capacity `?`.
- Islands (tape): a profile op that splits the footprint is judged on the
  smallest island under the force. A kept piece cut free with zero area is an
  error with or without a force; an offcut is a loose-offcut warning.
- `hold_capacity` is `?` → exit 4 with an empty `[required]` (D3).
- Orientation: the seat facing setup +Z on a mill passes the orientation gate;
  a seat on an angle plate (normal along setup X) or on a lathe is `?`.
- `thin_wall_under_clamp` is `not_applicable` on an area hold with no clamps on
  the work.

### Stack (`area_hold_stack`, proposed)

- Recipe B under an area hold is `?` naming recipe A as the supported zero.
- Endpoints: `to_z` at the band centre with a total width equal to the band
  passes, and 0.001 wider is an error; a narrow stack about an off-centre
  `to_z` that crosses one limit is an error.
- A cited (unmeasured) pair is `?` (D4).
- The S0A→S0B clean-up row: positive, zero and negative `T_A,lo − T_B,hi`; the
  raw clean-up row with `raw_min − T_A,hi` at both signs.
- Seat check: a pose written for 0.10 tape with a 0.25 gap is an error.
- Recipe A touch point: a missing `zero.z.at_mm` or tool radius is `?`; a touch
  disc clear of the footprint on the `on` face passes; a centre 1 mm outside the
  footprint with a Ø9.525 tool overlaps it and is an error; off the
  plate, on another solid or inside the footprint is an error.
- Release: an uncited tape release prints the STOP; a cited one prints
  its steps.

### Operator perturbation (proposed)

- *Dwell cut short:* with `dwell_min` untrusted, no capacity is claimed and
  the HOLD prints the dwell STOP; with it trusted, the gate row prints the
  minimum and "if the dwell is not met: STOP". There is no build-up curve
  (D6), and the test pins that no input admits a shorter dwell.
- *Tape thicker than nominal:* the same plan with the measured pair moved from
  `[0.095, 0.105]` to `[0.095, 0.135]` turns the stack row from pass to error
  and moves the printed underside range. A pair that does not contain the
  pose's gap fails the seat check.
- *Footprint reduced by the cut:* a setup whose last op leaves a 20 × 20 island
  passes at op 10 and errors at the island-making op.
- *Zero a DRO step off:* recipe A with the DRO term at one step; the band
  verdict changes exactly at the step that moves an endpoint past a limit.

### Input domains

- One parametrized test per row of section 2.7: a value just inside the domain
  is used, and the boundary outside it (`helix_deg` = 90 or −30;
  a pull test with `front_mm` = 0;
  `ae` > D; `k` = 0.9) is `?` naming the fact and its domain.

### Printed values (proposed)

- One parametrized test per row of section 6.3: an unknown source prints that
  STOP and never a runnable row.
- One new example bundle, `examples/geometry/area-hold/` (a strap on tape,
  recipe A), with goldens, run under `validate_examples.py`.
- The blind machinist review (`scripts/machinist_review.py`) of the section 6.2
  mock-up, then of the shipped traveler, by the other model family. This is a
  gate for the coordinator, run with phase 6.

## 9. Phased implementation plan

The original plan used one PR per phase. Phases 1 and 2 have shipped as
prerequisites; phases 3 through 6 have not. The sizes are original estimates,
not current measurements or delivery commitments.

| Phase | Work | Contents and status | Original size estimate |
|---|---|---|---|
| 1 | schema, shipped | `CitedFact` (+ `test`, `pairs`); solid `flatness_mm` and `material`; `adhesive_tape` with `width_mm`; `hold.area`; `zero.z.at_mm`; migration errors; [`inventory.md`](../inventory.md) and [`plan.md`](../plan.md) fields. No capacity or stack rule consumes them. | ~350 lines + tests |
| 2 | force helper, shipped | `_cutting_force.py`; material `kc1_n_per_mm2`, `mc`, `radial_ratio`; tool helix angle/hand; op `ae_mm`; [`cutting-data.md`](../cutting-data.md) and [`rules-physics.md`](../rules-physics.md). Caller-supplied entry is part of the actual interface. | ~400 + tests |
| 3 | kernel, proposed | Before/after seat sections, islands, centroid, polar moment and per-island removed-volume extent; generated layer and seat check; `ENGINE_SOURCES` identity. | ~700 + geometry tests |
| 4 | capacity, proposed | `hold_capacity` area provider, force/yaw/lift/overturning, always-required behavior, shared factor and pull-test schema; finish the clamp-rule interaction and update [`rules-setup.md`](../rules-setup.md). Tape removal from `_PROTECTED` has already shipped. | ~500 + tests |
| 5 | stack, proposed | Signed `area_hold_stack` intervals and endpoints; recipe A, B as `?`; S0A-to-S0B and raw clean-up rows; update [`rules-coordinates.md`](../rules-coordinates.md). | ~400 + tests |
| 6 | traveler, proposed | Apply/dwell/capacity/stack/release and STOP rows; example bundle, goldens and blind machinist review. | ~600 + goldens |
| 7 | #158, separate design | Clamp provider (`n × μ × preload`, cited), shared factor and per-solid clearance listing. | separate design note in #158 |
| follow-up | separate issues | Vacuum (#309, D11); drill thrust/torque and axial entry; recipe B; authored strips (D7); wax and CA (D9). | separate issues |

Phases 1 and 2 require no kernel work. Phase 4 depends on 2 and 3; phase 6
depends on 4 and 5. None of these dependencies makes the overall hold design complete.

## 10. Worked example: the strap, S0B (illustrative arithmetic)

This retained calculation illustrates the proposed model. Its values and
rounding are not generated capacity findings or physical test results.

```text
Tool  3/8 in 4-flute HSS, D 9.525, z 4, β 30° (illustrative), right hand
Op    finish_face, ap = doc_mm 0.25, ae not declared → bound D; cut height h 2.75 above the seat
Data  fz 0.05 (illustrative), kc1 1500 N/mm², mc 0.25, k_r 0.4 (all illustrative)

φ_e = π, h_max = 0.05, n_e = ceil(4·π/2π) = 2
F_t  = 2 × 1500 × 0.25 × 0.05^0.75 = 79.3 N
F_xy = 79.3 × sqrt(1.16) = 85.4 N          (#295 estimates 60–90 N)
F_z  = 79.3 × tan 30° = 45.8 N, lift

Tape lateral  C_xy  = 3.0 N/cm² × 133 cm² (shop record) = 399 N
Tape yaw      J     = ∫|ρ| dA over a 350 × 40 rectangle = 1.245e6 mm³
              C_yaw = 0.030 N/mm² × 1.245e6 = 37 340 N·mm
              M_yaw = 85.4 × hypot(175, 20) = 15 040 N·mm (the face sweep reaches the strap ends)
              use   = 85.4/399 + 15 040/37 340 = 0.617 → 1.6×    error at k = 2.0 (illustrative k)
Tape lift A   F_z,eff = 45.8 + 85.4 × 2.75 / 9.525 = 70.5 N
              C_z     = 4.0 N/cm × 0.9525 cm = 3.8 N → 0.05×    error
Stack (recipe A) about 2.500: tape ±0.010, plate ±0.005, touch ±0.010, DRO ±0.005
                 → 2.470–2.530 vs 2.475–2.525 → error
Stack (recipe B, out of scope): tape ±0.020 + …                    → worse
```

The shop record gives 133 cm²; a plain 350 × 40 rectangle has 140 cm². The
future provider must use the kernel-derived stock section, not either authored
area. Under the illustrative assumptions:

- force alone would leave a 4.7× lateral margin, but the yaw moment of a
  cutter at the end of a 350 mm strap brings it to 1.6×;
- lift is not provable from datasheet peel, so until the shop pull-tests the
  strap stays failing or `?` (D2);
- a 0.020 lot spread already uses 40 % of the band.

## 11. Decisions (maintainer, 2026-10-17, on PR #296)

These decisions define the target. Only the schema/migration and force-helper
parts identified above are implemented.

| # | Question | Decision |
|---|---|---|
| D1 | Error status | An insufficient hold margin is a hard `error`, as a §4.3 workholding rule. Unknown inputs stay `?` (section 4.3). |
| D2 | Lift model | Model A, the cutter-Ø peel front, by default. Only a measured pull test recorded on the real setup can claim more. Until the shop pull-tests, the rocker strap stays failing or `?` (section 3.4). |
| D3 | Required | `hold_capacity` is always required for area holds (section 4.3). |
| D4 | Thickness evidence | The stack check accepts only a measured lot pair; a datasheet tolerance stays `?` (section 2.1). |
| D5 | Turning deflection | `turning_deflection` keeps its own constant-K_c proxy (section 4.1). |
| D6 | Shear and dwell | The field is `shear_n_per_cm2`, with a `test` naming the test method. `dwell_min` is a hard gate: a dwell not met is a STOP; no build-up curve (sections 2.2, 6.1). |
| D7 | Coverage | The initial model uses footprint coverage only; authored strips are a follow-up (section 2.3). Schema delivery alone does not implement coverage. |
| D8 | Gaskets | Raised or compressible gaskets are out of scope for now (now part of #309). |
| D9 | Wax and CA | Their area-hold support remains a later issue (section 2.5). The existing wax protection path is unchanged. |
| D10 | Margin number | One shared `hold_capacity_factor_min` for tape, a later vacuum provider and #158's clamps; a per-provider override can come later if a case needs it (section 4.3). |
| D11 | Vacuum (owner, 2026-10-17, after design round 19) | Vacuum holds are deferred: the seal circuit cannot be derived from the work outline without recorded groove geometry, and a cord on a flat face is a compressible gasket (D8). The vacuum model so far is kept in #309. This design and its phases cover adhesive tape only. |

The design review added the following constraints after the maintainer's
decisions; they were not separate maintainer rulings:

- yaw and overturning checks, with the linear force/moment interaction, every
  lever measured from the traction centroid, the peel front and its lever
  capped by the island's least width, and the overturning lever taken at the
  highest point the flutes can engage (section 3.3);
- combined loads share one capacity: tape adds its shear and peel uses
  (section 4.3);
- stack endpoints compared with the band, not the width alone, and both
  clean-up rows built from interval endpoints (sections 5.3, 5.4);
- the force model scoped to end-mill milling with proven side entries: drill
  family, plunge and unproven entries are `?` (section 4.1); the lift sense
  comes from a separate `helix_hand` together with the cutting `hand`
  (sections 3.4, 4.2);
- pull tests qualify only by machine-checkable, trusted, positive fields; their
  credit scales to the cutter's local front, and a credited test raises the dwell
  gate to its own dwell (section 3.4);
- strengths apply only to the exact `{work, seat}` pairs they were established
  on, with the seat taken from the `on` solid's own `material`; every stack
  uncertainty has a named, trusted source; every consumed number has a domain
  (sections 2.6, 2.7);
- the tape's `width_mm` bounds footprint coverage, so seams are never credited
  (section 2.3);
- releases print only with a cited record (section 6.1);
- recipe A's touch point is a plan field, `zero.z.at_mm`, and the whole touch
  disc must land on the measured seat face, clear of the work; recipe B (zero
  from the work top) is out of scope under an area hold and stays `?`
  (section 5.2);
- round 20: the orientation gate (weight ignored only where it helps), the local
  peel width at the cut, and the release wait domain (sections 3.2, 3.4, 2.7);
- vacuum rounds 1 through 19 considered a fixed seal circuit, residual contact
  load after lift, gauge error and ambient bound. D11 deferred that model to
  #309 because of the missing seal geometry.

## 12. Open review notes (follow-ups for phases 2–6)

The owner stopped Codex review after 20 rounds. The findings below retain their
review provenance and implementation disposition; they do not certify the
unimplemented phases.

### Design changes after round 20

Round 20 reviewed `82a3850`. Commit `6f7c68c` changed three points without a
recorded follow-up review in the original design history:

- Local peel front (§3.2, §3.4): use `L_i = min(D, w_i)`. Phase 3 must emit
  island outlines and sampled cut points; phase 4 must compute local width and
  test both the 5 mm tab and 2 mm neck.
- Orientation (§3.2): ignore weight only for a +Z-facing seat on a mill.
  Phase 3 must emit `seat_normal`; phase 4 must check angle-plate and lathe cases.
- Release domains (§2.7): phase 1 now rejects nonpositive `wait_min` and
  `temp_c`. This schema constraint is shipped; it does not implement release rows.

### Answered and deferred findings

The P1 finding *eccentric axial lift in tape overturning* on `f6cf60a` asked
for an axial lever about the centroid. The design answer is unchanged: model A
already places the load at the nearest free edge (§3.3). Phase 4 still needs
the regression case showing the same `use_z` at centroid and edge.

Round 19's seal-groove and available-atmosphere findings belong to the deferred
vacuum design (D11, #309).

### Code-PR dispositions

- #310, undrawn seat: shipped input validation permits a named but untrusted or
  incomplete seat. Phase 3 must emit `area_hold.reason`; the future seat/stack
  consumer must leave `?`, never pass.
- #312, explicit `ae_mm = "unknown"`: the shipped helper uses full-slot `ae = D`,
  just as for omission, because force cannot grow past the full-slot `ae = D`
  bound in this model. This is a resolved helper contract, not an open capacity
  check. The original review described choosing debt instead as a one-line
  `_cutting_force.py` change; that is historical change-size commentary, not a
  compatibility promise. It would require a deliberate behavior change.
- #312, caller-supplied entry: shipped `milling_force(bundle, op, entry)` takes
  `"side"`, `"plunge"` or `"unknown"`. `entry_of(path)` also exists. Phase 4 still
  needs to obtain the coordinates level path and pass that classification into
  the area provider. The historical §4.1 sketch uses `(bundle, setup, op)`;
  the actual helper uses `(bundle, op, entry)`.
