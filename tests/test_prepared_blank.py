"""The squared blank a mill route prepares before S1 (docs/plan.md "Prepared blank").

The pivot-bracket example saws a flat bar and squares it in P1-P6 with six plan process
faces; S1 receives that blank. Each test perturbs the route and reads the consumer verdict.
"""

import json
import math

import pytest
from test_cli import SYNTHETIC_KERNEL, copy_examples, run_cli
from test_process_features import rules
from test_process_route import HEADER, drop_setup_key, evaluate, rewrite

from prechips.inputs import BadInput, load_bundle
from prechips.kernel import build_job, engine_job, run_geometries
from prechips.rules.prepared_blank import _axes


def bracket(tmp_path):
    return copy_examples(tmp_path) / "pivot-bracket" / "plan.toml"


def set_key(plan, table, key, value):
    """Set ``key`` in ``[table]`` (added when absent), or drop it when ``value`` is None."""
    lines = plan.read_text(encoding="utf-8").splitlines(keepends=True)
    start = next(n for n, line in enumerate(lines) if line.startswith(f"[{table}]"))
    end = next(n for n in range(start + 1, len(lines)) if HEADER.fullmatch(lines[n]))
    body = [line for line in lines[start + 1 : end] if not line.startswith(f"{key} ")]
    if value is not None:
        body.insert(0, f"{key} = {value}\n")
    lines[start + 1 : end] = body
    plan.write_text("".join(lines), encoding="utf-8")


def faces_cut_at_their_planes(bundle):
    """A kernel stand-in for every prep face cut whole at its plane: each setup hands on
    the box the route's planes trim the sawn bar to (the rule's own analytic box), so the
    route and the checks decide. Without that box, the stand-in hands on nothing."""
    object.__setattr__(bundle, "kernel", {"status": "ok", "setups": {}})
    numbers = evaluate("prepared_blank", bundle)["stock.prepared"].numbers
    spans, axes = numbers.get("received_box_mm"), _axes(bundle.plan["stock"])
    if spans is None or axes is None:
        return bundle
    lo, hi = [0.0] * 3, [0.0] * 3
    for unit, (low, high) in zip(axes, spans, strict=True):
        k = max(range(3), key=lambda i: abs(unit[i]))
        lo[k], hi[k] = (low, high) if unit[k] > 0 else (-high, -low)
    volume = math.prod(high - low for low, high in spans)
    bundle.kernel["setups"] = {
        setup["id"]: {"stock_out_bbox_mm": [*lo, *hi], "stock_out_volume_mm3": volume}
        for setup in bundle.plan["setups"]
    }
    return bundle


def blank(plan):
    bundle = faces_cut_at_their_planes(load_bundle(plan))
    return evaluate("prepared_blank", bundle)["stock.prepared"]


@pytest.mark.parametrize(
    ("stock_in", "status"),
    [
        ("P6", "pass"),
        # S1 skips P6: the seat end is faced outside the blank's lineage.
        ("P5", "error"),
        # Nothing prepares the blank: S1 would receive the sawn bar.
        ("stock", "error"),
    ],
)
def test_s1_receives_the_blank_only_after_every_face_is_made(tmp_path, stock_in, status):
    plan = bracket(tmp_path)
    text = plan.read_text(encoding="utf-8")
    plan.write_text(text.replace('stock_in = "P6"', f'stock_in = "{stock_in}"', 1), "utf-8")
    row = blank(plan)
    assert row.status == status
    if stock_in == "P6":
        assert row.numbers["received_size_mm"] == pytest.approx([34.2, 18.0, 26.2])
    if stock_in == "P5":
        assert row.numbers["made_outside_lineage"] == [
            "plan.process_features.blank_seat_end in P6 op 10"
        ]


def test_undeclared_routing_leaves_the_blank_unknown(tmp_path):
    plan = bracket(tmp_path)
    drop_setup_key(plan, "S1", "stock_in")
    assert blank(plan).status == "unknown"


@pytest.mark.parametrize(
    ("length", "status"),
    [
        ("34.2", "pass"),
        # Inside the declared ±0.02 band.
        ("34.215", "pass"),
        # The faced ends are 34.2 apart; 34.0 is outside ±0.02.
        ("34.0", "error"),
        ('"unknown"', "unknown"),
    ],
)
def test_the_faced_blank_size_is_checked_against_the_declared_size(tmp_path, length, status):
    plan = bracket(tmp_path)
    set_key(plan, "stock.prepared", "length_mm", length)
    assert blank(plan).status == status


