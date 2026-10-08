"""Regression coverage for authored report validation against plan touch surfaces."""

import copy
import functools
import json
import math
import runpy
import tomllib
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest
from test_cli import copy_examples
from test_deep_hole_speed import DEEP, drill_bundle
from test_operative_surface import plan as surface_plan
from test_process_features import set_process_key, set_tool_fact, shaft
from test_sheet_fixture import END_MILL, MAKE_OP

from prechips.findings import Finding
from prechips.inputs import load_bundle
from prechips.kernel import run_geometry
from prechips.model import Inventory
from prechips.rules import (
    RULES,
    Rule,
    coordinates,
    headroom,
    indexing,
    joints,
    prepared_blank,
    speeds_feeds,
    stickout,
    tool_resolves,
    zero_recipe,
)
from prechips.rules._bench import manual_bench
from prechips.rules.resolution import inch_sizes, resolve, setup_items
from prechips.rules.resolution import uncertain as resolved_uncertain
from prechips.rules.tip_endpoints import evaluate as endpoint_findings

ROOT = Path(__file__).resolve().parents[1]
VALIDATOR = runpy.run_path(str(ROOT / "scripts" / "validate_examples.py"))


def shifted(value):
    """``value`` moved 1 mm: a number, or a measured-edge ``M ±n`` reading's offset."""
    if isinstance(value, str):
        offset = float(value.removeprefix("M ")) + 1.0
        return "M " + f"{offset:+.6f}".rstrip("0").rstrip(".")
    return value + 1.0


def zero_case(part, setup_id):
    """``(setup, finding, entries, own)`` for ``check_zero`` on one example setup: the
    plan's setup, its expected ``zero_check`` finding and the validator's own inputs
    (plan, manifest, inventory, policy and its own kernel run)."""
    folder = ROOT / "examples" / part
    plan = tomllib.loads((folder / "plan.toml").read_text(encoding="utf-8"))
    features = tomllib.loads((folder / "features.toml").read_text(encoding="utf-8"))
    inventory = tomllib.loads((folder / plan["paths"]["inventory"]).read_text(encoding="utf-8"))
    policy = tomllib.loads((folder / plan["paths"]["policy"]).read_text(encoding="utf-8"))
    report = json.loads((folder / "expected" / "report.json").read_bytes())
    setup = next(s for s in plan["setups"] if s["id"] == setup_id)
    finding = next(
        f for f in report["findings"] if f["rule"] == "zero_check" and f["subject"] == setup_id
    )
    kernel = VALIDATOR["independent_kernel"](folder / "plan.toml")
    own = VALIDATOR["zero_inputs"](plan, features, inventory, policy, kernel)
    return setup, finding, VALIDATOR["Entries"](inventory), own


@pytest.mark.parametrize(
    ("part", "feature", "action", "reason"),
    [
        ("pivot-bracket", "ear_relief", "rough_pocket", "touched edge"),
        ("pivot-bracket", "outer_face", "face", "touched edge"),
        ("pivot-shaft", "pivot_bearing", "finish_turn", "touched edge"),
        # The bench shoulder-to-stub reading M, not its nominal length, sets Z.
        ("pivot-shaft", "north_dome", "face", "measured-edge"),
    ],
)
def test_rejects_self_consistent_wrong_z_edge(freecad_kernel, part, setup_id, reason):
    setup, finding, entries, own = zero_case(part, setup_id)
    VALIDATOR["check_zero"](setup, finding, entries, own)

    corrupted = copy.deepcopy(finding)
    row = corrupted["numbers"]["axes"]["z"]
    fields = ("edge_mm", "offset_mm", "axis_set", "check_reading", "mirrored_reading")
    fields += ("check_expression", "mirrored_expression")
    for field in fields:
        if field in row:
            row[field] = shifted(row[field])

    with pytest.raises(ValueError, match=reason):
        VALIDATOR["check_zero"](setup, corrupted, entries, own)


def cone_inputs(*, fresh_pure=False):
    folder = ROOT / "examples" / "cone-pivot-post"
    bundle = load_bundle(folder / "built-up.toml")
    report = json.loads((folder / "expected" / "built-up" / "report.json").read_bytes())
    if fresh_pure:
        # These checks consume rule evidence, not frozen SHA/path bindings.
        # Refresh only non-kernel findings; keep native assembly evidence intact.
        bench_bundle = replace(
            bundle,
            plan={
                **bundle.plan,
                "setups": [setup for setup in bundle.plan["setups"] if manual_bench(bundle, setup)],
            },
        )
        derived = [
            *zero_recipe.evaluate(bundle),
            *joints.evaluate_fit(bundle),
            *coordinates.evaluate(bench_bundle),
            *headroom.evaluate(bench_bundle),
        ]
        refreshed = {(row.rule, row.subject): row.to_dict() for row in derived}
        report["findings"] = [
            refreshed.pop((row["rule"], row["subject"]), row) for row in report["findings"]
        ] + list(refreshed.values())
    return bundle.plan, bundle.features, bundle.inventory, bundle.policy, report


@pytest.mark.parametrize("corruption", ["nearest", "spaces", "basic_band", "closure"])
def test_rejects_cone_indexing_arithmetic_even_when_unverified(corruption):
    plan, features, inventory, _, report = cone_inputs()
    setup = next(s for s in plan["setups"] if s["id"] == "S5")
    finding = next(
        f for f in report["findings"] if f["rule"] == "indexing" and f["subject"] == "S5"
    )
    entries = VALIDATOR["Entries"](inventory)
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


def test_rejects_unsourced_finished_diameter_in_unbound_profile(freecad_kernel):
    plan, features, inventory, policy, report = cone_inputs()
    setup = next(s for s in plan["setups"] if s["id"] == "S1")
    finding = next(
        f for f in report["findings"] if f["rule"] == "stickout" and f["subject"] == "S1"
    )
    kernel = VALIDATOR["independent_kernel"](
        ROOT / "examples" / "cone-pivot-post" / "built-up.toml"
    )
    VALIDATOR["check_stickout"](setup, plan, features, inventory, policy, finding, kernel)
    corrupted = copy.deepcopy(finding)
    corrupted["numbers"]["diameter_mm"] = 21.93
    with pytest.raises(ValueError):
        VALIDATOR["check_stickout"](setup, plan, features, inventory, policy, corrupted, kernel)


def test_accepts_cited_kernel_revolved_bases_without_declared_diameters():
    documents = {
        path.resolve(): tomllib.loads(path.read_text(encoding="utf-8"))
        for path in (ROOT / "examples").rglob("*.toml")
    }
    code, missing = VALIDATOR["validate_fixture"]("pivot-shaft", documents)
    assert code == 0
    assert missing == []


def test_exposed_profile_converts_inch_dia_alias_and_declared_dome_base():
    # Synthetic manifest and kernel facts: an inch shaft declared by its ``dia`` alias and
    # a dome by its base radius, each measured revolved about setup Z.
    setup = {
        "id": "S1",
        "frame": "F",
        "stock_state": {"north_end_z": 0.0, "south_end_z": 12.0},
        "hold": {"stickout_mm": 12.0},
        "ops": [],
    }
    features = {
        "units": "in",
        "frames": {"F": {"origin": [0.0, 0.0, 0.0]}},
        "features": {
            "neck": {"kind": "shaft", "dia": 0.25},
            "cap": {"kind": "dome", "base_radius": 0.125},
        },
    }
    revolved = {
        "neck": {"z_mm": [0.0, 10.0]},
        "cap": {"z_mm": [10.0, 12.0], "end_radii_mm": [3.175, 0.0]},
    }
    facts = {"status": "ok", "setups": {"S1": {"revolved": revolved}}}
    profile = VALIDATOR["kernel_exposed_profile"](
        setup, {"setups": [setup]}, features, 10.0, lambda: facts
    )
    assert profile["diameter_mm"] == pytest.approx(6.35)
    assert [(s["z_mm"], s["features"]) for s in profile["segments"]] == [
        ([0.0, 10.0], ["neck"]),
        ([10.0, 12.0], ["cap"]),
    ]
    assert [s["diameter_mm"] for s in profile["segments"]] == pytest.approx([6.35, 6.35])


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
        # Self-consistent: the shoulder stretched over the 5.7 mm relief, dropped, so the
        # least exposed diameter (and the L/D limit) reads the 6.35 mm journal instead.
        "stretched_shoulder",
    ],
)
def test_rejects_self_consistent_wrong_exposed_profiles(freecad_kernel, corruption):
    plan, features, inventory, policy, report = pivot_shaft_inputs()
    folder = ROOT / "examples" / "pivot-shaft"
    kernel = VALIDATOR["independent_kernel"](folder / "plan.toml")
    sid = "S3" if corruption in {"dome_cap", "dome_cap_with_nominal"} else "S1"
    setup = next(item for item in plan["setups"] if item["id"] == sid)
    finding = next(
        item for item in report["findings"] if item["rule"] == "stickout" and item["subject"] == sid
    )
    VALIDATOR["check_stickout"](
        setup, plan, features, inventory, policy, copy.deepcopy(finding), kernel
    )
    segments = finding["numbers"]["segments"]
    feature = {
        "groove_envelope": "south_relief",
        "non_axial_kind": "pivot_bearing",
    }.get(corruption, "south_dome")
    segment = next(item for item in segments if feature in item["features"])
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
    elif corruption == "stretched_shoulder":
        shoulder = next(item for item in segments if item["features"] == ["shoulder_od"])
        relief = next(item for item in segments if item["features"] == ["south_relief"])
        shoulder["z_mm"][1] = relief["z_mm"][1]
        segments.remove(relief)
        finding["numbers"]["diameter_features"] = ["pivot_bearing"]
    else:
        definition["base_radius"] = 5.5
        segment["diameter_mm"] = segment["base_diameter_mm"] = 11.0
    diameter = min(item["diameter_mm"] for item in segments)
    finding["numbers"].update(
        diameter_mm=diameter,
        unsupported_limit_mm=diameter * policy["numbers"]["stickout_ld_max"],
    )
    with pytest.raises(ValueError, match="finished exposed diameter"):
        VALIDATOR["check_stickout"](setup, plan, features, inventory, policy, finding, kernel)


def pivot_shaft_inputs():
    folder = ROOT / "examples" / "pivot-shaft"
    plan = tomllib.loads((folder / "plan.toml").read_text(encoding="utf-8"))
    features = tomllib.loads((folder / "features.toml").read_text(encoding="utf-8"))
    inventory = tomllib.loads((folder / plan["paths"]["inventory"]).read_text(encoding="utf-8"))
    policy = tomllib.loads((folder / plan["paths"]["policy"]).read_text(encoding="utf-8"))
    report = json.loads((folder / "expected" / "report.json").read_bytes())
    return plan, features, inventory, policy, report


@pytest.mark.parametrize(
    "case", ["support_unselected", "support_unverified", "ratio_halved", "report_named_support"]
)
def test_stickout_verdict_and_support_come_from_the_plan_hold_and_inventory(freecad_kernel, case):
    # pivot-shaft S1 holds 167.5 mm out against a 22.8 mm unsupported limit and passes
    # only on its selected, verified dead centre; S2 holds 14 mm, inside its limit. Change
    # what the plan selects, the inventory verifies or the policy allows: the stick-out
    # row derived from those inputs is accepted, and the shipped approval is not.
    plan, features, inventory, policy, report = pivot_shaft_inputs()
    kernel = VALIDATOR["independent_kernel"](ROOT / "examples" / "pivot-shaft" / "plan.toml")
    sid = "S1" if case.startswith("support_") else "S2"
    setup = next(item for item in plan["setups"] if item["id"] == sid)
    shipped = next(
        item for item in report["findings"] if item["rule"] == "stickout" and item["subject"] == sid
    )
    assert shipped["status"] == "pass"
    derived = copy.deepcopy(shipped)
    row = derived["numbers"]
    if case == "support_unselected":
        setup["hold"]["support"] = "none"  # the follow rest alone is no stick-out support
        row["supports"] = [s for s in row["supports"] if s["reference"] == "follow_rest"]
        row["support_status"], derived["status"] = "not_applicable", "error"
    elif case == "support_unverified":
        inventory["fixtures"]["dead_centre_tailstock_mt3"]["verify"] = True
        row["supports"][0]["status"] = "unknown"
        row["support_status"], derived["status"] = "unknown", "unknown"
    else:
        policy["numbers"]["stickout_ld_max"] = 2.0
        row.update(stickout_ld_max=2.0, unsupported_limit_mm=row["diameter_mm"] * 2.0)
        shipped["numbers"].update(
            stickout_ld_max=2.0, unsupported_limit_mm=row["diameter_mm"] * 2.0
        )
        derived["status"] = "error"
        if case == "report_named_support":
            shipped["numbers"]["support_status"] = "pass"
            shipped["numbers"]["supports"] = [
                {"reference": "tailstock", "kind": "accessory", "status": "pass", "source": "x"}
            ]
    VALIDATOR["check_stickout"](setup, plan, features, inventory, policy, derived, kernel)
    with pytest.raises(ValueError):
        VALIDATOR["check_stickout"](setup, plan, features, inventory, policy, shipped, kernel)


