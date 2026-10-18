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
| `"holes"` | Manifest kinds `hole`, `counterbore` and `thread` |
| `"toleranced_features"` | Inspection's tolerance selection, including unknown requirement identities or lists |
| Exact subject or list | Exact finding subjects such as `feature:requirement` and `setup:op`; a feature selector also matches that feature's requirement subjects |

Tolerance selection includes modeled tolerance dimension keys (including groove
width/depth) and every authored two-element numeric-or-unknown requirement band.
Ordinary three-component `at`, `thru` and `process` do not alone make a
toleranced feature. Arbitrary selector strings are not schema errors. An
unmatched selector produces unknown coverage rather than selecting everything.

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

`joint_fit`, `joint_assembly`, `manual_arc`, `centre_support`, `tooling_hole`,
`prepared_blank`, `purchased_tooling` and `keep_piece` are always required
(`findings.ALWAYS_REQUIRED`). Their `warn`, `unknown` and `unsupported` rows
yield exit 4 even when the policy omits them. A setup with no joint or centre
has only `not_applicable` rows for those checks, which do not block. There is no
`purchased_tooling` row without a bought item that has receipt checks, no
`tooling_hole` row without work or location on a tooling hole, and no `keep_piece`
row without a plan `keep`.

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
the [measurement checklist command](reference/cli.md) for the debt behind reports.

No policy field selects a collet shank class. `tool_resolves` accepts a tool shank
in a single nominal collet capacity on the ISO 286 h6 band (ISO 286-1:2010
Table 1 IT6). Policy cannot widen it to h7 or explicit limits. See
[`tool_resolves`](rules-tools.md#tool_resolves).

## Shop numbers

`numbers` maps names to finite numeric values or `"unknown"`. `numbers_cite`
supplies matching citations; `numbers_verify` maps names to booleans or unknown.
A true or unknown verification flag prevents a value from certifying a measured
threshold.

| Number | Consumer and meaning |
| --- | --- |
| `refixture_budget_mm` | Datum rule's re-fixturing budget, in mm |
| `stickout_ld_max` | Stick-out L/D maximum, multiplied by the smallest finished diameter along setup Z in the unsupported length, not held bar OD |
| `thin_wall_floor_mm` | Minimum grip-zone wall for the kernel's `thin_wall_under_clamp` measurement |
| `saw_min_teeth_in_work` | Fewest teeth of the blade's coarsest pitch in the thickness it crosses; must be positive, cited and explicitly unflagged. A common shop rule is 3; missing evidence leaves `?` |
| `min_hand_feed_mm` | Finger-to-blade clearance for `hold_fields` on a [hand-fed saw](plan.md#hand-fed-on-the-saw-table). Each blade position along each cut's scribed arc is compared with how far that cut's stock reaches from the blade |
| `max_filing_stock_mm` | Maximum stock a rough stair or drilled chain may leave for filing; must be nonnegative, cited and unflagged. Missing, negative, uncited or flagged values leave the filing limit unknown |
| `fixture_make_decimals` | Whole decimal places for printing shop-made fixture sizes and positions; never a pass condition |

For `min_hand_feed_mm`, absent, uncited or flagged values produce `?`; work that
cannot reach the clearance produces `✗`. For `max_filing_stock_mm`, exceeding
the known cap produces an error; an unknown cap leaves filing debt. See
[coordinates](rules-coordinates.md), [lathe rules](rules-lathe.md) and
[geometry rules](rules-geometry.md).

The shipped numbers remain `"unknown"` rather than copying unsourced shop
folklore. Required physics warnings yield exit 4 through the existing gate;
proxy warnings do not invent hard physical limits.

`fixture_make_decimals` prints a fit that locates the part at drawing precision
instead. An absent, unknown or flagged precision falls back to the DRO grid of
the fixture-making machine (the shop's mill, else the setup machine). Every
printed value lies on that grid. See [inventory](inventory.md).

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
