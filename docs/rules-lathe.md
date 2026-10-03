# Declared lathe profile and workholding rules

These M2 rules use the same `Finding`/`Bundle` contract as M1. Each emits one
subject per setup. They check declared geometry and inventory identities, not a
STEP solid, installed workholding, cutter clearance, whip or chatter. Missing
measurements and `verify` debt are not inferred away. There are no default shop
ratios or catalogue capacity lookups.

## `turned_profile`

The rule applies to lathe setups with axial turning/forming/grooving actions.
A known nonlathe setup or a lathe setup without those actions is
`not_applicable`; an unknown machine/action is `unknown`.

The spindle convention is PLAN §8 M2: setup Z runs along the spindle, positive
toward the exposed end, and X is a diameter. Every declared axial cylinder,
boss or groove is transformed from its feature frame into the setup frame
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

Evidence includes transformed intervals, the swept constant-diameter segments,
increase stations, matching grooving operations and unresolved geometry.
Citations identify PLAN §4.1 turned profile (line 540), the §8 spindle
convention, the authored feature dimensions/frames and plan grooving operations.
This is not a cutter-envelope or complete feature-coverage proof.

## `stickout`

For a lathe setup without a selected verified tailstock/steady exception:

`hold.stickout_mm <= policy.numbers.stickout_ld_max * held_diameter_mm`.

Equality passes. The ratio is read only from the policy, accompanied by
`numbers_cite.stickout_ld_max`; a missing, unknown, nonpositive, uncited or
unverified ratio leaves the limit `unknown`. The source is PLAN §4.1 stick-out
(line 541), not an unstated Handbook rule.

Held diameter is `setup.stock_state.od_mm` when authored, otherwise
`plan.stock.dia_mm`. Explicit unknown/nonpositive held OD, an explicitly unknown
stock state, or unverified fallback stock form remains `unknown`; none is
replaced with the original blank diameter. This makes a rechuck onto a finished
journal use that journal's OD instead of the starting bar.

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

Evidence records held diameter and its input source, declared stick-out, cited
ratio, unsupported length limit and each selected support's resolution status.

## `stock_diameter`

Checks `hold.fixture` when it selects a collet/collet set, `collet_chuck`, or
chuck. The held OD and fallback/unknown semantics are identical to `stickout`.

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
