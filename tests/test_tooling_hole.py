"""Plan tooling holes drilled in the work's own waste (#293).

The rocker bar's -X and +X ears are waste (outside X ±160). As in harmonic-analyzer's
rocker route v3, T1 drills and reams the CL locating hole in the -X ear and drills the CR
clearance hole in the +X ear; T3 locates the work on a dowel in CL and a pin in CR; T4 saws
the -X ear off, CL with it; T5 still names both. Each edge case perturbs that bundle.
"""

import math
import re
from dataclasses import replace

import pytest
from test_cli import copy_examples, rocker_s1_alone

from prechips import kernel
from prechips.findings import ALWAYS_REQUIRED, is_required
from prechips.inputs import BadInput, load_bundle
from prechips.rules import RULES
from prechips.rules.geometry_common import prepared_job

MEASURED = (
    'measured = { status = "measured", by = "test value (not a shop measurement)", '
    'date = "2026-10-17", instrument = "test fixture (no physical measurement)" }'
)
# Setup frame TA sits at model [0, 8, 3.52825]; the raw bar is model Z -9.525..9.525.
TOP, THICKNESS = 9.525 - 3.52825, 19.05
CL, CR, HUB = (-166.0, 12.5), (166.0, 12.5), (0.0, 8.0)
REAMER = 6.512  # tools.reamers-metric/6.5mm, the hole the kernel cuts
PIN = 6.495


def dowel(name, hole, dia, offset):
    """A test locating-pin fixture whose one cylinder ``locates`` ``hole``."""
    return (
        f'\n[fixtures.{name}]\nname = "{name}"\nkind = "locating_pin"\n'
        f'note = "test locating pin"\nsolids = [\n'
        f'  {{ name = "pin", shape = "cylinder", at_mm = [0.0, 0.0, 0.0], axis = [0.0, 0.0, 1.0], '
        f'dia_mm = {dia}, length_mm = 40.0, locates = "{hole}", bears = "bore", {MEASURED} }},\n'
        "]\n"
        if offset is not None
        else ""
    )


def clamp(ref, at, offset):
    origin = [at[0] + offset, at[1] - 8.0, -25.0]
    return (
        f'  {{ ref = "{ref}", restraint = "locate", pose = {{ origin_mm = {origin}, '
        'x = [1.0, 0.0, 0.0], z = [0.0, 0.0, 1.0] }, note = "test locator" },\n'
    )


def later(header, sid, stock_in, clamps):
    """The S1 header as setup ``sid``, receiving ``stock_in``, with locate ``clamps``."""
    text = header.replace('id = "S1"', f'id = "{sid}"', 1)
    text = re.sub(r"(?m)^stock_in = .*$", f'stock_in = "{stock_in}"', text, count=1)
    text = re.sub(r"(?m)^\[setups\.hold\]\n", lambda m: m[0] + f"clamps = [\n{clamps}]\n", text)
    return text + '\n[[setups.ops]]\nop = 10\ndo = "deburr"\nfeature = "hub_faces"\n'


