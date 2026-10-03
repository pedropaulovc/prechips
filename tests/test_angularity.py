"""Drawing angularity requires datum inspection and a viable datum pickup."""

import pytest

from prechips.inputs import load_bundle
from prechips.rules import datum_consistency, inspection

METHOD = '"Probe the cone relative to finished datums A and B"'


def angularity_bundle(
    tmp_path,
    *,
    band="[0.0, 0.10]",
    datums='["A", "B"]',
    gauge="cmm",
    check=True,
    method=METHOD,
    budget="0.10",
    transfer="",
    same_setup=False,
    requirement="angularity_dia",
    resolution="0.001",
    span="[0.0, 100.0]",
):
    checks = f'checks = {{ {requirement} = "gauge" }}\n' if check else ""
    methods = f"inspection_methods = {{ {requirement} = {method} }}\n" if method is not None else ""
    second_setup = (
        '\n[[setups]]\nid = "S2"\nmachine = "mill"\n' + transfer if not same_setup else ""
    )
    documents = {
        "plan.toml": (
            'part = "angularity-control"\nfeatures = "features.toml"\n'
            '[paths]\ninventory = "inventory.toml"\npolicy = "policy.toml"\n'
            'cutting_data = "cutting.toml"\n'
            '[[setups]]\nid = "S1"\nmachine = "mill"\n'
            '[[setups.ops]]\nop = 10\ndo = "face"\nfeature = "base"\n'
            '[[setups.ops]]\nop = 20\ndo = "bore"\nfeature = "axis"\n'
            + second_setup
            + '[[setups.ops]]\nop = 30\ndo = "turn"\nfeature = "cone"\n'
            + checks
            + methods
        ),
        "features.toml": (
            'part = "angularity-control"\nunits = "mm"\nframes = "unknown"\n'
            '[datums.A]\nfeature = "base"\n[datums.B]\nfeature = "axis"\n'
            '[features.base]\nkind = "face"\nrequirements = []\n'
            '[features.axis]\nkind = "hole"\nrequirements = []\n'
            '[features.cone]\nkind = "cone"\n'
            + f'requirements = ["{requirement}"]\n{requirement} = {band}\n'
            + (f"angularity_datums = {datums}\n" if datums is not None else "")
        ),
        "inventory.toml": (
            '[machines.mill]\nkind = "mill"\n[gauges.gauge]\n'
            + f'kind = "{gauge}"\nrange_mm = {span}\n'
            + f"resolution_mm = {resolution}\nverify = false\n"
        ),
        "policy.toml": f"[numbers]\nrefixture_budget_mm = {budget}\n",
        "cutting.toml": "revision = 1\n",
    }
    for name, text in documents.items():
        (tmp_path / name).write_text(text, encoding="utf-8")
    return load_bundle(tmp_path / "plan.toml")


def inspection_finding(bundle, requirement="angularity_dia"):
    return next(row for row in inspection.evaluate(bundle) if row.subject == f"cone:{requirement}")


def datum_finding(bundle):
    return next(row for row in datum_consistency.evaluate(bundle) if row.subject == "cone")


def test_missing_angularity_check_is_error(tmp_path):
    row = inspection_finding(angularity_bundle(tmp_path, check=False))
    assert row.status == "error"
    assert "no requirement-keyed inspection check" in row.sentence


def test_caliper_cannot_certify_angularity(tmp_path):
    row = inspection_finding(angularity_bundle(tmp_path, gauge="caliper"))
    assert row.status == "error"
    assert "cannot measure this requirement" in row.sentence


@pytest.mark.parametrize("gauge", ["cmm", "dial_indicator", "dial_test_indicator", "height_gauge"])
def test_known_datum_method_and_capable_gauge_cover_angularity(tmp_path, gauge):
    row = inspection_finding(angularity_bundle(tmp_path, gauge=gauge))
    assert row.status == "pass"
    assert row.numbers["band_mm"] == pytest.approx(0.10)


@pytest.mark.parametrize(
    "changes",
    [
        {"band": '"unknown"'},
        {"band": '[0.0, "unknown"]'},
        {"method": None},
        {"method": '"unknown"'},
        {"method": '""'},
        {"datums": None},
        {"datums": "[]"},
        {"datums": '["A", "unknown"]'},
        {"resolution": '"unknown"'},
    ],
)
def test_unresolved_angularity_evidence_does_not_pass(tmp_path, changes):
    assert inspection_finding(angularity_bundle(tmp_path, **changes)).status == "unknown"


@pytest.mark.parametrize("requirement", ["position_dia", "coaxiality_dia"])
@pytest.mark.parametrize("method", [None, '"unknown"'])
def test_geometric_bands_cannot_bypass_method_requirement(tmp_path, requirement, method):
    row = inspection_finding(
        angularity_bundle(tmp_path, requirement=requirement, method=method), requirement
    )
    assert row.status == "unknown"


@pytest.mark.parametrize(
    ("band", "budget", "status"),
    [
        ("[0.0, 0.10]", "0.10", "pass"),
        ("[0.0, 0.10]", "0.101", "error"),
        ("[0.02, 0.10]", "0.09", "error"),
        ("[0.0, 0.10]", '"unknown"', "unknown"),
        ('[0.0, "unknown"]', "0.10", "unknown"),
        ("0.10", "0.10", "pass"),
    ],
)
def test_angularity_refixture_uses_band_width(tmp_path, band, budget, status):
    row = datum_finding(angularity_bundle(tmp_path, band=band, budget=budget))
    assert row.status == status
    assert {item["datum"] for item in row.numbers["relationships"]} == {"A", "B"}
    assert all(item["status"] == status for item in row.numbers["relationships"])


@pytest.mark.parametrize(
    ("selected", "status"),
    [('["A", "B"]', "pass"), ('["A"]', "error"), ('["base", "axis"]', "pass")],
)
def test_transfer_must_pick_up_each_angularity_datum(tmp_path, selected, status):
    transfer = f'zero = {{ transfer = {{ from = "S1", indicate = {selected} }} }}\n'
    row = datum_finding(angularity_bundle(tmp_path, budget="0.20", transfer=transfer))
    assert row.status == status


def test_shared_setup_needs_no_refixture_budget(tmp_path):
    row = datum_finding(angularity_bundle(tmp_path, same_setup=True, budget='"unknown"'))
    assert row.status == "pass"
    assert all(item["same_setup"] for item in row.numbers["relationships"])


@pytest.mark.parametrize("datums", [None, "[]", '["A", "unknown"]', '["missing"]'])
def test_missing_angularity_datum_geometry_is_unresolved(tmp_path, datums):
    assert datum_finding(angularity_bundle(tmp_path, datums=datums)).status == "unknown"
