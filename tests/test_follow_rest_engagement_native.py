"""Typed engagement gates real follow-rest jaw/prism collision helpers, not pictures."""

import pytest
from test_kernel_retained_outputs import _probe

_NATIVE = r"""
import importlib.util, os
import FreeCAD, Part
spec = importlib.util.spec_from_file_location("rest_engine", os.environ["RETAINED_ENGINE"])
engine = importlib.util.module_from_spec(spec)
spec.loader.exec_module(engine)
V = FreeCAD.Vector
setup = object.__new__(engine._Setup)
setup.box = (-10, -10, -20, 10, 10, 20)
fixture = Part.makeBox(4, 2, 4, V(5, -1, -2))
setup.fixture = [{"name": "chuck", "envelope": fixture,
                  "envelope_bbox": engine._bbox(fixture)}]
# The jaws ride radius 5 at the contact point, but their depth also meets a real collar.
profile = Part.makeCylinder(5, 40, V(0, 0, -20)).fuse(
    Part.makeCylinder(7, 0.6, V(0, 0, -0.8)))
rest_section = engine._meridian_segments(profile)
section = [(5, -2), (9, -2), (9, 2), (5, 2)]
clear_section = [(1, -2), (2, -2), (2, 2), (1, 2)]


def run(feed, leading, contact=0, engage=0, diameter=True, malformed=False,
        omit_leading=False, clear=False, extra_active=False):
    rest = {"name": "carriage", "side": "turned", "lead_mm": 0,
            "jaw_depth_mm": 4, "jaw_width_mm": 2, "jaw_height_mm": 4,
            "jaw_angles_deg": [0]}
    if engage != "missing":
        rest["engage_at_z_mm"] = engage
    record = {"poses": 0, "clashes": {}, "gaps": [], "render": None}
    posed = [(rest, profile, rest_section if diameter else [], record)]
    other = None
    if extra_active:
        other = {"poses": 0, "clashes": {}, "gaps": [], "render": None}
        other_rest = dict(rest, name="active", engage_at_z_mm=-feed * 10)
        if extra_active == "ungated":
            del other_rest["engage_at_z_mm"]
        posed.append((other_rest, profile, rest_section, other))
    polygon = [] if malformed else (clear_section if clear else section)
    kwargs = {} if omit_leading else {"leading_z": leading}
    tool = {"feed_z": feed, "radius_mm": 0.4, "corners": 1}
    hits, gap = setup._rest_hits(posed, tool, (5, contact),
                                 polygon, [polygon, polygon], "S1:10", **kwargs)
    return {"hits": {kind: sorted(names) for kind, names in hits.items()},
            "gap": gap, "poses": record["poses"], "clashes": record["clashes"],
            "gaps": record["gaps"], "render": record["render"] is not None,
            "render_z": record["render"][1] if record["render"] else None,
            "render_bbox": list(engine._bbox(record["render"][0][0]))
                           if record["render"] and record["render"][0] else None,
            "other_poses": other["poses"] if other else None}

out = {}
for feed in (-1, 1):
    rows = {}
    rows["before"] = run(feed, -feed * 0.5)
    rows["equal"] = run(feed, 0)
    rows["past"] = run(feed, feed * 0.5)
    rows["render_nose_offset"] = run(feed, feed * 0.4)
    rows["before_no_diameter"] = run(feed, -feed, diameter=False)
    rows["before_bad_prism"] = run(feed, -feed, malformed=True)
    rows["equal_no_diameter"] = run(feed, 0, diameter=False)
    rows["equal_bad_prism"] = run(feed, 0, malformed=True)
    rows["radial_past_leading_before"] = run(feed, -feed * 0.5, contact=feed * 0.5)
    rows["radial_before_leading_past"] = run(feed, feed * 0.5, contact=-feed * 0.9)
    rows["missing_leading"] = run(feed, None, omit_leading=True)
    rows["unknown_leading"] = run(feed, "unknown")
    rows["unknown_leading_bad_prism"] = run(feed, "unknown", malformed=True)
    rows["unknown_leading_no_diameter"] = run(feed, "unknown", diameter=False)
    rows["unknown_leading_mixed"] = run(feed, "unknown", extra_active="ungated")
    rows["missing_engagement"] = run(feed, -feed, engage="missing")
    rows["unknown_engagement"] = run(feed, -feed, engage="unknown")
    rows["nonfinite_engagement"] = run(feed, -feed, engage=float("nan"))
    rows["clear_prism"] = run(feed, 0, clear=True)
    rows["mixed"] = run(feed, -feed * 0.5, extra_active=True)
    hypothetical_rest = {
        "name": "parked", "side": "turned", "lead_mm": 0, "jaw_depth_mm": 4,
        "jaw_width_mm": 2, "jaw_height_mm": 4, "jaw_angles_deg": [0],
        "engage_at_z_mm": feed * 8,
    }
    hypothetical_record = {"poses": 0, "clashes": {}, "gaps": [], "render": None}
    hypothetical = [(hypothetical_rest, profile, rest_section, hypothetical_record)]
    window = {"end": "z_from", "point": (5, feed * 0.4),
              "centre": (5, 0), "sample_z": feed * 10}
    rows["recommendation"] = setup._rest_engagement(
        hypothetical, {"feed_z": feed}, [window], "S1:10"
    )
    rows["recommendation_no_work"] = setup._rest_engagement(
        hypothetical, {"feed_z": feed}, [dict(window, sample_z=feed * 30)], "S1:10"
    )
    rows["recommendation_record"] = hypothetical_record
    out[str(feed)] = rows

# Two real active contacts, visited in opposite orders, must select the same
# representative cylindrical engagement picture even when the shoulder is first.
order_profile = Part.makeCylinder(5, 40)
order_section = engine._meridian_segments(order_profile)
order_rest = dict(hypothetical_rest, name="order", engage_at_z_mm=30)
order_tool = {"feed_z": -1, "radius_mm": 0.4, "corners": 1}
out["face_order"] = []
for contacts in (((20, 20), (30.4, 30)), ((30.4, 30), (20, 20))):
    record = {"poses": 0, "clashes": {}, "gaps": [], "render": None}
    for contact, leading in contacts:
        posed_polygon = [(r, z + contact) for r, z in section]
        setup._rest_hits([(order_rest, order_profile, order_section, record)],
                         order_tool, (5, contact), posed_polygon, None, "S1:10",
                         leading_z=leading)
    jaws, cut_z, why = record["render"]
    out["face_order"].append({"cut_z": cut_z, "why": why,
                              "bbox": list(engine._bbox(jaws[0]))})
out["missing_picture_geometry"] = []
for key in ("radius_mm", "corners"):
    missing = dict(order_tool)
    del missing[key]
    jaws, cut_z, why = setup._rest_render_pose(
        order_rest, order_section, missing, [], (5, 20), leading_z=20
    )
    out["missing_picture_geometry"].append({"drawn": jaws is not None, "why": why})
"""


