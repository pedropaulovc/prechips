"""Read the small process-plan format and render a self-contained print sheet."""

import base64
import re
import tomllib
from dataclasses import dataclass
from enum import Enum
from html import escape
from math import isfinite
from pathlib import Path
from xml.etree import ElementTree

from prechips import indexing, palette, speeds
from prechips.cad import CadData, CadError, bind_data, load_cad
from prechips.checks import CheckError
from prechips.checks import fields as check_fields
from prechips.profiles import PRO, Profile


class PlanError(ValueError):
    """An authored plan has a missing or unusable field."""


def _keys(table: dict, allowed: set[str], where: str) -> None:
    unknown = table.keys() - allowed
    if unknown:
        raise PlanError(f"{where}: unknown field(s): {', '.join(sorted(unknown))}")


def _text(table: dict, key: str, where: str, *, optional: bool = False) -> str:
    if optional and key not in table:
        return ""
    value = table.get(key)
    if not isinstance(value, str) or not value.strip():
        raise PlanError(f"{where}.{key}: expected a nonempty string")
    return value


def _tables(table: dict, key: str, where: str) -> list[dict]:
    value = table.get(key)
    if not isinstance(value, list) or not value:
        raise PlanError(f"{where}.{key}: expected a nonempty array of tables")
    if any(not isinstance(item, dict) for item in value):
        raise PlanError(f"{where}.{key}: expected an array of tables")
    return value


def _shop_record(shop: dict, section: str, key: str, where: str) -> dict:
    records = shop.get(section, {})
    if not isinstance(records, dict):
        raise PlanError(f"shop.{section}: expected a table")
    if key not in records:
        raise PlanError(f"{where}: unknown shared {section} reference {key!r}")
    record = records[key]
    if not isinstance(record, dict):
        raise PlanError(f"shop.{section}.{key}: expected a table")
    return record


def _cutting_settings(table: dict, where: str) -> None:
    _text(table, "feed", where, optional=True)
    if "rpm" in table:
        rpm = table["rpm"]
        if type(rpm) is not int or rpm <= 0:
            raise PlanError(f"{where}.rpm: expected a positive integer")


def _choice(table: dict, key: str, choices: set[str], where: str) -> None:
    if key in table and (not isinstance(table[key], str) or table[key] not in choices):
        raise PlanError(f"{where}.{key}: expected {' or '.join(sorted(choices))}")


STEP_KINDS = {"action", "check", "stop"}


def _steps(operation: dict, key: str, where: str) -> None:
    if key not in operation:
        return
    for index, step in enumerate(_tables(operation, key, where), 1):
        step_where = f"{where}.{key}[{index}]"
        _keys(step, {"text", "kind"}, step_where)
        _text(step, "text", step_where)
        if "kind" not in step:
            raise PlanError(f"{step_where}.kind: required")
        _choice(step, "kind", STEP_KINDS, step_where)


def _work(operation: dict, where: str) -> None:
    """Each slot, compact and detailed, holds instruction text or steps."""
    if "instruction" in operation and "steps" in operation:
        raise PlanError(f"{where}: declare instruction or steps, not both")
    if "instruction_detailed" in operation and "steps_detailed" in operation:
        raise PlanError(
            f"{where}: declare instruction_detailed or steps_detailed, not both"
        )
    if "instruction" not in operation and "steps" not in operation:
        raise PlanError(f"{where}: expected instruction or steps")
    if "instruction" in operation:
        _text(operation, "instruction", where)
    _text(operation, "instruction_detailed", where, optional=True)
    _steps(operation, "steps", where)
    _steps(operation, "steps_detailed", where)


def _diagram(table: dict, where: str) -> None:
    """A setup's or an operation's picture: an SVG file and its alt text."""
    if "diagram" not in table:
        return
    diagram = table["diagram"]
    where = f"{where}.diagram"
    if not isinstance(diagram, dict):
        raise PlanError(f"{where}: expected a table")
    _keys(diagram, {"file", "alt"}, where)
    _text(diagram, "file", where)
    _text(diagram, "alt", where)


def _turning_numbers(table: dict, keys: set[str], where: str) -> None:
    for key in keys & table.keys():
        value = table[key]
        if type(value) not in (int, float) or not isfinite(value):
            raise PlanError(f"{where}.{key}: expected a finite number")


