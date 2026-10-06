"""Saw cut-off must preserve target stock and retain concrete input debt."""

from types import SimpleNamespace

import pytest
from pydantic import ValidationError
from test_input_contracts import PLAN, bundle_files

from prechips.inputs import BadInput, load_bundle
from prechips.model import Inventory, Operation
from prechips.rules.saw_cut import evaluate


def bundle():
    return SimpleNamespace(
        plan={
            "setups": [
                {
                    "id": "S1",
                    "machine": "saw",
                    "ops": [
                        {
                            "op": 10,
                            "do": "saw_cut",
                            "tool": "blade",
                            "cut_plane": {"axis": "y", "value": 87.75, "keep": "below"},
                        }
                    ],
                }
            ]
        },
        inventory={
            "machines": {"saw": {"kind": "bandsaw", "blade_speed_sfm": [50, 200]}},
            "tools": {"blade": {"kind": "bandsaw", "kerf_mm": 1.5}},
        },
        features={"features": {}},
        kernel={
            "status": "ok",
            "ops": {
                "S1:10": {
                    "cut_plane": {"axis": "y", "value": 87.75, "keep": "below"},
                    "kerf_mm": 1.5,
                    "retained_boundary_mm": 87,
                    "kerf_volume_mm3": 15,
                    "offcut_volume_mm3": 25,
                    "removed_volume_mm3": 40,
                    "stock_volume_before_mm3": 140,
                    "stock_volume_after_mm3": 100,
                }
            },
        },
    )


def test_known_native_saw_volumes_preserve_target_and_report_retained_boundary():
    finding = evaluate(bundle())[0]
    assert finding.status == "pass"
    assert finding.numbers["retained_boundary_mm"] == 87
    assert finding.numbers["removed_volume_mm3"] == 40
    assert finding.numbers["stock_volume_after_mm3"] == 100


@pytest.mark.parametrize("kerf", [0, -1])
def test_nonpositive_known_blade_kerf_is_error(kerf):
    data = bundle()
    data.inventory["tools"]["blade"]["kerf_mm"] = kerf
    assert evaluate(data)[0].status == "error"


def test_unverified_blade_kerf_cannot_pass_from_stale_native_facts():
    data = bundle()
    data.inventory["tools"]["blade"]["kerf_mm"] = {"value": 1.5, "verify": True}
    assert evaluate(data)[0].status == "unknown"


@pytest.mark.parametrize("field", ["kerf_mm", "removed_volume_mm3", "stock_volume_after_mm3"])
def test_incomplete_native_saw_stock_stays_unknown(field):
    data = bundle()
    del data.kernel["ops"]["S1:10"][field]
    assert evaluate(data)[0].status == "unknown"


@pytest.mark.parametrize("reason", ["kerf intersects finished target", "cut removes all stock"])
def test_native_geometric_saw_refusal_is_error(reason):
    data = bundle()
    data.kernel["ops"]["S1:10"]["saw_error"] = reason
    assert evaluate(data)[0].status == "error"


@pytest.mark.parametrize("kind", ["lathe", "drill_press"])
def test_saw_does_not_apply_on_incompatible_machine(kind):
    data = bundle()
    data.inventory["machines"]["saw"]["kind"] = kind
    assert evaluate(data)[0].status == "error"


def test_missing_upstream_stock_and_unavailable_kernel_remain_debt():
    data = bundle()
    data.kernel["ops"]["S1:10"]["saw_reason"] = "upstream stock undeclared"
    assert evaluate(data)[0].status == "unknown"
    data.kernel = {"status": "unknown", "kernel_unavailable": True}
    finding = evaluate(data)[0]
    assert finding.status == "unknown"
    assert finding.numbers["kernel_unavailable"] is True


@pytest.mark.parametrize("axis,keep", [("q", "below"), ("y", "left")])
def test_saw_plane_schema_rejects_invalid_axis_or_side(axis, keep):
    with pytest.raises(ValidationError):
        Operation.model_validate(
            {"do": "saw_cut", "cut_plane": {"axis": axis, "value": 87, "keep": keep}}
        )


def test_blade_kerf_cannot_be_authored_in_two_units():
    with pytest.raises(ValidationError, match="author one length twice"):
        Inventory.model_validate(
            {"tools": {"blade": {"kind": "bandsaw", "kerf_mm": 1.5, "kerf_in": 0.06}}}
        )


@pytest.mark.parametrize("action", ["saw_cut", "cut_off"])
def test_saw_stock_cut_does_not_need_a_finished_feature_claim(tmp_path, action):
    plan = (
        PLAN.replace('do = "inspect"', f'do = "{action}"')
        .replace('feature = "subject"\n', "")
        .replace('checks = "unknown"\n', "")
    )
    data = load_bundle(bundle_files(tmp_path, plan))
    object.__setattr__(data, "kernel", bundle().kernel)
    assert evaluate(data)[0].status == "unknown"


@pytest.mark.parametrize("action", ["face", "drill"])
def test_machining_still_requires_a_manifest_feature(tmp_path, action):
    plan = PLAN.replace('do = "inspect"', f'do = "{action}"').replace('feature = "subject"\n', "")
    with pytest.raises(BadInput, match="feature is not in the manifest"):
        load_bundle(bundle_files(tmp_path, plan))


def test_unclaimed_saw_cannot_silently_drop_inspection_requirements(tmp_path):
    plan = PLAN.replace('do = "inspect"', 'do = "saw_cut"').replace('feature = "subject"\n', "")
    with pytest.raises(BadInput, match="inspection checks need a manifest feature"):
        load_bundle(bundle_files(tmp_path, plan))
