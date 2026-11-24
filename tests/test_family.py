"""A family plan: several parts' manifests on one traveler."""

import subprocess
from pathlib import Path

import pytest

from prechips.profiles import HOBBY
from prechips.traveler import PlanError, load_plan, render_traveler, setups_serving

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


def _cli(
    plan: Path, out: Path, profile: str, *more: str
) -> subprocess.CompletedProcess:
    return subprocess.run(
        [
            "prechips",
            "traveler",
            str(plan),
            "--profile",
            profile,
            "--out",
            str(out),
            *more,
        ],
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


# The back alone on a 1.8 in blank: the shared text names the front's length,
# so only the back's own reading of the plan can refuse it.
_BACK_BLANK_TOO_SHORT = (
    ("{{process.blank_length_min_in", "{{process.front.blank_length_min_in"),
    (
        'part = "clamp-back"\n',
        'part = "clamp-back"\n[parts.parameters]\nblank_length_min_in = 1.8\n',
    ),
    (
        "\n[parts.parameters]\nother_half_depth_min_mm = 17.272",
        "\nother_half_depth_min_mm = 17.272",
    ),
)


def test_every_part_passes_its_own_stock_fit(tmp_path):
    from prechips.stock import StockError, check_stock_fit

    loaded = load_plan(DEMO)
    check_stock_fit(loaded)
    # The clamp adapter refuses a short blank itself, so the comparison is
    # reached with the back's parameters changed after its manifest is read.
    cad, parameters = loaded.parts["back"]
    loaded.parts["back"] = (cad, parameters | {"blank_length_min_in": 1.8})
    with pytest.raises(StockError, match=r"stock_fit: length: .*\(part back\)"):
        check_stock_fit(loaded)
    # From the command line the adapter names the part first; nothing is written.
    out = tmp_path / "pair.html"
    result = _cli(_copy(tmp_path, DEMO, *_BACK_BLANK_TOO_SHORT), out, "pro")
    assert result.returncode == 2
    assert "parts[2] (back): process.blank_length_min_in" in result.stderr
    assert not out.exists()


def test_a_one_part_plan_has_no_parts_to_name(tmp_path):
    plan = _copy(tmp_path, SINGLE, ("[[setups]]\n", '[[setups]]\npart = "front"\n'))
    with pytest.raises(PlanError, match=r"setups\[1\]\.part: requires \[\[parts\]\]"):
        load_plan(plan)
    with pytest.raises(PlanError, match="unknown binding cad.front.width_mm"):
        load_plan(
            _copy(tmp_path, SINGLE, ('title = "', 'title = "{{cad.front.width_mm}} '))
        )


def test_tool_numbers_and_programs_print_once_for_the_whole_sheet(tmp_path):
    out = tmp_path / "pair.html"
    assert _cli(DEMO, out, "pro").returncode == 0
    html = out.read_text(encoding="utf-8")
    # The tool list and every operation call a tool by its one T number.
    assert '<td class="text">T3 #9 (.1960 in) drill' in html
    assert '<div class="text tool">T3 #9 drill</div>' in html
    assert '<div class="text tool">T4 #29 drill</div>' in html
    # A tool no program calls has no number.
    assert '<div class="text tool">Files</div>' in html
    assert "<dt>NC:</dt><dd>pair-bore.nc, bore-open.nc</dd>" in html


@pytest.mark.parametrize(
    ("old", "new", "message"),
    [
        (
            'id = "drill-29"\nnumber = 4',
            'id = "drill-29"\nnumber = 3',
            r"tools\[4\]\.number: T3 is already tool 'drill-9'",
        ),
        ('id = "spot"\nnumber = 2', 'id = "spot"\nnumber = 0', "positive integer"),
        (
            'programs = ["first-end.nc"]',
            'programs = ["first-end.nc", "first-end.nc"]',
            r"setups\[2\]\.programs: expected a nonempty array of distinct names",
        ),
        (
            'serves = ["front", "back"]',
            'serves = ["front", "rear"]',
            r"serves: unknown part 'rear'",
        ),
        (
            'serves = ["front", "back"]',
            'serves = ["front"]',
            r"serves: expected to include its part 'back'",
        ),
    ],
)
def test_number_program_and_serves_refusals(tmp_path, old, new, message):
    with pytest.raises(PlanError, match=message):
        load_plan(_copy(tmp_path, DEMO, (old, new)))


def test_serves_needs_a_family(tmp_path):
    plan = _copy(tmp_path, SINGLE, ("[[setups]]\n", '[[setups]]\nserves = ["a"]\n'))
    with pytest.raises(PlanError, match=r"setups\[1\]\.serves: requires \[\[parts\]\]"):
        load_plan(plan)


def test_a_setup_serves_its_part_or_every_part_unless_it_says():
    plan = load_plan(DEMO)
    front = [number for number, _ in setups_serving(plan, "front")]
    back = [number for number, _ in setups_serving(plan, "back")]
    # Setup 7 is the fronts', 8 and 11 the backs'; 10 names the back, whose
    # values it prints, and serves both: the pair is bored bolted together.
    assert front == [1, 2, 3, 4, 5, 6, 7, 9, 10, 12]
    assert back == [1, 2, 3, 4, 5, 6, 8, 9, 10, 11, 12]


def test_a_placeholder_points_one_part_to_the_shared_traveler(tmp_path):
    out = tmp_path / "front.html"
    result = _cli(
        DEMO, out, "hobby", "--placeholder", "front", "--shared-file", "pair.pdf"
    )
    assert result.returncode == 0, result.stderr
    html = out.read_text(encoding="utf-8")
    assert "<h1>DEMO-CLAMP-FRONT demo clamp front</h1>" in html
    assert (
        "shared traveler <strong>Demo clamp pair: front and back</strong> "
        "(file pair.pdf)" in html
    )
    assert "together with DEMO-CLAMP-BACK demo clamp back" in html
    # Its setups only, each with the programs it runs; no setup page follows.
    assert "Setup 7 — Fronts: outside face" in html
    assert "Setup 8 — Backs:" not in html
    assert "Setup 10 — Pair bore" in html and "pair-bore.nc, bore-open.nc" in html
    assert "<section>" not in html and "<img" not in html
    # Both profiles print the same placeholder.
    pro = tmp_path / "front-pro.html"
    result = _cli(
        DEMO, pro, "pro", "--placeholder", "front", "--shared-file", "pair.pdf"
    )
    assert result.returncode == 0, result.stderr
    assert pro.read_text(encoding="utf-8") == html


def test_a_placeholder_is_refused_with_its_traveler(tmp_path):
    # Not a part of the family; not a family; a plan that refuses.
    out = tmp_path / "x.html"
    result = _cli(DEMO, out, "pro", "--placeholder", "rear")
    assert result.returncode == 2 and "unknown part 'rear'" in result.stderr
    result = _cli(SINGLE, out, "pro", "--placeholder", "front")
    assert result.returncode == 2 and "no [[parts]]" in result.stderr
    result = _cli(DEMO, out, "pro", "--shared-file", "pair.pdf")
    assert result.returncode == 2 and "requires --placeholder" in result.stderr
    broken = _copy(tmp_path, DEMO, *_BACK_BLANK_TOO_SHORT)
    result = _cli(broken, out, "pro", "--placeholder", "front")
    assert result.returncode == 2
    assert "parts[2] (back): process.blank_length_min_in" in result.stderr
    assert not out.exists()
    # The traveler's own refusals hold too: a picture it cannot draw.
    unseen = _copy(
        tmp_path, DEMO, ("diagrams/demo-clamp-pair/saw.svg", "diagrams/none.svg")
    )
    result = _cli(unseen, out, "hobby", "--placeholder", "front")
    assert result.returncode == 2 and "none.svg" in result.stderr
    assert not out.exists()


def test_values_alike_but_for_noise_bind_the_same_whichever_part_is_first():
    from prechips.cad import Agreed

    small, other = (
        {"gap_mm": 1e-10, "runs": [0.1 + 0.2]},
        {"gap_mm": 2e-10, "runs": [0.3]},
    )
    for tables in ({"a": small, "b": other}, {"b": other, "a": small}):
        agreed = Agreed("process", tables)
        assert agreed["gap_mm"] == 0.0 and agreed["runs"] == [0.3]
    for tables in (
        {"a": {"x": -0.0}, "b": {"x": 0.0}},
        {"b": {"x": 0.0}, "a": {"x": -0.0}},
    ):
        assert repr(Agreed("process", tables)["x"]) == "0.0"
    # Values given exactly alike stay as computed.
    assert Agreed("process", {"a": small, "b": dict(small)})["gap_mm"] == 1e-10


def test_part_titles_and_pictures_bind_qualified_tokens_and_their_own_part(tmp_path):
    svg = tmp_path / "plain.svg"
    svg.write_text(
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10">'
        "<text>{{cad.depth_in:.3dot}} / {{cad.front.depth_in:.3dot}}</text></svg>",
        encoding="utf-8",
    )
    plan = _copy(
        tmp_path,
        DEMO,
        (
            'title = "{{cad.drawing_number}} demo clamp front"',
            'title = "{{cad.drawing_number}} front, mate {{cad.back.drawing_number}}"',
        ),
        (
            (
                f'file = "{DEMO.parent.as_posix()}/diagrams/demo-clamp-pair/mating.svg", '
                'part = "back", alt = "A back held the same way,'
            ),
            (
                f'file = "{svg.as_posix()}", part = "back", '
                'alt = "A back {{cad.depth_in:.3dot}} deep '
                "({{cad.front.depth_in:.3dot}} the front) held the same way,"
            ),
        ),
    )
    loaded = load_plan(plan)
    cad = {part: loaded.parts[part][0].values for part in ("front", "back")}
    front, back = (f"{cad[part]['depth_in']:.3f}".lstrip("0") for part in cad)
    assert front != back
    # A title names another part's value beside its own.
    numbers = [cad[part]["drawing_number"] for part in cad]
    assert loaded.titles["front"] == f"{numbers[0]} front, mate {numbers[1]}"
    # The picture names the back inside a setup that names no part: its alt
    # text and its authored SVG bind the back's values, and the front's by name.
    alts = [
        operation["diagram"]["alt"]
        for setup in loaded.data["setups"]
        for operation in setup["operations"]
        if "A back " in operation.get("diagram", {}).get("alt", "")
    ]
    assert any(
        alt.startswith(f"A back {back} deep ({front} the front) held") for alt in alts
    ), alts
    import base64
    import re

    html = render_traveler(loaded, profile=HOBBY)
    pictures = [
        base64.b64decode(data).decode("utf-8")
        for data in re.findall(r"data:image/svg\+xml;base64,([A-Za-z0-9+/=]+)", html)
    ]
    assert any(f"<text>{back} / {front}</text>" in picture for picture in pictures)


def test_a_template_picture_takes_qualified_tokens():
    from prechips.cad_diagrams import render_cad_svg

    loaded = load_plan(DEMO)
    template = (DEMO.parent / "diagrams/demo-clamp-pair/mating.svg").read_text(
        encoding="utf-8"
    )
    assert "data-cad-template" in template
    marked = template.replace(
        "/>", "><text>other {{cad.back.depth_in:.3dot}}</text></svg>"
    )
    assert marked != template
    back = f"{loaded.parts['back'][0].values['depth_in']:.3f}".lstrip("0")
    drawn = render_cad_svg(
        marked.encode("utf-8"), *loaded.parts["front"], parts=loaded.parts
    ).decode("utf-8")
    assert f"other {back}</" in drawn


def test_a_captioned_picture_cannot_be_split_from_its_caption():
    html = render_traveler(load_plan(DEMO), profile=HOBBY)
    whole = ' style="display: inline-block; width: 100%"><figcaption'
    captions = html.count("<figcaption")
    assert captions and html.count(whole) == captions
    # A picture without a caption keeps its plain figure.
    single = render_traveler(load_plan(SINGLE), profile=HOBBY)
    assert "<figcaption" not in single and "inline-block" not in single
