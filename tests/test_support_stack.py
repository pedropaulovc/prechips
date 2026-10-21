"""The shared support contract selects bearing references, never native obstacles."""

from copy import deepcopy

import pytest
from test_headroom import bundle, measured
from test_headroom_placed_support import posed

from prechips.rules._support_stack import bearing_layers, support_height


@pytest.mark.parametrize("supports", [None, "none", "not_applicable", []])
def test_absent_supports_have_no_bearing_layer(supports):
    assert bearing_layers(bundle(), {"supports": supports}) == ([], [])


@pytest.mark.parametrize("reference", ["blocks", "fixtures.blocks"])
def test_legacy_layer_retains_its_field_reference_and_authored_orientation(reference):
    hold = {
        "supports": [posed(ref="blocks"), {"ref": reference, "orientation": "2 in height"}],
        "support_orientation": "1 in height",
    }
    original = deepcopy(hold)
    assert bearing_layers(bundle(), hold) == ([("supports", reference, "2 in height")], [])
    assert hold == original


@pytest.mark.parametrize("supports", [None, [], [posed(ref="blocks")], ["blocks"]])
def test_explicit_riser_selects_one_layer_and_deduplicates_a_matching_support(supports):
    hold = {
        "supports": supports,
        "riser": "fixtures.blocks",
        "support_orientation": "1 in height",
    }
    assert bearing_layers(bundle(), hold) == ([("riser", "fixtures.blocks", "1 in height")], [])


@pytest.mark.parametrize("source", [{"ref": "blocks"}, {"stock_ref": "earlier-output"}])
def test_structurally_valid_auxiliary_leaves_pose_and_geometry_debt_to_native(source):
    auxiliary = posed(**source)
    auxiliary["pose"] = "unknown"
    data = bundle()
    data.inventory["fixtures"]["blocks"]["verify"] = True
    hold = {"supports": [auxiliary]}
    original = deepcopy((data.inventory, hold))
    assert bearing_layers(data, hold) == ([], [])
    assert (data.inventory, hold) == original


@pytest.mark.parametrize(
    "supports",
    [
        [None],
        [{}],
        [{"ref": "blocks", "unsupported_role": "rest"}],
        [posed(ref="missing")],
        [posed(ref="unknown")],
        [posed(ref="blocks", stock_ref="earlier-output")],
        [posed(ref="blocks"), posed(stock_ref="earlier-output")],
        ["blocks", "fixtures.blocks"],
    ],
)
def test_malformed_or_ambiguous_supports_return_plain_issues_not_raw_references(supports):
    hold = {"supports": supports, "support_orientation": "1 in height"}
    original = deepcopy(hold)
    layers, issues = bearing_layers(bundle(), hold)
    assert len(layers) <= 1
    assert issues
    assert all(
        field in ("supports", "riser") and isinstance(reason, str) for field, reason in issues
    )
    assert all(isinstance(reference, str) for _, reference, _ in layers)
    assert hold == original


@pytest.mark.parametrize("source", ["unknown", {}, {"kind": "unknown", "height_mm": 5}])
def test_unknown_inventory_source_is_not_a_known_auxiliary_or_bearing_layer(source):
    data = bundle()
    data.inventory["fixtures"]["blocks"] = source
    for supports in ([posed(ref="blocks")], ["blocks"]):
        layers, issues = bearing_layers(data, {"supports": supports})
        assert layers == []
        assert issues


def test_deduplication_preserves_inventory_member_identity():
    data = bundle()
    data.inventory["fixtures"]["levels"] = {"kind": "parallels_set", "heights_in": [1, 2]}
    selected = ("riser", "fixtures.levels/1in", None)
    layers, issues = bearing_layers(
        data, {"supports": ["levels/1in"], "riser": "fixtures.levels/1in"}
    )
    assert (layers, issues) == ([selected], [])
    layers, issues = bearing_layers(
        data, {"supports": ["levels/2in"], "riser": "fixtures.levels/1in"}
    )
    assert layers == [selected]
    assert issues


@pytest.mark.parametrize(
    ("item", "orientation", "expected"),
    [
        ({"height_mm": 7, "size_in": [1, 2, 3]}, "2 in height", 7),
        ({"height_mm": measured(8)}, None, 8),
        ({"height_in": "1/2"}, None, 12.7),
        ({"size_in": [0.5, 1, 2]}, "1/2 in height", 12.7),
        ({"size_in": [1, 2, 3]}, "2 in height", 50.8),
        ({"size_in": [1, 2, 3]}, None, "unknown"),
        ({"size_in": [1, 2, 3]}, "4 in height", "unknown"),
        ({"size_in": [1, 2, 3]}, "1/0 in height", "unknown"),
        ({"size_in": [1, 2, 3]}, "unknown", "unknown"),
        ({"height_mm": True}, None, "unknown"),
        (None, None, "unknown"),
    ],
)
def test_support_height_retains_the_existing_nominal_and_orientation_policy(
    item, orientation, expected
):
    original = deepcopy(item)
    assert support_height(item, orientation) == expected
    assert item == original
