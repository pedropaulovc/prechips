"""Small native boundaries for sequential assemblies and retaining-compound facts."""

import copy
import math
import subprocess

import pytest
from test_joint_geometry import _bar, _bore_setup, _joint_job, _primitive, _surface_job
from test_kernel_geometry import IDENTITY, Engine, _op
from test_turning_geometry import _turn

_AUTHOR = r"""
import sys
import FreeCAD, Part
V = FreeCAD.Vector
out = sys.argv[sys.argv.index("--") + 1]

def save(name, shape):
    shape = shape.removeSplitter()
    assert shape.isValid() and len(shape.Solids) == 1, name
    shape.exportStep(out + "/" + name + ".step")

body = Part.makeCylinder(10, 10)
sleeve = Part.makeCylinder(4.9, 20)
shaft = Part.makeCylinder(2.9, 30)
save("multi", body.multiFuse([sleeve, shaft]).cut(Part.makeCylinder(1, 30)))
save("joined", body.fuse(sleeve).cut(Part.makeCylinder(2, 20)))
save("blocks", Part.makeBox(40, 10, 10))
"""


def _author_solids(directory, executable):
    """Reusable authoring boundary for the parent's non-pytest native smoke."""
    script = directory / "author.py"
    script.write_text(_AUTHOR, encoding="utf-8")
    process = subprocess.run(
        [str(executable), str(script), "--", str(directory)],
        capture_output=True,
        text=True,
        errors="replace",
        timeout=300,
    )
    paths = {path.stem: path for path in directory.glob("*.step")}
    assert set(paths) == {"multi", "joined", "blocks"}, (
        process.stdout[-2000:] + process.stderr[-2000:]
    )
    return paths


@pytest.fixture(scope="module")
def multi_solids(tmp_path_factory, freecad_kernel):
    return _author_solids(tmp_path_factory.mktemp("joint-multi-solids"), freecad_kernel)


@pytest.fixture
def engine(tmp_path, freecad_kernel):
    return Engine(tmp_path, freecad_kernel)


def _setup(sid, stock_in, ops=(), frame=IDENTITY):
    return {
        "id": sid,
        "stock_in": stock_in,
        "frame": copy.deepcopy(frame),
        "hold": {"reason": "fixture outside this stock-boundary probe"},
        "ops": list(ops),
    }


def _prep(name, spec):
    return {
        **spec,
        "joint_feature": name,
        "action": "bore" if spec["kind"] == "cylinder_bore" else "finish_turn",
        "diameter_mm": spec["nominal_dia_mm"],
        "finishing": True,
        "completes": True,
    }


def _join(sid, socket, spigot, socket_ref, spigot_ref, *, method="retaining_compound"):
    refs = [socket_ref, spigot_ref]
    joint = {
        "kind": "cylindrical",
        "refs": refs,
        "socket": socket,
        "spigot": spigot,
        "socket_ref": socket_ref,
        "spigot_ref": spigot_ref,
        "fit": "clearance",
        "method": method,
        "band_mm": [0.2, 0.4],
        "process": "apply the cited retaining compound to the clean mating surfaces",
        "reason": None,
        "fit_error": None,
    }
    if method == "retaining_compound":
        joint.update(cure_time_min=30.0, surface_prep="degrease and dry both mating surfaces")
    return {**_setup(sid, refs), "joint": joint}


