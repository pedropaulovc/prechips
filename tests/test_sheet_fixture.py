"""Traveler HOLD and SHOP-MADE FIXTURE sheet facts from a synthetic bundle."""

import re
from html import unescape
from pathlib import Path

import pytest

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


def bridge_page(*extra, precision=3, mill=None, tolerances=None, **policy_numbers):
    """A shop-made two-stud bridge: a made beam and locating pad, bought studs, washers
    and nuts, clearance holes through beam and washers, nut threads, and the machine's
    vise jaw drawn for clearance."""
    data = bundle([{"fixture": "bridge", "pose": IDENTITY}])
    data.features.update(precision=precision, units="mm")
    if tolerances is not None:
        data.features["general_tolerances"] = tolerances
    data.inventory["machines"]["mill"].update(mill or {})
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


def test_made_parts_print_their_make_notes_and_differing_notes_stay_apart():
    hard = "O1 drill rod, hardened 58-60 HRC, OD ground"
    buttons = [
        cylinder(f"button-{s}", x, 8.26, 14, 4, note=note)
        for s, x, note in (("l", -20, hard), ("r", 20, hard), ("c", 0, "mild steel"))
    ]
    collar = cylinder("collar", 40, 8.26, 10, 3, note=hard)
    table = bridge_page(*buttons, collar)
    made = table[table.index("Component") : table.index("Bought hardware")]
    assert "button ×2" in made, "identical parts with one note share a row"
    # Rows sharing a make note are named together before it.
    assert f"Make: button ×2, collar: {hard}; button C: mild steel." in table
    # Bought hardware is not made, so its note is no make instruction.
    assert "zinc" not in bridge_page(cylinder("bolt", 0, 0, 6, 20, supply="bought", note="zinc"))


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


def test_a_locating_solid_with_a_bore_in_it_is_a_fit_as_well_as_its_bore():
    # A stand locates the part on its own top face; the bore through it does not make that
    # face a make-precision number.
    stand = cylinder("stand", 0, -17, 9.94, 9.94, locates="hub face")
    bore = cylinder("stand-bore", 0, -18, 4.5, 12, void=True, cuts=["stand"])
    table = bridge_page(stand, bore, fixture_make_decimals=1)
    assert "Ø9.94 × 9.94" in table and "Z -17…-7.06" in table
    assert "Ø9.9 × 9.9" not in table and "-7.1" not in table


# The shop's mill reads 0.005 mm; a pin locating the part stands in a hole in the beam.
FIVE_MICRON = {"resolution_mm": 0.005}
DIAL = (
    cylinder("pin", -0.368, 8.26, 4, 6, locates="cap bore"),
    cylinder("pin-hole", -0.368, -1, 4, 12, void=True, cuts=["beam"]),
    # A 3/4 in rail: half a 0.1 make step rounds up, whatever the float noise.
    {"name": "rail", "shape": "box", "at_mm": [60, -5, 0], "size_mm": [19.05, 5, 5]},
)


def test_fixture_positions_print_on_the_mill_grid_one_value_per_place():
    table = bridge_page(*DIAL, precision="unknown", mill=FIVE_MICRON, fixture_make_decimals=1)
    # The pin is a fit: on the mill's 0.005 grid, not 3 places off it.
    assert "axis at X -0.37, Y 0; Z 8.26…14.26" in table
    # The hole the pin stands in prints the same X, not the 0.1 make precision.
    assert "with 1 × Ø4 hole: axis at X -0.37, Y 0; Z -1…11" in table
    assert "-0.368" not in table and "X -0.4," not in table
    # The locating pad's 2.3456 thickness and underside are on the grid too.
    assert "10 × 10 × 2.345" in table and "Z -2.345…0" in table
    assert "19.1 × 5 × 5" in table


@pytest.mark.parametrize(
    ("tolerances", "printed"),
    [({"linear_3pl": 0.13}, "X -0.37,"), ({"linear_3pl": 0.001}, "X ?,"), ({}, "X ?,")],
)
def test_a_fit_the_mill_grid_moves_beyond_the_drawing_tolerance_is_unknown(tolerances, printed):
    table = bridge_page(*DIAL, precision=3, mill=FIVE_MICRON, tolerances=tolerances)
    pin = table[table.index("|pin|") :]
    assert f"axis at {printed} Y 0; Z 8.26…14.26" in pin
    # The hole it stands in is the same place: never a different, silently moved value.
    assert f"with 1 × Ø4 hole: axis at {printed} Y 0" in table
    if "?" in printed:
        assert "cannot hold" in table and "linear_3pl" in table


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


