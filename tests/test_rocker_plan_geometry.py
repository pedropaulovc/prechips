"""The rocker route's upper strap operations claim the cuttable exported side."""

from pathlib import Path

from prechips.inputs import load_bundle
from prechips.kernel import run_geometry
from prechips.rules import accessibility

ROOT = Path(__file__).resolve().parents[1]


def test_rocker_upper_strap_claims_are_not_far_side_errors(monkeypatch, freecad_kernel):
    monkeypatch.setenv("FREECAD_CMD", freecad_kernel)
    bundle = load_bundle(ROOT / "examples/rocker-arm/plan.toml")
    # Whatever the current setup layout, every op naming exported strap faces claims its own side.
    claims = {
        f"{setup['id']}:{op['op']}": op["faces"]
        for setup in bundle.plan["setups"]
        for op in setup.get("ops", [])
        if op.get("feature") == "strap_datum_b" and op.get("faces")
    }
    assert claims, "the rocker route needs explicitly claimed strap faces"
    facts = run_geometry(bundle)
    assert facts["status"] == "ok"
    rows = {row.subject: row for row in accessibility.evaluate(bundle)}
    for subject, faces in claims.items():
        detail = facts["ops"][subject]
        assert all(face not in facts["mapping_errors"] for face in faces)
        expected_indices = {facts["mapping"][face] for face in faces}
        assert expected_indices
        assert detail["claim_errors"] == []
        assert not detail.get("mapping_errors")
        assert isinstance(detail["claimed_indices"], list)
        assert set(detail["claimed_indices"]) == expected_indices
        # Another physical obstacle may still make the operation inaccessible.
        row = rows[subject]
        assert not row.numbers.get("claim_errors"), row.sentence
        assert not row.numbers.get("mapping_errors"), row.sentence
