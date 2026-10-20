"""Retained pieces keep physical identity without inventing independent supplies."""

import copy
from types import SimpleNamespace

import pytest
from test_input_contracts import PLAN, bundle_files

from prechips.inputs import BadInput, _finished_feature_owners, load_bundle
from prechips.kernel import _retained_output_inputs, engine_job, op_inputs
from prechips.material_routes import (
    MaterialGraph,
    feature_branch_status,
    feature_material_status,
    material_coverage_status,
    producer_setup,
    reference_frame,
)
from prechips.model import Features, Plan, setup_lineage, stock_ancestry
from prechips.rules.coordinates import frame_point

STEP = """ISO-10303-21;
HEADER;
FILE_DESCRIPTION(('host topology fixture; not native geometry'),'2;1');
ENDSEC;
DATA;
#1 = ADVANCED_FACE('body',(),#90,.T.);
#2 = ADVANCED_FACE('cap',(),#90,.F.);
#10 = CLOSED_SHELL('',(#1));
#11 = CLOSED_SHELL('',(#2));
#20 = MANIFOLD_SOLID_BREP('body',#10);
#21 = MANIFOLD_SOLID_BREP('cap',#11);
#90 = PLANE('',#91);
ENDSEC;
END-ISO-10303-21;
"""
SOLIDS = {
    "body": "#20/MANIFOLD_SOLID_BREP[1]/body",
    "cap": "#21/MANIFOLD_SOLID_BREP[2]/cap",
}
OWNERS = SimpleNamespace(finished_feature_owners={"body-thread": "body", "cap-thread": "cap"})


def output(carries):
    return {
        "carries": carries,
        "pose": "unknown",
        "cite": "Authored nominal route; pose unmeasured",
    }


def route():
    return {
        "part": "retained-route",
        "features": "features.toml",
        "setups": [
            {
                "id": "P1",
                "stock_in": "stock",
                "ops": [{"op": 20, "do": "spot", "feature": "centre"}],
            },
            {
                "id": "P3",
                "stock_in": "P1",
                "ops": [
                    {
                        "op": 10,
                        "do": "part_off",
                        "feature": "body-thread",
                        "outputs": {
                            "tube_blank": output("body-thread"),
                            "bar_remnant": output("cap-thread"),
                        },
                    }
                ],
            },
            {
                "id": "C1",
                "stock_in": "stock_out.bar_remnant",
                "ops": [
                    {
                        "op": 10,
                        "do": "part_off",
                        "feature": "cap-thread",
                        "keep": "cap-thread",
                    }
                ],
            },
            {
                "id": "T2",
                "stock_in": "stock_out.tube_blank",
                "ops": [{"op": 10, "do": "tap", "feature": "body-thread"}],
            },
            {
                "id": "A1",
                "stock_in": ["C1", "T2"],
                "joint": {
                    "kind": "threaded",
                    "socket": "body-thread",
                    "spigot": "cap-thread",
                    "process": "Hand screw together",
                    "cite": "Source assembly",
                    "engagement_mm": "unknown",
                    "seat": "unknown",
                },
                "ops": [{"op": 10, "do": "finish_turn", "feature": "body-thread"}],
            },
        ],
    }


def test_same_bar_siblings_route_to_one_threaded_assembly_without_new_supplies():
    plan = Plan.model_validate(route()).model_dump(exclude_unset=True)
    graph = MaterialGraph(plan, validate=True)
    assert graph.roots("A1") == {"stock"}
    assert graph.descriptor("P3", OWNERS.finished_feature_owners)["finished_solids"] is None
    assert graph.descriptor("C1", OWNERS.finished_feature_owners) == {
        "roots": ["stock"],
        "partitions": [{"root": "stock", "path": [{"split": "P3", "output": "bar_remnant"}]}],
        "finished_solids": ["cap"],
        "workpieces": None,
        "registrations": None,
    }
    assert graph.descriptor("A1", OWNERS.finished_feature_owners)["finished_solids"] == [
        "body",
        "cap",
    ]
    assert producer_setup(plan, "stock_out.tube_blank") == "P3"
    assert setup_lineage(plan, "T2") == {"P1", "P3", "T2"}
    assert stock_ancestry(plan)["stock_out.bar_remnant"] == {"stock"}
    assert "components" not in plan.get("stock", {})


