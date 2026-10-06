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


def cylinder(name, x, z, dia, length, **extra):
    return {
        "name": name,
        "shape": "cylinder",
        "at_mm": [x, 0, z],
        "axis": [0, 0, 1],
        "dia_mm": dia,
        "length_mm": length,
        **extra,
    }


def bridge_page(*extra, **policy_numbers):
    """A shop-made two-stud bridge: a made beam and locating pad, bought studs, washers
    and nuts, clearance holes through beam and washers, nut threads, and the machine's
    vise jaw drawn for clearance."""
    data = bundle([{"fixture": "bridge", "pose": IDENTITY}])
    data.features["precision"] = 3
    data.policy["numbers"] = policy_numbers
    bought = {"supply": "bought"}
    data.inventory["fixtures"]["bridge"] = {
        "kind": "custom",
        "solids": [
            {"name": "beam", "shape": "box", "at_mm": [-30, -5, 0], "size_mm": [60, 10, 8.26]},
            {
                "name": "pad",
                "shape": "box",
                "at_mm": [-5, -5, -2.3456],
                "size_mm": [10, 10, 2.3456],
                "locates": "cap face",
            },
            *(
                cylinder(f"stud-{s}", x, -30, 9.525, 50, fastener="3/8-16 x 2 in stud", **bought)
                for s, x in (("l", -20), ("r", 20))
            ),
            *(
                cylinder(f"washer-{s}", x, 8.26, 20.64, 1.6, **bought)
                for s, x in (("l", -20), ("r", 20))
            ),
            *(
                cylinder(f"nut-{s}", x, 9.86, 16.5, 8.33, fastener="3/8-16 hex nut", **bought)
                for s, x in (("l", -20), ("r", 20))
            ),
            *(
                cylinder(f"clearance-{s}", x, -1, 10.5, 12, void=True, cuts=["beam", f"washer-{s}"])
                for s, x in (("l", -20), ("r", 20))
            ),
            *(
                cylinder(f"nut-bore-{s}", x, 9.86, 9.525, 8.33, void=True, cuts=[f"nut-{s}"])
                for s, x in (("l", -20), ("r", 20))
            ),
            {
                "name": "vise-jaw",
                "shape": "box",
                "at_mm": [-40, 20, 0],
                "size_mm": [80, 10, 30],
                "supply": "existing",
            },
            *extra,
        ],
    }
    page = sheets(data)[0]
    return page[page.index("SHOP-MADE FIXTURE —") : page.index("CLEARANCE")]


def test_bought_hardware_is_one_line_not_made_rows():
    table = bridge_page()
    assert (
        "Bought hardware (not made): 2 × 3/8-16 x 2 in stud; 2 × washer Ø20.64 × 1.6; "
        "2 × 3/8-16 hex nut."
    ) in table
    made = table[table.index("Component") : table.index("Bought hardware")]
    for word in ("stud", "washer", "nut"):
        assert word not in made, word


def test_holes_print_in_the_row_of_the_part_they_are_cut_in():
    table = bridge_page()
    made = table[table.index("Component") : table.index("Bought hardware")]
    beam = re.split(r"\|{4,}", made[made.index("beam") :])[0]
    assert ("with 2 × Ø10.5 hole: axis at X -20, Y 0; Z -1…11; axis at X 20, Y 0; Z -1…11") in beam
    # The nut threads are part of the bought nuts; no hole gets a row of its own.
    assert "clearance" not in made and "bore" not in made and "Ø9.525" not in made


def test_existing_shop_parts_drawn_for_clearance_are_not_made():
    assert "vise" not in bridge_page()


def test_bought_part_drawn_as_head_and_shank_counts_once():
    screw = {"supply": "bought", "fastener": "M8 SHCS"}
    parts = [
        piece
        for x in (-40, 40)
        for piece in (
            cylinder(f"screw-head-{x}", x, 30, 13, 8, **screw),
            cylinder(f"screw-shank-{x}", x, 0, 8, 30, **screw),
        )
    ]
    table = bridge_page(*parts)
    assert "; 2 × M8 SHCS." in table
    assert table.count("M8 SHCS") == 1


