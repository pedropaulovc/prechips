<a id="shop-policy--shop-policytoml"></a>

# Shop policy: `shop-policy.toml`

Use a shop-owned policy to select required findings and supply cited shop
thresholds. Do not copy readiness overrides into each plan. Policy governs the
report gate; it cannot make an unimplemented check pass or approve unresolved
geometry.

For a worked check, see [the tutorial](manual/tutorial.md). For command syntax
and path overrides, see the [CLI reference](reference/cli.md). The
[report reference](report-and-telemetry.md) defines readiness and approval.

On this page:

- [Required subjects](#required-subjects)
- [Gate and always-required checks](#gate-and-always-required-checks)
- [Policy selection and defaults](#policy-selection-and-defaults)
- [Measured feasibility](#measured-feasibility)
- [Shop numbers](#shop-numbers)
- [Geometry requirements](#geometry-requirements)
- [Root fields](#root-fields)

## Required subjects

`required` maps rule names to `"*"`, `"setups"`, `"holes"`,
`"toleranced_features"`, an explicit subject list, or an exact subject/feature
selector.

| Selector | Matching subjects |
| --- | --- |
| `"*"` | All subjects for the named rule |
| `"setups"` | Bare setup IDs, not operation subjects |
| `"holes"` | Feature kinds `hole`, `counterbore`, `thread` and `threaded_hole`; manual relationships with a participating hole feature |
| `"toleranced_features"` | Inspection's tolerance selection, including unknown requirement identities or lists; a manual relationship is selected when a participant meets that selection |
| Exact subject list | Only the listed finding subjects, including any member or shared-check qualification |
| Exact subject, feature or relationship | An exact finding subject; a feature also selects its dimensional/member/shared checks and participating manual relationships; a relationship key selects its per-member checks |

Tolerance selection includes modeled tolerance dimension keys (including groove
width/depth) and every authored two-element numeric-or-unknown requirement band.
Ordinary three-component `at`, `thru` and `process` do not alone make a
toleranced feature. Arbitrary selector strings are not schema errors. An
unmatched selector produces unknown coverage rather than selecting everything.

Inspection ownership comes from the finding's structured identity, not from
splitting its displayed subject. For example, `base` selects
`S1:30/base:width`, and `end-length` selects `nut1/end-length:length`.
A relationship such as `stud_retention` selects its per-nut manual checks;
selecting one of its participating features selects those checks too.
The `"toleranced_features"` selector uses the participants' declared
dimensional requirements. A manual contract does not invent a numeric
tolerance.

Missing or unknown inspection ownership cannot establish that a finding is
outside a feature selection. Such findings remain readiness debt; unresolved
ownership is not positive evidence that a required feature was checked.

## Gate and always-required checks

Any error yields exit 2, regardless of policy. A required `warn`, `unknown` or
`unsupported` yields exit 4. Required `pass`, `info` and `not_applicable` do not
block the implemented gate. A missing required rule or named subject produces
an unknown coverage finding: “The shop requires a check with no matching supported
subject.”

A supplied policy with no `required` declaration behaves like
`required = "unknown"`: it creates an unknown `required_policy` coverage finding
and yields exit 4 unless an error takes precedence. It cannot authorize
`verification = "checked"`. An explicitly empty `[required]` table is a known
empty map, so nonrequired unknowns do not block. Errors still yield exit 2.

`joint_fit`, `joint_assembly`, `joint_thread`, `manual_arc`, `centre_support`,
`tooling_hole`, `prepared_blank`, `purchased_tooling` and `keep_piece` are always
required ([`findings.ALWAYS_REQUIRED`](../src/prechips/findings.py)). Their
`warn`, `unknown` and `unsupported` rows yield exit 4 even when the policy omits
them or supplies an empty `[required]` table. A `not_applicable` row does not
block. Each rule keeps its own scope: there is no `joint_thread` row without a
threaded assembly, no `purchased_tooling` row without a bought item that has
receipt checks, no `tooling_hole` row without work or location on a tooling
hole, and no `keep_piece` row without a plan `keep`.

For a removable threaded assembly, `joint_thread` checks the declared nominal
thread identities, hand/classes, axes, finite engagement, seat facts and
retained-material ownership. Known contradictions produce errors. Missing
facts remain unknown, and even agreeing nominal facts cannot prove the
unmodeled helical flanks, lead/runout or prepared shoulder seating. The current
`joint_thread` and `joint_assembly` results therefore remain unknown unless a
known contradiction makes them errors. They certify no joined stock, fit,
strength or retention. No policy selector, omission or waiver can turn that
debt into readiness. See the [joint input reference](plan.md#joint) and
[`rules/joints.py`](../src/prechips/rules/joints.py) for the consumed contract.

The setup sheet's operation-performed square records progress only. It is not
a rule `pass`, inspection acceptance, clearance to proceed, readiness or
approval. It adds no selector or status. Handwritten marks cannot clear STOP
or unknown findings or change the report gate.

## Policy selection and defaults

Selection order is `--policy`, a known `[paths].policy`, `PRECHIPS_POLICY`,
then the no-file fallback. A plan-declared `"unknown"` does not hide an
environment-supplied policy. The fallback requires `tool_resolves`, `sizing`,
`op_chain`, `blind_depth`, `inspection`, `coordinates` and `zero_check` on `"*"`.
It is not a file and has no input file digest. It does not apply to a supplied
policy that omits `[required]`.

The shared [input conventions](plan.md#input-conventions) define strict TOML keys, finite numbers
and the types below. Optional record fields accept `"unknown"` and stay absent
when omitted. In particular, omission does not invent an empty `required` map.
Schema acceptance is not proof of geometric validity; rules perform the checks.

## Measured feasibility

To require measured mill feasibility, add `envelope = "*"` and `travel = "*"`
to the shop's existing `[required]` table. These are not in the no-file fallback.
There is no `holder_stack` rule: a selected holder's unmeasured gauge keeps
`envelope` and `travel` at `?` wherever that gauge is consumed.

Missing, vendor-only, `assumed` or `illustrative` values produce `?` and exit 4
when required. A measured envelope/travel violation always yields exit 2.
Mill-only envelope/travel rows are `not_applicable` on a lathe.
See [measured setup screens](rules-setup.md#m5-measured-inventory-screens) and
[`prechips tools --measure`](reference/cli.md#measurement-checklist) for the debt behind reports.

No policy field selects a collet shank class. `tool_resolves` accepts a tool shank
in a single nominal collet capacity on the ISO 286 h6 band (ISO 286-1:2010
Table 1 IT6). Policy cannot widen it to h7 or explicit limits. See
[`tool_resolves`](rules-tools.md#tool_resolves).

## Shop numbers

`numbers` maps names to finite numeric values or `"unknown"`. `numbers_cite`
supplies matching citations; `numbers_verify` maps names to booleans or unknown.
For rule thresholds, a per-entry true or `"unknown"` verification flag withholds
the value; an omitted entry defaults to false.

A whole-map `numbers_verify = "unknown"` is not handled uniformly. Most
threshold consumers withhold their value, but `stickout` converts the non-map
to an empty map and defaults `stickout_ld_max` verification to false. A positive,
cited ratio can therefore remain a known limit in that case. To withhold that
ratio, set its individual verification entry to true or `"unknown"`; do not rely
on a whole-map unknown. The discrepancy is tracked in [issue #358](https://github.com/pedropaulovc/prechips/issues/358). The print-only fields have their own behavior below.

| Number | Consumer and meaning |
| --- | --- |
| `refixture_budget_mm` | Datum rule's re-fixturing budget, in mm |
| `stickout_ld_max` | Stick-out L/D maximum, multiplied by the smallest finished diameter along setup Z in the unsupported length, not held bar OD |
| `thin_wall_floor_mm` | Minimum grip-zone wall for the kernel's `thin_wall_under_clamp` measurement |
| `saw_min_teeth_in_work` | Fewest teeth of the blade's coarsest pitch in the thickness it crosses; must be positive, cited and explicitly unflagged. A common shop rule is 3; missing evidence leaves `?` |
| `min_hand_feed_mm` | Finger-to-blade clearance for `hold_fields` on a [hand-fed saw](plan.md#hand-fed-on-the-saw-table). Each blade position along each cut's scribed arc is compared with how far that cut's stock reaches from the blade |
| `max_filing_stock_mm` | Maximum stock a rough stair or drilled chain may leave for filing; must be nonnegative, cited and unflagged. Missing, negative, uncited or flagged values leave the filing limit unknown |
| `fixture_make_decimals` | Whole decimal places for printing shop-made fixture sizes and positions; never a pass condition |
| `near_jaw_mm` | Print-only distance threshold, in mm, for a boxed jaw-clearance line on lathe operation rows. Absent or unknown values fall back to 3 mm. The sheet does not consult citations or verification flags for this field; it is never a pass condition |

For `min_hand_feed_mm`, absent, uncited or flagged values produce `?`; work that
cannot reach the clearance produces `✗`. For `max_filing_stock_mm`, exceeding
the known cap produces an error; an unknown cap leaves filing debt. See
[coordinates](rules-coordinates.md), [lathe rules](rules-lathe.md) and
[geometry rules](rules-geometry.md).

The shipped [example policy](../examples/shop-policy.toml) supplies seven cited
illustrative values with false verification entries. Applicable rules treat
its numeric limits as known thresholds for the examples; the fixture-precision
and jaw-clearance print settings also take effect. These are not measured shop
safety limits. An illustrative citation does not make a threshold unresolved.
Do not copy these values into a real shop policy. Replace them with independently
established shop values, and flag unresolved rule thresholds rather than treating
the example limits as shop evidence.

Required physics warnings yield exit 4 through the existing gate; proxy warnings
do not invent hard physical limits.

A fit that locates the part prints at drawing precision instead of
`fixture_make_decimals`. For other fixture sizes and positions, an absent,
unknown or flagged precision falls back to the DRO grid of the fixture-making
machine (the shop's mill, else the setup machine). Every printed value lies on
that grid. See [inventory](inventory.md).

## Geometry requirements

The geometry rule catalog includes `accessibility`, `reach`,
`internal_corner_radius`, `coverage`, `blank_credit`, `finish_coverage`, `vise`,
`thin_wall_under_clamp`, `fixture_interference`, `saw_cut`, `saw_teeth`,
`keep_piece` and `joint_assembly`. Any can be named in `required`; `keep_piece`
and `joint_assembly` are already always required.

Use exact `setup:op` subjects for saw cuts. Saw cylinder checks are not
applicable, but required `saw_cut` remains unresolved when its kerf, plane or
stock cannot be derived. A missing FreeCAD kernel yields exit 4 whether or not
geometry rules are required: its `?` rows carry `kernel_unavailable`.
Exemptions do not turn missing geometry into approval.

Drill-kind `rough_profile` / `chain_drill` operations retain their `setup:op`
subjects while `speeds_feeds` selects drilling data and reports axial feed.
There is no additional selector or waiver. Missing, ambiguous or uncited
drilling data remains unresolved and blocks when required. See
[cutting data](cutting-data.md) for chart precedence and deep-hole derating.

Policy governs findings and the report gate, not [picture geometry or scale](rules-geometry.md#renders).
[Outline overlays](report-and-telemetry.md#kernel-renders) add no policy field,
waiver or verdict and cannot turn unknown or unsupported geometry into approval.

## Root fields

| Field | Type | Presence |
|---|---|---|
| `revision` | `int \| Unknown` | Optional |
| `required` | `dict[str, str \| list[str]] \| Unknown` | Optional |
| `numbers` | `dict[str, Number] \| Unknown` | Optional |
| `numbers_cite` | `dict[str, Citations] \| Unknown` | Optional |
| `numbers_verify` | `dict[str, bool \| Unknown] \| Unknown` | Optional |
