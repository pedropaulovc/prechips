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
from test_operative_surface import plan as surface_plan
from test_process_features import set_process_key, set_tool_fact, shaft

from prechips.inputs import load_bundle
from prechips.kernel import run_geometry
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


def test_rejects_unsourced_finished_diameter_in_unbound_profile(freecad_kernel):
    plan, features, _, policy, report = cone_inputs()
    setup = next(s for s in plan["setups"] if s["id"] == "S1")
    finding = next(
        f for f in report["findings"] if f["rule"] == "stickout" and f["subject"] == "S1"
    )
    kernel = VALIDATOR["independent_kernel"](
        ROOT / "examples" / "cone-pivot-post" / "built-up.toml"
    )
    VALIDATOR["check_stickout"](setup, plan, features, policy, finding, kernel)
    corrupted = copy.deepcopy(finding)
    corrupted["numbers"]["diameter_mm"] = 21.93
    with pytest.raises(ValueError):
        VALIDATOR["check_stickout"](setup, plan, features, policy, corrupted, kernel)


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
    folder = ROOT / "examples" / "pivot-shaft"
    plan = tomllib.loads((folder / "plan.toml").read_text(encoding="utf-8"))
    features = tomllib.loads((folder / "features.toml").read_text(encoding="utf-8"))
    policy = tomllib.loads((folder / plan["paths"]["policy"]).read_text(encoding="utf-8"))
    report = json.loads((folder / "expected" / "report.json").read_bytes())
    kernel = VALIDATOR["independent_kernel"](folder / "plan.toml")
    sid = "S3" if corruption in {"dome_cap", "dome_cap_with_nominal"} else "S1"
    setup = next(item for item in plan["setups"] if item["id"] == sid)
    finding = next(
        item for item in report["findings"] if item["rule"] == "stickout" and item["subject"] == sid
    )
    VALIDATOR["check_stickout"](setup, plan, features, policy, copy.deepcopy(finding), kernel)
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
        VALIDATOR["check_stickout"](setup, plan, features, policy, finding, kernel)


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
    """The engine's own blind_depth findings for a changed pivot-shaft centre: its endpoint
    row, a validator call that checks them, and the centre's finding."""
    plan = shaft(tmp_path)
    if where == "plan":
        set_process_key(plan, "plain_end_centre", key, value)
    elif where == "tool":
        set_tool_fact(plan, key, value)
    bundle = load_bundle(plan)
    findings = {(f.rule, f.subject): f.to_dict() for f in endpoint_findings(bundle)}
    entries = VALIDATOR["entries_for"](bundle.inventory)
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
    entries = VALIDATOR["entries_for"](data.inventory)
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
    entries = VALIDATOR["entries_for"](data.inventory)
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
    entries = VALIDATOR["entries_for"](data.inventory)
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
    entries = VALIDATOR["entries_for"](data.inventory)
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


@pytest.mark.parametrize("debt", ["machine", "tool", "material"])
def test_speed_oracle_never_passes_a_row_on_unverified_inputs(debt):
    # The engine leaves the derated 750 rpm unknown; the report claims a pass and drops
    # the verification flags it prints.
    data = drill_bundle(depth_mm=40.0)
    if debt == "material":
        data.plan["stock"]["material_verify"] = True
    else:
        data.inventory[f"{debt}s"][{"machine": "mill", "tool": "drill"}[debt]]["verify"] = True
    finding, check = speed_finding(data)
    check()
    assert finding["status"] == "unknown"
    finding["status"] = "pass"
    finding["numbers"].update(material_verify=False, rpm_range_verify=False)
    with pytest.raises(ValueError):
        check()


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
            VALIDATOR["entries_for"](data.inventory),
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
    entries = VALIDATOR["entries_for"](bundle.inventory)
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
        entries = VALIDATOR["entries_for"](bundle.inventory)
        grid = VALIDATOR["dro_grid"](setup, bundle.features, entries)
        row["dro"] = [VALIDATOR["dro_target"](value, grid) for value in row["setup"]]
        row["dro_xy"] = row["dro"][:2]
    with pytest.raises(ValueError):
        check()


def blank_inputs():
    """The rocker-arm plan, whose prepared blank is checked with gauges no setup names,
    its inventory, and the ``prepared_blank`` finding the engine reports once the received
    blank fits: every check read through the plan's gauge and passing."""
    folder = ROOT / "examples" / "rocker-arm"
    plan = tomllib.loads((folder / "plan.toml").read_text(encoding="utf-8"))
    inventory = tomllib.loads((folder / plan["paths"]["inventory"]).read_text(encoding="utf-8"))
    prepared = plan["stock"]["prepared"]
    bands = {"length": [339.8, 340.2], "section_0": [64.9, 65.1], "section_1": [15.95, 16.05]}
    rows = {
        key: {"gauge": prepared["checks"][key], "limits_mm": band, "status": "pass"}
        for key, band in bands.items()
    }
    for key in ("flat", "square", "parallel"):
        method = prepared["methods"][key]
        rows[key] = {"gauge": "dti", "limit_mm": 0.05, "method": method, "status": "pass"}
    finding = {"status": "pass", "numbers": {"checks": rows}}
    return plan, inventory, {("prepared_blank", "stock.prepared"): finding}


