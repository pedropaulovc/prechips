"""Selected profile faces require native circular association, not label guesses."""

from copy import deepcopy
from dataclasses import replace

import pytest
from test_geometry_rules import rules_bundle
from test_manual_arc import joined_chain_plan

from prechips.inputs import load_bundle
from prechips.kernel import table_checkpoints
from prechips.rules import coordinates, coverage, finish_coverage

REFS = ["#11", "#22", "#33"]


def _bundle(tmp_path, selected):
    data = load_bundle(joined_chain_plan(tmp_path))
    data.features["features"]["target"]["faces"] = REFS.copy()
    operation = data.plan["setups"][0]["ops"][0]
    operation["faces"] = selected
    operation["contour"] = {
        "method": "guided_sweep",
        "step_deg": 1.0,
        "sweep": {"sweep_deg": 80.0},
    }
    return data


def _row(data, monkeypatch, *, pre_kernel=False):
    # Isolate association from guide commissioning and the independent guide recipe.
    monkeypatch.setattr(coordinates, "_manual", lambda *args: ([], []))
    return next(
        row for row in coordinates.evaluate(data, pre_kernel=pre_kernel) if row.subject == "S1"
    )


@pytest.mark.parametrize("selected", [["#22"], ["#11", "#22"]])
def test_candidate_uses_source_arc_without_guessing_selected_types(tmp_path, monkeypatch, selected):
    data = _bundle(tmp_path, selected)
    original = deepcopy(data.features)
    row = _row(data, monkeypatch, pre_kernel=True)
    assert row.numbers["arc_table"]
    assert not row.numbers["line_table"]
    arc = row.numbers["arc_table"][0]
    assert arc["profile_subset_arc"]["radius"] == 20.0
    assert arc["profile_subset_arc"]["sweep_deg"] != 0
    assert data.features == original
    payload = table_checkpoints("S1:20", row.numbers, 20, "mm")
    assert payload["paths"]
    assert all(
        path["profile_subset_arc_mm"] == arc["profile_subset_arc"] for path in payload["paths"]
    )
    inch_payload = table_checkpoints("S1:20", row.numbers, 20, "in")
    for path in inch_payload["paths"]:
        associated = path["profile_subset_arc_mm"]
        source = arc["profile_subset_arc"]
        assert associated["centre"] == pytest.approx([v * 25.4 for v in source["centre"]])
        assert associated["radius"] == pytest.approx(source["radius"] * 25.4)
        assert associated["start_deg"] == source["start_deg"]
        assert associated["sweep_deg"] == source["sweep_deg"]


def test_full_selection_keeps_complete_joins(tmp_path, monkeypatch):
    data = _bundle(tmp_path, REFS.copy())
    row = _row(data, monkeypatch, pre_kernel=True)
    assert len(row.numbers["line_table"]) == 2
    assert all("profile_subset_arc" not in arc for arc in row.numbers["arc_table"])


@pytest.mark.parametrize(
    "proof",
    [
        None,
        {},
        {"status": "unknown", "reason": "unmapped face"},
        {"status": "error", "reason": "selected face is planar"},
    ],
)
def test_public_subset_withheld_until_native_association(tmp_path, monkeypatch, proof):
    data = _bundle(tmp_path, ["#22"])
    details = {} if proof is None else {"profile_subset": proof}
    data = replace(data, kernel={"status": "ok", "ops": {"S1:20": details}})
    row = _row(data, monkeypatch)
    assert not row.numbers["arc_table"]
    assert not row.numbers["line_table"]
    key = "arc_errors" if proof and proof.get("status") == "error" else "arc_debts"
    assert row.numbers[key]


def test_public_circular_subset_released_only_after_native_proof(tmp_path, monkeypatch):
    data = _bundle(tmp_path, ["#22"])
    data = replace(
        data,
        kernel={
            "status": "ok",
            "ops": {"S1:20": {"profile_subset": {"status": "ok", "claimed_indices": [2]}}},
        },
    )
    row = _row(data, monkeypatch)
    assert row.numbers["arc_table"]
    assert not row.numbers["line_table"]


@pytest.mark.parametrize("selected", [None, "unknown", [], ["#999"], REFS.copy()])
def test_only_a_proper_known_subset_requests_arc_association(selected):
    assert not coordinates._profile_face_subset({"faces": REFS}, {"faces": selected})


@pytest.mark.parametrize("rule", [coverage, finish_coverage])
def test_subset_never_credits_unselected_faces(tmp_path, rule):
    data = rules_bundle(tmp_path)
    feature = data.features["features"]["pocket"]
    feature["faces"] = ["#1", "#3"]
    data.kernel["mapping"]["#3"] = 3
    data.kernel["faces"].append({"ref": "#3", "index": 3})
    data.kernel["features"]["pocket"] = [1, 3]
    operation = data.plan["setups"][0]["ops"][0]
    operation["faces"] = ["#1"]
    data.kernel["ops"]["S1:10"]["profile_subset"] = {
        "status": "ok",
        "claimed_indices": [1],
    }
    [row] = rule.evaluate(data)
    assert row.status == "error"
    key = "unclaimed_indices" if rule is coverage else "uncovered_faces"
    assert row.numbers[key] == [3]
    data.plan["setups"][0]["ops"].append({**operation, "op": 30, "faces": ["#3"]})
    data.kernel["ops"]["S1:30"] = {"claimed_indices": [3], "claim_errors": []}
    [complete] = rule.evaluate(data)
    assert complete.status == "pass"
    assert feature["faces"] == ["#1", "#3"]
