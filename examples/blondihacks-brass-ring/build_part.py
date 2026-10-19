"""Build Blondihacks' nominal 360 free-machining brass ring in native FreeCAD.

Run: freecadcmd.exe <path-to-this-script>
Source: https://www.youtube.com/watch?v=t9NGty1CVII
05:41: ID 0.625 inch + twice 0.050 inch wall = OD 0.725 inch.
14:40-14:48: finished axial width 0.100 inch. Exact conversion: 25.4 mm/in.
These are spoken design nominals, not measured dimensions or tolerance bands.
The hand-filed/deburred edges have no stated size and remain nominally sharp.
The groove on sacrificial bar behind the ring is NOT a finished-part feature.
No stock, workholding or physical-fit approval is represented.

Private export normalizes only FILE_NAME and LF; an existing frozen STEP is
never replaced on mismatch. Native STEP reimport is validated before the SVG
and geometry report are produced. The report is outside the bundle, at the
video cache root. STEP identities are derived from entity surface geometry,
not from B-rep import order (same approach as examples/geometry/author_solids.py).
"""
from __future__ import annotations

import hashlib
import json
import math
import re
import tempfile
from pathlib import Path
from xml.etree import ElementTree

import FreeCAD
import Part
import TechDraw

HERE = Path(__file__).resolve().parent
# Keep diagnostic reports external even when this bundle is copied into a repo.
CACHE = Path.home() / ".cache" / "prechips" / "video-t9NGty1CVII"
SOURCE_URL = "https://www.youtube.com/watch?v=t9NGty1CVII"
OD_MM = 18.415
ID_MM = 15.875
WIDTH_MM = 2.54
TOL = 1e-7  # Numerical identity comparison only; not a design tolerance.


def build_shape():
    origin = FreeCAD.Vector(0, 0, -WIDTH_MM)
    axis = FreeCAD.Vector(0, 0, 1)
    outer = Part.makeCylinder(OD_MM / 2, WIDTH_MM, origin, axis)
    bore = Part.makeCylinder(ID_MM / 2, WIDTH_MM, origin, axis)
    return outer.cut(bore).removeSplitter()


def validate(shape):
    if shape.isNull() or not shape.isValid() or len(shape.Solids) != 1 or shape.Volume <= 0:
        raise ValueError("Ring must be one valid nonempty solid")
    box = shape.BoundBox
    actual = (box.XMin, box.YMin, box.ZMin, box.XMax, box.YMax, box.ZMax)
    expected = (-OD_MM / 2, -OD_MM / 2, -WIDTH_MM, OD_MM / 2, OD_MM / 2, 0)
    if any(abs(a - b) > TOL for a, b in zip(actual, expected)):
        raise ValueError("Ring bounds do not match the nominal design")
    volume = math.pi * ((OD_MM / 2) ** 2 - (ID_MM / 2) ** 2) * WIDTH_MM
    if abs(shape.Volume - volume) > TOL or len(shape.Faces) != 4:
        raise ValueError("Ring topology or volume does not match the nominal design")


def split_args(args):
    parts, depth, current, quoted = [], 0, [], False
    for char in args:
        if char == "'":
            quoted = not quoted
        if not quoted:
            if char == "(":
                depth += 1
            elif char == ")":
                depth -= 1
            elif char == "," and depth == 0:
                parts.append("".join(current).strip())
                current = []
                continue
        current.append(char)
    parts.append("".join(current).strip())
    return parts


def step_faces(text):
    """Resolve ADVANCED_FACE -> surface -> placement directly in STEP DATA."""
    records = {}
    body = text.split("DATA;", 1)[1].split("ENDSEC;", 1)[0]
    for raw in body.split(";"):
        match = re.fullmatch(r"#(\d+)\s*=\s*([A-Z0-9_]+)\s*\((.*)\)\s*", raw.strip(), re.DOTALL)
        if match:
            entity = int(match[1])
            if entity in records:
                raise ValueError("Duplicate STEP entity")
            records[entity] = (match[2], split_args(match[3]))

    def ref(token):
        return int(token.lstrip("#"))

    def triple(token):
        kind, fields = records[ref(token)]
        if kind not in ("CARTESIAN_POINT", "DIRECTION"):
            raise ValueError("Expected STEP point or direction")
        return [float(v) for v in fields[1].strip("() ").split(",")]

    rows = []
    for entity, (kind, fields) in records.items():
        if kind != "ADVANCED_FACE":
            continue
        surface_entity = ref(fields[2])
        surface, sfields = records[surface_entity]
        placement_kind, placement = records[ref(sfields[1])]
        if placement_kind != "AXIS2_PLACEMENT_3D":
            raise ValueError("Expected STEP surface placement")
        origin, axis = triple(placement[1]), triple(placement[2])
        ordinal = len(rows) + 1
        label = fields[0].strip("'").replace("''", "'")
        row = {"ref": f"#{entity}/ADVANCED_FACE[{ordinal}]/{label}",
               "entity": entity, "ordinal": ordinal, "label": label,
               "surface_entity": surface_entity, "surface": surface,
               "same_sense": fields[3] == ".T."}
        if surface == "CYLINDRICAL_SURFACE":
            row.update(axis_point_mm=origin, axis=axis, radius_mm=float(sfields[2]))
        elif surface == "PLANE":
            normal = axis if row["same_sense"] else [-x for x in axis]
            row.update(origin_mm=origin, normal=normal,
                       offset_mm=sum(p * n for p, n in zip(origin, normal)))
        else:
            raise ValueError(f"Unexpected ring surface {surface}")
        rows.append(row)
    return rows


