"""Cutter-centre rows and hole targets sit on the DRO grid, rounded on the safe side."""

import pytest
from test_headroom import coordinate_bundle

from prechips.inputs import load_bundle
from prechips.rules import coordinates

# Model x 0..20, y 0..10; frame A puts setup XY at model XY - (5, 2): x -5..15, y -2..8.
SLAB = "kind = 'plane'\nbounds = { x = [0.0, 20.0], y = [0.0, 10.0], z = [0.0, 1.0] }\n"
STEP = 0.005
RADIUS = 4.7625  # a 3/8 in cutter: every offset lands between 0.005 grid points


def scratch(tmp_path, feature, op, band=None):
    """S1 op 20 on a 0.005 mm DRO with a 9.525 mm cutter; ``band`` is a thickness band."""
    plan = coordinate_bundle(tmp_path, feature, op)
    root = plan.parent
    inventory = root / "inventory.toml"
    inventory.write_text(
        inventory.read_text(encoding="utf-8")
        .replace(
            "[machines.mill]\nkind = 'mill'\n",
            "[machines.mill]\nkind = 'mill'\nresolution_mm = 0.005\n",
        )
        .replace(
            "[tools.cutter]\nkind = 'endmill'\ndia_mm = 6.0\n",
            "[tools.cutter]\nkind = 'endmill'\ndia_mm = 9.525\n",
        ),
        encoding="utf-8",
    )
    if band is not None:
        features = root / "features.toml"
        features.write_text(
            features.read_text(encoding="utf-8").replace(
                "requirements = []\n", f"requirements = ['thickness']\nthickness = {list(band)}\n"
            ),
            encoding="utf-8",
        )
    return next(row for row in coordinates.evaluate(load_bundle(plan)) if row.subject == "S1")


def on_grid(value):
    return abs(value / STEP - round(value / STEP)) < 1e-6


def outline(do, allowance=""):
    return (
        f"[[setups.ops]]\nop = 20\ndo = '{do}'\nfeature = 'target'\ntool = 'cutter'\n"
        f"to_z = -1.0\ndirection = 'conventional'\n{allowance}"
        "contour = { method = 'linear_table' }\n"
    )


@pytest.mark.parametrize(
    ("do", "allowance", "offset"),
    [
        ("rough_profile", "rough_allowance_mm = 0.3\n", RADIUS + 0.3),
        ("finish_profile", "", RADIUS),
    ],
)
def test_outline_rows_sit_on_the_grid_never_nearer_the_wall_than_authored(
    tmp_path, do, allowance, offset
):
    row = scratch(tmp_path, SLAB, outline(do, allowance))
    assert row.status == "pass", row.sentence
    (profile,) = row.numbers["profiles"]
    points = profile["cutter_centre"]
    assert points[0] == points[-1]
    for x, y in points:
        assert on_grid(x) and on_grid(y), (x, y)
        # Outside the setup box x -5..15, y -2..8 by at least the offset on both walls...
        assert max(-5 - x, x - 15) >= offset - 1e-9
        assert max(-2 - y, y - 8) >= offset - 1e-9
        # ...and by less than one grid step more.
        assert max(-5 - x, x - 15) < offset + STEP
        assert max(-2 - y, y - 8) < offset + STEP
    assert profile["grid_residual_mm"] == pytest.approx(0.0025)


@pytest.mark.parametrize(
    ("do", "band", "error"),
    [
        ("finish_profile", (1.0, 1.0025), False),  # the 0.0025 left is inside the band
        ("finish_profile", (1.0, 1.002), True),  # it is not
        ("rough_profile", (1.0, 1.002), False),  # the finish pass removes it
    ],
)
def test_a_finish_row_the_grid_leaves_off_its_wall_past_its_band_is_an_error(
    tmp_path, do, band, error
):
    allowance = "rough_allowance_mm = 0.3\n" if do.startswith("rough") else ""
    row = scratch(tmp_path, SLAB, outline(do, allowance), band=band)
    errors = row.numbers.get("dro_xy_residual_errors", [])
    assert (row.status == "error") is error, row.sentence
    assert bool(errors) is error
    if error:
        assert "op 20 finish rows on the 0.005 DRO grid leave 0.0025" in errors[0], errors


def pocket(do, side="-x", allowance=""):
    return (
        f"[[setups.ops]]\nop = 20\ndo = '{do}'\nfeature = 'target'\ntool = 'cutter'\n"
        f"to_z = -1.0\ndirection = 'conventional'\n{allowance}"
        f"contour = {{ method = 'linear_table', step_mm = 1.0, open_side = '{side}' }}\n"
    )


@pytest.mark.parametrize("side", ["-x", "+x", "-y", "+y"])
def test_raster_rows_sit_on_the_grid_on_the_safe_side(tmp_path, side):
    row = scratch(tmp_path, SLAB, pocket("rough_pocket", side, "rough_allowance_mm = 0.3\n"))
    assert row.status == "pass", row.sentence
    (profile,) = row.numbers["profiles"]
    passes = profile["cutter_centre"]
    along_x = side.endswith("x")
    stand = 0 if along_x else 1  # the axis each pass stands at
    low, high = (-5.0, 15.0) if along_x else (-2.0, 8.0)
    first, last = (-2.0, 8.0) if along_x else (-5.0, 15.0)
    positions = [p[0][stand] for p in passes]
    for a, b in passes:
        assert all(on_grid(v) for v in (*a, *b)), (a, b)
        # Pass ends run at least one cutter radius past both area edges.
        ends = sorted([a[1 - stand], b[1 - stand]])
        assert ends[0] <= first - RADIUS and ends[1] >= last + RADIUS
        assert ends[0] > first - RADIUS - STEP and ends[1] < last + RADIUS + STEP
    # The first pass stands wholly outside the open side; the last stops at least the
    # offset short of the far wall; none steps more than step_mm.
    if side.startswith("-"):
        assert positions[0] <= low - RADIUS and high - positions[-1] >= RADIUS + 0.3 - 1e-9
    else:
        assert positions[0] >= high + RADIUS and positions[-1] - low >= RADIUS + 0.3 - 1e-9
    assert all(0 < abs(b - a) <= 1.0 + 1e-9 for a, b in zip(positions, positions[1:], strict=False))
    assert profile["grid_residual_mm"] == pytest.approx(0.0025)
    raster = profile["raster"]
    assert raster["clearance_mm"] == RADIUS and raster["area_ends"] == [first, last]


@pytest.mark.parametrize(("band", "error"), [((1.0, 1.0025), False), ((1.0, 1.002), True)])
def test_a_finish_raster_wall_pass_past_its_band_is_an_error(tmp_path, band, error):
    row = scratch(tmp_path, SLAB, pocket("finish_pocket"), band=band)
    assert (row.status == "error") is error, row.sentence
    assert bool(row.numbers.get("dro_xy_residual_errors")) is error


def test_a_hole_target_prints_the_nearest_grid_point(tmp_path):
    hole = "kind = 'hole'\nat = [20.0023, 10.0076, 0.0]\naxis = [0.0, 0.0, 1.0]\n"
    op = "[[setups.ops]]\nop = 10\ndo = 'spot'\nfeature = 'target'\ntool = 'spot'\ndepth_mm = 0.5\n"
    row = scratch(tmp_path, hole, op)
    (target,) = [r for r in row.numbers["rows"] if r["feature"] == "target"]
    assert target["setup"][:2] == pytest.approx([15.0023, 8.0076])
    assert target["dro_xy"] == [15.0, 8.01]