def _multi_job(engine, step, *, method="retaining_compound"):
    """Body + hollow sleeve, then that actual assembly + separately prepared shaft."""
    features = {
        "body-socket": _primitive("body-socket", "cylinder_bore", "body", 10, (10, 10.1), 10),
        "sleeve-spigot": _primitive(
            "sleeve-spigot", "cylinder_spigot", "sleeve", 9.8, (9.7, 9.8), 20
        ),
        "sleeve-socket": _primitive(
            "sleeve-socket", "cylinder_bore", "sleeve", 6, (6, 6.1), 20
        ),
        "shaft-spigot": _primitive(
            "shaft-spigot", "cylinder_spigot", "shaft", 5.8, (5.7, 5.8), 30
        ),
    }
    reverse = {"origin": [0, 0, 0], "x": [1, 0, 0], "y": [0, -1, 0], "z": [0, 0, -1]}
    setups = []
    for sid, name, ref in (
        ("body-bore", "body-socket", "stock.body"),
        ("sleeve-turn", "sleeve-spigot", "stock.sleeve"),
        ("sleeve-bore", "sleeve-socket", "sleeve-turn"),
        ("shaft-turn", "shaft-spigot", "stock.shaft"),
    ):
        cut = _prep(name, features[name])
        bore = features[name]["kind"] == "cylinder_bore"
        op = (
            {**_op(sid + ":10", name, 1, 40, 60), "do": "bore", "joint_cut": cut}
            if bore
            else _turn(sid + ":10", name, joint_cut=cut)
        )
        setups.append(_setup(sid, ref, [op], reverse if bore else IDENTITY))
    shaft_bore = _bore_setup("shaft-turn", "shaft-bore")
    shaft_bore["frame"]["origin"] = [0, 0, 30]
    setups += [
        shaft_bore,
        _join(
            "join-sleeve",
            "body-socket",
            "sleeve-spigot",
            "body-bore",
            "sleeve-bore",
            method=method,
        ),
        _join(
            "join-shaft",
            "sleeve-socket",
            "shaft-spigot",
            "join-sleeve",
            "shaft-bore",
            method=method,
        ),
    ]
    job = engine.job(
        step,
        setups=setups,
        features={"final-bore": engine.refs(step, (-1, -1, 0), (1, 1, 30), kind="Cylinder")},
        stock={"components": {"body": _bar(20, 10), "sleeve": _bar(12, 20), "shaft": _bar(8, 30)}},
    )
    job["joint_features"] = features
    return job


def test_three_components_join_sequentially_without_filling_the_sleeve_core(engine, multi_solids):
    facts = engine.run(_multi_job(engine, multi_solids["multi"]))
    assert facts["status"] == "ok", facts
    first, second = (facts["setups"][name] for name in ("join-sleeve", "join-shaft"))
    assert first["stock_out_volume_mm3"] == pytest.approx(
        math.pi * (100 * 10 + 4.9**2 * 10 - 3**2 * 20), abs=2e-3
    )
    assert second["stock_out_volume_mm3"] == pytest.approx(
        math.pi * (100 * 10 + 4.9**2 * 10 + 2.9**2 * 10 - 30), abs=2e-3
    )
    assert first["completed_joint_features"] == ["body-socket", "sleeve-socket", "sleeve-spigot"]
    assert second["completed_joint_features"] == [
        "body-socket",
        "shaft-spigot",
        "sleeve-socket",
        "sleeve-spigot",
    ]
    assert "assembly_error" not in first and "assembly_error" not in second


@pytest.mark.parametrize("thru", [True, False], ids=["blocked-through", "blind"])
def test_blocked_socket_end_never_becomes_a_through_joint(engine, multi_solids, thru):
    job = _multi_job(engine, multi_solids["multi"])
    job["stock"]["components"]["body"]["length_mm"] = 12
    job["joint_features"]["body-socket"]["thru"] = thru
    job["setups"][0]["ops"][0]["joint_cut"]["thru"] = thru
    facts = engine.run(job)
    if thru:
        assert "blocked axial end" in facts["ops"]["body-bore:10"]["joint_error"]
        assert "stock_out_volume_mm3" not in facts["setups"]["body-bore"]
    else:
        assert facts["setups"]["body-bore"]["completed_joint_features"] == ["body-socket"]
        assert "assembly_error" in facts["setups"]["join-sleeve"]
    assert "stock_out_volume_mm3" not in facts["setups"]["join-sleeve"]
    assert "stock_out_volume_mm3" not in facts["setups"]["join-shaft"]


@pytest.mark.parametrize("debt", ["stock", "clearance", "cure", "surface"])
def test_unknown_facts_withhold_both_current_and_downstream_union(engine, multi_solids, debt):
    job = _multi_job(engine, multi_solids["multi"])
    first = job["setups"][-2]["joint"]
    if debt == "stock":
        job["stock"]["components"]["body"]["reason"] = "body supply length is unknown"
        reason = "body supply length is unknown"
    elif debt == "clearance":
        first.update(band_mm="unknown", reason="authored clearance_mm is unknown")
        reason = "clearance_mm"
    else:
        field = {"cure": "cure_time_min", "surface": "surface_prep"}[debt]
        first[field] = "unknown"
        # No serialized reason: the native boundary must independently recognize debt.
        reason = field
    facts = engine.run(job)
    for sid in ("join-sleeve", "join-shaft"):
        row = facts["setups"][sid]
        assert "stock_out_volume_mm3" not in row
        assert "assembly_error" not in row
        assert reason in row["stock_out_reason"]


