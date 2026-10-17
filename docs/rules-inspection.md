# Inspection rule

## `inspection`

Subjects are `feature:requirement` for every requirements-listed two-element
numeric-or-unknown `[low, high]` band, even outside the named tolerance set, plus
each declared requirement in the recognized scalar/unknown tolerance set:
`dia`, `nominal_dia`, `position_dia`, `finish_ra`, `depth`, `length`, `width`, `height`,
`thickness`, `separation`, `coaxiality_dia`, `angularity_dia`, `surface_profile`,
`height_above_pivot`, `radius`, `station`, `arc_len`, `bottom_radius`,
`bottom_arc_len`, `tip_land`, `land_angle_deg`, `groove_width`, `groove_depth`.
This shared model selection also
drives policy `toleranced_features`; unknown generic dimensions cannot evade it.
An omitted or wholly unknown requirements list, or an unknown list element,
creates `feature:unknown` with unknown status and remains selected by policy
`toleranced_features`. A feature with an explicitly known list containing no
banded or recognized tolerance requirement (including `requirements = []`) gets
a bare-feature not-applicable finding. A missing list must not receive that
not-applicable finding. Unknown recognized dimension values still need an explicit
check; absence from a known requirements list is known absence. Bands outside
the tolerance set do not get invented defaults: the author must explicitly
declare the requirement and its limits.
An explicitly unknown kind or finishing action produces unknown for each
requirement (or the bare feature if there are none), not not-applicable.

The check must occur on or after the last relevant finishing cut, not merely on
an earlier pilot. The rule ignores rough operations, spot, deburr, coating and
release for this purpose. `checks` maps each requirement to its gauge; a missing
entry is an error, while literal `"unknown"` is an unresolved method. An entire
`checks = "unknown"` record at/after finishing likewise remains unknown. A missing
named gauge's missing-item error belongs to `tool_resolves`; inspection reports
its capability as unknown.

