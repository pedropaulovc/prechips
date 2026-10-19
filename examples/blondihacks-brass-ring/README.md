# Blondihacks brass ring

A complete, independently authored worked example from [Blondihacks — Metal Lathe Tutorial 16: Your First Project!](https://www.youtube.com/watch?v=t9NGty1CVII), uploaded 2019-05-19. The video actually machines **360 free-machining brass**, not the steel jewelry shown during its introduction.

This bundle contains an actual native FreeCAD STEP, reproducible generator, geometry-matched face bindings, all five TOML inputs and the complete demonstrated route. It uses no shared shop inventory, policy or cutting-data file. It is **demonstration data, PLANNED/HOLD**, not a measured shop record, released manufacturing drawing, fit certificate, jewelry-material approval or physical acceptance.

## Part and source boundary

| Design target | Video nominal |
| --- | --- |
| Inside diameter | 5/8 inch = 15.875 mm |
| Radial wall | 0.050 inch = 1.27 mm |
| Outside diameter | 0.725 inch = 18.415 mm, calculated/spoken as ID + 2 × wall |
| Axial width | 0.100 inch = 2.54 mm |
| Material | 360 free-machining brass |

All solid dimensions are stated in the actual video ([05:41](https://www.youtube.com/watch?v=t9NGty1CVII&t=341s), [14:40](https://www.youtube.com/watch?v=t9NGty1CVII&t=880s)); none is an invented measurement or an “assumed” replacement dimension. The [source ledger](source-ledger.md) records a real similar-size catalog search. Its approximately 16 mm-ID, 2–2.5 mm-wide adjustable brass jewelry setting is only a scale comparison: the video's own nominals already define the ring, so no unrelated catalog dimension or tolerance is imported.

The STEP is an ideal sharp-edged nominal ring. Unquantified hand-filed/deburred edge breaks are omitted, and the sacrificial bar's partial groove is not misrepresented as a finished-ring feature. This is therefore **not an exact physical replica** of the hand-finished part. Numerical acceptance limits, finish, fit, coaxiality, safe ring release and suitability for wear remain unestablished.

**Editorial material HOLD:** the [Copper Development Association C36000 composition table](https://alloys.copper.org/alloy/C36000) lists **2.5–3.0% lead (Pb)**. The actual 360-brass project must not be treated as lead-free or covered by the video's separate introductory warning about 12L14 steel. That alloy table is not a certificate for this scrap. Confirm actual stock identity/composition and applicable child-jewelry, wear and gift requirements before use; neither adult-wear nor child-use acceptance is implied.

## Full route

### L1 — one three-jaw chucking

1. Select the existing nominal 1-inch brass scrap; confirm actual stock/grip/stickout and tool/jaw clearance. For smaller purchased stock, source 05:55–06:04 recommends probably at least 0.050 inch above the 0.725-inch OD for cleanup, not a measured allowance. There is no source saw phase to invent.
2. Face the exposed end with the flat-top turning/facing tool, carriage locked, about 450 rpm and the demonstrated 0.020-inch axial pass.
3. Square the four-way toolpost against that face, check safe rear turning travel with the machinist scale and make the witness mark.
4. Touch OD and take the first cleanup pass, 0.020-inch **diameter** reduction on the source's direct-read handwheel dial. The visible cross-slide graduation is **0.002 inch of diameter reduction per tick**, not radial travel or millimetres. Set its ring to the closest whole number as shown; the actual starting number, calibration, backlash procedure and sign checks remain unknown. No electronic DRO Axis Set is introduced.
5. Clean the old scrap step, stop and measure. Retain both distinct 0.100-inch-diameter rough passes, about 380–390 rpm, followed by a separate stopped remeasurement.
6. Finish the OD to nominal 0.725 inch, source a little over 500 rpm; withdraw radially rather than dragging back across the finish.
7. Use the machinist scale to set the ring-side edge of the **wide traditional ground parting tool**, not a narrow blade, 0.100 inch behind the front face; lock the carriage. There is no source paper/top retouch after finishing. Partial groove at about 140 rpm: the source specifies 0.100 inch of diameter reduction and a little more depth than the 0.050-inch radial wall. Exactly 0.725 − 0.100 = 0.625 inch leaves zero nominal margin to the final 5/8-inch drill. Verify an actual groove root below the actual drill-cut diameter with an approved positive release margin; additional depth, root and required margin remain unknown. Do not part off yet.
8. With the bar still chucked, lightly file the front and rear outer edges; only the rear edge is reached through the wide groove. Source uses a fine-cut handled mill file at about 200 rpm; size and safe rotating-filing envelope are not certified. No bore is claimed before drilling creates it.
9. Fit the tailstock Jacobs-type drill chuck and spot using the #2 centre drill, oil, source approximately 800–900 rpm.
10. Drill the explicit sequence **1/4 → 5/16 → 7/16 → 1/2 → 5/8 inch**. The 7/16 and 1/2 stages are verified by on-screen overlays that captions omit. No 3/8 or 9/16 drill is invented. Source gives 400 rpm for the first two sizes and about 150 rpm for the final 5/8; montage-stage speeds remain unknown.
11. The final drill intersects the pre-groove and frees the ring onto the drill. This is the actual separation method, not a hidden final part-off or saw cut. Stop/isolate before recovery; safe breakthrough/retention requires an approved procedure.

### H1 — hand finishing

12. On the wooden bench, retain the small ring and manually twist the source conical deburring tool on both sharp inside edges. The source holds the ring in fingers; no bench vise, mandrel or qualified holding capacity is fabricated.
13. An explicitly labeled editorial final-record inspection uses only the source-visible dial caliper, plus visual edge/through-hole review. Record nominal comparisons without claiming acceptance against nonexistent tolerance bands. Coaxiality method/limit and numerical measurement uncertainty remain unknown.

One ring is demonstrated. The source invites making more; any repeat means the **whole route**, with a fresh actual grip/clearance and release review for each ring, not an unverified automatic feed or invented batch count.

## Independent video-only shop

The inventory contains only genuinely used source equipment: PM-1022V lathe, three-jaw chuck, four-way toolpost, turning tool, wide ground Grizzly parting tool, tailstock drill chuck, #2 centre drill, five stated twist drills, handled fine-cut mill file, dial caliper, machinist scale, cutting oil, wooden bench and conical hand deburring tool.

`present=true` means visible/used in the video, **not present in the reader's shop**. There are no fabricated `measured` records, no `vendor=true` certificates, no imported Pedro-shop capabilities and no extra tools from the video's affiliate list. Published drill diameters and stock diameter are bare source nominals, not installed-tool measurements. The actual machine nameplate is legible at 05:45; no other Precision Matthews model's specifications are substituted.

## Why the traveler stays on HOLD

The source does not establish the real shop's:

- Actual raw bar length/end stations, grip, chuck pose, stickout, permissible clamping load or measured jaw clearance.
- Machine envelope, speed range/power, rotation sign, handwheel sign/reversal checks, calibrated axis pickup or tailstock alignment.
- Tool material, geometry, shank, point angles/lengths, reach, holder body/grip or installed projections; drill nominal diameter is not chuck/shank capacity.
- Approved numeric feeds, cut forces, thin-wall floor, near-jaw allowance, refixture budget or lathe-filing procedure.
- Groove width/root and final-drill point travel that establish full-diameter breakthrough. At 20:12–20:28 the source discusses a **rough caliper figure of about 0.300 inch**, but the measured span and actual drill-point length are not established. The following approximate tip-travel instruction is nominally **0.300 inch = 7.62 mm**. A metric quill scale is visible at 20:40–20:44; which scale column she counted and the actual travel are unverified. This is not an approved machine setting.
- Safe release/retention of the loose ring onto a drill, mechanical bench retention or material/edge suitability for wear.
- Final dimensional/geometry limits, inspection uncertainty, coaxiality inspection method or physical results.

These remain literal `"unknown"` where the schema represents them, with explicit preloading and operation HOLD instructions. The local cutting-data file does not convert demonstration RPM into a fabricated handbook table. Unknown inputs are not a pass, and an approved procedure or measurement must not be inferred from generated sheets.

Editorial additions are explicitly identified: no gloves near rotating machinery (a deliberate departure from the video's gloved lathe work), stop/isolate for measurements and recovery, require approved filing/release/retention procedures, account for the actual brass alloy's lead content, and record final measurements. They are not falsely attributed to source footage or a measured first article.

## Files and use

- `build_part.py`, `brass-ring.STEP`, `part-reference.svg`: reproducible native nominal geometry and clearly labeled supplemental finished-part illustration.
- `features.toml`, `plan.toml`, `inventory.toml`, `shop-policy.toml`, `cutting-data.toml`: strict offline bundle inputs.
- [Geometry provenance](geometry-provenance.md): exact nominals, representation limits, native result, SHA-256 and all four STEP face identities.
- [Source ledger](source-ledger.md): timestamped complete route, visual verification, actual-used equipment and catalog comparison.

After native FreeCAD discovery is configured, generate printable HTML and its report from the repository root:

```text
uv run prechips traveler examples/blondihacks-brass-ring/plan.toml --out out/blondihacks-brass-ring
```

Set `FREECAD_CMD` to the native FreeCAD command executable if discovery cannot find it and use the shared `PRECHIPS_KERNEL_CACHE`. The generator's geometry evidence files go to `~/.cache/prechips/video-t9NGty1CVII`, never the repository root. The nominal SVG is **not** raw stock, a workholding image or proof of clearance. The traveler/report must be generated from operative inputs, not loaded from expected outputs.

The complete MP4, English captions, metadata, cleaned timestamped transcript, drill contact sheet and web comparison excerpt remain in the external source cache; video bytes are not committed. No physical rehearsal, shop readiness or jewelry suitability has been established.

## Observed focused generation

On 2026-10-18, native FreeCAD 1.1.4 emitted `RING_JSON` with one valid reimported solid and four geometry-matched faces; the corrected generator matched the frozen STEP digest. Native SVG stroke scale was corrected without changing geometry.

The strict input loader and actual traveler CLI were exercised against the complete external staging bundle, using the installed `freecadcmd.exe` and shared kernel cache:

```text
uv run prechips traveler C:/Users/pedro/.cache/prechips/video-t9NGty1CVII/bundle-staging/blondihacks-brass-ring/plan.toml --out C:/Users/pedro/.cache/prechips/video-t9NGty1CVII/observed-traveler
```

The historical staging consumer exit was **4**, as required by the remaining truthful unknowns. That report records `verification="planned"`; it has **0 errors, 76 unknowns, 1 warning, 23 passes and 107 not-applicable findings**. Imported-face coverage passes. `report.json` and printable `traveler.html` were generated in that external output directory. These counts describe that invocation, not a rerun of later annotations.

At that invocation, the lone warning was `finish_route`: the rule treated the as-turned/hand-deburred surface finish as requiring a coating operation. No coating is shown, so none was invented. The bundle now explicitly declares `material.finish_kind = "surface"` and describes the uncoated source route. A surface-finish declaration is neither coating coverage nor inspection credit. The staging counts and hash below predate the finish-kind, handwheel and source-review corrections; they do not claim a rerun or establish physical readiness.

Report hash at that invocation: `dab90cfd840235c6f9378b9fb2f8fbe27f2a5a466e1662494081e397f0df1984`. This is observed staging-run evidence, not a promise that path-sensitive report hashes will remain unchanged after publication or later engine revisions. The parent integration owner freezes expected outputs after the shared source is final.

No suite, package build, lint or formatter was run for this bundle. No physical paper rehearsal or live machining acceptance was performed.

An initial focused read-only review of the seven authoring/provenance files, complete cached transcript and drill contact sheet found no blockers within its scope. The later cross-family source review identified authoring/readout issues; the owned-input corrections remove the paper retouch, explicitly declare inch handwheels, state the groove-release relation and actual 360-brass lead HOLD, narrow edge-deburring bindings, document the visual through check and clarify the ambiguous rough depth figure. Neither review independently reran native/CLI checks or established physical acceptance.
