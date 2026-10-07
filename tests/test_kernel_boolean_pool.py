"""Pool workers answer the engine's independent booleans without changing a fact.

The engine hands checkpoint rows and culled cylinder booleans to ``freecadcmd`` worker
processes (``src/prechips/kernel/boolean_pool.py``). ``PRECHIPS_KERNEL_POOL_WAIT`` makes the
engine take every pooled boolean from a worker, so the same batch run with and without
workers must print the same facts while the pooled run reports worker answers. Runs
``freecad_job.py`` under ``freecadcmd`` and skips without it.
"""

import subprocess

import pytest
from test_kernel_checkpoints import _AUTHOR, MITER, WEST, _bounded, _clamped, _job, _profile
from test_kernel_geometry import Engine


@pytest.fixture(scope="module")
def island(tmp_path_factory, freecad_kernel):
    directory = tmp_path_factory.mktemp("pool-solids")
    script = directory / "author.py"
    script.write_text(_AUTHOR, encoding="utf-8")
    process = subprocess.run(
        [freecad_kernel, str(script), "--", str(directory)],
        capture_output=True,
        text=True,
        errors="replace",
        timeout=300,
    )
    step = directory / "island.step"
    assert step.exists(), process.stdout[-2000:] + process.stderr[-2000:]
    return step


def _facts(response):
    """The batch's results without their non-operative timing."""
    return [{k: v for k, v in result.items() if k != "timing"} for result in response["results"]]


def test_pooled_booleans_keep_every_fact_of_a_checkpointed_and_sampled_batch(
    tmp_path, freecad_kernel, island, monkeypatch
):
    engine = Engine(tmp_path, freecad_kernel)
    # A finish profile whose corner miter lies under a later press pad (rule A' judges its
    # pooled removal against the later setup) and a bounded rough profile (its rows' rough
    # leave windows); both sample the west wall, so reach and pose booleans pool too.
    miter = _profile(3.0, MITER, tip=10.0, overshoot={"S1:10 finish line -X[2]"})
    rough = _bounded([("line -X", [(1.5, 0.0), (1.5, 15.0)])])
    batch = {
        "jobs": [
            _job(engine, island, [miter], later=_clamped((2.0, 50.0)), west=WEST),
            _job(engine, island, [rough], west=WEST),
        ],
        "timing": True,
    }
    monkeypatch.setenv("PRECHIPS_KERNEL_WORKERS", "0")
    alone = engine.run(batch)
    monkeypatch.setenv("PRECHIPS_KERNEL_WORKERS", "2")
    monkeypatch.setenv("PRECHIPS_KERNEL_POOL_WAIT", "1")
    pooled = engine.run(batch)
    assert alone["timing"]["pool_answers"] == 0
    assert pooled["timing"]["pool_answers"] > 0
    assert _facts(pooled) == _facts(alone)
    errors = pooled["results"][0]["ops"]["S1:10"]["checkpoint_errors"]
    assert [error.get("later_setup") for error in errors] == ["S2"], errors