def test_known_missing_or_malformed_compound_facts_are_native_errors(engine, multi_solids):
    baseline = _multi_job(engine, multi_solids["multi"])
    invalid = [
        ("cure_time_min", None),
        ("cure_time_min", 0),
        ("cure_time_min", True),
        ("cure_time_min", "30"),
        ("surface_prep", None),
        ("surface_prep", " "),
        ("surface_prep", 12),
        ("process", None),
        ("process", "unknown"),
        ("process", " unknown "),
        ("process", ""),
        ("process", 12),
    ]
    jobs = []
    for field, value in invalid:
        job = copy.deepcopy(baseline)
        joint = job["setups"][-2]["joint"]
        if value is None:
            joint.pop(field)
        else:
            joint[field] = value
        # An upstream host reason must not conceal a known invalid native process fact.
        joint["reason"] = "some other process fact is unknown"
        jobs.append(job)
    results = engine.run({"jobs": jobs})["results"]
    for (field, _), facts in zip(invalid, results, strict=True):
        first = facts["setups"]["join-sleeve"]
        assert field in first["assembly_error"]
        assert "stock_out_volume_mm3" not in first
        assert "stock_out_volume_mm3" not in facts["setups"]["join-shaft"]


def test_shared_ancestry_is_refused_even_when_one_ref_is_an_assembly(engine, multi_solids):
    job = _multi_job(engine, multi_solids["multi"])
    join = job["setups"][-1]
    join["stock_in"] = ["join-sleeve", "sleeve-bore"]
    join["joint"].update(refs=join["stock_in"], spigot_ref="sleeve-bore")
    row = engine.run(job)["setups"]["join-shaft"]
    assert "share component ancestry" in row["assembly_error"]
    assert "stock_out_volume_mm3" not in row


def test_two_independent_existing_assemblies_cannot_be_joined(engine, multi_solids):
    job = _surface_job(engine, multi_solids["blocks"])
    components = job["stock"]["components"]
    components.update(
        third={**copy.deepcopy(components["right"]), "origin_mm": [20, 0, 0]},
        fourth={**copy.deepcopy(components["right"]), "origin_mm": [30, 0, 0]},
    )
    left = job["setups"][0]
    left["id"] = "left-assembly"
    right = copy.deepcopy(left)
    right["id"] = "right-assembly"
    right["stock_in"] = ["stock.third", "stock.fourth"]
    right["joint"].update(
        refs=right["stock_in"], negative_ref="stock.third", positive_ref="stock.fourth"
    )
    right["joint"]["interfaces"][0]["at_mm"][0] = 30
    finish = copy.deepcopy(left)
    finish["id"] = "forbidden"
    finish["stock_in"] = ["left-assembly", "right-assembly"]
    finish["joint"].update(
        refs=finish["stock_in"],
        negative_ref="left-assembly",
        positive_ref="right-assembly",
    )
    finish["joint"]["interfaces"][0]["at_mm"][0] = 20
    job["setups"] = [left, right, finish]
    facts = engine.run(job)
    assert facts["setups"]["left-assembly"]["stock_out_volume_mm3"] == pytest.approx(2000)
    assert facts["setups"]["right-assembly"]["stock_out_volume_mm3"] == pytest.approx(2000)
    row = facts["setups"]["forbidden"]
    assert "at most one existing assembly" in row["assembly_error"]
    assert "stock_out_volume_mm3" not in row


@pytest.mark.parametrize("socket", ["body-socket", "sleeve-socket"])
def test_later_socket_preparation_cannot_be_reused_after_consumption(engine, multi_solids, socket):
    job = _multi_job(engine, multi_solids["multi"])
    reuse = copy.deepcopy(job["setups"][-1])
    reuse["id"] = "reuse"
    reuse["stock_in"] = ["join-sleeve", "shaft-bore"]
    reuse["joint"].update(socket=socket)
    job["setups"].append(reuse)
    facts = engine.run(job)
    assert facts["setups"]["join-sleeve"]["stock_out_volume_mm3"] == pytest.approx(
        math.pi * (100 * 10 + 4.9**2 * 10 - 3**2 * 20), abs=2e-3
    )
    assert facts["setups"]["join-shaft"]["stock_out_volume_mm3"] == pytest.approx(
        math.pi * (100 * 10 + 4.9**2 * 10 + 2.9**2 * 10 - 30), abs=2e-3
    )
    row = facts["setups"]["reuse"]
    assert "already been consumed" in row["assembly_error"]
    assert "stock_out_volume_mm3" not in row