def bundle_plan(tmp_path, *, pin=PIN, cl_band="[6.500, 6.530]", saw=True, drill_cl=True):
    """Write the CL/CR rocker bundle; returns its plan path."""
    root = copy_examples(tmp_path)
    plan = root / "rocker-arm" / "plan.toml"
    inventory = root / "inventory" / "pedro-shop.toml"
    gap = (REAMER - pin) / 2 if isinstance(pin, float) else 0.0
    inventory.write_text(
        inventory.read_text(encoding="utf-8")
        + dowel("test-cl-dowel", "cl_tooling_hole", pin, gap)
        + dowel("test-cr-pin", "cr_tooling_hole", 6.35, (7.144 - 6.35) / 2)
        + dowel("test-hub-pin", "pivot_bore", 6.5, 0.0),
        encoding="utf-8",
    )
    text = rocker_s1_alone(plan.read_text(encoding="utf-8"))
    first = text.index("[[setups]]")
    head, s1 = text[:first], text[first:]
    # No op here faces the hubs, so the plan's faced-hub aims have nothing to move.
    head = re.sub(r"(?ms)^\[aims\.[^\n]*\n.*?(?=^\[|\Z)", "", head)
    s1 = s1.replace("[setups.stock_state]\n", "[setups.stock_state]\n", 1)
    s1 = re.sub(
        r"(?m)^\[setups\.stock_state\.local_thickness\]\n",
        lambda m: m[0] + f"cl_tooling_hole = {THICKNESS}\ncr_tooling_hole = {THICKNESS}\n",
        s1,
    )
    s1 = s1.rstrip("\n") + f"\n\n[setups.stock_state.entry_z]\ncl_tooling_hole = {TOP}\n"
    s1 += f"cr_tooling_hole = {TOP}\n"
    ops = ""
    spot = (
        '\n[[setups.ops]]\nop = {op}\ndo = "spot"\nfeature = "{hole}"\n'
        'tool = "center-drills-lms-4859/2"\nholder = "drill-chuck-r8"\ndepth_mm = 0.5\n'
    )
    if drill_cl:
        ops += spot.format(op=5, hole="cl_tooling_hole") + (
            '\n[[setups.ops]]\nop = 10\ndo = "drill"\nfeature = "cl_tooling_hole"\n'
            'tool = "drill-index-115/D"\nholder = "drill-chuck-r8"\nexit_mm = 2.0\n'
            '\n[[setups.ops]]\nop = 20\ndo = "ream"\nfeature = "cl_tooling_hole"\n'
            'tool = "reamers-metric/6.5mm"\nholder = "drill-chuck-r8"\nexit_mm = 2.0\n'
        )
    ops += spot.format(op=25, hole="cr_tooling_hole") + (
        '\n[[setups.ops]]\nop = 30\ndo = "drill"\nfeature = "cr_tooling_hole"\n'
        'tool = "drill-index-115/9-32in"\nholder = "drill-chuck-r8"\nexit_mm = 2.0\n'
    )
    header = s1.split("[setups.stock_state.entry_z]")[0]
    both = clamp("test-cl-dowel", CL, gap) + clamp("test-cr-pin", CR, (7.144 - 6.35) / 2)
    # The HUB pin in the pivot bore (model X0 Y8, the TA origin): the pin the dowel clocks.
    both += clamp("test-hub-pin", HUB, 0.0)
    setups = s1 + ops + "\n" + later(header, "T3", "S1", both)
    if saw:
        setups += (
            '\n[[setups]]\nid = "T4"\nmachine = "bandsaw-4x6"\nframe = "TA"\nstock_in = "T3"\n'
            '\n[setups.hold]\nfixture = "vise-bandsaw-4x6"\n'
            '\n[[setups.ops]]\nop = 10\ndo = "saw_cut"\ntool = "bandsaw-blade-4-6"\n'
            'cut_plane = { axis = "x", value = -161.0, keep = "above" }\n'
        )
    setups += later(header, "T5", "T4" if saw else "T3", both)
    holes = (
        "\n[process_features.cl_tooling_hole]\n"
        'kind = "tooling_hole"\n'
        f"at = [{CL[0]}, {CL[1]}, 9.525]\naxis = [0.0, 0.0, -1.0]\n"
        f"dia = {cl_band}\nthru = true\n"
        'note = "test: the -X ear locating hole; the T3 dowel locates on it; sawn off at T4"\n'
        'cite = ["test: rocker route v3 CL (harmonic-analyzer #1577)"]\n'
        "\n[process_features.cr_tooling_hole]\n"
        'kind = "tooling_hole"\n'
        f"at = [{CR[0]}, {CR[1]}, 9.525]\naxis = [0.0, 0.0, -1.0]\n"
        "dia = [7.0, 7.3]\nthru = true\n"
        'cite = ["test: rocker route v3 CR clearance hole"]\n'
    )
    plan.write_text(head + holes + "\n" + setups, encoding="utf-8")
    return plan


