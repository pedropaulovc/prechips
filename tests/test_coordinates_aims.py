"""A located mill target must stand inside the height-like band it holds from its
``height_from`` reference, as the sheet prints that band and as the DRO grid places it.

A plan ``aims`` entry moves only the DRO target (never the feature geometry) so that band
reads a stated value; the cone post's crank bore (separation 39.332 from the journal on a
printed 39.34-39.70) is the case that motivated it.
"""

from copy import deepcopy

from test_travel_m5 import bundle, measured, setup

from prechips.rules import coordinates

PRECISION = {"height": 2, "separation": 2}


def _bores(*, crank_x=72.7, grid=0.005):
    """A foot plane at X 0, a journal 33.368 above it and a crank bore whose separation
    from the journal is ``crank_x`` - 33.368, on a ``grid`` mm DRO."""
    data = bundle()
    data.inventory["machines"]["mill"]["resolution_mm"] = measured(grid)
    features = data.features["features"]
    features["foot"] = {"kind": "face", "plane": {"frame": "model", "axis": "x", "value": 0.0}}
    features["journal"] = {
        "kind": "hole",
        "at": [33.368, 0.0, 0.0],
        "axis": [0.0, 0.0, 1.0],
        "requirements": ["height"],
        "height": [33.118, 33.618],
        "height_from": "foot",
        "precision": dict(PRECISION),
    }
    features["crank"] = {
        "kind": "hole",
        "at": [crank_x, 0.0, 0.0],
        "axis": [0.0, 0.0, 1.0],
        "requirements": ["separation"],
        "separation": [39.332, 39.702],
        "height_from": "journal",
        "precision": dict(PRECISION),
    }
    setup(data)["ops"] = [
        {"op": 10, "do": "center", "feature": "journal", "tool": "cutter"},
        {"op": 20, "do": "center", "feature": "crank", "tool": "cutter"},
    ]
    return data


def _row(finding, name):
    (row,) = [row for row in finding.numbers["rows"] if row["feature"] == name]
    return row


def _aim(data, value):
    data.plan["aims"] = {
        "crank": {"requirement": "separation", "value_mm": value, "reason": "centre the band"}
    }


def test_a_nominal_target_below_its_printed_band_is_an_error():
    finding = coordinates.evaluate(_bores())[0]
    assert finding.status == "error"
    check = _row(finding, "crank")["band_check"]
    assert check["printed_band"] == [39.34, 39.7]
    assert check["value_mm"] == 39.332 and check["status"] == "error"
    assert "crank" in finding.numbers["band_errors"][0]


def test_an_aim_moves_the_dro_target_along_the_band_and_leaves_the_geometry_alone():
    data = _bores()
    _aim(data, 39.517)
    drawn = deepcopy(data.features["features"]["crank"])
    finding = coordinates.evaluate(data)[0]
    assert finding.status == "pass"
    crank = _row(finding, "crank")
    assert crank["nominal_setup"] == [72.7, 0.0, 0.0]
    assert crank["dro"] == [72.885, 0.0, 0.0]
    assert crank["aim"]["shift_mm"] == 0.185
    assert crank["band_check"] == {
        "requirement": "separation",
        "from": "journal",
        "printed_band": [39.34, 39.7],
        "value_mm": 39.517,
        "status": "pass",
    }
    assert data.features["features"]["crank"] == drawn
    assert "plan.aims.crank" in finding.cite
    # The unaimed journal prints on the 0.005 grid and is checked from the foot plane.
    journal = _row(finding, "journal")
    assert journal["dro"] == [33.37, 0.0, 0.0]
    assert journal["band_check"]["status"] == "pass"


def test_the_hole_op_dials_the_aimed_target_not_the_drawing_nominal():
    data = _bores()
    _aim(data, 39.517)
    crank = _row(coordinates.evaluate(data)[0], "crank")
    # The op row's tool-axis X/Y is the feature map's aimed DRO target, 0.185 off nominal.
    assert crank["dro_xy"] == [72.885, 0.0]


def test_an_aim_outside_the_printed_band_is_an_error():
    data = _bores()
    _aim(data, 39.335)  # inside the exported band, outside the printed 39.34
    finding = coordinates.evaluate(data)[0]
    assert finding.status == "error"
    assert _row(finding, "crank")["band_check"]["status"] == "error"


def test_dro_rounding_that_leaves_the_band_is_an_error():
    # Nominal separation 39.698 is inside 39.34-39.70; a 0.01 grid prints X 73.07 (39.702).
    data = _bores(crank_x=73.066, grid=0.01)
    finding = coordinates.evaluate(data)[0]
    crank = _row(finding, "crank")
    assert crank["setup"][0] == 73.066 and crank["dro"][0] == 73.07
    assert finding.status == "error" and crank["band_check"]["value_mm"] == 39.702


def test_an_aim_on_a_band_the_feature_does_not_hold_leaves_the_target_nominal():
    data = _bores()
    data.plan["aims"] = {
        "crank": {"requirement": "height", "value_mm": 72.885, "reason": "centre the band"}
    }
    finding = coordinates.evaluate(data)[0]
    crank = _row(finding, "crank")
    assert "holds no height band" in crank["aim"]["why"]
    assert crank["setup"] == [72.7, 0.0, 0.0]
    # Its nominal still fails its own printed separation band.
    assert finding.status == "error"
