"""Read the small process-plan format and render a self-contained print sheet."""

import tomllib
from html import escape
from pathlib import Path


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
        _keys(tool, {"id", "description"}, where)
        tool_id = _text(tool, "id", where)
        _text(tool, "description", where)
        if tool_id in tool_ids:
            raise PlanError(f"{where}.id: duplicate tool {tool_id!r}")
        tool_ids.add(tool_id)

    for index, setup in enumerate(_tables(plan, "setups", "plan"), 1):
        where = f"setups[{index}]"
        _keys(
            setup,
            {"title", "machine", "holding", "datum", "operations", "inspection"},
            where,
        )
        for key in ("title", "machine", "holding", "datum"):
            _text(setup, key, where)
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
                {"tool", "instruction", "rpm", "feed", "inspection"},
                op_where,
            )
            tool_id = _text(operation, "tool", op_where)
            if tool_id not in tool_ids:
                raise PlanError(f"{op_where}.tool: unknown tool {tool_id!r}")
            _text(operation, "instruction", op_where)
            for key in ("feed", "inspection"):
                _text(operation, key, op_where, optional=True)
            if "rpm" in operation:
                rpm = operation["rpm"]
                if type(rpm) is not int or rpm <= 0:
                    raise PlanError(f"{op_where}.rpm: expected a positive integer")
    return plan


CSS = """
:root {
  --ink: #000;
  --paper: #fff;
  --rule: #666;
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
  line-height: 1.3; max-width: 7.5in; margin: 0 auto;
}
h1 { font-size: var(--title-size); margin: 0 0 0.12in; }
h2 { font-size: var(--heading-size); margin: 0.18in 0 0.06in; }
h1, h2 { overflow-wrap: break-word; min-width: 0; }
h1, h2, dt, thead { break-after: avoid; }
p { margin: 0.05in 0; }
.meta { margin-bottom: 0.12in; }
dl { margin: 0.05in 0 0.1in; }
dt { font-weight: bold; float: left; clear: left; margin-right: 0.08in; }
dd { margin: 0 0 0.04in; white-space: pre-wrap; }
table { width: 100%; border-collapse: collapse; margin: 0.06in 0; }
th, td {
  border: 1px solid var(--rule); padding: 0.045in 0.06in;
  text-align: left; vertical-align: top; overflow-wrap: anywhere;
}
thead { display: table-header-group; }
tr { break-inside: avoid; }
.tools td { width: 50%; }
.setup-heading { break-inside: avoid; break-after: avoid; }
.operation {
  break-inside: avoid; border-top: 1px solid var(--rule);
  padding: 0.04in 0; margin-top: 0.06in;
}
.text { white-space: pre-wrap; }
ul { padding-left: 0.2in; margin: 0.06in 0; }
li { break-inside: avoid; }
@media screen { body { padding: 0.25in 0; } }
"""


def _html(value: str | int) -> str:
    return escape(str(value), quote=True)


def render_traveler(plan: dict) -> str:
    """Render a plan returned by load_plan; authored strings are always plain text."""
    tools = {tool["id"]: tool["description"] for tool in plan["tools"]}
    lines = [
        "<!doctype html>",
        '<html lang="en"><head><meta charset="utf-8">',
        f"<title>{_html(plan['title'])}</title>",
        f"<style>{CSS}</style></head><body>",
        f"<h1>{_html(plan['title'])}</h1>",
        '<div class="meta">',
        (
            f"<p><strong>Part:</strong> {_html(plan['part'])}<br>"
            f"<strong>Revision:</strong> {_html(plan['revision'])}</p>"
        ),
        (
            f"<p><strong>Material:</strong> {_html(plan['material'])}<br>"
            f"<strong>Stock:</strong> {_html(plan['stock'])}</p>"
        ),
        "</div>",
    ]
    if "note" in plan:
        lines.append(f'<p class="text">{_html(plan["note"])}</p>')
    lines.append('<h2>Tools</h2><table class="tools"><tbody>')
    descriptions = list(tools.values())
    for index in range(0, len(descriptions), 2):
        cells = descriptions[index : index + 2]
        lines.append("<tr>" + "".join(f"<td>{_html(t)}</td>" for t in cells))
        if len(cells) == 1:
            lines.append("<td></td>")
        lines.append("</tr>")
    lines.append("</tbody></table>")
    for setup in plan["setups"]:
        lines.append(
            f'<section><div class="setup-heading"><h2>{_html(setup["title"])}</h2><dl>'
        )
        for key in ("machine", "holding", "datum"):
            lines.append(f"<dt>{key.title()}:</dt><dd>{_html(setup[key])}</dd>")
        lines.append("</dl>")
        lines.append("</div>")
        for operation in setup["operations"]:
            details = [f"<strong>{_html(tools[operation['tool']])}</strong>"]
            if "rpm" in operation:
                details.append(f"{_html(operation['rpm'])} rpm")
            if "feed" in operation:
                details.append(_html(operation["feed"]))
            lines.append('<div class="operation">')
            lines.append('<p class="text">' + " — ".join(details) + "</p>")
            lines.append(f'<p class="text">{_html(operation["instruction"])}</p>')
            if "inspection" in operation:
                lines.append(
                    '<p class="text"><strong>Check:</strong> '
                    f"{_html(operation['inspection'])}</p>"
                )
            lines.append("</div>")
        if setup.get("inspection"):
            lines.append("<p><strong>Inspection</strong></p><ul>")
            for check in setup["inspection"]:
                lines.append(f'<li class="text">{_html(check)}</li>')
            lines.append("</ul>")
        lines.append("</section>")
    lines.append("</body></html>\n")
    return "\n".join(lines)
