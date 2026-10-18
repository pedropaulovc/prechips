# Frequently asked questions

Use these answers to decide what a prechips result can tell you. For a failed command or unresolved finding, use [troubleshooting](troubleshooting.md).

## What does prechips check?

Prechips checks an authored machining plan against its feature manifest, shop inventory, cutting data and shop policy. It produces a bound JSON report and, with the `traveler` command, a printable setup sheet. Checks cover declared tooling, operation sequence, dimensions, inspection, coordinates, workholding and supported geometry or machine-envelope constraints.

The checks depend on the supplied facts and the scope of each rule. Start with the [worked tutorial](tutorial.md), then use the [input and rule references](../README.md) for the checks that apply to your plan.

## Does it generate G-code or simulate a complete toolpath?

No. Prechips supports authored manual-machining plans and DRO instructions. It does not generate CNC programs or simulate the complete machine and tool motion.

Some geometry rules evaluate declared cuts, tool envelopes, clearance samples or intermediate stock. Those checks have specific scope and limits. A passing sample or modeled cut does not establish collision-free approach, retraction or every motion between checked positions. See the [geometry rule reference](../rules-geometry.md).

## Does a passing report certify that machining is safe?

No. A report checks consistency and supported constraints in the supplied inputs. It cannot certify the actual setup, cutter condition, clamping distortion, chatter, operator execution, final dimensions or correctness of the CAD and authored facts. A modeled fixture image does not prove the physical fixture matches it.

The machinist must check the real setup and follow the applicable inspection and first-article process. Tests, example output and rendered sheets do not establish physical acceptance. See the [report and approval contract](../report-and-telemetry.md#eligibility-and-approval).

## Can I run it offline?

Yes, once the Python environment and any required native software are installed locally. Checks read local inputs. Citation strings are evidence pointers; prechips does not fetch the cited source to validate it during a check.

Optional OTLP trace and log export sends telemetry to configured endpoints. Remove OTLP endpoint settings when you need a run without that export. Installing dependencies can also require network access. These are separate from the local checking workflow. See [telemetry configuration](../report-and-telemetry.md#telemetry-and-console) and [installation prerequisites](quickstart.md).

## Do I need FreeCAD?

You need a discoverable local FreeCAD command executable for the native geometry checks. Host-side input validation and the plan-scoped measurement checklist can run without it. A full check with unavailable FreeCAD reports unresolved geometry and cannot reach readiness; it exits 4 unless an error finding takes precedence with exit 2.

`FREECAD_CMD` selects the executable explicitly, including when the selected executable is unavailable. For discovery order and recovery, see [FreeCAD troubleshooting](troubleshooting.md#freecad-is-installed-but-geometry-says-the-kernel-is-unavailable). Installing FreeCAD does not fill in missing geometry facts or measurements.

## Are the example plans ready to use in my shop?

No. The examples demonstrate authored inputs and checker behavior. Their dimensions, tooling and measurement records are not measurements of your equipment. A fixture that exercises a measured-data branch does not prove that a physical measurement took place.

Use an example to learn the format, then author and verify your own inputs from the relevant drawing, tools, machine and workholding. Keep unsupported or unmeasured facts unresolved until you have evidence. The [example provenance page](../../examples/README.md) owns the disclosures; the [demonstration](demo.md) shows how to interpret actual example output.

## What is the difference between `unknown` and `pass`?

`pass` means the check's supplied facts satisfy that rule. `unknown` means the check lacks enough accepted evidence to decide. An unsupported case is also unresolved, not a pass. Missing values do not become zero, and a plausible nominal size does not become a measured installed dimension.

Required warnings, unknowns and unsupported results prevent readiness. Errors take precedence. Some rules are always required; other requirements come from shop policy. Exit 0 can still contain unresolved nonrequired findings, so read the findings as well as the summary. See [shop policy](../policy.md) and [readiness troubleshooting](troubleshooting.md#approval-does-not-clear-warnings-or-exit-4).

## Why is the setup sheet planned when the report is checked?

Checking and approval are separate. A report marked `checked` has exit 0 under the readiness rules. The sheet remains `PLANNED` until a supplied approval record matches that report's hash, records actual first-article evidence and refers to a checked report.

Approval cannot waive unresolved required checks. Input or bound-output changes can invalidate an earlier approval. Follow the [approval contract](../report-and-telemetry.md#eligibility-and-approval); do not record first-article evidence merely to change a demonstration's status.

## Does a matching report hash prove the inputs are true?

No. The hash binds canonical report content, including input digests and returned render digests. It helps identify the exact evidence used and detects content changes when a saved report is explained. It does not verify that an author measured a value correctly, selected the right drawing revision or exported the correct part.

Use `explain` to inspect an unchanged saved report. It validates the report hash and selected finding structure without rerunning geometry. See [saved-report troubleshooting](troubleshooting.md#explain-refuses-a-saved-report-or-finds-no-matching-row) and the [report format](../report-and-telemetry.md#canonical-report).

## Can I import prechips from Python?

Yes. The implementation is Python and has importable functions for loading inputs, evaluating rules and building reports. Importability does not promise a stable public SDK. Use the actual callables and side-effect boundaries in the [Python API catalog](../reference/python-api.md), and review compatibility when upgrading.

For an automated command workflow, the [CLI catalog](../reference/cli.md) documents the five verbs, machine-readable output and exit codes. Direct library calls can start native geometry. They do not automatically reproduce every CLI step, such as complete registry evaluation with required coverage, output-safety handling or approval processing.

## Why did a command produce files and still fail?

A valid plan can produce a useful planning report and sheet while its findings prevent readiness. Exit 2 means an error finding; exit 4 means unresolved readiness. Bad input and handled output errors use exit 3. Files from an earlier run may remain after a refused run, so file existence alone is insufficient.

Use a dedicated output directory, check the process exit and inspect the current report. The [output troubleshooting steps](troubleshooting.md#the-output-destination-is-refused-or-a-previous-sheet-disappears) explain replacement and stale-file removal. The [CLI streams and errors reference](../reference/cli.md#streams-and-errors) and [output-safety reference](../reference/cli.md#output-safety-and-environment) own the complete exit and output contract.
