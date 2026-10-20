# T-nut geometry provenance

**EXAMPLE ONLY — NOT FOR EXECUTION IN A REAL ENVIRONMENT**

The authored inputs now complete a four-member demonstration route. Source-video
and catalogue facts remain distinct from the explicitly adopted acceptance bands,
equipment selections and commissioning fixtures described below. No physical
measurement, executed inspection, first-article approval or machining success is
claimed.

Source: Blondihacks, <https://www.youtube.com/watch?v=TL0OsfFkBL8>.
The local MP4 inspected for this reconstruction is the actual downloaded video,
1920 × 1080, duration 1085.3 seconds; the adjacent `en-orig.vtt` provides captions.
Captions contain transcription errors (for example “tea nuts” and “40 bolts”);
the visible operations and spoken context establish four T-nuts, not forty.
This is a **catalog-based example design using the video's machining process**,
not an exact replica of either the video part or a commercial product.

## Recoverable facts

| Fact | Evidence | Meaning |
| --- | --- | --- |
| Four nuts, each 1 inch long | 02:42–02:50 | Nominal finished X length 25.4 mm; the extra 0.100 inch is separation allowance, not a finished dimension. |
| 1018 steel | 02:12 stock marking; narration 03:59 | Material identity; no heat-treatment condition or certificate is given. |
| Bottom flange 0.250 inch thick | Narration 06:47; frame 06:50 explicitly overlays `250 thou = 6.35mm` | Nominal Z shoulder elevation 6.35 mm above the bottom. |
| Symmetric shoulders | 07:17–07:33 | The two long edges are edge-found and the Y half function establishes the centerline. |
| Final cutter-center offset 0.477 inch from center | 08:03 narration; frame 08:07 overlays `477 thou ≈ 12.1mm`; 09:43 narration | This is a **tool-center coordinate**, not the stem half-width. Frame 09:45 shows Y 0.47657 near that nominal position. The roughing coordinate is ±0.487 inch, leaving 0.010 inch for finishing. |
| Centered tapped hole, 3/8-16 | Hardware identification 02:29–02:37; hole location 12:52–13:08; drill/tap 13:11–13:32 | Hole centered in X and Y; tap is a taper tap and the hole is through. No thread class is stated. |
| Break edges and deburr holes | 13:48–14:15 | Noga hand deburring tool and needle files; no numerical chamfer or edge radius. |
| Stake the final bottom thread | 14:43–15:04 | A punch distorts the bottom thread to prevent a stud passing through. No deformation dimensions or stud engagement limit. |
| Cold blue, rinse, dry, buff, oil | 15:06–16:45 | Surface finishing, not a quantified coating thickness or dimensional allowance. |

## Dimensions not specified by the video

The inspected sizing/caliper scenes (including 04:51, 05:23, 05:31), cutter
close-up (07:41), and finished profile view (10:29) do not establish an unambiguous
numerical finished base width, total height, stem width, or shoulder cutter diameter.
The video explains measuring the recipient mill's T-slot (01:30–02:09) rather than
publishing a universal T-nut drawing. Without the cutter diameter, the relation
`stem width = 2 × 0.477 inch − cutter diameter` cannot produce a source dimension.
The actual tapping-drill diameter is not spoken or legibly identified.

No tolerance, fit band, surface-roughness value, edge-break size, thread class,
staking displacement, or coating thickness is inferred. The statement at
17:39 that there are no tolerances to worry about is not a numerical acceptance
specification. Fit to another mill is not established by this model.

## Selected catalog-based example design

