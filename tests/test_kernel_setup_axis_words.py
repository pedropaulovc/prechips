"""An authored face name's axis words are printed in the setup's axes, not the model's.

The rocker's datum B is authored as the "+Z broad strap face" of the model. A setup that
turns the part over holds that face underneath; its picture must call it -Z there.
"""

import json
import os
import subprocess
from pathlib import Path

from prechips import kernel

_PROBE = r"""
import importlib.util, json, math, os, sys
import FreeCAD
out = sys.argv[sys.argv.index("--") + 1]
spec = importlib.util.spec_from_file_location("kernel_under_test", os.environ["KERNEL_SOURCE"])
job = importlib.util.module_from_spec(spec)
spec.loader.exec_module(job)

def turn(rotate, angle):
    matrix = FreeCAD.Matrix()
    if rotate:
        getattr(matrix, rotate)(angle)
    return lambda v: matrix.multVec(v) - matrix.multVec(FreeCAD.Vector())

cases = {
    "kept": (None, 0.0, "B: +Z broad strap face"),
    "turned over": ("rotateX", math.pi, "B: +Z broad strap face"),
    "quarter turn": ("rotateZ", math.pi / 2, "-X end face (+Z side)"),
    "tilted": ("rotateX", math.pi / 4, "top (+Z) face"),
}
result = {
    name: job._setup_axis_words(text, turn(rotate, angle))
    for name, (rotate, angle, text) in cases.items()
}
with open(os.path.join(out, "words.json"), "w", encoding="utf-8") as handle:
    json.dump(result, handle)
"""


def test_authored_axis_words_follow_the_setup_placement(tmp_path, freecad_kernel):
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
    report = tmp_path / "words.json"
    assert report.exists(), process.stdout[-2000:] + process.stderr[-2000:]
    words = json.loads(report.read_text(encoding="utf-8"))
    assert words["kept"] == "B: +Z broad strap face"
    # Turned over, the model's +Z face is the setup's underside.
    assert words["turned over"] == "B: -Z broad strap face"
    assert words["quarter turn"] == "-Y end face (+Z side)"
    # A model axis along no setup axis is not printed as if it were one.
    assert words["tilted"] == "top face"
