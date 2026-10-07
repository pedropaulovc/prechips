"""A located mill target must stand inside the height-like band it holds from its
``height_from`` reference, as the sheet prints that band and as the DRO grid places it.

A plan ``aims`` entry moves only the DRO target (never the feature geometry) so that band
reads a stated value; the cone post's crank bore (separation 39.332 from the journal on a
printed 39.34-39.70) is the case that motivated it.
"""

from copy import deepcopy

import pytest
from test_travel_m5 import bundle, measured, setup

from prechips.inputs import BadInput, load_bundle
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
    # Measured between the printed targets: crank 72.700 from journal 33.370.
    assert check["value_mm"] == 39.33 and check["status"] == "error"
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
        "value_mm": 39.515,  # 72.885 from the journal's printed 33.370
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


def test_an_aim_past_its_band_is_refused_even_where_dro_rounding_lands_inside():
    # The journal's printed height band is 33.12-33.61; 33.612 rounds to a 33.610 DRO
    # target inside it, but the aim itself asks for a value the drawing refuses.
    data = _bores()
    data.plan["aims"] = {
        "journal": {"requirement": "height", "value_mm": 33.612, "reason": "just past"}
    }
    finding = coordinates.evaluate(data)[0]
    assert finding.status == "error"
    journal = _row(finding, "journal")
    assert journal["dro"] == [33.37, 0.0, 0.0]  # never moved to the refused value
    assert any("aims.journal" in text for text in finding.numbers["band_errors"])


def test_a_negative_aim_never_crosses_the_reference():
    data = _bores()
    _aim(data, -39.517)
    finding = coordinates.evaluate(data)[0]
    assert finding.status == "error"
    assert _row(finding, "crank")["dro"] == [72.7, 0.0, 0.0]


FEATURES = """part = "review"
units = "mm"
precision = 2
[frames.model]
origin = [0.0, 0.0, 0.0]
x = [1.0, 0.0, 0.0]
y = [0.0, 1.0, 0.0]
z = [0.0, 0.0, 1.0]
binding = "measured"
[features.foot]
kind = "face"
plane = { frame = "model", axis = "x", value = 0.0 }
[features.hole]
kind = "hole"
at = [1.0, 0.0, 0.0]
axis = [0.0, 0.0, 1.0]
requirements = ["height"]
height = [0.9, 1.1]
height_from = "foot"
"""


def _load(tmp_path, value):
    (tmp_path / "inventory.toml").write_text(
        '[machines.mill]\nkind = "mill"\nresolution_mm = 0.005\n', encoding="utf-8"
    )
    (tmp_path / "cutting.toml").write_text("", encoding="utf-8")
    (tmp_path / "features.toml").write_text(FEATURES, encoding="utf-8")
    (tmp_path / "plan.toml").write_text(
        'part = "review"\nfeatures = "features.toml"\n'
        '[paths]\ninventory = "inventory.toml"\ncutting_data = "cutting.toml"\n'
        f'[aims.hole]\nrequirement = "height"\nvalue_mm = {value}\nreason = "probe"\n'
        '[[setups]]\nid = "S1"\nmachine = "mill"\nframe = "model"\n'
        '[[setups.ops]]\nop = 10\ndo = "center"\nfeature = "hole"\n',
        encoding="utf-8",
    )
    return load_bundle(tmp_path / "plan.toml")


@pytest.mark.parametrize("value", [1.101, -1.0, 0.899])
def test_loading_refuses_an_aim_outside_its_printed_band(tmp_path, value):
    with pytest.raises(BadInput, match="aims.hole"):
        _load(tmp_path, value)


def test_loading_accepts_an_aim_on_its_printed_band_limit(tmp_path):
    assert _load(tmp_path, 1.1).plan["aims"]["hole"]["value_mm"] == 1.1


def test_the_band_is_measured_between_the_two_printed_dro_targets():
    # Journal 33.368 prints 33.370 and crank 72.710 prints 72.710 on the 0.005 grid: the
    # manufactured separation is 39.340, below the printed 39.342 limit.
    data = _bores(crank_x=72.71)
    crank = data.features["features"]["crank"]
    crank.update(separation=[39.342, 39.702], precision={"separation": 3})
    finding = coordinates.evaluate(data)[0]
    assert finding.status == "error"
    check = _row(finding, "crank")["band_check"]
    assert check["value_mm"] == 39.34 and check["status"] == "error"


