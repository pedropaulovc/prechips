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
    "bond_offset_max_in": 0.008,
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
    assert values["hub_length_band_mm"] == [7.5692, 7.6708]
    assert values["strap_thickness_band_mm"] == [3.1496, 3.2004]
    # (.300 − .125)/2: each end .0875 over its own strap face.
    assert values["hub_end_height_in"] == pytest.approx(0.0875)
    assert values["bore_depth_mm"] == pytest.approx(7.62)
    assert values["pin_hole_from_bore_x_mm"] == pytest.approx(50.8)
    assert values["pin_hole_from_bore_y_mm"] == pytest.approx(6.35)
    assert values["pin_hole_from_bore_mm"] == pytest.approx(51.1953, abs=1e-4)
    assert "pin_hole_from_bore_z_mm" not in values
    # Shortest hub (.37), thickest strap, offset toward the end: .0265 off;
    # longest (.40), thinnest, offset away: .0585.
    assert values["face_depth_min_in"] == pytest.approx(0.0265)
    assert values["face_depth_max_in"] == pytest.approx(0.0585)
    assert values["hub_end_supply_max_in"] == pytest.approx(0.146)
    assert values["hub_land_band_mm"] == pytest.approx([12.6365, 12.6746])
    # Every feature also binds by name; a table field binds nothing.
    assert values["outline_surface_profile_in"] == pytest.approx(0.02)
    assert not any(key.startswith("outline_surface_profile_governs") for key in values)
    assert values["hub_root_radius_max_in"] == pytest.approx(0.01)
    required = {axis.name: axis.required_mm for axis in cad.stock_requirement.axes}
    assert required == {"hub length": 7.6708}


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
        # The bore lies on the hub's axis.
        (
            "at = [0.0, 0.0, 0.0]\naxis = [0.0, 0.0, 1.0]\ndia = [6.5278",
            "at = [0.5, 0.0, 0.0]\naxis = [0.0, 0.0, 1.0]\ndia = [6.5278",
            "on the hub's axis",
        ),
        # Every hole runs along the hub's axis.
        (
            "at = [50.8, 6.35, 0.0]\naxis = [0.0, 0.0, 1.0]",
            "at = [50.8, 6.35, 0.0]\naxis = [1.0, 0.0, 0.0]",
            "parallel to the hub's axis",
        ),
        # Facing each end from its own face cannot hold this tight a length.
        ("length = [7.5692, 7.6708]", "length = [7.6073, 7.6327]", "length band"),
        # The strap's thickness is one band.
        (
            "thickness = [3.1496, 3.2004]\nthickness_nominal = 3.175",
            "thickness = [3.1496, 3.2004]\nthickness_nominal = 3.2512",
            "outside its band",
        ),
        # Names collide with the members' own keys.
        ("[features.pivot_bore]", "[features.bore]", "bound twice"),
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
