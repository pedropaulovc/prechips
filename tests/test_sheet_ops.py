"""Operation-sheet wording a machinist acts on: printed bands and index directions."""

import pytest

from prechips.sheet import _Traveler


def bare(precision):
    sheet = _Traveler.__new__(_Traveler)
    sheet.precision = lambda feature, dimension: precision
    return sheet


@pytest.mark.parametrize(
    ("band", "precision", "printed"),
    [
        ([1.994, 2.094], 2, "2.00–2.09"),
        ([12.2555, 12.2855], 3, "12.256–12.285"),
        ([7.0565, 7.1065], 3, "7.057–7.106"),
        ([6.33, 6.35], 3, "6.330–6.350"),
    ],
)
def test_printed_band_never_wider_than_the_drawing(band, precision, printed):
    assert bare(precision).band(band, None, None) == printed


def test_band_narrower_than_its_precision_prints_declared_limits():
    assert bare(2).band([3.001, 3.004], None, None) == "3.001–3.004"


@pytest.mark.parametrize(
    ("clock", "z", "words"),
    [
        (12.5, [1.0, 0.0, 0.0], "counterclockwise viewed from the free end of the work"),
        (-12.5, [1.0, 0.0, 0.0], "clockwise viewed from the free end of the work"),
    ],
)
def test_index_direction_follows_jaw_clock_sign(clock, z, words):
    sense = _Traveler.index_sense({"jaw_clock_deg": clock, "pose": {"z": z}})
    assert sense.startswith(words)
    assert "from setup +X" in sense


def test_index_direction_names_the_viewing_end_from_the_chuck_axis():
    sense = _Traveler.index_sense({"jaw_clock_deg": 5.0, "pose": {"z": [0.0, 0.0, -1.0]}})
    assert "from setup −Z" in sense


def test_index_direction_unknown_without_a_clock_angle():
    assert _Traveler.index_sense({"pose": {"z": [1.0, 0.0, 0.0]}}).startswith("?")
