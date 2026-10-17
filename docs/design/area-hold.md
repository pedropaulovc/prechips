# Design: typed area hold (adhesive tape or vacuum)

Status: **design agreed, not implemented.** Issue
[#295](https://github.com/pedropaulovc/prechips/issues/295), sharing its force
side with [#158](https://github.com/pedropaulovc/prechips/issues/158). None of
this document is shipped behaviour: no schema, rule, kernel output or traveler
row described here exists yet. It follows the design-first rule from
[#289](https://github.com/pedropaulovc/prechips/issues/289): it writes down the
operator's step sequence, the physical reference behind every printed number,
and how each step's error reaches the cut or the hold, before any engine code.
The maintainer decided all ten open questions on PR #296 (2026-10-17); they are
recorded as D1–D10 in section 11 and the body follows them.

Motivating case: harmonic-analyzer #1577, rocker route v3, setups S0A/S0B (the
same strap setups as [#294](https://github.com/pedropaulovc/prechips/issues/294)).
The owner ruled on 2026-10-17 that the 350 × 40 × 3.0 1018 strap blank is faced
first, both sides, to 2.5 ±0.025, on a double-sided-tape hold, with no clamp
over the cut face. The shop record is harmonic-analyzer PR #1594: 3M 444 PET
film tape (0.10 mm) on a skimmed MIC-6 sub-plate.

**Numbers in this document.** Values quoted from #295 or the shop record are
marked *(shop record)*. Every other number (kc1, mc, the radial-force ratio,
helix angle, peel, tape lot limits, vacuum level, friction) is **illustrative
arithmetic** chosen to show the formulas working. None is a datasheet figure, a
measurement or a recommendation, and none may be copied into an inventory.

## 1. Problem

prechips has no typed hold whose capacity comes from contact area. Today a plan
can only:

- write `hold.method = "tape"` (free text, read only by
  `rules/thin_wall_under_clamp.py` `_PROTECTED`, where it turns a thin-wall
  error into a pass), and
- draw the tape layer as a `custom` fixture box solid with
  `locates = "work underside"`, `bears = "face"`.

Nothing then checks:

1. **Capacity.** Tape shear × area, or vacuum × sealed area × μ, against the
   op's lateral cutting force, and lift resistance against the helix's axial
   pull.
2. **Identity.** Tape product, thickness and dwell, or vacuum level and gasket
   inset, as typed inventory facts rather than a box solid plus a note.
3. **Stack-up.** The tape layer sits between the locating plate and the work,
   so its thickness and the spread of that thickness belong in the Z stack the
   part's thickness band is cut against.
4. **Release.** The traveler should print the release step (heat or solvent,
   then roll the work off; never pry thin work), as it already prints the
   compound's prep and cure for a bonded joint.

The only hold-specific output today is
`? S0A: thin_wall_under_clamp has no vise grip-zone facts for custom holding.`

## 2. Schema

### 2.1 Where the facts live

Tape is a consumable and a vacuum chuck is equipment, so they live in different
inventory roots:

| Hold | Inventory root | `kind` | Why there |
|---|---|---|---|
| Double-sided tape | `consumables.<id>` | `adhesive_tape` | It is used up per setup and bought by the roll. Today's `Consumable` is only `{ name, products }`; it becomes a discriminated union of the plain record and the typed tape record. |
| Vacuum chuck | `fixtures.<id>` | `vacuum` | It is a fixture with a body (`solids`), a gauge and a pump, like any other fixture item. |

Every capacity or stack fact is a **fact-local record**, following the existing
`LengthMeasurement` / `LimitsMeasurement` pattern:

```text
{ value, cite = "..." }                         # a datasheet or handbook value
{ value, measured = { status, by, date, instrument } }   # a shop measurement
```

A new `CitedFact` record (`value`, `cite`, `measured`, `verify`) carries the
non-length facts (shear, peel, dwell, vacuum, friction). It is trusted when it
has a non-blank cite or a complete `measured` record whose `status` is
`"measured"`, and no `verify = true` / `"unknown"`. A bare number, an empty or
`"unknown"` cite, an omitted status (`assumed`), `assumed`, `illustrative` or
`verify = true` is **debt** for that fact only, exactly as for M5 facts. A
cite is evidence for a datasheet property. It is never read as a measurement,
and a measurement's `by`/`instrument` prose is never parsed.

The tape thickness is a **stack dimension**, like a vise's bed height, so it is
a `LimitsMeasurement`, a `[least, greatest]` pair. **Decided (D4):** the stack
check accepts only a measured pair, a mic'd sample of the lot on hand. A
datasheet thickness or tolerance, even cited, stays `?`; it may be printed but
cannot clear a band.

The two strengths carry a required `test` text naming the test method the value
comes from (D6), for example `"PSTC-107 static shear, 1 kg, 23 °C"` or
`"ASTM D1002 overlap shear"`. The engine checks only that it is present and
known, and never parses it. A blank or `"unknown"` `test` is debt, as an empty
cite is. The traveler prints it beside the capacity line, so the reader sees
which property the margin rests on.

### 2.2 Tape record

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
| `width_mm` | `MeasuredLength` (a catalogue nominal is enough) | roll width. Footprint coverage is one seamless length, so the footprint's least width (the short side of its minimum-area bounding rectangle) must be at most `width_mm` | capacity `?` ("footprint 60.0 wide, roll 50.0: lay strips", a follow-up under D7) |
| `thickness_mm` | `LimitsMeasurement` | applied layer thickness, least–greatest | stack check `?`; layer drawn at the midpoint only when the pair is known, otherwise not drawn (render debt) |
| `shear_n_per_cm2` | `CitedFact` + `test` + `pairs` | shear strength used as lateral and yaw capacity per cm² of contact, for the exact work/seat pairs it was established on (section 2.7) | capacity `?` |
| `peel_n_per_cm` | `CitedFact` + `test` + `pairs` | peel resistance per cm of peel front, for the exact work/seat pairs it was established on | lift `?` |
| `dwell_min` | `CitedFact` | minimum time between applying the work and cutting, at which the two strengths hold. A hard gate (D6): no build-up curve, and nothing is claimed for a shorter dwell | capacity `?`; the traveler prints a STOP in place of the dwell row |
| `surface_prep`, `apply` | text | printed in the apply step | STOP row in the apply step |
| `release` | `{ method = "solvent" \| "heat", agent \| temp_c, wait_min, cite }` | printed release step | STOP row in the release step |

### 2.3 Vacuum record

```toml
[fixtures.vacuum-chuck-12x18]
kind = "vacuum"
vacuum_kpa = { value = 80.0, cite = "..." }          # illustrative; gauge vacuum below atmosphere
seal = "laid_cord"                                  # a gasket cord laid on the work's outline each setup
gasket_inset_mm = { value = 3.0, measured = { ... } } # work outline to the cord's centreline
friction = { value = 0.2, pairs = [{ work = "low_carbon_steel", seat = "aluminium" }], cite = "..." }   # illustrative; work on the chuck face, dry
surface_prep = "Wipe the chuck face and the work underside clean and dry."
release = { steps = "Close the chuck valve and open the vent; wait until the gauge reads 0; lift the work straight up.", cite = "..." }
gauge = "chuck-vacuum-gauge"                          # inventory gauge the operator reads
solids = [ { name = "face", shape = "box", ... } ]    # the chuck body, as for any fixture
```

| Field | Type | Meaning | Unknown or untrusted |
|---|---|---|---|
| `vacuum_kpa` | `CitedFact` | the least gauge vacuum at which capacity is claimed; the operator must read at least this before cutting | capacity `?`; STOP in place of the gauge row |
| `seal` | `"laid_cord"` | how the seal circuit is made. `laid_cord`: a gasket cord laid in the chuck's open-grid grooves along the work's outline, `gasket_inset_mm` inside it, at every setup. The HOLD prints the lay step, and the gauge reading proves the circuit closed. Fixed-groove chucks, whose circuit is the groove pattern rather than the work's outline, need their groove geometry recorded and are a follow-up | capacity `?` ("seal circuit not recorded") |
| `gasket_inset_mm` | `MeasuredLength` | inset of the cord's centreline inside the work outline | sealed area `?` |
| `friction` | `CitedFact` + `pairs` | static μ of the work on the chuck face, for the exact work/seat pairs it was established on (section 2.7) | capacity `?` |
| `surface_prep` | text | printed in the vacuum apply step | STOP row in the apply step |
| `release` | `{ steps, cite }` | printed vacuum release step (valve, vent, gauge at 0, lift) | STOP row in the release step, also when `cite` is blank or unknown |
| `gauge` | `str` | inventory gauge read at the chuck: an item of kind `vacuum_gauge` with trusted `range_kpa` `[lo, hi]`, `resolution_kpa` > 0 and `accuracy_kpa` >= 0. A displayed reading R proves only `R − accuracy_kpa − resolution_kpa / 2`, so the HOLD prints the minimum reading `P = ⌈(vacuum_kpa + accuracy_kpa + resolution_kpa / 2) / resolution_kpa⌉ × resolution_kpa`, and `P` itself must lie inside `range_kpa` | capacity `?` and STOP in place of the gauge row when the gauge is missing, of another kind, its range, resolution or accuracy is unknown, or `P` is outside the range |

Vacuum assumes the work seats metal-to-metal on the chuck face, with the gasket
in a groove, so the gasket adds no Z term. Raised or compressible gaskets the
work sits on are out of scope (D8). The seal line is fixed at setup entry
(section 3.1).

### 2.4 How the hold references them

`Hold` gains one optional record, `area`:

```toml
[setups.hold]
fixture = "thin-part-tape-subplate"     # the sub-plate (no tape solid any more)
area = { ref = "tape-3m-444", on = "plate" }
pose = { origin_mm = [0.0, 6.0, -0.100], x = [1.0, 0.0, 0.0], z = [0.0, 0.0, 1.0] }
```

- `ref` names a `consumables` `adhesive_tape` item, or a `fixtures` `vacuum`
  item. A vacuum `ref` **must** be the same item as `fixture`: the pressure,
  friction and gauge belong to the chuck whose face `on` names, and a `ref` naming
  another vacuum fixture is bad input.
- `on` names the solid of the holding fixture whose posed +z face carries the
  layer (for tape) or is the chuck face (for vacuum). Exactly one trusted solid
  must be named; otherwise the input is bad.
- Coverage is the work's footprint: one seamless length of tape, trimmed to the
  work outline on that face. A footprint wider than the tape's `width_mm` can't
  be covered that way and leaves capacity `?`; the engine never credits area
  that seams would leave unbonded. Phase 1 supports footprint coverage only (D7); authored strips are
  a follow-up.

`hold.method` stops being the carrier of the hold type. A hold with `area` is
an area hold; its kind is the referenced item's `kind`.

Note that the issue's snippet writes `[setups.hold] kind = "custom"`. `Hold` has
no `kind` field and forbids extra keys, so that line is bad input today. A
hold's kind is always the inventory kind of `hold.fixture`, and the migrated
form below drops it.

### 2.5 What replaces the box solid

The kernel builds the layer from the typed facts, instead of reading it from
`solids`:

- **Shape:** the setup-entry stock's footprint on the `on` face, i.e. the
  section of the stock at the seat plane, projected onto that face and
  intersected with it.
- **Thickness:** drawn at the midpoint of `thickness_mm` (the nominal the pose
  is written to). It is a compliant contact layer: it is excluded from
  `fixture_interference` against the stock it carries, but not against other
  fixtures, clamps or the cutter.
- **Seat check.** The gap between the posed `on` face and the setup-entry
  stock bottom must lie inside `thickness_mm` `[least, greatest]`. Outside that
  pair it is an error ("the work does not sit on the tape: gap 0.25, tape
  0.090–0.110"); with an unknown pair it is `?`. This replaces the
  interpenetration findings #294 reports against the box solid, and it catches
  a pose written for a different tape.
- Vacuum draws no layer. The seat check is the existing contact of the stock
  bottom with the `on` face.

### 2.6 Migration (no compatibility shim)

| Today | After | Result for an unmigrated plan |
|---|---|---|
| `hold.method = "tape"` or `"vacuum"` (any case) | `hold.area = { ref, on }` | Bad input (exit 3), with a message naming the new form, like the retired `method = "retaining_compound"` (`model.py` `Joint` validator). |
| tape box solid with `locates = "work underside"` in a fixture's `solids` | deleted; the layer comes from `area` | Not detectable as tape by shape. A fixture that is referenced by an `area` hold and still carries a solid whose `locates` names the work underside is bad input, because two seats are declared. |
| `"tape"` in `thin_wall_under_clamp._PROTECTED` | removed; an area hold with no clamps on the work makes the rule `not_applicable` (no grip zone); clamps that hold the plate to the table are not on the work | `"tape"` in `method` is already bad input (first row). |
| `"wax"`, `"soft_jaws"`, `"mandrel"` in `_PROTECTED` | unchanged | Wax and CA are also area holds, but they stay in `_PROTECTED` for a later issue (D9). |

The shipped examples use no tape or vacuum hold (`rg tape examples` finds only
"taper" and "tapered"), so nothing in this repository migrates. The consumer
change is harmonic-analyzer PR #1594's inventory and PR #1595's S0A/S0B holds:

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

### 2.7 Every uncertainty and coefficient has a source

No rule invents a coefficient or an error bound. Each one the capacity and stack
rules consume comes from a trusted fact, otherwise the finding is `?`:

| Term | Source | Trusted when |
|---|---|---|
| tape shear, peel | tape `shear_n_per_cm2`, `peel_n_per_cm` | cited or measured, `test` named, and `pairs` contains the exact pair `{ work = <the stock material's class through cutting-data aliases>, seat = <the `on` solid's own `material` class through the same aliases> }`. The seat is the selected solid, never the fixture item: a steel fixture with an aluminium pad seats on aluminium. An `on` solid with no `material` leaves the pair `?` |
| vacuum friction | chuck `friction` | the same exact-pair check, for the work and the `on` solid (the chuck face) |
| plate flatness f | new `flatness_mm` (`MeasuredLength`) on the `on` fixture solid: the flatness of that solid's **whole** top face, footprint and touch area alike | measured (a stack dimension, as D4); the recipe-A touch point must lie on that face (section 5.2) |
| touch error e | new policy number `touch_error_mm`, with `numbers_cite` | cited and not flagged by `numbers_verify` |
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

### 2.8 Input domains

Every number the capacity and stack rules consume has a domain, checked before
it is used. A value outside its domain is debt (`?`), never clamped, and the
finding names the fact and its domain. One parametrized test per row (section 8).

| Input | Domain | Outside it |
|---|---|---|
| `helix_deg` | finite, `0 ≤ β < 90`; the hand is `helix_hand`, never a sign | `?` (a signed or ≥ 90° value would flip or blow up `tan β`) |
| `D`, `z`, `fz`, `ap`, `ae` | `D > 0`, integer `z ≥ 1`, `fz > 0`, `ap > 0`, `0 < ae ≤ D` | `?` |
| `kc1`, `mc`, `radial_ratio` | `kc1 > 0`, `0 ≤ mc < 1`, `radial_ratio ≥ 0` | `?` |
| shear, peel, `vacuum_kpa`, `dwell_min` | `> 0` (schema) | bad input |
| `friction` | `0 < μ ≤ 1` | `?` |
| tape `thickness_mm` pair | `0 < t_lo ≤ t_hi` (schema) | bad input |
| `gasket_inset_mm`, `flatness_mm`, `touch_error_mm` | `≥ 0` | `?` |
| vacuum gauge | kind `vacuum_gauge`; range, resolution and accuracy as section 2.3 | `?` |
| pull test `lift_n`, `front_mm`, `thickness_mm`, `dwell_min` | each `> 0` | the test does not qualify (model A) |
| recipe-A touch disc | the `zero.z` tool's resolved radius `> 0`, or a gauge block's half-width | `?` |
| `k` (`hold_capacity_factor_min`) | `≥ 1` | `?` |

## 3. Capacity model

### 3.1 Contact area

The kernel derives the area. The plan does not author it.

For each op of an area-hold setup, the kernel takes the in-process stock
**before** and **after** the op and sections each at the seat plane (the layer
top for tape, the chuck face for vacuum). The section is split into connected
**islands**. The tape layer is laid once, at setup entry, trimmed to the
setup-entry footprint (D7: footprint coverage only).

```text
tape    A_i = island_i ∩ layer         holes the stock already has are absent from the section;
                                       a hole drilled later leaves tape behind, but no work bears on it
```

**Vacuum seals once, at setup entry.** The only seal supported is a
`seal = "laid_cord"` circuit the operator lays along the setup-entry outline at
`gasket_inset_mm`, so `S` below is a physical cord the HOLD prints, not an
assumed groove. The cord stays where it was laid while the cut changes the
work, so the seal circuit is fixed when the work is seated:

```text
seal    S   = erode(setup-entry footprint, gasket_inset_mm)
              empty S (work narrower than 2 × inset), or any through-opening of the
              setup-entry stock inside S                         → A_seal = 0 from setup entry
open    an op opens the chamber when its after-op stock has any through-opening
        inside S, or its cut crosses the seal line S down to the seat plane
              → A_seal = 0 for that op and every later op of the setup
vacuum  A_seal = area(S ∩ after-op section) while the chamber is closed
```

New cut edges never get a seal of their own. A profile that splits the work
inside the seal opens the chamber, so its islands are not credited
independently. The rule names the op that opens it.

The capacity for op *k* uses the **smaller** of its before- and after-op values
for each island, which is the after-op value for any op that only removes
material. All of the op's force is assumed to act on the island being cut,
which is conservative because the force goes to whichever island the cutter
is in.

**Zero capacity needs no force.** When an island under a cutting op has
`A = 0` (a kept piece cut free with no contact, or an opened vacuum chamber),
the finding is an error even if the op's force is unknown: no positive demand
fits under zero capacity. An offcut with no contact is a loose-offcut `warn`.

### 3.2 Force capacities

```text
tape    lateral  C_xy,i = shear_n_per_cm2 × A_i / 100              (A in mm², 100 mm²/cm²)
tape    lift     C_z,i  = peel_n_per_cm × L_i / 10                 (model A, section 3.4; L_i in mm)
                 L_i    = min(D, w_i)                           (w_i: the island's least width, the short
                                                                  side of its minimum-area bounding rectangle)
vacuum  normal   N_i    = vacuum_kpa × A_seal,i / 1000             (kPa·mm² → N)
vacuum  lateral  C_xy,i = friction × N_i
vacuum  lift     C_z,i  = N_i
```

The part's weight is ignored. It is small, it only helps, and adding it would
need a density fact.

### 3.3 Moment capacities

A cutter away from an island's centroid also imposes moments. Comparing only
total force with `shear × area` or `μN` would pass a long, narrow island that
the distributed traction cannot hold against the cutting moment. Each island is
therefore also checked for yaw (in the seat plane) and overturning (about a
seat edge):

```text
T_i      the traction region: the island's contact area for tape (A_i), the sealed area
         S ∩ island_i for vacuum. Every lever below is measured from its centroid, the same
         origin the traction capacity is integrated about.
c_i      centroid of T_i
r_k      the farthest distance from c_i to op k's cut on that island
         (the kernel's removed volume of op k, intersected with the island's column)
h_k      the highest point the cutting force can act above the seat: the before-op stock
         top over the island's column minus the seat Z — the lever of F_xy. Never the deepest
         cut Z, which is zero for a cut to the seat while the flutes engage above it
J_i      ∫ |ρ| dA over T_i about c_i            (polar first moment, mm³)
d_i      the least distance from c_i to the convex-hull boundary of T_i

yaw demand            M_yaw  = F_xy · r_k
tape yaw capacity     C_yaw  = shear_n_per_cm2 / 100 × J_i          (fully developed shear about c_i)
vacuum yaw capacity   C_yaw  = friction × vacuum_kpa / 1000 × J_i
overturning demand    M_ot   = F_xy · h_k + F_z · r_k               (lift sense only)
vacuum overturning    C_ot   = N_i · d_i                            (uniform pressure, tipping about the nearest hull edge)
tape overturning      folded into lift: F_z,eff = F_z + F_xy · h_k / L_i, checked against C_z,i
```

The force and yaw checks combine linearly, because they share the same
traction: `F_xy / C_xy + M_yaw / C_yaw ≤ 1 / hold_capacity_factor_min`. That is
conservative; it is a bound that forgoes the interaction curve's benefit. The
same combination applies to vacuum overturning with lift. An unknown `r_k`,
`h_k` or island geometry (no kernel, an unresolved removed volume) leaves the
finding `?`.

Model A already places the axial load at the nearest free edge, the most
eccentric position it can take, so moving the cutter toward the centroid can
only relieve the tape: the `F_z · r_k` part of `M_ot` is the peel the edge front
already carries. The tape overturning fold adds only the lateral couple, using
model A's local front of length D as its lever, capped like the front itself. It is consistent with D2 and is the only tape
overturning claim datasheet facts can make. A pull test (section 3.4) replaces
`C_z` for both the direct lift and the folded term.

### 3.4 Lift: peel against the helix's axial pull (D2)

A right-hand-helix, right-hand-cut end mill (the usual one) lifts its chips,
and the reaction pulls the work **up** toward the spindle. Tape resists by
peel, which starts at a free edge.

**Decided (D2): model A.** The peel front is the cutter Ø at the nearest
footprint edge, capped by the island's width: `C_z = peel_n_per_cm × min(D, w_i) / 10`.
A tab narrower than the cutter has only its own width to peel. Only a **measured pull test
recorded on the real setup** can claim more:

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

The test protocol is fixed: tape the work as the HOLD prints, wait the dwell,
then pull vertically at one end until the peel starts. A test qualifies for
island *i* at op *k* only when **every** machine-checkable field matches:

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

Then `C_z = lift_n`, unscaled. Any failed check leaves model A in force, and
the finding names the check that failed; a test never scales to a different
work. What no field can carry (surface condition beyond the tape's printed
prep, a different pull location) stays residue, and the HOLD prints the test's
`work` text so the operator sees what was pulled. The pull-test schema lands in phase 4
(section 9), not phase 1. Until the shop pull-tests, the rocker strap stays
failing or `?`.

The rejected alternatives are recorded for the history: model B (the
footprint width as the front) needs a stiffness criterion the inputs don't
carry.

The axial sense comes from the tool's helix and its cutting hand together,
never from the cutting hand alone: a helix of the same hand as the cut (right
helix with right-hand cut, or left with left) evacuates chips up and lifts the
work; opposite hands push it down. The helix hand is its own tool fact,
`helix_hand`, separate from the cutting `hand` that selects spindle rotation.
Either one unknown is evaluated as a lift. That is a bound, not a default: a
result that passes as a lift also passes as a push. Vacuum's lift capacity is the full normal force, so it rarely governs.

## 4. Force model, shared with #158

### 4.1 One model, one place

A private helper module, `src/prechips/rules/_cutting_force.py`, follows the
naming convention of `_envelope.py`, `_profile.py` and `_bench.py`. It exposes
one function:

```python
milling_force(bundle, setup, op) -> CuttingForce
# CuttingForce: lateral_n, axial_n, axial_sense ("lift" | "push"),
#               inputs {name: value}, debts [reason], cite [source]
```

Both holding providers consume it: the area hold here, and #158's clamp
friction/preload provider later (section 9, phase 7). There is one rule,
`hold_capacity`, with one finding per `(setup:op)`, and the provider is
selected by the hold. `turning_deflection` keeps its own constant-K_c static
proxy (D5).

**Scope: end-mill milling only.** The model covers endmill-family tools
(`endmill`, `endmill_set`, the same families as `engagement`) on milling
actions: face, profile, pocket and slot. Drilling, reaming, tapping and
counterboring with a drill-family tool load the work by thrust and torque, not
by a peripheral chip, so treating a drill's depth as `ap` would be physically
wrong. For those ops `milling_force` returns `?` ("no thrust/torque force model
for drill"), and with `hold_capacity` always required (D3) such a setup stops at
exit 4 until a thrust/torque model is designed (a follow-up issue). Zero
capacity is still decided without a force (section 3.1), so a drill that opens a
vacuum chamber is an error for every later cutting op. An endmill used for a
counterbore cuts with its end, so it falls under the entry rule below. Noncutting
actions (`fit`, `inspect`, `release`) are `not_applicable`.

**Side entry only.** The peripheral equations bound a cut whose flutes engage
from the side. A plunge or a helical ramp also cuts with the tool's end, a
thrust and torque those equations do not bound. The plan carries no CAM entry
strategy, so the model reuses the existing plunge decision of the coordinates
rule ([plunge rows](cutting-data.md#plunge)): an op whose milled path is proven
to enter from outside the stock or into an already-open region is computed. An
op that plunges, or whose entry is unproven, returns `?` ("no axial-entry force
model"). This holds a pocket, slot or closed profile that enters by plunging,
and an endmill counterbore, at `?` until an axial-entry model is designed (a
follow-up issue).

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

The model is a deliberate **upper bound**, not a mean: every engaged tooth is
taken at the maximum chip, and ae is a full slot unless the op says otherwise.
A bound that proves the margin is a proof. A missing input is never replaced
with a default:

| Input | Source | Missing |
|---|---|---|
| `D`, `z` | resolved tool/member (`dia_mm`, `flutes`) | `?` |
| `β` | new tool/member `helix_deg` (`CitedFact`: a cited vendor nominal is enough) | `?` |
| helix hand | new tool/member `helix_hand`: `"right"` / `"left"`, separate from the cutting `hand` | evaluated as lift (bound) |
| cutting hand | existing `hand`: `"right"` / `"left"` | evaluated as lift (bound) |
| `fz` | the op's resolved `chip_load_mm_per_tooth` (`speeds_feeds` resolution, unchanged) | `?` |
| `ap` | op `doc_mm` (> 0) | `?` |
| `ae` | new op `ae_mm` (0 < ae ≤ D), else D | the bound D is used |
| `kc1`, `mc`, `k_r` | new `[[material]]` fields `kc1_n_per_mm2`, `mc`, `radial_ratio`, under the row's existing `cite` | `?` |

`contour.step_mm` is a raster step, not a width of cut: the first pass of a
raster can be a full slot, so it is not read as ae.

### 4.3 Margin policy

```text
k        = hold_capacity_factor_min
tape     use_xy = F_xy / C_xy,i + M_yaw / C_yaw,i
         use_z  = F_z,eff / C_z,i                                (F_z,eff of section 3.3)
         use    = use_xy + use_z                                 (shear and peel share one bond)
vacuum   N_r    = N_i − k · F_z                                  (residual contact load, lift sense;
                                                                  a push is not credited)
         N_r ≤ 0                                                 → error (the lift alone opens the seat)
         use_xy = k · F_xy / (friction · N_r) + k · M_yaw / (friction · N_r · J_i / A_seal,i)
         use_ot = k · M_ot / (N_r · d_i)                         (tipping about the nearest hull edge:
                                                                  k(F_xy·h + F_z·(d + r)) ≤ N·d)
         use    = max(use_xy, use_ot)                            (already factored: pass at use ≤ 1)
         (each over every island under op k, worst op of the setup reported)
pass     tape use ≤ 1 / k;  vacuum use ≤ 1
error    use > 1 / k   with every input known and trusted, or zero capacity under a cutting op
?        any input unknown or untrusted, or k unknown or flagged
```

Combined loads are never checked one at a time. Tape's shear and peel act on
the same adhesive, so their uses add. Vacuum friction is limited by the contact
load the lift leaves, so the lateral check uses the residual `N_r` after the
factored lift, with the residual pressure `N_r / A_seal` taken as uniform for
yaw. Overturning uses the same residual: about the nearest hull edge, the lift
acts at most `d + r` from the edge, and moving its `k·F_z·d` share to the
restoring side gives `N_r · d`. Checking `μN` and `N` separately would pass `0.49 μN` lateral with `0.49 N`
lift at k = 2, leaving barely 1× of real margin.

The traveler prints the margin as a factor: `1 / use` for tape, and for vacuum
the largest k at which the factored checks still pass.

`hold_capacity_factor_min` is a new `shop-policy.numbers` entry with
`numbers_cite` and `numbers_verify`, shipped as `"unknown"`, as the other policy
numbers are. A true or unknown verify flag makes the factor unknown. **Decided
(D10):** there is one shared factor for tape, vacuum and #158's clamps; a
per-provider override can come later if a case needs it.

**Decided (D1): an insufficient margin is a hard `error`**, as a §4.3
workholding rule decided from declared facts, like `vise` or
`fixture_interference`. A lost hold is a part thrown by the cutter, not an
out-of-band dimension, so the PLAN §4.4 "lines only" proxies do not set the
precedent. Unknown inputs stay `?`.

**Decided (D3): `hold_capacity` is always required for area holds**, like
`centre_support`. Its `?` reaches exit 4 whatever `[required]` says, because an
unknown capacity on a clampless hold has no fallback. For #158's clamp provider
the rule follows `[required]` until that design says otherwise.

### 4.4 Named residue (not modelled)

These stay §4.6 residue, named on the capacity finding and never computed:
adhesive creep and compression in Z under cutting load, tape softening from
cutting heat or coolant, chips or burrs trapped under the layer, the free-state
bow of thin work after release, entry and exit impact peaks above the steady
bound, and an operator feeding faster than the printed feed on a manual mill.
`hold_capacity_factor_min` is the shop's allowance for them.

## 5. Z stack-up

### 5.1 The stack

Under an area hold, the work's underside is not a touchable surface: it is
glued down. The plan's frame may still put Z0 there (S0A: "Z0 on the raw strap
underside"), but the zero recipe has to touch something physical, and the
printed Axis Set value is then derived from the stack:

```text
plate top (the `on` face)    Z_p      posed; skimmed in place, flatness f over the footprint (measured)
tape layer                   t ∈ [t_lo, t_hi], nominal t_nom = (t_lo + t_hi) / 2
work underside               Z_p + t(x, y)
cut plane                    to_z, from Z0
```

The new rule, `area_hold_stack`, runs per area-hold setup that has a thickness
band to cut against: an op whose feature band is measured from the seated face
to the cut face. It builds a table of signed terms, each a `[lo, hi]` interval
in mm, adds them to the nominal cut (interval arithmetic), and requires **both
endpoints** of the resulting thickness interval to lie inside the feature's
`[low, high]` band. Width alone is not enough: a cut off the band centre can
have a narrow stack and still put one endpoint outside.

### 5.2 Which recipe carries which terms

Let P be the point where the zero is touched. For any point x under the cut,
each term is a signed interval added to the nominal thickness `to_z`:

**Recipe A, Z from the plate.** Touch the plate top beside the work (with paper
or a gauge block). Printed: `Axis Set Z = −t_nom + paper_mm`. The touch point
P is a plan fact: a new `zero.z.at_mm = [x, y]` in the setup frame, which recipe
A under an area hold requires and the HOLD prints ("touch the plate at X …,
Y …"). The kernel projects it onto the posed `on` face and checks the whole
touching tool, not just its centre. The disc of the touching tool's resolved
radius about P (the `zero.z` tool, or the gauge block's half-width when the
touch is through a block) must lie entirely on that solid's top face, the face
`flatness_mm` covers, and clear of the work's footprint and the tape layer. A
missing `at_mm` or an unresolved tool radius is `?`. A disc that overhangs the
plate, meets another solid or overlaps the footprint is an error, since the
tool would land on the work or off the measured face. P is never read from
prose.

```text
thickness(x) = to_z + (t_nom − t(x)) + (Z_p(P) − Z_p(x)) + e_touch + e_dro
terms:         tape  [t_nom − t_hi, t_nom − t_lo]
               plate [−f, +f]        (f: the `on` solid's measured `flatness_mm`)
               touch [−e, +e]        (e: policy `numbers.touch_error_mm`, cited, unflagged)
               DRO   [−r/2, +r/2]    (r: the setup machine's measured `resolution_mm`, the DRO grid)
```

**Recipe B, Z from the work top** (`measure_then_set`). Mic the work at P to
read M, then touch its top at P. Printed: `Axis Set Z = M + paper_mm`. **Recipe B
is out of scope under an area hold: its stack row is `?`** ("zero Z from the
seat face (recipe A) under an area hold"). The micrometer must read across both
faces before the work is bonded, at the same P the tool later touches, with an
instrument whose throat or jaw reach is modelled to get there. That needs
instrument-envelope facts the schema does not carry, and the result is worse
on the tape term anyway (below). The arithmetic is kept to show why recipe A is
preferred and as the basis for a follow-up, if a shop needs it.

```text
thickness(x) = to_z + (t(P) − t(x)) + (Z_p(P) − Z_p(x)) + e_mic + e_touch + e_dro
terms:         tape  [t_lo − t_hi, t_hi − t_lo]   plate [−f, +f]   mic [−m, +m]
               touch [−e, +e]                     DRO [−r/2, +r/2]
               (m: the micrometer gauge's trusted `accuracy_mm` plus half its `resolution_mm`)
```

B samples the tape at one point and assumes it everywhere else, so it carries
the tape spread **twice**. A carries it once but depends on the plate's
flatness, which is a measured fixture fact. The engine does not choose a
recipe: it evaluates the one the plan declares, and the term table shows the
author why the other might do better.

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

So **yes, the spread alone can make a band unprovable.** With recipe A, that
happens whenever `t_hi − t_lo` is greater than the band width (for any `to_z`);
with recipe B, whenever `2(t_hi − t_lo)` is. A spread exactly as wide as the
band, with every other term zero and `to_z` at the band centre, lands both
endpoints on the inclusive limits and passes. No zero recipe recovers it. The
remedy is a tighter measured lot, a different hold or a looser band.

### 5.4 Interaction with S0A/S0B (#294)

- **S0B governs the final thickness** (2.5 ±0.025). S0A's faced side sits on
  fresh tape, and the thin strap is pressed into the layer, so the S0B
  thickness at x is `cut_B − Z_p(x) − t_B(x)`. That does not depend on S0A's
  errors, provided the strap conforms to the tape.
- **S0A's error reaches S0B only through clean-up.** S0A's actual thickness is
  `T_A = [T_A,lo, T_A,hi]` from its own stack about 2.75. S0B's depth of cut
  must stay positive everywhere, or S0B leaves an uncut patch of S0A's face.
  The existing stock and coverage rules see only nominal stock. The new rule
  adds a stack row for the pair, `T_A,lo − T_B,hi > 0` (the least S0A thickness
  above the highest S0B cut), and `?` when either interval is unknown.
- **S0A's own clean-up** of the raw face needs `raw_min − T_A,hi > 0`, where
  `raw_min` is the least raw thickness (a stock fact; unknown is `?`) and
  `T_A,hi = 2.75 + (S0A width)/2` for a symmetric stack.
- **Conformity is an assumption.** If the strap is stiff, or bowed more than
  the tape can take up, it bridges, the contact area drops and the stack no
  longer follows `t(x)`. This is named residue (section 4.4), printed as the
  apply step's "press flat; no daylight under the ends" check.
- **#294's island** (a 0.25 Ø6.5 island over the hub footprint) is a separate
  kernel defect. Once it is fixed, S0B's entry stock is flat, and the seat check
  of section 2.5 replaces the interpenetration findings against the tape box.

## 6. Traveler

### 6.1 Placement

Following the joint-compound precedent (prep and cure print once, on the op
that bonds):

- the **apply** rows and the **dwell** gate print in the HOLD step. The dwell
  is a hard gate (D6): the row says "if the dwell is not met: STOP, do not
  cut", and there is no shortened-dwell allowance;
- the **capacity** lines (lateral with yaw, lift with overturning) and the
  **Z stack** row print in the HOLD step under the apply rows, naming the
  governing op and the strength's `test`;
- the **release** step prints after the setup's last op, before "Ends with",
  as a numbered noncutting step: the tape's `release` (solvent or heat, then
  roll off, never pry thin work), or the vacuum chuck's `release` steps (valve,
  vent, gauge at 0, lift). Each is runnable only with a known, cited record;
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

The STOP lines are what this design's illustrative inputs produce, and they are
left in on purpose. A runnable version needs a measured pull test, a hold
whose yaw margin clears the factor, and a measured lot spread small enough for
both endpoints to land inside the band.

### 6.3 STOP forms (one per printed value)

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
| vacuum gauge minimum P | `vacuum_kpa`, `gauge` (`vacuum_gauge`, `range_kpa`, `resolution_kpa`, `accuracy_kpa`) | `vacuum_kpa` untrusted, no gauge, a gauge of another kind, an untrusted range, resolution or accuracy, or a corrected P outside `range_kpa` |
| vacuum cord lay step and inset | `seal`, `gasket_inset_mm` | seal not `laid_cord`, or inset untrusted |
| release method, agent or temperature, wait (tape); release steps (vacuum) | tape or chuck `release` | missing, or its `cite` blank or `"unknown"`: a temperature or solvent is never printed without its source |

## 7. Operator step sequence and error propagation

| # | Operator does | Physical reference | Printed number from | Error source | How the error reaches the cut or the hold |
|---|---|---|---|---|---|
| 1 | Skims the plate, or checks the skimmed plate (once per install) | table travel | — (fixture fact) | plate flatness f | stack term ±f (both recipes) |
| 2 | Cleans the plate and the work | — | prep text | residual oil or chips | contact area and shear (residue); chips also add to t(x) |
| 3 | Lays the tape over the footprint | plate top, work outline | outline 350 × 40 (manifest footprint) | seams, wrinkles, short coverage | area below the derived A (residue); thickness locally outside the pair |
| 3v | (vacuum, instead of 3) Lays the gasket cord in the grid grooves along the work outline, before the work is seated; step 7 checks it after seating | the work outline | `gasket_inset_mm` | cord off the inset, a gap at the joint | sealed area differs from S; an open joint is caught by the gauge row (step 7) |
| 4 | Seats the work (tape: and rolls it) | end stop, plate top | stop X from the pose | work bridges instead of conforming | area loss; the stack stops following t(x) (residue; printed "no daylight") |
| 5 | (tape) Waits the dwell, writing both clock times | the clock | `dwell_min` | dwell cut short | strengths below the cited values; the printed gate is a STOP, so a short dwell is a stopped setup, not a reduced margin (D6) |
| 6 | Sets Z (recipe A: plate + paper) | plate top at P | `−t_nom + paper` | paper, touch feel, DRO step | touch and DRO terms; the tape mean enters as `t_nom − t(x)` |
| 7 | (vacuum) Reads the chuck gauge before each op | chuck gauge | the corrected minimum P (section 2.3), never `vacuum_kpa` itself | leak, pump, gauge error and resolution | P already absorbs gauge error, so a reading at P proves `vacuum_kpa`; a reading below P → STOP |
| 8 | Cuts each op at the printed feed | — | feed from cutting data | feeds faster by hand | F_xy and F_z scale with fz^(1−mc) (residue; covered by the factor) |
| 9 | Releases (solvent or heat, roll off) | — | release text | prying | bends thin work: the free-state bow is residue, and prying is forbidden in print |

## 8. Test plan

The tests follow the three gates #289 proposes: one resolver for every printed
value, one parametrized test per printed field, and operator perturbation. All
unit tests inject a synthetic `bundle.kernel` with island sections. Geometry
tests request the shared `freecad_kernel` fixture.

**Schema and migration (phase 1)**
- `adhesive_tape` / `vacuum` records parse; unknown keys are rejected; each
  `CitedFact` trust state (cited, measured, bare, assumed, illustrative,
  `verify = true`, blank cite, blank or unknown `test`) resolves to trusted or
  debt as section 2.1 says. `thickness_mm` is trusted only as a measured pair.
- `static_shear_n_per_cm2` (the pre-decision name) is rejected as an unknown key.
- `hold.method = "tape"` / `"vacuum"` without `area` is exit 3, naming
  `hold.area`. An `area` with an unknown `ref`, a `ref` of the wrong kind, or an
  `on` naming no single solid is exit 3. A fixture still carrying a
  `locates = "work underside"` solid under an `area` hold is exit 3.
- `"wax"` keeps its `thin_wall_under_clamp` pass (D9).

**Force model** (`_cutting_force.py`)
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

**Capacity and margin** (`hold_capacity`)
- Tape and vacuum with `use` exactly `1/k` (pass), just above (error), and `k`
  unknown or flagged (`?`).
- Moments: the same island and force pass with the cutter at the centroid and
  fail with it at the far end of a long, narrow island (yaw). An asymmetric vacuum
  island whose sealed area is offset from the island centroid is judged about
  the seal centroid: a cutter at the island centroid but far from the seal
  centroid still fails yaw. A vacuum island
  fails overturning with a tall cut at its narrow edge.
- Peel front: a 5 mm tab cut with a Ø10 cutter gets `L = 5`. A cut to the seat
  keeps `h_k` at the before-op stock height, not zero.
- A vacuum `area.ref` naming another vacuum fixture than `hold.fixture` is exit 3.
- Seat material: the pair's seat comes from the `on` solid's `material`. A
  steel-bodied fixture with an aluminium `on` pad seats on aluminium; an `on`
  solid with no `material` leaves capacity `?`.
- Pairs: a value listed for `{ work = steel, seat = aluminium }` qualifies that
  setup, but not steel on steel or aluminium on steel; those leave capacity `?`,
  naming the pair.
- Stack sources: each of `flatness_mm`, `touch_error_mm` and the machine's
  `resolution_mm` missing or untrusted leaves the stack `?`, naming that fact.
- Vacuum gauge: a `gauge` of another kind, a range not containing `vacuum_kpa`
  an unknown resolution or accuracy, or a printed minimum outside the range,
  leaves capacity `?`. On a 2 kPa gauge with 1.0 kPa accuracy, 80.0 kPa prints
  "at least 82" (80 + 1 + 1 = 82, on the grid; a reading of 82 proves 80) and
  81.0 prints "at least 84" (83 rounds up). A minimum of 100 on a 0–100 gauge
  passes; one of 102 is `?`.
- Combined loads: tape with `use_xy` and `use_z` each at 0.3 at k = 2 fails
  (sum 0.6 > 0.5); vacuum with `0.49 μN` lateral and `0.49 N` lift at k = 2
  fails on the residual load, and `k · F_z ≥ N` is an error. Overturning with
  a lift near `N / k` fails, though it would pass against the full `N · d`.
- Seal circuit: a vacuum fixture without `seal = "laid_cord"` leaves capacity
  `?`; the HOLD prints the cord lay step at `gasket_inset_mm`.
- Vacuum seal: a through-hole inside S at setup entry gives zero capacity from
  the first op; an op that drills through inside S, or profiles across the seal
  line, errors from that op on, even with its force unknown; a profile that
  splits the work inside S does not credit the islands independently; a work
  narrower than 2 × inset has sealed area 0.
- Pull test: a qualifying test raises `C_z` to `lift_n` and the printed dwell
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
- `thin_wall_under_clamp` is `not_applicable` on an area hold with no clamps on
  the work.

**Stack** (`area_hold_stack`)
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
- Release: an uncited tape or chuck release prints the STOP; a cited one prints
  its steps.

**Operator perturbation**
- *Dwell cut short:* with `dwell_min` untrusted, no capacity is claimed and
  the HOLD prints the dwell STOP; with it trusted, the gate row prints the
  minimum and "if the dwell is not met: STOP". There is no build-up curve
  (D6), and the test pins that no input admits a shorter dwell.
- *Tape thicker than nominal:* the same plan with the measured pair moved from
  `[0.095, 0.105]` to `[0.095, 0.135]` turns the stack row from pass to error
  and moves the printed underside range. A pair that does not contain the
  pose's gap fails the seat check.
- *Footprint reduced by the cut:* a setup whose last op leaves a 20 × 20 island
  passes at op 10 and errors at the island-making op; a vacuum setup errors
  from the op that drills through inside the seal.
- *Zero a DRO step off:* recipe A with the DRO term at one step; the band
  verdict changes exactly at the step that moves an endpoint past a limit.

**Input domains**
- One parametrized test per row of section 2.8: a value just inside the domain
  is used, and the boundary outside it (`helix_deg` = 90 or −30;
  `friction` = 1.01; a pull test with `front_mm` = 0;
  `ae` > D; `k` = 0.9) is `?` naming the fact and its domain.

**Printed values**
- One parametrized test per row of section 6.3: an unknown source prints that
  STOP and never a runnable row.
- One new example bundle, `examples/geometry/area-hold/` (a strap on tape,
  recipe A), with goldens, run under `validate_examples.py`.
- The blind machinist review (`scripts/machinist_review.py`) of the section 6.2
  mock-up, then of the shipped traveler, by the other model family. This is a
  gate for the coordinator, run with phase 6.

## 9. Phased implementation plan

Each phase is its own PR, stacked on the previous one.

| Phase | PR | Contents | Size (est.) |
|---|---|---|---|
| 1 | schema | `CitedFact` (+ `test`, `pairs`); solid `flatness_mm` and `material`; gauge `accuracy_mm`; `adhesive_tape` consumable variant (with `width_mm`); `vacuum` fixture kind (with `seal`, `release`); `vacuum_gauge` `range_kpa` / `resolution_kpa` / `accuracy_kpa`; `hold.area`; `zero.z.at_mm`; migration errors; `inventory.md` / `plan.md` tables. No rule reads the new facts yet | ~350 lines + tests |
| 2 | force | `_cutting_force.py` (endmill milling scope); `[[material]]` `kc1_n_per_mm2` / `mc` / `radial_ratio`; tool `helix_deg` and `helix_hand`; op `ae_mm`; `cutting-data.md`, `rules-physics.md` | ~400 + tests |
| 3 | kernel | seat-plane sections before and after each op, islands, centroid, polar moment, hull distance; the fixed seal circuit and its opening op; op removed-volume extent per island; the layer drawn from facts; seat check; `ENGINE_SOURCES` cache identity | ~700 + geometry tests |
| 4 | capacity | `hold_capacity` rule (area provider: force, yaw, lift, overturning), always required for area holds, shared policy factor, pull-test schema, `thin_wall_under_clamp` change; `rules-setup.md` | ~500 + tests |
| 5 | stack | `area_hold_stack` signed-term intervals, endpoint comparison, recipe A/B detection from `zero.z`, S0A→S0B and raw clean-up rows; `rules-coordinates.md` | ~400 + tests |
| 6 | traveler | apply, dwell gate, capacity, stack and release rows; STOP forms; the example bundle and goldens; blind machinist review | ~600 + goldens |
| 7 | #158 | clamp provider (`n × μ × preload`, cited) for `hold_capacity` with the shared factor; per-solid clearance listing | separate design note in #158 |
| — | follow-up | drill-family thrust/torque and axial-entry models; authored tape strips (D7); wax and CA (D9) | separate issues |

Phases 1–2 are independent of the kernel. Phase 4 needs 2 and 3, and phase 6
needs 4 and 5.

## 10. Worked example: the strap, S0B (illustrative arithmetic)

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
Vacuum (if used instead): S = (350 − 6)(40 − 6) = 116.96 cm² at 80 kPa → N = 936 N,
                          μ 0.2 → 187 N lateral; yaw and overturning per section 3.3
Stack (recipe A) about 2.500: tape ±0.010, plate ±0.005, touch ±0.010, DRO ±0.005
                 → 2.470–2.530 vs 2.475–2.525 → error
Stack (recipe B): tape ±0.020 + …                                   → worse
```

The 133 cm² is the shop record's figure; a plain 350 × 40 rectangle is 140 cm².
The engine uses its own section of the stock, not either number. Read honestly,
the illustrative inputs say:

- force alone would leave a 4.7× lateral margin, but the yaw moment of a
  cutter at the end of a 350 mm strap brings it to 1.6×;
- lift is not provable from datasheet peel, so until the shop pull-tests the
  strap stays failing or `?` (D2);
- a 0.020 lot spread already uses 40 % of the band.

## 11. Decisions (maintainer, 2026-10-17, on PR #296)

| # | Question | Decision |
|---|---|---|
| D1 | Error status | An insufficient hold margin is a hard `error`, as a §4.3 workholding rule. Unknown inputs stay `?` (section 4.3). |
| D2 | Lift model | Model A, the cutter-Ø peel front, by default. Only a measured pull test recorded on the real setup can claim more. Until the shop pull-tests, the rocker strap stays failing or `?` (section 3.4). |
| D3 | Required | `hold_capacity` is always required for area holds (section 4.3). |
| D4 | Thickness evidence | The stack check accepts only a measured lot pair; a datasheet tolerance stays `?` (section 2.1). |
| D5 | Turning deflection | `turning_deflection` keeps its own constant-K_c proxy (section 4.1). |
| D6 | Shear and dwell | The field is `shear_n_per_cm2`, with a `test` naming the test method. `dwell_min` is a hard gate: a dwell not met is a STOP; no build-up curve (sections 2.2, 6.1). |
| D7 | Coverage | Phase 1 covers footprint coverage only; authored strips are a follow-up (section 2.4). |
| D8 | Gaskets | Raised or compressible gaskets are out of scope for now (section 2.3). |
| D9 | Wax and CA | They stay in `_PROTECTED` for a later issue (section 2.6). |
| D10 | Margin number | One shared `hold_capacity_factor_min` for tape, vacuum and #158's clamps; a per-provider override can come later if a case needs it (section 4.3). |

Changes made after the decisions, in answer to the design review on PR #296,
not separately decided by the maintainer:

- yaw and overturning moment checks, with the linear force/moment interaction
  (section 3.3);
- the vacuum seal circuit fixed at setup entry, with any cut that opens it a
  leak (section 3.1);
- stack endpoints compared with the band, not the width alone (section 5.3);
- the force model scoped to end-mill milling, with drill-family ops `?` until
  a thrust/torque model exists (section 4.1);
- the S0A clean-up row uses the half-width (section 5.4);
- every moment lever is measured from the centroid of the traction region that
  carries it, which for vacuum is the sealed area (section 3.3);
- a credited pull test raises the dwell gate to the test's dwell (section 3.4);
- combined loads share one capacity: tape adds its shear and peel uses, and
  vacuum friction and overturning use the contact load left after the factored
  lift (section 4.3);
- the peel front and its lever are capped by the island's least width, and the
  overturning lever is the highest point the flutes can engage (section 3.3);
- a vacuum `ref` must be the held fixture (section 2.4);
- the vacuum gauge must be a `vacuum_gauge` with known range, resolution and
  accuracy; the printed minimum adds the accuracy and half a step before
  rounding up, and must itself lie in the range (section 2.3);
- only proven side entries are computed; a plunge or unproven entry is `?`
  until an axial-entry model exists (section 4.1);
- the plate's flatness covers its whole top face, and recipe A's touch point
  must lie on it; releases need a cited record, and vacuum gains its own release
  (sections 2.3, 2.7, 5.2, 6.1);
- recipe A's touch point is a plan field, `zero.z.at_mm`, never prose (section 5.2);
- every consumed number has a stated domain, checked before use (section 2.8);
- recipe B (zero from the work top) is out of scope under an area hold and
  stays `?`: it would need instrument reach facts, and recipe A carries the tape
  spread once instead of twice (section 5.2);
- a pull test's dwell is a trusted measured fact, and step 7 prints the
  corrected minimum P (sections 3.4, 7);
- strengths and friction apply only to the exact work/seat pairs they were
  established on, and every stack uncertainty has a named, trusted source
  (section 2.7);
- the lift sense comes from a separate `helix_hand` together with the cutting
  `hand` (section 3.4, 4.2);
- the vacuum seal is a cord laid along the work's outline (`seal = "laid_cord"`);
  other seal circuits are `?` until their groove geometry is recorded (section 2.3);
- pull tests qualify only by machine-checkable fields that must all match the
  setup (section 3.4);
- the tape's `width_mm` bounds footprint coverage, so seams are never credited
  (section 2.4).
