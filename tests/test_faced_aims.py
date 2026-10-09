"""A plan aim naming a ``face`` holds a faced length at a stated value inside its band.

The rocker arm's hub length (drawing 7.0565-7.1065, aimed 7.080) is the case: S1 faces
the upper hub, S2 zeroes so the lower hub lands at the aim. With the kernel cutting the
CAD hub, S2's frame on the aimed face put the CAD face 0.0235 outside the op's removal
box and S2's incoming top disagreed with what S1 left (the review's Z4.475 against
Z4.445). The kernel now cuts the part the aim makes, so S1's output, S2's entry, zero and
every later setup stand on one face position. FreeCAD-backed tests run the engine under
``freecadcmd`` and skip without it.
"""

import subprocess

import pytest
from test_kernel_geometry import Engine, _vise

from prechips.inputs import BadInput, load_bundle
from prechips.kernel import build_job, engine_job
from prechips.rules.coordinates import faced_aims
from prechips.sheet import _Traveler

FEATURES = """part = "plate"
units = "mm"
precision = 2
[frames.model]
origin = [0.0, 0.0, 0.0]
x = [1.0, 0.0, 0.0]
y = [0.0, 1.0, 0.0]
z = [0.0, 0.0, 1.0]
binding = "measured"
[features.plate_faces]
kind = "face"
frame = "model"
requirements = ["length"]
length = [10.0, 10.05]
length_nominal = 10.0
upper_z = 10.0
lower_z = 0.0
faces = ["#1/ADVANCED_FACE[1]/TOP", "#2/ADVANCED_FACE[2]/BOTTOM"]
"""
BOTTOM = "#2/ADVANCED_FACE[2]/BOTTOM"


def _write(tmp_path, aim, op="finish_face", features=FEATURES, faces=(BOTTOM,)):
    (tmp_path / "inventory.toml").write_text('[machines.mill]\nkind = "mill"\n', encoding="utf-8")
    (tmp_path / "cutting.toml").write_text("", encoding="utf-8")
    (tmp_path / "features.toml").write_text(features, encoding="utf-8")
    claims = ""
    if isinstance(faces, tuple | list):
        claims = f"faces = {list(faces)!r}\n"
    elif faces is not None:
        claims = f'faces = "{faces}"\n'
    (tmp_path / "plan.toml").write_text(
        'part = "plate"\nfeatures = "features.toml"\n'
        '[paths]\ninventory = "inventory.toml"\ncutting_data = "cutting.toml"\n'
        f"{aim}"
        '[[setups]]\nid = "S2"\nmachine = "mill"\nframe = "model"\n'
        f'[[setups.ops]]\nop = 10\ndo = "{op}"\nfeature = "plate_faces"\n' + claims,
        encoding="utf-8",
    )
    return tmp_path / "plan.toml"


def _aim(value, face=BOTTOM, name="plate_faces", requirement="length"):
    return (
        f'[aims.{name}]\nrequirement = "{requirement}"\nvalue_mm = {value}\n'
        f'reason = "AUTHOR\'S CHOICE: probe"\nface = "{face}"\n'
    )


def test_a_faced_aim_moves_its_face_by_the_aim_less_the_planes_separation(tmp_path):
    bundle = load_bundle(_write(tmp_path, _aim(10.03)))
    (record,) = faced_aims(bundle)
    assert record == {
        "feature": "plate_faces",
        "face": BOTTOM,
        "requirement": "length",
        "axis": [0.0, 0.0, 1.0],
        "lower_mm": 0.0,
        "upper_mm": 10.0,
        "value_mm": 10.03,
        "band_mm": [10.0, 10.05],
        "delta_mm": 0.03,
    }
    # The kernel cuts that part: the aim reaches its job, and its geometry cache key.
    assert engine_job(build_job(bundle))["aimed_faces"] == [record]


@pytest.mark.parametrize(
    "faces",
    [None, ["#1/ADVANCED_FACE[1]/TOP"], ["#1/ADVANCED_FACE[1]/TOP", "unknown"]],
)
def test_a_faced_move_requires_a_resolved_claim_or_feature_default(tmp_path, faces):
    top = "#1/ADVANCED_FACE[1]/TOP"
    bundle = load_bundle(_write(tmp_path, _aim(10.03, face=top), faces=faces))
    (record,) = faced_aims(bundle)
    assert record["face"] == top and record["value_mm"] == 10.03
    assert record["delta_mm"] == pytest.approx(0.03)
    assert engine_job(build_job(bundle))["aimed_faces"] == [record]


