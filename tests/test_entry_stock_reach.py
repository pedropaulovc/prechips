"""The stock a setup receives and the span its cutter must reach, in setup axes (#297)."""

from copy import deepcopy

import pytest
from test_headroom import bundle, measured

from prechips.findings import Finding
from prechips.rules import headroom, travel
from prechips.rules._envelope import blank_extents
from prechips.rules.geometry_common import lend_rows

IDENTITY = {"x": [1, 0, 0], "y": [0, 1, 0], "z": [0, 0, 1]}


@pytest.mark.parametrize(
    ("stock", "extents"),
    [
        # A box whose length stands on Z: never read along model X (sharp-corner S1).
        (
            {"length_mm": 21, "section_mm": [60, 40], "axis": [0, 0, 1], "section_axis": [1, 0, 0]},
            (60, 40, 21),
        ),
        # A box along model Y, its section across X then Z.
        (
            {
                "length_mm": 38,
                "section_mm": [19.05, 31.75],
                "axis": [0, 1, 0],
                "section_axis": [1, 0, 0],
            },
            (19.05, 38, 31.75),
        ),
        # A round bar standing on Z shows its diameter on both table axes (fixture-holds S1).
        ({"length_mm": 20, "dia_mm": 30, "axis": [0, 0, 1]}, (30, 30, 20)),
        ({"length_mm": 100, "dia_mm": 25, "axis": [1, 0, 0]}, (100, 25, 25)),
    ],
    ids=["box-on-z", "box-along-y", "round-on-z", "round-along-x"],
)
def test_an_authored_blank_is_placed_by_its_own_axes(stock, extents):
    result = blank_extents(stock, IDENTITY)
    assert tuple(result[axis] for axis in "xyz") == pytest.approx(extents)


@pytest.mark.parametrize(
    "missing", ["axis", "section_axis", "length_mm"], ids=lambda key: f"no-{key}"
)
def test_an_unplaced_blank_is_unknown_never_assumed_along_model_x(missing):
    stock = {"length_mm": 100, "section_mm": [30, 16], "axis": [1, 0, 0], "section_axis": [0, 1, 0]}
    del stock[missing]
    assert set(blank_extents(stock, IDENTITY).values()) == {"unknown"}


def test_a_rotated_raw_blank_feeds_headroom_in_setup_axes():
    data = bundle()
    data.plan["stock"].update(axis=[0, 1, 0], section_axis=[1, 0, 0])
    numbers = headroom.evaluate(data)[0].numbers
    assert (numbers["stock_extent_x_mm"], numbers["stock_extent_y_mm"]) == (30, 100)


@pytest.mark.parametrize(
    "route",
    ["raw", "prepared", "profiled", "component", "earlier setup"],
)
def test_the_kernel_setup_entry_box_is_read_for_every_stock_form(route):
    data = bundle()
    stock, setup = data.plan["stock"], data.plan["setups"][0]
    if route == "prepared":
        stock["prepare"] = [{"do": "saw", "length_mm": 80}]
    elif route == "profiled":
        stock.clear()
        stock["blank"] = {"step_path": "blank.step", "step_sha256": "0" * 64}
    elif route == "component":
        stock["components"] = [{"id": "body", "length_mm": 100, "section_mm": [30, 16]}]
        setup["stock_in"] = "stock.body"
    elif route == "earlier setup":
        earlier = deepcopy(setup)
        earlier["id"] = "S0"
        data.plan["setups"].insert(0, earlier)
        setup["stock_in"] = "S0"
    # The kernel's entry box (in the setup frame) is what the setup receives.
    data.kernel = {
        "status": "ok",
        "setups": {sid: {"stock_bbox_mm": [-5, -7, -12, 75, 18, 4]} for sid in ("S0", "S1")},
    }
    numbers = next(f for f in headroom.evaluate(data) if f.subject == "S1").numbers
    assert (numbers["stock_extent_x_mm"], numbers["stock_extent_y_mm"]) == (80, 25)
    assert numbers["stock_entry_basis"] == "kernel setup-entry stock"


@pytest.mark.parametrize("route", ["component", "earlier setup"])
def test_a_routed_stock_without_the_kernel_box_stays_unknown(route):
    data = bundle()
    setup = data.plan["setups"][0]
    if route == "component":
        data.plan["stock"]["components"] = [{"id": "body"}]
        setup["stock_in"] = "stock.body"
    else:
        earlier = deepcopy(setup)
        earlier["id"] = "S0"
        data.plan["setups"].insert(0, earlier)
        setup["stock_in"] = "S0"
    numbers = next(f for f in headroom.evaluate(data) if f.subject == "S1").numbers
    assert numbers["stock_extent_x_mm"] == "unknown"


def printed(*points):
    """The coordinates rows a traveler prints for S1 op 10: one join line through
    ``points`` (setup-frame cutter centres)."""
    numbers = {"line_table": [{"op": 10, "dro_xy": [list(p) for p in points]}]}
    return {"coordinates": [Finding("coordinates", "S1", "pass", numbers, [], "")]}


def test_the_travel_span_covers_the_printed_cutter_path_and_headroom_needs_it():
    # A face raster runs 12 mm past each end of the 100 mm blank (rocker P1's 345 vs 368).
    data = bundle()
    rows = printed((-12, 5), (112, 5))
    with lend_rows(data, rows):
        [span] = travel.evaluate(data)
        [row] = headroom.evaluate(data)
    assert span.numbers["travel_checks"]["x"]["required_mm"] == 124
    assert span.numbers["operations"][0]["printed_xy_bounds_mm"]["x"] == [-12, 112]
    assert row.numbers["travel_checks"]["x"] == {
        "travel_mm": 400,
        "part_mm": 100,
        "required_mm": 124,
    }
    # The printed path reaching past the travel is an error on both rows.
    data.inventory["machines"]["mill"]["envelope"]["travel_mm"]["x"] = measured(120)
    with lend_rows(data, rows):
        assert travel.evaluate(data)[0].status == "error"
        assert headroom.evaluate(data)[0].status == "error"


def test_a_printed_path_raises_but_never_completes_an_unresolved_span():
    data = bundle()
    data.plan["stock"].pop("axis")
    with lend_rows(data, printed((-12, 5), (112, 5))):
        [span] = travel.evaluate(data)
        [row] = headroom.evaluate(data)
    x = span.numbers["travel_checks"]["x"]
    assert x["required_mm"] == "unknown"
    assert x["minimum_required_mm"] == 124
    assert row.status == "unknown"
    assert row.numbers["travel_checks"]["x"]["required_mm"] == "unknown"
