"""A raw radial-reduction upper bound is not a certain multipass reach failure."""

import ast
import math
from types import SimpleNamespace

import pytest
from test_kernel_geometry import ENGINE

from prechips.rules import reach
from prechips.rules.geometry_common import TURNING, TURNING_HOLDER_KEYS

_BASIS = "entry_stock_radial_upper_bound"


def _row(monkeypatch, *, depth=34.045, hits=0, basis=_BASIS, turning=True, debts=()):
    detail = {"reach_depth_mm": depth, "holder_wall_hits": hits}
    if basis is not None:
        detail["reach_depth_basis"] = basis
    inputs = {
        **dict.fromkeys(TURNING_HOLDER_KEYS, 20.0),
        "projection_mm": 20.0,
        "shank_width_mm": 10.0,
        "head_len_mm": 15.0,
        "flute_len_mm": 5.0,
        "oal_mm": 20.0,
        "approach": TURNING if turning else "axial",
        "measurement_debts": list(debts),
    }
    context = (
        {"id": "S1"},
        {"op": 10, "do": "finish_turn"},
        {"status": "ok"},
        detail,
        inputs,
        [],
        None,
    )
    monkeypatch.setattr(reach, "op_contexts", lambda *args: [context])
    [row] = reach.evaluate(None)
    return row


def test_exceeded_raw_radial_bound_is_unknown_not_a_certain_oal_error(monkeypatch):
    row = _row(monkeypatch)
    assert row.status == "unknown"
    assert row.numbers["reach_depth_mm"] == 34.045
    assert row.numbers["reach_depth_basis"] == _BASIS
    assert "roughing progression is not modeled" in row.sentence


@pytest.mark.parametrize("depth", [2.0, 10.0, 34.045])
def test_known_holder_collision_remains_error_at_any_radial_bound(monkeypatch, depth):
    row = _row(monkeypatch, depth=depth, hits=1)
    assert row.status == "error"
    assert "holder intersects" in row.sentence


@pytest.mark.parametrize("depth", [2.0, 10.0, 20.0])
def test_a_bound_that_fits_still_supports_the_existing_necessary_condition(monkeypatch, depth):
    assert _row(monkeypatch, depth=depth).status == "pass"


def test_unknown_holder_clearance_does_not_turn_an_exceeded_bound_into_a_pass(monkeypatch):
    assert _row(monkeypatch, hits="unknown").status == "unknown"


@pytest.mark.parametrize("turning", [True, False])
def test_unmarked_direct_depth_retains_the_existing_oal_error(monkeypatch, turning):
    # Facing and blade plunge facts have no radial-upper-bound marker. Milling
    # also must not acquire the turning-only uncertainty semantics.
    assert _row(monkeypatch, basis=None, turning=turning).status == "error"


def test_turning_bound_marker_cannot_downgrade_milling_depth(monkeypatch):
    assert _row(monkeypatch, turning=False).status == "error"


def test_unresolved_progression_retains_exact_measurement_debt_and_citation(monkeypatch):
    debt = {
        "id": "tools.turn.projection",
        "status": "unknown",
        "reason": "installed projection must be measured",
        "cite": ["inventory.tools.turn.projection"],
    }
    row = _row(monkeypatch, debts=[debt])
    assert row.status == "unknown"
    assert row.numbers["measurements"] == [debt]
    assert debt["cite"][0] in row.cite
    assert debt["id"] in row.sentence


def test_measurement_debt_does_not_demote_a_known_holder_collision(monkeypatch):
    debt = {"id": "tools.turn.projection", "status": "unknown", "cite": []}
    assert _row(monkeypatch, hits=1, debts=[debt]).status == "error"


@pytest.fixture(scope="module")
def native_roughing_bound():
    # Exercise the actual native qualification predicate without launching FreeCAD.
    tree = ast.parse(ENGINE.read_text(encoding="utf-8"))
    names = {"_turn_roughing_bound", "_number", "_turned"}
    functions = [
        node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef) and node.name in names
    ]
    assert {node.name for node in functions} == names
    namespace = {"math": math, "TURNING": TURNING, "PLANE_TOL": 1e-6}
    exec(compile(ast.Module(body=functions, type_ignores=[]), str(ENGINE), "exec"), namespace)
    return namespace["_turn_roughing_bound"]


@pytest.mark.parametrize(
    ("action", "window", "prior_kind", "expected"),
    [
        ("rough_turn", (10.0, 0.0), None, True),
        ("rough_turn", None, None, False),
        ("rough_turn", (0.0, 0.0), None, False),
        ("finish_turn", (10.0, 0.0), None, False),
        ("finish_turn", (10.0, 0.0), "covering", True),
        ("finish_turn", (10.0, 0.0), "later", False),
        ("finish_turn", (10.0, 0.0), "other_claim", False),
        ("finish_turn", (10.0, 0.0), "partial_window", False),
        ("finish_turn", (10.0, 0.0), "unbounded", False),
        ("finish_turn", (10.0, 0.0), "facing", False),
        ("part_off", (10.0, 0.0), "covering", False),
        ("cut_to_fit", (10.0, 0.0), "covering", False),
    ],
)
def test_only_declared_bounded_roughing_qualifies_for_uncertainty(
    native_roughing_bound, action, window, prior_kind, expected
):
    op = {"approach": TURNING, "do": action, "indices": [1]}
    if window is not None:
        op.update(z_from=window[0], z_to=window[1])
    prior = {
        "approach": TURNING,
        "do": "rough_turn",
        "indices": [1],
        "z_from": 10.0,
        "z_to": 0.0,
    }
    if prior_kind == "other_claim":
        prior["indices"] = [2]
    elif prior_kind == "partial_window":
        prior["z_from"] = 5.0
    elif prior_kind == "unbounded":
        del prior["z_to"]
    elif prior_kind == "facing":
        prior["to_z"] = 0.0
    ops = [op] if prior_kind is None else [prior, op]
    if prior_kind == "later":
        ops.reverse()
    context = SimpleNamespace(ops=ops, _indices=lambda item: item["indices"])
    assert native_roughing_bound(context, op, [1]) is expected


def test_facing_cannot_acquire_roughing_uncertainty(native_roughing_bound):
    op = {"do": "rough_turn", "z_from": 10.0, "z_to": 0.0, "to_z": 0.0}
    assert native_roughing_bound(SimpleNamespace(ops=[op]), op, [1]) is False
