<a id="plan-format--plantoml"></a>

# Plan format: `plan.toml`

`plan.toml` declares the stock, setup sequence, workholding, DRO pickups,
operations and inspection procedures for one part. This reference defines its
fields, identity checks and unresolved-value behavior. A loaded plan is not
proof that a physical setup or machining process is safe.

Use the [quickstart](manual/quickstart.md) to check a bundle, the
[tutorial](manual/tutorial.md) to follow the input-to-sheet workflow, and the
[demonstration](manual/demo.md) to compare a shipped example with observed
output. For command options, see the [CLI catalog](reference/cli.md).

Find fields by domain:

- [Root fields](#root-fields), [drawing identity](#drawing) and [input paths](#paths).
- [Frames](#frames), [target and faced aims](#aims), [joint features](#joint-features)
  and [stock-preparation features](#process-features).
- [Stock](#stock), [prepared blanks](#prepared-blank), [profiled blanks](#profiled-blank),
  [setup routing](#setup) and [assembly joints](#assembly-joints).
- [Stock state](#stockstate), [holding](#hold), [indexing](#index) and
  [support references](#reference).
- [DRO declaration](#dro), [zero recipes](#zero), [axis pickups](#axiszero),
  [datum transfer](#transfer) and [tool touches](#tooltouch).
- [Operations](#operation), [contours](#contour), [manual arcs](#manual-arcs)
  and [saw cuts](#saw-cut-off).

Output layout and render binding belong to the
[report and setup-sheet reference](report-and-telemetry.md); sampled-geometry
limits belong to the [geometry rules](rules-geometry.md).
Use [troubleshooting](manual/troubleshooting.md) for unresolved inputs and
the [FAQ](manual/faq.md) for product-scope questions.

<a id="input-conventions"></a>

## Validation and unknown values

All five input documents are UTF-8 TOML, parsed by `tomllib` and strict
Pydantic 2 models in [`model.py`](../src/prechips/model.py). Unknown keys are
forbidden at every modeled record (`extra="forbid"`). Only explicitly declared
dictionaries, such as feature identities and `checks`, accept arbitrary keys.
Floats must be finite, and booleans are not numeric substitutes.

| Type used in this reference | Accepted value |
|---|---|
| `Number` | A numeric float or the literal `"unknown"` |
| `Vector` | A list of Numbers or `"unknown"` |
| `Citations` | A string or a list of strings |

Text fields can also carry the literal `"unknown"`. It declares unresolved
information, never a zero, a measurement or an approval. A rule can reject a
known value or leave a missing fact unresolved even when the schema accepts it.

Fields in the generated `record()` models are optional and accept `"unknown"`
in addition to their displayed types. Declarations with required fields, such
as plan frames, aims, joint features and process features, state those
requirements in their own sections. Required root fields must also be present.

Omitted `Setup.machine` and `Operation.do` become `"unknown"` and remain in
the loaded bundle so rules can report unresolved identity or applicability.
Other optional fields stay absent when omitted. In particular, omitted
`retouch_after` is unknown, not an empty list; field presence can change rule
applicability.

The snippets below are TOML fragments for the named records, not standalone
plans. They require the surrounding root fields, setups, features and inventory.

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
| `workpieces` | `dict[str, WorkpieceInstance] \| Unknown` | Optional; explicit registered copies of the canonical target |
| `aims` | `dict[str, Aim]` | Optional |
| `joint_features` | `dict[str, JointFeature]` | Optional |
| `process_features` | `dict[str, ProcessFeature]` | Optional |
| `setups` | `list[Setup]` | Required |

### Required identities and execution order

`part`, `features` and `setups` are required. The loader also requires:

- A nonempty setup list with known, unique setup ids. An id cannot be blank
  or whitespace-only, `"stock"`, or a name beginning with `"stock."` or `"stock_out."`.
- A nonempty operation list in every setup, with known operation numbers that
  are unique within that setup.
- A plan `part` that matches the manifest's `part`.
- Operation feature identities in the manifest, plan-owned `joint_features`
  or plan-owned `process_features`. A saw stock cut may omit `feature`, but
  inspection checks require a named feature.

Use `[[setups]]` and `[[setups.ops]]`. Execution follows authored array order,
not numeric sorting of operation ids. Setup-frame validation is described under
[Frames](#frames).

## Frames

`[frames.<name>]` declares a plan-owned setup transform that the CAD export
does not carry. It uses the manifest's [`Frame`](features.md#frame) fields:
`origin` and the three-component `x/y/z` basis are in the model frame, with
orthonormal, right-handed basis checks. Plan frames also require two declarations
that exported frames may omit:

- `binding` must be stated, if only as `"unknown"`. `"nominal"` lets the
  transform place model geometry in setup coordinates; `"unknown"` keeps the
  numeric transform for display while operation Z endpoints stay setup-local.
- `cite` must be non-empty. The bundled examples mark authored transforms with
  `AUTHOR'S CHOICE` in that citation, before their drawing/model sources.
  The operator-facing `note` describes orientation and physical pickup debt;
  it need not repeat the citation marker.

A setup's `frame` resolves to the exported manifest frame of that name, otherwise
to the plan frame. A plan frame whose name is already exported (including an
exported `"unknown"` frame such as `setup`) is bad input, so a plan can never
shadow CAD-owned geometry. Feature `frame` references and `sweep_frame` stay
manifest-only. Plan frames are never merged into the manifest or its hash; rule
citations carry `plan.frames.<name>: author-declared setup frame` followed by
the frame's own `cite`, while exported setup frames keep their manifest
provenance.

When the manifest's `frames` value is a dictionary, the loader rejects a known
setup `frame` that names neither an exported frame nor a plan frame. When the
manifest frame collection is `"unknown"`, that membership check cannot establish
the exported names. A literal `"unknown"` setup frame remains unresolved.

An operation's retained-output `pose` uses the same `PlanFrame` record inline,
not a frame-name reference. Its forward material-registration convention is
defined under [retained part-off outputs](#retained-part-off-outputs); it is not
the model-to-setup coordinate conversion.

### Registered workpieces

`[workpieces.<id>]` registers a physical copy of the canonical finished target.
Each `WorkpieceInstance` has a required `pose: PlanFrame | "unknown"` and
nonempty `cite`. The forward pose uses the same model-coordinate convention
as [retained outputs](#retained-part-off-outputs); its origin uses manifest
units. It does not change canonical STEP bytes, face references or feature
definitions. Cite an author-selected registration as `AUTHOR'S CHOICE`, not
as a shop measurement.

Declared membership alone does not prove that the target fits arriving stock.
Native containment must bind the exact member, registration and current
material path. Missing registration/protection stays unknown. A target known
to lie outside actual arriving stock is a containment error and earns no
geometry credit; another member cannot supply its missing evidence.

Use [member-qualified cutting claims](#member-qualified-cutting-claims) when
several members arrive together. An unqualified claim selects a registered
member only when exactly one member is carried. Explicit unknown registration
is debt, never an inferred empty batch.


## Aims

`[aims.<feature>]` selects a process target inside one printed drawing band.
It has two forms:

- Without `face`, it shifts a located feature's DRO target from drawing nominal.
  The height-like requirement from its `height_from` reference
  (`height_above_pivot`, `height` or `separation`) then reads the aimed value.
  This changes only the printed target, never the STEP, manifest, cutting claim
  or kernel input.
- With `face`, it moves a faced plane in the part the kernel cuts. The length
  between the feature's `lower_z` and `upper_z` planes then reads the aimed value.

| Field | Meaning |
|---|---|
| `requirement` | The requirement the aim sets. It must be one of the feature's exported drawing requirements |
| `value_mm` | The value, in mm, that the requirement reads at the aim. It must lie inside the printed band |
| `reason` | Known text. The bundled examples begin it with `AUTHOR'S CHOICE` |
| `face` | Optional. The faced plane that moves, a ref from the feature's own `faces` |

The `<feature>` must be a manifest feature that exports `requirement`.
`value_mm`, converted to the manifest units, must lie inside that requirement's
band as the sheet prints it. Anything else is bad input.

### Target aims

For an aim without `face`, the
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

### Faced aims

An aim with `face` also requires:

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

#### Kernel construction and unresolved cases

The kernel builds the aimed part under these constraints:

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

Every setup uses that face position for its protected part, removal bounds,
in-process stock, clearances, pictures and stock facts. A frame and zero on the
aimed face therefore agree with the stock an earlier setup leaves. The finished
part is the aimed part, with the value still inside the printed drawing band.

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
- faced aims on multiple finished solids, which are not modelled;
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

### Mouth edges and unresolved geometry

A `cylinder_bore` may also state its mouth edges as made: `edge_break = { kind =
"sharp" }`, or `{ kind = "radius" | "chamfer", size = s }` in manifest units (`size =
"unknown"` is debt). The mouths are the `at` end and, when `thru`, the far end too.
Only a joint that [forms](#assembly-joints) a feature reads it. A spigot carries no
`edge_break`, and a sharp break with a size, a sized break without one, or a
nonpositive size is bad input (exit 3).

Unsuffixed lengths use the manifest's model units; `axis` is dimensionless.
Known geometry must satisfy these constraints. Literal numeric `"unknown"`
remains debt and cannot create a solid, an inferred nominal, or a successful
assembly. Identity fields and citations are not numeric debt: missing/unknown
kinds, components and references are bad input. Optional `requirements` is a
subset of `["dia"]` and defaults to that list; depth is finite construction
geometry, not an invented depth tolerance. Optional `precision` and `note`
retain normal dimensional/display semantics.

### Preparation and finished-face credit

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

`[process_features.<id>]` declares stock preparation that a later setup relies
on. These features have no drawing-surface identity:

- `end_face`: a faced stock end.
- `centre_hole`: a combined drill-and-countersink seat for a later dead or live centre.
- `tooling_hole`: a locating hole in the work's waste, used by a later fixture
  pin until a waste cut removes it.

Identities must not collide with exported or joint features. A
`plan.process_features.` label can never be used as a finished face reference.

Every process feature requires `kind`, `at`, `axis` and a usable `cite`.
`at` and `axis` can be literal `"unknown"`; a known axis must be a unit vector.
The remaining required or forbidden fields depend on `kind`, as described below.

| Field | Meaning |
|---|---|
| `kind` | `end_face`, `centre_hole` or `tooling_hole` |
| `at` | Point on the stock end, model coordinates (manifest units); a centre's mouth centre, on the entry surface its quill is touched on |
| `axis` | Unit inward normal of that end, pointing into the kept material (the drilling direction) |
| `cite` | Nonempty author/source citation |
| `size` | `centre_hole` only: the source's size name |
| `drill_dia_mm` | `centre_hole` only: pilot drill diameter D |
| `drill_length_mm` | `centre_hole` only: pilot length C from the countersink to the tip, point included |
| `mouth_dia_mm` | `centre_hole` only: countersink diameter at the face; must exceed `drill_dia_mm` |
| `countersink_angle_deg` | `centre_hole` only: included countersink angle, between 0 and 180 |
| `dia` | `tooling_hole` only: its `[lo, hi]` size band (manifest units), `lo > 0` |
| `thru` | `tooling_hole` only: `true` for a hole through the stock |
| `depth` | `tooling_hole` only: full-diameter depth below `at` (manifest units, > 0) of a blind hole |
| `note` | Optional text |

### Centre holes

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

### Tooling holes

A `tooling_hole` needs `dia` and exactly one of `thru = true` or `depth` (each
numeric value may be `"unknown"` debt); the other kinds author none of `dia`,
`thru` and `depth`, and it authors no centre field. Its `at` is the mouth centre
on the entry surface and `axis` the drilling direction. It resolves as a plain
`hole` with no drawing requirements, so its ops get the ordinary hole rules:
[`blind_depth`](rules-operations.md#blind_depth-tip-endpoints) tip endpoints
(a through hole reads the setup's `stock_state.local_thickness.<id>` and the op's
`exit_mm`), speeds and feeds, reach, accessibility and headroom, and `sizing`
judges its finishing tool (the ream when there is one, else the drill) against
`dia`. Only `spot`, `drill` and `ream` make it: the ream finishes the band, the
drill roughs it and the spot only starts it (its point, to its own `depth_mm`), so
the hole chain is the one [`op_chain`](rules-operations.md) asks of any hole. A later setup's fixture or clamp solid whose `locates` names it is its
locating pin ([inventory](inventory.md#kernel-geometry-facts-m4)); the always-required
[`tooling_hole`](rules-setup.md#tooling_hole) rule judges that pin's fit and
refuses a setup that names a hole a waste cut has removed.

```toml
[process_features.cl_tooling_hole]
kind = "tooling_hole"
at = [-160.8945, 24.176, 1.25]
axis = [0.0, 0.0, -1.0]
dia = [6.010, 6.022] # F7 on 6, sized for the carrier dowel
thru = true
note = "tooling hole in the -X end waste; the carrier dowel locates on it; sawn off with the waste"
cite = ["harmonic-analyzer ch_rocker_arm_tl_oblique_trammel_spec.py CL"]
```

### End faces and parting

An `end_face` is any planar face of the stock: a turned end, or one of the six
faces of a rectangular blank a mill squares before S1. On a rectangular root stock
square to the model axes, each `end_face` square to a model axis carries derived
`bounds`: the root stock's section in that plane. A later setup's footprint of the
face is those bounds trimmed by every process face an earlier setup in its stock
lineage made, so a blank face is always cut whole. Round, built-up or unaligned
stock gets no derived bounds.

`face`, `rough_face`, `finish_face` and, on a lathe, `part_off` prepare an
`end_face`. A part-off parts the disc at its `to_z`: the end face's `at` must lie
on that setup Z and its `axis` must point along setup +Z, into the piece toward
the exposed end that the route keeps; the remainder stays in the chuck with the
bar. The disc must lie clear of the finished part. A part off over length then
names an `end_face` that a later setup faces to the finished length. Here the
setup frame's Z is model +Z with its origin at model Z +4.2:

```toml
[process_features.hub_supply_bottom]
kind = "end_face"
at = [0.0, 8.0, -4.2]
axis = [0.0, 0.0, 1.0]          # into the kept hub
cite = ["AUTHOR'S CHOICE: parted 0.67 over the finished hub face"]

[[setups.ops]]
op = 60
do = "part_off"
feature = "hub_supply_bottom"
to_z = -8.4
```

An axis off setup Z or pointing toward the chuck, or an `at` on another Z than
`to_z`, is a [`parting_face`](rules-geometry.md#parting-face)
error and the kernel does not cut it; an unknown `at`, `axis`, `to_z`, frame or
machine kind is `?`. Either leaves the later stock unknown. A part-off that
names a finished drawing face follows the ordinary parting contract.
`cut_to_fit` never prepares an `end_face`: it keeps the chuck side and drops the
free end, the opposite of a part-off.

On a mill, `profile`, `rough_profile` and `finish_profile` can side-mill an
`end_face` with the cutter's periphery, for example on a blank end overhanging
the vise. Give its `linear_table` contour an `open_side` so the passes step in
from clear air. See [coordinates](rules-coordinates.md).

### Operation and coverage boundaries

`spot` or the centre-specific `center_drill` prepares a `centre_hole`; only
`spot`, `drill` and `ream` prepare a `tooling_hole`. A process-feature op names
exactly that one feature and carries no `faces`, `checks` or
`missing_requirements`. It has no drawing limit to inspect. The loader rejects
a process feature in an inspect op's
feature list. A list inspect elsewhere in the setup does not change the
tooling hole's [`tooling_hole`](rules-setup.md#tooling_hole) rows.

Process cuts use the ordinary speeds and feeds, reach, accessibility, headroom,
tip endpoint, holding and fixture-model rules. The kernel removes the analytic
centre (countersink, pilot and point), the tooling hole (tool diameter through
the stock or to depth, with a drill point below), or a planar slab of arriving
stock for an end face. The setup picture and the next setup's entry stock show
those cuts.

A process feature earns neither finished STEP coverage nor finish coverage,
even on a drawing plane, and never becomes a drawing-requirements row.
`hold.centre_hole` names the process centre that supports a dead or live centre
([Hold](#hold)). Use [`stock.prepared`](#prepared-blank) to declare the squared
blank made by process faces.

## Drawing

| Field | Type (also accepts `"unknown"`) |
|---|---|
| `number` | `str` |
| `revision` | `str` |
| `cite` | `Citations` |

`[drawing]` records the drawing identity and its source citations. It does not
replace the exported dimensional requirements in the [feature manifest](features.md).

## Paths

| Field | Type (also accepts `"unknown"`) |
|---|---|
| `inventory` | `str` |
| `policy` | `str` |
| `cutting_data` | `str` |
| `step` | `str` |

### Path bases and precedence

`features` is relative to the plan and must stay inside the bundle root. The
root is the repository above `examples`, or the first ancestor with
`pyproject.toml`; otherwise it is the plan's parent.

Shared inventory, policy and cutting-data selection uses this precedence:

1. Explicit CLI override.
2. A known `[paths]` declaration.
3. `PRECHIPS_INVENTORY` or `PRECHIPS_POLICY`, where applicable. Cutting data
   has no environment fallback.

Omission or literal `"unknown"` in `[paths]` permits the environment fallback.
Plan-declared shared paths resolve relative to the plan and must stay inside
the bundle root. CLI and environment paths resolve relative to the working
directory and may be external. If no known policy path is selected, the loader
uses only the shipped required-rule vocabulary; it does not invent shop numbers.
See [policy selection](policy.md) and the [CLI catalog](reference/cli.md).

### STEP identity

Referenced STEP assets are read, hashed and contained inside the bundle.
An unreadable STEP file, a path outside the bundle, bytes that do not match
a known manifest `step_sha256`, or a known digest without its STEP bytes is
`BadInput` (exit 3), not a geometry unknown. The manifest digest must be the
literal `"unknown"` or a 64-character lowercase hexadecimal SHA-256; a
malformed digest is also `BadInput`.

An unknown digest can load, but cannot authorize the geometry job. With a
matching known digest, geometry rules share one FreeCAD job per run; missing
or unresolved geometry inputs remain `?`. See the
[geometry rules](rules-geometry.md) for kernel eligibility and limits.

## Stock

`[stock]` declares the candidate supply. Its geometry is an authored material
envelope; it does not establish measured dimensions or confirmed stock on hand.

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

### Component blanks

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

### Envelope placement and branch independence

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

### Supplied faces and construction permission

`as_is_faces` lists STEP face references (same forms as a feature's `faces`)
that stay as supplied stock; the M4 `coverage` rule unites them with the faces
claimed by cutting operations and those a joint [forms](#assembly-joints). An omitted list is unknown, not empty. On a
[profiled blank](#profiled-blank) each listed face is credited only when it is
supplied as cut within its drawing bands.

Root `construction` declares the candidate route, independently of the
drawing-side manifest permission. `built_up` is refused unless
`features.construction = "built_up_permitted"`: unknown or omitted drawing
permission does not lift the one-piece-only restriction. An explicit `one_piece`
candidate needs no such permission. An omitted plan `construction` remains
unknown; it is not an implicit one-piece declaration.
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
`section_1`, `flat`, `square` and `parallel`. `PreparedMethods` supplies the
written `flat`, `square` and `parallel` procedures; `PreparedForm` supplies
their limits.

A known `setup` that is not a plan setup is `BadInput`. An omitted or literal
`"unknown"` setup remains unresolved. A prepared blank on round, built-up or
profiled stock is `BadInput` because there is no rectangular root box to trim.
The [`prepared_blank`](rules-setup.md#prepared_blank) rule checks the size,
kernel-cut stock and inspection declarations. The receiving setup's sheet
prints CHECK THE BLANK, with each form row's limit and method.

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

This fragment abbreviates the hash. Replace it with the full lowercase SHA-256
of the blank STEP before loading the plan:

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

Author the blank STEP in the part model's coordinates, with the finished part
placed inside the solid that the vendor cuts. The STEP defines the supply's
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

`[dro]` declares a digital readout or mechanical handwheel dials, their source
manual and display convention. Unknown installation facts remain unresolved.

| Field | Type (also accepts `"unknown"`) |
|---|---|
| `kind` | `"digital" \| "handwheel"`; omitted preserves the digital contract, explicit `"unknown"` does not |
| `controller` | `str` |
| `manual` | `str` |
| `manual_url` | `str` |
| `mode` | `str` |
| `units` | `str` |
| `radius_mode` | `bool` |
| `direction` | `Direction` |
| `graduation` | Positive `float`: source nominal dial division in `dro.units`, on the declared radius/diameter scale |
| `procedure` | `str`: source-authored operating procedure |
| `backlash` | `str`: authored backlash/take-up procedure or unresolved fact |
| `calibration` | `str`: authored calibration fact, not an inferred measurement |
| `cite` | `Citations` |

`radius_mode` selects the lathe X display convention: radial physical X jogs
read once in radius mode and twice in diameter mode. It does not change a known
mill's linear axes. In a mixed-machine route, the traveler labels the actual
setup machine's display convention rather than applying the lathe label to all
setups. Omitted or unknown on a lathe, no X reading is printed: the feature map,
part-off X and dome tables stop rather than assume a display
([coordinates](rules-coordinates.md#coordinates)). Unknown controller/install
facts remain unresolved independently.

For `kind = "handwheel"`, `units = "in"` or `"mm"` selects the printed nominal
target units; it does not change manifest geometry units. A nominal
`graduation` is neither a measured digital resolution nor calibration evidence.
Use the authored procedures and explicit [physical dial settings](#axiszero),
not electronic Axis Set or Preset instructions. Unknown readout kind, units,
datum, graduation, calibration or backlash remains debt. The
[mechanical-readout rules](rules-coordinates.md#mechanical-dials-and-unknown-readouts)
define the current unresolved physical-registration boundary.

## Direction

`[dro.direction]` records the authored direction text for each axis.

| Field | Type (also accepts `"unknown"`) |
|---|---|
| `x` | `str` |
| `y` | `str` |
| `z` | `str` |

## Setup

Each `[[setups]]` record selects a machine, frame, entering stock, hold and
operation list. The records run in authored order.

| Field | Type (also accepts `"unknown"`) |
|---|---|
| `id` | `str` |
| `machine` | `str` |
| `frame` | `str` |
| `coolant` | `str` |
| `stock_in` | `str \| list[str]` |
| `joint` | Tagged cylindrical, surface or threaded joint (required for array `stock_in`) |
| `note` | `str` |
| `deburr_mm` | `Number` |
| `deburr_cite` | `Citations` |
| `stock_state` | `StockState` |
| `hold` | `Hold` |
| `zero` | `Zero` |
| `ops` | `list[Operation]` |

### Manual stations and travel scope

For a manual joining, finishing, layout, threading or inspection station,
declare the inventory machine's `kind = "bench"` (or `"manual"`) and use only
`fit`, `inspect`, `deburr`, `coating`, `scribe`, `file_to_line`, `die_thread`
or `hand_tap` operations, or `saw_cut`/`cut_off` selecting a verified `hand_saw`.
`zero_check`, `coordinates` and `headroom` are then `not_applicable`: the station
has no DRO, cutter-centre table, spindle stack or machine travel to check.
The joint's joining method does not create machine axes. Powered cuts or
explicitly unknown actions retain the normal screens; the bench name alone
cannot waive an applicable check.

A separate manual-thread-only scope makes `zero_check` and `coordinates`
`not_applicable` when the resolved machine has known kind `bench`, `manual`,
`lathe`, `mill` or `drill_press`, the setup contains at least one `hand_tap`
or `die_thread`, and every operation is a supported manual action. Unknown
actions or machine kind, or any powered cut in the same setup, retain normal
zero/coordinate obligations. This scope does not extend the bench-only
headroom exemption or waive tool selection, causal preparation, holding or
native geometry debt. See
[manual-thread-only applicability](rules-coordinates.md#manual-thread-only-applicability).

The holding rule likewise requires no machine fixed-jaw orientation or stock
top/bottom Z station for established manual bench work, or for a verified
bench/manual station used only for known non-spindle saw cuts and manual
actions. This includes a portable bandsaw cutting work held in a bench vise;
it does not waive powered-saw cutting data. Mechanical work, including manual
threading, still needs declared holding. Inspection/coating-only work may instead declare
`hold.note` for its actual handling, but only when no other holding fields
are supplied; missing or unknown handling is not complete. See
[manual bench holding and handling](rules-setup.md#manual-bench-holding-and-handling).
Physical joint, stock, frame, applicable render and mechanical holding checks
are not waived.

For component stock, an earlier setup output or a joint output, the mill
headroom X/Y travel screen uses the kernel's setup-entry stock bounding box,
before the current setup's cuts. It substitutes neither the finished part nor
the original raw blank. Missing entry stock remains geometry debt.

### Stock lineage

`stock_in` selects one source or an explicit two-branch assembly:

| Value | Source |
|---|---|
| `"stock"` | The single root supply, only when stock has no component blanks |
| `"stock.<id>"` | One built-up stock component |
| An earlier setup's `id` | That setup's single output, not necessarily the previous setup; a named split must instead use its `stock_out` references |
| `"stock_out.<name>"` | One [named retained part-off output](#retained-part-off-outputs) |
| An array of two references | Two material-disjoint branches joined by an explicit `joint` |

Bare `"stock"` is bad input when `stock.components` is a nonempty list; name
`"stock.<id>"` instead. Declaring `joint` requires an array `stock_in` with
exactly two references. A joint with scalar or omitted `stock_in` is bad input.

Unknown or forward references, including an authored `"unknown"` source, are
`BadInput` (exit 3). An omitted `stock_in` stays stock debt; it does not imply
a linear route. Supplies and ordinary setup outputs remain in the model frame;
a retained output's explicit `pose` registers its material into that frame.
A join reference never applies an implicit assembly transform or a generic
Boolean union.

Named-retained material is single-use: each `stock_out` reference, downstream
partitioned setup state and unsplit setup predecessor feeding the split may
be consumed only once. Registered-member routes also consume the original raw
supply once. Ordinary no-cut fan-out and selectable-state rework outside
these lineages retain their legacy behavior; raw supply aliases do not create
extra physical blanks.

A material identity consists of its supply root and ordered partition path.
Each edge is `{split: <actual setup id>, output: <global output name>}`.
At the first differing edge, different outputs of the same split are disjoint;
equal or ancestor/descendant paths overlap. Operation provenance such as
`S1:10` is recorded separately and is never parsed into a setup identity.
The host rejects overlapping identities; native geometry independently proves
the physical split and non-overlap.

A producing setup with named outputs cannot be consumed by its setup id.
Registered finite-saw outputs can be split again through nested named outputs;
assembled input is not permission for an arbitrary split. Ordinary machining
and `keep` on a retained child's later setup remain supported.
Producer history alone does not prove that a centre, touch face or other
preparation survived on either child. See
[causal preparation](rules-operations.md#op_chain).

### Assembly joints

Every array `stock_in` requires a singular tagged `joint` declaration and
exactly two material-disjoint input branches. Either input may be an
already-joined assembly if the other input is one single component. Thus
`["body", "cone"]` may produce `J1`, followed by `["J1", "crank"]` producing a
three-component assembly. Joining two existing assemblies, one-piece arrays
and arrays with more than two references are bad input (exit 3). Shared supply
ancestry is allowed only for the retained siblings described above, never
overlapping material. Each interface identity is consumed only once.
Joint geometry is in the model frame, regardless of the assembly setup's frame.
A missing or malformed identity/reference is bad input; unknown geometry or
joining-process facts withhold joined stock as named debt. A threaded joint
also retains the explicit unmodelled-geometry boundary below.

#### Cylindrical fit

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

#### Threaded joints

A removable threaded assembly declares `kind = "threaded"`. It uses exported
finished features, not transient `plan.joint_features`, and never takes the
cylindrical fit's `method`, `fit`, clearance/interference band or `compound`.
Every field below is required; none is inferred from a name or assembly note.

| Field | Type and meaning |
|---|---|
| `kind` | `"threaded"` |
| `socket` | Known exported feature id of kind `thread` or `threaded_hole` |
| `spigot` | Different known exported feature id of kind `external_thread` |
| `process` | Known nonempty assembly instructions |
| `cite` | Nonempty citations for the thread and assembly source |
| `engagement_mm` | Finite number or `"unknown"`: actual axial thread engagement in mm, not the male stub length |
| `seat` | `ThreadSeat` below or `"unknown"` |

The exported features carry their own nominal `thread`, `thread_hand` and
`thread_class` facts. Each interface must resolve to a different consumed
material branch and must not be reused by another threaded joint. A known
mixed-solid interface or same-finished-solid pair is bad input. Unknown face
identities or retained-material survival remain debt, not a guessed owner.
See [threaded features](features.md#threaded-features) for their field contract.

`ThreadSeat` requires all four fields below. Each may be `"unknown"`.

| Field | Type and meaning |
|---|---|
| `socket` | `JointInterface`: finite shoulder-seat patch on the socket |
| `spigot` | `JointInterface`: finite shoulder-seat patch on the spigot |
| `gap_mm` | Finite number: declared normal separation of the seat patches in mm |
| `runout_clearance_mm` | Finite number: declared runout clearance in mm |

Each `JointInterface` requires `at`, `normal`, `x`, `size_mm` and nonempty `cite`.
`at` is its model-frame centre in manifest units; `normal` and `x` are unit
orthogonal directions. `size_mm = [width, height]` gives positive full side
lengths in mm, with `normal × x` the height direction. Each geometry field may
be `"unknown"`. This is the same finite-patch record used by
[surface joints](#surface-joints-and-material-protection), not an inferred
shoulder from a cylinder's bounding box.

The declared-input [`joint_thread`](rules-tools.md#joint_thread) rule rejects
known contradictions in supported nominal size/pitch, hand, class role,
collinear axes, positive finite threaded depth and engagement. Engagement may
not exceed either threaded depth or the finite envelope overlap. Negative gap
or runout clearance, a positive seated gap, non-opposing seat normals,
separation inconsistent with the gap, or disjoint finite seat patches is an
error. A zero-gap seated male thread longer than the socket's threaded depth
is also an error. Length comparisons use a 1e-6 mm equality tolerance.
Unknown or unsupported facts remain unresolved.

Agreement is not a physical thread-fit, strength or retention verdict. The
engine does not model helical flanks, lead/runout or prepared shoulder contact,
so both `joint_thread` and native `joint_assembly` remain unknown even when
nominal facts agree. No annular bond fill, press fusion or certified joined
stock is produced. Omitted `forms` defaults to an empty list; a nonempty list
is bad input because a removable thread forms no bonded finished faces. See
the [native assembly boundary](rules-geometry.md#removable-threaded-assembly).

#### Retaining compound

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
The setup sheet prints the prep, cure time and "do not disturb until cured"
once before later machining: on the first `fit` op, which bonds the joint, or
otherwise in the setup's "Starts from" line. The `fit` op's material or
consumable cell names the product. A press fit with compound prints "press in
with the compound on the interface, then do not disturb until cured".

This process declaration does not model cure kinetics or certify a product.
Cite the source or authored choice for the band and cure conditions. A joint
without compound prints no prep or cure. Use the noncutting bench action
`do = "fit"`; `fit_up` and `bond` are not declared actions.

#### Faces formed by a joint

A cylindrical or surface joint may declare `forms`, a list of exported features whose finished
faces the join itself forms and no op cuts. The usual case is a root fillet whose
drawing limit admits the sharp corner the join leaves: a hub pressed through a
strap, with its root printed `2X R0.2 MAX` (`radius = [0, 0.2]`). The list goes on
the joint because forming the faces is a fact about the join. The exported manifest
is a consumer export that the plan does not edit. Rules for `forms`:

- Each entry names an exported feature with a `radius` band.
- An entry naming a plan joint feature is bad input (exit 3).
- An entry naming the same feature twice, in one joint or in two, is bad input
  (exit 3).
- An entry naming a feature with no radius band refuses the join.

The kernel checks the joined corner against the band (see the [assembly
backstop](rules-geometry.md#transient-joint-preparation-and-assembly)). It judges the
joined geometry with the socket's mouth breaks included, so a cylindrical joint that
forms a feature needs its socket's mouth `edge_break`. The spigot runs through the
corner and has no edge there.

- A sharp mouth leaves the sharp corner admitted by the band.
- A radius or chamfer mouth leaves a groove around the spigot, neither a fillet
  nor a sharp corner. The join is refused.
- The mouth break needs a flat socket face square to the axis. An authored end
  in air, or a saddle on a curved face, leaves the formed feature unresolved
  even if its other checks pass. A through socket authored past its material is
  one such case.
- An omitted or unknown break leaves the formed feature unresolved. Lost
  material at its faces withholds the joined stock; loss elsewhere is still refused.

The drawing's general `edge_break_r`/`chamfer_max` is not read for this. That
allowance is a maximum and does not say what this mouth carries.

Before the join, the corner a formed feature fills is finished material of neither
branch. Its corner is the finished material between the feature's faces and the
sharp corner where their neighbouring faces meet. A face op on the strap may take
that ring with the rest of its stock, and so may a ream, so the strap arrives with
a plain face for the join to judge. The kernel finds the corner by removing the
feature's faces from the finished solid and extending their neighbours. It withholds
a corner only when the band starts at 0, every face is mapped, the sharp solid adds
no material, and every point of the corner lies within the band's MAX of the
feature's faces. Otherwise the branches continue to protect that material as finished.
The join still judges what is actually lost against the band, so nothing beyond
the MAX is ever admitted.

The band must start at 0, with no missing material beyond its MAX. `coverage`
credits the formed faces only when the last op that names the feature and
checks its `radius` band passes. That op must be downstream of the joint, or
in the joint setup after its first `fit`. A setup without `fit` joins on entry.
Without the check, credit stays unresolved. A [limit leaf](rules-inspection.md)
at or below the MAX is sufficient when its declared leaf tolerance is zero or
omitted. This fragment shows the joint and sharp-mouth declarations; the
commented joint-feature fields must also be supplied:

```toml
[setups.joint]
kind = "cylindrical"
socket = "strap_hole"
spigot = "hub_land"
fit = "interference"
interference_mm = [0.005, 0.035]
method = "press"
process = "AUTHOR'S CHOICE: arbor press, hub square to the strap face"
cite = "AUTHOR'S CHOICE: H7/r6 press"
forms = ["hub_root"]   # 2X R0.2 MAX: the press leaves the root sharp

[joint_features.strap_hole]
# ... kind = "cylinder_bore", at, axis, dia, nominal_dia, depth, thru, cite
edge_break = { kind = "sharp" }   # mouths stated sharp: no break to leave a groove
```

A formed face is neither as-is stock nor a cut, so it does not go in `as_is_faces`.

This fragment uses illustrative process choices, not manufacturer specifications:

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

#### Cross-bores and sleeves

A cylindrical cross-bore socket uses the existing `cylinder_bore` kind with
`thru = true` and a finite `depth` spanning both openings. The kernel verifies
both ends are open; this is not an unbounded hole or a blind socket with a
waived bottom. A sleeve exterior is a `cylinder_spigot`, not a new feature kind.
An intentional bore already present in the sleeve is permitted only where it
does not remove required finished material; joining fills the mating annulus,
not the sleeve's core. A subsequent finished bore operation still needs its
own preparation/finish coverage and must follow the declared cure.

#### Surface joints and material protection

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

`[setups.stock_state]` describes the surfaces and section dimensions received
by the setup. It is checked against stock lineage and kernel facts, not used
to replace them.

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

### Received surfaces and local thickness

`stock_state` records received surfaces in the setup frame.
`local_thickness` is per hole, not the whole bar thickness. `entry_z` permits a
separate local entry surface.

`top_feature` names the touched face that facing advances; `top_z` is that
feature's +Z face. A facing op with `stock_removal_bounds` advances it only when
the box contains the feature's whole X/Y footprint. That footprint is its
`bounds`, or, for a bounds-free `kind = "face"`, the matched kernel box of every
listed plane at the op's `to_z`. Every listed face must resolve, and any
`contour.keep_out` island must clear the face by the cutter radius.
See [coordinates](rules-coordinates.md).

`bottom_feature` names the seated face; `bottom_z` is its -Z face. The kernel
supplies each named face's height and the entering stock's height over it.
The [consistency rule](rules-setup.md#consistency) compares these with `top_z`
and `bottom_z`.

Setup frames, stock state and authored operation bounds also supply the
geometry and spans used for [picture scale](rules-geometry.md#renders).

### Unsupported lathe span

For lathe stick-out, `north_end_z` / `south_end_z` and `hold.stickout_mm` bound
the unsupported span. Its D is the smallest finished feature diameter in that
span after transformation into setup Z; `od_mm` remains the held-stock diameter
for collet/chuck capacity, not the unsupported-section diameter.

## Hold

`[setups.hold]` declares how the arriving stock is seated, located and held.
Inventory references supply physical fixture facts; plan poses place them.
See [hold requirements](rules-setup.md#hold_fields) for applicability and
[inventory geometry](inventory.md#kernel-geometry-facts-m4) for fact trust.

| Field | Type (also accepts `"unknown"`) |
|---|---|
| `kind` | `"hand_fed"`: the work is fed by hand on a vertical bandsaw's table along a scribed line; omitted for a fixture hold. A hand-fed hold declares only `note` and its feeding (the four rows below) beside it ([hand-fed](#hand-fed-on-the-saw-table)) |
| `guide_above_mm` | `Number` (positive, hand-fed only): the upper blade guide's height above the top of the work |
| `push_aid` | `str` (hand-fed only): the inventory `fixtures` item (a push stick) that feeds the work near the blade |
| `feed_from` | `"+X" \| "-X" \| "+Y" \| "-Y"` (hand-fed only): the end of the line the cut starts from, in the setup frame |
| `end_support` | `"push_aid" \| "outfeed_table"` (hand-fed only): how the end of the cut is supported |
| `fixture` | `str` |
| `jaws_along` | `"x"` / `"y"` / `"not_applicable"`: the vise jaw length axis; any other text is bad input (exit 3) |
| `fixed_jaw` | `str` |
| `parallels` | `str` |
| `supports` | `str \| list[str \| Reference]`: each string or record's `ref` selects its fixture; list entries print the selected support name, with any operation/rest-setting metadata |
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
| `jaws_angle_deg` | `Number` strictly between −90 and 90: a vise swivelled on its base about setup +Z, the jaw line's angle from `jaws_along`, counterclockwise positive seen from above; omitted is square jaws, `"unknown"` leaves the jaws unplaced ([swivelled vise](#swivelled-vise)) |
| `jaw_bar` | `str` (fixtures `round_bar` between the work and the moving jaw) |
| `jaw_buttons` | `str` (fixtures `jaw_buttons`: one button between each jaw and the work, its spigot in the work's bore) |
| `area` | `{ ref: str, on: str }`: typed [area-hold identity](#area-hold-status). `ref` names a `consumables` `adhesive_tape` item; `on` names exactly one non-void solid of `fixture`. This is not a capacity or stack-up verdict |
| `align` | `{ indicator: str, limit_mm: Number, over_mm: Number, face: str, cite: str \| list[str] }`: how a mill vise's fixed jaw or angle plate's locating face is squared to the table travel; `indicator` is an inventory `dial_test_indicator` / `dial_indicator` gauge swept `over_mm` along the face, its reading changing no more than `limit_mm`; an angle plate's `face` names the fixture solid whose face is squared. Required where the setup mounts or turns the vise or plate ([hold_fields](rules-setup.md#hold_fields)). A swivelled vise adds `method` (`indicate_jaw`, `graduations`, `protractor`, `sine_bar`) and, for a stated method, `tolerance_deg` with its `cite` ([swivelled vise](#swivelled-vise)) |
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
| `centre_hole` | `str`: the process `centre_hole` the dead or live centre rides in; the always-required [`centre_support`](rules-setup.md#centre_support) rule needs earlier `spot` or centre-specific `center_drill` preparation on the received material, with a mouth equal to `centre_hole_dia_mm`; the kernel seats the centre in that cut countersink instead of cutting a seat of its own |
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

### Poses and clamp restraint

`Pose` is `{origin_mm, x, z}`: the origin and unit, orthogonal x and z axes of
a fixture-local frame. Each is a three-component `[Number, Number, Number]`;
the origin uses setup-frame millimetres and the axes are dimensionless.

`ClampPlacement` is `{ref, note, pose, restraint, torque_nm, tighten}`. `ref` names a fixture or a
`kit/member` such as a clamping-kit strap, and its authored `solids` are
placed by `pose` (origin at the strap underside on the work). `restraint` is
`press` (it holds the work down along pose -z), `locate` (it only positions
the work) or `none`; undeclared is `none`. Only a press clamp can hold a stock
piece split off by an op, and only when the kernel proves a load path to an
anchored support. A `locate` clamp must establish the contact its inventory
`bears` declares for every solid carrying `locates`: a pin's contact cylinder
in its locating bore (`bore`), or a flat locator's face (`face`). See
[`thin_wall_under_clamp`](rules-geometry.md#thin_wall_under_clamp).

### Protective holding method

`method` names a protective holding method in words (soft jaws, mandrel, wax).
Tape is not a method: `method = "tape"` (any case) is bad input whose message
names the `area` form.

### Area-hold status

`hold.area.ref` must resolve to a typed adhesive-tape consumable. A different
kind or category, including a qualified reference outside `consumables`, is
`BadInput`. `hold.area.on` must name exactly one non-void solid of the
selected fixture when that solids list is known. Zero or several matches are
bad input. A literal `"unknown"` identity or unresolved solids list does not
establish a seat.

The proposed tape layer covers the work's footprint on that solid's posed +z
face. Layer generation, seat checks, holding capacity and Z-stack rules have
not shipped. A named seat that is untrusted or incomplete must remain
unresolved in those future checks, never pass. Current identity validation
cannot qualify a physical hold. See [area-hold inventory](inventory.md#area-holds)
and the [implementation status](design/area-hold.md#current-status-and-navigation).

### Clamping and tightening

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

### Physical stops and available faces

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

### Vise jaws and seat height

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

### Jaw and parallel positions

`jaw_center_along_mm` is the jaw-plate centre along `jaws_along` in setup
coordinates. Without it, the kernel draws only jaw material certainly over
the gripped part, plus a pale envelope for possible remaining jaw positions.
Cutter samples inside that envelope stay `?`. `parallels_centres_mm` is
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

### Swivelled vise

`jaws_angle_deg` swivels the vise on its base about setup +Z: the jaw line runs at that
angle from `jaws_along` (counterclockwise positive seen from above). `jaws_along` and
`fixed_jaw` keep naming the jaws before the swivel (`rear` is the +Y jaw of
`jaws_along = "x"`), and `jaw_center_along_mm` is measured along the swivelled jaw line.
`parallels_centres_mm` and `riser_centres_mm` stay setup-frame `[X, Y]` centres; the
parallels and risers run along the swivelled jaws. The plan's setup frame carries the
work's own pose; the kernel closes the jaws on that work across the swivelled line.

Set `hold.align.method` when the setup mounts the vise or changes its swivel:

- `indicate_jaw`: rough the angle in on the base graduations. Touch the
  `indicator` near one end of the fixed jaw and zero the dial and DRO X/Y.
  Raise the quill, then move the printed ΔX = `over_mm`·cos and
  ΔY = `over_mm`·sin of the jaw line. Each move is rounded to the machine's
  measured DRO `resolution`, the step. Lower onto the jaw and tap the vise
  around until the readings agree within `limit_mm`. Setting tolerance is the
  dialled move's angular departure from the jaw line plus
  asin((`limit_mm` + √2·step/2) / L), where L is the dialled move's length and
  each axis is displayed within half a step.
- `graduations`, `protractor` or `sine_bar`: set from that reference against
  the fixed jaw to the stated `tolerance_deg`, which needs a `cite`.

The setup picture labels the stock's size along and across the swivelled jaws,
and labels its setup-frame box as the swivelled footprint.

Any unknown input leaves the tolerance unknown; the HOLD prints a STOP for it. The work
turns with the jaws while the cutter feeds along a table axis, so the
[`swivel`](rules-setup.md#swivel) rule holds each walled cut's angle band against the
tolerance and reports the shift L·sin(tolerance) at the cut's reach L from the DRO zero.
Because the work's edges then stand off the table travel, an X or Y zero is picked up by
indicating a bore's centre (`from = "indicated"`); an edge touch there is `?`
([zero_check](rules-coordinates.md)).

### Jaw bar and buttons

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

### Other fixture poses

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
An authored `angle_deg` with `positions >= 2` declares an open pattern:
every position is checked against `angle_tol_deg`, but closure is not applicable,
even when the authored steps happen to total a whole revolution. Explicit
`"unknown"` is not omission. `positions = 1` is one explicit angular setting
with no closure. The traveler prints plate, circle, turns and hole spaces,
with angles at the drawing's declared angular precision.

### Continuous rotation

For rotary milling, use
`hold.index = { fixture = "<head>", rotation = "continuous" }` instead of a
landing pattern. A verified `dividing_head` passes indexing with no landings;
another fixture kind or simultaneous `positions`/`angle_deg` is an error,
and an unverified head remains unknown. This declares how the head is used,
not proof that its rotation is collision-free or its torque/locking adequate.

## Reference

A `Reference` is a structured entry in `hold.supports`. It can select a fixture,
scope it to operations and declare a follow- or steady-rest position.
The tagged posed branch below is distinct from this legacy reference form.

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
[`turning_deflection`](rules-physics.md#turning_deflection) uses the rest span
instead of `stickout_mm`. The kernel also draws and
collision-checks the rest from that fixture's measured solid fields: a follow
rest's `jaw_width`, `jaw_height`, `jaw_depth` and `jaw_angles_deg`, a steady
rest's `body_dia` and `body_length` ([inventory](inventory.md),
[rules-geometry](rules-geometry.md#follow-and-steady-rests)). Example:
`supports = ["dead_centre_tailstock_mt3", { ref = "follow-rest", ops = [10, 30], jaw_lead_mm = 8.0, jaw_side = "turned" }]`.
The traveler's HOLD prints a follow rest's lead as a distance along the work,
never beside a Ø sign: `jaws 8.00 mm behind the tool, on the diameter just turned;
set on and backed off every pass as printed under each op` (trailing jaws ride
each pass's new diameter), or `jaws … mm ahead of the tool, on the uncut stock`.

### Posed and borrowed supports

A `hold.supports` entry with `placement = "posed"` has `id`, exactly one of
`ref` or `stock_ref`, required `pose`, and required known nonblank `note`. `id` identifies that placed
support in the setup. `ref` selects inventory fixture solids; `stock_ref`
borrows already-produced stock. The existing `Pose` is
`{ origin_mm = [x, y, z], x = [...], z = [...] }` in setup millimetres with
orthonormal axes. It is not a manifest-unit `PlanFrame`.

Borrowed stock must already exist, remain available and be disjoint from the
cutting stock. It is copied/posed once as support, without consumption,
joining or insertion into cutting stock. This does not authorize reuse of a
consumed ancestor or a sibling as an extra cutting blank.

Posed supports enter the ordinary native fixture scene alongside the primary
hold and capture. Their actual solids supply contact, collision and render
geometry, including on vise setups. Missing source geometry or pose stays a
scene gap. Tags cannot be mixed with legacy reference/rest fields.


### Follow-rest pass sequence

Each served op prints its pass sequence once as a full-width line below its
row. The coordinate cell keeps only `follow rest on: Z …` when the start would
foul the rest, using `engage_at_z_mm` on the DRO grid.

1. Start with the jaws backed off.
2. At the engagement Z, or after turning the jaw lead when no engagement Z is
   declared, stop the feed and then the spindle.
3. Set and lock the jaws. Restart the spindle, then resume the feed.
4. For trailing (`turned`) jaws, stop the feed and spindle at the pass end.
   Back the jaws off, withdraw along X and return the carriage to the pass start.
   The return carries the jaws behind that start by their lead onto stock the
   pass never cut.

Leading (`uncut`) jaws return over the smaller cut diameter and need no release.
Hands must never set a rest on a turning spindle, and cutting must never resume
with the spindle stopped. An unknown `jaw_side` or unknown/nonpositive
`jaw_lead_mm` prints a STOP box instead of a pass sequence.

## Zero

`[setups.zero]` groups axis pickups, datum-transfer instructions and tool-change
touches. The [zero rules](rules-coordinates.md#zero_check) check the complete
schedule against the setup and its operations.

| Field | Type (also accepts `"unknown"`) |
|---|---|
| `x` | `AxisZero` |
| `y` | `AxisZero` |
| `z` | `AxisZero` |
| `transfer` | `Transfer` |
| `procedure` | `str`: source-authored physical zero/pickup instructions |
| `tool_touches` | `list[ToolTouch]` |

`zero.transfer` describes a pickup from another setup. `tool_touches` records
tool changes explicitly. Neither declaration invents a measured trial-cut
diameter.

For mechanical dials, this procedure and each axis's `procedure` describe the
physical touch and backlash/take-up sequence. They do not convert nominal CAD
coordinates into measured dial settings or enable the digital-zero recipes
below. See [readout kinds](#dro).

When every spindle op in a setup is a `guided_sweep`, pivot and rail sweeps may
omit X/Y edge pickups: touching the cutter to the master sets those axes before
the table is locked. Even without pickups, X/Y DRO directions are checked
because the touch feed and rough back-off move those axes. A reversed direction
is an error; an undeclared or unrecognized direction remains unknown.

A trammel instead cuts at the rails' crossing under the spindle with X and Y
locked. An X/Y pickup would move it away from that crossing and is an error.
It needs no X/Y DRO direction for those locked axes.
See [zero_check](rules-coordinates.md#zero_check).

## AxisZero

Each `zero.x`, `zero.y` or `zero.z` uses an `AxisZero` recipe. Its declared
coordinate and method describe what is touched and what the operator sets.

| Field | Type (also accepts `"unknown"`) |
|---|---|
| `edge` | `str` |
| `feature` | `str` |
| `face` | `str` |
| `method` | `str` |
| `procedure` | `str`: source-authored touch and dial-setting instructions |
| `dial_setting` | `Number`: physical mechanical-dial setting in `dro.units`; not inferred from `edge_mm` |
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
| `at_mm` | `[Number, Number]`: X pickup `[Y, Ztip]`, Y pickup `[X, Ztip]`, opting into the transverse path proof below. For Z, `[X, Y]` retains its separate touch-location meaning |
| `approach_mm` | Positive transverse pickup approach distance |
| `retract_clearance_mm` | Positive clearance above actual arriving-stock top |

### Transverse pickup path

Presence of X/Y `at_mm` requests `transverse_finder_v1` native proof;
explicit `"unknown"` requests proof with debt. Despite their `_mm` names,
authored `at_mm`, `edge_mm`, `approach_mm`, `retract_clearance_mm` and
`check_jog_mm` follow manifest units and convert once to native mm.
This differs from posed supports and saw trajectories, which use literal mm.
`after_op` pickup is not yet modeled; this proof uses arriving stock before cuts.
Declare matching `from = "+x" | "-x" | "+y" | "-y"`, a selected `edge_finder`
`tool` and `holder`, numeric edge, positive approach/retract clearance and
signed check jog. Finder geometry needs fact-local measured/verified tip
diameter, `finder_tip_length_mm` / `_in`, shank diameter, pair projection,
selected holder diameter and gauge length. The body/holder cannot be replaced
by a tip-only collision test.

The target is an exact current face of the uniquely selected carried member,
an explicit raw-stock side (`stock:-x`, `stock:+x`, `stock:-y`, `stock:+y`), or
a named posed fixture face such as
`fixture:<support-id>/<component-id>:+x` (or the matching signed axis).
An inventory-reference selector is also accepted only when its actual
placement is unique. Canonical target pickup requires a unique arriving
member; there is no authored explicit member selector on `AxisZero`.
Numeric edge is checked against actual contact; it cannot supply a missing
face. Ambiguous planes remain unknown.

The native job starts outside the contact axis by the authored approach
distance, with the lowest tip at actual arriving-stock top plus retract
clearance. It descends to `Ztip`, approaches the face, retracts vertically,
then performs the signed check jog. Exact sweeps check tip, shank and holder
against actual stock and the full fixture/support/capture scene on every leg.
Known collisions error even alongside missing scene facts; full pass requires
complete geometry, actual tip-span contact and a clear complete path.

Rules and sheet displays accept only proof matching the current setup, axis,
full request and recipe/scene identity. Missing or stale proof stays unknown.
The printed physical transverse contact window is not an unestablished DRO
zero. Ordinary Axis Set arithmetic remains separate. Omit X/Y `at_mm` to
retain ordinary arithmetic without claiming a proved path; mounted-saw body
zero and Z area-hold behavior remain separate.

### Pickup coordinates and retouch schedule

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
([coordinates and DRO zero](rules-coordinates.md#zero_check)).

### Measured Z setting

Z `method = "measure_then_set"` (with `gauge`, `measure`, `offset_mm`; on a tool
touch `z_gauge`, `z_measure`, `z_offset_mm`) sets a measured edge, M + offset +
paper. On a mill setup's `top` the raw top then reads Z = M + offset while the ops'
levels start from `stock_state.top_z`; the DRO ZERO prints that correction: face a
higher top down to `top_z` first, no deeper per pass than the setup's least op
`doc_mm`, in plan units rounded down onto the DRO grid (unknown plan units print
no cap).

Only `measure_before_hold = true` with an authored `measure` puts acquisition of
M in the first HOLD step (`Before clamping, measure Z M = …`). That step keeps
35 × 10 mm of clear pen room, and the DRO row refers to
`M measured before clamping (HOLD)`. There is no separate MEASURED ZERO INPUTS
section. An absent or false flag keeps acquisition at the machine. Datum
transfer prints before the DRO ZERO table and tool settings.

## Transfer

`zero.transfer` declares how an existing datum is recovered from an earlier
setup, including the indicated feature, limit and any keep-clamped recovery.

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

The setup sheet interprets `indicate` by machine and reference:

- On a lathe, tap the work true to the limit.
- On a mill, centre a single hole, bore, boss or nonfeature item such as a pin
  head by moving the table.
- For surfaces or several features, sweep each surface with table travel and
  tap the work, not the table, until the reading is within the limit.

With `keep_clamped = true`, never loosen or tap the work. The sheet prints the
sweep as a check, `do not loosen`, and the authored `recovery` for an excessive
reading. Centring can still move the table. Missing `recovery` prints a STOP
and leaves [zero_check](rules-coordinates.md#zero_check) `unknown`.

## ToolTouch

Entries in `zero.tool_touches` declare the surfaces and offsets used to set
tools before their listed operations. They do not supply a measured diameter
unless the procedure explicitly obtains one.

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

Each `[[setups.ops]]` record declares one action and its tool, geometry,
cutting settings or inspection procedure. Its position in the array determines
execution order; `op` is its within-setup identity.

| Field | Type (also accepts `"unknown"`) |
|---|---|
| `op` | `int` |
| `do` | `str` |
| `feature` | `str`; an `inspect` op may name a list of two or more distinct features |
| `faces` | `list[str]` |
| `workpiece_faces` | `dict[str, list[str]]`: nonempty per-live-member canonical face claims, exclusive with explicit `faces`; see [qualified claims](#member-qualified-cutting-claims) |
| `tool` | `str` |
| `holder` | `str` (the tool's `shank` must fit it; a single nominal collet capacity accepts the ISO 286 h6 band below it, [`tool_resolves`](rules-tools.md#tool_resolves)) |
| `direction` | `str` |
| `note` | `str` |
| `layout` | `str` (`scribe` only: `dividers`, `trammel` or `template`; or `ends`, a guided sweep's two arc-end marks measured from the bar's own faces) |
| `guide` | `Guide` (`scribe` with a template, `file_to_line`) |
| `inspection_note` | `str \| list[str]` (numbered steps; see [Checks and written methods](#checks-and-written-methods)) |
| `process` | `str \| list[str]` (`coating` only: a `services` or `consumables` id) |
| `process_holds` | `list[ProcessHold]` |
| `to_z` | `float` |
| `depth_mm` | `float` |
| `exit_mm` | `float` |
| `rough_allowance_mm` | `float` |
| `stock_to_leave_mm` | `float` |
| `z_from` | `float` |
| `z_to` | `float` |
| `to_dia` | `float`: this operation's target diameter in manifest units; an explicit `"unknown"` does not inherit the finished feature's nominal diameter |
| `rpm` | `float`: optional authored spindle-speed request in rev/min; see [authored spindle speed](#authored-spindle-speed) |
| `feed_mm_min` | `float` |
| `doc_mm` | `float` |
| `ae_mm` | `float` (radial width of cut, 0 < ae ≤ D; omitted, the [force bound](rules-physics.md#cutting-force) takes a full slot. `contour.step_mm` is never read as it) |
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
| `saw_trajectory` | `SawTrajectory`: setup-mm start and cut/clear moves for a mounted saw; see [mounted path](#mounted-slitting-saw-path-and-capture) |
| `saw_capture` | `SawCapture`: independently posed fixture and moving clamp, with explicit clamped state; see [mounted path](#mounted-slitting-saw-path-and-capture) |
| `follows` | `str`: `"<setup>:<op>"` of an earlier `scribe` op (a saw that follows its line only; an `ends` layout scribes no line, an error) |
| `allowance_mm` | `Number` > 0: stock a saw that `follows` a line leaves outside it for the file |
| `keep` | `str` (a finished feature: after a held split, the piece that carries it stays and every other piece is discarded; see [keep piece](rules-geometry.md#keep-piece)) |
| `outputs` | `dict[str, RetainedOutput]`: exactly two named pieces on terminal `part_off` or registered mounted `cut_off`; see [retained outputs](#retained-part-off-outputs) |
| `prerequisites` | `{ spot = "<setup>:<op>" }`: typed prior preparation witness, or `spot = "unknown"` |

### Authored spindle speed

Omit `rpm` to use the sourced starting-speed path. An authored `rpm` takes
precedence exactly as requested, without nearest-50 rounding or clamping.
Explicit `"unknown"` requests no known speed; it does not fall back to a
computed recommendation. A known nonpositive request or a speed outside the
machine's known spindle limits or available bands is an error.

A positive request is not safety evidence. Missing or unverified machine,
tool, material, cutting-data or applicable depth facts still leave
`speeds_feeds` unresolved. The report preserves the requested speed separately
from the computed starting value and its verdict. The sheet prints a known
request even when unresolved, with the STOP/debt rather than presenting it as a
verified recommendation. Manual actions, including spindle-stopped
`die_thread` and `hand_tap`, and nonspindle saws have no RPM recommendation.
For either manual threading action, `tool_resolves` separately rejects any
known numeric `rpm` other than zero: a stopped-spindle declaration is not a
cutting-speed request. A mill-mounted `slitting_saw` uses the spindle-speed
path.

See [authored RPM](cutting-data.md#authored-rpm) for precedence, reported
evidence and feed arithmetic.

### Prior preparation references

`prerequisites.spot` optionally names one real earlier operation as
`"<setup>:<op>"`. The referenced operation must be a `spot` on a process
`centre_hole` or `tooling_hole`, or a centre-specific `center_drill`.
The [causal operation rule](rules-operations.md#op_chain) checks entry location,
directed axis, earlier route position and survival on the material that the
consumer receives. The reference offers evidence; it creates no second cut and
grants no credit merely because the producer is in the child's history.
`spot = "unknown"` or an unproved preparation/registration remains debt. A
known wrong action, geometry, order or material is an error.

### Manual threading

`die_thread` and `hand_tap` are spindle-stopped hand cuts, not powered spindle
operations or noncutting fitting instructions. They require actual selected
thread tools and manual holders, but no spindle RPM/feed, spindle/shank
mounting, axial tool setting or toolpost-retouch instructions. Omit `rpm` when
no speed applies; a known nonzero numeric value is an error.

`die_thread` works an exported `external_thread` and needs prior male
blank/shoulder preparation. Select the actual die or declared set member and a
`die_stock` holder. See [manual die threading](rules-tools.md#manual-die-threading)
for supported identities and fit facts, and
[external-thread preparation](rules-operations.md#external-thread-preparation)
for the causal preparation checks.

`hand_tap` works an exported `thread` or `threaded_hole`, using an actual tap
or declared tap-set member with a `tap_wrench` or `tap_follower` holder.
The selected tap must match the exported nominal thread, hand and class;
known mismatches are errors and missing facts remain debt. Holder fit needs
an exact tap identity or its supported nominal tap-size range/capacity, not a
spindle-collet shank fit. See [manual tapping](rules-tools.md#manual-tapping).

An internal thread still needs the real causal spot-and-drill preparation on
the material received by the tapping operation. An earlier drill on another
retained child cannot supply that preparation. A manual tap uses `depth_mm`
when authored, otherwise the feature's `thread_depth` or `depth` upper value
converted from manifest units; its selected tap's flutes must cover that
depth. This is a relative manual depth, not a DRO/absolute Z endpoint or a
powered-feed instruction. See [`op_chain`](rules-operations.md#op_chain) and
[tip endpoints](rules-operations.md#blind_depth-tip-endpoints).

Both actions are cuts for the terminal-holding rule: they cannot follow a
`part_off` or `release` in the same holding. Native stock after manual
threading remains unresolved because helical removal is unmodelled; no
nominal cylinder is subtracted in its place. See the
[manual-threading geometry boundary](rules-geometry.md#manual-threading).

### Endpoints and inspection procedures

`to_z` is an authored endpoint. `to_z_band` is a range, not a substitute for
measured setup binding. Arc contours need the nominal geometry and a supported
[manual-arc method](#manual-arcs); their finite bounds come from that geometry,
not an invented full circle.

#### Checks and written methods

For a single-feature op, `checks` maps requirement names to inventory gauge
references. Every key must belong to that resolved feature's `requirements`
list, exported or plan-owned. Otherwise loading raises `BadInput`, even if
another feature owns the name. A wholly unknown requirements list cannot
authorize arbitrary checks. A missing check is distinct from
`checks.dia = "unknown"`. Multi-feature inspection uses the scoping rules below.

`inspection_methods` supplies the authored procedure for datum/geometric
checks and missing requirements. Each `inspection_methods.<requirement>` or
operation `inspection_note` is either one string or a nonempty list of strings.
A string uses its blank-line paragraphs as numbered paragraphs
(`(1)…(2)…`). A list prints numbered steps in INSPECTION NOTES for the
machinist to follow and record:

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

#### Inspection views

An `inspect` op can illustrate its procedure with `inspection_views.<requirement>`,
a nonempty list containing one view per surface-plate arrangement.
Each needs a `title`, known three-component unit vectors `up` and `toward`,
and at least one mark. `up` points away from the plate in the part-model
frame, in the direction a height reading rises. `toward` points from the part
to the viewer and must be square to `up`. Neither vector accepts `"unknown"`.
`aids` is optional. Positions and sizes use part-model millimetres; unit
direction vectors are dimensionless:

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

The setup sheet retains every authored view in order with its own title.
Each attaches once as a whole figure to the requirement's worksheet or note.
A continuation can move the figure and repeat its context without duplicating
reading or calculation fields. Views change neither the schema nor the
authored procedure.

#### Missing requirements and paper records

When an inspection requirement has no exported owner/band, an explicit operation
may declare `missing_requirements = { length = "calipers" }` and
`inspection_methods.length`. This uses the same gauge-reference mapping type as
`checks`, but produces a named unknown inspection row with
`missing_requirement = true`, not an acceptance band or a dimensional pass.
The sheet prints `?`, the exact missing requirement identity and the authored
procedure; reference-only dimensions such as `length_ref` are not substitutes.
A name already in that feature's exported requirements is `BadInput` in
`missing_requirements`; use `checks` so actual requirements cannot be bypassed.

Paper records use the existing requirement-keyed `checks` and methods.
Below each real requirement, one full-width area accepts freeform readings
and observations beside its known owners, limits, gauge, method and authored
context. It infers no reading positions or counts. Authored `{name}` fields
remain separate named blanks, never invented samples or statistical summaries.
Missing identities or bands stay visible as `?` instructions, without
fabricated automatic measurement fields.

#### Multi-feature inspection

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

A feature uses its scoped entry when present, otherwise the flat entry.
Flat and scoped entries can share a table, but one requirement cannot be both
flat and scoped in that table. A flat entry already applies to every listed
feature that exports it. Different tables can mix scopes; for example,
flat `go_no_go.dia` can pair with scoped `checks`.

Loading raises `BadInput` for any of these conditions:

- A scope key is not one of the op's listed features.
- A scoped requirement is not exported by its feature. Use
  `missing_requirements` for absent requirements.
- A key is both a listed feature and an exported requirement.
- A requirement has both flat and scoped entries within one table.
- A `go_no_go` pair or scoped method has no corresponding `checks` gauge.
  A flat pair needs a gauge on every listed feature exporting its requirement.

A single-feature op always keys these tables by requirement; a scope key is
bad input. `missing_requirements` and `inspection_views` remain flat, and a
view illustrates only a flat `inspection_methods` entry. Feature lists on
actions other than `inspect` are bad input.

The inspection rule credits each feature with its own gauge, pair and method.
The sheet groups the op as one station card. A requirement row names all
features sharing a gauge, pair and method; features read differently get
separate rows. A scoped method prints once as a feature-headed note, while a
flat method prints once for each feature.

### Finishing route

`deburr` and `coating` are manual bench actions. A
`coating` op (black oxide, paint, oil) names its `process`: an outside
`[services.<id>]` item or in-house `[consumables.<id>]`. An absent process is
unknown in `tool_resolves`, and an unlisted one is an error. A drawing
`material.finish` with omitted `finish_kind` or explicit `"coating"` and no
`coating` op in the route is a job caution. Explicit `"surface"` declares a
surface condition instead, leaving its inspection to the existing inspection
rules; unknown kind or finish remains unresolved
(`finish_route`, [inspection rules](rules-inspection.md)).

### Process holds

A `ProcessHold` is `{ feature, requirement, band = [lo, hi], gauge, reason }`, all
required, plus an optional `go_no_go`: a shop limit tighter than the drawing, held for a stated process reason
(a downstream fit, a pin that clocks a later setup). `requirement` must be one the
feature exports (else `BadInput`), and `band` is in the drawing's units. The
inspection rule errors when the band reaches outside the drawing band (limits
included, a scalar zone `v` read as [0, v]). The sheet prints it in the op's
inspection cell as `PROCESS HOLD — not a drawing limit (why: see job page): …`,
never as a drawing limit, and the job page gathers every hold, with its reason, in
a `PROCESS HOLDS — in-process limits, not drawing limits` table, apart from
DRAWING REQUIREMENTS; the reason prints nowhere else.

A hold may instead name a feature's reference-only dimension (`<name>_ref`, a
number the drawing gives as REF or CUT TO FIT, such as an assembly fit-up span).
The drawing sets no limit there, so the hold must also say what the gauge reads
(`measure`, e.g. `"scribe to faced end"`) and where the band comes from (`cite`);
missing either is `BadInput`. A `measure` on a hold of an exported requirement is
`BadInput` too: that hold reads the requirement itself.

### GO / NO-GO declarations

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

### Cutting face claims

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

#### Member-qualified cutting claims

For registered workpieces, `workpiece_faces` maps each selected live member id
to a nonempty list of exact canonical STEP face references. It is mutually
exclusive with explicit `faces`; source references are validated against the
bound STEP. Select members explicitly rather than constructing display labels
or copying a sibling's face evidence.

An unqualified `faces` or feature-default claim is usable only for a unique
arriving member. A multi-member setup must qualify claims; a sibling's native
face, earlier operation, stock contact or inspection cannot supply credit.
Complete explicit ownership applies per member with the same ordinary
action/finishing filters. Display labels such as `nut1:<face>` are not new
canonical face references.


#### Complete explicit-face ownership

An op owns a feature it does not name when its
explicit `faces` list is known and nonempty and contains every face of that
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

### Stock removal bounds

`stock_removal_bounds` declares the setup-frame box
`{ x = [lo, hi], y = [lo, hi], z = [lo, hi] }`. All intervals must be numeric
and strictly increasing. The operation clears material outside the finished
part inside this volume and leaves everything outside it unchanged.
Its finished faces still need valid cutting claims from this setup.

The box can represent several roughing passes or the author's certification
of a chain-drilled-and-chiselled break-out footprint. It is not capped to the
claimed faces' X/Y box dilated by cutter radius. A known cutter radius is
still required: an unknown radius leaves the bounds `?` with that reason,
and later stock unresolved.

This material mask does not bound cutter travel through air. The
[`travel` rule](rules-setup.md#travel-required-table-and-spindle-stroke)
distinguishes an omitted field from an explicit `"unknown"` or known mask.

#### Removal and stock propagation

Removal is the box intersected with setup-entry stock, never finished
material or a protected rough leave. Every claim must touch the box, and
every removed piece must border a claim on that entering stock. An earlier
op clearing a bridge between claim and box therefore does not strand it.
The resulting pieces are cut from current stock in operation order, so
material is never restored.

Known future planned-hole columns, including finite caps, stay stock.
Removal must not split an original input solid. A violation creates named
stock debt, not an error; dependent later stock remains unresolved. In the
same setup, later ops retain only certain finished-material flute hits while
tool hits are unknown. Independent genuine collisions with finished material
remain errors.

This stock shapes later flute obstacles in the current and descendant
setups, excluding the operation's own derivable allowance. Accessibility
holder obstacles and holding facts still use setup-entry stock; reach,
holder-wall and shank screens see the removed stock.
See [reach](rules-geometry.md#reach).

#### Cutter access inside the box

Accessibility judges a claimed face only where the cutter can stand without
meeting stock outside the box. Air and finished part beyond it do not stop
the cutter. Unreachable samples can pass to a later operation that cuts or
files the same face, including another rough or file-to-line, never a saw.
Without such an operation, the finding is an
[accessibility error](rules-geometry.md#accessibility).

The box is an authored process/fixture volume, not a measured toolpath or
proof of safe continuous motion. Without it, a claimed wall still touching
overstock above `to_z`, including a drafted wall, needs named stock-out debt.
A contour-checkpoint bounding box is not a clearing volume. An unbounded
chain-drill op removes discrete holes and retains its webs until a later
known removal. See [Manual arcs](#manual-arcs).

### Rotary approach and claim windows

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

### Depth of cut and approach distance

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

### Kept pieces

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
piece that carries every face of the feature and discards the rest (an error if
a discarded piece holds finished material). Later
setups' entry stock and their `stock_state` checks then see the kept piece only,
as do later ops' flutes in the same setup; their holders still see the
setup-entry stock, as for any cut ([keep piece](rules-geometry.md#keep-piece)).
The op's traveler row tells the operator which piece to keep and to discard the
rest. Without `keep`, a held split retains every piece.

### Retained part-off outputs

Use `outputs` when both real pieces of a terminal `part_off` continue through
the route, rather than treating one as scrap or authoring a second stock
component. The schema requires this `part_off` to be the setup's final
material-changing operation. Only `inspect`, `deburr`, `coating`, `release`
or `scribe` may follow it. Later `fit`, `file_to_line`, `die_thread`,
`hand_tap`, powered cuts or unknown actions are bad input, not merely an
[`order` finding](rules-operations.md#order). Permitted deburring or coating
does not claim new native stock geometry or remeasurement of the retained
pieces; later inspection cannot authorize another cut in the released
holding.

`outputs` must contain exactly two globally unique, known, nonempty names with
no leading or trailing whitespace. Only one named split is allowed in a setup.
`keep` and `outputs` are mutually exclusive on the split op, and a later
`keep` in that same setup is bad input. A later setup machining one named
output may still use `keep` to discard genuine scrap.

Each `[setups.ops.outputs.<name>]` is a required-field `RetainedOutput`:

| Field | Type and meaning |
|---|---|
| `carries` | Legacy terminal `part_off` selector: one known exported finished feature id; exclusive with `carries_workpieces` |
| `carries_workpieces` | Registered finite-saw branch: nonempty list of carried member ids; exclusive with `carries` |
| `side` | Registered finite-saw branch: `"below"` or `"above"` |
| `pose` | Required inline `PlanFrame` or `"unknown"` |
| `cite` | Required nonempty citations for selection and authored registration |

For the legacy `carries` branch, the manifest must declare
[named finished solids](features.md#named-finished-solids).
The carried feature's bound source faces must resolve to one named finished
solid. That whole solid selects the piece: containing only a feature point,
face or local patch is insufficient. A known mixed-solid selector or two
selectors owning the same finished solid is bad input. Unknown face
identities withhold proof; they are not an empty protected shape.

The inline `pose` maps a point `p` in the incoming material's model coordinates
to registered model coordinates:

```text
p' = origin + x*p.x + y*p.y + z*p.z
```

`origin` uses manifest/plan units and the basis vectors are dimensionless.
The host converts the translation to mm once. The basis must be orthonormal
and right-handed, and the record must state `binding` and a nonempty `cite`,
as under [frames](#frames). `binding = "unknown"`, unknown units or unknown
numeric components leaves native registration unresolved. Describe a known
author-selected pose in `note` and `cite` as `AUTHOR'S CHOICE`, not as a
physical measurement.

Reference the outputs as `"stock_out.<name>"`. For example, after setup P3
names `tube_blank` and `bar_remnant`, T2 may consume
`stock_out.tube_blank` and C1 may consume `stock_out.bar_remnant`; an assembly
can then name `stock_in = ["C1", "T2"]`. P3 itself is not a selectable combined
output. These names retain the original supply root and distinct partition
identities; they do not create independent stock purchases.

The named split uses the selected parting blade's accepted width as a finite
kerf at `to_z`, on the claimed face's axial side. It must cut to the spindle
axis, not leave a connected core; any authored `z_from`/`z_to` span must cover
the full kerf. These are the [native cut requirements](rules-geometry.md#retained-part-off-outputs),
not additional output fields. The ordinary part-off-and-`keep` route is
unchanged.

Naming both outputs does not waive the existing
[held-split proof](rules-geometry.md#held-splits). Each retained piece still
needs modelled press-clamp contact and a load path to an anchored support.
Unknown catch/support geometry does not become permission to release or route
a loose piece.

The kernel must prove a real cut, two distinct pieces, unique whole-solid
containment after each pose, complete finished-solid accounting and no material
overlap before it exposes either output. Missing geometry or a failed proof
leaves the named outputs and downstream stock unresolved. See the
[native partition contract](rules-geometry.md#retained-part-off-outputs).

#### Registered finite-saw outputs

A terminal mounted `cut_off` may name exactly two retained outputs
using `carries_workpieces`, one `side = "below"` and one `side = "above"`.
Together the lists must account for the incoming members exactly once,
without duplicates or omissions. Each output has its own cited registration.
This branch uses the [mounted path/capture proof](#mounted-slitting-saw-path-and-capture),
not the legacy lathe feature selector or parting-blade model.
Nested retention uses a later setup with `stock_in = "stock_out.<name>"`,
not recursive output tables. Only `cut_off`, not the `saw_cut` alias, accepts
named finite-saw outputs. A registered plan cannot use legacy `carries`
selectors. Unknown output poses parse but cannot publish proved geometry.

The native job must prove exactly two real children, unique whole-target
containment on the declared sides, no protected kerf loss, conservation of
stock volume, and non-overlap after registration before publishing either
output. A descendant can split a retained child again; its ordered material
path preserves all prior edges. Route membership and canonical face lookup
alone do not establish any of these physical proofs.

The existing `part_off`/`carries` branch above remains unchanged. Its named
finished-solid and held-split requirements do not substitute for finite-saw
capture, and registered membership does not waive either branch's holding
requirements.


## Contour

`contour` declares a linear raster or one supported manual-arc method.
Linear pockets and faces may use `sweep_bounds`, `sweep_frame`, `open_side`
and circular `keep_out` islands; a raster also needs `step_mm`.
See [coordinates](rules-coordinates.md).

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

### Chain-drilling cutting data

A `rough_profile` with `method = "chain_drill"` and a resolved drill-kind
tool performs drilling, so its speed/feed lookup selects `operation = "drill"`.
Other contour methods and end-mill chain contours retain profile data.
The axial feed, tool-chart precedence and before-stock penetration used for
deep-hole derating are defined in [cutting data](cutting-data.md).

### Keep-out islands

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

`GuidedSweep` is the `sweep` record inside a `guided_sweep` contour. See
[pivot and rail sweeps](#pivot-and-rail-guided-sweeps) and
[oblique trammels](#oblique-trammel) for process requirements.

| Field | Type (also accepts `"unknown"`) |
|---|---|
| `guide` | `"pivot"` (a swing arm on a pin at the arc centre), `"rail"` (a sled's arc rail on two rollers) or `"trammel"` (a carrier's pin pair in two straight rails crossing at the spindle axis) |
| `fixture` | `str`: the inventory `fixtures` item that carries the work and rides the guide (`kind = "swing_arm"` for a pivot, `"arc_sled"` for a rail, `"trammel"` for a trammel); it must be the setup's `hold.fixture` |
| `master` | `str`: the inventory `gauges` item touched by the stationary cutter. A pivot uses `kind = "setting_bar"`; a rail uses `"master_arc"`. A master arc on a swing arm provides no radial centring line, so the sheet prints only a STOP. A trammel has no master, and naming one is an error |
| `touch_axis` | `"+X"`, `"-X"`, `"+Y"` or `"-Y"`: the setup axis on the cutter's radial line, and the side of the arc centre the cutter stands on; the setup frame is the work at the sweep's middle pose, so it must point from the arc centre to the arc's middle |
| `sweep_deg` | `float`: the fixture's whole sweep, centred on the arc; at least the arc's span and under 360 (a full circle cannot be swept: use a rotary table) |
| `rollers_deg` | `Vector` (rail: the two rollers' angles about the arc centre from the cutter's radial line, counterclockwise from above, with the cutter at the arc's middle) |
| `rail_deg` | `Vector` (rail: the rail's two ends, the same way) |
| `pin_pair` | `str` (trammel: the key of the carrier's pin pair this pass rides, in the fixture's `pin_spacing` map) |
| `pins_deg` | `Vector` (trammel: that pair's two pins' angles about the arc centre from the cutter's radial line, the same way; their central angle must be within 0.5° of `2α` or `360° − 2α`, and the measured `α` then places them exactly about the pair's bisector) |

## Guide

`guide` selects filing buttons, a template and the gauge used to check a
manual arc. A template also supplies a `scribe` op's `layout = "template"`.

| Field | Type (also accepts `"unknown"`) |
|---|---|
| `buttons` | `str`: an inventory `fixtures` kit of `kind = "filing_buttons"` |
| `bore` | `str`: the plan feature the buttons' pin goes through |
| `template` | `str`: an inventory `gauges` radius or profile template |
| `gauge` | `str`: the inventory radius or profile gauge that checks the filed arc |

## Manual arcs

The PM-30MV is a manual mill with a DRO. One handwheel moves at a time, so the
plan never calls for an arc as one simultaneous X/Y move: no MDI, G-code or
continuous two-axis circle. The supported 1898-style process is to lay out the
arc, rough outside the line and file to it, or use one of the milling and
guided-fixture alternatives below.

Manual-arc features use `mm` or `in`; other units remain unknown.
`method = "arc_table"` is an error.

### Layout

A `do = "scribe"` op names the arc feature and declares
`layout = "dividers" | "trammel" | "template"`. `guide.template` names the
template. Layout is optional with filing buttons. The `manual_arc` rule prints
the centre in setup X/Y, any hole on its axis, nominal radius and arc ends.
An unknown layout stays unknown.

### Roughing with stairs or chain drilling

Use a `rough_*` op with one of these contours:

- `contour = { method = "stairs", cusp_mm = … }`: single-axis stair corners
  on the DRO grid.
- `{ method = "chain_drill", pitch_mm = … }`: drilled holes, with webs
  chiselled out along the hole centres. The kernel credits the holes, not the
  chiselling, unless the authored clearing-box contract below supplies it.

Declare a nonnegative `rough_allowance_mm`. A negative leave on any op is an
error because it would cut into the finished part. Every stair corner, full
hole and break-out between neighbouring holes must stay outside the finished
line. Unless a later rough cuts the same faces again, the stock left for the
file must not exceed `numbers.max_filing_stock_mm`:

- For stairs, allowance plus stair cusp measured along the wall normal.
- For chain drilling, the maximum of allowance plus drill radius, printed
  arc break-out radial depth, and the greatest nearest-finished-wall distance
  of the retained printed straight-join break-out polyline.

A missing or unestablished filing-stock cap stays unknown. Both rough methods
support straight joins. Each finite chain-drilled join leg uses the same
drill-radius-plus-allowance offset, exact endpoints and miter, and nominal equal
spacing no greater than `pitch_mm`. Snapping to the DRO grid can change the
printed spacing.

A gentle arc can instead be hand-sawn outside its scribed line on the bench.
A saw op with `follows`, `allowance_mm` and `stock_removal_bounds` counts as
the rough that filing finishes. See
[hand saws](#hand-saw-on-the-bench-straight-or-to-a-scribed-line).

#### Finite-boundary acceptance

Host DRO selection and kernel regeneration use the same finite-boundary
predicate for bounded and unbounded chains. Closed finished loops, including
joined bottom outlines and full circles, use point-in-region and nearest
finite-boundary distance, negative in kept material. Exact arcs and lines can
arrive unordered; their real endpoints connect them, and authored scrap normals
identify the kept side.

True open arcs and partial top-plus-land wall packets do not contain a complete
finished loop. The top packet omits tapers and the bottom arc even when the
host model has those linked facts. The open fallback uses oriented finite
projections, real free-end caps and shared-concave-vertex sector classification.
It invents no closure. Distance ties are conservative; the predicate does not
combine distant supporting half-planes with a global AND. Missing or ambiguous
region geometry, inconsistent occupancy and unsupported topology remain
unknown, never an unsigned-distance pass. If no admissible grid point exists,
cut tables are withheld. A closed-loop break-out tests kept-region entry
against the whole finite boundary, not just its own join lines.

Unsigned wall distances still measure filing stock and residual, not
scrap-side acceptance. The cap is applied to the actual regenerated residual.
Every actual cylinder still needs web, bounds and 3D collision/accessibility
checks. The open fallback is not a full-part region proof. Internal wall
normals and outward signs add no plan field, policy knob or tolerance.
For native helper ownership and cache identity, see
[architecture](internals/architecture.md#native-boundary-and-cache).
The missing full-boundary transport is recorded in
[#212](https://github.com/pedropaulovc/prechips/issues/212).

#### Bounded chains and DRO placement

Method, stage, whole-hole outside-the-line and requested no-web errors are
checked before clipping. A requested `pitch_mm` no greater than the drill
diameter is a no-web error; clipping never waives it.

Clipping works at drill granularity:

1. Intersect the drill-centre offset arc and joins with the clearing bounds
   eroded by the full drill radius. Seam fragments of a closed arc form one span.
2. Regenerate each retained arc or leg independently with nominal equal
   intervals within `pitch_mm`. Web acceptance uses the actual snapped DRO
   centres, not nominal span alone.
3. For a span longer than the length tolerance, try the pitch-required count
   at its snapped positions even if it exceeds the nominal-length web bound.
   Try every higher nominally feasible count before shortening.
4. Keep exactly one hole for a span within that tolerance, an isolated point
   or a tiny retained arc or leg between two shared junctions. Never duplicate
   its row. If no tried count leaves positive web, omit the clipped end hole
   as a dropped end instead of fabricating a no-web error.
5. Snap every retained hole inside the bound on the DRO grid. It must pass
   the same finite-boundary predicate with clearance for the whole drill and
   allowance. Bounds waive neither closed-loop region membership nor the
   finite-projection, free-end and shared-concave-vertex checks for open packets.

Nominal-distance and offset guards are additional placement constraints,
not independent unsigned side acceptance. The authored radial whole-hole
check still precedes clipping: a regenerated, physically safe finite-cap hole
beyond the actual sweep can lie inside the authored supporting circle.

Each hole searches a symmetric square of three grid steps per axis and chooses
the nearest safe point by Euclidean distance, with a deterministic coordinate
tie-break. Ends and junctions can back off inward along the true curve. If the
full search and back-off find no candidate, the whole clip stays unknown;
no hole is placed in finished material. Every actual hole cylinder is judged.
A swept-chord intersection never becomes another hole.

Web and break-out validation and the single cap check use the resulting chain.
Tables mark only dropped ends and genuine piece breaks as stops, where stock
beyond is neither cleared nor part of the chiselled chain. An intact arc/join
junction continues into the adjacent table. Omitted joins add no debt while
an arc or other table remains; a wholly excluded or disconnected stage retains
its clip debt. Arc and join tables report the same worst-stage stock.

When residuals were computed, chain errors retain stock and cap profile facts
even if cut tables are withheld. A precondition error can prevent that
calculation. Hole repositioning is not a handwheel cut. See
[coordinates](rules-coordinates.md#coordinates).

#### In-process stock after chain drilling

Without `stock_removal_bounds`, a chain removes only the actual hole
cylinders. Positive webs, stock between the holes and claimed wall, and any
rail or ear beyond them remain until a later known cut removes them.
Unlike a milling profile, the chain receives no cutter corridor, +Z claim
sweep, lineage band or drill-radius sweep between centres.

Those webs remain overstock on the claimed wall. The op receives named stock
debt pointing to `stock_removal_bounds`, and descendant setups remain unknown
through ordinary stock propagation. Declare the bounds on the chain op to
certify the actual drilled-and-chiselled footprint. The same finite-box,
setup-entry-stock and protected-material rules apply as for any bounded op.
This is the author's process declaration, not a demonstrated toolpath.
Ordinary milling and bounded-box behavior is unchanged. There is no separate
break-out/chisel phase or schema; that work is recorded in
[#213](https://github.com/pedropaulovc/prechips/issues/213).

### Filing to the line

`do = "file_to_line"` needs a `guide`:

- Hardened `buttons` from an inventory `fixtures` kit of
  `kind = "filing_buttons"`, with limits for every element between the rims
  and bore axis. The setup holds the kit as `hold.fixture` or a clamp.
  The buttons are pinned through `bore`, a hole on the arc axis already
  drilled, reamed or bored to size.
- A `template` checked against a scribed layout.

A `gauge` of inventory kind `radius_gauge` or `profile_gauge` must have a
`range_mm` that covers R. Filing buttons produce this worst-case radius band:

- Lower limit: `button_min/2 − shift`.
- Upper limit: `button_max/2 + shift`.
- Rim-centre shift from the bore axis:
  `(bore_max − pin_min)/2 + (button_bore_max − pin_min)/2 + runout/2`.

The whole band must fit inside the radial drawing band.

| Condition | Result |
|---|---|
| Missing guide or gauge; buttons not held or flagged to verify; unknown button OD, button bore, pin, runout, bore drawing size or radius band; no earlier rough; or no established filing cap | Unknown |
| Gauge range misses R; buttons on a concave arc; bore off the axis or not yet made; largest pin exceeds the smallest work bore or button bore; or worst-case filed radius outside the band | Error |

`scribe` and `file_to_line` are manual actions with no tool requirement. They
can run on a bench setup (`machines.<id>.kind = "bench"`).
See [manual-arc inventory](inventory.md#manual-arc-kit).

### Chords and rotary-table finishing

`{ method = "chords", count = … }` cuts straight chords whose sagitta
`c²/8R` fits the band. Feed each chord along one axis. A slanted chord must be
indexed square on a rotary table, and a full circle requires at least three chords.

`{ method = "rotary_table", step_deg = …, centre_by = "pin" | "indicate", centre_feature = … }`
turns the work on an inventory `rotary_table` selected as `hold.fixture`.
For pin centring, its `bore_dia_mm` defines the table centre bore. Lock the
cutter at the cutter-centre radius on the DRO grid and turn between dial
readings rounded inward to the table resolution.

These conditions are errors:

- A pin that does not fit the table bore.
- A printed offset whose cut, widened by pin play, leaves the band.
- An arc too short for one dial step.
- Rows half a turn or more apart: `step_deg` of 180° or more on an arc long
  enough to reach that spacing.

### Pivot and rail guided sweeps

When the arc centre is too far off the part for a rotary table, use
`{ method = "guided_sweep", step_deg = …, sweep = { guide, fixture, master, touch_axis, sweep_deg, rollers_deg, rail_deg } }`.
The [GuidedSweep](#guidedsweep) record describes the guide:

- A swing arm (`guide = "pivot"`, inventory `kind = "swing_arm"`) turns on a
  pin at the arc centre.
- A sled (`guide = "rail"`, inventory `kind = "arc_sled"`) rides a concentric
  arc rail against two rollers fixed in the T-slots.

With the spindle stopped, touch the cutter itself to `master` along
`touch_axis`: a `setting_bar` seated on the pivot pin, or a `master_arc`
pinned on the fixture. Lock X and Y. Only the fixture moves during the cut.
The table never makes a simultaneous two-axis move.

#### Radius and error budget

The cut radius starts with the master's measured `radius_limits`. Widen it
for movement of the arc centre between touch-off and cut:

- A swing arm contributes measured `pivot_play`, twice when its master is on
  the arm and moves with the beam at touch-off.
- A rail contributes `2 × g × (rail_form_error + roller_runout / 2)`, with
  `g = (|sin a| + |sin b|) / |sin(a − b)|` for rollers at angles `a` and `b`.

Both cases also need their finite-geometry terms. A linear gain alone is no
bound; failure to converge leaves the cut unknown. A rough moves off the line
by its allowance, backed off along `touch_axis` on the DRO grid. This is the
only handwheel move. Widen its cut for departure of that move from a radial
move when the cutter is beside the radial line:

- A centred setting bar uses one DRO step plus pivot play.
- A rail uses centre sideways shift
  `(|cos a| + |cos b|) / |sin(a − b)|` times the rollers' 0.1 mm print
  rounding, plus form error and half the runout.

Then include one explicit safety margin, the machine's measured DRO resolution
(one display step, `margin_mm`). Start clearance carries the same margin.
Terms proven smaller than it are absorbed, including a setting-bar touch up to
one step beside its line and touch-axis lean within the one-step tolerance.
A resolution not recorded as measured, or cutter-centre reach under two steps,
leaves the margin unproven. The complete widened cut must fit the radial band.
See [guided-sweep limits](rules-coordinates.md) and
[#272](https://github.com/pedropaulovc/prechips/issues/272).

#### Sweep limits and unresolved facts

Rows sample the nominal cutter-centre arc every `step_deg` over the whole
sweep, centred on the arc and retaining its ends. The kernel therefore judges
the cutter at the arc ends and sweep stops.

These conditions are errors:

- A sweep shorter than the arc by more than one DRO step of cutter travel.
- A sweep of a full turn or more, or a full circle. It starts and ends at one
  fixture pose, so a pair of stops cannot bound it.
- `step_deg` of 180° or more. Half-turn rows do not identify which way the
  fixture turns between them.
- The wrong fixture kind, or a guide fixture that does not carry the work.
- A master other than a setting bar or master arc, or a setting bar on a rail.
- Two rollers on one line through the centre, or a roller leaving the rail.
- A worst-case cut outside the band.
- Another spindle op in the same setup. The turning fixture is not held at
  the setup pose before or after the sweep. Manual ops are allowed.

Undeclared, unmeasured or flagged guide/master facts remain unknown, with a
`measure:` instruction for every physical fact. A rail is never assumed
perfect. Unknown guide, axis, sweep, rollers or rail ends also remain
unresolved. The sweep start must be proved clear of arriving stock because
the cutter lowers there at every level, in air only.

#### Printed pivot and rail procedure

The sheet prints a guided-sweep procedure instead of a DRO table. Its contour
heading and operation-row pointer both identify the sweep. The procedure is:

1. Set the guide so the cutter lies on the arc's radial line. For a setting
   bar, seat it on the pivot pin, centre the other axis between its sides and
   lock that axis. For a rail, lock the other axis first and set the rollers
   from the spindle at their printed X/Y offsets. This places the rail centre
   on the spindle's line.
2. With the spindle stopped, touch along `touch_axis` only. Lock it and record
   the DRO reading in the printed blank. Never reset the setup zero. Remove
   the master from the sweep path.
3. At the touch position, before a rough back-off, set a block at each sweep
   end. Keep X/Y locked, the spindle stopped and Z just clear. Move the fixture
   until the extended radial stroke of the earlier `layout = "ends"` mark
   passes through the cutter axis, then continue by the printed overrun along
   the cutter path. The stroke's line matters, not its direction or the
   radius set by the master; 0.1° angle rounding moves the stop by thousandths.
   Overrun is measured on the touch path and printed to 0.1 mm, rounded down.
   Start clearance is proved at that printed stop.
4. For a rough, back off its allowance along the one named axis in the printed
   cutter-movement direction. A later finish raises Z, returns to the touch
   and continues the same numbered procedure. If that rough does not print
   runnable, the dependent finish stops too.
5. Make a dry pass from stop to stop.
6. Start the spindle in the stated direction, viewed from above. Feed the
   fixture through the printed sweep angle and cutter travel, using the time
   given for the op's starting feed.
7. Raise Z clear of the work and fixture after every sweep. For axial levels
   set by `doc_mm`, begin at the heading's top level, raise Z and return to the
   first stop for every further level. Never sweep straight to full depth.
8. After the op's last sweep, stop the spindle before reaching in.

A master arc on a swing arm supplies no radial centring line. It prints only a
STOP for roughs and finishes until a supported feeler touch is available.
See [#288](https://github.com/pedropaulovc/prechips/issues/288).

#### Arc-end marks, pictures and model limits

The earlier same-setup `scribe` op with `layout = "ends"` marks A and B on the
work top. Each point is measured from the nearer end and side faces of the raw
rectangular bar received by that setup, square to its axes. A short stroke
points toward the arc centre at the printed angle to that side face.
Scribe before any op in the setup that can cut those faces.

Missing layout, stock without those faces, layout after a cut, or a cut between
layout and sweep leaves the sweep unknown and prints only a STOP. An earlier
sweep can itself cut the marks away. The stop-setting step prints no setup
X/Y because the work's marks place the stops.

The setup picture draws a rail's rollers at their table positions, for
display only, once `roller_dia`, `roller_height`, `bed_height`, `rail_side`
and the supports under the work are known. It notes a pivot post off-picture
at the arc centre. A missing roller fact produces NOT SHOWN and its
`measure:` instruction, not a picture verdict. The worst-case cut radius
stays in the report. See [manual-arc kit](inventory.md#manual-arc-kit) and
[renders](rules-geometry.md#renders).

`travel` and `headroom` do not model the moving fixture's swept footprint or
stack at every pose. A setup with a guided sweep can never pass either;
each retains a `check:` debt. See [headroom](rules-setup.md#headroom).

Any unproven printed fact suppresses the runnable recipe and prints only a
STOP naming the gaps. This includes the guide, fixture, master, cut radius,
touch axis, rough back-off, sweep/spindle direction, sweep angle, path,
overrun, stop landmarks, cut Z, axial levels, pivot play, and rail rollers,
ends, radius or roller positions. A stage's other errors or debt, even when
not represented by a printed value, also stop the recipe. A machine not
proved to be a mill is one such case.

### Oblique trammel

An oblique trammel (`guide = "trammel"`, inventory `kind = "trammel"`) has no
master. One pin of its `pin_pair` rides in a carriage on each of two straight
rails clamped to the table. Their pin-lines cross at the spindle axis at the
measured rail angle `α`. The pins subtend `α` at the cutter at every pose,
so the cutter centre follows the circle through both pins in the carrier
frame:

`R = D / (2 sin α)`, where `D` is the measured pin spacing.

The circle centre is virtual and moves in the table frame while the carrier
translates and turns through half the swept angle. A second pin pair supplies
a concentric radius without moving the rails. X, Y and Z stay locked while
the operator feeds the carrier with its hand lever. No handwheel moves.
A rough stage is an error because there is no back-off.

As for all guided sweeps, rows stay on the drawing's nominal cutter-centre
arc. The kernel sweeps the exact arc, not its chords; the band check judges
where the pins put the real cut.

#### Trammel radius budget

The cut radius is `R` minus or plus cutter radius, widened by the error
budget. Radius falls with `α` and grows with `D`, so the measured
`rail_angle_error` and `pin_spacing_error` give exact corner extremes
`R(D − δD, α + δα)` and `R(D + δD, α − δα)`.

The first-order angular sensitivity magnitude is
`|∂R/∂α| = D cos α / (2 sin² α)` per radian, or that value times `π/180`
per degree: about 47 mm per degree at `D = 450`, `α = 16.44°`.
Spacing sensitivity is `1 / (2 sin α)` per mm. Each pin-line's
`pin_clearance` plus `rail_offset` also contributes through its exact
worst radius gain over the sweep, about 1:1. The complete band must fit inside
the drawing band. This budget bounds cut radius; the carrier locator controls
where the part centre sits. See
[#270](https://github.com/pedropaulovc/prechips/issues/270).

Pins that do not subtend `α`, a sweep carrying the cutter over a pin, or a
carriage leaving its measured `rail_travel` are errors. The sweep needs its
own setup.

#### Trammel stops and printed procedure

Clamp each stop by steel rule at its printed rail station. Any setting within
0.55 mm of that station, allowing 0.1 mm print rounding plus half a millimetre
of rule setting, must still hold the carrier past its arc end. Otherwise the
sweep is an error and must extend farther. At every pose the first stop can
hold, the cutter must lower clear of stock; an unproved start is debt.

The sheet prints:

1. The external drawing or construction document (`make_document`), the
   commissioning-record location, and the dowel reading against predicted
   stations. Missing commissioning is debt and makes the card a STOP.
2. The pin pair seated in its carriages and X/Y locked at the rails' crossing.
3. A stop on one rail at each end's exact pin station, also read along the
   rail from the carriage's near-end-stop position. The other rail's stations
   provide a check.
4. A dry pass, then lever feed from stop to stop. Cutter sweep angle, cutter
   travel and carrier turn are each named. Repeat for every axial level when
   the op steps down.

Every printed value participates in the same runnable-recipe check: any
unproven value prints only a STOP naming it. The full sequence, measurement
references and propagation of setting error are in
[Trammel operator sequence](rules-coordinates.md#trammel-operator-sequence).
Construction context is recorded in
[#269](https://github.com/pedropaulovc/prechips/issues/269).

## Bounds

`Bounds` is an axis-aligned box expressed as `x`, `y` and `z` intervals.
Its consuming field determines the coordinate frame and validity checks.
For operation clearing boxes, see [Stock removal bounds](#stock-removal-bounds).

| Field | Type (also accepts `"unknown"`) |
|---|---|
| `x` | `Vector` |
| `y` | `Vector` |
| `z` | `Vector` |

## Saw cut-off

`do = "saw_cut"` and `do = "cut_off"` remove a sacrificial end or slab using
an inventory blade in `tools`:

| Blade kind | Supported machine |
|---|---|
| `bandsaw` | `mill`, `bench` or `bandsaw` for a straight cut; a scribed-line cut needs a vertical `bandsaw` |
| `hand_saw` (a hacksaw) | `bench` or `manual` |
| `slitting_saw` (rotating disk; not a bandsaw alias) | `mill` only; finite mounted assembly with the strict path and capture below |

A lathe uses `part_off`, a separate action and model. Nonspindle bandsaw and
hand-saw operations need no spindle holder or direction. A slitting saw needs
its selected `holder`, qualified mounted assembly and conventional-feed
direction. An optional tool `arbor` identity does not prove fit. No saw earns finished-face
coverage. An authored feature must resolve normally; an omitted feature cannot
carry inspection checks.

### Straight cut plane and kerf

```toml
[[setups.ops]]
op = 10
do = "saw_cut"
tool = "metal-blade"
cut_plane = { axis = "y", value = 87.75, keep = "below" }
```

`SawPlane` declares `axis = "x" | "y" | "z"`, numeric `value` in manifest/plan
units, and `keep = "below" | "above"`. Each field can be `"unknown"`.
The plane is the blade centre in setup coordinates, with the inventory `kerf`
straddling it:

- `keep = "below"` retains `coordinate <= value - kerf/2`.
- `keep = "above"` retains `coordinate >= value + kerf/2`.

With 1.5 mm kerf, the fragment retains Y ≤ 87 mm, not Y ≤ 87.75 mm.
The kernel removes kerf and offcut, checks that no finished target was removed,
and passes the retained stock to later setups.

### Mounted slitting-saw path and capture

The `finite_disk_v1` model requires the
[blade and complete arbor inputs](inventory.md#mounted-slitting-saw-assembly).
Planar-only legacy inputs remain unknown for physical slitting support.
The ordinary axial cutter model and linear TPI calculation cannot substitute.
A slitting saw with `follows` remains unknown and cannot route known stock;
arbitrary scribed-region removal is not a finite-disk model.

`saw_trajectory` contains setup-mm `start_mm = [x, y, z]` and a nonempty
`moves` list of `{ to_mm = [x, y, z], mode = "cut" | "clear" }`.
These coordinates locate spindle XY and the cutting-band midplane Z, not
the tooth tip, body face or spindle nose. Exactly one finite, straight,
constant-Z cut is supported, with disk normal along setup Z and numeric
`cut_plane.axis = "z"` at the same converted Z. Manual moves are single-axis.
Diagonals, axial plunges, curves, reversing multi-cut paths and an initially
embedded disk are unsupported. Every pre/post clear move is checked.
The spindle runs only on the cut move and is fully stopped before and after.

Declare `direction = "conventional"`. Machine spindle rotation is viewed
from above down setup −Z. Installed tooth rotation must match it, and the
arbor's retaining side/thread hand must give tightening rather than loosening
tendency. Missing measured rotation facts stay unknown; a wrong sense errors.
The native check also proves placement: for spindle-axis feed `f`, transverse
direction is `(-f.y, f.x, 0)`. The engaged section must lie strictly on its
positive side for clockwise rotation, negative side for counterclockwise.
Touching or crossing the axis fails; the direction label alone is insufficient.
Axis travel here is not the work/table feed direction.

The cut's `saw_capture` declares `fixture`, `pose`, `moving_clamp`,
`moving_clamp_pose` and `state = "clamped" | "released" | "unknown"`.
The primary hold retains the lower remainder; the upper child needs independent
mechanical capture before cutting. Native geometry proves contact with the
actual upper child and includes capture components in collision sweeps.
Released capture errors; missing or unproved capture stays unknown.
Contact geometry does not establish dynamic clamp capacity.

Secure both holds, cut, stop fully with capture clamped, withdraw through the
proved clear/kerf path, then release/retrieve and adjust while stopped.
Both physical children remain in the native stock result and remain obstacles
during withdrawal. Registered [finite-saw outputs](#registered-finite-saw-outputs)
can route both children and split descendants with explicit member accounting.

### Mounted-saw Z setting

Use `method = "mounted_saw_side"` on the Z `AxisZero` or a `ToolTouch`.
A tool touch also names its `holder`. Its `mounted_saw` record declares
`blade_side = "minus_z" | "plus_z"`, `axis_xy_mm`, `point_mm` and
`spindle_state = "stopped" | "running"` (each may be unknown).
A running touch errors; unknown state remains debt.
Name a stock face/z-face or a posed
`fixture:<inventory-reference>/<component-id>:+z` or `:-z` face.
A numeric edge alone does not prove contact.

The proof requires the exposed flat body annulus outside every flange and
inside the tooth root, the correct body side and plane normal, and a clear
axial calibration approach. A broad stock top is not automatically a setting
pad. Each new or reinstalled tool/holder pair needs a matching setting.

For plane Z `E`, paper thickness `p`, body thickness `B` and signed kerf offset
`C`, lower body side on a +Z plane sets cutting-midplane DRO to
`E + p + B/2 + C`; upper body side on a −Z plane sets
`E − p − B/2 + C`. Never substitute kerf width or blade radius for body thickness.
Ordinary and mounted-saw settings do not transfer without the appropriate
touch; ordinary X/Y/Z evidence remains required where used.

### Teeth, holding and starting settings

For bandsaw and hand-saw blades, coarse-end `tpi` times the crossed work
thickness must reach the shop policy's `saw_min_teeth_in_work`. A 4/6 TPI blade
places 0.39 teeth in
a 2.5 mm strap, an error; a 32 TPI blade places 3.15. See
[saw teeth in the work](rules-geometry.md#saw-teeth-in-the-work).

An all-nonspindle-saw setup can include manual inspection and deburring without
a `zero` recipe or mill envelope. `zero_check`, `headroom`, `envelope` and
`travel` report why they are not applicable. A mixed setup still checks its
other machining ops. Any `slitting_saw` operation, even with unresolved
dimensions or verification, prevents this waiver. Its mounted zero and M5
screens use their corresponding evidence; missing facts remain debt.
A passing geometry proof cannot clear an independent zero or measurement
requirement, and a passing touch cannot clear geometry debt.

Holding, `stock_state.top_z/bottom_z`, bound frame and routing still apply.
Declare an ordinary fixture, such as a saw vise with its jaw/parallels fields,
to model it. A bandsaw machine identity does not invent an integral vise.
The exception is [hand-fed work along a scribed line](#hand-fed-on-the-saw-table).

For bandsaws, the setup sheet prints blade-centre setting, retained edge in mm,
linear blade speed in sfm and descent feed in mm/min. Those starting settings
come only from the cited [`saw_cut` cutting-data row](cutting-data.md), never
operation RPM/feed overrides. A mill slitting saw instead uses a cited
rotating-tool chart or unique `operation = "slitting_saw"` row selected by
disk OD: `sfm` and `chip_load_mm_per_tooth` produce spindle-limited RPM and
`RPM × flutes × chip load` feed. Canonical `saw_cut`/descent rows never supply
its numbers. Blade-centre settings, retained edges and sourced speed/feed
retain their own digits; coarse drawing precision does not round machine
settings. Starting numbers do not certify physical slitting clearance.

### Hand saw on the bench, straight or to a scribed line

Every saw op must declare exactly one shape:

- `cut_plane` for a straight cut. Use `cut_plane = "unknown"` while its plane
  is undecided.
- `follows = "<setup>:<op>"` for the line from an earlier `scribe` op.

Any other combination is `BadInput`. The line must be on the saw's workpiece:
scribed earlier in the same setup, or in an ancestor of its `stock_in` route.
Omitted routing establishes no ancestors. An `ends` layout marks only arc
ends and supplies no line for a saw to follow.

A following cut also declares positive `allowance_mm`, the stock left outside
the line for filing, and `stock_removal_bounds`, the setup-frame box removed
by blade and offcut. Neither belongs on a straight `cut_plane` cut.
A gentle curve, such as an R800 arc rising about 13 mm over 292 mm, can be
sawn this way and then filed:

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

#### Scribed-line removal

The box declares what the cut removes under the same clearing-box contract
as a mill operation. The kernel removes only stock inside it and does not
model separate break-out or chisel work.

For an arc laid out in the saw setup's frame, as printed by its `scribe`
card, clip the box to stay `allowance_mm` outside the arc:

- Outside the circle grown by the allowance when the part lies inside it.
- Inside the circle shrunk by the allowance when the part lies outside it.

Removal then follows the curve. A straight scribed line uses the box alone.
Unknown arc layout or unknown arc allowance removes nothing and stays `?`.
An omitted or unknown box also removes nothing. The `saw_cut` finding requests
"declare stock_removal_bounds for <setup:op>", and later stock stays unknown.
Removal closer than `allowance_mm` to the finished target is `✗`.
The following `file_to_line` judges the stock it meets against
`max_filing_stock_mm` and counts the saw as its earlier rough.
See [stock removal bounds](#stock-removal-bounds) for the shared limitations.

#### Powered bandsaws following a line

A bandsaw follows a scribed curve only in vertical mode: a `bandsaw` blade
on a `bandsaw` machine whose `saw_modes` includes `"vertical"`, with work
fed by hand on its table.

| Condition | Result |
|---|---|
| Known modes omit `"vertical"` | `✗` |
| Modes undeclared, or machine/blade unverified, including blade kerf | `?` |
| Bandsaw blade follows a line on a mill or bench | `✗` |

Blade speed comes from the cited `saw_cut` row. There is no descent feed:
the card prints "by hand", the hold's feed in its direction cell
("feed from +X toward -X"), and "leave at least <allowance> mm on the waste side of the
scribed line" in its target. The target is the one place that names the waste
side. A straight bandsaw cut needs no vertical mode.

```toml
[[setups.ops]]
op = 10
do = "saw_cut"
tool = "bandsaw-blade-4-6"       # kind = "bandsaw"; machine saw_modes = ["horizontal", "vertical"]
follows = "S4:20"                # the R816 arc's scribe
allowance_mm = 1.0               # left for the trammel pass
stock_removal_bounds = { x = [-150.0, 150.0], y = [-10.0, 6.0], z = [-20.0, 1.0] }
```

### Hand-fed on the saw table

`hold.kind = "hand_fed"` declares a vertical bandsaw cut along a scribed line,
with no vise or clamp holding the work. Only its optional note and four
feeding fields belong beside `kind`:

```toml
[setups.hold]
kind = "hand_fed"
note = "bar flat on the saw table, scribed face up"   # optional
guide_above_mm = 6.0          # upper blade guide above the top of the work
push_aid = "push-stick"       # an inventory fixtures item
feed_from = "-X"              # the end of the line the cut starts from
end_support = "push_aid"      # or "outfeed_table": how the end of the cut is supported
```

#### Admitted operations and unresolved declarations

`fixture`, `stop`, `grip_mm`, `clamp`, `fixed_jaw` and every other hold field
are `BadInput` in a hand-fed hold. Feeding fields on any other hold are also
bad input, as is a nonpositive `guide_above_mm`.

Each undeclared feeding field remains `?` in `hold_fields` and prints a
HOLD STOP. `push_aid` must resolve to an inventory fixture. A missing `kind`
means an ordinary fixture hold; `hand_fed` is not a reserved fixture name.
Fixture references still resolve by their inventory keys.

Every op in an admitted hand-fed setup must be `scribe`, `deburr`, `inspect`,
or a `saw_cut`/`cut_off` that follows a scribed line using a verified `bandsaw`
blade on a `bandsaw` machine whose `saw_modes` includes `"vertical"`.
There must be at least one such saw cut; several following saw cuts are allowed.
File to the line in a separate setup, held in a vise.

A known milling op, straight `cut_plane` cut, hand saw, horizontal-only
bandsaw, different machine kind or setup known to contain no saw is
`BadInput` (exit 3), with the reason named. An unknown action, unresolved blade,
machine or `saw_modes`, or `kind = "unknown"` can load but leaves the hold `?`.
A known out-of-scope operation still refuses the hold when another is unresolved.

Once admitted, the hold needs no fixture fields in `hold_fields`; coolant,
deburr and stock Z declarations still apply. `stock_diameter`, `vise`,
`thin_wall_under_clamp` and `fixture_interference` are `not_applicable`.
The kernel draws no fixture and requires no fixture measurement.

#### Feed direction and holding picture

The HOLD uses the resolved scribe identity, for example:
"Fed by hand on the saw table, sawing guided by the line scribed in S1 op 10; no vise or clamp holds the work."
It then prints each feeding declaration: guide height, push aid, cut-start
end and end-of-cut support. STOCK AND ROUTE uses the same resolution for its
"fed by hand on the saw table" holding cell.

The holding picture draws the saw table, blade at cut start up to the declared
guide height, and push aid behind the trailing end. Each is labelled and
render-only, never hit-tested. All use the same `feed_from` as the HOLD.
The named end leads into the stationary blade, so the work moves toward
`feed_from`. The push aid stands at the opposite end. Arrows point from the
trailing end toward blade entry. The top-face picture shows the saw path,
the scribed arc offset into waste by the allowance, with
"WORK FEED INTO THE BLADE" arrows.

The operation's profile sketch uses one transform for real setup coordinates:

- A thin setup-entry blank outline and one heavier scribed line, restricted
  to `stock_removal_bounds`.
- Shaded waste and unshaded keep side. The keys are SCRIBED LINE,
  "WASTE: SAW HERE, 0.450 MM MIN OFF THE LINE" and KEEP.
- Feed arrows alone in waste, 3 mm off the line, never on it or forming a
  second line.
- Hollow squares at the scribed LINE END points and, when `feed_from` is
  usable, crosses at the cut's ENTER and LEAVE.

It draws no separate saw path there: 0.45 mm is not visible on a 290 mm arc.
Undeclared `feed_from` draws no arrows, ENTER/LEAVE, blade or push aid.
Neither does a direction that selects no line end: the two ends are less than
1 mm apart on that axis, such as `+Y` on a symmetric top arc. `hold_fields`
leaves it `?`, and HOLD plus the op's direction cell print a STOP naming why.

The target states allowance once as a minimum:
"leave at least 0.450 mm on the waste side of the scribed line".
The direction cell states the feed, such as "feed from +X toward -X".

#### Cut entry and exit landmarks

When the line reaches the setup-entry blank outline and leaves no waste at
its ends, the target adds the actual cut crossings. It intersects the
allowance-offset saw path with the kernel entry box inside
`stock_removal_bounds`, in the setup frame, ordered entry-first from
`feed_from`. For example:

"Enter at X -142.741, Y 21.295 and leave at X 142.741, Y 21.295 on the +Y face (from Setup S2 zero): where the cut, 0.450 mm off the scribed line on the waste side, meets the +Y face."

These crossings are inward of the line's own ends at X ±145.240.
A bench hand saw prints "Cut through at ...". A line wholly inside the blank,
or crossings the kernel cannot place, adds no such landmarks. The sketch
uses crosses for ENTER/LEAVE and hollow squares for LINE END to keep them
distinct.

If the stock note prints model (STEP) coordinates without naming a setup
zero, every op row that prints setup coordinates names its frame, such as
"(from Setup S2 zero)". This applies to layout centre/ends, cut entry/exit,
hole tool axes and manual-arc centres.

#### Minimum work size for hand feeding

`numbers.min_hand_feed_mm` is the shop safety procedure's minimum allowed
finger-to-blade distance. A cited procedure might say "if your cut will require your fingers to get within 3 inches of the blade, use a push stick",
76.2 mm. This is a shop-owned threshold, not a built-in recommendation.

For every cut, `hold_fields` samples the allowance-offset scribed arc at
most 1 mm apart where that cut's stock box and `stock_removal_bounds`
overlap in setup X/Y and Z. The kernel cuts nowhere else. Its stock box is
`stock_bbox_before_mm`, after all earlier cuts. Only the first saw cut can
fall back to the setup-entry box; a later cut never borrows it.

At every blade position, enough work must remain at least the minimum
distance away to hold. The tight stock box bounds the farthest available work:

- Lower bound: the largest of the sides' nearest distances. Some work lies
  on every side of the box.
- Upper bound: the distance to the farthest corner. No work lies beyond it.

| Distance evidence over the cut | Result |
|---|---|
| Every sampled lower bound, after subtracting the 1 mm sampling step, reaches the minimum | Pass |
| Any position's upper bound falls below the minimum | `✗`, naming both distances |
| Bounds fall between those cases | `?` |

A known shortfall at any position is an error even when another cut has an
unknown stock box, path or other debt. Only when no known shortfall exists does
that debt make the result unknown. A pass requires all cuts to be resolved
and every lower bound to reach the minimum.

The minimum is unknown when absent, nonpositive, uncited or still flagged for
verification. The resolved `numbers_verify` value must be false; a missing
flag defaults to false. A missing per-cut stock box, unplaced blade path,
straight scribed line, nonnumeric removal box or removal box that does not
meet that cut's stock in X/Y/Z also leaves debt.

Each cut's bounds appear in `hand_fed_reach_by_op`; `hand_fed_reach_mm`
records the worst over all cuts, and a failing cut is named. This check
neither places hands nor plans push-stick use. See the
[hand-fed-saw fixture](../examples/geometry/hand-fed-saw/plan.toml).
The per-cut stock requirement is recorded in
[#347](https://github.com/pedropaulovc/prechips/issues/347), and the work-size
check in [#343](https://github.com/pedropaulovc/prechips/issues/343).

### Manual bench exemption

A `bench` or `manual` setup is manual bench work when every saw uses a verified
`hand_saw`, and all other actions are `fit`, `inspect`, `deburr`, `coating`,
`scribe` or `file_to_line`. Its DRO, zero and headroom screens are
`not_applicable`; `speeds_feeds` supplies no hand-saw blade speed or feed.
A powered or unresolved blade on a bench waives nothing.

The setup sheet puts the hand saw on the assembly/finishing card, for example
"Hand saw, blade centred on Y 87.75 mm; keep the side below it", or
"Hand saw guided by the line scribed in S4 op 10, leave at least 0.5 mm on the waste side of the scribed line for filing".