def face_role(surface, radius=None, z=None):
    if surface == "Cylinder":
        if abs(radius - OD_MM / 2) < TOL:
            return "outer_cylinder"
        if abs(radius - ID_MM / 2) < TOL:
            return "inner_cylinder"
    elif surface == "Plane":
        if abs(z) < TOL:
            return "front_annulus"
        if abs(z + WIDTH_MM) < TOL:
            return "back_annulus"
    raise ValueError("Unrecognized ring face geometry")


def map_faces(shape, text):
    native = {}
    for index, face in enumerate(shape.Faces, 1):
        surface = face.Surface
        kind = type(surface).__name__
        row = {"brep_face": index, "surface": kind, "area_mm2": face.Area,
               "center_mm": list(face.CenterOfMass), "orientation": face.Orientation,
               "bbox_min_mm": [face.BoundBox.XMin, face.BoundBox.YMin, face.BoundBox.ZMin],
               "bbox_max_mm": [face.BoundBox.XMax, face.BoundBox.YMax, face.BoundBox.ZMax]}
        radius = surface.Radius if kind == "Cylinder" else None
        if kind == "Cylinder":
            row.update(radius_mm=radius, axis=list(surface.Axis), axis_point_mm=list(surface.Center))
        else:
            normal = face.normalAt(0, 0)
            row.update(normal=list(normal), offset_mm=normal.dot(face.CenterOfMass))
        role = face_role(kind, radius, face.CenterOfMass.z)
        if role in native:
            raise ValueError("Ambiguous native face geometry")
        native[role] = row
    mapped = {}
    for row in step_faces(text):
        if row["surface"] == "CYLINDRICAL_SURFACE":
            if abs(abs(row["axis"][2]) - 1) > TOL or any(abs(v) > TOL for v in row["axis_point_mm"][:2]):
                raise ValueError("Unexpected cylinder axis")
            role = face_role("Cylinder", row["radius_mm"])
        else:
            if abs(abs(row["normal"][2]) - 1) > TOL:
                raise ValueError("Unexpected annulus normal")
            role = face_role("Plane", z=row["origin_mm"][2])
            if any(abs(a - b) > TOL for a, b in zip(row["normal"], native[role]["normal"])):
                raise ValueError("STEP/native oriented plane disagreement")
        if role in mapped:
            raise ValueError("Ambiguous STEP face geometry")
        mapped[role] = {"step": row, "native": native[role]}
    if set(mapped) != {"outer_cylinder", "inner_cylinder", "front_annulus", "back_annulus"}:
        raise ValueError("Missing functional ring face")
    return mapped


