"""Registered members retain canonical identity through three finite partitions."""

import copy
from types import SimpleNamespace

import pytest
from test_input_contracts import PLAN, bundle_files
from test_material_routes import SOLIDS, STEP

from prechips.inputs import BadInput, _placed_supports, load_bundle
from prechips.material_routes import (
    Material,
    MaterialGraph,
    Partition,
    feature_branch_status,
    feature_material_status,
    material_coverage_status,
    workpiece_status,
)
from prechips.model import AxisZero, Hold, Inventory, PlacedSupport, Plan

CITE = "Synthetic host route contract; not measured shop geometry"
FACE = "#1/ADVANCED_FACE[1]/body"
OWNERS = SimpleNamespace(finished_feature_owners={"face": "body", "unresolved": None})


def pose(x=0.0, *, reverse=False):
    return {
        "origin": [x, 0.0, 0.0],
        "x": [-1.0 if reverse else 1.0, 0.0, 0.0],
        "y": [0.0, -1.0 if reverse else 1.0, 0.0],
        "z": [0.0, 0.0, 1.0],
        "binding": "Authored canonical registration",
        "cite": CITE,
    }


def output(side, members):
    return {"side": side, "carries_workpieces": members, "pose": pose(), "cite": CITE}


def cut(sid, incoming, height, lower, upper, low_members, high_members):
    return {
        "id": sid,
        "stock_in": incoming,
        "ops": [
            {
                "op": 10,
                "do": "cut_off",
                "cut_plane": {"axis": "z", "value": height},
                "saw_trajectory": {
                    "start_mm": [-140.0, 0.0, height],
                    "moves": [{"to_mm": [0.0, 0.0, height], "mode": "cut"}],
                },
                "outputs": {
                    lower: output("below", low_members),
                    upper: output("above", high_members),
                },
            }
        ],
    }


def batch():
    plan = {
        "part": "batch-host",
        "features": "features.toml",
        "workpieces": {
            name: {"pose": pose(x, reverse=name == "nut4"), "cite": CITE}
            for name, x in zip(
                ("nut1", "nut2", "nut3", "nut4"), (100.33, 71.12, 41.91, 13.335), strict=True
            )
        },
        "setups": [
            {"id": "P0", "stock_in": "stock"},
            cut("C1a", "P0", 86.0425, "lower1", "nut1_b", ["nut2", "nut3", "nut4"], ["nut1"]),
            cut("C1b", "stock_out.lower1", 56.8325, "lower2", "nut2_b", ["nut3", "nut4"], ["nut2"]),
            cut("C2", "stock_out.lower2", 27.6225, "nut4_b", "nut3_b", ["nut4"], ["nut3"]),
        ],
    }
    plan["setups"][3]["hold"] = {
        "supports": [
            {
                "placement": "posed",
                "id": "balancer",
                "stock_ref": "stock_out.nut1_b",
                "pose": {"origin_mm": [0.0, 0.0, 0.0], "x": [1.0, 0.0, 0.0], "z": [0.0, 0.0, 1.0]},
                "note": "Borrow then return the already-produced first blank",
            }
        ]
    }
    for i in range(1, 5):
        plan["setups"].append(
            {
                "id": f"E{i}",
                "stock_in": f"stock_out.nut{i}_b",
                "ops": [
                    {
                        "op": 10,
                        "do": "inspect",
                        "feature": "face",
                        "workpiece_faces": {f"nut{i}": [FACE]},
                    }
                ],
            }
        )
    return plan


def test_nested_paths_keep_four_distinct_members_and_source_owners():
    plan = Plan.model_validate(batch()).model_dump(exclude_unset=True)
    graph = MaterialGraph(plan, validate=True)
    assert graph.members("P0") == {"nut1", "nut2", "nut3", "nut4"}
    assert graph.members("E4") == {"nut4"}
    assert graph.nodes["E4"][0].path == (
        Partition("C1a", "lower1"),
        Partition("C1b", "lower2"),
        Partition("C2", "nut4_b"),
    )
    descriptor = graph.descriptor("E4", OWNERS.finished_feature_owners)
    assert descriptor["partitions"] == [
        {
            "root": "stock",
            "path": [
                {"split": "C1a", "output": "lower1"},
                {"split": "C1b", "output": "lower2"},
                {"split": "C2", "output": "nut4_b"},
            ],
        }
    ]
    assert descriptor["workpieces"] == ["nut4"]
    assert descriptor["finished_solids"] is None
    assert descriptor["registrations"] == {"nut4": plan["workpieces"]["nut4"]}
    assert OWNERS.finished_feature_owners == {"face": "body", "unresolved": None}
    assert [setup["ops"][0]["workpiece_faces"] for setup in plan["setups"][-4:]] == [
        {f"nut{i}": [FACE]} for i in range(1, 5)
    ]


