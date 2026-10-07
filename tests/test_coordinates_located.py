"""Located features without their own ``at``: the shared parent locator and the kernel's
faces of revolution about setup Z, in any setup.

A child (``parent``/``hole``) is placed at its parent's ``at`` in the parent's frame by
the one locator ``coordinates`` and ``travel`` share. A located feature with neither
``at`` nor a parent is placed on setup Z through X0 Y0 at both ends of the kernel's
measured axial span, transformed through the setup frame; anything the kernel did not
measure as revolved about that axis stays unknown with its reason. Unit tests inject a
synthetic ``bundle.kernel``.
"""

import pytest
from test_travel_m5 import child_bundle, setup
from test_turned_profile_kernel import _boss_on_a_lathe, _revolved

from prechips.rules import coordinates, travel

UNKNOWN = ["unknown"] * 3
# Model +Y stands along setup +Z (the cone post's S11 pose), shifted off the model origin.
STANDING = {
    "origin": [5.0, 0.0, 3.0],
    "x": [1, 0, 0],
    "y": [0, 0, -1],
    "z": [0, 1, 0],
    "binding": "measured",
}


def _rows(finding, name):
    return [row for row in finding.numbers["rows"] if row["feature"] == name]


def _kernel(data, revolved=None, reasons=None, setup_id="S1"):
    facts = {"revolved": revolved or {}, "revolved_reasons": reasons or {}}
    data.kernel = {"status": "ok", "setups": {setup_id: facts}}
    return data


def _parent_in_a_rotated_frame():
    """The counterbore's parent sits in a rotated drawing frame and the setup frame is
    rotated and shifted too, so a locator reading the child's own frame would differ."""
    data = child_bundle()
    data.features["frames"]["drawing"] = {
        "origin": [100, 50, 0],
        "x": [0, 1, 0],
        "y": [-1, 0, 0],
        "z": [0, 0, 1],
    }
    data.features["frames"]["A"] = dict(STANDING)
    features = data.features["features"]
    features["right"].update(frame="drawing", at=[0, 90, 4])
    features["left"].update(frame="drawing", at=[0, 0, 0])
    return data


def test_parent_located_counterbore_resolves_identically_in_coordinates_and_travel():
    data = _parent_in_a_rotated_frame()
    targets = coordinates.evaluate(data)[0]
    assert targets.status == "pass"
    (cbore,) = _rows(targets, "cbore")
    # drawing (0, 90, 4) -> model (10, 50, 4) -> setup (10 - 5, -(4 - 3), 50 - 0), already
    # on the default 0.001 DRO grid.
    assert cbore == {
        "feature": "cbore",
        "model": [10, 50, 4],
        "setup": [5.0, -1.0, 50.0],
        "dro_xy": [5.0, -1.0],
        "located_by": "right",
        "dro": [5.0, -1.0, 50.0],
    }
    assert "features.features.right.at" in targets.cite
    assert "drawing right hole" in targets.cite
    spans = travel.evaluate(data)[0].numbers["operations"][0]["extent_mm"]
    assert [spans[axis] for axis in ("x", "y")] == [[value, value] for value in cbore["setup"][:2]]
    # A parent-located child never asks the kernel to locate it.
    assert "cbore" not in coordinates.revolved_located(setup(data), data.feature_definitions)


@pytest.mark.parametrize("gap", ["explicit unknown at", "parent not declared", "parent without at"])
def test_unlocated_child_stays_unknown_even_with_a_kernel_axis_fact(gap):
    data = child_bundle()
    cbore = data.features["features"]["cbore"]
    if gap == "explicit unknown at":
        cbore["at"] = "unknown"
    elif gap == "parent not declared":
        cbore["parent"] = "missing"
    else:
        del data.features["features"]["right"]["at"]
    # The kernel measuring it on the setup axis must not substitute for its locator.
    _kernel(data, _revolved(cbore=(0.0, 5.0, 3.0, 3.0, 3.0, 3.0)))
    finding = coordinates.evaluate(data)[0]
    assert finding.status == "unknown"
    (row,) = _rows(finding, "cbore")
    assert row["setup"] == UNKNOWN and "point" not in row
    assert travel.evaluate(data)[0].numbers["operations"][0]["extent_mm"] == "unknown"
    assert "cbore" not in coordinates.revolved_located(setup(data), data.feature_definitions)


