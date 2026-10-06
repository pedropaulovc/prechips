"""Turned-profile spans filled by the kernel's faces of revolution about setup Z.

Declared ``z_mm``/diameters stay authoritative; the kernel's per-setup ``revolved`` facts
fill what a consumer export leaves undeclared (shaft/dome/face without ``z_mm``); anything
neither source resolves stays unknown with its debt named.  Unit tests inject a synthetic
``bundle.kernel``; one FreeCAD test measures the facts on an authored shaft with a dome.
"""

import dataclasses
import math
import subprocess

import pytest
from test_kernel_geometry import IDENTITY, Engine
from test_lathe_m2 import bundle, setup
from test_turning_geometry import _CHUCK, _turn

from prechips.rules import coordinates, speeds_feeds, stickout, turned_profile

# Dome of base radius 4 and height 2 on a sphere of radius 5: sqrt(2 * (10 - 2)) = 4.
SHAFT_AND_DOME = {
    "body": {"kind": "shaft", "frame": "model", "dia_nominal": 8.0, "cite": "test shaft"},
    "tip": {
        "kind": "dome",
        "frame": "model",
        "sphere_radius": 5.0,
        "height_nominal": 2.0,
        "cite": "test dome",
    },
}


def _revolved(**facts):
    """One revolved fact per feature: (z_lo, z_hi, r_min, r_max, r_at_lo, r_at_hi)."""
    return {
        name: {
            "z_mm": [z0, z1],
            "radii_mm": [r0, r1],
            "end_radii_mm": [e0, e1],
            "kinds": ["Cylinder"],
        }
        for name, (z0, z1, r0, r1, e0, e1) in facts.items()
    }


def _with_kernel(data, revolved, reasons=None):
    facts = {"revolved": revolved, "revolved_reasons": reasons or {}}
    return dataclasses.replace(data, kernel={"status": "ok", "setups": {"S1": facts}})


def _shaft_and_dome(**revolved):
    data = bundle()
    data.features["features"] = dict(SHAFT_AND_DOME)
    setup(data)["ops"] = [
        {"op": 10, "do": "finish_turn", "feature": "body", "tool": "turner"},
        {"op": 20, "do": "form_dome", "feature": "tip", "tool": "turner"},
    ]
    facts = revolved or {"body": (0.0, 18.0, 4.0, 4.0, 4.0, 4.0), "tip": (18.0, 20.0, 0, 4, 4, 0)}
    return _with_kernel(data, _revolved(**facts))


def test_kernel_spans_fill_an_export_without_z_mm_and_its_absence_stays_unknown():
    data = _shaft_and_dome()
    profile, ld = turned_profile.evaluate(data)[0], stickout.evaluate(data)[0]
    assert profile.status == "pass"
    assert [(i["feature"], i["z_mm"], i["diameter_mm"]) for i in profile.numbers["intervals"]] == [
        ("body", [0.0, 18.0], 8.0),
        ("tip", [18.0, 20.0], 8.0),
    ]
    # D = 8 (the dome counts at its base): 20 mm stick-out is inside 3 x 8 = 24.
    assert ld.status == "pass" and ld.numbers["diameter_mm"] == 8.0
    assert any(text.startswith("kernel: setups.S1.revolved.body") for text in profile.cite)

    absent = dataclasses.replace(data, kernel=None)
    profile, ld = turned_profile.evaluate(absent)[0], stickout.evaluate(absent)[0]
    assert profile.status == ld.status == "unknown"
    reasons = profile.numbers["unresolved_reasons"]
    assert sorted(reasons) == ["body", "tip"]
    assert "no declared z_mm; kernel: no kernel geometry is available" in reasons["body"]
    assert ld.numbers["unresolved_reasons"] == reasons