@pytest.mark.parametrize("case", ["as_planned", "missing_gauge", "undeclared_gauge"])
def test_prepared_blank_gauges_resolve_through_their_own_finding(case):
    plan, inventory, findings = blank_inputs()
    finding = findings["prepared_blank", "stock.prepared"]
    rows = finding["numbers"]["checks"]
    checks = plan["stock"]["prepared"]["checks"]
    if case == "missing_gauge":
        checks["length"] = "calipers-36in"
        rows["length"] = {"gauge": "calipers-36in", "status": "error"}
        finding["status"] = "error"
    elif case == "undeclared_gauge":
        del checks["flat"]
        rows["flat"].update(gauge="unknown", status="unknown")
        finding["status"] = "unknown"
    entries = VALIDATOR["entries_for"](inventory)
    # No setup names them, so no tool_resolves finding reads them.
    assert VALIDATOR["check_references"]({"stock": plan["stock"], "setups": []}, entries, {}) == []
    missing = VALIDATOR["check_prepared_blank"](plan, inventory, findings)
    assert missing == (["calipers-36in"] if case == "missing_gauge" else [])


@pytest.mark.parametrize(
    "corruption",
    [
        "other_gauge",
        "missing_gauge_passed",
        "undeclared_gauge_passed",
        "unverified_gauge_passed",
        "size_band",
        "form_limit",
        "method",
        "verdict_better_than_row",
        "checks_never_read",
        "dropped_row",
        "no_finding",
        "approved_without_blank",
    ],
)
def test_prepared_blank_verdict_holds_to_the_plan_gauges_and_inventory(corruption):
    plan, inventory, findings = blank_inputs()
    finding = findings["prepared_blank", "stock.prepared"]
    rows = finding["numbers"]["checks"]
    prepared = plan["stock"]["prepared"]
    if corruption == "other_gauge":
        rows["length"]["gauge"] = "calipers"
    elif corruption == "missing_gauge_passed":
        prepared["checks"]["length"] = rows["length"]["gauge"] = "calipers-36in"
    elif corruption == "undeclared_gauge_passed":
        del prepared["checks"]["flat"]
        rows["flat"]["gauge"] = "unknown"
    elif corruption == "unverified_gauge_passed":
        inventory["gauges"]["dti"]["verify"] = True
    elif corruption == "size_band":
        rows["length"]["limits_mm"] = [339.0, 341.0]
    elif corruption == "form_limit":
        rows["flat"]["limit_mm"] = 0.5
    elif corruption == "method":
        rows["square"]["method"] = prepared["methods"]["flat"]
    elif corruption == "verdict_better_than_row":
        rows["square"]["status"] = "unknown"
    elif corruption == "checks_never_read":
        del finding["numbers"]["checks"]
    elif corruption == "dropped_row":
        del rows["parallel"]
    elif corruption == "no_finding":
        findings.clear()
    elif corruption == "approved_without_blank":
        del plan["stock"]["prepared"]
    with pytest.raises(ValueError):
        VALIDATOR["check_prepared_blank"](plan, inventory, findings)


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
    plan, features, _, _, report = cone_inputs()
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
        result = VALIDATOR["fit"](SimpleNamespace(plan=plan, features=features), setup)
        fit["numbers"].update(
            band_mm="unknown",
            guaranteed_mm="unknown",
            engagement_mm="unknown",
            engagement_dia_mm="unknown",
            missing=result["missing"],
        )
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


@pytest.mark.parametrize("corruption", ["unresolved", "refused", "no_kernel", "completed"])
def test_joint_assembly_verdict_is_the_validators_own_kernel_join(corruption):
    # The report approves S7's join as shipped, but the validator's own kernel run leaves
    # its joined stock unknown, refuses it or never ran; or the report claims a joint
    # feature completed that the join never completed.
    plan, features, _, _, report = cone_inputs()
    findings = {(row["rule"], row["subject"]): row for row in report["findings"]}
    assembly = findings["joint_assembly", "S7"]
    VALIDATOR["check_joint_declarations"](plan, features, findings, joined())
    assert assembly["status"] == "pass"
    kernel = joined()
    if corruption == "unresolved":
        kernel = joined("S7")
    elif corruption == "refused":
        kernel = joined("S7", error="spigot insertion sweep meets socket material")
    elif corruption == "no_kernel":
        kernel = lambda: {"status": "unknown", "reason": "FreeCAD kernel not found"}  # noqa: E731
    else:
        joined_kernel = joined()()
        joined_kernel["setups"]["S7"]["completed_joint_features"].remove("crank_spigot")
        kernel = lambda: joined_kernel  # noqa: E731
    with pytest.raises(ValueError, match="joint|assembly"):
        VALIDATOR["check_joint_declarations"](plan, features, findings, kernel)


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
    VALIDATOR["check_joint_declarations"](plan, features, findings, joined())
    assembly["status"] = "pass"
    with pytest.raises(ValueError, match="unavailable kernel cannot approve"):
        VALIDATOR["check_joint_declarations"](plan, features, findings, joined())
