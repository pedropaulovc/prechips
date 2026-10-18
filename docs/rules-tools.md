# Tools and sizing rules

Use `tool_resolves` to diagnose inventory identities and assembled tool fit, and
`sizing` to check the selected finishing tool against a feature's limits. A
resolved identity does not establish a dimensional fit.

Findings use `pass`, `error`, `warn`, `info`, `unknown`, `unsupported`, or
`not_applicable`. The report preserves exact numbers and citations; the setup
sheet uses drawing precision and plain sentences, without rule IDs. Unknown or
unverified geometry cannot establish a fit.

For input fields, see the [inventory reference](inventory.md) and
[feature reference](features.md). For help resolving a stopped plan, see
[troubleshooting](manual/troubleshooting.md). The
[report reference](report-and-telemetry.md) defines readiness and approval.

## `tool_resolves`

### Selected identities and assembled tools

Subjects include every selected inventory reference, each nonmanual cutting
assembly `setup:op`, and each `coating` operation. References include machine,
tool, holder, gauges (with a hold's `align.indicator`), fixture, parallels and
supports, including declared member references. Missing named
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

### References named in prose

Inventory names in prose are checked separately from selected tool assemblies.
An item written as `<category>.<key>[/<member>]` becomes its own subject,
`<category>.<key>`, with `named_in` listing its locations. Recognized locations
include plan notes and citations; a shop-made item's make notes, record checks
and `how`; and its make-operation `hold` and `cite` when a setup uses that item.
Record `gauge` values are read as `gauges.<gauge>`. In a make operation's `hold`
or `cite`, names count outside links and paths, never inside them. See the
[inventory reference](inventory.md) for these authoring fields.

A prose reference passes when the item is listed and verified. A missing or
unverified item is `unknown`, not an error or pass. The setup sheet prints
`? <key>` instead of presenting the bare key as resolved. A whole set is named
by its key; a member must resolve as a whole member
(`tools.drills/#61` is unknown on a `#1-60` index, never the index itself).

### Shop-made tooling and saws

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
blade on a `manual` one, is an error. A bandsaw blade that follows a scribed
line needs a `bandsaw` machine whose `saw_modes` include `"vertical"`: other
machine kinds or modes without it are errors, and undeclared modes stay debt. No holder is
required; incompatible known machine/tool kinds are errors and unverified
identities remain debt. A saw naming a groove cannot replace that groove's
size-setting tool, and a saw does not establish a finished datum.

A coating operation resolves its `process` to an outside `services` item or
in-house `consumables`. An unlisted process is an error. An unknown process or
unverified identity stays unknown; known listed processes pass. Coating sequence
and stock-lineage coverage are separate
[`finish_route`](rules-inspection.md#finish_route) checks.

### Nominal collet fit

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

### Finding messages and evidence

These representative templates use placeholders for the subject and current
values. They do not list every identity, saw-assembly or coating message.
Where several violations apply, the message joins them with semicolons.

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

To resolve an identity finding, list the intended item or select an existing
one, then verify its presence and catalogue identity. For assembly debt, supply
the measured shank and selected machine/holder facts. A known mismatch needs a
compatible selection; verifying the same incompatible dimensions does not fix it.

## `sizing`

### Finishing-tool selection and limits

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
checks; they do not prove [turned-profile feasibility](rules-lathe.md#turned_profile)
or swept geometry.

### Finding messages and evidence

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

To resolve sizing debt, identify the finishing operation and verify the selected
tool's controlling diameter or groove geometry. If that tool lies outside the
drawing band, select an appropriate tool or correct a demonstrated input error.
The rule does not choose a replacement or justify changing the drawing limit.
