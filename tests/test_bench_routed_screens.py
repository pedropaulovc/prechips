"""Manual bench applicability and setup-entry stock boxes in the DRO and machine screens."""

from types import SimpleNamespace

import pytest

from prechips.rules import coordinates, headroom, zero_recipe

MEASURED = {"by": "test", "date": "2026-10-05", "instrument": "steel rule"}
SCREENS = [zero_recipe, coordinates, headroom]
NO_KERNEL = {
    "status": "unknown",
    "kernel_unavailable": True,
    "reason": "FreeCAD kernel unavailable; install FreeCAD or set FREECAD_CMD.",
}


def measured(value):
    return {"value": value, "measured": dict(MEASURED)}


def bench_bundle(kind="bench", actions=("fit", "inspect"), joint=None):
    """A bench setup with no DRO, zero recipe, frame, hold, tool or machine envelope."""
    setup = {
        "id": "B1",
        "machine": "station",
        "ops": [
            {"op": 10 * (index + 1), "do": action, "feature": "body"}
            for index, action in enumerate(actions)
        ],
    }
    if joint is not None:
        setup["stock_in"] = ["stock.post", "stock.base"]
        shape = "surface" if joint == "weld" else "cylindrical"
        setup["joint"] = {"kind": shape, "method": joint}
    definitions = {}
    return SimpleNamespace(
        plan={
            "part": "post",
            "stock": {"components": [{"id": "post"}, {"id": "base"}]},
            "setups": [setup],
        },
        inventory={"machines": {"station": {"kind": kind}}},
        features={"frames": {}, "features": definitions},
        feature_definitions=definitions,
        policy={},
        kernel=dict(NO_KERNEL),
    )


@pytest.mark.parametrize("kind", ["bench", "manual"])
@pytest.mark.parametrize(
    "actions,joint",
    [
        (("fit", "inspect"), "silver_braze"),
        (("fit", "inspect"), "retaining_compound"),
        (("fit",), "press"),
        (("fit",), "weld"),
        (("fit",), None),
        (("inspect",), None),
    ],
)
@pytest.mark.parametrize("screen", SCREENS)
def test_all_manual_bench_work_needs_no_dro_spindle_or_travel(screen, kind, actions, joint):
    row = screen.evaluate(bench_bundle(kind, actions, joint))[0]
    assert row.status == "not_applicable"
    assert row.numbers.get("kernel_unavailable") is not True


@pytest.mark.parametrize(
    "actions",
    [
        ("fit", "drill"),
        ("inspect", "face"),
        ("fit", "deburr"),
        ("fit", "unknown"),
        (),
    ],
)
@pytest.mark.parametrize("screen", SCREENS)
def test_nonmanual_unknown_or_absent_action_cannot_waive_bench_screens(screen, actions):
    row = screen.evaluate(bench_bundle(actions=actions, joint="silver_braze"))[0]
    assert row.status == "unknown"


@pytest.mark.parametrize("kind", ["mill", "lathe", "unknown"])
@pytest.mark.parametrize("screen", SCREENS)
def test_manual_only_ops_keep_mill_lathe_and_unknown_machine_screens(screen, kind):
    row = screen.evaluate(bench_bundle(kind=kind, joint="silver_braze"))[0]
    assert row.status == "unknown"


# --------------------------------------------------------------- setup-entry stock headroom

# Setup-frame box of the stock S3 receives: 170 x 90 mm in X/Y.
ENTRY_BBOX = [-10.0, -5.0, 0.0, 160.0, 85.0, 30.0]
ROUTES = ["component", "union", "derived"]


def mill_setup(sid, stock_in):
    setup = {
        "id": sid,
        "machine": "mill",
        "frame": "A",
        "stock_in": stock_in,
        "stock_state": {"top_z": 4, "bottom_z": -12},
        # Parallels lift the 16 mm stock so the 0 mm face cut clears the jaw tops at -4 mm.
        "hold": {"fixture": "vise", "parallels": "parallel"},
        "ops": [
            {
                "op": 10,
                "do": "face",
                "feature": "top",
                "tool": "cutter",
                "holder": "holder",
                "to_z": 0,
            }
        ],
    }
    if isinstance(stock_in, list):
        setup["joint"] = {"kind": "cylindrical", "method": "silver_braze"}
    return setup


