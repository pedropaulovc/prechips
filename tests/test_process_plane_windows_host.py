"""Finite plan preparation planes, whole-plane unions and surviving touch coverage."""

from copy import deepcopy
from types import SimpleNamespace

import pytest

from prechips.process_features import arriving_bounds, feature_definitions
from prechips.rules import tip_endpoints
from prechips.rules.coordinates import frame_point
from prechips.rules.zero_recipe.faces import _tops

MODEL = {
    "origin": [0.0, 0.0, 0.0],
    "x": [1.0, 0.0, 0.0],
    "y": [0.0, 1.0, 0.0],
    "z": [0.0, 0.0, 1.0],
}
ROTATED = {
    "origin": [13.0, -7.0, 0.25],
    "x": [0.8, 0.6, 0.0],
    "y": [-0.6, 0.8, 0.0],
    "z": [0.0, 0.0, 1.0],
}
FLIPPED = {
    "origin": [0.0, 16.0, 0.0],
    "x": [-1.0, 0.0, 0.0],
    "y": [0.0, 1.0, 0.0],
    "z": [0.0, 0.0, -1.0],
}
LEVEL = 1.2446


def bounded_bundle(frame=MODEL, level=LEVEL):
    setup = {
        "id": "S1",
        "stock_in": "stock",
        "frame": "cut",
        "stock_state": {
            "top_z": 3.0,
            "top_feature": "plane",
            "entry_z": {"plane": 3.0},
        },
        "ops": [],
    }
    plan = {
        "stock": {
            "origin_mm": [-177.0, 0.0, -3.0],
            "axis": [1.0, 0.0, 0.0],
            "section_axis": [0.0, 1.0, 0.0],
            "length_mm": 354.0,
            "section_mm": [16.0, 6.0],
        },
        "process_features": {
            "plane": {
                "kind": "end_face",
                "at": [0.0, 8.0, level],
                "axis": [0.0, 0.0, -1.0 if level > 0 else 1.0],
                "cite": ["test-owned stock preparation, not a finished surface"],
            }
        },
        "setups": [setup],
    }
    bundle = SimpleNamespace(
        plan=plan,
        features={"units": "mm", "frames": {"model": deepcopy(MODEL), "cut": deepcopy(frame)}},
        feature_definitions=feature_definitions(plan, {}, "mm"),
        kernel={},
    )
    return bundle, setup


def cut(setup, x, y=(0.0, 16.0), *, floor=LEVEL, feature="plane", z=(-3.0, 3.0)):
    op = {
        "op": 10 * (len(setup["ops"]) + 1),
        "do": "face",
        "feature": feature,
        "to_z": floor,
        "stock_removal_bounds": {"x": list(x), "y": list(y), "z": list(z)},
    }
    setup["ops"].append(op)
    return op


@pytest.mark.parametrize("frame,level", [(MODEL, LEVEL), (ROTATED, LEVEL), (FLIPPED, -LEVEL)])
def test_finite_process_plane_uses_actual_plane_and_setup_frame(frame, level):
    bundle, setup = bounded_bundle(frame, level)
    target = bundle.feature_definitions["plane"]
    floor = frame_point([0.0, 8.0, level], frame)[2]
    full = tip_endpoints._setup_footprint(bundle, setup, target)
    # Bisect the actual polygon in setup X. This remains finite after arbitrary
    # in-plane rotation, translation, and a right-handed turned-over setup.
    middle = sum(full[0]) / 2
    op = cut(
        setup,
        [full[0][0] - 5, middle],
        [full[1][0] - 5, full[1][1] + 5],
        floor=floor,
        z=[floor - 1, floor + 1],
    )
    finite = tip_endpoints._setup_footprint(bundle, setup, target, op=op)
    assert finite[0] == pytest.approx([full[0][0], middle])
    assert full[1][0] <= finite[1][0] <= finite[1][1] <= full[1][1]
    assert tip_endpoints.cut_coverage(bundle, setup, op, target) == "partial"
    assert tip_endpoints.process_face_union(bundle, setup, target)[0] == "partial"
    # A second adjacent half covers the polygon itself, not just its bounding box.
    cut(
        setup,
        [middle, full[0][1] + 5],
        [full[1][0] - 5, full[1][1] + 5],
        floor=floor,
        z=[floor - 1, floor + 1],
    )
    assert tip_endpoints.process_face_union(bundle, setup, target)[0] == "whole"


