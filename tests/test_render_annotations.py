"""Shop annotations retain table targets without inventing connected toolpaths."""

from types import SimpleNamespace

import pytest

from prechips.kernel.render_inputs import contour_annotations, setup_annotations


def _bundle(units="mm"):
    return SimpleNamespace(features={"units": units}, inventory={"fixtures": {}})


def _setup():
    return {
        "hold": {"fixture": "none"},
        "stock_state": {},
        "ops": [{"op": 10, "tool": "endmill"}, {"op": 20, "tool": "turning_tool"}],
    }


def _point_keys(waypoints, op, axis="xy"):
    selected = [point for point in waypoints if point["op"] == str(op) and axis in point]
    keys = {tuple(point[axis]): point["label"] for point in selected}
    assert len(keys) == len(selected), "one table key per operation and geometric point"
    return keys


def _assert_table_keys(waypoints):
    labels = [point["label"] for point in waypoints]
    assert len(labels) == len(set(labels)), "different annotated rows must not share an identifier"
    assert all(label.startswith("P") and label[1:].isdigit() for label in labels)


def test_arc_end_midpoint_and_line_corners_share_keys_only_within_their_operation():
    arc_points = [[-5, 0], [-3, 4], [0, 5], [3, 4], [5, 0]]
    line_points = [[-5, 0], [-5, -2], [5, -2], [5, 0]]
    numbers = {
        "arc_table": [{"op": 10, "rows": [{"setup_xy": point} for point in arc_points]}],
        "line_table": [
            {"op": 10, "setup_xy": line_points},
            {"op": 20, "setup_xy": [[5, 0], [5, -2]]},
        ],
        # The coordinate report also exposes an arc as a generic profile. It
        # must not become a second contour or label every chord checkpoint.
        "profiles": [{"op": 10, "cutter_centre": [{"x": x, "y": y} for x, y in arc_points]}],
    }

    paths, waypoints = contour_annotations(numbers, 1.0)

    assert [path["xy"] for path in paths if path["op"] == "10"] == [arc_points, line_points]
    assert [path["xy"] for path in paths if path["op"] == "20"] == [[[5, 0], [5, -2]]]
    keys10 = _point_keys(waypoints, 10)
    keys20 = _point_keys(waypoints, 20)
    assert set(keys10) == {(-5, 0), (0, 5), (5, 0), (-5, -2), (5, -2)}
    assert set(keys20) == {(5, 0), (5, -2)}
    assert keys10[(5, 0)] != keys20[(5, 0)]
    assert keys10[(5, -2)] != keys20[(5, -2)]
    _assert_table_keys(waypoints)


def test_mirrored_line_points_keep_their_signed_setup_coordinates():
    west = [[-7.25, 1.5], [-3.5, 5.0], [-1.0, 5.0]]
    east = [[7.25, 1.5], [3.5, 5.0], [1.0, 5.0]]
    numbers = {
        "line_table": [
            {"op": 10, "setup_xy": west},
            {"op": 10, "setup_xy": east},
        ]
    }

    paths, waypoints = contour_annotations(numbers, 1.0)

    assert [path["xy"] for path in paths] == [west, east]
    keys = _point_keys(waypoints, 10)
    assert set(keys) == {tuple(point) for point in west + east}
    for left, right in zip(west, east, strict=True):
        assert keys[tuple(left)] != keys[tuple(right)]
    _assert_table_keys(waypoints)


def test_inch_contour_points_and_waypoint_keys_are_converted_to_millimetres():
    numbers = {
        "line_table": [{"op": 10, "setup_xy": [[0.25, -0.5], [1.0, 0.75], [1.0, -0.5]]}]
    }

    annotation = setup_annotations(_bundle("in"), _setup(), numbers)

    path = annotation["paths"][0]
    assert path["op"] == "10"
    expected = [[6.35, -12.7], [25.4, 19.05], [25.4, -12.7]]
    for actual, target in zip(path["xy"], expected, strict=True):
        assert actual == pytest.approx(target)
    for waypoint, target in zip(annotation["waypoints"], expected, strict=True):
        assert waypoint["op"] == "10"
        assert waypoint["xy"] == pytest.approx(target)
    _assert_table_keys(annotation["waypoints"])


