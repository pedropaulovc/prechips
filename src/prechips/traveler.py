"""Read the small process-plan format and render a self-contained print sheet."""

import base64
import tomllib
from html import escape
from pathlib import Path
from xml.etree import ElementTree

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


def load_plan(path: Path) -> dict:
    with path.open("rb") as source:
        plan = tomllib.load(source)
    _keys(
        plan,
        {"title", "part", "revision", "material", "stock", "note", "tools", "setups"},
        "plan",
    )
    for key in ("title", "part", "revision", "material", "stock"):
        _text(plan, key, "plan")
    _text(plan, "note", "plan", optional=True)

    tool_ids = set()
    for index, tool in enumerate(_tables(plan, "tools", "plan"), 1):
        where = f"tools[{index}]"
        _keys(tool, {"id", "name", "description"}, where)
        tool_id = _text(tool, "id", where)
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
                "holding",
                "datum",
                "diagram",
                "operations",
                "inspection",
            },
            where,
        )
        for key in ("title", "machine"):
            _text(setup, key, where)
        for key in ("holding", "datum"):
            _text(setup, key, where, optional=True)
        if "diagram" in setup:
            diagram = setup["diagram"]
            diagram_where = f"{where}.diagram"
            if not isinstance(diagram, dict):
                raise PlanError(f"{diagram_where}: expected a table")
            _keys(diagram, {"file", "alt"}, diagram_where)
            _text(diagram, "file", diagram_where)
            _text(diagram, "alt", diagram_where)
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
                {"tool", "instruction", "rpm", "feed", "inspection", "table"},
                op_where,
            )
            tool_id = _text(operation, "tool", op_where, optional=True)
            if tool_id and tool_id not in tool_ids:
                raise PlanError(f"{op_where}.tool: unknown tool {tool_id!r}")
            _text(operation, "instruction", op_where)
            for key in ("feed", "inspection"):
                _text(operation, key, op_where, optional=True)
            if "rpm" in operation:
                rpm = operation["rpm"]
                if type(rpm) is not int or rpm <= 0:
                    raise PlanError(f"{op_where}.rpm: expected a positive integer")
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
    return plan


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


def _diagram_html(setup: dict, profile: Profile, source_dir: Path) -> str:
    if "setup_diagrams" not in profile.features:
        return ""
    diagram = setup.get("diagram")
    where = f"setup {setup['title']!r}.diagram"
    if diagram is None:
        if "setup_diagrams" in profile.enforce:
            raise PlanError(f"{where}: required by profile {profile.name!r}")
        return ""
    path = source_dir / diagram["file"]
    try:
        content = path.read_bytes()
        root = ElementTree.fromstring(content)
        if root.tag not in {"svg", "{http://www.w3.org/2000/svg}svg"}:
            raise ValueError("expected an SVG root element")
    except (OSError, ElementTree.ParseError, ValueError) as error:
        raise PlanError(
            f"{where}: cannot use SVG {diagram['file']!r}: {error}"
        ) from error
    image = base64.b64encode(content).decode("ascii")
    alt = _html(diagram["alt"])
    return (
        '<figure class="setup-diagram">'
        f'<img src="data:image/svg+xml;base64,{image}" alt="{alt}">'
        "</figure>"
    )


def render_traveler(
    plan: dict, *, profile: Profile = PRO, source_dir: Path = Path(".")
) -> str:
    """Render a loaded plan; diagram paths are relative to the source plan directory."""
    tools = {tool["id"]: tool for tool in plan["tools"]}
    lines = [
        "<!doctype html>",
        '<html lang="en"><head><meta charset="utf-8">',
        f"<title>{_html(plan['title'])}</title>",
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
    operation_number = 0
    for setup_number, setup in enumerate(plan["setups"], 1):
        lines.append(
            '<section><div class="setup-heading">'
            f"<h2>Setup {setup_number} — {_html(setup['title'])}"
            f'<span class="machine">{_html(setup["machine"])}</span></h2>'
        )
        if "holding" in setup or "datum" in setup:
            lines.append("<dl>")
            for key in ("holding", "datum"):
                if key in setup:
                    lines.append(f"<dt>{key.title()}:</dt><dd>{_html(setup[key])}</dd>")
            lines.append("</dl>")
        lines.append("</div>")
        diagram = _diagram_html(setup, profile, source_dir)
        if diagram:
            lines.append(diagram)
        lines.append(
            '<table class="operations"><colgroup><col class="op-column">'
            '<col class="work-column"><col class="settings-column"></colgroup>'
            '<thead><tr><th scope="col">Op</th>'
            f'<th scope="col">Setup {setup_number} — Work</th>'
            '<th scope="col">Tool / settings</th></tr></thead><tbody>'
        )
        for operation in setup["operations"]:
            operation_number += 10
            tool = tools[operation["tool"]] if "tool" in operation else None
            lines.append(
                f'<tr><td class="op-number">{operation_number}</td>'
                f'<td><div class="text">{_html(operation["instruction"])}</div>'
            )
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
            if "table" in operation:
                data = operation["table"]
                lines.append(
                    '<tr class="data-row"><td colspan="3">'
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
        lines.append("</tbody></table>")
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
    lines.append("</body></html>\n")
    return "\n".join(lines)
