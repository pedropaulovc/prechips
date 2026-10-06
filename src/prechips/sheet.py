"""Printable bench instructions from the validated bundle and fresh rule findings.

Unlike the hand-curated references, continuations belong to their setup. Tables
flow safely across Letter pages; no fixed-height box can hide an instruction.
Computed symmetry may compress checkpoints, but never substitutes a contour.
"""

from __future__ import annotations

import math
import re
from html import escape

from .joint_features import TEMPORARY_LABEL
from .model import tolerance_requirements
from .rules.resolution import (
    MANUAL,
    SAW_OPS,
    WORKHOLDING_CATEGORIES,
    inventory_category,
    resolve,
    saw_setup,
)
from .rules.resolution import record as _mapping

_CSS = """@page { size: Letter portrait; margin: .4in; }
* { box-sizing: border-box; }
body { margin: 0; color: #000; background: #fff; font: 8pt/1.2 Arial, sans-serif; }
.page { break-after: page; page-break-after: always; }
.page:last-child { break-after: auto; page-break-after: auto; }
h1 { margin: 0; font-size: 12pt; } h2 { font-size: 9pt; margin: 4pt 0 2pt; \
border-bottom: 1px solid #000; break-after: avoid; }
p { margin: 2pt 0; } .meta { display: flex; justify-content: space-between; gap: 8pt; }
.banner { border: 2px solid #000; text-align: center; font-weight: bold; padding: 1pt; \
margin: 3pt 0; }
.byst p { margin: 1pt 0 1pt 1.3em; text-indent: -1.3em; }
table { width: 100%; border-collapse: collapse; margin: 2pt 0; table-layout: fixed; }
th, td { border: 1px solid #555; padding: 1pt 2pt; text-align: left; vertical-align: top; \
overflow-wrap: anywhere; }
th { background: #eee; } thead { display: table-header-group; }
tr { break-inside: avoid; page-break-inside: avoid; } .operations { font-size: 7.5pt; }
.fixture-render { margin: 4pt 0; break-inside: avoid; }
.fixture-render img { display: block; width: 100%; max-height: 1.7in; object-fit: contain; }
.fixture-render figcaption { font-size: 7pt; }
.foot { text-align: right; font-size: 7pt; margin-top: 5pt; break-inside: avoid; }
@media screen { body { max-width: 7.7in; margin: 12pt auto; } .page { margin-bottom: 24pt; } }
"""
_GLYPHS = {"error": "✗", "warn": "!", "unknown": "?", "unsupported": "?"}
_METADATA = {"cite", "source", "paths", "features", "step_sha256", "inspection_methods"}
_REFERENCE_FIELDS = {
    "fixture",
    "parallels",
    "supports",
    "support",
    "riser",
    "tool",
    "holder",
    "gauge",
}


def _status(finding):
    status = finding.status
    return getattr(status, "value", status)


def _field(finding, name, default=None):
    return getattr(finding, "sentence" if name == "message" else name, default)


def _text(value):
    if value is None or value == "unknown":
        return "?"
    if value == "not_applicable":
        return "—"
    if isinstance(value, (list, tuple)):
        return ", ".join(map(_text, value))
    return str(value).replace("_", " ")


def _number(value, precision=None):
    """Declared drawing precision fixes the decimals; any other known number prints its
    own value (six significant digits, float residue below 1e-6 dropped), never ``?``."""
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return _text(value)
    if not math.isfinite(value):
        return "?"
    result = f"{value:.{precision}f}" if isinstance(precision, int) else f"{round(value, 6):g}"
    return result.removeprefix("-") if float(result) == 0 else result


def _p(text, css=""):
    attribute = f' class="{css}"' if css else ""
    return f"<p{attribute}>{escape(str(text))}</p>"


