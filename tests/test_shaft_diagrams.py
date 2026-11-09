import re
import tomllib
from pathlib import Path
from xml.etree import ElementTree

import pytest

from prechips.cad import load_cad
from prechips.cad_diagrams import render_cad_svg

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "examples/cad/pivot-shaft-v40.toml"
PLAN = ROOT / "examples/comparison/pivot-shaft.toml"
DIAGRAMS = ROOT / "examples/comparison/diagrams/pivot-shaft"
NS = "{http://www.w3.org/2000/svg}"
CAP = [
    ('"height_nominal" = 1.5', '"height_nominal" = 1.6'),
    ('"sphere_radius" = 4.1102083333333335', '"sphere_radius" = 3.9501953125'),
]


def render(name, tmp_path=None, replacements=(), **changes):
    with PLAN.open("rb") as plan:
        parameters = {**tomllib.load(plan)["parameters"], **changes}
    source = SOURCE
    if replacements:
        text = SOURCE.read_text(encoding="utf-8")
        for old, new in replacements:
            assert old in text
            text = text.replace(old, new)
        source = tmp_path / "cad.toml"
        source.write_text(text, encoding="utf-8")
    cad = load_cad(source, parameters, "harmonic_pivot_shaft")
    content = render_cad_svg((DIAGRAMS / f"{name}.svg").read_bytes(), cad, parameters)
    assert b"{{" not in content
    return ElementTree.fromstring(content)


def group(root, name):
    return [child.attrib for child in root.find(f".//*[@id='{name}']")]


def outline(root, name="kept"):
    """Upper/lower silhouette points of the first main-view body in a group."""
    path = group(root, name)[0]["d"]
    numbers = [float(n) for n in re.findall(r"-?\d+(?:\.\d+)?", path)]
    return list(zip(numbers[::2], numbers[1::2]))


def ends(root):
    """Kept radius (px) at the left and right ends, and the right-end X."""
    points = outline(root)
    axis = float(group(root, "centre")[0]["y1"])
    right_x = max(x for x, _ in points)
    right = axis - min(y for x, y in points if abs(x - right_x) < 0.01)
    return axis - points[0][1], right, right_x


def attrs(root, element_id):
    return root.find(f".//*[@id='{element_id}']").attrib


@pytest.mark.parametrize("name", ["reverse", "fit"])
def test_cad_dome_change_reshapes_embedded_profile(tmp_path, name):
    before = outline(render(name))
    after = outline(render(name, tmp_path, CAP))
    assert before != after
    # The deeper cap moves the shoulder/dome stations, not only label text.
    assert {x for x, _ in before} != {x for x, _ in after}


def test_authored_stock_grip_and_rest_pose_move_geometry():
    base = render("short")
    assert outline(render("short", stock_dia_mm=10.2), "arriving") != outline(
        base, "arriving"
    )
    # A longer projection puts the faced end (Z0 datum) further from the jaws.
    moved = render("short", short_projection_mm=18.0)
    assert float(group(moved, "datum")[0]["x1"]) > float(group(base, "datum")[0]["x1"])
    longer = render("reverse", reverse_grip_mm=30.0)
    assert float(attrs(longer, "jaw-upper")["width"]) > float(
        attrs(render("reverse"), "jaw-upper")["width"]
    )
    rest = attrs(render("supported"), "rest-pad")
    reset = attrs(render("supported", follow_rest_reset_z_mm=140.0), "rest-pad")
    assert float(reset["x"]) < float(rest["x"])


def test_setup_reversal_and_centre_only_where_supported():
    stock = {}
    for name in ("short", "supported", "reverse", "fit"):
        root = render(name)
        left, right, right_x = ends(root)
        stock[name] = (left, right)
        anchors = [
            float(g.get("transform").split("(")[1].split()[0])
            for g in root.iter(f"{NS}g")
            if (g.get("transform") or "").startswith("translate")
            and g.find(f"{NS}path") is not None
        ]
        centred = any(abs(x - right_x) < 0.5 for x in anchors)
        assert centred == (name == "supported"), name
    # Supported: stock-diameter north stub left, smaller bearing at the centre.
    assert stock["supported"][0] > stock["supported"][1] > 0
    # Reversed: bearing body in the chuck, dome apex exposed on the right.
    assert stock["reverse"][0] > 0 and stock["reverse"][1] == 0
    assert stock["fit"][0] > 0 and stock["fit"][1] == 0
