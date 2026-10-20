"""Exact OCC footprint/newness controls that cannot all reach a retained partition.

The end-to-end registered route lives in ``test_batch_native.py``. Here actual
independently authored B-reps exercise the pure face witness, including target
loss that correctly prevents the normal builder from publishing named outputs.
No certificate, accepted output record, or native success payload is fabricated.
"""

import math

import pytest
from test_kernel_retained_outputs import _probe

BAND = (10.0, 13.175)
WIDTH = BAND[1] - BAND[0]
AREA = 36.0

_NATIVE = r"""
import os, sys
import Part
from FreeCAD import Vector as V
sys.path.insert(0, os.path.dirname(os.environ["RETAINED_ENGINE"]))
from saw_face_credit import _certify_face, _difference

band = [10.0, 13.175]
width = band[1] - band[0]
stock = Part.makeBox(12, 12, 20)
kerf = Part.makeBox(12, 12, width, V(0, 0, band[0]))
after = stock.cut(kerf)
target = Part.makeBox(6, 6, 6, V(2, 2, 4))

def top(shape):
    matches = [
        face for face in shape.Faces
        if abs(face.BoundBox.ZMin - 10) < 1e-7
        and abs(face.BoundBox.ZMax - 10) < 1e-7
    ]
    assert len(matches) == 1
    return matches[0]

face = top(target)
out = {}

def measure(name, before, remaining, target_face):
    removed = before.cut(remaining)
    children = sorted(remaining.Solids, key=lambda child: child.BoundBox.ZMin)
    assert children
    child = children[0]
    assert all(shape.isValid() for shape in (before, remaining, removed, child, target_face))
    # Only the selected side is an input. Every measurement/status below comes
    # from the actual helper or its native geometry exception, never a fixture cert.
    row = {"side": "below"}
    try:
        _certify_face(None, before, removed, child, target_face, row, band)
    except ValueError as exc:
        row.update(status="unknown", reasons=[str(exc)])
    out[name] = {
        "measurement": row,
        "before_volume_mm3": before.Volume,
        "after_volume_mm3": remaining.Volume,
        "removed_volume_mm3": removed.Volume,
        "actual_children": len(children),
        "target_area_mm2": target_face.Area,
        "target_bbox_mm": [
            target_face.BoundBox.XMin, target_face.BoundBox.YMin, target_face.BoundBox.ZMin,
            target_face.BoundBox.XMax, target_face.BoundBox.YMax, target_face.BoundBox.ZMax,
        ],
    }

measure("whole-rectangle", stock, after, face)

# Real trim loops, not a bounding rectangle or a tessellated/sample surrogate.
hole = Part.makeCylinder(1.2, 22, V(5, 5, -1))
ring_stock = stock.cut(hole)
ring_target = target.cut(hole)
measure("trimmed-hole", ring_stock, ring_stock.cut(kerf), top(ring_target))
concave_target = target.cut(Part.makeBox(3, 3, 6, V(5, 5, 4)))
measure("concave-footprint", stock, after, top(concave_target))

# An off-centre circular recess loses less than 0.2% of the footprint. Plane,
# bbox, centre and almost every sample still look correct; exact area does not.
pocket = Part.makeCylinder(0.15, 0.2, V(2.7, 3.1, 9.9))
measure("partial-boundary", stock, after.cut(pocket), face)

# The lower child's whole face exists, but some/all was already a stock face.
for name, length in (("partly-preexisting", 3), ("fully-preexisting", 6)):
    notch = Part.makeBox(length, 6, width, V(2, 2, 10))
    notched = stock.cut(notch)
    measure(name, notched, notched.cut(kerf), face)

# No old boundary at Z10: only a cavity further out in the actual kerf band.
# A short outward witness would miss this preexisting air completely.
for name, z, depth in (("existing-air", 11, 1), ("thin-existing-air", 12.9, 0.02)):
    cavity = Part.makeBox(6, 6, depth, V(2, 2, z))
    hollow = stock.cut(cavity)
    measure(name, hollow, hollow.cut(kerf), face)

# A tangent kerf meets only the target's edge, never its whole trimmed area.
tangent = Part.makeBox(4, 12, width, V(8, 0, 10))
measure("tangency", stock, stock.cut(tangent), face)

# A real two-child split with a much narrower removal cannot stand in for the
# full registered cutting band even though its lower face is exactly at Z10.
shallow = Part.makeBox(12, 12, 0.1, V(0, 0, 10))
measure("short-removed-column", stock, stock.cut(shallow), face)

# Keep a real top skin and its complete Z10 face, but remove material inside
# the 0.001-mm inward witness. Surface coincidence alone must not pass.
inward_void = Part.makeBox(6, 6, 0.0005, V(2, 2, 9.99925))
measure("inward-air", stock, after.cut(inward_void), face)

# Independent common measures distinguish a truly empty remainder from full
# or partial missing material. All operands and outputs are actual OCC shapes.
volume = Part.makeBox(6, 6, 2, V(2, 2, 10))
partial_face = top(Part.makeBox(3, 6, 6, V(2, 2, 4)))
far_face = top(Part.makeBox(6, 6, 6, V(20, 2, 4)))
out["boolean_measures"] = {}
for name, shape, within, dimension in (
    ("area-full", face, face.copy(), "Area"),
    ("area-partial", face, partial_face, "Area"),
    ("area-disjoint", face, far_face, "Area"),
    ("volume-full", volume, volume.copy(), "Volume"),
    ("volume-partial", volume, Part.makeBox(3, 6, 2, V(2, 2, 10)), "Volume"),
    ("volume-disjoint", volume, Part.makeBox(6, 6, 2, V(20, 2, 10)), "Volume"),
):
    remainder, missing = _difference(shape, within, dimension)
    common = shape.common(within)
    out["boolean_measures"][name] = {
        "original": getattr(shape, dimension),
        "missing": missing,
        "common": getattr(common, dimension),
        "remainder": getattr(remainder, dimension),
    }
"""


