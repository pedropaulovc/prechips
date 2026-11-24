import re
from pathlib import Path

import pytest

from prechips.cad import CadError
from prechips.cad_joined_hub import load_joined_hub
from prechips.cli import main

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "examples/cad/joined-hub-v51.toml"
PLAN = ROOT / "examples/demo-joined-hub.toml"
SUPPLY = {
    "hub_land_min_in": 0.4975,
    "hub_land_max_in": 0.4990,
    "hub_supply_length_min_in": 0.37,
    "hub_supply_length_max_in": 0.40,
    "bond_offset_max_in": 0.009,
}


@pytest.mark.parametrize(("profile", "pictures"), [("pro", 0), ("hobby", 4)])
def test_the_demo_renders_with_every_check(tmp_path, profile, pictures):
    out = tmp_path / "lever.html"
    assert main(["traveler", str(PLAN), "--profile", profile, "--out", str(out)]) == 0
    html = out.read_text(encoding="utf-8")
    assert "DEMO-JOINED-LEVER" in html and "v51" in html
    assert html.count('class="setup-diagram"') == pictures


def test_members_heights_and_offsets_follow_the_manifest():
    cad = load_joined_hub(SOURCE, SUPPLY, "joined-lever")
    values = cad.values
    assert values["hub_dia_band_mm"] == [12.446, 12.954]
    assert values["bore_dia_band_mm"] == [6.5278, 6.6294]
    assert values["bore_drill"] == "F"
    assert values["hub_length_band_mm"] == [7.5184, 7.7216]
    assert values["strap_thickness_band_mm"] == [3.1496, 3.2004]
    # The members' nominals, declared in either spelling.
    assert values["hub_dia_mm"] == pytest.approx(12.7)
    assert values["bore_dia_mm"] == pytest.approx(6.5278)
    # (.300 − .125)/2 = .0875 lies between two readings; .087 and .088 each
    # leave .002 in the .296–.304 band, so the nearer-then-lower .087 prints.
    assert values["hub_end_height_in"] == pytest.approx(0.087)
    assert values["hub_end_height_mm"] == pytest.approx(0.087 * 25.4)
    assert values["bore_depth_mm"] == pytest.approx(7.62)
    assert values["pin_hole_from_bore_x_mm"] == pytest.approx(50.8)
    assert values["pin_hole_from_bore_y_mm"] == pytest.approx(6.35)
    assert values["pin_hole_from_bore_mm"] == pytest.approx(51.1953, abs=1e-4)
    assert "pin_hole_from_bore_z_mm" not in values
    # Shortest hub (.37), thickest strap, offset toward the end: .026 off;
    # longest (.40), thinnest, offset away: .060.
    assert values["face_depth_min_in"] == pytest.approx(0.026)
    assert values["face_depth_max_in"] == pytest.approx(0.060)
    assert values["hub_end_supply_max_in"] == pytest.approx(0.147)
    assert values["hub_land_band_mm"] == pytest.approx([12.6365, 12.6746])
    # Every feature also binds by name; a table field binds nothing.
    assert values["outline_surface_profile_in"] == pytest.approx(0.02)
    assert not any(key.startswith("outline_surface_profile_governs") for key in values)
    assert values["hub_root_radius_max_in"] == pytest.approx(0.01)
    required = {axis.name: axis.required_mm for axis in cad.stock_requirement.axes}
    assert required == {"hub length": 7.7216}


def _manifest(tmp_path, old: str, new: str) -> Path:
    text = SOURCE.read_text(encoding="utf-8")
    assert old in text
    path = tmp_path / "joined.toml"
    path.write_text(text.replace(old, new, 1), encoding="utf-8")
    return path


@pytest.mark.parametrize(
    ("old", "new", "message"),
    [
        # The drawing must permit the built-up part.
        (
            'construction = "built_up_permitted"',
            'construction = "one_piece"',
            "built-up",
        ),
        # One boss, the hub.
        ('kind = "boss"', 'kind = "face"', "exactly one boss"),
        # The bore lies on the hub's axis; off it, the axis has no plain hole.
        (
            "at = [0.0, 0.0, 0.0]\naxis = [0.0, 0.0, 1.0]\ndia = [6.5278",
            "at = [0.5, 0.0, 0.0]\naxis = [0.0, 0.0, 1.0]\ndia = [6.5278",
            "plain hole on the hub's axis (pivot_bore lies off it, inside the hub)",
        ),
        # A tapped strap hole is sized by its thread's major.
        (
            "[features.outline]",
            (
                '[features.tap]\nkind = "threaded_hole"\nframe = "model"\n'
                'requirements = ["thread", "thru"]\nat = [7.0, 0.0, 0.0]\n'
                'axis = [0.0, 0.0, 1.0]\nthread = "#10-32 UNF-2B"\nthru = true\n\n'
                "[features.outline]"
            ),
            "tap: a strap hole cutting into the hub",
        ),
        # A malformed requirements list is refused, never a traceback.
        (
            'requirements = ["radius", "surface_profile"]',
            "requirements = 5",
            "outline",
        ),
        # The hole on the hub's axis is a plain hole.
        (
            '[features.pivot_bore]\nkind = "hole"',
            '[features.pivot_bore]\nkind = "threaded_hole"',
            "exactly one plain hole on the hub's axis",
        ),
        # Every hole runs along the hub's axis.
        (
            "at = [50.8, 6.35, 0.0]\naxis = [0.0, 0.0, 1.0]",
            "at = [50.8, 6.35, 0.0]\naxis = [1.0, 0.0, 0.0]",
            "parallel to the hub's axis",
        ),
        # Facing each end from its own face cannot hold this tight a length.
        ("length = [7.5184, 7.7216]", "length = [7.6073, 7.6327]", "length band"),
        # The strap's thickness is one band.
        (
            "thickness = [3.1496, 3.2004]\nthickness_nominal = 3.175",
            "thickness = [3.1496, 3.2004]\nthickness_nominal = 3.2512",
            "outside its band",
        ),
        # Names collide with the members' own keys.
        ("[features.pivot_bore]", "[features.bore]", "bound twice"),
        # A strap hole may not cut into the hub.
        ("at = [50.8, 6.35, 0.0]", "at = [4.0, 0.0, 0.0]", "cutting into the hub"),
        # A listed requirement written as a table is refused, not dropped.
        (
            "position_dia = 0.254",
            "position_dia = { zone = 0.254 }",
            "pin_hole.position_dia",
        ),
        # Every feature names its frame and kind.
        (
            'kind = "boss"\nframe = "model"\n',
            'kind = "boss"\n',
            "model-frame feature with a kind",
        ),
    ],
)
def test_bad_manifests_are_refused(tmp_path, old, new, message):
    with pytest.raises(CadError, match=re.escape(message)):
        load_joined_hub(_manifest(tmp_path, old, new), SUPPLY, "joined-lever")


