"""Five noninteractive verbs sharing validation, findings and bundle binding."""

from __future__ import annotations

import argparse
import json
import logging
import math
import os
import re
import sys
import tomllib
import uuid
from pathlib import Path

from prechips import __version__, telemetry
from prechips.findings import Finding, exit_code
from prechips.inputs import BadInput, Bundle, load_bundle, load_inventory
from prechips.report import (
    build_report,
    canonical_bytes,
    inspection_sketch_names,
    render_assets,
    report_hash,
)
from prechips.rules.resolution import _citations

# The picture files a run writes beside its report: a setup's, and its inspection sketches.
_GENERATED_PNG = re.compile(r"setup-S\d+(?:-op\d+-[A-Za-z0-9_]+)?\.png")


class Parser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        self.print_usage(sys.stderr)
        raise BadInput(message)


def _common(parser: argparse.ArgumentParser, *, bundle: bool = True) -> None:
    parser.add_argument("--json", action="store_true", default=argparse.SUPPRESS)
    parser.add_argument("--verbose", action="store_true", default=argparse.SUPPRESS)
    if bundle:
        parser.add_argument("--inventory")
        parser.add_argument("--policy")
        parser.add_argument("--cutting-data")
        parser.add_argument("--out", type=Path)


def build_parser() -> argparse.ArgumentParser:
    parser = Parser(prog="prechips", description="Checks before chips.")
    parser.add_argument("--version", action="version", version=f"prechips {__version__}")
    _common(parser, bundle=False)
    verbs = parser.add_subparsers(dest="verb", required=True)
    for verb in ("traveler", "check"):
        command = verbs.add_parser(verb)
        command.add_argument("plan", type=Path)
        _common(command)
        command.add_argument("--approval", type=Path)
    tools = verbs.add_parser("tools")
    tools.add_argument("query", nargs="?", default="")
    tools.add_argument("--inventory")
    tools.add_argument("--measure", action="store_true", help="List current-plan measurement debt.")
    tools.add_argument("--plan", action="append", type=Path, help="Scope --measure to this plan.")
    _common(tools, bundle=False)
    compare = verbs.add_parser("compare")
    compare.add_argument("plans", nargs="+", type=Path)
    _common(compare)
    explain = verbs.add_parser("explain")
    explain.add_argument("report", type=Path)
    explain.add_argument("finding", help="rule[:subject]")
    _common(explain, bundle=False)
    return parser


def _output_paths(out: Path, filenames: tuple[str, ...], inputs: list[Path]) -> list[Path]:
    root = out.resolve()
    if root.exists() and not root.is_dir():
        raise BadInput("The output directory names a file.")
    input_paths = {path.resolve() for path in inputs}
    result = []
    for filename in filenames:
        target = root / filename
        resolved = target.resolve()
        if not resolved.is_relative_to(root):
            raise BadInput("An output path escapes the output directory.")
        if resolved in input_paths or any(
            resolved.exists() and path.exists() and resolved.samefile(path) for path in input_paths
        ):
            raise BadInput("An output path is also an input; nothing was written.")
        if resolved.exists() and not resolved.is_file():
            raise BadInput("An output file names a directory.")
        result.append(target)
    return result


def _write_outputs(
    out: Path, outputs: dict[Path, bytes | None], tracing: telemetry.Telemetry
) -> None:
    """Stage every write/deletion in full before changing any target.

    A failure removes the staged files and returns each already-replaced target to
    its prior bytes (or removes it when it is new); a filesystem refusal is exit 3.
    """
    temporaries: list[Path] = []

    def stage(target: Path, data: bytes) -> Path:
        temporaries.append(target.with_name(f".{target.name}.{uuid.uuid4().hex}.tmp"))
        with temporaries[-1].open("xb") as handle:
            handle.write(data)
        return temporaries[-1]

    replaced: list[tuple[Path, Path | None]] = []
    try:
        out.mkdir(parents=True, exist_ok=True)
        staged = []
        for target, data in outputs.items():
            with tracing.span("output.write", path=str(target)):
                staged.append(stage(target, data) if data is not None else None)
        # Only targets changed before the last need backups; unlink is atomic too.
        targets = list(outputs)
        backups = [stage(t, t.read_bytes()) if t.exists() else None for t in targets[:-1]]
        for target, temporary, backup in zip(targets, staged, [*backups, None], strict=True):
            if temporary is None:
                target.unlink(missing_ok=True)
            else:
                os.replace(temporary, target)
            replaced.append((target, backup))
    except BaseException as exc:
        for target, backup in reversed(replaced):
            if backup is None:
                target.unlink(missing_ok=True)
            else:
                # If restoring fails, the backup keeps the only copy of the prior bytes.
                temporaries.remove(backup)
                os.replace(backup, target)
        if isinstance(exc, OSError):
            raise BadInput(f"Cannot write output: {exc}") from exc
        raise
    finally:
        for temporary in temporaries:
            temporary.unlink(missing_ok=True)


