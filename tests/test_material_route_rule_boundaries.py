"""Host consumers distinguish producer history from retained material membership."""

from copy import deepcopy
from types import SimpleNamespace

import pytest

from prechips.rules import (
    finish_route,
    geometry_common,
    hold_fields,
    manual_arc,
    op_order,
    prepared_blank,
    saw_cut,
    tip_endpoints,
    tooling_hole,
    turned_profile,
)
from prechips.rules.zero_recipe import faces, native, touch


FRAME = {
    "origin": [0, 0, 0],
    "x": [1, 0, 0],
    "y": [0, 1, 0],
    "z": [0, 0, 1],
}
POSE = {
    **FRAME,
    "binding": "Authored nominal registration",
    "cite": "Retained-material route fixture",
}


def routed_bundle(*, owner=None, action="face"):
    root = {
        "id": "BASE",
        "stock_in": "stock",
        "frame": "F",
        "ops": [{"op": 10, "do": action, "feature": "land", "to_z": 0}],
    }
    split = {
        "id": "SPLIT",
        "stock_in": "BASE",
        "frame": "F",
        "ops": [
            {
                "op": 20,
                "do": "part_off",
                "feature": "cut",
                "outputs": {
                    "left": {"carries": "left_body", "pose": deepcopy(POSE)},
                    "right": {"carries": "right_body", "pose": deepcopy(POSE)},
                },
            }
        ],
    }
    left = {"id": "LEFT", "stock_in": "stock_out.left", "frame": "F", "ops": []}
    right = {"id": "RIGHT", "stock_in": "stock_out.right", "frame": "F", "ops": []}
    plan = {
        "part": "two-parts",
        "stock": {"as_is_faces": []},
        "setups": [root, split, left, right],
    }
    return SimpleNamespace(
        plan=plan,
        features={"units": "mm", "material": {"finish": "oxide"}},
        feature_definitions={
            "land": {"kind": "face", "faces": ["F-land"], "bounds": {"x": [0, 1], "y": [0, 1]}},
            "left_body": {"kind": "cylinder"},
            "right_body": {"kind": "cylinder"},
        },
        finished_feature_owners={
            "left_body": "source:left-solid",
            "right_body": "source:right-solid",
            "land": owner,
        },
        kernel={},
    )


def setup(bundle, sid):
    return next(row for row in bundle.plan["setups"] if row["id"] == sid)


def coat(bundle, sid):
    setup(bundle, sid)["ops"].append({"op": 90, "do": "coating", "feature": "land"})


@pytest.mark.parametrize("coatings, expected", [(["LEFT"], "warn"), (["LEFT", "RIGHT"], "pass")])
def test_child_coating_covers_only_its_partition(coatings, expected):
    bundle = routed_bundle()
    for sid in coatings:
        coat(bundle, sid)
    (finding,) = finish_route.evaluate(bundle)
    assert finding.status == expected
    if expected == "warn":
        assert finding.numbers["uncoated_cuts"] == ["BASE:10", "SPLIT:20"]


def test_parent_coating_is_not_lost_when_both_children_are_retained():
    bundle = routed_bundle()
    coat(bundle, "SPLIT")
    (finding,) = finish_route.evaluate(bundle)
    assert finding.status == "pass"


def test_child_cut_still_needs_coating_after_parent_coating():
    bundle = routed_bundle()
    coat(bundle, "SPLIT")
    setup(bundle, "LEFT")["ops"] = [{"op": 30, "do": "face", "feature": "land"}]
    (finding,) = finish_route.evaluate(bundle)
    assert finding.status == "warn"
    assert finding.numbers["uncoated_cuts"] == ["LEFT:30"]


