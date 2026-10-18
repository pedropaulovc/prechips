# Design: printed 1:1 paper pattern as a layout line

Status: **owner decided D1–D7 (2026-10-18); Q8–Q9 open; not implemented.** Issue
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
| 7. Decisions and open questions | §11 |

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

**Decided (D1):** keep `do = "scribe"` and add one layout kind,
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
pattern = "tabloid-laser-paper"            # consumables, kind = "printed_pattern" (printer and paper)
adhesive = "spray-adhesive-3m-super-77"     # consumables, kind = "spray_adhesive"
scale_check = [   # at = "margin": read before gluing only; at = "work": read before gluing and again before the cut
  { at = "margin", axis = "x",  length_mm = 300.0, gauge = "calipers-18in", tolerance_mm = 0.15 },
  { at = "margin", axis = "y",  length_mm = 200.0, gauge = "calipers-18in", tolerance_mm = 0.15 },
  { at = "margin", axis = "xy", length_mm = 360.555, gauge = "calipers-18in", tolerance_mm = 0.15 },   # Q9
  { at = "work",   axis = "x",  length_mm = 300.0, gauge = "calipers-18in", tolerance_mm = 0.15 },
  { at = "work",   axis = "y",  length_mm = 30.0,  gauge = "calipers-18in", tolerance_mm = 0.05 },
]
register = { kind = "pins", holes = ["pivot_bore", "tool_hole_east", "tool_hole_west"], pins = "gauge-pins" }
station_check = { gauge = "calipers-18in", tolerance_mm = 0.40 }   # line stations, §4.8

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
| `feature` | `str` or list (min 1) | the lines the plan uses from the print; each is drawn from the bundle STEP onto the generated print (§2.2) |
| `on` | `str` | the manifest face the print is glued to; drives the removal gate (§2.6) |
| `pattern` | `str` | a `consumables` item of kind `printed_pattern`: the printer and paper the generated PDF is printed on |
| `adhesive` | `str` | a `consumables` item of kind `spray_adhesive` |
| `scale_check` | list of `{ at = "margin" \| "work", axis = "x" \| "y" \| "xy", length_mm, gauge, tolerance_mm }`, min 1 | a printed check bar, where it is printed, the gauge that reads it and the accepted error; the generator draws each one |
| `register` | `{ kind = "pins", holes, pins }` or `{ kind = "edges", edges }` | how the print is located on the work (§4.3) |
| `station_check` | `{ gauge, tolerance_mm }` | the gauge and tolerance for the pin-to-line stations (§4.8) |

The issue's free-text `locate` is replaced by the typed `register`; its prose
stays available as `note`.

### 2.2 The generated print and the printing consumable

**Decided (D2):** prechips generates the print from the bundle's own STEP.
No external export is accepted. The print is deterministic output from the
inputs, like the traveler, and the traveler run writes it beside
`traveler.html`.

**The artifact.** For each `printed_pattern` op, the traveler run writes
`pattern-<setup>-<op>.pdf`:

| Element | Content | From |
|---|---|---|
| Outline | each `feature` the op lists, at 1:1: the edges of its STEP faces where they meet the `on` face's plane, in the `on` face's frame | the kernel, on the bundle STEP |
| Registration circles | each `register.holes` hole as a circle at the pin set's nominal diameter `P_n`, with a centre crosshair | the kernel (hole axis on the `on` plane) and the pin set |
| Keep side | a short "KEEP" label and hatching on the waste side of each followed line | the saw's `remove` side (§2.5) |
| Check bars | one bar per axis (D3), each with end ticks, its nominal length and its accept window; the post-glue bars placed inside the `on` face's outline, the pre-glue bars along the sheet margin | `scale_check` |
| Line stations | each station's tick on the line, and from each pin it is read from a printed dimension line, pin edge to tick, labelled with its window (§4.8), so the calipers lie along the printed line and the measuring direction is on the paper | the rule |
| Title block | the match code in large type (below), which the operator compares with the traveler; then the full identities for audit: part name, `STEP sha256`, plan revision, setup and op, engine digest; sheet size; the scale statement `SCALE 1:1 — PRINT AT 100 % / ACTUAL SIZE — NO FIT TO PAGE`; the pattern file's own SHA-256 is not printed on itself (it cannot be), the traveler carries it | bundle identity |

