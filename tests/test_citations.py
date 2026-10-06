"""Incomplete citation lists retain usable source evidence across M2 consumers."""

from test_lathe_m2 import bundle as lathe_bundle
from test_physics_m2 import DIA_CITE, ROW_CITE, turning_bundle

from prechips.rules import stickout, turning_deflection


def test_deflection_retains_known_sources_in_incomplete_citation_lists():
    bundle = turning_bundle()
    bundle.cutting_data["material"][0]["cite"] = ["unknown", ROW_CITE, " "]
    bundle.features["features"]["journal"]["cite"]["dia"] = [DIA_CITE, "unknown"]

    finding = turning_deflection.evaluate(bundle)[0]

    assert finding.status == "warn"
    assert finding.numbers["deflection_mm"] > finding.numbers["acceptance_threshold_mm"]
    assert ROW_CITE in finding.cite
    assert DIA_CITE in finding.cite
    assert "unknown" not in finding.cite


def test_blank_policy_citation_cannot_approve_a_stickout_limit():
    bundle = lathe_bundle()
    bundle.policy["numbers_cite"]["stickout_ld_max"] = [" ", "unknown"]

    finding = stickout.evaluate(bundle)[0]

    assert finding.status == "unknown"
    assert finding.numbers["unsupported_limit_mm"] == "unknown"