def routed_bundle(route, travel_x=170, travel_y=200, entry=None, kernel=None):
    """S3 receives its stock by a component, joined or earlier-setup route.

    The derived route's raw 300 x 120 mm blank (S2's entry) cannot fit the travel S3's
    reduced entry stock fits; the finished part is smaller and the joined supplies larger
    than that entry stock.
    """
    if route == "derived":
        stock = {"length_mm": 300, "section_mm": [120, 40]}
        setups = [mill_setup("S2", "stock"), mill_setup("S3", "S2")]
    else:
        stock = {"components": [{"id": "post"}, {"id": "base"}]}
        stock_in = "stock.post" if route == "component" else ["stock.post", "stock.base"]
        setups = [mill_setup("S3", stock_in)]
    facts = {
        "status": "ok",
        "bbox_mm": [0.0, 0.0, 0.0, 60.0, 40.0, 20.0],
        "stock": {"bbox_mm": [0.0, 0.0, 0.0, 400.0, 300.0, 60.0]},
        "setups": {"S3": {"stock_bbox_mm": list(ENTRY_BBOX)} if entry is None else entry},
    }
    definitions = {}
    return SimpleNamespace(
        plan={"stock": stock, "setups": setups},
        inventory={
            "machines": {
                "mill": {
                    "kind": "mill",
                    "envelope": {
                        "spindle_to_table_max_mm": measured(200),
                        "travel_mm": {"x": measured(travel_x), "y": measured(travel_y)},
                    },
                }
            },
            "fixtures": {
                "vise": {
                    "kind": "vise",
                    "bed_height_mm": 20,
                    "jaw_height_mm": 40,
                    "length_mm": 150,
                    "width_mm": 80,
                },
                "parallel": {"kind": "parallels", "height_mm": 32},
            },
            "tools": {"cutter": {"kind": "endmill", "oal_mm": 80}},
            "holders": {"holder": {"kind": "collet", "gauge_len_mm": 30, "grip_mm": 25}},
        },
        features={"frames": {"A": {"x": [1, 0, 0], "y": [0, 1, 0]}}, "features": definitions},
        feature_definitions=definitions,
        policy={},
        kernel=facts if kernel is None else kernel,
    )


def row_for(data, sid="S3"):
    return next(row for row in headroom.evaluate(data) if row.subject == sid)


@pytest.mark.parametrize("route", ROUTES)
@pytest.mark.parametrize(
    "travel_x,travel_y,status",
    [
        (170, 90, "pass"),
        (169.9, 90, "error"),
        (170, 89.9, "error"),
    ],
)
def test_routed_travel_screen_uses_setup_entry_stock_box(route, travel_x, travel_y, status):
    row = row_for(routed_bundle(route, travel_x, travel_y))
    assert row.status == status
    checks = row.numbers["travel_checks"]
    assert checks["x"]["required_mm"] == 170
    assert checks["y"]["required_mm"] == 90


def test_raw_blank_outside_travel_does_not_fail_its_reduced_derived_entry():
    data = routed_bundle("derived", 170, 90)
    # The raw supply's own setup still screens the authored blank, which cannot fit.
    raw = row_for(data, "S2")
    assert raw.status == "error"
    assert raw.numbers["travel_checks"]["x"]["required_mm"] == 300
    assert row_for(data).status == "pass"


@pytest.mark.parametrize("route", ROUTES)
@pytest.mark.parametrize(
    "entry,kernel",
    [
        ({"stock_reason": "stock.base: supply dimensions are unknown"}, None),
        ({"assembly_error": "socket/spigot fit fails at a worst-case diameter extreme"}, None),
        ({}, None),
        (None, dict(NO_KERNEL)),
    ],
    ids=["stock-reason", "assembly-error", "no-entry-box", "kernel-unavailable"],
)
def test_absent_setup_entry_stock_stays_travel_debt_never_raw_blank(route, entry, kernel):
    # Generous travel: only the absent entry stock can keep the screen unresolved, and a
    # derived route must not fall back to its fitting 300 x 120 mm raw blank.
    row = row_for(routed_bundle(route, 1000, 1000, entry=entry, kernel=kernel))
    assert row.status == "unknown"
    for axis in ("x", "y"):
        assert row.numbers["travel_checks"][axis]["required_mm"] == "unknown"
    assert (row.numbers.get("kernel_unavailable") is True) == (kernel is not None)