@pytest.mark.parametrize(
    "faces",
    [[BOTTOM], "unknown", ["unknown"], []],
)
def test_loading_refuses_a_faced_move_without_a_resolved_claim(tmp_path, faces):
    with pytest.raises(BadInput):
        load_bundle(_write(tmp_path, _aim(10.03, face="#1/ADVANCED_FACE[1]/TOP"), faces=faces))


def test_mixed_face_debt_keeps_the_faced_aim_on_the_last_claiming_op(tmp_path):
    top = "#1/ADVANCED_FACE[1]/TOP"
    path = _write(tmp_path, _aim(10.03, face=top), faces=[top])
    with path.open("a", encoding="utf-8") as stream:
        stream.write(
            '[[setups.ops]]\nop = 20\ndo = "finish_face"\nfeature = "plate_faces"\n'
            f'faces = ["{top}", "unknown"]\n'
        )
    bundle = load_bundle(path)
    setup = bundle.plan["setups"][0]
    early, late = setup["ops"]
    traveler = _Traveler(bundle, [], {}, None)
    assert traveler.faced_aim_note(setup, early) is None
    note = traveler.faced_aim_note(setup, late)
    assert note is not None
    assert "10.03" in note and "10.00" in note and "10.05" in note
    assert "probe" in note


@pytest.mark.parametrize("value", [10.051, 9.999])
def test_loading_refuses_a_faced_aim_outside_its_printed_band(tmp_path, value):
    with pytest.raises(BadInput, match="outside its printed band"):
        load_bundle(_write(tmp_path, _aim(value)))


@pytest.mark.parametrize(
    "aim, op, features, match",
    [
        (_aim(10.03, face="#9/ADVANCED_FACE[9]/OTHER"), "finish_face", FEATURES, "not one of"),
        (_aim(10.03), "finish_profile", FEATURES, "no facing op claims"),
        (_aim(10.03), "finish_face", FEATURES.replace("lower_z = 0.0\n", ""), "no lower_z"),
    ],
)
def test_loading_refuses_a_faced_aim_that_moves_no_faced_plane(tmp_path, aim, op, features, match):
    with pytest.raises(BadInput, match=match):
        load_bundle(_write(tmp_path, aim, op, features))


def test_a_nominal_that_is_not_the_planes_separation_moves_no_face(tmp_path):
    bundle = load_bundle(
        _write(tmp_path, _aim(10.03), features=FEATURES.replace("upper_z = 10.0", "upper_z = 9.0"))
    )
    (record,) = faced_aims(bundle)
    assert "delta_mm" not in record and "not the lower_z-upper_z separation" in record["reason"]


@pytest.mark.parametrize("band", ['"unknown"', '[10.0, "unknown"]'])
def test_a_faced_aim_without_a_known_band_moves_no_face(tmp_path, band):
    # No known band authorizes the move: the kernel leaves the part unknown (the reason).
    features = FEATURES.replace("length = [10.0, 10.05]", f"length = {band}")
    (record,) = faced_aims(load_bundle(_write(tmp_path, _aim(10.03), features=features)))
    assert "delta_mm" not in record and "no known printed band" in record["reason"]


def test_an_aim_without_a_face_never_reaches_the_kernel(tmp_path):
    aim = '[aims.plate_faces]\nrequirement = "length"\nvalue_mm = 10.03\nreason = "probe"\n'
    bundle = load_bundle(_write(tmp_path, aim))
    assert faced_aims(bundle) == []
    assert "aimed_faces" not in build_job(bundle)


# --------------------------------------------------------------------------- kernel

_AUTHOR = r"""
import sys
import FreeCAD, Part
V = FreeCAD.Vector
out = sys.argv[sys.argv.index("--") + 1]
# A 60x40 plate 10 thick (z 0..10) with a 6 mm bore through it at x 30 y 20.
plate = Part.makeBox(60, 40, 10).cut(Part.makeCylinder(3, 12, V(30, 20, -1)))
plate.exportStep(out + "/plate.step")
# The same plate with a 45 degree chamfer along the bottom of its y = 0 side.
edge = [e for e in plate.Edges if e.BoundBox.ZMax < 1e-9 and e.BoundBox.YMax < 1e-9][0]
plate.makeChamfer(1.0, [edge]).exportStep(out + "/chamfered.step")
# The rocker's hub through its strap: a Ø16 hub z -2..12 standing proud of both faces of a
# 60x40 strap z 0..10.
hub = Part.makeBox(60, 40, 10).fuse(Part.makeCylinder(8, 14, V(30, 20, -2)))
hub.removeSplitter().exportStep(out + "/hub.step")
"""
BLANK = {
    "shape": "box",
    "origin_mm": [0.0, 0.0, -2.0],
    "axis": [1.0, 0.0, 0.0],
    "section_axis": [0.0, 1.0, 0.0],
    "length_mm": 60.0,
    "section_mm": [40.0, 14.0],
}
# Frame A: origin on the upper face, Z up. Frame B: turned over about X, origin on the
# lower face where the aim puts it, Z up out of it.
TOP_FRAME = {"origin": [0.0, 0.0, 10.0], "x": [1, 0, 0], "y": [0, 1, 0], "z": [0, 0, 1]}