@pytest.mark.parametrize(
    "case, reason",
    [
        ("duplicate", "already consumed"),
        ("ancestor", "already consumed"),
        ("parent_child", "already consumed"),
        ("split_id", "partitioned setup"),
        ("nested", "already partitioned"),
        ("invalid", "unknown stock reference"),
        ("reserved", "reserved stock namespace"),
        ("duplicate_names", "globally unique"),
    ],
)
def test_duplicate_or_unproven_material_is_rejected_statically(case, reason):
    plan = route()
    if case == "duplicate":
        plan["setups"].insert(4, {"id": "duplicate", "stock_in": "stock_out.tube_blank"})
    elif case == "ancestor":
        plan["setups"].insert(4, {"id": "ancestor", "stock_in": "P1"})
    elif case == "parent_child":
        plan["setups"][-1]["stock_in"] = ["P1", "C1"]
    elif case == "split_id":
        plan["setups"][2]["stock_in"] = "P3"
    elif case == "nested":
        plan["setups"][2]["ops"][0].pop("keep")
        plan["setups"][2]["ops"][0]["outputs"] = {
            "next_cap": output("cap-thread"),
            "scrap": output("body-thread"),
        }
    elif case == "invalid":
        plan["setups"][2]["stock_in"] = "stock_out.missing"
    elif case == "reserved":
        plan["setups"][0]["id"] = "stock_out.ambiguous"
    else:
        plan["setups"][2]["ops"][0].pop("keep")
        plan["setups"][2]["ops"][0]["outputs"] = copy.deepcopy(
            plan["setups"][1]["ops"][0]["outputs"]
        )
    with pytest.raises(ValueError, match=reason):
        Plan.model_validate(plan)


@pytest.mark.parametrize(
    "case, reason",
    [
        ("not_part_off", "only part_off"),
        ("one_output", "exactly two"),
        ("keep", "exclusive"),
        ("later_keep", "keep cannot follow"),
        ("uncited", "must cite"),
        ("blank_name", "known and non-empty"),
        ("unknown_selector", "known and non-empty"),
    ],
)
def test_output_schema_requires_real_two_piece_cited_split(case, reason):
    plan = route()
    op = plan["setups"][1]["ops"][0]
    if case == "not_part_off":
        op["do"] = "finish_turn"
    elif case == "one_output":
        op["outputs"].pop("bar_remnant")
    elif case == "keep":
        op["keep"] = "body-thread"
    elif case == "later_keep":
        plan["setups"][1]["ops"].append(
            {
                "op": 20,
                "do": "inspect",
                "feature": "body-thread",
                "keep": "body-thread",
            }
        )
    elif case == "uncited":
        op["outputs"]["tube_blank"]["cite"] = "unknown"
    elif case == "blank_name":
        op["outputs"][" "] = op["outputs"].pop("tube_blank")
    else:
        op["outputs"]["tube_blank"]["carries"] = "unknown"
    with pytest.raises(ValueError, match=reason):
        Plan.model_validate(plan)


def test_transient_centre_cannot_leak_from_parent_to_unknown_child():
    plan = route()
    assert feature_material_status(plan, "P3", "P1", "centre", OWNERS) is True
    assert feature_material_status(plan, "T2", "P1", "centre", OWNERS) is None
    assert feature_material_status(plan, "C1", "P1", "centre", OWNERS) is None
    assert feature_material_status(plan, "T2", "P1", "body-thread", OWNERS) is None
    assert feature_material_status(plan, "T2", "P1", "cap-thread", OWNERS) is False
    assert feature_branch_status(plan, "C1", "body-thread", OWNERS) is False
    assert feature_material_status(plan, "A1", "C1", "body-thread", OWNERS) is False
    assert feature_material_status(plan, "T2", "P1", "body-thread", {}) is None
    assert feature_branch_status(plan, "T2", "body-thread", {}) is None
    plan["setups"][1]["ops"][0]["outputs"]["tube_blank"]["pose"] = {
        "origin": [0, 0, 0],
        "x": [1, 0, 0],
        "y": [0, 1, 0],
        "z": [0, 0, 1],
        "binding": "Authored nominal registration",
        "cite": "Synthetic registration fixture, not a shop measurement",
    }
    assert feature_material_status(plan, "T2", "P1", "body-thread", OWNERS) is True
    assert feature_material_status(plan, "T2", "P1", "centre", OWNERS) is None