def test_lost_required_sleeve_wall_is_not_authorized_by_its_planned_inner_bore(engine, multi_solids):
    job = _multi_job(engine, multi_solids["multi"])
    damage = copy.deepcopy(job["setups"][1]["ops"][0])
    damage["subject"] = "sleeve-turn:20"
    damage["joint_cut"].update(diameter_mm=9.0, finishing=False, completes=False)
    job["setups"][1]["ops"].append(damage)
    facts = engine.run(job)
    assert "protected finished material" in facts["ops"]["sleeve-turn:20"]["joint_error"]
    assert "stock_out_volume_mm3" not in facts["setups"]["sleeve-turn"]
    assert "stock_out_volume_mm3" not in facts["setups"]["join-sleeve"]


def test_silver_braze_and_press_do_not_require_retaining_compound_facts(engine, multi_solids):
    results = engine.run(
        {
            "jobs": [
                _joint_job(engine, multi_solids["joined"], interference=False),
                _joint_job(engine, multi_solids["joined"], interference=True),
            ]
        }
    )["results"]
    for facts in results:
        row = facts["setups"]["join"]
        assert "assembly_error" not in row
        assert row["stock_out_volume_mm3"] == pytest.approx(
            math.pi * (100 * 10 + 4.9**2 * 10), abs=2e-3
        )


def _lost_cap_job(engine, step):
    job = _joint_job(engine, step)
    job["joint_features"]["spigot"]["depth_mm"] = 10.0
    job["setups"][1]["ops"][0]["joint_cut"].update(depth_mm=10.0, z_from=0.0, z_to=20.0)
    job["features"]["top"] = engine.refs(step, (-4.9, -4.9, 20), (4.9, 4.9, 20), kind="Plane")
    lost = _setup(
        "lost-cap",
        "spigot-cut",
        [{
            **_op("lost-cap:10", "top", 1, 25, 50),
            "do": "face",
            "to_z": 15.0,
            "stock_removal_bounds": {"x": [-6, 6], "y": [-6, 6], "z": [15, 20]},
        }],
    )
    job["setups"].insert(2, lost)
    join = job["setups"][3]
    join["stock_in"][1] = "lost-cap"
    join["joint"].update(spigot_ref="lost-cap", refs=list(join["stock_in"]))
    return job


@pytest.mark.parametrize("joined_elsewhere", [False, True], ids=["unused", "unrelated-joint"])
def test_unused_decoy_spigot_cannot_hide_lost_finished_material(
    engine, multi_solids, joined_elsewhere
):
    job = _lost_cap_job(engine, multi_solids["joined"])
    job["stock"]["components"]["decoy"] = _bar(12, 5, at=(0, 0, 15))
    decoy = _primitive("decoy-spigot", "cylinder_spigot", "decoy", 9.8, (9.7, 9.8), 5)
    decoy["at_mm"] = [0, 0, 15]
    job["joint_features"]["decoy-spigot"] = decoy
    if joined_elsewhere:
        job["stock"]["components"]["decoy-body"] = _bar(20, 5, at=(0, 0, 15))
        socket = _primitive(
            "decoy-socket", "cylinder_bore", "decoy-body", 10, (10, 10.1), 5
        )
        socket["at_mm"] = [0, 0, 15]
        job["joint_features"]["decoy-socket"] = socket
        job["setups"].append(_join(
            "unrelated", "decoy-socket", "decoy-spigot", "stock.decoy-body", "stock.decoy",
            method="silver_braze",
        ))
    facts = engine.run(job)
    assert facts["setups"]["lost-cap"]["stock_out_volume_mm3"] == pytest.approx(
        math.pi * 4.9**2 * 15, abs=2e-3
    )
    row = facts["setups"]["join"]
    assert "protected finished material missing" in row["assembly_error"]
    assert "stock_out_volume_mm3" not in row