def test_stickout_cannot_call_a_lathe_hold_inapplicable(freecad_kernel):
    plan, features, inventory, policy, report = pivot_shaft_inputs()
    kernel = VALIDATOR["independent_kernel"](ROOT / "examples" / "pivot-shaft" / "plan.toml")
    setup = next(item for item in plan["setups"] if item["id"] == "S1")
    finding = next(
        item
        for item in report["findings"]
        if item["rule"] == "stickout" and item["subject"] == "S1"
    )
    VALIDATOR["check_stickout"](setup, plan, features, inventory, policy, finding, kernel)
    finding["status"] = "not_applicable"
    with pytest.raises(ValueError):
        VALIDATOR["check_stickout"](setup, plan, features, inventory, policy, finding, kernel)


def test_stickout_reads_a_machine_selected_by_its_category_as_that_machine(freecad_kernel):
    """A setup selecting its machine as ``machines.<key>`` is on that machine, as on its
    bare key: the engine's stick-out finding (a lathe's verdict, another machine's
    inapplicable) is accepted with its own status, and no other status is."""
    plan_path = ROOT / "examples" / "pivot-shaft" / "plan.toml"
    bundle = load_bundle(plan_path)
    assert run_geometry(bundle)["status"] == "ok"
    kernel = VALIDATOR["independent_kernel"](plan_path)
    for setup in bundle.plan["setups"]:
        setup["machine"] = f"machines.{setup['machine']}"
    native = {f.subject: json.loads(json.dumps(f.to_dict())) for f in stickout.evaluate(bundle)}
    assert {row["status"] for row in native.values()} - {"not_applicable"}
    for setup in bundle.plan["setups"]:
        args = (setup, bundle.plan, bundle.features, bundle.inventory, bundle.policy)
        finding = native[setup["id"]]
        VALIDATOR["check_stickout"](*args, finding, kernel)
        for forged in sorted({"pass", "unknown", "error", "not_applicable"} - {finding["status"]}):
            with pytest.raises(ValueError):
                VALIDATOR["check_stickout"](*args, {**finding, "status": forged}, kernel)


@pytest.fixture(scope="module")
def shaft_bundle(freecad_kernel):
    bundle = load_bundle(ROOT / "examples" / "pivot-shaft" / "plan.toml")
    facts = run_geometry(bundle)
    assert facts["status"] == "ok", facts.get("reason")
    return bundle


@pytest.mark.parametrize("sid", ["S1", "S2"])
@pytest.mark.parametrize(
    "case",
    [
        "fallback_unverified",
        "fallback_verify_unknown",
        "fallback_dia_unknown",
        "held_unknown",
        "held_zero",
        "stock_state_unknown",
        "fallback_verified",
    ],
)
def test_stickout_holds_only_a_verified_held_diameter(shaft_bundle, sid, case):
    # With no od_mm in the setup's stock state the held diameter falls back to the
    # stock's dia_mm, which is evidence only when the stock's form is verified. The
    # engine's own stick-out row is accepted: unknown for an unverified, unknown or
    # unusable held diameter, a pass on the verified fallback. A row that holds the
    # unverified fallback (or any number the plan does not give) as evidence and
    # passes is not.
    bundle = copy.deepcopy(shaft_bundle)
    stock = bundle.plan["stock"]
    setup = next(item for item in bundle.plan["setups"] if item["id"] == sid)
    fallback = stock["dia_mm"]
    if case.startswith("fallback"):
        setup["stock_state"].pop("od_mm", None)
        stock["form_verify"] = {
            "fallback_unverified": True,
            "fallback_verify_unknown": "unknown",
        }.get(case, False)
        if case == "fallback_dia_unknown":
            stock["dia_mm"] = "unknown"
    elif case == "held_unknown":
        setup["stock_state"]["od_mm"] = "unknown"
    elif case == "held_zero":
        setup["stock_state"]["od_mm"] = 0
    else:
        setup["stock_state"] = "unknown"
    native = next(f.to_dict() for f in stickout.evaluate(bundle) if f.subject == sid)

    def check(finding):
        VALIDATOR["check_stickout"](
            setup,
            bundle.plan,
            bundle.features,
            bundle.inventory,
            bundle.policy,
            finding,
            lambda: bundle.kernel,
        )

    check(native)
    if case == "fallback_verified":
        assert (native["status"], native["numbers"]["held_diameter_mm"]) == ("pass", fallback)
        return
    assert native["status"] == "unknown"
    forged = copy.deepcopy(native)
    forged["status"] = "pass"
    forged["numbers"]["held_diameter_mm"] = fallback
    with pytest.raises(ValueError):
        check(forged)


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
    entries = VALIDATOR["Entries"](bundle.inventory)
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
    """The engine's own blind_depth findings for a changed pivot-shaft centre: its endpoint
    row, a validator call that checks them, and the centre's finding."""
    plan = shaft(tmp_path)
    if where == "plan":
        set_process_key(plan, "plain_end_centre", key, value)
    elif where == "tool":
        set_tool_fact(plan, key, value)
    bundle = load_bundle(plan)
    findings = {(f.rule, f.subject): f.to_dict() for f in endpoint_findings(bundle)}
    entries = VALIDATOR["Entries"](bundle.inventory)
    finding = findings["blind_depth", "plain_end_centre"]
    (row,) = finding["numbers"]["endpoints"]
    return (
        row,
        lambda: VALIDATOR["check_endpoints"](bundle.plan, bundle.features, findings, entries),
        finding,
    )


@pytest.mark.parametrize(("where", "key", "value"), CENTRE_CASES)
def test_centre_oracle_prints_a_quill_depth_only_for_the_centre_its_tool_cuts(
    tmp_path, where, key, value
):
    row, check, _ = centre_findings(tmp_path, where, key, value)
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
    row, check, _ = centre_findings(tmp_path)
    check()
    row[field] = value
    with pytest.raises(ValueError):
        check()


@pytest.mark.parametrize("fact", ["drill_dia_mm", "drill_length_mm", "point_angle_deg"])
def test_centre_oracle_holds_the_reported_tool_facts_to_the_inventory(tmp_path, fact):
    row, check, _ = centre_findings(tmp_path)
    check()
    row["tool_centre"][fact] += 1.0
    with pytest.raises(ValueError):
        check()


def test_centre_oracle_takes_the_touched_surface_from_the_plan_not_the_report(tmp_path):
    # The centre misplaced 0.25 into the end that S0 op 10 faces to setup Z 0: the engine
    # errors and prints no quill depth. Made self-consistent, the report claims the
    # touched surface is where the buried mouth lies and passes the prepared depth.
    row, check, finding = centre_findings(tmp_path, "plan", "at", "[0.0, 0.0, -173.25]")
    check()
    row["entry_z"] = row["mouth_z"]
    row["depth_mm"] = row["drill_length_mm"] + row["countersink_depth_mm"]
    row["tip_z"] = row["entry_z"] - row["depth_mm"]
    finding["status"] = "pass"
    with pytest.raises(ValueError):
        check()


@pytest.mark.parametrize("corruption", ["surface", "source"])
def test_endpoint_oracle_takes_a_blind_hole_entry_from_the_plan(corruption):
    data = drill_bundle(depth_mm=40.0)
    findings = {(f.rule, f.subject): f.to_dict() for f in endpoint_findings(data)}
    entries = VALIDATOR["Entries"](data.inventory)
    VALIDATOR["check_endpoints"](data.plan, data.features, findings, entries)
    (row,) = findings["blind_depth", "hole"]["numbers"]["endpoints"]
    if corruption == "surface":
        # The whole hole moved 1 mm into the part, its depth unchanged: self-consistent.
        for field in ("entry_z", "tip_z", "dro_entry_z", "dro_tip_z"):
            row[field] -= 1.0
    else:
        # The right Z, credited to a surface the plan never leaves there.
        row["entry_from"] = "S1 op 10 to_z"
    with pytest.raises(ValueError):
        VALIDATOR["check_endpoints"](data.plan, data.features, findings, entries)


def printed_endpoint(data):
    """The engine's one endpoint row for ``data``'s hole and a validator call on it."""
    findings = {(f.rule, f.subject): f.to_dict() for f in endpoint_findings(data)}
    entries = VALIDATOR["Entries"](data.inventory)
    (row,) = findings["blind_depth", "hole"]["numbers"]["endpoints"]

    def check():
        VALIDATOR["check_endpoints"](data.plan, data.features, findings, entries)

    check()
    return row, check


@pytest.mark.parametrize(
    ("thickness", "forged"),
    [
        # The printed blind tip 1 mm deeper than the planned one; every analytical Z intact.
        (None, {"dro_tip_z": -1.0}),
        # The printed entry and tip both 1 mm into the part: the same depth, self-consistent.
        (None, {"dro_entry_z": -1.0, "dro_tip_z": -1.0}),
        # The depth the printed tip leaves claimed 1 mm deeper than it is.
        (None, {"dro_depth_mm": 1.0}),
        # A through hole's printed exit face and tip moved together.
        (20.0, {"dro_exit_face": -1.0, "dro_tip_z": -1.0}),
        # The break-through the printed tip leaves claimed 1 mm longer.
        (20.0, {"dro_exit_mm": 1.0}),
    ],
)
def test_endpoint_oracle_holds_the_printed_endpoint_to_the_plan_on_the_grid(thickness, forged):
    row, check = printed_endpoint(
        drill_bundle(depth_mm=None if thickness else 40.0, thickness=thickness)
    )
    for field, delta in forged.items():
        row[field] += delta
    with pytest.raises(ValueError):
        check()


def test_endpoint_oracle_holds_the_depth_band_floor_the_traveler_stops_on():
    # A 38-42 depth band: the printed floor is what the traveler's STOP box compares the
    # printed depth against. Reported unknown, the box can never print.
    data = drill_bundle(depth_mm=40.0)
    data.features["features"]["hole"]["depth"] = [38.0, 42.0]
    row, check = printed_endpoint(data)
    assert row["depth_floor_mm"] == 38.0
    row["depth_floor_mm"] = "unknown"
    with pytest.raises(ValueError):
        check()