def rows(bundle, name="tooling_hole"):
    rule = next(rule for rule in RULES if rule.name == name)
    return {row.subject: row for row in rule.evaluate(bundle)}


def with_states(bundle, states):
    """``bundle`` on a synthetic kernel reporting tooling-hole ``states`` per setup."""
    setups = {
        sid: {"tooling_holes": {name: {"state": state} for name, state in holes.items()}}
        for sid, holes in states.items()
    }
    return replace(
        bundle, kernel={"status": "ok", "ops": {}, "setups": setups, "mapping": {}, "bbox_mm": []}
    )


ROUTE = {
    "S1": {"cl_tooling_hole": "undrilled", "cr_tooling_hole": "undrilled"},
    "T3": {"cl_tooling_hole": "present", "cr_tooling_hole": "present"},
    "T4": {"cl_tooling_hole": "present", "cr_tooling_hole": "present"},
    "T5": {"cl_tooling_hole": "gone", "cr_tooling_hole": "present"},
}


def test_the_issue_route_loads_and_resolves_as_plain_holes(tmp_path):
    bundle = load_bundle(bundle_plan(tmp_path))
    definition = bundle.feature_definitions["cl_tooling_hole"]
    assert definition["kind"] == "hole"
    assert definition["requirements"] == []
    assert definition["preparation"]["kind"] == "tooling_hole"
    assert definition["dia"] == [6.5, 6.53] and definition["thru"] is True


def test_the_route_locates_on_cl_until_the_saw_takes_it(tmp_path):
    found = rows(with_states(load_bundle(bundle_plan(tmp_path)), ROUTE))
    assert {subject: row.status for subject, row in found.items()} == {
        "S1:cl_tooling_hole": "pass",
        "S1:cr_tooling_hole": "pass",
        "T3:cl_tooling_hole": "pass",
        "T3:cr_tooling_hole": "pass",
        "T5:cl_tooling_hole": "error",
        "T5:cr_tooling_hole": "pass",
    }
    (fit,) = found["T3:cl_tooling_hole"].numbers["locators"]
    assert fit["clearance_mm"] == pytest.approx([6.5 - PIN, 6.53 - PIN])
    assert found["T3:cl_tooling_hole"].numbers["made_by"] == ["S1 op 5", "S1 op 10", "S1 op 20"]
    assert "gone" in found["T5:cl_tooling_hole"].sentence
    assert all(is_required(row, {"required": {}}) for row in found.values())


def test_a_pin_larger_than_the_hole_minimum_is_an_error(tmp_path):
    found = rows(with_states(load_bundle(bundle_plan(tmp_path, pin=6.505)), ROUTE))
    row = found["T3:cl_tooling_hole"]
    assert row.status == "error"
    assert "larger than cl_tooling_hole's Ø6.5 minimum" in row.sentence


def test_a_pin_at_the_hole_minimum_fits_with_zero_clearance(tmp_path):
    found = rows(with_states(load_bundle(bundle_plan(tmp_path, pin=6.5)), ROUTE))
    row = found["T3:cl_tooling_hole"]
    assert row.status == "pass"
    assert row.numbers["locators"][0]["clearance_mm"][0] == pytest.approx(0.0)


def test_an_unaccepted_pin_size_is_debt(tmp_path):
    plan = bundle_plan(tmp_path)
    inventory = plan.parents[1] / "inventory" / "pedro-shop.toml"
    text = inventory.read_text(encoding="utf-8")
    start = text.index("[fixtures.test-cl-dowel]")
    inventory.write_text(
        text[:start] + text[start:].replace(MEASURED, "verify = true", 1), encoding="utf-8"
    )
    row = rows(with_states(load_bundle(plan), ROUTE))["T3:cl_tooling_hole"]
    assert row.status == "unknown"
    assert "size is not accepted" in row.sentence


def test_an_unknown_hole_band_is_debt(tmp_path):
    row = rows(with_states(load_bundle(bundle_plan(tmp_path, cl_band='"unknown"')), ROUTE))
    assert row["T3:cl_tooling_hole"].status == "unknown"
    assert "dia band is unknown" in row["T3:cl_tooling_hole"].sentence