def test_disjoint_ear_windows_never_produce_a_whole_touch_or_global_entry():
    bundle, setup = bounded_bundle()
    left = cut(setup, [-182.0, -150.0])
    cut(setup, [150.0, 182.0])
    target = bundle.feature_definitions["plane"]
    # Overrun permission extends past raw stock; it creates no material there.
    assert tip_endpoints._setup_footprint(bundle, setup, target, op=left) == [
        [-177.0, -150.0],
        [0.0, 16.0],
    ]
    assert tip_endpoints.process_face_union(bundle, setup, target)[0] == "partial"
    states = list(tip_endpoints.stock_states(bundle, setup))
    assert states[-1][2]["top_z"] == 3.0
    assert states[-1][2]["entry_z"] == {"plane": 3.0}
    assert _tops(bundle, setup, states)[-1][0] == "unknown"
    debts = []
    assert tip_endpoints._producer(bundle, setup, LEVEL, "plane", 2, None, debts=debts) == "unknown"
    assert "gap" in " ".join(debts)


@pytest.mark.parametrize("gap", [0.0, 0.01])
def test_adjacent_window_union_advances_top_only_when_no_gap_remains(gap):
    bundle, setup = bounded_bundle()
    cut(setup, [-177.0, -150.0])
    cut(setup, [-150.0 + gap, 150.0])
    cut(setup, [150.0, 177.0])
    target = bundle.feature_definitions["plane"]
    coverage, maker = tip_endpoints.process_face_union(bundle, setup, target)
    states = list(tip_endpoints.stock_states(bundle, setup))
    if gap:
        assert coverage == "partial" and maker is None
        assert states[-1][2]["top_z"] == 3.0
        assert _tops(bundle, setup, states)[-1][0] == "unknown"
    else:
        assert coverage == "whole" and maker == (setup, setup["ops"][-1])
        assert states[-1][2]["top_z"] == LEVEL
        assert states[-1][2]["top_from"] == "S1 op 30 to_z"
        assert states[-1][2]["entry_z"] == {"plane": LEVEL}
        assert _tops(bundle, setup, states)[-1] == (LEVEL, 3)


def test_lineage_union_maps_distinct_process_features_between_rotated_setups():
    bundle, first = bounded_bundle()
    cut(first, [-150.0, 150.0])
    # A 180-degree in-plane rotation puts the ears on opposite setup X sides.
    frame = {**deepcopy(MODEL), "x": [-1.0, 0.0, 0.0], "y": [0.0, -1.0, 0.0]}
    bundle.features["frames"]["reverse"] = frame
    later = {
        "id": "S2",
        "stock_in": "S1",
        "frame": "reverse",
        "stock_state": {"top_z": 3.0, "top_feature": "plane"},
        "ops": [],
    }
    bundle.plan["setups"].append(later)
    ear = deepcopy(bundle.feature_definitions["plane"])
    ear["preparation"]["id"] = "ears"
    bundle.feature_definitions["ears"] = ear
    cut(later, [-177.0, -150.0], [-16.0, 0.0], feature="ears")
    cut(later, [150.0, 177.0], [-16.0, 0.0], feature="ears")
    target = bundle.feature_definitions["plane"]
    assert tip_endpoints.process_face_union(bundle, later, target, 1)[0] == "partial"
    assert tip_endpoints.process_face_union(bundle, later, target, 2)[0] == "whole"
    states = list(tip_endpoints.stock_states(bundle, later))
    assert states[-1][2]["top_z"] == LEVEL
    assert _tops(bundle, later, states)[-1] == (LEVEL, 2)