def test_feature_revolved_about_another_axis_leaves_the_profile_only_when_not_turned_here():
    """A cross boss (another component or a milled feature) does not poison the spindle
    profile; claimed by this setup's turning, or unmeasured, it remains a named debt."""
    data = _shaft_and_dome()
    data.features["features"]["cross"] = {"kind": "boss", "frame": "model", "dia_nominal": 4.0}
    reason = "#7/ADVANCED_FACE[2]/PIN is not revolved about setup Z through x = y = 0"
    data.kernel["setups"]["S1"]["revolved_reasons"]["cross"] = reason
    assert turned_profile.evaluate(data)[0].status == stickout.evaluate(data)[0].status == "unknown"

    data.kernel["setups"]["S1"]["revolved_off_axis"] = {"cross": {"axis": [1.0, 0.0, 0.0]}}
    profile, ld = turned_profile.evaluate(data)[0], stickout.evaluate(data)[0]
    assert profile.status == ld.status == "pass"
    assert profile.numbers["off_axis"] == ld.numbers["off_axis"] == {"cross": [1.0, 0.0, 0.0]}
    assert "cross" not in profile.numbers["unresolved"]

    setup(data)["ops"].append({"op": 30, "do": "finish_turn", "feature": "cross"})
    profile = turned_profile.evaluate(data)[0]
    assert profile.status == "unknown" and reason in profile.numbers["unresolved_reasons"]["cross"]


def test_declared_values_override_kernel_facts_and_kernel_fills_only_the_gap():
    data = _with_kernel(bundle(), _revolved(far=(10.0, 30.0, 5.0, 5.0, 5.0, 5.0)))
    span = turned_profile.feature_span(data, setup(data), "far")
    assert (span["z_mm"], span["diameter_mm"], span["source"]) == ([10.0, 20.0], 8.0, "declared")
    assert not any(text.startswith("kernel:") for text in span["cite"])

    del data.features["features"]["far"]["dia_nominal"]
    span = turned_profile.feature_span(data, setup(data), "far")
    assert (span["z_mm"], span["diameter_mm"], span["source"]) == ([10.0, 20.0], 10.0, "kernel")
    assert span["sources"] == {"z_mm": "declared", "diameter_mm": "kernel"}

    # Declared stations that do not resolve along setup Z are never replaced by the kernel.
    data.features["features"]["far"]["axis"] = [1.0, 0.0, 0.0]
    span = turned_profile.feature_span(data, setup(data), "far")
    assert span["z_mm"] == "unknown" and span["diameter_mm"] == 10.0


def test_kernel_omission_or_non_cylindrical_radii_leave_the_feature_unknown():
    reason = "#9/ADVANCED_FACE[3]/FLAT is not revolved about setup Z through x = y = 0"
    data = _with_kernel(bundle(), {}, {"far": reason})
    del data.features["features"]["far"]["z_mm"]
    span = turned_profile.feature_span(data, setup(data), "far")
    assert span["z_mm"] == "unknown" and span["source"] == "declared"  # its declared diameter
    assert span["unresolved"] == [f"no declared z_mm; kernel: {reason}"]
    profile = turned_profile.evaluate(data)[0]
    assert profile.status == "unknown" and reason in profile.numbers["unresolved_reasons"]["far"]

    # A kernel span over several radii is not one cylinder: no diameter is taken from it.
    data = _with_kernel(bundle(), _revolved(far=(10.0, 20.0, 3.0, 4.0, 4.0, 3.0)))
    del data.features["features"]["far"]["dia_nominal"]
    span = turned_profile.feature_span(data, setup(data), "far")
    assert span["diameter_mm"] == "unknown" and "radii 3..4 mm" in span["unresolved"][0]
    assert turned_profile.evaluate(data)[0].status == "unknown"

    data = dataclasses.replace(bundle(), kernel=None)
    span = turned_profile.feature_span(data, setup(data), "missing")
    assert span["z_mm"] == span["diameter_mm"] == "unknown" and span["source"] == "unknown"


def test_groove_takes_its_floor_and_a_face_its_axial_extent_from_the_kernel():
    data = bundle()
    data.features["features"]["relief"] = {"kind": "groove", "frame": "model"}
    data.features["features"]["thrust"] = {"kind": "face", "frame": "model"}
    data = _with_kernel(
        data,
        _revolved(relief=(8.0, 10.0, 2.85, 6.0, 6.0, 2.85), thrust=(10.0, 10.0, 2.85, 6.0, 6, 6)),
    )
    relief = turned_profile.feature_span(data, setup(data), "relief")
    thrust = turned_profile.feature_span(data, setup(data), "thrust")
    assert relief["z_mm"] == [8.0, 10.0] and relief["diameter_mm"] == pytest.approx(5.7)
    assert (thrust["z_mm"], thrust["height_mm"]) == ([10.0, 10.0], 0.0)
    assert thrust["diameter_mm"] == "unknown"