@pytest.mark.parametrize("producer_grid", [0.01, 0.1])
def test_endpoint_oracle_starts_a_hole_on_the_face_its_producer_cut_on_its_own_grid(
    tmp_path, producer_grid
):
    # S1, a coarser mill, faces the hole's entry to -2.27825; S2 (0.005 grid) drills a
    # 2.95-3.00 deep blind hole from it. That face stands where S1's DRO stopped, rounded up
    # on S1's grid, not where S2's grid would round the nominal.
    path = surface_plan(tmp_path, coarse=True, depth="[2.95, 3.0]")
    inventory = path.with_name("inventory.toml")
    text = inventory.read_text(encoding="utf-8")
    assert "resolution_mm = 0.01\n" in text
    coarse = text.replace("resolution_mm = 0.01\n", f"resolution_mm = {producer_grid}\n")
    inventory.write_text(coarse, encoding="utf-8")
    data = load_bundle(path)
    row, check = printed_endpoint(data)
    entries = VALIDATOR["Entries"](data.inventory)
    consumer = next(setup for setup in data.plan["setups"] if setup["id"] == "S2")
    grid = VALIDATOR["dro_grid"](consumer, data.features, entries)
    # Forged: the entry rounded on S2's grid and the drill run from there with its depth
    # claimed unchanged, so its tip runs past the 3.00 mm limit below the face S1 cut.
    entry = VALIDATOR["dro_up"](row["entry_z"], grid)
    assert entry < row["dro_entry_z"]
    planned_tip = row["tip_z"] + entry - row["entry_z"]
    tip = VALIDATOR["dro_up"](planned_tip, grid)
    row.update(dro_entry_z=entry, dro_tip_z=tip, dro_depth_mm=row["depth_mm"] - (tip - planned_tip))
    with pytest.raises(ValueError):
        check()


def test_centre_oracle_holds_the_printed_quill_endpoint(tmp_path):
    # The prepared pivot-shaft centre, its printed tip 0.5 mm deeper and its printed
    # depth to match: the traveler would send the quill past the Table 6 depth.
    row, check, _ = centre_findings(tmp_path)
    check()
    row["dro_tip_z"] -= 0.5
    row["dro_depth_mm"] += 0.5
    with pytest.raises(ValueError):
        check()


DEEPER = {**DEEP, "depth_over_dia": 8.0, "sfm_factor": 0.3, "cite": "deeper row"}


