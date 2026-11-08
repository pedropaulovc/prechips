"""Authored raster inputs preserve explicit moves; schema never supplies a path."""

import pytest
from pydantic import ValidationError

from prechips.model import Contour, InventoryItem


def raster():
    return {
        "method": "manual_raster",
        "raster": {
            "start_mm": [-4.0, 2.0, 12.0],
            "safe_z_mm": 12.0,
            "moves": [
                {"to_mm": [-4.0, 2.0, 1.0], "mode": "clear"},
                {"to_mm": [8.0, 2.0, 1.0], "mode": "cut"},
                {"to_mm": [8.0, 2.0, 12.0], "mode": "clear"},
            ],
        },
    }


def test_authored_trajectory_round_trips_without_generated_moves():
    authored = raster()
    parsed = Contour.model_validate(authored)
    assert parsed.model_dump(exclude_unset=True) == authored


@pytest.mark.parametrize("field", ["start_mm", "safe_z_mm", "moves"])
def test_raster_requires_each_authored_trajectory_field(field):
    authored = raster()
    del authored["raster"][field]
    with pytest.raises(ValidationError):
        Contour.model_validate(authored)


@pytest.mark.parametrize("point", [[1.0, 2.0], [1.0, 2.0, 3.0, 4.0], [0.0, 0.0, float("nan")]])
def test_raster_rejects_malformed_or_nonfinite_tool_tip(point):
    authored = raster()
    authored["raster"]["moves"][0]["to_mm"] = point
    with pytest.raises(ValidationError):
        Contour.model_validate(authored)


def test_unknown_measurement_remains_unknown_for_proof_consumer():
    authored = raster()
    authored["raster"]["moves"][0]["to_mm"][2] = "unknown"
    parsed = Contour.model_validate(authored)
    assert parsed.raster.moves[0].to_mm[2] == "unknown"


def test_empty_trajectory_and_implicit_motion_modes_are_not_paths():
    authored = raster()
    authored["raster"]["moves"] = []
    with pytest.raises(ValidationError):
        Contour.model_validate(authored)
    authored = raster()
    del authored["raster"]["moves"][0]["mode"]
    with pytest.raises(ValidationError):
        Contour.model_validate(authored)


def test_whole_body_bound_is_distinct_from_local_shank_measurement():
    item = InventoryItem.model_validate({"shank_mm": 6.0, "body_envelope_dia_mm": "unknown"})
    assert item.model_dump(exclude_unset=True) == {
        "shank_mm": 6.0,
        "body_envelope_dia_mm": "unknown",
    }
    assert "body_envelope_dia_mm" not in InventoryItem.model_validate({"shank_mm": 6.0}).model_dump(
        exclude_unset=True
    )
