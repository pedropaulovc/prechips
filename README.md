# Prechips v0.10

Turn an authored manual-machining process into a printable HTML traveler with the tools, setups, feeds, speeds and inspections an experienced operator needs.

This is a clean-slate prototype awaiting Pedro's milestone approval. It does not check geometry, choose a machining process or certify a setup. The previous implementation is preserved on [`archive/pre-v0.10-2026-11-08`](https://github.com/pedropaulovc/prechips/tree/archive/pre-v0.10-2026-11-08); old code will return only when a useful milestone needs it.

## Run

Python 3.12+ and [uv](https://docs.astral.sh/uv/):

```sh
uv sync --locked
uv run prechips traveler examples/base-bar.toml --out out/base-bar.html
```

Open the HTML in a browser. Print on Letter paper at 100% scale with browser headers and footers off. The HTML is standalone; it needs no server or internet connection.
The output must be a different file from the input plan, including filesystem aliases.

The base-bar example uses professional operator shorthand and is limited to two Letter pages at 10.5pt. It omits routine technique and generic safety reminders. It follows the November 5 hand-written guide's flat-on-table width operation. Following machinist review, rounded slots finish with a 17/32 in end mill along the specified arc-centre path instead of the guide's rectangular lap. The authored 1200 rpm / 4.8 in/min starting settings derive from the guide's 165 ft/min and .002 in/tooth. Source references are in the TOML comments.

Setups are numbered in order; operations use unique numbers in increments of ten. Operation tables align work instructions with tooling and cutting settings. Coordinate and inspection tables keep related values together.

## Process TOML

Dimensions and manual feed instructions are strings with explicit units; spindle speeds are positive integer rpm. Tool identifiers connect operations to descriptions and are not printed.

```toml
title = "Part setup sheet"
part = "drawing-part-name"
revision = "drawing revision"
material = "drawing material"
stock = "stock dimensions and quantity"
note = "Optional job-specific prerequisite"

[[tools]]
id = "cutter"
name = "Short tool name"
description = "Tool description and size"

[[setups]]
title = "Operation and setup"
machine = "Machine"
holding = "Workholding, orientation and necessary clearance"
datum = "Datum faces, axis directions and zero"
inspection = ["Setup-level inspection and acceptance limits"]

[[setups.operations]]
tool = "cutter"
instruction = "The cut, dimensions and coordinates"
# rpm = 1000              # Supply the actual authored spindle setting.
feed = "Authored feed with units, or a manual-feed instruction"
inspection = "Operation-specific inspection and acceptance limits"

[setups.operations.table]
columns = ["Feature", "X", "Y"]
rows = [["Feature name", "Authored X coordinate", "Authored Y coordinate"]]
```

Root `note`, tool `name`, setup `holding`, `datum`, `inspection`, and operation `tool`, `rpm`, `feed`, `inspection` and `table` are optional. Omit irrelevant setup fields rather than filling them with boilerplate. Omit `tool` for inspections or work requiring only ordinary shop equipment. Tool names provide short labels in operation tables; the tooling list retains full descriptions. Other shown fields are required; tools, setups and operations must be nonempty. Optional operation tables contain string `columns` and string-array `rows`, each matching the column count. Unknown fields and unresolved tool references produce an input error. Repeat tables in working order; each operation belongs to the most recent setup. Setup inspections print after its operations. Do not invent unknown machining values to fill a field.

## Development

```sh
uv run pytest
uv run ruff check .
uv run ruff format --check .
```

Keep tests to a CLI smoke test and fragile behavior. Run the CLI and inspect the print layout for changes to the sheet. No FreeCAD, integrity hashes, certificates, rule framework or verbosity modes in this milestone.

Pedro reviews each milestone. Work must not run more than three milestones ahead of his last review; v0.10 is the current review target. No later milestones are committed here.
