"""A family plan: several parts' manifests on one traveler."""

import subprocess
from pathlib import Path

import pytest

from prechips.traveler import PlanError, load_plan

ROOT = Path(__file__).resolve().parents[1]
DEMO = ROOT / "examples/demo-clamp-pair.toml"
SINGLE = ROOT / "examples/demo-hex-block.toml"


def _copy(tmp_path: Path, source: Path, *edits: tuple[str, str]) -> Path:
    """``source`` in ``tmp_path`` with its relative inputs made absolute."""
    examples = source.parent.as_posix()
    text = source.read_text(encoding="utf-8")
    for old, new in (
        ('shop = "shop.toml"', f'shop = "{examples}/shop.toml"'),
        ('file = "cad/', f'file = "{examples}/cad/'),
        ('file = "diagrams/', f'file = "{examples}/diagrams/'),
        *edits,
    ):
        assert old in text, old
        text = text.replace(old, new)
    plan = tmp_path / source.name
    plan.write_text(text, encoding="utf-8")
    return plan


def _cli(plan: Path, out: Path, profile: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["prechips", "traveler", str(plan), "--profile", profile, "--out", str(out)],
        capture_output=True,
        check=False,
        text=True,
        encoding="utf-8",
    )


@pytest.mark.parametrize("profile", ["pro", "hobby"])
def test_demo_pair_renders_one_traveler_for_both_parts(tmp_path, profile):
    out = tmp_path / "pair.html"
    result = _cli(DEMO, out, profile)
    assert result.returncode == 0, result.stderr
    html = out.read_text(encoding="utf-8")
    assert "DEMO-CLAMP-FRONT front, DEMO-CLAMP-BACK back" in html
    assert html.count("<section>") == 12
    # A picture that names its own part is captioned with that part's label.
    assert ("<figcaption" in html) == (profile == "hobby")


def test_text_binds_its_own_part_or_what_the_parts_share():
    plan = load_plan(DEMO)
    assert set(plan.parts) == {"front", "back"}
    setups = plan.data["setups"]
    # Shared setups print values both manifests give alike.
    assert "1.8900" in setups[2]["operations"][0]["instruction"]
    # A setup's part scopes its bare tokens: each half faces to its own depth.
    assert setups[6]["part"] == "front" and setups[7]["part"] == "back"
    assert ".6850" in setups[6]["operations"][0]["instruction"]
    assert ".6100" in setups[7]["operations"][0]["instruction"]
    # An operation's part does the same inside a shared setup.
    assert ".600–.620" in setups[8]["operations"][1]["inspection"]
    # Qualified tokens name a part anywhere, here in Setup 1's table.
    rows = setups[0]["operations"][0]["table"]["rows"]
    assert rows[2][1:] == [
        ".680–.690",
        ".580–.600 (.600–.620 until Setup 11's face-off)",
    ]
    # Each part's own parameters lie over the plan's.
    assert plan.parts["front"][1]["peck_mm"] != plan.parts["back"][1]["peck_mm"]
    assert plan.parts["front"][1]["quantity"] == plan.parts["back"][1]["quantity"]


@pytest.mark.parametrize(
    ("old", "new", "message"),
    [
        # A value the halves give differently, in text that names no part.
        (
            '["Depth, mating face to outside face", "{{cad.front.depth_min_in',
            '["Depth, mating face to outside face", "{{cad.depth_min_in',
            r"cad\.depth_min_in differs between parts \(front, back\)",
        ),
        # A value only one half has.
        (
            "at least {{cad.front.ear_wall_min_in:.3dot}}",
            "at least {{cad.ear_wall_min_in:.3dot}}",
            r"cad\.ear_wall_min_in differs between parts",
        ),
        ("{{cad.back.ear_thread}}", "{{cad.rear.ear_thread}}", "unknown binding"),
        (
            'machine_kind = "other"\npart = "front"',
            'machine_kind = "other"\npart = "rear"',
            "unknown part 'rear'",
        ),
    ],
)
def test_family_plan_refusals(tmp_path, old, new, message):
    with pytest.raises(PlanError, match=message):
        load_plan(_copy(tmp_path, DEMO, (old, new)))


def test_a_shared_picture_the_parts_draw_differently_must_name_one(tmp_path):
    # The halves' mating-skim pictures put the near side at opposite ends.
    plan = _copy(
        tmp_path, DEMO, ('mating.svg", part = "front", alt', 'mating.svg", alt')
    )
    out = tmp_path / "pair.html"
    result = _cli(plan, out, "hobby")
    assert result.returncode == 2
    assert "the parts draw it differently" in result.stderr
    assert not out.exists()


def test_every_part_passes_its_own_stock_fit(tmp_path):
    plan = _copy(
        tmp_path,
        DEMO,
        (
            'part = "clamp-back"\n',
            'part = "clamp-back"\n[parts.parameters]\nblank_section_in = 0.5\n',
        ),
        (
            "\n[parts.parameters]\nother_half_depth_min_mm = 17.272",
            "\nother_half_depth_min_mm = 17.272",
        ),
    )
    result = _cli(plan, tmp_path / "pair.html", "pro")
    assert result.returncode == 2
    assert "back" in result.stderr


def test_a_one_part_plan_has_no_parts_to_name(tmp_path):
    plan = _copy(tmp_path, SINGLE, ("[[setups]]\n", '[[setups]]\npart = "front"\n'))
    with pytest.raises(PlanError, match=r"setups\[1\]\.part: requires \[\[parts\]\]"):
        load_plan(plan)
    with pytest.raises(PlanError, match="unknown binding cad.front.width_mm"):
        load_plan(
            _copy(tmp_path, SINGLE, ('title = "', 'title = "{{cad.front.width_mm}} '))
        )
