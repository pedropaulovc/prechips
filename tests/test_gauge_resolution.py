"""A gauge or DRO resolution that is not positive reads nothing (#315): the inventory
refuses it at load, and a rule that meets one anyway never reads it as sufficient."""

import pytest
from test_angularity import angularity_bundle, inspection_finding
from test_prepared_blank import blank, bracket, set_key
from test_validate_examples import VALIDATOR

from prechips.inputs import BadInput, load_bundle
from prechips.rules import prepared_blank

MEASURED = (
    'measured = { status = "measured", by = "Inspector", date = "2026-10-05", '
    'instrument = "Resolution standard" }'
)


@pytest.mark.parametrize(
    "resolution",
    [
        "0.0",
        "-0.01",
        f"{{ value = 0.0, {MEASURED} }}",
        f"{{ value = -0.001, {MEASURED} }}",
    ],
)
@pytest.mark.parametrize("category", ["gauges", "machines"])
def test_a_resolution_that_is_not_positive_is_refused_at_load(tmp_path, resolution, category):
    angularity_bundle(tmp_path)
    inventory = tmp_path / "inventory.toml"
    text = inventory.read_text(encoding="utf-8")
    item = "[gauges.gauge]\n" if category == "gauges" else '[machines.mill]\nkind = "mill"\n'
    text = text.replace("resolution_mm = 0.001\n", "")
    inventory.write_text(
        text.replace(item, f"{item}resolution_mm = {resolution}\n"), encoding="utf-8"
    )
    with pytest.raises(BadInput, match="resolution must be a positive length"):
        load_bundle(tmp_path / "plan.toml")


@pytest.mark.parametrize("resolution", ['"unknown"', '{ value = "unknown" }', "0.0005"])
def test_an_unknown_or_positive_resolution_still_loads(tmp_path, resolution):
    row = inspection_finding(angularity_bundle(tmp_path, resolution=resolution))
    assert row.status in {"pass", "unknown"}


def _zero(bundle, value):
    bundle.inventory["gauges"]["gauge"]["resolution_mm"] = value
    return bundle


@pytest.mark.parametrize("value", [0.0, -0.01])
def test_the_issue_probe_a_zero_resolution_never_passes_a_band(tmp_path, value):
    # #315: R5 ±0.1 read by a gauge whose resolution is 0 passed as "sufficient resolution".
    bundle = angularity_bundle(
        tmp_path,
        requirement="radius",
        band="[4.9, 5.1]",
        gauge="radius_gauge",
        method=None,
        datums=None,
    )
    assert inspection_finding(bundle, "radius").status == "pass"
    row = inspection_finding(_zero(bundle, value), "radius")
    assert row.status == "unknown"
    assert row.sentence == "cone radius: gauge range or resolution unresolved."


@pytest.mark.parametrize("band", ["0.10", "[0.0, 0.10]"])
@pytest.mark.parametrize("value", [0.0, -0.01])
def test_a_zero_resolution_never_covers_a_geometric_zone(tmp_path, band, value):
    bundle = angularity_bundle(tmp_path, band=band)
    assert inspection_finding(bundle).status == "pass"
    assert inspection_finding(_zero(bundle, value)).status == "unknown"


@pytest.mark.parametrize("value", [0.0, -0.001])
def test_a_zero_resolution_never_reads_a_form_limit(tmp_path, value):
    plan = bracket(tmp_path)
    inventory = plan.parents[1] / "inventory" / "pedro-shop.toml"
    set_key(inventory, "gauges.dti", "resolution_in", "0.0001")
    assert blank(plan).status == "pass"
    bundle = load_bundle(plan)
    bundle.inventory["gauges"]["dti"]["resolution_in"] = value
    (row,) = prepared_blank.evaluate(bundle)
    checks = row.numbers["checks"]
    assert [checks[key]["status"] for key in ("flat", "square", "parallel")] == ["unknown"] * 3
    assert {checks[key]["resolution_mm"] for key in ("flat", "square", "parallel")} == {"unknown"}


@pytest.mark.parametrize("value", [0.0, -0.001])
def test_the_gauge_oracle_never_reads_a_zero_resolution(value):
    gauge = {"kind": "dial_indicator", "resolution_mm": value}
    assert VALIDATOR["gauge_resolution"](gauge) == "unknown"
    assert VALIDATOR["blank_form_check"](gauge, "sweep the face", 0.01, {}) == "unknown"
