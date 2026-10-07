"""Regression coverage for authored report validation against plan touch surfaces."""

import copy
import json
import math
import runpy
import tomllib
from pathlib import Path
from types import SimpleNamespace

import pytest
from test_cli import copy_examples
from test_deep_hole_speed import DEEP, drill_bundle
from test_process_features import set_process_key, set_tool_fact, shaft

from prechips.inputs import load_bundle
from prechips.rules import coordinates, speeds_feeds
from prechips.rules.tip_endpoints import evaluate as endpoint_findings

ROOT = Path(__file__).resolve().parents[1]
VALIDATOR = runpy.run_path(str(ROOT / "scripts" / "validate_examples.py"))


def shifted(value):
    """``value`` moved 1 mm: a number, or a measured-edge ``M ±n`` reading's offset."""
    if isinstance(value, str):
        offset = float(value.removeprefix("M ")) + 1.0
        return "M " + f"{offset:+.6f}".rstrip("0").rstrip(".")
    return value + 1.0


@pytest.mark.parametrize(
    ("part", "setup_id", "reason"),
    [
        ("pivot-bracket", "S2", "touched edge"),  # Raw top, not the finished foot top.
        ("pivot-bracket", "S4", "touched edge"),  # Ear inner face, not the raised stock top.
        ("pivot-shaft", "S1", "touched edge"),  # The prepared plain end, not the blank end.
        # A bench-measured edge: the shoulder-to-stub reading M sets the axis, so a
        # consistent shift of its offset and every reading is still the wrong edge.
        ("pivot-shaft", "S2", "measured-edge"),
    ],
)
def test_rejects_self_consistent_wrong_z_edge(part, setup_id, reason):
    folder = ROOT / "examples" / part
    plan = tomllib.loads((folder / "plan.toml").read_text(encoding="utf-8"))
    inventory = tomllib.loads((folder / plan["paths"]["inventory"]).read_text(encoding="utf-8"))
    report = json.loads((folder / "expected" / "report.json").read_bytes())
    setup = next(s for s in plan["setups"] if s["id"] == setup_id)
    finding = next(
        f for f in report["findings"] if f["rule"] == "zero_check" and f["subject"] == setup_id
    )
    entries = VALIDATOR["entries_for"](inventory)
    VALIDATOR["check_zero"](setup, finding, entries, plan["dro"])

    corrupted = copy.deepcopy(finding)
    row = corrupted["numbers"]["axes"]["z"]
    fields = ("edge_mm", "offset_mm", "axis_set", "check_reading", "mirrored_reading")
    fields += ("check_expression", "mirrored_expression")
    for field in fields:
        if field in row:
            row[field] = shifted(row[field])

    with pytest.raises(ValueError, match=reason):
        VALIDATOR["check_zero"](setup, corrupted, entries, plan["dro"])


def cone_inputs():
    folder = ROOT / "examples" / "cone-pivot-post"
    plan = tomllib.loads((folder / "built-up.toml").read_text(encoding="utf-8"))
    features = tomllib.loads((folder / "features.toml").read_text(encoding="utf-8"))
    inventory = tomllib.loads((folder / plan["paths"]["inventory"]).read_text(encoding="utf-8"))
    policy = tomllib.loads((folder / plan["paths"]["policy"]).read_text(encoding="utf-8"))
    report = json.loads((folder / "expected" / "built-up" / "report.json").read_bytes())
    return plan, features, inventory, policy, report


@pytest.mark.parametrize("corruption", ["nearest", "spaces", "basic_band", "closure"])
def test_rejects_cone_indexing_arithmetic_even_when_unverified(corruption):
    plan, features, inventory, _, report = cone_inputs()
    setup = next(s for s in plan["setups"] if s["id"] == "S5")
    finding = next(
        f for f in report["findings"] if f["rule"] == "indexing" and f["subject"] == "S5"
    )
    entries = VALIDATOR["entries_for"](inventory)
    VALIDATOR["check_indexing"](setup, features, entries, finding)
    corrupted = copy.deepcopy(finding)
    row = corrupted["numbers"]
    if corruption == "nearest":
        # A plausible actual setting on another declared circle, but not the
        # nearest one. Matching its own signed error must not legitimize it.
        row.update(plate="C", circle=41, turns=1, spaces=16, actual_angle_deg=513 / 41)
        error = 513 / 41 - 12.5182
        row.update(position_errors_deg=[error], max_position_error_deg=abs(error))
    elif corruption == "spaces":
        row["spaces"] += 1
    elif corruption == "basic_band":
        row["tolerance_deg"] = 1.0
    else:
        row["closure"] = {"error_deg": 0.0, "within_tolerance": True}
    with pytest.raises(ValueError):
        VALIDATOR["check_indexing"](setup, features, entries, corrupted)


