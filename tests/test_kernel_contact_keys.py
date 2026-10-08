"""Kernel holding contacts keep the plane each one lies on, through to the printed key.

A section view clips a contact's outline at its plane without changing that plane, and
numbered supports (a passive support's SUP code, numbered pads) that seat the work at two
heights key each support at its own height, never under one unqualified contact.
"""

import json
import math
import os
import re
import subprocess
from pathlib import Path

import pytest

from prechips import kernel
from prechips.kernel.render_diagram import (
    _CONTACT,
    _detail_frame,
    _Diagram,
    _holding_details,
    _HoldingDetail,
)
from prechips.kernel.render_inputs import _clamps

_PROBE_HEAD = r"""
import importlib.util, json, os, sys
import FreeCAD, Part
out = sys.argv[sys.argv.index("--") + 1]
spec = importlib.util.spec_from_file_location("kernel_under_test", os.environ["KERNEL_SOURCE"])
job = importlib.util.module_from_spec(spec)
spec.loader.exec_module(job)
V = FreeCAD.Vector
args = json.loads(os.environ["PROBE_ARGS"])
setup = job._Setup.__new__(job._Setup)
"""

_SECTION_PROBE = r"""
setup.part = Part.makeBox(10, 10, 10, V(-5, -5, 0))
supports = {
    # Its top is the block's whole underside: the section plane crosses the contact.
    "across": Part.makeBox(10, 10, 5, V(-5, -5, -5)),
    # Under the removed half only: the section keeps just one edge of its contact face.
    "edge": Part.makeBox(10, 5, 5, V(-5, -5, -5)),
}
result = {}
for name, solid in supports.items():
    for view, section in (("whole", None), ("section", (1, 1, 0.0))):
        contacts = setup._render_contacts([("fx:" + name, solid)], 0.01, section)
        result[name + " " + view] = contacts
"""

_SUPPORT_PROBE = r"""
# Work whose underside steps from Z left (X 0..35) to Z right (X 35..100), seated on one
# holding owner's two supports, one under each step.
left, right = args["heights"]
setup.part = Part.makeBox(35, 12, 18 - left, V(0, 0, left)).fuse(
    Part.makeBox(65, 12, 18 - right, V(35, 0, right))
)
setup.fixture, setup.hold = [], {"clamps": []}
identity = job._pose_matrix({"origin_mm": [0, 0, 0], "x": [1, 0, 0], "z": [0, 0, 1]})
setup._add_owned(args["solids"], args["role"], identity, args["owner"])
components = setup._render_components(args["annotation"])
solids = [(component["name"], component["solid"]) for component in setup.fixture]
contacts = setup._render_contacts(solids, 0.01, None)
meshes = []
for tag, solid in [("part", setup.part)] + solids:
    points, triangles = solid.tessellate(0.01)
    meshes.append([[[p.x, p.y, p.z] for p in points], [list(t) for t in triangles], tag])
result = {"components": components, "contacts": contacts, "meshes": meshes}
"""

_PROBE_TAIL = r"""
with open(os.path.join(out, "probe.json"), "w", encoding="utf-8") as handle:
    json.dump(result, handle)
"""


def _probe(tmp_path, freecad_kernel, body, **args):
    """Run ``body`` against the kernel source in FreeCAD; its JSON ``result``."""
    script = tmp_path / "probe.py"
    script.write_text(_PROBE_HEAD + body + _PROBE_TAIL, encoding="utf-8")
    source = Path(kernel.__file__).with_name("freecad_job.py")
    process = subprocess.run(
        [freecad_kernel, str(script), "--", str(tmp_path)],
        capture_output=True,
        text=True,
        errors="replace",
        timeout=300,
        env={**os.environ, "KERNEL_SOURCE": str(source), "PROBE_ARGS": json.dumps(args)},
    )
    report = tmp_path / "probe.json"
    assert report.exists(), process.stdout[-2000:] + process.stderr[-2000:]
    return json.loads(report.read_text(encoding="utf-8"))


# The section view the kernel draws for this block: from -Y, keeping Y >= 0.
_SECTION_CAMERA = [[1, 0, 0], [0, 0, 1], [0, -1, 0]]


def _section_keys(contacts):
    """The contact keys a holding detail prints for these kernel contacts."""
    spec = {
        "setup_id": "S1",
        "view": "elevation",
        "camera": _SECTION_CAMERA,
        "stock_box": [-5, -5, 0, 5, 5, 10],
        "zero_mm": [0, 0, 0],
        "contacts": contacts,
    }
    detail = _HoldingDetail([], spec, _detail_frame(spec), _SECTION_CAMERA, 1.0)
    detail.render()
    return [callout.label for callout in detail.callouts if callout.colour == _CONTACT]


