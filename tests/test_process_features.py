"""Plan process features: stock preparation a later setup relies on (docs/plan.md).

The pivot-shaft example faces its plain end and centre-drills it in S0 so S1's dead centre
has a seat. Each test perturbs that route structurally and reads the consumer verdict.
"""

import math

import pytest
from test_cli import copy_examples
from test_envelope_m5 import measured
from test_process_route import HEADER, blocks, drop_setup_key, evaluate, rewrite, setups

from prechips import kernel
from prechips.findings import Finding, exit_code, is_required
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
    ("change", "status", "made"),
    [
        (None, "pass", True),
        # Nothing upstream drills the seat: the hold contradicts the route.
        ("no centre drill", "error", False),
        # S1's arriving stock is undeclared: whether it has the centre is unknown.
        ("undeclared routing", "unknown", False),
        # S0 drills the centre, but S0's own arriving stock is undeclared upstream.
        ("undeclared upstream routing", "unknown", True),
        # S0 drills it, but the centre it drills has an unknown size.
        ("unknown drill length", "unknown", True),
    ],
)
def test_a_dead_centre_rides_only_in_a_centre_an_earlier_setup_drilled(
    tmp_path, change, status, made
):
    plan = shaft(tmp_path)
    synthetic_centre_tool(plan)
    if change == "no centre drill":
        rewrite(plan, ("op", *centre_drill(plan)), remove=True)
    if change == "undeclared routing":
        drop_setup_key(plan, "S1", "stock_in")
    if change == "undeclared upstream routing":
        drop_setup_key(plan, "S0", "stock_in")
    if change == "unknown drill length":
        set_process_key(plan, "plain_end_centre", "drill_length_mm", '"unknown"')
    row = evaluate("centre_support", load_bundle(plan))["S1"]
    assert row.status == status
    assert row.numbers["made_by"] == (["{} op {}".format(*centre_drill(plan))] if made else [])


def set_tool_fact(plan, key, value):
    """Set (``None``: remove) ``key`` on the selected #2 centre drill in the copied inventory."""
    inventory = plan.parents[1] / "inventory" / "pedro-shop.toml"
    lines = inventory.read_text(encoding="utf-8").splitlines(keepends=True)
    start = lines.index('[tools.center-drills-lms-4859.members."2"]\n')
    end = next(n for n in range(start + 1, len(lines)) if HEADER.fullmatch(lines[n]))
    body = [line for line in lines[start + 1 : end] if not line.startswith(f"{key} =")]
    added = [] if value is None else [f"{key} = {value}\n"]
    inventory.write_text("".join([*lines[: start + 1], *added, *body, *lines[end:]]), "utf-8")


def synthetic_centre_tool(plan):
    """Known #2 drill for centre-shape tests, not a certification of the example inventory."""
    for key, value in {
        "dia_mm": 1.98,
        "shank_in": 0.1875,
        "flute_len_mm": 1.9,
        "pilot_len_mm": 1.98,
        "oal_mm": 47.6,
        "point_angle": 118,
    }.items():
        set_tool_fact(
            plan,
            key,
            f'{{ value = {value}, measured = {{ status = "measured", '
            'by = "synthetic test operator", date = "2026-10-05", '
            'instrument = "synthetic centre drill specification" } }',
        )