The selected cross-section follows the published nominal dimensions of Carr Lane
**CL-0-TN**, [manufacturer T-nut catalog](https://www.carrlane.com/product/clamping-hardware/studs-bolts-t-nuts/t-nuts),
consulted 2026-10-18. Its drawing identifies B as actual stem width, C as base
width, D as length, E as overall height, and F as flange thickness.
Importantly, its nominal 1/2-inch **table slot** is not the actual B dimension.

| Parameter | Model value | Source |
| --- | --- | --- |
| Base width | 22.225 mm (0.875 inch) | Carr Lane CL-0-TN C = 7/8 inch. |
| Overall height | 12.7 mm (0.500 inch) | Carr Lane CL-0-TN E = 1/2 inch. |
| Stem width | 12.573 mm (0.495 inch) | Carr Lane CL-0-TN B = 0.495 inch. |
| Length | 25.4 mm (1 inch) | Video 02:45; deliberately differs from CL-0-TN D = 7/8 inch. |
| Flange thickness | 6.35 mm (0.250 inch) | Video 06:47; deliberately differs from CL-0-TN F = 9/32 inch. |
| Thread designation | 3/8-16 | Video 02:35 / 13:11; also Carr Lane CL-0-TN A. |
| Simple bore diameter | 9.525 mm (0.375 inch) | Nominal thread major diameter used as a cosmetic envelope; **not the tapping-drill size**, minor diameter, or thread profile. |

These are selected, cited design dimensions, not claims to have recovered the
missing video measurements. The catalog drawing gives B +0/−0.010 inch,
C ±0.010 inch, F +0/−1/64 inch, and a Class 2 thread. These identify the source
product; they are **not imported as acceptance limits** for this adapted design.
No catalog tolerance is silently applied to a dimension taken from the video.
Catalog steel/heat-treatment/finish or strength properties are likewise not
transferred to a video-process 1018-steel example.

The model is centered on X/Y: X is the one-inch length, Y is transverse,
and Z points from the flat bottom at Z=0 toward the top at Z=12.7 mm.
The through-bore axis is X=Y=0, parallel to +Z. The solid has ideal sharp
edges; unspecified edge breaks, helical threads, staking deformation,
and cold-blue surface effects are not geometrically represented. In particular,
the simple bore does **not** stop a stud: the real video's staked-bottom-thread
function must not be inferred from this STEP. This catalog-based nominal design
does not establish fit to the viewer's actual table, strength, clearance, or physical
acceptance. Measure the recipient slot and verify the finished part separately.

### Supplemental nominal part illustration

[Nominal finished design](part-reference.svg) is an isometric illustration generated
from the validated nominal B-rep using FreeCAD TechDraw's native hidden-line
removal (`projectToSVG`) and a fixed isometric projection, with only visible
CAD edges and no mesh shading. It is explicitly labeled **“Nominal finished
design — not stock, holding or fit approval”**. It is not a setup render, a
stock-state image, a fixture model, or evidence of tool access or physical fit.
No workholding or stock geometry is added to the illustration.

## Reproduction and observed export

Run with FreeCAD, not the project Python environment:

```text
freecadcmd.exe examples/blondihacks-t-nuts/build_part.py
```

The script checks the constructed solid, privately exports `t-nut.STEP`,
normalizes only the non-geometric `FILE_NAME` header (fixed epoch timestamp, no
absolute path), and compares its LF bytes with the existing frozen STEP. If the
bytes differ it fails without replacing the existing file; an absent STEP is
created. It then reimports the STEP, generates `part-reference.svg`, and emits a
`TNUT_JSON` summary. Byte identity across FreeCAD/OpenCascade versions is not
promised; a version-dependent mismatch preserves the committed reference.

Observed with FreeCAD 1.1.4 / build 20260928: valid reimported B-rep, one solid,
11 faces, bounds `(-12.7, -11.1125, 0)` to `(12.7, 11.1125, 12.7)` mm,
volume **4707.621531549312 mm³**.

STEP SHA-256:
`456cdbe656f84b5b3236b8878c820f1e64a21944a61bdc6165fd39fe2fe5336e`.

The frozen file contains one `MANIFOLD_SOLID_BREP`, entity `#15` with an empty
label, enclosing `CLOSED_SHELL` entity `#16`. The manifest names that source
`canonical-nut = "#15/MANIFOLD_SOLID_BREP[1]/"`; the source shell contains faces
`#17`, `#57`, `#88`, `#130`, `#161`, `#192`, `#223`, `#265`, `#287`, `#304`
and `#320`. These are source-text identities, not imported-solid indices or a
claim of four solids in the STEP. The four authored `plan.workpieces` registrations
instantiate this one canonical source with their separately declared poses.

The repository's existing `examples/geometry/author_solids.py -- faces` tool
derived these references from STEP surface geometry, not guessed face order.
Normals below point out of the solid; all plane positions are in model mm.
References bind to the committed STEP bytes and must be regenerated after
geometry/export changes.

| Role | STEP face reference | Geometric match |
| --- | --- | --- |
| +Y shoulder shelf | `#17/ADVANCED_FACE[1]/` | +Z plane Z=6.35; shelf center Y=8.6995 |
| +Y flange side | `#57/ADVANCED_FACE[2]/` | +Y plane Y=11.1125 |
| Bottom | `#88/ADVANCED_FACE[3]/` | −Z plane Z=0 |
| −Y flange side | `#130/ADVANCED_FACE[4]/` | −Y plane Y=−11.1125 |
| −Y shoulder shelf | `#161/ADVANCED_FACE[5]/` | +Z plane Z=6.35; shelf center Y=−8.6995 |
| −Y stem side | `#192/ADVANCED_FACE[6]/` | −Y plane Y=−6.2865 |
| Top | `#223/ADVANCED_FACE[7]/` | +Z plane Z=12.7 |
| +Y stem side | `#265/ADVANCED_FACE[8]/` | +Y plane Y=6.2865 |
| Cosmetic bore wall | `#287/ADVANCED_FACE[9]/` | Cylinder radius 4.7625; axis through (0,0), parallel +Z |
| −X end | `#304/ADVANCED_FACE[10]/` | −X plane X=−12.7 |
| +X end | `#320/ADVANCED_FACE[11]/` | +X plane X=12.7 |

No tests, package build, lint, or formatter were run for this geometry work.

## Demonstration acceptance and source exceptions

The video establishes the process and the nominal identities above, not a released
drawing. The example deliberately adds five **author-selected demonstration**
acceptance bands; it does not adopt the catalogue product's tolerances:

| Requirement | Acceptance, mm | Inch equivalent |
| --- | --- | --- |
| Base width | 22.1742–22.2758 | .875 ± .002 |
| Overall height | 12.6492–12.7508 | .500 ± .002 |
| Both flange thicknesses | 6.2992–6.4008 | .250 ± .002 |
| Stem width | 12.5222–12.6238 | .495 ± .002 |
| Finished length | 25.3492–25.4508 | 1.000 ± .002 |

The centered 3/8-16 right-hand through thread retains its source identity. No
minor-diameter, position-diameter, formal class, six-thread count, numerical
recess/overlap or load-rating acceptance is invented. The frozen STEP's 9.525-mm
major-diameter cylinder is explicitly `representation="thread_envelope"`; it is
neither the 7.9375-mm tap drill nor an exact helical solid. Manual tapping carries
a bounded unmodeled thread region, not fabricated helical-kernel proof.

The approved timing is **four final inspections only**, after each nut's
cutting, deburring, bottom-thread staking, blackening, rinsing, drying and oiling.
There is no mandatory S1 batch checkpoint or intermediate inspection result.
The earlier shared-bar plan is superseded by this explicit timing change; it is
not retained as hidden acceptance credit.

**F1a–F1d:10** each produces one separate, initially unfilled overall result for
its own nut. Using the same qualified calipers, check every numeric band above:
base width, overall height, **both** bottom-to-shelf flange thicknesses, stem
width and finished length. Both flange readings must satisfy their common
band; one result does not mean only one flange is measured.
Then `actual_slot_fit` requires free hand sliding without objectionable
rocking, both shelves bearing without bottoming/wedging, and the pulled-up top
below the table. `stud_retention` requires intended-stud entry by hand, bottom
deformation preventing exit/table contact, and no nut rotation or pass-through
in the intended slot. Manual fit does **not** replace any numeric size check.
The same checkpoint includes uniform black/oiled finish, no loose residue and
unobstructed fit/threads; finish remains an explicit visual instruction, not a
third typed relationship, invented gauge or separate result.

The Q3/Q4/E1/D1/B1 inspection operations and their unknown diameter/position and
missing-functional-requirement placeholders are superseded by these explicit
contracts, not hidden at a presentation level. No micrometer, formal working
thread gauge, locator gauge or thread-axis worksheet is required by this design.
The DTI remains for vise alignment only.

The actual-slot comparator's note discloses **example**, not measured PM-25 table,
dimensions: throat 12.7, undercut 22.86, total depth 13.97 and lip depth 6.985 mm;
the resulting undercut height is 6.985 mm. They are not a numeric fit certificate.
The comparator is the actual intended slot; the hardware comparator is the
intended 3/8-16 right-hand stud/nut, not an M10 × 1.5 near-fit.

### Demonstration measurement convention

Installed/commissioning measured records use the repository's exact disclosure:

```toml
measured = { status = "measured", by = "example value (realistic, not a shop measurement)", date = "2026-10-11", instrument = "example fixture (no physical measurement)" }
```

This exercises the same checker branch as a measured shop input without claiming
a shop observation. The checker must not interpret the attribution prose as a
trust override. Bare `Number`/`Vector` plan and capability fields retain their legal
shape with adjacent example-value attribution/citations; no fabricated wrapper is
introduced. Catalogue nominals remain catalogue facts, while installed projection,
body/kerf, holder/fixture dimensions and effective machine limits have separate
fact-local example records. All added equipment is an adopted example selection,
not identified as equipment in the video.

The current inventory schema represents the tap-wrench 5–12-mm capacity band as
`range_mm=[5,12]`, not the scalar `capacity_mm`. The follower uses the engine's
exact selected tool identity `fits="tools.taper-tap"` rather than an unsupported
designation list. Its note preserves the 3/8-16 right-hand identity. It guides;
it does not grip or drive the tap, and no follower-based tool projection, powered
tap RPM/feed or automatic class certification is supplied.

## Demonstration stock and registration

The adopted example annealed 1018/HB120 flat bar is 1 × .625 × 5 inch: model origin
[0,-12.7,-1.5875] mm, length axis +X, section axis +Y. The .001-inch-per-inch
starting-end squareness is an explicitly disclosed example raw-stock input, not a
completed preparation result or `stock.prepared` claim. B0's .889-mm kerf is
centered at B0 setup X101.4095 (batch/model X114.1095), 4.4925 inch from the starting face. It leaves
113.665 mm (4.475 inch) of batch bar and 12.446 mm (.490 inch) of scrap.
Nut4's raw starting end is later removed by its .635-mm E1d cleanup.

B0's pro/hobby retained-length/kerf instruction combines the native numeric
target with operation20's starting-end, scrap-side and stopped-retrieval wording;
the authored note does not repeat the target's retained length/kerf numbers.
Pedantic does not print that native target; its authored note retains the
113.665-mm batch length and 12.446-mm scrap length.
The far kerf edge is `4.4925 + .035/2 = 4.510 inch` (114.554 mm).
The pre-made scrap pedestal starts at setup X103, or `103 + 12.7 = 115.7 mm`
from the original starting end: 4.555118… inch, printed as about4.56 inch.
Thus its nearest occupied hardware remains 1.146 mm beyond that far edge;
the simplified placement prose does not move the support.

Q1–Q4 face only the four long faces. The 113.665-mm prepared section is exactly
four 26.035-mm blanks plus three 3.175-mm kerfs. In the upright end-up frame,
bottom is Z0:

| Physical cut | Kerf center Z, mm | Upper retained output Z | Lower retained output Z |
| --- | ---: | --- | --- |
| C1a:20 | 86.0425 | nut1_blank: 87.630–113.665 | bar_a: 0–84.455 |
| C1b:10 | 56.8325 | nut2_blank: 58.420–84.455 | bar_b: 0–55.245 |
| C2:10 | 27.6225 | nut3_blank: 29.210–55.245 | nut4_blank: 0–26.035 |

The unchanged canonical STEP spans X−12.7..+12.7, **not X0..25.4**. Correct
finished-target translations are [100.33,0,0], [71.12,0,0], [41.91,0,0], and
[13.335,0,0] mm; nut4 alone is rotated Rz180°. This preserves each retained #304
saw end and leaves .635 mm at its free #320 end. Output registration uses inverse
translations for nut1–nut3; nut4's rotated transform is self-inverse.
Q2 therefore claims #130 for nut1–nut3 but #57 for nut4; Q3 is the mirror.
No sibling borrows an untransformed face claim.

The named manifest surface `retained-saw-end` binds **only** canonical face
`#304/ADVANCED_FACE[10]/` (model −X plane X−12.7). E1/D1 `hold.stop_face`
references use that feature identity, not a raw STEP-face string, the ambiguous
two-ended `end-length` feature, or a generic `stock_end`. This is a locating
designation of existing frozen geometry with no additional size/inspection
requirement; top-up-reversed places it at setup X+12.7 against the rod's zero end.

The physical route is **29 setups / 64 operations / 14 presentation families**:
B0, Q1–Q4, S1, C1a, C1b, C2, then E1a–d, D1a–d, B1a–d, B2a–d, F1a–d.
Each downstream setup names one explicit incoming retained output/setup. E1,
D1, B1, B2 and F1 groups share presentation instructions only; their physical
operation identities, findings and results remain separate. The canonical STEP
bytes, SHA-256 and geometry export observations above are unchanged.

### Facing entry allowance

Q1–Q4 operation10 uses the existing `contour.sweep_bounds` and `sweep_frame`
to extend the planned cut area 2.54 mm (.100 inch) toward the actual raster
entry. This is an **AUTHOR'S CHOICE illustrative process allowance**, not a
video dimension, shop measurement, uncertainty bound or safety qualification.
The finished removal bounds, face depths, stepover and finished geometry are
unchanged. The cutter centre remains one cutter radius beyond the planned cut
area boundary; this radius is not the physical gap from the stock.

The source contours explicitly use `sweep_frame = "model"`: sweep source frames
resolve from the geometry manifest, not the plan-owned setup-frame table.
The bounds are transformed from the local audit extents below into that model
frame; they are not setup-frame numbers merely relabelled as model coordinates.
For the selected .750-inch cutter, the intended directed centre paths are:

| Setup | Existing setup frame | Setup-frame X projection, mm | Centre X start → end, inch |
| --- | --- | --- | --- |
| Q1 | batch-bottom-up | −15.24..100.965 | −.975 → 4.350 |
| Q2 | side-one-up | −103.505..12.7 | −4.450 → +.875 |
| Q3 | side-two-up | −15.24..100.965 | −.975 → 4.350 |
| Q4 | top-up | −15.24..100.965 | −.975 → 4.350 |

Q2 enters at the B0-sawn far end, not the accessible right datum end;
+.875 inch is its exit. Q1/Q3/Q4 enter at the original starting end.
The existing .001-inch-per-inch starting-end squareness corresponds to about
.0012 inch across the 1 × .625-inch section diagonal. The existing .0001-inch
DRO resolution is an illustrative capability, not positioning accuracy.
Those inputs provide scale for the chosen allowance but do not establish a
complete error budget. B0 length and face error, finder error, burrs, backlash
and manual positioning error remain undeclared; in particular Q2 has no
declared B0 error bound. No measurement is invented to justify .100 inch.

The actual incoming stock, transformed into each setup frame, must still be
used for native entry classification and pre/post geometry checks. Nominal
outside-stock entry does not certify real-world clearance or machining safety.
The prominent example-only warning and unresolved source boundaries remain.

## Finite saw and native pickup design

The saw, arbor, vises, supports and capture are explicit demonstration inputs, not
a universal sawing recipe or dynamic clamp-capacity certification. The 2-inch
36-tooth saw has .125-inch kerf, .120-inch body, 48-mm tooth root, measured-example
bore [12.700,12.710] mm and zero kerf offset. Installed body-midplane-to-gauge
projection is 45 mm; the arbor's complete holder/stem/flange/pilot/lower-retainer
envelope is separately recorded in inventory. CW teeth viewed from above and a
lower right-hand retainer are the selected placement-specific cutting/tightening
combination.

The independent capture is a pre-made, table-anchored assembly, not a hand-held
catch and not C2's balancing blank. Its widened head, both pad contacts, screw
housing/screw/handle envelopes, collar hardware, anchored post/base and M8 bolt
heads are occupied geometry. Each head is posed at its actual cut center; pads
contact the upper child's flange 12–24 mm above it. M6 pad/collar targets are
8 N·m and M8 base targets 18 N·m: instructions, not verified holding force.
No unused 1000-N rating remains.

The identity-placed post's occupied XY rectangle is X−20..20/Y40..50 mm;
the base is X−30..30/Y30..60 mm, from their inventory box origins plus sizes.
These existing-fixture footprints are placement context, not DRO targets,
fabrication instructions or a strength rating. They are not the whole head's
footprint: the head's separate arms, pads, screws and handle remain individually
modeled occupied solids, with the moving handle extending to X44 mm.

The original ledger's unbored collar and screw envelopes intersected the
independent rectangular post. The adopted pre-made mechanism now has a real
slotted-post through-clamp: a guided U-collar, bored front boss, removable rear
strap and rear M6 nut. This is a disclosed **illustrative fixture correction**,
not hardware identified in the video. The post/base, pad/arm geometry, moving
pad, base-bolt envelopes and all three placement poses are unchanged.

Head-local dimensions below are millimetres:

| Element | Adopted geometry |
| --- | --- |
| Collar post window | Box min [−20.25,40,29], size [40.5,11,8], subtracting only `rear-rail-collar`; .25-mm clearance on each X side of the 40-mm-wide post. |
| Front screw boss | Box min [−6,20,27], size [12,20,12], joined to the rail; the extra height leaves material around the screw bore. |
| Front screw bore | Ø6.5, +Y from [0,19,33], length22; subtracts only the rail and boss. |
| Rear clamping strap | Box min [−28,50,27], size [56,4,12], bearing on the post's rear Y50 plane and closing across the collar's side ends. |
| Rear strap bore | Ø6.5, +Y from [0,49,33], length6; subtracts only the strap. |
| Collar M6 screw | Original axis X0/Z33, Ø6, now Y20..60; the original Y20..56 occupied envelope is retained and extended, not hidden. |
| Rear M6 nut | Ø12 ×5 envelope at Y54..59; screw projects1 mm beyond it. Its Ø6 nominal thread-envelope void cuts the nut only, not the screw, and is not a helical-thread or thread-fit proof. |

The fixed post has a Ø6.5-wide vertical obround slot through its Y40..50
thickness. In post-local coordinates its straight void is min
[−3.25,39,60.6225], size [6.5,12,58.42], joined to Ø6.5 end voids centered
at X0/Z60.6225 and X0/Z119.0425 along +Y from Y39 for12 mm.
These subtract **only the post**. The rounded slot spans Z57.3725..122.2925,
covering all three actual screw centers `zc+33`:
60.6225/89.8325/119.0425, with .25-mm radial screw clearance.
Post material remains connected beside, above and below the slot.

The nominal clamping stack has screw-head/boss bearing at Y20,
collar/post bearing at Y40, post/strap bearing at Y50 and strap/nut
bearing at Y54. The bolt closes that stack through the real bores and slot;
the connected arms carry the two flange pads. Targeted voids do not subtract
another fixture owner's material or erase occupied hardware. All added
dimensions carry the same exact example-value measurement marker as the other
installed fixture facts. None is a recovered shop measurement or a holding-force
rating.

The anchored post and connected clamping hardware are **authored fixture
facts**, not a native anchorage certification. The finite-saw model checks
occupied geometry, its collisions and the fixed/moving pad contacts with the
upper child. Those checks do not establish an assembly load path, anchor-bolt
strength, slip resistance or dynamic capture capacity. The physical connection
must be present in the adopted fixture; neither the two pad contacts nor the
8/18-N·m tightening instructions prove its strength.

All custom-solid coordinates are fixture-local and all placed-support/capture
poses are setup-local millimetres, applied once. Upright table is Z−75;
the upright parallel/support plane is Z0. The setting-post origin is
[−119.38,0,−75], with local stem Z0..83.16 and a 2×2×2-mm boss above it:
`−75 + 83.16 + 2 = 10.16 mm = +.400 inch` above that support plane.
The lower blade body touches at [−119.38,0,10.16] with arbor XY[−139.7,0]
through .0508-mm paper:

`cutting-midplane Z = 10.16 + .0508 + 3.048/2 = 11.7348 mm = +.462 inch`.

Use actual body thickness, not kerf or radius. A +.250-inch check reads +.712,
not mirrored +.212. Each separate saw installation has its own fresh body-side
record; an earlier setting cannot silently transfer.

Before saw installation, find front Y0 first at a physical point by eye within
±.300 inch of its center, not an unset X readout; the native point uses X0.
Then find left stem X−6.2865 at Y10.541. Finder lowest-tip Z is
111.125/81.915/52.705 mm for C1a/C1b/C2, .100 inch below each current top.
The .100-inch lateral approach and .500-inch above-stock retract clearance
include descent, lateral contact, vertical withdrawal and signed check jog.
E1's accessible retained-end pickup similarly uses Y−.200/Z−.100, above the
stop, rather than touching the rough free end or through the stop.

Every saw cycle starts at calibration [−139.7,0,11.7348]. With spindle stopped,
move one axis at a time: Z130.175 → Y−10.541 → X−53.34 → Zcut → X−37.1475.
The sole cutting segment feeds +X to +37.1475 at 160 RPM / 58.5216 mm/min
with flood. Stop fully with capture still clamped. Withdraw Y−60.325, raise
Z130.175, then return X−139.7 → Y0 → Z11.7348. Both children and capture
remain obstacles until this complete stopped return; only then release/retrieve,
adjust capture and perform the next setup's pickups/setting. Lowering first and
crossing at the next height is not an allowed clear-return shortcut.

C2 borrows the already-produced `stock_out.nut1_blank` at origin [62.7,0,11.1125],
local x=setup+X, local z=setup+Y (local y=setup−Z). It is a temporary
obstacle/support, not duplicated/consumed material or a substitute upper hold.
Paper .0508 mm is at the cutting-piece/moving-jaw contact, not on this balancer.
Return nut1 before E1a.

The ledger's analytical expectations are retainer/jaw clearance 1.0985 mm,
flange/stock lateral gap 1.016 mm, descent pad clearance 2.444 mm and established
engagement about 41.6864° / mean 4.1686 teeth / guaranteed 4. They are design
expectations, **not native results exercised by this authoring change**; entry
and exit transitions are separate. Full finite motion, mounting, capture,
material/target protection and native pickups must supply actual checker proof.

C2's compact envelope labels use approximate inches, not DRO targets:
the 101.6-mm jaws centred at X34.8 occupy X−16..85.6 mm
(−.629921… ..3.370079… inch, displayed −.63..3.37).
The nut1 balancing blank at X62.7 occupies X50..76.035 mm
(1.968504… ..2.993504… inch, displayed about1.97..2.99); its top remains
Z22.225 mm/.875 inch. Capture pad contact stays 12–24 mm above the cut
(formerly displayed approximately .4724–.9449 inch), not a DRO setting.
The exact modeled retainer/jaw gap remains `1.0985/25.4 = .04325 inch`;
the authored compact statement displays **.043 inch (rounded down)**.
Neither approximation enlarges this clearance or changes occupied geometry.

C2 selects the complete canonical picture group `["setup"]`. The current
native scene places `closest_cut` in this main group, together with the full
fixture context and its continuations; no `holding_detail:1` exists in that
scene. This is one selected C2 setup figure, not a fixed physical band count.
The annotation distinguishes a verified stopped body-side setting contact from
ordinary pre-cut/clear approach and cutting clearance; a pre-cut move alone is
not evidence that the spindle is stopped. The canonical native result is
.0508 mm at the blade-body/setting-boss paper gap, distinct from the cut-stage
retainer/jaw clearance 1.0985 mm (.04325 inch). Do not substitute the cut-stage
value for the full-cycle minimum or claim that selecting a picture is itself
a clearance proof.

## Cutting-data sources

The local offline reference root is
`C:/src/harmonic-analyzer/references/machinerys-handbook/corpus/`.
Do not bundle the copyrighted corpus or fetch it during checks.

| Fact | Source and selected use |
| --- | --- |
| 1018/HSS 110 sfm at 100–125 HB | `pages/1366.md`, Table11, printed1045; HB120 is a disclosed example material selection. |
| ¾-inch HSS .003 in/tooth; ½-inch .001 in/tooth at cited .250-inch DOC | `1375.md`, Table15a, printed1054; selected 500/750 RPM both give 98.175 sfm. |
| HSS 1018 drilling 100 sfm; under⅛-inch .001–.003 in/rev, ¼–½-inch .004–.010 in/rev | `1381.md`/`1382.md`, printed1060/1061; adopted spot/drill rows are within these feed bands. |
| 3/8-16 commercial tap drill 5/16 inch | `2254.md`, Table3, printed1933; not recovered from the video. |
| 5/16 jobber LOC3-3/16/OAL4-1/2 inch; #3 centre drill ¼-inch body, 7/64-inch pilot/length, OAL2 inch | `1182.md`, printed861; `1194.md`, Table6, printed873. |
| Adopted PM-25MV-BD R8/1HP/speed ranges and nominal travel/headroom | [Manufacturer manual §2, UCSB mirror](https://microfluidics.cnsi.ucsb.edu/wiki/lib/exe/fetch.php?media=tools:precisionsmillingmachine:pm-25mv_manual.pdf); effective envelope limits are separate measured-example facts, not video mill identification. |
| 2-inch × .125-inch × ½-inch bore, 36T HSS saw; 80–100 sfm, .0004–.0018 in/tooth, flood guidance | [MariTool301-2.0-.50-.125-36T](https://www.maritool.com/product_info.php?products_id=25574); body, kerf and installation dimensions are separate example facts. |
| .375-inch body/.200-inch finder contact; generic 750–1500 RPM guidance | [Starrett827A](https://www.starrett.com/products/precision-shop-tools/edge-and-center-finders/827A), [Travers finder guidance](https://solutions.travers.com/how-to-use-a-.200-edge-finder-travers-tool-co); adopted 1000 RPM is not a Starrett speed certificate. |
| Bi-metal 1008/1018 base 270 ft/min; no fluid −30–50% | [LENOX Guide to Band Sawing](https://www.sawcalc.com/images/lenox-guide-to-band-sawing.pdf), printed p. 21: 4-in-wide annealed material, bi-metal blade and flood sawing fluid are the base conditions; bi-metal construction is defined in the glossary, printed p. 32. |
| Conditional corroboration of approximately100-sfm HSS practice | [Practical Machinist1018 discussion](https://www.practicalmachinist.com/forum/threads/1018-speeds-feed-and-removal-amount.120956/); not controlling numerical authority. |

The face/profile/spot/drill/saw rows produce respectively 152.4, 76.2, 30.48,
182.88 and 58.5216 mm/min at their authored 500/750/1200/1200/160 RPM.
Mill feed is derived, not overridden by operation feed fields. The nonspindle
bandsaw selects **135 sfm = 270 × 0.50** from the LENOX row above:
50% no-fluid reduction, with no small-section speed increase. The example adopts
annealed 1018 and a bi-metal blade with an HSS cutting edge electron-beam welded
to a spring-steel back; `material="HSS"` denotes the cutting edge. Neither
condition nor construction is a video observation or actual stock/blade
identification; HB120 remains an independent author-selected example hardness.
The unchanged 100–350-sfm machine capability is illustrative, not a loaded-speed
measurement. The 14 TPI pitch, .889-mm kerf and **25.4-mm/min descent** remain
independently illustrative and physically unqualified by this chart. This is not
a product-specific portable-saw recommendation, whole-cut qualification or
execution approval; the whole operation is not claimed to be conservative.
Only consumed policy floors remain: refixture .0254 mm, thin wall 1 mm,
minimum established saw engagement 3 teeth. No dormant Kc/E, load rating,
lathe-only stickout/near-jaw, filing-to-shape limit or print-precision override
is introduced.

A3 workflow explanations are short paraphrases only: PDF16/printed7 batching and
related surfaces before resetting; PDF18/printed9 true arbor/reference retention;
PDF20/printed11 touch/remove excess/remeasure; PDF24/printed15 indicate the fixed
jaw, tighten/recheck and seat duplicate work on parallels. No A3 part dimensions
or copyrighted page content is transplanted.

## Mandatory finish

The example selects JAX **Iron/Steel/Nickel Blackener**, not an unspecified
formulation. Follow [directions](https://jaxchemical.com/wp-content/uploads/2016/08/Directions-Iron-Steel-and-Nickel-Blackener.pdf)
and the [2024-10-04 SDS](https://jaxchemical.com/wp-content/uploads/2024/10/JAX-Iron-Steel-Nickel-Blackener-SDS.pdf):
degrease, final detergent-clean, use the supplied neat product, rinse, dry and oil.
No universal dwell, bath-temperature or coating-thickness requirement is invented.
Ventilation, splash protection, chemical-compatible gloves and segregated waste
remain core instructions in every detail level. ISO-VG32 oil and 5% water-miscible
semi-synthetic flood fluid are disclosed example product selections, not video
identifications. Optional steel-wool/reblackening work is removed; blackening is
mandatory and checked within each final overall result.

## Demonstration deburr maximum

The mechanically held B0/Q1–Q4/S1/C1a/C1b/C2/E1a–d/D1a–d/B1a–d setups
declare `deburr_mm=0.05` mm as an **author-selected demonstration maximum
incidental edge break**. This keeps the existing required input rather than
waiving its check. The video establishes hand burr removal but supplies no
numerical edge-break dimension; 0.05 mm is not attributed to the video, a
catalogue or a physical measurement.

`features.toml` encodes that same existing limit numerically as
`general_tolerances.edge_break_r=0.05` and `chamfer_max=0.05`, so the sheet can
recognize matching setup limits without interpreting free-text provenance.
Both fields limit incidental removal only; general linear/angular tolerances
stay unknown, and local reference/bearing/thread protection remains in force.

The intended process is light raised-burr removal, not deliberate chamfering:
remove the raised burr, preserve bearing/locating flats and usable entry threads,
and do not make an intentional hole-mouth countersink. The 0.05-mm ceiling is
smaller than the 0.0508-mm half-width of the adopted size bands; it does **not**
enlarge those bands or permit an undersize bearing surface. Original dimensional,
slot-fit and stud-retention acceptance remains unchanged. This is plausible
example process data, not a demonstrated result or a new source drawing limit.
Note-only chemical handling and final-comparison setups do not acquire a
mechanical deburring requirement or extra operation.

## Physical input completion

The first actual native-generation attempt identified missing fact qualification
and contact selectors. The corrective input declarations remain illustrative;
they do not turn the example into a physical measurement or a ready-to-run job.

The existing per-feature `stock_state.entry_z` field explicitly names the
declared material start in each operation's own setup frame:

| Setups | Feature | Entry Z, mm | Recipe basis |
| --- | --- | ---: | --- |
| Q1–Q4 | `base-envelope` | +1.5875 | Current unfinished upper face, with .0625-inch stock to remove before finished-face Z0; use that setup's fresh top-face paper touch. |
| S1 | `shoulders` | 0 | Q4's finished upper face; rough-wall and full-height finishing starts as detailed below. |
| E1a–d | `end-length` | 0 | Finished upper face of the registered retained blank in `top-up-reversed`; use the declared fresh top-face paper touch before full-height end milling. |

These are authored recipe datums, not measured heights or permission to trust
future stock. Actual native entry stock, lift clearance, finite cutter descent
and zero survival remain separate evidence. In particular, a missing air-entry
proof is not resolved by inventing a plunge feed. The declared outside-stock
approaches and end returns must be judged against their actual finite stock
and tool geometry.

Fresh top-face paper touches have explicit selected tool-axis coordinates,
not a native assumption that an unqualified bounding-box center is usable:

| Setup | Selected axis [X,Y], setup mm |
| --- | --- |
| Q1 | [44.1325,0] |
| Q2 | [−44.1325,−7.1425] |
| Q3 | [44.1325,−7.1425] |
| Q4 | [44.1325,0] |
| S1 rougher | [44.1325,0] |
| E1a–d | [0,0] |

Each recipe declares 12.7-mm retract clearance and retains the +6.35-mm signed
check jog. The three selected endmills explicitly qualify a sharp flat end
with the existing `nose_radius_mm=0` field; their existing flute lengths and
shanks now carry the same exact illustrative measurement marker. No dimensions
were changed and no physical tool measurement occurred.

These selected axes lie on the actual intended upper lands. Q2/Q3's upper
land is narrower than the .750-inch cutter and E1's stem is slightly narrower
than the .500-inch cutter, so partial end-face overhang is explicit. Contact
requires a real bounded planar overlap and the **whole occupied tool/holder**
must clear the actual approach/retraction path. A partial support footprint is
not permission for any part of the tool to penetrate stock or fixtures.

S1's after-roughing finisher touch deliberately uses the surviving stem top:
the rough stem is 13.081 mm wide, wider than the 12.7-mm finisher. A rough-floor
touch would need a genuinely off-axis contact lens to avoid the tall stem;
it is no longer this recipe. The named `ToolTouch` uses `z_face="top"`,
`after_op=10`, `before_ops=[20]`, paper .0508 mm and top height0. Its explicit
tool axis is [44.1325,0] mm with 12.7-mm retract clearance, using the staged
ToolTouch pose fields. Native contact-land and whole-tool/holder clearance
must be proved against the **actual stock after roughing10, before finishing20**.
The initial arrival-top witness is not substituted for that later-stage proof.

- Saw X/Y pickups select the **actual arriving stock** with `stock:-x` and
  `stock:-y`, respectively. Their separately authored transverse coordinates and
  lowest tip heights select the exposed stem and front-flange planes; the native
  contact proof must still establish that the selected plane is reached without
  another part of the finder/holder contacting stock or fixtures. No canonical
  face from an arbitrary one of the still-joined members is substituted.
- E1a–d X pickups name `retained-saw-end`, the exact single canonical #304 plane
  on that setup's sole carried member. This is the exposed upper part of the
  retained end, not a contact through the rod stop.
  The end stop now includes explicit occupied rod and mounting solids rather
  than an undrawn nominal diameter/length. The Ø6.35 ×50-mm rod and all eight
  poses remain unchanged: setup X12.7..62.7, Y±3.175, Z−12.7..−6.35.
  Its connected socket/cantilever, targeted rod and M4 screw bores, occupied
  screw shank/head and switchable magnetic foot are pre-made illustrative
  fixture facts, not hardware recovered from the video.
  The foot occupies setup X30..50/Y12..30/Z−7.7..7.3, seating on the adopted
  clean steel fixed-jaw top in both E1 and D1. It does not pass through the
  vise bed; its footprint lies within both actual jaw spans. The Ø6.40 socket
  bore is .025 mm above the rod axis so the rod seats against its lower wall,
  with the screw tip contacting from above. Voids do not erase the occupied
  rod or screw. All added primitives carry the exact example measurement marker.
  Pro instructions require seating the foot flush, switching ON, securing the
  rod screw, gentle locating contact and rechecking after vise tightening.
  The vise, not the stop, carries cutting loads. Native contact/pickup/clearance
  evidence and magnetic holding capacity are not established by these authored
  dimensions.
- S1's linear-table sweep names the retained stem envelope over the **whole raw
  batch length**, model X0..113.665 and Y±6.2865 mm. Offsetting its two long
  walls by the .500-inch cutter radius plus .010-inch rough allowance produces
  rough centre Y±12.8905 mm (±.5075 inch); the finish radius alone produces
  Y±12.6365 mm (±.4975 inch). The connecting returns stand beyond the raw ends:
  rough setup X−19.304/+107.569 and finish X−19.05/+107.315 mm. They do not shorten
  either end or substitute four short per-member paths. Clear-air depth entry
  and end returns remain subject to the real path/fixture checks.
  Both shoulder operations use that explicit guided profile **without**
  `stock_removal_bounds`: material removal belongs to the complete finite
  printed side passes, not to the complement of four separated final targets
  inside a broad clearing box. The stem stays continuous through all future
  kerf and end-trim gaps until the three explicit partition cuts and later end
  cleanups. Rough allowance is .254 mm normal to the stem walls only; the
  shoulder floors still finish at setup Z−6.35, with no invented axial leave.
  This authored path contract does not substitute for native target, allowance,
  stock and cutter/fixture evidence.
  `stock_state.entry_z.shoulders=0` explicitly names Q4's finished upper face
  as this profile's start surface in the S1 frame, using the rougher's declared
  top-face paper touch. It is an authored recipe datum, not an observed or
  future measurement. Rough levels remain Z−3.175/−6.35. The approved finisher
  touch is now on the surviving **stem top at Z0** through .0508-mm paper,
  not the rough shoulder floor: Axis Set +.002 inch, then +.250 jog reads
  +.252. The finish cut still engages the full wall from Z0 to Z−6.35 and does
  not lower the shoulder floors.
  Declaring this start does not certify carried stock or turn an unverified
  descent into proven air travel; native entry/material validation remains
  separate.
- Each D1 setup explicitly declares the centered hole's nominal entry Z0 and
  local section thickness 12.7 mm. These are derived from the adopted nominal
  design, not caliper readings. The 15.621-mm point-inclusive drill depth and
  2.921-mm exit allowance are unchanged; actual prior spot/drill material and
  retained-hole survival still require native evidence.
- B0's example bandsaw cut and B1's stopped hand deburring/staking explicitly
  declare `coolant="none"`. This completes the existing holding declaration;
  it does not waive its coolant/deburring checks or change the source process.

The setting post remains a separately **posed auxiliary support**, at
setup [−119.38,0,−75] mm. Its actual local `boss` top is 85.16 mm, so its
setup top is 10.16 mm. It is not relabelled as a workpiece stop or clamp to
avoid a missing engine placement path. The saw stem/pilot and real flange
envelopes likewise remain physically distinct; a stem touching the body plane
does not become an annular flange.

The inventory correction qualifies the existing physical numbers locally rather
than adding different nominal dimensions to silence the checker:

| Installed demonstration fact | Adopted value | Source boundary |
| --- | --- | --- |
| Mill DRO resolution | .0001 inch | Author-selected example capability, not a physical calibration or video identification. |
| Squaring / shoulder / finishing cutter diameters | 19.05 / 12.7 / 12.7 mm | Existing selected nominal sizes, now locally qualified as example installed dimensions. |
| Finder contact / shank | 5.08 / 9.525 mm | Starrett 827A's .200/.375-inch catalogue identities; installed qualification is illustrative, not a measured shop result. |
| #3 centre-drill pilot diameter / pilot and flute length / shank | 2.778125 / 2.778125 / 6.35 mm | Handbook `pages/1194.md:30–51`, Table 6, printed 873, for the selected pilot/body identity; no recovered video-tool measurement. |
| Centre-drill point angle | 118° | Author-selected illustrative pilot-point geometry, not a catalogue measurement; the 60° centre cone is a different surface. |
| Tap-drill diameter / flute length / shank | 7.9375 / 80.9625 / 7.9375 mm | Selected 5/16-inch tap drill: `pages/2254.md:83–84`, Table 3, printed 1933; jobber lengths `pages/1182.md:26–27`, printed 861. |
| Tap-drill point angle | 118° | Author-selected illustrative drill-point geometry, not observed from the video. |
| Drill-chuck maximum shank | 13 mm = 0.5118110236220472 inch | Existing example .5–13-mm capacity; explicit legal `max_shank_in` supplies the same upper limit, not an enlarged chuck. |

Each qualified measurement record carries the exact repository-required marker:

```toml
measured = { status = "measured", by = "example value (realistic, not a shop measurement)", date = "2026-10-11", instrument = "example fixture (no physical measurement)" }
```

Fields whose schema is a bare scalar, including `resolution_in` and
`max_shank_in`, retain that legal form with the full disclosure beside them.
The marker denotes a realistic fixture value; **no physical measurement or
machine calibration occurred**. Tool projections, effective machine travel and
headroom, jaw/parallel geometry, saw body/bore/root dimensions, arbor positions
and the .500-inch qualified manual-tap lead retain their disclosed values.
No plunge cutting-data row was added: the authored shoulder/end paths descend
outside the stock, and unresolved native geometry is not a reason to invent a
different entry motion.

## Batch datum correction

The registered target poses are canonical-to-**batch model** transforms, not
distances from a setup's local X datum. They remain exactly
[100.33,0,0], [71.12,0,0], [41.91,0,0] and [13.335,0,0] mm, with Rz180 only
for nut4. The unchanged centered canonical STEP therefore occupies these batch
X intervals:

| Target | Batch model X, mm | Its retained blank |
| --- | --- | --- |
| nut1 | 87.630..113.030 | 87.630..113.665 |
| nut2 | 58.420..83.820 | 58.420..84.455 |
| nut3 | 29.210..54.610 | 29.210..55.245 |
| nut4, Rz180 | .635..26.035 | 0..26.035 |

The raw supply now starts at batch X0 and ends at X127. B0 retains
X0..113.665; its kerf spans X113.665..114.554, leaving 12.446 mm of scrap.
This fixes a real draft coordinate inconsistency: the old supply and B0 frame
retained only batch X−12.7..100.965, which intersected nut1's declared target.
The native target-loss refusal was correct; no safety predicate or registered
target is changed to conceal it.

To retain the approved **operator-local** coordinates, only the batch preparation
frame origins move +12.7 mm in batch X:

| Frame | Batch model origin, mm |
| --- | --- |
| B0 `bench-raw` | [12.7,0,0] |
| Q1 `batch-bottom-up` | [12.7,0,0] |
| Q2 `side-one-up` | [12.7,−11.1125,0] |
| Q3 `side-two-up` | [12.7,11.1125,0] |
| Q4/S1 `top-up` | [12.7,0,12.7] |
| C1a/C1b/C2 `end-up` | [0,0,0] |

Axes are unchanged. Q1 gets a distinct batch frame so B1's released-member
`bottom-up` frame stays canonical at [0,0,0]. E1/D1 `top-up-reversed` also stays
canonical after each retained output's declared inverse registration. All three
upright cut heights, B0's 4.475-inch retained length, jaw/support positions and
printed X coordinates remain unchanged. S1's model-frame sweep bounds name
X0..113.665 and retain the same operator-local cutter centers; its explicit
guided profile has no broad material-clearing box. There is still one B0 cut
and exactly three partition cuts.

B0 is the actual bed-seated hold: its raw stock bottom and bed top are setup
Z−1.5875. With no parallels and 25-mm bench jaws, the jaw tops are Z23.4125;
`jaw_above_parallels_mm=25` is their actual elevation above that seat, while
`grip_mm=15.875` is the smaller stock-contact height. The saw remains 20 mm
beyond the jaw end; extra jaw height is not a reason to invent a lower vise.

## B1 flange hold without a false bed seat

The adopted B1 hold is bottom-up **between the jaws**, not flange-on-bed or
stem-on-bed. In the released-member frame the flange spans Z−6.35..0 and the
stem extends down to Z−12.7. Put the exposed bottom face flush with the jaw
tops at Z0; the jaws grip the outer flange side flats through 6.35 mm.
The native jaw-zone height above the lowest stock point is consequently
12.7 mm, not the contact grip of 6.35 mm.

For this disclosed example bench vise's 25-mm-high jaws, the bed/jaw foot is
Z−25, giving 12.3 mm clearance below the stem. No parallels are fitted.
`parallels="none"` declares their absence; it is not evidence that the work
rests on the bed. The clamp instruction requires the outer flange contacts and
under-stem clearance to be rechecked before staking. Reholding for manual mouth
and exterior deburring is retained; the final bottom-thread staking remains
the same physical operation. These are plausible, explicitly adopted fixture
positions, not video-derived measurements or demonstrated holding strength.