def test_monolithic_finish_route_keeps_known_missing_and_unknown_routing_distinct():
    bundle = routed_bundle()
    bundle.plan["setups"] = [setup(bundle, "BASE"), setup(bundle, "LEFT")]
    setup(bundle, "LEFT")["stock_in"] = "BASE"
    coat(bundle, "LEFT")
    assert finish_route.evaluate(bundle)[0].status == "pass"
    del setup(bundle, "LEFT")["stock_in"]
    assert finish_route.evaluate(bundle)[0].status == "unknown"
    setup(bundle, "LEFT")["stock_in"] = "BASE"
    setup(bundle, "BASE")["ops"].append({"op": 95, "do": "face", "feature": "land"})
    setup(bundle, "LEFT")["ops"] = []
    coat(bundle, "BASE")
    setup(bundle, "BASE")["ops"].append({"op": 100, "do": "face", "feature": "land"})
    assert finish_route.evaluate(bundle)[0].numbers["uncoated_cuts"] == ["BASE:100"]


@pytest.mark.parametrize("owner, expected", [(None, "unknown"), ("source:left-solid", "pass"), ("source:right-solid", "error")])
def test_stop_face_needs_material_membership_not_just_history(owner, expected):
    bundle = routed_bundle(owner=owner)
    status, facts = hold_fields.stop_face(bundle, setup(bundle, "LEFT"), "land")
    assert status == expected
    assert facts["cut_before"] == (["BASE op 10"] if expected == "pass" else [])
    assert facts["on_arriving_stock"] == {"pass": True, "error": False, "unknown": "unknown"}[expected]


@pytest.mark.parametrize("owner, expected", [(None, "unknown"), ("source:left-solid", "pass"), ("source:right-solid", "error")])
def test_as_is_stop_face_cannot_bypass_partition_ownership(owner, expected):
    bundle = routed_bundle(owner=owner)
    setup(bundle, "BASE")["ops"] = []
    bundle.plan["stock"]["as_is_faces"] = ["F-land"]
    assert hold_fields.stop_face(bundle, setup(bundle, "LEFT"), "land")[0] == expected


@pytest.mark.parametrize("owner, expected", [(None, "unknown"), ("source:left-solid", "pass"), ("source:right-solid", "error")])
def test_x_zero_credit_distinguishes_transient_and_owned_turned_land(owner, expected):
    bundle = routed_bundle(owner=owner, action="turn")
    status, _ = faces.x_face_state(bundle, setup(bundle, "LEFT"), {"x_face": "land"}, {}, [], 0)
    assert status == expected


def test_unresolved_prepared_face_is_unknown_not_a_missing_face_error():
    bundle = routed_bundle()
    bundle.feature_definitions["land"]["preparation"] = {"kind": "end_face"}
    status, numbers, _ = prepared_blank._evaluate(bundle, {"setup": "LEFT"})
    assert status == "unknown"
    assert numbers["made_by"] == []
    assert numbers["made_outside_lineage"] == []
    assert numbers["unresolved_faces"]


@pytest.mark.parametrize("reason, expected", [(None, "pass"), ("partition registration unresolved", "unknown")])
def test_prepared_blank_reads_selected_output_not_full_parent(monkeypatch, reason, expected):
    import prechips.kernel

    bundle = routed_bundle()
    output = {"bbox_mm": [0, 0, 0, 4, 2, 2], "volume_mm3": 16}
    if reason:
        output["reason"] = reason
    facts = {
        "status": "ok",
        "setups": {
            "SPLIT": {
                "stock_out_bbox_mm": [0, 0, 0, 10, 2, 2],
                "stock_out_volume_mm3": 40,
                "outputs": {"left": output},
            }
        },
    }
    monkeypatch.setattr(prechips.kernel, "run_geometry", lambda _: facts)
    status, _ = prepared_blank._cut(
        bundle, "LEFT", [FRAME["x"], FRAME["y"], FRAME["z"]],
        [[0, 4], [0, 2], [0, 2]], [0.01, 0.01, 0.01], {},
    )
    assert status == expected


