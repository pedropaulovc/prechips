"""A section view clips contact outlines at its plane without changing the contact's plane.

A block rests on a support whose top is its whole underside, at Z 0. The custom-fixture
elevation is a section at Y 0 that keeps Y >= 0: the drawn contact is the half of that
face behind the plane, and it is still keyed as the seating contact at Z 0, never as a
lateral contact at the face's far edge.
"""

import json
import os
import subprocess
from pathlib import Path

from prechips import kernel
from prechips.kernel.render_diagram import _CONTACT, _detail_frame, _HoldingDetail

_PROBE = r"""
import importlib.util, json, os, sys
import FreeCAD, Part
out = sys.argv[sys.argv.index("--") + 1]
spec = importlib.util.spec_from_file_location("kernel_under_test", os.environ["KERNEL_SOURCE"])
job = importlib.util.module_from_spec(spec)
spec.loader.exec_module(job)
V = FreeCAD.Vector
setup = job._Setup.__new__(job._Setup)
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
        contacts, _ = setup._render_contacts([("fx:" + name, solid)], None, 0.01, section)
        result[name + " " + view] = contacts
with open(os.path.join(out, "contacts.json"), "w", encoding="utf-8") as handle:
    json.dump(result, handle)
"""

# The section view the kernel draws for this block: from -Y, keeping Y >= 0.
_SECTION_CAMERA = [[1, 0, 0], [0, 0, 1], [0, -1, 0]]


def _contact_keys(contacts):
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
    script = tmp_path / "probe.py"
    script.write_text(_PROBE, encoding="utf-8")
    source = Path(kernel.__file__).with_name("freecad_job.py")
    process = subprocess.run(
        [freecad_kernel, str(script), "--", str(tmp_path)],
        capture_output=True,
        text=True,
        errors="replace",
        timeout=300,
        env={**os.environ, "KERNEL_SOURCE": str(source)},
    )
    report = tmp_path / "contacts.json"
    assert report.exists(), process.stdout[-2000:] + process.stderr[-2000:]
    found = json.loads(report.read_text(encoding="utf-8"))

    for name in ("across", "edge"):
        for view in ("whole", "section"):
            assert _contact_keys(found[f"{name} {view}"]) == [f"{name.upper()} CONTACT AT Z 0"]
    # The kept outline runs to the section plane: each side edge crossing it keeps the
    # point where it does, and nothing of the removed half is drawn.
    (contact,) = found["across section"]
    points = [point for line in contact["lines_mm"] for point in line]
    assert min(point[1] for point in points) >= -1e-3
    for x in (-5, 5):
        assert any(abs(p[0] - x) < 1e-6 and abs(p[1]) < 1e-6 for p in points), x