def synthetic_shaft_cutting_geometry(bundle):
    """Finite, test-owned S0/S1 tool/chuck geometry for the native centre/claim scenarios."""
    bundle.inventory["machines"]["PM-1127VF-LB"]["resolution_mm"] = measured(0.01)
    toolpost = "qctp-axa-lms-2280/1-turning-facing"
    for tool, width in (
        (bundle.inventory["tools"]["turning-tools-warner-lms-4132"]["members"]["AR"], 11.0),
        (bundle.inventory["tools"]["hss-toolbit-3-8-rh"], 10.1),
    ):
        for key, value in {
            "nose_radius_mm": 0.4,
            "insert_angle_deg": 60.0,
            "entering_angle_deg": 93.0,
            "edge_len_mm": 11.0,
            "head_len_mm": 14.0,
            "shank_width_mm": 9.525,
            "functional_width_mm": width,
        }.items():
            tool[key] = measured(value)
        tool["projection_mm"] = {toolpost: measured(20.0)}
    bundle.inventory["tools"]["hss-toolbit-3-8-rh"]["shank_in"] = measured(0.375)
    holder = bundle.inventory["holders"]["qctp-axa-lms-2280"]["members"]["1-turning-facing"]
    holder.update(body_width_mm=measured(60.0), body_depth_mm=measured(32.0))
    bundle.inventory["holders"]["drill-chuck-tailstock-mt3"].update(
        gauge_len_mm=measured(85.0), gauge_dia_mm=measured(50.8), grip_mm=measured(20.0)
    )
    drill = bundle.inventory["tools"]["center-drills-lms-4859"]["members"]["2"]
    drill["projection_mm"] = {"drill-chuck-tailstock-mt3": measured(27.0)}
    # Replace the illustrative chuck/range with a fresh, finite test-owned record.
    chuck = {
        "kind": "chuck_3jaw",
        "mount": "D1-4",
        "fits": "PM-1127VF-LB",
        "scroll": True,
        "range_mm": [3.0, 140.0],
        "note": "synthetic test chuck and gripping range",
    }
    bundle.inventory["fixtures"]["chuck-3jaw-6-d1-4"] = chuck
    for key, value in {
        "body_dia_mm": 158.0,
        "body_length_mm": 72.0,
        "bore_dia_mm": 40.0,
        "jaw_width_mm": 16.0,
        "jaw_height_mm": 45.0,
        "jaw_depth_mm": 25.0,
    }.items():
        chuck[key] = measured(value)


@pytest.mark.parametrize(
    ("where", "key", "value", "status"),
    [
        (None, None, None, "pass"),
        # The plan declares a centre the selected #2 drill cannot cut (Table 6 D, C, angle).
        ("plan", "drill_length_mm", "2.48", "error"),
        ("plan", "drill_dia_mm", "2.5", "error"),
        ("plan", "countersink_angle_deg", "90.0", "error"),
        # A mouth wider than the 3/16 in body: the countersink cannot open that far.
        ("plan", "mouth_dia_mm", "5.0", "error"),
        # The selected tool's own geometry changes while the plan stays the same.
        ("tool", "pilot_len_mm", "2.48", "error"),
        ("tool", "dia_mm", "2.5", "error"),
        ("tool", "angle_deg", "90", "error"),
        # The tool's drill length C is not recorded: the depth cannot be bound.
        ("tool", "pilot_len_mm", None, "unknown"),
        # The pilot point that closes the centre: unknown or unconfirmed, it is no centre the
        # kernel can cut; so sharp that it is longer than C, no centre the tool can be.
        ("tool", "point_angle", '"unknown"', "unknown"),
        ("tool", "point_angle", "{ value = 118, verify = true }", "unknown"),
        ("tool", "point_angle", "40", "error"),
        # Valid finite angles whose derived cone underflows or overflows are unresolved,
        # never a fabricated depth or an exception in the endpoint/kernel/support join.
        ("tool", "point_angle", "5e-324", "unknown"),
        ("matching angles", "countersink_angle_deg", "5e-324", "unknown"),
        ("matching angles", "countersink_angle_deg", "1e-310", "unknown"),
        # An unconfirmed tool record leaves every endpoint it cuts unknown, centres included.
        ("tool", "oal_mm", "{ value = 47.6, verify = true }", "unknown"),
        ("tool", "verify", "true", "unknown"),
    ],
)
def test_a_centre_is_the_shape_its_selected_tool_cuts(tmp_path, where, key, value, status):
    plan = shaft(tmp_path)
    synthetic_centre_tool(plan)
    if where == "plan":
        set_process_key(plan, "plain_end_centre", key, value)
    elif where == "tool":
        set_tool_fact(plan, key, value)
    elif where == "matching angles":
        set_process_key(plan, "plain_end_centre", key, value)
        set_tool_fact(plan, "angle_deg", value)
    bundle = load_bundle(plan)
    endpoint = evaluate("blind_depth", bundle)["plain_end_centre"]
    assert endpoint.status == status
    # The traveler's quill depth is the tool's own centre, else no depth is printed.
    (row,) = endpoint.numbers["endpoints"]
    assert (row["depth_mm"] == "unknown") is (status != "pass")
    if status == "pass":
        assert row["depth_mm"] == pytest.approx(2.8633, abs=5e-5)
        assert math.isfinite(row["depth_mm"])
    # The kernel cuts that same centre or none.
    setup = bundle.plan["setups"][0]
    op = next(op for op in setup["ops"] if op["do"] == "center_drill")
    job = kernel.op_inputs(bundle, setup, op)
    process_cut = job["process_cut"]
    if where == "matching angles":
        # An unresolved cone shoulder is omitted from the numeric kernel request.
        assert "shank_from_mm" not in job
    elif status == "pass":
        assert math.isfinite(job["shank_from_mm"])
        assert job["shank_from_mm"] > 0
    assert ("reason" in process_cut) is (status != "pass")
    if status != "pass":
        assert process_cut["reason"]
    # A centre its maker cannot be shown to cut is no seat for S1's dead centre.
    assert evaluate("centre_support", bundle)["S1"].status == status