def test_rejects_unsourced_finished_diameter_in_unbound_profile():
    plan, features, _, policy, report = cone_inputs()
    setup = next(s for s in plan["setups"] if s["id"] == "S1")
    finding = next(
        f for f in report["findings"] if f["rule"] == "stickout" and f["subject"] == "S1"
    )
    VALIDATOR["check_stickout"](setup, plan, features, policy, finding)
    corrupted = copy.deepcopy(finding)
    corrupted["numbers"]["diameter_mm"] = 21.93
    with pytest.raises(ValueError):
        VALIDATOR["check_stickout"](setup, plan, features, policy, corrupted)


def test_accepts_cited_kernel_revolved_bases_without_declared_diameters():
    documents = {
        path.resolve(): tomllib.loads(path.read_text(encoding="utf-8"))
        for path in (ROOT / "examples").rglob("*.toml")
    }
    code, missing = VALIDATOR["validate_fixture"]("pivot-shaft", documents)
    assert code == 0
    assert missing == []


def test_exposed_profile_converts_inch_dia_alias_and_declared_dome_base():
    setup = {
        "id": "S1",
        "stock_state": {"north_end_z": 0.0, "south_end_z": 12.0},
        "hold": {"stickout_mm": 12.0},
    }
    features = {
        "units": "in",
        "features": {
            "neck": {"kind": "shaft", "dia": 0.25},
            "cap": {"kind": "dome", "base_radius": 0.125},
        },
    }
    row = {
        "exposed_z_mm": [0.0, 12.0],
        "segments": [
            {"z_mm": [0.0, 10.0], "diameter_mm": 6.35, "features": ["neck"]},
            {
                "z_mm": [10.0, 12.0],
                "diameter_mm": 6.35,
                "base_diameter_mm": 6.35,
                "features": ["cap"],
            },
        ],
        "unresolved": [],
        "uncovered_z_mm": [],
    }
    citations = ["kernel: setups.S1.revolved.cap (synthetic native span)"]
    diameter = VALIDATOR["kernel_filled_exposed_diameter"](
        setup, {}, features, row, 10.0, citations
    )
    assert diameter == pytest.approx(6.35)


@pytest.mark.parametrize(
    "corruption",
    [
        "dome_cap",
        "dome_cap_with_nominal",
        "groove_envelope",
        "non_axial_kind",
        "unknown_nominal",
        "uncited_kernel",
        "unknown_feature",
        "outside_stock",
    ],
)
def test_rejects_self_consistent_wrong_exposed_profiles(corruption):
    folder = ROOT / "examples" / "pivot-shaft"
    plan = tomllib.loads((folder / "plan.toml").read_text(encoding="utf-8"))
    features = tomllib.loads((folder / "features.toml").read_text(encoding="utf-8"))
    policy = tomllib.loads((folder / plan["paths"]["policy"]).read_text(encoding="utf-8"))
    report = json.loads((folder / "expected" / "report.json").read_bytes())
    sid = "S3" if corruption in {"dome_cap", "dome_cap_with_nominal"} else "S1"
    setup = next(item for item in plan["setups"] if item["id"] == sid)
    finding = next(
        item for item in report["findings"] if item["rule"] == "stickout" and item["subject"] == sid
    )
    feature = {
        "groove_envelope": "south_relief",
        "non_axial_kind": "pivot_bearing",
    }.get(corruption, "south_dome")
    segment = next(item for item in finding["numbers"]["segments"] if feature in item["features"])
    definition = features["features"][feature]
    if corruption in {"dome_cap", "dome_cap_with_nominal"}:
        segment["diameter_mm"] = segment["base_diameter_mm"] = 6.0
        if corruption == "dome_cap_with_nominal":
            definition["dia_nominal"] = 6.0
    elif corruption == "groove_envelope":
        for key in ("dia_nominal", "nominal_dia", "dia"):
            definition.pop(key, None)
        segment["diameter_mm"] = segment["base_diameter_mm"]
    elif corruption == "non_axial_kind":
        definition["kind"] = "hole"
    elif corruption == "unknown_nominal":
        definition["dia_nominal"] = "unknown"
    elif corruption == "uncited_kernel":
        finding["cite"] = [
            cite
            for cite in finding["cite"]
            if not cite.startswith("kernel: setups.S1.revolved.south_dome (")
        ]
    elif corruption == "unknown_feature":
        segment["features"] = ["undeclared_dome"]
        finding["cite"].append("kernel: setups.S1.revolved.undeclared_dome (forged witness)")
    else:
        definition["base_radius"] = 5.5
        segment["diameter_mm"] = segment["base_diameter_mm"] = 11.0
    diameter = min(item["diameter_mm"] for item in finding["numbers"]["segments"])
    finding["numbers"].update(
        diameter_mm=diameter,
        unsupported_limit_mm=diameter * policy["numbers"]["stickout_ld_max"],
    )
    with pytest.raises(ValueError, match="finished exposed diameter"):
        VALIDATOR["check_stickout"](setup, plan, features, policy, finding)