@pytest.fixture(scope="module")
def saw_face_geometry(tmp_path_factory, freecad_kernel):
    return _probe(_NATIVE, tmp_path_factory.mktemp("saw-face-footprints"), freecad_kernel)


def _measurement(saw_face_geometry, name, *, passing=False):
    case = saw_face_geometry[name]
    row = case["measurement"]
    assert row["status"] == ("pass" if passing else "unknown"), case
    if passing:
        assert row["reasons"] == [], case
    else:
        assert row["reasons"], case
    assert row["surface"] == "plane"
    assert row["normal"] == [0, 0, 1]
    assert row["plane_z_mm"] == pytest.approx(BAND[0], abs=1e-6)
    assert row["cutting_band_mm"] == pytest.approx(BAND, abs=1e-6)
    assert 0 <= row["plane_error_mm"] <= 1e-6
    assert row["area_mm2"] == pytest.approx(case["target_area_mm2"], abs=1e-6)
    assert row["area_tolerance_mm2"] == pytest.approx(max(1e-6, row["area_mm2"] * 1e-6))
    assert row["volume_tolerance_mm3"] == pytest.approx(max(1e-6, row["area_mm2"] * WIDTH * 1e-6))
    assert row["outward_column_volume_mm3"] == pytest.approx(row["area_mm2"] * WIDTH, abs=1e-6)
    assert row["inward_column_volume_mm3"] == pytest.approx(row["area_mm2"] * 1e-3, abs=1e-6)
    assert case["before_volume_mm3"] - case["after_volume_mm3"] == pytest.approx(
        case["removed_volume_mm3"], abs=1e-6
    )
    return case, row


@pytest.mark.parametrize(
    "name,area",
    [
        ("whole-rectangle", AREA),
        ("trimmed-hole", AREA - math.pi * 1.2**2),
        ("concave-footprint", AREA - 3 * 3),
    ],
)
def test_exact_native_whole_trimmed_footprints_include_holes_and_concavities(
    saw_face_geometry, name, area
):
    case, row = _measurement(saw_face_geometry, name, passing=True)
    assert case["actual_children"] == 2
    assert case["target_bbox_mm"] == pytest.approx([2, 2, 10, 8, 8, 10], abs=1e-6)
    assert row["area_mm2"] == pytest.approx(area, abs=1e-6)
    for metric in ("boundary_uncovered_area_mm2", "preexisting_boundary_area_mm2"):
        assert 0 <= row[metric] <= row["area_tolerance_mm2"], row
    for metric in (
        "outward_missing_before_mm3",
        "outward_missing_removed_mm3",
        "inward_missing_child_mm3",
    ):
        assert 0 <= row[metric] <= row["volume_tolerance_mm3"], row


def test_exact_native_footprint_rejects_small_off_centre_missing_boundary(saw_face_geometry):
    case, row = _measurement(saw_face_geometry, "partial-boundary")
    missing_area = math.pi * 0.15**2
    assert case["actual_children"] == 2
    assert row["area_mm2"] == pytest.approx(AREA, abs=1e-6)
    assert row["boundary_uncovered_area_mm2"] == pytest.approx(missing_area, abs=1e-6)
    assert row["boundary_uncovered_area_mm2"] > row["area_tolerance_mm2"]
    assert row["preexisting_boundary_area_mm2"] == pytest.approx(0, abs=1e-6)
    assert row["outward_missing_before_mm3"] == pytest.approx(0, abs=1e-6)
    assert row["outward_missing_removed_mm3"] == pytest.approx(0, abs=1e-6)
    assert row["inward_missing_child_mm3"] == pytest.approx(missing_area * 1e-3, abs=1e-6)
    # The volume witness alone permits this tiny recess; exact area must catch it.
    assert row["inward_missing_child_mm3"] < row["volume_tolerance_mm3"]