def _evaluate(bundle: Bundle, tracing: telemetry.Telemetry):
    from prechips.rules import RULES, required_coverage

    findings = []
    for rule in RULES:
        with tracing.span(f"rule.{rule.name}.evaluate"):
            rows = rule.evaluate(bundle)
        for finding in rows:
            with tracing.span(
                f"rule.{rule.name}",
                subject=finding.subject,
                status=str(finding.status),
                numbers=finding.numbers,
            ):
                tracing.finding(finding)
        findings.extend(rows)
    step = bundle.features.get("step_sha256", "unknown")
    binding = Finding(
        "bundle_binding",
        "inputs",
        "unknown" if step == "unknown" else "pass",
        {"step_sha256": step, "inputs": bundle.input_records},
        ["PLAN.md §5 input-bundle binding"],
        "The part model is not bound to verified STEP bytes."
        if step == "unknown"
        else "The part model and every operative input are bound to the report.",
    )
    with tracing.span("rule.bundle_binding", subject="inputs"):
        tracing.finding(binding)
    findings.append(binding)
    for finding in required_coverage(bundle, findings):
        with tracing.span(f"rule.{finding.rule}", subject=finding.subject):
            tracing.finding(finding)
        findings.append(finding)
    keys = [(f.rule, f.subject) for f in findings]
    if len(keys) != len(set(keys)):
        raise RuntimeError("A rule returned duplicate subjects.")
    return findings


def _read_approval(path: Path | None, report: dict, tracing: telemetry.Telemetry) -> dict | None:
    if path is None:
        return None
    try:
        with tracing.span("input.load", kind="approval", path=str(path)):
            document = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, tomllib.TOMLDecodeError) as exc:
        raise BadInput(f"Cannot read approval record: {exc}") from exc
    record = document
    allowed = {"hash", "first_article", "inputs"}
    if set(record) - allowed:
        raise BadInput("Unknown approval record key.")
    if not isinstance(record.get("hash"), str) or not isinstance(record.get("first_article"), str):
        raise BadInput("An approval must name its report hash and first-article evidence.")
    old_inputs = record.get("inputs", {})
    if not isinstance(old_inputs, dict) or any(
        not isinstance(digest, str) for digest in old_inputs.values()
    ):
        raise BadInput("Approval inputs must be a table of digest strings.")
    matches = record["hash"] == report["hash"]
    warnings = []
    if not matches:
        changed = []
        for name, current in report["inputs"].items():
            if name not in old_inputs:
                continue
            if old_inputs[name] != current["sha256"]:
                changed.append(name.replace("_", " "))
        description = ", ".join(changed) or "the operative bundle"
        warnings.append(
            f"Approval no longer matches: {description} changed. Repeat the first article."
        )
    approved = (
        matches and bool(record["first_article"].strip()) and report["verification"] == "checked"
    )
    if matches and not record["first_article"].strip():
        warnings.append("No first-article evidence is recorded; the traveler remains planned.")
    elif matches and report["verification"] != "checked":
        warnings.append(
            "The report still has unresolved shop-required checks; approval cannot waive them."
        )
    for warning in warnings:
        tracing.log("warn", f"! {warning}")
    return {**record, "approved": approved, "warnings": warnings}


