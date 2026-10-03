# M4 geometry fixtures

Discriminating bundles for the seven PLAN.md rev 6 §4.2–4.3 geometry rules
(`accessibility`, `reach`, `internal_corner_radius`, `coverage`,
`finish_coverage`, `vise`, `thin_wall_under_clamp`) on the FreeCAD kernel. Each
failing candidate errors on **one named rule only**; its other geometry rows
pass or are not applicable, and the M1/M2 rows it does not exercise print as
`?` lines (the policy here requires only the geometry rules). Every traveler
stays **PLANNED**. Nothing in this directory is a shop process, a measured
inventory item or a drawing requirement.

| bundle | STEP | expected exit | discriminating finding |
|---|---|---|---|
| `rocker-jaw-occluded/plan.toml` | real labelled v40 `rocker-arm.STEP` | 2 | `accessibility S1:10` error: 56 of 65 strap-face samples occluded by the jaw standing beside the face and the hub boss; `vise S1` pass |
| `pocket-reach/plan.toml` | synthetic `pocket-block.STEP` | 2 | `reach S1:10` error: 45 mm floor, 19 mm flute, holder nose 7 mm below the top face hits the walls (161 samples); the same holder occlusion also errors `accessibility S1:10` |
| `pocket-reach/long-reach.toml` | synthetic `pocket-block.STEP` | 0 | same pocket, same holder, 100 mm OAL cutter: `reach S1:10` pass (depth beyond flute, within OAL, holder clear); every required row pass / not applicable |
| `sharp-corner/plan.toml` | synthetic `slot-block.STEP` | 2 | `internal_corner_radius S1:10` error: claimed corner radius 0 against the 1/4 in cutter's 3.175 mm |
| `unclaimed-face/plan.toml` | synthetic `step-block.STEP` | 2 | `coverage step-block` error naming `#185/ADVANCED_FACE[6]/`, cut by no op and not declared as-stock |

