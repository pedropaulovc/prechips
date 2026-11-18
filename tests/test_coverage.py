import pytest

from prechips import coverage
from prechips.cad import CadData
from prechips.checks import CheckError
from prechips.traveler import LoadedPlan

MANIFEST = """\
[features.bore]
requirements = ["dia", "station", "thread", "thru"]
dia = [9.5, 9.6]
station = [-7.3, -7.1]
thread = "5/16-18 UNC-2B"
thru = true

[features.flat]
requirements = ["clock_deg"]
clock_deg = [119.0, 121.0]
"""


def plan(tmp_path, gauge_checks, process_held=None, *, manifest=MANIFEST):
    cad = None
    if manifest is not None:
        source = tmp_path / "part.toml"
        source.write_text(manifest, encoding="utf-8")
        cad = CadData({}, None, source)
    data = {"setups": [{"title": "Mill", "operations": [{}]}]}
    data["setups"][0]["operations"][0]["gauge_checks"] = gauge_checks
    if process_held is not None:
        data["process_held"] = process_held
    return LoadedPlan(data, tmp_path / "plan.toml", cad, {}, None, {})


DIA = {"gauge": "pins", "band_mm": [9.5, 9.6], "requirements": ["bore.dia"]}
# A gauge reads a distance: the station below zero is compared by magnitude.
STATION = {"gauge": "dro", "band_mm": [7.1, 7.3], "requirements": ["bore.station"]}
HELD = [{"requirements": ["flat.clock_deg"], "reason": "Indexed."}]


def test_every_band_gauged_or_held_passes(tmp_path):
    coverage.check(
        plan(tmp_path, [DIA, STATION, {"gauge": "x", "band_mm": [0, 1]}], HELD)
    )


def test_unbound_band_refuses_naming_it(tmp_path):
    with pytest.raises(
        CheckError, match=r"process-held: bore\.station, flat\.clock_deg;"
    ):
        coverage.check(plan(tmp_path, [DIA]))


@pytest.mark.parametrize(
    ("gauge_checks", "held", "message"),
    [
        (
            [{**DIA, "requirements": ["bore.thread"]}],
            HELD,
            "not a CAD requirement band",
        ),
        ([{**DIA, "band_mm": [9.5, 9.7]}, STATION], HELD, "outside bore.dia 9.5–9.6"),
        (
            [DIA, STATION, {**DIA, "requirements": ["flat.clock_deg"]}],
            None,
            "in degrees",
        ),
        (
            [DIA, STATION],
            HELD + [{"requirements": ["bore.dia"], "reason": "Drill."}],
            "also gauged",
        ),
        ([DIA, STATION], HELD + HELD, "already process-held"),
        (
            [DIA, STATION],
            [{"requirements": ["flat.clock_deg"]}],
            "requirements and reason",
        ),
    ],
)
def test_bad_binding_refuses(tmp_path, gauge_checks, held, message):
    with pytest.raises(CheckError, match=message):
        coverage.check(plan(tmp_path, gauge_checks, held))


def test_plan_without_cad_names_no_requirement(tmp_path):
    coverage.check(plan(tmp_path, "other", manifest=None))
    with pytest.raises(CheckError, match="not a CAD requirement band"):
        coverage.check(plan(tmp_path, [DIA], manifest=None))
