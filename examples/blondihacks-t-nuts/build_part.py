"""Build the video-process, catalog-based T-nut design with FreeCAD's Part kernel.

Run from any directory:
    freecadcmd.exe examples/blondihacks-t-nuts/build_part.py

Source and limitations: geometry-provenance.md beside this script. Widths and
height follow Carr Lane CL-0-TN nominal dimensions; length and flange thickness
follow the video. This adapted design is not an exact replica of either source.
The bore represents nominal thread major diameter, not a drill or helical thread.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

import FreeCAD
import Part

HERE = Path(__file__).resolve().parent
SOURCE_URL = "https://www.youtube.com/watch?v=TL0OsfFkBL8"

# Spoken/overlaid nominal dimensions, converted using exactly 25.4 mm/inch.
LENGTH_MM = 25.4  # 02:45: each nut one inch long.
FLANGE_THICKNESS_MM = 6.35  # 06:47 / overlay 06:50: 0.250 inch.
NOMINAL_THREAD_DIAMETER_MM = 9.525  # 02:35 / 13:11: 3/8-16 thread.

# Selected Carr Lane CL-0-TN catalog nominal section dimensions (B, C, E).
# https://www.carrlane.com/product/clamping-hardware/studs-bolts-t-nuts/t-nuts
BASE_WIDTH_MM = 22.225  # C = 7/8 inch.
TOTAL_HEIGHT_MM = 12.7  # E = 1/2 inch.
STEM_WIDTH_MM = 12.573  # B = 0.495 inch; not the nominal 1/2-inch slot size.


def build_shape():
    """Centered X/Y, bottom Z=0; one bore along +Z, with ideal sharp edges."""
    vector = FreeCAD.Vector
    flange = Part.makeBox(
        LENGTH_MM,
        BASE_WIDTH_MM,
        FLANGE_THICKNESS_MM,
        vector(-LENGTH_MM / 2, -BASE_WIDTH_MM / 2, 0),
    )
    stem = Part.makeBox(
        LENGTH_MM,
        STEM_WIDTH_MM,
        TOTAL_HEIGHT_MM - FLANGE_THICKNESS_MM,
        vector(-LENGTH_MM / 2, -STEM_WIDTH_MM / 2, FLANGE_THICKNESS_MM),
    )
    bore = Part.makeCylinder(
        NOMINAL_THREAD_DIAMETER_MM / 2,
        TOTAL_HEIGHT_MM + 2,
        vector(0, 0, -1),
    )
    return flange.fuse(stem).cut(bore).removeSplitter()


def main():
    shape = build_shape()
    if not shape.isValid() or len(shape.Solids) != 1 or shape.Volume <= 0:
        raise ValueError("T-nut reconstruction must be one valid, nonempty solid")
    target = HERE / "t-nut.STEP"
    shape.exportStep(str(target))
    # OpenCascade includes wall-clock time and an absolute path in FILE_NAME.
    # Only replace that non-geometric header record, leaving DATA untouched.
    text = target.read_text(encoding="ascii")
    text, count = re.subn(
        r"FILE_NAME\(.*?\);",
        "FILE_NAME('t-nut.STEP','2000-01-01T00:00:00',(''),(''),"
        "'Open CASCADE STEP processor','FreeCAD','');",
        text,
        count=1,
        flags=re.DOTALL,
    )
    if count != 1:
        raise ValueError("Expected exactly one STEP FILE_NAME header")
    data = text.replace("\r\n", "\n").encode("ascii")
    target.write_bytes(data)
    imported = Part.Shape()
    imported.read(str(target))
    if not imported.isValid() or len(imported.Solids) != 1:
        raise ValueError("Exported STEP did not reimport as one valid solid")
    box = imported.BoundBox
    faces = []
    for index, face in enumerate(imported.Faces, 1):
        row = {
            "brep_face": index,
            "surface": type(face.Surface).__name__,
            "area_mm2": face.Area,
            "center_mm": list(face.CenterOfMass),
        }
        if isinstance(face.Surface, Part.Cylinder):
            row["radius_mm"] = face.Surface.Radius
            row["axis"] = list(face.Surface.Axis)
        faces.append(row)
    print(
        "TNUT_JSON "
        + json.dumps(
            {
                "source_url": SOURCE_URL,
                "freecad_version": FreeCAD.Version()[:3],
                "valid": imported.isValid(),
                "solids": len(imported.Solids),
                "bbox_min_mm": [box.XMin, box.YMin, box.ZMin],
                "bbox_max_mm": [box.XMax, box.YMax, box.ZMax],
                "volume_mm3": imported.Volume,
                "sha256": hashlib.sha256(data).hexdigest(),
                "faces": faces,
            },
            sort_keys=True,
        )
    )


# FreeCADCmd executes scripts without setting __name__ to '__main__'.
main()