Exits are the observed CLI exits of the frozen `expected/` outputs; two
consecutive runs, and runs from two empty kernel caches, were byte-identical for
`report.json`, `traveler.html` and `setup-S1.png`. `pocket-reach/plan.toml`
carries two errors on the same subject because a holder inside the pocket is
both a reach failure and an occlusion; `reach` is the rule the pair
discriminates (only the cutter's OAL differs between the two candidates).

## Shared inputs

- `inventory.toml`: a **synthetic test shop**. Every number is an authored
  fixture choice, flagged `verify = false` so the rules read it, and none is a
  measurement of Pedro's shop (`../inventory/pedro-shop.toml`), a catalogue fact
  or a purchase. Standalone cutters (`kind = "endmill"`: `dia_mm`,
  `flute_len_mm`, `oal_mm`, `shank_mm`), R8 collets with the holder cylinder
  (`gauge_dia_mm`, `gauge_len_mm`) and shank engagement (`grip_mm`, so a cutter
  projects `oal_mm − grip_mm`), two vises with all four jaw dimensions
  (`jaw_width_mm`, `opening_mm`, `jaw_height_mm`, `jaw_depth_mm`; the kernel
  never synthesizes a missing one) and one pair of 150 × 6 × 20 mm parallels
  (`kind = "parallels"`: `length_mm` along the jaws, `width_mm` along the clamp
  axis, `height_mm`). The 320 mm `test-vise-wide` covers the arm's whole span.
  Without an authored jaw centre, a part longer than the jaws leaves their pose
  unresolved; an exact centre instead bounds the grip zone to the declared span.
- Every plan declares the **exact scene**: `hold.jaw_center_along_mm` puts the
  jaw centre on the block's mid-length (35 or 30) or on the rocker's pivot axis
  (0), so the full jaw width is drawn rather than the undeclared envelope, and
  `hold.parallels_centres_mm` places the two parallel prisms by their
  setup-frame XY centres under the seat: 2–8 mm inside each jaw plane for the
  blocks, end to end along the jaws (x −150..150, y ±3) under the rocker's two
  tips. Every frozen report therefore carries `renders.S1.fixture =
  "modeled"` and `scene = {jaws: "exact", parallels: "exact", debts: []}`,
  and the sheet caption describes a complete fixture view. These are designed
  poses for a synthetic vise, not measured production setups.
- `shop-policy.toml`: requires the seven geometry rules and nothing else;
  `thin_wall_floor_mm = 2.0` is a synthetic threshold (`numbers_verify = false`)
  chosen so each fixture's grip-zone wall clears it, not a sourced shop limit.
- Cutting data is the shared `../cutting-data.toml`; the speeds/feeds rows are
  `?` lines in every fixture and are not under test.

## Synthetic solids and their provenance

`author_solids.py` is the provenance of the three designed test solids. It runs
only under `freecadcmd.exe` (FreeCAD 1.1.4, STEP AP214, Open CASCADE 7.8 writer):

```
freecadcmd.exe examples/geometry/author_solids.py -- build
freecadcmd.exe examples/geometry/author_solids.py -- faces <file.STEP>
```

`build` is **not** a build step: the STEP header carries a timestamp, so
re-running it changes the bytes, the digests and possibly the entity numbers.
The committed synthetic STEP files (written with LF line endings) are the frozen
fixtures; `features.toml` binds them by `step_sha256`, and `prechips` refuses a
mismatch. The authored dimensions:

- `pocket-block`: 70 × 50 × 60 mm, closed 40 × 24 mm pocket, R6 vertical
  corners, 45 mm deep from the top (floor z = 15). Fifteen faces.
- `slot-block`: 60 × 40 × 20 mm, closed 30 × 12 mm pocket with sharp vertical
  corners, 6 mm deep (floor z = 14). Eleven faces.
- `step-block`: 60 × 40 × 20 mm with the +X half stepped down 10 mm. Eight faces.

### Face references

A reference is `#<entity>/ADVANCED_FACE[<ordinal>]/<label>`: the STEP entity
number, the 1-based position of that `ADVANCED_FACE` record in file order, and
the record's own label (FreeCAD writes an empty label; the consumer's labelled
export writes `HAF_<FEATURE>__P<nn>`, and a periodic surface split into
patches repeats one feature label with P01/P02, so a label alone never
identifies a face). It is never FreeCAD's import ordinal. `author_solids.py
faces` prints every reference with the plane normal/offset or cylinder
axis/radius read from the STEP text, which is how the synthetic manifests were
bound (e.g. the pocket floor is the `PLANE` with normal (0, 0, 1) at offset
15). The kernel resolves each reference against the STEP text first — a
reference whose entity, ordinal or label disagrees with the record is an
`invalid STEP face reference` error naming it, never a guess — then matches
the record's surface kind, area and bounding box against the imported solid;
`scripts/validate_examples.py` re-reads the records independently.

## rocker-jaw-occluded: the real labelled export

`rocker-arm.STEP` is the consumer's labelled v40 export, delivered read-only as
`C:/src/dt-logs/features-bundles/rocker_arm/rocker-arm.STEP` and copied
**byte for byte** (CRLF line endings preserved; `.gitattributes` marks
`examples/**/*.STEP -text` so checkout cannot rewrite it; bound SHA-256
`19070131…`). It is a SolidWorks inch export with eighteen `ADVANCED_FACE`
records labelled `HAF_<FEATURE>__P<nn>`: the two patches of the pivot bore
both carry `HAF_PIVOT_BORE__P01` (`#233/ADVANCED_FACE[5]`,
`#382/ADVANCED_FACE[8]`), the rod hole likewise, and each hub cylinder is
split into `HAF_HUB_OD__P01` / `P02`. The fixture manifest's feature names and
`faces` lists are the consumer's exported face sets
(`features-bundles/rocker_arm/features.toml`) verbatim, so the one claimed
face is the export's `strap_datum_b` (`#492/ADVANCED_FACE[13]`, the +Z broad
face, datum B) and `strap_faces` is the −Z face only; the tip lands are the
export's `tip_land_pos_x` / `tip_land_neg_x`. Nominal dimensions quoted in the
notes are the consumer's source geometry, cited as in
`../rocker-arm/features.toml`; nothing is measured. The M1 reference bundle
`../rocker-arm` binds the same bytes and the exported face sets of its seven
existing features; the export's three extra features have no counterpart
there and are left unbound rather than invented, so its `coverage` row stays
`?` naming them and its renders are part-only views (the shipped shop vise
and parallels lack the jaw/parallel dimensions).

The setup is a test specification, not a process: the arm stands on its tips
(frame V: model −Y up, pivot axis horizontal across the jaws) on the parallel
pair laid end to end along the jaws, with the synthetic 320 mm vise centred on
the pivot closing on the two hub faces (`width_mm` 7.0565, a parallel planar
pair, so `vise` passes) and the jaw tops 26 mm above the parallels, 3.3 mm
below the outer arc. The one op side-mills the +Z strap face,
which lies 2.278 mm inside the rear jaw plane. The offset Ø8 cutter cylinder
beside that face hits the jaw and, above the pivot, the 2.278 mm proud hub
boss; the kernel excludes only the claimed face's own feature from the
obstacle. Dropping the jaw tops to the tips (`jaw_above_parallels_mm = 1.0`,
which also fails `vise`) leaves 9 of the 65 samples occluded, so at least 47
hits are the jaws: the §6 round-2 observation that a zero-radius ray cannot see
a jaw standing beside a face, but the cutter cylinder can.

