"""The squared blank a mill route prepares before S1 (docs/plan.md "Prepared blank").

The pivot-bracket example saws a flat bar and squares it in P1-P6 with six plan process
faces; S1 receives that blank. Each test perturbs the route and reads the consumer verdict.
"""

import pytest
from test_cli import copy_examples
from test_process_features import rules
from test_process_route import HEADER, drop_setup_key, evaluate, rewrite

from prechips.inputs import BadInput, load_bundle
from prechips.kernel import build_job, engine_job


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


def blank(plan):
    return evaluate("prepared_blank", load_bundle(plan))["stock.prepared"]


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