def speed_finding(data):
    """The engine's speeds_feeds finding for ``data``'s one drill op, and a validator call
    that checks it against the hole depths the validator derives from the plan."""
    findings = {
        (f.rule, f.subject): f.to_dict()
        for f in [*endpoint_findings(data), *speeds_feeds.evaluate(data)]
    }
    entries = VALIDATOR["Entries"](data.inventory)
    depths = VALIDATOR["check_endpoints"](data.plan, data.features, findings, entries)
    setup = data.plan["setups"][0]
    finding = findings["speeds_feeds", "S1:10"]

    def check():
        VALIDATOR["check_speeds"](
            data.plan,
            data.features,
            setup,
            setup["ops"][0],
            finding,
            entries,
            data.cutting_data,
            data.feature_definitions,
            depths,
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


def resped(row, sfm):
    """Recompute ``row``'s derated RPM and feed per tooth from ``sfm`` and its own spindle
    range, diameter, flutes and chip load: a self-consistent report."""
    raw = 12 * sfm * row["deep_hole_sfm_factor"] / (math.pi * row["diameter_in"])
    row["sfm"] = sfm
    row["rpm"] = round(max(row["rpm_min"], min(row["rpm_max"], raw)) / 50) * 50
    row["feed_mm_min"] = row["rpm"] * row["flutes"] * row["chip_load_mm_per_tooth"]


UNRELATED = {
    "material_class": "low_carbon_steel",
    "tool_material": "HSS",
    "operation": "drill",
    "diameter_range": [3.0, 13.0],
    "sfm": 350.0,
    "chip_load_mm_per_tooth": 0.05,
    "cite": "unrelated row",
}


@pytest.mark.parametrize(
    "corruption",
    [
        # The spindle floor raised to 800 so the 750 rpm drill is clamped up to it.
        "machine_bound",
        # A cited 350 sfm row for another operation, or for another tool material.
        "other_operation",
        "other_tool_material",
        # One more flute than the inventory drill has, its feed recomputed.
        "flutes",
        # The inventory drill's diameter is now unknown, the formerly valid row kept.
        "unknown_diameter",
    ],
)
def test_speed_oracle_takes_every_operand_from_the_inputs_not_the_report(corruption):
    data = drill_bundle(depth_mm=40.0)
    finding, check = speed_finding(data)
    check()
    row = finding["numbers"]
    if corruption == "machine_bound":
        row["rpm_min"] = 800
        resped(row, row["sfm"])
        assert row["rpm"] == 800
    elif corruption in {"other_operation", "other_tool_material"}:
        key, value = {"other_operation": ("operation", "ream")}.get(
            corruption, ("tool_material", "carbide")
        )
        data.cutting_data["cut"].append({**UNRELATED, key: value})
        resped(row, UNRELATED["sfm"])
    elif corruption == "flutes":
        row["flutes"] += 1
        resped(row, row["sfm"])
    else:
        data.inventory["tools"]["drill"]["dia_mm"] = "unknown"
    with pytest.raises(ValueError):
        check()


@pytest.mark.parametrize("flag", [True, "unknown"])
@pytest.mark.parametrize("debt", ["machine", "tool", "material"])
def test_speed_oracle_never_passes_a_row_on_unverified_inputs(debt, flag):
    # The engine leaves the derated 750 rpm unknown on an input flagged for verification
    # or left unknown; the report claims a pass and drops the verification flags it prints.
    data = drill_bundle(depth_mm=40.0)
    if debt == "material":
        data.plan["stock"]["material_verify"] = flag
    else:
        data.inventory[f"{debt}s"][{"machine": "mill", "tool": "drill"}[debt]]["verify"] = flag
    finding, check = speed_finding(data)
    check()
    assert finding["status"] == "unknown"
    finding["status"] = "pass"
    finding["numbers"].update(material_verify=False, rpm_range_verify=False)
    with pytest.raises(ValueError):
        check()


def solids(flag):
    """A one-box body whose own record carries ``flag`` as its verification."""
    box = {"name": "base", "shape": "box", "at_mm": [0, 0, 0], "size_mm": [100, 100, 30]}
    return [{**box, "verify": flag}]


@pytest.mark.parametrize(
    ("path", "value", "verdict"),
    [
        # The drill's verification left unknown, on its record or on a fact it is read by.
        (("tools", "drill", "verify"), "unknown", "unknown"),
        (("tools", "drill", "dia_mm"), {"value": 6.35, "verify": "unknown"}, "unknown"),
        # The drill, or every tool, left unknown.
        (("tools", "drill"), "unknown", "unknown"),
        (("tools",), "unknown", "unknown"),
        # A collection the drill is read through left unknown.
        (("tools", "drill", "flutes"), "unknown", "unknown"),
        # The machine's verification left unknown.
        (("machines", "mill", "verify"), "unknown", "unknown"),
        # A body solid's verification is the solid's, not its owner's identity.
        (("machines", "mill", "solids"), solids("unknown"), "pass"),
        (("machines", "mill", "solids"), solids(True), "pass"),
        (("tools", "drill", "solids"), solids("unknown"), "pass"),
    ],
)
def test_reference_oracle_reads_identity_verification_as_the_checker_does(path, value, verdict):
    """An identity the inventory leaves unknown, or whose own verification it leaves
    unknown, resolves unverified; a record it lists (a body's solid) does not qualify it.
    The engine's verdict is accepted, every other one rejected."""
    data = drill_bundle()
    set_key(path, value)(data.inventory)
    check_reference_verdict(data, path[1] if len(path) > 1 else "drill", verdict)


# A verification and its opposite: an unverified identity's is a verified one.
OPPOSITE = {True: False, False: True, "unknown": False}


@pytest.mark.parametrize("prefix", [False, True])
@pytest.mark.parametrize("flag", [True, False, "unknown"])
def test_reference_oracle_reads_an_accessory_as_the_machine_listing_it(flag, prefix):
    """A machine accessory is as verified as the record of the machine listing it, under
    whatever key: a slash-bearing key names that machine, not a member of an identity its
    prefix names (here, one carrying the opposite verification)."""
    data = drill_bundle()
    machines = data.inventory["machines"]
    machines["spare/mill"] = {"kind": "mill", "included": ["spare-vise"], "verify": flag}
    if prefix:
        machines["spare"] = {"kind": "mill", "verify": OPPOSITE[flag]}
    data.plan["setups"][0].setdefault("hold", {})["fixture"] = "spare-vise"
    check_reference_verdict(data, "spare-vise", "pass" if flag is False else "unknown")


@pytest.mark.parametrize("qualified", [False, True])
@pytest.mark.parametrize("slot", ["checks", "zero"])
@pytest.mark.parametrize("flag", [True, False, "unknown"])
def test_reference_oracle_reads_each_item_in_the_category_its_slot_selects(flag, slot, qualified):
    """One key two categories list is two items: the fixture a hold selects, and the gauge
    an inspection check or a zero pick-up selects (a spindle slot reads gauges after
    tools), are each as verified as their own record, never the other's, under the
    subject the checker gives each. A selection naming its category (``gauges.pins``) is
    that item, as its bare key in its slot is."""
    data = drill_bundle()
    data.inventory["fixtures"] = {"pins": {"kind": "fixture", "verify": OPPOSITE[flag]}}
    data.inventory["gauges"] = {"pins": {"kind": "pin_gauge", "verify": flag}}
    fixture, gauge = ("fixtures.pins", "gauges.pins") if qualified else ("pins", "pins")
    setup = data.plan["setups"][0]
    setup["hold"] = {"fixture": fixture}
    if slot == "checks":
        setup["ops"][0]["checks"] = {"dia": gauge}
    else:
        setup["zero"] = {"x": {"tool": gauge}}
    subjects = {
        (row.numbers.get("category"), row.numbers.get("reference")): row.subject
        for row in tool_resolves.evaluate(data)
        if "named_in" not in row.numbers
    }
    for category, flagged in (("gauges", flag), ("fixtures", OPPOSITE[flag])):
        verdict = "pass" if flagged is False else "unknown"
        check_reference_verdict(data, subjects[category, "pins"], verdict)


def check_reference_verdict(data, subject, verdict):
    """The engine's ``tool_resolves`` finding on ``subject`` is ``verdict``: the validator
    accepts it, and rejects it with any other status."""
    Inventory.model_validate(data.inventory)
    findings = {(f.rule, f.subject): f.to_dict() for f in tool_resolves.evaluate(data)}
    entries = VALIDATOR["Entries"](data.inventory)
    key = "tool_resolves", subject
    assert findings[key]["status"] == verdict
    VALIDATOR["check_references"](data.plan, entries, findings)
    for forged in sorted({"pass", "unknown", "error"} - {verdict}):
        with pytest.raises(ValueError):
            VALIDATOR["check_references"](
                data.plan, entries, {**findings, key: {**findings[key], "status": forged}}
            )


QUALIFIED_SELECTIONS = {
    # slot: (category, key, its record, where the plan selects it)
    "machine": ("machines", "mill", {"kind": "mill"}, lambda setup: (setup, "machine")),
    "tool": ("tools", "drill", {"kind": "drill"}, lambda setup: (setup["ops"][0], "tool")),
    "fixture": (
        "fixtures",
        "pins",
        {"kind": "fixture"},
        lambda setup: (setup.setdefault("hold", {}), "fixture"),
    ),
    "gauge": (
        "gauges",
        "pins",
        {"kind": "pin_gauge"},
        lambda setup: (setup["ops"][0].setdefault("checks", {}), "dia"),
    ),
}


@pytest.mark.parametrize("qualified", [False, True])
@pytest.mark.parametrize("flag", [True, False, "unknown", "absent"])
@pytest.mark.parametrize("slot", sorted(QUALIFIED_SELECTIONS))
def test_reference_coverage_reads_a_selection_as_the_item_it_selects(slot, flag, qualified):
    """A machine, tool, fixture or gauge the plan selects by its bare key or by
    ``<category>.<key>`` is the one item the checker selects: its native finding is
    accepted with its own verdict (an item not listed an error), and no other status is."""
    data = drill_bundle()
    category, key, item, place = QUALIFIED_SELECTIONS[slot]
    data.inventory.setdefault(category, {}).setdefault(key, item)
    if flag == "absent":
        key = "unlisted"
    else:
        data.inventory[category][key]["verify"] = flag
    target, field = place(data.plan["setups"][0])
    target[field] = f"{category}.{key}" if qualified else key
    Inventory.model_validate(data.inventory)
    findings = {(f.rule, f.subject): f.to_dict() for f in tool_resolves.evaluate(data)}
    items = {name: row for name, row in findings.items() if "category" in row["numbers"]}
    (selected,) = (
        row
        for row in items.values()
        if (row["numbers"]["category"], row["numbers"]["reference"]) == (category, key)
        and "named_in" not in row["numbers"]
    )
    verdict = "error" if flag == "absent" else "pass" if flag is False else "unknown"
    assert selected["status"] == verdict
    entries = VALIDATOR["Entries"](data.inventory)
    VALIDATOR["check_references"](data.plan, entries, findings)
    for name, row in items.items():
        for forged in sorted({"pass", "unknown", "error"} - {row["status"]}):
            with pytest.raises(ValueError):
                VALIDATOR["check_references"](
                    data.plan, entries, {**findings, name: {**row, "status": forged}}
                )


@pytest.mark.parametrize(
    ("listing", "fact", "verdict"),
    [
        ("listed", {}, "pass"),
        ("unverified", {}, "unknown"),
        ("listed", {"rpm": "unknown"}, "unknown"),
        ("unlisted", {}, "error"),
        ("accessory", {}, "error"),
    ],
)
def test_make_operation_oracle_holds_each_row_to_its_own_verdict(listing, fact, verdict):
    """Each make operation of a shop-made item a setup holds with is a ``tool_resolves``
    subject of its own (``<category>.<key> make op <n>``). Its native finding is accepted
    with its own verdict: a tool the shop's tools do not list an error, even one a machine
    carries as an accessory; an unverified tool or an unstated fact unknown. A report
    missing it, giving it any other status (alone, or with its unknowns and presence
    restated to agree), or naming another tool, item, operation or solid, is not."""
    data = drill_bundle()
    if listing in ("listed", "unverified"):
        data.inventory["tools"]["endmill-6"] = {**END_MILL, "verify": listing == "unverified"}
    if listing == "accessory":
        data.inventory["machines"]["mill"]["included"] = ["endmill-6"]
    beam = {"name": "beam", "shape": "box", "at_mm": [0, 0, 0], "size_mm": [60, 10, 8]}
    data.inventory["fixtures"] = {
        "bridge": {"kind": "custom", "solids": [beam], "make_ops": [{**MAKE_OP, **fact}]}
    }
    data.plan["setups"][0]["hold"] = {"fixture": "bridge"}
    Inventory.model_validate(data.inventory)
    findings = {(f.rule, f.subject): f.to_dict() for f in tool_resolves.evaluate(data)}
    key = "tool_resolves", "fixtures.bridge make op 1"
    native = findings[key]
    assert native["status"] == verdict
    entries = VALIDATOR["Entries"](data.inventory)

    def check(rows):
        VALIDATOR["check_make_ops"](data.plan, entries, rows)

    check(findings)
    with pytest.raises(ValueError):
        check({k: row for k, row in findings.items() if k != key})
    agreeing = {
        "pass": {"present": True, "unknown": []},
        "unknown": {"present": True, "unknown": ["rpm"]},
        "error": {"present": False, "unknown": []},
    }
    for forged in sorted({"pass", "unknown", "error"} - {verdict}):
        for numbers in (native["numbers"], {**native["numbers"], **agreeing[forged]}):
            with pytest.raises(ValueError):
                check({**findings, key: {**native, "status": forged, "numbers": numbers}})
    identities = {"tool": "endmill-8", "item": "fixtures.other", "make_op": 2, "solid": "head"}
    for field, value in identities.items():
        numbers = {**native["numbers"], field: value}
        with pytest.raises(ValueError):
            check({**findings, key: {**native, "numbers": numbers}})


def test_geometry_validation_holds_a_make_operation_to_its_own_verdict(freecad_kernel, monkeypatch):
    """A geometry bundle's report exits 2 on its expected fixture errors, so its exit
    cannot speak for a make operation's verdict: the row is held to the verdict the
    validator gives it, never forged from unknown to a pass or waived, nor restated with
    evidence made to agree. Here the nest fixture-holds holds S3 with is shop-made by
    one operation whose speed is unknown."""
    examples = ROOT / "examples"
    documents = {
        path.resolve(): tomllib.loads(path.read_text(encoding="utf-8"))
        for path in examples.rglob("*.toml")
    }
    case = next(c for c in VALIDATOR["GEOMETRY_CASES"] if c[:2] == ("fixture-holds", "plan.toml"))
    folder = examples / "geometry" / "fixture-holds"
    plan = documents[(folder / "plan.toml").resolve()]
    inventory = documents[(examples / "geometry" / "inventory.toml").resolve()]
    made = {**MAKE_OP, "tool": "em-8-std", "rpm": "unknown"}
    inventory["fixtures"]["test-nest"]["make_ops"] = [made]
    data = SimpleNamespace(plan=plan, inventory=inventory)
    native = [json.loads(json.dumps(f.to_dict())) for f in tool_resolves.evaluate(data)]
    subject = "fixtures.test-nest make op 1"
    (row,) = (r for r in native if r["subject"] == subject)
    assert (row["status"], row["numbers"]["unknown"]) == ("unknown", ["rpm"])
    golden = json.loads((folder / "expected" / "report.json").read_bytes())
    validate = VALIDATOR["validate_geometry_fixture"]

    def check(make_row):
        # The report re-hashed on the edited inventory: the checker's own tool_resolves
        # rows, with the make operation's as given.
        rows = [r for r in golden["findings"] if r["rule"] != "tool_resolves"]
        rows += [make_row if r["subject"] == subject else r for r in native]
        report = {**golden, "findings": rows}
        monkeypatch.setitem(validate.__globals__, "read_report", lambda path: report)
        validate(case, documents)

    check(row)
    for status, numbers in (
        ("pass", row["numbers"]),
        ("not_applicable", row["numbers"]),
        ("pass", {**row["numbers"], "unknown": []}),
    ):
        with pytest.raises(ValueError, match="make op"):
            check({**row, "status": status, "numbers": numbers})


PILOTS = [
    ROOT / "examples" / "pivot-shaft" / "plan.toml",
    ROOT / "examples" / "rocker-arm" / "plan.toml",
    ROOT / "examples" / "pivot-bracket" / "plan.toml",
    ROOT / "examples" / "cone-pivot-post" / "built-up.toml",
]
CATEGORIES = ("machines", "tools", "holders", "fixtures", "gauges")
# Every slot a reference is read in: any category, a slot kind (resolution.SLOT_CATEGORIES)
# or one category.
SLOTS = (None, "workholding", "spindle", "process", *CATEGORIES)
# Collections an identity may leave "unknown" (resolution.inventory_record).
COLLECTIONS = ("members", "nominal_dia_mm", "nominal_dia_cite", "holders", "sizes", "sizes_mm")
COLLECTIONS += ("sizes_in", "styles", "ranges_in", "heights_in", "flutes")
COLLECTIONS += ("standard_accessories", "included")
# Members a drill index's declared coverage generates, or not, and a qctp set's holder slots.
INDEX_MEMBERS = ("#1", "#60", "#61", "A", "Z", "1/16", "1/4", "33/64", "1/2", "17/32")
QCTP_MEMBERS = ("1-turning-facing", "2-boring-turning-facing", "4-heavy-boring", "7-parting")


def identities(root, item):
    """Every identity ``root`` names or may generate: itself, each declared member, each
    accessory, each member its declared sizes, flutes, styles, ranges, holders or coverage
    may generate, and one it declares nowhere."""
    if not isinstance(item, dict):
        return {root}

    def declared(*keys):
        return [v for key in keys if isinstance(item.get(key), (list, dict)) for v in item[key]]

    members = declared("members", "holders", "nominal_dia_mm", "sizes", "styles")
    members += [*INDEX_MEMBERS, *QCTP_MEMBERS, *(f"{size}mm" for size in declared("sizes_mm"))]
    for key in ("sizes_in", "heights_in", "ranges_in"):
        members += [f"{size}in" for size in inch_sizes(item.get(key))]
    members += [f"{size}in-{n}fl" for size in inch_sizes(item.get("sizes_in")) for n in (2, 3, 4)]
    accessories = declared("standard_accessories", "included")
    return {root, *accessories, *(f"{root}/{member}" for member in [*members, "undeclared"])}


@functools.cache
def pilot_inventories():
    """``[(inventory, refs)]``: each inventory the pilots read, as authored, with every
    identity its pilots' setups select (resolution.setup_items)."""
    plans = {}
    for path in PILOTS:
        bundle = load_bundle(path)
        inventory = (path.parent / bundle.plan["paths"]["inventory"]).resolve()
        plans.setdefault(inventory, []).append(bundle)
    return [
        (
            tomllib.loads(path.read_text(encoding="utf-8")),
            {
                ref
                for bundle in selecting
                for setup in bundle.plan["setups"]
                for _, ref, _ in setup_items(bundle, setup)
            },
        )
        for path, selecting in plans.items()
    ]


def declared_debts(item):
    """``[(label, record)]``: ``item`` declaring, clearing or leaving unknown each
    verification, presence, coverage, fact, listed solid, collection and member it can
    carry."""
    edits = [
        *((f"verify={flag}", {"verify": flag}) for flag in (True, False, "unknown")),
        *((f"present={flag}", {"present": flag}) for flag in (True, False, "unknown")),
        ("coverage", {"coverage": "verify on site"}),
        *((f"solid verify={flag}", {"solids": solids(flag)}) for flag in (True, False, "unknown")),
        *((f"{key}=unknown", {key: "unknown"}) for key in COLLECTIONS if key in item),
    ]
    if not any(key.startswith("body_dia") for key in item):
        edits += [
            (f"fact verify={flag}", {"body_dia_mm": {"value": 10.0, "verify": flag}})
            for flag in (True, False, "unknown")
        ]
    result = [(label, {**item, **edit}) for label, edit in edits]
    members = item.get("members")
    for name, member in members.items() if isinstance(members, dict) else ():
        edited = [("unknown", "unknown")]
        if isinstance(member, dict):
            edited += declared_debts({key: v for key, v in member.items() if key != "members"})
        result += [
            (f"member {name} {label}", {**item, "members": {**members, name: value}})
            for label, value in edited
        ]
    return result


def rekeyed(root, item):
    """``[(label, {key: record})]``: ``item`` under the slash-bearing key ``root/owner``
    with each verification, alone or beside an identity of its prefix key ``root``
    carrying the opposite one."""
    owner, result = f"{root}/owner", []
    for flag in (True, False, "unknown"):
        prefix = {key: item[key] for key in ("kind",) if key in item}
        record = {**item, "verify": flag}
        result += [
            (f"as {owner} verify={flag}", {owner: record}),
            (
                f"as {owner} verify={flag} beside {root}",
                {owner: record, root: {**prefix, "verify": OPPOSITE[flag]}},
            ),
        ]
    return result


def mutations(inventory):
    """``(label, category, keys, edited category)``: each category left unknown, and each
    identity of it left unknown, carrying each of its :func:`declared_debts`, or re-keyed
    (:func:`rekeyed`); ``keys`` are the identities the edit touches."""
    for category in CATEGORIES:
        items = inventory.get(category, {})
        yield f"{category}=unknown", category, (), "unknown"
        for root, item in items.items():
            edits = [("unknown", {root: "unknown"})]
            if isinstance(item, dict):
                edits += [(label, {root: edited}) for label, edited in declared_debts(item)]
                edits += rekeyed(root, item)
            rest = {key: value for key, value in items.items() if key != root}
            for label, keyed in edits:
                yield f"{root} {label}", category, (root, *keyed), {**rest, **keyed}


def verdicts(inventory, loaded, refs):
    """``{(ref, slot): (validator, checker)}`` identity verdicts in every slot
    (:data:`SLOTS`): error (does not resolve), unknown (resolves unverified) or pass. The
    validator reads the ``inventory`` as authored; the checker as it is ``loaded``."""
    entries = VALIDATOR["Entries"](inventory)

    def validator(ref, slot):
        if not entries.resolves(ref, slot):
            return "error"
        return "unknown" if entries.uncertain(ref, slot) else "pass"

    def checker(ref, slot):
        item = resolve(loaded, slot, ref)
        return "error" if item is None else "unknown" if resolved_uncertain(item) else "pass"

    pairs = [(ref, slot) for ref in refs for slot in SLOTS]
    return {pair: (validator(*pair), checker(*pair)) for pair in pairs}


def test_identity_oracle_resolves_and_verifies_every_identity_as_the_checker_does():
    """Differential: each identity of the pilots' inventory (selected, declared, member,
    accessory, generated, category-qualified or undeclared) resolves through the validator,
    in every slot, to the checker's verdict on the inventory as the checker loads it: as
    authored, and with each category or identity left unknown, re-keyed under a
    slash-bearing name (beside its prefix's identity or not) or carrying each declared,
    cleared or unknown verification, presence, coverage, fact, listed solid, collection and
    member."""
    compared, disagreements = 0, []
    for inventory, selected in pilot_inventories():
        base = Inventory.model_validate(inventory).model_dump(exclude_unset=True)
        everything = {
            root: identities(root, item) | {f"{category}.{root}"}
            for category in CATEGORIES
            for root, item in inventory[category].items()
        }
        for label, category, keys, edited in [("authored", None, (), None), *mutations(inventory)]:
            edit = {} if category is None else {category: edited}
            # The identities an edit touches, else (the authored inventory, or a whole
            # category left unknown) every identity.
            scope = set().union(
                *(everything.get(key, set()) | identities(key, edited.get(key)) for key in keys)
            )
            scope = scope or selected.union(*everything.values(), {"undeclared", "undeclared/x"})
            loaded = {**base, **Inventory.model_validate(edit).model_dump(exclude_unset=True)}
            found = verdicts({**inventory, **edit}, loaded, scope)
            compared += len(found)
            disagreements += [
                (label, ref, slot, ours, theirs)
                for (ref, slot), (ours, theirs) in sorted(found.items(), key=str)
                if ours != theirs
            ]
    assert compared > 10_000
    assert disagreements == []


def saw_finding(data):
    """The engine's speeds_feeds finding for ``data``'s one saw cut and a validator call."""
    findings = {(f.rule, f.subject): f.to_dict() for f in speeds_feeds.evaluate(data)}
    setup = data.plan["setups"][0]
    finding = findings["speeds_feeds", "S1:10"]

    def check():
        VALIDATOR["check_speeds"](
            data.plan,
            data.features,
            setup,
            setup["ops"][0],
            finding,
            VALIDATOR["Entries"](data.inventory),
            data.cutting_data,
            data.feature_definitions,
            {},
        )

    return finding, check


SAW_ROW = {
    "material_class": "low_carbon_steel",
    "tool_material": "bimetal",
    "operation": "saw_cut",
    "sfm": 150.0,
    "feed_mm_min": 20.0,
    "cite": "test saw row",
}


@pytest.mark.parametrize("corruption", ["material_class", "source", "unverified_machine"])
def test_saw_speed_oracle_takes_its_row_from_the_plan_material_not_the_report(corruption):
    data = drill_bundle()
    data.plan["setups"][0].update(machine="saw", ops=[{"op": 10, "do": "saw_cut", "tool": "blade"}])
    data.inventory["machines"]["saw"] = {"kind": "saw", "blade_speed_sfm": [50, 300]}
    data.inventory["tools"]["blade"] = {"kind": "saw_blade", "material": "bimetal"}
    other = {**SAW_ROW, "material_class": "aluminium", "sfm": 280.0, "cite": "aluminium row"}
    data.cutting_data["cut"] += [SAW_ROW, other]
    data.cutting_data["aliases"]["6061"] = "aluminium"
    if corruption == "unverified_machine":
        data.inventory["machines"]["saw"]["verify"] = True
    finding, check = saw_finding(data)
    check()
    row = finding["numbers"]
    if corruption == "material_class":
        # The report claims the stock is aluminium and takes that class's faster row,
        # self-consistently: the plan's 1018 selects the 150 sfm steel row.
        row.update(material="6061", material_class="aluminium", cutting_data_row=other["cite"])
        row.update(sfm=280.0, blade_speed_sfm=280.0)
    elif corruption == "source":
        row["cutting_data_row"] = "aluminium row"
    else:
        assert finding["status"] == "unknown"
        finding["status"] = "pass"
        row["blade_speed_range_verify"] = False
    with pytest.raises(ValueError):
        check()


def saw_bundle():
    """``drill_bundle`` turned into one verified bimetal blade cut on a verified saw."""
    data = drill_bundle()
    data.plan["setups"][0].update(machine="saw", ops=[{"op": 10, "do": "saw_cut", "tool": "blade"}])
    data.inventory["machines"]["saw"] = {"kind": "saw", "blade_speed_sfm": [50, 300]}
    data.inventory["tools"]["blade"] = {"kind": "saw_blade", "material": "bimetal"}
    data.cutting_data["cut"].append(SAW_ROW)
    return data


@pytest.mark.parametrize("cut", ["drill", "saw"])
def test_speed_oracle_certifies_the_row_its_inputs_settle(cut):
    # A sourced RPM (or blade speed) and feed on verified inputs is certified: the
    # report cannot leave it tentative, any more than it can pass an unsettled one.
    if cut == "drill":
        finding, check = speed_finding(drill_bundle(thickness=20.0))
    else:
        finding, check = saw_finding(saw_bundle())
    check()
    assert finding["status"] == "pass"
    finding["status"] = "unknown"
    with pytest.raises(ValueError):
        check()


@pytest.mark.parametrize(
    ("hole", "forged"),
    [
        # A through hole whose tip its verified drill places: pass.
        ("through", "unknown"),
        ("through", "error"),
        ("through", "no_row"),
        # A blind tip 40 mm (plus the drill point) into a 10 mm deep hole: error.
        ("over_guard", "pass"),
        ("over_guard", "unknown"),
        # A blind hole with no depth guard to hold the tip to: unknown.
        ("no_guard", "pass"),
        ("no_guard", "error"),
    ],
)
def test_endpoint_verdict_is_the_one_its_ops_tools_and_depth_guard_decide(hole, forged):
    data = drill_bundle(thickness=20.0) if hole == "through" else drill_bundle(depth_mm=40.0)
    if hole == "over_guard":
        data.features["features"]["hole"]["depth"] = 10.0
    findings = {(f.rule, f.subject): f.to_dict() for f in endpoint_findings(data)}
    entries = VALIDATOR["Entries"](data.inventory)
    finding = findings["blind_depth", "hole"]
    native = {"through": "pass", "over_guard": "error", "no_guard": "unknown"}[hole]
    assert finding["status"] == native
    VALIDATOR["check_endpoints"](data.plan, data.features, findings, entries)
    if forged == "no_row":
        finding["numbers"]["endpoints"].clear()  # nothing left to place the tip
    else:
        finding["status"] = forged
    with pytest.raises(ValueError):
        VALIDATOR["check_endpoints"](data.plan, data.features, findings, entries)


@pytest.mark.parametrize(("where", "key", "value"), CENTRE_CASES)
def test_centre_endpoint_verdict_is_the_one_its_inputs_decide(tmp_path, where, key, value):
    # Prepared, contradicted or unresolved, the centre's verdict is its own row's: an
    # unresolved centre is not an error, and a prepared one is not left tentative.
    _, check, finding = centre_findings(tmp_path, where, key, value)
    check()
    for forged in sorted({"pass", "unknown", "error"} - {finding["status"]}):
        finding["status"] = forged
        with pytest.raises(ValueError):
            check()


@pytest.mark.parametrize(
    ("tolerance", "verified", "native"),
    [
        # The 12.5182 degree setting inside a 1 degree band on the verified head.
        (1.0, True, "pass"),
        # A 0.0001 degree band the nearest setting misses.
        (0.0001, True, "error"),
        # The 1 degree band on an unverified head: tentative.
        (1.0, False, "unknown"),
    ],
)
def test_indexing_verdict_is_the_one_its_head_and_tolerance_decide(tolerance, verified, native):
    plan, features, inventory, _, _ = cone_inputs()
    setup = next(s for s in plan["setups"] if s["id"] == "S5")
    declaration = setup["hold"]["index"]
    features["features"][declaration["feature"]]["angle_tol_deg"] = tolerance
    inventory["machines"][declaration["fixture"]]["verify"] = not verified
    bundle = SimpleNamespace(
        plan=plan,
        features=features,
        inventory=inventory,
        feature_definitions=features["features"],
    )
    (finding,) = (f.to_dict() for f in indexing.evaluate(bundle) if f.subject == "S5")
    assert finding["status"] == native
    entries = VALIDATOR["Entries"](inventory)
    VALIDATOR["check_indexing"](setup, features, entries, finding)
    for forged in sorted({"pass", "unknown", "error"} - {native}):
        finding["status"] = forged
        with pytest.raises(ValueError):
            VALIDATOR["check_indexing"](setup, features, entries, finding)


@pytest.mark.parametrize(
    ("part", "setup_id", "corruption"),
    [
        ("pivot-bracket", "S2", "drop_axis"),
        ("pivot-bracket", "S1", "drop_retouch"),
        ("pivot-bracket", "S2", "unknown_paper:pass"),
        # Only a saw or manual bench setup waives its zero: an unresolved zero, or a
        # settled one, reported as waived or informational is approved by the gate.
        ("pivot-bracket", "S2", "unknown_paper:not_applicable"),
        ("pivot-bracket", "S2", "unknown_paper:info"),
        ("pivot-bracket", "S2", "settled:not_applicable"),
        ("pivot-shaft", "S2", "drop_axis"),
    ],
)
def test_zero_rows_are_the_plans_and_an_unresolved_zero_cannot_pass(
    freecad_kernel, part, setup_id, corruption
):
    setup, finding, entries, own = zero_case(part, setup_id)
    VALIDATOR["check_zero"](setup, finding, entries, own)
    numbers = finding["numbers"]
    if corruption == "drop_axis":
        del numbers["axes"]["x"]  # the X zero left unchecked
    elif corruption == "drop_retouch":
        assert numbers["retouch"]
        numbers["retouch"].pop()
    elif corruption.startswith("unknown_paper"):
        # No paper thickness: the Z Axis Set and its retouches are unknown, as the row
        # says; the zero is not certified.
        setup["zero"]["z"]["paper_mm"] = "unknown"
        z = numbers["axes"]["z"]
        z.update(axis_set="unknown", check_reading="unknown", mirrored_reading="unknown")
        for row in numbers["retouch"]:
            row["axis_set"] = "unknown"
    if ":" in corruption:
        finding["status"] = corruption.split(":")[1]
    with pytest.raises(ValueError):
        VALIDATOR["check_zero"](setup, finding, entries, own)


def native_zero(part, setup_id, dro_edit=None, inventory_edit=None):
    """The engine's ``zero_check`` finding for one example setup after ``dro_edit`` (a
    callable on the plan's ``dro`` table) and ``inventory_edit`` (one on the inventory),
    from a kernel run of the unedited plan (neither enters the kernel)."""
    bundle = load_bundle(ROOT / "examples" / part / "plan.toml")
    assert run_geometry(bundle)["status"] == "ok"
    if dro_edit:
        dro_edit(bundle.plan["dro"])
    if inventory_edit:
        inventory_edit(bundle.inventory)
    finding = next(f for f in zero_recipe.evaluate(bundle) if f.subject == setup_id)
    return json.loads(json.dumps(finding.to_dict()))


def set_key(path, value):
    """An edit of a table setting ``path`` (keys under it) to ``value``, or deleting it."""

    def edit(table):
        *parents, key = path
        for parent in parents:
            table = table[parent]
        if value is None:
            del table[key]
        else:
            table[key] = value

    return edit


DRO_EDITS = [
    # A reversed DRO count or a mode other than ABS is the error to stop on, on any axis
    # of a mill or a lathe; one the plan leaves unstated is never settled.
    ("pivot-bracket", "S2", ("direction", "x"), "left", "error"),
    ("pivot-bracket", "S2", ("direction", "y"), "toward", "error"),
    ("pivot-bracket", "S2", ("direction", "z"), "down", "error"),
    ("pivot-bracket", "S2", ("mode",), "inc", "error"),
    ("pivot-bracket", "S2", ("direction", "x"), None, "unknown"),
    ("pivot-bracket", "S2", ("mode",), "unknown", "unknown"),
    ("pivot-shaft", "S1", ("direction", "x"), "toward_spindle_axis", "error"),
    ("pivot-shaft", "S1", ("direction", "z"), "toward_chuck", "error"),
    ("pivot-shaft", "S1", ("radius_mode",), "unknown", "unknown"),
    # The lathe X display scale is the plan's radius/diameter mode, not the report's.
    ("pivot-shaft", "S1", ("radius_mode",), True, "pass"),
]


@pytest.mark.parametrize(("part", "setup_id", "path", "value", "verdict"), DRO_EDITS)
def test_zero_polarity_scale_and_mode_come_from_the_plans_dro(
    freecad_kernel, part, setup_id, path, value, verdict
):
    setup, _, entries, own = zero_case(part, setup_id)
    before = native_zero(part, setup_id)
    set_key(path, value)(own.plan["dro"])
    native = native_zero(part, setup_id, set_key(path, value))
    assert native["status"] == verdict
    VALIDATOR["check_zero"](setup, copy.deepcopy(native), entries, own)
    # The unedited plan's finding printing the edited plan's DRO modes (the reviewer's
    # report): the polarity, scale, readings and verdict stay the plan's, not the report's.
    stale = copy.deepcopy(before)
    stale["numbers"]["dro"] = native["numbers"]["dro"]
    with pytest.raises(ValueError):
        VALIDATOR["check_zero"](setup, stale, entries, own)
    for forged in sorted({"pass", "unknown", "error"} - {verdict}):
        with pytest.raises(ValueError):
            VALIDATOR["check_zero"](setup, {**native, "status": forged}, entries, own)


@pytest.mark.parametrize(("part", "setup_id"), [("pivot-bracket", "S2"), ("pivot-shaft", "S1")])
@pytest.mark.parametrize("status", ["pass", "error"])
def test_zero_jog_polarity_is_never_the_reports(freecad_kernel, part, setup_id, status):
    """A row printing a reversed X polarity with its readings swapped to match is still
    the plan's DRO counting up: neither approved nor taken as the reversal to stop on."""
    setup, _, entries, own = zero_case(part, setup_id)
    native = native_zero(part, setup_id)
    VALIDATOR["check_zero"](setup, copy.deepcopy(native), entries, own)
    row = native["numbers"]["axes"]["x"]
    row["sign"] = -row["sign"]
    row["check_reading"], row["mirrored_reading"] = row["mirrored_reading"], row["check_reading"]
    if "check_expression" in row:  # a measured axis prints its readings as expressions
        row["check_expression"], row["mirrored_expression"] = (
            row["mirrored_expression"],
            row["check_expression"],
        )
    native["status"] = status
    with pytest.raises(ValueError):
        VALIDATOR["check_zero"](setup, native, entries, own)


def inventory_edits(*edits):
    """One inventory edit applying each ``(path, value)`` of ``edits`` (:func:`set_key`)."""

    def edit(inventory):
        for path, value in edits:
            set_key(path, value)(inventory)

    return edit


FINDER = ("tools", "edge-finder")
MICROMETERS = ("gauges", "micrometers")
ZERO_INVENTORY_EDITS = [
    # A finder, cutter, tool bit or gauge whose verification the inventory leaves unknown,
    # on its record, on a fact it is read through or on the selected set member, or that
    # the inventory leaves unknown whole or by category, is not ready: never a pass.
    ("pivot-bracket", "S2", [((*FINDER, "verify"), "unknown")], "unknown"),
    (
        "pivot-bracket",
        "S2",
        [((*FINDER, "tip_in"), {"value": 0.2, "verify": "unknown"})],
        "unknown",
    ),
    ("pivot-bracket", "S2", [(FINDER, "unknown")], "unknown"),
    ("pivot-bracket", "S2", [(("tools",), "unknown")], "unknown"),
    ("pivot-bracket", "S2", [(("tools", "bracket-long-endmill", "verify"), "unknown")], "unknown"),
    ("pivot-shaft", "S1", [(("tools", "hss-toolbit-3-8-rh", "verify"), "unknown")], "unknown"),
    ("pivot-shaft", "S1", [((*MICROMETERS, "verify"), "unknown")], "unknown"),
    (
        "pivot-shaft",
        "S1",
        [((*MICROMETERS, "members"), {"0-1in": {"verify": "unknown"}})],
        "unknown",
    ),
    ("pivot-shaft", "S2", [(("gauges", "calipers", "verify"), "unknown")], "unknown"),
    # Flagged outright, the same.
    ("pivot-bracket", "S2", [((*FINDER, "verify"), True)], "unknown"),
    ("pivot-shaft", "S1", [((*MICROMETERS, "present"), "unknown")], "unknown"),
    # A finder's radius is half its tip, else its body, diameter, in either unit.
    ("pivot-bracket", "S2", [((*FINDER, "tip_in"), None), ((*FINDER, "dia_in"), 0.2)], "pass"),
    ("pivot-bracket", "S2", [((*FINDER, "tip_in"), None), ((*FINDER, "tip_mm"), 5.08)], "pass"),
    # A machine the inventory lists as absent is no lathe.
    ("pivot-shaft", "S1", [(("machines", "PM-1127VF-LB", "present"), False)], "unknown"),
    # An edge finder's procedure is the checker's: a band it does not state leaves the
    # zero unknown, and one no spindle band turns is the error to stop on.
    ("pivot-bracket", "S2", [((*FINDER, "rpm_range"), None)], "unknown"),
    ("pivot-bracket", "S2", [((*FINDER, "rpm_range"), [5000, 6000])], "error"),
]


def forged(value):
    """A value other than ``value`` of its own shape."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return [] if isinstance(value, list) else {} if isinstance(value, dict) else "forged"
    return value + 1


@pytest.mark.parametrize(
    ("part", "setup_id", "path"),
    [
        # An edge finder's procedure box: its tip, the band it runs at, its verdict.
        ("pivot-bracket", "S2", ("axes", "x", "finder", "tip_dia_mm")),
        ("pivot-bracket", "S2", ("axes", "y", "finder", "rpm")),
        ("pivot-bracket", "S2", ("axes", "x", "finder", "status")),
        ("pivot-bracket", "S2", ("axes", "y", "finder")),
        # A lathe X touch: whether the diameter it measures stands, and its Axis Set.
        ("pivot-shaft", "S2", ("tool_touches", 0, "x_face_status")),
        ("pivot-shaft", "S2", ("tool_touches", 0, "x_axis_set")),
        ("pivot-shaft", "S1", ("tool_touches", 0, "x_face_status")),
    ],
)
def test_zero_rows_only_the_checker_derives_are_its_own_on_the_validators_inputs(
    freecad_kernel, part, setup_id, path
):
    """A zero row the checker derives (an edge finder's procedure, a lathe touch's
    measured diameter and Axis Set) is accepted as the checker derives it on the
    validator's own inputs, and rejected moved or dropped: no report value stands in."""
    setup, _, entries, own = zero_case(part, setup_id)
    native = native_zero(part, setup_id)
    VALIDATOR["check_zero"](setup, copy.deepcopy(native), entries, own)
    *parents, key = path
    for change in ("forge", "drop"):
        finding = copy.deepcopy(native)
        table = finding["numbers"]
        for parent in parents:
            table = table[parent]
        if change == "forge":
            table[key] = forged(table[key])
        else:
            del table[key]
        with pytest.raises(ValueError):
            VALIDATOR["check_zero"](setup, finding, entries, own)


@pytest.mark.parametrize(("part", "setup_id", "edits", "verdict"), ZERO_INVENTORY_EDITS)
def test_zero_readiness_radius_and_lathe_come_from_the_inventory(
    freecad_kernel, part, setup_id, edits, verdict
):
    """The engine's finding on the edited inventory is accepted with its own verdict only;
    the unedited inventory's (a retained report) no longer stands where the edit moves it."""
    setup, _, _, own = zero_case(part, setup_id)
    edit = inventory_edits(*edits)
    before = native_zero(part, setup_id)
    edit(own.inventory)
    entries = VALIDATOR["Entries"](own.inventory)
    native = native_zero(part, setup_id, inventory_edit=edit)
    assert native["status"] == verdict
    VALIDATOR["check_zero"](setup, copy.deepcopy(native), entries, own)
    for forged in sorted({"pass", "unknown", "error"} - {verdict}):
        with pytest.raises(ValueError):
            VALIDATOR["check_zero"](setup, {**native, "status": forged}, entries, own)
    if before != native:
        with pytest.raises(ValueError):
            VALIDATOR["check_zero"](setup, before, entries, own)


def coverage_case():
    """The built-up cone's plan, manifest and report findings keyed by rule and subject,
    and the validator's coverage check on its own inventory read and bundle load."""
    plan, features, inventory, _, report = cone_inputs()
    entries = VALIDATOR["Entries"](inventory)
    checked = VALIDATOR["checker_findings"](ROOT / "examples" / "cone-pivot-post" / "built-up.toml")

    def check(policy, plan, features, findings):
        VALIDATOR["check_required_coverage"](policy, plan, features, findings, entries, checked)

    findings = {(row["rule"], row["subject"]): row for row in report["findings"]}
    return plan, features, findings, check


def coverage_row(rule, subject, selector, status="unknown"):
    return {"rule": rule, "subject": subject, "status": status, "numbers": {"required": selector}}


@pytest.mark.parametrize(
    ("rule", "selector", "subject"),
    [
        ("vise", ["S1", "S99"], "S99"),  # a setup the plan does not have
        ("not_implemented_check", "*", "*"),  # a rule no supported check implements
        ("not_implemented_check", [], "*"),  # an empty selection of one
    ],
)
def test_required_coverage_comes_from_the_policy_not_the_report(rule, selector, subject):
    plan, features, findings, check = coverage_case()
    policy = {"required": {rule: selector}}
    key = (rule, subject)
    # A required subject no supported check covers has the checker's unknown coverage row.
    check(policy, plan, features, {**findings, key: coverage_row(rule, subject, selector)})
    # It cannot be dropped, approved or waived: no supported check exists to decide it.
    with pytest.raises(ValueError):
        check(policy, plan, features, findings)
    for status in ("pass", "not_applicable", "info"):
        row = coverage_row(rule, subject, selector, status)
        with pytest.raises(ValueError):
            check(policy, plan, features, {**findings, key: row})
    # Nor can a fabricated subject of the rule, which no check evaluates, stand in for it.
    fabricated = (rule, "S99:10" if subject == "S99" else "S1")
    with pytest.raises(ValueError):
        check(policy, plan, features, {**findings, fabricated: coverage_row(*fabricated, {})})
    with pytest.raises(ValueError):
        rows = {key: coverage_row(rule, subject, selector), fabricated: {"status": "pass"}}
        check(policy, plan, features, {**findings, **rows})


def test_required_coverage_row_carries_the_policys_selector():
    plan, features, findings, check = coverage_case()
    # An empty selection's coverage row is required by the policy's selection of its
    # rule, never by the selector the report prints on it.
    policy = {"required": {"vise": []}}
    star = coverage_row("vise", "*", [])
    assert VALIDATOR["report_exit"]({"findings": [star]}, policy, plan, features) == 4
    star["numbers"]["required"] = "forged"
    assert VALIDATOR["report_exit"]({"findings": [star]}, policy, plan, features) == 4
    policy = {"required": {"not_implemented_check": "*"}}
    key = ("not_implemented_check", "*")
    with pytest.raises(ValueError):
        row = coverage_row(*key, "forged")
        check(policy, plan, features, {**findings, key: row})


def test_rules_only_the_checker_models_are_its_own_rows_on_the_validators_inputs(
    freecad_kernel, tmp_path, monkeypatch
):
    """A rule of the checker's catalogue the validator does not model (consistency,
    purchased_tooling, or one the checker adds later) is the rows its own rule gives on the
    validator's own bundle load and kernel run: each is required with that rule's verdict
    and evidence. A row dropped or fabricated, an unknown reported passed or waived, a
    verdict moved either way, or one standing on other evidence is rejected. Here the shop
    requires purchased tooling and the edge finder's receipt checks are unknown."""
    examples = copy_examples(tmp_path)
    for name, table, line in (
        ("inventory/pedro-shop.toml", "[tools.edge-finder]\n", 'acceptance = "unknown"\n'),
        ("shop-policy.toml", "[required]\n", 'purchased_tooling = "*"\n'),
    ):
        path = examples / name
        text = path.read_text(encoding="utf-8")
        assert table in text
        path.write_text(text.replace(table, table + line, 1), encoding="utf-8")
    plan_path = examples / "pivot-bracket" / "plan.toml"
    bundle = load_bundle(plan_path)
    assert run_geometry(bundle)["status"] == "ok"

    def later(data):
        return [
            Finding("later_rule", s["id"], "unknown", {"setup": s["id"]}, [], "")
            for s in data.plan["setups"]
        ]

    rule_subjects = VALIDATOR["rule_subjects"]
    rules = [*RULES, Rule("later_rule", later)]
    monkeypatch.setitem(rule_subjects.__globals__, "CHECKER_RULES", rules)
    entries = VALIDATOR["Entries"](bundle.inventory)
    checked = VALIDATOR["checker_findings"](plan_path)
    domains = rule_subjects(bundle.plan, bundle.features, entries, checked)
    assert set(domains["later_rule"]) == {setup["id"] for setup in bundle.plan["setups"]}
    native = {
        (f.rule, f.subject): json.loads(json.dumps(f.to_dict()))
        for rule in rules
        for f in rule.evaluate(bundle)
    }
    findings = {
        (rule, subject): native.get((rule, subject), {"status": "pass", "numbers": {}})
        for rule, subjects in domains.items()
        for subject in subjects
    }
    receipts = {row["status"] for key, row in findings.items() if key[0] == "purchased_tooling"}
    assert "unknown" in receipts
    check = VALIDATOR["check_required_coverage"]

    def rejected(changed):
        with pytest.raises(ValueError):
            check(bundle.policy, bundle.plan, bundle.features, changed, entries, checked)

    check(bundle.policy, bundle.plan, bundle.features, findings, entries, checked)
    for rule in ("later_rule", "consistency", "purchased_tooling"):
        rejected({key: row for key, row in findings.items() if key[0] != rule})
        rejected({**findings, (rule, "S99"): {"status": "pass", "numbers": {}}})
        for key, row in findings.items():
            if key[0] != rule:
                continue
            for status in sorted({"pass", "unknown", "error", "not_applicable"} - {row["status"]}):
                rejected({**findings, key: {**row, "status": status}})
            rejected({**findings, key: {**row, "numbers": {**row["numbers"], "forged": True}}})


def cone_coordinates(tmp_path, setup_id, aim=None, measured=False):
    """The engine's coordinates finding for one setup of the built-up cone (``aim``
    replaces the requirement and value of plan ``aims.crank_bore``, which asks 39.517 of
    its 39.34-39.70 printed separation; ``measured`` runs the kernel first, as the CLI
    does, so kernel spans place rows), and a validator call that checks it against a
    plan."""
    plan_path = copy_examples(tmp_path) / "cone-pivot-post" / "built-up.toml"
    if aim is not None:
        text = plan_path.read_text(encoding="utf-8")
        authored = 'requirement = "separation"\nvalue_mm = 39.517\n'
        assert authored in text
        plan_path.write_text(text.replace(authored, aim), encoding="utf-8")
    bundle = load_bundle(plan_path)
    if measured:
        assert run_geometry(bundle)["status"] == "ok"
    setup = next(setup for setup in bundle.plan["setups"] if setup["id"] == setup_id)
    finding = next(f for f in coordinates.evaluate(bundle) if f.subject == setup_id).to_dict()
    entries = VALIDATOR["Entries"](bundle.inventory)
    kernel = VALIDATOR["independent_kernel"](plan_path)

    def check(plan=bundle.plan):
        VALIDATOR["check_coordinates"](
            setup, bundle.features, finding, plan, entries, bundle.inventory, kernel
        )

    return bundle, setup, finding, check


def aimed_bore(tmp_path, aim=None):
    """The S8 coordinates of the cone's aimed crank bore (:func:`cone_coordinates`), its
    crank_bore row and the validator call."""
    bundle, _, finding, check = cone_coordinates(tmp_path, "S8", aim)
    (row,) = (row for row in finding["numbers"]["rows"] if row["feature"] == "crank_bore")
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


@pytest.mark.parametrize(
    "corruption",
    [
        # The aim dropped from what the machinist reads: the feature map's DRO stop and
        # the hole op's dialled X/Y, together or alone, at the bore's CAD station.
        "dro_and_xy",
        "dro",
        "dro_xy",
        # Every stop re-rounded to a 0.01 grid the machine's 0.005 resolution never shows.
        "grid",
        # A station label (which skipped the at check) on the bore, moved along its axis
        # with its setup and nominal targets: self-consistent.
        "station",
        # The same, as if the kernel's faces of revolution placed this at-located bore.
        "kernel_span",
    ],
)
def test_coordinate_oracle_holds_the_printed_dro_target_to_the_aimed_point_on_the_grid(
    tmp_path, corruption
):
    bundle, finding, row, check = aimed_bore(tmp_path)
    check()
    nominal = row["nominal_setup"]
    if corruption in {"dro_and_xy", "dro"}:
        row["dro"][0] = nominal[0]
    if corruption in {"dro_and_xy", "dro_xy"}:
        row["dro_xy"][0] = nominal[0]
    if corruption == "grid":
        finding["numbers"]["dro_grid"] = {"step": 0.01, "decimals": 2}
        for other in finding["numbers"]["rows"]:
            if "dro" in other:
                other["dro"] = [round(value, 2) + 0.0 for value in other["setup"]]
                other["dro_xy"] = other["dro"][:2]
        assert row["dro"][0] != -72.885
    if corruption in {"station", "kernel_span"}:
        row["point"] = "station" if corruption == "station" else "setup Z axis, kernel span start"
        setup = next(s for s in bundle.plan["setups"] if s["id"] == "S8")
        frame = VALIDATOR["setup_frame"](setup, bundle.plan, bundle.features)
        axis = bundle.feature_definitions["crank_bore"]["axis"]
        model = [value + step for value, step in zip(row["model"], axis, strict=True)]
        delta = [
            moved - placed
            for moved, placed in zip(
                VALIDATOR["frame_point"](model, frame),
                VALIDATOR["frame_point"](row["model"], frame),
                strict=True,
            )
        ]
        row["model"] = model
        for key in ("setup", "nominal_setup"):
            row[key] = [value + step for value, step in zip(row[key], delta, strict=True)]
    with pytest.raises(ValueError):
        check()


@pytest.mark.parametrize("status", ["not_applicable", "info"])
def test_a_cutting_setups_coordinates_are_a_verdict_never_a_waiver(tmp_path, status):
    # Only a manual bench setup waives its coordinates; S8 mills the aimed crank bore.
    _, finding, _, check = aimed_bore(tmp_path)
    check()
    finding["status"] = status
    with pytest.raises(ValueError):
        check()


@pytest.mark.parametrize("corruption", ["x_target", "station_z"])
def test_coordinate_oracle_holds_a_lathe_station_to_the_manifest_and_its_op(tmp_path, corruption):
    bundle, setup, finding, check = cone_coordinates(tmp_path, "S1")
    check()
    row = next(
        row
        for row in finding["numbers"]["rows"]
        if row.get("point", "").startswith("op ") and isinstance(row.get("dia_nominal"), float)
    )
    if corruption == "x_target":
        # The feature map's "turn to" diameter 1 mm over the manifest's nominal.
        ratio = row["x_target_mm"] / row["dia_nominal"]
        row["dia_nominal"] += 1.0
        row["x_target_mm"] = row["dia_nominal"] * ratio
    else:
        # The op's Z end 1 mm off its authored value, model and setup moved together.
        frame = VALIDATOR["setup_frame"](setup, bundle.plan, bundle.features)
        row["setup"][2] += 1.0
        row["model"] = VALIDATOR["model_point"](row["setup"], frame)
    with pytest.raises(ValueError):
        check()


@pytest.mark.parametrize("setup_id", ["S11", "S1"])
def test_coordinate_oracle_ends_a_kernel_span_where_its_own_kernel_run_measures_it(
    tmp_path, freecad_kernel, setup_id
):
    # The head's span start, 5 mm further along setup -Z with its model point (and on the
    # S11 mill its DRO stop) moved to match: self-consistent, as if the kernel measured the
    # head that much longer. S1 is the lathe, S11 the mill.
    bundle, setup, finding, check = cone_coordinates(tmp_path, setup_id, measured=True)
    check()
    row = next(
        row
        for row in finding["numbers"]["rows"]
        if row.get("feature") == "head" and row.get("point", "").endswith("kernel span start")
    )
    frame = VALIDATOR["setup_frame"](setup, bundle.plan, bundle.features)
    row["setup"][2] -= 5.0
    row["model"] = VALIDATOR["model_point"](row["setup"], frame)
    if "dro" in row:
        entries = VALIDATOR["Entries"](bundle.inventory)
        grid = VALIDATOR["dro_grid"](setup, bundle.features, entries)
        row["dro"] = [VALIDATOR["dro_target"](value, grid) for value in row["setup"]]
        row["dro_xy"] = row["dro"][:2]
    with pytest.raises(ValueError):
        check()


@pytest.fixture(scope="module")
def rocker_blank(freecad_kernel):
    """The rocker-arm bundle, whose prepared blank P5 cuts and gauges no setup names
    check, and its kernel facts."""
    bundle = load_bundle(ROOT / "examples" / "rocker-arm" / "plan.toml")
    facts = run_geometry(bundle)
    assert facts["status"] == "ok", facts.get("reason")
    return bundle, facts


def blank_case(rocker_blank, case=None):
    """The engine's own ``prepared_blank`` finding for the rocker-arm with ``case`` changed
    in its plan, inventory or kernel facts, and a validator call that checks a candidate
    finding against those inputs and facts (returning the gauges it cannot resolve)."""
    bundle, facts = copy.deepcopy(rocker_blank)
    prepared = bundle.plan["stock"]["prepared"]
    gauges = bundle.inventory["gauges"]
    cut = facts["setups"]["P5"]
    if case == "missing_form_limit":
        prepared["form_mm"].pop("flat")
    elif case == "unknown_form_limit":
        prepared["form_mm"]["flat"] = "unknown"
    elif case == "missing_form_method":
        prepared["methods"].pop("flat")
    elif case == "gauge_range_short":
        prepared["checks"]["length"] = "calipers"  # a 6 in caliper on the 340 mm length
    elif case == "gauge_resolution_coarse":
        gauges["calipers-18in"]["resolution_mm"] = 1.0
    elif case == "gauge_verify_unknown":
        gauges["calipers-18in"]["verify"] = "unknown"
    elif case == "missing_gauge":
        prepared["checks"]["length"] = "calipers-36in"
    elif case == "undeclared_gauge":
        del prepared["checks"]["flat"]
    elif case == "kernel_unavailable":
        facts = {"status": "unknown", "kernel_unavailable": True}
    elif case == "cut_unexplained":
        cut["stock_out_reason"] = "unknown milling pass"
    elif case == "cut_missing":
        del facts["setups"]["P5"]
    elif case == "cut_half_volume":
        cut["stock_out_volume_mm3"] *= 0.5
    elif case == "cut_long":
        cut["stock_out_bbox_mm"][3] += 5.0
    object.__setattr__(bundle, "kernel", facts)
    native = prepared_blank.evaluate(bundle)[0].to_dict()

    def check(finding):
        """``finding`` None: the report carries no prepared_blank finding."""
        return VALIDATOR["check_prepared_blank"](
            bundle.plan,
            bundle.features,
            bundle.inventory,
            {} if finding is None else {("prepared_blank", "stock.prepared"): finding},
            lambda: facts,
        )

    return bundle, native, check


@pytest.mark.parametrize(
    "case",
    [
        "missing_form_limit",
        "unknown_form_limit",
        "missing_form_method",
        "gauge_range_short",
        "gauge_resolution_coarse",
        "gauge_verify_unknown",
        "missing_gauge",
        "undeclared_gauge",
        "kernel_unavailable",
        "cut_unexplained",
        "cut_missing",
        "cut_half_volume",
        "cut_long",
    ],
)
def test_prepared_blank_approval_comes_from_its_gauges_and_kernel_cut(rocker_blank, case):
    # A blank its gauges cannot read (no form limit or method, a caliper short of the
    # length or too coarse for its band, an unverified, missing or undeclared gauge) or
    # its kernel cut does not explain (no run, an unexplained or missing cut, a cut that
    # is not the declared box) is not approved. The engine's own unresolved or failed
    # finding is accepted; the same finding with every check row and the verdict
    # approved is not.
    _, native, check = blank_case(rocker_blank, case)
    assert native["status"] != "pass"
    check(native)
    forged = copy.deepcopy(native)
    forged["status"] = "pass"
    for row in forged["numbers"].get("checks", {}).values():
        row["status"] = "pass"
    with pytest.raises(ValueError):
        check(forged)


@pytest.mark.parametrize("case", [None, "missing_gauge"])
def test_prepared_blank_reports_the_gauges_it_cannot_resolve(rocker_blank, case):
    bundle, native, check = blank_case(rocker_blank, case)
    entries = VALIDATOR["Entries"](bundle.inventory)
    # No setup names them, so no tool_resolves finding reads them.
    stock_only = {"stock": bundle.plan["stock"], "setups": []}
    assert VALIDATOR["check_references"](stock_only, entries, {}) == []
    assert check(native) == (["calipers-36in"] if case else [])


@pytest.mark.parametrize(
    "corruption",
    [
        "other_gauge",
        "size_band",
        "gauge_range",
        "form_limit",
        "method",
        "row_not_approved",
        "checks_never_read",
        "dropped_row",
        "cut_volume",
        "no_finding",
        "approved_without_blank",
    ],
)
def test_prepared_blank_verdict_holds_to_the_plan_gauges_and_inventory(rocker_blank, corruption):
    bundle, native, check = blank_case(rocker_blank)
    assert native["status"] == "pass"
    check(native)
    finding = copy.deepcopy(native)
    rows = finding["numbers"]["checks"]
    prepared = bundle.plan["stock"]["prepared"]
    if corruption == "other_gauge":
        rows["length"]["gauge"] = "calipers"
    elif corruption == "size_band":
        rows["length"]["limits_mm"] = [339.0, 341.0]
    elif corruption == "gauge_range":
        rows["length"]["range_mm"] = [0, 1000]
    elif corruption == "form_limit":
        rows["flat"]["limit_mm"] = 0.5
    elif corruption == "method":
        rows["square"]["method"] = prepared["methods"]["flat"]
    elif corruption == "row_not_approved":
        rows["square"]["status"] = "unknown"
    elif corruption == "checks_never_read":
        del finding["numbers"]["checks"]
    elif corruption == "dropped_row":
        del rows["parallel"]
    elif corruption == "cut_volume":
        finding["numbers"]["cut_volume_mm3"] *= 1.5
    elif corruption == "no_finding":
        finding = None
    elif corruption == "approved_without_blank":
        del bundle.plan["stock"]["prepared"]
    with pytest.raises(ValueError):
        check(finding)


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
    "rule",
    [
        "tool_resolves",
        "inspection",
        "joint_fit",
        "joint_assembly",
    ],
)
def test_built_up_subject_contract_excludes_manual_assembly_but_keeps_joint_debt(rule):
    plan, features, inventory, _, report = cone_inputs(fresh_pure=True)
    findings = {(row["rule"], row["subject"]): row for row in report["findings"]}
    joint_setup = next(
        s for s in plan["setups"] if s.get("joint", {}).get("socket") == "crank_socket"
    )
    cutting_setup, cutting_op = next(
        (s, op)
        for s in plan["setups"]
        for op in s["ops"]
        if op.get("feature") == "crank_socket" and op["do"] == "ream"
    )
    subject = {
        "tool_resolves": f"{cutting_setup['id']}:{cutting_op['op']}",
        "inspection": f"{joint_setup['joint']['socket']}:dia",
        "joint_fit": joint_setup["id"],
        "joint_assembly": joint_setup["id"],
    }[rule]
    missing = rule, subject
    # Manual fitting has no cutting-assembly requirement; joint debt still does.
    for setup in plan["setups"]:
        if VALIDATOR["manual_bench"](inventory, setup) is not None:
            for op in setup["ops"]:
                findings.pop(("tool_resolves", f"{setup['id']}:{op['op']}"), None)
    VALIDATOR["check_subjects"](plan, features, findings, inventory)
    del findings[missing]
    with pytest.raises(ValueError, match=f"missing finding {missing[0]}:{missing[1]}"):
        VALIDATOR["check_subjects"](plan, features, findings, inventory)