def test_later_overlapping_new_joint_leaves_prior_assemblies_and_unrelated_stock_known(
    engine, multi_solids
):
    job = _multi_job(engine, multi_solids["multi"])
    job["stock"]["components"].update(pin=_bar(8, 30), independent=_bar(20, 30))
    pin = _primitive("pin-spigot", "cylinder_spigot", "pin", 5.8, (5.7, 5.8), 30)
    socket = _primitive("body-socket-2", "cylinder_bore", "body", 10, (10, 10.1), 10)
    job["joint_features"].update({"pin-spigot": pin, "body-socket-2": socket})
    job["setups"][0]["ops"].append({
        **_op("body-bore:20", "body-socket-2", 1, 40, 60),
        "do": "bore",
        "joint_cut": _prep("body-socket-2", socket),
    })
    job["setups"] += [
        _setup("independent", "stock.independent"),
        _setup("pin-turn", "stock.pin", [
            _turn("pin-turn:10", "pin-spigot", joint_cut=_prep("pin-spigot", pin)),
        ]),
        _join("join-pin", "body-socket-2", "pin-spigot", "join-shaft", "pin-turn"),
    ]
    facts = engine.run(job)
    assert facts["setups"]["join-sleeve"]["stock_out_volume_mm3"] == pytest.approx(
        math.pi * (100 * 10 + 4.9**2 * 10 - 3**2 * 20), abs=2e-3
    )
    assert facts["setups"]["join-shaft"]["stock_out_volume_mm3"] == pytest.approx(
        math.pi * (100 * 10 + 4.9**2 * 10 + 2.9**2 * 10 - 30), abs=2e-3
    )
    assert facts["setups"]["independent"]["stock_out_volume_mm3"] == pytest.approx(
        math.pi * 100 * 30, abs=2e-3
    )
    row = facts["setups"]["join-pin"]
    assert "spigot ownership overlaps finished material" in row["assembly_error"]
    assert "stock_out_volume_mm3" not in row


@pytest.mark.parametrize("geometry", ["missing-prep", "blocked-blind", "fit-band", "lost-material"])
def test_unknown_cure_cannot_conceal_known_geometry_failure(engine, multi_solids, geometry):
    if geometry == "lost-material":
        job = _lost_cap_job(engine, multi_solids["joined"])
        join = job["setups"][-1]
        error = "protected finished material missing"
    else:
        job = _multi_job(engine, multi_solids["multi"])
        join = job["setups"][-2]
        if geometry == "missing-prep":
            job["setups"][0]["ops"] = []
            error = "no completed preparation"
        elif geometry == "blocked-blind":
            job["stock"]["components"]["body"]["length_mm"] = 12
            job["joint_features"]["body-socket"]["thru"] = False
            job["setups"][0]["ops"][0]["joint_cut"]["thru"] = False
            error = "overlap"
        else:
            join["joint"]["band_mm"] = [0.1, 0.3]
            error = "worst-case diameter"
    join["joint"].update(
        method="retaining_compound",
        cure_time_min="unknown",
        surface_prep="degrease and dry",
        process_reason="authored cure_time_min is unknown",
    )
    row = engine.run(job)["setups"][join["id"]]
    assert error in row["assembly_error"]
    assert "stock_out_volume_mm3" not in row


@pytest.mark.parametrize("method", ["retaining_compound", "silver_braze", "press", "weld"])
def test_every_native_joint_method_requires_known_process_text(engine, multi_solids, method):
    if method == "weld":
        job = _surface_job(engine, multi_solids["blocks"])
        components = job["stock"]["components"]
        components["left"]["length_mm"] = 20
        components["right"].update(length_mm=20, origin_mm=[20, 0, 0])
        job["setups"][0]["joint"]["interfaces"][0]["at_mm"][0] = 20
    else:
        job = _joint_job(engine, multi_solids["joined"], interference=method == "press")
        if method == "retaining_compound":
            job["setups"][-1]["joint"].update(
                method=method, cure_time_min=30, surface_prep="degrease and dry"
            )
    joint = job["setups"][-1]["joint"]
    joint.update(
        process="unknown",
        reason="joint geometry facts are unknown",
        process_reason="another process fact is unknown",
    )
    row = engine.run(job)["setups"]["join"]
    assert "joint process must be known nonempty text" in row["assembly_error"]
    assert "stock_out_volume_mm3" not in row


