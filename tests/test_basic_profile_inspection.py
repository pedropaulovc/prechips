"""BASIC geometry is accepted through its owning profile, not a fitted-size gauge."""

from copy import deepcopy

import pytest
from test_practical_inspection import MEMBERS, practical_bundle
from test_surface_profile import PROFILE_OUTER, TOP_EDGE, bundle

from prechips.rules import inspection


CASES = [
    ("top_edge", "radius", TOP_EDGE, 800.0, [799.5, 800.0]),
    ("profile_outer", "bottom_radius", PROFILE_OUTER, 816.0, [815.5, 816.0]),
]


def profile_bundle(tmp_path, name, requirement, definition):
    loaded = bundle(tmp_path, {name: definition}, subject=name, requirement=requirement, gauge="cmm")
    feature = loaded.features["features"][name]
    feature["faces"] = ["#10"]
    gauge = loaded.inventory["gauges"]["gauge"]
    gauge["range_mm"] = [0.0, 500.0]
    # The bounded physical instrument reads the small profile deviation. Neither
    # its span nor an independent radius check needs to reach the BASIC radius.
    setup = loaded.plan["setups"][1]
    checkpoint = setup["ops"][-1]
    checkpoint["checks"] = {"surface_profile": "gauge"}
    checkpoint["inspection_methods"] = {
        "surface_profile": "Probe the bounded edge in datum frame A|B|C on the CMM."
    }
    return loaded, setup, checkpoint


def findings(loaded):
    return {row.subject: row for row in inspection.evaluate(loaded)}


@pytest.mark.parametrize("name,requirement,definition,basic,limits", CASES)
def test_bounded_cmm_accepts_basic_only_through_actual_profile(
    tmp_path, name, requirement, definition, basic, limits
):
    loaded, _, _ = profile_bundle(tmp_path, name, requirement, definition)
    original = deepcopy(loaded.features)
    rows = findings(loaded)
    profile_row = rows[f"{name}:surface_profile"]
    dependent = rows[f"{name}:{requirement}"]
    assert profile_row.status == "pass", profile_row.sentence
    assert profile_row.numbers["range_mm"] == [0.0, 500.0]
    assert dependent.status == "pass", dependent.sentence
    assert dependent.numbers["acceptance_basis"] == "governing_surface_profile"
    assert dependent.numbers["basic_value"] == basic
    assert dependent.numbers["limits"] == pytest.approx(limits)
    assert dependent.numbers["profile_band"]
    (check,) = dependent.numbers["governing_checks"]
    assert check["subject"] == profile_row.subject
    assert check["identity"] == profile_row.numbers["identity"]
    assert check["status"] == profile_row.status
    assert dependent.numbers["part_result"] == "not_recorded"
    assert loaded.features == original
    assert loaded.feature_definitions[name][requirement] == basic
    assert loaded.feature_definitions[name]["surface_profile_governs"] == original["features"][name]["surface_profile_governs"]
    assert loaded.feature_definitions[name]["faces"] == ["#10"]


@pytest.mark.parametrize(
    "mutation,status",
    [
        ("missing-check", "error"),
        ("missing-method", "unknown"),
        ("unknown-method", "unknown"),
        ("missing-datums", "unknown"),
        ("unknown-datum", "unknown"),
        ("untrusted", "unknown"),
        ("unknown-resolution", "unknown"),
        # Geometric capability remains unresolved when the zone is finer than
        # the instrument resolves; the dependent BASIC must inherit that refusal.
        ("insufficient-resolution", "unknown"),
        ("wrong-gauge-kind", "error"),
    ],
)
def test_dependent_basic_preserves_real_profile_refusals(tmp_path, mutation, status):
    loaded, _, checkpoint = profile_bundle(tmp_path, "top_edge", "radius", TOP_EDGE)
    feature = loaded.feature_definitions["top_edge"]
    gauge = loaded.inventory["gauges"]["gauge"]
    if mutation == "missing-check":
        # A valid independent form gauge cannot substitute for the absent profile.
        loaded.inventory["gauges"]["radius-template"] = {
            "kind": "profile_gauge", "range_mm": [0.0, 1000.0], "resolution_mm": 0.01
        }
        checkpoint["checks"] = {"radius": "radius-template"}
        checkpoint["inspection_methods"] = {"radius": "Compare the radius to the template."}
    elif mutation == "missing-method":
        checkpoint.pop("inspection_methods")
    elif mutation == "unknown-method":
        checkpoint["inspection_methods"]["surface_profile"] = "unknown"
    elif mutation == "missing-datums":
        feature.pop("surface_profile_datums")
    elif mutation == "unknown-datum":
        feature["surface_profile_datums"] = ["A", "unknown"]
    elif mutation == "untrusted":
        gauge["verify"] = True
    elif mutation == "unknown-resolution":
        gauge["resolution_mm"] = "unknown"
    elif mutation == "insufficient-resolution":
        gauge["resolution_mm"] = 0.6
    else:
        gauge["kind"] = "caliper"
    rows = findings(loaded)
    dependent = rows["top_edge:radius"]
    assert dependent.status == status, dependent.sentence
    assert dependent.numbers["acceptance_basis"] == "governing_surface_profile"
    assert dependent.numbers["basic_value"] == 800.0
    if mutation != "missing-check":
        assert rows["top_edge:surface_profile"].status == status
        assert any(check["status"] == status for check in dependent.numbers["governing_checks"])


