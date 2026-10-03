# Cutting data — `cutting-data.toml`

`aliases` maps an exact authored material string to a material class. `[[cut]]`
rows select `(material_class, tool_material, operation)` and an inclusive
`diameter_range` in millimetres. Exactly one cited matching row is needed;
overlapping matches are unresolved, never first-row wins. Face variants select
`face`; pocket/profile variants select `profile`. A known tool `chart` takes
priority and requires that tool's own `sfm` and chip load; no chart is fetched.

`sfm` is surface feet/minute; `chip_load_mm_per_tooth` is mm/tooth. The machine
range and selected diameter are also required. RPM is `12*sfm/(pi*D_in)`, rounded
to nearest 50 (ties to even), then clamped to the actual machine limits.
An actual nonmultiple-of-50 boundary is retained. Mill feed is
`RPM*flutes*chip_load_mm_per_tooth`; the current rule does not certify a lathe
feed. Numbers are starting points, not cut-force or stability limits.

`[[material]]` carries material class, `kc_n_per_mm2`, `e_gpa`, and citations for
future force/deflection use. Carrying these fields does not implement physics
checks. Missing source pages, values, range, tool facts or material verification
remain unknown. The examples do not claim any verified Handbook 31 table/page
or cutting numbers; adding a row requires real source evidence.

All five inputs are UTF-8 TOML, parsed by `tomllib` and strict Pydantic 2
models in `src/prechips/model.py`. Unknown keys are forbidden at every modeled
record (`extra="forbid"`); arbitrary keys are allowed only in explicitly declared
dictionaries (for example feature identities or `checks`). Floats must be finite;
booleans are not numeric substitutes. `Number` means a numeric float or the literal
`"unknown"`; `Vector` means a list of Numbers or `"unknown"`; `Citations` means
a string or a list of strings. Text fields also accept `"unknown"`.

Every `record()` field below is optional and accepts `"unknown"` in addition to
the displayed type. Omitted fields are not filled into the loaded bundle; rules
decide whether missing information is an error, unknown or not applicable. Root
fields marked required must be present. A model accepting a value is not proof
of geometric validity; rules perform the applicable checks.

## Root fields

| Field | Type | Presence |
|---|---|---|
| `revision` | `int \| Unknown` | Optional |
| `aliases` | `dict[str, str] \| Unknown` | Optional |
| `cut` | `list[Cut] \| Unknown` | Optional |
| `material` | `list[CutMaterial] \| Unknown` | Optional |

## Cut

| Field | Type (also accepts `"unknown"`) |
|---|---|
| `material_class` | `str` |
| `tool_material` | `str` |
| `operation` | `str` |
| `diameter_range` | `Vector` |
| `sfm` | `float` |
| `chip_load_mm_per_tooth` | `float` |
| `cite` | `Citations` |

## CutMaterial

| Field | Type (also accepts `"unknown"`) |
|---|---|
| `material_class` | `str` |
| `kc_n_per_mm2` | `float` |
| `e_gpa` | `float` |
| `cite` | `Citations` |
