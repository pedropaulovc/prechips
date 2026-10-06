# Declared lathe profile and workholding rules

These M2 rules use the same `Finding`/`Bundle` contract as M1. Each emits one
subject per setup. They check declared geometry and inventory identities; the
profile rules also read the kernel's measured faces of revolution when a
successful kernel result is already present (they never start one). They do
not certify installed workholding, cutter clearance, whip or chatter. Missing
measurements and `verify` debt are not inferred away. There are no default shop
ratios or catalogue capacity lookups.

## `turned_profile`

The rule applies to lathe setups with axial turning/forming/grooving actions.
A known nonlathe setup or a lathe setup without those actions is
`not_applicable`; an unknown machine/action is `unknown`.

The spindle convention is PLAN §8 M2: setup Z runs along the spindle, positive
toward the exposed end, and X is a diameter. Every axial cylinder, boss, shaft
(a cylinder), groove or dome is transformed from its feature frame into the setup frame
using M1's `model_point`/`frame_point` functions. A rechuck with reversed spindle
Z therefore reverses the station order. Model +Z is never substituted for
setup +Z. Source and setup Z axes must describe the same spindle line direction
(up to reversal); a skewed axis is not treated as an axial turned profile.

Recoverable constant-diameter geometry requires:

- an explicit `dia_nominal`, otherwise `nominal_dia`, otherwise scalar `dia`;
- two known `z_mm` endpoints and known frame transforms;
- explicit manifest units, `mm` or `in` (inch identity is 25.4 mm/in);
- an axial feature direction, when `axis` is authored;
- a bound/nominal frame, rather than `binding = "unknown"`.

An explicitly unknown nominal is not replaced by another field. A diameter
band is a tolerance, not a nominal; its midpoint is never manufactured. Unknown
stations, overlapping inconsistent cylinders, gaps and selected forms without
a recoverable axial interval remain `unknown`, not a vacuous monotonicity pass.

Declared values are authoritative; the kernel fills only what a feature does
not declare (a consumer export need not author `z_mm`). For every setup with a
turning-model operation the kernel reports, per declared feature, its finished
faces of revolution about setup Z through x = y = 0 as
`setups.<id>.revolved.<feature> = { z_mm = [lo, hi], radii_mm = [r_min, r_max],
end_radii_mm = [r at lo, r at hi], kinds = [...] }` in setup-frame mm; a
feature with unmapped references or any face that is not an external surface of
revolution (a flat, a bore) is omitted with its reason under
`revolved_reasons`. When none of its faces is revolved about setup Z and one is
a cylinder, cone, torus or surface of revolution about a direction not parallel
to setup Z (a cross boss, or a component turned on another axis), the kernel
also reports `revolved_off_axis.<feature> = { axis = [x, y, z] }`. Such a
feature without resolving declared stations and not claimed by this setup's
profile operations is not on this spindle's profile: it is listed under
`off_axis` instead of `unresolved`, and any exposed span only it would cover
stays uncovered, never passed. Claimed by this setup, it remains unresolved.
Without declared `z_mm` the span is the kernel's `z_mm`;
declared stations that do not resolve along setup Z (skewed axis, unknown
binding) are never replaced. Without a nominal diameter a cylinder, boss or
shaft takes `2 * r_max` only when its faces have one radius, and a groove takes
its floor, `2 * r_min`. A dome is modelled at its widest (base) diameter over
its axial span: `2 * base_radius`, else `2 * sqrt(h (2R - h))` from its
declared `sphere_radius` and nominal height (2R once h exceeds R), else the
kernel's `2 * r_max`. Only a dome narrowing away from the chuck (the kernel's
smaller end radius at +Z) is bounded by its base; one whose apex faces the
chuck, or whose direction is unmeasured, stays `unknown`. Diameters equal
within the 1 nm length identity are one diameter, so float residue is never a
shoulder. `unresolved_reasons` names each unknown feature's debt (declared
field and kernel reason). `turned_profile.feature_span(bundle, setup, name)`
returns the same per-feature result (`z_mm`, `diameter_mm`, `base_diameter_mm`,
`height_mm` for a dome or a face's axial extent, `source`, `sources`,
`unresolved`, `cite`) for other rules.

