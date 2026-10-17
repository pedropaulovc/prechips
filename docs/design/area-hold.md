# Design: typed area hold (adhesive tape or vacuum)

Status: **design proposed, not implemented.** Issue
[#295](https://github.com/pedropaulovc/prechips/issues/295), sharing its force
side with [#158](https://github.com/pedropaulovc/prechips/issues/158). None of
this document is shipped behaviour: no schema, rule, kernel output or traveler
row described here exists yet. It follows the design-first rule from
[#289](https://github.com/pedropaulovc/prechips/issues/289): it writes down the
operator's step sequence, the physical reference behind every printed number,
and how each step's error reaches the cut or the hold, before any engine code.

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
a `LimitsMeasurement`, a `[least, greatest]` pair. The decision this document
recommends (open question Q4) is that the stack check accepts only a measured
pair: a mic'd sample of the lot on hand. The datasheet nominal may be printed,
but cannot clear a band.

### 2.2 Tape record

```toml
[consumables.tape-3m-444]
kind = "adhesive_tape"
name = "3M 444 double-coated PET film tape"
products = ["3M 444, 25 mm roll"]
# [least, greatest] over a mic'd sample of the lot on hand (illustrative values).
thickness_mm = { value = [0.090, 0.110], measured = { status = "measured", by = "...", date = "...", instrument = "0-25 mm micrometer, 0.001" } }
static_shear_n_per_cm2 = { value = 3.0, cite = "shop record harmonic-analyzer PR #1594" }   # (shop record)
peel_n_per_cm = { value = 4.0, cite = "..." }      # illustrative value
dwell_min = { value = 20, cite = "..." }           # the dwell the shear and peel are quoted at
surface_prep = "Clean both faces with isopropyl alcohol; dry; no oil film or chips."
apply = "Roll firmly end to end with a hand roller."
release = { method = "solvent", agent = "isopropyl alcohol", wait_min = 5, cite = "..." }
# or release = { method = "heat", temp_c = 70, wait_min = 2, cite = "..." }
```

| Field | Type | Meaning | Unknown or untrusted |
|---|---|---|---|
| `thickness_mm` | `LimitsMeasurement` | applied layer thickness, least–greatest | stack check `?`; layer drawn at the midpoint only when the pair is known, otherwise not drawn (render debt) |
| `static_shear_n_per_cm2` | `CitedFact` | shear strength used as lateral capacity per cm² of contact | capacity `?` |
| `peel_n_per_cm` | `CitedFact` | peel resistance per cm of peel front | lift `?` |
| `dwell_min` | `CitedFact` | minimum time between applying the work and cutting, at which the two strengths above hold | capacity `?`; the traveler prints a STOP in place of the dwell row |
| `surface_prep`, `apply` | text | printed in the apply step | STOP row in the apply step |
| `release` | `{ method = "solvent" \| "heat", agent \| temp_c, wait_min, cite }` | printed release step | STOP row in the release step |

### 2.3 Vacuum record

```toml
[fixtures.vacuum-chuck-12x18]
kind = "vacuum"
vacuum_kpa = { value = 80.0, cite = "..." }          # illustrative; gauge vacuum below atmosphere
gasket_inset_mm = { value = 3.0, measured = { ... } } # work outline to the seal line
friction = { value = 0.2, cite = "..." }             # illustrative; work on the chuck face, dry
gauge = "chuck-vacuum-gauge"                          # inventory gauge the operator reads
solids = [ { name = "face", shape = "box", ... } ]    # the chuck body, as for any fixture
```

| Field | Type | Meaning | Unknown or untrusted |
|---|---|---|---|
| `vacuum_kpa` | `CitedFact` | the least gauge vacuum at which capacity is claimed; the operator must read at least this before cutting | capacity `?`; STOP in place of the gauge row |
| `gasket_inset_mm` | `MeasuredLength` | inset of the seal line inside the work outline | sealed area `?` |
| `friction` | `CitedFact` | static μ of the work on the chuck face | capacity `?` |
| `gauge` | `str` | inventory gauge read at the chuck | STOP in place of the gauge row |

Vacuum assumes the work seats metal-to-metal on the chuck face, with the gasket
in a groove, so the gasket adds no Z term. A raised gasket the work sits on is
out of scope (open question Q8).

### 2.4 How the hold references them

`Hold` gains one optional record, `area`:

```toml
[setups.hold]
fixture = "thin-part-tape-subplate"     # the sub-plate (no tape solid any more)
area = { ref = "tape-3m-444", on = "plate" }
pose = { origin_mm = [0.0, 6.0, -0.100], x = [1.0, 0.0, 0.0], z = [0.0, 0.0, 1.0] }
```

- `ref` names a `consumables` `adhesive_tape` item, or a `fixtures` `vacuum`
  item (for vacuum it is normally the same item as `fixture`).
- `on` names the solid of the holding fixture whose posed +z face carries the
  layer (for tape) or is the chuck face (for vacuum). Exactly one trusted solid
  must be named; otherwise the input is bad.
- Coverage is the work's footprint: the layer is trimmed to the work outline on
  that face. Strips or partial coverage are open question Q7.

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
| `"wax"`, `"soft_jaws"`, `"mandrel"` in `_PROTECTED` | unchanged | Wax is also an area hold, but it is not typed here (open question Q9). |

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

## 3. Capacity model

### 3.1 Contact area

The kernel derives the area. The plan does not author it.

For each op of an area-hold setup, the kernel takes the in-process stock
**before** and **after** the op and sections each at the seat plane (the layer
top for tape, the chuck face for vacuum). The section is split into connected
**islands**. Each island *i* has:

```text
A_i          its area on the seat (holes the stock already has are absent from the section)
A_tape,i     = A_i ∩ layer                      (tape; the layer is the setup-entry footprint)
A_seal,i     = erode(island_i, gasket_inset_mm) (vacuum), and 0 when:
               - the eroded region is empty (the work is narrower than 2 × inset), or
               - any through-opening of the stock lies inside the seal line (a leak, not a subtraction)
```

The tape layer is laid once, at setup entry. A hole the setup drills later
leaves the tape behind it intact, but the work over the hole no longer bears on
it, so the after-op section is what counts. For vacuum, the same through-hole
opens the seal: the capacity of that island drops to zero for the rest of the
setup, and the rule reports which op breaks it.

The capacity for op *k* uses the **smaller** of its before- and after-op
values for each island, which is the after-op value for any op that only
removes material. All of the op's force is assumed to act on the island being
cut. That is conservative, since the force goes to whichever island the cutter
is in.

### 3.2 Capacities

```text
tape   lateral  C_xy,i = static_shear_n_per_cm2 × A_tape,i / 100            (A in mm², 100 mm²/cm²)
tape   lift     C_z,i  = peel_n_per_cm × L_front / 10                       (L in mm, section 3.3)
vacuum normal   N_i    = vacuum_kpa × A_seal,i / 1000                       (kPa·mm² → N)
vacuum lateral  C_xy,i = friction × N_i
vacuum lift     C_z,i  = N_i
```

The part's weight is ignored. It is small, it only helps, and adding it would
need a density fact.

### 3.3 Lift: peel against the helix's axial pull

A right-hand-helix, right-hand-cut end mill (the usual one) lifts its chips,
and the reaction pulls the work **up** toward the spindle. Tape resists that
pull by peel, which starts at a free edge. Its capacity depends on how long a
peel front the pull has to open. Three candidate models:

| Model | `L_front` | Inputs | Strap result (illustrative) |
|---|---|---|---|
| A: flexible work | the cutter Ø, at the nearest footprint edge | datasheet `peel_n_per_cm` only | 4.0 × 0.9525 = 3.8 N |
| B: stiff work | the footprint width across the edge the cutter is nearest | needs a rule for when work is stiff enough not to peel locally | 4.0 × 4.0 = 16 N |
| C: measured lift | a measured pull test on the real work section | a new `lift_n` measured fact on the hold | whatever the shop measures |

The recommendation is **A by default, C as the only way to claim more.** A is
the only model that datasheet facts alone can prove, and B needs a stiffness
criterion the inputs don't carry. It also means the motivating strap **fails
the lift check under A and B** (section 10). That is the conservative models
reporting what they can and cannot prove; the design does not choose a model so
that the example passes. This is open question Q2, and the most consequential
one.

An unknown helix hand (the free-text `hand` field) is evaluated as a lift. That
is a bound, not a default: a result that passes as a lift also passes as a
push.

Vacuum's lift capacity is the full normal force, so it rarely governs.

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
friction/preload provider later (section 8, phase 7). There is one rule,
`hold_capacity`, with one finding per `(setup:op)`, and the provider is
selected by the hold. `turning_deflection` keeps its constant-K_c static proxy
(open question Q5).

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
F_z    = F_t · tan β                     axial, sense from the helix hand (lift when unknown)
```

The model is a deliberate **upper bound**, not a mean: every engaged tooth is
taken at the maximum chip, and ae is a full slot unless the op says otherwise.
A bound that proves the margin is a proof. A missing input is never replaced
with a default:

| Input | Source | Missing |
|---|---|---|
| `D`, `z` | resolved tool/member (`dia_mm`, `flutes`) | `?` |
| `β` | new tool/member `helix_deg` (`CitedFact`: a cited vendor nominal is enough) | `?` |
| helix hand | existing `hand` text: `"right"` / `"left"` | evaluated as lift (bound) |
| `fz` | the op's resolved `chip_load_mm_per_tooth` (`speeds_feeds` resolution, unchanged) | `?` |
| `ap` | op `doc_mm` (> 0) | `?` |
| `ae` | new op `ae_mm` (0 < ae ≤ D), else D | the bound D is used |
| `kc1`, `mc`, `k_r` | new `[[material]]` fields `kc1_n_per_mm2`, `mc`, `radial_ratio`, under the row's existing `cite` | `?` |

`contour.step_mm` is a raster step, not a width of cut: the first pass of a
raster can be a full slot, so it is not read as ae.

### 4.3 Margin policy

```text
factor_xy = C_xy,i / F_xy        factor_z = C_z,i / F_z    (worst island, worst op)
pass   factor ≥ hold_capacity_factor_min   (both)
error  factor <  hold_capacity_factor_min, with every input known and trusted
?      any input unknown or untrusted, or the policy number unknown or flagged
```

`hold_capacity_factor_min` is a new `shop-policy.numbers` entry with
`numbers_cite` and `numbers_verify`, shipped as `"unknown"`, as the other policy
numbers are. A true or unknown verify flag makes the factor unknown.

**An insufficient margin is a hard `error`.** This departs from PLAN §4.4,
whose proxies are lines only and never emit an error. The justification is that
a lost hold is not an out-of-band dimension: it is a part thrown by the cutter.
That makes it a §4.3 workholding outcome, decided from declared facts like
`vise` or `fixture_interference`. Open question Q1 asks the maintainer to
confirm this. Q3 asks whether `hold_capacity` is always required, like
`centre_support`, or follows `[required]`. The recommendation is always
required for an area hold, because an unknown capacity on a clampless hold has
no fallback.

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
to the cut face. It builds a table of terms, each with a `[lo, hi]` interval in
mm, and compares the worst-case total width with the band width.

### 5.2 Which recipe carries which terms

Let P be the point where the zero is touched. For any point x under the cut:

**Recipe A, Z from the plate.** Touch the plate top beside the work (with paper
or a gauge block). Printed: `Axis Set Z = −t_nom + paper_mm`.

```text
thickness(x) = to_z + (t_nom − t(x)) + (Z_p(P) − Z_p(x)) + e_touch + e_dro
widths:        tape  t_hi − t_lo     plate 2f            touch 2e   DRO r
```

**Recipe B, Z from the work top** (`measure_then_set`). Mic the work at P to
read M, then touch its top at P. Printed: `Axis Set Z = M + paper_mm`.

```text
thickness(x) = to_z + (t(P) − t(x)) + (Z_p(P) − Z_p(x)) + e_mic + e_touch + e_dro
widths:        tape  2(t_hi − t_lo)   plate 2f           mic 2m   touch 2e   DRO r
```

B samples the tape at one point and assumes it everywhere else, so it carries
the tape spread **twice**. A carries it once but depends on the plate's
flatness, which is a measured fixture fact. The engine does not choose a
recipe: it evaluates the one the plan declares, and the term table shows the
author why the other might do better.

### 5.3 Outcomes

```text
Σ widths ≤ band width             pass   (the band is provable with this hold and recipe)
Σ widths > band width, all known  error  ("band 0.050 cannot be held: tape 0.020 + plate 0.010 + touch 0.020 + DRO 0.010 = 0.060")
any term unknown or untrusted     ?      (its measure: line names the fact)
```

So **yes, the spread alone can make a band unprovable.** With recipe A, that
happens whenever `t_hi − t_lo` is at least the band width; with recipe B,
whenever `2(t_hi − t_lo)` is. No zero recipe recovers it. The remedy is a
tighter lot, a measured pair, a different hold or a looser band.

### 5.4 Interaction with S0A/S0B (#294)

- **S0B governs the final thickness** (2.5 ±0.025, band width 0.050). S0A's
  faced side sits on fresh tape, and the thin strap is pressed into the layer,
  so the S0B thickness at x is `cut_B − Z_p(x) − t_B(x)`. That does not depend
  on S0A's errors, provided the strap conforms to the tape.
- **S0A's error reaches S0B only through clean-up.** S0A cuts to 2.75 with its
  own stack, so the actual S0A thickness lies in `2.75 ± (S0A stack width)/2`.
  S0B's depth of cut `doc_B = (S0A thickness) − 2.5` must stay positive
  everywhere, or S0B leaves an uncut patch of S0A's face. The existing stock
  and coverage rules see only nominal stock. The new rule adds
  `doc_B,min = 0.25 − (S0A width)/2 − (S0B width)/2 > 0` as a stack row for the
  pair, and `?` when either width is unknown.
- **S0A's own clean-up** of the raw face needs `3.0_raw,min − 2.75 > S0A width`.
  The raw thickness tolerance is a stock fact; unknown is `?`.
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

- the **apply** rows and the **dwell** fill-in print in the HOLD step;
- the **capacity** and **lift** lines and the **Z stack** row print in the HOLD
  step, under the apply rows, naming the governing op;
- the **release** step prints after the setup's last op, before "Ends with",
  as a numbered noncutting step;
- each unknown prints its STOP form in place of the runnable row. It never
  prints a runnable row with `?` in it (#289 proposal 2).

### 6.2 Mock-up: S0B, tape on the sub-plate (recipe A)

The stop and touch positions, and every number other than the shop record's
133 cm² and 3.0 N/cm², are illustrative.

```text
HOLD — tape on sub-plate thin-part-tape-subplate (3M 444, lot thickness 0.090–0.110 measured)
  1  Clean the plate top and the strap's datum-B face with isopropyl alcohol; let dry.
     No oil film, no chips.
  2  Lay 3M 444 over the strap footprint 350 × 40 on the plate; trim to the outline.
     No seams, wrinkles or overlaps under the strap.
  3  Peel the liner. Set the strap datum-B face DOWN on the tape against the end stop
     at X −175.0. Roll firmly end to end. Press flat: no daylight under the ends.
  4  Applied at ____:____.   Cut no earlier than ____:____ (dwell ≥ 20 min).
  HOLD CAPACITY  op 10 governs
     lateral  tape 3.0 N/cm² × 133.0 cm² = 399 N   vs cut 85 N   = 4.7×  (policy ≥ 2.0×)
     lift     peel 4.0 N/cm × 0.95 cm   = 3.8 N   vs pull 46 N  — STOP: lift not proven
  Z STACK  plate top Z −0.100 · tape 0.090–0.110 · strap underside Z −0.010 … +0.010
           band 2.475–2.525 (0.050): tape 0.020 + plate 0.010 + touch 0.020 + DRO 0.010 = 0.060
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
left in on purpose. With a pull-test lift fact (model C) and a lot spread of
0.010, the same rows print `lift … = N×` and `… = 0.050 ✓`.

### 6.3 STOP forms (one per printed value)

| Printed value | Source | STOP when |
|---|---|---|
| tape product, prep, apply text | tape record | missing or `"unknown"` |
| dwell minutes | `dwell_min` | untrusted |
| shear, area, lateral force, factor | `static_shear_n_per_cm2`, kernel island area, `milling_force` | any input untrusted, or no kernel |
| peel, front length, axial force, factor | `peel_n_per_cm`, model A front / `lift_n`, `milling_force` | ditto |
| policy factor | `hold_capacity_factor_min` | unknown or flagged |
| plate top Z, tape pair, underside range | pose, `thickness_mm` (measured) | pair unmeasured |
| stack terms and total | section 5 terms | any term unknown |
| Axis Set Z | recipe and `t_nom` | `t_nom` unknown |
| vacuum gauge minimum | `vacuum_kpa`, `gauge` | untrusted, or no gauge |
| release method, agent or temperature, wait | `release` | missing |

## 7. Operator step sequence and error propagation

| # | Operator does | Physical reference | Printed number from | Error source | How the error reaches the cut or the hold |
|---|---|---|---|---|---|
| 1 | Skims the plate, or checks the skimmed plate (once per install) | table travel | — (fixture fact) | plate flatness f | stack term 2f (both recipes) |
| 2 | Cleans the plate and the work | — | prep text | residual oil or chips | contact area and shear (residue); chips also add to t(x) |
| 3 | Lays the tape over the footprint | plate top, work outline | outline 350 × 40 (manifest footprint) | seams, wrinkles, short coverage | area below the derived A (residue); thickness locally outside the pair |
| 4 | Seats the work and rolls it | end stop, plate top | stop X from the pose | work bridges instead of conforming | area loss, stack stops following t(x) (residue; printed "no daylight") |
| 5 | Waits the dwell, writing both clock times | the clock | `dwell_min` | dwell cut short | shear and peel below the cited values; the margin is the only protection (Q6) |
| 6 | Sets Z (recipe A: plate + paper) | plate top at P | `−t_nom + paper` | paper, touch feel, DRO step | touch and DRO terms; the tape mean enters as `t_nom − t(x)` |
| 6′ | Sets Z (recipe B: mic M at P, touch the top) | work top at P | `M + paper` | mic, touch, DRO; t(P) unknown | mic and touch terms; tape term doubled |
| 7 | (vacuum) Reads the chuck gauge before each op | chuck gauge | `vacuum_kpa` minimum | leak, pump | capacity scales with the reading; below the minimum → STOP |
| 8 | Cuts each op at the printed feed | — | feed from cutting data | feeds faster by hand | F_xy and F_z scale with fz^(1−mc) (residue; covered by the factor) |
| 9 | Releases (solvent or heat, roll off) | — | release text | prying | bends thin work: the free-state bow is residue, and prying is forbidden in print |

## 8. Test plan

The tests follow the three gates #289 proposes: one resolver for every printed
value, one parametrized test per printed field, and operator perturbation. All
unit tests inject a synthetic `bundle.kernel` with island areas. Geometry tests
request the shared `freecad_kernel` fixture.

**Schema and migration**
- `adhesive_tape` / `vacuum` records parse; unknown keys are rejected; each
  `CitedFact` trust state (cited, measured, bare, assumed, illustrative,
  `verify = true`, blank cite) resolves to trusted or debt as section 2.1 says.
- `hold.method = "tape"` / `"vacuum"` without `area` is exit 3, naming
  `hold.area`. An `area` with an unknown `ref`, a `ref` of the wrong kind, or an
  `on` naming no single trusted solid is exit 3. A fixture still carrying a
  `locates = "work underside"` solid under an `area` hold is exit 3.

**Force model** (`_cutting_force.py`)
- Hand-computed cases: ae = D and ae < D/2 (`h_max = fz·sin φ_e`), z = 2/3/4,
  the `n_e` ceiling exactly at a tooth boundary, β = 0 (no axial force), left
  hand (push), unknown hand (lift).
- Each missing input leaves the result `?` naming that input; the ae bound is
  applied and reported as `ae_basis = "bound_full_slot"`.

**Capacity and margin** (`hold_capacity`)
- Tape and vacuum at the factor exactly equal to the minimum (pass), just
  below (error) and with the factor unknown or flagged (`?`).
- Vacuum: a through-hole inside the seal line → that island's capacity is 0,
  error from the op that opens it; a work narrower than 2 × inset → sealed
  area 0.
- Islands: a profile op that splits the footprint is judged on the smallest
  island under the force. A kept piece cut free with zero area is an error; an
  offcut is reported as a loose-offcut warning.
- `thin_wall_under_clamp` is `not_applicable` on an area hold with no clamps
  on the work.

**Stack** (`area_hold_stack`)
- Recipe A and recipe B on the same inputs: B's tape term is exactly twice A's.
- The total equal to the band width passes; 0.001 over is an error; an
  unmeasured pair is `?`.
- The S0A→S0B clean-up row: positive, zero and negative `doc_B,min`.
- Seat check: a pose written for 0.10 tape with a 0.25 gap is an error.

**Operator perturbation**
- *Dwell cut short:* with `dwell_min` untrusted, no capacity is claimed and
  the HOLD prints the dwell STOP; with it trusted, the fill-in row carries the
  minimum. A cited build-up curve is not modelled (Q6), and the test pins that
  a shorter written time changes nothing the checker certifies.
- *Tape thicker than nominal:* the same plan with the measured pair moved from
  `[0.090, 0.110]` to `[0.090, 0.140]` turns the stack row from pass to error
  and moves the printed underside range. A pair centred off the pose's
  `t_nom` fails the seat check.
- *Footprint reduced by the cut:* a setup whose last op leaves a 20 × 20
  island passes at op 10 and errors at the island-making op; a vacuum setup
  errors from the op that drills through inside the seal.
- *Zero a DRO step off:* recipe A with `e_dro` at one DRO step; the band
  verdict changes exactly at the step that tips the total over.

**Printed values**
- One parametrized test per row of section 6.3: an unknown source prints that
  STOP and never a runnable row.
- One new example bundle, `examples/geometry/area-hold/` (a strap on tape,
  recipe A), with goldens, run under `validate_examples.py`.
- The blind machinist review (`scripts/machinist_review.py`) of the section 6.2
  mock-up, then of the shipped traveler, by the other model family. This is a
  gate for the coordinator. It is not run in this design PR.

## 9. Phased implementation plan

| Phase | PR | Contents | Size (est.) |
|---|---|---|---|
| 1 | schema | `CitedFact`; `adhesive_tape` consumable variant; `vacuum` fixture kind; `hold.area`; migration errors; `inventory.md` / `plan.md` tables | ~350 lines + tests |
| 2 | force | `_cutting_force.py`; `[[material]]` `kc1_n_per_mm2` / `mc` / `radial_ratio`; tool `helix_deg`; op `ae_mm`; `cutting-data.md`, `rules-physics.md` | ~400 + tests |
| 3 | kernel | seat-plane sections per op, islands, seal erosion and leak test; the layer drawn from facts; seat check; `ENGINE_SOURCES` cache identity | ~600 + geometry tests |
| 4 | capacity | `hold_capacity` rule (area provider), policy number, margin statuses, `thin_wall_under_clamp` change; `rules-setup.md` | ~450 + tests |
| 5 | stack | `area_hold_stack` term table, recipe A/B detection from `zero.z`, S0A→S0B clean-up row; `rules-coordinates.md` | ~400 + tests |
| 6 | traveler | apply, dwell, capacity, stack and release rows; STOP forms; the example bundle and goldens; blind machinist review | ~600 + goldens |
| 7 | #158 | clamp provider (`n × μ × preload`, cited) for `hold_capacity`; per-solid clearance listing | separate design note in #158 |

Phases 1–2 are independent of the kernel. Phase 4 needs 2 and 3, and phase 6
needs 4 and 5.

## 10. Worked example: the strap, S0B (illustrative arithmetic)

```text
Tool  3/8 in 4-flute HSS, D 9.525, z 4, β 30° (illustrative), right hand
Op    finish_face, ap = doc_mm 0.25, ae not declared → bound D
Data  fz 0.05 (illustrative), kc1 1500 N/mm², mc 0.25, k_r 0.4 (all illustrative)

φ_e = π, h_max = 0.05, n_e = ceil(4·π/2π) = 2
F_t  = 2 × 1500 × 0.25 × 0.05^0.75 = 79.3 N
F_xy = 79.3 × sqrt(1.16) = 85.4 N          (#295 estimates 60–90 N)
F_z  = 79.3 × tan 30° = 45.8 N, lift

Tape lateral  3.0 N/cm² × 133 cm² (shop record) = 399 N → 4.7×
Tape lift A   4.0 N/cm × 0.9525 cm = 3.8 N   → 0.08×   error
Tape lift B   4.0 N/cm × 4.0 cm    = 16 N    → 0.35×   error
Vacuum (if used instead): sealed (350 − 6)(40 − 6) = 116.96 cm² at 80 kPa → N = 936 N,
                          μ 0.2 → 187 N lateral → 2.2×; lift 936 N → 20×
Stack (recipe A), band 0.050: tape 0.020 + plate 2f 0.010 + touch 0.020 + DRO 0.010 = 0.060 → error
Stack (recipe B):             tape 0.040 + …                                         → worse
```

The 133 cm² is the shop record's figure; a plain 350 × 40 rectangle is 140 cm².
The engine uses its own section of the stock, not either number. Read honestly,
the illustrative inputs say the tape hold is ample laterally, but its lift is not
provable from datasheet peel, and a 0.020 lot spread already uses 40 % of the
band. Those are the two questions this design puts to the maintainer.

## 11. Open questions for the maintainer

1. **Error status.** Should an insufficient hold margin be a hard `error`,
   departing from PLAN §4.4's lines-only proxies, on the grounds that a lost
   hold is a thrown part (section 4.3)? Recommended: yes, as a §4.3
   workholding rule.
2. **Lift model.** A (cutter-Ø peel front) by default, with only a measured
   pull test (C) able to claim more? Under A and B the motivating strap fails
   lift with plausible peel values (section 10). Is that the intended outcome
   until the shop pull-tests, or should B be admitted with a stiffness rule?
3. **Required.** Should `hold_capacity` be always required for area holds, like
   `centre_support`, or follow `[required]`? Recommended: always.
4. **Thickness evidence.** May the stack check accept a datasheet thickness
   tolerance (cited), or only a measured lot pair? Recommended: measured only,
   as for bed height, because it is a stack dimension.
5. **Turning deflection.** Should `turning_deflection` migrate to the Kienzle
   kc1/mc model so that there is one force model in the codebase, or keep its
   constant K_c? Recommended: keep it; it is a separate proxy.
6. **Shear semantics and dwell.** 3M datasheets' "static shear" is a creep test
   (time to failure under a hanging load), not a dynamic strength. Should the
   field be renamed (for example `shear_n_per_cm2`) and its cite required to
   name the test? And should a cited adhesion build-up curve be admitted to
   model a short dwell, or is the dwell a hard gate only? Recommended: rename,
   and gate only.
7. **Coverage.** Footprint coverage only in phase 1, or also authored strips
   (`area.strips`) for tape laid in bands?
8. **Raised gaskets.** Vacuum chucks where the work sits on a compressible
   gasket would need a compressed-height pair in the stack. Is that in scope?
9. **Wax and CA.** Type them now as `kind = "adhesive"` with the same fields
   (shear, release by heat), or leave `"wax"` in `_PROTECTED` for a later
   issue?
10. **Margin number.** One `hold_capacity_factor_min` for tape, vacuum and
    #158's clamps, or one per provider?
