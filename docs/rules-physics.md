# Static physics proxies

`turning_deflection` and `engagement` implement PLAN §4.4 (lines 563–568).
They are deterministic screens of declared facts, not measured workholding,
chatter, whip, cutter-life or final-size certification. They never emit a hard
`error`: a resolved over-limit result is `warn`, a resolved within-limit result
is `pass`, and missing or unverified necessary inputs remain `unknown` (`?`).

Both rules use operation subjects such as `S1:10`. Manual operations are
`not_applicable`; turning deflection is also not applicable to a known nonlathe
machine. An unknown operation or applicable machine identity is not a pass.

## `turning_deflection`

For a nonmanual lathe operation, use only the declared:

- span `L` in mm: a serving follow/steady rest's span (below), otherwise
  `hold.stickout_mm`;
- operation `doc_mm` and `feed_mm_rev` as radial DOC `a_p` and feed `f`;
- diameter `D`: for a radial cut, feature `dia_nominal`, then `nominal_dia`,
  then scalar `dia`. An authored unknown nominal diameter stays unknown, and a
  diameter acceptance band's midpoint is never substituted for a nominal
  diameter. For an axial-turning action (`face`, `rough_face`, `finish_face`,
  `cut_to_fit`, `part_off`, `form_dome`) the loaded section is the work entering
  the setup, `stock_state.od_mm`. A `dome` feature (any action) uses
  `turned_profile.feature_span` `base_diameter_mm` (declared `base_radius`, or
  the cap rim from `sphere_radius`/height nominal, else the kernel's revolved
  faces);
- exact authored stock-material alias and exactly one cited
  `cutting-data.[[material]]` row for `kc_n_per_mm2` and `e_gpa`.

PLAN §4.4 line 567 supplies the static proxy:

```text
F_N       = K_c_N/mm² × doc_mm × feed_mm/rev
I_mm⁴     = π × D_mm⁴ / 64
E_N/mm²   = e_gpa × 1000
δ_mm      = F_N × L_mm³ / (coefficient × E_N/mm² × I_mm⁴)
coefficient = 3 without support, 48 with declared/resolved support
```

`I` is the circular-section second moment used by the specified proxy; `1000`
is the GPa-to-N/mm² unit conversion, not a material constant. Explicit feature
`units = "in"` convert the nominal diameter and acceptance band using the same
25.4 mm/in identity as the lathe geometry rules. Unknown feature units do not
imply millimetres.

Support uses the shared `stickout.support_state` resolution. A selected verified
tailstock centre/steady-rest fixture or a suitable accessory listed by the
**selected setup machine** enables coefficient 48 over `hold.stickout_mm`.
Merely listing support in inventory does not declare it installed; an unrelated
machine's accessory does not qualify. Explicit `support = "none"` selects
coefficient 3. An absent, unknown, missing or unverified necessary support
declaration leaves deflection unknown. The shared helper also handles
`supports` lists and reference records.

### Follow and steady rests

A `hold.supports` table entry `{ ref, ops = [op ids], jaw_lead_mm }` declares a
follow rest; `{ ref, ops, at_z_mm }` a steady rest (setup-frame Z). `ref` must
resolve to a verified `inventory.fixtures` item of kind `follow_rest` /
`steady_rest` with fact-local measured `capacity_min_mm`/`capacity_max_mm` (or
`_in`). Omitted `ops` means every turning op of the setup; an explicit unknown
`ops` is unresolved. A rest serves an operation it lists when the diameter its
jaws ride on lies inside the inclusive capacity:

```text
follow rest: ridden D = turned diameter (radial rough cut: nominal + rough_allowance_mm)
             L = jaw_lead_mm
steady rest: ridden D = declared finished profile diameter(s) at at_z_mm
             L = max |cut z − at_z_mm| over the op's z_from/z_to (else to_z)
coefficient = 3 (cantilever from the rest jaws to the tool)
```

The shortest served span wins. A rest outside its capacity does not serve the
op, and a rest table is never a whole-stickout support: the op falls back to the
stick-out model above with only the remaining supports. An unresolved serving
rest (unknown kind or reference, unmeasured or unverified capacity, unknown jaw
lead, ridden diameter, `at_z_mm` or cut z, or both `jaw_lead_mm` and `at_z_mm`)
leaves deflection unknown and lists unmeasured capacity in the measurement
checklist. Rests have no kernel solid; they are not drawn or collision-checked.
Evidence: `span_mm`, `span_model` (`stickout`/`follow_rest`/`steady_rest`),
`rests` rows (reference, kind, ops, capacity, ridden diameter, span, status
`pass`/`outside_capacity`/`unknown`) and `turned_diameter_mm`.

### Acceptance threshold

The comparison follows PLAN line 567's ± tolerance wording against the
operation's own acceptance:

```text
rough_* action:          acceptance_threshold_mm = rough_allowance_mm / 2
dome feature:            acceptance_threshold_mm = (height_high_mm - height_low_mm) / 2
axial-turning action:    acceptance_threshold_mm = (length_high_mm - length_low_mm) / 2
                         (the feature's `height` band when it declares no `length`)
otherwise:               acceptance_threshold_mm = (dia_high_mm - dia_low_mm) / 2
δ_mm ≤ acceptance_threshold_mm  → pass
δ_mm > acceptance_threshold_mm  → warn
```

