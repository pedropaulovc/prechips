"""CAD-sharp concave corners admit a nose up to the feature's corner_radius_max_design."""

from pathlib import Path

import pytest
from test_geometry_rules import bundle, finding  # noqa: F401  (pytest fixture)

from prechips.inputs import Bundle
from prechips.rules import internal_corner_radius, sizing


def sharp(bundle, tool_radius, corners=(0.0,), allowance=0.25):  # noqa: F811
    bundle.inventory["tools"]["em"]["dia_mm"] = 2 * tool_radius
    bundle.kernel["ops"]["S1:10"]["corner_radii_mm"] = list(corners)
    if allowance is not None:
        bundle.features["features"]["pocket"]["corner_radius_max_design"] = allowance
    return finding(internal_corner_radius, bundle)


@pytest.mark.parametrize("tool_radius,status", [(0.25, "pass"), (0.26, "error")])
def test_cad_sharp_corner_admits_nose_up_to_declared_allowance(bundle, tool_radius, status):  # noqa: F811
    row = sharp(bundle, tool_radius)
    assert row.status == status
    assert row.numbers["corner_radius_max_design_mm"] == 0.25
    assert row.numbers["cad_sharp_corners"] == 1


def test_cad_sharp_corner_without_allowance_keeps_the_error(bundle):  # noqa: F811
    bundle.features["general_tolerances"] = {"edge_break_r": 0.25}
    row = sharp(bundle, 0.25, allowance=None)
    assert row.status == "error"
    assert "corner_radius_max_design" in row.sentence


def test_allowance_does_not_admit_a_modelled_corner_smaller_than_the_nose(bundle):  # noqa: F811
    assert sharp(bundle, 0.25, corners=(0.1,)).status == "error"
    assert sharp(bundle, 0.25, corners=(0.0, 0.1)).status == "error"
    assert sharp(bundle, 0.25, corners=(0.0, 0.25)).status == "pass"


def groove_bundle(nose, allowance=0.25):
    feature = {
        "kind": "groove",
        "dia": [5.57, 5.83],
        "width": [1.2, 2.8],
        "cite": ["scratch drawing fixture: relief"],
    }
    if allowance is not None:
        feature["corner_radius_max_design"] = allowance
    return Bundle(
        plan={
            "stock": {"dia_mm": 10.0},
            "setups": [
                {
                    "id": "S1",
                    "ops": [{"op": 10, "do": "form_relief", "feature": "relief", "tool": "b"}],
                }
            ],
        },
        features={"units": "mm", "features": {"relief": feature}},
        inventory={
            "tools": {"b": {"kind": "parting_blade", "nose_radius_mm": nose, "reach_mm": 18.0}}
        },
        policy={},
        cutting_data={},
        paths={},
        hashes={},
        root=Path("."),
    )


@pytest.mark.parametrize(
    "nose,allowance,status",
    [(0.25, 0.25, "pass"), (0.26, 0.25, "error"), (0.25, None, "unknown")],
)
def test_groove_sizing_nose_boundary_at_corner_allowance(nose, allowance, status):
    [row] = sizing.evaluate(groove_bundle(nose, allowance))
    assert row.status == status
