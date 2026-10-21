# Tools and sizing rules

Use `tool_resolves` to diagnose inventory identities and assembled tool fit,
`sizing` to check a finishing tool against a feature's limits, and
`joint_thread` to identify contradictions and unresolved facts in a removable
threaded assembly. A resolved identity does not establish a dimensional fit.

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
assembly `setup:op`, each `die_thread` or `hand_tap` assembly, and each `coating`
operation. References include machine,
tool, holder, gauges (with a hold's `align.indicator`), fixture, parallels and
supports, including declared member references. Missing named items are errors
except for the manual-thread selection debt described below; unknown categories
or unverified identities are unknown.
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

### Manual die threading

Each `die_thread` operation has a `tool_resolves` assembly finding with subject
`setup:op`. It is a spindle-stopped hand action, not a powered axial cutter or
lathe toolpost stack. It requires no spindle speed recommendation, taper,
shank fit or axial tool-setting instructions. An authored numeric `rpm`
other than zero is nevertheless an error; omission or `"unknown"` does not
create a speed requirement.

The check consumes the selected die and die-stock identities, the
`external_thread` feature's `thread`, `thread_hand` and `thread_class`, and
the stock's `fits` reference. Select an actual `die_set` or `tap_die_set`
member, not a set root. An explicit tool record with free kind `die` is also
accepted; it is not a new inventory category or a required replacement for
the existing set-member form. The selected holder must resolve to
`die_stock`; a category-qualified reference may select it from `tools`.
The [inventory die reference](inventory.md#manual-dies-and-die-stocks)
defines the fields and member inheritance.

The assembly passes only when both identities resolve and are verified,
the feature is an external thread, the nominal designation agrees, hand
and class agree after trimming whitespace and ignoring case, and `fits`
names the exact selected die identity. Bare and category-qualified spellings
of that same identity are equivalent; naming the parent set is not.

A known wrong tool kind, nonexternal feature, mismatched designation, hand,
class or `fits` is an error. Selecting an undeclared member of a known
explicit member map is also an error. Missing selections, unknown or
unverified identities, a set root without a selected die member, unsupported
thread designation, or missing thread/hand/class/fit facts remain unknown.
A missing item used only for manual die threading is selection debt, not
the ordinary missing-powered-tool error; using it in a powered operation
retains that operation's ordinary identity checks. Known contradictions
take precedence over missing facts.

The separate [`op_chain`](rules-operations.md#op_chain) finding requires a
real earlier same-feature turning operation that prepares the male blank
and its full shoulder extent on the material reaching the die operation.
Missing preparation or unresolved diameter, extent, frames or retained-material
survival stays unknown. Known wrong diameter, axis, extent or material is an
error. An external thread cannot substitute a spot/drill/tap chain. Die
threading still counts as cutting for terminal release/part-off ordering.

A passing tool or preparation finding does not model helical removal.
The native path leaves stock after manual threading unresolved rather than
subtracting a nominal major-diameter cylinder. Resolve identity and
preparation debt with the actual selected equipment and source-backed
blank geometry; these facts alone cannot resolve the unmodeled thread.
Implementation: [`tool_resolves.py`](../src/prechips/rules/tool_resolves.py),
[`op_chain.py`](../src/prechips/rules/op_chain.py) and the
[kernel operation descriptor](../src/prechips/kernel/__init__.py).

### Manual tapping

`hand_tap` is the spindle-stopped internal-thread counterpart to `die_thread`,
with its own `tool_resolves` finding at `setup:op`. Select a real `tap`, or a
declared `tap_set`/`tap_die_set` member, for a `thread` or `threaded_hole`
feature. Select a holder of kind `tap_wrench` or `tap_follower`; a qualified
`tools` reference may supply that holder. See the
[inventory manual-tap reference](inventory.md#manual-taps-and-wrenches)
for the input fields.

The selected tool and holder must resolve and be verified. The tap's explicit
nominal designation must match the feature, and its hand and class must agree
after trimming whitespace and ignoring case. A known wrong kind, feature
kind, designation, hand or class is an error. A missing or unknown identity,
unsupported designation or missing hand/class remains unknown, as for manual
die threading.

Holder compatibility needs either an exact `fits` reference to the selected
tap or a known nominal tap-size range/capacity containing the tap's `dia`.
The rule prefers declared `range_mm`/`range_in` fields to `capacity_mm`/
`capacity_in`. A two-limit range is inclusive at absolute `1e-6` mm; a scalar
capacity is a maximum. These are nominal tap sizes, not a spindle-collet
shank fit. A known incompatible `fits` or out-of-capacity tap is an error
even when the other compatibility fact agrees. Missing both usable fit and
capacity facts leaves the assembly unknown.

Like `die_thread`, this action requires no powered spindle interface,
toolpost/shank fit, axial tool setting or RPM recommendation. An authored
numeric `rpm` other than zero is an error.

The separate [`op_chain`](rules-operations.md#op_chain) finding accepts
`hand_tap` as the internal tapping action but still requires the causal
spot/drill preparation on the material reaching it, including the selected
tap-drill diameter check. Manual tapping counts as cutting for terminal
release/part-off ordering. A resolved manual tool assembly does not establish
that preparation, inspection or helical geometry. The native path leaves
stock after manual tapping unresolved.
Implementation: [`tool_resolves.py`](../src/prechips/rules/tool_resolves.py),
[`op_chain.py`](../src/prechips/rules/op_chain.py) and
[`op_order.py`](../src/prechips/rules/op_order.py).

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

For nonspindle saw cut-off, resolve the selected `bandsaw` blade and a `mill` /
`bench` / `bandsaw` machine, or a `hand_saw` and a `bench` / `manual` machine,
instead of a spindle/holder/shank assembly. A hand saw on any other machine, or
a bandsaw blade on a `manual` one, is an error. A bandsaw blade that follows a
scribed line needs a `bandsaw` machine whose `saw_modes` include `"vertical"`:
other machine kinds or modes without it are errors, and undeclared modes stay
debt. These nonspindle tools require no holder.

A mill-mounted disk uses `slitting_saw` under `saw_cut` / `cut_off`, only on a
`mill`. `tool_resolves` checks the selected holder and qualified
[blade/arbor assembly](inventory.md#mounted-slitting-saw-assembly), including
interface, pilot/bore fit, body thickness, flange geometry and rotation/
retaining-thread constraints. The optional `arbor` identity alone is
insufficient. Known nonpositive dimensions or incompatible taper error;
missing or unverified facts remain debt.

An excessive bore-to-pilot clearance is an error only when the clearance
allowance itself has qualified cited or measured evidence. An unqualified
allowance leaves that comparison unknown, even when its numeric value is exceeded.

Physical consumers require matching
[finite native evidence](rules-geometry.md#saw-cut-off), not planar kerf or an
axial cutter surrogate. Recognition, including an unverified raw
`slitting_saw` identity, never grants nonspindle-saw/manual-bench waivers.
An unresolved tool kind on a mill cannot establish nonspindle scope; a
verified incompatible kind still errors. Zero and M5 measurement proofs
remain separate from assembly resolution.

Incompatible known machine/tool kinds are errors and unverified identities
remain debt. No saw replaces a groove's size-setting tool or establishes a
finished datum.

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

## `joint_thread`

### Scope and consumed facts

The rule emits one setup-scoped finding for each assembly with array
`stock_in` and `joint.kind = "threaded"`. It emits no rows for other joint
kinds or plans without a threaded assembly. It is always required:
omitting it from shop policy cannot waive an error or unresolved assembly.
It evaluates declared inputs without starting the kernel.

The joint's socket and spigot name exported finished internal-thread and
`external_thread` features, respectively, not transient `joint_features`.
The [threaded-joint plan reference](plan.md#threaded-joints) defines the
joint, actual engagement and finite seat fields; the
[feature thread reference](features.md#threaded-features) defines nominal
designation, hand, class and envelope locations. `joint_thread` also
consumes each interface's retained-material ownership on the two incoming
branches. Source-solid ownership alone is not proof of material survival.

The rule compares explicit size/pitch designations and hand. Its supported
mating-class comparison checks Unified internal B and external A roles,
not equal grade numbers. Metric tolerance classes and other unsupported
class systems stay unresolved, even if their strings happen to match.
The finite envelopes use internal `depth` and external `length`, converted
from manifest units to mm. `engagement_mm` is the authored actual engagement,
not a value inferred from either envelope.

### Errors and unresolved debt

A known contradiction produces `error`, including when other facts are
unknown:

- Different nominal thread size/pitch or conflicting explicit series,
  different hands, or incompatible supported internal/external class roles.
- Nonpositive actual engagement or threaded depth, engagement longer than
  either threaded depth, or engagement longer than the finite axial overlap.
- When both envelope locations and axes resolve, nonunit axes, axes that
  are not collinear, or finite envelopes without positive overlap.
- Negative seat gap or runout clearance, a positive shoulder-seat gap beyond
  the length tolerance, or a male threaded length greater than socket depth
  when the declared seat gap is zero.
- Seat normals that do not oppose, interface separation inconsistent with
  `gap_mm`, or finite rectangular seat patches with no overlapping contact
  area.
- An interface proved absent from both consumed branches, an interface proved
  present on multiple consumed branches, or both interfaces proved on the
  same consumed branch.

Physical-length comparisons use absolute `1e-6` mm. Axis unit and
parallelism comparisons use `1e-6` dimensionless tolerance. Envelope overlap
must exceed the length tolerance; touching endpoints supply no engagement.
Finite seat patches must have overlapping area, not just touch at an edge.

Otherwise the result is always `unknown`, never `pass`. Missing designation,
hand, supported class, frame/location/axis, scalar depth, actual engagement,
seat facts or unique retained-material ownership is listed in `missing`.
Even when all supported nominal facts agree, helical flanks, lead/runout and
prepared shoulder seating remain unmodeled. Nonnegative runout clearance is
not proof that the available clearance is sufficient.

Invalid field shapes, missing required joint fields, wrong exported feature
kinds, reuse of an interface in another joint, an interface with known faces
spanning multiple named finished solids, or two interfaces known to belong
to the same named finished solid are bad input (exit 3), not rule findings.
See the linked plan and feature contracts for those input checks.

### Evidence, remedy and limits

Evidence includes `socket`/`spigot`, normalized `socket_geometry` and
`spigot_geometry`, resolved branch references or `"unknown"`, `engagement_mm`,
normalized `seat`, `missing`, `violations` and `unmodeled_geometry`.
Citations retain the joint's source and both exported features' citations.
The nominal-agreement message explicitly says that it is not a fit, strength
or retention verdict.

Correct the contradictory selection, geometry or route identified by an
error. Supply source-backed unknown thread, seat, engagement and ownership
facts where they are available; do not replace unknown actual engagement
with the stub length or invent a seat measurement. Completing those facts
does not remove the unmodeled-geometry limit.

A removable thread does not enter the bonded cylindrical `joint_fit` path
and supplies no annular fill, retaining compound or fused finished faces.
The separate [`joint_assembly`](rules-geometry.md#joint_assembly-findings)
native finding also cannot certify joined stock from nominal cylindrical
envelopes. Neither rule establishes mechanical capacity, retention,
machining acceptance or physical assembly acceptance.
Implementation: [`joint_features.py`](../src/prechips/joint_features.py),
[`thread_specs.py`](../src/prechips/thread_specs.py),
[`joints.py`](../src/prechips/rules/joints.py) and
[`findings.py`](../src/prechips/findings.py).