def test_an_unknown_sawn_bar_never_passes_as_the_blank(tmp_path):
    plan = bracket(tmp_path)
    set_key(plan, "stock", "length_mm", '"unknown"')
    assert blank(plan).status == "unknown"


@pytest.mark.parametrize(
    ("key", "value", "status"),
    [
        # A 0-1 in micrometer cannot span the 34.2 length.
        ("length", '"micrometers/0-1in"', "error"),
        # Not in the shop inventory.
        ("flat", '"surface-plate-gauge"', "error"),
        # Not declared: whether the blank is square is unknown.
        ("square", None, "unknown"),
    ],
)
def test_each_blank_check_needs_a_capable_inventory_gauge(tmp_path, key, value, status):
    plan = bracket(tmp_path)
    set_key(plan, "stock.prepared.checks", key, value)
    row = blank(plan)
    assert row.status == status
    assert row.numbers["checks"][key]["status"] == status


def _slab(kernel):
    # P1 leaves 0.4 on the model -X side: the 18.0 ±0.1 section is 18.4.
    handed = kernel["setups"]["P6"]
    handed["stock_out_bbox_mm"][0] -= 0.4
    handed["stock_out_volume_mm3"] *= 18.4 / 18.0


def _gouge(kernel):
    # The box is the blank's, yet a pass took material inside it.
    kernel["setups"]["P6"]["stock_out_volume_mm3"] -= 50.0


def _unproven(kernel):
    kernel["setups"]["P6"] = {"stock_out_reason": "op P1 10: the passes are unknown"}


def _no_kernel(kernel):
    kernel.clear()
    kernel.update(status="unknown", reason="FreeCAD kernel unavailable")


@pytest.mark.parametrize(
    ("change", "status"),
    [(_slab, "error"), (_gouge, "error"), (_unproven, "unknown"), (_no_kernel, "unknown")],
)
def test_the_blank_is_the_stock_the_route_hands_on_not_the_face_planes(tmp_path, change, status):
    # The six face planes still trim the sawn bar to the declared box; only what P6
    # hands on differs.
    bundle = faces_cut_at_their_planes(load_bundle(bracket(tmp_path)))
    change(bundle.kernel)
    assert evaluate("prepared_blank", bundle)["stock.prepared"].status == status


def drop_tables(plan, prefix):
    """``plan`` without the ``[prefix]`` table and its sub-tables (absent: unchanged)."""
    kept, dropping = [], False
    for line in plan.read_text(encoding="utf-8").splitlines(keepends=True):
        header = HEADER.fullmatch(line)
        if header:
            dropping = header.group(1) == prefix or header.group(1).startswith(prefix + ".")
        if not dropping:
            kept.append(line)
    plan.write_text("".join(kept), encoding="utf-8")


@pytest.mark.parametrize(("prepared", "status"), [(None, "not_applicable"), ("unknown", "unknown")])
def test_a_blank_declared_unknown_stays_unknown(tmp_path, prepared, status):
    plan = bracket(tmp_path)
    drop_tables(plan, "stock.prepared")
    if prepared is not None:
        set_key(plan, "stock", "prepared", f'"{prepared}"')
    assert evaluate("prepared_blank", load_bundle(plan))["stock.prepared"].status == status
    if prepared is None:
        return
    out = tmp_path / "out"
    result = run_cli("check", plan, "--out", out, setup=SYNTHETIC_KERNEL)
    assert result.returncode == 4, result.stderr
    report = json.loads((out / "report.json").read_bytes())
    rows = [row for row in report["findings"] if row["rule"] == "prepared_blank"]
    assert [row["status"] for row in rows] == ["unknown"]


@pytest.mark.parametrize(
    ("resolution_in", "form", "status"),
    [
        # The DTI's resolution is unknown: whether it reads 0.02 is unknown.
        ('"unknown"', True, "unknown"),
        # 0.01 in (0.254 mm) cannot read a 0.02 mm sweep.
        ("0.01", True, "error"),
        # No limit for the sweep: what it must read is unknown.
        (None, False, "unknown"),
    ],
)
def test_each_form_check_needs_a_limit_its_gauge_resolves(tmp_path, resolution_in, form, status):
    plan = bracket(tmp_path)
    if resolution_in is not None:
        inventory = plan.parents[1] / "inventory" / "pedro-shop.toml"
        set_key(inventory, "gauges.dti", "resolution_in", resolution_in)
    if not form:
        drop_tables(plan, "stock.prepared.form_mm")
    row = blank(plan)
    assert row.status == status
    checks = row.numbers["checks"]
    assert [checks[key]["status"] for key in ("flat", "square", "parallel")] == [status] * 3


