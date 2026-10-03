"""Printable bench instructions from the validated bundle and fresh rule findings.

Unlike the hand-curated references, continuations belong to their setup. Tables
flow safely across Letter pages; no fixed-height box can hide an instruction.
Computed symmetry may compress checkpoints, but never substitutes a contour.
"""
from __future__ import annotations

import math
import re
from html import escape

from .rules.resolution import MANUAL, resolve


_CSS = """@page { size: Letter portrait; margin: .4in .4in .55in; }
* { box-sizing: border-box; }
body { margin: 0; color: #000; background: #fff; font: 8pt/1.25 Arial, sans-serif; }
.page { break-after: page; page-break-after: always; }
.page:last-child { break-after: auto; page-break-after: auto; }
h1 { margin: 0; font-size: 12pt; } h2 { font-size: 9pt; margin: 5pt 0 2pt; border-bottom: 1px solid #000; break-after: avoid; }
p { margin: 2pt 0; } .meta { display: flex; justify-content: space-between; gap: 8pt; }
.banner { border: 2px solid #000; text-align: center; font-weight: bold; padding: 2pt; margin: 3pt 0; }
.byst p { margin-left: 1.3em; text-indent: -1.3em; }
table { width: 100%; border-collapse: collapse; margin: 2pt 0; table-layout: fixed; }
th, td { border: 1px solid #555; padding: 2pt; text-align: left; vertical-align: top; overflow-wrap: anywhere; }
th { background: #eee; } thead { display: table-header-group; }
tr { break-inside: avoid; page-break-inside: avoid; } .operations { font-size: 7pt; }
.foot { text-align: right; font-size: 7pt; margin-top: 5pt; break-inside: avoid; }
.print-footer { display: none; }
@media print { .foot { display: none; } .print-footer { display: block; position: fixed; bottom: -.25in; right: 0; font-size: 7pt; } }
@media screen { body { max-width: 7.7in; margin: 12pt auto; } .page { margin-bottom: 24pt; } }
"""
_GLYPHS = {"error": "✗", "warn": "!", "unknown": "?", "unsupported": "?"}
_METADATA = {"cite", "source", "paths", "features", "step_sha256", "inspection_methods"}
_REFERENCE_FIELDS = {"fixture", "parallels", "supports", "support", "riser", "tool", "holder", "gauge"}


def _status(finding):
    status = finding.get("status") if isinstance(finding, dict) else finding.status
    return getattr(status, "value", status)


def _field(finding, name, default=None):
    if isinstance(finding, dict):
        return finding.get(name, default)
    return getattr(finding, "sentence" if name == "message" else name, default)


def _text(value):
    if value is None or value == "unknown":
        return "?"
    if value == "not_applicable":
        return "—"
    return str(value).replace("_", " ")


def _number(value, precision):
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return _text(value)
    if not math.isfinite(value) or not isinstance(precision, int):
        return "?"
    result = f"{value:.{precision}f}"
    return result.removeprefix("-") if float(result) == 0 else result


def _p(text, css=""):
    attribute = f' class="{css}"' if css else ""
    return f"<p{attribute}>{escape(str(text))}</p>"


def _table(headings, rows, css="", widths=None):
    columns = ""
    if widths:
        columns = "<colgroup>" + "".join(f'<col style="width:{w}%">' for w in widths) + "</colgroup>"
    result = [f'<table class="{css}">', columns, "<thead><tr>"]
    result.extend(f"<th>{escape(h)}</th>" for h in headings)
    result.append("</tr></thead><tbody>")
    for row in rows:
        result.append("<tr>")
        for cell in row:
            lines = cell if isinstance(cell, (list, tuple)) else [cell]
            result.append("<td>" + "<br>".join(escape(str(line)) for line in lines) + "</td>")
        result.append("</tr>")
    result.append("</tbody></table>")
    return "".join(result)