def test_unequal_floor_and_keep_out_never_fill_a_gap():
    bundle, setup = bounded_bundle()
    cut(setup, [-177.0, 0.0])
    wrong = deepcopy(bundle.feature_definitions["plane"])
    wrong["at"][2] = LEVEL - 0.1
    wrong["bounds"]["z"] = [LEVEL - 0.1, LEVEL - 0.1]
    wrong["preparation"]["id"] = "lower"
    bundle.feature_definitions["lower"] = wrong
    cut(setup, [0.0, 177.0], floor=LEVEL - 0.1, feature="lower")
    assert (
        tip_endpoints.process_face_union(bundle, setup, bundle.feature_definitions["plane"])[0]
        != "whole"
    )
    setup["ops"].pop()
    island = cut(setup, [0.0, 177.0])
    island["contour"] = {"keep_out": [{"at": [80.0, 8.0], "dia_mm": 10.0}]}
    # Unknown cutter radius is debt, never a fictitious filled half-plane.
    bundle.inventory = {"tools": {}}
    assert (
        tip_endpoints.process_face_union(bundle, setup, bundle.feature_definitions["plane"])[0]
        == "unknown"
    )


@pytest.mark.parametrize(
    "failure",
    [
        {"claimed_indices": "unknown"},
        {"reason": "finite process window unresolved"},
        {"stock_reason": "upstream cut refused"},
        {"tool_hits": 1},
        {"holder_hits": 1},
    ],
)
def test_native_refusal_or_real_clamp_collision_cannot_be_repaired_by_authored_bounds(failure):
    bundle, setup = bounded_bundle()
    cut(setup, [-177.0, 0.0])
    cut(setup, [0.0, 177.0])
    good = {"claimed_indices": [1], "sample_count": 4, "tool_hits": 0, "holder_hits": 0}
    bundle.kernel = {"status": "ok", "ops": {"S1:10": good, "S1:20": dict(good)}}
    assert (
        tip_endpoints.process_face_union(bundle, setup, bundle.feature_definitions["plane"])[0]
        == "whole"
    )
    bundle.kernel["ops"]["S1:20"].update(failure)
    assert (
        tip_endpoints.process_face_union(bundle, setup, bundle.feature_definitions["plane"])[0]
        == "unknown"
    )
    states = list(tip_endpoints.stock_states(bundle, setup))
    assert states[-1][2]["top_z"] == "unknown"


@pytest.mark.parametrize(
    "native",
    [
        {"status": "ok", "ops": {}},
        {"status": "ok", "ops": {"S1:10": {}}},
        {"status": "error", "reason": "native geometry unavailable"},
    ],
)
def test_supplied_missing_or_unusable_native_packet_stays_debt(native):
    bundle, setup = bounded_bundle()
    cut(setup, [-177.0, 177.0])
    target = bundle.feature_definitions["plane"]
    assert tip_endpoints.process_face_union(bundle, setup, target)[0] == "whole"
    bundle.kernel = native
    assert tip_endpoints.process_face_union(bundle, setup, target)[0] == "unknown"


def test_finished_width_and_point_normal_never_replace_the_raw_stock_footprint():
    bundle, setup = bounded_bundle()
    op = cut(setup, [-175.0, 175.0])
    target = bundle.feature_definitions["plane"]
    assert tip_endpoints.process_face_union(bundle, setup, target)[0] == "partial"
    target.pop("bounds")
    debts = []
    assert tip_endpoints._setup_footprint(bundle, setup, target, debts, op=op) is None
    assert tip_endpoints.process_face_union(bundle, setup, target)[0] == "unknown"
    assert debts


@pytest.mark.parametrize(
    "region,z,floor",
    [
        ([190.0, 200.0], [-3.0, 3.0], LEVEL),
        ([177.0, 150.0], [-3.0, 3.0], LEVEL),
        ([-177.0, -150.0], [2.0, 3.0], LEVEL),
        ([-177.0, -150.0], [-3.0, 3.0], 0.0),
        ([-177.0, -177.0], [-3.0, 3.0], LEVEL),
        ([-177.0, -150.0], [LEVEL, LEVEL], LEVEL),
    ],
)
def test_empty_malformed_unreached_or_misplaced_window_has_no_finite_footprint(region, z, floor):
    bundle, setup = bounded_bundle()
    op = cut(setup, region, z=z, floor=floor)
    debts = []
    assert (
        tip_endpoints._setup_footprint(
            bundle, setup, bundle.feature_definitions["plane"], debts, op=op
        )
        is None
    )
    assert debts


