import base64
import re
from pathlib import Path
from xml.etree import ElementTree

import pytest

from prechips.palette import (
    CSS_WIDE_KEYWORDS,
    FONT_FAMILY,
    GENERIC_FAMILIES,
    LEGEND,
    MONO_FAMILY,
    ROLES,
    declare_font,
    legend_svg,
    paint,
)
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


@pytest.fixture(scope="module", params=PLANS, ids=lambda path: path.stem)
def hobby_pictures(request):
    """Each example plan's hobby pictures, rendered once for every test here."""
    pictures = IMAGE.findall(render_traveler(load_plan(request.param), profile=HOBBY))
    assert pictures
    return pictures


def test_hobby_pictures_take_every_colour_from_a_palette_role(hobby_pictures):
    pictures = hobby_pictures
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
    assert "fixture plate, fence" in key and "vise jaw, work holder" in key


def test_key_labels_fit_their_column():
    # A column leaves 148 px for a 12 px label; the widest that fits is
    # about 27 characters of this text.
    assert max(len(label) for _, label in LEGEND) <= 27


@pytest.mark.parametrize(
    "family, style, declared, changed",
    [
        (None, None, FONT_FAMILY, True),
        ("sans-serif", None, FONT_FAMILY, True),
        ("' Sans-Serif ', ''", None, FONT_FAMILY, True),
        ("''", None, FONT_FAMILY, True),
        ("sans-serif, Verdana", None, FONT_FAMILY, True),
        ("inherit", None, FONT_FAMILY, True),
        ("monospace", None, MONO_FAMILY, True),
        ("Verdana, sans-serif", None, "Verdana, sans-serif", False),
        ("'Courier New'", None, "'Courier New'", False),
        (FONT_FAMILY, None, FONT_FAMILY, False),
        # The inline style wins over the attribute, as in CSS.
        ("Verdana", "fill: none; font-family: serif", FONT_FAMILY, True),
        (None, "font-family: Verdana, sans-serif", None, False),
    ],
)
def test_a_picture_naming_no_real_font_prints_in_the_sheet_font(
    family, style, declared, changed
):
    # An <img> SVG does not inherit the page's CSS: without a named family its
    # text takes the printing browser's default, which differs by machine.
    root = ElementTree.fromstring(
        '<svg xmlns="http://www.w3.org/2000/svg"><text>a</text></svg>'
    )
    for key, value in (("font-family", family), ("style", style)):
        if value is not None:
            root.set(key, value)
    assert declare_font(root) is changed
    assert root.get("font-family") == declared
    if changed and style is not None:
        # A replaced font leaves the style, so the attribute is what prints.
        assert "font-family" not in root.get("style", "")


def test_text_inside_a_picture_naming_no_real_font_prints_in_the_sheet_font():
    root = ElementTree.fromstring(
        '<svg xmlns="http://www.w3.org/2000/svg" font-family="Verdana">'
        '<g font-family="sans-serif"><text>a</text></g>'
        '<text style="font-family: monospace">b</text>'
        '<text font-family="Georgia, serif">c</text>'
        '<text font-family="inherit">d</text>'
        "</svg>"
    )
    assert declare_font(root) is True
    group, mono, named, inherited = root
    assert group.get("font-family") == FONT_FAMILY
    assert mono.get("font-family") == MONO_FAMILY and mono.get("style") is None
    assert named.get("font-family") == "Georgia, serif"
    assert inherited.get("font-family") == "inherit"


def test_every_hobby_picture_names_a_real_font(hobby_pictures):
    for picture in hobby_pictures:
        family = ElementTree.fromstring(base64.b64decode(picture)).get("font-family")
        primary = (family or "").split(",")[0].strip().strip("'\"").strip().lower()
        assert primary not in {"", *GENERIC_FAMILIES, *CSS_WIDE_KEYWORDS}, family
