"""Complete explicit-face ownership: an op owns every feature its explicit faces cover."""

from types import SimpleNamespace

import pytest

from prechips.rules import datum_consistency
from prechips.rules.geometry_common import finishing_subjects
from prechips.rules.resolution import UNKNOWN, operations

PROFILE = {"op": 40, "do": "finish_profile", "feature": "profile", "faces": ["P1", "P2", "L"]}


def bundle(*claimers, land_faces=("L",), land_kind="face"):
    """Hole S2:50 is positioned from datum A = ``land``; the land has no labeled op."""
    return SimpleNamespace(
        plan={
            "setups": [
                {"id": "S1", "ops": list(claimers)},
                {"id": "S2", "ops": [{"op": 50, "do": "drill", "feature": "hole"}]},
            ]
        },
        features={
            "datums": {"A": {"feature": "land"}},
            "features": {
                "profile": {"kind": "profile", "faces": ["P1", "P2"]},
                "land": {
                    "kind": land_kind,
                    "faces": list(land_faces) if isinstance(land_faces, tuple) else land_faces,
                },
                "hole": {
                    "kind": "hole",
                    "faces": ["H"],
                    "position_datums": ["A"],
                    "position_dia": 0.2,
                },
            },
        },
        policy={"numbers": {"refixture_budget_mm": 0.05}},
    )


def hole_row(data):
    return next(row for row in datum_consistency.evaluate(data) if row.subject == "hole")


def test_complete_explicit_claim_owns_an_unlabeled_datum():
    data = bundle(PROFILE)
    row = hole_row(data)
    assert row.numbers["datums"]["A"] == ["S1:40"]
    assert row.status == "pass"
    # The label stays authoritative for label-scoped callers; ownership is opt-in.
    assert operations(data, "land") == []
    assert [op["op"] for _, op in operations(data, "land", owned=True)] == [40]
    assert "S1:40" in finishing_subjects(data)


@pytest.mark.parametrize(
    ("claim", "land_faces"),
    [
        (["P1", "P2"], ("L",)),  # partial: the land face is not claimed
        (["P1", "L"], ("L", "L2")),  # partial: one of two land faces
        ([], ("L",)),  # empty explicit claim
        (UNKNOWN, ("L",)),  # unknown explicit claim
        (["P1", UNKNOWN, "L"], ("L",)),  # an unknown member poisons the claim
        (["P1", "P2", "L"], UNKNOWN),  # the feature's own faces are unknown
        (["P1", "P2", "L"], ()),  # a feature with no declared faces is never owned
    ],
)
def test_incomplete_or_unknown_claims_never_own(claim, land_faces):
    row = hole_row(bundle({**PROFILE, "faces": claim}, land_faces=land_faces))
    assert row.numbers["datums"]["A"] == []
    assert row.status == "unknown"


def test_implicit_feature_faces_never_own_another_feature():
    # Without explicit faces the op claims its own feature's faces, which never name the land.
    labeled = {key: value for key, value in PROFILE.items() if key != "faces"}
    data = bundle(labeled)
    data.features["features"]["profile"]["faces"] = ["P1", "P2", "L"]
    assert hole_row(data).numbers["datums"]["A"] == []


@pytest.mark.parametrize("action", ["rough_profile", "inspect", "coating", "deburr", "spot"])
def test_nonforming_owner_is_not_a_final_cut(action):
    row = hole_row(bundle({**PROFILE, "do": action}))
    assert row.numbers["datums"]["A"] == []
    assert row.status == "unknown"


def test_hole_family_feature_is_owned_only_by_a_complete_form_action():
    data = bundle(PROFILE, land_kind="hole")
    assert hole_row(data).numbers["datums"]["A"] == []
    data = bundle({**PROFILE, "do": "bore"}, land_kind="hole")
    assert hole_row(data).numbers["datums"]["A"] == ["S1:40"]


def test_owned_ream_still_demotes_the_labeled_drill_pilot():
    pilot = {"op": 10, "do": "drill", "feature": "land"}
    ream = {"op": 20, "do": "ream", "feature": "other", "faces": ["L"]}
    data = bundle(pilot, ream, land_kind="hole")
    assert hole_row(data).numbers["datums"]["A"] == ["S1:20"]
    assert hole_row(bundle(pilot, land_kind="hole")).numbers["datums"]["A"] == ["S1:10"]