@pytest.mark.parametrize("action", ["tap", "ream", "drill"])
def test_endpoint_oracle_checks_member_facts_units_and_action_specific_depth(action):
    # Isolated synthetic facts, never a claim about shop inventory.
    operation = {"op": 10, "do": action, "feature": "h", "tool": "cutter/installed"}
    operation.update({"depth_mm": 5.0} if action == "tap" else {"exit_mm": 0.5})
    measured = {"by": "test", "date": "2026-10-03", "instrument": "synthetic gauge"}
    bundle = SimpleNamespace(
        plan={
            "setups": [
                {
                    "id": "S",
                    "stock_state": {"top_z": 10.0, "local_thickness": {"h": 20.0}},
                    "ops": [operation],
                }
            ]
        },
        features={
            "features": {
                "h": {
                    "kind": "threaded_hole" if action == "tap" else "hole",
                    "thru": action != "tap",
                    "depth": [4.0, 8.0],
                },
            }
        },
        inventory={
            "tools": {
                "cutter": {
                    "kind": "drill_set",
                    "dia_mm": 20.0,
                    "point_angle": 118.0,
                    "lead_mm": 2.0,
                    "members": {
                        "installed": {
                            "kind": action,
                            "dia_mm": {"value": 6.0, "measured": measured},
                            "point_angle": {"value": 90.0, "measured": measured},
                            "lead_mm": {"value": 3.175, "measured": measured},
                            "flute_len_in": 1.0,
                        }
                    },
                },
            }
        },
    )
    bundle.feature_definitions = bundle.features["features"]
    findings = {(f.rule, f.subject): f.to_dict() for f in endpoint_findings(bundle)}
    row = findings["blind_depth", "h"]["numbers"]["endpoints"][0]
    expected_tip = {"tap": 5.0, "ream": -13.675, "drill": -13.5}[action]
    assert row["tip_z"] == pytest.approx(expected_tip)
    entries = VALIDATOR["entries_for"](bundle.inventory)
    VALIDATOR["check_endpoints"](bundle.plan, bundle.features, findings, entries)
    field = {"tap": "flute_len_mm", "ream": "lead_mm", "drill": "point_mm"}[action]
    row[field] += 1.0
    if action != "tap":
        row["tip_z"] -= 1.0
    with pytest.raises(ValueError):
        VALIDATOR["check_endpoints"](bundle.plan, bundle.features, findings, entries)


# The pivot-shaft centre as the engine reports it: prepared, contradicted (plan or tool),
# unconfirmed, misplaced or unplaced.
CENTRE_CASES = [
    (None, None, None),
    ("plan", "drill_length_mm", "2.48"),
    ("plan", "mouth_dia_mm", "5.0"),
    ("tool", "point_angle", "40"),
    ("tool", "point_angle", "{ value = 118, verify = true }"),
    ("tool", "verify", "true"),
    ("plan", "at", "[0.0, 0.0, -173.25]"),
    ("plan", "at", "[0.5, 0.0, -173.5]"),
    ("plan", "axis", "[0.0, 0.0, -1.0]"),
    ("plan", "at", '"unknown"'),
]