def _json_stdout(value) -> None:
    sys.stdout.buffer.write(canonical_bytes(value))


def _tools(args, tracing: telemetry.Telemetry) -> int:
    from prechips.measurements import (
        envelope_measurements,
        measurement_checklist,
    )
    from prechips.rules.resolution import (
        authored,
        candidate_refs,
        length_mm,
        number,
        resolve,
        uncertain,
    )

    path = args.inventory or os.environ.get("PRECHIPS_INVENTORY")
    if args.measure:
        from prechips.rules import MEASUREMENT_RULES

        plans = args.plan
        if not plans:
            examples = Path(__file__).resolve().parents[2] / "examples"
            plans = [
                examples / "pivot-shaft" / "plan.toml",
                examples / "rocker-arm" / "plan.toml",
                examples / "pivot-bracket" / "plan.toml",
                examples / "cone-pivot-post" / "built-up.toml",
            ]
        scoped_findings = []
        inventories = set()
        for plan in plans:
            bundle = load_bundle(plan, inventory=path)
            inventory_path = bundle.paths["inventory"]
            inventories.add(inventory_path)
            for rule in MEASUREMENT_RULES:
                scoped_findings.extend(
                    (plan.as_posix(), inventory_path, finding) for finding in rule.evaluate(bundle)
                )
        findings = []
        for plan_label, inventory_path, finding in scoped_findings:
            for entry in finding.numbers.get("measurements", []):
                label = plan_label if entry["id"].startswith("plan.") else None
                if label is None and len(inventories) > 1:
                    label = inventory_path.as_posix()
                if label is not None:
                    entry["id"] = f"{label}:{entry['id']}"
                    entry["instruction"] = f"{label}: {entry['instruction']}"
            findings.append(finding)
        checklist = measurement_checklist(findings)
        if getattr(args, "json", False):
            _json_stdout(checklist)
        else:
            for entry in checklist:
                print(f"[ ] {entry['instruction']}")
                for citation in entry["cite"]:
                    print(f"    {citation}")
        tracing.log("debug", "Inventory measurement checklist.", measurements=len(checklist))
        return 0
    if args.plan:
        raise BadInput("--plan is only supported with tools --measure.")
    if not path:
        raise BadInput("tools requires --inventory or PRECHIPS_INVENTORY.")
    inventory = load_inventory(path)
    words = args.query.casefold().split()
    requested = None
    text_words = []
    for word in words:
        try:
            requested = float(word.removesuffix("mm"))
        except ValueError:
            text_words.append(word)
    if requested is not None and (not math.isfinite(requested) or requested <= 0):
        raise BadInput("A tool query diameter must be a finite positive millimetre size.")
    rows = []
    for category, identity in candidate_refs(inventory):
        item = resolve(inventory, category, identity)
        if item is None:
            item = {} if "/" in identity else authored(inventory, category, identity)
        searchable = json.dumps({"id": identity, **item}, ensure_ascii=False).casefold()
        if text_words and not all(word in searchable for word in text_words):
            continue
        diameter = length_mm(item, "dia")
        verdict = "unknown"
        reason = "No confirmed diameter is listed."
        if requested is not None and number(diameter):
            verdict = (
                "unknown"
                if uncertain(item)
                else "pass"
                if abs(diameter - requested) < 1e-9
                else "error"
            )
            reason = (
                "Nominal diameter matches."
                if abs(diameter - requested) < 1e-9
                else "Nominal diameter differs from requested size."
            )
            if uncertain(item):
                reason += " Verify the inventory measurement."
        size = diameter
        if not number(size):
            size = next(
                (
                    value
                    for field in ("capacity", "height", "range")
                    if number(value := length_mm(item, field))
                ),
                "unknown",
            )
        if size == "unknown" and isinstance(item.get("range_mm"), list):
            size = item["range_mm"]
        if number(size):
            size_in = size / 25.4
        elif isinstance(size, list) and all(number(value) for value in size):
            size_in = [value / 25.4 for value in size]
        else:
            size_in = "unknown"
        row = {
            "category": category,
            "id": identity,
            **item,
            "dia_mm": diameter,
            "dia_in": diameter / 25.4 if number(diameter) else "unknown",
            "verify": uncertain(item),
            "size_mm": size,
            "size_in": size_in,
            "holder_chain": item.get("standard", item.get("shank", item.get("series", "unknown"))),
        }
        stated = authored(inventory, category, identity) if "/" not in identity else {}
        if category == "machines" and (stated.get("kind") == "mill" or "envelope" in stated):
            row["envelope_measurements"] = envelope_measurements(stated)
            row["envelope_measurement_status"] = (
                "measured"
                if all(fact["verified"] for fact in row["envelope_measurements"].values())
                else "unmeasured"
            )
        if requested is not None:
            row.update(requested_dia_mm=requested, sizing=verdict, reason=reason)
        rows.append(row)
    if getattr(args, "json", False):
        _json_stdout(rows)
    else:
        print("ID | Kind | Size mm / in | Holder chain | Verification | Sizing")
        for row in rows:
            print(
                f"{row['id']} | {row.get('kind', 'unknown')} | "
                f"{row['size_mm']} / {row['size_in']} | "
                f"{row['holder_chain']} | {'verify' if row.get('verify') else 'listed'} | "
                f"{row.get('reason', '—')}"
            )
            if "envelope_measurements" in row:
                print(f"  Envelope {row['id']} [{row['envelope_measurement_status']}]")
                for field, fact in row["envelope_measurements"].items():
                    marker = "measured" if fact["verified"] else "unmeasured"
                    print(f"    {field}: {fact['value']} mm [{marker}]")
    tracing.log("debug", "Inventory resolved.", candidates=len(rows))
    return 0


