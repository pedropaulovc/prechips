"""Filing to the line: a bench file takes at most the shop's max_filing_stock_mm.

A ``file_to_line`` op has no machine cutter. The kernel removes the stock within the
policy cap of its claimed faces, from any side, and never the finished part. Stock
deeper than the cap is more than a file takes: its claims stay unknown, so coverage and
finish coverage credit a filed face only once the kernel filed it. Kernel cases run
``src/prechips/kernel/freecad_job.py`` under ``freecadcmd`` and skip without it.
"""

import math

import pytest
from test_geometry_rules import bundle  # noqa: F401  (pytest fixture)
from test_kernel_geometry import Engine, _setup
from test_kernel_rough_stock import (  # noqa: F401  (solids is a pytest fixture)
    ISLAND_BLANK,
    ISLAND_BOUNDS,
    ISLAND_HOLD,
    _island_walls,
    _rough,
    solids,
)

from prechips.kernel import build_job
from prechips.rules import coverage, finish_coverage

CAP = 0.5
LEAVE = 0.2


def _file(subject, feature, cap=CAP):
    return {
        "subject": subject,
        "feature": feature,
        "do": "file_to_line",
        "finishing": True,
        "approach": "hand",
        "max_filing_stock_mm": cap,
    }


@pytest.fixture
def engine(tmp_path, freecad_kernel):
    return Engine(tmp_path, freecad_kernel)


def test_a_file_takes_the_leave_off_its_claims_only_up_to_the_policy_cap(engine, solids):  # noqa: F811
    step = solids["island"]
    walls = _island_walls(engine, step)
    features = {"all": sum(walls.values(), []), "corner": walls["west"] + walls["south"]}
    index = {face["ref"]: face["index"] for face in engine.faces(step)}

    def job(leave, cap):
        rough = _rough("S1:10", "all", 3.0, 25.0, 30.0, leave, stock_removal_bounds=ISLAND_BOUNDS)
        setups = [
            _setup([rough], ISLAND_HOLD, setup_id="S1"),
            _setup([_file("S2:10", "corner", cap)], ISLAND_HOLD, setup_id="S2"),
            _setup([], ISLAND_HOLD, setup_id="S3"),
        ]
        return engine.job(step, features, setups, stock=ISLAND_BLANK)

    filed, deep, uncapped, unfiled = engine.run(
        {"jobs": [job(LEAVE, CAP), job(1.0, CAP), job(LEAVE, "unknown"), job(LEAVE, 0.0)]}
    )["results"]

    op = filed["ops"]["S2:10"]
    assert op["approach"] == "hand"
    assert op["claimed_indices"] == sorted(index[ref] for ref in features["corner"]), op
    second, third = filed["setups"]["S2"], filed["setups"]["S3"]
    assert "stock_reason" not in third, third.get("stock_reason")
    # The rough leave on the two claimed walls and their convex corner is filed away, and
    # each stroke runs on past its wall's free end, taking the leave's rounded nib in the
    # corner beyond it. The unclaimed walls keep their leave, the far corner keeps its, and
    # no finished material goes.
    taken = 20 * (LEAVE * (60 + 40) + 3 * math.pi * LEAVE**2 / 4)
    assert second["stock_volume_mm3"] - third["stock_volume_mm3"] == pytest.approx(taken, abs=0.01)
    # No cutter is drawn for a file.
    assert not any("cutter" in debt for debt in second["render_scene"]["render_debts"])

    # A 1 mm leave is twice what a file takes, and a shop that allows no filing lets a
    # file take none of a 0.2 mm leave: the claims stay unknown and the stock after the
    # file is never credited.
    for result in (deep, unfiled):
        op = result["ops"]["S2:10"]
        assert op["claimed_indices"] == "unknown"
        assert "stock deeper than its" in op["reasons"]["claimed_indices"], op
        reason = result["setups"]["S3"]["stock_reason"]
        assert "S2:10" in reason and "max_filing_stock_mm" in reason, reason

    op = uncapped["ops"]["S2:10"]
    assert op["claimed_indices"] == "unknown"
    assert "max_filing_stock_mm is unknown" in op["reasons"]["claimed_indices"], op
    assert "max_filing_stock_mm is unknown" in uncapped["setups"]["S3"]["stock_reason"]


