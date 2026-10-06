"""Lathe op starts, relief plunges and dome roughing as the rules derive them."""

from pathlib import Path
from types import SimpleNamespace

import pytest

from prechips.inputs import Bundle
from prechips.rules import coordinates, op_chain


def _setup(ops, setup_id="S3"):
    return {"id": setup_id, "machine": "lathe", "ops": ops}


def _bundle(setups, features):
    data = SimpleNamespace(
        plan={"setups": setups},
        features={"units": "mm", "features": features},
        inventory={"machines": {"lathe": {"kind": "lathe"}}, "tools": {}},
        policy={},
    )
    data.feature_definitions = data.features["features"]
    return data


_DOME = {"kind": "dome", "sphere_radius": 4.11}
_PART = {"op": 10, "do": "cut_to_fit", "feature": "dome", "to_z": 1.75}
_FORM = {
    "op": 20,
    "do": "form_dome",
    "feature": "dome",
    "z_from": 1.75,
    "z_to": 0.25,
    "contour": {"method": "axial_table", "step_mm": 0.1},
}


def _chain(ops):
    rows = op_chain.evaluate(_bundle([_setup(ops)], {"dome": dict(_DOME)}))
    return {row.subject: row for row in rows}["dome"]


def test_a_dome_table_cannot_start_on_a_face_left_only_within_a_band():
    # Parting to Z1.75 accepted anywhere in 1.5..2.0 leaves the apex row in air or the
    # table 0.25 under unfaced stock: the dome's printed start is not a known face.
    row = _chain([{**_PART, "to_z_band": [1.5, 2.0]}, _FORM])
    assert row.status == "error"
    assert row.numbers["banded_starts"] == [
        "S3 op 20 starts at Z 1.75, which op 10 leaves anywhere in 1.5 to 2; "
        "an op must leave that face at a deterministic to_z first"
    ]
    # A band that merely contains the start is the same unknown face.
    shifted = _chain([{**_PART, "to_z": 2.0, "to_z_band": [1.5, 2.0]}, _FORM])
    assert shifted.status == "error"


def test_a_deterministic_facing_after_the_banded_part_off_fixes_the_dome_start():
    banded = {**_PART, "to_z": 2.25, "to_z_band": [2.0, 2.5]}
    face = {"op": 15, "do": "face", "feature": "dome", "to_z": 1.75}
    assert _chain([banded, face, _FORM]).status == "not_applicable"
    # Without the facing op the banded part-off still decides the start.
    assert _chain([banded, {**_FORM, "z_from": 2.25}]).status == "error"
    # An unbanded part-off is itself deterministic.
    assert _chain([_PART, _FORM]).status == "not_applicable"


_IDENTITY = {
    "origin": [0.0, 0.0, 0.0],
    "x": [1.0, 0.0, 0.0],
    "y": [0.0, 1.0, 0.0],
    "z": [0.0, 0.0, 1.0],
    "binding": "nominal",
}


def _lathe(ops, features, tools):
    """A one-setup lathe bundle in an identity frame (setup Z = model Z, +Z free end)."""
    return Bundle(
        plan={
            "part": "lathe-review",
            "features": "features.toml",
            "dro": {"controller": "test DRO", "radius_mode": False},
            "stock": {"form": "round_bar", "dia_mm": 10.0, "cite": "test authored blank"},
            "setups": [
                {
                    "id": "S1",
                    "machine": "lathe",
                    "frame": "T",
                    "stock_state": {"od_mm": 10.0, "north_end_z": 20.0, "south_end_z": -5.0},
                    "hold": {"fixture": "chuck", "support": "none", "stickout_mm": 20.0},
                    "ops": ops,
                }
            ],
        },
        features={
            "part": "lathe-review",
            "units": "mm",
            "frames": {"model": dict(_IDENTITY), "T": dict(_IDENTITY)},
            "features": features,
        },
        inventory={"machines": {"lathe": {"kind": "lathe"}}, "tools": tools},
        policy={},
        cutting_data={},
        paths={},
        hashes={},
        root=Path("."),
    )


_RELIEF = {
    "kind": "groove",
    "frame": "model",
    "dia": [5.57, 5.83],
    "dia_nominal": 5.7,
    "width": [1.2, 2.8],
}


def _blade(hand="right"):
    return {"kind": "parting_blade", "hand": hand, "nose_radius_mm": 0.1, "blade_width_mm": 1.6}


def _relief(z_from, z_to, hand="right"):
    op = {
        "op": 50,
        "do": "form_relief",
        "feature": "relief",
        "tool": "blade",
        "z_from": z_from,
        "z_to": z_to,
        "direction": "plunge_radial",
    }
    return coordinates.evaluate(_lathe([op], {"relief": dict(_RELIEF)}, {"blade": _blade(hand)}))[0]