def test_first_differing_edge_proves_siblings_but_not_parent_aliases_disjoint():
    root = Material("stock")
    parent = Material("stock", (Partition("first", "lower"),))
    child = Material("stock", (*parent.path, Partition("second", "left")))
    sibling = Material("stock", (*parent.path, Partition("second", "right")))
    distant = Material("stock", (Partition("first", "upper"),))
    assert root.overlaps(child) and parent.overlaps(child) and child.overlaps(child)
    assert not child.overlaps(sibling) and not child.overlaps(distant)
    assert not Material("other", child.path).overlaps(child)
    assert child.overlaps(Material("stock", (*parent.path, Partition("alternative", "right"))))


def test_nested_coverage_needs_every_descendant_not_just_one_child():
    plan = batch()
    assert material_coverage_status(plan, ["E1", "E2", "E3", "E4"], "P0") is True
    assert material_coverage_status(plan, ["E1", "E2", "E3"], "P0") is False
    assert material_coverage_status(plan, ["E3", "E4"], "C2") is True
    assert material_coverage_status(plan, "E2", "E3") is False
    assert material_coverage_status(plan, "P0", "E4") is True


def test_member_queries_do_not_borrow_siblings_or_unknown_canonical_ownership():
    plan = batch()
    assert workpiece_status(plan, "E4", "nut4") is True
    assert workpiece_status(plan, "E4", "nut1") is False
    assert feature_branch_status(plan, "C2", "face", OWNERS) is None
    assert feature_branch_status(plan, "E4", ("nut4", "face"), OWNERS) is True
    assert feature_branch_status(plan, "E4", ("nut1", "face"), OWNERS) is False
    assert feature_material_status(plan, "E4", "P0", "face", OWNERS, workpiece_id="nut4") is True
    assert feature_material_status(plan, "E4", "P0", ("nut1", "face"), OWNERS) is False
    assert feature_material_status(plan, "E4", "P0", ("nut4", "unresolved"), OWNERS) is None
    plan["setups"][2]["ops"][0]["outputs"]["lower2"]["pose"] = "unknown"
    assert feature_material_status(plan, "E4", "P0", ("nut4", "face"), OWNERS) is None


@pytest.mark.parametrize(
    "case,reason",
    [
        ("duplicate_member", "every live workpiece exactly once"),
        ("missing_member", "every live workpiece exactly once"),
        ("unknown_member", "every live workpiece exactly once"),
        ("same_side", "distinct below/above"),
        ("child_reused", "already consumed"),
        ("parent_reused", "already consumed"),
        ("nested_parent_reused", "already consumed"),
        ("aliased_target", "alias the same target"),
        ("wrong_claim_member", "live carried members"),
        ("ambiguous_faces", "multi-workpiece faces"),
        ("missing_stock_in", "explicit scalar stock_in"),
    ],
)
def test_invalid_member_routes_are_rejected_before_native(case, reason):
    plan = batch()
    outputs = plan["setups"][1]["ops"][0]["outputs"]
    if case == "duplicate_member":
        outputs["lower1"]["carries_workpieces"].append("nut1")
    elif case == "missing_member":
        outputs["lower1"]["carries_workpieces"].remove("nut4")
    elif case == "unknown_member":
        outputs["nut1_b"]["carries_workpieces"] = ["missing"]
    elif case == "same_side":
        outputs["nut1_b"]["side"] = "below"
    elif case in {"child_reused", "parent_reused", "nested_parent_reused"}:
        incoming = {
            "child_reused": "stock_out.nut1_b",
            "parent_reused": "stock",
            "nested_parent_reused": "stock_out.lower1",
        }[case]
        plan["setups"].append({"id": "reuse", "stock_in": incoming})
    elif case == "aliased_target":
        plan["workpieces"]["nut2"]["pose"] = copy.deepcopy(plan["workpieces"]["nut1"]["pose"])
    elif case == "wrong_claim_member":
        plan["setups"][-1]["ops"][0]["workpiece_faces"] = {"nut1": [FACE]}
    elif case == "ambiguous_faces":
        plan["setups"][0]["ops"] = [{"op": 1, "do": "face", "feature": "face", "faces": [FACE]}]
    else:
        plan["setups"][-1].pop("stock_in")
    with pytest.raises(ValueError, match=reason):
        Plan.model_validate(plan)


