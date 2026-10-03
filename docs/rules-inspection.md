# Inspection rule

## `inspection`

Subjects are `feature:requirement` for every requirements-listed two-element
numeric-or-unknown `[low, high]` band, even outside the named tolerance set, plus
each declared requirement in the recognized scalar/unknown tolerance set:
`dia`, `position_dia`, `finish_ra`, `depth`, `length`, `width`, `height`,
`thickness`, `separation`, `coaxiality_dia`, `angularity_dia`, `height_above_pivot`, `radius`,
`station`, `arc_len`, `bottom_radius`, `bottom_arc_len`, `tip_land`,
`land_angle_deg`, `groove_width`, `groove_depth`. This shared model selection also
drives policy `toleranced_features`; unknown generic dimensions cannot evade it.
An omitted or wholly unknown requirements list, or an unknown list element,
creates `feature:unknown` with unknown status and remains selected by policy
`toleranced_features`. A feature with an explicitly known list containing no
banded or recognized tolerance requirement (including `requirements = []`) gets
a bare-feature not-applicable finding. A missing list must not receive that
not-applicable finding. Unknown recognized dimension values still need an explicit
check; absence from a known requirements list is known absence. Bands outside
the tolerance set do not get invented defaults: the author must explicitly
declare the requirement and its limits.
An explicitly unknown kind or finishing action produces unknown for each
requirement (or the bare feature if there are none), not not-applicable.

The check must occur on or after the last relevant finishing cut, not merely on
an earlier pilot. The rule ignores rough operations, spot, deburr, coating and
release for this purpose. `checks` maps each requirement to its gauge; a missing
entry is an error, while literal `"unknown"` is an unresolved method. An entire
`checks = "unknown"` record at/after finishing likewise remains unknown. A missing
named gauge's missing-item error belongs to `tool_resolves`; inspection reports
its capability as unknown.

Gauge kinds must suit the requirement. Roughness needs a roughness gauge,
comparator or profilometer; position/coaxiality/angularity needs CMM, indicator or height
gauge. Both scalar and banded geometric requirements additionally need a known,
nonempty declared datum inspection method; bands also use range/resolution checks.
Complex shape controls need CMM/profile/radius/angle gauges. Other dimensions use the capable dimensional
gauge kinds. An external micrometer does not measure a hole bore. Type
incompatibility is an error even if catalog dimensions are unverified.

For a `[low, high]` mm band, gauge range must cover both ends and resolution must
not exceed `high-low`. A scalar geometric tolerance needs resolution
at most the tolerance and a known declared method. Non-mm/unknown limits stay unknown.
Unverified gauge range/resolution cannot prove a dimensional error or pass.
Roughness capability is unresolved without explicit range evidence; the current
inventory schema does not expose the rule's `ra_range`/`range_ra` lookup, so do
not add those extra keys to an M1 input or claim a shipped roughness capability
pass. Scalar dimensions without an implemented capability branch stay unknown.

Sentence templates:

- `{feature}: no tolerance requirement to inspect.`
- `{feature}: inspection applicability or finishing action is explicitly unknown.`
- `{feature}: requirement identity is explicitly unknown.`
- `{feature} {requirement}: {message}.`, where message is exactly one of:
  - `explicit inspection method is unknown`
  - `inspection checks are explicitly unknown`
  - `gauge identity or capability is explicitly unknown`
  - `no requirement-keyed inspection check`
  - `named gauge is not listed; capability unresolved`
  - `named gauge cannot measure this requirement`
  - `requirement limits or units are unresolved`
  - `roughness gauge spans requirement`
  - `roughness requirement outside gauge range`
  - `roughness gauge capability unresolved`
  - `gauge does not span the requirement band`
  - `gauge resolution exceeds the requirement band`
  - `gauge spans the band at sufficient resolution`
  - `gauge range or resolution unresolved`
  - `gauge resolution and declared geometric inspection method cover requirement`
  - `geometric gauge capability or datum inspection method unresolved`
  - `inspection capability for requirement unresolved`
  - `named gauge capability needs verification`
  - `unverified gauge dimensions cannot establish capability`

Evidence: requirement, limits, finishing/check op, named gauge, kind, range,
resolution and band width where available. Citations: PLAN §4.1 inspection,
feature requirement manifest and inventory range/resolution/verification. A pin
size check is not a position check; a declared gauge is not first-article data.

## Angularity

Declare the drawing's angularity control as `angularity_dia`, with its explicit
`angularity_datums` list and drawing source citation. The cone's `[0.0, 0.10]` mm
band is a geometric requirement, not a caliper size check. It needs a
requirement-keyed `checks.angularity_dia` gauge and an explicit datum-referenced
`inspection_methods.angularity_dia` narrative. The narrative is the authored
inspection declaration; the rule does not infer a method from the gauge or parse
datum letters out of prose. Missing checks are errors. Caliper-only certification
is an error even with a declared narrative. Missing, empty or literal `"unknown"`
methods, unknown limits, and missing/empty/unknown datum evidence stay unresolved.
A capable geometric gauge, known datum list and method, adequate range and
resolution are all required to pass a band.

`datum_consistency` follows each `angularity_datums` relationship to the finished
datum cut. For a numeric band it compares `high-low`, not the upper endpoint, to
`refixture_budget_mm`; a scalar angularity tolerance uses its scalar value.
Separate setups without a valid indicated pickup fail when this tolerance is
below the measured budget, and pass at equality. Each datum must independently
share the setup, have a valid transfer from after its finishing cut, or fit the
budget. Unknown referenced geometry or an unknown cross-setup tolerance/budget
remains unresolved. Position and coaxiality keep their existing datum-budget
semantics.