@pytest.mark.parametrize("partitioned, expected", [(True, "unknown"), (False, "error")])
def test_prepared_child_without_native_proof_is_not_a_false_raw_box_error(
    monkeypatch, partitioned, expected
):
    import prechips.kernel

    bundle = routed_bundle()
    bundle.plan["stock"].update(
        origin_mm=[0, 0, 0],
        section_mm=[2, 2],
        length_mm=10,
        axis=FRAME["x"],
        section_axis=FRAME["y"],
    )
    if not partitioned:
        setup(bundle, "SPLIT")["ops"][0].pop("outputs")
        setup(bundle, "LEFT")["stock_in"] = "SPLIT"
        bundle.plan["setups"] = [
            row for row in bundle.plan["setups"] if row["id"] != "RIGHT"
        ]
    monkeypatch.setattr(
        prechips.kernel, "run_geometry", lambda _: {"status": "unknown", "reason": "no native proof"}
    )
    monkeypatch.setattr(prepared_blank, "_checks", lambda *args: ("pass", ""))
    status, _, _ = prepared_blank._evaluate(
        bundle,
        {
            "setup": "LEFT",
            "origin_mm": [0, 0, 0],
            "length_mm": 4,
            "section_mm": [2, 2],
            "tolerance_mm": [0.01, 0.01, 0.01],
        },
    )
    assert status == expected


def test_tip_producer_preserves_split_history_without_crediting_transient_face(monkeypatch):
    bundle = routed_bundle()
    monkeypatch.setattr(tip_endpoints, "cut_coverage", lambda *args, **kwargs: "whole")
    target = setup(bundle, "LEFT")
    assert [row["id"] for row in tip_endpoints.lineage(bundle, target)] == ["BASE", "SPLIT"]
    debts = []
    assert tip_endpoints._producer(bundle, target, 0, "land", 0, None, debts=debts) == "unknown"
    assert any("partition" in debt for debt in debts)
    bundle.finished_feature_owners["land"] = "source:left-solid"
    assert tip_endpoints._producer(bundle, target, 0, "land", 0, None)[0]["id"] == "BASE"


def test_anonymous_carried_top_does_not_gain_a_nominal_zero_after_split(monkeypatch):
    bundle = routed_bundle()
    setup(bundle, "BASE")["ops"] = []
    setup(bundle, "LEFT")["stock_state"] = {"top_z": 0}
    monkeypatch.setattr(tip_endpoints, "_carried", lambda *args: {})
    assert tip_endpoints.operative_z(bundle, setup(bundle, "LEFT"), 0, "top") == "unknown"


def test_explicit_zero_route_keeps_named_output_producer_and_rejects_broken_history():
    bundle = routed_bundle()
    assert [row["id"] for row in touch._stock_route(bundle, setup(bundle, "LEFT"))] == ["BASE", "SPLIT", "LEFT"]
    del setup(bundle, "BASE")["stock_in"]
    assert touch._stock_route(bundle, setup(bundle, "LEFT")) is None


@pytest.mark.parametrize("owner, expected", [(None, "unknown"), ("source:left-solid", 0)])
def test_native_as_is_plane_ledger_does_not_leak_across_partition(monkeypatch, owner, expected):
    bundle = routed_bundle(owner=owner)
    setup(bundle, "BASE")["ops"] = []
    bundle.plan["stock"]["as_is_faces"] = ["F-land"]
    bundle.kernel = {"mapping": {"F-land": 0}}
    plane = {"source": "BASE", "frame": FRAME, "normal_z": 1, "z_mm": 0}
    monkeypatch.setattr(native, "setup_frame", lambda *args: FRAME)
    monkeypatch.setattr(native, "_kernel_face_boxes", lambda *args: ([("F-land", [[0, 1], [0, 1], [0, 0]])], None))
    monkeypatch.setattr(native, "_carried_native_plane_groups", lambda *args, **kwargs: [{"z": 0, "refs": ["F-land"]}])
    monkeypatch.setattr(native, "_native_plane_geometry", lambda *args: deepcopy(plane))
    monkeypatch.setattr(native, "_plane_in_frame", lambda *args, **kwargs: 0)
    # Isolate route identity: the parting cut is independently proven to spare this face.
    monkeypatch.setattr(native, "_carry_cut", lambda *args: False)
    monkeypatch.setattr(native, "op_claims", lambda *args: ([], False, False))
    credited, debts = [], []
    result = native._carried_face_z(bundle, setup(bundle, "LEFT"), "land", 0, 0, debts, credited)
    assert result == expected
    assert credited == (["F-land"] if expected == 0 else [])
    assert bool(debts) is (expected == "unknown")


