# Shop policy — `shop-policy.toml`

Policy is shop-owned. Do not copy readiness overrides into each plan.
`required` maps rule names to `"*"`, `"setups"`, `"holes"`,
`"toleranced_features"`, an explicit subject list, or an exact subject/feature
selector. `holes` selects manifest kinds `hole`, `counterbore`, and `thread`;
`toleranced_features` uses the same selection as inspection: modeled tolerance
dimension keys (including groove width/depth), every authored two-element
numeric-or-unknown requirement band, and unknown requirement identities/lists.
Non-tolerance requirements such as ordinary three-component `at`, `thru`, and
`process` do not alone make a toleranced feature. Lists match exact finding
subjects, including `feature:requirement` and `setup:op`; feature selectors also
match their requirement subjects. `setups`
selects bare setup ids, not operation subjects. Arbitrary selector strings are
not schema errors; an unmatched subject gets an unknown coverage finding rather
than selecting every subject.

Any error yields exit 2 regardless of policy. A required `warn`, `unknown`, or
`unsupported` yields 4. Required `pass`, `info`, and `not_applicable` do not block
the implemented gate. A missing required rule or named subject gets
an unknown coverage finding: “The shop requires a check with no matching supported
subject.” A present policy file with no `required` declaration is treated like
`required = "unknown"`: it creates an unknown `required_policy` coverage finding
and yields exit 4 unless an error takes precedence (exit 2). It cannot authorize
`verification = "checked"`. An explicitly empty `[required]` table is different:
it is a known empty requirement map, so nonrequired unknowns do not block the
gate. Any error still yields exit 2. Policy cannot make an unimplemented required
check silently pass.

When no policy path is supplied, the loader requires `tool_resolves`, `sizing`,
`op_chain`, `blind_depth`, `inspection`, `coordinates`, and `zero_check` on `"*"`.
The fallback is not an extra file and therefore has no file digest in inputs.
This no-file fallback is not used for a supplied policy that omits `[required]`.
Selection is `--policy`, then a known `[paths].policy`, then
`PRECHIPS_POLICY`, before that no-file fallback. A plan-declared `"unknown"`
does not hide an environment-supplied shop policy.

M5 does not change this default. To require measured mill feasibility, add
`envelope = "*"` and `travel = "*"` to the shop's `[required]` table alongside
its existing requirements. `holder_stack = "*"` can also require every selected
cutting holder's measured gauge length. Missing or vendor-only values produce
`?` and exit 4 when required; a measured envelope/travel violation always
produces exit 2. Mill-only envelope/travel rows are `not_applicable` on a lathe.
See [measured setup screens](rules-setup.md#m5-measured-inventory-screens) and
`prechips tools --measure` for the concrete machine checklist.

`numbers` is a map of finite numeric values or `"unknown"`; `numbers_cite` is
the matching citation map; `numbers_verify` maps names to booleans or unknown.
The datum rule consumes `refixture_budget_mm`; M2 stick-out consumes
`stickout_ld_max`, multiplied by the smallest finished diameter in the unsupported
length (feature diameters along setup Z), not held bar OD. See PLAN §4.1 and
[lathe rules](rules-lathe.md). A true or unknown verification flag prevents
either from certifying a measured threshold. The shipped numbers remain `"unknown"`
rather than copying unsourced shop folklore. Required M2 physics warnings promote
readiness to exit 4 using the existing gate; proxy warnings never invent a
hard physical limit. Other number names do not imply deferred M4 rules shipped.

All five inputs are UTF-8 TOML, parsed by `tomllib` and strict Pydantic 2
models in `src/prechips/model.py`. Unknown keys are forbidden at every modeled
record (`extra="forbid"`); arbitrary keys are allowed only in explicitly declared
dictionaries (for example feature identities or `checks`). Floats must be finite;
booleans are not numeric substitutes. `Number` means a numeric float or the literal
`"unknown"`; `Vector` means a list of Numbers or `"unknown"`; `Citations` means
a string or a list of strings. Text fields also accept `"unknown"`.

Every `record()` field below is optional and accepts `"unknown"` in addition to
the displayed type. Omitted fields are not filled into the loaded bundle;
policy gates read an omitted `required` declaration as unknown rather than
inventing a known empty map. Other optional fields retain their applicability
semantics in the rules.
Root fields marked required must be present. A model accepting a value is not proof
of geometric validity; rules perform the applicable checks.

## Root fields

| Field | Type | Presence |
|---|---|---|
| `revision` | `int \| Unknown` | Optional |
| `required` | `dict[str, str \| list[str]] \| Unknown` | Optional |
| `numbers` | `dict[str, Number] \| Unknown` | Optional |
| `numbers_cite` | `dict[str, Citations] \| Unknown` | Optional |
| `numbers_verify` | `dict[str, bool \| Unknown] \| Unknown` | Optional |