@pytest.mark.parametrize(
    ("key", "value", "status"),
    [
        ("at", "[0.0, 0.0, -173.5]", "pass"),
        # Buried under the faced end the quill is touched on, by a little and by a lot.
        ("at", "[0.0, 0.0, -173.25]", "error"),
        ("at", "[0.0, 0.0, -169.5]", "error"),
        # Standing proud of the faced end, in air the quill never touches.
        ("at", "[0.0, 0.0, -173.75]", "error"),
        # Drilled from the far side: not along the quill's feed.
        ("axis", "[0.0, 0.0, -1.0]", "error"),
        # On the faced end but off the spindle axis the tailstock quill feeds along.
        ("at", "[0.5, 0.0, -173.5]", "error"),
        ("at", '"unknown"', "unknown"),
    ],
)
def test_a_centre_mouth_lies_on_the_surface_the_quill_is_touched_on(tmp_path, key, value, status):
    plan = shaft(tmp_path)
    synthetic_centre_tool(plan)
    set_process_key(plan, "plain_end_centre", key, value)
    bundle = load_bundle(plan)
    endpoint = evaluate("blind_depth", bundle)["plain_end_centre"]
    assert endpoint.status == status
    (row,) = endpoint.numbers["endpoints"]
    assert (row["depth_mm"] == "unknown") is (status != "pass")
    assert evaluate("centre_support", bundle)["S1"].status == status


def test_an_unknown_quill_touch_surface_leaves_the_centre_unknown(tmp_path):
    plan = shaft(tmp_path)
    synthetic_centre_tool(plan)
    # Op 10 faces the plain end the quill is touched on; its height is now unknown.
    rewrite(plan, ("op", "S0", 10), "to_z", '"unknown"')
    bundle = load_bundle(plan)
    assert evaluate("blind_depth", bundle)["plain_end_centre"].status == "unknown"
    assert evaluate("centre_support", bundle)["S1"].status == "unknown"


def only_first_setup(plan):
    """Keep S0 alone: the stock and the centre it drills, with no later consumer."""
    text = plan.read_text(encoding="utf-8")
    plan.write_text(text[: text.index("[[setups]]", text.index("[[setups]]") + 1)], "utf-8")


@pytest.mark.parametrize(
    ("where", "value", "status"),
    [
        ("at", "[0.0, 0.0, -173.5]", "pass"),
        ("at", "[0.0, 0.0, -173.25]", "unknown"),
        ("at", "[0.0, 0.0, -169.5]", "unknown"),
        ("tool", "2.48", "unknown"),
    ],
)
def test_the_kernel_drills_only_the_tool_s_centre_from_the_exposed_stock_surface(
    tmp_path, freecad_kernel, where, value, status
):
    plan = shaft(tmp_path)
    synthetic_centre_tool(plan)
    only_first_setup(plan)
    if where == "at":
        set_process_key(plan, "plain_end_centre", "at", value)
    else:
        set_tool_fact(plan, "pilot_len_mm", value)
    bundle = load_bundle(plan)
    synthetic_shaft_cutting_geometry(bundle)
    assert kernel.run_geometry(bundle)["status"] == "ok"
    rows = rules(bundle, "accessibility", "reach")
    assert {name: rows[name]["S0:20"].status for name in rows} == {
        "accessibility": status,
        "reach": status,
    }