def test_arriving_bounds_never_apply_a_partial_preparation_plane_as_infinite_trim():
    bundle, setup = bounded_bundle()
    cut(setup, [-177.0, -150.0])
    cut(setup, [150.0, 177.0])
    later = {"id": "S2", "stock_in": "S1", "frame": "cut", "ops": []}
    bundle.plan["setups"].append(later)
    # A perpendicular process plane spans the stock thickness. Partial facing of
    # the upper ears cannot trim its entire Z span.
    end = {
        "kind": "end_face",
        "frame": "model",
        "at": [177.0, 8.0, 0.0],
        "axis": [-1.0, 0.0, 0.0],
        "bounds": {"x": [177.0, 177.0], "y": [0.0, 16.0], "z": [-3.0, 3.0]},
        "preparation": {"id": "end", "kind": "end_face"},
    }
    assert arriving_bounds(bundle, later, end)["z"] == [-3.0, 3.0]
    cut(setup, [-150.0, 150.0])
    assert arriving_bounds(bundle, later, end)["z"] == [-3.0, LEVEL]


def test_finished_face_coverage_is_not_replaced_by_a_process_union():
    bundle, setup = bounded_bundle()
    cut(setup, [-177.0, 0.0])
    op = cut(setup, [0.0, 177.0])
    finished = {
        "kind": "face",
        "frame": "model",
        "bounds": {"x": [-177.0, 177.0], "y": [0.0, 16.0], "z": [LEVEL, LEVEL]},
    }
    assert tip_endpoints._local_cover(bundle, setup, op, finished, 2) == "partial"
    assert tip_endpoints.cut_coverage(bundle, setup, op, finished) == "partial"


def native_central_and_process_ears():
    bundle, first = bounded_bundle()
    bundle.feature_definitions["central"] = {
        "kind": "face",
        "frame": "model",
        "faces": ["Fcentral"],
    }
    cut(first, [-152.0, 152.0], feature="central")
    later = {
        "id": "S2",
        "stock_in": "S1",
        "frame": "cut",
        "stock_state": {"top_z": 3.0},
        "ops": [],
    }
    bundle.plan["setups"].append(later)
    cut(later, [-177.0, -150.0])
    cut(later, [150.0, 177.0])
    good = {"claimed_indices": [0], "sample_count": 4, "tool_hits": 0, "holder_hits": 0}
    bundle.kernel = {
        "status": "ok",
        "mapping": {"Fcentral": 0},
        "faces": [
            {"index": 0, "kind": "Plane", "bbox_mm": [-149.0, 1.0, LEVEL, 149.0, 15.0, LEVEL]}
        ],
        "ops": {"S1:10": dict(good), "S2:10": dict(good), "S2:20": dict(good)},
    }
    return bundle, first, later


def test_native_proven_central_clearing_and_process_ears_complete_the_raw_plane():
    bundle, first, later = native_central_and_process_ears()
    native = bundle.feature_definitions["central"]
    target = bundle.feature_definitions["plane"]
    assert tip_endpoints.cut_coverage(bundle, first, first["ops"][0], native) == "whole"
    assert tip_endpoints.process_face_union(bundle, later, target, 1)[0] == "partial"
    assert tip_endpoints.process_face_union(bundle, later, target, 2)[0] == "whole"
    states = list(tip_endpoints.stock_states(bundle, later))
    assert states[-1][2]["top_z"] == LEVEL
    assert _tops(bundle, later, states)[-1] == (LEVEL, 2)
    # The central native bbox is smaller than the raw strip. Its accepted multipass
    # clearing box, not a fictitious finished-face rectangle, joins the finite ears.
    first["ops"][0]["stock_removal_bounds"]["y"] = [0.0, 15.5]
    assert tip_endpoints.process_face_union(bundle, later, target)[0] == "partial"


@pytest.mark.parametrize(
    "failure", ["missing-native", "missing-op", "refused", "profile", "wrong-floor"]
)
def test_native_central_contribution_requires_successful_bounded_facing_on_the_actual_plane(
    failure,
):
    bundle, first, later = native_central_and_process_ears()
    if failure == "missing-native":
        bundle.kernel = {}
    elif failure == "missing-op":
        bundle.kernel["ops"].pop("S1:10")
    elif failure == "refused":
        bundle.kernel["ops"]["S1:10"]["stock_removal_error"] = "bounded removal refused"
    elif failure == "profile":
        first["ops"][0]["do"] = "profile"
    else:
        first["ops"][0]["to_z"] = LEVEL - 0.1
        bundle.kernel["faces"][0]["bbox_mm"][2] = LEVEL - 0.1
        bundle.kernel["faces"][0]["bbox_mm"][5] = LEVEL - 0.1
    assert (
        tip_endpoints.process_face_union(bundle, later, bundle.feature_definitions["plane"])[0]
        != "whole"
    )