def test_walls_filed_in_turn_leave_no_crumb_in_their_corner(engine, solids):  # noqa: F811
    # Filing the west wall and then the south wall leaves what filing both at once does:
    # a stroke runs on past the corner, so the leave's rounded nib there is never
    # stranded as a loose crumb that splits the stock.
    step = solids["island"]
    walls = _island_walls(engine, step)
    features = {
        "all": sum(walls.values(), []),
        "west": walls["west"],
        "south": walls["south"],
        "corner": walls["west"] + walls["south"],
    }

    def job(*files):
        rough = _rough("S1:10", "all", 3.0, 25.0, 30.0, LEAVE, stock_removal_bounds=ISLAND_BOUNDS)
        setups = [
            _setup([rough], ISLAND_HOLD, setup_id="S1"),
            _setup(list(files), ISLAND_HOLD, setup_id="S2"),
            _setup([], ISLAND_HOLD, setup_id="S3"),
        ]
        return engine.job(step, features, setups, stock=ISLAND_BLANK)

    in_turn, at_once = engine.run(
        {
            "jobs": [
                job(_file("S2:10", "west"), _file("S2:20", "south")),
                job(_file("S2:10", "corner")),
            ]
        }
    )["results"]

    for subject in ("S2:10", "S2:20"):
        assert isinstance(in_turn["ops"][subject]["claimed_indices"], list), in_turn["ops"][subject]
    third = in_turn["setups"]["S3"]
    assert "stock_reason" not in third, third.get("stock_reason")
    expected = at_once["setups"]["S3"]["stock_volume_mm3"]
    assert third["stock_volume_mm3"] == pytest.approx(expected, abs=0.01)


def _filed(data, claim):
    """S1:10 files the pocket's face #1; the kernel reports its hand facts ``claim``."""
    data.plan["setups"][0]["ops"] = [{"op": 10, "do": "file_to_line", "feature": "pocket"}]
    data.kernel["ops"]["S1:10"] = claim


@pytest.mark.parametrize(
    "claim,status",
    [
        ({"approach": "hand", "claimed_indices": [1], "claim_errors": []}, "pass"),
        # Stock deeper than the cap: the kernel never filed it.
        (
            {
                "approach": "hand",
                "claimed_indices": "unknown",
                "claim_errors": [],
                "reasons": {"claimed_indices": "stock deeper than max_filing_stock_mm"},
            },
            "unknown",
        ),
        # Facts not from the hand model (an axial cutter's claim) never credit a file.
        ({"claimed_indices": [1], "claim_errors": []}, "unknown"),
    ],
    ids=["filed", "too-deep", "not-hand-facts"],
)
def test_a_filed_face_is_covered_and_finished_only_once_the_kernel_filed_it(
    bundle,  # noqa: F811
    claim,
    status,
):
    _filed(bundle, claim)
    for rule in (coverage, finish_coverage):
        [row] = rule.evaluate(bundle)
        assert row.status == status, (rule.__name__, row.sentence)


CITED = {"max_filing_stock_mm": "example filing cap"}


@pytest.mark.parametrize(
    "numbers,verify,cite,cap",
    [
        ({"max_filing_stock_mm": CAP}, {"max_filing_stock_mm": False}, CITED, CAP),
        ({"max_filing_stock_mm": CAP}, {"max_filing_stock_mm": True}, CITED, "unknown"),
        ({"max_filing_stock_mm": CAP}, {"max_filing_stock_mm": False}, {}, "unknown"),
        ({"max_filing_stock_mm": 0.0}, {}, CITED, 0.0),
        ({"max_filing_stock_mm": -0.1}, {}, CITED, "unknown"),
        ({}, {}, {}, "unknown"),
    ],
    ids=["verified", "to-verify", "uncited", "zero", "negative", "absent"],
)
def test_the_kernel_bounds_a_file_by_the_verified_policy_cap(
    bundle,  # noqa: F811
    numbers,
    verify,
    cite,
    cap,
):
    _filed(bundle, {})
    bundle.policy["numbers"] = numbers
    bundle.policy["numbers_verify"] = verify
    bundle.policy["numbers_cite"] = cite
    [setup] = build_job(bundle)["setups"]
    [op] = setup["ops"]
    assert op["approach"] == "hand" and op["finishing"] is True
    assert op["max_filing_stock_mm"] == cap
    assert "radius_mm" not in op and "reason" not in op