def test_a_pin_in_a_hole_no_earlier_setup_drills_is_an_error(tmp_path):
    states = {sid: dict(holes) for sid, holes in ROUTE.items()}
    states["T3"]["cl_tooling_hole"] = "undrilled"
    row = rows(with_states(load_bundle(bundle_plan(tmp_path, drill_cl=False)), states))
    assert row["T3:cl_tooling_hole"].status == "error"
    assert "no earlier setup in its stock lineage drills" in row["T3:cl_tooling_hole"].sentence


def test_a_hole_a_cut_only_crossed_is_debt(tmp_path):
    states = {sid: dict(holes) for sid, holes in ROUTE.items()}
    states["T3"]["cl_tooling_hole"] = "partial"
    row = rows(with_states(load_bundle(bundle_plan(tmp_path)), states))["T3:cl_tooling_hole"]
    assert row.status == "unknown"


def test_an_op_on_a_hole_that_is_gone_is_an_error(tmp_path):
    plan = bundle_plan(tmp_path)
    plan.write_text(
        plan.read_text(encoding="utf-8").replace(
            'op = 10\ndo = "deburr"\nfeature = "hub_faces"\n',
            'op = 10\ndo = "ream"\nfeature = "cl_tooling_hole"\ntool = "reamers-metric/6.5mm"\n'
            'holder = "drill-chuck-r8"\nexit_mm = 2.0\n',
        ),
        encoding="utf-8",
    )
    row = rows(with_states(load_bundle(plan), ROUTE))["T5:cl_tooling_hole"]
    assert row.status == "error" and row.numbers["ops"] == ["T5:10"]


def test_without_a_kernel_every_row_stays_unknown(tmp_path):
    bundle = replace(
        load_bundle(bundle_plan(tmp_path)),
        kernel={"status": "unavailable", "reason": "FreeCAD kernel not found"},
    )
    assert {row.status for row in rows(bundle).values()} == {"unknown"}


def test_plans_without_tooling_holes_get_no_tooling_hole_rows(tmp_path):
    bundle = load_bundle(copy_examples(tmp_path) / "rocker-arm" / "plan.toml")
    assert rows(bundle) == {}
    assert "tooling_hole" in ALWAYS_REQUIRED


def test_the_hole_earns_no_drawing_coverage_but_its_ops_are_judged(tmp_path):
    bundle = with_states(load_bundle(bundle_plan(tmp_path)), ROUTE)
    for name in ("coverage", "finish_coverage"):
        assert not any("tooling_hole" in subject for subject in rows(bundle, name))
    assert rows(bundle, "inspection")["cl_tooling_hole"].status == "not_applicable"
    # The ream finishes the band; the drill only roughs it.
    sizing = rows(bundle, "sizing")["cl_tooling_hole"]
    assert sizing.status == "pass" and sizing.numbers["tool"] == "reamers-metric/6.5mm"
    assert rows(bundle, "blind_depth")["cl_tooling_hole"].status == "pass"


def test_only_spot_drill_and_ream_make_a_tooling_hole(tmp_path):
    from prechips.process_features import process_operation

    bundle = load_bundle(bundle_plan(tmp_path))
    op = {"op": 5, "do": "tap", "feature": "cl_tooling_hole"}
    assert "made only by drill or ream or spot, not tap" in process_operation(bundle, op)["reason"]


def test_the_route_spots_drills_and_reams_as_any_hole_chain(tmp_path):
    found = rows(with_states(load_bundle(bundle_plan(tmp_path)), ROUTE), "op_chain")
    assert found["cl_tooling_hole"].status == "pass", found["cl_tooling_hole"].sentence
    assert found["cr_tooling_hole"].status == "pass", found["cr_tooling_hole"].sentence


