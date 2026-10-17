# Plan format — `plan.toml`

`part`, `features`, and `setups` are required. The loader additionally requires
a nonempty setup list, known unique setup ids, a nonempty operation list per
setup and known unique operation numbers within each setup. A saw stock cut may
omit `feature`; every authored feature must be in the manifest, in plan-owned
`joint_features` or in plan-owned `process_features`, and inspection checks need a named feature. Plan and manifest
part names must agree; a known setup frame must name an exported manifest frame
or a plan-owned frame in [`frames`](#frames). A literal `"unknown"` setup frame
stays unresolved.
Execution follows authored array order, not numeric sorting of operation ids.

`features` is relative to the plan; it must stay inside the bundle root. The
root is the repository above `examples` or the first ancestor with
`pyproject.toml`, otherwise the plan's parent. Shared input precedence is CLI
override, then a known `[paths]` declaration, then `PRECHIPS_INVENTORY` or
`PRECHIPS_POLICY`; cutting data has no environment fallback. An omitted or
literal `"unknown"` declaration permits the environment fallback. Missing policy
uses the shipped required-rule vocabulary only when no known path is selected.
Plan-declared shared paths must stay inside
the bundle root; explicit CLI/environment shop paths may be external. STEP references are read and hashed, contained
inside the bundle, and checked against a known `step_sha256`. M4 geometry rules
hand that STEP, once its bytes match the manifest digest, to one FreeCAD job per
run; an unknown digest, a missing `step`, or mismatched bytes keeps all eight
geometry rules `?`. See [geometry rules](rules-geometry.md).

Use `[[setups]]` and `[[setups.ops]]`. `stock_state` records received surfaces in
the setup frame; `local_thickness` is per hole, not the whole bar thickness.
`top_feature` identifies the touched face that facing advances; `top_z` is then
that feature's +Z face. A facing op with `stock_removal_bounds` advances it only
when the box holds that feature's whole X/Y footprint: its `bounds`, or for a
bounds-free `kind = "face"` the matched kernel box of each listed plane at the
op's `to_z`, with every listed face resolved and any `contour.keep_out` island
clear of the face by the cutter radius
([coordinates](rules-coordinates.md)). `bottom_feature` likewise names the seated face: `bottom_z`
is that feature's -Z face. The kernel gives each named face's height and the
entering stock's over it, and [consistency](rules-setup.md#consistency) compares
them with `top_z` / `bottom_z`. `entry_z` permits
a separate local entry surface. `zero.transfer` describes a pickup from another
setup, and `tool_touches` explicitly records tool changes. Neither invents a
measured trial-cut diameter.

Setup frames, stock state and authored operation bounds supply the geometry and spans used for picture scale under [render geometry](rules-geometry.md#renders).
The [traveler render binding](report-and-telemetry.md#kernel-renders) preserves main's accepted leader placement and all original ordinary-tolerance layout and anchor inputs; a separate bounded stream is used only for outline painting. [#211](https://github.com/pedropaulovc/prechips/issues/211) stays open for a dedicated future leader PR. This adds no plan field and changes no authored setup coordinates, zero recipes or operation values.

Every zero recipe's `edge_mm` is the authored pickup coordinate in the setup
frame. A Z recipe with `face = "top"` uses the stock state's top; other named
faces require their own explicit `edge_mm`, not the stock top or a value copied
from report output. X/Y raw-overhang pickups likewise use their authored edges.
The Z pickup's `retouch_after` may declare a known operation list or `"unknown"`.
Omission and literal `"unknown"` leave the schedule unresolved, so a required
`zero_check` cannot pass merely because no rows were declared. An explicit
`retouch_after = []` means a known empty schedule; a known nonempty list produces
retouch rows using the stock top after each listed operation, including a face
cut that changes the touched top; each serves the next tool. A known list does not
certify the schedule: `zero_check` derives a touch for every other tool change from
the setup's standing touched or faced surfaces, or reports it missing as an error
([coordinates and DRO zero](rules-coordinates.md#zero_check)). Z
`method = "measure_then_set"` (with `gauge`, `measure`, `offset_mm`; on a tool
touch `z_gauge`, `z_measure`, `z_offset_mm`) sets a measured edge, M + offset +
paper. On a mill setup's `top` the raw top then reads Z = M + offset while the ops'
levels start from `stock_state.top_z`; the DRO ZERO prints that correction: face a
higher top down to `top_z` first, no deeper per pass than the setup's least op
`doc_mm`, in plan units rounded down onto the DRO grid (unknown plan units print
no cap).

`checks` maps requirement names to inventory gauge references. Every key must
belong to the selected resolved feature's `requirements` list (exported or
plan-owned); otherwise loading raises `BadInput`, even if another feature owns that name.
A wholly unknown requirements list cannot establish membership and does not
authorize arbitrary checks. `inspection_methods` supplies the authored procedure
for datum/geometric checks and missing requirements. A missing check is different
from `checks.dia = "unknown"`.

An `inspection_methods.<requirement>` procedure and an op's `inspection_note`
are each either one string or a non-empty list of strings. A string prints as
before (blank-line paragraphs become `(1)…(2)…`). A list prints as numbered steps
in the INSPECTION NOTES, for procedures a machinist follows and records as they go:

```toml
inspection_methods.position_dia = [
  "Pin the rod hole with the 4.000 gauge pin; zero the indicator on datum A.",
  "Read X at the pin: {X1}",
  "Read Y at the pin: {Y1}",
  "Calculate: position Ø = 2 × √((X1 − 133.067)² + (Y1 + 8.456)²) = {result}",
]
```

`{name}` normally prints as a labelled blank on its own line in prose. Worksheet
and calculation fields remain single fields, not duplicate prose boxes. A step
beginning `Calculate:` prints apart from the numbered steps. Only an authored
step-list procedure with named brace readings in its steps and at least two
calculation lines becomes a worksheet on an attached logical sheet after the
contours (the op row names it, `[S11 sheet 4 worksheet]`). Its original numbered
steps use references such as `[rJ1]`, without duplicate value boxes; READINGS
provides one value box per named reading with its source step. Original equations
and calculation fields print once. Standalone underscores do not count as named
worksheet readings. A list is known only when every step is a non-empty string
other than `"unknown"`.

An inspect op may illustrate a stated procedure with set-up sketches:
`inspection_views.<requirement>` is a non-empty list of views, one per way the
part is set up on the surface plate for that check. Each view gives a `title`,
`up` (a unit vector in the part model's axes pointing up off the plate, the way
a height reading rises), `toward` (a unit vector square to `up`, from the part to
the viewer), optional `aids` and at least one `mark`, all in part-model
millimetres:

```toml
[[setups.ops.inspection_views.position_dia]]
title = "VIEW 1: BOX ON ITS BASE, LAND C DOWN ON THE STOP BAR"
up = [-0.9833816999, -0.1815500823, 0.0]
toward = [0.0, 0.0, -1.0]
aids = [
  { name = "C STOP BAR", shape = "box", at_mm = [155.526, 40.78, 1.25], size_mm = [40.0, 12.2, 12.0], axes = [[0.1815500823, -0.9833816999, 0.0], [-0.9833816999, -0.1815500823, 0.0]] },
  { name = "ROD GAUGE PIN", shape = "cylinder", at_mm = [133.067, 16.456, -25.0], axis = [0.0, 0.0, 1.0], dia_mm = 1.994, length_mm = 26.2 },
]
marks = [
  { label = "R1: ROD PIN TOP", at_mm = [132.087, 16.275, -5.0], reads = true },
  { label = "C: LAND C ON THE STOP BAR", at_mm = [145.747, 26.547, 0.0] },
]
```

An aid is a `box` from its least corner `at_mm` by `size_mm` along its edge
directions `axes` (unit x then y, square; the model's X and Y when absent), or a
`cylinder` from its base centre `at_mm` along the unit `axis`, `dia_mm` across
and `length_mm` long. A mark is a labelled point; `reads = true` marks where a
height reading is taken. The kernel draws the sketch on the stock the op's setup
leaves ([renders](rules-geometry.md#renders)) and the traveler prints it at the
head of that requirement's worksheet or inspection note
([report binding](report-and-telemetry.md#kernel-renders)). Views on an op that is
not `inspect`, or for a requirement with no flat `inspection_methods` entry, are
`BadInput`: views are keyed by requirement alone, so a requirement whose method is
scoped per feature has none.

The traveler retains every authored view, in list order, with its own `title`.
Each view prints as a complete figure attached once to the original requirement's
worksheet or note. Continuations may move the figure whole and repeat applicable
context, without duplicating reading or calculation fields. This layout adds no
plan fields and changes no authored procedure.

When an inspection requirement has no exported owner/band, an explicit operation
may declare `missing_requirements = { length = "calipers" }` and
`inspection_methods.length`. This uses the same gauge-reference mapping type as
`checks`, but produces a named unknown inspection row with
`missing_requirement = true`, not an acceptance band or a dimensional pass.
The sheet prints `?`, the exact missing requirement identity and the authored
procedure; reference-only dimensions such as `length_ref` are not substitutes.
A name already in that feature's exported requirements is `BadInput` in
`missing_requirements`; use `checks` so actual requirements cannot be bypassed.

Paper records use the existing requirement-keyed `checks` and authored methods;
they add no plan fields. One full-width freeform readings/observations area
remains below each real requirement with its known owner(s), limits, gauge,
method and authored context. It does not infer reading positions or counts.
Authored `{name}` blanks remain separate named procedure fields, not invented
samples or statistical summaries. Missing identities or bands remain visible
as unresolved `?` instructions, without fabricated automatic measurement fields.

`to_z` is an authored endpoint;
`to_z_band` is a range, not a substitute for measured setup binding. An arc
contour needs explicit nominal geometry and one of the manual-arc methods
([Manual arcs](#manual-arcs)); finite bounds come from that geometry, not an
invented full circle. Linear
pockets and faces may declare `sweep_bounds`, `sweep_frame`, `open_side`, and
circular `keep_out` islands; their rasters need `step_mm`
(see [rules-coordinates](rules-coordinates.md)).

All five inputs are UTF-8 TOML, parsed by `tomllib` and strict Pydantic 2
models in `src/prechips/model.py`. Unknown keys are forbidden at every modeled
record (`extra="forbid"`); arbitrary keys are allowed only in explicitly declared
dictionaries (for example feature identities or `checks`). Floats must be finite;
booleans are not numeric substitutes. `Number` means a numeric float or the literal
`"unknown"`; `Vector` means a list of Numbers or `"unknown"`; `Citations` means
a string or a list of strings. Text fields also accept `"unknown"`.

Every `record()` field below is optional and accepts `"unknown"` in addition to
the displayed type. The schema defaults omitted `Setup.machine` and
`Operation.do` to `"unknown"` and retains those keys in the loaded bundle so
rules can report unresolved identity/applicability rather than crash. Other
omitted fields stay absent: `zero_check` reads an omitted `retouch_after` as
unknown rather than an empty list, and other rules retain optional-field
applicability semantics.
Root fields marked required must be present. A model accepting a value is not proof
of geometric validity; rules perform the applicable checks.

## Root fields

| Field | Type | Presence |
|---|---|---|
| `part` | `str` | Required |
| `features` | `str` | Required |
| `construction` | `Literal['one_piece', 'built_up'] \| Unknown` | Optional |
| `step` | `str \| Unknown` | Optional |
| `quantity` | `int \| Unknown` | Optional |
| `quantity_cite` | `Citations` | Optional |
| `drawing` | `Drawing \| Unknown` | Optional |
| `paths` | `Paths \| Unknown` | Optional |
| `stock` | `Stock \| Unknown` | Optional |
| `dro` | `Dro \| Unknown` | Optional |
| `frames` | `dict[str, PlanFrame] \| Unknown` | Optional |
| `aims` | `dict[str, Aim]` | Optional |
| `joint_features` | `dict[str, JointFeature]` | Optional |
| `process_features` | `dict[str, ProcessFeature]` | Optional |
| `setups` | `list[Setup]` | Required |

## Frames

`[frames.<name>]` declares an author-owned setup frame for a setup transform the
CAD export does not carry. Its fields are the manifest
[`Frame`](features.md#frame) fields, with the same three-component,
orthonormal, right-handed basis checks: `origin` and `x/y/z` are in the model
frame. Two fields that the manifest may omit are required here, because the
plan, not the CAD export, owns the choice:

- `binding` must be stated, if only as `"unknown"`. `"nominal"` lets the
  transform place model geometry in setup coordinates; `"unknown"` keeps the
  numeric transform for display while operation Z endpoints stay setup-local.
- `cite` must be non-empty. The bundled examples begin it, and the `note`, with
  `AUTHOR'S CHOICE` before the drawing/model citations the transform rests on.

A setup's `frame` resolves to the exported manifest frame of that name, otherwise
to the plan frame. A plan frame whose name is already exported (including an
exported `"unknown"` frame such as `setup`) is bad input, so a plan can never
shadow CAD-owned geometry. Feature `frame` references and `sweep_frame` stay
manifest-only. Plan frames are never merged into the manifest or its hash; rule
citations carry `plan.frames.<name>: author-declared setup frame` followed by
the frame's own `cite`, while exported setup frames keep their manifest
provenance.

## Aims

`[aims.<feature>]` holds one drawing requirement at a stated value inside its
printed band: a process choice. Without `face` it moves one located feature's
DRO target off its drawing nominal so that a height-like band it holds from its
`height_from` reference (`height_above_pivot`, `height` or `separation`) reads
that value. That form changes only the printed target, never the STEP, the
manifest, a cutting claim or a kernel input. With `face` it holds a faced
length: the part the kernel cuts has that face moved so that the length between
the feature's `lower_z` and `upper_z` planes reads the value.

| Field | Meaning |
|---|---|
| `requirement` | The requirement the aim sets. It must be one of the feature's exported drawing requirements |
| `value_mm` | The value, in mm, that the requirement reads at the aim. It must lie inside the printed band |
| `reason` | Known text. The bundled examples begin it with `AUTHOR'S CHOICE` |
| `face` | Optional. The faced plane that moves, a ref from the feature's own `faces` |

The `<feature>` must be a manifest feature that exports `requirement`.
`value_mm`, converted to the manifest units, must lie inside that requirement's
band as the sheet prints it. Anything else is bad input.

**Target aims (no `face`).** The
[`coordinates`](rules-coordinates.md#coordinates) rule moves the feature's own
target along the band's measuring direction in every setup that locates it,
then checks the target against the printed band where the features stand:

- the DRO-rounded target, where that setup machines the feature (a centre op
  names it);
- the planned point, where the setup only inspects it.

The distance is measured from the reference's own printed target when the same
setup machines the reference, else from the reference's planned point. The
finding cites `plan.aims.<feature>`. The sheet's feature map prints the aimed
target with the drawing nominal and the reason. These aims stay unknown and move
nothing:

- an aim on a feature without that band;
- an aim on a feature no mill setup's centre op (a hole op or `center`) names;
- an aim under unknown units;
- an aim whose distance cannot be measured.

An aim on a child located by its parent's `at` is refused (unknown). The child
still dials its parent's target, aimed or not.

**Faced aims (`face`).** Loading also needs:

- `face` listed in the exported feature's `faces`;
- the feature to declare `lower_z` and `upper_z`, the planes in its frame that
  the faced length runs between;
- a facing op (`face`, `rough_face` or `finish_face`) on the feature to claim
  `face`, either by omitting `faces` (the feature's default claims) or by
  explicitly naming that face in a list. `faces = "unknown"` or a list
  containing only `"unknown"` cannot authorize movement. A known explicit
  face still authorizes that faced aim when another entry is `"unknown"`.
  This does not resolve the whole non-rotary coverage or finish-coverage claim:
  a mixed known/unknown list leaves that claim unresolved.

Anything else is bad input. The kernel job gets:

- the face;
- the feature frame's Z, as a model axis;
- both planes, in mm;
- `value_mm`;
- the requirement's printed band, in mm;
- `delta_mm`, which is `value_mm` minus the planes' separation.

The kernel then builds the part the plan cuts:

- The aimed face must be a plane on one of the two declared planes, facing away
  from the other one. It moves `delta_mm` along its outward normal. A zero move
  leaves it where it is.
- Every neighbouring face runs square to the face (a plane along its normal, or
  a cylinder about it). Each one runs on to the moved face or is cut back to it,
  so every face keeps its index.
- The result must equal the STEP solid plus (or minus) the face's prism.
- The aims compose. On the part every move makes, each aimed face must stand on
  its aimed plane. The length's other end is every face on the other plane that
  faces the other way, and each of those faces must still stand where it was.
  The length between the two ends must read `value_mm` inside the band. So an
  aim that moves another aim's face, or the other end of its length, fails both
  lengths. Two features aiming the two faces of one thickness are such a pair.
  Loading cannot refuse such a pair as bad input, because only the kernel knows
  which plane a face lies on.

Every setup's protected part, removal bounds, in-process stock, clearances,
pictures and stock facts stand on that one face position. A frame and zero on
the aimed face therefore agree with what the earlier setup leaves. The aimed
value stays inside the printed band, and the finished part is the one the aim
makes.

The kernel result keeps `faces` and `bbox_mm` as the STEP exports them, and
lists each moved face under `aimed_faces` with its feature, ref, index,
`delta_mm` and its plane before and after, in mm along the axis. Other cases
leave the whole kernel result unknown with the reason:

- unknown units, printed band, planes or frame. No known band authorizes a move;
- a declared `<requirement>_nominal` that is not the planes' separation;
- an aimed face that is unmapped, not planar, or on neither plane;
- no face on the other plane facing the other way, so the length has no other
  end;
- a neighbour that does not run square to the face;
- a move that does not give one valid solid;
- aims that move each other's faces or other ends.

Faced aims move no DRO target. Aim each face whose position follows from the
aimed one. In the rocker example, the strap thickness is the hub aim less two
fixed hub-proud steps, so the strap face carries its own aim.

The sheet prints each faced aim once, in the instructions of the last facing op
that claims its face: the feature's requirement "faced to" `value_mm` (at no
fewer places than the drawing's), the band that holds it, and the reason. For
example: `Hub faces length faced to 7.080 (band 7.057–7.106): AUTHOR'S CHOICE …`.

## Joint features

`[joint_features.<id>]` declares transient component geometry, not a change to
the finished STEP or its feature manifest. Identities must not collide with
exported features. Every declaration requires:

| Field | Meaning |
|---|---|
| `kind` | `cylinder_bore` (socket) or `cylinder_spigot` |
| `component` | Exact declared stock component id |
| `at` | Starting-face centre in model coordinates |
| `axis` | Unit vector along positive depth |
| `dia` | Ordered positive diameter tolerance band `[low, high]` |
| `nominal_dia` | Authored cylinder diameter; never inferred from band midpoint |
| `depth` | Positive finite axial length, including when `thru = true` |
| `thru` | Boolean through/blind declaration |
| `cite` | Nonempty author/source citation |

Unsuffixed lengths use the manifest's model units; `axis` is dimensionless.
Known geometry must satisfy these constraints. Literal numeric `"unknown"`
remains debt and cannot create a solid, an inferred nominal, or a successful
assembly. Identity fields and citations are not numeric debt: missing/unknown
kinds, components and references are bad input. Optional `requirements` is a
subset of `["dia"]` and defaults to that list; depth is finite construction
geometry, not an invented depth tolerance. Optional `precision` and `note`
retain normal dimensional/display semantics.

Operations address these identities through the same resolved feature mapping
as exported dimensions (socket as hole, spigot as boss), but may prepare them
only on their own pre-assembly component ancestry. The original manifest and
STEP hashes remain unchanged. Findings cite `plan.joint_features.<id>` and the
author's citations, not invented exported faces. Completing a transient cut
earns no finished STEP coverage or final finish coverage by itself. A finishing
spigot turn earns both only for the exported faces the kernel measures it
leaves as its own turned surface, over their full area inside its finite
window (see [geometry rules](rules-geometry.md#face-identity)). A separate
pass on the exported feature is then unnecessary.
Inspection, fitting and other noncutting actions do not prepare or invalidate
a joint feature. Socket drill/ream/bore and spigot turning actions derive their
actual removal; spotting does not complete a socket. Transient `tap` and
`counterbore` operations leave named geometry debt until thread/step profiles
are supported. A rough cut's allowance must be removed by a valid finishing
cut before the selected branch can supply completed preparation to a join.
A drilled socket also needs a representable finite point cone from its selected
tool's included point angle. An underflowed zero tangent or nonfinite cone
leaves the socket profile, completed preparation and dependent join unresolved;
it does not become a flat-bottomed socket or borrow a CAD profile.

## Process features

`[process_features.<id>]` declares stock preparation the route makes and later
relies on, never a drawing surface: a faced end (`end_face`) or a combined drill
and countersink centre (`centre_hole`) that a later setup's dead or live centre
rides in.
Identities must not collide with exported or joint features, and nothing may name
a `plan.process_features.` label as a face reference.

| Field | Meaning |
|---|---|
| `kind` | `end_face` or `centre_hole` |
| `at` | Point on the stock end, model coordinates (manifest units); a centre's mouth centre, on the entry surface its quill is touched on |
| `axis` | Unit inward normal of that end, pointing into the kept material (the drilling direction) |
| `cite` | Nonempty author/source citation |
| `size` | `centre_hole` only: the source's size name |
| `drill_dia_mm` | `centre_hole` only: pilot drill diameter D |
| `drill_length_mm` | `centre_hole` only: pilot length C from the countersink to the tip, point included |
| `mouth_dia_mm` | `centre_hole` only: countersink diameter at the face; must exceed `drill_dia_mm` |
| `countersink_angle_deg` | `centre_hole` only: included countersink angle, between 0 and 180 |
| `note` | Optional text |

A `centre_hole` needs every centre field (each may be `"unknown"` debt); an
`end_face` authors none. The centre's feed depth below its faced end is
`drill_length_mm + (mouth_dia_mm - drill_dia_mm) / 2 / tan(countersink_angle_deg / 2)`:
the Machinery's Handbook Table 6 drill length C plus the countersink that opens to
the mouth. The centre is its `center_drill` op's selected tool: D, C and the
angle must be that tool's `dia`, `pilot_len` and `angle_deg`, the mouth no
wider than its body (`shank`), and its pilot `point_angle` must give a point
shorter than C; its mouth must lie on the surface the quill is touched on, fed
along setup -Z ([`blind_depth`](rules-operations.md#blind_depth-tip-endpoints)).
A mismatch is an error, and any unknown or unaccepted size or tool fact, or an
unconfirmed tool record, leaves the depth unknown and the centre uncut.

An `end_face` is any planar face of the stock: a turned end, or one of the six
faces of a rectangular blank a mill squares before S1. On a rectangular root stock
square to the model axes, each `end_face` square to a model axis carries derived
`bounds`: the root stock's section in that plane. A later setup's footprint of the
face is those bounds trimmed by every process face an earlier setup in its stock
lineage made, so a blank face is always cut whole. Round, built-up or unaligned
stock gets no derived bounds.

`face`, `rough_face` and `finish_face` prepare an `end_face`; on a mill
`profile`, `rough_profile` and `finish_profile` also prepare one, side-milled with
the cutter's periphery (a blank end overhanging the vise; give the op's
`linear_table` contour an `open_side` so its passes step in from clear air, see
[rules-coordinates](rules-coordinates.md)). Only `center_drill` prepares a
`centre_hole`. Such an op names exactly that one
feature and carries no `faces`, `checks` or `missing_requirements`: there is no
drawing limit to inspect. Process ops resolve through the same rules as other
cuts (speeds and feeds, reach, accessibility, headroom, tip endpoints, holding and
the fixture model), and the kernel removes the analytic centre (countersink, pilot
and drill point) or cuts the face away as a planar slab of the arriving stock so
the setup picture and the next setup's entry stock show them. They
earn no finished STEP coverage and no finish coverage, even when the cut lies on a
drawing plane, and a process feature is never a drawing-requirements row. A
hold's `centre_hole` names the process centre its dead or live centre rides in
(see [Hold](#hold)); the squared blank the faces make is declared in
[`stock.prepared`](#prepared-blank).

## Drawing

| Field | Type (also accepts `"unknown"`) |
|---|---|
| `number` | `str` |
| `revision` | `str` |
| `cite` | `Citations` |

## Paths

| Field | Type (also accepts `"unknown"`) |
|---|---|
| `inventory` | `str` |
| `policy` | `str` |
| `cutting_data` | `str` |
| `step` | `str` |

## Stock

| Field | Type (also accepts `"unknown"`) |
|---|---|
| `form` | `str` |
| `material` | `str` |
| `drawing_material` | `str` |
| `note` | `str` |
| `supply_datum` | `str` |
| `prerequisite` | `str` |
| `dia_mm` | `float` |
| `length_mm` | `float` |
| `north_allowance_mm` | `float` |
| `south_grip_mm` | `float` |
| `supply_length_mm` | `float` |
| `material_verify` | `bool` |
| `form_verify` | `bool` |
| `on_hand` | `bool` |
| `material_cite` | `Citations` |
| `section_mm` | `Vector` |
| `origin_mm` | `Vector` |
| `axis` | `Vector` |
| `section_axis` | `Vector` |
| `as_is_faces` | `list[str]` |
| `components` | `list[StockComponent]` |
| `prepared` | `PreparedBlank` ([Prepared blank](#prepared-blank)) |
| `blank` | `ProfiledBlank` ([Profiled blank](#profiled-blank)) |
| `cite` | `Citations` |

For a built-up stock candidate, `components` lists the separately authored
blanks. Each `StockComponent` requires a known, nonempty, unique `id`;
references match the exact id, with no ASCII character whitelist. It accepts `form`,
`dia_mm`, `length_mm`, `section_mm`, `origin_mm`, `axis`, `section_axis`, `blank`,
`note`, and `cite` with the same types and model-frame pose semantics as root stock.
A round blank uses diameter and length; a rectangular blank uses two section
dimensions and length. These are authored purchase/process choices, not
confirmed on-hand inventory. Missing dimensions or citations keep comparison
waste unresolved; finished volume comes only from the manifest's explicitly
sourced `volume_mm3`, never a bounding-box estimate.

M4 requires an explicitly placed envelope, not a finished-part bounding-box
substitute. `origin_mm` is in the model frame: the rectangular blank's corner
or the round blank's starting-face centre. `axis` is the unit length direction.
For a rectangular blank `section_axis` is the perpendicular unit direction
of `section_mm[0]`; `axis × section_axis` carries `section_mm[1]`. The box is
the product of those three positive intervals; a round blank is the declared
diameter cylinder along `axis`. Dimensions/placement describe authored material,
not measured stock on hand. Each built-up component must contain only its own
piece, not the full finished STEP. Missing component dimensions or placement
remain individual stock debt; a known component does not resolve another one.
Known component branches remain usable when another component's geometry is
missing. When every component envelope is known, their full union must contain
the finished STEP; failure leaves all component references with geometry debt.
A nonempty root `as_is_faces` declaration applies to the full joined supply
exterior and therefore requires every component envelope to be known; this
global declaration can withhold otherwise-known branches. Empty or omitted
`as_is_faces` adds no such cross-component dependency.
Incompatible as-is surfaces also keep stock-dependent geometry `?` with a reason.
`as_is_faces` never creates a stock solid by itself.

`as_is_faces` lists STEP face references (same forms as a feature's `faces`)
that stay as supplied stock; the M4 `coverage` rule unites them with the faces
claimed by cutting operations. An omitted list is unknown, not empty. On a
[profiled blank](#profiled-blank) each listed face is credited only when it is
supplied as cut within its drawing bands.

Root `construction` declares the candidate route, independently of the
drawing-side manifest permission. `built_up` is refused unless
`features.construction = "built_up_permitted"`: unknown or omitted drawing
permission does not lift the one-piece-only restriction. An explicit `one_piece`
candidate needs no such permission. Omitting the **plan's** candidate construction
is unknown rather than an implicit one-piece declaration.
See [stock-form comparison](rules-comparison.md).

### Prepared blank

`[stock.prepared]` declares the squared blank a mill route makes from a
rectangular root stock (`[stock]`, the raw sawn bar) with plan process
`end_face`s, and the setup that receives it. The saw cut stays prose in
`stock.prerequisite`. `prepared = "unknown"` declares a blank without saying
which: rule `prepared_blank` stays unknown.

| Field | Type (also accepts `"unknown"`) |
|---|---|
| `setup` | `str`: the plan setup that receives the blank (its `stock_in` lineage makes it) |
| `origin_mm` | `Vector`: blank corner, model frame, on the root stock's axes |
| `section_mm` | `Vector`: along `section_axis`, then along `axis × section_axis` |
| `length_mm` | `Number`: along the root stock `axis` |
| `tolerance_mm` | `Vector`: ± band for section 0, section 1 and length |
| `checks` | `PreparedChecks`: gauge reference per check |
| `methods` | `PreparedMethods`: written procedure per form check |
| `form_mm` | `PreparedForm`: `flat`, `square`, `parallel` limits (the most each procedure's gauge may move) |
| `cite` | `Citations` |

`PreparedChecks` names an inventory gauge for `length`, `section_0`,
`section_1`, `flat`, `square` and `parallel`; `PreparedMethods` gives the written
`flat`, `square` and `parallel` procedures and `PreparedForm` their limits. An
unknown `setup` is `BadInput`, as is a prepared blank on round, built-up or
profiled stock (there is no box to trim). Rule `prepared_blank`
([rules-setup](rules-setup.md#prepared_blank)) checks the size, the stock the
kernel cut and the checks; the receiving setup's sheet prints them as **CHECK THE
BLANK**, each form row with its limit and method.

### Profiled blank

A blank bought already profiled (laser-, waterjet- or plasma-cut from plate, for
example from SendCutSend or OSH Cut) is `form = "profiled_blank"` with a `blank`
table, on the root stock or on one `stock.components` entry:

| Field | Type (also accepts `"unknown"`) |
|---|---|
| `step` | `str`: the blank's STEP, relative to the plan's directory and inside the bundle |
| `step_sha256` | `str`: lowercase SHA-256 of those bytes |
| `profile_tolerance_mm` | `float`: the vendor's declared ± cut tolerance, positive |
| `cite` | `Citations`: the vendor's published tolerance |

```toml
[stock]
form = "profiled_blank"
as_is_faces = ["#119/ADVANCED_FACE[4]/", "#17/ADVANCED_FACE[1]/"]

[stock.blank]
step = "strap-blank.STEP"
step_sha256 = "ae8923c2…"
profile_tolerance_mm = 0.127 # the vendor's posted ±0.005 in
cite = "https://sendcutsend.com/blog/basic-tolerances-and-cut-feature-relationships/"
```

The blank STEP is authored in the **part model's coordinates**: the solid the
vendor cuts, placed where the finished part sits inside it. It is the supply's
whole envelope, so a profiled blank declares no `section_mm`, `dia_mm`,
`length_mm`, `origin_mm`, `axis` or `section_axis`. Any of them, a `blank` under
another `form`, or a root `blank` beside `components` is bad input (exit 3), and
so is a prepared blank on it. The loader reads and hashes the STEP like the
part's: bytes that do not match a known `step_sha256`, or a path outside the
bundle, are bad input; the report binds it as input `stock.blank` (a
component's as `stock.<id>.blank`). An unknown `step` or `step_sha256` leaves
the supply's geometry as named stock debt. The kernel imports the blank as the
supplied solid and accepts exactly one closed, valid solid that contains the
finished part; cuts, contact and volume then proceed as for a box or bar.
The tolerance is a cited vendor value, never a measurement (without a usable
`cite` it is unknown and credits nothing): it applies to every
face the plan credits from the blank, the sheet faces included, so declare the
larger of the vendor's cut tolerance and the plate's thickness tolerance when
the broad faces are credited. Inventory `stock` cannot hold a profiled blank.

`as_is_faces` still lists the faces the plan leaves as supplied. Each one is
credited only when the kernel finds it on the blank's boundary and every
drawing band of its features holds the vendor tolerance about its nominal
(rule [`blank_credit`](rules-geometry.md#blank_credit)); a face failing either
check stays uncovered and needs a cutting op, from a blank that leaves
machining allowance on it (an op cannot restore an undersize face). The
traveler prints the stock as a profiled blank of the kernel's overall size,
bought already cut to outline, with the vendor tolerance; the cut file itself is
bound in the report, not printed for the bench.

## Dro

| Field | Type (also accepts `"unknown"`) |
|---|---|
| `controller` | `str` |
| `manual` | `str` |
| `manual_url` | `str` |
| `mode` | `str` |
| `units` | `str` |
| `radius_mode` | `bool` |
| `direction` | `Direction` |

`radius_mode` selects the lathe X display convention: radial physical X jogs
read once in radius mode and twice in diameter mode. It does not change a known
mill's linear axes. In a mixed-machine route, the traveler labels the actual
setup machine's display convention rather than applying the lathe label to all
setups. Omitted or unknown on a lathe, no X reading is printed: the feature map,
part-off X and dome tables stop rather than assume a display
([coordinates](rules-coordinates.md#coordinates)). Unknown controller/install
facts remain unresolved independently.

## Direction

| Field | Type (also accepts `"unknown"`) |
|---|---|
| `x` | `str` |
| `y` | `str` |
| `z` | `str` |

## Setup

| Field | Type (also accepts `"unknown"`) |
|---|---|
| `id` | `str` |
| `machine` | `str` |
| `frame` | `str` |
| `coolant` | `str` |
| `stock_in` | `str \| list[str]` |
| `joint` | Tagged cylindrical or surface joint (required for array `stock_in`) |
| `note` | `str` |
| `deburr_mm` | `Number` |
| `deburr_cite` | `Citations` |
| `stock_state` | `StockState` |
| `hold` | `Hold` |
| `zero` | `Zero` |
| `ops` | `list[Operation]` |

For a manual joining, finishing or inspection station, declare the inventory
machine's `kind = "bench"` (or `"manual"`) and use only `fit`, `inspect`,
`deburr` and `coating` operations.
`zero_check`, `coordinates` and `headroom` are then `not_applicable`: the station
has no DRO, cutter-centre table, spindle stack or machine travel to check.
The joint's joining method does not create machine axes. Any cutting or
explicitly unknown action retains the normal screens; a bench declaration
cannot waive a machining operation. This does not waive physical joint,
holding, stock, frame or render requirements.

For component stock, an earlier setup's output, or a joint output, mill
headroom's X/Y travel screen uses the kernel's **setup-entry stock bounding
box**, before the current setup's cuts. It does not substitute the finished
part or the original raw blank. Missing entry stock remains a geometry debt.

`stock_in` names `"stock"` for a single supply, `"stock.<id>"` for a built-up
component, or any earlier setup's `id` (not necessarily the immediately previous
setup). An array requests assembly of exactly two disjoint branches and requires
an explicit `joint`; there is no generic Boolean-union fallback. Unknown or forward authored references are bad input
(exit 3), including authored `"unknown"` as a source. Omitted `stock_in`
remains stock debt; it does not infer a linear route. Every supply and setup output stays in the model frame:
joining references never applies an implicit assembly transform.
Array entries must have disjoint supply ancestry: repeated references or joining
a supply with its descendant (for example `["stock", "S1"]` when S1 consumes
stock) are bad input (exit 3), naming the shared supply ancestor. Separate route
alternatives may start from the same supply again, but cannot join that material
lineage twice.

### Assembly joints

Every array `stock_in` requires a singular tagged `joint` declaration and
exactly two disjoint input branches. Either input may be an already-joined
assembly if the other input is one single component. Thus `["body", "cone"]`
may produce `J1`, followed by `["J1", "crank"]` producing a three-component
assembly. Joining two existing assemblies, one-piece arrays and arrays with
more than two references are bad input (exit 3). Shared supply ancestry remains
forbidden at every step. Each interface identity is consumed only once.
Joint geometry is in the model frame, regardless of the assembly setup's frame.
A missing or malformed identity/reference is bad input; unknown numeric
geometry or joint-compound process facts withhold the union as named debt.

A cylindrical joint declares `kind = "cylindrical"`, `socket` and `spigot`
(matching plan joint-feature kinds on the two distinct consumed component
branches), `fit`, the applicable diametral fit band, `method`, nonempty
`process` and `cite`, plus an optional `compound`. `method` is the assembly
action. Clearance uses `fit = "clearance"` and `clearance_mm`, with
`method = "silver_braze"` or `"slip"`. Interference uses
`fit = "interference"`, `interference_mm` and `method = "press"`.
All tolerance extremes must satisfy the declared fit:

- Clearance interval: `[socket.low - spigot.high, socket.high - spigot.low]`.
- Interference interval: `[spigot.low - socket.high, spigot.high - socket.low]`.

The resulting interval must be nonnegative for clearance, strictly positive
for interference, and entirely inside the declared millimetre band; exact band
endpoints are accepted. A compatible nominal alone is insufficient. Axes must
be collinear with finite overlapping engagement.
Both preparation cuts must be completed on the actual selected ancestors,
remain intact, and have their target geometry verified at assembly. Declaring
a joint cannot turn untouched blanks into prepared components.

A retaining compound on the interface is a
`compound = { product, cure_time_min, surface_prep }` block: `product` names the
compound (nonempty, or literal `"unknown"`), `cure_time_min` is positive minutes
(or `"unknown"`) and `surface_prep` nonempty instructions (or `"unknown"`). The
joint's `cite` covers the compound's data sheet. A `slip` joint requires a
compound (a slip fit with nothing bonding it is not a joint), a `press` joint
takes one optionally (a light press with the compound filling the micro-gaps)
and a `silver_braze` joint takes none. A missing compound field is bad input;
explicitly unknown fit band, product, cure time or prep remains debt and cannot
produce assembled stock or a render. The retired `method = "retaining_compound"`
and the joint-level `cure_time_min`/`surface_prep` fields are bad input whose
message names this form. `process` itself must be known text: the literal
`"unknown"` is malformed, not an alternative bond process. Known physical
refusals remain errors even when prep or cure is unknown; a later invalid join
does not invalidate an earlier independent, valid assembly.
The traveler prints the prep, cure time and **do not disturb until cured** before
later machining, once: on the setup's first `fit` op (the op that bonds), else in
its "Starts from" line; that `fit` op's material / consumable cell names the
compound's product. A press fit with a compound prints **press in with the
compound on the interface, then do not disturb until cured**. The process does
not model cure kinetics or certify a product: cite the author's source/choice for
the declared band and cure conditions. A joint without a compound prints no prep
or cure. Use the canonical noncutting bench action `do = "fit"`, not an
undeclared `fit_up` or `bond` cutting action.

For example (illustrative process choices, not manufacturer specifications):

```toml
[[setups]]
id = "J2"
stock_in = ["J1", "crank_prepared"]
[setups.joint]
kind = "cylindrical"
socket = "crank_socket"
spigot = "crank_spigot"
fit = "clearance"
clearance_mm = [0.02, 0.06]
method = "slip"
process = "AUTHOR'S CHOICE: applied to both mating surfaces"
compound = { product = "AUTHOR'S CHOICE: example Loctite 638-class retaining compound", cure_time_min = 1440, surface_prep = "AUTHOR'S CHOICE: degrease and dry both mating surfaces" }
cite = "AUTHOR'S CHOICE: example clearance band and 24-hour cure before machining"
[[setups.ops]]
op = 10
do = "fit"
```

A cylindrical cross-bore socket uses the existing `cylinder_bore` kind with
`thru = true` and a finite `depth` spanning both openings. The kernel verifies
both ends are open; this is not an unbounded hole or a blind socket with a
waived bottom. A sleeve exterior is a `cylinder_spigot`, not a new feature kind.
An intentional bore already present in the sleeve is permitted only where it
does not remove required finished material; joining fills the mating annulus,
not the sleeve's core. A subsequent finished bore operation still needs its
own preparation/finish coverage and must follow the declared cure.

A surface joint needs no transient feature. It declares `kind = "surface"`,
`method = "weld"` or `"silver_braze"`, nonempty `process`, `cite`, and a nonempty
`interfaces` list. Each rectangle has model-space centre `at`, unit orthogonal
`normal` and `x`, positive `size_mm = [width, height]`, and nonempty `cite`.
Both sizes are full side lengths in millimetres; `normal × x` is the height
direction. `at` uses manifest units. These are author-declared internal butt interfaces,
not STEP face references. `stock_in[0]` owns the negative-normal side;
`stock_in[1]` owns the positive-normal side. Both received pieces must contact
essentially the whole rectangle inside the final solid, with no overlapping bulk. Multiple
patches describe one two-input join, not additional component inputs in that step.
Separated material is not joined merely because a process was named.

The kernel protects component-owned finished material during preparation and
checks final material coverage again at assembly. Cylindrical fill is limited
to derived finite engagement; surface joins add no fill. Undeclared overlap,
a blocked straight-axis insertion, or lost finished material refuses the
assembly. See [in-process stock](rules-geometry.md#in-process-stock).


## StockState

| Field | Type (also accepts `"unknown"`) |
|---|---|
| `top_feature` | `str` |
| `bottom_feature` | `str` |
| `note` | `str` |
| `top_z` | `float` |
| `bottom_z` | `float` |
| `retained_rail_bottom_z` | `float` |
| `od_mm` | `float` |
| `north_end_z` | `float` |
| `south_end_z` | `float` |
| `plain_end_z` | `float` |
| `bottom_z_cite` | `Citations` |
| `local_thickness` | `dict[str, Number]` |
| `local_thickness_cite` | `dict[str, Citations]` |
| `entry_z` | `dict[str, Number]` |

For lathe stick-out, `north_end_z` / `south_end_z` and `hold.stickout_mm` bound
the unsupported span. Its D is the smallest finished feature diameter in that
span after transformation into setup Z; `od_mm` remains the held-stock diameter
for collet/chuck capacity, not the unsupported-section diameter.

## Hold

| Field | Type (also accepts `"unknown"`) |
|---|---|
| `fixture` | `str` |
| `jaws_along` | `str` |
| `fixed_jaw` | `str` |
| `parallels` | `str` |
| `supports` | `str \| list[str \| Reference]` |
| `support` | `str` |
| `support_orientation` | `str` |
| `grip_on` | `str` |
| `stop` | `str` |
| `clamp` | `str` |
| `note` | `str` |
| `centre_lubrication` | `str` |
| `riser` | `str` |
| `method` | `str` |
| `orientation` | `str` |
| `locator` | `str` |
| `release` | `str` |
| `jaw_protection` | `str` |
| `locate` | `str` |
| `grip_mm` | `Number \| Literal['not_applicable']` |
| `jaw_above_parallels_mm` | `Number \| Literal['not_applicable']` |
| `stickout_mm` | `Number` |
| `stickout_fit` | `{ measure: str, nominal_mm: Number, add_mm: Number }`: a stickout set from a measured fit-up; `stickout_mm` is the nominal `nominal_mm + add_mm` ([stickout](rules-lathe.md#stickout)) and the operator sets the `measure` reading + `add_mm`. The HOLD table prints `nominal stickout mm` and `set stickout: measured … + N`; the picture dimensions `NOM STICKOUT …` and its notes say it is set as the measured fit-up + N |
| `jaw_center_along_mm` | `Number` |
| `jaw_bar` | `str` (fixtures `round_bar` between the work and the moving jaw) |
| `jaw_buttons` | `str` (fixtures `jaw_buttons`: one button between each jaw and the work, its spigot in the work's bore) |
| `align` | `{ indicator: str, limit_mm: Number, over_mm: Number, face: str, cite: str \| list[str] }`: how a mill vise's fixed jaw or angle plate's locating face is squared to the table travel; `indicator` is an inventory `dial_test_indicator` / `dial_indicator` gauge swept `over_mm` along the face, its reading changing no more than `limit_mm`; an angle plate's `face` names the fixture solid whose face is squared. Required where the setup mounts or turns the vise or plate ([hold_fields](rules-setup.md#hold_fields)) |
| `parallels_centres_mm` | `list[[Number, Number]]` (exactly two) |
| `parallels_along` | `str` (`x` / `y`; parallels under a non-vise hold) |
| `riser_up` | `str` (riser dimension standing vertical: `length` / `width` / `height`) |
| `riser_along` | `str` (riser dimension along `jaws_along`) |
| `riser_centres_mm` | `list[[Number, Number]]` (at least one) |
| `chuck` | `str` (the chuck a `dividing_head` carries) |
| `pose` | `Pose` |
| `jaw_clock_deg` | `Number` |
| `support_tip_mm` | `[Number, Number, Number]` |
| `quill_extension_mm` | `Number` |
| `centre_hole` | `str`: the `process_features` `centre_hole` the dead or live centre rides in; the always-required [`centre_support`](rules-setup.md#centre_support) rule requires an earlier setup in this setup's `stock_in` lineage (every setup in it routed) to drill it, with its preparation established and a mouth equal to `centre_hole_dia_mm`; the kernel seats the centre in that cut countersink instead of cutting a seat of its own |
| `centre_hole_dia_mm` | `Number` (> 0): the work's centre-hole countersink mouth at its end face; without `centre_hole`, the kernel cuts a seat of the dead centre's own point angle with that mouth on the face where the centre axis leaves the stock. In either case the centre must touch its seat (else a render debt) before it is checked against the setup-entry stock |
| `clamps` | `list[ClampPlacement]` |
| `clamp_order` | `list[positive int]` (1-based indices into `clamps`) |
| `preload_direction` | `"clockwise"` / `"counterclockwise"` |
| `stop_fixture` | `str` (inventory fixture with authored solids) |
| `stop_face` | `str` (feature id or `"stock_end"`: the face the stop seats on) |
| `stop_pose` | `Pose` |
| `grip_mm_verify` | `bool` |
| `jaw_above_parallels_mm_verify` | `bool` |
| `index` | `Index` |

`Pose` is `{origin_mm, x, z}`, each `[Number, Number, Number]` in setup-frame
mm: a fixture-local frame's origin and unit, orthogonal x and z axes. A
`ClampPlacement` is `{ref, note, pose, restraint, torque_nm, tighten}`: `ref` names a fixture or a
`kit/member` such as a clamping-kit strap, and its authored `solids` are
placed by `pose` (origin at the strap underside on the work). `restraint` is
`press` (it holds the work down along pose -z), `locate` (it only positions
the work) or `none`; undeclared is `none`. Only a press clamp can hold a stock
piece an op splits off, and only when the kernel proves the load path onto an
anchored support (rules-geometry, held split). A `locate` clamp must prove that
each of its solids that declares `locates` bears on the stock the way its
inventory `bears` declares: a pin's contact cylinder in the bore it locates
(`bore`) or a flat locator's face (`face`). See rules-geometry,
`thin_wall_under_clamp`.

`clamp` is the clamping instruction, or a declared clamp fixture's name. An
explicit `clamp = "none"` or `"not_applicable"` with no `clamps` members
declares a hold with no clamping load (for example gravity in a cradle); prose
such as "gravity only", an omitted or `"unknown"` value is not that declaration.
Under only non-cutting ops such a posed-solids hold makes
`thin_wall_under_clamp` not applicable (rules-geometry).

`clamp_order` is the declared tightening-action sequence for drawing badges,
not an automatic interpretation of the `clamps` array. A locating pin may
belong to that array for its posed solids without being a tightening action;
omit its index from the order. `preload_direction` is viewed from above,
looking down setup -Z. These annotations do not certify clamp force or order.
HOLD and the picture share one label per `clamps` entry, by its 1-based index:
`C<i>` for a press clamp (or, with `restraint` undeclared, an index in
`clamp_order` or no order at all), `LOC<i>` for `locate`, `SUP<i>` otherwise.
HOLD prints the order as "seat against the locators (turning in
`preload_direction`), snug each in turn, then tighten each fully in the same
order", to the entry's optional declared `torque_nm` when given. An entry declared
`tighten = "hand"` (a nut run down on a stud without a wrench) is printed as
tightened "by hand only, no wrench" instead of fully; it takes no `torque_nm`. A
clamp's note must not restate its tightening as hand or finger tight: the HOLD
prints it from these fields ([consistency](rules-setup.md#consistency)).

A physical stop uses `stop_fixture` plus `stop_pose`; its inventory solids
follow the same dimension/measurement/void trust rules as other fixture bodies.
The kernel places it, draws it and includes it in collision/interference checks.
An unresolved stop is a named fixture gap, not a guessed point from `stop` prose.

`stop_face` names the face the work seats on against the stop: a feature id or
`"stock_end"`. An unknown id is `BadInput`. `hold_fields` errors when the
arriving stock does not have that face yet: it must be `"stock_end"`, a face
the raw stock supplies (`stock.as_is_faces`), or a feature a cutting op in an
earlier setup of this setup's stock lineage made. A face the setup cuts itself,
or a later setup cuts, is not on the stock it receives. An earlier cut of
unknown action, or unknown as-is faces, leaves it unknown. When a setup in the
lineage omits `stock_in`, the routing is undeclared: an earlier setup's cut may
have made the face, so it is unknown, not an error. A cut in this or a later
setup is still an error: `stock_in` names only earlier setups.

M4 vise geometry consumes `fixture`, `parallels`, `fixed_jaw`, `jaws_along`,
`grip_mm` and `jaw_above_parallels_mm` to place the jaw solids in the setup
frame: `jaws_along` is the jaw length axis (`x` / `y`), `fixed_jaw` picks the
jaw on the negative or positive side of the other axis, `grip_mm` is the depth
of part inside the jaws and `jaw_above_parallels_mm` the jaw plate standing
above the stock seat (support tops, or the bed without a lifting support).
HOLD prints it and, from the same fields, `work top above jaw tops mm`
(`stock_state.top_z` less the seated bottom, `retained_rail_bottom_z` when lower,
and this height; `?` when any of them is unknown, or when this height or the
parallels are not inputs the kernel accepts below). A note in this hold must not
give heights from the jaws: give them as Z values
([consistency](rules-setup.md#consistency)).
An explicit `parallels = "none"` or `"not_applicable"` means known zero parallel
lift and no parallel solids or parallel-position debt. Without another lifting
support the work seats on the bed. Omitted,
`"unknown"` or unresolved named parallels still need an accepted positive
height; a named zero-height parallel is not equivalent to explicit absence.
A `grip_mm_verify = true` or
`jaw_above_parallels_mm_verify = true` flag makes that number unknown to the
kernel; `jaw_above_parallels_mm = 0` is a known zero, any other nonpositive or
unknown value is debt. Together with the vise's explicit `jaw_height`,
`jaw_width`, `jaw_depth` and `opening` and the selected parallels' `height`
(or explicitly declared zero lift), these are the facts behind the jaw solids
and setup findings. When a required fact is missing, the setup's `vise` and
`thin_wall_under_clamp` findings stay `?` and the render, if any, is a part-only
view labelled as unresolved.

Two optional authored pose fields complete the picture. `jaw_center_along_mm`
is the centre of the jaw plates along `jaws_along` in setup-frame
coordinates; without it the kernel draws only the jaw material certainly over
the gripped part and a pale envelope for where the rest of each jaw may lie,
and cutter samples inside that envelope stay `?`. `parallels_centres_mm` is
exactly two `[x, y]` setup-frame centres of the parallels; together with the
parallels row's fact-local `height`, `length` (along the jaws) and `width`
(along the clamp axis) they place two parallel solids with tops at the stock
seat. Nominal numbers are usable for geometry, not evidence of a measured
shop setup; a plan never carries measurement records, and a shop dimension
counts as measured only under the inventory's fact-local
[`measured.status` contract](inventory.md#measured-envelopes-and-installed-tool-stacks-m5).
Both poses are declarations the author must measure at the bench; the
kernel never infers a jaw centre or a parallel position, and only a setup
with exact jaws and, when selected, exact parallels is captioned as modeled.
Either field may be `"unknown"` (any unknown coordinate is a render debt, not
a guessed pose) and neither has a `_verify` flag: they are author coordinate
choices, while each parallel dimension has its own fact-local trust; the
inventory item's `verify` does not taint other numeric facts. Omitting the
optional poses does not block independent `vise` / `thin_wall_under_clamp`
facts. A selected parallel's missing height still leaves fixture dimensions unknown.

`jaw_bar` names a fixtures `round_bar` laid between the work and the moving jaw,
so a faced reference face seats flat on the fixed jaw while the opposite face is
still raw. Its fact-local measured `dia` holds the moving jaw off the work by
that diameter, so the jaws open by the work's width plus that Ø; the kernel draws
the bar along the jaws at the middle of the work held in the jaws and refuses a
bar taller than that work, or one that bears on no jaw-held work along its length.
The HOLD step prints the bar centre's height above the parallels in mm, like the
jaw height: the work's height comes from `stock_state` in plan units, so unknown
plan units leave the bar's height unknown. A bar that does not resolve to a
`round_bar` with measured `dia` and `length` leaves the jaws
unplaced (fixture debt), never drawn as closing on the work.

`jaw_buttons` names a fixtures `jaw_buttons` item: two shop-made buttons, one
between each jaw and the work, each with a spigot that drops into the work's bore
opening on that jaw face. Its fact-local measured `dia` (the button face),
`thickness`, `spigot_dia` and `spigot_length` place them: the kernel centres each
button on the one bore of the work opening on its jaw face that takes the spigot,
and the jaws close on the buttons, each standing off the work by `thickness`.
Any of those four unmeasured, or an item that is not `jaw_buttons`, leaves the
jaws unplaced (fixture debt), as does a face with no such bore, or with several,
or a button whose face shares no area with the work round that bore within the
jaw's height (a button no wider than the bore's mouth bears on nothing). The
contacts drawn are the button faces, not the jaws, and the grip measured is
only where the work bears on them. The HOLD's jaw-button step prints the four
measured sizes the jaws close on (face Ø, thickness, spigot Ø, spigot length);
an unmeasured one prints `? not measured`.

Other holding kinds are drawn from their own declarations, never defaulted.
A `chuck_3jaw` / `chuck_4jaw` (and the chuck a `dividing_head` names with
`chuck`) is placed by `pose` (origin at the jaw-face centre, +z toward the
work) with jaw 1 at `jaw_clock_deg` from pose x; its jaws close on the
setup-entry stock inside `grip_mm` behind the jaw face. A `dead_centre`
`support` is drawn from its tip at `support_tip_mm`, its quill
`quill_extension_mm` beyond the centre shank. An angle plate, custom fixture
or dividing head draws its inventory `solids` placed by `pose`, and each
`clamps` entry draws its member's `solids` at its own pose; a strap must bear
on the stock top. `riser`, `riser_up`, `riser_along` and `riser_centres_mm`
stand a vise's parallels on riser blocks (a `blocks_123` `supports` item is
the riser when `riser` is absent). Non-vise holds that declare no jaws set
`fixed_jaw = "not_applicable"`; one without a gripped depth also sets
`grip_mm = "not_applicable"`.

## Index

The `hold.index` record is strict: only the fields below are accepted.
Each field is optional and also accepts literal `"unknown"`; arbitrary keys
are bad input (exit 3 before output).

| Field | Type (also accepts `"unknown"`) | Meaning |
|---|---|---|
| `fixture` | `str` | Selected dividing-head identity in inventory. |
| `feature` | `str` | Feature owning the angular landing allowance. |
| `angle_deg` | `Number` | Authored step declares an open pattern with no closure; omitted with `positions >= 2` declares a full pattern at exact `360 / positions`. Explicit `"unknown"` stays unresolved. |
| `positions` | `int` | Number of checked landings; `1` is a single setting. Closure requires both `positions >= 2` and omitted `angle_deg`. |
| `rotation` | `"continuous"` | The head turns freely under rotary ops (`approach = "rotary"`); declares no `positions` or `angle_deg`, so there are no plate landings. |

`feature` selects the journal/pattern's angular tolerance. An omitted selector
or absent feature allowance falls back to `general_tolerances.angular_deg`;
an explicitly unknown selector or allowance stays unresolved. Angles are degrees
and `positions` counts angular settings, not drilled holes inferred from a part
name. Exactness uses the authored TOML angle value, not rounded sheet text.
For a full pattern (`positions >= 2` with `angle_deg` omitted), the step is
exactly `360 / positions`, and both every landing and cycle closure are checked.
An authored `angle_deg` with `positions >= 2` declares an **open pattern**:
every position is checked against `angle_tol_deg`, but closure is not applicable,
even when the authored steps happen to total a whole revolution. Explicit
`"unknown"` is not omission. `positions = 1` is one explicit angular setting
with no closure. The traveler prints plate, circle, turns and hole **spaces**,
with angles at the drawing's declared angular precision.

For rotary milling, use
`hold.index = { fixture = "<head>", rotation = "continuous" }` instead of a
landing pattern. A verified `dividing_head` passes indexing with no landings;
another fixture kind or simultaneous `positions`/`angle_deg` is an error,
and an unverified head remains unknown. This declares how the head is used,
not proof that its rotation is collision-free or its torque/locking adequate.

## Reference

| Field | Type (also accepts `"unknown"`) |
|---|---|
| `ref` | `str` |
| `orientation` | `str` |
| `note` | `str` |
| `height_mm` | `float` |
| `jaw_lead_mm` | `float` |
| `engage_at_z_mm` | `float`: follow rest only; the cut Z the tool passes before its jaws are set on the work, checked by `accessibility` against the kernel's clear Z ([geometry](rules-geometry.md#window-ends)) |
| `at_z_mm` | `float` |
| `jaw_side` | `str` (`turned` or `uncut`; follow rests only) |
| `ops` | `list[int]` |

A `hold.supports` table with `jaw_lead_mm` declares a follow rest riding that
far from the tool along Z; one with `at_z_mm` declares a steady rest at that
setup-frame Z. `ops` lists the operation ids it serves (omitted = every turning
op of the setup). A follow rest's `jaw_side` says which diameter its jaws ride:
`turned` (the default; trailing the tool on the diameter just cut) or `uncut`
(leading it on the diameter about to be cut). `ref` names an inventory
`follow_rest`/`steady_rest` fixture with measured `capacity_min`/`capacity_max`.
`turning_deflection` then uses the rest span instead of `stickout_mm`
(docs/rules-physics.md "Follow and steady rests"). The kernel also draws and
collision-checks the rest from that fixture's measured solid fields: a follow
rest's `jaw_width`, `jaw_height`, `jaw_depth` and `jaw_angles_deg`, a steady
rest's `body_dia` and `body_length` ([inventory](inventory.md),
[rules-geometry](rules-geometry.md#follow-and-steady-rests)). Example:
`supports = ["dead_centre_tailstock_mt3", { ref = "follow-rest", ops = [10, 30], jaw_lead_mm = 8.0, jaw_side = "turned" }]`.
The traveler's HOLD prints a follow rest's lead as a distance along the work,
never beside a Ø sign: `jaws 8.00 mm behind the tool, on the diameter just turned;
set on and backed off every pass as printed under each op` (trailing jaws ride
each pass's new diameter), or `jaws … mm ahead of the tool, on the uncut stock`.

Each op the rest serves prints its pass sequence once, as a full-width line under
the op row; the op's coordinate cell keeps only `follow rest on: Z …` where the
op's start would foul the rest (`engage_at_z_mm`, on the DRO grid). The sequence:
start with the jaws backed off; at that Z (or, with no engagement Z, once the tool
has turned the jaw lead) stop the feed, then the spindle; set the jaws and lock
them; restart the spindle, then resume the feed. Trailing (`turned`) jaws add the
pass end: stop the feed, then the spindle; back the jaws off; withdraw the tool
along X; return the carriage to the pass start — the return carries them back past
the pass start by their lead onto stock that pass never cut. Leading (`uncut`)
jaws return over the smaller cut diameter and get no release. Hands never set a
rest on a turning spindle, and the cut never resumes on a stopped one. A rest
whose `jaw_side` or positive `jaw_lead_mm` is not known prints a STOP box, never a
pass sequence.

## Zero

| Field | Type (also accepts `"unknown"`) |
|---|---|
| `x` | `AxisZero` |
| `y` | `AxisZero` |
| `z` | `AxisZero` |
| `transfer` | `Transfer` |
| `tool_touches` | `list[ToolTouch]` |

A setup whose every spindle op is a `guided_sweep` omits `x` and `y`: the sweep's
touch-off against its master sets them ([zero_check](rules-coordinates.md#zero_check)).

## AxisZero

| Field | Type (also accepts `"unknown"`) |
|---|---|
| `edge` | `str` |
| `feature` | `str` |
| `face` | `str` |
| `method` | `str` |
| `tool` | `str` |
| `holder` | `str` |
| `gauge` | `str` |
| `measure` | `str` (`measure_then_set`: what M is) |
| `from` | `str` |
| `edge_mm` | `float` |
| `radius_mm` | `float` |
| `paper_mm` | `float` |
| `check_jog_mm` | `float` |
| `offset_mm` | `float` (`measure_then_set`: Axis Set M + offset + paper) |
| `retouch_after` | `list[int]` |
| `after_op` | `int` |
| `measure_before_hold` | `bool` (`measure_then_set`: M is read on the part before it is held) |

Only explicit `measure_before_hold = true` with an authored `measure` places
M acquisition in its original first HOLD step (`Before clamping, measure Z M = …`).
That step has 35 × 10 mm clear pen room; no extra MEASURED ZERO INPUTS section is
added. Its DRO row refers back to `M measured before clamping (HOLD)`.
Absent/false declarations keep acquisition at the machine. The existing datum
transfer prints before the DRO ZERO table and tool settings, with its source
instructions and limits unchanged.

## Transfer

| Field | Type (also accepts `"unknown"`) |
|---|---|
| `from` | `str` |
| `indicate` | `str \| list[str]` |
| `tool` | `str` |
| `gauge` | `str` |
| `runout_limit_mm` | `Number` |
| `reindicate_after` | `list[int]` |
| `keep_clamped` | `bool`: the hold must not be loosened to correct the work (an indexed setup keeping an earlier chucking) |
| `recovery` | `str`: what to do when a `keep_clamped` sweep reads over the limit |

The setup sheet prints the transfer by what `indicate` names: on a lathe, tap true
to the limit; on a mill, one hole, bore or boss (or a named item that is not a
feature, such as a pin head) is centred on by moving the table; surfaces, or
several features, are an alignment, so the operator sweeps each surface by table
travel and taps the work, not the table, until the reading is within the limit.
With `keep_clamped = true` the work is never loosened or tapped: the sheet prints
the sweep as a check (a centring still moves the table), `do not loosen`, and the
plan's `recovery` for a reading over the limit. Without a `recovery` it prints a
STOP and [zero_check](rules-coordinates.md#zero_check) is `unknown`.

## ToolTouch

| Field | Type (also accepts `"unknown"`) |
|---|---|
| `tool` | `str` |
| `x_method` | `str` (the operator's words; `"trial_cut_measure"`: the touch trial-cuts its own diameter) |
| `x_face` | `str`: the plan feature whose measured diameter a lathe X touch is set on, or `"x_zero"` for this setup's X-zero trial-cut land; must stand where it touches ([zero_check](rules-coordinates.md#zero_check)) |
| `x_paper_mm` | `float`: paper between the tool and that diameter; Axis Set X = measured D + 2×paper on a diameter display (D/2 + paper on radius). The traveler prints the surface and this paper (`no paper` at 0, `paper ?` unknown) with the `x_method` words |
| `gauge` | `str` |
| `z_face` | `str` |
| `method` | `str` |
| `edge_mm` | `float` |
| `paper_mm` | `float` |
| `z_gauge` | `str` (`measure_then_set`) |
| `z_measure` | `str` (`measure_then_set`: what M is) |
| `z_offset_mm` | `float` (`measure_then_set`: Axis Set Z = M + offset + paper) |
| `corner` | `"chuck_side" \| "tailstock_side"`: a grooving/parting blade's Z touch corner where the touched face gives no measured normal (a scribe); a face normal that contradicts it is an error ([zero_check](rules-coordinates.md#zero_check)) |
| `before_ops` | `list[int]` |
| `after_op` | `int` |

## Operation

| Field | Type (also accepts `"unknown"`) |
|---|---|
| `op` | `int` |
| `do` | `str` |
| `feature` | `str`; an `inspect` op may name a list of two or more distinct features |
| `faces` | `list[str]` |
| `tool` | `str` |
| `holder` | `str` (the tool's `shank` must fit it; a single nominal collet capacity accepts the ISO 286 h6 band below it, [`tool_resolves`](rules-tools.md#tool_resolves)) |
| `direction` | `str` |
| `note` | `str` |
| `layout` | `str` (`scribe` only: `dividers`, `trammel` or `template`; or `ends`, a guided sweep's two arc-end marks measured from the bar's own faces) |
| `guide` | `Guide` (`scribe` with a template, `file_to_line`) |
| `inspection_note` | `str \| list[str]` (numbered steps; see above) |
| `process` | `str \| list[str]` (`coating` only: a `services` or `consumables` id) |
| `process_holds` | `list[ProcessHold]` |
| `to_z` | `float` |
| `depth_mm` | `float` |
| `exit_mm` | `float` |
| `rough_allowance_mm` | `float` |
| `stock_to_leave_mm` | `float` |
| `z_from` | `float` |
| `z_to` | `float` |
| `to_dia` | `float` |
| `rpm` | `float` |
| `feed_mm_min` | `float` |
| `doc_mm` | `float` |
| `feed_mm_rev` | `float` |
| `approach_mm` | `float` |
| `to_z_cite` | `Citations` |
| `note_cite` | `Citations` |
| `checks` | `dict[str, str \| dict[str, str]]` (a nested table scopes entries to one listed feature) |
| `go_no_go` | `dict[str, GoNoGo \| Unknown \| dict[str, GoNoGo \| Unknown]]` (each entry needs its feature's `checks` gauge) |
| `missing_requirements` | `dict[str, str]` |
| `inspection_methods` | `dict[str, str \| list[str] \| dict[str, str \| list[str]]]` |
| `inspection_views` | `dict[str, list[InspectionView]]` (flat only) |
| `to_z_band` | `Vector` |
| `contour` | `Contour` |
| `stock_removal_bounds` | `Bounds` |
| `approach` | `"rotary"` |
| `angle_window_deg` | `[Number, Number]` |
| `cut_plane` | `SawPlane` (a straight saw cut only) |
| `follows` | `str`: `"<setup>:<op>"` of an earlier `scribe` op (a saw that follows its line only; an `ends` layout scribes no line, an error) |
| `allowance_mm` | `Number` > 0: stock a saw that `follows` a line leaves outside it for the file |
| `keep` | `str` (a finished feature: after a held split, the piece that carries it stays and every other piece is discarded; see [keep piece](rules-geometry.md#keep-piece)) |

`keep` names the piece that leaves the setup when the work is in pieces, typically
on the `release` op after the cut that freed the part from its frame:

```toml
[[setups.ops]]
op = 70
do = "release"
keep = "hub_od"
```

The kernel applies it to the stock after the last op it models at or before the
keep op (a `release` is not modelled, so that is the freeing cut), keeps the one
piece that carries every face of the feature and discards the rest. Later
setups' entry stock and their `stock_state` checks then see the kept piece only,
as do later ops' flutes in the same setup; their holders still see the
setup-entry stock, as for any cut ([keep piece](rules-geometry.md#keep-piece)).
Without `keep`, a held split keeps every piece, as before.

An `inspect` op may name several features (`feature = ["a", "b"]`): one
drawing limit split across them, or one inspection station reading several. A
flat `checks`, `go_no_go` or `inspection_methods` key is a requirement name, valid
when any named feature exports it, and applies to every named feature that does.
A key naming one of the listed features instead scopes a table of requirement
entries to that feature, so one station reads the same requirement name with a
different gauge on each:

```toml
feature = ["pivot_bore", "hub_od", "hub_faces"]
checks = { pivot_bore = { dia = "pin-gauges" }, hub_od = { dia = "micrometers/0-1in" }, length = "micrometers/0-1in" }
go_no_go = { pivot_bore = { dia = { go = 6.500, no_go = 6.530 } } }
```

Each feature's entry is its scoped one, else the flat one. Flat and scoped entries
mix in one table, but one requirement is flat or scoped within a table, never both
(a flat entry already applies to every feature exporting it). Across tables they
mix freely: a flat `go_no_go.dia` pairs with scoped `checks`. `BadInput` when a
scope key is not one of the op's features, when a scoped requirement is not one
its feature exports (use `missing_requirements`), when a key is both a listed
feature and an exported requirement (ambiguous), when one requirement is given
both flat and scoped, and when a `go_no_go` pair or scoped method has no `checks`
gauge for its feature's requirement (a flat pair needs one on every listed feature
exporting it). A single-feature op keys these tables by requirement alone, so a
scope key on it is `BadInput`: there is nothing to tell apart, and one spelling
keeps every single-feature reader flat. `missing_requirements` and
`inspection_views` stay flat: a view illustrates a flat `inspection_methods`
entry, never a scoped one. The inspection rule credits the op to each feature
it reads, with that feature's own gauge, pair and method. The sheet prints the op
as one station card: one row per requirement, naming every feature that shares a
gauge, pair and method, and its own row for each feature read differently. A
scoped method prints once as its own note headed with its feature; a flat method
prints once for every feature. A list on any other action is `BadInput`.

**Finishing route.** `deburr` and `coating` are manual bench actions. A
`coating` op (black oxide, paint, oil) names its `process`: an outside
`[services.<id>]` item or in-house `[consumables.<id>]`. An absent process is
unknown in `tool_resolves`, and an unlisted one is an error. A drawing
`material.finish` with no `coating` op in the route is a job caution
(`finish_route`, [inspection rules](rules-inspection.md)).

A `ProcessHold` is `{ feature, requirement, band = [lo, hi], gauge, reason }`, all
required, plus an optional `go_no_go`: a shop limit tighter than the drawing, held for a stated process reason
(a downstream fit, a pin that clocks a later setup). `requirement` must be one the
feature exports (else `BadInput`), and `band` is in the drawing's units. The
inspection rule errors when the band reaches outside the drawing band (limits
included, a scalar zone `v` read as [0, v]). The sheet prints it in the op's
inspection cell as `PROCESS HOLD — not a drawing limit (why: see job page): …`,
never as a drawing limit, and the job page gathers every hold, with its reason, in
a **PROCESS HOLDS — in-process limits, not drawing limits** table, apart from
DRAWING REQUIREMENTS; the reason prints nowhere else.

A hold may instead name a feature's reference-only dimension (`<name>_ref`, a
number the drawing gives as REF or CUT TO FIT, such as an assembly fit-up span).
The drawing sets no limit there, so the hold must also say what the gauge reads
(`measure`, e.g. `"scribe to faced end"`) and where the band comes from (`cite`);
missing either is `BadInput`. A `measure` on a hold of an exported requirement is
`BadInput` too: that hold reads the requirement itself.

A `GoNoGo` is `{ go = <mm>, no_go = <mm> }`, both positive and different: the two
limit-gauge sizes a limit check uses. The GO size must pass the work (enter a hole,
pass over a boss or shaft) and the NO-GO size must not. An op's
`go_no_go.<requirement>` is the pair its `checks.<requirement>` gauge uses for the
drawing band (`go_no_go.<feature>.<requirement>` scoped on a multi-feature op); a `process_holds` entry's `go_no_go` is the pair for the hold band.
Both sizes must be listed in the gauge's `sizes_mm` and lie inside the band they
accept, the drawing band as printed (rounded inward) or the hold band; see
[inspection rules](rules-inspection.md#go--no-go-limit-checks). The op row prints
`GO <go> enters, NO-GO <no_go> does not`, so `inspection_methods` need not repeat
the sizes.

`faces` explicitly declares this operation's cutting claims using bound STEP
references. Omission uses the feature's default `faces`; `"unknown"` means
unresolved claims; a known explicit list must be nonempty. Explicit refs need
not be the feature's default refs: a drawing feature may require two broad surfaces even
when its exported label names only one. The plan can claim the other exported
surface without rewriting the manifest. Invalid/unmapped refs are geometry
errors. Under the axial milling model, a far-side face whose outward normal
opposes the setup's +Z approach by more than 90° is an error naming the face
and earns no coverage credit. Complementary setups can explicitly claim
opposite sides; finishing coverage credits each face only to the
approach-valid finishing cuts that claim it.
A claimed hole cap also needs its feature's last drill/ream/bore/counterbore
setup to leave it clear of stock; a tap or pilot claim never stands in for that
(see [geometry](rules-geometry.md#finish_coverage)). No plan field selects that op.

**Complete explicit-face ownership.** An op owns a feature it does not name when
its explicit `faces` list is known and nonempty and contains every face of that
feature's known, nonempty declared `faces`. Ownership is per op: a partial
claim, an empty or `"unknown"` list (or one with an `"unknown"` member), a
feature whose own faces are unknown, and an op without explicit `faces` never
own; a label alone never owns another feature. A hole-family feature (`hole`,
`counterbore`, `thread`, `threaded_hole`) is owned only by a complete-form
action (`drill`, `ream`, `bore`, `counterbore`). Ownership adds the op to the
feature's finishing cuts for datum consistency and finishing coverage, under the
same final-cut filters as a named op (no rough, manual or nonfinishing action);
label-scoped facts (hole chains, sizing, inspection checks) still follow the
op's own `feature`.

`stock_removal_bounds` is an explicit setup-frame clearing box:
`{ x = [lo, hi], y = [lo, hi], z = [lo, hi] }`, all three intervals numeric
and strictly increasing. It declares the material outside the finished part
that this cutting operation clears inside that volume, leaving everything
outside it unchanged. Its faces still need valid cutting claims from this
setup. The box is the explicit cleared footprint, for example the envelope of
several roughing passes or, on a `chain_drill` op, the author's certification
of the actual drilled-and-chiselled break-out footprint; it is not capped to
the claimed faces' XY bounding box
dilated by the cutter radius. The cutter radius must still be known: if it is
unknown, the bounds are `?` with a reason naming the missing cutter radius, and
later stock stays unresolved. Removal is the box's intersection with the
setup-entry stock and never takes finished material or a protected rough leave.
Every claim must touch the box and every removed piece must border a claim on
that setup-entry stock, so an earlier op of the setup clearing the bridge
between a claim and the rest of its box never strands it; the pieces are then
cut from the current stock, which only removes material and never restores what
an earlier op cleared. Known future planned-hole columns, with their finite caps,
stay stock; and the removal must not split an original input solid. A violation is named stock
debt, not an error: later stock that depends on it stays unresolved (later ops
of the same setup keep only certain finished-material flute hits, with tool hits
unknown), while genuine collisions with finished material remain independent
errors. It shapes the stock later flutes of this setup and later setups meet,
and excludes this operation's own derivable allowance from its flute obstacles;
accessibility holder obstacles and holding facts still use setup-entry stock,
while reach, holder-wall and shank screens see it ([`reach`](rules-geometry.md#reach)).
The box also confines this op's cutter: accessibility judges a claimed face
only where the cutter can stand without meeting stock outside the box (air and
the finished part beyond it do not stop it). Samples it cannot reach are
carried to a later op that cuts or files the same face (a rough cut or a file
to the line, for example; never a saw); with none, the finding is an
error ([`accessibility`](rules-geometry.md#accessibility)). This is an
authored process/fixture volume, not a
measured toolpath or proof that the whole toolpath is safe. Without it, any claimed wall
whose interior still touches overstock above `to_z` (including a drafted wall)
needs a named stock-out debt; a contour checkpoint bbox is not a clearing volume,
and an unbounded `chain_drill` op's webs are such overstock: the kernel removes
its discrete holes only and keeps the webs in stock until a later known
removal (see [Manual arcs](#manual-arcs)).

`approach = "rotary"` mills on a horizontal dividing head: each sample of the
claimed faces' windowed portions is turned about the head axis to top dead
centre under the vertical spindle
(see [Approach models](rules-geometry.md#approach-models)). For such an op
`z_from`/`z_to` are positions along the head axis (the chuck `pose` z) from the
pose origin, and `angle_window_deg = [from, to]` is the head rotation in
degrees, right-handed about that axis (from < to; a span of 360 or more is
unbounded). Together they are a partial-face claim window: the op samples and
removes only the part of each claimed face inside it, and points outside are
excluded, not claim errors. A window holding no positive-area part of a
claimed face makes that face a claim error. Claims must be supported external
surfaces of revolution about the head axis (coaxial cylinders or planar
annuli normal to it). The setup's `hold.index` declares
`rotation = "continuous"` without `positions` or `angle_deg`, and its
`hold.pose`, `hold.chuck` and inventory solids establish the head/chuck
geometry, not an inferred fixture.

A face claimed through rotary windows is covered only when the exact union of
every rotary op's window portion of it covers the whole face: several ops,
cutters and setups may contribute (for example a larger cutter on the body
and a smaller one into a shoulder), and `finish_coverage` unions only the
finishing ops' portions. An uncovered remainder is a `coverage` /
`finish_coverage` error naming its area and spans; an undecided union stays
unknown. A whole-face non-rotary claim, or `stock.as_is_faces` for
`coverage` only, covers the face regardless. See
[`coverage`](rules-geometry.md#coverage).

Own-removal combines each claimed cylinder's radial sweep with the actual
vertical cutter columns at concave wall-tangent sample poses. Each volume is
clipped to the axial/angular window, the finished solid is subtracted, and the
volumes are cut from the stock one by one in order, never fused: finished
bosses/pads and material outside that derivable allowance remain obstacles.
The flute meets the stock left after this removal; an underivable removal
credits none of it. Accessibility holder obstacles retain setup-entry stock;
reach, holder-wall and shank screens meet the stock earlier ops leave. This is
one top-dead-centre pose per sample,
not a continuous toolpath or proof of clearance while rotating between poses.

`doc_mm` supplies the engagement screen's axial depth per pass for an
endmill-family cutter on a cutting operation. Omitted, unknown or nonpositive
DOC on an eligible operation remains unresolved. Known noncutting actions
and known drills, reamers, taps or lathe tools are `not_applicable`.

`approach_mm` is the authored nonnegative safe approach/retract distance along
setup Z for M5's travel screen. There is no invented default: absence or
`"unknown"` leaves that operation's Z travel unresolved and the sheet says how
to measure/author it. It does not itself command a machine move or assert XY
collision clearance. Feature extents/centres and commanded tip targets supply
the other spans; see [M5 measured setup screens](rules-setup.md#m5-measured-inventory-screens).
On a milled path that returns to an entry (a raster, a path in pieces, an open
path cut in several depth levels) it also sets the raise Z the sheet prints,
`approach_mm` above the current top; without it that return is coordinates debt
([depth levels](rules-coordinates.md#coordinates)).

## Contour

| Field | Type (also accepts `"unknown"`) |
|---|---|
| `method` | `str`: `linear_table`, or a manual-arc method `stairs`, `chain_drill`, `chords`, `rotary_table`, `guided_sweep` |
| `sweep_frame` | `str` |
| `open_side` | `str` |
| `step_deg` | `float` (`rotary_table` and `guided_sweep` row spacing; `guided_sweep` under 180) |
| `step_mm` | `float` (raster step) |
| `start_deg` | `float` |
| `end_deg` | `float` |
| `cusp_mm` | `float` (`stairs`: most material a stair may leave on the wall) |
| `pitch_mm` | `float` (`chain_drill`: largest hole-centre spacing) |
| `count` | `int` (`chords`: number of chords) |
| `centre_by` | `str` (`rotary_table`: `pin` or `indicate`) |
| `centre_feature` | `str` (`rotary_table`: the hole on the arc axis the table centres on) |
| `sweep_bounds` | `Bounds` |
| `keep_out` | list of `{ at = [x, y], dia_mm = d }` circles |
| `sweep` | `GuidedSweep` (`guided_sweep`: its guide, master and sweep) |

A `rough_profile` with `method = "chain_drill"` and a resolved drill-kind
tool performs drilling, so its speed/feed lookup selects `operation = "drill"`.
Other contour methods and end-mill chain contours retain profile data.
The axial feed, tool-chart precedence and before-stock penetration used for
deep-hole derating are defined in [cutting data](cutting-data.md).

`keep_out` centres use `sweep_frame`, defaulting to the feature's frame.
Positive `dia_mm` islands exclude the whole cutter: pass centres clear each
island radius plus cutter radius. Crossing passes split into independent,
positive-length pieces in feed order, each with its own feed/lift/rapid cycle;
each cut point lies on the DRO grid, rounded away from the island.
The raster record reports setup-frame circles in `raster.keep_out`, the pass parts
they removed in `raster.keep_out_skipped`, and counts pieces in `raster.passes`.
The geometry kernel honours the same split: the op removes no stock inside an
island or in the cusps its printed pieces leave between their ends, and its floor
poses stand at least one cutter radius outside it (see
[rules-geometry.md](rules-geometry.md)). Stock tracking agrees: a surface an
island grown by the cutter radius reaches is at most partly faced, and an unknown
cutter radius leaves its coverage `?` (see
[coordinates](rules-coordinates.md)).

## GuidedSweep

A `guided_sweep` contour's `sweep` record ([manual arcs](#manual-arcs), step 4).

| Field | Type (also accepts `"unknown"`) |
|---|---|
| `guide` | `"pivot"` (a swing arm on a pin at the arc centre) or `"rail"` (a sled's arc rail on two rollers) |
| `fixture` | `str`: the inventory `fixtures` item that carries the work and rides the guide (`kind = "swing_arm"` for a pivot, `"arc_sled"` for a rail); it must be the setup's `hold.fixture` |
| `master` | `str`: the inventory `gauges` item the stationary cutter is touched to (`kind = "setting_bar"`, pivot only, or `"master_arc"`, rail only in practice: a master arc on a swing arm gives no radial line to centre the cutter on, so it prints only a STOP, [#288](https://github.com/pedropaulovc/prechips/issues/288)) |
| `touch_axis` | `"+X"`, `"-X"`, `"+Y"` or `"-Y"`: the setup axis on the cutter's radial line, and the side of the arc centre the cutter stands on; the setup frame is the work at the sweep's middle pose, so it must point from the arc centre to the arc's middle |
| `sweep_deg` | `float`: the fixture's whole sweep, centred on the arc; at least the arc's span and under 360 (a full circle cannot be swept: use a rotary table) |
| `rollers_deg` | `Vector` (rail: the two rollers' angles about the arc centre from the cutter's radial line, counterclockwise from above, with the cutter at the arc's middle) |
| `rail_deg` | `Vector` (rail: the rail's two ends, the same way) |

## Guide

| Field | Type (also accepts `"unknown"`) |
|---|---|
| `buttons` | `str`: an inventory `fixtures` kit of `kind = "filing_buttons"` |
| `bore` | `str`: the plan feature the buttons' pin goes through |
| `template` | `str`: an inventory `gauges` radius or profile template |
| `gauge` | `str`: the inventory radius or profile gauge that checks the filed arc |

## Manual arcs

The PM-30MV is a manual mill with a DRO: one handwheel moves at a time, so an arc
is never one move of two axes (no MDI, G-code or continuous circle). The plan
uses the 1898 manual arc method:

1. **Lay out** (optional with buttons): `do = "scribe"` on the arc feature with
   `layout = "dividers" | "trammel" | "template"` (`guide.template` names the
   template). The `manual_arc` rule prints the centre (setup X/Y, and the hole on
   its axis), the nominal radius and the arc ends; an unknown layout is unknown.
2. **Rough outside the line**: a `rough_*` op with
   `contour = { method = "stairs", cusp_mm = … }` (single-axis stair corners on
   the DRO grid) or `{ method = "chain_drill", pitch_mm = … }` (drilled holes,
   webs chiselled out along the hole centres; the kernel credits the drilled
   holes, not the chiselling, see below), plus a nonnegative
   `rough_allowance_mm` (a negative leave, here or on any op, is an error: the
   rough would cut into the finished part). Every
   stair corner, every full hole and every break-out between neighbouring holes
   must stay outside the finished line, and the stock left for the file
   (allowance + the stair cusp measured along the wall normal, or the maximum
   of allowance + drill radius, printed arc break-out radial depth and the
   greatest nearest-finished-wall distance of the retained printed
   straight-join break-out polyline)
   must not exceed the shop policy `numbers.max_filing_stock_mm` unless a later
   rough cuts the same faces again. Missing or unestablished caps remain unknown.
   Both rough methods support straight joins. Chain holes use the same
   drill-radius + allowance offset on each finite join leg, with exact
   endpoints/miter and nominal equal spacing no greater than `pitch_mm` (DRO
   grid snapping can move the printed spacing).
   Host DRO selection and kernel regeneration/actual-hole acceptance use one
   shared pure finite-boundary predicate for bounded and unbounded chains.
   Actual closed finished loops (joined bottom outlines and full circles
   included) use point-in-region plus nearest finite-boundary distance,
   negative in kept material. Unordered exact arcs and lines connect by real
   endpoints; authored scrap normals determine the kept side. True open arcs
   and current partial top-plus-land wall packets have no complete finished
   loop in the packet. The top packet omits tapers and the bottom arc even
   when the host model has those linked facts; fuller actual closed-boundary
   transport is tracked in
   [#212](https://github.com/pedropaulovc/prechips/issues/212).
   A gentle arc may instead be hand-sawn outside the line on the bench: a saw
   op that `follows` the scribe op, with its `allowance_mm` and declared
   `stock_removal_bounds`
   ([hand saw](#hand-saw-on-the-bench-straight-or-to-a-scribed-line)), counts
   as the rough the file finishes.
   No closure is invented: the open fallback uses oriented finite projections,
   real free-end
   caps and shared-concave-vertex sector classification. Conservative ties
   do not globally AND distant supporting half-planes. Missing or ambiguous
   region geometry, inconsistent occupancy or unsupported topology remains
   unknown, never an unsigned-distance pass. No admissible grid point leaves
   cut tables withheld. Closed-loop break-outs test kept-region entry against
   the whole finite boundary, not only their own join lines.
   Unsigned wall distances intentionally still measure filing stock/residual,
   not scrap-side acceptance; T6 enforces `numbers.max_filing_stock_mm` on
   the actual regenerated residual. Every actual cylinder still needs web,
   bounds and the existing 3D collision/accessibility backstop. The open
   fallback is not full-part region proof. Internal wall normals/outward
   signs add no user schema, policy knob or tolerance; the shared
   engine helper (`kernel/chain_boundary.py`) changes the source digest and re-keys every kernel job.
   Method, stage, full-hole outside-the-line and requested no-web (authored `pitch_mm` no greater than
   the drill diameter) errors are preconditions found before any clip. A bounded
   chain is then clipped at drill granularity: the drill-centre offset arc and
   joins are intersected with the bounds eroded by the full drill radius (a
   closed arc's seam fragments are one span), each retained arc or leg is
   regenerated on its own with equal nominal intervals within `pitch_mm` that
   still leave a web judged on the actual snapped DRO centres, not the nominal
   span alone (for a retained span longer than the length tolerance, the
   pitch-required count is always tried at its snapped positions, even when it
   exceeds the nominal-length web bound, and any higher nominally feasible
   count is also tried before shortening; a span within that
   tolerance, an isolated point or a tiny retained arc or leg between two
   shared junctions, keeps exactly one hole, never a duplicate row; a span whose
   snapped placement leaves no positive web at any such count omits its
   clipped end hole as
   a dropped end, never a fabricated no-web error), and every actual hole
   snaps to the DRO grid inside the bound and passes that same predicate
   with clearance for the whole drill and allowance. Bounds never waive
   region membership for a closed loop or the finite-projection/free-end/
   concave-shared-vertex fallback for a true open packet.
   Nominal-distance/offset guards remain additional placement constraints,
   not independent unsigned side acceptance. The authored radial whole-hole
   check is intentionally preserved before clipping; a regenerated,
   physically safe finite-cap hole beyond the actual sweep may nevertheless
   lie inside the authored supporting circle. Every hole searches a symmetric
   square of three
   grid steps per axis and chooses the nearest safe point by Euclidean
   distance with a deterministic coordinate tie-break; ends and junctions may
   back off inward along the true curve, and a hole with no such grid
   candidate after that full search and back-off leaves the whole clip
   unknown, never a hole in finished material. Every actual hole cylinder is judged; a
   swept-chord intersection never becomes an extra hole.
   Web/break-out validation and the single cap enforcement run on that chain.
   Its table names only dropped ends and genuine piece breaks as stops where
   stock beyond is not cleared or part of the chiselled chain; an intact
   arc/join junction continues into the adjacent table. Omitted joins add no
   join debt while an arc or other table
   remains, while a wholly excluded or disconnected stage keeps its existing
   clip debt. Arc and join tables report the same worst-stage stock; chain
   errors retain stock/cap profile facts where the residual was computed (a
   precondition error may prevent it), even when cut tables are
   withheld. Hole
   repositioning is not a handwheel cut ([coordinates](rules-coordinates.md#coordinates)).
   In-process stock: an unbounded chain (no `stock_removal_bounds`) removes
   only each actual hole cylinder; the positive webs between holes, the stock
   between the holes and the claimed wall and any rail or ear beyond them stay
   in stock until a later op really cuts them. It gets no cutter corridor,
   no +Z claim sweep, no lineage band and no drill-radius sweep between hole
   centres, unlike a milling profile. Those retained webs are then overstock
   on the claimed wall: the op is named stock debt pointing at
   `stock_removal_bounds`, and later setups descending from it stay unknown
   through the ordinary propagation. Declare `stock_removal_bounds` on the
   chain op to certify the actual drilled-and-chiselled footprint, under the
   same finite-box, setup-entry-stock and protected-material rules as any
   bounded op; it is the author's certification, not a demonstrated toolpath.
   Ordinary milling ops and bounded boxes are unchanged. A dedicated
   break-out/chisel phase or schema is tracked in
   [#213](https://github.com/pedropaulovc/prechips/issues/213); none exists yet.
3. **File to the line**: `do = "file_to_line"` with a `guide`: hardened filing
   `buttons` (an inventory `fixtures` kit with `kind = "filing_buttons"` and the
   declared limits of every element between its rims and the bore axis
   ([inventory](inventory.md)), held by the setup as its `hold.fixture` or a
   clamp) pinned through `bore`, a hole on the arc's axis drilled, reamed or
   bored to size earlier; or a `template` checked against a scribed layout. A
   `gauge` (inventory `radius_gauge`/`profile_gauge` whose `range_mm` covers R)
   checks the arc. The buttons file R worst case from `button_min/2 − shift` to
   `button_max/2 + shift`, where the rim centre's shift off the bore axis is
   `(bore_max − pin_min)/2 + (button_bore_max − pin_min)/2 + runout/2`; that whole
   band must sit inside the radial band. No guide, no gauge, buttons not held or
   flagged to verify, any unknown element limit (button OD, button bore, pin,
   runout or the bore's drawing size) or radius band, no earlier rough or no
   established cap is unknown; a gauge range that misses R, buttons on a concave
   arc, a bore off the axis or not yet made, a pin whose largest size exceeds the
   smallest bore or button bore, or a worst-case filed radius outside the band is
   an error. `scribe` and `file_to_line` are manual: they need no tool
   and may stand in a bench setup (`machines.<id>.kind = "bench"`).
4. **Or finish on the mill**: `{ method = "chords", count = … }` cuts straight
   chords whose sagitta `c²/8R` fits the band, each fed along one axis (a slanted
   chord indexed square on a rotary table; a full circle takes at least three);
   `{ method = "rotary_table", step_deg = …, centre_by = "pin" | "indicate",
   centre_feature = … }` turns the work on an inventory `rotary_table` fixture
   (`hold.fixture`, its centre bore `bore_dia_mm` for a pin) under a cutter
   locked at the cutter-centre radius on the DRO grid, between dial readings
   rounded inward on its resolution; a pin that misses the table bore, a printed
   offset whose cut (widened by a pin's play) leaves the band, an arc too
   short for one dial step, and rows half a turn or more apart
   (`step_deg` 180° or more on a long enough arc) are errors.
5. **Or sweep it under a locked cutter** when its centre is too far off the part
   for a rotary table: `{ method = "guided_sweep", step_deg = …, sweep = { guide,
   fixture, master, touch_axis, sweep_deg, rollers_deg, rail_deg } }`
   ([GuidedSweep](#guidedsweep)). The work rides a fixture that holds it to rotation
   about the arc centre: a swing arm (`guide = "pivot"`, inventory
   `kind = "swing_arm"`) turning on a pin at the centre, or a sled
   (`guide = "rail"`, `kind = "arc_sled"`) whose rail, an arc concentric with the
   part, is pushed against two rollers fixed in the T-slots. With the spindle
   stopped the cutter itself is touched to the named `master` along `touch_axis`
   (a `setting_bar` seated on the pivot pin, or a `master_arc` pinned on the
   fixture), and X and Y are locked: the table never moves while it cuts, only the
   fixture does, so no method moves two axes at once. The cut radius is the
   master's declared `radius_limits` (a measured fact), widened by how far the
   guide lets the arc centre move between the touch-off and the cut: the swing
   arm's measured `pivot_play` (twice for a master on the arm, which moves with the
   beam at the touch-off too), or, on a rail, `2 × g × (rail_form_error +
   roller_runout / 2)` with the rollers' gain `g = (|sin a| + |sin b|) / |sin(a −
   b)|` for rollers at `a` and `b`, each plus its finite-geometry terms (a linear
   gain alone is no bound; one that does not converge leaves the cut unknown); it
   must lie inside the radial band (a rough
   stage's moved off the line by its allowance, the cutter backed off that
   allowance along `touch_axis` on the DRO grid, the only handwheel move, and
   widened by how far that move misses its radial one with the cutter beside the
   radial line: one DRO step plus the pivot play for a centred setting bar, or a
   rail centre's sideways shift `(|cos a| + |cos b|) / |sin(a − b)|` times its
   rollers' 0.1 mm print rounding plus its form error and half its runout), then by
   one explicit safety margin, the machine's DRO resolution (one display step,
   `margin_mm`), which the start's clearance carries too. Bound terms provably
   smaller than that margin are absorbed rather than modelled (a setting bar touched
   up to a step beside its line, a touch axis leaning within its one-step tolerance;
   [#272](https://github.com/pedropaulovc/prechips/issues/272)); a DRO resolution not
   stated as a measured fact, or a cutter-centre reach under two steps, leaves the
   margin unproven. The
   rows sample the cutter-centre arc every `step_deg` over the whole sweep, centred
   on the arc with its ends kept, so the kernel judges the cutter where the arc
   ends and where the sweep stops. A sweep shorter than the arc (by more than one
   DRO step of cutter travel), a sweep of a full turn or more or a full circle
   (either starts and ends at one fixture pose, so no pair of stops bounds it), a
   `step_deg` of 180° or more (rows half a turn apart do not show which way the
   fixture turns between them), a guide fixture that does not carry the work or of
   the wrong kind, a master that is not a setting bar or master arc, a setting bar
   on a rail, two rollers on one line through the centre, a roller that runs off
   the rail during the sweep, a worst-case cut outside the band, and a sweep sharing
   its setup with another spindle op (nothing holds the turning fixture at the setup
   pose for it, before the sweep or after; manual ops aside) are errors; an
   undeclared, unmeasured or flagged guide or master fact (a rail is never
   perfect), an unknown guide, axis, sweep, rollers or rail ends, or a sweep start
   not proven clear of the stock the setup receives (the cutter goes down there at
   every level, in air only), is unknown,
   with a `measure:` instruction for each physical fact. The traveler prints no
   DRO table for it (its contour heading and the op row's pointer name a guided
   sweep): it prints the guide's set-up, which puts the cutter on the arc's radial line
   so a rough's one-axis back-off is radial (the setting bar seated on the pin, the
   other axis centred between the bar's two sides and locked; or, on a rail, the other
   axis locked first and the rollers set from the spindle at their X/Y offsets, which
   puts the rail's centre on the spindle's line; a master arc on a swing arm gives no
   radial line, so it prints only a STOP, a finish too, until a feeler touch lifts it,
   [#288](https://github.com/pedropaulovc/prechips/issues/288)), the touch-off (spindle
   stopped, feeding the touch axis only), its lock and a blank for the DRO reading at
   the touch (the setup's zero is never reset), the master taken off the sweep's path, a rough stage's
   one-axis back-off with the direction the cutter must move (a finish after it
   raises Z, returns to the touch and continues the same numbered steps; when the op
   leaves stock for a rough sweep that does not print runnable, the finish stops
   too), a stop block at each end of the sweep, set at the touch before any back-off
   (X and Y still locked, spindle stopped, Z just clear): the fixture is moved until
   the radial stroke of the arc-end mark an earlier `scribe` op with `layout = "ends"`
   laid out in the same setup, extended, runs through the cutter's axis (whatever
   radius the master set; only the line counts, never the stroke's direction, so the
   angle's 0.1° rounding moves the stop by thousandths), then on by the overrun measured
   along the cutter's path (printed to 0.1 mm rounded down, measured on the touch path;
   the start is proven in air at that printed stop). That layout scribes marks A and
   B on the work top, each a point measured from the nearer end face and side face of
   a rectangular bar the setup receives as the plan's raw stock, square to the setup
   axes, and a short stroke through it toward the arc's centre at a printed angle to
   that side face, scribed before any op in the setup that may cut those faces; no
   such op, stock without those faces, a layout after a cut, or a cut between the layout
   and the sweep (an earlier sweep cuts its marks away) is unknown and the sweep
   prints only a STOP. Then a dry pass from stop to stop, then the sweep: spindle started, its
   direction viewed from above, its angle and cutter travel, and the time it takes
   at the op's starting feed; each sweep ends with Z raised clear of the work and the
   fixture, the op's last also stopping the spindle before anyone reaches in. An op
   stepping down in axial levels (`doc_mm`) sets the heading's top level first and,
   with Z raised, returns to the first stop for each further level, never sweeping
   straight to the full depth. The stop step prints no setup X/Y: the marks place the
   stops on the work. The setup picture draws a rail's rollers where they stand on the
   table, render-only, once the sled's `roller_dia`, `roller_height`, `bed_height`
   and `rail_side` ([inventory](inventory.md#manual-arc-kit)) and the supports under
   the work are known, and notes a pivot's post at the arc centre, off the picture
   ([rules-geometry](rules-geometry.md#renders)); a missing roller fact is a `NOT
   SHOWN` note with its `measure:` instruction, never a picture verdict. The
   worst-case cut radius stays in the report. `travel` and `headroom` do not model
   the moving fixture (its swept footprint, the stack at every pose), so a setup with
   a guided sweep is never a pass for either: each owes a `check:` debt
   ([rules-setup](rules-setup.md#headroom), [#272](https://github.com/pedropaulovc/prechips/issues/272)). Any
   unproven fact the recipe prints (the guide, its fixture or master, the cut radius,
   the touch axis, a rough back-off, the sweep and spindle direction, the sweep angle,
   path or overrun, the stops' landmarks, the cut Z or any axial level, a pivot's play,
   or a rail's rollers, ends, radius or roller positions) prints only a STOP naming
   them: nothing runnable stands beside it. So does any error or debt the rule left on
   the stage that no printed value shows (a machine not proven a mill, say).
   Manual-arc features are cut in `mm` or `in`; other units are unknown.

The former `method = "arc_table"` is an error.

## Bounds

| Field | Type (also accepts `"unknown"`) |
|---|---|
| `x` | `Vector` |
| `y` | `Vector` |
| `z` | `Vector` |

## Saw cut-off

`do = "saw_cut"` and `do = "cut_off"` remove a sacrificial end/slab with a
`tools.<blade>` whose `kind = "bandsaw"` or a hand saw (`kind = "hand_saw"`, a
hacksaw). A bandsaw blade runs on a `mill`, `bench` or `bandsaw` machine; a hand
saw only on a `bench` or `manual` one. A lathe uses its separate `part_off`
action, not this model.
The operation requires no spindle holder, direction or finished-face claim.
If a feature is authored it must resolve normally; checks cannot be attached to
an omitted feature.

```toml
[[setups.ops]]
op = 10
do = "saw_cut"
tool = "metal-blade"
cut_plane = { axis = "y", value = 87.75, keep = "below" }
```

`SawPlane` has `axis = "x" | "y" | "z"`, numeric `value` in the manifest/plan
units, and `keep = "below" | "above"` (each may be `"unknown"`). The plane is the
**blade centre**, in setup coordinates. The blade's inventory `kerf` straddles
it: below retains `coordinate <= value - kerf/2`; above retains
`coordinate >= value + kerf/2`. For a 1.5 mm kerf, the example retains Y ≤ 87 mm,
not Y ≤ 87.75 mm. The kernel removes the kerf and the discarded offcut, checks
that no finished target is removed, and hands the retained stock to later setups.

An all-saw setup (possibly with manual inspection/deburring) needs no `zero`
recipe or mill envelope; `zero_check`, `headroom`, `envelope` and `travel` state
why they are not applicable. Mixed setups still check their other machining ops.
Holding declarations, `stock_state.top_z/bottom_z`, the bound frame and routing
remain operative. Use an ordinary declared fixture (for example a saw vise with
the usual jaw/parallels fields) to obtain a modeled fixture; a bandsaw machine
identity does not invent integral-vise geometry.

The traveler prints blade-centre setting, retained edge in mm, blade speed in
sfm and descent feed in mm/min. These starting numbers come only from the cited
[`saw_cut` cutting-data row](cutting-data.md), never op-level RPM/feed overrides.
Blade-centre settings, retained edges and sourced blade speed/feed keep their
own numeric digits; a coarse drawing print class does not round machine settings.

### Hand saw on the bench, straight or to a scribed line

A saw op declares exactly one shape, else the plan is `BadInput`: `cut_plane`
(a straight cut; `cut_plane = "unknown"` while the plane is undecided), or
`follows`, the `"<setup>:<op>"` of an earlier `scribe` op whose line the cut
follows. The line must be on the saw's own workpiece: scribed earlier in the same
setup, or in a setup the saw setup's `stock_in` routing descends from (a setup with
omitted routing descends from none). A cut that follows a line also declares `allowance_mm` (positive, the
stock left outside the line for the file) and `stock_removal_bounds`, the
setup-frame box the blade and its offcut take; neither belongs on a straight cut.
Gentle curves (an R800 arc rising about 13 mm over 292 mm) are sawn by hand this
way, then filed to the line:

```toml
[[setups.ops]]
op = 20
do = "saw_cut"
tool = "junior-hacksaw"          # inventory kind = "hand_saw"
follows = "S4:10"                # the scribe op that laid out the line
allowance_mm = 0.5
stock_removal_bounds = { x = [-1.0, 293.0], y = [13.5, 20.0], z = [-1.0, 17.0] }
note = "Saw just outside the scribed line."
```

The box is the author's declaration of what the cut removes, the same contract
as a mill op's clearing box: the kernel removes only the stock inside it and does
not model break-out or chisel work (#213). When the scribed feature is an arc (its
layout in the saw setup's frame, as the `scribe` card prints it), the box is
clipped to stay `allowance_mm` outside that arc: outside the circle grown by the
allowance for a part inside it, inside the circle shrunk by it for a part outside
it. The removal then follows the curve, as the operator's blade does. A straight
scribed line keeps the box alone. An arc whose layout in the saw setup is unknown,
or an unknown allowance on an arc, removes nothing and is `?`. An omitted or
unknown box removes nothing and is plan-input debt: the `saw_cut` finding is `?`
with "declare stock_removal_bounds for <setup:op>", and later stock stays unknown.
The removal must stay at least `allowance_mm` clear of the finished target, else
`✗`. The following `file_to_line` checks the stock it actually meets against the
shop's `max_filing_stock_mm`, and counts this saw as the rough it finishes.

A powered bandsaw follows a scribed curve the same way in vertical mode, the work
fed by hand on its table: a `bandsaw` blade on a `bandsaw` machine whose
inventory `saw_modes` include `"vertical"`. Modes without `"vertical"` are `✗`;
undeclared modes, an unverified machine or blade (its kerf included) are `?`; a
bandsaw blade following a line on a mill or bench is `✗`. Blade speed comes from
the cited `saw_cut` row as for any bandsaw cut, but there is no descent feed: the
card prints "by hand along the line" and "leave <allowance> mm outside the line".
A straight bandsaw cut needs no vertical mode.

```toml
[[setups.ops]]
op = 10
do = "saw_cut"
tool = "bandsaw-blade-4-6"       # kind = "bandsaw"; machine saw_modes = ["horizontal", "vertical"]
follows = "S4:20"                # the R816 arc's scribe
allowance_mm = 1.0               # left for the trammel pass
stock_removal_bounds = { x = [-150.0, 150.0], y = [-10.0, 6.0], z = [-20.0, 1.0] }
```

A setup on a `bench`/`manual` machine whose saws all use a verified `hand_saw`
tool, with otherwise only bench actions (`fit`, `inspect`, `deburr`, `coating`, `scribe`,
`file_to_line`), is manual bench work: its DRO, zero and headroom screens are
`not_applicable` and `speeds_feeds` gives the hand saw no blade speed or feed. A
powered or unresolved blade on a bench machine waives nothing. The traveler
prints a bench hand saw on the assembly / finishing card: "Hand saw, blade
centred on Y 87.75 mm; keep the side below it", or "Hand saw outside the line
scribed in S4 op 10, leave 0.5 mm for filing".

