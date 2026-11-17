"""The one named style palette every setup picture draws from.

Layouts and SVG templates name a role (``class="clamp"``, or a jig-shell
group of that name), never a colour: :func:`paint` gives each role element
its style and installs the shared markers and patterns, whose ids carry a
``prechips-`` prefix so an authored picture's own ids never collide with
them. Every role differs in greyscale by lightness, pattern or line style,
not by hue alone. The legend is printed once per hobby traveler, not in each
picture, and lists only the roles that traveler's pictures draw.

Feed arrows (``arrow``) show the cutter's path over the part. On a knee mill
the table moves the other way; setup text names the table motion. Coordinate
axes and viewing-direction arrows are ``axis``: thin, labelled where drawn,
and not in the legend.
"""

from __future__ import annotations

from xml.etree import ElementTree

from prechips.cad_diagrams import ARROW, SVG_NS

_DEFS = f"""<defs xmlns="{SVG_NS}">
  <marker id="prechips-arr" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7"
      markerHeight="7" orient="auto-start-reverse">
    <path d="M0 0L10 5L0 10z" fill="#111"/>
  </marker>
  <pattern id="prechips-cut" width="6" height="6" patternUnits="userSpaceOnUse"
      patternTransform="rotate(45)">
    <rect width="6" height="6" fill="#fbe1dd"/>
    <line x1="0" y1="0" x2="0" y2="6" stroke="#b33" stroke-width="1.6"/>
  </pattern>
  <pattern id="prechips-sec" width="6" height="6" patternUnits="userSpaceOnUse"
      patternTransform="rotate(-45)">
    <rect width="6" height="6" fill="#d7e1ec"/>
    <line x1="0" y1="0" x2="0" y2="6" stroke="#333" stroke-width="0.9"/>
  </pattern>
  <pattern id="prechips-thread" width="4" height="4" patternUnits="userSpaceOnUse">
    <rect width="4" height="4" fill="#fff"/>
    <path d="M0 0L4 4M4 0L0 4" stroke="#333" stroke-width="0.8"/>
  </pattern>
  <pattern id="prechips-vise" width="6" height="6" patternUnits="userSpaceOnUse">
    <rect width="6" height="6" fill="#dcdee1"/>
    <line x1="0" y1="3" x2="6" y2="3" stroke="#9a9fa6" stroke-width="1"/>
  </pattern>
  <pattern id="prechips-plate" width="8" height="8" patternUnits="userSpaceOnUse">
    <rect width="8" height="8" fill="#e6e8ea"/>
    <line x1="4" y1="0" x2="4" y2="8" stroke="#9a9fa6" stroke-width="1"/>
  </pattern>
  <pattern id="prechips-support" width="4" height="4" patternUnits="userSpaceOnUse">
    <circle cx="2" cy="2" r="1.1" fill="#2f6b3a"/>
  </pattern>
</defs>"""

# Role styles as SVG presentation attributes, in drawing order (jig shell).
ROLES: dict[str, dict[str, str]] = {
    "paper": {"fill": "#fff"},
    "fixture-table": {"fill": "#f1f2f3", "stroke": "#7a7f86", "stroke-width": "1"},
    "fixture-vise": {
        "fill": "url(#prechips-vise)",
        "stroke": "#555",
        "stroke-width": "1.2",
    },
    "fixture-plate": {
        "fill": "url(#prechips-plate)",
        "stroke": "#555",
        "stroke-width": "1.2",
    },
    "part-rest": {"fill": "#c9cbce", "stroke": "#888", "stroke-width": "1.2"},
    "part-waste": {
        "fill": "#eeeff0",
        "stroke": "#666",
        "stroke-width": "1.2",
        "stroke-dasharray": "2 2",
    },
    "part-arriving": {
        "fill": "none",
        "stroke": "#444",
        "stroke-width": "1.3",
        "stroke-dasharray": "8 4",
    },
    "part-kept": {"fill": "#d7e1ec", "stroke": "#111", "stroke-width": "1.6"},
    "section": {"fill": "url(#prechips-sec)", "stroke": "#111", "stroke-width": "1.5"},
    "part-removed": {"fill": "url(#prechips-cut)", "stroke": "none"},
    "part-threads": {
        "fill": "url(#prechips-thread)",
        "stroke": "#555",
        "stroke-width": "0.6",
    },
    "holes": {"fill": "#fff", "stroke": "#111", "stroke-width": "1.2"},
    "hidden": {
        "fill": "none",
        "stroke": "#555",
        "stroke-width": "1.1",
        "stroke-dasharray": "4 3",
    },
    "fixture-support": {
        "fill": "url(#prechips-support)",
        "stroke": "#2f6b3a",
        "stroke-width": "1.3",
        "stroke-dasharray": "1.5 2",
    },
    "clamp": {"fill": "#6b7178", "stroke": "#111", "stroke-width": "1.2"},
    "cutter": {"fill": "#e0a800", "stroke": "#111", "stroke-width": "1.6"},
    "centre-line": {
        "fill": "none",
        "stroke": "#555",
        "stroke-width": "0.9",
        "stroke-dasharray": "16 3 3 3",
    },
    "active-face": {
        "fill": "none",
        "stroke": "#e07000",
        "stroke-width": "3",
        "stroke-linecap": "round",
    },
    "datum": {"fill": "#b22", "stroke": "#b22", "stroke-width": "2.4"},
    "arrow": {
        "stroke": "#111",
        "stroke-width": "1.5",
        "marker-end": ARROW,
    },
    "axis": {
        "fill": "none",
        "stroke": "#111",
        "stroke-width": "1",
        "marker-end": ARROW,
    },
    "dims": {"fill": "none", "stroke": "#111", "stroke-width": "1"},
    "leader": {"fill": "none", "stroke": "#333", "stroke-width": "0.9"},
    "leader-dot": {"fill": "#333", "stroke": "none"},
    "label": {"fill": "#111"},
    "label-on-clamp": {"fill": "#fff"},
    "label-halo": {
        "fill": "#111",
        "stroke": "#fff",
        "stroke-width": "4",
        "paint-order": "stroke",
    },
    "datum-label": {"fill": "#b22", "font-weight": "bold"},
    "title": {"fill": "#555", "font-style": "italic"},
}