def _mill_boss(**kernel):
    """A boss with neither ``at`` nor a parent, faced and inspected in a standing pose."""
    data = child_bundle()
    data.features["frames"]["A"] = dict(STANDING)
    data.features["features"]["head"] = {"kind": "boss", "dia_nominal": 42.0, "cite": "head"}
    setup(data)["ops"] = [
        {"op": 10, "do": "face", "feature": "head", "tool": "cutter", "to_z": 86.0},
        {"op": 20, "do": "inspect", "feature": "head"},
    ]
    return _kernel(data, **kernel) if kernel else data


def test_mill_boss_is_located_at_x0_y0_on_the_kernel_span_through_the_setup_pose():
    data = _mill_boss(revolved=_revolved(head=(59.4, 86.0, 0.0, 21.4, 21.4, 21.4)))
    assert coordinates.revolved_located(setup(data), data.feature_definitions) == ["head"]
    finding = coordinates.evaluate(data)[0]
    assert finding.status == "pass"
    assert _rows(finding, "head") == [
        {
            "feature": "head",
            "point": "setup Z axis, kernel span start",
            "model": [5.0, 59.4, 3.0],
            "setup": [0.0, 0.0, 59.4],
        },
        {
            "feature": "head",
            "point": "setup Z axis, kernel span end",
            "model": [5.0, 86.0, 3.0],
            "setup": [0.0, 0.0, 86.0],
        },
    ]
    assert any(text.startswith("kernel: setups.S1.revolved.head") for text in finding.cite)


@pytest.mark.parametrize(
    ("kernel", "reason"),
    [
        (None, "no kernel geometry is available"),
        (
            {"reasons": {"head": "#4/HEAD is not revolved about setup Z through x = y = 0"}},
            "not revolved about setup Z through x = y = 0",
        ),
        (
            {"revolved": {"head": {"z_mm": [86.0, 59.4], "radii_mm": [21.4, 21.4]}}},
            "its kernel revolved facts are malformed",
        ),
        ({"setup_id": "S9"}, "the kernel measured no faces of revolution for this setup"),
    ],
    ids=["no kernel", "off axis", "malformed", "setup missing"],
)
def test_unmeasured_off_axis_or_malformed_revolved_fact_leaves_the_boss_unknown(kernel, reason):
    data = _mill_boss() if kernel is None else _mill_boss(**kernel)
    finding = coordinates.evaluate(data)[0]
    assert finding.status == "unknown"
    (row,) = _rows(finding, "head")
    assert row["setup"] == UNKNOWN and reason in row["reason"]


def test_unknown_setup_binding_never_locates_by_the_kernel_axis():
    data = _mill_boss(revolved=_revolved(head=(59.4, 86.0, 0.0, 21.4, 21.4, 21.4)))
    data.features["frames"]["A"]["binding"] = "unknown"
    (row,) = _rows(coordinates.evaluate(data)[0], "head")
    assert "point" not in row and "binding is unknown" in row["reason"]


def test_explicit_unknown_at_on_a_mill_boss_wins_over_the_kernel_axis():
    data = _mill_boss(revolved=_revolved(head=(59.4, 86.0, 0.0, 21.4, 21.4, 21.4)))
    data.features["features"]["head"]["at"] = "unknown"
    assert coordinates.revolved_located(setup(data), data.feature_definitions) == []
    finding = coordinates.evaluate(data)[0]
    assert finding.status == "unknown"
    assert _rows(finding, "head") == [
        {"feature": "head", "model": UNKNOWN, "setup": UNKNOWN, "dro_xy": UNKNOWN[:2]}
    ]


def test_lathe_spindle_rows_and_unmeasured_rows_keep_their_shape():
    coaxial = coordinates.evaluate(_boss_on_a_lathe({"boss": (20.0, 25.0, 3, 3, 3, 3)}))[0]
    assert [row for row in coaxial.numbers["rows"] if "point" in row] == [
        {
            "feature": "boss",
            "point": f"spindle axis, kernel span {end}",
            "model": [0.0, 0.0, z],
            "setup": [0.0, 0.0, z],
            "dia_nominal": 6.0,
            "x_target_mm": 6.0,
        }
        for end, z in (("start", 20.0), ("end", 25.0))
    ]
    # An unmeasured lathe feature keeps the established reasonless unknown row.
    why = {"boss": "#4/ADVANCED_FACE[2]/BOSS is not revolved about setup Z through x = y = 0"}
    finding = coordinates.evaluate(_boss_on_a_lathe(reasons=why))[0]
    assert finding.numbers["rows"] == [{"feature": "boss", "model": UNKNOWN, "setup": UNKNOWN}]
