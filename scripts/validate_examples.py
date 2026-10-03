# /// script
# requires-python = ">=3.11"
# dependencies = ["pyyaml>=6.0,<7"]
# ///
"""Validate authored reference fixtures, not machining feasibility.

Missing inventory items are allowed only when the expected report explicitly
blocks that exact reference. Unverified inventory is not silently measured.
Run from any directory: uv run scripts/validate_examples.py
"""

from __future__ import annotations

import csv
import hashlib
import json
import math
import re
import sys
from fractions import Fraction
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
EXAMPLES = ROOT / "examples"
PARTS = ("pivot-shaft", "rocker-arm", "pivot-bracket")
RULES = {
    "schema",
    "inventory_refs",
    "citations_present",
    "step_binding",
    "policy_integrity",
    "sizing_tool",
    "hole_op_chain",
    "op_order",
    "coordinate_table",
    "coverage",
    "blind_thread_depth",
    "envelope",
    "holder_compat",
    "index_representable",
}
STATUSES = {"pass", "fail", "unknown", "not_applicable"}
SET_KINDS = {
    "endmill_set",
    "collet_set",
    "parallels_set",
    "center_drill_set",
    "drill_index",
    "drill_set",
    "tap_die_set",
    "tap_set",
    "reamers",
    "countersink_set",
    "qctp_set",
    "insert_holders",
    "micrometer_set",
}


class UniqueLoader(yaml.SafeLoader):
    """Reject duplicate keys rather than quietly retaining the last value."""


def unique_mapping(loader, node, deep=False):
    result = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if key in result:
            raise ValueError(f"duplicate YAML key {key!r} at line {key_node.start_mark.line + 1}")
        result[key] = loader.construct_object(value_node, deep=deep)
    return result


UniqueLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, unique_mapping)


def load_yaml(path: Path):
    return yaml.load(path.read_text(encoding="utf-8"), Loader=UniqueLoader)


def inch_fraction(item: str) -> Fraction | None:
    text = item.removesuffix("in").replace("-", "/")
    try:
        return Fraction(text)
    except (ValueError, ZeroDivisionError):
        return None


def inventory_entries(inventory: dict) -> dict:
    entries = {}
    for category in ("machines", "workholding", "tools", "measuring"):
        entries.update(inventory.get(category, {}))
    # These are explicitly named physical accessories, not invented purchases.
    for machine, entry in inventory.get("machines", {}).items():
        for accessory in entry.get("standard_accessories", []) + entry.get("included", []):
            entries.setdefault(accessory, {"ref": machine})
    return entries


def ref_resolves(ref: str, entries: dict) -> bool:
    if ref in entries:
        return (
            entries[ref].get("present") is not False and entries[ref].get("kind") not in SET_KINDS
        )
    if "/" not in ref:
        return False
    root, item = ref.split("/", 1)
    entry = entries.get(root)
    if not isinstance(entry, dict) or entry.get("present") is False:
        return False
    if item in entry.get("included", []) + entry.get("standard_accessories", []):
        return True
    kind = entry.get("kind")
    if kind in {"collet_set", "parallels_set", "countersink_set"}:
        sizes = entry.get("sizes_in", entry.get("heights_in", []))
        selected = inch_fraction(item)
        return selected is not None and selected in {inch_fraction(str(size)) for size in sizes}
    if kind == "endmill_set":
        match = re.fullmatch(r"(.+in)-(2|4)fl", item)
        if not match:
            return False
        diameter = inch_fraction(match[1])
        sizes = entry.get("sizes_in", {}).get("2_and_4_flute", [])
        return diameter is not None and diameter in {inch_fraction(str(size)) for size in sizes}
    if kind == "center_drill_set":
        return item.removeprefix("#").isdigit() and int(item.removeprefix("#")) in entry.get(
            "sizes", []
        )
    if root == "drill-index-115":
        # The sample declares standard 115-piece coverage, not measured geometry.
        numbered = re.fullmatch(r"#?(\d{1,2})", item)
        if numbered:
            return 1 <= int(numbered[1]) <= 60
        if re.fullmatch(r"[A-Z]", item):
            return True
        size = inch_fraction(item)
        return (
            size is not None
            and Fraction(1, 16) <= size <= Fraction(1, 2)
            and (size * 64).denominator == 1
        )
    if kind == "qctp_set":
        aliases = {
            "1-turning-facing": "#1 turning/facing",
            "2-boring-turning-facing": "#2 boring/turning/facing",
            "4-heavy-boring": "#4 heavy boring",
            "7-parting": "#7 parting (1/2 blade)",
        }
        return aliases.get(item, item) in entry.get("holders", {})
    if kind == "insert_holders":
        return item in entry.get("styles", [])
    if kind == "micrometer_set":
        return item.removesuffix("in") in entry.get("ranges_in", [])
    # Candidate reamer sets and unlisted tap sizes do NOT assert physical items.
    return False


