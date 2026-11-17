"""The one named style palette every setup picture draws from.

Layouts and SVG templates name a role (``class="clamp"``, or a jig-shell
group of that name), never a colour: :func:`paint` gives each role element
its style and installs the shared markers and patterns. Every role differs in
greyscale by lightness, pattern or line style, not by hue alone. The legend is
printed once per hobby traveler, not in each picture.

Feed arrows (``arrow``) show the cutter's path over the part. On a knee mill
the table moves the other way; setup text names the table motion.
"""

from __future__ import annotations

from xml.etree import ElementTree

SVG_NS = "http://www.w3.org/2000/svg"
ElementTree.register_namespace("", SVG_NS)

_DEFS = f"""<defs xmlns="{SVG_NS}">
  <marker id="arr" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7"
      markerHeight="7" orient="auto-start-reverse">
    <path d="M0 0L10 5L0 10z" fill="#111"/>
  </marker>
  <pattern id="cut" width="6" height="6" patternUnits="userSpaceOnUse"
      patternTransform="rotate(45)">
    <rect width="6" height="6" fill="#fbe1dd"/>
    <line x1="0" y1="0" x2="0" y2="6" stroke="#b33" stroke-width="1.6"/>
  </pattern>
  <pattern id="thread" width="4" height="4" patternUnits="userSpaceOnUse">
    <rect width="4" height="4" fill="#fff"/>
    <path d="M0 0L4 4M4 0L0 4" stroke="#333" stroke-width="0.8"/>
  </pattern>
  <pattern id="vise" width="6" height="6" patternUnits="userSpaceOnUse">
    <rect width="6" height="6" fill="#dcdee1"/>
    <line x1="0" y1="3" x2="6" y2="3" stroke="#9a9fa6" stroke-width="1"/>
  </pattern>
  <pattern id="support" width="4" height="4" patternUnits="userSpaceOnUse">
    <circle cx="2" cy="2" r="1.1" fill="#2f6b3a"/>
  </pattern>
</defs>"""

# Role styles as SVG presentation attributes, in drawing order (jig shell).
ROLES: dict[str, dict[str, str]] = {
    "paper": {"fill": "#fff"},
    "fixture-table": {"fill": "#f1f2f3", "stroke": "#7a7f86", "stroke-width": "1"},
    "fixture-vise": {"fill": "url(#vise)", "stroke": "#555", "stroke-width": "1.2"},
    "part-rest": {"fill": "#c9cbce", "stroke": "#888", "stroke-width": "1.2"},
    "part-arriving": {
        "fill": "none",
        "stroke": "#444",
        "stroke-width": "1.3",
        "stroke-dasharray": "8 4",
    },
    "part-kept": {"fill": "#d7e1ec", "stroke": "#111", "stroke-width": "1.6"},
    "part-removed": {"fill": "url(#cut)", "stroke": "none"},
    "part-threads": {"fill": "url(#thread)", "stroke": "#555", "stroke-width": "0.6"},
    "holes": {"fill": "#fff", "stroke": "#111", "stroke-width": "1.2"},
    "hidden": {
        "fill": "none",
        "stroke": "#555",
        "stroke-width": "1.1",
        "stroke-dasharray": "4 3",
    },
    "fixture-support": {
        "fill": "url(#support)",
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
    "arrow": {"stroke": "#111", "stroke-width": "1.5", "marker-end": "url(#arr)"},
    "dims": {"fill": "none", "stroke": "#111", "stroke-width": "1"},
    "leader": {"fill": "none", "stroke": "#333", "stroke-width": "0.9"},
    "label": {"fill": "#111"},
    "title": {"fill": "#555", "font-style": "italic"},
}

# Legend entries in printed order: (role, text), four to a row.
LEGEND = (
    ("part-arriving", "arriving material"),
    ("part-removed", "removed this setup"),
    ("part-kept", "kept after this setup"),
    ("active-face", "cut or tapped here"),
    ("part-threads", "thread"),
    ("holes", "hole"),
    ("part-rest", "rest of bar, hardware"),
    ("hidden", "hidden edge"),
    ("fixture-table", "table, saw bed"),
    ("fixture-vise", "vise or chuck body"),
    ("fixture-support", "block, parallel, jack"),
    ("clamp", "jaw, strap, soft jaw"),
    ("cutter", "end mill, drill, tap"),
    ("datum", "datum, scribed line"),
    ("arrow", "cutter path on part"),
    ("centre-line", "centre line"),
)


def colour(role: str) -> str:
    """The role's ink: its stroke, or its fill for fill-only roles."""
    style = ROLES[role]
    return style.get("stroke", style.get("fill", ""))


def paint(root: ElementTree.Element) -> bool:
    """Style every element naming a role in ``class``; install the defs.

    Attributes the element already sets (a dash, a width) win over the role's.
    Returns whether any role was used.
    """
    used = False
    for element in root.iter():
        role = element.get("class")
        if role is None:
            continue
        if role not in ROLES:
            raise ValueError(f"unknown picture role {role!r}")
        for key, value in ROLES[role].items():
            element.attrib.setdefault(key, value)
        used = True
    if used:
        root.insert(0, ElementTree.fromstring(_DEFS))
    return used


def legend_svg() -> bytes:
    """The picture key: every legend role's swatch and meaning, four columns."""
    columns, width, row = 4, 180, 22
    root = ElementTree.Element(
        f"{{{SVG_NS}}}svg",
        {
            "width": "720",
            "height": str(row * -(-len(LEGEND) // columns) + 6),
            "font-family": "Arial, Helvetica, sans-serif",
            "font-size": "12",
        },
    )
    root.set("viewBox", f"0 0 {root.get('width')} {root.get('height')}")
    for index, (role, text) in enumerate(LEGEND):
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
            root, f"{{{SVG_NS}}}text", {"x": str(x + 32), "y": str(y + 11)}
        )
        label.text = text
    paint(root)
    return ElementTree.tostring(root, encoding="unicode").encode("utf-8")