@pytest.mark.parametrize(
    ("key", "value", "message"),
    [
        # The land is the finished outside: inside the hub's band.
        ("hub_land_max_in", 0.5105, "outside the hub's band"),
        # The shortest hub, offset by the joint, must still clean up.
        ("hub_supply_length_min_in", 0.31, "does not clean up"),
        ("bond_offset_max_in", -0.001, "offset ≥ 0"),
    ],
)
def test_bad_supply_is_refused(key, value, message):
    with pytest.raises(CadError, match=re.escape(message)):
        load_joined_hub(SOURCE, {**SUPPLY, key: value}, "joined-lever")


def test_the_supply_must_be_stated():
    supply = dict(SUPPLY)
    del supply["bond_offset_max_in"]
    with pytest.raises(CadError, match="bond_offset_max_in"):
        load_joined_hub(SOURCE, supply, "joined-lever")


def test_the_other_nominal_spelling_and_a_listed_statement_bind(tmp_path):
    text = SOURCE.read_text(encoding="utf-8")
    text = text.replace("thickness_nominal = 3.175", "nominal_thickness = 3.175", 1)
    text = text.replace(
        'requirements = ["radius", "surface_profile"]\nradius = 6.35',
        'requirements = ["radius", "surface_profile", "mirror_symmetric"]\n'
        "radius = 6.35\nmirror_symmetric = true",
        1,
    )
    path = tmp_path / "joined.toml"
    path.write_text(text, encoding="utf-8")
    values = load_joined_hub(path, SUPPLY, "joined-lever").values
    assert values["strap_thickness_mm"] == pytest.approx(3.175)
    assert values["outline_mirror_symmetric"] is True


def test_a_land_at_the_band_edge_is_not_refused_by_conversion_noise():
    # .5100 in is the hub's 12.954 mm high limit, read through inches.
    values = load_joined_hub(
        SOURCE, {**SUPPLY, "hub_land_max_in": 0.51}, "joined-lever"
    ).values
    assert values["hub_land_max_in"] == pytest.approx(0.51)


def test_a_unilateral_member_diameter_and_a_one_number_strap_hole_bind(tmp_path):
    text = SOURCE.read_text(encoding="utf-8")
    # A .257 +.001/+.003 bore: its nominal size lies under its band.
    text = text.replace("dia = [6.5278, 6.6294]", "dia = [6.5532, 6.6040]", 1)
    text = text.replace("dia = [3.2639, 3.3655]", "dia = 3.2639", 1)
    path = tmp_path / "joined.toml"
    path.write_text(text, encoding="utf-8")
    values = load_joined_hub(path, SUPPLY, "joined-lever").values
    assert values["bore_dia_band_mm"] == [6.5532, 6.6040]
    assert values["bore_dia_mm"] == pytest.approx(6.5278)
    assert values["pin_hole_from_bore_mm"] == pytest.approx(51.1953, abs=1e-4)


def test_the_printed_height_may_lie_below_the_exact_half(tmp_path):
    # Length .290–.300 (nominal .300), strap .125–.127 (nominal .126): the
    # half is .087, but .087 makes .301 on the thickest strap; .086 fits.
    text = SOURCE.read_text(encoding="utf-8")
    text = text.replace("length = [7.5184, 7.7216]", "length = [7.366, 7.62]", 1)
    text = text.replace(
        "thickness = [3.1496, 3.2004]\nthickness_nominal = 3.175",
        "thickness = [3.175, 3.2258]\nthickness_nominal = 3.2004",
        1,
    )
    path = tmp_path / "joined.toml"
    path.write_text(text, encoding="utf-8")
    supply = {**SUPPLY, "hub_supply_length_min_in": 0.36}
    values = load_joined_hub(path, supply, "joined-lever").values
    assert values["hub_end_height_in"] == pytest.approx(0.086)