@pytest.mark.parametrize(
    "second", [(150.0, 177.0), (-160.0, -140.0)], ids=["opposite-ear", "overlap"]
)
def test_operation_local_start_reuses_proven_arriving_top_only_in_an_untouched_window(
    monkeypatch, second
):
    from prechips import kernel
    from prechips.rules import coordinates
    from prechips.rules.zero_recipe import native

    bundle, setup = bounded_bundle()
    cut(setup, [-177.0, -150.0])
    current = cut(setup, second)
    current["doc_mm"] = 0.5
    good = {"claimed_indices": [1], "sample_count": 4, "tool_hits": 0, "holder_hits": 0}
    bundle.kernel = {"status": "ok", "ops": {"S1:10": dict(good), "S1:20": dict(good)}}
    monkeypatch.setattr(kernel, "_top_pickup_specs", lambda setup: [("initial", {}, 0)])
    monkeypatch.setattr(
        native,
        "top_pickup_evidence",
        lambda *args: {
            "status": "pass",
            "resolved_contact": {"plane_mm": 3.0},
        },
    )
    monkeypatch.setattr(coordinates, "dro_grid", lambda *args: (0.01, 2))
    # Isolate the reported seam: the global carry/standing read is unresolved after
    # a partial cut. A disjoint current window can retain its earlier proven reading.
    monkeypatch.setattr(tip_endpoints, "_operative_z", lambda *args, **kwargs: "unknown")
    reader = tip_endpoints.top_reader(bundle, setup)
    assert reader(3.0, 0) == 3.0
    states = list(tip_endpoints.stock_states(bundle, setup))
    record = coordinates._z_levels(
        current,
        states[1][1],
        {},
        [],
        bundle.feature_definitions,
        (0.01, 2),
        "mm",
        lambda: reader(3.0, 1),
    )
    assert record["start_z"] == 3.0
    if second[0] > 0:
        assert record["dro_start_z"] == 3.0
        assert isinstance(record["levels"], list)
    else:
        assert record["dro_start_z"] == "unknown"
        assert record["levels"] == "unknown"
    # No local pass recipe manufactures a uniform top or full touch from two ears.
    assert _tops(bundle, setup, states)[-1][0] == "unknown"
    assert (
        tip_endpoints.process_face_union(bundle, setup, bundle.feature_definitions["plane"])[0]
        == "partial"
    )


def test_untouched_window_does_not_repair_a_failed_initial_touch_or_native_cut(monkeypatch):
    from prechips import kernel
    from prechips.rules import coordinates
    from prechips.rules.zero_recipe import native

    bundle, setup = bounded_bundle()
    cut(setup, [-177.0, -150.0])
    cut(setup, [150.0, 177.0])
    good = {"claimed_indices": [1], "sample_count": 4, "tool_hits": 0, "holder_hits": 0}
    bundle.kernel = {"status": "ok", "ops": {"S1:10": dict(good), "S1:20": dict(good)}}
    monkeypatch.setattr(kernel, "_top_pickup_specs", lambda setup: [("initial", {}, 0)])
    monkeypatch.setattr(coordinates, "dro_grid", lambda *args: (0.01, 2))
    monkeypatch.setattr(tip_endpoints, "_operative_z", lambda *args, **kwargs: "unknown")
    monkeypatch.setattr(native, "top_pickup_evidence", lambda *args: {"status": "unknown"})
    assert tip_endpoints.top_reader(bundle, setup)(3.0, 1) == "unknown"
    monkeypatch.setattr(
        native,
        "top_pickup_evidence",
        lambda *args: {
            "status": "pass",
            "resolved_contact": {"plane_mm": 3.0},
        },
    )
    bundle.kernel["ops"]["S1:10"]["stock_removal_error"] = "ear cut refused"
    assert tip_endpoints.top_reader(bundle, setup)(3.0, 1) == "unknown"
