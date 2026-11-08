"""CAD dimension baselines are not manufactured-size acceptance targets.

Source: harmonic-analyzer cad/scripts/dt_cone_pivot_post_spec.py declares
BORE_DIA = 12.2682 and JOURNAL_BORE_BAND = (0.0254, 0.0127), intentionally
.483 +.0010/+.0005 in. draw_dt_cone_pivot_post.py exports that model nominal
and the separate limits. The opposite unilateral direction is equally valid.
"""

from copy import deepcopy
from math import inf, nextafter

import pytest
from test_angularity import angularity_bundle, inspection_finding

from prechips.rules import inspection

NOMINAL = 12.2682
POSITIVE_BAND = [12.2809, 12.2936]
NEGATIVE_BAND = [12.2428, 12.2555]


def diameter_bundle(tmp_path, band=POSITIVE_BAND, *, field="nominal_dia", check=True):
    data = angularity_bundle(
        tmp_path,
        requirement="dia",
        band=repr(band),
        gauge="cmm",
        check=check,
    )
    data.features["features"]["cone"].update(kind="hole", **{field: NOMINAL})
    return data


@pytest.mark.parametrize("band", [POSITIVE_BAND, NEGATIVE_BAND])
@pytest.mark.parametrize("field", ["nominal_dia", "dia_nominal"])
@pytest.mark.parametrize("gauge_state", ["verified", "unknown", "unverified", "missing"])
def test_unilateral_nominal_does_not_replace_acceptance_or_gauge_evidence(
    tmp_path, band, field, gauge_state
):
    data = diameter_bundle(tmp_path, band, field=field)
    original = deepcopy(data.features)
    gauge = data.inventory["gauges"]["gauge"]
    if gauge_state == "unknown":
        gauge["kind"] = "unknown"
    elif gauge_state == "unverified":
        gauge["verify"] = True
    elif gauge_state == "missing":
        data.inventory["gauges"].pop("gauge")

    row = inspection_finding(data, "dia")

    assert row.status == ("pass" if gauge_state == "verified" else "unknown")
    assert row.numbers["limits"] == band
    assert data.features == original


def test_unilateral_nominal_does_not_clear_missing_inspection(tmp_path):
    row = inspection_finding(diameter_bundle(tmp_path, check=False), "dia")
    assert row.status == "error"
    assert "no requirement-keyed inspection check" in row.sentence


def test_unilateral_nominal_does_not_resolve_unknown_applicability(tmp_path):
    data = diameter_bundle(tmp_path)
    data.features["features"]["cone"]["kind"] = "unknown"
    assert inspection_finding(data, "dia").status == "unknown"


def test_reversed_acceptance_band_is_still_an_error(tmp_path):
    data = diameter_bundle(tmp_path, list(reversed(POSITIVE_BAND)))
    assert inspection_finding(data, "dia").status == "error"


@pytest.mark.parametrize(
    ("hold", "status"),
    [
        (POSITIVE_BAND, "pass"),
        ([nextafter(POSITIVE_BAND[0], -inf), POSITIVE_BAND[1]], "error"),
        ([POSITIVE_BAND[0], nextafter(POSITIVE_BAND[1], inf)], "error"),
        ([NOMINAL, POSITIVE_BAND[0]], "error"),
    ],
)
def test_process_hold_must_remain_inside_actual_limits(tmp_path, hold, status):
    data = diameter_bundle(tmp_path)
    setup = data.plan["setups"][-1]
    op = setup["ops"][-1]
    op["process_holds"] = [
        {
            "feature": "cone",
            "requirement": "dia",
            "band": hold,
            "gauge": "gauge",
            "reason": "Authored process acceptance, not the model baseline",
        }
    ]

    row = inspection.process_holds(data, setup, op)

    assert row.status == status
    assert data.features["features"]["cone"]["dia"] == POSITIVE_BAND


@pytest.mark.parametrize(
    ("go", "no_go", "status"),
    [
        (*POSITIVE_BAND, "pass"),
        (nextafter(POSITIVE_BAND[0], -inf), POSITIVE_BAND[1], "error"),
        (POSITIVE_BAND[0], nextafter(POSITIVE_BAND[1], inf), "error"),
        (NOMINAL, POSITIVE_BAND[1], "error"),
    ],
)
def test_limit_gauges_cannot_accept_nominal_or_round_outward(tmp_path, go, no_go, status):
    data = diameter_bundle(tmp_path)
    op = data.plan["setups"][-1]["ops"][-1]
    op["go_no_go"] = {"dia": {"go": go, "no_go": no_go}}
    data.inventory["gauges"]["gauge"].update(kind="pin_gauge_set", sizes_mm=[go, no_go])

    row = inspection_finding(data, "dia")

    assert row.status == status
    assert row.numbers["accept_band"] == POSITIVE_BAND