@pytest.mark.parametrize(
    "ends,expected",
    [((4.0, 0.0), "pass"), ((0.0, 4.0), "unknown"), ((4.0, 4.0), "unknown")],
)
def test_dome_must_narrow_away_from_the_chuck(ends, expected):
    """Apex toward +Z is bounded by its base; apex toward the chuck or unresolved is not."""
    data = _shaft_and_dome(body=(0.0, 18.0, 4.0, 4.0, 4.0, 4.0), tip=(18.0, 20.0, 0.0, 4.0, *ends))
    finding = turned_profile.evaluate(data)[0]
    assert finding.status == expected
    if expected != "pass":
        assert "tip" in finding.numbers["unresolved_reasons"]


@pytest.mark.parametrize(
    "fields,units,expected",
    [
        ({"base_radius": 3.0, "sphere_radius": 5.0, "height_nominal": 2.0}, "mm", 6.0),
        ({"sphere_radius": 5.0, "height_nominal": 2.0}, "mm", 8.0),
        ({"sphere_radius": 5.0, "height": 5.0}, "mm", 10.0),  # hemisphere
        ({"sphere_radius": 5.0, "height": 8.0}, "mm", 10.0),  # widest at the equator
        ({"sphere_radius": 5.0, "height": 10.01}, "mm", "unknown"),  # taller than the sphere
        ({"sphere_radius": 5.0, "height": [1.0, 3.0]}, "mm", "unknown"),  # a band
        ({"sphere_radius": 0.2, "height_nominal": 0.08}, "in", 25.4 * 2 * math.sqrt(0.08 * 0.32)),
        ({"sphere_radius": 5.0, "height_nominal": 2.0}, "unknown", "unknown"),
    ],
)
def test_dome_base_diameter_from_declared_sphere(fields, units, expected):
    data = bundle()
    data.features["units"] = units
    value = turned_profile.dome_base_diameter(data, {"kind": "dome", **fields})
    assert value == (pytest.approx(expected) if expected != "unknown" else "unknown")


def test_dome_base_float_residue_is_not_a_shoulder_but_a_real_rise_is():
    """The exported pivot dome (R 4.1102083, h 1.5) is Ø6.35 at its base, as its journal."""
    data = bundle()
    data.features["features"] = {
        "journal": {"kind": "shaft", "frame": "model", "dia_nominal": 6.35, "z_mm": [0.0, 18.5]},
        "tip": {"kind": "dome", "sphere_radius": 4.1102083333333335, "height_nominal": 1.5},
    }
    setup(data)["ops"] = [{"op": 10, "do": "form_dome", "feature": "tip", "tool": "turner"}]
    data = _with_kernel(data, _revolved(tip=(18.5, 20.0, 0.0, 3.175, 3.175, 0.0)))
    assert turned_profile.dome_base_diameter(data, data.features["features"]["tip"]) != 6.35
    assert turned_profile.evaluate(data)[0].status == "pass"
    data.features["features"]["tip"]["base_radius"] = 3.1755
    assert turned_profile.evaluate(data)[0].status == "error"


@pytest.mark.parametrize("action", ["cut_to_fit", "part_off", "face"])
def test_cut_to_fit_and_part_off_start_at_the_held_stock_like_facing(action):
    data = bundle()
    setup(data)["stock_state"]["od_mm"] = 6.35
    op = {"op": 10, "do": action, "feature": "end"}
    assert speeds_feeds._diameter(data, setup(data), op, {}, True) == 6.35
    op["do"] = "finish_turn"
    assert speeds_feeds._diameter(data, setup(data), op, {}, True) == "unknown"


def test_dome_cutting_diameter_is_its_base_declared_or_measured():
    data = _shaft_and_dome()
    op = {"op": 20, "do": "form_dome", "feature": "tip"}
    assert speeds_feeds._diameter(data, setup(data), op, {}, True) == pytest.approx(8.0)
    del data.features["features"]["tip"]["sphere_radius"]
    data = _with_kernel(data, _revolved(tip=(18.0, 20.0, 0.0, 4.5, 4.5, 0.0)))
    assert speeds_feeds._diameter(data, setup(data), op, {}, True) == 9.0
    data = dataclasses.replace(data, kernel=None)
    assert speeds_feeds._diameter(data, setup(data), op, {}, True) == "unknown"


