# Follow a plan through its findings

Use the pivot-shaft example to trace an authored operation into a checker finding, then find the same work on the printable setup sheet. You will also learn how to investigate unresolved facts without changing the example to manufacture a pass.

## Before you start

Complete the [quickstart](quickstart.md), including the local FreeCAD installation. Run the PowerShell commands here from the checkout root. You can reuse the quickstart's output directory.

The [example bundle](../../examples/pivot-shaft/plan.toml) is an illustrative route for drawing MHA-065, revision v40. Its stock dimensions, holding choices and much of its inventory are demonstration values. The [examples policy](../../examples/README.md#examples-policy-plausible-labelled-values) identifies the deliberately nonphysical measurement metadata and the separately recorded real shop measurements. Leave those disclosures and the supplied files unchanged.

## 1. Identify the five inputs

Open `examples/pivot-shaft/plan.toml`. It names a feature manifest and three shared shop files. Together they provide five TOML inputs:

| Input | Role in this example | Reference |
| --- | --- | --- |
| `examples/pivot-shaft/plan.toml` | The authored route: stock, setup frames, workholding, DRO zeroing, ordered operations and inspection choices | [Plan format](../plan.md) |
| `examples/pivot-shaft/features.toml` | Part and drawing identity, dimensional requirements, model frames and face identities bound to the adjacent STEP file | [Feature format](../features.md) |
| `examples/inventory/pedro-shop.toml` | The machines, tools, holders, fixtures, gauges and other shop items the plan selects, with their source and measurement records | [Inventory format](../inventory.md) |
| `examples/shop-policy.toml` | Shop-owned required checks and limits; the plan cannot waive the shop's requirements | [Policy format](../policy.md) |
| `examples/cutting-data.toml` | Cited starting cutting data and material properties used by the relevant rules | [Cutting-data format](../cutting-data.md) |

The following exact fragment from the plan binds the three shared files. It is not a complete plan:

```toml
[paths]
inventory = "../inventory/pedro-shop.toml"
policy = "../shop-policy.toml"
cutting_data = "../cutting-data.toml"
```

Those paths are relative to the plan directory. The plan's `features = "features.toml"` resolves there too. The manifest names `pivot-shaft.STEP` and its SHA-256 digest; STEP is an adjacent geometry asset, not another authored process plan. Prechips checks the asset's bytes against that digest.

For this run, you do not need shop-file flags. If you later use them, explicit CLI overrides take precedence over known plan paths. CLI paths are relative to your working directory. See [input selection in the CLI catalog](../reference/cli.md) for environment fallbacks and containment rules.

## 2. Follow the preparation into the next setup

In `plan.toml`, find `[process_features.plain_end_centre]`. It declares the centre hole made for supporting later work. It is a plan-owned stock-preparation feature, not a dimension added to the finished-part drawing.

Under the first setup, `id = "S0"`, find this operation. The exact fragment stops before the operation's explanatory note:

```toml
[[setups.ops]]
op = 20
do = "center_drill"
feature = "plain_end_centre"
tool = "center-drills-lms-4859/2"
holder = "drill-chuck-tailstock-mt3"
```

The feature points back to the preparation declaration. The tool selects member `2` of the named inventory set, and the holder selects the tailstock drill chuck. Open the inventory file and locate those identities to see the facts the checks consume.

Next, find setup `S1`. Its hold selects `dead_centre_tailstock_mt3`, names `centre_hole = "plain_end_centre"` and declares a `3.0` mm mouth. This creates a dependency: S0 op 20 must make the seat before S1 uses it.

Follow the file's setup and operation array order. Operation numbers identify steps; prechips does not sort the route numerically.

## 3. Generate the report and sheet

Run the same command as the quickstart if you have not generated the files yet:

```powershell
uv run prechips traveler examples/pivot-shaft/plan.toml --out out/docs-smoke/pivot-shaft
$LASTEXITCODE
```

With FreeCAD available, the recorded run exited `0` and wrote `report.json`, `traveler.html` and four setup images. Its report has `verification = "checked"`. The [demonstration](demo.md) pairs the source fragments with actual output from this invocation.

`traveler` always evaluates the current inputs. It does not use a checked-in expected report as its answer. Keep the generated files in `out/` so you can compare them with the source without overwriting the source bundle.

## 4. Inspect one finding

A finding identifies a `rule` and a `subject`, then gives its `status`, `message`, `numbers` and `cite` entries. Subjects can identify a setup, an operation, a feature or another checked item. For example, `S0:20` means op 20 in setup S0.

Read the centre-support finding from the generated report:

```powershell
uv run prechips explain out/docs-smoke/pivot-shaft/report.json centre_support:S1 --json
```

The first colon separates the rule from its subject. This command selects the exact `centre_support` finding for `S1`, validates the saved report's hash and prints that finding as JSON. It does not rerun geometry or approve the report. A successful lookup exits `0`, even when the selected finding describes a failure or unresolved fact.

In this run, its message is:

> S1: the centre rides in plain_end_centre, drilled in S0 op 20.

Its `numbers` identify the support and preparation, including `made_by = ["S0 op 20"]`. Its citation points to the holding-field contract. The finding connects a later support to the earlier operation that makes its seat; it is not evidence that the physical hole has been drilled or inspected.

When reading other findings, distinguish these states:

| Status | How to use it |
| --- | --- |
| `pass` | The rule found enough declared facts to satisfy its check within the rule's model. |
| `error` | The rule found a violation. Any rule error makes the check exit `2`. |
| `unknown` | A needed fact or proof is unresolved. A required unknown makes the check exit `4`. |
| `unsupported` | The rule cannot evaluate the declared case. A required unsupported result makes the check exit `4`. |
| `warn` | Read the stated concern. A required warning makes the check exit `4`. |
| `not_applicable` | The rule explicitly does not apply to this subject. This differs from lacking enough facts to decide. |
| `info` | Informational output; it does not itself block eligibility. |

A missing FreeCAD kernel also makes the run unresolved. Error exit `2` takes precedence over unresolved exit `4`. The [rule references](../README.md) explain the inputs and limits of each check; the [CLI catalog](../reference/cli.md) defines all command exits.

## 5. Investigate measurement debt

For a plan whose findings need installed measurements, list the outstanding measurement instructions:

```powershell
uv run prechips tools --measure --plan examples/pivot-shaft/plan.toml
```

This reads the plan's selected inventory and evaluates the measurement checklist on the host. It does not run FreeCAD. It prints checkboxes and source citations for the measurement entries emitted by the checks; no entries means no checklist text. Its exit `0` means the checklist command succeeded, not that the plan is ready to run.

The checklist is scoped to facts the selected plan's rules request. It is not an audit of every inventory field, and it does not resolve all kinds of unknown. A missing drawing requirement or an unsupported geometry case needs its own source or rule investigation.

For your own shop bundle, measure the named installed fact with the stated instrument and units, then record the actual value and measurement provenance at that fact's inventory record. Use the [measurement-record contract](../inventory.md#measurement-records). Correct an authored route only when the real route or its declared facts justify the correction, then regenerate the report and review the affected findings.

Never change a measurement status, remove a required rule or copy the example's nonphysical provenance just to change the exit code. An absent value, an explicit `"unknown"` and a known empty list can have different meanings; use the relevant input reference before changing one into another.

## 6. Read the printable sheet separately

Open `out/docs-smoke/pivot-shaft/traveler.html` in a browser. Start with `JOB STATUS`. This example says that no first article is recorded and the stock must be obtained. The banner remains `PLANNED` and `NOT APPROVED`, although the report's checker result is `"checked"`.

Find setup S0 and compare it with the plan:

1. `HOLD` gives the chuck, grip, stop and clamping instructions.
2. `TOOLS FOR THIS SETUP` maps the selected inventory identities to local tool numbers.
3. `DRO ZERO` gives touch-off instructions and direction checks. The lathe's X display reads diameter.
4. `OPERATIONS` presents op 10 facing and op 20 centre drilling, with starting speed, feed, target and the authored instructions.
5. The attached holding picture and clearance section show the modeled setup. `setup-S1.png` belongs to authored setup S0 because filenames use ordinal numbering.

The setup sheet is the document the operator reads and writes on. The report keeps rule IDs, detailed numbers, source citations and input hashes for investigation. An operation's performed mark records that the operation was performed; it is not inspection acceptance or permission to proceed past a stop.

Use the browser's print preview for the whole HTML file on Letter portrait paper. Keep JavaScript enabled so the layout inserts blank backs and starts each logical setup section on a front side; print the whole file double-sided. If scripts are disabled, print single-sided. Check the preview rather than assuming that one setup occupies one physical sheet. The CLI has not generated a PDF for you. See the [generated-sheet reference](../report-and-telemetry.md#generated-traveler) for the print contract.

Approval requires separate first-article evidence bound to the eligible report; it cannot waive required unresolved checks. A generated report or printed sheet does not certify the physical setup, prevent every collision or simulate the operator's motion path.

Return to the [documentation home](../README.md) for other tasks. Use the [CLI catalog](../reference/cli.md) for flags and the [Python callable catalog](../reference/python-api.md) if you need to call implementation functions from code.
