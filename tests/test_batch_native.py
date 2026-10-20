"""Four canonical STEP instances routed by three real finite mounted-saw cuts.

Only FreeCAD/OCC's native JSON boundary supplies verdicts.  The canonical solid
is authored independently, and expected stock/target boxes and volumes below are
numeric oracles, not values obtained from the registration helper under test.
"""

import base64
import hashlib
import json
import subprocess
from copy import deepcopy

import pytest
from test_kernel_geometry import IDENTITY, Engine
from test_kernel_retained_outputs import _probe
from test_mounted_saw_native import POSE, _box, _mounted, _pad

from prechips.kernel.step_faces import StepFile

FRAME = {
    "origin": [0, 0, 0],
    "x": [0, 0, -1],
    "y": [0, 1, 0],
    "z": [1, 0, 0],
}
STOCK = {
    "shape": "box",
    "origin_mm": [0, -6.35, -12.7],
    "axis": [1, 0, 0],
    "section_axis": [0, 1, 0],
    "length_mm": 113.665,
    "section_mm": [12.7, 25.4],
}
CUTS = (86.0425, 56.8325, 27.6225)
AREA = 25.4 * 12.7
KERF = 3.175
MEMBERS = ("nut1", "nut2", "nut3", "nut4")
# Canonical X is the bar's longitudinal direction, not setup Z.  These are
# geometrically valid placements; the contradictory historical plan is not an oracle.
ORIGINS = (100.33, 71.12, 41.91, 13.335)
TARGET_BOXES = {
    "nut1": [-5, -4, 87.63, 5, 4, 113.03],
    "nut2": [-5, -4, 58.42, 5, 4, 83.82],
    "nut3": [-5, -4, 29.21, 5, 4, 54.61],
    "nut4": [-5, -4, 0.635, 5, 4, 26.035],
}

_AUTHOR = r"""
import sys
import Part
from FreeCAD import Vector
out = sys.argv[sys.argv.index("--") + 1]
# Independent centered canonical STEP; no native frame/registration helpers.
canonical = Part.makeBox(25.4, 8, 10, Vector(-12.7, -4, -5))
assert canonical.isValid() and len(canonical.Solids) == 1
canonical.exportStep(out + "/canonical.step")
"""


def _hold():
    return {
        "kind": "solids",
        "fixture_kind": "custom",
        "pose": deepcopy(POSE),
        "solids": [
            _box("lower-front", [-12.7, -9.35, 0], [25.4, 3, 10]),
            _box("lower-back", [-12.7, 6.35, 0], [25.4, 3, 10]),
            _pad(),
        ],
        "clamps": [],
        "debts": [],
        "gaps": [],
    }


def _saw(z):
    saw = _mounted()
    saw["trajectory"] = {
        "start_mm": [-47.7, -16.891, z],
        "moves": [
            {"to_mm": [47.7, -16.891, z], "mode": "cut"},
            {"to_mm": [47.7, -60, z], "mode": "clear"},
            {"to_mm": [47.7, -60, 180], "mode": "clear"},
            {"to_mm": [-47.7, -60, 180], "mode": "clear"},
            {"to_mm": [-47.7, -16.891, 180], "mode": "clear"},
            {"to_mm": [-47.7, -16.891, z], "mode": "clear"},
        ],
    }
    # Contacts are on the actual upper child of this cut, never on a nominal
    # old 30-mm fixture.  The back/side pads lie above the blade/arbor band.
    for component, (at, size) in zip(
        saw["capture"]["components"],
        [
            ([-11.7, 6.35, z + 6], [23.4, 3, 5]),
            ([-15.7, 1.65, z + 6], [3, 3, 5]),
            ([12.7, 1.65, z + 6], [3, 3, 5]),
        ],
        strict=True,
    ):
        component["solids"] = [_box(component["name"], at, size)]
    return saw


def _route(engine, path, refs, selected):
    setups = []
    incoming = "stock"
    for number, z in enumerate(CUTS, 1):
        sid = f"S{number}"
        low = f"tail{number}" if number < 3 else "blank4"
        outputs = {
            low: {
                "side": "below",
                "carries_workpieces": list(MEMBERS[number:]),
                "pose": deepcopy(IDENTITY),
                "cite": "independent identity registration",
            },
            f"blank{number}": {
                "side": "above",
                "carries_workpieces": [f"nut{number}"],
                "pose": deepcopy(IDENTITY),
                "cite": "independent identity registration",
            },
        }
        setups.append(
            {
                "id": sid,
                "stock_in": incoming,
                "frame": deepcopy(FRAME),
                "machine_kind": "mill",
                "hold": _hold(),
                "ops": [
                    {
                        "subject": f"{sid}:10",
                        "do": "cut_off",
                        "saw_tool": "slitting_saw",
                        "cut_plane": {"axis": "z", "value": z, "keep": "below"},
                        "kerf_mm": KERF,
                        "mounted_saw": _saw(z),
                        "outputs": outputs,
                    }
                ],
            }
        )
        incoming = "stock_out." + low
    for number, member in enumerate(MEMBERS, 1):
        setups.append(
            {
                "id": f"N{number}",
                "stock_in": f"stock_out.blank{number}",
                "frame": deepcopy(FRAME),
                "machine_kind": "mill",
                "hold": _hold(),
                "ops": [
                    {
                        "subject": f"N{number}:20",
                        "do": "inspect",
                        "workpiece_faces": {member: [selected[member]]},
                    }
                ],
            }
        )
    job = engine.job(path, features={"canonical": refs}, setups=setups, stock=deepcopy(STOCK))
    job["workpieces"] = {
        member: {"pose": {**deepcopy(IDENTITY), "origin": [origin, 0, 0]}}
        for member, origin in zip(MEMBERS, ORIGINS, strict=True)
    }
    job["workpieces"]["nut4"]["pose"].update(x=[-1, 0, 0], y=[0, -1, 0])
    return job