def joined(unresolved=None, error=None):
    """Synthetic kernel facts for the built-up cone's joins: S6 and S7 each derive their
    joined stock with these joint features completed. ``unresolved`` names a join whose
    joined stock that run leaves unknown (as it does for unknown fit bands), or, given an
    ``error``, refuses."""
    completed = ["cone_socket", "cone_spigot", "crank_socket"]
    setups = {
        sid: {
            "stock_bbox_mm": [[-1.0, -1.0, -1.0], [1.0, 1.0, 1.0]],
            "completed_joint_features": done,
        }
        for sid, done in (("S6", completed), ("S7", [*completed, "crank_spigot"]))
    }
    if unresolved is not None:
        done = setups[unresolved]["completed_joint_features"]
        setups[unresolved] = {"completed_joint_features": done}
        if error is None:
            setups[unresolved]["stock_reason"] = "joint fit diameter bands are unknown"
        else:
            setups[unresolved]["assembly_error"] = error
    return lambda: {"status": "ok", "setups": setups}


@pytest.mark.parametrize(
    "corruption", ["fit_pass", "missing", "socket", "assembly_pass", "branches"]
)
def test_built_up_joint_report_cannot_clear_numeric_debt_or_change_identity(corruption):
    plan, features, _, _, report = cone_inputs(fresh_pure=True)
    findings = {(row["rule"], row["subject"]): row for row in report["findings"]}
    kernel = joined()
    VALIDATOR["check_joint_declarations"](plan, features, findings, kernel)
    setup = next(setup for setup in plan["setups"] if setup["id"] == "S7")
    fit = findings["joint_fit", "S7"]
    assembly = findings["joint_assembly", "S7"]
    if corruption in {"fit_pass", "missing", "assembly_pass"}:
        # The shipped joint resolves, so declare numeric debt in the plan: the
        # report must then carry it and neither row may approve.
        setup["joint"]["clearance_mm"] = "unknown"
        kernel = joined("S7")
        fit["status"], assembly["status"] = "unknown", "unknown"
        VALIDATOR["check_joint_declarations"](plan, features, findings, kernel)
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
        VALIDATOR["check_joint_declarations"](plan, features, findings, kernel)


