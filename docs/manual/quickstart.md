# Generate your first setup sheet

Run the supplied pivot-shaft plan to produce a findings report and a printable setup sheet. You will use the example unchanged, so its authored choices and demonstration measurements remain visible.

## Prerequisites

- Access to the [prechips repository](https://github.com/pedropaulovc/prechips) and Git to obtain a checkout.
- Python 3.12 or newer and [uv](https://docs.astral.sh/uv/getting-started/installation/).
- A local [FreeCAD 1.x installation](https://github.com/FreeCAD/FreeCAD/releases) with its command-line executable. FreeCAD supplies the native geometry kernel; `uv sync` does not install it.
- PowerShell for the commands below. The `uv` commands also work in other shells, but environment-variable and exit-code syntax differ.

Dependency installation needs access to the package sources or an existing local cache. Once the dependencies, FreeCAD and input files are present, checking the bundle needs no network service.

## 1. Install the checkout

From the directory where you keep source checkouts, run:

```powershell
git clone https://github.com/pedropaulovc/prechips.git
Set-Location prechips
uv sync --locked
```

If you already have a checkout, open PowerShell at its root, beside `pyproject.toml`, and run only `uv sync --locked`. Keep this working directory for the rest of the quickstart.

## 2. Make FreeCAD available

Prechips looks for `FREECAD_CMD` first, then the recognized per-user Windows FreeCAD 1.1 installation, then a `freecadcmd.exe`, `FreeCADCmd` or `freecadcmd` launcher on `PATH`.

Step 3 reveals a discovery failure: the command reports that FreeCAD is unavailable, marks geometry findings with `numbers.kernel_unavailable = true`, and exits `4` unless a rule error takes precedence with exit `2`. Use the [unavailable-kernel troubleshooting steps](troubleshooting.md#freecad-is-installed-but-geometry-says-the-kernel-is-unavailable) if that happens.

If your installation needs an explicit launcher path, set its actual path in this PowerShell session before running step 3:

```powershell
$env:FREECAD_CMD = Read-Host 'Full path to the FreeCAD command-line executable'
```

Enter the executable path without surrounding quotation marks. Do not copy another computer's installation path. An invalid explicit override prevents fallback to an automatically discovered installation.

## 3. Generate the example

From the checkout root, run:

```powershell
uv run prechips traveler examples/pivot-shaft/plan.toml --out out/docs-smoke/pivot-shaft
$LASTEXITCODE
```

The last line displays the exit code in PowerShell. With FreeCAD available, this unchanged example exits `0`. The documented run produced no stdout or stderr. A quiet command is normal; inspect its files and exit code.

The output directory contains:

| File | What to inspect |
| --- | --- |
| `report.json` | Findings, source citations, input identities and checker result |
| `traveler.html` | The printable job and setup pages |
| `setup-S1.png` through `setup-S4.png` | The four native setup images |

Image numbering follows setup order: the authored setups `S0`, `S1`, `S2` and `S3` map to image files `setup-S1.png`, `setup-S2.png`, `setup-S3.png` and `setup-S4.png`. These files are not PDFs. The command can replace existing generated files in this output directory; it leaves the example inputs in place.

Without FreeCAD, geometry-dependent findings remain unresolved and no native setup images are produced. This returns `4` unless a rule error takes precedence and returns `2`. Invalid input or a handled output-path/write failure returns `3`. Use the [CLI exit reference](../reference/cli.md#streams-and-errors) for the full exit contract and the [output-safety reference](../report-and-telemetry.md#output-safety) for write guarantees.

## 4. Read the result before printing

Open `out/docs-smoke/pivot-shaft/report.json` in a text editor. Find `expected_exit` and `verification`. The recorded run contains `0` and `"checked"`: its declared inputs satisfy the current checker requirements.

Open `out/docs-smoke/pivot-shaft/traveler.html` in a browser. The sheet still says `PLANNED` and `NOT APPROVED` because no [approval record](../report-and-telemetry.md#eligibility-and-approval) was supplied. Its `JOB STATUS` separately lists the stock as not on hand. Exit `0` does not record a first article, confirm your machine or tooling measurements, or authorize machining.

The examples contain plausible, labelled demonstration values. They are not released shop plans. Read the [example provenance policy](../../examples/README.md#examples-policy-plausible-labelled-values) before reusing any content. Do not copy the fixtures' measurement metadata into a real inventory to clear an unresolved check.

Continue with [Follow a plan through its findings](tutorial.md) to understand the five inputs and read a stored finding. The [input-and-output demonstration](demo.md) shows exact excerpts from this run. See the output reference for [printing](../report-and-telemetry.md#generated-traveler) and [approval rules](../report-and-telemetry.md#eligibility-and-approval).

For other tasks, return to the [documentation home](../README.md). Use the [CLI catalog](../reference/cli.md) for command options and the [Python callable catalog](../reference/python-api.md) for the importable implementation surface and its stability limits.
