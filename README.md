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

The base-bar example follows the November 5 hand-written guide's flat-on-table width operation. Slot finishing is unresolved: the guide's rectangular finishing lap overcuts the rounded ends and is omitted. Required tooling and the outstanding Ra inspection are noted on the sheet. Source references are in the TOML comments.

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
```

Root `note`, setup `inspection`, and operation `rpm`, `feed` and `inspection` are optional. Other shown fields are required; tools, setups and operations must be nonempty. Unknown fields and unresolved tool references produce an input error. Repeat tables in working order; each operation belongs to the most recent setup. Setup inspections print after its operations. Use multiline TOML strings for coordinate lists. Do not invent unknown machining values to fill a field.

## Development

```sh
uv run pytest
uv run ruff check .
uv run ruff format --check .
```

Keep tests to a CLI smoke test and fragile behavior. Run the CLI and inspect the print layout for changes to the sheet. No FreeCAD, integrity hashes, certificates, rule framework or verbosity modes in this milestone.

Pedro reviews each milestone. Work must not run more than three milestones ahead of his last review; v0.10 is the current review target. No later milestones are committed here.
