"""Follow and steady rests posed in the turning model, and the setup's stock profile.

The filleted shaft of ``test_integrated_turning_routes`` (12 mm journal z 0..20, R1 fillet,
8 mm journal z 20..40, spindle on setup Z) is turned on a placed chuck; the rests are the
engine records the host builds from measured inventory facts. Assertions read only the
JSON of ``freecad_job.py``.
"""

import subprocess

import pytest
from test_fixture_solids import _chuck
from test_integrated_turning_routes import _AUTHOR, _AUTHORED, BAR, _journals, _lathe
from test_kernel_geometry import Engine
from test_turning_geometry import _turn

REST = "follow rest fr"
STEADY = "steady rest sr"


@pytest.fixture(scope="module")
def shaft(tmp_path_factory, freecad_kernel):
    directory = tmp_path_factory.mktemp("rest-shafts")
    script = directory / "author.py"
    script.write_text(_AUTHOR, encoding="utf-8")
    process = subprocess.run(
        [freecad_kernel, str(script), "--", str(directory)],
        capture_output=True,
        text=True,
        errors="replace",
        timeout=300,
    )
    paths = {path.stem: path for path in directory.glob("*.step")}
    assert len(paths) == _AUTHORED, process.stdout[-2000:] + process.stderr[-2000:]
    return paths["filleted"]


@pytest.fixture
def engine(tmp_path, freecad_kernel):
    return Engine(tmp_path, freecad_kernel)


def _follow(lead, **extra):
    """One 46 mm tall jaw on the tool's side (0 deg) trailing the cut of T1:10 only."""
    return {
        "name": "fr",
        "subjects": ["T1:10"],
        "side": "turned",
        "lead_mm": lead,
        "jaw_width_mm": 12.0,
        "jaw_height_mm": 46.0,
        "jaw_depth_mm": 10.0,
        "jaw_angles_deg": [0.0],
        **extra,
    }


def _ops(count=1):
    """Finish-turn passes over the exposed journal profile (z 40 -> 20), T1:10 first."""
    return [_turn(f"T1:{10 * (n + 1)}", "exposed", z_from=40.0, z_to=20.0) for n in range(count)]


def _run(engine, shaft, holds, ops, stock=BAR):
    features = _journals(engine, shaft)
    jobs = [engine.job(shaft, features, [_lathe("T1", ops, hold)], stock=stock) for hold in holds]
    return engine.run({"jobs": jobs})["results"]


def test_follow_rest_jaw_clears_the_toolpost_only_at_its_body_edge(engine, shaft):
    """The toolpost body ends 2 + 30 mm behind the nose centre (shank back face at
    functional - shank width, body 30 wide), and the 10 mm jaw is centred ``lead`` behind
    the cutting point: on the journal the nose centre is at the cutting point, so lead 37
    is flush; on the shoulder it sits a nose radius (0.4) further back, so all samples
    clear only from 37.4. Flush contact is no hit."""
    leads = (36.9, 37.0, 37.39, 37.4)
    holds = [_chuck(face_z=10.0, follow_rests=[_follow(lead)]) for lead in leads]
    ops = (result["ops"]["T1:10"] for result in _run(engine, shaft, holds, _ops()))
    results = dict(zip(leads, ops, strict=True))
    count = results[37.4]["sample_count"]
    assert results[36.9]["holder_hits"] == count
    assert 0 < results[37.39]["holder_hits"] < results[37.0]["holder_hits"] < count
    for lead in (36.9, 37.0, 37.39):
        # The jaw stands beside the toolpost body, above the insert's axial reach.
        assert results[lead]["obstacles"] == {"tool": [], "holder": [REST]}
        assert results[lead]["tool_hits"] == 0
    # Chuck placed and rest drawn: the clear samples are a certain pass.
    clear = results[37.4]
    assert clear["holder_hits"] == clear["tool_hits"] == 0
    assert clear["obstacles"] == {"tool": [], "holder": []}