def centre_findings(tmp_path, where=None, key=None, value=None):
    """The engine's own blind_depth findings for a changed pivot-shaft centre, and a
    validator call that checks them."""
    plan = shaft(tmp_path)
    if where == "plan":
        set_process_key(plan, "plain_end_centre", key, value)
    elif where == "tool":
        set_tool_fact(plan, key, value)
    bundle = load_bundle(plan)
    findings = {(f.rule, f.subject): f.to_dict() for f in endpoint_findings(bundle)}
    entries = VALIDATOR["entries_for"](bundle.inventory)
    (row,) = findings["blind_depth", "plain_end_centre"]["numbers"]["endpoints"]
    return row, lambda: VALIDATOR["check_endpoints"](
        bundle.plan, bundle.features, findings, entries
    )


@pytest.mark.parametrize(("where", "key", "value"), CENTRE_CASES)
def test_centre_oracle_prints_a_quill_depth_only_for_the_centre_its_tool_cuts(
    tmp_path, where, key, value
):
    row, check = centre_findings(tmp_path, where, key, value)
    check()
    # A quill depth the inputs do not derive: one printed for a centre that is not the
    # selected tool's own on the touched end, or a prepared one moved.
    if row["depth_mm"] == "unknown":
        row["depth_mm"] = 1.98 + (3.0 - 1.98) / 2 / math.tan(math.radians(30.0))
    else:
        row["depth_mm"] += 1.0
    row["tip_z"] = row["entry_z"] - row["depth_mm"]
    with pytest.raises(ValueError):
        check()


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("countersink_depth_mm", 0.9),
        ("drill_length_mm", 2.48),
        ("mouth_z", 1.0),
        ("depth_scale", "dro"),
        # Table 6 C already includes the pilot point: no drill-point lead is added.
        ("point_mm", 0.0),
    ],
)
def test_centre_oracle_rejects_a_centre_row_its_inputs_do_not_derive(tmp_path, field, value):
    row, check = centre_findings(tmp_path)
    check()
    row[field] = value
    with pytest.raises(ValueError):
        check()


@pytest.mark.parametrize("fact", ["drill_dia_mm", "drill_length_mm", "point_angle_deg"])
def test_centre_oracle_holds_the_reported_tool_facts_to_the_inventory(tmp_path, fact):
    row, check = centre_findings(tmp_path)
    check()
    row["tool_centre"][fact] += 1.0
    with pytest.raises(ValueError):
        check()


DEEPER = {**DEEP, "depth_over_dia": 8.0, "sfm_factor": 0.3, "cite": "deeper row"}


def speed_finding(data):
    """The engine's speeds_feeds finding for ``data``'s one drill op, and a validator call
    that checks it against the endpoint depths the validator has held to the plan."""
    findings = {
        (f.rule, f.subject): f.to_dict()
        for f in [*endpoint_findings(data), *speeds_feeds.evaluate(data)]
    }
    entries = VALIDATOR["entries_for"](data.inventory)
    VALIDATOR["check_endpoints"](data.plan, data.features, findings, entries)
    setup = data.plan["setups"][0]
    finding = findings["speeds_feeds", "S1:10"]

    def check():
        VALIDATOR["check_speeds"](
            setup,
            setup["ops"][0],
            finding,
            entries,
            data.cutting_data,
            data.feature_definitions,
            VALIDATOR["hole_depths"](findings),
        )

    return finding, check