A rough cut is judged against the stock it leaves for finishing, not the finish
band; a missing or nonpositive `rough_allowance_mm` is unknown. The ordered
feature `[low, high]` band must have a real citation. For a requirement-keyed
citation mapping, only the band's own key (`cite.dia`, `cite.length`,
`cite.height`) supplies that acceptance source; a cited length cannot certify a
diameter tolerance. No tolerance is inferred from a nominal value, general
class, handbook page or policy default.
When the force model is computable but the acceptance threshold is
missing, the result still reads `?`: the report keeps the computed deflection
and explains the missing comparison threshold. This half-band comparison is a
static screening proxy, not a prediction that bending changes size by δ.
Evidence names `acceptance_field`, `acceptance_band_mm`,
`acceptance_threshold_mm`, `tolerance_basis`, `diameter_basis` and
`rough_allowance_mm`.

Nonpositive DOC, feed, diameter, length, `K_c` or `E`, ambiguous material rows,
unknown aliases and material/machine verification debt cannot establish a
computed model. The examples' unsourced material coefficients remain unknown;
these rules do not add a Machinery's Handbook 31 citation or material value.

Evidence includes force, inertia, converted modulus, deflection, coefficient,
resolved support evidence, input material/class, cited acceptance band, derived
half-band and missing-input reasons. Citations include the operative PLAN row,
authored plan/feature field identities, actual cutting-data row source and
actual feature acceptance-band (or operation rough-allowance) source.

## `engagement`

This is an **endmill-only** screen for cutting operations with an explicitly
authored `doc_mm`. The selected resolved tool/member must have kind `endmill`
or `endmill_set`. Known drill, reamer, tap, lathe-tool and other non-endmill
families are `not_applicable`, even when the operation declares DOC; their
geometry must not produce a milling DOC-halving recommendation.
Noncutting/manual operations, including the manual joining action `fit` and `transfer`, and operations
with omitted DOC are also `not_applicable`. Cutting actions use the existing
face, profile, pocket, hole-making and turning action conventions; an endmill
used for a counterbore with authored DOC remains eligible.

On an eligible cutting operation with authored DOC, an unresolved selected
tool/member or unknown tool kind stays `unknown`, rather than establishing a
non-endmill exclusion. An unknown action also stays unknown unless omitted DOC
or a known non-endmill family independently establishes non-applicability.

Resolve the operation's selected inventory tool **and** holder. Use the existing
explicit-unit `length_mm` helper for tool diameter, projection/OAL and holder
grip; a tool with a bare diameter and no units does not acquire an assumed unit.

Projection uses explicit selected-tool geometry before OAL-minus-grip arithmetic:

1. Authored `projection_mm`, `projection_in`, or explicit-unit `projection` on
   the resolved selected tool identity/member. An explicit unknown remains
   unknown; it does not permit an OAL-minus-grip fallback.
2. Only when all projection keys are absent, known tool OAL minus the selected
   holder's known grip.

The existing schema carries a scalar projection on the selected tool/member;
there is no new per-holder projection mapping. Both the tool and holder must
resolve and be verified even when explicit tool projection is available. No
holder grip, tool diameter, OAL or projection is supplied for an absent tool.
Nonpositive projection, diameter or required fallback dimensions remain unknown.

PLAN §4.4 line 568 supplies both the 4×D boundary and halving factor:

```text
projection_ld = projection_mm / diameter_mm
projection_ld ≤ 4 → pass; no DOC reduction
projection_ld > 4 → warn; recommended_doc_mm = authored_doc_mm × 0.5
```

Equality passes. The existing `resolution.same_length` precision convention
(1 nm absolute, no relative slack) recognizes physically equal projection and
`4 × D` despite inch-conversion residue; the report keeps the unrounded ratio.
This is arithmetic equality handling, not a new shop-policy allowance.
The recommendation never changes the authored operation.
Unknown/nonpositive **authored** DOC keeps an eligible endmill result `unknown`
at any projection ratio, including at or below 4×D. When the geometry is known,
the report retains the projection ratio and prints `?`, but never guesses a
recommended cut depth. This differs from omitted DOC, which is `not_applicable`.

Evidence includes selected identities and tool kind, explicit-unit diameter, OAL, grip,
projection and its source basis, ratio, PLAN limit, authored DOC, reduction
factor, recommended DOC and missing-input reasons. Citations identify PLAN
line 568 and the actual selected inventory/operation fields.

## Existing readiness gate

There is no new warning-promotion mechanism. The existing shop `required`
selectors decide whether either proxy must be clean:

- Optional `warn`/`unknown`: exit 0 if no other rule stops the plan.
- Required `warn`/`unknown`: exit 4, remaining `PLANNED`.
- Any rule's hard `error`: exit 2, taking precedence over required proxy debt.
- Malformed input: exit 3 before rules or outputs.

The existing precedence is **3 > 2 > 4 > 0** (PLAN lines 473–478 and 501–509).
Isolated synthetic tests in `tests/test_physics_m2.py` cover the equations,
support selection, explicit units, projection fallback/precedence, DOC halving,
unknowns, deterministic nonmutating findings and these consumer-visible gates;
`tests/test_turning_rests.py` covers rest spans and capacity boundaries, rough
and axial thresholds and the dome base diameter.
Their numeric material rows are test fixtures, never shipped cutting data.
