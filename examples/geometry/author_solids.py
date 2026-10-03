"""Author the synthetic M4 geometry fixtures and derive their STEP face references.

Run under FreeCAD only (stdlib + FreeCAD; never imported by prechips):

    freecadcmd.exe examples/geometry/author_solids.py -- build
    freecadcmd.exe examples/geometry/author_solids.py -- faces <file.STEP> [...]

``build`` writes the three designed test solids beside their fixtures as STEP
(AP214, LF line endings) and prints each file's SHA-256. ``faces`` lists every
``ADVANCED_FACE`` of a STEP in file order as ``#<entity>/ADVANCED_FACE[<ordinal>]/<label>``
with the surface geometry read from the STEP text itself (plane normal and
offset, cylinder axis and radius), which is how the fixture manifests were
bound. The kernel re-derives the same identity from reconstructed B-rep faces;
the two derivations must agree or the manifest is wrong.

The solids are designed test geometries with authored dimensions. They are not
measurements of any inventory part or drawing. Re-running ``build`` writes new
bytes (the STEP header carries a timestamp), so the committed STEP files, their
manifest digests and face references are the frozen fixtures; this script is
their provenance, not a build step.
"""

from __future__ import annotations

import hashlib
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent

# Designed dimensions (mm). Every number here is a test-fixture choice.
POCKET_BLOCK = dict(block=(70.0, 50.0, 60.0), pocket=(40.0, 24.0), depth=45.0, corner_r=6.0)
SLOT_BLOCK = dict(block=(60.0, 40.0, 20.0), pocket=(30.0, 12.0), depth=6.0)
STEP_BLOCK = dict(block=(60.0, 40.0, 20.0), step_from_x=30.0, step_depth=10.0)

SOLIDS = {
    "pocket-reach/pocket-block.STEP": "pocket_block",
    "sharp-corner/slot-block.STEP": "slot_block",
    "unclaimed-face/step-block.STEP": "step_block",
}


def pocket_block():
    """70 x 50 x 60 block; closed 40 x 24 pocket, R6 vertical corners, 45 deep from the top."""
    import FreeCAD
    import Part

    V = FreeCAD.Vector
    bx, by, bz = POCKET_BLOCK["block"]
    px, py = POCKET_BLOCK["pocket"]
    depth, radius = POCKET_BLOCK["depth"], POCKET_BLOCK["corner_r"]
    block = Part.makeBox(bx, by, bz)
    floor_z = bz - depth
    cutter = Part.makeBox(px, py, depth + 1.0, V((bx - px) / 2, (by - py) / 2, floor_z))
    vertical = [e for e in cutter.Edges if abs(e.tangentAt(e.FirstParameter).z) > 0.999]
    cutter = cutter.makeFillet(radius, vertical)
    return block.cut(cutter)


def slot_block():
    """60 x 40 x 20 block; closed 30 x 12 pocket with sharp vertical corners, 6 deep."""
    import FreeCAD
    import Part

    V = FreeCAD.Vector
    bx, by, bz = SLOT_BLOCK["block"]
    px, py = SLOT_BLOCK["pocket"]
    depth = SLOT_BLOCK["depth"]
    block = Part.makeBox(bx, by, bz)
    cutter = Part.makeBox(px, py, depth + 1.0, V((bx - px) / 2, (by - py) / 2, bz - depth))
    return block.cut(cutter)


def step_block():
    """60 x 40 x 20 block; the +X half stepped down 10 mm (one floor, one vertical wall)."""
    import FreeCAD
    import Part

    V = FreeCAD.Vector
    bx, by, bz = STEP_BLOCK["block"]
    x0, depth = STEP_BLOCK["step_from_x"], STEP_BLOCK["step_depth"]
    block = Part.makeBox(bx, by, bz)
    cutter = Part.makeBox(bx - x0 + 1.0, by + 2.0, depth + 1.0, V(x0, -1.0, bz - depth))
    return block.cut(cutter)


def build():
    for relative, maker in SOLIDS.items():
        shape = globals()[maker]()
        assert shape.isValid() and len(shape.Solids) == 1, relative
        path = HERE / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        shape.exportStep(str(path))
        # The repository stores LF fixtures (.gitattributes); bind the digest to those bytes.
        data = path.read_bytes().replace(b"\r\n", b"\n")
        path.write_bytes(data)
        print(
            f"{relative}: faces={len(shape.Faces)} "
            f"volume={shape.Volume:.6f} sha256={hashlib.sha256(data).hexdigest()}"
        )