@pytest.fixture(scope="module")
def native(tmp_path_factory, freecad_kernel):
    return _probe(_NATIVE, tmp_path_factory.mktemp("follow-rest-engagement"), freecad_kernel)


@pytest.mark.parametrize("feed", ["-1", "1"])
def test_parked_rest_has_no_geometry_side_effects(native, feed):
    for name in ("before", "before_no_diameter", "before_bad_prism", "radial_past_leading_before"):
        row = native[feed][name]
        assert row["hits"] == {"tool": [], "holder": []}, (name, row)
        assert row["gap"] is None and row["gaps"] == [], (name, row)
        assert row["poses"] == 0 and row["clashes"] == {}, (name, row)
        assert row["render"] is False, (name, row)


@pytest.mark.parametrize("feed", ["-1", "1"])
def test_equal_and_past_engagement_keep_real_native_collisions(native, feed):
    for name in ("equal", "past", "radial_before_leading_past"):
        row = native[feed][name]
        assert row["hits"] == {
            "tool": ["follow rest carriage"],
            "holder": ["follow rest carriage"],
        }, (name, row)
        assert row["gap"] is None and row["poses"] == 1, (name, row)
        assert any("meets chuck" in key for key in row["clashes"]), (name, row)
        assert any("larger work" in key for key in row["clashes"]), (name, row)
        expected_z = -int(feed) * 0.4
        assert row["render"] is True and row["render_z"] == pytest.approx(expected_z), (name, row)
    assert "no work diameter" in native[feed]["equal_no_diameter"]["gap"]
    assert "tool section could not be built" in native[feed]["equal_bad_prism"]["gap"]
    clear = native[feed]["clear_prism"]
    assert clear["hits"] == {"tool": [], "holder": []}
    assert clear["poses"] == 1 and clear["clashes"]