@pytest.mark.parametrize("owner, expected", [(None, "unknown"), ("source:left-solid", "BASE:10"), ("source:right-solid", None)])
def test_scribe_and_rough_credits_require_owned_material(owner, expected):
    bundle = routed_bundle(owner=owner, action="scribe")
    root_op = setup(bundle, "BASE")["ops"][0]
    root_op["layout"] = "dividers"
    file_op = {"op": 30, "do": "file_to_line", "feature": "land"}
    setup(bundle, "LEFT")["ops"] = [file_op]
    assert manual_arc._layout_op(bundle, file_op, "land") == expected
    root_op.update(do="profile", contour={"method": "stairs"})
    rough = manual_arc._rough(bundle, file_op, "land")
    assert rough == ("BASE op 10" if expected == "BASE:10" else expected)


@pytest.mark.parametrize("owner, expected", [(None, None), ("source:left-solid", True), ("source:right-solid", False)])
def test_filing_button_hole_sizing_is_partition_aware(owner, expected):
    bundle = routed_bundle(owner=owner, action="drill")
    file_op = {"op": 30, "do": "file_to_line", "feature": "land"}
    setup(bundle, "LEFT")["ops"] = [file_op]
    assert manual_arc._sized_before(bundle, file_op, "land") is expected


def test_tooling_hole_unknown_maker_is_retained_as_debt(monkeypatch):
    bundle = routed_bundle(action="drill")
    monkeypatch.setattr(tooling_hole, "_sizing_action", lambda *args: "drill")
    monkeypatch.setattr(tooling_hole, "_fit", lambda *args: ("pass", {}, "fits"))
    monkeypatch.setattr(tooling_hole, "_clocking", lambda *args: {})
    status, numbers, why = tooling_hole._evaluate(
        bundle, setup(bundle, "LEFT"), "land", [], [("fixture", {})], {"state": "drilled"}, {},
    )
    assert status == "unknown"
    assert numbers["made_by"] == []
    assert numbers["unresolved_makers"] == ["BASE op 10"]
    assert "partition" in why
    assert "no earlier setup" not in why


@pytest.mark.parametrize("owner, expected", [(None, "unknown"), ("source:left-solid", "pass"), ("source:right-solid", "error")])
def test_drill_prerequisite_order_uses_material_not_ancestor_membership(owner, expected):
    bundle = routed_bundle(owner=owner, action="drill")
    setup(bundle, "LEFT")["ops"] = [{"op": 30, "do": "ream", "feature": "land"}]
    finding = next(row for row in op_order.evaluate(bundle) if row.subject == "LEFT")
    assert finding.status == expected
    if expected == "unknown":
        assert finding.numbers["violations"] == []
        assert finding.numbers["unresolved"]


def test_measurement_debt_history_includes_split_without_claiming_survival():
    bundle = routed_bundle()
    job = deepcopy(bundle.plan)
    for current in job["setups"]:
        for op in current["ops"]:
            op["subject"] = f"{current['id']}:{op['op']}"
    job["measurement_debts"] = {
        "setups": {"BASE": [{"id": "stock-size"}]},
        "ops": {"BASE:10": [{"id": "facing-depth"}], "SPLIT:20": [{"id": "split-kerf"}]},
    }
    debts = geometry_common.kernel_measurement_debts(job, setup(bundle, "LEFT"), stock=True)
    assert {row["id"] for row in debts} == {"stock-size", "facing-depth", "split-kerf"}