def write_reference_svg(shape, digest):
    # TechDraw returns sibling SVG groups for this ring, not one XML root.
    fragment = TechDraw.projectToSVG(shape, FreeCAD.Vector(1, -1, 1))
    projection = ElementTree.fromstring("<g>" + fragment + "</g>")
    projection.set("stroke-width", "0.10")
    # Native groups otherwise override the wrapper with a 1 mm stroke.
    for element in projection.iter():
        if "stroke-width" in element.attrib:
            element.set("stroke-width", "0.10")
    radius = math.sqrt((OD_MM / 2) ** 2 + WIDTH_MM ** 2) + 1
    rows = [
        '<svg xmlns="http://www.w3.org/2000/svg" width="640" height="450" viewBox="0 0 640 450">',
        '<title>Nominal finished design — not stock, holding or fit approval</title>',
        '<desc>Native FreeCAD TechDraw hidden-line projection of the validated brass ring B-rep. '
        'Sharp nominal edges; unquantified hand deburring and sacrificial-bar groove not modeled. '
        f'STEP SHA-256: {digest}.</desc>',
        '<rect width="640" height="450" fill="white"/>',
        '<g font-family="sans-serif" text-anchor="middle" fill="#222">',
        '<text x="320" y="30" font-size="18">Nominal finished design</text>',
        '<text x="320" y="54" font-size="15">— not stock, holding or fit approval</text>',
        f'<svg x="45" y="75" width="550" height="285" viewBox="{-radius} {-radius} {2*radius} {2*radius}">',
        ElementTree.tostring(projection, encoding="unicode"), '</svg>',
        '<text x="320" y="388" font-size="14">360 brass ring · OD 18.415 · ID 15.875 · width 2.54 mm</text>',
        '<text x="320" y="411" font-size="13">Spoken design nominals; no tolerance or physical measurement claim</text>',
        '<text x="320" y="434" font-size="13">Axis +Z; front Z=0; back Z=−2.54 mm; nominal sharp edges</text>',
        '</g></svg>',
    ]
    (HERE / "part-reference.svg").write_bytes(("\n".join(rows) + "\n").encode("utf-8"))


def main():
    shape = build_shape()
    validate(shape)
    target = HERE / "brass-ring.STEP"
    with tempfile.TemporaryDirectory(prefix="prechips-ring-") as directory:
        candidate = Path(directory) / target.name
        shape.exportStep(str(candidate))
        text = candidate.read_text(encoding="ascii")
        text, count = re.subn(
            r"FILE_NAME\(.*?\);",
            "FILE_NAME('brass-ring.STEP','2000-01-01T00:00:00',(''),(''),"
            "'Open CASCADE STEP processor','FreeCAD','');",
            text, count=1, flags=re.DOTALL,
        )
        if count != 1:
            raise ValueError("Expected exactly one STEP FILE_NAME header")
        data = text.replace("\r\n", "\n").encode("ascii")
        candidate.write_bytes(data)
        imported = Part.Shape()
        imported.read(str(candidate))
        validate(imported)
        faces = map_faces(imported, text)
        if target.exists():
            if target.read_bytes() != data:
                raise ValueError("Regenerated STEP differs from frozen reference; original preserved")
        else:
            target.write_bytes(data)
    digest = hashlib.sha256(data).hexdigest()
    write_reference_svg(imported, digest)
    box = imported.BoundBox
    summary = {
        "source_url": SOURCE_URL, "source_design_nominals": {
            "05:41": "ID 0.625 in + 2 x 0.050 in wall = OD 0.725 in",
            "14:40-14:48": "axial width 0.100 in"},
        "freecad_version": FreeCAD.Version()[:3], "valid": imported.isValid(),
        "solids": len(imported.Solids), "face_count": len(imported.Faces),
        "bbox_min_mm": [box.XMin, box.YMin, box.ZMin],
        "bbox_max_mm": [box.XMax, box.YMax, box.ZMax],
        "volume_mm3": imported.Volume, "sha256": digest, "faces": faces,
        "identity_method": "STEP ADVANCED_FACE -> analytic surface/placement matched to native face geometry; never import-order identity",
    }
    CACHE.mkdir(parents=True, exist_ok=True)
    (CACHE / "geometry-faces.json").write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    notes = (
        f"Source: {SOURCE_URL}\n"
        "Native FreeCAD Part construction and private STEP reimport observed.\n"
        f"FreeCAD: {'.'.join(FreeCAD.Version()[:3])}; valid={summary['valid']}; solids={summary['solids']}; faces={summary['face_count']}\n"
        f"SHA-256: {digest}\nVolume mm3: {imported.Volume:.15g}\n"
        f"Bounds mm: {summary['bbox_min_mm']} to {summary['bbox_max_mm']}\n"
        "Axis +Z; front Z=0; back Z=-2.54 mm.\n"
        "OD18.415, ID15.875, width2.54 mm are spoken design nominals, not tolerance bands or physical measurements.\n"
        "Sharp nominal edges: source hand-file/deburr has no quantified size. No sacrificial-bar groove on finished ring.\n"
        "SVG is native TechDraw hidden-line projection, not stock, holding or fit approval.\n"
        "STEP refs resolved through entity surface geometry, then matched by radius/axis or oriented plane position, never native import order.\n"
        + "".join(f"{role}: {row['step']['ref']}\n" for role, row in faces.items())
    )
    (CACHE / "geometry-notes.txt").write_text(notes, encoding="utf-8")
    print("RING_JSON " + json.dumps(summary, sort_keys=True))


# This FreeCADCmd entry runs through module import; require RING_JSON for success.
main()