def _explain(args, tracing: telemetry.Telemetry) -> int:
    try:
        with tracing.span("input.load", kind="report", path=str(args.report)):
            report = json.loads(args.report.read_text(encoding="utf-8"))
        if not isinstance(report, dict) or report.get("hash") != report_hash(report):
            raise BadInput("The report hash does not match its canonical content.")
        rule, separator, subject = args.finding.partition(":")
        rows = [
            f
            for f in report["findings"]
            if f["rule"] == rule and (not separator or f["subject"] == subject)
        ]
        if not rows:
            raise BadInput("No finding matches that rule and subject.")
        parsed = []
        for row in rows:
            if not all(isinstance(row[key], str) for key in ("rule", "subject", "message")):
                raise ValueError("Finding rule, subject and message must be strings.")
            if not isinstance(row["numbers"], dict):
                raise ValueError("Finding numbers must be an object.")
            if not isinstance(row["cite"], list) or not all(
                isinstance(cite, str) for cite in row["cite"]
            ):
                raise ValueError("Finding cite must be a list of strings.")
            parsed.append(
                Finding(
                    row["rule"],
                    row["subject"],
                    row["status"],
                    row["numbers"],
                    row["cite"],
                    row["message"],
                )
            )
    except (OSError, UnicodeError, ValueError, KeyError, TypeError) as exc:
        raise BadInput(f"Cannot explain report: {exc}") from exc
    for finding in parsed:
        tracing.finding(finding)
    if getattr(args, "json", False):
        _json_stdout(rows[0] if len(rows) == 1 else rows)
    else:
        for finding in rows:
            print(f"{finding['rule']}:{finding['subject']} — {finding['status']}")
            print(json.dumps(finding["numbers"], ensure_ascii=False, sort_keys=True, indent=2))
            print("Cite: " + "; ".join(finding["cite"]))
    return 0


def _validate_stock_dimensions(piece: dict, subject: str) -> None:
    from prechips.rules.resolution import number

    dimensions = [
        ("dia_mm", piece.get("dia_mm", "unknown")),
        ("length_mm", piece.get("length_mm", "unknown")),
    ]
    section = piece.get("section_mm", "unknown")
    if isinstance(section, list):
        if len(section) != 2:
            raise BadInput(f"{subject}.section_mm must contain two rectangular dimensions.")
        dimensions.extend((f"section_mm[{index}]", value) for index, value in enumerate(section))
    for field, value in dimensions:
        if number(value) and (not math.isfinite(value) or value <= 0):
            raise BadInput(f"{subject}.{field} must be finite and positive.")


