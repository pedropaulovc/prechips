# Tools and sizing rules

Findings use `pass`, `error`, `warn`, `info`, `unknown`, `unsupported`, or
`not_applicable`. The report preserves exact numbers and citations; the sheet
uses drawing precision and plain sentences, not rule ids. Placeholders below
stand for the current subject/values; semicolon-joined clauses preserve every
observed violation. Unknown or unverified geometry cannot establish a fit.

## `tool_resolves`

Subjects: every selected inventory reference plus each nonmanual cutting
assembly `setup:op`. References include machine, tool, holder, gauges, fixture,
parallels and supports, including declared member references. Missing named
items are errors; unknown categories or unverified identities are unknown.
Compatibility compares spindle taper or lathe toolpost series to holder
interface, then shank against collet capacity, maximum shank or a capacity
range. Shank lengths compare in mm with an absolute 1e-6 mm tolerance and no
relative tolerance: equal capacity, the maximum and both range ends count as a
fit, so `3/8` in and `9.525` mm agree. Unverified assemblies clear dimensional
mismatch conclusions and stay unknown. A missing item's error is owned by its
reference finding; its assembly finding stays unknown.
An explicitly unknown operation action also makes its assembly fit unknown.

Sentence templates:

- `{ref}: not listed in the inventory.`
- `{ref}: listed; presence or catalogue identity needs verification.`
- `{ref}: listed inventory identity resolves.`
- `{setup:op}: holder interface and shank fit.`
- `{setup:op}: assembly fit needs measured shank, holder and machine facts.`
- `{setup:op}: {violations}.` Violations are `holder interface does not match
  machine`, `tool shank does not match selected collet`, `tool shank exceeds
  holder capacity`, or `tool shank outside holder range`, joined with `; `.

Evidence: `reference`, `present`, `verified`, kind and available diameter;
assembly selected refs, interface names, shank and holder capacity in mm.
Citations identify inventory selected identity/member coverage and PLAN §3.3,
or spindle/holder/shank fields and PLAN §4.1. Resolver conversions use exactly
25.4 mm/in with declared units; no network catalog lookup occurs.

## `sizing`

Subject: every manifest feature. Hole/counterbore selected finishing tool is
counterbore, ream when route/process requests reaming, otherwise drill. Only a
verified selected diameter can pass the inclusive drawing band. The rule does
not substitute an unselected nearest candidate. Threaded/path-set features are
not applicable. Drawing units other than mm remain unresolved rather than
implicitly converting their tolerance limits.
An explicitly unknown feature kind or route action is unknown, not not-applicable.

Grooves compare selected nose radius to `corner_radius_max_design`, and radial
reach to `(stock.dia_mm - groove low diameter)/2`. These are explicit design
checks, not M2 turned-profile machinability or swept geometry proof.

Sentence templates (each prefixed `{feature}: ` and ending `.`):

- `dimensions are set by the path or endpoint, not cutter diameter`
- `selected finishing tool or its measured size is unresolved`
- `feature/tool units do not match; no implicit drawing conversion`
- `finishing tool diameter is within limits`
- `finishing tool diameter is outside limits`
- `feature kind or finishing action is explicitly unknown`
- `tool nose radius and radial reach need verified geometry`
- `tool nose and reach cover the groove design`
- `tool nose or reach cannot cover the groove design`

Evidence: feature kind, route refs, selected tool, mm/in tool diameter, drawing
unit, low/high mm limits, `under_low_mm=max(0, low-tool)` and
`over_high_mm=max(0, tool-high)`. Groove records preserve low width, diameter,
nose/reach, design corner maximum and required radial reach. Citations combine
PLAN §4.1, manifest citations, explicit tool size/25.4 conversion, and the
stock-reference radial-reach equation. Nominal identity is labelled as such
when unverified; it is not silently promoted to measured size.