def test_one_child_coating_does_not_cover_unsplit_parent_or_sibling():
    plan = route()
    assert material_coverage_status(plan, "C1", "P3") is False
    assert material_coverage_status(plan, "C1", "T2") is False
    assert material_coverage_status(plan, ["C1", "T2"], "P3") is True
    assert material_coverage_status(plan, "P1", "T2") is True


def manifest():
    return {
        "part": "scratch",
        "units": "mm",
        "frames": "unknown",
        "solids": dict(SOLIDS),
        "features": {
            "body-thread": {
                "kind": "threaded_hole",
                "faces": ["#1/ADVANCED_FACE[1]/body"],
                "requirements": [],
            },
            "cap-thread": {
                "kind": "external_thread",
                "faces": ["#2/ADVANCED_FACE[2]/cap"],
                "requirements": [],
            },
            "mixed": {
                "kind": "face",
                "faces": ["#1/ADVANCED_FACE[1]/body", "#2/ADVANCED_FACE[2]/cap"],
                "requirements": [],
            },
        },
    }


def test_finished_solid_binding_uses_exact_source_topology_not_face_order(tmp_path):
    path = tmp_path / "source.STEP"
    path.write_text(STEP, encoding="ascii")
    features = manifest()
    owners = _finished_feature_owners(features, path)
    assert owners == {"body-thread": "body", "cap-thread": "cap", "mixed": None}
    features["features"]["body-thread"]["faces"] = ["#2/ADVANCED_FACE[2]/cap"]
    assert _finished_feature_owners(features, path)["body-thread"] == "cap"


@pytest.mark.parametrize(
    "case",
    ["missing_solid", "wrong_entity", "wrong_ordinal", "wrong_label", "wrong_face", "no_source"],
)
def test_finished_solid_map_is_source_owned_and_complete(tmp_path, case):
    path = tmp_path / "source.STEP"
    path.write_text(STEP, encoding="ascii")
    features = manifest()
    if case == "missing_solid":
        features["solids"].pop("cap")
    elif case == "wrong_entity":
        features["solids"]["body"] = "#10/MANIFOLD_SOLID_BREP[1]/body"
    elif case == "wrong_ordinal":
        features["solids"]["body"] = "#20/MANIFOLD_SOLID_BREP[2]/body"
    elif case == "wrong_label":
        features["solids"]["body"] = "#20/MANIFOLD_SOLID_BREP[1]/cap"
    elif case == "wrong_face":
        features["features"]["body-thread"]["faces"] = ["#1/ADVANCED_FACE[2]/body"]
    else:
        path = None
    with pytest.raises(BadInput):
        _finished_feature_owners(features, path)


def test_duplicate_solid_refs_rejected_by_manifest_schema():
    features = manifest()
    features["solids"]["cap"] = features["solids"]["body"]
    with pytest.raises(ValueError, match="bijective"):
        Features.model_validate(features)


def test_loader_validates_solid_map_before_any_kernel(tmp_path):
    features = """part = "scratch"
step = "source.STEP"
frames = "unknown"
[solids]
body = "#20/MANIFOLD_SOLID_BREP[1]/body"
[features.subject]
kind = "face"
requirements = []
faces = ["#1/ADVANCED_FACE[1]/body"]
"""
    path = bundle_files(tmp_path, PLAN, features)
    (tmp_path / "source.STEP").write_text(STEP, encoding="ascii")
    with pytest.raises(BadInput, match="bijectively"):
        load_bundle(path)


def test_retained_pose_translation_converts_plan_units_only_once():
    pose = {
        "origin": [1, 2, 3],
        "x": [0, 0, 1],
        "y": [0, 1, 0],
        "z": [-1, 0, 0],
        "binding": "Authored nominal registration",
        "cite": "Source pose",
    }
    original = copy.deepcopy(pose)
    entries = {"piece": {**output("body-thread"), "pose": pose}}
    result = _retained_output_inputs(entries, "in")["piece"]["pose"]
    assert result["origin"] == pytest.approx([25.4, 50.8, 76.2])
    assert [result[key] for key in ("x", "y", "z")] == [
        [0, 0, 1],
        [0, 1, 0],
        [-1, 0, 0],
    ]
    assert pose == original
    pose["binding"] = "unknown"
    assert _retained_output_inputs(entries, "in")["piece"]["pose"] == "unknown"


