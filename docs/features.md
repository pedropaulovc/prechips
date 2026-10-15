# Feature manifest — `features.toml`

`part`, `frames`, and `features` are required. The loader rejects an empty
feature map. `frames` must be supplied but may be literal `"unknown"`; individual
frame/datum entries can also be `"unknown"`. Unknown is not an identity basis.
Each feature's `requirements` is a list or literal `"unknown"`. Omitting the
field leaves requirement identities unknown; it is not shorthand for `[]`.
Known list entries must be unique, must name modeled fields, and must have their
own explicitly supplied field values. A literal `"unknown"` list element means
the requirement identity is unresolved; it is not an extra field name that the
author must fabricate. An explicitly supplied unknown dimension value satisfies
presence but never proves the requirement. Absence from a known requirements
list represents known absence; an omitted or unknown whole list cannot establish
absence. An explicit `requirements = []` is legal and known empty, but does not
prove drawing completeness. Omitted/unknown lists or identities yield an
unresolved `inspection` subject `feature:unknown`, not a fictional tolerance or
N/A. This same selection keeps them required under policy `toleranced_features`.

`units` accepts only `"mm"`, `"in"`, or `"unknown"`. Feature geometry coordinates
use that unit; M1 does not silently convert drawing tolerance limits into mm.
`precision` is the drawing's display class; per-feature `precision` maps each
dimension to its decimal places. Nominal/reference dimensions and BASIC
coordinates do not acquire invented acceptance bands. Dimension fields accept
a scalar or list of Numbers; list limits conventionally mean `[low, high]`.
For a banded requirement, `<requirement>_nominal` / `nominal_<requirement>`
means its intended in-band target; inspection checks inclusive membership.
It is not a general fit-system basic-size field: displaced g6/p6 zones can
exclude the reference basic size, and interpreting those fit semantics is not
implemented. Do not conflate a fit's reference geometry with its acceptance
target.

