"""All consumed recorded facts are actionable without executing native geometry."""

import json

import pytest
from test_measurement_checklist import checklist_plans

from prechips import cli, kernel
from prechips.inputs import load_bundle


@pytest.mark.parametrize("status", ["assumed", "illustrative", None])
def test_host_checklist_names_every_refused_record_and_clears_after_local_measurement(
    tmp_path, monkeypatch, capfd, status
):
    plan, _, inventory, _ = checklist_plans(tmp_path)
    bundle = load_bundle(plan)
    records = {}

    def measured(identity, value):
        metadata = {
            "by": "isolated synthetic shop",
            "date": "2026-10-11",
            "instrument": "synthetic calipers",
        }
        if status is not None:
            metadata["status"] = status
        record = {"value": value, "measured": metadata, "verify": False}
        records[identity] = record
        return record

    bundle.inventory["tools"]["endmill"] = {
        "kind": "endmill",
        "dia_mm": measured("tools.endmill.dia", 10),
        "flute_len_mm": measured("tools.endmill.flute_len", 25),
        "oal_mm": measured("tools.endmill.oal", 80),
    }
    bundle.inventory["holders"]["collet"] = {
        "kind": "collet",
        "gauge_dia_mm": measured("holders.collet.gauge_dia", 30),
        "gauge_len_mm": measured("holders.collet.gauge_len", 40),
        "grip_mm": measured("holders.collet.grip", 35),
    }
    solid = {
        "name": "pad",
        "shape": "box",
        "at_mm": [0, 0, -5],
        "size_mm": [100, 30, 5],
        "measured": measured("fixtures.plate.solids.pad", 0)["measured"],
    }
    records["fixtures.plate.solids.pad"] = solid
    bundle.inventory["fixtures"]["plate"] = {"kind": "custom", "solids": [solid]}
    bundle.plan["setups"][0]["hold"] = {
        "fixture": "plate",
        "pose": {"origin_mm": [0, 0, 0], "x": [1, 0, 0], "z": [0, 0, 1]},
    }
    monkeypatch.setattr(cli, "load_bundle", lambda *args, **kwargs: bundle)

    def native_forbidden(*args, **kwargs):
        pytest.fail("tools --measure must remain host-only, even on a cold kernel cache")

    monkeypatch.setattr(kernel, "discover_kernel", native_forbidden)
    monkeypatch.setattr(kernel, "_execute", native_forbidden)
    monkeypatch.setattr(kernel, "_read_cache", native_forbidden)
    arguments = ["tools", "--measure", "--json", "--plan", str(plan), "--inventory", str(inventory)]
    assert cli.main(arguments) == 0
    entries = json.loads(capfd.readouterr().out)
    recorded = {
        entry["id"] for entry in entries if entry.get("status") in {"assumed", "illustrative"}
    }
    assert recorded == set(records)
    assert all(
        (status or "assumed") in entry["instruction"] for entry in entries if entry["id"] in records
    )

    # Counterfactual test data only: the authored shop/trial inputs are never certified.
    for identity in recorded:
        records[identity]["measured"]["status"] = "measured"
    assert cli.main(arguments) == 0
    after = json.loads(capfd.readouterr().out)
    assert not ({entry["id"] for entry in after} & recorded)
    assert not any(entry.get("status") in {"assumed", "illustrative"} for entry in after)