def test_raw_supply_can_seed_alternative_roots_but_not_an_overlapping_join():
    plan = route()
    plan["setups"].append({"id": "alternative", "stock_in": "stock"})
    Plan.model_validate(plan)
    plan["setups"][-1].update(
        stock_in=["stock", "A1"], joint=copy.deepcopy(plan["setups"][4]["joint"])
    )
    with pytest.raises(ValueError, match="shares ancestor 'stock'"):
        Plan.model_validate(plan)


@pytest.mark.parametrize("action", ["die_thread", "hand_tap"])
def test_manual_thread_recipe_never_asks_for_a_powered_toolpost_or_spindle(action):
    bundle = SimpleNamespace()
    result = op_inputs(
        bundle,
        {"id": "cap"},
        {"op": 10, "do": action, "feature": "cap-thread", "tool": "thread-tool"},
        finishing={"cap:10"},
    )
    assert result["do"] == action and result["finishing"] is True
    assert result["feature"] == "cap-thread"
    assert "unmodeled" in result["manual_thread"]["reason"]
    assert not ({"radius_mm", "projection_mm", "rpm", "joint_cut"} & result.keys())
    assert result["measurement_debts"] == []


@pytest.mark.parametrize(
    "case, reason",
    [
        ("not_exported", "exported finished feature"),
        ("same_solid", "distinct finished solids"),
        ("mixed_selector", "exactly one named finished solid"),
        ("no_solid_map", "require features.solids"),
    ],
)
def test_loader_rejects_invalid_finished_material_selectors(tmp_path, case, reason):
    selected = "missing" if case == "not_exported" else "other"
    plan = (
        PLAN.replace('do = "inspect"', 'do = "part_off"')
        + f'''
[setups.ops.outputs.first]
carries = "subject"
pose = "unknown"
cite = "Authored route; no physical registration measured"
[setups.ops.outputs.second]
carries = "{selected}"
pose = "unknown"
cite = "Authored route; no physical registration measured"
'''
    )
    second_faces = '["#2/ADVANCED_FACE[2]/cap"]'
    if case == "same_solid":
        second_faces = '["#1/ADVANCED_FACE[1]/body"]'
    elif case == "mixed_selector":
        second_faces = '["#1/ADVANCED_FACE[1]/body", "#2/ADVANCED_FACE[2]/cap"]'
    declarations = (
        ""
        if case == "no_solid_map"
        else """
[solids]
body = "#20/MANIFOLD_SOLID_BREP[1]/body"
cap = "#21/MANIFOLD_SOLID_BREP[2]/cap"
"""
    )
    features = f"""part = "scratch"
step = "source.STEP"
frames = "unknown"
{declarations}
[features.subject]
kind = "face"
requirements = []
faces = ["#1/ADVANCED_FACE[1]/body"]
[features.other]
kind = "face"
requirements = []
faces = {second_faces}
"""
    path = bundle_files(tmp_path, plan, features)
    (tmp_path / "source.STEP").write_text(STEP, encoding="ascii")
    with pytest.raises(BadInput, match=reason):
        load_bundle(path)


