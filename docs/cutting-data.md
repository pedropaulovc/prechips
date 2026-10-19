<a id="cutting-data--cutting-datatoml"></a>

# Cutting data: `cutting-data.toml`

Use `cutting-data.toml` to supply cited starting speeds, feeds, deep-hole
derating and material coefficients. These values support recommendations and
force models; they do not certify cut stability or physical machining conditions.

For a worked bundle, see [the tutorial](manual/tutorial.md). Tool charts and
machine limits are [inventory facts](inventory.md); rule decisions are in
[tool rules](rules-tools.md) and [physics rules](rules-physics.md).

On this page:

- [File selection and input conventions](#file-selection-and-input-conventions)
- [Cut row selection](#cut-row-selection)
- [Spindle speed and feed](#spindle-speed-and-feed)
- [Chain drilling](#chain-drilling)
- [Deep-hole speed reduction](#deep-hole-speed-reduction)
- [Saw speed and feed](#saw-speed-and-feed)
- [Material data and citations](#material-data-and-citations)
- [Field catalog](#root-fields)

## File selection and input conventions

Selection is `--cutting-data`, then a known `[paths].cutting_data`. There is no
environment fallback. Without an explicit override, an omitted or `"unknown"`
path is bad input (exit 3), not a source of invented numbers. See the
[CLI reference](reference/cli.md) for command options.

The shared [input conventions](plan.md#input-conventions) define strict TOML keys, finite numeric
types and citations. Optional fields in the catalog accept `"unknown"` and
remain absent when omitted. Rules determine whether missing information is an
error, unknown or not applicable. A missing fact needed by an applicable check
cannot establish known absence or a pass. Schema acceptance alone does not
prove geometric validity.

## Cut row selection

`aliases` maps an exact authored material string to a material class. `[[cut]]`
rows select `(material_class, tool_material, operation)` and an inclusive
`diameter_range` in millimetres. Exactly one cited matching row is needed.
Overlapping matches remain unresolved; selection never uses the first row
as a tie-breaker. Face variants select `face`; pocket/profile variants select
`profile`.

A known tool `chart` takes priority and requires that tool's own `sfm` and
chip load. The checker does not fetch the chart. Keep a cited per-tool chart
when it records a deliberate feed choice: removing it selects the shop row's
feed, which may be higher.

## Spindle speed and feed

`sfm` is surface feet/minute; `chip_load_mm_per_tooth` is mm/tooth. The
selected diameter and machine speed range are required.

RPM is `12*sfm/(pi*D_in)`, rounded to the nearest 50 (ties to even), then clamped
to actual machine limits. A nonmultiple-of-50 boundary is retained.
If `spindle.ranges_rpm` is present, each band is clipped to known `rpm_min`
and `rpm_max`; otherwise those limits define one band. Every band's endpoints
must be known, and at least one band must survive clipping. A rounded, clamped
speed in a gap moves down to the highest endpoint of a lower band. An in-band
speed stays unchanged; without a lower band, a gap value is unknown.
The checker never recommends an RPM in an unavailable gap.

Mill feed is `RPM*flutes*chip_load_mm_per_tooth`. Lathe feed is
`RPM*feed_mm_rev`; `feed_mm_rev` is mm/revolution, taken from the operation
when declared, else from the same cited row or tool chart. It follows the same
citation and verification rules as chip load. These are starting points, not
cut-force or stability limits.

The operation ledger keeps each cited recommendation beside its action in
authored order. Marking the operation performed neither accepts that
recommendation nor verifies actual cutting conditions. The paper layout adds
no cutting-data field and never replaces unknown recommendations with numbers.

## Chain drilling

A `rough_profile` with contour method `chain_drill` and tool kind `drill`
(including `drill_index`/`drill_set` members) selects `operation = "drill"`,
not an end-mill `profile` row. Drilling chip load times flutes gives axial
feed per revolution, also used for plunge; `[[plunge]]` is exclusively
end-mill data. A tool chart retains precedence but is not needed to work
around chain-drill lookup.

Drill feed cells show axial mm/min and mm/rev for a hand-fed quill. The mm/rev
value is the same chip load times flute count, not a separate recommendation.
Matching `[[deep_hole]]` rows use the canonical before-state feature entry,
else stock top, minus `to_z` in manifest units, converted to mm. The previous
chain endpoint and the approach lift do not define cutting depth.

## Deep-hole speed reduction

`[[deep_hole]]` rows derate starting speed. Each names an `operation` (for
example `drill`), a `depth_over_dia` threshold and an `sfm_factor` in `(0, 1]`.
When depth is strictly greater than the threshold times tool diameter, the
row or chart `sfm` is multiplied by that factor before RPM is derived.
Chip load or feed per revolution stays unchanged, so feed falls with RPM.

For holes, depth is the material cut at full diameter, from the `blind_depth`
tip endpoints: through-hole local thickness or planned blind-hole `depth_mm`,
never point or exit lead. Chain drilling uses the before-state depth described
above. The deepest exceeded threshold governs. An operation not named by any
row keeps its speed. For a named operation, unknown depth, nonpositive threshold
or factor, a factor above 1, an uncited row or a tie at the governing threshold
leaves RPM and feed unknown.

## Saw speed and feed

For a nonspindle `bandsaw`, `saw_cut` and `cut_off` select
`operation = "saw_cut"` by material class and blade material, without a
rotating-tool `diameter_range`. Exactly one cited row supplies positive `sfm`
(linear blade feet/minute) and `feed_mm_min` (blade descent feed). Blade speed
is clamped inclusively to the machine's positive, ordered
`blade_speed_sfm = [min, max]`. It is neither converted to RPM nor rounded to
50. Tool charts and operation overrides do not supply these bandsaw numbers.

For a vertical bandsaw operation with `follows`, the work is hand-fed along
the scribed line. Descent feed is `not_applicable`, and its absence creates no
feed debt. Missing, ambiguous or uncited rows, unknown applicable speeds/feed,
identity debt and material verification remain `?`. These recommendations do
not certify blade capacity, tooth selection, tension or physical feed control.

Blank and `"unknown"` citation entries are discarded. Without a remaining
source, a row cannot certify saw speed/feed; a mixed list keeps its real sources.

A verified inventory `hand_saw` has no blade speed or machine feed;
`speeds_feeds` reports `not_applicable` for it.

A mill-mounted `slitting_saw` is a rotating tool, not a bandsaw speed alias.
For either saw action it selects `operation = "slitting_saw"`: a cited tool
chart takes priority, otherwise exactly one cited cut row must match material
class, tool material and the explicit disk OD within `diameter_range`. It
requires positive `sfm` and `chip_load_mm_per_tooth`, disk `dia_mm` / `dia_in`
and `flutes` as tooth count. Use the spindle RPM calculation, rounding and
machine limits above; feed is `RPM × flutes × chip_load_mm_per_tooth`.
Canonical `operation = "saw_cut"` rows and their descent feed never supply
rotating-saw numbers. Unknown dimensions, tooth count, source or spindle limits
leave recommendations unknown. These starting numbers do not establish disk
engagement, teeth in the work, arbor fit or physical clearance.

## Material data and citations

`[[material]]` carries material class, `kc_n_per_mm2`, `e_gpa` and citations
for [turning deflection](rules-physics.md). Exactly one sourced row is needed.
`K_c` is N/mm²; `E` is GPa, explicitly converted to N/mm². Authored radial DOC
and feed/revolution supply the force inputs.

The shipped example rows are labelled `example (plausible, not measured)`
and checked against cited published ranges. They are illustrative values,
not shop measurements. A cutting-data citation never supplies physical
measurement status; only an inventory fact's own
[`measured.status`](inventory.md#measured-envelopes-and-installed-tool-stacks-m5)
does. Cutting-data rows have no `status` field; their trust comes from the
cite/verify contract. Missing sources, values, geometry or material verification
remain unresolved, not zero deflection. New numerical rows require source evidence.

Citation collection discards blank and `"unknown"` entries individually, keeping
known sources in mixed lists. The same collector serves comparison, construction,
indexing, sizing, holding policy, turned profiles and turning deflection.
Per-fact citation maps select only the requested fact.

Cutting data supplies recommendations, not [picture geometry or scale](rules-geometry.md#renders).
[Outline overlays](report-and-telemetry.md#kernel-renders) add no cutting-data
field and change no cited cutting value, RPM or feed recommendation.

## Root fields

| Field | Type | Presence |
|---|---|---|
| `revision` | `int \| Unknown` | Optional |
| `aliases` | `dict[str, str] \| Unknown` | Optional |
| `cut` | `list[Cut] \| Unknown` | Optional |
| `material` | `list[CutMaterial] \| Unknown` | Optional |
| `deep_hole` | `list[DeepHole] \| Unknown` | Optional |
| `plunge` | `list[Plunge] \| Unknown` | Optional |

## Cut

The selected operation determines which feed fields apply: chip load for
rotating-tool rows (including `slitting_saw`), feed/revolution for turning and
descent feed for nonspindle `saw_cut` rows.

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

Material coefficients are force-model inputs under the row's citation. They do
not establish workholding capacity or qualify an adhesive-tape hold.

| Field | Type (also accepts `"unknown"`) |
|---|---|
| `material_class` | `str` |
| `kc_n_per_mm2` | `float` |
| `e_gpa` | `float` |
| `kc1_n_per_mm2` | `float` (Kienzle specific cutting force at h = 1 mm, > 0) |
| `mc` | `float` (Kienzle exponent, 0 ≤ mc < 1) |
| `radial_ratio` | `float` (radial / tangential force ratio, ≥ 0) |
| `cite` | `Citations` |

`kc1_n_per_mm2`, `mc` and `radial_ratio` feed the [milling force bound](rules-physics.md#cutting-force)
under the row's own `cite`; `kc_n_per_mm2` stays the constant K_c of `turning_deflection`.

## DeepHole

See [deep-hole speed reduction](#deep-hole-speed-reduction) for threshold
selection and unknown conditions.

| Field | Type (also accepts `"unknown"`) |
|---|---|
| `operation` | `str` |
| `depth_over_dia` | `float` |
| `sfm_factor` | `float` |
| `cite` | `Citations` |

## Plunge

An end mill plunges when fed down its own axis into material, including a
milled path descending at a depth level the stock box does not prove clear.
See [coordinates](rules-coordinates.md#coordinates).

Outside drilling operations, plunges are supported only for centre-cutting end mills.
The inventory record must declare `center_cutting = true`; `false` prohibits feeding down, while
an absent or unknown declaration leaves capability unproven, regardless of row data.

The checker does not currently enforce the end-mill kind on this lookup:
any other tool with `center_cutting = true`, including a drill used in a milled
path, can receive the same feed. This is a [known checker defect](https://github.com/pedropaulovc/prechips/issues/359),
not support for plunging with other tool kinds. Do not use that result to authorize
an unsupported entry.

Plunge selection uses stock material class (through `aliases`), tool `material`
and tool diameter in mm within inclusive `diameter_range`, without an operation
selector. Exactly one cited, verified row with positive `feed_mm_rev` gives
`rpm * feed_mm_rev` mm/min at the operation's starting RPM. No match, multiple
matches, an uncited or unverified row, or a nonpositive feed leaves it unknown.
A plunging operation without known plunge feed has coordinates debt and a STOP
on the sheet.

| Field | Type (also accepts `"unknown"`) |
|---|---|
| `material_class` | `str` |
| `tool_material` | `str` |
| `diameter_range` | `Vector` |
| `feed_mm_rev` | `float` |
| `cite` | `Citations` |

The shipped example rows (`# --- SheetR5 additions ---`) are author's choices
derived from Machinery's Handbook, 27th ed.: half the low end of the p.1060
drill feed for the size band (1/8 to 1/4 in from exactly 3.175 mm, then to
1/2 in). That equals one or two teeth of the Table 15a (p.1054) end-mill feed
per tooth. The values are illustrative, not shop measurements.
