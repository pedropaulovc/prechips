"""Lathe headroom (swing and length) and lathe feed per revolution boundaries."""

from types import SimpleNamespace

import pytest

from prechips.rules import headroom, speeds_feeds

MEASURED = {"by": "test", "date": "2026-10-03", "instrument": "tape"}


def measured(value):
    return {"value": value, "measured": dict(MEASURED)}


def lathe_bundle(od=20.0, stickout=60.0, swing=280.0, centres=700.0):
    data = SimpleNamespace(
        plan={
            "stock": {"material": "1018", "dia_mm": od},
            "setups": [
                {
                    "id": "S1",
                    "machine": "lathe",
                    "stock_state": {"od_mm": od, "north_end_z": 10, "south_end_z": -90},
                    "hold": {"fixture": "chuck", "stickout_mm": stickout},
                    "ops": [
                        {"op": 10, "do": "finish_turn", "feature": "pin", "tool": "turn"},
                    ],
                }
            ],
        },
        features={"units": "mm", "features": {"pin": {"dia_nominal": 12.7}}},
        inventory={
            "machines": {
                "lathe": {
                    "kind": "lathe",
                    "spindle": {"ranges_rpm": [[70, 380], [380, 2200]]},
                    "envelope": {
                        "swing_over_bed_mm": measured(swing),
                        "swing_over_cross_slide_mm": measured(swing * 0.6),
                        "between_centres_mm": measured(centres),
                    },
                }
            },
            "fixtures": {
                "chuck": {"kind": "chuck_3jaw", "body_dia_mm": 150.0, "body_length_mm": 80.0}
            },
            "tools": {"turn": {"kind": "turning", "material": "HSS"}},
        },
        policy={},
        cutting_data={
            "aliases": {"1018": "low_carbon_steel"},
            "cut": [
                {
                    "material_class": "low_carbon_steel",
                    "tool_material": "HSS",
                    "operation": "finish_turn",
                    "diameter_range": [5.0, 25.0],
                    "sfm": 100.0,
                    "chip_load_mm_per_tooth": "unknown",
                    "feed_mm_rev": 0.1,
                    "cite": "test table p. 1",
                }
            ],
        },
    )
    data.feature_definitions = data.features["features"]
    return data


@pytest.mark.parametrize(
    "od,stickout,status",
    [
        (20.0, 60.0, "pass"),
        (168.0, 60.0, "pass"),  # exactly the cross-slide swing
        (168.5, 60.0, "error"),
        (20.0, 620.0, "pass"),  # 620 + 80 body = between centres
        (20.0, 621.0, "error"),
    ],
)
def test_lathe_headroom_is_swing_and_length_between_centres(od, stickout, status):
    row = headroom.evaluate(lathe_bundle(od=od, stickout=stickout))[0]
    assert row.status == status


def test_unmeasured_lathe_envelope_never_passes():
    bundle = lathe_bundle()
    del bundle.inventory["machines"]["lathe"]["envelope"]["between_centres_mm"]
    row = headroom.evaluate(bundle)[0]
    assert row.status == "unknown" and row.numbers["measurements"]


def test_lathe_feed_is_rpm_times_cited_feed_per_rev():
    row = speeds_feeds.evaluate(lathe_bundle())[0]
    # 12*100/(pi*0.5 in) = 763.9 -> 750 rpm; 750 * 0.1 mm/rev.
    assert row.status == "pass"
    assert row.numbers["rpm"] == 750
    assert row.numbers["feed_mm_min"] == pytest.approx(75.0)
    assert row.numbers["feed_mm_rev"] == 0.1


@pytest.mark.parametrize("per_rev", ["unknown", 0.0])
def test_lathe_feed_without_a_cited_feed_per_rev_is_unknown(per_rev):
    bundle = lathe_bundle()
    bundle.cutting_data["cut"][0]["feed_mm_rev"] = per_rev
    row = speeds_feeds.evaluate(bundle)[0]
    assert row.status == "unknown" and row.numbers["feed_mm_min"] == "unknown"


@pytest.mark.parametrize("planned,status", [(0.05, "pass"), ("unknown", "unknown")])
def test_a_planned_feed_per_rev_is_the_feed_evaluated_not_the_table_row(planned, status):
    # turning_deflection loads the cut with the op's feed_mm_rev: the row prints that feed.
    bundle = lathe_bundle()
    bundle.plan["setups"][0]["ops"][0]["feed_mm_rev"] = planned
    row = speeds_feeds.evaluate(bundle)[0]
    assert row.status == status and row.numbers["feed_mm_rev"] == planned
    if status == "pass":
        assert row.numbers["feed_mm_min"] == pytest.approx(750 * 0.05)


def test_lathe_rpm_clamps_to_the_slowest_band():
    bundle = lathe_bundle()
    bundle.cutting_data["cut"][0]["sfm"] = 5.0
    assert speeds_feeds.evaluate(bundle)[0].numbers["rpm"] == 70
