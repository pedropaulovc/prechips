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
`RPM*flutes*chip_load_mm_per_tooth`; lathe feed is `RPM*feed_mm_rev` with
`feed_mm_rev` (mm/revolution) from the same cited row or tool chart, under the
same citation and verify rules as the chip load. Numbers are starting points,
not cut-force or stability limits.

Saw actions `saw_cut` / `cut_off` both select `operation = "saw_cut"` by material
class and blade material, **without** a rotating-tool `diameter_range`. Exactly
one cited row supplies positive `sfm` (linear blade feet/minute) and
`feed_mm_min` (blade descent feed). The blade speed is clamped inclusively to the
machine's positive, ordered `blade_speed_sfm = [min, max]`; it is not converted
to RPM or rounded to 50. Tool charts and op-level overrides do not supply saw
numbers. Missing/ambiguous/uncited rows, unknown speeds/feed, identity debt and
material verification stay `?`. These are starting recommendations, not blade
capacity, tooth selection, tension or physical feed-control certification.
Blank and `"unknown"` citation entries are discarded. A row with no remaining
source cannot certify a saw speed/feed; a mixed list keeps its real citations.

`[[material]]` carries material class, `kc_n_per_mm2`, `e_gpa`, and citations for
M2 [turning deflection](rules-physics.md). Exactly one sourced material row is
needed. `K_c` is N/mm² and `E` is GPa (converted explicitly to N/mm²); authored
radial DOC and feed/revolution supply the force inputs. The shipped K_c/E values
remain `"unknown"`: no verified Handbook 31 table/page is available. Missing
sources, values, geometry or material verification remain unresolved, not zero
deflection. Adding a numerical row requires real source evidence.

Citation collection discards blank and `"unknown"` entries individually, so an
incomplete list does not erase other known sources. The same collector handles
comparison, construction, indexing, sizing, holding policy, turned profiles and
turning deflection; per-fact citation maps select only the requested fact.

Selection is `--cutting-data`, then a known `[paths].cutting_data`. There is no
cutting-data environment fallback; an omitted or `"unknown"` path without an
explicit override is bad input (exit 3), not a source of invented numbers.

All five inputs are UTF-8 TOML, parsed by `tomllib` and strict Pydantic 2
models in `src/prechips/model.py`. Unknown keys are forbidden at every modeled
record (`extra="forbid"`); arbitrary keys are allowed only in explicitly declared
dictionaries (for example feature identities or `checks`). Floats must be finite;
booleans are not numeric substitutes. `Number` means a numeric float or the literal
`"unknown"`; `Vector` means a list of Numbers or `"unknown"`; `Citations` means
a string or a list of strings. Text fields also accept `"unknown"`.

Every `record()` field below is optional and accepts `"unknown"` in addition to
the displayed type. Omitted fields are not filled into the loaded bundle; rules
decide whether missing information is an error, unknown or not applicable.
Missing facts needed by an applicable check cannot establish known absence or a
pass. Root fields marked required must be present. A model accepting a value is
not proof of geometric validity; rules perform the applicable checks.

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
| `feed_mm_rev` | `float` |
| `feed_mm_min` | `float` (saw blade descent feed only) |
| `cite` | `Citations` |

## CutMaterial

| Field | Type (also accepts `"unknown"`) |
|---|---|
| `material_class` | `str` |
| `kc_n_per_mm2` | `float` |
| `e_gpa` | `float` |
| `cite` | `Citations` |