def test_round_stock_cannot_declare_a_squared_blank(tmp_path):
    plan = bracket(tmp_path)
    set_key(plan, "stock", "dia_mm", "25.4")
    with pytest.raises(BadInput, match="round or built-up"):
        load_bundle(plan)


def hold_sent(plan, setup):
    job = engine_job(build_job(load_bundle(plan)))
    return next(entry for entry in job["setups"] if entry["id"] == setup)["hold"]


@pytest.mark.parametrize(
    ("bar", "placed"),
    [
        ('"jaw-round-bar"', True),
        # A fixture that is not a round bar: the jaws cannot be placed on the work.
        ('"vise-pm-6"', False),
        ('"no-such-bar"', False),
    ],
)
def test_the_jaw_round_bar_must_resolve_before_the_vise_is_placed(tmp_path, bar, placed):
    plan = bracket(tmp_path)
    rewrite(plan, ("hold", "P2"), "jaw_bar", bar)
    hold = hold_sent(plan, "P2")
    if placed:
        assert hold["jaw_bar"]["dia_mm"] == pytest.approx(6.35)
        assert "reason" not in hold
        return
    assert "jaw_bar" not in hold
    assert hold["reason"]


_BUTTONS = '\n[fixtures.jaw-buttons]\nkind = "jaw_buttons"\nname = "two jaw buttons with spigots"\n'
_MEASURED = (
    "{{ value = {}, measured = {{ by = "
    '"example (plausible, not measured)", date = "2026-10-05", instrument = "caliper" }} }}'
)


@pytest.mark.parametrize(
    ("reference", "unmeasured", "placed"),
    [
        ('"jaw-buttons"', None, True),
        # A button whose thickness or spigot is unmeasured: where the jaws close, or
        # whether the spigot seats in the work, is unknown.
        ('"jaw-buttons"', "thickness_mm", False),
        ('"jaw-buttons"', "spigot_length_mm", False),
        # Not jaw buttons: the jaws cannot be placed on them.
        ('"jaw-round-bar"', None, False),
    ],
)
def test_jaw_buttons_must_resolve_every_measurement_before_the_vise_is_placed(
    tmp_path, reference, unmeasured, placed
):
    plan = bracket(tmp_path)
    inventory = plan.parents[1] / "inventory" / "pedro-shop.toml"
    sizes = {"dia_mm": 16.0, "thickness_mm": 3.0, "spigot_dia_mm": 12.2, "spigot_length_mm": 2.0}
    item = "".join(
        f"{key} = {_MEASURED.format(value)}\n" for key, value in sizes.items() if key != unmeasured
    )
    inventory.write_text(inventory.read_text(encoding="utf-8") + _BUTTONS + item, encoding="utf-8")
    rewrite(plan, ("hold", "P4"), "jaw_buttons", reference)
    hold = hold_sent(plan, "P4")
    if placed:
        assert hold["jaw_buttons"] == {"name": "jaw-buttons", **sizes}
        assert "reason" not in hold
        return
    assert "jaw_buttons" not in hold
    assert "jaw_buttons" in hold["reason"]


def test_a_mill_process_face_on_a_drawing_plane_never_claims_that_face(tmp_path, freecad_kernel):
    plan = bracket(tmp_path)
    before = rules(load_bundle(plan), "coverage")["coverage"]["pivot-bracket"]
    assert before.status == "pass"
    # The same S1 facing pass, now preparing a plan process face laid on the seat plane
    # (model y = 0, material on +y): it removes the same slab, yet claims no STEP face.
    rewrite(plan, ("op", "S1", 10), "feature", '"seat_plane"')
    plan.write_text(
        plan.read_text(encoding="utf-8")
        + "\n[process_features.seat_plane]\n"
        + 'kind = "end_face"\n'
        + "at = [0.0, 0.0, 9.1]\n"
        + "axis = [0.0, 1.0, 0.0]\n"
        + 'cite = ["test: a process face on the exported seat plane"]\n',
        encoding="utf-8",
    )
    after = rules(load_bundle(plan), "coverage")["coverage"]["pivot-bracket"]
    assert after.status == "error"
    assert after.numbers["unclaimed_faces"] == ["#473/ADVANCED_FACE[16]/NONE"]