@pytest.mark.parametrize("source", ["arc", "line", "profile_points", "profile_rows"])
@pytest.mark.parametrize("unknown", [None, ["unknown", 5], [5, "unknown"]])
def test_unknown_interior_point_cannot_join_known_ends_or_claim_endpoint_keys(source, unknown):
    broken = [[0, 0], unknown, [10, 10]]
    valid = [[20, 0], [25, 5]]
    numbers = {"line_table": [{"op": 20, "setup_xy": valid}]}
    if source == "arc":
        numbers["arc_table"] = [{"op": 10, "rows": [{"setup_xy": point} for point in broken]}]
    elif source == "line":
        numbers["line_table"].append({"op": 10, "setup_xy": broken})
    else:
        points = broken
        if source == "profile_rows":
            points = [
                {"x": point[0], "y": point[1]} if point is not None else {"x": None, "y": None}
                for point in broken
            ]
        numbers["profiles"] = [{"op": 10, "cutter_centre": points}]

    paths, waypoints = contour_annotations(numbers, 1.0)

    assert paths == [{"op": "20", "xy": valid}]
    assert _point_keys(waypoints, 10) == {}
    assert set(_point_keys(waypoints, 20)) == {(20, 0), (25, 5)}
    _assert_table_keys(waypoints)


@pytest.mark.parametrize("unknown_middle", [False, True])
def test_raster_passes_remain_independent_even_when_a_middle_pass_is_incomplete(unknown_middle):
    first = [[0, 0], [10, 0]]
    middle = [[10, 2], ["unknown", 2], [0, 2]] if unknown_middle else [[10, 2], [0, 2]]
    last = [[0, 4], [10, 4]]
    numbers = {"profiles": [{"op": 10, "cutter_centre": [first, middle, last]}]}

    paths, waypoints = contour_annotations(numbers, 1.0)

    expected = [first, last] if unknown_middle else [first, middle, last]
    assert [path["xy"] for path in paths] == expected
    assert all(path["op"] == "10" for path in paths)
    # A fabricated traverse between raster passes would change Y within a path.
    assert all(len({point[1] for point in path["xy"]}) == 1 for path in paths)
    assert set(_point_keys(waypoints, 10)) == {(0, 0), (10, 0), (0, 4), (10, 4)}
    _assert_table_keys(waypoints)


@pytest.mark.parametrize("x_display", ["diameter", "radius"])
def test_axial_paths_and_sparse_row_keys_keep_displayed_x_targets_not_solid_radii(x_display):
    radii = [0.0, 3.0, 5.0, 6.0, 8.0]
    stations = [20.0, 18.0, 16.0, 12.0, 10.0]
    multiplier = 2 if x_display == "diameter" else 1
    displayed = [[radius * multiplier, z] for radius, z in zip(radii, stations, strict=True)]
    rows = [
        {
            "setup_xz": point,
            "x_target_mm": point[0],
            "radius_mm": radius,
            "diameter_mm": 2 * radius,
        }
        for point, radius in zip(displayed, radii, strict=True)
    ]
    numbers = {
        "x_display": x_display,
        "line_table": [{"op": 10, "setup_xy": [[-1, 0], [1, 0]]}],
        "contours": [{"op": 20, "rows": rows}],
    }

    annotation = setup_annotations(_bundle(), _setup(), numbers)

    assert annotation["axial_paths"] == [{"op": "20", "xz": displayed, "x_display": x_display}]
    keys = _point_keys(annotation["waypoints"], 20, axis="xz")
    assert set(keys) == {tuple(displayed[index]) for index in (0, 2, 4)}
    assert set(_point_keys(annotation["waypoints"], 10)) == {(-1, 0), (1, 0)}
    assert set(keys.values()).isdisjoint(_point_keys(annotation["waypoints"], 10).values())
    _assert_table_keys(annotation["waypoints"])


def test_unknown_axial_interior_does_not_fabricate_a_profile_or_table_keys():
    numbers = {
        "x_display": "diameter",
        "contours": [
            {
                "op": 10,
                "rows": [
                    {"setup_xz": [8, 20]},
                    {"setup_xz": ["unknown", 15]},
                    {"setup_xz": [12, 10]},
                ],
            },
            {"op": 20, "rows": [{"setup_xz": [6, 10]}, {"setup_xz": [8, 0]}]},
        ],
    }

    annotation = setup_annotations(_bundle(), _setup(), numbers)

    assert annotation["axial_paths"] == [
        {"op": "20", "xz": [[6, 10], [8, 0]], "x_display": "diameter"}
    ]
    assert _point_keys(annotation["waypoints"], 10, axis="xz") == {}
    assert set(_point_keys(annotation["waypoints"], 20, axis="xz")) == {(6, 10), (8, 0)}
    _assert_table_keys(annotation["waypoints"])