@pytest.mark.parametrize(
    "corruption", ["unresolved", "refused", "no_kernel", "no_setup_facts", "completed"]
)
def test_joint_assembly_verdict_is_the_validators_own_kernel_join(corruption):
    # The report approves S7's join as shipped, but the validator's own kernel run leaves
    # its joined stock unknown, refuses it, never ran or derived nothing for S7; or the
    # report claims a joint feature completed that the join never completed.
    plan, features, _, _, report = cone_inputs()
    findings = {(row["rule"], row["subject"]): row for row in report["findings"]}
    assembly = findings["joint_assembly", "S7"]
    VALIDATOR["check_joint_declarations"](plan, features, findings, joined())
    assert assembly["status"] == "pass"
    facts = joined()()
    if corruption == "unresolved":
        facts = joined("S7")()
    elif corruption == "refused":
        facts = joined("S7", error="spigot insertion sweep meets socket material")()
    elif corruption == "no_kernel":
        facts = {"status": "unknown", "kernel_unavailable": True, "reason": "no FreeCAD"}
    elif corruption == "no_setup_facts":
        del facts["setups"]["S7"]
    else:
        facts["setups"]["S7"]["completed_joint_features"].remove("crank_spigot")
    with pytest.raises(ValueError):
        VALIDATOR["check_joint_declarations"](plan, features, findings, lambda: facts)


