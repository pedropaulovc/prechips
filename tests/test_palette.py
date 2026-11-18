import base64
import re
from pathlib import Path
from xml.etree import ElementTree

import pytest

from prechips.palette import LEGEND, ROLES, legend_svg, paint
from prechips.profiles import HOBBY
from prechips.traveler import load_plan, render_traveler

ROOT = Path(__file__).resolve().parents[1]
PLANS = sorted(
    path for path in (ROOT / "examples").glob("*.toml") if path.name != "shop.toml"
) + [ROOT / "examples/comparison/demo-pivot-shaft.toml"]
COLOUR_ATTRIBUTES = ("fill", "stroke", "color", "stop-color", "flood-color")
IMAGE = re.compile(r'src="data:image/svg\+xml;base64,([^"]+)"')


def _palette_ids() -> set[str]:
    probe = ElementTree.fromstring(
        '<svg xmlns="http://www.w3.org/2000/svg"><rect class="paper"/></svg>'
    )
    paint(probe)
    return {element.get("id") for element in probe.iter() if element.get("id")}


@pytest.mark.parametrize("plan", PLANS, ids=lambda path: path.stem)
def test_hobby_pictures_take_every_colour_from_a_palette_role(plan):
    html = render_traveler(load_plan(plan), profile=HOBBY)
    pictures = IMAGE.findall(html)
    assert pictures
    palette_ids = _palette_ids()
    found = []
    for number, picture in enumerate(pictures):
        root = ElementTree.fromstring(base64.b64decode(picture))
        stack = [root]
        while stack:
            element = stack.pop()
            if element.tag.rpartition("}")[2] == "defs":
                # Only the palette's own markers and patterns may carry colour.
                found += [
                    f"picture {number}: defs #{child.get('id')}"
                    for child in element
                    if child.get("id") not in palette_ids
                ]
                continue
            role = next(
                (name for name in element.get("class", "").split() if name in ROLES),
                None,
            )
            if "style" in element.attrib:
                found.append(f"picture {number}: style={element.get('style')!r}")
            for key in COLOUR_ATTRIBUTES:
                value = element.get(key)
                if value is None or value == "none":
                    continue
                if role is None or ROLES[role].get(key) != value:
                    found.append(f"picture {number}: {key}={value!r} on {role}")
            stack += list(element)
    assert found == []


def test_a_fixture_plate_and_its_edge_clamps_draw_by_role_and_enter_the_key():
    svg = "{http://www.w3.org/2000/svg}"
    root = ElementTree.fromstring(
        '<svg xmlns="http://www.w3.org/2000/svg">'
        '<rect class="fixture-plate" width="330" height="76"/>'
        '<rect class="fixture-plate" width="330" height="10"/>'
        '<rect class="clamp" x="40" y="60" width="16" height="12"/>'
        "</svg>"
    )
    assert paint(root) == {"fixture-plate", "clamp"}
    plate, _fence, clamp = root.findall(f"{svg}rect")
    assert plate.get("fill") == "url(#prechips-plate)"
    assert root.find(f"{svg}defs/{svg}pattern[@id='prechips-plate']") is not None
    # Distinct from the table, the vise body and the clamps in greyscale.
    looks = [ROLES[role] for role in ("fixture-table", "fixture-vise", "clamp")]
    assert all(ROLES["fixture-plate"]["fill"] != look["fill"] for look in looks)
    assert clamp.get("fill") == ROLES["clamp"]["fill"]
    entries = [entry for entry in LEGEND if entry[0] in {"fixture-plate", "clamp"}]
    key = legend_svg(entries).decode("utf-8")
    assert "fixture plate, fence" in key and "jaw, clamp" in key