@pytest.mark.parametrize(
    "name,preexisting_area", [("partly-preexisting", 18), ("fully-preexisting", 36)]
)
def test_exact_native_newness_rejects_partly_and_wholly_preexisting_faces(
    saw_face_geometry, name, preexisting_area
):
    case, row = _measurement(saw_face_geometry, name)
    assert case["actual_children"] == 2
    assert row["boundary_uncovered_area_mm2"] == pytest.approx(0, abs=1e-6)
    assert row["inward_missing_child_mm3"] == pytest.approx(0, abs=1e-6)
    assert row["preexisting_boundary_area_mm2"] == pytest.approx(preexisting_area, abs=1e-6)
    assert row["preexisting_boundary_area_mm2"] > row["area_tolerance_mm2"]
    for metric in ("outward_missing_before_mm3", "outward_missing_removed_mm3"):
        assert row[metric] == pytest.approx(preexisting_area * WIDTH, abs=1e-6)
        assert row[metric] > row["volume_tolerance_mm3"]


@pytest.mark.parametrize("name,air_depth", [("existing-air", 1), ("thin-existing-air", 0.02)])
def test_exact_native_full_band_finds_existing_air_beyond_the_near_face(
    saw_face_geometry, name, air_depth
):
    case, row = _measurement(saw_face_geometry, name)
    assert case["actual_children"] == 2
    for metric in (
        "boundary_uncovered_area_mm2",
        "preexisting_boundary_area_mm2",
        "inward_missing_child_mm3",
    ):
        assert row[metric] == pytest.approx(0, abs=1e-6)
    for metric in ("outward_missing_before_mm3", "outward_missing_removed_mm3"):
        assert row[metric] == pytest.approx(AREA * air_depth, abs=1e-6)
        assert row[metric] > row["volume_tolerance_mm3"]


def test_exact_native_edge_tangency_has_zero_footprint_coverage(saw_face_geometry):
    case, row = _measurement(saw_face_geometry, "tangency")
    assert case["actual_children"] == 1
    assert row["boundary_uncovered_area_mm2"] == pytest.approx(AREA, abs=1e-6)
    assert row["outward_missing_removed_mm3"] == pytest.approx(AREA * WIDTH, abs=1e-6)
    assert row["outward_missing_before_mm3"] == pytest.approx(0, abs=1e-6)
    assert row["preexisting_boundary_area_mm2"] == pytest.approx(0, abs=1e-6)
    assert row["inward_missing_child_mm3"] == pytest.approx(0, abs=1e-6)


def test_exact_native_full_outward_column_must_be_removed_not_just_touch_the_cut(
    saw_face_geometry,
):
    case, row = _measurement(saw_face_geometry, "short-removed-column")
    assert case["actual_children"] == 2
    assert row["boundary_uncovered_area_mm2"] == pytest.approx(0, abs=1e-6)
    assert row["preexisting_boundary_area_mm2"] == pytest.approx(0, abs=1e-6)
    assert row["outward_missing_before_mm3"] == pytest.approx(0, abs=1e-6)
    assert row["inward_missing_child_mm3"] == pytest.approx(0, abs=1e-6)
    assert row["outward_missing_removed_mm3"] == pytest.approx(AREA * (WIDTH - 0.1), abs=1e-6)
    assert row["outward_missing_removed_mm3"] > row["volume_tolerance_mm3"]


def test_exact_native_inward_column_must_remain_in_the_actual_selected_child(saw_face_geometry):
    case, row = _measurement(saw_face_geometry, "inward-air")
    assert case["actual_children"] == 2
    for metric in (
        "boundary_uncovered_area_mm2",
        "preexisting_boundary_area_mm2",
        "outward_missing_before_mm3",
        "outward_missing_removed_mm3",
    ):
        assert row[metric] == pytest.approx(0, abs=1e-6)
    assert row["inward_missing_child_mm3"] == pytest.approx(AREA * 0.0005, abs=1e-6)
    assert row["inward_missing_child_mm3"] > row["volume_tolerance_mm3"]


@pytest.mark.parametrize(
    "name,original,missing,common",
    [
        ("area-full", 36, 0, 36),
        ("area-partial", 36, 18, 18),
        ("area-disjoint", 36, 36, 0),
        ("volume-full", 72, 0, 72),
        ("volume-partial", 72, 36, 36),
        ("volume-disjoint", 72, 72, 0),
    ],
)
def test_actual_occ_difference_and_independent_common_account_for_the_whole_measure(
    saw_face_geometry, name, original, missing, common
):
    row = saw_face_geometry["boolean_measures"][name]
    assert row["original"] == pytest.approx(original, abs=1e-6)
    assert row["missing"] == pytest.approx(missing, abs=1e-6)
    assert row["remainder"] == pytest.approx(missing, abs=1e-6)
    assert row["common"] == pytest.approx(common, abs=1e-6)
    assert row["missing"] + row["common"] == pytest.approx(row["original"], abs=1e-6)
    if name.endswith("-full"):
        assert row["common"] > 0
    else:
        assert row["missing"] > max(1e-6, row["original"] * 1e-6)