Manifest units, frames and bound STEP geometry supply the finished-outline coordinates and projected spans used for picture scale under [render geometry](rules-geometry.md#renders).
[Traveler outline overlays](report-and-telemetry.md#kernel-renders) use a separate bounded stream for painting only, preserving main's accepted leaders and all original ordinary-tolerance layout and anchor inputs. [#211](https://github.com/pedropaulovc/prechips/issues/211) stays open for a dedicated future leader PR. This adds no manifest field and changes no authored feature coordinates, nominal dimensions, tolerance bands or requirement identities.

Chain drilling does not require an invented hole feature or a new manifest field.
For a drill-kind `rough_profile` / `chain_drill` operation, deep-hole speed
derating uses the canonical before-stock state's entry for the named feature
(else its stock top), minus the plan's `to_z`, converted from manifest units
to mm. An earlier chain operation's endpoint is not the next entry surface.
See [cutting data](cutting-data.md) for row selection and unresolved-depth behavior.

`separation` is a supported dimension/tolerance field: for example,
`requirements = ["separation"]` with `separation = [9.9, 10.1]` declares a band
that needs its own `checks.separation` inspection gauge. Supplying
`separation = "unknown"` preserves the requirement without inventing its limits;
omitting a listed `separation` value is bad input.

Printed freeform recording areas attach to existing `feature:requirement`
identities and usable authored limits. Equal displayed bands alone are not proof
of a shared physical reading; a genuinely shared dimension remains one record.
The layout does not fill omitted identities or unknown
bands with nominal values, invented tolerances or result data; those debts stay
visible. Handwritten readings do not amend the manifest.

General vectors conventionally have three components and bands two; the model
does not enforce every vector length or dimension-band ordering. Frame vectors
are stricter: each supplied numeric/list origin or basis has exactly three
components. Fully known basis axes must be orthonormal and right-handed:
dot products equal the identity and `x cross y = z`, within absolute `1e-9`.
Invalid known frames are bad input (exit 3), not unknown findings. Unknown
components defer the basis check rather than substituting an identity.

Frames give `origin` and basis `x/y/z`; `binding = "unknown"` preserves nominal
geometry without certifying a measured setup. Frame names are not drawing datum
names. Drawing datums map to actual features/surfaces through `datums`,
`datum`, `position_datums`, `surface_profile_datums`, `coaxial_to` and
`height_from`. `faces` is the
feature's STEP face set: a list of face references that the M4 kernel maps to
faces of the imported solid by each referenced `ADVANCED_FACE`'s own geometry
(surface kind, area, bounding box), never by assuming the importer preserves
STEP ordinal order. A reference that is malformed, missing from the STEP, or
matches zero or several imported faces is a mapping error (`✗`) on every
geometry rule that needs the feature; an omitted, `"unknown"` or empty list
keeps those rules `?`. The M1/M2 declared-input rules read it only through an
already-present kernel result, never starting the kernel: a `kind = "face"`
feature without `bounds` takes its bounded-cut coverage from the matched boxes
of its listed faces, every one of which must resolve; only the planes lying at
the cutting op's `to_z` are covered and credited (see
[coordinates](rules-coordinates.md)). Authored `bounds`, even unknown or
malformed, take precedence. The schema is unchanged.
See [geometry rules](rules-geometry.md#face-identity).

`step_sha256` is `"unknown"` or a lowercase 64-hex SHA-256. A known digest
requires actual referenced STEP bytes in the bundle and must match their hash;
the digest alone is not accepted. Only a bundle with matching bytes reaches the
FreeCAD kernel. The shaft, rocker and cone reference bundles now consume the
consumer's generated manifests and exact adjacent STEP exports. The bracket
keeps a hand-authored `features.toml` on the consumer v39 STEP
(`6cd4ab60f57b1c9771cec083fbbd0ef1f94171f1d95f9485a135a4dec0b2dabc`).
There is no dimensioned bracket drawing, so its acceptance bands are
illustrative example design intent, not measured or imported drawing limits.
Exported face sets, CAD source metadata and citations do not establish
operation coverage, measured setup binding, a physical shop measurement (that
is only an inventory fact's own
[`measured.status = "measured"`](inventory.md#measured-envelopes-and-installed-tool-stacks-m5))
or machining approval.
`cite`, `cite_root`, and per-dimension citations identify evidence and
are not file assets fetched or opened during the check. Python citations use
`file:line` or line ranges; YAML citations use `file:dotted.key.path`.
M3 exports replace the three drawn pilots' handwritten manifests; the bracket's
absence of a dimensioned drawing remains explicit. Preserve source exports,
unknown requirements and omitted optional fields except for user-approved,
labelled [example divergences](../examples/README.md#example-divergences-from-consumer-exports).
These illustrative examples are not verbatim source manifests. Do not silently
backfill facts from superseded handwritten manifests.
Delivery provenance and divergence authority belong beside the examples, not
in extra manifest keys.
Citation collection discards blank and `"unknown"` entries individually, without
losing other known sources in the list. A per-dimension citation map supplies only
the requested fact; whole-record provenance is collected in sorted key order.

The stick-out rule takes its D from the smallest finished profile diameter along
setup Z in the unsupported span, using these authored axial stations and frames.
Unknown exposed stations, diameters or bindings cannot fall back to bar OD.

M2 adds declared lathe profiles (`z_mm` plus a nominal diameter) and angular
settings (`angle_deg`, `angle_tol_deg`). These are sourced nominal geometry,
not kernel-derived access proofs. `finish_ra`, listed in `requirements`, is
what the M4 `finish_coverage` rule reads: every face in that feature's `faces`
must be claimed by a finishing cut. A feature's `angle_tol_deg` is an angular
landing allowance in degrees; it is not the diametral angularity zone.
Every declared indexing position is checked against that allowance. Closure
applies only to a full pattern (`positions >= 2`, `angle_deg` omitted, exact
step `360 / positions`); an authored angle declares an open pattern with no closure.
`angularity_dia = [0.0, 0.10]` with `angularity_datums = ["A", "B"]`, listed in
`requirements`, declares a drawing FCF that needs its own geometric gauge and
datum-referenced inspection method. It does not convert Ø0.10 into degrees.

For an indexing feature with `dimension_type = "basic"`, an omitted
`angle_tol_deg` remains unresolved; it does not inherit the title-block general
angular tolerance. An explicit `angle_tol_deg` remains authoritative, whether
numeric or `"unknown"`; non-BASIC features retain the general-angle fallback.
The current cone export puts the 12.5182° BASIC relationship on `crank_bore`
as `land_angle_nominal_deg`, with Ø0.10 angularity to A/B but no
`angle_tol_deg`. HA already computes `CRANK_BORE_ANGLE_LIMIT_DEG` ≈ 0.0795°
(`cad/scripts/cone_pivot_post_spec.py:373`) but omits it from the export.
Export that derived allowance (or state why it is not an indexing landing
allowance); the consumer neither derives it from the bare FCF nor inherits
the title-block ±1°. The missing field is HA export debt, not a missing source.

The shaft and cone exports leave `frames.setup = "unknown"`. A bare unknown
frame is unbound just like a frame with `binding = "unknown"`. Numeric authored
operation endpoints (`to_z`, `z_from`, `z_to`) remain setup-local Z targets with
`local_from` operation provenance. They do not establish model coordinates or
setup X/Y when the basis is absent, and drawing stations remain unresolved.
Neither retaining a local endpoint nor the exported model frame supplies a
measured setup transform. Setup transforms the CAD export does not carry are
authored in the plan's `frames` table ([plan format](plan.md#frames)); they are
never written back into, merged with or allowed to shadow the exported manifest.

For travel-centre and `coordinates` placement (one shared locator), a child
feature with `parent` or `hole` and no authored `at` inherits the named
parent's `at`, transformed from the parent's source frame. An authored child
`at` takes precedence; explicit `"unknown"`
does not request inheritance. Missing parents/locations/frames remain debt;
dimensions and face claims are not borrowed as a side effect of locating the
child. Saw stock cuts may omit a feature entirely and never establish coverage
or surface-finish credit for a manifest face.

The optional root `volume_mm3` and `volume_cite` hold a sourced finished-part
volume for the generic `compare` command's stock comparison. Missing or
unverified volume remains `"unknown"`;
prechips never substitutes a feature bounding box, guessed cone subtraction,
or stock volume. Drawing `construction = "one_piece"` does not permit a
built-up candidate; permission requires the literal `"built_up_permitted"`.
Unknown or omitted drawing permission retains the one-piece-only restriction;
it never permits built-up construction. A one-piece candidate needs no permission.

All five inputs are UTF-8 TOML, parsed by `tomllib` and strict Pydantic 2
models in `src/prechips/model.py`. Unknown keys are forbidden at every modeled
record (`extra="forbid"`); arbitrary keys are allowed only in explicitly declared
dictionaries (for example feature identities or `checks`). Floats must be finite;
booleans are not numeric substitutes. `Number` means a numeric float or the literal
`"unknown"`; `Vector` means a list of Numbers or `"unknown"`; `Citations` means
a string or a list of strings. Text fields also accept `"unknown"`.

Every `record()` field below is optional and accepts `"unknown"` in addition to
the displayed type. The schema defaults omitted `Feature.kind` to `"unknown"`
and retains it in the loaded bundle so kind-dependent rules remain unresolved.
Other omitted fields stay absent: inspection and policy selection read an
omitted `requirements` declaration as unknown, never as a known empty list.
Other optional fields retain their applicability semantics in the rules.
Root fields marked required must be present. A model accepting a value is not proof
of geometric validity; rules perform the applicable checks.

## Surface profiles

A drawing SURFACE PROFILE `t` (ASME Y14.5 profile of a surface, optionally
`U` unequal disposition, to a datum reference frame) is a set of fields on the
feature whose faces its leader names, like `position_dia`/`position_datums`.
harmonic-analyzer #1544 is the motivation: the rocker's curved edges carry
BASIC `radius 800`, `height_above_pivot 8.0` and `bottom_radius 816` that only
their profile zones tolerance, so without these fields they had no band.

| Field | Meaning |
|---|---|
| `surface_profile` | Total zone width `t` > 0 (manifest units) or `"unknown"`. The feature must list `"surface_profile"` in a known `requirements` list (else bad input); it is inspected as a zone [0, t] like `position_dia`. |
| `surface_profile_u` | Optional `U`, the part of `t` on the side where material is added, 0 <= U <= t, or `"unknown"`. Omitted: equal-bilateral, U = t/2. |
| `surface_profile_datums` | Datum reference frame in precedence order, e.g. `["A", "B", "C"]`; `[]` is a form-only profile. Omitted or `"unknown"`, the zone's inspection and every band it derives stay unknown. |
| `surface_profile_governs` | Table of the BASIC scalar requirements the zone governs: a bare key (`"radius"`) is this feature's requirement, `"feature:requirement"` (`"tip_land_pos_x:station"`) another feature's. Keys match exactly (no wildcards). A governed requirement must be one the inspection rule reads as a dimension: a recognised tolerance requirement ([inspection](rules-inspection.md#inspection), `nominal_dia` included) other than a zone (`position_dia`, `coaxiality_dia`, `angularity_dia`, `finish_ra`). |

A `surface_profile_governs` entry says how the governed BASIC value `n` reads in the zone:

- `"increases"` / `"decreases"`: a BASIC length read along the governed surface's
  normal (a radius about a BASIC centre, a height or station where the surface
  normal is the reading direction) grows or shrinks when material is added at
  the surface. `"increases"` gives [n - (t - U), n + U]; `"decreases"` gives
  [n - U, n + (t - U)]. A concave edge's radius decreases with added material, a
  convex boss's radius increases. A governed BASIC diameter (`dia`,
  `nominal_dia`) spans two radial readings, so each offset counts twice: a boss
  `dia` D with t = U = 0.2 `"increases"` to [D, D + 0.4]; a bore's diameter
  `"decreases"`.
- `{ sense = "increases" | "decreases", obliquity_deg = θ }`, 0 <= θ < 90: the same
  BASIC length read at θ to a planar governed surface's normal at a fixed
  transverse station (the rocker tip land's X station, 10.46° off the land
  normal). Each offset is divided by cos θ.
- `{ tilt_across = "<banded length requirement of the governed feature>" }` or
  `{ tilt_across = <least face extent, manifest units> }`: a BASIC angle (degrees)
  of a planar governed face. The band is n ± asin(t / l_min) in degrees, l_min
  being the named band's lower limit or the number; it does not depend on U.
  When t >= l_min the zone bounds no tilt: unknown. Inspection reads the band as
  the linear zone it is, end to end across l_min (2t wide for one zone), never as
  degrees against a millimetre gauge ([inspection](rules-inspection.md#surface-profiles)).
- `"unknown"`: the governed requirement stays unknown.

The band is **pointwise**: every point of the surface lies in the zone about its
BASIC true profile, located from the DRF, so the reading is taken from the
DRF-located BASIC origin (centre, pivot, station). It is not a fitted-size
tolerance: a best-fit radius of the filed edge is not what it bounds. A
requirement governed by several profiles takes the intersection of their
bands; every band contains `n`, so the intersection is never empty. The
derived band is computed where it is read (`rules/_profile.py`
`requirement_band`); the manifest and every normalised view keep the BASIC
scalar as exported. The inspection rule (checks and process holds), manual-arc
`scribe`/`file_to_line` and datum consistency read it; other band readers,
such as coordinates arc tables, aims and the traveler's printed limits, still
read the exported BASIC value.

The requirement stays unknown, with the reason, when `t`, `U`, the DRF or the
entry is unknown, when the DRF is empty (a datumless profile controls form only,
never a size, location or orientation), when a `tilt_across` band's lower limit
is unknown, or when one of several governing profiles is unresolved. Bad input
(exit 3): `surface_profile_u`, `surface_profile_datums` or
`surface_profile_governs` without `surface_profile`; a zone its feature's
`requirements` does not list (or an omitted/unknown list); t <= 0; U outside [0, t];
a governed key naming a missing feature, or a requirement not listed in that
feature's `requirements`, or one whose value is not a BASIC scalar (a band, an
`"unknown"` or a flag), or one the inspection rule does not read as a dimension (a
zone such as `position_dia`, or a field outside the recognised set such as
`dome_height`, whose derived band no check would read); a sense entry on an angle
(`*_deg`) requirement or a `tilt_across` on a length; a `tilt_across` naming anything
but a listed length band of the governed feature, or a number <= 0; `obliquity_deg`
outside [0, 90).

```toml
["features"."top_edge"]
"requirements" = ["height_above_pivot", "radius", "surface_profile"]
"surface_profile" = 0.5
"surface_profile_u" = 0.5
"surface_profile_datums" = ["A", "B", "C"]
"surface_profile_governs" = { "radius" = "decreases", "height_above_pivot" = "increases" }
# derived: radius [799.5, 800.0], height_above_pivot [8.0, 8.5]

["features"."profile_outer"]
"requirements" = ["bottom_radius", "mirror_symmetric", "surface_profile"]
"surface_profile" = 0.5
"surface_profile_u" = 0.0
"surface_profile_datums" = ["A", "B", "C"]
"surface_profile_governs" = { "bottom_radius" = "increases" }
# derived: bottom_radius [815.5, 816.0]
```

A tip-land angle the outer zone governs would add
`"tip_land_pos_x:land_angle_deg" = { "tilt_across" = "tip_land" }`: tip_land's
least limit 5.08 gives 10.46 ± 5.65°.

## Angle bands read across a face

No gauge reads degrees: an inventory gauge declares millimetre range and
resolution only, so a drawn angle band (`*_deg`, `[lo, hi]` degrees) has no
inspection capability on its own ([inspection](rules-inspection.md#inspection)).
A planar face's angle is read instead as the deviation end to end across the
face, and the optional feature field `tilt_across` declares that length per
angle requirement:

| Field | Meaning |
|---|---|
| `tilt_across` | Table keyed by a listed drawn angle band of this feature (`"land_angle_deg"`). The value is the face extent the angle is read across: a listed length band of the same feature (its lower limit, the least extent) or a number > 0 (manifest units). |

Inspection reads `[lo, hi]` about its mid angle `m` as a linear zone
w = l·(sin(hi − m) − sin(lo − m)) = 2l·sin((hi − lo)/2), the chord between the
band's two extreme faces, with the same reading a profile's `tilt_across` gets.
A band with an unknown end, or a named length whose lower limit is unknown,
stays unknown. The band itself is unchanged; `tilt_across` adds no tolerance.
Bad input (exit 3): a key that is not a listed `*_deg` requirement of the
feature, or one whose value is a BASIC scalar rather than a drawn band (a BASIC
angle reads its tilt through its surface profile's `tilt_across`); a value
naming anything but a listed length band of the feature, or a number <= 0.

```toml
["features"."tip_land_pos_x"]
"requirements" = ["tip_land", "land_angle_deg"]
"tip_land" = [5.08, 6.1]
"land_angle_deg" = [89.0, 91.0]
"tilt_across" = { "land_angle_deg" = "tip_land" }
# inspected: 2 · 5.08 · sin 1° = 0.177 mm wide
```

## Root fields

| Field | Type | Presence |
|---|---|---|
| `part` | `str` | Required |
| `units` | `Literal['mm', 'in'] \| Unknown` | Optional |
| `precision` | `int \| Unknown` | Optional |
| `step_sha256` | `str` | Optional |
| `step` | `str \| Unknown` | Optional |
| `construction` | `str \| Unknown` | Optional |
| `volume_mm3` | `Number` | Optional |
| `volume_cite` | `Citations` | Optional |
| `cite_root` | `str \| Unknown` | Optional |
| `cite` | `Citations \| dict[str, Citations]` | Optional |
| `notes` | `Notes \| Unknown` | Optional |
| `drawing` | `Drawing \| Unknown` | Optional |
| `material` | `MaterialSpec \| Unknown` | Optional |
| `general_tolerances` | `GeneralTolerances \| Unknown` | Optional |
| `frames` | `dict[str, Frame \| Unknown] \| Unknown` | Required |
| `datums` | `dict[str, Datum \| Unknown] \| Unknown` | Optional |
| `features` | `dict[str, Feature]` | Required |

## Drawing

| Field | Type (also accepts `"unknown"`) |
|---|---|
| `number` | `str` |
| `revision` | `str` |
| `cite` | `Citations` |

## MaterialSpec

| Field | Type (also accepts `"unknown"`) |
|---|---|
| `spec` | `str` |
| `name` | `str` |
| `finish` | `str` |
| `thickness` | `Number` |
| `cite` | `Citations` |

## Notes

| Field | Type (also accepts `"unknown"`) |
|---|---|
| `manufacturing` | `list[str]` |
| `process` | `str` |
| `edge_break` | `str` |
| `cite` | `Citations` |

## GeneralTolerances

| Field | Type (also accepts `"unknown"`) |
|---|---|
| `linear_1pl` | `float` |
| `linear_2pl` | `float` |
| `linear_3pl` | `float` |
| `angular_deg` | `float` |
| `drilled_hole` | `float` |
| `drilled_hole_plus` | `float` |
| `drilled_hole_minus` | `float` |
| `edge_break_r` | `float` |
| `chamfer_max` | `float` |
| `cite` | `Citations \| dict[str, Citations]` |

## Frame

| Field | Type (also accepts `"unknown"`) |
|---|---|
| `origin` | `FrameVector` (three Numbers or `"unknown"`) |
| `x` | `FrameVector` (three Numbers or `"unknown"`) |
| `y` | `FrameVector` (three Numbers or `"unknown"`) |
| `z` | `FrameVector` (three Numbers or `"unknown"`) |
| `note` | `str` |
| `binding` | `str` |
| `cite` | `Citations` |

## Datum

| Field | Type (also accepts `"unknown"`) |
|---|---|
| `feature` | `str` |
| `surface` | `str` |
| `cite` | `Citations` |

## Feature

| Field | Type (also accepts `"unknown"`) |
|---|---|
| `kind` | `str` |
| `frame` | `str` |
| `drill` | `str` |
| `process` | `str` |
| `datum` | `str` |
| `coaxial_to` | `str` |
| `height_from` | `str` |
| `note` | `str` |
| `binding` | `str` |
| `dimension_type` | `str` |
| `thread` | `str` |
| `construction` | `str` |
| `representation` | `str` |
| `hole_spec` | `str` |
| `arc` | `str` |
| `parent` | `str` |
| `hole` | `str` |
| `top_edge_feature` | `str` |
| `requirements` | `list[str]` |
| `faces` | `list[str]` |
| `cite` | `Citations \| dict[str, Citations]` |
| `precision` | `dict[str, int \| Unknown]` |
| `position_datums` | `list[str]` |
| `angularity_datums` | `list[str]` |
| `surface_profile_datums` | `list[str]` |
| `surface_profile_governs` | `dict[str, ProfileEntry]` (`"increases"`, `"decreases"`, `"unknown"`, `{ sense, obliquity_deg }` or `{ tilt_across }`; see [Surface profiles](#surface-profiles)) |
| `tilt_across` | `dict[str, str \| float]` (drawn angle band → face extent it is read across; see [Angle bands read across a face](#angle-bands-read-across-a-face)) |
| `surface_profile` | `float` (> 0) |
| `surface_profile_u` | `float` (0 <= U <= `surface_profile`) |
| `thru` | `bool` |
| `mirror_symmetric` | `bool` |
| `at` | `Vector` |
| `axis` | `Vector` |
| `normal` | `Vector` |
| `at_reference` | `Vector` |
| `plane` | `Plane` |
| `bounds` | `Bounds` |
| `z_mm` | `Vector` |
| `end` | `Vector` |
| `arc_centre` | `Vector` |
| `bottom_end` | `Vector` |
| `angle_deg` | `Number` |
| `angle_tol_deg` | `Number` |
| `radial_tip_end` | `Vector` |
| `dia` | `float \| list[Number]` |
| `position_dia` | `float \| list[Number]` |
| `angularity_dia` | `float \| list[Number]` |
| `finish_ra` | `float \| list[Number]` |
| `depth` | `float \| list[Number]` |
| `length` | `float \| list[Number]` |
| `width` | `float \| list[Number]` |
| `height` | `float \| list[Number]` |
| `radius` | `float \| list[Number]` |
| `thickness` | `float \| list[Number]` |
| `coaxiality_dia` | `float \| list[Number]` |
| `height_above_pivot` | `float \| list[Number]` |
| `arc_len` | `float \| list[Number]` |
| `bottom_radius` | `float \| list[Number]` |
| `bottom_arc_len` | `float \| list[Number]` |
| `tip_land` | `float \| list[Number]` |
| `land_angle_deg` | `float \| list[Number]` |
| `land_angle_nominal_deg` | `float \| list[Number]` |
| `upper_z` | `float \| list[Number]` |
| `lower_z` | `float \| list[Number]` |
| `centre_from_pivot_ref` | `float \| list[Number]` |
| `depth_ref` | `float \| list[Number]` |
| `station` | `float \| list[Number]` |
| `nominal_dia` | `float \| list[Number]` |
| `nominal_width` | `float \| list[Number]` |
| `nominal_length` | `float \| list[Number]` |
| `nominal_height` | `float \| list[Number]` |
| `nominal_radius` | `float \| list[Number]` |
| `nominal_thickness` | `float \| list[Number]` |
| `length_ref` | `float \| list[Number]` |
| `dome_height` | `float \| list[Number]` |
| `groove_width` | `float \| list[Number]` |
| `groove_depth` | `float \| list[Number]` |
| `dia_nominal` | `float \| list[Number]` |
| `length_nominal` | `float \| list[Number]` |
| `width_nominal` | `float \| list[Number]` |
| `height_nominal` | `float \| list[Number]` |
| `thickness_nominal` | `float \| list[Number]` |
| `radius_nominal` | `float \| list[Number]` |
| `station_nominal` | `float \| list[Number]` |
| `through_thickness` | `float \| list[Number]` |
| `z_south_reference` | `float \| list[Number]` |
| `corner_radius_max_design` | `float \| list[Number]` |
| `apex_z` | `float \| list[Number]` |
| `base_z` | `float \| list[Number]` |
| `base_radius` | `float \| list[Number]` |
| `sphere_radius` | `float \| list[Number]` |
| `apex_z_reference` | `float \| list[Number]` |
| `base_z_reference` | `float \| list[Number]` |
| `length_reference` | `float \| list[Number]` |
| `cut_past_scribe` | `float \| list[Number]` |
| `end_past_scribe` | `float \| list[Number]` |
| `supply_length` | `float \| list[Number]` |
| `tap_drill_mm` | `float \| list[Number]` |
| `bottom_radius_nominal` | `float \| list[Number]` |
| `separation` | `float \| list[Number]` |

## Plane

| Field | Type (also accepts `"unknown"`) |
|---|---|
| `frame` | `str` |
| `axis` | `str` |
| `value` | `Number` |

## Bounds

| Field | Type (also accepts `"unknown"`) |
|---|---|
| `x` | `Vector` |
| `y` | `Vector` |
| `z` | `Vector` |