Loading rejects any `checks.<requirement>` absent from that operation's feature
exported `requirements` list, including when the list is wholly unknown. A name
exported on another feature does not establish ownership. An `inspect` op naming
a feature list may check a requirement any named feature exports; it is the
check op for each named feature that exports it, so one reading of a limit the
drawing gives two features covers both `feature:requirement` subjects. Such an op
may instead scope `checks`, `go_no_go` and `inspection_methods` entries to one
listed feature (`checks = { pivot_bore = { dia = "pin-gauges" }, hub_od = { dia =
"micrometers/0-1in" } }`, [plan](plan.md#operation)): each feature is then judged
with its own scoped gauge, pair and method, else the flat one, and a feature the op
gives no gauge for that requirement is not checked there. To retain
an authored inspection for a requirement absent from the export, declare a separate inspect
operation with `missing_requirements = { length = "calipers" }` and its
`inspection_methods.length` procedure. A name already exported on the selected
feature is rejected in `missing_requirements`; actual requirements must use checks.
Each explicit missing declaration emits `feature:requirement` with unknown
status, `missing_requirement = true`, `limits = "unknown"`, named gauge, operation
and inspection method evidence. This remains unknown even if the feature's
applicability or requirement list is unknown; it does not infer an acceptance
band from a nominal/reference dimension. A known empty/no-tolerance list with
such a declaration has the named unknown row, not a bare not-applicable finding.
The sheet renders a normal `?` check row naming the exact absent requirement and
preserves the authored procedure.
Place that unresolved check at its authored process point. The shaft's S3:15
check is after cutting the scribe-to-face target but before S3:20 doming:
measure the cut face while recutting is still possible, then follow the
existing forward instruction to verify the cylinder end after doming.

Gauge kinds must suit the requirement. Roughness needs a roughness gauge,
comparator or profilometer; position/coaxiality/angularity needs CMM, indicator or height
gauge. Both scalar and banded geometric requirements additionally need a known,
nonempty declared datum inspection method; bands also use range/resolution checks.
Complex shape controls need CMM/profile/radius/angle gauges. Other dimensions use the capable dimensional
gauge kinds. An external micrometer does not measure a hole bore (`dia` or `nominal_dia`). Type
incompatibility is an error even if catalog dimensions are unverified.

For a `[low, high]` mm band, gauge range must cover both ends and resolution must
not exceed `high-low`. The exception is a one-sided radius limit: a `radius` or
`bottom_radius` band `[0, r]` can only mean "R r MAX, sharp allowed", so no new field
marks it. A `radius_gauge` or `profile_gauge` reads it as a **limit check**, go/no-go
with its leaf at r: the leaf seats without rocking on a corner at or under r, and a
sharp corner needs no leaf. A leaf marked L whose maker tolerance is ±t
(`leaf_tolerance_mm`, [inventory](inventory.md)) may really be L + t and accept a
corner past the limit, so the leaf read must be at or under r − t. Outcomes:

- **Error, no leaf:** `range_mm` does not hold r (`range_mm[0] ≤ r ≤ range_mm[1]`
  fails), whatever the tolerance.
- **Error, tolerance crosses the limit:** no leaf lies at or under r − t. With
  t = 0.01, a leaf set R0.2–R1.0 has no leaf at or under R0.19, so the check is not a
  clean pass.
- **Error, resolution:** the gauge's resolution exceeds r, whatever the tolerance.
- **Unknown, tolerance:** the declared tolerance is unknown or not trusted. The
  tolerance is listed as debt.
- **Unknown, leaf not named:** t > 0 and a safe leaf exists. Only a leaf at or under
  r − t reads the limit, and the traveler prints the band and the gauge, never which
  leaf to use, so the operator would reach for the one at the limit. The evidence
  gives `leaf_max_mm` (r − t).
- **Unknown, no leaf at the limit:** t = 0, but the set brackets r without a leaf
  of r. For example, leaves from R0.15 by 0.1 have no R0.2 leaf. The smaller safe
  leaf is unnamed on the traveler; `leaf_max_mm` gives it.

- **Pass:** t = 0 (the tolerance is omitted or declared as 0), resolution ≤ r, and the
  set has a leaf of r. A leaf set R0.2–R1.0 by 0.1 with no declared tolerance reads
  `R0.2 MAX`.

The leaves are the gauge's declared `sizes_mm`; a declared empty list means none, so
no leaf reads the limit (error). Without `sizes_mm`, the leaves are the steps of
`resolution_mm` (the leaf pitch) up from `range_mm[0]`. A pitch that is not positive
leaves the check unknown (`gauge range or resolution unresolved`). `leaf_max_mm` is
always one of those leaves: the largest at or under r − t. A `sizes_mm` that is
unknown, wholly or in part, shows neither a leaf nor its absence, so the check is
unknown (`gauge leaf sizes unresolved`, or the gauge's own verification debt).

r is the MAX the traveler prints, the band rounded inward to the drawing's precision:
`[0, 0.24]` at precision 1 prints `0.0–0.2`, so the leaf read is R0.2, never R0.24.
When printing moves it, the evidence keeps the drawn limit as `drawing_limit_mm`.

Evidence adds `limit_check = "max"`, `limit_mm` (r) and, when declared,
`leaf_tolerance_mm`, instead of `band_mm`. An unverified gauge stays debt. A two-sided band (R5 ±0.1) and any reading gauge (a CMM) keep the full-span
rule. The mirror "R MIN" band `[r, inf]` cannot be written, since inputs refuse
`inf`, so no min-only case exists. A scalar geometric tolerance needs resolution
at most the tolerance and a known declared method. Non-mm/unknown limits stay unknown.
An angle band (`*_deg`, degrees) never meets a gauge's millimetre range and
resolution, and no gauge declares an angular capability: it is `unknown` (`no
angular gauge capability`) unless it is read across a face. A drawn band whose
feature declares the face extent l in `tilt_across`
([features](features.md#angle-bands-read-across-a-face)) is the deviation read end
to end across l about its mid angle m: a linear zone w = l·(sin(hi − m) − sin(lo −
m)), judged like every zone on resolution alone (`gauge resolves the tilt's linear
zone across its face`, else `gauge resolution exceeds the requirement band`). The
gauge's range is not compared, since an end-to-end deviation reading has no size to
span. Evidence keeps the degree `limits` and adds `tilt_across_length` (l) and
`band_mm` (w). A process hold on that angle is read the same way, about the drawn
band's m. A BASIC angle a surface profile bounds by `tilt_across` is read likewise
([Surface profiles](#surface-profiles)). An unknown length leaves
`tilt_across_length = "unknown"` with `tilt_across_reason`, and no angular gauge
capability.
Unverified gauge range/resolution cannot prove a dimensional error or pass.
Roughness capability is unresolved without explicit range evidence. A gauge of a
roughness kind (e.g. `roughness_comparator`) declares it with the inventory field
`ra_range = [low_um, high_um]`; the Ra limit must lie inside that range. Without
`ra_range` (or with an unverified item) finish_ra stays unknown. Scalar dimensions
without an implemented capability branch stay unknown.

A numeric requirement band must contain any explicitly exported numeric
`<requirement>_nominal` or `nominal_<requirement>`, inclusively. A contradiction is
an exporter-fact error regardless of gauge verification or unknown inspection
applicability. The error records the exact nominal field/value and exported
limits; no absolute-value/sign correction or nominal/reference inference is made.
An in-band, unknown or absent nominal leaves normal inspection evidence unchanged.
This contract assumes those nominal fields are **acceptance-band targets**,
not a fit system's reference basic size. A g6/p6-type fit band can legitimately
exclude its basic size; the checker does not interpret fit-class offsets and
such a basic size must not be exported as an in-band target under these names.
Reference geometry is not acceptance evidence. Supporting displaced fit-class
basic sizes needs separately identified semantics, not a sign change or a
nominal-band exception guessed from the numbers.

Sentence templates:

- `{feature}: no tolerance requirement to inspect.`
- `{feature}: inspection applicability or finishing action is explicitly unknown.`
- `{feature}: requirement identity is explicitly unknown.`
- `{feature} {requirement}: requirement is absent from the exported manifest; acceptance limits are unresolved.`
- `{feature} {requirement}: {message}.`, where message is exactly one of:
  - `explicit inspection method is unknown`
  - `inspection checks are explicitly unknown`
  - `gauge identity or capability is explicitly unknown`
  - `no requirement-keyed inspection check`
  - `named gauge is not listed; capability unresolved`
  - `named gauge cannot measure this requirement`
  - `requirement limits or units are unresolved`
  - `roughness gauge spans requirement`
  - `roughness requirement outside gauge range`
  - `roughness gauge capability unresolved`
  - `gauge does not span the requirement band`
  - `gauge resolution exceeds the requirement band`
  - `gauge spans the band at sufficient resolution`
  - `gauge range or resolution unresolved`
  - `limit check: gauge has no leaf at the MAX limit`
  - `limit check: the leaf's ±{t} tolerance crosses the MAX limit (no leaf at or under the limit less its tolerance)`
  - `limit check: gauge leaf tolerance unresolved`
  - `limit check: gauge leaf sizes unresolved`
  - `limit check: gauge resolution exceeds the MAX limit`
  - `limit check: only a leaf at or under R{r − t} reads the limit, and the traveler does not name it`
  - `limit check: the gauge has no R{r} leaf, and the traveler does not name the smaller one that reads the limit`
  - `limit check: the gauge's leaf at the MAX limit reads go/no-go (not a reading across the band)`
  - `gauge resolution and declared geometric inspection method cover requirement`
  - `geometric gauge capability or datum inspection method unresolved`
  - `no angular gauge capability`
  - `gauge resolves the tilt's linear zone across its face`
  - `gauge resolution unresolved`
  - `inspection capability for requirement unresolved`
  - `named gauge capability needs verification`
  - `unverified gauge dimensions cannot establish capability`
  - `exported nominal is outside the requirement band`
  - `a GO / NO-GO pair is read only for a diameter`
  - `GO / NO-GO direction is unresolved for a {kind} feature`
  - `named gauge cannot make a GO / NO-GO check of this feature`
  - `GO / NO-GO sizes accept work outside the band`
  - `GO / NO-GO sizes accept no work`
  - `the gauge lists no sizes_mm to hold the GO / NO-GO sizes`
  - `the gauge has no GO / NO-GO size of that diameter`
  - `GO / NO-GO sizes lie inside the band`
  - `{setup}:{op}: <one of the GO / NO-GO messages>` when an earlier op's pair is worse
    than the final check's

Evidence: requirement, limits, finishing/check op, named gauge, kind, range,
resolution and band width where available. Citations: PLAN §4.1 inspection,
feature requirement manifest and inventory range/resolution/verification. A pin
size check is not a position check; a declared gauge is not first-article data.

One full-width freeform readings/observations area stays below each real
requirement with its known owner(s), usable authored limits, gauge, units and
method reference. Equal printed bands alone do not establish shared physical
identity; a true across-faces dimension stays one record. Feature/location can
be identified when needed, without inferred counts, positions or statistics.
Unknown identities, bands and capability debts remain `?`; the layout invents
neither a result nor a gauge. Named authored procedure fields remain distinct
from freeform areas. An operation-performed mark is progress only,
separate from inspection acceptance, GO / NO-GO outcomes and clearance to proceed.
Authored inspection views stay in order as complete titled figures attached once
to the original requirement's note or worksheet. Continuations retain applicable
context without duplicating figures or reading/result fields. Moving a figure
whole changes no inspection method, evidence, unknown or acceptance decision.

## GO / NO-GO limit checks

An op's `go_no_go = { <requirement> = { go = <mm>, no_go = <mm> } }` states the two
sizes its `checks[<requirement>]` gauge uses; every key needs its `checks` entry
(otherwise bad input). On a multi-feature inspect op a pair may be scoped,
`go_no_go = { <feature> = { <requirement> = { go, no_go } } }`: it gauges that feature
alone, with that feature's `checks` gauge, and the other features keep theirs. A pair is a limit check: the GO size must pass the work and
the NO-GO size must not, so the gauge accepts the sizes between them. For a hole
(`hole`, `counterbore`, `thread`, `threaded_hole`) the gauge must be a pin, pin set or plug and
GO >= low limit, NO-GO <= high limit, GO < NO-GO. A boss or shaft is the mirror: a
ring or snap gauge with NO-GO >= low limit, GO <= high limit, NO-GO < GO. Any
other feature kind is `unknown`. A drawing check is judged against the band **as
the traveler prints it**, rounded inward at the drawing precision (the rocker rod
hole `[1.994, 2.094]` at 2 places prints, and is gauged as, 2.00–2.09). A pair
outside the band is `error`: it accepts work the band rejects. Both sizes must be
listed in the gauge's `sizes_mm`: a size not in the list is `error`, a gauge with
no `sizes_mm` is `unknown`, and an unverified gauge is `unknown`. A declared pair
replaces the span/resolution test for that check. The final check's pair grades
`{feature}:{requirement}`; a pair on any earlier op that prints the same drawing
band is graded the same way, recorded under `other_go_no_go`, and the worse status
wins. Evidence adds `go_mm`, `no_go_mm`, `accept_band` and, when missing,
`absent_sizes_mm`. The op row prints `<band>: <gauge>, GO <go> enters, NO-GO <no_go>
does not` (`passes over` for a boss or shaft), at the gauge's digits. A pair declared
`"unknown"` — the op's whole `go_no_go = "unknown"` (every requirement it checks) or one
entry `go_no_go = { <requirement> = "unknown" }` — is still a limit check, on the final
or an earlier op: `unknown` (`the GO / NO-GO pair is explicitly unknown`), never the
span/resolution test. Its row is flagged `?` and prints `GO / NO-GO sizes not set`.

## Process holds

An op's `process_holds` adds one `{setup}:{op}` inspection subject. Each hold's
`band` must lie inside its drawing requirement band, limits included. Only a
scalar zone or maximum (`position_dia`, `coaxiality_dia`, `angularity_dia`,
`surface_profile`, `finish_ra`) `v` reads as [0, v]; a BASIC scalar a surface
profile governs reads as its derived band ([Surface profiles](#surface-profiles));
any other scalar is a nominal with no band, so
the hold is `unknown`. Each hold's gauge is graded like a drawing check, against
the hold band: it must be able to measure the requirement, span the band and
resolve its width. A hold's own `go_no_go = { go, no_go }` makes that a limit
check against the hold band, by the rules above. A hold reaching outside the drawing band is `error`
(`process hold band outside the drawing band (…)`), and so is a gauge that cannot
read it (`process hold gauge cannot hold the band (…)`). An unresolved drawing
band, or an unknown, unlisted or unverified gauge, is `unknown`. Otherwise it is
`pass`. A hold on a reference-only dimension (`length_ref`, with its `measure` and
`cite`, see [plan](plan.md)) has no drawing band: `inside_drawing_band` is
`not_applicable`, never `unknown`, and its gauge is graded against the hold band
for the dimension it refers to (`length_ref` as a `length`). A `dro_scale` gauge (a
machine axis read-out) reads only a length along its axis (`length`, `depth`,
`height`, `thickness`, `station`); naming it for a diameter or a form is `error`.
Evidence: each hold's band, drawing band, gauge, reason, `measure` and `cite` when
given, `inside_drawing_band`, `gauge_status` and `gauge_message`. The sheet prints it as
`PROCESS HOLD — not a drawing limit (why: see job page): <feature> <requirement>
<band>: <gauge>`, followed by its GO / NO-GO pair when declared; the reason prints
once, on the job page. A reference-only hold prints
its `measure` for the requirement and adds `(drawing: <dimension> REF <value>, no
limit)`. The band prints with the
most decimals among its own limits, the drawing precision (none for a REF span) and
one gauge step in mm: a 0.001 mm or a 0.0001 in
(0.00254 mm) gauge reads 3 places, not the five of the inch conversion. The job page
gathers every hold in **PROCESS HOLDS — in-process limits, not drawing limits**:
setup / op, hold, gauge, the drawing's own limit and why.

## `finish_route`

One row per part. A coating applies the drawing `material.finish` to the cuts it
follows, in plan order, on stock that carries them: in the same setup after the
cut, or in a setup whose `stock_in` lineage contains the cut's setup. Every cut
needs such a coating. So on a built-up part, each component is covered either
by its own coating after its last cut, or by one coating of the joined assembly
after the last cut on it. No coating at all, or a cut no coating covers (it
removes the finish, or its component is never coated), is `warn` (a job-page
caution). `uncoated_cuts` names those cuts. A cut covered only by a coating
whose lineage has undeclared routing (a setup omitting `stock_in`), or an
uncovered op of explicitly unknown action, is `unknown` (`unresolved_cuts`).
Otherwise it is `pass`. An explicitly unknown finish is `unknown`; no declared
finish is `not_applicable`. Whether each coating op's `process` resolves to an
outside `services` item or in-house `consumables` is checked per op by
`tool_resolves`: absent is `unknown`, unlisted is `error`, and a consumables
entry whose product list is unknown, empty, or has a blank or `"unknown"`
product is `unknown`.

## Angularity

Declare the drawing's angularity control as `angularity_dia`, with its explicit
`angularity_datums` list and drawing source citation. The cone's `[0.0, 0.10]` mm
band is a geometric requirement, not a caliper size check. It needs a
requirement-keyed `checks.angularity_dia` gauge and an explicit datum-referenced
`inspection_methods.angularity_dia` narrative. The narrative is the authored
inspection declaration; the rule does not infer a method from the gauge or parse
datum letters out of prose. Missing checks are errors. Caliper-only certification
is an error even with a declared narrative. Missing, empty or literal `"unknown"`
methods, a step list with any empty or `"unknown"` step, unknown limits, and
missing/empty/unknown datum evidence stay unresolved.
A capable geometric gauge, known datum list and method, adequate range and
resolution are all required to pass a band.

`datum_consistency` follows each `angularity_datums` relationship to the finished
datum cut. For a numeric band it compares `high-low`, not the upper endpoint, to
`refixture_budget_mm`; a scalar angularity tolerance uses its scalar value.
Separate setups without a valid indicated pickup fail when this tolerance is
below the measured budget, and pass at equality. Each datum must independently
share the setup, have a valid transfer from after its finishing cut, or fit the
budget. Unknown referenced geometry or an unknown cross-setup tolerance/budget
remains unresolved. Position and coaxiality keep their existing datum-budget
semantics.

## Surface profiles

A drawing SURFACE PROFILE ([features](features.md#surface-profiles),
harmonic-analyzer #1544) is two things to this rule. The zone itself,
`feature:surface_profile`, is a geometric zone [0, t] inspected like
`position_dia`: it needs a requirement-keyed `checks.surface_profile` gauge of a
geometric kind (`cmm`, `dial_indicator`, `dial_test_indicator`, `height_gauge`),
a declared `inspection_methods.surface_profile` procedure, and a gauge resolution
no coarser than t; a missing check is an error, a missing or `"unknown"` method
unknown, a caliper an error. It passes only in a declared frame: an omitted or
`"unknown"` `surface_profile_datums`, or one with a datum that resolves to no
manifest feature through the `datums` table or a feature's `datum`, leaves it
unknown even with a capable gauge and method; an explicit `[]` (form only) or a
resolved datum list may pass. Evidence adds `surface_profile_datums`. A feature
declaring a zone must list `surface_profile` in its requirements (bad input
otherwise), so a zone never goes uninspected. Each BASIC scalar it governs
(`surface_profile_governs`) is read against the band the zone derives for it
instead of its bare BASIC value: `limits` is that band and the gauge must span
it and resolve its width, as for any drawn band, and evidence adds
`profile_band` (the governing profiles, or why the band is unknown). The band is
pointwise from the DRF-located BASIC origin, not a fitted size. An unresolved
derivation (unknown t, U, DRF or entry, an unresolved DRF datum, an empty DRF, a tilt the zone cannot
bound) leaves `limits = "unknown"` and the finding unknown. A process hold on a
governed requirement must lie inside the same derived band.

A BASIC angle a profile governs by `tilt_across` derives a band in degrees, n ±
asin(t / l), which is the zone read end to end across the face extent l. It is read
as the linear zone a drawn angle band read across a face is, about n: w = l·(sin(hi −
n) − sin(lo − n)), the exact inverse (2t for one zone t), judged on resolution
alone. A process hold on such an angle is read about the same n and l. When the
governing profiles tilt it across different lengths no single reading reads them
all: `tilt_across_length = "unknown"` with `tilt_across_reason`, and the band has
`no angular gauge capability`.

`datum_consistency` relates each `surface_profile_datums` datum at the zone t,
the same tolerance convention as a scalar angularity zone, converted to mm
(`units = "in"`: × 25.4) before it meets `refixture_budget_mm`; a profile with no
datums (form only) relates none, and an omitted list with a zone is unresolved.
A `height_from` on a feature whose BASIC height a profile governs takes the
derived band's width, likewise in mm.
