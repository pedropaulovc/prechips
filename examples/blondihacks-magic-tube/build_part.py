"""Reproduce the adapted Magic Tube nominal design using native FreeCAD Part.

This is two separate solids, not a fused imitation. Read geometry-provenance.md.
Thread cylinders are nominal-major visual envelopes, not helical thread/fit proof.
Run: freecadcmd.exe <bundle>/build_part.py
"""

from __future__ import annotations

import hashlib
import json
import re
import tempfile
from pathlib import Path
from xml.etree import ElementTree

import FreeCAD
import Part
import TechDraw

HERE = Path(__file__).resolve().parent
# Catalog 12L14-6875 nominal, deliberately selected as adapted finished OD.
# https://continentalsteel.com/item/steel-bars/cold-finished-round-bar-type-12l14/12l14-6875
OUTER_DIAMETER_MM = 17.4625
# AUTHOR'S CHOICE: reallocate the older article's 3.5-in OVERALL size to BODY
# length, leaving a 0.5-in base below its 3-in hole. This is NOT the article's body.
BODY_LENGTH_MM = 88.9
BORE_DEPTH_MM = 76.2  # Older same-project article's stated three-inch interior depth.
BORE_DIAMETER_MM = 11.90625  # 15/32-in tapping drill, video 08:51.
HEAD_LENGTH_MM = 12.7  # Older article: part cap 0.500 in behind its shoulder.
STUB_LENGTH_MM = 12.7  # Video 05:28: five indicator turns, 0.500-in shoulder depth.
THREAD_MAJOR_MM = 12.7  # Video 07:03: 1/2-20, right-hand confirmed 10:28.


def build_shapes():
    vector = FreeCAD.Vector
    body = Part.makeCylinder(OUTER_DIAMETER_MM / 2, BODY_LENGTH_MM)
    bore = Part.makeCylinder(
        BORE_DIAMETER_MM / 2,
        BORE_DEPTH_MM,
        vector(0, 0, BODY_LENGTH_MM - BORE_DEPTH_MM),
    )
    # A simple major envelope for the socket. The physical tap must cut further
    # than the male stub; actual full-thread length and lead clearance are unknown.
    socket = Part.makeCylinder(
        THREAD_MAJOR_MM / 2,
        STUB_LENGTH_MM,
        vector(0, 0, BODY_LENGTH_MM - STUB_LENGTH_MM),
    )
    body = body.cut(bore.fuse(socket)).removeSplitter()
    head = Part.makeCylinder(OUTER_DIAMETER_MM / 2, HEAD_LENGTH_MM, vector(0, 0, BODY_LENGTH_MM))
    stub = Part.makeCylinder(
        THREAD_MAJOR_MM / 2,
        STUB_LENGTH_MM,
        vector(0, 0, BODY_LENGTH_MM - STUB_LENGTH_MM),
    )
    cap = head.fuse(stub).removeSplitter()
    return body, cap


def stable_export(shape, filename):
    target = HERE / filename
    with tempfile.TemporaryDirectory(prefix="prechips-magic-tube-") as directory:
        candidate = Path(directory) / filename
        shape.exportStep(str(candidate))
        text = candidate.read_text(encoding="ascii")
    header = (
        f"FILE_NAME('{filename}','2000-01-01T00:00:00',(''),(''),"
        "'Open CASCADE STEP processor','FreeCAD','');"
    )
    text, count = re.subn(r"FILE_NAME\(.*?\);", header, text, count=1, flags=re.DOTALL)
    if count != 1:
        raise ValueError("Expected exactly one STEP FILE_NAME header")
    data = text.replace("\r\n", "\n").encode("ascii")
    if target.exists() and target.read_bytes() != data:
        raise ValueError(f"{filename}: regenerated STEP differs; frozen bytes preserved")
    if not target.exists():
        target.write_bytes(data)
    imported = Part.Shape()
    imported.read(str(target))
    if not imported.isValid():
        raise ValueError(f"{filename}: invalid exported shape")
    return imported, hashlib.sha256(data).hexdigest()


