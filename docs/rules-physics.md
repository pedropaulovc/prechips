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

- `hold.stickout_mm` as unsupported/supported length `L` in mm;
- operation `doc_mm` and `feed_mm_rev` as radial DOC `a_p` and feed `f`;
- feature `dia_nominal`, then `nominal_dia`, then scalar `dia` as diameter `D`.
  An authored unknown nominal diameter stays unknown, and a diameter acceptance
  band's midpoint is never substituted for a nominal diameter;
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
**selected setup machine** enables coefficient 48. Merely listing support in
inventory does not declare it installed; an unrelated machine's accessory does
not qualify. Explicit `support = "none"` selects coefficient 3. An absent,
unknown, missing or unverified necessary support declaration leaves deflection
unknown. The shared helper also handles `supports` lists and reference records.

The acceptance comparison follows PLAN line 567's ± tolerance wording:

```text
diameter_tolerance_mm = (dia_high_mm - dia_low_mm) / 2
δ_mm ≤ diameter_tolerance_mm  → pass
δ_mm > diameter_tolerance_mm  → warn
```

The ordered feature `dia = [low, high]` band must have a real citation. For a
requirement-keyed citation mapping, only `cite.dia` supplies that acceptance
source; a cited length cannot certify a diameter tolerance. No tolerance is
inferred from a nominal value, general class, handbook page or policy default.
When the force model is computable but the sourced acceptance threshold is
missing, the result still reads `?`: the report keeps the computed deflection
and explains the missing comparison threshold. This half-band comparison is a
static screening proxy, not a prediction that bending changes diameter by δ.

Nonpositive DOC, feed, diameter, length, `K_c` or `E`, ambiguous material rows,
unknown aliases and material/machine verification debt cannot establish a
computed model. The examples' unsourced material coefficients remain unknown;
these rules do not add a Machinery's Handbook 31 citation or material value.

Evidence includes force, inertia, converted modulus, deflection, coefficient,
resolved support evidence, input material/class, cited acceptance band, derived
half-band and missing-input reasons. Citations include the operative PLAN row,
authored plan/feature field identities, actual cutting-data row source and
actual feature diameter source.

## `engagement`

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
Above the limit, unknown/nonpositive authored DOC means an unknown reduction,
not a guessed cut depth; the report retains the known projection ratio and
prints `?`. At or below the limit no DOC is needed to decide the projection
check, so a missing DOC does not invent or demand a cutting recommendation.

Evidence includes selected identities, explicit-unit diameter, OAL, grip,
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
unknowns, deterministic nonmutating findings and these consumer-visible gates.
Their numeric material rows are test fixtures, never shipped cutting data.
