# M4 geometry fixtures

Discriminating bundles for the seven geometry rules (`accessibility`, `reach`,
`internal_corner_radius`, `coverage`, `finish_coverage`, `vise`,
`thin_wall_under_clamp`) on the FreeCAD kernel. Every traveler remains
**PLANNED**. These are authored test processes, not measured shop inventory,
approved toolpaths or drawing requirements.

Each candidate starts from a numerically placed blank with stock allowance.
One or two preparation setups declare the removed volumes with
`stock_removal_bounds`; the target setup therefore receives stock derived from
**earlier** setups, rather than silently borrowing the finished STEP solid.
Preparation tooling and holding remain explicit measurement debt. The local
policy requires target operation/setup geometry and the part-wide coverage
and finish checks; it does not certify the preparation operations.

Clearing boxes must fit the claimed faces' union XY bbox plus cutter radius
(zero for unknown tooling). The synthetic rocker therefore uses the STEP's
measured global XY bbox, `x = ±146.254568`, `y = 0..29.29464` mm, for both
its rectangular supply and opposed clearance boxes; its 1 mm allowance on
each Z end remains. The former extra XY margins had no claimed cutter radius.

| bundle | STEP | expected exit | discriminating finding |
|---|---|---|---|
| `rocker-jaw-occluded/plan.toml` | real labelled v40 `rocker-arm.STEP` | 2 | target `accessibility S3:10` error: the cutter beside the strap face meets the jaw and hub boss; `vise S3` pass |
| `pocket-reach/plan.toml` | synthetic `pocket-block.STEP` | 2 | target `reach S2:10` error: 45 mm depth exceeds the 19 mm flute and the holder hits the pocket; accessibility also errors on the holder |
| `pocket-reach/long-reach.toml` | synthetic `pocket-block.STEP` | 0 | same prepared pocket, holder and claims; the 100 mm OAL cutter clears the holder and passes target accessibility and reach |
| `sharp-corner/plan.toml` | synthetic `slot-block.STEP` | 2 | `internal_corner_radius S2:10` error: sharp claimed corners against the 1/4 in cutter's 3.175 mm radius |
| `unclaimed-face/plan.toml` | synthetic `step-block.STEP` | 2 | `coverage step-block` error naming `#185/ADVANCED_FACE[6]/`, claimed by no operation and not supplied as-stock |

The short/long pocket pair differs only in the target cutter. Its target
claims the vertical pocket walls and corners, while preparation claims the
floor. A centred tool pose on a floor boundary point would genuinely meet
the adjacent wall under the strict own-face exclusion; omitting that pose
from this side-wall discriminator is not a claim that the kernel searches
alternative floor-machining paths. The sharp-corner candidate can also
report accessibility collisions at its corners.

## Shared inputs

- `inventory.toml` is a **synthetic test shop**. Its nominal values can be
  consumed by the kernel, but are not measurements of Pedro's shop
  (`../inventory/pedro-shop.toml`), catalogue facts or purchases. Cutters have
  numeric diameter, flute, OAL and shank dimensions; collets have numeric
  gauge cylinders and grip. Projection falls back to OAL minus grip when no
  selected tool/holder projection is authored.
- Target setups declare `hold.jaw_center_along_mm` and
  `hold.parallels_centres_mm`. The block targets centre their jaws on the
  stock's length; the rocker target centres its 320 mm jaws on the pivot
  and places the parallels under its tips. These target scenes have exact
  brown jaws and green parallels. Preparation setups have unresolved
  holding, so their known-stock pictures do not claim a complete fixture.
- Holding, renders, reach and holder obstacles use immutable **entry stock**.
  Only a cutter's flute excludes its own operation's derivable outside-finished
  allowance, never another operation's removal or a neighbouring finished wall.
  Block blanks are one millimetre taller than their finished outer envelopes;
  preparation clears the top allowance and pocket/step material. The rocker
  uses opposed +Z/-Z preparations before the upright target. Invalid bounds
  or non-derivable stock never fall back to a finished-part clearance pass.
- `shop-policy.toml` and the bundle-local policies require the seven
  geometry families on the focused target subjects and the part-wide
  claims. `thin_wall_floor_mm = 2.0` is an authored test threshold, not a
  sourced shop limit.
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
`../rocker-arm` binds the same bytes and preserves its exported manifest.
Its S1 strap operations explicitly claim the top datum-B face `#492` instead
of changing `strap_faces`, whose truthful exported face is the bottom. The
tip lands remain unclaimed. Its numeric rectangular supply is drawn in S1;
the later stock is unknown because the production route does not author
the interrupted profile/retained rail-and-ear removal footprint. It therefore
does not emit fictitious S2/S3 finished-part stock views.

The target setup is a test specification, not a production process: after
opposed preparation the arm stands on its tips (frame V: model −Y up,
pivot axis horizontal across the jaws). The synthetic 320 mm vise closes on
the hub's planar faces, and the jaw tops stand beside the strap. The target
operation side-mills the +Z strap face with the prescribed offset Ø8 cutter
pose. The jaw and proud hub material remain obstacles; only the sampled
face's thin inward shell is excluded.

## Kernel conventions the fixtures rely on

As implemented in `src/prechips/kernel/freecad_job.py` and documented in
`docs/rules-geometry.md`:

- **Seat and jaw zone.** Entry stock is seated with its lowest setup-frame z at
  the parallels' top; the jaw zone runs from that seat up to
  `jaw_above_parallels_mm` and, because the target setups declare
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
  holder cylinder from `projection_mm` above the tip. The obstacle is entry
  stock, less a 0.001 mm inward shell of the **sampled face**, plus jaws.
  The flute also excludes only its own op's outside-finished allowance.
  Other finished faces remain obstacles. No cutter-radius slab,
  full-feature union or sharp-corner air wedge is removed. A hit means that
  prescribed pose collides, not that no other pose reaches the face.
  Far-side claims error by STEP reference; missing normals leave the face
  unknown rather than counting it clear.
- **`reach`.** `reach_depth_mm` is the highest entry-stock material within the
  cutter radius above each sample minus the sample height;
  `holder_wall_hits` counts holder intersections with the full entry stock.
- **`internal_corner_radius`.** Concave vertical edges shared by two claimed
  faces count as radius 0; claimed concave cylinders whose axis is parallel to
  the tool report their radius; floor-to-wall edges are ignored.
- **Render.** `setup-S<n>.png` is a 640 × 480 orthographic rasterization of
  entry stock (grey), exposed claimed faces (blue), jaws (brown) and
  parallels (green), without timestamps or machine metadata. The report
  binds each picture's path, SHA-256 and scene state. Unknown entry stock
  produces no picture; unresolved holding is named in the caption.
  `*.png binary` preserves frozen image bytes through Git checkout/archive.

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