def test_hole_without_cuts_prints_in_every_part_it_passes_through():
    lower = {"name": "lower", "shape": "box", "at_mm": [60, -5, 0], "size_mm": [10, 10, 5]}
    upper = {"name": "upper", "shape": "box", "at_mm": [60, -5, 5], "size_mm": [10, 10, 4]}
    hole = cylinder("pin-hole", 65, 0, 3, 9, void=True)
    table = bridge_page(lower, upper, hole)
    assert table.count("with 1 × Ø3 hole: axis at X 65, Y 0; Z 0…9") == 2
    # Unverified, the same hole withholds both parts it would cut.
    table = bridge_page(lower, upper, {**hole, "verify": True})
    assert table.count("? not set: its hole pin-hole is unverified") == 2
    assert "X 60…70" not in table


def test_bought_primitives_count_together_only_when_they_touch():
    screw = {"supply": "bought", "fastener": "M8 SHCS"}
    # Parallel Ø8 shanks 9.9 apart: their bounding boxes overlap, the screws do not.
    near = cylinder("screw-a", 0, 20, 8, 20, **screw)
    apart = {**cylinder("screw-b", 7, 20, 8, 20, **screw), "at_mm": [7, 7, 20]}
    assert "; 2 × M8 SHCS." in bridge_page(near, apart)
    # A Ø13 head resting on the end of its shank is one screw.
    head = cylinder("screw-head", 0, 40, 13, 8, **screw)
    assert "; 1 × M8 SHCS." in bridge_page(near, head)


def test_oblique_hole_without_cuts_withholds_the_part_it_may_cross():
    plate = {"name": "plate", "shape": "box", "at_mm": [60, -5, 0], "size_mm": [10, 10, 0.1]}
    hole = {
        "name": "slant",
        "shape": "cylinder",
        "at_mm": [35, 0, -40],
        "axis": [0.6, 0, 0.8],
        "dia_mm": 1,
        "length_mm": 100,
        "void": True,
    }
    table = bridge_page(plate, hole)
    assert "? not set: oblique hole slant may cross it; name it in cuts" in table
    assert "X 60…70" not in table
    # Named in cuts, the hole prints in the plate's row.
    table = bridge_page(plate, {**hole, "cuts": ["plate"]})
    assert "X 60…70, Y -5…5, Z 0…0.1|with 1 × Ø1 hole" in table


# A soft-jaw plate bolted to a vise jaw, drawn in its own frame: the vise places it.
SOFT_JAWS = {
    "kind": "vise",
    "shop_made": True,
    "solids": [
        {"name": "jaw-plate", "shape": "box", "at_mm": [0, 0, 0], "size_mm": [150, 20, 60]},
        {
            "name": "bolt-hole",
            "shape": "cylinder",
            "at_mm": [25, 0, 30],
            "axis": [0, 1, 0],
            "dia_mm": 11,
            "length_mm": 20,
            "void": True,
            "fastener": "M10 jaw bolt",
        },
    ],
}
BUTTONS = {
    "kind": "jaw_buttons",
    "shop_made": True,
    "solids": [
        {
            "name": "button",
            "shape": "cylinder",
            "at_mm": [0, 0, 0],
            "axis": [0, 0, 1],
            "dia_mm": 20,
            "length_mm": 6,
        },
    ],
}


def loose_page(hold, **items):
    data = bundle([hold])
    data.inventory["fixtures"].update(items)
    page = sheets(data)[0]
    return page, page[page.index("SHOP-MADE FIXTURE —") :]


def test_an_item_the_hold_places_prints_its_make_table_in_its_own_frame():
    _, table = loose_page({"fixture": "soft-jaws", "jaws_along": "x"}, **{"soft-jaws": SOFT_JAWS})
    assert "loose: placed as the HOLD says" in table
    assert "? not posed" not in table
    # Sizes and the bolt hole stand where the make table draws them, in the item frame.
    assert "150 × 20 × 60" in table and "X 0…150, Y 0…20, Z 0…60" in table
    assert "M10 jaw bolt" in table and "axis at X 25, Z 30" in table


def test_jaw_buttons_get_a_make_table_and_the_hold_points_to_it():
    page, table = loose_page({"fixture": "angle", "jaw_buttons": "buttons"}, buttons=BUTTONS)
    assert "Jaw buttons: " in page and "(shop-made: SHOP-MADE FIXTURE table, sheet 2)" in page
    assert "Ø20 × 6" in table and "loose: placed as the HOLD says" in table


def test_a_fixture_placed_by_its_pose_still_stops_without_one():
    _, table = loose_page({"fixture": "plate"})
    assert "? not posed" in table and "loose" not in table
