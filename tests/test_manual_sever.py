"""Manual severing is a material-state barrier, never a modeled release.

These tests exercise production dispatch without importing FreeCAD or launching a
native process. Sentinel solids test stock identity/credit, not physical geometry.
"""

import ast
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from prechips import kernel
from prechips.model import Plan
from prechips.rules.geometry_common import cutting_action
from prechips.rules.resolution import MANUAL, MANUAL_SEVER_REASON

ENGINE = Path(kernel.__file__).with_name("freecad_job.py")


def manual_op(**extra):
    return {"op": 20, "do": "manual_sever", "feature": "part", "tool": "unknown", **extra}


def plan(op):
    return {"part": "test", "features": "features.toml", "setups": [{"id": "H1", "ops": [op]}]}


@pytest.mark.parametrize("tool", [None, "unknown"])
def test_manual_sever_is_explicit_material_changing_action(tool):
    op = manual_op()
    if tool is None:
        del op["tool"]
    parsed = Plan.model_validate(plan(op)).model_dump(exclude_unset=True)
    assert parsed["setups"][0]["ops"][0] == op
    assert "manual_sever" in MANUAL
    assert cutting_action(op) is True


@pytest.mark.parametrize(
    "extra",
    [
        {"tool": "parting-blade"},
        {"to_dia": 6.35},
        {"to_z": -8.5},
        {"z_from": -8.0, "z_to": -9.0},
        {"depth_mm": 1.0},
        {"rpm": 100.0},
        {"feed_mm_rev": 0.05},
        {"keep": "part"},
        {"outputs": {}},
        {"holder": "parting-holder"},
        {"faces": ["#1"]},
        {"stock_removal_bounds": {"x": [-5.0, 5.0], "y": [-5.0, 5.0], "z": [-9.0, -8.0]}},
    ],
)
def test_manual_sever_cannot_declare_modeled_cut_or_retained_output(extra):
    with pytest.raises(ValidationError, match="manual_sever"):
        Plan.model_validate(plan(manual_op(**extra)))


def test_manual_sever_adapter_sends_barrier_not_a_cutting_recipe():
    setup = {"id": "H1"}
    # No bundle data may be needed to invent tool/geometry facts for this action.
    payload = kernel.op_inputs(SimpleNamespace(), setup, manual_op())
    assert payload == {
        "subject": "H1:20",
        "feature": "part",
        "do": "manual_sever",
        "finishing": False,
        "measurement_debts": [],
        "refused_fields": [],
    }


@pytest.fixture(scope="module")
def native_boundaries():
    """Compile only existing method bodies; no FreeCAD module or native execution."""
    tree = ast.parse(ENGINE.read_text(encoding="utf-8"))
    selected = {
        "_build",
        "_cut",
        "_finish",
        "_stock_after",
        "_unproven",
        "_stopping_tool_minimum",
        "_joined",
        "_op_unknown",
        "_op_stock",
    }
    methods = {
        method.name: method
        for cls in tree.body
        if isinstance(cls, ast.ClassDef)
        for method in cls.body
        if isinstance(method, ast.FunctionDef) and method.name in selected
    }
    assert set(methods) == selected
    namespace = {
        "UNKNOWN": "unknown",
        "MANUAL_SEVER_REASON": MANUAL_SEVER_REASON,
        "CLEARANCE_KEYS": (),
        "_number": lambda value: isinstance(value, (int, float)) and not isinstance(value, bool),
        "_retained_metadata": lambda op: op.get("do") in {"release", "inspect"},
        "_sawn": lambda op: False,
        "_hand": lambda op: False,
    }
    constants = [
        node
        for node in tree.body
        if isinstance(node, ast.Assign)
        and any(
            isinstance(target, ast.Name) and target.id == "MANUAL_SEVER_REASON"
            for target in node.targets
        )
    ]
    assert len(constants) == 1
    exec(
        compile(
            ast.Module(body=[*constants, *methods.values()], type_ignores=[]), str(ENGINE), "exec"
        ),
        namespace,
    )
    assert namespace["MANUAL_SEVER_REASON"] == MANUAL_SEVER_REASON
    return SimpleNamespace(**{name: namespace[name] for name in selected})


def built_route(native_boundaries):
    incoming = SimpleNamespace(Solids=["one connected incoming solid"])
    partial = SimpleNamespace(Solids=["one connected solid with residual web"])
    prep = {"subject": "H1:10", "do": "part_off", "to_dia": 6.85}
    sever = {"subject": "H1:20", "do": "manual_sever", "feature": "part", "finishing": False}
    later = {"subject": "H1:30", "do": "finish_face"}
    calls = []

    class Setup:
        _build = native_boundaries._build
        _finish = native_boundaries._finish
        _stock_after = native_boundaries._stock_after

        def _cut(self, op, stock):
            calls.append(op["subject"])
            if op is prep:
                assert stock is incoming
                return ("partial radial cut", []), None
            return native_boundaries._cut(self, op, stock)

        def _remove(self, *args):
            return [partial], None

        def _advance_lower(self, op, before, after, cut):
            self.lower_out = after

        def _keep_after(self, subject, stock, where):
            return stock, None

        def _where(self):
            return "sentinel route"

        def _subject(self, op):
            return op["subject"]

        def _begin_thread_material_op(self, op):
            pass

        def _end_thread_material_op(self, op):
            pass

        def _prove_op_pickup(self, op, stock):
            return None

    setup = Setup()
    setup.part = setup.lower_part = incoming
    setup.ops = [prep, sever, later]
    setup.thread_regions = []
    setup.cuts, setup.lower_cuts, setup.zero_pickup_debts = {}, {}, {}
    setup.stopped_cut = None
    setup.matrix = object()
    setup.built = setup._build()
    return setup, (prep, sever, later), incoming, partial, calls