def _collar(**facts):
    """The test bundle chucked 5 mm deeper: exposed z -5..20, where z -5..0 is raw stock
    between the jaw mouth and the first finished feature (the cone built-up raw collar).
    ``facts`` is the kernel's per-setup record (``stock_profile`` / its reason)."""
    data = bundle()
    setup(data)["hold"]["stickout_mm"] = 25.0
    return dataclasses.replace(data, kernel={"status": "ok", "setups": {"S1": facts}})


def test_raw_collar_takes_the_kernel_stock_diameter_and_can_make_stickout_an_error():
    # The collar is the Ø12 bar: D stays the Ø8 far journal, and 25 mm > 3 x 8 = 24.
    data = _collar(stock_profile=[[-5.0, 0.0, 6.0, 6.0], [0.0, 20.0, 4.0, 6.0]])
    ld = stickout.evaluate(data)[0]
    assert ld.status == "error" and "exceeds the unsupported shop limit" in ld.sentence
    assert ld.numbers["diameter_mm"] == 8.0 and ld.numbers["diameter_features"] == ["far"]
    assert ld.numbers["uncovered_z_mm"] == [] and ld.numbers["stock_reason"] is None
    collar = [s for s in ld.numbers["segments"] if s.get("source") == "kernel_stock"]
    assert collar == [
        {"z_mm": [-5.0, 0.0], "diameter_mm": 12.0, "features": [], "source": "kernel_stock"}
    ]
    assert any(text.startswith("kernel: setups.S1.stock_profile") for text in ld.cite)
    # The collar is the least radius any in-process state shows there: necked to Ø7 it,
    # not a finished feature, sets D (limit 21).
    necked = _collar(stock_profile=[[-5.0, 0.0, 3.5, 6.0], [0.0, 20.0, 4.0, 6.0]])
    ld = stickout.evaluate(necked)[0]
    assert ld.status == "error" and ld.numbers["diameter_mm"] == 7.0
    assert ld.numbers["diameter_features"] == ["kernel stock"]
    assert ld.numbers["unsupported_limit_mm"] == pytest.approx(21.0)


@pytest.mark.parametrize(
    ("facts", "reason"),
    [
        ({}, "the kernel reports no stock profile for this setup"),
        (
            {"stock_profile_reason": "the stock after removal 1 is not a solid of revolution"},
            "the stock after removal 1 is not a solid of revolution",
        ),
        # Starts 1 mm short of the jaw mouth, or leaves a hole inside the collar.
        ({"stock_profile": [[-4.0, 20.0, 4.0, 6.0]]}, "does not cover the whole span"),
        (
            {"stock_profile": [[-5.0, -3.0, 6.0, 6.0], [-2.0, 20.0, 4.0, 6.0]]},
            "does not cover the whole span",
        ),
    ],
)
def test_absent_or_partial_stock_profile_leaves_the_raw_collar_unknown(facts, reason):
    ld = stickout.evaluate(_collar(**facts))[0]
    assert ld.status == "unknown" and ld.numbers["diameter_mm"] == "unknown"
    assert ld.numbers["uncovered_z_mm"] == [[-5.0, 0.0]]
    assert reason in ld.numbers["stock_reason"] and reason in ld.sentence
    no_kernel = dataclasses.replace(_collar(), kernel=None)
    assert stickout.evaluate(no_kernel)[0].numbers["stock_reason"] == (
        "no kernel geometry is available"
    )


def _boss_on_a_lathe(revolved=None, reasons=None, at=None):
    """A Ø6 boss turned on the test lathe; located only by ``at`` or the spindle axis."""
    data = bundle()
    data.plan["dro"] = {"controller": "test manual DRO", "radius_mode": False}
    data.inventory["tools"] = {"turner": {"kind": "turning_tool", "nose_radius_mm": 0.4}}
    boss = {"kind": "boss", "frame": "model", "dia_nominal": 6.0, "cite": "test boss"}
    data.features["features"]["boss"] = boss if at is None else {**boss, "at": at}
    setup(data)["ops"] = [{"op": 10, "do": "finish_turn", "feature": "boss", "tool": "turner"}]
    return _with_kernel(data, _revolved(**(revolved or {})), reasons)