When both setup stock end stations and stick-out are known, the declared
exposed span is `max(north_end_z, south_end_z) - stickout_mm` through
`max(north_end_z, south_end_z)`. Known intervals wholly behind the chuck are
excluded; no chuck location is guessed when these inputs are absent. A whole
declared profile that is monotone can still pass, but a potential increase
without a known exposed span remains `unknown`, not an assumed exposed error.
Declared grooves overlay their parent cylindrical envelope while preserving
that envelope for the shoulder-monotonicity check. The adjacent intervals are
ordered toward +setup Z. Equal or decreasing diameter passes. A groove can
waive its recovery only back to the parent envelope, not an independently
larger outward shoulder. Recovery needs a matching declared grooving operation
on the targeted feature; a groove elsewhere cannot waive it. Matching
operations may come from the current setup or an already preceding setup in
the same plan route: a received groove does not require repeated grooving.
Future setups cannot supply the exception, while the current setup's planned
grooving actions can. Operation evidence retains the originating setup ID.

Actual grooving actions are `groove`, `rough_groove`, `finish_groove` and
`form_relief`. A turning action is not a grooving operation. An explicitly
unknown targeted action leaves the exception unresolved. PLAN §4.1 makes this
an operation/feature check, not a tool-capability certification: selected tool
identity and inventory verification remain the M1 `tool_resolves` rule's
responsibility.

Evidence includes transformed intervals (each with its `source`), the swept
constant-diameter segments, increase stations, matching grooving operations,
unresolved geometry and its reasons.
Citations identify PLAN §4.1 turned profile (line 540), the §8 spindle
convention, the authored feature dimensions/frames, the kernel's revolved facts
when used, and plan grooving operations.
This is not a cutter-envelope or complete feature-coverage proof.

## `stickout`

For a lathe setup without a selected verified tailstock/steady exception:

`hold.stickout_mm <= policy.numbers.stickout_ld_max * D`.

Equality passes. The ratio is read only from the policy, accompanied by
`numbers_cite.stickout_ld_max`; a missing, unknown, nonpositive, uncited or
unverified ratio leaves the limit `unknown`. The source is
[PLAN §4.1 stick-out](../PLAN.md#41-plan-lint-declared-inputs-only) (line 541),
whose example is “Ø6 × 40 past the chuck: add the tailstock centre.” This is
not an unstated Handbook rule.

**D is the smallest finished diameter in the unsupported exposed length, not
the bar diameter held in the jaws.** It is the minimum of the finished profile
segments along setup Z (declared, kernel-filled as described above), using
`turned_profile`'s frame transforms, explicit `mm`/`in` units and groove
overlays. The exposed span uses the authored
stock end stations and stick-out described above. A smaller diameter wholly
outside that span cannot control D; even an unknown diameter can be excluded
when its transformed stations prove it hidden. Unknown diameter in an exposed
segment, unknown location/transform, inconsistent overlapping geometry, or a
gap anywhere in the exposed span leaves D and the unsupported limit `unknown`.
Exposed stock beyond every finished feature (a raw collar between the jaw mouth
and the first finished feature, a supply end or a stub not yet cut off) takes
its diameter from the kernel's `setups.<id>.stock_profile`: rows
`[z_lo, z_hi, r_lo, r_hi]` in setup-frame mm. The kernel sections the entering
stock and the stock after every op that removes material; wherever any of these
states has material, `r_lo` is the least of their lower bounds on the outer
radius over the band. A stub turned and then faced off therefore counts at its
turned diameter, an end sawn off at its diameter before the cut. An op is one
step: a parting groove part-way through its own cut is not a state. The kernel
emits the profile only when every state's sections at six meridians agree (a
solid of revolution about setup Z), else `stock_profile_reason`. Each such span
must be covered end to end; its pieces join the exposed segments with
`source = "kernel_stock"` (`stock_segments`) and can set D
(`diameter_features` names `kernel stock`). A span the profile does not cover,
or any span without a kernel run, stays in `uncovered_z_mm` with
`stock_reason`, and D stays `unknown`: the stock state's `od_mm` cannot show
that no op reduced that span. `turned_profile` ignores stock segments.
There is no held-bar fallback for missing finished geometry. With an authored,
verified ratio of 4, Ø20 held with Ø6 finished over a 40 mm overhang therefore
has a 24 mm limit and is an `error` without the support exception.

