"""Traveler HOLD and SHOP-MADE FIXTURE sheet facts from a synthetic bundle."""

import re
from html import unescape
from pathlib import Path

from prechips.inputs import Bundle
from prechips.sheet import _Traveler

# Fixture-local x runs along setup +Y and local z along setup +Z, so local y runs along
# setup -X: local (x, y, z) sits at setup (100 - y, 50 + x, -20 + z).
TURNED = {"origin_mm": [100, 50, -20], "x": [0, 1, 0], "z": [0, 0, 1]}
IDENTITY = {"origin_mm": [0, 0, 0], "x": [1, 0, 0], "z": [0, 0, 1]}


def bundle(holds):
    return Bundle(
        plan={
            "setups": [
                {"id": f"S{n}", "machine": "mill", "frame": "TC", "hold": hold, "ops": []}
                for n, hold in enumerate(holds, 1)
            ]
        },
        inventory={
            "machines": {"mill": {"kind": "mill"}},
            "fixtures": {
                "plate": {
                    "kind": "custom",
                    "solids": [
                        {"name": "pad", "shape": "box", "at_mm": [0, 0, 0], "size_mm": [10, 20, 5]},
                        {
                            "name": "pin",
                            "shape": "cylinder",
                            "at_mm": [5, 5, 5],
                            "axis": [0, 0, 1],
                            "dia_mm": 6,
                            "length_mm": 8,
                            "locates": "datum bore",
                        },
                        {
                            "name": "stud-hole",
                            "shape": "cylinder",
                            "at_mm": [5, 15, 0],
                            "axis": [0, 0, 1],
                            "dia_mm": 5,
                            "length_mm": 5,
                            "void": True,
                            "fastener": "M6 stud",
                        },
                        {
                            "name": "shim-r",
                            "shape": "box",
                            "at_mm": [0, 0, 5],
                            "size_mm": [10, 4, 0.47175],
                            "shim": True,
                            "locates": "rail",
                        },
                        {
                            "name": "shim-l",
                            "shape": "box",
                            "at_mm": [0, 16, 5],
                            "size_mm": [10, 4, 0.47175],
                            "shim": True,
                            "locates": "rail",
                        },
                    ],
                },
                # Upright working face is local y = 0, facing local -y; the base is lowest.
                "angle": {
                    "kind": "angle_plate",
                    "solids": [
                        {
                            "name": "base",
                            "shape": "box",
                            "at_mm": [-50, 0, -90],
                            "size_mm": [100, 80, 10],
                            "fastener": "two 1/2-13 T-bolts",
                        },
                        {
                            "name": "upright",
                            "shape": "box",
                            "at_mm": [-50, 0, -80],
                            "size_mm": [100, 10, 80],
                        },
                    ],
                },
                "strap": {"kind": "strap_clamp"},
                "stop": {"kind": "custom", "shop_made": True},
            },
        },
        features={"features": {}},
        policy={},
        cutting_data={},
        paths={},
        hashes={},
        root=Path("."),
        kernel={"status": "ok", "ops": {}},
    )


def text(html):
    return unescape(re.sub(r"<[^>]+>", "|", html))


def sheets(data):
    traveler = _Traveler(data, [], {}, None)
    return [text("".join(sum(traveler.setup_section(s), []))) for s in data.plan["setups"]]


def test_custom_fixture_solids_print_at_their_setup_frame_positions():
    page = sheets(bundle([{"fixture": "plate", "pose": TURNED}]))[0]
    assert "SHOP-MADE FIXTURE" in page
    # The 10 x 20 x 5 pad: local x 0..10 -> Y 50..60, local y 0..20 -> X 80..100.
    assert "X 80…100, Y 50…60, Z -20…-15" in page
    # The locating pin stands at local (5, 5) on the pad top: X 95, Y 55, Z -15 up 8.
    assert "axis at X 95, Y 55; Z -15…-7" in page
    assert "datum bore" in page and "M6 stud" in page


def test_shim_stacks_print_their_drawn_nominal_once():
    page = sheets(bundle([{"fixture": "plate", "pose": TURNED}]))[0]
    assert "2 shim stacks under the rail (shim R, shim L): 0.472 mm nominal" in page


def test_angle_plate_base_and_working_face_print_in_the_setup_frame():
    # Plate turned a quarter about Z and lowered: local -y (the working face normal)
    # lies along setup +X, and the face itself at setup X 10.
    pose = {"origin_mm": [10, 0, -5], "x": [0, 1, 0], "z": [0, 0, 1]}
    page = sheets(bundle([{"fixture": "angle", "pose": pose}]))[0]
    assert (
        "Angle plate: base flat on the table, underside at Z -95; upright working face "
        "at X 10, facing +X; hold the base down with two 1/2-13 T-bolts."
    ) in page


def test_later_setup_points_back_to_the_first_table_at_the_same_pose():
    first, later = sheets(bundle([{"fixture": "plate", "pose": TURNED}] * 2))
    assert "SHOP-MADE FIXTURE" in first
    assert "SHOP-MADE FIXTURE —" not in later
    assert "Setup S1 sheet 2" in later


def test_moved_fixture_gets_its_own_table_in_the_new_frame():
    first, moved = sheets(
        bundle([{"fixture": "plate", "pose": TURNED}, {"fixture": "plate", "pose": IDENTITY}])
    )
    assert "SHOP-MADE FIXTURE —" in moved
    assert "X 0…10, Y 0…20, Z 0…5" in moved


def test_hold_labels_locators_apart_from_clamps_and_tightens_in_declared_order():
    hold = {
        "fixture": "plate",
        "pose": IDENTITY,
        "clamps": [
            {"ref": "strap", "restraint": "press", "torque_nm": 12},
            {"ref": "stop", "restraint": "locate"},
            {"ref": "strap", "restraint": "press", "torque_nm": 12},
        ],
        "clamp_order": [3, 1],
        "preload_direction": "clockwise",
    }
    page = sheets(bundle([hold]))[0]
    assert "C1 clamp:" in page and "LOC2 locator:" in page and "C3 clamp:" in page
    assert "Clamp 2" not in page
    assert (
        "Seat the part against LOC2, turning it clockwise (viewed from above) to take up "
        "the clearance; then tighten in order C3, C1: snug each in turn, then tighten each "
        "fully in the same order to 12 N·m."
    ) in page
