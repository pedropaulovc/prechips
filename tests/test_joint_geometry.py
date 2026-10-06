"""Real FreeCAD boundaries for authored transient cylinders and two-piece joints."""

import copy
import hashlib
import math
import subprocess

import pytest
from test_kernel_geometry import IDENTITY, Engine, _op
from test_turning_geometry import _turn

from prechips import kernel
from prechips.inputs import Bundle
from prechips.rules.resolution import MANUAL

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
boss = Part.makeCylinder(4.9, 20)
save("joined", body.fuse(boss).cut(Part.makeCylinder(2, 20)))
flange = Part.makeCylinder(8, 5, V(0, 0, 20))
save("captive", body.multiFuse([boss, flange]).cut(Part.makeCylinder(2, 25)))
save("butt", Part.makeBox(20, 10, 10))
"""


@pytest.fixture(scope="module")
def joint_solids(tmp_path_factory, freecad_kernel):
    directory = tmp_path_factory.mktemp("joint-solids")
    script = directory / "author.py"
    script.write_text(_AUTHOR, encoding="utf-8")
    process = subprocess.run(
        [freecad_kernel, str(script), "--", str(directory)],
        capture_output=True,
        text=True,
        errors="replace",
        timeout=300,
    )
    paths = {path.stem: path for path in directory.glob("*.step")}
    assert set(paths) == {"joined", "captive", "butt"}, (
        process.stdout[-2000:] + process.stderr[-2000:]
    )
    return paths


@pytest.fixture
def engine(tmp_path, freecad_kernel):
    return Engine(tmp_path, freecad_kernel)


def _bar(diameter, length, at=(0, 0, 0)):
    return {
        "shape": "round",
        "dia_mm": diameter,
        "length_mm": length,
        "origin_mm": list(at),
        "axis": [0, 0, 1],
    }


def _primitive(name, kind, component, diameter, band, depth):
    return {
        "label": "plan.joint_features." + name,
        "kind": kind,
        "component": component,
        "at_mm": [0, 0, 0],
        "axis": [0, 0, 1],
        "nominal_dia_mm": diameter,
        "dia_mm": list(band),
        "depth_mm": depth,
        "thru": True,
    }


def _joint_job(engine, step, *, interference=False):
    socket = _primitive(
        "socket",
        "cylinder_bore",
        "body",
        9.6 if interference else 10.0,
        (9.6, 9.7) if interference else (10.0, 10.1),
        10.0,
    )
    spigot = _primitive(
        "spigot", "cylinder_spigot", "boss", 9.8, (9.8, 9.9) if interference else (9.7, 9.8), 20.0
    )
    socket_cut = {
        "joint_feature": "socket",
        "action": "bore",
        "finishing": True,
        "completes": True,
        **socket,
        "diameter_mm": socket["nominal_dia_mm"],
    }
    spigot_cut = {
        "joint_feature": "spigot",
        "action": "finish_turn",
        "finishing": True,
        "completes": True,
        **spigot,
        "diameter_mm": 9.8,
    }
    reverse = {"origin": [0, 0, 0], "x": [1, 0, 0], "y": [0, -1, 0], "z": [0, 0, -1]}
    setups = [
        {
            "id": "socket-cut",
            "stock_in": "stock.body",
            "frame": reverse,
            "hold": {"reason": "fixture not part of this stock-boundary probe"},
            "ops": [
                {**_op("socket-cut:10", "socket", 2, 20, 50), "do": "bore", "joint_cut": socket_cut}
            ],
        },
        {
            "id": "spigot-cut",
            "stock_in": "stock.boss",
            "frame": IDENTITY,
            "hold": {"reason": "fixture not part of this stock-boundary probe"},
            "ops": [_turn("spigot-cut:10", "spigot", joint_cut=spigot_cut)],
        },
        {
            "id": "join",
            "stock_in": ["socket-cut", "spigot-cut"],
            "frame": IDENTITY,
            "hold": {"reason": "joining fixture not drawn"},
            "ops": [],
            "joint": {
                "kind": "cylindrical",
                "refs": ["socket-cut", "spigot-cut"],
                "socket": "socket",
                "spigot": "spigot",
                "socket_ref": "socket-cut",
                "spigot_ref": "spigot-cut",
                "fit": "interference" if interference else "clearance",
                "method": "press" if interference else "silver_braze",
                "process": "declared joining process",
                "band_mm": [0.1, 0.3] if interference else [0.2, 0.4],
                "reason": None,
                "fit_error": None,
            },
        },
    ]
    job = engine.job(
        step, setups=setups, stock={"components": {"body": _bar(20, 10), "boss": _bar(12, 20)}}
    )
    job["joint_features"] = {"socket": socket, "spigot": spigot}
    return job


@pytest.mark.parametrize("interference", [False, True])
def test_worst_case_fit_limits_join_real_prepared_stock(engine, joint_solids, interference):
    job = _joint_job(engine, joint_solids["joined"], interference=interference)
    facts = engine.run(job)
    assert facts["status"] == "ok", facts
    rows = facts["setups"]
    assert rows["socket-cut"]["completed_joint_features"] == ["socket"]
    assert rows["spigot-cut"]["completed_joint_features"] == ["spigot"]
    # The boss blank overlaps body-owned finished material at r=4.9..6, z=0..10.
    # Its sacrificial annulus must still be turned off on the separate boss branch.
    assert rows["spigot-cut"]["stock_out_volume_mm3"] == pytest.approx(
        math.pi * 4.9**2 * 20, abs=1e-3
    )
    assert rows["join"]["stock_out_volume_mm3"] == pytest.approx(
        math.pi * (100 * 10 + 4.9**2 * 10), abs=1e-3
    )
    assert "assembly_error" not in rows["join"]
    # Analytic claims have labels, but are never added to the imported face inventory.
    assert all(face["index"] >= len(facts["faces"]) for face in facts["transient_faces"])
    assert facts["ops"]["socket-cut:10"]["sample_count"] > 0
    assert facts["ops"]["spigot-cut:10"]["approach"] == "turning"
    assert facts["ops"]["socket-cut:10"]["corner_radii_mm"] == []
    assert facts["ops"]["spigot-cut:10"]["corner_radii_mm"] == []


def test_ordinary_prejoin_turning_uses_component_owned_protection(engine, joint_solids):
    step = joint_solids["joined"]
    job = _joint_job(engine, step)
    job["features"]["outer"] = engine.refs(step, (-4.9, -4.9, 10), (4.9, 4.9, 20), kind="Cylinder")
    ordinary = {
        "id": "ordinary-turn",
        "stock_in": "stock.boss",
        "frame": IDENTITY,
        "hold": {"reason": "fixture not part of this stock-boundary probe"},
        "ops": [_turn("ordinary-turn:10", "outer", z_from=0.0, z_to=20.0)],
    }
    job["setups"].insert(1, ordinary)
    job["setups"][2]["stock_in"] = "ordinary-turn"
    facts = engine.run(job)
    assert facts["setups"]["ordinary-turn"]["stock_out_volume_mm3"] == pytest.approx(
        math.pi * 4.9**2 * 20, abs=1e-3
    )
    assert "assembly_error" not in facts["setups"]["join"]


def test_join_backstop_refuses_lost_final_material_outside_finite_spigot(engine, joint_solids):
    step = joint_solids["joined"]
    job = _joint_job(engine, step)
    job["joint_features"]["spigot"]["depth_mm"] = 10.0
    job["setups"][1]["ops"][0]["joint_cut"].update(depth_mm=10.0, z_from=0.0, z_to=20.0)
    job["features"]["top"] = engine.refs(step, (-4.9, -4.9, 20), (4.9, 4.9, 20), kind="Plane")
    face = {
        "id": "lost-cap",
        "stock_in": "spigot-cut",
        "frame": IDENTITY,
        "hold": {"reason": "fixture not part of this stock-boundary probe"},
        "ops": [
            {
                **_op("lost-cap:10", "top", 1, 25, 50),
                "do": "face",
                "to_z": 15.0,
                "stock_removal_bounds": {"x": [-6, 6], "y": [-6, 6], "z": [15, 20]},
            }
        ],
    }
    job["setups"].insert(2, face)
    join = job["setups"][3]
    join["stock_in"][1] = "lost-cap"
    join["joint"].update(spigot_ref="lost-cap", refs=list(join["stock_in"]))
    intact = copy.deepcopy(job)
    intact["setups"][2]["ops"][0]["to_z"] = 20.0
    intact["setups"][2]["ops"][0].pop("stock_removal_bounds")
    supplied = engine.run(intact)["setups"]["join"]
    assert supplied["stock_out_volume_mm3"] == pytest.approx(
        math.pi * (100 * 10 + 4.9**2 * 10), abs=1e-3
    )
    facts = engine.run(job)
    cap = facts["setups"]["lost-cap"]
    # Preparation remains intact at z=0..10, but z=15..20 finished boss material
    # has been faced away outside that finite protected spigot cylinder.
    assert cap["completed_joint_features"] == ["spigot"]
    assert cap["stock_out_volume_mm3"] == pytest.approx(math.pi * 4.9**2 * 15, abs=1e-3)
    assert "assembly_error" in facts["setups"]["join"]
    assert "stock_out_volume_mm3" not in facts["setups"]["join"]
    assert "render_png_base64" not in facts["setups"]["join"]


def test_declared_cap_runout_removes_real_transient_shoulder_corner(engine, joint_solids):
    job = _joint_job(engine, joint_solids["joined"])
    job["stock"]["components"]["boss"]["length_mm"] = 22.0
    without_runout = engine.run(job)["ops"]["spigot-cut:10"]
    assert without_runout["corner_radii_mm"] == "unknown"
    job["setups"][1]["ops"][0]["joint_cut"].update(z_from=0.0, z_to=21.0)
    with_runout = engine.run(job)["ops"]["spigot-cut:10"]
    assert with_runout["corner_radii_mm"] == []


def test_reversed_spigot_runout_uses_prior_facing_to_clear_start_shoulder(engine, joint_solids):
    step = joint_solids["joined"]
    job = _joint_job(engine, step)
    job["stock"]["components"]["boss"].update(origin_mm=[0, 0, -6], length_mm=28)
    job["features"]["base"] = engine.refs(step, (-10, -10, 0), (10, 10, 0), kind="Plane")
    setup = job["setups"][1]
    setup["frame"] = {
        "origin": [0, 0, 0],
        "x": [1, 0, 0],
        "y": [0, -1, 0],
        "z": [0, 0, -1],
    }
    setup["ops"][0]["joint_cut"].update(z_from=0.0, z_to=-21.0)
    retained = engine.run(job)["ops"]["spigot-cut:10"]
    assert retained["corner_radii_mm"] == "unknown"
    setup["ops"].insert(0, _turn("spigot-cut:5", "base", to_z=0.0))
    facts = engine.run(job)
    assert facts["ops"]["spigot-cut:10"]["corner_radii_mm"] == []
    assert facts["setups"]["spigot-cut"]["completed_joint_features"] == ["spigot"]


def test_blind_transient_floor_keeps_specific_tool_edge_debt(engine, joint_solids):
    job = _joint_job(engine, joint_solids["joined"])
    job["joint_features"]["socket"].update(depth_mm=5.0, thru=False)
    job["setups"][0]["ops"][0]["joint_cut"].update(depth_mm=5.0, thru=False)
    detail = engine.run(job)["ops"]["socket-cut:10"]
    assert detail["corner_radii_mm"] == "unknown"


def test_incompatible_worst_case_band_withholds_join(engine, joint_solids):
    job = _joint_job(engine, joint_solids["joined"])
    job["setups"][2]["joint"]["band_mm"] = [0.1, 0.3]
    joined = engine.run(job)["setups"]["join"]
    assert "assembly_error" in joined
    assert "stock_out_volume_mm3" not in joined
    assert "render_png_base64" not in joined


@pytest.mark.parametrize("interference", [False, True])
def test_prepared_blind_socket_refuses_spigot_bulk_beyond_engagement(
    engine, joint_solids, interference
):
    job = _joint_job(engine, joint_solids["joined"], interference=interference)
    job["joint_features"]["socket"].update(depth_mm=5.0, thru=False)
    job["setups"][0]["ops"][0]["joint_cut"].update(depth_mm=5.0, thru=False)
    facts = engine.run(job)
    assert facts["setups"]["socket-cut"]["completed_joint_features"] == ["socket"]
    assert facts["setups"]["spigot-cut"]["completed_joint_features"] == ["spigot"]
    joined = facts["setups"]["join"]
    assert "assembly_error" in joined
    assert "stock_out_volume_mm3" not in joined
    assert "render_png_base64" not in joined


def test_socket_overdepth_outside_finite_engagement_is_protected(engine, joint_solids):
    job = _joint_job(engine, joint_solids["joined"])
    job["joint_features"]["socket"]["depth_mm"] = 5.0
    cut = job["setups"][0]["ops"][0]["joint_cut"]
    cut["depth_mm"] = 5.0
    cut["op_depth_mm"] = 10.0
    facts = engine.run(job)
    assert "joint_error" in facts["ops"]["socket-cut:10"]
    assert "stock_out_volume_mm3" not in facts["setups"]["socket-cut"]
    assert "stock_out_volume_mm3" not in facts["setups"]["join"]


@pytest.mark.parametrize("which", [0, 1])
def test_joint_declaration_cannot_substitute_for_missing_preparation(engine, joint_solids, which):
    job = _joint_job(engine, joint_solids["joined"])
    job["setups"][which]["ops"] = []
    joined = engine.run(job)["setups"]["join"]
    assert "assembly_error" in joined
    assert "stock_out_volume_mm3" not in joined


def test_preparation_on_parallel_branch_does_not_authorize_received_blank(engine, joint_solids):
    job = _joint_job(engine, joint_solids["joined"])
    fork = {**copy.deepcopy(job["setups"][0]), "id": "body-fork", "ops": []}
    job["setups"].insert(2, fork)
    join = job["setups"][3]
    join["stock_in"][0] = "body-fork"
    join["joint"]["socket_ref"] = "body-fork"
    join["joint"]["refs"] = list(join["stock_in"])
    facts = engine.run(job)
    assert facts["setups"]["socket-cut"]["completed_joint_features"] == ["socket"]
    assert "assembly_error" in facts["setups"]["join"]


def _bore_setup(stock_in, subject="final-bore"):
    return {
        "id": subject,
        "stock_in": stock_in,
        "frame": {**IDENTITY, "origin": [0, 0, 20]},
        "hold": {"reason": "fixture not part of this stock-boundary probe"},
        "ops": [{**_op(subject + ":10", "final-bore", 2, 25, 50), "do": "bore"}],
    }


def test_final_step_bore_removes_solid_core_after_join(engine, joint_solids):
    step = joint_solids["joined"]
    job = _joint_job(engine, step)
    job["features"]["final-bore"] = engine.refs(step, (-2, -2, 0), (2, 2, 20), kind="Cylinder")
    job["setups"].append(_bore_setup("join"))
    facts = engine.run(job)
    joined = facts["setups"]["join"]["stock_out_volume_mm3"]
    bored = facts["setups"]["final-bore"]["stock_out_volume_mm3"]
    assert joined - bored == pytest.approx(math.pi * 2**2 * 20, abs=2e-3)
    assert bored == pytest.approx(math.pi * (100 * 10 + 4.9**2 * 10 - 2**2 * 20), abs=2e-3)


def test_intentional_final_bore_preserves_spigot_interface_before_join(engine, joint_solids):
    step = joint_solids["joined"]
    job = _joint_job(engine, step)
    job["features"]["final-bore"] = engine.refs(step, (-2, -2, 0), (2, 2, 20), kind="Cylinder")
    job["setups"].insert(2, _bore_setup("spigot-cut", "damaged-spigot"))
    join = job["setups"][3]
    join["stock_in"][1] = "damaged-spigot"
    join["joint"]["spigot_ref"] = "damaged-spigot"
    join["joint"]["refs"] = list(join["stock_in"])
    facts = engine.run(job)
    assert facts["setups"]["damaged-spigot"]["completed_joint_features"] == ["spigot"]
    joined = facts["setups"]["join"]
    assert "assembly_error" not in joined
    assert joined["stock_out_volume_mm3"] == pytest.approx(
        math.pi * (100 * 10 + 4.9**2 * 10 - 2**2 * 20), abs=2e-3
    )


def test_captive_shoulder_refuses_straight_axis_insertion(engine, joint_solids):
    job = _joint_job(engine, joint_solids["captive"])
    job["stock"]["components"]["boss"] = _bar(16, 25)
    joined = engine.run(job)["setups"]["join"]
    assert "assembly_error" in joined
    assert "stock_out_volume_mm3" not in joined


def _surface_job(engine, step):
    stock = {
        "components": {
            "left": {
                "shape": "box",
                "length_mm": 10,
                "section_mm": [10, 10],
                "origin_mm": [0, 0, 0],
                "axis": [1, 0, 0],
                "section_axis": [0, 1, 0],
            },
            "right": {
                "shape": "box",
                "length_mm": 10,
                "section_mm": [10, 10],
                "origin_mm": [10, 0, 0],
                "axis": [1, 0, 0],
                "section_axis": [0, 1, 0],
            },
        }
    }
    refs = ["stock.left", "stock.right"]
    setup = {
        "id": "join",
        "stock_in": refs,
        "frame": IDENTITY,
        "hold": {"reason": "joining fixture not drawn"},
        "ops": [],
        "joint": {
            "kind": "surface",
            "refs": refs,
            "negative_ref": refs[0],
            "positive_ref": refs[1],
            "method": "weld",
            "process": "declared welding process",
            "reason": None,
            "interfaces": [
                {"at_mm": [10, 5, 5], "normal": [1, 0, 0], "x": [0, 1, 0], "size_mm": [10, 10]}
            ],
        },
    }
    return engine.job(step, setups=[setup], stock=stock)


def test_surface_joint_requires_full_opposing_rectangle_contact(engine, joint_solids):
    job = _surface_job(engine, joint_solids["butt"])
    joined = engine.run(job)["setups"]["join"]
    assert joined["stock_out_volume_mm3"] == pytest.approx(2000.0)
    assert "assembly_error" not in joined
    job["setups"][0]["joint"]["interfaces"][0]["at_mm"][0] = 9.0
    refused = engine.run(job)["setups"]["join"]
    assert "assembly_error" in refused
    assert "stock_out_volume_mm3" not in refused


@pytest.mark.parametrize("height", [6.0, 10.0])
def test_surface_interface_preserves_both_authored_rectangle_extents(engine, joint_solids, height):
    job = _surface_job(engine, joint_solids["butt"])
    interface = job["setups"][0]["joint"]["interfaces"][0]
    interface["size_mm"] = [10.0, height]
    assert engine.run(job)["setups"]["join"]["stock_out_volume_mm3"] == pytest.approx(2000.0)
    # The full authored height now crosses z=0. A shortened second half-extent
    # would incorrectly keep the rectangle inside the finished solid.
    interface["at_mm"][2] = 2.0
    refused = engine.run(job)["setups"]["join"]
    assert "assembly_error" in refused
    assert "stock_out_volume_mm3" not in refused
    assert "render_png_base64" not in refused


def test_internal_surface_interface_refuses_positive_but_incomplete_contact(engine, joint_solids):
    job = _surface_job(engine, joint_solids["butt"])
    components = job["stock"]["components"]
    components["right"]["section_mm"] = [7, 10]
    # An unconsumed supply completes the overall raw envelope, not the received
    # right branch. Its material cannot certify this two-piece contact patch.
    components["unconsumed"] = {
        **components["right"],
        "section_mm": [3, 10],
        "origin_mm": [10, 7, 0],
    }
    refused = engine.run(job)["setups"]["join"]
    assert "assembly_error" in refused
    assert "stock_out_volume_mm3" not in refused
    assert "render_png_base64" not in refused


def test_surface_joint_refuses_undeclared_overlapping_bulk(engine, joint_solids):
    job = _surface_job(engine, joint_solids["butt"])
    job["stock"]["components"]["right"]["origin_mm"][0] = 9.0
    job["stock"]["components"]["right"]["length_mm"] = 11.0
    refused = engine.run(job)["setups"]["join"]
    assert "assembly_error" in refused
    assert "stock_out_volume_mm3" not in refused


@pytest.mark.parametrize(
    "invalid",
    [
        {"normal": [2, 0, 0]},
        {"x": [1, 0, 0]},
        {"negative_ref": "stock.right"},
    ],
)
def test_invalid_surface_interface_blocks_only_its_component_branches(
    engine, joint_solids, invalid
):
    job = _surface_job(engine, joint_solids["butt"])
    join = job["setups"][0]
    if "negative_ref" in invalid:
        join["joint"].update(invalid)
    else:
        join["joint"]["interfaces"][0].update(invalid)
    job["stock"]["components"]["independent"] = {
        **job["stock"]["components"]["left"],
        "length_mm": 20,
    }
    branch_setups = [
        {
            "id": name,
            "stock_in": "stock." + name,
            "frame": IDENTITY,
            "hold": {"reason": "fixture not part of this stock-boundary probe"},
            "ops": [],
        }
        for name in ("left", "right", "independent")
    ]
    job["setups"] = branch_setups + [join]
    facts = engine.run(job)
    assert facts["status"] == "ok", facts
    for name in ("left", "right", "join"):
        refused = facts["setups"][name]
        assert "assembly_error" in refused
        assert "stock_out_volume_mm3" not in refused
        assert "render_png_base64" not in refused
    independent = facts["setups"]["independent"]
    assert independent["stock_volume_mm3"] == pytest.approx(2000.0)
    assert independent["stock_out_volume_mm3"] == pytest.approx(2000.0)
    assert "assembly_error" not in independent


def test_unknown_nominal_never_fabricates_geometry_or_union(engine, joint_solids):
    job = _joint_job(engine, joint_solids["joined"])
    job["joint_features"]["spigot"]["nominal_dia_mm"] = "unknown"
    job["setups"][1]["ops"][0]["joint_cut"]["nominal_dia_mm"] = "unknown"
    job["setups"][1]["ops"][0]["joint_cut"]["diameter_mm"] = "unknown"
    facts = engine.run(job)
    joined = facts["setups"]["join"]
    assert "stock_out_volume_mm3" not in joined
    assert "assembly_error" not in joined


def test_unpaired_spigot_does_not_authorize_erasing_finished_component_core(engine, joint_solids):
    spec = _primitive("unpaired", "cylinder_spigot", "body", 10, (10, 10), 10)
    cut = {
        "joint_feature": "unpaired",
        "action": "finish_turn",
        "finishing": True,
        "completes": True,
        **spec,
        "diameter_mm": 10,
    }
    setup = {
        "id": "cut",
        "stock_in": "stock.body",
        "frame": IDENTITY,
        "hold": {"reason": "fixture not part of this stock-boundary probe"},
        "ops": [_turn("cut:10", "unpaired", joint_cut=cut)],
    }
    job = engine.job(
        joint_solids["joined"], setups=[setup], stock={"components": {"body": _bar(20, 20)}}
    )
    job["joint_features"] = {"unpaired": spec}
    facts = engine.run(job)
    assert "joint_error" in facts["ops"]["cut:10"]
    assert "stock_out_volume_mm3" not in facts["setups"]["cut"]


@pytest.mark.parametrize("action", sorted(MANUAL | {"transfer"}))
def test_manual_actions_neither_damage_stock_nor_prepare_socket(engine, joint_solids, action):
    step = joint_solids["joined"]
    digest = hashlib.sha256(step.read_bytes()).hexdigest()
    bundle = Bundle(
        plan={
            "stock": {
                "components": [
                    {"id": "body", **_bar(20, 10)},
                    {"id": "boss", **_bar(12, 20)},
                ]
            },
            "joint_features": {
                "socket": {
                    "kind": "cylinder_bore",
                    "component": "body",
                    "at": [0, 0, 0],
                    "axis": [0, 0, 1],
                    "nominal_dia": 10.0,
                    "dia": [10.0, 10.1],
                    "depth": 10.0,
                    "thru": True,
                    "cite": ["AUTHOR'S CHOICE: socket preparation"],
                }
            },
            "setups": [
                {
                    "id": "socket-cut",
                    "stock_in": "stock.body",
                    "frame": "A",
                    "ops": [{"op": 10, "feature": "socket", "do": action}],
                },
                {"id": "after-manual", "stock_in": "socket-cut", "frame": "A", "ops": []},
            ],
        },
        features={"units": "mm", "step_sha256": digest, "frames": {"A": IDENTITY}, "features": {}},
        inventory={},
        policy={},
        cutting_data={},
        paths={"step": step},
        hashes={"step": digest},
        root=step.parent,
    )
    facts = engine.run(kernel.build_job(bundle))
    assert facts["status"] == "ok", facts
    for name in ("socket-cut", "after-manual"):
        stock = facts["setups"][name]
        assert stock["stock_volume_mm3"] == pytest.approx(math.pi * 1000, abs=1e-3)
        assert stock["stock_out_volume_mm3"] == pytest.approx(math.pi * 1000, abs=1e-3)
        assert stock["completed_joint_features"] == []


def test_partial_spot_profile_does_not_claim_full_through_cylinder(engine, joint_solids):
    job = _joint_job(engine, joint_solids["joined"])
    op = job["setups"][0]["ops"][0]
    op["do"] = "spot"
    op["radius_mm"] = 5.0
    op["joint_cut"].update(
        action="spot",
        diameter_mm=10.0,
        op_depth_mm=2.0,
        completes=False,
        point_angle_deg=90.0,
    )
    facts = engine.run(job)
    stock = facts["setups"]["socket-cut"]
    assert math.pi * 1000 - stock["stock_out_volume_mm3"] == pytest.approx(
        math.pi * 2**2 * 2 / 3, abs=1e-3
    )
    assert stock["completed_joint_features"] == []
    assert facts["ops"]["socket-cut:10"]["min_hits"]["tool"] == 0
    assert "assembly_error" in facts["setups"]["join"]


@pytest.mark.parametrize("action", ["tap", "counterbore"])
def test_unsupported_joint_profiles_withhold_cut_and_join_geometry(engine, joint_solids, action):
    job = _joint_job(engine, joint_solids["joined"])
    op = job["setups"][0]["ops"][0]
    op["do"] = action
    op["radius_mm"] = 5.0
    # A finite depth and a purported complete cylinder cannot stand in for
    # an actual thread or the separate counterbore-step geometry.
    op["joint_cut"].update(action=action, op_depth_mm=2.0)
    facts = engine.run(job)
    assert facts["status"] == "ok", facts
    socket = facts["setups"]["socket-cut"]
    assert socket["stock_volume_mm3"] == pytest.approx(math.pi * 1000, abs=1e-3)
    assert "stock_out_volume_mm3" not in socket
    assert "completed_joint_features" not in socket
    detail = facts["ops"]["socket-cut:10"]
    assert detail["tool_hits"] == detail["holder_hits"] == detail["corner_radii_mm"] == "unknown"
    assert facts["setups"]["spigot-cut"]["completed_joint_features"] == ["spigot"]
    assert "stock_out_volume_mm3" not in facts["setups"]["join"]
    assert "assembly_error" not in facts["setups"]["join"]


def test_real_drill_point_below_socket_floor_cannot_cut_protected_material(engine, joint_solids):
    job = _joint_job(engine, joint_solids["joined"])
    job["joint_features"]["socket"].update(depth_mm=5.0, thru=False)
    job["joint_features"]["spigot"]["depth_mm"] = 5.0
    op = job["setups"][0]["ops"][0]
    op["do"] = "drill"
    op["joint_cut"].update(action="drill", depth_mm=5.0, thru=False, point_angle_deg=118.0)
    facts = engine.run(job)
    assert "joint_error" in facts["ops"]["socket-cut:10"]
    assert "stock_out_volume_mm3" not in facts["setups"]["socket-cut"]


def test_unknown_boss_stock_does_not_report_other_component_as_certain_obstacle(
    engine, joint_solids
):
    step = joint_solids["joined"]
    job = _joint_job(engine, step)
    job["features"]["outer"] = engine.refs(step, (-4.9, -4.9, 10), (4.9, 4.9, 20), kind="Cylinder")
    job["setups"][1]["frame"] = "unknown"
    probe = {
        "id": "probe",
        "stock_in": "spigot-cut",
        "frame": IDENTITY,
        "hold": {"reason": "fixture not part of this stock-boundary probe"},
        "ops": [_turn("probe:10", "outer", z_from=0.0, z_to=20.0)],
    }
    job["setups"].insert(2, probe)
    detail = engine.run(job)["ops"]["probe:10"]
    assert detail["min_hits"] == {"tool": 0, "holder": 0}
    assert detail["tool_hits"] == "unknown"
    assert detail["holder_hits"] == "unknown"


def test_overlapping_spigot_ownership_refuses_only_involved_branches(engine, joint_solids):
    job = _joint_job(engine, joint_solids["joined"])
    job["stock"]["components"].update(
        other_body=_bar(20, 10), other_boss=_bar(12, 20), independent=_bar(20, 20)
    )
    job["joint_features"].update(
        other_socket=_primitive("other_socket", "cylinder_bore", "other_body", 10, (10, 10.1), 10),
        other_spigot=_primitive(
            "other_spigot", "cylinder_spigot", "other_boss", 9.8, (9.7, 9.8), 20
        ),
    )
    other = copy.deepcopy(job["setups"][2])
    other.update(id="other-join", stock_in=["stock.other_body", "stock.other_boss"])
    other["joint"].update(
        socket="other_socket",
        spigot="other_spigot",
        socket_ref="stock.other_body",
        spigot_ref="stock.other_boss",
        refs=list(other["stock_in"]),
    )
    job["setups"].extend(
        [
            other,
            {
                "id": "independent",
                "stock_in": "stock.independent",
                "frame": IDENTITY,
                "hold": {"reason": "fixture not part of this stock-boundary probe"},
                "ops": [],
            },
        ]
    )
    facts = engine.run(job)
    assert facts["status"] == "ok"
    assert "assembly_error" in facts["setups"]["socket-cut"]
    assert "stock_out_volume_mm3" not in facts["setups"]["socket-cut"]
    assert facts["setups"]["independent"]["stock_out_volume_mm3"] == pytest.approx(
        math.pi * 2000, abs=1e-3
    )


@pytest.mark.parametrize("from_positive_cap", [False, True])
def test_through_drill_follows_setup_feed_from_either_authored_cylinder_cap(
    engine, joint_solids, from_positive_cap
):
    job = _joint_job(engine, joint_solids["joined"])
    setup = job["setups"][0]
    if from_positive_cap:
        setup["frame"] = IDENTITY
    op = setup["ops"][0]
    op["do"] = "drill"
    op["radius_mm"] = 5.0
    op["joint_cut"].update(action="drill", point_angle_deg=118.0)
    facts = engine.run(job)
    assert facts["setups"]["socket-cut"]["stock_out_volume_mm3"] == pytest.approx(
        math.pi * 750, abs=1e-3
    )
    assert facts["setups"]["socket-cut"]["completed_joint_features"] == ["socket"]
    assert "assembly_error" not in facts["setups"]["join"]


def test_unknown_drill_point_is_geometry_debt_not_an_invented_flat_cut(engine, joint_solids):
    job = _joint_job(engine, joint_solids["joined"])
    op = job["setups"][0]["ops"][0]
    op["do"] = "drill"
    op["joint_cut"].update(action="drill", point_angle_deg="unknown")
    facts = engine.run(job)
    assert "stock_out_volume_mm3" not in facts["setups"]["socket-cut"]
    assert "stock_out_volume_mm3" not in facts["setups"]["join"]