Held OD remains a separate declared-input check: `setup.stock_state.od_mm` when
authored, otherwise `plan.stock.dia_mm`. Explicit unknown/nonpositive held OD,
an explicitly unknown stock state, or unverified fallback stock form remains
`unknown`; none is replaced with the original blank diameter. A verified
support does not resolve missing exposed geometry or this held-stock debt.
An explicit zero stick-out has no unsupported length to screen, but still needs
a verified cited ratio or the selected verified support exception.

The support exception requires an explicitly selected `hold.support` or
`hold.supports` reference. `supports` can contain strings or existing
`{ ref = ... }` records. A verified fixture of kind `tailstock`,
`tailstock_centre`, `tailstock_center` or `steady_rest` qualifies. Generic
live/dead centres need an explicit tailstock identity; a headstock centre does
not qualify. A named machine accessory must be listed in the **selected**
machine's `standard_accessories`/`included` and be verified. An accessory on
another machine and an unselected support merely present in inventory cannot
supply the exception. An explicit `present = false` fixture is not resurrected
by an accessory list.

Explicit `none`/`not_applicable` means no support exception. Missing or unknown
support declarations, unresolved identities and unverified supports stay
unresolved. A known length inside the unsupported limit can pass without
relying on unresolved support; an over-limit length cannot. A selected verified
support can establish the exception without inventing a missing policy ratio.
This does not calculate supported bending, certify installation or relax any
other rule.

Evidence records D, the feature(s) defining its minimum, transformed exposed
segments/span and unresolved geometry, as well as held OD and its input source,
declared stick-out, cited ratio, unsupported length limit and each selected
support's resolution status. Citations retain authored feature sources and
identify the feature dimensions/frames and authored setup stock end stations
and stick-out used to locate the exposed geometry.

## `stock_diameter`

Checks `hold.fixture` when it selects a collet/collet set, `collet_chuck`, or
chuck. It uses the held OD and fallback/unknown semantics described above, not
the finished exposed diameter D used by `stickout`.

Only actual declared gripping capacities are used:

- `sizes_mm` membership;
- flat or grouped `sizes_in` membership, explicitly converted by 25.4 mm/in;
- two-endpoint `range_mm` or `range_in`, with inclusive bounds.

A collet-set root can be checked against its declared members. A selected
member such as `set/<size>mm` or an M1 inch member is restricted to that member,
not all sizes of the parent set. Explicit `members` records use their own
sizes/ranges, not inherited parent-set coverage. Physical inch/mm identity
comparison reuses M1 `same_length`, so floating conversion residue is not a
spurious mismatch.

`diameter_in`, `dia`, swing, or a chuck's exterior size never supplies a gripping
range. A scalar range has no declared lower endpoint and stays unresolved;
missing capacity stays `unknown`, including a machine-accessory chuck without
its actual fixture/capacity record. A fully known verified set/range that excludes
the held stock produces `error`. Verified membership in a declared capacity
passes; unverified inventory cannot prove either fit or mismatch. Known
non-collet/chuck fixtures are `not_applicable`.

Evidence names the fixture, held diameter/source, normalized listed sizes,
normalized ranges and selected-member diameter when applicable. Citation:
PLAN §4.3 collet/chuck (line 558), the declared stock-state/stock diameter and
selected inventory capacity fields. This does not check jaws, clamping force,
runout or interference.

## Readiness and isolated proof cases

These families use existing `pass`, `error`, `unknown` and `not_applicable`
statuses; they introduce no alternative severity vocabulary. Errors take exit
2 ahead of unresolved required rows (exit 4); clean or optional unresolved
rows can exit 0. Input-schema errors remain exit 3 before any output, preserving
PLAN §4's precedence `3 > 2 > 4 > 0`.

`tests/test_lathe_m2.py` uses isolated authored bundles and covers diameter/order
boundaries, frame/rechuck transforms, targeted grooving exceptions, missing
geometry, selected fixture/accessory support, policy verification/citations,
held-OD precedence, actual collet/chuck capacities, canonical report repeatability
and exit precedence. The existing pivot shaft has no cross-hole: these checks
neither add one nor infer an indexing requirement.