@pytest.mark.parametrize(
    ("depth_mm", "thickness", "deep", "corruption", "wrong_rpm"),
    [
        # 6.3 x D blind: the derated 750 rpm, reported as the un-derated 1550.
        (40.0, None, (DEEP,), "rpm", 1550),
        # The same, made self-consistent: no derate row, factor or ratio reported.
        (40.0, None, (DEEP,), "fields", 1550),
        # The same, dodging the row by naming an operation no deep-hole row names.
        (40.0, None, (DEEP,), "operation", 1550),
        # 3.1 x D through, by local thickness rather than the tip.
        (None, 20.0, (DEEP,), "rpm", 1550),
        # 9.4 x D: the deepest exceeded tier (450 rpm) governs, not the shallower one.
        (60.0, None, (DEEP, DEEPER), "rpm", 750),
        # Exactly 3 x D is not deeper: the un-derated 1550 stands; a derated one is wrong.
        (3.0 * 6.35, None, (DEEP,), "rpm", 750),
    ],
)
def test_speed_oracle_holds_rpm_to_the_governing_deep_hole_derate(
    depth_mm, thickness, deep, corruption, wrong_rpm
):
    finding, check = speed_finding(drill_bundle(depth_mm=depth_mm, thickness=thickness, deep=deep))
    check()
    row = finding["numbers"]
    if corruption in {"fields", "operation"}:
        for field in ("depth_over_dia", "deep_hole_row", "deep_hole_sfm_factor"):
            row.pop(field)
    if corruption == "operation":
        row["operation"] = "ream"
    row["rpm"] = wrong_rpm
    row["feed_mm_min"] = wrong_rpm * row["flutes"] * row["chip_load_mm_per_tooth"]
    with pytest.raises(ValueError):
        check()


@pytest.mark.parametrize(
    ("depth_mm", "deep"),
    [
        # No planned depth: no ratio, so no derate and no RPM.
        (None, (DEEP,)),
        # Two rows claim the same threshold: no one governs.
        (40.0, (DEEP, {**DEEP, "sfm_factor": 0.7, "cite": "tied row"})),
        # The governing row is marked for verification: it derates, but proves nothing.
        (40.0, ({**DEEP, "verify": True},)),
    ],
)
def test_speed_oracle_never_passes_a_derate_it_cannot_resolve(depth_mm, deep):
    finding, check = speed_finding(drill_bundle(depth_mm=depth_mm, deep=deep))
    check()
    finding["status"] = "pass"
    with pytest.raises(ValueError):
        check()


def aimed_bore(tmp_path, aim=None):
    """The engine's S8 coordinates for the cone's aimed crank bore (plan ``aims.crank_bore``
    asks 39.517 of its 39.34-39.70 printed separation; ``aim`` replaces that requirement
    and value), its crank_bore row and a validator call that checks them against a plan."""
    plan_path = copy_examples(tmp_path) / "cone-pivot-post" / "built-up.toml"
    if aim is not None:
        text = plan_path.read_text(encoding="utf-8")
        authored = 'requirement = "separation"\nvalue_mm = 39.517\n'
        assert authored in text
        plan_path.write_text(text.replace(authored, aim), encoding="utf-8")
    bundle = load_bundle(plan_path)
    setup = next(setup for setup in bundle.plan["setups"] if setup["id"] == "S8")
    finding = next(f for f in coordinates.evaluate(bundle) if f.subject == "S8").to_dict()
    (row,) = (row for row in finding["numbers"]["rows"] if row["feature"] == "crank_bore")
    entries = VALIDATOR["entries_for"](bundle.inventory)

    def check(plan=bundle.plan):
        VALIDATOR["check_coordinates"](
            setup, bundle.features, finding, plan, entries, bundle.inventory
        )

    return bundle, finding, row, check


def move(row, distance_mm):
    """Stand the aimed row ``distance_mm`` further along its aim's own direction."""
    nominal, aimed, shift = row["nominal_setup"], row["setup"], row["aim"]["shift_mm"]
    row["setup"] = [a + (a - n) / shift * distance_mm for n, a in zip(nominal, aimed, strict=True)]
    row["aim"]["shift_mm"] += distance_mm


@pytest.mark.parametrize(
    "corruption",
    [
        # The aim dropped: the bore printed at its CAD station.
        "nominal",
        # Moved the same 0.185 mm, away from the band's reference instead of toward it.
        "reversed",
        # Self-consistent: a CAD separation 0.1 mm short, so the bore moved 0.1 mm further.
        "nominal_distance",
        # Self-consistent: the report asks 39.6 where the plan asks 39.517.
        "asked_value",
        # A target the plan never aimed: the plan names no aim for it.
        "unaimed_plan",
    ],
)
def test_coordinate_oracle_stands_an_aimed_target_where_plan_aims_and_its_band_put_it(
    tmp_path, corruption
):
    bundle, finding, row, check = aimed_bore(tmp_path)
    check()
    aim, plan = row["aim"], bundle.plan
    if corruption == "nominal":
        row["setup"] = row.pop("nominal_setup")
        row.pop("aim")
    elif corruption == "reversed":
        move(row, -2 * aim["shift_mm"])
    elif corruption == "nominal_distance":
        move(row, 0.1)
        aim["nominal_mm"] -= 0.1
    elif corruption == "asked_value":
        move(row, 39.6 - aim["value_mm"])
        aim["value_mm"] = aim["value"] = 39.6
    else:
        plan = {key: value for key, value in plan.items() if key != "aims"}
    with pytest.raises(ValueError):
        check(plan)