def test_exposed_profile_unknown_partition_feature_never_gets_declared_interval(monkeypatch):
    bundle = routed_bundle()
    bundle.feature_definitions = {"land": {"kind": "cylinder"}}
    monkeypatch.setattr(turned_profile, "_context", lambda *args: {})
    monkeypatch.setattr(turned_profile, "_kernel_off_axis", lambda *args: {})
    monkeypatch.setattr(turned_profile, "present", lambda *args: None)
    monkeypatch.setattr(turned_profile, "_stock_fill", lambda *args: ([], [], None))
    profile = turned_profile.exposed_profile(bundle, setup(bundle, "LEFT"))
    assert profile["intervals"] == []
    assert profile["unresolved"] == ["land"]
    assert "ownership" in profile["unresolved_reasons"]["land"]
    assert profile["complete"] is False


def test_tip_transfer_composes_output_pose_with_producer_frame(monkeypatch):
    from prechips.rules import coordinates

    bundle = routed_bundle(owner="source:left-solid")
    before, target = setup(bundle, "SPLIT"), setup(bundle, "LEFT")
    before["ops"][0]["outputs"]["left"]["pose"] = {
        **POSE,
        "origin": [0, 0, 10],
        "x": [1, 0, 0],
        "y": [0, -1, 0],
        "z": [0, 0, -1],
    }
    target["stock_state"] = {"top_z": 3, "top_feature": "land"}
    target["zero"] = {"z": {"face": "top"}}
    monkeypatch.setattr(
        tip_endpoints, "setup_frame",
        lambda _, current: {**FRAME, "origin": [0, 0, 2 if current is before else 1]},
    )
    monkeypatch.setattr(coordinates, "dro_grid", lambda *args: (0.1, 1))
    monkeypatch.setattr(tip_endpoints, "arrival_zs", lambda *args: {})
    requested = []

    def left_z(_, current, value, feature, received):
        requested.append((current["id"], value, feature))
        return value

    monkeypatch.setattr(tip_endpoints, "_left_z", left_z)
    move = tip_endpoints.transfer(bundle, target)
    assert move["sign"] == -1
    assert move["offset"] == pytest.approx(7)
    assert requested == [("SPLIT", 4, "land")]
    assert move["carried"] == {"top_z": (3, 3)}


@pytest.mark.parametrize("units", ["mm", "in"])
def test_tip_transfer_uses_forward_quarter_turn_registration_not_its_inverse(
    monkeypatch, units
):
    from prechips.rules import coordinates

    bundle = routed_bundle(owner="source:left-solid")
    bundle.features["units"] = units
    before, target = setup(bundle, "SPLIT"), setup(bundle, "LEFT")
    before["ops"][0]["outputs"]["left"]["pose"] = {
        **POSE,
        "origin": [10, 20, 30],
        "x": [0, 1, 0],
        "y": [-1, 0, 0],
        "z": [0, 0, 1],
    }
    target["stock_state"] = {"top_z": 29, "top_feature": "land"}
    target["zero"] = {"z": {"face": "top"}}
    monkeypatch.setattr(
        tip_endpoints, "setup_frame",
        lambda _, current: {
            **FRAME, "origin": [1, 2, 3] if current is before else [7, 8, 9],
        },
    )
    monkeypatch.setattr(coordinates, "dro_grid", lambda *args: (0.1, 1))
    monkeypatch.setattr(tip_endpoints, "arrival_zs", lambda *args: {})
    requested = []

    def left_z(_, current, value, feature, received):
        requested.append((current["id"], value, feature))
        return value

    monkeypatch.setattr(tip_endpoints, "_left_z", left_z)
    move = tip_endpoints.transfer(bundle, target)
    assert move["sign"] == 1
    # P([1, 2, 3]) = [8, 21, 33]; receiver origin Z is 9. P^-1 gives -36 instead.
    assert move["offset"] == pytest.approx(24)
    assert requested == [("SPLIT", 5, "land")]
    assert move["carried"] == {"top_z": (29, 29)}