def _turning_support(setup: dict, where: str) -> None:
    if "turning_support" not in setup:
        return
    support = setup["turning_support"]
    where = f"{where}.turning_support"
    if not isinstance(support, dict):
        raise PlanError(f"{where}: expected a table")
    numbers = {
        "chuck_z_mm",
        "centre_z_mm",
        "engage_z_mm",
        "offset_mm",
        "pad_width_mm",
    }
    _keys(support, {"kind"} | numbers, where)
    _choice(support, "kind", {"chuck_only", "tailstock", "follower"}, where)
    _turning_numbers(support, numbers, where)


def _turning_cuts(operation: dict, where: str) -> None:
    if "turning_cuts" not in operation:
        return
    numbers = {
        "start_z_mm",
        "end_z_mm",
        "start_diameter_mm",
        "end_diameter_mm",
        "max_radial_doc_mm",
        "feed_mm_rev",
        "minimum_diameter_mm",
        "max_deflection_mm",
        "kept_start_z_mm",
        "kept_end_z_mm",
    }
    for index, cut in enumerate(_tables(operation, "turning_cuts", where), 1):
        cut_where = f"{where}.turning_cuts[{index}]"
        _keys(cut, {"name", "phase"} | numbers, cut_where)
        _text(cut, "name", cut_where)
        _choice(cut, "phase", {"rough", "finish"}, cut_where)
        _turning_numbers(cut, numbers, cut_where)


@dataclass
class LoadedPlan:
    data: dict
    path: Path
    cad: CadData | None
    parameters: dict
    shop: Path | None
    shop_data: dict