def inventory_uncertain(ref: str, entries: dict, seen: tuple = ()) -> bool:
    """Inherit verification/presence uncertainty through a physical item's refs."""
    root = ref if ref in entries else ref.split("/", 1)[0]
    if root in seen or root not in entries:
        return True

    def uncertain(value):
        if isinstance(value, dict):
            if value.get("verify") is True or ("present" in value and value["present"] is None):
                return True
            if "ref" in value and inventory_uncertain(str(value["ref"]), entries, (*seen, root)):
                return True
            return any(uncertain(child) for child in value.values())
        if isinstance(value, list):
            return any(uncertain(child) for child in value)
        return False

    return uncertain(entries[root])


def selected_refs(plan: dict):
    def walk(value, location):
        if isinstance(value, dict):
            if "ref" in value:
                ref = str(value["ref"])
                if "item" in value:
                    ref += "/" + str(value["item"])
                yield ref, location
            for key, child in value.items():
                if key in {"machine", "tool", "holder", "gauge"} and isinstance(child, str):
                    yield child, f"{location}.{key}"
                elif key not in {"ref", "item"}:
                    yield from walk(child, f"{location}.{key}")
        elif isinstance(value, list):
            for index, child in enumerate(value):
                yield from walk(child, f"{location}[{index}]")

    yield from walk(plan, "plan")


def check_pickup(spec: dict, setup: dict):
    frame = spec["frames"][setup["frame"]]
    pickup = setup["pickup"]
    for axis in ("x", "y", "z"):
        if axis not in pickup or not isinstance(pickup[axis], dict):
            raise ValueError(f"{setup['id']}: missing structured {axis} pickup")
        item = pickup[axis]
        if "sets" not in item or "side" not in item or "feature" not in item:
            raise ValueError(f"{setup['id']}: incomplete {axis} pickup")
        if item["side"] not in {"+" + axis, "-" + axis}:
            raise ValueError(f"{setup['id']}: invalid {axis} pickup side {item['side']!r}")
    z = pickup["z"]
    feature = z["feature"]
    note = frame.get("note", "").lower()
    if feature in {"frame_origin_face", "origin", "origin_face"}:
        expected = 0.0
    elif feature in {"top", "top_face", "stock_top"}:
        top = re.search(r"\btop\b", note) is not None
        bottom = re.search(r"\bbottom\b", note) is not None
        if top and not bottom:
            expected = 0.0
        elif bottom and not top and "thickness" in spec.get("material", {}):
            thickness = spec["material"]["thickness"]
            expected = float(thickness["nominal"] if isinstance(thickness, dict) else thickness)
        else:
            raise ValueError(
                f"{setup['id']}: cannot derive top Z from frame note/material.thickness"
            )
    elif feature in {"axis", "spindle_axis", "shaft_axis", "centreline"}:
        expected = 0.0
    else:
        # A named axial feature may define the contact plane in the setup frame.
        features = {item["id"]: item for item in spec["features"]}
        contact = features.get(feature, {}).get("center", {})
        if features.get(feature, {}).get("frame") != setup["frame"] or "z" not in contact:
            raise ValueError(f"{setup['id']}: cannot source pickup Z for {feature!r}")
        expected = float(contact["z"])
    if not math.isclose(float(z["sets"]), expected, abs_tol=1e-9):
        raise ValueError(f"{setup['id']}: pickup Z sets={z['sets']} but frame requires {expected}")


def reject_constant(value):
    raise ValueError(f"non-finite JSON number {value}")


