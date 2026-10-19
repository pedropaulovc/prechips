"""Removable thread contracts never turn nominal agreement into joined geometry.

All numbers below are synthetic contract inputs, not physical shop measurements.
"""

from copy import deepcopy
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from prechips.inputs import BadInput
from prechips.joint_features import setup_joint, thread_facts, validate_threaded_joints
from prechips.material_routes import MaterialGraph
from prechips.model import ThreadedJoint, ThreadSeat
from prechips.rules import finish_route, joints
from prechips.rules.geometry_common import HAND, approach, cutting_action
from prechips.rules.resolution import MANUAL
from prechips.sheet import _Traveler
from prechips.thread_specs import match, mating_classes


def patch(normal):
    return {
        "at": [0.0, 0.0, 0.0],
        "normal": normal,
        "x": [1.0, 0.0, 0.0],
        "size_mm": [8.0, 8.0],
        "cite": ["synthetic contract fixture"],
    }


@pytest.fixture
def threaded():
    joint = ThreadedJoint.model_validate({
        "kind": "threaded",
        "socket": "female",
        "spigot": "male",
        "process": "Screw cap into tube by hand until the shoulders seat",
        "cite": ["synthetic contract fixture"],
        "engagement_mm": 4.0,
        "seat": {
            "socket": patch([0.0, 0.0, 1.0]),
            "spigot": patch([0.0, 0.0, -1.0]),
            "gap_mm": 0.0,
            "runout_clearance_mm": 0.5,
        },
    }).model_dump()
    definitions = {
        "female": {
            "kind": "threaded_hole", "frame": "model", "at": [0.0, 0.0, 0.0],
            "axis": [0.0, 0.0, 1.0], "depth": 6.0, "thread": "1/4-20 UNC",
            "thread_hand": "right", "thread_class": "2B",
        },
        "male": {
            "kind": "external_thread", "frame": "model", "at": [0.0, 0.0, 0.0],
            "axis": [0.0, 0.0, 1.0], "length": 6.0, "thread": "1/4-20 UNC",
            "thread_hand": "right", "thread_class": "2A",
        },
    }
    plan = {
        "stock": {"form": "round_bar"},
        "setups": [
            {"id": "P", "stock_in": "stock", "ops": [{
                "op": 10, "do": "part_off", "outputs": {
                    "tube": {"carries": "female"}, "cap": {"carries": "male"},
                },
            }]},
            {"id": "T", "stock_in": "stock_out.tube", "ops": []},
            {"id": "C", "stock_in": "stock_out.cap", "ops": []},
            {"id": "J", "machine": "bench", "stock_in": ["T", "C"],
             "joint": joint, "ops": []},
        ],
    }
    for output in plan["setups"][0]["ops"][0]["outputs"].values():
        output["pose"] = {
            "origin": [0.0, 0.0, 0.0], "x": [1.0, 0.0, 0.0],
            "y": [0.0, 1.0, 0.0], "z": [0.0, 0.0, 1.0],
            "binding": "synthetic contract registration",
            "cite": ["synthetic contract fixture; not a shop measurement"],
        }
    return SimpleNamespace(
        plan=plan,
        features={
            "units": "mm", "features": definitions,
            "frames": {"model": {
                "origin": [0.0, 0.0, 0.0], "x": [1.0, 0.0, 0.0],
                "y": [0.0, 1.0, 0.0], "z": [0.0, 0.0, 1.0],
            }},
        },
        feature_definitions=definitions,
        finished_feature_owners={"female": "body", "male": "cap"},
        inventory={}, policy={}, cutting_data={},
    )


def assembly(bundle):
    return bundle.plan["setups"][-1]


def joint(bundle):
    return assembly(bundle)["joint"]


def test_schema_and_split_branch_identity_are_explicit(threaded):
    ThreadSeat.model_validate(joint(threaded)["seat"])
    validate_threaded_joints(threaded.plan, threaded.features)
    MaterialGraph(threaded.plan, validate=True)
    facts = thread_facts(threaded, assembly(threaded))
    assert facts["socket_ref"] == "T"
    assert facts["spigot_ref"] == "C"
    assert facts["violations"] == facts["missing"] == []
    assert joints.evaluate_fit(threaded) == []
    [row] = joints.evaluate_thread(threaded)
    assert row.status == "unknown"
    assert row.numbers["unmodeled_geometry"]