def test_unserved_op_sees_the_rest_parked_and_a_missing_jaw_dimension_is_named(engine, shaft):
    missing = _follow(30.0, missing=["fixtures.fr.jaw_depth_mm (measured)"])
    del missing["jaw_depth_mm"]
    debt = "follow rest 'fr' not drawn: fixtures.fr.jaw_depth_mm (measured) unresolved"
    holds = [
        _chuck(face_z=10.0, follow_rests=[_follow(30.0)]),
        _chuck(face_z=10.0, follow_rests=[missing], debts=[debt]),
    ]
    served, unmeasured = _run(engine, shaft, holds, _ops(2))
    # A 30 mm lead puts the jaw inside the toolpost body at every T1:10 sample; T1:20 is
    # the same pass with the rest parked off the work.
    assert served["ops"]["T1:10"]["holder_hits"] == served["ops"]["T1:10"]["sample_count"]
    assert served["ops"]["T1:10"]["obstacles"]["holder"] == [REST]
    assert served["ops"]["T1:20"]["holder_hits"] == served["ops"]["T1:20"]["tool_hits"] == 0
    scene = served["setups"]["T1"]["render_scene"]
    (drawn,) = [c for c in scene["components"] if c["role"] == "follow_rest"]
    assert drawn["name"] == REST and drawn["exact"] is True and "T1:10" in drawn["pose"]
    assert served["setups"]["T1"]["fixture_rendered"] is True
    # Unmeasured jaws: the served op cannot pass, and the reason names the field.
    op = unmeasured["ops"]["T1:10"]
    assert op["tool_hits"] == op["holder_hits"] == "unknown"
    assert "fixtures.fr.jaw_depth_mm (measured)" in op["reasons"]["tool_hits"]
    assert unmeasured["ops"]["T1:20"]["tool_hits"] == 0
    setup = unmeasured["setups"]["T1"]
    assert setup["fixture_clash_debts"] == [debt] and setup["fixture_rendered"] is False
    assert not any(c["role"] == "follow_rest" for c in setup["render_scene"]["components"])


def test_a_follow_rest_is_drawn_where_its_jaws_go_on_beside_the_tool(engine, shaft):
    """The pass feeds z 40 -> 20; the trailing 10 mm jaw is centred 5 mm behind the cut.
    Declared to go on once the tool passes z 30, it is drawn there, riding the just-turned
    8 mm journal over z 30..40, never at whichever sample the pass checks first. An engage
    Z with no work to ride is not drawn, and the picture says so."""
    holds = [
        _chuck(face_z=10.0, follow_rests=[_follow(5.0, engage_at_z_mm=engage)])
        for engage in (30.0, 45.0)
    ]
    drawn, beyond = (result["setups"]["T1"] for result in _run(engine, shaft, holds, _ops()))
    (rest,) = [c for c in drawn["render_scene"]["components"] if c["role"] == "follow_rest"]
    assert "cutting at z 30.0 mm" in rest["pose"], rest["pose"]
    assert rest["box_mm"] == pytest.approx([4.0, -6.0, 30.0, 50.0, 6.0, 40.0], abs=1e-6)
    scene = beyond["render_scene"]
    assert not any(c["role"] == "follow_rest" for c in scene["components"])
    debt = f"{REST} not drawn for T1:10: no work diameter at its engage z 45.0 mm to ride"
    assert debt in scene["debts"], scene["debts"]


def test_steady_rest_ring_obstructs_the_ops_it_serves_and_is_drawn(engine, shaft):
    steady = {
        "name": "sr",
        "subjects": ["T1:10"],
        "at_z_mm": 30.0,
        "body_dia_mm": 60.0,
        "body_length_mm": 10.0,
    }
    (result,) = _run(engine, shaft, [_chuck(face_z=10.0, steady_rests=[steady])], _ops(2))
    served, parked = result["ops"]["T1:10"], result["ops"]["T1:20"]
    # The ring rides the Ø12 entry bar over z 25..35, right where the 8 mm journal is cut.
    assert served["obstacles"] == {"tool": [STEADY], "holder": [STEADY]}
    assert 0 < served["tool_hits"] < served["sample_count"]
    assert parked["tool_hits"] == parked["holder_hits"] == 0
    setup = result["setups"]["T1"]
    assert {"name": STEADY, "role": "rest", "exact": True} in setup["render_scene"]["components"]
    # Riding the bar is contact, not interpenetration.
    assert setup["fixture_clashes"] == [] and setup["fixture_rendered"] is True


def test_stock_profile_reports_the_least_radius_including_a_raw_collar(engine, shaft):
    # The bar starts 5 mm below the part: z -5..0 is a raw collar no op touches.
    collar = {**BAR, "origin_mm": [25.0, 0.0, 0.0], "length_mm": 45.0}
    plain, collared = (
        _run(engine, shaft, [_chuck(face_z=10.0)], _ops(), stock=stock)[0]["setups"]["T1"]
        for stock in (BAR, collar)
    )
    assert "stock_profile_reason" not in plain
    profile = plain["stock_profile"]
    # Entering Ø12 everywhere; after the pass the 8 mm journal is the least radius there,
    # while r_hi keeps the entering bar.
    assert profile[0] == [0.0, 20.0, 6.0, 6.0]
    assert profile[-1] == [pytest.approx(20.972232, abs=1e-5), 40.0, 4.0, 6.0]
    assert all(lo[1] == hi[0] for lo, hi in zip(profile, profile[1:], strict=False))
    assert collared["stock_profile"][0] == [-5.0, 20.0, 6.0, 6.0]
    assert collared["stock_profile"][1:] == profile[1:]
