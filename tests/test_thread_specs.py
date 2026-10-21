"""Nominal thread diameters have explicit millimetre units, not fit certification."""

import pytest

from prechips.thread_specs import basic_major_mm, selected_class_status


@pytest.mark.parametrize(
    "designation,diameter_mm",
    [
        ("3/8-16 UNC", 9.525),
        (".375-16", 9.525),
        ("1-8 UNC", 25.4),
        ("#10-24 UNC", 4.826),
        ("#0-80 UNF", 1.524),
        ("M6x1", 6.0),
        (" m12.5 × 1.25 ", 12.5),
    ],
)
def test_basic_major_is_always_mm(designation, diameter_mm):
    assert basic_major_mm(designation) == pytest.approx(diameter_mm)


@pytest.mark.parametrize(
    "designation",
    [
        "unknown",
        "",
        None,
        42,
        [],
        {},
        "M6",
        "M6x0",
        "1/0-20",
        "0/4-20",
        "3/8-0",
        "#7-24",
        "#010-24",
        "3/8-16 2B RH",
        "9" * 400 + "-1",
        "M" + "9" * 400 + "x1",
    ],
)
def test_basic_major_does_not_infer_unsupported_or_missing_identity(designation):
    assert basic_major_mm(designation) is None


@pytest.mark.parametrize(
    "feature,tool,acceptance,expected",
    [
        ({"thread_class": "2B"}, {"thread_class": "2b"}, "formal", "match"),
        ({"thread_class": "2B"}, {"thread_class": "3B"}, "manual_functional", "mismatch"),
        ({"requirements": []}, {}, "manual_functional", "not_adopted"),
        ({"requirements": ["dia"]}, {}, "manual_functional", "not_adopted"),
        ({"requirements": []}, {}, "formal", "unknown"),
        ({}, {}, "manual_functional", "unknown"),
        ({"requirements": "unknown"}, {}, "manual_functional", "unknown"),
        ({"requirements": ["unknown"]}, {}, "manual_functional", "unknown"),
        ({"requirements": ["thread_class"]}, {}, "manual_functional", "unknown"),
        ({"requirements": [], "thread_class": "unknown"}, {}, "manual_functional", "unknown"),
        ({"requirements": []}, {"thread_class": "unknown"}, "manual_functional", "unknown"),
        ({"requirements": [], "thread_class": "2B"}, {}, "manual_functional", "unknown"),
        ({"requirements": []}, {"thread_class": "2B"}, "manual_functional", "unknown"),
        (
            {"requirements": [], "thread_class": "unknown"},
            {"thread_class": "unknown"},
            "manual_functional",
            "unknown",
        ),
        ({"requirements": []}, {}, True, "unknown"),
        ({"requirements": []}, {}, "unknown", "unknown"),
    ],
)
def test_selected_class_policy_preserves_absence_unknown_and_contradiction(
    feature, tool, acceptance, expected
):
    assert selected_class_status(feature, tool, acceptance=acceptance) == expected