def test_the_kernel_job_carries_the_drilled_hole_and_its_exit(tmp_path):
    bundle = load_bundle(bundle_plan(tmp_path))
    job = kernel.engine_job(prepared_job(bundle))
    assert job["process_features"]["cl_tooling_hole"]["thru"] is True
    (s1,) = [setup for setup in job["setups"] if setup["id"] == "S1"]
    spot = next(op for op in s1["ops"] if op["subject"] == "S1:5")
    # A spot stops at its own tip, even in a through hole.
    assert spot["process_cut"]["op_depth_mm"] == 0.5 and "through_mm" not in spot["process_cut"]
    ream = next(op for op in s1["ops"] if op["subject"] == "S1:20")
    assert "hole" not in ream
    assert ream["process_cut"]["diameter_mm"] == REAMER
    assert ream["process_cut"]["exit_mm"] == 2.0
    assert ream["process_cut"]["lead_mm"] == 1.0
    # Through: the authored local thickness plus exit_mm, as blind_depth prints it.
    assert ream["process_cut"]["through_mm"] == pytest.approx(THICKNESS + 2.0)
    drill = next(op for op in s1["ops"] if op["subject"] == "S1:10")
    assert drill["process_cut"]["point_angle_deg"] > 0


@pytest.mark.parametrize(("depth_mm", "status"), [(7.5, "pass"), (8.5, "error")])
def test_a_blind_tooling_hole_is_drilled_to_the_op_depth_within_its_own(tmp_path, depth_mm, status):
    plan = bundle_plan(tmp_path)
    text = plan.read_text(encoding="utf-8")
    start = text.index("[process_features.cr_tooling_hole]")
    text = text[:start] + text[start:].replace("thru = true\n", "depth = 10.0\n", 1)
    text = text.replace(
        'tool = "drill-index-115/9-32in"\nholder = "drill-chuck-r8"\nexit_mm = 2.0\n',
        f'tool = "drill-index-115/9-32in"\nholder = "drill-chuck-r8"\ndepth_mm = {depth_mm}\n',
    )
    plan.write_text(text, encoding="utf-8")
    bundle = load_bundle(plan)
    # The 118° point of the 7.14 drill runs on past depth_mm; depth bounds the whole tip.
    assert rows(bundle, "blind_depth")["cr_tooling_hole"].status == status
    job = kernel.engine_job(prepared_job(bundle))
    (s1,) = [setup for setup in job["setups"] if setup["id"] == "S1"]
    drill = next(op for op in s1["ops"] if op["subject"] == "S1:30")
    assert drill["process_cut"]["op_depth_mm"] == depth_mm


@pytest.mark.parametrize(
    ("fields", "message"),
    [
        ("thru = true\ndepth = 5.0\n", "either thru = true or has a depth"),
        ("", "either thru = true or has a depth"),
        ("depth = -1.0\n", "depth must be positive"),
        ("thru = true\nmouth_dia_mm = 3.0\n", "has no mouth_dia_mm"),
    ],
)
def test_a_tooling_hole_declares_thru_or_a_depth(tmp_path, fields, message):
    plan = bundle_plan(tmp_path)
    text = plan.read_text(encoding="utf-8")
    start = text.index("[process_features.cr_tooling_hole]")
    body = text[start:].replace("thru = true\n", fields, 1)
    plan.write_text(text[:start] + body, encoding="utf-8")
    with pytest.raises(BadInput, match=message):
        load_bundle(plan)


def test_other_process_kinds_have_no_hole_fields(tmp_path):
    plan = copy_examples(tmp_path) / "rocker-arm" / "plan.toml"
    text = plan.read_text(encoding="utf-8")
    plan.write_text(
        text.replace('kind = "end_face"\n', 'kind = "end_face"\nthru = true\n', 1),
        encoding="utf-8",
    )
    with pytest.raises(BadInput, match="end_face process feature has no thru"):
        load_bundle(plan)