def test_profile_checkpoint_on_another_feature_cannot_accept_basic(tmp_path):
    loaded, setup, checkpoint = profile_bundle(tmp_path, "top_edge", "radius", TOP_EDGE)
    other = deepcopy(loaded.feature_definitions["top_edge"])
    other.update(requirements=["surface_profile"], faces=["#11"])
    other.pop("surface_profile_governs")
    loaded.features["features"]["other_edge"] = other
    checkpoint["feature"] = "other_edge"
    setup["ops"].insert(-1, {"op": 45, "do": "profile", "feature": "other_edge"})
    rows = findings(loaded)
    assert rows["other_edge:surface_profile"].status == "pass"
    assert rows["top_edge:radius"].status == "error"
    assert all(
        check["identity"]["feature_owner"] == "top_edge"
        for check in rows["top_edge:radius"].numbers["governing_checks"]
    )


@pytest.mark.parametrize("second_checked,status", [(False, "error"), (True, "pass")])
def test_every_actual_governing_profile_owner_is_required(tmp_path, second_checked, status):
    loaded, setup, checkpoint = profile_bundle(tmp_path, "top_edge", "radius", TOP_EDGE)
    owner = deepcopy(loaded.feature_definitions["top_edge"])
    owner.update(
        requirements=["surface_profile"],
        faces=["#11"],
        surface_profile_governs={"top_edge:radius": "decreases"},
    )
    loaded.features["features"]["second_zone"] = owner
    if second_checked:
        second = deepcopy(checkpoint)
        second.update(op=70, feature="second_zone")
        setup["ops"].append(second)
    rows = findings(loaded)
    dependent = rows["top_edge:radius"]
    assert rows["top_edge:surface_profile"].status == "pass"
    assert dependent.status == status, dependent.sentence
    if second_checked:
        assert rows["second_zone:surface_profile"].status == "pass"
        assert {check["subject"] for check in dependent.numbers["governing_checks"]} == {
            "top_edge:surface_profile", "second_zone:surface_profile"
        }


def test_sibling_workpiece_profile_checkpoint_cannot_accept_uninspected_member(tmp_path):
    loaded, setup, checkpoint = profile_bundle(tmp_path, "top_edge", "radius", TOP_EDGE)
    registered = practical_bundle()
    loaded.plan["workpieces"] = deepcopy(registered.plan["workpieces"])
    # Keep the fixture's established registrations but isolate final inspection
    # from saw partitions and shared pre-separation preservation evidence.
    loaded.plan["setups"] = [setup]
    setup["id"] = "S1"
    setup.pop("stock_in", None)
    setup["ops"][0]["workpiece_faces"] = {member: ["#10"] for member in MEMBERS}
    checkpoint["inspect_workpieces"] = ["nut1"]
    rows = findings(loaded)
    assert rows["nut1/top_edge:surface_profile"].status == "pass"
    assert rows["nut1/top_edge:radius"].status == "pass"
    sibling = rows["nut2/top_edge:radius"]
    assert sibling.status != "pass"
    assert all(check["identity"]["workpiece"] != "nut1" for check in sibling.numbers["governing_checks"])
    status, message, nums = inspection.requirement_check(
        loaded, "top_edge", "radius", checkpoint, setup=setup, workpiece="nut2"
    )
    assert status == "error", message
    assert nums["identity"]["workpiece"] == "nut2"
    assert nums["acceptance_basis"] == "governing_surface_profile"
    status, message, nums = inspection.requirement_check(
        loaded, "top_edge", "radius", checkpoint, setup=setup
    )
    assert status == "pass", message
    assert nums["identity"]["workpiece"] == "nut1"