def reference_svg(body, cap, digest):
    # Native hidden-line removal on an exploded display; never stock/holding evidence.
    exploded_cap = cap.copy()
    exploded_cap.translate(FreeCAD.Vector(0, 0, 15))
    projection = ElementTree.fromstring(
        "<g>"
        + TechDraw.projectToSVG(
            Part.makeCompound([body, exploded_cap]), FreeCAD.Vector(1, -1, 0.65)
        )
        + "</g>"
    )
    projection.set("stroke-width", "0.22")
    radius = 125
    svg = (
        '<svg xmlns="http://www.w3.org/2000/svg" width="680" height="500" viewBox="0 0 680 500">\n'
        "<title>Adapted Magic Tube design, exploded body and removable cap</title>\n"
        f"<desc>Native B-rep projection. STEP SHA-256 {digest}. No helical threads, "
        "chamfers, drill point, raw stock or workholding represented.</desc>\n"
        '<rect width="680" height="500" fill="white"/>\n'
        '<g font-family="sans-serif" text-anchor="middle" fill="#222">'
        '<text x="340" y="30" font-size="18">'
        "Adapted nominal Magic Tube — two separate pieces</text>"
        '<text x="340" y="55" font-size="14">'
        "Exploded view; not a physical fit or stock/holding certificate</text></g>\n"
        f'<svg x="40" y="70" width="600" height="350" viewBox="{-radius} {-radius} '
        f'{2 * radius} {2 * radius}">'
        '<g transform="translate(0,-85) scale(1.6)">'
        + ElementTree.tostring(projection, encoding="unicode")
        + "</g></svg>\n"
        '<g font-family="sans-serif" text-anchor="middle" fill="#444" font-size="14">'
        '<text x="340" y="450">Body 3.5 in; head 0.5 in; closed total 4 in; OD 11/16 in</text>'
        '<text x="340" y="475">'
        "1/2-20 RH visual envelopes only; no invented tolerance bands</text></g>\n</svg>\n"
    )
    (HERE / "part-reference.svg").write_text(svg, encoding="utf-8", newline="\n")


def build_reference():
    body, cap = build_shapes()
    for name, shape in (("body", body), ("cap", cap)):
        if not shape.isValid() or len(shape.Solids) != 1 or shape.Volume <= 0:
            raise ValueError(f"{name}: expected one valid nonempty solid")
    overlap = body.common(cap).Volume
    if overlap > 1e-7:
        raise ValueError("Body and cap have positive-volume interference")
    compound = Part.makeCompound([body, cap])
    imported, digest = stable_export(compound, "magic-tube.STEP")
    if len(imported.Solids) != 2:
        raise ValueError("Assembly STEP must retain exactly two distinct solids")
    reference_svg(body, cap, digest)
    rows = []
    for index, face in enumerate(imported.Faces, 1):
        box = face.BoundBox
        row = {
            "brep_face": index,
            "surface": type(face.Surface).__name__,
            "area_mm2": face.Area,
            "center_mm": list(face.CenterOfMass),
            "bbox_mm": [box.XMin, box.YMin, box.ZMin, box.XMax, box.YMax, box.ZMax],
        }
        if isinstance(face.Surface, Part.Cylinder):
            row["radius_mm"] = face.Surface.Radius
            row["axis"] = list(face.Surface.Axis)
        rows.append(row)
    result = {
        "freecad_version": FreeCAD.Version()[:3],
        "valid": imported.isValid(),
        "solids": len(imported.Solids),
        "volume_mm3": imported.Volume,
        "body_volume_mm3": body.Volume,
        "cap_volume_mm3": cap.Volume,
        "nominal_component_overlap_mm3": overlap,
        "sha256": digest,
        "faces": rows,
    }
    print("MAGIC_TUBE_JSON " + json.dumps(result, sort_keys=True))


# FreeCADCmd imports a positional script as a module; __main__ guards skip it.
try:
    build_reference()
except Exception:
    import traceback

    traceback.print_exc()
    raise