def test_the_issue_route_on_the_real_kernel(tmp_path, freecad_kernel):
    bundle = load_bundle(bundle_plan(tmp_path))
    facts = kernel.run_geometry(bundle)
    assert facts["status"] == "ok", facts.get("reason")
    assert {
        sid: {name: hole["state"] for name, hole in detail["tooling_holes"].items()}
        for sid, detail in facts["setups"].items()
    } == ROUTE
    for subject in ("S1:10", "S1:20", "S1:30", "T4:10"):
        assert facts["ops"][subject].get("reason") is None, facts["ops"][subject]
    found = rows(bundle)
    assert found["T3:cl_tooling_hole"].status == "pass"
    assert found["T5:cl_tooling_hole"].status == "error"
    assert found["T5:cr_tooling_hole"].status == "pass"


def test_a_through_hole_without_a_planned_thickness_is_not_cut(tmp_path):
    plan = bundle_plan(tmp_path)
    plan.write_text(
        plan.read_text(encoding="utf-8").replace(f"cl_tooling_hole = {THICKNESS}\n", "", 1),
        encoding="utf-8",
    )
    job = kernel.engine_job(prepared_job(load_bundle(plan)))
    (s1,) = [setup for setup in job["setups"] if setup["id"] == "S1"]
    ream = next(op for op in s1["ops"] if op["subject"] == "S1:20")
    assert "local_thickness.cl_tooling_hole is unknown" in ream["process_cut"]["reason"]


def test_the_dowel_reports_how_far_its_clearance_lets_the_work_turn_about_hub(tmp_path):
    bundle = with_states(load_bundle(bundle_plan(tmp_path)), ROUTE)
    # The entering stock's setup-frame box: the raw bar about the TA origin.
    box = [-172.5, -33.6, TOP - THICKNESS, 172.5, 42.6, TOP]
    bundle.kernel["setups"]["T3"]["stock_bbox_mm"] = box
    row = rows(bundle)["T3:cl_tooling_hole"]
    assert row.status == "pass"  # informational: the turn never changes the verdict
    (fit,) = row.numbers["locators"]
    about = {entry["locates"]: entry for entry in fit["clocking"]}
    assert set(about) == {"pivot_bore", "cr_tooling_hole"}
    hub = about["pivot_bore"]
    distance = math.hypot(CL[0] - HUB[0], CL[1] - HUB[1])
    assert hub["distance_mm"] == pytest.approx(distance)
    assert hub["angle_rad"] == pytest.approx((6.53 - PIN) / distance)
    # The farthest box corner from HUB moves the most.
    assert hub["max_shift_mm"] == pytest.approx(hub["angle_rad"] * math.hypot(172.5, 42.6))


def test_the_turn_is_unknown_while_the_pin_size_is_debt(tmp_path):
    plan = bundle_plan(tmp_path)
    inventory = plan.parents[1] / "inventory" / "pedro-shop.toml"
    text = inventory.read_text(encoding="utf-8")
    start = text.index("[fixtures.test-cl-dowel]")
    inventory.write_text(
        text[:start] + text[start:].replace(MEASURED, "verify = true", 1), encoding="utf-8"
    )
    (fit,) = rows(with_states(load_bundle(plan), ROUTE))["T3:cl_tooling_hole"].numbers["locators"]
    assert {entry["angle_rad"] for entry in fit["clocking"]} == {"unknown"}


def test_a_pivot_pin_not_parallel_to_the_hole_leaves_the_turn_unknown(tmp_path):
    plan = bundle_plan(tmp_path)
    inventory = plan.parents[1] / "inventory" / "pedro-shop.toml"
    text = inventory.read_text(encoding="utf-8")
    start = text.index("[fixtures.test-hub-pin]")
    tilted = text[start:].replace("axis = [0.0, 0.0, 1.0]", "axis = [1.0, 0.0, 0.0]", 1)
    inventory.write_text(text[:start] + tilted, encoding="utf-8")
    (fit,) = rows(with_states(load_bundle(plan), ROUTE))["T3:cl_tooling_hole"].numbers["locators"]
    hub = next(entry for entry in fit["clocking"] if entry["locates"] == "pivot_bore")
    assert hub["angle_rad"] == "unknown" and "not parallel" in hub["reason"]