def _pickup_request(setup):
    # Native treats scene_id as opaque.  Author this native-only scene identity
    # independently; host normalization/scene hashing has its own regressions.
    scene_id = hashlib.sha256(
        json.dumps(setup, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    request = {
        "model": "transverse_finder_v1",
        "axis": "x",
        "scene_id": scene_id,
        "from": "+x",
        "method": "edge_then_set",
        "face": "fixture:setting-pad:+x",
        "edge_mm": -117.0,
        "at_mm": [-100.0, 5.0],
        "approach_mm": 2.54,
        "retract_clearance_mm": 12.7,
        "check_jog_mm": 5.0,
        "tool": "edge-finder",
        "holder": "collet-9.525",
        "finder": {
            "tip_dia_mm": 5.08,
            "tip_length_mm": 6.35,
            "shank_dia_mm": 9.525,
            "projection_mm": 50.8,
            "holder_dia_mm": 32.0,
            "holder_gauge_len_mm": 20.0,
        },
        "surface": {"kind": "fixture", "name": "setting-pad", "side": "+x"},
        "reasons": [],
        "errors": [],
    }
    request["recipe_id"] = hashlib.sha256(
        json.dumps(request, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    return request


def _cases(job, refs, selected):
    cases = {"positive": job}

    def variant(name):
        cases[name] = deepcopy(job)
        return cases[name]

    def split(candidate, index=0):
        return candidate["setups"][index]["ops"][0]

    split(variant("duplicate-membership"))["outputs"]["tail1"]["carries_workpieces"].append("nut1")
    split(variant("missing-membership"))["outputs"]["tail1"]["carries_workpieces"].remove("nut4")
    repeated = variant("repeated-pose")
    repeated["workpieces"]["nut2"]["pose"] = deepcopy(repeated["workpieces"]["nut1"]["pose"])
    wrong = variant("wrong-member")
    wrong["setups"][3]["ops"][0]["workpiece_faces"] = {"nut2": [selected["nut2"]]}
    wrong = variant("wrong-canonical-face")
    wrong["setups"][3]["ops"][0]["workpiece_faces"] = {
        "nut1": ["#999999/ADVANCED_FACE[999999]/stale"]
    }
    # An actual sibling's valid proof is not evidence about the branch being operated on.
    sibling = variant("sibling-evidence")
    sibling["setups"][4]["ops"][0]["workpiece_faces"] = {"nut1": [selected["nut1"]]}
    low = split(variant("low-kerf-protected"), 2)
    low["cut_plane"]["value"] -= 0.16
    for point in [
        low["mounted_saw"]["trajectory"]["start_mm"],
        *[move["to_mm"] for move in low["mounted_saw"]["trajectory"]["moves"][:2]],
        low["mounted_saw"]["trajectory"]["moves"][-1]["to_mm"],
    ]:
        point[2] -= 0.16
    # Nut4's exact upper boundary is 26.035, the third kerf's lower face.
    # At end X-5.08, the R25.4 cap adds sqrt(25.4²-23.241²)
    # ≈10.25 mm at far Y+6.35, reaching X≈5.17 < stock X+12.7.
    # At near Y-6.35 its reach exceeds 23 mm: a far-corner ligament remains.
    for name, end in (("short-sweep", -10.0), ("residual-ligament", -5.08)):
        saw = split(variant(name))["mounted_saw"]
        # Keep withdrawal and lift axis-aligned at the shortened cut endpoint;
        # otherwise a diagonal clear move rejects trajectory syntax before
        # the finite sweep can measure the intended uncovered material.
        for move in saw["trajectory"]["moves"][:3]:
            move["to_mm"][0] = end
    for name, source in (("duplicate-child", "stock_out.blank1"), ("reused-root", "stock")):
        reuse = variant(name)
        reuse["setups"].append(
            {"id": "REUSE", "stock_in": source, "frame": deepcopy(FRAME), "ops": []}
        )
    alias = variant("nested-sibling-alias")
    alias["setups"] += [
        {"id": "ALIAS", "stock_in": "N2", "frame": deepcopy(FRAME), "ops": []},
        {"id": "JOIN", "stock_in": ["ALIAS", "N2"], "frame": deepcopy(FRAME), "ops": []},
    ]
    original = variant("original-bad-placements")
    for member in MEMBERS:
        original["workpieces"][member]["pose"]["origin"][0] -= 12.7
    for name, section in (
        ("engagement-debt", "blade"),
        ("zero-debt", "zero"),
        ("capture-debt", "capture"),
    ):
        saw = split(variant(name))["mounted_saw"]
        if section == "blade":
            saw["blade"].pop("flutes")
        elif section == "zero":
            saw["zero"]["touches"][0]["mounted_saw"]["spindle_state"] = "unknown"
        else:
            saw["capture"]["state"] = "unknown"
    debt = variant("fixture-debt")
    debt["setups"][3]["hold"]["supports"] = [
        {
            "placement": "posed",
            "id": "missing",
            "name": "missing",
            "ref": "unmeasured",
            "pose": "unknown",
            "solids": [],
            "reasons": ["support geometry is unmeasured"],
        }
    ]
    inventory = variant("posed-inventory")
    inventory["setups"][1]["hold"]["supports"] = [
        {
            "placement": "posed",
            "id": "rest",
            "name": "rest",
            "ref": "inventory.rest",
            "pose": {"origin_mm": [60, 40, 0], "x": [0, 1, 0], "z": [0, 0, 1]},
            "solids": [_box("support rest:pad", [0, 0, 0], [2, 3, 4])],
            "reasons": [],
        }
    ]
    embedded = variant("posed-inventory-clash")
    embedded["setups"][1]["hold"]["supports"] = deepcopy(inventory["setups"][1]["hold"]["supports"])
    embedded["setups"][1]["hold"]["supports"][0]["pose"]["origin_mm"] = [0, 0, 20]
    borrowed = variant("borrowed-stock")
    borrowed["setups"][1]["hold"]["supports"] = [
        {
            "placement": "posed",
            "id": "balance",
            "name": "balance",
            "stock_ref": "stock_out.blank1",
            "pose": {"origin_mm": [60, 40, -87.63], "x": [0, 0, 1], "z": [-1, 0, 0]},
            "reasons": [],
        }
    ]
    registered = variant("forward-output-registration")
    split(registered, 2)["outputs"]["blank4"]["pose"] = {
        "origin": [200, 30, 10],
        "x": [0, 1, 0],
        "y": [-1, 0, 0],
        "z": [0, 0, 1],
    }
    registered["setups"][6]["frame"] = {
        "origin": [200, 30, 10],
        "x": [0, 0, -1],
        "y": [-1, 0, 0],
        "z": [0, 1, 0],
    }
    for case in (
        "integrated-pickup",
        "integrated-pickup-moved-pad",
        "integrated-pickup-raised-pad",
    ):
        candidate = variant(case)
        setup = candidate["setups"][1]
        if case == "integrated-pickup-moved-pad":
            # Mutate the actual hold solid, not an expected contact or helper.
            setup["hold"]["solids"][2]["at_mm"][0] += 1.0
        elif case == "integrated-pickup-raised-pad":
            setup["hold"]["solids"][2]["size_mm"][2] = 55.0
        setup["zero_pickups"] = {"x": _pickup_request(setup)}
    return cases


@pytest.fixture(scope="module")
def batch_native(tmp_path_factory, freecad_kernel):
    directory = tmp_path_factory.mktemp("batch-native")
    script = directory / "author.py"
    script.write_text(_AUTHOR, encoding="utf-8")
    process = subprocess.run(
        [freecad_kernel, str(script), "--", str(directory)],
        capture_output=True,
        text=True,
        errors="replace",
        timeout=300,
    )
    path = directory / "canonical.step"
    assert path.exists(), process.stdout[-2000:] + process.stderr[-2000:]
    source = StepFile(path.read_text(encoding="latin-1"))
    refs = [face.ref for face in source.faces]
    assert len(refs) == 6
    engine = Engine(directory, freecad_kernel)
    inventory = engine.faces(path)
    positive_x = next(
        row["ref"]
        for row in inventory
        if abs(row["bbox_mm"][0] - 12.7) < 1e-6 and abs(row["bbox_mm"][3] - 12.7) < 1e-6
    )
    negative_x = next(
        row["ref"]
        for row in inventory
        if abs(row["bbox_mm"][0] + 12.7) < 1e-6 and abs(row["bbox_mm"][3] + 12.7) < 1e-6
    )
    selected = {member: negative_x if member == "nut4" else positive_x for member in MEMBERS}
    job = _route(engine, path, refs, selected)
    jobs = _cases(job, refs, selected)
    payload = engine.run({"jobs": list(jobs.values())})
    assert len(payload["results"]) == len(jobs), payload
    return {
        "results": dict(zip(jobs, payload["results"], strict=True)),
        "selected": selected,
        "job": job,
        "refs": refs,
        "directory": directory,
        "executable": freecad_kernel,
    }


def _result(batch_native, case="positive"):
    result = batch_native["results"][case]
    assert result["status"] == "ok", result
    return result


def test_three_native_cuts_preserve_four_targets_and_conserve_each_child(batch_native):
    result = _result(batch_native)
    assert result["mapping_errors"] == {}
    expected_members = [set(MEMBERS), set(MEMBERS[1:]), set(MEMBERS[2:])]
    top = 113.665
    for number, (z, members) in enumerate(zip(CUTS, expected_members, strict=True), 1):
        facts = result["setups"][f"S{number}"]
        assert set(facts["workpieces"]) == members
        assert all(row["status"] == "pass" for row in facts["workpieces"].values())
        saw = result["ops"][f"S{number}:10"]["saw"]
        assert saw["status"] == saw["capture"]["status"] == "pass", saw
        assert saw["engagement"]["status"] == saw["zero"]["status"] == "pass", saw
        assert saw["collisions"] == []
        assert saw["stock_volume_before_mm3"] == pytest.approx(AREA * top, abs=1e-5)
        assert saw["removed_kerf_volume_mm3"] == pytest.approx(AREA * KERF, abs=1e-5)
        heights = [z - KERF / 2, top - z - KERF / 2]
        assert [row["volume_mm3"] for row in saw["outputs"]] == pytest.approx(
            [AREA * height for height in heights], abs=1e-5
        )
        assert sum(row["volume_mm3"] for row in saw["outputs"]) + AREA * KERF == pytest.approx(
            AREA * top
        )
        outputs = facts["outputs"]
        assert len(outputs) == 2
        assert set().union(*(set(row["carries_workpieces"]) for row in outputs.values())) == members
        assert sum(len(row["carries_workpieces"]) for row in outputs.values()) == len(members)
        for row in outputs.values():
            assert row["status"] == "pass", row
            assert row["conservation_error_mm3"] == pytest.approx(0, abs=1e-5)
            assert row["children_volume_mm3"] == pytest.approx([AREA * h for h in heights])
        top = z - KERF / 2
    # Closed target boundaries touch kerf faces without losing volume: nut1's
    # lower face and nut4's upper face lie on the corresponding kerf boundaries.
    assert TARGET_BOXES["nut1"][2] == pytest.approx(CUTS[0] + KERF / 2)
    assert TARGET_BOXES["nut4"][5] == pytest.approx(CUTS[2] - KERF / 2)


def test_qualified_faces_subjects_and_nested_members_survive_json_and_render(batch_native):
    result = json.loads(json.dumps(_result(batch_native)))
    mapping = result["workpiece_mapping"]
    assert set(mapping) == set(MEMBERS)
    assert all(set(member) == set(batch_native["refs"]) for member in mapping.values())
    indices = [index for member in mapping.values() for index in member.values()]
    assert len(indices) == len(set(indices)) == 24
    claimed = []
    for number, member in enumerate(MEMBERS, 1):
        facts = result["setups"][f"N{number}"]
        assert set(facts["workpieces"]) == {member}
        proof = facts["workpieces"][member]
        assert proof["status"] == "pass", proof
        assert proof["volume_mm3"] == pytest.approx(2032)
        assert proof["bbox_mm"] == pytest.approx(TARGET_BOXES[member])
        expected_path = [{"split": f"S{i}", "output": f"tail{i}"} for i in range(1, min(number, 3))]
        expected_path.append({"split": f"S{min(number, 3)}", "output": f"blank{number}"})
        assert proof["partition_path"] == expected_path
        detail = result["ops"][f"N{number}:20"]
        selected = batch_native["selected"][member]
        assert detail["workpiece_faces"] == {member: [selected]}
        assert detail["claimed_indices"] == [mapping[member][selected]], detail
        claimed.extend(detail["claimed_indices"])
        assert base64.b64decode(facts["render_png_base64"]).startswith(b"\x89PNG\r\n\x1a\n")
        assert facts["render_scene"]["workpieces"][member]["status"] == "pass"
        assert facts["render_scene"]["workpiece_claims"] == {f"N{number}:20": {member: [selected]}}
    assert len(set(claimed)) == 4


@pytest.mark.parametrize(
    "case",
    [
        "duplicate-membership",
        "missing-membership",
        "low-kerf-protected",
        "short-sweep",
        "residual-ligament",
    ],
)
def test_failed_partition_never_publishes_children_or_downstream_proof(batch_native, case):
    result = _result(batch_native, case)
    sid = "S3" if case == "low-kerf-protected" else "S1"
    outputs = result["setups"][sid].get("outputs", {})
    assert not any(
        row.get("status") == "pass" or "volume_mm3" in row for row in outputs.values()
    ), outputs
    downstream = "N3" if case == "low-kerf-protected" else "N1"
    following = result["setups"][downstream]
    assert "stock_bbox_mm" not in following
    assert result["ops"][downstream + ":20"]["claimed_indices"] == "unknown"
    if case in {"short-sweep", "residual-ligament"}:
        saw = result["ops"]["S1:10"]["saw"]
        assert saw["status"] != "pass"
        assert saw["uncovered_kerf_volume_mm3"] > 0


def test_repeated_registration_is_not_a_second_physical_workpiece(batch_native):
    result = batch_native["results"]["repeated-pose"]
    assert result["status"] != "ok", result
    assert "overlap" in json.dumps(result).lower()


@pytest.mark.parametrize(
    "case,subject",
    [("wrong-member", "N1:20"), ("wrong-canonical-face", "N1:20"), ("sibling-evidence", "N2:20")],
)
def test_qualified_claim_cannot_borrow_sibling_or_guess_canonical_face(batch_native, case, subject):
    result = _result(batch_native, case)
    assert result["ops"][subject]["claimed_indices"] == "unknown"
    assert result["ops"][subject]["workpiece_faces"] == {}
    # The sibling's independently executed operation remains a real proof.
    untouched = "N2:20" if subject == "N1:20" else "N1:20"
    assert isinstance(result["ops"][untouched]["claimed_indices"], list)


@pytest.mark.parametrize(
    "case,sid",
    [("duplicate-child", "REUSE"), ("reused-root", "REUSE"), ("nested-sibling-alias", "JOIN")],
)
def test_consumed_parent_child_and_nested_aliases_never_reenter_material(batch_native, case, sid):
    facts = _result(batch_native, case)["setups"][sid]
    assert "stock_bbox_mm" not in facts, facts
    assert facts.get("stock_reason"), facts


@pytest.mark.parametrize("case,section", [("engagement-debt", "engagement"), ("zero-debt", "zero")])
def test_independent_mount_statuses_survive_complete_route(batch_native, case, section):
    result = _result(batch_native, case)
    saw = result["ops"]["S1:10"]["saw"]
    assert saw["status"] == saw["capture"]["status"] == "pass", saw
    assert saw[section]["status"] != "pass"
    other = "zero" if section == "engagement" else "engagement"
    assert saw[other]["status"] == "pass"
    assert all(row["status"] == "pass" for row in result["setups"]["S1"]["outputs"].values())


def test_capture_debt_does_not_become_an_empty_fixture_pass(batch_native):
    result = _result(batch_native, "capture-debt")
    saw = result["ops"]["S1:10"]["saw"]
    assert saw["capture"]["status"] != "pass", saw
    assert saw["status"] != "pass"
    assert not any(
        row.get("status") == "pass" for row in result["setups"]["S1"].get("outputs", {}).values()
    )


def test_return_path_sweeps_whole_assembly_not_only_cutting_move(batch_native):
    for number, z in enumerate(CUTS, 1):
        saw = _result(batch_native)["ops"][f"S{number}:10"]["saw"]
        assert saw["axis_path_bounds_mm"] == pytest.approx([-47.7, -60, z, 47.7, -16.891, 228])
        assert saw["spindle_nose_bounds_mm"] == pytest.approx(
            [-47.7, -60, z + 48, 47.7, -16.891, 228]
        )
        assert saw["assembly_swept_bounds_mm"][2] == pytest.approx(z - 4)
        assert saw["assembly_swept_bounds_mm"][5] == pytest.approx(228)


def test_incomplete_placed_support_remains_contact_and_collision_debt(batch_native):
    facts = _result(batch_native, "fixture-debt")["setups"]["N1"]
    assert facts["fixture_rendered"] is False, facts
    assert any("support missing" in reason for reason in facts["fixture_clash_debts"])
    assert facts["render_scene"]["debts"], facts["render_scene"]


def test_original_uncentered_plan_translations_are_not_certified(batch_native):
    result = batch_native["results"]["original-bad-placements"]
    assert result["status"] == "ok", result
    first = result["setups"]["S1"]
    assert any(row["status"] != "pass" for row in first["workpieces"].values()), first
    assert not any(row.get("status") == "pass" for row in first.get("outputs", {}).values())
    assert result["ops"]["N4:20"]["claimed_indices"] == "unknown"


def test_output_registration_moves_actual_stock_and_targets_forward_once(batch_native):
    result = _result(batch_native, "forward-output-registration")
    output = result["setups"]["S3"]["outputs"]["blank4"]
    assert output["status"] == "pass", output
    assert output["bbox_mm"] == pytest.approx([193.65, 30, -2.7, 206.35, 56.035, 22.7])
    assert output["volume_mm3"] == pytest.approx(AREA * 26.035)
    downstream = result["setups"]["N4"]
    assert downstream["stock_bbox_mm"] == pytest.approx([-12.7, -6.35, 0, 12.7, 6.35, 26.035])
    assert downstream["workpieces"]["nut4"]["bbox_mm"] == pytest.approx(TARGET_BOXES["nut4"])
    assert downstream["workpieces"]["nut4"]["status"] == "pass"
    assert result["ops"]["N4:20"]["claimed_indices"] == [
        result["workpiece_mapping"]["nut4"][batch_native["selected"]["nut4"]]
    ]


@pytest.mark.parametrize(
    "case,expected_box",
    [
        ("posed-inventory", [57, 40, 0, 60, 42, 4]),
        ("posed-inventory-clash", [-3, 0, 20, 0, 2, 24]),
    ],
)
def test_inventory_support_checked_and_rendered_at_identical_real_pose(
    batch_native, case, expected_box
):
    facts = _result(batch_native, case)["setups"]["S2"]
    components = [
        row for row in facts["render_scene"]["components"] if row.get("support_id") == "rest"
    ]
    assert len(components) == 1, facts["render_scene"]
    assert components[0]["name"] == "support rest:pad"
    assert components[0]["ref"] == "inventory.rest"
    assert components[0]["bbox_mm"] == pytest.approx(expected_box)
    assert components[0]["exact"] is True
    if case == "posed-inventory-clash":
        assert any("support rest:pad" in clash for clash in facts["fixture_clashes"]), facts
    else:
        assert facts["fixture_clashes"] == [], facts


def test_borrowed_proved_stock_is_fixture_not_consumption_or_material_join(batch_native):
    result = _result(batch_native, "borrowed-stock")
    facts = result["setups"]["S2"]
    components = [
        row for row in facts["render_scene"]["components"] if row.get("support_id") == "balance"
    ]
    assert len(components) == 1, facts["render_scene"]
    support = components[0]
    assert support["stock_ref"] == "stock_out.blank1"
    assert support["role"] == "fixture"
    assert support["exact"] is True
    assert support["bbox_mm"] == pytest.approx([47.3, 33.65, 0, 72.7, 46.35, 26.035])
    assert facts["stock_volume_mm3"] == pytest.approx(AREA * 84.455)
    assert set(facts["workpieces"]) == {"nut2", "nut3", "nut4"}
    # N1 subsequently consumes the very same named output: borrowing cannot
    # consume it, and must not append nut1 to S2's cutting material membership.
    later = result["setups"]["N1"]
    assert later["stock_volume_mm3"] == pytest.approx(AREA * 26.035)
    assert later["workpieces"]["nut1"]["status"] == "pass"
    assert isinstance(result["ops"]["N1:20"]["claimed_indices"], list)


_NESTED_PARTITIONS = r"""
import copy, importlib.util, json, os, sys
spec = importlib.util.spec_from_file_location("batch_engine", os.environ["RETAINED_ENGINE"])
engine = importlib.util.module_from_spec(spec)
spec.loader.exec_module(engine)
directory, target = sys.argv[sys.argv.index("--") + 1:]
with open(os.path.join(directory, "job.json"), encoding="utf-8") as stream:
    job = json.load(stream)
owner = engine._Job(job)
result = owner.run()
assert result["status"] == "ok", result
for sid in ("S1", "S2", "S3"):
    assert all(row["status"] == "pass" for row in result["setups"][sid]["outputs"].values())
sources = dict(owner.outputs)
def copy_native_state(value):
    # OCC topology and FreeCAD matrices cannot be pickled by deepcopy.
    if isinstance(value, engine.FreeCAD.Matrix):
        return engine.FreeCAD.Matrix(value)
    if isinstance(value, engine.Part.Shape):
        return value.copy()
    if isinstance(value, dict):
        return {key: copy_native_state(item) for key, item in value.items()}
    if isinstance(value, list):
        return [copy_native_state(item) for item in value]
    if isinstance(value, tuple):
        return tuple(copy_native_state(item) for item in value)
    if isinstance(value, set):
        return {copy_native_state(item) for item in value}
    return copy.deepcopy(value)

# A different string for an identical physical output must not bypass lineage.
sources["alias_blank3"] = (sources["stock_out.blank3"][0].copy(), None)
owner.states["alias_blank3"] = copy_native_state(owner.states["stock_out.blank3"])
out = {}
for case, refs in (
    ("divergent_nested_siblings", ["stock_out.blank1", "stock_out.blank3"]),
    ("ancestor_and_descendant", ["stock_out.tail1", "stock_out.blank3"]),
    ("identical_path_aliases", ["stock_out.blank3", "alias_blank3"]),
):
    # Exercise path comparison itself rather than the earlier consumed-ref gate.
    owner.consumed_refs = set()
    shape, reason, state, error = owner._held({"id": "PROBE", "stock_in": refs}, sources)
    out[case] = {
        "shape_known": shape is not None, "reason": reason, "error": error,
        "actual_intersection_mm3": sources[refs[0]][0].common(sources[refs[1]][0]).Volume,
        "input_paths": [
            [[{"split": split, "output": output} for split, output in path]
             for paths in owner.states[ref]["partitions"].values() for path in sorted(paths)]
            for ref in refs
        ],
    }
"""


@pytest.fixture(scope="module")
def nested_partition_probe(batch_native):
    directory = batch_native["directory"] / "nested-partitions"
    directory.mkdir()
    (directory / "job.json").write_text(json.dumps(batch_native["job"]), encoding="utf-8")
    return _probe(_NESTED_PARTITIONS, directory, batch_native["executable"])


def test_nested_siblings_are_disjoint_at_first_differing_partition_edge(nested_partition_probe):
    proof = nested_partition_probe["divergent_nested_siblings"]
    assert proof["input_paths"] == [
        [[{"split": "S1", "output": "blank1"}]],
        [
            [
                {"split": "S1", "output": "tail1"},
                {"split": "S2", "output": "tail2"},
                {"split": "S3", "output": "blank3"},
            ]
        ],
    ]
    assert proof["actual_intersection_mm3"] == pytest.approx(0, abs=1e-6)
    assert proof["shape_known"] is False
    # Reaching this later gate proves the real paths were admitted as siblings;
    # absence of a physical joint still correctly withholds assembled stock.
    assert proof["error"] == "every stock_in array requires a declared joint"


@pytest.mark.parametrize("case", ["ancestor_and_descendant", "identical_path_aliases"])
def test_nested_ancestor_and_same_path_alias_fail_without_consumption_shortcut(
    nested_partition_probe, case
):
    proof = nested_partition_probe[case]
    assert proof["shape_known"] is False
    assert proof["error"] == "stock_in branches share component ancestry"
    assert proof["actual_intersection_mm3"] == pytest.approx(AREA * 26.035)


@pytest.fixture(scope="module")
def batch_supply_contacts(batch_native):
    engine = Engine(batch_native["directory"], batch_native["executable"])
    source = batch_native["job"]["step_path"]
    # Select the authored canonical underside by independent geometry, not by
    # native instance import order or a member's contact verdict.
    underside = next(
        face["ref"]
        for face in engine.faces(source)
        if abs(face["bbox_mm"][2] + 5) < 1e-6 and abs(face["bbox_mm"][5] + 5) < 1e-6
    )
    job = deepcopy(batch_native["job"])
    job["setups"] = []
    job["stock"].update(origin_mm=[0, -4, -5], section_mm=[8, 10])
    job["as_is_faces"] = [underside]
    shifted = deepcopy(job)
    shifted["workpieces"]["nut2"]["pose"]["origin"][2] += 1
    results = engine.run({"jobs": [job, shifted]})["results"]
    assert len(results) == 2
    return underside, results


def test_as_is_supply_contact_is_proved_for_every_registered_member(batch_supply_contacts):
    ref, (result, _) = batch_supply_contacts
    assert result["status"] == "ok", result
    assert "as_is_contact" not in result
    assert set(result["workpiece_as_is_contact"]) == set(MEMBERS)
    assert "reason" not in result["stock"], result["stock"]
    for member in MEMBERS:
        contacts = result["workpiece_as_is_contact"][member]
        assert set(contacts) == {ref}
        assert contacts[ref]["contact"] == "on_supply", (member, contacts)
        assert contacts[ref]["max_gap_mm"] == pytest.approx(0, abs=1e-6)
        assert contacts[ref]["supplies"]


def test_one_shifted_member_cannot_borrow_siblings_as_is_supply_contact(batch_supply_contacts):
    ref, (_, result) = batch_supply_contacts
    assert result["status"] == "ok", result
    assert "as_is_contact" not in result
    assert result["stock"]["reason"], result["stock"]
    for member in MEMBERS:
        row = result["workpiece_as_is_contact"][member][ref]
        if member == "nut2":
            assert row["contact"] == "off_supply", row
            assert row["max_gap_mm"] == pytest.approx(1, abs=1e-6)
            assert row["supplies"] == []
        else:
            assert row["contact"] == "on_supply", (member, row)
            assert row["max_gap_mm"] == pytest.approx(0, abs=1e-6)


def test_whole_job_pickup_proves_actual_fixture_and_full_stack_from_arriving_child(batch_native):
    result = _result(batch_native, "integrated-pickup")
    setup = result["setups"]["S2"]
    proof = setup["zero_pickups"]["x"]
    request = _pickup_request(batch_native["job"]["setups"][1])
    assert proof["status"] == "pass", proof
    assert proof["setup_id"] == "S2" and proof["axis"] == "x"
    assert proof["model"] == "transverse_finder_v1"
    assert proof["recipe_id"] == request["recipe_id"]
    assert proof["request"]["scene_id"] == request["scene_id"]
    assert proof["request"] == request
    assert proof["resolved_contact"]["plane_mm"] == pytest.approx(-117.0)
    assert proof["resolved_contact"]["axis_mm"] == pytest.approx([-114.46, -100, 5])
    assert proof["resolved_contact"]["tip_span_mm"] == pytest.approx([5, 11.35])
    assert proof["resolved_contact"]["contact_z_mm"] == pytest.approx([5, 10])
    assert proof["path"]["stock_top_mm"] == pytest.approx(84.455)
    assert proof["path"]["retract_height_mm"] == pytest.approx(97.155)
    assert proof["path"]["start_mm"] == pytest.approx([-111.92, -100, 97.155])
    assert proof["path"]["contact_mm"] == pytest.approx([-114.46, -100, 5])
    assert proof["path"]["complete"] is True
    assert proof["path"]["jog_mm"] == pytest.approx(5.0)
    assert [leg["to_mm"] for leg in proof["path"]["legs"]] == [
        pytest.approx([-111.92, -100, 5]),
        pytest.approx([-114.46, -100, 5]),
        pytest.approx([-114.46, -100, 97.155]),
        pytest.approx([-109.46, -100, 97.155]),
    ]
    assert [leg["kind"] for leg in proof["path"]["legs"]] == [
        "descend",
        "approach",
        "retract",
        "check_jog",
    ]
    assert all(
        {component["id"] for component in leg["components"]} == {"tip", "shank", "holder"}
        for leg in proof["path"]["legs"]
    )
    assert proof["collisions"] == []
    pad = next(row for row in setup["render_scene"]["components"] if row["name"] == "setting-pad")
    assert pad["bbox_mm"] == pytest.approx([-119, -101, 5, -117, -99, 10])
    assert result["ops"]["S2:10"]["saw"]["status"] == "pass"
    assert result["setups"]["N2"]["workpieces"]["nut2"]["status"] == "pass"


def test_whole_job_pickup_reads_moved_hold_solid_instead_of_stale_fixture_proof(batch_native):
    original = _result(batch_native, "integrated-pickup")["setups"]["S2"]["zero_pickups"]["x"]
    setup = _result(batch_native, "integrated-pickup-moved-pad")["setups"]["S2"]
    proof = setup["zero_pickups"]["x"]
    assert proof["status"] == "error", proof
    assert proof["errors"], proof
    assert proof["recipe_id"] != original["recipe_id"]
    assert proof["request"]["scene_id"] != original["request"]["scene_id"]
    assert proof["request"]["edge_mm"] == original["request"]["edge_mm"] == -117.0
    pad = next(row for row in setup["render_scene"]["components"] if row["name"] == "setting-pad")
    assert pad["bbox_mm"] == pytest.approx([-118, -101, 5, -116, -99, 10])


def test_whole_job_pickup_detects_shank_collision_with_actual_raised_fixture(batch_native):
    setup = _result(batch_native, "integrated-pickup-raised-pad")["setups"]["S2"]
    proof = setup["zero_pickups"]["x"]
    assert proof["status"] == "error", proof
    # The selected plane and tip contact remain correct; only the real fixture
    # height changed.  A tip-only path would incorrectly certify this request.
    assert proof["resolved_contact"]["plane_mm"] == pytest.approx(-117.0)
    assert proof["resolved_contact"]["axis_mm"] == pytest.approx([-114.46, -100, 5])
    assert proof["path"]["stock_top_mm"] == pytest.approx(84.455)
    hits = [
        hit
        for hit in proof["collisions"]
        if hit["component"] == "shank" and hit["obstacle"] == "setting-pad"
    ]
    assert hits, proof
    assert all(hit["volume_mm3"] > 1e-6 for hit in hits)
    pad = next(row for row in setup["render_scene"]["components"] if row["name"] == "setting-pad")
    assert pad["bbox_mm"] == pytest.approx([-119, -101, 5, -117, -99, 60])


def test_actual_native_nested_proofs_are_consumable_by_host_rules(batch_native):
    from batch_rule_bridge import host_bundle_from_native

    from prechips.rules.geometry_common import op_claims
    from prechips.rules.resolution import (
        canonical_face_mapping,
        member_protection_evidence,
        member_protection_status,
        operation_material_status,
    )

    result = _result(batch_native)
    bundle = host_bundle_from_native(batch_native["job"], result, batch_native["refs"])
    assert bundle.kernel is result
    assert bundle.finished_feature_owners == {"canonical": "canonical_solid"}
    # Independent authored route expectations, never generated from MaterialGraph.
    expected_paths = {
        "nut1": [{"split": "S1", "output": "blank1"}],
        "nut2": [
            {"split": "S1", "output": "tail1"},
            {"split": "S2", "output": "blank2"},
        ],
        "nut3": [
            {"split": "S1", "output": "tail1"},
            {"split": "S2", "output": "tail2"},
            {"split": "S3", "output": "blank3"},
        ],
        "nut4": [
            {"split": "S1", "output": "tail1"},
            {"split": "S2", "output": "tail2"},
            {"split": "S3", "output": "blank4"},
        ],
    }
    for number, member in enumerate(MEMBERS, 1):
        sid = f"N{number}"
        setup = next(row for row in bundle.plan["setups"] if row["id"] == sid)
        native = result["setups"][sid]["workpieces"][member]
        assert native["partition_path"] == expected_paths[member]
        evidence = member_protection_evidence(bundle, setup, member)
        assert evidence["status"] == "pass", evidence
        assert evidence["proof"] is native
        assert member_protection_status(bundle, setup, member) is True
        assert canonical_face_mapping(bundle, result, setup) == result["workpiece_mapping"][member]
        assert (
            operation_material_status(bundle, setup, "S1", "canonical", workpiece_id=member) is True
        )
        claimed, away, invalid = op_claims(bundle, result, setup, setup["ops"][0])
        assert claimed == {result["workpiece_mapping"][member][batch_native["selected"][member]]}
        assert away == invalid == []
    assert operation_material_status(bundle, "N3", "S1", "canonical", workpiece_id="nut4") is False


def test_actual_native_operation_subject_paths_are_stale_rule_debt(batch_native):
    from batch_rule_bridge import host_bundle_from_native

    from prechips.rules.geometry_common import op_claims
    from prechips.rules.resolution import canonical_face_mapping, member_protection_evidence

    result = deepcopy(_result(batch_native))
    native = result["setups"]["N3"]["workpieces"]["nut3"]
    for edge in native["partition_path"]:
        edge["split"] += ":10"
    bundle = host_bundle_from_native(batch_native["job"], result, batch_native["refs"])
    setup = next(row for row in bundle.plan["setups"] if row["id"] == "N3")
    evidence = member_protection_evidence(bundle, setup, "nut3")
    assert evidence["status"] == "unknown", evidence
    assert evidence["proof"] == {}
    assert canonical_face_mapping(bundle, result, setup) == {}
    assert op_claims(bundle, result, setup, setup["ops"][0])[0] is None
    assert member_protection_evidence(bundle, "N4", "nut4")["status"] == "pass"


@pytest.mark.parametrize("wrong", ["registration", "workpiece_id"])
def test_actual_native_member_proof_cannot_be_borrowed_or_stale(batch_native, wrong):
    from batch_rule_bridge import host_bundle_from_native

    from prechips.rules.resolution import canonical_face_mapping, member_protection_evidence

    result = deepcopy(_result(batch_native))
    native = result["setups"]["N3"]["workpieces"]["nut3"]
    if wrong == "registration":
        native["registration"]["pose"]["origin"][0] += 1
    else:
        native["workpiece_id"] = "nut4"
    bundle = host_bundle_from_native(batch_native["job"], result, batch_native["refs"])
    evidence = member_protection_evidence(bundle, "N3", "nut3")
    assert evidence["status"] == "unknown", evidence
    assert evidence["proof"] == {}
    assert canonical_face_mapping(bundle, result, "N3") == {}
    assert member_protection_evidence(bundle, "N4", "nut4")["status"] == "pass"


def test_actual_native_containment_error_is_not_wrong_member_identity(batch_native):
    from batch_rule_bridge import host_bundle_from_native

    from prechips.rules.resolution import (
        canonical_face_mapping,
        member_protection_evidence,
        member_protection_status,
        operation_material_status,
    )

    job = deepcopy(batch_native["job"])
    # This existing native case independently exposes nut4 beyond the root stock.
    for member in MEMBERS:
        job["workpieces"][member]["pose"]["origin"][0] -= 12.7
    result = _result(batch_native, "original-bad-placements")
    bundle = host_bundle_from_native(job, result, batch_native["refs"])
    native = result["setups"]["S1"]["workpieces"]["nut4"]
    assert native["status"] == "error", native
    evidence = member_protection_evidence(bundle, "S1", "nut4")
    assert evidence["status"] == "error", evidence
    assert evidence["setup_id"] == "S1" and evidence["workpiece_id"] == "nut4"
    assert evidence["proof"] is native
    assert evidence["proof"]["partition_path"] == []
    assert evidence["proof"]["registration"] == job["workpieces"]["nut4"]
    assert evidence["reasons"]
    assert member_protection_status(bundle, "S1", "nut4") is None
    assert operation_material_status(bundle, "S1", "S1", "canonical", workpiece_id="nut4") is None
    assert canonical_face_mapping(bundle, result, "S1", workpiece_id="nut4") == {}
    assert member_protection_status(bundle, "S1", "nut1") is True