def check_report(path: Path, policy: dict) -> dict:
    text = path.read_bytes().decode("utf-8")
    report = json.loads(text, parse_constant=reject_constant)
    canonical = (
        json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n"
    )
    if text != canonical:
        raise ValueError(f"{path.relative_to(ROOT)}: not canonical sorted-key JSON")
    if (
        set(report) != {"inputs", "verification", "findings", "hash"}
        or report["hash"] != "<computed>"
    ):
        raise ValueError(f"{path.relative_to(ROOT)}: wrong §3.7 report shape/hash placeholder")
    input_fields = {
        "step_sha256",
        "spec_sha256",
        "plan_sha256",
        "inventory_sha256",
        "policy_sha256",
        "rules_version",
        "tables_version",
        "prechips_version",
    }
    if set(report["inputs"]) != input_fields or report["verification"] != "planned":
        raise ValueError(f"{path.relative_to(ROOT)}: wrong inputs/verification contract")
    findings = report["findings"]
    pairs = [(finding["rule"], finding["subject"]) for finding in findings]
    if pairs != sorted(pairs) or len(pairs) != len(set(pairs)):
        raise ValueError(f"{path.relative_to(ROOT)}: findings not unique/sorted by (rule, subject)")
    if {rule for rule, _ in pairs} != RULES:
        raise ValueError(f"{path.relative_to(ROOT)}: missing or unexpected M1/M1b rules")
    for finding in findings:
        if set(finding) != {"rule", "subject", "status", "severity", "evidence", "cite"}:
            raise ValueError(f"{path.relative_to(ROOT)}: wrong finding shape")
        if (
            finding["status"] not in STATUSES
            or finding["severity"] != policy["severity"][finding["rule"]]
        ):
            raise ValueError(f"{path.relative_to(ROOT)}: invalid finding status/severity")
        if not isinstance(finding["evidence"], list) or not finding["evidence"]:
            raise ValueError(f"{path.relative_to(ROOT)}: missing ordered evidence array")
    return report


def check_csv(path: Path, setup: dict):
    with path.open(encoding="utf-8", newline="") as stream:
        rows = list(csv.reader(stream))
    expected_prefix = [f"frame={setup['frame']}", " units=mm", " mode=absolute"]
    if len(rows) < 2 or [cell.strip() for cell in rows[0][:3]] != [
        cell.strip() for cell in expected_prefix
    ]:
        raise ValueError(f"{path.relative_to(ROOT)}: wrong frame/unit/mode header")
    if [cell.strip() for cell in rows[1]] != ["feature", "op", "x", "y", "z"]:
        raise ValueError(f"{path.relative_to(ROOT)}: wrong coordinate columns")
    expected = [(str(op["feature"]), str(op["op"])) for op in setup["operations"]]
    actual = [(row[0], row[1]) for row in rows[2:] if len(row) == 5]
    if actual != expected or any(len(row) != 5 for row in rows[2:]):
        raise ValueError(
            f"{path.relative_to(ROOT)}: coordinate rows do not cover operations in order"
        )
    for row in rows[2:]:
        for number in row[2:]:
            if number and not math.isfinite(float(number)):
                raise ValueError(f"{path.relative_to(ROOT)}: non-finite coordinate")


