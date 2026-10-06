"""The rocker route's upper strap operations claim the cuttable exported side."""

from pathlib import Path

from prechips.inputs import load_bundle
from prechips.rules import accessibility

ROOT = Path(__file__).resolve().parents[1]


def test_rocker_upper_strap_claims_are_not_far_side_errors(tmp_path, monkeypatch, freecad_kernel):
    monkeypatch.setenv("FREECAD_CMD", freecad_kernel)
    monkeypatch.setenv("PRECHIPS_KERNEL_CACHE", str(tmp_path / "cache"))
    bundle = load_bundle(ROOT / "examples/rocker-arm/plan.toml")
    # Whatever the current setup layout, every op naming exported strap faces claims its own side.
    claims = {
        f"{setup['id']}:{op['op']}": op["faces"]
        for setup in bundle.plan["setups"]
        for op in setup.get("ops", [])
        if op.get("feature") == "strap_datum_b" and op.get("faces")
    }
    assert claims, "the rocker route needs explicitly claimed strap faces"
    rows = {row.subject: row for row in accessibility.evaluate(bundle)}
    for subject, faces in claims.items():
        row = rows[subject]
        assert not row.numbers.get("claim_errors"), row.sentence
        if row.status == "error":
            assert not any(face in row.sentence for face in faces), row.sentence