def test_coaxial_boss_is_located_by_the_spindle_axis_but_off_axis_still_needs_at():
    coaxial = coordinates.evaluate(_boss_on_a_lathe({"boss": (20.0, 25.0, 3, 3, 3, 3)}))[0]
    assert coaxial.status == "pass"
    rows = {row["point"]: row["setup"] for row in coaxial.numbers["rows"]}
    assert rows == {
        "spindle axis, kernel span start": [0.0, 0.0, 20.0],
        "spindle axis, kernel span end": [0.0, 0.0, 25.0],
    }
    assert any(text.startswith("kernel: setups.S1.revolved.boss") for text in coaxial.cite)
    # Revolved about another axis (a cross boss) or not measured: no spindle location.
    why = {"boss": "#4/ADVANCED_FACE[2]/BOSS is not revolved about setup Z through x = y = 0"}
    unmeasured = dataclasses.replace(_boss_on_a_lathe(), kernel=None)
    for data in (_boss_on_a_lathe(reasons=why), unmeasured):
        finding = coordinates.evaluate(data)[0]
        assert finding.status == "unknown"
        assert all(row.get("point") is None for row in finding.numbers["rows"])
    # An authored ``at`` still locates an off-axis boss.
    placed = coordinates.evaluate(_boss_on_a_lathe(reasons=why, at=[3.0, 0.0, 22.0]))[0]
    assert placed.status == "pass"
    assert {"feature": "boss", "model": [3.0, 0.0, 22.0], "setup": [3.0, 0.0, 22.0]} in (
        placed.numbers["rows"]
    )


# --------------------------------------------------------------------- FreeCAD

_AUTHOR = r"""
import sys
import FreeCAD, Part
V = FreeCAD.Vector
out = sys.argv[sys.argv.index("--") + 1]
# Ø8 shaft z 0..30 with a 1.5 mm spherical dome (base r 4) on its +Z end and a milled
# flat (y = 3.5) over z 10..15 and a Ø4 cross pin along +X at z 20;
# R = (4^2 + 1.5^2) / (2 * 1.5).
R = (16 + 2.25) / 3
cap = Part.makeSphere(R, V(0, 0, 31.5 - R)).common(Part.makeCylinder(5, 2, V(0, 0, 30)))
part = Part.makeCylinder(4, 30).fuse(cap).removeSplitter()
part = part.cut(Part.makeBox(10, 10, 5, V(-5, 3.5, 10))).removeSplitter()
part = part.fuse(Part.makeCylinder(2, 6, V(0, 0, 20), V(1, 0, 0))).removeSplitter()
assert part.isValid() and len(part.Solids) == 1
part.exportStep(out + "/shaft-dome.step")
"""


@pytest.fixture(scope="module")
def shaft_dome(tmp_path_factory, freecad_kernel):
    directory = tmp_path_factory.mktemp("shaft-dome")
    script = directory / "author.py"
    script.write_text(_AUTHOR, encoding="utf-8")
    process = subprocess.run(
        [freecad_kernel, str(script), "--", str(directory)],
        capture_output=True,
        text=True,
        errors="replace",
        timeout=300,
    )
    path = directory / "shaft-dome.step"
    assert path.exists(), process.stdout[-2000:] + process.stderr[-2000:]
    return path


