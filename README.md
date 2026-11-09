# Prechips v0.2

Turn an authored manual-machining process into a printable HTML traveler. Choose a compact professional sheet or a hobby sheet with setup diagrams.

This is a prototype, not a geometry checker or machining certificate. v0.2 adds profiles and setup diagrams to the v0.10 restart. The previous implementation is preserved on [`archive/pre-v0.10-2026-11-08`](https://github.com/pedropaulovc/prechips/tree/archive/pre-v0.10-2026-11-08); old code returns only when a useful milestone needs it.

## Run

Python 3.12+ and [uv](https://docs.astral.sh/uv/):

```sh
uv sync --locked
uv run prechips traveler examples/base-bar.toml --profile pro --out out/base-bar-pro.html
uv run prechips traveler examples/base-bar.toml --profile hobby --out out/base-bar-hobby.html
```

Open either HTML in a browser. Print on Letter paper at 100% scale with browser headers and footers off. Both files are standalone; hobby embeds its diagrams, so they need no server, internet connection or adjacent image files.
The output must be a different file from the input plan, including filesystem aliases.

The pro base-bar example stays within two Letter pages at 10.5pt. Hobby uses extra pages for readable diagrams of all five setups. Both retain professional operator wording without routine technique or generic safety reminders. The base-bar route follows the November 5 hand guide, with the reviewed 17/32 in slot-finishing method. Source references and the cutting-data derivation are in TOML comments.

Setups are numbered in order; operations use unique numbers in increments of ten. Operation tables align work instructions with tooling and cutting settings. Coordinate and inspection tables keep related values together.

## Profiles

| Preset | Setup diagrams | Enforcement |
| --- | --- | --- |
| `pro` (default) | Omitted; diagram files are not opened | Ordinary process input errors only |
| `hobby` | Included for every setup | Missing, unreadable or invalid SVG diagrams fail with exit 2 |

v0.2 enforcement covers rendering completeness only. It does not check feeds, clearances or machining safety. The diagrams are authored setup illustrations, not CAD-derived fixture assemblies; no FreeCAD is needed.

Use `--profile path/to/profile.toml` for a custom profile:

```toml
name = "illustrated"
features = ["setup_diagrams"]
enforce = []  # Include declared diagrams; allow setups without one.
```

Add `"setup_diagrams"` to `enforce` to require one for every setup. It must also appear in `features`. These are the only feature and enforcement keys supported in v0.2; unknown keys are errors.

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
diagram = { file = "diagrams/setup.svg", alt = "Workholding and datum orientation" }

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

`diagram` is optional in the process schema. Its `file` and `alt` strings are required when it is supplied. SVG paths are relative to the process TOML, regardless of the working directory. An enabled diagram must parse as SVG; it is embedded as an image, not executable page markup. In `pro`, unused diagram files are not opened.

## Development

```sh
uv run pytest
uv run ruff check .
uv run ruff format --check .
```

Keep tests to CLI smoke coverage and fragile behavior. Run both profiles and inspect their actual print layouts for sheet changes. No FreeCAD, integrity hashes, certificates or machining-rule framework in this milestone.

Pedro reviews each milestone. Work must not run more than three milestones ahead of his last review; v0.2 is the current review target.