@pytest.mark.parametrize("corruption", ["moved", "passed"])
def test_coordinate_oracle_holds_an_aim_its_band_cannot_place_to_its_nominal_target(
    tmp_path, corruption
):
    # An in-band diameter aim: the bore holds its separation, not its diameter, from
    # height_from, so the aim names no direction to move the target in.
    _, finding, row, check = aimed_bore(tmp_path, 'requirement = "dia"\nvalue_mm = 11.43\n')
    check()
    # Left at its CAD station the bore's 39.332 separation is also below the printed band.
    assert finding["status"] == "error" and "nominal_setup" not in row
    if corruption == "moved":
        # Moved anyway, as if it were the separation it does not name.
        row["nominal_setup"] = list(row["setup"])
        row["setup"][0] -= 0.185
        row["aim"].pop("why")
    else:
        finding["status"] = "pass"
    with pytest.raises(ValueError):
        check()


def test_validator_rejects_a_check_without_its_feature_requirement():
    plan = {
        "setups": [
            {"id": "S3", "ops": [{"op": 10, "feature": "dome", "checks": {"length": "calipers"}}]}
        ]
    }
    features = {"features": {"dome": {"requirements": ["height"]}}}
    with pytest.raises(ValueError, match="dome has no requirement length"):
        VALIDATOR["check_inspection_declarations"](plan, features, {})


@pytest.mark.parametrize("status,missing", [("pass", True), ("unknown", False), (None, None)])
def test_validator_rejects_silently_dropped_or_cleared_missing_requirement(status, missing):
    plan = {
        "setups": [
            {
                "id": "S3",
                "ops": [
                    {
                        "op": 30,
                        "feature": "bearing",
                        "missing_requirements": {"length": "calipers"},
                    }
                ],
            }
        ]
    }
    features = {"features": {"bearing": {"requirements": ["dia"]}}}
    findings = {
        ("inspection", "bearing:length"): {
            "status": status,
            "numbers": {"missing_requirement": missing},
        }
    }
    with pytest.raises(ValueError, match="missing requirement inspection"):
        VALIDATOR["check_inspection_declarations"](plan, features, findings)


@pytest.mark.parametrize(
    "missing",
    [
        ("tool_resolves", "S4:40"),
        ("inspection", "crank_socket:dia"),
        ("joint_fit", "S7"),
        ("joint_assembly", "S7"),
    ],
)
def test_built_up_subject_contract_excludes_manual_assembly_but_keeps_joint_debt(missing):
    plan, features, inventory, _, report = cone_inputs()
    findings = {(row["rule"], row["subject"]): row for row in report["findings"]}
    # The exported fixture's fit action has tool="unknown", but no cutting assembly.
    VALIDATOR["check_subjects"](plan, features, findings, inventory)
    del findings[missing]
    with pytest.raises(ValueError, match=f"missing finding {missing[0]}:{missing[1]}"):
        VALIDATOR["check_subjects"](plan, features, findings, inventory)