def test_preexisting_alias_cannot_consume_nested_parent_again():
    plan = batch()
    plan["setups"].insert(2, {"id": "alias", "stock_in": "stock_out.lower1"})
    with pytest.raises(ValueError, match="already consumed"):
        Plan.model_validate(plan)


def test_borrowed_sibling_is_available_for_later_cutting_without_new_material():
    plan = Plan.model_validate(batch()).model_dump(exclude_unset=True)
    assert MaterialGraph(plan, validate=True).members("E1") == {"nut1"}
    assert len(plan["workpieces"]) == 4
    assert plan["setups"][3]["hold"]["supports"][0]["stock_ref"] == "stock_out.nut1_b"


@pytest.mark.parametrize(
    "case,reason",
    [
        ("raw", "available already-produced stock"),
        ("future", "available already-produced stock"),
        ("consumed", "available already-produced stock"),
        ("overlap", "overlap the cutting stock"),
        ("duplicate_id", "support ids must be unique"),
    ],
)
def test_borrowed_support_references_are_not_material_consumption(case, reason):
    plan = batch()
    support = plan["setups"][3]["hold"]["supports"][0]
    if case == "duplicate_id":
        plan["setups"][3]["hold"]["supports"].append(copy.deepcopy(support))
    else:
        support["stock_ref"] = {
            "raw": "stock",
            "future": "E1",
            "consumed": "stock_out.lower1",
            "overlap": "stock_out.lower2",
        }[case]
    with pytest.raises(ValueError, match=reason):
        Plan.model_validate(plan)


@pytest.mark.parametrize("mutation", ["both", "neither", "blank_id", "unknown_source"])
def test_placed_support_tag_has_one_known_source(mutation):
    entry = copy.deepcopy(batch()["setups"][3]["hold"]["supports"][0])
    if mutation == "both":
        entry["ref"] = "fixtures.block"
    elif mutation == "neither":
        entry.pop("stock_ref")
    elif mutation == "blank_id":
        entry["id"] = " "
    else:
        entry["stock_ref"] = "unknown"
    with pytest.raises(ValueError):
        PlacedSupport.model_validate(entry)


def test_legacy_untagged_supports_still_parse_without_placement():
    hold = Hold.model_validate({"supports": ["rest", {"ref": "rest", "orientation": "upright"}]})
    assert hold.model_dump(exclude_unset=True) == {
        "supports": ["rest", {"ref": "rest", "orientation": "upright"}]
    }


def test_qualified_face_maps_are_exclusive_nonempty_and_distinct():
    for patch in (
        {"faces": [FACE]},
        {"workpiece_faces": {"nut4": []}},
        {"workpiece_faces": {"nut4": [FACE, FACE]}},
        {"workpiece_faces": {}},
    ):
        plan = batch()
        plan["setups"][-1]["ops"][0].update(patch)
        with pytest.raises(ValueError):
            Plan.model_validate(plan)


@pytest.mark.parametrize(
    "case",
    [
        "empty_members",
        "duplicate_members",
        "mixed_selectors",
        "missing_side",
        "missing_member_cite",
        "missing_member_pose",
        "blank_member",
        "unknown_member_pose",
    ],
)
def test_batch_registration_and_output_schema_preserve_required_facts(case):
    plan = batch()
    entry = plan["setups"][1]["ops"][0]["outputs"]["nut1_b"]
    if case == "empty_members":
        entry["carries_workpieces"] = []
    elif case == "duplicate_members":
        entry["carries_workpieces"] = ["nut1", "nut1"]
    elif case == "mixed_selectors":
        entry["carries"] = "face"
    elif case == "missing_side":
        entry.pop("side")
    elif case == "missing_member_cite":
        plan["workpieces"]["nut1"]["cite"] = "unknown"
    elif case == "missing_member_pose":
        plan["workpieces"]["nut1"].pop("pose")
    elif case == "blank_member":
        plan["workpieces"][" "] = plan["workpieces"].pop("nut1")
    else:
        plan["workpieces"]["nut1"]["pose"] = "unknown"
        validated = Plan.model_validate(plan).model_dump(exclude_unset=True)
        assert feature_branch_status(validated, "E1", ("nut1", "face"), OWNERS) is None
        return
    with pytest.raises(ValueError):
        Plan.model_validate(plan)