def load_plan(path: Path) -> LoadedPlan:
    with path.open("rb") as source:
        plan = tomllib.load(source)
    parameters = plan.pop("parameters", {})
    if not isinstance(parameters, dict):
        raise PlanError("parameters: expected a table")
    for key, value in parameters.items():
        if key == "quantity" and (type(value) is not int or value < 1):
            raise PlanError("parameters.quantity: expected a positive integer")
        if type(value) not in (int, float):
            raise PlanError(f"parameters.{key}: expected a finite number")
        if not isfinite(value):
            raise PlanError(f"parameters.{key}: expected a finite number")
        if (
            key
            in {
                "blank_length_in",
                "blank_width_in",
                "blank_thickness_in",
            }
            and value <= 0
        ):
            raise PlanError(f"parameters.{key}: expected a positive number")
    cad = None
    config = plan.pop("cad", None)
    try:
        if config is not None:
            if not isinstance(config, dict):
                raise PlanError("cad: expected a table")
            _keys(config, {"file", "adapter", "part"}, "cad")
            cad = load_cad(
                path.parent / _text(config, "file", "cad"),
                parameters,
                _text(config, "adapter", "cad"),
                _text(config, "part", "cad"),
            )
        # Literal-only plans can also bind authored process parameters.
        context = cad or CadData({}, stock_requirement=None, source=path.resolve())
        # Analysis inputs retain full-precision numeric tokens. Printed fields
        # keep the existing text binding semantics.
        native = {
            "tools": check_fields("tool"),
            "setups": {"turning_support"} | check_fields("setup"),
            "operations": {"turning_cuts"} | check_fields("operation"),
        }

        def keep_numbers(table: dict, kind: str) -> None:
            for key in native[kind] & table.keys():
                table[key] = bind_data(
                    table[key], context, parameters, scalar_mode="native"
                )

        for tool in _tables(plan, "tools", "plan"):
            keep_numbers(tool, "tools")
        for setup in _tables(plan, "setups", "plan"):
            keep_numbers(setup, "setups")
            for operation in _tables(setup, "operations", "setup"):
                keep_numbers(operation, "operations")
        plan = bind_data(plan, context, parameters)
    except CadError as error:
        raise PlanError(str(error)) from error
    shop_path = None
    shop = {}
    if "shop" in plan:
        shop_path = (path.parent / _text(plan, "shop", "plan")).resolve()
        try:
            with shop_path.open("rb") as source:
                shop = tomllib.load(source)
        except (OSError, UnicodeError, tomllib.TOMLDecodeError) as error:
            raise PlanError(f"shop {shop_path}: {error}") from error
        plan.pop("shop")
    material_key = _text(plan, "material_key", "plan", optional=True)
    plan.pop("material_key", None)
    _keys(
        plan,
        {
            "title",
            "part",
            "revision",
            "material",
            "stock",
            "note",
            "tools",
            "setups",
            "turning_material",
            "milling_material",
        },
        "plan",
    )
    for key in ("title", "part", "revision", "material", "stock"):
        _text(plan, key, "plan")
    _text(plan, "note", "plan", optional=True)
    _text(plan, "turning_material", "plan", optional=True)
    _text(plan, "milling_material", "plan", optional=True)

    tool_ids = set()
    tool_refs = {}
    for index, tool in enumerate(_tables(plan, "tools", "plan"), 1):
        where = f"tools[{index}]"
        _keys(tool, {"id", "name", "description", "ref"} | check_fields("tool"), where)
        tool_id = _text(tool, "id", where)
        if "ref" in tool:
            ref = _text(tool, "ref", where)
            if shop_path is None:
                raise PlanError(f"{where}.ref: requires plan.shop")
            shared = _shop_record(shop, "tools", ref, f"{where}.ref")
            shared_where = f"shop.tools.{ref}"
            _keys(shared, {"name", "description"} | check_fields("tool"), shared_where)
            _text(shared, "description", shared_where)
            _text(shared, "name", shared_where, optional=True)
            for key in shared:
                if key not in tool:
                    tool[key] = shared[key]
            tool_refs[tool_id] = tool.pop("ref")
        _text(tool, "name", where, optional=True)
        _text(tool, "description", where)
        if tool_id in tool_ids:
            raise PlanError(f"{where}.id: duplicate tool {tool_id!r}")
        tool_ids.add(tool_id)

    for index, setup in enumerate(_tables(plan, "setups", "plan"), 1):
        where = f"setups[{index}]"
        _keys(
            setup,
            {
                "title",
                "machine",
                "machine_ref",
                "holding",
                "datum",
                "diagram",
                "operations",
                "inspection",
                "machine_kind",
                "turning_support",
            }
            | check_fields("setup"),
            where,
        )
        for key in ("title", "machine"):
            _text(setup, key, where)
        if "machine_ref" in setup:
            ref = _text(setup, "machine_ref", where)
            if shop_path is None:
                raise PlanError(f"{where}.machine_ref: requires plan.shop")
            _shop_record(shop, "machines", ref, f"{where}.machine_ref")
        _choice(setup, "machine_kind", {"lathe", "other"}, where)
        _turning_support(setup, where)
        for key in ("holding", "datum"):
            _text(setup, key, where, optional=True)
        _diagram(setup, where)
        checks = setup.get("inspection", [])
        if not isinstance(checks, list) or any(
            not isinstance(check, str) or not check.strip() for check in checks
        ):
            raise PlanError(
                f"{where}.inspection: expected an array of nonempty strings"
            )
        for op_index, operation in enumerate(_tables(setup, "operations", where), 1):
            op_where = f"{where}.operations[{op_index}]"
            _keys(
                operation,
                {
                    "tool",
                    "settings",
                    "instruction",
                    "instruction_detailed",
                    "steps",
                    "steps_detailed",
                    "rpm",
                    "feed",
                    "inspection",
                    "table",
                    "diagram",
                    "cut_kind",
                    "turning_cuts",
                }
                | check_fields("operation"),
                op_where,
            )
            _choice(operation, "cut_kind", {"longitudinal_turning", "other"}, op_where)
            _turning_cuts(operation, op_where)
            _cutting_settings(operation, op_where)
            _diagram(operation, op_where)
            tool_id = _text(operation, "tool", op_where, optional=True)
            if tool_id and tool_id not in tool_ids:
                raise PlanError(f"{op_where}.tool: unknown tool {tool_id!r}")
            if "settings" in operation:
                ref = _text(operation, "settings", op_where)
                if shop_path is None:
                    raise PlanError(f"{op_where}.settings: requires plan.shop")
                shared = _shop_record(shop, "settings", ref, f"{op_where}.settings")
                shared_where = f"shop.settings.{ref}"
                _keys(
                    shared,
                    {"tool", "material", "rpm", "feed"} | speeds.SETTING_FIELDS,
                    shared_where,
                )
                shared_tool = _text(shared, "tool", shared_where)
                shared_material = _text(shared, "material", shared_where)
                _cutting_settings(shared, shared_where)
                if (
                    not {
                        "rpm",
                        "sfm",
                        "feed",
                        "feed_mm_rev",
                        "chip_load_mm_per_tooth",
                    }
                    & shared.keys()
                ):
                    raise PlanError(f"{shared_where}: expected rpm or feed")
                if not tool_id or tool_refs.get(tool_id) != shared_tool:
                    raise PlanError(
                        f"{op_where}.settings: {ref!r} requires tool ref {shared_tool!r}"
                    )
                if not material_key or material_key != shared_material:
                    raise PlanError(
                        f"{op_where}.settings: {ref!r} requires "
                        f"material_key {shared_material!r}"
                    )
                try:
                    values = speeds.setting_values(
                        shared,
                        shared_where,
                        operation,
                        op_where,
                        setup.get("machine_ref"),
                        shop,
                    )
                except CheckError as error:
                    raise PlanError(str(error)) from error
                authored_feed = "feed" in operation
                for key, value in values.items():
                    if key not in operation:
                        operation[key] = value
                # milling_deflection reads the chip load behind a calculated
                # feed and the feed as printed; an authored feed has neither.
                if "chip_load_mm_per_tooth" in shared and not authored_feed:
                    operation["chip_load_mm_per_tooth"] = shared[
                        "chip_load_mm_per_tooth"
                    ]
                    operation["flutes"] = shared["flutes"]
                    operation["feed_mm_min"] = speeds.chip_load_feed(
                        shared, operation["rpm"]
                    )[1]
                operation.pop("settings")
            _work(operation, op_where)
            _text(operation, "inspection", op_where, optional=True)
            if "table" in operation:
                data = operation["table"]
                table_where = f"{op_where}.table"
                if not isinstance(data, dict):
                    raise PlanError(f"{table_where}: expected a table")
                _keys(data, {"columns", "rows"}, table_where)
                columns = data.get("columns")
                if (
                    not isinstance(columns, list)
                    or not columns
                    or any(
                        not isinstance(column, str) or not column.strip()
                        for column in columns
                    )
                ):
                    raise PlanError(
                        f"{table_where}.columns: expected nonempty column names"
                    )
                rows = data.get("rows")
                if (
                    not isinstance(rows, list)
                    or not rows
                    or any(
                        not isinstance(row, list)
                        or len(row) != len(columns)
                        or any(not isinstance(cell, str) for cell in row)
                        for row in rows
                    )
                ):
                    raise PlanError(
                        f"{table_where}.rows: expected nonempty rows matching the columns"
                    )
    return LoadedPlan(plan, path.resolve(), cad, parameters, shop_path, shop)


