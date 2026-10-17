# Tools and sizing rules

Findings use `pass`, `error`, `warn`, `info`, `unknown`, `unsupported`, or
`not_applicable`. The report preserves exact numbers and citations; the sheet
uses drawing precision and plain sentences, not rule ids. Placeholders below
stand for the current subject/values; semicolon-joined clauses preserve every
observed violation. Unknown or unverified geometry cannot establish a fit.

## `tool_resolves`

Subjects: every selected inventory reference plus each nonmanual cutting
assembly `setup:op`. References include machine, tool, holder, gauges (with a hold's
`align.indicator`), fixture, parallels and supports, including declared member
references. Missing named
items are errors; unknown categories or unverified identities are unknown.
Compatibility compares spindle taper or lathe toolpost series to holder
interface; a lathe's spindle-axis action (`spot`, `drill`, `ream`, `tap`,
`center`, `center_drill`) rides in the tailstock quill, so its holder must fit
the tailstock `taper` instead. Then shank against collet capacity, maximum shank or a capacity
range. Shank lengths compare in mm with an absolute 1e-6 mm tolerance and no
relative tolerance: the maximum and both range ends count as a fit, so `3/8` in
and `9.525` mm agree; a single nominal capacity also accepts the ISO 286 h6
band below it (below). Unverified assemblies clear dimensional
mismatch conclusions and stay unknown. A missing item's error is owned by its
reference finding; its assembly finding stays unknown.
An explicitly unknown operation action also makes its assembly fit unknown.
A selected tool whose identity row also claims its `dia` through a
`measured` record with `status` `assumed`, `illustrative` or omitted is
unknown, naming that record: the identity is not read past an unmeasured
diameter claim. A bare nominal catalogue `dia` or a pure identity row is
unchanged.

An inventory item named in prose as `<category>.<key>[/<member>]` (a plan note
or cite, a make note, record check or `how`, or make operation `hold` or `cite`
of a shop-made item a setup uses, and each record's `gauge` as
`gauges.<gauge>`; docs/inventory.md; in a make operation's `hold` or `cite`,
anywhere outside a link or path, never inside one) is a subject
of its own, `<category>.<key>`, with `named_in` listing where. It passes when
the item is listed and verified; missing or unverified, it is unknown (never a
pass, and never printed as the bare key: the traveler prints `? <key>`). A
whole set is named by its key; a member must resolve as a member, read whole
(`tools.drills/#61` is unknown on a `#1-60` index, never the index itself).

Each make operation (`make_ops`, docs/inventory.md) of a shop-made item a
setup holds with is a subject of its own, `<category>.<key> make op <n>`
numbered in print order. Its `tool` is a `tools` key, read in the tools only
(a same-key item of another category or a machine's standard accessory never
stands in): a key the tools do not list is an error. It passes when the tool
is listed and verified and the hold, speed, feed, depth of cut and source are
known; an unknown fact, an unknown tool or tools list, or a tool still to
verify (flagged, or its verification or presence unknown) is unknown, never a
pass, and its printed line stops on the same fact.

Saw cut-off resolves the selected bandsaw blade and a `mill` / `bench` /
`bandsaw` machine, or a `hand_saw` and a `bench` / `manual` machine, instead of
a spindle/holder/shank assembly; a hand saw on any other machine, or a bandsaw
blade on a `manual` one, is an error. No holder is
required; incompatible known machine/tool kinds are errors and unverified
identities remain debt. A saw naming a groove cannot replace that groove's
size-setting tool, and a saw does not establish a finished datum.

A tool shank in a holder with one nominal capacity (`capacity_mm` /
`capacity_in` as a single collet size, not a `[low, high]` range or a
`max_shank`) fits when it is inside the ISO 286 h6
shaft band for that nominal size: `capacity - IT6 <= shank <= capacity`, upper
deviation 0, both limits inclusive at the 1 nm length tolerance. IT6 is read
from ISO 286-1:2010 Table 1 by nominal size (9 µm above 6 up to and including
10 mm, so a 3/8 in collet accepts 9.516-9.525 mm). An oversize shank, or one
below the band, is `tool shank does not match selected collet`. A nominal
size above 500 mm, past the table, leaves an undersize shank unknown, never a
pass. Only h6 is applied; no collet or policy entry changes the class.

Sentence templates:

- `{ref}: not listed in the inventory.`
- `{ref}: listed; presence or catalogue identity needs verification.`
- `{ref}: listed inventory identity resolves.`
- `{category.key}: named in {places}; not listed in the inventory: list it or name a listed item.`
- `{category.key}: named in {places}; listed; presence or catalogue identity needs verification.`
- `{category.key}: named in {places}; listed inventory identity resolves.`
- `{category.key} make op {n}: tool {key} is not in the shop's tools.`
- `{category.key} make op {n}: {facts} not known.`
- `{category.key} make op {n}: its tool resolves and its cutting data is stated.`
- `{setup:op}: holder interface and shank fit.`
- `{setup:op}: assembly fit needs measured shank, holder and machine facts.`
- `{setup:op}: ISO 286-1 Table 1 gives no IT6 above 500 mm, so a shank under
  the nominal collet size has no known fit.` (after the sentence above, joined
  with `; `, when both apply)
- `{setup:op}: {violations}.` Violations are `holder interface does not match
  machine`, `tool shank does not match selected collet`, `tool shank exceeds
  holder capacity`, or `tool shank outside holder range`, joined with `; `.

Evidence: `reference`, `present`, `verified`, kind and available diameter;
assembly selected refs, interface names, shank and holder capacity in mm. A
shank off the nominal capacity also reports `shank_fit = "ISO 286 h6"` and
`shank_band_mm = [low, capacity]` (the low limit rounded to the nanometre;
`"unknown"` above 500 mm); a shank at nominal reports neither.
Citations identify inventory selected identity/member coverage and PLAN §3.3,
or spindle/holder/shank fields and PLAN §4.1, plus `ISO 286-1:2010 Table 1 IT6`
when the band is read. Resolver conversions use exactly
25.4 mm/in with declared units; no network catalog lookup occurs.

## `sizing`

Subject: every manifest feature. Hole/counterbore selected finishing tool is
counterbore, ream when route/process requests reaming, otherwise drill. Only a
verified selected diameter can pass the inclusive drawing band. The rule does
not substitute an unselected nearest candidate. Threaded/path-set features are
not applicable. Drawing units other than mm remain unresolved rather than
implicitly converting their tolerance limits.
An explicitly unknown feature kind or route action is unknown, not not-applicable.

Grooves compare selected nose radius to the feature's own
`corner_radius_max_design` (the same allowance `internal_corner_radius` admits at
CAD-sharp corners; equality passes: 0.25 admits a 0.25 mm nose, 0.26 errors), and
radial reach to `(stock.dia_mm - groove low diameter)/2`. A missing allowance
stays unknown; `edge_break` is never borrowed. These are explicit design
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