def test_unknown_retained_pose_withholds_thread_ownership(threaded):
    threaded.plan["setups"][0]["ops"][0]["outputs"]["tube"]["pose"] = "unknown"
    facts = thread_facts(threaded, assembly(threaded))
    assert facts["socket_ref"] == "unknown"
    assert "socket retained-material ownership" in facts["missing"]
    assert joints.evaluate_thread(threaded)[0].status == "unknown"

@pytest.mark.parametrize("field,value", [
    ("fit", "clearance"), ("clearance_mm", [0.0, 0.1]),
    ("compound", {"product": "adhesive"}), ("method", "press"),
    ("forms", ["bonded_fillet"]), ("spigot", "female"), ("cite", []),
])
def test_schema_rejects_bonded_fit_fields_and_false_formed_faces(threaded, field, value):
    candidate = deepcopy(joint(threaded))
    candidate[field] = value
    with pytest.raises(ValidationError):
        ThreadedJoint.model_validate(candidate)


@pytest.mark.parametrize("role,kind", [("socket", "external_thread"), ("spigot", "threaded_hole")])
def test_cross_file_validation_rejects_reversed_roles(threaded, role, kind):
    threaded.features["features"][joint(threaded)[role]]["kind"] = kind
    with pytest.raises(BadInput):
        validate_threaded_joints(threaded.plan, threaded.features)


def test_cross_file_validation_rejects_missing_export_and_reused_thread(threaded):
    joint(threaded)["socket"] = "absent"
    with pytest.raises(BadInput):
        validate_threaded_joints(threaded.plan, threaded.features)
    joint(threaded)["socket"] = "female"
    duplicate = deepcopy(assembly(threaded))
    duplicate["id"] = "J2"
    threaded.plan["setups"].append(duplicate)
    with pytest.raises(BadInput):
        validate_threaded_joints(threaded.plan, threaded.features)


@pytest.mark.parametrize("field,value,cause", [
    ("thread", "1/4-28 UNF", "designations"),
    ("thread_hand", "left", "hands"),
    ("thread_class", "2B", "classes"),
    ("axis", [1.0, 0.0, 0.0], "collinear"),
    ("axis", [0.0, 0.0, 2.0], "unit vector"),
    ("at", [1.0, 0.0, 0.0], "collinear"),
    ("at", [0.0, 0.0, 20.0], "overlap"),
    ("length", 2.0, "depth"),
    ("length", 0.0, "positive"),
])
def test_known_thread_contradictions_are_errors(threaded, field, value, cause):
    threaded.features["features"]["male"][field] = value
    [row] = joints.evaluate_thread(threaded)
    assert row.status == "error"
    assert any(cause in reason for reason in row.numbers["violations"])
    assert setup_joint(threaded, assembly(threaded))["thread_error"]


@pytest.mark.parametrize("engagement", [0.0, -1.0, 7.0])
def test_invalid_or_excessive_actual_engagement_is_error(threaded, engagement):
    joint(threaded)["engagement_mm"] = engagement
    [row] = joints.evaluate_thread(threaded)
    assert row.status == "error"


@pytest.mark.parametrize("field,value", [
    ("gap_mm", -0.1), ("gap_mm", 0.1), ("runout_clearance_mm", -0.1),
])
def test_known_seat_gap_and_runout_contradictions_are_errors(threaded, field, value):
    joint(threaded)["seat"][field] = value
    [row] = joints.evaluate_thread(threaded)
    assert row.status == "error"


def test_nonopposing_or_disjoint_seat_patches_are_errors(threaded):
    seat = joint(threaded)["seat"]
    seat["spigot"]["normal"] = [0.0, 0.0, 1.0]
    assert joints.evaluate_thread(threaded)[0].status == "error"
    seat["spigot"]["normal"] = [0.0, 0.0, -1.0]
    seat["spigot"]["at"] = [100.0, 0.0, 0.0]
    assert joints.evaluate_thread(threaded)[0].status == "error"


