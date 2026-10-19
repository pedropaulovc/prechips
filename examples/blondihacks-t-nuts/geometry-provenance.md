# T-nut geometry provenance

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

## Reproduction and observed export

Run with FreeCAD, not the project Python environment:

```text
freecadcmd.exe examples/blondihacks-t-nuts/build_part.py
```

The script checks the constructed solid, exports `t-nut.STEP`, normalizes only
the non-geometric `FILE_NAME` header (fixed epoch timestamp, no absolute path),
reimports it and emits a `TNUT_JSON` summary. LF bytes are used for its digest.
Byte identity across FreeCAD/OpenCascade versions is not promised.

Observed with FreeCAD 1.1.4 / build 20260928: valid reimported B-rep, one solid,
11 faces, bounds `(-12.7, -11.1125, 0)` to `(12.7, 11.1125, 12.7)` mm,
volume **4707.621531549312 mm³**.

STEP SHA-256:
`456cdbe656f84b5b3236b8878c820f1e64a21944a61bdc6165fd39fe2fe5336e`.

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
