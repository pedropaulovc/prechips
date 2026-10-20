# Blondihacks T-nuts — catalog-based example design

**EXAMPLE ONLY — NOT FOR EXECUTION IN A REAL ENVIRONMENT**

A standalone, **four-piece 1018-steel T-nut job** using the process demonstrated in
Blondihacks' [*Let's Make T-Nuts! Your first milling project*](https://www.youtube.com/watch?v=TL0OsfFkBL8)
(2020-05-02). Its complete route registers four physical workpieces against one
canonical nut STEP; it does not duplicate that STEP into four source solids.
The section uses selected [Carr Lane CL-0-TN catalog dimensions](https://www.carrlane.com/product/clamping-hardware/studs-bolts-t-nuts/t-nuts)
where the video does not publish dimensions. This is an **adapted example design**,
not an exact video reconstruction, a commercial-part replica, or a released
manufacturing drawing.

The setup sheets remain **PLANNED**, not approved for machining. The current
inputs deliberately complete a **demonstration**: selected equipment, installed
dimensions and commissioning facts are disclosed example values, not physical
measurements or equipment identified in the video. The expected checker exit is
**0** for those authored inputs; that is not a first-article result or a readiness
claim. Inventory, policy and cutting data are local to this bundle.

## Selected design, dimension by dimension

The table separates selected design nominals from their sources.
Inch-to-mm conversions use exactly 25.4 mm/in.

| Item | Selected nominal | Basis |
| --- | --- | --- |
| Quantity | 4 | Video 02:42–02:50; confirmed 06:43 and the later batch operations. |
| Material | 1018 steel; example annealed condition, HB120 | Video stock marking and narration 03:59 establish 1018, not condition or hardness. Annealed/HB120 are author-selected example assumptions, not observations or a material certificate. |
| Finished length, X | 1 in / 25.4 mm | Video 02:42–02:50; repeatable end facing 12:17–12:52. |
| Base width, Y | 7/8 in / 22.225 mm | Selected Carr Lane CL-0-TN dimension **C**. |
| Overall height, Z | 1/2 in / 12.7 mm | Selected Carr Lane CL-0-TN dimension **E**. |
| Stem width, Y | 0.495 in / 12.573 mm | Selected Carr Lane CL-0-TN actual nominal dimension **B** for a nominal 1/2-in slot; not a 0.500-in stem. |
| Flange thickness | 0.250 in / 6.35 mm | Video narration 06:47 and visible `250 thou = 6.35mm` overlay at 06:50. |
| Hole location | Centered in X and Y | Video midpoint/half-function method 07:17–07:33 and hole pickup 12:52–13:08; no positional tolerance. |
| Through thread | 3/8-16 | Video hardware comparison 02:23–02:39, drill/tap 13:11–13:32. Thread class unspecified. |

The actual Carr Lane CL-0-TN has **7/8-in length D and 9/32-in flange F**;
those two values are **not** used here. The selected length and flange instead
follow the video. The manufacturer drawing publishes tolerance information,
but those bands are **not adopted** for this combined design. Instead, the current
example explicitly adopts **±0.002 in (±0.0508 mm)** on base width, overall height,
stem width, flange thickness and finished length. These are **author-selected
demonstration acceptance bands**, not video or catalog tolerances. Local design
**BH-TN-EXAMPLE / catalog-design-1** identifies the authored example, not a released
source drawing. No formal thread class, minor-diameter, positional or roughness
limit is adopted. Raised-burr removal has a separate example maximum incidental
edge break of **0.05 mm**; it does not enlarge the size bands.
The manifest's per-dimension display precision is an author-selected **four
decimal places in mm**, preserving the exact converted inch limits. It is not
an original-drawing precision claim or an instrument-resolution requirement.

The video asks the viewer to measure the recipient table's slot rather than
giving a universal drawing. A catalog's nominal 1/2-in slot designation does
not prove that this nut will fit another mill. Measure the actual throat,
undercut and depth, establish suitable fit limits, and perform the final
functional checks before using the nuts.

### Model and tool-coordinate boundary

The STEP uses X along the one-inch length, Y across the symmetric section,
and Z upward from the bottom. See [geometry-provenance.md](geometry-provenance.md)
for the generator, exact face identities, source/design distinctions and digest.
The bore is a **9.525-mm nominal-major visual envelope**, not a tapping-drill
size, finished minor diameter or modeled helical thread. Edge breaks, cold-blue
effects and the bottom-thread staking deformation are not represented. The
STEP does not stop a stud from passing through; the physical retention check does.

![Nominal finished T-nut design, not stock or workholding evidence](part-reference.svg)

The source's nominal **±0.477-in cutter-center coordinates** and **0.010-in
finish allowance** are machining demonstrations, not a stem-width drawing.
Do not transfer that cutter-center setting to this selected 0.495-in stem.
The example selects a **0.500-in finishing cutter**, giving nominal shoulder-wall
cutter centers `Y = ±(0.495/2 + 0.500/2) = ±0.4975 in`; roughing centers are
**±0.5075 in**, leaving 0.010 in on each wall. These are authored demonstration
settings, not recovered tool measurements. [The provenance ledger](geometry-provenance.md#physical-input-completion)
owns the fresh stem-top touch and native contact/clearance boundary.

## Complete route and source ledger

The physical route contains **29 setups, 64 operations and 14 presentation
families**. B0 through S1 process one batch bar; C1a, C1b and C2 make exactly
three partition cuts. Named outputs retain each nut's material identity.
E1a–d through F1a–d then name the four separate physical members; presentation
groups share instructions, not material, findings or inspection results.

| Setup | Planned work | Source video |
| --- | --- | --- |
| B0 | Measure the actual T-slot; distinguish 3/8-16 hardware from misleading M10 × 1.5 near-fit; use the portable powered band saw to cut stock held in the bench vise. | 01:30–02:52; band wheels/blade visible at 02:45. |
| Q1 | Face the first long reference surface; remove seating burrs. | 03:03–04:03. |
| Q2 | Seat that face against the fixed jaw, use round bar at the moving jaw, and face the adjacent long surface. | 04:06–04:28. |
| Q3 | Use the squared corner as a reference and face the opposite long side; measure the width. | 04:30–05:36. |
| Q4 | Support on parallels and face the fourth long surface to overall height; keep head/quill/table rigid. | 05:47–06:34. |
| S1 | Choose grip/parallel height for shoulder clearance; edge-find both sides, use the DRO half function, rough both shoulders with cutting fluid, then finish conventionally. | 06:43–10:25. |
| C1a, C1b | Two separate upright slitting-saw cuts, each with its own pickup, body-side setting and retained outputs. | 10:25–11:30; upright cut visible 11:05. |
| C2 | Final upright separation; the previously separated nut1 blank balances the other jaw end. Paper goes with the cutting workpiece. | 11:31–11:50. |
| E1a–d | Face each nut's free end to length; retain the opposite saw end against the rod stop. | 12:17–12:52. |
| D1a–d | Locate each midpoint, centre drill, drill through and hand tap 3/8-16 with cutting fluid and spring follower. | 12:52–13:40. |
| B1a–d | Deburr hole mouths and edges, then stake only the last bottom thread. | 13:40–15:06. |
| B2a–d | Degrease, detergent-clean, JAX-blacken, rinse, dry and oil each nut. Blackening is mandatory in this example. | 15:08–16:45; product directions supplement the source. |
| F1a–d | One initially unfilled overall result per finished nut: all five size bands, both flange readings, actual-slot fit, stud retention and uniform black/oiled finish. | 17:00–17:33; numeric bands and final-only timing are authored choices. |

Squaring and appearance finishing are described as optional in the video, but
are retained here rather than silently dropping demonstrated phases. Four
long-face preparation setups precede the shoulder cuts; end finishing follows
separation. The black Niagara HSS TiCN squaring cutter is distinct from the
gold-coloured shoulder rougher shown beside the finisher at 07:44. The source
leaves 0.010 inch on the shoulder walls only, with the rough-cut floors already
at flange height. The example instead gives the finisher a fresh touch on the
surviving stem top; it does not reuse the source's rough-floor touch.
The two-tool shoulder route is retained, although the video mentions a suitable
finishing cutter alone as an alternative. No coating/material is inferred from
the gold colour.
Between early setups, the plan explicitly selects the video's later hand files
for seating-burr removal; the exact early deburring tool is not established.

### Editorial safeguards, not claimed video equipment

- **No gloves near the rotating spindle.** The source's one-glove anecdote at
  12:03–12:17 is not adopted as machining practice. Chemical-compatible gloves
  belong only in the separate stopped-machine chemical task.
- **Do not catch or retrieve loose cut-offs near a running saw.** The adopted
  example adds a pre-made, table-anchored capture assembly, finite blade/arbor
  geometry and a complete stopped return before retrieval. This is illustrative
  equipment, not equipment identified in the video. Occupied-geometry and pad
  contact checks do not certify dynamic capture capacity or anchorage strength;
  C2's balancing blank is not the independent upper-piece hold.
- The source emphasizes conventional milling, sufficient jaw grip, cutter
  clearance, quill/head rigidity and unused-axis locking. Actual dimensions
  and settings still need to be measured rather than read off a rendered image.
- Hand tapping is with the **spindle stopped**. Through-drill point clearance,
  parallel/vise avoidance, tap lead breakthrough and follower travel remain
  prerequisites, not inferred from the simple bore.
- The chemical sequence is **not a complete chemical-safety instruction**.
  The example selects JAX Iron/Steel/Nickel Blackener and ISO-VG32 oil rather
  than attributing those exact products to the video. Follow the cited product
  directions/SDS, including ventilation, splash protection, chemical-compatible
  gloves, solvent/fire controls and segregated waste. The source's approximate
  immersion time does not override the actual product instructions.

## Demonstration inputs and physical boundary

[geometry-provenance.md](geometry-provenance.md) owns the acceptance, stock,
registration, saw/capture, cutting-data and commissioning ledgers. The example
starts from a **1 × 0.625 × 5 in** raw bar; B0 retains **4.475 in**, followed by
four **1.025-in** blanks and three **0.125-in** separation kerfs. Each end cleanup
removes **0.025 in**. Those are adopted inputs, not measurements of source stock.
The PM-25MV-BD mill, tooling and installed fixture dimensions are likewise
illustrative selections. Source-known nominals retain their separate citations.

B0's source-derived illustrative starting band speed is **135 sfm = 270 × 0.50**.
[LENOX's Guide to Band Sawing](https://www.sawcalc.com/images/lenox-guide-to-band-sawing.pdf),
printed p. 21, gives 270 ft/min for 4-in-wide annealed 1008/1018 with a bi-metal
blade and flood sawing fluid, and a 30–50% reduction for no fluid. The author
selects 50% and takes no small-section speed increase. The example explicitly
adopts annealed 1018/HB120 and a bi-metal blade with an HSS cutting edge
electron-beam welded to a spring-steel back (glossary, printed p. 32), not an
observed stock condition or identified blade product. The 100–350-sfm machine
range is unchanged example capability, not a loaded-speed measurement.
The **14 TPI**, **.889-mm kerf** and **25.4 mm/min descent** remain independent
illustrative inputs; the chart does not qualify their combination or the whole
cut as conservative. This is not a product-specific portable-saw recommendation
or execution approval.

Installed facts use the repository's deliberately nonphysical disclosure:

```toml
measured = { status = "measured", by = "example value (realistic, not a shop measurement)", date = "2026-10-11", instrument = "example fixture (no physical measurement)" }
```

This exercises the measured-input branch; the wording is not a trust exception.
Fields whose schemas require bare numbers/vectors retain that shape with
adjacent example-value citations. Cutting recommendations use the offline
Handbook and tool-maker sources in the ledger, not inferred video tool sizes.

Only **F1a–F1d** record acceptance, after each member's machining, deburring,
staking and mandatory blackening/oiling. No intermediate operation supplies
hidden acceptance credit. Actual-slot and intended-stud comparisons supplement,
not replace, the five numeric size checks. No inspection has been executed:
all four result spaces start blank.

An exit of 0 does not mean every finding is a pass: the current report retains
four nonblocking accessibility unknowns for the hand-tapping operations. The
thread envelope is not native helical-thread proof. Before adopting any route
in a real shop, replace the demonstration commissioning facts with qualified
actual stock, slot, machine, tools, fixtures, zeros and cutting data, establish
the required acceptance specification, and obtain the appropriate review.
Neither checker success nor a rendered sheet establishes safe motion, holding
strength, chemical suitability, a clamping load rating or first-article approval.

## Files and reproduction

| File | Purpose |
| --- | --- |
| `plan.toml` | All 29 physical setups, four registered workpieces, retained outputs, zero recipes, final inspections and editorial safeguards. |
| `features.toml` | Selected nominals, five authored size bands, manual fit/retention relationships, exact STEP digest/face references and source provenance. |
| `inventory.toml` | Source identities and adopted demonstration equipment, with fact-local example qualification. |
| `shop-policy.toml` | Local required checks and cited demonstration policy floors. |
| `cutting-data.toml` | Cited offline Handbook/tool-maker rows and the disclosed illustrative bandsaw setting. |
| `build_part.py`, `t-nut.STEP`, `geometry-provenance.md` | Reproducible one-part design and geometry/face provenance. |

From the repository root, generate the report and printable setup sheets.
Omitting `--detail` selects **hobby**; explicit choices are **pro**, **hobby**
and **pedantic**. Detail changes presentation, not the checker inputs or exit.
Pro and hobby use a compact tool key and state shared units once. Preparation
headings keep each setup's grip and parallel instructions scoped; final
inspection places each numeric criterion beside its method and retains four
separate result boxes, one per physical nut. Hobby adds practical guidance;
pedantic retains expanded detail. Shared presentation does not prove fit,
combine results or approve execution.

Compact sheets retain the selected DRO resolution, finder speed range and saw
arbor identity. Hobby preparation rows keep pass extents, transverse stations,
face Z and lift together. Saw cycles state **stop before withdrawal**, with
capture held through the full return; the initial bandsaw descent has explicit
linear-feed units. The manual-tapping accessibility unknown remains disclosed,
not relabeled as clear.
Hobby facing-family sheets place the selected picture after the orientation/path
table and before shared facing/deburring steps, with headings inline beside
their opening instructions.

```sh
uv run prechips traveler examples/blondihacks-t-nuts/plan.toml --out out/blondihacks-t-nuts
uv run prechips traveler examples/blondihacks-t-nuts/plan.toml --detail pro --out out/tnut-detail-pro
uv run prechips traveler examples/blondihacks-t-nuts/plan.toml --detail hobby --out out/tnut-detail-hobby
uv run prechips traveler examples/blondihacks-t-nuts/plan.toml --detail pedantic --out out/tnut-detail-pedantic
```

The intended operator-facing output is `out/blondihacks-t-nuts/traveler.html`;
findings remain in the adjacent `report.json`. Generation requires no live
video/catalog fetch. The source MP4, captions and metadata were acquired into
an **external local cache**, not this repository. To acquire a fresh local
research copy, an example command is:

```sh
uv tool run yt-dlp --format "bv*[height<=1080]+ba/b[height<=1080]" --merge-output-format mp4 --write-auto-subs --sub-langs en-orig --write-info-json --output "TL0OsfFkBL8.%(ext)s" "https://www.youtube.com/watch?v=TL0OsfFkBL8"
```

That is a reproduction instruction, not a claim that this exact command was
used in every environment. Authentication/cookie details are intentionally
not copied. Do not commit the full video or captions. The inspected local
video is 1920 × 1080, about 18:05, with matching English automatic captions.
The caption extraction is summarized above rather than reproduced wholesale.

Important ASR corrections: **four**, not “forty”; **3/8-16**, not “3/16”;
T-nut/T-slot, not “tea nut/tea slot.” The oil's product/type is not established;
the source says any oil will work, so the plan does not assert way oil.
The garbled “soccer” phrase near 02:42–02:52 is interpreted cautiously as
separation/saw allowance, not a dimensioned manufacturing instruction.