@pytest.mark.parametrize("units, scale", [("mm", 1.0), ("in", 25.4)])
def test_registered_basis_applies_inverse_pose_to_model_point_readings(units, scale):
    plan = route()
    pose = {
        "origin": [10, 20, 30],
        "x": [0, 1, 0],
        "y": [-1, 0, 0],
        "z": [0, 0, 1],
        "binding": "Authored nominal registration",
        "cite": "Synthetic rotation and translation oracle, not a shop measurement",
    }
    outputs = plan["setups"][1]["ops"][0]["outputs"]
    outputs["tube_blank"]["pose"] = pose
    producer = {
        "origin": [1, 2, 3],
        "x": [0, 1, 0],
        "y": [-1, 0, 0],
        "z": [0, 0, 1],
    }
    registered = reference_frame(plan, "stock_out.tube_blank", producer)
    assert registered == {
        "origin": [8, 21, 33],
        "x": [-1, 0, 0],
        "y": [0, -1, 0],
        "z": [0, 0, 1],
    }
    # Old p=[4,6,8] has producer readings [4,-3,5]; direct P maps p to q=[4,24,38].
    # Reading q through the registered basis MUST still give those old readings.
    assert frame_point([4, 24, 38], registered) == [4, -3, 5]
    assert frame_point([4, 24, 38], producer) == [22, -3, 35]
    normalized_pose = _retained_output_inputs(outputs, units)["tube_blank"]["pose"]
    assert normalized_pose["origin"] == pytest.approx([10 * scale, 20 * scale, 30 * scale])
    assert [normalized_pose[key] for key in ("x", "y", "z")] == [
        [0, 1, 0],
        [-1, 0, 0],
        [0, 0, 1],
    ]
    metric_frame = {
        **registered,
        "origin": [value * scale for value in registered["origin"]],
    }
    assert frame_point([4 * scale, 24 * scale, 38 * scale], metric_frame) == pytest.approx(
        [4 * scale, -3 * scale, 5 * scale]
    )


def test_actual_native_projection_preserves_partition_and_manual_thread_contracts():
    job = {
        "version": 1,
        "step_path": "source.STEP",
        "step_sha256": "unknown",
        "features": {"body-thread": ["#1/ADVANCED_FACE[1]/body"]},
        "finished_solids": dict(SOLIDS),
        "feature_solids": {"body-thread": "body", "cap-thread": "cap"},
        "as_is_faces": "unknown",
        "stock": {"reason": "physical source dimensions unknown"},
        "setups": [
            {
                "id": "P3",
                "frame": "unknown",
                "hold": {"kind": "unknown"},
                "stock_in": "stock",
                "material": {"roots": ["stock"], "partitions": [], "finished_solids": None},
                "machine_kind": "lathe",
                "locate_revolved": [],
                "ops": [
                    {
                        "subject": "P3:10",
                        "do": "part_off",
                        "outputs": {
                            "tube_blank": output("body-thread"),
                            "bar_remnant": output("cap-thread"),
                        },
                    },
                    {
                        "subject": "P3:20",
                        "do": "hand_tap",
                        "manual_thread": {"reason": "helical thread removal unmodeled"},
                    },
                ],
            }
        ],
    }
    projected = engine_job(job)
    assert projected["finished_solids"] == {
        "body": "#20/MANIFOLD_SOLID_BREP[1]/body",
        "cap": "#21/MANIFOLD_SOLID_BREP[2]/cap",
    }
    assert projected["feature_solids"] == {"body-thread": "body", "cap-thread": "cap"}
    setup = projected["setups"][0]
    assert setup["material"] == {
        "roots": ["stock"],
        "partitions": [],
        "finished_solids": None,
    }
    assert setup["ops"][0]["outputs"]["tube_blank"]["carries"] == "body-thread"
    assert setup["ops"][0]["outputs"]["bar_remnant"]["pose"] == "unknown"
    assert setup["ops"][1]["manual_thread"]["reason"] == "helical thread removal unmodeled"
    job["setups"][0]["ops"][0]["outputs"]["tube_blank"]["pose"] = {
        "origin": [1, 2, 3],
        "x": [1, 0, 0],
        "y": [0, 1, 0],
        "z": [0, 0, 1],
    }
    assert engine_job(job)["setups"][0]["ops"][0]["outputs"]["tube_blank"]["pose"]["origin"] == [
        1,
        2,
        3,
    ]


@pytest.mark.parametrize(
    "action",
    [
        "face",
        "drill",
        "die_thread",
        "hand_tap",
        "file_to_line",
        "fit",
        "unknown",
        "unregistered_cut",
    ],
)
def test_named_outputs_cannot_snapshot_before_a_later_material_change(action):
    plan = route()
    plan["setups"][1]["ops"].append(
        {
            "op": 20,
            "do": action,
            "feature": "body-thread",
        }
    )
    with pytest.raises(ValueError, match="final material-changing operation"):
        Plan.model_validate(plan)


