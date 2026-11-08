# Historical pivot-shaft input and output

This demonstration preserves fragments and recorded output from the earlier v40 pivot-shaft bundle. The recorded run used prechips `0.2.0` with a local FreeCAD kernel available. No shop-file overrides or approval record were supplied. These observations are historical evidence, not results for the current exact v47 CAD source commit `441290434f34f62faba176ef576af6879189c5e7`. The current shaft is plain with two flats and has no cut-to-fit route; no new pass is claimed.

Use the [quickstart](quickstart.md) to install the prerequisites, or the [tutorial](tutorial.md) to follow the five inputs and investigate findings. All commands below use PowerShell from the checkout root.

## Current invocation; historical observations

The current entry point is [`examples/pivot-shaft/plan.toml`](../../examples/pivot-shaft/plan.toml). It selects the adjacent feature manifest and the shared inventory, policy and cutting-data files. The current manifest binds the adjacent `ch-pivot-shaft.STEP` asset by SHA-256; the older asset was named `pivot-shaft.STEP`. Running this command evaluates the current files; it does not reproduce or validate the historical excerpts below.

```powershell
uv run prechips traveler examples/pivot-shaft/plan.toml --out out/docs-smoke/pivot-shaft
$LASTEXITCODE
```

The earlier v40 invocation returned:

| Observation | Result |
| --- | --- |
| Process exit | `0` |
| Standard output | Empty |
| Standard error | Empty |
| Generated files | `report.json`, `traveler.html`, `setup-S1.png`, `setup-S2.png`, `setup-S3.png`, `setup-S4.png` |

These historical observations came from the generated files then in `out/docs-smoke/pivot-shaft/`, not the checked-in expected-output fixtures. Selected top-level fields from that run's actual `report.json` are shown below. Other fields are omitted; this is not a complete report:

```json
{
  "expected_exit": 0,
  "prechips_version": "0.2.0",
  "verification": "checked"
}
```

The report contained 158 `pass` findings and 144 `not_applicable` findings in this run. Exit `0` describes the checker result for these declared inputs. It does not establish that the route was physically executed or approved.

## Preparation input becomes a support finding

The historical plan's first setup was S0. This exact historical operation fragment selects the centre drill and tailstock drill chuck. The rest of the setup and the operation's note are omitted:

```toml
[[setups.ops]]
op = 20
do = "center_drill"
feature = "plain_end_centre"
tool = "center-drills-lms-4859/2"
holder = "drill-chuck-tailstock-mt3"
```

In that historical plan, `plain_end_centre` was declared under `[process_features.plain_end_centre]` earlier in the same file. It was the seat the route made for the later tailstock support. Inside S1's `[setups.hold]`, this exact historical one-line fragment named that seat:

```toml
centre_hole = "plain_end_centre"  # made by S0 op 20
```

The historical report contained this complete finding record:

```json
{
  "cite": [
    "PLAN.md §4.1 hold fields: hold.centre_hole and centre_hole_dia_mm"
  ],
  "message": "S1: the centre rides in plain_end_centre, drilled in S0 op 20.",
  "numbers": {
    "centre_hole": "plain_end_centre",
    "centres": [
      "dead_centre_tailstock_mt3"
    ],
    "countersink_depth_mm": 0.8833459118601275,
    "depth_mm": 2.8633459118601277,
    "drill_length_mm": 1.98,
    "hold_centre_hole_dia_mm": 3.0,
    "made_by": [
      "S0 op 20"
    ],
    "made_later": [],
    "mouth_dia_mm": 3.0,
    "preparation": {
      "S0 op 20": "pass"
    },
    "process_feature": "plan.process_features.plain_end_centre",
    "routed": true,
    "support": "dead_centre_tailstock_mt3"
  },
  "rule": "centre_support",
  "status": "pass",
  "subject": "S1"
}
```

The finding records a valid declared sequence: S0 op 20 prepares the centre hole before S1 relies on it. The calculated depths are derived from the declared feature geometry. They are not measurements of a hole someone drilled in the shop.

A separate geometry finding for S0 op 20 says:

> S0:20: sampled claimed faces clear the selected cutter and holder cylinders.

That was the recorded `accessibility` message for this operation in the historical run. Its sampled cutter-and-holder check does not prove that every approach, withdrawal or manual movement is collision-free.

## Stock input remains an instruction on a checked sheet

The historical plan's `[stock]` table contained these exact lines. This is a fragment, not a complete stock declaration:

```toml
on_hand = false              # inventory stock = [] (pedro-shop.toml:7)
prerequisite = "blank sawn square to 180.5 long from the Ø10 bar"  # AUTHOR'S CHOICE: the saw cut stays a prerequisite because the bar it is sawn from is not declared (on_hand = false; no raw bar length), so a saw setup would have no stock to cut
```

The historical generated `traveler.html` contained this banner:

```html
<div class="banner">PLANNED — NOT APPROVED</div>
```

Its historical `JOB STATUS` included the following actual text, with HTML markup removed:

```text
NOT APPROVED: no first article is recorded; the first part made is the first article — sign it off below.
Before S0: obtain the stock — not on hand.
Before S0: blank sawn square to 180.5 long from the Ø10 bar.
```

The declared preparation and stock availability remain visible even though the report is `"checked"`. No approval record accompanied the command, so no first article was recorded against this report. Approval cannot waive required unresolved checks; see [eligibility and approval](../report-and-telemetry.md#eligibility-and-approval).

## Match the images to the authored setups

The historical report's `renders` entries identified which image belonged to each setup:

| Authored setup | Generated image |
| --- | --- |
| `S0` | `setup-S1.png` |
| `S1` | `setup-S2.png` |
| `S2` | `setup-S3.png` |
| `S3` | `setup-S4.png` |

The filename number is the setup's one-based position in the plan, not its authored ID. Open the HTML with these images kept beside it. The printable sheet uses local tool numbers and setup instructions; the report retains rule identities, citations and detailed computed values. The command did not create a PDF. Use the [print instructions](../report-and-telemetry.md#generated-traveler) to preview the whole file before printing.

## Use the result within its limits

The [example provenance policy](../../examples/README.md#examples-policy-plausible-labelled-values) labels plausible authored choices and deliberately nonphysical measurement metadata. A fixture exercising a measured branch is not evidence of an installed shop measurement. Reusing that metadata would not resolve your own measurement debt.

With FreeCAD missing or a required fact unresolved, a run can still produce a report and sheet while exiting `4`; rule errors take precedence with exit `2`. Read the message and source facts, preserve unresolved values, and correct the underlying issue in your own bundle. Do not edit this demonstration's inputs, weaken policy or invent approval evidence to obtain exit `0`.

The checker does not generate or simulate toolpaths and does not certify physical workholding, chatter-free cutting, operator execution or first-article acceptance. Generated artifacts are evidence of what this software evaluated, not physical machining acceptance.

Return to the [documentation home](../README.md), consult the [CLI catalog](../reference/cli.md) for exact command behavior, or use the [Python callable catalog](../reference/python-api.md) for import paths and stability limits.
