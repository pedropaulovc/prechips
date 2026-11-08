"""Exercise the production native corner classifier offline with analytic stand-ins."""

import ast
from pathlib import Path
from types import SimpleNamespace

import pytest

from prechips.rules.internal_corner_radius import admits

ENGINE = Path(__file__).parents[1] / "src/prechips/kernel/freecad_job.py"


class Axis:
    def __init__(self, parallel=True):
        self.parallel = parallel

    def dot(self, other):
        return 1 if self.parallel else 0


class Cylinder:
    def __init__(self, radius, parallel=True):
        self.Radius = radius
        self.Axis = Axis(parallel)


class Plane:
    pass


@pytest.fixture
def classify():
    tree = ast.parse(ENGINE.read_text(encoding="utf-8"))
    setup = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "_Setup")
    method = next(node for node in setup.body if isinstance(node, ast.FunctionDef) and node.name == "_corners")
    namespace = {
        "Part": SimpleNamespace(Plane=Plane, Cylinder=Cylinder),
        "Z": object(),
        "PARALLEL": 0.999,
        "_cylinder_concave": lambda face: face.concave,
        "_curved_concave": lambda part, face: True,
        "_shared_edges": lambda faces, indices: [],
        "_r": lambda value: round(value, 6),
    }
    exec(compile(ast.Module(body=[method], type_ignores=[]), str(ENGINE), "exec"), namespace)
    return namespace["_corners"], namespace


def scene(mapping=(0,)):
    return SimpleNamespace(
        finished_face_count=3,
        finished=object(),
        owner=SimpleNamespace(process_planes=set(), labels=["own", "other", "outer"]),
        faces=[
            SimpleNamespace(Surface=Cylinder(6.1341), concave=True),
            SimpleNamespace(Surface=Cylinder(2), concave=True),
            SimpleNamespace(Surface=Cylinder(15), concave=False),
        ],
        _feature_indices=lambda name, member: list(mapping) if name == "journal" else "unknown",
    )


def test_hone_own_nominal_wall_does_not_reject_positive_band_working_radius(classify):
    corners, _ = classify
    assert corners(scene(), [0], op={"do": "hone", "feature": "journal"}) == []
    assert corners(scene(), [0], op={"do": "mill", "feature": "journal"}) == [6.1341]
    assert not admits(6.1341, 6.143625, "unknown")


def test_hone_claiming_unrelated_internal_corner_still_fails(classify):
    corners, _ = classify
    radii = corners(scene(), [0, 1, 2], op={"do": "hone", "feature": "journal"})
    assert radii == [2]
    assert not all(admits(radius, 6.143625, "unknown") for radius in radii)


@pytest.mark.parametrize("mapping", [(), (1,)])
def test_unmatched_bore_cannot_gain_hone_exemption(classify, mapping):
    corners, _ = classify
    assert corners(scene(mapping), [0], op={"do": "hone", "feature": "journal"}) == [6.1341]


def test_unknown_ownership_and_transverse_wall_remain_unresolved(classify):
    corners, _ = classify
    assert corners(scene(), [0], op={"do": "hone", "feature": "unknown"}) == [6.1341]
    value = scene()
    value.faces[0].Surface.Axis = Axis(False)
    assert "not the tool axis" in corners(value, [0], op={"do": "hone", "feature": "journal"})


def test_sharp_edges_and_concave_non_cylinders_are_not_hone_exempt(classify):
    corners, namespace = classify
    namespace.update(
        _shared_edges=lambda faces, indices: [(object(), 0, 1)],
        _edge_direction=lambda edge: "vertical",
        _concave_edge=lambda part, edge, a, b: True,
    )
    assert 0 in corners(scene(), [0, 1], op={"do": "hone", "feature": "journal"})
    namespace["_shared_edges"] = lambda faces, indices: []
    value = scene()
    value.faces[0].Surface = SimpleNamespace()
    assert "concave SimpleNamespace" in corners(value, [0], op={"do": "hone", "feature": "journal"})