def validate() -> int:
    errors = []
    documents = {}
    for path in sorted(EXAMPLES.rglob("*.yaml")):
        try:
            documents[path] = load_yaml(path)
        except (OSError, ValueError, yaml.YAMLError) as error:
            errors.append(f"{path.relative_to(ROOT)}: {error}")
    if errors:
        print("\n".join(errors), file=sys.stderr)
        return 1
    inventory = documents[EXAMPLES / "inventory" / "pedro-shop.yaml"]
    entries = inventory_entries(inventory)
    default_path = EXAMPLES / "policy" / "default.yaml"
    default_bytes = default_path.read_bytes()
    misses = []
    for part in PARTS:
        folder = EXAMPLES / part
        try:
            spec = documents[folder / "spec.yaml"]
            plan = documents[folder / "plan.yaml"]
            policy = documents[folder / "policy.yaml"]
            if spec["part"] != part or plan["part"] != part:
                raise ValueError("part identity differs from directory")
            if (folder / "policy.yaml").read_bytes() != default_bytes or set(
                policy["required"]
            ) != RULES:
                raise ValueError("policy copy differs or omits a required rule")
            feature_ids = [feature["id"] for feature in spec["features"]]
            if len(feature_ids) != len(set(feature_ids)):
                raise ValueError("duplicate spec feature ids")
            known = set(feature_ids)
            covered = set()
            setup_ids = set()
            for setup in plan["setups"]:
                if setup["id"] in setup_ids:
                    raise ValueError("duplicate setup ids")
                setup_ids.add(setup["id"])
                if setup["frame"] not in spec["frames"]:
                    raise ValueError(f"{setup['id']}: unknown frame")
                if set(setup.get("features", [])) - known:
                    raise ValueError(f"{setup['id']}: unresolved setup feature refs")
                for operation in setup["operations"]:
                    feature = operation["feature"]
                    if feature not in known:
                        raise ValueError(f"{setup['id']}: unresolved op feature {feature!r}")
                    covered.add(feature)
                check_pickup(spec, setup)
                check_csv(folder / "expected" / "coordinates" / f"{setup['id']}.csv", setup)
            if known - covered:
                raise ValueError(f"features without operations: {sorted(known - covered)}")
            report = check_report(folder / "expected" / "report.json", policy)
            digests = {
                "spec_sha256": hashlib.sha256((folder / "spec.yaml").read_bytes()).hexdigest(),
                "plan_sha256": hashlib.sha256((folder / "plan.yaml").read_bytes()).hexdigest(),
                "inventory_sha256": hashlib.sha256(
                    (EXAMPLES / "inventory" / "pedro-shop.yaml").read_bytes()
                ).hexdigest(),
                "policy_sha256": hashlib.sha256((folder / "policy.yaml").read_bytes()).hexdigest(),
            }
            if plan["spec_sha256"] != digests["spec_sha256"]:
                raise ValueError("plan.spec_sha256 does not bind the current spec bytes")
            for field, digest in digests.items():
                if report["inputs"][field] != digest:
                    raise ValueError(
                        f"expected report inputs.{field} differs from current file bytes"
                    )
            step_placeholder = f"<sha256 of cad/out/step/{part}.step>"
            if (
                spec["step_sha256"] != step_placeholder
                or report["inputs"]["step_sha256"] != step_placeholder
            ):
                raise ValueError("STEP placeholder differs from the fixture contract")
            expected_subjects = {
                rule: known
                for rule in (
                    "sizing_tool",
                    "hole_op_chain",
                    "coverage",
                    "blind_thread_depth",
                    "index_representable",
                )
            }
            expected_subjects.update(
                {rule: setup_ids for rule in ("op_order", "coordinate_table", "envelope")}
            )
            expected_subjects["inventory_refs"] = {ref for ref, _ in selected_refs(plan)}
            expected_subjects["holder_compat"] = {
                f"{setup['id']}:{operation['op']}"
                for setup in plan["setups"]
                for operation in setup["operations"]
            }
            for rule, subjects in expected_subjects.items():
                actual = {
                    finding["subject"] for finding in report["findings"] if finding["rule"] == rule
                }
                if actual != subjects:
                    raise ValueError(
                        f"{rule}: subject coverage differs: "
                        f"expected={sorted(subjects)}, actual={sorted(actual)}"
                    )
            for rule in ("schema", "citations_present", "step_binding", "policy_integrity"):
                if sum(finding["rule"] == rule for finding in report["findings"]) != 1:
                    raise ValueError(f"{rule}: expected one global finding")
            blocked_refs = {
                finding["subject"]
                for finding in report["findings"]
                if finding["rule"] == "inventory_refs"
                and finding["status"] == "fail"
                and finding["severity"] == "block"
            }
            missing = {ref for ref, _ in selected_refs(plan) if not ref_resolves(ref, entries)}
            if missing != blocked_refs:
                raise ValueError(
                    "inventory misses differ from expected blocks: "
                    f"actual={sorted(missing)}, report={sorted(blocked_refs)}"
                )
            for finding in report["findings"]:
                if finding["rule"] == "inventory_refs" and finding["subject"] not in missing:
                    expected_status = (
                        "unknown" if inventory_uncertain(finding["subject"], entries) else "pass"
                    )
                    if finding["status"] != expected_status:
                        raise ValueError(
                            f"inventory_refs({finding['subject']}): expected {expected_status} "
                            f"from inherited verification/presence, got {finding['status']}"
                        )
            for ref in sorted(missing):
                misses.append(f"  {part}: {ref}")
            if not (folder / "expected" / "traveler.html").is_file():
                raise ValueError("missing expected traveler")
            code = (
                2
                if any(
                    f["status"] == "fail" and f["severity"] == "block" for f in report["findings"]
                )
                else 4
                if any(
                    f["status"] == "unknown" and f["rule"] in policy["required"]
                    for f in report["findings"]
                )
                else 0
            )
            print(f"{part}: valid authored fixture; expected prechips exit {code}")
        except (KeyError, TypeError, ValueError, OSError, json.JSONDecodeError) as error:
            errors.append(f"{part}: {error}")
    if misses:
        print("Expected inventory misses (each has an inventory_refs fail/block finding):")
        print("\n".join(misses))
    else:
        print("Expected inventory misses: none")
    if errors:
        print("\n".join(errors), file=sys.stderr)
        return 1
    print(f"Validated {len(documents)} YAML files and all three canonical reference reports.")
    return 0


if __name__ == "__main__":
    raise SystemExit(validate())
