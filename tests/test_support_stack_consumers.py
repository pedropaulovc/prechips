"""The same bearing-role boundary governs envelope, saw headroom and guide scenes."""

from copy import deepcopy

import pytest
from test_envelope_m5 import bundle, measured
from test_mounted_saw_limits import mounted_bundle

from prechips.rules import envelope, guided_sweep, headroom


def posed(**source):
    return {
        "placement": "posed",
        "id": "independent-rest",
        **source,
        "pose": {"origin_mm": [120, 0, 0], "x": [1, 0, 0], "z": [0, 0, 1]},
        "note": "Independent obstacle beside the vise, not a bearing layer beneath it.",
    }


def add_supports(data, supports, *, riser=None):
    data.inventory["fixtures"]["bearing"] = {"kind": "spacer", "height_mm": measured(20)}
    data.inventory["fixtures"]["auxiliary"] = {"kind": "support", "height_mm": measured(900)}
    hold = data.plan["setups"][0]["hold"]
    hold["supports"] = supports
    if riser is not None:
        hold["riser"] = riser
    return hold


@pytest.mark.parametrize("source", [{"ref": "auxiliary"}, {"stock_ref": "earlier-output"}])
def test_envelope_never_resolves_a_posed_list_as_one_fixture_or_adds_its_height(source):
    data = bundle()
    hold = add_supports(data, [posed(**source)])
    original = deepcopy(hold)
    row = envelope.evaluate(data)[0]
    assert row.status == "pass", row.sentence
    assert row.numbers["stacks"][0]["stack_mm"] == 151
    assert row.numbers["stacks"][0]["spindle_nose_table_band_mm"] == [151, 156]
    assert not any("auxiliary.height" in entry["id"] for entry in row.numbers["measurements"])
    assert hold == original


@pytest.mark.parametrize(
    "supports",
    ["bearing", ["bearing"], [{"ref": "bearing"}], [posed(ref="auxiliary"), "bearing"]],
)
def test_envelope_preserves_one_actual_legacy_bearing_height(supports):
    data = bundle()
    add_supports(data, supports)
    row = envelope.evaluate(data)[0]
    assert row.status == "pass", row.sentence
    assert row.numbers["stacks"][0]["stack_mm"] == 171
    assert row.numbers["stacks"][0]["spindle_nose_table_band_mm"] == [171, 176]


@pytest.mark.parametrize("riser", ["bearing", "fixtures.bearing"])
@pytest.mark.parametrize("listed", [False, True])
def test_envelope_preserves_explicit_riser_without_double_counting_its_alias(riser, listed):
    data = bundle()
    supports = [posed(ref="auxiliary")]
    if listed:
        supports.append({"ref": "fixtures.bearing"})
    add_supports(data, supports, riser=riser)
    row = envelope.evaluate(data)[0]
    assert row.status == "pass", row.sentence
    assert row.numbers["stacks"][0]["stack_mm"] == 171


@pytest.mark.parametrize(
    "supports",
    [
        "unknown",
        [None],
        [{}],
        [{"ref": "bearing", "placement": "unposed"}],
        [{"ref": "bearing", "jaw_lead_mm": 5}],
        [{"ref": "bearing", "unsupported_role": "rest"}],
        ["bearing", "auxiliary"],
        ["bearing", "fixtures.bearing"],
        [posed(ref="missing")],
        [posed(ref="auxiliary"), posed(stock_ref="earlier-output")],
    ],
)
def test_envelope_unknown_or_ambiguous_roles_remain_debt_not_zero(supports):
    data = bundle()
    add_supports(data, supports)
    row = envelope.evaluate(data)[0]
    assert row.status == "unknown", row.sentence
    assert row.numbers["stacks"][0]["stack_mm"] == "unknown"
    assert row.numbers["measurements"]
    assert all(
        "{" not in entry["id"] and "[" not in entry["id"] for entry in row.numbers["measurements"]
    )


def test_envelope_retains_unmeasured_nominal_bearing_height_without_certifying_it():
    data = bundle()
    add_supports(data, [posed(ref="auxiliary"), "bearing"])
    data.inventory["fixtures"]["bearing"]["height_mm"] = 20
    row = envelope.evaluate(data)[0]
    assert row.status == "unknown"
    assert row.numbers["stacks"][0]["stack_mm"] == 171
    assert "fixtures.bearing.height" in {entry["id"] for entry in row.numbers["measurements"]}


