"""A hand-saw cut on the bench: straight, or following a scribed line (#249)."""

import re
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

import pytest
from pydantic import ValidationError
from test_bench_routed_screens import SCREENS, bench_bundle

from prechips.inputs import Bundle
from prechips.model import Plan
from prechips.rules import saw_cut, speeds_feeds, tool_resolves
from prechips.rules.manual_arc import _rough
from prechips.sheet import _Traveler

PLANE = {"axis": "y", "value": 87.75, "keep": "below"}
BOUNDS = {"x": [-1.0, 300.0], "y": [13.5, 20.0], "z": [-1.0, 10.0]}


def plan(*saw_ops, scribe=True):
    """A plan whose S1 scribes the arc line at op 10, then S2 runs ``saw_ops``."""
    layout = [{"op": 10, "do": "scribe", "feature": "arc", "layout": "trammel"}] if scribe else []
    return {
        "part": "rocker",
        "features": "features.toml",
        "setups": [
            {"id": "S1", "machine": "bench", "stock_in": "stock", "ops": layout},
            {"id": "S2", "machine": "bench", "stock_in": "S1", "ops": list(saw_ops)},
        ],
    }


def saw(**fields):
    return {"op": 20, "do": "saw_cut", "tool": "hacksaw", **fields}


def scribed(**fields):
    return saw(
        **{"follows": "S1:10", "allowance_mm": 0.5, "stock_removal_bounds": BOUNDS, **fields}
    )


# ---------------------------------------------------------------- schema: exactly one shape


@pytest.mark.parametrize(
    "op",
    [
        saw(cut_plane=PLANE),
        saw(cut_plane="unknown"),
        scribed(),
        saw(follows="S1:10"),
        saw(follows="S1:10", allowance_mm="unknown", stock_removal_bounds="unknown"),
        {**scribed(), "do": "cut_off"},
    ],
    ids=["plane", "plane-unknown", "scribed", "scribed-debt", "scribed-unknowns", "cut-off"],
)
def test_a_saw_declares_a_plane_or_the_scribed_line_it_follows(op):
    Plan.model_validate(plan(op))


@pytest.mark.parametrize(
    "op, scribe, words",
    [
        (saw(), True, "exactly one of cut_plane"),
        (scribed(cut_plane=PLANE), True, "exactly one of cut_plane"),
        (saw(cut_plane=PLANE, allowance_mm=0.5), True, "straight saw cut"),
        (saw(cut_plane=PLANE, stock_removal_bounds=BOUNDS), True, "straight saw cut"),
        (scribed(), False, "names no earlier scribe op"),
        (scribed(follows="S2:5"), True, "names no earlier scribe op"),
        (scribed(follows="S1"), True, "names no earlier scribe op"),
        (scribed(allowance_mm=0.0), True, "must be positive"),
        (scribed(allowance_mm=0), True, "must be positive"),
        (scribed(allowance_mm=-0.5), True, "must be positive"),
        ({"op": 20, "do": "file_to_line", "feature": "arc", "allowance_mm": 0.5}, True, "only"),
        ({"op": 20, "do": "deburr", "follows": "S1:10"}, True, "only a saw cut"),
    ],
)
def test_saw_shapes_are_exclusive_and_follow_an_earlier_scribe(op, scribe, words):
    with pytest.raises(ValidationError, match=words):
        Plan.model_validate(plan(op, scribe=scribe))


def test_a_scribe_later_in_plan_order_is_not_a_line_to_follow():
    data = plan(scribed())
    del data["setups"][1]["stock_in"]
    data["setups"].reverse()
    with pytest.raises(ValidationError, match="names no earlier scribe op"):
        Plan.model_validate(data)


@pytest.mark.parametrize("route", ["stock", None], ids=["own-branch", "unrouted"])
def test_a_line_scribed_on_another_workpiece_is_not_followed(route):
    data = plan(scribed())
    data["setups"][1].pop("stock_in")
    if route is not None:
        data["setups"][1]["stock_in"] = route
        data["stock"] = {"components": [{"id": "a"}, {"id": "b"}]}
        data["setups"][0]["stock_in"] = "stock.a"
        data["setups"][1]["stock_in"] = "stock.b"
    with pytest.raises(ValidationError, match="scribed on another workpiece"):
        Plan.model_validate(data)


def test_a_line_scribed_earlier_in_the_same_setup_is_followed():
    data = plan()
    data["setups"][0]["ops"].append(scribed())
    Plan.model_validate(data)


# ------------------------------------------------------------- manual bench waiver and screens


def with_tool(bundle, kind):
    bundle.inventory["tools"] = {"hacksaw": {"kind": kind}}
    for op in bundle.plan["setups"][0]["ops"]:
        if op["do"] == "saw_cut":
            op.update(tool="hacksaw", cut_plane=dict(PLANE))
    return bundle