@pytest.mark.parametrize("field", ["thread", "thread_hand", "thread_class", "at", "axis", "length"])
def test_unknown_thread_facts_remain_unknown(threaded, field):
    threaded.features["features"]["male"][field] = "unknown"
    facts = thread_facts(threaded, assembly(threaded))
    assert facts["missing"]
    assert facts["violations"] == []
    assert joints.evaluate_thread(threaded)[0].status == "unknown"


@pytest.mark.parametrize("field", ["seat", "engagement_mm"])
def test_unknown_actual_engagement_or_seating_is_not_inferred(threaded, field):
    joint(threaded)[field] = "unknown"
    payload = setup_joint(threaded, assembly(threaded))
    assert payload[field] == "unknown"
    assert payload["missing"]
    assert payload["reason"]
    assert joints.evaluate_thread(threaded)[0].status == "unknown"


@pytest.mark.parametrize("field", ["socket", "spigot", "gap_mm", "runout_clearance_mm"])
def test_partial_unknown_seat_is_explicit_debt(threaded, field):
    joint(threaded)["seat"][field] = "unknown"
    assert f"seat.{field}" in thread_facts(threaded, assembly(threaded))["missing"]
    assert joints.evaluate_thread(threaded)[0].status == "unknown"


def test_normalized_payload_never_invents_cylindrical_fill_or_engagement(threaded):
    payload = setup_joint(threaded, assembly(threaded))
    assert payload["engagement_mm"] == 4.0
    assert payload["kind"] == "threaded"
    assert "unmodeled" in payload["reason"]
    assert not {"fit", "band_mm", "guaranteed_mm", "compound", "engagement", "forms"} & payload.keys()
    joint(threaded)["engagement_mm"] = "unknown"
    assert setup_joint(threaded, assembly(threaded))["engagement_mm"] == "unknown"


def test_injected_bbox_cannot_certify_a_threaded_assembly(threaded, monkeypatch):
    monkeypatch.setattr("prechips.kernel.run_geometry", lambda bundle: {
        "status": "ok", "setups": {"J": {
            "stock_bbox_mm": {"min": [0.0, 0.0, 0.0], "max": [10.0, 10.0, 10.0]},
            "completed_joint_features": ["female", "male"],
        }},
    })
    [row] = joints.evaluate_assembly(threaded)
    assert row.status == "unknown"
    assert "unmodeled" in row.sentence


def test_bare_traveler_prints_removable_action_and_unconditional_hold(threaded):
    traveler = object.__new__(_Traveler)
    traveler.setup = assembly(threaded)
    traveler.plan = threaded.plan
    traveler.features = threaded.features["features"]
    traveler.faces = {}
    traveler.references = {}
    traveler.frames = {}
    traveler.records = {}
    traveler.decimals = 3
    text = traveler.joint_text(assembly(threaded))
    assert "removable threaded assembly" in text
    assert "male" in text and "female" in text
    assert "No bonding or press fit" in text
    debt = traveler.joint_debt(assembly(threaded))
    assert "STOP" in debt and "HOLD" in debt
    assert "no strength or retention certification" in debt


@pytest.mark.parametrize("required,actual,expected", [
    ("1/4-20 UNC", " 1/4 - 20 unc ", True),
    ("1/4-20", "0.25-20 UNC", True),
    ("M6 x 1", "m6×1.0", True),
    ("1/4-20 UNC", "1/4-28 UNF", False),
    ("1/4-20 UNC", "1/4-20 UNF", False),
    ("M6x1", "M6x0.75", False),
    ("#8-32 UNC", "#10-32 UNC", False),
])
def test_supported_fractional_and_metric_thread_comparisons(required, actual, expected):
    assert match(required, actual) is expected


@pytest.mark.parametrize("value", [
    "unknown", "", "unsupported", "1/0-20", "0/4-20", "1/4-0", "M6",
    "M6x0", "M6x1/0", "1//4-20", "1/4--20", None, 42, [], {},
])
def test_malformed_unsupported_or_unknown_designations_never_crash_or_pass(value):
    assert match(value, "1/4-20 UNC") is None
    assert match("1/4-20 UNC", value) is None