class _Traveler:
    def __init__(self, bundle, findings, report, approval):
        self.bundle = bundle
        self.plan = bundle.plan
        self.features = bundle.features.get("features", {})
        self.general_precision = bundle.features.get("precision")
        self.findings = sorted(findings, key=lambda f: (_field(f, "rule", ""), _field(f, "subject", "")))
        self.records = {(_field(f, "rule"), _field(f, "subject")): _field(f, "numbers", {}) for f in self.findings}
        self.report = report
        self.approval = approval or {}
        evidence = self.approval.get("first_article")
        current_hash = report.get("hash")
        self.checked = (report.get("verification") == "checked"
                        and self.approval.get("approved") is True
                        and isinstance(current_hash, str) and re.fullmatch(r"[0-9a-f]{64}", current_hash) is not None
                        and self.approval.get("hash") == current_hash
                        and isinstance(evidence, str) and bool(evidence.strip())
                        and evidence.strip().lower() != "unknown" and not self.approval.get("warnings"))
        self.units = bundle.features.get("units", "unknown")
        self.pages = []
        self.references = {}
        for finding in self.findings:
            if _field(finding, "rule") == "tool_resolves":
                subject = _field(finding, "subject", "")
                if ":" not in subject:
                    self.references[subject] = self.reference(subject)

    def precision(self, feature=None, dimension=None):
        overrides = self.features.get(feature, {}).get("precision", {})
        if isinstance(overrides, dict):
            return overrides.get(dimension, self.general_precision)
        return overrides

    def value(self, value, feature=None, dimension=None):
        if dimension in {"op", "before_ops", "after_op", "retouch_after", "passes"}:
            if isinstance(value, (list, tuple)):
                return ", ".join(map(_text, value))
            return _text(value)
        precision = self.precision(feature, dimension)
        if isinstance(value, dict):
            return "; ".join(f"{_text(k)}: {self.value(v, feature, k)}" for k, v in value.items()
                             if not self.metadata(k)) or "—"
        if isinstance(value, (list, tuple)):
            return " / ".join(self.value(v, feature, dimension) for v in value) or "—"
        if isinstance(value, bool):
            return "yes" if value else "no"
        return _number(value, precision)

    def recipe(self, value, feature=None, dimension=None):
        """Manual settings stay usable when a drawing has no precision contract."""
        if dimension in {"op", "before_ops", "after_op", "retouch_after", "passes"}:
            return self.value(value, feature, dimension)
        if isinstance(value, dict):
            return "; ".join(f"{_text(k)}: {self.recipe(v, feature, k)}" for k, v in value.items() if not self.metadata(k)) or "—"
        if isinstance(value, (list, tuple)):
            return " / ".join(self.recipe(v, feature, dimension) for v in value) or "—"
        if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) and not isinstance(self.precision(feature, dimension), int):
            return f"{value:g}"
        return self.value(value, feature, dimension)

    @staticmethod
    def metadata(key):
        return key in _METADATA or key.endswith(("_cite", "_verify")) or key == "verify"

    def reference(self, reference, category=None):
        if reference in (None, "unknown", "none", "not_applicable"):
            return _text(reference)
        if not isinstance(reference, str):
            return "?"
        item = resolve(self.bundle, category, reference)
        root, _, member = reference.partition("/")
        raw = self.bundle.inventory.get(category, {}).get(root, {}) if category else {}
        if not raw:
            raw = next((items[root] for items in self.bundle.inventory.values()
                        if isinstance(items, dict) and root in items), {})
        record = item or raw
        name = record.get("name", record.get("label"))
        if not name:
            if category == "machines" or root in self.bundle.inventory.get("machines", {}):
                name = root
            else:
                name = _text(root.replace("-", " ")) if record.get("kind") == "accessory" else _text(record.get("kind", root.replace("-", " ")))
                name = name.removesuffix(" set")
        if member:
            if record.get("kind") == "micrometer_set":
                member = member.removesuffix("in") + " in"
            else:
                member = re.sub(r"(\d+)-(\d+)in", r"\1/\2 in", member)
                member = re.sub(r"-(\d+)fl", r" \1-flute", member)
            if record.get("kind") == "center_drill_set" and member.isdigit():
                member = "#" + member
            name = f"{member} {name}"
        elif item:
            for field, unit in (("tip_in", "in"), ("dia_in", "in"), ("dia_mm", "mm")):
                size = record.get(field)
                if isinstance(size, (int, float)):
                    name = f"{size:g} {unit} {name}"
                    break
        if record.get("standard"):
            name = f"{record['standard']} {name}"
        return f"{name} (missing)" if item is None else str(name)

    def bench(self, text):
        text = str(text) if text is not None else "?"
        for reference, label in sorted(self.references.items(), key=lambda pair: -len(pair[0])):
            text = text.replace(reference, label)
        text = re.sub(r"\b[0-9a-fA-F]{32,64}\b", "", text)
        text = re.sub(r"https?://\S+|(?:[A-Za-z]:[\\/]|(?:\.?\.?/)?(?:cad|src|examples|harmonic-analyzer)/)\S+", "", text)
        text = text.replace("PLAN.md", "approved plan")
        text = re.sub(r"(?<!\w)(?:[A-Za-z]:[\\/]|(?:\.{1,2}[\\/])|(?:[\w.-]+[\\/]){2,})[^\s;,]+", "", text)
        for rule in {key[0] for key in self.records}:
            text = text.replace(rule, _text(rule))
        return _text(text)

    def paragraphs(self, mapping, recipes=False):
        parts = []
        for key, value in mapping.items():
            if self.metadata(key):
                continue
            if key in _REFERENCE_FIELDS:
                value = self.reference(value)
            elif key == "top_feature":
                value = _text(value)
            else:
                value = (self.recipe if recipes else self.value)(value, dimension=key)
            parts.append(f"{_text(key)}: {value}")
        return self.bench("; ".join(parts))

    def issues(self, findings, warnings=()):
        lines = []
        seen = set()
        for finding in findings:
            glyph = _GLYPHS.get(_status(finding))
            if glyph:
                line = f"{glyph} {self.bench(_field(finding, 'message', '?'))}"
                if line not in seen:
                    seen.add(line)
                    lines.append(_p(line))
        for warning in warnings:
            line = f"! {self.bench(warning)}"
            if line not in seen:
                seen.add(line)
                lines.append(_p(line))
        if not lines:
            lines.append(_p("No reported errors, warnings or unresolved checks for this section."))
        return '<h2>BEFORE YOU START</h2><div class="byst">' + "".join(lines) + "</div>"

    def setup_findings(self, setup):
        sid = setup["id"]
        features = {op.get("feature") for op in setup["ops"]}
        result = []
        for finding in self.findings:
            subject = _field(finding, "subject", "")
            rule = _field(finding, "rule")
            numbers = _field(finding, "numbers", {})
            if subject == sid or subject.startswith(sid + ":"):
                result.append(finding)
            elif subject.split(":")[0] in features and rule != "tool_resolves":
                endpoints = numbers.get("endpoints", [])
                checks = numbers.get("checks", [])
                owners = {str(c.get("op", "")).split(":")[0] for c in checks}
                if numbers.get("op"):
                    owners.add(str(numbers["op"]).split(":")[0])
                if endpoints:
                    owners.update(e.get("setup") for e in endpoints)
                if not owners or sid in owners:
                    result.append(finding)
        return result

    def dro(self, setup):
        numbers = self.records.get(("zero_check", setup["id"]), {})
        authored = setup.get("zero", {})
        settings = self.plan.get("dro", {})
        mode = "radius" if settings.get("radius_mode") is True else "diameter" if settings.get("radius_mode") is False else "?"
        pieces = [f"<h2>DRO ZERO — frame {escape(_text(setup.get('frame')))}, {escape(_text(self.units))}, {escape(_text(settings.get('mode')).upper())}, {mode} mode</h2>"]
        pieces.append(_p("Direction (§6.2): " + self.paragraphs(settings.get("direction", {}))
                         + ". Axis Set in ABS (§7.4) changes the datum; never use Preset (distance-to-go, §8.1). "
                         "Jog without touching again. A mirrored reading means STOP, correct Direction and redo touch / set / check."))
        axes = numbers.get("axes", {})
        top_feature = setup.get("stock_state", {}).get("top_feature")
        top_dimension = next((d for d in ("length", "thickness", "height") if d in self.features.get(top_feature, {})), None)
        rows = []
        for axis in ("x", "y", "z"):
            if axis not in authored and axis not in axes:
                continue
            computed = axes.get(axis, {})
            touch = dict(authored.get(axis, {}))
            touch.pop("check_jog_mm", None)
            touch.pop("retouch_after", None)
            for key in ("radius_mm", "paper_mm", "edge_mm", "method"):
                if key in computed:
                    touch[key] = computed[key]
            feature = top_feature if axis == "z" else None
            dimension = top_dimension if axis == "z" else None
            if "edge_mm" in touch:
                touch["edge_mm"] = self.recipe(touch["edge_mm"], feature, dimension)
            expected = self.recipe(computed.get("check_reading"), feature, dimension)
            mirrored = self.recipe(computed.get("mirrored_reading"), feature, dimension)
            if expected == "?" and computed.get("check_expression"):
                expected += " (" + self.bench(computed["check_expression"]) + ")"
            if mirrored == "?" and computed.get("mirrored_expression"):
                mirrored += " (" + self.bench(computed["mirrored_expression"]) + ")"
            jog = computed.get("jog_mm")
            jog_direction = "−" if isinstance(jog, (int, float)) and jog < 0 else "+"
            rows.append((axis.upper(), self.paragraphs(touch, recipes=True), self.recipe(computed.get("axis_set"), feature, dimension),
                         jog_direction + axis.upper() + " " + self.recipe(abs(jog) if isinstance(jog, (int, float)) else jog) + " physical", expected, mirrored))
        pieces.append(_table(["axis", "touch / compensation", "Axis Set", "jog, no touch", "must read", "mirrored: STOP"], rows, widths=[5, 43, 13, 13, 13, 13]))
        transfer = authored.get("transfer")
        if transfer:
            pieces.append(_p("Datum transfer: " + self.paragraphs(transfer)))
        retouches = {}
        for record in numbers.get("retouch", []):
            key = (self.recipe(record.get("top_z"), top_feature, top_dimension),
                   self.recipe(record.get("paper_mm")), self.recipe(record.get("axis_set"), top_feature, top_dimension))
            retouches.setdefault(key, []).append(_text(record.get("op")))
        for (top, paper, axis_set), ops in retouches.items():
            pieces.append(_p(f"After ops {', '.join(ops)}, re-touch {self.bench(setup.get('stock_state', {}).get('top_feature', 'top'))} "
                             f"at Z {top}, paper {paper}: Axis Set Z {axis_set} before the next tool's operation."))
        for touch in numbers.get("tool_touches", []):
            pieces.append(_p("Tool touch-off: " + self.paragraphs(touch, recipes=True)))
        for axis in axes.values():
            if axis.get("note"):
                pieces.append(_p(self.bench(axis["note"])))
        return "".join(pieces)

    def endpoint(self, setup, op):
        numbers = self.records.get(("blind_depth", op.get("feature")), {})
        return next((e for e in numbers.get("endpoints", [])
                     if e.get("setup") == setup["id"] and str(e.get("op")) == str(op["op"])), None)

    def tip(self, setup, op):
        feature = op.get("feature")
        endpoint = self.endpoint(setup, op)
        if endpoint:
            parts = [f"entry {self.value(endpoint.get('entry_z'), feature, 'depth')} → tip {self.value(endpoint.get('tip_z'), feature, 'depth')}"]
            for key in ("exit_face", "local_thickness", "point_mm", "lead_mm", "exit_mm", "depth_mm"):
                if key in endpoint and endpoint[key] != "not_applicable":
                    parts.append(f"{_text(key)} {self.value(endpoint[key], feature, 'depth')}")
            return parts
        parts = []
        for key in ("to_z", "z_from", "z_to", "depth_mm", "exit_mm", "to_z_band"):
            if key in op:
                dimension = next((d for d in ("depth", "length", "thickness") if d in self.features.get(feature, {})), "depth")
                parts.append(f"{_text(key)} {self.value(op[key], feature, dimension)}")
        return parts or ["—" if op.get("do") in MANUAL else "? tip endpoint"]

    def inspection(self, setup, op):
        rows = []
        feature = op.get("feature")
        definition = self.features.get(feature, {})
        for requirement, reference in op.get("checks", {}).items():
            finding = next((f for f in self.findings if _field(f, "rule") == "inspection"
                            and _field(f, "subject") == f"{feature}:{requirement}"), None)
            glyph = _GLYPHS.get(_status(finding)) if finding else "?"
            target = definition.get(requirement)
            method = op.get("inspection_methods", {}).get(requirement)
            datums = definition.get("position_datums") if requirement == "position_dia" else None
            line = f"{glyph + ' ' if glyph else ''}{_text(requirement)} {self.value(target, feature, requirement)}: {self.reference(reference, 'gauges')}"
            if datums:
                line += " to " + "|".join(map(_text, datums))
            if method:
                line += "; " + self.bench(method)
            rows.append(line)
        if op.get("inspection_note"):
            rows.append(self.bench(op["inspection_note"]))
        return rows or ["—"]

    def operations(self, setup, ops):
        rows = []
        citations = []
        for op in ops:
            feature = op.get("feature")
            numbers = self.records.get(("speeds_feeds", f"{setup['id']}:{op['op']}"), {})
            manual = op.get("do") in MANUAL
            tools = [self.reference(op.get("tool"), "tools") + " / " + self.reference(op.get("holder"), "holders")]
            if manual and "tool" not in op:
                tools = ["—"]
            action = [_text(op.get("do"))]
            if op.get("note"):
                action.append(self.bench(op["note"]))
            for key in ("rough_allowance_mm", "stock_to_leave_mm", "passes"):
                if key in op:
                    action.append(f"{_text(key)}: {self.recipe(op[key], feature, key)}")
            feed = numbers.get("feed_mm_min", numbers.get("feed_mm_rev"))
            feed_units = " / rev" if "feed_mm_rev" in numbers else " / min"
            feed_text = "—" if manual else self.recipe(feed) + (" mm" + feed_units if isinstance(feed, (int, float)) else "")
            rows.append((_text(op["op"]), action, _text(feature), tools,
                         "—" if manual else _number(numbers.get("rpm"), 0), feed_text,
                         self.tip(setup, op), _text(op.get("direction", "not_applicable" if manual or op.get("do") in {"spot", "drill", "ream", "tap"} else None)), self.inspection(setup, op)))
            headroom = self.records.get(("headroom", setup["id"]), {})
            stack = next((s for s in headroom.get("stacks", []) if s.get("op") == op["op"]), {})
            if isinstance(stack.get("margin_mm"), (int, float)):
                tools.append(f"{'? ' if stack.get('verify') else ''}headroom {self.value(stack['margin_mm'])} mm")
            jaw_clearance = headroom.get("cut_tip_above_jaws_mm", {}).get(str(op["op"]))
            if isinstance(jaw_clearance, (int, float)):
                rows[-1][6].append(f"? tip above jaws {self.value(jaw_clearance)} mm; access unproved")
            finding = next((f for f in self.findings if _field(f, "rule") == "speeds_feeds" and _field(f, "subject") == f"{setup['id']}:{op['op']}"), None)
            if finding:
                for cite in _field(finding, "cite", []):
                    citation = self.bench(cite)
                    if citation and citation not in citations:
                        citations.append(citation)
        result = "<h2>OPERATIONS — RPM / feed are starting points, not limits</h2>"
        result += _table(["op", "do / instructions", "feature", "tool / holder", "rpm", "feed", "Z (tool tip)", "direction", "inspection"], rows, "operations", [4, 20, 10, 15, 5, 7, 18, 7, 14])
        if citations:
            result += _p("RPM / feed source: " + "; ".join(citations))
        return result

    def coordinates(self, setup):
        numbers = self.records.get(("coordinates", setup["id"]), {})
        rows = []
        for record in numbers.get("rows", []):
            feature = record.get("feature")
            coordinates = record.get("setup", ["unknown"] * 3)
            if not isinstance(coordinates, (list, tuple)):
                coordinates = ["unknown"] * 3
            coordinates = list(coordinates) + ["unknown"] * (3 - len(coordinates))
            x = record.get("x_target_mm", coordinates[0])
            x_dimension = "dia" if "x_target_mm" in record else "at"
            note = []
            for key in ("point", "note", "local_from"):
                if key in record:
                    note.append(f"{_text(key)}: {self.bench(self.value(record[key]))}")
            z = _number(coordinates[2], record["precision"]) if "precision" in record else self.value(coordinates[2], feature, "at")
            rows.append((_text(feature), self.value(x, feature, x_dimension), self.value(coordinates[1], feature, "at"), z, note or ["—"]))
        pieces = [f"<h2>COORDINATES — frame {escape(_text(setup.get('frame')))}, {escape(_text(self.units))}; feature reference points</h2>"]
        if rows:
            pieces.append(_table(["feature", "X", "Y", "Z / station", "note"], rows))
            pieces.append(_p("These reference points are not tool-tip endpoints. Use the operation's tip Z and the cutter-centre continuation for cutting."))
        else:
            pieces.append(_p("? No resolved feature coordinates; use the explicit operation targets only where their local provenance is stated."))
        if any(isinstance(numbers.get(key), list) and numbers[key] for key in ("arc_table", "line_table", "profiles", "contours")):
            pieces.append(_p("Cutter-centre contours and exact joins follow this setup on continuation pages. Feature centres above are not profile cutter positions."))
        for key in ("route_limit", "binding", "retain_web_mm", "x_display", "tool_nose_radius_mm", "fitted_model_length_mm"):
            if key in numbers:
                pieces.append(_p(f"{_text(key)}: {self.bench(self.value(numbers[key]))}"))
        return "".join(pieces)

    def arc_rows(self, arc):
        """Compress only reflections already present in computed checkpoints."""
        records = arc.get("rows", [])
        centre = arc.get("centre_setup_xy")
        if not records or not isinstance(centre, list) or len(centre) != 2:
            return records, ""
        numeric = lambda v: isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)
        points = [r.get("setup_xy") for r in records]
        if not all(numeric(v) for v in centre) or not all(isinstance(p, list) and len(p) == 2 and all(numeric(v) for v in p) for p in points):
            return records, ""
        tips = [r.get("tip_z", arc.get("tip_z")) for r in records]
        if any(tip != tips[0] for tip in tips):
            return records, ""
        key = lambda x, y: (round(x, 7), round(y, 7))
        supplied = {key(*p) for p in points}
        axes = [axis for axis in range(2) if all(
            key(2 * centre[0] - p[0] if axis == 0 else p[0],
                2 * centre[1] - p[1] if axis == 1 else p[1]) in supplied for p in points)]
        if not axes:
            return records, ""
        selected = [r for r, p in zip(records, points) if all(p[axis] >= centre[axis] - 1e-7 for axis in axes)]
        if not selected or len(selected) == len(records):
            return records, ""
        names = " / ".join("XY"[axis] for axis in axes)
        note = (f"Equivalent {names} reflections omitted. Mirror the listed coordinates about "
                f"centre X {self.value(centre[0])}, Y {self.value(centre[1])}; not about a guessed datum. "
                "Keep the operation's cut direction and stated interpolation.")
        return selected, note

    def contours(self, setup):
        numbers = self.records.get(("coordinates", setup["id"]), {})
        tables = []
        arc_ops = set()
        for arc in numbers.get("arc_table", []) if isinstance(numbers.get("arc_table"), list) else []:
            feature = arc.get("feature")
            arc_ops.add(arc.get("op"))
            operation = next((o for o in setup["ops"] if o["op"] == arc.get("op")), {})
            records, symmetry = self.arc_rows(arc)
            rows = []
            for record in records:
                xy = record.get("setup_xy", [record.get("x", "unknown"), record.get("y", "unknown")])
                rows.append((self.value(record.get("angle_deg"), feature, "angle_deg"),
                             self.value(xy[0], feature, "at"), self.value(xy[1], feature, "at"),
                             self.value(record.get("tip_z", arc.get("tip_z", operation.get("to_z"))), feature, "depth")))
            title = f"Op {_text(arc.get('op'))} — {_text(feature)}"
            description = self.paragraphs({k: v for k, v in arc.items() if k not in {"rows", "feature", "op", "centre_model_xy"}})
            if arc.get("rows"):
                angles = [r.get("angle_deg") for r in arc["rows"]]
                description += f"; full computed arc range: {self.value(angles[0])} → {self.value(angles[-1])}°"
            if symmetry:
                description += "; " + symmetry
            tables.append((title, description, ["angle °", "X", "Y", "Z tip"], rows))
        for line in numbers.get("line_table", []):
            rows = [(str(i + 1), self.value(xy[0]), self.value(xy[1]), self.value(line.get("tip_z")))
                    for i, xy in enumerate(line.get("setup_xy", []))]
            description = self.paragraphs({k: v for k, v in line.items() if k not in {"setup_xy", "model_xy"}})
            tables.append((f"Op {_text(line.get('op'))} — exact line joins", description, ["join order", "X", "Y", "Z tip"], rows))
        for profile in numbers.get("profiles", []):
            if profile.get("op") in arc_ops and profile.get("contour", {}).get("method") == "arc_table":
                continue
            points = profile.get("cutter_centre", [])
            if not isinstance(points, list):
                continue
            feature = profile.get("feature")
            headings = ["point order", "X", "Y", "Z tip"]
            rows = []
            for i, point in enumerate(points):
                z = self.value(profile.get("to_z"), feature, "depth")
                if isinstance(point, dict):
                    rows.append((self.value(point.get("angle_deg"), feature, "angle_deg"),
                                 self.value(point.get("x"), feature, "at"), self.value(point.get("y"), feature, "at"), z))
                    headings[0] = "angle °"
                elif len(point) == 2 and all(isinstance(p, list) for p in point):
                    headings = ["pass", "X from", "Y from", "X to", "Y to", "Z tip"]
                    rows.append((str(i + 1), *(self.value(v, feature, "at") for p in point for v in p), z))
                else:
                    rows.append((str(i + 1), self.value(point[0], feature, "at"), self.value(point[1], feature, "at"), z))
            description = self.paragraphs({k: v for k, v in profile.items() if k not in {"cutter_centre", "model", "rows"}})
            tables.append((f"Op {_text(profile.get('op'))} — {_text(feature)}", description, headings, rows))
        for contour in numbers.get("contours", []):
            if not isinstance(contour, dict) or contour.get("method") != "axial_table":
                continue
            feature = contour.get("feature")
            rows = [(self.value(r.get("x_target_mm"), feature, "dia"), self.value(r.get("z_mm"), feature, "height"))
                    for r in contour.get("rows", [])]
            description = self.paragraphs({k: v for k, v in contour.items() if k != "rows"})
            description += "; nominal profile only: apply a confirmed tool-nose compensation, never invent it."
            tables.append((f"Op {_text(contour.get('op'))} — {_text(feature)}", description, ["X displayed target", "Z station"], rows))
        content = ""
        used = 0
        for title, description, headings, rows in tables:
            for start in range(0, max(1, len(rows)), 30):
                chunk = rows[start:start + 30]
                cost = len(chunk) + 4 + math.ceil(len(description) / 110)
                if content and used + cost > 48:
                    self.pages.append((f"Setup {setup['id']} contour continuation", content))
                    content, used = "", 0
                if not content:
                    content = "<h2>CONTOUR CONTINUATION — nominal targets</h2>"
                    content += _p(f"Frame {_text(setup.get('frame'))}, {_text(self.units)}. Cutter-centre X/Y for mills; displayed X/Z profile for lathes, subject to the stated tool-nose compensation.")
                    content += _p("Nominal checkpoints do not prove cutter access or workholding. Follow the setup's hold / release instructions.")
                content += _p(title + (" (continued)" if start else "")) + _p(description)
                content += _table(headings, chunk) if rows else _p("? Contour coordinates unresolved.")
                used += cost
        if content:
            self.pages.append((f"Setup {setup['id']} contour continuation", content))

    def render(self):
        setups = self.plan.get("setups", [])
        routed = {id(f) for setup in setups for f in self.setup_findings(setup)}
        header_findings = [f for f in self.findings if id(f) not in routed]
        header = self.issues(header_findings, self.approval.get("warnings", []))
        if self.plan.get("drawing", {}).get("revision", "unknown") == "unknown":
            header += _p("? Drawing revision is not confirmed.")
        if self.bundle.features.get("step_sha256", "unknown") == "unknown":
            header += _p("? No checked STEP / drawing pair is bound to this plan.")
        header += _p("Drawing material / finish: " + self.paragraphs(self.bundle.features.get("material", {}), recipes=True))
        header += "<h2>STOCK AND ROUTE</h2>" + _p(self.paragraphs(self.plan.get("stock", {}), recipes=True))
        header += _table(["setup", "starts from", "machine / fixture", "purpose"],
                         [(s["id"], _text(s.get("stock_in")), self.reference(s.get("machine"), "machines") + " / " + self.reference(s.get("hold", {}).get("fixture"), "fixtures"), self.bench(s.get("note", "? setup purpose"))) for s in setups])
        requirements = []
        for feature, definition in self.features.items():
            values = [f"{_text(d)} {self.value(definition.get(d), feature, d)}" for d in definition.get("requirements", [])]
            requirements.append((_text(feature), "; ".join(values) or "No drawing requirements declared."))
        header += "<h2>DRAWING REQUIREMENTS</h2>" + _table(["feature", "requirement / acceptance band"], requirements)
        header += _p("Holding and coordinates are declared or nominal M1 facts, not rendered geometry or a cutter-access proof. Unknown fields are ?. Keep the drawing at the bench.")
        self.pages.append(("Header / route", header))
        for setup in setups:
            content = self.issues(self.setup_findings(setup))
            content += f"<h2>SETUP {escape(setup['id'])} — {escape(self.reference(setup.get('machine'), 'machines'))}</h2>"
            content += _p("Starts from: " + _text(setup.get("stock_in")) + "; stock state: " + self.paragraphs(setup.get("stock_state", {}), recipes=True))
            content += _p("Hold: " + self.paragraphs(setup.get("hold", {}), recipes=True))
            content += _p("Coolant: " + _text(setup.get("coolant")) + "; deburr maximum: " + self.recipe(setup.get("deburr_mm")) + " mm")
            headroom = self.records.get(("headroom", setup["id"]), {})
            summary = {k: v for k, v in headroom.items() if k not in {"stacks", "cut_tip_above_jaws_mm"}}
            content += _p("Headroom / support / clearance (nominal unless confirmed): " + (self.paragraphs(summary, recipes=True) if summary else "? no headroom computation"))
            if setup.get("note"):
                content += _p(self.bench(setup["note"]))
            content += self.dro(setup) + self.coordinates(setup)
            ops = setup.get("ops", [])
            content += self.operations(setup, ops[:8])
            self.pages.append((f"Setup {setup['id']}", content))
            for start in range(8, len(ops), 8):
                context = _p(f"Frame {_text(setup.get('frame'))}, {_text(self.units)}; depths are tool-tip targets. Use this setup's hold and DRO touch / set / check recipe.")
                self.pages.append((f"Setup {setup['id']} operations continued", context + self.operations(setup, ops[start:start + 8])))
            self.contours(setup)
        drawing = self.plan.get("drawing", {})
        part = _text(self.plan.get("part"))
        banner = "CHECKED — HASH-MATCHED FIRST ARTICLE RECORDED" if self.checked else "PLANNED — NOT APPROVED FOR THIS INPUT BUNDLE"
        result = [f'<!DOCTYPE html>\n<html lang="en"><head><meta charset="utf-8"><title>{escape(part)} traveler</title><style>{_CSS}</style></head><body>']
        footer = f"prechips {self.report.get('prechips_version', '?')} · report {str(self.report.get('hash', '?'))[:8]}"
        result.append(_p(footer, "print-footer"))
        for title, content in self.pages:
            result.append('<section class="page">')
            result.append(f'<div class="meta"><h1>{escape(part.upper())} · {escape(_text(drawing.get("number")))} · rev {escape(_text(drawing.get("revision")))}</h1><div>qty {escape(_text(self.plan.get("quantity")))}</div></div>')
            result.append(_p(title))
            result.append(f'<div class="banner">{banner}</div>')
            result.append(content)
            result.append(_p("Sign off: __________  First article / measured results: ____________________"))
            result.append(_p(footer, "foot"))
            result.append("</section>")
        result.append("</body></html>\n")
        return "\n".join(result)


def render_traveler(bundle, findings, report, approval=None) -> str:
    """Render fresh declared/computed instructions; approval never supplies numbers."""
    return _Traveler(bundle, findings, report, approval).render()
