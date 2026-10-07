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


@pytest.mark.parametrize("action", ["inspect", "deburr"])
def test_a_reference_this_setup_does_not_machine_stands_at_its_model_position(action):
    # Only inspecting (or deburring) the journal here leaves it at 33.368, not at its
    # printed 33.370: the crank's 73.070 target stands 39.702 from it, past 39.70.
    data = _bores(crank_x=73.066, grid=0.01)
    setup(data)["ops"][0]["do"] = action
    finding = coordinates.evaluate(data)[0]
    assert finding.status == "error"
    assert _row(finding, "crank")["band_check"]["value_mm"] == 39.702


def test_machining_a_child_does_not_move_its_unmachined_parent():
    # A counterbore dialled at the journal's printed 33.370 leaves the journal hole itself
    # where it was made, 33.368: the crank's 73.070 target stands 39.702 from it.
    data = _bores(crank_x=73.066, grid=0.01)
    data.features["features"]["cbore"] = {"kind": "counterbore", "parent": "journal"}
    setup(data)["ops"][0]["feature"] = "cbore"
    finding = coordinates.evaluate(data)[0]
    assert finding.status == "error"
    assert _row(finding, "crank")["band_check"]["value_mm"] == 39.702


def test_a_feature_this_setup_only_inspects_is_checked_where_it_was_made():
    # Bored at 73.074, the crank stands 39.704 from the journal's printed 33.370; its
    # inspection row prints 73.070 (39.700) but that display does not move it inside.
    data = _bores(crank_x=73.074, grid=0.01)
    setup(data)["ops"][1]["do"] = "inspect"
    finding = coordinates.evaluate(data)[0]
    assert finding.status == "error"
    crank = _row(finding, "crank")
    assert crank["dro"] == [73.07, 0.0, 0.0]
    assert crank["band_check"]["value_mm"] == 39.704


def _inspected(data, *, machined):
    """``data`` with its one setup only inspecting both bores; ``machined`` adds a second
    setup that centres them (where an aim is cut)."""
    cut = deepcopy(setup(data))
    for op in setup(data)["ops"]:
        op["do"] = "inspect"
    if machined:
        data.plan["setups"].append({**cut, "id": "S2"})
    return data


def test_an_inspected_aimed_feature_is_checked_at_its_aimed_point():
    # As in the cone's final inspection setup: both bores were cut in another setup, the
    # crank at its aim, so the band reads the aim between their planned points here, not
    # between this setup's display roundings.
    data = _bores()
    _aim(data, 39.517)
    finding = coordinates.evaluate(_inspected(data, machined=True))[0]
    assert finding.status == "pass"
    assert _row(finding, "crank")["band_check"]["value_mm"] == 39.517


def test_an_aim_on_a_feature_no_setup_cuts_moves_nothing():
    # Only inspected, the crank stays at its drawing nominal: 39.332, below the band.
    data = _bores()
    _aim(data, 39.517)
    finding = coordinates.evaluate(_inspected(data, machined=False))[0]
    assert finding.status == "error"
    crank = _row(finding, "crank")
    assert crank["dro"] == [72.7, 0.0, 0.0] and "crank" in crank["aim"]["why"]
    assert crank["band_check"]["value_mm"] == 39.332


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
    assert "journal" in cbore["refused_aim"]["why"]
    assert "aim" not in cbore and cbore["dro"] == [33.37, 0.0, 0.0]
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


@pytest.mark.parametrize(
    ("crank_aim", "target", "status"),
    [(39.517, 72.885, "unknown"), (39.335, 72.7, "error")],
)
def test_a_refused_child_aim_keeps_the_child_on_its_parents_target(crank_aim, target, status):
    # The counterbore's own aim is refused; it still dials the crank's actual target, the
    # aimed 72.885 when that aim holds and the nominal 72.700 when it is refused too.
    data = _bores()
    _aim(data, crank_aim)
    data.features["features"]["cbore"] = {
        "kind": "counterbore",
        "parent": "crank",
        "requirements": ["height"],
        "height": [72.0, 74.0],
        "height_from": "foot",
    }
    data.plan["aims"]["cbore"] = {"requirement": "height", "value_mm": 73.0, "reason": "x"}
    setup(data)["ops"].append({"op": 30, "do": "center", "feature": "cbore", "tool": "cutter"})
    finding = coordinates.evaluate(data)[0]
    assert finding.status == status
    crank, cbore = _row(finding, "crank"), _row(finding, "cbore")
    assert crank["dro"] == cbore["dro"] == [target, 0.0, 0.0]
    assert cbore["dro_xy"] == [target, 0.0]
    assert cbore["aim"]["feature"] == "crank" and "crank" in cbore["refused_aim"]["why"]
    assert {"plan.aims.crank", "plan.aims.cbore"} <= set(finding.cite)


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