@pytest.mark.parametrize(
    "pose",
    [
        "unknown",
        {**POSE, "binding": "unknown"},
        {**POSE, "origin": ["unknown", 0, 0]},
        {**POSE, "z": ["unknown", 0, 1]},
    ],
    ids=["unknown", "binding", "origin", "axis"],
)
def test_tip_unknown_output_pose_carries_no_nominal_arrival_z(monkeypatch, pose):
    from prechips.rules import coordinates

    bundle = routed_bundle(owner="source:left-solid")
    setup(bundle, "SPLIT")["ops"][0]["outputs"]["left"]["pose"] = pose
    target = setup(bundle, "LEFT")
    target["stock_state"] = {
        "top_z": 3, "top_feature": "land",
        "bottom_z": 1, "bottom_feature": "land",
    }
    monkeypatch.setattr(tip_endpoints, "setup_frame", lambda *args: FRAME)
    monkeypatch.setattr(coordinates, "dro_grid", lambda *args: (0.1, 1))
    assert tip_endpoints.transfer(bundle, target) is None
    assert tip_endpoints.arrival_zs(bundle, target) == {
        "top_z": (3, "unknown"), "bottom_z": (1, "unknown"),
    }


@pytest.mark.parametrize(
    "owner, expected",
    [(None, (None, None)), ("source:left-solid", (True, False))],
)
def test_parent_scribe_needs_material_proof_for_each_retained_child(owner, expected):
    bundle = routed_bundle(owner=owner, action="scribe")
    saw = {"op": 30, "do": "saw_cut", "follows": "BASE:10"}
    assert tuple(
        saw_cut.scribe_material_status(bundle, setup(bundle, sid), saw)
        for sid in ("LEFT", "RIGHT")
    ) == expected


def test_unknown_parent_scribe_cannot_become_straight_box_removal():
    from prechips.kernel import scribed_profile

    bundle = routed_bundle(action="scribe")
    saw = {"op": 30, "do": "saw_cut", "follows": "BASE:10"}
    for sid in ("LEFT", "RIGHT"):
        profile = scribed_profile(bundle, setup(bundle, sid), saw)
        assert profile is not None
        assert profile.get("reason")
        assert "centre_mm" not in profile


def test_known_scribe_owner_with_unknown_output_pose_is_not_native_path_credit():
    from prechips.kernel import scribed_profile

    bundle = routed_bundle(owner="source:left-solid", action="scribe")
    setup(bundle, "SPLIT")["ops"][0]["outputs"]["left"]["pose"] = "unknown"
    target = setup(bundle, "LEFT")
    saw = {"op": 30, "do": "saw_cut", "follows": "BASE:10"}
    assert saw_cut.scribe_material_status(bundle, target, saw) is None
    assert scribed_profile(bundle, target, saw).get("reason")


@pytest.mark.parametrize(
    "owner, expected",
    [(None, "unknown"), ("source:left-solid", "pass"), ("source:right-solid", "error")],
)
def test_saw_native_volumes_cannot_override_scribe_material_debt(monkeypatch, owner, expected):
    import prechips.kernel

    bundle = routed_bundle(owner=owner, action="scribe")
    target = setup(bundle, "LEFT")
    target["ops"] = [
        {"op": 30, "do": "saw_cut", "follows": "BASE:10", "allowance_mm": 1}
    ]
    facts = {
        "status": "ok",
        "ops": {"LEFT:30": {key: 1 for key in saw_cut._SCRIBED_FACTS}},
    }
    monkeypatch.setattr(prechips.kernel, "run_geometry", lambda _: facts)
    monkeypatch.setattr(saw_cut, "saw_tool", lambda *args: "hand_saw")
    monkeypatch.setattr(saw_cut, "saw_station", lambda *args: "fits")
    monkeypatch.setattr(saw_cut, "slitting_saw", lambda *args: False)
    monkeypatch.setattr(saw_cut, "resolve", lambda *args: {"kind": "bench"})
    monkeypatch.setattr(saw_cut, "uncertain", lambda *args: False)
    monkeypatch.setattr(saw_cut, "unavailable", lambda *args: None)
    (finding,) = saw_cut.evaluate(bundle)
    assert finding.status == expected
    assert finding.numbers["scribe_on_arriving_stock"] == {
        "unknown": "unknown", "pass": True, "error": False,
    }[expected]
    if expected == "unknown":
        assert "survives the material partition" in finding.sentence