# Legend entries in printed order: (role, text), four to a row.
LEGEND = (
    ("part-arriving", "arriving material"),
    ("part-removed", "removed this setup"),
    ("part-kept", "kept after this setup"),
    ("section", "cut section"),
    ("active-face", "cut or tapped here"),
    ("part-threads", "thread"),
    ("holes", "hole"),
    ("part-rest", "rest of bar, hardware"),
    ("part-waste", "waste, parted off"),
    ("hidden", "hidden edge"),
    ("fixture-table", "table, saw bed"),
    ("fixture-vise", "vise or chuck body"),
    ("fixture-plate", "fixture plate, fence"),
    ("fixture-support", "block, parallel, jack"),
    ("clamp", "jaw, strap, edge clamp"),
    ("cutter", "cutter, edge finder"),
    ("datum", "datum, scribed line"),
    ("arrow", "cutter path on part"),
    ("centre-line", "centre line"),
)


# Rendered elements: a role on any of these counts as drawn for the key.
_SHAPES = {
    "rect",
    "circle",
    "ellipse",
    "line",
    "polyline",
    "polygon",
    "path",
    "text",
    "tspan",
    "use",
    "image",
}


def _role(element: ElementTree.Element) -> str | None:
    """The first palette role among the element's classes; others are ignored."""
    return next(
        (name for name in element.get("class", "").split() if name in ROLES), None
    )


def paint(root: ElementTree.Element) -> set[str]:
    """Style every element whose ``class`` names a role; install the defs.

    Classes that name no role are left alone, and attributes the element
    already sets (a dash, a width) win over the role's. The palette's
    markers and patterns are installed whenever a role is drawn; their
    ``prechips-`` ids leave the picture's own ids alone, and one the picture
    already carries (a template copied from a rendered traveler) is not added
    twice. Returns the roles drawn: those of rendered elements (shapes, text,
    ``<use>``, images), own or from a group.
    """
    drawn: set[str] = set()
    stack = [(root, None)]
    while stack:
        element, inherited = stack.pop()
        role = _role(element)
        if role is not None:
            for key, value in ROLES[role].items():
                element.attrib.setdefault(key, value)
        role = role or inherited
        if role is not None and element.tag.rpartition("}")[2] in _SHAPES:
            drawn.add(role)
        stack += [(child, role) for child in element]
    if not drawn:
        return drawn
    taken = {element.get("id") for element in root.iter()}
    defs = ElementTree.fromstring(_DEFS)
    for child in list(defs):
        if child.get("id") in taken:
            defs.remove(child)
    root.insert(0, defs)
    return drawn


def legend_svg(entries: list[tuple[str, str]]) -> bytes:
    """The picture key: each (role, text) entry's swatch and meaning, four columns."""
    columns, width, row = 4, 180, 22
    root = ElementTree.Element(
        f"{{{SVG_NS}}}svg",
        {
            "width": "720",
            "height": str(row * -(-len(entries) // columns) + 6),
            "font-family": "Arial, Helvetica, sans-serif",
            "font-size": "12",
        },
    )
    root.set("viewBox", f"0 0 {root.get('width')} {root.get('height')}")
    for index, (role, text) in enumerate(entries):
        x, y = 4 + width * (index % columns), 4 + row * (index // columns)
        if role in {"active-face", "datum", "arrow", "centre-line"}:
            swatch = {"x1": x, "y1": y + 7, "x2": x + 26, "y2": y + 7}
            tag = "line"
        else:
            swatch = {"x": x, "y": y, "width": 26, "height": 14}
            tag = "rect"
        ElementTree.SubElement(
            root,
            f"{{{SVG_NS}}}{tag}",
            {"class": role, **{key: str(value) for key, value in swatch.items()}},
        )
        label = ElementTree.SubElement(
            root,
            f"{{{SVG_NS}}}text",
            {"class": "label", "x": str(x + 32), "y": str(y + 11)},
        )
        label.text = text
    paint(root)
    return ElementTree.tostring(root, encoding="unicode").encode("utf-8")