@pytest.mark.parametrize("feed", ["-1", "1"])
def test_render_uses_contact_reference_at_leading_dro_threshold(native, feed):
    cut_z = -int(feed) * 0.4
    radius = 7 if feed == "1" else 5
    for name in ("equal", "past", "render_nose_offset", "radial_before_leading_past"):
        row = native[feed][name]
        assert row["render_z"] == pytest.approx(cut_z), (name, row)
        assert row["render_bbox"] == pytest.approx(
            [radius, -1, cut_z - 2, radius + 4, 1, cut_z + 2]
        ), (name, row)


@pytest.mark.parametrize("feed", ["-1", "1"])
def test_unknown_leading_reference_keeps_debt_and_independent_collisions(native, feed):
    for name in (
        "missing_leading",
        "unknown_leading",
        "unknown_leading_bad_prism",
        "unknown_leading_no_diameter",
    ):
        row = native[feed][name]
        assert "lacks a measured leading tool z" in row["gap"]
        assert row["gaps"] == [row["gap"]]
        assert row["hits"] == {"tool": [], "holder": []}
        assert row["poses"] == 0 and row["clashes"] == {}
        assert row["render"] is False
    mixed = native[feed]["unknown_leading_mixed"]
    assert "lacks a measured leading tool z" in mixed["gap"]
    assert mixed["poses"] == 0 and mixed["clashes"] == {} and mixed["render"] is False
    assert mixed["other_poses"] == 1
    assert mixed["hits"] == {"tool": ["follow rest active"], "holder": ["follow rest active"]}
    for name in ("missing_engagement", "unknown_engagement", "nonfinite_engagement"):
        row = native[feed][name]
        assert row["gap"] is None and row["poses"] == 1
        assert row["hits"]["tool"] == ["follow rest carriage"]


@pytest.mark.parametrize("feed", ["-1", "1"])
def test_parked_rest_does_not_hide_another_active_rest(native, feed):
    row = native[feed]["mixed"]
    assert row["poses"] == 0 and row["gaps"] == [] and row["clashes"] == {}
    assert row["render"] is False and row["other_poses"] == 1
    assert row["hits"] == {"tool": ["follow rest active"], "holder": ["follow rest active"]}


@pytest.mark.parametrize("feed", ["-1", "1"])
def test_hypothetical_clearance_reports_leading_dro_without_activating_jaws(native, feed):
    rows = native[feed]
    (entry,) = rows["recommendation"]
    assert entry["rest"] == "parked" and entry["meets"] == ["chuck"]
    assert entry["start_z_mm"] == pytest.approx(int(feed) * 0.4)
    assert entry["engage_z_mm"] == pytest.approx(int(feed) * 4.4, abs=1e-4)
    assert rows["recommendation_no_work"] == []
    assert rows["recommendation_record"] == {"poses": 0, "clashes": {}, "gaps": [], "render": None}


def test_shoulder_first_and_radial_first_render_the_same_exact_engagement_pose(native):
    assert native["face_order"][0] == native["face_order"][1]
    for row in native["face_order"]:
        assert row["cut_z"] == pytest.approx(30.4)
        assert row["why"] is None
        assert row["bbox"] == pytest.approx([5, -1, 28.4, 9, 1, 32.4])


def test_engagement_picture_requires_measured_nose_geometry(native):
    for row in native["missing_picture_geometry"]:
        assert row == {"drawn": False, "why": "engagement picture lacks measured nose geometry"}