def _partial(bundle):
    # P1's facing passes stop 0.4 above the face's plane.
    bundle.plan["setups"][0]["ops"][0]["to_z"] = 0.4


def _air(bundle):
    # P5's side-mill passes run 190 mm clear of the sawn right end.
    contour = bundle.plan["setups"][4]["ops"][0]["contour"]
    contour.update(
        sweep_bounds={"x": [190.0, 200.0], "y": [-20.0, 45.0], "z": [-8.5, 8.0]},
        sweep_frame="model",
    )


def _loose_bar(bundle):
    # P2's round bar, cut to 25.4, held 60 along the jaws: clear of the 38 long bar.
    bundle.plan["setups"][1]["hold"]["jaw_center_along_mm"] = 60.0
    bundle.inventory["fixtures"]["jaw-round-bar"]["length_mm"]["value"] = 25.4


@pytest.fixture(scope="module")
def prep_routes(tmp_path_factory, freecad_kernel):
    """``{case: (whole plan, its prep route)}`` after one FreeCAD batch over the routes.

    A route is the plan's setups up to the blank (S1 onward only consume it), so the
    kernel cuts the prep passes alone; the whole plan reads the route's facts."""
    examples = copy_examples(tmp_path_factory.mktemp("prep"))
    cases = {
        "bracket": ("pivot-bracket", 6, None),
        "partial": ("pivot-bracket", 6, _partial),
        "air": ("rocker-arm", 5, _air),
        "loose_bar": ("pivot-bracket", 2, _loose_bar),
    }
    bundles = {}
    for name, (folder, count, change) in cases.items():
        whole, route = (load_bundle(examples / folder / "plan.toml") for _ in range(2))
        for bundle in (whole, route) if change else ():
            change(bundle)
        route.plan["setups"] = route.plan["setups"][:count]
        bundles[name] = whole, route
    run_geometries([route for _, route in bundles.values()])
    for whole, route in bundles.values():
        object.__setattr__(whole, "kernel", route.kernel)
    return bundles


@pytest.mark.parametrize(
    ("case", "status"),
    [
        ("bracket", "pass"),
        # S1 would receive P1's 0.4 slab.
        ("partial", "error"),
        # S1 would receive the sawn 2.5 excess on the 340 length.
        ("air", "error"),
    ],
)
def test_the_blank_is_what_the_prep_passes_cut(prep_routes, case, status):
    whole, route = prep_routes[case]
    assert route.kernel["status"] == "ok", route.kernel.get("reason")
    assert evaluate("prepared_blank", whole)["stock.prepared"].status == status


def test_a_shallow_face_pass_leaves_its_slab_on_the_stock(prep_routes):
    faced = prep_routes["bracket"][1].kernel["setups"]["P1"]["stock_out_bbox_mm"]
    short = prep_routes["partial"][1].kernel["setups"]["P1"]["stock_out_bbox_mm"]
    # P1 faces the model -X side to the blank's X -9.0; stopped 0.4 high, it leaves X -9.4.
    assert faced[0] == pytest.approx(-9.0, abs=1e-3)
    assert short[0] == pytest.approx(-9.4, abs=1e-3)
    assert short[1:] == pytest.approx(faced[1:], abs=1e-3)


def test_the_vise_opens_by_the_work_plus_its_round_bar(prep_routes):
    _, route = prep_routes["bracket"]
    facts = route.kernel["setups"]["P2"]
    assert facts["jaw_separation_mm"] == pytest.approx(facts["width_mm"] + 6.35, abs=1e-3)
    assert evaluate("vise", route)["P2"].status == "pass"


def test_a_round_bar_clear_of_the_work_never_places_the_moving_jaw(prep_routes):
    _, route = prep_routes["loose_bar"]
    assert route.kernel["setups"]["P2"]["reasons"]
    assert evaluate("vise", route)["P2"].status == "unknown"
    assert {row.status for row in evaluate("fixture_interference", route).values()} != {"pass"}