def gate(bundle, row):
    """The checker's exit on ``row`` with every rule the shop policy requires passing."""
    passing = [Finding(rule, "*", "pass", {}, [], "") for rule in bundle.policy["required"]]
    return exit_code([*passing, row], bundle.policy, bundle)


LIVE_CENTRE = '\n[fixtures.live-centre-mt3]\nkind = "live_centre"\nfits = "PM-1127VF-LB"\n'
# Supports whose kind leaves open whether they are centres; a tailstock, which carries work
# only on one; a centre named by kind alone; and rests of known non-centre kind carrying
# record-level or measurement verification debt.
SUPPORTS = (
    LIVE_CENTRE
    + '\n[fixtures.kind-unknown]\nkind = "unknown"\n'
    + '\n[fixtures.tailstock-x]\nkind = "tailstock"\n'
    + '\n[fixtures.pipe-centre]\nkind = "pipe_center"\n'
    + '\n[fixtures.unconfirmed-rest]\nkind = "steady_rest"\nverify = true\n'
    + '\n[fixtures.unmeasured-rest]\nkind = "steady_rest"\n'
    + "capacity_min_mm = { value = 5, verify = true }\ncapacity_max_mm = 50\n"
    + '\n[fixtures.self-centering-rest]\nkind = "self_centering_steady_rest"\n'
)


def add_supports(plan):
    """Add ``SUPPORTS``, a fixture declared wholly ``"unknown"`` and two tailstock-mounted
    standard accessories that are not centres to the copied inventory."""
    inventory = plan.parents[1] / "inventory" / "pedro-shop.toml"
    text = inventory.read_text(encoding="utf-8")
    text = text.replace("[fixtures]\n", '[fixtures]\ndeclared-unknown = "unknown"\n', 1)
    text = text.replace(
        "standard_accessories = [",
        'standard_accessories = ["tailstock_drill_chuck", "tailstock_quill", ',
        1,
    )
    inventory.write_text(text + SUPPORTS, "utf-8")


@pytest.mark.parametrize(
    ("key", "value", "status"),
    [
        # A live centre in the tailstock, as the support or among the supports.
        ("support", '"live-centre-mt3"', "unknown"),
        ("supports", '["follow_rest", { ref = "live-centre-mt3" }]', "unknown"),
        # A machine's standard-accessory dead centre, with no fixture record of its own.
        ("support", '"dead_centre_headstock"', "unknown"),
        # A tailstock carries the work on a centre; so does any kind naming one.
        ("support", '"tailstock-x"', "unknown"),
        ("support", '"pipe-centre"', "unknown"),
        # A support that is unknown, or that the inventory does not know, may be a centre.
        ("support", '"unknown"', "unknown"),
        ("support", '"tailstock-thing"', "unknown"),
        # So may an inventory record declared unknown, or of unknown kind.
        ("support", '"declared-unknown"', "unknown"),
        ("support", '"kind-unknown"', "unknown"),
        # No centre: the rest alone, or nothing.
        ("supports", '["follow_rest"]', "not_applicable"),
        ("support", '"none"', "not_applicable"),
        # Tailstock-mounted accessories that are not centres.
        ("support", '"tailstock_drill_chuck"', "not_applicable"),
        ("support", '"tailstock_quill"', "not_applicable"),
        # Rests whose kind is known: their verify or measurement debt is their own checks'.
        ("support", '"steady_rest"', "not_applicable"),
        ("supports", '["unconfirmed-rest"]', "not_applicable"),
        ("support", '"unmeasured-rest"', "not_applicable"),
        ("support", '"self-centering-rest"', "not_applicable"),
    ],
)
def test_a_centre_with_no_prepared_seat_blocks_without_any_shop_policy_entry(
    tmp_path, key, value, status
):
    plan = shaft(tmp_path)
    add_supports(plan)
    # S2 carries no centre in the example; it now rides on one with no centre_hole.
    rewrite(plan, ("hold", "S2"), key, value)
    bundle = load_bundle(plan)
    assert "centre_support" not in bundle.policy["required"]
    row = evaluate("centre_support", bundle)["S2"]
    assert row.status == status
    assert is_required(row, bundle.policy, bundle)
    assert gate(bundle, row) == (0 if status == "not_applicable" else 4)