def _flipped(aim):
    return {"origin": [0.0, 0.0, 10.0 - aim], "x": [1, 0, 0], "y": [0, -1, 0], "z": [0, 0, -1]}


def _face_op(subject, feature, y):
    return {
        "subject": subject,
        "feature": feature,
        "do": "finish_face",
        "finishing": True,
        "radius_mm": 5.0,
        "flute_len_mm": 10.0,
        "oal_mm": 60.0,
        "projection_mm": 30.0,
        "holder_radius_mm": 10.0,
        "holder_gauge_len_mm": 30.0,
        "to_z": 0.0,
        "stock_removal_bounds": {"x": [-1.0, 61.0], "y": y, "z": [0.0, 5.0]},
    }


@pytest.fixture(scope="module")
def plates(tmp_path_factory, freecad_kernel):
    directory = tmp_path_factory.mktemp("faced-aim-solids")
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
    assert len(paths) == 3, process.stdout[-2000:] + process.stderr[-2000:]
    return paths


@pytest.fixture
def engine(tmp_path, freecad_kernel):
    return Engine(tmp_path, freecad_kernel)


def _held(setup, frame, feature, y):
    """One face op in a vise whose jaw tops stand about 2 mm below the faced Z0."""
    ops = [_face_op(f"{setup}:10", feature, y)]
    return {"id": setup, "frame": frame, "hold": _vise(8.0), "ops": ops}


def _flip_job(engine, step, aim, spec):
    top = engine.refs(step, (0, 0, 10), (60, 40, 10), kind="Plane")
    bottom = engine.refs(step, (0, 0, 0), (60, 40, 0), kind="Plane")
    assert len(top) == len(bottom) == 1
    job = engine.job(
        step,
        {"top": top, "bottom": bottom},
        [
            _held("S1", TOP_FRAME, "top", [-1.0, 41.0]),
            _held("S2", _flipped(aim), "bottom", [-41.0, 1.0]),
            _held("S3", TOP_FRAME, "top", [-1.0, 41.0]),
        ],
        stock=BLANK,
    )
    # S3 seats on the aimed face: the consistency rule reads its height from stock_faces_mm.
    job["setups"][2]["stock_features"] = ["bottom"]
    if spec is not None:
        job["aimed_faces"] = [{"feature": "plate_faces", "face": bottom[0], **spec}]
    return job


def _spec(delta):
    return {
        "axis": [0.0, 0.0, 1.0],
        "lower_mm": 0.0,
        "upper_mm": 10.0,
        "value_mm": round(10.0 + delta, 9),
        "band_mm": [9.95, 10.05],
        "delta_mm": delta,
    }


@pytest.mark.parametrize("length", [10.03, 9.97])
def test_every_setup_cuts_the_part_the_faced_aim_makes(engine, plates, length):
    delta = round(length - 10.0, 9)
    result = engine.run(_flip_job(engine, plates["plate"], length, _spec(delta)))
    assert result["status"] == "ok", result
    assert result["aimed_faces"][0]["plane_mm"] == [0.0, -delta]
    # The STEP stays as exported.
    assert result["bbox_mm"] == [0.0, 0.0, 0.0, 60.0, 40.0, 10.0]
    s1, s2, s3 = (result["setups"][sid] for sid in ("S1", "S2", "S3"))
    # S1 faces the upper face: 12 mm of the 14 mm blank go over to S2.
    assert s1["stock_bbox_mm"][2:6:3] == [-12.0, 2.0]
    # S2's frame stands on the aimed lower face: it receives that 12 mm with its top at
    # 12 - length, its op clears down to Z0 and S3 receives the aimed length.
    assert s2["stock_bbox_mm"][2:6:3] == pytest.approx([-length, 12.0 - length])
    assert "stock_reason" not in s3, s3
    assert s3["stock_bbox_mm"][2:6:3] == pytest.approx([-length, 0.0])
    # No hole op has bored it yet: the whole 60 x 40 section stands the aimed length.
    assert s3["stock_volume_mm3"] == pytest.approx(60 * 40 * length, rel=1e-6)
    # The face op at Z0 stands on the aimed face, inside the stock it removes.
    assert result["ops"]["S2:10"]["tool_hits"] == 0
    # The seated face's height, which consistency compares with stock_state.bottom_z, is
    # the aimed one: frame, zero, stock and the stated bottom stand on one face position.
    seated = s3["stock_faces_mm"]["bottom"]["down"]
    assert seated == {"face_z": pytest.approx(-length), "stock_z": pytest.approx(-length)}


