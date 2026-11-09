# Prechips v0.4

Turn an authored manual-machining process into a printable HTML traveler. Choose a compact professional sheet or a hobby sheet with setup diagrams.

This prototype binds traveler dimensions to a selected CAD/drawing export. Process choices remain authored. The previous implementation is preserved on [`archive/pre-v0.10-2026-11-08`](https://github.com/pedropaulovc/prechips/tree/archive/pre-v0.10-2026-11-08); old code returns only when a useful milestone needs it.

## Run

Python 3.12+ and [uv](https://docs.astral.sh/uv/):

```sh
uv sync --locked
uv run prechips traveler examples/base-bar.toml --profile pro --out out/base-bar-pro.html
uv run prechips traveler examples/base-bar.toml --profile hobby --out out/base-bar-hobby.html
```

Open either HTML in a browser. Print on Letter paper at 100% scale with browser headers and footers off. Both files are standalone; hobby embeds its diagrams, so they need no server, internet connection or adjacent image files.
The output must be a different file from the input plan, including filesystem aliases.

The pro base-bar example stays within two Letter pages at 10.5pt. Hobby includes diagrams of all six setups. Dimensions come from the released v47 CAD/drawing export; the November 7 discussion supplies the table-clamped squaring sequence. Tool selection, allowances, feeds and speeds remain process choices.

Setups are numbered in order; operations use unique numbers in increments of ten. Operation tables align work instructions with tooling and cutting settings. Coordinate and inspection tables keep related values together.

## CAD dimensions

The example reads `examples/cad/base-bar-v47.toml`, an unchanged copy of the released harmonic-analyzer `features.toml`. Point `cad.file` at another export to use that file directly. No STEP reader, FreeCAD, network access or hash checking is involved.

```toml
[cad]
file = "cad/base-bar-v47.toml"
adapter = "harmonic_base_bar"

[parameters]
blank_length_in = 17.4375
blank_width_in = 6.0
blank_thickness_in = 0.5
quantity = 2
width_rough_allowance_in = 0.015
slot_breakthrough_in = 0.02
slot_step_in = 0.12
slot_finish_diameter_in = 0.53125
```

All supplied parameters must be finite numbers. `blank_length_in`, `blank_width_in`, `blank_thickness_in` and `slot_finish_diameter_in`, when supplied, must be positive in every profile. `quantity`, when supplied, must be a positive integer (not a fractional value, float or boolean) in every profile. Literal-only plans can omit parameters, including `quantity`; the saw diagram requires `quantity`.

Use named bindings such as `{{cad.length_in:.2f}}` and `{{process.blank_length_in:fraction}}` in text. A whole-field binding can supply structured data, as in `rows = "{{cad.hole_rows}}"`. Unknown names fail; bindings do not execute expressions. See `examples/base-bar.toml` for the complete recipe.

The adapter uses exported requirement limits and drawing targets, converts millimetres to inches, and applies the authored setup's negative-Y convention. It distinguishes drawing-rounded positions from model coordinates. Printed dimensions, coordinate tables, diagram labels and feature positions share these values. Literal-only plans work with a custom profile that omits `stock_fit`.

Only the harmonic-analyzer base-bar export is supported by this adapter. Changing CAD dimensions does not select new tools or redesign the machining process.

## Stock fit

Both built-in profiles require declared blank length, width and thickness in inches and compare them with the CAD nominal envelope in matching axes. Exact fits pass. An undersized or missing dimension stops the command with exit 2 before writing output; the error names the affected axis and required size. Successful checks add nothing to the printed sheet.

This compares each rectangular blank, not the parent bar. It does not rotate stock, reserve machining allowance, calculate yield or check workholding.

## Profiles

| Preset | Setup diagrams | Enforcement |
| --- | --- | --- |
| `pro` (default) | Omitted; diagram files are not opened | Stock fits the CAD envelope |
| `hobby` | Included for every setup | Stock fits; every setup has a readable SVG diagram |

Enforcement does not check feeds, clearances or machining safety. The diagrams illustrate setups using CAD-derived part dimensions and authored fixture layouts; no FreeCAD is needed.

Use `--profile path/to/profile.toml` for a custom profile:

```toml
name = "illustrated"
features = ["setup_diagrams"]
enforce = []  # Skip stock checking; allow setups without a diagram.
```

Add `"setup_diagrams"` to `enforce` to require one for every setup; it must also appear in `features`. Add `"stock_fit"` to `enforce` to require CAD and fitting blank dimensions independently of diagrams. These are the supported enforcement keys; `setup_diagrams` is the only feature key. Unknown keys are errors.

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

Pedro reviews each milestone. Work must not run more than three milestones ahead of his last review. v0.3 introduces CAD bindings; v0.4 adds the profile-controlled stock-fit comparison.