def test_a_section_clips_a_contact_at_its_plane_and_keeps_its_seating_height(
    tmp_path, freecad_kernel
):
    found = _probe(tmp_path, freecad_kernel, _SECTION_PROBE)

    for name in ("across", "edge"):
        for view in ("whole", "section"):
            assert _section_keys(found[f"{name} {view}"]) == [f"{name.upper()} CONTACT AT Z 0"]
    # The kept outline runs to the section plane: each side edge crossing it keeps the
    # point where it does, and nothing of the removed half is drawn.
    (contact,) = found["across section"]
    points = [point for line in contact["lines_mm"] for point in line]
    assert min(point[1] for point in points) >= -1e-3
    for x in (-5, 5):
        assert any(abs(p[0] - x) < 1e-6 and abs(p[1]) < 1e-6 for p in points), x


# Each support's footprint starts here on X; the work steps at X 35.
_SUPPORT_X = (20, 40)


def _holding(kind, heights):
    """(role, owner, primitives, annotation, code) of one holding owner's two supports,
    the first under the work's left step and the second under its right."""
    if kind == "coded_support":
        # A declared passive support (restraint none): the traveler codes it SUP1.
        (clamp,) = _clamps({}, {"clamps": [{"ref": "stepped-rest", "restraint": "none"}]})
        role, owner, code = "clamp", clamp["owner"], clamp["code"]
        names, annotation = ["rail-shim-lu", "rail-shim-ru"], {"clamps": [clamp]}
    else:
        # Two numbered support pads of an authored fixture body.
        role, owner, code = "fixture", "fixture", None
        names, annotation = ["pad-1", "pad-2"], {}
    solids = [
        {
            "name": f"{owner}:{name}",
            "local": name,
            "shape": "box",
            "at_mm": [x, -2, 0],
            "size_mm": [8, 6, top],
        }
        for name, x, top in zip(names, _SUPPORT_X, heights, strict=True)
    ]
    return role, owner, solids, annotation, code


def _marks(detail):
    """(key words, height or None, pixels it marks) per contact key. A leader key marks
    its leader ends; a badge key marks the badges whose code it names, else every badge."""
    badges = detail.position_badges
    result = []
    for callout in detail.callouts:
        if callout.colour != _CONTACT:
            continue
        words = set(re.split(r"[\s(),:]+", callout.label))
        _, at, height = callout.label.partition(" AT Z ")
        points = callout.points
        if callout.leader == "keyed":
            named = [badge["xy"] for badge in badges if badge["label"] in words]
            points = named or [badge["xy"] for badge in badges]
        result.append((words, float(height) if at else None, points))
    return result


@pytest.mark.parametrize("kind", ["coded_support", "pads"])
@pytest.mark.parametrize("heights", [(10, 12), (12, 12)], ids=["stepped_work", "flat_work"])
def test_numbered_supports_seating_the_work_at_two_heights_key_each_support_at_its_own(
    tmp_path, freecad_kernel, kind, heights
):
    role, owner, solids, annotation, code = _holding(kind, heights)
    found = _probe(
        tmp_path,
        freecad_kernel,
        _SUPPORT_PROBE,
        heights=heights,
        role=role,
        owner=owner,
        solids=solids,
        annotation=annotation,
    )
    assert sorted(contact["plane"][1] for contact in found["contacts"]) == sorted(heights)
    colours = {"part": (160, 175, 185)}
    meshes = [
        (points, triangles, colours.get(tag, (120, 98, 76)), False, tag)
        for points, triangles, tag in found["meshes"]
    ]
    spec = {
        "setup_id": "S3",
        "view": "plan",
        "stock_box": [0, 0, min(heights), 100, 12, 18],
        "zero_mm": [0, 0, 0],
        "components": found["components"],
        "contacts": found["contacts"],
    }
    main = _Diagram(meshes, spec)
    main.render()
    details = _holding_details(meshes, spec, main)

    keyed, marked = [], set()
    for detail in details:
        supports = [
            (height, detail.canvas.project([x + 4, 1, height]))
            for x, height in zip(_SUPPORT_X, heights, strict=True)
        ]
        for words, height, points in _marks(detail):
            keyed.append(height)
            if code:
                # A coded support keeps its code on every key that names its contacts.
                assert code in words
            for point in points:
                # Every contact a key marks is a support seating the work at its height.
                seated, _ = min(supports, key=lambda support: math.dist(point, support[1]))
                assert seated == height, (words, height, seated)
                marked.add(seated)
    # One key per seating height, each marking a support at that height.
    assert sorted(keyed) == sorted(set(heights))
    assert marked == set(heights)