def test_envelope_oriented_nominal_blocks_do_not_become_measured_height():
    data = bundle()
    add_supports(data, [{"ref": "bearing", "orientation": "1 in height"}])
    data.inventory["fixtures"]["bearing"] = {"kind": "blocks_123", "size_in": [1, 2, 3]}
    row = envelope.evaluate(data)[0]
    assert row.status == "unknown"
    assert row.numbers["stacks"][0]["stack_mm"] == pytest.approx(176.4)
    assert "fixtures.bearing.height" in {entry["id"] for entry in row.numbers["measurements"]}


def test_independent_auxiliary_verification_cannot_hide_a_known_envelope_limit_error():
    data = bundle()
    add_supports(data, [posed(ref="auxiliary")])
    data.inventory["fixtures"]["auxiliary"]["verify"] = True
    data.inventory["machines"]["mill"]["envelope"]["spindle_to_table_max_mm"] = measured(155)
    row = envelope.evaluate(data)[0]
    assert row.status == "error", row.sentence
    assert row.numbers["stacks"][0]["upper_margin_mm"] == -1


@pytest.mark.parametrize("rule", [envelope, headroom])
@pytest.mark.parametrize("riser", [None, "bearing"])
def test_mounted_saw_table_translation_uses_the_same_bearing_roles(monkeypatch, rule, riser):
    data, _ = mounted_bundle(monkeypatch)
    add_supports(data, [posed(ref="auxiliary")], riser=riser)
    original = deepcopy(data.kernel)
    row = rule.evaluate(data)[0]
    assert row.status == "pass", row.sentence
    expected = [112, 142] if riser is None else [132, 162]
    assert row.numbers["stacks"][0]["spindle_nose_table_band_mm"] == expected
    assert data.kernel == original


@pytest.mark.parametrize("rule", [envelope, headroom])
def test_mounted_saw_unknown_support_role_cannot_certify_table_translation(monkeypatch, rule):
    data, _ = mounted_bundle(monkeypatch)
    add_supports(data, [{"ref": "bearing", "jaw_lead_mm": 5}])
    row = rule.evaluate(data)[0]
    assert row.status == "unknown", row.sentence
    assert row.numbers["stacks"][0]["spindle_nose_table_band_mm"] == "unknown"


def roller_scene(data):
    data.inventory["fixtures"]["sled"] = {
        "kind": "arc_sled",
        "roller_dia_mm": measured(22),
        "roller_height_mm": measured(12),
        "bed_height_mm": measured(30),
        "rail_side": "outer",
    }
    numbers = {
        "arc_table": [
            {
                "op": 10,
                "centre_setup_xy": [0, 0],
                "arc_mid_setup_xy": [0, -800],
                "guided": {
                    "guide": "rail",
                    "fixture": "sled",
                    "rail_radius_mm": 850,
                    "rollers_deg": [-15, 15],
                },
            }
        ]
    }
    return guided_sweep.guide_scene(data, data.plan["setups"][0], numbers, 1)


@pytest.mark.parametrize("riser", [None, "bearing", "fixtures.bearing"])
def test_guide_roller_table_height_ignores_auxiliary_but_preserves_actual_riser(riser):
    data = bundle()
    supports = [posed(ref="auxiliary")]
    if riser is not None:
        supports.append({"ref": "bearing"})
    hold = add_supports(data, supports, riser=riser)
    original = deepcopy(hold)
    scene, notes = roller_scene(data)
    assert not notes
    assert len(scene["rollers"]) == 2
    expected = [-52, -40] if riser is None else [-72, -60]
    assert all(roller["z_mm"] == expected for roller in scene["rollers"])
    assert hold == original


@pytest.mark.parametrize(
    "supports",
    [["bearing", "auxiliary"], [{"ref": "bearing", "at_z_mm": 5}], [posed(ref="missing")]],
)
def test_unknown_bearing_role_leaves_guide_rollers_undrawn(supports):
    data = bundle()
    add_supports(data, supports)
    scene, notes = roller_scene(data)
    assert scene is None
    assert any("support blocks' height under the work is unknown" in note for note in notes)