def _stock_piece_volume(piece: dict, subject: str) -> dict:
    """Count only an explicitly shaped, authored solid blank, never a part estimate."""
    from prechips.rules.resolution import number

    _validate_stock_dimensions(piece, subject)

    form = piece.get("form", "unknown")
    length = piece.get("length_mm", "unknown")
    diameter = piece.get("dia_mm", "unknown")
    section = piece.get("section_mm", "unknown")
    round_form = form in {"round", "round_bar"}
    rectangular_form = form in {
        "rectangular",
        "rectangular_bar",
        "rectangular_blank",
        "prepared_blank",
        "flat_bar",
        "square_bar",
    }
    volume = "unknown"
    if round_form and all(number(value) for value in (diameter, length)):
        volume = math.pi * diameter * diameter * length / 4
    elif (
        rectangular_form
        and isinstance(section, list)
        and all(number(value) for value in [*section, length])
    ):
        volume = section[0] * section[1] * length
    if number(volume) and (not math.isfinite(volume) or volume <= 0):
        raise BadInput(f"{subject}: stock volume is not finite and positive.")
    fields = (
        "dia_mm, length_mm"
        if round_form
        else "section_mm, length_mm"
        if rectangular_form
        else "form, length_mm (shape unresolved)"
    )
    return {
        "form": form,
        "dia_mm": diameter if round_form else "not_applicable",
        "section_mm": section if rectangular_form else "not_applicable",
        "length_mm": length,
        "volume_mm3": volume,
        "cite": [f"{subject}: authored {fields}"] + _citations(piece.get("cite")),
    }


def _comparison_row(bundle: Bundle, report: dict, plan_label: str) -> dict:
    from prechips.rules.resolution import identity, number, record, resolve, setup_items

    stock = record(bundle.plan.get("stock"))
    components = stock.get("components")
    if "components" in stock:
        _validate_stock_dimensions(stock, f"{plan_label}:stock")
    if isinstance(components, list):
        if not components:
            raise BadInput(f"{plan_label}: stock.components must contain at least one blank.")
        pieces = [
            _stock_piece_volume(piece, f"{plan_label}:stock.components[{index}]")
            for index, piece in enumerate(components)
        ]
    elif components == "unknown":
        pieces = []
    else:
        pieces = [_stock_piece_volume(stock, f"{plan_label}:stock")]
    stock_volume = "unknown"
    if pieces and all(number(piece["volume_mm3"]) for piece in pieces):
        try:
            stock_volume = math.fsum(piece["volume_mm3"] for piece in pieces)
        except OverflowError as exc:
            raise BadInput(f"{plan_label}: combined stock volume is not finite.") from exc
        if not math.isfinite(stock_volume):
            raise BadInput(f"{plan_label}: combined stock volume is not finite.")
    net_input = bundle.features.get("volume_mm3", "unknown")
    if number(net_input) and (not math.isfinite(net_input) or net_input < 0):
        raise BadInput(f"{plan_label}: features.volume_mm3 must be finite and nonnegative.")
    net_cite = _citations(bundle.features.get("volume_cite"))
    net_volume = net_input if number(net_input) and net_cite else "unknown"
    waste = "unknown"
    if number(stock_volume) and number(net_volume):
        if net_volume > stock_volume:
            raise BadInput(f"{plan_label}: sourced net volume exceeds authored stock volume.")
        waste = (stock_volume - net_volume) / stock_volume
    holds = [record(setup.get("hold")) for setup in bundle.plan["setups"]]
    # Each holding item is the (category, key) it selects (identity), however the hold
    # spells it: two spellings of one item are one entry, and one key in two categories
    # is two items. A hold's align block names a gauge, not holding.
    fixture_items = {
        (category, reference)
        for hold in holds
        for category, reference, _ in setup_items(
            bundle, {"hold": {k: v for k, v in hold.items() if k != "align"}}
        )
    }
    unknown_fixture = False
    for hold in holds:
        if hold.get("fixture", "unknown") == "unknown":
            unknown_fixture = True
        for key in ("parallels", "support", "supports", "riser"):
            if hold.get(key) == "unknown":
                unknown_fixture = True
        supports = hold.get("supports")
        for support in supports if isinstance(supports, list) else []:
            if support == "unknown" or (
                isinstance(support, dict) and support.get("ref", "unknown") == "unknown"
            ):
                unknown_fixture = True
        if "index" in hold and record(hold["index"]).get("fixture", "unknown") == "unknown":
            unknown_fixture = True
        # These fields can also be prose. Count them only when they name a declared fixture.
        for key in ("clamp", "stop", "locator", "jaw_protection"):
            reference = hold.get(key)
            if resolve(bundle, "fixtures", reference):
                fixture_items.add(identity(bundle, reference, "fixtures"))
    # A key names its item alone unless another listed item shares it; then both print
    # with their category.
    shared = [key for _, key in fixture_items]
    fixture_refs = {
        f"{category}.{key}" if shared.count(key) > 1 else key for category, key in fixture_items
    }
    if unknown_fixture:
        fixture_refs.add("unknown")
    counts = {}
    for finding in report["findings"]:
        counts[finding["status"]] = counts.get(finding["status"], 0) + 1
    cite = [
        "PLAN.md §4.5 stock-form comparison",
        "docs/rules-comparison.md: stock-volume and waste-ratio equations",
        f"{plan_label}:setups (authored setup count)",
    ]
    cite.extend(_citations(stock.get("cite")))
    cite.extend(source for piece in pieces for source in piece["cite"])
    cite.extend(net_cite)
    return {
        "plan": plan_label,
        "part": bundle.plan["part"],
        "construction": bundle.plan.get("construction", "unknown"),
        "setups": len(bundle.plan["setups"]),
        "fixtures": sorted(fixture_refs),
        "stock_volume_mm3": stock_volume,
        "net_volume_mm3": net_volume,
        "waste_ratio": waste,
        "volume_evidence": {
            "stock_components": pieces,
            "net_cite": net_cite,
            "formula": "(stock_volume_mm3 - net_volume_mm3) / stock_volume_mm3",
        },
        "cite": cite,
        "findings": counts,
        "rule_findings": report["findings"],
        "exit": report["expected_exit"],
        "inputs": report["inputs"],
    }