CSS = """
:root {
  --ink: #000;
  --paper: #fff;
  --rule: #ccc;
  --font: Arial, Helvetica, sans-serif;
  --body-size: 10.5pt;
  --title-size: 17pt;
  --heading-size: 12pt;
}
@page { size: Letter; margin: 0.5in; }
* { box-sizing: border-box; }
html, body { overflow-x: clip; }
body {
  color: var(--ink); background: var(--paper);
  font-family: var(--font); font-size: var(--body-size);
  line-height: 1.2; max-width: 7.5in; margin: 0 auto;
}
h1 { font-size: var(--title-size); margin: 0 0 0.08in; }
h2 { font-size: var(--heading-size); margin: 0.12in 0 0.04in; }
h1, h2 { overflow-wrap: break-word; min-width: 0; }
h1, h2, dt { break-after: avoid; }
p { margin: 0.05in 0; }
.meta { margin-bottom: 0.06in; }
dl { display: grid; grid-template-columns: 0.6in 1fr; gap: 0.02in 0.04in; margin: 0.04in 0; }
dt { font-weight: bold; }
dd { margin: 0; white-space: pre-wrap; }
table { width: 100%; border-collapse: collapse; margin: 0.06in 0; }
thead { display: table-header-group; break-after: avoid; }
tr { break-inside: avoid; }
th, td { text-align: left; vertical-align: top; padding: 0.015in 0.05in; }
th { border-bottom: 1px solid var(--ink); }
td { border-bottom: 1px solid var(--rule); }
th:first-child, td:first-child { padding-left: 0; }
th:last-child, td:last-child { padding-right: 0; }
.tools { table-layout: fixed; }
.tools td { width: 50%; }
.tools td:nth-child(2) { padding-left: 0.1in; }
.setup-heading { break-inside: avoid; break-after: avoid; }
.setup-heading h2 { display: flex; justify-content: space-between; gap: 0.12in; }
.machine { font-size: var(--body-size); font-weight: normal; text-align: right; }
.setup-diagram { margin: 0.08in 0; break-inside: avoid; }
.setup-diagram img { display: block; width: 100%; max-height: 4in; object-fit: contain; }
.operations { table-layout: fixed; break-before: avoid; }
.op-column { width: 6%; }
.work-column { width: 65%; }
.settings-column { width: 29%; }
.op-number { white-space: nowrap; font-variant-numeric: tabular-nums; }
.tool { font-weight: bold; }
.setting-value { font-variant-numeric: tabular-nums; }
.data-row { break-inside: auto; }
.data-row > td { padding: 0; border-bottom: 0; }
.data { margin: 0; }
.data th, .data td { font-variant-numeric: tabular-nums; }
.text { white-space: pre-wrap; }
ul { padding-left: 0.2in; margin: 0.06in 0; }
li { break-inside: avoid; }
@media screen { body { padding: 0.25in 0; } }
"""


