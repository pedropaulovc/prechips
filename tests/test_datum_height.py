"""A height from a datum axis (issue #176) is a linear height, not a form."""

import json

import pytest
from test_angularity import angularity_bundle, inspection_finding
from test_cli import SYNTHETIC_KERNEL, copy_examples, run_cli

METHOD = '"Pin gauge in the bore; height gauge on the surface plate over pin top and edge"'
SETUP_DEBT = "datum height setup (height_from datum or inspection method) unresolved"


def datum_height(tmp_path, *, gauge="height_gauge", method=METHOD, height_from="axis"):
    bundle = angularity_bundle(
        tmp_path,
        requirement="height_above_pivot",
        band="[8.0, 8.5]",
        gauge=gauge,
        method=method,
        datums=None,
        resolution="0.01",
        span="[0.0, 300.0]",
    )
    if height_from is not None:
        bundle.features["features"]["cone"]["height_from"] = height_from
    return inspection_finding(bundle, "height_above_pivot")


@pytest.mark.parametrize("gauge", ["height_gauge", "cmm", "profile_gauge"])
def test_datum_height_gauges_read_the_band_with_a_declared_setup(tmp_path, gauge):
    row = datum_height(tmp_path, gauge=gauge)
    assert (row.status, row.numbers["height_from"]) == ("pass", "axis")
    assert row.numbers["inspection_method"] == METHOD.strip('"')


@pytest.mark.parametrize("gauge", ["radius_gauge", "angle_gauge", "caliper", "micrometer"])
def test_gauges_without_a_datum_height_reading_cannot_measure_it(tmp_path, gauge):
    row = datum_height(tmp_path, gauge=gauge)
    assert row.status == "error"
    assert "named gauge cannot measure this requirement" in row.sentence


@pytest.mark.parametrize(
    "setup",
    [
        {"method": None},
        {"method": '"unknown"'},
        {"height_from": None},
        {"height_from": "unknown"},
        {"height_from": "no_such_feature"},
    ],
)
def test_undeclared_datum_setup_is_debt_not_a_pass(tmp_path, setup):
    row = datum_height(tmp_path, **setup)
    assert row.status == "unknown"
    assert SETUP_DEBT in row.sentence


def test_plan_owned_datum_is_not_a_drawing_datum(tmp_path):
    bundle = angularity_bundle(
        tmp_path,
        requirement="height_above_pivot",
        band="[8.0, 8.5]",
        gauge="height_gauge",
        method=METHOD,
        datums=None,
        resolution="0.01",
        span="[0.0, 300.0]",
    )
    # A plan joint or process feature is operative, never an exported drawing datum.
    operative = {**bundle.feature_definitions, "prep_top": {"kind": "face", "requirements": []}}
    bundle.__dict__["feature_definitions"] = operative
    bundle.features["features"]["cone"]["height_from"] = "prep_top"
    row = inspection_finding(bundle, "height_above_pivot")
    assert row.status == "unknown"
    assert SETUP_DEBT in row.sentence


def test_radius_stays_a_form_a_height_gauge_cannot_read(tmp_path):
    bundle = angularity_bundle(
        tmp_path, requirement="radius", band="[799.49, 800.51]", gauge="height_gauge"
    )
    assert inspection_finding(bundle, "radius").status == "error"


# The trial's plan snippet from issue #176, renumbered after the rocker's last op.
ISSUE_SNIPPET = """
[[setups.ops]]
op = 96
do = "inspect"
feature = "top_edge"
checks = { height_above_pivot = "height-gauge", radius = "arm-outline-template", arc_len = "arm-outline-template" }
"""  # noqa: E501


@pytest.mark.parametrize(
    ("method", "status", "message"),
    [
        ("", "unknown", SETUP_DEBT),
        (
            "inspection_methods = { height_above_pivot = "
            '"Pin gauge in the pivot bore, arm on the surface plate; read pin top and edge" }\n',
            "pass",
            "gauge spans the band at sufficient resolution",
        ),
    ],
)
def test_issue_snippet_reads_height_with_the_height_gauge(tmp_path, method, status, message):
    examples = copy_examples(tmp_path)
    plan = examples / "rocker-arm" / "plan.toml"
    plan.write_text(plan.read_text(encoding="utf-8") + ISSUE_SNIPPET + method, encoding="utf-8")
    out = tmp_path / "out"
    result = run_cli("check", plan, "--out", out, setup=SYNTHETIC_KERNEL)
    assert result.returncode in {0, 2, 4}, result.stderr
    findings = json.loads((out / "report.json").read_bytes())["findings"]
    row = next(
        f
        for f in findings
        if (f["rule"], f["subject"]) == ("inspection", "top_edge:height_above_pivot")
    )
    assert (row["status"], row["numbers"]["gauge"]) == (status, "height-gauge")
    assert row["numbers"]["gauge_kind"] == "height_gauge"
    assert message in row["message"]