@pytest.mark.parametrize(
    ("supports", "seat", "status"),
    [
        ('["follow_rest"]', MOUTH, "pass"),
        # Beside S1's prepared dead centre, a further support that may be a centre...
        ('["unknown"]', MOUTH, "unknown"),
        ('["missing-support"]', MOUTH, "unknown"),
        ('["follow_rest", "kind-unknown"]', MOUTH, "unknown"),
        # ...or a second centre, whose seat the one centre_hole cannot be.
        ('["dead_centre_headstock"]', MOUTH, "unknown"),
        # An established contradiction still stands.
        ('["unknown"]', 4.0, "error"),
    ],
)
def test_a_prepared_centre_never_hides_another_support_that_may_be_a_centre(
    tmp_path, supports, seat, status
):
    plan = shaft(tmp_path)
    synthetic_centre_tool(plan)
    add_supports(plan)
    rewrite(plan, ("hold", "S1"), "supports", supports)
    rewrite(plan, ("hold", "S1"), "centre_hole_dia_mm", repr(seat))
    bundle = load_bundle(plan)
    row = evaluate("centre_support", bundle)["S1"]
    assert row.status == status
    assert gate(bundle, row) == {"pass": 0, "unknown": 4, "error": 2}[status]


@pytest.mark.parametrize(("seat", "status"), [(MOUTH, "pass"), (4.0, "error"), (2.5, "error")])
def test_the_hold_seats_the_centre_in_the_mouth_the_centre_drill_made(tmp_path, seat, status):
    plan = shaft(tmp_path)
    synthetic_centre_tool(plan)
    rewrite(plan, ("hold", "S1"), "centre_hole_dia_mm", repr(seat))
    row = evaluate("centre_support", load_bundle(plan))["S1"]
    assert row.status == status
    assert row.numbers["mouth_dia_mm"] == MOUTH


# ``support`` and ``supports`` naming one centre, bare in one and qualified in the other,
# are one centre: the prepared seat passes. A second, different centre stays unknown.
@pytest.mark.parametrize(
    ("support", "supports", "status"),
    [
        ("{}", ["fixtures.{}"], "pass"),
        ("fixtures.{}", ["{}"], "pass"),
        ("{}", ["other-centre"], "unknown"),
    ],
    ids=["bare-qualified", "qualified-bare", "distinct"],
)
def test_one_centre_spelled_twice_in_the_hold_is_one_centre(tmp_path, support, supports, status):
    plan = shaft(tmp_path)
    synthetic_centre_tool(plan)
    bundle = load_bundle(plan)
    hold = next(s for s in bundle.plan["setups"] if s["id"] == "S1")["hold"]
    key = hold["support"].removeprefix("fixtures.")
    bundle.inventory["fixtures"]["other-centre"] = dict(bundle.inventory["fixtures"][key])
    hold.update(support=support.format(key), supports=[s.format(key) for s in supports])
    row = evaluate("centre_support", bundle)["S1"]
    assert row.status == status, row.sentence
    assert len(row.numbers["centres"]) == (1 if status == "pass" else 2)


@pytest.mark.parametrize("mouth", [MOUTH, 4.0])
def test_centre_depth_is_table_6_drill_length_plus_the_countersink_to_the_mouth(tmp_path, mouth):
    plan = shaft(tmp_path)
    synthetic_centre_tool(plan)
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
    before_bundle = load_bundle(plan)
    synthetic_shaft_cutting_geometry(before_bundle)
    before = rules(before_bundle, "finish_coverage")["finish_coverage"]["shoulder_thrust"]
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
    after_bundle = load_bundle(plan)
    synthetic_shaft_cutting_geometry(after_bundle)
    after = rules(after_bundle, "finish_coverage")["finish_coverage"]["shoulder_thrust"]
    assert after.status == "error"
    assert set(after.numbers["uncovered_faces"]) == set(before.numbers["required_faces"])