def test_later_surface_cut_invalidates_profile_and_dependent_basic(tmp_path):
    loaded, setup, _ = profile_bundle(tmp_path, "top_edge", "radius", TOP_EDGE)
    setup["ops"].append({"op": 90, "do": "profile", "feature": "top_edge"})
    rows = findings(loaded)
    assert rows["top_edge:surface_profile"].status == "error"
    assert rows["top_edge:radius"].status == "error"


def test_true_toleranced_size_still_requires_full_instrument_range(tmp_path):
    loaded, _, checkpoint = profile_bundle(tmp_path, "top_edge", "radius", TOP_EDGE)
    feature = loaded.feature_definitions["top_edge"]
    feature["radius"] = [799.5, 800.0]
    feature.pop("surface_profile_governs")
    checkpoint["checks"]["radius"] = "gauge"
    checkpoint["inspection_methods"]["radius"] = "Measure the radius on the CMM."
    rows = findings(loaded)
    assert rows["top_edge:surface_profile"].status == "pass"
    size = rows["top_edge:radius"]
    assert size.status == "error", size.sentence
    assert size.numbers["limits"] == [799.5, 800.0]
    assert size.numbers["range_mm"] == [0.0, 500.0]
    assert size.numbers.get("acceptance_basis") != "governing_surface_profile"


@pytest.mark.parametrize("span,status", [([0.0, 1000.0], "pass"), ([0.0, 500.0], "error")])
def test_process_hold_keeps_derived_band_and_independent_size_gauge(tmp_path, span, status):
    loaded, setup, _ = profile_bundle(tmp_path, "top_edge", "radius", TOP_EDGE)
    loaded.inventory["gauges"]["radius-template"] = {
        "kind": "profile_gauge", "range_mm": span, "resolution_mm": 0.01
    }
    cut = setup["ops"][0]
    cut["inspection_methods"] = {"radius": "Compare the cut radius against the template."}
    cut["process_holds"] = [{
        "feature": "top_edge", "requirement": "radius", "band": [799.6, 799.9],
        "gauge": "radius-template", "reason": "Leave a bounded finishing allowance."
    }]
    (hold,) = inspection.process_holds(loaded, setup, cut).numbers["process_holds"]
    assert hold["drawing_band"] == pytest.approx([799.5, 800.0])
    assert hold["inside_drawing_band"] is True
    assert hold["gauge_status"] == status, hold["gauge_message"]


@pytest.mark.parametrize("name,requirement,definition,basic,limits", CASES)
def test_public_requirement_check_uses_actual_same_operation_profile(
    tmp_path, name, requirement, definition, basic, limits
):
    loaded, setup, checkpoint = profile_bundle(tmp_path, name, requirement, definition)
    status, message, nums = inspection.requirement_check(
        loaded, name, requirement, checkpoint, setup=setup
    )
    profile_status, _, profile_nums = inspection.requirement_check(
        loaded, name, "surface_profile", checkpoint, setup=setup
    )
    assert status == profile_status == "pass", message
    assert nums["acceptance_basis"] == "governing_surface_profile"
    assert nums["basic_value"] == basic
    assert nums["limits"] == pytest.approx(limits)
    (check,) = nums["governing_checks"]
    assert check["identity"] == profile_nums["identity"]
    assert check["status"] == profile_status
    assert check["op"] == profile_nums["op"]


@pytest.mark.parametrize("radius_only", [False, True])
def test_public_requirement_check_cannot_borrow_later_profile_checkpoint(tmp_path, radius_only):
    loaded, setup, _ = profile_bundle(tmp_path, "top_edge", "radius", TOP_EDGE)
    loaded.inventory["gauges"]["radius-template"] = {
        "kind": "profile_gauge", "range_mm": [0.0, 1000.0], "resolution_mm": 0.01
    }
    earlier = {"op": 45, "do": "inspect", "feature": "top_edge"}
    if radius_only:
        earlier["checks"] = {"radius": "radius-template"}
        earlier["inspection_methods"] = {"radius": "Compare the radius to the template."}
    setup["ops"].insert(-1, earlier)
    # The route's real later profile is capable, but this API evaluates the
    # supplied checkpoint, not a different operation elsewhere on the route.
    assert findings(loaded)["top_edge:surface_profile"].status == "pass"
    status, message, nums = inspection.requirement_check(
        loaded, "top_edge", "radius", earlier, setup=setup
    )
    assert status == "unknown", message
    assert nums["acceptance_basis"] == "governing_surface_profile"
    assert nums["basic_value"] == 800.0
    assert all(check["status"] != "pass" for check in nums["governing_checks"])