**Format.** A one-page vector PDF whose page box is exactly the declared
`sheet` (tabloid 279.4 × 431.8, A3 297 × 420), zero margins, user unit
1 pt = 25.4/72 mm, strokes at one generator constant width, text in a
standard base-14 font (no embedding). `/ViewerPreferences` carries
`/PrintScaling /None`, which some print dialogs honour; the printed
instruction and the check bars are what the shop relies on. Arcs are cubic
Béziers split until each segment's radial deviation from the true arc is
under 0.001 mm (computed, not assumed); straight edges are lines.

**Writer.** Host Python writes the PDF directly (a few hundred lines: page,
paths, text). The kernel supplies only the geometry: for each listed feature,
its boundary edges on the `on` plane as exact arcs and lines in the `on`
face's frame. The print browser is not used, because a browser print adds
its own margins and scale.

**Determinism.** The same STEP bytes, features, plan, policy, inventory and
engine give byte-identical PDF output: no timestamp, a fixed `/ID` derived
from the content, sorted dictionaries and fixed number formatting. The pattern
digest joins the traveler's identity, and the kernel cache key gains the op's
feature list and `on` face, so a changed STEP or plan re-runs the geometry.

**How the traveler references it.** The T2A row names the file
`pattern-T2A-10.pdf` and one short **match code** (six characters from an
unambiguous alphabet, printed as `K7Q-4MD`). The print's title block carries
the same code in large type, and the operator compares the two. The code is
derived from the SHA-256 of the drawing content before the title block is
stamped (a file cannot carry its own hash), so any change to the geometry,
bars, stations or identities changes it. Full identities live on the title
block (STEP digest, plan revision, engine digest) and in `report.json` (those
plus the finished file's SHA-256). The traveler prints no truncated hash. A traveler run without a kernel writes no pattern: the row is a STOP
and the exit is 4, as for any missing kernel fact.

**The printing consumable.** What the engine cannot generate is how a given
printer and paper render the file. That stays a consumable:

```toml
[consumables.tabloid-laser-paper]
kind = "printed_pattern"
name = "Tabloid laser prints, office printer"
products = ["11 x 17 in 24 lb laser paper"]
sheet = "tabloid"            # one sheet; tiled prints are refused (D6)
# greatest printed stroke width of the generator's lines, read on a print from this printer
line_width_mm = { value = 0.20, measured = { status = "measured", by = "...", date = "...", instrument = "10x measuring loupe, 0.05 mm reticle" } }
```

| Field | Type | Meaning | Unknown or untrusted |
|---|---|---|---|
| `sheet` | enum `"letter" \| "a4" \| "tabloid" \| "a3"` | the page box the generator lays out on; the rule checks the outline, bars, stations and title block fit it | STOP on the print step |
| `line_width_mm` | `MeasuredLength` (greatest width) | printed stroke width `w`. The generator's stroke constant is not the printed width (toner spreads), so only a measurement on a print qualifies | stack `?` → STOP on the follower (§4.4) |

The scale is not a field: the generator writes only 1:1.

### 2.3 Adhesive consumable

```toml
[consumables.spray-adhesive-3m-super-77]
kind = "spray_adhesive"
name = "3M Super 77 spray adhesive"
products = ["3M Super 77, 16.75 oz can"]
surface_prep = "Wipe the face with isopropyl alcohol; dry; no oil film or chips."
apply = "Spray a light coat on the back of the print only, from about 200 mm; wait the tack time; lay it on over the pins and smooth from the pins outward with a dry cloth."
tack_s = { value = 30, cite = "..." }          # wait between spraying and laying on
removal = { method = "solvent", agent = "<consumables id>", wait_min = 2, cite = "..." }
```

| Field | Type | Unknown or untrusted |
|---|---|---|
| `surface_prep`, `apply` | text | STOP on that step |
| `tack_s` | `CitedFact` | STOP on the glue step |
| `removal` | `{ method = "solvent" \| "peel" \| "heat", agent \| temp_c, wait_min, cite }` (the area hold's release record, generalized); `agent` names a `consumables` item, whose `name` the row prints | STOP on the removal op, including an agent that is not in the consumables inventory |

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
| 1 | **Print.** Print the generated `pattern-<setup>-<op>.pdf` (the traveler shows its name and first 12 hex of its SHA-256; check them, and check the title block's plan revision and STEP digest against the traveler's front sheet) at *actual size / 100 %*, no fit-to-page, on one `sheet`. | office | printer scale, anisotropic: `ε_x`, `ε_y` |
| 2 | **Check scale before gluing.** Read every check bar with the named gauge. Accept only inside `length_mm ± tolerance_mm`; otherwise reprint, never glue. | bench | bounds `ε` per axis (§4.2) |
| 3 | **Prepare the surface.** The adhesive's `surface_prep` on the `on` face. | bench | none modelled; a dirty face lets the print lift (STOP if no text) |
| 4 | **Set the pins.** A gauge pin of the declared size in each registration hole, standing proud of the face. | bench | pin-in-hole clearance |
| 5 | **Glue.** The adhesive's `apply`: spray the back of the print, wait `tack_s`, lay it on over the pins so each pin pierces its printed crosshair, smooth from the pins outward. | bench | paper movement while smoothing (bounded by step 7) |
| 6 | **Check registration.** At each pin, the pin's edge must lie inside the printed circle's line all round (loupe). Any pin whose edge leaves the line: peel, discard, reprint. | bench | bounds registration (§4.3) |
| 6a | **Check the line stations.** With the pivot pin still in, read with the calipers from the pin to the printed line at each station the traveler lists, and accept only inside each station's window. Any station outside: peel, discard, reprint. Then pull the pins. | bench | catches a printer path that is not affine, and local distortion, at the stations (§4.8) |
| 7 | **Check scale again, on the work.** Re-read the bars that lie on the work. Same acceptance. This is the reading the stack uses: it includes stretch from the adhesive and the smoothing. | bench, immediately before the saw | bounds `ε` after gluing |
| 8 | **Saw to the line.** For each printed line: saw outside it, leaving `allowance_mm` between the line and the blade's near side; feed by hand along the line. | bandsaw, vertical | following error `f` |
| 9 | **Remove the print** before any op that locates on, clamps on or measures from the `on` face: the adhesive's `removal`. | bench | none once the face is clean |

Step 7 is the design's answer to paper stretch and adhesive creep (D4). No
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
  point has zero offset on that axis (never, for an arc). D3 requires one bar
  per axis.
- **Skew.** An X and a Y bar together do not bound shear: a sheet fed at a
  slant can read both bars in tolerance while its axes are not square. The
  formula above holds for an affine print only when a third, diagonal bar
  (`axis = "xy"`) is also read; with the three, the print's 2×2 linear map is
  bounded and `s(p)` uses that bound. Without a diagonal bar the stack is `?`.
  The diagonal is read before gluing only, as the diagonal of a rectangle on
  the sheet margin whose sides are the X and Y bars (for example 300 × 200):
  a diagonal on a 40 mm strap runs at under 6° and barely sees shear. Shear
  added by smoothing on the work is what the stations (§4.8) catch.
- **Non-affine distortion** (local stretch or a wrinkle smoothed flat) is not
  bounded by any set of bars. The line stations (§4.8) measure it where they
  are; between stations it is residue the owner decides on (Q8).
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
registration check (§4.3). It must be measured on a print from the shop's printer;
the generator's stroke constant is not evidence.

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
uncited, the follower is `?` (D5). The method is derived from the op: a
`saw_cut` on a bandsaw in vertical mode is `bandsaw_vertical`, a hand-saw op
`hand_saw`.

The saw's kerf lies on the waste side and does not enter the stack:
`allowance_mm` is measured to the blade's near side, as `saw_cut` already
assumes.

### 4.6 Named residue (not modelled)

- Non-affine distortion between line stations (§4.8, Q8).
- Paper drift during the cut, after step 7's reading.
- Print lifting at the line under the blade, if the adhesive lets go locally.
  Step 7's reading does not see it; the operator stops and re-glues.
- Hole wall damage from the pins (gauge pins are not driven).

### 4.8 Line stations: measuring the printed line itself

The digest, bars and pins prove the print's bytes, its scale and where it
sits; none of them proves that the printed arc is the manifest's arc. A PDF
whose bars and hole circles are right but whose top edge is R790 passes all
three. So the glued line is measured directly.

The rule chooses stations on each followed line: both ends and the midpoint
at least, and more until no two neighbours are farther apart than
`station_spacing_mm` (Q8). Each station is a short tick printed across the
line. For each station the rule prints two nominal distances: the straight
distance from the near edge of each of two registration pins (the pivot pin
and the nearer tooling-hole pin) to the point where the tick crosses the line,
read with the calipers' jaw tips. One distance from one pin proves the point
only along that pin's radial direction, which near the strap's ends runs
almost along the line; two pins at an angle fix the point in the plane. Each
window is

```text
nominal ± (k_station − m − w/2)
```

where `k_station` is the station tolerance the plan sets
(`station_check = { gauge, tolerance_mm }` on the pattern op) and the reading
error `m + w/2` is taken out of it, so an accepted reading proves the line
within `k_station` of the nominal along each pin's direction. The stack
needs the station's displacement along the line's normal. One pin whose
direction lies within 30° of that normal proves it alone, to
`k_station / cos φ` (φ the angle between them), as the pivot pin does at the
strap's midpoint. Otherwise the rule uses two pins and the bound
`k_station / sin θ` on the whole displacement, θ the angle between the two
pin directions at the station; a station where neither works is not offered. A window that
the reading error swallows (`k_station ≤ m + w/2`) is bad input.

At a station the stack's `s(p) + r(p)` is replaced by that bound when it is
smaller. Between stations the bound stays `s(p) + r(p)` from the bars and
pins; that bound assumes the print is affine. With the print generated from
the STEP (D2), a wrong outline is a generator defect, caught by the generator
tests (§8.4) rather than at the bench; the stations still catch a printer or
paper path that does not render the file faithfully. Three stations on an arc
fix its circle, so a print whose arc has the wrong radius or centre fails at
least one station. Distortion between stations is the residue Q8 decides.

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

- **Layout finding**, subject `<setup>:<op>` of the pattern op: the generated
  print's geometry (from the kernel) and digest, sheet fit, bars on the work, pins and holes, adhesive record. Its numbers
  carry every value §6 lists, so the traveler reads them and never computes.
- **Follower finding**, subject `<setup>:<op>` of each saw that follows it:
  the stack terms, `stock_min`, `stock_max`, the cap and the verdict.
- **Removal finding**, subject `<setup>:<op>` of each op the removal gate
  covers (§2.6).

`manual_arc` skips `layout = "printed_pattern"` ops (they may list several
features and print no centre). In `sheet.manual_arc_steps`, the scribe branch
for this layout prints the pattern instead of a centre and radius:

```text
Layout: glue the 1:1 print pattern-T2A-10.pdf (match code K7Q-4MD) on the
strap top face; lines used: top edge R800,
bottom edge R816, east and west end lands.
```

`sheet.saw_setting` for a saw that follows a print reads
"outside the printed top edge (T2A op 10)" in place of "outside the line
scribed in T2A op 10".

### 5.1 Setup pictures

Each setup gets a picture, drawn from the same kernel geometry as the print
and through the existing setup-picture path:

- **The pattern setup (T2A):** a top view of the `on` face with the
  generated outline over it; each registration pin standing in its hole; the
  bars that lie on the work; the KEEP side and the hatched waste. It shows the
  print's orientation on the work, so a print laid on the strap upside down or
  end for end is visibly wrong before gluing.
- **Each saw that follows the print (T2B):** the work on the saw's table, the
  followed line, the kept and waste sides, the blade where it enters the
  waste, and a feed arrow along the line. The table and support come from the
  #335 hold line once it prints.

A picture whose geometry is unknown is not drawn; the row's STOP stands. The
pictures join the paired main-versus-PR picture review in phase 5.

## 6. Unknown-value gate

The pattern op and each follower print runnable steps only when **every**
value below is proven. Any unproven value replaces that step with its STOP
row and adds it to the setup's STOP list; no partial recipe prints.

| # | Printed or consumed value | Proven by | STOP form |
|---|---|---|---|
| G1 | pattern file name and match code (the title block and `report.json` carry the full identities) | the kernel returned every listed feature's edges on the `on` plane and every registration hole's axis; the PDF was written | `STOP: pattern not generated — <reason>` (no kernel: exit 4) |
| G2 | sheet and "actual size, one sheet" | `sheet` known; outline plus bars fit it | `STOP: print does not fit one <sheet> sheet` |
| G3 | each check bar: axis, `length_mm`, accept window | `scale_check` entry; bar fits the sheet; post-glue bar inside the `on` face | `STOP: check bar <axis> not established` |
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
| G15 | each line station: X, nominal pin-to-line distance, window | `station_check` known; window wider than the reading error; stations cover each followed line at `station_spacing_mm` | `STOP: printed line stations not established` |
| G16 | diagonal bar | a `scale_check` with `axis = "xy"` | `STOP: print skew not checked` |

## 7. Traveler mock-up: T2 (for the blind machinist read)

The values are this document's illustrative ones, not shop facts. The
example inventory has no solvent consumable, so T3's removal row shows the
STOP it prints until one is recorded. The bandsaw's hold and blade pitch are
not specified here: T2B prints the hand-fed hold line of
[#335](https://github.com/pedropaulovc/prechips/issues/335) and the blade
TPI fact of [#336](https://github.com/pedropaulovc/prechips/issues/336)
(implemented in #341). T2A is a bench setup, so it prints the ASSEMBLY / FINISHING table (step, feature,
material / consumable, action, inspection). T2B is the bandsaw's machine
card.

```text
SETUP T2A — fitting bench — ASSEMBLY / FINISHING
Stock in: strap blank from T1, both faces faced, pivot bore and two tooling holes drilled.
[Setup picture T2A: top view of the strap, with the print's outline over it,
 the three gauge pins standing in the pivot bore and the tooling holes, the
 X and Y bars on the strap, KEEP inside the outline and the waste hatched]

Step 10 | top edge, bottom edge, east and west end lands
  Consumable: pattern-T2A-10.pdf, match code K7Q-4MD (made with this
              traveler), printed on tabloid laser paper;
              3M Super 77 spray adhesive
  Action:
   a. Print pattern-T2A-10.pdf on one tabloid sheet at ACTUAL SIZE (100 %).
      Turn off "fit to page" and any "shrink" option. The title block must
      show match code K7Q-4MD and SCALE 1:1. Another code: wrong print,
      do not use.
   b. Before gluing, with the 18 in calipers, on the sheet margin:
      bar X 299.85–300.15; bar Y 199.85–200.15; diagonal 360.41–360.71.
      On the strap outline: bar X 299.85–300.15; bar Y 29.95–30.05.
      Outside any: reprint. Do not glue.
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
   g. Pins still in. At each station the print shows a dimension line from
      a pin to the tick on the outline; it runs straight from the pin's
      centre to the point where the tick crosses the outline. Lay the
      calipers' outside-jaw tips along that printed line: one tip against
      the side of the pin that faces the station, the other on the point
      where the tick crosses the outline. Read:
        station           from pivot pin     from tooling pin
        top    X -140     139.20–139.74      21.23–21.77 (west)
        top    X    0       5.73–6.27        —  (pivot only; Y direction)
        top    X +140     139.20–139.74      21.23–21.77 (east)
        bottom X -130     127.75–128.29      28.24–28.78 (west)
        bottom X    0       5.73–6.27        —
        bottom X +130     127.75–128.29      28.24–28.78 (east)
      Outside any window: peel the print off, reprint, go back to c.
   h. Pull the pins.

SETUP T2B — 4x6 bandsaw, VERTICAL mode
Stock: 1018 strap, 2.5 thick, print glued on top.
Hold: [the hand-fed hold line from #335: table, guide height, hand position]
Blade: [the blade line with its TPI and teeth in the 2.5 mm work, #336/#341]
Lay the strap flat on the table, print up. Keep the side of each line
marked KEEP; the hatched side is waste.
[Setup picture T2B: the strap flat on the saw table, print up, the blade
 entering the waste side outside the printed top edge, a feed arrow along the
 line, KEEP toward the operator's guiding hand, the waste offcut beyond]
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
  Action: STOP: print removal not established — the adhesive record names
          no removal agent in the consumables inventory — do not run T3.
```

With a cited removal record whose agent is a consumables item, T3 step 5
prints that item's name, the wait, "peel the paper off; wipe the adhesive left
on the face off with a rag wet with" the same item, "wipe the face with
isopropyl alcohol; dry", and "the face must feel clean, not tacky". No removal
text is ever printed from a placeholder.

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
| `test_wrong_print_fails_a_station` | a print whose top edge renders at R790 (and, separately, its centre shifted 0.5) with correct bars and circles | the oracle's station reading falls outside its window, so the traveler's accept test rejects it; never a pass |
| `test_skew_needs_diagonal_bar` | a sheared print whose X and Y bars both read in tolerance | without a diagonal bar: `?` and the G16 STOP; with it, the shear is bounded and the stack holds against the oracle |
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

### 8.4 Pattern generator tests

- **Geometry round trip:** parse the written PDF's paths back (a small test
  parser for the generator's own subset) and compare every outline path with
  the kernel's edges for the listed features: deviation under 0.001 mm,
  including the Bézier split on R800.
- **Determinism:** two runs on the same inputs write byte-identical files;
  changing the STEP bytes, the plan revision, the feature list or `on`
  changes the digest and the title block.
- **Page box and scale:** the page box is exactly the declared sheet; the
  check bars' tick spacing in PDF units is `length_mm × 72/25.4`; the title
  block carries the full STEP digest, the plan revision and the scale
  statement.
- **No kernel:** with `FREECAD_CMD` set to a nonexistent path, no PDF is
  written, G1 prints its STOP and the exit is 4.
- Real-geometry tests request the shared `freecad_kernel` fixture; unit tests
  inject a synthetic `bundle.kernel` result.

## 9. Phased implementation plan

| Phase | Content | Depends on |
|---|---|---|
| 1 | Schema: the two consumable kinds and the discriminator fix, `mpe_mm`, op fields, validators, `remove_pattern`; §8.3 tests | — |
| 2 | Policy `line_following_mm`; docs (inventory, plan, policy, rules-operations) | 1 |
| 3 | Kernel: `scribed_profile` reads the saw's `feature`; each listed feature's edges on the `on` plane as exact arcs and lines, hole axes, sampled line points for the stack; sheet-fit and bar-on-face checks; cache key gains features and `on` | 1 |
| 3b | Pattern writer: deterministic one-page vector PDF (§2.2) from phase 3's geometry; §8.4 tests | 3 |
| 4 | Rule `printed_pattern`: layout, follower and removal findings; §8.1 and §8.2 tests | 2, 3 |
| 5 | Traveler rows, the pattern file beside the traveler, the setup pictures (§5.1), STOP forms, machinist review on the affected bundle | 3b, 4 |
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

## 11. Decisions and open questions

**Decisions (owner, 2026-10-18, on PR #346, recorded by the coordinator).**
The body above follows them.

| # | Question | Decision |
|---|---|---|
| D1 | Op shape | `do = "scribe"`, `layout = "printed_pattern"` (§2.1). |
| D2 | Pattern source | prechips generates the print from the bundle's STEP: a deterministic 1:1 vector PDF with check bars, title block (STEP digest, plan revision, scale statement) and the print-at-100 % instruction, referenced by the traveler (§2.2). No external export. |
| D3 | Check bars | One bar per axis (§4.2). |
| D4 | Stretch and creep | Bars read before gluing and re-read on the work right before the cut; the stack uses the re-read (§3 step 7). |
| D5 | Following error | Policy `line_following_mm.<method>`, cited or trial-measured; missing is `?` debt (§4.5). |
| D6 | Sheet | One tabloid or A3 sheet; tiling refused (§2.2). |
| D7 | Removal | A gated `remove_pattern` op (§2.6). |

**Still open** (raised by the Codex review after the questions were asked;
each is mirrored as a PR comment):

| # | Question | Options (recommended first) |
|---|---|---|
| Q8 | Distortion between line stations | **Stations at a policy `pattern_station_spacing_mm` (cited or set by the owner); between them the affine bound from bars and pins stands, named as residue**; or treat any point off a station as `?` (every print STOPs); or require a cited non-affine paper distortion bound |
| Q9 | Skew | **Add a diagonal bar, read before gluing on the sheet margin, beside D3's per-axis bars** (it bounds the printer's shear, which per-axis bars cannot); or per-axis bars only, with shear left to the stations |

## 12. Open review notes

Codex review round 1 (on `66bf57e`, before D1–D7) raised two P1 findings.
Both are addressed in the commits after it. Per the design-PR rule (one
round), no re-review was requested:

- *Bound nonuniform print distortion* (§4.2, §4.8): a diagonal bar bounds the
  printer's skew (G16, Q9), and the line stations measure distortion at each
  station from two pins. Distortion between stations is named residue (Q8).
- *Verify the exported outline geometry* (§2.2, §4.8): mostly answered by
  D2. The print is now generated from the bundle's STEP, so a wrong outline
  is a generator defect, caught by the round-trip tests (§8.4). The stations
  still catch a printer path that does not render the file faithfully.

Blind machinist read of §7 (coordinator, on `cf281b8`): five findings applied
to the design, all addressed in the next commit. The removal agent is now
taken from the consumables inventory or printed as a STOP; the example
inventory has none, so the mock-up shows the STOP. Truncated hashes are
replaced by one match code printed on both the traveler and the print, with
full identities on the title block and in `report.json`. Each station
reading names its edges and direction: the side of the pin facing the
station, along a printed dimension line from the pin centre. T2B references
#335's hand-fed hold line and #336's blade TPI fact, and names the keep
side.

Blind machinist read round 2 (on `ab8f8df`): none of the round 1 findings
came back. Two still applied, and both are addressed in the next commit:
setup pictures for T2A and T2B (§5.1, drawn into the mock-up as picture
captions), and the removal note moved out of the printed block. The
bracketed T2B hold and blade lines stay as references to #335 and #336/#341.
Their gates cover those rows once they print.

Not re-reviewed: the D2 rework (§2.2, §8.4, phase 3b) and the station
geometry (two pins, normal-direction bound). The §10 arithmetic leaves out
the diagonal bar and the station windows; both can only tighten the bound at
a station, never loosen it elsewhere.