UNAVAILABLE = {"status": "unknown", "kernel_unavailable": True, "reason": "no FreeCAD"}
REFUSED = "spigot insertion sweep meets socket material"


@pytest.mark.parametrize(
    ("run", "sid", "status", "numbers"),
    [
        # No kernel ran: an always-required join is unknown debt, never inapplicable,
        # whether the report keeps the shipped join evidence or the kernel's failure.
        ("unavailable", "S6", "not_applicable", "shipped"),
        ("unavailable", "S7", "not_applicable", "shipped"),
        ("unavailable", "S7", "not_applicable", None),
        # The validator's run refused S7: the report cannot call it unavailable debt.
        ("refused", "S7", "unknown", {"kernel_status": "unknown", "kernel_unavailable": True}),
        ("refused", "S7", "unknown", {"kernel_status": "unavailable"}),
        ("refused", "S7", "error", {"kernel_status": "error"}),
        # The validator's run joined S7: a reported kernel failure is not that run.
        ("joined", "S7", "unknown", {"kernel_status": "unknown", "kernel_unavailable": True}),
        ("joined", "S7", "error", {"kernel_status": "error"}),
    ],
)
def test_joint_assembly_report_cannot_name_a_kernel_outcome_its_validator_did_not_run(
    run, sid, status, numbers
):
    plan, features, _, _, report = cone_inputs()
    findings = {(row["rule"], row["subject"]): row for row in report["findings"]}
    shipped = copy.deepcopy(findings["joint_assembly", sid]["numbers"])
    if run == "unavailable":
        facts = UNAVAILABLE
        for subject in ("S6", "S7"):
            findings["joint_assembly", subject].update(
                status="unknown", numbers={"kernel_status": "unknown", "kernel_unavailable": True}
            )
    elif run == "refused":
        facts = joined("S7", error=REFUSED)()
        findings["joint_assembly", "S7"]["status"] = "error"
    else:
        facts = joined()()
    VALIDATOR["check_joint_declarations"](plan, features, findings, lambda: facts)
    findings["joint_assembly", sid]["status"] = status
    if numbers is not None:
        findings["joint_assembly", sid]["numbers"] = shipped if numbers == "shipped" else numbers
    with pytest.raises(ValueError):
        VALIDATOR["check_joint_declarations"](plan, features, findings, lambda: facts)


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


@pytest.mark.parametrize(
    ("facts", "status"), [(UNAVAILABLE, "unknown"), ({"status": "error", "reason": "x"}, "error")]
)
def test_joint_kernel_failure_cannot_be_approved_without_assembly_evidence(facts, status):
    # The validator's own run failed: each join carries that failure, and none approves.
    plan, features, _, _, report = cone_inputs()
    findings = {(row["rule"], row["subject"]): row for row in report["findings"]}
    numbers = {"kernel_status": facts["status"]}
    if facts.get("kernel_unavailable"):
        numbers["kernel_unavailable"] = True
    for sid in ("S6", "S7"):
        findings["joint_assembly", sid].update(status=status, numbers=dict(numbers))
    VALIDATOR["check_joint_declarations"](plan, features, findings, lambda: facts)
    findings["joint_assembly", "S7"]["status"] = "pass"
    with pytest.raises(ValueError):
        VALIDATOR["check_joint_declarations"](plan, features, findings, lambda: facts)
