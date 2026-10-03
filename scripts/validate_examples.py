"""Validate the rev-6 authored bundles; this is not a machining checker.

Run: uv run python scripts/validate_examples.py
Only the standard library is used, including Python 3.11+ tomllib.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
import sys
import tomllib
from fractions import Fraction
from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXAMPLES = ROOT / "examples"
PARTS = ("pivot-shaft", "rocker-arm", "pivot-bracket")
EXPECTED_EXIT = {"pivot-shaft": 4, "rocker-arm": 2, "pivot-bracket": 2}
STATUSES = {"pass", "error", "warn", "info", "unknown", "unsupported", "not_applicable"}
FEATURE_RULES = {"sizing", "op_chain", "blind_depth", "datum_consistency"}
SETUP_RULES = {"order", "hold_fields", "headroom", "zero_check", "coordinates"}
TOLERANCES = {
    "dia", "position_dia", "finish_ra", "depth", "length", "width", "height",
    "thickness", "separation", "coaxiality_dia", "height_above_pivot",
    "radius", "station", "arc_len", "bottom_radius", "bottom_arc_len", "tip_land",
    "land_angle_deg",
}
SET_KINDS = {
    "endmill_set", "collet_set", "parallels_set", "center_drill_set", "drill_index",
    "drill_set", "tap_die_set", "tap_set", "reamers", "countersink_set", "qctp_set",
    "insert_holders", "micrometer_set", "lathe_tool_bits",
}
REFERENCE_KEYS = {
    "machine", "tool", "holder", "gauge", "fixture", "parallels", "support", "clamps",
    "riser", "support_blocks", "ref",
}


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def numeric(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def near(actual, expected, where: str) -> None:
    if numeric(expected):
        require(numeric(actual), f"{where}: numeric result lost to {actual!r}")
        require(math.isclose(actual, expected, rel_tol=1e-10, abs_tol=1e-8),
                f"{where}: {actual!r} != {expected!r}")
    else:
        require(actual == "unknown", f"{where}: unresolved input must yield unknown")


def canonical(value: dict) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2,
                       allow_nan=False) + "\n").encode("utf-8")


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def fraction(value: str) -> Fraction | None:
    try:
        return Fraction(value.removesuffix("in").replace("-", "/"))
    except (ValueError, ZeroDivisionError):
        return None


def entries_for(inventory: dict) -> dict:
    entries = {}
    for category in ("machines", "fixtures", "holders", "tools", "gauges"):
        for name, item in inventory.get(category, {}).items():
            require(name not in entries, f"duplicate inventory identity {name}")
            entries[name] = item
    for name, machine in inventory.get("machines", {}).items():
        for accessory in machine.get("standard_accessories", []) + machine.get("included", []):
            entries.setdefault(accessory, {"ref": name})
    return entries


def resolves(ref: str, entries: dict) -> bool:
    if ref in entries:
        item = entries[ref]
        return item.get("present") is not False and item.get("kind") not in SET_KINDS
    if "/" not in ref:
        return False
    root, selected = ref.split("/", 1)
    entry = entries.get(root, {})
    if not entry or entry.get("present") is False:
        return False
    if selected in entry.get("included", []) + entry.get("standard_accessories", []):
        return True
    kind = entry.get("kind")
    if kind in {"collet_set", "parallels_set", "countersink_set"}:
        size = fraction(selected)
        choices = entry.get("sizes_in", entry.get("heights_in", []))
        return size is not None and size in {fraction(str(v)) for v in choices}
    if kind == "endmill_set":
        match = re.fullmatch(r"(.+in)-(2|4)fl", selected)
        if not match:
            return False
        size = fraction(match[1])
        return size is not None and size in {
            fraction(str(v)) for v in entry.get("sizes_in", {}).get("2_and_4_flute", [])
        }
    if kind == "center_drill_set":
        return selected.removeprefix("#").isdigit() and int(selected.removeprefix("#")) in (
            entry.get("sizes", [])
        )
    if kind == "drill_index":
        numbered = re.fullmatch(r"#(\d{1,2})", selected)
        if numbered:
            return 1 <= int(numbered[1]) <= 60
        if re.fullmatch("[A-Z]", selected):
            return True
        size = fraction(selected)
        return (size is not None and Fraction(1, 16) <= size <= Fraction(1, 2)
                and (size * 64).denominator == 1)
    if kind == "qctp_set":
        choices = {"1-turning-facing": "#1 turning/facing",
                   "2-boring-turning-facing": "#2 boring/turning/facing",
                   "4-heavy-boring": "#4 heavy boring", "7-parting": "#7 parting (1/2 blade)"}
        return choices.get(selected, selected) in entry.get("holders", {})
    if kind == "insert_holders":
        return selected in entry.get("styles", [])
    if kind == "micrometer_set":
        return selected.removesuffix("in") in entry.get("ranges_in", [])
    return False


def uncertain(ref: str, entries: dict, seen: tuple = ()) -> bool:
    root = ref if ref in entries else ref.split("/", 1)[0]
    if root not in entries or root in seen:
        return True

    def walk(value) -> bool:
        if isinstance(value, dict):
            if (value.get("verify") is True or value.get("present") == "unknown"
                    or "verify" in str(value.get("coverage", "")).lower()):
                return True
            if "ref" in value and uncertain(value["ref"], entries, (*seen, root)):
                return True
            return any(walk(v) for v in value.values())
        return isinstance(value, list) and any(walk(v) for v in value)

    return walk(entries[root])


def selected_refs(plan: dict):
    def walk(value):
        if isinstance(value, dict):
            if "ref" in value:
                ref = value["ref"]
                if "item" in value:
                    ref += "/" + str(value["item"])
                if ref != "unknown":
                    yield ref
            for key, child in value.items():
                if key in REFERENCE_KEYS - {"ref"} and isinstance(child, str):
                    if child not in {"unknown", "not_applicable", "none"}:
                        yield child
                elif key == "checks" and isinstance(child, dict):
                    yield from (v for v in child.values() if v != "unknown")
                elif key not in {"ref", "item"}:
                    yield from walk(child)
        elif isinstance(value, list):
            for child in value:
                yield from walk(child)
    return set(walk(plan))


def tool_diameter(ref: str, entries: dict):
    root, _, member = ref.partition("/")
    entry = entries.get(root, {})
    if entry.get("kind") == "endmill_set":
        match = re.fullmatch(r"(.+in)-(2|4)fl", member)
        size = fraction(match[1]) if match else None
        return float(size) * 25.4 if size is not None else "unknown"
    if entry.get("kind") == "drill_index":
        size = fraction(member)
        return float(size) * 25.4 if size is not None else entry.get(
            "nominal_dia_mm", {}).get(member, "unknown")
    return entry.get("dia", "unknown")


def tool_field(ref: str, key: str, entries: dict):
    root, _, member = ref.partition("/")
    entry = entries.get(root, {})
    if key == "flutes" and entry.get("kind") == "endmill_set":
        match = re.fullmatch(r"(.+in)-(2|4)fl", member)
        return int(match[2]) if match else "unknown"
    return entry.get("items", {}).get(member, {}).get(key, entry.get(key, "unknown"))


def frame_point(point: list, frame: dict) -> list:
    result = []
    for axis in ("x", "y", "z"):
        terms = [(point[i], frame["origin"][i], frame[axis][i]) for i in range(3)
                 if frame[axis][i] != 0]
        result.append(sum((p - origin) * scale for p, origin, scale in terms)
                      if all(numeric(p) for p, _, _ in terms) else "unknown")
    return result

def model_point(point: list, frame: dict) -> list:
    return [frame["origin"][i] + sum(point[j] * frame[axis][i]
            for j, axis in enumerate(("x", "y", "z"))) for i in range(3)]


def check_frames(features: dict) -> None:
    for name, frame in features["frames"].items():
        for key in ("origin", "x", "y", "z"):
            require(isinstance(frame.get(key), list) and len(frame[key]) == 3
                    and all(numeric(v) for v in frame[key]), f"frame {name}.{key}: numeric triple")
        axes = [frame[k] for k in ("x", "y", "z")]
        for i in range(3):
            for j in range(3):
                near(sum(a * b for a, b in zip(axes[i], axes[j], strict=True)),
                     1 if i == j else 0, f"frame {name}: orthonormal basis")
        x, y, z = axes
        cross = [x[1] * y[2] - x[2] * y[1], x[2] * y[0] - x[0] * y[2],
                 x[0] * y[1] - x[1] * y[0]]
        for actual, expected in zip(cross, z, strict=True):
            near(actual, expected, f"frame {name}: right-handed basis")


def read_report(path: Path) -> dict:
    def invalid_constant(value):
        raise ValueError(f"non-finite JSON value {value}")
    report = json.loads(path.read_bytes(), parse_constant=invalid_constant)
    require(path.read_bytes() == canonical(report), f"{path}: noncanonical JSON")
    payload = {k: v for k, v in report.items() if k != "hash"}
    require(report.get("hash") == hashlib.sha256(canonical(payload)).hexdigest(),
            f"{path}: report hash mismatch")
    require(report.get("verification") == "planned", f"{path}: unearned readiness")
    previous = None
    for finding in report["findings"]:
        key = finding["rule"], finding["subject"]
        require(previous is None or previous < key, f"{path}: duplicate/unsorted finding {key}")
        previous = key
        require(finding["status"] in STATUSES, f"{key}: invalid status")
        require(isinstance(finding.get("numbers"), dict), f"{key}: missing numbers")
        require(isinstance(finding.get("cite"), list) and finding["cite"], f"{key}: missing cite")
        require(isinstance(finding.get("message"), str) and finding["message"],
                f"{key}: missing finding sentence")
        require("severity" not in finding, f"{key}: obsolete severity vocabulary")
    return report


def input_paths(folder: Path, plan: dict) -> dict:
    paths = {"plan": folder / "plan.toml", "features": folder / plan["features"]}
    for key, field in (("inventory", "inventory"), ("shop_policy", "policy"),
                       ("cutting_data", "cutting_data")):
        paths[key] = (folder / plan["paths"][field]).resolve()
    for path in paths.values():
        require(path.is_relative_to(EXAMPLES), f"input escapes examples: {path}")
    return paths


def report_exit(report: dict, policy: dict) -> int:
    if any(f["status"] == "error" for f in report["findings"]):
        return 2
    required = policy["required"]
    if any(f["rule"] in required and f["status"] in {"unknown", "unsupported", "warn"}
           for f in report["findings"]):
        return 4
    return 0


def check_subjects(plan: dict, features: dict, findings: dict) -> None:
    def has(rule: str, subject: str) -> None:
        require((rule, subject) in findings, f"missing finding {rule}:{subject}")
    for name, feature in features["features"].items():
        requirements = feature.get("requirements")
        require(isinstance(requirements, list) and len(requirements) == len(set(requirements)),
                f"{name}: invalid requirements")
        for requirement in requirements:
            require(requirement in feature, f"{name}: omitted required field {requirement}")
        require(feature.get("faces") == "unknown" or isinstance(feature.get("faces"), list),
                f"{name}: faces must be set or unknown")
        if requirements:
            require(isinstance(feature.get("precision"), dict),
                    f"{name}: per-dimension precision")
        for rule in FEATURE_RULES:
            has(rule, name)
        tolerances = set(requirements) & TOLERANCES
        if not tolerances:
            has("inspection", name)
        for requirement in tolerances:
            subject = f"{name}:{requirement}"
            has("inspection", subject)
            finishing = [op for setup in plan["setups"] for op in setup["ops"]
                         if op["feature"] == name and requirement in op.get("checks", {})]
            require(finishing or findings["inspection", subject]["status"] == "error",
                    f"{subject}: no check entry or report error")
    setups = plan.get("setups")
    require(isinstance(setups, list) and setups, "empty plan setups")
    ids = [setup["id"] for setup in setups]
    require(len(ids) == len(set(ids)), "duplicate setup id")
    for setup in setups:
        sid = setup["id"]
        require(setup["frame"] in features["frames"], f"{sid}: missing frame")
        require(setup.get("ops"), f"{sid}: empty operations")
        require(isinstance(setup.get("stock_state"), dict), f"{sid}: missing stock state")
        require(isinstance(setup.get("hold"), dict), f"{sid}: missing hold")
        require(isinstance(setup.get("zero"), dict), f"{sid}: missing zero")
        axes = ("x", "z") if setup["machine"] == "PM-1127VF-LB" else ("x", "y", "z")
        for axis in axes:
            recipe = setup["zero"].get(axis)
            require(isinstance(recipe, dict) and "check_jog_mm" in recipe,
                    f"{sid}: missing {axis} check jog")
        require("retouch_after" in setup["zero"]["z"], f"{sid}: missing retouch contract")
        for rule in SETUP_RULES:
            has(rule, sid)
        ops = [op["op"] for op in setup["ops"]]
        require(len(ops) == len(set(ops)), f"{sid}: duplicate operation number")
        for op in setup["ops"]:
            require(op["feature"] in features["features"], f"{sid}: undeclared feature")
            has("speeds_feeds", f"{sid}:{op['op']}")
            if "tool" in op:
                require("holder" in op, f"{sid}:{op['op']}: omitted holder")
                has("tool_resolves", f"{sid}:{op['op']}")


def check_references(plan: dict, entries: dict, findings: dict) -> list:
    missing = []
    for ref in sorted(selected_refs(plan)):
        key = "tool_resolves", ref
        require(key in findings, f"missing reference finding for {ref}")
        finding = findings[key]
        if not resolves(ref, entries):
            require(finding["status"] == "error" and finding["numbers"].get("reference") == ref,
                    f"{ref}: missing item must have exact named error")
            missing.append(ref)
        elif uncertain(ref, entries):
            require(finding["status"] == "unknown", f"{ref}: inherited verify must be unknown")
        else:
            require(finding["status"] == "pass", f"{ref}: available identity must resolve")
    return missing


def check_zero(setup: dict, finding: dict, entries: dict) -> None:
    numbers = finding["numbers"]
    for axis, row in numbers.get("axes", {}).items():
        recipe = setup["zero"][axis]
        edge = recipe.get("edge_mm", "unknown")
        if axis == "z":
            edge = row.get("edge_mm", "unknown")
            paper = recipe.get("paper_mm", "unknown")
            expected = edge + paper if numeric(edge) and numeric(paper) else "unknown"
        elif recipe.get("method") == "trial_cut_measure":
            expected = "unknown"  # A measured trial diameter has not been supplied.
        elif recipe.get("from") == "indicated":
            near(row["radius_mm"], 0, "indicated axis has no finder correction")
            expected = edge
        else:
            tip = entries.get(recipe.get("tool", ""), {}).get("tip_in", "unknown")
            radius = tip * 25.4 / 2 if numeric(tip) else "unknown"
            near(row.get("radius_mm", "unknown"), radius, f"{setup['id']}.{axis}: finder radius")
            side = -1 if recipe.get("from") == f"-{axis}" else 1
            expected = edge + side * radius if numeric(edge) and numeric(radius) else "unknown"
        near(row.get("axis_set", "unknown"), expected, f"{setup['id']}.{axis}: Axis Set")
        jog = recipe["check_jog_mm"]
        sign = row.get("sign", "unknown")
        for field, factor in (("check_reading", 1), ("mirrored_reading", -1)):
            result = expected + factor * sign * jog if all(
                numeric(v) for v in (expected, sign, jog)) else "unknown"
            near(row.get(field, "unknown"), result, f"{setup['id']}.{axis}: {field}")
    top = setup["stock_state"].get("top_z", "unknown")
    after = {}
    for op in setup["ops"]:
        top_feature = setup["stock_state"].get("top_feature")
        if (op["do"] in {"face", "finish_face", "rough_face"} and "to_z" in op
                and (top_feature is None or op["feature"] == top_feature)):
            top = op["to_z"]
        after[op["op"]] = top
    for row in numbers.get("retouch", []):
        top = after[row["op"]]
        paper = setup["zero"]["z"].get("paper_mm", "unknown")
        near(row["top_z"], top, f"{setup['id']}: advanced top")
        expected = top + paper if numeric(top) and numeric(paper) else "unknown"
        near(row["axis_set"], expected, f"{setup['id']}: retouch Axis Set")

def check_endpoints(plan: dict, findings: dict, entries: dict) -> None:
    setups = {setup["id"]: setup for setup in plan["setups"]}
    for (rule, _), finding in findings.items():
        if rule != "blind_depth":
            continue
        for row in finding["numbers"].get("endpoints", []):
            setup = setups[row["setup"]]
            op = next(op for op in setup["ops"] if op["op"] == row["op"])
            require(op["feature"] == row["feature"], "endpoint mismatched feature")
            if op["do"] == "spot":
                depth = op.get("depth_mm", "unknown")
                tip = row["entry_z"] - depth if all(numeric(v) for v in (
                    row["entry_z"], depth)) else "unknown"
                near(row["tip_z"], tip, "spot endpoint")
                continue
            allowance = op.get("exit_mm", "unknown")
            near(row["exit_mm"], allowance, "endpoint exit allowance")
            diameter = tool_diameter(op.get("tool", "unknown"), entries)
            if op["do"] == "ream":
                point = tool_field(op["tool"], "lead_mm", entries)
                near(row.get("lead_mm", "unknown"), point, "reamer lead")
            else:
                angle = tool_field(op.get("tool", "unknown"), "point_angle", entries)
                point = diameter / (2 * math.tan(math.radians(angle / 2))) if all(
                    numeric(v) for v in (diameter, angle)) else "unknown"
                near(row.get("point_mm", "unknown"), point, "drill point")
            thickness = setup["stock_state"].get("local_thickness", {}).get(
                op["feature"], "unknown")
            entry = row.get("entry_z", "unknown")
            exit_face = entry - thickness if numeric(entry) and numeric(thickness) else "unknown"
            near(row["exit_face"], exit_face, "local exit face")
            tip = exit_face - point - allowance if all(
                numeric(v) for v in (exit_face, point, allowance)) else "unknown"
            near(row["tip_z"], tip, "tip endpoint")


def check_speeds(setup: dict, op: dict, finding: dict, entries: dict,
                 cutting: dict, features: dict) -> None:
    row = finding["numbers"]
    if finding["status"] == "not_applicable":
        return
    if setup["machine"] == "PM-1127VF-LB":
        feature = features["features"][op["feature"]]
        diameter = feature.get("dia_nominal", "unknown")
        if not numeric(diameter) and numeric(feature.get("base_radius")):
            diameter = 2 * feature["base_radius"]
        # A turned face/end can cut several diameters. Its workpiece envelope
        # is cited in the report, not inferred from a single-point tool's size.
    else:
        diameter = tool_diameter(op.get("tool", "unknown"), entries)
    if numeric(row.get("diameter_in")) and numeric(diameter):
        near(row["diameter_in"], diameter / 25.4, "cutting diameter")
    sfm = row.get("sfm", "unknown")
    if numeric(sfm):
        require(any(c["sfm"] == sfm and c["cite"] != "unknown" for c in cutting["cut"])
                or tool_field(op["tool"], "chart", entries) != "unknown",
                "numeric speed lacks source table/chart")
        raw = 12 * sfm / (math.pi * row["diameter_in"])
        rpm = round(max(row["rpm_min"], min(row["rpm_max"], raw)) / 50) * 50
        near(row["rpm"], rpm, f"{setup['id']}:{op['op']}: RPM")
    else:
        require(row.get("rpm") == "unknown", "uncited cutting speed became RPM")
    values = row.get("rpm"), row.get("flutes"), row.get("chip_load_mm_per_tooth")
    feed = math.prod(values) if all(numeric(v) for v in values) else "unknown"
    near(row.get("feed_mm_min", "unknown"), feed, "feed per tooth")


def check_coordinates(setup: dict, features: dict, finding: dict) -> None:
    frame = features["frames"][setup["frame"]]
    for row in finding["numbers"].get("rows", []):
        require(row["feature"] in features["features"], "unknown coordinate feature")
        feature = features["features"][row["feature"]]
        # A named station/apex on a turned part is not a feature centre.
        if "point" not in row:
            at = feature.get("at")
            require(isinstance(at, list) and len(at) == 3, "coordinate has no feature centre")
            model = model_point(at, features["frames"][feature.get("frame", "model")])
            for actual, expected in zip(row["model"], model, strict=True):
                near(actual, expected, "model coordinate")
        for actual, expected in zip(row["setup"], frame_point(row["model"], frame), strict=True):
            near(actual, expected, "setup coordinate")

class SheetText(HTMLParser):
    def __init__(self):
        super().__init__()
        self.text = []
        self.hidden = 0

    def handle_starttag(self, tag, attrs):
        if tag in {"style", "script"}:
            self.hidden += 1

    def handle_endtag(self, tag):
        if tag in {"style", "script"}:
            self.hidden -= 1

    def handle_data(self, data):
        if not self.hidden:
            self.text.append(data)


def check_sheet(folder: Path, report: dict) -> None:
    html = (folder / "expected" / "traveler.html").read_text(encoding="utf-8")
    parser = SheetText()
    parser.feed(html)
    text = " ".join(parser.text)
    require("PLANNED" in text and not re.search(r"(?<!NOT )\bCHECKED\b", text),
            "sheet claims unchecked approval")
    require(f"prechips 0.1 · report {report['hash'][:8]}" in text, "sheet/report footer mismatch")
    require("@page" in html and re.search(r"size\s*:\s*(?:letter|8.5in)", html, re.I),
            "missing Letter print CSS")
    require(not re.search(r"\.(?:toml|yaml|json|py|csv)\b|cad/|examples/", text),
            "bench sheet contains file paths")
    require(not any(rule in text for rule in FEATURE_RULES | SETUP_RULES | {"tool_resolves",
                "speeds_feeds", "inspection"}), "bench sheet contains rule ids")
    require("?" in text, "sheet hides required unknowns")
    if any(f["status"] == "error" for f in report["findings"]):
        require("✗" in text, "sheet hides errors")


def validate_fixture(part: str, documents: dict) -> tuple[int, list]:
    folder = EXAMPLES / part
    plan = documents[folder / "plan.toml"]
    features = documents[folder / "features.toml"]
    require(plan["part"] == features["part"] == part, "part identity mismatch")
    require(features.get("features"), "empty manifest")
    require(features["step_sha256"] == "unknown", "unprovided STEP digest asserted")
    paths = input_paths(folder, plan)
    inventory = documents[paths["inventory"]]
    policy = documents[paths["shop_policy"]]
    cutting = documents[paths["cutting_data"]]
    entries = entries_for(inventory)
    report = read_report(folder / "expected" / "report.json")
    require(set(report["inputs"]) == set(paths), "report input bundle incomplete")
    for key, path in paths.items():
        expected = {"path": path.relative_to(ROOT).as_posix(), "sha256": sha256(path)}
        require(report["inputs"][key] == expected, f"{part}: stale {key} input binding")
    require(report["step_sha256"] == features["step_sha256"], "STEP binding mismatch")
    findings = {(f["rule"], f["subject"]): f for f in report["findings"]}
    check_frames(features)
    check_subjects(plan, features, findings)
    missing = check_references(plan, entries, findings)
    check_endpoints(plan, findings, entries)
    for setup in plan["setups"]:
        check_zero(setup, findings["zero_check", setup["id"]], entries)
        check_coordinates(setup, features, findings["coordinates", setup["id"]])
        for op in setup["ops"]:
            check_speeds(setup, op, findings["speeds_feeds", f"{setup['id']}:{op['op']}"],
                         entries, cutting, features)
    exit_code = report_exit(report, policy)
    require(exit_code == report["expected_exit"] == EXPECTED_EXIT[part],
            f"{part}: expected exit mismatch ({exit_code})")
    check_sheet(folder, report)
    return exit_code, missing


def main() -> int:
    try:
        paths = sorted(EXAMPLES.rglob("*.toml"))
        require(paths, "no TOML fixtures found")
        documents = {path.resolve(): tomllib.loads(path.read_text(encoding="utf-8"))
                     for path in paths}
        require(not list(EXAMPLES.rglob("*.yaml")), "obsolete YAML examples remain")
        require(not list(EXAMPLES.rglob("*.csv")), "obsolete external coordinate files remain")
        print(f"Parsed {len(documents)} TOML files.")
        for part in PARTS:
            code, missing = validate_fixture(part, documents)
            print(f"{part}: expected exit {code}; named missing: {', '.join(missing) or 'none'}")
        print("All rev-6 reference bundles validate.")
        return 0
    except (OSError, ValueError, KeyError, TypeError, StopIteration) as exc:
        print(f"Example validation failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
