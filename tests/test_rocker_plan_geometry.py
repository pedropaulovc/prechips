"""The rocker route's upper strap operations claim the cuttable exported side."""

from test_kernel_geometry import FREECAD, needs_freecad

from prechips.inputs import load_bundle
from prechips.rules import accessibility


@needs_freecad
def test_rocker_upper_strap_claims_are_not_far_side_errors(tmp_path, monkeypatch):
    monkeypatch.setenv("FREECAD_CMD", FREECAD)
    monkeypatch.setenv("PRECHIPS_KERNEL_CACHE", str(tmp_path / "cache"))
    bundle = load_bundle("examples/rocker-arm/plan.toml")
    rows = {row.subject: row for row in accessibility.evaluate(bundle)}
    for subject in ("S1:20", "S1:25"):
        assert rows[subject].status == "unknown", rows[subject].sentence
        assert not rows[subject].numbers.get("claim_errors")