def _html(value: str | int) -> str:
    return escape(str(value), quote=True)


# Printed only on sheets that use markup or steps, so plain sheets keep their
# exact bytes.
RICH_CSS = """\
.text ol, .text ul { margin: 0; padding-left: 0.22in; }
.text .gap { height: 1.2em; }
code { font-family: Consolas, "Courier New", monospace; font-size: 0.95em; }
.steps { margin: 0; padding-left: 0.22in; white-space: pre-wrap; }
.steps-spaced > li + li { margin-top: 0.04in; }
.step-check, .step-stop { padding-left: 0.05in; }
.step-check { border-left: 1px solid var(--ink); }
.step-stop { border-left: 3px solid var(--ink); font-weight: bold; }
"""

_CODE = re.compile(r"`([^`\n]+)`")
_BOLD = re.compile(r"\*\*(?=[^\s*])(.+?)(?<=[^\s*])\*\*")
# Emphasis opens before a word character and never closes after "(", so
# footnote marks such as "(*)" stay literal; it may close after other
# punctuation ("*Note:*").
_EM = re.compile(r"(?<![*\w])\*(?=\w)(.+?)(?<=[^\s*(])\*(?![*\w])")
# Bullets use "* " (asterisk, space), which emphasis cannot open. "- " never
# makes a list, so a minus-sign tolerance line always prints as typed.
_ITEM = re.compile(r"(\d+)\. (.*)|\* (.*)")
# A blank line beside a list: the list's block edges would swallow it.
_GAP = '<div class="gap"></div>'


def _inline(value: str) -> str:
    """Escape, then apply **bold**, *em* and `code`; code spans stay literal."""
    parts = _CODE.split(_html(value))
    for index, part in enumerate(parts):
        if index % 2:
            parts[index] = f"<code>{part}</code>"
            continue
        parts[index] = _EM.sub(r"<em>\1</em>", _BOLD.sub(r"<strong>\1</strong>", part))
    return "".join(parts)