def test_a_reference_machined_in_another_setup_is_measured_at_its_model_position():
    # Without the journal's op here its model 33.368 is the reference: 73.07 - 33.368.
    data = _bores(crank_x=73.066, grid=0.01)
    setup(data)["ops"] = setup(data)["ops"][1:]
    finding = coordinates.evaluate(data)[0]
    assert finding.status == "error"
    assert _row(finding, "crank")["band_check"]["value_mm"] == 39.702


def _inch(value_mm):
    data = _bores()
    data.features["units"] = "in"
    data.features["features"]["journal"].update(at=[1.0, 0.0, 0.0], height=[0.9, 1.1])
    data.inventory["machines"]["mill"]["resolution_mm"] = measured(0.0254)
    setup(data)["ops"] = setup(data)["ops"][:1]
    data.plan["aims"] = {
        "journal": {"requirement": "height", "value_mm": value_mm, "reason": "probe"}
    }
    return data


def test_an_inch_drawing_converts_the_aim_and_reports_millimetres():
    finding = coordinates.evaluate(_inch(26.67))[0]  # 1.050 in
    assert finding.status == "pass"
    journal = _row(finding, "journal")
    assert journal["dro"] == [1.05, 0.0, 0.0]
    assert journal["aim"]["nominal_mm"] == 25.4 and journal["aim"]["shift_mm"] == 1.27
    assert journal["band_check"]["value_mm"] == 26.67


def test_an_inch_drawing_refuses_a_millimetre_aim_read_as_inches():
    finding = coordinates.evaluate(_inch(1.0))[0]  # 0.039 in, far below 0.9 in
    assert finding.status == "error"
    assert _row(finding, "journal")["dro"] == [1.0, 0.0, 0.0]


def test_unknown_units_leave_an_aim_unknown():
    data = _bores()
    _aim(data, 39.517)
    data.features["units"] = "unknown"
    finding = coordinates.evaluate(data)[0]
    assert finding.status == "unknown"
    assert _row(finding, "crank")["aim"]["why"]


def test_an_aim_on_a_parent_located_child_is_refused_with_its_reason():
    data = _bores()
    data.features["features"]["cbore"] = {
        "kind": "counterbore",
        "parent": "journal",
        "requirements": ["height"],
        "height": [33.0, 34.0],
        "height_from": "foot",
    }
    setup(data)["ops"] = [{"op": 10, "do": "center", "feature": "cbore", "tool": "cutter"}]
    data.plan["aims"] = {"cbore": {"requirement": "height", "value_mm": 33.5, "reason": "x"}}
    finding = coordinates.evaluate(data)[0]
    assert finding.status == "unknown"
    cbore = _row(finding, "cbore")
    assert "journal" in cbore["aim"]["why"]
    assert "plan.aims.cbore" in finding.cite


def test_a_child_dials_its_aimed_parent_target():
    data = _bores()
    data.features["features"]["cbore"] = {"kind": "counterbore", "parent": "crank"}
    setup(data)["ops"].append({"op": 30, "do": "center", "feature": "cbore", "tool": "cutter"})
    _aim(data, 39.517)
    finding = coordinates.evaluate(data)[0]
    assert finding.status == "pass"
    cbore = _row(finding, "cbore")
    assert cbore["dro_xy"] == [72.885, 0.0] and cbore["aim"]["feature"] == "crank"


@pytest.mark.parametrize("resolution", ["unknown", 0.005])
def test_an_unknown_or_unmeasured_dro_grid_never_passes_a_band(resolution):
    data = _bores()
    _aim(data, 39.517)
    data.inventory["machines"]["mill"]["resolution_mm"] = resolution
    finding = coordinates.evaluate(data)[0]
    assert finding.status == "unknown"
    assert _row(finding, "crank")["band_check"]["status"] == "unknown"


def test_explicitly_unknown_hole_axes_leave_the_band_unknown():
    data = _bores(crank_x=72.885)
    for name in ("journal", "crank"):
        data.features["features"][name]["axis"] = "unknown"
    finding = coordinates.evaluate(data)[0]
    assert finding.status == "unknown"
    check = _row(finding, "crank")["band_check"]
    assert check["status"] == "unknown" and "axis" in check["why"]