def _coaxial(**cbore):
    """The bores with a counterbore on the journal (no ``at`` or ``axis`` of its own) as
    the only feature centred; ``cbore`` adds fields to it."""
    data = _bores(crank_x=72.885)
    data.features["features"]["cbore"] = {"kind": "counterbore", "parent": "journal", **cbore}
    setup(data)["ops"] = [{"op": 10, "do": "center", "feature": "cbore", "tool": "cutter"}]
    return data


@pytest.mark.parametrize(
    ("axis", "status", "value"),
    [
        ("unknown", "unknown", None),
        ([1.0, 0.0, 0.0], "error", 0.0),
        ([0.0, 0.0, 1.0], "pass", 39.515),
    ],
)
def test_a_coaxial_child_without_an_axis_takes_its_parents(axis, status, value):
    # On the journal's axis: an unknown one leaves the separation unmeasured, one along X
    # meets the crank's axis, one along Z reads 33.370 to 72.885.
    data = _coaxial(requirements=["separation"], separation=[39.34, 39.7], height_from="crank")
    data.features["features"]["journal"]["axis"] = axis
    finding = coordinates.evaluate(data)[0]
    assert finding.status == status
    check = _row(finding, "cbore")["band_check"]
    assert check.get("value_mm") == value
    assert value is not None or "journal's axis" in check["why"]


def test_a_coaxial_child_reference_takes_its_parents_unknown_axis():
    data = _coaxial()
    data.features["features"]["journal"]["axis"] = "unknown"
    data.features["features"]["crank"]["height_from"] = "cbore"
    setup(data)["ops"] = [{"op": 10, "do": "center", "feature": "crank", "tool": "cutter"}]
    finding = coordinates.evaluate(data)[0]
    assert finding.status == "unknown"
    check = _row(finding, "crank")["band_check"]
    assert check["status"] == "unknown" and "journal's axis" in check["why"]


@pytest.mark.parametrize(
    "link",
    [{"kind": "counterbore", "parent": "journal"}, {"kind": "boss", "coaxial_to": "journal"}],
)
def test_a_feature_on_the_journal_axis_takes_it_even_with_its_own_at(link):
    # A counterbore of the journal, or a boss drawn coaxial with it, placed by its own at:
    # that point still fixes no direction for its separation from the crank.
    data = _coaxial()
    data.features["features"]["journal"]["axis"] = "unknown"
    data.features["features"]["cbore"] = {
        **link,
        "at": [33.368, 0.0, 5.0],
        "requirements": ["separation"],
        "separation": [39.34, 39.7],
        "height_from": "crank",
    }
    finding = coordinates.evaluate(data)[0]
    assert finding.status == "unknown"
    check = _row(finding, "cbore")["band_check"]
    assert check["status"] == "unknown" and "journal's axis" in check["why"]


def test_a_coaxial_child_reads_its_parents_axis_in_the_parents_frame():
    # The journal declares [1, 0, 0] in a frame whose x is model Z; read in the
    # counterbore's own model frame it would run along X and meet the crank's axis.
    data = _coaxial(requirements=["separation"], separation=[39.34, 39.7], height_from="crank")
    data.features["frames"]["turned"] = {
        "origin": [0.0, 0.0, 0.0],
        "x": [0.0, 0.0, 1.0],
        "y": [0.0, 1.0, 0.0],
        "z": [-1.0, 0.0, 0.0],
    }
    data.features["features"]["journal"].update(
        frame="turned", at=[0.0, 0.0, -33.368], axis=[1.0, 0.0, 0.0]
    )
    finding = coordinates.evaluate(data)[0]
    assert finding.status == "pass"
    assert _row(finding, "cbore")["band_check"]["value_mm"] == 39.515