## Kernel conventions the fixtures rely on

As implemented in `src/prechips/kernel/freecad_job.py` and documented in
`docs/rules-geometry.md`:

- **Seat and jaw zone.** The part is seated with its lowest setup-frame z at
  the parallels' top; the jaw zone runs from that seat up to
  `jaw_above_parallels_mm` and, because every plan here declares
  `jaw_center_along_mm`, is limited along `jaws_along` to the jaw span. The
  inner jaw planes sit at the zone material's extremes along the clamp axis
  (the horizontal axis that is not `jaws_along`; `fixed_jaw = "rear"` is +Y
  for `jaws_along = "x"`).
- **Exact jaws versus the undeclared envelope.** With `jaw_center_along_mm`
  each jaw box spans the full `jaw_width_mm` centred on that value ×
  `jaw_depth_mm` outward × `jaw_height_mm` down from the jaw top, and the
  scene records `jaws: "exact"`. Without it the dark jaws would span only the
  part's grip-zone extent, pale strips would mark where the remaining width
  may lie, cutter samples inside those strips would stay `?`, and the scene
  would record `jaws: "lateral_undeclared"` with that debt; none of the frozen
  fixtures is in that state (`tests/test_geometry_examples.py` strips the pose
  from `long-reach.toml` to prove the difference).
- **Parallels are drawn supports.** Two prisms, `length_mm` along the jaws ×
  `width_mm` along the clamp axis × `height_mm` down from the seat, stand at
  the plan's `parallels_centres_mm`; a prism intersecting a jaw box is a
  scene debt. They lie below every tool and holder cylinder and never enter a
  hit count, so the scene state `parallels: "exact"` is a picture fact, not a
  rule input. Without centres or dimensions the scene records `parallels:
  "not_modelled"`.
- **`vise`.** `parallel_pair` is true only when each jaw plane is touched by a
  planar part face whose outward normal is exactly ±clamp axis;
  `contact_grip_mm` is the merged z-extent of those faces inside the zone;
  `width_mm` is the part extent between the jaw planes.
- **`accessibility`.** A cell-centred 5 × 5 UV grid plus boundary points on
  each claimed face; at every sample one prescribed pose: the cutter cylinder
  (radius, flute length) with its axis offset by the radius along the
  horizontal part of the outward normal, tip at the sample height, and the
  holder cylinder from `projection_mm` above the tip. The obstacle is the part
  minus the op's own region plus the jaw boxes; the own region is the material
  within the radius of the claimed faces, with each sharp concave edge shared
  by two claimed faces carved by the radius cylinder minus the open-corner air
  wedge in front of both faces. A hit means that pose collides, not that no
  other pose reaches the face; downward-facing samples are occluded.
- **`reach`.** `reach_depth_mm` is the highest part material within the
  cutter radius above each floor sample minus the sample height;
  `holder_wall_hits` counts samples whose holder cylinder meets the **full**
  part, which is the rescue a long cutter must prove.
- **`internal_corner_radius`.** Concave vertical edges shared by two claimed
  faces count as radius 0; claimed concave cylinders whose axis is parallel to
  the tool report their radius; floor-to-wall edges are ignored.
- **Render.** `setup-S1.png` is a 640 × 480 orthographic flat-shaded
  rasterization of the kernel's own tessellation (part grey, claimed faces
  blue, fixed and moving jaw boxes two browns, parallels green) with no
  timestamp or machine metadata, so its bytes repeat. The report binds it as
  `renders.S1 = {path, sha256, fixture, scene}` and `inputs["render:S1"]`;
  `fixture = "modeled"` only with exact jaws, exact parallels and no debts.

## Regeneration

Only after a deliberate rule or kernel change, from the repository root, with
FreeCAD installed:

```
uv run prechips traveler examples/geometry/<bundle>/plan.toml --out examples/geometry/<bundle>/expected
uv run prechips traveler examples/geometry/pocket-reach/long-reach.toml --out examples/geometry/pocket-reach/expected/long-reach
```

Run each twice and confirm the bytes repeat before committing;
`tests/test_geometry_examples.py` and `scripts/validate_examples.py` hold the
exits and the discriminating findings above.