def test_partial_connected_stock_survives_before_unmodeled_manual_sever(native_boundaries):
    setup, (prep, sever, later), incoming, partial, calls = built_route(native_boundaries)
    assert setup.cuts[id(prep)] == (incoming, partial, None)
    before, after, _ = setup.cuts[id(sever)]
    assert before is partial
    assert after is None  # Neither unchanged stock nor an invented detached part.
    assert setup.stock_states == [incoming, partial]
    assert setup.cuts[id(later)][0:2] == (None, None)
    assert calls == ["H1:10"]  # The barrier never enters generic cut dispatch.
    assert setup.built[0] is None
    assert "manual_sever" in setup.built[1]


def test_manual_sever_refuses_generic_cut_even_with_plausible_cutting_fields(native_boundaries):
    class NoGenericGeometry:
        def _claims(self, op):
            pytest.fail("manual_sever must refuse before generic face/cutter dispatch")

    removal, reason = native_boundaries._cut(
        NoGenericGeometry(),
        {"do": "manual_sever", "to_dia": 6.35, "to_z": -8.5, "faces": ["#1"]},
        object(),
    )
    assert removal is None
    assert "manual_sever" in reason and "unmodeled" in reason


def test_manual_sever_blocks_finish_inspection_and_component_join_credit(native_boundaries):
    setup, (_, sever, later), _, _, _ = built_route(native_boundaries)
    assert setup._finish({}) == setup.built
    for op in (sever, later):
        stock, reason = setup._stock_after({"after": op["subject"]})
        assert stock is None and "unresolved" in reason
    # Joining a known independent component cannot repair the severed branch.
    joined, reason = native_boundaries._joined(
        ["H1", "component"], {"H1": setup.built, "component": (object(), None)}
    )
    assert joined is None and reason == setup.built[1]


def test_stock_barrier_preserves_independent_positive_collision_evidence(native_boundaries):
    facts = {
        "tool_hits": 7,
        "holder_hits": 3,
        "min_hits": {"tool": 7, "holder": 3},
        "corner_radii_mm": [0.0],
        "reasons": {},
    }
    native_boundaries._unproven(facts, "H1:20 manual_sever is unmodeled")
    assert facts["tool_hits"] == "unknown"
    assert facts["min_hits"]["tool"] == "unknown"
    assert facts["min_hits"]["holder"] == 3
    assert facts["corner_radii_mm"] == [0.0]
    setup = SimpleNamespace(stopped_cut=123)
    assert native_boundaries._stopping_tool_minimum(setup, object(), 4, 0, 4) == 4


def test_manual_sever_facts_cannot_claim_attainment_or_a_post_cut_snapshot(native_boundaries):
    setup, (_, sever, later), _, partial, _ = built_route(native_boundaries)
    measured = ("tool_hits", "holder_hits", "reach_depth_mm")
    facts = native_boundaries._op_unknown(
        SimpleNamespace(_MEASURED=measured), sever, MANUAL_SEVER_REASON
    )
    assert facts["approach"] == "manual_sever"
    assert facts["material_effect"] == "unmodeled"
    assert facts["stock_after"] == "unknown"
    for key in ("claimed_indices", *measured, "corner_radii_mm"):
        assert facts[key] == "unknown"
        assert facts["reasons"][key] == MANUAL_SEVER_REASON
    assert "completed" not in facts
    assert setup.lower_cuts[id(sever)][0] is partial
    assert setup.lower_cuts[id(sever)][1] is None
    setup.stock_reason = None
    setup._op_has_thread_material = lambda op, side: False
    for op in (sever, later):
        stock, reason = native_boundaries._op_stock(setup, op, 1)
        assert stock is None and reason