@pytest.mark.parametrize(
    "corruption", ["fit_pass", "missing", "socket", "assembly_pass", "branches"]
)
def test_built_up_joint_report_cannot_clear_numeric_debt_or_change_identity(corruption):
    plan, features, _, _, report = cone_inputs()
    findings = {(row["rule"], row["subject"]): row for row in report["findings"]}
    VALIDATOR["check_joint_declarations"](plan, features, findings)
    setup = next(setup for setup in plan["setups"] if setup["id"] == "S7")
    fit = findings["joint_fit", "S7"]
    assembly = findings["joint_assembly", "S7"]
    if corruption in {"fit_pass", "missing", "assembly_pass"}:
        # The shipped joint resolves, so declare numeric debt in the plan: the
        # report must then carry it and neither row may approve.
        setup["joint"]["clearance_mm"] = "unknown"
        result = VALIDATOR["fit"](SimpleNamespace(plan=plan, features=features), setup)
        fit["numbers"].update(
            band_mm="unknown",
            guaranteed_mm="unknown",
            engagement_mm="unknown",
            engagement_dia_mm="unknown",
            missing=result["missing"],
        )
        fit["status"], assembly["status"] = "unknown", "unknown"
        VALIDATOR["check_joint_declarations"](plan, features, findings)
    if corruption == "fit_pass":
        fit["status"] = "pass"
    elif corruption == "missing":
        fit["numbers"]["missing"] = []
    elif corruption == "socket":
        fit["numbers"]["socket"] = fit["numbers"]["spigot"]
    elif corruption == "assembly_pass":
        assembly["status"] = "pass"
    else:
        assembly["numbers"]["stock_in"].reverse()
    with pytest.raises(ValueError, match="joint|assembly"):
        VALIDATOR["check_joint_declarations"](plan, features, findings)


@pytest.mark.parametrize("corruption", ["shared_ancestor", "wrong_role", "finished_face"])
def test_joint_identity_and_exported_face_contract_remain_strict(corruption):
    plan, features, inventory, _, report = cone_inputs()
    findings = {(row["rule"], row["subject"]): row for row in report["findings"]}
    setup = next(setup for setup in plan["setups"] if setup["id"] == "S7")
    if corruption == "shared_ancestor":
        setup["stock_in"] = ["S6", "S4"]
    elif corruption == "wrong_role":
        setup["joint"]["socket"] = "crank_spigot"
    else:
        features["features"]["crank_boss"]["faces"] = ["plan.joint_features.crank_spigot"]
    with pytest.raises(ValueError, match="ancestor|kind cylinder_bore|finished STEP faces"):
        VALIDATOR["check_subjects"](plan, features, findings, inventory)


@pytest.mark.parametrize("rule", ["joint_fit", "joint_assembly", "centre_support"])
def test_unresolved_always_required_rule_needs_no_shop_policy_permission(rule):
    plan, features, _, _, _ = cone_inputs()
    report = {"findings": [{"rule": rule, "subject": "S7", "status": "unknown", "numbers": {}}]}
    assert VALIDATOR["report_exit"](report, {"required": {}}, plan, features) == 4


@pytest.mark.parametrize(
    ("selector", "subject"),
    [("holes", "crank_socket"), ("toleranced_features", "crank_spigot:dia")],
)
def test_required_selectors_include_transient_joint_requirements(selector, subject):
    plan, features, _, _, _ = cone_inputs()
    finding = {"rule": "inspection", "subject": subject, "numbers": {}}
    assert VALIDATOR["required_finding"](
        finding, {"required": {"inspection": selector}}, plan, features
    )


def test_joint_checks_use_operative_requirements_without_inventing_drawing_fields():
    plan, features, _, _, report = cone_inputs()
    findings = {(row["rule"], row["subject"]): row for row in report["findings"]}
    setup = next(setup for setup in plan["setups"] if setup["id"] == "S3")
    op = {"op": 60, "feature": "crank_spigot", "checks": {"dia": "calipers"}}
    setup["ops"].append(op)
    VALIDATOR["check_inspection_declarations"](plan, features, findings)
    op["missing_requirements"] = op.pop("checks")
    with pytest.raises(ValueError, match="crank_spigot.dia is an exported requirement"):
        VALIDATOR["check_inspection_declarations"](plan, features, findings)


@pytest.mark.parametrize("kernel_status,status", [("unavailable", "unknown"), ("error", "error")])
def test_joint_kernel_failure_cannot_be_approved_without_assembly_evidence(kernel_status, status):
    plan, features, _, _, report = cone_inputs()
    findings = {(row["rule"], row["subject"]): row for row in report["findings"]}
    assembly = findings["joint_assembly", "S7"]
    assembly["numbers"] = {"kernel_status": kernel_status}
    assembly["status"] = status
    VALIDATOR["check_joint_declarations"](plan, features, findings)
    assembly["status"] = "pass"
    with pytest.raises(ValueError, match="unavailable kernel cannot approve"):
        VALIDATOR["check_joint_declarations"](plan, features, findings)