def _table(headings, rows, css="", widths=None):
    columns = ""
    if widths:
        columns = (
            "<colgroup>" + "".join(f'<col style="width:{w}%">' for w in widths) + "</colgroup>"
        )
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
        # Operative features: the exported manifest plus resolved plan joint features.
        self.features = bundle.feature_definitions
        self.general_precision = bundle.features.get("precision")
        self.findings = sorted(
            findings, key=lambda f: (_field(f, "rule", ""), _field(f, "subject", ""))
        )
        self.records = {
            (_field(f, "rule"), _field(f, "subject")): _field(f, "numbers", {})
            for f in self.findings
        }
        self.report = report
        self.approval = approval or {}
        evidence = self.approval.get("first_article")
        current_hash = report.get("hash")
        self.checked = (
            report.get("verification") == "checked"
            and self.approval.get("approved") is True
            and isinstance(current_hash, str)
            and re.fullmatch(r"[0-9a-f]{64}", current_hash) is not None
            and self.approval.get("hash") == current_hash
            and isinstance(evidence, str)
            and bool(evidence.strip())
            and evidence.strip().lower() != "unknown"
            and not self.approval.get("warnings")
        )
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

    def feature_label(self, feature):
        """An exported feature prints its id; a transient joint feature is marked temporary."""
        joint = _mapping(self.features.get(feature, {}).get("joint"))
        if not joint:
            return _text(feature)
        kind = {"cylinder_bore": "socket bore", "cylinder_spigot": "spigot"}[joint["kind"]]
        return f"{_text(feature)} ({kind} on {_text(joint['component'])}): {TEMPORARY_LABEL}"

    def joint_text(self, setup):
        """How a two-branch setup joins: method, process and the declared fit band."""
        joint = _mapping(setup.get("joint"))
        if not joint:
            return ""
        text = f"; joined by {_text(joint['method'])} ({_text(joint['process'])})"
        if joint["kind"] == "cylindrical":
            band = joint.get(f"{joint['fit']}_mm")
            limits = " to ".join(map(_number, band)) if isinstance(band, list) else _text(band)
            text += (
                f": spigot {_text(joint['spigot'])} into socket {_text(joint['socket'])}, "
                f"{joint['fit']} {limits} mm diametral"
            )
        else:
            text += f" at {len(joint['interfaces'])} declared interface(s)"
        return text

    def value(self, value, feature=None, dimension=None, drawing=True):
        """Format with the dimension's declared drawing precision when one exists.

        ``drawing=False`` ignores drawing precision: a print class for a tolerance
        band is not the resolution of a computed machine target.
        """
        if dimension in {"op", "before_ops", "after_op", "retouch_after", "passes"}:
            return _text(value)
        if isinstance(value, dict):
            return (
                "; ".join(
                    f"{_text(k)}: {self.value(v, feature, k, drawing)}"
                    for k, v in value.items()
                    if not self.metadata(k)
                )
                or "—"
            )
        if isinstance(value, (list, tuple)):
            return " / ".join(self.value(v, feature, dimension, drawing) for v in value) or "—"
        if isinstance(value, bool):
            return "yes" if value else "no"
        return _number(value, self.precision(feature, dimension) if drawing else None)

    def operative(self, value, feature=None, dimension=None):
        """Tip targets, stations and cutter centres print their own computed digits."""
        return self.value(value, feature, dimension, drawing=False)

    @staticmethod
    def metadata(key):
        return key in _METADATA or key.endswith(("_cite", "_verify")) or key == "verify"

    def reference(self, reference, category=None):
        if reference in (None, "unknown", "none", "not_applicable"):
            return _text(reference)
        if not isinstance(reference, str):
            return "?"
        identity_category = category
        if category == "fixtures":
            identity_category = (
                inventory_category(self.bundle, reference, WORKHOLDING_CATEGORIES) or category
            )
        item = resolve(self.bundle, identity_category, reference)
        root, _, member = reference.partition("/")
        raw = (
            _mapping(_mapping(self.bundle.inventory.get(identity_category)).get(root))
            if identity_category
            else {}
        )
        if not raw:
            raw_category = inventory_category(self.bundle, reference, tuple(self.bundle.inventory))
            raw = (
                _mapping(_mapping(self.bundle.inventory.get(raw_category)).get(root))
                if raw_category
                else {}
            )
        record = item or raw
        name = record.get("name", record.get("label"))
        if not name:
            if category == "machines" or root in _mapping(self.bundle.inventory.get("machines")):
                name = root
            else:
                kind = record.get("kind", "unknown")
                name = _text(root.replace("-", " ") if kind in {"accessory", "unknown"} else kind)
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
        text = re.sub(
            r"https?://\S+|(?:[A-Za-z]:[\\/]|(?:\.?\.?/)?(?:cad|src|examples|harmonic-analyzer)/)\S+",
            "",
            text,
        )
        text = text.replace("PLAN.md", "approved plan")
        for rule in {key[0] for key in self.records}:
            text = text.replace(rule, _text(rule))
        return _text(text)

    def paragraphs(self, mapping, formatter=None):
        parts = []
        for key, value in mapping.items():
            if self.metadata(key):
                continue
            if key in _REFERENCE_FIELDS:
                value = self.reference(value)
            elif key == "top_feature":
                value = _text(value)
            else:
                value = (formatter or self.value)(value, dimension=key)
            parts.append(f"{_text(key)}: {value}")
        return self.bench("; ".join(parts))

    def short_reference(self, reference, category=None):
        label = self.reference(reference, category)
        for full, short in (
            ("4-flute", "4fl"),
            ("2-flute", "2fl"),
            ("endmill", "EM"),
            ("center drill", "CD"),
            ("drill index", "drill"),
            ("dial test indicator", "DTI"),
            ("dial indicator", "indicator"),
            ("micrometer", "mic"),
            (" (missing)", " ✗"),
        ):
            label = label.replace(full, short)
        return re.sub(r"(\d+)-turning-facing qctp", r"QCTP \1 turn/face", label)

    def hold(self, setup):
        hold = setup.get("hold", {})
        names = {
            "jaws_along": "jaws along",
            "grip_mm": "grip mm",
            "jaw_above_parallels_mm": "jaw above supports mm",
            "grip_on": "grip on",
        }
        parts = []
        for key, value in hold.items():
            if self.metadata(key) or value == "not_applicable" or key == "index":
                continue
            if key in _REFERENCE_FIELDS:
                value = self.short_reference(value)
            else:
                value = self.value(value, dimension=key)
            parts.append(f"{names.get(key, _text(key))}: {value}")
        return _p("Hold: " + self.bench("; ".join(parts))) + self.indexing(setup)

    def indexing(self, setup):
        hold = _mapping(setup.get("hold"))
        if "index" not in hold:
            return ""
        finding = next(
            (
                finding
                for finding in self.findings
                if _field(finding, "rule") == "indexing"
                and _field(finding, "subject") == setup["id"]
            ),
            None,
        )
        if finding is None:
            return _p("Index: ? Plate arithmetic not computed.")
        numbers = _field(finding, "numbers", {})
        feature = numbers.get("feature")
        r = self.operative
        requested = self.value(numbers.get("requested_angle_deg"), feature, "angle_deg")
        actual = self.value(numbers.get("actual_angle_deg"), feature, "angle_deg")
        glyph = _GLYPHS.get(_status(finding), "")
        tentative = "Tentative — " if _status(finding) == "unknown" else ""
        positions = numbers.get("positions")
        count = "one angular setting" if positions == 1 else f"{r(positions)} positions"
        parts = [
            f"Index: {glyph} {tentative}{self.short_reference(numbers.get('fixture'))}; "
            f"requested {requested}°; {count}; actual step {actual}°."
        ]
        if numbers.get("method") in {"direct", "worm"}:
            kind = "spindle" if numbers["method"] == "direct" else "crank"
            direction = "Reverse: " if numbers.get("direction") == "reverse" else ""
            parts.append(
                f"{direction}plate {r(numbers.get('plate'))}, "
                f"circle {r(numbers.get('circle'))}: "
                f"{r(numbers.get('turns'))} {kind} turns + "
                f"{r(numbers.get('spaces'))} hole spaces (spaces, not holes counted)."
            )
            parts.append("Nominal exact step." if numbers.get("exact") is True else "Nearest step.")
        else:
            parts.append("Plate / circle / turns / hole spaces: ?")
        parts.append(
            f"Angular tolerance ±{r(numbers.get('tolerance_deg'))}°; "
            f"maximum cumulative landing error {r(numbers.get('max_position_error_deg'))}°."
        )
        closure = numbers.get("closure")
        if closure == "not_applicable":
            parts.append(
                "Single setting: no cycle closure."
                if positions == 1
                else "Open pattern: no cycle closure."
            )
        elif isinstance(closure, dict):
            parts.append(
                f"Cycle closure: {r(closure.get('actual_angle_deg'))}° against "
                f"{r(closure.get('target_angle_deg'))}°; error {r(closure.get('error_deg'))}°."
            )
        else:
            parts.append("Cycle closure: ?")
        return _p(self.bench(" ".join(parts)))

    def headroom(self, setup):
        if saw_setup(setup):
            return _p("Saw cut-off: no spindle headroom stack applies.")
        numbers = self.records.get(("headroom", setup["id"]), {})
        if not numbers:
            if any(
                _field(f, "rule") == "headroom"
                and _field(f, "subject") == setup["id"]
                and _GLYPHS.get(_status(f))
                for f in self.findings
            ):
                return ""  # The unresolved clearance is already in Before You Start.
            return _p("? Headroom / support clearance not computed.")
        r = self.operative if "head_centre_height_mm" in numbers else self.value
        parts = [
            f"Stack (mm): bed {r(numbers.get('bed_height_mm'))}; "
            f"blocks {r(numbers.get('support_blocks_mm'))}; "
            f"parallels {r(numbers.get('parallels_mm'))}; "
            f"supported stock {r(numbers.get('stock_height_mm'))}; "
            f"insertion {r(numbers.get('insertion_mm'))}; required {r(numbers.get('sum_mm'))} / "
            f"spindle capacity {r(numbers.get('spindle_to_table_max_mm'))}."
        ]
        if "head_centre_height_mm" in numbers:
            parts = [
                f"Dividing head (mm): centre height {r(numbers.get('head_centre_height_mm'))}; "
                f"setup axis Z {r(numbers.get('head_axis_z'))}; "
                f"work top above table {r(numbers.get('work_top_above_table_mm'))}; "
                f"insertion {r(numbers.get('insertion_mm'))}; "
                f"required {r(numbers.get('sum_mm'))} / "
                f"spindle capacity {r(numbers.get('spindle_to_table_max_mm'))}."
            ]
        stacks = {}
        for stack in numbers.get("stacks", []):
            key = tuple(
                r(stack.get(k))
                for k in ("tool_projection_mm", "tool_oal_mm", "holder_gauge_len_mm", "margin_mm")
            )
            stacks.setdefault(key, []).append(_text(stack.get("op")))
        for (projection, oal, holder, margin), ops in stacks.items():
            all_ops = {str(o["op"]) for o in setup["ops"] if o.get("do") not in MANUAL | SAW_OPS}
            label = "Tools" if set(ops) == all_ops else "Ops " + ", ".join(ops)
            parts.append(
                f"{label}: projection {projection}, OAL {oal}, holder length {holder}, "
                f"headroom {margin} mm."
            )
        jaw = numbers.get("jaw_obstruction", {})
        if (
            "head_centre_height_mm" not in numbers
            and setup.get("hold", {}).get("jaws_along") != "not_applicable"
        ):
            parts.append(
                f"Jaw top Z {r(jaw.get('jaw_top_z'))}; "
                f"stock top {r(numbers.get('stock_top_above_jaws_mm'))} mm above jaws."
            )
        clearances = {}
        for op, value in numbers.get("cut_tip_above_jaws_mm", {}).items():
            clearances.setdefault(r(value), []).append(op)
        if clearances:
            parts.append(
                "Tip above jaws (mm): "
                + "; ".join(f"ops {', '.join(ops)}: {value}" for value, ops in clearances.items())
                + ". Cutter access unproved."
            )
        travel = numbers.get("travel_checks", {})
        if travel:
            axes = []
            for axis in ("x", "y"):
                record = travel.get(axis, {})
                axes.append(
                    f"{axis.upper()} stock {r(record.get('part_mm'))}, "
                    f"fixture {r(record.get('fixture_mm'))}, "
                    f"required {r(record.get('required_mm'))} / travel {r(record.get('travel_mm'))}"
                )
            parts.append("Envelope (mm): " + "; ".join(axes) + ".")
        return _p("Headroom / clearance — nominal, subject to verification. " + " ".join(parts))

    def issues(self, findings, warnings=(), setup=None):
        groups = {}
        errors = []
        for finding in findings:
            status = _status(finding)
            glyph = _GLYPHS.get(status)
            if not glyph:
                continue
            message = _field(finding, "message", "?")
            subject = _field(finding, "subject", "")
            rule = _field(finding, "rule")
            if status == "error":
                line = f"{glyph} {self.bench(message)}"
                if line not in errors:
                    errors.append(line)
                continue
            label = ""
            for prefix in (subject + ":", subject.replace(":", " ") + ":"):
                if message.startswith(prefix):
                    message = message[len(prefix) :].lstrip()
                    if rule == "inspection":
                        label = subject
                    elif setup and subject.startswith(setup["id"] + ":"):
                        label = "op " + subject.split(":", 1)[1]
                    else:
                        label = self.bench(subject.replace(":", " "))
                    break
            if status == "unknown":
                summaries = {
                    "blind_depth": (
                        "Hole entry / tool geometry / tip depth remains unresolved; see Z tips."
                    ),
                    "coordinates": (
                        "Coordinates are nominal; feature geometry or tool/frame binding "
                        "is unverified."
                    ),
                    "datum_consistency": ("Datum cuts or re-fixture acceptance remain unresolved."),
                    "headroom": (
                        "Headroom, travel or jaw access is unresolved; see clearance facts."
                    ),
                    "speeds_feeds": (
                        "Starting RPM/feed is unconfirmed: source, tool, material or machine range."
                    ),
                    "zero_check": (
                        "DRO/tool or trial-cut verification is unresolved; prove the sign below."
                    ),
                    "sizing": "Finishing tool size is unconfirmed.",
                }
                message = summaries.get(rule, message)
                if rule == "tool_resolves" and ":" in subject:
                    message = "Tool/holder fit needs measured shank, holder and machine facts."
                if rule == "inspection" and setup:
                    message = (
                        "Inspection limits, methods or gauge capability are unresolved; "
                        "close ? checks below."
                    )
                    label = ""
            key = (glyph, rule, self.bench(message))
            labels = groups.setdefault(key, [])
            if label and label not in labels:
                labels.append(label)
        lines = list(errors)
        unresolved = {}
        concise = {
            "blind_depth": ("Geometry", "hole entry / tip"),
            "coordinates": ("Geometry", "coordinates / frame binding"),
            "datum_consistency": ("Geometry", "datum transfer"),
            "headroom": ("Geometry", "headroom / clearance"),
            "sizing": ("Tooling", "finishing size"),
            "speeds_feeds": ("Tooling", "RPM / feed"),
            "tool_resolves": ("Tooling", "tool / holder / shank fit"),
            "zero_check": ("DRO / inspection", "DRO / tool / trial-cut checks"),
            "inspection": ("DRO / inspection", "inspection limits / methods / gauges"),
        }
        for (glyph, rule, message), labels in groups.items():
            if setup and glyph == "?" and rule in concise:
                category, term = concise[rule]
                labels = [label for label in labels if label and label != setup["id"]]
                if rule == "tool_resolves":
                    cutting = {
                        f"op {op['op']}" for op in setup["ops"] if op.get("do") not in MANUAL
                    }
                    if set(labels) == cutting:
                        labels = ["all cutting ops"]
                if labels:
                    term += " (" + ", ".join(labels) + ")"
                unresolved.setdefault(category, []).append(term)
                continue
            if rule == "inspection":
                features = {}
                for label in labels:
                    feature, _, requirement = label.partition(":")
                    features.setdefault(self.bench(feature), []).append(_text(requirement))
                labels = [
                    f"{feature} ({', '.join(requirements)})"
                    for feature, requirements in features.items()
                ]
            context = ", ".join(labels) + ": " if labels else ""
            lines.append(f"{glyph} {context}{message}")
        for category, terms in unresolved.items():
            lines.append(f"? {category} unresolved: {'; '.join(terms)}. Close ? checks below.")
        for warning in warnings:
            line = f"! {self.bench(warning)}"
            if line not in lines:
                lines.append(line)
        if not lines:
            lines.append("No reported errors, warnings or unresolved checks for this section.")
        return (
            '<h2>BEFORE YOU START</h2><div class="byst">'
            + "".join(_p(line) for line in lines)
            + "</div>"
        )

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
        if saw_setup(setup):
            return _p(
                "Saw setting uses the declared setup-frame cut plane; "
                "no spindle DRO zero or tool-touch recipe applies."
            )
        numbers = self.records.get(("zero_check", setup["id"]), {})
        authored = _mapping(setup.get("zero"))
        settings = _mapping(self.plan.get("dro"))
        machine = _mapping(resolve(self.bundle, "machines", setup.get("machine")))
        lathe = machine.get("kind") == "lathe"
        mode = "linear" if machine.get("kind") == "mill" else "?"
        if lathe:
            mode = (
                "radius"
                if settings.get("radius_mode") is True
                else "diameter"
                if settings.get("radius_mode") is False
                else "?"
            )
        pieces = [
            f"<h2>DRO ZERO — frame {escape(_text(setup.get('frame')))}, "
            f"{escape(_text(self.units))}, "
            f"{escape(_text(settings.get('mode')).upper())}, {mode} mode</h2>"
        ]
        if setup.get("zero") == "unknown":
            pieces.append(
                _p("? Zero recipe is unknown; touch, Axis Set and jog checks are unresolved.")
            )
        pieces.append(
            _p(
                "Direction (§6.2): "
                + self.paragraphs(settings.get("direction", {}))
                + ". ABS Axis Set (§7.4), never Preset (§8.1). Jog without retouch; "
                + "mirrored = STOP, correct Direction and redo touch / set / check."
            )
        )
        axes = numbers.get("axes", {})
        top_feature = setup.get("stock_state", {}).get("top_feature")
        top_dimension = next(
            (
                d
                for d in ("length", "thickness", "height")
                if d in self.features.get(top_feature, {})
            ),
            None,
        )
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
                touch["edge_mm"] = self.value(touch["edge_mm"], feature, dimension)
            contact = [
                self.bench(touch.get("edge", touch.get("face", touch.get("feature", "? contact"))))
            ]
            if touch.get("method") not in (None, "paper"):
                contact.append(_text(touch["method"]))
            for key, category in (("tool", "tools"), ("holder", "holders")):
                if key in touch:
                    contact.append(self.short_reference(touch[key], category))
            if touch.get("from"):
                contact.append("from " + _text(touch["from"]).upper())
            for key, label in (
                ("edge_mm", "surface"),
                ("radius_mm", "radius"),
                ("paper_mm", "paper"),
            ):
                if (
                    key in touch
                    and touch[key] != "not_applicable"
                    and not (
                        touch.get("from") == "indicated"
                        and key in {"edge_mm", "radius_mm"}
                        and touch[key] in (0, 0.0, "0.00")
                    )
                ):
                    contact.append(
                        label
                        + " "
                        + self.value(touch[key], feature, dimension if key == "edge_mm" else None)
                    )
            remaining = {
                k: v
                for k, v in touch.items()
                if k
                not in {
                    "edge",
                    "face",
                    "feature",
                    "method",
                    "tool",
                    "holder",
                    "from",
                    "edge_mm",
                    "radius_mm",
                    "paper_mm",
                }
            }
            if remaining:
                contact.append(self.paragraphs(remaining))
            expected = self.value(computed.get("check_reading"), feature, dimension)
            mirrored = self.value(computed.get("mirrored_reading"), feature, dimension)
            if expected == "?" and computed.get("check_expression"):
                expected += " (" + self.bench(computed["check_expression"]) + ")"
            if mirrored == "?" and computed.get("mirrored_expression"):
                mirrored += " (" + self.bench(computed["mirrored_expression"]) + ")"
            jog = computed.get("jog_mm")
            jog_direction = "−" if isinstance(jog, (int, float)) and jog < 0 else "+"
            rows.append(
                (
                    axis.upper(),
                    "; ".join(contact),
                    self.value(computed.get("axis_set"), feature, dimension),
                    jog_direction
                    + axis.upper()
                    + " "
                    + self.value(abs(jog) if isinstance(jog, (int, float)) else jog)
                    + " physical",
                    expected,
                    mirrored,
                )
            )
        pieces.append(
            _table(
                [
                    "axis",
                    "touch / compensation",
                    "Axis Set",
                    "jog, no touch",
                    "must read",
                    "mirrored: STOP",
                ],
                rows,
                widths=[5, 43, 13, 13, 13, 13],
            )
        )
        transfer = authored.get("transfer")
        if transfer:
            reindicate = transfer.get("reindicate_after", [])
            instruction = (
                f"Transfer from {_text(transfer.get('from'))}: "
                f"indicate {_text(transfer.get('indicate'))} "
                f"with {self.short_reference(transfer.get('tool'))}"
            )
            remaining = {
                k: v
                for k, v in transfer.items()
                if k not in {"from", "indicate", "tool", "reindicate_after"}
            }
            if remaining:
                instruction += "; " + self.paragraphs(remaining)
            if reindicate:
                instruction += (
                    ". After " + _text(reindicate) + ": re-indicate, repeat X/Y Axis Set / check."
                )
            pieces.append(_p(instruction))
        retouches = {}
        for record in numbers.get("retouch", []):
            key = (
                self.value(record.get("top_z"), top_feature, top_dimension),
                self.value(record.get("paper_mm")),
                self.value(record.get("axis_set"), top_feature, top_dimension),
            )
            retouches.setdefault(key, []).append(_text(record.get("op")))
        for (top, paper, axis_set), ops in retouches.items():
            pieces.append(
                _p(
                    f"After {', '.join(ops)}, re-touch "
                    f"{self.bench(setup.get('stock_state', {}).get('top_feature', 'top'))} "
                    f"Z {top} with {paper} paper → Axis Set Z {axis_set} before each changed tool."
                )
            )
        for touch in numbers.get("tool_touches", []):
            pieces.append(_p("Tool touch-off: " + self.paragraphs(touch)))
        for axis in axes.values():
            if axis.get("note"):
                pieces.append(_p(self.bench(axis["note"])))
        return "".join(pieces)

    def endpoint(self, setup, op):
        numbers = self.records.get(("blind_depth", op.get("feature")), {})
        return next(
            (
                e
                for e in numbers.get("endpoints", [])
                if e.get("setup") == setup["id"] and str(e.get("op")) == str(op["op"])
            ),
            None,
        )

    def tip(self, setup, op):
        feature = op.get("feature")
        endpoint = self.endpoint(setup, op)
        if endpoint:

            def value(key):
                return self.operative(endpoint.get(key))

            parts = [f"entry {value('entry_z')} → tip {value('tip_z')}"]
            if endpoint.get("exit_face", "not_applicable") != "not_applicable":
                allowance = "lead_mm" if "lead_mm" in endpoint else "point_mm"
                parts.append(
                    f"exit face {value('exit_face')} − "
                    f"{_text(allowance).removesuffix(' mm')} {value(allowance)} "
                    f"− exit {value('exit_mm')}"
                )
                if feature not in setup.get("stock_state", {}).get("local_thickness", {}):
                    parts.append("local thickness " + value("local_thickness"))
            elif "depth_mm" in endpoint:
                parts.append("depth " + value("depth_mm"))
            return parts
        parts = []

        def value(key):
            return self.operative(op[key])

        if "z_from" in op and "z_to" in op:
            parts.append(value("z_from") + " → " + value("z_to"))
        for key, label in (
            ("to_z", "→"),
            ("depth_mm", "depth"),
            ("exit_mm", "exit"),
            ("to_z_band", "band"),
        ):
            if key in op:
                parts.append(label + " " + value(key))
        for key in ("z_from", "z_to"):
            if key in op and not ("z_from" in op and "z_to" in op):
                parts.append(_text(key) + " " + value(key))
        return parts or ["—" if op.get("do") in MANUAL else "? tip endpoint"]

    def inspection(self, setup, op):
        rows = ["? Inspection checks unknown."] if op.get("checks") == "unknown" else []
        feature = op.get("feature")
        definition = self.features.get(feature, {})
        missing = _mapping(op.get("missing_requirements"))
        for requirement, reference in (_mapping(op.get("checks")) | missing).items():
            finding = next(
                (
                    f
                    for f in self.findings
                    if _field(f, "rule") == "inspection"
                    and _field(f, "subject") == f"{feature}:{requirement}"
                ),
                None,
            )
            glyph = (
                "?" if requirement in missing or finding is None else _GLYPHS.get(_status(finding))
            )
            target = None if requirement in missing else definition.get(requirement)
            method = _mapping(op.get("inspection_methods")).get(requirement)
            datums = definition.get("position_datums") if requirement == "position_dia" else None
            names = {
                "dia": "Ø",
                "position_dia": "position Ø",
                "coaxiality_dia": "coax Ø",
                "finish_ra": "Ra",
                "height_above_pivot": "height over pivot",
                "radius": "R",
                "bottom_radius": "bottom R",
                "arc_len": "arc",
                "bottom_arc_len": "bottom arc",
                "land_angle_deg": "land angle",
            }
            target_text = self.value(target, feature, requirement).replace(" / ", "–")
            line = (
                f"{glyph + ' ' if glyph else ''}{names.get(requirement, _text(requirement))} "
                f"{target_text}: {self.short_reference(reference, 'gauges')}"
            )
            if requirement in missing:
                line += f"; missing requirement {feature}:{requirement}"
            if datums:
                line += " to " + "|".join(map(_text, datums))
            if method:
                line += "; " + (method if requirement in missing else self.bench(method))
            rows.append(line)
        if op.get("inspection_note"):
            rows.append(self.bench(op["inspection_note"]))
        return rows or ["—"]

    def operations(self, setup, ops):
        rows = []
        citations = []
        notes = []
        saw_table = any(op.get("do") in SAW_OPS for op in ops)
        for op in ops:
            feature = op.get("feature")
            numbers = self.records.get(("speeds_feeds", f"{setup['id']}:{op['op']}"), {})
            manual = op.get("do") in MANUAL
            saw = op.get("do") in SAW_OPS
            tools = [
                self.short_reference(op.get("tool"), "tools")
                + " / "
                + self.short_reference(op.get("holder"), "holders")
            ]
            if manual and "tool" not in op:
                tools = ["—"]
            if saw:
                tools = [self.short_reference(op.get("tool"), "tools")]
            action = [_text(op.get("do"))]
            if op.get("note"):
                notes.append(f"{op['op']}: {self.bench(op['note'])}")
            for key in ("rough_allowance_mm", "stock_to_leave_mm", "passes"):
                if key in op:
                    label = {
                        "rough_allowance_mm": "allowance",
                        "stock_to_leave_mm": "stock left",
                        "passes": "passes",
                    }[key]
                    action.append(f"{label} {self.value(op[key], feature, key)}")
            if saw:
                plane = _mapping(op.get("cut_plane"))
                action.append(
                    f"blade centre {_text(plane.get('axis')).upper()} "
                    f"{self.operative(plane.get('value'))} {self.bundle.features.get('units', '?')}"
                )
            feed = numbers.get("feed_mm_min", numbers.get("feed_mm_rev"))
            feed_units = " / rev" if "feed_mm_rev" in numbers else " / min"
            feed_text = (
                "—"
                if manual
                else (self.operative(feed) if saw else self.value(feed))
                + (" mm" + feed_units if isinstance(feed, (int, float)) else "")
            )
            direction = _text(
                op.get(
                    "direction",
                    "not_applicable"
                    if manual or op.get("do") in {"spot", "drill", "ream", "tap"}
                    else None,
                )
            )
            direction = {
                "conventional": "conv",
                "climb": "climb",
                "radially inward": "radial in",
            }.get(direction, direction).replace("toward ", "→ ")
            if saw:
                direction = "keep " + _text(_mapping(op.get("cut_plane")).get("keep"))
            speed = (
                self.operative(numbers.get("blade_speed_sfm")) + " sfm"
                if saw
                else "—"
                if manual
                else _number(numbers.get("rpm"), 0) + (" rpm" if saw_table else "")
            )
            saw_numbers = self.records.get(("saw_cut", f"{setup['id']}:{op['op']}"), {})
            target = (
                "retained edge " + self.operative(saw_numbers.get("retained_boundary_mm")) + " mm"
                if saw
                else self.tip(setup, op)
            )
            rows.append(
                (
                    _text(op["op"]),
                    action,
                    self.feature_label(feature) if feature is not None else "stock" if saw else "?",
                    tools,
                    speed,
                    feed_text,
                    target,
                    direction,
                    self.inspection(setup, op),
                )
            )
            finding = next(
                (
                    f
                    for f in self.findings
                    if _field(f, "rule") == "speeds_feeds"
                    and _field(f, "subject") == f"{setup['id']}:{op['op']}"
                ),
                None,
            )
            if finding:
                for cite in _field(finding, "cite", []):
                    citation = self.bench(cite)
                    if citation.startswith("approved plan §3.5 RPM ="):
                        citation = "approved plan starting-speed model"
                    elif citation == "inventory machine spindle range":
                        citation = "machine range"
                    elif citation == "cutting-data aliases and rows":
                        citation = "cutting-data source row"
                    if citation and citation not in citations:
                        citations.append(citation)
        label = "speed / feed" if saw_table else "RPM / feed"
        result = f"<h2>OPERATIONS — {label} are starting points, not limits</h2>"
        widths = (
            [4, 10, 10, 18, 5, 7, 16, 8, 22]
            if self.records.get(("coordinates", setup["id"]), {}).get("x_display") == "diameter"
            else [4, 10, 10, 18, 5, 7, 16, 5, 25]
        )
        result += _table(
            [
                "op",
                "do",
                "feature",
                "tool / holder",
                "speed" if saw_table else "rpm",
                "feed",
                "cut target" if saw_table else "Z tip",
                "dir",
                "inspection",
            ],
            rows,
            "operations",
            widths,
        )
        if notes:
            result += _p(" ".join(notes))
        if citations:
            result += _p(label + " source: " + "; ".join(citations))
        return result

    def coordinates(self, setup):
        if saw_setup(setup):
            return ""
        numbers = self.records.get(("coordinates", setup["id"]), {})
        grouped = {}
        lathe = numbers.get("x_display") == "diameter"
        z_dimension = "length" if lathe else "at"
        for record in numbers.get("rows", []):
            feature = record.get("feature")
            coordinates = record.get("setup", ["unknown"] * 3)
            if not isinstance(coordinates, (list, tuple)):
                coordinates = ["unknown"] * 3
            coordinates = list(coordinates) + ["unknown"] * (3 - len(coordinates))
            x = record.get("x_target_mm", "unknown" if lathe else coordinates[0])
            x_dimension = "dia" if "x_target_mm" in record or lathe else "at"
            group = grouped.setdefault(
                (feature, tuple(coordinates), x),
                {"x_dimension": x_dimension, "operation": False, "notes": []},
            )
            # An operation's authored Z is an operative target, not a drawing dimension.
            operation = "local_from" in record or str(record.get("point")).startswith("op ")
            group["operation"] |= operation
            for name in ("point", "note", "local_from"):
                if name in record:
                    text = self.bench(self.value(record[name])).replace(
                        "drawing station", "station"
                    )
                    label = text if name == "point" else f"{_text(name)}: {text}"
                    if label not in group["notes"]:
                        group["notes"].append(label)
        rows = []
        for (feature, coordinates, x), group in grouped.items():
            z = (
                self.operative(coordinates[2])
                if group["operation"]
                else self.value(coordinates[2], feature, z_dimension)
            )
            cells = [_text(feature), self.value(x, feature, group["x_dimension"])]
            if not lathe:
                cells.append(self.value(coordinates[1], feature, "at"))
            rows.append((*cells, z, "; ".join(group["notes"]) or "—"))
        pieces = [
            f"<h2>COORDINATES — frame {escape(_text(setup.get('frame')))}, "
            f"{escape(_text(self.units))}; feature reference points</h2>"
        ]
        if rows:
            headings = (
                ["feature", "X diameter", "Z / station", "provenance"]
                if lathe
                else ["feature", "X", "Y", "Z / station", "note"]
            )
            pieces.append(_table(headings, rows, widths=[23, 12, 15, 50] if lathe else None))
        else:
            pieces.append(
                _p(
                    "? No resolved feature coordinates; use the explicit operation targets "
                    "only where their local provenance is stated."
                )
            )
        has_contours = any(
            isinstance(numbers.get(key), list) and numbers[key]
            for key in ("arc_table", "line_table", "profiles", "contours")
        )
        note = "Feature points, not cutting tips; use Z tips in operations. → = towards."
        if has_contours:
            note += " Cutter-centre tables / exact joins follow."
        for key, label in (
            ("route_limit", "Route limit"),
            ("binding", "Measured binding"),
            ("retain_web_mm", "Retained web mm"),
            ("x_display", "X display"),
            ("tool_nose_radius_mm", "Tool nose radius mm"),
            ("fitted_model_length_mm", "Fitted model length mm"),
        ):
            if key in numbers:
                note += f" {label}: {self.bench(self.value(numbers[key]))}."
        pieces.append(_p(note))
        return "".join(pieces)

    def arc_rows(self, arc):
        """Compress only reflections already present in computed checkpoints."""
        records = arc.get("rows", [])
        centre = arc.get("centre_setup_xy")
        if not records or not isinstance(centre, list) or len(centre) != 2:
            return records, ""

        def numeric(v):
            return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)

        points = [r.get("setup_xy") for r in records]
        if not all(numeric(v) for v in centre) or not all(
            isinstance(p, list) and len(p) == 2 and all(numeric(v) for v in p) for p in points
        ):
            return records, ""
        tips = [r.get("tip_z", arc.get("tip_z")) for r in records]
        if any(tip != tips[0] for tip in tips):
            return records, ""

        def key(x, y):
            return round(x, 7), round(y, 7)

        supplied = {key(*p) for p in points}
        axes = [
            axis
            for axis in range(2)
            if all(
                key(
                    2 * centre[0] - p[0] if axis == 0 else p[0],
                    2 * centre[1] - p[1] if axis == 1 else p[1],
                )
                in supplied
                for p in points
            )
        ]
        if not axes:
            return records, ""
        selected = [
            r
            for r, p in zip(records, points, strict=True)
            if all(p[axis] >= centre[axis] - 1e-7 for axis in axes)
        ]
        if not selected or len(selected) == len(records):
            return records, ""
        names = " / ".join("XY"[axis] for axis in axes)
        note = (
            f"Equivalent {names} reflections omitted. Mirror the listed coordinates about "
            f"centre X {self.operative(centre[0])}, Y {self.operative(centre[1])}; "
            f"not about a guessed datum. "
            "Keep the operation's cut direction and stated interpolation."
        )
        return selected, note

    def contours(self, setup):
        numbers = self.records.get(("coordinates", setup["id"]), {})
        tables = []
        arc_ops = set()
        o = self.operative
        for arc in (
            numbers.get("arc_table", []) if isinstance(numbers.get("arc_table"), list) else []
        ):
            feature = arc.get("feature")
            arc_ops.add(arc.get("op"))
            operation = next((op for op in setup["ops"] if op["op"] == arc.get("op")), {})
            records, symmetry = self.arc_rows(arc)
            rows = []
            for record in records:
                xy = record.get(
                    "setup_xy", [record.get("x", "unknown"), record.get("y", "unknown")]
                )
                rows.append(
                    (
                        o(record.get("angle_deg")),
                        o(xy[0]),
                        o(xy[1]),
                        o(record.get("tip_z", arc.get("tip_z", operation.get("to_z")))),
                    )
                )
            title = f"Op {_text(arc.get('op'))} — {_text(feature)}"
            description = self.paragraphs(
                {
                    k: v
                    for k, v in arc.items()
                    if k not in {"rows", "feature", "op", "centre_model_xy"}
                },
                o,
            )
            if arc.get("rows"):
                angles = [r.get("angle_deg") for r in arc["rows"]]
                description += f"; full computed arc range: {o(angles[0])} → {o(angles[-1])}°"
            if symmetry:
                description += "; " + symmetry
            tables.append((title, description, ["angle °", "X", "Y", "Z tip"], rows))
        for line in numbers.get("line_table", []):
            rows = [
                (str(i + 1), o(xy[0]), o(xy[1]), o(line.get("tip_z")))
                for i, xy in enumerate(line.get("setup_xy", []))
            ]
            description = self.paragraphs(
                {k: v for k, v in line.items() if k not in {"setup_xy", "model_xy"}}, o
            )
            tables.append(
                (
                    f"Op {_text(line.get('op'))} — exact line joins",
                    description,
                    ["join order", "X", "Y", "Z tip"],
                    rows,
                )
            )
        for profile in numbers.get("profiles", []):
            if (
                profile.get("op") in arc_ops
                and profile.get("contour", {}).get("method") == "arc_table"
            ):
                continue
            points = profile.get("cutter_centre", [])
            if not isinstance(points, list):
                continue
            feature = profile.get("feature")
            headings = ["point order", "X", "Y", "Z tip"]
            rows = []
            z = o(profile.get("to_z"))
            for i, point in enumerate(points):
                if isinstance(point, dict):
                    rows.append(
                        (o(point.get("angle_deg")), o(point.get("x")), o(point.get("y")), z)
                    )
                    headings[0] = "angle °"
                elif len(point) == 2 and all(isinstance(p, list) for p in point):
                    headings = ["pass", "X from", "Y from", "X to", "Y to", "Z tip"]
                    rows.append((str(i + 1), *(o(v) for p in point for v in p), z))
                else:
                    rows.append((str(i + 1), o(point[0]), o(point[1]), z))
            description = self.paragraphs(
                {k: v for k, v in profile.items() if k not in {"cutter_centre", "model", "rows"}},
                o,
            )
            tables.append(
                (f"Op {_text(profile.get('op'))} — {_text(feature)}", description, headings, rows)
            )
        for contour in numbers.get("contours", []):
            if not isinstance(contour, dict) or contour.get("method") != "axial_table":
                continue
            feature = contour.get("feature")
            rows = [(o(r.get("x_target_mm")), o(r.get("z_mm"))) for r in contour.get("rows", [])]
            description = self.paragraphs({k: v for k, v in contour.items() if k != "rows"}, o)
            description += (
                "; nominal profile only: apply a confirmed tool-nose compensation, never invent it."
            )
            tables.append(
                (
                    f"Op {_text(contour.get('op'))} — {_text(feature)}",
                    description,
                    ["X displayed target", "Z station"],
                    rows,
                )
            )
        content = ""
        used = 0
        for title, description, headings, rows in tables:
            for start in range(0, max(1, len(rows)), 30):
                chunk = rows[start : start + 30]
                cost = len(chunk) + 4 + math.ceil(len(description) / 110)
                if content and used + cost > 48:
                    self.pages.append((f"Setup {setup['id']} contour continuation", content))
                    content, used = "", 0
                if not content:
                    content = "<h2>CONTOUR CONTINUATION — nominal targets</h2>"
                    content += _p(
                        f"Frame {_text(setup.get('frame'))}, {_text(self.units)}. "
                        "Cutter-centre X/Y for mills; displayed X/Z profile for lathes, "
                        "subject to the stated tool-nose compensation."
                    )
                    content += _p(
                        "Nominal checkpoints do not prove cutter access or workholding. "
                        "Follow the setup's hold / release instructions."
                    )
                content += _p(title + (" (continued)" if start else "")) + _p(description)
                content += (
                    _table(headings, chunk) if rows else _p("? Contour coordinates unresolved.")
                )
                used += cost
        if content:
            self.pages.append((f"Setup {setup['id']} contour continuation", content))

    def fixture_render(self, setup):
        render = self.report.get("renders", {}).get(setup["id"])
        if not render:
            return _p("? Kernel fixture render unavailable; holding geometry is not confirmed.")
        scene = render.get("scene", {})
        kind = scene.get("fixture_kind", "vise")
        if render["fixture"] == "modeled":
            held = (
                "declared jaws / parallels"
                if kind == "vise"
                else f"declared {kind.replace('_', ' ')} fixture solids"
            )
            caption = (
                f"Kernel view: setup-entry stock and {held}; sampled checks are not a toolpath."
            )
        elif scene.get("jaws") == "lateral_undeclared":
            caption = (
                "? Kernel view: setup-entry stock, certain jaw material and a possible-jaw "
                "envelope; exact fixture pose is unresolved."
            )
        elif scene.get("jaws") == "exact":
            caption = (
                "? Kernel view: setup-entry stock and declared jaws; fixture scene incomplete."
            )
        elif scene.get("components"):
            caption = (
                "? Kernel view: setup-entry stock and declared fixture solids; "
                "fixture scene incomplete."
            )
        else:
            caption = "? Kernel stock view only; fixture dimensions or jaw pose remain unresolved."
        if scene.get("debts"):
            caption += " " + " ".join(scene["debts"])
        return (
            '<figure class="fixture-render">'
            f'<img src="{escape(render["path"], quote=True)}" '
            f'alt="{escape(setup["id"], quote=True)} kernel setup view">'
            f"<figcaption>{escape(caption)}</figcaption></figure>"
        )

    def render(self):
        setups = self.plan.get("setups", [])
        routed = {id(f) for setup in setups for f in self.setup_findings(setup)}
        header_findings = [f for f in self.findings if id(f) not in routed]
        header = self.issues(header_findings, self.approval.get("warnings", []))
        if self.plan.get("drawing", {}).get("revision", "unknown") == "unknown":
            header += _p("? Drawing revision is not confirmed.")
        if self.bundle.features.get("step_sha256", "unknown") == "unknown":
            header += _p("? No checked STEP / drawing pair is bound to this plan.")
        header += _p(
            "Drawing material / finish: "
            + self.paragraphs(self.bundle.features.get("material", {}))
        )
        header += "<h2>STOCK AND ROUTE</h2>" + _p(self.paragraphs(self.plan.get("stock", {})))
        header += _table(
            ["setup", "starts from", "machine / fixture"],
            [
                (
                    s["id"],
                    _text(s.get("stock_in")),
                    self.reference(s.get("machine"), "machines")
                    + " / "
                    + self.reference(s.get("hold", {}).get("fixture"), "fixtures"),
                )
                for s in setups
            ],
            widths=[10, 20, 70],
        )
        requirements, temporary = [], []
        for feature, definition in self.features.items():
            values = [
                "Requirement identity: ?"
                if d == "unknown"
                else f"{_text(d)} {self.value(definition.get(d), feature, d)}"
                for d in dict.fromkeys(tolerance_requirements(definition))
            ]
            if _mapping(definition.get("joint")):
                # Plan-authored preparation, never drawing acceptance.
                temporary.append(
                    (
                        self.feature_label(feature),
                        "; ".join(values) or "No preparation requirements declared.",
                    )
                )
                continue
            requirements.append(
                (_text(feature), "; ".join(values) or "No drawing requirements declared.")
            )
        header += "<h2>DRAWING REQUIREMENTS</h2>" + _table(
            ["feature", "requirement / acceptance band"], requirements
        )
        if temporary:
            header += f"<h2>{escape(TEMPORARY_LABEL)}</h2>" + _table(
                ["plan feature", "requirement / acceptance band"], temporary
            )
        header += _p(
            "Kernel geometry findings use sampled tool / holder solids, not CAM toolpaths. "
            "An unresolved fixture is not a rendered holding proof. "
            "? = unresolved. EM = endmill; CD = centre drill; DTI = test indicator; "
            "mic = micrometer. Keep the drawing at the bench."
        )
        self.pages.append(("Header / route", header))
        for setup in setups:
            content = (
                f"<h2>SETUP {escape(setup['id'])} — "
                f"{escape(self.reference(setup.get('machine'), 'machines'))}</h2>"
            )
            content += self.issues(self.setup_findings(setup), setup=setup)
            content += _p(
                "Starts from: "
                + _text(setup.get("stock_in"))
                + self.joint_text(setup)
                + "; stock state: "
                + self.paragraphs(setup.get("stock_state", {}))
            )
            content += self.hold(setup)
            content += self.fixture_render(setup)
            content += _p(
                "Coolant: "
                + _text(setup.get("coolant"))
                + "; deburr maximum: "
                + self.value(setup.get("deburr_mm"))
                + " mm"
            )
            content += self.headroom(setup)
            if setup.get("note"):
                content += _p(self.bench(setup["note"]))
            content += self.dro(setup) + self.coordinates(setup)
            ops = setup.get("ops", [])
            content += self.operations(setup, ops[:8])
            self.pages.append((f"Setup {setup['id']}", content))
            for start in range(8, len(ops), 8):
                context = _p(
                    f"Frame {_text(setup.get('frame'))}, {_text(self.units)}; "
                    "depths are tool-tip targets. Use this setup's hold and "
                    "DRO touch / set / check recipe."
                )
                self.pages.append(
                    (
                        f"Setup {setup['id']} operations continued",
                        context + self.operations(setup, ops[start : start + 8]),
                    )
                )
            self.contours(setup)
        drawing = self.plan.get("drawing", {})
        part = _text(self.plan.get("part"))
        banner = (
            "CHECKED — HASH-MATCHED FIRST ARTICLE RECORDED"
            if self.checked
            else "PLANNED — NOT APPROVED FOR THIS INPUT BUNDLE"
        )
        result = [
            f'<!DOCTYPE html>\n<html lang="en"><head><meta charset="utf-8">'
            f"<title>{escape(part)} traveler"
            f"</title><style>{_CSS}</style></head><body>"
        ]
        footer = (
            f"prechips {self.report.get('prechips_version', '?')} · report "
            f"{str(self.report.get('hash', '?'))[:8]}"
        )
        for title, content in self.pages:
            result.append('<section class="page">')
            result.append(
                f'<div class="meta"><h1>{escape(part.upper())} · '
                f"{escape(_text(drawing.get('number')))} · rev "
                f"{escape(_text(drawing.get('revision')))}</h1>"
                f"<div>qty {escape(_text(self.plan.get('quantity')))}</div></div>"
            )
            if not any(title == f"Setup {setup['id']}" for setup in setups):
                result.append(_p(title))
            result.append(f'<div class="banner">{banner}</div>')
            result.append(content)
            result.append(
                _p("Sign off: __________  First article / measured results: ____________________")
            )
            result.append(_p(footer, "foot"))
            result.append("</section>")
        result.append("</body></html>\n")
        return "\n".join(result)


def render_traveler(bundle, findings, report, approval=None) -> str:
    """Render fresh declared/computed instructions; approval never supplies numbers."""
    return _Traveler(bundle, findings, report, approval).render()
