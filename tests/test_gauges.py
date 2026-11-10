import pytest

from prechips import gauges
from prechips.checks import CheckError
from prechips.cli import main
from prechips.traveler import load_plan

PLAN = """\
shop = "shop.toml"
title = "Test part"
part = "T1"
revision = "A"
material = "Steel"
stock = "Authored blank"

[[tools]]
id = "bit"
description = "HSS bit"

[[setups]]
title = "Turn"
machine = "Manual lathe"
{setup}

[[setups.operations]]
instruction = "Rough."

[[setups.operations]]
instruction = "Finish."
{operation}
"""

SHOP = """\
[gauges.micrometers]
range_mm = [0.0, 25.0]
resolution_mm = 0.002
"""

INSPECTED = (
    'inspection = "Ø6.33–6.35."\n'
    'gauge_checks = [{ gauge = "micrometers", band_mm = [6.33, 6.35] }]'
)


def prepare(tmp_path, *, setup="", operation=INSPECTED, shop=SHOP):
    plan = tmp_path / "plan.toml"
    plan.write_text(PLAN.format(setup=setup, operation=operation), encoding="utf-8")
    (tmp_path / "shop.toml").write_text(shop, encoding="utf-8")
    profile = tmp_path / "gauges.toml"
    profile.write_text(
        'name = "Gauges"\nfeatures = []\nenforce = ["gauge_capability"]\n'
    )
    return plan, profile


def run(tmp_path, **kwargs):
    plan, profile = prepare(tmp_path, **kwargs)
    out = tmp_path / "out.html"
    args = ["traveler", str(plan), "--out", str(out), "--profile", str(profile)]
    return main(args), out


def refusal(tmp_path, **kwargs) -> str:
    plan, _ = prepare(tmp_path, **kwargs)
    with pytest.raises(CheckError) as error:
        gauges.check(load_plan(plan))
    return str(error.value)


def test_cli_passes_silently_and_refuses_before_output(tmp_path, capsys):
    status, out = run(tmp_path)
    assert status == 0
    assert "gauge" not in out.read_text(encoding="utf-8").lower()
    out.unlink()
    status, out = run(tmp_path, shop=SHOP.replace("25.0", "6.34"))
    assert status == 2
    assert not out.exists()
    assert "gauge_capability: setup 1 (Turn), Op 20" in capsys.readouterr().err


@pytest.mark.parametrize(
    ("band", "message"),
    [
        ("[0.0, 25.0]", None),
        ("[-0.001, 6.35]", "outside shop.gauges.micrometers range 0–25 mm"),
        ("[6.33, 25.001]", "outside shop.gauges.micrometers range 0–25 mm"),
        ("[6.33, 6.332]", None),
        ("[0.3, 0.302]", None),
        ("[6.33, 6.3319]", "resolution 0.002 mm exceeds band 6.33–6.3319 mm"),
        ("[6.33, 6.33]", "resolution 0.002 mm exceeds"),
    ],
)
def test_range_edges_and_resolution_rule(tmp_path, band, message):
    operation = (
        'inspection = "Size."\n'
        f'gauge_checks = [{{ gauge = "micrometers", band_mm = {band} }}]'
    )
    plan, _ = prepare(tmp_path, operation=operation)
    if message is None:
        gauges.check(load_plan(plan))
        return
    with pytest.raises(CheckError, match=message):
        gauges.check(load_plan(plan))


@pytest.mark.parametrize(
    ("setup", "operation", "message"),
    [
        ("", 'inspection = "Size."', "setup 1 (Turn), Op 20: inspection has no"),
        ("", 'gauge_checks = "other"', "Op 20: gauge_checks without inspection"),
        ('inspection = ["Runout."]', "", "setup 1 (Turn): inspection has no"),
        ('gauge_checks = "other"', "", "setup 1 (Turn): gauge_checks without"),
        ("", 'inspection = "Size."\ngauge_checks = []', 'expected "other"'),
        (
            "",
            'inspection = "Size."\ngauge_checks = [{ gauge = "calipers", band_mm = [1, 2] }]',
            "unknown shop gauges reference 'calipers'",
        ),
    ],
)
def test_strict_coverage(tmp_path, setup, operation, message):
    assert message in refusal(tmp_path, setup=setup, operation=operation)


def test_other_and_setup_declarations_pass(tmp_path):
    plan, _ = prepare(
        tmp_path,
        setup='inspection = ["Finish visual."]\ngauge_checks = "other"',
        operation='inspection = "Ra ≤1.6 µm."\ngauge_checks = "other"',
    )
    gauges.check(load_plan(plan))
