"""Bounded turning poses follow the cut window, not a claimed face's full extent.

The journal is one continuous face (r4, z0..60) ending at an integral r25 boss.
The boss stays protected in every case; only the domain where the tool is posed changes.
"""

import subprocess

import pytest
from test_kernel_geometry import Engine
from test_turning_geometry import _lathe, _turn

_AUTHOR = r"""
import sys
import FreeCAD, Part
V = FreeCAD.Vector
path = sys.argv[sys.argv.index("--") + 1]
shape = Part.makeCylinder(4, 60).fuse(Part.makeCylinder(25, 10, V(0, 0, 60)))
shape = shape.removeSplitter()
assert shape.isValid() and len(shape.Solids) == 1
shape.exportStep(path)
lateral = Part.makeCylinder(4, 70).fuse(
    Part.makeCylinder(6, 25, V(0, 0, 55), V(1, 0, 0))
).removeSplitter()
assert lateral.isValid() and len(lateral.Solids) == 1
lateral.exportStep(path.replace("journal.step", "lateral.step"))
"""


@pytest.fixture(scope="module")
def boss_journal(tmp_path_factory, freecad_kernel):
    directory = tmp_path_factory.mktemp("turn-sample-domain")
    script, step = directory / "author.py", directory / "journal.step"
    script.write_text(_AUTHOR, encoding="utf-8")
    process = subprocess.run(
        [freecad_kernel, str(script), "--", str(step)],
        capture_output=True,
        text=True,
        errors="replace",
        timeout=300,
    )
    assert step.exists(), process.stdout[-2000:] + process.stderr[-2000:]
    return step


@pytest.fixture
def bounded_turn(tmp_path, freecad_kernel, boss_journal):
    engine = Engine(tmp_path, freecad_kernel)
    journal = engine.refs(boss_journal, (-4, -4, 0), (4, 4, 60), kind="Cylinder")
    assert len(journal) == 1

    def run(**window):
        job = engine.job(
            boss_journal,
            {"journal": journal},
            [_lathe([_turn("S1:10", "journal", **window)])],
        )
        result = engine.run(job)
        assert result["status"] != "error", result.get("reason")
        return result["ops"]["S1:10"]

    return run


@pytest.mark.parametrize("ends", [(10.0, 0.0), (0.0, 10.0), (10.03, 10.01)])
def test_window_excludes_remote_boss_without_losing_narrow_profile_samples(bounded_turn, ends):
    facts = bounded_turn(z_from=ends[0], z_to=ends[1])
    # This fails before the fix: the full journal poses at z60 meet the boss
    # despite a cut confined to z0..10.
    assert facts["min_hits"]["tool"] == facts["min_hits"]["holder"] == 0
    assert facts["holder_wall_hits"] == 0
    assert facts["reach_depth_mm"] == pytest.approx(0.0, abs=1e-3)
    assert facts["sample_count"] > 0  # even a window narrower than the 1 mm grid
    assert facts["nose_z_mm"][0] >= min(ends) - 1.0
    assert facts["nose_z_mm"][1] <= max(ends) + 1.0
    assert {pose["end"] for pose in facts["window_poses"]} == {"z_from", "z_to"}


def test_no_window_still_checks_the_whole_claimed_journal(bounded_turn):
    facts = bounded_turn()
    assert facts["min_hits"]["tool"] > 0
    assert facts["min_hits"]["holder"] > 0
    assert facts["nose_z_mm"][1] >= 60.0


def test_in_window_boss_holder_collision_is_not_clipped(bounded_turn):
    facts = bounded_turn(z_from=60.0, z_to=59.0)
    # The sample is in the journal window, but its holder extends into the boss
    # beyond z60: clipping the obstacle or tool would hide real hits.
    assert facts["min_hits"]["tool"] > 0
    assert facts["min_hits"]["holder"] > 0
    assert facts["holder_wall_hits"] > 0


def test_commanded_endpoints_outside_the_claim_still_collide_with_the_boss(bounded_turn):
    facts = bounded_turn(z_from=61.0, z_to=60.5)
    # No journal face lies in this interval. Both explicit endpoint poses must
    # nevertheless ride its radius and meet the protected boss, not vanish.
    assert facts["sample_count"] == 0
    assert facts["min_hits"]["tool"] > 0
    assert facts["min_hits"]["holder"] > 0
    assert len(facts["window_poses"]) == 2
    assert all("part" in pose["meets"] for pose in facts["window_poses"])


def test_remote_lateral_boss_does_not_become_buried_depth_for_a_bounded_cut(
    tmp_path, freecad_kernel, boss_journal
):
    engine = Engine(tmp_path, freecad_kernel)
    step = boss_journal.with_name("lateral.step")
    journal = engine.refs(step, (-4, -4, 0), (4, 4, 70), kind="Cylinder")
    assert len(journal) == 1

    def run(**window):
        return engine.run(
            engine.job(
                step, {"journal": journal}, [_lathe([_turn("S1:10", "journal", **window)])]
            )
        )["ops"]["S1:10"]

    # This radial boss obscures part, not all, of the journal's continuous face.
    # Its r4 samples at z55 are buried under the boss's swept radial envelope;
    # unlike a shoulder tangent, the nose cannot slide clear by its corner radius.
    bounded = run(z_from=10.0, z_to=0.0)
    whole = run()
    at_boss = run(z_from=55.0, z_to=54.0)
    assert bounded["reach_depth_mm"] == pytest.approx(0.0, abs=1e-3)
    assert bounded["min_hits"]["tool"] == bounded["min_hits"]["holder"] == 0
    for facts in (whole, at_boss):
        assert facts["reach_depth_mm"] > 20.0
        assert facts["min_hits"]["tool"] > 0
        assert facts["min_hits"]["holder"] > 0