def test_incompatible_fit_does_not_invalidate_correct_component_preparation(engine, multi_solids):
    job = _joint_job(engine, multi_solids["joined"])
    joint = job["setups"][-1]["joint"]
    joint.update(
        band_mm=[0.1, 0.3],
        fit_error="socket/spigot fit fails at a worst-case diameter extreme",
    )
    facts = engine.run(job)
    assert facts["setups"]["socket-cut"]["completed_joint_features"] == ["socket"]
    assert facts["setups"]["socket-cut"]["stock_out_volume_mm3"] == pytest.approx(
        math.pi * (100 - 25) * 10, abs=2e-3
    )
    assert facts["setups"]["spigot-cut"]["completed_joint_features"] == ["spigot"]
    assert facts["setups"]["spigot-cut"]["stock_out_volume_mm3"] == pytest.approx(
        math.pi * 4.9**2 * 20, abs=2e-3
    )
    row = facts["setups"]["join"]
    assert "worst-case diameter" in row["assembly_error"]
    assert "stock_out_volume_mm3" not in row


def test_rotary_transient_bore_is_named_debt_not_fictional_coverage(engine, multi_solids):
    job = _joint_job(engine, multi_solids["joined"])
    job["setups"][0]["ops"][0]["approach"] = "rotary"
    facts = engine.run(job)
    assert facts["status"] == "ok", facts
    detail = facts["ops"]["socket-cut:10"]
    assert "rotary machining on plan.joint_features.socket is not modelled" in detail["reason"]
    assert detail["tool_hits"] == detail["holder_hits"] == detail["corner_radii_mm"] == "unknown"
    assert "stock_out_volume_mm3" not in facts["setups"]["socket-cut"]
    assert "stock_out_volume_mm3" not in facts["setups"]["join"]


@pytest.mark.parametrize("cut_depth", [10.0, 11.0], ids=["closed-cap", "open-cap-before-wall"])
def test_finite_through_cap_checks_do_not_search_distant_axial_material(
    engine, multi_solids, cut_depth
):
    job = _multi_job(engine, multi_solids["multi"])
    job["stock"]["components"]["body"]["length_mm"] = 15
    job["setups"][0]["ops"][0]["joint_cut"]["depth_mm"] = cut_depth
    facts = engine.run(job)
    prepared = facts["setups"]["body-bore"]
    if cut_depth == 10.0:
        assert "blocked axial end" in facts["ops"]["body-bore:10"]["joint_error"]
        assert "stock_out_volume_mm3" not in prepared
    else:
        assert prepared["completed_joint_features"] == ["body-socket"]
        assert prepared["stock_out_volume_mm3"] == pytest.approx(
            math.pi * (100 * 15 - 25 * 11), abs=2e-3
        )
        assert "overlap" in facts["setups"]["join-sleeve"]["assembly_error"]
    assert "stock_out_volume_mm3" not in facts["setups"]["join-sleeve"]
    assert "stock_out_volume_mm3" not in facts["setups"]["join-shaft"]


def test_later_bad_fit_does_not_demand_future_component_material_in_prior_assembly(
    engine, multi_solids
):
    job = _multi_job(engine, multi_solids["multi"])
    job["setups"][-1]["joint"].update(
        band_mm=[0.1, 0.3],
        fit_error="socket/spigot fit fails at a worst-case diameter extreme",
    )
    facts = engine.run(job)
    first = facts["setups"]["join-sleeve"]
    assert first["stock_out_volume_mm3"] == pytest.approx(
        math.pi * (100 * 10 + 4.9**2 * 10 - 3**2 * 20), abs=2e-3
    )
    assert "assembly_error" not in first
    later = facts["setups"]["join-shaft"]
    assert "worst-case diameter" in later["assembly_error"]
    assert "stock_out_volume_mm3" not in later


def test_small_through_socket_detects_a_real_closed_cap_by_contact_area(engine, multi_solids):
    job = _multi_job(engine, multi_solids["multi"])
    job["stock"]["components"]["body"]["length_mm"] = 15
    job["joint_features"]["body-socket"].update(nominal_dia_mm=1.0, dia_mm=[1.0, 1.0])
    setup = job["setups"][0]
    setup["ops"][0]["joint_cut"].update(
        nominal_dia_mm=1.0, diameter_mm=1.0, dia_mm=[1.0, 1.0]
    )
    setup["ops"][0]["radius_mm"] = 0.2
    job["setups"] = [setup]
    facts = engine.run(job)
    assert facts["status"] == "ok", facts
    assert "blocked axial end" in facts["ops"]["body-bore:10"]["joint_error"]
    assert "stock_out_volume_mm3" not in facts["setups"]["body-bore"]