def _rich(value: str) -> str:
    """Inline markup plus `1.`/`*` line lists; plain text renders as `_html`."""
    lines = value.split("\n")
    found = [_ITEM.fullmatch(line) for line in lines]
    if not any(found):
        return _inline(value)
    blocks: list[str] = []
    plain: list[str] = []
    items: list[str] = []
    tag = start = number = None

    def close_list() -> None:
        nonlocal tag
        if tag is None:
            return
        begin = f'<ol start="{start}">' if tag == "ol" and start != 1 else f"<{tag}>"
        blocks.append(begin + "".join(items) + f"</{tag}>")
        items.clear()
        tag = None

    def flush_plain() -> int:
        """Print the plain run; return its trailing blank lines, which print
        as gaps only if a list follows (none at the start or end)."""
        filled = [index for index, line in enumerate(plain) if line]
        if not filled:
            trailing = len(plain) if blocks else 0
            plain.clear()
            return trailing
        first, final = filled[0], filled[-1]
        if blocks:
            blocks.append(_GAP * first)
        blocks.append(_inline("\n".join(plain[first : final + 1])))
        trailing = len(plain) - 1 - final
        plain.clear()
        return trailing

    for line, item in zip(lines, found, strict=True):
        if item is None:
            close_list()
            plain.append(line)
            continue
        kind = "ol" if item[1] else "ul"
        if kind != tag:
            close_list()
            if plain:
                blocks.append(_GAP * flush_plain())
            tag, start = kind, int(item[1]) if item[1] else None
            number = start - 1 if start is not None else None
        text = _inline(item[2] if item[1] else item[3])
        if kind == "ul":
            items.append(f"<li>{text}</li>")
            continue
        # Numbers count on from the previous item; an authored number that
        # jumps ahead prints as written, and a repeated or lower one ("1.",
        # "1.", "1.") counts on, as in markdown.
        authored = int(item[1])
        if authored <= number:
            number += 1
            items.append(f"<li>{text}</li>")
            continue
        jump = f' value="{authored}"' if authored != number + 1 else ""
        number = authored
        items.append(f"<li{jump}>{text}</li>")
    close_list()
    if plain:
        flush_plain()
    return "".join(blocks)


STEP_LABELS = {"check": "Check:", "stop": "Stop:"}


class StepLayout(Enum):
    """How a step list prints; the value is its CSS class."""

    COMPACT = "steps"
    SPACED = "steps steps-spaced"


def _steps_html(steps: list[dict], layout: StepLayout) -> str:
    """Numbered steps; check and stop lines carry a label, rule and weight."""
    rows = []
    for step in steps:
        text = _inline(step["text"])
        label = STEP_LABELS.get(step["kind"])
        if label is None:
            rows.append(f"<li>{text}</li>")
            continue
        rows.append(
            f'<li class="step-{step["kind"]}"><strong>{label}</strong> {text}</li>'
        )
    return f'<ol class="{layout.value}">' + "".join(rows) + "</ol>"


# Printed only on sheets with an operation picture. The picture and its
# operation's row share one tbody so a page break cannot separate them.
OP_DIAGRAM_CSS = """\
.op-group { break-inside: avoid; }
.op-diagram > td { padding: 0; border-bottom: 0; }
"""


def used_diagrams(setup: dict, profile: Profile) -> dict[int, dict]:
    """The pictures a render of this setup opens: 0 is the setup's own, n its
    nth operation's. The CLI's output guard reads the same lookup."""
    if "setup_diagrams" not in profile.features:
        return {}
    tables = (setup, *setup["operations"])
    return {
        index: table["diagram"]
        for index, table in enumerate(tables)
        if "diagram" in table
    }


def _diagram_html(
    diagram: dict,
    where: str,
    figure_class: str,
    source_dir: Path,
    cad: CadData | None,
    parameters: dict,
) -> tuple[str, set[str]]:
    """Return a setup's or operation's picture figure and the roles it draws."""
    path = source_dir / diagram["file"]
    try:
        content = path.read_bytes()
        if cad is not None:
            from prechips.cad_diagrams import render_cad_svg

            content = render_cad_svg(content, cad, parameters)
        root = ElementTree.fromstring(content)
        if root.tag not in {"svg", "{http://www.w3.org/2000/svg}svg"}:
            raise ValueError("expected an SVG root element")
        drawn = palette.paint(root)
        if drawn:
            content = ElementTree.tostring(root, encoding="utf-8")
    except (OSError, ElementTree.ParseError, ValueError) as error:
        raise PlanError(
            f"{where}: cannot use SVG {diagram['file']!r}: {error}"
        ) from error
    image = base64.b64encode(content).decode("ascii")
    alt = _html(diagram["alt"])
    figure = (
        f'<figure class="{figure_class}">'
        f'<img src="data:image/svg+xml;base64,{image}" alt="{alt}">'
        "</figure>"
    )
    return figure, drawn