def test_kernel_measures_revolved_spans_of_an_authored_shaft_and_dome(
    tmp_path, freecad_kernel, shaft_dome
):
    engine = Engine(tmp_path, freecad_kernel)
    features = {
        "shaft": engine.refs(shaft_dome, (-4, -4, 0), (4, 4, 30), kind="Cylinder"),
        "dome": engine.refs(shaft_dome, (-4, -4, 30), (4, 4, 31.5), kind="Sphere"),
        "end": engine.refs(shaft_dome, (-4, -4, 0), (4, 4, 0), kind="Plane"),
        "flat": engine.refs(shaft_dome, (-4, 3.5, 10), (4, 3.5, 15), kind="Plane"),
        "pin": engine.refs(shaft_dome, (0, -2, 18), (6, 2, 22), kind="Cylinder"),
    }
    assert all(features.values()), features
    # S2 rechucks reversed: setup +Z runs from the apex (setup z 0) toward the plain end.
    flipped = {"origin": [0, 0, 31.5], "x": [1, 0, 0], "y": [0, -1, 0], "z": [0, 0, -1]}
    setups = [
        {"id": setup_id, "frame": frame, "hold": _CHUCK, "ops": [_turn(f"{setup_id}:10", "shaft")]}
        for setup_id, frame in (("S1", IDENTITY), ("S2", flipped))
    ]
    result = engine.run(engine.job(shaft_dome, features, setups))
    assert result["status"] == "ok", result
    first, second = (result["setups"][key] for key in ("S1", "S2"))
    approx = pytest.approx

    shaft, dome, end = (first["revolved"][name] for name in ("shaft", "dome", "end"))
    assert (shaft["z_mm"], shaft["radii_mm"], shaft["kinds"]) == ([0, 30], [4, 4], ["Cylinder"])
    assert dome["z_mm"] == approx([30.0, 31.5]) and dome["radii_mm"] == approx([0.0, 4.0])
    assert dome["end_radii_mm"] == approx([4.0, 0.0]) and dome["kinds"] == ["Sphere"]
    assert end["z_mm"] == [0, 0] and end["radii_mm"] == approx([0.0, 4.0])
    # A milled flat is not a face of revolution: omitted, with the reason named.
    assert "flat" not in first["revolved"]
    assert "not revolved about setup Z" in first["revolved_reasons"]["flat"]
    # A cross pin is revolved, but about X: reported off-axis; a flat has no axis.
    assert "pin" not in first["revolved"] and "flat" not in first["revolved_off_axis"]
    assert [abs(value) for value in first["revolved_off_axis"]["pin"]["axis"]] == [1, 0, 0]

    shaft, dome = second["revolved"]["shaft"], second["revolved"]["dome"]
    assert shaft["z_mm"] == approx([1.5, 31.5])
    assert dome["z_mm"] == approx([0.0, 1.5]) and dome["end_radii_mm"] == approx([0.0, 4.0])


def test_kernel_measures_requested_revolved_facts_in_mill_setups(
    tmp_path, freecad_kernel, shaft_dome
):
    """A setup without turning measures only the features the host asks to locate."""
    engine = Engine(tmp_path, freecad_kernel)
    features = {
        "shaft": engine.refs(shaft_dome, (-4, -4, 0), (4, 4, 30), kind="Cylinder"),
        "dome": engine.refs(shaft_dome, (-4, -4, 30), (4, 4, 31.5), kind="Sphere"),
        "end": engine.refs(shaft_dome, (-4, -4, 0), (4, 4, 0), kind="Plane"),
        "flat": engine.refs(shaft_dome, (-4, 3.5, 10), (4, 3.5, 15), kind="Plane"),
    }
    assert all(features.values()), features
    # M1 turns the part over and swaps X/Y: setup z = 31.5 - model z. M2 is shifted 2 mm
    # off the shaft axis. M3 asks for nothing.
    swapped = {"origin": [0, 0, 31.5], "x": [0, 1, 0], "y": [1, 0, 0], "z": [0, 0, -1]}
    shifted = {**IDENTITY, "origin": [2, 0, 0]}
    hold = {"kind": "vise", "reason": "test: the vise is not placed"}
    asked = ["dome", "flat", "shaft"]
    setups = [
        {"id": "M1", "frame": swapped, "hold": hold, "ops": [], "locate_revolved": asked},
        {"id": "M2", "frame": shifted, "hold": hold, "ops": [], "locate_revolved": ["shaft"]},
        {"id": "M3", "frame": IDENTITY, "hold": hold, "ops": [], "locate_revolved": []},
    ]
    result = engine.run(engine.job(shaft_dome, features, setups))
    assert result["status"] == "ok", result
    first, second, third = (result["setups"][key] for key in ("M1", "M2", "M3"))
    approx = pytest.approx

    assert sorted(first["revolved"]) == ["dome", "shaft"]
    assert first["revolved"]["shaft"]["z_mm"] == approx([1.5, 31.5])
    assert first["revolved"]["shaft"]["radii_mm"] == approx([4.0, 4.0])
    assert first["revolved"]["dome"]["z_mm"] == approx([0.0, 1.5])
    # Only requested features are measured; a flat is omitted with its reason.
    assert list(first["revolved_reasons"]) == ["flat"]
    assert "not revolved about setup Z" in first["revolved_reasons"]["flat"]
    # Off the setup axis the same cylinder locates nothing.
    assert second["revolved"] == {}
    assert "not revolved about setup Z" in second["revolved_reasons"]["shaft"]
    assert "revolved" not in third