@pytest.mark.parametrize("field", ["approach_mm", "retract_clearance_mm"])
@pytest.mark.parametrize("value", [0.0, -1.0])
def test_requested_pickup_distances_are_positive(field, value):
    with pytest.raises(ValueError):
        AxisZero.model_validate({"at_mm": [10.541, -2.54], field: value})


def test_pickup_fields_and_measured_tip_length_preserve_authored_presence():
    recipe = {"at_mm": [10.541, -2.54], "approach_mm": 2.54, "retract_clearance_mm": 12.7}
    assert AxisZero.model_validate(recipe).model_dump(exclude_unset=True) == recipe
    assert "at_mm" not in AxisZero.model_validate({"edge_mm": 0.0}).model_dump(exclude_unset=True)
    measurement = {
        "value": 6.35,
        "measured": {
            "status": "measured",
            "by": "host fixture",
            "date": "2026-10-19",
            "instrument": "synthetic caliper record",
        },
        "verify": False,
    }
    # Fact-local provenance survives schema loading, independently of tool identity.
    item = Inventory.model_validate({"tools": {"finder": {"finder_tip_length_mm": measurement}}})
    assert (
        item.model_dump(exclude_unset=True)["tools"]["finder"]["finder_tip_length_mm"]
        == measurement
    )
    with pytest.raises(ValueError, match="finder_tip_length"):
        Inventory.model_validate(
            {"tools": {"finder": {"finder_tip_length_mm": 6.35, "finder_tip_length_in": 0.25}}}
        )


REGISTERED = (
    "[workpieces.nut1]\n"
    "pose = { origin = [1.0, 0.0, 0.0], x = [1.0, 0.0, 0.0], y = [0.0, 1.0, 0.0], "
    'z = [0.0, 0.0, 1.0], binding = "Synthetic registration", cite = "Host fixture" }\n'
    'cite = "Host fixture"\n'
)
FEATURES = f'''part = "scratch"
step = "source.STEP"
frames = "unknown"
[solids]
body = "{SOLIDS["body"]}"
cap = "{SOLIDS["cap"]}"
[features.subject]
kind = "face"
requirements = []
faces = ["{FACE}"]
'''


def loader_plan(face=FACE):
    return (
        PLAN.replace("[[setups]]", REGISTERED + "[[setups]]").replace(
            'id = "S1"', 'id = "S1"\nstock_in = "stock"'
        )
        + f'workpiece_faces = {{ nut1 = ["{face}"] }}\n'
    )


def test_loader_preserves_canonical_source_and_instance_ownership_separately(tmp_path):
    path = bundle_files(tmp_path, loader_plan(), FEATURES)
    source = tmp_path / "source.STEP"
    source.write_text(STEP, encoding="ascii")
    original = source.read_bytes()
    bundle = load_bundle(path)
    assert bundle.finished_feature_owners == {"subject": "body"}
    assert bundle.workpiece_registrations["nut1"]["pose"]["origin"] == [1.0, 0.0, 0.0]
    assert bundle.features["features"]["subject"]["faces"] == [FACE]
    assert source.read_bytes() == original


@pytest.mark.parametrize(
    "face", ["#1/ADVANCED_FACE[2]/body", "#1/ADVANCED_FACE[1]/cap", "nut2:#1/ADVANCED_FACE[1]/body"]
)
def test_loader_rejects_wrong_qualified_canonical_face_references(tmp_path, face):
    path = bundle_files(tmp_path, loader_plan(face), FEATURES)
    (tmp_path / "source.STEP").write_text(STEP, encoding="ascii")
    with pytest.raises(BadInput, match="qualified workpiece faces"):
        load_bundle(path)


def test_unknown_placed_inventory_reference_is_load_error_not_empty_fixture():
    plan = {
        "setups": [
            {
                "id": "S",
                "hold": {
                    "supports": [{"placement": "posed", "id": "block", "ref": "fixtures.missing"}]
                },
            }
        ]
    }
    with pytest.raises(BadInput, match="inventory fixture or workholding"):
        _placed_supports(plan, {"fixtures": {}})


def test_unknown_inventory_category_preserves_placed_support_debt():
    plan = {
        "setups": [
            {
                "id": "S",
                "hold": {
                    "supports": [
                        {"placement": "posed", "id": "block", "ref": "fixtures.unresolved"}
                    ]
                },
            }
        ]
    }
    _placed_supports(plan, {"fixtures": "unknown"})