def test_without_the_aim_the_cad_face_lies_outside_the_aimed_removal_box(engine, plates):
    # The review's case: the frame and zero stand on the aim, the kernel on the CAD face.
    result = engine.run(_flip_job(engine, plates["plate"], 10.03, None))
    assert "lie outside its stock_removal_bounds" in result["setups"]["S3"]["stock_reason"]
    # Its cut is unknown, so the stock it would remove stands in the cutter's way.
    assert result["ops"]["S2:10"]["tool_hits"] > 0


def test_an_aim_at_the_nominal_leaves_the_face_where_it_stands(engine, plates):
    result = engine.run(_flip_job(engine, plates["plate"], 10.0, _spec(0.0)))
    assert result["status"] == "ok", result
    assert result["aimed_faces"][0]["plane_mm"] == [0.0, 0.0]
    assert result["setups"]["S3"]["stock_bbox_mm"][2:6:3] == pytest.approx([-10.0, 0.0])


def test_aims_moving_each_others_other_end_leave_the_part_unknown(engine, plates):
    # One thickness under two names, each aiming one of its faces at 10.03: the part the
    # two moves make is 10.06 thick, which meets neither aim.
    job = _flip_job(engine, plates["plate"], 10.03, _spec(0.03))
    top = engine.refs(plates["plate"], (0, 0, 10), (60, 40, 10), kind="Plane")[0]
    job["aimed_faces"].append({"feature": "other_faces", "face": top, **_spec(0.03)})
    result = engine.run(job)
    assert result["status"] == "unknown", result
    assert "the other end of its length, from 10.0 to 10.03 mm" in result["reason"], result


@pytest.mark.parametrize("order", [1, -1])
def test_hub_and_strap_aims_each_measure_their_own_length(engine, plates, order):
    # The rocker's pair: the hub length and the strap thickness each move their own lower
    # face; neither moves the other's face or upper end, so both lengths hold together.
    step = plates["hub"]
    (hub,) = engine.refs(step, (22, 12, -2), (38, 28, -2), kind="Plane")
    (strap,) = engine.refs(step, (0, 0, 0), (60, 40, 0), kind="Plane")
    aims = [
        {
            "feature": "hub",
            "face": hub,
            **_spec(0.03),
            "lower_mm": -2.0,
            "upper_mm": 12.0,
            "value_mm": 14.03,
            "band_mm": [14.0, 14.05],
        },
        {"feature": "strap", "face": strap, **_spec(0.0235), "value_mm": 10.0235},
    ][::order]
    job = engine.job(step, {"hub": [hub], "strap": [strap]})
    job["aimed_faces"] = aims
    result = engine.run(job)
    assert result["status"] == "ok", result
    planes = {fact["feature"]: fact["plane_mm"] for fact in result["aimed_faces"]}
    assert planes == {"hub": [-2.0, -2.03], "strap": [0.0, -0.0235]}


@pytest.mark.parametrize(
    "step, spec, why",
    [
        ("plate", {**_spec(0.03), "lower_mm": 0.5}, "is not its lower plane"),
        ("plate", {**_spec(0.03), "axis": [1.0, 0.0, 0.0]}, "not a plane square"),
        ("chamfered", _spec(0.03), "does not run square to it"),
        ("plate", {"reason": "features.plate_faces.lower_z/upper_z are not two"}, "not two"),
    ],
)
def test_an_aim_the_kernel_cannot_place_leaves_the_part_unknown(engine, plates, step, spec, why):
    result = engine.run(_flip_job(engine, plates[step], 10.03, spec))
    assert result["status"] == "unknown" and why in result["reason"], result