def test_manual_barrier_is_sent_even_though_preservation_ledger_is_unmodeled(monkeypatch):
    from prechips import joint_features
    from prechips.rules import coordinates

    setup = {"id": "H1", "stock_in": "stock", "ops": [manual_op()]}
    bundle = SimpleNamespace(features={"units": "mm"}, feature_definitions={})
    monkeypatch.setattr(kernel, "setup_frame", lambda *args: "unknown")
    monkeypatch.setattr(kernel, "_registration_inputs", lambda *args, **kwargs: "unknown")
    monkeypatch.setattr(kernel, "hold_inputs", lambda *args: {})
    monkeypatch.setattr(kernel, "inspection_preservation_inputs", lambda *args: [])
    monkeypatch.setattr(kernel, "resolve", lambda *args: {})
    monkeypatch.setattr(joint_features, "setup_joint", lambda *args: None)
    monkeypatch.setattr(coordinates, "revolved_located", lambda *args: False)
    payload, sent = kernel._setup_inputs(bundle, setup, {}, set(), set(), None, {})
    assert sent == setup["ops"]
    assert payload["preservation_ledger"] == [
        {"subject": "H1:20", "do": "manual_sever", "effect": "unmodeled"}
    ]
    assert len(payload["ops"]) == 1
    assert payload["ops"][0]["do"] == "manual_sever"
    assert payload["ops"][0]["finishing"] is False


@pytest.mark.parametrize("rule", ["accessibility", "reach", "attainment"])
def test_host_manual_action_remains_unknown_even_with_stale_positive_credit(monkeypatch, rule):
    from prechips.rules import geometry_common

    setup = {"id": "H1", "ops": [manual_op()]}
    op = setup["ops"][0]
    stale = {
        "status": "ok",
        "ops": {"H1:20": {"claimed_indices": [0], "tool_hits": 0, "holder_hits": 0}},
    }
    monkeypatch.setattr(kernel, "run_geometry", lambda bundle: stale)
    monkeypatch.setattr(
        geometry_common,
        "prepared_job",
        lambda bundle: {"setups": [{"id": "H1", "hold": {}, "frame": "unknown", "ops": []}]},
    )
    monkeypatch.setattr(geometry_common, "operations", lambda bundle: [(setup, op)])
    monkeypatch.setattr(geometry_common, "provenance", lambda *args: [])
    (context,) = geometry_common.op_contexts(SimpleNamespace(), rule)
    finding = context[-1]
    assert finding.status == "unknown"
    assert finding.numbers["material_effect"] == "unmodeled"
    assert finding.numbers["model_reason"] == MANUAL_SEVER_REASON


def test_post_sever_inspection_is_a_checkpoint_not_material_reconstruction(native_boundaries):
    setup, (prep, sever, _), incoming, partial, _ = built_route(native_boundaries)
    inspect = {
        "subject": "H1:90",
        "do": "inspect",
        "feature": "hub_supply_bore",
        "checks": {"dia": "existing-gauge"},
    }
    setup.ops = [prep, sever, inspect]
    setup.cuts = {}
    setup.built = setup._build()
    assert setup.cuts[id(prep)] == (incoming, partial, None)
    assert setup.cuts[id(sever)][0:2] == (partial, None)
    assert setup.cuts[id(inspect)][0:2] == (None, None)
    assert setup.built[0] is None
    snapshot, reason = setup._stock_after({"after": inspect["subject"]})
    assert snapshot is None and "unresolved" in reason
    assert setup._finish({}) == setup.built


def test_known_inspection_capacity_can_pass_without_restoring_material_state(native_boundaries):
    from test_practical_inspection import final_op, practical_bundle

    from prechips.rules import inspection

    bundle = practical_bundle()
    op = final_op(bundle)
    setup = next(
        entry
        for entry in bundle.plan["setups"]
        if any(candidate is op for candidate in entry["ops"])
    )
    setup["ops"].insert(0, manual_op(op=5))
    bundle = replace(
        bundle,
        kernel={
            "status": "ok",
            "setups": {setup["id"]: {"stock_reason": MANUAL_SEVER_REASON}},
        },
    )
    status, message, nums = inspection.requirement_check(bundle, "end", "length", op)
    assert status == "pass" and message
    assert nums["evaluation"] == "inspection_plan"
    assert nums["part_result"] == "not_recorded"
    # Gauge capability and an authored checkpoint do not rebuild material.
    route, _, _, _, _ = built_route(native_boundaries)
    assert route._finish({})[0] is None


def test_positive_parting_stop_preserves_z_placement_pass_without_release_claim(monkeypatch):
    from prechips.rules import parting_face

    setup = {"id": "H1"}
    op = {"op": 70, "do": "part_off", "feature": "hub_supply_parting", "to_z": -8.5, "to_dia": 6.85}
    monkeypatch.setattr(parting_face, "operations", lambda bundle: [(setup, op)])
    monkeypatch.setattr(parting_face, "parts_off", lambda bundle, candidate: True)
    monkeypatch.setattr(
        parting_face, "parting_plane", lambda *args: {"status": "pass", "face_z": -8.5}
    )
    monkeypatch.setattr(parting_face, "label", lambda name: name)
    (finding,) = parting_face.evaluate(SimpleNamespace())
    assert finding.status == "pass"
    assert finding.numbers["to_z"] == finding.numbers["face_z"] == -8.5
    assert finding.numbers["to_dia"] == 6.85
    assert finding.numbers["separation"] == "unknown"
    assert "separation and retained-piece release are not established" in finding.sentence
    assert "keeping the piece toward the exposed end" not in finding.sentence
    assert "plan.setups.H1.ops.70.to_dia" in finding.cite