@pytest.mark.parametrize("kind", ["bench", "manual"])
@pytest.mark.parametrize("screen", SCREENS)
def test_a_hand_saw_keeps_the_manual_bench_waiver(screen, kind):
    bundle = with_tool(bench_bundle(kind, ("scribe", "saw_cut", "file_to_line")), "hand_saw")
    row = screen.evaluate(bundle)[0]
    assert row.status == "not_applicable"
    assert "inventory.tools.hacksaw: kind hand_saw" in row.cite


@pytest.mark.parametrize("kind", ["bandsaw", "unknown"])
@pytest.mark.parametrize("screen", SCREENS)
def test_a_powered_or_unresolved_saw_tool_waives_no_bench_screen(screen, kind):
    # A dedicated saw setup still has no spindle zero or headroom of its own, but the bench
    # kind waives nothing for a powered or unresolved blade.
    bundle = with_tool(bench_bundle("bench", ("saw_cut", "fit")), kind)
    row = screen.evaluate(bundle)[0]
    assert "plan.setups.B1.ops: manual bench actions only" not in row.cite
    assert row.numbers.get("machine_kind") != "bench"


@pytest.mark.parametrize(
    "debt",
    [{"verify": True}, {"source": {"verify": True}}],
    ids=["flagged", "nested"],
)
@pytest.mark.parametrize("screen", SCREENS)
def test_an_unverified_hand_saw_waives_no_bench_screen(screen, debt):
    bundle = with_tool(bench_bundle("bench", ("saw_cut", "fit")), "hand_saw")
    bundle.inventory["tools"]["hacksaw"].update(debt)
    row = screen.evaluate(bundle)[0]
    assert "plan.setups.B1.ops: manual bench actions only" not in row.cite


def saw_bundle(machine_kind="bench", tool_kind="hand_saw", op=None, kernel=None):
    return Bundle(
        plan={
            "setups": [
                {
                    "id": "S2",
                    "machine": "station",
                    "ops": [op or saw(cut_plane=dict(PLANE))],
                }
            ]
        },
        inventory={
            "machines": {"station": {"kind": machine_kind, "blade_speed_sfm": [80, 200]}},
            "tools": {"hacksaw": {"kind": tool_kind, "kerf_mm": 1.0, "material": "bimetal"}},
        },
        features={"features": {}, "units": "mm"},
        policy={},
        cutting_data={},
        paths={},
        hashes={},
        root=Path("."),
        kernel=kernel or {"status": "ok", "ops": {}},
    )


@pytest.mark.parametrize("machine", ["bench", "manual"])
def test_a_bench_hand_saw_has_no_blade_speed_screen(machine):
    row = speeds_feeds.evaluate(saw_bundle(machine))[0]
    assert row.status == "not_applicable"
    assert "blade_speed_sfm" not in row.numbers


@pytest.mark.parametrize("machine, tool", [("bench", "bandsaw"), ("bandsaw", "bandsaw")])
def test_a_powered_saw_keeps_its_blade_speed_screen(machine, tool):
    row = speeds_feeds.evaluate(saw_bundle(machine, tool))[0]
    assert row.status == "unknown"
    assert row.numbers["blade_speed_min_sfm"] == 80
    assert row.numbers["operation"] == "saw_cut"


@pytest.mark.parametrize(
    "machine, tool, status",
    [
        ("bench", "hand_saw", "pass"),
        ("manual", "hand_saw", "pass"),
        ("mill", "hand_saw", "error"),
        ("bandsaw", "hand_saw", "error"),
        ("manual", "bandsaw", "error"),
        ("bandsaw", "bandsaw", "pass"),
    ],
)
def test_a_hand_saw_cuts_only_at_a_bench_station(machine, tool, status):
    bundle = saw_bundle(machine, tool)
    row = next(row for row in tool_resolves.evaluate(bundle) if row.subject == "S2:20")
    assert row.status == status
    if status == "error":
        assert saw_cut.evaluate(bundle)[0].status == "error"


# ------------------------------------------------------------------- saw_cut on the scribed line

NATIVE = {
    "allowance_mm": 0.5,
    "retained_to_target_mm": 0.5,
    "removed_volume_mm3": 150.0,
    "stock_volume_before_mm3": 1000.0,
    "stock_volume_after_mm3": 850.0,
}


def scribed_bundle(native=None, **fields):
    detail = dict(NATIVE if native is None else native)
    return saw_bundle(op=scribed(**fields), kernel={"status": "ok", "ops": {"S2:20": detail}})


def test_a_scribed_cut_that_keeps_its_allowance_passes_without_a_kerf():
    bundle = scribed_bundle()
    del bundle.inventory["tools"]["hacksaw"]["kerf_mm"]
    finding = saw_cut.evaluate(bundle)[0]
    assert finding.status == "pass", finding.sentence
    assert finding.numbers["follows"] == "S1:10"
    assert finding.numbers["retained_to_target_mm"] == 0.5
    assert "cut_plane" not in finding.numbers