def _print_comparison(rows: list[dict]) -> None:
    def cell(value):
        return str(value).replace("\n", " ").replace("|", "\\|")

    print("Plan | Part | Setups | Waste ratio (stock-net)/stock | Fixtures required | Findings")
    for row in rows:
        waste = "?" if row["waste_ratio"] == "unknown" else f"{row['waste_ratio']:.6g}"
        fixtures = ", ".join("?" if ref == "unknown" else ref for ref in row["fixtures"])
        print(
            f"{cell(row['plan'])} | {cell(row['part'])} | {row['setups']} | "
            f"{waste} | {cell(fixtures)} | {row['findings']}"
        )
    print()
    print("Rule:subject | " + " | ".join(cell(row["plan"]) for row in rows))
    candidates = [
        {(finding["rule"], finding["subject"]): finding for finding in row["rule_findings"]}
        for row in rows
    ]
    for key in sorted({key for candidate in candidates for key in candidate}):
        messages = []
        for candidate in candidates:
            finding = candidate.get(key)
            if finding is None:
                messages.append("—")
            else:
                glyph = telemetry._GLYPHS.get(finding["status"])
                message = f"{glyph} {finding['message']}" if glyph else finding["message"]
                messages.append(cell(message))
        print(f"{cell(':'.join(key))} | " + " | ".join(messages))


