"""Exact native per-operation TRANSIENT plane windows; no CAD identity changes."""

import os
import subprocess
from pathlib import Path
from textwrap import indent

from prechips import kernel


_PROBE = r'''
import importlib.util
import os
import FreeCAD as App
import Part

spec = importlib.util.spec_from_file_location("bounded_plane_job", os.environ["PLANE_KERNEL_SOURCE"])
job = importlib.util.module_from_spec(spec)
spec.loader.exec_module(job)
V = App.Vector

frames = [
    {"origin": [0, 0, 0], "x": [1, 0, 0], "y": [0, 1, 0], "z": [0, 0, 1]},
    {"origin": [13, -7, 9], "x": [0.8, 0.6, 0], "y": [-0.6, 0.8, 0], "z": [0, 0, 1]},
    {"origin": [-9, 3, 4], "x": [-1, 0, 0], "y": [0, 1, 0], "z": [0, 0, -1]},
]
for frame in frames:
    matrix, why = job._frame_matrix(frame)
    assert why is None
    inverse = matrix.inverse()
    stock = Part.makeBox(360, 16, 6, V(-180, 0, -3))
    stock.transformShape(inverse)
    for level, sign in [(1.2446, -1), (-1.2446, 1)]:
        at = inverse.multVec(V(0, 8, level))
        axis = inverse.multVec(V(0, 8, level + sign)) - at
        feature = {"kind": "end_face", "label": "TRANSIENT ear", "at_mm": list(at),
                   "axis": list(axis)}
        ops = []
        for lo, hi in [(-177, -150), (150, 177)]:
            ops.append({"process_cut": {"process_feature": "ears"},
                        "stock_removal_bounds": {"x": [lo, hi], "y": [0, 16],
                                                 "z": [level - 0.5, level + 0.5]}})
        ops.extend([
            {"process_cut": {"process_feature": "ears"}},
            {"process_cut": {"process_feature": "ears"},
             "stock_removal_bounds": {"x": [177, 150], "y": [0, 16], "z": [-3, 3]}},
            {"process_cut": {"process_feature": "ears"},
             "stock_removal_bounds": {"x": [190, 200], "y": [0, 16], "z": [-3, 3]}},
        ])
        owner = job._Job.__new__(job._Job)
        owner.job = {"process_features": {"ears": feature},
                     "setups": [{"frame": frame, "ops": ops}]}
        # A real finished-face index precedes every synthetic process face.
        owner.labels, owner.synthetic_faces = ["#finished"], []
        owner._init_process(stock)
        setup = job._Setup.__new__(job._Setup)
        setup.owner = owner
        windows = []
        for op, (lo, hi) in zip(ops[:2], [(-177, -150), (150, 177)]):
            indices = setup._indices(op)
            assert indices != job.UNKNOWN
            assert all(i > 0 and i in owner.process_planes for i in indices)
            faces = [owner.synthetic_faces[i - 1].copy() for i in indices]
            for face in faces:
                face.transformShape(matrix)
                box = job._bbox(face)
                assert abs(box[0] - lo) < 1e-6 and abs(box[3] - hi) < 1e-6, box
                assert abs(box[2] - level) < 1e-6 and abs(box[5] - level) < 1e-6
                assert abs(face.Area - 27 * 16) < 1e-5
                found, missed = job._face_samples(face, 2)
                assert found and not missed
                assert all(lo - 1e-6 <= p.x <= hi + 1e-6 for p, n in found)
                assert all(n.z * sign < -0.999 for p, n in found)
                # Exact untrimmed cutter solids: central clamps are outside the claim,
                # an ear clamp is hit, and a clamp just beyond the box is still hit.
                points = [p for p, n in found] + [v.Point for v in face.Vertexes]
                cutters = [Part.makeCylinder(2, 10, V(p.x, p.y, level + job.LIFT))
                           for p in points]
                central = Part.makeBox(160, 16, 5, V(-80, 0, level + 1))
                inside = Part.makeBox(2, 16, 5, V((lo + hi) / 2 - 1, 0, level + 1))
                overrun = Part.makeBox(1, 18, 5, V(hi + 0.5, -1, level + 1))
                # Overlapping cylinders are not a valid boolean compound. Test each
                # exact tool solid independently, as collision existence is their union.
                assert all(c.common(central).Volume < job.HIT_MM3 for c in cutters)
                assert any(c.common(inside).Volume > job.HIT_MM3 for c in cutters)
                assert any(c.common(overrun).Volume > job.HIT_MM3 for c in cutters)
                holders = [
                    Part.makeCylinder(8, 20, V(p.x, p.y, level + 11)) for p in points
                ]
                holder_obstacle = Part.makeBox(1, 18, 5, V(hi + 4, -1, level + 12))
                assert all(c.common(holder_obstacle).Volume < job.HIT_MM3 for c in cutters)
                assert any(h.common(holder_obstacle).Volume > job.HIT_MM3 for h in holders)
                windows.append(face)
        assert not set(setup._indices(ops[0])) & set(setup._indices(ops[1]))
        assert abs(Part.makeCompound(windows).Area - 2 * 27 * 16) < 1e-5
        gap = Part.makeBox(300, 16, 1, V(-150, 0, level - 0.5))
        assert Part.makeCompound(windows).common(gap).Area < 1e-5
        unbounded = setup._indices(ops[2])
        assert abs(sum(owner.synthetic_faces[i - 1].Area for i in unbounded) - 360 * 16) < 1e-5
        assert setup._indices(ops[3]) == job.UNKNOWN
        assert setup._indices(ops[4]) == job.UNKNOWN

# Generic deterministic through-prism construction, independent of any fixture identity.
import math


def box_spec(name, at, size, cuts=None):
    return {"name": name, "local": name, "shape": "box", "at_mm": at, "size_mm": size,
            **({"void": True, "cuts": cuts} if cuts is not None else {})}


def cylinder_spec(name, at, radius, length, axis=(0, 0, 1), cuts=None):
    return {"name": name, "local": name, "shape": "cylinder", "at_mm": at,
            "dia_mm": 2 * radius, "length_mm": length, "axis": list(axis),
            **({"void": True, "cuts": cuts} if cuts is not None else {})}


plate = box_spec("plate", [0, 0, 5], [10, 10, 4])
through = cylinder_spec("through", [5, 5, 4], 1, 6, cuts=["plate"])
negative_axis = cylinder_spec("negative-axis", [5, 5, 10], 1, 6,
                              axis=(0, 0, -1), cuts=["plate"])
for tool in (through, negative_axis):
    exact = job._prismatic_owner_cut(plate, [tool])
    assert exact is not None and exact.isValid()
    assert abs(exact.Volume - (400 - 4 * math.pi)) < 1e-6
    assert len(exact.Solids) == 1
    assert not exact.isInside(V(5, 5, 6), 1e-7, True)
    assert exact.isInside(V(3, 5, 6), 1e-7, True)

blind = cylinder_spec("blind", [5, 5, 7], 1, 3, cuts=["plate"])
assert job._prismatic_owner_cut(plate, [blind]) is None
blind_result = dict((s["local"], shape) for s, shape in job._owner_primitives([plate, blind]))["plate"]
assert blind_result.isValid() and abs(blind_result.Volume - (400 - 2 * math.pi)) < 1e-6
assert blind_result.isInside(V(5, 5, 6), 1e-7, True)  # blind floor is still an obstacle
side_hole = cylinder_spec("side-hole", [-1, 5, 7], 1, 12,
                          axis=(1, 0, 0), cuts=["plate"])
assert job._prismatic_owner_cut(plate, [side_hole]) is None
side_result = dict((s["local"], shape) for s, shape in job._owner_primitives([plate, side_hole]))["plate"]
assert side_result.isValid() and abs(side_result.Volume - (400 - 10 * math.pi)) < 1e-6
tilted = cylinder_spec("tilted", [30, 0, 0], 2, 8, axis=(0.6, 0, 0.8))
assert job._prismatic_owner_cut(tilted, [through]) is None
tilted_result = dict((s["local"], shape) for s, shape in job._owner_primitives([tilted, through]))["tilted"]
assert tilted_result.isValid() and abs(tilted_result.Volume - 32 * math.pi) < 1e-6
other = box_spec("other-owner", [0, 0, 5], [10, 10, 4])
owned = dict((s["local"], shape) for s, shape in job._owner_primitives([plate, other, through]))
assert abs(owned["plate"].Volume - (400 - 4 * math.pi)) < 1e-6
assert abs(owned["other-owner"].Volume - 400) < 1e-6  # no cross-owner void leakage

square_hole = box_spec("square-through", [3, 3, 4], [4, 4, 6], cuts=["plate"])
square_result = job._prismatic_owner_cut(plate, [square_hole])
assert square_result.isValid() and len(square_result.Solids) == 1
assert abs(square_result.Volume - 336) < 1e-6
assert square_result.isInside(V(2, 5, 6), 1e-7, True)
assert not square_result.isInside(V(5, 5, 6), 1e-7, True)
sever = box_spec("sever-through", [4, -1, 4], [2, 12, 6], cuts=["plate"])
sever_result = job._prismatic_owner_cut(plate, [sever])
assert sever_result.isValid() and len(sever_result.Solids) == 2
assert abs(sever_result.Volume - 320) < 1e-6

names = ["left-band", "right-band"]
bands = [cylinder_spec(name, [0, 0, 3], 20, 4) for name in names]
voids = [
    cylinder_spec("inner", [0, 0, 2], 16, 6, cuts=names),
    box_spec("lower-clip", [-25, -25, 2], [50, 25, 6], cuts=names),
    box_spec("left-partition", [0, -25, 2], [25, 50, 6], cuts=[names[0]]),
    box_spec("right-partition", [-25, -25, 2], [25, 50, 6], cuts=[names[1]]),
    cylinder_spec("hub", [0, 18, 2], 3, 6, cuts=names),
]
pieces = [shape for s, shape in job._owner_primitives(bands + voids)]
assert len(pieces) == 2 and all(s.isValid() and len(s.Solids) == 1 for s in pieces)


def lens(R, r, d):
    return (R * R * math.acos((d*d + R*R - r*r) / (2*d*R))
            + r * r * math.acos((d*d + r*r - R*R) / (2*d*r))
            - 0.5 * math.sqrt((-d+R+r)*(d+R-r)*(d-R+r)*(d+R+r)))


expected = (math.pi * (20**2 - 16**2) / 2 - lens(20, 3, 18) + lens(16, 3, 18)) * 4
assert abs(sum(s.Volume for s in pieces) - expected) < 1e-5
assert pieces[0].common(pieces[1]).Volume < 1e-7
assert all(abs(s.Volume - expected / 2) < 1e-5 for s in pieces)
for x in (-18, 18):
    cutter = Part.makeCylinder(0.5, 2, V(x, 2, 4))
    assert sum(s.common(cutter).Volume > 1e-7 for s in pieces) == 1
gap = Part.makeCylinder(0.5, 2, V(0, 18, 4))
assert all(s.common(gap).Volume < 1e-7 for s in pieces)

# Regression for a wide annular band clipped by large remote boxes. The upper clip is
# provably disjoint; subtracting it from the planar section previously threw Null shape.
wide_names = ["wide-left", "wide-right"]
wide = [cylinder_spec(name, [0, -762.7235464004277, 0], 813.61875, 6.096)
        for name in wide_names]
wide_voids = [
    cylinder_spec("wide-inner", [0, -762.7235464004277, -0.1], 802.38125, 6.296,
                  cuts=wide_names),
    box_spec("wide-clip-left", [-900, -1700, -0.1], [729.82, 1800, 6.296], cuts=wide_names),
    box_spec("wide-clip-right", [170.18, -1700, -0.1], [729.82, 1800, 6.296], cuts=wide_names),
    box_spec("wide-clip-low", [-900, -1700, -0.1], [1800, 1716.002, 6.296], cuts=wide_names),
    box_spec("wide-clip-high", [-900, 56.642, -0.1], [1800, 100, 6.296], cuts=wide_names),
    box_spec("wide-left-half", [0, -1700, -0.1], [900, 1800, 6.296], cuts=[wide_names[0]]),
    box_spec("wide-right-half", [-900, -1700, -0.1], [900, 1800, 6.296], cuts=[wide_names[1]]),
    cylinder_spec("wide-hub", [0, 45.53045359957228, -0.1], 5.969, 6.296, cuts=wide_names),
]
for x in (-160.8948959654355, 160.8948959654355):
    wide_voids.append(cylinder_spec("wide-end-" + str(x), [x, 29.354329170069267, -0.1],
                                     3.2639, 6.296, cuts=wide_names))
for x, y in [(-39.98366373443545, 44.28655677943425),
             (39.98366373443545, 44.28655677943425),
             (-119.55935301865681, 36.381929181963756),
             (119.55935301865681, 36.381929181963756)]:
    wide_voids.append(cylinder_spec("wide-fixing-" + str(x), [x, y, -0.1],
                                     1.63195, 6.296, cuts=wide_names))
wide_pieces = [shape for s, shape in job._owner_primitives(wide + wide_voids)]
assert len(wide_pieces) == 2 and all(s.isValid() and len(s.Solids) == 1 for s in wide_pieces)
assert abs(sum(s.Volume for s in wide_pieces) - 22211.358505091455) < 1e-3
assert all(abs(s.Volume - 11105.6792525457) < 1e-3 for s in wide_pieces)
assert wide_pieces[0].common(wide_pieces[1]).Volume < 1e-7
for x in (-40, 40):
    obstacle = Part.makeCylinder(0.5, 2, V(x, 48, 2))
    assert sum(s.common(obstacle).Volume > 1e-7 for s in wide_pieces) == 1
covering_void = box_spec("whole-removal", [-1, -1, 4], [12, 12, 6], cuts=["plate"])
try:
    job._owner_primitives([plate, covering_void])
except job._Unknown:
    pass
else:
    raise AssertionError("invalid/empty fixture must remain debt, never disappear")
print("BOUNDED_TRANSIENT_PLANES_OK")
'''


def test_native_process_planes_use_each_operation_window(tmp_path, freecad_kernel):
    script = tmp_path / "prove_process_plane_windows.py"
    script.write_text(
        "try:\n" + indent(_PROBE, "    ")
        + "\nexcept Exception:\n    import traceback\n    traceback.print_exc()\n",
        encoding="utf-8",
    )
    result = subprocess.run(
        [freecad_kernel, str(script)],
        capture_output=True,
        text=True,
        errors="replace",
        timeout=120,
        env={
            **os.environ,
            "PLANE_KERNEL_SOURCE": str(Path(kernel.__file__).with_name("freecad_job.py")),
        },
    )
    assert "BOUNDED_TRANSIENT_PLANES_OK" in result.stdout, result.stdout + result.stderr
