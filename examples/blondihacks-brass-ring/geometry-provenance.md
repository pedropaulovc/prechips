# Brass-ring geometry provenance

Source: Blondihacks, [Metal Lathe Tutorial 16: Your First Project!](https://www.youtube.com/watch?v=t9NGty1CVII), uploaded 2019-05-19. See [chronological source ledger](source-ledger.md) for media inspection and equipment evidence.

This is a **source-nominal demonstration design**, not a physical measurement or an exact model of the hand-deburred ring. It is not a commercial ring replica, released drawing or fit certificate.

## Design dimensions

| Parameter | Nominal | Source |
| --- | --- | --- |
| Inside diameter | 15.875 mm = 0.625 inch = 5/8 inch | [05:41–05:49](https://www.youtube.com/watch?v=t9NGty1CVII&t=341s), final drill [22:41](https://www.youtube.com/watch?v=t9NGty1CVII&t=1361s). |
| Radial wall | 1.27 mm = 0.050 inch | [05:41–05:47](https://www.youtube.com/watch?v=t9NGty1CVII&t=341s). This is radial wall, not axial width. |
| Outside diameter | 18.415 mm = 0.725 inch | Same spoken calculation: 0.625 + 2 × 0.050 = 0.725 inch, [05:41–05:52](https://www.youtube.com/watch?v=t9NGty1CVII&t=341s). |
| Axial width | 2.54 mm = 0.100 inch | Machinist-scale setting [14:40–14:48](https://www.youtube.com/watch?v=t9NGty1CVII&t=880s). |
| Material | 360 free-machining brass | Scrap identification [04:59](https://www.youtube.com/watch?v=t9NGty1CVII&t=299s); no certificate, composition analysis or jewelry-compliance record. |

Conversion uses exactly 25.4 mm/inch. No acceptance bands, coaxiality limit, fit allowance, surface-roughness number or chamfer/radius is fabricated. Source OD readings 0.944 and 0.743 inch are observations of intermediate states of that particular bar; they are not final model dimensions or measurements of the reader's work.

The [similar-size catalog search](source-ledger.md#similar-size-online-research) found real approximately 16 mm-ID, 2–2.5 mm-wide brass jewelry settings. Those are distinct adjustable/plated products and are not a source for this ring's geometry, tolerances or material certification. The video already gives all nominal dimensions needed for the ideal ring.

## Representation and coordinate choices

The native shape is the difference of two coaxial cylinders, one valid solid. Model +Z points toward the exposed end, front annulus at Z = 0 and rear annulus at Z = −2.54 mm. X/Y form a right-handed nominal frame on the spindle axis. This frame is explicitly **AUTHOR'S CHOICE** and does not establish the actual machine jaw-front station, stock end, chuck runout, tool height or handwheel pickup.

The video slightly chamfers both outer edges using a file and then hand-deburrs the inner edges, but publishes no dimensions for those changes. The STEP deliberately has ideal sharp edges; its volume is the nominal sharp-edged solid's volume, not a measured finished-part volume. The partial separation groove is in the retained/sacrificial bar, behind the ring; it is not a finished-part circumferential groove and is not added to the finished STEP. Groove width/root, tool width, raw stock length and final drill-point geometry remain unknown.

The source's nominal groove arithmetic is 0.725 − 0.100 = 0.625 inch, equal to the final drill nominal. Its additional “little more” depth is therefore material to release, not an optional invented tolerance. The plan explicitly requires an actual groove root below the actual drill-cut diameter with an approved positive margin, while leaving extra depth, root and acceptable margin unknown. The rough 0.300-inch caliper figure discussed during drilling does not establish the exact measured span or point length; 0.300 inch = 7.62 mm is only a nominal conversion, not verified quill travel.

The final drill frees the ring onto the drill. Neither this B-rep nor a static clearance check proves safe retention, dynamic behavior, drilling/grabbing resistance, finish, edge safety, wearability or physical acceptance.

## Reproduction

Run the adjacent `build_part.py` using native FreeCAD, not the project Python:

```text
freecadcmd.exe examples/blondihacks-brass-ring/build_part.py
```

The generator privately exports, normalizes only the nongeometric `FILE_NAME` header to fixed metadata, and preserves frozen STEP bytes if a new export differs. It validates the constructed solid and reimported STEP, emits a `RING_JSON` success summary and generates the supplemental SVG with native TechDraw hidden-line projection. The native SVG's sibling groups are explicitly wrapped; they are not assumed to be a single XML document root. FreeCAD's script process exit alone is not sufficient proof of successful generation: require the summary and files, without Python exception output.

Observed with FreeCAD 1.1.4: one valid nonempty solid, four faces, bounding box `(-9.2075, -9.2075, -2.54)` to `(9.2075, 9.2075, 0)` mm, volume **173.74999458253205 mm³**. A final native run matched the frozen reference bytes. Byte identity across different FreeCAD/OpenCascade releases is not promised.

STEP SHA-256:

```text
5e1fc38ebade5d85d47ab662b184b09d688fb75962f169483059d47526796ed7
```

## Exact face identities

STEP entity surfaces and placements were matched to native face geometry; these are not guessed import-order identities. All references bind to the exact digest above.

| Functional face | STEP reference | Geometric match |
| --- | --- | --- |
| Outside cylinder | `#17/ADVANCED_FACE[1]/` | Coaxial cylinder radius 9.2075 mm, Z −2.54 to 0. |
| Front annulus | `#50/ADVANCED_FACE[2]/` | Plane Z 0, outward normal +Z, inner/outer radii 7.9375/9.2075 mm. |
| Rear annulus | `#70/ADVANCED_FACE[3]/` | Plane Z −2.54, outward normal −Z, same radii. |
| Bore cylinder | `#90/ADVANCED_FACE[4]/` | Coaxial cylinder radius 7.9375 mm, Z −2.54 to 0. |

The [part reference](part-reference.svg) is explicitly labeled **Nominal finished design — not stock, holding or fit approval**. It depicts only the nominal finished B-rep, not an incoming stock state, toolpath, fixture or setup rendering.