def test_custom_item_with_nothing_to_make_gets_no_table_or_pointer():
    data = bundle([{"fixture": "rest", "pose": IDENTITY}])
    data.inventory["fixtures"]["rest"] = {
        "kind": "custom",
        "solids": [
            {
                "name": "plate",
                "shape": "box",
                "at_mm": [0, 0, -10],
                "size_mm": [50, 50, 10],
                "supply": "existing",
            }
        ],
    }
    page = sheets(data)[0]
    assert "SHOP-MADE" not in page and "shop-made" not in page


def test_existing_part_drilled_here_lists_only_its_holes():
    plate = {
        "name": "plate",
        "shape": "box",
        "at_mm": [-50, -50, -20],
        "size_mm": [100, 100, 10],
        "supply": "existing",
    }
    hole = cylinder("tap", 40, -20, 8.5, 10, void=True, cuts=["plate"], fastener="M10 tapped")
    table = bridge_page(plate, hole)
    assert "plate (existing part: make the holes only)" in table
    assert "with 1 × M10 tapped: axis at X 40, Y 0; Z -20…-10" in table
    assert "100 × 100 × 10" not in table and "vise" not in table


def test_fixture_numbers_print_at_policy_make_precision_and_fits_at_drawing_precision():
    table = bridge_page(fixture_make_decimals=1)
    assert "60 × 10 × 8.3" in table
    assert "Ø20.6 × 1.6" in table
    # The locating pad is a fit: drawing precision (3), not the make precision.
    assert "10 × 10 × 2.346" in table


def test_separate_bought_parts_with_one_fastener_text_count_apart():
    screw = {"supply": "bought", "fastener": "M8 SHCS"}
    table = bridge_page(
        cylinder("screw-a", -40, 20, 8, 20, **screw), cylinder("screw-b", 40, 20, 8, 30, **screw)
    )
    assert "; 2 × M8 SHCS." in table


def test_hole_through_stacked_parts_prints_in_every_part_it_cuts():
    lower = {"name": "lower", "shape": "box", "at_mm": [60, -5, 0], "size_mm": [10, 10, 5]}
    upper = {"name": "upper", "shape": "box", "at_mm": [60, -5, 5], "size_mm": [10, 10, 4]}
    hole = cylinder("pin-hole", 65, 0, 3, 9, void=True, cuts=["lower", "upper"])
    table = bridge_page(lower, upper, hole)
    assert table.count("with 1 × Ø3 hole: axis at X 65, Y 0; Z 0…9") == 2


def test_unverified_primitive_prints_no_make_numbers():
    block = {
        "name": "gauge-block",
        "shape": "box",
        "at_mm": [70, -5, 0],
        "size_mm": [12.5, 7, 3],
        "verify": True,
    }
    table = bridge_page(block)
    assert "gauge block" in table and "? not set: unverified; verify before making" in table
    assert "12.5 × 7 × 3" not in table and "X 70" not in table


def test_existing_and_made_parts_of_one_size_keep_separate_rows():
    old = {
        "name": "old",
        "shape": "box",
        "at_mm": [60, -5, 0],
        "size_mm": [10, 10, 5],
        "supply": "existing",
    }
    new = {"name": "new", "shape": "box", "at_mm": [80, -5, 0], "size_mm": [10, 10, 5]}
    hole = cylinder("tap", 65, 0, 5, 5, void=True, cuts=["old"], fastener="M6 tapped")
    table = bridge_page(old, new, hole)
    assert "old (existing part: make the holes only)" in table
    assert "old / new" not in table and "|new||10 × 10 × 5|" in table


def test_renumbered_clamp_gets_its_own_table_not_a_pointer():
    clamp = {"ref": "plate", "restraint": "press", "pose": IDENTITY}
    first, later = sheets(
        bundle([{"clamps": [clamp]}, {"clamps": [{"ref": "strap", "restraint": "none"}, clamp]}])
    )
    assert "(C1)" in first
    assert "SHOP-MADE FIXTURE —" in later and "Setup S1 sheet 2" not in later


def test_each_placement_of_an_item_builds_its_own_shim_stacks():
    clamps = [
        {"ref": "plate", "restraint": "press", "pose": IDENTITY},
        {"ref": "plate", "restraint": "press", "pose": TURNED},
    ]
    page = sheets(bundle([{"clamps": clamps}]))[0]
    assert "4 shim stacks under the rail (C1 shim R, C2 shim R, C1 shim L, C2 shim L)" in page