def render_traveler(loaded: LoadedPlan, *, profile: Profile = PRO) -> str:
    """Render a loaded plan; source paths remain relative to its TOML file."""
    plan = loaded.data
    source_dir = loaded.path.parent
    tools = {tool["id"]: tool for tool in plan["tools"]}
    lines = [
        "<!doctype html>",
        '<html lang="en"><head><meta charset="utf-8">',
        f"<title>{_html(plan['title'])}</title>",
    ]
    # Sheets using markup, steps or operation pictures get their extra CSS
    # spliced in here at the end.
    style_at = len(lines)
    lines += [
        f"<style>{CSS}</style></head><body>",
        f"<h1>{_html(plan['title'])}</h1>",
        '<div class="meta">',
        (f"<p>{_html(plan['part'])}; {_html(plan['revision'])}</p>"),
        (f"<p><strong>{_html(plan['material'])}.</strong> {_html(plan['stock'])}</p>"),
        "</div>",
    ]
    if "note" in plan:
        lines.append(f'<p class="text">{_html(plan["note"])}</p>')
    lines.append(
        '<table class="tools"><thead><tr><th colspan="2">Tools</th></tr></thead><tbody>'
    )
    tool_list = list(tools.values())
    for start in range(0, len(tool_list), 2):
        lines.append("<tr>")
        for tool in tool_list[start : start + 2]:
            lines.append(f'<td class="text">{_html(tool["description"])}</td>')
        if len(tool_list[start : start + 2]) == 1:
            lines.append("<td></td>")
        lines.append("</tr>")
    lines.append("</tbody></table>")
    # The palette's key prints here, once, listing the roles the pictures draw.
    key_at = len(lines)
    drawn: set[str] = set()
    rich = op_diagrams = False
    detailed = "detailed_instructions" in profile.features
    layout = StepLayout.SPACED if detailed else StepLayout.COMPACT
    pictures_on = "setup_diagrams" in profile.features
    operation_number = 0
    for setup_number, setup in enumerate(plan["setups"], 1):
        lines.append(
            '<section><div class="setup-heading">'
            f"<h2>Setup {setup_number} — {_html(setup['title'])}"
            f'<span class="machine">{_html(setup["machine"])}</span></h2>'
        )
        index = indexing.setting(
            loaded, setup, f"setup {setup_number} ({setup['title']})"
        )
        if "holding" in setup or "datum" in setup or index is not None:
            lines.append("<dl>")
            for key in ("holding", "datum"):
                if key in setup:
                    lines.append(f"<dt>{key.title()}:</dt><dd>{_html(setup[key])}</dd>")
            if index is not None:
                lines.append(
                    f"<dt>Index:</dt><dd>{_html(indexing.describe(index))}</dd>"
                )
            lines.append("</dl>")
        lines.append("</div>")
        # Profiles require the setup's picture only; operation pictures are
        # optional additions under the same feature.
        pictures = used_diagrams(setup, profile)
        where = f"setup {setup['title']!r}.diagram"
        if 0 in pictures:
            diagram, roles = _diagram_html(
                pictures[0],
                where,
                "setup-diagram",
                source_dir,
                loaded.cad,
                loaded.parameters,
            )
            drawn |= roles
            lines.append(diagram)
        elif pictures_on and "setup_diagrams" in profile.enforce:
            raise PlanError(f"{where}: required by profile {profile.name!r}")
        lines.append(
            '<table class="operations"><colgroup><col class="op-column">'
            '<col class="work-column"><col class="settings-column"></colgroup>'
            '<thead><tr><th scope="col">Op</th>'
            f'<th scope="col">Setup {setup_number} — Work</th>'
            '<th scope="col">Tool / settings</th></tr></thead><tbody>'
        )
        # The plain tbody just opened has no rows. An op picture and its row
        # get a tbody of their own ("closed" leaves none open), and no empty
        # tbody is left between the header and a group: that break point
        # would carry no break-avoid and could strand the heading.
        body = "empty"
        for op_index, operation in enumerate(setup["operations"], 1):
            operation_number += 10
            tool = tools[operation["tool"]] if "tool" in operation else None
            grouped = op_index in pictures
            if grouped:
                # Setup-picture styling, plus a class of its own so setup
                # pictures can still be counted apart.
                diagram, roles = _diagram_html(
                    pictures[op_index],
                    f"setup {setup_number} ({setup['title']}), Op {operation_number}"
                    " diagram",
                    "setup-diagram op-picture",
                    source_dir,
                    loaded.cad,
                    loaded.parameters,
                )
                drawn |= roles
                op_diagrams = True
                if body == "empty":
                    lines[-1] = lines[-1].removesuffix("<tbody>")
                lines.append(
                    ("</tbody>" if body == "rows" else "") + '<tbody class="op-group">'
                    f'<tr class="op-diagram"><td colspan="3">{diagram}</td></tr>'
                )
            # The detailed slot, when selected and authored, replaces the
            # compact one; either slot holds instruction text or steps.
            slots = [("instruction", "steps")]
            if detailed:
                slots.insert(0, ("instruction_detailed", "steps_detailed"))
            text_key, steps_key = next(
                pair for pair in slots if pair[0] in operation or pair[1] in operation
            )
            # Validation leaves exactly one of the two keys.
            if steps_key in operation:
                work = _steps_html(operation[steps_key], layout)
                rich = True
            if text_key in operation:
                text = _rich(operation[text_key])
                rich |= text != _html(operation[text_key])
                work = f'<div class="text">{text}</div>'
            reopen = "<tbody>" if body == "closed" and not grouped else ""
            lines.append(
                f'{reopen}<tr><td class="op-number">{operation_number}</td><td>{work}'
            )
            body = "rows"
            if "inspection" in operation:
                lines.append(
                    '<div class="text"><strong>Check:</strong> '
                    f"{_html(operation['inspection'])}</div>"
                )
            lines.append("</td><td>")
            if tool is not None:
                lines.append(
                    f'<div class="text tool">{_html(tool.get("name", tool["description"]))}</div>'
                )
            settings = []
            if "rpm" in operation:
                settings.append(f"{_html(operation['rpm'])} rpm")
            if "feed" in operation:
                settings.append(_html(operation["feed"]))
            if settings:
                lines.append(
                    '<div class="text setting-value">' + "; ".join(settings) + "</div>"
                )
            lines.append("</td></tr>")
            if grouped:
                lines.append("</tbody>")
                body = "closed"
            if "table" in operation:
                data = operation["table"]
                lines.append(
                    ("<tbody>" if body == "closed" else "")
                    + '<tr class="data-row"><td colspan="3">'
                    f'<table class="data" aria-label="Op {operation_number} data">'
                    "<thead><tr>"
                    + "".join(
                        f'<th scope="col">{_html(column)}</th>'
                        for column in data["columns"]
                    )
                    + "</tr></thead><tbody>"
                )
                for row in data["rows"]:
                    lines.append(
                        "<tr>"
                        + "".join(
                            f'<td class="text">{_html(cell)}</td>' for cell in row
                        )
                        + "</tr>"
                    )
                lines.append("</tbody></table></td></tr>")
                body = "rows"
        lines.append("</table>" if body == "closed" else "</tbody></table>")
        checks = setup.get("inspection", [])
        if len(checks) == 1:
            lines.append(
                f'<p class="text"><strong>Inspection:</strong> {_html(checks[0])}</p>'
            )
        elif checks:
            lines.append("<p><strong>Inspection</strong></p><ul>")
            for check in checks:
                lines.append(f'<li class="text">{_html(check)}</li>')
            lines.append("</ul>")
        lines.append("</section>")
    entries = [(role, text) for role, text in palette.LEGEND if role in drawn]
    if entries:
        key = base64.b64encode(palette.legend_svg(entries)).decode("ascii")
        alt = _html("Picture key: " + "; ".join(text for _, text in entries))
        lines.insert(
            key_at,
            '<figure class="picture-key" style="margin: 0.08in 0">'
            f'<img src="data:image/svg+xml;base64,{key}" alt="{alt}"'
            ' style="display: block; width: 100%">'
            "</figure>",
        )
    extra = (RICH_CSS if rich else "") + (OP_DIAGRAM_CSS if op_diagrams else "")
    if extra:
        lines[style_at] = f"<style>{CSS}{extra}</style></head><body>"
    lines.append("</body></html>\n")
    return "\n".join(lines)