def _run(args, tracing: telemetry.Telemetry) -> int:
    if args.verb == "tools":
        return _tools(args, tracing)
    if args.verb == "explain":
        return _explain(args, tracing)
    plans = args.plans if args.verb == "compare" else [args.plan]
    bundles = [load_bundle(p, args.inventory, args.policy, args.cutting_data) for p in plans]
    out = args.out or plans[0].parent
    names = ("compare.json",) if args.verb == "compare" else ("report.json", "traveler.html")
    if args.verb == "traveler":
        names += tuple(
            f"setup-S{ordinal}.png" for ordinal, _ in enumerate(bundles[0].plan["setups"], start=1)
        )
        names += inspection_sketch_names(bundles[0].plan)
    if args.verb in {"traveler", "check"}:
        names += tuple(
            path.name
            for path in sorted(out.glob("setup-S*.png"))
            if path.name not in names and _GENERATED_PNG.fullmatch(path.name)
        )
    all_inputs = [path for bundle in bundles for path in bundle.paths.values()]
    if getattr(args, "approval", None):
        all_inputs.append(args.approval)
    try:
        destinations = _output_paths(out, names, all_inputs)
    except OSError as exc:
        raise BadInput(f"Cannot check output path: {exc}") from exc
    from prechips.kernel import run_geometries

    run_geometries(bundles)
    findings = [_evaluate(bundle, tracing) for bundle in bundles]
    try:
        assets = [render_assets(bundle) for bundle in bundles]
        reports = [
            build_report(bundle, rows, assets=images)
            for bundle, rows, images in zip(bundles, findings, assets, strict=True)
        ]
    except ValueError as exc:
        raise BadInput(f"Invalid kernel render output: {exc}") from exc
    if args.verb == "compare":
        try:
            comparison_root = Path(
                os.path.commonpath([str(bundle.paths["plan"].parent) for bundle in bundles])
            )
            labels = [
                bundle.paths["plan"].relative_to(comparison_root).as_posix() for bundle in bundles
            ]
        except ValueError:
            # Cross-volume Windows inputs have no common relative root.
            labels = [bundle.paths["plan"].as_posix() for bundle in bundles]
        rows = [
            _comparison_row(bundle, report, label)
            for bundle, report, label in zip(bundles, reports, labels, strict=True)
        ]
        _write_outputs(out, {destinations[0]: canonical_bytes(rows)}, tracing)
        if getattr(args, "json", False):
            _json_stdout(rows)
        else:
            _print_comparison(rows)
        codes = {report["expected_exit"] for report in reports}
        return 2 if 2 in codes else 4 if 4 in codes else 0
    report = reports[0]
    approval = _read_approval(getattr(args, "approval", None), report, tracing)
    html = None
    if args.verb == "traveler":
        from prechips.sheet import render_traveler

        html = render_traveler(bundles[0], findings[0], report, approval)
    outputs = {destinations[0]: canonical_bytes(report)}
    if html is not None:
        outputs[destinations[1]] = html.encode("utf-8")
        outputs.update({path: assets[0].get(path.name) for path in destinations[2:]})
    elif args.verb == "check":
        try:
            outputs.update(
                {
                    path: None
                    for path in destinations[1:]
                    if path.name not in assets[0]
                    or not path.exists()
                    or path.read_bytes() != assets[0][path.name]
                }
            )
        except OSError as exc:
            raise BadInput(f"Cannot check output path: {exc}") from exc
    _write_outputs(out, outputs, tracing)
    if getattr(args, "json", False):
        _json_stdout(report)
    return exit_code(findings[0], bundles[0].policy, bundles[0])


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    verb = next(
        (value for value in argv if value in {"traveler", "check", "tools", "compare", "explain"}),
        "usage",
    )
    tracing = telemetry.configure(verb)
    verbose_handler = None
    try:
        args = build_parser().parse_args(argv)
        if getattr(args, "verbose", False):
            logger = logging.getLogger("prechips")
            for handler in list(logger.handlers):
                if hasattr(handler, "verbose"):
                    logger.removeHandler(handler)
                    handler.close()
            verbose_handler = telemetry.console_handler(True)
            logger.addHandler(verbose_handler)
        return _run(args, tracing)
    except BadInput as exc:
        tracing.log("error", f"Bad input: {exc}")
        return 3
    finally:
        if verbose_handler is not None:
            logging.getLogger("prechips").removeHandler(verbose_handler)
            verbose_handler.close()
        tracing.flush()


if __name__ == "__main__":
    sys.exit(main())
