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
    _op,
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


def _box(name, at, size):
    return {"name": name, "shape": "box", "at_mm": at, "size_mm": size}


def test_a_guided_file_stops_on_its_buttons_and_dimensions_the_holding_it_must_clear(
    engine,
    solids,  # noqa: F811
):
    # The island stands on a plate 5 mm in from its west wall. A guide kit presses its
    # top: its button's rim is the west wall line, its stud stands 15 mm in. Filing the
    # west wall's leave reaches the button: guided, that is where the file stops, and the
    # holding the file must clear is the plate; unguided, it is a zero clearance. Only a
    # button of the kit's declared OD whose rim lies on the filed face is a stop: one whose
    # rim stands over the unfiled wall (X 4.8), a kit solid touching that wall, or a square
    # block is holding to clear. A setup that also machines has a CLEARANCE row for the file
    # and one for the cutter, and its picture dimensions the least of them.
    step = solids["island"]
    walls = _island_walls(engine, step)
    features = {"all": sum(walls.values(), []), "west": walls["west"], "east": walls["east"]}
    origin = {"origin_mm": [0.0, 0.0, 0.0], "x": [1.0, 0.0, 0.0], "z": [0.0, 0.0, 1.0]}
    disc = {
        "name": "clamp 1 kit:button",
        "shape": "cylinder",
        "at_mm": [10.0, 25.0, 20.0],
        "axis": [0.0, 0.0, 1.0],
        "dia_mm": 10.0,
        "length_mm": 4.0,
    }
    # Its X 4.8 face touches the wall before filing, not the filed X 5 face.
    tangent = _box("clamp 1 kit:tab", [4.7, 30.0, 0.0], [0.1, 4.0, 24.0])

    def job(guided, button, *extra, machined=False):
        kit = {
            "name": "clamp 1 kit",
            "pose": origin,
            "solids": [
                button,
                _box("clamp 1 kit:stud", [20.0, 20.0, 20.0], [4.0, 4.0, 20.0]),
                *extra,
            ],
        }
        hold = {
            "kind": "solids",
            "fixture_kind": "angle_plate",
            "pose": origin,
            "solids": [_box("plate:top", [10.0, 10.0, -10.0], [50.0, 30.0, 10.0])],
            "clamps": [kit],
            "debts": [],
            "gaps": [],
        }
        rough = _rough("S1:10", "all", 3.0, 25.0, 30.0, LEAVE, stock_removal_bounds=ISLAND_BOUNDS)
        filed = _file("S2:10", "west")
        if guided:
            filed["guide_owner"] = "clamp 1 kit"
            filed["guide_rim_dia_mm"] = [9.99, 10.01]
        ops = [filed]
        if machined:
            finish = {**_op("S2:20", "east", 3.0, 25.0, 30.0), "do": "finish_profile"}
            ops.append({**finish, "rough_allowance_mm": LEAVE})
        setups = [
            _setup([rough], ISLAND_HOLD, setup_id="S1"),
            _setup(ops, hold, setup_id="S2"),
        ]
        return engine.job(step, features, setups, stock=ISLAND_BLANK)

    block = _box("clamp 1 kit:button", [5.0, 20.0, 20.0], [10.0, 10.0, 4.0])
    over = {**disc, "at_mm": [9.8, 25.0, 20.0]}
    jobs = [job(True, disc), job(False, disc), job(True, disc, tangent), job(True, block)]
    jobs += [job(False, disc, machined=True), job(True, over)]
    guided, unguided, beside, square, mixed, overhung = (
        result["setups"]["S2"]["render_scene"] for result in engine.run({"jobs": jobs})["results"]
    )

    assert guided["guide_stops"] == ["clamp 1 kit:button"]
    assert guided["closest_cut"]["tag"] == "plate:top"
    assert guided["closest_cut"]["mm"] == pytest.approx(5.0, abs=1e-3)
    point, direction = guided["guide_axis_mm"]
    assert point[:2] == pytest.approx([10.0, 25.0], abs=1e-6)
    assert direction == pytest.approx([0.0, 0.0, 1.0], abs=1e-9)
    assert unguided["guide_stops"] == []
    assert unguided["closest_cut"]["tag"] == "clamp 1 kit:button"
    assert unguided["closest_cut"]["mm"] == pytest.approx(0.0, abs=1e-6)
    assert unguided["guide_axis_mm"] is None
    # The picture's dimension is a CLEARANCE table row: the file's own.
    for scene, tag, mm in ((guided, "plate:top", 5.0), (unguided, "clamp 1 kit:button", 0.0)):
        [row] = scene["cut_clearances"]
        assert (row["op"], row["tag"], row["mm"]) == ("10", tag, pytest.approx(mm, abs=1e-3))
    assert beside["guide_stops"] == ["clamp 1 kit:button"]
    assert beside["closest_cut"]["tag"] == "clamp 1 kit:tab"
    assert beside["closest_cut"]["mm"] == pytest.approx(0.0, abs=1e-6)
    assert square["guide_stops"] == []
    assert square["closest_cut"]["tag"] == "clamp 1 kit:button"
    assert square["closest_cut"]["mm"] == pytest.approx(0.0, abs=1e-6)
    assert square["guide_axis_mm"] is None
    # A setup that files and machines has a row for each. The unguided file reaches the
    # button (0 mm); the east finish is told no commanded path, so its whole tool's row is
    # unknown, and the picture dimensions nothing the table cannot print.
    filed, finished = mixed["cut_clearances"]
    assert (filed["op"], filed["tag"]) == ("10", "clamp 1 kit:button")
    assert filed["mm"] == pytest.approx(0.0, abs=1e-6)
    assert finished == {"op": "20", "mm": "unknown", "tag": "unknown"}
    assert mixed["closest_cut"] is None
    assert overhung["guide_stops"] == []
    assert overhung["closest_cut"]["tag"] == "clamp 1 kit:button"
    assert overhung["closest_cut"]["mm"] == pytest.approx(0.0, abs=1e-6)


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
