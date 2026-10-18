# Design: printed 1:1 paper pattern as a layout line

Status: **design proposed, not implemented.** Issue
[#344](https://github.com/pedropaulovc/prechips/issues/344). None of this
document is shipped behaviour: no schema, rule, kernel output or traveler row
described here exists yet. It follows the design-first rule from
[#289](https://github.com/pedropaulovc/prechips/issues/289): it writes down the
operator's step sequence, the physical reference behind every printed number,
and how each step's error reaches the cut, before any engine code.

Motivating case: harmonic-analyzer #1595, rocker route v3, step T2 (owner
ruling 2026-10-17). T2 roughs the strap's R800 top edge and R816 bottom arc,
plus the end waste with its two tooling holes, to the line +1 on a 4x6
bandsaw in vertical mode, before the T3 trammel jig finishes them. The lines
come from a 1:1 print of the strap outline glued to the faced blank with spray
adhesive; the print's scale is checked before gluing by measuring a printed
300 mm check bar *(shop record: #344)*.

**Numbers in this document.** Values quoted from #344 (300 mm bar, 0.15 mm
tolerance, +1 allowance, 4x6 bandsaw, spray adhesive) are marked *(shop
record)*. Outline coordinates come from the rocker example traveler
(`examples/rocker-arm/expected/traveler.html`, the S4 outline template:
arc ends X ±145.240 Y 21.295, lands to X ±146.255 Y 15.800, tapers to
X ±132.757 Y 2.872, common centre X 0 Y 808 from the bore A axis) and are
marked *(example geometry)*; the consumer's v3 strap may differ. Every other
number (gauge error, line width, following error, hole and pin sizes, the
tooling-hole positions, the finisher's cap) is **illustrative arithmetic**
chosen to show the formulas working. None is a datasheet figure, a
measurement or a recommendation, and none may be copied into an inventory or a
policy.

Where each deliverable of the #344 design task lives:

| Deliverable | Section |
|---|---|
| 1. Operator step sequence | §3 |
| 2. Physical reference and error path of every number, compared with `allowance_mm` | §4, §10 |
| 3. Schema, `follows` resolution, the `manual_arc` row | §2, §5 |
| 4. Unknown-value gate and one test per printed field | §6, §8.1 |
| 5. Operator-perturbation tests | §8.2 |
| 6. T2 traveler mock-up for the blind machinist read | §7 |
| 7. Open questions for the owner | §11 |

## 1. Problem

`scribe` admits `layout = "dividers" | "trammel" | "template" | "ends"`
(`rules/manual_arc.py` `LAYOUTS`). `template` means scribing around an
inventory radius or profile gauge (`guide.template`, a `gauges` radius/profile
gauge with a covering `range_mm`). A saw op's `follows` must name an earlier
non-`ends` `scribe` op (`model.py` `Plan.saw_shapes`).

A paper print glued to the work is none of these:

1. **Not a gauge.** Nothing scribes around it, it is not reused, and it is
   consumed with the waste. Declaring it a profile gauge is false.
2. **Not one feature.** One print carries several lines (R800, R816, the end
   lands and tapers, the tooling-hole circles). `Operation.feature` is a list
   only for `inspect`; `manual_arc.evaluate` and `kernel.scribed_profile` read
   one arc feature per scribe op.
3. **Its error is not a template's.** A template's line error is its own made
   accuracy. A print's line error is a stack: printer scale (anisotropic),
   the gauge that checks it, registration on the work, line width, paper
   movement under the adhesive, and the operator's following error. None of
   these is modelled.
4. **It has to come off.** Paper and adhesive left on a face the next setup
   locates on, clamps on or measures from move that setup's datum.

So T2 stays out of the consumer plan.

## 2. Schema

### 2.1 Op shape: a `scribe` with `layout = "printed_pattern"`

**Recommended (Q1):** keep `do = "scribe"` and add one layout kind,
`layout = "printed_pattern"`. "Layout" already is the enum for *how* the line
gets onto the work. Reusing `scribe` keeps the code paths that make a line
followable unchanged: `Plan.saw_shapes` registers it as a followable scribe,
`manual_arc._full_line` and `_layout_op` treat it as a full line,
`kernel.scribed_profile` finds it, and `sheet.saw_setting` names it.

The alternative, a new `do = "apply_pattern"`, says plainly that nothing is
scribed. Its cost: every one of those five sites gains a second action, and
`follows` gains a second target kind. The physical difference (no scriber
touches the work) is carried by the layout kind either way.

```toml
[[setups.ops]]            # T2A, fitting bench
op = 10
do = "scribe"
layout = "printed_pattern"
feature = ["top_edge", "profile_outer", "end_land_east", "end_land_west"]
on = "strap_top_face"                       # the face the print is glued to
pattern = "strap-outline-print-1to1"        # consumables, kind = "printed_pattern"
adhesive = "spray-adhesive-3m-super-77"     # consumables, kind = "spray_adhesive"
scale_check = [
  { axis = "x", length_mm = 300.0, gauge = "calipers-18in", tolerance_mm = 0.15 },
  { axis = "y", length_mm = 30.0,  gauge = "calipers-18in", tolerance_mm = 0.05 },
]
register = { kind = "pins", holes = ["pivot_bore", "tool_hole_east", "tool_hole_west"], pins = "gauge-pins" }

[[setups.ops]]            # T2B, bandsaw vertical
op = 10
do = "saw_cut"
follows = "T2A:10"
feature = "top_edge"      # which printed line; one saw op per line
allowance_mm = 1.0
stock_removal_bounds = { ... }

[[setups.ops]]            # T3 setup entry or an earlier bench step
op = 5
do = "remove_pattern"
removes = "T2A:10"
```

Fields new on `Operation` for this layout, all forbidden on any other op:

| Field | Type | Meaning |
|---|---|---|
| `layout` | gains `"printed_pattern"` | the line comes from a glued print |
| `feature` | `str` or list (min 1) | the lines the plan uses from the print; each must be in the pattern's `export.features` |
| `on` | `str` | the manifest face the print is glued to; drives the removal gate (§2.6) |
| `pattern` | `str` | a `consumables` item of kind `printed_pattern` |
| `adhesive` | `str` | a `consumables` item of kind `spray_adhesive` |
| `scale_check` | list of `{ axis = "x" \| "y", length_mm, gauge, tolerance_mm }`, min 1 | a printed check bar, the gauge that reads it and the accepted error |
| `register` | `{ kind = "pins", holes, pins }` or `{ kind = "edges", edges }` | how the print is located on the work (§4.3) |

The issue's free-text `locate` is replaced by the typed `register`; its prose
stays available as `note`.

### 2.2 Pattern consumable

```toml
[consumables.strap-outline-print-1to1]
kind = "printed_pattern"
name = "Rocker strap outline, 1:1 print"
export = { file = "patterns/strap-outline.pdf", sha256 = "<64 hex>", features = ["top_edge", "profile_outer", "end_land_east", "end_land_west", "tool_hole_east", "tool_hole_west", "pivot_bore"], cite = "harmonic-analyzer <export task and commit>" }
scale = "1:1"
sheet = "tabloid"            # one sheet; phase 1 refuses tiled prints (Q6)
# greatest printed stroke width over the outline, bars and circles, read on a print from this export
line_width_mm = { value = 0.20, measured = { status = "measured", by = "...", date = "...", instrument = "10x measuring loupe, 0.05 mm reticle" } }
```

| Field | Type | Meaning | Unknown or untrusted |
|---|---|---|---|
| `export.file`, `export.sha256` | path in the bundle, 64-hex digest | the file the operator prints. The engine hashes the bundle's own file and compares, as it does for the STEP; a mismatch is bad input (exit 3), a missing file is `?` | STOP on the print step |
| `export.features` | list of manifest feature names | the lines the export draws. Not geometry the engine can check: the pins (§4.3) and the check bars (§4.2) are what catch a wrong or rescaled export at the bench | a plan `feature` not listed is bad input |
| `export.cite` | citations | where the export came from | STOP on the print step |
| `scale` | `Literal["1:1"]` | the only scale; anything else is bad input | — |
| `sheet` | enum `"letter" \| "a4" \| "tabloid" \| "a3"` | the paper the export is laid out on; the engine checks that the outline plus the bars fit it | STOP on the print step |
| `line_width_mm` | `MeasuredLength` (greatest width) | printed stroke width `w`. The export's stroke weight is not the printed width (toner spreads), so only a measurement on a print qualifies; a cite to the export's stroke weight stays debt | stack `?` → STOP on the follower (§4.4) |

### 2.3 Adhesive consumable

```toml
[consumables.spray-adhesive-3m-super-77]
kind = "spray_adhesive"
name = "3M Super 77 spray adhesive"
products = ["3M Super 77, 16.75 oz can"]
surface_prep = "Wipe the face with isopropyl alcohol; dry; no oil film or chips."
apply = "Spray a light coat on the back of the print only, from about 200 mm; wait the tack time; lay it on over the pins and smooth from the pins outward with a dry cloth."
tack_s = { value = 30, cite = "..." }          # wait between spraying and laying on
removal = { method = "solvent", agent = "...", wait_min = 2, cite = "..." }
```

| Field | Type | Unknown or untrusted |
|---|---|---|
| `surface_prep`, `apply` | text | STOP on that step |
| `tack_s` | `CitedFact` | STOP on the glue step |
| `removal` | `{ method = "solvent" \| "peel" \| "heat", agent \| temp_c, wait_min, cite }` (the area hold's release record, generalized) | STOP on the removal op |

Both new kinds join `ConsumableEntry`. `model._consumable_kind` today returns
`"adhesive_tape"` for *any* stated `kind`, so it becomes a lookup over the
known kinds, with an unknown kind bad input.

### 2.4 Gauge accuracy

`gauges.calipers-18in` carries `resolution_mm` only. Resolution is not
accuracy. Each gauge a `scale_check` names needs a new `mpe_mm`, a `CitedFact`
(the maker's maximum permissible error over the range used, or a cited
calibration record). Missing or uncited, the scale term is `?`.

### 2.5 How `follows` resolves

- `Plan.saw_shapes` is unchanged in shape: a `printed_pattern` scribe is a
  full-line scribe, so it lands in `scribes` and the lineage check applies.
- New: when the followed op lists more than one `feature`, the saw must name
  `feature`, one of them; otherwise bad input ("follows T2A:10, a print of 4
  lines: name the line with feature"). With one line, `feature` defaults to it.
  One saw op per line is necessary anyway: the top edge's removal is inside
  the R800 circle and the bottom's is outside R816, opposite `remove` sides.
- `kernel.scribed_profile` reads the arc from the saw's `feature` instead of
  the scribe's. A non-arc line (a land or taper) returns None, so its
  declared `stock_removal_bounds` alone governs, as for a straight scribed
  line today.
- Only `saw_cut` follows a print in phase 1 (§9). `file_to_line` to a printed
  line, where the print is the *finishing* line, is phase 6: the same stack is
  then compared with the drawing's band instead of an allowance. `rough_*`
  mill ops are located by the DRO and do not follow lines.

### 2.6 Removal

A new manual op `do = "remove_pattern"` with `removes = "<setup>:<op>"`, a
`printed_pattern` scribe on its workpiece lineage. It prints the adhesive's
`removal` record. A new check in the same rule: every op after the pattern op,
on the same workpiece, that locates on, clamps on, measures from or cuts the
`on` face must come after a `remove_pattern` for it. A missing removal before
such an op is an `error` (the paper and glue move that op's datum by an
unmodelled amount), not `?`. The saw ops that follow the print are exempt:
they cut beside the line, not on the face.

## 3. Operator step sequence

In order, with the error each step introduces (§4 gives the arithmetic):

| # | Step | Where | Error it introduces |
|---|---|---|---|
| 1 | **Print.** Print `export.file` (the traveler shows its name and first 12 hex of its SHA-256; check them) at *actual size / 100 %*, no fit-to-page, on one `sheet`. | office | printer scale, anisotropic: `ε_x`, `ε_y` |
| 2 | **Check scale before gluing.** Read every check bar with the named gauge. Accept only inside `length_mm ± tolerance_mm`; otherwise reprint, never glue. | bench | bounds `ε` per axis (§4.2) |
| 3 | **Prepare the surface.** The adhesive's `surface_prep` on the `on` face. | bench | none modelled; a dirty face lets the print lift (STOP if no text) |
| 4 | **Set the pins.** A gauge pin of the declared size in each registration hole, standing proud of the face. | bench | pin-in-hole clearance |
| 5 | **Glue.** The adhesive's `apply`: spray the back of the print, wait `tack_s`, lay it on over the pins so each pin pierces its printed crosshair, smooth from the pins outward. | bench | paper movement while smoothing (bounded by step 7) |
| 6 | **Check registration.** At each pin, the pin's edge must lie inside the printed circle's line all round (loupe). Any pin whose edge leaves the line: peel, discard, reprint. Then pull the pins. | bench | bounds registration (§4.3) |
| 7 | **Check scale again, on the work.** Re-read the bars that lie on the work. Same acceptance. This is the reading the stack uses: it includes stretch from the adhesive and the smoothing. | bench, immediately before the saw | bounds `ε` after gluing |
| 8 | **Saw to the line.** For each printed line: saw outside it, leaving `allowance_mm` between the line and the blade's near side; feed by hand along the line. | bandsaw, vertical | following error `f` |
| 9 | **Remove the print** before any op that locates on, clamps on or measures from the `on` face: the adhesive's `removal`. | bench | none once the face is clean |

Step 7 is the design's answer to paper stretch and adhesive creep (Q4). No
cited magnitude for paper hygroexpansion under a spray adhesive was found for
this document; rather than guess one, the stack uses a measurement taken after
gluing and immediately before the cut. What remains unmodelled is drift
during the cut itself (§4.6).

## 4. Error model

### 4.1 What is compared with what

At every point of a followed line, the radial stock the saw leaves outside the
true outline is

```text
stock = allowance_mm ± f ± s(p) ± r(p) ± w/2 ± d
```

| Term | Physical reference | Source of its magnitude |
|---|---|---|
| `allowance_mm` | the op's authored leave, measured from the printed line to the blade's near side | plan |
| `f` | the operator's following error for the method (vertical bandsaw, hand saw, file) | shop policy, cited or measured (§4.5) |
| `s(p)` | print scale error at point `p`, from the registration origin | `scale_check` and the gauge's `mpe_mm` (§4.2) |
| `r(p)` | registration error at `p` | pin and hole limits, `w` (§4.3) |
| `w/2` | line half-width: the operator may reference any part of the line | `line_width_mm` (§4.4) |
| `d` | the registration holes' own position band relative to the datum the finishing op uses | drawing requirements; 0 when the finisher locates on the same holes (§4.3) |

Two comparisons, both required:

1. **Into the part:** `stock_min = allowance − f − max_p(s + r) − w/2 − d > 0`.
   Otherwise an `error`: the cut may enter the finished part.
2. **Past the finisher:** `stock_max = allowance + f + max_p(s + r) + w/2 + d ≤ cap`,
   where `cap` is what the next op on that feature removes: the policy
   `max_filing_stock_mm` for a `file_to_line`; for a guided sweep, the radial
   stock its stages declare. Over the cap is an `error`.

Any term unknown makes the follower `?`, and the traveler prints a STOP in
place of the saw step (§6). For bound 1 only, an unknown `w` would be safe at
0 if the operator always referenced the line's outer edge; the design does not
rely on that (the "far edge" test, §8.2), so `w` is required for both.

Each term is bounded by the magnitude of the displacement vector, not its
component along the line's normal. That is conservative: along most of the
strap the X scale error moves points nearly along the line. Projecting onto
the normal is a later refinement and changes no field.

### 4.2 Scale

A bar of printed length `L` along print axis `a` is read with a gauge of
maximum permissible error `m`. Each bar end is a printed tick of width up to
`w`, so setting a jaw on it adds up to `w/2` per end. An accepted reading
inside `L ± t` therefore bounds the scale error on that axis to

```text
ε_a = (t + m + w) / L
```

and at a point `p` whose offset from the registration origin `o` is
`(dx, dy)`, the scale displacement is at most

```text
s(p) = hypot(ε_x · dx, ε_y · dy)
```

- **The lever is from the registration origin, not the print's end.** The
  issue's "0.15 mm on 300 mm grows at 340 mm" measures from one end. With the
  print pinned at the hub, the longest lever to any line point is the
  distance from the hub to the far land: hypot(146.255, 15.800) = 147.1 mm
  *(example geometry)*. The engine derives the lever from the plan geometry
  (each registration hole's position to every sampled line point) and takes
  `o` as the hole that gives each point the least bound.
- **Printers scale each axis differently.** One bar proves one axis. An axis
  with no bar leaves `ε` unknown on it, and the stack `?`, unless every line
  point has zero offset on that axis (never, for an arc). Q3 asks whether to
  require a bar per axis or credit only the bar's axis.
- **The post-glue reading governs.** Both readings (§3 steps 2 and 7) use the
  same acceptance; the stack uses step 7's bars, which must lie on the work.
  On a 40 mm blank a Y bar is at most about 30 mm, so its reading error `w`
  dominates its `ε_y` (§10). The engine checks that each post-glue bar fits
  inside the `on` face's outline.

### 4.3 Registration

**Pins (computable).** A gauge pin stands in each registration hole and
pierces the print's crosshair; the operator then checks that the pin's edge
lies inside the printed circle's line all round. The printed circle is drawn
at the pin's nominal diameter `P_n`. Per hole:

```text
e = (H_max − P_min) / 2      pin in the drilled hole (drawing limits, pin set limits)
  + w / 2                    pin edge inside the printed line all round
  + |P_n − P_min| / 2        pin size against the printed circle
```

Two holes `A`, `B` at baseline `b = |A − B|` fix translation and rotation; the
rigid displacement at `p` is at most

```text
r(p) = min over ordered pairs (A, B) of  e_A + (e_A + e_B) · |p − A| / b
```

With three holes the minimum over pairs applies. The check in step 6 is a
geometric GO/NO-GO: it needs no operator-skill magnitude. A pin set whose
sizes or a hole whose limits are unknown leaves `r` unknown.

The term `d` is the registration holes' position band against the datum the
finishing op uses. The T3 trammel jig finishes the arcs about the pivot bore,
which is also a registration hole, so `d = 0` for it. A finisher on another
datum adds the holes' drawing position band; an unknown band is `?`.

**Edges.** Laying the print's printed edges to the stock's edges by eye has
no source for its error. Phase 1 accepts `register.kind = "edges"` in the
schema and prints a STOP: "registration to stock edges has no proven error:
register over drilled holes with pins". A later issue may add a cited or
measured edge-alignment fact.

**By eye over holes** (a printed circle centred over a hole without pins) has
no source either, and is not offered.

### 4.4 Line width

The line is a band of width `w` centred on the true outline. "Saw 1 mm
outside the line" may be read from either edge of the band, so the stack
carries `±w/2`. The same `w` enters the bar readings (§4.2) and the
registration check (§4.3). It must be measured on a print from this export;
the export's stroke weight is not evidence.

### 4.5 Following error

How closely a person holds a saw or file to a nominal offset from a line is a
shop fact, not a geometric one. It lives in policy, per method:

```toml
[numbers.line_following_mm]
bandsaw_vertical = { value = 0.3, cite = "..." }  # or measured = { ... } from a recorded trial cut
hand_saw = { value = ..., cite = "..." }
file = { value = ..., cite = "..." }
```

Each entry is a `CitedFact`. A trial cut (saw along a printed test line,
measure the offset at intervals) is a measurement and qualifies. Missing or
uncited, the follower is `?` (Q5). The method is derived from the op: a
`saw_cut` on a bandsaw in vertical mode is `bandsaw_vertical`, a hand-saw op
`hand_saw`.

The saw's kerf lies on the waste side and does not enter the stack:
`allowance_mm` is measured to the blade's near side, as `saw_cut` already
assumes.

### 4.6 Named residue (not modelled)

- Paper drift during the cut, after step 7's reading.
- Print lifting at the line under the blade, if the adhesive lets go locally.
  Step 7's reading does not see it; the operator stops and re-glues.
- Hole wall damage from the pins (gauge pins are not driven).

### 4.7 Every assumed magnitude has a source

| Magnitude | Source accepted | Without it |
|---|---|---|
| `t` (bar tolerance) | plan choice, positive | bad input if ≤ 0 |
| `m` (gauge MPE) | `gauges.<id>.mpe_mm`, cited | `?` |
| `w` | `line_width_mm`, measured | `?` |
| `H_min/max` | drawing limits of each registration hole | `?` |
| `P_min/max`, `P_n` | the pin set's inventory limits | `?` |
| `d` | drawing position band, or 0 by the same-hole rule | `?` |
| `f` | `numbers.line_following_mm.<method>`, cited or measured | `?` |
| `cap` | `max_filing_stock_mm`, or the finisher's declared stages | `?` |
| `tack_s`, `removal.wait_min` | the adhesive record, cited | STOP on that step |

## 5. Rule and the `manual_arc` row

A new rule module, `printed_pattern`, owns this layout:

- **Layout finding**, subject `<setup>:<op>` of the pattern op: export digest,
  sheet fit, bars on the work, pins and holes, adhesive record. Its numbers
  carry every value §6 lists, so the traveler reads them and never computes.
- **Follower finding**, subject `<setup>:<op>` of each saw that follows it:
  the stack terms, `stock_min`, `stock_max`, the cap and the verdict.
- **Removal finding**, subject `<setup>:<op>` of each op the removal gate
  covers (§2.6).

`manual_arc` skips `layout = "printed_pattern"` ops (they may list several
features and print no centre). In `sheet.manual_arc_steps`, the scribe branch
for this layout prints the pattern instead of a centre and radius:

```text
Layout: glue the 1:1 print "Rocker strap outline, 1:1 print"
(strap-outline.pdf, SHA-256 3f9a…c21e) on the strap top face; lines used:
top edge R800, bottom edge R816, east and west end lands.
```

`sheet.saw_setting` for a saw that follows a print reads
"outside the printed top edge (T2A op 10)" in place of "outside the line
scribed in T2A op 10".

## 6. Unknown-value gate

The pattern op and each follower print runnable steps only when **every**
value below is proven. Any unproven value replaces that step with its STOP
row and adds it to the setup's STOP list; no partial recipe prints.

| # | Printed or consumed value | Proven by | STOP form |
|---|---|---|---|
| G1 | export file name and SHA-256 | bundle file hashes to `export.sha256`; `export.cite` known | `STOP: print source not established — <reason>` |
| G2 | sheet and "actual size, one sheet" | `sheet` known; outline plus bars fit it | `STOP: print does not fit one <sheet> sheet` |
| G3 | each check bar: axis, `length_mm`, accept window | `scale_check` entry; bar on the export; post-glue bar inside the `on` face | `STOP: check bar <axis> not established` |
| G4 | the gauge that reads the bars | gauge resolves, range covers `length_mm`, `mpe_mm` cited | `STOP: scale check gauge not established` |
| G5 | surface prep text | adhesive `surface_prep` known | `STOP: surface preparation not established` |
| G6 | adhesive product, apply text, tack time | `products`, `apply`, `tack_s` cited | `STOP: adhesive application not established` |
| G7 | registration holes and pin size | each hole drilled to size earlier on this workpiece; pin set resolves with limits; `kind = "pins"` | `STOP: registration not established — <reason>` |
| G8 | line width (consumed, not printed) | `line_width_mm` measured | `STOP: printed line width not measured` |
| G9 | saw allowance | `allowance_mm` known and > 0 | `STOP: stock to leave outside the line not established` (existing form) |
| G10 | following error (consumed) | policy entry cited or measured | `STOP: following error for <method> not established` |
| G11 | predicted stock window `stock_min`–`stock_max` for the finisher | §4.1 both bounds pass | `STOP: printed line may leave <min>–<max>, outside 0–<cap> — do not run` |
| G12 | finisher cap (consumed) | cap resolves | `STOP: stock the finishing op takes is not established` |
| G13 | removal method, agent, wait | adhesive `removal` cited | `STOP: print removal not established` |
| G14 | blade speed | existing `speeds_feeds` | existing `STOP: no blade speed` |

## 7. Traveler mock-up: T2 (for the blind machinist read)

The values are this document's illustrative ones, not shop facts. T2A is a
bench setup, so it prints the ASSEMBLY / FINISHING table (step, feature,
material / consumable, action, inspection). T2B is the bandsaw's machine
card.

```text
SETUP T2A — fitting bench — ASSEMBLY / FINISHING
Stock in: strap blank from T1, both faces faced, pivot bore and two tooling holes drilled.

Step 10 | top edge, bottom edge, east and west end lands
  Consumable: Rocker strap outline, 1:1 print (strap-outline.pdf,
              SHA-256 3f9a1d07c21e…); 3M Super 77 spray adhesive
  Action:
   a. Print strap-outline.pdf on one tabloid sheet at ACTUAL SIZE (100 %).
      Turn off "fit to page". Check the file name and SHA-256 above.
   b. Before gluing: read check bar X with 18 in calipers. Accept
      299.85–300.15 mm. Read check bar Y. Accept 29.95–30.05 mm.
      Outside either: reprint. Do not glue.
   c. Wipe the strap top face with isopropyl alcohol; let it dry.
   d. Stand a Ø3.990–4.000 gauge pin in the pivot bore and in each
      tooling hole.
   e. Spray a light coat on the back of the print only. Wait 30 s. Lay it
      on so each pin goes through its printed cross. Smooth outward from
      the pins with a dry cloth.
  Inspection:
   f. At each pin, with the loupe: the pin's edge is inside the printed
      circle's line all the way round. If not: peel the print off, reprint,
      go back to c.
   g. Pull the pins.

SETUP T2B — 4x6 bandsaw, VERTICAL mode
Op | Feature     | Tool        | Speed    | Feed                    | Action
10 | top edge    | 1/2 in blade| 165 sfm  | by hand along the line  | Just before cutting: read check bar X
   |             |             |          |                         | on the strap: 299.85–300.15; bar Y:
   |             |             |          |                         | 29.95–30.05. Outside: STOP, re-glue.
   |             |             |          |                         | Saw outside the printed top edge
   |             |             |          |                         | (T2A step 10); leave 1.0 mm outside
   |             |             |          |                         | the line. Leaves 0.12–1.88 mm for T3.
20 | bottom edge | 1/2 in blade| 165 sfm  | by hand along the line  | Saw outside the printed bottom edge
   |             |             |          |                         | (T2A step 10); leave 1.0 mm outside
   |             |             |          |                         | the line. Leaves 0.12–1.88 mm for T3.
30 | east land   | ...         |          |                         | ...

SETUP T3 — first bench step
Step 5 | strap top face
  Action: Remove the print: <removal agent>, wait 2 min, peel; wipe the face
          clean. Nothing of the paper or glue may stay on the face the jig
          sits on.
```

With following error 0.5 instead of 0.3 (§10), T2B's rows print instead:

```text
STOP: printed line may leave -0.08–2.08 mm, outside 0–2.00 for T3 — do not run.
```

## 8. Test plan

Unit tests inject synthetic `bundle.kernel` results where geometry is needed,
as AGENTS.md requires; no test reads a real shop file.

### 8.1 One parametrized test per printed field

`test_printed_pattern_gate`, parametrized over G1–G13 (§6). Each case starts
from one fully proven synthetic bundle (pattern, adhesive, gauge with
`mpe_mm`, pins, holes, policy) and makes exactly one value unproven:

| Case | Mutation | Asserts |
|---|---|---|
| G1 | digest mismatch; file missing; blank cite | mismatch exit 3; others `?` and the G1 STOP, no runnable step |
| G2 | outline wider than the sheet | G2 STOP |
| G3 | no Y bar; post-glue bar outside the `on` face | `?`, G3 STOP |
| G4 | gauge with `resolution_mm` and no `mpe_mm`; range under `length_mm` | G4 STOP |
| G5, G6, G13 | each text or cited fact `"unknown"` | that step's STOP, and no other step of the recipe prints as runnable |
| G7 | hole drilled after the pattern op; pin set without limits; `kind = "edges"` | G7 STOP |
| G8 | `line_width_mm` cited, not measured | G8 STOP |
| G9 | `allowance_mm = "unknown"` | existing STOP |
| G10 | no policy entry for the method | G10 STOP |
| G11 | values that close only one bound | the G11 STOP with the computed window |
| G12 | finisher with no cap | G12 STOP |

Each case also asserts the report status (`unknown`, exit 4 with no error, or
`error`, exit 2) so no unproven value reads as a pass.

### 8.2 Operator-perturbation tests

Each test realizes one operator error on synthetic geometry with an
independent oracle (rigid transform plus scale applied to sampled line points,
then the realized cut offset measured against the true outline), and asserts:
**either the rule passes and the realized stock lies in `(0, cap]` at every
sample, or the traveler prints a STOP.** Never a pass with stock outside.

| Test | Perturbation | Expected |
|---|---|---|
| `test_scale_off_by_tolerance` | print scaled so the post-glue bar reads `L + t` (and `L − t`), each axis | with the §10 inputs, pass and stock in band; with `t` raised until `stock_min ≤ 0`, STOP |
| `test_registration_off_by_hole_clearance` | each pin shifted to the far side of its hole (`(H_max − P_min)/2`) and the print rotated by the worst pair combination | pass and in band; with an oversize hole, STOP |
| `test_line_followed_at_far_edge` | the operator references the line's inner edge (`−w/2`) with the following error at its full value toward the part | pass and in band with `f = 0.3`; STOP with `f = 0.5` |
| `test_perturbations_combined` | all three at once, worst sign | the stack's `stock_min` equals the oracle's least stock within 1e-6 |

### 8.3 Schema and validator tests

- `layout = "printed_pattern"` without `pattern`, `adhesive`, `scale_check`
  or `register`: bad input naming the missing field. Those fields on any other
  op: bad input.
- A saw following a multi-line print without `feature`, or with a feature not
  in the print: bad input.
- `scale != "1:1"`, a `scale_check` with `tolerance_mm <= 0`, an unknown
  consumable `kind`: bad input.
- `remove_pattern` naming a non-pattern op, or one on another workpiece:
  bad input. An op clamping the `on` face before the removal: `error`.

## 9. Phased implementation plan

| Phase | Content | Depends on |
|---|---|---|
| 1 | Schema: the two consumable kinds and the discriminator fix, `mpe_mm`, op fields, validators, `remove_pattern`; §8.3 tests | — |
| 2 | Policy `line_following_mm`; export digest check; docs (inventory, plan, policy, rules-operations) | 1 |
| 3 | Kernel: `scribed_profile` reads the saw's `feature`; sampled line points and hole positions in setup coordinates for the stack; sheet-fit and bar-on-face checks | 1 |
| 4 | Rule `printed_pattern`: layout, follower and removal findings; §8.1 and §8.2 tests | 2, 3 |
| 5 | Traveler rows, STOP forms, machinist review on the affected bundle | 4 |
| 6 | `file_to_line` to a printed line (stack against the drawing band) | 4 |

No shipped example uses a print; the consumer change is harmonic-analyzer
#1595's T2.

## 10. Worked example: strap T2 (illustrative arithmetic)

```text
Geometry  hub (pivot bore) at X 0 Y 0; line points sampled on R800, R816, lands, tapers
          (example geometry); tooling holes at X ±160, Y 8 (illustrative)
Bars      X: L 300, t 0.15 (shop record); Y: L 30, t 0.05 (illustrative)
Gauge     m 0.03 (illustrative)          Line  w 0.20 (illustrative)
Holes     Ø4.000–4.030, pins Ø3.990–4.000, P_n 4.000 (illustrative)

ε_x = (0.15 + 0.03 + 0.20) / 300 = 1.27e-3
ε_y = (0.05 + 0.03 + 0.20) / 30  = 9.33e-3
s   = max hypot(ε_x·dx, ε_y·dy) = 0.27   (at the arc ends: 0.185 in X, 0.199 in Y)
      issue's reading, tolerance only, from one end: 0.15 × 340/300 = 0.17
      tolerance only, from the hub:                  0.15 × 147.1/300 = 0.07

e   = (4.030 − 3.990)/2 + 0.20/2 + (4.000 − 3.990)/2 = 0.125 per hole
r   = max over points of the best pair = 0.21   (pivot bore and one tooling hole only: 0.35)
d   = 0                  (T3 finishes about the pivot bore, a registration hole)

f 0.3:  stock = 1.0 ± (0.3 + 0.27 + 0.21 + 0.10) = 0.12 … 1.88   → pass if T3 takes ≥ 1.88
f 0.5:  stock = 1.0 ± (0.5 + 0.27 + 0.21 + 0.10) = −0.08 … 2.08  → error: may enter the part
```

Read honestly, the illustrative inputs say:

- the Y bar is the largest scale term, not the 300 mm X bar: a 30 mm bar read
  across a 0.20 line spends most of its accuracy on reading the ticks. A finer
  bar line or a longer Y lever helps more than tightening the X tolerance;
- the third registration hole is worth 0.14 mm: with only the pivot bore and
  one tooling hole, the far end swings about the near pin;
- whether +1 closes is decided by the following error, which today has no
  source at all. Until the shop records a trial cut, T2B prints a STOP.

## 11. Open questions for the owner

Each is also asked in the PR and mirrored there as a comment; the recommended
option is first.

| # | Question | Options (recommended first) |
|---|---|---|
| Q1 | Op shape | **`do = "scribe"`, `layout = "printed_pattern"`**: reuses `follows`, `_full_line`, `scribed_profile`; or a new `do = "apply_pattern"`: honest name, every followable-line site gains a second action |
| Q2 | Pattern source | **External export identified by bundle path + SHA-256 + cite** (the consumer's outline export); or prechips generates the print from the bundle's STEP (identity is the STEP digest; larger kernel work, later phase) |
| Q3 | Check bars | **One bar per axis, both read before and after gluing**; or credit only the bar's axis and STOP on any line point with an offset on the other |
| Q4 | Paper stretch and adhesive creep | **Re-read the bars on the work immediately before the cut; the stack uses that reading**; or a cited hygroexpansion magnitude; or always STOP |
| Q5 | Following error | **Policy `line_following_mm.<method>`, cited or from a recorded trial cut**; or a fixed fraction of `allowance_mm` (no source, so not recommended) |
| Q6 | Sheet | **One sheet (tabloid / A3) only; tiled prints refused in phase 1**; or tiled Letter with tile registration marks (the tile-joint error has no source) |
| Q7 | Removal | **Explicit `remove_pattern` op, required before any op that locates on, clamps on or measures from the glued face**; or a printed note in the next setup with no gate |

## 12. Open review notes

None yet.
