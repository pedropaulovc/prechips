import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
# A quoted hex colour: "#abc" or "#aabbcc" (issue numbers in comments are not).
HEX = re.compile(r"""["']#[0-9a-fA-F]{3}(?:[0-9a-fA-F]{3})?["']""")


def test_pictures_take_colours_only_from_the_palette():
    sources = [
        *(ROOT / "src/prechips").glob("*.py"),
        *(ROOT / "examples").rglob("*.svg"),
    ]
    found = [
        f"{path.relative_to(ROOT)}: {match.group()}"
        for path in sources
        if path.name != "palette.py"
        for match in HEX.finditer(path.read_text(encoding="utf-8"))
    ]
    assert found == []
