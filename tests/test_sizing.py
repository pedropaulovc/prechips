from pathlib import Path

import pytest

from prechips.checks import CheckError
from prechips.cli import main
from prechips.sizing import check
from prechips.traveler import LoadedPlan

EXAMPLES = Path(__file__).resolve().parents[1] / "examples"


def _plan(sizing, *, drill=4.9784, tap_drill=3.4544, tool="drill"):
    operation = {"instruction": "Drill."}
    if tool:
        operation["tool"] = tool
    if sizing is not None:
        operation["sizing"] = sizing
    data = {
        "tools": [
            {"id": "drill", "description": "Drill", "diameter_mm": drill},
            {"id": "tap", "description": "Tap", "tap_drill_mm": tap_drill},
            {"id": "bare", "description": "Unsized"},
        ],
        "setups": [
            {"title": "Holes", "operations": [{"instruction": "Set."}, operation]}
        ],
    }
    return LoadedPlan(data, Path("plan.toml"), None, {}, None, {})


BAND = {"kind": "band", "band_mm": [4.9784, 5.08]}
TAP = {"kind": "tap_drill", "tap": "tap"}


@pytest.mark.parametrize("drill", [4.9784, 5.0, 5.08])
def test_band_is_inclusive(drill):
    check(_plan(BAND, drill=drill))


@pytest.mark.parametrize("drill", [4.9783, 5.0801])
def test_outside_band_refuses_with_location(drill):
    with pytest.raises(CheckError) as error:
        check(_plan(BAND, drill=drill))
    assert str(error.value) == (
        f"setup 1 (Holes), Op 20, sizing: tool 'drill' diameter {drill:.6g} mm "
        "is outside band 4.9784–5.08 mm"
    )


@pytest.mark.parametrize("drill", [3.4544, 3.4544 + 0.9e-6, 3.4544 - 0.9e-6])
def test_tap_drill_matches_within_tolerance(drill):
    check(_plan(TAP, drill=drill))


@pytest.mark.parametrize("drill", [3.454, 3.4544 + 2e-6])
def test_tap_drill_mismatch_refuses(drill):
    with pytest.raises(CheckError, match="does not match tap 'tap' tap drill 3.4544"):
        check(_plan(TAP, drill=drill))


@pytest.mark.parametrize(
    ("sizing", "options", "message"),
    [
        (None, {}, "tool 'drill' requires sizing"),
        ("other", {"tool": None}, "sizing declared without a tool"),
        ("band", {}, 'sizing must be "other" or a table'),
        ({"kind": "nearest"}, {}, "sizing.kind: expected band or tap_drill"),
        (BAND, {"tool": "bare"}, "tool 'bare' diameter_mm is not declared"),
        ({"kind": "band", "band_mm": [5.1, 5.0]}, {}, "reversed band"),
        ({"kind": "band", "band_mm": "5.0"}, {}, "expected [low, high]"),
        ({"kind": "tap_drill", "tap": "missing"}, {}, "unknown tool 'missing'"),
        ({"kind": "tap_drill", "tap": "bare"}, {}, "'bare' tap_drill_mm is not"),
        (BAND, {"drill": "4.98"}, "tool 'drill' diameter_mm: expected a positive"),
    ],
)
def test_coverage_and_shape_refusals(sizing, options, message):
    with pytest.raises(CheckError) as error:
        check(_plan(sizing, **options))
    assert message in str(error.value)


def _base_bar(tmp_path, old, new):
    """The real base bar with one shop line replaced."""
    shop = (EXAMPLES / "shop.toml").read_text(encoding="utf-8")
    assert old in shop
    (tmp_path / "shop.toml").write_text(shop.replace(old, new), encoding="utf-8")
    plan = (EXAMPLES / "base-bar.toml").read_text(encoding="utf-8")
    plan = plan.replace('"cad/', f'"{(EXAMPLES / "cad").as_posix()}/')
    path = tmp_path / "base-bar.toml"
    path.write_text(plan, encoding="utf-8")
    profile = tmp_path / "profile.toml"
    profile.write_text(
        'name = "sizing"\nfeatures = []\nenforce = ["tool_sizing"]\n', encoding="utf-8"
    )
    out = tmp_path / "out.html"
    return main(["traveler", str(path), "--out", str(out), "--profile", str(profile)])


def test_cli_base_bar_passes(tmp_path):
    assert _base_bar(tmp_path, "", "") == 0
    assert (tmp_path / "out.html").exists()


@pytest.mark.parametrize(
    ("old", "new", "message"),
    [
        (
            # The v47 #9 bracket drill no longer fits the v48 #12 band.
            "diameter_mm = 4.8006",
            "diameter_mm = 4.9784",
            (
                "tool_sizing: setup 5 (Drill / tap / counterbore / slots), Op 100, "
                "sizing: tool 'bracket-drill' diameter 4.9784 mm is outside band "
                "4.8006–4.9022 mm"
            ),
        ),
        (
            "diameter_mm = 3.4544",
            "diameter_mm = 3.5814",
            (
                "tool_sizing: setup 5 (Drill / tap / counterbore / slots), Op 90, "
                "sizing: tool 'rail-drill' diameter 3.5814 mm does not match tap "
                "'tap' tap drill 3.4544 mm"
            ),
        ),
    ],
)
def test_cli_base_bar_refuses_wrong_drill(tmp_path, capsys, old, new, message):
    assert _base_bar(tmp_path, old, new) == 2
    assert message in capsys.readouterr().err
    assert not (tmp_path / "out.html").exists()