def test_a_blade_narrower_than_its_relief_plunges_flush_with_each_wall():
    # The 1.6 blade cuts the 2.0 relief in two plunges whose chuck-side corners (the DRO
    # reading after a +Z end-face touch) sit at Z0 and Z0.4, each to the drawing diameter.
    finding = _relief(0.0, 2.0)
    (plunges,) = finding.numbers["plunges"]
    assert plunges["corner_z_mm"] == pytest.approx([0.0, 0.4])
    assert plunges["groove_z_mm"] == pytest.approx([0.0, 2.0])
    assert plunges["width_mm"] == pytest.approx(2.0)
    assert plunges["diameter_mm"] == 5.7 and plunges["dia_band_mm"] == [5.57, 5.83]
    assert finding.status != "error"
    # Authored from the far wall, the plunges are the same; a left-hand blade reads its
    # +Z corner instead.
    assert _relief(2.0, 0.0).numbers["plunges"][0]["corner_z_mm"] == pytest.approx([0.0, 0.4])
    left = _relief(0.0, 2.0, hand="left").numbers["plunges"][0]
    assert left["corner_z_mm"] == pytest.approx([1.6, 2.0])


def test_relief_plunges_wider_than_the_drawing_width_band_are_refused():
    # Plunging at both printed ends of a 0..2 row with the 1.6 blade cuts 0..3.6; a span
    # authored that wide is refused against the 2.8 maximum, and 2.8 itself is accepted.
    wide = _relief(0.0, 3.6)
    assert wide.status == "error"
    assert wide.numbers["plunges"][0]["corner_z_mm"] == pytest.approx([0.0, 1.0, 2.0])
    assert "op 50 plunges leave a groove 3.6 wide, outside the drawing width 1.2 to 2.8" in (
        wide.sentence
    )
    assert _relief(0.0, 2.8).status != "error"
    # A blade wider than the authored span still cuts its own width.
    narrow = _relief(0.0, 1.0).numbers["plunges"][0]
    assert narrow["corner_z_mm"] == [0.0] and narrow["width_mm"] == pytest.approx(1.6)


_DOME = {"kind": "dome", "frame": "model", "height": [0.7, 2.3], "sphere_radius": 4.1102}
_AR = {
    "kind": "turning_tool",
    "hand": "right",
    "nose_radius_mm": 0.4,
    "entering_angle_deg": 93.0,
    "insert_angle_deg": 60.0,
}


def _dome(**extra):
    op = {
        "op": 20,
        "do": "form_dome",
        "feature": "dome",
        "tool": "ar",
        "z_from": 1.75,
        "z_to": 0.25,
        "direction": "apex_to_base",
        "contour": {"method": "axial_table", "step_mm": 0.1},
        **extra,
    }
    bundle = _lathe([op], {"dome": dict(_DOME)}, {"ar": dict(_AR)})
    return coordinates.evaluate(bundle)[0]


def test_a_dome_with_a_rough_allowance_gets_a_stair_that_never_comes_inside_it():
    finding = _dome(rough_allowance_mm=0.2)
    assert finding.status == "pass"
    (stair,) = finding.numbers["stair_tables"]
    (finish,) = finding.numbers["contours"]
    assert (stair["stage"], finish["method"]) == ("rough", "axial_table")
    rows = stair["rows"]
    # One facing row per finish Z below the apex, until the grown sphere passes the Ø6.35
    # base the dome caps.
    assert [round(r["z_mm"], 6) for r in rows] == [
        round(1.75 - 0.1 * i, 6) for i in range(1, len(rows) + 1)
    ]
    assert all(r["x_target_mm"] < 2 * stair["work_radius_mm"] for r in rows)
    assert stair["work_radius_mm"] == pytest.approx(3.1749, abs=1e-3)
    # Every corner (the imaginary-tip reading) is 0.1 (half the diametral allowance) off
    # the sphere, and the stair rises outward from each finish row.
    centre = 1.75 - 4.1102
    by_z = {round(r["z_mm"], 6): r for r in finish["rows"]}
    for row in rows:
        r, z = row["x_target_mm"] / 2, row["z_mm"]
        assert ((r * r + (z - centre) ** 2) ** 0.5) - 4.1102 == pytest.approx(0.1)
        assert row["x_target_mm"] > by_z[round(z, 6)]["x_target_mm"]
    # A rough_* op with the table carries the stair only, never the finished surface.
    rough = _dome(do="rough_dome", rough_allowance_mm=0.2)
    assert rough.numbers["stair_tables"][0]["rows"] == rows
    assert rough.numbers["contours"] == []


def test_a_dome_stair_is_not_assumed_for_an_apex_toward_the_chuck():
    finding = _dome(z_from=0.25, z_to=1.75, rough_allowance_mm=0.2)
    assert "stair_tables" not in finding.numbers
    assert finding.status == "unknown"
