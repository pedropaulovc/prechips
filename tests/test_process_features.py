"""Plan process features: stock preparation a later setup relies on (docs/plan.md).

The pivot-shaft example faces its plain end and centre-drills it in S0 so S1's dead centre
has a seat. Each test perturbs that route structurally and reads the consumer verdict.
"""

import math

import pytest
from test_cli import copy_examples
from test_process_route import HEADER, blocks, drop_setup_key, evaluate, rewrite, setups

from prechips.inputs import load_bundle
from prechips.rules import RULES
from prechips.rules.resolution import claim_refs

# Machinery's Handbook 27th ed. p.873 Table 6, plain size 2: drill D and drill length C
# 5/64 in (as the example plan rounds them), 60° countersink, opened to the plan's Ø3.0.
DRILL, LENGTH, MOUTH, ANGLE = 1.98, 1.98, 3.0, 60.0


def shaft(tmp_path):
    return copy_examples(tmp_path) / "pivot-shaft" / "plan.toml"


def centre_drill(plan):
    """``(setup id, op)`` of the one op that centre-drills the plain end."""
    return next(
        (setup["id"], op["op"])
        for setup in setups(plan)
        for op in setup["ops"]
        if op["do"] == "center_drill"
    )


def set_process_key(plan, name, key, value):
    """Replace ``key`` in ``[process_features.<name>]``."""
    lines = plan.read_text(encoding="utf-8").splitlines(keepends=True)
    start = lines.index(f"[process_features.{name}]\n")
    end = next(n for n in range(start + 1, len(lines)) if HEADER.fullmatch(lines[n]))
    lines[start + 1 : end] = [
        f"{key} = {value}\n" if line.startswith(f"{key} =") else line
        for line in lines[start + 1 : end]
    ]
    plan.write_text("".join(lines), encoding="utf-8")


@pytest.mark.parametrize(
    ("change", "status"),
    [
        (None, "pass"),
        # Nothing upstream drills the seat: the hold contradicts the route.
        ("no centre drill", "error"),
        # S1's arriving stock is undeclared: whether it has the centre is unknown.
        ("undeclared routing", "unknown"),
    ],
)
def test_a_dead_centre_rides_only_in_a_centre_an_earlier_setup_drilled(tmp_path, change, status):
    plan = shaft(tmp_path)
    if change == "no centre drill":
        rewrite(plan, ("op", *centre_drill(plan)), remove=True)
    if change == "undeclared routing":
        drop_setup_key(plan, "S1", "stock_in")
    row = evaluate("centre_support", load_bundle(plan))["S1"]
    assert row.status == status
    made = row.numbers["made_by"]
    assert made == ([] if change else ["{} op {}".format(*centre_drill(plan))])


@pytest.mark.parametrize(("seat", "status"), [(MOUTH, "pass"), (4.0, "error"), (2.5, "error")])
def test_the_hold_seats_the_centre_in_the_mouth_the_centre_drill_made(tmp_path, seat, status):
    plan = shaft(tmp_path)
    rewrite(plan, ("hold", "S1"), "centre_hole_dia_mm", repr(seat))
    row = evaluate("centre_support", load_bundle(plan))["S1"]
    assert row.status == status
    assert row.numbers["mouth_dia_mm"] == MOUTH


@pytest.mark.parametrize("mouth", [MOUTH, 4.0])
def test_centre_depth_is_table_6_drill_length_plus_the_countersink_to_the_mouth(tmp_path, mouth):
    plan = shaft(tmp_path)
    set_process_key(plan, "plain_end_centre", "mouth_dia_mm", repr(mouth))
    rows = evaluate("blind_depth", load_bundle(plan))["plain_end_centre"].numbers["endpoints"]
    countersink = (mouth - DRILL) / 2 / math.tan(math.radians(ANGLE / 2))
    assert [row["depth_mm"] for row in rows] == [pytest.approx(LENGTH + countersink)]
    assert rows[0]["countersink_depth_mm"] == pytest.approx(countersink)
    # Fed on the tailstock quill from touching the faced end (Z0 after op 10).
    assert rows[0]["entry_z"] == 0.0
    assert rows[0]["tip_z"] == pytest.approx(-(LENGTH + countersink))
    if mouth == MOUTH:
        assert rows[0]["depth_mm"] == pytest.approx(2.8633, abs=5e-5)


def test_a_drawing_feature_finished_by_reaming_is_not_stock_preparation(tmp_path):
    # The rocker's exported pivot bore carries its own drawing `process = "ream"`; that
    # must neither refuse its inspected ream op nor turn its STEP faces into a plan label.
    bundle = load_bundle(copy_examples(tmp_path) / "rocker-arm" / "plan.toml")
    bore = bundle.feature_definitions["pivot_bore"]
    assert bore["process"] == "ream"
    ream = next(
        op
        for setup in bundle.plan["setups"]
        for op in setup["ops"]
        if op.get("feature") == "pivot_bore" and op["do"] == "ream"
    )
    assert claim_refs(bundle, ream) == bore["faces"]
    assert set(ream["checks"]) == {"dia", "finish_ra"}


def drop_checks(plan, block):
    """Remove the ``[setups.ops.checks]`` sub-table from one op block."""
    lines = plan.read_text(encoding="utf-8").splitlines(keepends=True)
    start, end = blocks(lines, setups(plan))[block]
    head = next(n for n in range(start, end) if lines[n].startswith("[setups.ops.checks]"))
    stop = next((n for n in range(head + 1, end) if HEADER.fullmatch(lines[n])), end)
    plan.write_text("".join([*lines[:head], *lines[stop:]]), encoding="utf-8")


def thrust_face_op(plan):
    return next(
        ("op", setup["id"], op["op"])
        for setup in setups(plan)
        for op in setup["ops"]
        if op["do"] == "face" and op.get("feature") == "shoulder_thrust"
    )


def rules(bundle, *names):
    return {
        name: {
            row.subject: row for row in next(r for r in RULES if r.name == name).evaluate(bundle)
        }
        for name in names
    }


def test_a_process_face_cut_on_a_drawing_plane_never_finishes_that_face(tmp_path, freecad_kernel):
    plan = shaft(tmp_path)
    before = rules(load_bundle(plan), "finish_coverage")["finish_coverage"]["shoulder_thrust"]
    assert before.status == "pass"
    # The same facing pass, now preparing a plan process face laid on the thrust plane.
    block = thrust_face_op(plan)
    drop_checks(plan, block)
    rewrite(plan, block, "feature", '"thrust_plane"')
    plan.write_text(
        plan.read_text(encoding="utf-8")
        + "\n[process_features.thrust_plane]\n"
        + 'kind = "end_face"\n'
        + "at = [0.0, 0.0, -7.5]\n"
        + "axis = [0.0, 0.0, 1.0]\n"
        + 'cite = ["test: a process face on the exported shoulder thrust plane"]\n',
        encoding="utf-8",
    )
    after = rules(load_bundle(plan), "finish_coverage")["finish_coverage"]["shoulder_thrust"]
    assert after.status == "error"
    assert set(after.numbers["uncovered_faces"]) == set(before.numbers["required_faces"])