def test_kerf_debt_a_scribed_cut_never_reads_does_not_block_it():
    bundle = scribed_bundle()
    bundle.inventory["tools"]["hacksaw"].update(
        verify=False, kerf_mm={"value": "unknown", "verify": True}
    )
    assert saw_cut.evaluate(bundle)[0].status == "pass"
    row = next(row for row in tool_resolves.evaluate(bundle) if row.subject == "S2:20")
    assert row.status == "pass"
    # The same holds for a kit member's own kerf debt; other member debt still counts.
    kit = scribed_bundle(tool="hacksaws/fine")
    kit.kernel["ops"]["S2:20"] = dict(NATIVE)
    kit.inventory["tools"] = {
        "hacksaws": {
            "kind": "hand_saw",
            "verify": False,
            "members": {"fine": {"kerf_mm": {"value": "unknown", "verify": True}}},
        }
    }
    assert saw_cut.evaluate(kit)[0].status == "pass"
    kit.inventory["tools"]["hacksaws"]["members"]["fine"]["verify"] = True
    assert saw_cut.evaluate(kit)[0].status == "unknown"
    # A straight cut reads that kerf: the same debt keeps it unknown.
    straight = saw_bundle()
    straight.inventory["tools"]["hacksaw"]["kerf_mm"] = {"value": "unknown", "verify": True}
    assert saw_cut.evaluate(straight)[0].status == "unknown"


@pytest.mark.parametrize(
    "change, words",
    [
        ({"allowance_mm": "unknown"}, "declare allowance_mm for S2:20"),
        ({"stock_removal_bounds": "unknown"}, "declare stock_removal_bounds"),
        ({"retained_to_target_mm": "unknown"}, "clearance to the target"),
    ],
)
def test_a_scribed_cut_with_unknown_extent_or_allowance_stays_debt(change, words):
    native = {**NATIVE, **{k: v for k, v in change.items() if k in NATIVE}}
    fields = {k: v for k, v in change.items() if k not in NATIVE or k == "allowance_mm"}
    if "stock_removal_bounds" in change:
        native["saw_reason"] = "declare stock_removal_bounds for S2:20: the region the saw takes"
        for key in ("removed_volume_mm3", "stock_volume_after_mm3"):
            native[key] = "unknown"
    finding = saw_cut.evaluate(scribed_bundle(native, **fields))[0]
    assert finding.status == "unknown"
    assert words in finding.sentence


def test_a_scribed_cut_into_its_allowance_is_an_error():
    native = {**NATIVE, "retained_to_target_mm": 0.2}
    native["saw_error"] = (
        "the declared saw region comes within 0.2 mm of the finished target, inside the 0.5 mm "
        "allowance left for the file"
    )
    assert saw_cut.evaluate(scribed_bundle(native))[0].status == "error"


# ------------------------------------------------------- the file after a saw to the line


def test_a_saw_to_the_scribed_line_roughs_the_arc_for_the_file():
    data = plan(scribed())
    filing = {"op": 30, "do": "file_to_line", "feature": "arc"}
    data["setups"][1]["ops"].append(filing)
    bundle = SimpleNamespace(plan=data)
    assert _rough(bundle, filing, "arc") == "S2 op 20"
    other = deepcopy(data)
    other["setups"][0]["ops"][0]["feature"] = "other_arc"
    assert _rough(SimpleNamespace(plan=other), other["setups"][1]["ops"][1], "arc") is None


# ------------------------------------------------------------------------ the hand-saw card


@pytest.mark.parametrize(
    "op, words",
    [
        (scribed(), "Hand saw outside the line scribed in S1 op 10, leave 0.500 mm for filing."),
        (
            scribed(allowance_mm="unknown"),
            "STOP: stock to leave for filing not established",
        ),
        (
            saw(cut_plane=dict(PLANE)),
            "keeping the -Y piece 37.5 mm long; the kerf falls on the +Y (waste) side",
        ),
    ],
)
def test_a_bench_hand_saw_prints_a_hand_saw_card(op, words):
    native = {"retained_boundary_mm": 87.0, "retained_length_mm": 37.5}
    bundle = saw_bundle(op=op, kernel={"status": "ok", "ops": {"S2:20": native}})
    findings = saw_cut.evaluate(bundle) + speeds_feeds.evaluate(bundle)
    setup = bundle.plan["setups"][0]
    html, _, _, _ = _Traveler(bundle, findings, {}, None).operations(setup, {}, {"notes": 2})
    text = re.sub(r"<[^>]+>", "", html)
    assert "ASSEMBLY / FINISHING" in text
    assert words in text
    assert "deburr" not in html
    assert "STOP: no blade speed" not in html