@pytest.mark.parametrize("action", ["inspect", "deburr", "coating", "release", "scribe"])
def test_named_outputs_allow_existing_nonstockgeometry_process_followups(action):
    plan = route()
    plan["setups"][1]["ops"].append(
        {
            "op": 20,
            "do": action,
            "feature": "body-thread",
        }
    )
    validated = Plan.model_validate(plan).model_dump(exclude_unset=True)
    assert validated["setups"][1]["ops"][-1]["do"] == action
    assert MaterialGraph(validated, validate=True).roots("A1") == {"stock"}


@pytest.mark.parametrize(
    "setups",
    [
        [{}],
        [{}, {}],
        [{"id": "unknown"}],
        [{"id": ""}],
        [{"id": " "}],
    ],
)
def test_missing_setup_identity_is_structured_input_failure_not_an_anonymous_root(setups):
    plan = {"part": "identity-test", "features": "features.toml", "setups": setups}
    with pytest.raises(ValueError, match="Setup ids must be known and non-empty"):
        Plan.model_validate(plan)
    with pytest.raises(ValueError, match="Setup ids must be known and non-empty"):
        MaterialGraph(plan, validate=True)
    with pytest.raises(ValueError, match="Setup ids must be known and non-empty"):
        setup_lineage(plan, "unknown")


def test_missing_setup_id_reaches_loaders_bad_input_contract(tmp_path):
    path = bundle_files(tmp_path, PLAN.replace('id = "S1"\n', ""))
    with pytest.raises(BadInput, match="Setup ids must be known and non-empty"):
        load_bundle(path)


def test_ordinary_setup_states_allow_fan_out_and_selected_ancestor_rework():
    plan = {
        "part": "ordinary-state-routing",
        "features": "features.toml",
        "setups": [
            {"id": "S1", "stock_in": "stock"},
            {"id": "S2", "stock_in": "S1"},
            {"id": "S3", "stock_in": "S1"},
            {"id": "S4", "stock_in": "S2"},
        ],
    }
    validated = Plan.model_validate(plan).model_dump(exclude_unset=True)
    graph = MaterialGraph(validated, validate=True)
    assert graph.roots("S3") == {"stock"}
    assert setup_lineage(validated, "S3") == {"S1", "S3"}
    assert setup_lineage(validated, "S4") == {"S1", "S2", "S4"}
    # Alternative process states are not two disjoint pieces to assemble together.
    plan["setups"].append(
        {
            "id": "invalid_join",
            "stock_in": ["S2", "S3"],
            "joint": copy.deepcopy(route()["setups"][-1]["joint"]),
        }
    )
    with pytest.raises(ValueError, match="shares ancestor"):
        Plan.model_validate(plan)


def test_named_partition_does_not_make_unrelated_ordinary_setup_states_single_use():
    plan = route()
    plan["stock"] = {"components": [{"id": "bar"}, {"id": "plate"}]}
    plan["setups"][0]["stock_in"] = "stock.bar"
    plan["setups"].extend(
        [
            {"id": "plate_start", "stock_in": "stock.plate"},
            {"id": "plate_second", "stock_in": "plate_start"},
            {"id": "plate_rework", "stock_in": "plate_start"},
        ]
    )
    graph = MaterialGraph(Plan.model_validate(plan).model_dump(exclude_unset=True), validate=True)
    assert graph.roots("A1") == {"stock.bar"}
    assert graph.roots("plate_second") == graph.roots("plate_rework") == {"stock.plate"}
    assert all(not atom.path for atom in graph.nodes["plate_rework"])


def test_unsplit_predecessor_of_named_partition_is_still_exclusive():
    plan = route()
    plan["setups"].insert(1, {"id": "other_use", "stock_in": "P1"})
    with pytest.raises(ValueError, match="already consumed"):
        Plan.model_validate(plan)


@pytest.mark.parametrize("identity", [None, "", "unknown"])
def test_rendering_route_precondition_never_relaxes_strict_identity_validation(identity):
    from prechips.material_routes import route_identities_known

    plan = route()
    Plan.model_validate(plan)
    assert route_identities_known(plan, "T2")
    plan["setups"][2]["id"] = identity
    assert not route_identities_known(plan, "T2")
    assert not route_identities_known(plan, identity)
    with pytest.raises(ValueError):
        Plan.model_validate(plan)
    # The sole mutation is this setup's identity, not a different route violation.
    plan["setups"][2]["id"] = "C1"
    Plan.model_validate(plan)
