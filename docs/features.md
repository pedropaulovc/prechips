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
`separation` is a supported dimension/tolerance field: for example,
`requirements = ["separation"]` with `separation = [9.9, 10.1]` declares a band
that needs its own `checks.separation` inspection gauge. Supplying
`separation = "unknown"` preserves the requirement without inventing its limits;
omitting a listed `separation` value is bad input.
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
`datum`, `position_datums`, `coaxial_to` and `height_from`. `faces` is the
feature's STEP face set: a list of face references that the M4 kernel maps to
faces of the imported solid by each referenced `ADVANCED_FACE`'s own geometry
(surface kind, area, bounding box), never by assuming the importer preserves
STEP ordinal order. A reference that is malformed, missing from the STEP, or
matches zero or several imported faces is a mapping error (`✗`) on every
geometry rule that needs the feature; an omitted, `"unknown"` or empty list
keeps those rules `?`. The M1/M2 declared-input rules still do not read it.
See [geometry rules](rules-geometry.md#face-identity).

`step_sha256` is `"unknown"` or a lowercase 64-hex SHA-256. A known digest
requires actual referenced STEP bytes in the bundle and must match their hash;
the digest alone is not accepted. Only a bundle with matching bytes reaches the
FreeCAD kernel. The shaft, rocker and cone reference bundles now consume the
consumer's generated manifests and exact adjacent STEP exports. The bracket
remains hand-authored without STEP bytes, so its geometry rows remain `?`.
Exported face sets do not establish operation coverage, measured setup binding
or machining approval.
`cite`, `cite_root`, and per-dimension citations identify evidence and
are not file assets fetched or opened during the check. Python citations use
`file:line` or line ranges; YAML citations use `file:dotted.key.path`.
M3 exports replace the three drawn pilots' handwritten manifests; the bracket's
missing drawing contract remains explicit. Preserve exports verbatim, including
unknown requirements and omitted optional fields: do not backfill facts from
the superseded hand-authored manifests. Delivery provenance belongs in
[examples/README.md](../examples/README.md), not extra manifest keys.
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
`angle_tol_deg`. Neither the BASIC nominal nor that diametral zone supplies a
degree-based indexing acceptance band.

The shaft and cone exports leave `frames.setup = "unknown"`. A bare unknown
frame is unbound just like a frame with `binding = "unknown"`. Numeric authored
operation endpoints (`to_z`, `z_from`, `z_to`) remain setup-local Z targets with
`local_from` operation provenance. They do not establish model coordinates or
setup X/Y when the basis is absent, and drawing stations remain unresolved.
Neither retaining a local endpoint nor the exported model frame supplies a
measured setup transform. Setup transforms the CAD export does not carry are
authored in the plan's `frames` table ([plan format](plan.md#frames)); they are
never written back into, merged with or allowed to shadow the exported manifest.

The optional root `volume_mm3` and `volume_cite` hold a sourced finished-part
volume for stock comparison. Missing or unverified volume remains `"unknown"`;
prechips never substitutes a feature bounding box, guessed cone subtraction,
or stock volume. Drawing `construction = "one_piece"` does not permit a
built-up candidate; permission requires the literal `"built_up_permitted"`.
Unknown or omitted drawing permission retains the one-piece-only restriction;
it never permits built-up construction. A one-piece candidate needs no permission.

In particular, the current cone export omits `volume_mm3` and `volume_cite`.
Its comparison therefore has unknown finished volume/waste despite the older
hand-authored fixture's analytic-volume citation. The export's `construction`
remains `"one_piece"`; the separately authored built-up candidate is still refused.

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
