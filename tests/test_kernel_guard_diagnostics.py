"""Native guard failures retain their cause without requiring a FreeCAD process."""

import ast
import math
from types import SimpleNamespace

from test_kernel_geometry import ENGINE


def test_window_guard_reports_failed_arc_offset_without_returning_geometry():
    tree = ast.parse(ENGINE.read_text(encoding="utf-8"))
    rounding = next(
        node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "_r"
    )
    setup = next(
        node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "_Setup"
    )
    guard = next(
        node
        for node in setup.body
        if isinstance(node, ast.FunctionDef) and node.name == "_window_guard"
    )
    solid = object()
    source = SimpleNamespace(Solids=[solid])
    offset_calls = []

    def failed_offset(shape, leave):
        offset_calls.append((shape, leave))
        raise RuntimeError("native arc offset failed")

    namespace = {
        "math": math,
        "_box_shape": tuple,
        "_valid": lambda shape, description: shape,
        "_offset": failed_offset,
    }
    module = ast.Module(body=[rounding, guard], type_ignores=[])
    exec(compile(module, str(ENGINE), "exec"), namespace)
    protected = SimpleNamespace(common=lambda box: source)
    pieces, why = namespace["_window_guard"](
        SimpleNamespace(protected=protected),
        0.25,
        (-1.23456789, -0.0, 2, 3.45678912, 4.0, 5.0),
    )

    assert offset_calls == [(solid, 0.25)]
    assert pieces is None
    assert why == (
        "protected finished material offset by its 0.25 mm rough_allowance_mm "
        "leave within [-1.234568, 0.0, 2.0, 3.456789, 4.0, 5.0] "
        "failed (arc joins: native arc offset failed)"
    )