@pytest.mark.parametrize("female,male,expected", [
    ("2B", "2A", True), ("1b", "3a", True), ("2A", "2B", False),
    ("2B", "2B", False), ("unknown", "2A", None), ("6H", "6g", None),
])
def test_mating_classes_preserve_internal_external_roles(female, male, expected):
    assert mating_classes(female, male) is expected


def test_thread_geometry_transforms_frames_and_manifest_inches_to_mm(threaded):
    threaded.features["units"] = "in"
    frame = threaded.features["frames"]["model"]
    frame["origin"] = [1.0, 2.0, 3.0]
    frame["x"], frame["z"] = [0.0, 0.0, -1.0], [1.0, 0.0, 0.0]
    facts = thread_facts(threaded, assembly(threaded))
    for role in ("socket_geometry", "spigot_geometry"):
        assert facts[role]["at_mm"] == pytest.approx([25.4, 50.8, 76.2])
        assert facts[role]["axis"] == [1.0, 0.0, 0.0]
        assert facts[role]["depth_mm"] == pytest.approx(152.4)
    assert facts["engagement_mm"] == 4.0
    assert facts["seat"]["socket"]["size_mm"] == [8.0, 8.0]


def test_die_thread_is_manual_but_material_cutting_with_no_powered_approach(threaded):
    op = {"op": 20, "do": "die_thread", "feature": "male"}
    assert "die_thread" in MANUAL
    assert cutting_action(op) is True
    assert approach(threaded, assembly(threaded), op) == HAND


def test_die_thread_after_coating_cannot_keep_coating_coverage(threaded):
    threaded.plan["part"] = "synthetic-threaded-part"
    threaded.features["material"] = {"finish": "black oxide", "finish_kind": "coating"}
    # Isolate finish ordering on the real named cap branch of the one-bar split.
    cap = threaded.plan["setups"][2]
    cap["ops"] = [
        {"op": 10, "do": "coating"},
        {"op": 20, "do": "die_thread", "feature": "male"},
    ]
    [row] = finish_route.evaluate(threaded)
    assert row.status == "warn"
    assert "C:20" in row.numbers["uncoated_cuts"]


def test_die_thread_remains_a_final_forming_cut_and_finishing_subject(threaded):
    from prechips.rules.datum_consistency import _cuts
    from prechips.rules.geometry_common import finishing_subjects

    cap = threaded.plan["setups"][2]
    cap["ops"] = [
        {"op": 10, "do": "finish_turn", "feature": "male"},
        {"op": 20, "do": "die_thread", "feature": "male"},
    ]
    cuts = _cuts(threaded, "male")
    assert [(setup["id"], op["op"]) for _, setup, op in cuts] == [
        ("C", 10), ("C", 20),
    ]
    assert {"C:10", "C:20"} <= finishing_subjects(threaded)


def test_unknown_die_finish_withholds_an_earlier_known_turning_finish(threaded, monkeypatch):
    from prechips.rules import finish_coverage

    face = "#42/ADVANCED_FACE[1]/SYNTHETIC_THREAD"
    threaded.features["features"]["male"].update({
        "faces": [face], "requirements": ["finish_ra"], "finish_ra": 1.6,
    })
    cap = threaded.plan["setups"][2]
    cap["machine"] = "lathe"
    cap["ops"] = [{"op": 10, "do": "finish_turn", "feature": "male"}]
    threaded.inventory = {"machines": {"lathe": {"kind": "lathe", "verify": False}}}
    facts = {
        "status": "ok",
        "mapping": {face: 0},
        "features": {"male": [0]},
        "ops": {
            "C:10": {"approach": "turning", "claimed_indices": [0]},
            "C:20": {
                "approach": "hand",
                "claimed_indices": "unknown",
                "reason": "helical removal and resulting thread finish are unmodeled",
            },
        },
    }
    monkeypatch.setattr("prechips.kernel.run_geometry", lambda bundle: facts)
    before = next(row for row in finish_coverage.evaluate(threaded) if row.subject == "male")
    assert before.status == "pass"
    cap["ops"].append({"op": 20, "do": "die_thread", "feature": "male"})
    after = next(row for row in finish_coverage.evaluate(threaded) if row.subject == "male")
    assert after.status == "unknown"