# --- STEP text derivation (ISO 10303-21, stdlib only) -------------------------------

_RECORD = re.compile(r"#(\d+)\s*=\s*([A-Z0-9_]+)\s*\((.*)\)\s*$", re.DOTALL)


def _records(text: str) -> dict[int, tuple[str, str]]:
    body = text.split("DATA;", 1)[1].split("ENDSEC;", 1)[0]
    found = {}
    for raw in body.split(";"):
        raw = raw.strip()
        if not raw.startswith("#"):
            continue
        match = _RECORD.match(raw)
        if match is None:
            continue
        entity, kind, args = int(match[1]), match[2], match[3]
        if entity in found:
            raise ValueError(f"duplicate STEP entity #{entity}")
        found[entity] = (kind, args)
    return found


def _split_args(args: str) -> list[str]:
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


def _ref(token: str) -> int:
    return int(token.strip().lstrip("#"))


def _triple(records, entity: int) -> tuple[float, float, float]:
    kind, args = records[entity]
    assert kind in {"CARTESIAN_POINT", "DIRECTION"}, kind
    values = _split_args(args)[1].strip("() ")
    return tuple(float(v) for v in values.split(","))


def _placement(records, entity: int):
    kind, args = records[entity]
    assert kind == "AXIS2_PLACEMENT_3D", kind
    fields = _split_args(args)
    return _triple(records, _ref(fields[1])), _triple(records, _ref(fields[2]))


def _label(raw: str) -> str:
    return raw.replace("''", "'")


def faces(path: Path):
    """Every ADVANCED_FACE in file order with its reference and surface signature."""
    text = path.read_text(encoding="ascii")
    records = _records(text)
    rows = []
    ordinal = 0
    for entity, (kind, args) in records.items():  # insertion order = file order
        if kind != "ADVANCED_FACE":
            continue
        ordinal += 1
        fields = _split_args(args)
        label = _label(fields[0].strip().strip("'"))
        surface = _ref(fields[2])
        same_sense = fields[3].strip() == ".T."
        skind, sargs = records[surface]
        sfields = _split_args(sargs)
        signature = {"surface": skind}
        if skind == "PLANE":
            origin, normal = _placement(records, _ref(sfields[1]))
            signature["normal"] = normal if same_sense else tuple(-v for v in normal)
            signature["offset"] = sum(
                o * n for o, n in zip(origin, signature["normal"], strict=True)
            )
        elif skind == "CYLINDRICAL_SURFACE":
            origin, axis = _placement(records, _ref(sfields[1]))
            signature.update(axis_point=origin, axis=axis, radius=float(sfields[2]))
        rows.append(
            {
                "ref": f"#{entity}/ADVANCED_FACE[{ordinal}]/{label}",
                "entity": entity,
                "ordinal": ordinal,
                "label": label,
                **signature,
            }
        )
    return rows


def _fmt(value):
    if isinstance(value, tuple):
        return "(" + ", ".join(f"{v:.6g}" for v in value) + ")"
    if isinstance(value, float):
        return f"{value:.6g}"
    return str(value)


def main(argv: list[str]) -> int:
    args = [a for a in argv if a != "--"]
    if args[:1] == ["build"]:
        build()
        return 0
    if args[:1] == ["faces"] and len(args) > 1:
        for name in args[1:]:
            path = Path(name)
            print(f"== {path} sha256={hashlib.sha256(path.read_bytes()).hexdigest()}")
            for row in faces(path):
                extras = {
                    k: v for k, v in row.items() if k not in {"ref", "entity", "ordinal", "label"}
                }
                print(row["ref"], " ".join(f"{k}={_fmt(v)}" for k, v in extras.items()))
        return 0
    print(__doc__)
    return 2


# freecadcmd executes the file without ``__name__ == "__main__"``; FreeCAD's own flags
# precede ``--``.
_STATUS = main(sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else sys.argv[1:])
sys.stdout.flush()
if _STATUS:
    raise SystemExit(_STATUS)
